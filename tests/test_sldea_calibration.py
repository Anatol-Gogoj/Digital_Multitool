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
    # an UNAVAILABLE cross-check is recorded as a gap, in the same voice
    # as a trip -- never as a quiet nil (review 2026-08-06, finding 3)
    gone = se.anchor_guard(500.0, None, MASK_MM)
    assert se.anchor_guard_note(gone, False) == \
        'NOT CROSS-CHECKED: no automatic disc fit was available'
    assert se.anchor_guard_note(gone, True).startswith('NOT CROSS-CHECKED')
    assert 'accepted anyway by operator' in se.anchor_guard_note(gone, True)
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
    assert se.CAL_ROUNDS == 3


def test_adding_a_round_can_never_clear_the_spread_gate():
    """Review 2026-08-06 (minor 5): the gate statistic is a RANGE, and
    max-min cannot shrink when a fit is added, so the dialog's old "Add
    another round?" offer could not clear the gate it was offered for --
    it always landed on "Accept the mean anyway?" instead. A test that
    built a FRESH tight 4-value list hid that; a 4th round APPENDS.

    The range is kept as the recorded statistic on purpose:
    SLDEA_MEASUREMENT 2.1a converts it into the budget's error term
    (sigma ~ R/1.693, mean SE ~ R/2.93, area ~ R/1.47). What changed is
    the remedy the dialog offers -- a refit, which can clear it."""
    loose = [575.0, 590.0, 582.0]
    assert not se.spread_ok(se.calibration_stats(loose))
    # every possible 4th value, inside the range and far outside it
    for extra in (575.0, 578.0, 582.0, 582.3333, 590.0, 400.0, 900.0):
        s4 = se.calibration_stats(loose + [extra])
        assert not se.spread_ok(s4), (extra, s4['spread_pct'])
    # the floor is structural: 100*(max-min)/max, whatever n becomes
    s = se.calibration_stats(loose + [582.0] * 50)
    assert s['n'] == 53
    assert s['spread_pct'] >= 100.0 * 15.0 / 590.0 > se.CAL_SPREAD_PCT
    # ... whereas a REFIT starts a new set, which can pass
    assert se.spread_ok(se.calibration_stats([581.0, 582.0, 583.0]))


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
    # as uncheckable, never as clean -- and ABOVE OK, because 'cross-check
    # unavailable' at OK severity is the shape of finding that gets
    # skimmed past (review 2026-08-06, finding 3). Nothing else on this
    # run ever checks the anchor, in the app or in this report.
    vs = sd.verdicts(_diag_d(baseline_disc=None, scale_anchor=p3_2))
    hit = [(s, h, dt) for s, h, dt in vs if 'cross-check' in h]
    assert len(hit) == 1, hit
    assert hit[0][0] == 'MED', hit[0]
    assert 'never been cross-checked' in hit[0][1], hit[0]
    assert 'mask' in hit[0][2] and 'unverified' in hit[0][2]
    assert not any('sanity guard' in h for _s, h, _d in vs)

    # (g) finding 4 (review 2026-08-06): the three-round spread needs no
    # automatic fit to be judged -- it is a property of the three fits
    # alone. Nested inside `if ref and anchor` it was emitted at NO
    # severity on exactly the runs where baseline_disc refuses, i.e. the
    # runs with no automatic reference at all.
    for kw in ({'baseline_disc': None}, {}):
        vs = sd.verdicts(_diag_d(scale_anchor=good, **kw))
        rep = [(s, h) for s, h, _d in vs if 'Operator repeatability' in h]
        assert len(rep) == 1, (kw, vs)
        assert rep[0][0] == 'OK', rep
        vs = sd.verdicts(_diag_d(scale_anchor=loose, **kw))
        rep = [s for s, h, _d in vs if 'Operator repeatability' in h]
        assert rep == ['MED'], (kw, rep)
        # ... and the two-click era's ABSENCE is reported with or without
        # an automatic fit too
        vs = sd.verdicts(_diag_d(scale_anchor=p3_2, **kw))
        assert any('no repeatability record' in h for _s, h, _d in vs)
    # it must not fire without an anchor to report on, in either case
    for kw in ({'baseline_disc': None}, {}):
        vs = sd.verdicts(_diag_d(scale_anchor=None, **kw))
        assert not any('repeatability record' in h for _s, h, _d in vs)
        assert not any('Operator repeatability' in h for _s, h, _d in vs)
    # the verdict says out loud that the number is not budget-ready
    vs = sd.verdicts(_diag_d(scale_anchor=good, baseline_disc=None))
    dt = [t for _s, h, t in vs if 'Operator repeatability' in h][0]
    assert 'DO NOT feed this into the error budget' in dt


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
    # the round count is FIXED since review 2026-08-06: the spread gate's
    # remedy is a refit, not an extra round (a range cannot shrink), so
    # there is no variable-round cap to keep in sync any more
    assert not hasattr(gui, 'CAL_MAX_ROUNDS')
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


# ---------------------------------------------------------------------------
# MODE B and the n-aware statistics (2026-08-06 evening)
#
# The operator drove mode A six times on a scratch copy of P3_2 and the
# recorded 3-round ranges were 1.94, 2.09, 1.62, 1.81, 1.44 % plus one
# under 1 % -- per-fit sigma ~ 1.05 %, i.e. a 3-round mean SE of 0.61 %
# diameter / 1.21 % area against SLDEA_MEASUREMENT 2.1's ~0.4 % / ~0.8 %.
# Mode B is the alternative that gets A/B'd against it, and the statistics
# had to stop hard-wiring n = 3 before either could be judged.
# ---------------------------------------------------------------------------

# The measured mode-A ranges, from the `#215` comment of 2026-08-06.
MODE_A_RANGES_PCT = (1.94, 2.09, 1.62, 1.81, 1.44)


def test_d2_lookup_matches_the_published_factors():
    """The control-chart d2 factors (ASTM E2587 / Duncan), by lookup. The
    n=3 value 1.693 is the one SLDEA_MEASUREMENT 2.1a was written around,
    so it is the anchor of the table."""
    assert se.d2(3) == 1.693
    for n, f in ((2, 1.128), (4, 2.059), (5, 2.326), (6, 2.534),
                 (7, 2.704), (8, 2.847)):
        assert se.d2(n) == f, (n, se.d2(n))
    # monotonic: more samples, wider expected range
    fs = [se.d2(n) for n in sorted(se.D2_RANGE_FACTORS)]
    assert fs == sorted(fs) and len(set(fs)) == len(fs)


def test_d2_REFUSES_outside_the_table_instead_of_guessing():
    """THE POINT of the lookup. 2.1a used to hard-wire the n=3 constants
    (R/1.693, R/2.93, R/1.47); with the round count configurable those are
    wrong for every other n, and a silent fallback -- nearest neighbour, an
    interpolation, or just reusing 1.693 -- would push a wrong error term
    into the budget with nobody seeing it happen."""
    for n in (0, 1, 9, 12, 100, -3):
        assert se.d2(n) is None, n
    for junk in (None, '', 'five', object()):
        assert se.d2(junk) is None, junk
    # and the refusal propagates: no sigma, no SE, no area SE -- all None
    # TOGETHER, never a zero that reads as perfect precision
    s1 = se.calibration_stats([577.0])
    assert s1['n'] == 1 and s1['d2'] is None
    for k in ('sigma_px', 'sigma_pct', 'se_px', 'se_pct', 'area_se_pct'):
        assert s1[k] is None, k
    # a single round PASSES the old range gate vacuously (there is no
    # range) but must NOT pass the SE gate -- nothing was computed to judge
    assert se.spread_ok(s1) is True
    assert se.se_ok(s1) is None
    assert se.sigma_from_range(1.0, 9) is None
    assert se.sigma_from_range(None, 3) is None


def test_sigma_and_se_arithmetic_at_several_n():
    """sigma = R/d2(n), mean SE = sigma/sqrt(n), area SE = 2 x mean SE --
    checked at four round counts, because the whole failure mode this
    replaces was arithmetic that only held at n = 3."""
    for n in (2, 3, 4, 5, 6, 7, 8):
        # a set whose range is exactly 10 px on a mean of 1000 px = 1.00 %
        vals = [995.0] + [1000.0] * (n - 2) + [1005.0]
        s = se.calibration_stats(vals)
        assert s['n'] == n
        assert abs(s['spread_pct'] - 1.0) < 1e-9
        assert abs(s['sigma_pct'] - 1.0 / se.d2(n)) < 1e-9, n
        assert abs(s['se_pct'] - s['sigma_pct'] / math.sqrt(n)) < 1e-12
        assert abs(s['area_se_pct'] - 2.0 * s['se_pct']) < 1e-12
        # px and % agree with each other
        assert abs(s['sigma_px'] / s['mean'] * 100 - s['sigma_pct']) < 1e-9
        assert abs(s['se_px'] / s['mean'] * 100 - s['se_pct']) < 1e-9

    # the SAME range means DIFFERENT precision at different n -- which is
    # exactly why a range gate could not survive a configurable n
    s3 = se.calibration_stats([995.0, 1000.0, 1005.0])
    s5 = se.calibration_stats([995.0, 1000.0, 1000.0, 1000.0, 1005.0])
    assert s3['spread_pct'] == s5['spread_pct']
    assert s5['sigma_pct'] < s3['sigma_pct']
    assert abs(s3['sigma_pct'] / s5['sigma_pct']
               - se.d2(5) / se.d2(3)) < 1e-9        # 1.37x

    # read-back path: sigma from a RECORDED range + n, no diameters needed
    assert abs(se.sigma_from_range(1.0, 3) - 1.0 / 1.693) < 1e-12
    assert abs(se.sigma_from_range(2.4, 3) - 2.4 / 1.693) < 1e-12


def test_the_measured_mode_A_numbers_reproduce_the_issues_conversion():
    """The five recorded mode-A ranges convert to the sigmas quoted on the
    issue, and to a 3-round mean SE outside SLDEA_MEASUREMENT 2.1's
    budget. If this ever stops holding, the premise of mode B is gone."""
    sigmas = [se.sigma_from_range(r, 3) for r in MODE_A_RANGES_PCT]
    for got, want in zip(sigmas, (1.15, 1.23, 0.96, 1.07, 0.85)):
        assert abs(got - want) < 0.01, (got, want)
    # the issue's headline figure is the MEAN of the five (1.05 %); its
    # median is 1.07 %, quoted there too
    sigma = sum(sigmas) / len(sigmas)
    assert abs(sigma - 1.05) < 0.01, sigma
    assert abs(sorted(sigmas)[len(sigmas) // 2] - 1.07) < 0.01
    # at that per-fit precision, 3 rounds MISSES the budget ...
    se3 = sigma / math.sqrt(3)
    assert 0.60 < se3 < 0.62 and se3 > se.CAL_SE_PCT
    assert 1.20 < 2 * se3 < 1.24            # % area, vs the ~0.8 % budget
    # ... and it would take ~7 rounds to reach it, which is the number the
    # issue quotes and the number the gate's own remedy must name (at the
    # median it is 8 -- either way, more than anyone will sit through)
    assert se.rounds_for_se(sigma) == 7
    assert se.rounds_for_se(sorted(sigmas)[len(sigmas) // 2]) == 8
    # mode B's target: sigma < 0.9 % puts 5 rounds essentially on budget
    assert 0.9 / math.sqrt(5) < 0.41
    assert se.rounds_for_se(0.894) == 5


def test_the_gate_is_the_SE_not_the_range_and_can_be_cleared():
    """The gate change (2026-08-06 evening). Two properties a range gate
    could not have: it is comparable across n, and its own remedy can
    clear it -- `test_adding_a_round_can_never_clear_the_spread_gate` pins
    the defect this fixes."""
    assert se.CAL_SE_PCT == 0.4          # derived from 2.1, not measured
    tight = se.calibration_stats([999.0, 1000.0, 1001.0])   # SE 0.068 %
    loose = se.calibration_stats([980.0, 1000.0, 1020.0])   # SE 1.36 %
    assert se.se_ok(tight) is True and tight['se_pct'] < se.CAL_SE_PCT
    assert se.se_ok(loose) is False
    # exactly at the gate passes (the gate is "exceeds")
    n = 4
    mean = 1000.0
    rng = se.CAL_SE_PCT * math.sqrt(n) * se.d2(n) / 100.0 * mean
    edge = se.calibration_stats([mean - rng / 2.0] + [mean] * (n - 2)
                                + [mean + rng / 2.0])
    assert abs(edge['se_pct'] - se.CAL_SE_PCT) < 1e-9
    assert se.se_ok(edge) is True

    # THE MONOTONICITY THE RANGE GATE LACKED. Holding the per-fit scatter
    # fixed at the measured mode-A value (sigma ~ 1 % of 600 px), the
    # EXPECTED mean SE falls through the gate between n=3 and n=8:
    #   0.577 % at n=3 (over) -> 0.354 % at n=8 (under).
    # So more rounds is a real remedy here. It was not for the range: the
    # range GROWS with n, which is what
    # test_adding_a_round_can_never_clear_the_spread_gate pins.
    assert 1.0 / math.sqrt(3) > se.CAL_SE_PCT > 1.0 / math.sqrt(8)
    rnd = random.Random(20260806)
    trips = {3: 0, 5: 0, 8: 0}
    N = 600
    for _ in range(N):
        for n in sorted(trips):
            fits = [rnd.gauss(600.0, 6.0) for _ in range(n)]
            if se.se_ok(se.calibration_stats(fits)) is False:
                trips[n] += 1
    # The SE estimate is itself noisy (the range of a few samples is a
    # scatter), so this is a rate claim, not a certainty -- the
    # deterministic version is the assertion above. What matters is the
    # DIRECTION: the same operator precision trips the gate far more often
    # at 3 rounds than at 8, and the rate falls all the way down.
    assert trips[3] > N * 0.6, trips              # ~70 %
    assert trips[8] < N * 0.4, trips              # ~32 %
    assert trips[3] > trips[5] > trips[8], trips
    assert trips[3] > 2 * trips[8], trips


def test_rounds_for_se_names_the_remedy_and_admits_when_there_is_none():
    assert se.rounds_for_se(0.4) == 2       # already at the gate; n>=2
    assert se.rounds_for_se(0.8) == 4
    assert se.rounds_for_se(1.05) == 7
    assert se.rounds_for_se(2.0) == 25       # NOT clipped to the table:
    assert se.rounds_for_se(2.0) > max(se.D2_RANGE_FACTORS)   # a caller
    # must be able to say "this method cannot reach budget", not be handed
    # a quietly clipped 8
    for junk in (0, -1, None, '', 'x'):
        assert se.rounds_for_se(junk) is None, junk


def test_mode_constants_are_shared_and_the_defaults_are_per_mode():
    import sldea_edge_gui as gui
    # NAMES, not letters (2026-08-06 late). The recorded value has to be
    # self-describing because the LABELS have already been renumbered once
    # and the old letters are on disk -- see the legacy-mapping test below.
    assert se.CAL_MODES == ('verify', 'circle', 'twopoint')
    assert se.CAL_MANUAL_MODES == ('circle', 'twopoint')
    assert se.CAL_MODE_ROUNDS[se.CAL_MODE_CIRCLE] == se.CAL_ROUNDS == 3
    assert se.CAL_MODE_ROUNDS[se.CAL_MODE_TWOPOINT] == 5
    # the verify mode has NO round count, deliberately: a 1 in this table
    # would read as "one round" and invite sigma/SE to be computed for a
    # sample of one
    assert se.CAL_MODE_VERIFY not in se.CAL_MODE_ROUNDS
    # the circle stays the MANUAL default (what the verify mode falls back
    # to): switching it would change every existing hand-calibration path
    # silently.
    assert se.CAL_DEFAULT_MODE == se.CAL_MODE_CIRCLE
    # every per-mode default has a d2 factor, or its own gate could never
    # be applied to it
    for n in se.CAL_MODE_ROUNDS.values():
        assert se.d2(n) is not None, n
    assert gui.CAL_ROUNDS_TWOPOINT is se.CAL_ROUNDS_TWOPOINT
    assert gui.CAL_STROKE_STYLES[0] == '3 px solid'   # circle unchanged
    # THE LABELS, and the swap that made them (operator 2026-08-06 late):
    # A is the mode the gate OPENS in, so the first letter and the default
    # are the same thing. Presentation only -- nothing writes these.
    assert se.CAL_MODE_LABELS == {'verify': 'A', 'circle': 'B',
                                  'twopoint': 'C'}
    assert se.CAL_MODE_LABELS[se.cal_open_mode(_auto_ref())] == 'A'
    # every mode has exactly one label and no two share one
    assert sorted(se.CAL_MODE_LABELS) == sorted(se.CAL_MODES)
    assert len(set(se.CAL_MODE_LABELS.values())) == len(se.CAL_MODES)


def test_the_gate_opens_on_mode_C_only_when_there_is_a_fit_to_verify():
    """`#215` 2026-08-06 evening: the machine measures and the operator
    verifies — but only where the machine produced something. A refused fit
    cannot be verified, so the gate must fall through to the hand
    measurement rather than opening an empty mode C."""
    assert se.cal_open_mode(_auto_ref()) == se.CAL_MODE_VERIFY
    for none_ish in (None, {}, {'diam_px': 0.0}, {'diam_px': None},
                     {'method': 'baseline-disc'}):
        assert se.cal_open_mode(none_ish) == se.CAL_DEFAULT_MODE, none_ish
    assert se.cal_open_mode(None) in se.CAL_MANUAL_MODES


# ---------------------------------------------------------------------------
# mode B geometry: rotate for display, measure in ORIGINAL coordinates
# ---------------------------------------------------------------------------

def test_rotation_angles_are_stratified_over_the_whole_circle():
    """Rotation is the mechanism, so it has to actually happen. n
    independent uniform draws can cluster; one draw per equal sector
    cannot. The whole circle, not a half: the human bias toward horizontal
    and vertical chords is 90-degree periodic."""
    import sldea_edge_gui as gui
    for n in (2, 3, 5, 8):
        angs = gui.rotation_angles(n, random.Random(7 + n))
        assert len(angs) == n
        assert all(0.0 <= a < 360.0 for a in angs), angs
        # exactly one angle per sector, whatever order they came out in
        sectors = sorted(int(a // (360.0 / n)) for a in angs)
        assert sectors == list(range(n)), (n, angs)
    # shuffled, so the order carries no information about the round
    orders = set()
    for seed in range(40):
        angs = gui.rotation_angles(5, random.Random(seed))
        orders.add(tuple(sorted(range(5),
                                key=lambda i: angs[i])))
    assert len(orders) > 10, orders
    # and consecutive rounds really are far apart on average
    angs = gui.rotation_angles(5, random.Random(3))
    assert max(angs) - min(angs) > 180.0


def test_clicks_map_back_through_the_rotation_to_the_same_diameter():
    """A synthetic disc rotated by a KNOWN angle must yield the same
    diameter. Driven against PIL's real Image.rotate, not against a
    re-derivation of it: the markers are located in the ROTATED pixels the
    operator would click on, then unrotated.

    Length is rotation-invariant, so this is really a check that the
    inverse mapping matches PIL's forward one -- sign convention included,
    which is the one thing that would silently produce plausible-looking
    wrong numbers."""
    import numpy as np
    from PIL import Image
    import sldea_edge_gui as gui
    W, H = 320, 240
    p1, p2 = (60.0, 130.0), (250.0, 96.0)       # a 193.0 px chord
    truth = gui.two_point_diameter(p1, p2)
    assert abs(truth - 193.018) < 0.01

    def centroid(mask):
        ys, xs = np.nonzero(mask)
        assert len(xs), "marker lost in the rotation -- test is broken"
        return float(xs.mean()), float(ys.mean())

    worst_pt, worst_d = 0.0, 0.0
    for deg in (0.0, 17.0, 37.4, 90.0, 123.5, 180.0, 201.8, 270.0,
                318.6, 359.2):
        a = np.zeros((H, W), np.uint8)
        for (px, py), val in ((p1, 255), (p2, 128)):
            a[int(py) - 2:int(py) + 3, int(px) - 2:int(px) + 3] = val
        rot = Image.fromarray(a).rotate(deg, resample=Image.NEAREST,
                                        expand=True)
        ra = np.asarray(rot).astype(float)
        q1 = gui.unrotate_point(*centroid(ra > 200), rot_w=rot.width,
                                rot_h=rot.height, img_w=W, img_h=H, deg=deg)
        q2 = gui.unrotate_point(*centroid((ra > 60) & (ra <= 200)),
                                rot_w=rot.width, rot_h=rot.height,
                                img_w=W, img_h=H, deg=deg)
        worst_pt = max(worst_pt, math.dist(q1, p1), math.dist(q2, p2))
        worst_d = max(worst_d,
                      abs(gui.two_point_diameter(q1, q2) - truth))
    # the recovered POINTS carry PIL's expand rounding (ceil/floor on the
    # new canvas size, up to ~1.5 px) plus NEAREST pixel quantization ...
    assert worst_pt < 2.0, worst_pt
    # ... but that offset is a pure TRANSLATION, so it cancels in the
    # DIFFERENCE and the measured diameter is good to well under a pixel.
    # This is the property that makes rotating the display safe at all.
    assert worst_d < 0.5, worst_d
    # a zero rotation is the identity, exactly
    for (px, py) in (p1, p2, (0.0, 0.0), (W, H)):
        gx, gy = gui.unrotate_point(px, py, W, H, W, H, 0.0)
        assert abs(gx - px) < 1e-9 and abs(gy - py) < 1e-9


def test_two_point_diameter_is_rotation_invariant_by_construction():
    import sldea_edge_gui as gui
    assert gui.two_point_diameter((0, 0), (3, 4)) == 5.0
    assert gui.two_point_diameter((3, 4), (0, 0)) == 5.0     # symmetric
    assert gui.two_point_diameter((5, 5), (5, 5)) == 0.0
    # the same chord measured in rotated coordinates gives the same length
    for deg in (11.0, 47.0, 143.0, 299.0):
        ph = math.radians(deg)
        def rot(p):
            return (p[0] * math.cos(ph) - p[1] * math.sin(ph),
                    p[0] * math.sin(ph) + p[1] * math.cos(ph))
        a, b = (12.0, -30.0), (200.0, 61.0)
        assert abs(gui.two_point_diameter(rot(a), rot(b))
                   - gui.two_point_diameter(a, b)) < 1e-9


def test_markers_do_not_occlude_the_point_being_judged():
    """The whole reason mode B exists. The operator's diagnosis of mode A's
    1.05 % scatter was that "the bright green circle occludes the edges" --
    a 3 px stroke laid along the boundary hides the feature being aligned
    to. So mode B's marker must leave the judged pixel visible: a hollow
    ring and a crosshair with a HOLE in it, never a filled dot."""
    import sldea_edge_gui as gui
    for vx, vy in ((0.0, 0.0), (120.0, 80.5), (-40.0, 900.0)):
        sh = gui.marker_shapes(vx, vy)
        clear = gui.marker_clear_radius(vx, vy, sh)
        assert clear >= gui.CAL_MARK_GAP_VIEW, (vx, vy, clear)
        assert clear > 0.0
        # the ring is CENTRED on the click and hollow: the click point is
        # strictly inside it, so no ink of the ring lands on it
        x0, y0, x1, y1 = sh['ring']
        assert abs((x0 + x1) / 2.0 - vx) < 1e-9
        assert abs((y0 + y1) / 2.0 - vy) < 1e-9
        assert (x1 - x0) / 2.0 == gui.CAL_MARK_RING_VIEW
        # four arms, all pointing away, none crossing the centre
        assert len(sh['arms']) == 4
        for ax0, ay0, ax1, ay1 in sh['arms']:
            near = min(math.dist((ax0, ay0), (vx, vy)),
                       math.dist((ax1, ay1), (vx, vy)))
            far = max(math.dist((ax0, ay0), (vx, vy)),
                      math.dist((ax1, ay1), (vx, vy)))
            assert abs(near - gui.CAL_MARK_GAP_VIEW) < 1e-9
            assert abs(far - gui.CAL_MARK_ARM_VIEW) < 1e-9
    # the chord stops short of BOTH endpoints, so its ink misses them too
    seg = gui.chord_segment((100.0, 100.0), (300.0, 100.0))
    assert seg is not None
    assert abs(seg[0] - 103.0) < 1e-9 and abs(seg[2] - 297.0) < 1e-9
    # ... and a degenerate pair draws no chord at all rather than a blob
    assert gui.chord_segment((10.0, 10.0), (11.0, 10.0)) is None


def test_mode_A_stroke_option_is_the_third_arm_and_defaults_unchanged():
    """If occlusion is really the cause of mode A's scatter, a 1 px or
    dashed stroke may rescue mode A -- worth testing while an operator is
    measuring. The 3 px solid stroke stays the DEFAULT, so mode A's
    behaviour is unchanged unless the option is touched."""
    import sldea_edge_gui as gui
    assert gui.cal_stroke_spec('3 px solid') == (3, None)
    assert gui.cal_stroke_spec('1 px solid') == (1, None)
    w, dash = gui.cal_stroke_spec('1 px dashed')
    assert w == 1 and dash and len(dash) == 2
    # unknown styles fall back to the default rather than raising: a stroke
    # width is not worth losing a calibration over
    for junk in ('', None, 'hairline', 42):
        assert gui.cal_stroke_spec(junk) == (3, None), junk
    assert all(s in gui.CAL_STROKE_STYLES
               for s in ('3 px solid', '1 px solid', '1 px dashed'))


# ---------------------------------------------------------------------------
# the calibration log -- the capture that was missing last time
# ---------------------------------------------------------------------------

def _stats_b(n=5):
    return se.calibration_stats([588.3, 591.0, 589.4, 590.2, 587.9][:n])


def test_log_line_leads_with_sigma_and_states_the_mode():
    """The one-line summary the operator reports an A/B result with. sigma
    leads because sigma is the only figure comparable between two modes run
    at different round counts."""
    s = _stats_b()
    line = se.calibration_log_line({
        'when': '2026-08-06T14:22:31', 'mode': se.CAL_MODE_TWOPOINT,
        'stats': s, 'gate': se.CAL_SE_PCT, 'verdict': 'PASS',
        'rot_deg': [37.4, 201.8, 95.2, 318.6, 144.0],
        'auto_diam_px': 577.1, 'auto_pct': 2.12,
        'outcome': 'accepted', 'frame': 'base.png'})
    # mode= is a NAME (2026-08-06 late), in the same position as before:
    # the field ORDER is unchanged, only that field's value space moved,
    # because a stored letter changed meaning when the labels were swapped.
    assert line.startswith('SLDEA-CAL 2026-08-06T14:22:31 mode=twopoint '
                           'n=5 ')
    # a LEGACY letter handed to the formatter is read with its PRE-SWAP
    # meaning and written out as the name, so one file never mixes both
    legacy = se.calibration_log_line({
        'when': 'T', 'mode': 'B', 'stats': s, 'outcome': 'accepted'})
    assert ' mode=twopoint ' in legacy and 'mode=B' not in legacy
    assert 'sigma=0.23%' in line
    assert 'se=0.10%' in line and 'area_se=0.20%' in line
    assert 'gate=0.40%' in line and 'verdict=PASS' in line
    assert 'range=0.53%' in line and 'mean=589.36px' in line
    assert 'diams=588.30,591.00,589.40,590.20,587.90px' in line
    assert 'rot=37.4,201.8,95.2,318.6,144.0deg' in line
    assert 'auto=577.1px(+2.12%)' in line
    assert 'outcome=accepted' in line and 'frame=base.png' in line
    # ONE line, always -- a stray newline would split one record in two
    assert '\n' not in line and '\r' not in line
    # the circle carries the stroke style instead of rotations, and the
    # line keeps the same SHAPE either way so a column splitter cannot slip
    a = se.calibration_log_line({'when': 'T', 'mode': se.CAL_MODE_CIRCLE,
                                 'stats': se.calibration_stats(
                                     [580.0, 584.0, 582.0]),
                                 'verdict': 'OVER-GATE',
                                 'stroke': '1 px dashed',
                                 'outcome': 'declined-refit'})
    assert 'mode=circle n=3' in a and 'stroke=1 px dashed' in a
    assert 'rot=-deg' in a and 'auto=none' in a
    assert 'verdict=OVER-GATE' in a


def test_log_line_says_unconvertible_rather_than_inventing_a_sigma():
    """n=1 has no d2 factor, so there is no sigma, no SE and no verdict --
    and the line has to SAY that rather than print a zero."""
    line = se.calibration_log_line({'when': 'T', 'mode': 'B',
                                    'stats': se.calibration_stats([590.0]),
                                    'verdict': None,
                                    'outcome': 'declined-unjudgeable'})
    assert 'n=1' in line
    assert 'sigma=unconvertible' in line and 'se=unconvertible' in line
    assert 'area_se=unconvertible' in line
    assert 'verdict=UNJUDGEABLE' in line
    assert '0.00%' not in line.split('range=')[0]


def test_log_appends_every_round_set_accepted_or_declined():
    """The gap this closes: the six mode-A spreads that motivated mode B
    survive only because they were typed into a chat. Every one of those
    calibrations was DECLINED at a gate, and setup.txt is written at Save,
    so the run recorded nothing at all."""
    d = tempfile.mkdtemp(prefix='cal_log_')
    try:
        C, T = se.CAL_MODE_CIRCLE, se.CAL_MODE_TWOPOINT
        recs = [(C, 'declined-cancel'), (C, 'declined-refit'),
                (T, 'accepted'), (T, 'accepted-override')]
        for mode, outcome in recs:
            path, line = se.append_calibration_log(d, {
                'when': '2026-08-06T00:00:00', 'mode': mode,
                'stats': _stats_b(3 if mode == C else 5),
                'gate': se.CAL_SE_PCT, 'verdict': 'PASS',
                'rot_deg': [1.0, 2.0] if mode == T else None,
                'outcome': outcome})
            assert path and os.path.basename(path) == se.CAL_LOG_NAME
            assert outcome in line
        with open(path, encoding='utf-8') as f:
            body = f.read()
        lines = [ln for ln in body.splitlines() if ln.startswith('SLDEA-CAL')]
        assert len(lines) == 4, lines
        # DECLINED sets are in there -- that is the whole point
        assert sum('outcome=declined' in ln for ln in lines) == 2
        assert sum('mode=circle n=3' in ln for ln in lines) == 2
        assert sum('mode=twopoint n=5' in ln for ln in lines) == 2
        # a header explains the columns exactly once, on creation -- and it
        # documents the LEGACY LETTERS, because a reader grepping a mixed
        # file has to know that a bare letter is a pre-swap one
        assert body.count('# SLDEA Edge Review scale calibrations') == 1
        assert 'Compare methods on SIGMA' in body
        assert se.CAL_LOG_VOCAB_MARK in body
        assert 'A = circle, B = twopoint, C = verify' in body
        # no migration note in a file this build created: that note exists
        # only to mark where an EXISTING file changes vocabulary
        assert body.count(se.CAL_LOG_VOCAB_MARK) == 1
        # ASCII-safe: this file gets grepped and pasted into issues
        body.encode('ascii')
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_log_write_failure_costs_the_file_not_the_measurement():
    """The run folder can be read-only or full (the 2026-08-04 disk-full
    incident). A logging error must never be how a calibration is lost, so
    the line comes back regardless and the caller prints it to stdout."""
    gone = os.path.join(tempfile.gettempdir(),
                        'no_such_dir_' + os.urandom(4).hex())
    path, line = se.append_calibration_log(
        gone, {'when': 'T', 'mode': se.CAL_MODE_TWOPOINT,
               'stats': _stats_b(), 'outcome': 'accepted'})
    assert path is None
    assert line.startswith('SLDEA-CAL') and 'mode=twopoint' in line
    # no rundir at all (a run that was never opened) is the same story
    path, line = se.append_calibration_log(
        None, {'when': 'T', 'mode': se.CAL_MODE_CIRCLE,
               'stats': _stats_b(3), 'outcome': 'accepted'})
    assert path is None and 'mode=circle' in line


def test_mode_and_conversion_round_trip_into_setup_txt():
    """cal_mode / sigma_pct / se_pct persist with the anchor: a bare range
    cannot be converted later by anyone who does not also know n, and
    nothing records which METHOD produced an anchor otherwise.

    `method` must stay exactly 'manual-calibration' -- se.mm_per_px matches
    it against that string to give a hand calibration priority over every
    automatic reference, so a mode suffix there would silently demote every
    mode-B anchor back below the disc fit."""
    d = tempfile.mkdtemp(prefix='cal_mode_')
    try:
        _setup(d)
        s = _stats_b()
        se.save_scale_anchor(d, {
            'method': 'manual-calibration',
            'cal_mode': se.CAL_MODE_TWOPOINT,
            'diam_px': s['mean'], 'diam_mm': 16.0,
            'mm_per_px': 16.0 / s['mean'], 'n_rounds': s['n'],
            'rounds_px': s['values'], 'spread_px': s['spread_px'],
            'spread_pct': s['spread_pct'], 'sigma_pct': s['sigma_pct'],
            'se_pct': s['se_pct'], 'guard': 'clear (auto +0.00% diam)'})
        back = se.load_scale_anchor(d)
        # the exact string mm_per_px matches on, so a mode-B anchor still
        # beats every automatic reference at Save
        assert back['method'] == 'manual-calibration'
        assert back['cal_mode'] == se.CAL_MODE_TWOPOINT == 'twopoint'
        assert back['n_rounds'] == 5 and len(back['rounds_px']) == 5
        assert abs(back['sigma_pct'] - s['sigma_pct']) < 0.005
        assert abs(back['se_pct'] - s['se_pct']) < 0.005
        # a mode-A/two-click anchor with none of these still loads
        _setup(d)
        se.save_scale_anchor(d, {'method': 'manual-calibration',
                                 'diam_px': 577.1, 'diam_mm': 16.0,
                                 'mm_per_px': 16.0 / 577.1})
        old = se.load_scale_anchor(d)
        assert old['diam_px'] == 577.1
        for k in ('cal_mode', 'sigma_pct', 'se_pct'):
            assert k not in old, k
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_diag_judges_the_SE_and_names_the_method():
    """sldea_diag reads the anchor off setup.txt, so its repeatability
    verdict has to be n-aware too -- and it derives sigma from the RECORDED
    range and n, because rounds_px is optional and the persisted range is
    the statistic the anchor carries."""
    import sldea_diag as sd

    def one(anchor, needle='repeatability'):
        return [(s, h, dt) for s, h, dt in
                sd.verdicts(_diag_d(scale_anchor=anchor)) if needle in h]

    base = {'method': 'manual-calibration', 'diam_px': 577.1,
            'diam_mm': 16.0, 'mm_per_px': 16.0 / 577.1,
            'guard': 'clear (auto +0.00% diam)'}
    # a mode-B anchor at n=5 whose range is 1.0 %: sigma 0.43 %, SE 0.19 %
    good = dict(base, cal_mode=se.CAL_MODE_TWOPOINT, n_rounds=5,
                spread_pct=1.0, spread_px=5.8,
                rounds_px=[575, 576, 577, 578, 580])
    hit = one(good, 'Operator repeatability')
    assert len(hit) == 1 and hit[0][0] == 'OK', hit
    assert 'sigma 0.43%/fit' in hit[0][1], hit[0][1]
    assert 'mean SE 0.19%' in hit[0][1], hit[0][1]
    # NAMED with letter AND name: the letter matches the dialog the
    # operator used, the name matches the record and survives a relabelling
    assert 'method C (twopoint)' in hit[0][2], hit[0][2]
    assert 'DO NOT feed this into the error budget' in hit[0][2]
    # the SAME 1.0 % range at n=3 is WORSE precision, and that shows
    at3 = dict(base, cal_mode=se.CAL_MODE_CIRCLE, n_rounds=3,
               spread_pct=1.0, spread_px=5.8)
    hit3 = one(at3, 'Operator repeatability')
    assert 'sigma 0.59%/fit' in hit3[0][1], hit3[0][1]
    assert 'mean SE 0.34%' in hit3[0][1], hit3[0][1]
    assert hit3[0][0] == 'OK'
    # the measured mode-A reality: a 1.94 % range at n=3 misses the budget
    real = dict(base, cal_mode=se.CAL_MODE_CIRCLE, n_rounds=3,
                spread_pct=1.94, spread_px=11.2)
    hitr = one(real, 'Operator repeatability')
    assert hitr[0][0] == 'MED', hitr
    assert f"over the {se.CAL_SE_PCT:g}% gate" in hitr[0][1]
    # an n with NO d2 factor is reported as a GAP, above OK -- never as a
    # pass, and never with an invented sigma
    bad = dict(base, cal_mode=se.CAL_MODE_TWOPOINT, n_rounds=9,
               spread_pct=1.0, spread_px=5.8)
    hitb = one(bad, 'cannot be converted')
    assert len(hitb) == 1 and hitb[0][0] == 'MED', hitb
    assert 'no d2 factor for n=9' in hitb[0][1]
    # and NO judged verdict is emitted alongside it: nothing was computed,
    # so nothing may be reported as inside or outside the budget
    assert not one(bad, 'mean SE')
    assert not any('gate' in h for _s, h, _d in
                   sd.verdicts(_diag_d(scale_anchor=bad))
                   if 'repeatability' in h)
    # ... and the text report prints the conversion, or says there is none
    txt = sd.report(_diag_d(scale_anchor=good))
    assert 'method C (twopoint)' in txt and 'sigma 0.43%/fit' in txt
    txt = sd.report(_diag_d(scale_anchor=bad))
    assert 'no d2 factor for n=9' in txt


# ---------------------------------------------------------------------------
# MODE C -- the machine measures, the operator VERIFIES (2026-08-06 evening)
#
# The A/B/A' experiment inverted the premise: on P3_2's baseline the
# automatic fit (577.08 px, circ 0.999, conf 0.871, residual 2.3 px, 204
# edge points) beat ALL ELEVEN hand calibrations on accuracy and nine of
# eleven on precision. Everything below pins the honesty of the mode that
# follows from that, because its whole risk is claiming a verification it
# did not perform.
# ---------------------------------------------------------------------------

P3_2_FIT = {'method': 'baseline-disc', 'diam_px': 577.08, 'cx': 960.0,
            'cy': 540.0, 'area_px': math.pi * (577.08 / 2.0) ** 2,
            'circ': 0.999, 'conf': 0.871, 'fit_resid_px': 2.3,
            'n_edge': 204, 'arc_cov': 1.0, 'solidity': 0.99,
            'paper_lum': 186.0}


def test_verify_stats_writes_UNDEFINED_not_zero():
    """A mode-C anchor is ONE automatic fit. sigma, the mean SE and the
    range do not exist for a sample of one, and writing 0 for them would
    read as PERFECT PRECISION everywhere downstream -- the log line, the
    status line, sldea_diag. None is a refusal to state a number; 0.00 % is
    a claim. calibration_stats([d]) would honestly return the latter, which
    is exactly why verify_stats exists."""
    s = se.verify_stats(P3_2_FIT)
    assert s['n'] == 1 and s['mean'] == 577.08 and s['values'] == [577.08]
    assert s['single_fit'] is True
    for k in ('spread_px', 'spread_pct', 'd2', 'sigma_px', 'sigma_pct',
              'se_px', 'se_pct', 'area_se_pct'):
        assert s[k] is None, (k, s[k])
    # and the contrast: the generic stats function DOES say 0.00 %, which
    # is why it must not be used here
    naive = se.calibration_stats([577.08])
    assert naive['spread_pct'] == 0.0
    # the gate refuses to judge either of them -- never True
    assert se.se_ok(s) is None and se.se_ok(naive) is None
    for junk in (None, {}, {'diam_px': 0}, {'diam_px': None}):
        assert se.verify_stats(junk) is None, junk


def test_fit_resid_pct_is_the_fits_own_uncertainty_not_a_repeatability_term():
    """An auto-verified anchor's uncertainty is the FIT's residual, not an
    operator spread. On P3_2's baseline that is 2.3 px on 577.08 px = 0.40 %
    of diameter, which lands on SLDEA_MEASUREMENT 2.1's ~0.4 % budget."""
    rp = se.fit_resid_pct(P3_2_FIT)
    assert abs(rp - 0.3985) < 0.001, rp
    assert abs(rp - 0.4) < 0.01                  # the quotable figure
    for junk in (None, {}, {'diam_px': 577.0}, {'fit_resid_px': 2.3},
                 {'diam_px': 0, 'fit_resid_px': 2.3}):
        assert se.fit_resid_pct(junk) is None, junk


def test_the_anchor_guard_is_VACUOUS_on_an_autofit_derived_anchor():
    """THE HONEST CONSTRAINT. Declaring the fitted disc to be diam_mm makes
    the resting area pi*(diam_mm/2)^2 BY CONSTRUCTION, so anchor_guard's two
    tests both read exactly 0.00 % on a mode-C anchor -- on ANY frame,
    however wrong the fit is. It is a check that cannot fail, and a green
    tick from it would be a claim of verification the code never performed.

    Demonstrated rather than asserted: the identity is exercised over a
    range of fitted diameters, including absurd ones."""
    for d in (12.0, 100.0, 577.08, 900.0):
        ref = dict(P3_2_FIT, diam_px=d,
                   area_px=math.pi * (d / 2.0) ** 2)
        g = se.anchor_guard(d, ref, MASK_MM)
        assert g['available'] is True
        assert abs(g['diam_pct']) < 1e-9, (d, g['diam_pct'])
        assert abs(g['area_pct']) < 1e-9, (d, g['area_pct'])
        assert g['warn'] == [], (d, g['warn'])
        # ... and the implied resting area is the mask's, exactly, always
        assert abs(g['rest_area_mm2'] - MASK_AREA_MM2) < 1e-6, d
    # so it must be flagged and not run
    assert se.guard_is_vacuous({'method': se.ANCHOR_METHOD_VERIFIED})
    for other in ({'method': se.ANCHOR_METHOD_MANUAL}, {}, None,
                  {'method': 'baseline-disc'}):
        assert not se.guard_is_vacuous(other), other


def test_the_two_anchor_methods_are_distinct_and_both_override():
    """PROVENANCE. Anyone auditing a run must be able to tell 'a human
    MEASURED this' from 'a human APPROVED the machine's measurement' -- two
    different claims with different failure modes. Both still beat every
    automatic reference at Save, because both are decisions a person is
    answerable for; only the provenance differs."""
    assert se.ANCHOR_METHOD_MANUAL == 'manual-calibration'
    assert se.ANCHOR_METHOD_VERIFIED == 'auto-verified'
    assert se.ANCHOR_METHODS == (se.ANCHOR_METHOD_MANUAL,
                                se.ANCHOR_METHOD_VERIFIED)
    rows = [{'tag': 'baseline'}, {'tag': 'post-ramp'}]
    # a baseline-row detection at a DIFFERENT diameter must not outrank
    # either kind of human-signed anchor (the 2026-08-05 audit's bug)
    results = {0: {'diam_px': 500.0, 'area_px': 1.0}}
    st = {'diam_mm': 16.0}
    for method in se.ANCHOR_METHODS:
        anchor = {'method': method, 'diam_px': 577.08}
        assert abs(se.mm_per_px(results, rows, st, anchor)
                   - 16.0 / 577.08) < 1e-12, method
        assert method in se.scale_source(results, rows, anchor), method
    # an automatic fit passed in as baseline_ref still loses to the
    # baseline row, exactly as before
    assert abs(se.mm_per_px(results, rows, st, dict(P3_2_FIT))
               - 16.0 / 500.0) < 1e-12


def test_verify_note_records_who_approved_what_and_what_was_not_checked():
    note = se.verify_note(P3_2_FIT, 'anatol', '2026-08-06T18:30:00')
    note.encode('ascii')                     # setup.txt field, one line
    assert '\n' not in note and '\r' not in note
    assert note.startswith('AUTO-VERIFIED')
    for needle in ('577.1 px', 'circ 0.999', 'conf 0.871', 'resid 2.3px',
                   '204 edge pts', 'anatol', '2026-08-06T18:30:00'):
        assert needle in note, (needle, note)
    # the vacuity, in words, in the run's own record
    assert 'NOT cross-checked' in note
    assert 'vacuous' in note and 'human eye' in note
    # a fit with no quality numbers still produces a usable line
    bare = se.verify_note({'diam_px': 577.08})
    bare.encode('ascii')
    assert 'AUTO-VERIFIED' in bare and 'NOT cross-checked' in bare


def test_mode_C_log_line_says_undefined_and_leaves_A_and_B_untouched():
    """The log's existing format is load-bearing, so the verify mode extends
    it rather than changing it: the measuring modes' lines keep every field
    in every position, and the verify mode's precision columns read
    `undefined` -- not `0.00%` (perfect precision) and not `unconvertible`
    (which means a number exists that the d2 table cannot convert; here the
    quantity itself does not exist).

    The ONE field whose value space moved is `mode=`, which now holds a name
    (2026-08-06 late) because a stored letter changed meaning when the
    labels were swapped. Its position is unchanged."""
    stats = se.verify_stats(P3_2_FIT)
    rec = {'when': '2026-08-06T18:30:00', 'mode': se.CAL_MODE_VERIFY,
           'stats': stats, 'gate': se.CAL_SE_PCT, 'verdict': 'NOT-GATED',
           'auto_diam_px': P3_2_FIT['diam_px'], 'auto_pct': None,
           'fit_circ': 0.999, 'fit_conf': 0.871, 'fit_resid_px': 2.3,
           'fit_arc_cov': 1.0, 'fit_n_edge': 204,
           'fit_resid_pct': se.fit_resid_pct(P3_2_FIT),
           'outcome': 'accepted-verified', 'frame': 'base.png'}
    line = se.calibration_log_line(rec)
    assert 'mode=verify' in line and 'n=1' in line
    for f in ('sigma=undefined', 'se=undefined', 'area_se=undefined',
              'range=undefined'):
        assert f in line, (f, line)
    assert '0.00%' not in line, line          # nothing reads as perfect
    assert 'unconvertible' not in line, line  # the OTHER kind of gap
    assert 'verdict=NOT-GATED' in line
    # the deviation column would be +0.00% by construction, so it is not
    # printed as agreement
    assert 'auto=577.1px(IS-the-anchor)' in line, line
    assert '(+0.00%)' not in line
    # the fit's real quality figures are there instead
    for f in ('circ=0.999', 'conf=0.871', 'resid=2.3px', 'arc=1.00',
              'n_edge=204', 'resid_pct=0.40%'):
        assert f in line, (f, line)
    # and an A line is exactly what it was before mode C existed
    a = se.calibration_log_line({
        'when': 'W', 'mode': se.CAL_MODE_CIRCLE, 'stats':
            se.calibration_stats([570.0, 575.0, 580.0]), 'gate': 0.4,
        'verdict': 'PASS', 'auto_diam_px': 577.1, 'auto_pct': -0.35,
        'stroke': '3 px solid', 'outcome': 'accepted', 'frame': 'b.png'})
    assert ('SLDEA-CAL W mode=circle n=3 sigma=1.03% se=0.59% '
            'area_se=1.19% gate=0.40% verdict=PASS range=1.74% '
            'mean=575.00px diams=570.00,575.00,580.00px rot=-deg '
            'stroke=3 px solid auto=577.1px(-0.35%) outcome=accepted '
            'frame=b.png') == a, a
    assert 'circ=' not in a and 'resid_pct=' not in a
    # ... and every field is in the position it was in before the mode=
    # value changed, so an existing splitter still finds each one
    old = ('SLDEA-CAL W mode=A n=3 sigma=1.03% se=0.59% area_se=1.19% '
           'gate=0.40% verdict=PASS range=1.74% mean=575.00px '
           'diams=570.00,575.00,580.00px rot=-deg stroke=3 px solid '
           'auto=577.1px(-0.35%) outcome=accepted frame=b.png')
    got_keys = [b.split('=')[0] for b in a.split(' ') if '=' in b]
    old_keys = [b.split('=')[0] for b in old.split(' ') if '=' in b]
    assert got_keys == old_keys, (got_keys, old_keys)


def test_auto_verified_anchor_round_trips_through_setup_txt():
    """The fit's quality numbers and the human who approved them have to
    survive into setup.txt and back, and the 15 two-click anchors and the
    two runs with no block at all have to keep loading unchanged."""
    d = tempfile.mkdtemp(prefix='cal_verified_')
    try:
        _setup(d)
        se.save_scale_anchor(d, {
            'method': se.ANCHOR_METHOD_VERIFIED,
            'cal_mode': se.CAL_MODE_VERIFY,
            'diam_px': P3_2_FIT['diam_px'], 'diam_mm': 16.0,
            'mm_per_px': 16.0 / P3_2_FIT['diam_px'],
            'anchor_frame': 'base.png', 'anchor_is_baseline': True,
            'auto_diam_px': P3_2_FIT['diam_px'],
            'fit_circ': 0.999, 'fit_conf': 0.871, 'fit_resid_px': 2.3,
            'fit_arc_cov': 1.0, 'fit_n_edge': 204,
            'verified_by': 'anatol', 'verified_at': '2026-08-06T18:30:00',
            'guard': se.verify_note(P3_2_FIT, 'anatol',
                                    '2026-08-06T18:30:00')})
        back = se.load_scale_anchor(d)
        assert back['method'] == se.ANCHOR_METHOD_VERIFIED
        assert back['cal_mode'] == se.CAL_MODE_VERIFY == 'verify'
        assert abs(back['diam_px'] - 577.08) < 0.01
        assert abs(back['fit_circ'] - 0.999) < 1e-9
        assert abs(back['fit_resid_px'] - 2.3) < 1e-9
        assert back['fit_n_edge'] == 204 and isinstance(back['fit_n_edge'],
                                                       int)
        assert back['verified_by'] == 'anatol'
        assert back['verified_at'] == '2026-08-06T18:30:00'
        assert 'NOT cross-checked' in back['guard']
        # NO rounds, NO spread -- they were never written, so they are
        # absent rather than zero
        for k in ('n_rounds', 'rounds_px', 'spread_px', 'spread_pct',
                  'sigma_pct', 'se_pct'):
            assert k not in back, k
        # it still overrides every automatic reference
        assert se._is_manual_cal(back)
        # a two-click anchor written over it loses the fit_* keys entirely
        se.save_scale_anchor(d, {'method': se.ANCHOR_METHOD_MANUAL,
                                 'diam_px': 590.26, 'diam_mm': 16.0,
                                 'mm_per_px': 16.0 / 590.26})
        old = se.load_scale_anchor(d)
        assert old['method'] == se.ANCHOR_METHOD_MANUAL
        for k in ('fit_circ', 'fit_n_edge', 'verified_by', 'verified_at'):
            assert k not in old, k
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_baseline_disc_names_the_GATE_that_refused_it():
    """`baseline_disc` returns a bare None, which is right for every
    automatic caller and useless to an operator being sent to measure by
    hand instead. Mode C quotes the reason, so the reason has to be real:
    'the arc covers only 87 degrees' sends them to move whatever is lying
    across the frame, 'the diameter is outside the plausible range' sends
    them to the camera zoom."""
    import numpy as np
    s = dict(se.DEFAULT_SETTINGS)
    s['diam_mm'] = 16.0
    yy, xx = np.mgrid[0:240, 0:320]

    def gray(f):
        return np.clip(f, 0, 255).astype(np.uint8)

    # (a) a real disc fits, and there is NO refusal on record for it
    ok = np.full((240, 320), 190.0)
    ok[(xx - 160) ** 2 + (yy - 120) ** 2 <= 80 * 80] = 165.0
    assert se.baseline_disc(gray(ok), s) is not None
    assert se.baseline_disc_refusal(gray(ok), s) is None
    # (b) a flat field: nothing to seed on, and it SAYS so
    flat = np.full((240, 320), 190.0)
    assert se.baseline_disc(gray(flat), s) is None
    why = se.baseline_disc_refusal(gray(flat), s)
    assert why and 'seed' in why, why
    # (c) a dark BAR, not a disc: round enough to seed, not round enough to
    # pass -- the circularity or arc gate, named either way
    bar = np.full((240, 320), 190.0)
    bar[100:140, 40:280] = 165.0
    assert se.baseline_disc(gray(bar), s) is None
    why = se.baseline_disc_refusal(gray(bar), s)
    assert why, 'a refusal with no reason is the thing this closes'
    assert any(w in why for w in ('circularity', 'arc', 'residual', 'fill',
                                  'plausible', 'ray', 'edge points')), why
    # (d) no frame at all
    assert se.baseline_disc(None, s) is None
    assert 'no readable baseline' in (se.baseline_disc_refusal(None, s) or '')
    # every reason is one plain sentence an operator can act on
    for g in (flat, bar):
        r = se.baseline_disc_refusal(gray(g), s)
        assert r and r[0].islower() and '\n' not in r, r


def test_contrast_stretch_is_measured_from_the_frame_and_refuses_a_flat_one():
    """The 20-gray step on a 186 background is nearly invisible, so mode C
    stretches the DISPLAY. The window comes from the frame's own measured
    disc and paper levels (the exposure moves between runs -- the carbon-
    black baseline medians 255), and it REFUSES when there is no step:
    amplifying noise into a visible edge is the one failure this feature
    must not have."""
    import numpy as np
    import sldea_edge_gui as gui
    yy, xx = np.mgrid[0:240, 0:320]
    a = np.full((240, 320), 186.0)
    a[(xx - 160) ** 2 + (yy - 120) ** 2 <= 80 * 80] = 166.0
    assert gui.disc_paper_lum(a, 160, 120, 80) == (166.0, 186.0)
    lo, hi = gui.cal_stretch_window(166.0, 186.0)
    # the ~160-192 window that makes a P3 baseline's step visible
    assert 150 <= lo <= 165 and 188 <= hi <= 200, (lo, hi)
    assert lo < 166.0 and hi > 186.0
    # NO STRETCH when there is no step to stretch
    for dl, pl in ((186.0, 186.0), (190.0, 186.0), (183.0, 186.0),
                   (None, 186.0), (166.0, None), (None, None)):
        assert gui.cal_stretch_window(dl, pl) is None, (dl, pl)
    # a saturated frame (the CB baseline) has no measurable step either
    sat = np.full((240, 320), 255.0)
    dl, pl = gui.disc_paper_lum(sat, 160, 120, 80)
    assert gui.cal_stretch_window(dl, pl) is None
    # the LUT maps the window across the full range, clipping outside
    lut = gui.cal_stretch_lut(157.0, 195.0)
    assert len(lut) == 256 and lut[0] == 0 and lut[255] == 255
    assert lut[157] == 0 and lut[195] == 255
    assert 0 < lut[176] < 255 and lut[166] < lut[176] < lut[186]
    assert all(0 <= v <= 255 for v in lut)
    assert all(lut[i] <= lut[i + 1] for i in range(255))   # monotone
    # a degenerate window cannot produce a divide-by-zero or an inversion
    for a_, b_ in ((100.0, 100.0), (200.0, 10.0), (-5.0, 999.0)):
        L = gui.cal_stretch_lut(a_, b_)
        assert len(L) == 256 and all(0 <= v <= 255 for v in L), (a_, b_)
    # and a garbage geometry gets no window rather than a wrong one
    assert gui.disc_paper_lum(a, 160, 120, 0) == (None, None)
    assert gui.disc_paper_lum(np.zeros((4, 4)), 2, 2, 1) == (None, None)


def test_verify_evidence_is_four_lines_and_still_says_the_honest_part():
    """The text the operator judges on, pinned as text so both its BUDGET
    and its honesty are tests rather than a screenshot.

    Four lines was the budget after the first declutter (`#215`, 2026-08-06
    late); the screen is now normally TWO. The verify mode was driven on a
    real disc and the fit was accepted as correct -- the premise held -- but
    the screen carried 13 lines of prose wrapping to 19 and the operator's
    verdict was "wayyyyy too busy with text and unnecessary garbage", and
    then that the surviving standing sentence ("View is contrast-stretched
    so the edge is visible... your eye is the check.") was unnecessary too.
    It was: on every normal run it said the same two things, and a
    disclaimer that is always true is one nobody reads.

    So what is left is the value adopted and two quality numbers, plus two
    CONDITIONAL lines: a warning when the contrast stretch could not be
    computed (a fault in the picture, false on a normal run) and the
    consequence line when a prior anchor actually differs. The budget stays
    at four because the pathological case can still reach it.

    THE HONESTY DID NOT GO ANYWHERE -- it moved to the record, which is
    pinned at the other end by
    test_verify_note_and_the_log_keep_every_number_the_screen_dropped."""
    import sldea_edge_gui as gui
    t = gui.verify_evidence(P3_2_FIT, 16.0, recorded=None, n_px_rows=0,
                            stretch=(157.0, 195.0))
    lines = t.split('\n')
    assert gui.CAL_VERIFY_MAX_LINES == 4
    # TWO lines in the normal case: no prior anchor and a working stretch
    assert len(lines) == 2, lines
    for ln in lines:
        assert ln.strip() and len(ln) <= 200, (len(ln), ln)
    # 1. THE VALUE: exactly the number the run's whole mm2 column hangs on
    assert lines[0] == ("Automatic fit \u2014 577.1 px across = 16.00 mm "
                        "(0.027726 mm/px)"), lines[0]
    # 2. THE QUALITY: two numbers, the two that would make a reader doubt
    #    the fit -- residual as a PERCENTAGE of diameter, and circularity
    assert '0.40 % of diameter' in lines[1] and '0.999' in lines[1]
    assert lines[1].count('\u00b7') == 1, lines[1]
    # 3. THE STANDING DISCLAIMER IS GONE FROM THE SCREEN (operator
    #    2026-08-06 late). Not softened, not shortened -- absent.
    for dropped in ('contrast-stretched so the edge is visible',
                    'Nothing cross-checks it', 'your eye is the check',
                    'measured on the raw frame'):
        assert dropped not in t, dropped
    # ... and no claim that anything passed
    for lie in ('cross-check passed', 'verified against', 'agrees with the '
                'mask', '\u2713', '+0.00'):
        assert lie not in t, lie
    # WHAT IS NO LONGER ON SCREEN. conf goes because it is DERIVED from the
    # same residual/circularity/coverage quantities -- it is not an
    # independent number and there is nothing a human can do with it.
    for gone in ('conf', '0.871', 'edge point', '204', 'arc coverage',
                 'interior fill', 'resting area', '201.06', 'ALL ELEVEN',
                 'BY CONSTRUCTION', 'press Z', 'below 1:1', 'UNCERTAINTY',
                 'HOW TO JUDGE', 'repeatab'):
        assert gone not in t, gone
    # A FRAME WITH NO MEASURABLE STEP still says so, and this is the one
    # thing the dropped sentence used to carry that had to stay: it is not a
    # standing disclaimer but a fault in the picture the whole verification
    # rests on, and it is false on a normal run.
    t_raw = gui.verify_evidence(P3_2_FIT, 16.0, stretch=None)
    raw_lines = t_raw.split('\n')
    assert len(raw_lines) == 3, t_raw
    assert 'NOT contrast-stretched' in raw_lines[2]
    assert 'too faint to judge' in raw_lines[2]
    # 4. THE CONSEQUENCE, and only when there is one. P3_2's own case seen
    #    from the other side: the fit is 2.23 % BELOW the two-click anchor,
    #    so accepting moves every mm2 up 4.62 %.
    t2 = gui.verify_evidence(P3_2_FIT, 16.0,
                             recorded={'diam_px': 590.26,
                                       'saved': '2026-08-06'},
                             n_px_rows=12, stretch=(157.0, 195.0))
    l2 = t2.split('\n')
    assert len(l2) == 3, l2
    assert '-2.23 %' in l2[-1] and '+4.62 %' in l2[-1], l2[-1]
    assert 'next Save' in l2[-1] and '590.3 px on record' in l2[-1]
    # THE WORST CASE -- both conditional lines at once -- still fits the
    # budget, which is why the budget stays at four rather than dropping
    worst = gui.verify_evidence(P3_2_FIT, 16.0,
                                recorded={'diam_px': 590.26, 'saved': 'x'},
                                n_px_rows=12, stretch=None,
                                diam_recorded=False)
    assert len(worst.split('\n')) == gui.CAL_VERIFY_MAX_LINES, worst
    # SILENCE where silence is correct. No prior anchor: nothing to compare
    # against, so nothing is said -- not a paragraph explaining the absence.
    assert len(gui.verify_evidence(P3_2_FIT, 16.0, n_px_rows=9,
                                   stretch=(157.0, 195.0))
               .split('\n')) == 2
    # A prior anchor that does NOT differ: "+0.00 %" is a claim dressed as a
    # measurement, so the line is absent rather than zero.
    same = gui.verify_evidence(P3_2_FIT, 16.0,
                               recorded={'diam_px': 577.08, 'saved': 'x'},
                               n_px_rows=12, stretch=(157.0, 195.0))
    assert len(same.split('\n')) == 2, same
    assert 'Accepting moves' not in same, same
    # ... and one just past the epsilon IS reported
    eps = 577.08 * (1.0 + 2.0 * gui.CAL_VERIFY_DEV_EPS_PCT / 100.0)
    near = gui.verify_evidence(P3_2_FIT, 16.0,
                               recorded={'diam_px': eps, 'saved': 'x'},
                               n_px_rows=12, stretch=(157.0, 195.0))
    assert len(near.split('\n')) == 3, near
    # the gate label is hidden in the verify mode, so its "diameter was NOT
    # recorded at capture" warning rides on the value line -- not its own
    nd = gui.verify_evidence(P3_2_FIT, 16.0, stretch=(157.0, 195.0),
                             diam_recorded=False)
    assert len(nd.split('\n')) == 2, nd
    assert 'settings default' in nd.split('\n')[0]
    assert 'NOT measured at capture' in nd.split('\n')[0]
    # a fitter that reported no quality numbers must not print zeros
    bare = gui.verify_evidence({'diam_px': 100.0}, 16.0,
                               stretch=(157.0, 195.0))
    assert len(bare.split('\n')) == 2, bare
    assert '0.000' not in bare and '0.00 %' not in bare, bare
    assert 'nothing here to judge the fit by but the picture' in bare
    # and a fit that does not exist produces nothing to approve
    for junk in (None, {}, {'diam_px': 0}):
        assert gui.verify_evidence(junk, 16.0) == '', junk


def test_a_stored_mode_LETTER_keeps_its_pre_swap_meaning():
    """THE MIGRATION, and the trap it exists for (`#215`, 2026-08-06 late).

    The dialog's mode letters were renumbered at the operator's request --
    A = verify, B = circle, C = twopoint, where before the swap A was the
    circle, B the two-point and C the verify. THE OLD LETTERS ARE ON DISK:
    `P3_2_2.5mL_20260728/setup.txt` records `cal_mode: C` AND
    `prev_cal_mode: C`, both written when C meant verify, and that run's
    scale_calibration_log.txt holds eight `mode=C` lines with the same
    meaning. Reinterpreting a stored letter against the NEW labels would
    turn every one of them into a claim that the operator clicked two points
    on a run where they approved an automatic fit.

    Two things stop that, and both are asserted here: the record now holds a
    self-describing NAME so no future relabelling can reach it, and every
    read of a legacy letter goes through cal_mode_read with the PRE-SWAP
    mapping."""
    # THE RULE
    assert se.CAL_MODE_LEGACY == {'A': 'circle', 'B': 'twopoint',
                                  'C': 'verify'}
    assert se.cal_mode_read('A') == se.CAL_MODE_CIRCLE
    assert se.cal_mode_read('B') == se.CAL_MODE_TWOPOINT
    assert se.cal_mode_read('C') == se.CAL_MODE_VERIFY
    # P3_2's ACTUAL stored value, which is the whole point of this test
    assert se.cal_mode_read('C') == 'verify'
    assert se.cal_mode_label('C') == 'A'          # verify's label today
    assert se.cal_mode_text('C') == 'A (verify)'
    # the legacy letter must NOT be read against the CURRENT labels
    assert se.cal_mode_read('C') != se.CAL_MODE_TWOPOINT
    assert se.cal_mode_read('A') != se.CAL_MODE_VERIFY
    # a NAME reads as itself, and is idempotent under a second read
    for name in se.CAL_MODES:
        assert se.cal_mode_read(name) == name
        assert se.cal_mode_read(se.cal_mode_read(name)) == name
        assert se.cal_mode_label(name) == se.CAL_MODE_LABELS[name]
    # nothing is INVENTED for a token that names no method -- a hand-edited
    # setup.txt is a fact of bench life
    for junk in (None, '', '  ', 'D', 'Z', 'circle-ish', 42):
        assert se.cal_mode_read(junk) is None, junk
        assert se.cal_mode_label(junk) == '?', junk
    assert se.cal_mode_read('nonsense', default='kept') == 'kept'
    assert 'unrecognised' in se.cal_mode_text('nonsense')

    # ---- and END TO END, through P3_2's real anchor block ----------------
    d = tempfile.mkdtemp(prefix='cal_legacy_')
    try:
        _setup(d)
        # written by hand exactly as the live run holds it: the LETTER, in
        # both the anchor's own field and the re-anchor's previous-mode field
        path = os.path.join(d, 'setup.txt')
        with open(path, 'a', encoding='utf-8') as f:
            f.write('\n' + se.ANCHOR_HDR + '\n'
                    'method: auto-verified\n'
                    'cal_mode: C\n'
                    'diam_px: 577.078\n'
                    'diam_mm: 16\n'
                    'mm_per_px: 0.0277259\n'
                    'reanchor: scale-only\n'
                    'prev_method: auto-verified\n'
                    'prev_cal_mode: C\n')
        back = se.load_scale_anchor(d)
        # NORMALISED AT THE BOUNDARY, so no reader downstream can forget
        assert back['cal_mode'] == se.CAL_MODE_VERIFY, back['cal_mode']
        assert back['prev_cal_mode'] == se.CAL_MODE_VERIFY
        assert back['diam_px'] == 577.078
        # sldea_diag names it correctly rather than calling it two-point
        import sldea_diag as sd
        rep = '\n'.join(sd.verdicts(_diag_d(scale_anchor=back))[i][2]
                         for i in range(len(sd.verdicts(
                             _diag_d(scale_anchor=back)))))
        assert 'twopoint' not in rep, rep
        # and a re-save writes the NAME -- a correct translation of what the
        # letter meant, not a letter whose meaning has since changed
        se.save_scale_anchor(d, dict(back))
        text = open(path, encoding='utf-8').read()
        assert 'cal_mode: verify' in text, text
        assert 'prev_cal_mode: verify' in text
        assert 'cal_mode: C' not in text
        # the re-anchor's provenance builder carries the name too, from a
        # block that still holds the letter
        fields = se.reanchor_anchor_fields({'method': 'auto-verified',
                                           'cal_mode': 'C',
                                           'diam_px': 577.078}, {})
        assert fields['prev_cal_mode'] == se.CAL_MODE_VERIFY
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_an_existing_log_file_is_told_where_its_vocabulary_changes():
    """A run that was calibrated before the letters became names already has
    a scale_calibration_log.txt full of `mode=C` lines (live P3_2 has
    eight). Appending `mode=verify` under a header that says "mode=C the
    operator VERIFIED" would leave the file self-contradicting, so the file
    gets ONE note marking where its vocabulary changes -- written once, and
    never for a file this build created."""
    d = tempfile.mkdtemp(prefix='cal_log_migrate_')
    try:
        legacy = os.path.join(d, se.CAL_LOG_NAME)
        # P3_2's real first line, letter and all
        with open(legacy, 'w', encoding='utf-8') as f:
            f.write('# SLDEA Edge Review scale calibrations, one line per '
                    'completed round-set, accepted or declined.\n'
                    '# mode=A circle fit, mode=B two-point diameter with '
                    'the display randomly rotated per round,\n'
                    'SLDEA-CAL 2026-08-06T22:41:10 mode=C n=1 '
                    'sigma=undefined outcome=accepted-verified\n')
        rec = {'when': 'T', 'mode': se.CAL_MODE_VERIFY,
               'stats': se.verify_stats(P3_2_FIT), 'verdict': 'NOT-GATED',
               'outcome': 'accepted-verified'}
        se.append_calibration_log(d, rec)
        body = open(legacy, encoding='utf-8').read()
        assert body.count(se.CAL_LOG_VOCAB_MARK) == 1, body
        assert 'A = circle, B = twopoint, C = verify' in body
        # the note sits BETWEEN the old lines and the new one
        note_at = body.index(se.CAL_LOG_VOCAB_MARK)
        assert body.index('mode=C n=1') < note_at < body.index('mode=verify')
        # the old line is untouched -- this is a log, not a rewrite
        assert 'SLDEA-CAL 2026-08-06T22:41:10 mode=C n=1' in body
        # a SECOND append does not repeat the note
        se.append_calibration_log(d, rec)
        body2 = open(legacy, encoding='utf-8').read()
        assert body2.count(se.CAL_LOG_VOCAB_MARK) == 1, body2
        assert body2.count('mode=verify') == 2
        body2.encode('ascii')
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_verify_note_and_the_log_keep_every_number_the_screen_dropped():
    """THE OTHER HALF OF THE DECLUTTER. Four lines on screen is only
    acceptable because the record still carries everything -- a reader
    coming to this run months later has to be able to reconstruct why the
    anchor was trusted, and the dialog is not where they will look.

    So every number cut from the screen (`conf`, `n_edge`, arc coverage,
    interior fill, the implied resting area, the full cross-check algebra)
    is asserted present in the anchor record's `guard` line and in the
    calibration log line. If a future declutter reaches into
    se.verify_note or se.append_calibration_log, this fails."""
    import sldea_edge_gui as gui
    note = se.verify_note(P3_2_FIT, 'anatol', '2026-08-06T18:30:00')
    screen = gui.verify_evidence(P3_2_FIT, 16.0, stretch=(157.0, 195.0))
    # the quality numbers the screen no longer shows
    for kept in ('conf 0.871', 'circ 0.999', 'resid 2.3px', 'arc 1.00',
                 '204 edge pts', '577.1 px'):
        assert kept in note, kept
    assert 'conf' not in screen and 'edge pts' not in screen
    # the cross-check algebra, in full, where an auditor reads it
    for kept in ('NOT cross-checked', 'vacuous',
                 'pi*(d/2)^2 = pi*(d/2)^2', 'human eye'):
        assert kept in note, kept
    assert 'anatol' in note and '2026-08-06T18:30:00' in note
    note.encode('ascii')          # the record stays ASCII
    # and the LOG line carries the same, plus the residual as a percentage
    rec = {'when': '2026-08-06T18:30:00', 'mode': se.CAL_MODE_VERIFY,
           'stats': se.verify_stats(P3_2_FIT), 'gate': se.CAL_SE_PCT,
           'verdict': 'NOT-GATED', 'rot_deg': None, 'stroke': None,
           'auto_diam_px': P3_2_FIT['diam_px'], 'auto_pct': None,
           'outcome': 'accepted-verified', 'frame': 'base.png',
           'fit_circ': P3_2_FIT['circ'], 'fit_conf': P3_2_FIT['conf'],
           'fit_resid_px': P3_2_FIT['fit_resid_px'],
           'fit_arc_cov': P3_2_FIT['arc_cov'],
           'fit_n_edge': P3_2_FIT['n_edge'],
           'fit_resid_pct': se.fit_resid_pct(P3_2_FIT)}
    line = se.format_calibration_log(rec) if hasattr(
        se, 'format_calibration_log') else None
    if line is None:
        d = tempfile.mkdtemp(prefix='cal_log_')
        try:
            _p, line = se.append_calibration_log(d, rec)
        finally:
            shutil.rmtree(d, ignore_errors=True)
    for kept in ('mode=verify', 'conf=0.871', 'circ=0.999', 'n_edge=204',
                 'arc=1.00', 'resid=2.3px', 'resid_pct=0.40%',
                 'sigma=undefined', 'se=undefined', 'range=undefined',
                 'verdict=NOT-GATED', '(IS-the-anchor)'):
        assert kept in line, (kept, line)
    assert '0.00%' not in line, line


def test_verify_zoom_frames_the_circle_not_the_frame():
    """Mode C opens ALREADY ZOOMED, which is what removed the "below 1:1 --
    press Z before accepting" nag rather than hiding it.

    The nag was noise generated by a bad default: the view opened
    fit-to-FRAME, so on a 1080p frame the 577 px disc arrived 282 canvas px
    across and the operator was told off for it. The operator is judging ONE
    BOUNDARY, so the CIRCLE is what the view has to frame."""
    import sldea_edge_gui as gui
    # the real geometry: a 577 px disc, a 1000x760 canvas on a 1080p bench
    z = gui.verify_zoom(577.08, 1000, 760)
    span = 577.08 * z
    assert 0.75 * 760 <= span <= 760, span     # fills it, is not cropped
    assert z > 1.0, z                          # ... and above 1:1, so the
    #                                            nag it replaced could not
    #                                            fire even if it still existed
    # the SHORTER side governs, so the whole circle is on screen whichever
    # way the canvas is shaped
    assert gui.verify_zoom(577.08, 1000, 760) == \
        gui.verify_zoom(577.08, 760, 1000)
    # a disc WIDER than the canvas is shown whole rather than cropped to
    # 1:1: half a boundary cannot be verified at all
    z_big = gui.verify_zoom(2000.0, 1000, 760)
    assert z_big < 1.0 and 2000.0 * z_big <= 760, z_big
    # ... and a tiny one is not interpolated into fake detail
    assert gui.verify_zoom(4.0, 1000, 760) == gui.CAL_VERIFY_MAX_OPEN_ZOOM
    # no fit, no framing: the caller falls back to fitting the frame
    for junk in ((None, 1000, 760), (0, 1000, 760), (-5, 1000, 760),
                 (577.08, 0, 760), (577.08, 1000, 0),
                 (577.08, None, None)):
        assert gui.verify_zoom(*junk) is None, junk


def test_diag_tells_a_verified_anchor_from_a_measured_one():
    """`sldea_diag` is where a run is audited months later, so the
    provenance distinction has to be visible there -- and the vacuous
    cross-check must not be printed as a passing one."""
    import sldea_diag as sd
    verified = {'method': se.ANCHOR_METHOD_VERIFIED, 'cal_mode': 'C',
                'diam_px': 577.1, 'diam_mm': 16.0,
                'mm_per_px': 16.0 / 577.1, 'fit_circ': 0.999,
                'fit_conf': 0.871, 'fit_resid_px': 2.3, 'fit_arc_cov': 1.0,
                'fit_n_edge': 204, 'verified_by': 'anatol',
                'verified_at': '2026-08-06T18:30:00',
                'guard': se.verify_note(P3_2_FIT, 'anatol',
                                        '2026-08-06T18:30:00')}
    vs = sd.verdicts(_diag_d(scale_anchor=verified))
    heads = [h for _s, h, _d in vs]
    scale = [(s, h, dt) for s, h, dt in vs if 'VERIFIED by an operator' in h]
    assert len(scale) == 1, heads
    dt = scale[0][2]
    assert 'anatol' in dt and '2026-08-06T18:30:00' in dt
    assert 'circ 0.999' in dt and '204 edge points' in dt
    assert 'NOT CROSS-CHECKED' in dt and 'BY CONSTRUCTION' in dt
    # the % apart line for a MEASURED anchor must not appear for this one
    assert not any('recorded manual anchor' in h for h in heads), heads
    assert not any('sanity guard' in h for h in heads), heads
    assert '% apart in diameter' not in dt
    # no repeatability term, and NOT described as a missing record
    rep = [(s, h, d2) for s, h, d2 in vs if 'repeatab' in h.lower()]
    assert len(rep) == 1 and rep[0][0] == 'OK', rep
    assert 'VERIFIED automatic fit' in rep[0][1], rep[0][1]
    assert 'UNDEFINED' in rep[0][2] and 'rather than zero' in rep[0][2]
    assert 'contributes NOTHING' in rep[0][2]
    assert 'two-click era' not in rep[0][1]
    # a HAND anchor on the same run still gets both of its old verdicts
    hand = {'method': se.ANCHOR_METHOD_MANUAL, 'cal_mode': 'A',
            'diam_px': 577.1, 'diam_mm': 16.0, 'mm_per_px': 16.0 / 577.1,
            'n_rounds': 3, 'spread_pct': 0.5, 'spread_px': 2.9,
            'guard': 'clear (auto +0.00% diam, mask +0.00% area)'}
    hh = [h for _s, h, _d in sd.verdicts(_diag_d(scale_anchor=hand))]
    assert any('recorded manual anchor' in h for h in hh), hh
    assert any('Operator repeatability' in h for h in hh), hh
    # the TEXT report prints the provenance and the undefined precision
    txt = sd.report(_diag_d(scale_anchor=verified))
    assert 'AUTO-VERIFIED' in txt and 'auto-verified' in txt
    assert 'sigma/SE/range are UNDEFINED' in txt
    assert 'anatol' in txt and 'circ 0.999' in txt
    assert 'two-click' not in txt.split('VERDICTS')[0]


def test_the_folded_scale_action_states_which_one_it_will_do():
    """ONE SCALE BUTTON, TWO blast radii (operator 2026-08-06 late, `#215`).

    Calibrate... and Re-anchor scale... were folded because they open
    the same dialog. The hazard in folding them is that one WRITES data.csv
    the moment it is confirmed and the other does not, so the banner that
    names the intent is pinned as text: neither branch may borrow the
    other's promise."""
    import sldea_edge_gui as gui
    cal = gui.scale_intent_banner(gui.SCALE_INTENT_CALIBRATE)
    rea = gui.scale_intent_banner(gui.SCALE_INTENT_REANCHOR)
    assert cal != rea
    # the non-writing branch promises exactly that, and never the other
    assert 'CALIBRATE' in cal and 'next' in cal and 'Save' in cal
    assert 'NOTHING is written' in cal
    assert 'IMMEDIATELY' not in cal and 'RE-ANCHOR' not in cal
    # the writing branch says WRITES, up front, and does not offer Save as
    # a later moment when nothing is written -- there is no later moment
    assert 'RE-ANCHOR' in rea
    assert 'WRITTEN TO data.csv IMMEDIATELY' in rea
    assert 'NOTHING is written' not in rea
    # ... and it promises the numbers first, which is the confirmation
    assert 'before it commits' in rea
    # an unknown/absent intent falls back to the NON-writing wording: a
    # dialog that guessed the other way would announce a rewrite that is
    # not about to happen
    for junk in (None, '', 'something-else', 0):
        assert gui.scale_intent_banner(junk) == cal, junk


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
