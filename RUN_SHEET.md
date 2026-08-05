# Run sheet — 2026-08-05 (v1.1.0)

**What this is:** an ordered, tick-off view of the open work, split by
where you have to be to do it. **`PROJECT_HANDOFF.md` is the source of
truth** — this is a snapshot of its docket, not a second copy of it.
When they disagree, the handoff is right. Regenerate this file rather
than maintaining it in parallel, and delete it once the list is empty.

Three buckets: **A** you, anywhere · **B** at the bench but **no high
voltage** — safe to hand to a colleague · **C** at the bench **with HV**.

Bucket B is the one worth pushing: **§M alone is the whole gate on
trusting `telemetry.csv`**, it needs no HV training, and it is about
twenty minutes of somebody's time.

---

## A. Remote — nothing here is blocked

Roughly in the order that unblocks the most.

- [ ] **Two 07-23 breakdown-run reviews** — `152205` and `233451`.
      First real exercise of the confirmed-breakdown review path on the
      audit-fixed save chain. `sldea_plot --mode current` previews both
      events. *Agent runs `compare_errorbars.py` after each save.*
- [ ] **Control round traces** (~15 min) — **gates every remaining
      absolute-mm² verdict**, because the optics moved between sessions.
      Do this before the P3_2 review.
- [ ] **P3_2 review** — eyeball the mid-ramp overlays first; +0.7 px flag.
- [ ] **P3_6 holdout frame** (`SLDEA_s31_07.75kV_pre-ramp`) — accept or
      hand-trace. Upgrades P3_6 from a conditional pass. Safe now that
      the #213 partial-re-save fix has landed.
- [ ] **Empty the Recycle Bin** — ~3.26 GB, and C: is tight.
- [ ] **Confirm the OneDrive `Recordings\SLDEA_data` deletion was
      sanctioned.** ⏳ *This one has a clock:* the web recycle bin keeps
      ~30 days from 2026-08-05. If it was not sanctioned, that is the
      recovery path and it expires.
- [ ] **Decide #219's direction** — needs §N's numbers first, so this
      sits behind bucket B.
- [ ] **Pull v1.1.0 onto the bench and analysis PCs** — `Tools → Update
      Software…` / `update_software.sh`, then check the footer reads
      `v1.1.0+…`. The fleet is one release behind. (The updater clones
      main HEAD, so the pre-release flag does not block it.)
- [ ] **Promote the v1.1.0 pre-release to Latest** — *after §M passes.*
      Until then GitHub serves v1.0.0 as "Latest", so anyone told to
      "grab the manual from the latest release" gets the old PDF.
      The bump itself is DONE (shipped 2026-08-05 with both manuals).

**Open decisions with no deadline** (all in `PROJECT_HANDOFF.md`):
split the SLDEA analysis suite into its own repo · manual binaries in
git vs LFS vs release-assets-only · `demos/` fate once #32 is decided.

---

## B. Bench, **no HV** — hand this to a colleague

> A dry run never commands the signal generator, so the app puts no
> control voltage into the Trek. Nothing in this bucket energizes
> anything. It does need the **Linux** bench PC — instrument control
> does not work on Windows.

- [ ] **§M — telemetry dry-run smoke.** Full numbered steps in
      `BENCH_TEST.md`. ~20 min.
      **Unblocks:** trusting `telemetry.csv` at all, and promoting the
      v1.1.0 pre-release to Latest.
      **Send back:** `run.log`, `data.csv`, `telemetry.csv`, `setup.txt`
      from the run folder (a few kB — skip `frames/`).
      **The answer I most want:** whether the run log says `SLOW DISK`.
      The bench output directory is a network share and that is the one
      behaviour desk testing cannot reproduce.
- [ ] **§N — watchdog probe.** One command, ~1 min:
      ```
      .venv/bin/python bench/test_sldea_watchdog_probe.py --ich 3 --vch 2
      ```
      **Unblocks:** #189 increment (1) — the peak-token trip level cannot
      be guessed at a desk — and settles whether #157's 2 Hz cap has
      headroom, and whether increment (3) needs new driver work.
      **Send back:** `sldea_watchdog_probe.txt` and `.json`.
- [ ] **#206 — installer idempotence.** Run
      `deploy/install_lab_launchers.sh` twice; the second run should
      change nothing. Note any duplicate launchers.
- [ ] **#193 — camera manual exposure.** Testing whether the firmware
      honours manual UVC controls needs no HV. Try Stabilize first.

---

## C. Bench, **with HV** — trained and authorized operator only

> Energizes the Trek to real kV. Two rules for whoever does it:
> instrument control is **Linux-bench-only**, and a live run must be
> ended with **■ Abort** — closing the app only attempts a best-effort
> ramp.

- [ ] **§O — live-run verification.** Verifies **#159** (which was
      auto-closed by mistake and reopened — it closes when this RUNS). Full steps in
      `BENCH_TEST.md`. **There is no manual scope work in this.** The
      pre-run check reads the vertical setup back and, on a window that
      cannot show the run's range, offers **"Fix it automatically"**,
      which programs scale, position, offset, attenuation and coupling
      on both monitor channels itself; the −16 µA I_Out offset is
      cancelled by the watchdog's learned 0 kV baseline. Both shipped in
      #195. The job is to *confirm the app does the right thing* — watch
      the dialog fire, note what it said it fixed, and check
      `measured_kV` tracks `nominal_kV` for the whole ramp.
- [ ] **#189 increment (1)** — MEAN → MAXIMUM/PK2PK, streak semantics
      re-tuned for peak noise. **Do §N first**; its section A is the
      input this needs.
- [ ] **#189 increments (3)+(4)** — trigger-armed single-shot capture of
      I_Out plus post-trip `get_waveform()` forensics. The actual fix for
      the ms-arc blind spot. Finishes **#189**.
- [ ] **104531 device** — physically test it: dead device, or HV not
      reaching the sample?
- [ ] **#194 — fiducial contrast ring** for low-CNT devices. Needs a real
      run to evaluate. **Unblocks:** P3_7, and its verdict may shrink
      #198's niche — so do #194 before starting #198.

---

## What just landed (2026-08-05)

- **#218** — the telemetry sidecar. The watchdog's ~2 Hz samples now go
  to `telemetry.csv` beside `data.csv` instead of being discarded.
  Implements #157; #189 increment (2). **Desk-tested only** — §M is the
  gate.
- **#220** — this run sheet's bench half: `BENCH_TEST.md` §M/§N/§O and
  `bench/test_sldea_watchdog_probe.py`.
- **#222 / v1.1.0** — tagged and published as a GitHub **pre-release**
  (because telemetry is desk-only), with both manuals regenerated at
  40 pages and a real crash fix: `sldea_diag.py` was dying on cp1252
  consoles, so on the bench PC a run that reached the new scale gate
  would finish its analysis and then die before writing any of it.
- **Filed:** **#219** the watchdog is invisible on screen until it trips,
  and its trip level is typed by hand while every confirmed breakdown in
  the 08-04 ground truth was a deviation of 11–192 µA — so the smallest
  real events sit *below* the 100 µA default and were only ever caught
  post-hoc · **#223** the plot tool needs a GUI · **#224** telemetry
  control wording · **#225** tabs have no horizontal scrollbar.
- **Reopened:** **#159**, which #220 auto-closed by accident — its
  verification (§O) has never run.
