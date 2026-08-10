#!/usr/bin/env python3
"""Point-and-click front end for sldea_plot (issue `#223`).

The plot tool was the only SLDEA companion with no way in from the app:
Edge Review and the tuner have buttons on the SLDEA tab, while putting two
runs on one figure meant a command line and eight flags. This is that
window -- pick several runs, tick what to draw, watch it redraw, then
Export.

    python sldea_plot_gui.py [RUN_OR_PARENT]     # or newest under the default
    python sldea_plot.py --gui [RUN ...]         # same window, via the CLI

It is a VIEWFINDER on sldea_plot, not a second plotting tool: run picking
goes through sldea_plot.prepare_runs, drawing through sldea_plot.draw and
writing through sldea_plot.export. So a figure made here is the figure the
command line makes -- same era guards, same warnings, same palette, and
the same tidy CSV beside the same PNG. The headless paths are untouched;
--selftest and batch scripting stay first-class.

Two deliberate shapes:

  * Preview DRAWS ONLY. Nothing reaches the disk until Export, which names
    the files it wrote in the window. A preview that quietly littered the
    run folder with PNGs would be worse than the CLI, not better.
  * Export always writes the tidy per-snapshot CSV beside the figure.
    That CSV is the figure's evidence -- it is what makes a figure
    traceable back to its numbers -- so there is no "just the picture"
    option here, whichever format the picture is in (sldea_plot.export
    enforces it for both front ends; `#314` made the format and the dpi
    the operator's choice and left that rule untouched).

Two things the window remembers or reaches for, both additive:

  * a double-click on a data point opens THAT FRAME in Edge Review
    (`#274`), through the same sibling-process launch the SLDEA tab's
    buttons use, with `--goto ROW`;
  * the draw options are remembered PER PARENT FOLDER in a per-user file
    (`#275`), never in a run folder and never in the repo. Precedence is
    explicit CLI/init args > remembered > defaults, and a corrupt or
    stale file can only cost the memory, never the window.
"""
import math
import os
import subprocess
import sys
import time
import tk_fontfix                      # must run before tkinter connects:
tk_fontfix.apply()                     # colour-emoji glyphs hard-crash Tk
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import sldea_edge as se
import sldea_plot as sp

# ASCII only: this is the one thing the module prints to a console, and a
# Windows cp1252 console cannot carry the docstring's prose.
USAGE = """\
Usage:
    python sldea_plot_gui.py [RUN_OR_PARENT]   # a run, a folder of runs,
                                               # or a bench shortcut (1/2/3)
    python sldea_plot.py --gui [RUN ...]       # the same window, via the CLI

Pick several runs, choose area / current / power, tick what to draw.
Double-click a point on the figure to open that frame in Edge Review.
Export writes the figure, its tidy per-snapshot CSV and its figspec
sidecar together -- PNG (at a dpi you set, 300 by default) or SVG.

The draw options are remembered PER PARENT FOLDER in a per-user file --
~/.local/share/scpi_control/sldea_plot_gui.json, or the same name under
~/.cache/scpi_control -- never in the repo and never in a run folder.
Precedence: an option given on the command line beats a remembered one,
which beats the default. Delete that file to forget everything."""

DEFAULT_PARENT = os.environ.get(
    'SCPI_SLDEA_DIR', '/mnt/shareDrive/robot_incubator/SLDEA_data')

# Where figures go when nobody says otherwise. NOT the current directory:
# the CLI's cwd default is right for a shell but wrong for a double-clicked
# window, where cwd is wherever the launcher happened to be and figures go
# missing (`#223`). A 'plots' folder beside the runs keeps a campaign's
# figures with the campaign and never writes inside a run folder.
OUT_SUBDIR = 'plots'

PROCESSED_MARK = '  ✓ processed'       # Edge Review's labelling convention

# The smallest window the layout still WORKS in (`#271`). Width is
# measured, not guessed: the controls column asks for whatever the theme
# and DPI make it (295 px on the Windows analysis PC, wider on a
# high-DPI bench PC), and MIN_FIG_W is the narrowest figure worth
# drawing beside it. Height is the message pane plus the matplotlib
# toolbar plus a figure that is still a figure.
MIN_FIG_W = 360
MIN_H = 420

# Redraw coalescing for a CONTROL change -- a tick box, a keystroke, a
# drag through the run list. 120 ms is a click's worth of quiet.
REDRAW_MS = 120

# A resize needs its own, longer window, and the reason is the `#316`
# defect: a restartable timer only coalesces a burst whose events arrive
# FASTER THAN IT FIRES, and a resize drag's did not.
#
# Measured, 13 corpus runs on one area figure, a real 3.5 s mouse drag on
# the window edge: 3-5 <Configure> reached the canvas and 3-5 FULL
# REDRAWS came back. One for one, no coalescing at all. A drag does not
# fire <Configure> per pixel the way this comment used to assume -- it
# fires ONE PER REDRAW, because each redraw blocks the Tk loop for 480 ms
# (298 ms building 742 artists, 178 ms rendering them) and nothing can be
# delivered meanwhile. The debounce was not late to the drag; the drag
# was throttled to the debounce.
#
# So the window is measured against the thing it has to outlast. With the
# redundant redraws gone, consecutive <Configure> arrive 280-500 ms apart
# on this corpus -- that gap being matplotlib's OWN resize render (262 ms,
# measured with our handler disabled entirely) plus the WM's dispatch.
# 500 ms clears it. A drag settling a third of a second later than a click
# costs nothing visible: matplotlib's handler has already redrawn the
# figure at the new size by then, and what our redraw adds on top is the
# re-run of tight_layout against it.
RESIZE_MS = 500

# That gap IS the cost of servicing one resize, though, so it grows with
# the series count and no fixed window can be right for every figure.
# This covers the rest, and it needs no number for the workload: a timer
# that comes up LATE waited on a blocked loop. The two cases separate by
# a factor of six, measured on the real debounce path -- ~5 ms past the
# deadline on an idle loop, 240-290 ms past it when a render ran in
# between. A redraw that comes up late is a redraw whose burst is still
# running, so it re-arms instead of firing.
LATE_MS = 40

# ...and deferral is BOUNDED, because "the loop is busy" is not a promise
# that it will ever go quiet. A new event restarts the budget -- that is
# a live burst, and waiting through it is the point -- but nothing else
# may push the figure further out of date than this. One visibly late
# redraw beats a figure that silently stopped tracking its window.
MAX_DEFER_MS = 1000


# ---------------------------------------------------------------------------
# run discovery -- kept apart from the widgets on purpose
#
# These wrap sldea_edge's existing resolvers (se.run_csv / se.resolve_run /
# se.newest_run), which are what the tuner, the diagnostic, Edge Review and
# the Windows launcher already agree on. Nothing here decides what a run
# is; it only decides how to say it in a list box. Headless-testable.
# ---------------------------------------------------------------------------

def is_processed(rundir):
    """True when the run's CSV carries at least one reviewed area.

    Same question Edge Review's run list asks, and the same length guard:
    a truncated or blank line used to raise IndexError and take the whole
    listing with it."""
    path = se.run_csv(rundir)
    if not path:
        return False
    try:
        with open(path, encoding='utf-8-sig', errors='replace') as f:
            if 'active_area_px' not in (f.readline() or ''):
                return False
            return any(len(c := line.split(',')) > 10 and c[10].strip()
                       for line in f)
    except OSError:
        return False


def list_runs(parent):
    """-> [(name, label)] for every run directory under `parent`, newest
    name first. A run is ANY directory holding a run CSV (se.run_csv), so
    custom-named and renamed-CSV runs list like the rest."""
    try:
        names = sorted((n for n in os.listdir(parent)
                        if os.path.isdir(os.path.join(parent, n))
                        and se.run_csv(os.path.join(parent, n))),
                       reverse=True)
    except OSError:
        return []
    return [(n, n + (PROCESSED_MARK
                     if is_processed(os.path.join(parent, n)) else ''))
            for n in names]


def split_target(path):
    """-> (parent to list, run name to preselect or None).

    Accepts what every other SLDEA entry point accepts -- a run directory,
    a parent full of runs, or a bench shortcut -- by going through
    se.resolve_run first, so '1' opens the bench run here too.

    Never raises. This is the window's front door: the argument arrives
    from a command line, from a drag-and-drop, or from whatever is typed in
    the SLDEA tab's output-dir box, and a resolver that threw would take
    the window down before it drew anything. se.run_csv guards OSError but
    not ValueError, which is what a path with an embedded NUL produces."""
    if not path:
        return None, None
    try:
        resolved = se.resolve_run(path)
        if resolved and se.run_csv(resolved):
            resolved = os.path.abspath(resolved)
            return os.path.dirname(resolved), os.path.basename(resolved)
        if os.path.isdir(path):
            return os.path.abspath(path), None
    except (OSError, ValueError):
        pass
    return None, None


def initial_state(args):
    """-> (parent, [names to preselect]).

    Several run arguments preselect several runs -- the whole point of the
    tool is more than one run on a figure. Runs from different parents
    cannot be listed at once, so the FIRST argument picks the parent and
    the rest preselect only if they live there (the others are still
    reachable via Browse)."""
    parent, preselect = None, []
    for a in args or ():
        p, name = split_target(a)
        if p is None:
            continue
        if parent is None:
            parent = p
        if name and p == parent:
            preselect.append(name)
    if parent is None:
        parent, name = split_target(DEFAULT_PARENT)
        if name:
            preselect = [name]
    return parent or DEFAULT_PARENT, preselect


def default_out_dir(parent):
    """Figures land beside the runs, never inside one."""
    return os.path.join(parent or os.getcwd(), OUT_SUBDIR)


# ---------------------------------------------------------------------------
# remembered options, per parent folder (`#275`)
#
# USER SCOPE, and deliberately so. Not in the run folders -- run data
# never carries a UI preference, and the campaign corpus is read-only.
# Not in the repo either, so there is nothing to add to .gitignore: the
# file cannot land in the tree because it is not in it.
#
# The location and the format are the house convention for per-user state
# (webcam.py's camera_controls.json, presets_path.py's fallback): a JSON
# file under ~/.local/share/scpi_control, falling back to
# ~/.cache/scpi_control, which the launcher creates at every start and is
# therefore always writable -- the primary was left root-owned in one
# user's home by the root-run desktop installer (bench 2026-07-24) and an
# unguarded write there is a known Errno 13. The filename carries the
# module so the open-decision-2 repo split moves exactly one file.
#
# This is NOT `setup.txt`'s territory (house rule 2026-08-08: that stays
# plain text, and machine-read fields there keep Key: value). This file
# is neither in a run folder nor read by any measurement path.
# ---------------------------------------------------------------------------

OPTIONS_PATH = os.path.join(os.path.expanduser('~'), '.local', 'share',
                            'scpi_control', 'sldea_plot_gui.json')
OPTIONS_FALLBACK = os.path.join(os.path.expanduser('~'), '.cache',
                                'scpi_control', 'sldea_plot_gui.json')

# What is worth remembering: how the figure is DRAWN, plus an output
# folder someone deliberately chose.
#
# Not the title and not the file stem: both name one particular figure,
# and resurrecting last week's caption over this week's runs would be a
# wrong label that looks like a right one. THE PANEL TITLES ARE THE SAME
# ANSWER for the same reason -- 'title_first'/'title_second' caption two
# panels of one figure rather than describing a house style, so they are
# deliberately absent below while every other drawing option joins.
# Not the run selection either -- a campaign gains runs, and reopening on
# a stale set would quietly plot the wrong batch.
REMEMBERED = ('mode', 'prepost', 'mean', 'bands', 'breakdown', 'vs_area',
              'logx', 'logy', 'marker_key', 'subplots', 'cadence_guard',
              'aggregate', 'aggregate_exact', 'fmt', 'dpi')

# The remembered options that are NAMES rather than flags, each with the
# vocabulary sldea_plot validates it against -- read from sldea_plot so a
# value the engine has retired can never survive a round trip here.
ENUM_OPTIONS = {'mode': sp.MODES, 'subplots': sp.SUBPLOTS,
                'fmt': sp.FORMATS}

# ...and the ones that are NUMBERS (`#314` brought the first), each with
# the engine's own checker. Same principle as ENUM_OPTIONS: the window
# does not restate a range sldea_plot already owns, so a hand-edited
# config cannot smuggle a dpi past the refusal make_opts would give it.
NUMERIC_OPTIONS = {'dpi': sp.check_dpi}


def options_key(parent):
    """The config key for a parent folder: absolute, and normcase'd
    because Windows paths differ in case without differing."""
    try:
        return os.path.normcase(os.path.abspath(parent or ''))
    except (OSError, ValueError):
        return str(parent or '')


def _clean_options(d):
    """-> only the entries that are RECOGNIZABLE and VALID.

    Everything else is dropped rather than repaired. A stale file written
    by an older build, a mode that no longer exists, a hand-edit that put
    a string where a flag goes: none of them may reach make_opts, and
    none of them may stop the window opening."""
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, allowed in ENUM_OPTIONS.items():
        if d.get(k) in allowed:
            out[k] = d[k]
    for k, check in NUMERIC_OPTIONS.items():
        if k in d:
            value, err = check(d[k])
            # `None` reads as 'unset' to the checker and would silently
            # reinstate the default; a key that is PRESENT and unusable is
            # dropped like any other unrecognizable entry
            if err is None and d[k] is not None:
                out[k] = value
    for k in REMEMBERED:
        if (k not in ENUM_OPTIONS and k not in NUMERIC_OPTIONS
                and isinstance(d.get(k), bool)):
            out[k] = d[k]
    if isinstance(d.get('out_dir'), str) and d['out_dir'].strip():
        out['out_dir'] = d['out_dir']
    return out


def load_options(parent, path=None):
    """-> the remembered options for `parent`, or {}.

    NEVER RAISES. A missing, unreadable, truncated, non-JSON or
    hand-mangled file yields {} and the window opens on the defaults --
    silently to the operator, with one line on stderr for whoever is
    reading a console. A convenience must not be able to cost someone
    their program."""
    import json
    paths = [path] if path is not None else [OPTIONS_PATH, OPTIONS_FALLBACK]
    for p in paths:
        try:
            with open(p, encoding='utf-8') as f:
                blob = json.load(f)
        except (OSError, ValueError, UnicodeDecodeError) as e:
            if isinstance(e, OSError) and e.errno == 2:
                continue                       # simply not there yet
            print(f"sldea plot: ignoring unreadable options file "
                  f"{ascii(p)} ({type(e).__name__})")
            continue
        try:
            return _clean_options(blob.get('parents', {}).get(
                options_key(parent), {}))
        except AttributeError:                 # not the shape we write
            print(f"sldea plot: ignoring options file {ascii(p)} "
                  f"(unexpected structure)")
    return {}


def save_options(parent, opts, out_dir=None, path=None):
    """Remember `opts` for `parent`. -> the file written, or None.

    NEVER RAISES either, for the same reason: this runs when the window
    is closing, and a failure to remember a checkbox must not turn a
    close into a traceback. Other parents' entries are preserved --
    the file is read, one key is replaced, and it is written atomically
    through a .tmp so a crash mid-write cannot leave a half file."""
    import json
    entry = {k: opts[k] for k in REMEMBERED if k in opts}
    if out_dir:
        entry['out_dir'] = out_dir
    for cand in ([path] if path is not None
                 else [OPTIONS_PATH, OPTIONS_FALLBACK]):
        try:
            blob = {}
            try:
                with open(cand, encoding='utf-8') as f:
                    blob = json.load(f)
            except (OSError, ValueError, UnicodeDecodeError):
                blob = {}                      # start clean over junk
            if not isinstance(blob.get('parents'), dict):
                blob = {'version': 1, 'parents': {}}
            blob['version'] = 1
            blob['parents'][options_key(parent)] = entry
            os.makedirs(os.path.dirname(cand) or '.', exist_ok=True)
            tmp = cand + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(blob, f, indent=2, sort_keys=True)
            os.replace(tmp, cand)
            return cand
        except OSError:
            continue
    print("sldea plot: could not save the remembered options")
    return None


def explicit_opts(opts):
    """-> the option names `opts` states EXPLICITLY, for the precedence
    rule (CLI/init args > remembered > defaults).

    Derived by DIFFING AGAINST sldea_plot's defaults, because that is all
    the command line leaves behind: sldea_plot.main builds a complete
    opts dict whether or not a single flag was given, so a field sitting
    on its default cannot be told apart from one nobody mentioned.

    The consequence is stated rather than hidden. `--mode area` reads as
    "unset" and a remembered mode wins; `--mode power` beats anything
    remembered. Any caller that knows better can hand `launch` the set
    instead of making it guess."""
    base, _err = sp.make_opts()
    return {k for k, v in (opts or {}).items()
            if k in base and v != base[k]}


# ---------------------------------------------------------------------------
# click-through to Edge Review (`#274`)
#
# A figure that shows an odd point and cannot say WHICH FRAME it is makes
# the operator go and find it by hand -- open Edge Review, guess the run,
# count frames. These two functions are the whole resolver, and they are
# pure so they can be tested without a window.
# ---------------------------------------------------------------------------

PICK_PX = 30       # how near a double-click must land, in SCREEN pixels

CLICK_HINT = ("Double-click a point on the figure to open that frame in "
              "Edge Review.")


def plot_points(runs, opts, panel=0):
    """-> [(x, y, run, row)] for every ROW the current mode draws on axes
    `panel` (0 = the only axes, or area mode's mm²-vs-kV panel; 1 = area
    mode's A/A₀ panel).

    ROWS, NOT MARKERS, on purpose. What a double-click asks is "which
    snapshot is that", and a snapshot IS a row -- the frame Edge Review
    would open. With --prepost the drawn markers are exactly these rows;
    with the mean line drawn instead, a level's mean sits between its
    pre/post pair and the nearer row wins, which is the honest answer.

    The value rules are sldea_plot's, not this module's: the same "has a
    kV and a value" test levels() applies, the same vs-area x axis, and
    power through power_mw -- so a row can only appear here if the figure
    drew something for it.
    """
    out = []
    for run in runs:
        if opts['mode'] == 'area':
            a0 = run['a0']
            for r in run['rows']:
                if r['kv'] is None or r['area_mm2'] is None:
                    continue
                if panel == 1:
                    if not a0:
                        continue
                    out.append((r['kv'], r['area_mm2'] / a0, run, r))
                else:
                    out.append((r['kv'], r['area_mm2'], run, r))
            continue
        med = sp.run_ua_median(run)
        for r in run['rows']:
            x = r['area_mm2'] if opts['vs_area'] else r['kv']
            y = sp.power_mw(r, med) if opts['mode'] == 'power' else r['ua']
            if x is None or y is None:
                continue
            out.append((x, y, run, r))
    return out


def nearest_point(ax, points, px, py, tol=PICK_PX):
    """-> (run, row, distance_px) nearest the DISPLAY position (px, py),
    or None when nothing is within `tol` pixels.

    DISPLAY pixels, never data units. kV runs 0-10 while mm² runs
    150-250, so a distance in data space is dominated by whichever axis
    carries the bigger numbers -- "nearest" would quietly mean "nearest
    in y". Going through the axes' own transform also makes the
    tolerance mean the same thing at every window size and every zoom,
    because it is the transform the figure was drawn with.
    """
    best = None
    for x, y, run, row in points:
        try:
            tx, ty = ax.transData.transform((x, y))
        except (ValueError, TypeError):        # non-finite after a log axis
            continue
        if not (math.isfinite(tx) and math.isfinite(ty)):
            continue
        d = math.hypot(tx - px, ty - py)
        if d <= tol and (best is None or d < best[2]):
            best = (run, row, d)
    return best


# ---------------------------------------------------------------------------
# hover tooltip (`#266`)
#
# COPIED, NOT IMPORTED, from ui_widgets.py — and the reason is the one
# sldea_edge_gui.py already writes out above its own copy: PROJECT_HANDOFF
# open decision 2 moves the SLDEA suite into its own instrument-free repo,
# this module is on that side of the seam (it imports sldea_edge and
# sldea_plot), and `ui_widgets` is not. Importing it would plant a
# cross-seam dependency on the split's own boundary for ~35 lines with no
# state and no invariants. If the split is ever abandoned, delete this
# and `from ui_widgets import add_tooltip` — the signature matches on
# purpose, in all three places.
# ---------------------------------------------------------------------------

class Tooltip:
    """Show `text` in a small popup after hovering `widget` for `delay` ms.

    Tk has no built-in tooltip; this is the standard Toplevel +
    overrideredirect pattern. Hides on leave/click/destroy.
    """

    def __init__(self, widget, text, delay=650, wraplength=380):
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
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:          # widget died while the timer was pending
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
    """Attach a hover tooltip; returns the Tooltip."""
    return Tooltip(widget, text)


# The bands are a CALIBRATED ERROR BUDGET, not a fit residual and not
# anything this window computed (`#266`). Nothing on screen said so, and
# the one number an operator sees next to every area — Edge Review's
# `conf` — looks exactly like the uncertainty it is not.
#
# Both percentages are interpolated from sldea_plot's constants rather
# than typed again: this string and the drawn band must not be able to
# disagree (the `#224` lesson, a label hand-kept in five places).
BANDS_TIP = (
    f"Where the bands come from: the CALIBRATED ERROR BUDGET in "
    f"SLDEA_MEASUREMENT.md. They are quoted, not computed — nothing "
    f"here fits them to your data.\n\n"
    f"±{sp.MACHINE_BAND_PCT:g}%  machine-measured levels (the "
    f"half-height ink step): the per-run scale anchor (~0.8% area) over "
    f"the disc-fit's own CI (0.2–0.7%).\n"
    f"±{sp.TRACED_BAND_PCT:g}%  hand-traced levels (the outer toe): "
    f"operator repeatability, measured over 9 repeat pairs.\n\n"
    f"A level that MIXES the two keeps the machine "
    f"±{sp.MACHINE_BAND_PCT:g}% band, because what it plots is its "
    f"machine member(s) only — the two conventions differ +5.2–5.7% in "
    f"area and are never averaged.\n\n"
    f"'conf' IS NOT IN THIS. The confidence score beside each candidate "
    f"in Edge Review is a review-ORDERING score — it decides what a "
    f"human looks at first, nothing more. It measured "
    f"ANTI-calibrated across methods (patch winners at 0.97–0.99 scored "
    f"IoU ~0.43 while boundary fits at 0.74 scored 0.89), so a high conf "
    f"is not a small error bar. Never quote it as an uncertainty.")


# Hover text for the engine options the Draw column exposes. Module
# constants rather than literals at the widgets, for the reason BANDS_TIP
# is one: a test can read them, and the sentence that HAS to stay true --
# the cadence guard's, which is the difference between annotating an
# event and hiding one -- sits somewhere findable.
DRAW_TIPS = {
    'logx': (
        "Log x axis — log10 when every plotted x is positive, otherwise "
        "symlog (linear near zero, log outside) so no point is dropped, "
        "and the caption names the scale it chose."),
    'logy': (
        "Log y axis — the same rule as log x, and the reason symlog "
        "exists here: this suite's currents idle NEGATIVE, so a plain log "
        "scale would drop the whole trace rather than show it."),
    'marker_key': (
        "Adds a second compact legend, lower right, naming what the open "
        "and filled markers mean — area mode only, because current and "
        "power draw one plain dot per snapshot with no open/closed "
        "distinction to explain."),
    'cadence_guard': (
        "Asks how often each run measured current and, where that is "
        "slower than 1 s, draws its breakdown X hollow with the spacing "
        "in the caption — it ANNOTATES the mark rather than SUPPRESSING "
        "it, and whether it belongs on by default is an open decision for "
        "the bench (`#264`), not a rendering preference."),
    'aggregate': (
        "One mean curve across every SELECTED run, in black, with a band "
        "that is the standard error of the mean (σ/√n) per level — not "
        "the ±1–2% instrument budget, which belongs to a single run and is "
        "suppressed here. With one run selected there is NO band and the "
        "caption says why: a band across a family needs at least two "
        "members. The curve stops at the first current-confirmed "
        "breakdown, past which the mean would mix intact and collapsed "
        "devices. Area mode only (`#268`)."),
    'aggregate_exact': (
        "Pool only the levels a run really measured, instead of "
        "interpolating every run onto the common grid. Honest but lumpy: "
        "in the campaign corpus one run steps 0.2 kV against everyone "
        "else's 0.25 and shares just 8 of 41 levels, so exact pooling "
        "makes n alternate 4/5 level to level and the band step for a "
        "reason that is an artifact of grid choice, not of the devices. "
        "Interpolation never extrapolates past a run's own range and "
        "never crosses a breakdown, and the figure prints how many "
        "values at each level were measured versus interpolated."),
    'subplots': (
        "Which of the mode's panels render — a single chosen panel "
        "becomes the figure's ONLY axes and fills the canvas instead of "
        "sitting in half a grid, and 'second' needs area mode because "
        "current and power have no second panel."),
    'title_first': (
        "Replaces the first panel's built-in heading; blank keeps the "
        "default, and this wins over Title above, which is the older name "
        "for the same panel."),
    'title_second': (
        "Replaces the second panel's built-in heading; area mode only, "
        "because current and power draw a single panel."),
}

# Hover text for the two options that describe the FILE rather than the
# drawing (`#314`). Their own dict because they belong to the Export box
# and never touch the preview -- the canvas is at screen dpi and stays
# there whichever of these is set.
EXPORT_TIPS = {
    'fmt': (
        "PNG is the default and what every figure in the handoff is. SVG "
        "is vector — enlarge it or re-letter it without touching the "
        "data. Its size follows the number of drawn ELEMENTS rather than "
        "the pixel count, which is why the confirmation names it: "
        "measured 2026-08-10, seven runs with pre/post and the mean came "
        "to 322 kB against the same figure's 310 kB PNG, but a denser one "
        "has no such promise. The tidy CSV and the figspec are written "
        "for both."),
    'dpi': (
        f"Raster resolution, {sp.DEFAULT_DPI} by default, "
        f"{sp.DPI_MIN}–{sp.DPI_MAX}. Outside that range it is REFUSED "
        f"rather than quietly clamped — a typed '30000' asks for a render "
        f"that looks exactly like a hang. Greyed under SVG because a "
        f"vector file has no dots per inch to set: the backend pins it to "
        f"72 and scales in user units, so a number here could only ever "
        f"be one that did nothing."),
}


# ---------------------------------------------------------------------------
# the controls column (`#271`)
#
# COPIED IN SPIRIT, NOT IMPORTED, from ui_widgets.ScrollableTab —
# deliberately, and for the same reason sldea_edge_gui keeps its own
# Tooltip (see the block above its class): PROJECT_HANDOFF open decision
# 2 moves the SLDEA suite into its own instrument-free repo, and this
# module is on that side of the seam (it imports sldea_edge and
# sldea_plot). `ui_widgets` is NOT, so importing it here would plant a
# cross-seam dependency for the sake of a stateless Tk idiom.
#
# It is not the same widget anyway: ScrollableTab scrolls a NOTEBOOK TAB
# and shows its bar unconditionally, while this is a fixed-width column
# beside a figure whose bar must appear only on genuine overflow — the
# `#225` decision (a bar that is always there is one more thing on
# screen that says nothing).
# ---------------------------------------------------------------------------

class ScrollColumn(ttk.Frame):
    """Fixed-width column with a vertical scrollbar ONLY when it overflows.

    Build the controls into `.body`, not into the column itself.

    Two properties make it stable, and both are the reason the naive
    version oscillates:

      * the canvas is exactly as wide as `.body` ASKS to be, and the bar's
        width is added to the COLUMN. Taking it out of the content instead
        would narrow the controls, re-wrap their labels, make them taller,
        and the bar could then never go away again.
      * the body is stretched to the canvas height when there is room to
        spare, so `expand=True` inside it still works — a scroll canvas
        otherwise pins every child to its requested height and the run
        list stops growing with the window.
    """

    SLACK = 4          # px of overflow to tolerate before showing the bar

    def __init__(self, master, padding=0):
        super().__init__(master)
        bg = ttk.Style().lookup('TFrame', 'background') or None
        self._cv = tk.Canvas(self, highlightthickness=0, borderwidth=0,
                             **({'bg': bg} if bg else {}))
        self.bar = ttk.Scrollbar(self, orient=tk.VERTICAL,
                                 command=self._cv.yview)
        self._cv.configure(yscrollcommand=self.bar.set)
        self._cv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.body = ttk.Frame(self._cv, padding=padding)
        self._win = self._cv.create_window((0, 0), window=self.body,
                                           anchor='nw')
        self.bar_shown = False
        self._geom = None
        self.body.bind('<Configure>', self._refit)
        self._cv.bind('<Configure>', self._refit)
        # The wheel is grabbed only while the pointer is over the column
        # and released on the way out, so it never steals scrolling from
        # the figure beside it (matplotlib binds its own scroll_event on
        # the canvas). bind_all is what makes the grab reach the deeply
        # nested children; the Leave release is what keeps it honest.
        self.bind('<Enter>', self._bind_wheel)
        self.bind('<Leave>', self._unbind_wheel)
        self._cv.configure(takefocus=1)
        for key, n in (('<Up>', -1), ('<Down>', 1),
                       ('<Prior>', -5), ('<Next>', 5)):
            self._cv.bind(key, lambda _e, n=n: self._scroll(n))

    # -- fit ---------------------------------------------------------------

    def _refit(self, _event=None):
        """Re-measure and show or hide the bar. Idempotent: it is bound to
        both <Configure>s and they trip each other."""
        want = self.body.winfo_reqwidth()
        need = self.body.winfo_reqheight()
        have = self._cv.winfo_height()
        geom = (want, need, have)
        if geom == self._geom:
            return
        self._geom = geom
        self._cv.config(width=want)
        self._cv.itemconfigure(self._win, width=want, height=max(need, have))
        self._cv.configure(scrollregion=(0, 0, want, max(need, have)))
        self.show_bar(need > have + self.SLACK)

    def natural_width(self):
        """The width the column needs: what the controls ask for PLUS the
        bar, whether or not it is showing right now.

        Measured off `.body`, never off the canvas: the canvas does not
        learn its width until the first <Configure>, which needs the
        window on screen, so a floor computed at construction time from
        the canvas comes out 34 px (measured) instead of 302."""
        self.update_idletasks()
        return self.body.winfo_reqwidth() + self.bar.winfo_reqwidth()

    def show_bar(self, on):
        """The `#225` rule: the bar is a REPORT of overflow, not furniture.
        Hiding it also rewinds — a column scrolled halfway down and then
        given room would otherwise keep its offset with no way to undo it."""
        if on == self.bar_shown:
            return
        self.bar_shown = on
        if on:
            self.bar.pack(side=tk.RIGHT, fill=tk.Y)
        else:
            self.bar.pack_forget()
            self._cv.yview_moveto(0)

    # -- scrolling ---------------------------------------------------------

    def _scroll(self, units):
        if self.bar_shown:                 # nothing to scroll when it fits
            self._cv.yview_scroll(units, 'units')

    def _wheel(self, event):
        if getattr(event, 'num', 0) == 4 or getattr(event, 'delta', 0) > 0:
            self._scroll(-2)
        elif getattr(event, 'num', 0) == 5 or getattr(event, 'delta', 0) < 0:
            self._scroll(2)

    def _bind_wheel(self, _event=None):
        self._cv.bind_all('<Button-4>', self._wheel)      # X11 up
        self._cv.bind_all('<Button-5>', self._wheel)      # X11 down
        self._cv.bind_all('<MouseWheel>', self._wheel)    # Windows / macOS

    def _unbind_wheel(self, _event=None):
        for seq in ('<Button-4>', '<Button-5>', '<MouseWheel>'):
            try:
                self._cv.unbind_all(seq)
            except tk.TclError:            # the window went away under us
                pass


# ---------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------

MODE_HINT = {
    'area': "Needs REVIEWED runs (Edge Review has saved areas). "
            "Two panels: mm² vs kV, and A/A₀.",
    'current': "Works on RAW runs too — measured µA vs kV, one point per "
               "snapshot, run-median baseline dotted.",
    'power': "Works on RAW runs too — |kV × (µA − run median)| in mW, "
             "offset-corrected per run.",
}


class PlotWindow:
    """The whole tool. One instance per process (the button opens a fresh
    process, exactly like 🔍 Edge Review… and 🎚 Tune params…), so there is
    no singleton to leak and closing it takes everything with it."""

    def __init__(self, root, parent_dir, preselect=(), opts=None,
                 out_dir=None, stem=None, explicit=None, remember=True):
        self.root = root
        self.parent = parent_dir
        self.runs = []                 # [(name, label)] currently listed
        self._loaded = {}              # rundir -> loaded run dict (cache)
        self._prepared = []            # what the canvas is currently showing
        self._drawn_key = None         # ...and what it was derived from
        self._redraw_after = None
        self._deadline = 0.0           # when the pending redraw is DUE
        self._window_ms = REDRAW_MS    # the quiet this burst has to make
        self._defer_until = None       # how long this burst may push it
        self._canvas_size = None       # last figure-canvas size (`#271`)
        self.min_size = (MIN_FIG_W, MIN_H)   # replaced by apply_minsize
        self._warns = []
        root.title("SLDEA plot — cross-run figures")

        # PRECEDENCE (`#275`): explicit CLI/init args > remembered >
        # defaults. `remember=False` opts a caller out of the file
        # entirely (the tests, and anything that must be reproducible).
        self.remember = remember
        o = sp.make_opts()[0]
        mem = load_options(parent_dir) if remember else {}
        self.remembered = mem
        o.update({k: v for k, v in mem.items() if k in REMEMBERED})
        if opts:
            named = explicit_opts(opts) if explicit is None else set(explicit)
            o.update({k: opts[k] for k in named if k in opts})
            # no title is ever remembered, so an explicit one is simply the
            # only one there can be -- and that holds for the two panel
            # headings exactly as it holds for the legacy --title
            for k in ('title', 'title_first', 'title_second'):
                if opts.get(k):
                    o[k] = opts[k]
        self.v_mode = tk.StringVar(value=o['mode'])
        self.v_prepost = tk.BooleanVar(value=o['prepost'])
        self.v_mean = tk.BooleanVar(value=o['mean'])
        self.v_bands = tk.BooleanVar(value=o['bands'])
        self.v_breakdown = tk.BooleanVar(value=o['breakdown'])
        self.v_vs_area = tk.BooleanVar(value=o['vs_area'])
        self.v_title = tk.StringVar(value=o['title'] or '')
        # the `#263`/`#267`/`#269`/`#270`/`#264`/`#268` engine options.
        # Every one of them reaches current_opts below: a variable that
        # the window showed but did not pass would put the tick box and
        # the figure in disagreement, which is how a CLI `--logy --gui`
        # preselection used to be thrown away by the window's own first
        # redraw.
        self.v_logx = tk.BooleanVar(value=o['logx'])
        self.v_logy = tk.BooleanVar(value=o['logy'])
        self.v_marker_key = tk.BooleanVar(value=o['marker_key'])
        self.v_cadence = tk.BooleanVar(value=o['cadence_guard'])
        self.v_aggregate = tk.BooleanVar(value=o['aggregate'])
        self.v_aggregate_exact = tk.BooleanVar(value=o['aggregate_exact'])
        self.v_subplots = tk.StringVar(value=o['subplots'])
        self.v_title_first = tk.StringVar(value=o['title_first'] or '')
        self.v_title_second = tk.StringVar(value=o['title_second'] or '')
        # the `#314` export options. Strings, both of them: the format is
        # a name and the dpi is what an operator TYPES, so it is validated
        # by the engine (sp.check_dpi, through current_opts) rather than
        # by an IntVar that raises TclError on a half-typed number.
        self.v_fmt = tk.StringVar(value=o['fmt'])
        self.v_dpi = tk.StringVar(value=str(o['dpi']))
        chosen_out = out_dir or mem.get('out_dir')
        self.v_out = tk.StringVar(
            value=chosen_out or default_out_dir(parent_dir))
        self.v_stem = tk.StringVar(value=stem or '')
        self._out_chosen = bool(chosen_out)  # did someone pick it themselves?

        self._build(root)
        self.populate(preselect)
        # AFTER populate: the floor is measured off the finished column,
        # and the run list and the parent-path label are part of it.
        self.apply_minsize()
        # remember on the way out (`#275`). Closing is where a set of
        # options is finished with; Export saves too, because that is the
        # moment someone committed to them.
        try:
            root.protocol('WM_DELETE_WINDOW', self._closing)
        except tk.TclError:                # not a toplevel to ask
            pass

    # -- construction ------------------------------------------------------

    def _build(self, root):
        from matplotlib.backends.backend_tkagg import (FigureCanvasTkAgg,
                                                       NavigationToolbar2Tk)
        from matplotlib.figure import Figure

        # The controls scroll when the window is too short for them
        # (`#271`): every control below the run list — including 💾 Export,
        # the whole point of the tool — used to be cut off with no bar and
        # no way to reach it.
        self.column = ScrollColumn(root, padding=8)
        self.column.pack(side=tk.LEFT, fill=tk.Y)
        left = self.column.body
        right = ttk.Frame(root)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # --- runs
        rf = ttk.LabelFrame(left, text="Runs (pick several)", padding=6)
        rf.pack(fill=tk.BOTH, expand=True)
        self.lbl_parent = ttk.Label(rf, text='', foreground='#666',
                                    wraplength=260, justify=tk.LEFT)
        self.lbl_parent.pack(fill=tk.X)
        box = ttk.Frame(rf)
        box.pack(fill=tk.BOTH, expand=True, pady=(4, 4))
        sb = ttk.Scrollbar(box, orient=tk.VERTICAL)
        # EXTENDED, not BROWSE: several runs on one figure is the reason
        # this tool exists, so the picker must be able to say so.
        # Ctrl/Shift-click and drag all work.
        self.run_box = tk.Listbox(box, selectmode=tk.EXTENDED, height=12,
                                  exportselection=False,
                                  yscrollcommand=sb.set)
        sb.config(command=self.run_box.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.run_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.run_box.bind('<<ListboxSelect>>', lambda _e: self.schedule())
        brow = ttk.Frame(rf)
        brow.pack(fill=tk.X)
        ttk.Button(brow, text="Browse…", command=self._browse).pack(
            side=tk.LEFT)
        ttk.Button(brow, text="Select all", command=self._select_all).pack(
            side=tk.LEFT, padx=6)
        ttk.Label(rf, foreground='#666', wraplength=260, justify=tk.LEFT,
                  text="✓ processed = Edge Review saved areas for that "
                       "run.").pack(fill=tk.X, pady=(4, 0))

        # --- mode
        mf = ttk.LabelFrame(left, text="Mode", padding=6)
        mf.pack(fill=tk.X, pady=(8, 0))
        for m in sp.MODES:
            ttk.Radiobutton(mf, text=m, value=m, variable=self.v_mode,
                            command=self._mode_changed).pack(anchor=tk.W)
        self.lbl_mode = ttk.Label(mf, foreground='#666', wraplength=260,
                                  justify=tk.LEFT)
        self.lbl_mode.pack(fill=tk.X, pady=(4, 0))

        # --- draw options
        df = ttk.LabelFrame(left, text="Draw", padding=6)
        df.pack(fill=tk.X, pady=(8, 0))
        ttk.Checkbutton(df, text="pre/post separately "
                                 "(post solid, pre dashed)",
                        variable=self.v_prepost,
                        command=self._toggled).pack(anchor=tk.W)
        # "…and the mean line" is a CHILD option: without separated
        # pre/post lines the single drawn line already IS the level mean
        # (draw_area: `if opts['mean'] or not opts['prepost']`), so the
        # toggle only means something on top of them — indented and
        # disabled to say so (operator review 2026-08-07).
        self.cb_mean = ttk.Checkbutton(df, text="…and the mean line on top",
                                       variable=self.v_mean,
                                       command=self.schedule)
        self.cb_mean.pack(anchor=tk.W, padx=(18, 0))
        # the two percentages come from sldea_plot's constants, here and
        # in BANDS_TIP, so the label cannot outlive the band it names
        self.cb_bands = ttk.Checkbutton(
            df, text=f"uncertainty bands (±{sp.MACHINE_BAND_PCT:g}% / "
                     f"±{sp.TRACED_BAND_PCT:g}%)",
            variable=self.v_bands, command=self.schedule)
        self.cb_bands.pack(anchor=tk.W)
        # hover says WHERE THE NUMBERS COME FROM, and that conf is not one
        # of them (`#266`)
        self.tip_bands = add_tooltip(self.cb_bands, BANDS_TIP)
        # the cross-run aggregate (`#268`). It sits directly under the
        # bands row because it REPLACES what that band means: the ±1–2%
        # budget is one run's instrument error, and the aggregate's band
        # is the standard error of the mean across runs. Area mode only —
        # make_opts refuses the pair, so current_opts neutralises it the
        # way it does --vs-area, and the box greys rather than vanishing.
        self.cb_aggregate = ttk.Checkbutton(
            df, text="cross-run aggregate (mean + SEM band)",
            variable=self.v_aggregate, command=self._toggled)
        self.cb_aggregate.pack(anchor=tk.W)
        add_tooltip(self.cb_aggregate, DRAW_TIPS['aggregate'])
        # a CHILD of the aggregate, for the same reason the mean line is a
        # child of pre/post: nothing outside `if opts['aggregate']` reads
        # it, so on its own it is a control that does nothing.
        self.cb_aggregate_exact = ttk.Checkbutton(
            df, text="…pooling exact levels only (no interpolation)",
            variable=self.v_aggregate_exact, command=self.schedule)
        self.cb_aggregate_exact.pack(anchor=tk.W, padx=(18, 0))
        add_tooltip(self.cb_aggregate_exact, DRAW_TIPS['aggregate_exact'])
        # the open/closed marker key (`#267`). Area mode only -- draw_area
        # is the only drawer that calls _marker_key, because current and
        # power draw one plain dot per snapshot and a key there would
        # claim a distinction the figure does not make. GREYED rather than
        # hidden in those modes: a control that vanishes says nothing
        # about why it went.
        self.cb_marker_key = ttk.Checkbutton(
            df, text="marker key (open = hand-traced)",
            variable=self.v_marker_key, command=self.schedule)
        self.cb_marker_key.pack(anchor=tk.W)
        add_tooltip(self.cb_marker_key, DRAW_TIPS['marker_key'])
        ttk.Checkbutton(df, text="breakdown marks (recomputed)",
                        variable=self.v_breakdown,
                        command=self._toggled).pack(anchor=tk.W)
        # the cadence guard (`#264`) is a CHILD of the breakdown marks for
        # exactly the reason the mean line is a child of pre/post:
        # sldea_plot consults coarse_cadence only inside
        # `if opts['breakdown']`, so with the X marks off there is nothing
        # left for it to annotate. Indented and disabled to say so.
        self.cb_cadence = ttk.Checkbutton(
            df, text="…and flag coarse current sampling",
            variable=self.v_cadence, command=self.schedule)
        self.cb_cadence.pack(anchor=tk.W, padx=(18, 0))
        add_tooltip(self.cb_cadence, DRAW_TIPS['cadence_guard'])
        self.cb_vs_area = ttk.Checkbutton(
            df, text="x axis = active area (needs reviewed runs)",
            variable=self.v_vs_area, command=self.schedule)
        self.cb_vs_area.pack(anchor=tk.W)
        # the log scales (`#263`) share ONE row: two independent flags
        # with three-character labels, and the column is tall already.
        lrow = ttk.Frame(df)
        lrow.pack(fill=tk.X)
        for text, var, key in (("log x", self.v_logx, 'logx'),
                               ("log y", self.v_logy, 'logy')):
            cb = ttk.Checkbutton(lrow, text=text, variable=var,
                                 command=self.schedule)
            cb.pack(side=tk.LEFT, padx=(0, 12))
            add_tooltip(cb, DRAW_TIPS[key])
        # which panel(s) render (`#270`). Radios rather than a combobox:
        # three fixed choices, all three worth reading at once, and it
        # costs the same single row either way.
        prow = ttk.Frame(df)
        prow.pack(fill=tk.X, pady=(2, 0))
        lbl_panels = ttk.Label(prow, text="Panels:")
        lbl_panels.pack(side=tk.LEFT)
        add_tooltip(lbl_panels, DRAW_TIPS['subplots'])
        self.rb_subplots = {}
        for name in sp.SUBPLOTS:
            rb = ttk.Radiobutton(prow, text=name, value=name,
                                 variable=self.v_subplots,
                                 command=self._toggled)
            rb.pack(side=tk.LEFT, padx=(6, 0))
            add_tooltip(rb, DRAW_TIPS['subplots'])
            self.rb_subplots[name] = rb
        # the headings (`#269`). --title predates the per-panel pair and
        # has always meant the FIRST panel, so it keeps its row and its
        # name; the two below are its precise successors and beat it.
        # sldea_plot._panel_title owns that rule -- this only exposes it.
        self.e_title = self._title_row(df, "Title:", self.v_title)
        self.e_title_first = self._title_row(
            df, "Panel 1:", self.v_title_first, DRAW_TIPS['title_first'])
        self.e_title_second = self._title_row(
            df, "Panel 2:", self.v_title_second, DRAW_TIPS['title_second'])

        # --- export
        xf = ttk.LabelFrame(left, text="Export (figure + tidy CSV)",
                            padding=6)
        xf.pack(fill=tk.X, pady=(8, 0))
        # format and resolution (`#314`) sit HERE and not in Draw: they
        # change the file, never the picture, and the preview canvas is at
        # screen dpi whatever they say. One row for both, because the Draw
        # column is what `#271`'s measured floor is taken from.
        frow = ttk.Frame(xf)
        frow.pack(fill=tk.X, pady=(0, 4))
        lbl_fmt = ttk.Label(frow, text="Format:")
        lbl_fmt.pack(side=tk.LEFT)
        add_tooltip(lbl_fmt, EXPORT_TIPS['fmt'])
        self.rb_fmt = {}
        for name in sp.FORMATS:
            rb = ttk.Radiobutton(frow, text=name.upper(), value=name,
                                 variable=self.v_fmt,
                                 command=self._format_changed)
            rb.pack(side=tk.LEFT, padx=(6, 0))
            add_tooltip(rb, EXPORT_TIPS['fmt'])
            self.rb_fmt[name] = rb
        self.lbl_dpi = ttk.Label(frow, text="dpi:")
        self.lbl_dpi.pack(side=tk.LEFT, padx=(12, 0))
        # a Spinbox says the range is bounded before anything is typed;
        # the refusal outside it is still the engine's, since the box can
        # be typed into freely
        self.sb_dpi = ttk.Spinbox(frow, from_=sp.DPI_MIN, to=sp.DPI_MAX,
                                  increment=50, width=6,
                                  textvariable=self.v_dpi,
                                  command=self._show_targets)
        self.sb_dpi.pack(side=tk.LEFT, padx=(4, 0))
        # NO redraw binding, deliberately: the dpi cannot change the
        # preview, and a redraw per keystroke would blank the figure on
        # the '5' of '500' while the number is still half typed
        self.sb_dpi.bind('<KeyRelease>', lambda _e: self._show_targets())
        for w in (self.lbl_dpi, self.sb_dpi):
            add_tooltip(w, EXPORT_TIPS['dpi'])
        orow = ttk.Frame(xf)
        orow.pack(fill=tk.X)
        ttk.Label(orow, text="Folder:").pack(side=tk.LEFT)
        ttk.Entry(orow, textvariable=self.v_out).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        ttk.Button(orow, text="…", width=3, command=self._browse_out).pack(
            side=tk.LEFT)
        srow = ttk.Frame(xf)
        srow.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(srow, text="Name:").pack(side=tk.LEFT)
        e_stem = ttk.Entry(srow, textvariable=self.v_stem)
        e_stem.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        e_stem.bind('<KeyRelease>', lambda _e: self._show_targets())
        self.lbl_targets = ttk.Label(xf, foreground='#666', wraplength=260,
                                     justify=tk.LEFT)
        self.lbl_targets.pack(fill=tk.X, pady=(4, 0))
        self.btn_export = tk.Button(xf, text="💾 Export figure + CSV",
                                    command=self._export,
                                    font=('TkDefaultFont', 9, 'bold'))
        self.btn_export.pack(fill=tk.X, pady=(6, 0))

        # --- messages: the CLI's warnings, which are the tool's whole
        # safety story (scale eras, stale brands, mixed conventions). A
        # window that swallowed them would be strictly less safe than the
        # command line it replaces.
        #
        # PACKED BEFORE THE FIGURE, side=BOTTOM (`#271`). pack fills each
        # slave's request from the cavity IN ORDER, so with the figure
        # first it took its full requested height and the toolbar and this
        # pane were pushed off the bottom of a short window — measured: at
        # 900x560 both were unmapped, i.e. the warnings were gone and
        # nothing said so. Claiming their space first makes the FIGURE the
        # thing that shrinks, which is what expand=True already promised.
        self.msg = tk.Text(right, height=6, wrap='word', state='disabled')
        self.msg.pack(side=tk.BOTTOM, fill=tk.X)

        # --- the click-through line (`#274`). It doubles as the report of
        # what the last double-click resolved to: the feature is invisible
        # otherwise, and a click that silently opened a window somewhere
        # would be worse than one that did nothing.
        self.lbl_click = ttk.Label(right, foreground='#666', anchor=tk.W,
                                   text=CLICK_HINT)
        self.lbl_click.pack(side=tk.BOTTOM, fill=tk.X, padx=6, pady=(2, 2))

        # --- canvas
        self.fig = Figure(figsize=sp.FIGSIZE['area'], dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        widget = self.canvas.get_tk_widget()
        self.toolbar = NavigationToolbar2Tk(self.canvas, right,
                                            pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        # add='+' IS THE `#271` FIX, not a style choice. FigureCanvasTkAgg
        # binds <Configure> on this same widget to its own `resize`, which
        # is the ONLY thing that tells the Figure how many inches it now
        # has. A plain bind() REPLACES that binding (verified on
        # matplotlib 3.10.9: the tag holds one script, not a list), so the
        # figure stayed 12.6x5.4 in forever — laid out by tight_layout
        # against a size the window had not had since it opened, clipped
        # on the right and blank below at EVERY size including the
        # default. Our own handler then re-runs tight_layout against the
        # new size; the coalescing keeps a drag from redrawing per pixel.
        widget.bind('<Configure>', self._canvas_configured, add='+')
        # DOUBLE-click, not single: single-click belongs to the toolbar's
        # pan and zoom rectangles, and launching a program on a stray
        # click while someone is dragging a zoom box would be hostile.
        self.canvas.mpl_connect('button_press_event', self.on_click)

        # LAST: the greying rules span both boxes now (`#314` greys the dpi
        # from the format radios in the Export frame), so the first sync
        # can only run once every widget it touches exists.
        self._sync_enabled()

    def _title_row(self, master, label, var, tip=None):
        """One 'Label: [entry]' heading row in the Draw column. -> the
        Entry.

        There are three of them now (the legacy --title and the two
        per-panel headings, `#269`), so the row pattern is written once
        and the label width is fixed in characters -- the three entries
        line up at whatever the theme's font is, which a hand-repeated
        row does not."""
        row = ttk.Frame(master)
        row.pack(fill=tk.X, pady=(4, 0))
        lbl = ttk.Label(row, text=label, width=8)
        lbl.pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        entry.bind('<KeyRelease>', lambda _e: self.schedule())
        if tip:
            add_tooltip(lbl, tip)
            add_tooltip(entry, tip)
        return entry

    # -- run list ----------------------------------------------------------

    def populate(self, preselect=()):
        self.runs = list_runs(self.parent)
        self.run_box.delete(0, tk.END)
        for _name, label in self.runs:
            self.run_box.insert(tk.END, label)
        self.lbl_parent.config(text=self.parent)
        want = [i for i, (name, _l) in enumerate(self.runs)
                if name in set(preselect)]
        for i in want:
            self.run_box.selection_set(i)
        if not self.runs:
            self._set_messages(
                [f"no runs (directories holding data.csv) in {self.parent} "
                 f"— use Browse… to point at a folder of runs"])
        self._mode_changed()

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.parent or DEFAULT_PARENT)
        if not d:
            return
        parent, name = split_target(d)
        self.parent = parent or d
        # the output folder follows the runs UNTIL the user picks one of
        # their own: browsing to another campaign should not quietly file
        # its figures under the previous campaign, but neither should it
        # override a folder someone deliberately chose
        if not self._out_chosen:
            self.v_out.set(default_out_dir(self.parent))
        self.populate([name] if name else [])
        self.schedule()

    def _select_all(self):
        self.run_box.selection_set(0, tk.END)
        self.schedule()

    def selected_dirs(self):
        return [os.path.join(self.parent, self.runs[i][0])
                for i in self.run_box.curselection()]

    # -- options -----------------------------------------------------------

    def remember_now(self):
        """Write the current options under the current parent (`#275`).
        -> the file written, or None. Never raises."""
        if not self.remember:
            return None
        opts, err = self.current_opts()
        if err:                       # an invalid combination is not a
            return None               # preference worth restoring
        return save_options(self.parent, opts,
                            self.v_out.get().strip()
                            if self._out_chosen else None)

    def _closing(self):
        """Remember, cancel, destroy -- in that order.

        remember_now FIRST (`#275`): it reads the live widgets, and a
        destroyed root has none.

        Then the pending debounced redraw, BEFORE destroy. A close landing
        inside REDRAW_MS of a click -- picking a run and reaching straight
        for the X -- left one queued at a command Tk had just deleted, and
        its background error handler printed `invalid command name
        ...redraw` on the console (`#283`). Harmless, but it is exactly
        the kind of line a real failure hides behind, which is why the
        test suite's own _shut() helper has been sweeping it up by hand.

        The only other after() in this module is Tooltip's hover timer,
        and it cancels itself: Tooltip binds <Destroy> to _hide. Nothing
        else here queues a callback, so this is the whole sweep -- and it
        stays a list of THIS window's ids rather than 'after info', which
        on a shared root would cancel someone else's."""
        self.remember_now()
        self._cancel_redraw()
        self.root.destroy()

    def _cancel_redraw(self):
        """Drop the pending debounced redraw, if any. Never raises -- an
        id Tk has already fired or forgotten is not an error to a caller
        on its way out."""
        if self._redraw_after is not None:
            try:
                self.root.after_cancel(self._redraw_after)
            except Exception:
                pass
            self._redraw_after = None

    def _sync_enabled(self):
        """Grey every control the current mode and panel selection make
        INERT, and un-grey it the moment it means something again.

        Greyed rather than hidden, throughout: a control that vanishes
        tells an operator nothing about why it went, while a greyed one
        with a tooltip says what would bring it back. Every rule below is
        sldea_plot's — each names the engine code that makes the option a
        no-op — so the column cannot drift from what the figure does."""
        area = self.v_mode.get() == 'area'
        which = self.v_subplots.get()

        def live(widget, on):
            widget.config(state='normal' if on else 'disabled')

        # without separated pre/post lines the single drawn line already IS
        # the level mean (draw_area: `if opts['mean'] or not opts['prepost']`)
        live(self.cb_mean, self.v_prepost.get())
        # coarse_cadence is consulted only inside `if opts['breakdown']`
        live(self.cb_cadence, self.v_breakdown.get())
        # _marker_key is called by draw_area alone
        live(self.cb_marker_key, area)
        # the aggregate pools PER-LEVEL curves, which only area mode has;
        # make_opts refuses the other pairing outright
        live(self.cb_aggregate, area)
        # nothing outside `if opts['aggregate']` reads the grid toggle
        live(self.cb_aggregate_exact, area and self.v_aggregate.get())
        # --vs-area is meaningless in area mode (the x axis IS area there);
        # the CLI refuses the combination, so the window does not offer it
        live(self.cb_vs_area, not area)
        # 'second' names a panel only area mode has
        live(self.rb_subplots['second'], area)
        # a heading only lands on a panel that RENDERS: --title and
        # --title-first reach the first panel, --title-second the second,
        # and area_axes creates neither when `#270` switched it off
        first_drawn = not (area and which == 'second')
        live(self.e_title, first_drawn)
        live(self.e_title_first, first_drawn)
        live(self.e_title_second, area and which != 'first')
        # the dpi is dots per INCH of raster, and SVG has no raster: the
        # backend pins the figure to 72 dpi and scales in user units, so
        # _savefig does not pass one at all. Greyed rather than silently
        # ignored, which is what `#314` asked for, and greyed rather than
        # hidden for the reason every other rule here is (`#314`).
        raster = self.v_fmt.get() != 'svg'
        live(self.sb_dpi, raster)
        live(self.lbl_dpi, raster)

    def _format_changed(self):
        """PNG <-> SVG: the dpi field goes live or grey, and the target
        filenames change extension. No redraw -- the preview canvas is at
        screen dpi and neither option can reach it."""
        self._sync_enabled()
        self._show_targets()

    def _toggled(self):
        """A control whose own state changes what ELSE is live: re-sync
        the column, then redraw like any other change."""
        self._sync_enabled()
        self.schedule()

    def _mode_changed(self):
        mode = self.v_mode.get()
        self.lbl_mode.config(text=MODE_HINT.get(mode, ''))
        # 'second' asks for a panel current/power do not have, and
        # make_opts refuses that pair. The radio is SNAPPED back rather
        # than only greyed, because a greyed-but-still-filled 'second'
        # beside a two-panel figure would be a control contradicting the
        # picture — a radio group always shows one choice as taken, so an
        # inert one cannot just sit there the way an inert checkbox can.
        # (current_opts neutralises it too: that is what keeps the pair
        # from ever reaching make_opts, whatever set the variable.)
        if mode != 'area' and self.v_subplots.get() == 'second':
            self.v_subplots.set('both')
        self._toggled()

    def current_opts(self):
        """-> (opts, error). Same builder the CLI uses, so the window
        cannot invent an options combination the CLI would refuse.

        EVERY option the column shows is passed through. One that had a
        widget but no argument here would redraw on the DEFAULT while the
        widget went on showing something else — which is precisely what
        used to happen to `python sldea_plot.py --logy --gui`: the flag
        reached the window, and the window's own first redraw threw it
        away."""
        area = self.v_mode.get() == 'area'
        which = self.v_subplots.get()
        return sp.make_opts(
            mode=self.v_mode.get(),
            vs_area=self.v_vs_area.get() and not area,
            prepost=self.v_prepost.get(), mean=self.v_mean.get(),
            bands=self.v_bands.get(), breakdown=self.v_breakdown.get(),
            title=self.v_title.get().strip() or None,
            logx=self.v_logx.get(), logy=self.v_logy.get(),
            marker_key=self.v_marker_key.get(),
            cadence_guard=self.v_cadence.get(),
            # area mode only, and make_opts REFUSES the other pairing --
            # neutralised here exactly as vs_area is above, so a mode
            # switch produces a figure rather than an error message
            aggregate=self.v_aggregate.get() and area,
            aggregate_exact=self.v_aggregate_exact.get(),
            # 'second' outside area mode is the one combination make_opts
            # refuses. Neutralised to the default exactly as vs_area is
            # above: an error message where the figure goes is not what a
            # mode switch should produce.
            subplots='both' if which == 'second' and not area else which,
            title_first=self.v_title_first.get().strip() or None,
            title_second=self.v_title_second.get().strip() or None,
            # `#314`. NOT neutralised under SVG the way vs_area and
            # subplots are above: a dpi beside a vector format is inert,
            # not illegal, and make_opts takes the pair happily. Keeping
            # the typed value means the figspec records what was chosen
            # and `--from-spec --format png` re-renders at it, instead of
            # at a default nobody asked for. A blank box is the absence of
            # a request, so check_dpi reads it as the default; a bad or
            # out-of-range one is REFUSED here, in the CLI's own words.
            fmt=self.v_fmt.get(), dpi=self.v_dpi.get())

    # -- drawing -----------------------------------------------------------

    def schedule(self, _event=None, ms=REDRAW_MS):
        """Coalesce redraws: dragging through the run list fires a select
        event per row, a resize drag fires <Configure> per redraw, and
        each redraw is a full matplotlib pass. `ms` is how much quiet the
        burst has to produce before the redraw lands -- a click's worth by
        default, a resize's when the resize handler asks for it (`#316`).

        Every caller comes through here, so this is also where the
        deferral budget restarts: a fresh event is a new burst, whatever
        the last one was still waiting on."""
        self._defer_until = None
        self._arm(ms)

    def _arm(self, ms):
        """Queue the coalesced redraw and REMEMBER WHEN IT IS DUE. That
        deadline is the whole `#316` mechanism -- without it the callback
        cannot tell a quiet loop from a blocked one."""
        self._cancel_redraw()          # one canceller, shared with _closing
        self._window_ms = ms
        self._deadline = time.monotonic() + ms / 1000.0
        if self._defer_until is None:
            self._defer_until = self._deadline + MAX_DEFER_MS / 1000.0
        self._redraw_after = self.root.after(ms, self._debounced)

    def _debounced(self):
        """Redraw -- or defer once more, because the burst is still
        running (`#316`).

        A timer that comes up LATE waited on a blocked event loop, and
        during a resize drag it always does: matplotlib's own resize
        handler renders the figure at the new size before Tk gets to
        service anything else. Firing there redraws INTO a drag that is
        still going, which is how 6 <Configure> used to cost 6 full
        redraws. Re-arming instead means the redraw lands once, when the
        drag stops -- and the ordinary case is untouched, because a
        toggle blocks nothing and its timer is ~5 ms late, not 250."""
        self._redraw_after = None
        now = time.monotonic()
        if ((now - self._deadline) * 1000.0 > LATE_MS
                and now < self._defer_until):
            self._arm(self._window_ms)
            return
        self._defer_until = None
        self.redraw()

    def _canvas_configured(self, event):
        """The figure canvas changed size — relayout, coalesced (`#271`).

        SIZE, not every <Configure>: the event also fires when the widget
        merely MOVES (the scrollbar appearing beside it shifts it by its
        own width), and a full prepare_runs + draw for a move is work
        nobody asked for.

        RESIZE_MS, not REDRAW_MS: a drag's events are hundreds of
        milliseconds apart because servicing one costs that much, so the
        click-sized window let a drag redraw straight through it
        (`#316`)."""
        size = (event.width, event.height)
        if size == self._canvas_size:
            return
        self._canvas_size = size
        self.schedule(None, RESIZE_MS)

    def apply_minsize(self):
        """Floor the window so the layout cannot collapse (`#271`).

        The width is MEASURED — the controls column asks for whatever the
        theme and DPI make it, and a hardcoded number that is right on the
        analysis PC is wrong on a high-DPI bench PC. A window this size is
        cramped but every control is reachable (the column scrolls) and the
        figure is still a figure.

        -> the (width, height) it set, also kept on `self.min_size`."""
        try:
            self.root.update_idletasks()
            self.min_size = (self.column.natural_width() + MIN_FIG_W,
                             MIN_H)
            self.root.minsize(*self.min_size)
        except tk.TclError:                # no window manager to ask
            pass
        return self.min_size

    def _load(self, rundir, warn):
        """load_run, cached -- the toggles redraw constantly and re-reading
        every run's CSV (and recomputing its breakdown flags) on each tick
        made the window feel broken. Warnings from the first load are
        replayed so a cached run still reports its stale brands."""
        if rundir not in self._loaded:
            msgs = []
            self._loaded[rundir] = (sp.load_run(rundir, msgs.append), msgs)
        run, msgs = self._loaded[rundir]
        for m in msgs:
            warn(m)
        return run

    def _figure_key(self):
        """What the figure on screen was DERIVED FROM: the run set and
        every option that reaches the drawing. Two redraws with the same
        key can only differ in the size of the canvas they land on."""
        opts, err = self.current_opts()
        return (tuple(self.selected_dirs()), err,
                None if err else tuple(sorted(opts.items())))

    def relayout(self):
        """Re-run the last draw's layout at the canvas's new size, WITHOUT
        rebuilding the figure (`#316`).

        A resize does not change a single number on the figure; it changes
        how many inches the numbers have. Rebuilding to find that out cost
        298 ms of artist construction over 13 runs and a second full
        render on top of the one matplotlib's own resize handler had
        already done -- measured, and the larger half of a drag's whole
        bill. -> True when it could be done.

        draw_idle, not draw: matplotlib has a render pending for this same
        resize, and this merges into it instead of adding a second."""
        if not sp.relayout(self.fig):
            return False
        self.canvas.draw_idle()
        return True

    def redraw(self):
        self._redraw_after = None
        # the click line goes back to being a hint: what it says otherwise
        # is which frame the LAST double-click opened, and that answer
        # belongs to the figure that was on screen when it was clicked --
        # at the size it was then, which is why a relayout takes it down
        # too: the point it named has moved
        self.lbl_click.config(text=CLICK_HINT)
        # A resize reaches here like everything else, and is told apart
        # like this rather than by a flag: what makes it cheap is that
        # nothing the figure was derived from has changed, and a flag
        # would have to be right about that. Interleave a tick box with
        # the drag and the key moves, so the rebuild happens.
        if self._drawn_key is not None and self._figure_key() == \
                self._drawn_key and self.relayout():
            return
        opts, err = self.current_opts()
        self._drawn_key = None         # nothing survives the clear below
        self.fig.clear()
        if err:
            self._prepared = []
            self._set_messages([err])
            self.canvas.draw()
            return
        dirs = self.selected_dirs()
        warns = []
        if not dirs:
            self._prepared = []
            self._hint("Pick one or more runs on the left.")
            self._set_messages(warns)
            self._show_targets()
            return
        # prepare_runs re-resolves and re-guards on every redraw (the mode
        # changes what counts as plottable), but loading goes through the
        # cache
        # pre-2026-07-28 areas (the 2.3-2.7x scale-bug era) are refused
        # outright in the window: the campaign dataset is reprocessed, so
        # the override checkbox was dropped (operator call 2026-08-07).
        # The CLI keeps --allow-suspect-scale for archaeology.
        runs = sp.prepare_runs(dirs, opts, warns.append,
                               allow_suspect=False,
                               load=self._load)
        self._prepared = runs
        if not runs:
            self._hint("Nothing to plot with these runs in this mode.\n"
                       "See the messages below.")
        else:
            sp.draw(self.fig, runs, opts, warns.append)
            # only a real figure can be re-laid-out instead of rebuilt:
            # the hint above draws no axes and sp.relayout says so
            self._drawn_key = self._figure_key()
        self._set_messages(warns)
        self._show_targets()
        self.canvas.draw()

    # -- click-through (`#274`) --------------------------------------------

    def on_click(self, event):
        """matplotlib button_press_event -> the frame under the pointer.

        Returns what it resolved (run, row) so the live smoke and the
        tests can see the whole chain without watching for a process."""
        if not getattr(event, 'dblclick', False) or event.inaxes is None:
            return None
        if not self._prepared:
            return None
        opts, err = self.current_opts()
        if err:
            return None
        try:
            panel = list(self.fig.axes).index(event.inaxes)
        except ValueError:                 # the axes was cleared under us
            return None
        hit = nearest_point(event.inaxes,
                            plot_points(self._prepared, opts, panel),
                            event.x, event.y)
        if hit is None:
            self.lbl_click.config(
                text=f"no data point within {PICK_PX} px of that "
                     f"double-click — aim at a marker")
            return None
        run, row, _dist = hit
        self.open_in_edge_review(run, row)
        return run, row

    def open_in_edge_review(self, run, row):
        """Its own process, exactly like the app's 🔍 Edge Review… button
        (gui.py `_sldea_open_edge_review`) and the two other sibling
        launches: this window keeps its figure, and the review outlives
        it. -> the argv used, or None if it could not start."""
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'sldea_edge_gui.py')
        # row['index'] is the 0-BASED CSV row. Edge Review shows 1-based
        # FRAMES and does the translation itself (see its goto_row) —
        # `#255` is on record for what doing it at the wrong end costs.
        cmd = [sys.executable, script, run['dir'],
               '--goto', str(row['index'])]
        try:
            subprocess.Popen(cmd, start_new_session=True)
        except Exception as e:
            messagebox.showerror("Edge Review",
                                 f"Could not launch Edge Review:\n{e}")
            return None
        snap = str(row.get('snapshot') or '?')
        self.lbl_click.config(
            text=f"→ Edge Review opening on {run['name']}, snapshot "
                 f"{snap} (data row {row['index']})")
        return cmd

    def _hint(self, text):
        ax = self.fig.add_subplot(111)
        ax.axis('off')
        ax.text(0.5, 0.5, text, ha='center', va='center', color='#999',
                fontsize=13)
        self.canvas.draw()

    def _set_messages(self, warns):
        self._warns = list(warns)
        self.msg.config(state='normal')
        self.msg.delete('1.0', tk.END)
        if warns:
            self.msg.insert(tk.END, '\n'.join('warning: ' + w for w in warns))
        self.msg.config(state='disabled')

    # -- export ------------------------------------------------------------

    def _browse_out(self):
        d = filedialog.askdirectory(initialdir=self.v_out.get() or os.getcwd())
        if d:
            self.v_out.set(d)
            self._out_chosen = True
            self._show_targets()

    def _show_targets(self):
        """Name every file BEFORE the click. The CLI prints what it wrote;
        a window that only said 'Saved' would be a step backwards.

        It is also where a refused dpi surfaces while it is being typed
        (`#314`): the message goes here rather than into the figure pane,
        because the preview is not what an unusable dpi spoils."""
        opts, err = self.current_opts()
        mode = self.v_mode.get() if err else opts['mode']
        fmt = self.v_fmt.get() if err else opts['fmt']
        if fmt not in sp.FORMATS:                  # only via a stale config
            fmt = sp.DEFAULT_FORMAT
        img, csvp = sp.output_paths(self.v_out.get(), self.v_stem.get(),
                                    mode, fmt)
        lines = [f"→ {os.path.basename(img)}",
                 f"→ {os.path.basename(csvp)}",
                 f"→ {os.path.basename(sp.figspec_path(img))}"]
        if err:
            lines.append(f"REFUSED: {err}")
        self.lbl_targets.config(text='\n'.join(lines))
        return img, csvp

    def _export(self):
        opts, err = self.current_opts()
        if err:
            messagebox.showwarning("Plot", err)
            return
        if not self._prepared:
            messagebox.showwarning(
                "Plot", "Nothing is plotted — pick runs that work in this "
                        "mode first (the messages under the figure say why "
                        "a run was skipped).")
            return
        out_dir = self.v_out.get().strip()
        if not out_dir:
            messagebox.showwarning("Plot", "Choose an output folder.")
            return
        warns = list(self._warns)
        try:
            img, csvp = sp.export(self._prepared, opts, out_dir,
                                  self.v_stem.get(), warns.append)
        except OSError as e:
            messagebox.showerror("Plot", f"Could not write the figure:\n{e}")
            return
        self._set_messages(warns)
        self.remember_now()          # they committed to these options
        messagebox.showinfo(
            "Exported",
            # the format, the dpi where it means anything, and the SIZE --
            # an SVG's is the one thing about an export that does not
            # follow from the settings, since it counts drawn elements
            # rather than pixels (`#314`, and describe_output has the
            # measurement)
            f"Figure ({sp.describe_output(img, opts)}) and its tidy "
            f"per-snapshot CSV:\n\n{img}\n{csvp}\n\nThe CSV is the "
            f"figure's evidence — keep the pair together.")


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------

def launch(args=(), opts=None, out_dir=None, stem=None, explicit=None,
           remember=True):
    """Open the window. Returns an exit code (0).

    `explicit` names the options the CALLER actually set, for the `#275`
    precedence rule (explicit > remembered > defaults). Left None it is
    inferred by diffing `opts` against sldea_plot's defaults -- see
    explicit_opts for what that can and cannot tell apart."""
    parent, preselect = initial_state(args)
    root = tk.Tk()
    PlotWindow(root, parent, preselect, opts=opts, out_dir=out_dir,
               stem=stem, explicit=explicit, remember=remember)
    root.mainloop()
    return 0


def main(argv):
    if argv and argv[0] in ('-h', '--help'):
        print(USAGE)
        return 0
    return launch(argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
