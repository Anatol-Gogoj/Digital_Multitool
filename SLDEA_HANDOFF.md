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

## Open — in rough priority order

1. **Everything still goes to review.** 24/24 frames flagged on all three
   runs; median best-candidate confidence 0.42–0.48 against
   `accept_conf` 0.75. Localization is fixed, but the conf formula
   (solidity + contrast + cross-method agreement + wrinkle bonus) was
   tuned for the diff tiers and the candidates disagree on *extent*
   (spread 27%+): diff-lo traces the full disc while tex-ratio traces
   the wrinkled patches inside it. Decide what "the active area" means
   operationally (full changed disc vs wrinkled interior), then
   calibrate conf/spread so clean frames auto-accept.

2. **Detected area is not monotonic with voltage** (44% of up-ramp steps
   go backwards on run 2). Each frame is detected independently; nothing
   enforces the physics. A temporal prior (previous accepted area as a
   soft anchor) or picking the tier by cross-frame consistency would
   likely fix both this and half of item 1.

3. **Per-frame Otsu instability — still open** (previous handoff task 5).
   The diff tiers remain multiples of a per-frame Otsu that swings
   0.3–3.2σ across a run. The texture channel sidesteps this (its
   threshold is a ratio), which is partly why it wins mid-ramp. If the
   diff tiers stay, express their thresholds in σ above the measured
   noise floor (`sldea_diag` already prints every threshold in σ).

4. **The ~5 kV event is real and now has two independent signatures:**
   detection jumps onto the disc / tex-ratio starts winning, and run 2's
   paper-only gain dips 0.78→0.67. Wrinkle onset / pull-in /
   snap-through remain the candidates. #157 (continuous kV/µA logging)
   would date it electrically.

5. **Secondary candidates sometimes outline the shadow left of the disc**
   (runs 1/3, mid-ramp, 2nd/3rd candidates only — the best stays on the
   device). Harmless for auto-accept but noisy in the GUI; the shadow is
   neither foil (smooth) nor paper.

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
python tests/test_sldea_edge.py      # 31
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
