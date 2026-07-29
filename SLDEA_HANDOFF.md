# SLDEA detection — handoff

The previous handoff asked the next agent to read the run frames, because
every conclusion up to that point rested on statistics and nobody had
checked whether the detected outline lands in the right place. **That has
now been done** (2026-07-28). It does not land in the right place, and the
reason turned out to explain most of the earlier statistics.

Read this file, then `sldea_edge.py` (`candidates`, `prepared_diff`,
`photometric_fit`, `baseline_disc`, `mm_per_px`) and `sldea_diag.py`.

All of this is on `main` as of `331b957` (PR #156, merged 2026-07-28). The
branch it came from, `claude/local-tuning-win11-qsqpqo`, has been deleted —
start from `main`.

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

**The contrast asymmetry that drives everything below.** Measured on all
three baselines: the resting disc sits only **10–20 gray levels** below
the paper, while the foil strips span **120–255** and occupy **~11–13% of
the frame**. The device is the lowest-contrast object in the scene and the
electrodes are by far the highest-variance one. Any global intensity
threshold finds foil first — this is not a tuning problem.

### Where the data is

All three runs are on this machine at

```
C:\Users\anato\OneDrive - University of Connecticut\Recordings\SLDEA_data\
    P3_1_2.5mL_20260728\   P3_2_2.5mL_20260728\   P3_3_2.5mL_20260728\
```

each with `data.csv`, `setup.txt` and `frames/` (81 frames + baseline).
`sldea_edge.BENCH_RUNS` maps `1`, `2`, `3` to exactly those paths, so
`python sldea_diag.py 1` works. None of the three has a saved edge-settings
section in `setup.txt`, so **all three run on `DEFAULT_SETTINGS`** —
including `electrode_lum: 220` and `norm_bg: 2`.

The CSVs are named `data.csv`, not `data1/2/3.csv` as an earlier version of
this doc said; `sldea_edge.run_csv()` accepts either.

## Established WITHOUT frames (previous session) — still valid

Numbers from the three runs, 24 frames analysed per run. Do not re-derive.

**Ruled out — the camera.** Two snapshots at the *same* voltage, 57 s
apart, differ by a median of 1.5–1.7 gray levels against a sensor σ of
2.1–3.15 — about half a sigma — with pair-to-pair gains of 0.99–1.01. An
earlier theory that `webcam.oneshot_rgb` reopening the device per snapshot
let auto-exposure re-converge is **dead**.

**Ruled out — geometric drift.** Phase correlation reports 5–27 px shifts,
but undoing them changes the difference energy by ~1%. The shift vectors
have `dy ≈ 0` with erratic `dx` — the aperture problem from those
horizontal copper strips. Registration is not the fix.

**Established — a photometric mismatch between the baseline and the rest
of the run.** Every frame sits at gain 0.72–0.82 with a +8..+41 offset
against its own baseline. At 0.25 kV the mean ROI difference was
26.1 / 24.3 / 29.0 gray levels — a 10–17σ pedestal. A gain+offset fit on
matched quantiles takes that to 1.55 / 1.58 / 1.67, below sensor noise,
while the residual still grows with voltage. Hence `norm_bg`: `0` = off,
`1` = legacy scalar border-band ratio, `2` = gain+offset fit, now default.

**Established — the raw difference is not thresholdable.** `sep_intensity`
is **exactly 0.000 on all 72 frames**. The reason is now known: see below.

## Established WITH frames (2026-07-28) — this session

**The detector is locking onto the electrodes, not the device.** Across
runs 1 and 2, **83–100% of the detected area lies on the foil strips**. In
run 1 at 5.25 kV all three candidate tiers outline foil — `diff-hi` and
`diff-otsu` on the left strip (x 237..453), `diff-lo` on the right
(x 1281..1641) — while the disc, centred near x≈950, is visibly wrinkling
in the same frame and gets no detection at all. This is directly visible in
`sldea_diag_contact.png` for every run.

This is why `sep_intensity` was 0.000 everywhere. It was never a subtle
statistical failure; the map being scored is dominated by the wrong object.

**Root cause — electrode suppression covers a minority of the electrode.**
`prepared_diff` masks pixels `>= electrode_lum` (220) in the baseline,
dilated 7×7. Measured against a texture-derived foil footprint:

| run | foil footprint | masked (dilated) | **coverage** |
|-----|---------------|------------------|--------------|
| 1   | 11.18%        | 3.75%            | **33.6%**    |
| 3   | 11.37%        | 4.76%            | **41.8%**    |

The median foil pixel is **173** (p10 144, p90 239). A brightness threshold
catches the specular streaks and leaves 58–66% of the crinkled strip — the
dark creases — fully exposed to the differencing. Those creases are exactly
the pixels that swing when the foil shifts. Raising `electrode_lum` makes
this worse; lowering it far enough to catch the creases would also swallow
the paper.

**Q1 — the affine fit does absorb the device, but only in run 3.** Refit
with the fit region restricted to paper only (ROI minus disc minus foil):

| run | gain, full ROI            | gain, paper only          |
|-----|---------------------------|---------------------------|
| 3   | 0.77 → **0.55** @5.25 kV → 0.65 | 0.78 → 0.85 → 0.81 — flat |
| 2   | 0.81 → 0.70 @4.75 kV → 0.72 | 0.78 → 0.67 → 0.78 — **survives** |
| 1   | 0.79 → 0.72, monotonic     | 0.80 → ~1.00 @4.75 → 0.90 |

Run 3's excursion is an artifact of the device sitting inside its own fit
region — the previous handoff's decision rule says restrict the fit to the
paper background, and that is confirmed. Run 2's excursion **survives** the
restriction, so there something in the scene really does change. These are
two different causes that the earlier statistics could not separate; do not
treat the ~5 kV gain dip as one phenomenon.

**Q2 — the ~5 kV event is real.** At exactly 5.25–5.75 kV the detection
jumps *off* the foil and onto the disc (run 2: 94% → 8% of detected area on
foil) and separability measured **inside the disc alone** spikes from 0.000
to **0.40** (run 2) and **0.27** (run 3). It is the one moment the device
changes enough to outrank the electrodes. Wrinkle onset / pull-in /
snap-through remain the candidates; this is not a photometric artifact.

**Q3 — answered: photometry was necessary but not sufficient.** See the
localization numbers above. The next step is not a better threshold on the
intensity difference.

**NEW BUG — `baseline_disc` is not tracing the disc, and it silently
corrupts the px→mm scale.** On all three baselines it merges the disc, both
foil strips and a slab of surround into one blob:

- `circ = 0.32` (a disc would approach 1.0)
- contour bbox `x 144..1773` — 85% of the frame width
- `diam_px = 896` (run 1), 951 (run 2), 897 (run 3)
- **`conf = 0.93`** — nothing flags it

`mm_per_px` divides the nominal 16 mm by that `diam_px`, so every
`active_area_mm2` written for these runs is wrong. The 21×21 merge close in
`_region_candidate` is the mechanism: it bridges the disc to the strips.
Note `baseline_disc` *does* neutralize pixels ≥ `electrode_lum` before its
Otsu (line ~626) — that neutralization has the same 34–42% coverage problem
documented above, so the strips survive it.

**Magnitude not established.** Three measurement approaches gave 1.36×,
1.46× and 2.98× on diameter. The disc/paper contrast is too low (10–20
gray levels) for quick threshold or half-height-profile methods — they lock
onto the strip-end shadows instead. Best estimate ~1.4× on diameter (~2× on
area), but **this needs a real measurement, not the above.** Do not quote a
correction factor until it is measured properly.

### Reproducing the foil footprint

Brightness cannot define the foil (that is the thing under test). Texture
can — the crinkled foil is high local-Laplacian energy while both paper and
the resting disc are smooth:

```python
tex = sldea_diag.texture_map(base)
m = (tex >= np.percentile(tex, 92)).astype(np.uint8)
m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((41, 41), np.uint8))
m = cv2.morphologyEx(m, cv2.MORPH_OPEN,  np.ones((15, 15), np.uint8))
# keep connected components larger than 0.5% of the frame, then dilate 15x15
```

This cleanly isolates the two strips on all three baselines — verified by
eye against the frames, which is the only reason to trust it.

## Tasks, in priority order

1. **Measure the true resting-disc diameter properly, then fix
   `baseline_disc`.** Highest priority: it is the only finding that
   silently corrupts recorded physical measurements, and it reports high
   confidence while doing so. The merge close bridging disc to strips is
   the mechanism. At minimum `baseline_disc` must refuse to return a
   detection with `circ = 0.32` as a disc — a solidity check alone did not
   catch this. Whatever the fix, it must also stop reporting `conf` 0.93 on
   a region spanning 85% of the frame.

2. **Restrict the photometric fit region to the paper background.**
   Confirmed correct by Q1. The fit region should be ROI minus disc minus
   foil. Note this makes the fit depend on a disc estimate, which depends
   on task 1 — sequence them.

3. **Segment on texture, not intensity difference.** The lab defines the
   wrinkled region as the active area, and texture is the one channel where
   the disc outranks the foil rather than losing to it by an order of
   magnitude. `sldea_diag.texture_map` already exists and the wrinkle ratio
   already feeds `conf`. This is the change most likely to actually fix
   detection; tasks 1 and 2 make it measurable.

4. **Then revisit electrode suppression.** With texture segmentation the
   brightness mask may become unnecessary. If it is kept, it must cover the
   whole strip footprint, not its highlights — a texture-derived mask is
   the obvious candidate, and it is already needed for task 2.

5. **Per-frame Otsu instability — still open, untouched this session.** All
   three candidate tiers are multiples of one Otsu value that swings across
   a run, so a setting tuned on one frame is a different cut on the next. A
   threshold expressed in σ above the measured noise floor would transfer;
   a gray-level constant does not. `sldea_diag` already reports every
   threshold in σ.

## Repo state you are inheriting

**Git history was cleaned on 2026-07-28.** A previous session had committed
the run data — `b7be7b6 "add 3 bunches of real frames"`, a 555,590,120-byte
zip — despite `.gitignore` listing `*.zip`; it had been force-added, and
`.gitignore` does not apply to tracked files. That commit and its merge
were local-only, never pushed, and contained **nothing but the zip**. Both
were dropped (`git reset --hard origin/...`, reflog expired, `git gc`):
`.git` went **532 MB → 1.1 MB**. PR #156 was never affected. The zip itself
is intact in the OneDrive folder above.

If you extract runs into the working directory, `.gitignore` already
excludes `P3_*/`, `SLDEA_*/`, `*.zip` and the diagnostic's outputs — but
that only protects you if nobody uses `git add -f`.

**A test that encoded the absence of the data was fixed** (already on
`main`): `tests/test_sldea_edge.py`. The test
`test_bench_shortcuts_resolve_and_stay_inert_elsewhere` asserted the bench
paths do not exist on this machine — true when written, false now that the
runs are here, so it failed for the wrong reason. It now asserts what its
docstring promises: a shortcut resolves to its own directory or to nothing,
never to a different run. 25/25 pass.

## How to run the loop

```
python sldea_diag.py "<path to run>"          # or: python sldea_diag.py 1
```

Writes `sldea_diag.txt` / `.json` / `.png` / `_contact.png` beside the run.
**Use `--out DIR` to write them somewhere else** — the runs already contain
diagnostic outputs from earlier sessions and the default path overwrites
them.

**Read `sldea_diag_contact.png`.** It draws the detected outline on real
frames across the ramp with kV, area, confidence and review state in each
title. You can open images directly — do it. Every conclusion in the
"without frames" section above rests on statistics, and the frames
overturned the interpretation of several of them.

The report's **A/B verdict** runs `candidates()` under both normalizations
on the same frames and compares frames-needing-review and median
confidence — the test of whether a normalization change altered what is
actually *found*, as opposed to what the residuals look like.

## Guardrails

- Do not commit run data, the zip, or diagnostic outputs. Never `git add -f`
  in this repo.
- Do not modify `data*.csv` or `setup.txt` in the runs. The diagnostic is
  read-only; `sldea_edge.write_back` and the tuner's Save are not, so if you
  use Edge Review's save path, work on a copy.
- Keep `norm_bg: 1` working. Runs tuned under the legacy scalar must
  reprocess identically. Task 2 changes what `norm_bg: 2` fits on, so it
  needs a regression check against this.
- The bench PC is Windows with a conda Python; `deploy/Tune_SLDEA_Windows.bat`
  is the launcher and `/diag` runs the diagnostic. Two traps already hit and
  fixed there: `shift` moves `%0` so `%~dp0` must be banked first, and
  Python must never be invoked from inside a `for /f` (cmd mangles a quoted
  command carrying quoted arguments, which silently broke every path
  containing a space).

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

Beware of tests that encode "the bench data is not on this machine" — one
already did (see Repo state). On a machine holding the runs, that class of
assumption fails for the wrong reason.

## Related issues

- #157 — log kV/µA continuously at ≥1 Hz. The watchdog already samples
  current at 2 Hz and discards every sample.
- #158 — breakdown detection should trigger on a step change, not an
  absolute µA threshold. Depends on #157.
- #159 — `measured_kV` stops being recorded around snapshot 34. Leading
  hypothesis: the SLDEA path never sets the scope's vertical scale, so
  V_Out eventually leaves the screen and `measure()` returns the 9.9E37
  invalid-measurement sentinel for the rest of the ramp.
