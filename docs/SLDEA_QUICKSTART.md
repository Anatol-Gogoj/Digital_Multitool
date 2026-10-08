# SLDEA quickstart: from an unpowered rig to an exported plot

For a new student at the Linux bench PC: one full pass from camera to exported plot. The physics
and the error budget are in SLDEA_MEASUREMENT.md.

How to read this page:
- Text in double quotes is copied from the app (a button, a dialog title, a log line) or from the
  repo file named beside it, minus small pictures, long dashes, markup and trailing colons. An
  ellipsis is written as three dots. In logs, u is the micro sign and -> the arrow.
- This is main at commit 1eb85b2 (2026-09-24), read from the code and from the 16 real runs ("on
  file", 2026-07-23 to 2026-10-01). Nobody has walked a new student through it at the bench yet.
  Where the repo has no answer, the page says so and points to a numbered item in the box below.

> **To be filled in by the lab before a new student uses this page**
>
> The code and the repo docs cannot answer these. Until a line is filled in, ask a trained person
> before you do that step.
>
> 1. Who authorizes HV work and may start LIVE runs, who must be present, what training comes first?
> 2. Barrier or enclosure, HV lead routing and clearances, how to contact and mount a device.
> 3. Trek front-panel state before a run (HV enable, gain, polarity). Which setting of "Trek
>    inverts (negate control)" this bench needs, and which sign the first "meas" line should show.
> 4. Lockout and discharge: what to switch off by hand after a run and in what order, how to
>    discharge the Trek and the device, how to prove it is safe to touch. (The repo does not say
>    how fast either falls after the signal generator goes to 0 V.)
> 5. What the BK 9174B DC supply powers on this rig, and when it must be off.
> 6. Emergency: where the stop is, who to call, when to press "Abort", what follows a breakdown.
> 7. The highest kV and the staircase allowed on a first LIVE run.
> 8. Lighting, camera mount, zoom, working distance, and a starting exposure for this rig.
> 9. Which "Output dir" to use, the run-name rule (BENCH_TEST.md names the corpus convention
>    DEVICE_CONCENTRATION_DATE), who to ask when a run looks wrong.
> 10. Continue or abort when "V_Out off-screen" appears (section 3, step 5)?
> 11. With a pale ring around the dark ink disc, which edge is the 16 mm feature? May a hand
>     measured scale be accepted when the automatic fit refuses?
> 12. At which step may the Trek's HV output be enabled, and by whom? What must signal generator CH1
>     show before that (0 V or output OFF), and how do you confirm it? Section 5 says why.

## 1. What you need before you start

Safety statements that already exist in the repo (quoted, nothing added):
- BENCH_TEST.md, section O: "Only for someone trained and authorized on that rig." and "closing
  the app only attempts a best-effort ramp." Section M: "A dry run never commands the signal
  generator, so the app puts no control voltage into the Trek. Leave the HV off." Section R: "Keep
  the Trek's HV output OFF for this whole section."
- CLAUDE.md: "Closing the app does not switch off the BK 9174B output". The manual: "A live run
  drives real HV up to 10 kV through the Trek." RUN_SHEET.md: "Bench - HV (authorized operator)".

You need:
1. The Linux bench PC (a live run refuses on Windows: "Linux only") with the scope, signal generator
   and camera on and connected. Start the app from its desktop icon. On the "Oscilloscope (MSO24)"
   and "Signal Gen (BK 4055B)" tabs the "Connection" line must be green; if red, power the
   instrument on and press "Reconnect". **The Trek's HV output stays OFF through sections 2 to 4.**
2. The wiring the software assumes (docs/manual-src/addendum_a_stack.json): signal generator CH1 is
   a DC source into the Trek control input (1 V per kV, 10 kV maximum). Trek V_Out goes to scope
   CH2 (1 kV per scope volt), I_Out to CH3 (200 uA per scope volt): the defaults of "SG CH",
   "V_Out scope CH" and "I_Out scope CH" on the "SLDEA Test" tab. The software cannot see cables.
3. A mounted, lit device, its electrode material and (for CNT inks) its ink volume.

## 2. Camera and lighting

The picture is the measurement: every area comes from the photos, and a bad one cannot be fixed
later. The repo has no lighting or mounting advice, so ask the lab (box item 8). A usable picture:
- **The disc stands out.** The automatic fit looks for a dark disc on lighter paper ("no central
  dark region big enough to seed on"). Real P3 discs are only 10 to 25 gray levels darker than the
  paper (162 to 167 against 176 to 190, manual Part II). No visible edge, no fit.
- **In focus, centered, with room.** The disc grows as voltage rises (area up to 1.63 times its
  resting area on run DOT_P3_1_20260729), so the whole grown disc must stay in the picture.
- **Not clipped.** On file, good baselines read mean 116 to 188 with 0 to 2.5 percent of pixels at
  250 or more; the two clipped ones read mean 239 to 242 with 80 to 83 percent.

Set it on the "Webcam" tab:
1. The preview starts when you open the tab; if it does not, press "Start Preview". The run always
   uses camera 0, whatever "Camera" says.
2. The focus score is on: turn the lens for the highest number, then check by eye. It counts
   mostly the middle of the picture (the circle), so center the disc first. It has no pass
   mark: real baselines on file read 7 to 768, a blank picture reads 0.
3. Press "Auto-set camera" and wait until the line under it starts "locked: exposure". It pins
   gain at 0, finds the exposure for a mid-gray picture, balances the white on the scene in view,
   and locks it all; the exposure and gain boxes then say what is locked. Look at the preview. If
   the disc is still not clear, change the light, then press "Auto-set camera" again. If a step
   fails, the line says which, and the previous lock stays.
4. To set the exposure by hand instead, type it in "exposure_time_absolute" (units of 100
   microseconds: 20 = 2 ms), keep "gain" at 0, and press "Apply & Lock" beside them ("saved
   for next start" means it saved). Typing alone changes nothing in the preview, and
   the line under the boxes says "Typed, not locked" until you lock. Every run on file except
   2026-10-01 used exposure 23 to 100; that run used 3 (0.3 ms).
5. Make a lock your last camera action: "Auto-set camera", or "Apply & Lock". "Refresh", "Read
   camera", "Auto-expose" and starting the app refill the exposure and gain fields from the camera.
   The run uses those fields; the pre-flight picture uses the locked values. They agree only if a
   lock came last.
6. "no camera controls detected" on the panel: stop. The run then asks for exposure 6 and gain 60
   (a fallback), and setup.txt names them as built-in defaults. Plug the camera in, open "Advanced
   camera settings", press "Read camera".

The pre-flight picture appears when you press Run (section 5). Judge it like this:
1. Look first. Can you see the disc edge all the way round? If not, press "Adjust (open Webcam
   tab)" or "Cancel", not "Looks good - start run" (Enter presses it). Then the numbers: "mean"
   about 115 to 190, "saturated" under about 3 percent.
2. **The verdict "exposure OK" can appear on an unusable frame.** The app calls a frame dark only
   below mean 40, and only a clipped frame (saturated 20 percent or more, or mean 225 or more) makes
   it ask a question. A frame like the 2026-10-01 baseline (mean 67, saturated 0.0 percent, focus 0:
   uniform dark gray, no disc) gets "exposure OK". Only a clipped frame is logged.

## 3. Scope and drive checks the software expects

1. The run reads V_Out and I_Out on the channels set in "V_Out scope CH" and "I_Out scope CH". The
   LIVE pre-run check tests only each channel's scale, attenuation, position and offset, so AC
   coupling, a channel that is off or a stopped scope pass. Look at the scope screen (BENCH_TEST.md
   section N): "both monitor channels DC-coupled and on, and the scope running, not in Single".
2. The "Oscilloscope (MSO24)" tab never reads the scope's settings back, so it does not show the
   scope's state. Its "Coupling" (DC) and "Enable Channel" (ticked on Channel 1 only) are start-up
   values, not readings. **Do not press "Apply CH2 Config" or "Apply CH3 Config" to fix coupling.**
   The button writes all of that channel's boxes. At start-up that switches the channel OFF ("Enable
   Channel" unticked) and sets 1.0 V/div and position 0. The pre-run check does not test whether a
   channel is on, so it would not notice. Set coupling on the scope itself, or ask. (If the lab
   wants the button used: tick "Enable Channel" and type "Vertical (V/div)" and "Position (div)"
   first.) Do not press "Stop", "Single" or "AutoSet" before a run.
3. "Trek inverts (negate control)" is ticked at start (a preset can untick it). Ticked, the run
   sends the signal generator a negative control voltage, and that is all it changes: the scope
   check still expects V_Out to swing 0 to plus kV, and V_Out and I_Out are logged as read. Its
   hint: "Tick when the Trek outputs NEGATIVE kV for a positive control voltage". Which setting
   this bench needs is a lab question (box item 3). Set it before you press Run.
4. The first landing is the check. After each photo the "Run log" gets a line like `snap s01 0.25 kV
   [post-ramp]  meas -0.26 kV / -1 uA  -> SLDEA_s01_00.25kV_post-ramp.png`. "snap" kV is commanded;
   "meas" kV is what the scope read, after the "Trek inverts" box was applied. At the first landing
   (0.25 kV by default) the size should be close and the sign must be the one the lab gave you. If
   not, press "Abort" and ask. On file, all 14 runs that have readings (2026-10-01 among them) read
   negative with the box unticked, and none has the "INVERTED" line in setup.txt. That is why the
   box now starts ticked: with it, the first "meas" line should read positive. If it reads negative
   with the box ticked, this Trek does not invert: press "Abort" and ask. The lab decides.
5. The off-screen warning starts "V_Out off-screen (9.9E37 sentinel)" and goes on "measured_kV logs
   blank from here; vertical window too small". The scope gave no valid V_Out reading, so from that
   photo on the voltage is not recorded. The run does not stop and areas do not depend on it, but
   you lose the record that the Trek delivered the voltage. On 2026-10-01 readings were valid to
   2.00 kV and lost from 2.25 kV, though "monitor check: OK" was logged. On file, none of the 440
   rows at 4.25 kV or more has one. Whether to abort is a lab question (box item 10).

## 4. Dry run first

A dry run rehearses timing, camera and folder. It does not prove the scope window, the Trek
polarity or the drive: it skips the scope check, the "Energize HV?" dialog and the watchdog, and
never touches the signal generator. Keep the Trek's HV output off for the whole dry run.
1. On the "SLDEA Test" tab the checkbox "DRY RUN - HV OFF" is ticked at start and the button reads
   "Run (DRY)". If it says "LIVE - HV WILL BE DRIVEN", tick the checkbox again.
2. A saved setup is faster: pick it under "Run configuration presets", across the top of the tab,
   and press "Load" (the tab stays in DRY), then still check every field this step and the next
   name. For a quick rehearsal use Start 0, End 1, Step 0.5, Ramp 2, Landing 10 (BENCH_TEST.md section M):
   the summary line reads "2 levels 0->1 kV: 2 landings, 6 frames, total 0:00:26". The defaults take
   0:43:22 for 82 frames. Keep "Start (kV)" at 0: the first ramp always starts from 0 kV.
3. Fill "Output dir" ("New folder..." beside "Browse" makes a fresh folder inside it, for example
   one per session; set it before you press Run, since both buttons refuse during a run), "Run
   name (blank = auto)", "DEA active area diam (mm)" (16 for the standard disc; text that is not a
   number silently becomes 16), "Electrode", "Concentration (mL)" (CNT inks only) and "Film
   thickness (um)": the film measured mounted and prestretched, in micrometers (the plot's field
   axis divides the voltage by it). Start the run name with DRY, so you can tell the folder from a live run later. This
   is advice on this page, not a repo rule. The automatic folder name does not say DRY.
4. Press "Run (DRY)", answer the dialogs (section 5) and judge the pre-flight picture (section 2).
5. At "complete", open the run folder and frames/SLDEA_s00_00.00kV_baseline.png: disc visible and
   sharp? If not, go back to section 2. Edge Review opens by itself: close it unsaved.

## 5. Live run

Before you press Run: a lock ("Auto-set camera" or "Apply & Lock") was your last camera action, the scope is as in section 3,
"Trek inverts (negate control)" is set as the lab says, and the lab box steps are done. Leave
"Breakdown watchdog (LIVE runs)" enabled. Use a NEW "Run name (blank = auto)": the line under the box
shows the folder the run will write to, and when that folder already holds a run, or the share it is
on is not mounted, the line warns and "Run" refuses to start. Check "Output dir" now too: whether the
app can write there is only found out after the last dialog.

**The app sends nothing to the signal generator until the last dialog is answered.** Whatever the
drive channel (CH1 by default) was left outputting goes to the Trek's control input, and is
amplified once the Trek's HV is on. The app's own dry-run text says a stopped sweep leaves the
channel at its last level, and to set it to 0 V, or its output OFF, on the Signal Gen tab. Do that,
and ask the lab how to confirm it and when the Trek's HV may be enabled (box item 12). Then untick
"DRY RUN - HV OFF" (the row turns red and says "LIVE - HV WILL BE DRIVEN") and press the button,
which now reads "Run - LIVE HV".

The dialogs come in this order; a dry run skips items 5 to 10. Enter answers the default: No on
every question except "Scope monitor setup" (Yes) and the pre-flight picture (Enter presses "Looks
good - start run"). An error box asks nothing: the run did not start, nothing was sent to the signal
generator, so fix what it names and press Run again.
1. An error "SLDEA" that starts "Fix the profile first": a staircase field is not a number or is
   out of range.
2. "SLDEA - run blocked", "This run cannot start yet": a Webcam-tab sweep is writing the run's own
   SG channel, a timed capture or camera adjustment is going, the previous run's video recorder is
   still releasing the camera, a Signal Gen tab command is still being sent (live runs), or a sweep
   on the other SG channel needs the camera while video "Record" is ticked. Stop it, or wait, and
   press Run again. For a sweep on the run's own channel, press "Stop sweep", then set that channel
   to 0 V or output OFF on the Signal Gen tab (the dry-run text of this dialog says so; the live
   text leaves it out). "Stepped sweep still running" (a sweep on the other SG channel, "Record"
   unticked) asks "Start the run with the sweep still going?" Yes risks "NO FRAME" photos; answer
   No, press "Stop sweep" on the Webcam tab, press Run.
3. "SLDEA run folder": the run will not write there, and there is no "start anyway". The folder
   "already holds a run" (setup.txt or data.csv), the run name cannot name a folder (plain ASCII
   only: "u for" the micro sign, "as in 2.5uL"), the share is not mounted, or the Output dir could
   not be read or did not answer within 3 s ("Could not check the run folder"). A blank name is
   refused only on the share, when it is not mounted or does not answer. The line under "Run name
   (blank = auto)" says the same before you press Run: "Saves to:" and the folder, then a warning
   ending "Run will refuse". Type another name or clear the box, or have the share mounted, and
   press Run again.
4. Only with video "Record" ticked: "Video unavailable" ("This PC cannot record the lossless video")
   or "Not enough disk for the video", each asking "Run WITHOUT video (snapshots only)?" Yes runs
   with snapshots only; No stops the run.
5. Only with the watchdog ticked: an error "SLDEA", "Breakdown watchdog Trip (uA) must be a positive
   number" (or "Confirm (s)"): the box is blank, zero, negative or not a number. The defaults are
   100 and 3.
6. "Linux only" (a live run on Windows). An error "SLDEA" that starts "Signal generator not
   connected": connect it on the Signal Gen tab, or use a dry run.
7. "No current monitoring" (no scope): Yes = no kV/uA readings, watchdog or telemetry. Answer No.
8. "Scope monitor setup" (only if the scope window is wrong): "Yes = fix and continue", "No = run
   anyway", "Cancel = stop". Yes rewrites scale, position, attenuation, offset, coupling and
   channel-on for both monitor channels at once, even if you cancel a later dialog (BENCH_TEST.md
   section O says take the fix). No keeps what was flagged ("this silently ruined five runs on
   2026-07-25", manual). No problem: no dialog, only the log line "monitor check: OK". If the fix
   fails, an error "Scope", "Could not rescale", stops the run.
9. "A video is still being copied" (a previous run's video is still being moved into its run folder,
   on the share this run writes to): "Start the LIVE run anyway?" Answer No and wait until the line
   under the Run row says "ready in the run folder" (section 7, step 5).
10. "Energize HV?": "LIVE run - this drives the Trek up to" your top kV "via SG CH" and the channel,
    then the staircase summary, the breakdown watchdog's state ("Breakdown watchdog: ON..." with its
    trip and confirm time, or "Breakdown watchdog: OFF. Nothing stops this run on a breakdown..." if
    the box was unticked), and "Proceed?". Yes means carry on. Nothing is sent to the signal
    generator until the last dialog is answered. Then the program sets the channel to DC at 0 V,
    output ON, and ramps up. The dialog shows no polarity or folder, so check them first.
11. "No electrode specified", "No concentration specified" (CNT inks only), "No film thickness
    specified": "Start the run without it?" Yes records nothing. Answer No, fill the field, press
    Run again. "Film thickness looks unusual" means a value outside 5 to 2000 um, such as one typed
    in mm: answer No and fix it. An error "SLDEA" that starts "Concentration (mL) must be a positive
    number" or "Film thickness (um) must be a positive number": fix the box or clear it.
12. The camera pre-flight. With no frame it is a question, "Camera pre-flight": "No camera frame
    available", "Continue anyway?". Yes starts a run with no images and no areas: answer No and fix
    the camera. If the picture check itself fails, "Camera pre-flight" says "The picture check could
    not run" and asks "Start the run anyway?": answer No. Otherwise it is the picture window,
    "Camera pre-flight - SLDEA run". "Looks good - start run" starts the staircase now. "Adjust
    (open Webcam tab)" and "Cancel" cancel the run: fix it, press Run, answer every dialog again. A
    warning renames the first button "Start anyway (...)" and takes Enter off it. Pressed on a
    clipped frame, that button asks "Baseline is blown out", on a flat one "No picture in this
    frame" (both default No).
13. After the last answer the run checks twice more, asks nothing, and either starts or refuses:
    "SLDEA - run blocked" again if something from item 2 began while a dialog was open (a sweep
    started "while this run was being set up"), or, rarely, "SLDEA - run blocked" with "The
    breakdown watchdog's state changed since Energize HV?" (a scope "Reconnect" finished while a
    question was open). Nothing was sent to the signal generator: press Run again and answer with
    the state as it is now.

## 6. While it runs

The app never stops a run because a monitor or the camera failed. Its own warning for lost current
monitoring says: "Run continues; watch the DEA and abort manually if in doubt."
- The status next to the buttons reads like `LIVE  t=120/2602s  ~0.50 kV  frames 5/82` (the
  defaults, 120 s in). That kV is commanded, not what the Trek does, and the frame count counts
  attempts, not saved photos. The "Run log" is at the bottom of the tab, under the buttons, and
  shows 8 lines, so a warning scrolls away. Check the first landing at once (section 3, step 4).
- Also check the picture early. When the "Run log" shows the line "snap s00 0.00 kV [baseline]",
  open frames/SLDEA_s00_00.00kV_baseline.png in the run's folder (the "run dir:" log line names it).
  No disc, or flat dark gray: press "Abort". The pre-flight picture can miss this (section 2): on
  2026-10-01 the run went 209 s, to 3 kV, on such frames before the abort.
- Leave the Webcam tab alone. While a run is going it cannot open the camera or change its
  exposure, and its preview comes back by itself once the run lets go of the camera, unless you
  pressed "Stop Preview".
- **Press "Abort" if** you are in doubt, and in particular if the first landing is not what the lab
  expects, the baseline photo shows no disc, "CURRENT MONITORING LOST" appears, "NO FRAME" repeats,
  or anything on the rig or device looks wrong (box item 6). Do not close the window to stop a run
  (only a best-effort stop). "V_Out off-screen" is not an Abort rule here (section 3, step 5).
- What "Abort" does: it sets a stop flag, seen within about 0.1 s or after the photo in progress.
  The program then sets the signal generator offset to 0 V and only then switches its output OFF:
  one step, not a slow ramp, although the log line "abort requested" and the manual say ramp. The
  status reads "aborted" in green. Green does not mean safe.
- If the watchdog trips ("BREAKDOWN CONFIRMED" in the log), the run takes one photo, stops and
  zeroes, and the status reads "BREAKDOWN-ABORT" in red. BENCH_TEST.md section O: "keep everything".

## 7. After the run

1. Wait until the Run button is active again and "Abort" is gray: the shutdown code has finished.
2. The program set the signal generator offset to 0 V, then its output OFF. It does not read the
   output back: no dialog means no error was raised, not that zero was measured. If it could not
   zero it, the log says "FAILED TO ZERO THE SG OUTPUT" and the dialog "HV NOT ZEROED" says "The
   Trek may still be outputting high voltage." and "Turn the SG output OFF on its front panel (or
   power it off) NOW, then check the Trek." That is the only emergency instruction in the repo.
3. The app does not switch off the Trek (it has no Trek driver, only the signal generator) or
   the BK 9174B DC supply. It says nothing about discharging the device or when it is safe to
   touch. Follow the lab's answers (box items 4 and 5).
4. Keep the run folder whole and out of the code repository. Edge Review opens itself only after
   "complete" (not "aborted" or "BREAKDOWN-ABORT"); else press "Edge Review..." (SLDEA Test tab).
5. After a video run the recording is moved into the run folder in the background: the line under
   the Run row says "ready in the run folder" when it is there.

## 8. Edge Review

Edge Review turns the photos into areas, and you check the machine's work. It writes no areas to
data.csv until you press Save. Closing the window first loses your accept and reject choices.
1. Check the "Run:" box: opened by hand, Edge Review picks the first run in the list, which may not
   be yours. A run marked "processed" already has areas: "Detect Edges" starts a new pass, and a
   later Save writes over old areas where you accept a frame.
2. "Detect Edges" opens the scale window first (it is already open if Edge Review opened itself).
   It shows the 0 kV baseline photo; look at it first. No disc? "Cancel (Esc)" and tell the lab.
3. The scale window (title starts "Calibrate - applied at Save") turns pixels into millimeters. It
   offers "VERIFY the automatic fit", "BY HAND: fit a circle" and "BY HAND: two opposite points".
   - **Verify (the normal case).** The picture has extra contrast, so its colors are not real. The
     dashed green circle is the automatic fit. "Automatic fit" gives its pixels across (= 16 mm) and
     "Quality" gives "fit residual" and "circularity" (on file: 0.4 to 1.3 percent of diameter, 0.97
     to 1.0). Does the circle follow the edge of the dark disc all the way round, not a strip, glare
     or a pale ring? Then press "Accept the automatic fit (at Save)" (Enter will not: "Enter cannot
     approve an anchor"). Wrong feature? "Cancel (Esc)" and ask.
   - **When the fit refuses** (6 of the 16 on file) the first line reads "NO automatic fit on this
     run, so there is nothing to verify: measure the disc BY HAND." and then "Reason:". First
     decide: can you see the disc edge? If not (a Reason such as "the paper reads" 67 gray, where P3
     paper reads 176 to 190), press "Cancel (Esc)", do not measure by hand, do not Save: the run
     cannot be measured and must be repeated. On 2026-10-01 three hand circles on a blank picture
     disagreed by 23 percent and were accepted anyway. If you can see the edge, measure by hand.
   - **By hand.** Circle the dark ink disc (box item 11 if a pale ring surrounds it): "straddle the
     edge: half the stroke on the disc, half on the paper." Circle mode: drag to move, drag a handle
     to resize, press "Continue ->" after each round. Two-point mode: the second click ends the
     round. After the last round press "Finish calibration (applied at Save)" (Enter will not).
   - The questions after the last round open over the calibration window, and their buttons say
     what they do. Enter and Esc always pick the safe button.
   - "Rounds disagree": your rounds are too far apart. Press "Refit all" and measure again; if
     again, "Cancel" and ask. Never "Accept as measured". "Anchor NOT cross-checked" ("Nothing can
     check this scale."): nothing can check a hand fit on this run. Press "Use unchecked scale"
     only if you see the edge clearly and the lab allows hand-measured scales (box item 11);
     otherwise "Cancel".
4. Detection runs. The status line counts "auto-accepted", "no-change/no-edge" and "need review".
   **Warning sign:** almost every frame "no-change/no-edge" although the voltage went up (on
   2026-10-01: 25 of 26, with "review queue: 0 frame(s) left"). Do not Save. Look at the first and
   last frame with the arrow keys: no disc, unusable run.
5. The queue. A, B and C are the machine's outlines (letters on the picture), D is your own trace,
   and A is pre-selected. Trust the method name more than "conf", a score and not a probability.
   "disc-fit" follows the edge (median IoU 0.89, SLDEA_MEASUREMENT.md 1.2). "diff-hi", "diff-lo",
   "diff-otsu" and "tex-ratio" outline a changed or wrinkled patch, 40 to 69 percent too small.
   - **Accept** (Enter): the selected outline follows the disc edge all the way round.
   - **Pick another** (press 2 or 3, or click B or C): it fits better. It commits at once, though
     the "How to use" panel says "select". Look at all three first.
   - **Reject** (R): only if no correct edge can be drawn, even by hand (obstruction, debris,
     damaged image). A hard frame is not a reason. Nothing asks first; to undo, press "Prev", then
     Accept. "Next" leaves it unreviewed, and Save leaves it blank at first review. If unsure, ask.
   - **Trace** (D or 4): no outline fits, or the frame is washed out above about 5.5 kV ("How to
     use": "Trace a washed-out frame. Do not reject it."). In "Trace boundary" click points around
     the disc, then "Done (Enter)", which only stages D; press "Accept (Enter)" too. For "The
     outline crosses itself. Keep it anyway?" click No: Enter would answer Yes. On a "no change"
     frame "Trace with NO machine candidate" comes first: Cancel if no disc shows, else OK.
   - **Which edge:** trace the outer edge of the expanded disc (the outer toe), not the middle of
     its soft edge, and do not straddle (the scale circle does). Hand traces read 5.2 to 5.7 percent
     larger than machine outlines (SLDEA_MEASUREMENT.md 1.3): a step in the plot (section 9).
   - Arrow keys browse and decide nothing, but Enter always commits the selected outline, even on
     a frame the machine accepted. Before you Save, step through frames the queue skipped (accepted
     alone, or "no change vs baseline (auto)"): the first, the last, several above 5 kV.
6. Save: "Save to data.csv...". The dialog "Save results" starts "Write results into this run's
   data.csv?" and lists "accepted:", "rejected:", "unreviewed:", the count "RENAMED with a
   _BREAKDOWN suffix" and "A backup is kept as data.csv.bak". Read it: **Enter answers Yes.** A
   "breakdown?" line on a frame is a confirmed event, and Save then renames every later frame file
   (a "collapse?" or "transient discharge?" note renames nothing). A second Save overwrites the
   first .bak. With no scale you get "Scale gate:". Leave "Advanced..." alone, and use "Calibrate /
   re-anchor..." only if the lab says: on a saved run its "Write data.csv now" button rewrites
   data.csv at once.

## 9. Plot

1. On the "SLDEA Test" tab press "Plot runs...". The window "SLDEA plot - cross-run figures" opens.
   In "Runs (pick several)" pick runs with a check mark (processed); drag down the list or
   Shift-click to pick several ("Add folder..." adds a parent folder).
   Keep the mode "area". The window reads each run once: after a review, close and reopen it. It
   remembers the last user's settings (shared account): check every box under "Draw".
2. Read the figure before you trust it:
   - The x axis is commanded kV unless you pick "field V/um": kV divided by each run's film
     thickness, for comparing films of different thickness (a run with no thickness is left off
     that axis by name, with how to add it). A flat stretch at A/A0 = 1.0 at low voltage is "resting": the
     machine asserted the baseline area where it saw no change. It is not a measurement. A straight
     line across several kV with no markers is a gap you did not review.
   - Open markers are hand-traced (outer toe), filled ones are machine (half-height). The shaded
     band ("uncertainty bands") is fixed at 2 percent machine, 1 percent traced, not measured from
     your data. With "Normalized panel as strain %" it is too narrow: untick the bands.
   - Where markers change from filled to open, expect A/A0 to step up by about 5 percent. That
     comes from the two edge conventions, not from the device: traced areas are divided by the
     machine's baseline area (SLDEA_MEASUREMENT.md: 5.2 to 5.7 percent). Do not report it as strain.
   - Read the "warning:" lines under the figure ("no reviewed areas" means a run was skipped).
   - In a small or short window the caption may end with "[Caption cut in this window: N more rows
     in the export.]". A large window shows the whole caption, and the exported figure, and a Save
     from the toolbar, always carry it.
3. Scroll the left column down to "Export (figure + tidy CSV)". Choose format, dpi (300 default),
   folder ("plots" beside the runs by default) and name. The lines under "Name" list the three
   files: figure, CSV and figspec (a redraw file). A file with the same name is overwritten without
   asking. Press "Export figure + CSV". "The CSV is the figure's evidence": keep them together.
4. Do not use the toolbar's floppy icon (a bare picture). Edge Review's area_vs_voltage.png is a
   quick look. In a git checkout leave "Name" empty (README.md: "keep the default sldea_plot stem").

## 10. When something looks wrong

On 2026-10-01 (run SLDEA_20261001_151016) three things went wrong in a row, marked failure 1 to 3.

| You see | Likely cause | Do this |
|---|---|---|
| Baseline photo in frames/ is flat dark gray, no disc (failure 1); the pre-flight picture may have looked fine | The exposure field and the lock disagreed, or exposure really was 3 (setup.txt; the other runs used 23 to 100). Not provable: nothing logs the pre-flight | "Abort" (section 6). Section 2: press "Auto-set camera" (or raise the exposure and "Apply & Lock" last), press Run again |
| The exposure field shows a number you did not type | Starting the app, "Refresh", "Read camera" or "Auto-expose" filled it from the camera | Press "Auto-set camera", or type your value and press "Apply & Lock" last |
| First "meas" line has a sign or size the lab did not expect | Trek polarity, the "Trek inverts" box and the scope window disagree | "Abort", ask the lab (box item 3), start a new run |
| "V_Out off-screen (9.9E37 sentinel)" (failure 2: lost from 2.25 kV, run aborted at 3.0 kV) | The reading left the scope screen (window framed for positive kV, readings negative), though "monitor check: OK" was logged | Not an Abort rule here: ask the lab (box item 10). Section 3, step 5 |
| Dialog "HV NOT ZEROED" | The app could not zero the signal generator | Do what the dialog says, at once |
| "Rounds disagree" after hand circles (failure 3: 23 percent apart, accepted) | Hand fits on a disc you cannot see | "Refit all", or "Cancel" and ask |
| 25 of 26 frames "no-change/no-edge", queue empty | Blank pictures, not a stiff device | Do not Save. Look at the first and last frame |
| A window froze (not responding) | Something held its main thread | Send tk_stall.log and tk_stall.log.1 from ~/.cache/scpi_control (or $SCPI_CACHE) with your report |

## 11. Words used in this tool

- **Landing / level:** one hold at one voltage. **Step (kV):** the voltage increment on the tab; in
  Edge Review and data.csv "step" is the landing number. **Frame / photo:** one picture.
- **Post-ramp / pre-ramp:** a photo taken "Settle (s)" after a ramp ends / "Snap lead (s)" before
  the next ramp. **Baseline:** the 0 kV photo every area is measured against. **warmup:** a spare
  0 kV photo two seconds before it, so the camera settles. **Resting:** the disc at 0 kV.
- **Nominal / measured kV:** commanded / read by the scope. **V_Out / I_Out:** the Trek's voltage
  and current monitor outputs. **Watchdog:** aborts when the current stays "Trip" uA from its 0 kV
  level for "Confirm (s)" seconds. **Breakdown:** an electrical failure of the device.
- **Scale / anchor:** pixels to millimeters (16 mm divided by the disc's pixels). **Verify, circle,
  twopoint:** the three ways to set it; files store these names, not letters.
- **Candidate A to D:** outlines for a frame (D is yours). **conf:** the machine's score for an
  outline. **w:** wrinkle index, 1.0 means no texture change. **IoU:** overlap of two outlines, 1
  is identical. **Half-height / outer toe:** the middle / the outer rim of a soft edge; machines
  use the first, hand traces land on the second. **A0, A/A0:** baseline area, area divided by it.
