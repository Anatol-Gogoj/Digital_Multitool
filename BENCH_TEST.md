# Bench test checklist — signal gen (§A–§L, historical) + SLDEA telemetry/watchdog (§M–§O, current)

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
2. **SLDEA Test** tab → find the **📈 Telemetry log (telemetry.csv)** box
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

---

**Pass =** every box ticked. Anything off: note section letter + what the applied readout / front panel / scope showed.
