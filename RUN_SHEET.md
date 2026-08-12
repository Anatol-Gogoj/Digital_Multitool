# Run sheet — 2026-08-12 (post plot-window batch)

**What this is:** an ordered, tick-off view of the open work, split by
**where you have to be to do it**. **`PROJECT_HANDOFF.md` is the source
of truth** — this is a snapshot of its docket, not a second copy of it.
When they disagree, the handoff is right. Regenerate this file rather
than editing it alongside the handoff.

**State:** main green at `011c976` (#324), **no open PRs**. Everything
`GATES.md` listed as blocked has merged: the eleven gated PRs on 08-09
(#296–#309) and the plot-window batch on 08-10 (#310, #317–#324). The
remote is **`main` alone**; PR #221's draft is preserved as tag
`archive/run-sheet-221`.

**Suite baseline: 39/39 SUITES on the analysis VM** (2026-08-12). This
is a new vocabulary — #303/#306 changed the reporting, so the old
"34/38" and "38/38" per-test lines do not compare to it. Eight tests
skip honestly: 4 `test_app_launch` + 2 `test_tk_fontfix` are Linux-only
gates, and 2 `test_sldea_plot_gui` scroll cases need more screen height
than this desktop has. **The lab PC has not been measured since #296 and
#303 landed** — it will inherit both, but its number is still unknown.

**Corpus: consolidated and backed up, still not protected.** All 15 runs
now sit under one parent, `SLDEA_data\runs\` (2026-08-12, a same-volume
rename verified by file count, byte total and hashes). The backup is
confirmed archived out of the shared directory — the irreplaceable-data
risk is closed. The *access* risk is not: the read-only share is still
not attached and the live corpus is still reachable **writable** at
`Z:\SLDEA_data` (verified this date). The share relayout in §B closes
that half.

**⚠ `SCPI_SLDEA_DIR` MUST BECOME `…\SLDEA_data\runs` ON EVERY MACHINE.**
Both obvious values fail SILENTLY after the relayout — measured this
date, not reasoned about. `…\Upload 20260804`, which is the current
lab-PC value, descends into `_baselines\` and serves **2 baseline
COPIES** as though they were runs. `…\SLDEA_data` stops at the root and
serves **1** — the scratch playground — because it holds a `data.csv`
directly. Neither errors; both just hand you the wrong runs.

**⚠ Screen height: the ≥1150 px figure is stale for the tests.**
Measured at 1920×1200 on 2026-08-12 — the Draw column needs 1186 px and
gets 1181, missing by five, because `#268` added two Draw rows after
that threshold was written. Those two cases want **≥ ~1205 px** of
screen. Manual capture is a different, lower bar (≥1090) and 1200
clears it.

---

## A. Anywhere — a VM or any fresh checkout (code + synthetic tests)

- [x] **Close the nine shipped-but-open issues** — `#307` `#311` `#312`
      `#313` `#314` `#315` `#316` `#323` `#49`. DONE 2026-08-12, each
      verified against `main` first; the evidence table is in
      `PROJECT_HANDOFF.md` under "Roster changes 2026-08-09 →
      2026-08-12".
- [ ] **`#268` electrode-family grouping — UNBLOCKED 2026-08-12**, by
      Anatol's decision to backfill the fields by hand. Two halves, in
      order:
      **(a) the backfill itself** (lab PC / wherever the corpus is —
      see §B), and **(b) the code**, which does not exist: nothing in
      `sldea_plot.py` or `sldea_plot_gui.py` reads the electrode fields,
      and `GROUP_ASSIGN_TIP` asserts no run carries them, so that text
      goes stale on the first backfilled run. Per `#313` the field
      **pre-fills** grouping and never replaces it.
      **Blocked on one answer first:** does `P3` in the campaign folder
      names mean the Carbon Solutions P3-SWNT ink, or device 3?
      `electrode_family()` refuses to guess from device tokens, so a
      bare `P3` lands in `other` — the answer decides whether the
      backfill is mechanical or needs the notes.
- [ ] **Fix the screen-height figure in `provision-guest.ps1`** — it
      still asks for ≥1150 px. Host-side edit; the script is out of repo
      by decision, so no PR can reach it. The in-repo copy of the stale
      figure (the `_need_room` docstring, which is where anyone would
      look it up) is corrected as of 2026-08-12.
- [ ] `#199` wishlist — next picks from the tracker. The close-vs-trim
      call is still deferred (`GATES.md` G3), including the open
      sub-question: "error bars" — did that mean capped bars? What
      shipped is `fill_between` ribbons.
- [ ] `#200` connection takeover — build + tests possible; SHIPS only
      after a bench verify. HV policy decided (2026-08-09): **no forced
      remote abort of a live run**. The standing recommendation is
      **not to start it** (`GATES.md` G6): large build, worst case
      bricks connection on the only bench PC, and a machine-local claim
      file cannot arbitrate the two LAN instruments anyway.
- [ ] Optional: trim the manual's Edge Review chapter by ~1,800 words
      (cut list in PR #293's thread; Anatol's call, still no).
- [ ] First run on a new machine: `run_tests.py` to establish ITS
      baseline.

## B. Lab PC / host only (data- or display-bound)

- [x] **Corpus backup — DONE, confirmed by Anatol 2026-08-12**: archived
      and out of the shared directory. `GATES.md` G9 is closed.
- [x] **Backfill `Compliant electrode:` / `Ink concentration:` — DONE
      2026-08-12 on the `Z:` share**, 16 files, each with a
      `.bak-20260812-pre-electrode-backfill` sidecar. Values from Anatol:
      `P3` = Carbon Solutions P3-SWNT with the mL token as the
      concentration, every `SLDEA_202607*` run is P3 at 2.5 mL,
      `SLCBvalidationTest` is carbon black (no concentration key).
      `Electrode family:` was derived by importing the app's own
      `electrode_family()`, never typed.
- [ ] **`DOT_P3_1_20260729` — still unlabelled.** P3-SWNT by name and by
      the SCORECARD's family grouping, but its folder carries no mL token
      and the concentration is not known (Anatol, 2026-08-12). Left
      ABSENT rather than guessed at 2.5, since absent means "predates the
      field" and a wrong value would be indistinguishable from a
      measured one.
- [x] **Stragglers — RESOLVED 2026-08-12, there are none.** Anatol
      placed the CB runs in `SL Ramp Test Initial CB\` "and that's it";
      measured, that folder held exactly one run and the Triazole folder
      one, and a `data.csv` sweep found no others. Everything on the
      share was backfilled.
- [x] **Consolidate the runs under one parent — DONE 2026-08-12.** All
      15 now sit in `SLDEA_data\runs\`, moved by same-volume rename and
      verified on file count, byte total and the SHA-256 of `data.csv`
      and `setup.txt`. `PROVENANCE.md` carries a dated relayout block.
      `_baselines\`, `_analysis\`, `_diag_history\`, `plots\` and the
      campaign docs stayed under `Upload 20260804\`.
- [ ] **REPOINT `SCPI_SLDEA_DIR` to `…\SLDEA_data\runs` on the lab PC
      and the bench fleet — do this before anyone opens a run.** The
      current lab-PC value silently resolves to the two `_baselines\`
      copies (see the warning at the top of this sheet). This is the one
      item the relayout created and it is not optional.
- [ ] **Then the share relayout** (decided: option c) — move
      `SLDEA_data` out of the read-write share's root, attach it as a
      genuine read-only share, repoint `SCPI_SLDEA_DIR` again to wherever
      it lands. Bundled with the consolidation above by decision, so
      recorded paths are invalidated once rather than twice — the
      consolidation is done, this half is host-side and still owed. Same
      pass: the plot window's default Export target writes a `plots` dir
      *beside the runs* and a read-only share will refuse it. Do **not**
      shortcut by pointing `SCPI_SLDEA_DIR` at the `Z:` path — it
      resolves, and hands every tool write access to the corpus.
- [ ] **The control round** (~15–20 min at the Edge Review GUI,
      operator) — the LAST desk-side measurement item. Targets in
      GUI-frame numbers: `DOT_P3_1_20260729` frame 29 ·
      `P3_3_2.5mL_20260728` frames 29 and 66 · `P3_5_2.5mL_0729` frame
      26, plus a SECOND trace on two of them (the repeat pairs — none
      exist corpus-wide). No ▶ Detect, no 💾 Save. Then the agent
      computes the §3b-5 gates and writes the SCORECARD/HANDOFF
      verdicts.
- [ ] `#215` — a second device's worth of operator rounds, **driven in
      circle or twopoint mode**: a verified anchor contributes no
      operator-repeatability figure, so verify-mode rounds cannot answer
      the question. No HV, no instruments — the dialog reads a baseline
      frame and nothing else. Work on a COPY; the dialog writes into the
      run folder.
- [ ] **Re-baseline the lab PC** — unmeasured since #296/#303/#306
      changed both the failures and the reporting.
- [ ] Fleet, analysis PC: `Tools → Update Software…` → footer reads
      `v1.2.0+…`.
- [ ] `#280` — runner flake; box-context, so diagnosis happens where it
      fires. 0 of 4 on the VM, too few to mean anything.
- [ ] Any manual regeneration (capture = headed desktop + Edge + a
      hydrated run folder). **This can now run on the analysis VM** —
      the venv has pypdf and reportlab and the display clears
      `capture.py`'s ≥1090 px bar.

## C. Bench — no HV (delegable, ~25 min)

- [ ] **§M telemetry dry-run smoke** (`BENCH_TEST.md`) — gates trusting
      `telemetry.csv` AND **promotes v1.2.0 out of pre-release**. Also
      produces the first fine-cadence run, which is what the `#264`
      default decision is waiting on.
- [ ] §N watchdog probe — its numbers unblock `#219` design and `#189`
      increment (1). It also reports whether `ACQUIRE:STATE?` answers,
      which is what a scope-left-in-STOP detector would need.
- [ ] `#300` — the `#231` electrode/warm-up smoke (SG stays at 0 V
      through warm-up; blank electrode prompts).
- [ ] `#299` — BK9174B serial exclusivity: apply `exclusive=True` and
      check a cold connect, a second instance failing cleanly, and
      recovery after `kill -9`.
- [ ] §P steps P1/P2 — the dry, delegable half of the fiducial-ring
      procedure.
- [ ] Bench fleet: update to `v1.2.0+…` (currently two releases behind).
- [ ] `#206` installer idempotence re-run.

## D. Bench — HV (authorized operator)

- [ ] §O live telemetry verification.
- [ ] `#159` live verify — one ramp, watch the scope-monitor auto-fix
      dialog, `measured_kV` tracks the whole ramp with no blank tail.
- [ ] **§P fiducial contrast ring** (`BENCH_TEST.md`) — `#193` / `#194`
      exposure + ring experiment as one procedure, ~2.5 h; everything
      after P1/P2 is HV. Unblocks P3_7, and its verdict sizes `#198`.
- [ ] `SLDEA_20260729_104531` device autopsy — dead device vs HV not
      reaching the sample.

## Parked decisions (Anatol's)

- **Release bump.** Main is **62 commits past `v1.2.0`** and the manual
  PDF predates the whole plot batch. The capture stage now runs on the
  VM. Note it stacks a SECOND unpromoted release — v1.2.0 is still a
  pre-release pending §M.
- `#264` cadence-guard default — **decide after §M**, when a
  fine-cadence run exists. Zero of 13 corpus runs would pass the check
  today, so a flip now restyles every historical figure. Persistence
  trap: a stored `cadence_guard: false` silently overrides an
  engine-side flip, so you would see the old behaviour while a colleague
  saw the new one.
- `#268` close vs trim (see §A) · `#199` close vs trim.
- Repo split (PROJECT_HANDOFF open decision 2) · manual binaries → LFS ·
  `demos/` fate.
- `vm-setup\provision-guest.ps1` stays OUT of the repo (decided
  2026-08-09). Its five known defects were fixed in place on 2026-08-09;
  the stale-screen-height figure in §A is a NEW sixth, and has the same
  problem — it can only be fixed by hand on the host.
