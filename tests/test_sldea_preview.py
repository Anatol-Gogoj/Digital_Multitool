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
    bar and must FAIL it, so the check is one that can fail;
  * marker size follows the room between landings, within its limits,
    and the markers made smaller in #401 keep the old hover reach;
  * the hover text names each snapshot in the tab's own words;
  * on the real tab: the two timing fields sit together under their tags'
    names and still drive the profile, the canvas draws one marker per
    scheduled snapshot plus a legend, the playhead is not the old red,
    and hovering a marker describes it.

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
        # read the legend the way a person does: left to right on screen
        legend_items = sorted((i for i in c.find_withtag('legend')
                               if c.type(i) == 'text'),
                              key=lambda i: c.bbox(i)[0])
        legend = [c.itemcget(i, 'text') for i in legend_items]
        assert legend == [pv.MARKERS[t][2] for t in pv.legend_tags(p)], \
            legend
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
