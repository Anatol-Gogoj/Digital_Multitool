# SLDEA active-area measurement — error budget and how the algorithm works

Status: 2026-08-06 (§2.1a; the rest 2026-08-01). Every number in this
document is **measured**, not estimated — sources are the four
calibration rounds (47 operator labels across both campaigns), the
three-round scale calibration, the operator repeatability round, the
per-frame boundary self-audit, and the baseline-scale overlays. The
provenance table at the end maps each number to its origin. When
calibration numbers move (new labels, new campaigns), update this file
in the same PR.

---

## 1. Quick reference — glance here first

### 1.1 What uncertainty do I quote?

| You are reporting | Quote | Dominated by | Conditions |
|---|---|---|---|
| **Expansion ratio A/A₀** (area-vs-kV curves) | **±1–2%** | fit CI + second-order residual of the edge-definition offset | auto-accepted `disc-fit` / `resting` / refit frames |
| **Absolute area (mm²), edge convention stated** | **±1–2%** | scale anchor + fit CI | methods section states the half-height convention |
| **Absolute area (mm²), convention not stated** | **±3%** (or a one-sided +5.5% band) | the edge-definition offset | avoid this — state the convention instead |
| **Hand-traced areas** (wash-out frames ≥5.5 kV) | **±1%** precision, outer-toe convention | operator repeatability | machine has no boundary there; traces are the measurement |

### 1.2 How much do I trust each method?

| Winning method | What it actually measures | Validated accuracy | Auto-accepts? |
|---|---|---|---|
| `disc-fit` | ink-edge boundary, robust ellipse | IoU vs operator: median 0.89, min 0.82 (n=26); own 85% CI 0.2–0.7% | yes, at conf ≥ 0.75 with a clean audit |
| `resting` | asserts the baseline area on no-change frames | audit-bounded to ≤ ~2%; clean controls score IoU 0.94–0.95 | yes |
| `disc-fit` + `resting_refit` | measured boundary on a bias-tripped "no-change" frame | matches the audit-predicted creep (+4.1/+4.6% at P3_1 2.0 kV vs +3.8/+4.2 predicted) | yes, only if its own audit is clean |
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
| Scale anchor (baseline disc trace vs by-eye) | systematic, per run | ~0.4% diameter → **~0.8% area**; 0.3% repeat on one device 32 min apart. From 2026-08-06 **measured per run** — see §2.1a | baseline overlays, both campaigns; per-run spread from the 3-round calibration |
| Nominal diameter (the value the mm scale hangs on) | systematic | **closed** — anchored by the laser-cut application mask | lab confirmation 2026-08-01 (see §2.4) |
| `disc-fit` statistical CI (edge-point scatter) | random, per frame | **0.2–0.7%** (85% CI) | fit CI, both campaigns |
| Operator trace precision (the validation floor) | random | **~1%** area (0.2–2.5%); IoU ceiling 0.973 | repeatability round, 9 repeat pairs |
| Clean `resting` claims | bounded | ≤ ~2% (the 3 px audit-bias gate; the refit measures anything past it) | audit + resting-refit |
| Onset frames (audit-capped fits, interpolated arc) | systematic, local | ~1–2% excess understatement after decomposition | round 3, corrected by round 4 |
| Wrong-feature tracking (halo, smoothing shift) | systematic | bounded **< ~0.3%** area (per-run median audit bias −0.4..+0.4 px) | boundary self-audit, all six runs |

### 2.1a The scale anchor became a per-run measurement (2026-08-06)

Since the fit-a-circle calibration (`#215`), Edge Review takes **three
independent circle fits** of the resting disc per run — each respawned at
a randomized position and size — and anchors on their **mean**. The
**range** of the three is recorded in `setup.txt`
(`rounds_px` / `spread_px` / `spread_pct`) and reported by `sldea_diag`.

What changes is the term's **character, not its size**. Before, ~0.4%
diameter was an estimate borrowed from baseline overlays across
campaigns; now every run carries its own number. The conversion, for a
recorded range *R* on *n* = 3 fits:

- the expected range of 3 normal samples is **1.693 σ**, so
  **σ ≈ R / 1.693** per fit;
- the mean of 3 has standard error **σ/√3 = R / 2.93**;
- diameter → area doubles it: **area SE ≈ 2 · R / 2.93 = R / 1.47**.

Worked at the acceptance gate: a run accepted right at the 1% spread gate
carries **σ ≈ 0.59%** per fit, **0.34% on the mean diameter** and
**≈0.68% in area** — i.e. the gate *caps* the random part of this term at
just under the ~0.4% / ~0.8% previously assumed. A typical 0.3% recorded
spread gives 0.10% diameter / 0.20% area, about four times better than
the old estimate. The old numbers are therefore kept in §2.1 as the
conservative ceiling, and a specific run may quote its own spread instead
— divided by 2.93 for diameter, 1.47 for area.

Three caveats, all load-bearing:

- **This measures precision, not accuracy.** A consistently mis-placed
  circle (the outer toe instead of the half-height, say) produces a tight
  spread and a wrong mean. The **anchor guard** covers that axis by
  cross-checking the mean against the automatic disc fit and against the
  16 mm mask's π·8² resting area at ~1% (see §2.4 and the 2026-08-06
  `SLDEA_HANDOFF.md` entry). Run `P3_2_2.5mL_20260728` is the standing
  example: +2.28% diameter, −4.42% area, a *systematic* miss that no
  spread would have caught.
- **The remaining systematic part does not shrink with n.** Averaging
  divides the random scatter, not the edge-convention offset of §2.3.
- **No run has a measured spread yet.** The mechanism ships 2026-08-06;
  the 1% gate is chosen, not validated. Update this section with the real
  distribution once ~5 runs have been calibrated — and if the gate turns
  out to trip routinely, the honest fix is to raise `CAL_SPREAD_PCT` and
  record the measured spread, not to tighten the operator.

### 2.2 Why ratios are tight: the annulus cancellation

The definitional offset behaves as a near-constant annulus of ~7 px
on a ~289 px resting radius. In a ratio, a fixed annulus cancels to
second order: at 1.2× radius (1.44× area) the residual between the
two conventions is ~0.8%. Combined with the fit CI (0.2–0.7%) and
pre/post pair scatter, **expansion curves carry ±1–2%** — the same
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
inherit only the scale terms (~1%) and the per-frame CI. Fail to pick
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
(~0.8% area) and the per-frame fit CI, i.e. the ±1–2% of table 1.1
with nothing pending.

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
edge — along each one. An ellipse fitted through those edge points
gives the area. Every answer carries a confidence score; frames below
the bar go to a human, who picks between candidate outlines or traces
the edge by hand.

### Level 3 — new lab member

The pipeline is a **competition between detection channels, refereed
by an acceptance system**. The channels: thresholded
difference-images (three tiers), a texture-ratio channel (wrinkling
raises local energy against the frame's own baseline — the P3 devices
activate by wrinkling with almost no brightness change), and the
boundary tracker, which ray-casts from the known resting center and
robust-fits an ellipse to the ink edge itself. A frame showing no
detectable change is *stated* as "area = resting area" rather than
left blank — and if a self-audit finds the ink step measurably off
that circle, the fitter re-measures it (the resting-refit).
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
   at 0.80–1.38 r₀, sub-pixel refined by parabolic interpolation,
   sectors through the electrodes excluded by azimuth, robust trimmed
   ellipse fit, and its reported spread is a genuine 85% CI from the
   edge-point scatter.
4. **Ranking rules with semantics.** Patches contained inside a valid
   boundary fit are supporting evidence and are capped below it. A
   per-ray self-audit (signed offset between the fitted boundary and
   the measured step, plus the fraction of arc with no measurable
   step) gates *acceptance*, not ranking: a winner that fails audit
   keeps its rank and area but loses the right to auto-accept — and
   pair agreement can never lift it back, because two snapshots
   fooled the same way agree beautifully (correlated error is exactly
   what pair agreement cannot certify against).

### Level 5 — referee / metrologist

The system is a **hypothesis generator wrapped in a falsification
architecture**, held together by three invariants:

1. **Refuse rather than fabricate.** The baseline tracer returns
   nothing unless arc coverage, fit residual, interior fill, and
   roundness all pass; no-change frames yield honest statements, not
   invented outlines; weak candidates are tagged so they can never
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
| Fit CI 0.2–0.7% | disc-fit 85% CI, P3 (0.2–0.5%) and 07-23 (0.5–0.7%) runs |
| Scale 0.4% / repeat 0.3% | Baseline-disc overlays vs by-eye, both campaigns |
| Scale anchor per run (§2.1a): σ ≈ R/1.693, mean SE R/2.93, area R/1.47 | Range of the 3 circle fits recorded in each run's `setup.txt` (Edge Review, 2026-08-06 onward). **No run measured yet** |
| Audit bias bound ±0.4 px per run | Boundary self-audit medians, all six runs |
| Refit accuracy (+4.1/+4.6% vs predicted +3.8/+4.2%) | Resting-refit validation vs stored labels (2026-07-30) |
| Onset excess ~1–2% | Round 3 (−6.9%) decomposed by round 4's controls |
| Old-CSV 2.3–2.7× scale error | Baseline re-measurement, 2026-07-28 |
| 16 mm anchor closed (laser-cut mask) | Lab confirmation (Anatol), 2026-08-01 |

Full narrative and the decision log: `SLDEA_HANDOFF.md`. Ground truth:
`edge_labels.json` beside each run's `data.csv` (append-only; re-score
any algorithm change against it with `python sldea_trace.py <runs>`).
