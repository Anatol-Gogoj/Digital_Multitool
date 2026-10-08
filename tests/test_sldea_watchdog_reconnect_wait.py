#!/usr/bin/env python3
"""A ticked LIVE run waits at 0 V for a scope Reconnect still in flight at
its watchdog's arming line, then arms as usual (#423).

A LIVE Reconnect confirmed in a run's first seconds (#339) used to leave
the run with no watchdog: the worker builds it once, at the arming line
after the SG output goes on at 0 V, and only if the scope is there. Since
#406's HV review such a run says NOT ARMED. Owner decision 2026-10-08:
while the scope's Reconnect is still in flight there, the run waits at
0 V, bounded, with Abort checked throughout; a scope back in time gets the
normal on-time baseline and arms exactly as an on-time arming does; any
other end stays NOT ARMED as #406 records it, with the wait recorded too.
The wait comes before the run clock starts, so the profile, stills, video
and telemetry keep their timing. (The first attempt armed late from
inside the run loop instead; its HV review dropped it.)

Every run below is the real sldea_run and the real worker on the
scope-lock suite's fakes (tests/test_scope_live_lock.py), with two things
real that the other suites stub: _run_bg, so a connect runs on its own
thread and its done callback lands on the "Tk" thread (this test's pump),
and _reconnect, pressed during the worker's camera setup, before its
arming line, with Yes to its "Scope in use" question. Each scope read
takes 0.13 s, the bench's: per-run medians of 104 to 141 ms in nine
telemetry.csv files (HV review of the first attempt, 2026-10-08). The
scope reads 7 uA at 0 kV, not 0, so a learned baseline shows: a ramp
current of -95 uA trips a 100 uA watchdog only against that baseline
(|-95 - 7| = 102), never on the absolute rule (|-95| = 95).

Run: .venv/bin/python tests/test_sldea_watchdog_reconnect_wait.py
"""
import os
import re
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import gui  # noqa: E402
import sldea_profile as sp  # noqa: E402
import test_scope_live_lock as L  # noqa: E402

G = gui.InstrumentControlGUI
READ_S = 0.13             # one bench measure_raw (see the docstring)
REST_V = 0.035            # I_Out monitor volts at 0 kV: 7 uA
TRIP_V = 0.6              # 120 uA, over the 100 uA trip either way
BASE_ONLY_V = -0.475      # -95 uA: trips only against the 7 uA baseline
WAIT_LINE = ("breakdown watchdog: the scope Reconnect is still running, so "
             "the run waits for it here at 0 V, up to ")
NOT_ARMED = "⚠⚠ BREAKDOWN WATCHDOG NOT ARMED — "
ARMED_RE = re.compile(r"breakdown watchdog ARMED after a (\d+\.\d) s wait "
                      r"at 0 V for the scope Reconnect, as at any arming")
BASELINE_7 = ("watchdog baseline 7.0 µA (median of 8 reads at 0 kV); trip "
              "|I−baseline| ≥ 100 µA for 1s")
ANSWERS = {'Energize HV?': True, L.LOCK: True}


class _TimedSG(L._FakeSG):
    """The recording SG, with the moment of each write beside it."""

    def __init__(self):
        super().__init__()
        self.t = []

    def _stamp(self):
        self.t.append(time.monotonic())

    def set_load_polarity(self, channel, load=None, polarity=None):
        super().set_load_polarity(channel, load=load, polarity=polarity)
        self._stamp()

    def set_basic_wave(self, channel, **params):
        super().set_basic_wave(channel, **params)
        self._stamp()

    def set_output(self, channel, on):
        super().set_output(channel, on)
        self._stamp()

    def set_offset(self, channel, offset_v):
        super().set_offset(channel, offset_v)
        self._stamp()

    def first(self, call, pred=lambda w: True):
        """When the first write of `call` matching `pred` was made."""
        for w, t in zip(self.writes, self.t):
            if w[0] == call and pred(w):
                return t
        return None


class _App(L._App):
    """The scope-lock suite's stub with the REAL _run_bg, so a Reconnect
    stays in flight while the worker runs and its done callback lands on
    the thread that pumps root.after, as in the app."""
    _run_bg = G._run_bg
    SLDEA_SCOPE_WAIT_S = getattr(G, 'SLDEA_SCOPE_WAIT_S', 25.0)

    def __init__(self, tmp, wait_s=None):
        super().__init__(tmp, dry=False, real_worker=True, wd_on=True)
        self.sg = _TimedSG()
        self.line_t = []
        self._scope_reconnecting = False
        if wait_s is not None:
            self.SLDEA_SCOPE_WAIT_S = wait_s
        self.sldea_vars['wd_ua'].set('100')
        self.sldea_vars['wd_s'].set('1')
        self._sldea_build_profile = lambda: (
            L._short_profile(landing_s=6.0), None)

    def _sldea_log(self, msg):
        self.lines.append(str(msg))
        self.line_t.append(time.monotonic())

    def when(self, head):
        """When the one run.log line starting with `head` was logged."""
        hits = [t for ln, t in zip(self.lines, self.line_t)
                if ln.startswith(head)]
        assert len(hits) == 1, (head, self.lines)
        return hits[0]


def _scope(app, ramp_v, reads):
    """A fake scope at 7 uA on I_Out at 0 kV and `ramp_v` once the ramp has
    started, each read taking READ_S. Every read is noted in `reads` as
    (scope, caller, channel, SG writes so far, time)."""
    s = L._FakeScope(volts=lambda ch: (
        (ramp_v if L._ramping(app) else REST_V) if ch == 3 else 0.0))

    def on_read(ch, caller):
        reads.append((s, caller, ch, list(app.sg.writes), time.monotonic()))
        time.sleep(READ_S)
    s.on_read = on_read
    return s


class _Connect:
    """What _reconnect's work() opens (cls()), on _run_bg's thread: the
    scope `gives` after `delay_s`, or IOError when it gives None. release()
    ends the delay at once."""

    def __init__(self, gives, delay_s):
        self.gives, self.delay_s = gives, delay_s
        self._go = threading.Event()
        self.calls = 0

    def __call__(self):
        self.calls += 1
        self._go.wait(self.delay_s)
        if self.gives is None:
            raise IOError("no device found")
        return self.gives

    def release(self):
        self._go.set()


def _press(app, connect):
    """The operator presses the scope's Reconnect and says Yes: the real
    _reconnect on the 'Tk' thread. Called from the worker's thread, which
    goes on once the press has happened (the scope handle is gone then)."""
    pressed = threading.Event()

    def press():
        try:
            app._reconnect('scope', connect, app.scope_status)
        finally:
            pressed.set()
    app.root.after(0, press)
    assert pressed.wait(10), "the Reconnect was never pressed"


def _at_camera(app, connect, settle=None):
    """Press Reconnect where the worker resolves the camera, before its
    arming line. `settle(app)` is waited for before the worker goes on."""
    def resolve(idx):
        _press(app, connect)
        t_end = time.monotonic() + 10
        while settle is not None and not settle(app):
            assert time.monotonic() < t_end, "the Reconnect never settled"
            time.sleep(0.01)
        return {'kind': 'cv2', 'index': int(idx)}
    gui.webcam.resolve_camera = resolve           # _patched restores


def _pump(app, each=None, timeout=90):
    """The Tk mainloop's part: play root.after callbacks until the worker
    is done, calling `each()` on every turn."""
    t_end = time.monotonic() + timeout
    while not app.worker_done.is_set():
        assert time.monotonic() < t_end, app.lines
        app.root.run_pending()
        if each is not None:
            each()
        time.sleep(0.005)
    app.root.run_pending()
    assert app.worker_error is None, repr(app.worker_error)


def _settle_connect(app, connect):
    """Let a connect still held end (as a failure when it gives None) and
    its done callback run, so no thread outlives the test."""
    connect.release()
    t_end = time.monotonic() + 10
    while 'connect' in app._bg_busy:
        assert time.monotonic() < t_end
        app.root.run_pending()
        time.sleep(0.005)
    app.root.run_pending()


def _setup_rows(tmp):
    with open(os.path.join(tmp, 'RUN', 'setup.txt'), 'rb') as f:
        raw = f.read()
    return raw.decode('ascii').splitlines()   # ASCII, every line of it


def _shadow_made():
    """Record the #219 shadow rule's construction: -> (made, restore)."""
    real = gui.sldea_profile.NSigmaWatchdog
    made = []

    class Rec(real):
        def __init__(self, *a, **kw):
            made.append((a, kw))
            super().__init__(*a, **kw)
    gui.sldea_profile.NSigmaWatchdog = Rec

    def restore():
        gui.sldea_profile.NSigmaWatchdog = real
    return made, restore


def _waited_run(tmp, ramp_v, delay_s=1.0):
    """A ticked LIVE run whose scope Reconnect is pressed at the camera
    step and comes back `delay_s` later with a new scope; -> (app, new,
    old, reads, shadow constructions)."""
    reads = []
    made, restore = _shadow_made()
    try:
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp)
            old = app.scope
            new = _scope(app, ramp_v, reads)
            connect = _Connect(new, delay_s)
            _at_camera(app, connect)
            app.sldea_run()
            _pump(app)
            _settle_connect(app, connect)
    finally:
        restore()
    return app, new, old, reads, made


def _baseline_reads(reads, scope):
    """The worker's first ten reads of `scope`: its 0 kV baseline, when
    it took one (the run loop's monitor reads come after them)."""
    return [r for r in reads if r[0] is scope
            and r[1] == '_sldea_worker'][:10]


def _shadow_bases(made):
    """The baselines the run's #219 shadow rules were built with (the
    start line's rule text builds one with none, which is left out)."""
    return [(round(kw['base_loc'], 9), kw['base_sigma'])
            for _a, kw in made if 'base_loc' in kw]


def _assert_waited_and_armed(app, new, reads, made, tmp):
    """The wait happened at 0 V, then the normal baseline on the new
    scope, and the run armed as an on-time arming does."""
    t_wait = app.when(WAIT_LINE)
    [armed] = [ln for ln in app.lines if ARMED_RE.match(ln)]
    waited = float(ARMED_RE.match(armed).group(1))
    assert 0.3 <= waited <= 2.5, armed
    # the normal baseline: ten reads of the NEW scope at 0 V, after the
    # wait, the first two discarded, a 7 uA median from the other eight
    base = _baseline_reads(reads, new)
    assert len(base) == 10 and all(r[2] == 3 for r in base), base
    assert base[0][4] > t_wait
    on_at_0v = [('set_load_polarity', 1, 'HZ'),
                ('set_basic_wave', 1, {'WVTP': 'DC', 'OFST': 0.0}),
                ('set_output', 1, True)]
    for r in base:            # the SG on at 0 V, nothing else, throughout
        assert r[3] == on_at_0v, r[3]
    assert BASELINE_7 in app.lines, app.lines
    i_wait = app.lines.index(next(ln for ln in app.lines
                                  if ln.startswith(WAIT_LINE)))
    assert i_wait < app.lines.index(BASELINE_7) < app.lines.index(armed)
    assert not any(NOT_ARMED in ln or 'baseline unavailable' in ln
                   for ln in app.lines), app.lines
    # the #219 shadow starts as at an on-time arming: the same baseline
    assert _shadow_bases(made) == [(7.0, 0.0)], made
    rows = _setup_rows(tmp)
    assert (f"Breakdown watchdog (scope wait): {waited:.1f} s at 0 V for a "
            f"scope Reconnect; the scope came back and the watchdog armed"
            in rows), rows
    assert not any('NOT armed' in r for r in rows), rows
    return waited


# --------------------------------------------------------------------------
# The words
# --------------------------------------------------------------------------

def test_the_wait_records_are_worded_for_every_outcome():
    rec = sp.scope_wait_record
    log, rows = rec('armed', 3.24, 25.0)
    assert log == ("breakdown watchdog ARMED after a 3.2 s wait at 0 V for "
                   "the scope Reconnect, as at any arming (the line above "
                   "says what its 0 kV baseline came to)"), log
    assert rows == ["Breakdown watchdog (scope wait): 3.2 s at 0 V for a "
                    "scope Reconnect; the scope came back and the watchdog "
                    "armed"], rows
    tail = (" Nothing stops this run on a breakdown; only ■ Abort or the end "
            "of the run does. Energize HV? and the start line said ON.")
    cases = {
        'timeout': ("the scope was gone when the run reached the arming "
                    "line, and its Reconnect was still running after a "
                    "25.0 s wait at 0 V, the limit." + tail,
                    ["Breakdown watchdog (start): NOT armed (no scope)",
                     "Breakdown watchdog (scope wait): 25.0 s at 0 V for a "
                     "scope Reconnect, still running at the 25 s limit, so "
                     "NOT armed"]),
        'failed': ("the scope was gone when the run reached the arming "
                   "line, and its Reconnect failed after a 25.0 s wait at "
                   "0 V." + tail,
                   ["Breakdown watchdog (start): NOT armed (no scope)",
                    "Breakdown watchdog (scope wait): 25.0 s at 0 V for a "
                    "scope Reconnect, which failed, so NOT armed"]),
        'aborted': ("■ Abort was pressed after a 25.0 s wait at 0 V for the "
                    "scope Reconnect. The run ends here, at 0 V. Energize "
                    "HV? and the start line said ON.",
                    ["Breakdown watchdog (start): NOT armed (stopped while "
                     "waiting for the scope)",
                     "Breakdown watchdog (scope wait): 25.0 s at 0 V for a "
                     "scope Reconnect, ended by Abort, so NOT armed"]),
        'unread': ("the scope came back after a 25.0 s wait at 0 V for its "
                   "Reconnect, but only 2 of the 8 baseline reads at 0 kV "
                   "answered (a baseline needs 4), so there is no baseline "
                   "to arm from." + tail,
                   ["Breakdown watchdog (start): NOT armed (scope back, but "
                    "no 0 kV baseline)",
                    "Breakdown watchdog (scope wait): 25.0 s at 0 V for a "
                    "scope Reconnect; the scope came back, but only 2 of 8 "
                    "0 kV reads answered, so NOT armed"]),
    }
    for outcome, (words, want_rows) in cases.items():
        log, rows = rec(outcome, 25.0, 25.0, good=2)
        assert log == NOT_ARMED + words, (outcome, log)
        assert rows == want_rows, (outcome, rows)
    for outcome in ('armed',) + tuple(cases):
        for r in rec(outcome, 1.0, 25.0, good=1)[1]:
            r.encode('ascii')              # setup.txt's locale encoding
            assert r.startswith('Breakdown watchdog ('), r
    try:
        rec('back', 1.0, 25.0)
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown outcome was worded")


def test_the_bound_is_twenty_five_seconds():
    assert G.SLDEA_SCOPE_WAIT_S == 25.0


# --------------------------------------------------------------------------
# What a run does
# --------------------------------------------------------------------------

def test_a_reconnect_in_flight_is_waited_for_at_0_v_then_armed():
    """The scope back 1 s after the press: the run waits at 0 V, takes
    the normal baseline on the new scope, arms, and trips at 120 uA over
    the 100 uA trip. The old session is closed by the Reconnect."""
    with tempfile.TemporaryDirectory() as tmp:
        app, new, old, reads, made = _waited_run(tmp, TRIP_V)
        assert old.closed
        assert any(ln.startswith("⚠ scope Reconnect during the LIVE run "
                                 "(confirmed)") for ln in app.lines)
        _assert_waited_and_armed(app, new, reads, made, tmp)
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('run BREAKDOWN-ABORT') for ln in
                   app.lines), app.lines
        assert any(ln.startswith('⚡ BREAKDOWN CONFIRMED — I=120 µA')
                   for ln in app.lines), app.lines
        assert app.sg.writes[-2:] == [('set_offset', 1, 0.0),
                                      ('set_output', 1, False)], \
            app.sg.writes[-4:]


def test_the_waited_arming_trips_on_the_learned_baseline():
    """-95 uA once the ramp has started is 102 uA from the 7 uA baseline
    the waited arming learned, and 95 uA in absolute terms: only a
    watchdog that holds the learned baseline trips on it."""
    with tempfile.TemporaryDirectory() as tmp:
        app, new, _old, reads, made = _waited_run(tmp, BASE_ONLY_V)
        _assert_waited_and_armed(app, new, reads, made, tmp)
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('⚡ BREAKDOWN CONFIRMED — I=-95 µA')
                   for ln in app.lines), app.lines


def test_a_reconnect_that_never_finishes_ends_the_wait_not_armed():
    """The connect still running at the bound (1.5 s here): the run stops
    waiting, stays NOT ARMED and says so, then goes on as before, through
    a current that a watchdog would have tripped on."""
    with tempfile.TemporaryDirectory() as tmp:
        reads = []
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp, wait_s=1.5)
            connect = _Connect(_scope(app, TRIP_V, reads), 60.0)
            _at_camera(app, connect)
            app.sldea_run()
            _pump(app)
            assert app.scope is None and app._scope_reconnecting
            _settle_connect(app, connect)
            assert app.scope is not None and not app._scope_reconnecting
        t_wait = app.when(WAIT_LINE)
        assert WAIT_LINE + "1.5 s, before it arms. ■ Abort ends the run." \
            in app.lines, app.lines
        [warn] = [ln for ln in app.lines if NOT_ARMED in ln]
        m = re.search(r"its Reconnect was still running after a "
                      r"(\d+\.\d) s wait at 0 V, the limit\.", warn)
        assert m and 1.5 <= float(m.group(1)) <= 2.0, warn
        t_not = app.when(NOT_ARMED)
        assert 1.5 <= t_not - t_wait <= 2.0, t_not - t_wait
        # at 0 V with the output on for the whole wait: no offset written
        # until the wait had ended
        t_on = app.sg.first('set_output', lambda w: w[2] is True)
        assert t_on is not None and t_on < t_wait
        assert app.sg.first('set_offset') > t_not
        assert reads == [], "no scope was there to read"
        assert any(ln.startswith('run complete') for ln in app.lines), \
            app.lines
        assert not app._sldea_bd_tripped
        assert ('set_offset', 1, 1.0) in app.sg.writes
        assert app.sg.writes[-2:] == [('set_offset', 1, 0.0),
                                      ('set_output', 1, False)]
        rows = _setup_rows(tmp)
        i = rows.index("Breakdown watchdog (start): NOT armed (no scope)")
        assert rows[i + 1] == (
            f"Breakdown watchdog (scope wait): {m.group(1)} s at 0 V for a "
            f"scope Reconnect, still running at the 1.5 s limit, so NOT "
            f"armed"), rows[i:i + 2]
        assert not any('ARMED after' in ln for ln in app.lines)


def test_abort_during_the_wait_ends_the_run_at_0_v_promptly():
    """Abort 0.3 s into a wait whose connect never comes back, with the
    full 25 s bound: the run ends within a poll or two, at 0 V, its SG
    never commanded above 0 V, and its records say why it never armed."""
    with tempfile.TemporaryDirectory() as tmp:
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp)
            connect = _Connect(None, 60.0)
            _at_camera(app, connect)
            app.sldea_run()
            pressed = []

            def abort_once_waiting():
                if pressed or not any(ln.startswith(WAIT_LINE)
                                      for ln in app.lines):
                    return
                if time.monotonic() - app.when(WAIT_LINE) >= 0.3:
                    pressed.append(time.monotonic())
                    app.sldea_abort()          # ■ Abort, on the Tk thread
            _pump(app, each=abort_once_waiting)
            done_t = time.monotonic()
            _settle_connect(app, connect)
        assert pressed, app.lines
        assert done_t - pressed[0] < 1.0, done_t - pressed[0]
        assert not any(w[0] == 'set_offset' and w[2] != 0
                       for w in app.sg.writes), app.sg.writes
        assert app.sg.writes[-2:] == [('set_offset', 1, 0.0),
                                      ('set_output', 1, False)], \
            app.sg.writes
        assert any(ln.startswith('run aborted') for ln in app.lines), \
            app.lines
        [warn] = [ln for ln in app.lines if NOT_ARMED in ln]
        assert re.search(r"■ Abort was pressed after a 0\.\d s wait at 0 V "
                         r"for the scope Reconnect\. The run ends here", warn), \
            warn
        rows = _setup_rows(tmp)
        assert "Breakdown watchdog (start): NOT armed (stopped while " \
            "waiting for the scope)" in rows, rows
        assert any(r.startswith("Breakdown watchdog (scope wait): ")
                   and r.endswith(", ended by Abort, so NOT armed")
                   for r in rows), rows


def test_a_scope_that_drops_again_during_the_baseline_does_not_arm():
    """The scope back after the wait, then gone again at its fourth
    baseline read (a second Reconnect, answered Yes): two of the eight
    reads that count answered, which is no baseline, so the run stays
    NOT ARMED. The first attempt armed blind here on the absolute rule.
    The second Reconnect brings a scope back 1 s later, reading 120 uA on
    the ramp, and nothing trips: not armed means not armed."""
    with tempfile.TemporaryDirectory() as tmp:
        reads = []
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp)
            third = _scope(app, TRIP_V, reads)
            second_connect = _Connect(third, 1.0)
            new = _scope(app, TRIP_V, reads)
            inner = new.on_read

            def drop_at_fourth(ch, caller):
                if caller == '_sldea_worker' and len(
                        _baseline_reads(reads, new)) == 3:
                    _press(app, second_connect)   # the handle is gone now
                inner(ch, caller)
            new.on_read = drop_at_fourth
            connect = _Connect(new, 0.5)
            _at_camera(app, connect)
            app.sldea_run()
            _pump(app)
            _settle_connect(app, second_connect)
        assert len(_baseline_reads(reads, new)) == 4, reads
        assert app.lines.count("⚠ scope Reconnect during the LIVE run "
                               "(confirmed) — no kV/µA readings until its "
                               "new session is open") == 2, app.lines
        [warn] = [ln for ln in app.lines if NOT_ARMED in ln]
        assert re.search(r"the scope came back after a \d+\.\d s wait at 0 V "
                         r"for its Reconnect, but only 2 of the 8 baseline "
                         r"reads at 0 kV answered", warn), warn
        assert not any('baseline unavailable' in ln or 'ARMED after' in ln
                       or ln.startswith('watchdog baseline')
                       for ln in app.lines), app.lines
        # the third scope was read during the run, at 120 uA on the ramp,
        # and nothing stopped the run
        assert any(r[0] is third and any(w[0] == 'set_offset' and w[2] > 0
                                         for w in r[3]) for r in reads), \
            reads
        assert any(ln.startswith('run complete') for ln in app.lines), \
            app.lines
        assert not app._sldea_bd_tripped
        rows = _setup_rows(tmp)
        i = rows.index("Breakdown watchdog (start): NOT armed (scope back, "
                       "but no 0 kV baseline)")
        assert re.fullmatch(r"Breakdown watchdog \(scope wait\): \d+\.\d s at "
                            r"0 V for a scope Reconnect; the scope came back, "
                            r"but only 2 of 8 0 kV reads answered, so NOT "
                            r"armed", rows[i + 1]), rows[i:i + 2]


def test_no_reconnect_in_flight_means_no_wait():
    """A scope Reconnect that already FAILED before the arming line: no
    scope and nothing in flight. The run does not wait; it says NOT ARMED
    in #406's words, word for word, and writes no wait line."""
    with tempfile.TemporaryDirectory() as tmp:
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp)
            connect = _Connect(None, 0.0)
            _at_camera(app, connect, settle=lambda a: (
                'connect' not in a._bg_busy
                and not a._scope_reconnecting))
            app.sldea_run()
            _pump(app)
        assert connect.calls == 1
        assert app.scope is None and not app._scope_reconnecting
        assert not any(ln.startswith(WAIT_LINE) for ln in app.lines)
        [warn] = [ln for ln in app.lines if NOT_ARMED in ln]
        assert warn == (
            "⚠⚠ BREAKDOWN WATCHDOG NOT ARMED — the scope was gone when the "
            "run reached the arming line (a Reconnect?). Nothing stops this "
            "run on a breakdown; only ■ Abort or the end of the run does. "
            "Energize HV? and the start line said ON."), warn
        # no hold at 0 V: the run clock's first offset write follows the
        # output switch-on at once
        t_on = app.sg.first('set_output', lambda w: w[2] is True)
        assert app.sg.first('set_offset') - t_on < 0.3
        assert any(ln.startswith('run complete') for ln in app.lines)
        rows = _setup_rows(tmp)
        assert "Breakdown watchdog (start): NOT armed (no scope)" in rows
        assert not any('(scope wait)' in r for r in rows), rows


def test_an_on_time_arming_is_unchanged():
    """No Reconnect: the scope is there at the arming line. The same ten
    reads before any offset write, the same 7 uA baseline, the same
    shadow, a trip on the learned baseline, and no wait anywhere."""
    with tempfile.TemporaryDirectory() as tmp:
        reads = []
        made, restore = _shadow_made()
        try:
            with L._patched(L._MB(ANSWERS)):
                app = _App(tmp)
                app.scope = _scope(app, BASE_ONLY_V, reads)
                app.sldea_run()
                _pump(app)
        finally:
            restore()
        assert not any(ln.startswith(WAIT_LINE) or 'ARMED' in ln
                       for ln in app.lines), app.lines
        base = _baseline_reads(reads, app.scope)
        assert len(base) == 10, base
        assert BASELINE_7 in app.lines, app.lines
        assert _shadow_bases(made) == [(7.0, 0.0)], made
        assert all(not any(w[0] == 'set_offset' for w in r[3])
                   for r in base), base
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('⚡ BREAKDOWN CONFIRMED — I=-95 µA')
                   for ln in app.lines), app.lines
        rows = _setup_rows(tmp)
        assert not any('(scope wait)' in r or 'NOT armed' in r
                       for r in rows), rows


def _run():
    # Failures are collected, not fatal (`#280`).
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
