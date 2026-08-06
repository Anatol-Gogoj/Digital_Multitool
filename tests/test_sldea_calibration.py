#!/usr/bin/env python3
"""Edge Review scale gate v2 -- fit-a-circle calibration (#215) plus the
anchor sanity guard added on top of it (2026-08-06).

Everything measurable is pure and runs headlessly: the circle geometry
(spawn / handles / hit-test / clamp / key nudges), the averaging and the
spread gate, the two-reference guard, the partial-re-save rescale
arithmetic, and the BACKWARDS-COMPATIBLE anchor read path -- 15 runs
carry the 2026-08-05 two-click anchor with no rounds recorded and two
(P3_6_2.5mL_20260729, DOT_P3_1_20260729) predate the gate and carry no
anchor block at all. All of them must still load and report.

Deliberately NOT tested here: that the dialog opens. The Tk widget layer
skips headlessly (see tests/test_sldea_edge_gui.py) and
tests/test_app_launch.py self-skips on Windows, so this file pins the
LOGIC the dialog drives, not the dialog.

Run: .venv/Scripts/python.exe tests/test_sldea_calibration.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import math
import os
import random
import shutil
import tempfile

import sldea_edge as se


# ---------------------------------------------------------------------------
# the field failure this whole change exists for
# ---------------------------------------------------------------------------

# Run P3_2_2.5mL_20260728, reviewed 2026-08-06. The operator's two-click
# anchor vs the automatic resting-disc fit (circ 0.999, conf 0.871).
P3_2_MANUAL_PX = 590.26
P3_2_AUTO_PX = 577.1
MASK_MM = 16.0
MASK_AREA_MM2 = math.pi * 8.0 ** 2          # 201.06 mm2, SLDEA_MEASUREMENT 2.4


def _auto_ref(diam_px=P3_2_AUTO_PX, **kw):
    """A baseline_disc-shaped reference. baseline_disc returns a CIRCLE
    fit, so area_px is pi*r^2 -- which is exactly why the area guard is
    the diameter guard squared, and why the test says so out loud."""
    ref = {'method': 'baseline-disc', 'diam_px': float(diam_px),
           'area_px': math.pi * (float(diam_px) / 2.0) ** 2,
           'circ': 0.999, 'conf': 0.871}
    ref.update(kw)
    return ref


def test_anchor_guard_reproduces_the_p3_2_field_failure():
    """The guard must catch, twice over, the run that shipped 4.42% low
    in every absolute mm2 while the old 3% cross-check said nothing."""
    g = se.anchor_guard(P3_2_MANUAL_PX, _auto_ref(), MASK_MM)
    assert g['available']
    # +2.28% in diameter -> -4.42% in area, and the recorded resting area
    # was 192.18 mm2 against the mask's 201.06
    assert abs(g['diam_pct'] - 2.28) < 0.01, g['diam_pct']
    assert abs(g['area_pct'] + 4.41) < 0.02, g['area_pct']
    assert abs(g['rest_area_mm2'] - 192.2) < 0.1, g['rest_area_mm2']
    assert abs(g['nominal_mm2'] - MASK_AREA_MM2) < 1e-9
    assert len(g['warn']) == 2                     # both references object
    assert any('automatic disc fit' in w for w in g['warn'])
    assert any('mask anchor' in w for w in g['warn'])
    # and the OLD tier would still have let it through in silence
    assert abs(g['diam_pct']) < se.ANCHOR_MODAL_DIAM_PCT


def test_anchor_guard_is_quiet_on_an_honest_calibration():
    g = se.anchor_guard(P3_2_AUTO_PX, _auto_ref(), MASK_MM)
    assert g['available'] and g['warn'] == []
    assert abs(g['diam_pct']) < 1e-9
    assert abs(g['area_pct']) < 1e-9
    assert abs(g['rest_area_mm2'] - MASK_AREA_MM2) < 1e-6
    # 0.3% in diameter -- the measured repeat of the scale trace on one
    # device 32 min apart (SLDEA_MEASUREMENT 2.1) -- must NOT warn on
    # diameter, though 0.3% diameter is 0.6% area, also inside the gate
    g = se.anchor_guard(P3_2_AUTO_PX * 1.003, _auto_ref(), MASK_MM)
    assert g['warn'] == [], g['warn']


def test_anchor_guard_area_gate_is_the_binding_one():
    """Honest about the algebra: on a circle-fit reference the area test
    IS the diameter test squared, so a 1% area gate trips at ~0.5%
    diameter and the 1% diameter gate never fires first. Pinned so a
    later reader cannot mistake them for two independent votes."""
    g = se.anchor_guard(P3_2_AUTO_PX * 1.006, _auto_ref(), MASK_MM)
    assert abs(g['diam_pct'] - 0.6) < 1e-6
    assert abs(g['area_pct'] + 1.19) < 0.01          # (1/1.006^2 - 1)
    assert len(g['warn']) == 1                       # area only
    assert 'mask anchor' in g['warn'][0]
    # the identity itself
    for f in (0.97, 0.995, 1.004, 1.03):
        g = se.anchor_guard(P3_2_AUTO_PX * f, _auto_ref(), MASK_MM)
        assert abs((1.0 + g['area_pct'] / 100.0) - 1.0 / f ** 2) < 1e-9


def test_anchor_guard_refuses_to_invent_a_cross_check():
    """No automatic fit, a refused fit, or a nonsense diameter -> the
    guard reports unavailable and warns about NOTHING. baseline_disc
    refuses rather than fabricating; the guard must inherit that."""
    for auto in (None, {}, {'method': 'baseline-disc'},
                 {'diam_px': 0.0}, {'diam_px': None}):
        g = se.anchor_guard(P3_2_MANUAL_PX, auto, MASK_MM)
        assert g['available'] is False and g['warn'] == []
        assert g['diam_pct'] is None and g['area_pct'] is None
    # a garbage anchor or diam_mm cannot raise either
    for mean, dmm in ((0, 16.0), (None, 16.0), (590.0, 0), (590.0, None)):
        g = se.anchor_guard(mean, _auto_ref(), dmm)
        assert g['available'] is False and g['warn'] == []
    # a non-16 mm mask moves the nominal with it (the guard is not
    # hardcoded to 201.06)
    g = se.anchor_guard(300.0, _auto_ref(300.0), 20.0)
    assert abs(g['nominal_mm2'] - math.pi * 100.0) < 1e-9
    assert g['warn'] == []


def test_anchor_guard_uses_the_fits_measured_area_when_it_has_one():
    """area_px is preferred over pi*r^2 so a future non-circular
    reference contributes real information instead of a restatement."""
    ref = _auto_ref()
    ref['area_px'] = ref['area_px'] * 1.02            # 2% more area, same d
    g = se.anchor_guard(P3_2_AUTO_PX, ref, MASK_MM)
    assert abs(g['diam_pct']) < 1e-9                  # diameter agrees
    assert abs(g['area_pct'] - 2.0) < 1e-6            # area does not
    assert len(g['warn']) == 1 and 'mask anchor' in g['warn'][0]


def test_guard_note_records_the_decision_not_just_the_number():
    g = se.anchor_guard(P3_2_MANUAL_PX, _auto_ref(), MASK_MM)
    note = se.anchor_guard_note(g, overridden=True)
    assert note.startswith('OVERRIDDEN by operator')
    assert '+2.28% diam' in note and '-4.41% area' in note
    assert se.anchor_guard_note(g, False).startswith('tripped:')
    clean = se.anchor_guard(P3_2_AUTO_PX, _auto_ref(), MASK_MM)
    assert se.anchor_guard_note(clean, False).startswith('clear (')
    assert se.anchor_guard_note(
        se.anchor_guard(500.0, None, MASK_MM), False) == \
        'no auto disc fit to cross-check'
    # setup.txt is ASCII-only for this field
    for n in (note, se.anchor_guard_note(clean, False)):
        n.encode('ascii')


# ---------------------------------------------------------------------------
# averaging, spread, and the spread gate
# ---------------------------------------------------------------------------

def test_calibration_stats_mean_and_spread():
    s = se.calibration_stats([580.0, 584.0, 582.0])
    assert s['n'] == 3 and abs(s['mean'] - 582.0) < 1e-12
    assert s['min'] == 580.0 and s['max'] == 584.0
    assert abs(s['spread_px'] - 4.0) < 1e-12
    assert abs(s['spread_pct'] - 100 * 4.0 / 582.0) < 1e-12
    assert s['values'] == [580.0, 584.0, 582.0]      # order preserved
    # a single round has a mean and no spread
    s1 = se.calibration_stats([577.0])
    assert s1['n'] == 1 and s1['spread_px'] == 0.0
    assert s1['spread_pct'] == 0.0
    # nothing fitted -> None, never a zero that reads as a measurement
    assert se.calibration_stats([]) is None
    assert se.calibration_stats(None) is None
    assert se.calibration_stats([0.0, 0.0]) is None


def test_calibration_stats_does_not_reject_outliers():
    """A plain mean of EVERY round. Dropping the odd one out would edit
    the very number the spread exists to report -- three fits is far too
    few to identify an outlier anyway."""
    s = se.calibration_stats([580.0, 582.0, 640.0])
    assert abs(s['mean'] - (580 + 582 + 640) / 3.0) < 1e-12
    assert s['n'] == 3
    assert s['spread_pct'] > se.CAL_SPREAD_PCT        # and it shows


def test_spread_gate():
    tight = se.calibration_stats([580.0, 582.0, 581.0])     # 0.34%
    loose = se.calibration_stats([575.0, 590.0, 582.0])      # 2.58%
    assert se.spread_ok(tight) and tight['spread_pct'] < se.CAL_SPREAD_PCT
    assert not se.spread_ok(loose)
    # exactly at the gate passes (the gate is "exceeds")
    at = se.calibration_stats([1000.0, 1010.0])              # ~0.995%
    assert at['spread_pct'] < 1.0 and se.spread_ok(at)
    # one round passes vacuously -- the honest answer, not a certificate
    assert se.spread_ok(se.calibration_stats([577.0]))
    assert se.spread_ok(None)
    # a 4th round can rescue a loose set, which is what the gate offers
    rescued = se.calibration_stats([581.0, 582.0, 583.0, 582.0])
    assert se.spread_ok(rescued) and rescued['n'] == 4
    assert se.CAL_ROUNDS == 3


def test_three_round_mean_beats_a_single_fit_on_scatter():
    """The arithmetic claimed in SLDEA_MEASUREMENT 2.1: averaging n fits
    divides the RANDOM part of the scale-anchor term by sqrt(n). Driven
    with a seeded generator so the assertion is deterministic."""
    rnd = random.Random(20260806)
    truth, sigma = 577.1, 4.0            # ~0.7% per-fit scatter
    single, mean3 = [], []
    for _ in range(4000):
        fits = [rnd.gauss(truth, sigma) for _ in range(3)]
        single.append(fits[0] - truth)
        mean3.append(sum(fits) / 3.0 - truth)

    def rms(xs):
        return (sum(x * x for x in xs) / len(xs)) ** 0.5

    ratio = rms(mean3) / rms(single)
    assert 0.50 < ratio < 0.66, ratio           # 1/sqrt(3) = 0.577
    # and the mean range of 3 normal samples is ~1.693 sigma, the
    # conversion the 1% spread gate is chosen against
    rng = []
    for _ in range(4000):
        fits = [rnd.gauss(truth, sigma) for _ in range(3)]
        rng.append(max(fits) - min(fits))
    assert 1.6 < (sum(rng) / len(rng)) / sigma < 1.8


# ---------------------------------------------------------------------------
# the partial-re-save consequence
# ---------------------------------------------------------------------------

def test_rescale_pct_is_the_partial_resave_consequence():
    """SLDEA_HANDOFF [critical] 2026-08-05: unreviewed rows keep their px
    and their mm2 are RE-DERIVED at the current save's scale, so changing
    the anchor moves the WHOLE run's absolute column. P3_2's numbers are
    the worked example: 577.1 -> 590.26 px is -4.42% on every mm2."""
    assert abs(se.rescale_pct(P3_2_AUTO_PX, P3_2_MANUAL_PX) + 4.41) < 0.02
    # symmetric the other way (recalibrating BACK)
    assert se.rescale_pct(P3_2_MANUAL_PX, P3_2_AUTO_PX) > 4.5
    # a bigger diameter means a smaller mm/px means smaller areas
    assert se.rescale_pct(100.0, 200.0) < 0
    assert abs(se.rescale_pct(100.0, 200.0) + 75.0) < 1e-9
    assert se.rescale_pct(300.0, 300.0) == 0.0
    for a, b in ((0, 300.0), (300.0, 0), (None, 300.0), (300.0, None)):
        assert se.rescale_pct(a, b) is None
    # it really is the ratio of the two mm2 the two anchors produce
    area_px = 261564.6
    old = area_px * (MASK_MM / P3_2_AUTO_PX) ** 2
    new = area_px * (MASK_MM / P3_2_MANUAL_PX) ** 2
    assert abs(se.rescale_pct(P3_2_AUTO_PX, P3_2_MANUAL_PX)
               - 100.0 * (new / old - 1.0)) < 1e-9


# ---------------------------------------------------------------------------
# circle geometry -- what the handles and keys actually do
# ---------------------------------------------------------------------------

def test_spawn_stays_inside_the_roi_and_actually_moves():
    import sldea_edge_gui as gui
    w, h, rf = 1920, 1080, 0.85
    x0, y0, x1, y1 = gui.cal_roi(w, h, rf)
    # the ROI is the one baseline_disc searches
    assert abs(x0 - w * 0.075) < 1e-9 and abs(y0 - h * 0.075) < 1e-9
    rnd = random.Random(215)
    seen = set()
    for _ in range(500):
        cx, cy, r = gui.spawn_circle(w, h, rf, rnd)
        assert x0 <= cx - r and cx + r <= x1, (cx, r)
        assert y0 <= cy - r and cy + r <= y1, (cy, r)
        assert r >= gui.CAL_MIN_R_PX
        seen.add((round(cx, 3), round(cy, 3), round(r, 3)))
    # decorrelation is the POINT: no two rounds may spawn identically
    assert len(seen) == 500
    # and the jitter is real, not cosmetic -- centres and radii both move
    # by a useful fraction of the disc
    rnd = random.Random(215)
    trials = [gui.spawn_circle(w, h, rf, rnd) for _ in range(200)]
    assert max(t[0] for t in trials) - min(t[0] for t in trials) > 40
    assert max(t[2] for t in trials) - min(t[2] for t in trials) > 40
    # a seeded generator makes a session reproducible
    a = gui.spawn_circle(w, h, rf, random.Random(7))
    b = gui.spawn_circle(w, h, rf, random.Random(7))
    assert a == b
    # tiny and extreme frames must not produce a nonsense circle
    for (fw, fh, frac) in ((64, 64, 0.85), (4000, 200, 0.5),
                           (100, 100, 0.2), (100, 100, 1.0)):
        bx0, by0, bx1, by1 = gui.cal_roi(fw, fh, frac)
        cx, cy, r = gui.spawn_circle(fw, fh, frac, random.Random(1))
        assert r > 0
        assert bx0 - 1e-9 <= cx - r and cx + r <= bx1 + 1e-9
        assert by0 - 1e-9 <= cy - r and cy + r <= by1 + 1e-9


def test_handles_ring_the_circle():
    import sldea_edge_gui as gui
    hs = gui.circle_handles(100.0, 200.0, 50.0)
    assert len(hs) == 8
    names = [n for n, _x, _y in hs]
    assert sorted(names) == sorted(['e', 'se', 's', 'sw',
                                    'w', 'nw', 'n', 'ne'])
    for nm, x, y in hs:
        assert abs(((x - 100.0) ** 2 + (y - 200.0) ** 2) ** 0.5 - 50.0) < 1e-9
    d = dict((n, (x, y)) for n, x, y in hs)
    assert d['e'] == (150.0, 200.0) and d['w'] == (50.0, 200.0)
    assert d['s'] == (100.0, 250.0) and d['n'] == (100.0, 150.0)


def test_hit_test_prefers_handles_and_grabs_nothing_outside():
    import sldea_edge_gui as gui
    cx, cy, r = 100.0, 100.0, 40.0
    assert gui.hit_test_circle(cx, cy, r, 140.0, 100.0) == 'e'
    assert gui.hit_test_circle(cx, cy, r, 100.0, 60.0) == 'n'
    assert gui.hit_test_circle(cx, cy, r, 100.0, 100.0) == 'move'
    assert gui.hit_test_circle(cx, cy, r, 120.0, 100.0) == 'move'
    # a press just inside the boundary still grabs the handle, not move
    assert gui.hit_test_circle(cx, cy, r, 136.0, 100.0) == 'e'
    # the nearest handle wins when two are in reach
    on_se = gui.circle_handles(cx, cy, r)[1]
    assert gui.hit_test_circle(cx, cy, r, on_se[1], on_se[2]) == 'se'
    # THE interaction bug that must not exist: a press that grabs
    # nothing returns None, so the circle cannot teleport to a stray
    # click after the operator thinks the fit is done
    assert gui.hit_test_circle(cx, cy, r, 400.0, 400.0) is None
    assert gui.hit_test_circle(cx, cy, r, cx, cy - r - 30) is None
    # tolerance is in the caller's units (the dialog hit-tests in VIEW
    # px, so a handle is the same size to the hand at every zoom)
    assert gui.hit_test_circle(cx, cy, r, 152.0, 100.0, tol=15) == 'e'
    assert gui.hit_test_circle(cx, cy, r, 152.0, 100.0, tol=2) is None


def test_resize_is_about_the_centre_and_always_circular():
    import sldea_edge_gui as gui
    assert abs(gui.resize_radius(0.0, 0.0, 30.0, 40.0) - 50.0) < 1e-9
    # dragging any handle to the same distance gives the same radius --
    # a circle has one degree of freedom, by construction (#215: ellipse
    # handles are out of scope)
    for px, py in ((50.0, 0.0), (0.0, 50.0), (-50.0, 0.0),
                   (35.355339, 35.355339)):
        assert abs(gui.resize_radius(0.0, 0.0, px, py) - 50.0) < 1e-4
    # collapsing onto the centre floors at the minimum, never 0 or
    # negative (a 0-radius circle would divide by zero into mm/px)
    assert gui.resize_radius(0.0, 0.0, 0.0, 0.0) == gui.CAL_MIN_R_PX
    assert gui.resize_radius(0.0, 0.0, 1.0, 1.0) == gui.CAL_MIN_R_PX


def test_clamp_contain_for_spawn_and_loose_for_dragging():
    import sldea_edge_gui as gui
    box = (0.0, 0.0, 200.0, 100.0)
    # contain: the whole circle inside, radius capped by the short side
    cx, cy, r = gui.clamp_circle(10.0, 10.0, 80.0, box, contain=True)
    assert r == 50.0 and (cx, cy) == (50.0, 50.0)
    # loose (dragging): the CENTRE is boxed, the circle may overhang --
    # a disc running off the frame edge is a broken run, and hiding it
    # would be worse than drawing it
    cx, cy, r = gui.clamp_circle(-40.0, 500.0, 80.0, box, contain=False)
    assert (cx, cy) == (0.0, 100.0) and r == 80.0
    # radius floor in both modes
    for contain in (True, False):
        assert gui.clamp_circle(50.0, 50.0, -5.0, box,
                                contain=contain)[2] == gui.CAL_MIN_R_PX
    # a box smaller than the minimum radius must not produce an inverted
    # centre range (it centres instead)
    cx, cy, r = gui.clamp_circle(3.0, 3.0, 2.0, (0.0, 0.0, 4.0, 4.0),
                                 contain=True)
    assert r == gui.CAL_MIN_R_PX and (cx, cy) == (2.0, 2.0)


def test_diameter_plausibility_matches_the_automatic_fits_own_gate():
    """A circle collapsed onto its own centre is not a fit, and a
    nonsense anchor scales EVERY area in the run. The two-click dialog
    refused clicks under 10 px apart; the same refusal has to survive the
    replacement, and it uses baseline_disc's own 0.06-0.85-of-ROI window
    so the dialog cannot accept what the automatic fit would reject."""
    import sldea_edge_gui as gui
    w, h, rf = 1920, 1080, 0.85
    x0, y0, x1, y1 = gui.cal_roi(w, h, rf)
    span = min(x1 - x0, y1 - y0)
    assert gui.cal_diam_plausible(577.1, w, h, rf)       # the real disc
    assert not gui.cal_diam_plausible(2 * gui.CAL_MIN_R_PX, w, h, rf)
    assert not gui.cal_diam_plausible(0.0, w, h, rf)
    assert not gui.cal_diam_plausible(0.9 * span, w, h, rf)
    # exactly on both edges of the window is accepted
    assert gui.cal_diam_plausible(gui.CAL_MIN_DIAM_FRAC * span, w, h, rf)
    assert gui.cal_diam_plausible(gui.CAL_MAX_DIAM_FRAC * span, w, h, rf)
    # a RAW SPAWN must always be acceptable, or the first Continue of
    # every round could be refused as implausible
    rnd = random.Random(9)
    for (fw, fh, frac) in ((1920, 1080, 0.85), (1280, 960, 0.85),
                           (320, 240, 0.85), (640, 480, 0.5)):
        for _ in range(200):
            _cx, _cy, r = gui.spawn_circle(fw, fh, frac, rnd)
            assert gui.cal_diam_plausible(2 * r, fw, fh, frac), (fw, r)


def test_key_and_wheel_deltas():
    import sldea_edge_gui as gui
    assert gui.cal_key_delta('Left') == (-1.0, 0.0, 0.0)
    assert gui.cal_key_delta('Right') == (1.0, 0.0, 0.0)
    assert gui.cal_key_delta('Up') == (0.0, -1.0, 0.0)      # screen y down
    assert gui.cal_key_delta('Down') == (0.0, 1.0, 0.0)
    # Shift+arrows RESIZE by 1 px; up/right grow (#215)
    assert gui.cal_key_delta('Up', shift=True) == (0.0, 0.0, 1.0)
    assert gui.cal_key_delta('Right', shift=True) == (0.0, 0.0, 1.0)
    assert gui.cal_key_delta('Down', shift=True) == (0.0, 0.0, -1.0)
    assert gui.cal_key_delta('Left', shift=True) == (0.0, 0.0, -1.0)
    assert gui.cal_key_delta('a') is None
    assert gui.cal_key_delta('') is None and gui.cal_key_delta(None) is None
    assert gui.cal_key_delta('LEFT') == (-1.0, 0.0, 0.0)    # case-blind
    # the wheel is the FINE RESIZE, positive notch grows
    assert gui.cal_wheel_dr(1) == gui.CAL_WHEEL_FINE_PX
    assert gui.cal_wheel_dr(-1) == -gui.CAL_WHEEL_FINE_PX
    assert gui.cal_wheel_dr(1, coarse=True) == gui.CAL_WHEEL_COARSE_PX
    assert gui.CAL_WHEEL_FINE_PX < gui.CAL_WHEEL_COARSE_PX


def test_a_fitted_circle_yields_the_diameter_the_anchor_uses():
    """End to end on the geometry: fit the circle to a known disc, take
    2r per round, average -> that is the anchor. Uses the P3_2 disc so
    the guard verdict is the field verdict."""
    import sldea_edge_gui as gui
    rnd = random.Random(1)
    truth_r = P3_2_AUTO_PX / 2.0
    diams = []
    for _ in range(se.CAL_ROUNDS):
        cx, cy, _r = gui.spawn_circle(1920, 1080, 0.85, rnd)
        # the operator drags a handle onto the true edge
        r = gui.resize_radius(cx, cy, cx + truth_r, cy)
        diams.append(2.0 * r)
    stats = se.calibration_stats(diams)
    assert abs(stats['mean'] - P3_2_AUTO_PX) < 1e-6
    assert stats['spread_pct'] == 0.0 and se.spread_ok(stats)
    assert se.anchor_guard(stats['mean'], _auto_ref(), MASK_MM)['warn'] == []


# ---------------------------------------------------------------------------
# persistence, and the backwards-compatible read path
# ---------------------------------------------------------------------------

def _setup(d, body="SLDEA Test\nDEA nominal diameter: 16 mm\n"):
    with open(os.path.join(d, 'setup.txt'), 'w', encoding='utf-8') as f:
        f.write(body)


def test_rounds_and_spread_round_trip_into_setup_txt():
    d = tempfile.mkdtemp(prefix='cal_persist_')
    try:
        _setup(d)
        stats = se.calibration_stats([580.4, 583.1, 581.2])
        guard = se.anchor_guard(stats['mean'], _auto_ref(581.0), MASK_MM)
        se.save_scale_anchor(d, {
            'method': 'manual-calibration',
            'diam_px': stats['mean'], 'diam_mm': MASK_MM,
            'mm_per_px': MASK_MM / stats['mean'],
            'anchor_frame': 'SLDEA_s00_00.00kV_baseline.png',
            'anchor_is_baseline': True, 'auto_diam_px': 581.0,
            'n_rounds': stats['n'], 'rounds_px': stats['values'],
            'spread_px': stats['spread_px'],
            'spread_pct': stats['spread_pct'],
            'guard': se.anchor_guard_note(guard, False)})
        a = se.load_scale_anchor(d)
        assert a['n_rounds'] == 3
        assert a['rounds_px'] == [580.4, 583.1, 581.2]
        assert abs(a['spread_px'] - 2.7) < 0.01
        assert abs(a['spread_pct'] - stats['spread_pct']) < 0.01
        assert a['guard'].startswith('clear (')
        assert abs(a['diam_px'] - stats['mean']) < 0.01
        # still a usable mm_per_px reference, and still survives a
        # settings save (the block sits before the settings section)
        assert abs(se.mm_per_px({}, [], {'diam_mm': MASK_MM},
                               baseline_ref=a) - MASK_MM / a['diam_px']) \
            < 1e-9
        se.save_settings(d, dict(se.DEFAULT_SETTINGS))
        again = se.load_scale_anchor(d)
        assert again['rounds_px'] == [580.4, 583.1, 581.2]
        text = open(os.path.join(d, 'setup.txt'), encoding='utf-8').read()
        assert text.count(se.ANCHOR_HDR) == 1
        assert 'rounds_px: 580.40; 583.10; 581.20' in text
        # a RECALIBRATION replaces the record, rounds and all
        se.save_scale_anchor(d, {'method': 'manual-calibration',
                                 'diam_px': 577.1, 'diam_mm': MASK_MM,
                                 'mm_per_px': MASK_MM / 577.1,
                                 'n_rounds': 4,
                                 'rounds_px': [577.0, 577.2, 577.1, 577.1],
                                 'spread_px': 0.2, 'spread_pct': 0.035})
        a2 = se.load_scale_anchor(d)
        assert a2['n_rounds'] == 4 and len(a2['rounds_px']) == 4
        assert open(os.path.join(d, 'setup.txt'),
                    encoding='utf-8').read().count('rounds_px') == 1
    finally:
        shutil.rmtree(d)


def test_two_click_era_anchors_still_load_untouched():
    """15 runs carry the 2026-08-05 anchor: method/diam_px/diam_mm/
    mm_per_px/frame/auto_diam_px and NOTHING else. They must load, be
    usable as a scale, and report their MISSING rounds as missing --
    never as a zero spread, which would read as perfect repeatability."""
    d = tempfile.mkdtemp(prefix='cal_legacy_')
    try:
        _setup(d)
        with open(os.path.join(d, 'setup.txt'), 'a',
                  encoding='utf-8') as f:
            f.write('\n' + se.ANCHOR_HDR + '\n'
                    'method: manual-calibration\n'
                    'diam_px: 590.26\n'
                    'diam_mm: 16\n'
                    'mm_per_px: 0.0271067\n'
                    'anchor_frame: SLDEA_s00_00.00kV_baseline.png\n'
                    'anchor_is_baseline: 1\n'
                    'auto_diam_px: 577.1\n'
                    'saved: 2026-08-06T09:14:02\n'
                    'user: anatol\n')
        a = se.load_scale_anchor(d)
        assert a['diam_px'] == 590.26 and a['anchor_is_baseline'] is True
        assert a['user'] == 'anatol'
        for k in ('rounds_px', 'n_rounds', 'spread_px', 'spread_pct',
                  'guard'):
            assert k not in a, k
            assert a.get(k) is None
        assert se.mm_per_px({}, [], {'diam_mm': 16.0}, baseline_ref=a) > 0
        # this IS P3_2: the offline guard must flag it from the record
        g = se.anchor_guard(a['diam_px'], _auto_ref(a['auto_diam_px']),
                            a['diam_mm'])
        assert len(g['warn']) == 2
        # and a re-save that adds rounds does not corrupt the old fields
        se.save_scale_anchor(d, dict(a, n_rounds=3,
                                     rounds_px=[590.0, 590.5, 590.28],
                                     spread_px=0.5, spread_pct=0.085))
        b = se.load_scale_anchor(d)
        assert b['anchor_frame'] == a['anchor_frame']
        assert b['saved'] == a['saved'] and b['n_rounds'] == 3
    finally:
        shutil.rmtree(d)


def test_pre_gate_runs_with_no_anchor_at_all_still_load():
    """P3_6_2.5mL_20260729 and DOT_P3_1_20260729 predate the gate: no
    anchor block, and in the limit no setup.txt. Every reader returns
    None instead of raising."""
    d = tempfile.mkdtemp(prefix='cal_pregate_')
    try:
        assert se.load_scale_anchor(d) is None          # no setup.txt
        _setup(d)
        assert se.load_scale_anchor(d) is None          # no block
        assert se.load_settings(d)['diam_mm'] == 16.0
        # a block with no diameter is not an anchor
        with open(os.path.join(d, 'setup.txt'), 'a',
                  encoding='utf-8') as f:
            f.write('\n' + se.ANCHOR_HDR + '\nmethod: manual-calibration\n'
                    'spread_pct: 0.4\n')
        assert se.load_scale_anchor(d) is None
    finally:
        shutil.rmtree(d)


def test_hand_edited_and_hostile_anchor_fields_degrade_quietly():
    """setup.txt is hand-annotated on the bench. A garbled new field
    must cost that field, not the anchor."""
    d = tempfile.mkdtemp(prefix='cal_hostile_')
    try:
        _setup(d)
        with open(os.path.join(d, 'setup.txt'), 'a',
                  encoding='utf-8') as f:
            f.write('\n' + se.ANCHOR_HDR + '\n'
                    'method: manual-calibration\n'
                    'diam_px: 581.2\n'
                    'diam_mm: 16\n'
                    'n_rounds: three\n'
                    'rounds_px: 580.4, oops, 581.2\n'
                    'spread_px: \n'
                    'spread_pct: n/a\n'
                    'guard: clear (auto +0.1% diam)\n')
        a = se.load_scale_anchor(d)
        assert a['diam_px'] == 581.2                 # the anchor survives
        assert 'n_rounds' not in a                    # unparseable: absent
        assert a['rounds_px'] == [580.4, 581.2]       # the good values kept
        assert 'spread_pct' not in a and 'spread_px' not in a
        assert a['guard'] == 'clear (auto +0.1% diam)'
        # an all-garbage round list is omitted rather than served empty
        _setup(d)
        with open(os.path.join(d, 'setup.txt'), 'a',
                  encoding='utf-8') as f:
            f.write('\n' + se.ANCHOR_HDR + '\ndiam_px: 100\n'
                    'rounds_px: ;;,\n')
        assert 'rounds_px' not in se.load_scale_anchor(d)
        # a newline smuggled into a text field cannot split the block and
        # orphan the fields after it
        _setup(d)
        se.save_scale_anchor(d, {'method': 'manual-calibration',
                                 'diam_px': 300.0, 'diam_mm': 16.0,
                                 'guard': 'line one\nmethod: EVIL',
                                 'user': 'tester'})
        a = se.load_scale_anchor(d)
        assert a['method'] == 'manual-calibration'
        assert '\n' not in a['guard'] and a['user'] == 'tester'
    finally:
        shutil.rmtree(d)


def _diag_d(**over):
    """A neutral verdicts()/report() input, same shape as the fixture in
    tests/test_sldea_diag.py, so one anchor rule can be exercised without
    a detection pass."""
    frame = {'idx': 1, 'kv': 5.0, 'file': 'f.png', 'shift_px': 0.1,
             'dx': 0.1, 'dy': 0.0, 'pc_response': 0.5, 'diff_mean': 4.0,
             'diff_mean_registered': 4.0, 'diff_mean_normbg': 4.0,
             'diff_mean_photofit': 4.0, 'gain': 1.0, 'offset': 0.0,
             'diff_p99': 8.0, 'diff_p99_sigma': 4.0, 'gated': False,
             'otsu': 20.0, 'texture_ratio': 1.0, 'sep_intensity': 0.4,
             'sep_registered': 0.4, 'sep_photofit': 0.4,
             'sep_texture': 0.4, 'area_px': 1000.0, 'solidity': 0.7,
             'conf': 0.8, 'needs_review': False}
    d = {'rundir': '/x/SLDEA_run', 'frames_analyzed': 3,
         'baseline_row': 0, 'frame_shape': [1080, 1920], 'sigma': 2.0,
         'sigma_source': 'test', 'settings': dict(se.DEFAULT_SETTINGS),
         'sweep_thresholds': [3, 5], 'sweeps': [], 'repeats': {},
         'frames': [dict(frame), dict(frame), dict(frame)],
         'baseline_disc': _auto_ref(577.1, cx=960.0, cy=540.0,
                                    mm_per_px=16.0 / 577.1),
         'scale_anchor': None}
    d['settings']['diam_mm'] = 16.0
    d.update(over)
    return d


def test_diag_reports_new_and_old_anchors_without_a_detection_pass():
    """The diagnostic's anchor verdicts read straight off setup.txt, so
    they must hold for a three-round anchor, a two-click anchor and no
    anchor -- the whole corpus, unchanged, on one code path."""
    import sldea_diag as sd

    def heads(anchor):
        return [h for _s, h, _d in
                sd.verdicts(_diag_d(scale_anchor=anchor))]

    def detail(anchor, needle):
        return [dt for _s, h, dt in
                sd.verdicts(_diag_d(scale_anchor=anchor)) if needle in h]

    # (a) a good three-round anchor: guard clear, repeatability reported
    good = {'method': 'manual-calibration', 'diam_px': 577.1,
            'diam_mm': 16.0, 'mm_per_px': 16.0 / 577.1, 'n_rounds': 3,
            'rounds_px': [576.8, 577.4, 577.1], 'spread_px': 0.6,
            'spread_pct': 0.104, 'guard': 'clear (auto +0.00% diam)'}
    hs = heads(good)
    assert not any('outside the ~1% sanity guard' in h for h in hs)
    assert any('Operator repeatability' in h for h in hs)
    assert '576.8, 577.4, 577.1 px' in detail(good, 'repeatability')[0]

    # (b) P3_2's recorded anchor: the guard fires, MED, with the numbers
    p3_2 = {'method': 'manual-calibration', 'diam_px': P3_2_MANUAL_PX,
            'diam_mm': 16.0, 'mm_per_px': 16.0 / P3_2_MANUAL_PX,
            'auto_diam_px': 577.1, 'saved': '2026-08-06T09:14:02'}
    vs = sd.verdicts(_diag_d(scale_anchor=p3_2))
    hit = [(s, h, dt) for s, h, dt in vs
           if 'sanity guard' in h]
    assert len(hit) == 1 and hit[0][0] == 'MED'
    assert '201.06' in hit[0][2] and '-4.4' in hit[0][2]
    # ... and it says the repeatability number is simply absent
    assert any('no repeatability record' in h for _s, h, _d in vs)
    assert not any('Operator repeatability' in h for _s, h, _d in vs)

    # (c) a loose three-round anchor gets MED on repeatability, not on
    # the guard (precision and accuracy are different findings)
    loose = dict(good, spread_pct=2.4, spread_px=13.9)
    sev = [s for s, h, _d in sd.verdicts(_diag_d(scale_anchor=loose))
           if 'Operator repeatability' in h]
    assert sev == ['MED']

    # (d) no anchor at all -- pre-gate runs still produce verdicts
    vs = sd.verdicts(_diag_d(scale_anchor=None))
    assert any('cross-check anchor available' in h for _s, h, _d in vs)
    assert not any('sanity guard' in h for _s, h, _d in vs)
    assert not any('repeatability record' in h for _s, h, _d in vs)
    # (e) no automatic fit either: nothing is invented
    vs = sd.verdicts(_diag_d(baseline_disc=None, scale_anchor=None))
    assert any('No scale reference at all' in h for _s, h, _d in vs)
    assert not any('sanity guard' in h for _s, h, _d in vs)
    # (f) an anchor with NO automatic fit to check it against: reported
    # as uncheckable, never as clean
    vs = sd.verdicts(_diag_d(baseline_disc=None, scale_anchor=p3_2))
    assert any('automatic cross-check unavailable' in h
               for _s, h, _d in vs)
    assert not any('sanity guard' in h for _s, h, _d in vs)


def test_diag_text_report_prints_the_anchor_block_for_both_eras():
    import sldea_diag as sd
    d = _diag_d(scale_anchor={'method': 'manual-calibration',
                              'diam_px': 577.1, 'diam_mm': 16.0,
                              'mm_per_px': 16.0 / 577.1, 'n_rounds': 3,
                              'rounds_px': [576.8, 577.4, 577.1],
                              'spread_px': 0.6, 'spread_pct': 0.104,
                              'guard': 'clear (auto +0.00% diam)',
                              'saved': '2026-08-06T10:00:00'})
    txt = sd.report(d)
    assert 'saved anchor    : 577.1 px = 16 mm' in txt
    assert 'rounds        : 576.8, 577.4, 577.1 px' in txt
    assert 'guard: clear' in txt
    # the two-click era prints the same block minus the rounds
    old = dict(d['scale_anchor'])
    for k in ('n_rounds', 'rounds_px', 'spread_px', 'spread_pct', 'guard'):
        old.pop(k)
    txt = sd.report(dict(d, scale_anchor=old))
    assert 'saved anchor    : 577.1 px' in txt
    assert 'none recorded (pre-2026-08-06 two-click anchor' in txt
    # and a pre-gate run prints no anchor block at all, without raising
    txt = sd.report(dict(d, scale_anchor=None))
    assert 'saved anchor' not in txt


def test_gui_constants_agree_with_the_shared_ones():
    """The dialog must not carry its own copy of the round count or the
    spread gate -- one number, one place."""
    import sldea_edge_gui as gui
    assert gui.CAL_ROUNDS is se.CAL_ROUNDS
    assert gui.CAL_MAX_ROUNDS > se.CAL_ROUNDS
    assert se.ANCHOR_GUARD_DIAM_PCT == 1.0
    assert se.ANCHOR_GUARD_AREA_PCT == 1.0
    assert se.ANCHOR_MODAL_DIAM_PCT > se.ANCHOR_GUARD_DIAM_PCT
    # the spawn arithmetic keeps the circle in the ROI without relying
    # on the clamp: max radius + max jitter must stay under half the ROI
    assert (gui.CAL_SPAWN_R_FRAC[1] + gui.CAL_SPAWN_JITTER) < 0.5
    assert gui.CAL_SPAWN_R_FRAC[0] < gui.CAL_SPAWN_R_FRAC[1]
    # ... and every spawn diameter sits inside the plausibility window,
    # so no round can open on a circle its own Continue would refuse
    assert (2 * gui.CAL_SPAWN_R_FRAC[1]) < gui.CAL_MAX_DIAM_FRAC
    assert (2 * gui.CAL_SPAWN_R_FRAC[0]) > gui.CAL_MIN_DIAM_FRAC


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
