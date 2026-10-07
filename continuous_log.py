#!/usr/bin/env python3
"""Pure helpers for the Continuous Logging tab (no Tk, no VISA).

Issue #30 asked for three things on what was the "Data Logging" tab: a name
that says the logging is continuous, a cadence the user can type either as
seconds between samples or as samples per second (Hz), and a live min / max
beside each value while a run is going. This module is the bookkeeping half
of the last two, kept out of gui.py so it can be tested without a display
or an instrument:

  * parse_cadence / interval_to_hz / hz_to_interval -- the cadence entry.
    The cadence is stored in ONE unit, seconds between sample starts; Hz is
    only ever an input and a display.
  * next_tick -- when the logging loop takes its next sample. Samples sit on
    a fixed grid (start + k * interval), so "2 Hz" means two samples a
    second rather than "0.5 s of idle after however long the reads took".
  * LiveStats -- running current / min / max per logged quantity for one
    run, fed by the logging worker thread and read by the Tk main thread.
  * *_quantities -- one source's reading as (quantity, value, unit) rows,
    mirroring that source's CSV columns.

Headless self-test: .venv/bin/python tests/test_continuous_log.py
"""
import math
import threading

import lcr_format

# ---- Cadence ---------------------------------------------------------------
# The two units the cadence box accepts. The STORED unit is always seconds.
UNIT_S = 's'
UNIT_HZ = 'Hz'
CADENCE_UNITS = (UNIT_S, UNIT_HZ)

# The tab opens on this, exactly as it did before #30 ("1.0" seconds).
DEFAULT_INTERVAL_S = 1.0

# The lower bound on the interval is main's, unchanged: start_logging has
# refused only zero and negative intervals since 3118026 (issue #39), and
# #30 adds no floor of its own and lowers none. A cadence typed in Hz goes
# through the same check after conversion, so the Hz box cannot reach an
# interval the seconds box could not. The practical floor is the
# instruments' own round trips: sources are read one after another, and a
# tick whose reads overrun the interval makes next_tick skip slots rather
# than fire the missed ones back to back.
MIN_INTERVAL_EXCLUSIVE_S = 0.0

_EXAMPLE = {UNIT_S: '1.0', UNIT_HZ: '2'}
_WHAT = {UNIT_S: 'the interval in seconds', UNIT_HZ: 'the rate in Hz'}


def _norm_unit(unit):
    """'s' or 'Hz' from any reasonable spelling; ValueError otherwise."""
    text = str(unit).strip().lower()
    if text in ('s', 'sec', 'secs', 'second', 'seconds'):
        return UNIT_S
    if text in ('hz', 'hertz'):
        return UNIT_HZ
    raise ValueError(f"unknown cadence unit {unit!r} (use 's' or 'Hz')")


def check_interval(seconds):
    """`seconds` if it is a usable interval; ValueError with a message for
    the user otherwise. This is the lower bound (see
    MIN_INTERVAL_EXCLUSIVE_S): finite and greater than zero."""
    if isinstance(seconds, bool):
        raise ValueError("the interval must be a number of seconds")
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        raise ValueError("the interval must be a number of seconds")
    if not math.isfinite(seconds):
        raise ValueError("the interval must be a finite number of seconds")
    if seconds <= MIN_INTERVAL_EXCLUSIVE_S:
        raise ValueError("the interval must be greater than 0 s")
    return seconds


def interval_to_hz(seconds):
    """Seconds between samples -> samples per second. ValueError if the
    interval is not usable or so short that its rate overflows."""
    seconds = check_interval(seconds)
    hz = 1.0 / seconds
    if not math.isfinite(hz):
        raise ValueError(f"{seconds:g} s is too short to express in Hz")
    return hz


def hz_to_interval(hz):
    """Samples per second -> seconds between samples, through the same
    lower bound as a typed interval."""
    if isinstance(hz, bool):
        raise ValueError("the rate must be a number in Hz")
    try:
        hz = float(hz)
    except (TypeError, ValueError):
        raise ValueError("the rate must be a number in Hz")
    if not math.isfinite(hz):
        raise ValueError("the rate must be a finite number in Hz")
    if hz <= 0:
        raise ValueError("the rate must be greater than 0 Hz")
    return check_interval(1.0 / hz)


def parse_cadence(text, unit=UNIT_S):
    """The cadence box's text in `unit` -> the interval in SECONDS.

    Raises ValueError carrying a message meant for the user: empty, not a
    number, not finite, zero or negative are all refused, in either unit.
    A bare number with no unit is seconds, which is how the box read before
    #30, so existing habits and typed values keep their meaning.
    """
    unit = _norm_unit(unit)
    raw = '' if text is None else str(text).strip()
    if not raw:
        raise ValueError(
            f"Enter {_WHAT[unit]} (e.g. {_EXAMPLE[unit]}).")
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(
            f"{raw!r} is not a number. Enter {_WHAT[unit]} "
            f"(e.g. {_EXAMPLE[unit]}).")
    try:
        if unit == UNIT_S:
            return check_interval(value)
        return hz_to_interval(value)
    except ValueError as e:
        raise ValueError(f"{raw} {unit}: {e}.")


def fmt_number(value):
    """A cadence number for the box and the echo: up to 6 significant
    digits, no trailing zeros. 6 digits make s -> Hz -> s round-trip to the
    same text (3 -> 0.333333 -> 3)."""
    return f"{value:.6g}"


def convert_text(text, from_unit, to_unit):
    """The box's text re-expressed in `to_unit` when the unit selector
    changes, so switching units keeps the same cadence. Text that does not
    parse is returned unchanged (the user is mid-edit; Start will say what
    is wrong with it)."""
    from_unit, to_unit = _norm_unit(from_unit), _norm_unit(to_unit)
    if from_unit == to_unit:
        return text
    try:
        seconds = parse_cadence(text, from_unit)
        value = seconds if to_unit == UNIT_S else interval_to_hz(seconds)
    except ValueError:
        return text
    return fmt_number(value)


def describe_cadence(seconds):
    """'every 0.5 s (2 Hz)' -- the run's cadence in both units, for the
    Log Status line and the live readout."""
    seconds = check_interval(seconds)
    try:
        hz = f"{fmt_number(interval_to_hz(seconds))} Hz"
    except ValueError:
        hz = "too fast to express in Hz"
    return f"every {fmt_number(seconds)} s ({hz})"


def echo_text(text, unit):
    """The hint beside the cadence box: the same cadence in the other unit,
    or why the text is not a cadence yet. Never raises."""
    try:
        unit = _norm_unit(unit)
        seconds = parse_cadence(text, unit)
    except ValueError:
        if not str(text or '').strip():
            return ''
        return 'not a valid cadence'
    if unit == UNIT_S:
        try:
            return f"= {fmt_number(interval_to_hz(seconds))} Hz"
        except ValueError:
            return 'too fast to express in Hz'
    return f"= every {fmt_number(seconds)} s"


def next_tick(t_first, interval_s, slot, now):
    """When the next sample starts: (next_slot, due_time, skipped_slots).

    Samples are due on the grid t_first + k * interval_s, k = 0, 1, 2...
    `slot` is the k of the tick that just finished and `now` the time it
    finished (same clock as t_first). Normally the next tick is slot + 1.
    If the reads took so long that one or more later slots have already
    passed, those slots are SKIPPED and counted, never replayed: a slow
    tick is followed by idle time up to the next slot still ahead, not by a
    burst of catch-up reads. So the instruments are never polled more often
    than the cadence asked for, and a source slower than the cadence costs
    samples, not extra traffic.

    An interval too short for the grid arithmetic (the grid index stops
    being finite) degrades to "start now", which is what main's loop did
    for such an interval anyway.
    """
    nxt = slot + 1
    due = t_first + nxt * interval_s
    if due >= now:
        return nxt, due, 0
    behind = (now - t_first) / interval_s
    if not math.isfinite(behind) or behind > 2 ** 52:
        return nxt, now, 0
    late = int(math.ceil(behind))
    if late <= nxt:
        return nxt, max(due, now), 0
    return late, t_first + late * interval_s, late - nxt


# ---- Live current / min / max ----------------------------------------------

# A reading this large is an instrument saying "no number", never a value.
# SCPI's codes for that are 9.9E37 (INFinity), -9.9E37 (NINFinity) and
# 9.91E37 (NAN), and the Tek scope answers an off-screen measurement with
# 9.9E37 (TekMSO24.measure_raw, which already turns it into None). The
# DMM, supply and LCR replies reach LiveStats as plain floats, so a bare
# code would become a max and stay one for the rest of the run (#389).
# What the 5493C answers on an overload is unchecked (#369 asks the
# bench); its parser test assumes '9.9E37 OVLD', which is not a number and
# so already comes back None. The CSVs are not filtered: they keep
# whatever the instrument answered.
OVERLOAD_CODE = 9.9e37


def as_number(value):
    """A reading as a finite float, or None when it carries no number.

    None (scope 'No signal', DMM overload), NaN, infinities, booleans,
    unparseable strings and the SCPI overload codes (anything at or above
    OVERLOAD_CODE in size) all come back None, so a failed read can never
    become a min or a max."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or abs(v) >= OVERLOAD_CODE:
        return None
    return v


class LiveStats:
    """Current, min and max of every logged quantity, for ONE run.

    A new LiveStats is made at each Start, which is the reset: the logging
    worker of an earlier run keeps writing to its own object, never to the
    one the tab is showing. The worker thread writes; the Tk main thread
    reads snapshot(). Every access holds the lock.

    A row is keyed by (source, quantity, unit). The unit is part of the key
    so a mid-run change (say the LCR switched from CPD to LSRS on its own
    tab) starts new rows instead of taking a min across farads and henries.

    Only finite numbers count toward min and max. A reading without one
    leaves min and max alone and shows as no current value.
    """

    def __init__(self, interval_s=None):
        self._lock = threading.Lock()
        self._rows = {}              # key -> row dict, insertion-ordered
        self.interval_s = interval_s
        self.ticks = 0
        self.skipped = 0

    def record(self, source, readings):
        """One successful read of `source`: `readings` is a list of
        (quantity, value, unit). Rows of this source that the read did not
        produce lose their current value (they are no longer being read)."""
        seen = set()
        with self._lock:
            for quantity, value, unit in readings:
                key = (source, quantity, unit or '')
                seen.add(key)
                row = self._rows.get(key)
                if row is None:
                    row = self._rows[key] = {
                        'source': source, 'quantity': quantity,
                        'unit': unit or '', 'current': None, 'min': None,
                        'max': None, 'good': 0, 'missed': 0}
                v = as_number(value)
                row['current'] = v
                if v is None:
                    row['missed'] += 1
                    continue
                row['good'] += 1
                if row['min'] is None or v < row['min']:
                    row['min'] = v
                if row['max'] is None or v > row['max']:
                    row['max'] = v
            for key, row in self._rows.items():
                if key[0] == source and key not in seen:
                    row['current'] = None

    def record_failure(self, source):
        """A read of `source` that raised: every row of it shows no
        current value and counts a miss; min and max are kept."""
        with self._lock:
            for key, row in self._rows.items():
                if key[0] == source:
                    row['current'] = None
                    row['missed'] += 1

    def tick(self, skipped=0):
        """One sampling tick done, and how many grid slots it overran."""
        with self._lock:
            self.ticks += 1
            self.skipped += int(skipped)

    def snapshot(self):
        """(rows, ticks, skipped): copies, in first-seen order."""
        with self._lock:
            rows = [dict(r) for r in self._rows.values()]
            return rows, self.ticks, self.skipped


def fmt_value(value, unit):
    """A live readout cell: SI-prefixed with its unit, '--' for none."""
    return lcr_format.format_si(value, unit, digits=6)


def summary_line(ticks, skipped, interval_s, running):
    """The line under the live table."""
    if running and not ticks:
        return "Running: waiting for the first sample..."
    state = 'Running' if running else 'Stopped'
    cadence = ''
    if interval_s is not None:
        try:
            cadence = f", {describe_cadence(interval_s)}"
        except ValueError:
            cadence = ''
    line = f"{state}: {ticks} sample{'' if ticks == 1 else 's'}{cadence}"
    if skipped:
        line += (f"; {skipped} slot{'' if skipped == 1 else 's'} skipped "
                 "(reads took longer than the cadence)")
    return line


# ---- One source's reading as rows (the CSV columns, numeric ones) ---------

SCOPE_QUANTITIES = (('freq', 'Frequency', 'Hz'), ('period', 'Period', 's'),
                    ('mean', 'Mean', 'V'), ('pk2pk', 'Pk-Pk', 'V'),
                    ('rms', 'RMS', 'V'), ('amplitude', 'Amplitude', 'V'))

SG_QUANTITIES = (('FRQ', 'Frequency', 'Hz'), ('AMP', 'Amplitude', 'Vpp'),
                 ('OFST', 'Offset', 'V'), ('STDEV', 'Stdev', 'V'),
                 ('MEAN', 'Mean', 'V'))

PSU_QUANTITIES = (('set_voltage_v', 'Set V', 'V'),
                  ('meas_voltage_v', 'Meas V', 'V'),
                  ('meas_current_a', 'Meas A', 'A'),
                  ('power_w', 'Power', 'W'))


def _lcr_primary_name(mode):
    """'CPD' -> 'Cp', 'LSRS' -> 'Ls', 'RX' -> 'R', 'ZTD' -> 'Z'."""
    if len(mode) >= 2 and mode[0] in 'CL' and mode[1] in 'PS':
        return mode[0] + mode[1].lower()
    return mode[:1] or 'Primary'


def lcr_quantities(mode, freq_hz, primary, secondary, status):
    """The LCR row. A nonzero status is the meter saying the reading is not
    good (the LCR tab shows it as 'Status: Error'), so its primary and
    secondary count as misses rather than as values."""
    mode = str(mode or '').strip().upper()
    units = lcr_format.MODE_UNITS.get(mode)
    if units:
        p_unit, s_name, s_unit = units
        p_name = _lcr_primary_name(mode)
    else:
        p_name, p_unit, s_name, s_unit = 'Primary', '', 'Secondary', ''
    good = status == 0
    return [('Test frequency', freq_hz, 'Hz'),
            (p_name, primary if good else None, p_unit),
            (s_name, secondary if good else None, s_unit)]


def scope_quantities(meas):
    """All six scope measurements; a missing one (no signal) is a miss."""
    return [(name, meas.get(key), unit)
            for key, name, unit in SCOPE_QUANTITIES]


def sg_quantities(bswv):
    """The numeric stimulus settings the waveform actually has (a sine has
    no Stdev; leaving it out keeps the table free of rows that can never
    hold a value)."""
    return [(name, bswv.get(key), unit)
            for key, name, unit in SG_QUANTITIES if key in bswv]


def psu_quantities(reading):
    """The supply's row. Power is the driver's V_meas * I_meas, so it is a
    miss whenever either factor is: 9.9E37 V times 0.3 A is 2.97E37 W,
    under OVERLOAD_CODE, and would otherwise become the max (#389)."""
    rows = []
    for key, name, unit in PSU_QUANTITIES:
        value = reading.get(key)
        if key == 'power_w' and (
                as_number(reading.get('meas_voltage_v')) is None
                or as_number(reading.get('meas_current_a')) is None):
            value = None
        rows.append((name, value, unit))
    return rows


def dmm_quantities(function, value, unit):
    return [(function, value, unit)]
