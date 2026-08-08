# Digital Multitool — agent context

Tk bench-control app for SCPI lab instruments plus the SLDEA test and
analysis suite, supporting DEA actuator research. Two halves: instrument
infrastructure (per-instrument GUI tabs, drivers, presets, data logging,
webcam capture, battery post-processing) and the SLDEA measurement chain
(capture tab → Edge Review / tuner / diagnostic operating on run folders).

This file is the durable context only. **Current state, open decisions and
campaign status live in `PROJECT_HANDOFF.md`** — update that file at
milestones, not this one.

## Doc map — read the one you need

| Doc | What it answers |
|---|---|
| `PROJECT_HANDOFF.md` | where things stand right now; open decisions |
| `RUN_SHEET.md` | the same docket as a tick-off list, split remote / bench-no-HV / bench-HV. A dated snapshot — regenerate it, never maintain it alongside the handoff |
| `README.md` | setup, transports, every bench-verified instrument quirk |
| `SLDEA_HANDOFF.md` | measurement-chain decision log (append-only, dated) |
| `SLDEA_MEASUREMENT.md` | the error budget — what uncertainty to quote and why |
| `docs/manual-src/README.md` | user-manual pipeline + the release checklist |
| `BENCH_TEST.md` | manual hardware-in-the-loop checklist — §A–§L signal gen (historical), **§M/§N/§O the current SLDEA telemetry + watchdog gate** |
| `deploy/BENCH_PC_NOTES.md` | bench-PC launch chain and its traps |

## Conventions that override defaults

- **Changelogs, release notes and PR bodies start with a dumb TL;DR** —
  two or three plain sentences a tired labmate can skim, before any wordy
  sections. Same for new `SLDEA_HANDOFF.md` entries.
- **Never ship bench-unverified instrument I/O.** New SCPI paths need a
  bench session first; until then they are documented follow-ups, not
  code. Bench-verified claims cite their verification date.
- **Releases:** bump `version.py`, re-run the manual pipeline, commit BOTH
  regenerated manuals, tag, GitHub release with the PDF attached. The
  updater clones main HEAD — it never reads tags or the releases API, so
  a pre-release still reaches the fleet; the version+hash stamp only
  invalidates each launcher's cache.
- **Run data never enters the repo.** `.gitignore` blocks run folders and
  their outputs; a PR that introduces a new capture artifact type extends
  `.gitignore` in the same PR.
- **`setup.txt` is a lab-notebook document, not a config file — it stays
  plain text** (decision 2026-08-08, dated entry in `SLDEA_HANDOFF.md`).
  New machine-read fields keep the `Key: value` convention through
  `se.load_settings`/`save_settings`; if typed or nested structure is
  ever needed, add a sidecar file beside the txt — never convert it.
- **SLDEA measurement-chain behavior changes** land with a dated
  observation → decision entry in `SLDEA_HANDOFF.md`.
- **Breakdown semantics (since 2026-08-05):** only current-confirmed
  events (sustained deviation from the run's median baseline, or a
  terminal event) rename frames `*_BREAKDOWN`; area collapse alone is an
  advisory. Do not "simplify" this back to area- or absolute-µA-triggered
  renaming — that false-branded 35 healthy frames once.
- **Process:** changes land via PR with the TL;DR-first body; Anatol
  merges. Anything touching HV-safety paths (SLDEA runner, watchdog,
  instrument output switching) gets an adversarial review pass before
  the PR opens.
- **Plots:** Paul Tol bright palette family, colorblind-safe, validated.

## Timeless traps

- Closing the app does **not** switch off the BK 9174B output, and a live
  SLDEA run must end via ■ Abort (best-effort ramp on window close only).
- The 4055B's USB is hard-capped at 52 bytes per command and a long
  transfer wedges the firmware — arbs go via LAN or flash drive
  (README §quirks has the full story; the probe that proves it lives in
  `bench/archive/`).
- Windows is view/edit-only for instruments; Battery Data and Webcam are
  fully functional there. Instrument control is Linux-bench-only.
- Old `active_area_mm2` values written before 2026-07-28 carry a 2.3–2.7×
  scale bug — reprocess, never mix.
- **The px→mm scale is the machine's job, not the operator's** (measured
  2026-08-06). Hand calibration has σ ≈ 1.0–1.1 % of diameter whatever the
  method, because the disc edge is a ~60 px gradient rather than a line;
  `baseline_disc` fits it to a 0.03–0.80 % residual. Every absolute-area
  error in the corpus came from a manual anchor, and every run that used the
  automatic fit lands on π·8² exactly. Edge Review therefore defaults to
  verify-the-fit; hand measurement is the fallback for when the fit refuses.
- **Calibration methods are stored as NAMES (`verify`/`circle`/`twopoint`),
  never letters.** The UI letters were swapped 2026-08-06, so a legacy stored
  letter means the pre-swap method (`A`=circle, `B`=twopoint, `C`=verify).
  Read them through `se.cal_mode_read`; live data contains both vocabularies.
- **An auto-verified anchor has no independent cross-check, and the code says
  so rather than faking one.** Declaring the fitted disc to be 16 mm makes
  the resting area π·8² by construction, so a mask-area test on it can only
  pass. Do not add a cross-check that cannot fail.
