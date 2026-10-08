#!/usr/bin/env python3
"""A ticked LIVE run waits at 0 V for a scope Reconnect in flight while it
arms its breakdown watchdog, then arms as usual (#423).

A LIVE Reconnect confirmed in a run's first seconds (#339) used to leave
the run with no watchdog: the worker builds it once, at the arming line
after the SG output goes on at 0 V, and only if the scope is there. #406's
HV review made such a run say NOT ARMED. Owner decisions 2026-10-08:

* while the scope's own Reconnect is in flight at the arming line, the run
  waits at 0 V, bounded, with Abort checked throughout; a scope back in
  time gets the normal on-time baseline;
* a Reconnect that lands during the 0 kV baseline (the likelier case: the
  baseline takes about 2.8 s) is waited for too, and the baseline taken
  again, with ONE bound for all the waits together; one that finishes
  during the baseline gets the baseline taken once more on its session;
* one rule for the rest: a ticked LIVE run always arms. With a baseline
  short of reads (fewer than 4 of 8), or no scope at all at the arming
  line, it arms on the absolute rule |I| >= trip, and setup.txt says so.
  A scope a later Reconnect brings back is read and trips it. Only a stop
  (Abort or the window closed) leaves it NOT ARMED;
* Abort or the window closing ends the baseline at once.

All of it happens before the run clock starts, so the profile, stills,
video and telemetry keep their timing.

Every run below is the real sldea_run and the real worker on the
scope-lock suite's fakes (tests/test_scope_live_lock.py), with two things
real that the other suites stub: _run_bg, so a connect runs on its own
thread and its done callback lands on the "Tk" thread (this test's pump),
and _reconnect, pressed during the worker's camera setup or during its
baseline, with Yes to its "Scope in use" question. Each scope read takes
0.13 s, the bench's: per-run medians of 104 to 141 ms in nine
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
REWAIT_RE = re.compile(r"breakdown watchdog: only (\d) of the 8 baseline "
                       r"reads at 0 kV answered, and a scope Reconnect is "
                       r"running, so the run waits for it here at 0 V, up "
                       r"to (\d+\.\d) s more \(one (\S+) s bound for every "
                       r"wait\), then takes the baseline again\.")
BACK_RE = re.compile(r"breakdown watchdog: the scope is back after a "
                     r"(\d+\.\d) s wait at 0 V; taking the 0 kV baseline "
                     r"now$")
NOT_ARMED = "⚠⚠ BREAKDOWN WATCHDOG NOT ARMED — "
ARMED_RE = re.compile(r"breakdown watchdog ARMED after (\d+\.\d) s of "
                      r"waiting at 0 V for the scope Reconnect"
                      r"( \((\d) waits\))?; the line above says what its "
                      r"0 kV baseline came to$")
NO_SCOPE_LOG = ("⚠ breakdown watchdog armed on the absolute rule |I| >= "
                "100 uA with no scope at the arming line: nothing is read "
                "until a scope Reconnect succeeds, and the monitoring-lost "
                "alarm fires after 10 s")
NO_SCOPE_ROW = ("Breakdown watchdog (start): armed on the absolute rule "
                "|I| >= 100 uA; no scope at the arming line")
BASELINE_7 = ("watchdog baseline 7.0 µA (median of 8 reads at 0 kV); trip "
              "|I−baseline| ≥ 100 µA for 1s")
STOPPED = "the run was stopped (Abort or the window closed)"
ANSWERS = {'Energize HV?': True, L.LOCK: True}
ON_AT_0V = [('set_load_polarity', 1, 'HZ'),
            ('set_basic_wave', 1, {'WVTP': 'DC', 'OFST': 0.0}),
            ('set_output', 1, True)]


def _unavailable(n):
    return (f"watchdog baseline unavailable ({n}/8 reads ok) — absolute "
            f"trip |I| ≥ 100 µA for 1s")


def _absolute_row(n):
    return (f"Breakdown watchdog (start): armed on the absolute rule |I| >= "
            f"100 uA; only {n} of 8 0 kV reads answered")


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

    def index(self, pred):
        """Where the one run.log line matching `pred` is."""
        hits = [i for i, ln in enumerate(self.lines) if pred(ln)]
        assert len(hits) == 1, self.lines
        return hits[0]


def _scope(app, ramp_v, reads, read_s=READ_S):
    """A fake scope at 7 uA on I_Out at 0 kV and `ramp_v` once the ramp has
    started, each read taking `read_s`. Every read is noted in `reads` as
    (scope, caller, channel, SG writes so far, time)."""
    s = L._FakeScope(volts=lambda ch: (
        (ramp_v if L._ramping(app) else REST_V) if ch == 3 else 0.0))

    def on_read(ch, caller):
        reads.append((s, caller, ch, list(app.sg.writes), time.monotonic()))
        time.sleep(read_s)
    s.on_read = on_read
    return s


def _on_nth_read(scope, reads, n, action):
    """Run `action()` as the worker starts its n-th read of `scope` (1 = the
    first), before that read is answered."""
    inner = scope.on_read

    def on_read(ch, caller):
        if caller == '_sldea_worker' and len(_worker_reads(reads, scope)) \
                == n - 1:
            action()
        inner(ch, caller)
    scope.on_read = on_read


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


def _at_camera(app, action):
    """Run `action()` where the worker resolves the camera, before its
    arming line."""
    def resolve(idx):
        action()
        return {'kind': 'cv2', 'index': int(idx)}
    gui.webcam.resolve_camera = resolve           # _patched restores


def _back_when_running(app, scope):
    """The scope is back (no Reconnect: the handle simply returns) at the
    run loop's first status update, so from the run clock's start on."""
    def status(text, fg=None):
        if app.scope is None and not text.startswith('LIVE  waiting'):
            app.scope = scope
    app._sldea_set_status = status


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


def _settle(app, *connects):
    """Let connects still held end (as a failure when they give None) and
    their done callbacks run, so no thread outlives the test."""
    for c in connects:
        c.release()
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


def _watchdog_rows(tmp):
    """setup.txt's rows after its start block, about the watchdog."""
    return [r for r in _setup_rows(tmp)
            if r.startswith('Breakdown watchdog (')]


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


def _shadow_bases(made):
    """The baselines the run's #219 shadow rules were built with (the
    start line's rule text builds one with none, which is left out)."""
    return [(None if kw['base_loc'] is None else round(kw['base_loc'], 9),
             kw['base_sigma']) for _a, kw in made if 'base_loc' in kw]


def _worker_reads(reads, scope):
    """The worker's reads of `scope` (baseline and monitor ticks)."""
    return [r for r in reads if r[0] is scope and r[1] == '_sldea_worker']


def _baseline_reads(reads, scope):
    """The worker's first ten reads of `scope`: its 0 kV baseline, when it
    took one (the run loop's monitor reads come after them)."""
    return _worker_reads(reads, scope)[:10]


def _assert_at_0v_until_baseline(app, reads, scope):
    """No offset written until `scope` had given its ten baseline reads,
    and the SG on at 0 V, nothing else, throughout."""
    base = _baseline_reads(reads, scope)
    assert len(base) == 10 and all(r[2] == 3 for r in base), base
    for r in base:
        assert r[3] == ON_AT_0V, r[3]


def _ends_at_0v(app):
    assert app.sg.writes[-2:] == [('set_offset', 1, 0.0),
                                  ('set_output', 1, False)], \
        app.sg.writes[-4:]


def _run_waited(tmp, ramp_v, delay_s=1.0):
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
            _at_camera(app, lambda: _press(app, connect))
            app.sldea_run()
            _pump(app)
            _settle(app, connect)
    finally:
        restore()
    return app, new, old, reads, made


def _assert_waited_and_armed(app, new, reads, made, tmp):
    """The wait happened at 0 V, then the normal baseline on the new
    scope, and the run armed as an on-time arming does."""
    t_wait = app.when(WAIT_LINE)
    i_back = app.index(BACK_RE.match)
    waited = float(BACK_RE.match(app.lines[i_back]).group(1))
    assert 0.3 <= waited <= 2.5, app.lines[i_back]
    _assert_at_0v_until_baseline(app, reads, new)
    assert _baseline_reads(reads, new)[0][4] > t_wait
    i_armed = app.index(ARMED_RE.match)
    m = ARMED_RE.match(app.lines[i_armed])
    assert float(m.group(1)) == waited and m.group(2) is None, m.group(0)
    assert i_back < app.lines.index(BASELINE_7) < i_armed
    assert not any(NOT_ARMED in ln or 'baseline unavailable' in ln
                   for ln in app.lines), app.lines
    # the #219 shadow starts as at an on-time arming: the same baseline
    assert _shadow_bases(made) == [(7.0, 0.0)], made
    assert _watchdog_rows(tmp) == [
        f"Breakdown watchdog (scope wait): {waited:.1f} s at 0 V for a "
        f"scope Reconnect at the arming line; the scope came back"], \
        _watchdog_rows(tmp)
    return waited


# --------------------------------------------------------------------------
# The words, and the order of the Reconnect's writes
# --------------------------------------------------------------------------

def test_the_wait_records_are_worded_for_every_outcome():
    assert sp.scope_wait_start_line(25.0, 25.0) == (
        "breakdown watchdog: the scope Reconnect is still running, so the "
        "run waits for it here at 0 V, up to 25 s, before it arms. ■ Abort "
        "ends the run.")
    assert REWAIT_RE.match(sp.scope_wait_start_line(25.0, 21.04, 2))
    assert sp.scope_wait_start_line(25.0, 21.04, 2).endswith(
        "up to 21.0 s more (one 25 s bound for every wait), then takes the "
        "baseline again. ■ Abort ends the run.")
    head = "Breakdown watchdog (scope wait): 3.2 s at 0 V for a scope " \
           "Reconnect "
    ends = {'back': "the scope came back",
            'failed': "the Reconnect failed",
            'timeout': "still running at the 25 s limit",
            'aborted': STOPPED}
    for outcome, end in ends.items():
        log, rows = sp.scope_wait_lines(outcome, 3.24, 25.0)
        assert rows == [head + "at the arming line; " + end], rows
        if outcome == 'back':
            assert BACK_RE.match(log), log
        elif outcome == 'aborted':
            assert log is None, log        # stopped_not_armed_record says it
        else:
            assert log == (f"breakdown watchdog: waited 3.2 s at 0 V for the "
                           f"scope Reconnect: {end}."), log
        log, rows = sp.scope_wait_lines(outcome, 3.24, 25.0, 2)
        assert rows == [head + "after only 2 of 8 0 kV baseline reads "
                        "answered; " + end], rows
        if outcome == 'back':
            assert BACK_RE.match(log), log
        elif outcome == 'aborted':
            assert log == ("breakdown watchdog: waited 3.2 s at 0 V for the "
                           "scope Reconnect: the run was stopped (■ Abort or "
                           "the window closed). It ends here, at 0 V."), log
        else:
            assert log == (f"breakdown watchdog: waited 3.2 s at 0 V for the "
                           f"scope Reconnect: {end}. The baseline stays "
                           f"short, so the absolute rule follows."), log
    # no scope at the arming line: armed on the absolute rule (owner
    # decision 2026-10-08), never "NOT armed (no scope)"
    assert sp.absolute_no_scope_record(100.0) == (NO_SCOPE_LOG,
                                                  [NO_SCOPE_ROW])
    # only a stop leaves a ticked LIVE run NOT armed
    said = " Energize HV? and the start line said ON."
    assert sp.stopped_not_armed_record(0.36) == (
        NOT_ARMED + "the run was stopped (■ Abort or the window closed) "
        "after a 0.4 s wait at 0 V for the scope Reconnect. It ends here, "
        "at 0 V." + said,
        ["Breakdown watchdog (start): NOT armed (stopped while waiting for "
         "the scope)"])
    assert sp.stopped_not_armed_record() == (
        NOT_ARMED + "the run was stopped (■ Abort, the window closed, or a "
        "check before the HV) before its arming line, with no scope there. "
        "It ends here, at 0 V." + said,
        ["Breakdown watchdog (start): NOT armed (stopped before the arming "
         "line)"])
    assert sp.baseline_retake_line(2) == (
        "breakdown watchdog: only 2 of the 8 baseline reads at 0 kV "
        "answered, and a scope Reconnect put a new session in place during "
        "them, so the run takes the baseline again on it",
        ["Breakdown watchdog (retake): only 2 of 8 0 kV reads answered and "
         "a new scope session came up during them; baseline taken again"])
    assert ARMED_RE.match(sp.scope_wait_armed_line(3.24, 1))
    assert ARMED_RE.match(sp.scope_wait_armed_line(3.24, 2)).group(3) == '2'
    assert 'as at any arming' not in sp.scope_wait_armed_line(1.0, 1)
    assert sp.absolute_fallback_line(100.0, 2) == _absolute_row(2)
    rows = [r for outcome in ends for good in (None, 3)
            for r in sp.scope_wait_lines(outcome, 1.0, 25.0, good)[1]]
    rows += sp.absolute_no_scope_record(75.0)[1]
    rows += sp.stopped_not_armed_record(1.0)[1]
    rows += sp.stopped_not_armed_record()[1]
    rows += sp.baseline_retake_line(0)[1]
    rows.append(sp.absolute_fallback_line(75.0, 0))
    for r in rows:
        r.encode('ascii')                  # setup.txt's locale encoding
        assert r.startswith('Breakdown watchdog ('), r
    try:
        sp.scope_wait_lines('unread', 1.0, 25.0)
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown outcome was worded")


def test_the_bound_is_twenty_five_seconds():
    assert G.SLDEA_SCOPE_WAIT_S == 25.0


class _SetOrder(L._App):
    """The scope-lock stub (its _run_bg runs the connect inline), noting
    every write of the scope handle and of the in-flight mark, in order."""

    def __setattr__(self, name, value):
        log = self.__dict__.get('set_log')
        if log is not None and name in ('scope', '_scope_reconnecting'):
            log.append((name, value))
        object.__setattr__(self, name, value)


def test_the_mark_goes_up_before_the_handle_and_down_after_it():
    """The read-order argument rests on two write orders on the Tk thread:
    the mark is set before the handle is dropped, and the new handle is in
    place before the mark is cleared. A failed connect clears the mark
    before its error box, which can stay open for as long as the operator
    leaves it. Another instrument's Reconnect never touches the mark."""
    new = L._FakeScope()
    mb = L._MB({})
    with L._patched(mb):
        app = _SetOrder()
        old = app.scope
        app.set_log = []
        mb.showerror = lambda *a, **k: app.set_log.append(('showerror',))
        app._reconnect('scope', lambda: new, app.scope_status)
        assert app.set_log == [('_scope_reconnecting', True),
                               ('scope', None), ('scope', new),
                               ('_scope_reconnecting', False)], app.set_log
        assert old.closed and app.scope is new

        app.set_log = []

        def fails():
            raise IOError("no device found")
        app._reconnect('scope', fails, app.scope_status)
        assert app.set_log == [('_scope_reconnecting', True),
                               ('scope', None),
                               ('_scope_reconnecting', False),
                               ('showerror',)], app.set_log
        assert app.scope is None

        app.set_log = []
        app._reconnect('lcr', lambda: L._FakeScope(), app.scope_status)
        assert app.set_log == [], app.set_log


# --------------------------------------------------------------------------
# A Reconnect in flight at the arming line
# --------------------------------------------------------------------------

def test_a_reconnect_in_flight_is_waited_for_at_0_v_then_armed():
    """The scope back 1 s after the press: the run waits at 0 V, takes
    the normal baseline on the new scope, arms, and trips at 120 uA over
    the 100 uA trip. The old session is closed by the Reconnect."""
    with tempfile.TemporaryDirectory() as tmp:
        app, new, old, reads, made = _run_waited(tmp, TRIP_V)
        assert old.closed
        assert any(ln.startswith("⚠ scope Reconnect during the LIVE run "
                                 "(confirmed)") for ln in app.lines)
        _assert_waited_and_armed(app, new, reads, made, tmp)
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('run BREAKDOWN-ABORT') for ln in
                   app.lines), app.lines
        assert any(ln.startswith('⚡ BREAKDOWN CONFIRMED — I=120 µA')
                   for ln in app.lines), app.lines
        _ends_at_0v(app)


def test_the_waited_arming_trips_on_the_learned_baseline():
    """-95 uA once the ramp has started is 102 uA from the 7 uA baseline
    the waited arming learned, and 95 uA in absolute terms: only a
    watchdog that holds the learned baseline trips on it."""
    with tempfile.TemporaryDirectory() as tmp:
        app, new, _old, reads, made = _run_waited(tmp, BASE_ONLY_V)
        _assert_waited_and_armed(app, new, reads, made, tmp)
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('⚡ BREAKDOWN CONFIRMED — I=-95 µA')
                   for ln in app.lines), app.lines


def _assert_armed_with_no_scope(app, tmp, rows_before):
    """Armed on the absolute rule with no scope at the arming line (owner
    decision 2026-10-08): its log line and setup.txt row, after the rows
    `rows_before`, no NOT ARMED anywhere, no baseline taken, and the run
    clock's first offset write right after the records."""
    assert NO_SCOPE_LOG in app.lines, app.lines
    assert not any(NOT_ARMED in ln or ARMED_RE.match(ln)
                   or ln.startswith('watchdog baseline')
                   for ln in app.lines), app.lines
    assert _watchdog_rows(tmp) == rows_before + [NO_SCOPE_ROW], \
        _watchdog_rows(tmp)
    assert app.sg.first('set_offset') > app.when(NO_SCOPE_LOG)
    assert app.sg.first('set_offset') - app.when(NO_SCOPE_LOG) < 0.3


def test_a_reconnect_that_fails_during_the_wait_ends_it_and_arms():
    """The connect fails 0.5 s after the press: the wait ends then, not at
    the bound, and the run arms on the absolute rule with no scope (owner
    decision 2026-10-08), then goes on to its end. Its ticks fail their
    reads (logged once), as they would on any armed run whose scope is
    gone."""
    with tempfile.TemporaryDirectory() as tmp:
        with L._patched(L._MB(ANSWERS)) as mb:
            app = _App(tmp)
            connect = _Connect(None, 0.5)
            _at_camera(app, lambda: _press(app, connect))
            app.sldea_run()
            _pump(app)
        assert ('showerror', 'Connection Error') in [c[:2] for c in
                                                     mb.calls], mb.calls
        t_wait = app.when(WAIT_LINE)
        head = "breakdown watchdog: waited "
        i_end = app.index(lambda ln: ln.startswith(head))
        m = re.fullmatch(r"breakdown watchdog: waited (\d+\.\d) s at 0 V for "
                         r"the scope Reconnect: the Reconnect failed\.",
                         app.lines[i_end])
        assert m and float(m.group(1)) < 1.0, app.lines[i_end]
        assert app.line_t[i_end] - t_wait < 1.0
        assert i_end < app.lines.index(NO_SCOPE_LOG)
        _assert_armed_with_no_scope(app, tmp, [
            f"Breakdown watchdog (scope wait): {m.group(1)} s at 0 V for a "
            f"scope Reconnect at the arming line; the Reconnect failed"])
        assert sum(ln.startswith('⚠ monitor scope read failed')
                   for ln in app.lines) == 1, app.lines
        assert any(ln.startswith('run complete') for ln in app.lines), \
            app.lines


def test_a_timed_out_wait_arms_on_the_absolute_rule():
    """The connect still running at the bound (1.5 s here): the run stops
    waiting, arms on the absolute rule with no scope and says so, then
    goes on; no offset is written until the wait has ended."""
    with tempfile.TemporaryDirectory() as tmp:
        reads = []
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp, wait_s=1.5)
            connect = _Connect(_scope(app, TRIP_V, reads), 60.0)
            _at_camera(app, lambda: _press(app, connect))
            app.sldea_run()
            _pump(app)
            assert app.scope is None and app._scope_reconnecting
            _settle(app, connect)
            assert app.scope is not None and not app._scope_reconnecting
        t_wait = app.when(WAIT_LINE)
        assert WAIT_LINE + "1.5 s, before it arms. ■ Abort ends the run." \
            in app.lines, app.lines
        i_end = app.index(lambda ln: ln.startswith(
            "breakdown watchdog: waited "))
        m = re.fullmatch(r"breakdown watchdog: waited (\d+\.\d) s at 0 V for "
                         r"the scope Reconnect: still running at the 1\.5 s "
                         r"limit\.", app.lines[i_end])
        assert m and 1.5 <= float(m.group(1)) <= 2.0, app.lines[i_end]
        assert 1.5 <= app.line_t[i_end] - t_wait <= 2.0
        # at 0 V with the output on for the whole wait
        t_on = app.sg.first('set_output', lambda w: w[2] is True)
        assert t_on is not None and t_on < t_wait
        _assert_armed_with_no_scope(app, tmp, [
            f"Breakdown watchdog (scope wait): {m.group(1)} s at 0 V for a "
            f"scope Reconnect at the arming line; still running at the "
            f"1.5 s limit"])
        assert reads == [], "no scope was there to read"
        assert any(ln.startswith('run complete') for ln in app.lines), \
            app.lines
        assert ('set_offset', 1, 1.0) in app.sg.writes
        _ends_at_0v(app)


def test_a_scope_back_from_a_later_reconnect_trips_the_no_scope_arming():
    """The reviewer's E6, as a test. The first Reconnect fails at the
    arming line, so the run arms on the absolute rule with no scope. Its
    ticks fail: the 10 s CURRENT MONITORING LOST alarm comes about 10 s
    into the run clock. A second Reconnect 11.5 s in brings back a scope
    reading 120 uA on the 1 kV landing: monitoring recovers, and the
    watchdog trips on it and ends the run at 0 V. The #219 shadow runs as
    at any arming without a baseline."""
    with tempfile.TemporaryDirectory() as tmp:
        reads = []
        made, restore = _shadow_made()
        try:
            with L._patched(L._MB(ANSWERS)):
                app = _App(tmp)
                app._sldea_build_profile = lambda: (
                    L._short_profile(landing_s=14.0), None)
                first = _Connect(None, 0.5)
                back = _scope(app, TRIP_V, reads)
                second = _Connect(back, 0.2)
                _at_camera(app, lambda: _press(app, first))
                pressed = []

                def second_reconnect():
                    t_first = app.sg.first('set_offset')
                    if (pressed or t_first is None
                            or 'connect' in app._bg_busy
                            or time.monotonic() - t_first < 11.5):
                        return
                    pressed.append(time.monotonic())
                    app._reconnect('scope', second, app.scope_status)
                app.sldea_run()
                _pump(app, each=second_reconnect)
                _settle(app, first, second)
        finally:
            restore()
        t_clock = app.sg.first('set_offset')
        assert NO_SCOPE_LOG in app.lines, app.lines
        lost = ("⚠⚠ CURRENT MONITORING LOST — scope unreadable for 10 s, "
                "breakdown watchdog is BLIND")
        t_lost = app.when(lost)
        assert 9.9 <= t_lost - t_clock <= 11.0, t_lost - t_clock
        assert pressed and pressed[0] > t_lost
        t_back = app.when('current monitoring recovered')
        assert t_back > pressed[0]
        t_trip = app.when('⚡ BREAKDOWN CONFIRMED — I=120 µA')
        assert 0.8 <= t_trip - t_back <= 2.5, t_trip - t_back
        assert app._sldea_bd_tripped
        assert any(ln.startswith('run BREAKDOWN-ABORT') for ln in
                   app.lines), app.lines
        _ends_at_0v(app)
        assert any(r[0] is back and r[1] == '_sldea_worker' for r in reads)
        assert not any(NOT_ARMED in ln for ln in app.lines), app.lines
        assert _shadow_bases(made) == [(None, None)], made
        assert _watchdog_rows(tmp)[-1] == NO_SCOPE_ROW, _watchdog_rows(tmp)


def test_a_scope_back_at_the_bound_still_counts_as_back():
    """The Reconnect's done callback lands while the worker is between two
    polls, and the bound passes in that gap: the scope is back, and that
    is checked before the bound. Deterministic: the done callback's two
    writes (handle, then mark) are made from inside the wait's own status
    update, after the bound."""
    with tempfile.TemporaryDirectory() as tmp:
        reads = []
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp, wait_s=0.5)
            new = _scope(app, BASE_ONLY_V, reads)

            def drop():                     # what _reconnect does, in order
                app._scope_reconnecting = True
                app.scope = None
            _at_camera(app, drop)

            def status(text, fg=None):
                if text.startswith('LIVE  waiting') and app.scope is None:
                    time.sleep(0.6)
                    app.scope = new
                    app._scope_reconnecting = False
            app._sldea_set_status = status
            app.sldea_run()
            _pump(app)
        i_back = app.index(BACK_RE.match)
        assert float(BACK_RE.match(app.lines[i_back]).group(1)) >= 0.5
        assert BASELINE_7 in app.lines and not any(
            NOT_ARMED in ln for ln in app.lines), app.lines
        assert app._sldea_bd_tripped, app.lines


def test_abort_during_the_wait_ends_the_run_at_0_v_promptly():
    """Abort 0.3 s into a wait whose connect never comes back, with the
    full 25 s bound: the run ends within a poll or two, at 0 V, its SG
    never commanded above 0 V, and its records say it was stopped, without
    claiming which of Abort or the window close did it."""
    with tempfile.TemporaryDirectory() as tmp:
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp)
            connect = _Connect(None, 60.0)
            _at_camera(app, lambda: _press(app, connect))
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
            _settle(app, connect)
        assert pressed, app.lines
        assert done_t - pressed[0] < 1.0, done_t - pressed[0]
        assert not any(w[0] == 'set_offset' and w[2] != 0
                       for w in app.sg.writes), app.sg.writes
        _ends_at_0v(app)
        assert any(ln.startswith('run aborted') for ln in app.lines), \
            app.lines
        [warn] = [ln for ln in app.lines if NOT_ARMED in ln]
        assert re.search(r"the run was stopped \(■ Abort or the window "
                         r"closed\) after a 0\.\d s wait at 0 V for the scope "
                         r"Reconnect\. It ends here, at 0 V\.", warn), warn
        rows = _watchdog_rows(tmp)
        assert len(rows) == 2 and rows[0].endswith(
            "at the arming line; " + STOPPED), rows
        assert rows[1] == ("Breakdown watchdog (start): NOT armed (stopped "
                           "while waiting for the scope)"), rows


def test_no_reconnect_in_flight_means_no_wait_and_the_absolute_rule():
    """A scope Reconnect that already FAILED before the arming line: no
    scope and nothing in flight. The run does not wait. It arms on the
    absolute rule with no scope and says so; #406's NOT ARMED record for
    this case is gone (owner decision 2026-10-08)."""
    with tempfile.TemporaryDirectory() as tmp:
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp)
            connect = _Connect(None, 0.0)

            def press_and_let_it_fail():
                _press(app, connect)
                t_end = time.monotonic() + 10
                while 'connect' in app._bg_busy or app._scope_reconnecting:
                    assert time.monotonic() < t_end
                    time.sleep(0.01)
            _at_camera(app, press_and_let_it_fail)
            app.sldea_run()
            _pump(app)
        assert connect.calls == 1
        assert app.scope is None and not app._scope_reconnecting
        assert not any(ln.startswith('breakdown watchdog:')
                       for ln in app.lines), app.lines
        _assert_armed_with_no_scope(app, tmp, [])
        # no hold at 0 V: the run clock's first offset write follows the
        # output switch-on at once
        t_on = app.sg.first('set_output', lambda w: w[2] is True)
        assert app.sg.first('set_offset') - t_on < 0.3
        assert any(ln.startswith('run complete') for ln in app.lines)


def test_a_run_stopped_before_its_arming_line_with_no_scope_is_not_armed():
    """Abort during the camera start-up, with the scope gone and nothing
    in flight: the SG is never switched on, and the run is the one kind of
    ticked LIVE run left NOT ARMED, with its records saying it was
    stopped."""
    with tempfile.TemporaryDirectory() as tmp:
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp)

            def gone_and_aborted():
                app.scope = None
                app.sldea_abort()
            _at_camera(app, gone_and_aborted)
            app.sldea_run()
            _pump(app)
        assert not any(w == ('set_output', 1, True) for w in app.sg.writes)
        assert not any(w[0] == 'set_offset' and w[2] != 0
                       for w in app.sg.writes), app.sg.writes
        [warn] = [ln for ln in app.lines if NOT_ARMED in ln]
        assert warn == (NOT_ARMED + "the run was stopped (■ Abort, the "
                        "window closed, or a check before the HV) before "
                        "its arming line, with no scope there. It ends "
                        "here, at 0 V. Energize HV? and the start line said "
                        "ON."), warn
        assert NO_SCOPE_LOG not in app.lines
        assert _watchdog_rows(tmp) == [
            "Breakdown watchdog (start): NOT armed (stopped before the "
            "arming line)"], _watchdog_rows(tmp)
        assert any(ln.startswith('run aborted') for ln in app.lines)


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
        assert not any(ln.startswith('breakdown watchdog') or 'ARMED' in ln
                       for ln in app.lines), app.lines
        _assert_at_0v_until_baseline(app, reads, app.scope)
        assert BASELINE_7 in app.lines, app.lines
        assert _shadow_bases(made) == [(7.0, 0.0)], made
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('⚡ BREAKDOWN CONFIRMED — I=-95 µA')
                   for ln in app.lines), app.lines
        assert _watchdog_rows(tmp) == [], _watchdog_rows(tmp)


# --------------------------------------------------------------------------
# A Reconnect during the 0 kV baseline: wait again, take it again
# --------------------------------------------------------------------------

def test_a_reconnect_during_an_on_time_baseline_is_waited_for():
    """The likelier #339 case: the scope there at the arming line, the
    Reconnect pressed at its fourth baseline read. Two of eight reads
    answered, a Reconnect in flight: the run waits at 0 V, takes the whole
    baseline again on the new scope, and arms from it (it trips at -95 uA,
    which only the learned 7 uA baseline can)."""
    with tempfile.TemporaryDirectory() as tmp:
        reads = []
        made, restore = _shadow_made()
        try:
            with L._patched(L._MB(ANSWERS)):
                app = _App(tmp)
                first = app.scope = _scope(app, BASE_ONLY_V, reads)
                new = _scope(app, BASE_ONLY_V, reads)
                connect = _Connect(new, 1.0)
                _on_nth_read(first, reads, 4, lambda: _press(app, connect))
                app.sldea_run()
                _pump(app)
                _settle(app, connect)
        finally:
            restore()
        assert len(_worker_reads(reads, first)) == 4, reads
        i_re = app.index(REWAIT_RE.match)
        m = REWAIT_RE.match(app.lines[i_re])
        assert m.group(1) == '2' and m.group(3) == '25', m.group(0)
        i_back = app.index(BACK_RE.match)
        waited = float(BACK_RE.match(app.lines[i_back]).group(1))
        _assert_at_0v_until_baseline(app, reads, new)
        i_armed = app.index(ARMED_RE.match)
        assert i_re < i_back < app.lines.index(BASELINE_7) < i_armed
        assert float(ARMED_RE.match(app.lines[i_armed]).group(1)) == waited
        assert not any(ln.startswith('watchdog baseline unavailable')
                       or NOT_ARMED in ln for ln in app.lines), app.lines
        assert _shadow_bases(made) == [(7.0, 0.0)], made
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('⚡ BREAKDOWN CONFIRMED — I=-95 µA')
                   for ln in app.lines), app.lines
        assert _watchdog_rows(tmp) == [
            f"Breakdown watchdog (scope wait): {waited:.1f} s at 0 V for a "
            f"scope Reconnect after only 2 of 8 0 kV baseline reads "
            f"answered; the scope came back"], _watchdog_rows(tmp)


def test_a_reconnect_during_the_waited_baseline_is_waited_for_again():
    """The scope back after the first wait, then a second Reconnect at its
    fourth baseline read: the run waits again, takes the baseline again on
    the third scope, arms after two waits and trips at 120 uA. (The first
    version of this change left that run NOT ARMED.)"""
    with tempfile.TemporaryDirectory() as tmp:
        reads = []
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp)
            third = _scope(app, TRIP_V, reads)
            second_connect = _Connect(third, 1.0)
            new = _scope(app, TRIP_V, reads)
            _on_nth_read(new, reads, 4, lambda: _press(app, second_connect))
            connect = _Connect(new, 0.5)
            _at_camera(app, lambda: _press(app, connect))
            app.sldea_run()
            _pump(app)
            _settle(app, connect, second_connect)
        assert len(_worker_reads(reads, new)) == 4, reads
        assert app.lines.count("⚠ scope Reconnect during the LIVE run "
                               "(confirmed) — no kV/µA readings until its "
                               "new session is open") == 2, app.lines
        backs = [ln for ln in app.lines if BACK_RE.match(ln)]
        assert len(backs) == 2, app.lines
        waits = [float(BACK_RE.match(b).group(1)) for b in backs]
        assert REWAIT_RE.match(
            app.lines[app.index(REWAIT_RE.match)]).group(1) == '2'
        _assert_at_0v_until_baseline(app, reads, third)
        m = ARMED_RE.match(app.lines[app.index(ARMED_RE.match)])
        assert m.group(3) == '2', m.group(0)
        assert abs(float(m.group(1)) - sum(waits)) <= 0.11, (m.group(0),
                                                             waits)
        assert BASELINE_7 in app.lines
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('⚡ BREAKDOWN CONFIRMED — I=120 µA')
                   for ln in app.lines), app.lines
        rows = _watchdog_rows(tmp)
        assert len(rows) == 2, rows
        assert rows[0].endswith("at the arming line; the scope came back")
        assert rows[1].endswith("after only 2 of 8 0 kV baseline reads "
                                "answered; the scope came back"), rows


def test_all_the_waits_share_one_bound():
    """A 3 s bound: the first wait takes 0.5 s, the baseline about 1.9 s
    more until a second Reconnect, which never finishes. The re-wait gets
    only what is left of the 3 s, then the run arms on the absolute rule
    from its short baseline and says so."""
    with tempfile.TemporaryDirectory() as tmp:
        reads = []
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp, wait_s=3.0)
            second_connect = _Connect(None, 60.0)
            new = _scope(app, TRIP_V, reads)
            _on_nth_read(new, reads, 4, lambda: _press(app, second_connect))
            connect = _Connect(new, 0.5)
            _at_camera(app, lambda: _press(app, connect))
            app.sldea_run()
            _pump(app)
            _settle(app, connect, second_connect)
        t_first = app.when(WAIT_LINE)
        m = REWAIT_RE.match(app.lines[app.index(REWAIT_RE.match)])
        left = float(m.group(2))
        assert 0.2 <= left <= 1.5 and m.group(3) == '3', m.group(0)
        i_end = app.index(lambda ln: ln.startswith(
            "breakdown watchdog: waited ") and "still running at the 3 s "
            "limit. The baseline stays short, so the absolute rule "
            "follows." in ln)
        assert 2.95 <= app.line_t[i_end] - t_first <= 3.4, \
            app.line_t[i_end] - t_first
        i_un = app.lines.index(_unavailable(2))
        i_armed = app.index(ARMED_RE.match)
        assert i_end < i_un < i_armed
        assert ARMED_RE.match(app.lines[i_armed]).group(3) == '2'
        assert not any(NOT_ARMED in ln for ln in app.lines), app.lines
        rows = _watchdog_rows(tmp)
        assert len(rows) == 3, rows
        assert rows[0].endswith("at the arming line; the scope came back")
        assert rows[1].endswith("after only 2 of 8 0 kV baseline reads "
                                "answered; still running at the 3 s limit")
        assert rows[2] == _absolute_row(2), rows


class _DeadScope:
    """A scope session that stopped answering: every read raises, as a
    timed-out one does. `on_read(n)` runs at its n-th read first."""

    def __init__(self, on_read=None):
        self.n = 0
        self.on_read = on_read

    def measure_raw(self, meas_type, channel):
        self.n += 1
        if self.on_read is not None:
            self.on_read(self.n)
        raise IOError("VI_ERROR_TMO")


def test_a_reconnect_that_finishes_inside_the_baseline_gets_a_retake():
    """The HV re-check's low finding: a Reconnect that finishes before the
    baseline ends has already cleared the flag, so nothing waits. Here the
    session stops answering at the fourth baseline read and a new one is
    in place by the last: two of eight reads, the flag clear, a new scope
    there. The run takes the baseline once more on it and arms from it, so
    it trips at -95 uA, which the absolute rule never would. Deterministic:
    the handle is swapped by the reads themselves, as done() would."""
    with tempfile.TemporaryDirectory() as tmp:
        reads = []
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp)
            first = app.scope = _scope(app, BASE_ONLY_V, reads)
            fresh = _scope(app, BASE_ONLY_V, reads)

            def last_read(n):
                if n == 6:                   # the baseline's tenth read
                    app.scope = fresh
            dead = _DeadScope(last_read)

            def stops_answering():
                app.scope = dead
            _on_nth_read(first, reads, 4, stops_answering)
            app.sldea_run()
            _pump(app)
        assert len(_worker_reads(reads, first)) == 4 and dead.n == 6
        i_re = app.index(lambda ln: ln.startswith(
            "breakdown watchdog: only 2 of the 8 baseline reads at 0 kV "
            "answered, and a scope Reconnect put a new session in place"))
        _assert_at_0v_until_baseline(app, reads, fresh)
        assert i_re < app.lines.index(BASELINE_7)
        assert not any(ln.startswith('watchdog baseline unavailable')
                       or ARMED_RE.match(ln) or REWAIT_RE.match(ln)
                       for ln in app.lines), app.lines
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('⚡ BREAKDOWN CONFIRMED — I=-95 µA')
                   for ln in app.lines), app.lines
        assert _watchdog_rows(tmp) == [
            "Breakdown watchdog (retake): only 2 of 8 0 kV reads answered "
            "and a new scope session came up during them; baseline taken "
            "again"], _watchdog_rows(tmp)


def test_only_one_retake():
    """A second session that stops answering too: one retake only, then
    the absolute rule from the retaken baseline's own count."""
    with tempfile.TemporaryDirectory() as tmp:
        reads = []
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp)
            first = app.scope = _scope(app, TRIP_V, reads)
            fresh = _scope(app, TRIP_V, reads)
            another = _scope(app, TRIP_V, reads)

            def swap_to(scope):
                def at(n):
                    if n == 6:
                        app.scope = scope
                return at
            dead2 = _DeadScope(swap_to(another))
            dead1 = _DeadScope(swap_to(fresh))
            _on_nth_read(first, reads, 4,
                         lambda: setattr(app, 'scope', dead1))
            _on_nth_read(fresh, reads, 4,
                         lambda: setattr(app, 'scope', dead2))
            app.sldea_run()
            _pump(app)
        assert sum(ln.startswith("breakdown watchdog: only 2 of the 8 "
                                 "baseline reads at 0 kV answered, and a "
                                 "scope Reconnect put a new session")
                   for ln in app.lines) == 1, app.lines
        assert _unavailable(2) in app.lines, app.lines
        rows = _watchdog_rows(tmp)
        assert len(rows) == 2 and rows[0].startswith(
            "Breakdown watchdog (retake): "), rows
        assert rows[1] == _absolute_row(2), rows
        assert app._sldea_bd_tripped, app.lines      # 120 uA, absolute


# --------------------------------------------------------------------------
# A baseline still short: the absolute rule (owner decision 2026-10-08)
# --------------------------------------------------------------------------

def _short_baseline_run(tmp, waited):
    """A ticked LIVE run whose scope stops answering at its fourth
    baseline read with no Reconnect in flight (the handle simply goes), and
    is there again from the run clock's start, at 120 uA on the ramp.
    With `waited`, the scope came back from a wait at the arming line
    first."""
    reads = []
    made, restore = _shadow_made()
    try:
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp)
            scope = _scope(app, TRIP_V, reads)

            def gone():
                app.scope = None
            _on_nth_read(scope, reads, 4, gone)
            _back_when_running(app, scope)
            if waited:
                connect = _Connect(scope, 0.5)
                _at_camera(app, lambda: _press(app, connect))
            else:
                app.scope = scope
            app.sldea_run()
            _pump(app)
            if waited:
                _settle(app, connect)
    finally:
        restore()
    return app, scope, reads, made


def test_a_short_on_time_baseline_arms_on_the_absolute_rule():
    """Two of eight reads on time: the absolute rule, as before, and now
    setup.txt says so instead of leaving the start line's "baseline
    learned at 0 kV" standing. The scope back from the run clock's start
    at 120 uA trips it."""
    with tempfile.TemporaryDirectory() as tmp:
        app, scope, reads, made = _short_baseline_run(tmp, waited=False)
        assert len(_baseline_reads(reads, scope)) >= 4
        assert _unavailable(2) in app.lines, app.lines
        assert not any(ln.startswith('breakdown watchdog')
                       or NOT_ARMED in ln for ln in app.lines), app.lines
        assert _shadow_bases(made) == [(None, None)], made
        assert _watchdog_rows(tmp) == [_absolute_row(2)], _watchdog_rows(tmp)
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('⚡ BREAKDOWN CONFIRMED — I=120 µA')
                   for ln in app.lines), app.lines


def test_a_short_baseline_after_a_wait_arms_on_the_absolute_rule():
    """The same after a wait (owner decision 2026-10-08, reversing the
    first review's NOT ARMED): the absolute rule, recorded, and it trips
    at 120 uA once the scope answers again. NOT ARMED would have read
    nothing at all with telemetry off."""
    with tempfile.TemporaryDirectory() as tmp:
        app, scope, reads, made = _short_baseline_run(tmp, waited=True)
        i_back = app.index(BACK_RE.match)
        i_un = app.lines.index(_unavailable(2))
        i_armed = app.index(ARMED_RE.match)
        assert i_back < i_un < i_armed
        assert not any(NOT_ARMED in ln or REWAIT_RE.match(ln)
                       for ln in app.lines), app.lines
        assert _shadow_bases(made) == [(None, None)], made
        rows = _watchdog_rows(tmp)
        assert len(rows) == 2 and rows[0].endswith(
            "at the arming line; the scope came back"), rows
        assert rows[1] == _absolute_row(2), rows
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('⚡ BREAKDOWN CONFIRMED — I=120 µA')
                   for ln in app.lines), app.lines


# --------------------------------------------------------------------------
# Abort during the baseline
# --------------------------------------------------------------------------

def test_abort_ends_the_baseline_at_once():
    """A scope whose reads take 1 s each (one stalled near its timeout),
    Abort pressed at the second baseline read: the run ends after the read
    in progress, not after eight more, at 0 V, with no baseline verdict."""
    with tempfile.TemporaryDirectory() as tmp:
        reads = []
        with L._patched(L._MB(ANSWERS)):
            app = _App(tmp)
            app.scope = _scope(app, TRIP_V, reads, read_s=1.0)
            app.sldea_run()
            pressed = []

            def abort_at_second_read():
                if not pressed and len(reads) >= 2:
                    pressed.append(time.monotonic())
                    app.sldea_abort()
            _pump(app, each=abort_at_second_read)
            done_t = time.monotonic()
        assert pressed, app.lines
        assert done_t - pressed[0] < 1.6, done_t - pressed[0]
        assert len(reads) <= 3, len(reads)
        assert not any(ln.startswith('watchdog baseline')
                       for ln in app.lines), app.lines
        assert any(ln.startswith('run aborted') for ln in app.lines), \
            app.lines
        assert not any(w[0] == 'set_offset' and w[2] != 0
                       for w in app.sg.writes), app.sg.writes
        _ends_at_0v(app)
        assert _watchdog_rows(tmp) == [], _watchdog_rows(tmp)


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
            print(f"FAIL {fn.__name__}", flush=True)
            continue
        print(f"ok  {fn.__name__}", flush=True)
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
