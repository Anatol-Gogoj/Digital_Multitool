#!/usr/bin/env python3
"""Static check: no function rebinds an imported name locally, and no
function reads one before its own local import of it (#474, the bug
class behind #468).

#468: arb_editor.ArbWaveformEditor._build_ui named a local Combobox `uc`.
A binding anywhere in a function makes that name local to the WHOLE
function, so the earlier `uc.TEXT_MUTED` (meant: the ui_colors alias)
read an unbound local and raised UnboundLocalError. No suite built that
window, so it shipped. This suite finds the same shape in the app's
modules and in the bench, manual and demo scripts (SCANNED below) by
parsing them with `ast`. It imports none of them, so it needs no display.

What is checked. For each function (def, async def, lambda) it takes the
names the module imports at module level (a module-level try or if
included) and the names the function makes local: a parameter,
assignment, augmented or annotated assignment, a bare annotation, `for`
target, `with ... as`, `except ... as`, a local import, a walrus, a
nested def or class, a match capture, `del`. `global` and `nonlocal`
exempt a name, because the function then does not own it. Comprehension
targets stay inside the comprehension; a walrus inside one binds in the
enclosing function, as in Python. For a name that is both imported and
local, the function FAILS when:
  1. it makes the name local by anything but an import (a parameter or
     a bare annotation included), in any order. Inside that function the
     name is then never the module: `uc = Combobox()` breaks a
     `uc.TEXT_MUTED` above it (UnboundLocalError) and below it
     (AttributeError) alike, and inside an `if` it breaks a read below
     the `if` whichever way the `if` went.
  2. it re-imports the name locally (`import os` inside the function)
     but reads it before that import. A local re-import placed above its
     reads is fine; main has seven.
`del` alone is no binding: a `del` with no binding before it is a read
of an unbound local, and fails by rule 2.

"Before" in rule 2 means evaluation order along one straight path
through the function body: an assignment's value before its targets, a
`for` iterable before its target, a `with` expression before its `as`
name, the read in `x += 1` before the write, a comprehension's first
iterable in the enclosing function, decorators and defaults before the
def binds its name. A read inside a nested function, lambda or class body
counts where that scope is written, since it sees the enclosing local
and not the module import.

Known blind spots of rule 2. The order is source order, not control flow:
  * Branches: a local import in one arm of an `if` or `try` counts as
    done for every later line.
  * Loops: a read above a local import in the same loop body fails even
    when it only runs on later passes, after the import; a read below an
    import that runs on only some passes is taken as safe.
  * A nested function or lambda written above the local import and read
    from there is flagged even if it is only called after the import, so
    it would work. The message says so; moving the import up fixes it.
  * A generator expression counts where it is written, like the other
    comprehensions, although its body runs only when it is consumed.
  * A read after a `del` of a locally re-imported name is not caught.
  * Annotations count as reads, even where Python never evaluates them.
    That is the strict side; none on main trips it.
And of both rules:
  * A local import is taken to be the same module as the module-level
    one: `import other as uc` inside a function is not compared.
  * Only names imported at module level are checked. A module constant
    or a builtin shadowed the same way is not, and `from x import *`
    names are unknown.

Run: .venv/bin/python tests/test_no_shadowed_imports.py
Scan given files instead of the repo (the mutation check uses this):
     .venv/bin/python tests/test_no_shadowed_imports.py FILE...
"""
import ast
import glob
import os
import sys
import tokenize
from collections import namedtuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Event kinds, recorded per scope in evaluation order.
READ = 'read'
BIND = 'bind'
# a walrus target inside a comprehension: it binds in the enclosing scope
OUTER = 'outer'
# a read from inside a class's methods or comprehensions: the class scope
# is invisible to them, so it passes through the class untouched
THROUGH = 'through'

# A module-level import name that one function makes local. bind_line and
# how are its first local binding; bind_line is None when nothing binds
# it (only a `del` or a bare annotation makes it local). rebinds holds
# (line, how) for every way the function makes it local other than an
# import (rule 1); early_reads holds (line, how) for every read before the
# first binding (rule 2). The shadow fails when either is not empty.
Shadow = namedtuple(
    'Shadow',
    'path func name bind_line how import_line early_reads rebinds')


class _Scope:
    """One Python scope: what it reads and binds, in evaluation order."""

    def __init__(self, kind):
        self.kind = kind            # module, function, class, comprehension
        self.events = []            # (kind, name, line, how)
        self.declared = set()       # named by `global` or `nonlocal`
        self.globals = set()        # named by `global`
        self.unbound_locals = {}    # name -> [(line, how)]: local, unbound

    def locals(self):
        bound = {e[1] for e in self.events if e[0] == BIND}
        return (bound | set(self.unbound_locals)) - self.declared


def _join(prefix, name):
    return f'{prefix}.{name}' if prefix else name


def _params(args):
    extra = [a for a in (args.vararg, args.kwarg) if a is not None]
    return args.posonlyargs + args.args + args.kwonlyargs + extra


class _Builder:
    """Walks one module and builds a _Scope for every function in it.

    The ast.NodeVisitor pattern, with the current scope, the qualname
    prefix and the binding kind (`how`) passed along. Node types without a
    visit_ method are walked child by child in field order, which is
    evaluation order for everything not special-cased here.
    """

    def __init__(self):
        self.functions = []         # (qualname, _Scope)

    def module(self, tree):
        scope = _Scope('module')
        for stmt in tree.body:
            self.visit(stmt, scope, '')
        return scope

    def function(self, node, qualname):
        scope = _Scope('function')
        for param in _params(node.args):
            scope.events.append((BIND, param.arg, param.lineno, 'parameter'))
        body = node.body if isinstance(node.body, list) else [node.body]
        for stmt in body:
            self.visit(stmt, scope, qualname + '.<locals>')
        self.functions.append((qualname, scope))
        return scope

    @staticmethod
    def hand_up(child, scope):
        """Give `scope` what `child` does to it, in order: the reads of
        names `child` does not own, and a comprehension's walrus binds."""
        own = child.locals()
        for kind, name, line, how in child.events:
            if kind == OUTER:
                up = OUTER if scope.kind == 'comprehension' else BIND
                scope.events.append((up, name, line, how))
            elif kind == THROUGH or (kind == READ and name not in own
                                     and name not in child.globals):
                up = THROUGH if scope.kind == 'class' else READ
                scope.events.append((up, name, line, 'nested'))

    def visit(self, node, scope, prefix, how='assignment'):
        method = getattr(self, 'visit_' + type(node).__name__, None)
        if method is not None:
            method(node, scope, prefix, how)
            return
        for child in ast.iter_child_nodes(node):
            self.visit(child, scope, prefix, how)

    def visit_Name(self, node, scope, prefix, how):
        if isinstance(node.ctx, ast.Load):
            scope.events.append((READ, node.id, node.lineno, 'read'))
        elif isinstance(node.ctx, ast.Store):
            scope.events.append((BIND, node.id, node.lineno, how))
        else:
            # `del x` needs x bound, and makes x local without binding it
            scope.events.append((READ, node.id, node.lineno, 'del'))
            scope.unbound_locals.setdefault(node.id, []).append(
                (node.lineno, 'del'))

    def visit_FunctionDef(self, node, scope, prefix, how):
        # decorators, defaults and annotations run here, before the def
        # binds its name; the body runs later, in its own scope
        args = node.args
        first = (node.decorator_list + args.defaults
                 + [d for d in args.kw_defaults if d is not None]
                 + [p.annotation for p in _params(args) if p.annotation]
                 + [r for r in [node.returns] if r is not None])
        for expr in first:
            self.visit(expr, scope, prefix)
        child = self.function(node, _join(prefix, node.name))
        scope.events.append((BIND, node.name, node.lineno, 'def'))
        self.hand_up(child, scope)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node, scope, prefix, how):
        args = node.args
        for expr in args.defaults + [d for d in args.kw_defaults if d]:
            self.visit(expr, scope, prefix)
        self.hand_up(self.function(node, _join(prefix, '<lambda>')), scope)

    def visit_ClassDef(self, node, scope, prefix, how):
        first = (node.decorator_list + node.bases
                 + [k.value for k in node.keywords])
        for expr in first:
            self.visit(expr, scope, prefix)
        body = _Scope('class')
        qualname = _join(prefix, node.name)
        for stmt in node.body:
            self.visit(stmt, body, qualname)
        self.hand_up(body, scope)
        scope.events.append((BIND, node.name, node.lineno, 'class'))

    def visit_ListComp(self, node, scope, prefix, how):
        # the first iterable runs in the enclosing scope; the rest runs in
        # the comprehension's own scope, and its targets stay there
        scope_iter = node.generators[0].iter
        self.visit(scope_iter, scope, prefix)
        comp = _Scope('comprehension')
        for gen in node.generators:
            if gen.iter is not scope_iter:
                self.visit(gen.iter, comp, prefix)
            self.visit(gen.target, comp, prefix, 'comprehension target')
            for cond in gen.ifs:
                self.visit(cond, comp, prefix)
        if isinstance(node, ast.DictComp):
            parts = [node.key, node.value]
        else:
            parts = [node.elt]
        for part in parts:
            self.visit(part, comp, prefix)
        self.hand_up(comp, scope)

    visit_SetComp = visit_GeneratorExp = visit_DictComp = visit_ListComp

    def visit_NamedExpr(self, node, scope, prefix, how):
        self.visit(node.value, scope, prefix)
        kind = OUTER if scope.kind == 'comprehension' else BIND
        scope.events.append((kind, node.target.id, node.target.lineno,
                             'walrus'))

    def visit_Assign(self, node, scope, prefix, how):
        self.visit(node.value, scope, prefix)
        for target in node.targets:
            self.visit(target, scope, prefix, 'assignment')

    def visit_AugAssign(self, node, scope, prefix, how):
        # `x += v` reads x, then v, then binds x
        target = node.target
        if not isinstance(target, ast.Name):
            self.visit(target, scope, prefix)
            self.visit(node.value, scope, prefix)
            return
        scope.events.append((READ, target.id, target.lineno, 'read'))
        self.visit(node.value, scope, prefix)
        scope.events.append((BIND, target.id, target.lineno,
                             'augmented assignment'))

    def visit_AnnAssign(self, node, scope, prefix, how):
        if node.value is not None:
            self.visit(node.value, scope, prefix)
        self.visit(node.annotation, scope, prefix)
        target = node.target
        if not isinstance(target, ast.Name):
            self.visit(target, scope, prefix)
        elif node.value is not None:
            scope.events.append((BIND, target.id, target.lineno,
                                 'annotated assignment'))
        else:
            # a bare `x: int` makes x local without binding it
            scope.unbound_locals.setdefault(target.id, []).append(
                (target.lineno, 'bare annotation'))

    def visit_For(self, node, scope, prefix, how):
        self.visit(node.iter, scope, prefix)
        self.visit(node.target, scope, prefix, 'for target')
        for stmt in node.body + node.orelse:
            self.visit(stmt, scope, prefix)

    visit_AsyncFor = visit_For

    def visit_With(self, node, scope, prefix, how):
        for item in node.items:
            self.visit(item.context_expr, scope, prefix)
            if item.optional_vars is not None:
                self.visit(item.optional_vars, scope, prefix, 'with ... as')
        for stmt in node.body:
            self.visit(stmt, scope, prefix)

    visit_AsyncWith = visit_With

    def visit_ExceptHandler(self, node, scope, prefix, how):
        if node.type is not None:
            self.visit(node.type, scope, prefix)
        if node.name:
            scope.events.append((BIND, node.name, node.lineno,
                                 'except ... as'))
        for stmt in node.body:
            self.visit(stmt, scope, prefix)

    def visit_Import(self, node, scope, prefix, how):
        for alias in node.names:
            if alias.name != '*':
                name = alias.asname or alias.name.split('.')[0]
                scope.events.append((BIND, name, node.lineno, 'import'))

    visit_ImportFrom = visit_Import

    def visit_Global(self, node, scope, prefix, how):
        scope.declared.update(node.names)
        scope.globals.update(node.names)

    def visit_Nonlocal(self, node, scope, prefix, how):
        scope.declared.update(node.names)

    # match statements (3.10+): the capture names are plain strings
    def visit_MatchAs(self, node, scope, prefix, how):
        if node.pattern is not None:
            self.visit(node.pattern, scope, prefix)
        if node.name:
            scope.events.append((BIND, node.name, node.lineno,
                                 'match capture'))

    def visit_MatchStar(self, node, scope, prefix, how):
        if node.name:
            scope.events.append((BIND, node.name, node.lineno,
                                 'match capture'))

    def visit_MatchMapping(self, node, scope, prefix, how):
        for part in node.keys + node.patterns:
            self.visit(part, scope, prefix)
        if node.rest:
            scope.events.append((BIND, node.rest, node.lineno,
                                 'match capture'))


def scan_source(source, path='<string>'):
    """Every module-level import name that a function in `source` makes
    local, as Shadow tuples in function order. Raises SyntaxError."""
    builder = _Builder()
    module = builder.module(ast.parse(source, filename=path))
    imports = {}
    for kind, name, line, how in module.events:
        if kind == BIND and how == 'import':
            imports.setdefault(name, line)
    shadows = []
    for qualname, scope in builder.functions:
        events = scope.events
        for name in sorted(scope.locals() & set(imports)):
            binds = [e for e in events if e[0] == BIND and e[1] == name]
            unbound = scope.unbound_locals.get(name, [])
            if binds:
                stop = events.index(binds[0])
                bind_line, how = binds[0][2], binds[0][3]
            else:
                stop = len(events)
                bind_line, how = None, unbound[0][1]
            early = tuple((e[2], e[3]) for e in events[:stop]
                          if e[0] == READ and e[1] == name)
            # rule 1: anything but an import, and a bare annotation, says
            # the name means something else here; a `del` binds nothing
            rebinds = tuple(sorted(
                [(e[2], e[3]) for e in binds if e[3] != 'import']
                + [u for u in unbound if u[1] == 'bare annotation']))
            shadows.append(Shadow(path, qualname, name, bind_line, how,
                                  imports[name], early, rebinds))
    return shadows


def scan_paths(paths):
    """(shadows, errors) over files; an error is a file that will not be
    read or parsed, which fails the suite too. A RecursionError (an
    expression nested deeper than the parser or this walk can follow) is
    one, so the failure still names its file."""
    shadows, errors = [], []
    for path in paths:
        shown = os.path.relpath(path, ROOT) if _inside(path) else path
        try:
            with tokenize.open(path) as handle:
                source = handle.read()
            shadows.extend(scan_source(source, shown))
        except (OSError, SyntaxError, UnicodeDecodeError,
                RecursionError) as exc:
            errors.append(f'{shown}: {type(exc).__name__}: {exc}')
    return shadows, errors


def _inside(path):
    full = os.path.abspath(path)
    try:
        return os.path.commonpath([full, ROOT]) == ROOT
    except ValueError:          # another drive, on Windows
        return False


# What the suite scans, relative to the repo root: the app's modules, and
# the bench, manual and demo scripts that no suite runs, which is where
# this bug hides longest. Not recursive, so a venv or build tree dropped
# in one of these folders is never walked. tests/ is left out: a suite
# runs its own functions, so the bug already fails there, and parsing
# tests/ too more than doubled the time (0.6 s to 1.4 s on 2026-10-20).
SCANNED = ('*.py', 'bench/*.py', 'bench/archive/*.py', 'demos/*.py',
           'docs/manual-src/*.py')


def repo_files():
    files = []
    for pattern in SCANNED:
        files.extend(sorted(glob.glob(os.path.join(ROOT, pattern))))
    return files


def _lines(pairs, skip=()):
    """The distinct line numbers of (line, how) pairs, in order, as text."""
    out = []
    for line, _how in pairs:
        if line not in out and line not in skip:
            out.append(line)
    return ', '.join(str(line) for line in out)


def describe(shadow):
    """The failure message for a failing shadow."""
    name = repr(shadow.name)
    imported = f'the module imports {name} at line {shadow.import_line}'
    if shadow.rebinds:
        # rule 1: the name means something else in this function
        line, how = shadow.rebinds[0]
        text = (f'{shadow.path}:{line}: {shadow.func} makes {name} a local '
                f'at line {line} ({how}), but {imported}. A local binding '
                f'covers the whole function, so no line of it sees the '
                f'import: a read above line {line} raises '
                f'UnboundLocalError and a read below it gets the local '
                f'(the #468 bug). Rename the local.')
        more = _lines(shadow.rebinds, skip=(line,))
        if more:
            text += f' Also made local at line(s) {more}.'
        if shadow.early_reads:
            text += (f' Read before its first binding at line(s) '
                     f'{_lines(shadow.early_reads)}.')
        return text
    # rule 2: only local imports bind it, and a read comes first
    line, how = shadow.early_reads[0]
    if shadow.bind_line is None:
        text = (f'{shadow.path}:{line}: {shadow.func} reads or deletes '
                f'{name}, but a `del` makes it local to the whole function '
                f'and nothing binds it, so this raises UnboundLocalError; '
                f'{imported}.')
    elif how == 'nested':
        text = (f'{shadow.path}:{line}: {shadow.func} has a nested '
                f'function, lambda or class that reads {name} at line '
                f'{line}, above the local import at line '
                f'{shadow.bind_line}. It reads that local, not the module '
                f'import at line {shadow.import_line}, so it fails if it '
                f'runs before line {shadow.bind_line}; a nested def or '
                f'lambda called only after it works. Move the import above '
                f'line {line}.')
    else:
        text = (f'{shadow.path}:{line}: {shadow.func} reads {name} before '
                f'the local import at line {shadow.bind_line}. That import '
                f'makes {name} local to the whole function, so this read '
                f'raises UnboundLocalError instead of reaching the module '
                f'import at line {shadow.import_line}. Move the import '
                f'above line {line}.')
    more = _lines(shadow.early_reads, skip=(line,))
    if more:
        text += f' Also read early at line(s) {more}.'
    return text


def _failing(shadows):
    return [s for s in shadows if s.early_reads or s.rebinds]


# Self-tests: crafted sources with a known answer.


def _scan(source):
    return scan_source(source.lstrip('\n'), '<crafted>')


def _one_failure(source, func, name):
    shadows = _scan(source)
    bad = _failing(shadows)
    assert [(s.func, s.name) for s in bad] == [(func, name)], \
        (func, name, shadows)
    return bad[0]


SOURCE_468 = '''
import tkinter.ttk as ttk
import ui_colors as uc


class ArbWaveformEditor:
    def _build_ui(self, view):
        ttk.Label(view, text="Time unit:", foreground=uc.TEXT_MUTED)
        uc = ttk.Combobox(view, width=4, state='readonly')
        uc.pack()
'''


def test_468_shape_is_caught():
    bad = _one_failure(SOURCE_468, 'ArbWaveformEditor._build_ui', 'uc')
    assert bad.rebinds == ((8, 'assignment'),), bad
    assert bad.early_reads == ((7, 'read'),), bad
    assert (bad.bind_line, bad.how, bad.import_line) == \
        (8, 'assignment', 2), bad
    text = describe(bad)
    assert text.startswith('<crafted>:8: ArbWaveformEditor._build_ui '
                           "makes 'uc' a local at line 8 (assignment)"), text
    assert text.endswith('Read before its first binding at line(s) 7.'), \
        text


def test_468_fix_passes():
    fixed = SOURCE_468.replace('uc = ttk', 'unit_box = ttk').replace(
        'uc.pack', 'unit_box.pack')
    assert _scan(fixed) == [], _scan(fixed)


def test_a_read_after_the_rebinding_is_caught():
    # #468 with the lines the other way round: no UnboundLocalError, but
    # uc is the Combobox there, so uc.TEXT_MUTED is an AttributeError
    source = '''
import tkinter.ttk as ttk
import ui_colors as uc


class E:
    def _build_ui(self, view):
        uc = ttk.Combobox(view); uc.pack()
        ttk.Label(view, foreground=uc.TEXT_MUTED)
'''
    bad = _one_failure(source, 'E._build_ui', 'uc')
    assert (bad.rebinds, bad.early_reads) == \
        (((7, 'assignment'),), ()), bad


def test_a_rebinding_in_a_branch_is_caught():
    # one arm binds the Combobox; the read below the if breaks either way
    source = '''
import tkinter.ttk as ttk
import ui_colors as uc


class E:
    def _build_ui(self, view, show_units):
        if show_units:
            uc = ttk.Combobox(view)
            uc.pack()
        ttk.Label(view, foreground=uc.TEXT_MUTED)
'''
    bad = _one_failure(source, 'E._build_ui', 'uc')
    assert (bad.rebinds, bad.early_reads) == \
        (((8, 'assignment'),), ()), bad


def test_a_parameter_named_like_an_import_is_caught():
    source = 'import numpy as np\n\n\ndef f(np):\n    return np\n'
    bad = _one_failure(source, 'f', 'np')
    assert bad.rebinds == ((4, 'parameter'),), bad


# Every form below makes the imported name `np` local. Each one but a
# local import is rule 1 and fails wherever it stands. A local import
# fails only after a read (rule 2). `del` binds nothing, so it reads an
# unbound local and fails wherever it stands, by rule 2.
BINDING_FORMS = [
    ('np = 1', 'assignment'),
    ('np, other = 1, 2', 'assignment'),
    ('np += 1', 'augmented assignment'),
    ('np: int = 1', 'annotated assignment'),
    ('np: int', 'bare annotation'),
    ('for np in []:\n        pass', 'for target'),
    ('with open(__file__) as np:\n        pass', 'with ... as'),
    ('try:\n        pass\n    except ValueError as np:\n        pass',
     'except ... as'),
    ('import numpy as np', 'import'),
    ('from numpy import np', 'import'),
    ('if (np := 1):\n        pass', 'walrus'),
    ('rows = [(np := r) for r in range(3)]', 'walrus'),
    ('def np():\n        pass', 'def'),
    ('class np:\n        pass', 'class'),
    ('match 1:\n        case np:\n            pass', 'match capture'),
    ('del np', 'del'),
]


def test_every_binding_form_is_caught():
    for form, how in BINDING_FORMS:
        for read_first in (True, False):
            body = ['print(np.pi)', form]
            if not read_first:
                body.reverse()
            source = ('import numpy as np\n\n\ndef f():\n'
                      + ''.join(f'    {line}\n' for line in body))
            bad = _failing(_scan(source))
            case = (form, read_first, bad)
            if how == 'import' and not read_first:
                assert bad == [], case
                continue
            assert [(s.func, s.name) for s in bad] == [('f', 'np')], case
            shadow = bad[0]
            assert shadow.how == how, case
            if how in ('import', 'del'):
                assert shadow.rebinds == (), case
                assert shadow.early_reads, case
            else:
                assert shadow.rebinds[0][1] == how, case
            if read_first:
                assert shadow.early_reads[0] == (5, 'read'), case
            # `del` and a bare annotation make np local without binding it
            unbound = how in ('bare annotation', 'del')
            assert (shadow.bind_line is None) == unbound, case


def test_augmented_assignment_alone_is_caught():
    # `np += 1` reads np before it writes it, so it fails with no other read
    source = 'import numpy as np\n\n\ndef f():\n    np += 1\n'
    bad = _failing(_scan(source))
    assert [(s.early_reads, s.bind_line) for s in bad] == \
        [(((5, 'read'),), 5)], bad


def test_except_as_and_for_target_are_caught():
    source = '''
import os
import re


def find(text, paths):
    hit = re.match('a', text)
    try:
        hit.group(0)
    except AttributeError as re:
        pass
    base = os.getcwd()
    for os in paths:
        print(os, base)
'''
    shadows = _scan(source)
    bad = {s.name: s for s in _failing(shadows)}
    assert sorted(bad) == ['os', 're'], shadows
    assert (bad['re'].early_reads[0][0], bad['re'].bind_line,
            bad['re'].how) == (6, 9, 'except ... as'), bad['re']
    assert (bad['os'].early_reads[0][0], bad['os'].bind_line,
            bad['os'].how) == (11, 12, 'for target'), bad['os']


def test_evaluation_order_not_column_order():
    # the targets are written left of the reads, but run after them
    source = '''
import numpy as np
import os


def f(x):
    np = np.asarray(x)
    for os in os.listdir('.'):
        pass
    return np
'''
    bad = {s.name: s for s in _failing(_scan(source))}
    assert sorted(bad) == ['np', 'os'], bad
    assert bad['np'].early_reads == ((6, 'read'),), bad['np']
    assert bad['os'].early_reads == ((7, 'read'),), bad['os']


def test_local_import_before_reads_passes():
    # rule 2's good case, the shape of the seven local imports on main
    # (gui.py, sldea_edge_gui.py)
    source = '''
import numpy as np
import os
import re


def lan_reachable(host):
    import os
    return os.path.exists(host)


def render(card):
    import re
    import numpy as np
    pattern = re.compile('x')
    return np.asarray(card), pattern
'''
    shadows = _scan(source)
    assert _failing(shadows) == [], shadows
    # seen and passed, not missed: all three local imports are shadows
    seen = sorted((s.func, s.name, s.how) for s in shadows)
    assert seen == [('lan_reachable', 'os', 'import'),
                    ('render', 'np', 'import'),
                    ('render', 're', 'import')], seen


def test_global_and_nonlocal_pass():
    source = '''
import json
import ui_colors as uc


def set_theme(theme):
    global uc
    print(uc.TEXT_MUTED)
    uc = theme


def outer():
    import json

    def inner():
        nonlocal json
        print(json.dumps(1))
        json = None
    inner()
'''
    shadows = _scan(source)
    assert _failing(shadows) == [], shadows
    # outer's local import is a shadow that passes; set_theme and inner do
    # not own the name at all
    assert [(s.func, s.name) for s in shadows] == [('outer', 'json')], \
        shadows


def test_comprehension_targets_do_not_leak():
    source = '''
import numpy as np


def f(rows):
    first = np.asarray(rows[0])
    squares = [np * np for np in range(3)]
    keyed = {np: 1 for np in rows}
    total = sum(np for np in rows)
    nested = [[np for np in row] for row in rows]
    return np.concatenate([first, squares]), keyed, total, nested
'''
    assert _scan(source) == [], _scan(source)


def test_reads_in_nested_scopes_count():
    # rule 2: a nested scope written above the local import sees the
    # local, not the module import, so each of these reads is caught at
    # its own line. A comprehension's first iterable is the exception: it
    # runs in the function itself, so it is a plain read.
    readers = [
        ('cb = lambda: uc.TEXT_MUTED', 'nested'),
        ('def cb():\n        return uc.TEXT_MUTED', 'nested'),
        ('colors = [uc.TEXT_MUTED for _ in range(2)]', 'nested'),
        ('colors = [c for c in uc.ALL]', 'read'),
        ('class Box:\n        color = uc.TEXT_MUTED', 'nested'),
        ('class Box:\n        def color(self):\n'
         '            return uc.TEXT_MUTED', 'nested'),
    ]
    for reader, expected in readers:
        source = ('import ui_colors as uc\n\n\ndef build(view):\n'
                  f'    {reader}\n    import ui_colors as uc\n')
        bad = _failing(_scan(source))
        assert [(s.func, s.name) for s in bad] == [('build', 'uc')], \
            (reader, bad)
        assert bad[0].rebinds == (), (reader, bad)
        line, how = bad[0].early_reads[0]
        assert how == expected, (reader, bad)
        assert 'uc.' in source.splitlines()[line - 1], (reader, bad)


def test_nested_scopes_after_the_binding_pass():
    source = '''
import numpy as np


def f(rows):
    import numpy as np
    cb = lambda: np.zeros(2)

    def inner():
        return np.ones(2)
    return [np.asarray(r) for r in rows], cb, inner
'''
    shadows = _scan(source)
    assert _failing(shadows) == [], shadows
    assert [(s.func, s.name) for s in shadows] == [('f', 'np')], shadows


def test_a_nested_read_above_a_local_import_says_what_happens():
    # the known limit: g only runs after the import, so this works, but it
    # is flagged; the message says when it fails and how to fix it
    source = '''
import numpy as np


def f():
    def g():
        return np.pi
    import numpy as np
    return g()
'''
    bad = _one_failure(source, 'f', 'np')
    assert (bad.early_reads, bad.rebinds) == (((6, 'nested'),), ()), bad
    text = describe(bad)
    assert text.startswith("<crafted>:6: f has a nested function, lambda "
                           "or class that reads 'np' at line 6, above the "
                           "local import at line 7."), text
    assert 'fails if it runs before line 7' in text, text
    assert 'called only after it works' in text, text


def test_the_message_names_each_early_line_once():
    source = '''
import numpy as np


def f():
    print(np.pi, np.e)
    print(np.e, np.pi)
    import numpy as np
'''
    bad = _one_failure(source, 'f', 'np')
    assert [r[0] for r in bad.early_reads] == [5, 5, 6, 6], bad
    text = describe(bad)
    assert text.startswith("<crafted>:5: f reads 'np' before the local "
                           "import at line 7."), text
    assert text.endswith(' Also read early at line(s) 6.'), text
    one_line = describe(_one_failure(
        source.replace('    print(np.e, np.pi)\n', ''), 'f', 'np'))
    assert 'Also' not in one_line, one_line


def test_too_deep_a_file_is_an_error_that_names_it():
    import shutil
    import tempfile
    folder = tempfile.mkdtemp(prefix='shadow_scan_')
    try:
        path = os.path.join(folder, 'deep.py')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('total = ' + ' + '.join(['1'] * 5000) + '\n')
        shadows, errors = scan_paths([path])
        assert shadows == [], shadows
        assert len(errors) == 1 and errors[0].startswith(path + ': ') \
            and 'RecursionError' in errors[0], errors
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_a_class_scope_name_does_not_reach_methods():
    # a class attribute named like the import does not shadow it for the
    # methods (class scope is invisible to them), and a method that binds
    # the name itself is judged on its own
    source = '''
import numpy as np


class Plot:
    np = None

    def fine(self):
        return np.zeros(1)

    def broken(self):
        out = np.zeros(1)
        np = out
        return np
'''
    bad = _failing(_scan(source))
    assert [(s.func, s.name) for s in bad] == [('Plot.broken', 'np')], bad


def test_module_level_import_inside_try_counts():
    source = '''
try:
    import cv2
except ImportError:
    cv2 = None


def grab(cam):
    frame = cv2.imread(cam)
    cv2 = frame
    return cv2
'''
    bad = _failing(_scan(source))
    assert [(s.func, s.name) for s in bad] == [('grab', 'cv2')], bad


def test_repo_has_no_shadowed_imports():
    files = repo_files()
    names = {os.path.basename(p) for p in files}
    # the scan is not vacuous: it reached the modules it exists for
    assert {'arb_editor.py', 'gui.py', 'sldea_edge_gui.py'} <= names, names
    shadows, errors = scan_paths(files)
    assert not errors, '\n'.join(errors)
    bad = _failing(shadows)
    assert not bad, '\n' + '\n'.join(describe(s) for s in bad)
    print(f'    {len(files)} files, {len(shadows)} local re-imports of '
          f'imported names, each one above its reads')


def _cli(paths):
    shadows, errors = scan_paths(paths)
    bad = _failing(shadows)
    for text in errors + [describe(s) for s in bad]:
        print(text)
    print(f'{len(paths)} file(s), {len(shadows)} function(s) making an '
          f'imported name local, {len(bad)} failing, '
          f'{len(errors)} unparsed')
    return 1 if bad or errors else 0


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block; run_tests.py explains why.
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = []
    for fn in fns:
        try:
            fn()
        except Exception:
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
        print(f"ok  {fn.__name__}")
    if not failed:
        print(f"\n{len(fns)} tests passed")
        return 0
    head = f"{len(failed)} of {len(fns)} tests failed"
    print(f"\n{head}")
    for name, tb in failed:
        print(f"===== FAIL {name} =====")
        print(tb.rstrip('\n'))
    print(f"===== end {head} =====")
    return 1


if __name__ == '__main__':
    if sys.argv[1:]:
        raise SystemExit(_cli(sys.argv[1:]))
    raise SystemExit(_run())
