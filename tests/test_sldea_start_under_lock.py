#!/usr/bin/env python3
"""A LIVE run's first SG writes are made under the SG's I/O lock, with the
stop checked again under it, so a window close can never leave the output
ON at DC 0 V (#471).

The run's start sets its channel's load and polarity, sets DC at 0 V,
marks the channel for window close (#460) and switches the output ON. It
used to check the stop once, outside the SG's I/O lock
(instruments._io_lock). Continuous Logging reads the SG on its own thread,
and one timed-out query holds that lock for up to 5 s, longer than window
close's ~3 s wait. A worker that passed the check and then queued behind
such a hold let the close find no mark, write no zero and switch CH1 and
CH2 off; its queued writes then landed after that and left the channel ON
at DC 0 V. What is pinned here:

* the three writes and the mark are made inside the same hold of the lock
  as the worker's last stop check before them, in the order they always
  had, and nothing else is sent;
* a stop set while the worker waits for that lock means none of the three
  writes and no mark;
* a close while another thread holds the lock past the close's wait ends
  with both outputs OFF, and nothing switches CH1 back on;
* a close that comes after the worker's check, while it is making the
  writes, queues behind them and still ends with the outputs OFF: the
  Tk thread waits on the lock and the worker, which needs nothing from
  the Tk thread under it, lets it go;
* a DRY run takes no SG lock and writes nothing.

Everything runs the REAL sldea_run, worker and _on_app_close on the
scope-lock suite's Tk-free stub app (tests/test_scope_live_lock.py),
against a fake SG that takes the SG's I/O lock around each of its own
writes as the real driver does (VisaInstrument.write), and records
whether the caller already held it. The lock is a reentrant lock that
lets waiting threads in strictly in arrival order, says who holds it and
who waits, and fails a wait that lasts a minute, so a deadlock fails the
test instead of hanging the suite.

Run: .venv/bin/python tests/test_sldea_start_under_lock.py
"""
import collections
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
from instruments import _io_lock  # noqa: E402

G = gui.InstrumentControlGUI
WAIT_S = 30.0                   # how long a test waits for a thread


# --------------------------------------------------------------------------
# The fakes
# --------------------------------------------------------------------------

class _FifoLock:
    """The SG's I/O lock (what instruments._io_lock hands out): reentrant,
    and it lets waiting threads in strictly in the order they came, so a
    test can say who gets it next. `holds` counts the outermost
    acquisitions; while a thread holds the lock it is that hold's number.
    A wait over STUCK_S fails, as a deadlock would."""
    STUCK_S = 60.0

    def __init__(self):
        self._cv = threading.Condition()
        self.owner = None
        self.depth = 0
        self.holds = 0
        self.queue = []

    def acquire(self):
        me = threading.get_ident()
        with self._cv:
            if self.owner == me:
                self.depth += 1
                return True
            self.queue.append(me)
            ok = self._cv.wait_for(
                lambda: self.owner is None and self.queue[0] == me,
                timeout=self.STUCK_S)
            if not ok:
                self.queue.remove(me)
                self._cv.notify_all()
                raise AssertionError(
                    f"waited {self.STUCK_S:g} s for the SG's I/O lock: "
                    f"deadlock?")
            self.queue.pop(0)
            self.owner, self.depth = me, 1
            self.holds += 1
            return True

    def release(self):
        with self._cv:
            assert self.owner == threading.get_ident(), \
                "released by a thread that does not hold it"
            self.depth -= 1
            if self.depth == 0:
                self.owner = None
                self._cv.notify_all()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False

    def held_here(self):
        """True when the calling thread holds it. owner is changed only by
        the thread that holds the lock, so for that thread it is exact."""
        return self.owner == threading.get_ident()

    def waiting(self):
        with self._cv:
            return list(self.queue)


# One timeline for the stop checks, the mark and the SG calls, so a test
# can tell which lock hold each was made under. kind: 'stop?' (what = the
# value read), 'mark' (what = the channel) or 'call' (what = (name,
# channel, value)). held: the thread already held the SG's lock as it
# came in. hold: the number of the lock hold it was made under, else None.
Ev = collections.namedtuple('Ev', 'kind what held hold tid')


class _DriverSG:
    """BK4055B stand-in that locks the way the real driver does: each call
    takes the SG's I/O lock around its own write, as VisaInstrument.write
    does, after noting whether the caller already held it. A call made
    after close() fails, as on a closed pyvisa session, and lands nothing.
    `writes` holds what landed, in the order it landed, and `by` the thread
    that sent each; `out` and `dc` are what the SG is left doing, and
    `on_call(name, channel, value)` runs inside the lock just before a call
    lands."""

    def __init__(self, events):
        self.lock = self.__dict__['_io_rlock'] = _FifoLock()
        self.events = events
        self.writes, self.by = [], []
        self.failed = []
        self.out = {1: False, 2: False}
        self.dc = {1: False, 2: False}
        self.closed = False
        self.on_call = None

    def _call(self, name, channel, value, apply=None):
        held = self.lock.held_here()
        with _io_lock(self):
            self.events.append(Ev('call', (name, channel, value), held,
                                  self.lock.holds, threading.get_ident()))
            if self.on_call is not None:
                self.on_call(name, channel, value)
            if self.closed:
                self.failed.append((name, channel, value))
                raise IOError('VI_ERROR_INV_OBJECT (fake: session closed)')
            self.writes.append((name, channel, value))
            self.by.append(threading.get_ident())
            if apply is not None:
                apply()

    def landed_from(self, ident):
        """What landed from one thread, in order."""
        return [w for w, t in zip(self.writes, self.by) if t == ident]

    def set_load_polarity(self, channel, load=None, polarity=None):
        self._call('set_load_polarity', channel, (load, polarity))

    def set_basic_wave(self, channel, **params):
        def apply():
            if str(params.get('WVTP', '')).upper() == 'DC':
                self.dc[channel] = True
        self._call('set_basic_wave', channel, dict(params), apply)

    def set_offset(self, channel, offset_v):
        self._call('set_offset', channel, offset_v)

    def set_output(self, channel, on):
        def apply():
            self.out[channel] = bool(on)
        self._call('set_output', channel, bool(on), apply)

    def go_local(self):
        self._call('go_local', None, None)     # SYST:LOC goes through write

    def close(self):
        self.closed = True                     # the real one takes no lock


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
    or DMM, and the locking SG above. The stop flag and the window-close
    mark are properties, so each read of the one and each write of the
    other on the worker's thread lands in the timeline with the lock hold
    it was made under."""
    _on_app_close = G._on_app_close

    def __init__(self, tmp='.', **kw):
        self.events = []
        self.worker_ident = None
        self._stop_value = False
        self._mark_value = None
        super().__init__(tmp, **kw)
        self.root = _Root()
        self.sg = _DriverSG(self.events)
        self.psu = self.dmm = None
        self._sldea_sg_dc_ch = None

    def _note(self, kind, what):
        if threading.get_ident() != self.worker_ident:
            return
        sg = self.__dict__.get('sg')
        lock = getattr(sg, 'lock', None)
        held = lock is not None and lock.held_here()
        self.events.append(Ev(kind, what, held,
                              lock.holds if held else None,
                              threading.get_ident()))

    @property
    def _sldea_stop(self):
        value = self._stop_value
        self._note('stop?', value)
        return value

    @_sldea_stop.setter
    def _sldea_stop(self, value):
        self._stop_value = value

    @property
    def _sldea_sg_dc_ch(self):
        return self._mark_value

    @_sldea_sg_dc_ch.setter
    def _sldea_sg_dc_ch(self, value):
        self._note('mark', value)
        self._mark_value = value

    def _sldea_worker(self, *args, **kw):
        self.worker_ident = threading.get_ident()
        super()._sldea_worker(*args, **kw)


def _live_app(tmp):
    app = _App(tmp, dry=False, real_worker=True, wd_on=True)
    app._sldea_build_profile = lambda: (L._short_profile(), None)
    return app


START = [('set_load_polarity', 1, ('HZ', 'NOR')),
         ('set_basic_wave', 1, {'WVTP': 'DC', 'OFST': 0.0}),
         ('set_output', 1, True)]
ZERO = [('set_offset', 1, 0.0), ('set_output', 1, False)]


def _is_start(what):
    return what in START


def _worker_starts(app):
    """The worker's start calls, landed or not, as timeline entries."""
    return [e for e in app.events if e.kind == 'call'
            and e.tid == app.worker_ident and _is_start(e.what)]


def _worker_marks(app):
    return [e for e in app.events if e.kind == 'mark'
            and e.tid == app.worker_ident and e.what is not None]


def _until(cond, what):
    """Poll `cond` until it is true, or fail after WAIT_S."""
    end = time.monotonic() + WAIT_S
    while not cond():
        assert time.monotonic() < end, f"timed out waiting for {what}"
        time.sleep(0.01)


class _Holder:
    """Another thread holding the SG's I/O lock, as Continuous Logging does
    through a timed-out query. It lets go when `release` is set, or, with
    `until`, as soon as until(lock) is true."""

    def __init__(self, lock, until=None):
        self.lock, self.until = lock, until
        self.got, self.release = threading.Event(), threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        try:
            with self.lock:
                self.got.set()
                if self.until is not None:
                    _until(lambda: self.until(self.lock), 'the waiters')
                else:
                    assert self.release.wait(WAIT_S), "never released"
        except BaseException as e:           # a thread's traceback is lost
            self.error = e
            self.got.set()

    def __enter__(self):
        self.thread.start()
        assert self.got.wait(WAIT_S) and self.error is None, self.error
        return self

    def __exit__(self, *exc):
        self.release.set()
        self.thread.join(WAIT_S)
        return False


# --------------------------------------------------------------------------
# The start writes and the lock
# --------------------------------------------------------------------------

def test_the_start_writes_are_made_under_the_hold_their_stop_check_took():
    """No contention: the run's start sends what it always sent, in the
    same order, and its last stop check before them, the three writes and
    the mark are all made inside ONE hold of the SG's lock that the worker
    took itself. A check under one hold and writes under a later one, or
    writes after the lock is let go, would leave a gap close could use."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)):
        app = _live_app(tmp)
        app.sldea_run()
        assert app.worker_done.wait(WAIT_S), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert app.sg.writes[:3] == START, app.sg.writes
        ev = app.events
        starts = _worker_starts(app)
        assert [e.what for e in starts] == START, starts
        [mark] = _worker_marks(app)
        assert mark.what == 1, mark
        order = [ev.index(e) for e in (starts[0], starts[1], mark,
                                       starts[2])]
        assert order == sorted(order), \
            "the DC write, then the mark, then output ON"
        checks = [e for e in ev[:order[0]] if e.kind == 'stop?'
                  and e.tid == app.worker_ident]
        assert checks, "the worker never checked the stop before its writes"
        last = checks[-1]
        assert last.what is False, last
        assert last.held, \
            "the last stop check before the writes was made outside the lock"
        for e in starts + [mark]:
            assert e.held, f"{e.what} was made outside the worker's hold"
            assert e.hold == last.hold, (
                f"{e.what} was made in lock hold {e.hold}, the stop check "
                f"in hold {last.hold}")
        # and the levels after them still went through the lock, unchanged
        levels = [w for w in app.sg.writes[3:] if w[0] == 'set_offset'
                  and w[2] != 0.0]
        assert levels, app.sg.writes
        assert app.sg.writes[-2:] == ZERO, app.sg.writes


def test_a_stop_set_while_the_run_waits_for_the_sg_lock_means_no_start_write():
    """Another thread holds the SG's lock when the worker reaches its start,
    so the worker queues on it. Abort is pressed while it waits. When the
    lock is let go, the worker checks the stop again under it: none of the
    three writes is made, the channel is never marked, and the only SG
    writes of the run are its finally block's zero."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)):
        app = _live_app(tmp)
        lock = app.sg.lock
        with _Holder(lock) as holder:
            app.sldea_run()
            _until(lambda: lock.waiting() == [app.worker_ident],
                   'the worker to queue on the SG lock')
            assert app.sg.writes == [] and app._sldea_sg_dc_ch is None
            app.sldea_abort()
            holder.release.set()
        assert holder.error is None, repr(holder.error)
        assert app.worker_done.wait(WAIT_S), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert _worker_starts(app) == [], _worker_starts(app)
        assert _worker_marks(app) == [], _worker_marks(app)
        assert app._sldea_sg_dc_ch is None    # before _sldea_finished runs
        assert app.sg.writes == ZERO, app.sg.writes
        assert app.sg.out == {1: False, 2: False}, app.sg.out
        assert not app.sg.dc[1], "the channel was set to DC after the stop"
        assert any(ln.startswith('run aborted') for ln in app.lines), \
            app.lines


def test_a_close_while_another_thread_holds_the_sg_lock_leaves_the_outputs_off():
    """The #471 race, end to end. Another thread holds the SG's lock past
    the close's ~3 s wait; the worker passed its first stop check and
    queued on that lock before the close. The close finds no mark, writes
    no zero and queues its outputs-off behind the worker. When the lock is
    let go the worker gets it first and finds the stop the close set, so
    nothing it does lands after the close's OFF: both outputs end OFF and
    CH1 is never switched on. Its finally block's zero goes to the closed
    session and lands nothing, as in the app."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)):
        app = _live_app(tmp)
        lock = app.sg.lock
        # let go once the worker and the close both wait, worker first
        holder = _Holder(lock, until=lambda lk: len(lk.waiting()) >= 2)
        with holder:
            app.sldea_run()
            _until(lambda: lock.waiting() == [app.worker_ident],
                   'the worker to queue on the SG lock')
            assert app.sg.writes == [], app.sg.writes
            app._on_app_close()                 # the real ~3 s wait
        assert holder.error is None, repr(holder.error)
        assert app.root.destroyed
        assert app.worker_done.wait(WAIT_S), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        # no mark at the close's read, so the close wrote no offset
        closing = app.sg.landed_from(threading.get_ident())
        assert closing == [('set_output', 1, False), ('set_output', 2, False),
                           ('go_local', None, None)], closing
        assert ('set_output', 1, True) not in app.sg.writes, app.sg.writes
        assert app.sg.out == {1: False, 2: False}, app.sg.writes
        assert _worker_marks(app) == [], _worker_marks(app)


def test_a_close_during_the_start_writes_queues_behind_them_and_ends_off():
    """The close comes after the worker's check, while it is in the middle
    of its start writes (held here inside its DC write until the close
    queues on the lock). The Tk thread waits on the SG's lock while the
    worker holds it, and the worker finishes its writes without anything
    from the Tk thread, so there is no deadlock: its output ON lands, then
    the close's outputs-off, and both outputs end OFF."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)):
        app = _live_app(tmp)
        lock = app.sg.lock
        inside = threading.Event()

        def on_call(name, channel, value):
            if (name == 'set_basic_wave' and not inside.is_set()
                    and threading.get_ident() == app.worker_ident):
                inside.set()
                _until(lambda: len(lock.waiting()) >= 1,
                       'the close to queue on the SG lock')
        app.sg.on_call = on_call
        app.sldea_run()
        assert inside.wait(WAIT_S), app.lines
        app._on_app_close()                     # the real ~3 s wait
        assert app.root.destroyed
        assert app.worker_done.wait(WAIT_S), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        writes, by = app.sg.writes, app.sg.by
        main = threading.get_ident()
        assert app.sg.landed_from(app.worker_ident)[:3] == START, writes
        on = writes.index(('set_output', 1, True))
        off = [i for i, (w, t) in enumerate(zip(writes, by))
               if t == main and w == ('set_output', 1, False)]
        assert off and off[0] > on, \
            f"the close's CH1 OFF must land after the run's ON: {writes}"
        assert app.sg.out == {1: False, 2: False}, writes


def test_a_dry_run_takes_no_sg_lock_and_writes_nothing():
    """A DRY run never commands the SG, and it does not queue on the SG's
    lock behind Continuous Logging either."""
    with tempfile.TemporaryDirectory() as tmp, \
            L._patched(L._MB(L.LIVE_OK)):
        app = _App(tmp, dry=True, real_worker=True)
        app.sldea_run()
        assert app.worker_done.wait(WAIT_S), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert app.lines, "the DRY run logged nothing"
        assert app.sg.writes == [] and app.sg.failed == [], app.sg.writes
        assert app.sg.lock.holds == 0, app.sg.lock.holds
        assert _worker_marks(app) == [], _worker_marks(app)


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
    raise SystemExit(_run())
