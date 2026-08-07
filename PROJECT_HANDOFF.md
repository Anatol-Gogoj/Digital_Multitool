# Project handoff — state as of 2026-08-07

**TL;DR (2026-08-07, later desk sessions — read this first; the block
below it is the same day, earlier).** Main is unchanged and green, but
**eight PRs are now open**, from parallel desk sessions working the
roster: #240 (`#238` how-to panel), #241 (`#237` detect timer), #242
(`#216` tooltips), #247 (`#215` dialog-test deflake), and two pairs of
**duplicates** — #245/#246 (manual sources caught up to the verify-first
calibration flow) and #248/#249 (annotate.py fails the manual build on
unmatched callouts). Parallel sessions picked up the same two follow-ups
independently; the pairs conflict on the same lines, so **one of each
pair merges and the other closes** — the differences that matter for the
pick are recorded in "Roster changes 2026-08-07" below. This session
authored #245 and #248 and verified only those four diffs; the other
four PRs are known here by title only.

**TL;DR (2026-08-07, earlier desk session, no bench access).**
Main is green, **no open PRs at its close**, suite **29/33** (the four failures are the
documented environmental ones). Four PRs merged: **#233** the campaign
docket, **#234** the telemetry wording (`#224`), **#235** trace/machine
pairing (`#162`), and **#236** the scale-calibration rework — which grew
well past its issue and is the headline of the session.

**The scale chain is now understood, measured, and one run of it is fixed.**
A corpus-wide auto-calibration sweep fitted every baseline frame and showed
that **every recorded resting area in the corpus is explained, to two
decimals, by its anchor's deviation from the automatic fit** — and that the
eight runs which never had a manual anchor are exactly the eight that land
on π·8² perfectly. Manual calibration is the only source of absolute-area
error in this dataset. Thirteen logged hand calibrations put operator
precision at **σ ≈ 1.05–1.07 % of diameter**, invariant across three
different methods, against an automatic fit whose residual is **0.40 %**.
So the app now defaults to *the machine measures, the operator verifies*.

**Two of my own earlier claims were wrong and are corrected in place** —
worth knowing because both are the kind that get quoted onward. The
resting-area misses were **not** "the optics moved" (per-run anchoring
absorbs optics entirely; they were manual calibrations), and the audit p95
figures were computed nearest-rank where `sldea_diag` uses
`np.percentile`-linear. Details in `SCORECARD.md`'s footnotes and the
sweep report.

**What a fresh agent should know before touching anything:** the bench debt
is unchanged and still gates the priority thread (`BENCH_TEST.md` §M/§N,
~25 min, no HV); the desk-side measurement work is **done** except the
control round, whose premise has itself shifted (see Batch-QA); and
`#236`'s new calibration UI has been driven hard by the operator on real
data but **only on one comparatively clean disc** — P3_7 and low-contrast
ink are unexercised.

---

**TL;DR (2026-08-05, the prior session):** Big day 2026-08-05. Merged, in order: the plot tool (#199),
the scale gate, the 28-finding audit round, the **live telemetry
sidecar** (#218), its **bench hand-over** (#220), **v1.1.0** as a GitHub
**pre-release** (#222), the **tuner fixes** (#226) and the **camera
exposure gate** (#227). Batch-QA sits at 5 of 13 runs reviewed, plus two
NEW runs from the 08-05 session (a carbon-black device and a P3
Triazole).

**Session closed 2026-08-05 with main green and no open PRs.** Merged
after the above: **#230** (the exposure-gate wording — measurement showed
a clipped background does NOT break the detector, so the gate no longer
claims it does) and **#231** (the compliant-electrode field, and a
camera warm-up frame before the baseline).

**⚠ The run schema changed in #231.** Every new run now has a `warmup`
frame at t=0 and its real `baseline` at t=2, with the staircase starting
at t=2. If a run folder looks like it has "two baselines", that is why —
and only the row tagged exactly `baseline` is the reference.

**Everything now blocks on one bench visit, and most of it needs no high
voltage.** `BENCH_TEST.md` **§M** (telemetry dry-run smoke) and **§N**
(watchdog probe) are ~25 minutes together, need no HV training, and
between them unblock: trusting `telemetry.csv`, promoting v1.1.0 out of
pre-release, and #189 increment (1). The desk cannot advance the
priority thread any further — see "Picking up work".

**2026-08-06 (desk, remote session — no bench access).** Both 07-23
breakdown reviews landed by hand, and the whole 07-23 family was then
**retired from the measurement campaign** — files kept, with 152205 and
233451 retained as the breakdown ground-truth fixture. Numbers and
rationale in the Batch-QA section and `SCORECARD.md`. Two defects found and
fixed/recorded on the way: `compare_errorbars.py` had been skipping its
pair-CV check on `pre`/`post`-tagged runs with nothing in the report to say
so, and **#159 + #193 were both auto-closed by keyword parsing and have
been reopened** (roster has the mechanism). Bench debt is unchanged — §M,
§N and §O are all still owed.

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
  camera path stopped ignoring the tab's exposure/gain fields); **#230**
  the exposure-gate wording, corrected after measuring that a clipped
  background does not break detection (the CB run traces at conf
  0.98–0.99 with the disc itself 0.00 % saturated) — the gate stays for
  the two reasons that survived measurement: clipped pixels cannot be
  photometrically normalised, and that baseline was exposed differently
  from its own ramp frames; **#231** the compliant-electrode field
  (`setup.txt` now records `Compliant electrode:` + a canonical
  `Electrode family:`; blank is allowed but Run asks first) and the
  **camera warm-up frame** — a throw-away 0 kV frame at t=0, the real
  baseline at t=2, staircase starting at t=2, which also forced an HV
  fix in `kv_at()` (it fell through to the FINAL level for any t before
  the first segment). Dated entries for all of it in `SLDEA_HANDOFF.md`.
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
- **Suite baseline is now 29/33** (2026-08-07, after #235's and #236's new
  suites: `test_sldea_reanchor.py` and the calibration suites). The four
  failures are the same documented environmental ones. The 27/31 figure
  below is the 2026-08-05 state, kept because the entries around it are
  dated.
- Suite baseline: `run_tests.py` → **27/31** on the Windows lab PC (the 4
  failures — test_arb_bin, test_camera_controls, test_presets_path,
  test_tk_fontfix — are environmental and documented; all SLDEA suites
  green). Was 26/30 before the telemetry sidecar added
  `test_sldea_telemetry.py`, and 25/29 before #199 added the sldea_plot
  suite.

## The scale chain, settled 2026-08-07 (read before any absolute-mm² work)

This is the session's substantive result and it changes how the campaign's
absolute areas should be treated.

**The sweep.** `baseline_disc` was run on every run's baseline frame
(script and report: `_analysis\auto_calibration_sweep_20260806.*` beside the
campaign data). It fits 13 of 15 runs — P3_7 refuses honestly, 145259 has no
baseline frame — with uniform quality: circularity 0.971–0.999, residual
**0.03–0.80 % of diameter**, 151–300 edge points.

**The finding.** Every one of the eleven recorded resting areas in the
corpus is predicted, to two decimal places, by its anchor's deviation from
that automatic fit. The **eight runs with no manual anchor land on
π·8² exactly**; the five with one miss it, by −0.02 % to +2.28 % in diameter.
**Manual calibration is the only source of absolute-area error in this
dataset.** Three runs were ≥1 %: P3_2 (−4.42 % in area), 152205 (−3.38 %),
233451 (+2.44 %).

**Why, measured not assumed.** Thirteen logged hand calibrations give
operator precision **σ ≈ 1.05–1.07 % of diameter**, and it did not move
across three quite different methods (circle-fit, thin-stroke circle,
two-point-with-rotation) nor after a diameter leak that had been correlating
the rounds was closed. A radial intensity profile of P3_2's baseline shows
why: the disc/paper step is **20 gray levels spread over ~60 px of radius**,
so there is no line to click — the operator is choosing a point inside a
gradient wider than the stroke they draw with. The machine takes the
steepest gradient on each of 204 rays and fits robustly.

**Consequences already applied.** The app defaults to verify-the-fit
(#236); a scale-only **re-anchor** path corrects a run's scale without
re-reviewing it; **P3_2 has been corrected** (resting 192.18 → 201.062 mm²,
`method: auto-verified`, px/notes/A-A₀-from-px all byte-identical). 152205
and 233451 still carry their offsets — deliberately, since both are retired
from measurement and correcting them would rewrite the breakdown fixture for
no measurement gain. Their offsets are recorded to two decimals.

**The control round's premise has shifted.** It was justified by "the optics
moved between sessions". Per-run anchoring absorbs optics movement entirely —
which is why the eight autofit runs hit π·8² while spanning 527–606 px. The
residual absolute-mm² risk is calibration *precision*, and auto-calibration
addresses it directly. Its remaining unique value is the machine-vs-operator
boundary offset on ramp frames, which is a different quantity from anything
the sweep measured. **Decide what it is for before spending an operator on
it** — and note its operator-repeat leg has never had data, while `#215`'s
three-round spread now generates that number for free on every manual
calibration.

**What is still unmeasured, and cannot be measured by more of the same:**
the automatic fit's own **systematic** error. Agreement with by-eye readings
on three P3 baselines within ~1 % (the `baseline_disc` docstring) is the only
external check that exists, and sweeping the fitter against itself cannot
supply another. A 0.03 % residual is precision, not accuracy.

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
- **⚠ The five 07-23 runs are RETIRED from the measurement campaign
  (2026-08-06, Anatol's call).** Earliest testing, from a session whose
  inconsistencies were ironed out later — and the numbers agree: all three
  processed ones break the ci85 ceiling (0.90 / 1.16 / 0.97 % against a
  0.2–0.7 % budget) and two miss the 16 mm mask anchor in opposite
  directions (−3.4 %, +2.4 %) where every P3-family run hits π·8² exactly.
  **Nothing was deleted, and 152205 + 233451 are retained as the breakdown
  ground-truth fixture** — they are the corpus's only two designated
  breakdown runs and the evidence behind #219's sub-100 µA argument. Do not
  quote them for area or absolute mm²; do keep using them for breakdown and
  trip-level work. Rationale, numbers and carve-out in `SCORECARD.md`
  §"07-23 family retired from the measurement campaign".
- **P3_2 reviewed 2026-08-06 — conditional pass, with a scale caveat.**
  81/81 filled, 64 auto (79 %), 17 picks + **10 traces** (all in the
  4.5–5.75 kV collapse band, where `tex-ratio` had won on one frame with a
  jagged non-boundary and `disc-fit` was riding an outer halo on the rest:
  no-step 41–43 %, bias −31.85 / −10.09 px). ci85 median 0.30 %, pair CV
  median 0.86 %. **A/A₀ peak 2.302 @ 5.25 kV** — in family with P3_5's
  2.34× — then the usual wrinkle collapse (pair CV 15 % @ 5.5, 26 % @ 5.75,
  matching P3_3/P3_5/P3_6) relaxing to 1.159 by 10 kV.
- **⚠ P3_2's absolute mm² reads −4.42 % low, accepted as-is (Anatol's call
  2026-08-06).** Its manual calibration was drawn at **590.26 px = 16 mm**
  where the resting disc auto-fits at **577.1 px** (circ 0.999), so resting
  comes out 192.18 mm² / 15.643 mm instead of π·8² = 201.06 / 16.000. It is
  the only run in the corpus that misses the mask anchor. **Ratios are
  scale-invariant and are this run's quotable output; do not cross-compare
  its absolute areas** — against the CB curve especially — without applying
  the offset (×1.0462 recovers the anchored scale). Fixing it later is one
  recalibration plus a save, no re-review, since mm² re-derives from px.
- **P3_6 holdout RESOLVED 2026-08-06 — and it is a breakdown.** Anatol's
  determination: the 21 % collapse between post- and pre-ramp at 7.75 kV is a
  breakdown event, so the 257.786 mm² value is true. Accepted as saved —
  **closed without saving**, so the run keeps its pre-#214 auto scale and its
  resting 201.062 mm² = π·8² exactly. **P3_6 upgrades to a full pass**, and
  its worst pair CV (16.4 % @ 7.75 kV) is now explained rather than
  tolerated. Usable curve is the ramp **up to 7.75 kV post-ramp** (peak
  A/A₀ 2.255 @ 5.5 kV); everything above is post-event.
- **⚠ That breakdown is advisory-only, and it is new evidence for the
  priority thread.** `measured_uA` reads **exactly −16.00 µA on every frame
  from 7.00 to 8.50 kV** — this run's I_Out offset, i.e. the channel sitting
  on its own zero — so deviation at the event is **+0.0 µA** and per
  `CLAUDE.md` semantics the frames are **NOT** renamed `*_BREAKDOWN`. But the
  channel demonstrably works on this run (it caught the −30.62 µA transient
  at 5.25–5.5 kV), so either there was no electrical event or **it fell
  between snapshots** — samples are ~8 s apart, a breakdown is milliseconds.
  This is the corpus's **first probable breakdown the current channel
  missed**; both 07-23 ground-truth runs had working traces. Cite it when
  `#219`'s trip level is derived, and note it as motivation on `#157`/`#189`.
  Second-order trap: because the event is advisory, those post-event rows
  carry no `post-breakdown` annotation, so downstream filters will **not**
  drop them — the opposite of P3_5's false-fire problem.
- **Remaining:** the batch-level **control round** (~15 min of traces —
  still required, because the optics moved across the *remaining* sessions
  too); P3_7 (blocked on contrast — see issues #193/#194); 104531 (bench
  decision: device barely actuated, suspect dead device / HV not reaching
  sample).
- **The two 08-05 runs are folded in (2026-08-06)** — `SCORECARD.md` now
  carries a measured verdict for each. **CB** (the first non-CNT
  electrode): A/A₀ **1.158** at 5 kV, resting 202.55 mm² = 16.06 mm, ci85
  median 0.05 %, pair CV median 0.24 %, all 11 frames conf 0.95–0.99 —
  **PASS**, with the clean-exposure re-shoot still owed (baseline median
  255, 73.7 % of pixels ≥250, re-verified 2026-08-06). **Triazole** (CNT,
  81 frames): A/A₀ **1.523** at 8 kV, resting 200.95 mm², ci85 median
  0.24 %, pair CV median 0.76 % — **PASS**. Its **headline is A/A₀ 1.404 @
  7.8 kV**, not the 8.0 kV peak (Anatol's call 2026-08-06, after the
  re-trace below). Onset is 2.2 kV and the 20 sub-onset frames are *stated*
  resting values rather than measurements, so they must not be plotted as
  points.
- **The 8.0 kV re-trace (2026-08-06) moved the peak UP, not down.** The
  promotion path from the first fold was to hand-trace the run's weakest
  frame. Traced, it went **316.27 → 352.13 mm² (+11.3 %)**, A/A₀ 1.574 →
  1.751, and the 8.0 kV pair CV went 4.8 % → **11.9 %** against its own
  post-ramp partner at the same voltage. A careful operator and the detector
  differ by 11 % on that frame, which says the 8.0 kV boundary is genuinely
  ill-defined — the device is wrinkling hard at the end of the ramp and the
  run stops with no relaxation phase. So **8.0 kV is recorded as a traced
  upper bound (1.479–1.751, level mean 1.615) rather than a headline**, and
  7.8 kV — pair CV 0.4 %, both frames conf 0.96 — is the quotable figure.
  Comparison figure: `_analysis\triazole_8kV_after_trace.png`.
- **Two side effects of that re-save.** (a) **Reproducibility, measured for
  free and good:** re-detection reproduced the other 80 frames to a median
  of **0.092 %** (worst 0.61 %), and the scale anchor came through
  **unchanged in value** because the existing calibration was confirmed
  rather than redrawn — the `[critical]` partial-re-save hazard in
  `SLDEA_HANDOFF.md` was avoided. (b) **Rows carrying `(user)` went 81 → 6**,
  so the 08-05 whole-run confirmation is no longer in `data.csv` (it
  survives in `data.csv.pre-8kV-retrace-20260806` beside the run). Upside:
  the acceptance mix is now honest at **93 % auto**, so caveat (a) below no
  longer applies to this run — only to CB.
- **Two caveats that apply to both runs, and to anything reading their
  CSVs:** (a) **the CB run's 0 % auto-accept figure is an artifact** — every
  row carries `(user)`, which `compare_errorbars.py` counts as a human pick,
  so the mix reads 0 auto *by construction*; the diagnostic flagged 0/10, so
  do not compare it to the ~84 % baseline. (Triazole had the same artifact
  until its 08-06 re-save cleared it.) (b) **A missing `audit_*` field means the frame PASSED,
  not that the check was skipped** — `sldea_edge.py:1190-1196` sets
  `audit_nostep` / `audit_bias` only when a frame *exceeds* its gate, and
  the real per-frame numbers live in `frames[].audit`. An earlier version
  of this entry got that backwards and recorded §3b check 2 as
  unevaluated on both runs. Recomputed properly, **both pass**: CB
  **+0.01 px** median with a p95 of **0.25 px** — the cleanest boundary
  audit in the corpus, where every other run sits at 1.90–5.60 px — and
  Triazole **−0.15 px** (p95 2.03). Those p95s are `np.percentile`-linear,
  matching `sldea_diag.py:730` and every run's `sldea_diag.txt`; an earlier
  version of this entry quoted nearest-rank figures (0.28 / 2.12), which
  differ from the machine record on six runs. The method reproduces the
  scorecard's
  original Pass-0 audit column exactly on all eleven earlier runs.
- **Triazole's no-step arc was a false alarm too.** The 34.7 % first
  reported was the median over only the 2 frames that tripped the gate. The
  run-level median over all 48 audited boundaries is **10.8 %**, under the
  15 % gate (P3_1 2.0 %, P3_6 7.7 %, the 07-23 family 9.9–14.8 %), and it
  is elevated for a documented mechanical reason: below onset the boundary
  washes out and the ellipse interpolates those sectors
  (`sldea_edge.py:1467`), which is the same sub-onset stretch that produces
  the stated resting areas. By band: sub-onset 12.2 %, **mid-ramp 5.1 %**,
  top 13.6 % — the measurement band is clean, and the only 2 frames over
  the gate are both at 8.0 kV.
- **The 5.6–7.4 kV plateau is RESOLVED (2026-08-06): device dynamics, not
  detector wander.** Overlays for the band are archived at
  `_analysis\triazole_plateau_5.6-8.0kV_overlays_20260806.png`. Three lines
  agree: the band's boundaries are well supported (no-step 2.0–5.4 %,
  |bias| ≤ 0.65 px, ci85 0.22–0.31 %); precision is ~0.25 % while
  level-to-level variation is ~5 %, twenty times larger; and the dips are
  pre-ramp frames whose post partners are high (6.2 pre 1.221 vs post
  1.333; 7.0 pre 1.190 vs post 1.346), both capped at conf exactly 0.74 —
  `accept_conf` minus 0.01 — i.e. capped on **pair mismatch**, not by the
  audit. Same pattern already attributed to hold-time device motion on
  P3_3 and DOT_P3_1.
- **Peak caveat (Anatol's call 2026-08-06: keep 1.523, footnote it).** The
  investigation relocated the concern from the plateau to the top of the
  ramp. The 8.0 kV **pre-ramp** frame carries the worst confidence (0.59),
  worst bias (+2.34 px), worst no-step (51.7 %) and worst ci85 (0.67 %) of
  all 48 audited boundaries, and the level-averaged headline is half-made
  of it. **7.8 kV is the last fully-supported level (A/A₀ 1.401–1.411)** —
  prefer 1.41 wherever a defensible fully-audited figure is needed, e.g.
  comparing against the CB curve. Hand-tracing that single frame would
  promote 1.523 to fully-supported; not owed, just available.
- The control round's **operator-repeat leg has nothing to compute from
  yet**: `sldea_trace.py` finds 140 labels across 8 runs and **0 repeat
  pairs anywhere**. The 2 repeat pairs still need tracing. Of those 140,
  60 sit in the retired 07-23 runs and 80 in the retained measurement set
  — #198 should say which number it means.
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
and would be masked by its own brightness cut. Worth designing for before
the first EGaIn run rather than after — **#229**. That issue also notes
that nothing in `data.csv` or `setup.txt` currently records which
electrode material a run used, which is awkward for a campaign whose
whole point is comparing materials.

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

  **REVIEWED AND ACCEPTED, 2026-08-05 23:00 (Anatol, full Edge Review).**
  The saturation worry was mine and it did not survive contact with the
  data. All 11 frames reviewed by hand, every one accepted at **conf
  0.95–0.99** (`disc-fit` throughout), areas monotonic, and pre/post
  pairs agreeing to 0.2–0.3 %:

  | | baseline | 1 kV | 2 kV | 3 kV | 4 kV | 5 kV |
  |---|---|---|---|---|---|---|
  | mm² | 202.55 | 204.64 | 211.70 | 224.51 | 231.27 | 234.10 |
  | A/A₀ | 1.000 | 1.010 | 1.045 | 1.108 | 1.142 | 1.156 |

  The resting diameter comes out **16.059 mm against a 16 mm nominal**
  (0.4 %). So CB has a usable expansion curve and the run stays in the
  campaign. What remains is provenance, not measurement: its baseline
  was exposed differently from its own ramp frames, which is why the
  warm-up baseline landed (see `SLDEA_HANDOFF.md`). Re-shoot when
  convenient for a clean-provenance CB curve; do not discard this one.
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
4. **(Anatol, desk) DONE 2026-08-06 — and those runs are now retired.**
   Both 07-23 breakdown reviews (152205, 233451) were completed by hand
   and saved. The confirmed-breakdown review path worked on the
   audit-fixed save chain: 4 and 21 frames renamed on current-confirmed
   events (26/79 µA deviations against a 0.9 µA baseline; the −207 µA
   staircase). `compare_errorbars.py` ran on both, and what it showed is
   what retired the 07-23 family from measurement — see the Batch-QA
   section above. **The breakdown ground truth is retained, so #189 and
   #219 lose nothing.**

**Campaign items (unchanged gates):**

- **(Anatol, ~15 min)** the **control round** traces — still gates every
  remaining absolute-mm² verdict (optics moved between sessions). **This is
  now the only desk-side measurement item left**, and it still needs its 2
  repeat pairs traced, which do not exist anywhere in the corpus yet.
- ~~P3_2 review~~ **DONE 2026-08-06** — conditional pass; A/A₀ 2.302 @
  5.25 kV quotable, absolute mm² −4.42 % low (accepted as-is).
- ~~P3_6 holdout frame~~ **RESOLVED 2026-08-06** — it is a breakdown and the
  value is true; accepted without saving, so the run's π·8² resting survived.
  P3_6 upgrades to a full pass. Details in the Batch-QA section above.

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

## What to continue with (final, 2026-08-05 — main green, no open PRs)

**In order. The first item is the whole bottleneck; everything else is
genuinely independent of it.**

**Status 2026-08-07:** items 1/1b/2 below are unchanged and still owed.
Items 3 and 4 are **DONE** — every desk-side review is complete and both
08-05 runs are folded in. Item 5's list has been worked: `#224` merged in
#234, and `#215` merged in #236 having grown into the whole calibration
rework. What is genuinely left at a desk, in order:

- **`#237`** split the elapsed timer (detection time vs session time) ·
  **`#238`** the Edge Review "How to use" panel · **`#216`** hover
  tooltips and button flow. All three are small, hardware-free, and were
  asked for by the operator after a long real session — they are the
  highest-value desk work now that the measurement side is quiet.
- **`#225`** the horizontal-scrollbar family (root-causes `#27`, related
  to `#26`) · **`#197`** tuner run picker · **`#200`** connection takeover
  (touches instrument connection — cannot be bench-verified here) ·
  **`#223`** a GUI for the plot tool.
- **The control round's premise changed** — see Batch-QA. Do not simply
  "do the control round" without reading that first.

1. **§M + §N at the bench — ~25 min, NO high voltage, delegable.** A dry
   run never commands the SG, so neither needs HV training. Between them
   they unblock trusting `telemetry.csv`, promoting v1.1.0 out of
   pre-release, and #189 increment (1). Full steps in `BENCH_TEST.md`;
   send back `run.log`, `data.csv`, `telemetry.csv`, `setup.txt` and the
   probe's two files. **The single answer most wanted: does run.log say
   `SLOW DISK`** — the bench output dir is a network share and that is
   the one behaviour desk testing cannot reproduce.
1b. **While at the bench, smoke the two #231 changes** — they are
   desk-tested only and both touch the run itself. Start any short run
   and check: `setup.txt` carries `Compliant electrode:`; the run folder
   has a `warmup` frame at t=0 AND a `baseline` at t=2; leaving the
   Electrode box blank prompts before starting; and — the one that
   matters — **the SG stays at 0 V for the whole warm-up window**. That
   last one is pinned by a test, but it is an HV path and deserves eyes.
2. **Fix the CB exposure before capturing that device again (#193).**
   Now concrete rather than theoretical: its baseline is median 255 and
   73.7 % saturated. Since #227 the app will REFUSE to start such a run
   without an explicit override, and will log the override — so the next
   CB attempt should be preceded by lowering exposure on the Webcam tab
   until the pre-flight goes quiet. If the firmware will not honour the
   manual controls, that IS #193 and no app change fixes it.
3. **(desk, Anatol)** the two 07-23 breakdown reviews and the **P3_2
   review** are all **done (2026-08-06)**, as is the **P3_6 holdout**; the
   07-23 family is retired from measurement. What is left on this line is the
   **control round** alone — unchanged, unblocked, independent of everything
   above, and still needing its 2 repeat pairs, which do not exist anywhere
   in the corpus yet. **Every P3-family run in the batch is now reviewed, and
   the control round is the only desk-side measurement item remaining.**
4. **(desk) DONE 2026-08-06.** Both 08-05 runs are folded into
   `SCORECARD.md` with measured verdicts — `sldea_diag.py` and
   `compare_errorbars.py` were run on each rather than transcribing this
   file's figures. **Both PASS, §3b check 2 included** — that check reads
   as unevaluated only if you mistake the per-frame `audit_*` exception
   flags for measurements; the numbers live in `frames[].audit`, and CB's
   audit is the cleanest in the corpus. (The CB peak reads A/A₀ **1.158**
   in the scorecard where this file said 1.156, because the scorecard
   averages each level's pre/post pair while the earlier note quoted single
   frames — same data, different reduction.) The CB clean-provenance
   re-shoot is still worth doing when convenient; the areas stand. Caveats
   in the Batch-QA section above.
5. **(Anatol, 30 seconds)** accept or overrule #224's proposed label
   `📈 Scope kV/µA log (telemetry.csv)` — implemented, every hand-kept
   copy moved (Tk, `content.json` ×2, `annotate.py`, `BENCH_TEST.md`),
   but the word choice is a taste call and nobody but Anatol owns it.
   If you overrule it, the comment above the string in `gui.py` lists
   the copies and the `git grep` that finds them — use the grep, not the
   list. Then #225, #223, #216, #215, #197, #200 — all real, scoped and
   hardware-free. #219 becomes designable the moment §N's numbers land.
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

## Roster changes 2026-08-07

**Merged and delivered:** `#224` (telemetry wording, #234) · `#162`'s unmet
criterion (trace labels always carry a machine candidate, #235) · `#215`
(#236 — see below).

**`#215` is delivered but deliberately left OPEN.** #236 implemented its
fit-a-circle-three-rounds ask *and* superseded it: the measured σ ≈ 1.05 %
means the circle method misses the ±0.4 % SE budget at three rounds, so it
shipped as a **fallback** with verify-the-automatic-fit as the default. What
keeps the issue open is that its own numbers remain unvalidated — the 1 %
spread gate, the round count, the wheel steps and the spawn band are all
chosen rather than measured, and nobody has judged the dialog on
**low-contrast ink** (P3_2's disc is comparatively clean). Close it when a
second device's worth of calibrations exists.

**New:** **`#237`** the elapsed timer keeps running after detection, so
detection time is destroyed as soon as it is produced — split it or freeze
it · **`#238`** an Edge Review "How to use" panel (distinct from `#216`'s
tooltips: what do I do here, versus what does this button do), carrying the
three things that cost time today — wash-out frames get traced not
rejected, Accept stages but Save commits, and a re-anchor skips detection.
`#238` also flags a real design question: the repo already regenerates a
manual from `docs/manual-src/content.json`, so in-app workflow prose is a
second copy that will drift.

**`#216`** now also carries the operator's unprompted re-request for
tooltips after a long real session, so treat that item as confirmed.

**Manual-copy follow-up (2026-08-07, later desk session — PRs #245 and
#248).** The task: `#238`'s implementation found `docs/manual-src/` still
describing the pre-`#215` calibration flow — a button named 📏 Calibrate…
and click-the-disc's-two-opposite-edges as THE method — and deliberately
left the fix out of that PR's scope. Done as two PRs, every claim verified
against `sldea_edge_gui.py` (module docstring, `_scale_intent`, `detect()`)
before rewriting:

- **#245** fixes **five** stale spots, not the three flagged — a repo-wide
  grep found two more, per `#224`'s re-derive-the-set-with-grep rule:
  `content.json`'s control entry, workflow step and subwindow entry,
  `annotate.py`'s 40_edge_review matcher, and `build_manual.py`'s
  "Reviewing a run" steps 2+5. New copy is verify-first (✔ Accept the
  automatic fit; hand circle/two-point as the fallback, offered with the
  fitter's reason on refusal) and states the folded re-anchor outcome
  (saved run + px rows + no open pass → data.csv rewritten immediately, no
  re-detection). Shipped manual binaries intentionally untouched —
  release-cadence, same treatment as the `#224` label move.
- **#248** makes `annotate.py` **fail (exit 1) on any unmatched callout**,
  after completing the sweep so one run lists every drifted string, and
  **deletes `annotated/legends.json` on failure** — `build_manual.py` loads
  it at import, so a chained build stops instead of assembling from the
  previous run's legends. stdout goes `errors=backslashreplace` so the
  emoji-bearing miss report cannot crash a redirected console. Exercised
  against the real v1.1.0 `build/shots`: stale state fails and removes even
  a just-written legends.json; a simulated fresh capture passes and
  restores the dropped callout. Its first real run flagged the KNOWN stale
  pair — the `#224` spec (`📈 Scope kV/µA log`, a startswith-prefix of the
  current Tk label) vs shots that still hold pre-rename
  `📈 Telemetry log (telemetry.csv)`. That is the documented
  old-label-until-rebuild state, now loud instead of silent. The
  handoff-continuation worktree's `build/` is left fail-closed on purpose:
  **no legends.json until the next capture run** — not breakage.

**The duplicate pairs, and what matters for the pick** (this session
authored #245/#248 — weigh the recommendation accordingly):

- **#245 vs #246** is wording emphasis; both are correct against the code.
  #245 leads verify-first, also fixes build_manual step 2 (Detect diverts
  to the dialog on an unanchored run) and names both divert routes
  (Detect and `--auto`) in the subwindow entry; #246 leads with the
  one-button-two-outcomes fold and carries the anchor-resets-per-run-switch
  detail. Merge either; grafting the other's emphasis is a two-line edit.
- **#248 vs #249 differ in behavior, not wording.** #249 writes
  legends.json FIRST and exits 1 after — a chained build that ignores the
  exit code still assembles the degraded manual; #248 deletes legends.json
  so it cannot (the repo's fail-closed idiom). #249 prints misses as
  `ascii()` escapes even on a console that could show them; #248 escapes
  only what the stream cannot carry. And #249 also flips the 📏 MATCH
  string while keeping its stale pre-`#215` LABEL ("click two opposite
  disc edges") — so if #249 is the pick, a copy PR (#245 or #246) is still
  needed for the label either way. Whichever merges: run `annotate.py`
  once afterwards and confirm the exit behavior does what its PR says.

## Active issues roster (curated subset — full list on GitHub)

**The priority thread:** #189 live breakdown watchdog + fast scope
capture — **increment (2) built 2026-08-05**, increments (1)
MEAN→MAXIMUM/PK2PK and (3)+(4) trigger-armed single-shot + waveform
forensics still open and bench-first · #157 ≥1 Hz kV/µA logging —
**implemented by that increment; closeable once the bench smoke passes**
· #159 measured_kV dropout (pre-run check shipped in #195; live verify
pending). **#158 is CLOSED** (post-hoc step-change detection shipped +
ground-truthed).

**⚠ #159 and #193 were BOTH auto-closed again and have been reopened
(2026-08-06).** Neither closure was anyone's decision, and cold-start trap
4 has now fired three times in two days — including inside the PR that
documented it:

- **#159** was closed by PR #228's body, which quoted the phrase
  `closes #159` while explaining that #220 had wrongly closed it that way.
  Quotation marks and surrounding context mean nothing to the keyword
  parser. Its history now reads closed → reopened → closed → reopened, and
  §O has still never run.
- **#193** was closed by commit `5902104` (merged as #227), whose message
  says *"Does NOT fix #193…"*. The negation is invisible to the parser.
  #227's own body is explicit: "Neither of these is #193; they stop the app
  *hiding* #193." The hardware question — whether the firmware honours
  manual UVC controls at all — is untouched.

The rule that actually works: **in a PR body or commit message that only
describes pending work, put the reference in backticks** — `#159` — and
never write a closing keyword next to an issue number, even negated. New follow-up worth filing: a scope left in STOP freezes
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
wording (DONE pending one taste call: the filler caption went on
2026-08-05, and the label is now `📈 Scope kV/µA log (telemetry.csv)`
in all FIVE hand-kept places — Tk, `content.json`'s control entry, its
inert callout entry, `annotate.py`'s callout matcher (which matches the
literal on-screen string), and `BENCH_TEST.md` §M step 2, which sends a
bench operator looking for the box by name. The issue text itself says
three copies and the first fix said four; both undercounted, so re-derive
the
set with `git grep -n "Scope kV"` rather than trusting any list in
prose — ASCII-only, because `git grep` matches bytes and a pattern
containing `µ` or `.` in its place silently matches nothing. The FILE
stays `telemetry.csv` on purpose.
Anatol accepts the wording or picks another; the shipped manual
binaries still show the old label until the next version bump
regenerates them) · **#225** tabs
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

**Five more traps, all from 2026-08-06/07 and all of which cost real time:**

6. **`Accept` in the calibration dialog only STAGES the anchor — Save
   writes it.** The operator accepted a corrected fit on live P3_2, closed
   before Save, and the correction was lost. Nothing on screen implies it.
   The `scale_calibration_log.txt` line is written either way, which is how
   we know the accept happened.
7. **Calibration methods are recorded as NAMES on disk, not letters.**
   `verify` / `circle` / `twopoint` in `cal_mode:` and `mode=`. The UI
   letters were swapped on 2026-08-06 (A=verify, B=circle, C=twopoint), so
   any *legacy* stored letter means the pre-swap thing: `A`=circle,
   `B`=twopoint, `C`=verify. `se.cal_mode_read` is the single rule — use it,
   do not compare letters by hand. Live data contains both vocabularies.
8. **A low residual is precision, not accuracy.** The CB run's fit has a
   0.03 % residual, which says its 284 edge points lie on a circle — not
   that it is the right circle. The automatic fit's systematic error is
   measured by nothing, and no amount of re-fitting can supply it.
9. **Per-frame `audit_nostep` / `audit_bias` are EXCEPTION FLAGS, not
   measurements** (`sldea_edge.py:1190-1196` sets them only when a frame
   exceeds its gate). Null means the frame PASSED. The real numbers are in
   `frames[].audit`. Reading the flags as measurements turns a pass into
   "unevaluated" — done once, corrected in `SCORECARD.md` footnote 3.
10. **The audit p95 is `np.percentile`-linear**, matching `sldea_diag.py:730`
   and every run's `sldea_diag.txt`. Nearest-rank differs on six of twelve
   runs (P3_6 5.60 vs 5.90, 152205 3.60 vs 3.74). One cell in the Pass-0
   scorecard column — P3_1's `2.8` — is a transcription slip; its own
   diag.txt says 2.7. Do not "correct" the method toward that cell.

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

**Three facts about the data you will otherwise get wrong:**

- **A run has TWO 0 kV frames since #231** — `warmup` at t=0 (a
  throw-away that lets the camera settle) and `baseline` at t=2 (the
  reference). Only the row tagged exactly `baseline` is the reference.
  The tag is `warmup`, deliberately NOT `baseline-warmup`, because
  `sldea_plot` phases rows with `tag.startswith('baseline')` and would
  otherwise average the throw-away into A₀.
- **`electrode_lum` masks the FOIL CONTACT TAPE, not the compliant
  electrode.** The name misleads. The electrode is the disc, and on both
  CNT and carbon black it reads *darker* than the membrane — which is
  what `baseline_disc` seeds on. Liquid metal will invert that (#229).
- **A saturated background does not break detection.** Measured on the
  CB run: 73.7 % of the frame clipped, the disc itself 0.00 %, and every
  level traced at conf 0.98–0.99. If you are tempted to write that
  saturation ruins a run, measure first — that exact claim was made and
  retracted here twice.

**What you can do at a desk, no hardware** — all verified to run:

```
.venv\Scripts\python run_tests.py                       # 29/33 as of 2026-08-07; the 4 failures are environmental
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
#219 becomes designable as soon as §N's numbers land, and #229 (liquid
metal inverts the dark-disc assumption) is designable now but should not
be built before there is a device to test it against.

**How this session worked, in case it helps.** Almost everything of
value came from measuring rather than reasoning: the electrode-mask
change looked catastrophic on a synthetic frame and was a no-op on real
data; the saturation worry survived two rounds of confident prose and
died on the first histogram; the `newest_run` bug was found by reading
the resolver rather than by reproducing the symptom. Where a claim here
cites a number, it was run. Where it does not, treat it as a hypothesis.

## Picking up work

Read `CLAUDE.md` (conventions), then this file, then whichever doc the
task needs (doc map in `CLAUDE.md`). For campaign work, start from the
campaign `HANDOFF.md` + `SCORECARD.md` in the Upload folder. PRs follow
the TL;DR-first convention; Anatol merges.
