#!/usr/bin/env python3
"""Headless tests for the SLDEA telemetry sidecar (no hardware, no Tk).

The live-run half of #189/#157: the watchdog's ~2 Hz current samples are
written to telemetry.csv beside data.csv instead of being discarded. The
properties pinned here are the ones a live HV run depends on -- the
writer must never raise into the run loop, unreadable samples must still
leave a row, and the achieved rate must be reported honestly.

Run: .venv/bin/python tests/test_sldea_telemetry.py
"""
import csv as _csv
import os as _os
import sys as _sys
import tempfile as _tempfile
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

from sldea_profile import (TelemetryLog, TELEMETRY_COLUMNS,
                           TELEMETRY_FILENAME, TELEMETRY_MAX_HZ,
                           TELEMETRY_MIN_HZ, clamp_telemetry_hz)  # noqa: F401

TS = '2026-08-05T12:00:00.000'


def _read(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(_csv.DictReader(f))


def _log(tmp, **kw):
    return TelemetryLog(_os.path.join(tmp, TELEMETRY_FILENAME), **kw)


def test_header_and_row_shape():
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp)
        t.sample(0.0, TS, 0.0, ua=-16.2, i_status='ok', kv=0.01,
                 v_status='ok')
        t.close()
        rows = _read(t.path)
        assert list(rows[0].keys()) == TELEMETRY_COLUMNS, rows[0]
        assert rows[0]['t_s'] == '0.0'
        assert rows[0]['measured_uA'] == '-16.2'
        assert rows[0]['measured_kV'] == '0.01'
        assert rows[0]['i_status'] == 'ok' and rows[0]['v_status'] == 'ok'
        assert rows[0]['event'] == ''


def test_current_every_sample_kv_at_the_slower_sub_rate():
    """2 Hz current, <=1 Hz kV: the second read is a whole extra
    MEASUREMENT:IMMED triple under the instrument lock, and nominal_kV
    already carries the commanded voltage on every row."""
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp, target_hz=2.0)
        kv_ticks = []
        for i in range(8):                      # 0.0 .. 3.5 s at 2 Hz
            el = i * 0.5
            assert t.due(el), el
            want_kv = t.kv_due(el)
            kv_ticks.append(want_kv)
            t.sample(el, TS, 1.0, ua=1.0, i_status='ok',
                     kv=1.0 if want_kv else None,
                     v_status='ok' if want_kv else '')
            assert not t.due(el), "same tick must not sample twice"
        t.close()
        assert kv_ticks == [True, False] * 4, kv_ticks
        rows = _read(t.path)
        assert len(rows) == 8
        assert [r['measured_kV'] != '' for r in rows] == kv_ticks
        assert [r['v_status'] for r in rows][1] == 'skipped'
        assert t.kv_rows == 4


def test_slow_rate_reads_kv_on_every_sample():
    # at 0.5 Hz the kV floor (1 s) is already satisfied by the sample
    # period, so nothing is sub-sampled away
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp, target_hz=0.5)
        assert t.kv_due(0.0) and t.due(0.0)
        t.sample(0.0, TS, 0.0, ua=0.0, i_status='ok', kv=0.0, v_status='ok')
        assert not t.due(1.0) and t.due(2.0)
        assert t.kv_due(2.0)
        t.close()


def test_unreadable_and_offscreen_samples_still_leave_a_row():
    """A gap in the record IS the evidence that monitoring was lost --
    #159 was filed because a blank cell said nothing about why."""
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp)
        t.sample(0.0, TS, 0.0, ua=None, i_status='invalid')
        t.sample(0.5, TS, 0.5, ua=None, i_status='offscreen')
        t.sample(1.0, TS, 1.0, ua=None, i_status='error')
        t.close()
        rows = _read(t.path)
        assert len(rows) == 3
        assert all(r['measured_uA'] == '' for r in rows)
        assert [r['i_status'] for r in rows] == ['invalid', 'offscreen',
                                                 'error']
        assert t.offscreen == 1 and t.unreadable == 2


def test_write_failure_never_raises_and_stops_cleanly():
    """A full disk or a yanked USB stick costs the record, never the HV
    shutdown path: the run loop must be able to keep calling this."""
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp)
        assert t.sample(0.0, TS, 0.0, ua=1.0, i_status='ok')
        t._f.close()                            # simulate the device going
        assert t.sample(0.5, TS, 0.5, ua=1.0, i_status='ok') is False
        assert t.failed and t.last_error is not None
        # every entry point stays callable and inert afterwards
        assert t.due(9.0) is False
        assert t.kv_due(9.0) is False
        assert t.sample(9.0, TS, 1.0, ua=1.0, i_status='ok') is False
        assert t.event(9.0, TS, 1.0, 'BREAKDOWN CONFIRMED') is False
        assert 'STOPPED EARLY' in t.summary()
        t.close()
        assert len(_read(t.path)) == 1          # the flushed row survived


def test_unwritable_path_fails_at_construction_not_mid_run():
    with _tempfile.TemporaryDirectory() as tmp:
        try:
            TelemetryLog(_os.path.join(tmp, 'no_such_dir', 'x.csv'))
        except OSError:
            pass                                # caller decides: log + skip
        else:
            raise AssertionError("expected the open to fail")


def test_event_rows_do_not_disturb_the_schedule_or_the_rate():
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp)
        t.sample(0.0, TS, 0.0, ua=1.0, i_status='ok', kv=0.0, v_status='ok')
        t.event(0.2, TS, 0.4, 'snap s01 post-ramp', ua=2.0, i_status='ok',
                kv=0.4, v_status='ok')
        assert not t.due(0.2), "an event row must not shift the schedule"
        assert t.due(0.5)
        t.sample(0.5, TS, 0.5, ua=1.0, i_status='ok')
        t.close()
        rows = _read(t.path)
        assert len(rows) == 3 and t.rows == 3
        assert t.samples == 2                   # the event is not a sample
        assert rows[1]['event'] == 'snap s01 post-ramp'
        assert abs(t.achieved_hz() - 2.0) < 1e-9


def test_achieved_rate_gap_and_shortfall_are_reported():
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp, target_hz=2.0)
        for el in (0.0, 0.5, 1.0, 4.0):         # a 3 s stall in the middle
            t.sample(el, TS, 1.0, ua=1.0, i_status='ok')
        t.close()
        assert abs(t.achieved_hz() - 3 / 4.0) < 1e-9
        assert abs(t.max_gap_s - 3.0) < 1e-9
        assert t.rate_shortfall()               # 0.75 Hz vs a 2 Hz target
        line = t.summary()
        assert '0.75 Hz achieved (target 2)' in line
        assert 'max gap 3.0 s' in line and TELEMETRY_FILENAME in line
        # a healthy run does not cry wolf
        u = _log(tmp, target_hz=2.0)
        for i in range(5):
            u.sample(i * 0.5, TS, 1.0, ua=1.0, i_status='ok')
        assert not u.rate_shortfall()
        u.close()


def test_achieved_rate_is_none_below_two_samples():
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp)
        assert t.achieved_hz() is None
        t.sample(0.0, TS, 0.0, ua=1.0, i_status='ok')
        assert t.achieved_hz() is None and not t.rate_shortfall()
        assert 'Hz achieved' not in t.summary()
        t.close()


def test_rate_is_clamped_to_what_the_hardware_is_known_to_sustain():
    assert clamp_telemetry_hz(2.0) == TELEMETRY_MAX_HZ
    assert clamp_telemetry_hz(50.0) == TELEMETRY_MAX_HZ   # bench-unverified
    assert clamp_telemetry_hz(0.0) == TELEMETRY_MIN_HZ
    assert clamp_telemetry_hz(-3.0) == TELEMETRY_MIN_HZ
    assert clamp_telemetry_hz('') == TELEMETRY_MAX_HZ     # empty entry box
    assert clamp_telemetry_hz(None) == TELEMETRY_MAX_HZ
    assert clamp_telemetry_hz(float('nan')) == TELEMETRY_MAX_HZ
    assert clamp_telemetry_hz(1.0) == 1.0
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp, target_hz=99.0)
        assert t.target_hz == TELEMETRY_MAX_HZ and t.period_s == 0.5
        t.close()


def test_blanks_and_rounding_match_the_data_csv_convention():
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp)
        t.sample(1.23456, TS, 2.123456, ua=-207.4567, i_status='ok',
                 kv=7.7512345, v_status='ok')
        t.sample(2.0, TS, None, ua=None, i_status='invalid')
        t.close()
        rows = _read(t.path)
        assert rows[0]['t_s'] == '1.235'
        assert rows[0]['nominal_kV'] == '2.1235'
        assert rows[0]['measured_kV'] == '7.7512'      # 4 dp, like data.csv
        assert rows[0]['measured_uA'] == '-207.46'     # 2 dp, like data.csv
        assert rows[1]['nominal_kV'] == '' and rows[1]['measured_kV'] == ''


def test_a_slow_share_stops_flushing_every_row():
    """The run loop is also the thread that services ■ Abort, and the
    bench's default output dir is a network share. Flushing 2 rows a
    second into a stalling file system would put the ramp-down behind
    the file system, so a slow write degrades to periodic flushing."""
    ticks = [0.0, 0.6]                      # the first write "takes" 0.6 s
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp, clock=lambda: ticks.pop(0) if ticks else 0.0)
        t.sample(0.0, TS, 0.0, ua=1.0, i_status='ok')
        assert t.slow and t.max_write_s >= 0.6
        period = t.flush_period_s()
        assert period >= 4 * 0.6            # the window clears the write
        # rows inside the window are buffered, not flushed...
        t.sample(0.5, TS, 0.5, ua=1.0, i_status='ok')
        t.sample(period - 0.1, TS, 1.0, ua=1.0, i_status='ok')
        assert len(_read(t.path)) == 1
        # ...and the next flush commits the backlog
        t.sample(period, TS, 1.0, ua=1.0, i_status='ok')
        assert len(_read(t.path)) == 4
        assert 'SLOW DISK' in t.summary() and '0.60 s worst write' in \
            t.summary()
        assert f"every {period:.1f} s" in t.summary()
        t.close()


def test_the_throttle_survives_a_write_slower_than_its_own_window():
    """The regime the mitigation exists for. With a fixed 1 s window a
    write costing 1 s+ leaves the window already expired on arrival at
    the next row, so every row flushed anyway and the 0.5 s monitor
    cadence tracked the share 1:1 (measured, review 2026-08-05)."""
    with _tempfile.TemporaryDirectory() as tmp:
        for cost in (1.0, 3.0, 10.0):
            ticks = []
            t = TelemetryLog(_os.path.join(tmp, f'tel_{cost:g}.csv'),
                             clock=lambda: ticks.pop(0) if ticks else 0.0)
            flushed_at = []
            el = 0.0
            for _ in range(30):             # 15 s of run at 2 Hz
                ticks[:] = [0.0, cost]      # every write costs `cost`
                before = len(_read(t.path))
                t.sample(el, TS, 1.0, ua=1.0, i_status='ok')
                if len(_read(t.path)) > before:
                    flushed_at.append(el)
                # the loop is blocked for the write it just did
                el += 0.5 + (cost if flushed_at and flushed_at[-1] == el
                             else 0.0)
            assert t.slow
            assert len(flushed_at) < t.rows, (cost, flushed_at, t.rows)
            gaps = [b - a for a, b in zip(flushed_at, flushed_at[1:])]
            assert all(g >= cost for g in gaps), (cost, gaps)
            t.close()
            assert len(_read(t.path)) == t.rows   # close commits the tail


def test_hold_flush_buffers_the_hv_shutdown_path_until_close():
    """Between a confirmed breakdown and the SG reaching 0 V the Trek is
    still arcing. The trip rows are written — they are the record of the
    event — but nothing waits on the file system until close(), which
    the runner calls after the HV is down."""
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp)
        t.sample(0.0, TS, 0.0, ua=1.0, i_status='ok')
        assert len(_read(t.path)) == 1
        t.hold_flush = True
        t.event(0.4, TS, 5.0, 'BREAKDOWN CONFIRMED', ua=-207.0,
                i_status='ok')
        t.event(0.9, TS, 5.0, 'snap s99 breakdown', ua=-210.0,
                i_status='ok')
        assert len(_read(t.path)) == 1, "the shutdown path must not block"
        t.close()
        rows = _read(t.path)
        assert len(rows) == 3, rows
        assert rows[1]['event'] == 'BREAKDOWN CONFIRMED'
        assert rows[1]['measured_uA'] == '-207.0'


def test_a_healthy_disk_keeps_flushing_every_row():
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp, clock=lambda: 0.0)    # every write instantaneous
        for i in range(4):
            t.sample(i * 0.5, TS, 1.0, ua=1.0, i_status='ok')
            assert len(_read(t.path)) == i + 1
        assert not t.slow and 'SLOW DISK' not in t.summary()
        t.close()


def test_shortfall_tolerates_the_loops_own_quantisation():
    """The 10 Hz run loop turns a 0.5 s gate into 0.5-0.6 s in practice,
    and every snapshot steals a tick. Only a real inability to keep up
    may warn, or the warning gets ignored."""
    with _tempfile.TemporaryDirectory() as tmp:
        ok = _log(tmp, target_hz=2.0)
        for i in range(11):                 # 0.6 s cadence -> 1.67 Hz
            ok.sample(i * 0.6, TS, 1.0, ua=1.0, i_status='ok')
        assert not ok.rate_shortfall(), ok.achieved_hz()
        ok.close()
        bad = TelemetryLog(_os.path.join(tmp, 'slow.csv'), target_hz=2.0)
        for i in range(11):                 # 1.2 s cadence -> 0.83 Hz
            bad.sample(i * 1.2, TS, 1.0, ua=1.0, i_status='ok')
        assert bad.rate_shortfall(), bad.achieved_hz()
        bad.close()


def test_event_text_is_clamped_to_ascii():
    """The run log's own vocabulary is not ASCII (⚡, µA) and `event` is
    caller-supplied, so the file cannot depend on callers staying ASCII."""
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp)
        t.event(0.0, TS, 0.0, '⚡ BREAKDOWN CONFIRMED — 207 µA')
        t.close()
        with open(t.path, 'rb') as f:
            raw = f.read()
        raw.decode('ascii')                 # raises if anything leaked
        assert b'BREAKDOWN CONFIRMED' in raw


def test_garbage_values_cost_one_cell_not_the_record():
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp)
        t.sample(0.0, TS, 0.0, ua=float('nan'), i_status='ok')
        t.sample(0.5, TS, 0.5, ua='not a number', i_status='ok')
        t.sample(1.0, TS, float('inf'), ua=1.0, i_status='ok', kv=None)
        t.sample(1.5, TS, 1.5, ua=2.0, i_status='ok')
        t.close()
        rows = _read(t.path)
        assert len(rows) == 4 and not t.failed
        assert [r['measured_uA'] for r in rows] == ['', '', '1.0', '2.0']
        assert rows[2]['nominal_kV'] == ''


def test_a_failed_log_stops_doing_work_entirely():
    """Not just 'returns False': no per-row work at all, or a dead share
    gets 2 futile writes a second for the rest of a 40-minute run."""
    with _tempfile.TemporaryDirectory() as tmp:
        n = [0]

        def _clock():
            n[0] += 1
            return 0.0
        t = _log(tmp, clock=_clock)
        t.sample(0.0, TS, 0.0, ua=1.0, i_status='ok')
        t._f.close()
        t.sample(0.5, TS, 0.5, ua=1.0, i_status='ok')   # the failing write
        before = n[0]
        for i in range(20):
            t.sample(1.0 + i, TS, 1.0, ua=1.0, i_status='ok')
            t.event(1.0 + i, TS, 1.0, 'ignored')
        assert n[0] == before, "a failed log must not keep working"
        t.close()


def test_close_is_idempotent_and_writing_after_it_is_inert():
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp)
        t.sample(0.0, TS, 0.0, ua=1.0, i_status='ok')
        t.close()
        t.close()                            # no raise
        assert t.sample(0.5, TS, 0.5, ua=1.0, i_status='ok') is False
        assert t.failed
        assert len(_read(t.path)) == 1


def test_an_existing_file_is_replaced_not_appended():
    with _tempfile.TemporaryDirectory() as tmp:
        first = _log(tmp)
        first.sample(0.0, TS, 0.0, ua=1.0, i_status='ok')
        first.close()
        second = _log(tmp)                   # same path, new run
        second.close()
        with open(second.path, encoding='utf-8') as f:
            body = f.read()
        assert body.count('t_s') == 1, body  # exactly one header
        assert not _read(second.path)


def test_rows_survive_an_abrupt_end_without_close():
    # an aborted run kills the worker mid-loop; every row is flushed, so
    # the file on disk is complete up to the last sample
    with _tempfile.TemporaryDirectory() as tmp:
        t = _log(tmp)
        for i in range(3):
            t.sample(i * 0.5, TS, 1.0, ua=1.0, i_status='ok')
        assert len(_read(t.path)) == 3          # read while still open
        t.close()


# --------------------------------------------------------------------------
# Wiring: the real _sldea_worker, driven with a fake scope and no camera.
# The unit tests above cannot see a mis-wired call site, and this loop is
# the live HV path -- the one place where "it compiles" is not enough.
# --------------------------------------------------------------------------

class _FakeScope:
    """measure_raw stand-in. Per-channel scripted scope-volts; the last
    entry repeats forever. `calls` records (type, channel) in order."""

    def __init__(self, by_ch, raise_on=()):
        self.by_ch = {ch: list(v) for ch, v in by_ch.items()}
        self.raise_on = set(raise_on)
        self.calls = []

    def measure_raw(self, meas_type, channel):
        self.calls.append((meas_type, channel))
        if channel in self.raise_on:
            raise IOError(f"CH{channel}: link timeout")
        seq = self.by_ch.get(channel) or [None]
        v = seq[0] if len(seq) == 1 else seq.pop(0)
        if v is None:
            return None, 'offscreen'
        return v, 'ok'


class _StubApp:
    """Just enough app for _sldea_worker: no Tk, no SG, no camera."""
    import gui as _gui
    SLDEA_POLL_S = _gui.InstrumentControlGUI.SLDEA_POLL_S
    _sldea_worker = _gui.InstrumentControlGUI._sldea_worker
    _sldea_capture = _gui.InstrumentControlGUI._sldea_capture

    def __init__(self, scope):
        import threading
        import types
        self.scope, self.sg = scope, None
        self._sldea_stop = False
        self._sldea_bd_tripped = False
        self._sldea_elapsed = 0.0
        self._sldea_prelog, self._sldea_runlog = [], None
        self._sldea_loglock = threading.Lock()
        self.lines = []
        self.root = types.SimpleNamespace(after=lambda *a, **k: None)

    def _sldea_log(self, msg):
        self.lines.append(str(msg))

    def _sldea_set_status(self, *a, **k):
        pass

    def _sldea_finished(self):
        pass


def _short_profile(**kw):
    from sldea_profile import SldeaProfile
    opts = dict(start_kv=0.0, end_kv=1.0, step_kv=1.0, ramp_s=0.4,
                landing_s=1.2, settle_s=0.2, snap_lead_s=0.2)
    opts.update(kw)
    return SldeaProfile(**opts)


def _drive(app, p, tmp, **kw):
    """Run the worker to completion with the camera forced absent."""
    import gui
    real = gui.webcam.resolve_camera

    def _no_camera(*a, **k):
        raise RuntimeError('no camera in tests')
    gui.webcam.resolve_camera = _no_camera
    try:
        opts = dict(cam_exp=6, cam_gain=60, diam_mm=16.0, autoproc=False,
                    tel_on=True, tel_hz=2.0)
        opts.update(kw)
        app._sldea_worker(p, tmp, 'RUN', 1, 2, 3, opts.pop('dry', True),
                          **opts)
    finally:
        gui.webcam.resolve_camera = real
    return _os.path.join(tmp, 'RUN')


def test_worker_writes_the_sidecar_without_touching_data_csv():
    with _tempfile.TemporaryDirectory() as tmp:
        p = _short_profile()
        # I_Out 0.05 V = 10 uA; V_Out 0.5 V = 0.5 kV (channels 2=V, 3=I)
        app = _StubApp(_FakeScope({2: [0.5], 3: [0.05]}))
        rundir = _drive(app, p, tmp)
        tel_path = _os.path.join(rundir, TELEMETRY_FILENAME)
        assert _os.path.exists(tel_path), _os.listdir(rundir)
        rows = _read(tel_path)
        assert rows and list(rows[0].keys()) == TELEMETRY_COLUMNS

        # data.csv keeps its own schema and exactly one row per snapshot
        with open(_os.path.join(rundir, 'data.csv'), newline='') as f:
            data = list(_csv.DictReader(f))
        assert len(data) == len(p.snapshots), (len(data), len(p.snapshots))
        assert list(data[0].keys()) == p.CSV_COLUMNS
        assert 'telemetry' not in ' '.join(p.CSV_COLUMNS)

        periodic = [r for r in rows if not r['event']]
        events = [r for r in rows if r['event']]
        assert len(periodic) >= 2, rows
        # ~2 Hz over a ~1.6 s profile, and every row carries the commanded
        # voltage even when V_Out was not sampled on that tick
        assert all(r['measured_uA'] == '10.0' for r in periodic), periodic
        assert all(r['nominal_kV'] != '' for r in rows)
        assert any(r['measured_kV'] == '0.5' for r in periodic)
        assert any(r['v_status'] == 'skipped' for r in periodic), \
            "kV must be sub-sampled, not read on every tick"
        # one event row per snapshot, naming the snapshot it belongs to
        assert len(events) == len(p.snapshots), events
        assert events[0]['event'].startswith('snap s00 warmup')
        assert any(e['event'].startswith('snap s00 baseline') for e in events)
        assert any('post-ramp' in r['event'] for r in events)
        # the achieved rate is reported, not assumed -- and a healthy run
        # at the default settings must NOT cry shortfall (the 10 Hz loop
        # quantises a 0.5 s gate to 0.5-0.6 s; a warning that fires every
        # time is a warning nobody reads)
        assert any(l.startswith('telemetry:') and 'Hz achieved' in l
                   for l in app.lines), app.lines
        assert not any('below its' in l for l in app.lines), app.lines
        assert not any('SLOW DISK' in l for l in app.lines), app.lines
        # provenance: setup.txt says the file exists and at what rate
        with open(_os.path.join(rundir, 'setup.txt')) as f:
            setup = f.read()
        assert '--- Telemetry ---' in setup and TELEMETRY_FILENAME in setup


def test_worker_telemetry_off_leaves_no_sidecar():
    with _tempfile.TemporaryDirectory() as tmp:
        app = _StubApp(_FakeScope({2: [0.5], 3: [0.05]}))
        rundir = _drive(app, _short_profile(), tmp, tel_on=False)
        assert not _os.path.exists(_os.path.join(rundir, TELEMETRY_FILENAME))
        assert _os.path.exists(_os.path.join(rundir, 'data.csv'))


def test_worker_records_the_trek_inverted_sign_like_data_csv():
    """Telemetry must be directly comparable to data.csv, which applies
    the Trek polarity to BOTH monitors (D5 2026-08-04)."""
    with _tempfile.TemporaryDirectory() as tmp:
        app = _StubApp(_FakeScope({2: [0.5], 3: [0.05]}))
        rundir = _drive(app, _short_profile(), tmp, trek_sign=-1.0)
        rows = _read(_os.path.join(rundir, TELEMETRY_FILENAME))
        assert all(r['measured_uA'] == '-10.0' for r in rows
                   if r['measured_uA']), rows
        assert all(float(r['measured_kV']) == -0.5 for r in rows
                   if r['measured_kV'])


def test_worker_never_claims_a_channel_was_read_when_its_cell_is_blank():
    """Half-dead link: the scope answers V_Out and times out on I_Out.
    The two reads are separate lock acquisitions, so the kV that DID
    arrive must survive, and no row may say v_status=ok next to a blank
    measured_kV — that is the #159 ambiguity the column exists to end."""
    with _tempfile.TemporaryDirectory() as tmp:
        app = _StubApp(_FakeScope({2: [0.5]}, raise_on={3}))
        rundir = _drive(app, _short_profile(), tmp)
        rows = _read(_os.path.join(rundir, TELEMETRY_FILENAME))
        assert rows
        for r in rows:
            assert not (r['v_status'] == 'ok' and r['measured_kV'] == ''), r
            assert not (r['i_status'] == 'ok' and r['measured_uA'] == ''), r
        snaps = [r for r in rows if r['event']]
        assert snaps and all(r['measured_kV'] == '0.5' for r in snaps), snaps
        assert all(r['i_status'] == 'error' for r in snaps), snaps
        # and the good reading reaches data.csv too, not just the sidecar
        with open(_os.path.join(rundir, 'data.csv'), newline='') as f:
            data = list(_csv.DictReader(f))
        assert all(r['measured_kV'] == '0.5' for r in data), data


def test_worker_dates_a_breakdown_trip_in_the_telemetry_stream():
    """The point of the whole exercise: the 233451 staircase was invisible
    because nothing electrical was recorded between snapshots."""
    with _tempfile.TemporaryDirectory() as tmp:
        # 12 quiet baseline reads, then 0.6 V = 120 uA forever
        scope = _FakeScope({2: [0.5], 3: [0.0] * 12 + [0.6]})
        app = _StubApp(scope)
        rundir = _drive(app, _short_profile(landing_s=6.0), tmp,
                        dry=False, wd_on=True, wd_ua=100.0, wd_s=1.0)
        assert app._sldea_bd_tripped, app.lines
        rows = _read(_os.path.join(rundir, TELEMETRY_FILENAME))
        trips = [r for r in rows if r['event'] == 'BREAKDOWN CONFIRMED']
        assert len(trips) == 1, rows
        assert trips[0]['measured_uA'] == '120.0'
        assert float(trips[0]['t_s']) > 0
        # the trip row lands BEFORE the breakdown frame's own row, and the
        # frame row is the later, separate instant
        idx = rows.index(trips[0])
        assert any('breakdown' in r['event'] for r in rows[idx + 1:]), rows
        # and the periodic record shows the excursion that led to it
        over = [r for r in rows if r['measured_uA'] == '120.0']
        assert len(over) >= 3, rows


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
