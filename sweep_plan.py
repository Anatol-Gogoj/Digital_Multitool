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

Headless self-test: .venv/bin/python tests/test_sweep_plan.py
"""

# Axis modes, as stored in the Tk mode variables.
MODE_LIST = 'list'
MODE_RANGE = 'range'


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
