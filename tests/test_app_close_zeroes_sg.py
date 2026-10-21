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
  it checked the stop under;
* a close whose offset and output-off writes on the run's channel both
  went through records that (#472), and so does a close whose output-off
  went through on the channel of a run that never marked one (never
  switched it on), holding the SG's I/O lock from those writes until the
  session is closed, so a write queued behind it lands on the closed
  session. Once a close has begun, the run's own zero takes that lock
  and reads the record; failing on the closed session, it then logs what
  the close did instead of FAILED TO ZERO, with no NOT ZEROED status and
  no box. The alarm stays whenever the channel may be on or may still
  hold the run's level: a close that failed (dead link), zeroed another
  channel or another SG handle, zeroed only after the run's own zero had
  failed, or only switched off a channel the run had marked, and a
  failed zero with no close at all. With no close begun, the run's zero
  is made as before: unlocked, reading no record.

The close-handler cases run the REAL _on_app_close on a Tk-free stub app,
against a fake SG that records every call in order. The end-to-end cases
use the scope-lock suite's fakes (tests/test_scope_live_lock.py). The
stub app's Tk hand-offs (_sldea_log, _sldea_set_status, root.after) fail
when a worker thread makes one while holding an SG I/O lock: window close
waits for that lock on the Tk thread, so in the app that would deadlock.

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


class _SessionSG(_SG):
    """The recording SG with a session, as pyvisa has one (#472): once
    close() has run, every write is still recorded but raises, as a write
    to a closed session does. `dead` makes every write raise, as a dead
    link does after its timeout, and `dead_for_run` only the writes made
    off the main thread, which in these tests are the run's. `fail` also
    takes (method, channel). `on_zero(channel)` runs on the run's thread
    as an offset write of 0 V starts, before it is recorded. With
    `locking`, each write takes the SG's I/O lock around itself, as
    VisaInstrument.write does."""
    CLOSED = 'Invalid session handle. The resource might be closed.'

    def __init__(self, fail=(), locking=False):
        super().__init__(fail)
        self.closed = self.dead = self.dead_for_run = False
        self.on_zero = None
        self.locking = locking

    def _fail_now(self, name, channel):
        run = threading.current_thread() is not threading.main_thread()
        if self.closed:
            raise IOError(self.CLOSED)
        if (self.dead or (self.dead_for_run and run) or name in self.fail
                or (name, channel) in self.fail):
            raise IOError('VI_ERROR_TMO (fake dead link)')

    def _write(self, record):
        name, channel = record[0], record[1]
        if not self.locking:
            self.writes.append(record)
            self._fail_now(name, channel)
            return
        with gui._io_lock(self):
            self.writes.append(record)
            self._fail_now(name, channel)

    def set_load_polarity(self, channel, load=None, polarity=None):
        self._write(('set_load_polarity', channel, load))

    def set_basic_wave(self, channel, **params):
        self._write(('set_basic_wave', channel, params))

    def set_offset(self, channel, offset_v):
        if (self.on_zero is not None and offset_v == 0.0
                and threading.current_thread()
                is not threading.main_thread()):
            self.on_zero(channel)
        self._write(('set_offset', channel, offset_v))

    def set_output(self, channel, on):
        self._write(('set_output', channel, on))

    def close(self):
        super().close()
        self.closed = True


def _holds_sg_lock(sg):
    """True when the calling thread holds `sg`'s I/O lock: whichever lock
    a test installed as its `_io_rlock`, or the RLock instruments._io_lock
    makes. False with no SG or no lock yet."""
    lock = sg.__dict__.get('_io_rlock') if sg is not None else None
    if lock is None:
        return False
    if hasattr(lock, 'held_here'):
        return lock.held_here()
    owned = getattr(getattr(lock, 'inner', lock), '_is_owned', None)
    return bool(owned()) if owned is not None else False


# Every Tk hand-off a worker thread made while holding an SG I/O lock (each
# stub app's _tk_guard adds to it). _run clears it before each case and
# fails the case if it is not empty after.
TK_UNDER_LOCK = []


class _Root(L._Root):
    """The suite's Tk root, with what window close calls on it: update()
    plays the queued callbacks, as the real one does, and destroy() is
    only noted. `on_update()`, when set, runs at the start of each
    update(): inside the close's wait. after() first calls
    `guard('root.after')`, which the app uses to fail a hand-off made
    while holding the SG's lock."""

    def __init__(self):
        super().__init__()
        self.updates = 0
        self.destroyed = False
        self.on_update = None
        self.guard = None

    def after(self, ms, fn=None, *args):
        if self.guard is not None:
            self.guard('root.after')
        return super().after(ms, fn, *args)

    def update(self):
        self.updates += 1
        if self.on_update is not None:
            self.on_update()
        self.run_pending()

    def destroy(self):
        self.destroyed = True


class _App(L._App):
    """The scope-lock suite's stub app with the real close handler, no PSU
    or DMM, and the recording SG above. `marks` notes, per run.log line,
    which channel the run had marked as set to DC at that moment;
    `statuses` notes the run's status lines, and `on_log(line)`, when set,
    runs as each line is logged, on the thread that logs it.

    The Tk hand-offs (_sldea_log, _sldea_set_status, root.after) fail when
    a worker thread makes one while it holds an SG I/O lock, and note it in
    `tk_under_lock` (and TK_UNDER_LOCK). In the app each one waits for the
    Tk thread, and window close waits for that lock on the Tk thread, so
    it would deadlock; these stubs never wait, so nothing else would show
    it (#472, after #471's guard). On the Tk thread a Tk call cannot wait
    for itself, so the close, which holds the lock there, is not checked.
    The SGs checked are the app's and the one the run captured."""
    _on_app_close = G._on_app_close

    def __init__(self, tmp='.', sg=None, **kw):
        super().__init__(tmp, **kw)
        self.root = _Root()
        self.sg = sg if sg is not None else _SG()
        self.psu = self.dmm = None
        self._sldea_sg_dc_ch = None
        self._sldea_close_zeroed = None
        self.marks = []
        self.statuses = []
        self.on_log = None
        self.run_sg = None
        self.tk_under_lock = []
        self.root.guard = self._tk_guard

    def _tk_guard(self, what):
        if threading.current_thread() is threading.main_thread():
            return
        for sg in (self.__dict__.get('sg'), self.run_sg):
            if _holds_sg_lock(sg):
                self.tk_under_lock.append(what)
                TK_UNDER_LOCK.append(what)
                raise AssertionError(f"{what} called by a worker thread "
                                     f"while it holds the SG's I/O lock")

    def _sldea_worker(self, *args, **kw):
        self.run_sg = self.sg           # the handle the run captures
        super()._sldea_worker(*args, **kw)

    def _sldea_log(self, msg):
        self._tk_guard('_sldea_log')
        self.lines.append(str(msg))
        self.marks.append(getattr(self, '_sldea_sg_dc_ch', None))
        if self.on_log is not None:
            self.on_log(str(msg))

    def _sldea_set_status(self, text, *a, **k):
        self._tk_guard('_sldea_set_status')
        self.statuses.append(text)


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
# What run.log says in place of the alarm (#472) when the close zeroed CH1,
# and when it switched off CH1 of a run that had never switched it on
CLOSE_LINE = ("SG CH1 is at 0 V and off: window close set it to 0 V and "
              "switched it off, then closed the SG session, so this run's "
              "own zeroing found the session already closed")
OFF_LINE = ("SG CH1 is off: this run never switched it on, and window close "
            "switched it off and closed the SG session, so this run's own "
            "zeroing found the session already closed")


def _close_lines(app):
    """run.log's lines that speak for a close in place of the alarm."""
    return [ln for ln in app.lines
            if ln.startswith('SG CH') and 'window close' in ln]


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


def test_a_close_records_the_zero_only_when_both_writes_went_through():
    """#472. For a run that marked its channel, the record is (SG handle,
    channel, True), set only when the offset write AND the output-off
    write on that channel both went through: either one failing may leave
    the channel at a level or switched on. The other channel failing to
    switch off leaves the run's channel at 0 V and off, so the record
    stands. The SG writes are the same either way."""
    for fail, ch, recorded in (
            (set(), 2, True),
            ({'set_offset'}, 1, False),
            ({'set_output'}, 1, False),
            ({('set_output', 2)}, 2, False),
            ({('set_output', 2)}, 1, True),
            ({'set_offset', 'set_output'}, 2, False)):
        app = _App(sg=_SessionSG(fail=fail))
        _stuck_run(app, ch=ch)
        with _fast_clock():
            app._on_app_close()
        case = (fail, ch)
        assert app.sg.writes == ([('set_offset', ch, 0.0)] + OUTPUTS_OFF
                                 + SESSION_END), (case, app.sg.writes)
        rec = app._sldea_close_zeroed
        if recorded:
            assert (rec is not None and rec[0] is app.sg
                    and rec[1:] == (ch, True)), (case, rec)
        else:
            assert rec is None, (case, rec)
        assert app.root.destroyed, case


def test_a_close_records_switching_off_a_channel_the_run_never_marked():
    """#472, from #471's review. A LIVE run closed before it set its
    channel to DC (camera start-up, or its start writes found the stop)
    never switched that channel on. The close writes no offset there, as
    before, and records (SG handle, channel, False) once the output-off
    write on the run's channel went through: off, offset untouched. The
    other channel failing does not void it; the run's channel failing
    does."""
    for fail, recorded in ((set(), True), ({('set_output', 1)}, True),
                           ({('set_output', 2)}, False),
                           ({'set_output'}, False)):
        app = _App(sg=_SessionSG(fail=fail))
        _stuck_run(app, ch=2, dc=False)
        with _fast_clock():
            app._on_app_close()
        assert app.sg.writes == OUTPUTS_OFF + SESSION_END, \
            (fail, app.sg.writes)
        rec = app._sldea_close_zeroed
        if recorded:
            assert (rec is not None and rec[0] is app.sg
                    and rec[1:] == (2, False)), (fail, rec)
        else:
            assert rec is None, (fail, rec)


def test_a_close_with_no_live_run_records_nothing():
    """No LIVE run still flagged, no record: no run, a run that finished
    within the wait, a DRY run. None of them takes the SG's lock."""
    def finished(app):
        _stuck_run(app, ch=2)
        app.root.after(0, app._sldea_finished)
    for name, setup in (
            ('no run', lambda app: None),
            ('finished', finished),
            ('DRY', lambda app: _stuck_run(app, ch=1, live=False))):
        sg = _SessionSG()
        gate = _CloseLock()
        sg.__dict__['_io_rlock'] = gate
        app = _App(sg=sg)
        setup(app)
        with _fast_clock():
            app._on_app_close()
        assert sg.offsets(1) == sg.offsets(2) == [], (name, sg.writes)
        assert app._sldea_close_zeroed is None, name
        assert not gate.main_waiting.is_set(), f"{name}: took the lock"


def test_the_close_holds_the_sg_lock_from_its_zero_to_the_session_close():
    """#472. With the zero made (or, on a channel the run never marked,
    the output-off), the close keeps the SG's I/O lock until the SG
    session is closed, so no other write can reach the channel in
    between. With those writes failed, it lets the lock go once both
    outputs are off, and the run's own zero still gets the open session.
    Either way the lock is free once the window has gone."""
    for fail, dc, held_to_close in (
            (set(), True, True), ({'set_offset'}, True, False),
            ({('set_output', 1)}, True, False),
            (set(), False, True), ({('set_output', 1)}, False, False)):
        sg = _SessionSG(fail=fail)
        gate = _CloseLock()
        sg.__dict__['_io_rlock'] = gate
        held = []
        for name in ('set_offset', 'set_output', 'go_local', 'close'):
            def watch(*args, _inner=getattr(sg, name), _name=name):
                held.append((_name, gate.held_here()))
                return _inner(*args)
            setattr(sg, name, watch)
        app = _App(sg=sg)
        _stuck_run(app, ch=1, dc=dc)
        with _fast_clock():
            app._on_app_close()
        case = (fail, dc)
        assert held == ([('set_offset', True)] if dc else []) + [
            ('set_output', True), ('set_output', True),
            ('go_local', held_to_close), ('close', held_to_close)], \
            (case, held)
        assert gate.depth == 0 and gate.owner is None, (case, gate.depth)
        assert app.root.destroyed


def test_a_write_queued_behind_the_close_lands_on_the_closed_session():
    """#472, and why the lock is held until the session is closed: a write
    that queues for the SG's lock during the close's zero gets it only
    once the session is closed, so it fails there and the channel stays
    at 0 V and off. That write can be the run's own output ON, when its
    start-up writes do not check the stop under this lock (#471), or
    another thread's. Let go of the lock any earlier and the write lands
    on the open session, after the zero the record speaks for."""
    sg = _SessionSG()
    sg.__dict__['_io_rlock'] = _CloseLock()
    app = _App(sg=sg)
    _stuck_run(app, ch=1)
    queued, wrote = threading.Event(), threading.Event()
    outcome = []

    def writer():
        queued.set()
        try:
            with gui._io_lock(sg):
                sg.set_output(1, True)
            outcome.append('landed')
        except IOError as e:
            outcome.append(str(e))
        wrote.set()
    thread = threading.Thread(target=writer, daemon=True)
    inner_offset, inner_local = sg.set_offset, sg.go_local

    def set_offset(channel, offset_v):
        thread.start()                  # the close holds the lock here
        assert queued.wait(5)
        inner_offset(channel, offset_v)

    def go_local():
        wrote.wait(0.5)                 # room for a write let in early
        inner_local()
    sg.set_offset, sg.go_local = set_offset, go_local
    with _fast_clock():
        app._on_app_close()
    thread.join(5)
    assert outcome == [_SessionSG.CLOSED], (outcome, sg.writes)
    assert (sg.writes.index(('set_output', 1, True))
            > sg.writes.index(('close',))), sg.writes
    rec = app._sldea_close_zeroed
    assert rec is not None and rec[0] is sg and rec[1:] == (1, True), rec


# --------------------------------------------------------------------------
# The real run: the DC mark, and no level after a stop
# --------------------------------------------------------------------------

def _ramp_profile():
    """1 kV over 3 s, then a short landing: long enough that a tick blocked
    mid-ramp comes back to a level different from the last one written."""
    return L._short_profile(ramp_s=3.0, landing_s=1.0), None


def _live_app(tmp, sg=None):
    app = _App(tmp, sg=sg, dry=False, real_worker=True, wd_on=True)
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
        # one it then did not write, and the run's start before them
        # (#471: its DC write and output ON are made under the lock)
        levels = [w for w in app.sg.writes[:hit[0]] if w[0] == 'set_offset']
        assert gate.entries == len(levels) + 2, (gate.entries, levels)


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


class _CloseLock(_OwnedLock):
    """_OwnedLock with the acquire() and release() window close calls on
    the SG's I/O lock (#472), as the run's own zero calls them too.
    `main_waiting` is set as the main thread, the Tk thread in the app,
    starts to wait for it there; `acquires` lists the thread of every
    acquire() call (a `with` block is not one)."""

    def __init__(self):
        super().__init__()
        self.main_waiting = threading.Event()
        self.acquires = []

    def acquire(self):
        self.acquires.append(threading.get_ident())
        if threading.current_thread() is threading.main_thread():
            self.main_waiting.set()
        self.__enter__()
        return True

    def release(self):
        self.__exit__(None, None, None)


class _FifoLock:
    """A reentrant SG I/O lock that lets waiting threads in strictly in
    the order they came, so a test can say who gets it next (#472;
    threading.RLock promises no order). acquire()/release() and `with`.
    `queued()` counts the threads waiting; `main_waiting` is set as the
    main thread starts to wait. A wait over 60 s fails instead of
    hanging."""

    def __init__(self):
        self._cond = threading.Condition(threading.Lock())
        self._owner = None
        self._depth = 0
        self._queue = []
        self.main_waiting = threading.Event()

    def acquire(self):
        me = threading.get_ident()
        with self._cond:
            if self._owner == me:
                self._depth += 1
                return True
            if threading.current_thread() is threading.main_thread():
                self.main_waiting.set()
            self._queue.append(me)
            deadline = time.monotonic() + 60
            while self._owner is not None or self._queue[0] != me:
                left = deadline - time.monotonic()
                assert left > 0, "waited 60 s for the SG's lock"
                self._cond.wait(left)
            self._queue.pop(0)
            self._owner, self._depth = me, 1
        return True

    def release(self):
        with self._cond:
            assert self._owner == threading.get_ident(), "not the holder"
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
                self._cond.notify_all()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False

    def queued(self):
        with self._cond:
            return len(self._queue)

    def held_here(self):
        """True when the calling thread holds it: _owner changes only
        under the holder's own hand, so for that thread it is exact."""
        return self._owner == threading.get_ident()


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
        # the run's own zero went through after the close's: it zeroed the
        # channel itself, so run.log has neither the alarm nor the close's
        # line (#472)
        assert not any('FAILED TO ZERO' in ln for ln in app.lines), \
            app.lines
        assert not _close_lines(app), app.lines


# --------------------------------------------------------------------------
# The real run's own zero after a close: the close's line or the alarm
# (#472)
# --------------------------------------------------------------------------

def _alarmed(app, mb):
    """(run.log's FAILED TO ZERO line, the NOT ZEROED status, the HV NOT
    ZEROED box): which parts of the alarm the run raised. Call after
    root.run_pending(), which shows the queued box."""
    return (any('FAILED TO ZERO' in ln for ln in app.lines),
            any('NOT ZEROED' in s for s in app.statuses),
            'HV NOT ZEROED' in mb.titles('showerror'))


def _close_mid_ramp(app, before_close=None, after_close=None):
    """Block the run in its first I_Out read after the ramp has started,
    run `before_close()` there, close the window, run `after_close()`,
    then let the read come back and wait for the run to end. -> the SG
    writes the close made. The close's wait runs on the fast clock: the
    run is blocked in the read meanwhile, so it reads no clock."""
    entered, release, hit = _block_first_ramp_read(app)
    try:
        app.sldea_run()
        assert entered.wait(30), app.lines
        assert app._sldea_running and app._sldea_sg_dc_ch == 1
        if before_close is not None:
            before_close()
        n = len(app.sg.writes)
        with _fast_clock():
            app._on_app_close()
        closing = app.sg.writes[n:]
        assert app.root.destroyed
        if after_close is not None:
            after_close()
    finally:
        # the worker must be done with the run folder before the
        # temporary directory goes, pass or fail
        release.set()
        done = app.worker_done.wait(30)
    assert done, app.lines
    assert app.worker_error is None, repr(app.worker_error)
    assert app.tk_under_lock == [], app.tk_under_lock
    app.root.run_pending()              # shows a box the run queued
    return closing


def test_a_close_that_zeroed_the_channel_is_logged_instead_of_the_alarm():
    """The run is blocked past the close's wait. The close sets CH1 to 0 V,
    switches both outputs off and closes the SG session. The run's own
    zero then fails on the closed session, which used to log FAILED TO
    ZERO and raise HV NOT ZEROED although CH1 was at 0 V and off. Now
    run.log says what the close did, after the attempt's own error, and
    neither the NOT ZEROED status nor the box goes up. The SG writes are
    the ones the close and the run made before."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)) as mb:
        app = _live_app(tmp, sg=_SessionSG())
        closing = _close_mid_ramp(app)
        assert closing == ([('set_offset', 1, 0.0)] + OUTPUTS_OFF
                           + SESSION_END), closing
        rec = app._sldea_close_zeroed
        assert (rec is not None and rec[0] is app.sg
                and rec[1:] == (1, True)), rec
        assert app.sg.writes[-1] == ('set_offset', 1, 0.0), app.sg.writes
        assert _alarmed(app, mb) == (False, False, False), \
            (app.lines, app.statuses, mb.calls)
        i = app.lines.index(CLOSE_LINE)
        assert app.lines[i - 1] == ("SG zeroing attempt failed: "
                                    + _SessionSG.CLOSED), app.lines


def test_a_close_on_a_dead_link_keeps_the_alarm():
    """The link died mid-run: the close's zero and both outputs-off fail,
    so it records nothing, and the run's failed zero is the real HV alarm
    it always was: the run.log line, the status and the box."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)) as mb:
        app = _live_app(tmp, sg=_SessionSG())
        closing = _close_mid_ramp(
            app, before_close=lambda: setattr(app.sg, 'dead', True))
        assert closing == ([('set_offset', 1, 0.0)] + OUTPUTS_OFF
                           + SESSION_END), closing
        assert app._sldea_close_zeroed is None
        assert _alarmed(app, mb) == (True, True, True), \
            (app.lines, app.statuses, mb.calls)
        assert not _close_lines(app), app.lines


def test_a_close_that_zeroed_another_channel_keeps_the_alarm():
    """The record names CH2 and the run drives CH1, whose offset may still
    hold the run's level: the run's failed zero keeps the alarm. The mark
    is set to CH2 by hand here; in the app it is always the run's own
    channel, so this pins the channel check, not a path."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)) as mb:
        app = _live_app(tmp, sg=_SessionSG())
        closing = _close_mid_ramp(
            app, before_close=lambda: setattr(app, '_sldea_sg_dc_ch', 2))
        assert closing[0] == ('set_offset', 2, 0.0), closing
        rec = app._sldea_close_zeroed
        assert rec is not None and rec[1:] == (2, True), rec
        assert _alarmed(app, mb) == (True, True, True), \
            (app.lines, app.statuses, mb.calls)
        assert not any(ln.startswith('SG CH') for ln in app.lines), \
            app.lines


def test_a_close_through_another_sg_handle_keeps_the_alarm():
    """The close zeroed CH1 through another SG handle than the one the run
    drove (self.sg replaced mid-run; Reconnect refuses that during a LIVE
    run, so this pins the handle check, not a path). The run's levels went
    through its own handle and its own lock, which the record says
    nothing about, so with both of the run's attempts failed the alarm
    stands."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)) as mb:
        run_sg = _SessionSG()
        app = _live_app(tmp, sg=run_sg)
        other = _SessionSG()

        def swap():
            run_sg.dead = True            # the run's own handle is gone
            app.sg = other
        closing = _close_mid_ramp(app, before_close=swap)
        assert closing == ([('set_offset', 1, 0.0)] + OUTPUTS_OFF
                           + SESSION_END), closing
        rec = app._sldea_close_zeroed
        assert (rec is not None and rec[0] is other
                and rec[1:] == (1, True)), rec
        tries = [ln for ln in app.lines
                 if ln.startswith('SG zeroing attempt failed')]
        assert len(tries) == 2, app.lines
        assert _alarmed(app, mb) == (True, True, True), \
            (app.lines, app.statuses, mb.calls)
        assert not _close_lines(app), app.lines


def test_a_close_during_camera_start_up_is_logged_as_off_not_as_the_alarm():
    """From #471's review. The window closes while the run is still in its
    camera start-up, before its SG start writes: the run has not marked a
    channel, so the close writes no offset, switches both outputs off and
    closes the session. The run then skips its start writes (the stop is
    set), never switches CH1 on, and its own zero fails on the closed
    session. That used to say FAILED TO ZERO, "the Trek may still be
    energized", for a channel that was never switched on. Now run.log says
    CH1 is off, and neither the status nor the box goes up."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)) as mb:
        app = _live_app(tmp, sg=_SessionSG())
        in_camera, release = threading.Event(), threading.Event()
        inner = gui.webcam.resolve_camera

        def resolve_camera(idx):
            if threading.current_thread() is not threading.main_thread():
                in_camera.set()
                assert release.wait(30), "the test never let the run on"
            return inner(idx)
        gui.webcam.resolve_camera = resolve_camera      # _patched restores
        try:
            app.sldea_run()
            assert in_camera.wait(30), app.lines
            assert app._sldea_running and app._sldea_sg_dc_ch is None
            with _fast_clock():
                app._on_app_close()
            closing = list(app.sg.writes)
        finally:
            release.set()
            done = app.worker_done.wait(30)
        assert done, app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert app.tk_under_lock == [], app.tk_under_lock
        app.root.run_pending()
        assert closing == OUTPUTS_OFF + SESSION_END, closing
        assert app.sg.writes[len(closing):] == [('set_offset', 1, 0.0)], \
            app.sg.writes
        rec = app._sldea_close_zeroed
        assert (rec is not None and rec[0] is app.sg
                and rec[1:] == (1, False)), rec
        assert _alarmed(app, mb) == (False, False, False), \
            (app.lines, app.statuses, mb.calls)
        assert _close_lines(app) == [OFF_LINE], app.lines


def test_a_close_while_the_run_start_waits_for_the_sg_lock_is_logged_as_off():
    """From #471's review. Another thread holds the SG's lock (Continuous
    Logging); the run passed its first stop check and waits for the lock
    to make its start writes; the window closes and waits for the lock
    too, after the run. When the lock is let go, the run gets it first.
    With #471 the run finds the stop under the lock and writes nothing;
    without it, its first start write lands and the next one queues
    behind the close. Either way the close then finds no mark, switches
    both outputs off and closes the session, the run's later writes fail
    there, CH1 is never switched on, and run.log says it is off."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)) as mb:
        sg = _SessionSG(locking=True)
        lock = _FifoLock()
        sg.__dict__['_io_rlock'] = lock
        app = _live_app(tmp, sg=sg)
        holding, let_go = threading.Event(), threading.Event()

        def logger():                     # Continuous Logging, say
            with lock:
                holding.set()
                assert lock.main_waiting.wait(30), "the close never waited"
            let_go.set()
        thread = threading.Thread(target=logger, daemon=True)
        thread.start()
        assert holding.wait(5)
        try:
            app.sldea_run()
            deadline = time.monotonic() + 30
            while lock.queued() < 1:
                assert time.monotonic() < deadline, app.lines
                time.sleep(0.01)
            with _fast_clock():
                app._on_app_close()
        finally:
            lock.main_waiting.set()       # never leave the logger holding
            thread.join(30)
            done = app.worker_done.wait(30)
        assert let_go.is_set()
        assert done, app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert app.tk_under_lock == [], app.tk_under_lock
        app.root.run_pending()
        end = sg.writes.index(('close',)) + 1
        assert ('set_output', 1, True) not in sg.writes[:end], sg.writes
        assert sg.writes[end - 4:end] == OUTPUTS_OFF + SESSION_END, \
            sg.writes
        rec = app._sldea_close_zeroed
        assert rec is not None and rec[0] is sg and rec[1:] == (1, False), \
            rec
        assert app._sldea_sg_dc_ch is None
        assert _alarmed(app, mb) == (False, False, False), \
            (app.lines, app.statuses, mb.calls)
        assert _close_lines(app) == [OFF_LINE], app.lines


def test_a_close_that_only_switched_off_a_marked_channel_keeps_the_alarm():
    """The close saw no mark and only switched CH1 off, but the run had
    marked CH1 (in the app, a mark set between the close's look and its
    writes): CH1 may still hold the run's last level, so the run's failed
    zero keeps the alarm. The mark is hidden from the close by hand."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)) as mb:
        app = _live_app(tmp, sg=_SessionSG())
        closing = _close_mid_ramp(
            app,
            before_close=lambda: setattr(app, '_sldea_sg_dc_ch', None),
            after_close=lambda: setattr(app, '_sldea_sg_dc_ch', 1))
        assert closing == OUTPUTS_OFF + SESSION_END, closing
        rec = app._sldea_close_zeroed
        assert (rec is not None and rec[0] is app.sg
                and rec[1:] == (1, False)), rec
        assert _alarmed(app, mb) == (True, True, True), \
            (app.lines, app.statuses, mb.calls)
        assert not _close_lines(app), app.lines


def test_the_close_reads_the_mark_once_it_holds_the_sg_lock():
    """The run marks CH1 while the close waits for the SG's lock (with
    #471, a close that comes during the run's start writes waits for all
    of them, the mark included). The close reads the mark only once it
    holds the lock, so it zeroes CH1 and records that, and run.log says
    CH1 is at 0 V and off. Read before the lock, the mark would be missed:
    CH1 only switched off, and the alarm. The mark is set by hand as the
    close takes the lock."""
    class MarkOnAcquire(_CloseLock):
        def acquire(self):
            if threading.current_thread() is threading.main_thread():
                app._sldea_sg_dc_ch = 1
            return super().acquire()
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)) as mb:
        app = _live_app(tmp, sg=_SessionSG())
        app.sg.__dict__['_io_rlock'] = MarkOnAcquire()
        closing = _close_mid_ramp(
            app, before_close=lambda: setattr(app, '_sldea_sg_dc_ch', None))
        assert closing == ([('set_offset', 1, 0.0)] + OUTPUTS_OFF
                           + SESSION_END), closing
        rec = app._sldea_close_zeroed
        assert (rec is not None and rec[0] is app.sg
                and rec[1:] == (1, True)), rec
        assert _alarmed(app, mb) == (False, False, False), \
            (app.lines, app.statuses, mb.calls)
        assert _close_lines(app) == [CLOSE_LINE], app.lines


def test_a_failed_zero_with_no_close_keeps_the_alarm():
    """No close at all: the link dies mid-run, Abort, and the run's own
    zero fails. The alarm, as before. With no close begun the run reads no
    record, so even one left set by hand, naming this handle and channel,
    changes nothing."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)) as mb:
        app = _live_app(tmp, sg=_SessionSG())
        app._sldea_close_zeroed = (app.sg, 1, True)

        def die_then_abort():
            app.sg.dead = True
            app.sldea_abort()
        entered, release, hit = _block_first_ramp_read(app, die_then_abort)
        release.set()
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert app.tk_under_lock == [], app.tk_under_lock
        app.root.run_pending()
        assert hit, "the worker never read I_Out while ramping"
        assert _alarmed(app, mb) == (True, True, True), \
            (app.lines, app.statuses, mb.calls)
        assert not _close_lines(app), app.lines


def test_without_a_close_the_run_zero_is_made_as_before():
    """A run that ends by Abort, with no window close begun, zeroes as it
    did before #472: offset, then output off, neither under the SG's I/O
    lock, and no record read. The lock has the acquire() the run's zero
    would call, so a zero that took it here would be seen, not swallowed
    as a failed acquire."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)) as mb:
        app = _live_app(tmp, sg=_SessionSG())
        gate = _CloseLock()
        app.sg.__dict__['_io_rlock'] = gate
        app._sldea_close_zeroed = (app.sg, 1, True)    # must not be read
        held = []
        for name in ('set_offset', 'set_output'):
            def watch(channel, value, _inner=getattr(app.sg, name),
                      _name=name):
                if app._sldea_stop:
                    held.append((_name, value, gate.held_here()))
                return _inner(channel, value)
            setattr(app.sg, name, watch)
        entered, release, hit = _block_first_ramp_read(app, app.sldea_abort)
        release.set()
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        app.root.run_pending()
        assert held == [('set_offset', 0.0, False),
                        ('set_output', False, False)], held
        assert gate.acquires == [], "the run's zero took the SG's lock"
        assert _alarmed(app, mb) == (False, False, False), \
            (app.lines, app.statuses, mb.calls)
        assert not _close_lines(app), app.lines
        assert app.tk_under_lock == [], app.tk_under_lock


def test_a_close_that_zeroes_after_the_run_zero_failed_keeps_the_alarm():
    """The run's own zero fails first (its writes time out), and the close
    then zeroes CH1 before the run has decided what to log. The alarm
    stands: the record was not there when the run's attempt began, and
    when that attempt failed nothing said the channel was at 0 V. A record
    read when the run decides, rather than when its attempt begins, gets
    this case wrong."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)) as mb:
        app = _live_app(tmp, sg=_SessionSG())
        failed, resume = threading.Event(), threading.Event()

        def on_log(line):
            if line.startswith('SG zeroing attempt failed'):
                failed.set()
                assert resume.wait(30), "the test never resumed the run"
        app.on_log = on_log

        def time_out_then_abort():
            app.sg.dead_for_run = True
            app.sldea_abort()
        entered, release, hit = _block_first_ramp_read(app,
                                                       time_out_then_abort)
        release.set()
        try:
            app.sldea_run()
            assert failed.wait(30), app.lines
            assert app._sldea_running, "the run is paused, still flagged"
            n = len(app.sg.writes)
            with _fast_clock():
                app._on_app_close()
            closing = app.sg.writes[n:]
        finally:
            resume.set()
            done = app.worker_done.wait(30)
        assert done, app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert app.tk_under_lock == [], app.tk_under_lock
        app.root.run_pending()
        assert closing == ([('set_offset', 1, 0.0)] + OUTPUTS_OFF
                           + SESSION_END), closing
        rec = app._sldea_close_zeroed
        assert (rec is not None and rec[0] is app.sg
                and rec[1:] == (1, True)), rec
        assert _alarmed(app, mb) == (True, True, True), \
            (app.lines, app.statuses, mb.calls)
        assert not _close_lines(app), app.lines


def _close_during_the_run_zero(app, fail):
    """The run is blocked in a scope read mid-ramp when the window closes.
    At the close's first update() (inside its wait, so the close has
    begun) the read comes back, and the run, stopped by the close, reaches
    its own zero, which is held there, inside the SG's lock, until window
    close starts to wait for that lock: the close's ~3 s wait has run out
    while the run is still zeroing. `fail` makes the run's zero time out
    there. -> the SG writes from that zero on."""
    gate = _CloseLock()
    app.sg.__dict__['_io_rlock'] = gate
    in_zero = threading.Event()
    held = []

    def on_zero(channel):
        if app._sldea_stop and not in_zero.is_set():
            held.append(gate.held_here())
            in_zero.set()
            assert gate.main_waiting.wait(30), \
                "the close never waited for the SG's lock"
            app.sg.dead_for_run = fail
    app.sg.on_zero = on_zero
    entered, release, hit = _block_first_ramp_read(app)

    def let_the_run_reach_its_zero():
        if not release.is_set():
            release.set()
            assert in_zero.wait(30), "the run never reached its zero"
    try:
        app.sldea_run()
        assert entered.wait(30), app.lines
        n = len(app.sg.writes)
        app.root.on_update = let_the_run_reach_its_zero
        with _fast_clock():
            app._on_app_close()
        assert app.root.destroyed
    finally:
        release.set()
        gate.main_waiting.set()           # never leave the run waiting
        done = app.worker_done.wait(30)
    assert done, app.lines
    assert app.worker_error is None, repr(app.worker_error)
    assert app.tk_under_lock == [], app.tk_under_lock
    assert held == [True], "the run's zero is not under the SG's lock"
    app.root.run_pending()
    return app.sg.writes[n:]


def test_a_close_while_the_run_is_zeroing_waits_and_logs_no_alarm():
    """The wait runs out while the run is in its own zero. The close waits
    for the SG's lock, so the run's offset and output-off go in together,
    then the close's own: nothing lands between the run's two writes. The
    run zeroed the channel itself, so run.log has neither the alarm nor
    the close's line."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)) as mb:
        app = _live_app(tmp, sg=_SessionSG())
        writes = _close_during_the_run_zero(app, fail=False)
        assert writes == ([('set_offset', 1, 0.0), ('set_output', 1, False),
                           ('set_offset', 1, 0.0)] + OUTPUTS_OFF
                          + SESSION_END), writes
        assert _alarmed(app, mb) == (False, False, False), \
            (app.lines, app.statuses, mb.calls)
        assert not _close_lines(app), app.lines


def test_a_close_while_the_run_zero_times_out_keeps_the_alarm():
    """The wait runs out while the run is in its own zero, and that zero
    times out. The close zeroes CH1 after it, but the run's attempt began
    before any record and failed: the alarm stands."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)) as mb:
        app = _live_app(tmp, sg=_SessionSG())
        writes = _close_during_the_run_zero(app, fail=True)
        assert writes == ([('set_offset', 1, 0.0), ('set_offset', 1, 0.0)]
                          + OUTPUTS_OFF + SESSION_END), writes
        rec = app._sldea_close_zeroed
        assert rec is not None and rec[1:] == (1, True), rec
        assert _alarmed(app, mb) == (True, True, True), \
            (app.lines, app.statuses, mb.calls)
        assert not _close_lines(app), app.lines


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = []
    for fn in fns:
        # every case, guarded helpers or not: a Tk hand-off a worker made
        # under an SG I/O lock fails it, even where the run swallowed the
        # guard's error (#472)
        TK_UNDER_LOCK.clear()
        try:
            fn()
            assert not TK_UNDER_LOCK, (
                f"a worker thread made a Tk hand-off while holding an SG "
                f"I/O lock: {TK_UNDER_LOCK}")
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
