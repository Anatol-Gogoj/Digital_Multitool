# Project handoff — state as of 2026-08-05

**TL;DR:** Big day 2026-08-05. Merged, in order: the plot tool (#199),
the scale gate, the 28-finding audit round, the **live telemetry
sidecar** (#218), its **bench hand-over** (#220), **v1.1.0** as a GitHub
**pre-release** (#222), the **tuner fixes** (#226) and the **camera
exposure gate** (#227). Batch-QA sits at 5 of 13 runs reviewed, plus two
NEW runs from the 08-05 session (a carbon-black device and a P3
Triazole).

**Everything now blocks on one bench visit, and most of it needs no high
voltage.** `BENCH_TEST.md` **§M** (telemetry dry-run smoke) and **§N**
(watchdog probe) are ~25 minutes together, need no HV training, and
between them unblock: trusting `telemetry.csv`, promoting v1.1.0 out of
pre-release, and #189 increment (1). The desk cannot advance the
priority thread any further — see "Picking up work".

The fleet is still on **v1.0.0+4f5f213**, one release behind; pulling
v1.1.0 onto the bench and analysis PCs is a live action item. Durable
conventions live in `CLAUDE.md`; this file is the snapshot — update it
at milestones.

## Code state (main)

- **v1.1.0** tagged 2026-08-05 — minor, not patch: since v1.0.0 main
  gained a new tool (`sldea_plot.py`), a new GUI control and output
  artifact (`telemetry.csv`), and the Edge Review scale gate, which
  **requires the operator to do a manual per-run calibration that did
  not exist before**. Both manuals regenerated against the live app at
  this version (**40**-page PDF; telemetry control and the plot tool both
  documented and callout-annotated, cover rebranded off the old
  SCPI_Control name). **Published as a PRE-RELEASE** because the
  telemetry sidecar is desk-tested only — GitHub still reports v1.0.0 as
  "Latest", so `releases/latest` still serves the OLD manual PDF.
  Promote it once §M passes. The updater does a shallow **clone of main
  HEAD** and never reads tags or the releases API, so pre-release status
  does not gate deployment; the `+<hash>` stamp is a deploy-complete
  marker for each launcher's cache.
- **v1.0.0** tagged 2026-08-03 (GitHub release, manual PDF attached).
  Merged since, in order: **#195** current-based breakdown detection +
  scope-clipping fixes (ground-truth-validated on all 11 real runs; see
  the 2026-08-04 entry in `SLDEA_HANDOFF.md`); **#196** repo `CLAUDE.md` +
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
  chain self-consistent, 0 sanity violations in 454 rows); **#218** the
  live telemetry sidecar (the watchdog's ~2 Hz samples now land in
  `telemetry.csv` beside data.csv instead of being discarded —
  implements #157, #189 increment (2); DESK-TESTED ONLY, §M is its
  gate); **#220** its bench hand-over (`BENCH_TEST.md` §M/§N/§O +
  `bench/test_sldea_watchdog_probe.py`); **#226** the tuner fixes
  (electrode mask default 220→255, and the Tune button's resolver — it
  used `newest_run`, which only inspects SUB-directories, so pointing
  the output dir at a run folder reported "no finished runs (data.csv)"
  about a folder containing exactly that); **#227** the camera gate (a
  blown-out baseline now stops a run instead of whispering, and the cv2
  camera path stopped ignoring the tab's exposure/gain fields). Dated
  entries for all of it in `SLDEA_HANDOFF.md`.
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

### Electrode material is a study variable, not a rig detail

**The SLDEA study compares COMPLIANT ELECTRODE TYPES.** Everything
measured so far is **CNT** (the `P3 *-mL` runs). **Carbon black (CB)**
is the second type and is now in the campaign. **Liquid metal is
expected later** and will be the hard one. So the tool is not "a CNT
tool that also coped with a CB run" — it has to capture every type, and
each new type is a first-class campaign device, not a shakedown to be
discarded.

Read the 2026-08-05 mask/exposure work in that light: nothing about it
is CB-specific. The `electrode_lum` mask keys on BRIGHTNESS and actually
targets the **foil contact tape**, not the compliant electrode itself —
the electrode is the disc, and on both CNT and CB it reads DARKER than
the membrane, which is exactly what `baseline_disc` seeds on
(`dark = sm < paper - 5`). **Liquid metal breaks that assumption**: a
specular, mirror-bright electrode would be brighter than the membrane
and would be masked by its own brightness cut. Worth designing for
before the first EGaIn run rather than after — filed as an issue.

**NEW: `SLDEA_data\Upload 20260805\`** — a second upload folder, not yet
folded into the campaign runbook:

- `SL Ramp Test Initial CB\SLCBvalidationTest` — the first **carbon
  black** run, and the campaign's first non-CNT electrode. 11 frames,
  0–5 kV, raw (never reviewed). Its `setup.txt` already carries
  `electrode_lum: 255`. **Its baseline is saturated — mean 235, MEDIAN
  255, 73.7 % of pixels at/above 250**, against 0.12–3.62 % on every
  other baseline in the corpus. That is an EXPOSURE fault, not an
  electrode one (08-05 entry in `SLDEA_HANDOFF.md`), and since #227 the
  app refuses to start such a run without a logged override.
  **Decision needed: review these 11 frames, or re-shoot the device
  with corrected exposure and review that?** Areas measured against a
  mostly-white baseline carry an uncertainty nothing in
  `SLDEA_MEASUREMENT.md` covers, so if these frames are kept the CB
  numbers need a caveat the CNT numbers do not. Re-shooting is cheap by
  comparison — 11 frames, 0–5 kV.
- `Single Layer Testing\P3 1.5mL Triazole Bake1\P3 1.5mL Triazole
  Bake1-1` — an 81-frame CNT run, already reviewed (areas + `edge:
  resting conf 0.95 (user)` in `data.csv`), healthy baseline. Not in
  `SCORECARD.md`; folding it in is desk work.

## Next on the docket (re-designated 2026-08-05: breakdown detection first)

**PRIORITY THREAD — current-based breakdown detection.** The post-hoc
detector is done (#158 CLOSED: step-change-from-median shipped in #195,
ground-truthed twice). What remains is the LIVE half — the watchdog that
missed 233451's −207 µA staircase in real time — tracked in **#189**
(trip logic + fast scope capture), which also carries **#157** (≥1 Hz
logging) and closes out **#159** (kV telemetry dropout, pre-run check
shipped, live verify pending). Staged per #189's own increment plan:

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

   **The bench half is now written down and delegable.** `BENCH_TEST.md`
   gained three sections: **§M** the telemetry dry-run smoke (no HV — a
   dry run never commands the SG, so this needs no HV training and is
   the whole gate on trusting the file), **§N** the watchdog probe (also
   no HV), **§O** the live verification (HV, authorized operator only).
   §M and §N can go to a colleague at the bench as-is; neither depends
   on §O.
2. **(bench, first item of the visit)** verify #195 live → **close
   #159**. Be clear what this is NOT: **nobody recentres the scope by
   hand.** `_sldea_check_monitors` reads the vertical setup back before
   every live run and, when the visible window cannot show the run's
   range, offers **"Fix it automatically"**, which programs SCALE /
   POSITION / OFFSET / attenuation / coupling on both monitor channels
   itself; the ≈ −16 µA I_Out offset is separately cancelled by the
   watchdog's learned 0 kV baseline. Both shipped in #195. What is
   actually owed is confirming it live: one ramp, watch the dialog fire,
   check `measured_kV` tracks `nominal_kV` for the WHOLE ramp with no
   blank tail. (**#159 was auto-closed by mistake on 2026-08-05** — PR
   #220's body said "closes #159" while merely describing the §O
   checklist — and has been reopened. A docs PR describing pending work
   must not use closing keywords.) Same visit,
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

**Desk backlog (after the above):** **release bump** (fleet already on
main tip, but the bump regenerates both manuals and stamps the fleet
v1.0.1) · #215 circle-fit calibration ×3 · #216 Edge Review UX (primary
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

## What to continue with (2026-08-05, after #226/#227 merged)

**In order. The first two are the whole bottleneck.**

1. **§M + §N at the bench — ~25 min, NO high voltage, delegable.** A dry
   run never commands the SG, so neither needs HV training. Between them
   they unblock trusting `telemetry.csv`, promoting v1.1.0 out of
   pre-release, and #189 increment (1). Full steps in `BENCH_TEST.md`;
   send back `run.log`, `data.csv`, `telemetry.csv`, `setup.txt` and the
   probe's two files. **The single answer most wanted: does run.log say
   `SLOW DISK`** — the bench output dir is a network share and that is
   the one behaviour desk testing cannot reproduce.
2. **Fix the CB exposure before capturing that device again (#193).**
   Now concrete rather than theoretical: its baseline is median 255 and
   73.7 % saturated. Since #227 the app will REFUSE to start such a run
   without an explicit override, and will log the override — so the next
   CB attempt should be preceded by lowering exposure on the Webcam tab
   until the pre-flight goes quiet. If the firmware will not honour the
   manual controls, that IS #193 and no app change fixes it.
3. **(desk, Anatol)** the two 07-23 breakdown reviews (152205, 233451),
   then the control round, P3_2, and the P3_6 holdout frame — unchanged,
   unblocked, and independent of everything above.
4. **(desk/bench)** decide the CB run's fate — review the 11 saturated
   frames with a caveat, or re-shoot the device at a corrected exposure
   and review that (see the campaign section). Either way CB is a
   campaign electrode type, not a shakedown. Also fold the new CNT
   Triazole run into `SCORECARD.md`.
5. **(desk)** #224's rename word choice, then #225, #223, #216, #215,
   #197, #200 — all real, scoped and hardware-free. #219 becomes
   designable the moment §N's numbers land.
6. **PR #221 is deliberately set aside** — it holds `RUN_SHEET.md` (the
   tick-off version of this docket, split remote / bench-no-HV /
   bench-HV) and a cold-start briefing for a new agent. It was mergeable
   at the time it was parked; it will want main merged into it again
   before it lands, because this file has moved since.

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
#216 Edge Review UX (primary Detect, tooltips, flow) · **#219** live
watchdog display + where the trip level comes from · **#223** give the
plot tool a GUI instead of eight CLI flags · **#224** telemetry control
wording (the filler caption is gone; the rename still needs a word
choice, and the label has THREE copies that must move together — Tk,
`content.json`, and `annotate.py`'s callout matcher) · **#225** tabs
have no horizontal scrollbar, wide content is clipped and unreachable
(`ScrollableTab` pins content width to the canvas, so adding a bar
alone does nothing; likely the root cause of #27, same family as #26).

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
- C: space is tight (hit 0 GB free 2026-08-04; ~21 GB free 2026-08-05)
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

Verified by re-running it, not recalled. If a fact here disagrees with
prose elsewhere in this file, trust this and fix the other one.

**Five traps that have already caught someone:**

1. **Your local `main` is probably stale.** `git fetch` updates
   `origin/main`, not `main`. Reading `version.py` or this file from a
   stale checkout shows an older reality and looks entirely plausible.
   Check `git rev-list --count main..origin/main` first.
2. **`python` on PATH is not the repo's Python** — it lacks cv2 and
   pandas, so suites fail for reasons unrelated to your change. Use
   `.venv\Scripts\python.exe`.
3. **Selftests write into the current directory.** Run them from a
   scratch dir. If you add a tool that writes a new artifact type,
   extend `.gitignore` in the same PR (the watchdog probe's outputs were
   missed and had to be added later).
4. **Never put "closes #N" in a PR that only DESCRIBES pending work.**
   #220 did, and GitHub closed #159 — whose verification has never run.
   It has been reopened.
5. **Passing tests are not proof the GUI opens.** `test_sldea_edge_gui`
   passes headlessly by skipping the display cases; only
   `test_app_launch.py` (under Xvfb) answers that, and it self-skips on
   Windows.

**What you can do at a desk, no hardware** — all verified to run:

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

The four selftests synthesise their own data. The real runs live outside
the repo (paths in the Batch-QA section).

**The 4 failing suites are environmental and expected**: `test_arb_bin`,
`test_camera_controls`, `test_presets_path`, `test_tk_fontfix`. A FIFTH
failure is yours.

**What you CANNOT do at a desk, and must not fake.** #189's remaining
increments need a new SCPI token (MEAN→MAXIMUM/PK2PK), a trigger-state
query the driver does not have, and a peak-noise floor that has to be
MEASURED. `CLAUDE.md` forbids shipping bench-unverified instrument I/O.
`bench/test_sldea_watchdog_probe.py` exists to get those numbers; until
someone runs it, increment (1) is not designable. Do not start it.

**Useful desk work** is in `RUN_SHEET.md` bucket A, or #215 / #216 /
#197 / #200 / #223 / #224 / #225 — all real, scoped, hardware-free.
#219 becomes designable as soon as §N's numbers land.

## Picking up work

Read `CLAUDE.md` (conventions), then this file, then whichever doc the
task needs (doc map in `CLAUDE.md`). For campaign work, start from the
campaign `HANDOFF.md` + `SCORECARD.md` in the Upload folder. PRs follow
the TL;DR-first convention; Anatol merges.
