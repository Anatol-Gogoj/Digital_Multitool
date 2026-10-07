#!/usr/bin/env python3
"""Tests for the window-freeze logger, tk_stall.py (`#397`).

Run: .venv/bin/python tests/test_tk_stall.py

Most cases drive StallTracker in made-up time: no clock, thread, Tk or
file, so they run anywhere, WSL included. The real-thread cases (the CPU
clock, a look from another thread, the whole logger on a fake root) run
on whatever OS this is, which is how the Linux paths get checked for real
under WSL (pthread_getcpuclockid, /proc/loadavg) next to the Windows one
(GetThreadTimes). The Tk cases need a display and tkinter; where either is
missing they are SKIPPED, counted and named in the tail line, and never
reported as passes.
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import ast
import hashlib
import io
import os
import re
import shutil
import sys
import tempfile
import threading
import time

import tk_stall

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STACK = [('app.py', 10, 'main'), ('app.py', 20, 'slow_call')]


class _Skip(Exception):
    """Raised by a test that cannot run here. `reason` is what the tail
    line names."""

    def __init__(self, reason, detail=None):
        super().__init__(f'{reason}: {detail}' if detail else reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# made-up time
# ---------------------------------------------------------------------------

def _entries(text):
    """[(kind, text)] for each entry of a log, in file order: an entry is
    a line that starts with a timestamp, plus its indented lines."""
    out = []
    for line in text.splitlines():
        if line and not line[0].isspace():
            out.append([line])
        elif out:
            out[-1].append(line)
    return [(b[0].split()[2], '\n'.join(b)) for b in out]


def _beats(t0, t1, period=0.05):
    """Heartbeat times from t0 to t1 inclusive, `period` apart."""
    n = int(round((t1 - t0) / period))
    return [round(t0 + k * period, 6) for k in range(n + 1)]


def _simulate(beat_times, end, cpu_at=lambda t: 0.0,
              stack_at=lambda t: list(STACK)):
    """Drive a tracker the way the two threads do, in made-up time: the
    heartbeat at `beat_times`, the watchdog whenever poll asks to be woken
    (5 ms late and at least 10 ms apart, like StallLogger._watch). Each
    look records when it was taken and shows stack_at(that time). Returns
    (tracker, records, look times)."""
    tr = tk_stall.StallTracker((0.0, cpu_at(0.0), cpu_at(0.0)))
    now = [0.0]
    looks = []

    def look():
        looks.append(now[0])
        c = cpu_at(now[0])
        return tk_stall.Look(c, c, None, stack_at(now[0]), [], None)

    beats = sorted(beat_times)
    records = []
    i, wake = 0, 0.0
    while True:
        nxt = beats[i] if i < len(beats) else float('inf')
        if min(nxt, wake) > end:
            break
        if nxt <= wake:
            now[0] = nxt
            tr.beat((nxt, cpu_at(nxt), cpu_at(nxt)))
            i += 1
        else:
            now[0] = wake
            got, asked = tr.poll(wake, look)
            records.extend(got)
            wake = max(wake + 0.01, asked + 0.005)
    records.extend(tr.drain())
    return tr, records, looks


def _on_plan(seen, plan, slack=0.02):
    """Each look in `seen` (seconds into the stall) at or just after its
    planned time. The watchdog wakes 5-10 ms after a plan, and in made-up
    time the exact moment depends on float rounding."""
    assert len(seen) == len(plan), (seen, plan)
    for got, want in zip(seen, plan):
        assert want <= got <= want + slack, (seen, plan)


def _stall_beats(start, stop, end):
    """Heartbeats every 50 ms from 0 to `start`, none until `stop`, then
    every 50 ms again to `end`: one stall from `start` to `stop`."""
    return _beats(0.05, start) + _beats(stop, end)


def test_steady_heartbeats_make_no_record_and_no_look():
    tr, records, looks = _simulate(_beats(0.05, 30.0), 30.0)
    assert records == [] and looks == [], (records, looks)
    assert tr.count == 0


def test_one_stall_is_one_record_with_its_length_and_cpu():
    # computing for the whole stall: the Tk thread's CPU follows the clock
    def cpu_at(t):
        return 0.0 if t <= 1.0 else min(t, 1.8) - 1.0
    tr, records, looks = _simulate(_stall_beats(1.0, 1.8, 3.0), 3.0, cpu_at)
    assert len(records) == 1, records
    rec = records[0]
    assert rec.kind == 'STALL' and rec.number == 1, rec
    assert abs((rec.end[0] - rec.start[0]) - 0.8) < 1e-9
    assert abs((rec.end[1] - rec.start[1]) - 0.8) < 1e-9
    assert not rec.startup
    # one look, just past the threshold, while it lasted
    assert len(rec.samples) == 1 and len(looks) == 1, looks
    s = rec.samples[0]
    _on_plan([s.at], [tk_stall.THRESHOLD_S])
    assert abs(s.at - (looks[0] - 1.0)) < 1e-9
    assert abs(s.cpu - s.at) < 1e-9, s      # its CPU so far, not the gap's
    assert s.stack == STACK
    assert tr.longest == rec.end[0] - rec.start[0]


def test_a_gap_at_the_threshold_is_not_a_stall():
    tr = tk_stall.StallTracker((0.0, 0.0, 0.0))
    tr.beat((0.30, 0.0, 0.0))             # exactly the threshold: fine
    tr.beat((0.60, 0.0, 0.0))
    assert tr.drain() == []
    tr.beat((0.91, 0.0, 0.0))             # 0.31 s: a stall
    [rec] = tr.drain()
    assert rec.kind == 'STALL' and abs(rec.end[0] - 0.91) < 1e-9


def test_a_stall_the_watchdog_never_saw_is_still_recorded():
    tr = tk_stall.StallTracker((0.0, 0.0, 0.0))
    tr.beat((0.05, 0.0, 0.0))
    tr.beat((0.45, 0.2, 0.2))             # no poll in between
    [rec] = tr.drain()
    assert rec.samples == () and rec.number == 1
    assert abs((rec.end[1] - rec.start[1]) - 0.2) < 1e-9


def test_long_stalls_are_looked_at_on_a_capped_doubling_schedule():
    tr, records, looks = _simulate(_stall_beats(1.0, 400.0, 401.0), 401.0)
    stall = [r for r in records if r.kind == 'STALL']
    assert len(stall) == 1, records
    into = [t - 1.0 for t in looks]
    # 0.3, then doubling from 1 s, then never more than 30 s apart
    _on_plan(into, [0.3, 1, 2, 4, 8, 16, 32, 62, 92, 122, 152, 182, 212,
                    242, 272, 302, 332, 362, 392])
    kept = [s.at for s in stall[0].samples]
    assert len(kept) == tk_stall.MAX_SAMPLES
    # the first eleven, then the latest
    assert kept == into[:tk_stall.MAX_SAMPLES - 1] + [into[-1]], kept


def test_a_stall_past_hang_s_is_written_early_once_then_finished():
    tr, records, looks = _simulate(_stall_beats(1.0, 11.0, 12.0), 12.0)
    assert [r.kind for r in records] == ['STALLING', 'STALL'], records
    early, done = records
    assert early.number == done.number == 1
    assert early.start is done.start
    _on_plan([early.at - early.start[0]], [tk_stall.HANG_S])
    # the looks it had by then, the 4 s one included
    _on_plan([s.at for s in early.samples], [0.3, 1, 2, 4])
    _on_plan([s.at for s in done.samples], [0.3, 1, 2, 4, 8])
    assert abs((done.end[0] - done.start[0]) - 10.0) < 1e-9


def test_a_stall_shorter_than_hang_s_writes_no_early_record():
    _, records, _ = _simulate(_stall_beats(1.0, 4.9, 6.0), 6.0)
    assert [r.kind for r in records] == ['STALL'], records


def test_a_look_that_races_the_recovery_is_dropped():
    # The Tk thread comes back WHILE the watchdog is looking: what it saw
    # belongs to whatever ran next, not to the stall.
    tr = tk_stall.StallTracker((0.0, 0.0, 0.0))
    tr.beat((0.05, 0.0, 0.0))

    def look():
        tr.beat((0.40, 0.0, 0.0))
        return tk_stall.Look(0.0, 0.0, None, list(STACK), [], None)
    got, _ = tr.poll(0.36, look)
    assert got == []
    [rec] = tr.drain()
    assert rec.samples == (), rec.samples


def test_the_stall_before_the_first_heartbeat_is_marked_startup():
    beats = [2.0] + _beats(2.05, 3.0) + _beats(4.0, 5.0)
    _, records, _ = _simulate(beats, 5.0)
    assert [r.startup for r in records] == [True, False], records
    assert [r.number for r in records] == [1, 2]


def test_two_stalls_keep_their_own_numbers_and_stacks():
    def stack_at(t):
        return [('app.py', 1, 'first_freeze' if t < 2.0 else
                 'second_freeze')]
    beats = _stall_beats(1.0, 1.6, 3.0) + _beats(3.6, 4.0)
    _, records, _ = _simulate(beats, 4.0, stack_at=stack_at)
    assert [(r.kind, r.number) for r in records] == \
        [('STALL', 1), ('STALL', 2)], records
    assert {s.stack[0][2] for s in records[0].samples} == {'first_freeze'}
    assert {s.stack[0][2] for s in records[1].samples} == {'second_freeze'}


# ---------------------------------------------------------------------------
# the record as text, and the file
# ---------------------------------------------------------------------------

def _wall(t):
    return 1790000000.0 + t                 # a fixed epoch: stable text


def test_a_record_reads_as_documented():
    here = os.path.join(tk_stall.APP_DIR, 'tk_stall.py')
    stack = [(here, 1, 'outer'), ('/lib/x.py', 7, 'Thing.slow')]
    other = [('worker', ('/lib/w.py', 3, 'loop'))]
    samples = (
        tk_stall.Sample(0.31, 0.30, 0.31, '1.5 0.9 0.4 3/200 99', stack,
                        other, None),
        tk_stall.Sample(1.0, 0.98, 1.2, None, list(stack), [], None),
        tk_stall.Sample(2.0, None, None, None, None, None,
                        'no stack (boom)'))
    rec = tk_stall.Record('STALL', 7, (10.0, 1.0, 2.0), (12.0, 2.5, 4.0),
                          12.0, samples, False)
    text = tk_stall.format_record(rec, 'Edge Review', 4242, 'MainThread',
                                  4.0, _wall, '0.1 0.2 0.3 1/100 5')
    lines = text.splitlines()
    assert re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} STALL 2\.00 s '
                        r'in Edge Review \(pid 4242, stall 7\)', lines[0]), \
        lines[0]
    assert lines[1] == '  began 6.0 s after the window opened', lines[1]
    assert lines[2] == ('  Tk thread (MainThread) cpu +1.50 s = 75 % of the '
                        'gap; whole process cpu +2.00 s'), lines[2]
    assert lines[3] == '  load after: 0.1 0.2 0.3 1/100 5'
    assert ('  stack at +0.31 s (Tk thread cpu +0.30 s, process +0.31 s, '
            'load 1.5 0.9 0.4 3/200 99), most recent call last:') in lines
    # an app module is named bare, with its source line under it
    i = lines.index('    tk_stall.py:1 in outer')
    assert lines[i + 1] == '      #!/usr/bin/env python3', lines[i + 1]
    assert '    /lib/x.py:7 in Thing.slow' in lines
    assert ('  stack at +1.00 s (Tk thread cpu +0.98 s, process +1.20 s): '
            'unchanged') in lines
    assert ('  stack at +2.00 s (Tk thread cpu n/a, process n/a): '
            'no stack (boom)') in lines
    assert lines[-2:] == ['  other threads at +0.31 s:',
                          '    worker: /lib/w.py:3 in loop'], lines[-2:]
    assert text.endswith('\n') and text.isascii()

    early = rec._replace(kind='STALLING', end=None, at=14.5, samples=(),
                         startup=True)
    lines = tk_stall.format_record(early, 'plot window', 1, 'MainThread',
                                  10.0, _wall).splitlines()
    assert ' STALLING 4.5 s so far in plot window (pid 1, stall 7): ' \
        'still frozen' in lines[0], lines[0]
    assert lines[1] == ('  began 0.0 s after the window opened (no '
                        'heartbeat had run yet: the window was being '
                        'built)'), lines[1]
    assert lines[2] == '  no stack taken yet', lines[2]


def test_a_cut_stack_says_so():
    def deep(n):
        return deep(n - 1) if n else sys._getframe()
    stack = tk_stall._stack(deep(5), limit=3)
    assert stack[0] == (None, None, 'outer frames cut'), stack
    assert len(stack) == 4, stack
    assert all(f[2].endswith('.deep') for f in stack[1:]), stack
    assert tk_stall._frame_lines(stack)[0] == '    (outer frames cut)'
    whole = tk_stall._stack(deep(2))
    assert whole[0][0] is not None and whole[-1][2].endswith('.deep'), whole


def test_the_log_rotates_once_when_over_its_cap():
    folder = tempfile.mkdtemp(prefix='tk_stall_')
    try:
        log = os.path.join(folder, 'sub', 'tk_stall.log')   # made on demand
        recs = [f"record {k} " + 'x' * 60 + '\n' for k in range(5)]
        for rec in recs:                    # 70 bytes each, cap 100
            tk_stall.append_record(log, rec, max_bytes=100)
        with open(log, encoding='utf-8') as fh:
            live = fh.read()
        with open(log + '.1', encoding='utf-8') as fh:
            old = fh.read()
        # rotated before the 3rd and the 5th write; the 1st rotation's
        # file was replaced by the 2nd: one old generation only
        assert live == recs[4], live
        assert old == recs[2] + recs[3], old
        assert sorted(os.listdir(os.path.dirname(log))) == \
            ['tk_stall.log', 'tk_stall.log.1']
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_an_unwritable_log_goes_to_stderr_and_never_raises():
    folder = tempfile.mkdtemp(prefix='tk_stall_')
    real = sys.stderr
    try:
        blocker = os.path.join(folder, 'a_file')
        with open(blocker, 'w') as fh:
            fh.write('not a folder')
        logger = tk_stall.StallLogger(None, 'w', os.path.join(
            blocker, 'tk_stall.log'))
        sys.stderr = io.StringIO()
        logger._write('THE RECORD\n')
        said = sys.stderr.getvalue()
        assert 'cannot write' in said and 'THE RECORD' in said, said
        logger._close_clock()
    finally:
        sys.stderr = real
        shutil.rmtree(folder, ignore_errors=True)


def test_the_switch_and_the_default_place():
    path = tk_stall.log_path({})
    assert path == tk_stall.default_log_path({})
    assert os.path.basename(path) == 'tk_stall.log'
    assert os.path.basename(os.path.dirname(path)) == 'scpi_control'
    if os.name == 'nt':
        assert tk_stall.default_log_path({'LOCALAPPDATA': r'C:\L'}) == \
            r'C:\L\scpi_control\tk_stall.log'
    else:
        assert path == os.path.join(os.path.expanduser('~'), '.cache',
                                    'scpi_control', 'tk_stall.log')
    for off in ('0', 'off', ' OFF ', 'No', 'false'):
        assert tk_stall.log_path({tk_stall.ENV: off}) is None, off
    assert tk_stall.log_path({tk_stall.ENV: ''}) == path
    assert tk_stall.log_path({tk_stall.ENV: '~/x/s.log'}) == \
        os.path.expanduser('~/x/s.log')


def test_watch_switched_off_does_nothing_and_a_bad_root_does_not_raise():
    saved = os.environ.get(tk_stall.ENV)
    real = sys.stderr
    try:
        os.environ[tk_stall.ENV] = '0'
        before = threading.active_count()
        root = _FakeRoot()              # one that COULD be watched
        assert tk_stall.watch(root, 'off') is None
        assert root.jobs == {} and root.bound == [], (root.jobs, root.bound)
        assert tk_stall.watching(root) is None
        assert threading.active_count() == before
        os.environ.pop(tk_stall.ENV)
        sys.stderr = io.StringIO()
        assert tk_stall.watch(None, 'broken', path=os.devnull) is None
        assert 'not watching' in sys.stderr.getvalue()
        assert tk_stall.watching(None) is None
        assert threading.active_count() == before
    finally:
        sys.stderr = real
        if saved is None:
            os.environ.pop(tk_stall.ENV, None)
        else:
            os.environ[tk_stall.ENV] = saved


def test_the_cpu_clock_reads_another_threads_cpu_from_outside():
    """The watchdog's view of the Tk thread's CPU must be the Tk thread's
    own: measured from outside, it matches that thread's thread_time()."""
    box = {}
    ready, done = threading.Event(), threading.Event()

    def worker():
        box['clock'], box['how'] = tk_stall._cpu_clock()
        c0 = time.thread_time()
        while time.thread_time() - c0 < 0.3:
            pass
        box['own'] = time.thread_time()
        ready.set()
        done.wait(10)

    th = threading.Thread(target=worker)
    th.start()
    try:
        assert ready.wait(10)
        clock = box['clock']
        if clock is None:
            # Linux and Windows both have one; only elsewhere is it n/a
            assert os.name != 'nt' and not sys.platform.startswith(
                'linux'), box['how']
            raise _Skip('no per-thread CPU clock here', box['how'])
        seen = clock.read()
        assert abs(seen - box['own']) < 0.05, (seen, box['own'], box['how'])
        assert seen >= 0.28, seen
        # the worker now idles: the reading must not follow the READER's
        # own CPU, which this loop spends
        c0 = time.thread_time()
        while time.thread_time() - c0 < 0.2:
            pass
        assert clock.read() - seen < 0.05, (clock.read(), seen)
        clock.close()
        clock.close()                       # twice is harmless
    finally:
        done.set()
        th.join()


def _parked_for_the_test(ready, release):
    ready.set()
    release.wait(10)


def test_a_look_sees_the_watched_thread_and_names_the_others():
    """The mechanism behind every stack in the log, without Tk: a look
    taken on one thread shows where the watched thread is, and lists the
    rest by name, leaving out the watched one and the looker."""
    box = {}
    ready, release = threading.Event(), threading.Event()
    other_ready = threading.Event()

    def watched():
        box['logger'] = tk_stall.StallLogger(None, 'w', os.devnull)
        _parked_for_the_test(ready, release)

    a = threading.Thread(target=watched, name='watched-thread')
    b = threading.Thread(target=_parked_for_the_test, name='bystander',
                         args=(other_ready, release))
    a.start()
    b.start()
    try:
        assert ready.wait(10) and other_ready.wait(10)
        logger = box['logger']
        assert logger.tk_name == 'watched-thread'
        look = logger._look()
        assert look.note is None, look.note
        funcs = [f[2] for f in look.stack]
        assert '_parked_for_the_test' in funcs, funcs
        assert funcs.index('_parked_for_the_test') > funcs.index(
            'test_a_look_sees_the_watched_thread_and_names_the_others.'
            '<locals>.watched'), funcs
        others = [name for name, _ in look.threads]
        assert 'bystander' in others, others
        assert 'watched-thread' not in others and 'MainThread' not in others
        if logger.clock is not None:
            assert look.cpu is not None and look.cpu >= 0.0
        logger._close_clock()
    finally:
        release.set()
        a.join()
        b.join()


class _FakeRoot:
    """Just enough of a Tk root for StallLogger, with no tkinter: after,
    after_cancel and bind, an event loop run on the calling thread, and a
    close that fires the <Destroy> bindings with the root as the widget."""

    def __init__(self):
        self.jobs = {}
        self.bound = []
        self.n = 0

    def after(self, ms, func, *args):
        self.n += 1
        self.jobs[f"after#{self.n}"] = (time.monotonic() + ms / 1000.0,
                                        func, args)
        return f"after#{self.n}"

    def after_cancel(self, job):
        self.jobs.pop(job, None)

    def bind(self, sequence, func, add=None):
        self.bound.append((sequence, func))

    def run(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            now = time.monotonic()
            for job, (due, func, args) in sorted(self.jobs.items()):
                if due <= now and self.jobs.pop(job, None) is not None:
                    func(*args)
            time.sleep(0.002)

    def close(self):
        event = type('Event', (), {'widget': self})()
        for sequence, func in self.bound:
            if sequence == '<Destroy>':
                func(event)


def test_the_logger_end_to_end_without_tk():
    """The whole logger (heartbeat, watchdog, CPU clock, the file) on a
    fake root, so Linux runs it for real too, /proc/loadavg included."""
    folder = tempfile.mkdtemp(prefix='tk_stall_')
    saved = os.environ.pop(tk_stall.ENV, None)
    root = _FakeRoot()
    try:
        log = os.path.join(folder, 'tk_stall.log')
        logger = tk_stall.watch(root, 'fake window', path=log)
        assert logger is not None and tk_stall.watching(root) is logger
        root.run(0.3)
        root.after(0, _block_the_tk_thread_for_the_test, 0.5)
        root.run(0.6)
        root.close()
        assert not logger.thread.is_alive() and root.jobs == {}, root.jobs
        with open(log, encoding='utf-8') as fh:
            text = fh.read()
        entries = _entries(text)
        assert entries[0][0] == 'START' and entries[-1][0] == 'STOP', text
        [(kind, rec)] = [(k, r) for k, r in entries
                         if '_block_the_tk_thread_for_the_test' in r]
        assert kind == 'STALL' and 'in fake window (pid ' in rec, rec
        gap, cpu = _gap_and_cpu(rec)
        assert 0.45 <= gap <= 2.5 and cpu < 0.15, rec
        if sys.platform.startswith('linux'):
            assert '\n  load after: ' in rec, rec
            assert re.search(r'stack at \+0\.\d\d s \(Tk thread cpu '
                             r'\+\d\.\d\d s, process \+\d\.\d\d s, load ',
                             rec), rec
            assert 'cpu clock: pthread_getcpuclockid' in text, text
        else:
            assert 'load after' not in rec and ', load ' not in rec, rec
    finally:
        root.close()
        if saved is not None:
            os.environ[tk_stall.ENV] = saved
        shutil.rmtree(folder, ignore_errors=True)


def _hash_for_the_test(stop):
    data = b'x' * 4000000
    while not stop.is_set():
        hashlib.sha256(data).digest()      # hashes with the GIL released


def test_other_threads_cpu_is_not_charged_to_the_tk_thread():
    """The split the issue reads stalls by: a Tk thread that waits while
    another thread of the same program computes must show ~0 s of its own
    CPU and the other thread's CPU under 'whole process'."""
    folder = tempfile.mkdtemp(prefix='tk_stall_')
    saved = os.environ.pop(tk_stall.ENV, None)
    root = _FakeRoot()
    stop = threading.Event()
    hasher = threading.Thread(target=_hash_for_the_test, args=(stop,))
    try:
        log = os.path.join(folder, 'tk_stall.log')
        tk_stall.watch(root, 'fake window', path=log)
        root.run(0.3)
        hasher.start()
        root.after(0, _block_the_tk_thread_for_the_test, 0.5)
        root.run(0.6)
        stop.set()
        hasher.join()
        root.close()
        with open(log, encoding='utf-8') as fh:
            entries = _entries(fh.read())
        [rec] = [r for k, r in entries
                 if '_block_the_tk_thread_for_the_test' in r]
        _, cpu = _gap_and_cpu(rec)
        whole = float(re.search(r'whole process cpu \+(\d+\.\d+) s',
                                rec).group(1))
        assert cpu < 0.15 and whole >= 0.2, rec
    finally:
        stop.set()
        if hasher.ident is not None:
            hasher.join()
        root.close()
        if saved is not None:
            os.environ[tk_stall.ENV] = saved
        shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------------------
# a real Tk root
# ---------------------------------------------------------------------------

def _tk_root():
    try:
        import tkinter as tk
    except ImportError as e:
        raise _Skip('no tkinter', str(e))
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip('no display for Tk', str(e))
    root.withdraw()
    return root


def _pump(root, seconds):
    """Run the root's event loop for `seconds`; stops early when the root
    has been destroyed."""
    import tkinter as tk
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            root.update()
        except tk.TclError:
            return
        time.sleep(0.005)


class _Logged:
    """A temp log, the switch cleared, and the root destroyed at the end."""

    def __enter__(self):
        self.folder = tempfile.mkdtemp(prefix='tk_stall_')
        self.path = os.path.join(self.folder, 'tk_stall.log')
        self.saved = os.environ.pop(tk_stall.ENV, None)
        self.root = _tk_root()
        return self

    def text(self):
        try:
            with open(self.path, encoding='utf-8') as fh:
                return fh.read()
        except FileNotFoundError:
            return ''

    def records(self):
        return _entries(self.text())

    def __exit__(self, *exc):
        try:
            self.root.destroy()
        except Exception:
            pass
        if self.saved is not None:
            os.environ[tk_stall.ENV] = self.saved
        shutil.rmtree(self.folder, ignore_errors=True)
        return False


def _block_the_tk_thread_for_the_test(seconds):
    time.sleep(seconds)          # a stand-in for a share or instrument wait


def _spin_the_tk_thread_for_the_test(cpu_seconds):
    c0 = time.thread_time()
    while time.thread_time() - c0 < cpu_seconds:
        pass


def _close_after_a_wait_for_the_test(root, seconds):
    time.sleep(seconds)          # like a close that waits for a worker
    root.destroy()


def _gap_and_cpu(record_text):
    m = re.search(r' STALL (\d+\.\d+) s in ', record_text)
    c = re.search(r'Tk thread \(\w+\) cpu \+(\d+\.\d+) s', record_text)
    return float(m.group(1)), float(c.group(1))


def test_tk_a_half_second_block_is_one_record_naming_the_blocker():
    with _Logged() as t:
        logger = tk_stall.watch(t.root, 'test window', path=t.path)
        assert logger is not None and logger.thread.is_alive()
        _pump(t.root, 0.4)
        t.root.after(0, _block_the_tk_thread_for_the_test, 0.5)
        _pump(t.root, 0.8)
        t.root.destroy()
        records = t.records()
        named = [(k, r) for k, r in records
                 if '_block_the_tk_thread_for_the_test' in r]
        assert len(named) == 1, t.text()
        kind, rec = named[0]
        assert kind == 'STALL', t.text()
        assert f'in test window (pid {os.getpid()}, stall ' in rec, rec
        gap, cpu = _gap_and_cpu(rec)
        assert 0.45 <= gap <= 2.5, rec
        assert cpu < 0.15, rec               # it slept: no Tk-thread CPU
        kinds = [k for k, _ in records]
        assert kinds[0] == 'START' and kinds[-1] == 'STOP', kinds
        assert 'STALLING' not in kinds, t.text()


def test_tk_a_busy_tk_thread_shows_its_cpu():
    with _Logged() as t:
        tk_stall.watch(t.root, 'test window', path=t.path)
        _pump(t.root, 0.3)
        t.root.after(0, _spin_the_tk_thread_for_the_test, 0.4)
        _pump(t.root, 0.8)
        t.root.destroy()
        [rec] = [r for k, r in t.records()
                 if '_spin_the_tk_thread_for_the_test' in r]
        gap, cpu = _gap_and_cpu(rec)
        assert cpu >= 0.3 and gap >= cpu - 0.05, rec


def test_tk_one_logger_per_root_and_it_stops_with_the_window():
    with _Logged() as t:
        first = tk_stall.watch(t.root, 'test window', path=t.path)
        again = tk_stall.watch(t.root, 'another name', path=t.path)
        assert first is again and tk_stall.watching(t.root) is first
        _pump(t.root, 0.3)
        t.root.destroy()
        assert first.stopped and not first.thread.is_alive()
        assert tk_stall.watching(t.root) is None
        text = t.text()
        kinds = [k for k, _ in t.records()]
        assert kinds[0] == 'START' and kinds[-1] == 'STOP', text
        # a stall here could only be the desktop's (other suites run Tk
        # windows alongside); the STOP line must count whatever there was
        n = kinds.count('STALL')
        assert f" STOP test window (pid {os.getpid()}): watched " in text
        assert f"; {n} stall{'' if n == 1 else 's'}" in text, text
        time.sleep(3 * tk_stall.THRESHOLD_S)   # a live watchdog would log
        assert t.text() == text, t.text()
        root2 = _tk_root()
        try:
            second = tk_stall.watch(root2, 'test window 2', path=t.path)
            assert second is not None and second is not first
        finally:
            root2.destroy()
        assert not second.thread.is_alive()


def test_tk_a_child_widget_closing_does_not_stop_the_logger():
    """<Destroy> bound on the root fires for every child widget too: only
    the root's own may stop the logger."""
    with _Logged() as t:                   # skips first when there is no Tk
        import tkinter as tk
        logger = tk_stall.watch(t.root, 'test window', path=t.path)
        child = tk.Frame(t.root)
        child.pack()
        _pump(t.root, 0.2)
        child.destroy()
        _pump(t.root, 0.2)
        assert not logger.stopped and logger.thread.is_alive()
        t.root.after(0, _block_the_tk_thread_for_the_test, 0.5)
        _pump(t.root, 0.8)
        t.root.destroy()
        assert [k for k, r in t.records()
                if '_block_the_tk_thread_for_the_test' in r] == ['STALL'], \
            t.text()


def test_tk_a_close_that_waits_first_is_recorded():
    with _Logged() as t:
        tk_stall.watch(t.root, 'test window', path=t.path)
        _pump(t.root, 0.3)
        t.root.after(0, _close_after_a_wait_for_the_test, t.root, 0.5)
        _pump(t.root, 3.0)                 # returns once the root is gone
        records = t.records()
        named = [(k, r) for k, r in records
                 if '_close_after_a_wait_for_the_test' in r]
        assert [k for k, _ in named] == ['STALL'], t.text()
        assert 0.45 <= _gap_and_cpu(named[0][1])[0] <= 2.5, named[0][1]
        assert records[-1][0] == 'STOP', t.text()   # and it came after


def test_tk_switched_off_leaves_the_window_alone():
    with _Logged() as t:
        os.environ[tk_stall.ENV] = 'off'
        try:
            assert tk_stall.watch(t.root, 'test window', path=t.path) is None
            assert not t.root.tk.call('after', 'info')
            assert t.root.bind('<Destroy>') == ''
            _pump(t.root, 0.2)
            assert not os.path.exists(t.path)
        finally:
            os.environ.pop(tk_stall.ENV, None)


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block; run_tests.py explains why.
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    ran = skipped = 0
    reasons = []
    failed = []
    for fn in fns:
        try:
            fn()
        except _Skip as why:
            skipped += 1
            if why.reason not in reasons:
                reasons.append(why.reason)
            print(f"skip {fn.__name__}  ({why})")
            continue
        except Exception:
            ran += 1
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
        ran += 1
        print(f"ok  {fn.__name__}")
    tail = f"{ran} of {len(fns)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped, {'; '.join(reasons)})"
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
