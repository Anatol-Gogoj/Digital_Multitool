# SLDEA detection — handoff

Fourth session (2026-07-29). The previous handoff's two initial tasks
are **done, tested, and verified on all six runs**: (1) the boundary
self-audit is folded into ACCEPTANCE — two per-frame gates cap the
winner below `accept_conf` when the audit contradicts it; (2) the #162
manual-trace tool is built and wired into Edge Review — the labeling
instrument exists, end-to-end. Folding the audit in surfaced a
systematic error no previous conf number ever saw: **stale 'resting'
claims** (below). What remains is operator time, not code — see
"IMMEDIATE NEXT TASKS".

Read this file, then `sldea_edge.py` (`candidates` — the audit fold is
at its end — `audit_boundary`, `reconcile_pairs`), `sldea_trace.py`,
and the `TraceWindow` class in `sldea_edge_gui.py`.

## The audit fold (done this session)

Inside `candidates()`, after ranking: the winning `disc-fit`/`resting`
candidate is audited (`audit_boundary`, attached as `cand['audit']`)
and CAPPED to `accept_conf - 0.01` when either gate trips — the winner
keeps its rank and its area (it is still the best measurement on
offer); it only loses the right to auto-accept, and the tag says why:

- **`audit_nostep`** (`audit_nostep_pct`, default 15): more than 15% of
  the fitted arc has no measurable ink step under it — the interpolated
  onset sectors. Exactly the frames the previous handoff ordered to
  review.
- **`audit_bias`** (`audit_bias_px`, default 3): the median signed
  offset between the fitted boundary and the measured step exceeds
  3 px — the fit (or the resting circle) is not where the ink is.

`reconcile_pairs` cannot boost a capped frame back over the bar: two
snapshots interpolated over the same washed-out arc — or stated resting
while the edge sat outside the circle in both — agree beautifully;
that is precisely the correlated error pair agreement cannot certify
against. The clean partner still gets its bonus. Both knobs are in
DEFAULT_SETTINGS / Advanced… / setup.txt; 0 disables either gate.

## The stale-resting discovery — READ THIS

The nostep gate was the assignment; running the audit against
acceptance exposed a second failure mode on **all six runs, both
campaigns**: in the 1.5–3 kV band the gated frames win as `resting`
("area = resting area", conf 0.84–0.99, auto-accept) while the audit
measures the actual ink step **outside** the claimed circle, drifting
monotonically with kV — bias −4 px at 1.5–2.2 kV growing to **−11 px
(P3_2 at 2.0 kV)** before disc-fit takes over. The disc starts creeping
out below the no-change gate's sensitivity (a few px of a 10–25-level
edge is invisible to the downscaled diff p99), and "resting" silently
understates the area by up to ~7%. The audit saw it all along; nothing
was listening. Those frames now cap to review tagged `audit_bias`, and
each one is a two-minute manual trace away from being both a correct
measurement and a calibration label.

## Where the six runs stand (re-run this session, both gates on)

| run | review | capped: no-step | capped: bias | notes |
|-----|--------|-----------------|--------------|-------|
| P3_1 | 7/48 (was 4) | 2 (5.25–5.75 kV) | 4 | bias caps incl. 5.75 kV disc-fit at +10.4 px |
| P3_2 | 12/48 (was 8) | 0 | 4 | the −11 px resting pair at 2.0 kV |
| P3_3 | 8/48 (was 6) | 0 | 2 | 1.5 kV resting pair |
| 152205 | 21/48 | 9 (2.25–5.25 kV) | 8 | onset 4.75–5.25 kV nostep 19–31% |
| 155425 | 33/48 | 20 | 8 | **see floor note below** |
| 233451 | 31/48 | 8 | 8 | all 8 bias caps are the 2.2–3 kV resting drift |

Median audit bias per run stays −0.4..+0.4 px — the no-feature-bias
verdict stands; these caps are per-frame exceptions, not a systematic.

**The 155425 floor:** that device's resting boundary has a stable
~15.5–16% faint-arc sector (constant 24–25 of 155 audited rays on
every low-kV frame, bias clean there). The 15% default sits just under
that floor, so its whole low ramp caps to review. After eyeballing one
such frame, either raise `audit_nostep_pct` to ~20 for that run
(Advanced… → save to setup.txt) or accept the review load. Do NOT
raise the default: P3's floor is 0–2.8% and the default catches real
onset interpolation there.

## The #162 manual-trace tool (built this session)

`sldea_trace.py` (headless model, 10 tests) + `TraceWindow` in
`sldea_edge_gui.py` (button "✏ Trace (T)" beside Accept/Reject).
Everything in the issue spec: click-to-place points closing into the
outer boundary, wheel zoom about the cursor, middle/space-drag pan, F
fit, drag to move a point, right-click to delete one, Undo/Redo as
buttons AND Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z, Restart-with-confirm that
is itself one undoable op, min 3 points, self-intersection warning
with override, optional edge-snap magnet (OFF by default, labels
tagged `snapped`), overlays (resting disc ON by default; candidates
and previous outline OFF so labels are not anchored to what the
machine drew — visibility state recorded per label).

On close the polygon becomes the frame's accepted result (`method
'manual-trace'`, conf 1.0, `chosen_by: user`, wrinkle index computed
over the traced region) and flows through the normal
`apply_results`/`write_back` path — CSV note `edge:manual-trace conf
1.00 (user)`. Simultaneously a label record (full-res polygon, frame
shape, kV/tag, timestamp, OS user, zoom, overlay state, elapsed
seconds, snapped flag, and the machine's best candidate at trace time)
is appended to `edge_labels.json` beside data.csv — atomic tmp+replace,
append-only across sessions, refuses (never clobbers) a corrupt file.
Tracing itself never touches data.csv/setup.txt.

The calibration consumer already exists:

```
python sldea_trace.py <run-or-parent> [...]
```

pools every `edge_labels.json` it finds and prints the conf-vs-IoU
table (P(IoU >= 0.8) per conf bin, per-method medians) — the curve
that decides what `accept_conf` may rise to.

## IMMEDIATE NEXT TASKS (operator time, in order)

1. **Label ~30 frames across both campaigns** with the tracer, chosen
   where the labels matter most: the onset band (4.5–5.75 kV, both
   campaigns — the interpolated-arc frames now queued for review), a
   few of the 1.5–3 kV `audit_bias` resting frames (each trace is both
   the corrected measurement and a label), and a handful of clean
   mid-ramp disc-fits as controls. Every review-queue frame traced =
   one measurement fixed + one label earned.
2. **Run `python sldea_trace.py` over the runs** → the conf-vs-IoU
   curve → raise `accept_conf` to whatever the curve supports. This
   also audits the pair-confirm/hysteresis boosts (correlated errors
   included), which no internal check can.
3. Spot-read the new review queue on the contact sheets — the capped
   frames are annotated with their tags in Edge Review and the
   diagnostic (`audit_nostep` / `audit_bias` per frame in the JSON,
   counts in the verdicts).

## The original self-audit spec (historical; implemented and now folded into acceptance)

**Build the boundary self-audit, run it on all six runs, and report the
bias numbers — before any labeling happens.** Rationale: conf is
currently a consistency score (see "Does higher conf mean more correct
edges?" below); the audit is the only correctness check that costs the
operator nothing, and if it finds a systematic bias, that gets fixed
BEFORE operator labeling time (#162) is spent measuring a known flaw.

Spec, agreed with Anatol:

- New function in `sldea_edge` (so the GUI/tuner can reuse it), e.g.
  `audit_boundary(prep, cand, settings)`; reported by `sldea_diag`.
- For every frame whose best candidate is `disc-fit` or `resting`:
  along the FITTED boundary, per kept ray, locate the local ink step's
  half-height position and report the SIGNED offset to the fitted
  radius (+ = fit outside the step), plus the fraction of boundary arc
  with NO measurable step beneath it (step below the scene's adaptive
  cut within a ±window).
- Per frame: median signed offset (px, full-res), MAD, no-step arc %.
  Per run: median bias, p95 |offset|, median no-step arc — new report
  section + JSON block + two per-frame columns.
- Decision rule: |median bias| <= 2 px AND no-step arc <= 10% on all
  six runs -> detections trustworthy at the current bar; proceed to
  #162 labeling. Anything worse -> investigate the feature bias first
  (prime suspects: halo interference, asymmetric-soft-edge smoothing
  shift; see the rejected-designs history in the decision log).
- Tests: a synthetic with a known boundary audits to ~0 bias; a
  candidate deliberately shifted +5 px audits to ~+5; the ring-artifact
  scene audits to a large no-step arc.
- "Circled the noise" maps exactly to: large no-step arc. Systematic
  wrong-feature maps to: nonzero bias with small MAD. Say which, with
  numbers, in the handoff when done.

Then, second: the #162 manual-trace tool + ~30 operator labels across
both campaigns -> the conf-vs-IoU calibration curve -> raise
`accept_conf` to whatever the curve supports. In that order.

Start from `main`. The work described here was developed on
`claude/automated-tuning-tasks-3f935d`.

## The physical setup

VHB 4910 acrylic elastomer sandwiched between two rigid annuli that sit
just barely in frame. Electrodes are CNT ink (2.5 mL used in the transfer
— that is what the `2.5mL` in the run names means, not a liquid volume).
Copper strips contact the electrodes and run roughly horizontally across
the frame; smooth dark CNT traces connect the strip ends to the disc.
The whole assembly lies flat on **paper**, which is the background. There
is no liquid and no dish.

Frames are 1920×1080. A run is ~40 voltage steps to 10 kV, with **two
snapshots per step** (`pre-ramp` and `post-ramp`) about 57 s apart, so a
run takes ~40 minutes and yields ~81 rows.

**The contrast asymmetry that drove everything.** The resting disc sits
10–25 gray levels below the paper (measured: disc 162–167, paper
176–190); the foil strips span 120–255 and cover 12.7–13.3% of the frame
(median foil pixel 173 — most of the strip is *dimmer* than paper, which
is why `electrode_lum` never could mask it). The device is the
lowest-contrast object in the scene; texture, not brightness, is the
channel where it wins.

### Where the data is

The three runs are OneDrive-synced to (at least) two machines:

```
C:\Users\anato\OneDrive - University of Connecticut\Recordings\SLDEA_data\        (bench PC)
C:\Users\Anatol Gogoj\OneDrive - University of Connecticut\Recordings\SLDEA_data\ (analysis PC)
    P3_1_2.5mL_20260728\   P3_2_2.5mL_20260728\   P3_3_2.5mL_20260728\
```

each with `data.csv`, `setup.txt` and `frames/` (81 frames + baseline).
`sldea_edge.BENCH_RUNS` now picks whichever root exists, so
`python sldea_diag.py 1` works on both machines. None of the three runs
has a saved edge-settings section, so **all three run on
`DEFAULT_SETTINGS`** — including the new `tex_seg: 1`.

## Done and verified this session (2026-07-28)

**The resting-disc diameter is measured, by eye and by code, and the old
scale error is quantified.** Radial-edge measurement with a trimmed circle
fit, verified on overlays drawn on the real baselines (they hug the
visible disc edge on all three runs):

| run | by eye (px) | `baseline_disc` (px) | old blob (px) | old error | mm/px now |
|-----|------------|----------------------|---------------|-----------|-----------|
| 1   | 579.1      | 576.5                | 896           | 1.55×     | 0.02775   |
| 2   | 578.2      | 577.5                | 951           | 1.65×     | 0.02771   |
| 3   | 586.4      | 586.5                | 897           | 1.53×     | 0.02728   |

Every `active_area_mm2` recorded in the three CSVs is therefore
**understated by 2.3–2.7× (area)**. The run CSVs were *not* rewritten
(guardrail below); reprocessing through Edge Review with the fixed code
will produce correct values. Ellipse fits are near-circular (axis ratio
0.97–1.00) and the three runs agree within 1.5%, as they should for a
fixed camera geometry.

**`baseline_disc` was rewritten** (the old one merged disc, strips and
surround into one blob spanning 85% of the frame — circ 0.32 at conf
0.93). Region-growing is unfixable here: smooth CNT traces and
under-strip shadows bridge the dark class to the strips no matter how the
foil is masked. The new detector seeds on the central dark region, casts
360 radial rays, keeps the strongest dark→light step per ray where the
edge neighborhood is clear of foil/glint, and fits a circle robustly
(twice — an off-centre seed truncates the far side). It **refuses**
(returns None) unless ≥120° of arc, fit residual ≤6% of radius, the
circle is filled with the dark class, the diameter is a plausible ROI
fraction, and the edge-point ellipse is round (≥0.85 — the P3 discs
measure 0.966–0.999; the blob read 0.32). conf is built from fill, arc
coverage and residual, so a barely-passing shape cannot read as
certainty. On the P3 baselines it lands within 0.4% of the by-eye
measurement at conf 0.86–0.87; on a scene with no disc it returns None
where the old code returned the blob.

**The electrode footprint is texture-defined** (`sldea_edge.foil_mask`):
p92 of local Laplacian energy (floored so flat scenes yield nothing),
close-41 / open-15, drop components thinner than 30 px of inscribed depth
(a step edge smears into a band exactly one box-window wide — without the
thickness gate a hard-edged disc's own rim classifies as foil), keep
≥0.5% components, dilate 15. Coverage 12.7–13.3% on the three baselines,
hugging the strips — verified on overlays. Cached per baseline
fingerprint.

**Electrode suppression now covers the whole strip** (`prepared_diff`):
the brightness cut (34–42% coverage — only the specular streaks) is
unioned with the foil footprint under the same `electrode_lum` knob.
Result across the three runs: **detected area on foil went from 83–100%
to 0–1%** (`foil%` column in the diagnostic; verified on the contact
sheets — every best outline now sits on the device).

**The photometric fit is restricted to paper** (Q1 implemented):
`photometric_fit` takes an optional pixel mask; under `norm_bg: 2` the
fit region is ROI minus disc minus foil (`_paper_mask`), falling back to
the plain ROI when there is nothing to exclude, so synthetic scenes and
`norm_bg: 0/1` reprocess identically. The diagnostic reports both fits
per frame (`gain` vs `g-pap`); on run 2 the ~5 kV gain excursion
(0.78 → 0.67) survives the paper restriction, confirming it is a real
scene change, not the device dragging its own correction.

**Texture-ratio segmentation is in** (`tex_seg: 1`, method
`'tex-ratio'`): dense energy ratio frame/baseline (full-resolution, the
ridges do not survive downscale), regularized, foil+glint neutralized,
thresholded at `wrinkle_ratio` (1.4) — a physical ratio against the
frame's own baseline, so it transfers where a gray-level constant does
not. A candidate must be wrinkled *through* (its band-eroded core median
must clear the threshold), which kills the boundary-artifact rings that
plague ratio maps. The no-change gate no longer drops a frame the
texture channel can detect — a fine wrinkle can be invisible to the
downscaled diff, and that is precisely the P3 activation mode
(`sep_intensity` 0.000 everywhere; `sep_texture` ~0.3). On the bench
runs `tex-ratio` wins exactly in the 4.5–5.75 kV window — the Q2 event.

**Diagnostic upgrades:** per-frame `foil%` and winning `method` columns,
`g-pap`, a BASELINE header line (disc diam → mm/px, foil coverage), two
new verdicts (localization; scale anchoring), and the contact sheet now
leads with a baseline panel showing the disc trace and foil footprint.

## Added the same evening — the boundary tracker (disc-fit)

The lab ruled (2026-07-28): **active area = the full responding disc,
wrinkled and non-wrinkled together; the electrode leads that feed the
copper tape are not part of it.** That unlocked the strongest prior in
the scene — the object being tracked is known — and detection became
"fit the boundary of the known disc" instead of "pick the best blob".

**`disc-fit`** (in `candidates()`, wins by conf when the disc responds):
rays from the resting-disc centre; per ray, the strongest sustained
dark→light step of the **ink edge on the photometrically normalized
frame**, searched at 0.80–1.38 r₀; strips and the leads that feed them
excluded by azimuth (±10° around foil-blocked sectors); robust trimmed
ellipse fit; area from the fitted shape, so no merge-close area steps.
Its `spread_pct` is its own **85% CI on area** from the edge-point
scatter (0.2–0.5% on the bench runs) — a statistical statement, where
the cross-tier spread it replaces measured threshold sensitivity.

Two designs were tried and rejected on the frames before this one, and
both failure modes are worth remembering. A *change-map* boundary rides
out to the **passive membrane ring** that hoop-wrinkles around the
expanding disc (saturated response out to 1.27 r₀ at 4.25 kV — real
mechanics, but not active area) and reports impossible 1.6–2× areas; a
*valley* tracker between disc response and ring response follows the
taut rim of the active disc, which migrates inward with kV, so the area
shrinks as the voltage rises. The ink edge is the only feature that IS
the boundary. **Verified against intensity profiles**: at 4.25 kV the
edge visibly moved ~80 px and the fit sits exactly on the step
(`edge_profiles.png` in the session scratchpad; regenerate any time).

**`resting`**: a gated frame with a known resting disc now states
"area = resting area" (conf 0.82–0.91, growing with the gate margin)
instead of leaving an empty row queued for review over nothing.

**`ramp_consistency`** (sldea_edge): pre/post same-kV pairs must agree
and area must not dip against rising voltage; violations are annotated,
never averaged away. Wired into Edge Review's save path and the
diagnostic (verdict + `consistency` block; the diag now samples both
members of each chosen pair).

**Where the bench runs now stand** (24 sampled steps → 48 frames each):

| run | review rate | median conf | conf ≥0.85 | pair mismatches | dips |
|-----|------------|-------------|-----------|-----------------|------|
| 1   | 8/48       | 0.91        | 30/48     | 4               | 0    |
| 2   | 9/48       | 0.90        | 38/48     | 6               | 0    |
| 3   | 7/48       | 0.87        | 26/48     | 2               | 1    |

(Previous state: 24/24 review, median conf 0.42–0.48, 44% of up-ramp
steps going backwards.) The area-vs-kV curve is now reproducible across
all three runs: growth from 1.0× to a **peak ~1.4–1.5× around
4.5–5 kV, then partial retraction to ~1.15–1.3×** — consistent with
wrinkle onset converting in-plane expansion into out-of-plane buckling,
and with the ~5 kV event all previous evidence pointed at.

## Open — in rough priority order

0. ~~The boundary self-audit~~ — **done and folded into acceptance
   (2026-07-29)**, see the top of this file.

1. **Calibrate conf against human labels** — the #162 tool is BUILT;
   what remains is the operator's ~30 labels across both campaigns,
   then `python sldea_trace.py <runs>` for the curve, then raising
   `accept_conf` to what the curve supports. Conf still certifies
   consistency, not correctness, until this is done. See IMMEDIATE
   NEXT TASKS at the top.

2. **Pair mismatches (2–6 per run) need eyes.** Most sit around the
   ~5 kV event, where the pre-ramp and post-ramp snapshots are 57 s
   apart and the state may genuinely differ mid-transition — but some
   may be tier flips between channels. The annotations name the frames;
   the contact sheet shows them.

3. **The ~5 kV event**: now visible as the area peak + tex-ratio wins +
   run 2's surviving paper-gain dip. #157 (continuous kV/µA logging)
   would date it electrically against the area curve.

4. **Per-frame Otsu instability** (previous task 5) — still open but
   demoted: the diff tiers are secondaries now. If they stay, express
   their thresholds in σ above the measured noise floor.

5. **Leads**: excluded by sector-blocking plus the robust fit. If a
   device is ever built whose leads leave the disc away from the strip
   azimuths, the exclusion needs the lead's own azimuth.

## Confidence round 2 (2026-07-29) — pair-confirm, hysteresis, sub-pixel

Three mechanisms, one commit, all three validated on both campaigns:

- **Sub-pixel, contrast-adaptive disc-fit rays**: parabolic refinement
  on the ink step, and the per-ray step cut derived from the scene's own
  median ink contrast (`max(3, 0.35·median)`) instead of a fixed 4 —
  the P3 ink steps 10–25 with a fainter top arc while the 07-23 devices
  step 40+ and their spurious lead/shadow edges alone reach 6–8. Effect:
  coverage up (disc-fit now holds through the P3 5.75 kV event frames it
  used to refuse), residuals down.
- **Channel hysteresis** (`candidates(..., prev_method=)`): the previous
  frame's winning channel gets +0.05, tagged `hyst_bonus`, so a
  challenger must win by a margin, not a coin flip. Threaded through the
  GUI detect loops, the diagnostic and the contact sheet.
- **Pair agreement folded into conf** (`reconcile_pairs`, called by the
  GUI between detection and auto-accept, and by the diagnostic): best
  candidates of a same-kV pair that agree within a CI-derived tolerance
  gain +0.05 (`pair_confirmed`); past twice the tolerance both are
  capped below `accept_conf` (`pair_mismatch_pct`) — a confident tier
  flip can never auto-accept on both sides of a contradiction.
- Plus the **containment cap**: a tex-ratio patch sitting inside a valid
  disc-fit is capped just below it (`capped_by`) — the recorded area is
  the boundary's, per the active-area ruling; tex still wins outright
  where the fit refuses.

| run (pre-event where marked) | review | median conf | conf ≥0.85 |
|------|--------|-------------|-----------|
| P3_1 | 4/48 (was 8) | 0.97 (was 0.91) | 79% (was 63%) |
| P3_2 | 8/48 (was 9) | 0.99 (was 0.90) | 83% (was 79%) |
| P3_3 | 6/48 (was 7) | 0.95 (was 0.87) | 90% (was 54%) |
| 152205 <5.2 kV | 1/40 (was 6) | 0.93 (was 0.84) | 83% |
| 155425 <5.2 kV | 2/40 (was 6) | 0.93 (was 0.83) | 78% |
| 233451 <5.2 kV | 2/32 (was 6) | 0.95 (was 0.87) | 78% |

Contact-sheet check (P3_2): every sampled frame disc-fit or resting,
boundaries on the visible edge including 5.75 kV (1.33× resting, conf
0.97, smooth between the 4.5 peak and the 7.25 plateau). The known
caveat of pair-confirm: correlated errors would be boosted together —
which is exactly what the human-label calibration (issue #162) exists
to audit. Do that next, before trusting any bar above 0.85.

## Does higher conf mean more correct edges? (operator question, 2026-07-29)

Anatol asked the right question after round 2: "for all I know, we could
be more confident that we've circled the noise." Here is exactly what is
and is not certified, so nobody mistakes the number for more than it is.

**What is ground-truthed (human- or profile-verified):**
- The resting-disc scale, on all six baselines across both campaigns —
  by-eye overlay measurement, agreement within 0.4% (P3) and repeat
  agreement 0.3% between two runs of one device (07-23).
- One activated frame verified against physics directly: run 2 @
  4.25 kV, where the fitted boundary sits exactly on the intensity step
  in the profile plot, and the step itself visibly moved ~80 px
  (`edge_profiles.png`). This is a SPOT CHECK, not a systematic audit.
- Contact sheets for five runs read frame-by-frame — but by the agent,
  from rendered PNGs. The operator has seen selected sheets in chat.

**What the round-2 boosts actually certify — consistency, not truth:**
- The hysteresis bonus is a prior, no new evidence at all.
- Pair-confirmation is real evidence against RANDOM error (two
  exposures, independent sensor noise) and no evidence against
  CORRELATED error: same scene, same lighting, same algorithm — two
  snapshots fooled the same way agree beautifully and both get +0.05.
- The sub-pixel/adaptive rays changed the measurement itself (more
  rays, tighter residuals). Probably more accurate; not proven against
  ground truth.
- The containment cap is a ranking rule, not a correctness claim.

**Why "circled the noise" is bounded but not excluded.** A disc-fit
boundary must be a sustained >=3-gray-level dark->light step, at
0.8–1.38x the verified resting radius, roughly concentric, round, and
reproducible across pairs, runs and devices — sensor noise cannot
manufacture that. What CAN survive every one of those checks is a
systematically wrong FEATURE: the halo's outer rim instead of the ink
edge, or a few-px bias from smoothing an asymmetric soft edge. The
change-map and valley failures caught during development (1.6–2x and
shrinking-with-kV areas) were exactly this class, caught by physics
plausibility and profile reads — the ink-edge design survived those
tests, but only one activated frame has been profile-verified since.

**Conf today = "strength of internally consistent evidence."** It is
valid for ORDERING frames for review. It is NOT a calibrated
probability of a correct boundary. Treat conf >= 0.85 as "no internal
contradiction found", not "validated correct".

**What converts it into the real thing, in order of power:**
1. Manual-trace labels (#162) -> the conf-vs-IoU calibration curve.
   This audits everything at once, including correlated-pair boosts.
2. A cheap automated self-audit (no human needed): for every ACCEPTED
   frame, report the signed offset between the fitted radius and the
   local step's half-height along each kept ray, plus the fraction of
   boundary arc that has no measurable step under it. A systematic
   feature bias shows up as a nonzero mean offset; "circled noise"
   shows up as no-step arc. Not yet implemented; small.
3. Operator spot-reads of the contact sheets (minutes per run).

## Generalization check (2026-07-29) — the 2026-07-23 dataset

Ran unmodified on `D:\Downloads\SLDEA_data\SLDEA_20260723_*` — a
different campaign entirely: color frames, the full 3D-printed annulus
in frame, a TEXTURED blue foam background instead of paper, tape strips
entering vertically (152205/155425) or horizontally (233451), a much
smaller higher-contrast disc, one run at camera gain 44, and a steady
camera (fitted gain 1.00 — the P3 photometric pedestal was that
campaign's artifact, and the fit correctly no-ops here). Zero retuning.

- **Scale**: disc 371/372 px on the two afternoon runs of the same
  device 32 min apart (0.3% repeatability), 362 px at night; circ 0.98,
  conf 0.85–0.88 on all three. Verified on the contact-sheet baseline
  panels.
- **Detection**: resting auto-accepts the low ramp; disc-fit tracks the
  expansion (CI 0.5–0.7%) mid-ramp; review 6/40 and 6/32 frames below
  5.2 kV at median conf 0.83–0.87.
- **The flags above 5.2 kV are the device, not the detector**: both
  devices break down — the CSVs record −78 µA at 6.0 kV (152205) and
  −26 → −123 µA over 5.6–6.4 kV (233451, which stopped at 7.6 of a
  planned 10 kV). Wrinkle onset ~5.2–5.6 kV is visible in the frames;
  post-breakdown frames yield small flagged non-disc changes, never a
  fabricated disc.
- **Known limits observed** (both fail toward review, not toward wrong
  numbers): the annulus' print texture partially enters the foil mask
  (harmless — a static object; costs a few blocked ray azimuths), and
  under violent bright wrinkling near breakdown the ink edge washes out
  and disc-fit yields to tex/diff candidates with review. A
  "bright-wrinkle boundary" mode could extend coverage there if those
  frames ever matter; they are post-failure frames today.
- The aborted 2-frame run (233426) and the frameless folder (145259)
  are handled gracefully (no crash; nothing invented).

## Decision log (2026-07-28, both sessions)

Every entry is a choice that could have gone another way; the evidence
column is what settled it. Do not relitigate these without new evidence.

| Decision | Why | Evidence |
|---|---|---|
| Active area = full responding disc, leads and passive ring excluded | Lab ruling (Anatol, 2026-07-28) | — |
| Measure the resting disc by radial rays + robust circle fit, not region-growing | Smooth CNT traces and under-strip shadows bridge the dark class to the strips past ANY mask; region-growing is unfixable here | Overlays: cyan region contour leaks to both strips on all 3 baselines; fit lands 0.4% from by-eye truth |
| A circle prior is legitimate for `baseline_disc` only | The resting disc is circular by construction; the activated area is not | P3 discs measure axis ratio 0.966–0.999 at rest |
| Define the foil by texture, not brightness | Median foil pixel (173) is dimmer than paper (176–190); a brightness cut can only catch specular streaks (34–42% coverage) | Foil-fraction of detections fell 83–100% → 0–1% after full-footprint suppression |
| Thickness gate (30 px inscribed depth) on foil components | A step edge smears into a band exactly one box-window wide; real crinkle is a filled region — without the gate a hard-edged disc's own rim classifies as foil | Synthetic rim false-positive; real strips have ~100 px depth |
| Fit photometry on paper only (ROI − disc − foil) | A changed region bigger than the trim can absorb drags its own correction | Q1: run 3's gain dip 0.77→0.55 vanished under restriction; run 2's survived (real scene change) |
| Texture threshold is a ratio vs the frame's own baseline (`wrinkle_ratio`), not a gray-level | Gray-level constants do not transfer: per-frame Otsu swings 0.3–3.2σ across one run | TRANSFER section of the diag; tex channel stable where tiers flip |
| Texture candidates must be wrinkled THROUGH (band-eroded core) | A step edge draws a high-ratio ring around a smooth interior; a ring thinner than the box window is indistinguishable from that artifact | Synthetic flat-disc ring false-positive at spread 27% |
| Boundary feature = the INK EDGE on the normalized frame | The change map cannot mark the boundary: a change edge rides out to the passive wrinkle ring (1.6–2× areas); the valley between responses tracks the taut rim, which migrates inward with kV | Radial profiles at 4.25 kV: ring saturates to 1.27 r₀; ink step visibly moved ~80 px and the fit sits on it (`edge_profiles.png`) |
| The passive membrane ring is excluded like the leads | It responds (hoop-wrinkles) but is not electroded | Lab ruling + the 4.25 kV profile |
| `spread_pct` on disc-fit = its own 85% CI on area | Cross-tier spread measures threshold sensitivity; a boundary fit's honest dispersion is its edge-point scatter | CI 0.2–0.5% on the bench runs |
| Corroboration pools split by semantics (tiers / tex / disc-fit) | Mixing full-region and interior-subset areas into one spread sent 24/24 frames to review over a difference of DEFINITION | Review rate 100% → 15–19% with no change to any threshold |
| Gated frames with a known disc are stated as `resting`, not blanked | "No detectable change + known object" is a measurement (area = resting), not an absence | Low-kV frames auto-accept at conf 0.82–0.91; empty-scene behavior unchanged (no ref → no fabrication) |
| Pair mismatches and dips are ANNOTATED, never averaged away | A mismatch usually means the detection changed, not the device; a dip usually IS the event | `ramp_consistency`; flags cluster in the 4.6–5.9 kV band |
| Report text stays ASCII | cp1252 consoles: one `→` crashed the whole diagnostic | UnicodeEncodeError on the analysis PC |
| Per-ray step cut adapts to the scene's median ink contrast (`max(3, 0.35·median)`) | One fixed cut cannot serve ink at 10–25 levels (P3, faint top arc) and 40+ levels (07-23, junk lead edges at 6–8) | Round-2 tables; disc-fit now holds through the P3 5.75 kV frames it refused |
| Incumbent channel gets +0.05 hysteresis, tagged | Near-tied channels flipped on single frames and caused most pair mismatches | Pair mismatches 2–6/run → 0–2 after |
| Same-kV pair agreement folded into conf: +0.05 within CI tolerance, both capped below accept past 2× | The pair is the run's own control — but it certifies against random error only, not correlated error | Round-2 tables; caveat in the epistemics section above |
| A tex patch contained in a valid disc-fit is capped below it | The recorded area is the boundary's, per the active-area ruling; interior wrinkle is supporting evidence | 5.75 kV frames now record the boundary, not the patch |
| conf is a review-ordering score, not a probability of correctness | Only the #162 label calibration can make it one; pair-confirm boosts correlated errors too | Epistemics section above |
| The self-audit gates ACCEPTANCE, not ranking: a capped winner keeps rank and area, loses auto-accept | The fit is still the best measurement on offer; the recorded area stays the boundary's, but the audit's contradiction sends it to a human | 2026-07-29 fold; audit_nostep / audit_bias tags |
| Per-frame no-step cap at 15% (audit_nostep_pct), per-run tunable | Sends the interpolated-arc onset frames to review, as specified in the previous handoff | 31 frames capped across six runs, all in the onset band or the 155425 floor |
| A second audit gate on per-frame bias (audit_bias_px, 3 px) | Stale 'resting' claims: all six runs drift −4..−11 px in the 1.5–3 kV band while auto-accepting at conf 0.84–0.99 — the disc creeps out below the diff gate's sensitivity | Stale-resting section above; P3_2 2.0 kV pair at −11 px |
| An audit cap survives pair confirmation | Two frames wrong the same way agree; the audit's per-boundary verdict outranks cross-frame consistency | reconcile_pairs; test_pair_agreement_cannot_lift_an_audit_capped_boundary |
| Labels are full polygons + the machine's candidate at trace time, in an append-only atomic sidecar | IoU must be computable offline without re-detection; a mid-write failure must never destroy accumulated ground truth | #162 spec; edge_labels.json; corrupt file refuses rather than clobbers |
| Manual traces flow through the NORMAL accept path (method 'manual-trace', conf 1.0) | One save path, one CSV semantics; tracing is also the recovery path for frames where the detector honestly gives up | apply_results note 'edge:manual-trace conf 1.00 (user)' |

## Repo state you are inheriting

- All of the above is code + tests on this branch; nothing else changed.
- Suites: `test_sldea_edge.py` 41, `test_sldea_diag.py` 16,
  `test_sldea_trace.py` 10 (new), `test_sldea_tuner.py` 8; both
  `--selftest`s pass.
- `run_tests.py` on the analysis PC: 24/28 — the four failures are
  environmental and pre-existing (`test_arb_bin`, `test_camera_controls`,
  `test_presets_path` expect read-only-dir writes to fail, which Windows
  ACLs don't enforce the way the test assumes; `test_tk_fontfix` fails
  identically on a clean `main` checkout). `test_scope_trace` passes here
  (anaconda has tkinter).
- Python on the analysis PC: `C:\ProgramData\anaconda3\python.exe`
  (3.11, cv2 4.11, numpy 1.26). The PATH `python` (3.10) has no cv2.
- Git history was cleaned on 2026-07-28 (555 MB zip dropped from local
  history; never pushed). `.gitignore` excludes `P3_*/`, `SLDEA_*/`,
  `*.zip` and diagnostic outputs — that only protects you if nobody uses
  `git add -f`.

## How to run the loop

```
python sldea_diag.py 1                        # bench shortcut, either machine
python sldea_diag.py "<path to run>" --out DIR
```

Writes `sldea_diag.txt / .json / .png / _contact.png`. **Use `--out` —
the run folders already contain outputs from earlier sessions and the
default path overwrites them.**

**Read `sldea_diag_contact.png`.** Panel 0 is the baseline with the disc
trace and foil footprint; the rest are ramp frames with kV, method, area,
conf and review state. The statistics said nothing while every outline
sat on the strips; the frames are the check no residual substitutes for.

## Guardrails

- Do not commit run data, the zip, or diagnostic outputs. Never
  `git add -f` in this repo.
- Do not modify `data*.csv` or `setup.txt` in the runs. The diagnostic is
  read-only; `sldea_edge.write_back` and the tuner's Save are not, so if
  you use Edge Review's save path, work on a copy. (This is why the
  known-wrong mm² values in the three CSVs were left in place.)
- Keep `norm_bg: 1` working. Runs tuned under the legacy scalar must
  reprocess identically — the scalar branch in `prepared_diff` is
  untouched and `_paper_mask` only affects `norm_bg: 2`.
- `tex_seg: 0` restores the pre-2026-07-28 diff-only detector if a legacy
  comparison is ever needed.
- The bench PC is Windows with a conda Python; `deploy/Tune_SLDEA_Windows.bat`
  is the launcher and `/diag` runs the diagnostic. Two traps already hit
  and fixed there: `shift` moves `%0` so `%~dp0` must be banked first,
  and Python must never be invoked from inside a `for /f`.
- Report text must stay ASCII: the bench/analysis consoles are cp1252 and
  a single `→` in a verdict crashed the whole diagnostic.

## Verification

```
python tests/test_sldea_edge.py      # 41
python tests/test_sldea_diag.py      # 16
python tests/test_sldea_trace.py     # 10
python tests/test_sldea_tuner.py     # 8
python sldea_diag.py --selftest out.png
python sldea_tuner.py --selftest out.png
python run_tests.py
```

## Related issues

- #162 — manual boundary tracing: **the tool is built (this session)**;
  the issue stays open until the ~30 operator labels and the
  calibration curve exist.
- #157 — log kV/µA continuously at ≥1 Hz. The watchdog already samples
  current at 2 Hz and discards every sample. Would date the ~5 kV event.
- #158 — breakdown detection should trigger on a step change, not an
  absolute µA threshold. Depends on #157.
- #159 — `measured_kV` stops being recorded around snapshot 34. Leading
  hypothesis: the SLDEA path never sets the scope's vertical scale, so
  V_Out eventually leaves the screen and `measure()` returns the 9.9E37
  invalid-measurement sentinel for the rest of the ramp.
