#!/usr/bin/env python3
"""Static check: no function reads an imported name before it binds that
same name locally (#474, the bug class behind #468).

#468: arb_editor.ArbWaveformEditor._build_ui named a local Combobox `uc`.
A binding anywhere in a function makes that name local to the WHOLE
function, so the earlier `uc.TEXT_MUTED` (meant: the ui_colors alias)
read an unbound local and raised UnboundLocalError. No suite built that
window, so it shipped. This suite finds the same shape in the app's
modules and in the bench, manual and demo scripts (SCANNED below) by
parsing them with `ast`. It imports none of them, so it needs no display.

What is checked. For each function (def, async def, lambda) it takes the
names the module imports at module level (a module-level try or if
included) and the names the function binds itself: assignment, augmented
or annotated assignment, `for` target, `with ... as`, `except ... as`, a
local import, a walrus, a nested def or class, a match capture, `del`.
Parameters bind first. `global` and `nonlocal` exempt a name, because the
function then does not own it. Comprehension targets stay inside the
comprehension; a walrus inside one binds in the enclosing function, as in
Python. A name that is both imported and local FAILS when the function
reads it before its first local binding.

"Before" means evaluation order along one straight path through the
function body: an assignment's value before its targets, a `for` iterable
before its target, a `with` expression before its `as` name, the read in
`x += 1` before the write, a comprehension's first iterable in the
enclosing function, decorators and defaults before the def binds its
name. A read inside a nested function, lambda or class body counts where
that scope is written, since it sees the enclosing local and not the
module: `lambda: uc.TEXT_MUTED` above `uc = ...` is #468 again, deferred
to the click.

Known blind spots. The order is source order, not control flow:
  * Branches: a binding in one arm of an `if` or `try` counts as done for
    every later line. `if a: np = f()` then `np.x` passes, as does a read
    in an `except` handler of a name the `try` body binds late.
  * Loops: a read above a binding in the same loop body fails even when
    it only runs on later passes, after the binding; a read below a
    binding that runs on only some passes is taken as safe.
  * A generator expression counts where it is written, like the other
    comprehensions, although its body runs only when it is consumed.
  * Python deletes the name of `except E as name` when the handler ends;
    a read of it after the handler is not caught.
  * A read after the first binding is taken to mean the local. If that
    local is a different object from the module (a Combobox named `uc`),
    a later `uc.TEXT_MUTED` is an AttributeError this check cannot see.
  * Annotations count as reads, even where Python never evaluates them.
    That is the strict side; none on main trips it.
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

# One local binding of a module-level import name, in one function.
# early_reads holds (line, how) for every read before that binding; the
# shadow is a failure only when it is not empty. bind_line is None when
# the name is local only through `del` or a bare annotation.
Shadow = namedtuple(
    'Shadow', 'path func name bind_line how import_line early_reads')


class _Scope:
    """One Python scope: what it reads and binds, in evaluation order."""

    def __init__(self, kind):
        self.kind = kind            # module, function, class, comprehension
        self.events = []            # (kind, name, line, how)
        self.declared = set()       # named by `global` or `nonlocal`
        self.globals = set()        # named by `global`
        self.unbound_locals = {}    # name -> (line, how): local, never bound

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
            scope.unbound_locals.setdefault(node.id, (node.lineno, 'del'))

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
            scope.unbound_locals.setdefault(
                target.id, (target.lineno, 'bare annotation'))

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
    """Every local binding of a module-level import name in `source`, as
    Shadow tuples in function order. Raises SyntaxError."""
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
            binds = [i for i, e in enumerate(events)
                     if e[0] == BIND and e[1] == name]
            if binds:
                stop = binds[0]
                bind_line, how = events[stop][2], events[stop][3]
            else:
                stop = len(events)
                bind_line, how = None, scope.unbound_locals[name][1]
            early = tuple((e[2], e[3]) for e in events[:stop]
                          if e[0] == READ and e[1] == name)
            shadows.append(Shadow(path, qualname, name, bind_line, how,
                                  imports[name], early))
    return shadows


def scan_paths(paths):
    """(shadows, errors) over files; an error is a file that will not
    parse, which fails the suite too."""
    shadows, errors = [], []
    for path in paths:
        shown = os.path.relpath(path, ROOT) if _inside(path) else path
        try:
            with tokenize.open(path) as handle:
                source = handle.read()
            shadows.extend(scan_source(source, shown))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
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


def describe(shadow):
    """The failure line for a shadow with early reads."""
    line, how = shadow.early_reads[0]
    if shadow.bind_line is None:
        binding = f'is local through a {shadow.how} and never bound'
    else:
        binding = (f'is bound locally at line {shadow.bind_line} '
                   f'({shadow.how})')
    if how == 'nested':
        effect = ('this read, inside a nested function, lambda or class, '
                  'gets the local and not the import')
    else:
        effect = 'this read raises UnboundLocalError'
    more = ''
    if len(shadow.early_reads) > 1:
        rest = ', '.join(str(r[0]) for r in shadow.early_reads[1:])
        more = f' Also read early at line(s) {rest}.'
    return (f'{shadow.path}:{line}: {shadow.func} reads {shadow.name!r} '
            f'(imported at line {shadow.import_line}) before its first '
            f'local binding. {shadow.name!r} {binding}, which makes it '
            f'local to the whole function, so {effect} (the #468 bug).'
            f'{more}')


def _failing(shadows):
    return [s for s in shadows if s.early_reads]


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
    assert bad.early_reads == ((7, 'read'),), bad
    assert (bad.bind_line, bad.how, bad.import_line) == \
        (8, 'assignment', 2), bad
    text = describe(bad)
    assert text.startswith('<crafted>:7: ArbWaveformEditor._build_ui '
                           "reads 'uc'"), text


def test_468_fix_passes():
    fixed = SOURCE_468.replace('uc = ttk', 'unit_box = ttk').replace(
        'uc.pack', 'unit_box.pack')
    assert _scan(fixed) == [], _scan(fixed)


# Each binding form below, written after a read of the imported name `np`,
# must be caught, and named as the binding that shadows it.
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
    ('del np', 'del'),
]


def test_every_binding_form_is_caught():
    for form, how in BINDING_FORMS:
        source = ('import numpy as np\n\n\ndef f():\n'
                  f'    print(np.pi)\n    {form}\n')
        shadows = _scan(source)
        bad = _failing(shadows)
        assert [(s.func, s.name) for s in bad] == [('f', 'np')], \
            (form, shadows)
        assert bad[0].how == how, (form, bad)
        assert bad[0].early_reads[0] == (5, 'read'), (form, bad)
        # `del` and a bare annotation make np local without binding it
        unbound = how in ('bare annotation', 'del')
        assert (bad[0].bind_line is None) == unbound, (form, bad)


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
    # the shape of the six local imports on main (gui.py, sldea_edge_gui.py)
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
    # a nested scope written before the local binding sees the local, not
    # the import: each of these reads is caught at its own line. A
    # comprehension's first iterable is the exception that runs in the
    # function itself, so it is a plain read.
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
                  f'    {reader}\n    uc = view.combobox()\n')
        bad = _failing(_scan(source))
        assert [(s.func, s.name) for s in bad] == [('build', 'uc')], \
            (reader, bad)
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


def test_repo_has_no_shadowed_import_reads():
    files = repo_files()
    names = {os.path.basename(p) for p in files}
    # the scan is not vacuous: it reached the modules it exists for
    assert {'arb_editor.py', 'gui.py', 'sldea_edge_gui.py'} <= names, names
    shadows, errors = scan_paths(files)
    assert not errors, '\n'.join(errors)
    bad = _failing(shadows)
    assert not bad, '\n' + '\n'.join(describe(s) for s in bad)
    print(f'    {len(files)} files, {len(shadows)} local bindings of '
          f'imported names, each one before its reads')


def _cli(paths):
    shadows, errors = scan_paths(paths)
    bad = _failing(shadows)
    for text in errors + [describe(s) for s in bad]:
        print(text)
    print(f'{len(paths)} file(s), {len(shadows)} local binding(s) of '
          f'imported names, {len(bad)} read before binding, '
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
