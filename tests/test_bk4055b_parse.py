#!/usr/bin/env python3
"""Headless tests for the BK4055B response parsers (no instrument needed).

Feeds captured BSWV?/OUTP? response strings into the parsers and asserts the
resulting dicts/bytes. Run: .venv/bin/python tests/test_bk4055b_parse.py
"""
# Runnable from anywhere: put the repo root (one level up) on sys.path
# so the app modules import when this file is executed directly.
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import struct
import types

from instruments import BK4055B


class FakeSG(BK4055B):
    """BK4055B with the transport stubbed out (skips VisaInstrument.__init__)."""
    def __init__(self, bswv=None, outp=None):
        self._bswv = bswv
        self._outp = outp
        self.sent = []
        self.sent_raw = []
        self.inst = types.SimpleNamespace(timeout=2000)   # upload_arb tweaks this

    def get_basic_wave(self, channel):
        return self._bswv

    def ask(self, command):
        return self._outp

    def write(self, command):
        self.sent.append(command)

    def write_raw(self, data):
        self.sent_raw.append(data)

    def write_raw_oneshot(self, data):
        self.sent_raw.append(data)


def test_strip_unit():
    assert BK4055B._strip_unit('100HZ') == 100.0
    assert BK4055B._strip_unit('0.01S') == 0.01
    assert BK4055B._strip_unit('-1V') == -1.0
    assert BK4055B._strip_unit('1.41421Vrms') == 1.41421
    assert BK4055B._strip_unit('2.4e-07S') == 2.4e-07
    assert BK4055B._strip_unit('HZ') == 'HZ'  # no number -> passthrough


def test_basic_wave_sine():
    sg = FakeSG(bswv='C1:BSWV WVTP,SINE,FRQ,100HZ,PERI,0.01S,AMP,2V,'
                     'OFST,0V,HLEV,1V,LLEV,-1V,PHSE,0')
    d = sg.get_basic_wave_dict(1)
    assert d['WVTP'] == 'SINE'
    assert d['FRQ'] == 100.0
    assert d['AMP'] == 2.0
    assert d['OFST'] == 0.0
    assert d['PHSE'] == 0.0


def test_basic_wave_square_with_duty():
    sg = FakeSG(bswv='C2:BSWV WVTP,SQUARE,FRQ,1000HZ,AMP,3V,OFST,0V,DUTY,30')
    d = sg.get_basic_wave_dict(2)
    assert d['WVTP'] == 'SQUARE'
    assert d['DUTY'] == 30.0


def test_basic_wave_no_echo_prefix():
    # Tolerate a response without the 'C1:BSWV ' echo.
    sg = FakeSG(bswv='WVTP,RAMP,FRQ,50HZ,AMP,1V,SYM,50')
    d = sg.get_basic_wave_dict(1)
    assert d['WVTP'] == 'RAMP'
    assert d['SYM'] == 50.0


def test_output_dict():
    sg = FakeSG(outp='C1:OUTP ON,LOAD,HZ,PLRT,NOR')
    d = sg.get_output_dict(1)
    assert d == {'state': True, 'load': 'HZ', 'polarity': 'NOR'}

    sg = FakeSG(outp='C2:OUTP OFF,LOAD,50,PLRT,INVT')
    d = sg.get_output_dict(2)
    assert d == {'state': False, 'load': '50', 'polarity': 'INVT'}


def test_check_echo_passes_a_reply_that_is_its_own():
    """The Signal Gen sweep (#65) reads back with check_echo=True: a reply
    whose head is this query's own echo parses as before."""
    sg = FakeSG(bswv='C2:BSWV WVTP,SINE,FRQ,100HZ,AMP,2V,OFST,1V')
    d = sg.get_basic_wave_dict(2, check_echo=True)
    assert (d['FRQ'], d['AMP'], d['OFST']) == (100.0, 2.0, 1.0), d
    sg = FakeSG(bswv='c1:bswv WVTP,SINE,FRQ,5HZ')    # case does not matter
    assert sg.get_basic_wave_dict(1, check_echo=True)['FRQ'] == 5.0
    sg = FakeSG(outp='C1:OUTP OFF,LOAD,HZ,PLRT,NOR')
    assert sg.get_output_dict(1, check_echo=True) == {
        'state': False, 'load': 'HZ', 'polarity': 'NOR'}
    sg = FakeSG(outp='C2:OUTP ON')
    assert sg.get_output_dict(2, check_echo=True)['state'] is True
    assert BK4055B._check_echo('C1:BSWV WVTP,SINE', 1, 'BSWV') is None
    assert BK4055B._check_echo('C2:OUTP OFF', 2, 'OUTP') is None


def _refused(call, *args):
    try:
        got = call(*args, check_echo=True)
    except ValueError as e:
        assert 'not its own' in str(e), e
        return str(e)
    raise AssertionError(f"accepted a reply that is not its own: {got}")


def test_check_echo_refuses_another_channel_another_query_or_no_header():
    """A reply left over from an earlier query (another channel's, or an
    OUTP? answer to a BSWV?) must not be parsed as this one's."""
    for raw in ('C1:BSWV WVTP,SINE,FRQ,100HZ',       # another channel
                'C12:BSWV WVTP,SINE',                # not channel 2 either
                'C2:OUTP ON,LOAD,HZ,PLRT,NOR',       # another query
                'C2:BSWVX WVTP,SINE',
                'WVTP,RAMP,FRQ,50HZ,AMP,1V',         # no header at all
                ''):
        msg = _refused(FakeSG(bswv=raw).get_basic_wave_dict, 2)
        assert 'C2:BSWV?' in msg, msg
    for raw in ('C2:OUTP ON,LOAD,HZ', 'C1:BSWV WVTP,SINE,FRQ,100HZ',
                'ON,LOAD,HZ,PLRT,NOR', 'ON', ''):
        msg = _refused(FakeSG(outp=raw).get_output_dict, 1)
        assert 'C1:OUTP?' in msg, msg
    for raw, ch, kind in (('C2:BSWV X', 1, 'BSWV'), ('C1:OUTP ON', 1, 'BSWV'),
                          ('OFF', 1, 'OUTP')):
        try:
            BK4055B._check_echo(raw, ch, kind)
        except ValueError:
            continue
        raise AssertionError(f"_check_echo passed {raw!r} for C{ch}:{kind}")


def test_without_check_echo_the_parse_stays_tolerant():
    """Every other caller keeps the old parse, header or not."""
    for kw in ({}, {'check_echo': False}):
        sg = FakeSG(bswv='C1:BSWV WVTP,SINE,FRQ,100HZ,AMP,2V')
        assert sg.get_basic_wave_dict(2, **kw)['FRQ'] == 100.0
        sg = FakeSG(bswv='WVTP,RAMP,FRQ,50HZ,AMP,1V,SYM,50')
        assert sg.get_basic_wave_dict(1, **kw)['SYM'] == 50.0
        sg = FakeSG(outp='C2:OUTP ON,LOAD,50,PLRT,INVT')
        assert sg.get_output_dict(1, **kw) == {
            'state': True, 'load': '50', 'polarity': 'INVT'}
        sg = FakeSG(outp='OFF')
        assert sg.get_output_dict(1, **kw)['state'] is False


def test_set_basic_wave_number_formatting():
    # Bench-found bug (2026-06-11): 'DUTY,50.0' lands as 5% duty on the
    # 4055B. Floats must be sent without a trailing '.0' and without
    # scientific notation.
    sg = FakeSG()
    sg.set_basic_wave(1, WVTP='SQUARE', FRQ=1000.0, AMP=2.0, OFST=0.0,
                      DUTY=50.0, PHSE=0.0)
    assert sg.sent[0] == ('C1:BSWV WVTP,SQUARE,FRQ,1000,AMP,2,OFST,0,'
                          'DUTY,50,PHSE,0')

    sg.set_basic_wave(2, DUTY=12.5, RISE=1.68e-8)
    assert sg.sent[1] == 'C2:BSWV DUTY,12.5,RISE,0.0000000168'
    assert 'e' not in sg.sent[1].split('RISE,')[1]   # no exponent form

    sg.set_frequency(1, 2500.0)
    assert sg.sent[2] == 'C1:BSWV FRQ,2500'


def test_fmt_param():
    f = BK4055B._fmt_param
    assert f(50.0) == '50'
    assert f(0.0) == '0'
    assert f(12.5) == '12.5'
    assert f(1e-6) == '0.000001'
    assert f(2e6) == '2000000'
    assert f(50) == '50'          # ints pass through
    assert f('HZ') == 'HZ'        # strings pass through


def test_output_dict_minimal():
    # Some firmware returns just the state.
    sg = FakeSG(outp='C1:OUTP OFF')
    d = sg.get_output_dict(1)
    assert d['state'] is False
    assert d['load'] == 'HZ'        # default
    assert d['polarity'] == 'NOR'   # default


def test_samples_to_int16():
    data = BK4055B.samples_to_int16([0.0, 1.0, -1.0, 0.5])
    vals = struct.unpack('<4h', data)
    assert vals == (0, 32767, -32767, 16384)   # 0.5 * 32767 rounds to 16384

    # |samples| > 1 are normalised to full scale
    data = BK4055B.samples_to_int16([2.0, -2.0, 1.0])
    vals = struct.unpack('<3h', data)
    assert vals == (32767, -32767, 16384)      # 1.0/2.0 -> half scale

    try:
        BK4055B.samples_to_int16([])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for empty samples")


def test_upload_arb_message():
    sg = FakeSG()
    samples = [0.0, 1.0, 0.0, -1.0] * 8        # 32 points
    clean = sg.upload_arb(1, 'my wave!', samples, points=32)
    assert clean == 'my_wave_'                 # sanitised name returned
    assert len(sg.sent_raw) == 1
    msg = sg.sent_raw[0]
    # Minimal header only: the 4055B silently rejects the full-field
    # app-note form (bench 2026-07-02) -- level/rate go via BSWV/SRATE.
    header = b'C1:WVDT WVNM,my_wave_,WAVEDATA,'
    assert msg.startswith(header)
    assert b'LENGTH' not in msg
    payload = msg[len(header):]
    assert len(payload) == 32 * 2
    assert struct.unpack('<4h', payload[:8]) == (0, 32767, 0, -32767)


def test_upload_arb_defaults_to_short_buffer():
    # No explicit points -> short ARB_DEFAULT_POINTS buffer (not 16384).
    sg = FakeSG()
    sg.upload_arb(1, 'short', [0.0, 1.0, 0.0, -1.0] * 1000)
    payload = sg.sent_raw[0].split(b'WAVEDATA,', 1)[1]
    assert len(payload) == BK4055B.ARB_DEFAULT_POINTS * 2


class _TimeoutInst:
    """The VISA session's timeout, logged as (op, value, lock held?): the
    upload must save, raise and restore it holding the SG's I/O lock,
    which _drain() holds while it has the timeout at 60 ms."""

    def __init__(self, sg, timeout):
        self._sg, self._timeout, self.log = sg, timeout, []

    def _owned(self):
        lock = self._sg.__dict__.get('_io_rlock')
        return lock is not None and lock._is_owned()

    @property
    def timeout(self):
        self.log.append(('get', self._timeout, self._owned()))
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        self.log.append(('set', value, self._owned()))
        self._timeout = value


class _UploadSG(FakeSG):
    """FakeSG whose write_raw notes the timeout and the lock, and can
    fail the way a dropped LAN link does."""

    def __init__(self, timeout=2000, fail=False):
        super().__init__()
        self.inst = _TimeoutInst(self, timeout)
        self.fail = fail
        self.during = None

    def write_raw(self, data):
        self.during = (self.inst._timeout, self.inst._owned())
        if self.fail:
            raise OSError('VI_ERROR_CONN_LOST')
        self.sent_raw.append(data)


def test_upload_arb_restores_the_timeout_under_the_lock():
    for fail in (False, True):
        sg = _UploadSG(timeout=2000, fail=fail)
        try:
            sg.upload_arb(1, 'w', [0.0, 1.0, 0.0, -1.0] * 8, points=32)
        except OSError:
            assert fail, "raised without a failure"
        else:
            assert not fail, "a failed write_raw was swallowed"
        assert sg.during == (20000, True), sg.during
        assert sg.inst._timeout == 2000, sg.inst.log
        assert sg.inst.log == [('get', 2000, True), ('set', 20000, True),
                               ('set', 2000, True)], sg.inst.log
        assert not sg.inst._owned(), "the upload left the lock held"
    # a longer timeout is kept, not shortened
    sg = _UploadSG(timeout=30000)
    sg.upload_arb(1, 'w', [0.0, 1.0] * 16, points=32)
    assert sg.during == (30000, True) and sg.inst._timeout == 30000


def test_select_arb_and_arwv_parse():
    sg = FakeSG(outp='C1:ARWV INDEX,2,NAME,wave1')
    sg.select_arb(1, 'wave1')
    assert sg.sent == ['C1:BSWV WVTP,ARB', 'C1:ARWV NAME,wave1']
    assert sg.get_arb_dict(1) == {'index': 2, 'name': 'wave1'}

    sg = FakeSG(outp='C2:ARWV NAME,stairs')    # INDEX missing
    assert sg.get_arb_dict(2) == {'index': None, 'name': 'stairs'}


def test_burst_dict_off():
    # bench-captured off form (2026-07-10)
    sg = FakeSG(outp='C1:BTWV STATE,OFF')
    assert sg.get_burst_dict(1) == {'STATE': 'OFF'}


def test_burst_dict_on_with_units():
    sg = FakeSG(outp='C2:BTWV STATE,ON,GATE_NCYC,NCYC,TRSR,MAN,TIME,5,'
                     'PRD,0.01S,DLAY,2.4e-07S')
    d = sg.get_burst_dict(2)
    assert d['STATE'] == 'ON'
    assert d['GATE_NCYC'] == 'NCYC'
    assert d['TRSR'] == 'MAN'
    assert d['TIME'] == 5.0
    assert d['PRD'] == 0.01
    assert d['DLAY'] == 2.4e-07


def test_set_burst_commands_short_and_ordered():
    sg = FakeSG()
    sg.set_burst(1, True, ncycles=5, trigger='INT', period_s=0.25)
    # Trigger source is set BEFORE STATE,ON (so enabling can't auto-fire an
    # internal trigger), and re-asserted after.
    assert sg.sent == ['C1:BTWV TRSR,INT', 'C1:BTWV GATE_NCYC,NCYC',
                       'C1:BTWV TIME,5', 'C1:BTWV PRD,0.25',
                       'C1:BTWV STATE,ON', 'C1:BTWV TRSR,INT']
    assert sg.sent.index('C1:BTWV TRSR,INT') < sg.sent.index('C1:BTWV STATE,ON'), \
        "trigger source must be set before the burst is enabled"
    for cmd in sg.sent:
        assert len(cmd.encode()) <= BK4055B.USB_MAX_CMD, cmd
    sg = FakeSG()
    sg.set_burst(2, False)
    assert sg.sent == ['C2:BTWV STATE,OFF']
    sg = FakeSG()
    sg.set_burst(1, True, ncycles=3, trigger='MAN', period_s=1.0)
    assert not any('PRD' in c for c in sg.sent), \
        "PRD only applies to the INT trigger"


def test_set_burst_validation():
    sg = FakeSG()
    for bad in (lambda: sg.set_burst(1, True, ncycles=0),
                lambda: sg.set_burst(1, True, trigger='BOGUS')):
        try:
            bad()
            assert False, "must raise ValueError"
        except ValueError:
            pass
    assert sg.sent == [], "nothing may be sent on invalid input"


def test_burst_trigger():
    sg = FakeSG()
    sg.burst_trigger(1)
    assert sg.sent == ['C1:BTWV MTRIG']


def test_sync_parse_and_set():
    assert FakeSG(outp='C1:SYNC OFF').get_sync(1) is False
    assert FakeSG(outp='C1:SYNC ON').get_sync(1) is True
    # extra fields after the state must be tolerated
    assert FakeSG(outp='C1:SYNC ON,LOAD,HZ').get_sync(1) is True
    sg = FakeSG()
    sg.set_sync(1, True)
    sg.set_sync(2, False)
    assert sg.sent == ['C1:SYNC ON', 'C2:SYNC OFF']


def test_noise_stdev_mean_parsed_numeric():
    # STDEV/MEAN were missing from _BSWV_NUMERIC: a NOISE channel synced
    # back '0.2V'/'0V' strings into the entries and Apply then died on
    # float() (audit 2026-07-25).
    sg = FakeSG(bswv='C1:BSWV WVTP,NOISE,STDEV,0.2V,MEAN,0V')
    d = sg.get_basic_wave_dict(1)
    assert d['WVTP'] == 'NOISE'
    assert d['STDEV'] == 0.2 and isinstance(d['STDEV'], float), d
    assert d['MEAN'] == 0.0 and isinstance(d['MEAN'], float), d


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = []
    for t in tests:
        try:
            t()
        except Exception:
            failed.append((t.__name__, traceback.format_exc()))
            print(f"FAIL {t.__name__}")
            continue
        print(f"PASS {t.__name__}")
    if not failed:
        print(f"\nAll {len(tests)} parser tests passed.")
        return 0
    head = f"{len(failed)} of {len(tests)} tests failed"
    print(f"\n{head}")
    for name, tb in failed:
        print(f"===== FAIL {name} =====")
        print(tb.rstrip('\n'))
    print(f"===== end {head} =====")
    return 1


if __name__ == '__main__':
    raise SystemExit(_run())
