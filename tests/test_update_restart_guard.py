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
* `_sldea_finished` releases both, including after an aborted run;
* the flag the gate reads is honest, on the REAL run worker: a LIVE run
  holds it until its SG has been set to 0 V and switched off -- when the
  run completes, is aborted, or loses its SG link -- and sldea_run claims
  it before it starts the worker;
* with no run going, both behave exactly as before: Update asks its
  question, Restart destroys the window and re-execs with the same argv,
  and neither touches an instrument (Restart is not the window-close
  shutdown: outputs stay as they are, by the same decision);
* except where the app runs from the share launcher's cache, or a
  launcher named itself in SCPI_LAUNCHER: there Restart re-execs `bash
  <launcher>` instead, so the cache is refreshed and the new version
  loads (2026-09-24; the rules are in tests/test_relaunch.py). Still the
  gate first, then destroy, then one execv;
* the update dialog's Restart button asks at click time, not when the
  dialog was built, and parents its warning on the dialog (real Tk, plus
  a source check that runs without a display);
* an inventory of every call that can end the bench app's process: a new
  one fails here until someone decides whether a run must block it.

Everything drives the REAL methods on a Tk-free stub app. `gui.messagebox`
is a recorder, and `gui.os` a stand-in whose execv records the call
instead of replacing this process -- a real execv here would re-run the
suite, forever.

Run: .venv/bin/python tests/test_update_restart_guard.py
"""
import ast as _ast
import collections as _collections
import contextlib as _contextlib
import glob as _glob
import os as _os
import queue as _queue
import shutil as _shutil
import sys as _sys
import tempfile as _tempfile
import threading as _threading
import time as _time
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _ROOT)

import gui  # noqa: E402
import relaunch  # noqa: E402

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
    # getattr so that, against code without the gate, the suite still
    # imports and fails test by test instead of not running at all
    _sldea_run_blocks = getattr(G, '_sldea_run_blocks', None)
    _sldea_finished = G._sldea_finished
    sldea_abort = G.sldea_abort
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
        self.log = []

    def _find_update_script(self):
        self.lookups += 1
        return SCRIPT

    def _sldea_log(self, msg):
        self.log.append(msg)

    def touched(self):
        """{instrument: [attributes read]} for every stand-in touched."""
        out = {}
        for k in ('lcr', 'scope', 'sg', 'psu', 'dmm'):
            seen = getattr(getattr(self, k), 'touched', None)
            if seen:
                out[k] = seen
        return out


@_contextlib.contextmanager
def _patched(mb, events):
    """The messagebox recorder and the os stand-in, in gui only, and the
    app's command line as ARGV. No launcher can be found -- no
    SCPI_LAUNCHER, and a share launcher that does not exist -- so the
    restart is the old one unless a test sets one up (_launcher)."""
    fake_os = _OS(events)
    saved = (gui.messagebox, gui.os, _sys.argv, relaunch.SHARE_LAUNCHER,
             _os.environ.pop(relaunch.LAUNCHER_ENV, None))
    gui.messagebox, gui.os, _sys.argv = mb, fake_os, list(ARGV)
    relaunch.SHARE_LAUNCHER = _os.path.join(_ROOT, 'no-such-dir',
                                            'launch_gui.sh')
    try:
        assert gui.os is fake_os      # never reach a real execv
        yield fake_os
    finally:
        (gui.messagebox, gui.os, _sys.argv, relaunch.SHARE_LAUNCHER,
         named) = saved
        _os.environ.pop(relaunch.LAUNCHER_ENV, None)
        if named is not None:
            _os.environ[relaunch.LAUNCHER_ENV] = named


@_contextlib.contextmanager
def _launcher(where):
    """Inside _patched: a launcher Restart must run again -> its path.

    'cache': the app runs from the share launcher's cache (gui.APP_DIR
    moved there, SCPI_CACHE pointing at it) and the share launcher exists.
    'named': a launcher exported SCPI_LAUNCHER; the app runs from here."""
    keys = ('SCPI_CACHE', relaunch.LAUNCHER_ENV)
    saved = (gui.APP_DIR, relaunch.SHARE_LAUNCHER,
             {k: _os.environ.get(k) for k in keys})
    with _tempfile.TemporaryDirectory() as tmp:
        launcher = _os.path.join(tmp, 'launch_gui.sh')
        with open(launcher, 'w') as f:
            f.write('#!/usr/bin/env bash\n')
        if where == 'cache':
            cache = _os.path.join(tmp, 'cache')
            gui.APP_DIR = _os.path.join(cache, 'SCPI_Control')
            _os.makedirs(gui.APP_DIR)
            _os.environ['SCPI_CACHE'] = cache
            relaunch.SHARE_LAUNCHER = launcher
        else:
            _os.environ[relaunch.LAUNCHER_ENV] = launcher
        try:
            yield launcher
        finally:
            gui.APP_DIR, relaunch.SHARE_LAUNCHER, env = saved
            for k, v in env.items():
                _os.environ.pop(k, None)
                if v is not None:
                    _os.environ[k] = v


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


def _bash():
    """The bash relaunch finds on this PATH, or a skip: the launcher
    restart needs one, and a machine without bash cannot show it."""
    bash = _shutil.which('bash', path=_os.environ.get('PATH'))
    if not bash:
        raise _Skip("no bash on PATH")
    return bash


def _relaunched(app, fake_os, launcher):
    """The restart through the launcher: destroy, THEN one execv of `bash
    <launcher>` with the app's arguments (launch_gui.sh passes "$@" on)."""
    assert app.events == ['destroy', 'execv'], app.events
    assert fake_os.execs == [(_bash(), ['bash', launcher] + ARGV[1:])], \
        fake_os.execs


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
    assert ('end the run before it can set the SG to 0 V and switch it '
            'off, leaving the Trek energized') in msg, msg
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
    assert 'Trek' not in msg and 'SG' not in msg, msg
    assert '■ Abort' in msg, msg


def test_restart_is_refused_while_a_run_is_still_stopping():
    """■ Abort only sets _sldea_stop. Until the worker has tried to zero
    the SG and _sldea_finished has run, the run is still going."""
    for run, says in ((2, 'The LIVE HV run on SG CH2 is still stopping.'),
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
    """_sldea_finished runs on the Tk side once the worker has tried to
    zero the SG; from then on Restart works again, with no second
    warning."""
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


def test_an_aborted_run_that_has_ended_no_longer_blocks():
    """_sldea_stop stays True after an aborted run ends -- only the next
    ▶ Run resets it -- so the gate must not read it on its own: after
    _sldea_finished, Update asks and Restart re-execs."""
    for run in (1, 'dry'):
        app = _App(run=run)
        mb = _MB({'Update Software': False})
        with _patched(mb, app.events) as fake_os:
            app.sldea_abort()                 # the real ■ Abort
            assert app._sldea_stop is True
            app._sldea_finished()
            assert app._sldea_stop is True, "reset only by the next run"
            app.open_update_software()
            app._restart_app()
        assert [(k, t) for k, t, _, _ in mb.calls] == [
            ('askyesno', 'Update Software')], mb.calls
        _reexeced(app, fake_os)


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


def test_restart_from_the_launcher_cache_runs_the_share_launcher():
    """The bench's case (2026-09-24): the app runs from the share
    launcher's cache, which only the launcher refreshes, so re-running the
    app's own command line reloaded the OLD code. Restart runs the
    launcher -- after destroy, one execv, no dialog, no instrument
    touched. A destroy() that raises still does not stop it."""
    for fail in (False, True):
        app = _App(run=None)
        app.root = _Root(app.events, fail=fail)
        mb = _MB()
        with _patched(mb, app.events) as fake_os, \
                _launcher('cache') as launcher:
            app._restart_app()
            _relaunched(app, fake_os, launcher)
        assert mb.calls == [], mb.calls
        assert not app.touched(), app.touched()


def test_restart_runs_a_launcher_that_named_itself():
    """A launcher that exports SCPI_LAUNCHER is run again, wherever the
    app runs from (here: the repo, which is no launcher's cache)."""
    app = _App(run=None)
    mb = _MB()
    with _patched(mb, app.events) as fake_os, \
            _launcher('named') as launcher:
        app._restart_app()
        _relaunched(app, fake_os, launcher)
    assert mb.calls == [], mb.calls


def test_the_launcher_restart_is_still_refused_during_a_run():
    """The gate comes first whatever Restart would run: during a LIVE run,
    DRY run or one still stopping, a launcher that is there changes
    nothing -- the same warning, no destroy, no exec."""
    for run, stopping in ((1, False), ('dry', False), (2, True)):
        for where in ('cache', 'named'):
            app = _App(run=run, stopping=stopping)
            mb = _MB()
            with _patched(mb, app.events) as fake_os, _launcher(where):
                app._restart_app()
            _refused(app, fake_os)
            _one_warning(mb, RESTART_REFUSED)


# --------------------------------------------------------------------------
# Update Software
# --------------------------------------------------------------------------

def test_update_is_refused_during_a_run():
    """Refused before anything else: no script lookup, no question, no
    dialog, nothing marked as updating -- and the note gives the owner's
    two reasons, not a restart the gate already prevents."""
    for run, stopping, says in (
            (1, False, 'LIVE HV run is driving the Trek on SG CH1'),
            ('dry', False, 'A DRY run is in progress'),
            (2, True, 'The LIVE HV run on SG CH2 is still stopping.')):
        app = _App(run=run, stopping=stopping)
        mb = _MB()
        with _patched(mb, app.events) as fake_os:
            app.open_update_software()
        _refused(app, fake_os)
        assert app.lookups == 0, "refused before the script lookup"
        assert app.status_bar.cfg is None, app.status_bar.cfg
        msg, kw = _one_warning(mb, UPDATE_REFUSED)
        assert says in msg, msg
        assert ('Update after the run ends: Restart now is refused until '
                'then anyway') in msg, msg
        assert 'shared drive the run may be saving to' in msg, msg
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
# The flag the gate reads, on the REAL run worker
# --------------------------------------------------------------------------

class _ZeroingSG:
    """BK4055B stand-in for the run worker. Every write goes on the shared
    timeline; the switch-off (set_output(ch, False), the last step of the
    worker's zeroing) blocks until the test releases it, so the test can
    act while the worker is still inside its finally. `fail_setup` makes
    the run's SG setup raise, as a dropped link would."""

    def __init__(self, timeline, fail_setup=False):
        self.timeline = timeline
        self.fail_setup = fail_setup
        self.zeroing = _threading.Event()
        self.release = _threading.Event()

    def set_load_polarity(self, ch, load=None, polarity=None):
        self.timeline.append(('sg', 'set_load_polarity', ch))

    def set_basic_wave(self, ch, **params):
        self.timeline.append(('sg', 'set_basic_wave', ch))
        if self.fail_setup:
            raise RuntimeError('SG link lost during setup')

    def set_offset(self, ch, v):
        self.timeline.append(('sg', 'set_offset', ch, v))

    def set_output(self, ch, on):
        self.timeline.append(('sg', 'set_output', ch, on))
        if not on:
            self.zeroing.set()
            self.release.wait(30)


class _AfterRoot(_Root):
    """Tk root stand-in for a worker thread: after() queues the callback,
    noting on the timeline when it is _sldea_finished; pump() runs the
    queue on the test's thread, as the Tk loop would."""

    def __init__(self, events, timeline):
        super().__init__(events)
        self.timeline = timeline
        self.queue = _queue.Queue()

    def after(self, ms, fn, *args):
        if getattr(fn, '__name__', '') == '_sldea_finished':
            self.timeline.append(('after', '_sldea_finished'))
        self.queue.put((fn, args))

    def pump(self):
        while True:
            try:
                fn, args = self.queue.get_nowait()
            except _queue.Empty:
                return
            fn(*args)


class _RunApp(_App):
    """_App plus what the real run worker needs. The SG is a _ZeroingSG;
    there is no scope and no camera."""
    SLDEA_POLL_S = G.SLDEA_POLL_S
    _sldea_worker = G._sldea_worker
    _sldea_capture = G._sldea_capture

    def __init__(self, sg, timeline):
        super().__init__(run=None)
        self.root = _AfterRoot(self.events, timeline)
        self.sg, self.scope = sg, None
        self._sldea_bd_tripped = False
        self._sldea_elapsed = 0.0

    def _sldea_set_status(self, text, fg='#555'):
        pass


@_contextlib.contextmanager
def _no_camera():
    saved = gui.webcam.resolve_camera

    def none(*_a, **_k):
        raise RuntimeError('no camera in this test')
    gui.webcam.resolve_camera = none
    try:
        yield
    finally:
        gui.webcam.resolve_camera = saved


def _live_run_through_its_zeroing(end):
    """Drive the REAL _sldea_worker as a LIVE run on SG CH1, ended by `end`
    -- 'complete' (the staircase runs out), 'abort' (the real ■ Abort) or
    'error' (the SG link fails during setup) -- and press Restart now and
    Update Software twice: while the worker is blocked inside its
    finally-block switch-off, and after the run has ended.

    -> dict: the flag, the dialogs and the re-execs at both moments, the
    timeline of SG writes and _sldea_finished being queued, and the log."""
    timeline = []
    sg = _ZeroingSG(timeline, fail_setup=(end == 'error'))
    app = _RunApp(sg, timeline)
    mb = _MB({'Update Software': False})
    # 0.8 s, two snapshots: short enough to run out in a test
    p = gui.SldeaProfile(start_kv=0.0, end_kv=0.5, step_kv=0.5, ramp_s=0.2,
                         landing_s=0.6, settle_s=0.1, snap_lead_s=0.1,
                         baseline=False)
    out = {}
    with _patched(mb, app.events) as fake_os, _no_camera(), \
            _tempfile.TemporaryDirectory() as tmp:
        # what sldea_run does on the Tk thread just before the worker starts
        app._sldea_stop = False
        app._sldea_running, app._sldea_live_ch = True, 1
        worker = _threading.Thread(
            target=app._sldea_worker,
            args=(p, tmp, 'run', 1, 2, 3, False), daemon=True)
        worker.start()
        try:
            if end == 'abort':
                _time.sleep(0.3)
                app.sldea_abort()
            assert sg.zeroing.wait(20), "the worker never reached its zeroing"
            _time.sleep(0.3)             # anything it would queue, queued
            app.root.pump()              # the Tk loop keeps running meanwhile
            out['running_while_zeroing'] = app._sldea_running
            app._restart_app()
            app.open_update_software()
            out['while_zeroing'] = ([(k, t) for k, t, _, _ in mb.calls],
                                    list(fake_os.execs), list(app.events))
            mb.calls.clear()
        finally:
            sg.release.set()
            worker.join(20)
        assert not worker.is_alive(), "the worker did not finish"
        app.root.pump()
        out['running_after'] = app._sldea_running
        app.open_update_software()
        app._restart_app()
        out['after'] = ([(k, t) for k, t, _, _ in mb.calls],
                        list(fake_os.execs), list(app.events))
    out['timeline'] = timeline
    out['log'] = app.log
    return out


def _check_the_gate_held(out, ended):
    assert any(f"run {ended}" in m or m.startswith(ended)
               for m in out['log']), (ended, out['log'])
    assert out['running_while_zeroing'] is True, (
        "_sldea_running cleared before the worker's zeroing finished -- "
        "Restart would re-exec with the Trek still live")
    assert out['while_zeroing'] == (
        [('showwarning', RESTART_REFUSED), ('showwarning', UPDATE_REFUSED)],
        [], []), out['while_zeroing']
    assert out['running_after'] is False
    assert out['after'] == (
        [('askyesno', 'Update Software')],
        [(_sys.executable, [_sys.executable] + ARGV)],
        ['destroy', 'execv']), out['after']
    tl = out['timeline']
    assert tl.count(('after', '_sldea_finished')) == 1, tl
    done = tl.index(('after', '_sldea_finished'))
    for step in (('sg', 'set_offset', 1, 0.0), ('sg', 'set_output', 1, False)):
        assert step in tl[:done], (
            f"_sldea_finished was queued before {step}: {tl}")


def test_a_live_run_holds_the_gate_until_its_sg_is_zeroed_when_it_completes():
    _check_the_gate_held(_live_run_through_its_zeroing('complete'),
                         'complete')


def test_a_live_run_holds_the_gate_until_its_sg_is_zeroed_when_aborted():
    _check_the_gate_held(_live_run_through_its_zeroing('abort'), 'aborted')


def test_a_live_run_holds_the_gate_until_its_sg_is_zeroed_when_it_fails():
    out = _live_run_through_its_zeroing('error')
    _check_the_gate_held(out, 'ERROR')
    assert ('sg', 'set_output', 1, True) not in out['timeline'], (
        "the setup failed before the output went on")


def _gui_tree():
    with open(_os.path.join(_ROOT, 'gui.py'), encoding='utf-8') as f:
        return _ast.parse(f.read(), 'gui.py')


def _find_def(tree, cls, name):
    [c] = [n for n in tree.body
           if isinstance(n, _ast.ClassDef) and n.name == cls]
    [fn] = [n for n in c.body
            if isinstance(n, _ast.FunctionDef) and n.name == name]
    return fn


def _blocks(node):
    """Every statement list under `node`: bodies, else and finally."""
    for n in _ast.walk(node):
        for field in ('body', 'orelse', 'finalbody'):
            block = getattr(n, field, None)
            if isinstance(block, list) and block \
                    and isinstance(block[0], _ast.stmt):
                yield block


def _is_worker_start(stmt):
    """`threading.Thread(target=self._sldea_worker, ...).start()`"""
    call = getattr(stmt, 'value', None)
    return (isinstance(stmt, _ast.Expr) and isinstance(call, _ast.Call)
            and isinstance(call.func, _ast.Attribute)
            and call.func.attr == 'start'
            and isinstance(call.func.value, _ast.Call)
            and any(k.arg == 'target'
                    and isinstance(k.value, _ast.Attribute)
                    and k.value.attr == '_sldea_worker'
                    for k in call.func.value.keywords))


def _is_claim(stmt):
    """`self._sldea_running = True`"""
    return (isinstance(stmt, _ast.Assign) and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], _ast.Attribute)
            and stmt.targets[0].attr == '_sldea_running'
            and isinstance(stmt.value, _ast.Constant)
            and stmt.value.value is True)


def _claims_before_start(fn):
    """True when `fn` starts the run worker exactly once, and claims the
    run (`_sldea_running = True`) earlier in that same block -- so no
    branch can start the worker without the claim."""
    starts = [(block, i) for block in _blocks(fn)
              for i, s in enumerate(block) if _is_worker_start(s)]
    if len(starts) != 1:
        return False
    block, at = starts[0]
    return any(_is_claim(s) for s in block[:at])


def test_sldea_run_claims_the_run_before_it_starts_the_worker():
    """The other half of the flag's contract. A claim made after start()
    would leave a moment where the worker writes the SG and the gate
    still sees no run. The check itself is shown to fail on a late
    claim and on a claim in another branch."""
    assert _claims_before_start(
        _find_def(_gui_tree(), 'InstrumentControlGUI', 'sldea_run'))
    late = _ast.parse(
        "def f(self):\n"
        "    threading.Thread(target=self._sldea_worker).start()\n"
        "    self._sldea_running = True\n").body[0]
    elsewhere = _ast.parse(
        "def f(self, x):\n"
        "    if x:\n"
        "        self._sldea_running = True\n"
        "    threading.Thread(target=self._sldea_worker).start()\n"
        ).body[0]
    assert not _claims_before_start(late)
    assert not _claims_before_start(elsewhere)


# --------------------------------------------------------------------------
# The real update dialog
# --------------------------------------------------------------------------

def test_the_restart_button_passes_its_dialog_as_the_parent():
    """Read from the source, so it is checked where there is no display:
    the Restart now button's command is `lambda:
    self._restart_app(parent=win)`, and `win` is the update dialog. The
    real-Tk test below proves the same wiring on a real button."""
    fn = _find_def(_gui_tree(), 'InstrumentControlGUI',
                   'open_update_software')
    [button] = [n for n in _ast.walk(fn) if isinstance(n, _ast.Call)
                and any(k.arg == 'text' and isinstance(k.value, _ast.Constant)
                        and k.value.value == 'Restart now'
                        for k in n.keywords)]
    [cmd] = [k.value for k in button.keywords if k.arg == 'command']
    assert isinstance(cmd, _ast.Lambda) and not cmd.args.args, \
        _ast.dump(cmd)
    call = cmd.body
    assert (isinstance(call, _ast.Call)
            and isinstance(call.func, _ast.Attribute)
            and call.func.attr == '_restart_app'), _ast.dump(call)
    parent = {k.arg: k.value for k in call.keywords}.get('parent')
    assert isinstance(parent, _ast.Name) and parent.id == 'win', \
        _ast.dump(call)
    [made] = [n.value for n in _ast.walk(fn) if isinstance(n, _ast.Assign)
              and any(isinstance(t, _ast.Name) and t.id == 'win'
                      for t in n.targets)]
    assert (isinstance(made, _ast.Call)
            and isinstance(made.func, _ast.Attribute)
            and made.func.attr == 'Toplevel'), _ast.dump(made)


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
# Inventory: every call that can end the bench app's process
# --------------------------------------------------------------------------

# Every site in the bench app's process that can end the process: its
# kind, why that is allowed, and what it does (ender -> count). The run
# worker is a daemon thread, so ending the process kills it wherever it
# is, before its finally block zeroes the SG. The scan below must find
# exactly this. A new site, or a new ender in a listed one, fails the
# suite: decide whether a run must block it, then list it. A 'gated' site
# must ask _sldea_run_blocks in a top-level `if ...: return` before the
# statement holding its first ender -- checked, not taken on trust.
PROCESS_ENDERS = {
    'gui.InstrumentControlGUI._restart_app': (
        'gated', 'Restart now: re-execs the app',
        {'root.destroy': 1, 'os.execv': 1}),
    'gui.InstrumentControlGUI._on_app_close': (
        'shutdown', 'window close: asks a running run to stop and waits '
                    'up to ~3 s for it, switches both SG outputs off, then '
                    'destroys the window',
        {'root.destroy': 1}),
    'gui:__main__': (
        'startup', 'the app failed to build, so no run can exist yet',
        {'root.destroy': 1, 'sys.exit': 1}),
    'sldea_tuner.TunerWindow._on_close': (
        'own process', "the tuner's own window. The bench app starts the "
                       "tuner as a separate process (Popen) and, in its own "
                       "process, only calls sldea_tuner.resolve_run",
        {'root.destroy': 1}),
}

_OS_ENDERS = ('exec', '_exit', 'abort')


def _root_like(node):
    """`root`, `self.root`, `app.root`, `self.app.root`: the spellings the
    app uses for the Tk root."""
    return ((isinstance(node, _ast.Name) and node.id == 'root')
            or (isinstance(node, _ast.Attribute) and node.attr == 'root'))


def _enders(node):
    """What under `node` can end the process, in source order: os.exec* /
    os._exit / os.abort and sys.exit, called or handed out; the same names
    imported from os or sys; `raise SystemExit`; the Tk root's destroy and
    any .quit (which ends the main loop), called or handed out as a
    callback. A tripwire for the spellings the app uses, not a proof: an
    alias under another name (`r = self.root; r.destroy()`), a widget's
    winfo_toplevel().destroy() and a getattr are not seen."""
    found = []
    for n in _ast.walk(node):
        what = None
        if isinstance(n, _ast.Attribute):
            owner = n.value
            if isinstance(owner, _ast.Name) and owner.id == 'os' \
                    and n.attr.startswith(_OS_ENDERS):
                what = f'os.{n.attr}'
            elif isinstance(owner, _ast.Name) and owner.id == 'sys' \
                    and n.attr == 'exit':
                what = 'sys.exit'
            elif n.attr == 'destroy' and _root_like(owner):
                what = 'root.destroy'
            elif n.attr == 'quit':
                what = '.quit'
        elif isinstance(n, _ast.Raise) and n.exc is not None:
            exc = n.exc.func if isinstance(n.exc, _ast.Call) else n.exc
            if isinstance(exc, _ast.Name) and exc.id == 'SystemExit':
                what = 'SystemExit'
        elif isinstance(n, _ast.ImportFrom) and n.level == 0:
            for a in n.names:
                if (n.module == 'os' and a.name.startswith(_OS_ENDERS)) or \
                        (n.module == 'sys' and a.name == 'exit'):
                    found.append((n.lineno, n.col_offset,
                                  f'from {n.module} import {a.name}'))
        if what:
            found.append((n.lineno, n.col_offset, what))
    return [what for _, _, what in sorted(found)]


def _is_main_guard(stmt):
    """`if __name__ == '__main__':`"""
    test = getattr(stmt, 'test', None)
    return (isinstance(stmt, _ast.If) and isinstance(test, _ast.Compare)
            and isinstance(test.left, _ast.Name)
            and test.left.id == '__name__'
            and any(isinstance(c, _ast.Constant) and c.value == '__main__'
                    for c in test.comparators))


def _ender_sites(modules, main):
    """({site: Counter(ender -> count)}, {site: its def}) for `modules`
    ({name: source}). An ender is charged to the OUTERMOST def around it
    (a callback or a nested worker counts as its method's). One at module
    level is charged to the module; one in `main`'s own `if __name__ ==
    '__main__':` block to 'main:__main__'. Every other module's main block
    is skipped: it runs only when that module is the program, never when
    the bench app imports it."""
    counts, defs = {}, {}

    def visit(body, prefix, module):
        for stmt in body:
            if isinstance(stmt, _ast.ClassDef):
                visit(stmt.body, f"{prefix}.{stmt.name}", module)
                continue
            owner = prefix
            if prefix == module and _is_main_guard(stmt):
                if module != main:
                    continue
                owner = f"{module}:__main__"
            elif isinstance(stmt, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                owner = f"{prefix}.{stmt.name}"
                defs[owner] = stmt
            found = _enders(stmt)
            if found:
                counts.setdefault(owner,
                                  _collections.Counter()).update(found)

    for name, source in modules.items():
        visit(_ast.parse(source, name).body, name, name)
    return counts, {k: v for k, v in defs.items() if k in counts}


def _asks_the_gate_first(fn):
    """True when `fn` has a top-level `if <x>._sldea_run_blocks(...): ...
    return` before the first top-level statement holding an ender. A
    check nested in a branch, one that does not return, or one placed
    after an ender does not count."""
    if fn is None:
        return False
    for stmt in fn.body:
        if (isinstance(stmt, _ast.If) and isinstance(stmt.test, _ast.Call)
                and isinstance(stmt.test.func, _ast.Attribute)
                and stmt.test.func.attr == '_sldea_run_blocks'
                and isinstance(stmt.body[-1], _ast.Return)):
            return True
        if _enders(stmt):
            return False
    return False


def _bench_app_modules():
    """gui.py and every repo-root module it imports, directly or through
    another, at module level or inside a function: the code that can run
    in the bench app's own process."""
    sources = {}
    for path in sorted(_glob.glob(_os.path.join(_ROOT, '*.py'))):
        with open(path, encoding='utf-8') as f:
            sources[_os.path.basename(path)[:-3]] = f.read()
    seen, todo = set(), ['gui']
    while todo:
        name = todo.pop()
        if name in seen or name not in sources:
            continue
        seen.add(name)
        for n in _ast.walk(_ast.parse(sources[name], name)):
            if isinstance(n, _ast.Import):
                todo.extend(a.name.split('.')[0] for a in n.names)
            elif isinstance(n, _ast.ImportFrom) and n.level == 0 \
                    and n.module:
                todo.append(n.module.split('.')[0])
    return {name: sources[name] for name in sorted(seen)}


def test_every_process_ender_in_the_bench_app_is_accounted_for():
    modules = _bench_app_modules()
    # the scope is computed, so check it reaches what it must
    assert {'gui', 'arb_editor', 'battery_tab', 'sldea_tuner'} \
        <= set(modules), sorted(modules)
    counts, _ = _ender_sites(modules, main='gui')
    found = {k: dict(v) for k, v in counts.items()}
    listed = {k: enders for k, (_, _, enders) in PROCESS_ENDERS.items()}
    new = {k: v for k, v in found.items() if k not in listed}
    assert not new, (
        f"process enders in unlisted places: {new}. A running SLDEA "
        f"worker dies with the process, before it zeroes the SG. Should a "
        f"run block this? Gate it with _sldea_run_blocks (or route it "
        f"through _on_app_close), test it above, then list it in "
        f"PROCESS_ENDERS.")
    gone = set(listed) - set(found)
    assert not gone, (
        f"listed in PROCESS_ENDERS but no longer ending the process: "
        f"{gone} -- moved or renamed? Re-check wherever it went.")
    changed = {k: {'found': found[k], 'listed': v}
               for k, v in listed.items() if k in found and found[k] != v}
    assert not changed, (
        f"the enders changed in: {changed}. A new ender in a listed place "
        f"is still new: check it against a running SLDEA run, then update "
        f"PROCESS_ENDERS.")


def test_every_gated_ender_asks_the_gate_first():
    _, defs = _ender_sites(_bench_app_modules(), main='gui')
    for name, (kind, _, _) in PROCESS_ENDERS.items():
        if kind == 'gated':
            assert _asks_the_gate_first(defs.get(name)), (
                f"{name} can end the process without asking "
                f"_sldea_run_blocks in a top-level `if ...: return` first")


def test_the_ender_scan_sees_the_spellings_it_claims():
    """Pin the scan on a module whose answer is known: every spelling
    `_enders` claims is caught, counted and charged to the right place,
    a callback included; a widget's own destroy and look-alike names are
    not enders; and only the program's own main block is in scope."""
    src = ("import os, sys\n"
           "from os import execv\n"
           "class A:\n"
           "    def restart(self):\n"
           "        if self._sldea_run_blocks('restart'):\n"
           "            return\n"
           "        self.root.destroy()\n"
           "        os.execv('py', ['py'])\n"
           "    def quit_item(self, menu):\n"
           "        menu.add_command(label='Quit',\n"
           "                         command=self.root.destroy)\n"
           "    def bail(self):\n"
           "        sys.exit(1)\n"
           "    def stop(self):\n"
           "        raise SystemExit('bye')\n"
           "    def leave_loop(self):\n"
           "        self.root.quit()\n"
           "    def close_editor(self):\n"
           "        self.destroy()\n"
           "        self.win.destroy()\n"
           "    def harmless(self):\n"
           "        os.path.exists('x')\n"
           "        self.execv('not os')\n"
           "def module_level():\n"
           "    os._exit(0)\n"
           "if __name__ == '__main__':\n"
           "    sys.exit(0)\n")
    counts, _ = _ender_sites({'m': src}, main='m')
    assert {k: dict(v) for k, v in counts.items()} == {
        'm': {'from os import execv': 1},
        'm.A.restart': {'root.destroy': 1, 'os.execv': 1},
        'm.A.quit_item': {'root.destroy': 1},
        'm.A.bail': {'sys.exit': 1},
        'm.A.stop': {'SystemExit': 1},
        'm.A.leave_loop': {'.quit': 1},
        'm.module_level': {'os._exit': 1},
        'm:__main__': {'sys.exit': 1}}, counts
    counts, _ = _ender_sites({'m': src}, main='gui')
    assert 'm:__main__' not in counts, "an imported module's main block"


def test_the_gate_check_must_come_first_and_must_return():
    src = ("import os\n"
           "class C:\n"
           "    def ok(self):\n"
           "        '''doc'''\n"
           "        if self._sldea_run_blocks('restart'):\n"
           "            return\n"
           "        self.root.destroy()\n"
           "        os.execv('py', ['py'])\n"
           "    def after_destroy(self):\n"
           "        self.root.destroy()\n"
           "        if self._sldea_run_blocks('restart'):\n"
           "            return\n"
           "        os.execv('py', ['py'])\n"
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
           "        run = lambda: os.execvp('py', ['py'])\n")
    _, defs = _ender_sites({'m': src}, main='m')
    verdict = {k.rsplit('.', 1)[1]: _asks_the_gate_first(v)
               for k, v in defs.items()}
    assert verdict == {'ok': True, 'after_destroy': False, 'nested': False,
                       'no_return': False, 'callback': False}, verdict


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
