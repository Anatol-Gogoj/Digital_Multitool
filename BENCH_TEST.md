# Bench test checklist — signal gen (§A–§L, historical) + SLDEA telemetry/watchdog (§M–§O) + fiducial-ring experiment (§P, current) + SLDEA Run start gate (§R) + SLDEA camera pre-flight image gate and override (§S, gates its PR)

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
> on CH1" → "Send to CH:" + "Upload & Select"), direct upload is now
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
9. **Send to CH 1**, **Upload & Select** → the editor DERIVES the channel frequency from the X span (e.g. a 1 ms span → 1 kHz) and sets amplitude from full-scale; channel panel shows ARB + name + the derived freq/amp; on the **scope** the output period = the X span, shape matches the editor (use Periods=2 as the expected repeating view). Also try **Send to CH 2**.
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

**The camera must see a lit scene (added 2026-10-02).** A run now stops
itself after two frames when its baseline picture is flat (§S), and a DRY
run does the same. Either light the scene until the pre-flight's numbers
line reads `contrast 20 gray levels` or more, or unplug the camera and
answer **Yes** to the pre-flight's `No camera frame available` question.
Since 2026-10-03 a third way is the override: **⚠ Start anyway (no
picture)** then **Yes** at the pre-flight, which is written to `run.log`
and `setup.txt` (§S). A camera that shows a picture at the pre-flight
and then gives no baseline frame stops the run too (§S7).

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

## N. SLDEA watchdog probe — the numbers #189 and ▶ Run's monitor check are blocked on (no HV)

> **Scope only, HV off.** The script never opens the signal generator. A
> quiet 0 kV rig is the condition being measured — a live one would
> invalidate the result.

### N1. The probe, about a minute

```
.venv/bin/python bench/test_sldea_watchdog_probe.py --ich 3 --vch 2
```

- [ ] adjust `--ich` / `--vch` if the Trek monitors are on other channels (they are whatever the SLDEA tab's *I_Out / V_Out scope CH* fields say)
- [ ] it prints three sections and writes `sldea_watchdog_probe.txt` + `.json`
- [ ] **send both files back** — section A decides the trip level for the peak-reading watchdog, section C decides how much driver work increment (3) needs. Since 2026-09-24 section C also lists each monitor channel's coupling and on/off reply

Runs in about a minute and changes nothing on the scope. `--selftest`
runs it against a synthetic scope with no instruments attached, if you
want to see the output shape first.

### N2. What the scope answers when I_Out is blind, about 5 minutes (added 2026-09-24)

**Why.** Before a LIVE run, ▶ Run's monitor check reads each monitor
channel's scale, attenuation, position and offset, and nothing else. So
an I_Out channel left on AC coupling (a bench profile can do that), an
I_Out channel switched off, or a scope left stopped all pass the check.
The breakdown watchdog would then read about 0 µA, or one frozen record,
for the whole run. That is what we expect; nobody has checked it on this
scope. The check can only learn to catch these once we know what the
scope replies in each state, so this step records it. The app does not
change until the replies are in.

> The walk has **you** put I_Out into exactly the states a LIVE run must
> never start in. At the end it reads the scope again. It prints
> `RESTORED` only when both monitor channels read DC-coupled and on and
> the scope acquiring, through queries the walk saw follow the front
> panel, and the watchdog's own read is a readable current.

**Setup:** as N1: scope connected, HV off. Set the scope up the way a
LIVE run uses it: the I_Out and V_Out channels DC-coupled and on, and the
scope acquiring (Run/Stop lit green). Then write down the **trigger
mode** (Auto or Normal) and the **trigger source** channel shown on the
screen.

```
.venv/bin/python bench/test_sldea_watchdog_probe.py --ich 3 --vch 2 --walk
```

Use the same `--ich` / `--vch` as N1. It asks for one change at a time.
Make each change **on the scope's front panel** and press Enter. The
probe reads the scope after each one. The table assumes I_Out is on CH3:

| Step | What you do | What that step checks |
|---|---|---|
| 1 `normal` | nothing, if the scope is set up as above | the replies in normal use, which every later step is compared with |
| 2 `i_ac` | set CH3 (I_Out) to **AC** coupling | did `CH3:COUPLING?` change |
| 3 `i_off` | set CH3 back to DC, then turn CH3 **off** | did `SELECT:CH3?` change (and `DISPLAY:GLOBAL:CH3:STATE?`, a second on/off query) |
| 4 `stopped` | turn CH3 back on, then press **Run/Stop** so the scope stops | did `ACQUIRE:STATE?` change |
| 5 `restored` | put it back: CH3 DC and on, and press **Run/Stop** if the scope shows Stopped | that the scope is ready for a LIVE run again |

At every step it records, word for word, what the scope replied to:

- `CH<n>:COUPLING?`, `SELECT:CH<n>?` and `DISPLAY:GLOBAL:CH<n>:STATE?`,
  for both monitor channels;
- `ACQUIRE:STATE?`, `ACQUIRE:STOPAFTER?`, `TRIGGER:STATE?`,
  `TRIGGER:A:MODE?`, the trigger type and source, and the timebase;
- six `MEASUREMENT:IMMED:VALUE?` reads of MEAN on I_Out, taken 0.5 s
  apart as the watchdog takes them. Beside each is what the watchdog
  would make of it: a real current, the off-screen sentinel (which it
  counts as over-trip), or unreadable.

Check:

- [ ] each step's section says the query it targets **moved**. If one says `did NOT move` while the screen shows the change, that is a finding: write down which
- [ ] the summary's list **Which queries follow the front panel** is the main result: a query counts only if it changed when you made the change it reads. Only those can be used by the check this step is for
- [ ] the first table in the file has one column per step. Check it against what the screen showed at each step
- [ ] the walk ends with `RESTORED`. **Even then, look at the screen** before anyone starts a LIVE run: both monitor channels DC-coupled and on, and the scope running, not in Single. How to handle the other endings:
  - `NOT READY FOR A LIVE RUN`: fix what it names on the front panel and press Enter. It reads the scope again, and keeps asking until it is right or you type `q`
  - `NOT CONFIRMED`, `NOT CHECKED` or `INTERRUPTED`: the probe could not check everything itself. Check each thing it names on the screen yourself before anyone starts a LIVE run
  - if it insists on something the screen contradicts, type `q` and write that down
- [ ] **send back** `sldea_watchdog_probe_walk.txt` + `.json`, the trigger mode and source you wrote down, and anything the screen showed that the file cannot: a message when CH3 went off, or a front panel that did not respond while the walk waited

**The trigger mode.** `TRIGGER:A:MODE?` decides whether a channel the
run does not read can freeze it. The walk's summary says which of these
this scope is in:

- **AUTO:** the scope acquires with or without a trigger, so no channel's
  settings can stall it.
- **NORMAL:** the scope acquires only on a trigger. If the trigger source
  is a channel the run does not read, re-coupling that channel or turning
  it off freezes every read, just as Stop does. Nothing locks those
  channels during a run, not even with #337. If the source is I_Out
  itself, a quiet I_Out that never crosses the trigger level freezes the
  reads without anyone touching anything. If it is AUX or a digital
  channel, the scope waits for that input, and if nothing drives it, the
  reads freeze too.

**At 0 kV, AC coupling may hardly change the number.** At rest, I_Out's
DC level is just the rig's standing offset: −16 µA through the 07-29
campaign, 0.9 µA on the 07-23 breakdown runs. So the AC-coupled MEAN can
land close to the DC-coupled one. What that step proves is the
`CH3:COUPLING?` reply, and that the value still comes back as an ordinary
number the watchdog would accept.

`--selftest --walk` runs the whole walk against a synthetic scope, if you
want to see the prompts first.

## O. SLDEA live-run verification — ⚡ REQUIRES HV ⚡ (#159, #195, PR #218)

> **This section energizes the Trek to real kV.** Only for someone
> trained and authorized on that rig. Two rules: instrument control is
> **Linux-bench-only**, and a live run must be ended with **■ Abort** —
> closing the app only attempts a best-effort ramp.

This verifies #159 and finishes the telemetry smoke. Sections M and N do
not depend on it and should be done first. The camera rule in §M's setup
holds here too (added 2026-10-02): a lit scene with `contrast 20 gray
levels` or more at the pre-flight, or no camera at all, otherwise the run
stops itself at its baseline frame.

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

## Q. SLDEA video beside the snapshots — DRY-RUN smoke, no HV (2026-09-23)

> **DRY RUN only** — the camera path is what is under test, not the Trek.
> Linux bench PC with the DFK attached, ~20 min. **The video branch must
> not merge until this section passes** (CLAUDE.md: never ship
> bench-unverified instrument I/O).

**What this gates.** A video run holds the DFK's `v4l2-ctl` Bayer stream
open for the WHOLE run on the recorder's own threads, where the stills
path only ever opened it for one grab at a time. The stills then come off
that stream instead of one-shot grabs, and the file is encoded with FFV1,
which must exist in the bench's OpenCV wheel. None of that could be tried
at a desk: the desk tests use a fake camera, and FFV1 was measured on a
Windows OpenCV 5.0 build, not the bench's 4.13.

- [ ] **Q1.** `python sldea_video.py --selftest` on the bench PC prints
  `FFV1 lossless round trip: OK`. If not, stop: the bench wheel has no
  encoder, and the tab will offer "Run WITHOUT video" instead. Since
  2026-10-06 it also prints `FFV1 lossless round trip at 1920 x 1080: OK`,
  and first a line `OpenCV …, avcodec …`. **Note the avcodec version**:
  58.x is FFmpeg 4.x, which reads 1 KB past every gray frame (on Linux a
  crash if that memory is unmapped; `ffmpeg_safe` keeps the read inside
  the recorder's buffer), and 59 or later does not
  (SLDEA_DECISIONS 2026-10-06, the codec at the camera's own size).
- [ ] **Q2.** SLDEA tab → 🎥 **Record**, fps **1**. The size line shows
  roughly 2.5 GB for the default 0→10 kV profile. Set a short profile
  (0→2 kV, 1 kV steps, 20 s landings) and press **▶ Run (DRY)**.
- [ ] **Q3.** Within ~5 s the run log says `video: recording 1 fps to
  local disk (…)` — **not** `delivered nothing … NO recording`. Just
  before it: `video: FFV1 checked at 1920 x 1080, the stream's own size:
  lossless` (2026-10-06). A `run stopped before any HV: the video check
  at the camera's frame size failed (…)` line instead means this
  camera's size fails on this OpenCV: note the size and the reason.
- [ ] **Q4.** Every `data.csv` row has a frame file. Open the baseline PNG
  next to one from a **stills-only** dry run of the same scene and
  settings: the same exposure, the same colour, no magenta checkerboard
  (the Bayer-phase trap, README), mean grey within ±2 levels.
- [ ] **Q5.** The end of the log: `video: N frames recorded at ~1.00 fps`
  with **no** `DROPPED`, then `video.mkv and video_frames.csv are in the
  run folder`. `video.mkv` is ~1 MB per frame.
- [ ] **Q6.** `video.mkv` plays (VLC or `ffplay`): grey, the right way up,
  the same field of view as the PNGs, and no frozen stretch.
- [ ] **Q7.** During a run, Webcam tab → **Start Preview** is refused with
  *"Camera in use — SLDEA run"* (as are Apply & Lock, Stabilize,
  Auto-expose, grey-world and the timed/interval/stepped captures).
- [ ] **Q8.** Start another dry video run and **■ Abort** it mid-landing:
  the tab frees at once, and the log still ends with the video lines
  (the move runs after the run, on its own thread).
- [ ] **Q9.** Tick **then detect edges on every frame** and let a run
  complete: `video_edges.csv` and `video_edges.png` appear. Where a video
  frame and a still share a moment, their `area_px` agree within the ±2 %
  band (open Edge Review on the stills to compare).
- [ ] **Q10.** Loop health: in `telemetry.csv` (scope connected) the row
  spacing is still ~0.5 s, as in a stills-only dry run — the stream must
  not starve the loop that runs the watchdog. `top`: the app under ~50 %
  of one core.
- [ ] **Q11.** The real stream rate: during a video run,
  `v4l2-ctl -d /dev/video0 --get-parm` reports ~10 fps (and the log's
  `stream N fps` agrees); **after** the run, check it again and note
  whether the setting persisted. A UVC format call can reset the rate,
  and a rate that persists would slow later one-shot grabs.
- [ ] **Q12.** Camera unplugged mid-run (dry): the log says `reopening
  (attempt n)`, and once replugged, `camera stream reopened`. The stills
  in between log NO FRAME; the ones after are filed normally.
- [ ] **Q13.** Gain over a long stream: a **≥ 40-minute** dry video run
  of an unchanging scene. Compare the baseline still with the **last**
  still (mean grey within ±2 levels), and look for any `gain` drift in
  the log. Every still re-stamps the full lock, gain included, as a
  one-shot grab does; this checks that it holds.
- [ ] **Q14.** ⚡ **LIVE, but with the Trek's HV output disabled** (HV
  enable off / interlock open; SG CH output on the scope instead):
  - Run a short profile with **Record on**, and **■ Abort** mid-ramp.
    On the scope, the SG output reaches 0 V as fast as in the same
    abort with Record **off**. The shutdown order puts the SG first;
    this checks it.
  - Force a watchdog trip (§N's probe, or a low trip level with a
    resistor on I_Out). Time-to-0 V is no worse with Record on, and the
    breakdown frame is filed.
- [ ] **Q15.** Back to back: straight after a video run whose output dir
  is the **share**, start a LIVE-mode run (Trek HV still disabled). The
  tab asks *"A video is still being copied"*. Answer yes, and check the
  telemetry spacing stays ~0.5 s while the copy runs (throttled to
  40 MB/s).
- [ ] **Q16.** Review by exception (2026-10-06): after the Q9 run's video
  is in its folder, open it in Edge Review, calibrate, ▶ Detect Edges and
  💾 Save. The strip ends with *"video edges re-running in the background
  (…)"*, and within a minute or two `run.log` gains *"video edges:
  re-running after Save (…)"* then *"… N flagged for review against M
  accepted still(s) …; the video reads ±x % against the stills
  overall"*. Note N, M and x. Save again at once: the strip now says
  *"video edges are current"* once the first re-run has finished.
- [ ] **Q17.** 🎞 **Video review…** opens on the first flagged frame (or
  frame 0 when none is flagged). ← → step frames; N / P jump between
  flagged frames; the blue outline appears within about a second; A / R
  record a decision and move on, and `video_review.csv` gains a row.
  Close: `video_edges.png` is redrawn with the decision (diamond or
  cross). Note how long the outline takes to appear on this PC.

Record the date and the Q1/Q5/Q10/Q11/Q13/Q14/Q16/Q17 numbers in
`SLDEA_DECISIONS.md`.

---

## R. SLDEA Run start gate — a DRY look at the dialogs, Trek HV off (2026-09-23)

> **Keep the Trek's HV output OFF for this whole section.** The runs are
> DRY, but the stepped sweeps in steps 1 and 4 really write the signal
> generator: they are set to hold 0 V, and through an enabled Trek 1 V is
> 1 kV at the DEA, so a typo in the level would matter. The gate itself
> only ever withholds writes, so this is a look at the real dialogs, not
> a merge gate. The logic, including every LIVE-side check, is
> headless-tested in `tests/test_sldea_interlock.py`.

**Setup:** the Linux bench PC with the signal generator and camera
connected, and the Trek's HV output off. ~5 min. SLDEA tab: **Start 0**,
**End 1**, **Step 0.5**, **Ramp 2**, **Landing 10**, **SG CH: 1**, any
value in the **Electrode** box (an empty one asks its own question
first), and **DRY RUN — HV OFF** ticked. The camera must see a lit scene
(the pre-flight's numbers line reads `contrast 20 gray levels` or more;
added 2026-10-02): step 4 lets a run finish, and a run now stops itself
at a flat baseline picture (§S).

1. Webcam tab → Stepped capture: **SG CH 1**, levels `0`, dwell `120` → **Run sweep** (one 0 V level, held for two minutes)
2. SLDEA tab → **▶ Run (DRY)**
   - [ ] an error box titled **SLDEA — run blocked** names SG CH1 and says *Stop sweep*, with no question before it
   - [ ] the SLDEA tab's log pane shows `run refused — a stepped sweep is writing SG CH1, the run's channel`
3. Webcam tab → **Stop sweep**, then SLDEA → **▶ Run (DRY)**
   - [ ] the camera pre-flight opens, so the gate has cleared. **✖ Cancel** it
4. Webcam tab: **SG CH 2**, levels `0`, dwell `120` → **Run sweep**. Then SLDEA → **▶ Run (DRY)**
   - [ ] a question titled **Stepped sweep still running** names CH2, and **Enter** answers **No**: nothing starts
   - [ ] press ▶ Run again and answer **Yes**: the camera pre-flight opens. Start the run and let it finish. Some snapshots may log `NO FRAME` (the question warned about that), and the run folder's `run.log` has the line `run-anyway beside a stepped sweep on SG CH2`
   - [ ] afterwards, **Stop sweep** if the button still reads so

**Send back:** anything that differed, the wording of any box that read
badly, and the `run.log` from step 4.

## S. SLDEA camera pre-flight image gate: flat frame, baseline stop, settings warning, pre-flight override (2026-10-02, override and no-frame stop 2026-10-03)

> **Keep the Trek's HV output OFF for this whole section.** S4 and S7
> hold LIVE runs: the signal generator really drives its output, and
> through an enabled Trek 1 V of control is 1 kV at the DEA. With the
> Trek's HV disabled the control voltage goes nowhere. One LIVE run in S4
> is expected to stop itself about 3 s in; the other (the override) runs
> the whole 1 V staircase. **#348 merged on 2026-10-06 by the owner's
> decision, before this section ran: its boxes are tracked in issue
> #369.** The logic is headless-tested in
> `tests/test_sldea_preflight.py` and `tests/test_sldea_interlock.py`;
> this section is the half only the real camera, signal generator and
> dialogs can show.

**Setup:** the Linux bench PC with the signal generator and camera
connected, and the Trek's HV output off. A normal disc device under the
camera, lit as for a real run. BNC from SG CH1 to scope CH1 (1 MΩ,
20 mV/div for the stop, 0.5 V/div for the override staircase, timebase
as the bench has it) for steps S4 and S7. ~25 min. SLDEA tab: **Start
0**, **End 1**, **Step 0.25**, **Ramp 2**, **Landing 10**, **SG CH: 1**,
any value in the **Electrode** box, and **DRY RUN — HV OFF** ticked.
That profile has 10 frames (warm-up, baseline, two per landing) and
takes about 50 s when it runs to the end.

A **flat frame** below means the 2026-10-01 picture: on the Webcam tab
set `exposure_time_absolute` to `3` and `gain` to `0`, then **Apply &
Lock**. The preview goes to an even dark gray. A **good frame** is the
exposure you would normally run at (the disc clearly darker than the
paper), also with **Apply & Lock**.

A **covered start** below is the route to a flat baseline WITHOUT the
override: good frame locked, the pre-flight shows the good picture, press
**✔ Looks good — start run**, and at once cover the lens with a dark
card or its cap. The warm-up is shot about 0.7 s in and the baseline about
2 s in, so the baseline is flat. (Since #361, merged with #348 on
2026-10-06, the pre-flight shoots at the run's own settings, so the old
route, a typed but unlocked exposure of 3, now makes the PRE-FLIGHT frame
flat and lands on its gate instead. S5 checks what that dialog says now.)
Keep 🎥 **Record** unticked for S3 and S4: in a video run the baseline is
the first stream frame after its moment, up to 1.5 s later.

Since 2026-10-03 (owner decisions 12, 13 and 14) the **override** is one
mechanism: **⚠ Start anyway (no picture)** followed by **Yes** at the
pre-flight carries into the run, DRY or LIVE. The baseline picture is
still checked and its verdict logged, but it does not stop that run,
and `run.log` and `setup.txt` record the override. Without the override,
a baseline the camera gives **no frame** for stops the run the way a flat
one does, when the pre-flight had a camera (S7).

**S1. A normal frame starts normally**

1. Webcam tab: good frame, **Apply & Lock**. Go to the SLDEA tab
   - [ ] under the Run row a line reads `Camera for this run: exposure N, gain G, set on the Webcam tab`, with the Webcam tab's own numbers and no ⚠
2. **▶ Run (DRY)**
   - [ ] the pre-flight shows the disc, the verdict reads `exposure OK`, and the numbers line ends in `contrast NN gray levels` with NN at 20 or more
   - [ ] a line reads `Disc found: NNN px across, fit quality 0.NN` (or `Disc not found: ...` for a device that is not a disc; either is fine here)
   - [ ] the same `Camera for this run: ...` line is in the dialog, and nothing in the dialog is red
   - [ ] the button reads **✔ Looks good — start run** and **Enter** starts the run
3. Let it finish
   - [ ] the run completes as it always did, and `run.log` holds `camera pre-flight: mean ..., saturated ...%, contrast ... gray levels, focus ..., verdict OK` and `baseline picture check: contrast ... gray levels, saturated ...% - OK`

**S2. A flat frame is refused at the pre-flight**

4. Webcam tab: flat frame, **Apply & Lock**. SLDEA tab → **▶ Run (DRY)**
   - [ ] bold red text: `NO PICTURE: the frame is flat (contrast N gray levels). The disc is not visible. Raise the exposure or the light on the Webcam tab.`
   - [ ] a `Disc not found: ...` line under it
   - [ ] the button reads **⚠ Start anyway (no picture)**, the focus ring is on **✎ Adjust**, and pressing **Enter** does nothing at all
5. Click **⚠ Start anyway (no picture)**
   - [ ] a question titled **No picture in this frame** opens, says `the run will NOT stop itself on a flat baseline` and that `setup.txt records that you started anyway`, and **Enter** answers **No**: the pre-flight is still open and nothing started
6. **✖ Cancel**
   - [ ] the SLDEA log pane shows the pre-flight line ending `verdict FLAT` and then `run cancelled at camera pre-flight`

**S3. A flat baseline stops a DRY run, unless the pre-flight was overridden**

7. The stop. Covered start: **▶ Run (DRY)** → **✔ Looks good — start run**, then cover the lens at once
   - [ ] within about 3 s the run stops by itself: the status line turns red and reads `STOPPED: NO PICTURE in the baseline frame, nothing was measured (see Run log)`, and a box titled **Run stopped: no picture** opens
   - [ ] `run.log` holds, in this order: the pre-flight's `verdict OK` line, the `NO PICTURE ... STOPPING NOW.` line, `run stopped at the baseline frame. This was a DRY run: no voltage was driven.`, and `run aborted: 2/10 frames`
   - [ ] the run's `frames/` folder holds exactly the warmup and the baseline frame (the warmup may still show the disc if the card came late; the baseline must be dark)
   - [ ] the run's `setup.txt` has no `Pre-flight override:` line
8. The override. Webcam tab: flat frame, **Apply & Lock**. **▶ Run (DRY)** → **⚠ Start anyway (no picture)** → **Yes**
   - [ ] the run does NOT stop: it runs to the end (about 50 s), the status line ends green `complete — 10 frames`, and no **Run stopped** box opens
   - [ ] `run.log` holds, in this order: `operator started the run ANYWAY on a flat pre-flight frame (no picture): the baseline picture stop is OFF for this run`, then `pre-flight override: no picture. The baseline picture check still runs and its verdict goes to this log, but it will NOT stop this run.`, then (after the baseline snap line) the `NO PICTURE ... so the run CARRIES ON. Review this run by hand.` line, and `run complete: 10/10 frames`; `STOPPING NOW` appears nowhere
   - [ ] `setup.txt` holds exactly one line `Pre-flight override: no picture (the operator started anyway at the camera pre-flight; the baseline picture stop is off for this run)`, on its own right after the `--- Snapshots ---` block
   - [ ] `frames/` holds all 10 frames
9. Type the good exposure back in the box and **Apply & Lock**

**S4. A flat baseline stops a LIVE run, unless the pre-flight was overridden (Trek HV disabled)**

10. Check the Trek's HV output is OFF. Untick DRY so the box reads **⚡ LIVE — HV WILL BE DRIVEN**. Scope CH1 on SG CH1 at 20 mV/div, running
11. The stop. Covered start, 🎥 Record unticked: **▶ Run — LIVE HV**, answer the questions (Energize HV: Yes), then **✔ Looks good — start run** and cover the lens at once
    - [ ] the run stops within about 3 s exactly as in S3 step 7
    - [ ] afterwards the signal generator's CH1 output is OFF and its offset reads 0 V on the front panel
    - [ ] on the scope the control voltage never rose above 0.1 V (expected under 40 mV for well under a second: the first ramp is one loop tick old when the baseline is shot, and that tick is the same on every run)
    - [ ] `run.log` holds `run stopped at the baseline frame. The first voltage ramp had only just begun: the drive had been commanded to 0.0NN kV when the run stopped.`, and 0.0NN kV agrees with the scope (1 V of control is 1 kV)
    - [ ] `run.log` has no `FAILED TO ZERO` line
12. The override. Scope CH1 to 0.5 V/div. Webcam tab: flat frame, **Apply & Lock**. **▶ Run — LIVE HV**, answer the questions, then **⚠ Start anyway (no picture)** → **Yes**
    - [ ] the run does NOT stop: the scope shows the whole staircase (0.25, 0.5, 0.75 and 1.0 V of control, each held about 10 s) and the run ends `complete — 10 frames`
    - [ ] afterwards the signal generator's CH1 output is OFF and its offset reads 0 V: the ordinary end-of-run zeroing
    - [ ] `run.log` and `setup.txt` carry the same override lines as S3 step 8, `run.log` has no `STOPPING NOW` and no `FAILED TO ZERO`
13. Tick **DRY RUN — HV OFF** again. Type the good exposure back in the box and **Apply & Lock**

**S5. The settings warning appears when the Webcam entry differs from the lock** (rewritten 2026-10-06 for the #361 merge)

14. Webcam tab: good frame, **Apply & Lock**. Then type a DIFFERENT exposure that still gives a good picture (the good value plus about a third) and do **NOT** press Apply & Lock. Go to the SLDEA tab
    - [ ] the camera line reads `Camera for this run: exposure E, gain G, set on the Webcam tab` with your typed E, and under it, in amber, `⚠ The Webcam tab has LOCKED exposure N instead, so its live preview will NOT show what the run records (the pre-flight does). ...`
15. **▶ Run (DRY)**
    - [ ] the pre-flight picture is taken at the typed exposure (a little brighter than the Webcam preview was) and the verdict reads `exposure OK`
    - [ ] bold red text reads `⚠ The Webcam tab's fields differ from its lock: exposure E (locked: N). The Webcam preview uses the lock; this run uses the fields, as this picture does. ...`, and NO line says `This preview was NOT taken with the run's settings`
    - [ ] the button reads **⚠ Start anyway (the Webcam preview differs from the run)** and **Enter** does nothing
16. Click **⚠ Start anyway (the Webcam preview differs from the run)** (one click, no second question)
    - [ ] the run starts and runs to the end; `run.log` holds the `⚠ camera pre-flight: The Webcam tab's fields differ from its lock ...` line and `operator pressed: ⚠ Start anyway (the Webcam preview differs from the run)` before the start line
17. Webcam tab → **Start Preview**
    - [ ] the preview shows the LOCKED picture again although the box still holds E: the pre-flight and the run handed the Webcam tab's lock back
18. The old route lands on the flat gate now: type `3` (not locked) and **▶ Run (DRY)**
    - [ ] the pre-flight picture is FLAT (it is taken at exposure 3) and the dialog is S2's: **⚠ Start anyway (no picture)**, plus the fields-vs-lock sentence. **✖ Cancel**, then type the good exposure back in the box and **Apply & Lock**

**S6. Cancel leaves the camera as it was**

19. Good frame locked, preview stopped. In a terminal: `v4l2-ctl -d /dev/video0 --list-ctrls > /tmp/cam_before.txt`
20. SLDEA → **▶ Run (DRY)** → **✖ Cancel** at the pre-flight. Then `v4l2-ctl -d /dev/video0 --list-ctrls > /tmp/cam_after.txt; diff /tmp/cam_before.txt /tmp/cam_after.txt`
    - [ ] `diff` prints nothing (or only `gain`, if the firmware auto-gain moved it; note the two values)
21. Repeat with **✎ Adjust** instead of Cancel
    - [ ] the Webcam tab opens, its status still reads locked, and **Start Preview** shows the same picture as before the run

**S7. No baseline frame stops the run (decision 13, 2026-10-03)**

The pre-flight got a frame, then the camera gives the run none. The
pre-flight dialog is modal, so take the camera away while it is open,
from a terminal or by hand: `v4l2-ctl -d /dev/video0 --stream-mmap`
holds the device and streams until Ctrl-C (`ffplay /dev/video0` does the
same), or pull the camera's USB plug. Note which way was used.

22. Good frame locked, DRY ticked. **▶ Run (DRY)**: the pre-flight shows the good picture. With the dialog still open, take the camera away. Then **✔ Looks good — start run**
    - [ ] within about 3 s the run stops itself: the status line turns red and reads `STOPPED: NO BASELINE FRAME from the camera, nothing was measured (see Run log)`, and a box titled **Run stopped: no baseline frame** opens
    - [ ] `run.log` holds, in this order: the two snap lines ending `→ NO FRAME (camera busy? close the Webcam preview)` (warmup and baseline; the warmup may still have a frame if the camera went away late), then `NO BASELINE FRAME: the camera gave the pre-flight a picture but gave this run none for its baseline ... STOPPING NOW.`, `run stopped at the baseline frame. This was a DRY run: no voltage was driven.`, and `run aborted: 2/10 frames`
    - [ ] `data.csv` has two rows, `frame_file` empty on the baseline row; `frames/` holds at most the warmup
23. Give the camera back (Ctrl-C, or plug it in). The "no camera at all" case keeps its old behaviour: take the camera away BEFORE pressing Run this time, then **▶ Run (DRY)**
    - [ ] the pre-flight asks `No camera frame available ... Continue anyway?` (Enter = No). Answer **Yes**
    - [ ] the run goes on to the end with `NO FRAME` on every snap line, `run complete: 10/10 frames`, and no `STOPPED` status: this is the existing question, not the new stop
24. LIVE, Trek HV OFF, scope CH1 at 20 mV/div: untick DRY and repeat step 22 as **▶ Run — LIVE HV** (Energize HV: Yes)
    - [ ] the run stops within about 3 s; afterwards SG CH1 output is OFF and its offset reads 0 V; the control voltage never rose above 0.1 V; `run.log` names the commanded kV in the `run stopped at the baseline frame.` line and has no `FAILED TO ZERO`
25. Tick DRY again. The override covers this case too: flat frame locked, **▶ Run (DRY)** → **⚠ Start anyway (no picture)** → **Yes**, with the camera taken away while the question was open
    - [ ] the run does NOT stop: `run.log` holds `NO BASELINE FRAME ... so the run CARRIES ON. Review this run by hand.` and `run complete: 10/10 frames`
26. Give the camera back and restore the good frame (**Apply & Lock**)

**Send back:** the `run.log` from S1, S3 (both runs), S4 (both runs), S5
and S7 (steps 22 to 25), the `setup.txt` from S3 step 8, a photo of the
pre-flight in S2 and S5, the peak control voltage seen in S4 step 11 and
S7 step 24, the two `v4l2-ctl` listings from S6, and how the camera was
taken away in S7.

**Follow-up for this bench session, not in the PR (camera I/O):** make the
pre-flight frame use the run's own control set, so the picture approved is
the picture recorded. Proposed change in `gui.py` `_sldea_preflight`,
replacing the bare `frame = webcam.oneshot_rgb(spec, count=3)`:

```python
prev = dict(webcam.LOCKED_CONTROLS)
webcam.set_locked(dict(prev, auto_exposure=1, white_balance_automatic=0,
                       exposure_time_absolute=cam_exp, gain=cam_gain))
try:
    frame = webcam.oneshot_rgb(spec, count=3)
finally:
    webcam.set_locked(prev)
```

This is the overlay `_sldea_worker` already installs, stamped per grab by
`oneshot_rgb` itself (not in advance, which the firmware undoes in about
0.5 s), and undone on every exit so Cancel and Adjust keep the operator's
lock. It belongs inside the existing `if spec.get('device'):` branch, as
in the worker, and `preflight_report` is then handed the overlay as its
lock, so the "NOT taken with the run's settings" warning falls silent by
itself. These are questions for that later change, not boxes for this PR.
What the bench has to answer before it ships:

- With the S5 setup, is the pre-flight picture now the flat one, and does the `NO PICTURE` gate fire in the dialog?
- After **✖ Cancel** the device is left at the run's exposure until the next grab or preview re-stamps the lock. Is that acceptable, or must the lock be re-applied (`webcam.apply_locked(dev)`) on the way out? Repeat S6 with the change in.
- Does the `gain` control behave across the extra stamp (firmware auto-gain, bench 2026-07-24)?

---

**Pass =** every box ticked. Anything off: note section letter + what the applied readout / front panel / scope showed.
