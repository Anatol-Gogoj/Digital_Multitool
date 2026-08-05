# Project handoff — state as of 2026-08-05

**TL;DR:** v1.0.0 shipped with an illustrated manual; the breakdown
detector was rebuilt around current (not visuals) and ground-truth
validated; the repo is now `Anatol-Gogoj/Digital_Multitool` with **zero
stale pointers anywhere**; repo + data live under
`C:\Users\Anatol Gogoj\Desktop\Digital Multitool\` (umbrella folder).
Batch-QA: 5 of 13 runs reviewed and passed. Priorities are designated in
**Next on the docket** below. Durable conventions live in `CLAUDE.md`;
this file is the snapshot — update it at milestones.

## Code state (main)

- **v1.0.0** tagged 2026-08-03 (GitHub release, manual PDF attached).
  Merged since, in order: **#195** current-based breakdown detection +
  scope-clipping fixes (ground-truth-validated on all 11 real runs; see
  the 2026-08-04 entry in `SLDEA_HANDOFF.md`); **#196** repo `CLAUDE.md` +
  `.gitignore` hardening; **#201** deep clean (4 historical probes →
  `bench/archive/`, stale docs fixed); **#204** deploy-script URLs for
  the rename; **#208** lab installer versioned (bench-authored); **#209**
  rename-complete handoff sync.
- **Manuals are one release behind the tooltips** — #195 changed watchdog
  and Edge Review settings text; per the release checklist the manuals
  regenerate at the next version bump (pipeline: `docs/manual-src/`).
- Suite baseline: `run_tests.py` → **25/29** on the Windows lab PC (the 4
  failures are environmental and documented; all SLDEA suites green).

## Batch-QA campaign (data side, lives OUTSIDE the repo)

Canonical home: `C:\Users\Anatol Gogoj\Desktop\Digital Multitool\SLDEA_data\Upload 20260804\`
(moved from D:\Downloads 2026-08-05; `SCPI_SLDEA_DIR` points there) — contains
`HANDOFF.md` (the campaign runbook), `SCORECARD.md` (per-run verdicts),
`PROVENANCE.md` (consolidation ledger: every source path, what is now
retire-able — the 555 MB zip, OneDrive and loose copies),
`compare_errorbars.py` (top level), `_baselines\`, `_analysis\` (plots),
and the 13 runs (nested in `SLDEA_data (1)\`).

- **Reviewed (5):** P3_1 (prior), P3_3, DOT_P3_1 passed clean; P3_5 and
  P3_6 are **conditional passes** (audit bias slightly out of gate —
  details in `SCORECARD.md`). Error bars carry over: ci85 medians
  0.22–0.35 %.
- **Remaining:** the batch-level **control round** (~15 min of traces —
  required because optics moved between sessions); P3_2 review; the two
  07-23 breakdown-run reviews (152205, 233451); P3_7 (blocked on contrast
  — see issues #193/#194); 104531 (bench decision: device barely actuated,
  suspect dead device / HV not reaching sample).
- **P3_6's raw capture exists nowhere** (review overwrote in place) — its
  processed CSV is the only record.
- Known systemic rig fault (fixed in code by #195's pre-run check, but
  verify on next bench session): scope V_Out clipping killed `measured_kV`
  from 4.25 kV in the P3_5 / P3_6 / 104531 runs; I_Out offset ≈ −16 µA.

## Next on the docket (designated 2026-08-05)

**Immediate next actions:**

1. **(Anatol, ~15 min)** the campaign **control round** traces — it
   gates every remaining verdict (optics moved between sessions). Then
   the **P3_2** review; agent runs `compare_errorbars.py` after each.
2. **(agent, buildable now)** **#199 auto-plot tool** — the campaign
   consumes it immediately for the remaining comparisons and the PhD
   figures; a working prototype already exists at the Upload folder's
   top-level `compare_errorbars.py` (Tol bright, per the issue's toggle
   wishlist).
3. **(Anatol)** reviews of the two 07-23 **breakdown runs** (152205,
   233451) — first real exercise of the new confirmed-breakdown review
   path.

**Next bench session (bundle everything into one visit):**

- **Fix the rig fault, then verify #195 live:** recenter the scope's
  V_Out window and I_Out offset (≈ −16 µA), run one live SLDEA ramp,
  confirm the pre-run window check + deviation watchdog behave →
  **close #158 and #159** (both are code-complete in #195, pending this
  verification).
- **#189** scope-side fast current capture experiments (MEAS slots,
  Hi-Res, single-shot trigger, CURVE logging) — this is also the path
  that finishes **#157** (≥1 Hz logging).
- **#206** remaining criteria: deduplicate the heredoc-vs-`deploy/`
  script copies, then re-run `install_lab_launchers.sh` as the
  idempotence check.
- **#193/#194** experiments: try Stabilize exposure first; one-device
  fiducial contrast-ring validation — unblocks P3_7's review and may
  shrink #198's niche.
- **104531 device decision:** physically test it (barely actuated —
  dead device, or HV not reaching the sample?).

**Desk backlog (after the above):** #197 tuner run picker · #200
connection takeover · #198 ML experiment (after the #194 verdict) ·
next release bump regenerates both manuals (tooltip text drifted in
#195).

**Housekeeping:** delete `D:\Downloads\gui\` (locked by the 2026-08-05
session — delete after it closes) · retire redundant SLDEA copies only
against `PROVENANCE.md` (555 MB zip, OneDrive copies) · the open
decisions below.

## Open decisions (Anatol's calls)

1. **Repo rename: DONE 2026-08-05 — zero stale pointers remain
   anywhere.** GitHub repo is `Anatol-Gogoj/Digital_Multitool`
   (underscore); old SCPI_Control URLs redirect indefinitely. Verified
   end-to-end: both PCs, the ShareDrive updater, the bench installer
   (now versioned at `deploy/install_lab_launchers.sh`, #208), both
   live launchers, the hand-run copy, and the runtime cache clone.
   Full ledger with backups:
   `~/Documents/repo_rename_pointer_hygiene_2026-08-04.md` on the
   bench. ShareDrive/cache FOLDER names (`SCPI_Control`) are deployment
   layout, not the repo name — leave them. Residual #206 work is in the
   bench bundle above.
2. **Split the SLDEA analysis suite** into its own repo. Seam:
   `sldea_edge / sldea_edge_gui / sldea_tuner / sldea_diag / sldea_trace`
   move out (instrument-free); `sldea_profile` + the capture tab stay
   (bench infrastructure). Use `git filter-repo` to keep history; DM then
   launches Edge Review/tuner as an external tool. The rename has
   settled, so nothing blocks this technically — decide whenever. Open
   design point: the manual pipeline captures Edge Review screenshots
   across the seam.
3. **Manual binaries in git** (~5.5 MB/release): keep committing, or move
   to Git LFS / release-assets-only.
4. **`demos/` fate** — decision material for open issue #32 (GUI
   framework); archive the trio when #32 is decided.

## Active issues roster (curated subset — full list on GitHub)

#32 GUI framework restyle (demos/ tied) · #189 scope-side fast current
sampling — MEAS slots, Hi-Res, single-shot trigger, CURVE logging (needs
a bench session; the SW-side half shipped in #195) · #193 camera manual
exposure (try Stabilize first; C920/ELP/machine-vision if firmware wins)
· #194 fiducial contrast ring for low-CNT devices (one-device validation
planned; DOT-dot "evidence" was retracted — DOT is an acronym, different
device) · #197 tuner run picker · #198 ML edge-channel experiment (~93
labels and growing; do #194 first — it may shrink the niche) · #199
run-data auto-plot tool (full toggle wishlist in the issue; Tol bright)
· #200 cross-session instrument-connection takeover with warning.

## This machine (Windows lab/analysis PC)

- Everything lives under the umbrella folder
  `C:\Users\Anatol Gogoj\Desktop\Digital Multitool\` (note the space):
  repo checkout at `Digital-Multitool\` inside it (venv at `.venv`,
  verified; agent worktrees under `.claude\worktrees\`), data at
  `SLDEA_data\` beside it. `SCPI_SLDEA_DIR` points at
  `...\SLDEA_data\Upload 20260804`. No `py` launcher — use `python`.
  Quote every path — two levels of this tree contain spaces. Leftover
  `D:\Downloads\gui\` could not be deleted during the move (session
  file lock) — delete it whenever.
- C: space is tight (hit 0 GB free 2026-08-04; ~23 GB after cleanup)
  and repo + data now deliberately live on C: — watch free space, and
  retire the `PROVENANCE.md`-verified redundant copies to keep headroom.
- `robocopy` needs `/R:2 /W:5` or it hangs on one locked file.
- OneDrive `Recordings\SLDEA_data` copies are now redundant per
  `PROVENANCE.md` — retire only against that ledger.

## Picking up work

Read `CLAUDE.md` (conventions), then this file, then whichever doc the
task needs (doc map in `CLAUDE.md`). For campaign work, start from the
campaign `HANDOFF.md` + `SCORECARD.md` in the Upload folder. PRs follow
the TL;DR-first convention; Anatol merges.
