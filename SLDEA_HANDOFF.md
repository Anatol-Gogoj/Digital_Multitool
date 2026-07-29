# SLDEA detection — handoff

Third session (2026-07-28, evening). The previous handoff's tasks 1–4 are
**done and verified on the frames**: the detector no longer locks onto the
electrodes, the px→mm scale is anchored on a real measurement of the
resting disc, the photometric fit is restricted to the paper background,
and a texture-ratio channel segments the wrinkle map directly. What
remains is calibration, not localization — see "Open" below.

Read this file, then `sldea_edge.py` (`candidates`, `_texture_candidate`,
`prepared_diff`, `photometric_fit`, `foil_mask`, `baseline_disc`,
`mm_per_px`) and `sldea_diag.py`.

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

1. **Calibrate conf against human labels.** Median conf is at 0.87–0.91
   but only 54–79% of frames clear 0.85. ~30 accepted/adjusted frames in
   Edge Review across the three runs would let the conf weights be fit
   so conf ≈ P(IoU with the human ≥ 0.8) — after which raising
   `accept_conf` to 0.85 (or wherever the bar moves) is a measured
   decision, not a guess. This is the next session's main lever.

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

## Repo state you are inheriting

- All of the above is code + tests on this branch; nothing else changed.
- Suites: `test_sldea_edge.py` 31, `test_sldea_diag.py` 16,
  `test_sldea_tuner.py` 8; both `--selftest`s pass.
- `run_tests.py` on the analysis PC: 23/27 — the four failures are
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
python tests/test_sldea_edge.py      # 34
python tests/test_sldea_diag.py      # 16
python tests/test_sldea_tuner.py     # 8
python sldea_diag.py --selftest out.png
python sldea_tuner.py --selftest out.png
python run_tests.py
```

## Related issues

- #157 — log kV/µA continuously at ≥1 Hz. The watchdog already samples
  current at 2 Hz and discards every sample. Would date the ~5 kV event.
- #158 — breakdown detection should trigger on a step change, not an
  absolute µA threshold. Depends on #157.
- #159 — `measured_kV` stops being recorded around snapshot 34. Leading
  hypothesis: the SLDEA path never sets the scope's vertical scale, so
  V_Out eventually leaves the screen and `measure()` returns the 9.9E37
  invalid-measurement sentinel for the rest of the ramp.
