#!/usr/bin/env python3
"""Headless tests for bench/lcr_speed_probe.py (#505, no instrument).

Nothing here says how fast a real 894 is: only the bench run can. These
pin the probe's own logic against a fake meter on a fake clock:

- a :FETC? that waits for each new measurement reads as all fresh;
- a :FETC? that hands back the last finished reading reads as repeats;
- a timing-out :FETC? is flagged, and the block stops instead of paying
  a timeout per call;
- the probe writes only :APER and :FREQ, never the test level or bias,
  and puts both back, also after Ctrl-C;
- main() writes its CSV and summary where it is told, not into the repo.

Run: .venv/bin/python tests/test_lcr_speed_probe.py
"""
import contextlib
import csv
import importlib.util
import io
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from instruments import BK894      # noqa: E402


def _load_probe():
    """The bench script, imported by path (bench/ is not a package)."""
    path = os.path.join(ROOT, 'bench', 'lcr_speed_probe.py')
    spec = importlib.util.spec_from_file_location('lcr_speed_probe', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


probe = _load_probe()


class FakeMeter(BK894):
    """BK894 with the transport replaced by a fake meter on a fake clock.

    Every query costs rt_ms. With blocking=True a :FETC? also waits one
    measurement time and returns a new reading each call; otherwise it
    returns the reading the meter last finished, which changes once per
    measurement time. fail_fetch=True makes every :FETC? time out."""

    def __init__(self, rt_ms=2.0, blocking=False, fail_fetch=False,
                 interrupt_on_fetch=None):
        self.now = 0.0
        self.rt_ms = rt_ms
        self.blocking = blocking
        self.fail_fetch = fail_fetch
        self.interrupt_on_fetch = interrupt_on_fetch
        self.fetches = 0
        self.taken = 0
        self.writes = []
        self.queries = []
        self.aper = ('MED', 4)
        self.freq = 1000.0
        self.inst = types.SimpleNamespace(timeout=2000)
        self.idn = 'FAKE,894'
        self.resource = 'FAKE::INSTR'
        self.local = False
        self.closed = False

    def clock(self):
        return self.now

    def sleep(self, s):
        self.now += s

    def write(self, command):
        self.writes.append(command)
        if command.startswith(':APER '):
            speed, avg = command.split(' ', 1)[1].split(',')
            self.aper = (speed, int(avg))
        elif command.startswith(':FREQ '):
            self.freq = float(command.split(' ', 1)[1])

    def ask(self, command):
        self.queries.append(command)
        self.now += self.rt_ms / 1000.0
        if command == ':APER?':
            return f"{self.aper[0]},{self.aper[1]}"
        if command == ':FUNC:IMP?':
            return 'CPD'
        if command == ':FREQ?':
            return f"{self.freq:.5e}"
        if command == ':VOLT?':
            return '1.00000e+00'
        if command == ':FETC?':
            self.fetches += 1
            if self.interrupt_on_fetch == self.fetches:
                raise KeyboardInterrupt
            if self.fail_fetch:
                self.now += self.inst.timeout / 1000.0
                raise TimeoutError('VI_ERROR_TMO')
            meas_s = probe.DATASHEET_MS[self.aper[0]] / 1000.0
            if self.blocking:
                self.now += meas_s
                self.taken += 1
                k = self.taken
            else:
                k = int(self.now / meas_s)
            return f"{1e-9 + k * 1e-15:+.6e},{1e-3:+.5e},0"
        raise AssertionError(f"unexpected query {command!r}")

    def _drain(self):
        pass

    def go_local(self):
        self.local = True

    def close(self):
        self.closed = True


def _block(meter, speed, n=40):
    meter.aper = (speed, 1)
    rows = probe.run_block(meter, 'b', ':FETC?', n, meter.clock)
    return rows, probe.summarize(rows, 2000, fetch=True)


def test_blocking_fetch_reads_all_fresh():
    m = FakeMeter(blocking=True)
    rows, s = _block(m, 'MED')
    assert s['n_ok'] == 40 and s['fresh'] == 40, s
    assert abs(s['median_ms'] - 69.0) < 0.01, s['median_ms']
    assert abs(s['fresh_per_s'] - 1000 / 69.0) < 0.1, s['fresh_per_s']
    assert 'almost every reading is new' in probe.verdict('MED', s)


def test_latest_reading_fetch_reads_as_repeats():
    m = FakeMeter(rt_ms=2.0, blocking=False)
    rows, s = _block(m, 'MED')
    # 40 calls x 2 ms = 80 ms of wall time, about one MED measurement
    assert s['fresh'] <= 3, s
    assert s['calls_per_s'] > 400, s
    v = probe.verdict('MED', s)
    assert 'last finished reading' in v, v


def test_timeouts_are_flagged_and_the_block_stops():
    m = FakeMeter(fail_fetch=True)
    rows, s = _block(m, 'FAST', n=50)
    assert len(rows) == probe.MAX_ERRORS_PER_BLOCK, len(rows)
    assert s['n_err'] == 3 and s['n_near_timeout'] == 3, s
    assert 'TimeoutError' in rows[0]['error']
    assert 'timing out' in probe.verdict('FAST', s)


def test_bad_format_reply_is_not_counted_fresh():
    rows = [{'block': 'b', 'query': ':FETC?', 'index': i, 't_start_s': i * 0.01,
             'duration_ms': 5.0, 'reply': r, 'error': ''}
            for i, r in enumerate(['+1e-9,+1e-3,0', '1', '+2e-9,+1e-3,0'])]
    s = probe.summarize(rows, 2000, fetch=True)
    assert s['bad_format'] == 1 and s['fresh'] == 2, s


def test_probe_writes_only_aperture_and_frequency_and_restores():
    m = FakeMeter(blocking=True)
    rows, lines = probe.run_probe(m, 5, [100.0, 1000.0, 10000.0], 0.5,
                                  clock=m.clock, sleep=m.sleep)
    for w in m.writes:
        assert w.startswith((':APER ', ':FREQ ')), w
    assert m.aper == ('MED', 4), m.aper
    assert m.freq == 1000.0, m.freq
    text = '\n'.join(lines)
    assert 'Aperture MED,4: RESTORED' in text, text
    assert 'Frequency 1000 Hz: RESTORED' in text, text
    # 4 round-trip blocks + 3 freqs x 3 speeds, 5 calls each
    assert len(rows) == (4 + 9) * 5, len(rows)


def test_current_frequency_only_by_default_and_not_rewritten():
    m = FakeMeter(blocking=True)
    probe.run_probe(m, 3, [], 0.0, clock=m.clock, sleep=m.sleep)
    assert not any(w.startswith(':FREQ') for w in m.writes), m.writes


def test_unreadable_start_frequency_skips_freqs():
    m = FakeMeter(blocking=True)
    m.get_config = lambda: {'mode': 'CPD', 'frequency': None,
                            'voltage': 1.0}
    rows, lines = probe.run_probe(m, 3, [100.0], 0.0, clock=m.clock,
                                  sleep=m.sleep)
    assert not any(w.startswith(':FREQ') for w in m.writes), m.writes
    assert 'start frequency unreadable' in '\n'.join(lines)


def test_ctrl_c_still_restores_and_reports():
    m = FakeMeter(blocking=True, interrupt_on_fetch=2)
    rows, lines = probe.run_probe(m, 5, [10000.0], 0.0,
                                  clock=m.clock, sleep=m.sleep)
    text = '\n'.join(lines)
    assert 'Stopped by user.' in text, text
    assert m.aper == ('MED', 4) and m.freq == 1000.0, (m.aper, m.freq)
    assert 'RESTORED' in text and 'NOT RESTORED' not in text, text


def test_error_mid_probe_still_restores():
    m = FakeMeter(blocking=True)
    real = m.set_aperture

    def flaky(speed, avg=1):
        if speed == 'SLOW':
            raise OSError('Pipe error')
        return real(speed, avg)
    m.set_aperture = flaky
    rows, lines = probe.run_probe(m, 3, [], 0.0, clock=m.clock,
                                  sleep=m.sleep)
    text = '\n'.join(lines)
    assert 'Probe stopped early: OSError: Pipe error' in text, text
    assert m.aper == ('MED', 4), m.aper


def test_parse_freqs_checks_the_894_range():
    assert probe.parse_freqs('100, 1000') == [100.0, 1000.0]
    assert probe.parse_freqs('') == []
    for bad in ('10', '600000'):
        try:
            probe.parse_freqs(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} accepted")


def test_default_out_dir_is_outside_the_repo():
    d = os.path.abspath(probe.default_out_dir())
    assert not (d + os.sep).startswith(ROOT + os.sep), d


def test_main_writes_csv_and_summary_and_closes():
    made = []

    class Factory(FakeMeter):
        def __init__(self, resource=None):
            super().__init__(blocking=True, rt_ms=0.0)
            made.append(self)

    real = probe.BK894
    probe.BK894 = Factory
    try:
        with tempfile.TemporaryDirectory() as td:
            with contextlib.redirect_stdout(io.StringIO()):
                probe.main(['--n', '3', '--settle', '0', '--out-dir', td])
            names = sorted(os.listdir(td))
            assert len(names) == 2 and names[0].endswith('.csv') \
                and names[1].endswith('.txt'), names
            with open(os.path.join(td, names[0]), newline='',
                      encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
            assert len(rows) == (4 + 3) * 3, len(rows)
            with open(os.path.join(td, names[1]), encoding='utf-8') as f:
                assert 'RESTORED' in f.read()
    finally:
        probe.BK894 = real
    assert made and made[0].local and made[0].closed


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
