#!/usr/bin/env python3
"""Headless tests for the BK894 driver additions (issue #44, no instrument).

Response formats were captured from the real meter (fw 1.0.5, 2026-07-10):
:BIAS:VOLT? -> '0.00000e+00', :BIAS:STAT? -> '0', :APER? -> 'MED,1',
:CORR:OPEN:STAT? -> '1'. Run: .venv/bin/python tests/test_bk894_parse.py
"""
# Runnable from anywhere: put the repo root (one level up) on sys.path
# so the app modules import when this file is executed directly.
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import types

from instruments import BK894


class FakeLCR(BK894):
    """BK894 with the transport stubbed (skips VisaInstrument.__init__)."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.sent = []
        self.inst = types.SimpleNamespace(timeout=2000)

    def ask(self, command):
        self.sent.append(command)
        return self.answers[command]

    def write(self, command):
        self.sent.append(command)


def test_get_config_recovers_from_desynced_reply():
    # The mode string desyncs into the numeric field on the first read; after
    # a buffer DRAIN + retry the meter answers cleanly.
    seq = {':FUNC:IMP?': ['CSRS', 'CSRS'],
           ':FREQ?': ['CSRS', '1.00000e+03'],   # desynced, then correct
           ':VOLT?': ['1.00000e+00', '1.00000e+00']}

    class Retry(BK894):
        def __init__(self):
            self.calls = {}
            self.drained = 0
            self.inst = types.SimpleNamespace(timeout=2000, read=self._read)

        def _read(self):
            self.drained += 1
            raise Exception("buffer empty")     # ends the drain loop

        def ask(self, cmd):
            i = self.calls.get(cmd, 0)
            self.calls[cmd] = i + 1
            vals = seq[cmd]
            return vals[min(i, len(vals) - 1)]

    lcr = Retry()
    cfg = lcr.get_config()
    assert cfg['frequency'] == 1000.0 and cfg['voltage'] == 1.0
    assert cfg['mode'] == 'CSRS'
    assert lcr.drained >= 1                     # it drained and retried


def test_get_config_degrades_instead_of_raising():
    # A persistent desync (every query returns the mode) must NOT raise --
    # numeric fields come back None so the sync degrades, no footer error.
    class Stuck(BK894):
        def __init__(self):
            self.inst = types.SimpleNamespace(timeout=2000, read=self._read)

        def _read(self):
            raise Exception("buffer empty")

        def ask(self, cmd):
            return 'CSRS'

    cfg = Stuck().get_config()
    assert cfg['mode'] == 'CSRS'
    assert cfg['frequency'] is None and cfg['voltage'] is None


def test_parse_aperture():
    assert BK894.parse_aperture('MED,1') == ('MED', 1)
    assert BK894.parse_aperture('SLOW,32') == ('SLOW', 32)
    assert BK894.parse_aperture('fast,4') == ('FAST', 4)
    assert BK894.parse_aperture('MED') == ('MED', 1), "missing count -> 1"


def test_get_bias_parses_meter_format():
    lcr = FakeLCR({':BIAS:VOLT?': '0.00000e+00', ':BIAS:STAT?': '0'})
    assert lcr.get_bias() == {'volts': 0.0, 'on': False}
    lcr = FakeLCR({':BIAS:VOLT?': '1.50000e+00', ':BIAS:STAT?': '1'})
    assert lcr.get_bias() == {'volts': 1.5, 'on': True}


def test_set_bias_validation():
    lcr = FakeLCR()
    lcr.set_bias_voltage(-2.0)
    assert lcr.sent == [':BIAS:VOLT -2.0']
    for bad in (5.1, -6.0):
        try:
            lcr.set_bias_voltage(bad)
            assert False, f"{bad} must raise"
        except ValueError:
            pass
    lcr.set_bias_enabled(True)
    lcr.set_bias_enabled(False)
    assert lcr.sent[-2:] == [':BIAS:STAT 1', ':BIAS:STAT 0']


def test_set_aperture_validation():
    lcr = FakeLCR()
    lcr.set_aperture('slow', 16)
    assert lcr.sent == [':APER SLOW,16']
    for bad_call in (lambda: lcr.set_aperture('TURBO'),
                     lambda: lcr.set_aperture('MED', 0),
                     lambda: lcr.set_aperture('MED', 257)):
        try:
            bad_call()
            assert False, "must raise"
        except ValueError:
            pass


def _raises(fn, *args):
    """-> the ValueError message `fn(*args)` raises, or None."""
    try:
        fn(*args)
    except ValueError as e:
        return str(e)
    return None


def test_validate_config_refuses_what_each_setter_refuses_sending_nothing():
    # #483: Apply runs validate_config before any setter, so it must
    # refuse exactly what the setters refuse, with their message, and
    # never write. One copy of each range: the setters call the checks.
    good = dict(mode='cpd', freq_hz=1000.0, voltage=1.0, speed='med',
                avg=1, bias_volts=0.0)
    setter_of = {
        'mode': lambda lcr, v: lcr.set_mode(v),
        'freq_hz': lambda lcr, v: lcr.set_frequency(v),
        'voltage': lambda lcr, v: lcr.set_voltage(v),
        'speed': lambda lcr, v: lcr.set_aperture(v, 1),
        'avg': lambda lcr, v: lcr.set_aperture('MED', v),
        'bias_volts': lambda lcr, v: lcr.set_bias_voltage(v),
    }
    probes = {
        'mode': ('CPD', 'csrs', 'ZTR', 'XYZ', ''),
        'freq_hz': (19.99, 20, 20.01, 1000, 500000, 500000.1, 0, -20,
                    float('nan'), float('inf')),
        'voltage': (0.0099, 0.01, 1.0, 2.0, 2.0001, 0, -1, float('nan')),
        'speed': ('SLOW', 'fast', 'Med', 'TURBO', ''),
        'avg': (0, 1, 256, 257, -1, 8.0),
        'bias_volts': (-5.0001, -5.0, 0.0, 5.0, 5.0001, float('nan')),
    }
    for field, values in probes.items():
        for v in values:
            lcr = FakeLCR()
            msg = _raises(lambda: BK894.validate_config(**dict(good,
                                                               **{field: v})))
            assert lcr.sent == []
            want = _raises(setter_of[field], lcr, v)
            assert msg == want, (field, v, msg, want)
            # A refused setter writes nothing; an accepted one writes once.
            assert len(lcr.sent) == (0 if want else 1), (field, v, lcr.sent)
    assert BK894.validate_config(**good) is None


def test_validate_config_reports_the_first_bad_field_in_apply_order():
    # Apply used to stop at the first setter that raised: mode, frequency,
    # voltage, aperture, bias. The box keeps naming that same field.
    msg = _raises(lambda: BK894.validate_config('XYZ', 10, 9.0, 'TURBO', 0,
                                                9.0))
    assert msg.startswith('Invalid mode'), msg
    msg = _raises(lambda: BK894.validate_config('CPD', 10, 9.0, 'MED', 0,
                                                9.0))
    assert msg == 'Frequency must be 20 Hz to 500 kHz', msg
    msg = _raises(lambda: BK894.validate_config('CPD', 100, 9.0, 'MED', 0,
                                                9.0))
    assert msg == 'Voltage must be 0.01 to 2.0 V', msg
    msg = _raises(lambda: BK894.validate_config('CPD', 100, 1.0, 'MED', 0,
                                                9.0))
    assert msg == 'Averaging count must be 1 to 256', msg
    msg = _raises(lambda: BK894.validate_config('CPD', 100, 1.0, 'MED', 1,
                                                9.0))
    assert msg == 'Bias must be within +/-5 V', msg


def test_setters_send_what_they_sent_before_the_shared_checks():
    lcr = FakeLCR()
    lcr.set_mode('cpd')
    lcr.set_frequency(1000.0)
    lcr.set_voltage(0.5)
    lcr.set_aperture('slow', 16.0)
    lcr.set_bias_voltage(-2.0)
    assert lcr.sent == [':FUNC:IMP CPD', ':FREQ 1000.0', ':VOLT 0.5',
                        ':APER SLOW,16', ':BIAS:VOLT -2.0'], lcr.sent


def test_correction_states():
    lcr = FakeLCR({':CORR:OPEN:STAT?': '1', ':CORR:SHOR:STAT?': '0'})
    assert lcr.get_correction_states() == {'open': True, 'short': False}


def test_run_correction_sequence_and_timeout_restore():
    lcr = FakeLCR({':CORR:OPEN:STAT?': '1'})
    lcr.run_correction('open')
    # sweep command, completion-blocking query, then enable
    assert lcr.sent == [':CORR:OPEN', ':CORR:OPEN:STAT?', ':CORR:OPEN:STAT 1']
    assert lcr.inst.timeout == 2000, "timeout must be restored"

    # timeout must be restored even when the sweep query fails
    class Boom(FakeLCR):
        def ask(self, command):
            raise RuntimeError("sweep timed out")
    lcr = Boom()
    try:
        lcr.run_correction('short')
        assert False, "must propagate"
    except RuntimeError:
        pass
    assert lcr.inst.timeout == 2000


def test_range_auto():
    lcr = FakeLCR()
    lcr.set_range_auto(True)
    lcr.set_range_auto(False)
    assert lcr.sent == [':FUNC:IMP:RANG:AUTO 1', ':FUNC:IMP:RANG:AUTO 0']


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
