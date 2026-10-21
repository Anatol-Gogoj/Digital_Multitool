#!/usr/bin/env python3
"""The SLDEA tab's preview marks snapshots by SHAPE, in Tol colours.

What these pin down (2026-09-23):
  * every tag SldeaProfile can schedule has a marker -- the camera warm-up
    frame once fell through a colour table to an unexplained black dot;
  * the markers differ in shape, so colour is never the only cue;
  * every colour is from Paul Tol's schemes, and the pairs that share the
    staircase stay apart under simulated colour blindness: worst-case
    CIEDE2000 over Machado-2009 deutan/protan/tritan >= 18. (18.00 is
    TOL_BRIGHT's adjacent-pair floor as the `#313` script measured it,
    with the matrices applied to gamma-encoded sRGB. This file applies
    them in LINEAR RGB, the standard since 2026-10-06 (sourced in
    SLDEA_DECISIONS.md), where that same floor is 15.35, so 18 is the
    stricter of the two bars.) The old green/red pair is held to the same
    bar and must FAIL it, so the check is one that can fail. Since #461
    (2026-10-19) the baseline is held to it too, beside post-ramp,
    pre-ramp, the staircase and the warm-up ring (that set of four is
    pinned, so none can be dropped quietly; #476), and the grey it
    replaced must fail it;
  * marker size follows the room between landings, within its limits,
    and the markers made smaller in #401 keep the old hover reach;
  * the hover text names each snapshot in the tab's own words;
  * Edge Review's area_vs_voltage.png marks each tag with the preview's
    shape, fill, black edge and legend text (#478, 2026-10-21). Both
    sides are read as drawn: the canvas items, and the matplotlib
    artists of the figure Save writes, each outline named by its
    geometry rather than by a constant;
  * on the real tab: the two timing fields sit together under their tags'
    names and still drive the profile, the canvas draws one marker per
    scheduled snapshot plus a legend, each in its tag's shape and fill,
    the playhead is not the old red, hovering a marker describes it, and
    the area plot of the same schedule marks every tag it draws as the
    canvas does.

Run: .venv/bin/python tests/test_sldea_preview.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import math

import sldea_preview as pv
import sldea_profile as sp


class _Skip(Exception):
    """The test could not run here (no display) -- reported, not passed."""


# Paul Tol's bright scheme (the house plot palette, sldea_plot.TOL_BRIGHT)
# and his high-contrast scheme, whose black carries the lines.
TOL_BRIGHT = {'#4477AA', '#66CCEE', '#228833', '#CCBB44', '#EE6677',
              '#AA3377', '#BBBBBB'}
TOL_HIGH_CONTRAST = {'#FFFFFF', '#DDAA33', '#BB5566', '#004488', '#000000'}
TOL = TOL_BRIGHT | TOL_HIGH_CONTRAST

CVD_FLOOR = 18.0

# Machado, Oliveira & Fernandes 2009, severity 1.0, applied in linear RGB.
MACHADO = {
    'normal': ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    'deuteranopia': ((0.367322, 0.860646, -0.227968),
                     (0.280085, 0.672501, 0.047413),
                     (-0.011820, 0.042940, 0.968881)),
    'protanopia': ((0.152286, 1.052583, -0.204868),
                   (0.114503, 0.786281, 0.099216),
                   (-0.003882, -0.048116, 1.051998)),
    'tritanopia': ((1.255528, -0.076749, -0.178779),
                   (-0.078411, 0.930809, 0.147602),
                   (0.004733, 0.691367, 0.303900)),
}


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lab_seen(hex_colour, vision):
    """CIELAB (D65) of `hex_colour` as seen under `vision`."""
    h = hex_colour.lstrip('#')
    rgb = [_lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4)]
    m = MACHADO[vision]
    rgb = [min(1.0, max(0.0, sum(m[r][k] * rgb[k] for k in range(3))))
           for r in range(3)]
    xyz = [sum(w * c for w, c in zip(row, rgb)) / n for row, n in zip(
        ((0.4124564, 0.3575761, 0.1804375),
         (0.2126729, 0.7151522, 0.0721750),
         (0.0193339, 0.1191920, 0.9503041)), (0.95047, 1.0, 1.08883))]
    d = 6 / 29
    fx, fy, fz = (t ** (1 / 3) if t > d ** 3 else t / (3 * d * d) + 4 / 29
                  for t in xyz)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _ciede2000(lab1, lab2):
    (L1, a1, b1), (L2, a2, b2) = lab1, lab2
    cb = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(cb ** 7 / (cb ** 7 + 25 ** 7)))
    a1, a2 = (1 + g) * a1, (1 + g) * a2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    h1 = math.degrees(math.atan2(b1, a1)) % 360
    h2 = math.degrees(math.atan2(b2, a2)) % 360
    dh = 0.0 if c1 * c2 == 0 else (
        h2 - h1 if abs(h2 - h1) <= 180 else
        h2 - h1 - 360 if h2 > h1 else h2 - h1 + 360)
    dH = 2 * math.sqrt(c1 * c2) * math.sin(math.radians(dh / 2))
    lm, cm = (L1 + L2) / 2, (c1 + c2) / 2
    hm = h1 + h2 if c1 * c2 == 0 else (
        (h1 + h2) / 2 if abs(h1 - h2) <= 180 else
        (h1 + h2 + 360) / 2 if h1 + h2 < 360 else (h1 + h2 - 360) / 2)
    t = (1 - 0.17 * math.cos(math.radians(hm - 30))
         + 0.24 * math.cos(math.radians(2 * hm))
         + 0.32 * math.cos(math.radians(3 * hm + 6))
         - 0.20 * math.cos(math.radians(4 * hm - 63)))
    rt = (-2 * math.sqrt(cm ** 7 / (cm ** 7 + 25 ** 7))
          * math.sin(math.radians(60 * math.exp(-((hm - 275) / 25) ** 2))))
    sl = 1 + 0.015 * (lm - 50) ** 2 / math.sqrt(20 + (lm - 50) ** 2)
    sc, sh = 1 + 0.045 * cm, 1 + 0.015 * cm * t
    return math.sqrt(((L2 - L1) / sl) ** 2 + ((c2 - c1) / sc) ** 2
                     + (dH / sh) ** 2 + rt * ((c2 - c1) / sc) * (dH / sh))


def _worst_de(c1, c2):
    """Smallest CIEDE2000 between two colours over all four visions."""
    return min(_ciede2000(_lab_seen(c1, v), _lab_seen(c2, v))
               for v in MACHADO)


def _profiles():
    """Profiles that between them schedule every snapshot kind."""
    return [sp.SldeaProfile(),                                # tab defaults
            sp.SldeaProfile(updown=True, repeat=2),
            sp.SldeaProfile(baseline_warmup_s=0),
            sp.SldeaProfile(end_kv=2, step_kv=1, snap_pre=False),
            sp.SldeaProfile(end_kv=2, step_kv=1, snap_post=False)]


def _outline_shape(pts, curved=False):
    """Name the outline `pts` [(x, y), ...] (y UP) draws: 'circle',
    'square', 'diamond', 'triangle' (apex up) or 'other'. From geometry
    alone, so a shape is read off what was drawn, not off a constant.
    `curved` says the outline is a curve, whose `pts` then only bound it."""
    xs = [x for x, _y in pts]
    ys = [y for _x, y in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    tol = 1e-3 * span
    if curved:
        round_ = abs((max(xs) - min(xs)) - (max(ys) - min(ys))) < tol
        return 'circle' if round_ else 'other'
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]                        # a repeated closing vertex
    cx = sum(x for x, _y in pts) / len(pts)
    cy = sum(y for _x, y in pts) / len(pts)
    rel = [(x - cx, y - cy) for x, y in pts]
    if len(rel) == 4:
        if all(min(abs(dx), abs(dy)) < tol for dx, dy in rel) and abs(
                max(abs(dx) for dx, _ in rel)
                - max(abs(dy) for _, dy in rel)) < tol:
            return 'diamond'          # corners on the axes, as wide as tall
        if all(abs(abs(dx) - abs(dy)) < tol for dx, dy in rel):
            return 'square'                   # corners on the diagonals
    if len(rel) == 3:
        apex = max(rel, key=lambda p: p[1])
        (bx0, by0), (bx1, by1) = [p for p in rel if p is not apex]
        if abs(apex[0]) < tol and abs(by0 - by1) < tol \
                and abs(bx0 + bx1) < tol and by0 < apex[1]:
            return 'triangle'
    return 'other'


def _canvas_shape(kind, coords):
    """The shape a Tk canvas item draws, from its type and coords (Tk's
    y grows DOWN, so it is flipped first)."""
    if kind == 'oval':
        x0, y0, x1, y1 = coords
        return _outline_shape([(x0, -y0), (x1, -y1)], curved=True)
    if kind == 'polygon':
        return _outline_shape([(coords[i], -coords[i + 1])
                               for i in range(0, len(coords), 2)])
    return 'other'


def _mpl_shape(marker):
    """The shape matplotlib draws for `marker` (a marker code or a
    MarkerStyle), read off the marker's own path, transform included."""
    from matplotlib.markers import MarkerStyle
    from matplotlib.path import Path
    ms = marker if isinstance(marker, MarkerStyle) else MarkerStyle(marker)
    path = ms.get_path().transformed(ms.get_transform())
    codes = (list(path.codes) if path.codes is not None
             else [Path.LINETO] * len(path.vertices))
    pts = [(float(x), float(y)) for (x, y), c in zip(path.vertices, codes)
           if c != Path.CLOSEPOLY]
    if not pts:
        return 'other'
    curved = any(c in (Path.CURVE3, Path.CURVE4) for c in codes)
    return _outline_shape(pts, curved=curved)


def _drawn_shape(artist):
    """The shape a Line2D, or a legend handle, draws. get_marker() gives
    back only the marker code and drops a MarkerStyle's own transform (a
    '^' turned over would still read apex up), so the MarkerStyle the
    artist holds is read where matplotlib keeps one (`_marker`)."""
    from matplotlib.markers import MarkerStyle
    ms = getattr(artist, '_marker', None)
    return _mpl_shape(ms if isinstance(ms, MarkerStyle)
                      else artist.get_marker())


def _hex(colour):
    from matplotlib import colors as mcolors
    return mcolors.to_hex(colour).upper()


def _marker_reach(artist):
    """How far a Line2D's marker path reaches from its centre, in points
    (its largest vertex coordinate times its size)."""
    from matplotlib.markers import MarkerStyle
    ms = getattr(artist, '_marker', None)
    if not isinstance(ms, MarkerStyle):
        ms = MarkerStyle(artist.get_marker())
    path = ms.get_path().transformed(ms.get_transform())
    return float(max(max(abs(x), abs(y)) for x, y in path.vertices)
                 * artist.get_markersize())


def _area_plot_marks(rows, rejected=(), areas=None, png=False):
    """Run Edge Review's real Save plot (`_save_plot`) on `rows` and read
    back what the figure holds: ({label: mark}, [legend entry, ...]) where
    a mark is {'shape', 'fill', 'edge', 'alpha', 'size', 'z', 'xs',
    'reach_pt', 'edge_pt', 'px'} ('px': each point's centre in the saved
    PNG's pixels) and a legend entry is (text, shape, fill, edge), in the
    legend's order. Every row has an accepted area (`areas[i]`, else
    100 + i) except the indices in `rejected`, which carry None, as Edge
    Review records a rejected frame. With `png`, the saved image (an RGB
    array) and its dpi come back too."""
    import shutil
    import tempfile
    import types
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    from PIL import Image
    import sldea_edge_gui
    d = tempfile.mkdtemp(prefix='preview_area_plot_')
    seen = {}
    real = Figure.savefig

    def spy(fig, path, *a, **k):
        ax = fig.axes[0]
        dpi = k.get('dpi') or fig.dpi
        height = fig.get_figheight() * dpi

        def px(ln):
            pts = ax.transData.transform(np.column_stack(
                [ln.get_xdata(), ln.get_ydata()]))
            return [(x * dpi / fig.dpi, height - y * dpi / fig.dpi)
                    for x, y in pts]
        seen['lines'] = [
            (ln.get_label(), {'shape': _drawn_shape(ln),
                              'fill': _hex(ln.get_markerfacecolor()),
                              'edge': _hex(ln.get_markeredgecolor()),
                              'alpha': ln.get_alpha(),
                              'size': ln.get_markersize(),
                              'z': ln.get_zorder(),
                              'xs': [float(x) for x in ln.get_xdata()],
                              'reach_pt': _marker_reach(ln),
                              'edge_pt': ln.get_markeredgewidth(),
                              'px': px(ln)})
            for ln in ax.lines]
        leg = ax.get_legend()
        handles = (getattr(leg, 'legend_handles', None)
                   or getattr(leg, 'legendHandles', []))
        seen['legend'] = [(t.get_text(), _drawn_shape(h),
                           _hex(h.get_markerfacecolor()),
                           _hex(h.get_markeredgecolor()))
                          for t, h in zip(leg.get_texts(), handles)]
        out = real(fig, path, *a, **k)
        with Image.open(path) as im:
            seen['png'] = np.asarray(im.convert('RGB')).astype(int)
        seen['dpi'] = dpi
        return out
    Figure.savefig = spy
    try:
        stub = types.SimpleNamespace(
            rundir=d, run={'rows': rows},
            results={i: (None if i in rejected else
                         {'area_px': (areas or {}).get(i, 100.0 + i)})
                     for i in range(len(rows))})
        sldea_edge_gui.EdgeReviewApp._save_plot(stub, None)
    finally:
        Figure.savefig = real
        shutil.rmtree(d, ignore_errors=True)
    lines = seen.get('lines', [])
    labels = [label for label, _m in lines]
    assert len(set(labels)) == len(labels), f"one label twice: {labels}"
    if png:
        return dict(lines), seen.get('legend', []), seen['png'], seen['dpi']
    return dict(lines), seen.get('legend', [])


# ---------------------------------------------------------------- headless

def test_every_scheduled_tag_has_a_marker():
    tags = {s['tag'] for p in _profiles() for s in p.snapshots}
    assert tags >= {'warmup', 'baseline', 'post-ramp', 'pre-ramp'}, (
        f"the fixture profiles no longer exercise every kind: {tags}")
    missing = tags - set(pv.MARKERS)
    assert not missing, f"scheduled with no preview marker: {missing}"
    assert set(pv.LEGEND_ORDER) == set(pv.MARKERS)


def test_shape_alone_tells_every_tag_apart():
    shapes = [shape for shape, _fill, _label in pv.MARKERS.values()]
    assert len(set(shapes)) == len(shapes), (
        f"two snapshot kinds share a shape, so only colour separates "
        f"them: {shapes}")
    labels = [label for _shape, _fill, label in pv.MARKERS.values()]
    assert len(set(labels)) == len(labels), labels


def test_colours_come_from_tol_schemes():
    used = ({fill for _s, fill, _l in pv.MARKERS.values()}
            | {pv.LINE, pv.OUTLINE, pv.PLAYHEAD})
    stray = {c.upper() for c in used} - TOL
    assert not stray, f"colours outside Paul Tol's schemes: {stray}"


def test_marks_on_the_staircase_survive_colour_blindness():
    post = pv.MARKERS['post-ramp'][1]
    pre = pv.MARKERS['pre-ramp'][1]
    for name, a, b in (('post-ramp vs pre-ramp', post, pre),
                       ('staircase vs post-ramp', pv.LINE, post),
                       ('staircase vs pre-ramp', pv.LINE, pre)):
        worst = _worst_de(a, b)
        assert worst >= CVD_FLOOR, (
            f"{name}: worst-case CIEDE2000 {worst:.1f} < {CVD_FLOOR}")


def test_the_old_green_red_pair_fails_that_bar():
    # the pair this replaced; proves the check above can fail at all
    worst = _worst_de('#2e7d32', '#c62828')
    assert worst < CVD_FLOOR, worst
    assert 5.0 < worst < 8.0, f"expected the measured ~6.6, got {worst:.2f}"


def _baseline_pairs(baseline):
    # The baseline diamond sits on the staircase at 0 kV, overlaps the
    # warm-up ring by design (drawn on top of it), and shares the legend
    # with both landing fills. The ring is hollow: its face is HOLLOW.
    return (('baseline vs post-ramp', baseline, pv.MARKERS['post-ramp'][1]),
            ('baseline vs pre-ramp', baseline, pv.MARKERS['pre-ramp'][1]),
            ('baseline vs staircase', baseline, pv.LINE),
            ('baseline vs warm-up ring', baseline, pv.MARKERS['warmup'][1]))


def test_the_baseline_survives_colour_blindness_beside_its_neighbours():
    # #461: no pair involving the baseline was checked before, and the
    # grey it had missed the floor twice (next test)
    assert pv.MARKERS['warmup'][1] == pv.HOLLOW
    for name, a, b in _baseline_pairs(pv.MARKERS['baseline'][1]):
        worst = _worst_de(a, b)
        assert worst >= CVD_FLOOR, (
            f"{name}: worst-case CIEDE2000 {worst:.1f} < {CVD_FLOOR}")


def test_the_old_grey_baseline_fails_that_bar():
    # Tol bright grey #BBBBBB, the baseline until #461: shapes kept it
    # readable, but beside pre-ramp yellow and the warm-up ring's white
    # face it measured 16.02 and 15.41, so the check above can fail.
    worst = {name: _worst_de(a, b)
             for name, a, b in _baseline_pairs('#BBBBBB')}
    failing = sorted(n for n, w in worst.items() if w < CVD_FLOOR)
    assert failing == ['baseline vs pre-ramp',
                       'baseline vs warm-up ring'], worst
    assert 15.9 < worst['baseline vs pre-ramp'] < 16.1, worst
    assert 15.3 < worst['baseline vs warm-up ring'] < 15.5, worst


def test_the_baseline_is_held_against_every_neighbour():
    # also from #476: the two tests above share _baseline_pairs, and the
    # grey one names only the two pairs the grey fails. A pair dropped
    # from the helper (the grey passes beside post-ramp and the staircase)
    # would pass both, so the whole set is pinned here, partners included.
    probe = '#123456'
    pairs = _baseline_pairs(probe)
    assert all(a == probe for _name, a, _b in pairs), pairs
    names = [name for name, _a, _b in pairs]
    assert len(names) == len(set(names)), names
    assert {name: b for name, _a, b in pairs} == {
        'baseline vs post-ramp': pv.MARKERS['post-ramp'][1],
        'baseline vs pre-ramp': pv.MARKERS['pre-ramp'][1],
        'baseline vs staircase': pv.LINE,
        'baseline vs warm-up ring': pv.HOLLOW}, pairs


def test_the_shape_reader_tells_the_four_shapes_apart():
    # the reader the two tests below rely on: it must name each outline
    # right, and must not name a wrong one as any of the four
    assert _outline_shape([(0, 0), (2, 2)], curved=True) == 'circle'
    assert _outline_shape([(0, 0), (3, 2)], curved=True) == 'other'
    assert _outline_shape([(-1, -1), (1, -1), (1, 1), (-1, 1)]) == 'square'
    assert _outline_shape([(0, -1), (1, 0), (0, 1), (-1, 0)]) == 'diamond'
    assert _outline_shape([(0, 1), (-1, -1), (1, -1)]) == 'triangle'
    assert _outline_shape([(0, -1), (-1, 1), (1, 1)]) == 'other'   # apex down
    assert _outline_shape([(-2, -1), (2, -1), (2, 1), (-2, 1)]) == 'other'
    assert _mpl_shape('v') == 'other' and _mpl_shape('d') == 'other'


def test_matplotlib_marks_are_the_canvas_shapes():
    # #478: mpl_style is how a figure off the canvas marks a tag. Both
    # outlines are read as drawn, the canvas polygon from marker_coords
    # and the path matplotlib draws for the marker code, and must name
    # the tag's shape. Fill, edge and legend text are the canvas's too.
    assert len(set(pv.MPL_MARKERS.values())) == len(pv.MPL_MARKERS)
    for tag, (shape, fill, label) in pv.MARKERS.items():
        kind, co = pv.marker_coords(shape, 100.0, 50.0, pv.R_MAX)
        assert _canvas_shape(kind, co) == shape, (tag, kind, co)
        style = pv.mpl_style(tag)
        assert _mpl_shape(style['marker']) == shape, (tag, style['marker'])
        assert style['markerfacecolor'] == fill, (tag, style)
        assert style['markeredgecolor'] == pv.OUTLINE, (tag, style)
        assert style['label'] == label and style['linestyle'] == '', style
        # one size for all but the warm-up, which rings what it shares a
        # point with in the area plot
        assert style['markersize'] == (pv.MPL_WARMUP_SIZE if tag == 'warmup'
                                       else pv.MPL_SIZE), style
        assert 'alpha' not in style, style


def test_the_area_plot_marks_each_tag_as_the_preview_does():
    # Edge Review's area_vs_voltage.png, read off the figure Save writes
    # (#478). Until then it drew the baseline as a black triangle and
    # post-ramp as a circle, the preview's post-ramp and warm-up shapes,
    # and left the warm-up frame out. The owner chose to show an accepted
    # warm-up frame, as the preview's open circle (2026-10-21). The 07-23
    # era's 'post'/'pre' tags join post-ramp and pre-ramp; a watchdog
    # breakdown row is not plotted.
    rows = [{'nominal_kV': '0', 'tag': 'warmup'},
            {'nominal_kV': '0', 'tag': 'baseline'},
            {'nominal_kV': '1', 'tag': 'post-ramp'},
            {'nominal_kV': '1', 'tag': 'pre-ramp'},
            {'nominal_kV': '2', 'tag': 'post'},
            {'nominal_kV': '2', 'tag': 'pre'},
            {'nominal_kV': '2.5', 'tag': 'breakdown'}]
    drawn, legend = _area_plot_marks(rows)
    by_label = {label: tag for tag, (_s, _f, label) in pv.MARKERS.items()}
    unknown = set(drawn) - set(by_label)
    assert not unknown, f"area plot labels the preview does not use: {unknown}"
    tags = [by_label[label] for label in drawn]
    assert tags == list(pv.LEGEND_ORDER), \
        f"not every tag, or not in the preview's legend order: {tags}"
    for label, mark in drawn.items():
        shape, fill, _label = pv.MARKERS[by_label[label]]
        assert mark['shape'] == shape, (label, mark)
        assert mark['fill'] == fill.upper(), (label, mark)
        assert mark['edge'] == pv.OUTLINE, (label, mark)
        assert mark['alpha'] in (None, 1.0), (label, mark)
    assert drawn['warm-up']['xs'] == [0.0]
    assert drawn['baseline 0 kV']['xs'] == [0.0]
    assert drawn['post-ramp']['xs'] == [1.0, 2.0]
    assert drawn['pre-ramp']['xs'] == [1.0, 2.0]
    # opaque marks hide what is under them, so marks that share a point
    # stack largest first: the warm-up ring, drawn larger, at the bottom,
    # then baseline, pre-ramp, and post-ramp's triangle (which fits in the
    # square at one size) on top
    order = sorted(drawn, key=lambda label: drawn[label]['z'])
    assert order == ['warm-up', 'baseline 0 kV', 'pre-ramp', 'post-ramp'], \
        [(label, drawn[label]['z']) for label in order]
    assert len({m['z'] for m in drawn.values()}) == 4, drawn
    others = {m['size'] for label, m in drawn.items() if label != 'warm-up'}
    assert others == {pv.MPL_SIZE}, drawn
    assert drawn['warm-up']['size'] == pv.MPL_WARMUP_SIZE > pv.MPL_SIZE, \
        drawn['warm-up']
    want = [(pv.MARKERS[t][2], pv.MARKERS[t][0], pv.MARKERS[t][1].upper(),
             pv.OUTLINE) for t in tags]
    assert legend == want, legend
    # only an ACCEPTED warm-up frame is drawn: a run without one, or with
    # its warm-up rejected in review, has no warm-up mark or legend entry
    for case, (case_rows, rejected) in {
            'no warm-up row': (rows[1:], ()),
            'warm-up rejected': (rows, (0,))}.items():
        drawn, legend = _area_plot_marks(case_rows, rejected=rejected)
        assert 'warm-up' not in drawn, (case, list(drawn))
        assert [text for text, _s, _f, _e in legend] == [
            'baseline 0 kV', 'post-ramp', 'pre-ramp'], (case, legend)


def test_the_warmup_ring_shows_the_baseline_inside_it():
    # The warm-up and the baseline are the membrane at rest two seconds
    # apart, so they usually measure one area and land on one point. The
    # warm-up circle is drawn first and larger (MPL_WARMUP_SIZE), so it
    # rings the diamond (2026-10-21). Drawn over it at MPL_SIZE, the white
    # circle covered the diamond's red; under it at MPL_SIZE, the diamond
    # hid the circle. Read off the saved PNG: the red diamond shows, and
    # the ring's black edge shows outside it all the way round, with the
    # ring's white face between.
    import math
    import numpy as np
    rows = [{'nominal_kV': '0', 'tag': 'warmup'},
            {'nominal_kV': '0', 'tag': 'baseline'},
            {'nominal_kV': '1', 'tag': 'post-ramp'},
            {'nominal_kV': '1', 'tag': 'pre-ramp'}]
    drawn, _legend, img, dpi = _area_plot_marks(
        rows, areas={0: 201.0, 1: 201.0, 2: 204.0, 3: 204.0}, png=True)
    ring, dia = drawn['warm-up'], drawn['baseline 0 kV']
    assert ring['px'] == dia['px'], (ring['px'], dia['px'])
    k = dpi / 72.0                                      # px per point
    # From the drawn paths: the diamond's mitred black tips reach half
    # its edge width over sin 45 degrees past its points; the ring's black
    # edge starts half its own width inside its radius.
    tip = dia['reach_pt'] + dia['edge_pt'] / 2 / math.sin(math.radians(45))
    inner = ring['reach_pt'] - ring['edge_pt'] / 2
    assert (inner - tip) * k >= 1.5, \
        f"the ring clears the diamond by only {(inner - tip) * k:.2f} px"
    cx, cy = ring['px'][0]
    rows_, cols_ = np.mgrid[0:img.shape[0], 0:img.shape[1]]
    near = ((cols_ + 0.5 - cx) ** 2 + (rows_ + 0.5 - cy) ** 2
            <= (dia['reach_pt'] * k) ** 2)
    red = np.abs(img - np.array([0xBB, 0x55, 0x66])).sum(axis=2) < 60
    assert (red & near).sum() >= 20, \
        f"only {(red & near).sum()} red px: the diamond is covered"

    def gray(r, deg):
        x = cx + r * math.cos(math.radians(deg))
        y = cy - r * math.sin(math.radians(deg))
        return int(img[int(math.floor(y)), int(math.floor(x))].mean())
    # Along each ray: the diamond, then the ring's white face, then its
    # black edge. The edge is 1 pt (about 1.5 px) wide, so where it falls
    # between pixel centres it is two pixels near gray 105, not one black
    # one: "dark" is under half white.
    reach = (ring['reach_pt'] + ring['edge_pt']) * k + 2
    for deg in range(0, 360, 5):
        grays = [gray(i / 4, deg) for i in range(int(reach * 4))]
        light = next((i for i, g in enumerate(grays) if g > 200), None)
        assert light is not None, (deg, grays)
        assert min(grays[light:]) < 128, \
            f"no ring edge outside the diamond at {deg} degrees: {grays}"


def test_marker_radius_follows_the_room():
    assert pv.marker_radius([]) == pv.R_MAX
    assert pv.marker_radius([(0, 0)]) == pv.R_MAX
    assert pv.marker_radius([(0, 0), (5, 0)]) == pv.R_MIN       # crowded
    assert pv.marker_radius([(0, 0), (100, 0)]) == pv.R_MAX     # sparse
    assert pv.marker_radius([(0, 0), (11, 0)]) == 5.0           # between
    assert pv.marker_radius([(0, 0), (100, 0), (106, 0)]) == pv.R_MIN, (
        "the tightest gap must govern")
    assert pv.R_MIN > 3, "the floor must still beat the old 3 px dots"


def test_smaller_markers_keep_the_old_reach_and_legend_place():
    # #401 drew the markers about 14 % smaller (4 -> 3.5, 7 -> 6). The
    # pointer's reach keeps the bounds they had before, so the reach did
    # not shrink with them, and the legend glyph keeps its place between
    # floor and ceiling.
    assert (pv.HOVER_R_MIN, pv.HOVER_R_MAX) == (4.0, 7.0), \
        "the hover reach must keep the pre-#401 radius bounds"
    assert pv.R_MIN < pv.HOVER_R_MIN and pv.R_MAX < pv.HOVER_R_MAX
    assert pv.R_MIN <= pv.R_LEGEND <= pv.R_MAX, pv.R_LEGEND


def test_real_profiles_size_their_markers_sensibly():
    box = (52, 42, 1240 - 14, 240 - 26)          # the tab's plot box

    def radius(p):
        return pv.marker_radius([(x, y) for x, y, s
                                 in pv.snapshot_points(p, *box)
                                 if s['step'] > 0])
    # the default 40-landing profile is crowded: floor, but no smaller
    assert radius(sp.SldeaProfile()) == pv.R_MIN
    # a five-landing sweep has room: markers grow to the ceiling
    assert radius(sp.SldeaProfile(end_kv=10, step_kv=2)) == pv.R_MAX


def test_warmup_and_baseline_do_not_pin_the_size():
    # They sit 2 s apart at 0 kV -- a small fraction of any landing gap,
    # and overlapping by design (the baseline is drawn on top). Counting
    # that gap would shrink every marker of a sparse run to the floor.
    p = sp.SldeaProfile(end_kv=10, step_kv=2)
    pts = pv.snapshot_points(p, 52, 42, 1226, 214)
    zero = [(x, y) for x, y, s in pts if s['step'] == 0]
    landing = [(x, y) for x, y, s in pts if s['step'] > 0]
    assert len(zero) == 2, zero
    tightest = min(math.dist(a, b) for a, b in zip(landing, landing[1:]))
    assert math.dist(*zero) < tightest / 4, (zero, tightest)
    assert pv.marker_radius([(x, y) for x, y, _s in pts]) == pv.R_MIN
    assert pv.marker_radius(landing) == pv.R_MAX


def test_snapshot_points_run_in_time_order_inside_the_box():
    p = sp.SldeaProfile(updown=True)
    pts = pv.snapshot_points(p, 10, 20, 510, 220)
    ts = [s['t'] for _x, _y, s in pts]
    assert ts == sorted(ts)
    assert len(pts) == len(p.snapshots)
    for x, y, s in pts:
        assert 10 <= x <= 510 and 20 <= y <= 220, (x, y, s)
    top = max(p.levels)
    assert min(y for _x, y, _s in pts) == 20      # the peak meets the top
    assert all(y == 220 for _x, y, s in pts if s['nominal_kv'] == 0)
    assert any(s['nominal_kv'] == top for _x, _y, s in pts)
    line = pv.staircase(p, 10, 20, 510, 220)
    assert len(line) == 4 * len(p.segments)


def test_marker_geometry_is_centred_and_scales():
    for shape in {m[0] for m in pv.MARKERS.values()}:
        spans = []
        for r in (pv.R_MIN, pv.R_MAX):
            kind, co = pv.marker_coords(shape, 100.0, 50.0, r)
            if kind == 'oval':
                cx, cy = (co[0] + co[2]) / 2, (co[1] + co[3]) / 2
            else:
                assert kind == 'polygon' and len(co) % 2 == 0
                cx = sum(co[0::2]) / (len(co) / 2)       # vertex mean =
                cy = sum(co[1::2]) / (len(co) / 2)       # the centroid here
            assert abs(cx - 100) < 1e-9 and abs(cy - 50) < 1e-9, (
                shape, cx, cy)
            spans.append(max(co[0::2]) - min(co[0::2]))
        assert spans[1] > spans[0], (shape, spans)
    try:
        pv.marker_coords('hexagon', 0, 0, 4)
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown shape must raise")


def test_hover_text_speaks_the_tabs_words():
    p = sp.SldeaProfile(end_kv=1.0, step_kv=0.5)          # landings 0.5, 1
    by = {(s['tag'], s['step']): s for s in p.snapshots}
    post1 = pv.describe(by[('post-ramp', 1)], p)
    for want in ('Post-ramp snapshot', 'landing 1/2', '0.5 kV',
                 '2 s after the ramp ends'):
        assert want in post1, (want, post1)
    assert 'rising' not in post1, "a single sweep needs no direction word"
    assert '1 s before the next ramp' in pv.describe(by[('pre-ramp', 1)], p)
    assert '1 s before the run ends' in pv.describe(by[('pre-ramp', 2)], p)
    base = pv.describe(by[('baseline', 0)], p)
    assert 'Baseline snapshot' in base and 'reference' in base
    warm = pv.describe(by[('warmup', 0)], p)
    assert 'warm-up' in warm and 'never used as the reference' in warm


def test_hover_text_names_the_direction_on_up_down_runs():
    # sequence 0.5, 1.0, 0.5 | 0.5, 1.0, 0.5 -- the lowest level is landed
    # twice in a row at the seam between the two cycles
    p = sp.SldeaProfile(end_kv=1.0, step_kv=0.5, updown=True, repeat=2)
    by = {(s['tag'], s['step']): s for s in p.snapshots}
    assert '(rising)' in pv.describe(by[('post-ramp', 2)], p)
    assert '(falling)' in pv.describe(by[('post-ramp', 3)], p)
    assert '(repeat starts)' in pv.describe(by[('post-ramp', 4)], p)
    assert 'landing 6/6' in pv.describe(by[('pre-ramp', 6)], p)


def test_legend_lists_only_what_the_profile_draws():
    assert pv.legend_tags(sp.SldeaProfile()) == [
        'warmup', 'baseline', 'post-ramp', 'pre-ramp']
    assert pv.legend_tags(sp.SldeaProfile(baseline_warmup_s=0)) == [
        'baseline', 'post-ramp', 'pre-ramp']
    assert pv.legend_tags(sp.SldeaProfile(
        end_kv=2, step_kv=1, snap_pre=False)) == [
        'warmup', 'baseline', 'post-ramp']


# ------------------------------------------------------------- on the tab

OLD_COLOURS = {'#2e7d32', '#c62828', '#1565c0'}     # green, red, the blue


class _Ev:
    def __init__(self, x, y):
        self.x, self.y = x, y


def _settle(root, n=8):
    import time
    for _ in range(n):
        root.update_idletasks()
        root.update()
        time.sleep(0.02)


def _app():
    """(root, app) with the SLDEA tab showing, or raise _Skip."""
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    import gui
    # No instrument hunt: irrelevant here, and it starts threads.
    gui.InstrumentControlGUI.auto_connect = lambda self: None
    app = gui.InstrumentControlGUI(root)
    root.geometry('1300x900')
    root.deiconify()
    assert app.select_manual_tab('sldea'), "cannot find the SLDEA tab"
    _settle(root, 12)
    app._sldea_refresh()
    _settle(root, 4)
    return root, app


def _canvas_mark(c, item):
    """(shape, fill, outline) of one canvas item, read as drawn."""
    return (_canvas_shape(c.type(item), [float(v) for v in c.coords(item)]),
            c.itemcget(item, 'fill').upper(),
            c.itemcget(item, 'outline').upper())


def _canvas_marks(c):
    """{tag: {(shape, fill, outline), ...}} over the preview's markers."""
    out = {}
    for item in c.find_withtag('marker'):
        tag = next(t[len('marker-'):] for t in c.gettags(item)
                   if t.startswith('marker-'))
        out.setdefault(tag, set()).add(_canvas_mark(c, item))
    return out


def _texts(widget):
    """Every Label text under `widget`, depth first."""
    out = []
    for child in widget.winfo_children():
        try:
            out.append(str(child.cget('text')))
        except Exception:
            pass
        out += _texts(child)
    return out


def test_the_timing_fields_sit_together_under_their_tags_names():
    root, app = _app()
    try:
        post = app.sldea_vars['settle_s']
        pre = app.sldea_vars['snap_lead_s']
        row = post.master
        assert pre.master is row, "the two timing fields are split apart"
        words = _texts(row)
        for want in ('Post-ramp', 's after the ramp ends', 'Pre-ramp',
                     's before the next ramp'):
            assert want in words, (want, words)
        assert 'Snapshots each landing:' in _texts(row.master)
        everywhere = _texts(root)
        assert not any(t.startswith(('Settle', 'Snap lead'))
                       for t in everywhere), "an old field name survives"
        # the moved fields still drive the schedule
        for e, val in ((post, '5'), (pre, '3')):
            e.delete(0, 'end')
            e.insert(0, val)
        app._sldea_refresh()
        assert app._sldea_profile.settle_s == 5.0
        assert app._sldea_profile.snap_lead_s == 3.0
    finally:
        root.destroy()


def test_the_canvas_draws_every_scheduled_snapshot_by_shape():
    root, app = _app()
    try:
        c = app.sldea_canvas
        p = app._sldea_profile
        for tag in pv.MARKERS:
            want = sum(1 for s in p.snapshots if s['tag'] == tag)
            got = len(c.find_withtag(f'marker-{tag}'))
            assert got == want, (tag, got, want)
        # ...each in its tag's shape, fill and black edge, read off the
        # items as drawn (#478)
        assert set(_canvas_marks(c)) == set(pv.legend_tags(p))
        for tag, marks in _canvas_marks(c).items():
            shape, fill, _label = pv.MARKERS[tag]
            assert marks == {(shape, fill.upper(), pv.OUTLINE)}, (tag, marks)
        # read the legend the way a person does: left to right on screen
        legend_items = sorted((i for i in c.find_withtag('legend')
                               if c.type(i) == 'text'),
                              key=lambda i: c.bbox(i)[0])
        legend = [c.itemcget(i, 'text') for i in legend_items]
        assert legend == [pv.MARKERS[t][2] for t in pv.legend_tags(p)], \
            legend
        glyphs = [_canvas_mark(c, i) for i in sorted(
            (i for i in c.find_withtag('legend') if c.type(i) != 'text'),
            key=lambda i: c.bbox(i)[0])]
        assert glyphs == [(pv.MARKERS[t][0], pv.MARKERS[t][1].upper(),
                           pv.OUTLINE) for t in pv.legend_tags(p)], glyphs
        # ...and it starts at the LEFT, which is always on screen: the tab
        # scrolls sideways when narrow, and a right-aligned legend was lost
        assert c.bbox(legend_items[0])[0] < c.winfo_width() / 4, \
            "legend is not anchored at the left"
        app._sldea_draw_cursor(p.total_duration_s / 3)
        cursor = c.find_withtag('cursor')
        assert cursor, "no playhead drawn"
        for i in cursor:
            assert c.itemcget(i, 'fill').upper() == pv.PLAYHEAD, \
                c.itemcget(i, 'fill')
        for i in c.find_all():
            for opt in ('fill', 'outline'):
                try:
                    val = c.itemcget(i, opt).lower()
                except Exception:
                    continue
                assert val not in OLD_COLOURS, (c.type(i), opt, val)
    finally:
        root.destroy()


def test_the_preview_and_the_area_plot_mark_each_tag_alike():
    # #478: the tab's preview and Edge Review's area_vs_voltage.png of the
    # same schedule, both read as drawn. With every frame accepted, the
    # area plot draws every tag the canvas does, the warm-up's open circle
    # included (owner, 2026-10-21), each in the canvas's shape, fill and
    # edge, and the two legends use the same words in the same order.
    root, app = _app()
    try:
        c = app.sldea_canvas
        p = app._sldea_profile
        on_canvas = _canvas_marks(c)
        legend_items = sorted((i for i in c.find_withtag('legend')
                               if c.type(i) == 'text'),
                              key=lambda i: c.bbox(i)[0])
        canvas_legend = [c.itemcget(i, 'text') for i in legend_items]
    finally:
        root.destroy()
    assert 'warmup' in on_canvas, "the tab's defaults no longer warm up"
    rows = [{'nominal_kV': f"{s['nominal_kv']:g}", 'tag': s['tag']}
            for s in p.snapshots]
    drawn, legend = _area_plot_marks(rows)
    by_label = {label: tag for tag, (_s, _f, label) in pv.MARKERS.items()}
    assert set(drawn) <= set(by_label), set(drawn) - set(by_label)
    in_plot = {by_label[label]: (m['shape'], m['fill'], m['edge'])
               for label, m in drawn.items()}
    assert set(in_plot) == set(on_canvas), (in_plot, on_canvas)
    for tag, mark in in_plot.items():
        assert on_canvas[tag] == {mark}, (tag, on_canvas[tag], mark)
    assert [text for text, _s, _f, _e in legend] == canvas_legend, \
        (legend, canvas_legend)


def test_hovering_a_marker_describes_it():
    root, app = _app()
    try:
        c = app.sldea_canvas
        x, y, _r, s = next(m for m in app._sldea_marks
                           if m[3]['tag'] == 'post-ramp')
        app._sldea_hover(_Ev(x, y))
        texts = [c.itemcget(i, 'text') for i in c.find_withtag('hover')
                 if c.type(i) == 'text']
        assert len(texts) == 1 and 'Post-ramp snapshot' in texts[0], texts
        assert f"landing {s['step']}/" in texts[0], texts
        # the warm-up and the baseline overlap at 0 kV: both are listed
        x0, y0, _r, _s = next(m for m in app._sldea_marks
                              if m[3]['tag'] == 'baseline')
        app._sldea_hover(_Ev(x0, y0))
        both = "\n".join(c.itemcget(i, 'text') for i in
                         c.find_withtag('hover') if c.type(i) == 'text')
        assert 'Baseline' in both and 'warm-up' in both, both
        app._sldea_hover(_Ev(3, 3))                    # empty corner
        assert not c.find_withtag('hover')
    finally:
        root.destroy()


def test_smaller_markers_are_hovered_from_as_far_as_before():
    # #401 drew the markers smaller, but a pointer the old reach found
    # (the pre-#401 radius plus 3 px) must still find the marker.
    root, app = _app()
    try:
        for key, val in (('end_kv', '10'), ('step_kv', '2')):    # sparse
            e = app.sldea_vars[key]
            e.delete(0, 'end')
            e.insert(0, val)
        app._sldea_refresh()
        _settle(root, 4)
        c = app.sldea_canvas
        p = app._sldea_profile
        k = app._sldea_ui_scale()
        x, y, r, s = next(m for m in app._sldea_marks
                          if m[3]['tag'] == 'post-ramp')
        assert r == pv.R_MAX * k, (r, k)            # sparse: the ceiling
        reach = pv.HOVER_R_MAX * k + 3
        assert r + 3 < reach - 0.5, "the drawn marker did not shrink"
        head = pv.describe(s, p).splitlines()[0]

        def shown(px, py):
            app._sldea_hover(_Ev(px, py))
            return "\n".join(c.itemcget(i, 'text')
                             for i in c.find_withtag('hover')
                             if c.type(i) == 'text')
        # to the left: the ramp up to this landing, with no marker near it
        assert head in shown(x - (reach - 0.5), y), \
            "a pointer the old reach found now misses the marker"
        assert head not in shown(x - (reach + 1.5), y), \
            "the reach grew past the old one"
    finally:
        root.destroy()


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    ran = skipped = 0
    failed = []
    for n in names:
        try:
            globals()[n]()
        except _Skip as why:
            skipped += 1
            print('skip', n, f'({why})')
            continue
        except Exception:
            # A test that blew up still RAN -- only a skip is "did not run".
            ran += 1
            failed.append((n, traceback.format_exc()))
            print('FAIL', n)
            continue
        ran += 1
        print('ok ', n)
    tail = f"{ran} of {len(names)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped, no display)"
    print(tail)
    if not failed:
        return 0
    head = f"{len(failed)} of {len(names)} tests failed"
    print(f"\n{head}")
    for name, tb in failed:
        print(f"===== FAIL {name} =====")
        print(tb.rstrip('\n'))
    print(f"===== end {head} =====")
    return 1


if __name__ == '__main__':
    raise SystemExit(_run())
