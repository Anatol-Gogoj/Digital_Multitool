# Project handoff — state as of 2026-08-05

**TL;DR:** Big day 2026-08-05: the cross-run plot tool (#199), the Edge
Review scale gate, **all 28 double-confirmed findings of a 67-agent
correctness audit**, the **live telemetry sidecar** (#218) and its bench
hand-over (#220) all merged to main, and **v1.1.0 tagged and published
as a GitHub PRE-RELEASE** (#222). The bench fleet is still on
v1.0.0+4f5f213 — **one release behind; pulling v1.1.0 onto the bench and
analysis PCs is a live action item.** Batch-QA sits at 5 of 13
runs reviewed. **The priority thread is still current-based breakdown
detection** (#189/#157/#159) — increment (2) is now built, and
**everything left in it is bench-gated**. The desk cannot advance it
further: the remaining increments need SCPI paths and a noise floor
nobody has measured. **The single highest-leverage next action is
`BENCH_TEST.md` §M** — the telemetry dry-run smoke, which involves no
high voltage, needs no HV training, and is the whole gate on trusting
`telemetry.csv`. `RUN_SHEET.md` has the tick-off version split by
remote / bench-no-HV / bench-HV. Durable conventions live in
`CLAUDE.md`; this file is the snapshot — update it at milestones.

## Code state (main)

- **v1.1.0** tagged 2026-08-05 — minor, not patch: since v1.0.0 main
  gained a new tool (`sldea_plot.py`), a new GUI control and output
  artifact (`telemetry.csv`), and the Edge Review scale gate, which
  **requires the operator to do a manual per-run calibration that did
  not exist before**. Both manuals regenerated against the live app at
  this version (**40**-page PDF, telemetry control and the plot tool
  documented and callout-annotated; cover rebranded off the old
  SCPI_Control name). **Published as a PRE-RELEASE** because the
  telemetry sidecar is desk-tested only — so GitHub still reports v1.0.0
  as "Latest" and `releases/latest` still serves the OLD manual PDF.
  Promote it once `BENCH_TEST.md` §M passes.
- **How the fleet actually updates** (checked, because the wording here
  used to be wrong): `update_software.sh` does a shallow **clone of main
  HEAD** — it never reads tags or the releases API, so pre-release
  status does not gate deployment. The `+<hash>` stamp it writes into
  the deployed `version.py` last is a deploy-complete marker for each
  launcher's cache check, not the thing being fetched.
- **v1.0.0** tagged 2026-08-03 (GitHub release, manual PDF attached).
  Merged since, in order: **#195** current-based breakdown detection +
  scope-clipping fixes (ground-truth-validated on all 11 real runs; see
  the 2026-08-04 entry in `SLDEA_HANDOFF.md`); **#218** the live
  telemetry sidecar (the watchdog's ~2 Hz samples now land in
  `telemetry.csv` beside data.csv instead of being discarded —
  implements #157, #189 increment (2); desk-tested only, §M is its
  gate) and **#220** its bench hand-over (`BENCH_TEST.md` §M/§N/§O +
  `bench/test_sldea_watchdog_probe.py`); **#222** the v1.1.0 bump, both
  regenerated manuals, and a real crash fix — `sldea_diag.py` died on
  cp1252 consoles because the scale-gate wording put a 📏 into three
  printed verdicts, so on the bench PC a run that reached the new gate
  would finish its analysis and then die before writing any of it;
  **#196** repo `CLAUDE.md` +
  `.gitignore` hardening; **#201** deep clean (4 historical probes →
  `bench/archive/`, stale docs fixed); **#204** deploy-script URLs for
  the rename; **#208** lab installer versioned (bench-authored); **#209**
  rename-complete handoff sync; **#210** docket designation; **#211**
  `sldea_plot.py` cross-run auto-plot tool (#199 v1; issue stays open as
  the wishlist tracker); **#214** Edge Review scale gate (manual per-run
  calibration, really overrides at Save; supersedes #212, which GitHub
  auto-closed when its stacked base branch was deleted); **#213** the
  edge-suite audit round — 28 double-confirmed + 12 review-pass findings
  fixed (67-agent Opus audit, dual-verified; all runtime gates green and
  the real 13-run batch revalidated: breakdown ground truth exact, scale
  chain self-consistent, 0 sanity violations in 454 rows). Dated entries
  for all of it in `SLDEA_HANDOFF.md`.
- **Bench fleet was deployed + confirmed at v1.0.0+4f5f213**
  (2026-08-05): `Tools → Update Software…` / `update_software.sh` ran and
  the RHEL bench footer was verified by Anatol. **It is now one release
  behind** — pull v1.1.0 onto the bench and analysis PCs and check the
  footer reads `v1.1.0+…`.
- **Manuals are current as of v1.1.0** (2026-08-05) — the three changes
  they were behind on (#195's watchdog/settings text, the scale-gate/
  calibrate flow, the telemetry-log control) are all in, captured from
  the live app rather than hand-edited. Regenerating surfaced a real
  bug, now fixed: `sldea_diag.py --selftest` **crashed** on this Windows
  box because the 2026-08-05 scale-gate wording put a 📏 emoji into three
  printed verdicts, and the bench/analysis consoles are cp1252. The
  report is now ASCII-clamped at one choke point (`sldea_diag._ascii`)
  with a regression test — policing individual f-strings is what failed
  last time.
- Suite baseline: `run_tests.py` → **27/31** on the Windows lab PC (the 4
  failures — test_arb_bin, test_camera_controls, test_presets_path,
  test_tk_fontfix — are environmental and documented; all SLDEA suites
  green). Was 26/30 before the telemetry sidecar added
  `test_sldea_telemetry.py`, and 25/29 before #199 added the sldea_plot
  suite.

## Batch-QA campaign (data side, lives OUTSIDE the repo)

Canonical home: `C:\Users\Anatol Gogoj\Desktop\Digital Multitool\SLDEA_data\Upload 20260804\`
(moved from D:\Downloads 2026-08-05; `SCPI_SLDEA_DIR` points there) — contains
`HANDOFF.md` (the campaign runbook), `SCORECARD.md` (per-run verdicts),
`PROVENANCE.md` (consolidation ledger, retirement executed 2026-08-05 —
recycled copies pending a Recycle Bin empty), `compare_errorbars.py`
(top level; §3b text comparison), `_baselines\`, `_analysis\` (plots),
`_diag_history\` (salvaged gen-1/gen-2 diag snapshots), and the 13 runs
(nested in `SLDEA_data (1)\`). Cross-run figures now come from the
repo's `sldea_plot.py` (area/A-A₀, pre/post, current, power modes) —
stop hand-rolling matplotlib.

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

## Next on the docket (re-designated 2026-08-05: breakdown detection first)

**PRIORITY THREAD — current-based breakdown detection.** The post-hoc
detector is done (#158 CLOSED: step-change-from-median shipped in #195,
ground-truthed twice). What remains is the LIVE half — the watchdog that
missed 233451's −207 µA staircase in real time — tracked in **#189**
(trip logic + fast scope capture), which also carries **#157** (≥1 Hz
logging — implemented by increment (2), issue still OPEN) and **#159**
(kV dropout; the fix shipped in #195, the live verify is what remains).

> **#159 was auto-closed by accident on 2026-08-05 and has been
> reopened.** PR #220's body said "closes #159" while merely describing
> the §O checklist, and GitHub took it literally. The verification has
> never run. Watch for this shape of error: a docs PR that *describes*
> pending work must not use closing keywords.

Staged per #189's own increment plan:

1. **(agent, desk) #189 increment (2): MERGED 2026-08-05 (PR #218) —
   bench smoke owed.** The ~2 Hz watchdog samples (I_Out every sample,
   a kV read at ≤1 Hz) now append to `telemetry.csv` beside data.csv;
   no new SCPI path, `data.csv` and its readers untouched. Implements
   #157. Two adversarial review rounds ran before the PR and caught six
   real defects — the sharpest three found by measurement against the
   real runner: the slow-share flush throttle was inert once a write
   cost more than its own window (a 3 s share stretched the watchdog's
   0.5 s tick to 3 s), the breakdown path flushed twice with the HV
   still up (+4 s of arcing at a 2 s/flush share), and a half-dead link
   could log `v_status=ok` beside a blank `measured_kV`. All fixed with
   tests. Suite 27/31, the new `test_sldea_telemetry.py` (27) covering
   the writer AND the real worker against a fake scope. **Nothing
   depends on the file until the bench smoke below passes.**

   **The bench half is written down and delegable (#220, merged
   2026-08-05).** `BENCH_TEST.md` gained three sections: **§M** the
   telemetry dry-run smoke (no HV — a dry run never commands the SG, so
   this needs no HV training and is the whole gate on trusting the
   file), **§N** the watchdog probe (also no HV), **§O** the live
   verification (HV, authorized operator only). §M and §N can go to a
   colleague at the bench as-is; neither depends on §O. `RUN_SHEET.md`
   is the same list in tick-off form.
2. **(bench, first item of the visit)** verify #195 live → **close
   #159**. Be clear about what this is NOT: **nobody recentres the scope
   by hand.** `_sldea_check_monitors` reads the vertical setup back
   before every live run and, when the visible window cannot show the
   run's range, offers **"Fix it automatically"** — which programs
   SCALE / POSITION / OFFSET / attenuation / coupling on both monitor
   channels itself. The ≈ −16 µA I_Out offset is separately cancelled by
   the watchdog's learned 0 kV baseline. Both shipped in #195; the
   earlier wording here implied manual scope work and was wrong. What is
   actually owed is confirming it live: one SLDEA ramp, watch the dialog
   fire, and check `measured_kV` tracks `nominal_kV` for the WHOLE ramp
   with no blank tail. Same visit,
   **smoke the telemetry sidecar** — a DRY run with the scope connected
   is enough for most of it (telemetry is armed on dry runs, which now
   take scope readings between snapshots where they took none before):
   `telemetry.csv` appears, achieved Hz reads sensibly with no shortfall
   or SLOW-DISK warning in run.log, `data.csv` is byte-identical in
   schema to a pre-change run. Then the live ramp adds the rest —
   `measured_kV` tracking `nominal_kV`, an off-screen I_Out logging
   `i_status=offscreen` with a blank µA, and ■ Abort still ramping
   promptly. Note the bench output dir is a network share: if run.log
   reports SLOW DISK, say so — that is the one behaviour desk testing
   cannot reproduce.
3. **(bench, same visit)** #189 increments (1) then (3)+(4): switch the
   watchdog read MEAN → MAXIMUM/PK2PK (new SCPI token — bench-first per
   convention, streak semantics re-tuned for peak noise), then the real
   fix: trigger-armed single-shot capture of I_Out + post-trip
   `get_waveform()` forensics. Together these finish **#157/#189**.
   **Run `bench/test_sldea_watchdog_probe.py` (§N) first** — it measures
   the three things this step is blocked on: the quiet-rig spread per
   measurement token (which sets the peak-based trip level and cannot be
   guessed at a desk), the real cost of the MEASUREMENT:IMMED triple
   (whether #157's 2 Hz cap has headroom), and whether `TRIGGER:STATE?`
   / `ACQUIRE:STATE?` answer at all. No HV needed for the probe.
4. **(Anatol, desk)** the two 07-23 **breakdown-run reviews** (152205,
   233451) — first real exercise of the confirmed-breakdown review path
   on the audit-fixed save chain; `sldea_plot --mode current` previews
   both events. Agent runs `compare_errorbars.py` after each save.

**Campaign items (unchanged gates):**

- **(Anatol, ~15 min)** the **control round** traces — still gates every
  remaining absolute-mm² verdict (optics moved between sessions). Then
  the **P3_2** review (eyeball mid-ramp overlays first, +0.7 px flag).
- **P3_6 holdout frame** (`SLDEA_s31_07.75kV_pre-ramp`): accept or
  hand-trace → upgrades the conditional pass. Safe now — the #213
  partial-re-save fix landed and merged.

**Rest of the bench visit:** #206 script dedup + installer idempotence
re-run · #193/#194 exposure/contrast-ring experiments (unblocks P3_7,
may shrink #198) · physically test the 104531 device (dead device vs HV
not reaching the sample).

**Desk backlog (after the above):** **promote the v1.1.0 pre-release to
Latest** once §M passes (the bump itself is done — shipped 2026-08-05
with both manuals) · #215 circle-fit calibration ×3 · #216 Edge Review UX (primary
Detect, tooltips) · #197 tuner run picker · #200 connection takeover ·
#198 ML experiment (after the #194 verdict).

**Housekeeping: DONE 2026-08-05** (Anatol-authorized). All 12 DDL-side
`PROVENANCE.md` items verified then moved to the **Recycle Bin**
(~3.26 GB — empty the bin to actually reclaim C: space); the sole-copy
gen-1/gen-2 diag snapshots were salvaged into the Upload folder's
`_diag_history\` first. Ledger updated with a dated retirement entry.
NOTE: the OneDrive `Recordings\SLDEA_data` tree and `D:\Downloads\gui\`
were **already gone before the session acted** (both mtimes 2026-08-05
~00:41–00:43) — if that wasn't a sanctioned cleanup, the OneDrive web
recycle bin (~30-day retention) is the recovery path. Remaining: the
open decisions below.

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

**The priority thread:** #189 live breakdown watchdog + fast scope
capture — **increment (2) built 2026-08-05**, increments (1)
MEAN→MAXIMUM/PK2PK and (3)+(4) trigger-armed single-shot + waveform
forensics still open and bench-first · #157 ≥1 Hz kV/µA logging —
**implemented by that increment; closeable once the bench smoke passes**
· #159 measured_kV dropout (pre-run check shipped in #195; live verify
pending). **#158 is CLOSED** (post-hoc step-change detection shipped +
ground-truthed). New follow-up worth filing: a scope left in STOP freezes
MEAN and telemetry would record a plausible flat trace — detecting it
needs an `ACQUIRE:STATE?` query, so bench-first (the §N probe reports
whether that query answers). · **#219 (new 2026-08-05)** the watchdog's
operator-facing half: it is invisible on screen until it trips, and its
trip level is typed by hand — while every confirmed breakdown in the
08-04 ground truth was a deviation of 11–192 µA, so the smallest real
events sit BELOW the 100 µA default. Display and threshold-derivation
filed together because an automatic number needs a visible one.

**The rest:** #32 GUI framework restyle (demos/ tied) · #193 camera
manual exposure (try Stabilize first; C920/ELP/machine-vision if
firmware wins) · #194 fiducial contrast ring for low-CNT devices
(one-device validation planned; DOT-dot "evidence" was retracted — DOT
is an acronym, different device) · #197 tuner run picker · #198 ML
edge-channel experiment (~93 labels and growing; do #194 first — it may
shrink the niche) · #199 run-data auto-plot tool (v1 shipped in #211;
issue stays open as the wishlist tracker) · #200 cross-session
instrument-connection takeover with warning · #206 deploy-script
dedup/idempotence · #215 circle-fit calibration ×3 (scale gate v2) ·
#216 Edge Review UX (primary Detect, tooltips, flow) · #219 live
watchdog display + where the trip level comes from · **#223** give the
plot tool a GUI instead of eight CLI flags · **#224** telemetry control
wording (drop the filler caption, say it is the scope log) · **#225**
tabs have no horizontal scrollbar — wide content is clipped and
unreachable (same family as #26/#27; the mechanism is that
`ScrollableTab` pins content width to the canvas, so adding a bar alone
would not help).

## This machine (Windows lab/analysis PC)

- Everything lives under the umbrella folder
  `C:\Users\Anatol Gogoj\Desktop\Digital Multitool\` (note the space):
  repo checkout at `Digital-Multitool\` inside it (venv at `.venv`,
  verified; agent worktrees under `.claude\worktrees\`), data at
  `SLDEA_data\` beside it. `SCPI_SLDEA_DIR` points at
  `...\SLDEA_data\Upload 20260804`. No `py` launcher — use `python`.
  Quote every path — two levels of this tree contain spaces. The
  leftover `D:\Downloads\gui\` is gone (verified 2026-08-05, see
  Housekeeping).
- C: space is tight (hit 0 GB free 2026-08-04; **~19 GB free**, measured
  2026-08-05 evening)
  and repo + data now deliberately live on C: — the redundant copies
  were retired to the Recycle Bin 2026-08-05; **empty the bin** to
  reclaim the ~3.26 GB. `SLDEA_data\` now contains only
  `Upload 20260804\`.
- `robocopy` needs `/R:2 /W:5` or it hangs on one locked file.
- OneDrive `Recordings\SLDEA_data` copies: **already deleted by someone
  or something before the 2026-08-05 agent session** (see Housekeeping
  above) — verify that was sanctioned; OneDrive web recycle bin is the
  recovery path if not.

## Cold start — read this first if you are new here

Verified 2026-08-05 by re-running everything below; if a fact here
disagrees with prose elsewhere in this file, trust this section and fix
the other one.

**Where things actually are.** `main` is at the v1.1.0 merge. There is
**one open PR** and it is docs-only. The designated priority is the
live breakdown-detection thread (#189), and **it has no desk work left
in it** — see "what you cannot do" below.

**Five traps that have already caught someone:**

1. **Your local `main` is probably stale.** `git fetch` updates
   `origin/main`, not `main`. Reading `version.py` or this file from a
   stale checkout shows pre-v1.1.0 reality and looks completely
   plausible. Check `git rev-list --count main..origin/main` before
   trusting anything, and edit docs from an up-to-date ref or you will
   silently revert the release documentation.
2. **`python` on PATH is not the repo's Python.** It lacks cv2 and
   pandas, so suites fail for reasons that have nothing to do with your
   change. Use `.venv\Scripts\python.exe` (Windows) — every command in
   this file assumes it.
3. **Selftests write into the current directory.** Run them from a
   scratch dir, not the repo root. Related: the watchdog probe's
   outputs were not gitignored until this was noticed — if you add a
   tool that writes a new artifact type, extend `.gitignore` in the
   same PR (`CLAUDE.md` says so; #220 still got it wrong).
4. **Never put "closes #N" in a PR that only *describes* pending work.**
   #220 did, and GitHub closed #159 — an issue whose verification has
   never been run. It has been reopened.
5. **Passing tests are not proof the GUI opens.** `test_sldea_edge_gui`
   passes headlessly by skipping the display cases. Only
   `test_app_launch.py` (under Xvfb) actually answers that, and it
   self-skips on Windows.

**What you can do at a desk, with no hardware** — all verified to run:

```
.venv\Scripts\python run_tests.py                       # 27/31; the 4 failures are environmental
.venv\Scripts\python tests\test_sldea_telemetry.py      # or any suite directly
.venv\Scripts\python sldea_plot.py --selftest OUT.png
.venv\Scripts\python sldea_diag.py --selftest OUT.png
.venv\Scripts\python sldea_tuner.py --selftest
.venv\Scripts\python bench\test_sldea_watchdog_probe.py --selftest
.venv\Scripts\python sldea_plot.py RUN1 RUN2 --mode area --out <scratch>
.venv\Scripts\python sldea_diag.py <run folder>
```

The four selftests synthesise their own data — no run folders, no
instruments. The 13 real runs live outside the repo (path in the
Batch-QA section above).

**The 4 failing suites are environmental and expected**: `test_arb_bin`,
`test_camera_controls`, `test_presets_path`, `test_tk_fontfix`. If a
FIFTH fails, that one is yours.

**What you cannot do at a desk, and must not fake.** #189's remaining
increments need a new SCPI token (MEAN→MAXIMUM/PK2PK), a trigger-state
query the driver does not have, and a peak-noise floor that has to be
*measured*. `CLAUDE.md` forbids shipping bench-unverified instrument
I/O, and there is no way around it — `bench/test_sldea_watchdog_probe.py`
exists precisely to get those numbers, and until someone runs it at the
bench, increment (1) is not designable. Do not start it.

**If you want useful desk work**, take it from `RUN_SHEET.md` bucket A,
or from #215 / #216 / #197 / #200 / #223 / #224 / #225 — all of which
are real, scoped and hardware-free. #219 becomes designable as soon as
§N's numbers land.

## Picking up work

Read `CLAUDE.md` (conventions), then this file, then whichever doc the
task needs (doc map in `CLAUDE.md`). For campaign work, start from the
campaign `HANDOFF.md` + `SCORECARD.md` in the Upload folder. PRs follow
the TL;DR-first convention; Anatol merges.

**If you are an agent picking this up at a desk:** the priority thread
has no desk work left in it. #189's remaining increments need new SCPI
paths (bench-first per `CLAUDE.md`) and a peak-noise floor that has to
be measured, not guessed — `bench/test_sldea_watchdog_probe.py` exists
to get it. Do not start increment (1) from a desk. The desk-side work
that IS open is in `RUN_SHEET.md` bucket A, and #219 (watchdog display /
threshold derivation) becomes designable once §N's numbers land.
