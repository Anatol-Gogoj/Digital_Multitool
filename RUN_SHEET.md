# Run sheet — 2026-08-09 (analysis-VM era)

**What this is:** an ordered, tick-off view of the open work, split by
**where you have to be to do it**. **`PROJECT_HANDOFF.md` is the source
of truth** — this is a snapshot of its docket, not a second copy of it.
When they disagree, the handoff is right. Regenerate this file rather
than editing it alongside the handoff.

**State:** main at the #295 merge. **Three PRs open and unmerged:**
`#296` (test suite → 38/38 on Windows), `#297` (the `#268` band-semantics
decision record), `#298` (launcher guard + `.gitignore`). v1.2.0 released
(pre-release; §M promotes it), manual 59 pages incl. Part II. The remote
is now **`main` alone** — all 27 `claude/*` branches swept 2026-08-09,
with PR #221's draft preserved as tag `archive/run-sheet-221`.

**Suite baselines.** Analysis VM: **38/38** once `#296` merges (34/38
before it). Lab PC: **34/38** and unmeasured since — it will inherit the
fix. The old "four environmental failures" line is retired: they were six
failures from two causes, hidden by fail-fast. A new machine still
establishes its own baseline first.

**⚠ Corpus safety is protocol-only right now**, contrary to what the
handoff claimed before 2026-08-09 — the read-only share is not attached
and the corpus is reachable **writable** at `Z:\SLDEA_data`. The backup
item in §B is the first thing on this sheet for a reason.

---

## A. Anywhere — a VM or any fresh checkout (code + synthetic tests)

- [ ] `#268` cross-run aggregate — **now unblocked**; the stats policy is
      decided and written up in `#297`. Build: mean curve, SEM band,
      interpolated common grid with exact-key pooling on a toggle, capped
      at first breakdown, plus the three guardrails (no extrapolation, no
      interpolation across a breakdown, measured-vs-interpolated counts
      per level). Real-corpus validation runs **wherever the corpus is
      reachable read-only** — that is the VM today, but see the §B share
      decision, which can change it.
- [ ] **Before `#268`: document the plot-option seam.** A new option has
      to land in five places and four fail silently — including the one
      where `--from-spec` re-renders a *different* figure than the spec
      describes. `#268` adds two options and would hit two of them.
- [ ] `#268` electrode-family grouping — **blocked, no data.** The
      `Electrode family:` field it keys on is carried by **zero of 13**
      corpus runs.
- [ ] `#200` connection takeover — build + tests possible; SHIPS only
      after a bench verify. Decided (Anatol, 2026-08-09): **no forced
      remote abort of a live HV run**. Note two factual errors in the
      issue body: the cross-user-on-Windows premise (instrument control
      is Linux-gated) and the "related prior work" pointer.
- [ ] `#199` wishlist — evidence posted; the close-vs-trim call is
      deferred.
- [ ] `#49` — audit posted, five of six bullets dead. **Close once `#298`
      merges**, not before.
- [ ] Q4 middle path (agreed): make the suites continue past failures
      under a `K of M failed` header instead of stopping at the first.
      31 files, no product-behaviour change.
- [ ] Honest skip reporting for the display-gated suites — 45 of 52
      `test_sldea_edge_gui` cases are gated, and `test_app_launch` prints
      "4 tests passed" after running zero.
- [ ] Optional: trim the manual's Edge Review chapter by ~1,800 words
      (cut list in PR #293's thread; Anatol's call).
- [ ] First run on a new machine: `run_tests.py` to establish ITS
      baseline.

## B. Lab PC only (data- or display-bound)

- [ ] **BACK UP THE CAMPAIGN CORPUS — first, before anything else.**
      `…\Desktop\Digital Multitool\SLDEA_data\Upload 20260804\`.
      **P3_6's processed `data.csv` is the sole copy in existence**, and
      it is currently sitting on a read-write share. robocopy needs
      `/R:2 /W:5` on this box.
- [ ] **Then the share relayout** (decided: option c) — move `SLDEA_data`
      out of the read-write share's root, attach it as a genuine
      read-only share, repoint `SCPI_SLDEA_DIR`. Same pass: fix the two
      hard-coded corpus paths in the docs, and the plot window's default
      Export target, which writes beside the runs and will fail read-only.
- [ ] **The control round** (~15–20 min at the Edge Review GUI, operator)
      — the LAST desk-side measurement item. Targets in GUI-frame
      numbers: `DOT_P3_1_20260729` frame 29 · `P3_3_2.5mL_20260728`
      frames 29 and 66 · `P3_5_2.5mL_0729` frame 26, plus a SECOND trace
      on two of them (the repeat pairs — none exist corpus-wide). No
      ▶ Detect, no 💾 Save. Then the agent computes the §3b-5 gates and
      writes the SCORECARD/HANDOFF verdicts.
- [ ] `#215` — **re-bucketed here from bench-HV** (2026-08-09): the
      calibration dialog reads a baseline frame and nothing else, so no
      HV, no instruments. What is owed is a second device's worth of
      operator rounds, **driven in circle or twopoint mode** — a verified
      anchor contributes no operator-repeatability figure. Work on a
      COPY: the dialog writes into the run folder.
- [ ] Fleet, analysis PC: `Tools → Update Software…` → footer reads
      `v1.2.0+…`.
- [ ] `#280` — runner flake; box-context, so diagnosis happens where it
      fires. 0 of 4 on the VM, which is too few to mean anything.
- [ ] Any manual regeneration (capture = headed desktop + Edge + a
      hydrated run folder). **Needs ≥1150 px of screen height** — the
      capture script targets 1320×1000 and derives its height from the
      screen, so 1920×1080 silently yields 1320×990.

## C. Bench — no HV (delegable, ~25 min)

- [ ] **§M telemetry dry-run smoke** (`BENCH_TEST.md`) — gates trusting
      `telemetry.csv` AND **promotes v1.2.0 out of pre-release**. Also
      produces the first fine-cadence run, which is what the `#264`
      default decision is waiting on.
- [ ] §N watchdog probe — its numbers unblock `#219` design and `#189`
      increment (1).
- [ ] `#300` — the `#231` electrode/warm-up smoke (SG stays at 0 V
      through warm-up; blank electrode prompts). Previously booked here
      against PR #231, which is not an issue and so was invisible.
- [ ] `#299` — BK9174B serial exclusivity: apply `exclusive=True` and
      check a cold connect, a second instance failing cleanly, and
      recovery after `kill -9`.
- [ ] Bench fleet: update to `v1.2.0+…` (currently two releases behind).
- [ ] `#206` installer idempotence re-run.

## D. Bench — HV (authorized operator)

- [ ] §O live telemetry verification.
- [ ] `#159` live verify — one ramp, watch the scope-monitor auto-fix
      dialog, `measured_kV` tracks the whole ramp with no blank tail.
- [ ] **§P fiducial contrast ring** (`BENCH_TEST.md`) — `#193` / `#194`
      exposure + ring experiment as one procedure, ~2.5 h. Its P1/P2 steps
      are dry and delegable from §C; everything after them is HV. Unblocks
      P3_7, and its verdict sizes `#198`.
- [ ] `SLDEA_20260729_104531` device autopsy — dead device vs HV not
      reaching the sample.

## Parked decisions (Anatol's)

- `#264` cadence-guard default — **decide after §M**, when a
  fine-cadence run exists. Zero of 13 corpus runs would pass the check
  today, so a flip now restyles every historical figure. Note the
  persistence trap: a stored `cadence_guard: false` silently overrides an
  engine-side flip.
- `#199` close vs trim.
- Repo split (PROJECT_HANDOFF open decision 2) · manual binaries → LFS ·
  `demos/` fate.
- `vm-setup\provision-guest.ps1` stays OUT of the repo (decided
  2026-08-09 — it is a debugging/development aid). Its five known defects
  therefore stay unreviewed; the load-bearing one is that it never clears
  a stale `SCPI_SLDEA_DIR`, which is how this VM got into that state.
