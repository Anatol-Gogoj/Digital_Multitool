#!/usr/bin/env python3
"""The Continuous Logging tab (`#30`): cadence in s or Hz, live min / max.

Three layers, cheapest first:
  * continuous_log on its own: the s <-> Hz conversion, what the cadence
    box refuses, the lower bound, the sampling grid, and the live
    current / min / max bookkeeping. No Tk, no instruments.
  * gui.logging_loop on a stub app with fake instruments: what it writes
    to the CSVs and to LiveStats, and WHEN it reads (a fake clock), with
    no thread and no Tk.
  * the real app (skipped without a display): the tab under its new name,
    the unit switch, Start refusing a bad cadence, Start handing the worker
    seconds and a fresh LiveStats, and the table drawing what it is fed.

Run: .venv/bin/python tests/test_continuous_log.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import csv
import math
import shutil
import tempfile
import threading
import time

import continuous_log as cl


def _refused(text, unit):
    """The ValueError message parse_cadence gives `text`, or fail."""
    try:
        got = cl.parse_cadence(text, unit)
    except ValueError as e:
        return str(e)
    raise AssertionError(f"{text!r} {unit} was accepted as {got!r} s")


# --------------------------------------------------------------------------
# Cadence: conversion, validation, the lower bound
# --------------------------------------------------------------------------

def test_seconds_and_hz_convert_both_ways():
    assert cl.interval_to_hz(0.5) == 2.0
    assert cl.interval_to_hz(4) == 0.25
    assert cl.hz_to_interval(2) == 0.5
    assert cl.hz_to_interval(0.25) == 4.0
    for s in (0.001, 0.1, 1.0, 3.0, 60.0, 3600.0):
        assert math.isclose(cl.hz_to_interval(cl.interval_to_hz(s)), s,
                            rel_tol=1e-12), s
    # the box reads in its unit and always answers in SECONDS
    assert cl.parse_cadence('2', 'Hz') == 0.5
    assert cl.parse_cadence('0.5', 's') == 0.5
    assert cl.parse_cadence('10', 'Hz') == 0.1
    assert cl.parse_cadence(' 2 ', 'hz') == 0.5        # spelling-tolerant
    assert cl.parse_cadence('1e-1', 'seconds') == 0.1


def test_switching_the_unit_keeps_the_cadence():
    """0.5 s becomes 2 Hz, not 0.5 Hz; and back again to the same text."""
    assert cl.convert_text('0.5', 's', 'Hz') == '2'
    assert cl.convert_text('2', 'Hz', 's') == '0.5'
    third = cl.convert_text('3', 's', 'Hz')
    assert third == '0.333333', third
    assert cl.convert_text(third, 'Hz', 's') == '3'    # not always: below
    # same unit, or text that is not a cadence: left exactly as typed
    assert cl.convert_text('1.50', 's', 's') == '1.50'
    for text in ('', 'abc', '0', '-1', 'nan'):
        assert cl.convert_text(text, 's', 'Hz') == text, text


def test_a_unit_switch_moves_the_cadence_by_at_most_5_ppm():
    """`#389`: fmt_number's docstring promised that 6 significant digits
    make s -> Hz -> s an exact round trip. They do not: 7 s comes back as
    7.00001 s. Each switch rounds to 6 digits, which moves the cadence by
    at most half a unit in the 6th digit (5 ppm), and that bound is what
    the docstring now says."""
    hz = cl.convert_text('7', 's', 'Hz')
    assert hz == '0.142857', hz
    assert cl.convert_text(hz, 'Hz', 's') == '7.00001'
    assert math.isclose(cl.parse_cadence(hz, 'Hz'), 7.0, rel_tol=5e-6)
    # the bound, over cadences from 0.1 ms to 10000 s
    for k in range(-1000, 1001):
        text = cl.fmt_number(10 ** (k / 250))
        seconds = float(text)
        hz = cl.convert_text(text, 's', 'Hz')
        # Start reads the Hz box: one rounding away from the typed cadence
        assert math.isclose(cl.parse_cadence(hz, 'Hz'), seconds,
                            rel_tol=5e-6), (text, hz)
        # switching back rounds once more
        back = float(cl.convert_text(hz, 'Hz', 's'))
        assert math.isclose(back, seconds, rel_tol=1e-5), (text, hz, back)


def test_the_box_refuses_empty_non_numeric_zero_negative_and_non_finite():
    for unit, word in (('s', 'seconds'), ('Hz', 'Hz')):
        assert 'Enter' in _refused('', unit) and word in _refused('', unit)
        assert 'Enter' in _refused('   ', unit)
        msg = _refused('abc', unit)
        assert "'abc' is not a number" in msg and word in msg, msg
        msg = _refused('1,5', unit)                   # a decimal comma
        assert 'is not a number' in msg, msg
        for text in ('0', '0.0', '-0', '-1', '-0.5'):
            msg = _refused(text, unit)
            assert 'greater than 0' in msg, (text, msg)
        for text in ('nan', 'inf', '-inf', '1e999'):
            msg = _refused(text, unit)
            assert 'finite' in msg or 'greater than 0' in msg, (text, msg)
    # the message names the unit it read the number in
    assert _refused('0', 'Hz').startswith('0 Hz:')
    assert _refused('-2', 's').startswith('-2 s:')
    try:
        cl.parse_cadence('1', 'kHz')
    except ValueError as e:
        assert 'unit' in str(e)
    else:
        raise AssertionError("an unknown unit was accepted")


def test_the_lower_bound_is_mains_and_hz_cannot_get_under_it():
    """main refused only interval <= 0 (start_logging since 3118026); #30
    keeps exactly that bound, adds none and lowers none. The Hz box goes
    through the same check after conversion, so a rate cannot reach an
    interval the seconds box would refuse."""
    assert cl.MIN_INTERVAL_EXCLUSIVE_S == 0.0
    for bad in (0, 0.0, -0.0, -1e-9, -5):
        try:
            cl.check_interval(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad!r} s passed the lower bound")
    tiny = 5e-324                                 # smallest positive float
    assert cl.check_interval(tiny) == tiny        # as main: > 0 is enough
    assert cl.parse_cadence('1e-6', 's') == 1e-6
    # a rate whose interval would be 0 or not finite is refused...
    assert 'greater than 0 Hz' in _refused('1e-400', 'Hz')   # rate == 0.0
    assert 'finite' in _refused('1e400', 'Hz')               # rate == inf
    # ...and a huge but finite rate lands on a positive interval, like
    # typing that interval in seconds would
    assert cl.parse_cadence('1e300', 'Hz') == 1e-300
    for bad in (True, None, 'x', float('nan')):
        try:
            cl.check_interval(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad!r} passed check_interval")


def test_old_seconds_text_still_means_what_it_meant():
    """Nothing about this tab was ever saved (no config key, no preset, no
    bench-profile entry), so the compatibility that matters is the box:
    a bare number read with no unit is seconds, exactly as before #30, and
    the tab still opens on 1.0 s."""
    assert cl.DEFAULT_INTERVAL_S == 1.0
    for text in ('1.0', '0.1', ' 2 ', '1e-3', '60', '0.25'):
        assert cl.parse_cadence(text) == float(text), text
        assert cl.parse_cadence(text, 's') == float(text), text


def test_the_hint_shows_the_other_unit_and_never_raises():
    assert cl.echo_text('0.5', 's') == '= 2 Hz'
    assert cl.echo_text('4', 'Hz') == '= every 0.25 s'
    assert cl.echo_text('', 's') == ''
    assert cl.echo_text('abc', 'Hz') == 'not a valid cadence'
    assert cl.echo_text('0', 's') == 'not a valid cadence'
    assert cl.echo_text('1', 'parsecs') == 'not a valid cadence'
    assert cl.echo_text('1e-320', 's') == 'too fast to express in Hz'
    assert cl.describe_cadence(0.5) == 'every 0.5 s (2 Hz)'
    assert cl.describe_cadence(1.0) == 'every 1 s (1 Hz)'
    assert cl.describe_cadence(1e-320).endswith('(too fast to express in Hz)')


# --------------------------------------------------------------------------
# The sampling grid
# --------------------------------------------------------------------------

def test_ticks_sit_on_the_grid_and_never_catch_up_in_a_burst():
    # on time: the next slot
    assert cl.next_tick(10.0, 1.0, 0, 10.4) == (1, 11.0, 0)
    assert cl.next_tick(10.0, 1.0, 5, 15.9) == (6, 16.0, 0)
    # finished exactly on the next slot: go now, nothing skipped
    assert cl.next_tick(10.0, 1.0, 0, 11.0) == (1, 11.0, 0)
    # overran slots 1 and 2: they are skipped, the next tick is slot 3
    assert cl.next_tick(10.0, 1.0, 0, 12.5) == (3, 13.0, 2)
    # the property: whatever the overrun, the next start is never in the
    # past (no back-to-back catch-up reads) and is always a grid slot
    for interval in (0.1, 0.5, 1.0, 7.0):
        for ran in (0.0, 0.01, 0.99, 1.0, 1.01, 2.5, 13.3):
            now = 100.0 + ran * interval
            slot, due, skipped = cl.next_tick(100.0, interval, 0, now)
            assert due >= now - 1e-9, (interval, ran, due, now)
            assert slot >= 1 and skipped == slot - 1, (slot, skipped)
            assert math.isclose(due, 100.0 + slot * interval,
                                rel_tol=0, abs_tol=1e-9), (due, slot)
            assert due - now <= interval + 1e-9, "idled past a free slot"


def test_an_interval_too_short_for_the_grid_starts_now():
    assert cl.next_tick(0.0, 1e-320, 0, 5.0) == (1, 5.0, 0)
    slot, due, skipped = cl.next_tick(0.0, 1e-300, 7, 5.0)
    assert (slot, due, skipped) == (8, 5.0, 0)


# --------------------------------------------------------------------------
# Live current / min / max
# --------------------------------------------------------------------------

def _row(stats, source, quantity):
    rows, _t, _s = stats.snapshot()
    hits = [r for r in rows if (r['source'], r['quantity']) == (source,
                                                                quantity)]
    assert len(hits) == 1, (source, quantity, rows)
    return hits[0]


def test_min_and_max_accumulate_and_bad_reads_never_poison_them():
    st = cl.LiveStats(1.0)
    for v in (2.0, None, 5.0, float('nan'), -1.0, float('inf'), True,
              'garbage', '3.5', 4.0):
        st.record('DMM', [('DC Voltage', v, 'V')])
    r = _row(st, 'DMM', 'DC Voltage')
    assert (r['min'], r['max'], r['current']) == (-1.0, 5.0, 4.0), r
    assert r['good'] == 5 and r['missed'] == 5, r   # '3.5' parses; True not
    # a None read shows as no current value, min/max untouched
    st.record('DMM', [('DC Voltage', None, 'V')])
    r = _row(st, 'DMM', 'DC Voltage')
    assert r['current'] is None and (r['min'], r['max']) == (-1.0, 5.0)
    # a read that RAISED: same, for every row of that source only
    st.record('PSU', [('Meas V', 12.0, 'V'), ('Meas A', 0.3, 'A')])
    st.record_failure('PSU')
    for q, v in (('Meas V', 12.0), ('Meas A', 0.3)):
        r = _row(st, 'PSU', q)
        assert r['current'] is None and r['missed'] == 1, r
        assert (r['min'], r['max']) == (v, v), r
    st.record('PSU', [('Meas V', 11.0, 'V'), ('Meas A', 0.4, 'A')])
    r = _row(st, 'PSU', 'Meas V')
    assert (r['current'], r['min'], r['max']) == (11.0, 11.0, 12.0), r
    assert _row(st, 'DMM', 'DC Voltage')['min'] == -1.0   # untouched
    # a row that has only ever failed has no min or max at all
    st.record('Scope CH1', [('RMS', None, 'V')])
    r = _row(st, 'Scope CH1', 'RMS')
    assert (r['current'], r['min'], r['max']) == (None, None, None)
    assert cl.fmt_value(None, 'V') == '--'


def test_an_overload_code_never_becomes_a_min_or_a_max():
    """`#389`: as_number took anything float() parses, so a DMM that
    answers an overload with a bare 9.9E37 would have set Max to it for
    the rest of the run. SCPI's no-number codes (+-9.9E37, 9.91E37) and
    anything larger now come back None, like the scope's do in its
    driver; ordinary large readings are still numbers."""
    for code in (9.9e37, -9.9e37, 9.91e37, '9.9E37', '+9.90000000E+37',
                 '-9.9E+37', 1e300):
        assert cl.as_number(code) is None, code
    for value in (1.2e9, -4.5e8, 3.3e-12, 0.0):
        assert cl.as_number(value) == value, value
    st = cl.LiveStats(1.0)
    for v in (2.0, 9.9e37, 5.0, -9.9e37, 9.91e37, 3.0):
        st.record('DMM', [('DC Voltage', v, 'V')])
    r = _row(st, 'DMM', 'DC Voltage')
    assert (r['current'], r['min'], r['max']) == (3.0, 2.0, 5.0), r
    assert r['good'] == 3 and r['missed'] == 3, r
    st.record('DMM', [('DC Voltage', 9.9e37, 'V')])
    assert _row(st, 'DMM', 'DC Voltage')['current'] is None
    # the supply's power is V * I: a code times a current is no reading
    # either, though at 2.97e37 it is under the code itself
    reading = {'set_voltage_v': 12.0, 'meas_voltage_v': 9.9e37,
               'meas_current_a': 0.3, 'power_w': 9.9e37 * 0.3}
    assert cl.psu_quantities(reading)[3] == ('Power', None, 'W')
    # the current is the other factor: at 0 V a current code makes 0 W
    off = {'set_voltage_v': 0.0, 'meas_voltage_v': 0.0,
           'meas_current_a': 9.9e37, 'power_w': 0.0 * 9.9e37}
    assert off['power_w'] == 0.0
    assert cl.psu_quantities(off)[3] == ('Power', None, 'W')
    st.record('DC Supply CH1', cl.psu_quantities(reading))
    st.record('DC Supply CH1', cl.psu_quantities(
        {'set_voltage_v': 12.0, 'meas_voltage_v': 11.9,
         'meas_current_a': 0.3, 'power_w': 3.57}))
    for q, top in (('Meas V', 11.9), ('Meas A', 0.3), ('Power', 3.57)):
        r = _row(st, 'DC Supply CH1', q)
        assert r['max'] == top, r
    assert _row(st, 'DC Supply CH1', 'Power')['missed'] == 1


def test_a_source_that_fails_from_its_first_read_still_gets_a_row():
    """`#389`: record_failure marked only rows that already existed, so a
    source whose first read raised was missing from the table and its
    failure showed only in Log Status. It now gets one '(read failed)'
    stand-in row until its first good read replaces it."""
    assert cl.READ_FAILED == '(read failed)'
    st = cl.LiveStats(1.0)
    st.record('LCR', cl.lcr_quantities('CPD', 1e3, 3.3e-9, 0.002, 0))
    st.record_failure('DMM')
    st.record_failure('DMM')
    rows, _t, _s = st.snapshot()
    assert [(r['source'], r['quantity']) for r in rows] == [
        ('LCR', 'Test frequency'), ('LCR', 'Cp'), ('LCR', 'D'),
        ('DMM', '(read failed)')], rows
    r = _row(st, 'DMM', '(read failed)')
    assert (r['current'], r['min'], r['max']) == (None, None, None), r
    assert (r['good'], r['missed']) == (0, 2), r
    # the first good read replaces the stand-in; its misses carry over
    st.record('DMM', cl.dmm_quantities('DC Voltage', 0.5, 'V'))
    rows, _t, _s = st.snapshot()
    assert [r['quantity'] for r in rows if r['source'] == 'DMM'] == [
        'DC Voltage'], rows
    r = _row(st, 'DMM', 'DC Voltage')
    assert (r['current'], r['min'], r['max']) == (0.5, 0.5, 0.5), r
    assert (r['good'], r['missed']) == (1, 2), r
    # a source that has rows: a failure marks them, and no stand-in
    st.record_failure('DMM')
    rows, _t, _s = st.snapshot()
    assert [r['quantity'] for r in rows if r['source'] == 'DMM'] == [
        'DC Voltage'], rows
    assert _row(st, 'DMM', 'DC Voltage')['missed'] == 3
    # every row a stand-in turns into starts with its misses
    st.record_failure('DC Supply CH1')
    st.record('DC Supply CH1', cl.psu_quantities(
        {'set_voltage_v': 12.0, 'meas_voltage_v': 11.9,
         'meas_current_a': 0.3, 'power_w': 3.57}))
    for q in ('Set V', 'Meas V', 'Meas A', 'Power'):
        r = _row(st, 'DC Supply CH1', q)
        assert (r['good'], r['missed']) == (1, 1), r
    # the other source never noticed
    assert _row(st, 'LCR', 'Cp')['current'] == 3.3e-9


def test_a_read_with_no_numbers_keeps_the_stand_in():
    """A read that raises nothing but yields no rows (a BSWV reply with no
    numeric keys gives sg_quantities nothing) has nothing to show, so the
    '(read failed)' stand-in stays, with its misses, until a read yields
    rows. Review of `#389`: the stand-in used to go on any read that did
    not raise, taking the source out of the table."""
    st = cl.LiveStats(1.0)
    st.record_failure('SigGen CH1')
    st.record_failure('SigGen CH1')
    empty = cl.sg_quantities({'WVTP': 'SINE'})
    assert empty == [], empty
    st.record('SigGen CH1', empty)
    r = _row(st, 'SigGen CH1', '(read failed)')
    assert (r['current'], r['good'], r['missed']) == (None, 0, 2), r
    st.record('SigGen CH1', cl.sg_quantities({'WVTP': 'SINE', 'FRQ': 100.0}))
    rows, _t, _s = st.snapshot()
    assert [(r['quantity'], r['current'], r['good'], r['missed'])
            for r in rows] == [('Frequency', 100.0, 1, 2)], rows


def test_start_is_the_reset():
    """start_logging makes a NEW LiveStats per run (asserted against the
    real app below); a new one holds nothing of the old."""
    old = cl.LiveStats(1.0)
    old.record('DMM', [('DC Voltage', 9.0, 'V')])
    old.tick(2)
    new = cl.LiveStats(0.5)
    assert new.snapshot() == ([], 0, 0)
    assert new.interval_s == 0.5
    old.record('DMM', [('DC Voltage', -9.0, 'V')])   # a late old worker
    assert new.snapshot() == ([], 0, 0)


def test_a_unit_change_starts_a_new_row_and_old_rows_go_quiet():
    st = cl.LiveStats()
    st.record('LCR', cl.lcr_quantities('CPD', 1000.0, 3.3e-9, 0.001, 0))
    st.record('LCR', cl.lcr_quantities('LSRS', 1000.0, 1e-3, 2.0, 0))
    rows, _t, _s = st.snapshot()
    keys = [(r['quantity'], r['unit']) for r in rows]
    assert keys == [('Test frequency', 'Hz'), ('Cp', 'F'), ('D', ''),
                    ('Ls', 'H'), ('Rs', 'Ω')], keys
    cp = _row(st, 'LCR', 'Cp')
    assert cp['current'] is None and cp['max'] == 3.3e-9, cp
    assert _row(st, 'LCR', 'Ls')['current'] == 1e-3


def test_source_rows_mirror_the_csv_columns():
    # LCR: a nonzero status is the meter's own "not a good reading"
    good = cl.lcr_quantities('cpd', 1e3, 3.3e-9, 0.002, 0)
    assert good == [('Test frequency', 1e3, 'Hz'), ('Cp', 3.3e-9, 'F'),
                    ('D', 0.002, '')], good
    bad = cl.lcr_quantities('CPD', 1e3, 9.9e37, 9.9e37, 1)
    assert [v for _q, v, _u in bad] == [1e3, None, None], bad
    assert cl.lcr_quantities(None, None, 1.0, 2.0, 0)[1:] == [
        ('Primary', 1.0, ''), ('Secondary', 2.0, '')]
    assert [q for q, _v, _u in cl.lcr_quantities('RX', 1, 1, 1, 0)] == [
        'Test frequency', 'R', 'X']
    assert [q for q, _v, _u in cl.lcr_quantities('ZTD', 1, 1, 1, 0)] == [
        'Test frequency', 'Z', 'θ']
    # scope: all six, a missing one is a miss
    rows = cl.scope_quantities({'freq': 1e3, 'pk2pk': None})
    assert [q for q, _v, _u in rows] == ['Frequency', 'Period', 'Mean',
                                         'Pk-Pk', 'RMS', 'Amplitude']
    assert rows[0] == ('Frequency', 1e3, 'Hz') and rows[3][1] is None
    # sig gen: only what the waveform has
    rows = cl.sg_quantities({'WVTP': 'SINE', 'FRQ': 100.0, 'AMP': 2.0,
                             'OFST': 0.0})
    assert rows == [('Frequency', 100.0, 'Hz'), ('Amplitude', 2.0, 'Vpp'),
                    ('Offset', 0.0, 'V')], rows
    rows = cl.psu_quantities({'set_voltage_v': 12, 'meas_voltage_v': 11.9,
                              'meas_current_a': 0.3, 'power_w': 3.57})
    assert [q for q, _v, _u in rows] == ['Set V', 'Meas V', 'Meas A',
                                         'Power']
    assert rows[3] == ('Power', 3.57, 'W'), rows
    assert cl.dmm_quantities('DC Voltage', 0.1, 'V') == [
        ('DC Voltage', 0.1, 'V')]


def test_the_summary_line_counts_samples_and_skipped_slots():
    assert cl.summary_line(0, 0, 1.0, True) == (
        'Running: waiting for the first sample...')
    assert cl.summary_line(1, 0, 1.0, True) == (
        'Running: 1 sample, every 1 s (1 Hz)')
    line = cl.summary_line(12, 3, 0.5, False)
    assert line.startswith('Stopped: 12 samples, every 0.5 s (2 Hz); 3 '
                           'slots skipped'), line
    assert cl.summary_line(0, 0, None, False) == 'Stopped: 0 samples'


def test_the_skipped_count_stays_readable_at_an_absurd_cadence():
    """`#389`: main's > 0 bound accepts 1e-12 s, and there 50 ms of reads
    skip about 5e10 slots a tick. The line shows the count exactly up to
    a million and "over 1,000,000" beyond. Only the text is capped: the
    count, the grid and what the box accepts stay as they were."""
    assert cl.parse_cadence('1e-12', 's') == 1e-12       # still accepted
    slot, due, skipped = cl.next_tick(0.0, 1e-12, 0, 0.05)
    assert skipped > 4e10 and math.isclose(due, 0.05, abs_tol=1e-9), (
        slot, due, skipped)
    st = cl.LiveStats(1e-12)
    st.tick(skipped)
    _rows, ticks, total = st.snapshot()
    assert total == skipped                    # the count is not capped
    assert cl.summary_line(ticks, total, 1e-12, True) == (
        'Running: 1 sample, every 1e-12 s (1e+12 Hz); over 1,000,000 '
        'slots skipped (reads took longer than the cadence)')
    head = 'Stopped: 5 samples, every 1 s (1 Hz); '
    tail = ' skipped (reads took longer than the cadence)'
    for n, words in ((1, '1 slot'), (12345, '12,345 slots'),
                     (cl.SKIPPED_SHOWN_MAX, '1,000,000 slots'),
                     (cl.SKIPPED_SHOWN_MAX + 1, 'over 1,000,000 slots'),
                     (10 ** 15, 'over 1,000,000 slots')):
        line = cl.summary_line(5, n, 1.0, False)
        assert line == head + words + tail, (n, line)


def test_live_stats_survive_a_writer_and_a_reader_at_once():
    """The worker writes while the Tk thread snapshots, and a run adds
    rows as it goes (a source's first good read, an LCR mode change), so
    the writer adds a new row on every read. `#389`: with one fixed row
    this test passed with LiveStats' lock replaced by a no-op. The switch
    interval is cut from the default 5 ms to 1 us so the threads trade
    the GIL far more often; without the lock the reader's snapshot meets
    "dictionary changed size during iteration" (or a row with a min and
    no max yet) within milliseconds: 1000 of 1000 runs failed on Windows
    and on WSL Debian, Python 3.13, 2026-10-06. With the lock the race
    runs its 0.2 s."""
    st = cl.LiveStats(0.01)
    stop = threading.Event()
    errors, wrote = [], []

    def writer():
        i = 0
        try:
            while not stop.is_set():
                st.record('DMM', [(f'Q{i}', float(i), 'V')])
                st.tick()
                i += 1
        except Exception as e:             # reported by the reader below
            errors.append(e)
        wrote.append(i)

    saved = _sys.getswitchinterval()
    t = None
    try:
        # inside the try, so a writer that fails to start still gets the
        # switch interval put back
        _sys.setswitchinterval(1e-6)
        t = threading.Thread(target=writer, daemon=True)
        t.start()
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            rows, _ticks, _s = st.snapshot()
            for r in rows:
                if r['min'] is not None:
                    assert r['max'] is not None and r['min'] <= r['max'], r
    finally:
        stop.set()
        if t is not None and t.is_alive():
            t.join(5)
        _sys.setswitchinterval(saved)
    assert not errors and wrote, (errors, wrote)
    # nothing the writer did was lost or garbled
    rows, ticks, _s = st.snapshot()
    assert ticks == wrote[0], (ticks, wrote)
    assert [(r['quantity'], r['min'], r['max']) for r in rows] == [
        (f'Q{i}', float(i), float(i)) for i in range(wrote[0])]


# --------------------------------------------------------------------------
# gui.logging_loop on a stub app (no Tk, no thread)
# --------------------------------------------------------------------------

class _Root:
    def after(self, _ms, fn=None, *args):
        return 'after#'


class _LoopApp:
    """Just enough app for logging_loop: the real loop, fake sources."""

    def __init__(self):
        import gui
        self.logging_loop = gui.InstrumentControlGUI.logging_loop.__get__(
            self)
        self._LOG_MAX_FAILS = gui.InstrumentControlGUI._LOG_MAX_FAILS
        self.recording = True
        self._log_gen = None
        self.lcr = self.scope = self.sg = self.psu = self.dmm = None
        self.psu_lock = threading.Lock()
        self.root = _Root()
        self.lines = []

    def log_message(self, message):
        self.lines.append(message)

    def _logging_failed(self):
        self.recording = False


class _FakeDMM:
    """Scripted readings; an Exception in the script is raised. The last
    scripted read ends the run. `clock`/`read_s`: a read takes that long."""

    def __init__(self, app, script, clock=None, read_s=0.0):
        self.app, self.script = app, list(script)
        self.clock, self.read_s = clock, read_s
        self.starts = []

    def measure(self, function):
        if self.clock is not None:
            self.starts.append(self.clock.t)
            self.clock.t += self.read_s
        v = self.script.pop(0)
        if not self.script:
            self.app.recording = False
        if isinstance(v, Exception):
            raise v
        return v

    def unit(self, function):
        return 'V'


class _FakePSU:
    def __init__(self):
        self.n = 0

    def read_channel(self, ch):
        self.n += 1
        if self.n == 2:
            raise IOError('serial timeout')
        v, a = 12.0 - 0.01 * self.n, 0.3
        return {'channel': ch, 'set_voltage_v': 12.0, 'meas_voltage_v': v,
                'meas_current_a': a, 'power_w': v * a}


def _cfg(tmp, stats, psu=False, dmm=True):
    return {'dir': tmp, 'lcr': False,
            'scope': {ch: False for ch in range(1, 5)},
            'sg': {1: False, 2: False}, 'psu': {1: psu, 2: False},
            'dmm': dmm, 'dmm_fn': 'DC Voltage', 'stats': stats}


def test_the_loop_feeds_min_max_and_leaves_the_csvs_as_they_were():
    tmp = tempfile.mkdtemp(prefix='contlog_')
    try:
        app = _LoopApp()
        app.dmm = _FakeDMM(app, [1.5, None, IOError('socket closed'), 3.0,
                                 0.5, 2.0])
        app.psu = _FakePSU()
        stats = cl.LiveStats(0.001)
        app._log_gen = tok = object()
        app.logging_loop(0.001, _cfg(tmp, stats, psu=True), tok)

        r = _row(stats, 'DMM', 'DC Voltage')
        assert (r['current'], r['min'], r['max']) == (2.0, 0.5, 3.0), r
        assert r['good'] == 4 and r['missed'] == 2, r   # None + the raise
        v = _row(stats, 'DC Supply CH1', 'Meas V')
        assert v['good'] == 5 and v['missed'] == 1, v   # read 2 raised
        assert math.isclose(v['max'], 11.99) and math.isclose(v['min'],
                                                               11.94), v
        rows, ticks, skipped = stats.snapshot()
        assert ticks == 6, ticks
        assert any('DMM error: socket closed' in m for m in app.lines)

        files = sorted(_os.listdir(tmp))
        dmm = [f for f in files if f.startswith('dmm_')]
        psu = [f for f in files if f.startswith('psu_ch1_')]
        assert len(dmm) == 1 and len(psu) == 1, files
        with open(_os.path.join(tmp, dmm[0]), newline='') as fh:
            data = list(csv.reader(fh))
        assert data[0] == ['Timestamp', 'Function', 'Value', 'Unit']
        # the raised read writes no row; the None read writes a blank value
        assert [row[2] for row in data[1:]] == ['1.5', '', '3.0', '0.5',
                                                '2.0'], data
        assert all(row[1] == 'DC Voltage' and row[3] == 'V'
                   for row in data[1:])
        with open(_os.path.join(tmp, psu[0]), newline='') as fh:
            data = list(csv.reader(fh))
        assert data[0] == ['Timestamp', 'Set V', 'Meas V', 'Meas A',
                           'Power (W)']
        assert len(data) == 1 + 5, data
    finally:
        shutil.rmtree(tmp)


def _dmm_csv_values(tmp):
    files = [f for f in _os.listdir(tmp) if f.startswith('dmm_')]
    assert len(files) == 1, files
    with open(_os.path.join(tmp, files[0]), newline='') as fh:
        return [row[2] for row in list(csv.reader(fh))[1:]]


def test_the_loop_keeps_an_overload_code_in_the_csv_but_not_in_max():
    """`#389`: a bare 9.9E37 from the DMM stays in the CSV exactly as the
    meter answered it (the CSV is the raw record, and the code is plain to
    see there), while the live table shows -- and keeps it out of min and
    max."""
    tmp = tempfile.mkdtemp(prefix='contlog_')
    try:
        app = _LoopApp()
        app.dmm = _FakeDMM(app, [1.5, 9.9e37, 2.0])
        stats = cl.LiveStats(0.001)
        app._log_gen = tok = object()
        app.logging_loop(0.001, _cfg(tmp, stats), tok)
        r = _row(stats, 'DMM', 'DC Voltage')
        assert (r['current'], r['min'], r['max']) == (2.0, 1.5, 2.0), r
        assert (r['good'], r['missed']) == (2, 1), r
        assert _dmm_csv_values(tmp) == ['1.5', '9.9e+37', '2.0']
    finally:
        shutil.rmtree(tmp)


def test_the_loop_shows_a_source_whose_first_read_fails():
    """`#389`: the DMM's first read raises. The table gets a '(read
    failed)' row for it at once (the error is in Log Status as before),
    and its first good read takes that row's place."""
    for script, want in (
            ([IOError('socket closed')],
             [('(read failed)', None, 0, 1)]),
            ([IOError('socket closed'), 0.25],
             [('DC Voltage', 0.25, 1, 1)])):
        tmp = tempfile.mkdtemp(prefix='contlog_')
        try:
            app = _LoopApp()
            app.dmm = _FakeDMM(app, script)
            stats = cl.LiveStats(0.001)
            app._log_gen = tok = object()
            app.logging_loop(0.001, _cfg(tmp, stats), tok)
            rows, ticks, _s = stats.snapshot()
            got = [(r['quantity'], r['current'], r['good'], r['missed'])
                   for r in rows if r['source'] == 'DMM']
            assert got == want, (script, got)
            assert ticks == len(script), ticks
            assert any('DMM error: socket closed' in m for m in app.lines)
            # the raised read wrote no CSV row, as before
            assert _dmm_csv_values(tmp) == [
                str(v) for v in script if not isinstance(v, Exception)]
        finally:
            shutil.rmtree(tmp)


class _FakeLCR:
    def __init__(self):
        self.reads = [(3.3e-9, 0.002, 0), (9.9e37, 9.9e37, 1),
                      (3.1e-9, 0.003, 0)]

    def get_config(self):
        return {'mode': 'CPD', 'frequency': 1000.0, 'voltage': 1.0}

    def measure(self):
        return self.reads.pop(0)


class _FakeScope:
    def __init__(self):
        self.n = 0

    def get_all_measurements(self, channel):
        self.n += 1
        return {'freq': 1000.0 + self.n, 'period': 1e-3, 'mean': 0.0,
                'pk2pk': 2.0 * self.n, 'rms': None, 'amplitude': 1.0}


class _FakeSG:
    def __init__(self):
        self.n = 0

    def get_basic_wave_dict(self, channel):
        self.n += 1
        return {'WVTP': 'SINE', 'FRQ': 100.0 * self.n, 'AMP': 2.0,
                'OFST': -0.5 * self.n}

    def get_output_dict(self, channel):
        return {'state': True, 'load': 'HZ', 'polarity': 'NOR'}


def test_every_source_reaches_the_live_table():
    """The LCR, scope, sig-gen, supply and DMM rows are each wired in."""
    tmp = tempfile.mkdtemp(prefix='contlog_')
    try:
        app = _LoopApp()
        app.lcr, app.scope, app.sg = _FakeLCR(), _FakeScope(), _FakeSG()
        app.psu = _FakePSU()
        app.dmm = _FakeDMM(app, [0.1, 0.3, 0.2])
        stats = cl.LiveStats(0.001)
        cfg = _cfg(tmp, stats, psu=True)
        cfg['lcr'] = True
        cfg['scope'][1] = True
        cfg['sg'][1] = True
        app._log_gen = tok = object()
        app.logging_loop(0.001, cfg, tok)

        cp = _row(stats, 'LCR', 'Cp')
        assert (cp['current'], cp['min'], cp['max']) == (3.1e-9, 3.1e-9,
                                                         3.3e-9), cp
        assert cp['missed'] == 1, cp            # the status-1 read
        assert _row(stats, 'LCR', 'D')['max'] == 0.003
        assert _row(stats, 'LCR', 'Test frequency')['current'] == 1000.0
        pk = _row(stats, 'Scope CH1', 'Pk-Pk')
        assert (pk['min'], pk['max']) == (2.0, 6.0), pk
        rms = _row(stats, 'Scope CH1', 'RMS')
        assert rms['missed'] == 3 and rms['max'] is None, rms
        off = _row(stats, 'SigGen CH1', 'Offset')
        assert (off['min'], off['max']) == (-1.5, -0.5), off
        rows, ticks, _s = stats.snapshot()
        assert not [r for r in rows if r['source'] == 'SigGen CH1'
                    and r['quantity'] in ('Stdev', 'Mean')], rows
        assert _row(stats, 'DC Supply CH1', 'Power')['good'] == 2
        dmm = _row(stats, 'DMM', 'DC Voltage')
        assert (dmm['min'], dmm['max']) == (0.1, 0.3), dmm
        assert ticks == 3, ticks
    finally:
        shutil.rmtree(tmp)


class _Clock:
    """Stands in for gui.time inside logging_loop."""

    def __init__(self, t=100.0):
        self.t = t

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _run_on_clock(interval, read_s, n):
    import gui
    tmp = tempfile.mkdtemp(prefix='contlog_')
    saved = gui.time
    clock = _Clock()
    gui.time = clock
    try:
        app = _LoopApp()
        app.dmm = _FakeDMM(app, [1.0] * n, clock=clock, read_s=read_s)
        stats = cl.LiveStats(interval)
        app._log_gen = tok = object()
        app.logging_loop(interval, _cfg(tmp, stats), tok)
        return app.dmm.starts, stats, app.lines
    finally:
        gui.time = saved
        shutil.rmtree(tmp)


def test_a_cadence_in_hz_is_kept_whatever_the_reads_cost():
    """2 Hz means a sample every 0.5 s. Before #30 the loop idled a whole
    interval AFTER the reads, so 0.2 s reads at "0.5 s" sampled every
    0.7 s (1.43 Hz)."""
    starts, stats, lines = _run_on_clock(cl.parse_cadence('2', 'Hz'), 0.2, 5)
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert all(math.isclose(g, 0.5, abs_tol=1e-9) for g in gaps), gaps
    assert stats.snapshot()[1:] == (5, 0)
    assert not any('skipped' in m for m in lines), lines


def test_reads_slower_than_the_cadence_skip_slots_instead_of_bursting():
    """1.5 s of reads at a 1 s cadence: every other slot is skipped, so
    samples land 2 s apart and the instruments get 0.5 s of rest after
    each read -- never a back-to-back catch-up read."""
    starts, stats, lines = _run_on_clock(1.0, 1.5, 3)
    assert [round(s - starts[0], 9) for s in starts] == [0.0, 2.0, 4.0], \
        starts
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert min(gaps) >= 1.0, gaps
    assert stats.snapshot()[1:] == (3, 3)
    notes = [m for m in lines if 'skipped, not made up' in m]
    assert len(notes) == 1, lines                   # said once, not per tick


# --------------------------------------------------------------------------
# The real app (needs a display)
# --------------------------------------------------------------------------

def _app():
    """(root, app) with every tab built, or (None, None) with no display."""
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return None, None
    import gui
    gui.InstrumentControlGUI.auto_connect = lambda self: None
    app = gui.InstrumentControlGUI(root)
    root.update_idletasks()
    return root, app


class _MB:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith('show') or name.startswith('ask'):
            def note(title, message, **kw):
                self.calls.append((name, title, message))
                return False
            return note
        raise AttributeError(name)


def test_the_tab_is_found_under_its_new_name_and_its_old_slug():
    """`#30`: the label is "Continuous Logging" now; the slug that the
    manual pipeline and content.json key off is still `logging`."""
    import json
    import gui
    entry = [t for t in gui.MANUAL_TABS if t[0] == 'logging']
    assert entry == [('logging', 'continuous logging',
                      'create_logging_tab')], entry
    here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    with open(_os.path.join(here, 'docs', 'manual-src', 'content.json'),
              encoding='utf-8') as fh:
        content = json.load(fh)
    assert content['logging']['area'] == 'Continuous Logging'
    root, app = _app()
    if root is None:
        return
    try:
        tab = app.tab_widget('logging')
        assert tab is not None, "the logging slug lost its tab"
        assert app.notebook.tab(tab, 'text') == 'Continuous Logging'
        labels = [app.notebook.tab(t, 'text') for t in app.notebook.tabs()]
        assert not any('Data Logging' in s for s in labels), labels
        assert app.select_manual_tab('logging')
        assert app.notebook.select() == str(tab)
    finally:
        root.destroy()


def test_the_unit_switch_converts_the_box_and_the_hint_follows():
    root, app = _app()
    if root is None:
        return
    try:
        assert app.log_interval.get() == '1.0'          # as before #30
        assert app.log_cadence_unit.get() == 's'
        assert app.log_cadence_echo.cget('text') == '= 1 Hz'
        app._set_entry(app.log_interval, '0.5')
        app._log_cadence_echo_update()
        assert app.log_cadence_echo.cget('text') == '= 2 Hz'
        app.log_cadence_unit.set('Hz')
        app._log_cadence_unit_changed()
        assert app.log_interval.get() == '2'
        assert app.log_cadence_echo.cget('text') == '= every 0.5 s'
        app.log_cadence_unit.set('s')
        app._log_cadence_unit_changed()
        assert app.log_interval.get() == '0.5'
        # mid-edit garbage is left alone by a unit switch
        app._set_entry(app.log_interval, '0.5x')
        app.log_cadence_unit.set('Hz')
        app._log_cadence_unit_changed()
        assert app.log_interval.get() == '0.5x'
        assert app.log_cadence_echo.cget('text') == 'not a valid cadence'
    finally:
        root.destroy()


def test_start_refuses_a_bad_cadence_with_a_message_and_starts_nothing():
    import gui
    root, app = _app()
    if root is None:
        return
    saved = gui.messagebox
    mb = gui.messagebox = _MB()
    try:
        for unit in ('s', 'Hz'):
            app.log_cadence_unit.set(unit)
            app._log_cadence_unit_was = unit
            for text in ('', 'abc', '0', '-1', 'nan', 'inf'):
                del mb.calls[:]
                app._set_entry(app.log_interval, text)
                app.start_logging()
                assert [c[:2] for c in mb.calls] == [
                    ('showerror', 'Logging')], (unit, text, mb.calls)
                assert mb.calls[0][2].startswith('Invalid sample cadence'), \
                    mb.calls[0][2]
                assert not app.recording, (unit, text)
                assert str(app.log_start_btn.cget('state')) == 'normal'
    finally:
        gui.messagebox = saved
        root.destroy()


def test_start_hands_the_worker_seconds_and_a_fresh_live_table():
    import gui
    root, app = _app()
    if root is None:
        return
    saved = gui.messagebox
    gui.messagebox = _MB()
    tmp = tempfile.mkdtemp(prefix='contlog_')
    runs = []
    try:
        # A stand-in worker: the real one needs instruments. Bound on the
        # instance, so start_logging's Thread(target=self._logging_worker)
        # picks it up.
        app._logging_worker = lambda interval, cfg, tok: runs.append(
            (interval, cfg))
        app.psu = object()                  # "connected"; never called
        app.log_lcr.set(False)
        for ch in range(1, 5):
            app.log_scope_channels[ch].set(False)
        app.log_psu_channels[1].set(True)
        app.log_dir.set(tmp)
        app._set_entry(app.log_interval, '4')
        app.log_cadence_unit.set('Hz')
        app._log_cadence_unit_was = 'Hz'
        app.start_logging()
        app.record_thread.join(5)
        assert runs and runs[0][0] == 0.25, runs        # 4 Hz -> 0.25 s
        first = runs[0][1]['stats']
        assert isinstance(first, cl.LiveStats) and first.interval_s == 0.25
        assert app._log_stats is first
        # the table shows what the run's LiveStats holds
        first.record('DC Supply CH1', cl.psu_quantities(
            {'set_voltage_v': 12.0, 'meas_voltage_v': 11.98,
             'meas_current_a': 0.25, 'power_w': 2.995}))
        first.record('DC Supply CH1', cl.psu_quantities(
            {'set_voltage_v': 12.0, 'meas_voltage_v': 11.96,
             'meas_current_a': 0.31, 'power_w': 3.7076}))
        first.tick()
        first.tick(2)
        app._log_live_render(first, running=False)
        tree = app.log_live_tree
        got = {tree.item(i, 'values')[1]: tree.item(i, 'values')
               for i in tree.get_children()}
        assert list(got) == ['Set V', 'Meas V', 'Meas A', 'Power'], got
        assert got['Meas A'][2:] == ('310 mA', '250 mA', '310 mA'), got
        assert got['Meas V'][2:] == ('11.96 V', '11.96 V', '11.98 V'), got
        summary = app.log_live_summary.cget('text')
        assert summary.startswith('Stopped: 2 samples, every 0.25 s (4 Hz)'
                                  '; 2 slots skipped'), summary
        # Stop, then Start again: a NEW LiveStats, and an empty table
        app.stop_logging()
        app._set_entry(app.log_interval, '2')
        app.log_cadence_unit.set('s')
        app._log_cadence_unit_was = 's'
        app.start_logging()
        app.record_thread.join(5)
        assert len(runs) == 2 and runs[1][0] == 2.0, runs
        second = runs[1][1]['stats']
        assert second is not first and second.snapshot() == ([], 0, 0)
        assert app._log_stats is second
        assert tree.get_children() == (), tree.get_children()
        # the old run's poll (if one is still pending) stops by itself
        app._log_live_poll(first, app.record_thread)
        assert tree.get_children() == ()
        app.stop_logging()
    finally:
        gui.messagebox = saved
        shutil.rmtree(tmp, ignore_errors=True)
        root.destroy()


def test_the_table_shows_a_failing_source_and_drops_its_stand_in():
    """`#389`: a source whose first read raised shows as '(read failed)';
    once it reads, that row leaves the table rather than sitting there
    stale beside the real ones."""
    root, app = _app()
    if root is None:
        return
    try:
        stats = cl.LiveStats(1.0)
        app._log_live_show(stats)
        tree = app.log_live_tree

        def shown():
            return [tree.item(i, 'values') for i in tree.get_children()]

        stats.record('DC Supply CH1', cl.psu_quantities(
            {'set_voltage_v': 12.0, 'meas_voltage_v': 11.98,
             'meas_current_a': 0.25, 'power_w': 2.995}))
        stats.record_failure('DMM')
        stats.tick()
        app._log_live_render(stats, running=True)
        assert shown()[-1] == ('DMM', '(read failed)', '--', '--', '--'), \
            shown()
        assert len(shown()) == 5, shown()
        stats.record('DMM', cl.dmm_quantities('DC Voltage', 0.5, 'V'))
        stats.tick()
        app._log_live_render(stats, running=True)
        assert [v[:2] for v in shown()] == [
            ('DC Supply CH1', 'Set V'), ('DC Supply CH1', 'Meas V'),
            ('DC Supply CH1', 'Meas A'), ('DC Supply CH1', 'Power'),
            ('DMM', 'DC Voltage')], shown()
        assert shown()[-1][2:] == ('500 mV', '500 mV', '500 mV'), shown()
        assert ('DMM', '(read failed)', '') not in app._log_live_items
        assert len(app._log_live_items) == 5
    finally:
        root.destroy()


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
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
