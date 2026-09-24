#!/usr/bin/env python3
"""Headless tests for the SLDEA run gate on Tools → Update Software and
its Restart now (no hardware; one real-Tk case, skipped without a display).

Update Software streams update_software.sh, then offers Restart now, which
re-execs the process with `os.execv`. Until 2026-09-24 nothing checked for
an SLDEA run. During a LIVE run the SG channel that drives the Trek (1 V =
1 kV at the DEA) is ON at the run's current offset, and `os.execv`
replaces the process at once: neither the run worker's finally-block
zeroing nor the window-close shutdown (`_on_app_close`) ever ran, so the
Trek stayed energized while the restarted app showed an idle SLDEA tab.
The owner's decision (2026-09-24): refuse, and send the operator to
■ Abort. What is pinned here:

* Restart now refuses during any SLDEA run -- LIVE, DRY, or one still
  stopping after ■ Abort -- with a warning that says which, and neither
  destroys the window nor re-execs;
* Update Software refuses to start during a run, before any other dialog;
* `_sldea_finished` releases both;
* with no run going, both behave exactly as before: Update asks its
  question, Restart destroys the window and re-execs with the same argv,
  and neither touches an instrument (Restart is not the window-close
  shutdown: outputs stay as they are, by the same decision);
* the real update dialog's Restart button asks at click time, not when
  the dialog was built, and parents its warning on the dialog (real Tk);
* every process-replacing call in the app modules asks the gate first.

Everything drives the REAL methods on a Tk-free stub app. `gui.messagebox`
is a recorder, and `gui.os` a stand-in whose execv records the call
instead of replacing this process -- a real execv here would re-run the
suite, forever.

Run: .venv/bin/python tests/test_update_restart_guard.py
"""
import ast as _ast
import contextlib as _contextlib
import glob as _glob
import os as _os
import sys as _sys
import threading as _threading
import time as _time
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _ROOT)

import gui  # noqa: E402

G = gui.InstrumentControlGUI
RESTART_REFUSED = 'Restart refused — SLDEA run in progress'
UPDATE_REFUSED = 'Update refused — SLDEA run in progress'
SCRIPT = '/mnt/shareDrive/_software/update_software.sh'
# The app's command line while a test runs: launch_gui.sh passes "$@"
# through, and a restart must keep every argument, not just the script.
ARGV = ['/home/lab/.cache/scpi_control/SCPI_Control/gui.py', '--an-arg']


class _Skip(Exception):
    """Raised by a case that cannot run here. Counted, never silent."""


class _OS:
    """gui's `os` for these tests. Everything forwards to the real module
    except execv, which records (path, argv). Any other exec* / _exit
    fails loudly rather than forwarding -- forwarded, it would replace
    this test process."""

    def __init__(self, events):
        self.execs = []
        self._events = events

    def execv(self, path, args):
        self._events.append('execv')
        self.execs.append((path, list(args)))

    def __getattr__(self, name):
        if name.startswith(('exec', 'spawn', '_exit', 'abort', 'kill')):
            raise AssertionError(f"gui called os.{name} -- not stubbed")
        return getattr(_os, name)


class _MB:
    """tkinter.messagebox stand-in: records (kind, title, message, kw) and
    answers questions by title. A question it has no answer for fails the
    test -- an unexpected dialog is a finding, not something to guess."""

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.calls = []

    def askyesno(self, title, message, **kw):
        self.calls.append(('askyesno', title, message, kw))
        if title not in self.answers:
            raise AssertionError(f"unexpected question: {title!r}")
        return self.answers[title]

    def _note(self, kind):
        def show(title, message, **kw):
            self.calls.append((kind, title, message, kw))
        return show

    def __getattr__(self, name):
        if name.startswith('show'):
            return self._note(name)
        raise AttributeError(name)


class _Instrument:
    """An instrument handle that nothing here may touch: any attribute
    read is recorded. Restart is not the window-close shutdown, so it must
    leave every output exactly as it is -- not even a read."""

    def __init__(self):
        self.__dict__['touched'] = []

    def __getattr__(self, name):
        self.touched.append(name)
        return lambda *a, **k: None


class _Root:
    """Tk root stand-in: records destroy() on the shared timeline."""

    def __init__(self, events, fail=False):
        self.destroyed = False
        self._events = events
        self._fail = fail

    def destroy(self):
        self._events.append('destroy')
        if self._fail:
            raise gui.tk.TclError("can't invoke \"destroy\" command")
        self.destroyed = True


class _Widget:
    """Label / button stand-in: records the last config()."""

    def __init__(self):
        self.cfg = None

    def config(self, **kw):
        self.cfg = kw


class _App:
    """Just enough app for the updater and the run gate: the real methods
    under test, stubs for Tk and the instruments.

    `run` is None (no run), 'dry', or the SG channel of a LIVE run --
    set the way sldea_run sets it: `_sldea_running` True, and
    `_sldea_live_ch` the driven channel for LIVE, None for DRY."""
    open_update_software = G.open_update_software
    _restart_app = G._restart_app
    _sldea_run_blocks = G._sldea_run_blocks
    _sldea_finished = G._sldea_finished
    # Never called by the code under test. Bound so that a restart turned
    # into the window-close shutdown fails as touched instruments -- what
    # it would really do -- rather than as a missing method.
    _on_app_close = G._on_app_close

    def __init__(self, run=None, stopping=False, root=None):
        self.events = []
        self.root = _Root(self.events) if root is None else root
        self.lcr, self.scope, self.sg, self.psu, self.dmm = (
            _Instrument() for _ in range(5))
        self._updating = False
        self._sldea_running = run is not None
        self._sldea_live_ch = None if run in (None, 'dry') else run
        self._sldea_stop = stopping
        # what _sldea_finished tidies up when a run ends
        self._sldea_loglock = _threading.Lock()
        self._sldea_runlog = self._sldea_prelog = None
        self.sldea_run_btn, self.sldea_abort_btn = _Widget(), _Widget()
        self.status_bar = _Widget()
        self.lookups = 0

    def _find_update_script(self):
        self.lookups += 1
        return SCRIPT

    def touched(self):
        """{instrument: [attributes read]} for every instrument touched."""
        return {k: getattr(self, k).touched
                for k in ('lcr', 'scope', 'sg', 'psu', 'dmm')
                if getattr(self, k).touched}


@_contextlib.contextmanager
def _patched(mb, events):
    """The messagebox recorder and the os stand-in, in gui only, and the
    app's command line as ARGV."""
    fake_os = _OS(events)
    saved = (gui.messagebox, gui.os, _sys.argv)
    gui.messagebox, gui.os, _sys.argv = mb, fake_os, list(ARGV)
    try:
        assert gui.os is fake_os      # never reach a real execv
        yield fake_os
    finally:
        gui.messagebox, gui.os, _sys.argv = saved


def _one_warning(mb, title):
    """Exactly one dialog, a warning with `title`: -> (message, kw)."""
    [(kind, got, msg, kw)] = mb.calls
    assert (kind, got) == ('showwarning', title), mb.calls
    return msg, kw


def _refused(app, fake_os):
    """Nothing happened: no re-exec, the window stands, no instrument
    touched, no update started."""
    assert fake_os.execs == [], fake_os.execs
    assert app.events == [], app.events
    assert not app.root.destroyed
    assert not app.touched(), app.touched()
    assert app._updating is False


def _reexeced(app, fake_os):
    """The unchanged restart: destroy, THEN execv of the same command."""
    assert app.events == ['destroy', 'execv'], app.events
    assert fake_os.execs == [(_sys.executable,
                              [_sys.executable] + ARGV)], fake_os.execs


# --------------------------------------------------------------------------
# Restart now
# --------------------------------------------------------------------------

def test_restart_is_refused_during_a_live_run():
    app = _App(run=1)
    mb = _MB()
    with _patched(mb, app.events) as fake_os:
        app._restart_app()
    _refused(app, fake_os)
    msg, kw = _one_warning(mb, RESTART_REFUSED)
    assert 'LIVE HV run is driving the Trek on SG CH1' in msg, msg
    assert 'stop the run from ramping down, leaving the Trek energized' in msg, msg
    assert '■ Abort' in msg and 'press Restart now again' in msg, msg
    assert kw == {}, kw


def test_restart_is_refused_during_a_dry_run():
    """A DRY run drives nothing, so the note must not claim the Trek is
    live -- but a restart would still cut the run off mid-folder."""
    app = _App(run='dry')
    mb = _MB()
    with _patched(mb, app.events) as fake_os:
        app._restart_app()
    _refused(app, fake_os)
    msg, _ = _one_warning(mb, RESTART_REFUSED)
    assert 'A DRY run is in progress' in msg, msg
    assert 'before it closes its run folder' in msg, msg
    assert 'Trek' not in msg and 'SG CH' not in msg, msg
    assert '■ Abort' in msg, msg


def test_restart_is_refused_while_a_run_is_still_stopping():
    """■ Abort only sets _sldea_stop. Until the worker has zeroed the SG
    and _sldea_finished has run, the run is still going."""
    for run, says in ((2, 'The LIVE HV run on SG CH2 is still stopping. '
                          'It sets the SG to 0 V and switches it off'),
                      ('dry', 'The DRY run is still stopping.')):
        app = _App(run=run, stopping=True)
        mb = _MB()
        with _patched(mb, app.events) as fake_os:
            app._restart_app()
        _refused(app, fake_os)
        msg, _ = _one_warning(mb, RESTART_REFUSED)
        assert says in msg, msg
        assert 'Wait until ▶ Run is available again' in msg, msg
        assert '■ Abort' not in msg, "it was aborted already"


def test_the_warning_goes_to_the_window_that_asked():
    """The update dialog passes itself; a bare call gets root's."""
    app = _App(run=1)
    mb = _MB()
    dialog = object()
    with _patched(mb, app.events) as fake_os:
        app._restart_app(parent=dialog)
    _refused(app, fake_os)
    _, kw = _one_warning(mb, RESTART_REFUSED)
    assert kw == {'parent': dialog}, kw


def test_the_run_finishing_opens_the_gate():
    """_sldea_finished runs on the Tk side once the worker has zeroed the
    SG; from then on Restart works again, without a second warning."""
    app = _App(run=1)
    mb = _MB()
    with _patched(mb, app.events) as fake_os:
        app._restart_app()
        _refused(app, fake_os)
        app._sldea_finished()
        assert not app._sldea_running and app._sldea_live_ch is None
        app._restart_app()
    _reexeced(app, fake_os)
    assert len(mb.calls) == 1, mb.calls


def test_restart_with_no_run_is_unchanged():
    """No run: no dialog, the window goes, the same command is re-exec'd,
    and no instrument is touched -- outputs stay exactly as they are."""
    app = _App(run=None)
    mb = _MB()
    with _patched(mb, app.events) as fake_os:
        app._restart_app()
    _reexeced(app, fake_os)
    assert mb.calls == [], mb.calls
    assert not app.touched(), app.touched()


def test_restart_still_re_execs_when_the_window_is_already_gone():
    """Unchanged: a destroy() that raises does not stop the re-exec."""
    app = _App(run=None)
    app.root = _Root(app.events, fail=True)
    mb = _MB()
    with _patched(mb, app.events) as fake_os:
        app._restart_app()
    _reexeced(app, fake_os)
    assert mb.calls == [], mb.calls


# --------------------------------------------------------------------------
# Update Software
# --------------------------------------------------------------------------

def test_update_is_refused_during_a_run():
    """Refused before anything else: no script lookup, no question, no
    dialog, nothing marked as updating."""
    for run, stopping, says in (
            (1, False, 'LIVE HV run is driving the Trek on SG CH1'),
            ('dry', False, 'A DRY run is in progress'),
            (2, True, 'The LIVE HV run on SG CH2 is still stopping')):
        app = _App(run=run, stopping=stopping)
        mb = _MB()
        with _patched(mb, app.events) as fake_os:
            app.open_update_software()
        _refused(app, fake_os)
        assert app.lookups == 0, "refused before the script lookup"
        assert app.status_bar.cfg is None, app.status_bar.cfg
        msg, kw = _one_warning(mb, UPDATE_REFUSED)
        assert says in msg, msg
        assert 'Update after the run ends' in msg, msg
        assert 'Tools → Update Software… again' in msg, msg
        assert kw == {}, kw


def test_update_with_no_run_asks_as_before():
    """No run: straight on to the script lookup and the usual question
    (declined here, so no Tk window is needed)."""
    app = _App(run=None)
    mb = _MB({'Update Software': False})
    with _patched(mb, app.events) as fake_os:
        app.open_update_software()
    assert [(k, t) for k, t, _, _ in mb.calls] == [
        ('askyesno', 'Update Software')], mb.calls
    assert app.lookups == 1
    assert fake_os.execs == [] and app._updating is False
    assert not app.touched(), app.touched()


def test_update_after_the_run_finishes_is_allowed_again():
    app = _App(run='dry')
    mb = _MB({'Update Software': False})
    with _patched(mb, app.events):
        app.open_update_software()
        app._sldea_finished()
        app.open_update_software()
    assert [(k, t) for k, t, _, _ in mb.calls] == [
        ('showwarning', UPDATE_REFUSED),
        ('askyesno', 'Update Software')], mb.calls
    assert app.lookups == 1


# --------------------------------------------------------------------------
# The real update dialog (real Tk)
# --------------------------------------------------------------------------

class _TkApp(_App):
    """_App on a real Tk root, with an update 'script' that succeeds at
    once -- nothing is run."""
    _drain_update_queue = G._drain_update_queue
    _append_update_text = G._append_update_text

    def _update_worker(self, script, q):
        q.put(('line', 'fake update\n'))
        q.put(('done', 0))


def _find(widget, cls, **cfg):
    """The descendants of `widget` that are `cls` with every cget match."""
    out = []
    for w in widget.winfo_children():
        if isinstance(w, cls) and all(w.cget(k) == v for k, v in cfg.items()):
            out.append(w)
        out.extend(_find(w, cls, **cfg))
    return out


def test_the_real_restart_button_asks_at_click_time():
    """Build the real update dialog, let the fake update succeed, THEN
    start a LIVE run and press the real button: refused, with the warning
    over the dialog. After the run ends the same button restarts. On
    78315cc the button re-exec'd mid-run."""
    tk = gui.tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    try:
        root.withdraw()
        app = _TkApp(run=None, root=root)
        mb = _MB({'Update Software': True})
        with _patched(mb, app.events) as fake_os:
            app.open_update_software()
            [dialog] = _find(root, tk.Toplevel)
            [button] = _find(dialog, tk.Button, text='Restart now')
            deadline = _time.monotonic() + 10
            while str(button.cget('state')) != 'normal':
                assert _time.monotonic() < deadline, "update never finished"
                root.update()
                _time.sleep(0.01)
            assert app._updating is False
            assert [(k, t) for k, t, _, _ in mb.calls] == [
                ('askyesno', 'Update Software')], mb.calls
            mb.calls.clear()
            # the dialog is open and ready; now a LIVE run starts
            app._sldea_running, app._sldea_live_ch = True, 1
            button.invoke()
            assert fake_os.execs == [], "re-exec'd during a LIVE run"
            assert root.winfo_exists() and dialog.winfo_exists()
            assert not app.touched(), app.touched()
            msg, kw = _one_warning(mb, RESTART_REFUSED)
            assert 'SG CH1' in msg, msg
            assert kw == {'parent': dialog}, kw
            # the run ends; the same button now restarts
            app._sldea_finished()
            button.invoke()
            assert fake_os.execs == [(_sys.executable,
                                      [_sys.executable] + ARGV)]
            assert not app.touched(), app.touched()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass                      # the restart destroyed it already


# --------------------------------------------------------------------------
# Every process-replacing call asks the gate first
# --------------------------------------------------------------------------

# Calls that end this process without the window-close shutdown: a run's
# worker is a daemon thread and dies with it, finally block and all.
_ENDERS = ('exec', '_exit', 'abort')


def _process_enders(node):
    """os.exec*(), os._exit(), os.abort() calls under `node` -- spelled
    `os.<name>`, which is how the app spells them. An alias (`from os
    import execv`) is not seen: a tripwire, not a proof."""
    return [n for n in _ast.walk(node)
            if isinstance(n, _ast.Call)
            and isinstance(n.func, _ast.Attribute)
            and isinstance(n.func.value, _ast.Name)
            and n.func.value.id == 'os'
            and n.func.attr.startswith(_ENDERS)]


def _ender_sites(modules):
    """{'module.Class.method': its def} for every def that holds a process
    ender, charged to the OUTERMOST def around it (a nested callback
    counts as its method's). One at module level is charged to the
    module, with no def to check -- which fails the gate check below."""
    sites = {}

    def visit(body, prefix):
        for stmt in body:
            if isinstance(stmt, _ast.ClassDef):
                visit(stmt.body, f"{prefix}.{stmt.name}")
            elif isinstance(stmt, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                if _process_enders(stmt):
                    sites[f"{prefix}.{stmt.name}"] = stmt
            elif _process_enders(stmt):
                sites[prefix] = None

    for name, source in modules.items():
        visit(_ast.parse(source, name).body, name)
    return sites


def _asks_the_gate_first(fn):
    """True when `fn` has a top-level `if <x>._sldea_run_blocks(...): ...
    return` before the first top-level statement holding a process ender.
    A check nested in a branch, one that does not return, or one placed
    after the call does not count."""
    if fn is None:
        return False
    for stmt in fn.body:
        if (isinstance(stmt, _ast.If) and isinstance(stmt.test, _ast.Call)
                and isinstance(stmt.test.func, _ast.Attribute)
                and stmt.test.func.attr == '_sldea_run_blocks'
                and isinstance(stmt.body[-1], _ast.Return)):
            return True
        if _process_enders(stmt):
            return False
    return False


def _app_modules():
    """Every module at the repo root."""
    out = {}
    for path in sorted(_glob.glob(_os.path.join(_ROOT, '*.py'))):
        with open(path, encoding='utf-8') as f:
            out[_os.path.basename(path)[:-3]] = f.read()
    return out


def test_every_process_replacing_call_asks_the_gate_first():
    """Today there is exactly one: Restart now. A second restart path (a
    menu item, a crash handler that re-execs) fails here until it asks
    the gate too -- or is listed here with the reason it need not."""
    sites = _ender_sites(_app_modules())
    assert set(sites) == {'gui.InstrumentControlGUI._restart_app'}, (
        f"process-replacing calls found in {sorted(sites)}: a LIVE run's "
        f"worker dies with the process, zeroing and all. Ask "
        f"_sldea_run_blocks first, then list the site here.")
    for name, fn in sites.items():
        assert _asks_the_gate_first(fn), (
            f"{name} replaces the process without asking _sldea_run_blocks "
            f"in a top-level `if ...: return` first")


def test_the_gate_check_must_come_first_and_must_return():
    """Pin the scan on a module whose answer is known, so the check
    above can fail."""
    src = ("import os\n"
           "class C:\n"
           "    def ok(self):\n"
           "        '''doc'''\n"
           "        if self._sldea_run_blocks('restart'):\n"
           "            return\n"
           "        self.root.destroy()\n"
           "        os.execv('py', ['py'])\n"
           "    def late(self):\n"
           "        os.execv('py', ['py'])\n"
           "        if self._sldea_run_blocks('restart'):\n"
           "            return\n"
           "    def nested(self, x):\n"
           "        if x:\n"
           "            if self._sldea_run_blocks('restart'):\n"
           "                return\n"
           "        os.execl('py', 'py')\n"
           "    def no_return(self):\n"
           "        if self._sldea_run_blocks('restart'):\n"
           "            pass\n"
           "        os._exit(0)\n"
           "    def callback(self):\n"
           "        run = lambda: os.execvp('py', ['py'])\n"
           "    def harmless(self):\n"
           "        os.path.exists('x')\n"
           "        self.execv('not os')\n"
           "def module_level():\n"
           "    os.abort()\n"
           "os.execv('py', ['py'])\n")
    sites = _ender_sites({'m': src})
    verdict = {k: _asks_the_gate_first(v) for k, v in sites.items()}
    assert verdict == {'m.C.ok': True, 'm.C.late': False,
                       'm.C.nested': False, 'm.C.no_return': False,
                       'm.C.callback': False, 'm.module_level': False,
                       'm': False}, verdict


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    ran = skipped = 0
    failed = []
    for fn in fns:
        try:
            fn()
        except _Skip as why:
            skipped += 1
            print(f"skip {fn.__name__}  ({why})")
            continue
        except Exception:
            # A test that blew up still RAN -- only a skip is "did not run".
            ran += 1
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
        ran += 1
        print(f"ok  {fn.__name__}")
    tail = f"{ran} of {len(fns)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped, needs a display for Tk)"
    print(f"\n{tail}")
    if not failed:
        return 0
    head = f"{len(failed)} of {len(fns)} tests failed"
    print(f"\n{head}")
    for name, tb in failed:
        print(f"===== FAIL {name} =====")
        print(tb.rstrip('\n'))
    print(f"===== end {head} =====")
    return 1


if __name__ == '__main__':
    raise SystemExit(_run())
