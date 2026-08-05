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

Canonical home: `D:\Downloads\SLDEA_data\Upload 20260804\` — contains
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

1. **Repo rename → Digital Multitool.** Safe: GitHub redirects old URLs
   indefinitely. Follow-ups when triggered: `deploy/scpi_from_github.sh`
   hardcoded URL, ShareDrive launcher references, `git remote set-url` on
   clones. Local folder rename is optional and riskier (breaks worktree
   registrations) — skip or do separately.
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

- Repo checkout `D:\Downloads\gui\SCPI_Control` with venv at `.venv`
  (numpy/cv2/matplotlib/Pillow installed). Agent worktrees live under
  `.claude\worktrees\`. No `py` launcher — use `python`.
- C: fills up (was at 0 GB free on 2026-08-04); keep work on D:.
- `robocopy` needs `/R:2 /W:5` or it hangs on one locked file.
- OneDrive `Recordings\SLDEA_data` copies are now redundant per
  `PROVENANCE.md` — retire only against that ledger.

## Picking up work

Read `CLAUDE.md` (conventions), then this file, then whichever doc the
task needs (doc map in `CLAUDE.md`). For campaign work, start from the
campaign `HANDOFF.md` + `SCORECARD.md` in the Upload folder. PRs follow
the TL;DR-first convention; Anatol merges.
