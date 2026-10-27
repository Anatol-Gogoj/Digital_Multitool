# Changelog

Every release opens with a plain TL;DR, then the details by area. Versions are
tags on `main`; the GitHub release of each version carries the matching user
manual PDF. Older releases are summarized here and link to their full notes.
The measurement-chain decision log (`SLDEA_DECISIONS.md`) is the record of
*why*; this file is the record of *what shipped*.

## v1.4.8 (2026-10-27, pre-release)

**TL;DR:** The Signal Gen tab can step one channel through a frequency ×
amplitude sweep, 0 V to Vpp by default, with every point read back into a
CSV, and a new Set to Vpp/2 button fills DC Offset for a 0 V to Vpp drive.
The LCR sweep checks every reading and realigns the meter before it starts,
the LCR takes 20 Hz, and neither sweep overwrites an earlier CSV any more.
None of this is bench-checked (the checks are in #369), and the Signal Gen
sweep sends the 4055B a read drain it has never had from this app, so
BENCH_TEST §T step 3 must pass before anyone sweeps with the Trek connected.

### Signal Gen tab

- **Stepped sweep, frequency × amplitude** (#500). A new section between
  the channel tabs and Presets steps one channel, SINE or SQUARE, through a
  frequency axis and an amplitude axis (each a range or a list, as on the
  LCR sweep), with a dwell per point. "0 V to Vpp (offset = Vpp/2)" is
  ticked by default, so every point's offset is half its amplitude;
  unticked, a fixed Offset is used. Each CSV row holds what was asked and
  what the generator read back, and whether they match.
- **What a sweep refuses and checks.** It runs only with the channel's Load
  at High-Z and Polarity at NOR, refuses any point beyond ±10 V (the
  4055B's High-Z limit), and asks once (default No), naming the channel,
  the lowest and highest volts and "1 V = 1 kV". It switches the channel
  OFF, sets point 1 and reads it back, and switches it ON only on a match.
  Between points the frequency changes first, then the amplitude and offset
  in the order that keeps a 0 V to Vpp drive from dipping below 0 V. A
  read-back that differs is marked `no` (there is no frequency cap, so a
  generator clamp shows there); one more than 10 mV outside the band the
  question named, or one that cannot be read or answers for another query,
  stops the sweep. On the SLDEA bench the Trek inverts, so the HV there runs
  from 0 to minus Vpp kV.
- **OFF is believed only when the generator reads it back.** The sweep
  switches the channel OFF at the end, on Stop Sweep, on that channel's
  Output button and on any error, then reads the output state. If it cannot
  confirm OFF, an "SG CHn NOT SWITCHED OFF" box says to switch it off on
  the front panel, and the Output button stays red.
- **The swept channel is locked while the sweep owns it.** Apply, Fire,
  the Waveform Editor's upload, preset and profile loads, the Webcam
  stepped capture and the timed capture's trigger are refused on it; its
  Output button means Stop. Reconnect, Restart now and Update Software are
  refused while any sweep runs. An SLDEA run, DRY or LIVE, will not start
  on the swept channel, and a sweep will not start on the channel a running
  SLDEA run is set to. The other channel stays usable.
- **An arb upload to the other channel stretches a point's dwell.** The
  upload holds the generator's I/O lock for its whole transfer (as before
  this release), so the sweep's next point waits for it and that point is
  held longer than its dwell.
- **The read drain is bench-unverified instrument I/O.** At its start,
  before every point's read-back, before the final output read and before
  the panel read-back at the end, the sweep drains stale replies from the
  4055B (`VisaInstrument._drain`: up to 20 reads with a 60 ms timeout, until
  nothing comes). This app had only ever
  done that to the LCR meter, and the 4055B has wedged over USB on unusual
  traffic before (a wedged box takes writes into the void until a front
  panel power cycle). BENCH_TEST §T step 3 checks it over USB with three
  back-to-back sweeps, and must pass before anyone sweeps with the Trek
  connected.
- **A new CSV at every Start** (#500). With Output CSV blank, every Start
  writes a new `sg_sweep_<timestamp>.csv` in the log folder, names it in the
  status line and leaves the field blank. A typed file that already exists
  is asked about (default No) before the sweep's question.
- **Set to Vpp/2** (#499), beside DC Offset wherever Amplitude shows (not
  for DC), fills DC Offset with half the amplitude, so the waveform runs
  from 0 V to Vpp. It sends nothing; Apply sends it like a typed value. The
  Signal Gen Usage Tips were tightened to fit it, with every safety line
  unchanged.

### LCR tab

- **The sweep checks every reading** (#497). A reply to `:FETC?` that is
  not three numbers is now drained and asked for once more, and a second
  bad one stops the sweep with the meter's reply quoted. Before, a sweep
  stopped on its first sample with "not enough values to unpack (expected 3,
  got 1)", and when the meter had fallen one reply behind with a reading as
  the stale reply, every later sample was the previous one's reading,
  silently.
- **The sweep realigns before it starts and holds the meter** (#497). It
  drains the meter's input once before its first sample, and from Start to
  its last sample Apply Configuration, Single Measurement, the config sync
  and the corrections are refused. A Start while the meter is busy starts
  nothing. No new SCPI: the LCR meter already had this drain.
- **20 Hz to 500 kHz** (#497), the 894's specified range, for Apply and the
  sweep's frequency axis; the floor was 100 Hz.
- **A new CSV at every Start** (#500). The sweep wrote its made-up file name
  back into Output CSV, so the next Start overwrote the first sweep's file.
  A blank field now gets a new `sweep_<timestamp>.csv` at every Start and
  stays blank, and a typed file that already exists is asked about first
  (default No), before the live readout is stopped, so No changes nothing.
  A log folder that cannot be made is now said in a box.

### Manual

Rebuilt for this release, the first rebuild since v1.4.6, so it also
carries v1.4.7's Usage Tips text, area plot and diagnostic figures and the
page-flow fixes of #491. The Signal Gen chapter covers the sweep and Set to
Vpp/2, the LCR chapter says 20 Hz (below 100 Hz not bench-checked yet), and
the LCR caution on a bad value says what Apply had already sent (#490's
wording, hidden until now by an older override). Part II no longer says the
watchdog reads the current at exactly 2 Hz: 0.5 s is a gate, and LIVE runs
record a 0.56 s median tick (#424, corrected in `SLDEA_DECISIONS.md` on
2026-10-08 but not in the manual).

### Tests

New suites for the Signal Gen sweep (69 tests), the LCR reply check,
realign and CSV path (17) and Set to Vpp/2 (6).

### Not bench-checked

The lines are in #369, section 2: BENCH_TEST §T for the Signal Gen sweep
and Set to Vpp/2, starting with the read drain in step 3 (Trek HV off);
the LCR sweep after a desync-prone step and the 20 Hz floor (#497); and
the LCR sweep's new CSV at every Start.

## v1.4.7 (2026-10-21, pre-release)

**TL;DR:** A window close during a LIVE run can no longer let the run's own
start-up writes switch its signal generator channel back on, and when the
close has already zeroed the channel, run.log says so instead of a false
FAILED TO ZERO alarm. Usage Tips open in a window you can resize and scroll,
at about half their old length. The manual was not rebuilt for this release,
and none of this is bench-checked yet: the checks are in #369.

### SLDEA test tab

- **A LIVE run's first SG writes are made under the SG's I/O lock** (#492).
  Load and polarity, DC at 0 V and output ON now go out holding the lock,
  with the stop checked again under it. Before, a window close that came
  while those writes waited behind a long Continuous Logging query could
  switch the outputs off first, and the queued writes then switched the
  run's channel back on at 0 V. Nothing new is sent; only the order and the
  locking changed.
- **run.log tells the truth after a window close zeroed the run** (#493).
  When the close has set the run's channel to 0 V and switched it off (or
  switched off the channel of a run that never switched it on) and closed
  the SG session first, the run's own zero finds the session closed. The
  log now says what the close did, instead of "FAILED TO ZERO THE SG
  OUTPUT" and the HV NOT ZEROED alarm. Every other failed zero keeps the
  full alarm, and the SCPI sent is unchanged. ■ Abort is still the way to
  end a run.
- **A program the tab started is watched for 30 s** (#488). The tab stopped
  watching Edge Review, the tuner, the plot window and the video review once
  they said "opened" at 2 s, and on some Windows PCs a start is held about 5 s, so a
  later death went unreported. Such a death is now reported like an early
  one, in a box that waits for a running SLDEA run to end. The video review
  exits cleanly after its own "no video yet" box, so no second box follows.
- **The live view draws the pre-flight's reticle** (#489): one white
  reticle on a black halo for both camera views, instead of cyan.

### Edge Review and the SLDEA tools

- **The area plot marks each frame as the preview does** (#487). In
  `area_vs_voltage.png` the camera warm-up is an open circle, the 0 kV
  baseline a red diamond, post-ramp a blue triangle and pre-ramp a yellow
  square, with the preview's legend words. The warm-up's circle is drawn
  larger and underneath, so a warm-up and a baseline of one area show as
  the red diamond inside a ring. Before, the baseline was a black triangle,
  post-ramp a circle and the warm-up frame was missing. Both plots now take
  their marks from one table in `sldea_preview.py`. The plot window keeps
  its own shapes for the legs and advisories.
- **Each diagnostic map has a color bar** (#486) that says what dark means,
  numbered in the map's own values. Since v1.4.6 the maps draw high values
  dark, the reverse of magma, so without a key an old `sldea_diag.png` and
  a new one read in opposite directions. The bad-data gray is set with
  `with_extremes`, which drops matplotlib's pending-deprecation warning
  without changing a pixel.
- **Edge Review moves a letter tag off an earlier one** (#491), so the B and
  C tags no longer overlap, and the tuner's self-test discs get soft edges.

### Instrument tabs

- **Usage Tips open in their own window** (#490). Each tab's Show Usage Tips
  button opens a window that resizes, scrolls and stays above the app,
  instead of the narrow message box that wrapped the text down the screen.
  The six tips are cut from 2082 words to 1135, with the safety lines first
  and worded to match what the code does: closing the app only tries to
  switch the SG outputs off, Restart leaves them as they are, and a LIVE run
  ends with ■ Abort. The facts that no longer fit moved into the manual's
  sources, so they reach the manual at its next rebuild.

### Tests

- **A new suite catches the #468 bug class** (#484) without building a
  window: it fails when a function rebinds an imported name such as `uc`,
  or reads it above its own local `import`.
- **Two flaky load tests check their own timing** (#485), the webcam
  auto-start and live view tests; the app was not at fault.
- **Pixel tests** for the contact sheet's foil outline, the two-point
  calibration's chord and the pre-flight's reticle (#489).

### Manual

Not rebuilt for this release; the committed manuals and the latest PDF are
still v1.4.6's. Its Usage Tips text, area plot and diagnostic figures, and
the page-flow fixes of #491 come with the next rebuild.

### Not bench-checked

The lines are in #369: the start-up writes under the lock (#492, section 3),
the 30 s launch watch with a program killed after it opened, including the
Linux signal case, and the video review's single box (#488, section 1), and
the Usage Tips window on the Linux bench (#490, section 1).

## v1.4.6 (2026-10-21, pre-release)

**TL;DR:** The SLDEA tab loads on the Linux bench again; in v1.4.5 it did not
(#449). Every color the app draws or writes in is now a Paul Tol
colorblind-safe one, so OK reads blue, warnings and errors brown, and a red
button means HV can be on. Closing the window during a LIVE run now sets the
run's signal generator channel to 0 V before it switches the outputs off.
None of this is bench-checked yet: the checks are in #369.

### SLDEA test tab

- **The tab loads on the Linux bench** (#449, a v1.4.5 hotfix on main since
  2026-10-09). The DRY RUN box's check mark read its border and padding with
  `int()`, and the bench's Tk gives those in units, so the tab said "This tab
  failed to load". The sizes are now read as pixels, and a surprise there
  leaves the theme's plain box instead of a dead tab. Edge Review's radio
  dots had the same flaw and the same fix.
- **Window close zeroes a LIVE run's channel** (#460). If a LIVE run has not
  stopped within the close's wait of about 3 s, the close sets the run's SG
  channel to 0 V, then switches both SG outputs off. Before, the run's last
  level stayed set, and the next Output ON put it back on the Trek. Once a
  stop is asked, the run writes no new level; the stop is checked again
  under the SG's I/O lock. ■ Abort is still the way to end a run.
- **■ Abort is described as what it does** (#452): the run's SG channel to
  0 V in one write, then its output off. The run log, a tooltip, the manual,
  BENCH_TEST §O and CLAUDE.md said "ramp"; the code never ramped. Words only.
- **The run folder line keeps track of its typing pause** (#459). When the
  poll checked the folder itself, the pause the last key had armed still
  fired, checked the same folder a second time, and could not be cancelled
  when the window closed.

### Colors (Paul Tol, colorblind-safe)

- **Words and banners** (#462). Status lines, readouts, hints, tooltips and
  banners in every window take their colors from one new module,
  `ui_colors.py`, and every word reaches 4.5:1 on the Linux bench's gray. No
  Tol green does both jobs, so connected, done and OK are blue; warnings and
  errors share one brown, and the words or the ⚠ say which. On a button, red
  means energized: the LIVE ▶ Run button and Output: ON on the Signal Gen and
  PSU tabs. The DRY ▶ Run button is blue, the DRY RUN row pale blue and the
  LIVE row orange.
- **Edge Review's candidates** (#450): A cyan, B blue, C yellow and D white,
  each outline on a black edge so it shows on the gray membrane. Outlines
  are 2 px wider than before (4 px, 5 px selected). Under color blindness the
  old B and D were nearly one color.
- **The SLDEA tools** (#454): the tuner, the diagnostic sheet and figure, the
  calibration dialog, the hand tracer, the area plot, the overlay export and
  the camera pre-flight reticle. In the calibration dialog and the tracer
  only the colors changed, not one width, dash or halo, because a wider line
  moves where people place points (#215). Trace labels and calibration
  round-sets now record `palette: tol-454`, so a record made in the old
  colors can be told from a new one.
- **The SLDEA preview's 0 kV baseline diamond is Tol red** (#461), not gray,
  which missed the color-blind floor beside the pre-ramp and warm-up marks.
- **The diagnostic's maps use Tol's iridescent scheme** (#461) instead of
  magma. High values are now dark and low values pale, the reverse of magma,
  so an old diagnostic sheet and a new one read in opposite directions.

### Diagnostics and tests

- **Three tests that failed on loaded Windows PCs with the app correct**
  now check their own premise: the hanging-share test (#453), the run folder
  line's timer tests (#459), and the launch check (#458; on one PC about 1 in
  30 Python starts is held for about 5 s before Python runs).

### Not bench-checked

The lines are in #369: the SLDEA tab and Edge Review loading after Update
Software (#448), the window close during a LIVE run (#460, section 3), and
the new candidate outlines and the calibration and tracer colors on a real
run (#451, #456, section 1).

## v1.4.5 (2026-10-08, pre-release)

**TL;DR:** The SLDEA tab has a new layout with the presets on top and Run in
view without scrolling, shows the folder a run will write to, and refuses a
run name that would overwrite an earlier run. "Energize HV?" now says whether
the breakdown watchdog is on, and a second breakdown rule runs in shadow only:
it logs what it would have done and stops nothing. The Webcam tab sets and
locks the camera in one press, check boxes and radio buttons on the Linux
bench show a check mark and a dot, and none of this is bench-checked yet: the
checks are in #369.

### SLDEA test tab

- **A new layout** (#437). Run configuration presets sit across the top, the
  settings in a left column and the kV preview in a right one, then the run
  row and the log. The tab is 883 px tall instead of 1183: nothing scrolls at
  1320 x 990, and the whole ▶ Run button shows at 1024 x 768. Every control,
  label and tooltip is kept. The preview's snapshot markers are about 14 %
  smaller, and the pointer finds them from as far away as before (#430).
- **The folder a run will write to** (#435). A line under Run name reads
  "Saves to:" and the folder, and warns as you type. ▶ Run refuses, before any
  HV question and with no "start anyway", a folder that already holds a run
  (setup.txt or data.csv), a run name that cannot be a folder name (plain
  ASCII only: u for µ, as in 2.5uL), an Output dir on the share while the
  share is not mounted, and one that does not answer within 3 s. Before, a
  run name used twice made the second run write over the first. On Windows
  the built-in Output dir is a Linux path under the share, so a DRY run there
  is now refused as "share not mounted" until Output dir or `SCPI_SLDEA_DIR`
  names a real folder.
- **"Energize HV?" names the breakdown watchdog's state** (#433): ON with its
  Trip and Confirm, or OFF and why. run.log's start line and a new setup.txt
  line record the same. The box stays ticked by default. ▶ Run now refuses a
  ticked LIVE run whose Trip or Confirm is not a positive number (a nan or a
  zero used to be armed as typed), and a run whose watchdog state changed
  while a question was open.
- **A ticked LIVE run always arms its watchdog** (#446). When a scope
  Reconnect is still running as the run reaches its arming line or its 0 kV
  baseline, the run waits for it at 0 V, with ■ Abort checked and all waits
  within one 25 s bound, then takes the baseline and arms. With a short
  baseline (fewer than 4 of 8 reads) or no scope at all, it arms on the
  absolute rule, |I| ≥ Trip, and run.log and setup.txt say so; with no scope
  it reads nothing until a later Reconnect succeeds. Only a stop (■ Abort or
  the window closed) leaves a run NOT ARMED, which replaces #433's NOT ARMED
  record for a run that lost its scope. A run with no scope when ▶ Run is
  pressed is unchanged: "Energize HV?" says OFF and it does not arm.
- **A second breakdown rule runs in shadow** (#434). On every LIVE run with
  current reads, the N-sigma rule watches beside the 100 µA / 3 s watchdog: a
  read 5 sigma or 20 µA (whichever is larger) away from the run's recent
  quiet reads, twice in a row, would trip it. It acts on nothing. It marks a
  would-trip in telemetry.csv, and after the run lists its away reads in
  run.log and its verdict in setup.txt. Replayed on the 18 single-layer runs
  on file, it made no false trip and caught a breakdown the watchdog missed.
  The watchdog still stops runs; the shadow lines from LIVE runs will decide
  whether the rule may act.
- **setup.txt's camera block** (#436) now records the white balance, the
  camera device, pixel format and frame size, and every locked control, not
  only exposure and gain.
- **Programs started from the tab say whether they opened** (#445). Edge
  Review, the tuner, the plot window and the video review read "starting" on
  the status bar, then "opened" once they have run for 2 s. One that fails
  before then is named there, with a box giving its exit code, its last lines
  and its log file; during a run the box waits until the run has ended, so it
  never covers ■ Abort. What these programs print now goes to `launch_logs`
  in `~/.cache/scpi_control` (or `$SCPI_CACHE`), not to `launch.log`.

### Webcam tab

- **Auto-set camera** (#436). One press stops the preview, pins gain at 0,
  finds the exposure for a mid-gray picture, balances the white on the scene
  in view, locks and saves it all, and starts the preview. A step that fails
  says which and leaves the previous lock. 🔒 Apply & Lock now sits beside the
  exposure and gain boxes, and a value typed there but not locked is named on
  the status line. Every other control and the single steps (Read camera,
  Auto-expose, Auto-WB once, Stabilize) sit under "Advanced camera settings",
  closed when the tab opens. The focus score is on by default and its label
  is larger.
- **Stabilize and Auto-WB once search the scene in view** (#436). Before,
  every trial picture was shot at the locked values, so they found the lock
  again. Both now put the lock back on the camera when they end (#441).
- **A lock that set nothing is a failure** (#436). Apply & Lock on a panel the
  camera reported no controls for used to clear the previous lock and save
  over it; now it keeps the previous lock and says "Nothing locked".
- **Refresh and Read camera refuse while a camera adjustment runs** (#436,
  #441). They used to put a trial exposure into the boxes a run takes.

### All windows

- **A check mark and a dot on every platform** (#431, #432). A ticked check
  box shows a white check in a Tol-blue box, and a selected radio button a
  blue dot in a ring, instead of the Linux bench theme's filled square and
  filled diamond. The DRY RUN box and Edge Review's candidate rows get them
  too. Nothing changes size on Windows; on the bench theme a check box is
  3 px wider.

### Diagnostics and tests

- **`run_tests.py` fails a suite that reports no test** (#442). The Trek
  polarity suite had run nothing while listed as ok; it now runs its three
  tests, and the sweep plan suite no longer stops at its first failure.
- **The plot window cancels its queued redraws when it closes** (#443), and
  its tests fail on a leaked callback instead of sweeping it up.
- **Edge Review's calibration question box hands the grab back by name**
  (#444): hardening against a KeyError that no path reaches today.
- **The watchdog's 0.5 s cadence is a gate, not a validated period** (#440).
  LIVE runs record a median tick of 0.56 s and gaps up to 1.45 s. Comment and
  decision log only.

## v1.4.4 (2026-10-08, pre-release)

**TL;DR:** Everything that reached `main` after v1.4.3, and none of it has been
checked on the bench yet: the checks are listed in #369. The SLDEA tab now
shows the camera live during a run, records the film thickness, and checks the
video codec before any HV; the plot window groups runs by material and can plot
against the electric field. Data Logging is now Continuous Logging, and the
Webcam tab starts its own preview.

### SLDEA test tab

- **Live camera view during a run** (#386). A window opens with each run: a
  video run's stream, or a stills-only run's newest still labelled with its
  step and age, with the pre-flight reticle, the commanded kV and the exposure
  verdict of the frame on screen. It only reads frames the run already holds,
  so it never opens the camera; the run waits at most one view tick, about
  10 ms, for it. A dead stream stays red through ■ Abort, and a video run
  whose stream gives nothing in its first 5 s shows its stills under a red
  VIDEO STREAM DOWN banner (#413).
- **Film thickness** (#416). A "Film thickness (µm)" box under Concentration,
  measured with the film mounted and prestretched, checked at ▶ Run like the
  concentration and written to setup.txt as `Film thickness: 50 um`. A blank
  box or a value outside 5 to 2000 µm asks before the run starts, default No.
- **The video codec is checked at the camera's own frame size before any HV**
  (#379), and the run stops at 0 V if that frame cannot be recorded
  losslessly. The "Unknown C++ exception" behind it was FFmpeg 4.4 reading
  1 KB past every gray frame; frames are now laid out so that read stays in
  the app's own buffer. The check gives up after 15 s, and setup.txt now ends
  with one `Video outcome (end):` line: the frames recorded, or NOT recorded,
  and why the video stopped (#412).
- **Video review from the SLDEA tab and the plot window** (#417): a 🎞 Video
  review… button for the run that just ended, and an entry in the plot
  window's right-click menu on a run. The review runs as its own program, so
  a decoder stall cannot take the main window or the plot window down.
- **The post-run video job shows its progress** (#418) on a line under the run
  row ("detecting edges 120/438", "copying video.mkv into the run folder",
  "ready in the run folder"), including the re-run Edge Review's Save starts.
  The job runs at low priority, and Edge Review's Save writes its files on a
  worker thread behind a "Saving n/N" box, so neither window looks hung. Every
  file Save writes is byte-identical to before.
- **New folder… beside Browse** (#410) on the SLDEA, Webcam and Continuous
  Logging tabs, because the bench's folder dialog cannot make one. Browse
  opens at the folder in the box. During a run the SLDEA tab's two buttons
  refuse with a note, and during a LIVE run New folder… refuses on the other
  two tabs as well, because it works on the share from the thread the HV
  worker waits on.
- **The run video stays full-frame** (#387): a crop changes what the edge
  detector measures. Decision log only.

### Plot window

- **Group by material** (#382): a button fills the groups from each run's
  `Compliant electrode:` line, and "...and by concentration" splits each
  material further. Each group mean draws in its material's line style.
- **The run list is a table** (#383) with the run, its electrode material and
  its group; click a heading to sort, right-click to move runs between groups.
  Material is re-read from setup.txt whenever a grouping change acts on a run,
  click-drag selects a range again, and four layout fixes come with it (#415).
- **Field axis** (#416): a third x axis, the nominal field V / t0 in V/µm, for
  runs whose setup.txt records the film thickness (`--x field` on the command
  line). Runs without it are left off that axis by name.
- **The caption fits the figure** (#380, #420). Every caption line is wrapped
  at its measured width, and grouped captions lay out faster (a six-group
  figure draws in about 200 ms instead of 360). In the window only, a caption
  too tall for a small window is cut with a row saying so; exports always
  carry the whole caption, and the toolbar's Save does too. A run legend that
  covers data moves below the panels.

### Continuous Logging (was Data Logging)

- **Renamed, with a cadence in seconds or Hz and live min and max** (#384).
  The loop samples on a fixed time grid, so "2 Hz" means two samples a second.
- **A meter's overload code can no longer become the Max** (#409), and a source
  whose first read fails gets a "(read failed)" row. The CSVs and the
  instrument loop are unchanged.

### Webcam tab

- **The preview starts when the tab opens** (#385) and stops when you leave it,
  unless interval capture is running. When it is off, the view says PREVIEW
  OFF in large text with the reason, over the last frame dimmed.
- **It comes back once by itself** when what held it off ends (#411): Apply &
  Lock, an SLDEA run, a timed capture or a dialog. It never takes the camera
  from a run, a capture or an adjustment, and Stop Preview holds for the visit.

### Diagnostics and tests

- **Window freezes are logged** (#414). The main window, Edge Review and the
  plot window write one record to `tk_stall.log` (in `~/.cache/scpi_control`,
  or `$SCPI_CACHE`) each time they freeze for more than 0.3 s, with the stack
  of where they were stuck. Nothing that causes a freeze changes yet: run it on
  the bench through a working day and send the log.
- **The edge-GUI test flake is fixed** (#419): a hover tip's timer could stop a
  test's window teardown half way. #280 stays open for a re-run on a lab PC.
- **The plot suite's byte check runs again** (#408) in every clone.
- `sldea_preview.py`'s docstring cites the CVD floor by method (#381).

## v1.4.3 (2026-10-06, pre-release)

**TL;DR:** Two fixes that reached `main` after v1.4.2. Neither has been
checked on the bench yet. Update Software → Restart now reopens the app on
the new version instead of the old cached copy. The camera pre-flight refuses
a flat picture, and a run stops itself if its baseline photo is flat or
missing, unless you chose to start anyway at the pre-flight. The bench checks
are listed in #369, section 4.

### Tools

- **Restart now loads the new version** (#340). Update Software deploys to
  the shared drive, but Restart now re-ran this PC's cached copy of the app,
  so the old version came back. Restart now runs what the desktop icon runs,
  which refreshes the cached copy first: the app is gone for about half a
  minute, then opens on the new version. Restart is still not a shutdown:
  signal generator outputs and LCR bias stay as they are during the gap, and
  if the new version fails to start the app does not come back by itself, so
  switch outputs off first if they must not be left unattended. Close Edge
  Review, tuner and plot windows first, because the refresh replaces the
  files they run from. Restart is still refused during any SLDEA run. The
  update that first installs this fix on a PC is restarted by the old code,
  so start the app from the icon once after it. **Not bench-checked**
  (checks A and B in `deploy/BENCH_PC_NOTES.md`).

### SLDEA test tab

- **The camera pre-flight refuses a flat picture** (#348). On 2026-10-01 a
  LIVE run went to 3 kV for 209 s on a flat dark gray picture, after a
  pre-flight that said "exposure OK" and started on Return. A frame whose
  central window spans less than 20 gray levels (5th to 95th percentile) is
  now treated like a blown-out one: the dialog says NO PICTURE in bold red,
  the start button reads ⚠ Start anyway (no picture), and pressing it asks
  again, with No as the default. Return now starts a run only from a clean
  pre-flight. Any warning, a picture check that could not run, a preview not
  taken with the run's settings, a built-in camera value, or a Webcam-tab
  lock that differs from the run's boxes leaves the focus on ✎ Adjust
  instead. Every pre-flight is logged with its verdict.
- **A run stops itself at a flat or missing baseline photo** (#348). The
  0 kV baseline photo is checked as the run takes it. If it is flat, or the
  camera gives no frame for it after giving the pre-flight one, the run
  stops through the same path as ■ Abort (SG offset 0 V, output off) and
  says why in a box. The baseline is shot as the first ramp begins, so on
  the default ramp the stop comes about half a second in, at about 12 V
  commanded; `run.log` prints the number. A run whose pre-flight got no
  frame at all, and that you continued past the existing "No camera frame
  available" question, is unchanged.
- **⚠ Start anyway (no picture), then Yes, is a deliberate override**
  (#348), for a faint device you will review by hand. It carries into the
  run, DRY or LIVE: the baseline is still checked and logged, but the run
  carries on, and `run.log` and setup.txt (a `Pre-flight override:` line)
  record it. No other "start anyway" is an override. Edge Review does not
  read the setup.txt line yet.
- **The tab says which camera settings a run would use** (#348). A line
  under ▶ Run gives the exposure and gain the run takes from the Webcam
  tab's boxes. It turns amber, with the reason in words, when a value is a
  built-in default or when the Webcam tab has locked different values.
- All four are **not bench-checked** (BENCH_TEST section S).

### Manual

- Both manuals are regenerated at v1.4.3. The Tools chapter says what
  Restart now does after an update, and the SLDEA chapter covers the camera
  line, when Return starts a run, and the baseline stop with its override.
- The PDF's SLDEA control table prints whole again. In v1.4.1 and v1.4.2 one
  long label pushed its description column off the page, so those
  descriptions were cut off; the build now refuses a label that long. The
  PDF is 63 pages instead of 66.

## v1.4.2 (2026-10-06, pre-release)

**TL;DR:** Analysis only: nothing that drives an instrument or records a run
changed. Backlit runs whose disc fit used to refuse now fit, and a new
🎞 Video review… window in Edge Review shows only the video frames that
disagree with your accepted stills. The video parts are **not** bench-checked
yet (BENCH_TEST section Q, now with Q16 and Q17), so treat their flags as
advice.

### Edge Review

- **A disc fit that refuses now retries from the center of the window**
  (#365). On backlit run 13_backlight_2 the disc is only about 6 gray levels
  darker than its surround while the backlight falls off by about 15 across
  the window. The fit seeded on the dim side of the backlight and refused, and
  without it Edge Review rejected all the other frames. When the first fit
  refuses, it now retries from the center of the search window and judges the
  disc against the ring just outside it instead of the frame-wide median. Fits
  that already succeeded are unchanged (the ten original corpus fits are
  bit-identical). 13_backlight_2 now fits at 407 px and P3_7 at 541 px; open
  such a run again, ▶ Detect Edges and Save. On 13_backlight_2 the hand anchor
  (425 px) sits at the outer foot of the disc edge, so re-check its scale in
  verify mode (#369).
- **Save re-runs the video pass, and 🎞 Video review… shows the frames worth a
  look** (#366). The video edge pass used to run once, right after the run and
  before anyone calibrated, and nothing read it again: on 13_backlight_2 all
  438 frames came out flagged with no area. Save now re-runs it in the
  background whenever its edges are out of date (the status line says so, and
  `run.log` records the result), and `video_edges.json` records what each pass
  ran with. Each video frame is checked against the run's accepted stills,
  after the run-wide offset between the two is divided out (-1.19 % on
  13_backlight_2). A frame goes to a person only when the detector doubts it,
  when it reads more than 2 % off the stills of its landing, or when, between
  landings, it spikes or a 2 % step lands on it. The new button (or
  `python sldea_video_review.py RUN`) steps through those frames with the
  detector's outline and records accept or reject in `video_review.csv`;
  `data.csv` is never touched. **Not bench-checked** (BENCH_TEST Q16, Q17).
- **A window the SLDEA tab opened for one run closes after a clean Save**
  (#367, for #363). Any warning or scale caveat keeps it open with its
  message. A window you opened yourself (the multi-run batch cockpit) stays
  open, and so does an auto-opened window you switched to another run.
- **The session clock stops when detection ends** (#368, for #364), so
  nothing on the toolbar is still counting once the machine is done. The next
  ▶ Detect Edges starts it again. The value it keeps is the time at the stop;
  it could be a second old, and a pass run without the event loop (the manual
  capture) left it at 0 s.
- **A failed write to setup.txt is shown instead of overwritten** (#370,
  #371). When Save or a scale-only re-anchor could not record the scale
  anchor in setup.txt, its warning was replaced a moment later by the "saved"
  or "RE-ANCHORED" line, although `data.csv` had already been written at that
  anchor. The warning now stays on the final status line with what to do:
  after a Save, Save again once the folder is writable; after a re-anchor,
  re-anchor again and measure afresh, since Reuse offers the old anchor.

### Manual

- Both manuals are regenerated at v1.4.2. The companion tools chapter now
  covers 🎞 Video review… and the video re-run at Save, and the SLDEA tab's
  Auto-open entry says when that window closes itself.

## v1.4.1 (2026-10-05, pre-release)

**TL;DR:** A bugfix release. "Trek inverts" is ticked by default and only
flips the control, so a correctly set run reads positive kV. The camera
pre-flight now shows exactly the exposure the run will use, after a backlit
run whose pre-flight looked fine came out blown out. Edge Review's
calibration questions are short, open on top, and have buttons that say what
they do. Also new: optional lossless video beside the snapshots, which has
**not** been bench-checked yet (BENCH_TEST section Q), so leave Record
unticked on important runs until it has.

### SLDEA test tab

- **"Trek inverts (negate control)" starts ticked, and negates the control
  only** (#354). Every run on file read negative kV with it unticked: on this bench
  V_Out reads the opposite sign to the control. Ticked, the run now sends a
  negative control and nothing else changes: the scope check frames V_Out
  from 0 to +kV, and both monitors are logged as read, so a correctly set
  run reads positive. Until now a ticked box also framed V_Out for 0 to -kV
  and multiplied both readings by -1, which put a correctly set run
  off-screen and logged it negative. setup.txt records "INVERTED ...
  monitor readings logged as read"; Edge Review's sign note now also fires
  when a ticked run reads negative, which means that Trek does not invert.
  A preset still sets the box either way.
- **The camera pre-flight shows what the run will shoot** (#361). On run
  13_backlight the pre-flight picture looked fine and all 60 run frames came
  out 57 to 66 percent saturated. The pre-flight was shot at the Webcam tab's
  locked exposure, but the run uses the Webcam panel's exposure field, and
  the two differed. The pre-flight now uses the run's settings, and when the
  fields and the lock differ it says so in red ("exposure 20 (locked: 4)")
  and points at Apply & Lock. A stale camera settings file could also bring
  old values back into the panel at start; the newer of the two settings
  files now wins.
- **Optional lossless video beside the snapshots** (#359). Tick Record and
  the run also records grey FFV1 video at 1 to 2 fps, with each frame's time
  and commanded kV in `video_frames.csv`; snapshots and `data.csv` are
  unchanged, and Edge Review's detector can run on every frame afterwards.
  **Not bench-verified** (BENCH_TEST section Q, including a live run with
  the Trek HV disabled). With Record ticked, ▶ Run refuses to start beside a
  Webcam-tab sweep on the other channel, and waits for a previous run's
  recorder to release the camera.
- **The run preview marks snapshots by shape** (#357): ▲ post-ramp, ■
  pre-ramp, ◆ baseline, ○ warm-up, in Tol colours with a legend and hover
  text, instead of green and red alone. The two timing fields share one row,
  "Snapshots each landing", named after the snapshot each one moves.

### Edge Review

- **Calibration questions are short, open on top, and name their buttons**
  (#355, #356). When the disc fit refuses a poor baseline and you measure by
  hand, the checks that follow used to be long Yes/No boxes that could open
  behind the calibration window. They are now short boxes with buttons such
  as "Use unchecked scale" / "Cancel", owned by the calibration window. The
  re-anchor question reads "Write data.csv now" / "Keep for next Save" /
  "Cancel". Enter and Esc still pick the safe button; what each answer
  records is unchanged.
- **A run whose disc fit refuses the baseline still gets its A0** (#353).
  The baseline row takes its resting area from the hand-measured scale
  anchor, so the plot no longer drops such a run in area mode. The row says
  where its A0 came from.
- **The trace window no longer jumps sideways** while you place points
  (#360). Its status line grew wider as the area gained digits and widened
  the window.

### Plot

- **Up/down runs are drawn leg by leg** (#358): ▲ rising, ▼ falling, with
  arrows in the direction of travel, instead of one averaged point per kV.
  A new elapsed-time x axis (`--x time`) unrolls any run; `--merge-legs
  --no-arrows` gives the old figure back. The tidy CSV gains `elapsed_s`,
  `leg` and `cycle`. A double-click on the strain-percent panel now opens
  the right frame.

### Manual and tests

- **Manual screenshots fixed** (#352). The v1.4.0 manual was captured on a
  175 percent display with a scaling workaround that left the Arb Editor and
  the dialogs cramped and several callouts off target. The capture now pins
  Tk to 96 dpi; both manuals are regenerated.
- The manual's SLDEA chapter shows the tab in two annotated screenshots:
  the new video row made it taller than one, and the run buttons had fallen
  off the first.
- The Arb Editor's "Upload && Select" button now reads "Upload & Select".
- The plot's byte-identity test was failing on every machine since the
  provenance columns were added to the tidy CSV; it now drops them by name
  and passes.

## v1.4.0 (2026-10-05)

**TL;DR:** The area measurement is fixed. Until now the resting area was a
circle fit and every expanded area was an ellipse fit, and the two disagreed by
up to 7 percent on the same photo, so every strain curve carried a run-specific
offset and a step at low voltage. Both are now measured from the same edge rays.
Saved runs reviewed under the old method must go through Edge Review again, and
the plot refuses them until they have. Edge Review also tells a new student up
front whether a run can be measured, the hand-calibration dialog can no longer
accept a guess, and a one-page quickstart takes a student from the bench to a
plot.

**Re-review before plotting.** Old and new areas are not comparable. Opening a
saved run in Edge Review and pressing Save stamps the new method into
`setup.txt` and empties any unreviewed row that still holds an old automatic
area; until then the plot leaves that run off the area axes. The only reviewed
campaign run on the share at release time, DOT_P3_1, still needs this.

### Measurement chain

- **One estimator for A and A0** (#344). A tracked frame's area is the resting
  area times the ratio of summed squared edge radii over the rays measured on
  both the baseline and the frame. No shape model in the number, no
  extrapolation across the sectors hidden by the leads. Quiet frames at 0 to
  0.5 kV read 1.000 within 0.1 to 0.3 percent per run; the step at the
  resting hand-over (3.8 to 8.8 strain points per run before) is gone; tracked
  rows agree with an independent fit-free edge measurement within 1 point up
  to 4 kV. Low-voltage frames are now measured instead of written as exactly
  the resting area.
- The spread figure on a tracked frame is a block bootstrap over angular
  sectors; nothing calls it a confidence interval any more.
- A reading from a one-sided set of rays (one-sidedness above 0.6) or one
  where the trim dropped more than a fifth of the rays stays on the card for
  the reviewer but never auto-accepts (#344). On the 899-frame review corpus
  that routes 21 rows to a human that auto-accepted before, and no accepted
  area moved.
- **Tracker range** (#345). The boundary tracker now searches out to 1.70 and
  accepts fits up to 1.75 times the resting radius (it stopped at 1.38 and
  1.30, written when 1.25x area was thought to be a full ramp), so the flat
  shoulder frames before buckling get a real edge. A clean tracked frame is no
  longer sent to review only because its landing partner found a patch.
- Every Save stamps the estimator version, the baseline's provenance, the
  tracker window limits and the OpenCV and numpy versions into the run's
  `setup.txt` edge-settings block, and the plot's tidy CSV carries them. Edge
  Review warns in one line when it runs off the pinned OpenCV.
- Pairs are one landing, not one kV, on up/down and repeat runs (#333).

### Edge Review

- **Run health on open** (#346). Picking a run shows a strip that says, in
  plain sentences, whether the run can be measured and what went wrong at
  capture: a blank or overexposed baseline, a refused disc fit, missing voltage
  or current readings, a run that ended early, a watchdog stop, missing frames,
  off-screen telemetry. On a run marked STOP, the auto-process no longer
  presses Detect for you.
- Save keeps the notes the runner wrote at capture (WATCHDOG, V_Out off-screen)
  instead of overwriting them (#346).
- A watchdog trip row counts as a confirmed breakdown unless the reading that
  tripped it was the scope's off-screen placeholder; streaks in
  `telemetry.csv` become advisory notes that never rename a frame (#346).
- **Hand-calibration guardrails** (#347). The hand modes show a
  contrast-stretched frame; a round whose circle was never moved is refused;
  a frame with no visible picture opens on a plain notice with Cancel as the
  default; rounds more than 5 percent apart are refused outright. The
  2026-10-01 anchor, three untouched circles 23 percent apart, cannot happen
  again.

### Plot

- The strain-mode uncertainty band is plus or minus 2 percent of the area
  mapped to strain points (plus or minus 1 percent on traced levels). It was
  drawn as a percent of the strain value, so it had no width at rest and was
  2.6 to 10.5 times too narrow elsewhere (#343). `--strain-pct` now works on
  the command line.
- The normalized panel can be drawn as areal strain percent, not only A/A0
  (#330).
- Runs reviewed under the old estimator are refused from area axes with a
  message that says to re-review them; `--allow-old-estimator` keeps them,
  named in the caption (#344).

### Live capture interlocks

- Run refuses to start beside a Webcam-tab sweep on its channel, and a sweep
  never writes a LIVE run's channel (#334).
- Fire and the Waveform Editor's upload obey the LIVE channel lock (#335).
- A LIVE run locks the scope channels it reads and the settings they share
  (#337); the scope's Reconnect asks first during a LIVE run (#339); Reconnect
  no longer drops the instrument when another connect is running (#336).
- Restart now and Update Software refuse while a run is going; a mid-run
  restart had left the Trek energized (#338).
- Bench-side probe for the monitor channels' coupling and on/off state (#341).
  The bench verification of these interlocks (BENCH_TEST sections M, N and O)
  is still owed.

### Documentation

- `docs/SLDEA_QUICKSTART.md`: one page from an unpowered rig to an exported
  plot, with a box of questions the lab must answer before a new student uses
  it (#342).
- Session state moved out of the repo: `PROJECT_HANDOFF.md` and
  `RUN_SHEET.md` are frozen history as of 2026-08-12, and the decision log is
  renamed from `SLDEA_HANDOFF.md` to `SLDEA_DECISIONS.md` (#350).
- The Invisicon pair is the spray: duplicate entries dropped (#329).

### Tests and platforms

- Windows test fixes: the EasyWave temp path and the plot-window resize race
  (#331); the fontconfig fix is gated on the platform it acts on (#332).
- The test suite grew from 39 to 46 suites since v1.3.0, with new cases
  across the estimator, tracker, run health, calibration and plot changes.

### Not in this release (bench-gated)

- #348, the pre-flight image gate (refuse a flat picture before HV, stop a run
  on a flat or missing baseline). Waits for BENCH_TEST section S.
- #340, Restart now through the desktop launcher. Waits for bench checks A and
  B in `deploy/BENCH_PC_NOTES.md`.

## v1.3.0 (2026-08-12), the analysis release

Runs from several folders can go on one figure and be averaged by group with
an SEM band; Edge Review no longer discards its own controls when the window
is small; the campaign corpus is consolidated under one parent and every run
records which electrode it used. Promoted straight to Latest, superseding the
v1.2.0 pre-release. Full notes:
https://github.com/Anatol-Gogoj/Digital_Multitool/releases/tag/v1.3.0

## v1.2.0 (2026-08-08, pre-release), the analysis cockpit release

The plot tool became a window on the SLDEA tab: pick runs, toggle what is
drawn, log axes, export PNG plus CSV plus a re-renderable figspec, and
double-click a point to open that frame in Edge Review. Edge Review got a
How-to panel, an unmistakable primary button, tooltips and an honest detection
clock. Pre-release pending the telemetry bench smoke. Full notes:
https://github.com/Anatol-Gogoj/Digital_Multitool/releases/tag/v1.2.0

## v1.1.0 (2026-08-05, pre-release)

A live SLDEA run records its current continuously to `telemetry.csv`; the
cross-run plot tool and the Edge Review scale gate arrived, with 28 audit
fixes. Pre-release because the telemetry sidecar had only been tested at a
desk. Full notes:
https://github.com/Anatol-Gogoj/Digital_Multitool/releases/tag/v1.1.0

## v1.0.0 (2026-08-03)

First stable release: LCR meter, oscilloscope, signal generator, DC supply and
DMM control on the Linux bench, multi-source CSV logging, battery data
processing, webcam capture, and the SLDEA test and Edge Review chain. Full
notes: https://github.com/Anatol-Gogoj/Digital_Multitool/releases/tag/v1.0.0
