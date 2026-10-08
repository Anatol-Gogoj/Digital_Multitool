"""'Trek inverts (negate control)' negates the DRIVE only (2026-10-05).

Every run on file read V_Out with the opposite sign to the control: with
the box unticked a positive control gave negative readings. The monitors
measure the Trek output, so negating the control makes that output, and
both monitors, positive. Until 2026-10-05 a ticked box also framed the
V_Out window 0..-need and multiplied both readings by -1, which put a
correctly set run off-screen and logged it negative. These tests pin the
corrected rule: the box flips the control voltage and nothing else.

Run: .venv/bin/python tests/test_trek_polarity.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sldea_profile  # noqa: E402
from tests.test_sldea_telemetry import (  # noqa: E402
    TELEMETRY_FILENAME, _FakeScope, _StubApp, _drive, _read,
    _short_profile)


class _Var:
    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v


class _QueryScope:
    """Answers the monitor check's CH<n>:<cmd>? queries from a table."""

    def __init__(self, answers):
        self.answers = answers
        self.writes = []

    def ask(self, cmd):
        return str(self.answers[cmd])

    def write(self, cmd):
        self.writes.append(cmd)


class _CheckApp:
    import gui as _gui
    _sldea_check_monitors = _gui.InstrumentControlGUI._sldea_check_monitors

    def __init__(self, scope, trek_inv):
        self.scope = scope
        self.sldea_vars = {'vch': _Var('2'), 'ich': _Var('3'),
                           'wd_ua': _Var('100')}
        self.sldea_trek_inv = _Var(trek_inv)
        self.lines = []

    def _sldea_log(self, msg):
        self.lines.append(str(msg))


def _scope_framed_positive(max_kv=10.0, wd_ua=100.0):
    """A scope set exactly as the fix plan sets it for a 0..+kV swing."""
    plan = sldea_profile.monitor_fix_plan(max_kv, wd_ua, v_sign=1.0)
    ans = {}
    for ch, scale, pos in ((2, plan['v_scale'], plan['v_position']),
                           (3, plan['i_scale'], plan['i_position'])):
        ans[f'CH{ch}:SCALE?'] = scale
        ans[f'CH{ch}:PROBEFUNC:EXTATTEN?'] = plan['atten']
        ans[f'CH{ch}:POSITION?'] = pos
        ans[f'CH{ch}:OFFSET?'] = 0.0
    return _QueryScope(ans)


def test_a_ticked_box_still_frames_v_out_on_the_positive_side():
    import gui
    # a problem would ask Yes/No/Cancel; answer Cancel so a regression
    # fails here instead of opening a dialog
    real_ask = gui.messagebox.askyesnocancel
    try:
        gui.messagebox.askyesnocancel = lambda *a, **k: None
        p = _short_profile(end_kv=10.0, step_kv=5.0)
        for ticked in (True, False):
            app = _CheckApp(_scope_framed_positive(), trek_inv=ticked)
            assert app._sldea_check_monitors(p) is True, (ticked, app.lines)
            assert 'monitor check: OK' in app.lines, app.lines
            assert app.scope.writes == [], app.scope.writes
    finally:
        gui.messagebox.askyesnocancel = real_ask


def test_readings_are_logged_as_read_when_the_box_is_ticked():
    """trek_sign=-1 flips the SG control only. A V_Out of +0.5 V and an
    I_Out of +0.05 V are logged as +0.5 kV and +10 uA, in data.csv and in
    the telemetry sidecar alike, and setup.txt says so."""
    with tempfile.TemporaryDirectory() as tmp:
        app = _StubApp(_FakeScope({2: [0.5], 3: [0.05]}))
        rundir = _drive(app, _short_profile(), tmp, trek_sign=-1.0)
        rows = _read(os.path.join(rundir, TELEMETRY_FILENAME))
        assert any(r['measured_uA'] for r in rows), rows
        assert all(r['measured_uA'] == '10.0' for r in rows
                   if r['measured_uA']), rows
        assert all(float(r['measured_kV']) == 0.5 for r in rows
                   if r['measured_kV']), rows
        data = _read(os.path.join(rundir, 'data.csv'))
        assert data and all(float(r['measured_kV']) == 0.5 for r in data)
        with open(os.path.join(rundir, 'setup.txt'), encoding='utf-8') as f:
            setup = f.read()
        assert 'Trek control polarity: INVERTED' in setup
        assert 'logged as read' in setup
        assert 'sign-corrected' not in setup


class _RecordingSG:
    """Accepts any SG call (LIVE runs set load, wave, output and offset)
    and keeps the offsets the run commanded."""

    def __init__(self):
        self.offsets = []

    def set_offset(self, ch, v):
        self.offsets.append((ch, v))

    def __getattr__(self, name):
        return lambda *a, **k: None


def test_the_box_negates_the_sg_control_voltage():
    """The one thing the box still does: the SG offset goes negative."""
    for sign in (-1.0, 1.0):
        with tempfile.TemporaryDirectory() as tmp:
            app = _StubApp(_FakeScope({2: [0.5], 3: [0.05]}))
            app.sg = _RecordingSG()
            _drive(app, _short_profile(start_kv=1.0, end_kv=1.0), tmp,
                   dry=False, trek_sign=sign)
        powered = [v for _ch, v in app.sg.offsets if abs(v) > 1e-9]
        assert powered, ("the worker never drove the SG", app.lines)
        assert all(v * sign > 0 for v in powered), (sign, powered)


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    # Until #426 this file had no runner at all: run_tests.py executes each
    # suite as a script, so it exited 0 having run none of these.
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
