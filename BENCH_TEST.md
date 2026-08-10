# Bench test checklist — signal gen (§A–§L, historical) + SLDEA telemetry/watchdog (§M–§O) + fiducial-ring experiment (§P, current)

**Setup:** BNC from sig gen **CH1 → scope CH1** (1 MΩ input). ~15 min total.
Launch: `.venv/bin/python gui.py`

---

## A. Connect & populate (PR #7, #11)

- [ ] SG tab status shows **Connected: BK,4055B,…** (green) on launch
- [ ] CH1/CH2 input fields match the **front panel's** current settings
- [ ] Gray *applied* readouts beside each field match the front panel too
- [ ] Output buttons match reality (green **Output: ON** only if a channel is actually on)

## B. Adaptive fields (#8) — flip waveform on CH1, watch the form

- [ ] SINE → Frequency / Amplitude / Offset only (Basic mode)
- [ ] SQUARE → **Duty Cycle (%)** appears
- [ ] RAMP → **Symmetry (%)** appears (duty gone)
- [ ] PULSE → Duty appears (Rise/Fall/Delay only after step C)
- [ ] DC → only DC Offset remains; NOISE → no parameter fields
- [ ] Preview redraws to the right shape on every switch

## C. Basic/Advanced toggle

- [ ] Toggle **Advanced mode** on → Phase, Load (Ω), Polarity appear; with PULSE selected, Rise/Fall/Delay appear
- [ ] Toggle off → they hide again (values are still applied regardless — verified in E)

## D. Apply vs Output split (#9) — the big one

1. CH1: SQUARE, 1000 Hz, 2 Vpp, offset 0, **Duty 25** → **Apply CH1 Settings**
   - [ ] Front panel shows the new config
   - [ ] **Output LED did NOT change** (Apply must not touch output)
   - [ ] Applied readouts update to 1000 / 2 / 0 / 25
2. Press **Output** button
   - [ ] Button goes green **Output: ON**, front-panel output LED lights
   - [ ] Scope shows a 1 kHz square, high ~25% of the period
   - [ ] Scope tab → Get CH1 Measurements: Frequency ≈ 1 kHz, Pk-Pk ≈ 2 V
3. Press **Output** again → [ ] OFF, LED out, scope flatlines

## E. Applied readouts catch clamping (#11)

- [ ] Enter Frequency `999999999` (1 GHz) → Apply → input still shows your number, but the **applied readout shows the instrument's clamped max** (≠ input) — or an error dialog, either proves the readback works
- [ ] Restore a sane frequency → Apply → applied matches input again

## F. Load control (#10) — Advanced mode on, CH1 SINE 1 Vpp, output ON

- [ ] Load shows **High-Z** (not "HZ") and scope reads ≈ 1 Vpp
- [ ] Set Load `50` → Apply → front panel shows 50 Ω, **scope now reads ≈ 2 Vpp** (amplitude is calibrated *into 50 Ω*; the 1 MΩ scope sees double)
- [ ] Type a custom value `600` → Apply → front panel shows 600 Ω (no error)
- [ ] Back to High-Z → Apply → scope reads ≈ 1 Vpp again
- [ ] Junk load (`fifty`) → Apply → clean error dialog, nothing sent

## G. Preview accuracy (#12)

- [ ] SQUARE duty `10` → preview shows narrow pulses (live while typing)
- [ ] RAMP symmetry `100` → rising sawtooth; `0` → falling
- [ ] Advanced: SINE phase `90` → preview starts at the crest
- [ ] After Apply + Output ON: **preview shape ≈ scope shape** for each of the above

## H. Presets (PR #7 + extended schema)

1. CH1: SQUARE duty 25; CH2: RAMP symmetry 30 → save as `bench_test`
   - [ ] Appears in dropdown; `presets/siggen_presets.json` contains `duty_pct`/`sym_pct`
2. Change both channels to SINE defaults → Apply both
3. Load `bench_test`
   - [ ] Inputs restore **including duty/symmetry**, config pushed (applied readouts + front panel confirm)
   - [ ] **Output state unchanged** by the preset load
4. Delete `bench_test` → [ ] gone from dropdown and file

## I. Error handling & reconnect

- [ ] Frequency `abc` → Apply → error dialog, GUI alive
- [ ] Duty `150` → Apply → validation error ("between 0 and 100"), nothing sent
- [ ] (Optional) Unplug sig gen USB → Apply → error dialog; replug → **Reconnect** → status green, fields repopulate

## J. Channel independence

- [ ] Configure + Apply CH2 only → CH1 applied readouts and front-panel CH1 unchanged
- [ ] CH2 Output button drives only CH2's LED

## K. Arbitrary waveforms (PR: sg-arb-upload, #13)

> **⚠ HISTORICAL — superseded.** This section predates the arb editor
> rework and the 52-byte USB cap discovery: the button labels below no
> longer exist ("Save CSV Template…" → "Save Template...", "Load CSV…" →
> "Import CSV...", "Save Current" → "Save to Library", "Upload & Select
> on CH1" → "Send to CH:" + "Upload && Select"), direct upload is now
> LAN-only (refused over USB), and the K.8 max-length probe is exactly
> the experiment that wedges the 4055B. Use the current arb workflow in
> README §"BK 4055B arbitrary waveforms" and section L instead.

1. CH1 → waveform **ARB** → [ ] "Arb Waveform:" row appears with **Waveform Editor…** button
2. Open editor → **Save CSV Template…** to e.g. `~/arb_template.csv`
   - [ ] File has `value` header + 32 rows (one sine period)
3. Edit a few rows in the CSV (e.g. clip the top: change values > 0.8 to 0.8) → **Load CSV…**
   - [ ] Info shows "32 points loaded", preview shows the clipped sine
4. Name `clipsine`, CH1 freq 1000 / amp 2 / offset 0 → **Upload & Select on CH1**
   - [ ] No error; channel panel switches to ARB, arb name label shows `clipsine`
   - [ ] Applied readout (gray, next to Waveform Editor) shows `clipsine`
   - [ ] Front panel shows ARB mode with the waveform name
5. Output ON → [ ] scope shows the clipped sine at 1 kHz, 2 Vpp
6. **Save Current** to library → [ ] `presets/arb/clipsine.csv` exists
7. Save a channel preset while ARB selected → reload it later
   - [ ] Preset restores ARB + `clipsine` selection (arb must already be in instrument memory — preset load selects, does not re-upload)
8. **Max-length probe** (fills in the unknown): make a CSV with 16384 rows
   (`python -c "print('value'); [print(__import__('math').sin(6.283*i/16384)) for i in range(16384)]" > big.csv`)
   - [ ] Uploads OK → try larger by editing `ARB_MAX_POINTS` in instruments.py; note where the box errors/truncates

---

## L. Waveform editor — compose + draw (PR: sg-arb-editor, EasyWaveX-style)

1. CH1 → waveform **ARB** → **Waveform Editor…** opens the editor
2. **Compose via sidebar (typed coordinates)** — build the worked example:
   - Point 0 = (0, 0); double-click cells to type exact X/Y
   - Add a point, set it (2, 0.25), segment-to-next of point 0 = **LINE**
   - Add a point (3, 0.25), segment-to-next of the (2,0.25) point = **HOLD**
   - [ ] Canvas shows a ramp 0→0.25 then a flat line at 0.25
3. **Draw on canvas** — click empty space to add a point; **drag a dot** to move it; **right-click a dot** to delete
   - [ ] Dragging updates the X/Y in the sidebar live; readout shows coords
4. **Segment types** — select a row, change its **To-next** type to SINE, set Cycles/Amplitude → [ ] canvas shows the sine riding that interval
5. **Undo/redo** — **Ctrl-Z** reverts the last add/move/type change; **Ctrl-Y** reapplies
6. **View** — **Fit All**, **Zoom +/-** (zoom in far enough to grab a single point), **Periods: 2** shows the repeating output, **Time unit** (µs/ms/s) rescales the X axis; the header shows "period = \<span\>\<unit\> = \<freq\> Hz" and updates as you move the last point
7. **Save to Library** as `bench_edit` → [ ] `presets/arb/bench_edit.csv` **and** `bench_edit.recipe.json` exist
8. Close + reopen the editor (or **Load** `bench_edit`) → [ ] the **segment list repopulates** (re-editable, not just a flat curve)
9. **Send to CH 1**, **Upload && Select** → the editor DERIVES the channel frequency from the X span (e.g. a 1 ms span → 1 kHz) and sets amplitude from full-scale; channel panel shows ARB + name + the derived freq/amp; on the **scope** the output period = the X span, shape matches the editor (use Periods=2 as the expected repeating view). Also try **Send to CH 2**.
10. **Import CSV** (a value-column file) → [ ] becomes an editable LINE-anchored approximation you can tweak
11. Save a **channel preset** referencing `bench_edit`, reload → [ ] select-only loads the named arb

---

## M. SLDEA telemetry sidecar — DRY-RUN smoke (PR #218, issues #157/#189)

> **No high voltage is involved in this section.** A dry run never
> commands the signal generator, so the app puts no control voltage into
> the Trek. Leave the HV off. This is the only thing gating whether
> `telemetry.csv` can be trusted, and it needs no HV training to run.

**Setup:** the **Linux** bench PC (instrument control does not work on
Windows), oscilloscope connected and powered, Trek/HV off. ~20 min.
Launch: `.venv/bin/python gui.py`

1. **Oscilloscope** tab shows **Connected** — [ ] if not, stop here; without a scope there is no telemetry to test
2. **SLDEA Test** tab → find the **📈 Scope kV/µA log (telemetry.csv)** box
   - [ ] **Enabled** is ticked and **Rate (Hz)** reads `2`
3. Make the run short so this takes minutes, not an hour: **Start 0**, **End 1**, **Step 0.5**, **Ramp 2**, **Landing 10**
   - [ ] the summary line under the fields shows a total well under two minutes
4. **The `DRY RUN — HV OFF` checkbox stays TICKED.** The run button must read **▶ Run (DRY)** in amber
   - [ ] if it reads **▶ Run — LIVE HV** in red, re-tick the box — do not continue
5. Press **▶ Run (DRY)** and let it finish. The run log's first line is `run dir: …` — that folder is what everything below refers to
6. Open the run folder:
   - [ ] `telemetry.csv` sits beside `data.csv`
   - [ ] its first line is exactly `t_s,timestamp,nominal_kV,measured_kV,measured_uA,v_status,i_status,event`
   - [ ] rows land about twice a second, and nearly all have a `measured_uA`
   - [ ] `measured_kV` is filled on roughly every **other** row, blank with `v_status=skipped` in between — **this is by design**, not a fault
   - [ ] there is one row per photo whose `event` names the frame, e.g. `snap s01 post-ramp SLDEA_s01_…png`
   - [ ] `setup.txt` contains a `--- Telemetry ---` section
   - [ ] `data.csv` still has its usual 15 columns, unchanged from any earlier run
7. In the run log, find the last line starting `telemetry:` — it reads something like
   `telemetry: 118 samples, 1.94 Hz achieved (target 2), max gap 0.6 s, 59 with kV -> telemetry.csv`
   - [ ] the achieved rate is **1.4 Hz or better**
   - [ ] the line does **not** contain `SLOW DISK`
   - [ ] there is no `⚠ telemetry ran below its 2 Hz target` warning after it

**If something is off, this is the interesting part — write down what you
saw rather than retrying:**

- `SLOW DISK (… s worst write)` → the output directory is on the lab
  share and it stalled. **Note the worst-write number** — that is exactly
  the case desk testing cannot reproduce, and the reason the throttle
  exists. Worth re-running once with the output dir set to local disk to
  confirm that is the cause.
- achieved rate below 1.4 Hz → note the number and the `max gap`.
- no `telemetry.csv` at all → the run log will say why
  (`telemetry log could not be opened …` or `NO SCOPE`).

**Send back:** `run.log`, `data.csv`, `telemetry.csv` and `setup.txt` from
the run folder. Skip `frames/` — the four files are a few kB. The run
folder can be deleted afterwards; it is a rehearsal, not data.

## N. SLDEA watchdog probe — the numbers #189 is blocked on (no HV)

> **Scope only, HV off.** The script never opens the signal generator. A
> quiet 0 kV rig is the condition being measured — a live one would
> invalidate the result.

```
.venv/bin/python bench/test_sldea_watchdog_probe.py --ich 3 --vch 2
```

- [ ] adjust `--ich` / `--vch` if the Trek monitors are on other channels (they are whatever the SLDEA tab's *I_Out / V_Out scope CH* fields say)
- [ ] it prints three sections and writes `sldea_watchdog_probe.txt` + `.json`
- [ ] **send both files back** — section A decides the trip level for the peak-reading watchdog, section C decides how much driver work increment (3) needs

Runs in about a minute and changes nothing on the scope. `--selftest`
runs it against a synthetic scope with no instruments attached, if you
want to see the output shape first.

## O. SLDEA live-run verification — ⚡ REQUIRES HV ⚡ (#159, #195, PR #218)

> **This section energizes the Trek to real kV.** Only for someone
> trained and authorized on that rig. Two rules: instrument control is
> **Linux-bench-only**, and a live run must be ended with **■ Abort** —
> closing the app only attempts a best-effort ramp.

This verifies #159 and finishes the telemetry smoke. Sections M and N do
not depend on it and should be done first.

1. Same short profile as §M, but untick DRY RUN → button reads **▶ Run — LIVE HV** (red)
2. The **scope monitor check** runs first. If it reports a problem it offers **"Fix it automatically"**
   - [ ] take the automatic fix — it sets scale, position, attenuation and coupling on both monitor channels
   - [ ] note what the dialog said it was fixing (this is the #159 evidence)
3. Confirm the **Energize HV?** prompt, then watch the run log
   - [ ] a `watchdog baseline … µA` line appears before the ramp
   - [ ] `measured_kV` in `data.csv` tracks `nominal_kV` for the **whole** ramp — no blank tail (that was the 07-29 dropout)
4. **■ Abort** partway through
   - [ ] the ramp goes to 0 promptly and the log says `aborted`
   - [ ] `telemetry.csv` is complete up to the abort
5. If anything trips the watchdog, keep everything — the run folder is then the first live-recorded breakdown.

## P. SLDEA fiducial contrast ring — the one-visit experiment (`#194`) — ⚡ P3–P6 REQUIRE HV ⚡

> **P1 and P2 are dry (HV off) and they come first on purpose** — they are
> the two cheap checks that can kill the whole experiment, and running
> them after the Trek is up wastes the visit. **P3 onward energizes to
> 10 kV**: authorized operator, Linux bench, and a live run is ended with
> **■ Abort**, exactly as §O.
>
> **Never a metallic, silver, graphite or otherwise conductive ink.** The
> ring lands *on* the electrode boundary; a conductive one is a
> breakdown path at 10 kV and a second electrode in the measurement.
> Water-based pigment paint pen only. If the pen's barrel does not say
> what it is, do not use it.

**What this gates.** Whether low-CNT / transparent devices
(`P3_7_2.3mL_20260729` and anything cast like it) are measurable *at
all*, and how much of `#198` is left to do. It is an experiment, not a
regression check: **no app change is involved and none is needed.** The
detector measures an ink step at the electrode boundary — it has no
opinion about whether that ink is CNT or pigment.

### P0. The numbers the ring has to clear

A ring only helps if it clears the detector's own gates. These are the
gates, in the shipped code:

| Gate | Where | Rule |
|---|---|---|
| Resting-disc step floor (the px→mm anchor) | `sldea_edge.py:3293` | a ray is kept only if `median(outs) - median(ins) >= 4.0` gray, and **≥ 40 of 360 rays** must survive (`sldea_edge.py:3301`) |
| Responding-disc adaptive cut (`disc-fit`) | `sldea_edge.py:2254` | `cut = max(3.0, 0.35 * median(step))` over the rays that already cleared a `> 2.0` gray pre-filter (`sldea_edge.py:2249`); needs ≥ 40 points and ≥ 90 open sectors (`sldea_edge.py:2274`) |
| Audit boundary (the accept/refuse cross-check) | `sldea_edge.py:3016` | the same `max(3.0, 0.35 * median(step))` rule |
| Contrast term inside `conf` | `sldea_edge.py:2310` | `contrast = median(step) / 12.0`, clipped to 1 — **12 gray levels saturates it**; it is 0.30 of `conf` (`sldea_edge.py:2314`) |

Measured, not assumed:

- **`P3_7_2.3mL_20260729` fails on the first gate.** Running the shipped
  `baseline_disc` on its baseline frame returns the refusal *"only 19 of
  360 radial rays found a clean dark→light ink step (need 40) — the disc
  edge is too faint"*. That is the whole of `#194` in one sentence, and
  it is why the run's `sldea_diag.txt` header reads
  `resting disc : NOT FOUND` and its mm figures fall back to an
  *activated* frame.
- **A device that works clears it comfortably.** `P3_2_2.5mL_20260728`
  keeps 204 edge points at conf 0.871, and its per-ray step measured at
  the fitted centre has **median ≈ 11.7 gray** (p25 8.3, p75 14.6).
  `P3_6_2.5mL_20260729`: 178 points, median ≈ 7.0 gray.
- **Sensor noise on these frames is σ ≈ 3.15 gray levels**
  (`P3_7`'s own `sldea_diag.txt`, border-band upper bound). So the 4.0
  floor is only ~1.3 σ — passing it barely is not passing it.

**Therefore the ring must produce a sustained dark→light step of ≈ 12–25
gray levels, uniformly around the full circumference.**

- **≥ 12** because that saturates the contrast term at
  `sldea_edge.py:2310`, sits at ~4 σ of the measured sensor noise, matches
  the best working device in the corpus, and leaves margin against `#193`:
  at the worst photometric gain that campaign measured (0.71) a 12-gray
  step still reads 8.5 — twice the 4.0 floor. At `P3_7`'s actual step
  there is no margin at all, which is why `#193` and `#194` bind together
  on exactly these devices.
- **Not much above ~25, and uniformity beats depth.** The cuts at
  `sldea_edge.py:2254` and `:3016` are a *fraction of the scene's own
  median step*, so a very dark but patchy ring raises the median and
  therefore raises the cut, and the thin or skipped arcs of that same
  ring then fall below it and are discarded. Worked example: a ring
  stepping 40 gray over three quarters of the circumference sets
  `cut ≈ 14`, which throws away every ray on the faint quarter — and, on
  the control device in P5, every genuine CNT ray too. **A patchy 40-gray
  ring is worse than an even 12-gray one.** Draw it in one continuous
  pass, not in touch-ups.

### P1. Solvent compatibility — sacrificial device, no HV, ~30 min

Do not put a pen on a device you care about until this passes.

1. Take a **sacrificial device** — same membrane and same cast as the real
   ones, no data value.
2. Seat the **16 mm laser-cut application mask** over it (the same mask
   that anchors the diameter, `SLDEA_MEASUREMENT.md` §2.4) and draw the
   ring against the mask edge in **one continuous pass**. The mask is
   what makes the ring concentric with the electrode boundary by
   construction — do not freehand it.
   - [ ] mark the **low-field side** if the build allows it
3. Lift the mask, wait **15 minutes**, then inspect under the bench lamp:
   - [ ] no swelling, blistering, wrinkling or tackiness along the ring
   - [ ] no bleed — the line has not crept outward into the membrane
   - [ ] the membrane still snaps back when gently prodded (no local softening)
4. If any of those fail: **stop, write down which pen and which symptom,
   and end the section.** A different pen is a different experiment and
   needs P1 again from the top.
5. Re-inspect this device **24 h later** and photograph it. Slow solvent
   attack will not show in 15 minutes, and the answer matters even
   though it arrives after the visit.

### P2. Does the ring actually clear the floor? — DRY RUN, HV off, ~15 min

This is the gate that decides whether the HV is worth switching on. It
uses the §M dry-run mechanic, so it commands nothing.

1. Mount the ringed sacrificial device on the rig exactly as a real run,
   camera framed as usual.
2. **Webcam** tab: **Stabilize (pin gain 0)**, then **🔒 Apply & Lock**
   (`#193` — every gray level of the margin above matters here)
   - [ ] note the exposure/gain the Stabilize step landed on
3. **SLDEA Test** tab, **DRY RUN — HV OFF ticked**, button amber
   **▶ Run (DRY)**. Short profile: **Start 0, End 1, Step 0.5, Ramp 2,
   Landing 10**. Note the `run dir:` line.
4. Analyse it:
   ```
   .venv/bin/python sldea_diag.py RUNDIR
   ```
5. Read the **`resting disc :`** line in the header it prints:
   - [ ] it reads `diam … px … conf …`, **not** `NOT FOUND`
   - [ ] `conf` is **≥ 0.80** (`P3_2` reads 0.871, `P3_6` 0.827)
   - [ ] `circ` **≥ 0.97** and `fill` **≥ 0.85**
   - [ ] the diameter is within ~2 % of what the same rig gives on a
         standard device — the ring is on the 16 mm mask circle, so it
         must land where the CNT edge lands, not a pen-width outside it
6. Open `sldea_diag_contact.png` and look at the drawn outline:
   - [ ] the outline sits **on** the ring, all the way round
   - [ ] no arc where the outline jumps off to a shadow or the mask witness mark

**If the ring does not clear this, do not energize.** Write down the
`resting disc` line verbatim, keep `sldea_diag.txt`/`.json`/`_contact.png`,
and stop — that is a complete and useful negative result, and it costs no
HV time. A darker or more even pen is the retry, not more voltage.

### P3. Dielectric check at 10 kV — sacrificial device, ~15 min

Now the ring is proven visible, prove it is electrically inert. Still the
sacrificial device — this is the step that is allowed to destroy one.

1. Untick DRY RUN (button reads **▶ Run — LIVE HV**, red). Take the
   scope-monitor auto-fix if it offers one, as §O.
2. Profile: **Start 0, End 10, Step 0.5, Landing 15** — a fast climb, the
   point is the current, not the areas.
3. Watch the run log and the µA:
   - [ ] the `watchdog baseline … µA` line appears before the ramp
   - [ ] **no confirmed breakdown flag** at any level
   - [ ] `measured_uA` stays within **±20 µA** of the run's own median for
         the whole climb. That is the shipped
         `breakdown_dev_ua` (`sldea_edge.py:95`), ground-truthed
         2026-08-04: real events sustain 26.5–208 µA of deviation,
         false/borderline stay ≤ 14.6
   - [ ] compare against a bare device on the same rig — if none is at
         hand, `P3_2`/`P3_6`'s `data.csv` is the reference
4. Then look at the device:
   - [ ] no arc track, pinhole or scorch **along the ring**
   - [ ] the ring has not migrated, smeared or darkened

**Any of these fails ⇒ the ring is not dielectrically safe with that pen,
and P4/P5 do not happen.** Keep the run folder — a ring-induced breakdown
is the single most valuable frame set this section can produce.

### P4. The CONTROL — a normal-contrast device, bare then ringed, ~55 min

**This is the step the experiment cannot be read without.** Without it
there is no way to separate *"the ring helped"* from *"the ring changed
everything"*: a low-contrast device that starts working after being
marked proves nothing on its own, because the low-contrast device has no
before-picture worth comparing to.

Same device, twice, so the comparison is not device-to-device:

1. **Bare pass.** A standard 2.5 mL device, no ring, full ramp but coarse:
   **Start 0, End 10, Step 0.5, Landing 60** (~22 min). The control is
   about agreement, not resolution.
   - [ ] `setup.txt` carries `Ink concentration: 2.5 mL` and the nominal
         16 mm diameter
   - [ ] rename the run folder to end `_CTRL_bare` before touching the device
2. **Ring it in place if you can.** Mask on, one pass, same pen as P1.
   Not moving the device between passes removes the largest confound
   there is; if it must come off the rig, say so in `NOTES.txt`.
3. **Ringed pass.** Identical profile, identical camera settings (do not
   re-Stabilize between passes — that would change the photometry you are
   trying to hold still).
   - [ ] rename to end `_CTRL_ring`
4. Compare the two, at the desk if need be:
   - [ ] **`baseline_disc` diameter agrees within ~0.4 %** between passes —
         that is the auto-verified anchor's own residual
         (`SLDEA_MEASUREMENT.md` §2.1a), and the resting geometry is the
         thing a ring is most likely to shift
   - [ ] **A/A₀ expansion ratios agree within the ±0.8 % area budget**
         (`SLDEA_MEASUREMENT.md` §2.1/§2.5). Compare **ratios, not
         absolute areas** — `#194` caveat 3 is right that the ring
         redefines the boundary convention from "CNT half-height edge" to
         "marker-ring edge", and ratios are immune to that
   - [ ] `disc-fit` still **wins** on the ringed pass at a comparable rate,
         and the frames-needing-review count has not gone up
   - [ ] the `nostep_pct` figure from the boundary audit has not risen —
         a rise is the `sldea_edge.py:3016` cut-raising failure mode from
         P0, i.e. the ring is too dark or too patchy

> A second ramp on one device is not perfectly identical to the first
> (viscoelastic settling, and any partial damage from pass 1). That is
> why the acceptance is on the **resting diameter** and on **ratios**,
> both of which survive it, rather than on absolute areas.

### P5. The TEST — the low-contrast device, ~45 min

1. A device cast at the low concentration that motivated this
   (**2.3 mL**). If `P3_7_2.3mL_20260729` itself is still sound, use it —
   its bare `sldea_diag.txt` already exists as the before-picture, which
   no fresh device can give you.
2. Ring it, mask-guided, one pass.
3. Full standard profile — the same one `P3_7` ran: **Start 0, End 10,
   Step 0.25, Ramp 5, Landing 60** (~43 min), so the result is
   corpus-quality and not just a demo.
4. Then:
   ```
   .venv/bin/python sldea_diag.py RUNDIR
   ```
   - [ ] `resting disc :` is **found** (it was `NOT FOUND` on `P3_7`)
   - [ ] the `[MED ] No trustworthy resting-disc trace` verdict is **gone**
   - [ ] frames needing review is well under 48/48, and median confidence
         is above 0.00 — both were pinned at the failure value on `P3_7`
   - [ ] `disc-fit` appears in the `method` column instead of only
         `GATED` / `diff-lo` / `tex-ratio`
   - [ ] area grows with voltage instead of the 44 % of steps that went
         backwards
5. If the wrinkle wash-out band still refuses, **note which kV levels** —
   that is the number `#198` is sized on.

### P6. Send back

Per run folder, these five and no frames (a few hundred kB total):
`data.csv`, `setup.txt`, `run.log`, `sldea_diag.txt`, `sldea_diag.json`.
Plus `sldea_diag_contact.png` and `sldea_diag.png` for the P2, P4-ringed
and P5 runs — the contact sheet is the one thing no residual can stand in
for. Plus `edge_labels.json` if any frame was traced in Edge Review.

Also send, once:

- [ ] a **`NOTES.txt`** written by hand into each run folder — `setup.txt`
      has no free-text field, so the ring is otherwise unrecorded. State:
      pen make and model, "water-based pigment", mask-guided single pass,
      which side, dwell time before the run, and for P4 whether the device
      came off the rig between passes
- [ ] the **15-minute and 24-hour photos** of the P1 sacrificial device
- [ ] the P2 `resting disc :` line verbatim, and the exposure/gain
      Stabilize landed on
- [ ] run folders named `…_CTRL_bare`, `…_CTRL_ring`, and the P5 test run
      by the corpus convention (`DEVICE_CONCENTRATION_DATE`)

### What each outcome means for `#198`

- **P4 clean and P5 recovers the ramp** → transparent devices are
  measurable with a $3 pen, and the wrinkle wash-out band shrinks to
  whatever the ring did *not* fix. `#198`'s only claimed unique win is
  that band, so it shrinks by the same amount — likely to a nice-to-have,
  and worth re-scoping before any label work starts.
- **P5 recovers the resting disc but the wash-out frames still refuse** →
  the calibration anchor is fixed (which alone rescues `P3_7`'s mm
  figures) but `#198` keeps its niche intact and should proceed as
  written.
- **P4 perturbs the control** (diameter or ratios outside the gates
  above) → the ring is not a free win, and `#198` gets *more* important,
  not less, because there is then no cheap physical fix.
- **P1, P2 or P3 fails** → `#194` is answered *no* on physical grounds
  and `#198` is unblocked immediately at full scope. This is why P1–P3
  are cheap and come first.

---

**Pass =** every box ticked. Anything off: note section letter + what the applied readout / front panel / scope showed.
