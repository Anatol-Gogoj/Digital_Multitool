# SLDEA active-area measurement — error budget and how the algorithm works

Status: 2026-08-07 (§2.1a; the rest 2026-08-01). Every number in this
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
| Scale anchor (baseline disc trace vs by-eye) | systematic, per run | ~0.4% diameter → **~0.8% area**; 0.3% repeat on one device 32 min apart. From 2026-08-06 **measured per run** — see §2.1a: measured human per-fit **σ ≈ 1.0–1.1% whatever the method**, so a *hand* anchor MISSES this budget below ~7 rounds, while an **auto-verified** anchor carries the fit's own residual (0.40% of diameter here) and no operator term at all | baseline overlays, both campaigns; per-run scatter from the calibration's n rounds (hand modes only) |
| Nominal diameter (the value the mm scale hangs on) | systematic | **closed** — anchored by the laser-cut application mask | lab confirmation 2026-08-01 (see §2.4) |
| `disc-fit` statistical CI (edge-point scatter) | random, per frame | **0.2–0.7%** (85% CI) | fit CI, both campaigns |
| Operator trace precision (the validation floor) | random | **~1%** area (0.2–2.5%); IoU ceiling 0.973 | repeatability round, 9 repeat pairs |
| Clean `resting` claims | bounded | ≤ ~2% (the 3 px audit-bias gate; the refit measures anything past it) | audit + resting-refit |
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
| Scale anchor per run (§2.1a): σ ≈ R/d₂(n), mean SE = σ/√n, area SE = 2·SE | d₂ factors from ASTM E2587 / Duncan (`se.D2_RANGE_FACTORS`, n = 2–8; the code refuses any other n). Range of the n fits recorded in each run's `setup.txt`, plus every round-set in `scale_calibration_log.txt` (Edge Review, 2026-08-06 onward) |
| The circle mode per-fit σ ≈ 1.05% of diameter (3-round mean SE 0.61% diam / 1.21% area) | Six circle-mode attempts on a scratch copy of `P3_2_2.5mL_20260728`, one operator, 2026-08-06 (`#215` comment). **A first data point, not a distribution — quotable only as that; §2.1's 0.4%/0.8% still apply.** |
| Human per-fit σ ≈ 1.0–1.1% of diameter **regardless of method or stroke** (A 1.03%, A′ 1.11%, B 2.09%); stroke cost is BIAS not precision (A +2.07% vs A′ +0.77% in diameter, the §1.3 outer toe) | A/B/A′ session, eleven interleaved calibrations on one disc against a 577.08 px automatic fit, one operator, 2026-08-06 evening (`#215` comment). **One operator, one disc, one session — §2.1's 0.4%/0.8% remain the numbers to quote** |
| Auto-verified anchor uncertainty = the fit's own residual, 0.40% of diameter (2.3 px / 577.08 px over 204 edge points) | `se.fit_resid_pct` on `baseline_disc`'s output. **Conservative** (per-point scatter, not the fitted radius's SE, which is ~√n smaller). σ/SE/range are **undefined** for such an anchor, not zero, and it contributes nothing to §2.5's operator-repeat leg. **The fit's systematic term is unmeasured, and no cross-check of it exists** (declaring the fitted disc 16 mm makes §2.4's mask test pass by construction) |
| Audit bias bound ±0.4 px per run | Boundary self-audit medians, all six runs |
| Refit accuracy (+4.1/+4.6% vs predicted +3.8/+4.2%) | Resting-refit validation vs stored labels (2026-07-30) |
| Onset excess ~1–2% | Round 3 (−6.9%) decomposed by round 4's controls |
| Old-CSV 2.3–2.7× scale error | Baseline re-measurement, 2026-07-28 |
| 16 mm anchor closed (laser-cut mask) | Lab confirmation (Anatol), 2026-08-01 |

Full narrative and the decision log: `SLDEA_HANDOFF.md`. Ground truth:
`edge_labels.json` beside each run's `data.csv` (append-only; re-score
any algorithm change against it with `python sldea_trace.py <runs>`).
