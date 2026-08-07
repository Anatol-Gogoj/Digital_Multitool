# Run sheet — 2026-08-07 (v1.1.0, main at the #236 merge)

**What this is:** an ordered, tick-off view of the open work, split by
where you have to be to do it. **`PROJECT_HANDOFF.md` is the source of
truth** — this is a snapshot of its docket, not a second copy of it.
When they disagree, the handoff is right. Regenerate this file rather
than editing it alongside the handoff.

**State:** main green, **no open PRs**, suite **29/33** (four documented
environmental failures: `test_arb_bin`, `test_camera_controls`,
`test_presets_path`, `test_tk_fontfix` — a fifth is yours).

---

## A. Remote — nothing here is blocked

Everything in this section can be done at a desk with no hardware.

- [ ] **`#237` split the elapsed timer.** It keeps counting after detection
      finishes, so detection time — the number that tells an operator
      whether a run takes 1 minute or 15 — is destroyed as soon as it is
      produced. Freeze it at the end of detection, or add a second readout.
- [ ] **`#238` the Edge Review "How to use" panel.** Bottom-right button,
      short read on the actual loop. Must carry the three things that cost
      time on 2026-08-06: wash-out frames get **traced, not rejected**;
      `Accept` in the calibration dialog **stages** the anchor and **Save**
      writes it; a scale-only **re-anchor** skips detection entirely.
      **Decide first** where the text lives — the repo already regenerates a
      manual from `docs/manual-src/content.json`, so in-app prose is a
      second copy that will drift.
- [ ] **`#216` hover tooltips + button flow.** Re-requested unprompted by
      the operator after a long real session, so item 2 is confirmed rather
      than speculative. Note the `add_tooltip` helper lives in
      `ui_widgets.py`, which the planned repo split would put across the
      seam (open decision 2).
- [ ] **`#225` tabs have no horizontal scrollbar.** `ScrollableTab` pins
      inner width to the canvas, so adding a bar alone does nothing. One fix
      root-causes `#27` and is the same family as `#26` — three issues for
      one change.
- [ ] **`#197` tuner run picker.** `#226` fixed the Tune button's resolver;
      this is the remaining UI half. Real risk it removes: tuning the wrong
      run silently rewrites that run's `setup.txt`.
- [ ] **`#223` a GUI (or a button) for `sldea_plot.py`** — the only tool in
      the chain with no way in from the app.
- [ ] **`#215` stays open deliberately.** #236 delivered it and superseded
      it: measured σ ≈ 1.05 % means the circle mode misses the ±0.4 % SE
      budget at three rounds, so it shipped as a fallback behind
      verify-the-fit. What keeps it open is that its own numbers are chosen
      rather than measured — the 1 % spread gate, round count, wheel steps,
      spawn band — and the dialog has never been judged on **low-contrast
      ink**. Close it when a second device's calibrations exist.
- [ ] **`#229` liquid metal inverts the dark-disc assumption.** Designable
      now, but do not build it before there is a device to test against.
- [ ] **`#198` ML edge channel** — after `#194`'s verdict, which is bench-side.

**Campaign (data) side, also desk work:**

- [ ] **Decide what the control round is now for.** Its stated premise —
      "the optics moved between sessions" — was disproved on 2026-08-06:
      per-run anchoring absorbs optics movement entirely, and every
      absolute-area error in the corpus came from a manual calibration. Its
      remaining unique value is the machine-vs-operator boundary offset on
      ramp frames. Its operator-repeat leg has never had data, and `#215`'s
      three-round spread now produces that number for free.
- [ ] **Optional and cosmetic:** re-anchor `SLDEA_20260723_152205`
      (−3.38 % in area) and `SLDEA_20260723_233451` (+2.44 %). Both are
      retired from measurement and gate nothing; correcting them rewrites
      the breakdown fixture for no measurement gain. Offsets are recorded.

---

## B. Bench, **no HV** — hand this to a colleague

~25 minutes together, no HV training, and between them they unblock
trusting `telemetry.csv`, promoting v1.1.0 out of pre-release, and `#189`
increment (1). Full steps in `BENCH_TEST.md`.

- [ ] **§M telemetry dry-run smoke.** A dry run never commands the SG.
      **The single answer most wanted: does `run.log` say `SLOW DISK`** —
      the bench output dir is a network share and that is the one behaviour
      desk testing cannot reproduce.
- [ ] **§N watchdog probe.** `bench/test_sldea_watchdog_probe.py --ich 3
      --vch 2`, about a minute, changes nothing on the scope. Section A sets
      the peak-based trip level; section C decides how much driver work
      `#189` increment (3) needs.
- [ ] **Send back** `run.log`, `data.csv`, `telemetry.csv`, `setup.txt` and
      the probe's two files.
- [ ] **Smoke the two `#231` changes** on any short run: `setup.txt` carries
      `Compliant electrode:`; the folder has a `warmup` frame at t=0 **and**
      a `baseline` at t=2; a blank Electrode box prompts before starting;
      and — the one that matters — **the SG stays at 0 V through the
      warm-up window**.
- [ ] **Judge the new calibration dialog on real ink.** It has been driven
      hard by the operator, but only on P3_2's comparatively clean disc, and
      nobody has seen it rendered in colour on the bench screen. Two things
      to watch: whether *"straddle the edge — half the stroke on the disc,
      half on the paper"* reads unambiguously on a low-contrast disc, and
      whether the contrast-stretched view helps or misleads.
- [ ] **`#193` camera exposure** — try Stabilize first; C920 / ELP /
      machine-vision if the firmware wins. Unblocks P3_7 and a
      clean-provenance CB re-shoot.
- [ ] **`#194` fiducial contrast ring** (may shrink `#198`'s niche).
- [ ] **`#206` deploy-script dedup / installer idempotence re-run.**
- [ ] **Physically test the 104531 device** — dead device, or HV not
      reaching the sample.
- [ ] **Pull v1.1.0 onto the bench and analysis PCs** and check the footer
      reads `v1.1.0+…`. The fleet is still on v1.0.0+4f5f213.

---

## C. Bench, **with HV** — trained and authorized operator only

- [ ] **§O live-run verification → closes `#159`.** One live ramp: the
      pre-run monitor dialog fires, and `measured_kV` tracks `nominal_kV`
      for the **whole** ramp with no blank tail. Nobody recentres the scope
      by hand — `_sldea_check_monitors` offers "Fix it automatically" and
      programs both monitor channels itself.
- [ ] **`#189` increments (1) then (3)+(4)**: switch the watchdog read
      MEAN → MAXIMUM/PK2PK (new SCPI token, bench-first per convention),
      then trigger-armed single-shot capture of I_Out plus post-trip
      `get_waveform()` forensics. Run §N **first** — it measures the three
      numbers these are blocked on.
- [ ] **P3_7 capture** once `#193`/`#194` give it usable contrast. Its
      automatic disc fit **refuses**, so it is also the only run that
      exercises the calibration dialog's refuse→measure-by-hand fallback —
      the one path in that flow nobody has driven.

---

## What just landed (2026-08-06/07) — main green, no open PRs

- **#233** campaign docket · **#234** telemetry wording (`#224`) ·
  **#235** trace labels always carry a machine candidate (`#162`'s unmet
  criterion) · **#236** the scale-calibration rework.
- **#236 in one line:** the machine measures the px→mm scale and the
  operator verifies it, because thirteen logged hand calibrations put
  operator precision at σ ≈ 1.0–1.1 % against an automatic fit's 0.40 %
  residual. Adds a scale-only **re-anchor** that corrects a run's scale
  without re-reviewing it.
- **Every desk-side review is complete.** Both 07-23 breakdown runs, P3_2,
  the P3_6 holdout frame, and both 08-05 runs folded into `SCORECARD.md`.
- **P3_2's scale is corrected and verified** — resting 192.18 → 201.062 mm²,
  with its px column, `notes` column and A/A₀-from-px byte-identical.
- **Two of my own earlier claims were corrected**: the resting-area misses
  were manual calibrations, not moved optics; and the audit p95 is
  `np.percentile`-linear, not nearest-rank.
