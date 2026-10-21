#!/usr/bin/env python3
"""The SLDEA tab's launchers check that their program opened (#429).

Edge Review..., Tune params, Plot runs... and Video review... start
programs of their own. Each used to say "<program> opened on <run>" as soon
as Popen returned, so a program that died at once still read as opened,
and what it printed went to the bench app's own output. Pinned here:

* a program that exits at once with an error is said on the status bar
  and in a box, with its exit code, the last lines it printed (its
  traceback last, however much it printed before it) and the log they are
  in; during an SLDEA run the box waits for the run's end, so it can never
  stand between the operator and ■ Abort, and while one of the run's own
  alarms (HV NOT ZEROED) is open it waits for that too; exit code 0 is a
  normal close,
  said as "closed" with no box;
* a program that stays up reads "starting" until launch_check.CHECK_MS
  has passed, then "opened", unless something else has used the status
  bar meanwhile;
* the look goes on after "opened" (#473): a program that dies before
  launch_check.WATCH_MS is said the same way, once, and its box waits for
  a run too; one that closes normally then is not said; the window's
  close ends the look and lets go of the program;
* each look is one poll() on the Tk thread, and the launcher returns
  without waiting for its program;
* a healthy program starts as before: the same arguments, working folder
  and start_new_session, and the same environment but for
  PYTHONUNBUFFERED=1, with its stdout and stderr in a log file of its own,
  never a pipe;
* launch_check itself: the tail of a log, the sweep of old logs, a log
  that cannot be made (the program still starts), a Popen that raises,
  and a window that closes during the look.

The launcher cases start real child processes (`python -c ...`) in place
of the programs, through the launchers' own Popen keywords, and stop
every one through the Popen handle they hold. They need a Tk display and
skip cleanly without one.

A stand-in that exits at once is waited for (_exited) before Tk is
pumped, so the check's first look finds it gone. "At once" is not "within
CHECK_MS" on a busy Windows PC: there 36 of 1080 starts of the venv's
`python -c "sys.exit(3)"` lived 5.08 to 5.21 s by the OS's own process
times (the rest a median 0.14 s, none between 1 and 2 s), with under
0.1 s of CPU, and the 5 s came before Python's first import (Gogojster,
2026-10-19, #458). The check then saw such a stand-in running at CHECK_MS
and rightly said "opened", and these cases failed.

Run: .venv/bin/python tests/test_launch_check.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import gc
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

try:
    import launch_check
except ImportError:
    # main before #429 has no launch_check. The launcher cases still run
    # there, which is how the first one was shown to fail on 9e94274.
    launch_check = None

# A child that dies at once with a message on stderr, and one that stays.
DIES = [sys.executable, '-c',
        'import sys; sys.stderr.write("boom from the child\\n"); '
        'sys.exit(3)']
STAYS = [sys.executable, '-c', 'import time; time.sleep(60)']
PROBE_ENV = 'LAUNCH_CHECK_PROBE_429'
# ...one that says where it runs and what it was given, then stays
TELLS = [sys.executable, '-c',
         'import json, os, sys, time; '
         f'print(json.dumps([os.getcwd(), os.environ.get("{PROBE_ENV}"), '
         'os.environ.get("PYTHONUNBUFFERED")])); '
         'sys.stdout.flush(); time.sleep(60)']
# ...one that prints more lines than the tail holds, then raises: buffered,
# its prints reached the file at exit, after the traceback (#429 review)
CHATTY = [sys.executable, '-c',
          'import sys\nfor i in range(20): print("progress", i)\n'
          'raise RuntimeError("the real error")']
# ...one that closes normally at once
CLOSES = [sys.executable, '-c', 'import sys; sys.exit(0)']


def _waits(go):
    """...and one that runs until the file `go` exists, as a window that
    has read as opened (#473), then writes a line to stderr and exits
    with the code in that file (_go). It gives up after 300 s, so a test
    that died cannot leave it running for long."""
    return [sys.executable, '-c',
            'import os, sys, time\n'
            'end = time.time() + 300\n'
            'while not os.path.exists(sys.argv[1]) and time.time() < end:\n'
            '    time.sleep(0.05)\n'
            'sys.stderr.write("late boom from the child\\n")\n'
            'sys.exit(int(open(sys.argv[1]).read()) '
            'if os.path.exists(sys.argv[1]) else 9)', go]


def _go(go, code):
    """Tell the _waits(go) stand-ins to exit with `code`. The file appears
    whole (written beside it, then renamed), so none reads it half
    written."""
    part = go + '.part'
    with open(part, 'w') as f:
        f.write(str(code))
    os.replace(part, go)

# program -> (its script, the title of its boxes)
PROGRAMS = {
    'Edge Review': ('sldea_edge_gui.py', 'Edge Review'),
    'Edge tuner': ('sldea_tuner.py', 'Edge tuner'),
    'Plot window': ('sldea_plot_gui.py', 'SLDEA plot'),
    'Video review': ('sldea_video_review.py', 'Video review'),
}

# A look on the Tk thread must take less than this (wall time). A look is
# one proc.poll() and a clock read; the bound is loose for a PC busy with
# other suites, and still far under the POLL_MS a blocking wait would cost.
LOOK_MAX_S = 0.10

# How long a stand-in that exits at once may take to exit, or to print
# its first line: over ten times the 5.2 s measured on a busy Gogojster
# (#458). Longer than that is a failure, never a skip.
EXIT_WAIT_S = 60


class _Skip(Exception):
    """Raised by a case this PC cannot host: no Tk, or no display for it."""


# ---------------------------------------------------------------------------
# stand-ins
# ---------------------------------------------------------------------------

class _Swap:
    """Stands in for gui's subprocess module: starts `child` in place of
    the program the launcher asked for, with the launcher's own Popen
    keywords, and keeps every handle so the test can stop it."""

    def __init__(self, child):
        self.child = child
        self.calls, self.procs = [], []

    def Popen(self, cmd, **kw):
        self.calls.append((list(cmd), dict(kw)))
        proc = subprocess.Popen(self.child, **kw)
        self.procs.append(proc)
        return proc

    def stop(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
            try:
                p.wait(10)
            except Exception:
                pass


class _Boxes:
    """messagebox stand-in: records every box as (title, text)."""

    def __init__(self):
        self.infos, self.errors = [], []

    def showinfo(self, title=None, message=None, **k):
        self.infos.append((title, message))

    def showerror(self, title=None, message=None, **k):
        self.errors.append((title, message))


class _TimedRoot:
    """The Tk root as the launch's look sees it, timing every callback it
    is asked to run (wall time, in `spans`)."""

    def __init__(self, root):
        self._root = root
        self.spans = []

    def after(self, ms, fn=None, *a):
        def timed(*args):
            t = time.perf_counter()
            try:
                return fn(*args)
            finally:
                self.spans.append(time.perf_counter() - t)
        return self._root.after(ms, timed, *a)

    def __getattr__(self, name):
        return getattr(self._root, name)


class _Var:
    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v


def _gui():
    try:
        import gui
    except ImportError as e:            # no tkinter (WSL)
        raise _Skip(f"gui.py needs tkinter: {e}")
    return gui


def _tk_root():
    _gui()                              # tk_fontfix before any Tk root
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    root.withdraw()
    return root


def _destroy(root):
    try:
        for job in root.tk.splitlist(root.tk.call('after', 'info')):
            try:
                root.after_cancel(job)
            except Exception:
                pass
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass
    import tkinter as tk
    if getattr(tk, '_default_root', None) is root:
        tk._default_root = None


def _until(root, cond, timeout):
    """Pump Tk until cond() holds or `timeout` s pass -> cond()."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def _app(root, outdir):
    """Just enough of the app for the four launchers: the real methods,
    a real status bar, and the look's root timed."""
    import tkinter as tk
    G = _gui().InstrumentControlGUI

    class App:
        _sldea_open_edge_review = G._sldea_open_edge_review
        _sldea_open_tuner = G._sldea_open_tuner
        _sldea_open_plot = G._sldea_open_plot
        _sldea_open_video_review = G._sldea_open_video_review
        sldea_abort = G.sldea_abort

        def __init__(self):
            self.root = _TimedRoot(root)
            self.status_bar = tk.Label(root, text='')
            self.sldea_outdir = _Var(outdir)
            self._sldea_edge_procs = []
            self._sldea_video_reviews = {}
            self._sldea_video_run = None
            self._sldea_running = self._sldea_starting = False
            self._sldea_stop = False
            self.logged = []

        def _sldea_tuner_confirmed(self):
            return True

        def _sldea_job_resume(self):
            pass

        def _sldea_log(self, msg):
            self.logged.append(msg)

        def status(self):
            return self.status_bar.cget('text')
    return App()


def _press(app, program, run):
    """What pressing `program`'s button does, on `run`."""
    if program == 'Edge Review':
        app._sldea_open_edge_review(run)
    elif program == 'Edge tuner':
        app._sldea_open_tuner(run)
    elif program == 'Plot window':
        app._sldea_open_plot(run)
    else:
        app._sldea_video_run = run
        app._sldea_open_video_review()


class _Bench:
    """A Tk root, a run folder, gui's subprocess and messagebox swapped
    for stand-ins, and the launch logs in the test's own folder; restores
    all of it and stops every child it started. `watch_ms`, when given,
    stands in for launch_check.WATCH_MS meanwhile."""

    def __init__(self, child, watch_ms=None):
        self.swap, self.boxes = _Swap(child), _Boxes()
        self.watch_ms = watch_ms

    def __enter__(self):
        self.gui = _gui()
        self.tmp = tempfile.mkdtemp(prefix='launch_check_')
        self.run = os.path.join(self.tmp, 'SLDEA_20261008_120000')
        os.makedirs(self.run)
        self.logs = os.path.join(self.tmp, 'launch_logs')
        self.saved = (self.gui.subprocess, self.gui.messagebox,
                      launch_check.LOG_DIR if launch_check else None,
                      getattr(launch_check, 'WATCH_MS', None))
        self.root = None
        try:
            self.root = _tk_root()
        except BaseException:
            shutil.rmtree(self.tmp, ignore_errors=True)
            raise
        self.gui.subprocess, self.gui.messagebox = self.swap, self.boxes
        if launch_check is not None:
            launch_check.LOG_DIR = self.logs
            if self.watch_ms is not None:
                launch_check.WATCH_MS = self.watch_ms
        return self

    def __exit__(self, *exc):
        self.swap.stop()
        self.gui.subprocess, self.gui.messagebox = self.saved[:2]
        if launch_check is not None:
            launch_check.LOG_DIR = self.saved[2]
            if self.saved[3] is not None:
                launch_check.WATCH_MS = self.saved[3]
        _destroy(self.root)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


def _check_ms():
    return launch_check.CHECK_MS if launch_check else 2000


def _cmds(b):
    """The commands the stand-ins were started with, for a failure's
    message. Not b.swap.calls itself: each call's keywords carry the
    whole environment, which a pasted failure would publish."""
    return [cmd for cmd, _kw in b.swap.calls]


def _exited(b):
    """Wait, without pumping Tk, until every stand-in `b` has started has
    exited (proc.wait: the OS's word, not the check's), so the launch
    check's first look finds each one gone (#458). When that wait passes
    CHECK_MS, the look comes late, as it does in the app when its Tk
    thread is held up, and the check still reports the exit it missed
    (launch_check.watch looks for the exit before the time)."""
    for p in b.swap.procs:
        try:
            p.wait(EXIT_WAIT_S)
        except subprocess.TimeoutExpired:
            raise AssertionError(
                f"a stand-in that exits at once still ran after "
                f"{EXIT_WAIT_S} s: {_cmds(b)}") from None


# ---------------------------------------------------------------------------
# the launchers
# ---------------------------------------------------------------------------

def test_a_program_that_dies_at_once_is_said_with_its_last_lines():
    """THE #429 BUG. Each launcher said "<program> opened on <run>" when
    Popen returned. A program that exits at once must instead be said on
    the status bar and in a box: its exit code, the last lines it printed
    and the log they are in. On 9e94274 no box ever comes."""
    with _Bench(DIES) as b:
        name = os.path.basename(b.run)
        apps = {}
        for program in PROGRAMS:
            apps[program] = app = _app(b.root, b.run)
            _press(app, program, b.run)
        assert len(b.swap.procs) == len(PROGRAMS), _cmds(b)
        _exited(b)
        _until(b.root, lambda: len(b.boxes.errors) >= len(PROGRAMS),
               timeout=_check_ms() / 1000.0 + 5.0)
        said = {app.status() for app in apps.values()}
        assert len(b.boxes.errors) == len(PROGRAMS), (
            f"{len(b.boxes.errors)} boxes for {len(PROGRAMS)} programs that "
            f"died at once; the status lines read {sorted(said)}")
        for p in b.swap.procs:
            assert p.poll() == 3, p.poll()
        titles = sorted(t for t, _m in b.boxes.errors)
        assert titles == sorted(t for _s, t in PROGRAMS.values()), titles
        for program, (_script, title) in PROGRAMS.items():
            [text] = [m for t, m in b.boxes.errors if t == title]
            assert f"{program} stopped before it opened (exit code 3)" \
                in text, text
            assert "boom from the child" in text, text
            log = text.rsplit('\n', 1)[-1]
            assert os.path.dirname(log) == b.logs, text
            with open(log, encoding='utf-8') as f:
                assert 'boom from the child' in f.read()
            st = apps[program].status()
            assert st == (f"{program} stopped on {name} before it opened "
                          f"(exit code 3)"), st
            spans = apps[program].root.spans
            assert spans and max(spans) < LOOK_MAX_S, spans
        assert not b.boxes.infos, b.boxes.infos


def test_a_program_that_stays_up_reads_starting_then_opened():
    """"starting" until the program has run for CHECK_MS, then "opened",
    and no box. Every look is quick, and the launcher itself returns long
    before CHECK_MS: it never waits for its program. A status bar that
    something else has used meanwhile keeps that newer text."""
    with _Bench(STAYS) as b:
        name = os.path.basename(b.run)
        apps, took = {}, {}
        t0 = time.monotonic()
        for program in PROGRAMS:
            apps[program] = app = _app(b.root, b.run)
            t = time.perf_counter()
            _press(app, program, b.run)
            took[program] = time.perf_counter() - t
            assert app.status() == f"{program} starting on {name}…", \
                app.status()
        assert max(took.values()) < _check_ms() / 2000.0, took
        # one status bar is taken over by something newer
        other = _app(b.root, b.run)
        _press(other, 'Edge Review', b.run)
        other.status_bar.config(text="Preset saved")
        opened_at, looks_at = {}, {}

        def all_opened():
            for program, app in apps.items():
                if program not in opened_at and \
                        app.status() == f"{program} opened on {name}":
                    opened_at[program] = time.monotonic() - t0
                    looks_at[app] = len(app.root.spans)
            return len(opened_at) == len(apps)
        # still starting a little before the check passes
        _until(b.root, lambda: False, timeout=_check_ms() / 2000.0)
        for program, app in apps.items():
            assert app.status() == f"{program} starting on {name}…", \
                app.status()
        assert _until(b.root, all_opened,
                      timeout=_check_ms() / 1000.0 + 5.0), \
            {p: a.status() for p, a in apps.items()}
        assert min(opened_at.values()) >= _check_ms() / 1000.0 - 0.05, \
            opened_at
        looks_at[other] = len(other.root.spans)
        _until(b.root, lambda: False, timeout=0.5)
        assert other.status() == "Preset saved", other.status()
        assert not (b.boxes.errors or b.boxes.infos), b.boxes.errors
        for p in b.swap.procs:
            assert p.poll() is None, "the stand-in program stopped"
        # and after "opened" it goes on looking (#473), every LATE_POLL_MS
        # (waited for, not timed: an after() can come late)
        assert _until(b.root, lambda: all(
            len(a.root.spans) > n for a, n in looks_at.items()),
            timeout=launch_check.LATE_POLL_MS / 1000.0 + 10.0), \
            {a.status(): (n, len(a.root.spans)) for a, n in looks_at.items()}
        for app in list(apps.values()) + [other]:
            spans = app.root.spans
            # it kept looking, every POLL_MS, until the check passed (each
            # after() can come late, so fewer looks than CHECK_MS/POLL_MS)
            looks = _check_ms() // launch_check.POLL_MS
            assert looks // 2 <= looks_at[app] <= looks + 1, spans
            assert max(spans) < LOOK_MAX_S, max(spans)


# The look outlasts every wait in the #473 cases below (EXIT_WAIT_S for a
# stand-in's exit, then the pumping after it), so whether a death is said
# never hangs on how long a held start took. The 30 s default itself is
# pinned with a fake clock (test_after_up_the_look_goes_on_to_watch_ms).
LONG_WATCH_MS = (EXIT_WAIT_S + 60) * 1000


def _watches(app):
    """The launch looks `app` keeps (gui.sldea_launch_keep)."""
    return list(getattr(app, '_sldea_launch_watches', None) or [])


def _opened(b, apps, name):
    """Pump until every app's program reads opened. The _waits stand-ins
    run until told, so each is still running at CHECK_MS however long its
    start was held."""
    assert _until(b.root, lambda: all(
        a.status() == f"{p} opened on {name}" for p, a in apps.items()),
        timeout=_check_ms() / 1000.0 + 5.0), \
        {p: a.status() for p, a in apps.items()}


def test_a_program_that_dies_after_it_opened_is_said_too():
    """THE #473 BUG. The look stopped at "opened". On a Windows PC that
    holds a Python start about 5 s (#458) a real window reads "opened"
    while it is still starting, and if it then died nobody was told. Now
    a death before WATCH_MS is said as a death at once is: on the status
    bar and in a box, with its exit code, its last lines and its log.
    Once: the look ends at the death, and neither the bar nor the box
    comes again."""
    gd = _tmp()
    go = os.path.join(gd, 'go')
    try:
        with _Bench(_waits(go), watch_ms=LONG_WATCH_MS) as b:
            name = os.path.basename(b.run)
            apps = {}
            for program in PROGRAMS:
                apps[program] = app = _app(b.root, b.run)
                _press(app, program, b.run)
            _opened(b, apps, name)
            assert not b.boxes.errors, b.boxes.errors
            for app in apps.values():
                [w] = _watches(app)
                assert not w.done and w.proc is not None, \
                    "the look ended at opened"
            _go(go, 3)
            _exited(b)
            assert _until(b.root, lambda: len(b.boxes.errors) >= len(PROGRAMS),
                          timeout=launch_check.LATE_POLL_MS / 1000.0 + 5.0), (
                f"{len(b.boxes.errors)} boxes for {len(PROGRAMS)} programs "
                f"that died after they opened; the status lines read "
                f"{sorted(a.status() for a in apps.values())}")
            for p in b.swap.procs:
                assert p.poll() == 3, p.poll()
            titles = sorted(t for t, _m in b.boxes.errors)
            assert titles == sorted(t for _s, t in PROGRAMS.values()), titles
            for program, (_script, title) in PROGRAMS.items():
                app = apps[program]
                [text] = [m for t, m in b.boxes.errors if t == title]
                head = text.split('\n', 1)[0]
                lead = f"{program} stopped within "
                assert head.startswith(lead), text
                assert head.endswith(" s of starting (exit code 3)."), text
                secs = int(head[len(lead):].split()[0])
                assert secs >= _check_ms() / 1000.0, head
                assert "late boom from the child" in text, text
                log = text.rsplit('\n', 1)[-1]
                assert os.path.dirname(log) == b.logs, text
                st = app.status()
                assert st == (f"{program} stopped on {name} within {secs} s "
                              f"of starting (exit code 3)"), st
                [w] = _watches(app)
                assert w.done and w.job is None, \
                    "the look went on after the death"
                assert w.proc is None, "the ended look kept the handle"
                # something newer on the bar is not overwritten again
                app.status_bar.config(text="Preset saved")
            _until(b.root, lambda: False,
                   timeout=3 * launch_check.LATE_POLL_MS / 1000.0)
            assert len(b.boxes.errors) == len(PROGRAMS), b.boxes.errors
            for app in apps.values():
                assert app.status() == "Preset saved", app.status()
                spans = app.root.spans
                assert spans and max(spans) < LOOK_MAX_S, spans
            assert not b.boxes.infos, b.boxes.infos
    finally:
        shutil.rmtree(gd, ignore_errors=True)


def test_a_program_closed_after_it_opened_is_not_said():
    """#473: exit code 0 after "opened" is its user closing it. The look
    sees it (and ends), and says nothing: no box, and the status line
    keeps "opened"."""
    gd = _tmp()
    go = os.path.join(gd, 'go')
    try:
        with _Bench(_waits(go), watch_ms=LONG_WATCH_MS) as b:
            name = os.path.basename(b.run)
            apps = {}
            for program in PROGRAMS:
                apps[program] = app = _app(b.root, b.run)
                _press(app, program, b.run)
            _opened(b, apps, name)
            looks = [w for a in apps.values() for w in _watches(a)]
            assert len(looks) == len(apps), looks
            _go(go, 0)
            _exited(b)
            # the look has seen every exit: it ends there
            assert _until(b.root, lambda: all(w.done for w in looks),
                          timeout=launch_check.LATE_POLL_MS / 1000.0 + 5.0)
            for p in b.swap.procs:
                assert p.poll() == 0, p.poll()
            _until(b.root, lambda: False, timeout=0.3)
            assert not (b.boxes.errors or b.boxes.infos), b.boxes.errors
            for program, app in apps.items():
                assert app.status() == f"{program} opened on {name}", \
                    app.status()
    finally:
        shutil.rmtree(gd, ignore_errors=True)


def test_a_death_after_opened_during_a_run_waits_for_the_run_too():
    """#473 with the #429 review's hold, HV-relevant: a box from a death
    after "opened" must not stand between the operator and Abort either. The worker opens Edge Review itself at a run's end, so its
    late death can come while the run is going: the status line says it
    at once, and the box waits for the run's end."""
    gui = _gui()
    hold_s = gui.SLDEA_LAUNCH_HOLD_MS / 1000.0
    gd = _tmp()
    go = os.path.join(gd, 'go')
    try:
        with _Bench(_waits(go), watch_ms=LONG_WATCH_MS) as b:
            name = os.path.basename(b.run)
            app = _app(b.root, b.run)
            app._sldea_running = True
            app._sldea_open_edge_review(b.run)
            _opened(b, {'Edge Review': app}, name)
            _go(go, 3)
            _exited(b)
            assert _until(b.root, lambda: 'stopped' in app.status(),
                          timeout=launch_check.LATE_POLL_MS / 1000.0 + 5.0), \
                app.status()
            _until(b.root, lambda: False, timeout=3 * hold_s)
            assert b.boxes.errors == [], (
                f"a box opened during the run: {b.boxes.errors}")
            st = app.status()
            assert st.startswith(f"Edge Review stopped on {name} within "), st
            assert st.endswith(" s of starting (exit code 3)"
                               + gui.SLDEA_LAUNCH_HELD), st
            app._sldea_running = False
            assert _until(b.root, lambda: b.boxes.errors,
                          timeout=hold_s + 3.0)
            [(title, text)] = b.boxes.errors
            assert title == 'Edge Review' and '(exit code 3)' in text, text
            assert 'late boom from the child' in text, text
    finally:
        shutil.rmtree(gd, ignore_errors=True)


def test_the_look_ends_when_the_window_closes():
    """#473: the look now outlives "opened" by up to WATCH_MS, so a window
    closed in that time takes its timer with it: none is left to fire
    into a window that is gone (Tk would say "invalid command name"), and
    the look lets go of the program's handle, as _sldea_folder_stop does
    for the run folder line. The program itself is not touched."""
    with _Bench(STAYS) as b:
        name = os.path.basename(b.run)
        app = _app(b.root, b.run)
        _press(app, 'Plot window', b.run)
        _opened(b, {'Plot window': app}, name)
        [w] = _watches(app)
        job = w.job
        assert not w.done and job is not None, (w.done, job)

        def pending():
            return set(b.root.tk.splitlist(b.root.tk.call('after', 'info')))
        assert job in pending(), (job, pending())
        b.root.destroy()
        assert w.done and w.job is None and w.proc is None, \
            (w.done, w.job, w.proc)
        assert job not in pending(), (job, pending())
        assert _watches(app) == []
        assert b.swap.procs[0].poll() is None, "the program was stopped"


def test_a_healthy_program_starts_as_it_did_with_its_output_in_a_log():
    """The arguments and working folder are the app's, as they were before
    #429, and start_new_session too. Its output moves: stdout and stderr
    together, into a file of its own, unbuffered. PYTHONUNBUFFERED=1 is
    the one change to its environment."""
    os.environ[PROBE_ENV] = 'x429'
    try:
        with _Bench(TELLS) as b:
            app = _app(b.root, b.run)
            app._sldea_open_edge_review(b.run, auto=True)
            [(cmd, kw)] = b.swap.calls
            script = os.path.join(os.path.dirname(os.path.abspath(
                b.gui.__file__)), 'sldea_edge_gui.py')
            assert cmd == [sys.executable, script, b.run, '--auto'], cmd
            # the key names only: kw['env'] is the whole environment, which
            # a pasted failure would publish (#476)
            assert set(kw) == {'start_new_session', 'stdout', 'stderr',
                               'env'}, sorted(kw)
            assert kw['start_new_session'] is True
            assert kw['stderr'] == subprocess.STDOUT
            assert kw['env'] == dict(os.environ, PYTHONUNBUFFERED='1')
            assert not isinstance(kw['stdout'], int), kw['stdout']
            assert kw['stdout'].closed, "the app kept the log open"
            assert app._sldea_edge_procs == b.swap.procs
            assert _until(b.root, lambda: 'opened' in app.status(),
                          timeout=_check_ms() / 1000.0 + 5.0), app.status()
            [log] = [os.path.join(b.logs, n) for n in os.listdir(b.logs)]

            def logged():
                with open(log, encoding='utf-8') as f:
                    return f.read().splitlines()
            # it prints once its Python runs, which on a busy Windows PC
            # can be seconds after "opened" (#458)
            end = time.monotonic() + EXIT_WAIT_S
            while len(logged()) < 3 and time.monotonic() < end:
                time.sleep(0.05)
            lines = logged()
            assert len(lines) >= 3, lines
            assert lines[0].startswith('# Edge Review, started '), lines
            assert 'sldea_edge_gui.py' in lines[1], lines
            told = json.loads(lines[2])
            assert told == [os.getcwd(), 'x429', '1'], told
    finally:
        os.environ.pop(PROBE_ENV, None)


def test_a_program_that_cannot_start_is_said_as_before():
    """A Popen that raises is still "Could not launch" in a box with the
    old title, and it leaves no log behind."""
    gui = _gui()

    class _Refuse:
        def Popen(self, cmd, **kw):
            raise OSError("no fork")
    with _Bench(STAYS) as b:
        gui.subprocess = _Refuse()
        app = _app(b.root, b.run)
        app.status_bar.config(text="before")
        for program in PROGRAMS:
            _press(app, program, b.run)
        assert [t for t, _m in b.boxes.errors] == \
            [t for _s, t in PROGRAMS.values()], b.boxes.errors
        assert all(m == "Could not launch: no fork"
                   for _t, m in b.boxes.errors), b.boxes.errors
        assert app.status() == "before", app.status()
        assert app._sldea_edge_procs == [] and \
            app._sldea_video_reviews == {}
        left = os.listdir(b.logs) if os.path.isdir(b.logs) else []
        assert left == [], left


def test_the_traceback_is_in_the_tail_after_many_printed_lines():
    """#429 review: a Python program writing to a file buffered its
    stdout and wrote it at exit, after the traceback, so 20 printed lines
    pushed the error out of the 12-line tail. Unbuffered, the error is
    the tail's last line."""
    with _Bench(CHATTY) as b:
        app = _app(b.root, b.run)
        app._sldea_open_tuner(b.run)
        _exited(b)
        assert _until(b.root, lambda: b.boxes.errors,
                      timeout=_check_ms() / 1000.0 + 5.0), app.status()
        [(title, text)] = b.boxes.errors
        assert title == 'Edge tuner', title
        assert "(exit code 1)" in text, text
        shown = text.split('The last lines it printed:\n\n', 1)[1]
        shown = shown.split('\n\nAll of its output:', 1)[0].splitlines()
        assert shown[-1] == 'RuntimeError: the real error', shown
        assert 'progress 19' in shown, shown


def test_a_program_closed_at_once_reads_closed_with_no_box():
    """Exit code 0 inside the check is a normal close: none of the four
    programs hands off to a copy already running. The status line says
    "closed" and no box opens."""
    with _Bench(CLOSES) as b:
        name = os.path.basename(b.run)
        apps = {}
        for program in PROGRAMS:
            apps[program] = app = _app(b.root, b.run)
            _press(app, program, b.run)
        _exited(b)

        def all_closed():
            return all(a.status() == f"{p} closed on {name}"
                       for p, a in apps.items())
        assert _until(b.root, all_closed,
                      timeout=_check_ms() / 1000.0 + 5.0), \
            {p: a.status() for p, a in apps.items()}
        for p in b.swap.procs:
            assert p.poll() == 0, p.poll()
        _until(b.root, lambda: False, timeout=0.3)
        assert not (b.boxes.errors or b.boxes.infos), b.boxes.errors


def test_during_a_run_the_box_waits_for_the_run_to_end():
    """#429 review, HV-relevant. A message box takes a grab, and on
    Windows it is owner-modal, so while one is open ■ Abort (no key
    binding) does not respond. Edge Review..., Tune params and Plot
    runs... stay enabled during a run, and the worker opens Edge Review
    itself before it zeroes the SG. While _sldea_running or _sldea_starting
    is set, a launch that failed is said on the status line only; the box
    comes once the run has ended, in a callback of its own, never from
    the run's end path."""
    import tkinter as tk
    gui = _gui()
    # (500 ms without the constant: the review's proof ran this on the
    # head before the fix, where it must fail on the box, not the name)
    hold_s = getattr(gui, 'SLDEA_LAUNCH_HOLD_MS', 500) / 1000.0
    with _Bench(DIES) as b:
        name = os.path.basename(b.run)
        app = _app(b.root, b.run)
        abort = tk.Button(b.root, text='■ Abort', command=app.sldea_abort)
        app._sldea_running = True
        app._sldea_open_edge_review(b.run)
        _exited(b)
        assert _until(b.root, lambda: 'stopped' in app.status(),
                      timeout=_check_ms() / 1000.0 + 5.0), app.status()
        _until(b.root, lambda: False, timeout=3 * hold_s)
        assert b.boxes.errors == [], (
            f"a box opened during the run: {b.boxes.errors}")
        assert app.status() == (
            f"Edge Review stopped on {name} before it opened (exit code 3)"
            f"; details when the run ends"), app.status()
        # ■ Abort still answers while the program has died
        abort.invoke()
        assert app._sldea_stop is True and app.logged, app.logged
        # the run ends: what _sldea_finished does to the flag. The box is
        # not shown from there...
        app._sldea_running = False
        assert b.boxes.errors == []
        # ...but by the next look, in a callback of its own
        t = time.monotonic()
        assert _until(b.root, lambda: b.boxes.errors, timeout=hold_s + 3.0)
        assert time.monotonic() - t < hold_s + 0.5, time.monotonic() - t
        [(title, text)] = b.boxes.errors
        assert title == 'Edge Review' and '(exit code 3)' in text, text
        assert 'boom from the child' in text, text
        spans = app.root.spans
        assert len(spans) > 3 and max(spans) < LOOK_MAX_S, spans

        # a Popen that fails during the camera pre-flight: sldea_run sets
        # _sldea_starting just before it, after its earlier start dialogs
        # (where the HV is off and Abort is disabled, and a held box may
        # still open on top of them)
        del b.boxes.errors[:]

        class _Refuse:
            def Popen(self, cmd, **kw):
                raise OSError("no fork")
        b.gui.subprocess = _Refuse()
        app._sldea_starting = True
        app._sldea_open_plot(b.run)
        assert app.status() == (f"Plot window could not be started on "
                                f"{name}; details when the run ends"), \
            app.status()
        _until(b.root, lambda: False, timeout=2 * hold_s)
        assert b.boxes.errors == []
        app._sldea_starting = False
        assert _until(b.root, lambda: b.boxes.errors, timeout=hold_s + 3.0)
        assert b.boxes.errors == [('SLDEA plot', 'Could not launch: no fork')]


def test_a_held_box_waits_for_an_open_hv_alarm():
    """#429 re-check. When zeroing fails, the worker queues HV NOT ZEROED
    before _sldea_finished, so _sldea_finished runs inside the open alarm
    and clears the run flag. A held launch box must keep waiting until the
    alarm is closed: nothing covers an HV alarm. Then it shows."""
    import inspect
    gui = _gui()
    hold_s = getattr(gui, 'SLDEA_LAUNCH_HOLD_MS', 500) / 1000.0
    with _Bench(DIES) as b:
        app = _app(b.root, b.run)
        app._sldea_running = True
        app._sldea_open_edge_review(b.run)
        _exited(b)
        assert _until(b.root, lambda: 'stopped' in app.status(),
                      timeout=_check_ms() / 1000.0 + 5.0), app.status()
        seen = {}

        def alarm(title, text):
            # what Tk does under a modal box: it keeps serving events, and
            # the run's end (_sldea_finished) runs in here
            app._sldea_running = False
            seen['open'] = getattr(app, '_sldea_alarms_open', None)
            _until(b.root, lambda: False, timeout=3 * hold_s)
            seen['boxes'] = list(b.boxes.errors)
            return 'dismissed'
        assert gui.sldea_alarm(app, alarm, "HV NOT ZEROED",
                               "turn it off") == 'dismissed'
        assert seen['open'] == 1, seen
        assert seen['boxes'] == [], \
            f"a launch box opened over the HV alarm: {seen['boxes']}"
        assert app._sldea_alarms_open == 0
        # the alarm is closed: the box comes at the next look
        assert _until(b.root, lambda: b.boxes.errors, timeout=hold_s + 3.0)
        [(title, text)] = b.boxes.errors
        assert title == 'Edge Review' and '(exit code 3)' in text, text

    # an alarm box that raises still closes its count
    class _App:
        pass
    a = _App()

    def broken(title, text):
        raise RuntimeError("Tk is gone")
    try:
        gui.sldea_alarm(a, broken, 't', 'x')
    except RuntimeError:
        pass
    else:
        raise AssertionError("the alarm's error was swallowed")
    assert a._sldea_alarms_open == 0
    # both of the run's own boxes go through it. A source check, because
    # driving the worker to a failed zeroing needs the whole run harness.
    src = ' '.join(inspect.getsource(
        gui.InstrumentControlGUI._sldea_worker).split())
    assert 'sldea_alarm( self, messagebox.showerror, "HV NOT ZEROED",' \
        in src, "HV NOT ZEROED is not shown through sldea_alarm"
    assert 'sldea_alarm( self, messagebox.showwarning, stop_box' in src
    assert 'lambda: messagebox.show' not in src


def test_a_signal_is_said_as_a_signal():
    """POSIX: a program a signal ended (a segfault, a kill) has a negative
    return code, said as the signal."""
    assert launch_check.exit_words(3) == 'exit code 3'
    assert launch_check.exit_words(-11) == 'ended by signal 11'
    if os.name == 'nt':
        return
    killed = [sys.executable, '-c',
              'import os, signal; os.kill(os.getpid(), signal.SIGTERM)']
    with _Bench(killed) as b:
        app = _app(b.root, b.run)
        app._sldea_open_plot(b.run)
        _exited(b)
        assert _until(b.root, lambda: b.boxes.errors,
                      timeout=_check_ms() / 1000.0 + 5.0)
        assert app.status().endswith('(ended by signal 15)'), app.status()


# ---------------------------------------------------------------------------
# launch_check itself
# ---------------------------------------------------------------------------

def _tmp():
    return tempfile.mkdtemp(prefix='launch_check_')


def test_the_tail_is_the_end_of_what_the_program_wrote():
    """Last TAIL_LINES lines, never the header, each line cut to
    LINE_CHARS, the partial first line of a read from the middle
    dropped, and output in the locale's encoding still read."""
    d = _tmp()
    try:
        path = os.path.join(d, 'x.log')
        head = b'# Edge Review, started now\n# python x.py\n'
        body = b''.join(b'line %d\n' % i for i in range(40))
        with open(path, 'wb') as f:
            f.write(head + body + b'\n\n')
        got = launch_check.tail(path, start=len(head))
        assert got.splitlines() == [f'line {i}' for i in range(28, 40)], got
        # few lines: all of them, and no header
        with open(path, 'wb') as f:
            f.write(head + b'only this\r\n')
        assert launch_check.tail(path, start=len(head)) == 'only this'
        # nothing written
        with open(path, 'wb') as f:
            f.write(head)
        assert launch_check.tail(path, start=len(head)) == ''
        # a read from the middle drops the partial first line
        with open(path, 'wb') as f:
            f.write(head + b'x' * 50 + b'\nwhole\n')
        assert launch_check.tail(path, start=len(head), max_bytes=20) == \
            'whole'
        # a long line is cut
        with open(path, 'wb') as f:
            f.write(head + b'y' * 1000 + b'\n')
        got = launch_check.tail(path, start=len(head))
        assert len(got) == launch_check.LINE_CHARS and got.endswith('...')
        # not UTF-8 (a Windows console encoding): still text
        with open(path, 'wb') as f:
            f.write(head + b'5 \xb5A\n')
        got = launch_check.tail(path, start=len(head))
        assert got.startswith('5 ') and got.endswith('A'), got
        assert launch_check.tail(os.path.join(d, 'gone.log')) is None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_report_names_the_code_the_lines_and_the_log():
    d = _tmp()
    try:
        path = os.path.join(d, 'x.log')
        with open(path, 'wb') as f:
            f.write(b'# h\nTraceback\nImportError: no cv2\n')
        run = launch_check.Launch(None, 'Edge tuner', path, start=4)
        text = launch_check.report(run, 1)
        assert text.startswith(
            'Edge tuner stopped before it opened (exit code 1).'), text
        assert 'ImportError: no cv2' in text and '# h' not in text, text
        assert text.endswith('\n' + path), text
        # a death the look saw after "opened" (#473): when, as an upper
        # bound from the time of that look, and the same lines and log
        late = launch_check.report(run, 1, 6.2)
        assert late.startswith(
            'Edge tuner stopped within 7 s of starting (exit code 1).'), late
        assert late.split('\n', 1)[1] == text.split('\n', 1)[1], late
        assert launch_check.when_words(None) == 'before it opened'
        assert launch_check.when_words(3.0) == 'within 3 s of starting'
        with open(path, 'wb') as f:
            f.write(b'# h\n')
        assert 'It printed nothing.' in launch_check.report(run, 2)
        os.remove(path)
        assert 'could not be read' in launch_check.report(run, 2)
        none = launch_check.Launch(None, 'Edge tuner', None, why='full disk')
        text = launch_check.report(none, 2)
        assert 'not kept' in text and 'full disk' in text, text
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_old_logs_are_swept_and_nothing_else():
    d = _tmp()
    try:
        now = time.time()
        old, fresh = os.path.join(d, 'a_old.log'), os.path.join(d, 'b.log')
        other = os.path.join(d, 'notes.txt')
        sub = os.path.join(d, 'old_dir.log')
        for p in (old, fresh, other):
            open(p, 'w').close()
        os.makedirs(sub)
        week = launch_check.KEEP_S
        for p in (old, other, sub):
            os.utime(p, (now - week - 60, now - week - 60))
        os.utime(fresh, (now - week + 60, now - week + 60))
        assert launch_check.sweep(d, now=now) == 1
        assert sorted(os.listdir(d)) == ['b.log', 'notes.txt', 'old_dir.log']
        assert launch_check.sweep(os.path.join(d, 'none')) == 0
        # and a start sweeps its folder first
        os.utime(fresh, (now - week - 60, now - week - 60))
        saved = launch_check.LOG_DIR
        launch_check.LOG_DIR = d
        try:
            run = launch_check.start(
                ['prog'], 'Edge Review',
                popen=lambda cmd, **kw: 'proc')
        finally:
            launch_check.LOG_DIR = saved
        assert run.proc == 'proc'
        left = sorted(os.listdir(d))
        assert 'b.log' not in left and len(left) == 3, left
        assert os.path.basename(run.path).startswith('edge_review_')
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_log_that_cannot_be_made_costs_only_the_log():
    """The program is started all the same, on the app's own output, and
    a report says its output was not kept and why."""
    d = _tmp()
    saved = launch_check.LOG_DIR
    try:
        blocker = os.path.join(d, 'a_file')
        open(blocker, 'w').close()
        launch_check.LOG_DIR = os.path.join(blocker, 'logs')
        calls = []
        run = launch_check.start(
            ['prog', 'run'], 'Video review',
            popen=lambda cmd, **kw: calls.append((cmd, kw)) or 'proc')
        assert calls == [(['prog', 'run'], {'start_new_session': True})], \
            calls
        assert run.proc == 'proc' and run.path is None and run.why
        assert 'not kept' in launch_check.report(run, 1)
    finally:
        launch_check.LOG_DIR = saved
        shutil.rmtree(d, ignore_errors=True)


def test_a_popen_that_raises_leaves_no_log():
    d = _tmp()
    saved = launch_check.LOG_DIR
    try:
        launch_check.LOG_DIR = d

        def refuse(cmd, **kw):
            raise OSError('no fork')
        try:
            launch_check.start(['prog'], 'Edge tuner', popen=refuse)
        except OSError as e:
            assert str(e) == 'no fork'
        else:
            raise AssertionError("the Popen error was swallowed")
        assert os.listdir(d) == [], os.listdir(d)
    finally:
        launch_check.LOG_DIR = saved
        shutil.rmtree(d, ignore_errors=True)


def test_the_default_log_folder_is_beside_the_other_local_logs():
    import tk_stall
    saved = launch_check.LOG_DIR
    try:
        launch_check.LOG_DIR = None
        assert launch_check.log_dir() == os.path.join(
            os.path.dirname(tk_stall.default_log_path()), 'launch_logs')
    finally:
        launch_check.LOG_DIR = saved


class _FakeRoot:
    """Records after() calls; `gone` makes them raise, as Tk does once
    the window is destroyed. after_cancel() drops a job, as Tk's does."""

    def __init__(self):
        self.jobs, self.gone = [], False
        self.ids, self.canceled, self.n = [], [], 0

    def after(self, ms, fn=None, *a):
        if self.gone:
            raise RuntimeError('application has been destroyed')
        self.n += 1
        self.jobs.append((ms, fn))
        self.ids.append(self.n)
        return self.n

    def after_cancel(self, job):
        self.canceled.append(job)
        if job in self.ids:
            i = self.ids.index(job)
            del self.jobs[i], self.ids[i]

    def run_next(self):
        _ms, fn = self.jobs.pop(0)
        self.ids.pop(0)
        fn()


class _FakeProc:
    def __init__(self, codes):
        self.codes = list(codes)

    def poll(self):
        return self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]


def test_the_look_calls_exactly_one_of_up_and_down():
    t = [0]                             # ms, so the sums stay exact

    def clock():
        return t[0] / 1000.0
    said = []
    # exits on the third look
    root, proc = _FakeRoot(), _FakeProc([None, None, 3])
    launch_check.watch(root, proc, lambda: said.append('up'),
                       lambda c: said.append(('down', c)),
                       check_ms=2000, poll_ms=200, clock=clock)
    for _i in range(3):
        assert root.jobs[0][0] == 200
        t[0] += 200
        root.run_next()
    assert said == [('down', 3)] and root.jobs == [], (said, root.jobs)
    # stays up: up() at the first look at or after check_ms
    said.clear()
    t[0] = 0
    root, proc = _FakeRoot(), _FakeProc([None])
    launch_check.watch(root, proc, lambda: said.append('up'),
                       lambda c: said.append(('down', c)),
                       check_ms=2000, poll_ms=200, clock=clock)
    n = 0
    while root.jobs:
        t[0] += 200
        root.run_next()
        n += 1
    assert said == ['up'] and n == 10, (said, n)
    # a Tk thread held up past check_ms still reports the exit it missed
    said.clear()
    t[0] = 0
    root, proc = _FakeRoot(), _FakeProc([1])
    launch_check.watch(root, proc, lambda: said.append('up'),
                       lambda c: said.append(('down', c)),
                       check_ms=2000, poll_ms=200, clock=clock)
    t[0] = 9000
    root.run_next()
    assert said == [('down', 1)], said
    # the window closes during the look: no error, nobody told
    said.clear()
    t[0] = 0
    root, proc = _FakeRoot(), _FakeProc([None])
    launch_check.watch(root, proc, lambda: said.append('up'),
                       lambda c: said.append(('down', c)),
                       check_ms=2000, poll_ms=200, clock=clock)
    root.gone = True
    root.run_next()
    assert said == [] and root.jobs == []
    # a poll or a callback that raises never reaches Tk
    class _Bad:
        def poll(self):
            raise OSError('reaped elsewhere')
    root = _FakeRoot()
    launch_check.watch(root, _Bad(), lambda: 1 / 0, lambda c: None,
                       check_ms=0, poll_ms=200, clock=clock)
    root.run_next()
    assert root.jobs == []


def test_after_up_the_look_goes_on_to_watch_ms():
    """#473, with a fake clock. Given a `late`, the look goes on after
    up() every LATE_POLL_MS until WATCH_MS (30 s by default) after the
    start; a death in that time calls late(code, secs) once, and the
    look ends there, as it does at WATCH_MS. Then it holds neither the
    process nor the callbacks. cancel() ends it at once."""
    t = [0]                             # ms, so the sums stay exact

    def clock():
        return t[0] / 1000.0
    said = []

    def go(codes):
        root, proc = _FakeRoot(), _FakeProc(codes)
        w = launch_check.watch(root, proc, lambda: said.append('up'),
                               lambda c: said.append(('down', c)),
                               lambda c, s: said.append(('late', c, s)),
                               clock=clock)
        return root, w

    def looks(root, n=None):
        """Run each look when its time comes: `n` of them, or all to the
        look's end (at most 10000, so a look that never ends fails the
        case rather than hanging it) -> how many ran."""
        ran, n = 0, 10000 if n is None else n
        while root.jobs and ran < n:
            t[0] += root.jobs[0][0]
            root.run_next()
            ran += 1
        return ran
    assert launch_check.WATCH_MS == 30000, launch_check.WATCH_MS
    early = launch_check.CHECK_MS // launch_check.POLL_MS   # up() at the last
    chk = launch_check.CHECK_MS / 1000.0
    late_ms = launch_check.LATE_POLL_MS
    # stays up: up() at CHECK_MS, then a look every LATE_POLL_MS until the
    # first one at or after WATCH_MS, and nothing more
    said.clear()
    t[0] = 0
    root, w = go([None])
    n = looks(root)
    late_looks = -(-(launch_check.WATCH_MS - launch_check.CHECK_MS)
                   // late_ms)
    assert said == ['up'] and root.jobs == [], (said, root.jobs)
    assert n == early + late_looks, n
    assert t[0] == launch_check.CHECK_MS + late_looks * late_ms, t[0]
    assert w.done and w.proc is None and w.job is None
    assert (w.up, w.down, w.late) == (None, None, None)
    # dies after up: late() once, with the time of that look (the third
    # late look), then nothing
    said.clear()
    t[0] = 0
    root, w = go([None] * (early + 2) + [3])
    looks(root)
    assert said == ['up', ('late', 3, chk + 3 * late_ms / 1000.0)], said
    assert root.jobs == [] and w.done and w.proc is None
    # exit code 0 is the caller's to judge: late() is called all the same
    said.clear()
    t[0] = 0
    root, w = go([None] * early + [0])
    looks(root)
    assert said == ['up', ('late', 0, chk + late_ms / 1000.0)], said
    # a Tk thread held up past WATCH_MS still reports the exit it missed
    said.clear()
    t[0] = 0
    root, w = go([None] * early + [1])
    looks(root, early)
    assert said == ['up'] and len(root.jobs) == 1, said
    t[0] = 45000
    root.run_next()
    assert said == ['up', ('late', 1, 45.0)] and w.done, said
    # an early death is still down(), never late()
    said.clear()
    t[0] = 0
    root, w = go([None, 2])
    looks(root)
    assert said == [('down', 2)] and w.done, said
    # cancel() during the late looks: its job is gone, nothing more runs
    said.clear()
    t[0] = 0
    root, w = go([None])
    looks(root, early + 2)
    assert said == ['up'] and len(root.jobs) == 1 and w.job is not None
    job = w.job
    w.cancel()
    assert root.canceled == [job] and root.jobs == [], root.canceled
    assert w.done and w.proc is None and w.job is None
    w.cancel()                          # again: nothing, no error
    assert root.canceled == [job]
    # a late() that raises ends the look and never reaches Tk
    said.clear()
    t[0] = 0
    root, proc = _FakeRoot(), _FakeProc([None] * early + [3])
    w = launch_check.watch(root, proc, lambda: None, lambda c: None,
                           lambda c, s: 1 / 0, clock=clock)
    looks(root)
    assert w.done and root.jobs == []


# ---------------------------------------------------------------------------

def _run_all():
    # Failures are collected, not fatal (`#280`); skips are counted apart
    # and are not failures.
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    ran = skipped = 0
    failed = []
    for n in names:
        try:
            globals()[n]()
        except _Skip as why:
            skipped += 1
            print('skip', n, f'({why})')
            gc.collect()
            continue
        except Exception:
            ran += 1
            failed.append((n, traceback.format_exc()))
            print('FAIL', n)
            gc.collect()
            continue
        ran += 1
        print('ok  ', n)
        gc.collect()
    tail = f"{ran} of {len(names)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped)"
    print(tail)
    if not failed:
        return 0
    head = f"{len(failed)} of {len(names)} tests failed"
    print(f"\n{head}")
    for name, tb in failed:
        print(f"===== FAIL {name} =====")
        print(tb.rstrip('\n'))
    print(f"===== end {head} =====")
    return 1


if __name__ == '__main__':
    raise SystemExit(_run_all())
