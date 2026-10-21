#!/usr/bin/env python3
"""The words of each instrument tab's Usage Tips window (#480).

Each tab's "Show Usage Tips" button opens its page from PAGES in
ui_widgets.show_tips. Until #480 they were messagebox.showinfo strings of
up to 630 words, which the native Windows box wrapped down the screen in a
window that could neither grow nor scroll. Each page is now cut to what an
operator needs at the bench: the safety lines first, then short sections of
one-line bullets. The long explanations are in the user manual
(docs/manual-src/content.json, the same tab's entry), and each page's last
line names its section there.

A page is Page(title, heading, sections, manual). A section is
(heading, lines) or (heading, lines, ALERT); an ALERT section is a safety
section, drawn behind a warning sign in the alert color. Each line is one
bullet.

Every claim was checked against gui.py when it was written (2026-10-20).
NAMED_CONTROLS lists, per page, the on-screen labels the words quote; the
tests check each one is still a real widget label, so a renamed button
cannot leave a tip that sends the operator looking for it.
"""
from collections import namedtuple

Page = namedtuple('Page', 'title heading sections manual')

ALERT = 'alert'          # third element of a safety section


def _manual(section):
    return f'Full detail: the user manual, section "{section}".'


LCR = Page(
    title="LCR Meter Tips",
    heading="BK Precision 894 LCR Meter",
    sections=(
        ("Apply first", (
            "Nothing reaches the meter until Apply Configuration.",
            "Readouts are labeled with the last applied mode, not the Mode "
            "box.",
            "Status: OK is a valid reading. A few fF usually means an open "
            "circuit.",
        )),
        ("Settings (hover a field for its help)", (
            "Mode: a parallel mode (CP, LP) above about 10 kΩ, a series "
            "mode (CS, LS) below about 1 kΩ.",
            "Frequency: 1 kHz for most capacitors, 100 Hz for electrolytics.",
            "Voltage: 1.0 V is standard. Above 2.0 V the meter clamps "
            "without an error.",
            "Quietest D on small capacitors: Speed SLOW, Avg 8 to 16.",
            "Untick Auto range to hold the range on a fixed part.",
        )),
        ("DC bias", (
            "Set DC Bias (V), tick Bias ON, Apply. It stays on until you "
            "untick it and Apply again; closing the app switches it off.",
        )),
        ("Fixture correction", (
            "Run Open Correction... (fixture empty) and Short Correction... "
            "(terminals shorted) again after any fixture or lead change. "
            "Each takes tens of seconds.",
        )),
        ("Readings", (
            "Single Measurement reads once; Start Continuous reads every "
            "0.2 s until Stop.",
            "A sweep leaves the meter at its last point: Apply "
            "Configuration again before single readings.",
            "Short leads, Kelvin clips for low impedance, and 2 to 3 s to "
            "settle after a frequency change.",
        )),
    ),
    manual=_manual("LCR Meter — BK 894"),
)

SCOPE = Page(
    title="Oscilloscope Tips",
    heading="Tektronix MSO24 Oscilloscope",
    sections=(
        ("During an SLDEA run", (
            "A LIVE run locks its V_Out and I_Out channels, the timebase "
            "and the trigger, and refuses Stop, Single and AutoSet: the "
            "breakdown watchdog reads I_Out.",
            "Reconnect asks first. Say Yes only if the scope has stopped "
            "answering.",
        ), ALERT),
        ("Apply", (
            "Typed values do nothing until Apply. Apply CH1 Config sends "
            "one channel; only Apply All Settings sends the trigger.",
            "AutoSet does not update these fields, so a later Apply All "
            "Settings undoes it.",
        )),
        ("Setting up", (
            "Fill 60 to 80 % of the screen height (V/div) and show 2 or 3 "
            "cycles (s/div).",
            "Tick Use as trigger on one channel; set the level mid-signal.",
            "Unknown signal: AutoSet first, then fine-tune.",
        )),
        ("Measurements", (
            "Readouts change only on Get CH1 Measurements (one button per "
            "channel).",
            "No signal means no valid value; Frequency and Period need a "
            "periodic signal.",
            "Capture CH1 Waveform plots the full record; Save CSV... is in "
            "that window.",
        )),
    ),
    manual=_manual("Oscilloscope — Tektronix MSO24"),
)

SIGGEN = Page(
    title="Signal Generator Tips",
    heading="B&K Precision 4055B Signal Generator",
    sections=(
        ("Safety", (
            "Output ON can energize the Trek HV amplifier: 1 V from this "
            "generator is 1 kV at the DEA.",
            "Apply with the output off, then press Output: OFF. It asks "
            "first (Enter = No) and is red while ON.",
            "Closing the app switches both outputs off.",
            "A LIVE SLDEA run locks the channel driving the Trek. ■ Abort "
            "on the SLDEA tab ends the run.",
        ), ALERT),
        ("Apply, then Output", (
            "Apply CH1 Settings sends the settings only. It never switches "
            "the output.",
            "Gray values beside the fields are what the instrument "
            "accepted. Believe them over what you typed.",
            "The preview draws your typed values; it is not a measurement.",
            "Read Instrument loads the generator's settings, for example "
            "after front-panel changes.",
        )),
        ("Amplitude and Load", (
            "Amplitude is peak to peak (Vpp), set for the Load in Advanced "
            "mode. 50 Ω into a High-Z input gives about twice the voltage.",
            "For a steady level, pick DC and set DC Offset.",
        )),
        ("Burst", (
            "Burst sends exactly Cycles periods per trigger, then idles.",
            "Tick Burst, Apply, switch the output on, then Fire (Trigger "
            "MAN). INT repeats every Interval; EXT uses the rear Aux In.",
        )),
        ("ARB and presets", (
            "USB cannot carry waveform data. Draw it in Waveform Editor... "
            "and use its flash-drive export; Upload & Select needs LAN.",
            "Load Preset sends both channels' settings. It never switches "
            "an output.",
        )),
    ),
    manual=_manual("Signal Generator — BK 4055B"),
)

PSU = Page(
    title="DC Supply Tips",
    heading="BK 9174B DC Supply",
    sections=(
        ("Safety", (
            "Closing the app leaves the supply as it is: an ON output keeps "
            "powering its load.",
            "Only Output: OFF energizes the terminals. It asks first and "
            "is red while ON.",
            "The current limit is not a fuse: at the limit the voltage "
            "drops to hold the current. Set it just above the expected "
            "draw.",
            "Set OVP and OCP with Set Protection before switching on.",
        ), ALERT),
        ("Setting an output", (
            "Pick Channel 1 or 2, type Set Voltage and Current Limit, then "
            "Apply V / I limit. Apply never switches the output.",
            "Up to 3 A at 0 to 35 V, 1.5 A at 35 to 70 V. Apply refuses a "
            "pair outside that.",
        )),
        ("Readout and logging", (
            "Live readout shows V, A and W every 0.5 s but saves nothing. "
            "To record, tick DC Supply CH1 or CH2 on Continuous Logging.",
        )),
    ),
    manual=_manual("DC Supply — BK 9174B"),
)

DMM = Page(
    title="DMM Tips",
    heading="BK 5493C Multimeter",
    sections=(
        ("Connection", (
            "LAN only (its USB never enumerated), port 45454.",
            "On the meter, Menu > I/O / LAN > DHCP Once gets an address. "
            "Type that IP here, then Reconnect.",
            "One client at a time: if Reconnect keeps failing, close the "
            "other program or power-cycle the meter.",
            "SCPI_DMM_ADDR sets the IP in the box at start-up.",
        )),
        ("Reading", (
            "Pick a Function, then Read once, or tick Live reading (2 per "
            "second). OVLD means overload or no numeric reply.",
        )),
        ("Logging", (
            "Tick DMM on Continuous Logging. It records the Function "
            "selected when you press Start Logging.",
        )),
    ),
    manual=_manual("Digital Multimeter — BK 5493C"),
)

LOGGING = Page(
    title="Continuous Logging Tips",
    heading="Continuous Logging",
    sections=(
        ("Before Start", (
            "Set up each instrument on its own tab first. A ticked source "
            "that is not connected is skipped, with a note in Log Status.",
            "Cadence: seconds between samples (s) or samples per second "
            "(Hz). 1 s for slow processes, 0.1 s for faster ones.",
        )),
        ("During a run", (
            "Sources are read one after another each sample. Samples missed "
            "because that took too long are skipped and counted, never "
            "made up.",
            "Live Values: latest, min and max since Start. A cell reading "
            "\"--\" had no value and is not counted.",
            "A source failing 5 reads in a row is dropped, with one note in "
            "Log Status.",
            "Stop Logging before disconnecting an instrument.",
        )),
        ("Files", (
            "Each Start writes new CSVs, one per source, in the Log "
            "Directory (like lcr_20260206_143052.csv).",
            "Rows are saved as they are taken: a crash loses at most the "
            "last row. The manual lists each file's columns.",
        )),
    ),
    manual=_manual("Continuous Logging"),
)

# tab slug (gui.MANUAL_TABS) -> its page
PAGES = {'lcr': LCR, 'scope': SCOPE, 'siggen': SIGGEN, 'psu': PSU,
         'dmm': DMM, 'logging': LOGGING}

# Per page, the on-screen labels its words quote, exactly as the widgets
# show them. Tested both ways: each is in the page's text and is a live
# widget label in the built app.
NAMED_CONTROLS = {
    'lcr': ("Apply Configuration", "Bias ON", "Auto range",
            "Open Correction...", "Short Correction...",
            "Single Measurement", "Start Continuous", "Stop"),
    'scope': ("Apply CH1 Config", "Apply All Settings", "AutoSet", "Stop",
              "Single", "Reconnect", "Get CH1 Measurements",
              "Capture CH1 Waveform"),
    'siggen': ("Output: OFF", "Apply CH1 Settings", "Read Instrument",
               "Advanced mode", "Burst", "Fire", "Waveform Editor...",
               "Load Preset", "■ Abort"),
    'psu': ("Output: OFF", "Set Protection", "Apply V / I limit",
            "Live readout"),
    'dmm': ("Reconnect", "Read once", "Live reading", "Start Logging"),
    'logging': ("Stop Logging", "Log Status"),
}
