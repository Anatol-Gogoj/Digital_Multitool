#!/usr/bin/env python3
"""Window close zeroes a LIVE run's SG channel when the run has not
stopped in time, and a stopping run never writes a new level (#460).

Closing the window asks a running SLDEA run to stop and pumps Tk for up to
about 3 s. The run zeroes its own channel in its finally block (offset to
0 V, then output off). A run blocked longer than that, in a scope read or a
photo, used to get only both SG outputs switched off: its last level stayed
set on the channel, and the next Output ON put it straight back on the
Trek. What is pinned here:

* a run still flagged after the wait has the channel it set to DC zeroed
  first, then both outputs go off, in that order, each best-effort;
* no offset write when the run finished within the wait, when it never
  set its channel to DC (closed during camera startup), on a DRY run, or
  with no run at all: OFST is written only where the run itself wrote
  levels;
* a dead link on the zero still switches both outputs off and closes the
  window;
* the run marks its channel after the DC write and before output ON, and
  _sldea_finished clears the mark; a DRY run never sets it;
* end to end, on the real sldea_run and worker: a close during a scope
  read that outlasts the wait leaves the channel at 0 V, Abort during a
  scope read writes no new level after it, and a stop that comes while
  the worker waits for the SG's I/O lock (another thread holding it)
  stops the level too, because the stop is checked again under that
  lock, and every level is written while the worker still holds the lock
  it checked the stop under.

The close-handler cases run the REAL _on_app_close on a Tk-free stub app,
against a fake SG that records every call in order. The end-to-end cases
use the scope-lock suite's fakes (tests/test_scope_live_lock.py).

Run: .venv/bin/python tests/test_app_close_zeroes_sg.py
"""
import contextlib
import math
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import gui  # noqa: E402
import test_scope_live_lock as L  # noqa: E402

G = gui.InstrumentControlGUI
WAIT_TICKS = 30                 # the close handler's wait, 30 x 0.1 s


class _SG(L._FakeSG):
    """The recording SG, plus the session calls the close handler makes.
    A method named in `fail` records its call, then raises, as a dead link
    does after its timeout."""

    def __init__(self, fail=()):
        super().__init__()
        self.fail = set(fail)

    def _maybe_fail(self, name):
        if name in self.fail:
            raise IOError('VI_ERROR_TMO (fake dead link)')

    def set_offset(self, channel, offset_v):
        super().set_offset(channel, offset_v)
        self._maybe_fail('set_offset')

    def set_output(self, channel, on):
        super().set_output(channel, on)
        self._maybe_fail('set_output')

    def go_local(self):
        self.writes.append(('go_local',))

    def close(self):
        self.writes.append(('close',))

    def offsets(self, channel):
        return [w[2] for w in self.writes
                if w[0] == 'set_offset' and w[1] == channel]


class _Root(L._Root):
    """The suite's Tk root, with what window close calls on it: update()
    plays the queued callbacks, as the real one does, and destroy() is
    only noted."""

    def __init__(self):
        super().__init__()
        self.updates = 0
        self.destroyed = False

    def update(self):
        self.updates += 1
        self.run_pending()

    def destroy(self):
        self.destroyed = True


class _App(L._App):
    """The scope-lock suite's stub app with the real close handler, no PSU
    or DMM, and the recording SG above. `marks` notes, per run.log line,
    which channel the run had marked as set to DC at that moment."""
    _on_app_close = G._on_app_close

    def __init__(self, tmp='.', sg=None, **kw):
        super().__init__(tmp, **kw)
        self.root = _Root()
        self.sg = sg if sg is not None else _SG()
        self.psu = self.dmm = None
        self._sldea_sg_dc_ch = None
        self.marks = []

    def _sldea_log(self, msg):
        self.lines.append(str(msg))
        self.marks.append(getattr(self, '_sldea_sg_dc_ch', None))


class _Clock:
    """gui.time for the close-handler cases: sleep() is only counted, so
    the ~3 s wait costs nothing. Everything else is the real module. Only
    used where no worker thread runs, since the worker reads gui.time
    too."""

    def __init__(self):
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def __getattr__(self, name):
        return getattr(time, name)


@contextlib.contextmanager
def _fast_clock():
    saved = gui.time
    clock = _Clock()
    gui.time = clock
    try:
        yield clock
    finally:
        gui.time = saved


def _stuck_run(app, ch, dc=True, live=True):
    """The state a run is in when the close handler's wait runs out: still
    flagged, its channel claimed (LIVE), and marked as set to DC once the
    worker got that far."""
    app._sldea_running = True
    app._sldea_stop = False
    app._sldea_live_ch = ch if live else None
    app._sldea_sg_dc_ch = ch if (live and dc) else None


OUTPUTS_OFF = [('set_output', 1, False), ('set_output', 2, False)]
SESSION_END = [('go_local',), ('close',)]


# --------------------------------------------------------------------------
# The close handler, on its own
# --------------------------------------------------------------------------

def test_a_run_still_running_has_its_channel_zeroed_then_both_outputs_off():
    """The run never finishes within the wait: the channel it set to DC
    gets offset 0 V first, then both outputs go off, then the session is
    handed back and the window goes."""
    app = _App()
    _stuck_run(app, ch=2)
    with _fast_clock() as clock:
        app._on_app_close()
    assert app.sg.writes == ([('set_offset', 2, 0.0)] + OUTPUTS_OFF
                             + SESSION_END), app.sg.writes
    # 0.0 == -0.0, so the list compare above cannot see the sign
    assert math.copysign(1.0, app.sg.offsets(2)[0]) == 1.0, \
        "close must write +0 V, not -0"
    assert app._sldea_stop, "close must ask the run to stop"
    assert len(clock.sleeps) == WAIT_TICKS, clock.sleeps
    assert app.root.updates == WAIT_TICKS, app.root.updates
    assert app.root.destroyed


def test_the_zero_goes_to_the_run_channel_only():
    """CH1 runs: only CH1's offset is written. CH2 may hold any waveform,
    and its offset is the operator's."""
    app = _App()
    _stuck_run(app, ch=1)
    with _fast_clock():
        app._on_app_close()
    assert app.sg.offsets(1) == [0.0], app.sg.writes
    assert app.sg.offsets(2) == [], app.sg.writes


def test_a_run_that_finishes_within_the_wait_is_not_written_again():
    """The worker finished its finally block (zero, then off) and queued
    _sldea_finished, which the wait's first update() plays: the close
    handler writes no offset of its own and stops waiting."""
    app = _App()
    _stuck_run(app, ch=2)
    app.root.after(0, app._sldea_finished)
    with _fast_clock() as clock:
        app._on_app_close()
    assert app.sg.writes == OUTPUTS_OFF + SESSION_END, app.sg.writes
    assert not app._sldea_running and app._sldea_sg_dc_ch is None
    assert len(clock.sleeps) == 1, clock.sleeps
    assert app.root.destroyed


def test_a_run_that_never_set_its_channel_to_dc_gets_no_offset_write():
    """Closed during camera startup: the run has claimed CH2 but written
    nothing to it, so the channel still holds the operator's waveform,
    whatever its mode. Outputs off only, as before."""
    app = _App()
    _stuck_run(app, ch=2, dc=False)
    with _fast_clock():
        app._on_app_close()
    assert app.sg.writes == OUTPUTS_OFF + SESSION_END, app.sg.writes


def test_a_dry_run_gets_no_offset_write():
    """A DRY run never commands the SG, so close has nothing to zero."""
    app = _App()
    _stuck_run(app, ch=1, live=False)
    with _fast_clock() as clock:
        app._on_app_close()
    assert app.sg.writes == OUTPUTS_OFF + SESSION_END, app.sg.writes
    assert len(clock.sleeps) == WAIT_TICKS, clock.sleeps


def test_no_run_means_no_wait_and_no_offset_write():
    app = _App()
    with _fast_clock() as clock:
        app._on_app_close()
    assert app.sg.writes == OUTPUTS_OFF + SESSION_END, app.sg.writes
    assert clock.sleeps == [] and app.root.updates == 0
    assert not app._sldea_stop


def test_a_stale_mark_without_a_running_run_writes_no_offset():
    """The mark alone is not enough: with no run flagged, close leaves the
    offset alone even if the mark was somehow left set."""
    app = _App()
    app._sldea_sg_dc_ch = 2
    with _fast_clock():
        app._on_app_close()
    assert app.sg.writes == OUTPUTS_OFF + SESSION_END, app.sg.writes


def test_a_dead_link_on_the_zero_still_switches_both_outputs_off():
    """The zero times out: both outputs are still tried, the session is
    still handed back, and the window still goes."""
    app = _App(sg=_SG(fail={'set_offset'}))
    _stuck_run(app, ch=2)
    with _fast_clock():
        app._on_app_close()
    assert app.sg.writes == ([('set_offset', 2, 0.0)] + OUTPUTS_OFF
                             + SESSION_END), app.sg.writes
    assert app.root.destroyed


def test_a_dead_link_everywhere_still_closes_the_window():
    app = _App(sg=_SG(fail={'set_offset', 'set_output'}))
    _stuck_run(app, ch=1)
    with _fast_clock():
        app._on_app_close()
    assert app.sg.writes == ([('set_offset', 1, 0.0)] + OUTPUTS_OFF
                             + SESSION_END), app.sg.writes
    assert app.root.destroyed


# --------------------------------------------------------------------------
# The real run: the DC mark, and no level after a stop
# --------------------------------------------------------------------------

def _ramp_profile():
    """1 kV over 3 s, then a short landing: long enough that a tick blocked
    mid-ramp comes back to a level different from the last one written."""
    return L._short_profile(ramp_s=3.0, landing_s=1.0), None


def _live_app(tmp):
    app = _App(tmp, dry=False, real_worker=True, wd_on=True)
    app._sldea_build_profile = _ramp_profile
    return app


def _block_first_ramp_read(app, action=None):
    """Make the worker's first I_Out read after the ramp has started block
    until `release` is set; `entered` is set once it blocks. `action()`
    runs on the worker's thread as the read starts, before it blocks."""
    entered, release = threading.Event(), threading.Event()
    hit = []

    def on_read(channel, caller):
        if (caller == '_sldea_worker' and channel == 3 and not hit
                and L._ramping(app)):
            hit.append(len(app.sg.writes))
            if action is not None:
                action()
            entered.set()
            assert release.wait(30), "the test never released the read"
    app.scope.on_read = on_read
    return entered, release, hit


def test_the_run_marks_its_channel_after_the_dc_write_and_before_output_on():
    """The mark is set between the run's DC write and its output ON, so it
    never names a channel the run has not set to DC, and it is set before
    any level can be on the Trek. _sldea_finished clears it."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)):
        app = _live_app(tmp)
        app._sldea_build_profile = lambda: (L._short_profile(), None)
        seen = []
        sg = app.sg
        inner_wave, inner_out = sg.set_basic_wave, sg.set_output

        def set_basic_wave(channel, **params):
            seen.append(('set_basic_wave', app._sldea_sg_dc_ch))
            inner_wave(channel, **params)

        def set_output(channel, on):
            seen.append(('set_output', on, app._sldea_sg_dc_ch))
            inner_out(channel, on)
        sg.set_basic_wave, sg.set_output = set_basic_wave, set_output
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert seen[0] == ('set_basic_wave', None), seen
        assert seen[1] == ('set_output', True, 1), seen
        assert 1 in app.marks, app.marks
        assert app._sldea_sg_dc_ch == 1     # until the Tk side finishes
        app.root.run_pending()
        assert app._sldea_sg_dc_ch is None and not app._sldea_running


def test_a_dry_run_never_marks_a_channel():
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)):
        app = _App(tmp, dry=True, real_worker=True)
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert app.lines, "the DRY run logged nothing"
        assert set(app.marks) == {None}, app.marks
        assert app.sg.writes == [], app.sg.writes


def test_abort_during_a_scope_read_writes_no_new_level():
    """Abort lands while the worker waits on a scope read mid-ramp. The
    tick it is in used to go on to write the next ramp level; now the
    level writes stop at the Abort and the next write is the zero."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)):
        app = _live_app(tmp)
        entered, release, hit = _block_first_ramp_read(app, app.sldea_abort)
        release.set()                       # Abort only; nothing blocks
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert hit, "the worker never read I_Out while ramping"
        after = app.sg.writes[hit[0]:]
        assert after == [('set_offset', 1, 0.0), ('set_output', 1, False)], \
            after
        assert any(ln.startswith('run aborted') for ln in app.lines), \
            app.lines


class _GateLock:
    """The SG's I/O lock (what instruments._io_lock hands out), with a hook
    run as a thread is let in, before the holder's first statement: the
    moment a thread that was queued behind another holder gets the lock."""

    def __init__(self, on_enter):
        self.inner = threading.RLock()
        self.on_enter = on_enter
        self.entries = 0

    def __enter__(self):
        self.inner.acquire()
        self.entries += 1
        self.on_enter()
        return self

    def __exit__(self, *exc):
        self.inner.release()
        return False


def test_a_stop_that_comes_while_the_run_waits_for_the_sg_lock_still_holds():
    """Another thread (Continuous Logging reads the SG) holds the SG's I/O
    lock past close's wait. The worker passed its first stop check before
    the stop, and is let into the lock only after it: close or Abort has
    set the stop meanwhile, and close's zero may already have gone in.
    The worker checks again under the lock and writes no level."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)):
        app = _live_app(tmp)
        hit = []

        def let_in():
            if L._ramping(app) and not hit:
                hit.append(len(app.sg.writes))
                app._sldea_stop = True       # set while it waited
        gate = _GateLock(let_in)
        app.sg.__dict__['_io_rlock'] = gate
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert hit, "the drive write never took the SG's I/O lock"
        after = app.sg.writes[hit[0]:]
        assert after == [('set_offset', 1, 0.0), ('set_output', 1, False)], \
            after
        # every level the run wrote went through the lock, and so did the
        # one it then did not write
        levels = [w for w in app.sg.writes[:hit[0]] if w[0] == 'set_offset']
        assert gate.entries == len(levels) + 1, (gate.entries, levels)


class _OwnedLock:
    """The SG's I/O lock, able to say whether the calling thread holds it.
    owner and depth change only while the lock is held."""

    def __init__(self):
        self.inner = threading.RLock()
        self.owner = None
        self.depth = 0

    def __enter__(self):
        self.inner.acquire()
        self.owner = threading.get_ident()
        self.depth += 1
        return self

    def __exit__(self, *exc):
        self.depth -= 1
        if self.depth == 0:
            self.owner = None
        self.inner.release()
        return False

    def held_here(self):
        return self.owner == threading.get_ident()


def test_every_level_is_written_under_the_lock_its_stop_check_took():
    """The stop check under the SG's lock only helps if the level write
    happens before that lock is let go: checked under the lock, then
    written after it is released, close's zero can land in between. The
    recording SG never takes the lock itself, so the write must find the
    worker still holding it (second adversarial review, 2026-10-19)."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)):
        app = _live_app(tmp)
        gate = _OwnedLock()
        app.sg.__dict__['_io_rlock'] = gate
        unlocked = []
        inner = app.sg.set_offset

        def set_offset(channel, offset_v):
            worker = threading.current_thread() is not threading.main_thread()
            if worker and offset_v != 0.0 and not gate.held_here():
                unlocked.append((channel, offset_v))
            inner(channel, offset_v)
        app.sg.set_offset = set_offset
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        levels = [w for w in app.sg.writes
                  if w[0] == 'set_offset' and w[2] != 0.0]
        assert levels, "the run wrote no level"
        assert unlocked == [], unlocked


def test_close_during_a_long_scope_read_leaves_the_run_channel_at_0v():
    """The worker is stuck in a scope read mid-ramp for longer than the
    close handler's ~3 s wait. Close zeroes the run's channel and switches
    both outputs off; when the read comes back, the worker writes no new
    level. Its finally block's zero still reaches this fake SG, which
    takes writes after close(); in the app that session is closed by then
    and those writes fail."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)):
        app = _live_app(tmp)
        entered, release, hit = _block_first_ramp_read(app)
        try:
            app.sldea_run()
            assert entered.wait(30), app.lines
            assert app._sldea_running and app._sldea_sg_dc_ch == 1
            n = len(app.sg.writes)
            app._on_app_close()             # the real ~3 s wait
            closing = app.sg.writes[n:]
            assert closing == ([('set_offset', 1, 0.0)] + OUTPUTS_OFF
                               + SESSION_END), closing
            assert app.root.destroyed
        finally:
            # the worker must be done with the run folder before the
            # temporary directory goes, pass or fail
            release.set()
            done = app.worker_done.wait(30)
        assert done, app.lines
        assert app.worker_error is None, repr(app.worker_error)
        later = app.sg.writes[n + len(closing):]
        assert later == [('set_offset', 1, 0.0), ('set_output', 1, False)], \
            later
        assert app.sg.offsets(1)[-1] == 0.0, app.sg.writes


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
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
    raise SystemExit(_run())
