#!/usr/bin/env python3
"""The SLDEA tools around Edge Review's candidate card draw in Tol colors.

#450 moved Edge Review's candidate colors A/B/C/D to Paul Tol's. What these
pin down for everything else that still drew in Material colors or in
matplotlib's default cycle (#454, 2026-10-19):

  * every color the tuner, the diagnostic, Edge Review's calibration
    dialog, hand tracer, area plot and overlay export, and the camera
    pre-flight's reticle draw with is from Paul Tol's schemes;
  * colors that share a view and carry meaning stay apart under simulated
    color blindness: worst-case CIEDE2000 over normal and Machado-2009
    deutan, protan and tritan vision >= 18, with the simulator and floor
    of tests/test_sldea_preview.py. The set each one replaced is held to
    the same bar and must FAIL it, so the check is one that can fail;
  * each line stands off what it is drawn on by 3:1 (WCAG 2.1 SC 1.4.11),
    or sits on a dark halo where it does not;
  * the calibration dialog and the tracer are where an operator places
    points on the edge, and `#215` measured that a wider stroke there moves
    hand placement (+2.07 % diameter at 3 px). So their widths, dashes and
    halos are pinned here at the values those measurements were made with;
    only the colors changed;
  * drawings no test had looked at (#476): the contact sheet's foil
    outline, the two-point calibration's chord, and the pre-flight
    dialog's own call of the reticle, which is now one reticle with the
    live view's, white on a black halo;
  * the Webcam tab's focus circle (#482), which was still Tol cyan: it
    now wears the reticle's white on a black halo, drawn by the same
    code, and the focus score is still taken before it is drawn.

The cases that open a Tk window are skipped, and counted as skipped, when
there is no display.

Run: .venv/bin/python tests/test_sldea_tol_colors.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import itertools
import os
import shutil
import tempfile
import types

import numpy as np

import test_sldea_preview as cvd


class _Skip(Exception):
    """The test could not run here (no display): reported, not passed."""


# Paul Tol, "Colour Schemes", SRON/EPS/TN/09-002, issue 3.2 (2021): the
# muted and medium-contrast qualitative schemes, beside the bright and
# high-contrast ones tests/test_sldea_preview.py already lists. sldea_plot
# draws group means from both (#373).
TOL_MUTED = {'#CC6677', '#332288', '#DDCC77', '#117733', '#88CCEE',
             '#882255', '#44AA99', '#999933', '#AA4499', '#DDDDDD'}
TOL_MEDIUM_CONTRAST = {'#FFFFFF', '#EECC66', '#EE99AA', '#6699CC',
                       '#997700', '#994455', '#004488', '#000000'}
TOL = cvd.TOL | TOL_MUTED | TOL_MEDIUM_CONTRAST

# The candidate colors #450 gives Edge Review's A, B and C, and the
# Material ones main had before it. The tracer draws A, B and C's colors
# beside its own, so its own colors must clear the floor against both:
# this branch and #450 can land in either order.
TOL_ABC = ['#66CCEE', '#4477AA', '#CCBB44']
MATERIAL_ABC = ['#00c853', '#2196f3', '#ff9100']

# The membrane on the manual's Edge Review frame (run P3_6_2.5mL_20260729,
# measured off the committed manual's shot on 2026-10-19): median gray
# 147 of the frame area, 5th to 95th percentile 106 to 167.
MEMBRANE = '#939393'
WHITE_FACE = '#FFFFFF'


def _up(colors):
    return {c.upper() for c in colors}


def _lum(hex_color):
    h = hex_color.lstrip('#')
    r, g, b = (cvd._lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(hex1, hex2):
    """WCAG contrast ratio between two sRGB colors."""
    hi, lo = sorted((_lum(hex1), _lum(hex2)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _gray(level):
    return '#%02X%02X%02X' % (level, level, level)


def _worst(palette):
    """(worst-case CIEDE2000, a, b) over every pair in `palette`."""
    return min((cvd._worst_de(a, b), a, b)
               for a, b in itertools.combinations(palette, 2))


def _worst_against(own, others):
    """Worst pair with at least one member in `own`: the pairs among
    `others` alone are someone else's to keep apart."""
    pairs = list(itertools.combinations(own, 2)) + [
        (a, b) for a in own for b in others]
    return min((cvd._worst_de(a, b), a, b) for a, b in pairs)


def _tk_root():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    root.withdraw()
    return root


def _items(cv, tag='all'):
    """Every drawn item on a Tk canvas as a dict: its type, its color(s),
    width and dash. Images carry no color and are left out."""
    out = []
    for i in cv.find_withtag(tag):
        kind = cv.type(i)
        if kind == 'image':
            continue
        it = {'kind': kind, 'coords': [float(v) for v in cv.coords(i)],
              'fill': cv.itemcget(i, 'fill').upper(),
              'width': float(cv.itemcget(i, 'width') or 0),
              'dash': tuple(int(x) for x in
                            cv.itemcget(i, 'dash').split() if x)}
        if kind != 'line' and kind != 'text':
            it['outline'] = cv.itemcget(i, 'outline').upper()
        out.append(it)
    return out


def _colors(items):
    return {c for it in items for c in (it.get('fill'), it.get('outline'))
            if c}


# ---------------------------------------------------------------- headless

def test_tuner_candidates_are_tol_cyan_blue_yellow_and_survive_cvd():
    """Best, 2nd and 3rd outline in the tuner: the colors Edge Review gives
    A, B and C (#450), at worst-case CIEDE2000 24.35. The Material set
    they replace fails the same bar (9.15, #00e676 vs #40c4ff, tritan).
    Alone on the membrane the three come to 1.5-1.7:1, which is why each
    runs on a black halo: every color stands off the halo by 3:1."""
    import sldea_tuner as st
    cols = list(st.PANEL_COLORS)
    assert cols == TOL_ABC, cols
    assert not _up(cols + [st.PANEL_HALO]) - TOL, cols
    de, a, b = _worst(cols)
    assert de >= cvd.CVD_FLOOR, (round(de, 3), a, b)
    assert de >= 24.34, (round(de, 3), a, b)   # the comment's 24.35
    old, oa, ob = _worst(['#00e676', '#40c4ff', '#ff9100'])
    assert old < cvd.CVD_FLOOR, old
    assert {oa, ob} == {'#00e676', '#40c4ff'} and 9.0 < old < 9.3, \
        (round(old, 3), oa, ob)
    for c in cols:
        assert _contrast(c, MEMBRANE) < 3.0, (c, _contrast(c, MEMBRANE))
        assert _contrast(c, st.PANEL_HALO) >= 3.0, c
    assert _contrast(st.PANEL_HALO, MEMBRANE) >= 3.0
    # the cue that needs no color: three different line styles
    assert len(set(st.PANEL_STYLES)) == len(st.PANEL_STYLES) == len(cols)


def test_the_diagnostic_copies_the_tuners_outline_palette():
    """sldea_diag may not import sldea_tuner (Tk font workaround), so it
    holds a copy; the copies must not drift apart."""
    import sldea_diag as sd
    import sldea_tuner as st
    assert sd.SHEET_COLORS == st.PANEL_COLORS
    assert sd.SHEET_STYLES == st.PANEL_STYLES
    assert sd.SHEET_HALO == st.PANEL_HALO


def test_diag_baseline_panel_disc_and_foil_are_white_and_black():
    """The contact sheet's baseline panel: resting disc and foil footprint.
    The Material pair they replace was 11.71 apart (deutan) and reached
    1.84 and 1.36:1 on the membrane; white and black need no halo."""
    import sldea_diag as sd
    pair = [sd.SHEET_DISC, sd.SHEET_FOIL]
    assert not _up(pair) - TOL, pair
    assert cvd._worst_de(*pair) >= cvd.CVD_FLOOR
    old = cvd._worst_de('#ff9100', '#00e676')
    assert old < cvd.CVD_FLOOR and 11.5 < old < 11.9, old
    for c in pair:
        assert _contrast(c, MEMBRANE) >= 3.0, (c, _contrast(c, MEMBRANE))


def test_diag_figure_lines_are_tol_medium_contrast_and_survive_cvd():
    """The diagnostic figure's line plots: Tol medium-contrast dark blue,
    light blue, dark yellow and black, worst-case CIEDE2000 27.81, each
    3:1 on the white plot face. matplotlib's default cycle they replace
    has orange and green at 1.25 under protanopia. The twin axis's grey
    stays 18 from every line, and the reference lines are the one black
    the energy plot's data lines do not wear."""
    import sldea_diag as sd
    lines = list(sd.DIAG_LINES)
    assert not _up(lines + [sd.DIAG_REF, '#BBBBBB']) - TOL, lines
    de, a, b = _worst(lines)
    assert de >= cvd.CVD_FLOOR and de >= 27.80, (round(de, 3), a, b)
    old, oa, ob = _worst(['#1f77b4', '#ff7f0e', '#2ca02c', '#d81b60'])
    assert old < cvd.CVD_FLOOR and old < 2.0, (round(old, 3), oa, ob)
    for c in lines:
        assert _contrast(c, WHITE_FACE) >= 3.0, (c, _contrast(c, WHITE_FACE))
    for c in lines:
        assert cvd._worst_de('#BBBBBB', c) >= cvd.CVD_FLOOR, c
    assert sd.DIAG_REF == lines[3]
    assert len(set(sd.DIAG_MARKERS)) == len(sd.DIAG_MARKERS) >= 3


def test_calibration_white_reads_on_the_stretched_disc_and_black_on_paper():
    """The calibration dialog draws one color plus black, so no pair has
    to stay apart; what matters is contrast on what it is drawn over. The
    display is stretched (cal_stretch_window): on the P3 baseline its
    docstring names (disc 166, paper 186) the disc shows near gray 60 and
    the paper near 195. White stands off the disc by 3:1 and more, the
    black halo off the paper; the green they replace stood off the paper
    at 1.06:1 and off raw gray 147 at 1.84:1."""
    import sldea_edge_gui as gui
    assert not _up([gui.CAL_INK, gui.CAL_HALO]) - TOL
    lut = gui.cal_stretch_lut(*gui.cal_stretch_window(166, 186))
    disc, paper = _gray(lut[166]), _gray(lut[186])
    assert _contrast(gui.CAL_INK, disc) >= 10.0, _contrast(gui.CAL_INK, disc)
    assert _contrast(gui.CAL_HALO, paper) >= 10.0
    assert _contrast(gui.CAL_INK, gui.CAL_HALO) >= 3.0
    assert _contrast(gui.CAL_INK, MEMBRANE) >= 3.0
    assert _contrast('#00e676', paper) < 1.1
    assert _contrast('#00e676', MEMBRANE) < 3.0


def test_tracer_colors_are_tol_and_clear_the_floor_beside_either_abc():
    """The tracer's trace (white), previous outline (indigo) and resting
    disc (black), beside the candidate overlays it draws in A, B and C's
    colors: worst pair 19.14 beside #450's Tol A/B/C, 21.33 beside the
    Material ones, and no worse beside whatever this checkout holds.
    The tracer's old colors fail on their own (8.04, trace vs rubber
    band, tritan). Each new color reaches 3:1 at the membrane's median;
    a halo is not allowed in this window, so that is the bar."""
    import sldea_edge_gui as gui
    own = [gui.TRACE_INK, gui.TRACE_PREV, gui.TRACE_REST]
    assert not _up(own + [gui.TRACE_FACE]) - TOL, own
    for abc, floor in ((TOL_ABC, 19.14), (MATERIAL_ABC, 21.32),
                       (list(gui.CAND_COLORS[:gui.TRACE_SLOT]), 19.14)):
        de, a, b = _worst_against(own, abc)
        assert de >= cvd.CVD_FLOOR and de >= floor, (abc, round(de, 3), a, b)
    old, oa, ob = _worst(['#00e676', '#80cbc4', '#b39ddb', '#888888'])
    assert old < cvd.CVD_FLOOR, old
    assert {oa, ob} == {'#00e676', '#80cbc4'} and 7.9 < old < 8.2, \
        (round(old, 3), oa, ob)
    for c in own:
        assert _contrast(c, MEMBRANE) >= 3.0, (c, _contrast(c, MEMBRANE))
    for c in ('#00e676', '#80cbc4', '#b39ddb', '#888888'):
        assert _contrast(c, MEMBRANE) < 2.0, c
    # the rings' face sits inside a white ring: they must stand apart
    assert _contrast(gui.TRACE_INK, gui.TRACE_FACE) >= 3.0


def _blend(hex_color, alpha, under='#FFFFFF'):
    """`hex_color` drawn at `alpha` over `under`, as the eye gets it."""
    a, b = hex_color.lstrip('#'), under.lstrip('#')
    return '#' + ''.join(
        '%02X' % round(alpha * int(a[i:i + 2], 16)
                       + (1 - alpha) * int(b[i:i + 2], 16))
        for i in (0, 2, 4))


def test_area_plot_tags_wear_the_preview_colors_on_black_edges():
    """Save's area_vs_voltage.png, as it draws it: the warm-up's Tol
    high-contrast white face (shown since the owner's call of
    2026-10-21), baseline Tol high-contrast red, post-ramp Tol bright
    blue and pre-ramp Tol bright yellow, the SLDEA tab preview's fills
    (#478; the baseline was black before), each opaque on a black edge.
    Measured on the drawn artists: the four fills are 21.36 apart at
    worst (baseline vs post-ramp, under the simulator's four visions;
    white is 22.74 from yellow, its nearest) and 31.5 or more from the
    black edge. Red and blue reach 4.56 and 4.70:1 on the white face;
    yellow reaches only 1.95:1 and the white face 1:1, so the black edge
    (21:1, and 16.98:1 on the grid's light gray) is what carries them,
    as on the canvas. At the 0.8
    alpha the plot drew with before #478, red and blue would blend to
    16.45 apart and fail the floor, so opacity is held here too.
    matplotlib's default cycle the plot used before #454 put pre-ramp
    orange and baseline green 1.25 apart (protan)."""
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import colors as mcolors
    from matplotlib.figure import Figure
    import sldea_edge_gui as gui
    d = tempfile.mkdtemp(prefix='tol_area_plot_')
    seen = []
    grids = []
    real = Figure.savefig

    def spy(fig, *a, **k):
        for ax in fig.axes:
            seen.extend((ln.get_label(),
                         mcolors.to_hex(ln.get_markerfacecolor()).upper(),
                         mcolors.to_hex(ln.get_markeredgecolor()).upper(),
                         ln.get_alpha(), ln.get_marker(),
                         ln.get_markeredgewidth())
                        for ln in ax.lines)
            grids.extend(
                (mcolors.to_hex(g.get_color()).upper(), g.get_alpha())
                for g in ax.get_xgridlines() + ax.get_ygridlines()
                if g.get_visible())
            seen.append(('face', mcolors.to_hex(ax.get_facecolor()).upper(),
                         None, None, None, None))
        return real(fig, *a, **k)
    Figure.savefig = spy
    try:
        stub = types.SimpleNamespace(
            rundir=d,
            results={0: {'area_px': 201.0}, 1: {'area_px': 200.0},
                     2: {'area_px': 260.0}, 3: {'area_px': 255.0}},
            run={'rows': [{'nominal_kV': '0', 'tag': 'warmup'},
                          {'nominal_kV': '0', 'tag': 'baseline'},
                          {'nominal_kV': '1', 'tag': 'post-ramp'},
                          {'nominal_kV': '1', 'tag': 'pre-ramp'}]})
        gui.EdgeReviewApp._save_plot(stub, None)
        assert os.path.exists(os.path.join(d, 'area_vs_voltage.png'))
    finally:
        Figure.savefig = real
        shutil.rmtree(d, ignore_errors=True)
    face = next(f for label, f, _e, _a, _m, _w in seen if label == 'face')
    by = {label: (fill, edge, alpha, mk, width)
          for label, fill, edge, alpha, mk, width in seen if label != 'face'}
    assert set(by) == {'warm-up', 'baseline 0 kV', 'post-ramp',
                       'pre-ramp'}, seen
    assert by['warm-up'][0] == '#FFFFFF', by
    assert by['baseline 0 kV'][0] == '#BB5566', by
    assert by['post-ramp'][0] == '#4477AA' and by['pre-ramp'][0] == '#CCBB44'
    fills = [v[0] for v in by.values()]
    assert not _up(fills + [face]) - TOL, (fills, face)
    de, a, b = _worst(fills)
    assert de >= cvd.CVD_FLOOR, (round(de, 3), a, b)
    assert 21.3 < de < 21.4 and {a, b} == {'#BB5566', '#4477AA'}, \
        (round(de, 3), a, b)
    assert {v[1] for v in by.values()} == {'#000000'}, by
    edge_de, _a, _b = _worst_against(['#000000'], fills)
    assert edge_de >= 31.5, round(edge_de, 3)
    # opaque: an alpha would draw tints that are not Tol's colors, and at
    # the old 0.8 the red and the blue fall under the floor
    assert {v[2] for v in by.values()} <= {None, 1.0}, by
    tinted = cvd._worst_de(_blend('#BB5566', 0.8), _blend('#4477AA', 0.8))
    assert tinted < cvd.CVD_FLOOR and 16.4 < tinted < 16.5, tinted
    # every mark stands off the face by 3:1, or its edge does, and the
    # edge also stands off the grid lines the marks sit on
    assert face == WHITE_FACE, face
    assert grids, "the plot drew no grid"
    unders = [face] + [_blend(g, 1.0 if alpha is None else alpha, face)
                       for g, alpha in grids]
    for label, (fill, edge, _alpha, _mk, width) in by.items():
        assert width > 0, (label, width)
        for under in unders:
            assert _contrast(fill, under) >= 3.0 or \
                _contrast(edge, under) >= 3.0, (label, fill, edge, under)
    assert _contrast('#CCBB44', face) < 3.0       # why the edge matters
    assert _contrast('#FFFFFF', face) < 3.0       # the warm-up's face too
    assert len({v[3] for v in by.values()}) == 4, by
    old = cvd._worst_de('#ff7f0e', '#2ca02c')
    assert old < cvd.CVD_FLOOR, old


def test_tuner_render_draws_every_halo_before_any_color_and_best_on_top():
    """sldea_tuner.render on three overlapping outlines: one black halo per
    outline, 2 pt wider, under every colored line (zorder), then the
    colors with the best drawn last, solid / dashed / dotted. A halo drawn
    with its own line would black out a neighbour's color where two
    outlines run close (#450 measured 553 px of it on the card)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import sldea_tuner as st
    sq = [[100, 60], [220, 60], [220, 180], [100, 180]]
    cands = [{'contour': np.array(sq) + k, 'method': m, 'area_px': 14400.0,
              'solidity': 1.0, 'conf': 0.9, 'wrinkle': 0.0,
              'spread_pct': 0.0}
             for k, m in enumerate(('disc-fit', 'diff-hi', 'diff-lo'))]
    panel = {'gray': np.full((240, 320), 147, np.uint8), 'label': 'mid-run',
             'row': {'nominal_kV': '3'}}
    fig, ax = plt.subplots()
    try:
        st.render(ax, panel, cands, None)
        st.render(ax, panel, cands, None)          # a live re-render
        lines = list(ax.lines)
        assert len(lines) == 6, len(lines)         # nothing left behind
        halos = [ln for ln in lines if ln.get_color() == st.PANEL_HALO]
        inks = [ln for ln in lines if ln.get_color() != st.PANEL_HALO]
        assert len(halos) == len(inks) == 3
        assert max(h.get_zorder() for h in halos) < \
            min(i.get_zorder() for i in inks)
        assert [i.get_color() for i in inks] == st.PANEL_COLORS[::-1]
        assert [i.get_linestyle() for i in inks] == [':', '--', '-'], \
            [i.get_linestyle() for i in inks]
        widths = {i.get_color(): i.get_linewidth() for i in inks}
        assert widths[st.PANEL_COLORS[0]] == 2.0
        assert sorted(h.get_linewidth() for h in halos) == [3.0, 3.0, 4.0]
        fills = list(ax.patches)
        assert len(fills) == 1, fills
        rgb = fills[0].get_facecolor()[:3]
        want = tuple(int(st.PANEL_COLORS[0][i:i + 2], 16) / 255
                     for i in (1, 3, 5))
        assert np.allclose(rgb, want), (rgb, want)
    finally:
        plt.close(fig)


def test_diag_contact_sheet_draws_only_tol_colors():
    """sldea_diag.contact_sheet on Edge Review's synthetic run (it has a
    resting disc baseline_disc can fit): every line it draws wears a Tol
    color, the baseline panel shows the white disc, and the candidate
    panels the tuner's colors on black halos drawn under them."""
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    import sldea_diag as sd
    import test_sldea_edge_gui as edge
    d = tempfile.mkdtemp(prefix='tol_contact_')
    seen = []
    real = Figure.savefig

    def spy(fig, *a, **k):
        for ax in fig.axes:
            for ln in ax.lines:
                seen.append((ax.get_title(loc='left'),
                             str(ln.get_color()).upper(),
                             ln.get_linestyle(), ln.get_zorder()))
        return real(fig, *a, **k)
    Figure.savefig = spy
    try:
        run = edge._fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        sd.contact_sheet(run, os.path.join(d, 'sheet.png'), count=3)
    finally:
        Figure.savefig = real
        shutil.rmtree(d, ignore_errors=True)
    assert seen, "the contact sheet drew no lines"
    colors = {c for _t, c, _s, _z in seen}
    assert not colors - TOL, colors - TOL
    base = [(c, s) for t, c, s, _z in seen if t.startswith('baseline')]
    assert (sd.SHEET_DISC, '-') in base, base
    cand = [(c, s, z) for t, c, s, z in seen if not t.startswith('baseline')]
    assert any(c == sd.SHEET_COLORS[0] and s == '-' for c, s, _z in cand), \
        cand
    halos = [z for c, _s, z in cand if c == sd.SHEET_HALO]
    inks = [z for c, _s, z in cand if c != sd.SHEET_HALO]
    assert halos and inks and max(halos) < min(inks), (halos, inks)


def _foil_run(d):
    """Edge Review's synthetic run with two crinkled electrode strips
    beside the disc on every frame, and the strips' mask. The plain run
    has no foil: sldea_edge.foil_mask's thickness gate drops a sharp disc
    rim, and nothing else in it has texture. Two strips of 70 x 80 px of
    noise (sigma 40 gray levels) are kept whole; at 70 x 60 px they were
    not kept at all."""
    import cv2
    import test_sldea_edge_gui as edge
    run = edge._fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
    yy, xx = np.mgrid[0:240, 0:320]
    strips = ((((xx >= 4) & (xx < 74)) | ((xx >= 246) & (xx < 316)))
              & (yy >= 80) & (yy < 160))
    tex = 180 + np.random.default_rng(1).normal(0, 40, int(strips.sum()))
    frames = os.path.join(run, 'frames')
    for fn in os.listdir(frames):
        p = os.path.join(frames, fn)
        g = cv2.imread(p, cv2.IMREAD_GRAYSCALE).astype(float)
        g[strips] = tex
        cv2.imwrite(p, np.clip(g, 0, 255).astype(np.uint8))
    return run, strips


def test_diag_contact_sheet_draws_the_foil_black_dashed_thin():
    """The contact sheet's foil footprint, which the synthetic run never
    showed (#476). On a run whose baseline has two foil strips, the
    baseline panel outlines each one in Tol black, dashed, 0.9 pt wide,
    beside the resting disc's solid white 2 pt line: thin and dashed, so
    the footprint never reads as the disc."""
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    import sldea_diag as sd
    import sldea_edge as se
    assert sd.SHEET_FOIL == '#000000', sd.SHEET_FOIL
    d = tempfile.mkdtemp(prefix='tol_foil_')
    seen = []
    real = Figure.savefig

    def spy(fig, *a, **k):
        for ax in fig.axes:
            if not ax.get_title(loc='left').startswith('baseline'):
                continue
            for ln in ax.lines:
                seen.append((str(ln.get_color()).upper(), ln.get_linestyle(),
                             float(ln.get_linewidth()),
                             np.asarray(ln.get_xdata(), float),
                             np.asarray(ln.get_ydata(), float)))
        return real(fig, *a, **k)
    Figure.savefig = spy
    try:
        run, strips = _foil_run(d)
        rows = se.load_run(run)
        base = se.load_gray(se.frame_path(rows, rows['rows'][0]))
        foil = se.foil_mask(base)
        assert foil is not None and (foil & strips).sum() >= \
            0.9 * strips.sum(), "the strips were not taken for foil"
        sd.contact_sheet(run, os.path.join(d, 'sheet.png'), count=3)
    finally:
        Figure.savefig = real
        shutil.rmtree(d, ignore_errors=True)
    disc = [s for s in seen if s[:3] == (sd.SHEET_DISC, '-', 2.0)]
    footprint = [s for s in seen if s[:3] != (sd.SHEET_DISC, '-', 2.0)]
    assert len(disc) == 1, [s[:3] for s in seen]
    assert len(footprint) >= 2, [s[:3] for s in seen]
    assert {s[:3] for s in footprint} == {('#000000', '--', 0.9)}, \
        {s[:3] for s in footprint}
    # each strip has an outline drawn around it, not merely somewhere
    left = np.mgrid[0:240, 0:320][1] < 160
    for side in (left, ~left):
        ys, xs = np.nonzero(strips & side)
        assert any(x.min() <= xs.min() and x.max() >= xs.max()
                   and y.min() <= ys.min() and y.max() >= ys.max()
                   for _c, _s, _w, x, y in footprint), \
            (xs.min(), xs.max(), ys.min(), ys.max())


def test_diag_figure_draws_only_tol_colors():
    """sldea_diag.figure on the self-test's expanding run (the manual's
    31_diag_selftest): every line, including the 1 sigma and the
    identical-frame floor, wears a Tol color."""
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    import sldea_diag as sd
    d = tempfile.mkdtemp(prefix='tol_diag_fig_')
    seen = []
    real = Figure.savefig

    def spy(fig, *a, **k):
        for ax in fig.axes:
            seen.extend(str(ln.get_color()).upper() for ln in ax.lines)
        return real(fig, *a, **k)
    Figure.savefig = spy
    try:
        run = sd._synth_run(os.path.join(d, 'SLDEA_expand'), 'expand')
        rep = sd.analyze(run)
        sd.figure(rep, os.path.join(d, 'diag.png'), rundir=run)
    finally:
        Figure.savefig = real
        shutil.rmtree(d, ignore_errors=True)
    assert len(seen) >= 8, seen
    assert not set(seen) - TOL, set(seen) - TOL


def test_overlay_export_draws_a_black_2px_outline():
    """Save's overlays/: one outline per accepted frame, Tol black at the
    same 2 px the green had, on the frame's own pixels."""
    import cv2
    import sldea_edge as se
    import sldea_edge_gui as gui
    import test_sldea_edge_gui as edge
    d = tempfile.mkdtemp(prefix='tol_overlays_')
    try:
        rundir = edge._fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        run = se.load_run(rundir)
        sq = np.array([[40, 40], [120, 40], [120, 120], [40, 120]])
        stub = types.SimpleNamespace(rundir=rundir, run=run,
                                     results={1: {'contour': sq}})
        gui.EdgeReviewApp._save_overlays(stub)
        name = run['rows'][1]['frame_file']
        img = cv2.imread(os.path.join(rundir, 'overlays', name))
        src = cv2.imread(se.frame_path(run, run['rows'][1]))
        assert img is not None and src is not None
        row = img[80, 30:52].astype(int)          # across the left edge
        black = [k for k, px in enumerate(row) if not px.any()]
        assert black, row
        assert 2 <= len(black) <= 3, black        # a 2 px line, no wider
        assert (img[80, 30] == src[80, 30]).all()  # the frame beyond it
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_preflight_reticle_is_white_on_a_black_halo():
    """The camera pre-flight's reticle: a white cross and circle, each on
    a black halo 1 px wider on each side, on the frame. Across the
    vertical line near the top the pixels read frame, black, white, black,
    frame. Where the two lines cross, both stay white: every halo goes
    down before any white, so one line's halo never cuts the other.

    The live view draws the same reticle (#476), so its colors are pinned
    here as values: on the membrane's gray 147 the white alone stands off
    by 3.07:1, and Tol cyan, the live view's color before, by 1.67:1."""
    from PIL import Image
    import gui
    import sldea_liveview as lv
    assert (lv.RETICLE_INK, lv.RETICLE_HALO) == ('#FFFFFF', '#000000')
    assert _contrast(lv.RETICLE_INK, MEMBRANE) >= 3.0
    assert _contrast(lv.TOL_CYAN, MEMBRANE) < 3.0
    assert _contrast(lv.RETICLE_HALO, MEMBRANE) >= 3.0
    img = Image.new('RGB', (520, 292), (147, 147, 147))
    gui.draw_preflight_reticle(img)
    a = np.asarray(img).astype(int)
    cx, cy = 260, 146
    y = 30                                    # off the circle and the cross

    def kind(px):
        px = tuple(px)
        return 'W' if px == (255, 255, 255) else \
            'K' if px == (0, 0, 0) else 'F'
    row = ''.join(kind(a[y, x]) for x in range(cx - 3, cx + 4))
    assert row in ('FFKWKFF', 'FKKWKFF', 'FFKWKKF'), row
    cross = ''.join(kind(a[yy, cx]) for yy in (cy - 1, cy, cy + 1)) + \
        ''.join(kind(a[cy, xx]) for xx in (cx - 1, cx + 1))
    assert cross == 'WWWWW', cross
    # The circle, off the cross: down each column 40 and 60 px either side
    # of the centre, across the top and the bottom arc, the frame meets
    # black, then at least 2 px of white, then black again. A halo all on
    # one side of the ring (the live view's before #476) or a 1 px ring
    # fails here.
    import re
    r = 292 * 0.32
    for dx in (-60, -40, 40, 60):
        for side in (-1, 1):
            yc = int(round(cy + side * (r * r - dx * dx) ** 0.5))
            col = ''.join(kind(a[yy, cx + dx])
                          for yy in range(yc - 8, yc + 9))
            assert re.fullmatch(r'F+K+W{2,}K+F+', col), (dx, side, col)
    colors = {tuple(px) for px in a.reshape(-1, 3)}
    assert colors <= {(147, 147, 147), (0, 0, 0), (255, 255, 255)}, \
        colors - {(147, 147, 147), (0, 0, 0), (255, 255, 255)}


def test_the_live_view_draws_the_preflights_reticle():
    """#476: the live view drew the pre-flight's reticle in Tol cyan, and
    its circle's halo lay all inside the ring (the box was not grown to
    center it). It now draws the very same reticle: on the same picture,
    the live view's frame below its banner is the pre-flight's, pixel
    for pixel."""
    from PIL import Image
    import gui
    import sldea_liveview as lv
    thumb = np.full((270, 480, 3), 147, np.uint8)
    pre = Image.fromarray(thumb.copy())
    gui.draw_preflight_reticle(pre)
    live = lv.render(thumb, 'live')
    a, b = np.asarray(pre), np.asarray(live)
    assert a.shape == b.shape, (a.shape, b.shape)
    band = 25                       # the banner covers rows 0 to 24
    assert (a[band:] != 147).any(), "no reticle was drawn"
    diff = np.argwhere((a[band:] != b[band:]).any(axis=2))
    assert not len(diff), f"{len(diff)} pixels differ, first {diff[:3]}"


def test_the_webcam_focus_circle_is_the_reticles_white_on_a_black_halo():
    """#482: the Webcam tab's focus circle, its center cross and its score
    label drew in Tol cyan (Edge Review's candidate A, 1.67:1 on the
    membrane's gray 147) over a black under-stroke that lay all inside
    the ring. They now wear the reticle's RETICLE_INK on RETICLE_HALO,
    the halo 1 px wider on each side, with the circle's own geometry: a
    3 px ring of FOCUS_AOI_RADIUS_FRAC x the shorter side, a 13 px cross.

    Across the ring at the right, on the centre row, the pixels read
    frame, black, 3 white, black, frame. Every pixel of the picture is a
    gray (r = g = b), so no cyan is left anywhere, label included."""
    import re
    from PIL import Image
    import gui
    import sldea_liveview as lv
    import webcam
    img = Image.new('RGB', (640, 480), (147, 147, 147))
    height = gui.draw_focus_overlay(img, 1234)
    a = np.asarray(img).astype(int)
    cx, cy = 320, 240
    r = int(webcam.FOCUS_AOI_RADIUS_FRAC * 480)
    ink = tuple(int(lv.RETICLE_INK[i:i + 2], 16) for i in (1, 3, 5))
    halo = tuple(int(lv.RETICLE_HALO[i:i + 2], 16) for i in (1, 3, 5))
    assert (ink, halo) == ((255, 255, 255), (0, 0, 0))

    def kind(px):
        px = tuple(px)
        return 'W' if px == ink else 'K' if px == halo else \
            'F' if px == (147, 147, 147) else '?'
    for x0, step in ((cx + r - 10, 1), (cx - r + 10, -1)):
        row = ''.join(kind(a[cy, x0 + step * k]) for k in range(16))
        assert re.fullmatch(r'F+KWWWKF+', row), (step, row)
    col = ''.join(kind(a[yy, cx]) for yy in range(cy + r - 10, cy + r + 6))
    assert re.fullmatch(r'F+KWWWKF+', col), col
    # the cross: white through the centre, black beside it, frame beyond
    assert all(kind(a[cy + d, cx]) == 'W' for d in range(-5, 6))
    assert all(kind(a[cy, cx + d]) == 'W' for d in range(-5, 6))
    assert kind(a[cy - 3, cx - 1]) == kind(a[cy - 3, cx + 1]) == 'K'
    assert kind(a[cy - 3, cx - 3]) == 'F'
    # below the label (its type is antialiased), only the frame, the
    # halo and the ink
    top = cy - r - 4
    assert 4 + 2 * height < top, (height, top)
    below = {tuple(px) for px in a[top:].reshape(-1, 3)}
    assert below <= {(147, 147, 147), halo, ink}, below
    # the label: white type on a black stroke
    label = {tuple(px) for px in a[:top, :300].reshape(-1, 3)}
    assert ink in label and halo in label, label
    assert (a[..., 0] == a[..., 1]).all() and (a[..., 1] == a[..., 2]).all(), \
        "a colored pixel is left"


def test_the_focus_score_is_taken_before_the_focus_circle_is_drawn():
    """The Webcam preview (_cam_show) scores the camera's frame, then
    draws the circle on its own thumbnail of it: the score is the
    undrawn frame's, the frame itself is untouched, and the picture
    shown carries the circle's white (#482). Headless: the label and
    the PhotoImage are stand-ins."""
    import types
    from PIL import ImageTk
    import gui
    import sldea_liveview as lv
    import webcam
    rng = np.random.default_rng(482)
    # under 200, so the only white in the picture shown is the circle's
    rgb = rng.integers(0, 200, (480, 640, 3), dtype=np.uint8)
    before = rgb.copy()
    want = webcam.focus_score(before)
    order, seen = [], {}
    real_score, real_draw = webcam.focus_score, gui.draw_focus_overlay
    real_photo = ImageTk.PhotoImage

    def score(frame):
        order.append('score')
        seen['scored'] = np.array(frame, copy=True)
        return real_score(frame)

    def draw(img, s):
        order.append('draw')
        seen['score'] = s
        return real_draw(img, s)

    def photo(img):
        seen['shown'] = np.asarray(img).copy()
        return object()
    view = types.SimpleNamespace(winfo_width=lambda: 644,
                                 config=lambda **kw: None)
    app = types.SimpleNamespace(
        cam_view=view, cam_focus_var=types.SimpleNamespace(get=lambda: True))
    webcam.focus_score, gui.draw_focus_overlay = score, draw
    ImageTk.PhotoImage = photo
    try:
        gui.InstrumentControlGUI._cam_show(app, rgb)
    finally:
        webcam.focus_score, gui.draw_focus_overlay = real_score, real_draw
        ImageTk.PhotoImage = real_photo
    assert order == ['score', 'draw'], order
    assert np.array_equal(seen['scored'], before), "scored a drawn frame"
    assert seen['score'] == want, (seen['score'], want)
    assert np.array_equal(rgb, before), "the overlay drew on the frame"
    white = tuple(int(lv.RETICLE_INK[i:i + 2], 16) for i in (1, 3, 5))
    assert (seen['shown'] == white).all(axis=2).any(), "no circle shown"


# ------------------------------------------------------------- needs Tk

def test_the_preflight_dialog_shows_the_reticle_it_drew():
    """The test above draws the reticle by hand. Here the REAL pre-flight
    dialog (test_sldea_preflight's driver, on its synthetic disc frame)
    calls draw_preflight_reticle on the frame it took, scaled to 520 px
    wide, and shows that very picture: on screen, the pixel where the
    vertical line crosses the top of the picture is the reticle's white,
    and a pixel off the reticle is the frame's own (#476)."""
    from PIL import Image
    import tkinter as tk
    import gui
    import sldea_liveview as lv
    import test_sldea_preflight as pf
    calls, shown = [], {}
    real = gui.draw_preflight_reticle

    def spy(img):
        calls.append((img.size, np.asarray(img).copy()))
        return real(img)

    def probe(dlg, app, mb):
        [lbl] = [w for w in dlg.win.winfo_children()
                 if isinstance(w, tk.Label) and str(w.cget('image'))]
        name = str(lbl.cget('image'))

        def px(x, y):
            got = dlg.win.tk.splitlist(dlg.win.tk.call(name, 'get', x, y))
            return tuple(int(str(v)) for v in got)
        shown['on'], shown['off'] = px(260, 10), px(20, 10)
        dlg.start.invoke()

    gui.draw_preflight_reticle = spy
    try:
        go, _app, _mb, _cam, _lock = pf._dialog(pf.GOOD, {}, probe)
    except pf._Skip as why:
        raise _Skip(str(why))
    finally:
        gui.draw_preflight_reticle = real
    assert go is True
    assert len(calls) == 1, [c[0] for c in calls]
    h, w = pf.GOOD.shape[:2]
    want = np.asarray(Image.fromarray(pf.GOOD).resize(
        (520, int(h * (520 / w)))))
    size, before = calls[0]
    assert size == (want.shape[1], want.shape[0]), size
    assert np.array_equal(before, want), "the reticle went on another picture"
    white = tuple(int(lv.RETICLE_INK[i:i + 2], 16) for i in (1, 3, 5))
    assert shown['on'] == white, shown
    assert shown['off'] == tuple(int(v) for v in want[10, 20]), \
        (shown, want[10, 20])

def test_tracer_draws_its_tol_colors_at_the_widths_215_measured():
    """The hand tracer on a gray frame with every overlay on, three points
    placed and the pointer out: what each item is drawn in, and how wide.
    Colors: TRACE_* and A/B/C's, wrapping over A/B/C only (a fourth
    detector candidate is drawn in A's color, never in D's). Widths and
    dashes: the trace's segments 2, its closing segment and the rubber
    band 1 and dashed, the rings 2 then 1, every overlay 1 and dashed.
    Nothing has a halo."""
    import sldea_edge_gui as gui
    from PIL import Image
    root = _tk_root()
    d = tempfile.mkdtemp(prefix='tol_tracer_')
    try:
        img = os.path.join(d, 'f.png')
        Image.new('RGB', (320, 240), (147, 147, 147)).save(img)

        def ring(r):
            t = np.linspace(0, 2 * np.pi, 40, endpoint=False)
            return np.stack([160 + r * np.cos(t), 120 + r * np.sin(t)], 1)
        cands = [{'contour': ring(r)} for r in (60, 64, 68, 72)]
        app = types.SimpleNamespace(
            root=root, base_ref={'contour': ring(50)},
            results={0: {'contour': ring(56)}}, frame_rows=[0, 1],
            run={'rows': [{'step': 0, 'tag': 'post-ramp',
                           'nominal_kV': '1.0'},
                          {'step': 1, 'tag': 'post-ramp',
                           'nominal_kV': '2.0'}]},
            trace_overlay_cands=lambda i: cands)
        win = gui.TraceWindow(app, 1, img, mm_per_px=0.05)
        try:
            for var in (win.ov_rest, win.ov_cand, win.ov_prev):
                var.set(True)
            for x, y in ((100.0, 60.0), (220.0, 60.0), (220.0, 180.0)):
                win.model.add(x, y)
            win._cursor = (40.0, 40.0)
            win._drag_idx = None
            win._vectors()
            items = _items(win.cv, 'vec')
        finally:
            win.destroy()
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)
    # the candidate overlays wear CAND_COLORS, which are #450's to choose
    own = [it for it in items if it['dash'] != (2, 4) or it['kind'] == 'line']
    assert not _colors(own) - TOL, _colors(own) - TOL
    polys = [it for it in items if it['kind'] == 'polygon']
    by_dash = {}
    for it in polys:
        by_dash.setdefault(it['dash'], []).append(it['outline'])
        assert it['width'] == 1.0 and it['fill'] == '', it
    assert by_dash[(4, 4)] == [gui.TRACE_REST], by_dash
    assert by_dash[(6, 3)] == [gui.TRACE_PREV], by_dash
    # four detector candidates: A, B, C, then A again, not D's color
    want = [c.upper() for c in gui.CAND_COLORS[:gui.TRACE_SLOT]]
    assert by_dash[(2, 4)] == want + want[:1], by_dash
    lines = [it for it in items if it['kind'] == 'line']
    solid = [it for it in lines if not it['dash']]
    assert len(solid) == 2 and all(
        it['fill'] == gui.TRACE_INK and it['width'] == 2.0 for it in solid), \
        solid
    dashed = sorted((it['dash'], it['fill'], it['width'])
                    for it in lines if it['dash'])
    assert dashed == [((2, 4), gui.TRACE_INK, 1.0),
                      ((3, 4), gui.TRACE_INK, 1.0)], dashed
    rings = [it for it in items if it['kind'] == 'oval']
    assert [it['width'] for it in rings] == [2.0, 1.0, 1.0], rings
    assert all(it['outline'] == gui.TRACE_INK
               and it['fill'] == gui.TRACE_FACE for it in rings), rings


def _cal_items(mode, clicks=()):
    """Open the real calibration dialog on the synthetic run in `mode`,
    click each point of `clicks` (ORIGINAL px) in turn, and return what
    its canvas holds, the dialog's stroke style and the points placed in
    the current round (in VIEW px) before closing it."""
    import sldea_edge_gui as gui
    import test_sldea_edge_gui as edge
    root = _tk_root()
    d = tempfile.mkdtemp(prefix='tol_cal_')
    real_mb, real_choice = gui.messagebox, gui.cal_choice
    got = {}
    try:
        run = edge._fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None, "synthetic run failed to load"
        spy = edge._ModalSpy(real_mb, app, answers=[])
        gui.messagebox = gui.cal_choice = spy

        def look(win):
            edge._cal_onscreen(root, win)
            for click in clicks:
                edge._click_at_original(app, click)
            p = app._cal_probe
            assert p and p['mode_var'].get(), "the dialog published no probe"
            got['stroke'] = p['stroke_var'].get()
            got['items'] = _items(p['canvas'])
            got['views'] = [p['vt'].to_view(x, y) for x, y in p['st']['ptsv']]
            win.destroy()
        app.root.wait_window = look
        app._calibrate_scale(mode=mode)
    finally:
        gui.messagebox, gui.cal_choice = real_mb, real_choice
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)
    assert got.get('items'), f"the {mode} dialog drew nothing"
    return got


def test_calibration_verify_mode_is_white_dashed_on_a_black_companion():
    """VERIFY: the automatic fit as a 1 px dashed white circle with a 1 px
    dashed black companion just outside it, and a white cross with a hole
    in it. One px wide, as #215's A' arm found it has to be."""
    import sldea_edge_gui as gui
    got = _cal_items('verify')
    items = got['items']
    assert _colors(items) <= {gui.CAL_INK, gui.CAL_HALO}, _colors(items)
    ovals = [it for it in items if it['kind'] == 'oval']
    assert sorted(it['outline'] for it in ovals) == sorted(
        [gui.CAL_INK, gui.CAL_HALO]), ovals
    for it in ovals:
        assert it['width'] == gui.CAL_VERIFY_STROKE_PX == 1, it
        assert it['dash'] == gui.CAL_VERIFY_DASH, it
    # the companion sits OUTSIDE the white circle, never on the boundary
    ink = next(it for it in ovals if it['outline'] == gui.CAL_INK)
    halo = next(it for it in ovals if it['outline'] == gui.CAL_HALO)
    grow = [h - i for h, i in zip(halo['coords'], ink['coords'])]
    assert np.allclose(grow, [-1, -1, 1, 1]), (halo['coords'], ink['coords'])
    arms = [it for it in items if it['kind'] == 'line']
    assert len(arms) == 4 and all(it['fill'] == gui.CAL_INK
                                  and it['width'] == 1.0 for it in arms), arms


def test_calibration_circle_mode_keeps_its_3px_stroke_on_a_5px_halo():
    """CIRCLE at its default stroke: a 3 px white circle on a 5 px black
    halo (the arm #215 measured at +2.07 %), a white center cross, and
    white handles edged in black."""
    import sldea_edge_gui as gui
    got = _cal_items('circle')
    items = got['items']
    assert _colors(items) <= {gui.CAL_INK, gui.CAL_HALO}, _colors(items)
    assert gui.cal_stroke_spec(got['stroke']) == (3, None), got['stroke']
    ovals = sorted((it['width'], it['outline'], it['dash'])
                   for it in items if it['kind'] == 'oval')
    assert ovals == [(3.0, gui.CAL_INK, ()), (5.0, gui.CAL_HALO, ())], ovals
    handles = [it for it in items if it['kind'] == 'rectangle']
    assert handles and all(it['fill'] == gui.CAL_INK
                           and it['outline'] == gui.CAL_HALO
                           for it in handles), handles
    cross = [it for it in items if it['kind'] == 'line']
    assert len(cross) == 2 and all(it['fill'] == gui.CAL_INK
                                   for it in cross), cross


def test_calibration_two_point_marker_is_a_1px_white_ring_on_black():
    """TWOPOINT after one click: a 1 px white ring with a 1 px black ring
    just outside it, and white crosshair arms, never a filled dot."""
    import sldea_edge_gui as gui
    got = _cal_items('twopoint', clicks=[(80.0, 120.0)])
    items = got['items']
    assert _colors(items) <= {gui.CAL_INK, gui.CAL_HALO}, _colors(items)
    ovals = sorted((it['width'], it['outline'], it['fill'])
                   for it in items if it['kind'] == 'oval')
    want = sorted([(1.0, gui.CAL_INK, ''), (1.0, gui.CAL_HALO, '')])
    assert ovals == want, ovals
    arms = [it for it in items if it['kind'] == 'line']
    assert arms and all(it['fill'] == gui.CAL_INK and it['width'] == 1.0
                        for it in arms), arms


def test_calibration_two_point_chord_is_a_1px_white_dashed_line():
    """TWOPOINT with both points of a round placed (#476: the case above
    clicks once, so the chord was never drawn). Every round but the last
    banks on its second click and clears, so the chord stays on screen
    only in the last one; the clicks go through all five rounds. It is a
    single 1 px white line dashed (3, 5) that stops CAL_MARK_GAP_VIEW
    short of each point, so its ink never touches a judged pixel, and the
    only dashed line in the dialog. The markers at both points stay 1 px
    rings."""
    import math
    import sldea_edge_gui as gui
    clicks = [(80.0, 120.0), (240.0, 120.0)] * gui.CAL_ROUNDS_TWOPOINT
    got = _cal_items('twopoint', clicks=clicks)
    items = got['items']
    assert _colors(items) <= {gui.CAL_INK, gui.CAL_HALO}, _colors(items)
    assert len(got['views']) == 2, got['views']
    chords = [it for it in items if it['kind'] == 'line' and it['dash']]
    assert len(chords) == 1, chords
    ch = chords[0]
    assert (ch['fill'], ch['width'], ch['dash']) == \
        (gui.CAL_INK, 1.0, (3, 5)), ch
    p1, p2 = got['views']
    want = gui.chord_segment(p1, p2)
    assert want and np.allclose(ch['coords'], want, atol=0.5), \
        (ch['coords'], want)
    ends = (ch['coords'][:2], ch['coords'][2:])
    for x, y in (p1, p2):
        near = min(math.hypot(ex - x, ey - y) for ex, ey in ends)
        assert near >= gui.CAL_MARK_GAP_VIEW - 0.5, (near, (x, y), ends)
    ovals = sorted((it['width'], it['outline'], it['fill'])
                   for it in items if it['kind'] == 'oval')
    assert ovals == sorted([(1.0, gui.CAL_INK, ''),
                            (1.0, gui.CAL_HALO, '')] * 2), ovals


def test_labels_and_round_sets_name_the_palette_they_were_drawn_in():
    """#454 review: a lab PC runs the build it last updated to, so neither
    a label's timestamp nor a round-set's tells the Material colors from
    these. The label record carries the palette it is given (None when
    none is), and the round-set's log line ends with it only when the
    record names one, so every older line keeps its fields in place."""
    import sldea_edge as se
    import sldea_edge_gui as gui
    import sldea_trace as strc
    assert gui.TOOL_PALETTE == 'tol-454', gui.TOOL_PALETTE
    row = {'frame_file': 'SLDEA_s01_00.25kV_pre-ramp.png',
           'nominal_kV': '0.25', 'tag': 'pre-ramp'}
    poly = [(10, 10), (110, 12), (108, 90), (12, 88)]
    mach = {'method': 'disc-fit', 'conf': 0.91, 'area_px': 7500.0,
            'contour': np.array([[10, 10], [110, 10],
                                 [110, 90], [10, 90]], float)}
    rec = strc.label_record(3, row, poly, (540, 960), machine=mach,
                            palette=gui.TOOL_PALETTE, user='op',
                            now=1753795000)
    assert rec['palette'] == 'tol-454', rec
    old = strc.label_record(3, row, poly, (540, 960), machine=mach,
                            user='op', now=1753795000)
    assert old['palette'] is None, old
    cal = {'when': 'T', 'mode': se.CAL_MODE_CIRCLE,
           'stats': {'n': 3, 'mean': 575.0,
                     'values': [570.0, 575.0, 580.0]},
           'stroke': '3 px solid', 'outcome': 'accepted', 'frame': 'b.png'}
    before = se.calibration_log_line(cal)
    after = se.calibration_log_line(dict(cal, palette=gui.TOOL_PALETTE))
    assert 'palette=' not in before, before
    assert after == before + ' palette=tol-454', (before, after)


def test_the_tracer_hands_its_palette_to_the_label():
    """#454 review: Done passes TOOL_PALETTE with the rest of the label's
    metadata, so the label written from it names the colors drawn."""
    import sldea_edge_gui as gui
    from PIL import Image
    root = _tk_root()
    d = tempfile.mkdtemp(prefix='tol_palette_')
    staged = []
    try:
        img = os.path.join(d, 'f.png')
        Image.new('RGB', (320, 240), (147, 147, 147)).save(img)
        t = np.linspace(0, 2 * np.pi, 40, endpoint=False)
        disc = np.stack([160 + 50 * np.cos(t), 120 + 50 * np.sin(t)], 1)
        app = types.SimpleNamespace(
            root=root, base_ref={'contour': disc}, results={}, frame_rows=[0],
            run={'rows': [{'step': 0, 'tag': 'post-ramp',
                           'nominal_kV': '1.0'}]},
            trace_overlay_cands=lambda i: [],
            _trace_staged=lambda i, pts, meta: staged.append(meta))
        win = gui.TraceWindow(app, 0, img, mm_per_px=0.05)
        for x, y in ((100.0, 60.0), (220.0, 60.0), (220.0, 180.0)):
            win.model.add(x, y)
        win._done()
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)
    assert len(staged) == 1, staged
    assert staged[0]['palette'] == gui.TOOL_PALETTE, staged[0]


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block; run_tests.py explains why.
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
            # A test that blew up still RAN: only a skip is "did not run".
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
