# Project handoff — state as of 2026-08-05

**TL;DR:** v1.0.0 shipped with an illustrated manual; since then the
breakdown detector was rebuilt around current (not visuals) and merged;
the repo got a deep clean (verdict: nothing was dead); all SLDEA run data
now lives canonically in `D:\Downloads\SLDEA_data\Upload 20260804\`. Open:
a repo rename, a possible analysis-suite split, the rest of the batch-QA
reviews, and a stack of enhancement issues. Durable conventions live in
`CLAUDE.md`; this file is the snapshot — update it at milestones.

## Code state (main)

- **v1.0.0** tagged 2026-08-03 (GitHub release, manual PDF attached).
  Merged since, in order: **#195** current-based breakdown detection +
  scope-clipping fixes (ground-truth-validated on all 11 real runs; see
  the 2026-08-04 entry in `SLDEA_HANDOFF.md`); **#196** repo `CLAUDE.md` +
  `.gitignore` hardening; **#201** deep clean (4 historical probes →
  `bench/archive/`, stale docs fixed).
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
retire-able — the 555 MB zip, OneDrive and loose copies), `_baselines\`,
`_analysis\` (plots + `compare_errorbars.py`), and the 13 runs.

- **Reviewed + passed (5):** P3_1 (prior), P3_3, DOT_P3_1, P3_5, P3_6 —
  error bars carry over (ci85 medians 0.22–0.35 %, all §3b checks).
- **Remaining:** the batch-level **control round** (~15 min of traces —
  required because optics moved between sessions); P3_2 review; the two
  07-23 breakdown-run reviews (152205, 233451); P3_7 (blocked on contrast
  — see issues #193/#194); 104531 (bench decision: device barely actuated,
  suspect dead device / HV not reaching sample).
- **P3_6's raw capture exists nowhere** (review overwrote in place) — its
  processed CSV is the only record.
- Known systemic rig fault (fixed in code by #195's pre-run check, but
  verify on next bench session): scope V_Out clipping killed `measured_kV`
  from 4.25 kV in all three 07-29 runs; I_Out offset ≈ −16 µA.

## Open decisions (Anatol's calls)

1. **Repo rename: DONE 2026-08-05.** GitHub repo is now
   `Anatol-Gogoj/Digital_Multitool` (underscore); old SCPI_Control URLs
   redirect indefinitely. Local checkout lives at
   `C:\Users\Anatol Gogoj\Desktop\Digital-Multitool` (worktrees repaired,
   venv verified, remote set-url done); repo scripts
   (`deploy/scpi_from_github.sh`, `deploy/update_software.sh.reference`)
   point at the new URL. Bench-side repointing
   2026-08-05: RHEL clone remote + pull (#204), ShareDrive
   `_software/update_software.sh`, the live
   `/usr/local/bin/scpi-from-github.sh` (interactive-sudo sed, verified
   1-line change), and the launcher's runtime cache clone
   (`~/.cache/scpi_control_git` stored its own old origin — repointed;
   kiosk account has no cache, clones fresh) are ALL done. **Rename saga COMPLETE
   2026-08-05: zero stale pointers remain anywhere** — GitHub, both PCs,
   the ShareDrive updater, the bench installer, both live launchers, the
   hand-run copy, and the runtime cache clone all read
   `Digital_Multitool` (bench sweep verified; full ledger in
   `~/Documents/repo_rename_pointer_hygiene_2026-08-04.md` on the bench,
   backups kept). The installer is versioned at
   `deploy/install_lab_launchers.sh` (#208). Remaining #206 work for the
   next bench visit: deduplicate the heredoc-vs-`deploy/` script copies
   and re-run the installer as an idempotence check. ShareDrive/cache
   FOLDER names (`SCPI_Control`) are deployment layout, not the repo
   name — leave them.
2. **Split the SLDEA analysis suite** into its own repo. Seam:
   `sldea_edge / sldea_edge_gui / sldea_tuner / sldea_diag / sldea_trace`
   move out (instrument-free); `sldea_profile` + the capture tab stay
   (bench infrastructure). Use `git filter-repo` to keep history; DM then
   launches Edge Review/tuner as an external tool. Decide after rename +
   these PRs settle. Open design point: the manual pipeline captures Edge
   Review screenshots across the seam.
3. **Manual binaries in git** (~5.5 MB/release): keep committing, or move
   to Git LFS / release-assets-only.
4. **`demos/` fate** — decision material for open issue #32 (GUI
   framework); archive the trio when #32 is decided.

## Open issues roster

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
- C: fills up (was at 0 GB free on 2026-08-04); keep work on D:.
- `robocopy` needs `/R:2 /W:5` or it hangs on one locked file.
- OneDrive `Recordings\SLDEA_data` copies are now redundant per
  `PROVENANCE.md` — retire only against that ledger.

## Picking up work

Read `CLAUDE.md` (conventions), then this file, then whichever doc the
task needs (doc map in `CLAUDE.md`). For campaign work, start from the
campaign `HANDOFF.md` + `SCORECARD.md` in the Upload folder. PRs follow
the TL;DR-first convention; Anatol merges.
