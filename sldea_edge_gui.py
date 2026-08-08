#!/usr/bin/env python3
"""SLDEA Edge Review -- offline edge-detection GUI for SLDEA runs.

The companion program to the Digital Multitool's SLDEA tab: point it at a run
directory (SLDEA_<ts>/), it traces the active-area disc in every frame
(difference-imaging vs the 0 kV baseline + a Hough candidate), auto-accepts
confident detections, and queues the shaky ones for a human pick -- each
candidate outline is drawn over the photo and the user chooses A/B/C, a
hand-traced candidate D, or Reject. Breakdown heuristics (current spike,
area collapse) annotate suspect
steps. Results are written back to the run's data.csv only after an explicit
prompt (a .bak is kept), together with an area-vs-voltage plot and outline
overlays for audit.

    python sldea_edge_gui.py [run-or-parent-dir] [--auto]

SCALE GATE (operator decision 2026-08-05): the camera zoom moves between
runs, so every run's px→mm anchor is measured by hand — Detect diverts to
the 📏 scale dialog until the resting disc has been measured on THIS
run's baseline frame, Save hard-blocks without it, and the anchor resets
on every run switch.

ONE 📏 BUTTON, TWO OUTCOMES (operator 2026-08-06 late, `#215`).
📏 Calibrate… and 📏 Re-anchor scale… were folded into a single
entry point because they open the SAME dialog; what differs is what happens
to the number afterwards, and that follows the RUN'S STATE
(EdgeReviewApp._scale_intent). With a review pass in memory — or a detect
worker running, or nothing measured yet — it CALIBRATES: the anchor is held
and applied at the next Save, and nothing is written now. On a saved run
with px measurements and no pass open it RE-ANCHORS: every mm² in data.csv
is re-derived from the stored px and committed. The refusal that used to
stop a re-anchor on top of an open pass survives as that routing rule AND
as an independent check inside _reanchor_scale, because re-anchoring over a
partial pass is the [critical] mixed-scale bug's own shape. Since one path
writes immediately and the other does not, the intent is named in the
dialog's title, on its primary button and in its confirmation.

THE METHOD LABELS ARE A / B / C AND THE RECORD HOLDS NAMES. The letters
were renumbered on 2026-08-06 late — A = verify, B = circle, C = twopoint —
so the letter an operator reads first is the mode the gate opens in. Because
the OLD letters are already on disk in `cal_mode:` and in `mode=` log lines
(live P3_2 carries `cal_mode: C`, meaning verify), nothing writes a letter
any more: se.CAL_MODE_LABELS is presentation, the record holds
verify/circle/twopoint, and se.cal_mode_read reads a legacy letter with its
PRE-SWAP meaning (A = circle, B = twopoint, C = verify).

The manual calibration overrides every automatic reference at Save (it
used to be silently ignored when the baseline row had an accepted result);
the automatic disc fit is demoted to a cross-check.

CALIBRATION v3 — THE VERIFY MODE (label A), "verify the automatic fit" (`#215`,
2026-08-06 evening). The gate now OPENS on the machine's own measurement
whenever `se.baseline_disc` returns a fit, and asks the operator to JUDGE it
rather than repeat it. The A/B/A′ experiment forced that: eleven hand
calibrations on P3_2's baseline against an automatic fit of 577.08 px (circ
0.999, conf 0.871, residual 2.3 px, 204 edge points) — the fit beat ALL ELEVEN
on accuracy and NINE OF ELEVEN on precision, and per-fit human precision sat at
σ ≈ 1.0–1.1 % of diameter whatever the method or stroke, needing ~7 rounds to
average down to the 0.4 % SE gate. The reason is in the frame: the disc reads
166 gray, the paper 186, and that 20-level step is spread over ~60 px of
RADIUS. There is no line to click.

The verify mode therefore shows the fit with a 1 px dashed stroke (a 3 px
stroke on the boundary measurably biases a human by +2 %, so it may not be what
presents a boundary for judgement), over a CONTRAST-STRETCHED display copy
(display only, stated as such — at native contrast the step is nearly
invisible), framed on the CIRCLE so it fills the canvas the moment the dialog
opens. Its actions are ✔ Accept (primary, and Tk's default button — but
<Return> still cannot reach it) and Cancel; the route to a HAND measurement
is the radio row itself, which is why its caption is bold and its manual
entries say "measure BY HAND" — the ✎ Measure by hand instead button was
dropped as a second control for one job (operator 2026-08-06 late). When the
fit REFUSES, the gate falls straight through
to the hand measurement and says so, quoting the fitter's own reason
(`se.baseline_disc_refusal`).

The verify mode's SCREEN IS AT MOST FOUR SHORT LINES
(CAL_VERIFY_MAX_LINES) and normally TWO: the value being adopted and two
quality numbers, plus a warning if the contrast stretch could not be
computed and a consequence line only when a prior anchor exists and differs.
That budget is a requirement, not a style: an operator drove the 13-line
version on a real disc, agreed with the fit, and reported the screen as
"wayyyyy too busy with text and unnecessary garbage" (`#215`, 2026-08-06
late), then had the standing "view is contrast-stretched … your eye is the
check" sentence taken off it as unnecessary. Every number and every
statement removed from the screen — `conf`, `n_edge`, arc coverage, interior
fill, the implied resting area, the display-only stretch and the whole
cross-check algebra — still reaches setup.txt's `guard:` field, the
calibration log and `sldea_diag` unchanged; see `verify_evidence` and
`se.verify_note`.

There is NO independent cross-check for an automatic anchor, and the verify
mode does not pretend otherwise: declaring the fitted disc to be diam_mm makes
the resting area π·(diam_mm/2)² BY CONSTRUCTION, so `se.anchor_guard`'s two
tests both read +0.00 % on any frame however wrong the fit is. It is not run
and not claimed anywhere — the dialog, the status line, the record and
`sldea_diag` all say the verification was the operator's eye plus the fit
quality (`se.guard_is_vacuous`, `se.verify_note`).

An accepted verify-mode anchor is recorded with method **`auto-verified`**, not
`manual-calibration`: anyone auditing a run has to be able to tell "a
human measured this" from "a human approved the machine's measurement".
Both override every automatic reference at Save.

CALIBRATION v2 (#215, 2026-08-06): the anchor is measured by hand over
several INDEPENDENT rounds and averaged, by one of TWO methods the
operator picks from a chooser in the dialog — so both can be driven on the
same disc in one session and compared. These are still how a run gets a
HAND measurement, and the verify mode's fallback:

  THE CIRCLE MODE, label B (se.CAL_MODE_CIRCLE, 3 rounds, the manual default):
  fit a CIRCLE onto the resting disc — drag to move, 8 handles to resize — each
  round respawning at a randomized position/size in the central ROI. THE
  TWO-POINT MODE, label C (se.CAL_MODE_TWOPOINT, 5 rounds): click two
  roughly-opposite edge points, with the DISPLAY ROTATED BY A RANDOM ANGLE
  between rounds. Rotation is the mechanism: it turns mis-judging "exactly
  opposite" from a systematic error into a random one that averaging suppresses
  as sqrt(n), and averages out the human bias toward horizontal/vertical
  chords. Clicks are mapped back through the inverse rotation and measured in
  ORIGINAL image px. Markers are a hollow ring plus a gapped crosshair — the
  two-point mode exists because the operator measured the circle mode's per-fit
  scatter at ~1.05% of diameter and diagnosed it as "the bright green circle
  occludes the edges" (`#215` comment, 2026-08-06).

In the two-point mode the SECOND CLICK BANKS THE ROUND and advances — no
Continue press (operator 2026-08-06 late) — except on the last round, where
✔ Finish is still required because what follows it is the acceptance gate,
the anchor guard and an anchor. Auto-advance removes the pause in which a
bad click could be noticed, so ◀ Back / Backspace steps one round back and
re-randomises it; the label names the round it lands on.

The rounds are kept BLIND in both modes: no previously accepted diameter and no
running average is shown until the last round is in, because a visible target
turns the scatter into a number the operator can hit (review 2026-08-06). The
two-point mode shows no length for the current pair either.

The scatter is the run's operator-repeatability number and is persisted
with the anchor, n-awarely: sigma = range/d2(n), mean SE = sigma/sqrt(n),
area SE = 2*SE (se.D2_RANGE_FACTORS; the code REFUSES to convert an n it
has no factor for). Compare the two methods on SIGMA — it is the only
figure that survives a different round count.

Two sanity gates fire before Save: the ACCEPTANCE GATE on the mean's
standard error (se.se_ok vs CAL_SE_PCT = 0.4% diameter, derived from
SLDEA_MEASUREMENT §2.1's budget — it replaced a raw-range gate, which was
neither comparable across n nor clearable by its own remedy), and the
ANCHOR GUARD (se.anchor_guard) — a deviation over ~1% from either the
automatic disc fit or the mask's π·(diam_mm/2)² resting area demands an
explicit override, and an UNAVAILABLE cross-check demands one too. Run
P3_2_2.5mL_20260728 shipped 4.42% low in every absolute mm² because the
old 3% cross-check said nothing.

EVERY completed round-set is appended to <run>/scale_calibration_log.txt and
printed to stdout, ACCEPTED OR DECLINED (se.append_calibration_log): the six
circle-mode spreads that motivated the two-point mode survive only because they
were typed into a chat, since every one of those calibrations was declined and
setup.txt is written at Save.

Every yes/no gate in the dialog is asked with an EXPLICIT default= and
with <Return> taken away from the window underneath while it is up:
tkinter's askyesno defaults to YES, and the Toplevel's Enter binding used
to answer all of them in sequence — six Enter presses accepted an
out-of-tolerance anchor without a word being read (review 2026-08-06).

With --auto (used by the SLDEA tab's "auto process"), the calibrate
dialog opens on launch and detection chains automatically once
calibration finishes. Keyboard: 1/2/3 pick a candidate, R reject,
4/D/T open the manual tracer (#162/#172 -- its Done stages the polygon
as candidate D; Accept commits it like any other candidate),
Left/Right navigate, Enter accept + next.
"""
import math
import os
import sys
import threading
import time
import queue as _queue
import tk_fontfix                      # must precede tkinter:
tk_fontfix.apply()                     # colour emoji crash Tk
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont

import numpy as np

import sldea_edge as se
import sldea_trace as strc

DEFAULT_PARENT = os.environ.get('SCPI_SLDEA_DIR',
                                '/mnt/shareDrive/robot_incubator/SLDEA_data')
# A green, B blue, C orange, D magenta (D = the manual trace, #172)
CAND_COLORS = ['#00c853', '#2196f3', '#ff9100', '#e040fb']
CAND_KEYS = ['A', 'B', 'C', 'D']
TRACE_SLOT = 3          # radio value / paint slot of the manual trace
VIEW_W = 780            # initial card view only -- once mapped, the card
VIEW_H = 560            # tracks the LIVE canvas size (#178)
MAX_UPSCALE = 2.0       # card upscale cap: past ~2x native a big monitor
                        # only interpolates mush (#178)
TAG_PX = 20             # letter-tag font size on the review card (#173)
SIDE_W = 330            # right panel width -- FIXED, propagation off (#179)
RADIO_TEXT_PX = SIDE_W - 100   # text budget in a candidate radio row: the
                               # panel + LabelFrame padding, colour swatch
                               # and radio indicator eat ~100 px of the row
PRIMARY_FG = '#1f3a5f'  # the app's existing accent blue (splash, clock) —
                        # reused for ▶ Detect Edges rather than introducing
                        # a colour, because #32 owns any real restyle
# There is deliberately NO secondary foreground. The first `#216` version
# muted Advanced… / 📏 grey, and on the first real drive the operator read
# exactly that as disabled — and was surprised the buttons worked
# (2026-08-07: "greyed out, but I can click them"). A muted-but-live
# control is the colour-alone lie about state the 2026-08-05 audit warns
# about; the primary accent plus the separators carry the hierarchy alone.
INFO_LINES = 5          # info label height (text lines): 3 fixed lines +
                        # room for a flag line and its wrap -- a flag must
                        # change content, not layout (#179)

_TAG_FONT = None


def _tag_font():
    """Bold letter-tag font for the review card (#173: the default PIL
    font was unreadably small on 1080p frames downscaled to the card).
    Cached; falls back to PIL's builtin when no TrueType font resolves."""
    global _TAG_FONT
    if _TAG_FONT is None:
        from PIL import ImageFont
        for name in ('arialbd.ttf', 'DejaVuSans-Bold.ttf', 'arial.ttf',
                     'DejaVuSans.ttf'):
            try:
                _TAG_FONT = ImageFont.truetype(name, TAG_PX)
                break
            except OSError:
                continue
        else:
            try:
                _TAG_FONT = ImageFont.load_default(TAG_PX)
            except TypeError:              # Pillow < 10.1: no size arg
                _TAG_FONT = ImageFont.load_default()
    return _TAG_FONT


def card_geometry(img_w, img_h, view_w, view_h, max_upscale=MAX_UPSCALE):
    """Contain-fit an img_w x img_h frame in a view_w x view_h canvas
    (#178): aspect kept, upscale capped at max_upscale, centered.
    Returns (scale, w, h, x, y) with (x, y) the card's top-left inside
    the view. Pure so the math is testable without Tk."""
    scale = min(view_w / float(img_w), view_h / float(img_h), max_upscale)
    w = max(1, int(round(img_w * scale)))
    h = max(1, int(round(img_h * scale)))
    return scale, w, h, (view_w - w) // 2, (view_h - h) // 2


def elide(text, width_px, measure):
    """Longest prefix of `text` (plus an ellipsis) that `measure`s within
    width_px. The side panel is a fixed box (#179): text must fit the
    panel, never size it -- the tail (the wrinkle term, the point count)
    is the sacrificial end."""
    if measure(text) <= width_px:
        return text
    for n in range(len(text) - 1, 0, -1):
        s = text[:n].rstrip() + '…'
        if measure(s) <= width_px:
            return s
    return '…'


# ---------------------------------------------------------------------------
# ❓ HOW TO USE — the workflow panel (`#238`)
#
# Edge Review had no in-app answer to "what am I supposed to do here". Every
# control could be identified and none of them said where to START, so the
# window's own loop — pick a run, calibrate, work the queue, Save — was
# folklore. This is that loop, written for the operator who has just opened
# the window, not a feature tour.
#
# WHERE THE WORDS LIVE, and why this is a HAND-KEPT COPY (`#238` decision).
# The repo already has a manual pipeline whose written copy is
# docs/manual-src/content.json, so a second copy of workflow prose can drift
# from it — this project has been bitten by one label living in five
# hand-kept places (gui.py, the telemetry LabelFrame). Three options were on
# the table; the panel is a hand-kept copy, deliberately, because:
#
#   * content.json is MANUAL copy, not app copy. Its Edge Review material
#     sits inside one "Companion tools" area shared with the tuner, the
#     diagnostic and the plot tool, and its `workflow` list is that whole
#     tool-chain in the manual's voice. There is no per-window workflow node
#     to source, and inventing one would be inventing an app-facing schema
#     inside a docs-build input.
#   * Sourcing the panel from content.json at runtime would make a
#     docs/ build input a RUNTIME dependency of the review program, with a
#     new failure mode (missing/renamed file -> an empty help window) for a
#     surface whose whole job is to be there when someone is lost.
#   * content.json is a RELEASE-CADENCE artifact and is already behind the
#     code: it still describes the scale entry point as "📏 Calibrate…" and
#     tells the operator to "click the resting disc's two opposite edges",
#     which is the pre-#215 flow. Text that ships in the same commit as the
#     code it describes cannot lag it by a release; text pulled from
#     content.json would have put that stale instruction on screen.
#
# So: the panel is SHORT and points at the manual for depth, the words live
# in ONE place (HOWTO_SECTIONS, right here, next to the code they describe),
# and docs/manual-src/README.md names this constant in the release checklist
# so the manual and the panel move together. HOWTO_QUOTED_CONTROLS is the
# anti-drift latch: every on-screen control the text names is listed there
# and the tests assert those strings are still real widget labels.
#
# Every factual claim below is load-bearing and was checked against the code
# before it was written; wrong help is worse than none. In particular the
# "nothing is written until Save" line carries its own exception, because
# a re-anchor on a saved run DOES write data.csv immediately
# (_reanchor_scale).
# ---------------------------------------------------------------------------

HOWTO_BTN_TEXT = "❓ How to use…"
HOWTO_TITLE = "Edge Review — how to use"
HOWTO_W = 860                       # sized for a 1080p bench screen; the
HOWTO_H = 700                       # height is clamped to the real screen

# The on-screen controls the panel names by their exact label. A renamed
# button must rename them here too, or the help sends the operator hunting
# for a control that no longer exists (the failure mode that made the
# telemetry LabelFrame's five copies worth a comment). Tested both ways:
# each string appears in the text AND is a live widget label.
HOWTO_QUOTED_CONTROLS = (
    "▶ Detect Edges",
    "📏 Calibrate / re-anchor…",
    "💾 Save to data.csv…",
    "Next unreviewed",
)

HOWTO_SECTIONS = [
    ("Edge Review turns a run's photos into measured areas", [
        "The machine measures; your job is to check its work and fix what "
        "it got wrong. Nothing from a review pass reaches data.csv until "
        "you press 💾 Save to data.csv… — the one exception is a re-anchor "
        "on an already-saved run, which says so on its own button before "
        "it writes.",
    ]),
    ("The loop", [
        "1.   Pick the run in the Run box at the top. Runs that already "
        "carry measured areas are marked ✓ processed.",

        "2.   Press ▶ Detect Edges. Calibration comes first: the camera "
        "zoom moves between runs, so Detect diverts to the scale dialog "
        "until this run has its own px→mm anchor. The dialog opens on the "
        "machine's own fit of the resting disc, and the job it asks of you "
        "is to JUDGE that circle, not to measure the disc again. Measuring "
        "by hand is the fallback for when the fit refuses, and it is "
        "measurably worse — roughly 1 % of diameter per attempt against "
        "the fit's 0.03–0.80 % residual, because the disc edge is a ~60 px "
        "gradient with no line to click. ✔ Accept, and detection starts on "
        "its own.",

        "3.   Work the review queue. Confident frames are accepted "
        "automatically; the rest wait for you. Keys 1 / 2 / 3 pick "
        "candidate A / B / C, Enter accepts and moves on, D (or 4) opens "
        "the hand tracer, R rejects. Next unreviewed jumps to the next "
        "frame that still needs a human.",

        "4.   💾 Save to data.csv… when the queue is empty. A .bak is kept, "
        "and the confirm prompt says what is about to be written and how "
        "many frames will be renamed before you answer.",
    ]),
    ("Three things that cost people real time", [
        "•   Wash-out frames are TRACED, not rejected. Above about 5.5 kV "
        "the ink boundary washes out and no boundary-shaped candidate can "
        "exist — that is the frame being what it is, not the detector "
        "failing, and your trace IS the measurement there. Reject means "
        "something narrower: no honest boundary can be drawn even by hand "
        "(occlusion, breakdown debris, a corrupt frame). Rejecting a "
        "wash-out frame silently discards a real data point, and it is the "
        "one instruction a new operator gets wrong.",

        "•   ✔ Accept in the scale dialog only STAGES the anchor — the "
        "Save is what writes it. Nothing on screen implies that, so it is "
        "worth over-learning: on a live run on 2026-08-06 an operator "
        "accepted a corrected fit, closed the window before saving, and "
        "the correction was lost. If you accepted a scale, Save before you "
        "close. (The dialog's own primary button says which one you are "
        "in: \"applied at Save\" versus \"RE-ANCHOR NOW\".)",

        "•   A wrong scale does not mean re-reviewing the run. On a run "
        "that is already saved, carries pixel measurements and has no "
        "review pass open, 📏 Calibrate / re-anchor… re-derives every mm² "
        "straight from the pixels already in data.csv — no detection, no "
        "second pass over the queue. Which of the two the button is about "
        "to do follows the run's state and is named in the dialog's title, "
        "on its primary button and in its confirmation.",
    ]),
    ("The two numbers on every candidate line", [
        ('code', "A: disc-fit   12345 px²   conf 0.87   w1.2"),

        "•   conf is the detector's own 0–1 opinion of that outline, built "
        "from how solid the shape is, how hard the edge steps, whether the "
        "other candidates agree with it and whether its interior is "
        "wrinkled. At or above accept_conf (0.75 by default) a frame is "
        "auto-accepted; below it, the frame comes to you. It is a score, "
        "not a probability — a confident wrong answer is possible, which "
        "is exactly why the queue exists.",

        "•   w is the wrinkle index: the texture inside the outline "
        "compared with the same patch of the 0 kV baseline. 1.0 means no "
        "texture change at all. At or above wrinkle_ratio (1.4 by default) "
        "the frame counts as wrinkle-mode, and since the lab defines the "
        "active area AS the buckled region, a wrinkled interior is "
        "evidence that the outline is sitting on the right thing.",
    ]),
    ("If you need more than this", [
        "The illustrated manual has the screenshots, the tuner and the "
        "rest of the tool chain: docs/digital-multitool-manual.pdf in the "
        "repo (or the copy handed out at the bench), section \"Companion "
        "tools\".",
    ]),
]


def howto_text():
    """The whole panel as plain text, in reading order.

    A paragraph is either a plain string or a ('code', text) pair (the one
    literal example of a candidate line, which is rendered in a fixed font
    and must not be reflowed). This is the single reader for the words, so
    the headless tests check exactly what the window renders."""
    out = []
    for heading, paras in HOWTO_SECTIONS:
        out.append(heading)
        out.extend(p[1] if isinstance(p, tuple) else p for p in paras)
    return '\n'.join(out)
# ---------------------------------------------------------------------------
# the two clocks (`#237`) — pure, so both readouts are testable without Tk
#
# ONE toolbar clock used to run from ▶ Detect Edges until 💾 Save, which
# made it a session stopwatch: the moment detection finished it kept
# counting through however long the human then spent reviewing, and the
# only number an operator can plan with — how long the PASS took — was
# destroyed as soon as it was produced. Two readouts instead, because
# both are wanted: the detection pass's own time, FROZEN when the pass
# ends and carrying its frame count so it reads as a rate, above a
# session total that never stops.
# ---------------------------------------------------------------------------


def fmt_dur(sec):
    """Compact absolute duration — `43s`, `2m14s`, `1h04m` (`#237`).

    Deliberately not M:SS. These readouts are read as an ANSWER ("81
    frames in 2m14s"), and a bare `2:14` sitting beside a running session
    clock reads as a time of day; M:SS also never rolls over, so a
    90-minute pass prints `90:00`. Not `sldea_profile.fmt_duration`
    either — its `0:02:14` spends three characters on an hour that a
    detection pass almost never has."""
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m{sec % 60:02d}s"
    return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"


def detect_readout(n_frames=None, secs=None, total=None):
    """The DETECTION line of the toolbar clock (`#237`).

    Three states, one function so a test can pin all of them:

    - `secs is None` — **no detection pass has run on this run**, said out
      loud rather than left blank. A scale-only re-anchor never detects
      (`#215`), so the ABSENCE of a fresh detection time is exactly the
      signal that tells an operator which of the two paths they are on —
      and a blank readout beside a running session clock is indis-
      tinguishable from a readout that has not repainted yet.
    - `total` given — a pass is in flight; the line reads as progress.
    - otherwise — the pass finished and this is the frozen answer.
    """
    if secs is None:
        return "detect: not run"
    if total is not None:
        # no "frames" while running: the `/` already says what the pair
        # is, the banner and the status line both spell it out, and this
        # form has to stay inside the same fixed box as the frozen one
        return f"detect: {n_frames}/{total}  {fmt_dur(secs)}"
    return f"detect: {n_frames} frames in {fmt_dur(secs)}"


def session_readout(secs):
    """The SESSION line of the toolbar clock (`#237`) — how long this
    window has been open. Runs from the moment Edge Review opens to the
    moment it closes: it is not reset by a run switch (the batch cockpit
    is one session across many runs) and not stopped by Save (reviewing
    continues after one)."""
    return f"session {fmt_dur(secs)}"
# ---------------------------------------------------------------------------
# hover tooltips (`#216`)
#
# COPIED, NOT IMPORTED, from ui_widgets.py — deliberately (PROJECT_HANDOFF
# open decision 2). That decision moves sldea_edge / sldea_edge_gui /
# sldea_tuner / sldea_diag / sldea_trace into their own repo as an
# instrument-free suite; `ui_widgets` is NOT in that seam, so importing it
# here would plant a cross-seam dependency on the split's own boundary for
# the sake of ~35 lines with no state and no invariants. The repo's
# duplication scar (the `#224` label in five hand-kept places) is about a
# STRING an operator reads and a doc quotes; this is a behaviourless Tk
# idiom. If the two ever drift, nothing measurable is wrong — one popup
# waits 650 ms and the other 700.
#
# If the split is ever abandoned, delete this and
# `from ui_widgets import add_tooltip` instead: the signature is the same
# on purpose.
# ---------------------------------------------------------------------------


class Tooltip:
    """Show `text` in a small popup after hovering `widget` for `delay` ms.

    Tk has no built-in tooltip; this is the standard Toplevel +
    overrideredirect pattern. Hides on leave/click/destroy.
    """

    def __init__(self, widget, text, delay=650, wraplength=340):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self._after_id = None
        self._tip = None
        widget.bind('<Enter>', self._schedule, add='+')
        widget.bind('<Leave>', self._hide, add='+')
        widget.bind('<ButtonPress>', self._hide, add='+')
        widget.bind('<Destroy>', self._hide, add='+')

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 14
            y = (self.widget.winfo_rooty()
                 + self.widget.winfo_height() + 6)
        except tk.TclError:      # widget died while the timer was pending
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f'+{x}+{y}')
        tk.Label(tip, text=self.text, justify='left',
                 wraplength=self.wraplength, bg='#ffffe0', fg='black',
                 relief='solid', borderwidth=1, padx=7, pady=5).pack()
        self._tip = tip

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


def add_tooltip(widget, text):
    """Attach a hover tooltip; returns the Tooltip.

    THE ONE DELIBERATE DIFFERENCE from ui_widgets.add_tooltip, which
    returns the widget so a caller can chain `add_tooltip(ttk.Button(…),
    …)`. Nothing here chains, and one caller — ▶ Detect Edges, whose
    hover text follows its enabled state — needs the object back."""
    return Tooltip(widget, text)


# TIPS is the whole hover-help inventory in one place, keyed by the
# attribute/slot it hangs on, so a reviewer can read every string the
# operator can summon without walking _build_ui — and so the tests can
# assert that every control the issue names actually carries one.
# One short sentence each: what THIS control does, in the words the code
# uses. Workflow prose ("what do I do here") is #238's panel, not this.
TIPS = {
    'run_box': "Pick which run folder to review — '✓ processed' means its "
               "data.csv already carries pixel areas from an earlier pass.",
    'browse_btn': "Point Edge Review at a different run folder, or at a "
                  "parent folder full of them.",
    'detect_btn': "START HERE: traces the disc in every frame of this run — "
                  "if the run has no px→mm anchor yet, the 📏 calibration "
                  "opens first and detection continues by itself.",
    'detect_btn_disabled': "Pick a run in the Run box first — there is "
                           "nothing to detect until then.",
    'detect_btn_busy': "Detection is running — the Run box and Browse… are "
                       "locked until it finishes, so a stale pass cannot "
                       "land on the next run.",
    'adv_btn': "Edit this run's detection thresholds; changing one that "
               "affects detection clears the current pass and asks first.",
    'scale_btn': "Set this run's px→mm anchor from the resting disc; on an "
                 "already-saved run with no review pass open it re-derives "
                 "every mm² in data.csv instead.",
    'save_btn': "Writes the accepted areas into data.csv (a .bak is kept) "
                "and saves the plot and outline overlays — greyed out until "
                "▶ Detect Edges has run, and it still refuses without the "
                "📏 scale anchor.",
    # the digit leads because <Key-1..3> is bound unconditionally, while
    # the letter binding is <Key-a/b/c> — lowercase, so it is the letter
    # an unshifted keypress sends (unlike R/D/T, bound in both cases)
    'cand': "Machine candidate {k} — the outline drawn on the frame in the "
            "matching colour; press {n} or {k} to pick it. conf is a "
            "review-ordering score, not a probability that the edge is "
            "right.",
    'trace': "Draw the outline yourself when no candidate is right — keys "
             "4, D or T open the tracer. Done only STAGES it as D; "
             "✔ Accept commits it.",
    'accept_btn': "Commit the selected candidate for this frame (Enter), "
                  "then jump to the next frame still needing a decision.",
    'reject_btn': "Record that this frame has no reliable edge (R) — its "
                  "area columns are blanked, and it is not left unreviewed.",
    'prev_btn': "Back one frame (Left arrow); browsing never changes a "
                "decision.",
    'next_btn': "Forward one frame (Right arrow); browsing never changes a "
                "decision.",
    'unrev_btn': "Jump to the first frame still waiting for a decision.",
}

# The empty canvas says what to press. The scale gate turns Detect into
# the ONE entry point — it diverts to 📏 and chains back — so the hint
# names Detect, not calibration (`#216`). Every other place that tells an
# operator how to start a run says the same thing in the same order; if
# you change this, grep for "Detect Edges" and change them together.
HINT_PICK_RUN = ("Pick a run in the Run box above,\n"
                 "then press  ▶ Detect Edges")
HINT_DETECT = ("Press  ▶ Detect Edges  to start.\n"
               "📏 Calibration will guide you first when this run "
               "needs an anchor.")


# ---------------------------------------------------------------------------
# the 📏 fit-a-circle calibration (#215) — pure geometry, no Tk
#
# The operator sits a thick-stroke circle on the resting disc edge, three
# times, and the mean of the fitted diameters is the run's anchor. Two
# clicks on exactly-opposite points is a thing humans do badly; a circle
# is compared against the WHOLE visible boundary. Each round respawns at
# a randomized position and size inside the central ROI so the three fits
# are independent rather than three nudges of the first one.
# ---------------------------------------------------------------------------

CAL_ROUNDS = se.CAL_ROUNDS          # 3 (the spread needs >= 2). Fixed:
                                    # the spread gate's remedy is a REFIT,
                                    # not a 4th round, because max-min
                                    # cannot shrink when a round is added
                                    # (se.spread_ok, review 2026-08-06)
CAL_MIN_R_PX = 8.0                  # smallest fittable radius, full-res px
CAL_HANDLE_TOL = 10                 # handle grab radius, VIEW px
CAL_SPAWN_R_FRAC = (0.30, 0.40)     # spawn radius / ROI min-dimension
CAL_SPAWN_JITTER = 0.06             # spawn centre jitter / ROI min-dimension
                                    # 0.40 + 0.06 < 0.5 keeps the spawned
                                    # circle inside the ROI by arithmetic,
                                    # not by the clamp; and 2*0.40 = 0.80
                                    # stays inside the plausibility gate
                                    # below, so a raw spawn is always an
                                    # acceptable (if wrong) fit
CAL_WHEEL_FINE_PX = 0.5             # wheel notch -> radius, fine
CAL_WHEEL_COARSE_PX = 5.0           # Shift+wheel notch -> radius
CAL_MIN_DIAM_FRAC = 0.06            # an acceptable diameter, as a fraction
CAL_MAX_DIAM_FRAC = 0.85            # of the ROI's short side — the SAME
                                    # gate se.baseline_disc applies
_SQ = 0.5 ** 0.5
# 8 handles like any drawing tool; all of them resize about the centre,
# because the shape is a CIRCLE by construction (#215: ellipse handles /
# tilt correction are explicitly out of scope — the camera is normal to
# the sample and the mask is laser-cut round)
CAL_HANDLE_DIRS = (('e', 1.0, 0.0), ('se', _SQ, _SQ),
                   ('s', 0.0, 1.0), ('sw', -_SQ, _SQ),
                   ('w', -1.0, 0.0), ('nw', -_SQ, -_SQ),
                   ('n', 0.0, -1.0), ('ne', _SQ, -_SQ))


def cal_roi(img_w, img_h, roi_frac):
    """(x0, y0, x1, y1) of the central ROI, in full-res image px, using
    the SAME window se.baseline_disc searches — so "inside the ROI" means
    the same thing to the spawn and to the automatic fit it is checked
    against."""
    rf = min(1.0, max(0.2, float(roi_frac)))
    x0 = img_w * (1.0 - rf) / 2.0
    y0 = img_h * (1.0 - rf) / 2.0
    return (x0, y0, float(img_w) - x0, float(img_h) - y0)


def clamp_circle(cx, cy, r, box, min_r=CAL_MIN_R_PX, contain=True):
    """Keep a circle sane inside box=(x0, y0, x1, y1).

    contain=True (the spawn) fits the WHOLE circle inside the box.
    contain=False (dragging) boxes the CENTRE only and caps the radius at
    the box's longest side: a disc that runs off the frame edge is a
    broken run, but refusing to let the operator draw it would hide that
    instead of showing it."""
    x0, y0, x1, y1 = (float(v) for v in box)
    r = max(float(min_r), float(r))
    if contain:
        r = min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0)
        r = max(r, float(min_r))
        lox, hix, loy, hiy = x0 + r, x1 - r, y0 + r, y1 - r
    else:
        r = min(r, max(x1 - x0, y1 - y0))
        lox, hix, loy, hiy = x0, x1, y0, y1
    cx = (x0 + x1) / 2.0 if hix < lox else min(max(float(cx), lox), hix)
    cy = (y0 + y1) / 2.0 if hiy < loy else min(max(float(cy), loy), hiy)
    return (cx, cy, r)


def spawn_circle(img_w, img_h, roi_frac, rnd=None):
    """A randomized (cx, cy, r) start for one calibration round, wholly
    inside the central ROI (#215).

    Randomizing per round is the point: an operator who only nudges the
    previous circle produces three correlated fits and a spread that
    understates their real scatter. `rnd` is any random.Random (pass a
    seeded one to make a session reproducible in a test)."""
    import random as _random
    rnd = rnd or _random
    x0, y0, x1, y1 = cal_roi(img_w, img_h, roi_frac)
    span = min(x1 - x0, y1 - y0)
    lo, hi = CAL_SPAWN_R_FRAC
    r = span * rnd.uniform(lo, hi)
    j = span * CAL_SPAWN_JITTER
    cx = (x0 + x1) / 2.0 + rnd.uniform(-j, j)
    cy = (y0 + y1) / 2.0 + rnd.uniform(-j, j)
    return clamp_circle(cx, cy, r, (x0, y0, x1, y1), contain=True)


def cal_diam_plausible(diam_px, img_w, img_h, roi_frac):
    """Could this diameter be the resting disc at all?

    Mirrors se.baseline_disc's own size gate — 0.06 to 0.85 of the ROI's
    short side — so the dialog refuses exactly what the automatic fit
    would refuse. The two-click dialog had a 10 px floor for the same
    reason (a fat-fingered pair of clicks 3 px apart would have set
    mm_per_px to ~5 mm/px and every area with it); a circle can be
    collapsed onto its own centre just as easily."""
    x0, y0, x1, y1 = cal_roi(img_w, img_h, roi_frac)
    span = min(x1 - x0, y1 - y0)
    return (CAL_MIN_DIAM_FRAC * span <= float(diam_px)
            <= CAL_MAX_DIAM_FRAC * span)


def circle_handles(cx, cy, r):
    """[(name, x, y)] of the 8 resize handles, in the same coordinate
    space as the inputs."""
    return [(nm, cx + dx * r, cy + dy * r) for nm, dx, dy in CAL_HANDLE_DIRS]


def hit_test_circle(cx, cy, r, px, py, tol=CAL_HANDLE_TOL):
    """What a press at (px, py) grabs: a handle name, 'move' (interior),
    or None (a press that grabs nothing at all — it must NOT teleport the
    circle, which is the one interaction bug that would silently corrupt
    a fit the operator thought was finished).

    tol is in the coordinate space of the arguments; the dialog hit-tests
    in VIEW px so a handle stays the same physical size at every zoom."""
    hit, best = None, None
    for nm, hx, hy in circle_handles(cx, cy, r):
        d = ((px - hx) ** 2 + (py - hy) ** 2) ** 0.5
        if d <= tol and (best is None or d < best):
            hit, best = nm, d
    if hit:
        return hit
    if ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5 <= r:
        return 'move'
    return None


def resize_radius(cx, cy, px, py, min_r=CAL_MIN_R_PX):
    """Radius for a handle dragged to (px, py): the distance from the
    centre. Resize is ALWAYS about the centre and always circular."""
    return max(float(min_r), ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5)


def cal_key_delta(keysym, shift=False):
    """(dcx, dcy, dr) in full-res px for an arrow key: arrows nudge the
    centre 1 px, Shift+arrows resize 1 px (Up/Right grow, Down/Left
    shrink). None for any other key."""
    k = (keysym or '').lower()
    if k not in ('left', 'right', 'up', 'down'):
        return None
    if shift:
        return (0.0, 0.0, 1.0 if k in ('up', 'right') else -1.0)
    return ({'left': (-1.0, 0.0, 0.0), 'right': (1.0, 0.0, 0.0),
             'up': (0.0, -1.0, 0.0), 'down': (0.0, 1.0, 0.0)}[k])


def cal_wheel_dr(steps, coarse=False):
    """Radius change for `steps` wheel notches: fine by default, coarse
    with Shift. The wheel is the FINE RESIZE here (#215) — zoom moved to
    Ctrl+wheel, because a wheel that zoomed while the operator was
    sizing a circle would fight the primary gesture."""
    return float(steps) * (CAL_WHEEL_COARSE_PX if coarse
                           else CAL_WHEEL_FINE_PX)


def cal_stroke_spec(style):
    """(width_px, dash_or_None) for the circle mode's circle stroke.

    THE CHEAP THIRD ARM of the A/B comparison (`#215`, 2026-08-06). The
    operator's diagnosis of the circle mode's 1.05 % per-fit scatter was that
    "the bright green circle occludes the edges" — a 3 px stroke laid along the
    boundary hides the feature being aligned to. If that is the real cause then
    a 1 px or dashed stroke may rescue the circle mode outright, and it costs
    two lines to find out while an operator is measuring anyway. The 3 px solid
    stroke stays the DEFAULT so the circle mode's behaviour is unchanged unless
    the option is touched.

    Unknown styles fall back to the default rather than raising: a stroke
    width is not worth losing a calibration over."""
    return {'1 px solid': (1, None),
            '1 px dashed': (1, (4, 4))}.get(style, (3, None))


# ---------------------------------------------------------------------------
# THE VERIFY MODE (label A) — the machine measures, the operator VERIFIES
#
# The A/B/A′ experiment (`#215`, 2026-08-06 evening) inverted the premise
# this dialog was built on. Eleven hand calibrations on P3_2's baseline
# against an automatic fit of 577.08 px (circ 0.999, conf 0.871, residual
# 2.3 px, 204 edge points): the fit beat ALL ELEVEN on accuracy and NINE OF
# ELEVEN on precision, and per-fit human precision sat at σ ≈ 1.0–1.1 % of
# diameter whatever the method or the stroke width.
#
# The radial intensity profile says why there is no gesture that fixes it:
# the disc reads 166 gray, the paper 186, and that 20-level step is spread
# over ~60 px of RADIUS. Asking an operator to pick "the edge" is asking
# them to pick a point inside a gradient WIDER than the stroke they draw
# with — and the point a human picks is the outer toe (§1.3, +2.6 %
# diameter), which is the measured bias of the circle mode.
#
# So the verify mode shows the fit and asks for a judgement. Three things
# make that a real judgement rather than a rubber stamp:
#
#   1. A NON-OCCLUDING stroke. A 3 px stroke laid on the boundary
#      measurably biases a human by +2 % (the circle mode vs the A′ arm),
#      so it must not be what presents a boundary FOR JUDGEMENT. One px,
#      dashed, dark-haloed.
#   2. A CONTRAST STRETCH of the displayed crop. A 20-level step on a 186
#      background is nearly invisible at native contrast — the operator
#      would be judging a flat grey field. The stretch is DISPLAY ONLY and
#      the dialog says so; the measurement used the raw frame.
#   3. FOUR LINES OF TEXT, and the canvas gets everything else.
#
# That third point is the DECLUTTER (`#215`, 2026-08-06 late). The verify
# mode was driven on P3_2's baseline and the fit was accepted as correct — so
# the premise held — but the screen it was accepted on carried 13 lines of
# prose
# wrapping to 19, and the operator's verdict was that the dialog was "wayyyyy
# too busy with text and unnecessary garbage". The evidence block asked for
# every quality number the fitter reports; the result was a wall that stole
# the canvas height from the only thing that IS the verification, which is
# the dashed circle on the stretched frame. So the budget is now four short
# lines (CAL_VERIFY_MAX_LINES): the value adopted, two quality numbers, one
# honest sentence, and a consequence line only when there is a consequence.
# Nothing was DELETED from the record — see verify_evidence for the full
# accounting of where each cut number still lands.
#
# The verify mode also opens ALREADY ZOOMED (verify_zoom): the operator is
# judging one boundary, not surveying the frame, and a fit-to-window view put
# the disc at
# half size behind a "below 1:1 — press Z" nag. Fix the zoom and the nag has
# nothing to warn about.
# ---------------------------------------------------------------------------

CAL_VERIFY_STROKE_PX = 1        # never thicker: the stroke must not sit ON
CAL_VERIFY_DASH = (5, 7)        # the feature being judged (see above)
CAL_VERIFY_FILL_FRAC = 0.82     # of the canvas's shorter side, on open: the
                                # fitted circle plus a margin of paper, so
                                # the whole boundary is judgeable at once
CAL_VERIFY_MAX_OPEN_ZOOM = 6.0  # past this the display is interpolating, not
                                # revealing (a tiny disc is a refused fit)
CAL_STRETCH_PAD_FRAC = 0.45     # display window padding, as a fraction of
                                # the measured disc→paper step
CAL_STRETCH_MIN_SPAN = 6.0      # never stretch a narrower window than this:
                                # past it the display is amplifying sensor
                                # noise, not revealing an edge


def disc_paper_lum(arr, cx, cy, r, inner=0.60, ring=(1.25, 1.55)):
    """(disc median, paper median) gray levels, measured off the frame
    itself well INSIDE and well OUTSIDE the fitted circle — never across
    the ramp, which is the thing being displayed.

    The ~20-gray step spans ~60 px of radius on a ~290 px radius, i.e. about
    0.90 r to 1.10 r, so `inner` = 0.60 r and a ring starting at 1.25 r both
    sit clear of it. The ring STOPS at 1.55 r rather than reaching further:
    past that it starts collecting the electrode foil and the frame edge on
    a 1080-tall frame, and a paper level pulled up by foil would under-
    stretch the very step this exists to reveal. MEDIANS, not means, for the
    same reason — the electrode strips cross both samples.

    Prefer `baseline_disc`'s own `paper_lum` for the paper level where it is
    available (the caller does): the fitter measured it with foil and glint
    already rejected, which no annulus here can do.

    Returns (None, None) when either sample is too small or the frame is
    unusable, and every caller must then simply not stretch: a stretch
    computed from nothing is worse than no stretch.

    Pure numpy so the window arithmetic is testable without a display."""
    a = np.asarray(arr, float)
    if a.ndim == 3:
        a = a.mean(axis=2)
    if a.ndim != 2 or a.size == 0 or not r or r <= 0:
        return (None, None)
    h, w = a.shape
    yy, xx = np.ogrid[0:h, 0:w]
    d2 = (xx - float(cx)) ** 2 + (yy - float(cy)) ** 2
    din = a[d2 <= (inner * r) ** 2]
    lo, hi = ring
    dout = a[(d2 >= (lo * r) ** 2) & (d2 <= (hi * r) ** 2)]
    if din.size < 16 or dout.size < 16:
        return (None, None)
    return (float(np.median(din)), float(np.median(dout)))


def cal_stretch_window(disc_lum, paper_lum, pad_frac=CAL_STRETCH_PAD_FRAC,
                       min_span=CAL_STRETCH_MIN_SPAN):
    """(lo, hi) gray levels to map across full black→white for the verify-mode
    display, or **None** when there is nothing worth stretching.

    Derived from the frame's OWN measured disc and paper levels rather than
    from a fixed pair, because the exposure moves between runs (the carbon-
    black baseline medians 255). On a P3 baseline — disc 166, paper 186 —
    this returns about (157, 195), i.e. the ~160–192 window that makes the
    step visible.

    None when the disc is not darker than the paper, or when the step is
    narrower than `min_span`: at that point the display would be amplifying
    noise and inventing an edge, which is the one failure this feature must
    not have. A caller that gets None shows the raw crop."""
    if disc_lum is None or paper_lum is None:
        return None
    d, p = float(disc_lum), float(paper_lum)
    span = p - d
    if span < float(min_span):
        return None
    pad = float(pad_frac) * span
    lo = max(0.0, d - pad)
    hi = min(255.0, p + pad)
    if hi - lo < float(min_span):
        return None
    return (lo, hi)


def cal_stretch_lut(lo, hi):
    """256-entry lookup table mapping [lo, hi] linearly onto [0, 255], for
    PIL's `Image.point`. Clipping outside, so the disc reads black and the
    paper white and the ramp between them uses the whole display range.

    A LUT rather than arithmetic on the array: it is exact, it is what PIL
    wants for an RGB crop (lut * 3), and it cannot accidentally be applied
    to anything but the DISPLAY copy."""
    lo = max(0.0, min(254.0, float(lo)))
    hi = max(lo + 1.0, min(255.0, float(hi)))
    span = hi - lo
    out = []
    for i in range(256):
        if i <= lo:
            out.append(0)
        elif i >= hi:
            out.append(255)
        else:
            out.append(int(round(255.0 * (i - lo) / span)))
    return out


def verify_zoom(diam_px, canvas_w, canvas_h,
                fill=CAL_VERIFY_FILL_FRAC,
                max_zoom=CAL_VERIFY_MAX_OPEN_ZOOM):
    """The zoom the verify mode should OPEN at, so the fitted circle fills
    the canvas the moment the dialog appears.

    The verify mode used to open at fit-to-window, which on a 1080p frame is
    ~0.5x — the 577 px disc arrived 282 canvas px across, and the live line had
    to nag "below 1:1 — press Z before accepting". That nag was noise generated
    by a bad default: the operator is judging ONE BOUNDARY, not surveying the
    frame, so the frame is the wrong thing to fit. Fit the CIRCLE instead and
    the nag has nothing to warn about.

    `fill` of the canvas's SHORTER side, so the whole circle is on screen
    whichever way the canvas is shaped, with a margin of paper round it —
    the operator has to see the ramp on both sides of the stroke to judge
    whether it sits in the middle of it.

    Clamped ABOVE by `max_zoom` only. Deliberately not clamped below at
    1.0: a disc wider than the canvas would then be cropped, and half a
    boundary cannot be verified at all, whereas a slightly-under-1:1 view
    of a whole boundary can. Returns None when there is no fit to frame,
    and the caller then fits the frame as before.

    Pure, so the arithmetic is a headless test."""
    d = float(diam_px or 0.0)
    w, h = float(canvas_w or 0.0), float(canvas_h or 0.0)
    if d <= 0 or w <= 0 or h <= 0:
        return None
    z = float(fill) * min(w, h) / d
    if not (z > 0):
        return None
    return min(float(max_zoom), z)


# ---------------------------------------------------------------------------
# THE TWO THINGS THE ONE 📏 BUTTON DOES (`#215`, operator 2026-08-06 late)
#
# 📏 Calibrate… and 📏 Re-anchor scale… were folded into one entry point
# because they open THE SAME DIALOG and having two was confusing. What
# differs is not the measurement but what happens to it afterwards, and
# that follows the RUN'S STATE:
#
#   CALIBRATE  the anchor is held in memory and applied at the next Save.
#              NOTHING is written now. This is where a run with an open
#              review pass goes (and a run with nothing measured yet).
#   REANCHOR   the anchor is committed immediately: every mm² in data.csv
#              is re-derived from the px already stored there.
#
# The asymmetry — one writes now, the other does not — is the only real
# hazard in folding them, so the intent is named in the dialog's TITLE, on
# its PRIMARY BUTTON, and in the confirmation that follows. It is computed
# fresh at click time (EdgeReviewApp._scale_intent) so it can never be a
# stale label.
# ---------------------------------------------------------------------------
SCALE_INTENT_CALIBRATE = 'calibrate'
SCALE_INTENT_REANCHOR = 'reanchor'


def scale_intent_banner(intent):
    """The short, unmistakable statement of which of the two folded actions is
    about to happen. **The WINDOW TITLE's own prefix, in every mode** — and the
    one place this wording is written down, so the three title call sites
    cannot drift apart.

    It has been shortened twice by the operator in one day (`#215`,
    2026-08-07), and where it lives has moved with it:

    * it began as a 3–4 line paragraph opening the measuring modes' gate
      block, above the picture, on every run;
    * the morning's trim made it a 127-character tag on the round header;
    * the evening's cuts took it off the screen entirely: *"the commit warning
      belongs in one place — on the primary button and in its confirmation —
      not repeated in every mode's header."*

    What it may NOT lose is the asymmetry itself — one of the two folded
    actions writes data.csv the moment it is confirmed and the other does
    not — and it is still stated in THREE places, all of which are places
    where it decides something: this title prefix, the PRIMARY BUTTON on
    exactly the press that commits (`✔ Finish & RE-ANCHOR NOW` vs
    `✔ Finish calibration (applied at Save)`), and the re-anchor CONFIRMATION,
    which now opens by asking whether to overwrite the calibration on record.

    Pure, so the wording is a headless test: the writing branch's promise and
    the non-writing branch's must never be able to appear on the wrong one."""
    if intent == SCALE_INTENT_REANCHOR:
        return "RE-ANCHOR — writes data.csv"
    return "Calibrate — applied at Save"


# ---------------------------------------------------------------------------
# THE ON-SCREEN BUDGET — ALL THREE MODES (`#215`, operator 2026-08-07)
#
# The verify mode was decluttered first, alone, and the operator then drove
# the two measuring modes on real data and said the same thing about them:
# "trim the wall of text". Measured at a simulated 1080p, the verify mode was
# showing 2 lines / 124 chars while the circle and two-point modes were
# showing 9 lines each (1155 and 1393 chars). So the budget stops being the
# verify block's private rule and becomes the SCREEN's rule, in every mode.
#
# What survives in a measuring mode is only what a person needs WHILE
# placing points or sizing a circle:
#
#   1. WHICH ROUND THEY ARE ON  — the bold round header, and NOTHING ELSE on
#      it since the operator's second pass the same evening: the nominal disc
#      size and the folded-action tag both joined it in the morning's trim and
#      both came off again (see head_text). The commit warning belongs on the
#      primary button and in its confirmation, in one place, not on every
#      mode's header.
#   2. THE IMMEDIATE INSTRUCTION — one line: the gesture, and the aim rule,
#      which is the one instruction here with a measured cost behind it
#      (§1.3's +2.6 % diameter). Phrased as WHERE TO PUT THE MARK —
#      "straddle the edge: half the stroke on the disc, half on the paper" —
#      because the convention it achieves (the half-height of the ink step) is
#      a property of an intensity profile and not something a hand can aim at.
#      §1.3 owns the convention; this line owns the gesture.
#   3. THE LIVE READOUT — numbers, not prose, and in the two-point mode it
#      is also what says what the NEXT CLICK does, which is the only moment
#      auto-advance leaves to say it.
#
# Everything else was reference material and is now off screen: what the
# method is for, why the rounds are randomised and kept blind, what the
# statistics will do afterwards, the key-binding catalogue, and — second pass
# — the standing "N row(s) already carry px" consequence, which is now the
# opening question of the re-anchor confirmation. The keys that matter are
# named where they are needed instead — Z by the live line's sub-1:1 warning,
# Backspace by the ◀ Back button's own label. The full catalogue is in
# _calibrate_scale's docstring and in SLDEA_HANDOFF.md.
#
# NOTHING NUMERIC LEFT THE RECORD. Every number taken off a screen is still
# in scale_calibration_log.txt and in setup.txt's anchor block — verified by
# diffing a full accepted round-set's record in all three modes across each
# of these changes: byte-identical, same SHA-256.
# ---------------------------------------------------------------------------
CAL_SCREEN_MAX_LINES = 4        # the PATHOLOGICAL ceiling, EVERY mode: the
#                                 verify block's four (value, quality, a
#                                 stretch that could not be computed, a prior
#                                 anchor that differs) is the worst any mode
#                                 can reach, and it is reached only when all
#                                 of those are actually TRUE
CAL_SCREEN_MAX_LINES_ORDINARY = 3   # ... and the ORDINARY worst case, which
#                                 is what an operator meets: a prior anchor
#                                 that differs plus already-measured px rows.
#                                 Three in EVERY mode since the operator's
#                                 second pass (`#215`, 2026-08-07): the
#                                 measuring modes' gate row moved into the
#                                 commit button's own confirmation, so on an
#                                 ordinary run they show the instruction, the
#                                 round header and the live readout — nothing
#                                 else. This is the number the budget test
#                                 drives; the 4 above is the ceiling it may
#                                 not pass even when every warning is true.
CAL_SCREEN_MAX_LINE_CHARS = 180  # ... and no line may become a paragraph
# Total characters ON SCREEN, per mode, in the ORDINARY worst case — which is
# what the budget test drives. Two names because the two kinds of screen are
# not the same thing (a measuring mode carries a live per-click readout and a
# gesture instruction the verify mode has no equivalent of), but after the
# 2026-08-07 cuts THE TWO NUMBERS CONVERGED — measured 293 / 247 / 271 for
# verify / circle / twopoint against 291 / 498 / 546 before — so they are one
# value now, and that is itself the result: the three modes finally cost the
# same. They came down from 400 and 560, and they are deliberately tight,
# because every sentence cut from this screen was TRUE and every number cut is
# still in the record. A future reader will find them and be tempted, and
# slack left in a budget is slack that gets spent.
#
# NOT a cap on the pathological cases (a stretch that could not be computed,
# a diam_mm nobody measured, a refused fit): those are FAULTS, each capped at
# one line, and compressing a fault to fit a character budget is the wrong
# trade. CAL_SCREEN_MAX_LINES is what bounds them.
CAL_SCREEN_MAX_CHARS = 300      # verify
CAL_SCREEN_MAX_CHARS_MEASURING = 300
CAL_VERIFY_MAX_LINES = CAL_SCREEN_MAX_LINES   # the verify block's own cap,
#                                 kept as a name because verify_evidence is
#                                 a pure function with its own test
CAL_VERIFY_DEV_EPS_PCT = 0.005  # below this a prior anchor does not "differ"
                                # at the 2-dp the line would print, so the
                                # line is silence rather than "+0.00 %"


def verify_evidence(ref, diam_mm, recorded=None, n_px_rows=0,
                    stretch=None, diam_recorded=True):
    """Everything the verify mode puts in front of the operator — **at most
    CAL_VERIFY_MAX_LINES lines**, and that budget is the point.

    The verify mode was driven on a real disc (P3_2's baseline, automatic fit
    577.08 px) and the operator's verdict was two-part: *"the fit looks right,
    accept it. But the calibration screen is wayyyyyy too busy with text and
    unnecessary garbage."* So the premise is validated — a human CAN judge the
    fit by eye, and did, correctly. What failed was this block, which asked for
    every quality number the fitter reports and got 13 lines of them. Nineteen
    wrapped lines of 8-point prose is not evidence an operator reads; it is a
    wall they scroll past to reach the button, and it was stealing the canvas
    height from the ONE thing that is actually the verification: the dashed
    circle on the stretched frame.

    So, four lines, each earning its place:

    1. **the value being adopted** — diameter in px, the mm it is being
       called, and the mm/px that follows. This is the number the run's
       whole absolute mm² column hangs on, so it is stated, once.
    2. **the quality, two numbers only** — the fit residual as a PERCENTAGE
       of diameter, and circularity. Those are the two that would make a
       reader doubt the fit. `conf` is gone from the screen deliberately:
       it is *derived from* the same residual/circularity/coverage
       quantities, so it adds no independent information and nothing a
       human can act on. `n_edge`, arc coverage and interior fill are gone
       for the same reason — they qualify the residual rather than
       challenging it.
    3. **the picture's own warning, and only when it is true** — that the
       contrast stretch could NOT be computed on this frame, so the edge
       may be too faint to judge. The standing version of this line — *"View
       is contrast-stretched so the edge is visible… your eye is the
       check."* — came OFF the screen on 2026-08-06 late at the operator's
       request, who found it unnecessary. It was: on every normal run it
       said the same two things every time, and a disclaimer that is always
       true is a disclaimer nobody reads. **Both halves of it stay in the
       RUN RECORD** — the `guard:` string in setup.txt carries the whole
       statement, including that both of `anchor_guard`'s references are
       vacuous on an auto-verified anchor (`se.verify_note`), and
       `sldea_diag` repeats it in its verdicts and its text report. The
       honesty lives in the record, where a later reader needs it, not on
       the screen of the person judging one boundary in one moment.
       What survives on screen is the case that is NOT a standing
       disclaimer but a fault: a frame whose disc/paper step could not be
       measured has no stretch, and the operator is then looking at a
       nearly flat grey field and has to be told so.
    4. **the consequence, and ONLY when there is one** — the signed scale
       change against a prior anchor that actually differs, and that
       accepting re-derives the run's areas at the next Save (the
       `[critical]` partial-re-save entry in SLDEA_HANDOFF). With no prior
       anchor there is nothing to compare against and the line is absent:
       silence is the correct output, not a paragraph explaining the
       silence.

    EVERYTHING CUT IS STILL RECORDED. `n_edge`, arc coverage, interior
    fill, `conf`, the implied resting area and the full cross-check
    algebra all still reach the anchor block in setup.txt, the
    scale_calibration_log line and `sldea_diag`'s verdicts, unchanged —
    see `se.verify_note`, `se.append_calibration_log` and
    `sldea_diag.verdicts`. Decluttering the dialog cost no auditability: a
    reader coming to the run months later can still reconstruct why the
    anchor was trusted. What changed is that the OPERATOR, who is judging
    one boundary in one moment, is no longer handed the audit trail to read
    first.

    Pure, so the budget and the honesty are both headless tests rather than
    a screenshot. An empty string is never returned for a usable fit: if
    this block is blank the operator is being asked to approve a number
    they cannot see."""
    d = float((ref or {}).get('diam_px') or 0.0)
    if d <= 0:
        return ''
    dmm = float(diam_mm or 0.0)
    mmpp = (dmm / d) if d else 0.0
    rp = se.fit_resid_pct(ref)
    L = []
    # 1. THE VALUE. `diam_recorded` rides here rather than on a fifth line:
    # the gate's "the diameter was not recorded at capture" warning is a
    # qualifier ON this number, and the number is right there.
    L.append(f"Automatic fit — {d:.1f} px across = {dmm:.2f} mm "
             f"({mmpp:.6f} mm/px)"
             + ('' if diam_recorded else
                f"   ⚠ {dmm:.2f} mm is the settings default — the mask was "
                f"NOT measured at capture"))
    # 2. THE QUALITY, two numbers. Built from what the fitter actually
    # reported: a missing number is never printed as 0.
    q = []
    if rp is not None:
        q.append(f"fit residual {rp:.2f} % of diameter")
    circ = (ref or {}).get('circ')
    if circ is not None:
        q.append(f"circularity {float(circ):.3f}")
    L.append("Quality — " + ('   ·   '.join(q) if q else
                             "the fitter reported neither a residual nor a "
                             "circularity, so there is nothing here to "
                             "judge the fit by but the picture."))
    # 3. THE PICTURE'S WARNING — only when the stretch FAILED.
    #
    # The standing sentence ("View is contrast-stretched so the edge is
    # visible; the fit is measured on the raw frame. Nothing cross-checks
    # it — your eye is the check.") is GONE from the screen at the
    # operator's request, 2026-08-06 late. It is not gone from the RECORD:
    # se.verify_note puts the whole statement — the display-only stretch,
    # the absent cross-check and the algebra that makes an independent one
    # impossible — into setup.txt's `guard:` field, and sldea_diag repeats
    # it. Nothing here weakens what the run says about itself; what changed
    # is that the operator is no longer handed a disclaimer that is true on
    # every run before they look at the one boundary in front of them.
    #
    # What is NOT a standing disclaimer: a frame the stretch could not be
    # computed on. That is a fault in the picture the verification depends
    # on, it is false on a normal run, and it stays.
    if not stretch:
        L.append("⚠ View is NOT contrast-stretched (this frame's disc/paper "
                 "step could not be measured), so the edge may be too faint "
                 "to judge — zoom in before deciding.")
    # 4. THE CONSEQUENCE, only when a prior anchor exists AND differs.
    if recorded and recorded.get('diam_px'):
        rec = float(recorded['diam_px'])
        dev = 100.0 * (d - rec) / rec
        pct = se.rescale_pct(rec, d)
        if abs(dev) >= CAL_VERIFY_DEV_EPS_PCT:
            L.append(f"⚠ Accepting moves this run's scale {dev:+.2f} % from "
                     f"the {rec:.1f} px on record"
                     + ((f", re-deriving every mm² in the run "
                         f"{pct:+.2f} % at the next Save — including rows "
                         f"you never re-review." if n_px_rows else
                         ", and every mm² measured from here on.")
                        if pct is not None else '.'))
    return '\n'.join(L[:CAL_VERIFY_MAX_LINES])


# ---------------------------------------------------------------------------
# THE TWO-POINT MODE (label C) — two-point diameter, N rounds, the
# display randomly rotated
#
# The operator clicks two roughly-opposite points on the disc edge, as the
# pre-#215 dialog did, N times (default 5). The MEAN of the N diameters is
# the anchor. Two things make that better than the single pair it revives:
#
#   1. ROTATION between rounds is the load-bearing idea. Mis-judging
#      "exactly opposite" is a SYSTEMATIC error while the disc always sits
#      the same way up — one pair of clicks, one biased chord, forever
#      (that is run P3_2's +2.28 %). Rotate the display by a random angle
#      each round and the same misjudgement lands in a different direction
#      every time, so it becomes RANDOM and averaging suppresses it as
#      sqrt(n). It also averages out the human preference for horizontal
#      and vertical chords over diagonal ones.
#   2. NON-OCCLUDING MARKERS. A point marker with a hole in the middle
# leaves the edge visible under the judged point; a stroke laid along the
# boundary does not. This is the whole reason the two-point mode
# exists, so the markers are specified here (marker_shapes) rather than left to
# whatever the canvas call happened to draw.
#
# Everything is MEASURED IN ORIGINAL IMAGE COORDINATES: the clicks are
# mapped back through the inverse rotation and the diameter is computed in
# original px. A length is rotation-invariant, so a correct implementation
# gets the same answer either way — the point of doing it in original
# space is that the RECORDED click positions stay meaningful (comparable
# between rounds, and against the automatic fit's centre).
# ---------------------------------------------------------------------------

CAL_ROUNDS_TWOPOINT = se.CAL_ROUNDS_TWOPOINT     # 5
CAL_STROKE_STYLES = ('3 px solid', '1 px solid', '1 px dashed')
CAL_MARK_RING_VIEW = 7.0    # hollow ring radius, VIEW px — far enough out
                            # that its own 1 px stroke crosses the boundary
                            # ~7 px away from the point being judged
CAL_MARK_ARM_VIEW = 11.0    # crosshair arm outer end, VIEW px
CAL_MARK_GAP_VIEW = 3.0     # NOTHING is drawn within this of the click:
                            # the pixels the operator is actually judging
CAL_PT_NUDGE_PX = 1.0       # arrow-key nudge of the last placed point
CAL_PT_NUDGE_COARSE_PX = 5.0


def rotation_angles(n, rnd=None):
    """`n` display-rotation angles in degrees, one per twopoint-mode round —
    STRATIFIED: one uniform draw inside each of n equal sectors of the
    FULL circle, then shuffled so the order carries no information.

    Stratified rather than n independent uniform draws, because rotation
    is the mechanism and independent draws can fail to deliver it: five
    uniform angles land within 40 degrees of each other often enough to
    matter, and a round-set that never really rotated is a round-set whose
    systematic error never got randomized. Stratifying guarantees the
    coverage the sqrt(n) argument assumes.

    The whole circle, not a half: the human bias toward horizontal and
    vertical chords is 90-degree periodic, so sectors spanning only 180
    degrees would leave it half-sampled.

    `rnd` is any random.Random — pass a seeded one to make a session
    reproducible in a test."""
    import random as _random
    rnd = rnd or _random
    n = max(1, int(n))
    step = 360.0 / n
    angles = [i * step + rnd.uniform(0.0, step) for i in range(n)]
    rnd.shuffle(angles)
    return [a % 360.0 for a in angles]


def unrotate_point(rx, ry, rot_w, rot_h, img_w, img_h, deg):
    """Map a point in the ROTATED display image back to ORIGINAL image px.

    Matches PIL's `Image.rotate(deg, expand=True)` exactly in the part
    that matters. PIL rotates counter-clockwise about the ORIGINAL centre
    and then expands the canvas around the bounding box, whose centre is
    that same rotated centre; its affine matrix maps output -> input with
    phi = -deg. So the mapping is a rotation by -deg about the two
    centres, which is what this computes.

    PIL's expand arithmetic rounds the new size with ceil/floor, which can
    offset the canvas centre by up to half a pixel. That offset is a pure
    TRANSLATION and therefore cancels exactly in the difference between
    two points — the diameter is unaffected — while a single recorded
    click position can sit up to ~0.5 px out. Recorded positions are
    provenance, not measurements, so that is the right side to lose on.

    Display rotation also RESAMPLES, which softens the ink edge slightly.
    That is a real cost and it is not a bias: every round is rotated, so
    every round's edge is softened the same way, and the operator's
    judgement is degraded identically in all n rounds rather than in some
    of them. It inflates sigma a little; it does not move the mean."""
    phi = math.radians(-float(deg))
    c, s = math.cos(phi), math.sin(phi)
    dx = float(rx) - float(rot_w) / 2.0
    dy = float(ry) - float(rot_h) / 2.0
    return (c * dx + s * dy + float(img_w) / 2.0,
            -s * dx + c * dy + float(img_h) / 2.0)


def two_point_diameter(p1, p2):
    """Distance between two ORIGINAL-coordinate clicks — the two-point
    mode's fitted diameter for one round. Rotation-invariant by
    construction, which is what lets the display be rotated at all."""
    return math.hypot(float(p2[0]) - float(p1[0]),
                      float(p2[1]) - float(p1[1]))


def marker_shapes(vx, vy, ring_r=CAL_MARK_RING_VIEW,
                  arm=CAL_MARK_ARM_VIEW, gap=CAL_MARK_GAP_VIEW):
    """What to draw at a placed point, in VIEW px:
    {'ring': (x0, y0, x1, y1), 'arms': [(x0, y0, x1, y1) x4]}.

    A hollow ring plus a crosshair with a HOLE in the middle. Nothing is drawn
    within `gap` px of (vx, vy) — invariant `marker_clear_radius` asserts, and
    the reason the two-point mode exists: the circle mode's 3 px stroke sits ON
    the boundary and hides the pixels being aligned to. Never a filled
    dot, never a thick stroke through the edge."""
    return {'ring': (vx - ring_r, vy - ring_r, vx + ring_r, vy + ring_r),
            'arms': [(vx + gap, vy, vx + arm, vy),
                     (vx - gap, vy, vx - arm, vy),
                     (vx, vy + gap, vx, vy + arm),
                     (vx, vy - gap, vx, vy - arm)]}


def marker_clear_radius(vx, vy, shapes):
    """Closest approach of any drawn marker ink to the click point — the
    testable form of "the marker must not occlude the edge". Larger is
    better; 0 would mean something is drawn right on the judged pixel."""
    d = min(abs(shapes['ring'][2] - vx), abs(shapes['ring'][3] - vy))
    for x0, y0, x1, y1 in shapes['arms']:
        d = min(d, math.hypot(x0 - vx, y0 - vy), math.hypot(x1 - vx,
                                                            y1 - vy))
    return d


def chord_segment(p1v, p2v, gap=CAL_MARK_GAP_VIEW):
    """The measured chord as a line that STOPS `gap` px short of each
    endpoint, in VIEW px — or None when the two points are closer together
    than the gaps.

    Drawing the chord shows the operator what they measured; stopping it
    short keeps its ink off both judged points. It runs across the disc
    interior, not along the boundary, so it occludes nothing that is being
    judged in any case."""
    x1, y1 = float(p1v[0]), float(p1v[1])
    x2, y2 = float(p2v[0]), float(p2v[1])
    L = math.hypot(x2 - x1, y2 - y1)
    if L <= 2.0 * gap:
        return None
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    return (x1 + ux * gap, y1 + uy * gap, x2 - ux * gap, y2 - uy * gap)


def hot_slot(entries, chosen, sel):
    """Which outline reads as SELECTED on the card. `entries` is
    [(slot, candidate)], `chosen` the frame's accepted result (or None),
    `sel` the radio selection (a slot). An accepted frame follows its
    result; an unreviewed frame follows the radio -- candidate A used to
    render at the thin weight until its already-selected radio was
    clicked, because only an accepted result set the weight (#171)."""
    if chosen:
        for slot, c in entries:
            if c['method'] == chosen['method']:
                return slot
    if any(slot == sel for slot, _c in entries):
        return sel
    return None


class EdgeReviewApp:
    def __init__(self, root, path=None, auto=False, goto=None):
        self.root = root
        root.title("SLDEA Edge Review — Digital Multitool")
        root.geometry("1150x760")
        self.settings = dict(se.DEFAULT_SETTINGS)
        self.run = None
        self.rundir = None
        self.cands_all = {}     # frame row index -> candidate list
        self.pair_cands = {}    # row index -> (candidates, failure reason)
        # from an ON-DEMAND single-frame detect, so a trace of a frame no
        # pass ever covered still has a machine candidate to be ground
        # truth against (#162). Deliberately NOT cands_all: a lone frame
        # carries neither the ramp-order hysteresis bonus nor the same-kV
        # pair reconciliation, so these candidates must never enter the
        # review pass, the A/B/C radios, `has_pass` or a saved
        # active_area_px — see _machine_pairing (review 2026-08-06).
        self.results = {}       # row index -> chosen candidate | None=rejected
        self.traces = {}        # row index -> STAGED candidate D (#172)
        self._select_trace_once = False   # next _show selects D (just staged)
        self.auto_idx = set()   # auto-accepted row indices
        self.auto_rej = set()   # auto-rejected (no change / no edge)
        self.load_fail = {}     # row -> 'unreadable' | 'processing
        # failed: …' — frames not MEASURED this pass for file- or
        # code-level reasons, never a measurement verdict (audit
        # 2026-08-05: these used to launder into 'no change vs baseline'
        # / 'rejected (no reliable edge)'; the reason is kept so a
        # processing crash is not misreported as a missing file)
        self.frame_rows = []    # row indices that have a frame file
        self.pos = 0
        self.flags = {}         # CONFIRMED breakdown rows (rename + brand)
        self.advisories = {}    # notes-only (transient / uncorroborated)
        self.manual_ref = None  # px→mm anchor from 📏 — the SCALE GATE;
        self.base_ref = None    # reset per run (zoom moves between runs)
        self._base_ref_pending = None
        self._photo = None
        self._detq = _queue.Queue()
        # Detect-in-flight guard (audit 2026-08-05, critical): the Run
        # combobox and Browse… stayed live during a multi-minute detect,
        # and the stale worker/poll chain refilled cands_all, base_ref
        # and the Save button AFTER _pick_run's fail-closed reset —
        # writing run A's px areas through run B's anchor. Run switching
        # is disabled while a worker runs, and every queue item carries a
        # generation token so a stale chain can never resurrect state.
        self._detect_busy = False
        self._detect_gen = 0
        # auxiliary windows are modal or SINGLETON, never unbounded (#176)
        self._adv_win = None
        self._cal_win = None    # the gate dialog is a singleton too: the
        # grab is pointer-only, so review keys can pierce it and a second
        # gate dialog would chain a second detect worker (review 2026-08-05)
        self._cal_probe = None  # the live calibration dialog's own state,
        # published for the tests that drive it (see _calibrate_scale)
        self._howto_win = None  # ❓ How to use (`#238`) — singleton, and
        # NON-modal on purpose: the whole point is to read it beside the
        # window while working, not instead of it
        self._howto_scroll = None      # its canvas, published for the tests
        self._tips = {}          # control name -> live Tooltip (`#216`)
        self._hint = None        # the empty-canvas "press this" line (`#216`)
        self._primary_font = None   # kept alive by _install_styles (`#216`)
        self._build_ui()
        start = path or DEFAULT_PARENT
        self._populate_runs(start)
        # `--goto ROW` lands on a frame BEFORE anything else happens
        # (`#274`). With --auto as well the detect pass repositions to the
        # first unreviewed frame when it finishes, which is what --auto
        # means; the plot window never sends both.
        if goto is not None:
            self.goto_row(goto)
        if auto and self.rundir:
            root.after(300, self.detect)

    # ---------------- UI scaffolding ----------------
    def _install_styles(self):
        """The ONE accent in Edge Review: ▶ Detect Edges (`#216`).

        Deliberately NOT a restyle of the app — #32 owns that, and this is
        stock ttk on the vista theme. Measured on the Windows analysis PC
        (Tk 8.6.12, theme `vista`, Segoe UI 9): a named style's `font`,
        `padding` and `foreground` are all honoured by the native button
        element, so the accented button renders 105x31 against a plain
        88x25 and its label is drawn in the house blue. On a theme that
        ignores foreground the bold face and the extra padding still carry
        the emphasis, so it degrades to "bigger and bolder" rather than to
        nothing. No `default='active'`: <Return> is bound to ✔ Accept, and
        calling Detect the default button would be a lie.

        Secondary (Advanced…, 📏) is STOCK — geometry AND colour. The
        first version muted their label grey, guarding only against
        "smaller AND muted reads as disabled"; on the first real drive
        (2026-08-07) the mute ALONE read as disabled, and the operator
        was surprised the buttons worked. The style name stays applied as
        a hook, deliberately unconfigured.

        THE BOLD FONT IS HELD ON THE APP, not on the stack. A tkfont.Font
        deletes its named font from the interpreter when it is collected,
        and a style pointing at a deleted name falls back to the default
        face without a word — a bold accent that is silently not bold.
        It is per-app rather than a module cache because the name lives in
        the Tk interpreter, and the tests build and destroy roots.
        """
        st = ttk.Style()
        try:
            self._primary_font = tkfont.nametofont('TkDefaultFont').copy()
            self._primary_font.configure(weight='bold')
            st.configure('Primary.TButton', font=self._primary_font,
                         padding=(12, 4), foreground=PRIMARY_FG)
            # 'Secondary.TButton' stays on Advanced…/📏 as a hook but is
            # NOT configured: unstyled it inherits stock TButton, i.e. it
            # looks exactly as enabled as it is. See the PRIMARY_FG note.
        except tk.TclError as e:
            # a theme that refuses one of these must cost the ACCENT, not
            # the window: the button still works unstyled
            print(f"edge review: accent style unavailable ({e})")

    def _build_ui(self):
        self._install_styles()
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill='x')
        # THE TOP BAR READS LEFT TO RIGHT AS THE JOB (`#216`): pick the run,
        # press the one accented button, review, save on the far right. The
        # separators are the grouping — [run] | [the action] | [tools] — so
        # the two tool buttons stop competing with Detect for the eye.
        self.run_lbl = ttk.Label(top, text="Run:")
        self.run_lbl.pack(side=tk.LEFT)
        self.run_box = ttk.Combobox(top, width=44, state='readonly')
        self.run_box.pack(side=tk.LEFT, padx=6)
        self.run_box.bind('<<ComboboxSelected>>', lambda _e: self._pick_run())
        self.browse_btn = ttk.Button(top, text="Browse…",
                                     command=self._browse)
        self.browse_btn.pack(side=tk.LEFT)
        ttk.Separator(top, orient='vertical').pack(side=tk.LEFT, fill='y',
                                                   padx=10, pady=2)
        # THE primary action, and disabled until a run is picked — the
        # affordance doubles as the state, so a first-time operator is
        # never invited to press the button that would only say "Pick a
        # run first" in a modal (`#216`). _sync_detect_btn owns it from
        # here on; the detect-in-flight lock goes through the same place.
        self.detect_btn = ttk.Button(top, text="▶ Detect Edges",
                                     command=self.detect,
                                     style='Primary.TButton',
                                     state='disabled')
        self.detect_btn.pack(side=tk.LEFT, padx=10)
        ttk.Separator(top, orient='vertical').pack(side=tk.LEFT, fill='y',
                                                   padx=10, pady=2)
        # ONE settings-editing path in Edge Review: Advanced… covers every
        # knob with Apply+Save. The Tune button was removed (operator
        # decision 2026-07-31) — the tuner is a development instrument,
        # launched directly (deploy/Tune_SLDEA_Windows.bat unchanged).
        self.adv_btn = ttk.Button(top, text="Advanced…",
                                  command=self._advanced,
                                  style='Secondary.TButton')
        self.adv_btn.pack(side=tk.LEFT)
        # ONE scale entry point (operator decision 2026-08-06 late, `#215`).
        # It used to be two buttons — 📏 Calibrate… and 📏 Re-anchor scale… —
        # and the operator's objection was that they open THE SAME DIALOG, so
        # having two is confusing. They do; what differs is what happens to
        # the number afterwards, and that follows the run's state rather than
        # which button was pressed (see _scale_intent).
        #
        # The label names BOTH outcomes and never changes, deliberately. A
        # label that tracked the state would be one refresh away from
        # announcing the wrong one, and the asymmetry here is that one path
        # writes data.csv immediately and the other does not — a stale label
        # would be lying about exactly the thing that matters. Which of the
        # two is about to happen is computed at click time and said in the
        # dialog's title, on its primary button and in its confirmation.
        self.scale_btn = ttk.Button(top, text="📏 Calibrate / re-anchor…",
                                    command=self._scale_action,
                                    style='Secondary.TButton')
        self.scale_btn.pack(side=tk.LEFT, padx=(6, 0))
        # Save stays on the far RIGHT — the end of the job, and out of the
        # left-to-right flow (`#216`). It is NOT accented: two accents is
        # no accent, and its own affordance is the disabled state, which
        # the tooltip explains rather than leaving as a dead grey button.
        self.save_btn = ttk.Button(top, text="💾 Save to data.csv…",
                                   command=self.save, state='disabled')
        self.save_btn.pack(side=tk.RIGHT)
        # progress + TWO clocks (`#237`), stacked rather than side by side
        # so the toolbar keeps its width: the detection pass's own time
        # (the number an operator plans a run with, so it is the bold one)
        # over the session total.
        #
        # A FIXED BOX, right-aligned, for #179's reason one row up: with
        # geometry propagation on, this frame tracks its widest child --
        # text that changes every poll -- and the only widget with any
        # give left in the toolbar is the progress bar beside it, which
        # would then resize under its own moving fill.
        clock_font = ('TkDefaultFont', 9)
        clocks = ttk.Frame(top)
        clocks.pack(side=tk.RIGHT, padx=(8, 6))
        self.detect_lbl = tk.Label(clocks, text=detect_readout(), fg='#1f3a5f',
                                   anchor='e',
                                   font=clock_font + ('bold',))
        self.detect_lbl.pack(fill='x')
        self.clock_lbl = tk.Label(clocks, text="", fg='#5a6b7d', anchor='e',
                                  font=clock_font)
        self.clock_lbl.pack(fill='x')
        # Both dimensions measured from the widgets and the font rather
        # than typed in: the toolbar row is one button tall, so a height
        # left to the parent clipped the session line to 4 of its 21 px,
        # and a hard-coded pair would do it again on the next display
        # scaling or theme font.
        clocks.configure(
            width=tkfont.Font(font=clock_font + ('bold',)).measure(
                detect_readout(999, 3600.0)) + 8,
            height=(self.detect_lbl.winfo_reqheight()
                    + self.clock_lbl.winfo_reqheight()))
        clocks.pack_propagate(False)
        self.prog = ttk.Progressbar(top, length=180, mode='determinate')
        self.prog.pack(side=tk.RIGHT, padx=6)
        self._t0 = None             # start of the CURRENT detection pass
        self._t_session = time.time()   # window open — never reset
        self._clock_on = True
        self._tick_clock()

        mid = ttk.Frame(self.root)
        mid.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(mid, width=VIEW_W, height=VIEW_H, bg='#222',
                                highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill='both', expand=True,
                         padx=(6, 0), pady=4)
        # the card follows the canvas, not a constant (#178): re-render on
        # resize, debounced -- <Configure> streams during a drag
        self._view_wh = (VIEW_W, VIEW_H)
        self._resize_job = None
        self.canvas.bind('<Configure>', self._canvas_resized)

        side = ttk.Frame(mid, padding=8, width=SIDE_W)
        side.pack(side=tk.RIGHT, fill='y')
        # FIXED box (#179): with geometry propagation on, the width above
        # is inert and the panel tracked its widest child -- the radio
        # text, which changes every frame -- sliding the buttons out from
        # under a rapid-clicking cursor
        side.pack_propagate(False)
        self._side = side
        self._side_font = tkfont.nametofont('TkDefaultFont')
        self.info = tk.Label(side, text="pick a run and Detect",
                             justify='left', anchor='nw',
                             font=('TkDefaultFont', 10),
                             height=INFO_LINES, wraplength=SIDE_W - 24)
        self.info.pack(fill='x', pady=(0, 6))
        self.cand_var = tk.IntVar(value=0)
        self.cand_frame = ttk.LabelFrame(side, text="Candidates", padding=6)
        self.cand_frame.pack(fill='x')
        self.cand_radios = []
        for k in range(4):
            row = ttk.Frame(self.cand_frame)
            row.pack(fill='x')
            # swatch carries the color; the TEXT stays readable (colored
            # label text was 1.6:1 and the mapping was color-only — audit
            # 2026-07-25; letters are also drawn ON the image now)
            tk.Label(row, width=2, bg=CAND_COLORS[k],
                     text=CAND_KEYS[k], fg='black').pack(side='left',
                                                         padx=(0, 4))
            rb = tk.Radiobutton(
                row, text="—", anchor='w',
                variable=self.cand_var, value=k,
                # D is a tool, not a precomputed candidate: its radio
                # opens the tracer; Done stages, Accept commits (#172)
                command=self._trace if k == TRACE_SLOT
                else self._choose_current)
            rb.pack(side='left', fill='x', expand=True)
            self.cand_radios.append(rb)
        bt = ttk.Frame(side)
        bt.pack(fill='x', pady=6)
        self.accept_btn = ttk.Button(bt, text="✔ Accept (Enter)",
                                     command=self._accept_next)
        self.accept_btn.pack(side=tk.LEFT)
        self.reject_btn = ttk.Button(bt, text="✘ Reject (R)",
                                     command=self._reject)
        self.reject_btn.pack(side=tk.LEFT, padx=6)
        nav = ttk.Frame(side)
        nav.pack(fill='x')
        self.prev_btn = ttk.Button(nav, text="◀ Prev",
                                   command=lambda: self._step(-1))
        self.prev_btn.pack(side=tk.LEFT)
        self.next_btn = ttk.Button(nav, text="Next ▶",
                                   command=lambda: self._step(+1))
        self.next_btn.pack(side=tk.LEFT, padx=6)
        self.unrev_btn = ttk.Button(nav, text="Next unreviewed",
                                    command=self._next_unreviewed)
        self.unrev_btn.pack(side=tk.LEFT)
        self.queue_lbl = tk.Label(side, text="", fg='#8a5a00', anchor='w',
                                  justify='left')
        self.queue_lbl.pack(fill='x', pady=(8, 0))
        self.status = tk.Label(self.root, text="idle", bd=1, relief=tk.SUNKEN,
                               anchor='w')
        self.status.pack(side=tk.BOTTOM, fill='x')
        # ❓ How to use — BOTTOM-RIGHT of the window (`#238`). Packed at the
        # BOTTOM *after* the status strip on purpose: with side=BOTTOM each
        # slave takes the bottom of what is left, so the strip keeps the
        # window's own bottom edge and this row sits directly above it,
        # flush right. Nothing above is touched — the top bar is where the
        # RUN's controls live, and a "where do I start" affordance that sat
        # among them would be one more thing to read before starting.
        foot = ttk.Frame(self.root, padding=(6, 3))
        foot.pack(side=tk.BOTTOM, fill='x')
        self.howto_btn = ttk.Button(foot, text=HOWTO_BTN_TEXT,
                                    command=self._howto)
        self.howto_btn.pack(side=tk.RIGHT)
        self._attach_tooltips()

        for key, fn in (('<Key-1>', lambda e: self._pick_k(0)),
                        ('<Key-2>', lambda e: self._pick_k(1)),
                        ('<Key-3>', lambda e: self._pick_k(2)),
                        ('<Key-a>', lambda e: self._pick_k(0)),
                        ('<Key-b>', lambda e: self._pick_k(1)),
                        ('<Key-c>', lambda e: self._pick_k(2)),
                        ('<Key-r>', lambda e: self._reject()),
                        ('<Key-R>', lambda e: self._reject()),
                        ('<Key-4>', lambda e: self._trace()),
                        ('<Key-d>', lambda e: self._trace()),
                        ('<Key-D>', lambda e: self._trace()),
                        ('<Key-t>', lambda e: self._trace()),
                        ('<Key-T>', lambda e: self._trace()),
                        ('<Return>', lambda e: self._accept_next()),
                        ('<Left>', lambda e: self._step(-1)),
                        ('<Right>', lambda e: self._step(+1))):
            self.root.bind(key, fn)

    # ---------------- hover help + the primary action's state ----------
    def _attach_tooltips(self):
        """Hover help on every control in the top bar and the review card
        (`#216`, and the operator asked for it again unprompted after a
        long session). Every string lives in TIPS; the key bindings quoted
        in them are the ones bound at the end of _build_ui.

        `self._tips` is the live inventory, keyed the same as TIPS, so the
        tests can assert coverage against the controls rather than against
        a list that would rot the first time one is added."""
        self._tips = {}
        for name, widget in (('run_box', self.run_box),
                             ('browse_btn', self.browse_btn),
                             ('detect_btn', self.detect_btn),
                             ('adv_btn', self.adv_btn),
                             ('scale_btn', self.scale_btn),
                             ('save_btn', self.save_btn),
                             ('accept_btn', self.accept_btn),
                             ('reject_btn', self.reject_btn),
                             ('prev_btn', self.prev_btn),
                             ('next_btn', self.next_btn),
                             ('unrev_btn', self.unrev_btn)):
            self._tips[name] = add_tooltip(widget, TIPS[name])
        # the "Run:" caption is part of the same control to a pointer
        add_tooltip(self.run_lbl, TIPS['run_box'])
        # A/B/C say which key picks them; D is the tracer, not a candidate
        for k in range(3):
            self._tips[f'cand{k}'] = add_tooltip(
                self.cand_radios[k],
                TIPS['cand'].format(k=CAND_KEYS[k], n=k + 1))
        self._tips['trace'] = add_tooltip(self.cand_radios[TRACE_SLOT],
                                          TIPS['trace'])
        # ▶ Detect Edges is the one tip that MOVES: a greyed-out button
        # whose tooltip describes what it would do, without saying why it
        # is grey, leaves the state the affordance was meant to explain
        # unexplained.
        self._sync_detect_btn()

    def _sync_detect_btn(self):
        """▶ Detect Edges is live exactly when there is a run to detect
        and no worker in flight (`#216`).

        Disabled-until-a-run-is-picked makes the affordance carry the
        state: the button used to be live from launch and answer a click
        with a modal 'Pick a run first'. It matters in COCKPIT MODE, where
        Edge Review is opened on a parent folder — an empty parent, or one
        whose named target is missing, leaves no run loaded at all.

        The detect-in-flight lock (audit 2026-08-05) routes through here
        too, so there is ONE writer of this button's state."""
        busy = self._detect_busy
        ready = self.run is not None and not busy
        self.detect_btn.config(state='normal' if ready else 'disabled')
        tip = self._tips.get('detect_btn')
        if tip is not None:
            tip.text = (TIPS['detect_btn_busy'] if busy else
                        TIPS['detect_btn'] if self.run is not None else
                        TIPS['detect_btn_disabled'])

    def _canvas_hint(self, text=None):
        """The empty card area SAYS what to press (`#216`).

        Passing None clears it, which every path that paints the canvas
        does — the hint belongs to the empty state only. It is re-drawn on
        resize (_redraw_card) because a <Configure> would otherwise leave
        the operator staring at the blank canvas the hint exists for."""
        self._hint = text or None
        try:
            self.canvas.delete('hint')
        except tk.TclError:                # canvas already gone
            return
        if not self._hint:
            return
        w, h = self._view_size()
        self.canvas.create_text(w // 2, h // 2, text=self._hint,
                                fill='#d7dde5', justify='center',
                                width=max(220, w - 80), tags='hint',
                                font=('TkDefaultFont', 13))

    # ---------------- run selection ----------------
    def _list_runs(self, parent):
        # Any directory holding a run CSV is a run — custom-named runs
        # (the SLDEA tab allows free names) were invisible before and
        # auto-open silently fell back to the newest SLDEA_* run instead
        # (audit 2026-07-25). se.run_csv also accepts a renamed data1.csv /
        # data2.csv, which the bench uses to open several runs in Excel at
        # once (2026-07-28).
        try:
            names = sorted(
                (n for n in os.listdir(parent)
                 if os.path.isdir(os.path.join(parent, n)) and
                 se.run_csv(os.path.join(parent, n))),
                reverse=True)
        except OSError:
            return []
        out = []
        for n in names:
            done = ''
            try:
                with open(se.run_csv(os.path.join(parent, n))) as f:
                    # length-guarded: a truncated/blank line used to raise
                    # IndexError and crash the whole listing
                    if 'active_area_px' in (f.readline() or '') and any(
                            len(c := line.split(',')) > 10 and c[10].strip()
                            for line in f):
                        done = '  ✓ processed'
            except OSError:
                pass
            out.append(n + done)
        return out

    def _populate_runs(self, path):
        """Accept a run dir (holds a run CSV), a parent full of runs, or a
        campaign wrapper one level above such a parent.

        The wrapper case goes through se.runs_parent -- the same one-level
        descent the tuner and the Windows launcher resolve with (`#261`),
        so opening the cockpit on SCPI_SLDEA_DIR lists the same runs the
        Tune button would open. A folder that IS a run still wins: the
        run_csv test comes first."""
        path = os.path.abspath(path)
        if se.run_csv(path):
            self.parent = os.path.dirname(path)
            preselect = os.path.basename(path)
        else:
            self.parent = se.runs_parent(path)
            preselect = None
        runs = self._list_runs(self.parent)
        self.run_box['values'] = runs
        if runs:
            want = 0
            if preselect:
                for i, r in enumerate(runs):
                    if r.split('  ')[0] == preselect:
                        want = i
                        break
                else:
                    # NEVER silently fall back to a different run when an
                    # explicit target was given (audit 2026-07-25: auto-open
                    # used to process the newest run instead).
                    self.status.config(
                        text=f"target run '{preselect}' not found in "
                             f"{self.parent} — pick one manually")
                    self._sync_detect_btn()
                    self._canvas_hint(HINT_PICK_RUN)
                    return
            self.run_box.current(want)
            self._pick_run()
        else:
            self.status.config(text=f"no runs (dirs holding a data CSV) "
                                    f"in {self.parent}")
            # COCKPIT MODE, empty parent: no run is loaded, so ▶ Detect
            # Edges stays grey and the canvas says which box to use first
            self._sync_detect_btn()
            self._canvas_hint(HINT_PICK_RUN)

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.parent or DEFAULT_PARENT)
        if d:
            self._populate_runs(d)

    def _detect_ui(self, busy):
        """Run switching is closed while a detect worker runs — the
        combobox and Browse… used to stay live and cross-contaminate the
        freshly picked run with the old worker's output (audit
        2026-08-05)."""
        # ▶ Detect Edges goes through _sync_detect_btn, which ANDs this
        # lock with "is a run even loaded" (`#216`) — re-enabling it here
        # unconditionally would hand a runless cockpit a live button again
        self._sync_detect_btn()
        self.run_box.config(state='disabled' if busy else 'readonly')
        self.browse_btn.config(state='disabled' if busy else 'normal')

    def _pick_run(self):
        name = (self.run_box.get() or '').split('  ')[0]
        if not name:
            return
        self.rundir = os.path.join(self.parent, name)
        # Fail CLOSED: reset the review state and the SCALE GATE before
        # anything that can raise -- an exception mid-load used to leave
        # the new run paired with the previous run's manual anchor,
        # results and live Save button (review 2026-08-05: that writes
        # run A's scale into run B, the exact error the gate prevents).
        # A programmatic switch mid-detect also invalidates the worker:
        # the generation bump makes every queued item stale, and
        # _base_ref_pending can never carry a previous run's disc into
        # _finish_detect (audit 2026-08-05).
        self._detect_gen += 1
        self._detect_busy = False
        self._base_ref_pending = None
        self._detect_ui(busy=False)
        self.run = None
        self.frame_rows = []
        self.cands_all, self.results, self.flags = {}, {}, {}
        self.pair_cands = {}
        self.advisories = {}
        self.traces = {}
        self.auto_idx, self.auto_rej = set(), set()
        self.load_fail = {}
        self.base_ref = None
        self.manual_ref = None
        self.pos = 0
        # the detection readout belongs to a PASS, so it dies with the run
        # it measured (`#237`). The batch cockpit switches runs inside one
        # session, and the old single clock kept the previous run's number
        # on screen through the switch — where it reads as this run's.
        self._t0 = None
        self._set_detect_clock()
        self.save_btn.config(state='disabled')
        self._sync_detect_btn()          # self.run is None again (`#216`)
        try:
            self.run = se.load_run(self.rundir)
            self.settings = se.load_settings(self.rundir)
        except Exception as e:
            messagebox.showerror("Run", f"Cannot read {name}: {e}")
            self.run = None
            self._sync_detect_btn()
            self._canvas_hint(HINT_PICK_RUN)
            return
        self.frame_rows = [i for i, r in enumerate(self.run['rows'])
                           if (r.get('frame_file') or '').strip()]
        n = len(self.frame_rows)
        # the CSV listing a frame does not mean the disk holds it —
        # count the missing ones up front instead of discovering them as
        # blank cards mid-review (audit 2026-08-05)
        missing = sum(
            1 for i in self.frame_rows
            if not os.path.exists(se.frame_path(self.run,
                                                self.run['rows'][i]) or ''))
        miss_txt = (f" ({missing} MISSING on disk — kept unreadable, "
                    f"never re-measured)" if missing else "")
        # ONE STORY ABOUT HOW TO START (`#216`). This line used to read
        # "📏 Calibrate / re-anchor, then Detect", which is the pre-gate
        # order: since the scale gate (2026-08-05) Detect DIVERTS to the
        # calibration itself and chains back, so telling the operator to
        # press 📏 first contradicts the button that is now accented and
        # the hint on the empty canvas. The gate is still named, because
        # it is why the first Detect opens a dialog instead of detecting.
        self.status.config(
            text=f"{name}: {len(self.run['rows'])} snapshots, {n} frames "
                 f"listed{miss_txt} — press ▶ Detect Edges "
                 f"(it opens 📏 Calibrate / re-anchor first when this run "
                 f"has no anchor; diam {self.settings['diam_mm']:g} mm; "
                 f"scale gate re-arms per run)")
        self.canvas.delete('all')
        self._canvas_hint(HINT_DETECT)
        self._sync_detect_btn()
        self.info.config(text=f"{name}\n{n} frames ready")

    # ---------------- detection ----------------
    def _tick_clock(self):
        """The SESSION clock, once a second for the life of the window
        (`#237`). It is not stopped by Save and not reset by a run switch;
        the detection readout beside it is the one that belongs to a pass
        and is repainted by `_set_detect_clock`."""
        if not self._clock_on:
            return
        try:
            self.clock_lbl.config(
                text=session_readout(time.time() - self._t_session))
        except tk.TclError:
            self._clock_on = False      # the window closed under the tick
            return
        self.root.after(1000, self._tick_clock)

    def _set_detect_clock(self, n_frames=None, secs=None, total=None):
        """Repaint the DETECTION readout — see `detect_readout` for the
        three states. Called with no arguments it says 'not run', which is
        what a freshly picked run and a scale-only re-anchor both are."""
        self.detect_lbl.config(text=detect_readout(n_frames, secs, total))

    def _banner(self, text):
        """Big unmissable state banner drawn over the image area."""
        self.canvas.delete('banner')
        if text:
            w, h = self._view_size()
            self.canvas.create_rectangle(0, h // 2 - 42, w, h // 2 + 42,
                                         fill='#b36b00', outline='',
                                         tags='banner')
            self.canvas.create_text(w // 2, h // 2, text=text, fill='white',
                                    font=('TkDefaultFont', 20, 'bold'),
                                    tags='banner')

    def _no_baseline_refusal(self):
        """REFUSE-DON'T-FABRICATE (audit 2026-08-05, critical): with the
        baseline frame missing/0-byte/undecodable there is no difference
        to image — the old fallback auto-accepted the ROI *background*
        at 2.74x the true area under the operator's perfectly good
        manual anchor. Nothing is detected; every frame stays in the
        review queue for hand-tracing or until the baseline is
        restored."""
        messagebox.showerror(
            "Detect",
            "The BASELINE frame is unreadable (missing, 0-byte or "
            "truncated) — no difference imaging is possible, and every "
            "detected area would be a guess.\n\nRestore the baseline "
            "frame, or hand-trace frames individually (D). Nothing was "
            "detected or auto-accepted.")
        self.status.config(
            text="detection REFUSED: baseline frame unreadable — restore "
                 "it or hand-trace (D); nothing was measured")
        # the hand-trace escape hatch must be able to SAVE: traced +
        # accepted rows flow through the normal (gated, scaled) path,
        # while everything untouched stays untouched
        self.save_btn.config(state='normal')
        if self.frame_rows:
            self.pos = 0
            self._show()

    def detect(self):
        if not self.run:
            messagebox.showinfo("Detect", "Pick a run first")
            return
        if self._detect_busy:
            return
        if not self.frame_rows:
            messagebox.showinfo(
                "Detect", "This run has no frames on disk (the camera was "
                "busy or dry-run frames were skipped).")
            return
        if self.manual_ref is None:
            # SCALE GATE (operator decision 2026-08-05): the camera zoom
            # moves between runs, so the px→mm anchor is clicked by hand
            # on every run before any detection; the automatic disc fit
            # is a cross-check, not the anchor. Detection chains once the
            # clicks land.
            self._calibrate_scale(then_detect=True)
            return
        base = self._base_gray()
        if base is None:
            self._no_baseline_refusal()
            return
        # Every Detect pass starts CLEAN: stale results from a previous
        # pass (old settings, manual picks) used to survive re-detection
        # and get saved as a silent mix of two passes (audit 2026-07-25).
        # Staged traces clear too — their polygons are already safe in
        # edge_labels.json (appended at trace-Done, #172).
        self.cands_all, self.results, self.flags = {}, {}, {}
        self.pair_cands = {}
        self.advisories = {}
        self.traces = {}
        self.auto_idx, self.auto_rej = set(), set()
        self.load_fail = {}
        self.base_ref = None
        self._base_ref_pending = None
        self._detect_gen += 1
        self._detect_busy = True
        self._detect_ui(busy=True)
        # a re-detect must not leave the PREVIOUS pass's Save live while
        # the new results stream in (audit 2026-08-05)
        self.save_btn.config(state='disabled')
        # a re-detect discards the previous pass's frozen time with the
        # previous pass's results — this readout is about the pass that is
        # running now (`#237`)
        self._t0 = time.time()
        self._set_detect_clock(0, 0.0, len(self.frame_rows))
        self.prog.config(maximum=len(self.frame_rows), value=0)
        self._canvas_hint(None)        # the hint's job is done (`#216`)
        self.canvas.delete('all')
        self._banner(f"DETECTING…  0/{len(self.frame_rows)}")
        self.status.config(text="detecting…")
        gen = self._detect_gen
        threading.Thread(
            target=self._detect_worker,
            args=(gen, self.run, list(self.frame_rows),
                  dict(self.settings), base),
            daemon=True).start()
        self.root.after(100, lambda: self._poll_detect(gen))

    def _base_gray(self):
        for i in self.frame_rows:
            if self.run['rows'][i].get('tag') == 'baseline':
                return se.load_gray(se.frame_path(self.run,
                                                  self.run['rows'][i]))
        return None

    def _base_frame_name(self):
        """Basename of the frame `_base_gray` (and so the automatic fit)
        reads — or '' when there is no baseline-tagged row.

        The verify mode draws the automatic fit's circle over the frame the
        operator is looking at, so it has to know that the two are the SAME
        FILE. `_anchor_frame` can legitimately serve a later activated frame
        while `_base_gray` only ever serves the baseline row, and the fallback
        path (an unreadable baseline PNG) is exactly when they diverge."""
        for i in self.frame_rows:
            if self.run['rows'][i].get('tag') == 'baseline':
                p = se.frame_path(self.run, self.run['rows'][i])
                return os.path.basename(p) if p else ''
        return ''

    def _detect_worker(self, gen, run, frame_rows, settings, base):
        # Per-frame try + sentinel in finally: one bad frame (shape
        # mismatch, decode error) used to kill the thread silently and
        # leave 'DETECTING…' stuck forever (audit 2026-07-25). The
        # worker binds run/frame_rows/settings at start and tags every
        # queue item with its generation — it must never read live app
        # state, which a mid-flight run switch swaps out from under it
        # (audit 2026-08-05).
        try:
            self._detq.put((gen, 'base_ref',
                            se.baseline_disc(base, settings)))
            prev = None
            for i in frame_rows:
                fail = None
                try:
                    img = se.load_gray(se.frame_path(run, run['rows'][i]))
                    if img is None:
                        # a file that will not read is NOT an empty
                        # detection — the distinction must survive to
                        # the review queue (audit 2026-08-05)
                        fail = 'unreadable'
                        cands = []
                    else:
                        cands = se.candidates(base, img, settings,
                                              prev_method=prev)
                except Exception as e:
                    # a readable frame whose DETECTION raised is not a
                    # disk problem — record the true cause, or the
                    # operator chases a missing file that exists
                    # (review 2026-08-05)
                    print(f"detect: frame {i} failed: {e}")
                    fail = f'processing failed: {e}'
                    cands = []
                if cands:
                    prev = cands[0]['method']
                self._detq.put((gen, i, (cands, fail)))
        finally:
            self._detq.put((gen, None, None))

    def _poll_detect(self, gen):
        if gen != self._detect_gen:
            return                  # a run switch invalidated this chain
        done = False
        while True:
            try:
                item = self._detq.get_nowait()
            except _queue.Empty:
                break
            g, key, payload = item
            if g != self._detect_gen:
                continue            # stale worker output: drop, never apply
            if key is None:
                done = True
                break
            if key == 'base_ref':
                self._base_ref_pending = payload
                continue
            cands, fail = payload
            self.cands_all[key] = cands
            if fail:
                self.load_fail[key] = fail
        n, total = len(self.cands_all), len(self.frame_rows)
        self.prog.config(value=n)
        el = time.time() - self._t0
        eta = (el / n * (total - n)) if n else 0
        self._set_detect_clock(n, el, total)
        self.status.config(
            text=f"detecting… {n}/{total}  —  elapsed {fmt_dur(el)}"
                 + (f", ~{fmt_dur(eta)} left" if n else ""))
        self._banner(f"DETECTING…  {n}/{total}")
        if done:
            self._finish_detect()
        else:
            self.root.after(100, lambda: self._poll_detect(gen))

    def detect_all_sync(self):
        """Synchronous detection (used by --auto tests and headless runs)."""
        # this pass, not the first one of the session: `_t0 or time.time()`
        # made a second sync pass report the time since the FIRST (`#237`)
        self._t0 = time.time()
        self.cands_all, self.results, self.flags = {}, {}, {}
        self.pair_cands = {}
        self.advisories = {}
        self.traces = {}
        self.auto_idx, self.auto_rej = set(), set()
        self.load_fail = {}
        base = self._base_gray()
        if base is None:
            self._base_ref_pending = None
            self._no_baseline_refusal()
            return
        self._base_ref_pending = se.baseline_disc(base, self.settings)
        prev = None
        for i in self.frame_rows:
            try:
                img = se.load_gray(
                    se.frame_path(self.run, self.run['rows'][i]))
                if img is None:
                    self.load_fail[i] = 'unreadable'
                    self.cands_all[i] = []
                    continue
                self.cands_all[i] = se.candidates(
                    base, img, self.settings, prev_method=prev)
            except Exception as e:
                # same per-frame containment as the threaded worker —
                # one bad frame must not abort the whole sync pass
                # (review 2026-08-05)
                print(f"detect: frame {i} failed: {e}")
                self.load_fail[i] = f'processing failed: {e}'
                self.cands_all[i] = []
                continue
            if self.cands_all[i]:
                prev = self.cands_all[i][0]['method']
        self._finish_detect()

    def _finish_detect(self):
        self.auto_rej = set()
        self._detect_busy = False
        self._detect_ui(busy=False)
        # px→mm reference traced on the BASELINE frame itself (non-diff);
        # manual calibration (📏) overrides it.
        self.base_ref = self._base_ref_pending
        # the pre/post pair is the run's own control: agreement raises
        # confidence, contradiction forces review on both members
        se.reconcile_pairs(self.run['rows'], self.cands_all, self.settings)
        for i in self.frame_rows:
            if i in self.load_fail:
                # an unreadable file or a per-frame processing crash is
                # not a measurement outcome: the row stays in the review
                # queue, clearly labeled with its true cause, and its
                # previously saved values survive a Save untouched
                # (audit 2026-08-05: these auto-rejected as 'no change
                # vs baseline' and Save blanked a hand-traced terminal-
                # breakdown measurement)
                continue
            cands = self.cands_all.get(i, [])
            if cands and not se.needs_review(cands, self.settings):
                self.results[i] = dict(cands[0])
                self.auto_idx.add(i)
            elif not cands:
                # honest no-change/no-edge: nothing to choose, so auto-reject
                # (browse back + lower min_diff in Advanced to disagree)
                self.results[i] = None
                self.auto_rej.add(i)
        self._recount()
        self.save_btn.config(state='normal')
        self.prog.config(value=len(self.frame_rows))
        self._banner(None)
        q = self._queue_list()
        # THE DETECTION READOUT FREEZES HERE (`#237`) — the pass is over,
        # and everything after this point is the human's time, not the
        # machine's. The session clock beside it carries on.
        dt = (time.time() - self._t0) if self._t0 else None
        took = fmt_dur(dt) if dt is not None else '?'
        self._set_detect_clock(len(self.frame_rows), dt)
        if self.manual_ref:
            # the auto disc fit is a CROSS-CHECK of the operator's fit,
            # not the anchor (scale gate, 2026-08-05). Since #215 the
            # SAME guard runs at calibration time (se.anchor_guard, ~1%
            # in diameter and in mask area) — this repeat is the
            # detect-time restatement, and it also covers the paths that
            # skip the dialog's guard: a REUSED recorded anchor, and a
            # settings change (diam_mm) made after calibrating. The old
            # tiering fired a modal only past 3%, which is how P3_2's
            # 2.28% shipped in silence.
            verified = se.guard_is_vacuous(self.manual_ref)
            sc = (f"; scale: "
                  + ("AUTO-VERIFIED " if verified else "manual ")
                  + f"{self.manual_ref['diam_px']:.0f} px")
            spr = self.manual_ref.get('spread_pct')
            if spr is not None:
                # quote the MEAN SE, which is what the gate judges and what
                # §2.1 budgets — the raw range is not comparable between an
                # n=3 and an n=5 anchor (2026-08-06 evening)
                nr = self.manual_ref.get('n_rounds')
                sep = self.manual_ref.get('se_pct')
                if sep is None:
                    sig = se.sigma_from_range(spr, nr)
                    sep = (sig / math.sqrt(nr)) if (sig and nr) else None
                sc += (f" (method "
                       f"{se.cal_mode_text(self.manual_ref.get('cal_mode'))}"
                       f", "
                       f"avg of {nr if nr is not None else '?'}, range "
                       f"{spr:.2f}%"
                       + (f", SE {sep:.2f}%"
                          + ('' if sep <= se.CAL_SE_PCT else ' ⚠')
                          if sep is not None
                          else ', SE not convertible ⚠') + ')')
            guard = se.anchor_guard(self.manual_ref['diam_px'],
                                    self.base_ref, self.settings['diam_mm'])
            if verified:
                # THE VACUOUS CROSS-CHECK, NOT SHOWN (`#215` the verify mode).
                # This anchor IS the automatic fit, so `guard` reads
                # +0.00 % on both of its tests by construction — printing
                # "vs auto disc: +0.0% apart ✓" here would be a green tick
                # from a test that cannot fail, on any frame, however wrong
                # the fit is. What the operator gets instead is the fit's
                # own quality, which is the evidence they actually judged.
                rp = se.fit_resid_pct(self.manual_ref)
                sc += (" (operator-approved automatic fit: circ "
                       f"{float(self.manual_ref.get('fit_circ') or 0):.3f}, "
                       f"conf "
                       f"{float(self.manual_ref.get('fit_conf') or 0):.3f}"
                       + (f", resid {rp:.2f}% of diam" if rp is not None
                          else '')
                       + ") ⚠ NOT cross-checked — no independent check of "
                         "an automatic anchor exists: declaring the fitted "
                         "disc "
                       f"{self.settings['diam_mm']:g} mm makes the mask "
                       "area test pass by construction")
                # THE ONE THING that is NOT vacuous on a verified anchor:
                # whether the fit THIS detection pass just made is still the
                # fit that was approved. It normally is, to the bit (both
                # come from se.baseline_disc's cache on the same frame), so
                # any daylight here means the baseline changed underneath a
                # reused or stale anchor — which is real information, not an
                # identity. Reported as a deviation, and never as a tick.
                if (guard['available']
                        and abs(guard['diam_pct']) > 0.01):
                    sc += (f" ⚠⚠ AND the automatic fit on this run is NOW "
                           f"{guard['auto_diam_px']:.0f} px, "
                           f"{-guard['diam_pct']:+.2f}% from the "
                           f"{self.manual_ref['diam_px']:.0f} px that was "
                           f"approved — the baseline or the settings have "
                           f"changed since, so this anchor was verified "
                           f"against a DIFFERENT fit. Re-verify it.")
            elif guard['available']:
                sc += (f" vs auto disc {guard['auto_diam_px']:.0f} px: "
                       f"{guard['diam_pct']:+.1f}% apart in diam, mask "
                       f"area {guard['area_pct']:+.1f}% "
                       + ('⚠' if guard['warn'] else '✓'))
                # The MODAL stays at the historical 3% tier, plus one new
                # case: an anchor REUSED from setup.txt never passed
                # through the dialog's guard, so this is its only
                # chance to be questioned. Firing a modal on every 1%
                # deviation here would nag every honestly-calibrated
                # run (baseline_disc itself agrees with the by-eye
                # measurement only to ~1%); the status ⚠ carries that
                # tier, and the DECISION is made at calibration time.
                if (abs(guard['diam_pct']) > se.ANCHOR_MODAL_DIAM_PCT
                        or (guard['warn']
                            and self.manual_ref.get('reused'))):
                    messagebox.showwarning(
                        "Scale cross-check",
                        "The anchor these results were measured with "
                        "disagrees with a reference the app measured "
                        "independently:\n\n"
                        + '\n'.join('• ' + w for w in guard['warn']
                                    or [f"diameter "
                                        f"{guard['diam_pct']:+.2f}% from "
                                        f"the automatic disc fit"])
                        + ("\n\n(this anchor was REUSED from setup.txt, "
                           "so it never passed the calibration-time "
                           "guard)" if self.manual_ref.get('reused')
                           else "")
                        + f"\n\nRe-check the fitted circle, the optics, "
                          f"and the {self.settings['diam_mm']:g} mm "
                          f"nominal. The MANUAL anchor is what Save "
                          f"uses — every absolute mm² in this run "
                          f"inherits it.")
            else:
                # NOT a neutral parenthetical (review 2026-08-06): with no
                # automatic fit, nothing on this run has ever checked the
                # anchor against anything, and the mask-area test could
                # not run either. Same voice as a trip.
                sc += (" ⚠ NOT cross-checked: no automatic disc fit on "
                       "this run — the anchor is unverified against the "
                       "disc AND against the mask area")
        else:
            # detect_all_sync (tests/headless) can reach here ungated
            sc = (f"; scale ref: baseline disc "
                  f"{self.base_ref['diam_px']:.0f} px"
                  if self.base_ref
                  else "; scale ref: NONE — use 📏 Calibrate / "
                       "re-anchor")
        unread = (f"{len(self.load_fail)} UNREADABLE/FAILED (kept, not "
                  f"re-measured), " if self.load_fail else "")
        self.status.config(
            text=f"detected {len(self.frame_rows)} frames in {took}: "
                 f"{len(self.auto_idx)} auto-accepted, "
                 f"{len(self.auto_rej)} no-change/no-edge, {unread}"
                 f"{len(q)} need review{sc}")
        self.pos = self.frame_rows.index(q[0]) if q else 0
        self._show()

    def _queue_list(self):
        return [i for i in self.frame_rows if i not in self.results]

    def _recount(self):
        areas = {i: r['area_px'] for i, r in self.results.items() if r}
        self.flags, self.advisories = se.breakdown_flags(
            self.run['rows'], areas, self.settings)

    # ---------------- review ----------------
    def _current(self):
        return self.frame_rows[self.pos] if self.frame_rows else None

    def _show(self):
        i = self._current()
        if i is None:
            return
        row = self.run['rows'][i]
        cands = self.cands_all.get(i, [])
        chosen = self.results.get(i)
        trace_now = self.traces.get(i)
        # a staged D that is NOT the committed polygon must never read as
        # the accepted result — the card used to show the corrected
        # outline as 'accepted' while Save wrote the old one (audit
        # 2026-08-05)
        stale_d = (chosen is not None and trace_now is not None
                   and (chosen.get('method') != 'manual-trace'
                        or chosen.get('trace_points')
                        != trace_now.get('trace_points')))
        # info panel
        state = (('FRAME UNREADABLE — not measured (file missing/0-byte)'
                  if self.load_fail.get(i) == 'unreadable'
                  else 'FRAME PROCESSING FAILED — not measured')
                 if i in self.load_fail and i not in self.results else
                 'auto-accepted' if i in self.auto_idx else
                 'accepted' if chosen else
                 'no change vs baseline (auto)' if i in self.auto_rej
                 and i in self.results else
                 'REJECTED' if i in self.results else 'needs review')
        if stale_d:
            state += ' — ⚠ staged D NOT committed (Enter commits it)'
        txt = (f"frame {self.pos+1}/{len(self.frame_rows)}   step "
               f"{row.get('step')} [{row.get('tag')}]\n"
               f"nominal {row.get('nominal_kV')} kV   "
               f"measured {row.get('measured_kV') or '—'} kV   "
               f"{row.get('measured_uA') or '—'} µA\n"
               f"state: {state}")
        if i in self.flags:
            txt += f"\n⚠ {self.flags[i]}"
        elif i in self.advisories:      # elif keeps the fixed info height
            txt += f"\nⓘ {self.advisories[i]}"
        self.info.config(text=txt)
        # radio text is elided to the FIXED panel (#179): the tail (the
        # wrinkle term first) yields before the panel ever resizes
        meas = self._side_font.measure
        for k in range(3):
            if k < len(cands):
                c = cands[k]
                self.cand_radios[k].config(
                    text=elide(f"{CAND_KEYS[k]}: {c['method']}  "
                               f"{c['area_px']:.0f} px²  conf {c['conf']:.2f}"
                               f"  w{c.get('wrinkle', 1):.1f}",
                               RADIO_TEXT_PX, meas),
                    state='normal')
            else:
                self.cand_radios[k].config(text=f"{CAND_KEYS[k]}: —",
                                           state='disabled')
        # row D: the staged manual trace, or the invitation to make one
        trace = self.traces.get(i)
        if trace is not None:
            mmscale = se.mm_per_px(self.results, self.run['rows'],
                                   self.settings,
                                   baseline_ref=self.manual_ref or
                                   self.base_ref)
            mm = (f"  {trace['area_px'] * mmscale * mmscale:.1f} mm²"
                  if mmscale else "")
            staged = ' STAGED≠accepted' if stale_d else ''
            self.cand_radios[TRACE_SLOT].config(
                text=elide(f"D: manual-trace{staged}  "
                           f"{trace['area_px']:.0f} px²{mm}"
                           f"  ({trace['n_points']} pts)",
                           RADIO_TEXT_PX, meas),
                state='normal')
        else:
            self.cand_radios[TRACE_SLOT].config(
                text="D: ✏ trace by hand…", state='normal')
        # selection: just-staged D wins once, else the accepted result,
        # else a pending D on an unreviewed frame, else A
        sel = 0
        if self._select_trace_once:
            self._select_trace_once = False
            sel = TRACE_SLOT
        elif chosen:
            if chosen['method'] == 'manual-trace':
                sel = TRACE_SLOT
            else:
                for k, c in enumerate(cands):
                    if c['method'] == chosen['method']:
                        sel = k
                        break
        elif i not in self.results and trace is not None:
            sel = TRACE_SLOT
        self.cand_var.set(sel)
        q = self._queue_list()
        self.queue_lbl.config(
            text=f"review queue: {len(q)} frame(s) left"
                 + (f"\nbreakdown-flagged: {len(self.flags)}" if self.flags
                    else ""))
        self._draw(i, cands, chosen)

    def _view_size(self):
        """The card's view box: the live canvas size once mapped, else
        the last <Configure> size -- winfo reports 1x1 before layout
        (withdrawn roots in tests land there)."""
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            cw, ch = self._view_wh
        return cw, ch

    def _canvas_resized(self, ev):
        """<Configure> on the canvas (#178): remember the size and
        re-render the card to fill it. Debounced -- the event streams
        continuously during a drag-resize."""
        wh = (ev.width, ev.height)
        if wh == self._view_wh:
            return
        self._view_wh = wh
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(120, self._redraw_card)

    def _redraw_card(self):
        self._resize_job = None
        i = self._current()
        if self.run is None or i is None or i not in self.cands_all:
            # nothing to render: re-centre the empty-canvas hint on the new
            # size instead of leaving it stranded off-centre (`#216`)
            if self._hint:
                self._canvas_hint(self._hint)
            return
        self._draw(i, self.cands_all.get(i, []), self.results.get(i))

    def _render_card(self, i, cands, chosen, view=None):
        """The review card as a PIL image (no Tk): frame + candidate
        outlines + letter tags, contain-fit to `view` (default: the live
        canvas size, #178). Line widths and TAG_PX stay in VIEW pixels
        so legibility is constant at any card size. Split from _draw so
        the rendering is checkable headlessly -- the card is what the
        operator judges."""
        from PIL import Image, ImageDraw
        import numpy as np
        path = se.frame_path(self.run, self.run['rows'][i])
        img = Image.open(path).convert('RGB')
        vw, vh = view or self._view_size()
        scale, w, h, _x, _y = card_geometry(img.width, img.height, vw, vh)
        img = img.resize((w, h))
        dr = ImageDraw.Draw(img)
        entries = list(enumerate(cands))
        trace = self.traces.get(i)
        if trace is not None:              # the staged D outline (#172)
            entries.append((TRACE_SLOT, trace))
        hot = hot_slot(entries, chosen, self.cand_var.get())
        # A committed manual trace with a NEWER D staged: the staged
        # polygon used to be the only one drawn — at the heavy selected
        # weight — while Save wrote the committed one (audit 2026-08-05).
        # Draw the committed outline too (heavy) and thin the staged one.
        stale_d = (chosen is not None and trace is not None
                   and (chosen.get('method') != 'manual-trace'
                        or chosen.get('trace_points')
                        != trace.get('trace_points')))
        committed_trace = (chosen if stale_d
                           and chosen.get('method') == 'manual-trace'
                           else None)
        font = _tag_font()
        for slot, c in entries:
            pts = [(float(x) * scale, float(y) * scale)
                   for x, y in np.asarray(c['contour'])]
            if len(pts) <= 2:
                continue
            # thicker lines, selection visibly heavier (#171/#173)
            wdt = 3 if slot == hot else 2
            if stale_d and slot == TRACE_SLOT and c is trace:
                wdt = 1                    # staged-but-uncommitted: thin
            dr.line(pts + [pts[0]], fill=CAND_COLORS[slot], width=wdt)
            # letter tag: candidate↔outline mapping must not rely on
            # color alone (audit 2026-07-25); large + solid halo (#173)
            tx, ty = max(pts, key=lambda p: p[0])
            tx = min(tx + 6, img.width - TAG_PX - 2)
            ty = min(max(ty - TAG_PX / 2, 0), img.height - TAG_PX - 4)
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if dx or dy:
                        dr.text((tx + dx, ty + dy), CAND_KEYS[slot],
                                fill='black', font=font)
            dr.text((tx, ty), CAND_KEYS[slot], fill=CAND_COLORS[slot],
                    font=font)
        if committed_trace is not None:
            pts = [(float(x) * scale, float(y) * scale)
                   for x, y in np.asarray(committed_trace['contour'])]
            if len(pts) > 2:
                dr.line(pts + [pts[0]], fill=CAND_COLORS[TRACE_SLOT],
                        width=3)
        return img

    def _draw(self, i, cands, chosen):
        from PIL import ImageTk
        vw, vh = self._view_size()
        self._hint = None          # a card is about to occupy the canvas
        try:
            img = self._render_card(i, cands, chosen, view=(vw, vh))
        except OSError:
            # frame missing/undecodable: SAY so on the card — a silently
            # blank canvas next to a physical-sounding state line is how
            # a missing file laundered into a measurement verdict (audit
            # 2026-08-05). Draw bugs stay loud.
            self.canvas.delete('all')
            row = self.run['rows'][i] if self.run else {}
            name = (row.get('frame_file') or '(no file)').strip()
            reason = self.load_fail.get(i)
            if reason and reason != 'unreadable':
                head, detail = 'FRAME PROCESSING FAILED', reason[:90]
            else:
                head = 'FRAME UNREADABLE'
                detail = '(missing / 0-byte / truncated on disk)'
            self.canvas.create_rectangle(0, vh // 2 - 46, vw, vh // 2 + 46,
                                         fill='#7a1f1f', outline='')
            self.canvas.create_text(
                vw // 2, vh // 2, fill='white', justify='center',
                font=('TkDefaultFont', 14, 'bold'),
                text=f"{head}\n{name}\n{detail}")
            return
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete('all')
        # centered on the canvas; the canvas itself is sized by the
        # packer, never by the card (#178)
        self.canvas.create_image(vw // 2, vh // 2, anchor='center',
                                 image=self._photo)

    def _pick_k(self, k):
        i = self._current()
        if i is None or k >= len(self.cands_all.get(i, [])):
            return
        self.cand_var.set(k)
        self._choose_current()

    def _choose_current(self):
        # review inputs are inert while a worker streams: the panel
        # still shows the PREVIOUS pass, so Enter/1/2/3 would accept a
        # candidate the operator has never seen — and _finish_detect
        # would then overwrite the pick as 'auto-accepted' (review
        # 2026-08-05)
        if self._detect_busy:
            return
        i = self._current()
        if i is None:
            return
        k = self.cand_var.get()
        if k == TRACE_SLOT:
            # Accept commits the STAGED trace (#172) -- staging alone
            # (closing the tracer) never touches results
            trace = self.traces.get(i)
            if trace is None:
                return
            chosen = dict(trace)
        else:
            cands = self.cands_all.get(i, [])
            if k >= len(cands):
                return
            chosen = dict(cands[k])
        chosen['chosen_by'] = 'user'
        self.results[i] = chosen
        self.auto_idx.discard(i)
        self._recount()
        self._show()

    def _accept_next(self):
        # ALWAYS (re)accept the selected candidate -- a frame that was
        # rejected earlier must flip back to accepted (bench bug 2026-07-23:
        # a "was it already decided?" guard swallowed the re-accept).
        self._choose_current()
        self._advance()

    def _reject(self):
        if self._detect_busy:          # same guard as _choose_current
            return
        i = self._current()
        if i is None:
            return
        self.results[i] = None
        self.auto_idx.discard(i)
        self._recount()
        self._advance()

    # ---------------- manual trace (#162, candidate D per #172) --------
    def _detect_one(self, i):
        """Detect THIS ONE frame, only so a trace of it has a machine
        candidate to be ground truth against (#162, 2026-08-06).
        -> (candidates, failure reason | None).

        The candidates are tagged SCOPE_FRAME and go into pair_cands, NOT
        cands_all. A single frame is not a small detection pass: it has no
        previous frame, so `prev_method` (the ramp-order hysteresis bonus)
        is absent and se.reconcile_pairs never runs. Measured 2026-08-06
        on synthetic diff-tier scenes: the missing 0.05 bonus is applied
        BEFORE candidates() sorts, so it can also change WHICH candidate
        ranks first -- best area moved 3-9% between prev_method=None and
        prev_method=<tier> where the disc fit refuses, which is exactly
        the event/breakdown frames an operator hand-traces. So:

        - as a PAIRING it is honest and self-consistent (the stored conf
          and the stored contour come from the same candidate) and the
          label's machine.detect_scope says which convention it follows;
        - as a REVIEW RESULT it is not, and keeping it out of cands_all is
          what stops it from reaching the A/B/C radios, an accepted
          active_area_px, or `has_pass` in Advanced -> Apply (which would
          then offer to clear a 'pass' that never existed and wipe the
          staged traces with it -- review 2026-08-06).

        Failures are returned, not raised, and the CALLER caches them: at
        3840x2160 the baseline decode plus detect costs ~1 s, and _trace
        and _trace_staged both ask, so an uncached failure branch made the
        operator wait through it twice per traced frame."""
        try:
            base = self._base_gray()
        except Exception as e:            # a truncated baseline can raise
            print(f"trace: baseline did not load: {e}")
            base = None
        if base is None:
            # the model owns the vocabulary: one place decides what a
            # baseline-less frame is, for the GUI and the report alike
            return [], strc.machine_pairing([], baseline_ok=False)[1]
        try:
            img = se.load_gray(se.frame_path(self.run,
                                             self.run['rows'][i]))
        except Exception as e:
            print(f"trace: frame {i} did not load: {e}")
            img = None
        if img is None:
            return [], strc.UNPAIRED_FRAME_UNREADABLE
        self.status.config(text="detecting this frame on demand "
                                "(so the trace can be paired)…")
        self.root.update_idletasks()
        try:
            cands = se.candidates(base, img, self.settings)
        except Exception as e:
            # same containment as the detect worker: a failed frame must
            # not block the recovery trace -- but the status line must not
            # be left claiming a detect is still running either
            print(f"trace: on-demand detect for frame {i} failed: {e}")
            self.status.config(
                text=f"on-demand detect for this frame FAILED ({e}) — the "
                     f"trace still records the area, but not ground truth")
            return [], strc.UNPAIRED_DETECT_FAILED
        for c in cands:
            c['detect_scope'] = strc.SCOPE_FRAME
        self.status.config(
            text=f"detected {len(cands)} candidate(s) for THIS frame on "
                 f"demand, for the trace's PAIRING only — ▶ Detect Edges "
                 f"is what fills the review pass (its confidence needs "
                 f"the ramp order)")
        return cands, None

    def _machine_pairing(self, i):
        """The machine candidate this frame's trace will be PAIRED with,
        and why there is none when there is none (#162, 2026-08-06).

        Every trace is a ground-truth label, and a label with
        machine:null yields None from sldea_trace.label_iou forever --
        worthless for the conf-vs-IoU curve #162 exists to build. It used
        to happen silently: a run opened WITHOUT --auto has never
        detected anything, cands_all is empty, and the label went out
        unpaired with no complaint (four of them in the 2026-07/08 batch
        control round; the operator's work had to be redone).

        So the pairing is CREATED rather than reported, by detecting the
        one frame (_detect_one, cached per frame including its failures).
        A real pass ALWAYS wins over an on-demand result for the same
        frame: its conf carries the ramp hysteresis and the same-kV
        reconciliation, which is the convention the curve is read in.

        Review state is never touched here -- not results, not
        auto_idx/auto_rej, not the scale gate, not cands_all -- so an
        on-demand detect can neither accept, reject, nor invalidate
        anything."""
        if i in self.cands_all:           # a real pass covered this frame
            cands = self.cands_all[i]
            if not cands and i in self.load_fail:
                # a file- or code-level failure is not 'the detector found
                # nothing' — the distinction survives into the label for
                # the same reason it survives into the review queue
                return None, (strc.UNPAIRED_FRAME_UNREADABLE
                              if self.load_fail[i] == 'unreadable'
                              else strc.UNPAIRED_DETECT_FAILED)
            return strc.machine_pairing(cands)
        if i not in self.pair_cands:
            if self._detect_busy:
                # unreachable from _trace (inert while a worker streams);
                # detecting here anyway would put a second thread in
                # sldea_edge's baseline caches, and the pass itself is
                # about to supply the pairing
                return None, strc.UNPAIRED_NOT_DETECTED
            self.pair_cands[i] = self._detect_one(i)
        cands, fail = self.pair_cands[i]
        if fail:
            return None, fail
        return strc.machine_pairing(cands)

    def trace_overlay_cands(self, i):
        """What a tracer may DRAW as 'candidates' for frame i: the review
        pass's list, else the on-demand pairing detected for this trace
        (#162). Drawing is all it is for -- picking a machine candidate
        goes through cands_all, which an on-demand detect never fills."""
        cands = self.cands_all.get(i)
        if cands is None:
            cands = self.pair_cands.get(i, ([], None))[0]
        return [c for c in cands if c.get('contour') is not None]

    def _trace(self):
        """Open the manual tracer: the recovery path when every candidate
        is rejected, and the labeling instrument for the conf-vs-IoU
        calibration. Allowed even when a candidate exists -- correcting a
        near-miss is a valuable label, not a rejection. The closed trace
        is STAGED as candidate D (row D + drawn on the card); Accept
        commits it like any other candidate (#172). Re-opening D edits
        the pending polygon rather than starting over."""
        if self._detect_busy:          # same guard as _choose_current
            return
        i = self._current()
        if self.run is None or i is None:
            messagebox.showinfo("Trace", "Pick a run first")
            return
        path = se.frame_path(self.run, self.run['rows'][i])
        if not path or not os.path.exists(path):
            messagebox.showinfo("Trace", "This row has no frame on disk.")
            self._show()               # the D radio may have grabbed sel
            return
        # the pairing is settled BEFORE the operator spends a minute
        # tracing: either it exists (detected on demand if need be), or
        # they are told plainly that this trace cannot be ground truth,
        # with a chance to repair the cause first (#162, 2026-08-06)
        _mach, why = self._machine_pairing(i)
        if why:
            outlook = (f"Tracing anyway still RECOVERS the measurement — "
                       f"the polygon, its area and the label are saved as "
                       f"usual, and the label is marked '{why}' so the "
                       f"calibration pass reports it instead of silently "
                       f"ignoring it.")
            if why == strc.UNPAIRED_FRAME_UNREADABLE:
                # the tracer decodes the SAME file (with PIL, not cv2), so
                # promising a recovery here is a promise this branch
                # cannot keep — it used to raise straight out of
                # Image.open into a console nobody watches (review
                # 2026-08-06)
                outlook = ("This frame did not decode for detection, so "
                           "the tracer may not be able to open it either. "
                           "If it does open, the trace is still saved as "
                           "a recovery measurement.")
            if not messagebox.askokcancel(
                    "Trace with NO machine candidate",
                    f"This frame has no machine candidate, so a trace of "
                    f"it CANNOT serve as ground truth: the "
                    f"machine-vs-operator IoU and the definitional-offset "
                    f"gate are not computable from it, ever (#162).\n\n"
                    f"{strc.unpaired_message(why)}\n\n{outlook}\n\n"
                    f"Trace anyway?"):
                self._show()           # the D radio may have grabbed sel
                return
        scale = se.mm_per_px(self.results, self.run['rows'], self.settings,
                             baseline_ref=self.manual_ref or self.base_ref)
        trace = self.traces.get(i) or {}
        try:
            TraceWindow(self, i, path, mm_per_px=scale,
                        seed=trace.get('trace_points'),
                        seed_snapped=bool(trace.get('snapped')),
                        unpaired_ack=why)
        except Exception as e:
            # a frame that EXISTS but does not decode (truncated, 0-byte)
            # raised out of PIL.Image.open with no dialog at all: an
            # unhandled traceback where the operator expected a tracer
            # (review 2026-08-06)
            print(f"trace: tracer did not open for frame {i}: {e}")
            messagebox.showerror(
                "Trace", f"This frame did not open for tracing:\n{e}\n\n"
                         f"Nothing was staged and no label was written.")
            self._show()

    def _trace_staged(self, i, points, meta):
        """TraceWindow Done -> the polygon is staged as candidate D and
        the ground-truth label is appended to edge_labels.json. Staging
        does NOT touch results -- Accept commits (#172). The label
        appends HERE, at Done, so a completed trace is never lost even
        if it is not accepted; a re-trace appends another record (repeat
        labels are how operator repeatability was measured). Tracing
        never touches data.csv/setup.txt -- the committed result flows
        through the normal Save path."""
        meta = dict(meta)
        # what the operator was told at tracer-open time (#162): a
        # pairing gap they have NOT seen gets stated here instead of
        # only landing in the sidecar
        ack = meta.pop('unpaired_ack', None)
        poly = np.asarray(points, np.float64)
        area = strc.polygon_area(poly)
        cx, cy = strc.polygon_centroid(poly)
        wrinkle = None
        gray = se.load_gray(se.frame_path(self.run, self.run['rows'][i]))
        try:
            base = self._base_gray()
            # se.wrinkle_index, NOT the raw-frame ratio: |Laplacian| is
            # linear in gain, and the un-normalized frame gave traced
            # rows an index 20-30% off at the P3 campaign's photometric
            # gain — the saved column silently mixed two normalizations
            # and P3_5 lost its wrinkle-mode onset to it (audit
            # 2026-08-05)
            wrinkle = se.wrinkle_index(base, gray, poly, self.settings)
        except Exception:
            wrinkle = None
        self.traces[i] = {
            'method': 'manual-trace', 'conf': 1.0, 'chosen_by': 'user',
            'area_px': float(area),
            'diam_px': strc.equivalent_diam(area),
            'cx': float(cx), 'cy': float(cy),
            'contour': poly.astype(np.int32), 'solidity': 1.0,
            'spread_pct': 0.0, 'ci85_pct': None, 'wrinkle': wrinkle,
            'n_points': len(poly),
            # full-precision points so re-opening D edits, not re-clicks
            'trace_points': [(float(x), float(y)) for x, y in poly],
            'snapped': bool(meta.get('snapped'))}
        # every trace is a label, stored with the machine's best candidate
        # at trace time so IoU is computable offline (#162). The pairing
        # is resolved through _machine_pairing, which DETECTS this frame
        # if nothing ever did — label_record refuses an unexplained
        # machine:null, so no path can write a dead label by omission.
        mach, why = self._machine_pairing(i)
        shape = gray.shape if gray is not None else (0, 0)
        self._select_trace_once = True
        try:
            # label_record inside the try on purpose: its refusal is a
            # ValueError, and an unhandled one here would print to a
            # console nobody is watching and lose the label silently --
            # the exact shape of failure this gate exists to end
            rec = strc.label_record(i, self.run['rows'][i], poly, shape,
                                    machine=mach, unpaired=why, **meta)
            strc.append_label(self.rundir, rec)
            n = len(strc.load_labels(self.rundir))
            self.status.config(
                text=f"trace staged as candidate D ({area:.0f} px², "
                     f"{len(poly)} points) — Accept (Enter) commits; "
                     f"label {n} in {strc.LABELS_NAME}"
                     + (f"  ⚠ UNPAIRED ({why}): recovery only, NOT usable "
                        f"as ground truth" if why else ""))
            if why and why != ack:
                # a label reached the sidecar without the operator having
                # seen the tracer-open warning (a caller that bypassed
                # _trace, or candidates that went away mid-trace): say it
                # now, rather than leaving it findable only offline
                messagebox.showwarning(
                    "Trace label is NOT ground truth",
                    f"This trace was saved as a recovery measurement, "
                    f"but it has no machine candidate to pair with, so no "
                    f"IoU can ever be computed from it (#162).\n\n"
                    f"{strc.unpaired_message(why)}")
        except (OSError, ValueError) as e:
            messagebox.showerror(
                "Trace label", f"The trace is staged as candidate D, but "
                f"appending the label sidecar failed:\n\n{e}")
        self._show()

    def _advance(self):
        """After accept/reject: jump to the next unreviewed frame (first one
        after the current position, wrapping), else just the next frame."""
        q = self._queue_list()
        if q:
            i_cur = self._current()
            later = [i for i in q if i > (i_cur if i_cur is not None else -1)]
            self.pos = self.frame_rows.index(later[0] if later else q[0])
            self._show()
        elif self.pos < len(self.frame_rows) - 1:
            self._step(+1)
        else:
            self._show()
            self.status.config(text="review complete — Save to data.csv "
                                    "when ready")

    def _step(self, d):
        if not self.frame_rows:
            return
        self.pos = max(0, min(len(self.frame_rows) - 1, self.pos + d))
        self._show()

    def goto_row(self, row):
        """Show the frame for DATA ROW `row` (`#274`).

        -> the row actually landed on, or None when there is nothing to
        land on.

        THE MAPPING IS `frame_rows` — the rows that HAVE a frame file, in
        CSV order — which is the same rule `#255` documented when the
        trace report's 0-based rows met this window's 1-based frames and
        mis-targeted a trace by one. `frame_rows.index(row) + 1` is the
        frame number on screen; nothing else is.

        A row with NO frame of its own resolves to the nearest one and
        the status bar says which. The plot window can legitimately point
        at a snapshot that was never photographed — currents and powers
        are drawn per snapshot, and a run captured with fewer frames than
        snapshots has plenty of them — and both alternatives are worse:
        refusing throws away a click that meant something, and silently
        landing on frame 1 is a wrong answer that looks like a right one.
        """
        if not self.run or not self.frame_rows:
            self.status.config(
                text=f"--goto {row}: no frames in this run to show")
            return None
        if row in self.frame_rows:
            landed, note = row, ''
        else:
            # ties go to the LOWER row: deterministic, and the earlier
            # frame is the one before the event rather than after it
            landed = min(self.frame_rows, key=lambda i: (abs(i - row), i))
            note = (f" — data row {row} has no frame of its own, "
                    f"nearest is row {landed}")
        self.pos = self.frame_rows.index(landed)
        self._show()
        self.status.config(
            text=f"opened at frame {self.pos + 1}/{len(self.frame_rows)} "
                 f"for data row {row}{note}")
        return landed

    def _next_unreviewed(self):
        q = self._queue_list()
        if q:
            self.pos = self.frame_rows.index(q[0])
            self._show()
        else:
            self._show()
            self.status.config(text="review complete — Save to data.csv when "
                                    "ready")

    # ---------------- save ----------------
    def save(self):
        if not self.run:
            return
        if self.manual_ref is None:
            # the scale gate holds at Save too — no entry point may write
            # mm² off an unverified anchor (operator decision 2026-08-05)
            messagebox.showinfo(
                "Save", "Scale gate: 📏 Calibrate / re-anchor this "
                        "run's resting disc "
                        "first — the manual px→mm anchor is required "
                        "before results are written.")
            return
        q = self._queue_list()
        accepted = sum(1 for r in self.results.values() if r)
        rejected = sum(1 for r in self.results.values() if r is None)
        n_unread = sum(1 for i in q if i in self.load_fail)
        # unreviewed rows KEEP their previous pass's px measurement,
        # re-scaled to this session's anchor (one scale per save, audit
        # 2026-08-05) — the dialog used to claim they were 'left blank'
        n_kept = sum(
            1 for i in q
            if (self.run['rows'][i].get('active_area_px') or '').strip())
        unrev = (f"unreviewed: {len(q)}"
                 + (f" ({n_kept} keep the previous pass's px, re-scaled "
                    f"to THIS anchor)" if n_kept else " (left blank)")
                 + (f"\n  incl. {n_unread} UNREADABLE frame(s) — kept, "
                    f"not re-measured" if n_unread else ""))
        # ... and SAY BY HOW MUCH (#215). "re-scaled to THIS anchor" is
        # true but abstract; an operator who re-reviewed one frame needs
        # the number, because the whole mm² column moves by it.
        rescale, prev = None, None
        try:
            prev = se.load_scale_anchor(self.rundir)
            if prev and self.manual_ref:
                rescale = se.rescale_pct(prev['diam_px'],
                                         self.manual_ref['diam_px'])
        except OSError:
            rescale, prev = None, None
        if n_kept and rescale is not None and abs(rescale) >= 0.005:
            unrev += (f"\n  ⚠ this anchor differs from the recorded one "
                      f"({prev['diam_px']:.1f} → "
                      f"{self.manual_ref['diam_px']:.1f} px): EVERY "
                      f"re-derived mm² moves {rescale:+.2f}%, including "
                      f"rows you did not re-review.")
        elif n_kept and not prev and self.manual_ref:
            # The PRE-GATE runs (P3_6_2.5mL_20260729, DOT_P3_1_20260729):
            # px rows, no anchor block, so there is no recorded diameter
            # to quote against — and they are precisely the runs whose
            # whole mm² column is about to hang on a hand-fitted anchor
            # for the first time. Quote it against the automatic fit,
            # which is the scale a pre-gate save derived them at; with no
            # automatic fit either, say plainly that there is no number
            # (review 2026-08-06, minor 6). It used to show nothing.
            auto_px = (self.base_ref or {}).get('diam_px')
            pct = se.rescale_pct(auto_px, self.manual_ref['diam_px'])
            if pct is not None:
                unrev += (f"\n  ⚠ NO anchor is on record for this run (a "
                          f"pre-gate save): those mm² were derived at the "
                          f"AUTOMATIC disc fit's scale ({auto_px:.1f} px), "
                          f"so this Save moves every one of them "
                          f"{pct:+.2f}% — the first time this column hangs "
                          f"on a hand-fitted anchor "
                          f"({self.manual_ref['diam_px']:.1f} px).")
            else:
                unrev += (f"\n  ⚠ NO anchor is on record for this run AND "
                          f"there is no automatic fit, so there is no "
                          f"percentage to quote: the WHOLE mm² column is "
                          f"derived fresh at this anchor "
                          f"({self.manual_ref['diam_px']:.1f} px), "
                          f"including rows you did not re-review.")
        n_bd = 0
        if self.flags:
            start = min(self.flags)
            n_bd = sum(1 for i in self.frame_rows if i >= start)
        # retracted brands rename BACK — the dialog must say so, not
        # only announce the branding direction (review 2026-08-05)
        first = min(self.flags) if self.flags else None
        n_unbrand = sum(
            1 for i, row in enumerate(self.run['rows'])
            if '_BREAKDOWN' in (row.get('frame_file') or '')
            and (first is None or i < first))
        msg = (f"Write results into this run's data.csv?\n\n"
               f"accepted: {accepted}  (auto {len(self.auto_idx)})\n"
               f"rejected: {rejected}\n"
               f"{unrev}\n"
               f"breakdown-flagged: {len(self.flags)}"
               + (f"  (+{len(self.advisories)} advisory note(s), no renames)"
                  if self.advisories else "") + "\n"
               + (f"\n⚠ {n_bd} frame file(s) from the first breakdown onward "
                  f"will be RENAMED with a _BREAKDOWN suffix (kept, never "
                  f"deleted — usable later as ML training data).\n"
                  if n_bd else "\n")
               + (f"⚠ {n_unbrand} file(s) carry a breakdown brand the "
                  f"current flags RETRACT — renamed back (un-branded), "
                  f"stale notes cleaned.\n" if n_unbrand else "")
               + "A backup is kept as data.csv.bak; an area-vs-voltage plot "
                 "and outline overlays are saved beside it.")
        if not messagebox.askyesno("Save results", msg):
            return
        ref = self.manual_ref or self.base_ref
        scale = se.mm_per_px(self.results, self.run['rows'], self.settings,
                             baseline_ref=ref)
        src = se.scale_source(self.results, self.run['rows'],
                              baseline_ref=ref)
        onset, annos = se.wrinkle_onset(self.run['rows'], self.results,
                                        self.settings)
        # physics the per-frame detector cannot see: pre/post pairs must
        # agree, and the area must not dip while the voltage rises
        for i, note in se.ramp_consistency(self.run['rows'], self.results,
                                           self.settings).items():
            annos[i] = (annos[i] + '; ' + note) if i in annos else note
        # advisory breakdown notes ride the anno channel: written to the
        # CSV, never renaming frames or seeding post-breakdown branding
        for i, note in self.advisories.items():
            annos[i] = (annos[i] + '; ' + note) if i in annos else note
        # a not-measured frame's row records WHY — a file- or code-level
        # fact, never a physical verdict (audit 2026-08-05). ASCII-safe
        # in the CSV.
        for i in q:
            if i in self.load_fail:
                note = ('frame unreadable - kept, not re-measured'
                        if self.load_fail[i] == 'unreadable' else
                        'frame processing failed - kept, not re-measured')
                annos[i] = (annos[i] + '; ' + note) if i in annos else note
        if 'wrinkle_idx' not in self.run['columns']:
            # older runs predate the column; slot it in before notes
            cols = self.run['columns']
            cols.insert(cols.index('notes') if 'notes' in cols else len(cols),
                        'wrinkle_idx')
        for row in self.run['rows']:
            row.setdefault('wrinkle_idx', '')
        # The destructive phase must NEVER fail silently, and its ORDER
        # is load-bearing (audit 2026-08-05): data.csv commits FIRST
        # (backup + atomic tmp+replace inside write_back), the frame
        # renames run after. A failure before the commit leaves the run
        # byte-identical on disk with zero files renamed; a failure
        # during the renames leaves a saved CSV whose links the next
        # Save's symmetric heal repairs. The old order renamed first, so
        # a full disk left renamed frames, a stale CSV and a dialog
        # promising a .bak that was never made.
        csv_path = self.run.get('csv_path') or ''
        try:
            se.apply_results(self.run['rows'], self.results, scale,
                             self.flags, annos)
            plan = se.plan_breakdown_marks(self.run, self.flags)
            se.write_back(self.rundir, self.run)
        except Exception as e:
            has_bak = csv_path and os.path.exists(csv_path + '.bak')
            messagebox.showerror(
                "Save FAILED",
                f"Writing results failed:\n\n{e}\n\nYour review is still "
                f"in memory — fix the problem (share up? disk full?) and "
                f"Save again. No frame files were renamed."
                + (f"\nA pre-save backup is at data.csv.bak."
                   if has_bak else ""))
            return
        renamed, rn_errors = se.apply_rename_plan(plan)
        if rn_errors:
            messagebox.showwarning(
                "Save: renames incomplete",
                f"data.csv is saved, but {len(rn_errors)} frame "
                f"rename(s) failed:\n\n" + '\n'.join(rn_errors[:4])
                + ('\n…' if len(rn_errors) > 4 else '')
                + "\n\nSave again once the files are reachable — the "
                  "branding self-heals in either direction.")
        # persist the anchor that produced every mm² in this save — the
        # run's absolute scale used to be a pair of clicks recorded
        # nowhere (audit 2026-08-05); the 📏 dialog offers it for reuse.
        #
        # Built by _anchor_record, which the scale-only re-anchor writes
        # through too (`#215`): one builder, so a field added for one path
        # can never be silently missing from the other. A Save deliberately
        # writes NO `reanchor` marker — this run WAS reviewed, and the
        # marker's whole job is to distinguish the two.
        try:
            se.save_scale_anchor(self.rundir,
                                 self._anchor_record(self.manual_ref, scale))
        except OSError as e:
            self.status.config(
                text=f"saved, but recording the scale anchor in "
                     f"setup.txt failed: {e}")
        # detect→Save, the whole round trip, said in the status line where
        # it always was. Save no longer STOPS the toolbar clock (`#237`):
        # that clock is now the session, a session outlives a Save (the
        # batch cockpit saves one run and moves to the next), and the
        # frozen `detect:` readout above it is the number that used to be
        # destroyed. The old `done in …` said detect→Save in a widget that
        # then sat stale through every following run.
        took = fmt_dur(time.time() - self._t0) if self._t0 else '?'
        try:
            self._save_plot(scale)
            self._save_overlays()
        except Exception as e:
            self.status.config(text=f"saved CSV; plot/overlays failed: {e}")
            return
        scale_txt = (f"scale {scale:.5f} mm/px [{src}]" if scale
                     else "no mm scale — use 📏 Calibrate / "
                          "re-anchor")
        bd_txt = f", {renamed} frame(s) renamed" if renamed else ""
        self.status.config(
            text=f"saved in {took} — data.csv updated ({scale_txt}){bd_txt}")

    def _save_plot(self, scale):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        xs, ys, tags = [], [], []
        for i, r in self.results.items():
            if not r:
                continue
            row = self.run['rows'][i]
            try:
                kv = float(row.get('nominal_kV') or '')
            except ValueError:
                continue
            area = r['area_px'] * (scale * scale) if scale else r['area_px']
            xs.append(kv)
            ys.append(area)
            tags.append(row.get('tag'))
        if not xs:
            return
        fig, ax = plt.subplots(figsize=(8, 5))
        # prefix match keeps old runs (tags 'post'/'pre') plottable alongside
        # new ones ('post-ramp'/'pre-ramp')
        for pref, mk, label in (('post', 'o', 'post-ramp'),
                                ('pre', 's', 'pre-ramp'),
                                ('baseline', '^', 'baseline')):
            px = [x for x, t in zip(xs, tags) if (t or '').startswith(pref)]
            py = [y for y, t in zip(ys, tags) if (t or '').startswith(pref)]
            if px:
                ax.plot(px, py, mk, label=label, alpha=0.8)
        ax.set_xlabel('nominal voltage (kV)')
        ax.set_ylabel('active area (mm²)' if scale else 'active area (px²)')
        ax.set_title(os.path.basename(self.rundir) + ' — active area vs voltage')
        ax.grid(alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(self.rundir, 'area_vs_voltage.png'), dpi=110)
        plt.close(fig)

    def _save_overlays(self):
        import cv2
        import numpy as np
        outdir = os.path.join(self.rundir, 'overlays')
        os.makedirs(outdir, exist_ok=True)
        for i, r in self.results.items():
            if not r:
                continue
            row = self.run['rows'][i]
            path = se.frame_path(self.run, row)
            img = cv2.imread(path)
            if img is None:
                continue
            cv2.polylines(img, [np.asarray(r['contour'], np.int32)], True,
                          (80, 200, 0), 2)
            cv2.imwrite(os.path.join(outdir, os.path.basename(path)), img)

    def _diam_recorded(self):
        """True when this run's setup.txt carries the capture-side
        'DEA nominal diameter' line (written from the SLDEA tab's
        'DEA active area diam (mm)' field) — if not, diam_mm is only the settings
        default and the gate dialog says so.

        utf-8 + errors='replace', like load_settings: the bare locale-
        codec open raised UnicodeDecodeError (a ValueError, NOT an
        OSError) on any hand-annotated non-ASCII byte, mid-dialog-build
        — which published a half-built singleton and silently bricked
        Detect for the rest of the session (audit 2026-08-05)."""
        try:
            with open(os.path.join(self.rundir, 'setup.txt'),
                      encoding='utf-8', errors='replace') as f:
                return 'DEA nominal diameter:' in f.read()
        except (OSError, TypeError, UnicodeError):
            return False

    def _anchor_frame(self):
        """-> (PIL image, is_baseline, tried, frame_name) — the first
        READABLE frame to calibrate on: baseline-tagged rows first, then
        the rest of the ramp. A baseline PNG can be listed in the CSV
        yet be 0-byte or truncated on disk (interrupted capture, e.g.
        the 2026-08-04 disk-full incident) — the gate must fall back,
        not crash, or the whole run becomes permanently unprocessable
        (review 2026-08-05). `tried` collects the unreadable names for
        the error dialog; `frame_name` feeds the anchor's provenance
        record."""
        from PIL import Image
        ordered = ([i for i in self.frame_rows
                    if self.run['rows'][i].get('tag') == 'baseline']
                   + [i for i in self.frame_rows
                      if self.run['rows'][i].get('tag') != 'baseline'])
        tried = []
        for i in ordered:
            row = self.run['rows'][i]
            path = se.frame_path(self.run, row)
            if not path or not os.path.exists(path):
                tried.append(os.path.basename(path or '(no file)'))
                continue
            try:
                img = Image.open(path).convert('RGB')
            except Exception as e:          # 0-byte, truncated, not-a-PNG
                tried.append(f"{os.path.basename(path)} ({e})")
                continue
            return (img, row.get('tag') == 'baseline', tried,
                    os.path.basename(path))
        return None, False, tried, ''

    def _gate_status(self):
        self.status.config(text="Detect is gated on the scale "
                                "calibration — 📏 Calibrate / "
                                "re-anchor to proceed")

    def _review_dirty(self):
        """The UNSAVED review work in memory, named — or [].

        Shared by the folded 📏 action and the re-anchor's own refusal,
        because they are one question asked twice: is there a second writer
        for this run's mm² column right now?"""
        return [name for name, n in (('reviewed rows', len(self.results)),
                                     ('staged trace(s)', len(self.traces)),
                                     ('breakdown flag(s)', len(self.flags)),
                                     ('advisory note(s)',
                                      len(self.advisories))) if n]

    def _scale_intent(self):
        """WHICH of the two folded scale actions this run's state calls for,
        as {'intent', 'why', 'dirty', 'n_px_rows'} (`#215`, 2026-08-06 late).

        One 📏 button, because the two it replaces opened the same dialog and
        the operator found having two confusing. The behaviour follows the
        RUN, not the button:

        - **an open review pass → CALIBRATE.** This is the `[critical]`
          mixed-scale bug's own shape: committing a scale to data.csv while a
          half-finished pass sits in `self.results` puts this write and the
          later Save's write on either side of one mm² column
          (SLDEA_HANDOFF 2026-08-05). The old re-anchor button REFUSED here,
          and folding must not turn a refusal into a silent commit — so the
          refusal survives as a routing rule, and `_reanchor_scale` still
          refuses independently, fail-closed, in case this ever disagrees.
        - **a detect worker in flight → CALIBRATE**, for the same reason
          re-anchoring refused: nothing may rewrite data.csv under a running
          pass.
        - **nothing measured yet → CALIBRATE.** There are no px to
          re-derive; this run needs the anchor Detect is gated on.
        - **otherwise → RE-ANCHOR.** The run is saved, no pass is open, and
          rows carry px: correcting the scale is a scale-only rewrite and
          costs no re-review.

        Computed at click time and never cached, so the toolbar button's
        label cannot go stale about which one it will do."""
        dirty = self._review_dirty()
        n_px = self._px_rows()
        out = {'dirty': dirty, 'n_px_rows': n_px,
               'intent': SCALE_INTENT_CALIBRATE}
        if self._detect_busy:
            out['why'] = ("a detection pass is running, so nothing may be "
                          "written to data.csv — this only sets the anchor "
                          "the next Save will apply")
        elif dirty:
            out['why'] = ("an UNSAVED review pass is in memory ("
                          + ', '.join(dirty) + "), so this calibrates THAT "
                          "pass and is applied when you Save it. Committing "
                          "a scale now would put two writers on one mm² "
                          "column")
        elif not n_px:
            out['why'] = ("no row in this run carries a px measurement yet, "
                          "so there is nothing to re-derive — this sets the "
                          "anchor Detect and Save are gated on")
        else:
            out['intent'] = SCALE_INTENT_REANCHOR
            out['why'] = (f"{n_px} row(s) already carry a px measurement and "
                          f"no review pass is open, so this corrects the "
                          f"SAVED run's scale and commits immediately")
        return out

    def _scale_action(self):
        """The ONE 📏 toolbar entry point (`#215`, operator 2026-08-06 late).

        Dispatches on `_scale_intent`; both branches drive the same
        calibration dialog, and each tells the operator in the dialog itself
        which of the two it is."""
        if not self.run:
            messagebox.showinfo("Scale", "Pick a run first")
            return
        if self._cal_win is not None and self._cal_win.winfo_exists():
            # the dialog is a singleton: front the live one rather than
            # stacking a second wait chain behind it (#176)
            self._cal_win.lift()
            self._cal_win.focus_set()
            return
        if self._scale_intent()['intent'] == SCALE_INTENT_REANCHOR:
            self._reanchor_scale()
        else:
            self._calibrate_scale()

    def _px_rows(self):
        """How many rows already carry a px measurement — i.e. how many
        absolute mm² a new anchor would REWRITE at the next Save."""
        try:
            return sum(1 for row in self.run['rows']
                       if (row.get('active_area_px') or '').strip())
        except Exception:
            return 0

    def _auto_disc(self):
        """The automatic baseline disc fit, for the anchor guard — or
        None. Cached inside se.baseline_disc, so asking here also warms
        the cache detection is about to use. Never allowed to raise out
        of the dialog: a cv2 failure must cost the CROSS-CHECK, not the
        calibration (the gate is fail-closed by construction, audit
        2026-08-05)."""
        try:
            base = self._base_gray()
            if base is None:
                return None
            return se.baseline_disc(base, self.settings)
        except Exception as e:
            print(f"calibrate: automatic disc cross-check failed: {e}")
            return None

    def _auto_disc_refusal(self):
        """WHY the automatic fit refused this baseline, in the fitter's own
        words — or None.

        The verify mode falls through to a hand measurement whenever the fit is
        unavailable, and an operator being told to do the slower, measurably
        worse job deserves to know which gate said no: 'the arc covers only
        87°' sends them to move whatever is lying across the frame, while
        'the diameter is outside the plausible range' sends them to the
        camera zoom and diam_mm. Never raises, for the same reason
        `_auto_disc` does not."""
        try:
            base = self._base_gray()
            if base is None:
                return ('the baseline frame will not load, so the fit was '
                        'never attempted')
            return se.baseline_disc_refusal(base, self.settings)
        except Exception as e:
            print(f"calibrate: could not read the fit's refusal: {e}")
            return None

    def _calibrate_scale(self, then_detect=False, mode=None, intent=None):
        """The px→mm SCALE GATE — THREE METHODS (operator decision
        2026-08-05, `#215` 2026-08-06). Detect and Save both require it per
        run, and whatever it produces overrides EVERY automatic reference at
        Save. With then_detect, detection chains automatically once
        calibration finishes (Detect's gate path and --auto). `mode`
        pre-selects a method; **None opens on `se.cal_open_mode(the fit)`** —
        `verify` when there is an automatic fit to verify, `circle` when
        there is not.

        **THE LABELS ARE A / B / C AND THE RECORD HOLDS NAMES.** The letters
        were renumbered on 2026-08-06 late at the operator's request — A is
        now the verify mode, where the gate opens, so the first letter and
        the default are the same thing — and because the old letters are on
        disk in `cal_mode:` and in `mode=` log lines, nothing writes a letter
        any more. `se.CAL_MODE_LABELS` is presentation; `se.cal_mode_read`
        is the rule for a letter found in an existing record.

        `intent` is which of the two folded actions this dialog serves —
        SCALE_INTENT_CALIBRATE (held for the next Save; nothing written) or
        SCALE_INTENT_REANCHOR (committed to data.csv as soon as it is
        confirmed). It changes NOTHING about the measurement; it changes what
        the window is titled, what the primary button says, and what the
        confirmation asks, because one of the two writes immediately and an
        operator must not have to remember which. Defaults to CALIBRATE —
        the Detect gate path and `--auto` never commit.

        **THE `verify` MODE (label A) — verify the automatic fit** (where the
        gate opens, and the one that is not a hand measurement).
        `se.baseline_disc` measured the disc; the operator judges whether it
        is right. Drawn with a 1 px dashed stroke over a contrast-stretched
        DISPLAY copy, framed on the circle, under **two short lines** and
        nothing else — the value and two quality numbers — plus a warning
        line if the stretch could not be computed and a consequence line only
        when there is a consequence (verify_evidence; the operator's verdict
        on the 13-line version was that it was "wayyyyy too busy with text
        and unnecessary garbage", and on the 3-line version that the standing
        stretch/no-cross-check sentence was unnecessary — it lives in the
        run's `guard:` record instead). Actions: ✔ Accept (primary and Tk's
        default button, but <Return> cannot reach it) and Cancel. The
        hand-measurement route is the RADIO ROW, which is the only route
        since the ✎ Measure by hand instead button was dropped as a second
        way to do one thing. Recorded with method `auto-verified` so an audit
        can tell it from a hand measurement — with every number the screen
        no longer shows.

        Why it exists, measured (`#215` comment, 2026-08-06 evening): on
        P3_2's baseline the automatic fit (577.08 px, circ 0.999, conf
        0.871, residual 2.3 px, 204 edge points) beat ALL ELEVEN hand
        calibrations on accuracy and nine of eleven on precision. The ink
        step is a ~20-gray ramp over ~60 px of radius — a gradient wider
        than the stroke an operator draws with — so there is no gesture that
        fixes the human side, and the point a human picks is the outer toe
        (§1.3, +2.6 % diameter). It is withdrawn when the fit refuses
        (as on P3_7_2.3mL_20260729) or when the frame being calibrated on is
        not the baseline the fit ran on; the gate then falls through to the
        hand measurement and states the fitter's own reason.

        The two HAND methods below are unchanged, and are what the verify mode
        falls back to. They are also still the only source of the
        operator-repeatability figure: a verified anchor contributes none.

        **THE `circle` MODE (label B) — fit a circle** (the incumbent,
        behaviour unchanged):
        drag to move, 8 handles to resize about the centre, CAL_ROUNDS
        rounds, mean of the fitted diameters. Optionally with a thin or
        dashed stroke instead of the 3 px solid one — the cheap third arm
        of the comparison (cal_stroke_spec).

        **THE `twopoint` MODE (label C) — two-point diameter, N rounds,
        randomly rotated**: click two roughly-opposite points on the disc
        edge, N times (default 5), with the DISPLAY ROTATED BY A RANDOM
        ANGLE between rounds, and the mean of the N diameters is the anchor.
        **The second click BANKS the round and advances to the next one** —
        no Continue press (operator 2026-08-06 late). The LAST round still
        needs the ✔ Finish button, because auto-advancing into the accept
        path is how a stray click would answer the gates that follow it, and
        a misclick anywhere is undone with ◀ Back / Backspace, which steps
        one round back and re-randomises it. Measured in ORIGINAL image
        coordinates — the clicks are mapped back through the inverse
        rotation (unrotate_point) — and the markers are a hollow ring plus
        a gapped crosshair that leave the judged pixels visible.

        Why the two-point mode exists, from real measurements (`#215`
        comment, 2026-08-06): the operator drove the circle six times on a
        scratch copy
        of P3_2_2.5mL_20260728 and its 3-round ranges were 1.94, 2.09,
        1.62, 1.81, 1.44 % plus one under 1 % — per-fit sigma ~ 1.05 % of
        diameter, so a 3-round mean SE of 0.61 % diameter / 1.21 % area
        against §2.1's ~0.4 % / ~0.8 % budget. The circle would need ~7
        rounds to reach budget. The operator's diagnosis: "the bright green
        circle occludes the edges". The two-point mode's target is
        sigma < 0.9 %, at which 5 rounds lands on budget.

        Why a circle and not the two clicks it replaces: judging
        "exactly opposite" on a disc is something humans do badly, and
        run P3_2_2.5mL_20260728 is the measured proof — its two-click
        anchor landed 2.28% off the automatic fit, which put every
        absolute mm² in that run 4.42% low, and nothing warned because
        2.28% sat inside the old 3% cross-check. A circle is judged
        against the WHOLE visible boundary.

        The circle's rounds each RESPAWN at a randomized position and size
        inside the central ROI (spawn_circle); the two-point mode's each rotate
        the display to a fresh stratified angle (rotation_angles). Either way
        the point is the same: n nudges of one fit are n correlated fits and
        their scatter flatters the operator. The scatter across rounds is kept
        — it is the only measurement of operator repeatability this project
        has, and now the only figure that can decide the A/B comparison
        (per-fit sigma, which survives a different n).

        And the rounds are kept BLIND (review 2026-08-06): the header used
        to render "accepted so far: N px" while the live readout rendered
        the current circle's diameter, so an operator could wheel round 2
        until the two numbers matched. Randomizing the spawn is worthless
        against a printed target — the spread would be biased toward zero
        by construction, the spread gate could never fire, and the
        repeatability figure SLDEA_MEASUREMENT §2.1a converts into an
        error term (R/2.93, R/1.47) would be fabricated precision entering
        the budget. Nothing about a previous round is shown until the last
        fit is in; then all of it is.

        SINGLETON like Advanced… (#176): the grab is pointer-only, so a
        pierced dialog must front the live one, never stack a second wait
        chain. Fail-CLOSED construction (audit 2026-08-05): the singleton
        handle publishes only once the dialog is fully built, and a
        try/finally destroys a half-built window and clears the handle no
        matter what raises — an exception mid-build used to leave a dead
        Toplevel in self._cal_win, and every later Detect lifted the
        corpse and returned, silently and forever.

        The two-point mode is blinder still: it shows NO length for the
        chord being placed either, because unlike the circle it needs no
        numeric feedback to place two clicks on an edge. So it is measured
        under stricter blinding than the circle — worth knowing when
        reading the comparison, since it can only handicap it.

        EVERY completed round-set is appended to the run's
        scale_calibration_log.txt and printed to stdout, ACCEPTED OR DECLINED
        (se.append_calibration_log). The six circle-mode spreads that motivated
        the two-point mode survive only because they were typed into a chat:
        every one of those calibrations was declined, and setup.txt is written
        at Save.

        **THE KEY BINDINGS, IN FULL — and THIS IS THEIR HOME** (`#215` trim,
        2026-08-07). The catalogue used to be a standing third line of the
        measuring modes' on-screen help; a catalogue is reference material and
        it came off the screen with the rest of the prose (see
        CAL_SCREEN_MAX_LINES). The two keys that change a MEASUREMENT are
        still named where they are needed — Z by the live line's own sub-1:1
        warning, Backspace on the ◀ Back button's own label:

          * Ctrl+wheel  zoom about the cursor        * F   fit to window
          * right-drag  pan                          * Z   1:1
          * arrows      nudge the last point/circle (Shift = coarse)
          * Shift+arrows  resize the circle
          * Backspace / ◀ Back   go back one round (re-randomised)
          * P    reuse the RECORDED anchor from setup.txt, skipping the rounds
          * Esc  cancel

        The frame is ZOOMABLE because the fixed 0.41x preview put one display
        pixel at ~2.5 full-res px while the soft ink edge spans 8-15 (audit
        2026-08-05). In the circle mode the plain wheel is the FINE RESIZE so
        it cannot fight the sizing gesture; in the two-point mode there is
        nothing to resize, so the plain wheel zooms. Geometry is always
        full-res image coordinates."""
        import random
        if not self.run:
            messagebox.showinfo("Calibrate", "Pick a run first")
            return
        if self._cal_win is not None and self._cal_win.winfo_exists():
            self._cal_win.lift()
            self._cal_win.focus_set()
            return
        from PIL import Image, ImageTk
        img, anchor_is_baseline, tried, frame_name = self._anchor_frame()
        if img is None:
            messagebox.showerror(
                "Calibrate",
                "No readable frame to calibrate on — Detect and Save "
                "stay gated until one exists (restore or re-export a "
                "frame).\nTried: " + '; '.join(tried[:4])
                + ('…' if len(tried) > 4 else ''))
            if then_detect:
                self._gate_status()
            return
        recorded = se.load_scale_anchor(self.rundir)
        n_px_rows = self._px_rows()
        # ONCE, not per repaint: the round header now carries this warning
        # (head_text) and the header is rebuilt on every mouse move.
        diam_rec = self._diam_recorded()
        # WHICH of the two folded actions this dialog is serving. Normalised
        # rather than trusted, so a caller that passes nothing gets the
        # non-writing one: a dialog that guessed REANCHOR would put "this
        # writes data.csv now" in front of an operator whose Save is the only
        # thing that will write.
        if intent not in (SCALE_INTENT_CALIBRATE, SCALE_INTENT_REANCHOR):
            intent = SCALE_INTENT_CALIBRATE
        reanchoring = (intent == SCALE_INTENT_REANCHOR)
        # ---- VERIFY-MODE availability, decided BEFORE the window is built
        # (`#215`, 2026-08-06 evening.) The verify mode shows the automatic
        # fit drawn on the frame the operator is looking at, so it needs BOTH a
        # fit AND the certainty that the fit belongs to THIS frame: on the
        # fallback-frame path _anchor_frame() serves a later activated frame
        # while _base_gray() (and so the fit) can only ever come from the
        # baseline row. Drawing the baseline's circle over an activated
        # frame would be an outright lie, so the verify mode is withdrawn
        # unless the two are the same file.
        auto0 = self._auto_disc()
        same_frame = bool(anchor_is_baseline
                          and frame_name
                          and frame_name == self._base_frame_name())
        verify_ok = bool(same_frame and (auto0 or {}).get('diam_px'))
        refusal = (None if verify_ok else self._auto_disc_refusal())
        opens_c = (verify_ok and mode is None) or (mode == se.CAL_MODE_VERIFY
                                                  and verify_ok)
        win = tk.Toplevel(self.root)
        try:
            # THE INTENT IS ON THE TITLE, and the wording comes from ONE
            # place (scale_intent_banner) rather than being retyped at each of
            # the three title call sites. It came off the round header in the
            # operator's second pass (`#215`, 2026-08-07), so the title is now
            # one of only three surfaces that carry it and none of them may
            # drift.
            win.title(scale_intent_banner(intent) + " — pick a method")
            win.transient(self.root)
            # WARNINGS ONLY, since the 2026-08-07 trim (`#215`, operator).
            # This block used to open with the folded-action banner and a
            # standing "SCALE GATE — this run's px→mm anchor. The nominal
            # disc is 16 mm across." Both were prose that said the same thing
            # on every run, in a block that is above the picture the operator
            # is working in, and together they were two of the nine lines the
            # measuring modes were showing.
            #
            # Neither was DELETED. They went to the round header, and then
            # off it again the same evening (`#215`, operator, second pass):
            # the folded action's tag is now carried by the window TITLE, the
            # PRIMARY BUTTON and the re-anchor CONFIRMATION — still three
            # surfaces, and all three are places where it decides something —
            # while the nominal disc size is in the settings, in setup.txt and
            # on every log line. Only its WARNING is on screen, below.
            #
            # What stays here is only what is CONDITIONALLY TRUE — a fit that
            # refused, a missing baseline, a diam_mm nobody measured. On an
            # ordinary run this label carries nothing and is not packed at
            # all, so it costs the picture no height.
            gate = ''
            if not verify_ok:
                # THE REFUSAL, STATED. When baseline_disc will not fit this
                # baseline there is nothing to verify and the operator has
                # to measure by hand after all — which is a different job
                # from the one the gate normally opens with, so it is said
                # plainly and with the fitter's own reason rather than left
                # to be inferred from a missing radio button. One line now,
                # reason included, where it was two.
                why = (f" Reason: {refusal}" if refusal else
                       " Reason: this is NOT the baseline frame the fit runs "
                       "on, so its circle would not belong to this picture."
                       if not same_frame else
                       " Reason: not reported — see the console.")
                gate += ("⚠ NO automatic fit on this run, so there is "
                         "nothing to verify: measure the disc BY HAND." + why)
            if not anchor_is_baseline:
                gate += ("\n⚠ The baseline frame is missing — this is a LATER "
                         "frame. Calibrate here only if the disc is visibly "
                         "AT REST; otherwise Esc and restore the baseline.")
            # THE "ALREADY CALIBRATED" ROW IS GONE FROM HERE — it moved into
            # the button's own confirmation (`#215`, operator 2026-08-07,
            # second pass). It used to read
            #
            #   ⚠ 81 row(s) already carry px — accepting RE-SCALES every
            #   recorded mm² at the next 💾 Save, including frames you never
            #   re-review   ·   an anchor is on record — press P to REUSE it.
            #
            # and it was the top row of the window on every saved run, i.e.
            # standing prose above the picture the operator is measuring in.
            # The operator's reasoning, and it is the right one: the place a
            # consequence belongs is the moment it is incurred. So the
            # RE-ANCHOR confirmation (_reanchor_msg) now OPENS by naming the
            # calibration already on record and asking whether to overwrite
            # it — and once that question has been answered, "every area is
            # re-derived" needs no spelling out, because that is what
            # overwriting a scale MEANS.
            #
            # Nothing numeric was lost. The percentage the move costs is
            # quoted where a number can be checked: `rescale_note` on every
            # exceptional gate, the verify mode's own consequence line, and
            # the confirmation's multiplier plus its resting-area
            # before → after. `P` keeps its own button, which carries its own
            # key. The `[critical]` partial-re-save rule (SLDEA_HANDOFF
            # 2026-08-05) is unchanged; only where it is said is.
            #
            # THE DISC'S ONE WARNING LANDS HERE INSTEAD. `disc 16 mm` came
            # off the round header with the rest of its run-on, and this
            # warning rode on it. It is conditionally true — false whenever
            # capture recorded a diameter — which makes it exactly what this
            # warnings-only block is for, and it is the reason the block is
            # not simply deleted along with the row above.
            if not diam_rec:
                gate += (('\n' if gate else '')
                         + f"⚠ {self.settings['diam_mm']:g} mm is the "
                           f"settings DEFAULT — the mask was NOT measured at "
                           f"capture, so every absolute mm² inherits whatever "
                           f"that value is wrong by.")
            # PACKED ONLY WHEN IT HAS SOMETHING TO SAY (`#215`, 2026-08-07).
            # Previously this label always carried at least the banner and the
            # standing SCALE GATE line, so it was always on screen; now it is
            # warnings-only and an ordinary run has none, so on an ordinary run
            # it is not packed and the picture keeps the height. It is hidden
            # in the verify mode regardless, where every warning it can carry
            # is either impossible (the verify mode requires both a fit and the
            # baseline frame) or already folded into verify_evidence's own
            # lines. sync_buttons owns the decision.
            GATE_PACK = dict(pady=(6, 2), padx=8, anchor='w')
            gate_lbl = tk.Label(win, text=gate, justify='left',
                                wraplength=980)
            gate_lbl.pack(**GATE_PACK)
            # ---- the mode chooser (`#215`, 2026-08-06) ----------------
            # Per calibration, not per session, so both methods can be
            # driven on the SAME disc minutes apart — which is the only
            # way the comparison means anything. Switching restarts the
            # round-set: half a circle set and half a two-point set is not
            # a measurement of either method.
            chooser = tk.Frame(win)
            chooser.pack(anchor='w', padx=8, pady=(0, 2))
            # `mode` may arrive as a legacy LETTER from an old caller, so it
            # goes through the same read rule every record does
            want = se.cal_mode_read(mode)
            if want == se.CAL_MODE_VERIFY and not verify_ok:
                want = None            # asked for verify, there is nothing
                #                        to verify: fall through to the manual
                #                        mode with the refusal stated above
            mode_var = tk.StringVar(
                value=(want if want else se.cal_open_mode(auto0)
                       if verify_ok else se.CAL_DEFAULT_MODE))
            n_var = tk.StringVar()
            stroke_var = tk.StringVar(value=CAL_STROKE_STYLES[0])
            # BOLD, and the radios are now the ONLY route into a hand
            # measurement (`#215`, operator 2026-08-06 late): the
            # "✎ Measure by hand instead" button was dropped because the
            # radios already switch methods and a second way to do one thing
            # is the clutter the operator objected to. So this row has to
            # read as the mode control on its own — hence the weight here,
            # and hence each manual radio saying BY HAND rather than just
            # naming its gesture.
            tk.Label(chooser, text="METHOD:",
                     font=('TkDefaultFont', 10, 'bold')).pack(side=tk.LEFT)
            n_choices = sorted(se.D2_RANGE_FACTORS)
            # LABELLED A / B / C in this order, with A = verify (operator
            # 2026-08-06 late). The letters are se.CAL_MODE_LABELS and are
            # presentation only — what a record stores is the NAME, because
            # this is the second numbering these methods have had and a
            # stored letter would have silently changed meaning under the
            # first swap. A run's letter keeps its position when the verify
            # mode is withdrawn: B is the circle whether or not A is offered.
            LBL = se.CAL_MODE_LABELS
            # SHORT, because this row sets the dialog's minimum width and
            # the operator's other standing complaint about this screen was
            # its length. "BY HAND" is the part that has to be there: it is
            # what the deleted ✎ button used to say.
            choices = [
                (se.CAL_MODE_VERIFY,
                 f"{LBL[se.CAL_MODE_VERIFY]} · VERIFY the automatic fit"),
                (se.CAL_MODE_CIRCLE,
                 f"{LBL[se.CAL_MODE_CIRCLE]} · BY HAND: fit a circle"),
                (se.CAL_MODE_TWOPOINT,
                 f"{LBL[se.CAL_MODE_TWOPOINT]} · BY HAND: two opposite "
                 f"points")]
            if not verify_ok:
                # nothing to verify on this run: the radio is not offered as
                # an empty screen (the gate block says why, above)
                choices = [c for c in choices
                           if c[0] != se.CAL_MODE_VERIFY]
            for val, txt in choices:
                tk.Radiobutton(chooser, text=txt, value=val,
                               variable=mode_var,
                               command=lambda: switch_mode()).pack(
                                   side=tk.LEFT, padx=(4, 8))
            # ---- the two per-mode controls, each in its own box ----------
            # BOXED so they can be DE-RENDERED as a unit, caption and all
            # (`#215`, operator 2026-08-07, second pass). Greying them out
            # left two dead captions and two dead menus on the top row of
            # every screen they do not apply to: the round count is
            # meaningless in the verify mode (there are no rounds) and the
            # stroke belongs to the circle mode alone. A disabled control is
            # still a thing to read and still invites a click; an absent one
            # is not. sync_buttons owns which of them exist.
            rounds_box = tk.Frame(chooser)
            rounds_box.pack(side=tk.LEFT)
            tk.Label(rounds_box, text="rounds:").pack(side=tk.LEFT)
            # Only round counts the d2 table has a factor for: an n with
            # no factor cannot be converted to sigma/SE at all, so it is
            # refused at the chooser rather than at the gate.
            n_menu = tk.OptionMenu(rounds_box, n_var,
                                   *[str(v) for v in n_choices],
                                   command=lambda _v: set_rounds())
            n_menu.pack(side=tk.LEFT, padx=(2, 8))
            stroke_box = tk.Frame(chooser)
            stroke_box.pack(side=tk.LEFT)
            # THE LETTER FOLLOWS THE LABEL, not a hardcoded "A". This
            # caption said "A stroke:" and the stroke belongs to the
            # CIRCLE mode, which the 2026-08-06 swap relabelled from A
            # to B -- a stale letter here would point the operator at
            # the verify mode, which has no stroke to choose.
            tk.Label(stroke_box,
                     text=f"{LBL[se.CAL_MODE_CIRCLE]} stroke:").pack(
                         side=tk.LEFT)
            stroke_menu = tk.OptionMenu(stroke_box, stroke_var,
                                        *CAL_STROKE_STYLES,
                                        command=lambda _v: repaint())
            stroke_menu.pack(side=tk.LEFT, padx=2)
            ROUNDS_PACK = dict(side=tk.LEFT)
            STROKE_PACK = dict(side=tk.LEFT)
            # The METHOD-SPECIFIC block: the gestures in the measuring modes,
            # and in the verify mode the fit's own evidence. Split out of
            # `gate` (which is the static warnings) because the two say
            # different things at different lengths, and because showing the
            # two-point mode's rotation explanation while the verify mode is up
            # is noise the operator has to read past.
            how = tk.Label(win, text='', justify='left', wraplength=980)
            how.pack(anchor='w', padx=8, pady=(0, 2))
            # The ROUND HEADER — progress, which the verify mode has none of.
            # Named and hidden there (see sync_buttons): "there are no rounds
            # and no spread" was a line spent saying that a thing is absent,
            # which the window title already covers.
            HDR_PACK = dict(anchor='w', padx=8)
            # wraplength, for the same reason `live` has one: the two-point
            # round header runs to ~200 characters and without it the dialog
            # was 300 px wider than its own canvas (measured by rendering).
            hdr = tk.Label(win, text='', justify='left', wraplength=980,
                           font=('TkDefaultFont', 11, 'bold'))
            hdr.pack(**HDR_PACK)
            cw = max(400, min(1000, self.root.winfo_screenwidth() - 220))
            # 400, not 360: the chooser row plus the taller header cost
            # ~40 px, and the pre-existing budget already left only ~35 px
            # of slack on a 1080p bench screen with every warning showing.
            #
            # PER MODE, not fixed at build time, and since the declutter the
            # split runs the OTHER WAY (`#215`, 2026-08-06 late). The verify
            # mode now shows four lines where A/B show a gate block plus three
            # lines of gesture help and a round header, so the verify mode is
            # the mode with height to spare — and the picture is what it must
            # be spent on, because in the verify mode the picture IS the
            # verification. The measuring modes' figure is unchanged, so their
            # layout is untouched.
            def canvas_h(for_verify):
                return max(300, min(760, self.root.winfo_screenheight()
                                    - (300 if for_verify else 400)))

            ch = canvas_h(opens_c)
            cv = tk.Canvas(win, width=cw, height=ch, bg='#111',
                           cursor='crosshair')
            cv.pack(padx=8, pady=6)
            LIVE_PACK = dict(anchor='w', padx=8)
            # wraplength MATTERS here: without it this line's ~150
            # characters force the dialog wider than its own canvas, which
            # is the defect the `#215` declutter found on the verify mode's
            # version of it. The measuring modes kept it until now.
            live = tk.Label(win, text='', justify='left', wraplength=980)
            live.pack(**LIVE_PACK)
            btns = tk.Frame(win)
            btns.pack(fill='x', padx=8, pady=(2, 8))
            vt = strc.ViewTransform()
            vt.fit(img.width, img.height, cw, ch)
            rnd = random.Random()

            def show_line(w, on, opts, before=None):
                """Show or hide one widget, keeping its place in the layout.
                pack_forget/pack rather than text='' because an empty Label
                still reserves a line's height, and in the verify mode that
                height belongs to the picture — three blank lines is ~65 px
                of the canvas gone to say nothing.

                ALSO HOW THE INAPPLICABLE CONTROLS GO AWAY (`#215`, operator
                2026-08-07, second pass): *"a disabled control still costs a
                line of visual scanning and invites a click; an absent one
                does not."* So ◀ Back, ⟲ Restart, the round-count selector
                and the stroke selector are DE-RENDERED where they mean
                nothing rather than greyed out. `before` is the always-packed
                widget they must stay to the left of — omitted for the
                chooser row's boxes, which are last in their frame's packing
                list and so re-pack in order on their own (the stroke box is
                only ever shown when the rounds box is, so their relative
                order cannot invert)."""
                try:
                    if on:
                        if not w.winfo_manager():
                            w.pack(**(dict(opts, before=before)
                                      if before is not None else opts))
                    elif w.winfo_manager():
                        w.pack_forget()
                except tk.TclError:
                    pass          # a half-torn-down dialog is not a failure

            def say_live(text):
                """THE ONLY writer of the live line. Sets the text and
                guarantees the invariant that non-empty text is VISIBLE
                text.

                The verify mode's four-line budget hides `live`, but a refused
                <Return> has to be SEEN or the refusal is silent and the
                operator taps again harder. So the line reappears for the
                message and goes away at the next mode change: it is an
                answer to something the operator just did, not standing
                clutter.

                Every write goes through here rather than live.config because
                the first version did not, and the circle mode's diameter
                readout — the one number a circle-mode round needs — came back
                from a C→A switch with its text set and its label still
                forgotten. A message nobody can read is worse than no
                message: the caller believes it spoke."""
                live.config(text=text)
                show_line(live, bool(text), LIVE_PACK, btns)

            def view_h():
                """The canvas's CURRENT height — the one number the view
                math must agree with. Read live rather than closed over,
                because sync_buttons resizes the canvas per mode and a
                stale height would crop the picture wrong."""
                try:
                    return int(cv.cget('height'))
                except (tk.TclError, TypeError, ValueError):
                    return ch
            # box the drag CAN reach vs the box a spawn must sit in
            full_box = (0.0, 0.0, float(img.width), float(img.height))
            roi_box = cal_roi(img.width, img.height,
                              self.settings.get('roi_frac', 0.85))
            st = {'photo': None, 'pan': None, 'grab': None,
                  'round': 1, 'diams': [], 'circle': None,
                  # twopoint: the rotated display image, the angle it is
                  # rotated by, the angles still to come in this set, the
                  # angles already used, and the current round's two
                  # clicks in ORIGINAL image px ('pts') plus the same two
                  # in ROTATED display px ('ptsv', for drawing only —
                  # never for measuring)
                  'mode': mode_var.get(), 'n': 0, 'rimg': None,
                  'rot': 0.0, 'pending_rots': [], 'rots': [],
                  # seeded with the fit verify-mode availability was decided
                  # on, so the dialog and the chooser can never disagree about
                  # whether there is something to verify
                  'pts': [], 'ptsv': [], 'auto': auto0,
                  # a modal warning is up: <Return> must not reach the
                  # dialog underneath while one is (review 2026-08-06)
                  'modal': False,
                  # verify: the display-only contrast window (lo, hi) gray
                  # levels, computed ONCE from the frame's measured disc and
                  # paper levels. Once, not per repaint: a window that moved
                  # as the operator panned would change the picture they are
                  # judging while they judge it.
                  'stretch': None, 'lut': None,
                  # the anchor guard's modal has to print the mean and the
                  # reference diameter for its warning to be actionable at
                  # all, so declining it and refitting means the next
                  # rounds ARE fitted against a disclosed number. That
                  # cannot be prevented; it is recorded instead.
                  'disclosed': False}

            def two_point():
                return st['mode'] == se.CAL_MODE_TWOPOINT

            def verify():
                """The verify mode — nothing is fitted here, so every
                round-based path has to sit this one out."""
                return st['mode'] == se.CAL_MODE_VERIFY

            def disp():
                """(image, w, h) currently DISPLAYED. The circle mode shows the
                frame itself; the two-point mode shows it rotated, and `vt`
                therefore maps view px to ROTATED px in the two-point mode —
                every click is pushed back through unrotate_point before it is
                measured
                or stored."""
                if two_point() and st['rimg'] is not None:
                    return st['rimg'], st['rimg'].width, st['rimg'].height
                return img, img.width, img.height

            def fit_view(keep_zoom=False):
                _im, w, h = disp()
                if keep_zoom and vt.zoom > 0:
                    # a new rotation changes the canvas size, so the pan
                    # has to be recentred — but keeping the ZOOM matters:
                    # at fit zoom on a 1080p frame the operator is below
                    # 1:1, which the live readout warns about, and losing
                    # their zoom every round would push them to work there
                    z = vt.zoom
                    vt.ox = w / 2.0 - cw / (2.0 * z)
                    vt.oy = h / 2.0 - view_h() / (2.0 * z)
                else:
                    vt.fit(w, h, cw, view_h())

            def verify_view():
                """Frame the verify mode on the CIRCLE, not on the frame — the
                operator is judging one boundary, not surveying the picture
                (verify_zoom). Falls back to fitting the frame when there is
                no fit to centre on, which cannot happen through the chooser
                but keeps this fail-closed."""
                ref = auto_ref() or {}
                h = view_h()
                z = verify_zoom(ref.get('diam_px'), cw, h)
                if z is None:
                    fit_view(keep_zoom=False)
                    return
                vt.zoom = z
                vt.ox = float(ref.get('cx', img.width / 2.0)) - cw / (2.0 * z)
                vt.oy = float(ref.get('cy', img.height / 2.0)) - h / (2.0 * z)

            def refit():
                """Re-frame the view for the CURRENT mode, after anything
                that changes the canvas size. One place, so the verify
                mode's opening zoom cannot be clobbered by a later
                fit_view."""
                if verify():
                    verify_view()
                else:
                    fit_view(keep_zoom=False)

            def respawn():
                st['circle'] = spawn_circle(
                    img.width, img.height,
                    self.settings.get('roi_frac', 0.85), rnd)

            def set_circle(cx, cy, r):
                st['circle'] = clamp_circle(cx, cy, r, full_box,
                                            contain=False)

            def set_rotation(deg, keep_zoom=True):
                """Rotate the DISPLAY for one twopoint-mode round and clear the
                round's clicks.

                BICUBIC, not NEAREST: the ink edge is a soft 8-15 px ramp
                and the operator is aiming at its half-height, so the
                resample has to preserve the ramp rather than staircase
                it. It does soften the edge slightly — see unrotate_point
                for why that costs sigma and not the mean."""
                st['rot'] = float(deg) % 360.0
                st['rimg'] = img.rotate(st['rot'], resample=Image.BICUBIC,
                                        expand=True, fillcolor=(17, 17, 17))
                st['pts'], st['ptsv'] = [], []
                fit_view(keep_zoom=keep_zoom)

            def rounds_wanted():
                """Rounds this set wants, read from the CHOOSER — one
                source of truth. st['n'] mirrors it for the log and for
                is_last_round; reading st['n'] here instead would have meant
                the very first set fell back to the circle mode's 3 whatever
                the chooser said, because st['n'] is not set until
                restart_all runs."""
                try:
                    n = int(n_var.get())
                except (TypeError, ValueError):
                    n = se.CAL_MODE_ROUNDS.get(st['mode'], se.CAL_ROUNDS)
                return max(2, n)

            def is_last_round():
                """True when accepting the current fit FINISHES the
                calibration — i.e. when the next press runs the gates."""
                return len(st['diams']) + 1 >= max(rounds_wanted(),
                                                   st['round'])

            def head_text():
                """PROGRESS ONLY — no previously accepted diameter, no
                running average (review 2026-08-06). A visible target makes the
                rounds dependent, which biases the scatter toward zero, stops
                the gate from ever firing, and turns the repeatability figure
                into fabricated precision. The live readout of the CURRENT
                circle is fine on its own; the two-point mode shows no length
                at all, because two clicks on an edge need
                no numeric feedback to place.

                THE ROUND AND NOTHING ELSE, since the 2026-08-07 cuts
                (`#215`, operator, second pass). The morning's trim folded two
                things onto this line from the gate block — the nominal disc
                size and the folded action's tag — and the operator drove all
                three modes on real runs that evening and cut both again:

                * the FOLDED ACTION'S TAG (`scale_intent_banner`). *"The
                  commit warning belongs in one place — on the primary button
                  and in its confirmation — not repeated in every mode's
                  header."* It is still stated three times where it decides
                  something: the window TITLE, the PRIMARY BUTTON (which says
                  `✔ Finish & RE-ANCHOR NOW` on exactly the press that
                  commits), and the re-anchor CONFIRMATION, which now opens by
                  asking whether to overwrite the calibration on record. What
                  went is the standing copy on a line the operator watches for
                  the round number.
                * `disc 16 mm`. Named for the circle mode and applied to both,
                  because the two measuring screens have to read the same and
                  the operator's objection was the run-on itself. The nominal
                  diameter is not something an operator acts on mid-round; it
                  is in the settings, in `setup.txt` and on every log line.
                  Its ONE warning — that `diam_mm` is the settings default and
                  was never measured at capture — is conditionally true, so it
                  moved to the gate block, which is exactly the label that
                  carries conditionally-true warnings and is otherwise
                  unpacked.
                * `· view rotated 299.3°` in the two-point mode — *"drop the
                  bolded run-on after Round 1 of 3"*. The angle is a fact
                  about the picture, and the picture shows it: the frame is
                  visibly rotated. It stays in the record (`rot=` on the log
                  line), where the comparison between the modes needs it.

                What is left is `Method B · Round 1 of 3` (plus the two-point
                mode's point count, which is progress and is what this line is
                for).

                Two things left it earlier, both explanation rather than
                guidance:

                * *"the earlier rounds are HIDDEN until the last fit is in —
                  each fit has to be independent, or the scatter is a
                  fiction"*. The BLINDNESS IS UNCHANGED; what went is the
                  paragraph justifying it. Nothing about a previous round is
                  still on this screen, which is the property that matters,
                  and it is asserted by the tests that look for a previous
                  diameter rather than by a sentence claiming it.
                * *"this is the LAST round: use the ✔ Finish calibration
                  button"*. The primary BUTTON says "✔ Finish calibration" on
                  exactly that round, and in the two-point mode the live line
                  says it again as soon as the first point is down. A third
                  copy on the header was the ceremony, not the signal."""
                if verify():
                    # NOTHING. No rounds, so no progress to report — and a
                    # line whose whole content is "there are no rounds and
                    # no spread" is a line spent announcing an absence
                    # (`#215` declutter). The window title already says
                    # which mode this is; sync_buttons hides the label
                    # entirely so it does not even cost a blank line.
                    #
                    # The blindness rules that govern A/B have nothing to
                    # protect here either: the operator is not producing a
                    # number, so there is no number to steer.
                    return ''
                # the LETTER here, because the letter is what the radio row
                # beside it shows; the record keeps the name
                where = (f"Method {se.cal_mode_label(st['mode'])} · Round "
                         f"{st['round']} of "
                         f"{max(rounds_wanted(), st['round'])}")
                if two_point():
                    where += f" · {len(st['pts'])} of 2 points"
                return where

            def reveal_text(stats):
                """All of it, at once, once the fitting is OVER — the
                values, their average, the range, and the n-aware
                conversion the gate judges (SLDEA_MEASUREMENT §2.1a).
                Shown on the main window's status line by accept(), which
                is the one place that outlives the dialog; deliberately NOT
                shown while any further round could still be fitted.

                sigma leads because sigma is what the A/B comparison turns
                on: it is the METHOD's per-fit precision and it is the only
                figure here that survives a different round count."""
                conv = (f"σ {stats['sigma_pct']:.2f}%/fit, SE "
                        f"{stats['se_pct']:.2f}% diam = "
                        f"{stats['area_se_pct']:.2f}% area "
                        f"(gate {se.CAL_SE_PCT:g}%)"
                        if stats.get('se_pct') is not None
                        else f"NOT CONVERTIBLE: no d₂ factor for "
                             f"n={stats['n']}")
                return (f"mean of {stats['n']}: "
                        + ', '.join(f"{v:.1f}" for v in stats['values'])
                        + f" px, spread {stats['spread_px']:.1f} px = "
                          f"{stats['spread_pct']:.2f}%, " + conv)

            def auto_ref():
                """The automatic disc fit, fetched once per dialog. Wanted
                for the guard AND for every log record — including the
                round-sets declined before the guard ever runs, which is
                most of them and exactly the data the A/B comparison
                needs."""
                if st['auto'] == '?':
                    st['auto'] = self._auto_disc()
                return st['auto']

            def repaint():
                src, sw, sh = disp()
                ix0, iy0 = vt.to_image(0, 0)
                ix1, iy1 = vt.to_image(cw, view_h())
                cx0, cy0 = max(0, int(ix0)), max(0, int(iy0))
                cx1 = min(sw, int(ix1) + 2)
                cy1 = min(sh, int(iy1) + 2)
                cv.delete('all')
                if cx1 > cx0 and cy1 > cy0:
                    crop = src.crop((cx0, cy0, cx1, cy1))
                    # THE VERIFY MODE ONLY, and only on the DISPLAY copy: the
                    # ink step is ~20 gray levels on a ~186 background, which
                    # is nearly invisible, and an operator squinting at a flat
                    # grey field is not verifying anything. The measurement is
                    # already finished and used the raw frame — this LUT
                    # touches `crop`, a throwaway, and nothing else.
                    if verify() and st['lut']:
                        try:
                            crop = crop.point(st['lut'] * len(crop.getbands()))
                        except (ValueError, TypeError):
                            pass          # never lose the picture to a LUT
                    dw = max(1, int(round((cx1 - cx0) * vt.zoom)))
                    dh = max(1, int(round((cy1 - cy0) * vt.zoom)))
                    res = (Image.NEAREST if vt.zoom >= 2.0
                           else Image.BILINEAR)
                    st['photo'] = ImageTk.PhotoImage(
                        crop.resize((dw, dh), res))
                    vx, vy = vt.to_view(cx0, cy0)
                    cv.create_image(int(vx), int(vy), anchor='nw',
                                    image=st['photo'])
                if verify():
                    paint_verify()
                elif two_point():
                    paint_points()
                else:
                    paint_circle()
                hdr.config(text=head_text())
                zoom_note = (f"zoom {vt.zoom:.2f}x"
                             + ('' if vt.zoom >= 1.0 else
                                "  ⚠ below 1:1 — press Z before accepting"))
                if verify():
                    # NOTHING, in the steady state (`#215` declutter). This
                    # line used to re-announce the stretch a second time
                    # (the evidence block already said it), explain the 1 px
                    # stroke, and carry the "below 1:1 — press Z" nag. The
                    # stretch is now stated once; the 1 px stroke is a
                    # design decision recorded in paint_verify, not
                    # something the operator acts on; and the nag is gone
                    # because verify_zoom opens ABOVE 1:1, so it never had
                    # anything to warn about (it stays in A/B, where a
                    # fit-to-window view genuinely is sub-1:1 and the
                    # operator is about to measure on it).
                    #
                    # Not cleared, so a transient say_live() message — the
                    # <Return> refusal — survives a repaint.
                    pass
                elif two_point():
                    # NO LENGTH, deliberately (see head_text): the two-point
                    # mode needs no numeric feedback to put two clicks on an
                    # edge, so it does not offer one — nothing on screen is a
                    # number a later round could be steered onto.
                    #
                    # AUTO-ADVANCE (operator 2026-08-06 late): the second
                    # click banks the round and moves on, so the only states
                    # this line normally describes are 0 and 1 points placed
                    # — 2 survives only on the LAST round, where the ✔ Finish
                    # button is still required. What it has to say is what the
                    # NEXT CLICK DOES, because with no Continue press there is
                    # no other moment to say it, and it names the undo in the
                    # same breath so the misclick has a visible answer.
                    if len(st['pts']) >= 2:
                        nxt = ("   ·   both points placed — ✔ Finish "
                               "calibration, or ◀ Back (Backspace) to redo "
                               "this round")
                    elif len(st['pts']) == 1:
                        nxt = ("   ·   click the point OPPOSITE the first — "
                               + ("then ✔ Finish calibration"
                                  if is_last_round() else
                                  "that click BANKS this round and moves to "
                                  "the next (◀ Back / Backspace undoes it)"))
                    else:
                        nxt = "   ·   click one edge of the resting disc"
                    say_live(f"{len(st['pts'])} of 2 edge points placed"
                             + nxt + f"   ·   {zoom_note}")
                else:
                    dpx = 2.0 * st['circle'][2]
                    say_live(f"circle: {dpx:.1f} px across  →  "
                             f"{self.settings['diam_mm'] / max(dpx, 1e-9):.5f}"
                             f" mm/px   ·   centre "
                             f"({st['circle'][0]:.0f}, "
                             f"{st['circle'][1]:.0f})   ·   " + zoom_note)

            def paint_circle():
                ccx, ccy, r = st['circle']
                vx, vy = vt.to_view(ccx, ccy)
                vr = r * vt.zoom
                # The stroke IS the comparison in the circle mode, so it must
                # be visible against the ink — and the operator's measured
                # diagnosis is that at 3 px it also HIDES the edge it sits on,
                # which is what the thin/dashed options are here to test
                # (cal_stroke_spec, the third arm of the A/B).
                wid, dash = cal_stroke_spec(stroke_var.get())
                halo = {'outline': '#000000', 'width': wid + 2}
                core = {'outline': '#00e676', 'width': wid}
                if dash:
                    halo['dash'] = core['dash'] = dash
                cv.create_oval(vx - vr, vy - vr, vx + vr, vy + vr, **halo)
                cv.create_oval(vx - vr, vy - vr, vx + vr, vy + vr, **core)
                cv.create_line(vx - 6, vy, vx + 6, vy, fill='#00e676')
                cv.create_line(vx, vy - 6, vx, vy + 6, fill='#00e676')
                for _nm, hx, hy in circle_handles(ccx, ccy, r):
                    hvx, hvy = vt.to_view(hx, hy)
                    cv.create_rectangle(hvx - 4, hvy - 4, hvx + 4, hvy + 4,
                                        fill='#00e676', outline='#000000')

            def paint_verify():
                """The verify mode: the AUTOMATIC fit, drawn thin enough to
                judge against.

                One px, dashed, with a 1 px dark companion ring OUTSIDE it so
                it reads on pale paper and on dark ink without the ink that
                crosses the boundary getting any thicker. That is not a style
                preference: the measured cost of the circle mode's 3 px stroke
                was +2.07 % in diameter against A′'s +0.77 % at 1 px dashed
                (`#215`, 2026-08-06), i.e. laying a stroke along a soft edge
                moves where a human thinks the edge is. A dialog whose whole
                job is to present a boundary FOR JUDGEMENT may not use it.

                A centre cross with a hole in it, for concentricity — the same
                non-occluding rule as the two-point mode's markers, applied to
                a point nobody is judging but which the eye uses to check the
                circle is not offset."""
                ref = auto_ref() or {}
                if not ref.get('diam_px'):
                    return
                r = 0.5 * float(ref['diam_px'])
                vx, vy = vt.to_view(float(ref['cx']), float(ref['cy']))
                vr = r * vt.zoom
                # the dark companion sits OUTSIDE, never on the boundary
                cv.create_oval(vx - vr - 1, vy - vr - 1,
                               vx + vr + 1, vy + vr + 1, outline='#000000',
                               width=CAL_VERIFY_STROKE_PX,
                               dash=CAL_VERIFY_DASH)
                cv.create_oval(vx - vr, vy - vr, vx + vr, vy + vr,
                               outline='#00e676', width=CAL_VERIFY_STROKE_PX,
                               dash=CAL_VERIFY_DASH)
                g = CAL_MARK_GAP_VIEW
                for x0, y0, x1, y1 in ((vx + g, vy, vx + 12, vy),
                                       (vx - g, vy, vx - 12, vy),
                                       (vx, vy + g, vx, vy + 12),
                                       (vx, vy - g, vx, vy - 12)):
                    cv.create_line(x0, y0, x1, y1, fill='#00e676', width=1)

            def paint_points():
                """The two-point mode's markers: a 1 px hollow ring and a
                crosshair with a HOLE in it, at every placed point, plus the
                chord stopping short of both ends.

                Nothing is drawn within CAL_MARK_GAP_VIEW px of a click — this
                is the whole reason the two-point mode exists, so it is not
                left to chance: the shapes come from marker_shapes(), whose
                clearance is asserted in the tests. Never a filled dot,
                never a stroke laid along the boundary."""
                vpts = [vt.to_view(px, py) for px, py in st['ptsv']]
                if len(vpts) == 2:
                    seg = chord_segment(vpts[0], vpts[1])
                    if seg:
                        cv.create_line(*seg, fill='#00e676', width=1,
                                       dash=(3, 5))
                for vx, vy in vpts:
                    sh = marker_shapes(vx, vy)
                    # a dark ring one px outside the bright one, so the
                    # marker reads on pale paper and on dark ink alike
                    # without either ring thickening
                    cv.create_oval(sh['ring'][0] - 1, sh['ring'][1] - 1,
                                   sh['ring'][2] + 1, sh['ring'][3] + 1,
                                   outline='#000000', width=1)
                    cv.create_oval(*sh['ring'], outline='#00e676', width=1)
                    for arm in sh['arms']:
                        cv.create_line(*arm, fill='#00e676', width=1)

            def accept(dpx_full, source_frame, src_is_baseline=None,
                       stats=None, guard=None, overridden=False,
                       verified=None, who=None, when=None):
                # PROVENANCE (`#215` the verify mode, 2026-08-06 evening). The
                # method string is how an audit tells "a human MEASURED this"
                # from "a human APPROVED the machine's measurement" — two
                # different claims about where the number came from, with
                # different failure modes (a hand measurement can carry the
                # +2.6 % outer-toe bias; an approved fit carries whatever the
                # step-finder locks onto). Both override every automatic
                # reference at Save, because both are decisions a person is
                # answerable for; only the provenance differs.
                self.manual_ref = {'method': (se.ANCHOR_METHOD_VERIFIED
                                              if verified
                                              else se.ANCHOR_METHOD_MANUAL),
                                   'diam_px': float(dpx_full),
                                   'frame': source_frame,
                                   'is_baseline': (anchor_is_baseline
                                                   if src_is_baseline
                                                   is None
                                                   else src_is_baseline)}
                if verified:
                    # what quantifies an approved fit is the FIT's quality,
                    # not a spread across rounds there were none of
                    self.manual_ref.update({
                        'cal_mode': se.CAL_MODE_VERIFY,
                        'fit_circ': verified.get('circ'),
                        'fit_conf': verified.get('conf'),
                        'fit_resid_px': verified.get('fit_resid_px'),
                        'fit_arc_cov': verified.get('arc_cov'),
                        'fit_n_edge': verified.get('n_edge'),
                        'verified_by': who, 'verified_at': when})
                # `not verified`: a verify-mode anchor has NO rounds, so it
                # must not carry rounds_px/n_rounds/spread at all — recording a
                # one-element round list and a 0 spread would make an approved
                # automatic fit look like a hand measurement of perfect
                # precision, in setup.txt, forever
                if stats and not verified:
                    self.manual_ref.update({
                        'cal_mode': st['mode'],
                        'rounds_px': list(stats['values']),
                        'n_rounds': stats['n'],
                        'spread_px': stats['spread_px'],
                        'spread_pct': stats['spread_pct'],
                        # the n-aware conversion travels WITH the range,
                        # because a bare range cannot be converted later
                        # by anyone who does not also know n
                        'sigma_pct': stats.get('sigma_pct'),
                        'se_pct': stats.get('se_pct')})
                if verified:
                    self.manual_ref['guard'] = se.verify_note(verified, who,
                                                              when)
                if guard is not None:
                    note = se.anchor_guard_note(guard, overridden)
                    if st['disclosed']:
                        # these rounds were fitted AFTER a cross-check had
                        # printed the mean and the reference, so their
                        # spread is not a blind measurement any more. A
                        # suspiciously tight spread on such a run has an
                        # explanation, and it belongs in the record.
                        note += '; refit after a disclosed cross-check'
                    self.manual_ref['guard'] = note
                # THE REVEAL (#215 + review 2026-08-06): the values were
                # hidden while they were being fitted, so the record of
                # what they were belongs here — after the fitting, on the
                # one surface that survives the dialog closing
                # se_ok is THREE-valued: None means the round count has no
                # d₂ factor, so the SE was never computed. That must not
                # render as "over gate" (which implies a number was
                # judged) and must not render as clean either.
                if verified:
                    # A verify-mode status line must not borrow the vocabulary
                    # of a hand measurement: no σ, no SE, no spread (there is
                    # no sample), and NO cross-check tick (it would be an
                    # identity). What it says instead is the fit's own quality
                    # and who approved it.
                    #
                    # THE FOOTER IS GONE (`#215`, operator 2026-08-07, second
                    # pass). This line used to end with
                    #
                    #   — σ/SE undefined (one fit, no rounds); NOT
                    #   cross-checked, and no independent check of an
                    #   automatic anchor exists — overrides every automatic
                    #   reference at Save
                    #
                    # i.e. 160 characters of honesty arriving AFTER the
                    # operator had already decided, on the one surface that
                    # outlives the dialog and is read next by someone doing
                    # something else. Every word of it is true and none of it
                    # is lost: `se.verify_note` puts the whole statement —
                    # undefined σ/SE, the absent cross-check and the algebra
                    # that makes an independent one impossible — into
                    # setup.txt's `guard:` field, the log line writes
                    # `sigma=undefined se=undefined range=undefined
                    # verdict=NOT-GATED`, and `sldea_diag` repeats it in two
                    # verdicts AND its text report ("NOT CROSS-CHECKED, and no
                    # independent check of an automatic anchor exists…",
                    # "sigma/SE/range are UNDEFINED … not zero"). Verified by
                    # diffing the record across this change, not assumed.
                    #
                    # One clause of that footer is NOT verbatim in the record
                    # and is flagged rather than quietly dropped: "overrides
                    # every automatic reference at Save" is a statement about
                    # how the app RANKS references (se._is_manual_cal matches
                    # the method SET), not a measurement of this run, and what
                    # the record carries is the fact it follows from —
                    # `method: auto-verified`. The hand-measurement and reuse
                    # status lines still say it in words.
                    #
                    # What stays is EVIDENCE: the value adopted, who approved
                    # it, and the fit's own quality numbers.
                    rp = se.fit_resid_pct(verified)
                    bits = [f"circ {float(verified.get('circ', 0)):.3f}",
                            f"conf {float(verified.get('conf', 0)):.3f}"]
                    if verified.get('fit_resid_px') is not None:
                        bits.append(
                            f"resid "
                            f"{float(verified['fit_resid_px']):.1f} px"
                            + (f" = {rp:.2f}% of diam" if rp is not None
                               else ''))
                    if verified.get('n_edge'):
                        bits.append(f"{int(verified['n_edge'])} edge pts")
                    self.status.config(
                        text=f"scale VERIFIED (automatic fit approved by "
                             f"{who or '?'}): "
                             f"{self.settings['diam_mm']:g} mm = "
                             f"{dpx_full:.0f} px (" + ', '.join(bits) + ") "
                             f"({self.settings['diam_mm'] / dpx_full:.5f} "
                             f"mm/px)")
                    win.destroy()
                    return
                ok = se.se_ok(stats) if stats else None
                verdict_tag = ('' if ok else ' ⚠ OVER GATE' if ok is False
                               else ' ⚠ NOT JUDGED (no d₂ factor)')
                extra = ((' (' + reveal_text(stats) + verdict_tag + ')')
                         if stats else '')
                # an anchor that met no cross-check must not look like one
                # that passed a cross-check
                if guard is not None and not guard.get('available'):
                    extra += " ⚠ NOT cross-checked (no automatic disc fit)"
                elif guard is not None and overridden:
                    extra += " ⚠ guard OVERRIDDEN"
                self.status.config(
                    text=f"scale calibrated: "
                         f"{self.settings['diam_mm']:g} mm = "
                         f"{dpx_full:.0f} px{extra} "
                         f"({self.settings['diam_mm'] / dpx_full:.5f} "
                         f"mm/px) — overrides every automatic reference "
                         f"at Save")
                win.destroy()

            def ask(title, msg, default, three=False, **kw):
                """askyesno / askyesnocancel with an EXPLICIT default, and
                with <Return> taken off the window underneath while the
                question is up.

                Review 2026-08-06, demonstrated not speculated: tkinter's
                askyesno defaults to YES and was passed no default=, while
                the Toplevel bound <Return> to Continue/Finish. Six Enter
                presses therefore produced four "Rounds disagree" prompts
                and the "Anchor sanity check", and ACCEPTED an
                out-of-tolerance anchor — the guard that exists to catch a
                P3_2-style error could be dismissed without being read.
                Every accept-anyway prompt now defaults to the DECLINING
                button, and Enter cannot reach the dialog beneath."""
                st['modal'] = True
                try:
                    win.unbind('<Return>')
                except tk.TclError:
                    pass
                fn = (messagebox.askyesnocancel if three
                      else messagebox.askyesno)
                try:
                    return fn(title, msg, default=default, **kw)
                finally:
                    st['modal'] = False
                    try:
                        if win.winfo_exists():
                            win.bind('<Return>', continue_key)
                    except tk.TclError:
                        pass

            def rescale_note(mean_px, auto_px):
                """What accepting `mean_px` does to the mm² already in the
                CSV, as a NUMBER wherever one exists.

                Two references, in order of authority: the run's recorded
                anchor (the column was last derived at that scale), else
                the automatic disc fit — which is the scale a PRE-GATE save
                derived them at, and the two pre-gate runs
                (P3_6_2.5mL_20260729, DOT_P3_1_20260729) are exactly the
                ones whose whole column is about to hang on a hand-fitted
                anchor for the first time (review 2026-08-06, minor 6).
                With neither reference, say plainly that there is no
                percentage rather than showing None."""
                if not n_px_rows:
                    return ''
                if recorded:
                    pct = se.rescale_pct(recorded['diam_px'], mean_px)
                    if pct is not None:
                        return (f"\n\nAccepting also moves the "
                                f"{n_px_rows} already-measured row(s) by "
                                f"{pct:+.2f}% in mm² at the next Save "
                                f"(re-derived from px at this anchor, "
                                f"against the recorded "
                                f"{recorded['diam_px']:.1f} px).")
                pct = se.rescale_pct(auto_px, mean_px)
                if pct is not None:
                    return (f"\n\nNo anchor is on record for this run, so "
                            f"those {n_px_rows} mm² were derived at the "
                            f"AUTOMATIC fit's scale ({auto_px:.1f} px): "
                            f"accepting moves every one of them "
                            f"{pct:+.2f}% at the next Save, and it is the "
                            f"first time the column hangs on a hand-fitted "
                            f"anchor.")
                return (f"\n\nNo anchor is on record for this run AND "
                        f"there is no automatic fit, so there is no "
                        f"percentage to quote: all {n_px_rows} mm² are "
                        f"re-derived from px at this anchor, sight unseen, "
                        f"including rows you do not re-review.")

            def log_set(stats, outcome, guard=None):
                """Append this completed round-set to the run's calibration
                log AND print the same line to stdout — both, every time,
                accepted or declined.

                Why declined sets are logged: the six circle-mode spreads that
                motivated the two-point mode (`#215`, 2026-08-06) exist only as
                numbers typed into a chat, because every one of those
                calibrations was DECLINED at a gate and setup.txt is written at
                Save. A declined round-set is still a measurement of the
                method.

                Why stdout as well as the file: the run folder can be
                read-only or full (2026-08-04 disk-full incident), and a
                logging failure must not be how a measurement is lost."""
                auto = auto_ref() or {}
                auto_px = auto.get('diam_px')
                ok = se.se_ok(stats)
                vfy = verify()
                rec = {
                    'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'mode': st['mode'], 'stats': stats,
                    'gate': se.CAL_SE_PCT,
                    # the verify mode is NOT GATED rather than UNJUDGEABLE: the
                    # SE gate does not apply to a single automatic fit at all,
                    # which is different from a round-set whose n has no d₂
                    # factor. Writing 'UNJUDGEABLE' would imply the gate was
                    # reached for and missed.
                    'verdict': ('NOT-GATED' if vfy
                                else {True: 'PASS',
                                      False: 'OVER-GATE'}.get(ok)),
                    'rot_deg': (list(st['rots']) if two_point()
                                else None),
                    'stroke': (stroke_var.get()
                               if st['mode'] == se.CAL_MODE_CIRCLE
                               else None),
                    'auto_diam_px': auto_px,
                    'auto_pct': (None if vfy else
                                 (100.0 * (stats['mean'] - auto_px) / auto_px)
                                 if auto_px else None),
                    'outcome': outcome, 'frame': frame_name}
                if vfy:
                    rec.update({'fit_circ': auto.get('circ'),
                                'fit_conf': auto.get('conf'),
                                'fit_resid_px': auto.get('fit_resid_px'),
                                'fit_arc_cov': auto.get('arc_cov'),
                                'fit_n_edge': auto.get('n_edge'),
                                'fit_resid_pct': se.fit_resid_pct(auto)})
                try:
                    _p, line = se.append_calibration_log(self.rundir, rec)
                    print(line)
                except Exception as e:            # never lose a round-set
                    print(f"calibrate: logging the round-set failed: {e}")

            def verify_accept(_ev=None):
                """THE VERIFY MODE's only outcome that produces an anchor: the
                operator has read the fit's numbers, looked at the circle on
                the stretched frame, and approved it.

                NO GATE RUNS HERE, and that is deliberate rather than an
                omission:

                - the SE gate judges the scatter of n hand fits; there are
                  none, and `verify_stats` writes σ/SE/range as undefined
                  rather than 0 so nothing downstream reads a sample of one
                  as perfect precision;
                - the ANCHOR GUARD is **vacuous** on this anchor. Its two
                  references are the automatic fit (which IS this anchor, so
                  0.00 %) and the mask's π·(diam_mm/2)² resting area (which
                  this anchor makes exact by construction, so 0.00 %). It
                  could only ever pass, on any frame, however wrong the fit
                  is, so it is not run and — the part that matters — it is
                  not CLAIMED, here, on the status line, in the record, or
                  in `sldea_diag` (`se.guard_is_vacuous`).

                What IS recorded is that a named human approved it at a
                named time, with the fit's own quality numbers beside their
                name, and a `guard` note saying in words what was not
                checked (`se.verify_note`)."""
                ref = auto_ref()
                if not (ref or {}).get('diam_px'):
                    # cannot happen through the chooser (the verify mode is
                    # only offered with a fit in hand) but a fail-closed dialog
                    # does not rely on that
                    messagebox.showwarning(
                        "Calibrate",
                        "The automatic fit is no longer available, so there "
                        "is nothing to verify. Measure the disc by hand "
                        "instead.")
                    mode_var.set(se.CAL_DEFAULT_MODE)
                    switch_mode()
                    return
                stats = se.verify_stats(ref)
                try:
                    import getpass
                    who = getpass.getuser()
                except Exception:
                    who = '?'
                when = time.strftime('%Y-%m-%dT%H:%M:%S')
                log_set(stats, 'accepted-verified')
                accept(float(ref['diam_px']), frame_name, stats=stats,
                       verified=ref, who=who, when=when)

            # `hand_instead` and its ✎ Measure by hand instead button are GONE
            # (operator 2026-08-06 late): the radio row already switches
            # methods, so the button was a second control for one job. The
            # route it provided is unchanged — picking a manual radio still
            # restarts in that mode from scratch, blind, with the fit's
            # diameter NOWHERE on screen (switch_mode → restart_all), which is
            # the property that mattered about it. What is gone is the second
            # way to ask for it.

            def finish():
                """Average the rounds, run the SE gate, then the anchor
                guard, then accept — and only then REVEAL the values
                (accept() puts them on the status line, which outlives this
                window). Every gate is a DECISION the operator makes
                explicitly — the failure this replaces was silence, not a
                missing number — and every accept-anyway question defaults
                to declining it. Every exit path logs the round-set."""
                stats = se.calibration_stats(st['diams'])
                if not stats:
                    return

                def say(text):
                    say_live(text)
                    try:
                        win.update_idletasks()
                    except tk.TclError:
                        pass

                say(f"{stats['n']} fits recorded — checking how precise "
                    f"they are…")
                ok = se.se_ok(stats)
                if ok is None:
                    # The round count has no d₂ factor, so sigma and the
                    # mean's SE were never computed — §2.1a's conversion
                    # simply does not exist for this n. REFUSING is the
                    # point: silently reusing 1.693 (the n=3 factor the
                    # section used to hard-wire) would push a wrong error
                    # term into the budget with nobody seeing it happen.
                    say("⚠ this round count cannot be converted to an "
                        "error term")
                    if not ask(
                            "Precision cannot be judged",
                            f"You fitted {stats['n']} round(s), and there "
                            f"is no d₂ range-to-sigma factor for that "
                            f"count (the table covers n = "
                            f"{min(se.D2_RANGE_FACTORS)}–"
                            f"{max(se.D2_RANGE_FACTORS)}).\n\nSo this "
                            f"anchor's per-fit precision and its mean "
                            f"standard error were NOT computed, and the "
                            f"acceptance gate could not be applied. "
                            f"Nothing here has been checked against "
                            f"SLDEA_MEASUREMENT §2.1's ~0.4% diameter "
                            f"budget."
                            + rescale_note(stats['mean'], None)
                            + f"\n\nUse this UNJUDGED anchor anyway?\n\n"
                              f"No = cancel and calibrate again with a "
                              f"round count in the table.",
                            default='no', icon='warning'):
                        log_set(stats, 'declined-unjudgeable')
                        win.destroy()
                        return
                elif not ok:
                    # THE ACCEPTANCE GATE, on the mean's standard error
                    # rather than the raw range (2026-08-06 evening). Two
                    # reasons, both established: a range is not comparable
                    # across different n, and a range cannot shrink when a
                    # round is added — so a range gate's own remedy could
                    # never clear it and the flow always landed on "accept
                    # anyway". SE falls as 1/sqrt(n), so this gate can name
                    # the round count that WOULD clear it, from the sigma
                    # just measured (se.rounds_for_se).
                    #
                    # Quoted as PERCENTAGES ONLY, on purpose: a refit is
                    # one of the answers, so the individual diameters and
                    # their average must stay hidden here too or the refit
                    # is fitted against a disclosed target (review
                    # 2026-08-06). A percentage is not a number you can aim
                    # a click at.
                    # AT A GLANCE (`#215`, operator 2026-08-07). This prompt
                    # was 12 lines of prose and the operator, having met it on
                    # real data, asked for three things: the round σ, what it
                    # implies AS AREA ERROR — the number the measurement is
                    # actually quoted in — and the choice. So that is what it
                    # says, and it QUOTES the numbers rather than deriving
                    # them; the derivation (σ ≈ R/d₂(n), SE = σ/√n, area
                    # = 2·SE, and where the 0.4 %/0.8 % gate comes from) lives
                    # in SLDEA_MEASUREMENT §2.1a, which is where a reader who
                    # wants it will be.
                    #
                    # Off the prompt, still in the RECORD, every one of them:
                    # the mean's SE in diameter and the raw range (`se=` and
                    # `range=` in scale_calibration_log.txt, `se_pct` and
                    # `spread_pct` in setup.txt), d₂ (fixed by `n=`, which is
                    # in both), and that an over-gate accept is recorded as
                    # such (`verdict=OVER-GATE`, and sldea_diag says so).
                    #
                    # PERCENTAGES ONLY, unchanged and load-bearing: a REFIT is
                    # one of the three answers, so the individual diameters
                    # and their average must stay hidden here or the refit is
                    # fitted against a disclosed target (review 2026-08-06). A
                    # percentage is not a number you can aim a click at. And
                    # default='cancel' is unchanged for the reason it was
                    # introduced — <Return> reaching an accept on this exact
                    # prompt is a demonstrated failure, not a hypothetical.
                    need = se.rounds_for_se(stats['sigma_pct'])
                    top = max(se.D2_RANGE_FACTORS)
                    # THE REMEDY STAYS, in one clause, and this is the one
                    # thing beyond the operator's three: it is a NUMBER, not a
                    # derivation, and it is what decides which of the three
                    # answers is right — "12 rounds would clear it" and "no
                    # runnable count clears it, change method" point at
                    # different buttons.
                    if need and need <= top:
                        remedy = (f"{need} rounds would meet the gate at "
                                  f"this σ.")
                    elif need:
                        remedy = (f"It would take {need} rounds — past the "
                                  f"{top} the d₂ table covers, so the remedy "
                                  f"is the other method, not more rounds.")
                    else:
                        remedy = ''
                    ans = ask(
                        "Rounds disagree",
                        f"σ = {stats['sigma_pct']:.2f} % of diameter  →  "
                        f"±{stats['area_se_pct']:.2f} % in area "
                        f"(budget ±{2 * se.CAL_SE_PCT:g} %).\n"
                        f"{remedy}\n\n"
                        # ONE LINE, and it has to STAY one line: the native
                        # message box wraps at about 70 characters whatever
                        # its longest line is, and a choice list that breaks
                        # mid-choice ("Cancel / = calibrate later") is exactly
                        # what a glanceable prompt cannot afford. Measured by
                        # rendering it, not guessed. Cancel carries no gloss
                        # for the same reason the operator's own sketch gave
                        # it none — the word is not ambiguous, and what the
                        # run is left in is on the status line afterwards.
                        f"Yes = refit all {stats['n']} rounds · "
                        f"No = accept as measured · Cancel",
                        default='cancel', three=True, icon='warning')
                    if ans is None:
                        log_set(stats, 'declined-cancel')
                        win.destroy()
                        return
                    if ans:
                        log_set(stats, 'declined-refit')
                        restart_all()
                        return
                say("cross-checking the average against the automatic disc "
                    "fit…")
                guard = se.anchor_guard(stats['mean'], auto_ref(),
                                        self.settings['diam_mm'])
                overridden = False
                if not guard['available']:
                    # The cross-check DID NOT RUN. Reached whenever
                    # _base_gray() refuses — most importantly on the
                    # fallback-frame path, where _anchor_frame() found a
                    # later frame precisely because the baseline row will
                    # not load, so the automatic fit can never run on this
                    # run. This used to accept in silence one line after
                    # announcing the cross-check, which reads as a check
                    # that passed (review 2026-08-06). An absent check is
                    # now as loud as a failed one, and it is recorded as a
                    # gap in setup.txt (se.anchor_guard_note).
                    say("⚠ NO automatic cross-check was possible — this "
                        "anchor is UNCHECKED")
                    if not ask(
                            "Anchor NOT cross-checked",
                            f"The mean of your {stats['n']} fits is "
                            f"{stats['mean']:.1f} px, and NOTHING checked "
                            f"it.\n\nThe automatic baseline disc fit is "
                            f"unavailable on this run (the baseline frame "
                            f"will not load, or the fit refused it), so "
                            f"neither reference could be applied: not the "
                            f"independent disc fit, and not the "
                            f"{self.settings['diam_mm']:g} mm mask's "
                            f"π·(d/2)² resting area. A P3_2-style "
                            f"systematic error — the stroke on the outer "
                            f"toe, the wrong feature encircled, the wrong "
                            f"diam_mm — would pass unnoticed here.\n\n"
                            f"Your fits agreeing says only that you "
                            f"are REPEATABLE, not that you are right."
                            + rescale_note(stats['mean'], None)
                            + f"\n\nUse this UNCHECKED anchor anyway?\n\n"
                              f"No = cancel (restore the baseline frame, "
                              f"or verify the anchor by eye on the "
                              f"contact sheet first).",
                            default='no', icon='warning'):
                        log_set(stats, 'declined-uncrosschecked', guard)
                        win.destroy()
                        return
                    overridden = True
                elif guard['warn']:
                    # the P3_2 case: 2.28% diameter / -4.42% area, INSIDE
                    # the old 3% cross-check, so it shipped silently and
                    # the run now carries a permanent caveat. This is the
                    # guard that would have caught it — twice.
                    lines = '\n'.join('• ' + w for w in guard['warn'])
                    if not ask(
                            "Anchor sanity check",
                            f"The accepted average ({stats['mean']:.1f} px) "
                            f"disagrees with a reference the app "
                            f"measured independently:\n\n{lines}\n\n"
                            f"The scale-anchor budget is ~0.4% diameter "
                            f"/ ~0.8% area (SLDEA_MEASUREMENT §2.1), so "
                            f"this is outside it. Common causes: the mark "
                            f"sat on the outer toe instead of the "
                            f"half-height, the wrong feature was "
                            f"measured, or diam_mm does not match this "
                            f"device's mask."
                            + rescale_note(stats['mean'],
                                           guard['auto_diam_px'])
                            + f"\n\nUse this anchor ANYWAY?\n\n"
                              f"No = recalibrate from round 1.",
                            default='no', icon='warning'):
                        st['disclosed'] = True
                        log_set(stats, 'declined-guard', guard)
                        restart_all()
                        return
                    overridden = True
                log_set(stats, ('accepted-override' if overridden
                                else 'accepted'), guard)
                accept(stats['mean'], frame_name, stats=stats,
                       guard=guard, overridden=overridden)

            def continue_key(_ev=None):
                """What <Return> does — and what it must NOT.

                It advances an intermediate round, and that is all. It
                cannot finish the calibration, so it can never reach the
                spread gate or the anchor guard, so it can never answer
                them (review 2026-08-06: with Enter bound to
                Continue/Finish and askyesno defaulting to YES, six Enter
                presses accepted an out-of-tolerance anchor). The last
                round needs the button; the modals default to declining."""
                if st['modal']:
                    return 'break'
                if verify():
                    # THE VERIFY MODE. The measured evidence says accepting the
                    # machine is the GOOD outcome, so ✔ Accept is the
                    # primary button and Tk draws it as the default one —
                    # but Enter still cannot reach it. An operator who
                    # arrives at this dialog and taps Enter out of habit
                    # would otherwise approve a scale they had not read, and
                    # "Accept is a judgement rather than a reflex" is the
                    # only thing standing between the verify mode and a
                    # rubber stamp.
                    #
                    # say_live, not live.config: the verify mode hides the
                    # live line to keep its budget, so the refusal has to
                    # bring the line back with it or it is refused silently.
                    say_live("⚠ Enter cannot approve an anchor — read the "
                             "numbers above, look at the circle, then click "
                             "the ✔ Accept button (or pick METHOD "
                             f"{se.CAL_MODE_LABELS[se.CAL_MODE_CIRCLE]}/"
                             f"{se.CAL_MODE_LABELS[se.CAL_MODE_TWOPOINT]} "
                             "above to measure it by hand instead)")
                    return 'break'
                if is_last_round():
                    say_live("⚠ the LAST round must be confirmed with the "
                             "✔ Finish calibration BUTTON — Enter cannot "
                             "accept an anchor, or answer the checks that "
                             "follow it")
                    return 'break'
                continue_round()
                return 'break'

            def round_diameter():
                """The current round's fitted diameter in ORIGINAL image
                px, or None when the round is not finished.
                The two-point mode measures in original coordinates by
                construction: st['pts'] holds the two clicks already mapped
                back through the inverse rotation, so the length here is the
                length on the frame as captured. A length is
                rotation-invariant, so a correct implementation would get the
                same number from the rotated coordinates — measuring in
                original space is what
                keeps the RECORDED click positions meaningful."""
                if two_point():
                    if len(st['pts']) < 2:
                        return None
                    return two_point_diameter(st['pts'][0], st['pts'][1])
                return 2.0 * st['circle'][2]

            def step(_ev=None):
                """What the PRIMARY button does — one command, dispatched on
                the mode, so the button cannot be wired to the wrong action
                after a mode switch."""
                if verify():
                    verify_accept()
                else:
                    continue_round()

            def continue_round(_ev=None):
                dpx = round_diameter()
                if dpx is None:
                    say_live("⚠ place BOTH edge points before "
                             "continuing — click one edge, then "
                             "the point opposite it")
                    return
                if not cal_diam_plausible(dpx, img.width, img.height,
                                          self.settings.get('roi_frac',
                                                            0.85)):
                    # a circle collapsed onto its own centre (or grown
                    # past the frame) is not a fit. The two-click dialog
                    # refused clicks under 10 px apart for the same
                    # reason: a nonsense anchor scales EVERY area.
                    if two_point():
                        # NUMBERLESS: the two-point mode shows no length
                        # anywhere before acceptance, and a refusal that
                        # printed one would be the one place the operator
                        # could read a figure off and carry it into the
                        # next round.
                        messagebox.showwarning(
                            "Calibrate",
                            "Those two points are too close together (or "
                            "too far apart) to be the resting disc — they "
                            "are outside the size range the automatic fit "
                            "accepts. Click the two OPPOSITE edges of the "
                            "shaded disc; a third click starts the pair "
                            "over.")
                    else:
                        messagebox.showwarning(
                            "Calibrate",
                            f"{dpx:.0f} px across cannot be the resting "
                            f"disc — it is outside the size range the "
                            f"automatic fit accepts too. Resize the circle "
                            f"onto the disc edge (drag a handle, or the "
                            f"wheel) before continuing.")
                    return
                st['diams'].append(dpx)
                if two_point():
                    # the angle this round was judged at, kept for the log:
                    # a round-set whose rotations turned out to cluster is
                    # a round-set whose rotation did less than it should
                    st['rots'].append(st['rot'])
                if len(st['diams']) >= max(rounds_wanted(), st['round']):
                    finish()
                    return
                st['round'] = len(st['diams']) + 1
                next_round()
                sync_buttons()
                repaint()

            def next_round():
                """Re-randomize for a fresh round: the circle mode respawns
                the circle somewhere else at some other size, the two-point
                mode rotates the display to the next stratified angle. Same
                purpose in both — n nudges of one fit are n correlated
                fits."""
                if two_point():
                    ang = (st['pending_rots'].pop(0)
                           if st['pending_rots']
                           else rotation_angles(1, rnd)[0])
                    set_rotation(ang)
                else:
                    respawn()

            def back_target():
                """The round ◀ Back would land on — the last BANKED round if
                there is one, else the round in progress."""
                return len(st['diams']) or 1

            def back_round(_ev=None):
                """◀ Back / Backspace — step ONE round backwards and
                re-randomise it.

                THE ANSWER TO THE MISCLICK (`#215`, operator 2026-08-06
                late). The two-point mode now banks a round on its second
                click, which removes the moment an operator could have
                noticed a bad click before it counted. So the round just
                banked has to be recoverable, and it is: this drops it and
                puts the operator back in it.

                ONE RULE, so it is predictable and repeatable — it always
                goes back one round. Mid-set that means the current round's
                clicks are discarded AND the previously banked diameter is
                dropped; on round 1, with nothing banked, it re-randomises
                round 1, which is what the old ↻ Redo did. Press it twice and
                you are two rounds back.

                Well defined at any point because the mean is not computed
                until the last round is in — nothing downstream has seen
                these numbers yet. The round comes back RE-RANDOMISED (a
                fresh rotation, a fresh spawn): a redo that restored the old
                view with the old clicks on it would be a correlated second
                look at one fit, which is exactly what the blind independent
                rounds exist to prevent. `st['rots']` therefore keeps the
                angles actually judged, so the log stays true.

                The discarded diameter is NOT logged. Only completed
                round-sets go to scale_calibration_log.txt (accepted or
                declined), and a redone round never completed one."""
                if verify():
                    return 'break'      # no rounds here to go back through
                if st['diams']:
                    st['diams'].pop()
                    if st['rots']:
                        st['rots'].pop()
                    st['round'] = len(st['diams']) + 1
                next_round()
                sync_buttons()
                repaint()
                return 'break'

            def prepare_verify():
                """The verify mode's setup: measure the display contrast
                window from the frame's OWN disc and paper levels, once —
                then frame the view on the fitted circle.

                No circle to spawn and no rotation to pick, because nothing is
                being fitted. `st['circle']` is left as whatever the circle
                mode last had (or None); every interaction that would touch it
                sits the verify mode out."""
                st['rimg'] = None
                st['pts'], st['ptsv'] = [], []
                st['stretch'], st['lut'] = None, None
                ref = auto_ref() or {}
                if ref.get('diam_px'):
                    try:
                        arr = np.asarray(img.convert('L'), float)
                        dl, pl = disc_paper_lum(arr, float(ref['cx']),
                                                float(ref['cy']),
                                                0.5 * float(ref['diam_px']))
                        # the fit measured the paper level with foil and
                        # glint already rejected; no annulus here can do
                        # that, so its number wins whenever the fit
                        # reported one
                        if ref.get('paper_lum') is not None:
                            pl = float(ref['paper_lum'])
                        win_lohi = cal_stretch_window(dl, pl)
                    except Exception as e:
                        # a stretch is a convenience; losing it must not cost
                        # the verification, and a silently RAW display is
                        # stated in the evidence block rather than pretended
                        # about
                        print(f"calibrate: contrast stretch unavailable: {e}")
                        win_lohi = None
                    if win_lohi:
                        st['stretch'] = win_lohi
                        st['lut'] = cal_stretch_lut(*win_lohi)
                # ALWAYS, and after the stretch rather than before: losing
                # the stretch must not also lose the framing, which is the
                # half of this the operator cannot work around by zooming.
                verify_view()

            def restart_all(_ev=None):
                """Start the round-set over. Also what a mode or round-count
                change does: half a circle set plus half a two-point set is
                not a measurement of either method."""
                st['mode'] = mode_var.get()
                st['n'] = rounds_wanted()
                st['round'], st['diams'] = 1, []
                st['rots'] = []
                if verify():
                    prepare_verify()
                elif two_point():
                    st['pending_rots'] = rotation_angles(st['n'], rnd)
                    # keep_zoom=False on the FIRST round only: the operator
                    # has not chosen a zoom yet, and a rotated frame is a
                    # different size from the one the view was fitted to
                    set_rotation(st['pending_rots'].pop(0), keep_zoom=False)
                else:
                    st['rimg'] = None
                    st['pts'], st['ptsv'] = [], []
                    respawn()
                sync_buttons()
                repaint()

            def set_rounds(_ev=None):
                restart_all()          # rounds_wanted() reads n_var itself

            def switch_mode(_ev=None):
                """Mode radio changed: adopt that mode's DEFAULT round
                count and start over. Adopting the default rather than keeping
                whatever was showing means the operator who just wants "the
                other method" gets the round count that method was designed
                around (3 for the circle, 5 for two-point) without having to
                know it. The verify
                mode has no rounds, so the menu keeps whatever manual count was
                showing and is DE-RENDERED instead (`#215`, operator
                2026-08-07) — setting it to '1' would read as "one round",
                which is not what the verify mode does, and greying it out
                still left a control to read on the top row."""
                if mode_var.get() != se.CAL_MODE_VERIFY:
                    n_var.set(str(se.CAL_MODE_ROUNDS.get(mode_var.get(),
                                                         se.CAL_ROUNDS)))
                restart_all()

            def reuse(_ev=None):
                if recorded:
                    # a reused anchor keeps ITS OWN provenance — the
                    # frame it was clicked on and whether that was the
                    # baseline, not this session's (review 2026-08-05).
                    # Its rounds/spread stay ITS record too: this session
                    # fitted nothing, so it must not claim a spread.
                    #
                    # Including its METHOD (`#215` the verify mode, 2026-08-06
                    # evening): hardcoding 'manual-calibration' here would
                    # silently relabel a reused auto-verified anchor as a
                    # HAND measurement, which is the one distinction the
                    # provenance field exists to keep — and it would then
                    # collect a vacuous cross-check tick at detect time.
                    meth = recorded.get('method')
                    if meth not in se.ANCHOR_METHODS:
                        meth = se.ANCHOR_METHOD_MANUAL
                    self.manual_ref = {
                        'method': meth,
                        'diam_px': float(recorded['diam_px']),
                        'frame': (recorded.get('anchor_frame', '')
                                  or frame_name),
                        'is_baseline': recorded.get('anchor_is_baseline',
                                                    anchor_is_baseline),
                        'reused': True}
                    for k in ('cal_mode', 'rounds_px', 'n_rounds',
                              'spread_px', 'spread_pct', 'sigma_pct',
                              'se_pct', 'fit_circ', 'fit_conf',
                              'fit_resid_px', 'fit_arc_cov', 'fit_n_edge',
                              'verified_by', 'verified_at', 'guard'):
                        if recorded.get(k) is not None:
                            self.manual_ref[k] = recorded[k]
                    dpx = float(recorded['diam_px'])
                    self.status.config(
                        text=f"scale REUSED from the recorded "
                             f"{meth} anchor: "
                             f"{self.settings['diam_mm']:g} mm = "
                             f"{dpx:.0f} px "
                             f"({self.settings['diam_mm'] / dpx:.5f} "
                             f"mm/px) — overrides every automatic "
                             f"reference at Save")
                    win.destroy()

            cont = tk.Button(btns, text='', command=step)
            cont.pack(side=tk.LEFT)
            # ✎ Measure by hand instead is GONE (operator 2026-08-06 late).
            # The radio row at the top already switches methods, so the button
            # was a second way to do one thing — and the verify mode's screen
            # is the one this branch has twice been told is too busy. The hand
            # measurement is not gone: the radios are now the only route to
            # it, which is why they say "measure BY HAND" rather than just
            # naming their gesture, and why their caption is bold.
            #
            # ◀ Back is the answer to the auto-advanced misclick: with the
            # second click banking the round there is no pause in which to
            # notice a bad one, so the round just banked has to be
            # recoverable. Labelled with the round it lands on and with its
            # key, because an undo nobody can find is not an undo.
            # THE ROUND CONTROLS, BOXED so they can be DE-RENDERED together
            # in the verify mode (`#215`, operator 2026-08-07, second pass).
            # Neither means anything where there are no rounds, and greyed out
            # they were still two buttons to read and to reach for — the
            # operator asked for them absent instead. Boxed rather than
            # forgotten individually so the row cannot come back in a
            # different order, and packed BEFORE the always-present widget on
            # its right (`round_after`) so re-showing lands them back between
            # the primary button and Reuse/Cancel.
            round_box = tk.Frame(btns)
            round_box.pack(side=tk.LEFT)
            back_btn = tk.Button(round_box, text="◀ Back",
                                 command=back_round)
            back_btn.pack(side=tk.LEFT, padx=6)
            restart_btn = tk.Button(round_box, text="⟲ Restart all rounds",
                                    command=restart_all)
            restart_btn.pack(side=tk.LEFT)
            reuse_btn = None
            if recorded:
                reuse_btn = tk.Button(btns,
                                      text="📏 Reuse recorded anchor (P)",
                                      command=reuse)
                reuse_btn.pack(side=tk.LEFT, padx=6)
            cancel_btn = tk.Button(btns, text="Cancel (Esc)",
                                   command=win.destroy)
            cancel_btn.pack(side=tk.RIGHT)
            ROUND_PACK = dict(side=tk.LEFT)
            round_after = reuse_btn if reuse_btn is not None else cancel_btn

            def sync_buttons():
                vfy = verify()
                # THE FOUR-LINE BUDGET (CAL_SCREEN_MAX_LINES), enforced here
                # because this is the one function every mode change goes
                # through (`#215` declutter 2026-08-06 late, extended to all
                # three modes 2026-08-07). In the verify mode the only text on
                # screen is the evidence block: the gate's warnings are either
                # impossible here or folded into its lines, the round header
                # has no rounds to report, and the live readout is empty until
                # it has something transient to say. In the MEASURING modes the
                # header and the live readout come back, the instruction is one
                # line, and the gate block appears only when a warning is
                # actually true.
                # `bool(gate)` as well as `not vfy` since the 2026-08-07 trim:
                # the block is warnings-only now, and an ordinary run has none
                # — so an empty label must not cost the picture a line's height
                # in the measuring modes either.
                show_line(gate_lbl, bool(gate) and not vfy, GATE_PACK,
                          chooser)
                show_line(hdr, not vfy, HDR_PACK, cv)
                # `live` BOTH WAYS, not just hidden in C: leaving it
                # forgotten on the way back to A/B hid the circle mode's
                # diameter readout, which is the one number a circle-mode round
                # needs (caught by rendering the dialog after a C→A switch).
                # Every write to it goes through say_live for the same reason.
                if vfy:
                    say_live('')
                else:
                    show_line(live, True, LIVE_PACK, btns)
                # give the canvas the height the verify mode's shorter text
                # frees up, and take it back for A/B (canvas_h). Before refit
                # runs — restart_all calls sync_buttons then repaint, and
                # repaint crops against view_h()
                want_h = canvas_h(vfy)
                if view_h() != want_h:
                    cv.config(height=want_h)
                    refit()
                # THE INTENT, ON THE BUTTON THAT COMMITS (`#215` fold). The
                # verify mode hides the gate block that states it in words, so
                # the button the operator actually presses has to carry it —
                # this is the one place the asymmetry between the two folded
                # actions is unmissable in every mode. Never a bare "Accept":
                # accepting means two different things now.
                if reanchoring:
                    accept_txt = ("✔ Accept fit & RE-ANCHOR NOW" if vfy else
                                  "✔ Finish & RE-ANCHOR NOW")
                else:
                    accept_txt = ("✔ Accept the automatic fit (at Save)"
                                  if vfy else
                                  "✔ Finish calibration (applied at Save)")
                cont.config(
                    text=(accept_txt if (vfy or is_last_round())
                          else "Continue →"),
                    # PRIMARY in the verify mode, because the measured evidence
                    # says accepting the machine is the good outcome — unlike
                    # the warning gates on this branch, whose safe default is
                    # to decline. Tk's `default='active'` draws the ring; it
                    # does NOT bind <Return>, which continue_key still refuses
                    # in the verify mode so that Accept stays a judgement.
                    default=('active' if vfy else 'normal'))
                # ◀ Back NAMES THE ROUND IT LANDS ON, so the undo is
                # discoverable without a paragraph explaining it: the label
                # itself says what pressing it does, and carries its key.
                back_btn.config(text=(f"◀ Back — redo round {back_target()} "
                                      f"(Backspace)"))
                # DE-RENDERED, not disabled, where there are no rounds
                # (`#215`, operator 2026-08-07). Both buttons keep state
                # 'normal' so that nothing is ever shown greyed: the mode
                # decides whether they EXIST, and back_round/restart_all sit
                # the verify mode out on their own anyway (fail-closed — a
                # Backspace keybinding is not a button and cannot be
                # unpacked).
                show_line(round_box, not vfy, ROUND_PACK, round_after)
                # ... and the two per-mode chooser controls. The round count
                # is meaningless in the verify mode; the stroke belongs to the
                # circle mode alone.
                #
                # HIDE STROKE, THEN SHOW ROUNDS, THEN SHOW STROKE — the order
                # is load-bearing. These two re-pack at the END of the
                # chooser's packing list (there is nothing to their right to
                # pack `before`), so packing the stroke box while the rounds
                # box is absent would leave them the wrong way round for good.
                # The stroke box is only ever wanted when the rounds box is,
                # so this sequence cannot invert them.
                want_stroke = (st['mode'] == se.CAL_MODE_CIRCLE)
                if not want_stroke:
                    show_line(stroke_box, False, STROKE_PACK)
                show_line(rounds_box, not vfy, ROUNDS_PACK)
                show_line(stroke_box, want_stroke, STROKE_PACK)
                if vfy:
                    win.title(
                        scale_intent_banner(intent)
                        + f" ({se.CAL_MODE_LABELS[se.CAL_MODE_VERIFY]})"
                          f" — verify the automatic fit on the resting disc")
                    how.config(text=verify_evidence(
                        auto_ref(), self.settings['diam_mm'],
                        recorded=recorded, n_px_rows=n_px_rows,
                        stretch=st['stretch'],
                        # the gate label is hidden in the verify mode, so its
                        # "the diameter was NOT recorded at capture"
                        # warning rides on the value line instead (in the
                        # measuring modes it is the gate block's own line,
                        # since `disc 16 mm` left the round header)
                        diam_recorded=diam_rec))
                    return
                what = ("fit the circle to the resting disc" if not
                        two_point() else
                        "click the two opposite edges of the resting disc")
                win.title(scale_intent_banner(intent)
                          + f" ({se.cal_mode_label(st['mode'])}) — {what} "
                            f"({st['round']} of "
                            f"{max(rounds_wanted(), st['round'])})")
                # THE IMMEDIATE INSTRUCTION, ONE LINE (`#215` trim,
                # 2026-08-07). Three lines became one: the gesture, and the
                # AIM RULE, which is the only instruction on this screen with
                # a measured cost behind it (§1.3 — the point a human picks is
                # the outer toe, +2.6 % in diameter, and that is the bias the
                # whole A/B exists to chase).
                #
                # THE AIM RULE IS NOW AN INSTRUCTION, NOT A DEFINITION
                # (`#215`, operator 2026-08-07, second pass). It read *"aim at
                # the ink edge's HALF-HEIGHT (mid-gray), never its outer
                # toe."* — which is the metrology convention, correctly named,
                # and is not something a hand can do. "Half-height of the
                # intensity step" describes a property of a profile; what the
                # operator actually does is place a mark so that it sits half
                # on the ink and half off it, and STRADDLE is the word for
                # that. So the screen says where to put the mark and
                # SLDEA_MEASUREMENT §1.3 keeps the convention it achieves —
                # the +5.2–5.7 % area / +2.6 % diameter band between the
                # half-height step and the visual outer toe is unchanged and
                # is still what the sentence is FOR.
                #
                # The mark differs per mode and the sentence names the one in
                # front of the operator: the circle mode's own stroke (3 px
                # solid by default, and the stroke chooser's whole point is
                # that this stroke is what lands on the boundary), the
                # two-point mode's hollow marker RING, which is centred on the
                # click and therefore straddles it by construction
                # (marker_shapes — nothing is drawn within CAL_MARK_GAP_VIEW
                # of the judged pixel, so the ring is the only thing there is
                # to aim).
                #
                # What came off, and where it is instead:
                #   the "METHOD C (two points)" / "METHOD B (circle)" prefix
                #       — the round header one line below says "Method C",
                #         and the radio row above it has the letter filled;
                #   the ROTATION's rationale ("it turns misjudging opposite
                #       from a fixed error into a random one") — and, since
                #       the second pass, the ANGLE itself: the picture is
                #       visibly rotated, so the header was printing a fact the
                #       operator can see. Both the reason and the number are
                #       in the record (SLDEA_MEASUREMENT §2.1a, this module's
                #       two-point section, and `rot=` on every log line);
                #   "that SECOND CLICK BANKS THE ROUND and moves on" — the
                #       LIVE line says it per click, which is where it is
                #       true, and ◀ Back's own label carries Backspace;
                #   the KEY CATALOGUE (wheel/arrow nudges, Ctrl+wheel, F, Z,
                #       Esc) — a catalogue is reference material. The two
                #       keys that change a MEASUREMENT are named where they
                #       are needed: Z by the live line's own sub-1:1 warning,
                #       Backspace on the ◀ Back button. The rest is in
                #       _calibrate_scale's docstring and SLDEA_HANDOFF.md.
                how.config(text=(
                    "Click one edge, then the point OPPOSITE it — straddle "
                    "the edge: half the ring on the disc, half on the paper."
                    if two_point() else
                    "Drag to move · a handle to resize — straddle the edge: "
                    "half the stroke on the disc, half on the paper."))

            def place_point(rx, ry):
                """Record one twopoint-mode click. `rx, ry` are ROTATED display
                image px; what gets STORED and measured is the point mapped
                back to ORIGINAL image px.

                A click whose original-space position falls outside the
                frame is refused: the expanded rotation canvas has
                background-filled corners, and a click there is not a point
                on the disc."""
                _im, rw, rh = disp()
                ox, oy = unrotate_point(rx, ry, rw, rh,
                                        img.width, img.height, st['rot'])
                if not (0.0 <= ox <= img.width and 0.0 <= oy <= img.height):
                    say_live("⚠ that click is off the frame (the "
                             "rotated view has empty corners) — "
                             "click on the disc edge itself")
                    return
                if len(st['pts']) >= 2:
                    st['pts'], st['ptsv'] = [], []   # a 3rd click restarts
                st['pts'].append((ox, oy))
                st['ptsv'].append((float(rx), float(ry)))
                repaint()
                # ---- AUTO-ADVANCE (operator 2026-08-06 late) -------------
                # The second point BANKS the round and moves to the next one.
                # No Continue press: the operator asked for it, and the press
                # was pure ceremony — nothing happens between placing point
                # two and pressing Continue except the press.
                #
                # NOT on the last round, deliberately. There is no "next
                # round" to advance to there; what follows instead is
                # finish(), i.e. the SE gate, the anchor guard and an anchor.
                # Auto-advancing into that would let one stray click accept a
                # scale and then meet warning modals it never read — the same
                # hazard `continue_key` refuses <Return> for. So the last
                # round keeps its ✔ Finish button, which is also the one
                # moment auto-advance takes away: the pause in which a bad
                # click can be noticed. Everywhere else that pause is ◀ Back.
                if len(st['pts']) == 2 and not is_last_round():
                    continue_round()

            def press(ev):
                # THE VERIFY MODE: the displayed circle is the MACHINE's
                # measurement. Nothing the operator does with the mouse may
                # move it — the whole point is that they judge a fixed number,
                # and a draggable circle would turn the verify mode back into
                # the circle mode with a head start.
                if verify():
                    return
                if two_point():
                    place_point(*vt.to_image(ev.x, ev.y))
                    return
                ccx, ccy, r = st['circle']
                # hit-test in VIEW px: a handle must stay the same
                # physical size to the hand at every zoom
                vx, vy = vt.to_view(ccx, ccy)
                what = hit_test_circle(vx, vy, r * vt.zoom, ev.x, ev.y)
                if what is None:
                    st['grab'] = None
                    return
                ix, iy = vt.to_image(ev.x, ev.y)
                st['grab'] = (what, ix - ccx, iy - ccy)

            def drag(ev):
                # the two-point mode never sets a grab, so a drag there is a
                # no-op — a click-and-wobble must not move a placed point
                if not st['grab']:
                    return
                what, offx, offy = st['grab']
                ix, iy = vt.to_image(ev.x, ev.y)
                ccx, ccy, r = st['circle']
                if what == 'move':
                    set_circle(ix - offx, iy - offy, r)
                else:
                    set_circle(ccx, ccy,
                               resize_radius(ccx, ccy, ix, iy))
                repaint()

            def release(_ev):
                st['grab'] = None

            def wheel(vx, vy, steps, ctrl=False, shift=False):
                # In the circle mode the plain wheel is the FINE RESIZE and
                # zoom is on Ctrl, so the wheel cannot fight the sizing
                # gesture. In modes B and C there is nothing to resize, so the
                # plain wheel does the obvious thing and zooms — and in the
                # verify mode zooming is the ONLY gesture, because inspecting
                # the edge closely is the whole job.
                if ctrl or two_point() or verify():
                    vt.zoom_at(vx, vy, 1.15 ** steps)
                else:
                    ccx, ccy, r = st['circle']
                    set_circle(ccx, ccy, r + cal_wheel_dr(steps, shift))
                repaint()

            def key_nudge(ev):
                shift = bool(ev.state & 0x0001)
                if verify():
                    return 'break'      # nothing here is the operator's to
                    #                     nudge (see press)
                if two_point():
                    # arrows nudge the LAST placed point, in the rotated
                    # display frame the operator is looking at — one screen
                    # px, whichever way that points in the original
                    d = cal_key_delta(ev.keysym, False)
                    if d is None or not st['ptsv']:
                        return
                    step = (CAL_PT_NUDGE_COARSE_PX if shift
                            else CAL_PT_NUDGE_PX)
                    rx, ry = st['ptsv'][-1]
                    st['pts'].pop()
                    st['ptsv'].pop()
                    place_point(rx + d[0] * step, ry + d[1] * step)
                    return 'break'
                d = cal_key_delta(ev.keysym, shift)
                if d is None:
                    return
                ccx, ccy, r = st['circle']
                set_circle(ccx + d[0], ccy + d[1], r + d[2])
                repaint()
                return 'break'

            def one_to_one(_ev=None):
                """Zoom to at least 1:1 centred on the fit — the fixed 0.41x
                preview was itself an audit finding. The two-point
                mode centres on the last placed point, or on the frame centre
                before any point is placed; the verify mode centres on the
                automatic fit,
                which
                is the thing being inspected."""
                _im, w, h = disp()
                if verify():
                    ref = auto_ref() or {}
                    ccx, ccy = (float(ref.get('cx', w / 2.0)),
                                float(ref.get('cy', h / 2.0)))
                elif two_point():
                    ccx, ccy = (st['ptsv'][-1] if st['ptsv']
                                else (w / 2.0, h / 2.0))
                else:
                    ccx, ccy = st['circle'][0], st['circle'][1]
                vt.zoom = max(1.0, vt.zoom)
                vt.ox = ccx - cw / (2.0 * vt.zoom)
                vt.oy = ccy - view_h() / (2.0 * vt.zoom)
                repaint()

            def pan_start(ev):
                st['pan'] = (ev.x, ev.y)

            def pan_move(ev):
                if st['pan'] is None:
                    return
                dx, dy = ev.x - st['pan'][0], ev.y - st['pan'][1]
                st['pan'] = (ev.x, ev.y)
                vt.pan_view(dx, dy)
                repaint()

            cv.bind('<Button-1>', press)
            cv.bind('<B1-Motion>', drag)
            cv.bind('<ButtonRelease-1>', release)
            cv.bind('<MouseWheel>',
                    lambda e: wheel(e.x, e.y, e.delta / 120.0,
                                    bool(e.state & 0x0004),
                                    bool(e.state & 0x0001)))
            cv.bind('<Button-4>', lambda e: wheel(
                e.x, e.y, 1, bool(e.state & 0x0004),
                bool(e.state & 0x0001)))
            cv.bind('<Button-5>', lambda e: wheel(
                e.x, e.y, -1, bool(e.state & 0x0004),
                bool(e.state & 0x0001)))
            cv.bind('<Button-3>', pan_start)
            cv.bind('<B3-Motion>', pan_move)
            for k in ('<Key-f>', '<Key-F>'):
                # disp(), not img: in the two-point mode the view is fitted to
                # the ROTATED canvas, which is bigger and a different shape
                win.bind(k, lambda e: (fit_view(), repaint()))
            win.bind('<Key-z>', one_to_one)
            win.bind('<Key-Z>', one_to_one)
            for k in ('<Left>', '<Right>', '<Up>', '<Down>',
                      '<Shift-Left>', '<Shift-Right>', '<Shift-Up>',
                      '<Shift-Down>'):
                win.bind(k, key_nudge)
            # NOT continue_round: Enter must not be able to finish, and
            # `ask` unbinds this for the duration of every modal warning
            win.bind('<Return>', continue_key)
            # THE UNDO'S KEY. Backspace is where a hand already goes to take
            # back the last thing it did, and with the two-point mode banking
            # a round on its second click there has to be a key for it — the
            # operator's hand is on the mouse and the misclick has just
            # happened. Bound on the window, so it works with the canvas
            # focused; harmless in the verify mode, where back_round returns
            # immediately (there are no rounds to step through).
            # ONE key, the one the button names: an undo bound to keys nobody
            # was told about is how a round disappears unexplained.
            win.bind('<BackSpace>', back_round)
            if recorded:
                win.bind('<Key-p>', reuse)
                win.bind('<Key-P>', reuse)
            win.bind('<Escape>', lambda e: win.destroy())
            # n_var carries the chosen mode's DEFAULT round count (3 for
            # the circle, 5 for two-point); restart_all() reads it back and
            # opens round 1 in that mode
            n_var.set(str(se.CAL_MODE_ROUNDS.get(mode_var.get(),
                                                 se.CAL_ROUNDS)))
            restart_all()
            cv.focus_set()
            self._cal_win = win
            # TEST SEAM, published only while the dialog is alive (like
            # _cal_win above). A test that wants to drive the two-point mode
            # has to click at VIEW coordinates, which means it needs the
            # dialog's OWN view transform and its own rotated canvas —
            # computing them a second time in the test would test the
            # re-derivation instead of the dialog. Nothing in the app reads
            # this.
            self._cal_probe = {'st': st, 'vt': vt, 'canvas': cv,
                               'disp': disp, 'mode_var': mode_var,
                               'n_var': n_var, 'stroke_var': stroke_var,
                               # verify: the evidence block and the two
                               # buttons whose enablement IS the mode
                               'how': how, 'step_btn': cont,
                               # the undo, and the intent this dialog serves —
                               # both are behaviour a test has to be able to
                               # read without re-deriving it
                               'back_btn': back_btn, 'intent': intent,
                               'restart_btn': restart_btn,
                               # the four boxes that are DE-RENDERED rather
                               # than disabled where they do not apply
                               # (`#215`, operator 2026-08-07): the budget
                               # test reads winfo_manager() on these, because
                               # "absent" is the claim now and a disabled
                               # widget would still satisfy an existence check
                               'round_box': round_box,
                               'rounds_box': rounds_box,
                               'stroke_box': stroke_box,
                               'n_menu': n_menu, 'stroke_menu': stroke_menu}
            win.grab_set()
            self.root.wait_window(win)
        finally:
            self._cal_win = None
            self._cal_probe = None
            try:
                if win.winfo_exists():
                    win.destroy()
            except tk.TclError:
                pass
        if then_detect:
            if self.manual_ref is not None:
                self.detect()
            else:
                self._gate_status()

    # ---------------- scale-only re-anchor (`#215`) ----------------
    def _reanchor_scale(self):
        """📏 RE-ANCHOR — correct this run's px→mm scale and re-derive every
        recorded area from the pixel measurements ALREADY in data.csv, with
        NO detection and NO re-review.

        NO LONGER ITS OWN BUTTON (operator 2026-08-06 late, `#215`). This is
        one of the two things the single 📏 entry point does, chosen by
        `_scale_intent`: a saved run with px measurements and no open review
        pass lands here. It keeps its own refusals regardless — the routing is
        not treated as a guarantee.

        Its confirmation is THREE-WAY since the fold. As a dedicated button,
        declining meant "I have changed my mind" and the measurement was
        rightly thrown away; as the only 📏 route on a saved run, that would
        strand an operator who wants an anchor in order to re-Detect. So YES
        commits, NO keeps the anchor for the next Save without writing
        anything, and CANCEL discards it.

        Why it exists (`#215`, 2026-08-06). The corpus-wide sweep
        (`_analysis/auto_calibration_sweep_20260806.md`) found three runs whose
        absolute areas are wrong purely because a human mis-calibrated the
        scale — P3_2_2.5mL_20260728 by −4.42 % in area, SLDEA_20260723_152205
        by −3.38 %, SLDEA_20260723_233451 by +2.44 %. Their PIXEL measurements
        are correct; only the factor is wrong. Correcting one used to cost a
        full detect-and-save cycle (minutes of detection over 81 frames) even
        though no review work needed redoing, and an operator who accepted the
        corrected fit on live P3_2 closed before Save because of that cost —
        the correction was lost. Eight further runs carry no anchor at all and
        are one re-save away from acquiring a fresh error, so the friction
        would have recurred.

        SCALE-ONLY, and that is enforced by what is NOT called rather than by
        intent. `apply_results(rows, {}, scale, {}, None)` is the whole
        commit: with an empty results dict every row takes the unreviewed
        branch, which is the rule the [critical] partial-re-save entry put in
        force (SLDEA_HANDOFF 2026-08-05) — keep the px, RE-DERIVE mm²/diam at
        this scale, and blank a bug-era mm² that has no px rather than keep it
        on an unknowable anchor. That branch reads each row's own `notes` back
        unchanged and touches no other column, and because
        `plan_breakdown_marks` / `apply_rename_plan` are never reached, a
        `*_BREAKDOWN` rename can be neither re-applied nor reverted. No
        arithmetic is reimplemented here; `se.mm_per_px` derives the scale
        exactly as Save does.

        The new scale is measured or verified through the EXISTING
        calibration dialog, unchanged — the same A/B/C chooser, the same
        gates, the same log line — so a re-anchor is held to the same
        standard as a first calibration. The dialog is told which intent it
        serves (SCALE_INTENT_REANCHOR), which changes only what it is TITLED
        and what its accept button SAYS: one of the two folded actions writes
        data.csv the moment it is confirmed and the other does not, and an
        operator must not have to remember which one they are in.

        Refuses rather than guesses in three states, all of them cases where
        one button would otherwise rewrite a whole run's absolute column on a
        false premise: nothing to re-derive (no row carries px), a detect
        worker in flight, and an UNSAVED review in memory. The last one is the
        [critical] mixed-scale bug's own shape — committing a scale while a
        half-finished review sits in `self.results` would put this write and a
        later Save's write on either side of the same column."""
        if not self.run:
            messagebox.showinfo("Re-anchor scale", "Pick a run first")
            return
        if self._detect_busy:
            messagebox.showinfo(
                "Re-anchor scale",
                "A detection pass is running. Re-anchoring rewrites "
                "data.csv, so it waits until the worker has finished.")
            return
        if self._cal_win is not None and self._cal_win.winfo_exists():
            # The gate dialog is a singleton, so _calibrate_scale() would
            # LIFT the open one and return without waiting — and this method
            # would then read manual_ref as a cancel. Harmless but confusing
            # (a "cancelled" status while a calibration is visibly open), so
            # it is refused where the operator can see why.
            self._cal_win.lift()
            self._cal_win.focus_set()
            messagebox.showinfo(
                "Re-anchor scale",
                "The calibration dialog is already open. Finish or cancel "
                "it first — a re-anchor drives that same dialog.")
            return
        # An unsaved review means two writers for one column. Refused, not
        # merged: the operator can Save (which applies a new anchor to the
        # whole column anyway, so a re-anchor is redundant then) or re-pick
        # the run to drop the pass.
        # THE REFUSAL SURVIVES THE FOLD, independently. `_scale_intent`
        # already routes a dirty run to a plain calibration, so in the normal
        # flow this is unreachable — which is exactly why it stays: folding two
        # buttons must not be able to turn a refusal into a silent commit, and
        # a future caller reaching _reanchor_scale directly gets the refusal
        # rather than the [critical] mixed-scale bug.
        dirty = self._review_dirty()
        if dirty:
            messagebox.showwarning(
                "Re-anchor scale",
                "This run has UNSAVED review work in memory ("
                + ', '.join(dirty) + ").\n\nRe-anchor is a scale-only "
                "correction of what is already in data.csv, so it refuses "
                "to write while a review pass is open — the two writes "
                "would land on either side of the same mm² column.\n\n"
                "Either 💾 Save the pass (a Save re-scales the whole "
                "column at the new anchor anyway, so no re-anchor is "
                "needed), or re-pick the run in the Run box to drop it.")
            return
        rows = self.run['rows']
        dmm = self.settings['diam_mm']
        # counts BEFORE the dialog opens: refusing after making the operator
        # measure a disc would waste exactly the work this action saves
        probe = se.reanchor_plan(rows, None, dmm)
        if not probe['n_derive']:
            messagebox.showerror(
                "Re-anchor scale",
                f"NOTHING TO RE-DERIVE — no row in this run carries an "
                f"active_area_px measurement, so there are no pixel areas "
                f"to convert at a corrected scale.\n\n"
                f"Re-anchor only fixes the px→mm factor of a run that has "
                f"already been measured. This run has not been: press "
                f"▶ Detect Edges (it opens 📏 Calibrate / re-anchor "
                f"first — Detect is gated on it) and then 💾 Save.\n\n"
                f"({probe['n_rows']} row(s) scanned"
                + (f"; {probe['n_blank']} carry an mm² with no px, which a "
                   f"re-anchor could only blank" if probe['n_blank'] else '')
                + ")")
            return
        try:
            prev = se.load_scale_anchor(self.rundir)
        except OSError:
            prev = None
        # ---- the new scale, through the EXISTING dialog, unchanged -------
        # manual_ref is cleared so a Cancel is distinguishable from an
        # accept, and restored on every path that does not commit: cancelling
        # a re-anchor must leave the session's gate state exactly as it was,
        # including leaving Detect gated on a run that had no anchor.
        was = self.manual_ref
        self.manual_ref = None
        self._calibrate_scale(intent=SCALE_INTENT_REANCHOR)
        new_ref = self.manual_ref
        if new_ref is None:
            self.manual_ref = was
            self.status.config(text="re-anchor cancelled — data.csv "
                                    "untouched")
            return
        # the SAME derivation Save performs, on an empty results dict: a
        # human-signed anchor beats every automatic reference, so this is
        # diam_mm / new_ref['diam_px'] — but routed through mm_per_px so the
        # two paths can never drift apart
        scale = se.mm_per_px({}, rows, self.settings, baseline_ref=new_ref)
        if not scale:
            self.manual_ref = was
            messagebox.showerror(
                "Re-anchor scale",
                "The accepted anchor did not yield a usable mm/px scale, "
                "so nothing was written.")
            return
        plan = se.reanchor_plan(rows, scale, dmm, recorded=prev)
        # THREE WAYS OUT, since the fold (`#215`, 2026-08-06 late). While
        # 📏 Re-anchor was its own button, declining it correctly threw the
        # measurement away — the operator had asked for a commit and changed
        # their mind. Now that this is the ONLY 📏 route on a saved run, a
        # two-way question would dead-end it: an operator who wants an anchor
        # so they can re-Detect a frame would measure the disc, decline the
        # commit, and find the anchor gone and Detect still gated.
        #
        # So the question names both non-writing outcomes as well as the
        # write, which also makes the fold's asymmetry explicit in the one
        # place it matters most:
        #   YES    commit now — every mm² in data.csv re-derived
        #   NO     keep the anchor for the next Save; nothing written now
        #   CANCEL throw the measurement away; the run is untouched
        # default='cancel', the option that changes nothing, keeping this
        # branch's rule that a warning gate's Enter must not act.
        ans = messagebox.askyesnocancel(
            "Re-anchor scale — SCALE ONLY",
            self._reanchor_msg(plan, prev, new_ref),
            default='cancel', icon='warning')
        if ans is None:
            self.manual_ref = was
            self.status.config(text="re-anchor cancelled — the measured "
                                    "anchor was discarded and data.csv is "
                                    "untouched")
            return
        if not ans:
            # KEPT, not committed: manual_ref stays as the dialog left it, so
            # the anchor gates Detect open and the next Save applies it to the
            # whole column (which is the same rewrite, later, under a review
            # pass the operator will have seen).
            self.status.config(
                text=f"scale accepted but NOT committed: "
                     f"{new_ref['diam_px']:.1f} px is held for this session "
                     f"and applied at the next 💾 Save — data.csv is "
                     f"untouched, and no areas have changed yet")
            return
        # ---- commit, atomically in memory as well as on disk -------------
        # apply_results mutates the rows in place, and write_back can fail
        # AFTER it (data.csv open in Excel is the everyday case). Without
        # this snapshot a failed re-anchor would leave the in-memory column
        # at the new scale while the disk held the old, and the next
        # attempt's confirmation would report a ×1.000 multiplier against
        # numbers the operator never agreed to. Restored per-row rather than
        # by rebinding the list so nothing holding a row reference sees a
        # stale dict.
        snap = [dict(r) for r in rows]
        cols = list(self.run['columns'])
        try:
            se.apply_results(rows, {}, scale, {}, None)
            se.write_back(self.rundir, self.run)
        except Exception as e:
            for row, old in zip(rows, snap):
                row.clear()
                row.update(old)
            self.run['columns'] = cols
            self.manual_ref = was
            csv_path = self.run.get('csv_path') or ''
            has_bak = csv_path and os.path.exists(csv_path + '.bak')
            messagebox.showerror(
                "Re-anchor FAILED",
                f"Writing the re-derived areas failed:\n\n{e}\n\nNOTHING "
                f"was changed — the run is exactly as it was, in memory "
                f"and on disk, and no frame files were touched. If "
                f"data.csv is open in Excel, close it and try again."
                + (f"\nAn earlier pre-save backup is at data.csv.bak "
                   f"(from a previous write, not this one)."
                   if has_bak else ""))
            return
        # ---- provenance: this run must NOT end up looking re-reviewed ----
        anchor = self._anchor_record(new_ref, scale)
        if not anchor.get('auto_diam_px'):
            # base_ref is a DETECT-time reference and a re-anchor never
            # detects, so it is normally None here — which would drop the
            # automatic fit out of the record on exactly the writes that
            # exist because a manual anchor disagreed with it. Asked for
            # directly instead (se.baseline_disc is cached, so the dialog
            # already warmed it), and never allowed to raise: a missing
            # cross-check number must not cost the correction.
            anchor['auto_diam_px'] = (self._auto_disc() or {}).get('diam_px')
        anchor.update(se.reanchor_anchor_fields(prev, plan))
        try:
            se.save_scale_anchor(self.rundir, anchor)
        except OSError as e:
            self.status.config(
                text=f"areas re-derived, but recording the re-anchor in "
                     f"setup.txt failed: {e}")
        try:
            _p, line = se.append_calibration_log(
                self.rundir, se.reanchor_log_record(anchor, plan))
            print(line)
        except Exception as e:
            print(f"re-anchor: logging the correction failed: {e}")
        old_txt = (f"{plan['old_diam_px']:.1f}" if plan['old_diam_px']
                   else '?')
        rest = ''
        # nominal_mm2 in the condition as well as the text: it is None for a
        # non-positive diam_mm, and so are the deviations — a bare
        # {None:+.2f} here would raise AFTER the commit, turning a completed
        # correction into a traceback
        if (plan['rest_after'] is not None and plan['rest_before'] is not None
                and plan['nominal_mm2']):
            rest = (f"; resting {plan['rest_before']:.2f} → "
                    f"{plan['rest_after']:.2f} mm² "
                    f"({plan['rest_dev_after']:+.2f}% from "
                    f"{plan['nominal_mm2']:.2f})")
        self.status.config(
            text=f"RE-ANCHORED (scale only, no re-review): {old_txt} → "
                 f"{new_ref['diam_px']:.1f} px, {plan['n_derive']} row(s) "
                 f"re-derived"
                 + (f", {plan['n_blank']} blanked" if plan['n_blank'] else '')
                 + (f", every area ×{plan['mult']:.4f}" if plan['mult']
                    else '')
                 + rest)

    def _reanchor_msg(self, plan, prev, new_ref):
        """The re-anchor confirmation, WITH NUMBERS.

        **IT OPENS BY ASKING WHETHER TO OVERWRITE THE CALIBRATION ON RECORD**
        (`#215`, operator 2026-08-07, second pass). That question used to be a
        standing row at the top of the calibration dialog —
        *"⚠ 81 row(s) already carry px — accepting RE-SCALES every recorded
        mm² at the next 💾 Save…"* — where it stood above the picture through
        every round of a measurement it could not affect. It belongs at the
        moment it is incurred, which is this button, and the operator's
        reasoning for the shorter wording is the right one: once you have said
        *overwrite the existing calibration*, that every area is re-derived
        follows from what overwriting a scale MEANS and does not need spelling
        out. So the prose went and the EVIDENCE stayed.

        One button here rewrites every absolute area in the run, so the
        dialog has to be sanity-checkable on its own: the counts on both
        sides of the [critical] blank-vs-re-derive rule, both anchor
        diameters, the multiplier every area is about to be multiplied by,
        and the resting area before → after with its deviation from
        π·(diam_mm/2)² on BOTH sides. That last pair is the check that
        actually catches a wrong answer — re-anchoring to a run's own
        automatic fit forces its resting area onto π·(diam_mm/2)², so an
        'after' that does not land there means the anchor is not the fit.

        Rows that would BLANK are reported here, before the commit, not
        after: a bug-era mm² with no px cannot be re-derived and is dropped
        rather than kept on an unknowable anchor, and that is a deletion the
        operator has to agree to in advance.

        The three-way choice is unchanged and so are its glosses: they are
        not prose about a consequence, they are what the three buttons DO,
        and two of the three do not write."""
        nom = plan['nominal_mm2']
        dmm = self.settings['diam_mm']
        old_px = plan['old_diam_px']
        new_px = float(new_ref['diam_px'])
        # THE LEAD, and it branches on the truth. On a run that carries an
        # anchor this is an overwrite and is named as one; on a pre-gate run
        # (P3_6_2.5mL_20260729, DOT_P3_1_20260729 — px rows, no anchor block)
        # there is nothing to overwrite, and claiming otherwise would be a
        # question about a record that does not exist.
        if prev and prev.get('diam_px'):
            head = ("This run ALREADY HAS A CALIBRATION on record"
                    + (f" ({prev.get('method')}"
                       + (f", {se.cal_mode_text(prev['cal_mode'])}"
                          if prev.get('cal_mode') else '')
                       + (f", saved {prev['saved']}" if prev.get('saved')
                          else '')
                       + ")" if prev.get('method') else '')
                    + ".\n\nOVERWRITE it with the anchor you just measured?")
        else:
            head = ("This run has NO calibration on record (a pre-gate "
                    "save).\n\nWRITE the anchor you just measured, and "
                    "derive this run's areas from it?")
        # ONE LINE for what YES does, where there were five. What is kept is
        # the SCOPE — that this is SCALE ONLY, that no detection runs and
        # nothing is re-reviewed, and that only the derived columns move.
        # That is not the consequence of overwriting a scale (which is
        # self-explanatory and went); it is the premise of the whole action,
        # and an operator who assumed a re-anchor re-detects would decline it
        # for the wrong reason. What went with the prose is the enumeration
        # (notes / tags / snapshots / current / voltage / frame names), which
        # "only the mm² and diameter columns" says in six words.
        L = [head,
             "",
             "⚠ YES WRITES data.csv NOW — SCALE ONLY: no detection runs, "
             "nothing is re-reviewed, and only the mm² and diameter columns "
             "change (frame names, notes and tags are not touched).",
             "NO = keep this anchor for the session and apply it at the next "
             "💾 Save instead — nothing is written now.",
             "CANCEL = discard the measurement; the run stays exactly as it "
             "is.",
             ""]
        L.append(f"  anchor       {(f'{old_px:.2f} px' if old_px else '?')}"
                 f"  →  {new_px:.2f} px          ({dmm:g} mm disc)")
        if plan['old_scale']:
            L.append(f"  scale        {plan['old_scale']:.6f}  →  "
                     f"{plan['new_scale']:.6f} mm/px")
        if plan['mult']:
            L.append(f"  MULTIPLIER   every area × {plan['mult']:.6f}   "
                     f"({100 * (plan['mult'] - 1):+.2f}%)")
        else:
            L.append("  MULTIPLIER   UNKNOWN — no previous scale could be "
                     "recovered from this run's own numbers, so there is no "
                     "factor to quote. Every mm² is derived fresh.")
        L += ["",
              f"  rows re-derived from px   {plan['n_derive']} of "
              f"{plan['n_rows']}"]
        if plan['n_fresh']:
            L.append(f"  rows gaining an mm² now   {plan['n_fresh']}  "
                     f"(px present, no previous mm²)")
        # stated whether or not it is zero: "0 rows will be blanked" is the
        # reassurance, and its absence would be indistinguishable from the
        # line not existing
        L.append(f"  rows BLANKED              {plan['n_blank']}"
                 + ("   ⚠ an mm² with NO px cannot be re-derived — it is "
                    "dropped, not kept on an unknowable anchor"
                    if plan['n_blank'] else ''))
        if plan['n_untouched']:
            L.append(f"  rows untouched            "
                     f"{plan['n_untouched']}  (no px, no mm²)")
        # `nom` in the condition, not only in the text: with a non-positive
        # diam_mm there is no mask area to judge against, and the deviation
        # figures are None — which would formatter-crash mid-dialog, the
        # exact failure class the 2026-08-05 audit found bricking the gate
        if (plan['rest_before'] is not None and plan['rest_after'] is not None
                and nom):
            which = ("baseline row" if plan['rest_is_baseline']
                     else f"row {plan['rest_row']} — NOT the baseline row")
            L += ["",
                  f"  resting area ({which}), against π·({dmm:g}/2)² = "
                  f"{nom:.2f} mm²:",
                  f"     before   {plan['rest_before']:>8.3f} mm²   "
                  f"({plan['rest_dev_before']:+.2f}%)",
                  f"     after    {plan['rest_after']:>8.3f} mm²   "
                  f"({plan['rest_dev_after']:+.2f}%)"]
            if abs(plan['rest_dev_after']) > 1.0:
                L.append("     ⚠ the corrected resting area is still more "
                         "than 1% from the mask anchor. Re-anchoring to "
                         "this run's own automatic fit lands it on "
                         "π·(d/2)² by construction, so this anchor is NOT "
                         "that fit — check the method before committing.")
        elif plan['rest_before'] is None:
            L += ["",
                  "  ⚠ no resting area is recorded (no row tagged "
                  "'baseline' carries a px measurement), so the one check "
                  "that can catch a wrong anchor is UNAVAILABLE here."]
        if plan['mixed']:
            L += ["",
                  f"  ⚠ THIS COLUMN ALREADY HOLDS MORE THAN ONE SCALE: the "
                  f"{plan['n_scales']} measured rows imply scales spanning "
                  f"{plan['scale_span_pct']:.2f}% in area. That is the "
                  f"partial-re-save state (SLDEA_HANDOFF 2026-08-05, "
                  f"[critical]). Re-anchoring FIXES it — every row is "
                  f"re-derived from px at one scale — but the multiplier "
                  f"above is quoted against the resting row's scale and "
                  f"does not describe the others."]
        if plan['anchor_matches_data'] is False:
            L += ["",
                  f"  ⚠ the anchor recorded in setup.txt "
                  f"({plan['recorded_diam_px']:.2f} px) is NOT the scale "
                  f"this column was actually derived at "
                  f"({old_px:.2f} px implied by the data). The DATA is "
                  f"what gets re-derived, so the multiplier follows the "
                  f"data, not the block."]
        if prev is None:
            # the pre-gate case is already named in the lead, so what is left
            # to say here is only where the "before" numbers above came from
            L += ["",
                  "  ⚠ The previous scale above is the one implied by the "
                  "run's own mm²/px, not a recorded anchor — there is none."]
        if plan['mult'] and abs(plan['mult'] - 1.0) < 1e-6:
            L += ["",
                  "  Note: this anchor is the one already in force, so no "
                  "area changes measurably. The write still records the "
                  "anchor and its provenance."]
        L += ["",
              "A backup is kept as data.csv.bak. Expansion ratios A/A₀ are "
              "unaffected — a uniform scale factor cancels exactly in a "
              "ratio."]
        # THE ONE STALE ARTIFACT, disclosed. Save draws
        # area_vs_voltage.png from the SESSION's accepted results, and a
        # re-anchor has none by definition — so the plot cannot be
        # regenerated here and would keep showing the old absolute mm² with
        # nothing on it saying so. Named rather than deleted: it is a saved
        # artifact, and silently removing one is worse than a stale one that
        # the operator has been told about. (The outlines in overlays/ are
        # px contours and carry no scale, so they stay correct; re-running
        # sldea_diag picks the new anchor up and reports the re-anchor.)
        try:
            if os.path.exists(os.path.join(self.rundir,
                                           'area_vs_voltage.png')):
                L += ["",
                      "  ⚠ area_vs_voltage.png is NOT regenerated — it is "
                      "drawn from a review pass and there is none here, so "
                      "it will keep showing the OLD absolute areas until the "
                      "next Save. Its shape is unaffected; only its mm² "
                      "axis is stale."]
        except (OSError, TypeError):
            pass
        return '\n'.join(L)

    def _anchor_record(self, ref, scale):
        """The setup.txt anchor dict for `ref` at `scale` — the ONE builder
        both Save and the scale-only re-anchor write through.

        Shared rather than duplicated (`#215`, 2026-08-06) so the re-anchor
        path records the FULL provenance of its anchor — the verify mode's fit
        quality and who approved it, or a hand measurement's rounds, spread, σ
        and SE — and cannot drift into a thinner second version of the same
        record. The re-anchor adds its own fields on top (see
        `se.reanchor_anchor_fields`); nothing here knows about that.

        Every key is optional on write: `save_scale_anchor` omits whatever is
        absent, which is how the pre-#215 two-click anchors, the hand
        calibrations and the verify-mode anchors all share one block format."""
        return {
            'method': ref.get('method', se.ANCHOR_METHOD_MANUAL),
            'diam_px': ref['diam_px'],
            'diam_mm': self.settings['diam_mm'],
            'mm_per_px': scale,
            'anchor_frame': ref.get('frame', ''),
            'anchor_is_baseline': ref.get('is_baseline'),
            'auto_diam_px': (self.base_ref or {}).get('diam_px'),
            # #215: the three (or more) fitted diameters, their spread and
            # what the anchor guard said. The spread is the ONLY per-run
            # measurement of operator repeatability in this project —
            # SLDEA_MEASUREMENT §2.5's "operator repeat ~1%" has never had
            # data. Absent on a reused pre-#215 anchor, and save_scale_anchor
            # simply omits the keys then.
            'n_rounds': ref.get('n_rounds'),
            'rounds_px': ref.get('rounds_px'),
            'spread_px': ref.get('spread_px'),
            'spread_pct': ref.get('spread_pct'),
            # which METHOD produced it (A circle / B two-point) and the
            # n-aware conversion of its scatter. The range alone is not
            # comparable between anchors taken at different round counts, so
            # sigma and the mean SE travel with it.
            'cal_mode': ref.get('cal_mode'),
            'sigma_pct': ref.get('sigma_pct'),
            'se_pct': ref.get('se_pct'),
            # the verify mode (`#215`, 2026-08-06 evening): an 'auto-verified'
            # anchor has no rounds and no spread, so what quantifies it is the
            # FIT's own quality, and what makes it auditable is the named human
            # who approved it and when. save_scale_anchor omits every one of
            # these when they are absent, which is every hand-measured and
            # every pre-#215 anchor.
            'fit_circ': ref.get('fit_circ'),
            'fit_conf': ref.get('fit_conf'),
            'fit_resid_px': ref.get('fit_resid_px'),
            'fit_arc_cov': ref.get('fit_arc_cov'),
            'fit_n_edge': ref.get('fit_n_edge'),
            'verified_by': ref.get('verified_by'),
            'verified_at': ref.get('verified_at'),
            'guard': ref.get('guard'),
        }

    # ---------------- advanced settings ----------------
    def _howto(self):
        """❓ How to use — the workflow panel (`#238`).

        SINGLETON like Advanced… (#176) and NON-MODAL, deliberately: this is
        read BESIDE the window while working — an operator who has just been
        told that a wash-out frame gets traced needs the trace controls live
        while the sentence is still on screen. It takes no grab and blocks
        nothing.

        It also owns no key bindings of the main window. The review keys
        (1/2/3, R, D, Enter) are bound on the review root, and Tk's bindtag
        chain for a widget inside THIS Toplevel does not include that root —
        so typing in the help window can never accept or reject a frame.

        Fail-CLOSED construction, the lesson from the calibration singleton:
        the handle is published only once the window is fully built, and a
        failure mid-build destroys the half-built Toplevel rather than
        leaving a corpse that every later click would lift and return from.

        The words are HOWTO_SECTIONS; see the block comment there for why
        they are a hand-kept copy rather than being sourced from
        docs/manual-src/content.json."""
        if self._howto_win is not None and self._howto_win.winfo_exists():
            self._howto_win.lift()
            self._howto_win.focus_set()
            return
        BG, FG, HEAD = '#ffffff', '#1a1a1a', '#1f3a5f'
        win = tk.Toplevel(self.root)
        try:
            win.title(HOWTO_TITLE)
            win.transient(self.root)     # stays with its window; no grab
            # Sized for a 1080p bench screen and CLAMPED to the real one, so
            # a smaller/rotated bench display cannot get a window taller
            # than itself with its close button off-screen.
            h = max(340, min(HOWTO_H, self.root.winfo_screenheight() - 180))
            w = max(420, min(HOWTO_W, self.root.winfo_screenwidth() - 80))
            win.geometry(f"{w}x{h}")
            win.minsize(420, 300)
            outer = ttk.Frame(win)
            outer.pack(fill='both', expand=True)
            cv = tk.Canvas(outer, bg=BG, highlightthickness=0, bd=0)
            bar = ttk.Scrollbar(outer, orient='vertical', command=cv.yview)
            cv.configure(yscrollcommand=bar.set)
            bar.pack(side=tk.RIGHT, fill='y')
            cv.pack(side=tk.LEFT, fill='both', expand=True)
            body = tk.Frame(cv, bg=BG, padx=18, pady=14)
            item = cv.create_window((0, 0), window=body, anchor='nw')

            wrapped = []                 # labels that must reflow on resize
            for si, (heading, paras) in enumerate(HOWTO_SECTIONS):
                tk.Label(body, text=heading, bg=BG, fg=HEAD, anchor='w',
                         justify='left',
                         font=('TkDefaultFont', 11, 'bold')).pack(
                    fill='x', pady=((14 if si else 0), 4))
                for p in paras:
                    if isinstance(p, tuple):     # the candidate-line example
                        tk.Label(body, text=p[1], bg='#f2f4f7', fg=FG,
                                 anchor='w', justify='left', padx=8, pady=4,
                                 font='TkFixedFont').pack(
                            fill='x', pady=(2, 6))
                        continue
                    lb = tk.Label(body, text=p, bg=BG, fg=FG, anchor='w',
                                  justify='left',
                                  font=('TkDefaultFont', 10))
                    lb.pack(fill='x', pady=(0, 7))
                    wrapped.append(lb)

            def refit(_e=None):
                # the body tracks the canvas width so the text reflows with
                # the window instead of being clipped by a fixed wraplength
                cw = max(200, cv.winfo_width())
                cv.itemconfigure(item, width=cw)
                for lb in wrapped:
                    lb.config(wraplength=cw - 40)
                cv.configure(scrollregion=cv.bbox('all'))

            cv.bind('<Configure>', refit)
            body.bind('<Configure>',
                      lambda _e: cv.configure(scrollregion=cv.bbox('all')))

            def wheel(e):
                cv.yview_scroll(-1 if e.delta > 0 else 1, 'units')

            # bound on the TOPLEVEL, never bind_all: a wheel binding on the
            # whole app would scroll this panel from over the review canvas
            win.bind('<MouseWheel>', wheel)                      # Win/macOS
            win.bind('<Button-4>', lambda e: cv.yview_scroll(-1, 'units'))
            win.bind('<Button-5>', lambda e: cv.yview_scroll(1, 'units'))
            win.bind('<Up>', lambda e: cv.yview_scroll(-1, 'units'))
            win.bind('<Down>', lambda e: cv.yview_scroll(1, 'units'))
            win.bind('<Prior>', lambda e: cv.yview_scroll(-1, 'pages'))
            win.bind('<Next>', lambda e: cv.yview_scroll(1, 'pages'))
            win.bind('<Escape>', lambda e: win.destroy())

            foot = ttk.Frame(win, padding=(8, 6))
            foot.pack(side=tk.BOTTOM, fill='x')
            ttk.Button(foot, text="Close",
                       command=win.destroy).pack(side=tk.RIGHT)
            self._howto_scroll = cv     # published for the tests
            refit()
            win.update_idletasks()
            refit()                     # once more with real geometry
        except Exception:
            win.destroy()               # never publish a half-built window
            raise
        self._howto_win = win

    def _advanced(self):
        # SINGLETON (#176): stacked settings dialogs each hold the
        # values from their open time, so Apply on a stale one silently
        # reverts newer changes. Re-clicking fronts the live dialog.
        if self._adv_win is not None and self._adv_win.winfo_exists():
            self._adv_win.lift()
            self._adv_win.focus_set()
            return
        win = tk.Toplevel(self.root)
        self._adv_win = win
        win.title("Edge detection settings")
        entries = {}
        tips = {'diam_mm': "DEA resting active-area diameter (mm) — sets the "
                           "px→mm scale via the baseline detection",
                'blur_px': "Gaussian blur kernel (odd px)",
                'diff_thresh': "fixed diff threshold; 0 = auto (Otsu tiers)",
                'min_diff': "diff p99 below this = no change vs baseline "
                            "(frame auto-rejected; lower it to dig for "
                            "subtle changes; frames above it always yield "
                            "at least one candidate for review)",
                'electrode_lum': "mask pixels this bright in the BASELINE "
                                 "(plus the texture-derived foil "
                                 "footprint) — the electrodes are static, "
                                 "so the baseline knows where they are; "
                                 "0 disables",
                'min_solidity': "drop candidates below this solidity (0–1); "
                                "oblong shapes still score 1.0",
                'roi_frac': "central search window as a fraction of the "
                            "frame (ignores electrode glare at the edges)",
                'accept_conf': "auto-accept at/above this confidence (0–1)",
                'spread_pct': "candidate area disagreement (%) forcing review",
                'audit_nostep_pct': "self-audit gate: % of the winning "
                                    "boundary's arc with no measurable ink "
                                    "step under it above which the frame is "
                                    "capped to review; 0 disables",
                'audit_bias_px': "self-audit gate: median offset (px) "
                                 "between the fitted boundary and the "
                                 "measured ink step above which the frame "
                                 "is capped to review (catches resting "
                                 "claims gone stale); 0 disables",
                'breakdown_dev_ua': "current deviation (µA) from the run's "
                                    "median that marks a breakdown event "
                                    "row; two adjacent event rows (or one "
                                    "ending the run) confirm, a single "
                                    "recovered one is an advisory note",
                'breakdown_ua': "gross ABSOLUTE current limit (µA) — "
                                "fallback used only when the run has "
                                "fewer than 5 readable µA rows (no "
                                "median baseline)",
                'area_jump_pct': "area collapse (%) while voltage rises: "
                                 "confirms breakdown only with a current "
                                 "event at the same kV level, otherwise "
                                 "an advisory note",
                'wrinkle_ratio': "wrinkle index (texture vs baseline) at/"
                                 "above this = wrinkle-mode; first such "
                                 "frame is noted as the onset",
                'norm_bg': "photometric normalization vs the baseline "
                           "before diffing (cancels the camera's internal "
                           "auto-gain drift): 2 = gain+offset fit on ROI "
                           "quantiles (default), 1 = legacy scalar "
                           "border-band ratio, 0 = off"}
        for r, key in enumerate(se.DEFAULT_SETTINGS):
            ttk.Label(win, text=f"{key}:").grid(row=r, column=0, sticky='e',
                                                padx=6, pady=3)
            e = ttk.Entry(win, width=10)
            e.insert(0, f"{self.settings[key]:g}")
            e.grid(row=r, column=1, padx=6)
            ttk.Label(win, text=tips.get(key, ''), foreground='#666',
                      wraplength=380, justify='left').grid(
                row=r, column=2, sticky='w', padx=6)
            entries[key] = e

        # knobs that change what DETECTION produces — applying one of
        # these invalidates the current pass; the rest (breakdown
        # thresholds, wrinkle onset, diam_mm) are pure post-processing
        # and are recomputed live instead (audit 2026-08-05: Apply used
        # to leave Save armed with flags computed under the OLD
        # thresholds, and mark_breakdown_files renamed frames on them)
        detect_keys = ('blur_px', 'diff_thresh', 'min_diff',
                       'min_solidity', 'roi_frac', 'electrode_lum',
                       'accept_conf', 'spread_pct', 'audit_nostep_pct',
                       'audit_bias_px', 'wrinkle_ratio', 'tex_seg',
                       'norm_bg')

        def apply(save=False):
            if self._detect_busy:
                # the generation token protects run SWITCHES; a mid-
                # detect settings change would let the still-streaming
                # worker (bound to the OLD settings) refill a pass the
                # apply just cleared — auto-accepting old-settings
                # candidates under new-settings gates, and recording
                # settings that do not reproduce the outputs (review
                # 2026-08-05)
                messagebox.showinfo(
                    "Settings", "Detection is running — wait for it to "
                    "finish (or switch runs) before applying settings.",
                    parent=win)
                return
            try:
                new = {}
                for key, e in entries.items():
                    cast = type(se.DEFAULT_SETTINGS[key])
                    new[key] = cast(float(e.get()))
            except ValueError as err:
                messagebox.showerror("Settings", str(err), parent=win)
                return
            has_pass = bool(self.results or self.cands_all)
            detect_changed = any(new[k] != self.settings[k]
                                 for k in detect_keys)
            # pair_cands is NOT a pass (see _detect_one) so it never makes
            # has_pass true -- but it IS settings-dependent, so a changed
            # detect key must drop it either way, or the next trace would
            # pair with a candidate the current settings do not reproduce
            invalidates = has_pass and detect_changed
            if invalidates:
                n_rev = sum(1 for i in self.results
                            if i not in self.auto_idx
                            and i not in self.auto_rej)
                # staged manual traces die with the pass, and a dialog
                # that counts only DECIDED frames read as harmless while
                # it discarded a morning of tracing (review 2026-08-06)
                staged = (f", and {len(self.traces)} STAGED manual "
                          f"trace(s) that would have to be re-clicked "
                          f"(their polygons stay in {strc.LABELS_NAME}, "
                          f"the staging does not)" if self.traces else "")
                if not messagebox.askyesno(
                        "Settings",
                        f"These change what detection produces — the "
                        f"current pass ({len(self.results)} decided "
                        f"frame(s), {n_rev} by hand{staged}) will be "
                        f"CLEARED and Detect must re-run.\n\n"
                        f"Apply anyway?",
                        parent=win):
                    return
            self.settings.update(new)
            if detect_changed:
                self.pair_cands = {}
            if save and self.rundir:
                se.save_settings(self.rundir, self.settings)
            win.destroy()
            saved_txt = " + saved to setup.txt" if save else ""
            if invalidates:
                self.cands_all, self.results, self.flags = {}, {}, {}
                self.pair_cands = {}
                self.advisories = {}
                self.traces = {}
                self.auto_idx, self.auto_rej = set(), set()
                self.load_fail = {}
                self.save_btn.config(state='disabled')
                self.status.config(
                    text=f"settings applied{saved_txt} — pass "
                         f"invalidated, re-run Detect")
                self._show()
            elif self.run and (self.results or self.cands_all):
                # post-processing knobs: flags, advisories and the info
                # panel refresh NOW, so Save can never rename frames on
                # thresholds the operator just changed away from
                self._recount()
                self._show()
                self.status.config(
                    text=f"settings applied{saved_txt} — breakdown/"
                         f"wrinkle flags recomputed "
                         f"({len(self.flags)} confirmed, "
                         f"{len(self.advisories)} advisory)")
            else:
                self.status.config(
                    text=f"settings applied{saved_txt} — run Detect")

        bf = ttk.Frame(win)
        bf.grid(row=len(se.DEFAULT_SETTINGS), column=0, columnspan=3, pady=8)
        ttk.Button(bf, text="Apply", command=apply).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="Apply + Save to setup.txt",
                   command=lambda: apply(True)).pack(side=tk.LEFT, padx=4)


class TraceWindow(tk.Toplevel):
    """Manual boundary tracing (#162): click points that close into the
    outer edge of the active area. All geometry/undo/coordinate state
    lives in sldea_trace (headless-tested); this class only translates
    Tk events into model calls and repaints. Done STAGES the polygon as
    candidate D in the review card (app._trace_staged); the operator
    commits it with Accept, same as any candidate (#172).

    Interaction: left-click add point (drag an existing point to move
    it, right-click deletes it), wheel zooms about the cursor, middle-
    or space-drag pans, F fits, Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z) undo/
    redo, Enter / double-click / clicking the first point closes,
    Esc cancels. The polygon is stored in FULL-RES image px throughout
    -- zoom can never desynchronize clicks from image coordinates."""

    CV_W, CV_H = 900, 620
    GRAB_PX = 8            # view-px radius: press on a point = drag it
    DEL_PX = 12            # view-px radius for right-click delete

    def __init__(self, app, row_index, img_path, mm_per_px=None,
                 seed=None, seed_snapped=False, unpaired_ack=None):
        super().__init__(app.root)
        from PIL import Image
        self.app = app
        self.row_index = row_index
        self.mm_per_px = mm_per_px
        # the pairing gap the operator acknowledged before this window
        # opened (#162) — travels back with Done so _trace_staged knows
        # whether it still has to say it, and dies with the window
        self._unpaired_ack = unpaired_ack
        self.img = Image.open(img_path).convert('RGB')
        self.gray = se.load_gray(img_path)
        row = app.run['rows'][row_index]
        self.title(f"Trace boundary — step {row.get('step')} "
                   f"[{row.get('tag')}] {row.get('nominal_kV')} kV")
        self.model = strc.TraceModel()
        self._seeded = bool(seed)
        if seed:
            # re-trace (#172): edit the pending D polygon instead of
            # re-clicking it. Seeded points are the baseline state (not
            # undoable ops); Restart still clears them in one step.
            self.model.points = [(float(x), float(y)) for x, y in seed]
        self.vt = strc.ViewTransform()
        self.vt.fit(self.img.width, self.img.height, self.CV_W, self.CV_H)
        self._t_open = time.time()
        # a seeded polygon traced with the magnet keeps its 'snapped'
        # tag -- the label must not launder snapped points as freehand
        self._snap_used = bool(seed_snapped)
        self._drag_idx = None
        self._drag_orig = None
        self._pan_from = None
        self._space = False
        self._cursor = None
        self._photo = None

        bar = ttk.Frame(self, padding=4)
        bar.pack(fill='x')
        self.undo_btn = ttk.Button(bar, text="↶ Undo",
                                   command=self._undo, state='disabled')
        self.undo_btn.pack(side=tk.LEFT)
        self.redo_btn = ttk.Button(bar, text="↷ Redo",
                                   command=self._redo, state='disabled')
        self.redo_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="⟲ Restart placements…",
                   command=self._restart).pack(side=tk.LEFT, padx=(8, 0))
        self.snap_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="edge snap",
                        variable=self.snap_var).pack(side=tk.LEFT,
                                                     padx=(12, 0))
        self.ov_rest = tk.BooleanVar(value=True)
        self.ov_cand = tk.BooleanVar(value=False)
        self.ov_prev = tk.BooleanVar(value=False)
        for var, txt in ((self.ov_rest, "resting disc"),
                         (self.ov_cand, "candidates"),
                         (self.ov_prev, "prev outline")):
            ttk.Checkbutton(bar, text=txt, variable=var,
                            command=self._repaint).pack(side=tk.LEFT,
                                                        padx=(6, 0))
        ttk.Button(bar, text="✔ Done (Enter)",
                   command=self._done).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Cancel (Esc)",
                   command=self._cancel).pack(side=tk.RIGHT, padx=6)
        self.zoom_lbl = ttk.Label(bar, text="")
        self.zoom_lbl.pack(side=tk.RIGHT, padx=8)

        self.cv = tk.Canvas(self, width=self.CV_W, height=self.CV_H,
                            bg='#111', highlightthickness=0,
                            cursor='crosshair')
        self.cv.pack(padx=4, pady=4)
        self.stat = tk.Label(self, anchor='w', justify='left',
                             text="click to place points — they close "
                                  "into the outer edge of the active area")
        self.stat.pack(fill='x', padx=6, pady=(0, 4))

        self.cv.bind('<Button-1>', self._press)
        self.cv.bind('<B1-Motion>', self._drag)
        self.cv.bind('<ButtonRelease-1>', self._release)
        self.cv.bind('<Button-3>', self._delete_near)
        self.cv.bind('<Double-Button-1>', lambda e: self._done())
        self.cv.bind('<Motion>', self._motion)
        self.cv.bind('<MouseWheel>',
                     lambda e: self._wheel(e.x, e.y, e.delta / 120.0))
        self.cv.bind('<Button-4>', lambda e: self._wheel(e.x, e.y, 1))
        self.cv.bind('<Button-5>', lambda e: self._wheel(e.x, e.y, -1))
        self.cv.bind('<Button-2>', self._pan_start)
        self.cv.bind('<B2-Motion>', self._pan_move)
        self.bind('<Control-z>', lambda e: self._undo())
        self.bind('<Control-y>', lambda e: self._redo())
        self.bind('<Control-Z>', lambda e: self._redo())   # Ctrl+Shift+Z
        self.bind('<Key-f>', lambda e: self._fit())
        self.bind('<Key-F>', lambda e: self._fit())
        self.bind('<Return>', lambda e: self._done())
        self.bind('<Escape>', lambda e: self._cancel())
        self.bind('<KeyPress-space>', lambda e: self._set_space(True))
        self.bind('<KeyRelease-space>', lambda e: self._set_space(False))
        self.protocol('WM_DELETE_WINDOW', self._cancel)
        self.transient(app.root)
        self.grab_set()
        self.cv.focus_set()
        self._repaint()

    # -- coordinate helpers ---------------------------------------------
    def _img_xy(self, ev):
        return self.vt.to_image(ev.x, ev.y)

    def _near_point(self, ev, r_view):
        ix, iy = self._img_xy(ev)
        return self.model.nearest(ix, iy, r_view / self.vt.zoom)

    # -- pointer events -------------------------------------------------
    def _press(self, ev):
        if self._space:
            self._pan_start(ev)
            return
        idx = self._near_point(ev, self.GRAB_PX)
        pts = self.model.points
        if idx == 0 and len(pts) >= 3:
            self._done()
            return
        if idx is not None:
            self._drag_idx = idx
            self._drag_orig = pts[idx]
            return
        ix, iy = self._img_xy(ev)
        if self.snap_var.get() and self.gray is not None:
            ix, iy = strc.edge_snap(self.gray, ix, iy)
            self._snap_used = True
        self.model.add(ix, iy)
        self._vectors()

    def _drag(self, ev):
        if self._pan_from is not None:
            self._pan_move(ev)
            return
        if self._drag_idx is None:
            return
        self.model.points[self._drag_idx] = self._img_xy(ev)
        self._vectors()

    def _release(self, ev):
        if self._pan_from is not None:
            self._pan_from = None
            return
        if self._drag_idx is None:
            return
        idx, orig = self._drag_idx, self._drag_orig
        self._drag_idx = self._drag_orig = None
        ix, iy = self._img_xy(ev)
        if self.snap_var.get() and self.gray is not None:
            ix, iy = strc.edge_snap(self.gray, ix, iy)
            self._snap_used = True
        # reconcile through the op stack: transient motion above was a
        # preview; the MOVE is one atomic, undoable op
        self.model.points[idx] = orig
        self.model.move(idx, ix, iy)
        self._vectors()

    def _delete_near(self, ev):
        idx = self._near_point(ev, self.DEL_PX)
        if idx is not None:
            self.model.delete(idx)
            self._vectors()

    def _motion(self, ev):
        self._cursor = (ev.x, ev.y)
        self._vectors()

    # -- view -----------------------------------------------------------
    def _wheel(self, vx, vy, steps):
        self.vt.zoom_at(vx, vy, 1.15 ** steps)
        self._repaint()

    def _pan_start(self, ev):
        self._pan_from = (ev.x, ev.y)

    def _pan_move(self, ev):
        if self._pan_from is None:
            return
        dx, dy = ev.x - self._pan_from[0], ev.y - self._pan_from[1]
        self._pan_from = (ev.x, ev.y)
        self.vt.pan_view(dx, dy)
        self._repaint()

    def _set_space(self, held):
        self._space = held
        if not held:
            self._pan_from = None

    def _fit(self):
        self.vt.fit(self.img.width, self.img.height, self.CV_W, self.CV_H)
        self._repaint()

    # -- history --------------------------------------------------------
    def _undo(self):
        if self.model.undo():
            self._vectors()

    def _redo(self):
        if self.model.redo():
            self._vectors()

    def _restart(self):
        if not self.model.points:
            return
        if messagebox.askyesno("Restart placements",
                               "Remove ALL placed points and start over?\n"
                               "(This is one undoable step.)",
                               parent=self):
            self.model.restart()
            self._vectors()

    # -- painting -------------------------------------------------------
    def _repaint(self):
        """Photo layer: the visible crop of the full-res frame, resized
        to the viewport (nearest-neighbour when zoomed in, so pixels stay
        honest). Vector layer painted on top."""
        from PIL import Image, ImageTk
        t = self.vt
        ix0, iy0 = t.to_image(0, 0)
        ix1, iy1 = t.to_image(self.CV_W, self.CV_H)
        cx0, cy0 = max(0, int(ix0)), max(0, int(iy0))
        cx1 = min(self.img.width, int(ix1) + 2)
        cy1 = min(self.img.height, int(iy1) + 2)
        self.cv.delete('img')
        if cx1 > cx0 and cy1 > cy0:
            crop = self.img.crop((cx0, cy0, cx1, cy1))
            dw = max(1, int(round((cx1 - cx0) * t.zoom)))
            dh = max(1, int(round((cy1 - cy0) * t.zoom)))
            res = Image.NEAREST if t.zoom >= 2.0 else Image.BILINEAR
            self._photo = ImageTk.PhotoImage(crop.resize((dw, dh), res))
            vx, vy = t.to_view(cx0, cy0)
            self.cv.create_image(int(vx), int(vy), anchor='nw',
                                 image=self._photo, tags='img')
        self.cv.tag_lower('img')
        self.zoom_lbl.config(text=f"zoom {100 * t.zoom:.0f}%")
        self._vectors()

    def _poly_view(self, contour):
        return [c for x, y in np.asarray(contour, float)
                for c in self.vt.to_view(x, y)]

    def _vectors(self):
        self.cv.delete('vec')
        t = self.vt
        # context overlays (recorded in the label so calibration knows
        # what the operator could see)
        if self.ov_rest.get() and self.app.base_ref is not None \
                and self.app.base_ref.get('contour') is not None:
            self.cv.create_polygon(
                *self._poly_view(self.app.base_ref['contour']),
                outline='#888888', fill='', dash=(4, 4), tags='vec')
        if self.ov_cand.get():
            # the on-demand pairing is drawable too (#162): the operator
            # should SEE the candidate their trace will be compared with.
            # Colour index wraps -- candidates() can return more than the
            # three review slots (disc-fit + three diff tiers + tex).
            for k, c in enumerate(self.app.trace_overlay_cands(
                    self.row_index)):
                self.cv.create_polygon(
                    *self._poly_view(c['contour']),
                    outline=CAND_COLORS[k % len(CAND_COLORS)], fill='',
                    dash=(2, 4), tags='vec')
        if self.ov_prev.get():
            prev = None
            for j in self.app.frame_rows:
                if j >= self.row_index:
                    break
                r = self.app.results.get(j)
                if r:
                    prev = r
            if prev is not None:
                self.cv.create_polygon(
                    *self._poly_view(prev['contour']),
                    outline='#b39ddb', fill='', dash=(6, 3), tags='vec')
        pts = self.model.points
        vp = [self.vt.to_view(x, y) for x, y in pts]
        if len(vp) >= 2:
            for a, b in zip(vp[:-1], vp[1:]):
                self.cv.create_line(*a, *b, fill='#00e676', width=2,
                                    tags='vec')
        if len(vp) >= 3:
            self.cv.create_line(*vp[-1], *vp[0], fill='#00e676',
                                dash=(3, 4), tags='vec')
        if self._cursor and vp and self._drag_idx is None:
            self.cv.create_line(*vp[-1], *self._cursor, fill='#80cbc4',
                                dash=(2, 4), tags='vec')
        for k, (vx, vy) in enumerate(vp):
            r = 5 if k == 0 else 3
            self.cv.create_oval(vx - r, vy - r, vx + r, vy + r,
                                outline='#00e676',
                                width=2 if k == 0 else 1,
                                fill='#003322', tags='vec')
        self.undo_btn.config(
            state='normal' if self.model.can_undo() else 'disabled')
        self.redo_btn.config(
            state='normal' if self.model.can_redo() else 'disabled')
        area = strc.polygon_area(pts)
        mm = (f"  =  {area * self.mm_per_px ** 2:.1f} mm²"
              if self.mm_per_px and area else "")
        self.stat.config(
            text=f"{len(pts)} point(s) — area {area:.0f} px²{mm} — "
                 f"click add · drag move · right-click delete · wheel "
                 f"zoom · middle/space drag pan · Enter/double-click/"
                 f"first-point close · F fit · Esc cancel")

    # -- finish ---------------------------------------------------------
    def _done(self):
        pts = list(self.model.points)
        if len(pts) < 3:
            messagebox.showinfo("Trace", "Place at least 3 points to "
                                "close the outline.", parent=self)
            return
        if strc.self_intersects(pts) and not messagebox.askyesno(
                "Trace", "The outline crosses itself. Keep it anyway?",
                parent=self):
            return
        meta = {'zoom': self.vt.zoom,
                'overlays': {'resting': bool(self.ov_rest.get()),
                             'candidates': bool(self.ov_cand.get()),
                             'prev': bool(self.ov_prev.get())},
                'elapsed_s': time.time() - self._t_open,
                'snapped': self._snap_used,
                'unpaired_ack': self._unpaired_ack}
        self.grab_release()
        self.destroy()
        self.app._trace_staged(self.row_index, pts, meta)

    def _cancel(self):
        msg = ("Close the tracer? The previously staged D outline is "
               "kept; this session's edits are discarded."
               if self._seeded else "Discard the traced points?")
        if self.model.points and not messagebox.askyesno(
                "Trace", msg, parent=self):
            return
        self.grab_release()
        self.destroy()
        # clicking the D radio set the selection before opening the
        # tracer; a cancel must put it back where the frame's state says
        self.app._show()


def parse_args(argv):
    """-> (path, auto, goto) for the command line.

    `--goto ROW` (also `--goto=ROW`) opens the run at the frame showing
    that DATA ROW — the plot window's click-through target (`#274`). ROW
    is a 0-BASED index into the run CSV, which is what every other tool
    in the suite means by a row; this window shows 1-based FRAMES, and
    `#255` is on record for what confusing the two costs (a trace
    mis-targeted by one frame). Translating between them is `goto_row`'s
    job, not the caller's.

    NEVER RAISES AND NEVER REFUSES TO OPEN. A junk or missing ROW is
    dropped with a console note and the window opens exactly as it would
    have: this is a shortcut, and a broken shortcut must not cost the
    operator their program. A junk value is still CONSUMED, so
    `--goto nonsense` cannot be mistaken for the run path -- but a value
    that looks like a flag is left alone, which is sldea_plot's rule for
    its own valued flags: `--goto --auto` is a --goto with no value AND
    an --auto, not a swallowed --auto.
    """
    path, auto, goto = None, False, None
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--auto':
            auto = True
        elif a == '--goto' or a.startswith('--goto='):
            if '=' in a:
                val = a.split('=', 1)[1]
            elif i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                val = argv[i + 1]
                i += 1
            else:
                val = None
            try:
                goto = int(val)
            except (TypeError, ValueError):
                # ASCII: a Windows cp1252 console cannot carry a path
                print(f"edge review: ignoring --goto {ascii(val)} "
                      f"(want a 0-based CSV row number)")
        elif not a.startswith('--'):
            rest.append(a)
        i += 1
    return (rest[0] if rest else None), auto, goto


def main():
    path, auto, goto = parse_args(sys.argv[1:])
    root = tk.Tk()
    EdgeReviewApp(root, path=path, auto=auto, goto=goto)
    root.mainloop()


if __name__ == '__main__':
    main()
