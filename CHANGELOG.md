# Changelog

Every release opens with a plain TL;DR, then the details by area. Versions are
tags on `main`; the GitHub release of each version carries the matching user
manual PDF. Older releases are summarized here and link to their full notes.
The measurement-chain decision log (`SLDEA_DECISIONS.md`) is the record of
*why*; this file is the record of *what shipped*.

## v1.4.0 (2026-10-05)

**TL;DR:** The area measurement is fixed. Until now the resting area was a
circle fit and every expanded area was an ellipse fit, and the two disagreed by
up to 7 percent on the same photo, so every strain curve carried a run-specific
offset and a step at low voltage. Both are now measured from the same edge rays.
Saved runs reviewed under the old method must go through Edge Review again, and
the plot refuses them until they have. Edge Review also tells a new student up
front whether a run can be measured, the hand-calibration dialog can no longer
accept a guess, and a one-page quickstart takes a student from the bench to a
plot.

**Re-review before plotting.** Old and new areas are not comparable. Opening a
saved run in Edge Review and pressing Save stamps the new method into
`setup.txt` and empties any unreviewed row that still holds an old automatic
area; until then the plot leaves that run off the area axes. The only reviewed
campaign run on the share at release time, DOT_P3_1, still needs this.

### Measurement chain

- **One estimator for A and A0** (#344). A tracked frame's area is the resting
  area times the ratio of summed squared edge radii over the rays measured on
  both the baseline and the frame. No shape model in the number, no
  extrapolation across the sectors hidden by the leads. Quiet frames at 0 to
  0.5 kV read 1.000 within 0.1 to 0.3 percent per run; the step at the
  resting hand-over (3.8 to 8.8 strain points per run before) is gone; tracked
  rows agree with an independent fit-free edge measurement within 1 point up
  to 4 kV. Low-voltage frames are now measured instead of written as exactly
  the resting area.
- The spread figure on a tracked frame is a block bootstrap over angular
  sectors; nothing calls it a confidence interval any more.
- A reading from a one-sided set of rays (one-sidedness above 0.6) or one
  where the trim dropped more than a fifth of the rays stays on the card for
  the reviewer but never auto-accepts (#344). On the 899-frame review corpus
  that routes 21 rows to a human that auto-accepted before, and no accepted
  area moved.
- **Tracker range** (#345). The boundary tracker now searches out to 1.70 and
  accepts fits up to 1.75 times the resting radius (it stopped at 1.38 and
  1.30, written when 1.25x area was thought to be a full ramp), so the flat
  shoulder frames before buckling get a real edge. A clean tracked frame is no
  longer sent to review only because its landing partner found a patch.
- Every Save stamps the estimator version, the baseline's provenance, the
  tracker window limits and the OpenCV and numpy versions into the run's
  `setup.txt` edge-settings block, and the plot's tidy CSV carries them. Edge
  Review warns in one line when it runs off the pinned OpenCV.
- Pairs are one landing, not one kV, on up/down and repeat runs (#333).

### Edge Review

- **Run health on open** (#346). Picking a run shows a strip that says, in
  plain sentences, whether the run can be measured and what went wrong at
  capture: a blank or overexposed baseline, a refused disc fit, missing voltage
  or current readings, a run that ended early, a watchdog stop, missing frames,
  off-screen telemetry. On a run marked STOP, the auto-process no longer
  presses Detect for you.
- Save keeps the notes the runner wrote at capture (WATCHDOG, V_Out off-screen)
  instead of overwriting them (#346).
- A watchdog trip row counts as a confirmed breakdown unless the reading that
  tripped it was the scope's off-screen placeholder; streaks in
  `telemetry.csv` become advisory notes that never rename a frame (#346).
- **Hand-calibration guardrails** (#347). The hand modes show a
  contrast-stretched frame; a round whose circle was never moved is refused;
  a frame with no visible picture opens on a plain notice with Cancel as the
  default; rounds more than 5 percent apart are refused outright. The
  2026-10-01 anchor, three untouched circles 23 percent apart, cannot happen
  again.

### Plot

- The strain-mode uncertainty band is plus or minus 2 percent of the area
  mapped to strain points (plus or minus 1 percent on traced levels). It was
  drawn as a percent of the strain value, so it had no width at rest and was
  2.6 to 10.5 times too narrow elsewhere (#343). `--strain-pct` now works on
  the command line.
- The normalized panel can be drawn as areal strain percent, not only A/A0
  (#330).
- Runs reviewed under the old estimator are refused from area axes with a
  message that says to re-review them; `--allow-old-estimator` keeps them,
  named in the caption (#344).

### Live capture interlocks

- Run refuses to start beside a Webcam-tab sweep on its channel, and a sweep
  never writes a LIVE run's channel (#334).
- Fire and the Waveform Editor's upload obey the LIVE channel lock (#335).
- A LIVE run locks the scope channels it reads and the settings they share
  (#337); the scope's Reconnect asks first during a LIVE run (#339); Reconnect
  no longer drops the instrument when another connect is running (#336).
- Restart now and Update Software refuse while a run is going; a mid-run
  restart had left the Trek energized (#338).
- Bench-side probe for the monitor channels' coupling and on/off state (#341).
  The bench verification of these interlocks (BENCH_TEST sections M, N and O)
  is still owed.

### Documentation

- `docs/SLDEA_QUICKSTART.md`: one page from an unpowered rig to an exported
  plot, with a box of questions the lab must answer before a new student uses
  it (#342).
- Session state moved out of the repo: `PROJECT_HANDOFF.md` and
  `RUN_SHEET.md` are frozen history as of 2026-08-12, and the decision log is
  renamed from `SLDEA_HANDOFF.md` to `SLDEA_DECISIONS.md` (#350).
- The Invisicon pair is the spray: duplicate entries dropped (#329).

### Tests and platforms

- Windows test fixes: the EasyWave temp path and the plot-window resize race
  (#331); the fontconfig fix is gated on the platform it acts on (#332).
- The test suite grew from 39 to 46 suites since v1.3.0, with new cases
  across the estimator, tracker, run health, calibration and plot changes.

### Not in this release (bench-gated)

- #348, the pre-flight image gate (refuse a flat picture before HV, stop a run
  on a flat or missing baseline). Waits for BENCH_TEST section S.
- #340, Restart now through the desktop launcher. Waits for bench checks A and
  B in `deploy/BENCH_PC_NOTES.md`.

## v1.3.0 (2026-08-12), the analysis release

Runs from several folders can go on one figure and be averaged by group with
an SEM band; Edge Review no longer discards its own controls when the window
is small; the campaign corpus is consolidated under one parent and every run
records which electrode it used. Promoted straight to Latest, superseding the
v1.2.0 pre-release. Full notes:
https://github.com/Anatol-Gogoj/Digital_Multitool/releases/tag/v1.3.0

## v1.2.0 (2026-08-08, pre-release), the analysis cockpit release

The plot tool became a window on the SLDEA tab: pick runs, toggle what is
drawn, log axes, export PNG plus CSV plus a re-renderable figspec, and
double-click a point to open that frame in Edge Review. Edge Review got a
How-to panel, an unmistakable primary button, tooltips and an honest detection
clock. Pre-release pending the telemetry bench smoke. Full notes:
https://github.com/Anatol-Gogoj/Digital_Multitool/releases/tag/v1.2.0

## v1.1.0 (2026-08-05, pre-release)

A live SLDEA run records its current continuously to `telemetry.csv`; the
cross-run plot tool and the Edge Review scale gate arrived, with 28 audit
fixes. Pre-release because the telemetry sidecar had only been tested at a
desk. Full notes:
https://github.com/Anatol-Gogoj/Digital_Multitool/releases/tag/v1.1.0

## v1.0.0 (2026-08-03)

First stable release: LCR meter, oscilloscope, signal generator, DC supply and
DMM control on the Linux bench, multi-source CSV logging, battery data
processing, webcam capture, and the SLDEA test and Edge Review chain. Full
notes: https://github.com/Anatol-Gogoj/Digital_Multitool/releases/tag/v1.0.0
