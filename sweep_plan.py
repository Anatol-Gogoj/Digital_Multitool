#!/usr/bin/env python3
"""Sweep planning: turn one axis' UI fields into the list of points to visit.

Pure arithmetic only -- no Tk, no VISA, no instrument I/O. This is the
planning half of a stepped sweep; the stepping itself (setting the box,
dwelling, reading back) stays in the GUI worker thread.

The LCR tab's sweep (`gui.InstrumentControlGUI._parse_sweep_axis`) grew this
maths welded to its Tk variables, which made it untestable and unusable from
anywhere else. The signal-generator sweep of `#65` wants exactly the same
planner, so it lives here now and the GUI method is a thin wrapper that reads
its widgets and delegates.

Fields arrive as strings (Tk entries only ever hand back text), so `plan_axis`
does its own float()/int() conversion and reports a bad field as a ValueError
the caller can put straight in front of the user. Every failure mode is a
ValueError carrying a message that names the axis.

The signal-generator half (`sg_points`, `level_writes`, `sg_extremes`,
`readback_matches`) turns two planned axes into the settings the Signal
Gen tab's sweep visits, and says in which order to send each change.

Headless self-test: .venv/bin/python tests/test_sweep_plan.py
"""
import math

from waveform_render import unipolar_offset

# Axis modes, as stored in the Tk mode variables.
MODE_LIST = 'list'
MODE_RANGE = 'range'

# Signal Gen sweep orders, as the Order box shows them. Amplitude outer is
# the default: each level is held across every frequency, and the levels
# only ever rise, so the highest one comes last.
SG_ORDER_AMP_OUTER = 'Vpp outer, Freq inner'
SG_ORDER_FREQ_OUTER = 'Freq outer, Vpp inner'
SG_ORDERS = (SG_ORDER_AMP_OUTER, SG_ORDER_FREQ_OUTER)


def plan_axis(mode, list_text='', start=None, stop=None, points=None,
              scale='linear', vmin=float('-inf'), vmax=float('inf'),
              name='Value'):
    """Return the list[float] of points for one sweep axis.

    ``mode`` == 'list' reads ``list_text`` -- comma- (or semicolon-) separated
    values, blanks ignored, so a trailing separator is harmless. Anything else
    is treated as a range: ``points`` values from ``start`` to ``stop``, spaced
    linearly or (``scale`` == 'log') geometrically.

    Descending sweeps (stop < start) are supported in both scalings. A log
    sweep needs a positive start AND stop -- zero or negative would give a
    complex or infinite ratio -- and is rejected rather than allowed to
    produce NaN/inf points that would be sent to an instrument.

    The last point is assigned ``stop`` verbatim instead of being computed,
    because the accumulated ratio/step lands a decade sweep on
    100000.00000000003 and an operator reading that in a CSV rightly does not
    trust the rest of the column.

    Every point is checked against the inclusive [vmin, vmax] instrument
    limits. Raises ValueError -- naming ``name`` -- on any bad input.
    """
    if mode == MODE_LIST:
        try:
            values = [float(x) for x in list_text.replace(';', ',').split(',')
                      if x.strip()]
        except ValueError as e:
            raise ValueError(f"{name} list could not be parsed: {e}")
        if not values:
            raise ValueError(f"{name} list is empty")
    else:
        try:
            start = float(start)
            stop = float(stop)
            points = int(points)
        except ValueError as e:
            raise ValueError(f"{name} range fields must be numeric: {e}")
        if points < 1:
            raise ValueError(f"{name} points must be ≥ 1")
        if points == 1:
            values = [start]
        elif scale == 'log':
            if start <= 0 or stop <= 0:
                raise ValueError(
                    f"{name} log sweep requires positive start and stop")
            ratio = (stop / start) ** (1.0 / (points - 1))
            values = [start * (ratio ** i) for i in range(points - 1)]
            values.append(stop)  # snap endpoint to avoid 100000.00000000003
        else:
            step = (stop - start) / (points - 1)
            values = [start + step * i for i in range(points - 1)]
            values.append(stop)
    for v in values:
        if not (vmin <= v <= vmax):
            raise ValueError(f"{name} value {v} is outside [{vmin}, {vmax}]")
    return values


def sg_points(freqs, amps, order=SG_ORDER_AMP_OUTER, unipolar=True,
              offset_v=0.0):
    """The settings a Signal Gen sweep visits, in order: a list of
    (frequency Hz, amplitude Vpp, offset V) tuples.

    ``order`` is one of SG_ORDERS; with ``unipolar`` every point's offset
    is half its amplitude (waveform_render.unipolar_offset), so each point
    runs from 0 V to its Vpp. Otherwise every point uses ``offset_v``.
    """
    if order not in SG_ORDERS:
        raise ValueError(f"Order must be one of {SG_ORDERS}, got {order!r}")
    if order == SG_ORDER_AMP_OUTER:
        pairs = [(f, a) for a in amps for f in freqs]
    else:
        pairs = [(f, a) for f in freqs for a in amps]
    fixed = float(offset_v)
    return [(float(f), float(a),
             unipolar_offset(a) if unipolar else fixed) for f, a in pairs]


def level_writes(prev, new):
    """The BSWV writes that take a channel from ``prev`` to ``new`` (each a
    (frequency, amplitude, offset) tuple), as a list of parameter dicts in
    the order to send them. Only what changed is sent; nothing changed is
    an empty list.

    Frequency goes first; it moves no voltage. When the amplitude AND the
    offset change, the order keeps the waveform inside the band the two
    settings span between them, so the one in-between setting the box
    holds never reaches a new extreme:

    * amplitude shrinking: amplitude first. The old offset then centres a
      narrower swing, inside the old setting's band.
    * amplitude growing (or equal): offset first. The new offset then
      centres the old, narrower swing, inside the new setting's band.

    For a 0 V to Vpp sweep both troughs are 0 V, so the waveform never
    dips below 0 V between points. Sent as one combined BSWV the order
    would be the firmware's, which nobody has measured.
    """
    f0, a0, o0 = prev
    f1, a1, o1 = new
    out = []
    if f1 != f0:
        out.append({'FRQ': f1})
    amp = {'AMP': a1} if a1 != a0 else None
    off = {'OFST': o1} if o1 != o0 else None
    if amp and off:
        out += [amp, off] if a1 < a0 else [off, amp]
    else:
        out += [w for w in (amp, off) if w]
    return out


def sg_extremes(points):
    """(lowest trough, highest peak) in volts over ``points``, each a
    (frequency, amplitude, offset) tuple: offset -/+ amplitude / 2."""
    if not points:
        raise ValueError("no points")
    return (min(o - a / 2.0 for _f, a, o in points),
            max(o + a / 2.0 for _f, a, o in points))


def readback_matches(asked, got):
    """True when the instrument's read-back ``got`` (a BSWV dict with FRQ,
    AMP and OFST as floats, as BK4055B.get_basic_wave_dict returns them)
    holds the (frequency, amplitude, offset) ``asked`` for.

    The tolerance covers the box rounding what it echoes (0.1 % of the
    value, or 1 uHz / 1 mV), not a different setting: a clamped amplitude
    or a refused offset fails it. A missing or non-numeric field fails it.
    """
    f, a, o = asked
    try:
        return (math.isclose(float(got['FRQ']), f, rel_tol=1e-3,
                             abs_tol=1e-6)
                and math.isclose(float(got['AMP']), a, rel_tol=1e-3,
                                 abs_tol=1e-3)
                and math.isclose(float(got['OFST']), o, rel_tol=1e-3,
                                 abs_tol=1e-3))
    except (KeyError, TypeError, ValueError):
        return False
