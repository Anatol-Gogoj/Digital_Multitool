# Run sheet — 2026-08-08 (post-v1.2.0, pre-VM-move)

**What this is:** an ordered, tick-off view of the open work, split by
**where you have to be to do it**. **`PROJECT_HANDOFF.md` is the source
of truth** — this is a snapshot of its docket, not a second copy of it.
When they disagree, the handoff is right. Regenerate this file rather
than editing it alongside the handoff.

**State:** main green at the #293 merge, no open PRs, **v1.2.0 released
(pre-release; §M promotes it)**, manual 59 pages incl. Part II. Lab-PC
suite baseline **34/38** (four documented environmental failures:
`test_arb_bin`, `test_camera_controls`, `test_presets_path`,
`test_tk_fontfix` — a fifth is yours). A new machine establishes its own
baseline first.

---

## A. Anywhere — a VM or any fresh checkout (code + synthetic tests)

- [ ] `#200` connection takeover — build + tests now; SHIPS only after a
      bench verify (the bench-unverified-instrument-I/O rule).
- [ ] `#268` cross-run mean ± N·σ + electrode-family grouping. Stats
      policy lives inside it (run scatter vs the budget band; an
      interpolation rule for mismatched staircases). Synthetic tests in
      the VM; real-corpus validation needs the lab PC's data.
- [ ] `#199` wishlist — next picks from the tracker.
- [ ] Optional: trim the manual's Edge Review chapter by ~1,800 words
      (exact cut list in PR #293's thread; Anatol's call).
- [ ] `#264` decision PREP — draft the dated `SLDEA_HANDOFF.md` entry;
      the default flip itself waits for telemetry-era captures.
- [ ] First run on a new machine: `run_tests.py` to establish ITS
      environmental-failure baseline.

## B. Lab PC only (data- or display-bound)

- [ ] **The control round** (~15–20 min at the Edge Review GUI, operator)
      — the LAST desk-side measurement item. Targets in GUI-frame
      numbers: `DOT_P3_1_20260729` frame 29 · `P3_3_2.5mL_20260728`
      frames 29 and 66 · `P3_5_2.5mL_0729` frame 26, plus a SECOND trace
      on two of them (the repeat pairs — none exist corpus-wide). No
      ▶ Detect, no 💾 Save. Then the agent computes the §3b-5 gates and
      writes the SCORECARD/HANDOFF verdicts.
- [ ] **Before any data migration: back up the campaign corpus**
      (`…\Desktop\Digital Multitool\SLDEA_data\Upload 20260804\`).
      **P3_6's processed `data.csv` is the sole copy in existence.**
      robocopy needs `/R:2 /W:5` on this box.
- [ ] Fleet, analysis PC: `Tools → Update Software…` → footer reads
      `v1.2.0+…`.
- [ ] `#280` — the runner-flake evidence capture is armed
      (`test_failures/`); the flake is box-context (focus), so diagnosis
      happens where it fires.
- [ ] Any manual regeneration (capture = headed desktop + Edge + a
      hydrated run folder).

## C. Bench — no HV (delegable, ~25 min)

- [ ] **§M telemetry dry-run smoke** (`BENCH_TEST.md`) — gates trusting
      `telemetry.csv` AND **promotes v1.2.0 out of pre-release**.
- [ ] §N watchdog probe — its numbers unblock `#219` design and `#189`
      increment (1).
- [ ] Bench fleet: update to `v1.2.0+…` (currently two releases behind).
- [ ] `#206` installer idempotence re-run.

## D. Bench — HV (authorized operator)

- [ ] §O live telemetry verification.
- [ ] `#159` live verify — one ramp, watch the scope-monitor auto-fix
      dialog, `measured_kV` tracks the whole ramp with no blank tail.
- [ ] `#231` smoke — SG stays at 0 V through the warm-up window; blank
      electrode prompts.
- [ ] `#193` / `#194` exposure + fiducial-ring experiments (unblocks
      P3_7; may shrink `#198`).
- [ ] `SLDEA_20260729_104531` device autopsy — dead device vs HV not
      reaching the sample.
- [ ] `#215` — a second device's worth of calibrations, then close.

## Parked decisions (Anatol's)

- `#264` cadence-guard default (decide after the first telemetry-era
  captures exist).
- `#268` band semantics: run scatter vs the calibrated budget band.
- Repo split (PROJECT_HANDOFF open decision 2) · manual binaries → LFS ·
  `demos/` fate.
- `Ink concentration:` as the setup.txt key and the removed `'other'`
  electrode entry — accepted by merge 2026-08-08; revisit if either
  reads wrong on the first real run.
