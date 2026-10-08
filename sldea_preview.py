#!/usr/bin/env python3
"""How the SLDEA tab's preview marks each snapshot on its kV-vs-time canvas.

Pure logic -- no Tk -- so the marker vocabulary is unit-testable, and every
tag SldeaProfile can emit is guaranteed a marker: the camera warm-up frame
was once drawn as an unexplained black dot because the colour table had no
entry for it and fell through to a default.

Colour is never the only cue. Each snapshot kind has its own SHAPE, and
every colour comes from Paul Tol's schemes (CLAUDE.md), chosen by
worst-case CIEDE2000 over normal + Machado-2009 deutan/protan/tritan
simulation, with the matrices applied in LINEAR RGB (2026-09-23):

    post-ramp vs pre-ramp fills (Tol bright blue vs yellow)     43.2
    staircase line (Tol high-contrast black) vs either fill    >= 39.2
    the green/red pair this replaced, under deuteranopia          6.6

tests/test_sldea_preview.py holds these pairs to a floor of 18.0. That
is TOL_BRIGHT's adjacent-pair floor as the `#313` script measured it,
with the matrices applied to gamma-encoded sRGB (the 18.00 that
sldea_plot.py's GROUP_COLORS comment cites). Linear RGB is the standard
since 2026-10-06: Machado, Oliveira & Fernandes, IEEE TVCG
15(6):1291-1298, 2009, sec. 4.1, Eq. 8 builds the matrix from the
primaries' spectral power distributions, and colorspacious and
DaltonLens-Python both decode sRGB before applying it. Measured that way
the same floor is 15.35, so 18.0 is the stricter of the two bars.
Light fills (yellow, grey) carry a black edge, as Tol advises on white.

Headless self-test: .venv/bin/python tests/test_sldea_preview.py
"""
import math

from sldea_profile import fmt_duration

# Tol high-contrast black: the staircase, every marker edge and the run
# playhead. The playhead used to share the pre-ramp dots' red.
LINE = '#000000'
OUTLINE = '#000000'
PLAYHEAD = '#000000'
HOLLOW = '#FFFFFF'           # the open warm-up ring's face

# tag -> (shape, fill, legend text). Shapes are mutually distinct so the
# tags stay apart in greyscale, in print and for any colour vision.
MARKERS = {
    'warmup': ('circle', HOLLOW, 'warm-up'),
    'baseline': ('diamond', '#BBBBBB', 'baseline 0 kV'),   # Tol bright grey
    'post-ramp': ('triangle', '#4477AA', 'post-ramp'),     # Tol bright blue
    'pre-ramp': ('square', '#CCBB44', 'pre-ramp'),         # Tol bright yellow
}
LEGEND_ORDER = ('warmup', 'baseline', 'post-ramp', 'pre-ramp')

# Marker "radius" in canvas px. The floor is still larger than the old
# 3 px dots; the ceiling keeps a sparse profile from drawing blobs. On the
# default 0->10 kV x 0.25 kV profile one landing's pre-ramp snapshot sits
# ~5 px from the next landing's post-ramp one, so markers there stay near
# the floor and may just touch -- the outlines keep both shapes readable.
# `#401` made them about 14 % smaller (4 -> 3.5 and 7 -> 6).
R_MIN = 3.5
R_MAX = 6.0
# The legend's glyphs, at one radius in the same place between floor and
# ceiling as before `#401` (4.5 then).
R_LEGEND = 3.9
# The pointer's reach keeps the radius bounds the markers had before
# `#401`, so a smaller marker is no harder to hover: the reach is this
# radius, chosen by marker_radius the same way, plus 3 px.
HOVER_R_MIN = 4.0
HOVER_R_MAX = 7.0


def _scales(profile, x0, y0, x1, y1):
    total = profile.total_duration_s or 1.0
    vmax = max([profile.end_kv] + profile.levels) or 1.0
    return (lambda t: x0 + (x1 - x0) * t / total,
            lambda v: y1 - (y1 - y0) * v / vmax)


def staircase(profile, x0, y0, x1, y1):
    """Flat [x, y, x, y, ...] of the kV-vs-time drive curve in the plot box
    (x0, y0)-(x1, y1), top-left origin as on a Tk canvas."""
    X, Y = _scales(profile, x0, y0, x1, y1)
    pts = []
    for _kind, t0, t1, a, b in profile.segments:
        pts += [X(t0), Y(a), X(t1), Y(b)]
    return pts


def snapshot_points(profile, x0, y0, x1, y1):
    """[(x, y, snapshot), ...] for every scheduled snapshot, in time order
    -- the order they are drawn in, so later markers land on top."""
    X, Y = _scales(profile, x0, y0, x1, y1)
    return [(X(s['t']), Y(s['nominal_kv']), s)
            for s in sorted(profile.snapshots, key=lambda s: s['t'])]


def marker_radius(points, r_min=R_MIN, r_max=R_MAX):
    """Largest radius that keeps consecutive landing markers apart.

    `points` are the canvas (x, y) of the LANDING snapshots (post/pre-ramp)
    in time order. The warm-up and baseline frames are left out on purpose:
    they sit two seconds apart at 0 kV and overlap by design (the baseline
    is drawn on top), so they would pin every run to the floor."""
    gaps = [math.hypot(x1 - x0, y1 - y0)
            for (x0, y0), (x1, y1) in zip(points, points[1:])]
    if not gaps:
        return r_max
    return max(r_min, min(r_max, min(gaps) / 2.0 - 0.5))


def marker_coords(shape, x, y, r):
    """(kind, coords) for a Tk canvas item centred on (x, y).

    kind is 'oval' (coords = bounding box) or 'polygon' (flat vertex list).
    Sizes are tuned so the four shapes carry similar visual weight at the
    same r: a diamond needs a longer half-diagonal than a square's
    half-side, and a triangle's area sits low, so it is centred on its
    centroid rather than its bounding box."""
    if shape == 'circle':
        q = 0.85 * r
        return 'oval', [x - q, y - q, x + q, y + q]
    if shape == 'square':
        q = 0.9 * r
        return 'polygon', [x - q, y - q, x + q, y - q,
                           x + q, y + q, x - q, y + q]
    if shape == 'diamond':
        h = 1.25 * r
        return 'polygon', [x, y - h, x + h, y, x, y + h, x - h, y]
    if shape == 'triangle':
        R = 1.3 * r                            # circumradius, apex up
        c = R * math.cos(math.radians(30))
        return 'polygon', [x, y - R, x + c, y + R / 2, x - c, y + R / 2]
    raise ValueError(f"unknown marker shape {shape!r}")


def legend_tags(profile):
    """Marker tags this profile actually draws, in legend order."""
    present = {s['tag'] for s in profile.snapshots}
    return [t for t in LEGEND_ORDER if t in present]


def _direction(profile, step):
    """'rising'/'falling' for landing `step` on an up/down or repeat run
    (vs the landing before it), else ''. A plain single sweep only ever
    rises, so saying so on every marker would be noise."""
    if not (profile.updown or profile.repeat > 1):
        return ''
    seq = profile.sequence()
    if not 1 <= step <= len(seq):
        return ''
    prev = seq[step - 2] if step >= 2 else 0.0
    here = seq[step - 1]
    if here > prev:
        return 'rising'
    if here < prev:
        return 'falling'
    return 'repeat starts'           # the lowest level landed twice in a row


def describe(snap, profile):
    """Hover text for one scheduled snapshot: what it is, where, and when.

    Worded after the tag and the two fields that time it, so the canvas,
    the field row above it and the frame filenames all use one vocabulary."""
    tag, t, kv = snap['tag'], snap['t'], snap['nominal_kv']
    when = fmt_duration(t)
    if tag == 'warmup':
        return (f"Camera warm-up frame · 0 kV\nat {when} — lets the camera "
                f"settle; never used as the reference")
    if tag == 'baseline':
        return (f"Baseline snapshot · 0 kV\nat {when} — the reference "
                f"every area in the run is measured against")
    n = profile.n_levels
    step = snap['step']
    head = f"landing {step}/{n} · {kv:g} kV"
    d = _direction(profile, step)
    if d:
        head += f" ({d})"
    if tag == 'post-ramp':
        return (f"Post-ramp snapshot · {head}\nat {when} — "
                f"{profile.settle_s:g} s after the ramp ends")
    if tag == 'pre-ramp':
        nxt = 'the run ends' if step >= n else 'the next ramp'
        return (f"Pre-ramp snapshot · {head}\nat {when} — "
                f"{profile.snap_lead_s:g} s before {nxt}")
    return f"{tag} snapshot · {kv:g} kV\nat {when}"
