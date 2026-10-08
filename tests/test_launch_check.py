#!/usr/bin/env python3
"""The SLDEA tab's launchers check that their program opened (#429).

Edge Review..., Tune params, Plot runs... and Video review... start
programs of their own. Each used to say "<program> opened on <run>" as soon
as Popen returned, so a program that died at once still read as opened,
and what it printed went to the bench app's own output. Pinned here:

* a program that exits at once is said on the status bar and in a box,
  with its exit code, the last lines it printed and the log they are in;
* a program that stays up reads "starting" until launch_check.CHECK_MS
  has passed, then "opened", unless something else has used the status
  bar meanwhile;
* each look is one poll() on the Tk thread, and the launcher returns
  without waiting for its program;
* a healthy program starts as before: the same arguments, working folder,
  environment and start_new_session, with its stdout and stderr in a log
  file of its own, never a pipe;
* launch_check itself: the tail of a log, the sweep of old logs, a log
  that cannot be made (the program still starts), a Popen that raises,
  and a window that closes during the look.

The launcher cases start real child processes (`python -c ...`) in place
of the programs, through the launchers' own Popen keywords, and stop
every one through the Popen handle they hold. They need a Tk display and
skip cleanly without one.

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
# ...and one that says where it runs and what it was given, then stays
TELLS = [sys.executable, '-c',
         'import json, os, sys, time; '
         f'print(json.dumps([os.getcwd(), os.environ.get("{PROBE_ENV}")])); '
         'sys.stdout.flush(); time.sleep(60)']

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

        def __init__(self):
            self.root = _TimedRoot(root)
            self.status_bar = tk.Label(root, text='')
            self.sldea_outdir = _Var(outdir)
            self._sldea_edge_procs = []
            self._sldea_video_reviews = {}
            self._sldea_video_run = None

        def _sldea_tuner_confirmed(self):
            return True

        def _sldea_job_resume(self):
            pass

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
    all of it and stops every child it started."""

    def __init__(self, child):
        self.swap, self.boxes = _Swap(child), _Boxes()

    def __enter__(self):
        self.gui = _gui()
        self.tmp = tempfile.mkdtemp(prefix='launch_check_')
        self.run = os.path.join(self.tmp, 'SLDEA_20261008_120000')
        os.makedirs(self.run)
        self.logs = os.path.join(self.tmp, 'launch_logs')
        self.saved = (self.gui.subprocess, self.gui.messagebox,
                      launch_check.LOG_DIR if launch_check else None)
        self.root = None
        try:
            self.root = _tk_root()
        except BaseException:
            shutil.rmtree(self.tmp, ignore_errors=True)
            raise
        self.gui.subprocess, self.gui.messagebox = self.swap, self.boxes
        if launch_check is not None:
            launch_check.LOG_DIR = self.logs
        return self

    def __exit__(self, *exc):
        self.swap.stop()
        self.gui.subprocess, self.gui.messagebox = self.saved[:2]
        if launch_check is not None:
            launch_check.LOG_DIR = self.saved[2]
        _destroy(self.root)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


def _check_ms():
    return launch_check.CHECK_MS if launch_check else 2000


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
        assert len(b.swap.procs) == len(PROGRAMS), b.swap.calls
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
        opened_at = {}

        def all_opened():
            for program, app in apps.items():
                if program not in opened_at and \
                        app.status() == f"{program} opened on {name}":
                    opened_at[program] = time.monotonic() - t0
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
        _until(b.root, lambda: False, timeout=0.5)
        assert other.status() == "Preset saved", other.status()
        assert not (b.boxes.errors or b.boxes.infos), b.boxes.errors
        for p in b.swap.procs:
            assert p.poll() is None, "the stand-in program stopped"
        for app in list(apps.values()) + [other]:
            spans = app.root.spans
            # it kept looking, every POLL_MS, until the check passed (each
            # after() can come late, so fewer looks than CHECK_MS/POLL_MS)
            looks = _check_ms() // launch_check.POLL_MS
            assert looks // 2 <= len(spans) <= looks + 1, spans
            assert max(spans) < LOOK_MAX_S, max(spans)


def test_a_healthy_program_starts_as_it_did_with_its_output_in_a_log():
    """The arguments, working folder and environment are the app's, as
    they were before #429, and start_new_session too. Only its output
    moves: stdout and stderr together, into a file of its own."""
    os.environ[PROBE_ENV] = 'x429'
    try:
        with _Bench(TELLS) as b:
            app = _app(b.root, b.run)
            app._sldea_open_edge_review(b.run, auto=True)
            [(cmd, kw)] = b.swap.calls
            script = os.path.join(os.path.dirname(os.path.abspath(
                b.gui.__file__)), 'sldea_edge_gui.py')
            assert cmd == [sys.executable, script, b.run, '--auto'], cmd
            assert set(kw) == {'start_new_session', 'stdout', 'stderr'}, kw
            assert kw['start_new_session'] is True
            assert kw['stderr'] == subprocess.STDOUT
            assert not isinstance(kw['stdout'], int), kw['stdout']
            assert kw['stdout'].closed, "the app kept the log open"
            assert app._sldea_edge_procs == b.swap.procs
            assert _until(b.root, lambda: 'opened' in app.status(),
                          timeout=_check_ms() / 1000.0 + 5.0), app.status()
            [log] = [os.path.join(b.logs, n) for n in os.listdir(b.logs)]
            with open(log, encoding='utf-8') as f:
                lines = f.read().splitlines()
            assert lines[0].startswith('# Edge Review, started '), lines
            assert 'sldea_edge_gui.py' in lines[1], lines
            told = json.loads(lines[2])
            assert told == [os.getcwd(), 'x429'], told
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
    the window is destroyed."""

    def __init__(self):
        self.jobs, self.gone = [], False

    def after(self, ms, fn=None, *a):
        if self.gone:
            raise RuntimeError('application has been destroyed')
        self.jobs.append((ms, fn))
        return len(self.jobs)

    def run_next(self):
        _ms, fn = self.jobs.pop(0)
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
