# SLDEA detection — handoff

You are picking this up in a working directory that has something the
previous session never had: **the actual run frames**. Roughly half a
gigabyte of them, which is why they could not be sent. Everything below
was established without ever seeing a frame — from `sldea_diag.py` JSON
output alone. Your job is to run the loop with the images in hand.

Branch: `claude/local-tuning-win11-qsqpqo` (PR #156). Start by reading
`sldea_edge.py` (`candidates`, `photometric_fit`, `prepared_diff`) and
`sldea_diag.py`.

## The physical setup

VHB 4910 acrylic elastomer sandwiched between two rigid annuli that sit
just barely in frame. Electrodes are CNT ink (2.5 mL used in the transfer
— that is what the `2.5mL` in the run names means, not a liquid volume).
Copper strips contact the electrodes and run roughly horizontally across
the frame. The whole assembly lies flat on **paper**, which is the
background. There is no liquid and no dish.

Frames are 1920×1080. A run is ~40 voltage steps to 10 kV, with **two
snapshots per step** (`pre-ramp` and `post-ramp`) about 57 s apart, so a
run takes ~40 minutes and yields ~81 rows.

The three runs are `P3_1_2.5mL_20260728`, `P3_2…`, `P3_3…`. Their CSVs
were renamed `data1.csv` / `data2.csv` / `data3.csv` so several could be
open in Excel at once — every reader in this repo handles that via
`sldea_edge.run_csv()`. Folder names do not need an `SLDEA_` prefix.

## What is already established — do not re-derive

Numbers below are from the three runs, 24 frames analysed per run.

**Ruled out — the camera.** Two snapshots at the *same* voltage, 57 s
apart, differ by a median of 1.5–1.7 gray levels against a sensor σ of
2.1–3.15 — about half a sigma — with pair-to-pair gains of 0.99–1.01. The
camera is steady. An earlier theory that `webcam.oneshot_rgb` reopening
the device per snapshot let auto-exposure re-converge each time is
**dead**; do not spend time on it.

**Ruled out — geometric drift.** Phase correlation reports 5–27 px
shifts, but undoing them changes the difference energy by ~1%. The shift
vectors have `dy ≈ 0` with erratic `dx`, which is the aperture problem
from those horizontal copper strips: translation along their own axis is
unobservable. `sldea_diag` now reports this as "the measured shift is not
a real translation" rather than as drift. Registration is not the fix.

**Established — a photometric mismatch between the baseline and the rest
of the run.** Every frame sits at gain 0.72–0.82 with a +8..+41 offset
against its own baseline. At 0.25 kV, where nothing has activated, the
mean ROI difference was 26.1 / 24.3 / 29.0 gray levels — a 10–17σ
pedestal — and it stayed there up the whole ramp. Fitting gain+offset on
matched quantiles takes that to **1.55 / 1.58 / 1.67**, below the sensor
noise, while the residual still grows with voltage (1.6 → 7.8 at 5.25 kV
→ 5.0 at 10 kV). So it removes the artifact, not the device.

**Established — the raw difference is not thresholdable.** `sep_intensity`
(Otsu separability, rescaled so one noise population reads 0) is **exactly
0.000 on all 72 frames** across all three runs. The photometry-corrected
map reads 0.17–0.51. Below diff threshold ~20 the "detected region" is
1,490,535 px², which is the entire ROI, and every frame comes back
`needs_review`.

Consequently `norm_bg` changed from a boolean to `0` = off, `1` = legacy
scalar border-band ratio, `2` = gain+offset fit on ROI quantiles, now the
default. A run whose `setup.txt` still says `1` reprocesses as tuned.

## The automated run

Extract the runs anywhere convenient; `.gitignore` already excludes
`P3_*/`, `SLDEA_*/`, `*.zip` and the diagnostic's outputs, so nothing here
can commit half a gigabyte by accident. **Do not commit run data.** The
diagnostic never writes to `data*.csv` or `setup.txt`.

For each of the three runs:

```
python sldea_diag.py "<path to run>"
```

That writes `sldea_diag.txt` / `.json` / `.png` / `_contact.png` beside the
run. `sldea_edge.BENCH_RUNS` maps `1`, `2`, `3` to the OneDrive paths, so
`python sldea_diag.py 1` works if the runs are still there.

**Read `sldea_diag_contact.png` for each run.** It draws the detected
outline on real frames across the ramp with kV, area, confidence and
review state in each title. You can open images — do it. Every conclusion
so far rests on statistics; nobody has yet checked whether the outline
lands in the right place. That check is the point of this handoff.

Then read the **A/B verdict** in the report: it runs `candidates()` under
both normalizations on the same frames and compares frames-needing-review
and median confidence. That is the test of whether switching to the
gain+offset fit changed what is actually *found*, as opposed to what the
residuals look like.

## What to decide, and what would settle it

1. **Does the affine fit eat device signal?** The fitted gain makes a
   smooth excursion that peaks at ~5 kV and recovers (P3_3: 0.77 → 0.60 →
   0.68), exactly where the device changes most. Either the scene really
   changes there, or the fit is tracking the DEA because it occupies a
   large share of the ROI. Evidence for "real": the same-voltage pair
   differences also peak at 5–5.75 kV, and pairs are two frames of one
   state, independent of any fit. **Settle it from the frames**: mask the
   annulus interior out of the fit region and see whether the gain
   excursion survives. If it does not, the fit is absorbing the device and
   the fit region needs restricting to the paper background.

2. **What happens at ~5 kV?** In all three runs, diff p99, the wrinkle
   ratio (1.85 / 2.76 / 2.62) and the pair differences all peak there and
   fall back, and phase-correlation response collapses to ~0.00 on exactly
   those frames. Something reproducible happens. Look at those frames.
   Wrinkle onset, pull-in, electrode delamination and a snap-through are
   all consistent with the numbers so far; the images should discriminate.

3. **Is the corrected map separable enough?** 0.17–0.51 is "there is
   structure", not "two clean populations". If the contact sheets show
   outlines still landing on the copper strips or the annulus rather than
   the active area, photometry was necessary but not sufficient, and the
   next candidates are: restrict the ROI to the annulus interior; segment
   the dense wrinkle map (`sldea_diag.texture_map`) instead of the
   intensity difference, since the lab defines the wrinkled region as the
   active area; or replace the 21×21 merge close, which makes area a step
   function of threshold (largest single-step jump 2.8×).

4. **Per-frame Otsu instability.** All three candidate tiers are multiples
   of one Otsu value that swings across a run, so a setting tuned on one
   frame is a different cut on the next. A threshold expressed in σ above
   the measured noise floor would transfer; a gray-level constant does
   not. `sldea_diag` already reports every threshold in σ.

## Guardrails

- Do not commit run data, the zip, or diagnostic outputs.
- Do not modify `data*.csv` or `setup.txt` in the runs. The diagnostic is
  read-only; `sldea_edge.write_back` and the tuner's Save are not, so if
  you use Edge Review's save path, work on a copy.
- Keep `norm_bg: 1` working. Runs tuned under the legacy scalar must
  reprocess identically.
- The bench PC is Windows with a conda Python; `deploy/Tune_SLDEA_Windows.bat`
  is the launcher and `/diag` runs the diagnostic. Two traps already hit
  and fixed there: `shift` moves `%0` so `%~dp0` must be banked first, and
  Python must never be invoked from inside a `for /f` (cmd mangles a
  quoted command carrying quoted arguments, which silently broke every
  path containing a space).

## Verification

```
python tests/test_sldea_edge.py      # 25
python tests/test_sldea_diag.py      # 15
python tests/test_sldea_tuner.py     # 8
python sldea_diag.py --selftest out.png
python sldea_tuner.py --selftest out.png
python run_tests.py
```

`run_tests.py` fails four suites when run as root (`test_arb_bin`,
`test_camera_controls`, `test_presets_path` make a directory read-only and
expect a write to fail, which root bypasses) and `test_scope_trace` needs
tkinter. Those are environmental and pre-existing.

## Related issues

- #157 — log kV/µA continuously at ≥1 Hz. The watchdog already samples
  current at 2 Hz and discards every sample.
- #158 — breakdown detection should trigger on a step change, not an
  absolute µA threshold. Depends on #157.
- #159 — `measured_kV` stops being recorded around snapshot 34. Leading
  hypothesis: the SLDEA path never sets the scope's vertical scale, so
  V_Out eventually leaves the screen and `measure()` returns the 9.9E37
  invalid-measurement sentinel for the rest of the ramp.
