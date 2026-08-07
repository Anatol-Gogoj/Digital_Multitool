#!/usr/bin/env python3
"""The SCALE-ONLY RE-ANCHOR (`#215`, 2026-08-06) — correcting a run's px→mm
factor and re-deriving every recorded area from the stored pixel
measurements, with NO detection and NO re-review.

Why it exists, from real data. The corpus-wide sweep
(`_analysis/auto_calibration_sweep_20260806.md`) closed the scale chain:
every one of the eleven recorded resting areas is explained to two decimal
places by its anchor's deviation from the automatic disc fit, and the eight
runs that never had a manual anchor are exactly the eight that land on
π·8² = 201.06 mm² perfectly. Three runs are therefore wrong in absolute mm²
for one reason only — a human mis-calibrated the scale — while their PIXEL
measurements are correct:

    run                     anchor      auto fit   resting     Δ area
    P3_2_2.5mL_20260728     590.26 px   577.08 px  192.181     −4.42 %
    SLDEA_20260723_152205   377.087 px  370.65 px  194.259     −3.38 %
    SLDEA_20260723_233451   357.832 px  362.18 px  205.977     +2.44 %

The numbers below are those runs' REAL recorded values (read out of their
data.csv on 2026-08-06 and pinned here — run data never enters the repo, so
the numbers travel and the files do not). Re-anchoring each to its own
automatic fit must land its resting area on π·8², because declaring the
fitted disc to be 16 mm forces it. That is the arithmetic identity the whole
action rests on, so it is asserted against all three.

The commit itself reuses `apply_results` with an EMPTY results dict, which
is what makes it scale-only: every row takes the unreviewed branch — keep
the px, re-derive mm²/diam at this scale, blank a bug-era mm² that has no px
— which is the rule the [critical] partial-re-save entry put in force
(SLDEA_HANDOFF 2026-08-05). These tests pin that the re-anchor obeys exactly
that rule and touches nothing else.

Run: .venv/Scripts/python.exe tests/test_sldea_reanchor.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import csv
import math
import os
import shutil
import tempfile

import sldea_edge as se
import sldea_diag as sd


MASK_MM = 16.0
NOMINAL_MM2 = math.pi * 8.0 ** 2                 # 201.0619…, SLDEA_MEAS 2.4

# The three runs' REAL recorded numbers: the resting row's px and mm², the
# manual anchor in setup.txt, and the automatic fit baseline_disc produces
# on the same frame (verified end-to-end against the real frames on
# 2026-08-06 — baseline_disc reproduced 577.08 / 370.65 / 362.18 exactly).
REAL = {
    'P3_2_2.5mL_20260728': dict(
        rest_px=261552.0, rest_mm2=192.181, rest_diam=15.643,
        anchor_px=590.26, auto_px=577.08, n_rows=81,
        # a few real activated rows, so the ratio test runs on real spread
        rows_px=[261552.0, 268134.0, 292716.0, 301480.0]),
    'SLDEA_20260723_152205': dict(
        rest_px=107901.0, rest_mm2=194.259, rest_diam=15.727,
        anchor_px=377.087, auto_px=370.65, n_rows=49,
        rows_px=[107901.0, 110430.0, 118773.0, 124005.0]),
    'SLDEA_20260723_233451': dict(
        rest_px=103024.0, rest_mm2=205.977, rest_diam=16.194,
        anchor_px=357.832, auto_px=362.18, n_rows=77,
        rows_px=[103024.0, 105881.0, 112604.0, 119337.0]),
}

COLS = ['snapshot', 'step', 'tag', 'nominal_kV', 'control_V', 'measured_kV',
        'measured_uA', 't_planned_s', 'timestamp', 'frame_file',
        'active_area_px', 'active_area_mm2', 'active_diam_mm', 'wrinkle_idx',
        'notes']


def _row(i, tag, px, scale, **over):
    """One data.csv row as the app writes it: px to 0 dp, mm² and diam to
    3 dp. The rounding matters — it is why A/A₀ recomputed from the STORED
    mm² is not bit-identical while A/A₀ from px is."""
    r = {'snapshot': f"s{i:02d}", 'step': str(i), 'tag': tag,
         'nominal_kV': f"{0.25 * i:.2f}", 'control_V': f"{i * 10}",
         'measured_kV': f"{0.25 * i:.3f}", 'measured_uA': f"{i * 0.7:.2f}",
         't_planned_s': '5', 'timestamp': f"2026-07-28T10:00:{i:02d}",
         'frame_file': f"SLDEA_s{i:02d}_{0.25 * i:05.2f}kV_{tag}.png",
         'active_area_px': '', 'active_area_mm2': '', 'active_diam_mm': '',
         'wrinkle_idx': '', 'notes': f"edge:disc-fit conf 0.9{i % 10}"}
    if px is not None:
        r['active_area_px'] = f"{px:.0f}"
        if scale:
            r['active_area_mm2'] = f"{px * scale * scale:.3f}"
            r['active_diam_mm'] = (
                f"{2.0 * math.sqrt(px / math.pi) * scale:.3f}")
    r.update(over)
    return r


def _rows_for(name):
    """A run shaped like the real one: the resting row carries the run's
    REAL px/mm²/diam triple, the rest are derived at that same scale."""
    d = REAL[name]
    scale = math.sqrt(d['rest_mm2'] / d['rest_px'])
    rows = [_row(0, 'baseline', d['rest_px'], None,
                 active_area_px=f"{d['rest_px']:.0f}",
                 active_area_mm2=f"{d['rest_mm2']:.3f}",
                 active_diam_mm=f"{d['rest_diam']:.3f}")]
    for k, px in enumerate(d['rows_px'][1:], start=1):
        rows.append(_row(k, 'post-ramp' if k % 2 else 'pre-ramp', px, scale))
    return rows, scale


def _settings(diam_mm=MASK_MM):
    s = dict(se.DEFAULT_SETTINGS)
    s['diam_mm'] = diam_mm
    return s


def _ratios(rows, col):
    """A/A₀ against the baseline row, parsed from the STORED strings."""
    base = None
    for r in rows:
        if r.get('tag') == 'baseline':
            base = se._num(r.get(col))
            break
    return [None if (se._num(r.get(col)) is None or not base)
            else se._num(r.get(col)) / base for r in rows]


# ---------------------------------------------------------------------------
# the acceptance table — real numbers, all three runs
# ---------------------------------------------------------------------------

def test_three_real_runs_land_on_pi_r_squared():
    """THE identity the action rests on. Re-anchoring a run to its own
    automatic disc fit declares that fitted disc to be diam_mm, which forces
    the resting area onto π·(diam_mm/2)². If a run does not land there, the
    re-derivation is wrong.

    Asserted to two decimals — the tolerance the sweep table is quoted at —
    because the stored mm² is rounded to 3 dp and the fit's px diameter to
    2 dp, so the identity holds to ~1e-5 relative and not to the bit.

    The multipliers below are what these fixtures' inputs produce, with the
    automatic fit quoted at the sweep table's 2 dp. Driven end to end on
    scratch COPIES of the real runs on 2026-08-06 — where `baseline_disc`
    supplies its full-precision diameter rather than 577.08 / 370.65 /
    362.18 — the same code produced x1.046211, x1.035021 and x0.976141, and
    all three written resting areas landed on 201.06 mm². The two sets agree
    to 2e-5, which is the fit diameter's own rounding."""
    expect_mult = {'P3_2_2.5mL_20260728': 1.046202,
                   'SLDEA_20260723_152205': 1.035038,
                   'SLDEA_20260723_233451': 0.976137}
    for name, d in REAL.items():
        rows, old_scale = _rows_for(name)
        # the anchor implied by the run's own numbers IS the recorded one
        assert abs(MASK_MM / old_scale - d['anchor_px']) < 0.01, name
        new_ref = {'method': se.ANCHOR_METHOD_VERIFIED,
                   'cal_mode': se.CAL_MODE_VERIFY, 'diam_px': d['auto_px']}
        scale = se.mm_per_px({}, rows, _settings(), baseline_ref=new_ref)
        assert abs(scale - MASK_MM / d['auto_px']) < 1e-12, name
        plan = se.reanchor_plan(rows, scale, MASK_MM)
        # the multiplier every area is about to be multiplied by
        assert abs(plan['mult'] - expect_mult[name]) < 5e-6, (
            name, plan['mult'])
        # before → after, both against the mask anchor.
        #
        # A TOLERANCE, not round(x, 2) == round(NOMINAL, 2): with the fit
        # quoted at 2 dp one run lands at 201.0654, which is 0.0017 % from
        # pi*8^2 and therefore correct, but rounds to 201.07 and would fail a
        # rounding-equality check on the boundary. 0.01 mm2 is 0.005 % — two
        # orders of magnitude inside the ~0.8 % area budget of
        # SLDEA_MEASUREMENT 2.1, and three below the errors being corrected.
        assert abs(plan['rest_before'] - d['rest_mm2']) < 5e-4, name
        assert abs(plan['rest_after'] - NOMINAL_MM2) < 0.01, (
            name, plan['rest_after'])
        assert abs(plan['rest_dev_after']) < 0.005, name
        # and the WRITTEN column agrees with what the confirmation promised
        se.apply_results(rows, {}, scale, {}, None)
        got = float(rows[0]['active_area_mm2'])
        assert abs(got - NOMINAL_MM2) < 0.01, (name, got)
        assert abs(got - plan['rest_after']) < 5e-4, name


def test_deviation_from_the_mask_is_reported_on_both_sides():
    """The confirmation must let an operator sanity-check the whole
    operation, which means the deviation from π·8² BEFORE as well as after —
    the 'before' is the evidence that there was something to correct."""
    expect_before = {'P3_2_2.5mL_20260728': -4.42,
                     'SLDEA_20260723_152205': -3.38,
                     'SLDEA_20260723_233451': +2.44}
    for name, d in REAL.items():
        rows, _ = _rows_for(name)
        plan = se.reanchor_plan(rows, MASK_MM / d['auto_px'], MASK_MM)
        assert abs(plan['rest_dev_before'] - expect_before[name]) < 0.01, (
            name, plan['rest_dev_before'])
        assert abs(plan['rest_dev_after']) < 0.01, (name,
                                                    plan['rest_dev_after'])
        assert abs(plan['nominal_mm2'] - NOMINAL_MM2) < 1e-9


# ---------------------------------------------------------------------------
# the strongest single check: a uniform scale cancels in a ratio
# ---------------------------------------------------------------------------

def test_expansion_ratios_survive_a_reanchor():
    """A/A₀ must not move: a uniform scale factor cancels exactly in a
    ratio, which is why the three affected runs' RATIO results stand
    unchanged and only their absolute mm² were ever in question.

    Two claims, and they are NOT the same claim:

    1. from `active_area_px` — **bit-identical**, and this is the one that
       matters downstream, because breakdown_flags and sldea_plot both read
       px (SLDEA_HANDOFF 2026-08-05: that is exactly why the mixed-scale bug
       was invisible to them). The re-anchor never writes the px column, so
       the ratios are identical objects, not merely close.
    2. from the stored `active_area_mm2` — equal only to within the 3-decimal
       storage rounding (~1e-5 relative), and NOT bit-identical. Asserting
       bit-identity there would be asserting that quantisation commutes with
       multiplication, which it does not: round(px·s₁²,3)/round(px₀·s₁²,3)
       is not round(px·s₂²,3)/round(px₀·s₂²,3). Measured worst drift on the
       three real runs is 1.2e-5. Pinned as a BOUND so a real error — which
       would be percent-scale — still fails this test."""
    for name, d in REAL.items():
        rows, _ = _rows_for(name)
        before = [dict(r) for r in rows]
        se.apply_results(rows, {}, MASK_MM / d['auto_px'], {}, None)
        # (1) px ratios: bit-identical
        rb, ra = _ratios(before, 'active_area_px'), _ratios(
            rows, 'active_area_px')
        assert rb == ra, name
        assert all(v is not None for v in ra), name
        # every px cell is byte-identical too, not just its ratio
        assert ([r['active_area_px'] for r in before]
                == [r['active_area_px'] for r in rows]), name
        # (2) mm² ratios: within quantisation, and NOT claimed as identical
        mb, ma = _ratios(before, 'active_area_mm2'), _ratios(
            rows, 'active_area_mm2')
        worst = max(abs(a - b) / abs(a) for a, b in zip(mb, ma) if a)
        assert worst < 1e-4, (name, worst)


# ---------------------------------------------------------------------------
# the [critical] rule: re-derive from px, blank an mm² that has none
# ---------------------------------------------------------------------------

def test_mixed_px_and_no_px_rows_are_counted_before_the_commit():
    """The adversarial case the confirmation exists for: a run where some
    rows carry px and others carry a bug-era mm² with none.

    The rule (SLDEA_HANDOFF 2026-08-05, [critical]): a row with px keeps it
    and has mm²/diam RE-DERIVED at this scale; an mm² with NO px is BLANKED,
    never kept on an unknowable anchor. A re-anchor is a deletion for those
    rows, so the count has to be on screen BEFORE the operator commits — and
    the count the plan reports must be the count the commit produces, or the
    confirmation is worse than none."""
    d = REAL['P3_2_2.5mL_20260728']
    old = math.sqrt(d['rest_mm2'] / d['rest_px'])
    rows, _ = _rows_for('P3_2_2.5mL_20260728')
    # two bug-era rows: an mm²/diam pair with no px at all
    rows.append(_row(90, 'post-ramp', None, None,
                     active_area_mm2='188.400', active_diam_mm='15.49'))
    rows.append(_row(91, 'pre-ramp', None, None, active_area_mm2='188.900'))
    # one row with px but NO previous mm² — it GAINS an absolute area
    rows.append(_row(92, 'post-ramp', None, None, active_area_px='270000'))
    # one row with neither: untouched
    rows.append(_row(93, 'pre-ramp', None, None))
    scale = MASK_MM / d['auto_px']
    plan = se.reanchor_plan(rows, scale, MASK_MM)
    assert plan['n_rows'] == len(rows)
    assert plan['n_derive'] == 5, plan['n_derive']      # 4 real + the fresh
    assert plan['n_blank'] == 2, plan['n_blank']
    assert plan['n_fresh'] == 1, plan['n_fresh']
    assert plan['n_untouched'] == 1, plan['n_untouched']
    # the old scale is the RESTING row's own, not a median polluted by the
    # rows that carry no usable pair
    assert abs(plan['old_scale'] - old) < 1e-12
    # ... and the commit does exactly what was counted
    se.apply_results(rows, {}, scale, {}, None)
    assert rows[-4]['active_area_mm2'] == ''
    assert rows[-4]['active_diam_mm'] == ''
    assert rows[-3]['active_area_mm2'] == ''
    assert rows[-2]['active_area_px'] == '270000'
    assert float(rows[-2]['active_area_mm2']) > 0
    # the equivalent diameter, for a row that had no diam definition to keep
    assert abs(float(rows[-2]['active_diam_mm'])
               - 2.0 * math.sqrt(270000 / math.pi) * scale) < 5e-4
    assert rows[-1]['active_area_mm2'] == ''
    assert rows[-1]['active_area_px'] == ''
    n_blank_after = sum(1 for r in rows if not (r['active_area_px'] or '')
                        and not (r['active_area_mm2'] or ''))
    assert n_blank_after == 3, n_blank_after            # 2 blanked + 1 empty


def test_refuses_when_no_row_carries_a_pixel_measurement():
    """Nothing to re-derive ⇒ refuse and say why. Counting is done BEFORE
    the calibration dialog opens (new_scale=None), so an operator is never
    made to measure a disc only to be told afterwards that the run has no
    pixel areas to convert."""
    rows = [_row(i, 'baseline' if i == 0 else 'post-ramp', None, None)
            for i in range(4)]
    plan = se.reanchor_plan(rows, None, MASK_MM)
    assert plan['n_derive'] == 0
    assert plan['n_rows'] == 4
    assert plan['mult'] is None and plan['rest_after'] is None
    assert plan['old_scale'] is None and plan['old_diam_px'] is None
    # a run holding ONLY unre-derivable mm² is still a refusal, but the
    # count of what would be destroyed is available for the message
    rows[1]['active_area_mm2'] = '190.0'
    plan = se.reanchor_plan(rows, None, MASK_MM)
    assert plan['n_derive'] == 0 and plan['n_blank'] == 1
    # nominal is available with no rows at all -- it depends on diam_mm only
    assert abs(plan['nominal_mm2'] - NOMINAL_MM2) < 1e-9


def test_scale_only_leaves_every_other_column_byte_identical():
    """It is a SCALE operation. `notes`, `tag`, `snapshot`, the current and
    voltage columns, `wrinkle_idx`, `frame_file` and `active_area_px` must
    come out of a re-anchor byte-identical — including the '_BREAKDOWN'
    frame names and the 'post-breakdown' notes of a branded run, which the
    re-anchor must neither re-apply nor revert."""
    d = REAL['P3_2_2.5mL_20260728']
    rows, old = _rows_for('P3_2_2.5mL_20260728')
    # a branded run: renamed frames and branded notes from a previous save
    rows[2]['frame_file'] = 'SLDEA_s02_00.50kV_post-ramp_BREAKDOWN.png'
    rows[2]['notes'] = 'edge:disc-fit conf 0.92; breakdown? current spike'
    rows[3]['frame_file'] = 'SLDEA_s03_00.75kV_pre-ramp_BREAKDOWN.png'
    rows[3]['notes'] = 'edge:disc-fit conf 0.93; post-breakdown'
    rows[1]['wrinkle_idx'] = '1.37'
    rows[1]['notes'] = 'edge:texture conf 0.71; wrinkle-dominated'
    # An OBLONG activated row, whose recorded diameter is deliberately NOT
    # the equivalent-circle diameter of its px area. Needed to test the
    # preservation at all: on the resting rows of these three runs the
    # accepted candidate IS the circle fit, so the two definitions coincide
    # to 7e-5 mm and a preserved diameter is indistinguishable from a
    # substituted one.
    rows.append(_row(94, 'post-ramp', None, None,
                     active_area_px='290000', active_area_mm2='212.926',
                     active_diam_mm='19.500'))
    before = [dict(r) for r in rows]
    se.apply_results(rows, {}, MASK_MM / d['auto_px'], {}, None)
    for i, (b, a) in enumerate(zip(before, rows)):
        for c in COLS:
            if c in ('active_area_mm2', 'active_diam_mm'):
                continue
            assert (b.get(c) or '') == (a.get(c) or ''), (i, c, b.get(c),
                                                          a.get(c))
    # the two derived columns DID move, or the test above proves nothing
    assert rows[0]['active_area_mm2'] != before[0]['active_area_mm2']
    assert rows[0]['active_diam_mm'] != before[0]['active_diam_mm']
    new_scale = MASK_MM / d['auto_px']
    # the resting row's diameter lands on the mask's 16.000 mm, which is the
    # same identity as its area landing on pi*8^2
    assert abs(float(rows[0]['active_diam_mm']) - MASK_MM) < 5e-4, (
        rows[0]['active_diam_mm'])
    # a row's own diam DEFINITION is preserved rather than replaced by the
    # equivalent-circle diameter: the oblong row re-scales by the ratio of
    # the two anchors and stays oblong
    # ... and it re-scales by the ratio of the ROW'S OWN implied scale to the
    # new one, not the run's, which is what "preserve the row's own diam
    # definition exactly" means in apply_results
    kept = float(rows[-1]['active_diam_mm'])
    row_old = se.implied_scale(before[-1])
    assert abs(kept - 19.500 * new_scale / row_old) < 5e-4, kept
    assert abs(row_old - old) > 1e-6                # genuinely its own
    equiv = 2.0 * math.sqrt(290000 / math.pi) * new_scale
    assert abs(kept - equiv) > 0.5, (kept, equiv)


def test_a_reanchor_is_idempotent():
    """Re-anchoring twice to the same scale must be a no-op the second time.
    It is not free: the second pass recovers the old scale from the ROUNDED
    mm², so the multiplier it reports is 1.0 only to ~1e-6 — but the column
    it writes must be identical, because both derive from the untouched px."""
    d = REAL['SLDEA_20260723_233451']
    rows, _ = _rows_for('SLDEA_20260723_233451')
    scale = MASK_MM / d['auto_px']
    se.apply_results(rows, {}, scale, {}, None)
    once = [dict(r) for r in rows]
    plan2 = se.reanchor_plan(rows, scale, MASK_MM)
    assert abs(plan2['mult'] - 1.0) < 1e-4, plan2['mult']
    se.apply_results(rows, {}, scale, {}, None)
    for i, (a, b) in enumerate(zip(once, rows)):
        for c in COLS:
            assert (a.get(c) or '') == (b.get(c) or ''), (i, c)


# ---------------------------------------------------------------------------
# the old scale, recovered from the data rather than trusted from setup.txt
# ---------------------------------------------------------------------------

def test_old_scale_is_recovered_from_the_data_not_the_anchor_block():
    """`implied_scale` inverts area = px·scale². That is what lets a run with
    NO anchor block be re-anchored at all — the eight pre-gate runs, which
    are the ones 'one re-save away from acquiring a fresh error' — and it is
    also what makes the multiplier honest when setup.txt and the column
    disagree."""
    for name, d in REAL.items():
        rows, _ = _rows_for(name)
        sc = se.implied_scale(rows[0])
        assert abs(MASK_MM / sc - d['anchor_px']) < 0.01, name
    # no usable pair -> None, never a guess
    assert se.implied_scale({}) is None
    assert se.implied_scale({'active_area_px': '1000'}) is None
    assert se.implied_scale({'active_area_mm2': '5'}) is None
    assert se.implied_scale({'active_area_px': '0',
                             'active_area_mm2': '5'}) is None
    # and a hand-damaged cell cannot abort the plan (the '1e999' -> inf
    # class of failure _num was hardened against, review 2026-08-05)
    assert se.implied_scale({'active_area_px': '1e999',
                             'active_area_mm2': '5'}) is None
    rows, _ = _rows_for('P3_2_2.5mL_20260728')
    rows[1]['active_area_px'] = 'not a number'
    plan = se.reanchor_plan(rows, 0.0277, MASK_MM)
    assert plan['n_derive'] == 3 and plan['n_blank'] == 1


def test_pre_gate_run_with_no_anchor_block_can_still_be_reanchored():
    """The eight runs that carry no anchor block: `recorded` is None, so
    there is no recorded diameter to quote against — but the column itself
    still says what scale it was derived at, and that is what the operator
    is shown."""
    d = REAL['P3_2_2.5mL_20260728']
    rows, old = _rows_for('P3_2_2.5mL_20260728')
    plan = se.reanchor_plan(rows, MASK_MM / d['auto_px'], MASK_MM,
                            recorded=None)
    assert plan['recorded_diam_px'] is None
    assert plan['anchor_matches_data'] is None
    assert abs(plan['old_diam_px'] - d['anchor_px']) < 0.01
    assert plan['mult'] is not None
    # the provenance still records what the scale WAS, via the implied value
    f = se.reanchor_anchor_fields(None, plan)
    assert 'prev_diam_px' not in f          # nothing was on record
    assert abs(f['prev_implied_px'] - d['anchor_px']) < 0.01
    assert f['reanchor'] == se.REANCHOR_SCALE_ONLY
    assert 'prev_method' not in f


def test_anchor_block_that_disagrees_with_the_column_is_reported():
    """A setup.txt whose anchor is not the scale the column was derived at —
    a hand-edited block, or a save that never completed. The DATA wins,
    because the data is what gets re-derived; the disagreement is surfaced
    rather than silently resolved."""
    d = REAL['P3_2_2.5mL_20260728']
    rows, _ = _rows_for('P3_2_2.5mL_20260728')
    agree = se.reanchor_plan(rows, MASK_MM / d['auto_px'], MASK_MM,
                             recorded={'diam_px': d['anchor_px']})
    assert agree['anchor_matches_data'] is True
    bad = se.reanchor_plan(rows, MASK_MM / d['auto_px'], MASK_MM,
                           recorded={'diam_px': 601.0})
    assert bad['anchor_matches_data'] is False
    assert bad['recorded_diam_px'] == 601.0
    # the multiplier follows the DATA, not the block
    assert abs(bad['mult'] - agree['mult']) < 1e-12


def test_a_column_holding_two_scales_is_detected():
    """The [critical] mixed-scale state itself (a 56.1 % artificial step on
    the real-data repro). A re-anchor FIXES it — every row is re-derived
    from px at one scale — but the operator has to be told the multiplier
    quoted describes the resting row only."""
    rows, old = _rows_for('P3_2_2.5mL_20260728')
    clean = se.reanchor_plan(rows, 0.0277, MASK_MM)
    assert clean['mixed'] is False, clean['scale_span_pct']
    assert clean['n_scales'] == 4
    # rounding alone must NOT trip it: 3-dp mm² over 0-dp px is ~1e-3 %
    assert clean['scale_span_pct'] < se.REANCHOR_MIXED_TOL_PCT
    # one row written at a foreign anchor, as a partial re-save produced
    px = se._num(rows[2]['active_area_px'])
    rows[2]['active_area_mm2'] = f"{px * (old * 1.2) ** 2:.3f}"
    mixed = se.reanchor_plan(rows, 0.0277, MASK_MM)
    assert mixed['mixed'] is True
    assert mixed['scale_span_pct'] > 40.0, mixed['scale_span_pct']
    # and the resting row still sets the quoted factor
    assert abs(mixed['old_scale'] - old) < 1e-12


def test_resting_row_falls_back_and_says_so():
    """With no baseline-tagged row carrying px, the one check that can catch
    a wrong anchor is unavailable — so the plan falls back to the first
    measured row and FLAGS that it is not the baseline, rather than quietly
    presenting an activated frame's area as the resting area."""
    rows, _ = _rows_for('P3_2_2.5mL_20260728')
    for c in ('active_area_px', 'active_area_mm2', 'active_diam_mm'):
        rows[0][c] = ''
    plan = se.reanchor_plan(rows, 0.0277, MASK_MM)
    assert plan['rest_is_baseline'] is False
    assert plan['rest_row'] == 1
    assert plan['n_derive'] == 3
    # no measured row at all -> no before/after pair, and no invented one
    for r in rows:
        for c in ('active_area_px', 'active_area_mm2', 'active_diam_mm'):
            r[c] = ''
    empty = se.reanchor_plan(rows, 0.0277, MASK_MM)
    assert empty['rest_is_baseline'] is None
    assert empty['rest_before'] is None and empty['rest_after'] is None
    assert empty['rest_dev_after'] is None


# ---------------------------------------------------------------------------
# provenance — the run must not end up looking re-reviewed
# ---------------------------------------------------------------------------

def test_provenance_round_trips_through_setup_txt():
    """A later reader must be able to tell 'the scale was corrected' from
    'the run was reviewed again'. Round-tripped through the real block
    writer/reader, alongside a mode-C anchor's own provenance, because a
    re-anchor must not cost the record of where its new scale came from."""
    d = REAL['P3_2_2.5mL_20260728']
    rows, _ = _rows_for('P3_2_2.5mL_20260728')
    rows.append(_row(90, 'post-ramp', None, None, active_area_mm2='188.4'))
    plan = se.reanchor_plan(rows, MASK_MM / d['auto_px'], MASK_MM)
    prev = {'method': se.ANCHOR_METHOD_MANUAL, 'cal_mode': se.CAL_MODE_CIRCLE,
            'diam_px': d['anchor_px'], 'diam_mm': MASK_MM}
    anchor = {'method': se.ANCHOR_METHOD_VERIFIED,
              'cal_mode': se.CAL_MODE_VERIFY, 'diam_px': d['auto_px'],
              'diam_mm': MASK_MM, 'mm_per_px': MASK_MM / d['auto_px'],
              'fit_circ': 0.999, 'fit_conf': 0.871, 'fit_resid_px': 2.3,
              'fit_arc_cov': 0.75, 'fit_n_edge': 204,
              'verified_by': 'anatol', 'verified_at': '2026-08-06T18:40:00'}
    anchor.update(se.reanchor_anchor_fields(prev, plan))
    tmp = tempfile.mkdtemp(prefix='sldea_reanchor_')
    try:
        se.save_scale_anchor(tmp, anchor)
        back = se.load_scale_anchor(tmp)
        assert back['reanchor'] == se.REANCHOR_SCALE_ONLY
        assert abs(back['prev_diam_px'] - d['anchor_px']) < 1e-9
        assert back['prev_method'] == se.ANCHOR_METHOD_MANUAL
        assert back['prev_cal_mode'] == se.CAL_MODE_CIRCLE
        assert abs(back['prev_implied_px'] - d['anchor_px']) < 0.01
        assert back['reanchor_rows'] == 4
        assert back['reanchor_blanked'] == 1
        # the NEW anchor's own provenance survives intact
        assert back['method'] == se.ANCHOR_METHOD_VERIFIED
        assert back['verified_by'] == 'anatol'
        assert back['fit_n_edge'] == 204
        assert se.guard_is_vacuous(back)
        # a normal Save writes NO marker: that is how the two are told apart
        plain = dict(anchor)
        for k in ('reanchor', 'prev_diam_px', 'prev_implied_px',
                  'prev_method', 'prev_cal_mode', 'reanchor_rows',
                  'reanchor_blanked'):
            plain.pop(k, None)
        se.save_scale_anchor(tmp, plain)
        assert se.load_scale_anchor(tmp).get('reanchor') is None
        assert 'reanchor' not in open(os.path.join(tmp, 'setup.txt'),
                                      encoding='utf-8').read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_zero_blanked_rows_omit_the_key_rather_than_recording_a_zero():
    """`reanchor_blanked` absent means 'none', which is the block's existing
    convention for every optional field — a recorded 0 would be a claim in a
    format where absence is how nothing is said."""
    d = REAL['P3_2_2.5mL_20260728']
    rows, _ = _rows_for('P3_2_2.5mL_20260728')
    plan = se.reanchor_plan(rows, MASK_MM / d['auto_px'], MASK_MM)
    f = se.reanchor_anchor_fields({'diam_px': d['anchor_px']}, plan)
    assert 'reanchor_blanked' not in f
    assert f['reanchor_rows'] == 4


def test_diag_surfaces_the_reanchor_at_every_provenance():
    """`sldea_diag` must say it, and must not depend on baseline_disc to say
    it — a re-anchor is a fact about the run's own record. Nested under the
    automatic-fit branches it would go unreported on exactly the runs where
    the fit refuses (the shape of review 2026-08-06's major 4)."""
    d = REAL['P3_2_2.5mL_20260728']
    base = {'method': se.ANCHOR_METHOD_VERIFIED,
            'cal_mode': se.CAL_MODE_VERIFY, 'diam_px': d['auto_px'],
            'diam_mm': MASK_MM, 'mm_per_px': MASK_MM / d['auto_px'],
            'fit_circ': 0.999, 'fit_conf': 0.871, 'fit_resid_px': 2.3,
            'fit_n_edge': 204, 'verified_by': 'anatol',
            'saved': '2026-08-06T18:40:00', 'user': 'anatol',
            'reanchor': se.REANCHOR_SCALE_ONLY,
            'prev_diam_px': d['anchor_px'],
            'prev_implied_px': d['anchor_px'],
            'prev_method': se.ANCHOR_METHOD_MANUAL,
            'prev_cal_mode': se.CAL_MODE_CIRCLE,
            'reanchor_rows': 81, 'reanchor_blanked': 0}
    frame = {'idx': 1, 'kv': 5.0, 'file': 'f.png', 'shift_px': 0.1,
             'dx': 0.1, 'dy': 0.0, 'pc_response': 0.5, 'diff_mean': 4.0,
             'diff_mean_registered': 4.0, 'diff_mean_normbg': 4.0,
             'diff_mean_photofit': 4.0, 'gain': 1.0, 'offset': 0.0,
             'diff_p99': 8.0, 'diff_p99_sigma': 4.0, 'gated': False,
             'otsu': 20.0, 'texture_ratio': 1.0, 'sep_intensity': 0.4,
             'sep_registered': 0.4, 'sep_photofit': 0.4, 'sep_texture': 0.4,
             'area_px': 1000.0, 'solidity': 0.7, 'conf': 0.8,
             'needs_review': False}

    def diag(anchor, **over):
        dd = {'rundir': '/x/SLDEA_run', 'frames_analyzed': 1,
              'baseline_row': 0, 'frame_shape': [1080, 1920], 'sigma': 2.0,
              'sigma_source': 'test', 'settings': _settings(),
              'sweep_thresholds': [3, 5], 'sweeps': [], 'repeats': {},
              'frames': [dict(frame)], 'scale_anchor': anchor,
              'baseline_disc': {'method': 'baseline-disc',
                                'diam_px': d['auto_px'],
                                'area_px': math.pi * (d['auto_px'] / 2) ** 2,
                                'circ': 0.999, 'conf': 0.871,
                                'solidity': 0.98, 'arc_cov': 0.75,
                                'cx': 960.0, 'cy': 540.0,
                                'mm_per_px': MASK_MM / d['auto_px']}}
        dd.update(over)
        return dd

    # (a) with an automatic fit available
    got = [(s, h, t) for s, h, t in sd.verdicts(diag(base))
           if 'RE-ANCHORED' in h]
    assert len(got) == 1, [h for _s, h, _t in sd.verdicts(diag(base))]
    sev, head, detail = got[0]
    assert sev == 'OK' and 'NOT re-reviewed' in head
    assert 'scale-only' in detail
    assert '590.26 px recorded' in detail, detail
    assert se.ANCHOR_METHOD_MANUAL in detail
    assert '81 row(s) re-derived' in detail
    assert 'A/A0' in detail and 'cancels exactly' in detail
    assert 'x1.0462' in detail, detail
    # (b) baseline_disc REFUSED -- the verdict must still be emitted
    ref_gone = diag(base)
    ref_gone['baseline_disc'] = None
    got2 = [h for _s, h, _t in sd.verdicts(ref_gone) if 'RE-ANCHORED' in h]
    assert len(got2) == 1, got2
    # (c) a hand-calibrated re-anchor, and a pre-gate one with no prev block
    hand = dict(base)
    hand.update({'method': se.ANCHOR_METHOD_MANUAL,
                 'cal_mode': se.CAL_MODE_CIRCLE, 'n_rounds': 3,
                 'rounds_px': [576.8, 577.4, 577.1], 'spread_px': 0.6,
                 'spread_pct': 0.104, 'sigma_pct': 0.35, 'se_pct': 0.2})
    assert any('RE-ANCHORED' in h for _s, h, _t in sd.verdicts(diag(hand)))
    pre = dict(base)
    for k in ('prev_diam_px', 'prev_method', 'prev_cal_mode'):
        pre.pop(k)
    dt = [t for _s, h, t in sd.verdicts(diag(pre)) if 'RE-ANCHORED' in h][0]
    assert 'no anchor was on record' in dt, dt
    # (d) an anchor with NO marker must not produce the verdict
    plain = dict(base)
    for k in ('reanchor', 'reanchor_rows', 'reanchor_blanked'):
        plain.pop(k)
    assert not any('RE-ANCHORED' in h for _s, h, _t in sd.verdicts(
        diag(plain)))
    # ... and the TEXT report prints it
    txt = sd.report(diag(base))
    assert 're-anchored' in txt and 'NO detection, NO re-review' in txt
    assert 'previous scale' in txt and '590.26 px' in txt
    assert '81 re-derived' in txt


# ---------------------------------------------------------------------------
# the calibration log
# ---------------------------------------------------------------------------

def test_reanchor_log_line_records_the_correction():
    """One greppable line in the run's scale_calibration_log.txt, through the
    SAME formatter the three calibration modes use, so a run's whole scale
    history is one file."""
    d = REAL['SLDEA_20260723_152205']
    rows, _ = _rows_for('SLDEA_20260723_152205')
    plan = se.reanchor_plan(rows, MASK_MM / d['auto_px'], MASK_MM)
    anchor = {'method': se.ANCHOR_METHOD_VERIFIED,
              'cal_mode': se.CAL_MODE_VERIFY, 'diam_px': d['auto_px'],
              'diam_mm': MASK_MM, 'mm_per_px': MASK_MM / d['auto_px'],
              'auto_diam_px': d['auto_px'], 'fit_circ': 0.980,
              'fit_conf': 0.886, 'fit_resid_px': 2.0, 'fit_n_edge': 241,
              'reanchor': se.REANCHOR_SCALE_ONLY,
              'prev_method': se.ANCHOR_METHOD_MANUAL,
              'anchor_frame': 'SLDEA_s00_00.00kV_baseline.png'}
    rec = se.reanchor_log_record(anchor, plan, when='2026-08-06T18:41:00')
    line = se.calibration_log_line(rec)
    assert line.startswith('SLDEA-CAL 2026-08-06T18:41:00 mode=C n=1 ')
    assert 'outcome=reanchor-committed' in line
    assert 'reanchor=scale-only' in line
    assert 'rows=4' in line and 'blanked=0' in line
    assert f"prev={d['anchor_px']:.2f}px" in line
    assert f"prev_method={se.ANCHOR_METHOD_MANUAL}" in line
    assert 'area_mult=x1.035038' in line
    assert 'resting=194.259->201.06' in line
    assert 'resting_dev=+0.00%' in line
    # mode C's vocabulary is kept: no sigma/SE/range for a single fit
    assert 'sigma=undefined se=undefined' in line
    assert 'verdict=NOT-GATED' in line
    # mode C's honest 'auto=' column: the anchor IS the fit, so a deviation
    # percentage would be an identity dressed as agreement
    assert '(IS-the-anchor)' in line and 'auto=370.6' in line
    assert f"diams={d['auto_px']:.2f}px" in line
    # ... and it lands in the run's own log
    tmp = tempfile.mkdtemp(prefix='sldea_reanchor_log_')
    try:
        path, written = se.append_calibration_log(tmp, rec)
        assert path and os.path.exists(path)
        assert written == line
        body = open(path, encoding='utf-8').read()
        assert line in body and body.startswith('# SLDEA Edge Review')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_hand_measured_reanchor_keeps_its_own_statistics():
    """A re-anchor can be committed from any mode, so a mode A/B anchor's
    rounds, sigma and SE have to survive into the line — otherwise the only
    per-run operator-repeatability measurement this project has would be
    dropped on exactly the runs being corrected."""
    d = REAL['P3_2_2.5mL_20260728']
    rows, _ = _rows_for('P3_2_2.5mL_20260728')
    plan = se.reanchor_plan(rows, MASK_MM / d['auto_px'], MASK_MM)
    anchor = {'method': se.ANCHOR_METHOD_MANUAL,
              'cal_mode': se.CAL_MODE_CIRCLE, 'diam_px': 577.1,
              'diam_mm': MASK_MM, 'auto_diam_px': d['auto_px'],
              'n_rounds': 3, 'rounds_px': [576.8, 577.4, 577.1],
              'spread_px': 0.6, 'spread_pct': 0.104, 'sigma_pct': 0.061,
              'se_pct': 0.035, 'reanchor': se.REANCHOR_SCALE_ONLY,
              'prev_method': se.ANCHOR_METHOD_MANUAL}
    line = se.calibration_log_line(
        se.reanchor_log_record(anchor, plan, when='2026-08-06T18:42:00'))
    assert 'mode=A n=3' in line
    assert 'sigma=0.06% se=0.04% area_se=0.07%' in line
    assert 'range=0.10%' in line
    assert 'diams=576.80,577.40,577.10px' in line
    assert 'verdict=PASS' in line          # SE 0.035% is inside the 0.4% gate
    assert 'reanchor=scale-only' in line
    assert 'circ=' not in line             # mode C's fit fields stay absent
    # a pre-#215 two-click anchor has no rounds: its own diameter is the one
    # value there is, and the precision fields are 'unconvertible', not 0
    two = {'method': se.ANCHOR_METHOD_MANUAL, 'diam_px': 590.26,
           'diam_mm': MASK_MM, 'reanchor': se.REANCHOR_SCALE_ONLY}
    l2 = se.calibration_log_line(se.reanchor_log_record(two, plan))
    assert ' n=1 ' in l2 and 'diams=590.26px' in l2
    assert 'sigma=unconvertible' in l2 and 'verdict=UNJUDGEABLE' in l2


def test_mode_a_b_c_round_set_lines_are_byte_identical_to_before():
    """The three modes' log-line formats are pinned by exact-string tests in
    tests/test_sldea_calibration.py. The re-anchor group is rendered ONLY
    when `reanchor` is present, so a round-set line cannot have changed —
    asserted here as well, against the same record with and without it."""
    stats = se.calibration_stats([576.8, 577.4, 577.1])
    rec = {'when': '2026-08-06T18:00:00', 'mode': se.CAL_MODE_CIRCLE,
           'stats': stats, 'gate': se.CAL_SE_PCT, 'verdict': 'PASS',
           'rot_deg': None, 'stroke': '3 px', 'auto_diam_px': 577.08,
           'auto_pct': 0.0, 'outcome': 'accepted', 'frame': 'b.png'}
    plain = se.calibration_log_line(rec)
    assert 'reanchor' not in plain and 'blanked' not in plain
    assert plain.endswith('outcome=accepted frame=b.png')
    with_rn = se.calibration_log_line(
        dict(rec, reanchor={'scope': se.REANCHOR_SCALE_ONLY, 'n_derive': 3,
                            'n_blank': 0}))
    # the group is inserted BEFORE outcome/frame, so those stay last
    assert with_rn.endswith('outcome=accepted frame=b.png')
    assert with_rn.startswith(plain.split(' outcome=')[0] + ' reanchor=')
    # unknowns are said, not defaulted to a number nobody measured
    assert 'prev=unknown' in with_rn and 'area_mult=unknown' in with_rn


# ---------------------------------------------------------------------------
# the full commit, on a real CSV, including the backup and a locked file
# ---------------------------------------------------------------------------

def _write_run(tmp, rows):
    path = os.path.join(tmp, 'data.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return {'rundir': tmp, 'csv_path': path, 'columns': list(COLS),
            'rows': rows}


def test_commit_writes_the_backup_and_survives_a_locked_csv():
    """The Save path's `data.csv.bak` is kept, and the everyday failure —
    data.csv open in Excel — must leave the run untouched on BOTH sides.
    `apply_results` mutates in place and `write_back` can fail after it, so
    the GUI snapshots the rows and restores them; without that a failed
    re-anchor would leave memory at the new scale and disk at the old, and
    the next attempt would report a x1.000 multiplier against numbers the
    operator never agreed to."""
    d = REAL['P3_2_2.5mL_20260728']
    rows, _ = _rows_for('P3_2_2.5mL_20260728')
    tmp = tempfile.mkdtemp(prefix='sldea_reanchor_csv_')
    try:
        run = _write_run(tmp, rows)
        original = open(run['csv_path'], encoding='utf-8-sig').read()
        scale = MASK_MM / d['auto_px']
        se.apply_results(run['rows'], {}, scale, {}, None)
        se.write_back(tmp, run)
        assert os.path.exists(run['csv_path'] + '.bak')
        assert open(run['csv_path'] + '.bak',
                    encoding='utf-8-sig').read() == original
        with open(run['csv_path'], encoding='utf-8-sig', newline='') as f:
            back = list(csv.DictReader(f))
        assert round(float(back[0]['active_area_mm2']), 2) == round(
            NOMINAL_MM2, 2)
        # --- the locked-file path: snapshot + restore leaves NOTHING moved
        saved = open(run['csv_path'], encoding='utf-8-sig').read()
        snap = [dict(r) for r in run['rows']]
        cols = list(run['columns'])

        def boom(*_a, **_k):
            raise PermissionError(
                "[WinError 32] The process cannot access the file because "
                "it is being used by another process")

        real, se.write_back = se.write_back, boom
        try:
            try:
                se.apply_results(run['rows'], {}, scale * 1.5, {}, None)
                se.write_back(tmp, run)
                raise AssertionError('the locked write should have raised')
            except PermissionError:
                for row, old in zip(run['rows'], snap):
                    row.clear()
                    row.update(old)
                run['columns'] = cols
        finally:
            se.write_back = real
        assert [dict(r) for r in run['rows']] == snap
        assert open(run['csv_path'], encoding='utf-8-sig').read() == saved
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# the confirmation dialog's TEXT — one button rewrites every area in the run
# ---------------------------------------------------------------------------

class _Stub:
    """Enough of EdgeReviewApp for `_reanchor_msg`, which reads only
    `self.settings`. Bound rather than instantiated because the message
    builder is pure text and must be testable without a Tk display (the
    widget layer skips headlessly — see tests/test_sldea_edge_gui.py)."""

    def __init__(self, settings, rundir=None):
        self.settings = settings
        self.rundir = rundir

    def msg(self, plan, prev, new_ref):
        import sldea_edge_gui as gui
        return gui.EdgeReviewApp._reanchor_msg(self, plan, prev, new_ref)


def test_confirmation_carries_every_number_an_operator_needs():
    """An operator must be able to sanity-check the WHOLE operation from
    this dialog, because accepting it rewrites every absolute area in the
    run. Required contents: rows to re-derive, rows that would blank, both
    anchor diameters, the multiplier, and the before → after resting area
    with its deviation from pi*8^2 on BOTH sides."""
    d = REAL['P3_2_2.5mL_20260728']
    rows, _ = _rows_for('P3_2_2.5mL_20260728')
    rows.append(_row(90, 'post-ramp', None, None, active_area_mm2='188.4'))
    scale = MASK_MM / d['auto_px']
    plan = se.reanchor_plan(rows, scale, MASK_MM,
                            recorded={'diam_px': d['anchor_px']})
    prev = {'method': se.ANCHOR_METHOD_MANUAL, 'diam_px': d['anchor_px']}
    new_ref = {'method': se.ANCHOR_METHOD_VERIFIED, 'diam_px': d['auto_px']}
    m = _Stub(_settings()).msg(plan, prev, new_ref)
    assert 'SCALE ONLY' in m
    # it says what it does NOT do -- the whole premise of the action
    assert 'Detection does NOT re-run' in m and 'nothing is re-reviewed' in m
    assert 'frame names are not touched' in m
    # both anchors and the multiplier
    assert '590.26 px' in m and '577.08 px' in m
    assert '× 1.046202' in m and '+4.62%' in m
    # counts on both sides of the [critical] rule
    assert 'rows re-derived from px   4 of 5' in m
    assert 'rows BLANKED              1' in m
    assert 'cannot be re-derived' in m
    # resting area, before and after, deviation on both sides
    assert '201.06 mm²' in m                      # the mask anchor itself
    assert '192.181 mm²   (-4.42%)' in m
    assert '(+0.00%)' in m or '(-0.00%)' in m
    assert 'baseline row' in m
    assert 'data.csv.bak' in m and 'A/A₀' in m


def test_confirmation_warns_when_the_corrected_area_misses_the_mask():
    """The one check that can catch a wrong anchor: re-anchoring to a run's
    own automatic fit forces its resting area onto pi*(d/2)^2, so an 'after'
    that does not land there means the anchor is not that fit. Silence there
    would make the dialog's strongest number decorative."""
    d = REAL['P3_2_2.5mL_20260728']
    rows, _ = _rows_for('P3_2_2.5mL_20260728')
    stub = _Stub(_settings())
    # the correct fit: no warning
    ok = se.reanchor_plan(rows, MASK_MM / d['auto_px'], MASK_MM)
    assert 'still more than 1%' not in stub.msg(
        ok, None, {'diam_px': d['auto_px']})
    # an anchor 3 % off in diameter: ~6 % off in area, and it must say so
    bad_px = d['auto_px'] * 1.03
    bad = se.reanchor_plan(rows, MASK_MM / bad_px, MASK_MM)
    m = stub.msg(bad, None, {'diam_px': bad_px})
    assert 'still more than 1% from the mask anchor' in m
    assert 'this anchor is NOT that fit' in m


def test_confirmation_states_the_awkward_cases_rather_than_omitting_them():
    """Every shape the plan can take has to render, and the cases where a
    number does NOT exist have to be stated rather than left blank."""
    d = REAL['P3_2_2.5mL_20260728']
    stub = _Stub(_settings())
    new_ref = {'diam_px': d['auto_px']}
    # (a) a pre-gate run with no anchor block
    rows, _ = _rows_for('P3_2_2.5mL_20260728')
    m = stub.msg(se.reanchor_plan(rows, MASK_MM / d['auto_px'], MASK_MM,
                                  recorded=None), None, new_ref)
    assert 'NO anchor was on record' in m and 'pre-gate save' in m
    # (b) setup.txt disagreeing with the column
    m = stub.msg(se.reanchor_plan(rows, MASK_MM / d['auto_px'], MASK_MM,
                                  recorded={'diam_px': 601.0}),
                 {'diam_px': 601.0}, new_ref)
    assert 'is NOT the scale this column was actually derived at' in m
    assert 'the multiplier follows the' in m
    # (c) a column already holding two scales
    mixed_rows = [dict(r) for r in rows]
    px = se._num(mixed_rows[2]['active_area_px'])
    old = se.implied_scale(mixed_rows[0])
    mixed_rows[2]['active_area_mm2'] = f"{px * (old * 1.2) ** 2:.3f}"
    m = stub.msg(se.reanchor_plan(mixed_rows, MASK_MM / d['auto_px'],
                                  MASK_MM), None, new_ref)
    assert 'MORE THAN ONE SCALE' in m and 'Re-anchoring FIXES it' in m
    # (d) no recoverable old scale -> no invented multiplier
    fresh = [_row(0, 'baseline', None, None, active_area_px='261552'),
             _row(1, 'post-ramp', None, None, active_area_px='268134')]
    m = stub.msg(se.reanchor_plan(fresh, MASK_MM / d['auto_px'], MASK_MM),
                 None, new_ref)
    assert 'MULTIPLIER   UNKNOWN' in m
    assert 'rows gaining an mm² now   2' in m
    # (e) re-anchoring to the anchor already in force
    same = se.reanchor_plan(rows, se.implied_scale(rows[0]), MASK_MM)
    m = stub.msg(same, None, {'diam_px': d['anchor_px']})
    assert 'no area changes measurably' in m
    # (f) no resting area at all -> the check is declared UNAVAILABLE
    hollow = [_row(0, 'baseline', None, None),
              _row(1, 'post-ramp', None, None, active_area_mm2='5.0')]
    m = stub.msg(se.reanchor_plan(hollow, MASK_MM / d['auto_px'], MASK_MM),
                 None, new_ref)
    assert 'UNAVAILABLE' in m
    # (g) a nonsensical diam_mm must not formatter-crash the dialog
    m = _Stub(_settings(diam_mm=0.0)).msg(
        se.reanchor_plan(rows, 0.0277, 0.0), None, new_ref)
    assert 'SCALE ONLY' in m
    # (h) the one stale artifact is named when it exists, and not when it
    # does not. Save draws area_vs_voltage.png from the session's accepted
    # results and a re-anchor has none, so it cannot be regenerated.
    plan = se.reanchor_plan(rows, MASK_MM / d['auto_px'], MASK_MM)
    tmp = tempfile.mkdtemp(prefix='sldea_reanchor_plot_')
    try:
        assert 'area_vs_voltage.png' not in _Stub(_settings(), tmp).msg(
            plan, None, new_ref)
        open(os.path.join(tmp, 'area_vs_voltage.png'), 'wb').close()
        m = _Stub(_settings(), tmp).msg(plan, None, new_ref)
        assert 'area_vs_voltage.png is NOT regenerated' in m
        assert 'only its mm² axis is stale' in m
        # a missing rundir must not raise out of a confirmation dialog
        assert 'SCALE ONLY' in _Stub(_settings(), None).msg(plan, None,
                                                           new_ref)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
