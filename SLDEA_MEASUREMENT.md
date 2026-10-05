# SLDEA active-area measurement — error budget and how the algorithm works

Status: 2026-08-07 (§2.1a; the rest 2026-08-01); the `disc-fit` area
estimator rows, the spread term and the Level 2–4 descriptions were
corrected 2026-10-02, when the area became a common-ray ratio (dated
entry in `SLDEA_DECISIONS.md`; the measurements behind it are §2.1b and
the note under table 1.1). The other terms were NOT re-measured then.
The 47 operator labels score the drawn ellipse outline, which did not
change; they say nothing about the new area. Every number in this
document is **measured**, not estimated — sources are the four
calibration rounds (47 operator labels across both campaigns), the
per-run scale calibration (two hand methods A/B compared against the
automatic fit the operator now verifies instead — §2.1a), the
operator repeatability round, the per-frame boundary self-audit, and the
baseline-scale overlays. The
provenance table at the end maps each number to its origin. When
calibration numbers move (new labels, new campaigns), update this file
in the same PR.

---

## 1. Quick reference — glance here first

### 1.1 What uncertainty do I quote?

| You are reporting | Quote | Dominated by | Conditions |
|---|---|---|---|
| **Expansion ratio A/A₀** (area-vs-kV curves) | **±1–2%** | the **measured** terms of §2.1: frame repeatability, the spread, the trim, the second-order residual of the edge-definition offset. **The hidden-perimeter term is not in this figure**: nothing bounds it independently (the series it is checked against shares the hidden sectors), and its likely size, an over-read of order 1 point at the peak, is quoted separately under this table | auto-accepted `disc-fit` / `resting` / refit frames **saved with area estimator 2** (2026-10-02 on; `area_estimator: 2` in the run's `setup.txt`). Checked up to 4 kV against an independent sector measurement that shares the hidden sectors: per-run mean difference −1.0 to +0.5 points of A/A₀, SD 0.2–0.7. Above 4 kV the figure is not checked; the measured facts there are under this table. Rows saved earlier carry a run-specific offset of −0.4 to +7.4% and do **not** meet this figure: reprocess them |
| **Absolute area (mm²), edge convention stated** | **±1–2%** | scale anchor + the measured tracker terms of §2.1 (the hidden-perimeter term is not in it either) | methods section states the half-height convention; area estimator 2 rows only, as above |
| **Absolute area (mm²), convention not stated** | **±3%** (or a one-sided +5.5% band) | the edge-definition offset | avoid this — state the convention instead |
| **Hand-traced areas** (wash-out frames ≥5.5 kV) | **±1%** precision, outer-toe convention | operator repeatability | machine has no boundary there; traces are the measurement |

**Above 4 kV** (measured 2026-10-02 on the auto-accepted tracker rows,
OpenCV 4.13; evidence for the sign and size of the hidden-perimeter
term of §2.1, **not a correction**, nothing below is applied to any
number):

- *The edge definition is still in the number.* The tracker takes the
  strongest sustained ink step on each ray; the independent series
  takes the half-height point. On `DOT_P3_1` at 4.25–6 kV the ratio
  over the top and bottom sectors alone (the independent series' own
  sectors) reads **+2.2 points** above that series, and over all rays
  +1.7, so the gap there is an edge-definition term the old estimator
  shared, not a sector effect. Up to 4 kV the same split reads
  −0.1/−0.2 points.
- *The rays nearest the leads strain less than the top and bottom
  rays.* At 2.25–6 kV, lead-adjacent minus top/bottom strain, per-run
  mean (median): `DOT_P3_1` −1.4 (−0.8), `P3_2` −1.5 (−1.4), `P3_3`
  −0.4 (−0.4), `P3_5` −2.6 (−2.0), `P3_6` −4.2 (−3.0), `104531` −0.6
  (−0.7) points. The hidden perimeter sits between those lead-adjacent
  rays. If it follows them rather than the average of every visible
  ray (what the estimator assumes), the estimator over-reads by about
  the hidden share times that gap: per-run mean **+0.2 to +1.8 points
  at 4.25–6 kV** (`DOT_P3_1` +0.8, `P3_5` +1.8; `P3_6` +3.7 on its one
  auto row there), +0.1 to +1.3 at 2.25–4 kV. Which sectors the hidden
  perimeter follows is a statement about the device, not the code, and
  is an open owner decision (`SLDEA_DECISIONS.md`, 2026-10-02).

### 1.2 How much do I trust each method?

| Winning method | What it actually measures | Validated accuracy | Auto-accepts? |
|---|---|---|---|
| `disc-fit` | ink-edge boundary. **Area** = the baseline circle × the common-ray ratio (the same rays measured on the baseline frame and on this one; 2026-10-02). The robust ellipse is the drawn outline and the audit carrier, not the area | outline IoU vs operator: median 0.89, min 0.82 (n=26, scored before 2026-10-02); area vs an independent sector measurement, auto-accepted rows up to 4 kV: per-run mean −1.0 to +0.5 points, SD 0.2–0.7. Its spread (median 0.6%) is a block-bootstrap figure, **not** a confidence interval | yes, at conf ≥ 0.75 with a clean audit |
| `resting` | asserts the baseline area: the baseline row itself (A₀ by definition), and a no-change frame the tracker could not measure | audit-bounded to ≤ ~2%; clean controls score IoU 0.94–0.95 | yes |
| `disc-fit` + `resting_refit` | measured boundary on a "no-change" (gated) frame: **every** such frame since 2026-10-02, not only a bias-tripped one | frames at 0.25–0.5 kV read 0.9996–1.0036 × A₀ per run, SD 0.08–0.26% (six campaign runs). The earlier line here ("+4.1/+4.6% at P3_1 2.0 kV, matching the audit-predicted creep") was a statement about the ellipse area and is not carried over: on `DOT_P3_1_20260729` the ellipse already read +7.4% on the 0 kV frame, and that run's 2.0 kV frames now read +0.5/+1.1% | yes, only if its own audit is clean |
| `manual-trace` (candidate D) | the operator's polygon | ground truth by definition; ±1% area precision, self-agreement IoU ceiling 0.973 | committed by the user |
| `diff-*` / `tex-ratio` (patch tiers) | the changed/wrinkled *region*, not the boundary | IoU ~0.43; area −40..−69% vs the true boundary | in practice held in review by the spread/pair rules — if one ever auto-accepts, treat it as suspect and trace the frame |

### 1.3 Do / Don't

- **DO** state the edge convention when quoting mm². The machine
  measures the **half-height point of the ink step** (the standard
  optical-metrology choice, audited to sub-pixel); a human tracing by
  eye lands on the **outer toe** of the soft edge, +5.2–5.7% area
  above it.
- **DO** prefer expansion ratios A/A₀ — the scale cancels exactly and
  the definitional offset cancels to second order (~1% at 1.44×).
- **DON'T** use any `active_area_mm2` written before 2026-07-28: the
  old blob detector's scale bug understated areas 2.3–2.7×. Reprocess
  through Edge Review instead.
- **DON'T** mix `disc-fit` areas saved before 2026-10-02 with later
  ones. Until then the area was the fitted ellipse, which read −0.4 to
  +7.4% against the same run's own A₀ (a different offset per run).
  `setup.txt` says which a run holds: `area_estimator: 2` in its Edge
  Detection settings block is the common-ray ratio, no such line is the
  ellipse. Reprocess old runs through Edge Review (Detect, review,
  Save). A Save never keeps a `disc-fit` row from the old estimator
  beside new rows: an unreviewed one is emptied and its notes say
  `not kept: measured with the old area method (ellipse, before
  2026-10-02) - re-review this frame` (the old value stays in
  `data.csv.bak` until the next Save). The Save dialog counts such rows
  before anything is written. Across runs, `sldea_plot` and the plot
  window refuse a run holding unstamped (or older-stamped) `disc-fit`
  areas from area axes, the way the 2026-07-28 scale era is refused;
  the CLI's `--allow-old-estimator` draws it anyway, named in the
  caption, and the tidy CSV's `area_estimator` column says which
  estimator wrote each `disc-fit` row. Since 2026-10-03 the same Save
  also stamps `opencv_version` and `numpy_version` (the process that
  wrote the areas; every number here is OpenCV 4.13), the tidy CSV
  carries them beside `area_estimator` on every machine row, and Edge
  Review shows one warning line when it runs off the pinned OpenCV.
  The Save also stamps the tracker's window limits, `ray_win_hi` and
  `disc_fit_r_max` (§3 level 4, item 3; owner decision 6, 2026-10-03):
  they are constants that moved once under the same `area_estimator`
  (1.38 -> 1.70 and 1.3 -> 1.75 r₀), and on the wrinkled review-queue
  frames the two windows read +8 to +16% apart, so a row accepted from
  the queue is only comparable with another once both say which window
  measured them. The stamp is per run (the window of the last Save that
  ran Detect), not per row: a queue row kept from an earlier pass keeps
  that pass's px under the later stamp, so after any further move of
  the window re-review a re-saved run's kept rows. The tidy CSV carries
  the two beside the versions on every `disc-fit` row; a run saved
  before they were recorded has them blank (with `area_estimator` 2
  that means the 1.38 / 1.3 window).
- **DON'T** mix machine areas and hand-traced areas in one absolute
  comparison without the +5.5% definitional correction.
- **DON'T** judge any machine boundary against a bar above IoU ~0.97 —
  that is the measured limit of human self-agreement.
- The resting diameter is **anchored at 16 mm by the laser-cut CNT
  application mask** (lab confirmation, 2026-08-01) — no per-device
  verification needed for this series; see §2.4.

---

## 2. The error budget in full

### 2.1 The terms

| Error term | Type | Measured size | Source |
|---|---|---|---|
| Edge definition (visual outer toe vs half-height ink step) | systematic | **+5.2–5.7% area** between conventions; spread across controls only 0.5% | round 4, four audit-clean controls |
| Scale anchor (baseline disc trace vs by-eye) | systematic, per run | ~0.4% diameter → **~0.8% area**; 0.3% repeat on one device 32 min apart. From 2026-08-06 **measured per run** — see §2.1a: measured human per-fit **σ ≈ 1.0–1.1% whatever the method**, so a *hand* anchor MISSES this budget below ~7 rounds, while an **auto-verified** anchor carries the fit's own residual (0.40% of diameter here) and no operator term at all | baseline overlays, both campaigns; per-run scatter from the calibration's n rounds (hand modes only) |
| Nominal diameter (the value the mm scale hangs on) | systematic | **closed** — anchored by the laser-cut application mask | lab confirmation 2026-08-01 (see §2.4) |
| `disc-fit` spread (block bootstrap of the common-ray ratio) | random + uneven strain, per frame | median **0.6%**, 0.2–1.9% (5th–95th percentile), growing with voltage. **Not a calibrated confidence interval**: it holds 66% of the quiet-frame deviations from A₀ (0.25–0.5 kV, n=32) and about 90% of the detrended same-landing pre/post differences up to 4 kV, but only 50–60% above 4 kV | corpus replay 2026-10-02 (450 auto-accepted tracker rows, 8 runs, OpenCV 4.13) |
| `disc-fit` repeatability on an unchanged disc | random, per frame | **0.08–0.26%** SD per run at 0.25–0.5 kV (rms 0.22% about A₀ over 32 frames); same-landing pre/post robust SD 0.3–0.4% up to 4 kV, 1.2% above | same replay |
| The trim (a ray whose own ratio r_k/r_k(0) sits more than 2.5 robust sigmas from the median is dropped before the sum; `n_trimmed` and the trim share on the card; a share above 0.2 makes the candidate review only, never auto-accepted, since 2026-10-03) | **systematic, chosen by the rule**, per frame | trimmed minus untrimmed ratio on the 450 auto-accepted rows, in points of A/A₀: median abs 0.27 / 0.33 / 0.47 / 0.85 / 0.69 by band (0–0.5 / 0.75–2 / 2.25–4 / 4.25–6 / 6.25+ kV), 90th percentile 0.7 / 0.8 / 1.9 / 2.6 / 1.8, maximum **11.8**. On the frames it moves most (`P3_5` rows 31–34 at 4.0–4.25 kV, +10.6 to +11.6; `DOT_P3_1` rows 63–75 at 8–9.5 kV, +8.5 to +11.8; 22–31% of the rays dropped) it is a modelling choice with a first-order effect, not an outlier rule: `P3_5`'s peak is 1.579 trimmed, 1.463 untrimmed, 1.595 by the independent series. Details in §2.1b | same replay, trimmed against untrimmed on the same rays |
| Hidden perimeter (the edge the rays cannot use is **assumed** to strain like the edge they can. On the campaign runs 32–55% of the perimeter has no measurable edge even at rest (foil, leads, faint ink), and a typical accepted frame's ratio uses about half of the perimeter) | systematic, cannot be checked from the image | not measured. Evidence of its size: agreement with an independent sector measurement within 1 point of A/A₀ per run up to 4 kV; over the whole ramp +0.4 to +1.4 points on four runs, −1.2 on P3_5, 0.0 on 104531; different shape models spread about ±2.5% at the peak. Its likely SIGN: the rays nearest the hidden sectors strain 1–4 points less than the top/bottom rays at 2.25–6 kV on four runs, so the term is probably an over-read of order 1 point at the peak (the note under table 1.1) | corpus replay + science review, 2026-10-02; sector split of the same replay |
| Fixed ray centre (rays are cast from the BASELINE centre; a shifted disc biases the ratio when the visible rays are one-sided) | systematic, per frame | 0.22% of area per px of shift (median; 0.39% 90th percentile, 0.70% worst) → 0.04% at the ~0.2 px median rig drift. P3_5 is the exposed run (one-sidedness 0.53, 0.32%/px). Frames with one-sidedness > 0.6 are review only, never auto-accepted (refused outright through 2026-10-02): there the ratio read +6.0% (median) over the independent measurement | re-cast from a moved centre, corpus replay 2026-10-02 |
| Operator trace precision (the validation floor) | random | **~1%** area (0.2–2.5%); IoU ceiling 0.973 | repeatability round, 9 repeat pairs |
| Clean `resting` claims | bounded | ≤ ~2% (the 3 px audit-bias gate; the refit measures anything past it). Since 2026-10-02 only the baseline row and gated frames the tracker cannot measure are `resting`; of the 112 frames that used to auto-accept as exactly A₀, 111 are now measured (median +0.30%, 90th percentile +1.4%, max +2.6%) | audit + resting-refit; corpus replay 2026-10-02 |
| Onset frames (audit-capped fits, interpolated arc) | systematic, local | ~1–2% excess understatement after decomposition | round 3, corrected by round 4 |
| Wrong-feature tracking (halo, smoothing shift) | systematic | bounded **< ~0.3%** area (per-run median audit bias −0.4..+0.4 px) | boundary self-audit, all six runs |

### 2.1a The scale anchor became a per-run measurement (2026-08-06)

Since the fit-a-circle calibration (`#215`), Edge Review takes **several
independent fits** of the resting disc per run and anchors on their
**mean**. Two hand methods exist, chosen per calibration so they can be
compared on the same disc — plus the `verify` method, which is not a hand
measurement at all (see below):

| | `circle` (label **B**) | `twopoint` (label **C**) |
|---|---|---|
| gesture | drag/resize a circle onto the boundary | click two roughly-opposite edge points; **the second click banks the round and advances** |
| decorrelation | each round respawns at a random position and size | the **display is rotated by a random angle** each round |
| default rounds | 3 | 5 |
| shipped | 2026-08-06 | 2026-08-06 (evening) |

**Methods are recorded by NAME, not by their dialog letter.** The letters
were renumbered on 2026-08-06 (late) at the operator's request so that
**A = `verify`**, the method the gate opens in, with B = `circle` and
C = `twopoint`. Before that swap A was the circle, B the two-point and C
the verify — and those letters are on disk, in `setup.txt`'s `cal_mode:`
and in `scale_calibration_log.txt`'s `mode=` field, on live campaign runs
(`P3_2_2.5mL_20260728` records `cal_mode: C`, meaning *verify*). So:

- nothing writes a letter any more. `cal_mode:` and `mode=` hold
  `verify` / `circle` / `twopoint`, which no future relabelling can
  reinterpret. The field ORDER of the log line is unchanged; only that one
  field's value space moved.
- **the read rule for a legacy letter is its PRE-SWAP meaning** —
  A = circle, B = twopoint, C = verify — applied in one place
  (`se.cal_mode_read`) and used by every reader, including `sldea_diag`,
  the anchor loader and the reuse path. A log file that predates the
  change gets one note marking where its own vocabulary changes.
- the letters remain only as UI labels (`se.CAL_MODE_LABELS`).

The **range** of the rounds is recorded in `setup.txt`
(`rounds_px` / `spread_px` / `spread_pct`), together with which method
produced it and the conversion below (`cal_mode` / `sigma_pct` / `se_pct`),
and `sldea_diag` reports all of it. Every completed round-set — **accepted
or declined** — is also appended to `scale_calibration_log.txt` in the run
folder and printed to stdout.

What changes is the term's **character, not its size**. Before, ~0.4%
diameter was an estimate borrowed from baseline overlays across
campaigns; now every run carries its own number.

#### The conversion is n-aware

For a recorded range *R* over *n* fits, using the control-chart **d₂(n)**
factors (ASTM E2587 / Duncan, *Quality Control and Industrial
Statistics*; `se.D2_RANGE_FACTORS`):

| n | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|
| d₂ | 1.128 | 1.693 | 2.059 | 2.326 | 2.534 | 2.704 | 2.847 |

- per-fit precision **σ ≈ R / d₂(n)** — the *method's* own property, and
  the only figure comparable between two modes run at different *n*;
- the mean of *n* has standard error **SE = σ/√n**;
- diameter → area doubles it: **area SE = 2 · SE**.

At *n* = 3 those are the R/1.693, R/2.93 and R/1.47 this section used to
hard-wire. **They hold at n = 3 only.** With the round count configurable
the code refuses to convert an *n* the table has no factor for, rather
than reusing 1.693 — `se.d2()` returns None, `calibration_stats` leaves
σ/SE None *together*, `se.se_ok()` returns None (not True), and the dialog
and `sldea_diag` both report the gap instead of a number. A raw range on
its own is **not comparable across n**: the range of 5 fits is 1.37× the
range of 3 at identical precision.

#### The acceptance gate is the mean SE, not the range

`se.se_ok` against **`CAL_SE_PCT` = SE ≤ 0.4% of diameter** (≡ 0.8% area).
That threshold is **derived from §2.1's standing budget above, not
measured** — the budget already existed, and SE is the quantity it is
expressed in, so this is not a second invented number.

The range gate it replaces (`CAL_SPREAD_PCT` = 1%, still recorded and
still reported) had two defects. A range is not comparable across *n*, so
it could not survive a configurable round count. And **a range cannot
shrink when a round is added**, so the remedy a range gate offers could
never clear it (`SLDEA_HANDOFF.md` 2026-08-06 review sub-entry) — the flow
always landed on "accept anyway". SE falls as 1/√n, so the gate now names
the round count that *would* clear it, computed from the σ just measured
(`se.rounds_for_se`).

**What the operator sees when it trips (2026-08-07).** The prompt quotes
three things and nothing else: the round **σ as a % of diameter**, what that
implies as **area error** (2·σ/√n) against the **±0.8 % area budget**, and the
round count that would clear the gate — then the three-way choice (refit /
accept as measured / cancel). **This section is where the derivation lives**;
the prompt does not repeat it, because it is read in the middle of a
measurement. The mean's SE in diameter and the raw range are not on that
prompt either and do not need to be: they are `se=` and `range=` in
`scale_calibration_log.txt` and `se_pct` / `spread_pct` in `setup.txt`, and d₂
is fixed by the `n=` both of them carry. The prompt quotes **percentages only,
never a diameter** — a refit is one of its answers, and a printed diameter
would make that refit a fitted-to-target one rather than an independent
round — and its default is **Cancel**, the answer that changes nothing.

**The range cap is not a gate (2026-10-03, owner decision 19).** Before the
SE gate runs, a round-set whose range is **more than `CAL_RANGE_CAP_PCT` =
5 % of its mean** is refused outright: no accept-as-measured, no override,
only "measure again" or cancel (`se.over_range_cap`, logged as
`verdict=OVER-CAP`). A cap on the range does not reintroduce the two
defects above, because it is not asking the gate's question. It asks
whether the rounds were measurements of one thing at all, and for that a
range needs no d2 factor and no remedy other than starting over. Every set
over the cap is already over the SE gate (the largest range the gate passes
is 0.4 x d2(n) x sqrt(n): 1.17 % at n = 3, 3.22 % at n = 8), so the cap
removes an override, not a pass. Its cost is in the two-point mode: at
that mode's one measured sigma of 2.09 % the expected 5-round range is
4.86 %, and about 44 % of honest 5-round sets are refused (200,000
simulated sets); at the circle mode's 1.05 % the figure is under 2 % at
every n in the table. Details and the refusal wording: `SLDEA_DECISIONS.md`
2026-10-03 sub-entry.

#### First real data: the circle mode's per-fit σ ≈ 1.05% (2026-08-06)

Six circle-mode calibration attempts on a scratch copy of
`P3_2_2.5mL_20260728` (Anatol, 2026-08-06 — recorded in the
[`#215` comment](https://github.com/Anatol-Gogoj/Digital_Multitool/issues/215)).
Recorded 3-round ranges **1.94, 2.09, 1.62, 1.81, 1.44%** plus a sixth
that passed the 1% gate (exact value not captured):

| range R | 1.94 | 2.09 | 1.62 | 1.81 | 1.44 |
|---|---|---|---|---|---|
| σ = R/1.693 | 1.15% | 1.23% | 0.96% | 1.07% | 0.85% |

**Per-fit σ ≈ 1.05%** (mean; median 1.07%). Therefore the 3-round mean SE
is **0.61% diameter → 1.21% area**, against §2.1's ~0.4% / ~0.8% — the
mechanism intended to *tighten* this term currently sits ~1.5× outside it,
and the circle mode would need **~7 rounds** to reach budget at this precision. The
operator's diagnosis is that the bright green 3 px stroke **occludes the
edge it is being aligned to**; the two-point mode (non-occluding markers, rotated
display) targets **σ < 0.9%**, at which 5 rounds lands on budget. A mild
practice effect is visible across the six attempts (1.94 → 2.09 → 1.62 →
1.81 → 1.44 → <1.0), so the asymptote may be better than 1.05% — but not
by the ~2.6× needed.

> **NOT YET QUOTABLE — do not put a per-run spread in the budget.** One
> operator, one disc, one method: that is a first data point, not a
> distribution. σ ≈ 1.05% above is what the circle mode measured *on this disc, by
> this operator, on that afternoon* — it is quotable as **that**, and it is
> what justifies building the two-point mode, but the per-run figure the tool prints
> must **not** be fed into this budget (or into a methods section, or into
> `sldea_diag`'s numbers as if it were an established term) until several
> runs and both methods have been measured. Until then §2.1's ~0.4%
> diameter / ~0.8% area **remain the numbers to quote**, and the two-point mode's own σ
> is **entirely unmeasured**.

Worked at the new gate: a run accepted right at SE = 0.4% carries
**0.4% on the mean diameter** and **0.8% in area** by construction — the
gate *caps* the random part of this term at exactly §2.1's figure, which
is what makes it the right statistic to gate on. At *n* = 5 that
corresponds to σ ≈ 0.89% per fit; at *n* = 3, σ ≈ 0.69%.

Four caveats, all load-bearing:

- **This measures precision, not accuracy.** A consistently mis-placed
  mark (the outer toe instead of the half-height, say) produces a tight
  spread and a wrong mean. The **anchor guard** covers that axis by
  cross-checking the mean against the automatic disc fit and against the
  16 mm mask's π·8² resting area at ~1% (see §2.4 and the 2026-08-06
  `SLDEA_HANDOFF.md` entry). Run `P3_2_2.5mL_20260728` is the standing
  example: +2.28% diameter, −4.42% area, a *systematic* miss that no
  spread would have caught.
- **The remaining systematic part does not shrink with n.** Averaging
  divides the random scatter, not the edge-convention offset of §2.3. Mode
  B's rotation converts *one* systematic term — mis-judging "exactly
  opposite", and the human preference for horizontal/vertical chords over
  diagonal — into a random one that averaging does suppress. It does
  nothing for the edge convention.
- **The two-point mode's display rotation resamples the frame**, which softens the ink
  edge slightly. Every round is rotated, so the softening is identical in
  all *n* rounds: it can inflate σ, and it does not bias the mean.
- **Precision is only measurable if the rounds are blind.** The dialog
  hides every previously accepted diameter and the running average until
  the last fit is in, because a visible target makes the spread a number
  the operator can hit rather than a number they produce (review
  2026-08-06). The two-point mode additionally shows *no length at all* for the pair
  being placed, so it is measured under stricter blinding than the circle mode —
  which can only handicap B in the comparison. If any of that changes,
  this whole section stops meaning anything.
  **Neither 2026-08-07 on-screen pass changed it.** All three modes now hold
  one on-screen budget — `gui.CAL_SCREEN_MAX_LINES_ORDINARY` = 3 in every
  mode, with `CAL_SCREEN_MAX_LINES` = 4 as the ceiling the pathological cases
  may not pass — where the measuring modes had been showing nine lines. What
  came off was prose, and three of the removals *strengthen* the blinding
  rather than weakening it: the sentence that *explained* it, the prior
  anchor's recorded diameter (whose standing presence through a blind
  round-set was itself a printed target), and — in the second pass — the
  measuring modes' `⚠ N row(s) already carry px …` row, which stood above the
  picture for the whole set and has moved to the confirmation of the button
  that actually commits. Every number involved is still in `setup.txt` and
  `scale_calibration_log.txt`, verified by diffing a full accepted round-set's
  record in all three modes across each change: byte-identical, same SHA-256.

  **The aim instruction's wording is presentation; this document owns the
  convention.** The screen says *"straddle the edge: half the stroke on the
  disc, half on the paper"* (and *"half the ring …"* in the two-point mode,
  where the marker ring is centred on the click). That is an instruction about
  where to put the mark, which is what a hand can act on; what it *achieves*
  is §1.3's **half-height of the ink step**, and the +5.2–5.7 % area /
  +2.6 % diameter band against the visual outer toe is unchanged and stays
  there. The screen deliberately no longer names the convention — a definition
  is not an instruction — so **§1.3 is the only place it is written down**, and
  a reader quoting absolute mm² must go there for it.

#### The measured human per-fit σ is ~1.0–1.1 %, and it does not depend on the method (2026-08-06, evening)

This is the section's **first real data on human precision**, and it is the
same number three ways. Anatol's A/B/A′ session on a scratch copy of
`P3_2_2.5mL_20260728`, eleven calibrations interleaved to cancel the
practice effect, against an automatic fit of **577.08 px** (circ 0.999,
conf 0.871, residual 2.3 px, 204 edge points):

| arm | *n* | per-fit **σ** (median) | mean diameter vs the automatic fit |
|---|---|---|---|
| **A** — circle, 3 px solid + 5 px halo | 3 | **1.03 %** | **+2.07 %** |
| **A′** — circle, 1 px dashed | 3 | **1.11 %** | **+0.77 %** |
| **B** — two-point diameter, rotated | 5 | **2.09 %** | +0.95 % |

Three readings of that table, all load-bearing:

- **σ ≈ 1.0–1.1 % per fit, and the stroke does not move it.** A → A′ shifts
  σ by 0.08 points (inside the noise of four samples) while it shifts the
  **mean by 1.3 points**. The stroke's cost is **accuracy, not precision** —
  and averaging suppresses noise as √n while doing *nothing* to a bias, so
  no round count would ever have fixed the circle mode. Its +2.07…+2.59 % is the
  documented **outer-toe convention** of §2.3/§1.3 (+2.6 % in diameter),
  locked in by a stroke that hides the step.
- **At σ ≈ 1.05 % the 3-round mean SE is 0.61 % diameter / 1.21 % area**
  against this document's standing ~0.4 % / ~0.8 %, so a hand-measured
  anchor needs **~7 rounds** to reach budget. The two-point mode is *worse*, not better
  (a single chord uses far less of the boundary than a circle fit, and the
  stratified rotation did not compensate), so it is dominated by A′ on both
  axes.
- **The automatic fit beat all eleven attempts on accuracy and nine of
  eleven on precision.** That is why the scale gate now opens on
  `baseline_disc`'s measurement and asks the operator to *verify* it (the verify mode
  — see the 2026-08-06 evening `SLDEA_HANDOFF.md` entry).

**The mechanism, measured on the frame:** the disc reads **166 gray**, the
paper **186**, and that 20-level step is spread over **~60 px of radius**.
There is no line to click. Asking an operator to pick "the edge" is asking
them to pick a point inside a gradient *wider than the stroke they draw
with*, and the point they pick is the outer toe.

#### An auto-verified anchor's uncertainty is the FIT's, not an operator term

A verify-mode anchor (`method: auto-verified`) has **no rounds**, so σ, the mean
SE and the range are **undefined for it — not zero**. The code writes them
as undefined everywhere (`se.verify_stats`, the calibration log's
`sigma=undefined`, `sldea_diag`), because `0.00 %` in those columns would
read as perfect precision.

What quantifies it is the fit's own **median edge-point residual as a
fraction of diameter** (`se.fit_resid_pct`): on this baseline
**2.3 px / 577.08 px = 0.40 % of diameter**, i.e. it lands on §2.1's
standing budget. Two honest qualifications:

- it is **conservative** — the per-point scatter, not the standard error of
  the *fitted radius*, which with n_edge = 204 points is roughly √n ≈ 14×
  smaller (~0.03 %). The per-point figure is quoted because it is what the
  fitter measured, and because over-stating this term is the safe direction;
- it is a **precision** figure, and the fit's **systematic** term — which
  feature the step-finder locks onto versus the true mechanical boundary —
  **is not measured by anything in this project.** The evidence for the fit's
  accuracy is `baseline_disc` agreeing with the by-eye measurement to ~1 % on
  the three P3 baselines (579/578/586 px) plus the eleven-attempt comparison
  above. And unlike a hand-measured anchor, **there is no cross-check that
  can test it**: declaring the fitted disc to be `diam_mm` makes the resting
  area π·(diam_mm/2)² by construction, so §2.4's mask anchor reads +0.00 % on
  a verify-mode anchor at any diameter. That check is not run on one and not
  claimed.

An auto-verified anchor therefore contributes **nothing** to §2.5's
operator-repeat leg. That number still comes only from runs calibrated by
hand in the circle or two-point mode.

> **STILL NOT QUOTABLE — one operator, one disc, one session.** σ ≈ 1.0–1.1 %
> above is a first data point, not a distribution: it is quotable as *what
> this operator measured on that disc on that afternoon*, and it is what
> justifies the verify mode, and that is all. **§2.1's ~0.4 % diameter / ~0.8 % area
> remain the numbers to quote.** The blockquote above this sub-section
> applies unchanged.

### 2.1b The common-ray ratio, measured (2026-10-02)

The tables behind the `disc-fit` rows of tables 1.1, 1.2 and 2.1. They
were measured on the 16 run folders of the review copy (899 frames)
with the pinned OpenCV 4.13, by replaying detection exactly as Edge
Review runs it (`baseline_disc`, `candidates` per frame with
`prev_method` chained, `reconcile_pairs`, `needs_review`); "old" is
`main` at `1eb85b2`, the ellipse estimator. The decision they settled
is the `SLDEA_DECISIONS.md` entry of that date.

**The defect.** A0 (the baseline row and every `resting` row) was the
`baseline_disc` circle; every `disc-fit` row was π·a·b of a robust
ellipse fitted only to rays in foil-free sectors and extrapolated
across the blocked ones. The ellipse fitted to the baseline frame
itself, over the circle of that same frame:

| Run | ellipse / circle at 0 kV | old step at the hand-over (points of A/A₀) |
|---|---|---|
| DOT_P3_1_20260729 | 1.074 | +8.8 (1.75 → 2.0 kV) |
| P3_2_2.5mL_20260728 | 1.030 | +5.1 (1.0 → 1.25 kV) |
| P3_3_2.5mL_20260728 | 1.031 | +5.3 (1.0 → 1.25 kV) |
| P3_5_2.5mL_0729 | 1.006 | +4.3 (1.0 → 1.25 kV) |
| P3_6_2.5mL_20260729 | 1.022 | +3.8 (0.75 → 1.0 kV) |
| SLDEA_20260729_104531 | 0.9965 | −0.5 (2.5 → 2.75 kV) |
| SLDEA_20260723_152205 (retired) | 1.147 | |
| SLDEA_20260723_233451 (retired) | 0.996 | |

The edge points were never the problem (the tracker's kept points sit
at 0.998–1.008 r₀ on quiet frames); the shape model was. The ratio
uses the same rays on both frames and no shape model. Each Save
stamps the run's own ellipse/circle offset into `setup.txt`
(`base_ellipse_over_circle`), so the size of the correction is on
record per run.

**Repeatability on an unchanged disc** (the 0.25–0.5 kV frames,
which every run holds four of; all measured, none asserted):

| Run | A/A₀, mean of 4 frames | SD | range |
|---|---|---|---|
| DOT_P3_1 | 1.0003 | 0.08% | 0.9997 to 1.0013 |
| P3_2 | 1.0021 | 0.26% | 0.9985 to 1.0043 |
| P3_3 | 1.0013 | 0.14% | 0.9993 to 1.0024 |
| P3_5 | 0.9996 | 0.17% | 0.9980 to 1.0018 |
| P3_6 | 1.0036 | 0.09% | 1.0026 to 1.0045 |
| 104531 | 0.9999 | 0.13% | 0.9984 to 1.0010 |

P3_6's +0.36% may be real: the independent series reads 0.0 to +0.7%
over its own baseline on those four frames.

**The one-sidedness limit** (0.6; length of the mean unit vector of
the ray directions, 0 = balanced, 1 = all one way). Ratio minus the
independent sector measurement, with the limit lifted:

| one-sidedness | frames with an independent value | median difference |
|---|---|---|
| 0 to 0.30 | 434 | +0.24% |
| 0.30 to 0.45 | 37 | −0.11% |
| 0.45 to 0.60 | 75 (64 of them P3_5) | −0.97% |
| 0.60 to 0.70 | 6 | +6.5% |
| above 0.70 | 18 | +5.9% |

In the offline ray statistics (every gate lifted) 31 corpus frames sit
above the limit, 26 of them in review on every version and 5 (rows
29–33 of retired `SLDEA_20260723_233451`, 3.0–3.4 kV, wrinkle onset)
auto-accepted on `main` +2.0 to +2.7% over the independent value. In
`candidates()` itself only 14 of the 31 ever reach the limit with a
tracker candidate (the ellipse gates refuse the other 17 first): P3_2
row 40, P3_3 rows 41–44, 233451 rows 29–33 and 47–50. **Since
2026-10-03 (owner decision 2) the limit does not refuse**: the
candidate keeps its number and its outline, is tagged
`ray_one_sided`, is capped just below `accept_conf`, and the frame goes
to a human whatever else is on it (all 14 are tagged; the gate reads
the one-sidedness as measured, not rounded, so row 47 of 233451 at
0.6001 is over the limit). All 31 are in review, none auto, none
rejected. Through
2026-10-02 the same 14 frames had no tracker outline at all. The
60-ray and 120° limits never fired (accepted frames have at least 92
rays and 8 blocks) and still refuse. The limit's value was tuned on
this corpus.

**Result on the six campaign runs** (old → new; A/A₀ against the
run's own baseline row; the hand-over step is the landing-mean
difference at the two landings the old code handed over at):

| Run | step across the old hand-over | auto / review | median abs(pre − post) per landing ≤ 4 kV | peak A/A₀, auto-accepted |
|---|---|---|---|---|
| DOT_P3_1 | +8.8 → +0.3 points | 56/25 → 63/18 | 0.78 → 0.47% | 1.630 → 1.557 (6.0 kV) |
| P3_2 | +5.1 → +1.1 | 67/14 → 67/14 | 0.53 → 0.55% | 1.581 → 1.575 (4.25 kV) |
| P3_3 | +5.3 → +0.6 | 71/10 → 69/12 | 0.48 → 0.43% | 1.608 → 1.584 (4.5 kV) |
| P3_5 | +4.3 → +1.0 | 60/21 → 60/21 | 0.71 → 0.73% | 1.540 → 1.579 (4.25 kV) |
| P3_6 | +3.8 → +1.0 | 52/29 → 52/29 | 0.67 → 0.41% | 1.521 → 1.532 (4.0 kV) |
| 104531 | −0.5 → +0.2 | 81/0 → 81/0 | 0.00 → 0.10% | 1.048 (4.75 kV) → 1.034 (10 kV) |

Frame to frame (the last frame the old code accepted as `resting` to
the first it measured) the old step is +8.8, +4.9, +5.1, +3.8, +3.8,
−0.5 points and the new reading of the same two frames +0.6, +0.7,
+0.2, +0.4, −0.0, −0.1; from the baseline to the 0.25 kV landing the
new curve moves +0.05, +0.02, +0.03, −0.07, +0.34, −0.12. What is left
of each step is strain between those landings.

**Against the independent series** (the gate reviewer's half-height
radius on top and bottom sectors, `series_indep.csv`, no repo detector
code; auto-accepted tracker rows up to 4 kV; difference in points of
A/A₀, mean and SD):

| Run | old minus independent | new minus independent | new minus the tracker reviewer's prototype |
|---|---|---|---|
| DOT_P3_1 | +7.32 (0.34) | −0.02 (0.39) | −0.03 (0.23) |
| P3_2 | +3.03 (0.63) | +0.46 (0.44) | −0.10 (0.20) |
| P3_3 | +3.24 (0.79) | 0.00 (0.44) | −0.48 (0.55) |
| P3_5 | −0.13 (1.04) | −0.97 (0.68) | −0.01 (0.40) |
| P3_6 | +1.42 (0.96) | +0.33 (0.71) | +0.20 (0.43) |
| 104531 | −0.53 (0.62) | +0.04 (0.15) | +0.09 (0.13) |

Over the whole ramp the new minus independent means are +1.36, +0.48,
+0.43, −1.22, +0.61 and +0.03; pooled rms by band 0–0.5 / 0.75–2 /
2.25–4 / 4.25–6 / 6.25+ kV: 0.23 / 0.38 / 0.89 / 1.75 / 1.60 points
(old: – / 2.28 / 3.63 / 6.05 / 2.43). No auto row up to 2 kV sits more
than 1.5 points from the series (n = 96). P3_5 reads about 1 point
below it and nothing here says which is right.

**The trim** (2.5 robust sigmas, MAD, on the per-ray ratio) removes a
median of 21 rays per accepted frame (share of the common rays:
median 11%, 90th percentile 16%, maximum 31%); without it the
quiet-frame scatter doubles (rms 0.22% → 0.49%). That is its effect
on quiet frames only. Its **signed effect at strain** (trimmed minus
untrimmed ratio, same rays, the 450 auto-accepted rows; the
reproduction matches the harness ratios to 1e-5):

| kV band | rows | median abs | 90th pct abs | max abs | median signed |
|---|---|---|---|---|---|
| 0–0.5 | 32 | 0.27 | 0.68 | 1.56 | −0.15 |
| 0.75–2 | 98 | 0.33 | 0.77 | 1.30 | −0.24 |
| 2.25–4 | 116 | 0.47 | 1.90 | 10.58 | −0.15 |
| 4.25–6 | 51 | 0.85 | 2.63 | 11.59 | +0.16 |
| 6.25+ | 149 | 0.69 | 1.82 | 11.80 | −0.30 |

(points of A/A₀.) The frames it moves by more than 5 points are the
six auto rows of `P3_5` at 3.5–4.25 kV (rows 28–31, 33, 34: +5.7 to
+11.6, 20–31% of the rays dropped), the fourteen auto rows of
`DOT_P3_1` at 8–10 kV (rows 63–80, post-washout: +6.8 to +11.8,
16–30% dropped) and one row of retired 233451 (+5.7). On those
frames the rule is dropping a coherent minority of the edge, not
outliers, and the number rests on which rays it keeps: `P3_5`'s peak
(row 34) is **1.579 trimmed, 1.463 untrimmed**; the independent
series reads 1.595 there and 1.567 / 1.452 on rows 33 / 31 (trimmed
1.540 / 1.446, untrimmed 1.430 / 1.341), so the trimmed value is the
one that series supports. On `DOT_P3_1` 8.5–9.5 kV the trimmed value
sits +4.5 to +4.9 above the series and the untrimmed −6.3 to −7.3
below it; neither reproduces it. The trim is therefore a modelling
decision with a first-order effect at strain (the row in table 2.1),
and the card shows `n_trimmed` with the trim share beside it. **Since
2026-10-03 (owner decision 9) a trim share above 0.2 is a review-only
limit**: the share is `n_trimmed / (n_common + n_trimmed)`, the
fraction of the rays measured on both frames that the trim dropped;
above 0.2 the candidate is tagged `ray_trim_share`, capped just below
`accept_conf`, and the frame goes to a human (never a refusal). On the
corpus replay this routes 21 formerly auto rows to review (`DOT_P3_1`
rows 63–67 and 69–75 at 8–9.5 kV, `P3_5` rows 28–31, 33, 34 at
3.5–4.25 kV, retired `152205` rows 1, 4, 6 at 0.25–0.75 kV), 18 of
them among the 36 rows the trim moves by more than 2 points (the
other 18 such rows sit at or below 0.2, among 429), plus 10 rows
already in review. `P3_5`'s auto-accepted peak therefore drops from
1.579 (row 34) to 1.281 (row 27, 3.5 kV): its top of ramp is a human's
call. The share's median is 0.106, 90th percentile 0.164, maximum 0.31
on the 450 auto rows of 2026-10-02. **The fixed ray
centre:** re-casting every frame's rays from a centre moved one
detector px changes the ratio by 0.22% of area per full-resolution px
(median), 0.39% at the 90th percentile, 0.70% worst; P3_5 is the
exposed run (one-sidedness about 0.53, 0.32%/px). A
translation-corrected variant (first harmonic removed) was worse on
quiet frames (rms 0.26%; P3_5's quiet mean moved from 0.9996 to
1.0038) and unstable on one-sided arcs, and was not taken.

**The spread** (`ci85_pct`, shown as `spread_pct`): the half-width of
the central 85% of a 300-resample block bootstrap of the ratio over
whole 20° blocks (neighbouring rays correlate, lag-1 about 0.5), fixed
seed. Median 0.57%, 0.20–1.88% from the 5th to the 95th percentile,
maximum 4.3% on accepted frames. It holds 66% of the quiet-frame
deviations from A₀ (32 frames, rms 0.22%), 91% and 90% of the
detrended same-landing pre/post differences up to 2 kV and from 2 to
4 kV, 50% and 61% from 4 to 6 kV and above 6 kV. The old number was
the ellipse's edge-scatter formula, which assumed a known shape and
independent rays and held 21–49% where it claimed 85%.

### 2.2 Why ratios are tight: the annulus cancellation

The definitional offset behaves as a near-constant annulus of ~7 px
on a ~289 px resting radius. In a ratio, a fixed annulus cancels to
second order: at 1.2× radius (1.44× area) the residual between the
two conventions is ~0.8%. Combined with the tracker's repeatability
(0.1–0.3% on an unchanged disc, §2.1), the hidden-perimeter assumption
and pre/post pair scatter, **expansion curves carry ±1–2%** — the same
order as the human trace precision, i.e. as good as validation can
certify.

One honest caveat: the annulus was measured at rest and low kV. If
the edge blurs further under large strain, the annulus could grow
with expansion; the onset-frame excess (~1–2%) bounds how big that
effect can be over the measured range.

### 2.3 Why absolute areas are looser: the definition band

"Where does the electrode end" has two defensible answers on a soft
edge that spans ~8–15 px: the half-height of the intensity step
(machine) or the visually apparent outer toe (human). The +5.2–5.7%
between them is not noise — its spread across four independent
controls was 0.5%, and the operator's own repeatability is ~1% — it
is a **convention choice**. Pick one, state it, and absolute areas
inherit only the scale terms (~1%) and the per-frame spread. Fail to pick
one and you owe the reader the ±3% band.

### 2.4 The nominal-diameter anchor — CLOSED (2026-08-01)

The px→mm scale anchors to the device's nominal resting diameter of
16 mm. Originally flagged as the one unquantified term, this is now
**closed by fabrication**: the CNT electrodes are applied through a
laser-cut mask, so the discs sit at 16 mm by manufacture for this
entire series (lab confirmation, Anatol, 2026-08-01) — the anchor is
a machined constraint, not an assumption. Since 2026-08-06 the mask
anchor is also an **active check on the operator**: Edge Review's
calibration compares the accepted scale against π·(diam_mm/2)² —
201.06 mm² at 16 mm — via the automatic disc fit, and demands an explicit
override past ~1%. Run `P3_2_2.5mL_20260728` is why (see §2.1a).
Two consequences worth
stating in a methods section: (a) because every device in the series
is cut by the same mask, any residual mask-aperture tolerance is
common-mode — it cancels in cross-device comparisons as well as in
ratios, and only the absolute SI traceability rests on the laser-cut
spec; (b) absolute mm² therefore carries only the scale-trace term
(~0.8% area) and the per-frame tracker terms of §2.1 (repeatability,
the hidden-perimeter assumption), i.e. the ±1–2% of table 1.1.

### 2.5 Scope limits

- Frames at ≥5.5 kV (bright-wrinkle wash-out) have **no machine
  boundary**; the recorded number there is a manual trace (outer-toe
  convention, ±1%) or nothing. A "bright-wrinkle boundary mode" would
  be new capability, not a fix.
- Patch-tier winners are region measurements, not boundary
  measurements (see table 1.2); they exist to flag change where the
  boundary fitter cannot run.
- These budgets hold for the two campaigns measured (P3 2026-07-28,
  SLDEA 2026-07-23). A new optical geometry inherits the *methods*
  but should re-run a control round (~15 min of tracing) before the
  numbers are reused.
- The two **retired 2026-07-23 fixtures** are outside the ±1–2% figure
  of table 1.1 above 4 kV. `SLDEA_20260723_152205` (ellipse/circle
  1.147 at rest; the tape edge lies outside the foil mask, so rays
  reach a tape edge the mask does not block) reads within 1.5 points
  of the independent series up to 4 kV (SD 3.0) but **+8 points above
  it at 4.25–6 kV** (n = 3), growing with voltage from +2 at 3.5 kV.
  A trim-share refusal was measured and not adopted (the review-only
  tag of 2026-10-03 catches this fixture's quiet rows 1, 4 and 6, not
  its over-reading ones): the over-reading frames trim only 6–10% of their
  rays (16–27 of about 260) against a corpus median of 11% (90th
  percentile 16%, maximum 31%), and the 12 auto rows above 25% are
  `DOT_P3_1` at 8–9.5 kV (post-washout, +3 to +5 points over the
  series), `P3_5` at 4.25 kV (−1.6 and −2.7) and this fixture's own
  0.25 kV frame (−0.3): no common sign, so trim share does not
  separate the fixture from good frames. `SLDEA_20260723_233451` is
  within 1 point up to 4 kV (SD 0.9) and has one auto row above
  (+3.8).

---

## 3. How the algorithm works — five levels

### Level 1 — the elevator version

We photograph a dark circle (the device) on paper before any voltage
is applied, and again at every voltage step. The computer plays
spot-the-difference against the first photo, draws a line around the
circle's edge in each new photo, and measures the space inside the
line. When it is not sure the line is right, it raises its hand and a
person checks — or draws the line by hand.

### Level 2 — high school

Every image is a grid of brightness numbers, and the device is a disc
slightly darker than the paper behind it. The program first measures
the resting disc in the zero-volt photo, which also fixes how many
millimeters one pixel is. For each later photo it corrects for camera
brightness drift, then walks outward from the disc's center in
hundreds of directions, finding where dark turns to light — the ink
edge — along each one. It did the same walk on the zero-volt photo,
so for every direction it has two distances: before and now. The area
is the resting disc's area times how much those distances grew
(squared, and summed over the directions seen in both photos). The
directions hidden behind the electrode strips are left out, which
assumes the hidden part of the edge grew like the visible part.
Every answer carries a confidence score; frames below
the bar go to a human, who picks between candidate outlines or traces
the edge by hand.

### Level 3 — new lab member

The pipeline is a **competition between detection channels, refereed
by an acceptance system**. The channels: thresholded
difference-images (three tiers), a texture-ratio channel (wrinkling
raises local energy against the frame's own baseline — the P3 devices
activate by wrinkling with almost no brightness change), and the
boundary tracker, which ray-casts from the known resting center to the
ink edge itself and reports the resting area times the **common-ray
ratio**: Σr² over Σr₀² on the rays measured on both the baseline frame
and the frame (2026-10-02; a robust ellipse through the same points is
the drawn outline, not the area). A frame showing no detectable change
is measured the same way (the resting-refit, on every such frame since
2026-10-02); only where the tracker cannot measure it is the frame
*stated* as "area = resting area" rather than left blank.
Confidence folds in internal agreement, an incumbent bonus, and
pre/post snapshot agreement; anything under 0.75, or contradicted by
the audit, queues for review, where the reviewer picks a candidate or
hand-traces — and every trace is also banked as a ground-truth label.
A circle prior is allowed only for the resting disc; activated shapes
are measured, never assumed.

### Level 4 — computer-vision-literate colleague

The load-bearing choices:

1. **Normalization** — a gain+offset photometric fit computed on
   paper only (ROI minus disc minus electrode footprint), so a
   changed device cannot drag its own correction. The electrode
   footprint is defined by Laplacian-energy texture, not brightness,
   because most of the copper is dimmer than the paper.
2. **Thresholds that transfer** — the texture channel cuts on a
   physical ratio against the frame's own baseline rather than a
   gray-level constant (per-frame Otsu swings ~2× across one ramp);
   the boundary fitter's per-ray step cut adapts to the scene's
   median ink contrast.
3. **The boundary feature is the ink edge, not the change map.**
   Change-based boundaries ride out to the passive membrane ring that
   hoop-wrinkles around the disc (1.6–2× areas); valley trackers
   follow the taut rim, which migrates inward with kV. Both were
   built, falsified against radial intensity profiles, and rejected.
   The fitter takes the strongest sustained dark→light step per ray
   at 0.80–1.70 r₀ (1.38 through 2026-10-02: that window and the
   1.3 r₀ gate on the fitted ellipse, now 1.75 r₀, refused the flat
   shoulder frames at 1.70–1.94× area although the campaign peaks are
   2.25–2.34×; a ray that meets foil or the frame border inside
   1.8 r₀ is never read, so the window cannot reach the strips; both
   limits are constants, and Edge Review's Save stamps them into
   `setup.txt` as `ray_win_hi` and `disc_fit_r_max` so a run says
   which window its last Detect-and-Save used, per run and not per
   row, owner decision 6, 2026-10-03),
   sub-pixel refined by parabolic interpolation,
   sectors through the electrodes excluded by azimuth. The same rays
   are measured on the baseline frame, and the area is the baseline
   circle × Σr²/Σr₀² over the common rays after a 2.5σ (MAD) trim of
   the per-ray ratio: no shape model, no extrapolation across the
   blocked sectors (2026-10-02; before that the area was π·a·b of the
   robust ellipse, which read −0.4 to +7.4% against the baseline
   circle on the same 0 kV frame). The ellipse is still fitted, for
   the outline, the sanity gates and the audit. The reported spread
   is the central 85% of a 20°-block bootstrap of that ratio; it is
   not a calibrated confidence interval (§2.1). The ratio refuses
   under 60 common rays or under 120° of reach; rays that sit on one
   side of the disc (one-sidedness above 0.6), or a trim that dropped
   more than a fifth of the rays measured on both frames, keep the
   number and the outline but make the candidate review only, never
   auto-accepted (2026-10-03).
4. **Ranking rules with semantics.** Patches contained inside a valid
   boundary fit are supporting evidence and are capped below it. A
   per-ray self-audit (signed offset between the fitted boundary and
   the measured step, plus the fraction of arc with no measurable
   step) gates *acceptance*, not ranking: a winner that fails audit
   keeps its rank and area but loses the right to auto-accept — and
   pair agreement can never lift it back, because two snapshots
   fooled the same way agree beautifully (correlated error is exactly
   what pair agreement cannot certify against). A pair
   *disagreement* caps both snapshots, with one exception since
   2026-10-03: a tracked boundary with a recorded, clean audit
   verdict, and no review-only tag from the ray ratio (one-sided
   rays, a large trim share), whose mate is a patch tier keeps its
   own confidence. The exception relies only on that verdict (the ink
   step under the outline was measured) and on the patch member
   staying capped, so the landing is still queued; it does not know
   why the snapshots disagree. On the review corpus it fires twice,
   both on a one-sided mid-hold collapse (a buckled post-ramp snapshot
   only a tex-ratio patch outlines, a collapsed pre-ramp disc the
   tracker reads): there the accepted number is the collapsed state's,
   and the human sees the collapse through the capped member.

### Level 5 — referee / metrologist

The system is a **hypothesis generator wrapped in a falsification
architecture**, held together by three invariants:

1. **Refuse rather than fabricate.** The baseline tracer returns
   nothing unless arc coverage, fit residual, interior fill, and
   roundness all pass; the tracker's area ratio returns nothing when
   too few rays or too little arc is measured on both frames, and
   hands a one-sided or heavily trimmed reading to a human rather than
   to the auto-accept; no-change frames are measured, or stated
   as the resting area where they cannot be, never given invented
   outlines; weak candidates are tagged so they can never
   auto-accept; wash-out frames route to a human rather than to the
   least-wrong patch.
2. **Every automated claim is either audited or sampled.** The
   boundary self-audit re-measures every accepted winner against the
   raw ink profile (bounding wrong-feature bias below ~0.3% area at
   run level), and the human-label loop samples every stratum —
   including the auto-accepted majority, whose validation closed the
   last dark corner of the acceptance policy.
3. **Confidence is only a review-ordering score until calibrated
   against ground truth.** The calibration falsified naive trust:
   conf was *anti*-calibrated across methods (patch winners at
   0.97–0.99 scored IoU ~0.43 while boundary fits at 0.74 scored
   0.89), which drove a ranking fix; an apparently attractive
   loosening was rejected when the labels showed IoU flattered frames
   whose recorded *area* ran −7%; and that −7% was later decomposed
   into a +5.5% edge-definition offset plus a small real onset term
   by labeling audit-clean controls. Every label lives in an
   append-only sidecar with the machine's contemporaneous candidate,
   so any future change is re-scored against the full ground-truth
   set offline — bounded above by the measured human ceiling (IoU
   0.973), below which no machine is asked to perform better than a
   person agrees with themselves. Design decisions are logged with
   the observation that settled them and are not relitigated without
   new evidence.

---

## 4. Provenance — where each number comes from

| Number | Origin |
|---|---|
| +5.2–5.7% definitional offset | Calibration round 4 (2026-07-30): four audit-clean controls, P3_1 |
| IoU 0.89 median / 0.82 min for disc-fit (n=26) | Pooled calibration, 47 labels, both campaigns |
| Patch tiers IoU ~0.43, area −40..−69% | Same pooled set (n=15) |
| Operator precision ~1% area, IoU ceiling 0.973 | Repeatability round (9 repeat pairs, 2026-07-29) |
| `disc-fit` spread: median 0.6%, 0.2–1.9%; its coverage; repeatability 0.08–0.26% on an unchanged disc; one-sidedness and drift figures; the 112 formerly-`resting` frames | Corpus replay under OpenCV 4.13, 2026-10-02: 16 run folders, 899 frames, 450 auto-accepted tracker rows on 8 runs. Method and tables in §2.1b. **Replaces "Fit CI 0.2–0.7%"**, the edge-scatter formula of the ellipse fit, which assumed a known shape and independent rays and held 21–49% of repeat differences where it claimed 85% |
| Agreement with an independent sector measurement (−1.0 to +0.5 points per run up to 4 kV) | Science review 2026-10-02: a half-height radius on top and bottom sectors that uses no repo detector code, six campaign runs, auto-accepted tracker rows. One reviewer's series, computed under OpenCV 5.0; it is a cross-check between two estimators that both see only part of the edge, not ground truth |
| Sector split above 4 kV (top/bottom-only ratio +2.2 points over the half-height series on DOT_P3_1 at 4.25–6 kV; lead-adjacent rays 1–4 points below top/bottom at 2.25–6 kV; implied over-read of order 1 point at peak) | The same 2026-10-02 replay, the tracker's own rays split by sector (top/bottom = 40–140° and 220–320° from the lead axis, the independent series' sectors), auto-accepted rows. Evidence for the hidden-perimeter term's sign, not a correction (note under table 1.1) |
| The trim's signed effect (median abs 0.27–0.85 points by band, maximum 11.8; `P3_5` peak 1.579 trimmed / 1.463 untrimmed) | The same replay's rays, the production ratio recomputed with and without the 2.5-sigma trim on the 450 auto-accepted rows (reproduces the harness ratios to 1e-5), review of 2026-10-02 (§2.1b, table 2.1) |
| Scale 0.4% / repeat 0.3% | Baseline-disc overlays vs by-eye, both campaigns |
| Scale anchor per run (§2.1a): σ ≈ R/d₂(n), mean SE = σ/√n, area SE = 2·SE | d₂ factors from ASTM E2587 / Duncan (`se.D2_RANGE_FACTORS`, n = 2–8; the code refuses any other n). Range of the n fits recorded in each run's `setup.txt`, plus every round-set in `scale_calibration_log.txt` (Edge Review, 2026-08-06 onward) |
| The circle mode per-fit σ ≈ 1.05% of diameter (3-round mean SE 0.61% diam / 1.21% area) | Six circle-mode attempts on a scratch copy of `P3_2_2.5mL_20260728`, one operator, 2026-08-06 (`#215` comment). **A first data point, not a distribution — quotable only as that; §2.1's 0.4%/0.8% still apply.** |
| σ ≈ 1.0–1.1% holds across **three** hand methods and survives blinding | Thirteen logged calibrations, 2026-08-06/07: circle-fit with a 3 px stroke, the same with a 1 px dashed stroke, and two-point-with-random-rotation. A later round closed a leak that had been printing the recorded anchor's diameter through supposedly blind rounds; the first post-fix circle round still measured σ **1.07%**. **The ~1% is the edge, not the interface** — the disc/paper step is 20 gray levels spread over ~60 px of radius, so there is no line to click |
| Manual calibration is the ONLY source of absolute-area error in the corpus | Corpus-wide auto-calibration sweep, 2026-08-06 (`_analysis\auto_calibration_sweep_20260806.md` beside the campaign data): `baseline_disc` fitted 13 of 15 runs, residual 0.03–0.80% of diameter. **All eleven recorded resting areas are predicted to two decimals by their anchor's deviation from that fit**, and the eight runs with no manual anchor land on π·8² exactly. Optics movement (discs span 362–606 px) is absorbed entirely by per-run anchoring |
| The automatic fit's SYSTEMATIC error | **Not measured, and not measurable by re-fitting.** The only external check is `baseline_disc`'s own note of ~1% agreement with by-eye readings on three P3 baselines. A 0.03% residual is precision, not accuracy |
| Human per-fit σ ≈ 1.0–1.1% of diameter **regardless of method or stroke** (A 1.03%, A′ 1.11%, B 2.09%); stroke cost is BIAS not precision (A +2.07% vs A′ +0.77% in diameter, the §1.3 outer toe) | A/B/A′ session, eleven interleaved calibrations on one disc against a 577.08 px automatic fit, one operator, 2026-08-06 evening (`#215` comment). **One operator, one disc, one session — §2.1's 0.4%/0.8% remain the numbers to quote** |
| Auto-verified anchor uncertainty = the fit's own residual, 0.40% of diameter (2.3 px / 577.08 px over 204 edge points) | `se.fit_resid_pct` on `baseline_disc`'s output. **Conservative** (per-point scatter, not the fitted radius's SE, which is ~√n smaller). σ/SE/range are **undefined** for such an anchor, not zero, and it contributes nothing to §2.5's operator-repeat leg. **The fit's systematic term is unmeasured, and no cross-check of it exists** (declaring the fitted disc 16 mm makes §2.4's mask test pass by construction) |
| Audit bias bound ±0.4 px per run | Boundary self-audit medians, all six runs |
| Refit accuracy (+4.1/+4.6% vs predicted +3.8/+4.2%) | Resting-refit validation vs stored labels (2026-07-30). **Historical: it validated the ellipse area, withdrawn from table 1.2 on 2026-10-02** |
| Onset excess ~1–2% | Round 3 (−6.9%) decomposed by round 4's controls |
| Old-CSV 2.3–2.7× scale error | Baseline re-measurement, 2026-07-28 |
| 16 mm anchor closed (laser-cut mask) | Lab confirmation (Anatol), 2026-08-01 |

Full narrative and the decision log: `SLDEA_HANDOFF.md`. Ground truth:
`edge_labels.json` beside each run's `data.csv` (append-only; re-score
any algorithm change against it with `python sldea_trace.py <runs>`).
