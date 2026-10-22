#!/usr/bin/env python3
"""Headless tests for the LCR sweep on a meter one reply behind (#495, no
hardware, no Tk).

The bug: an LCR sweep stopped on its first sample with "not enough values
to unpack (expected 3, got 1)". The BK 894 can fall one reply behind, so
every query returns the previous query's answer (4c86b00). `get_config`
drains and re-reads on a malformed reply; `measure` split the `:FETC?`
reply three ways with no check. The connect-time config sync ends with
`:CORR:OPEN:STAT?` / `:CORR:SHOR:STAT?`, which answer a bare '1' on this
unit (bench-captured 2026-07-10), and a sweep sends only writes before its
first `:FETC?`, so that '1' became the first sample. Once past it, every
sample was the previous one's reading, silently. What is pinned here:

* `measure` on a lagged meter drains and returns the CURRENT reading; a
  reply that stays malformed raises, quoting it;
* `parse_fetch` takes exactly three numeric fields and nothing else;
* a sweep on a lagged meter whose stale reply is a `:FETC?` answer (the
  case a format check cannot see) records every point's own reading,
  because the worker drains before its first sample;
* the sweep holds the 'lcr-io' busy key from Start to its last event, so
  Apply-style jobs are refused meanwhile, a Start while the key is held
  starts nothing, a correction is refused, and the key is let go on both
  the done and the error paths.

The meter is a fake pyvisa resource under the REAL `BK894` driver (`ask`,
`_drain`, `measure`), and the sweep runs the REAL `lcr_start_sweep`,
`_lcr_sweep_worker`, `_drain_sweep_queue` and `_run_bg` on a Tk-free stub
app whose root queues callbacks for the test to run.

Run: .venv/bin/python tests/test_lcr_sweep_desync.py
"""
import collections as _collections
import csv as _csv
import os as _os
import queue as _queue
import sys as _sys
import tempfile as _tempfile
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import gui  # noqa: E402
from instruments import BK894  # noqa: E402

G = gui.InstrumentControlGUI


def _reading(freq, volt):
    """The fake meter's :FETC? answer at a given set-up: distinct per point
    so a row carrying another point's reading shows."""
    return f"{freq * 1e-12:+.5e},{volt:+.5e},0"


class FakeMeter:
    """pyvisa resource stand-in with an output queue, like the real one:
    a query enqueues its reply and a read takes the OLDEST. `stale` primes
    the queue with a leftover reply, which makes every later query return
    the previous query's answer until a drain empties it."""

    REPLIES = {':FUNC:IMP?': 'CSRS', ':FREQ?': '1.00000e+03',
               ':VOLT?': '1.00000e+00', ':BIAS:VOLT?': '0.00000e+00',
               ':BIAS:STAT?': '0', ':APER?': 'MED,1',
               ':CORR:OPEN:STAT?': '1', ':CORR:SHOR:STAT?': '1'}

    def __init__(self, stale=None, fetch=None, late=None):
        self.timeout = 2000
        self.out = _collections.deque([stale] if stale is not None else [])
        self.freq, self.volt = 1000.0, 1.0
        self.fetch = fetch          # fixed :FETC? answer, overrides _reading
        self.late = late            # query whose reply comes after its read
        self.sent = []

    def write(self, command):
        self.sent.append(command)
        head, _, arg = command.partition(' ')
        if head == ':FREQ':
            self.freq = float(arg)
        elif head == ':VOLT':
            self.volt = float(arg)
        elif command == ':FETC?':
            self.out.append(self.fetch if self.fetch is not None
                            else _reading(self.freq, self.volt))
        elif command.endswith('?'):
            self.out.append(self.REPLIES[command])

    def read(self):
        if not self.out:
            raise TimeoutError("VI_ERROR_TMO")
        return self.out.popleft()

    def query(self, command):
        self.write(command)
        if command == self.late:
            self.late = None        # the read times out; the reply stays
            raise TimeoutError("VI_ERROR_TMO")
        return self.read()


def _lcr(meter):
    lcr = BK894.__new__(BK894)      # skips VisaInstrument.__init__
    lcr.inst = meter
    return lcr


# ---- driver ---------------------------------------------------------------

def test_parse_fetch_takes_exactly_three_numeric_fields():
    assert BK894.parse_fetch('+1.2e-10,+2.0e-03,0') == (1.2e-10, 0.002, 0)
    for bad in ('1', 'CSRS', 'MED,1', '1,2,3,4', '1,x,0', '1,2,0.5', '',
                None):
        assert BK894.parse_fetch(bad) is None, bad


def test_measure_on_a_lagged_meter_drains_and_returns_the_current_reading():
    meter = FakeMeter(stale='1')        # the corr-state answer, as on connect
    lcr = _lcr(meter)
    lcr.set_frequency(100)
    lcr.set_voltage(0.1)
    p, s, st = lcr.measure()
    assert (p, s, st) == BK894.parse_fetch(_reading(100, 0.1))
    assert not meter.out, "drain left the meter behind"
    # Realigned: the next reading is its own, not the previous one's.
    lcr.set_frequency(200)
    assert lcr.measure() == BK894.parse_fetch(_reading(200, 0.1))


def test_get_config_realigns_a_session_already_behind():
    # Why the lag must start AFTER get_config: one behind at its start,
    # :FREQ? reads the mode string, which is not numeric, so it drains.
    meter = FakeMeter(stale='stale')
    lcr = _lcr(meter)
    cfg = lcr.get_config()
    assert cfg['frequency'] == 1000.0 and cfg['voltage'] == 1.0, cfg
    assert lcr.measure() == BK894.parse_fetch(_reading(1000, 1))
    assert meter.sent.count(':FETC?') == 1


def test_measure_after_a_late_reply_in_the_config_syncs_best_effort_block():
    # A path that fits the bench report (not bench-verified): the last
    # correction-state read times out inside update_lcr_config's
    # best-effort block, which swallows the error, and its '1' arrives
    # late. Then the sweep's writes and its first :FETC?, which used to
    # raise "expected 3, got 1".
    meter = FakeMeter(late=':CORR:SHOR:STAT?')
    lcr = _lcr(meter)
    lcr.get_config()
    try:
        lcr.get_bias()
        lcr.get_aperture()
        lcr.get_correction_states()
    except Exception:
        pass                        # as update_lcr_config's work() does
    assert list(meter.out) == ['1'], meter.out
    lcr.set_mode('CPD')
    lcr.set_frequency(100)
    lcr.set_voltage(0.1)
    assert lcr.measure() == BK894.parse_fetch(_reading(100, 0.1))


def test_measure_raises_quoting_a_reply_that_stays_bad():
    lcr = _lcr(FakeMeter(fetch='CSRS'))
    try:
        lcr.measure()
    except ValueError as e:
        msg = str(e)
    else:
        raise AssertionError("a malformed reply was accepted")
    assert "'CSRS'" in msg and 'out of step' in msg, msg
    assert 'unpack' not in msg, msg
    assert lcr.inst.sent.count(':FETC?') == 2, lcr.inst.sent


def test_set_frequency_takes_the_894s_full_range():
    # 20 Hz to 500 kHz is the 894's spec; the app stopped at 100 Hz (#495).
    meter = FakeMeter()
    lcr = _lcr(meter)
    for f in (20, 50, 99.9, 100, 500000):
        lcr.set_frequency(f)
    assert meter.sent == [f':FREQ {f}' for f in (20, 50, 99.9, 100, 500000)]
    for f in (19.9, 0, -100, 500001):
        try:
            lcr.set_frequency(f)
        except ValueError as e:
            assert '20 Hz to 500 kHz' in str(e), e
        else:
            raise AssertionError(f"{f} Hz was accepted")
    assert len(meter.sent) == 5, meter.sent


def test_sweep_axis_takes_20_hz():
    # The sweep's axis limits are the driver's constants, which the
    # setters check against, so the two cannot drift apart (#483).
    assert (BK894.FREQ_MIN_HZ, BK894.FREQ_MAX_HZ) == (20, 500000)
    assert (BK894.VOLT_MIN, BK894.VOLT_MAX) == (0.01, 2.0)
    meter = FakeMeter()
    app, out = _sweep(meter, freqs=(20, 40), volts=(0.1,))
    seen = {}
    real = app._parse_sweep_axis

    def spy(axis, vmin, vmax, name):
        seen[axis] = (vmin, vmax)
        return real(axis, vmin, vmax, name)
    app._parse_sweep_axis = spy
    with _Boxes() as boxes:
        app.run()
    assert seen['freq'] == (BK894.FREQ_MIN_HZ, BK894.FREQ_MAX_HZ), seen
    assert seen['volt'] == (BK894.VOLT_MIN, BK894.VOLT_MAX), seen
    # and the limits are the ones set_frequency and set_voltage enforce
    for setter, lo, hi in ((BK894.check_frequency, BK894.FREQ_MIN_HZ,
                            BK894.FREQ_MAX_HZ),
                           (BK894.check_voltage, BK894.VOLT_MIN,
                            BK894.VOLT_MAX)):
        assert setter(lo) == lo and setter(hi) == hi
        for bad in (lo * 0.999, hi * 1.001):
            try:
                setter(bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"{bad} was accepted")
    assert not boxes.calls, boxes.calls
    assert [r['Frequency (Hz)'] for r in _rows(out)] == ['20', '20', '40',
                                                         '40']


def test_measure_on_a_clean_meter_asks_once():
    meter = FakeMeter()
    assert _lcr(meter).measure() == BK894.parse_fetch(_reading(1000, 1))
    assert meter.sent == [':FETC?'], meter.sent


# ---- sweep ----------------------------------------------------------------

class _Var:
    def __init__(self, value=''):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Widget:
    def __init__(self):
        self.text = None

    def config(self, text=None, **_kw):
        if text is not None:
            self.text = text

    configure = config


class _Root:
    """Queues after() callbacks; the test runs them in the main loop's
    place."""

    def __init__(self):
        self.q = _queue.Queue()

    def after(self, _ms, fn, *args):
        self.q.put((fn, args))

    def run_pending(self, rounds=200):
        for _ in range(rounds):
            try:
                fn, args = self.q.get(timeout=0.5)
            except _queue.Empty:
                return
            fn(*args)


class _App:
    """Tk-free stand-in carrying the real sweep and _run_bg methods."""

    lcr_start_sweep = G.lcr_start_sweep
    _lcr_sweep_worker = G._lcr_sweep_worker
    _drain_sweep_queue = G._drain_sweep_queue
    _sweep_finished_ui = G._sweep_finished_ui
    _sweep_failed_ui = G._sweep_failed_ui
    _sweep_release_lcr = G._sweep_release_lcr
    _interruptible_sleep = G._interruptible_sleep
    _run_bg = G._run_bg
    lcr_run_correction = G.lcr_run_correction
    lcr_stop_continuous = G.lcr_stop_continuous

    def __init__(self, meter, out_path, freqs, volts):
        self.lcr = _lcr(meter)
        self.root = _Root()
        self._bg_busy = set()
        self.sweeping = False
        self._sweep_holds_lcr = False
        self.sweep_thread = None
        self.sweep_queue = _queue.Queue()
        self.lcr_continuous = False
        self._axes = {'freq': freqs, 'volt': volts}
        self.sw_dwell = _Var('0')
        self.sw_samples = _Var('2')
        self.sw_isd = _Var('0')
        self.sw_output = _Var(out_path)
        self.lcr_mode = _Var('CPD')
        self.sw_order = _Var('Freq outer, V inner')
        self.sw_progress = _Widget()
        self.sw_status = _Widget()
        self.status_bar = _Widget()
        self.errors = []

    def _parse_sweep_axis(self, axis, *_a):
        return list(self._axes[axis])

    def _set_sweep_ui_state(self, running):
        pass

    def run(self):
        """Start the sweep, wait for its worker, then run the Tk side."""
        self.lcr_start_sweep()
        if self.sweep_thread is not None:
            self.sweep_thread.join(10)
            assert not self.sweep_thread.is_alive(), "sweep worker hung"
        self.root.run_pending()


class _Boxes:
    """Records messagebox calls instead of opening windows."""

    def __enter__(self):
        self.calls = []
        self.saved = {n: getattr(gui.messagebox, n)
                      for n in ('showerror', 'askyesno', 'askokcancel')}
        gui.messagebox.showerror = \
            lambda *a, **k: self.calls.append(('showerror', a))
        gui.messagebox.askyesno = lambda *a, **k: True
        gui.messagebox.askokcancel = \
            lambda *a, **k: self.calls.append(('askokcancel', a)) or True
        return self

    def __exit__(self, *exc):
        for n, fn in self.saved.items():
            setattr(gui.messagebox, n, fn)


def _rows(path):
    with open(path, newline='') as f:
        return list(_csv.DictReader(f))


def _sweep(meter, freqs=(100, 1000, 10000), volts=(0.1, 0.5)):
    tmp = _tempfile.mkdtemp(prefix='lcr_sweep_')
    out = _os.path.join(tmp, 'sweep.csv')
    app = _App(meter, out, freqs, volts)
    return app, out


def test_sweep_on_a_meter_behind_by_a_fetch_reply_records_each_points_own():
    # A stale :FETC? answer passes the format check, so only the worker's
    # drain before its first sample keeps the rows on their own points.
    meter = FakeMeter(stale=_reading(50, 2.0))
    app, out = _sweep(meter)
    with _Boxes() as boxes:
        app.run()
    assert not boxes.calls, boxes.calls
    rows = _rows(out)
    assert len(rows) == 3 * 2 * 2, len(rows)
    for r in rows:
        want = BK894.parse_fetch(_reading(float(r['Frequency (Hz)']),
                                          float(r['Voltage (V)'])))
        got = (float(r['Primary']), float(r['Secondary']), int(r['Status']))
        assert got == want, (r, want)
    assert 'Sweep complete' in app.sw_status.text, app.sw_status.text


def test_sweep_on_a_meter_left_behind_by_the_connect_sync_completes():
    meter = FakeMeter(stale='1')
    app, out = _sweep(meter)
    with _Boxes() as boxes:
        app.run()
    assert not boxes.calls, boxes.calls
    assert 'Sweep complete' in app.sw_status.text, app.sw_status.text
    assert len(_rows(out)) == 12


def test_sweep_holds_lcr_io_until_its_last_event():
    meter = FakeMeter()
    app, _out = _sweep(meter)
    with _Boxes():
        app.lcr_start_sweep()
        assert 'lcr-io' in app._bg_busy and app._sweep_holds_lcr
        # An Apply/Single/config-sync job is refused while the sweep runs.
        started = app._run_bg(lambda: None, lambda *_: None, busy='lcr-io')
        assert started is False
        app.sweep_thread.join(10)
        # The worker is done but its 'done' event is not drained yet: the
        # key is still held, so a Start now would not drop that event.
        assert 'lcr-io' in app._bg_busy
        app.root.run_pending()
    assert 'lcr-io' not in app._bg_busy and not app._sweep_holds_lcr
    assert 'Sweep complete' in app.sw_status.text


def test_sweep_lets_go_of_lcr_io_on_an_error():
    meter = FakeMeter(fetch='CSRS')
    app, _out = _sweep(meter)
    with _Boxes() as boxes:
        app.run()
    assert 'lcr-io' not in app._bg_busy and not app._sweep_holds_lcr
    assert not app.sweeping
    titles = [a[0] for name, a in boxes.calls if name == 'showerror']
    assert titles == ['Sweep error'], boxes.calls
    assert "'CSRS'" in boxes.calls[0][1][1], boxes.calls


def test_start_while_the_meter_is_busy_starts_nothing():
    for key in ('lcr-io', 'lcr-corr'):
        meter = FakeMeter()
        app, out = _sweep(meter)
        app._bg_busy.add(key)
        with _Boxes():
            app.lcr_start_sweep()
        assert app.sweep_thread is None and not app.sweeping, key
        assert not app._sweep_holds_lcr, key
        assert app._bg_busy == {key}, (key, app._bg_busy)
        assert meter.sent == [] and not _os.path.exists(out), key
        assert 'busy' in app.sw_status.text, app.sw_status.text


def test_correction_is_refused_while_a_sweep_holds_the_meter():
    meter = FakeMeter()
    app, _out = _sweep(meter)
    app._sweep_holds_lcr = True
    with _Boxes() as boxes:
        app.lcr_run_correction('open')
    assert [n for n, _a in boxes.calls] == ['showerror'], boxes.calls
    assert boxes.calls[0][1][0] == 'LCR busy'
    assert 'lcr-corr' not in app._bg_busy
    assert meter.sent == []


def _run():
    # Failures are collected, not fatal (`#280`), as in the other suites.
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
