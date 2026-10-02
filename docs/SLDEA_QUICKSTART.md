# SLDEA quickstart: from an unpowered rig to an exported plot

For a new student at the Linux bench PC. One full pass: camera, scope, dry run, live run, Edge Review,
plot. The physics and the error budget are in SLDEA_MEASUREMENT.md, not here.

How to read this page:
- Text in double quotes is copied from the app (a button, a dialog title, a log line) or from the repo
  file named beside it, minus the app's small pictures and long dashes ("Abort" has a square in front of
  it on screen). In log examples, u is the micro sign and -> the arrow.
- The box just below is the lab box; box item 3 is its item 3. "On file" means the 16 real runs reviewed
  for this page (2026-07-23 to 2026-10-01). This page describes main at commit 1eb85b2 (2026-09-24), read
  from the code. Nobody has walked a new student through it at the bench yet. Where the repo has no
  answer, it says so.

> **To be filled in by the lab before a new student uses this page**
>
> The code and the repo docs cannot answer these. Until a line is filled in, ask a trained person before
> you do that step.
>
> 1. Who may start a LIVE run? Must a second person be present? What training comes first?
> 2. Barrier or enclosure, HV lead routing and clearances, how to contact and mount a device.
> 3. Trek front-panel state before a run (HV enable, gain, polarity). Which setting of "Trek inverts
>    (negate control)" this bench needs, which sign the first "meas" shows, and whether to continue or
>    abort when "V_Out off-screen" appears (section 3, step 4).
> 4. After a run: what to switch off by hand and in what order, how to discharge the device, how to prove
>    it is safe to touch. (The repo does not say how fast the Trek output or the device falls after the
>    signal generator goes to 0 V.)
> 5. What the BK 9174B DC supply powers on this rig, and when it must be off.
> 6. Emergency: where the stop is, who to call, what to do after a breakdown.
> 7. The highest kV and the staircase a new student may use on a first LIVE run.
> 8. Lighting, camera mount, zoom, working distance, and a starting exposure for this rig.
> 9. Which "Output dir" to use, and the folder naming rule (BENCH_TEST.md calls the corpus convention
>    DEVICE_CONCENTRATION_DATE). Who to ask when a run looks wrong.
> 10. When a pale ring surrounds the dark ink disc, which edge is the 16 mm feature?
> 11. At which step may the Trek's HV output be enabled, and by whom? (This page keeps it off through
>     sections 2 to 4.)

## 1. What you need before you start

Safety statements that already exist in the repo (quoted, nothing added):
- BENCH_TEST.md, section O: "Only for someone trained and authorized on that rig." and "closing the app
  only attempts a best-effort ramp." Section M (dry run): "A dry run never commands the signal generator,
  so the app puts no control voltage into the Trek. Leave the HV off." Section R: "Keep the Trek's HV
  output OFF for this whole section." Section P2 is headed "DRY RUN, HV off".
- CLAUDE.md: "Closing the app does not switch off the BK 9174B output".
- Manual, SLDEA chapter: "A live run drives real HV up to 10 kV through the Trek."
- RUN_SHEET.md files live HV work under "Bench - HV (authorized operator)".

You need:
1. The Linux bench PC (on Windows a live run refuses to start), with the scope, signal generator and
   camera powered and connected. Start the app from its desktop icon. Each instrument tab's "Connection"
   line must turn green. If it is red, power that instrument on and press its "Reconnect". **The Trek's HV
   output stays OFF through sections 2, 3 and 4** (statements above). Who may enable it, and when, is not
   in the repo (box item 11).
2. The wiring the software assumes (docs/manual-src/addendum_a_stack.json): signal generator CH1 is a DC
   source into the Trek control input (1 V = 1 kV, 10 kV maximum). Trek V_Out goes to scope CH2 (1 kV per
   scope volt), I_Out to CH3 (200 uA per scope volt), direct BNC. These are the defaults of "V_Out scope
   CH", "I_Out scope CH" and "SG CH" on the "SLDEA Test" tab. The software cannot see your cables.
3. A mounted, lit device (lab box), its electrode material and ink volume, an image viewer.

## 2. Camera and lighting

The picture is the measurement. Every area number comes from the photos, so a bad picture cannot be fixed
later. The repo has no lighting, mount, zoom or working-distance instructions (checked: README.md,
RUN_SHEET.md, BENCH_TEST.md, the manual). Ask the lab (box item 8). The Trek's HV output stays off
(section 1). A usable picture:
- **The disc stands out from its surround.** The automatic fit looks for a dark disc on lighter paper. On
  real baselines the disc is only 10 to 25 gray levels darker than the paper (162 to 167 against 176 to
  190, manual Part II): a faint patch, not a black circle. If you cannot see its edge, the software cannot
  either.
- **In focus, centered, with room.** The disc grows as voltage rises (area ratio 1.6 on run
  DOT_P3_1_20260729), so the whole grown disc must stay in the picture.
- **Not clipped.** Healthy baselines read mean 128 to 190 (the lowest real one on file is 116), with 0.1
  to 3.6 percent of pixels at 250 or more. Keep the exposure fixed: auto drifts.

Set it on the Webcam tab:
1. Open "Webcam", press "Start Preview". The run always uses camera 0, whatever "Camera:" says.
2. Tick "Show focus score". Turn the lens for the highest number, then confirm by eye. The number has no
   target. Real baselines read from about 7 to about 770. A blank picture reads 0.
3. The exposure goes in "exposure_time_absolute" (units of 100 microseconds, 20 = 2 ms). Keep "gain" at 0
   (its hint: "prefer exposure/light"). The bench habit is "Stabilize (pin gain 0)", then adjust
   (BENCH_TEST.md, section P). Healthy runs on file used exposure 23 to 100. The 2026-10-01 run used 3
   (0.3 ms). **Typing a number changes nothing by itself**: neither the camera nor the preview follows the
   fields until step 5.
4. If the panel says "no camera controls detected", stop. The run then uses exposure 6 and gain 60 without
   telling you, and setup.txt still says so. Press "Read camera" and fix it first.
5. Loop: type a value, press "Apply & Lock", look at the preview, repeat until the disc is clear. The
   status "saved for next start" means it saved (the number after "locked" counts attempts, not values the
   camera took). Make "Apply & Lock" your last camera action: "Read camera" and "Refresh" refill the two
   fields from the camera. The run takes exposure and gain from the fields.

The pre-flight picture appears when you press Run (section 5). Judge it like this:
1. Look first. Can you see the disc edge all the way round? If not, press "Adjust (open Webcam tab)" or
   "Cancel", not "Looks good - start run". Then the numbers: "mean" about 115 to 190, "saturated" under
   about 4 percent, "focus" has no pass mark. Enter presses "Looks good".
2. **The verdict "exposure OK" can appear on an unusable frame.** A frame counts as dark only below mean
   40, and only a clipped frame is stopped. On 2026-10-01 the baseline had mean 67, saturated 0.0 percent,
   focus 0: a uniform dark gray with no disc. The verdict was "exposure OK".

## 3. Scope and drive checks the software expects

1. Scope. Before a live run the app reads scale, attenuation, position and offset only. BENCH_TEST.md,
   section N: "an I_Out channel left on AC coupling (a bench profile can do that), an I_Out channel
   switched off, or a scope left stopped all pass the check." So look at the scope's own screen (section
   N: "look at the screen"): "both monitor channels DC-coupled and on, and the scope running, not in
   Single". **The "Oscilloscope (MSO24)" tab does not show the scope's state.** It never reads the scope
   back: its "Coupling:" drop-down (DC) and "Enable Channel" checkbox (ticked on CH1 only) are start-up
   defaults. "Apply CH2 Config" is the only button that sends coupling, and it also writes that tab's
   "Vertical (V/div):", "Position (div):" and "Enable Channel" values. Do not press "Stop" or "Single"
   before a run.
2. "Trek inverts (negate control)" is unticked at start (a preset can tick it). When ticked, the run (a)
   sends the signal generator a negative control voltage, (b) makes the scope check expect V_Out to swing
   0 to minus kV, (c) multiplies logged V_Out and I_Out by -1. Hint: "Tick when the Trek outputs NEGATIVE
   kV for a positive control voltage". Which setting this bench needs is a lab question (box item 3). Set
   it BEFORE you press Run.
3. The first landing is the check. After each photo the "Run log" gets a line like
   `snap s01 0.25 kV [post-ramp]  meas -0.26 kV / -1 uA  -> SLDEA_s01_00.25kV_post-ramp.png`. The kV after
   "snap" is commanded. The kV after "meas" is what the scope read, after the "Trek inverts" checkbox was
   applied. At the first landing (0.25 kV by default) the size must agree, and the sign must be the one
   the lab gave you. If either is off, press "Abort" and ask. On 2026-10-01 the line read `meas -0.26 kV`
   for 0.25 kV, with the checkbox unticked.
4. The off-screen warning starts "V_Out off-screen (9.9E37 sentinel)" and goes on "measured_kV logs blank
   from here; vertical window too small". The scope gave no valid V_Out reading, so from that photo on the
   voltage is NOT recorded. The run does not stop. **Every run on file with readings (14 of 16) logged
   V_Out as NEGATIVE (none positive) with the checkbox unticked, and none of the 440 rows at 4.25 kV or
   more has a reading.** On 2026-10-01 (1 V/div, position -3 div, "monitor check: OK" logged) readings
   stayed valid to 2.00 kV commanded ("meas -2.03 kV") and were lost from 2.25 kV, about 2 divisions below
   zero. No run ticked the checkbox, so nobody knows if it helps, and the app has no setting known to
   prevent this. What to do when the warning appears is a lab question (box item 3).
5. Leave the watchdog as it starts ("Breakdown watchdog (LIVE runs)": "Enabled", "Trip" 100, "Confirm (s)"
   3) unless the lab says otherwise. It needs the scope.

## 4. Dry run first

A dry run rehearses timing, camera and folder. It does NOT prove the scope window, the Trek polarity or
the drive: it skips the scope check, the "Energize HV?" dialog and the watchdog. **It also does not switch
the SG output off**: it never touches the signal generator, so whatever the SG was left doing stays. Keep
the Trek's HV output off for the whole dry run (BENCH_TEST.md, section M: "Leave the HV off."). The app
says why when a Webcam-tab sweep is still writing the run's channel: a DRY run "would not be dry: the
sweep can still energize the Trek", and "A sweep leaves CH1 at its last level when it stops, so also set
CH1 to 0 V, or its output OFF, on the Signal Gen tab." (CH1 stands for the run's channel.)
1. On the "SLDEA Test" tab the checkbox "DRY RUN - HV OFF" is ticked at start and the button reads "Run
   (DRY)". If it says "LIVE - HV WILL BE DRIVEN", tick the checkbox again.
2. For a quick rehearsal use Start 0, End 1, Step 0.5, Ramp 2, Landing 10 (BENCH_TEST.md, section M): well
   under two minutes. The defaults (0 to 10 kV, step 0.25, Ramp 5, Landing 60) take 0:43:22 (82 frames).
   The first ramp always starts from 0 kV, so keep "Start (kV)" at 0.
3. Fill "Output dir", "Run name (blank = auto)", "DEA active area diam (mm)" (16 for the standard disc),
   "Electrode" and "Concentration (mL)" (grayed out for inks without a volume). The folder name does not
   say DRY, so start the name with DRY_. Press "Run (DRY)", answer the dialogs (section 5) and judge the
   pre-flight picture (section 2).
4. At "complete", open the run folder: setup.txt (third line `MODE: *** DRY RUN (HV output OFF) ***`),
   data.csv, run.log, frames/ (one PNG per photo), telemetry.csv (scope connected). Open
   frames/SLDEA_s00_00.00kV_baseline.png. Disc visible and sharp? If not, go back to section 2. Edge
   Review opens by itself ("Auto-open Edge Review" is ticked): close it unsaved.

## 5. Live run

Before you press Run: "Apply & Lock" was your last camera action; scope as in section 3; "Trek inverts
(negate control)" set as the lab says; staircase right; the physical steps in the lab box done; the Trek's
HV output enabled only as the lab says (box item 11). Use a NEW "Run name (blank = auto)": a used name is
reused and its files overwritten. "Output dir" is not checked until the end of the dialogs, so look at it
now. Then untick the checkbox "DRY RUN - HV OFF". The row turns red ("LIVE - HV WILL BE DRIVEN"), the
button reads "Run - LIVE HV". Press it.

The dialogs come in this order. Enter answers the default. That is the cautious answer on every dialog
except the pre-flight picture, where Enter presses "Looks good - start run".
1. "SLDEA - run blocked" (only if needed): a Webcam-tab sweep on the run's own SG channel, a timed capture
   or a camera adjustment is still going. Stop it, press Run again.
2. "Stepped sweep still running" (only if a Webcam-tab sweep is writing the OTHER SG channel): "Start the
   run with the sweep still going?" Default No. Yes starts the run beside the sweep; both want the camera,
   so photos can fail with "NO FRAME". Answer No, press "Stop sweep" on the Webcam tab, press Run again.
3. Two notices stop a LIVE run before it starts: "Linux only" (use the Linux bench PC) and an error
   "SLDEA" starting "Signal generator not connected" (connect it, press Run again).
4. "No current monitoring" (only with no scope): Yes = no measured kV or uA, no watchdog, no telemetry.
   Answer No.
5. "Scope monitor setup" (only if the scope window is wrong): "Yes = fix and continue", "No = run anyway",
   "Cancel = stop". Yes rewrites scale, position, attenuation, offset, coupling and channel-on for both
   monitor channels (BENCH_TEST.md, section O, says take it). No keeps what was flagged ("this silently
   ruined five runs on 2026-07-25", manual). No problem: no dialog, only the log line "monitor check: OK".
6. "Energize HV?": "LIVE run - this drives the Trek up to" your top kV "via SG CH" and the channel, the
   staircase summary, "Proceed?". Default No. Yes means: after the last dialog the program sets the signal
   generator to DC, switches its output ON and ramps up. It shows no polarity, watchdog or folder, so
   check them first.
7. "No electrode specified", "No concentration specified" (CNT inks only): "Start the run without it?" Yes
   records nothing. Answer No, type the value, press Run again.
8. "Camera pre-flight". With no frame it is a question: "No camera frame available", "Continue anyway?",
   default No. Yes starts a run that takes NO images, so no area can be measured: answer No and fix the
   camera (section 2). Otherwise it is the picture: "Looks good - start run" starts the staircase now.
   "Adjust (open Webcam tab)" cancels the run: press Run again and answer every dialog again. "Cancel"
   cancels. A clipped frame turns the first button into "Start anyway (baseline blown out)" and adds the
   dialog "Baseline is blown out" (default No).

## 6. While it runs

The app never stops a run because a monitor or the camera failed. Its warning for lost current monitoring
says "Run continues; watch the DEA and abort manually if in doubt."
- The status next to the buttons reads like `LIVE  t=120/2602s  ~0.50 kV  frames 5/82` (the defaults, 120
  s in). That kV is COMMANDED, not what the Trek does. The "Run log" is at the bottom of the tab (scroll
  down) and shows 8 lines, so a warning scrolls away. Check the first landing at once (section 3).
- Leave the Webcam tab alone (preview, "Apply & Lock", sweeps). Nothing blocks you, but photos then fail
  with "NO FRAME (camera busy? close the Webcam preview)".
- **Press "Abort" if** the first landing is wrong (section 3, step 3); "CURRENT MONITORING LOST" appears;
  "NO FRAME" repeats; or anything on the rig or device looks wrong. Do not close the window to stop a run:
  that is only a best-effort stop.
- "V_Out off-screen" is NOT an Abort rule here: every run on file that reached 4.25 kV lost its voltage
  reading (section 3, step 4), and the app has no setting known to prevent it. Continue or abort is a lab
  decision (box item 3). Until it is filled in, ask a trained person.
- What "Abort" does: it sets a stop flag, seen within about 0.1 s (or after the photo being taken). The
  program then sets the signal generator offset to 0 V and only after that switches its output OFF: one
  step, not a slow ramp, although the log line "abort requested" says ramping. The status reads "aborted"
  in GREEN. Green does not mean safe.
- If the watchdog trips, the log says "BREAKDOWN CONFIRMED", the run takes one photo, stops and zeroes,
  and the status reads "BREAKDOWN-ABORT" in red. BENCH_TEST.md section O: "keep everything".

## 7. After the run

1. Wait until the Run button is active again and "Abort" is gray. That happens only after the shutdown
   code has finished.
2. The program set the signal generator offset to 0 V, then its output OFF. It does not read the output
   back: no dialog means no error was raised, not that zero was measured. If it could not, the log says
   "FAILED TO ZERO THE SG OUTPUT" and the dialog "HV NOT ZEROED" says "The Trek may still be outputting
   high voltage." and "Turn the SG output OFF on its front panel (or power it off) NOW, then check the
   Trek." That is the only emergency instruction in the repo.
3. NOT switched off by this app, ever: the Trek (the app controls only the signal generator) and the BK
   9174B DC supply (CLAUDE.md: "Closing the app does not switch off the BK 9174B output"). The app says
   nothing about discharging the device or when it is safe to touch. Follow the lab's answers (box items 4
   and 5).
4. The run folder (setup.txt, data.csv, run.log, frames/, telemetry.csv) is in "Output dir". Keep it whole
   and out of the code repository. Edge Review opens by itself only after "complete". After "aborted" or
   "BREAKDOWN-ABORT" press "Edge Review..." on the "SLDEA Test" tab.

## 8. Edge Review

1. Check the "Run:" field. The first folder in the list is pre-selected and may not be yours. A run marked
   "processed" already has areas, and "Detect Edges" starts a new pass over them. Edge Review shows no
   picture until you press it, so first open frames/SLDEA_s00_00.00kV_baseline.png in an image viewer. No
   visible disc? Stop, tell the lab.
2. Press "Detect Edges". The scale window opens first (title starts "Calibrate - applied at Save"). It
   turns pixels into millimeters. Radio buttons: "VERIFY the automatic fit", "BY HAND: fit a circle", "BY
   HAND: two opposite points".
3. **Verify (the normal case).** The picture has extra contrast, so its colors are not real. A dashed
   green circle is the automatic fit. Two lines give "Automatic fit" (pixels = 16 mm) and the quality:
   "fit residual" and "circularity" (the 10 of 16 real baselines it accepted read 0.4 to 1.3 percent of
   diameter and 0.97 to 1.0). Does the circle follow the edge of the dark disc all the way round, not a
   strip, glare or a pale ring? Then press "Accept the automatic fit (at Save)" (Enter will not: "Enter
   cannot approve an anchor"). It only STAGES the scale: nothing is written until Save. Wrong feature?
   "Cancel (Esc)", ask.
4. **When the fit refuses** (6 of the 16 on file did) the first line reads "NO automatic fit on this run,
   so there is nothing to verify: measure the disc BY HAND." with a "Reason:". Decide first: can you see
   the disc edge?
   - No (the Reason says "the paper reads" a low number such as 67 gray, where healthy paper reads 176 to
     190): "Cancel (Esc)". Do not measure by hand, do not Save: the run cannot be measured and must be
     repeated. On 2026-10-01 three hand circles on a blank picture disagreed by 23 percent, and were
     accepted anyway.
   - Yes: use the circle: "straddle the edge: half the stroke on the disc, half on the paper." Circle the
     dark ink disc (box item 10 if a pale ring surrounds it). After the last round press "Finish
     calibration (applied at Save)"; Enter will not. Dialog "Rounds disagree": answer "Yes = refit all"
     rounds; if it still disagrees, "Cancel" and ask; never "No = accept as measured". Dialog "Anchor NOT
     cross-checked" ("Use this UNCHECKED anchor anyway?"): nothing can check a hand fit on this run. Yes
     only if you can see the edge clearly, "Rounds disagree" did not stand, and the lab allows hand
     anchors; otherwise No.
5. Detection runs. The status line counts "auto-accepted", "no-change/no-edge" and "need review".
   **Warning sign:** almost every frame "no-change/no-edge" although the voltage went up. On 2026-10-01
   that was 25 of 26 frames, with `review queue: 0 frame(s) left`. An empty queue is not good news here.
   Do not Save. Look at the first and last frame with the arrow keys. No disc in them? The run is
   unusable.
6. The queue. Outlines A, B, C carry letter tags; D is your own trace. Trust the method name in each row
   more than "conf" (a score, not a probability). "disc-fit" follows the edge (median IoU 0.89 against an
   operator, SLDEA_MEASUREMENT.md, 1.2). "diff-hi", "diff-lo", "diff-otsu" and "tex-ratio" outline a
   changed or wrinkled patch, 40 to 69 percent too small. Rules of thumb:
   - **Accept** (Enter): the selected outline follows the disc edge all the way round.
   - **Pick another** (press 2 or 3, or click B or C): it fits better. It COMMITS at once, although the
     in-app help says "select". Look at all three outlines first.
   - **Reject** (R): only if no correct edge can be drawn, even by hand (an obstruction, debris from a
     breakdown, a damaged image). A hard frame is not a reason. There is no undo button.
   - **Trace** (D or 4): no outline fits, or the frame is washed out above about 5.5 kV (How to use, step
     6: "Trace a washed-out frame. Do not reject it."). In "Trace boundary" click points around the disc,
     then "Done (Enter)", which only stages D: press "Accept (Enter)" in the main window too. To "The
     outline crosses itself. Keep it anyway?" click No: Enter would answer Yes.
   - **Which edge to trace:** the OUTER edge of the expanded disc (the outer toe), not the middle of its
     soft edge. Do not straddle: that is for the scale circle only. Hand traces read 5.2 to 5.7 percent
     larger in area than machine outlines (SLDEA_MEASUREMENT.md, 1.3): expected.
   - **Not sure:** "Next" leaves the frame unreviewed, and Save then blanks it. Ask instead.
   - Arrow keys browse and decide nothing. Enter always commits the selected outline, even on a frame the
     machine already accepted. The queue skips frames the machine accepted alone and frames it called "no
     change vs baseline (auto)": step through several before you Save.
   - "breakdown?" is a confirmed event: Save then renames every later frame with _BREAKDOWN. "collapse?"
     and "transient discharge?" are only notes.
7. Save: press "Save to data.csv...". The dialog "Save results" starts "Write results into this run's
   data.csv?" and lists "accepted:", "rejected:", "unreviewed:" (left blank), the count "RENAMED with a
   _BREAKDOWN suffix" and "A backup is kept as data.csv.bak". Read it. **Enter answers Yes.** A second
   Save overwrites the first .bak. With no scale you get "Scale gate:". Never close Edge Review before
   Save: the review is lost. Leave "Advanced..." and "Calibrate / re-anchor..." alone unless the lab says
   (on a saved run, re-anchor rewrites data.csv at once).

## 9. Plot

1. "SLDEA Test" tab, "Plot runs...". Window "SLDEA plot - cross-run figures". In "Runs (pick several)"
   pick runs marked "processed" ("Add folder..." adds a parent folder). Keep the mode "area". The window
   reads runs once: after reviewing, close it and open it again.
2. Read the figure before you trust it.
   - The x axis is commanded kV, not measured kV. A flat stretch at A/A0 = 1.0 at low voltage is
     "resting": the machine asserted the baseline area where it saw no change. It is not a measurement. A
     straight line across several kV with no markers is a gap you did not review.
   - Open markers are hand-traced (outer toe), filled ones are machine (half-height). The shaded band
     ("uncertainty bands") uses fixed numbers, 2 percent machine and 1 percent traced, not measured from
     your data. With "Normalized panel as strain %" it comes out too narrow: untick the bands.
   - Read the "warning:" lines under the figure. "no reviewed areas" means the run was skipped.
3. Scroll the left column down to "Export (figure + tidy CSV)". Choose format, dpi (300 default), folder
   and name. The names under the Name field show what will be written: figure, CSV and figspec.json. The
   default name is overwritten without asking. Press "Export figure + CSV". "The CSV is the figure's
   evidence": keep the files together.
4. Do not save with the floppy icon in the plot toolbar (a bare picture). Edge Review's
   area_vs_voltage.png is a quick look with default colors. Never export in a git checkout under a custom
   name (README.md: "keep the default sldea_plot stem").

## 10. When something looks wrong

| You see | Likely cause | Do this |
|---|---|---|
| Pre-flight picture flat, dark, no disc, verdict "exposure OK" (2026-10-01, failure 1) | Exposure far too low (mean 67) | "Adjust (open Webcam tab)", raise exposure, "Apply & Lock", run again |
| "no camera controls detected" | The run falls back to exposure 6, gain 60 | Plug the camera in, "Read camera", set and lock |
| First "meas" has the wrong sign or size (2026-10-01, failure 2) | Trek polarity, checkbox and scope window disagree | "Abort", ask the lab (box item 3), start a new run |
| "V_Out off-screen (9.9E37 sentinel)" | No valid V_Out reading; voltage no longer recorded. Every run on file that reached 4.25 kV lost it | Not an Abort rule here: ask the lab (box item 3). Section 3, step 4 |
| Dialog "HV NOT ZEROED" | Zeroing failed | Do what the dialog says, at once |
| Scale window "NO automatic fit on this run" | Fit refused. A blank picture is the worst case | Section 8 step 4. Blank: "Cancel (Esc)", repeat the run |
| "Rounds disagree" after hand circles (2026-10-01, failure 3) | Hand fits on a disc you cannot see | "Yes = refit all" rounds, or "Cancel" and ask |
| 25 of 26 frames "no-change/no-edge", queue empty | Blank pictures, not a stiff device | Do not Save. Look at frame 1 and the last |

## 11. Words used in this tool

- **Landing / level:** one hold at one voltage. **Step (kV):** the voltage increment on the tab; in Edge
  Review and data.csv "step" is the landing number. **Frame / photo:** one picture. **Post-ramp /
  pre-ramp:** taken "Settle (s)" after a ramp ends / "Snap lead (s)" before the next.
- **Baseline:** the 0 kV photo every area is measured against. **warmup:** a throw-away 0 kV photo two
  seconds earlier. **Nominal / measured kV:** commanded / read by the scope. **V_Out / I_Out:** the Trek
  voltage and current monitors.
- **Watchdog:** aborts when current stays "Trip" uA away from its 0 kV level for "Confirm (s)".
  **Breakdown:** an electrical failure of the device. Only current-confirmed events rename frames
  _BREAKDOWN. **Resting:** the disc at 0 kV.
- **Scale / anchor:** the pixel to millimeter conversion (16 mm divided by the disc pixels). **Verify,
  circle, twopoint:** the three ways to set it. Files store these names, not letters.
- **Candidate A to D:** outlines proposed for a frame; D is your trace. **conf:** the machine's score for
  an outline. **w:** wrinkle index, 1.0 means no texture change. **Auto-accepted:** the machine decided,
  you did not. **Queue:** frames waiting for you. **Staged:** held in memory, not committed.
  **Processed:** some row has an area. **Half-height / outer toe:** the middle / the outer rim of a soft
  edge; machines use the first, hand traces land on the second. **A0, A/A0:** baseline area, and area
  divided by it. **Areal strain:** (A - A0) / A0 x 100.
