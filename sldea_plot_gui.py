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
    stale file can only cost the memory, never the window. With runs
    from SEVERAL folders on one figure (`#323`) the memory is keyed on
    the FIRST folder, and the window says which one above the run list;
  * each empty heading box shows, in grey, the heading that panel will
    actually carry (`#315`) -- a HINT and never a value, so blank still
    means 'no override' and no derived wording can reach the options file
    or an exported figspec. See the block above HINT_FG;
  * runs can be put in named GROUPS (`#313`), and the cross-run aggregate
    then draws one mean per group -- carbon black against P3, two lines
    on one panel -- with a tick box that hides the contributing runs so
    the panel carries the comparison and not the thicket. The grouping is
    the operator's; nothing is read from setup.txt, which is why it works
    on every run in the corpus and the parked `Electrode family:` half of
    `#268` does not.
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
    """-> ([parent folders, first one first], [run DIRECTORIES to
    preselect]).

    Several run arguments preselect several runs -- the whole point of the
    tool is more than one run on a figure.

    IT USED TO RETURN ONE PARENT (`#323`). The first argument picked it
    and every argument living anywhere else was silently dropped: the
    window listed one folder, so a run from a second one had nowhere to
    appear. That is not a listing quirk, it is the reason the comparison
    the campaign exists for could not be drawn at all -- carbon black
    lives under `Upload 20260805\\SL Ramp Test Initial CB` and the P3
    family under `Upload 20260804\\SLDEA_data (1)`, and no single parent
    contains both. Now every argument's parent joins the list, in
    argument order, and the preselection is by DIRECTORY rather than by
    name, because two runs in different parents can share a name and a
    name is no longer an identity here.

    The FIRST parent stays special, and only for the two things that need
    a single answer: the remembered-options key and the default output
    folder. Both say so where they are used, rather than merging several
    parents' state into something no operator asked for."""
    parents, preselect = [], []
    for a in args or ():
        p, name = split_target(a)
        if p is None:
            continue
        if p not in parents:
            parents.append(p)
        if name:
            preselect.append(os.path.join(p, name))
    if not parents:
        p, name = split_target(DEFAULT_PARENT)
        if p:
            parents.append(p)
            if name:
                preselect = [os.path.join(p, name)]
    return parents or [DEFAULT_PARENT], preselect


def default_out_dir(parent):
    """Figures land beside the runs, never inside one.

    `parent` is the FIRST parent when several are in play (`#323`): a
    figure drawn from two campaigns has to be filed under one of them,
    and the one the window opened on is the only choice that does not
    move when a folder is added or removed."""
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
#
# `groups` IS REMEMBERED, and it is the one entry here that names
# particular runs -- which is exactly what the paragraph above says is
# never remembered. The distinction is real and worth stating (`#313`):
# the run SELECTION is what a figure is drawn from, so a stale one plots
# the wrong batch silently. A grouping is a LABELLING of runs the
# operator has already told us about, keyed on absolute run directories,
# and it changes nothing unless a run it names is both selected AND the
# aggregate is on. So a stale group is inert rather than wrong, while
# re-typing 'these six are P3' every session is a real cost paid every
# session. Remembered under the FIRST parent, like everything else here
# (`#323` made 'the parent' a list; see options_key).
REMEMBERED = ('mode', 'prepost', 'mean', 'bands', 'breakdown', 'vs_area',
              'logx', 'logy', 'marker_key', 'subplots', 'cadence_guard',
              'aggregate', 'aggregate_exact', 'groups', 'aggregate_only',
              'strain_pct', 'fmt', 'dpi')

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

# ...and the ones that are STRUCTURES (`#313` brought the first). Same
# principle again, and the reason the seam's landing-site map now has a
# note about it: `groups` is a list of (name, run dirs) pairs, so neither
# the enum test nor the number test nor the isinstance(bool) test below
# would have recognised it, and an unvalidated one out of a hand-edited
# config -- two groups with the same name, one run in both -- would have
# reached make_opts and been refused there, which in the window means an
# error message where the figure goes, from a file the operator never
# opened.
STRUCTURED_OPTIONS = {'groups': sp.check_groups}


def options_key(parent):
    """The config key for a parent folder: absolute, and normcase'd
    because Windows paths differ in case without differing.

    With several parents on one figure (`#323`) this is given the FIRST
    of them, deliberately and visibly: the window prints which folder its
    memory is filed under. Merging several parents' entries was the other
    candidate and it has no defensible answer to 'which one wins' -- the
    same two folders opened in the other order would restore different
    options, which is a memory that cannot be reasoned about."""
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
    for k, check in STRUCTURED_OPTIONS.items():
        # the SHAPE is tested here and the CONTENTS by the engine's own
        # checker. A present-but-wrong-shaped entry (a string, a null) is
        # dropped like every other unrecognizable one rather than being
        # read as 'no groups' -- 'repair' is what this function does not
        # do. An empty list IS a valid value and is kept, so a round trip
        # through the file returns exactly what was written to it.
        if isinstance(d.get(k), (list, tuple)):
            value, err = check(d[k])
            if err is None:
                out[k] = value
    for k in REMEMBERED:
        if (k not in ENUM_OPTIONS and k not in NUMERIC_OPTIONS
                and k not in STRUCTURED_OPTIONS
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
    # NOTHING is clickable when the per-run curves are hidden (`#313`):
    # the only marks left are group means, and a mean is not a frame.
    # Returning the rows anyway would resolve a double-click against
    # markers that are not on the figure -- the click-through would open
    # Edge Review on a frame nobody could see, which is worse than the
    # silence `#311` spent a week diagnosing. on_click says so in words.
    if opts.get('aggregate_only') and opts.get('aggregate'):
        return []
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


# Why the box is GREY, said before the budget itself (`#312`). The bands
# checkbox reaches exactly one line of the engine --
# `budget_bands = opts['bands'] and not opts.get('aggregate')` in draw_area,
# which is the only place sldea_plot reads the option at all -- so in two
# states it is a control that cannot change the figure, and this window's
# rule is that such a control greys with a tooltip saying what brings it
# back. The reason leads and the unchanged budget text follows it: an
# operator hovering a greyed box wants the WHY first.
BANDS_OFF_AGGREGATE_TIP = (
    "Greyed: the cross-run aggregate suppresses this band. The ±1–2% "
    "budget is ONE run's instrument error, while the aggregate's band is "
    "the standard error of the mean across runs (`#268`) — two different "
    "quantities, and stacking them would invite reading one for the "
    "other. Turn the aggregate off to draw the budget bands again.\n\n"
    + BANDS_TIP)

BANDS_OFF_MODE_TIP = (
    "Greyed: the bands are an AREA budget and only the area figure draws "
    "them — current and power plot microamps and milliwatts, which this "
    "budget says nothing about. Switch to area mode to draw them "
    "again.\n\n" + BANDS_TIP)


def bands_tip(area, aggregate):
    """The bands tooltip for the state the window is in: the plain budget
    text while the box is live, that text behind a reason while it is
    not."""
    if not area:
        return BANDS_OFF_MODE_TIP
    return BANDS_OFF_AGGREGATE_TIP if aggregate else BANDS_TIP


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
    'aggregate_only': (
        "Draws the aggregate means ALONE — the per-run curves, their "
        "markers and their breakdown X marks are all left off, so a "
        "CB-against-P3 panel is two lines and not fifteen (`#313`). "
        "Nothing is thrown away: every contributing run is still loaded, "
        "still guarded and still written to the tidy CSV in full, with "
        "the group it was in. Needs the aggregate above — on its own "
        "there would be nothing left to draw, so the engine refuses the "
        "pair rather than handing back an empty figure. Note that "
        "double-click-to-open-a-frame goes quiet while the runs are "
        "hidden: the points it resolves are the per-run markers."),
    'strain_pct': (
        "Draws the normalized panel as AREAL STRAIN, (A − A₀)/A₀ × 100 in "
        "percent, instead of the expansion ratio A/A₀. Same measurement, "
        "same baseline, same curve shape — 1.40 becomes 40 % — so it is a "
        "units choice and not a different analysis. Use it when the figure "
        "goes next to numbers quoted as strain. The axis label and the "
        "panel heading both follow, because a reader who sees 40 where "
        "they expected 1.4 needs the panel to say which one it is. Area "
        "mode only: it describes the second panel, and the current and "
        "power modes have none. The tidy CSV keeps its expansion column as "
        "A/A₀ either way, so a saved CSV means the same thing whichever "
        "way the figure was drawn."),
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

# Hover text for the run-folder buttons (`#323`) and the group editor
# (`#313`). Module constants for the reason every other tooltip here is
# one: a test can read them, and the sentence that has to stay true --
# that the memory is keyed on ONE of several folders -- sits somewhere
# findable rather than inline at a widget.
BROWSE_TIP = (
    "ADDS a folder of runs to the list; it does not replace the one "
    "already there (`#323`). That is the whole point: the campaign's two "
    "electrode families live under different Upload folders, so a "
    "carbon-black-against-P3 figure needs runs from more than one parent "
    "and used to be impossible to draw at all. Runs are listed with the "
    "folder they came from, because two runs in different folders can "
    "share a name.")

DROP_FOLDERS_TIP = (
    "Goes back to the folder this window opened on, dropping the ones "
    "added since. The remembered options and the default output folder "
    "are keyed on that FIRST folder and do not move when you add or drop "
    "others — the window names it above the list, so which one is never "
    "a guess.")

GROUP_ASSIGN_TIP = (
    "Type a name, select runs on the left, press Assign: those runs "
    "become that group, and the cross-run aggregate then draws ONE MEAN "
    "PER GROUP instead of one mean over everything (`#313`). Two groups "
    "give the CB-against-P3 comparison the campaign is for.\n\n"
    "The grouping is YOURS — nothing is read from setup.txt. The "
    "'Electrode family:' field exists but no run in the corpus carries "
    "it, so grouping by hand is what works on the runs that exist.\n\n"
    "Each group's band follows the same decided rule as the ungrouped "
    "aggregate, computed from that group's own runs: SEM for two runs or "
    "more, and for a single run NO band plus a caption saying an "
    "aggregate needs at least two. A run belongs to at most one group.")

GROUP_UNGROUP_TIP = (
    "Takes the selected runs out of whatever group they are in, leaving "
    "the other groups alone. A run in no group is still drawn; it just "
    "averages into nothing, and the console says so.")

GROUP_CLEAR_TIP = (
    "Forgets every group. The aggregate goes back to one mean over every "
    "selected run, which is what it drew before groups existed.")


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
# the heading hints (`#315`)
#
# THE PROBLEM: three empty boxes say nothing. An operator cannot tell that
# Title / Panel 1 / Panel 2 are editable, because an empty box looks the
# same as a box that does nothing.
#
# THE ANSWER IS A HINT, NOT A PRE-FILL. Writing the derived heading INTO
# the boxes was the other candidate and it is the wrong one, on three
# pieces of evidence found in the code rather than in taste:
#
#   1. the second panel's default heading names the baseline it divides
#      by -- 'Normalized to baseline area (A₀ = 201.1 mm²)' -- so it moves
#      with the RUN SELECTION, not only with the mode. A pre-fill would
#      have to rewrite a box the operator may be typing in every time a
#      row of the run list is clicked, and every path that forgot to would
#      leave a WRONG heading that looks like a chosen one.
#   2. sldea_plot._panel_title reads blank as 'no override'. A pre-fill
#      turns all three fields into permanent explicit overrides, and the
#      figspec sidecar (`#273`) records `dict(opts)` verbatim -- so every
#      exported figure would carry today's derived wording as if somebody
#      had typed it, and --from-spec would re-render it over other data.
#      That is a worse leak than the remembered-options file, and unlike
#      that file it is not filtered by a key list.
#   3. --title vs --title-first precedence would invert: a pre-filled
#      Panel 1 beats anything typed into Title, so the older box would
#      stop working the moment the newer one was pre-filled.
#
# A hint is a LABEL SITTING OVER AN EMPTY ENTRY, never the entry's value.
# Nothing downstream changes: current_opts still reads the variables, the
# variables are still blank, make_opts still gets None, and the figure
# still derives its own heading. Clearing a box therefore returns to the
# derived heading for free -- there is no state to reset -- and no derived
# string can reach the options file or a figspec, because none of them is
# ever a value.
#
# The hint text is THE HEADING THAT PANEL WILL ACTUALLY CARRY
# (sp.panel_titles, the same call draw_area makes), refreshed on every
# redraw. So a box either holds what the figure says, or shows what the
# figure says.
# ---------------------------------------------------------------------------

HINT_FG = '#8a8a8a'                    # grey: a hint, not a value


def _field_bg(widget):
    """The Entry field colour this theme paints, so a hint laid over one
    is invisible against it. Best effort: an unknown theme gets the
    platform's window colour and, failing that, white -- a hint in the
    wrong shade is cosmetic, and it must not stop the window opening."""
    for cand in (ttk.Style().lookup('TEntry', 'fieldbackground'),
                 'SystemWindow', 'white'):
        if not cand:
            continue
        try:
            widget.winfo_rgb(cand)
        except tk.TclError:
            continue
        return cand
    return 'white'


class TitleRow:
    """One heading box and the hint that sits over it while it is empty.

    The hint is a separate widget on purpose (see the block above): it
    cannot be read back as the field's value, by this module or by any
    later one, because it is not in the variable.
    """

    def __init__(self, key, panel, var, entry, hint, tip, base_tip=''):
        self.key = key            # the opts name this box fills
        self.panel = panel        # which panel it heads: 'first'/'second'
        self.var = var
        self.entry = entry
        self.hint = hint
        self.tip = tip            # the hint's own Tooltip
        self.base_tip = base_tip  # the row's tooltip, which the hint covers

    def typed(self):
        """-> what the operator put in this box (stripped), or ''."""
        return self.var.get().strip()

    def show(self, text):
        """Show `text` as this box's hint, or hide the hint if empty.

        The label's text is cleared when it is hidden, so `hint['text']`
        is the whole truth about what the box is showing -- a caller
        never has to also ask whether it is mapped.

        The hint's tooltip is rewritten with it, for two reasons. It sits
        ON the entry, so it would otherwise SWALLOW the row's own hover
        text; and the column is narrow, so a long heading -- the second
        panel's names its baseline area -- is clipped by the box it is
        shown in, and the hover is where it can be read whole."""
        if text:
            self.hint.config(text=text)
            self.hint.place(in_=self.entry, x=3, y=0,
                            relwidth=1.0, width=-6, relheight=1.0)
            reads = f"Blank keeps this panel's heading: \"{text}\""
            self.tip.text = (f"{self.base_tip}\n\n{reads}"
                             if self.base_tip else reads)
        else:
            self.hint.config(text='')
            self.hint.place_forget()
            self.tip.text = self.base_tip


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
        # `#323`: SEVERAL parent folders, in the order they arrived, and
        # `self.parent` is the first of them -- the one the options file
        # and the default output folder are keyed on. A single string is
        # still accepted here because every caller but launch() passes
        # one, and a window that took a list only would break them all
        # for no gain.
        self.parents = ([parent_dir] if isinstance(parent_dir, str)
                        else [p for p in (parent_dir or []) if p]
                        or [DEFAULT_PARENT])
        self.runs = []                 # [(rundir, label)] currently listed
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
        self._title_rows = []          # the heading boxes (`#315`)
        self._title_focused = None     # the one with the caret, if any
        root.title("SLDEA plot — cross-run figures")

        # PRECEDENCE (`#275`): explicit CLI/init args > remembered >
        # defaults. `remember=False` opts a caller out of the file
        # entirely (the tests, and anything that must be reproducible).
        self.remember = remember
        o = sp.make_opts()[0]
        mem = load_options(self.parent) if remember else {}
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
        self.v_aggregate_only = tk.BooleanVar(value=o['aggregate_only'])
        self.v_strain_pct = tk.BooleanVar(value=o['strain_pct'])
        # `#313`. NOT a Tk variable: the grouping is a mapping from run
        # directory to group name, which no Tk variable type can hold, so
        # it lives here and current_opts renders it into opts' canonical
        # form. `_group_order` keeps the operator's group order, because
        # that order picks the colours (sp.group_style) and a set would
        # repaint the figure on every reload.
        self.groups = {}               # run key -> group name
        self._group_order = []         # group names, creation order
        self._set_groups(o['groups'])
        self.v_group_name = tk.StringVar(value='')
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
            value=chosen_out or default_out_dir(self.parent))
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

    # -- parents and groups ------------------------------------------------

    @property
    def parent(self):
        """The FIRST parent folder, which is the one two things are keyed
        on and nothing else is (`#323`): the remembered-options entry and
        the default output folder. Read-only on purpose -- `#323` made
        the answer to "the parent" a list, and code that assigns a new
        one is code that has not noticed."""
        return self.parents[0]

    def _set_groups(self, groups):
        """Replace the whole grouping from opts' canonical form."""
        self.groups = {}
        self._group_order = []
        for name, members in (groups or ()):
            if name not in self._group_order:
                self._group_order.append(name)
            for path in members:
                self.groups[path] = name

    def group_list(self):
        """-> the grouping in sp.check_groups' canonical form, in the
        operator's group order.

        Built from the mapping every time rather than kept alongside it,
        so the two cannot disagree -- the bug this window has had twice
        in other guises (a widget saying one thing while the figure drew
        another)."""
        out = []
        for name in self._group_order:
            members = [k for k, n in self.groups.items() if n == name]
            if members:
                out.append([name, members])
        return out

    def assign_group(self, name, rundirs):
        """Put `rundirs` in the group `name`, taking them out of whatever
        group they were in. Empty `name` UNGROUPS them, which is the one
        control this box needs beyond assignment.

        -> an error message, or None. The engine's own checker has the
        last word (sp.check_groups), so the window cannot create a
        grouping the CLI would refuse."""
        name = (name or '').strip()
        # STORED AS SPELLED, matched case-insensitively -- the engine's
        # own rule (sp.group_key's docstring): a normcased store puts a
        # lowercased run path into the figspec and into every warning,
        # against a folder of the real name.
        paths = [os.path.abspath(d) for d in rundirs]
        if not paths:
            return 'Pick the runs to group on the left first.'
        drop = {sp.group_key(p) for p in paths}
        self.groups = {k: v for k, v in self.groups.items()
                       if sp.group_key(k) not in drop}
        if name:
            for path in paths:
                self.groups[path] = name
            if name not in self._group_order:
                self._group_order.append(name)
        # drop names nothing is in any more, so the order list cannot
        # grow forever and a re-used name keeps its original colour slot
        self._group_order = [n for n in self._group_order
                             if n in set(self.groups.values())]
        _clean, err = sp.check_groups(self.group_list())
        if err:
            return err
        return None

    def group_summary(self):
        """One line naming the groups and their sizes, for the label under
        the group box -- the window's own read-out of what it will draw."""
        rows = self.group_list()
        if not rows:
            return ('No groups. The aggregate averages every selected run '
                    'into one mean.')
        bits = [f"{name} ({len(members)})" for name, members in rows]
        line = 'Groups: ' + ', '.join(bits) + '.'
        if not self.v_aggregate.get():
            line += (' Turn on the cross-run aggregate to draw a mean per '
                     'group.')
        elif self.v_mode.get() != 'area':
            line += ' Area mode only — nothing is drawn from them here.'
        return line

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
        # ADDS a folder, never replaces the list (`#323`). The old
        # behaviour -- browse somewhere and the previous folder's runs
        # vanish -- is exactly what made a CB-vs-P3 figure impossible,
        # since the two families live under different Upload folders.
        b_browse = ttk.Button(brow, text="Add folder…", command=self._browse)
        b_browse.pack(side=tk.LEFT)
        add_tooltip(b_browse, BROWSE_TIP)
        ttk.Button(brow, text="Select all", command=self._select_all).pack(
            side=tk.LEFT, padx=6)
        self.btn_drop = ttk.Button(brow, text="Reset folders",
                                   command=self._drop_extra_parents)
        self.btn_drop.pack(side=tk.LEFT)
        add_tooltip(self.btn_drop, DROP_FOLDERS_TIP)
        ttk.Label(rf, foreground='#666', wraplength=260, justify=tk.LEFT,
                  text="✓ processed = Edge Review saved areas for that "
                       "run.").pack(fill=tk.X, pady=(4, 0))

        # --- groups (`#313`). Under the run list rather than in Draw,
        # because what it edits is the RUNS -- who belongs with whom --
        # and not how the figure is drawn. Left live in every mode for
        # the same reason the run list is: it edits data the operator is
        # entering, and greying it would mean 'assign your groups only
        # after you have switched to area mode and ticked aggregate'.
        # What the figure does with them is the aggregate's business, and
        # the label below says so whenever nothing is being drawn.
        gf = ttk.LabelFrame(left, text="Groups (aggregate each separately)",
                            padding=6)
        gf.pack(fill=tk.X, pady=(8, 0))
        grow = ttk.Frame(gf)
        grow.pack(fill=tk.X)
        ttk.Label(grow, text="Name:").pack(side=tk.LEFT)
        self.e_group = ttk.Entry(grow, textvariable=self.v_group_name,
                                 width=10)
        self.e_group.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        self.e_group.bind('<Return>', lambda _e: self._assign_group())
        self.btn_assign = ttk.Button(grow, text="Assign",
                                     command=self._assign_group)
        self.btn_assign.pack(side=tk.LEFT)
        for w in (self.e_group, self.btn_assign):
            add_tooltip(w, GROUP_ASSIGN_TIP)
        g2 = ttk.Frame(gf)
        g2.pack(fill=tk.X, pady=(4, 0))
        self.btn_ungroup = ttk.Button(g2, text="Ungroup selected",
                                      command=self._ungroup_selected)
        self.btn_ungroup.pack(side=tk.LEFT)
        add_tooltip(self.btn_ungroup, GROUP_UNGROUP_TIP)
        self.btn_clear_groups = ttk.Button(g2, text="Clear all",
                                           command=self._clear_groups)
        self.btn_clear_groups.pack(side=tk.LEFT, padx=6)
        add_tooltip(self.btn_clear_groups, GROUP_CLEAR_TIP)
        self.lbl_groups = ttk.Label(gf, foreground='#666', wraplength=260,
                                    justify=tk.LEFT)
        self.lbl_groups.pack(fill=tk.X, pady=(4, 0))

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
        # the other child of the aggregate (`#313`), and the one the
        # operator actually asked for: two lines, not fifteen. Same
        # indentation and the same greying rule -- make_opts REFUSES it
        # without the aggregate, because on its own it would empty the
        # figure rather than tidy it.
        self.cb_aggregate_only = ttk.Checkbutton(
            df, text="…and hide the contributing runs",
            variable=self.v_aggregate_only, command=self._toggled)
        self.cb_aggregate_only.pack(anchor=tk.W, padx=(18, 0))
        add_tooltip(self.cb_aggregate_only, DRAW_TIPS['aggregate_only'])
        # The normalized panel's UNITS: A/A₀, or areal strain in percent.
        # NOT indented under the aggregate -- it applies to the per-run
        # curves just as much, and indentation here reads as "belongs to
        # the box above". Area mode only, greyed elsewhere by the same
        # rule as the marker key below.
        self.cb_strain_pct = ttk.Checkbutton(
            df, text="Normalized panel as strain %  ((A−A₀)/A₀)",
            variable=self.v_strain_pct, command=self._toggled)
        self.cb_strain_pct.pack(anchor=tk.W)
        add_tooltip(self.cb_strain_pct, DRAW_TIPS['strain_pct'])
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
        # Each row carries the panel it heads, which is what its hint
        # reports (`#315`): Title and Panel 1 both head the first panel,
        # so both hint at the first panel's heading.
        self.e_title = self._title_row(df, "Title:", self.v_title,
                                       'title', 'first')
        self.e_title_first = self._title_row(
            df, "Panel 1:", self.v_title_first, 'title_first', 'first',
            DRAW_TIPS['title_first'])
        self.e_title_second = self._title_row(
            df, "Panel 2:", self.v_title_second, 'title_second', 'second',
            DRAW_TIPS['title_second'])

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
        # from the format radios in the Export frame, `#315`'s hints follow
        # the greying), so the first sync can only run once every widget it
        # touches exists.
        self._sync_enabled()

    def _title_row(self, master, label, var, key, panel, tip=None):
        """One 'Label: [entry]' heading row in the Draw column, with the
        `#315` hint laid over the entry. -> the Entry.

        There are three of them now (the legacy --title and the two
        per-panel headings, `#269`), so the row pattern is written once
        and the label width is fixed in characters -- the three entries
        line up at whatever the theme's font is, which a hand-repeated
        row does not.

        The hint is placed IN the entry rather than beside it because it
        has to read as the box's own content: a grey line under the row
        would be one more label in a column full of them. It hides while
        the box has focus, so what an operator sees the moment they click
        is an empty field and a caret -- the point of the exercise is
        'you may type here', and a caret behind grey text says it less
        clearly than a caret in an empty box."""
        row = ttk.Frame(master)
        row.pack(fill=tk.X, pady=(4, 0))
        lbl = ttk.Label(row, text=label, width=8)
        lbl.pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        entry.bind('<KeyRelease>', lambda _e: self._title_typed())
        # PARENTED TO THE ENTRY, not to the row, even though it is placed
        # over the entry either way. A Label whose parent is the row but
        # which is placed `in_` a sibling gets destroyed TWICE on teardown
        # -- once when Tk tears down the entry it is placed in, then again
        # when the row walks its own children -- and the second
        # deletecommand raises TclError. Tk.destroy() clears
        # tkinter._default_root only on the way OUT, so the raise left a
        # live root behind and the next test asserting a clean interpreter
        # failed instead of this one. Parenting it here means it is
        # destroyed exactly once.
        hint = tk.Label(entry, text='', anchor=tk.W, foreground=HINT_FG,
                        background=_field_bg(entry), borderwidth=0,
                        font='TkTextFont')
        # a click has to land in the box the hint covers, not on the hint
        hint.bind('<Button-1>', lambda _e: entry.focus_set())
        trow = TitleRow(key, panel, var, entry, hint,
                        add_tooltip(hint, tip or ''), tip or '')
        # tracked rather than asked of Tk (focus_get answers for the whole
        # application, and returns None at all when the window is not the
        # one the desktop focused)
        entry.bind('<FocusIn>', lambda _e: self._title_focus(trow))
        entry.bind('<FocusOut>', lambda _e: self._title_focus(None, trow))
        self._title_rows.append(trow)
        if tip:
            add_tooltip(lbl, tip)
            add_tooltip(entry, tip)
        return entry

    # -- the heading hints (`#315`) ----------------------------------------

    def _title_focus(self, row, leaving=None):
        """Remember which heading box has the caret, and re-hint."""
        if leaving is not None and self._title_focused is not leaving:
            return                     # a stale FocusOut; someone else has it
        self._title_focused = row
        self._refresh_hints()

    def _title_typed(self):
        """A heading box changed. Re-hint IMMEDIATELY (the box just became
        filled, or just became empty again) and redraw on the debounce
        like every other control."""
        self._refresh_hints()
        self.schedule()

    def _refresh_hints(self):
        """Show, over every EMPTY heading box, the heading that panel will
        actually carry -- and nothing over a box that has text, has the
        caret, or heads a panel this figure does not draw.

        Asked of sldea_plot.panel_titles with the runs currently prepared,
        which is the same call draw_area makes, so the hint cannot say one
        thing while the figure says another. Called from redraw(), so it
        follows the mode, the panel choice AND the run selection -- the
        second panel's default heading names the baseline area, which
        moves with the runs.

        An options combination the engine REFUSES draws an error message
        instead of a figure, so it has no headings to report and every
        hint goes: a hint is a courtesy, and one left over from the last
        drawable combination would be a claim about a figure that does
        not exist."""
        opts, err = self.current_opts()
        heads = {} if err else sp.panel_titles(opts, self._prepared)
        for row in self._title_rows:
            live = str(row.entry.cget('state')) == 'normal'
            row.show('' if (row.typed() or row is self._title_focused
                            or not live)
                     else (heads.get(row.panel) or ''))

    def title_hints(self):
        """-> {opts name: the hint that box is showing, '' for none}.

        The window's own read-out of what it is telling the operator."""
        return {r.key: r.hint.cget('text') for r in self._title_rows}

    # -- run list ----------------------------------------------------------

    def populate(self, preselect=(), keep=True):
        """List every parent's runs, preselecting the given DIRECTORIES.

        Directories, not names (`#323`): two runs in different parents
        can share a name, so a name is no longer an identity here. `keep`
        carries the current selection across a re-listing, which is what
        makes 'Add folder…' additive in the way that matters -- adding a
        second campaign must not deselect the first one's runs.

        A BARE NAME is still accepted, and matches that name under every
        listed parent. Not laziness: this is the window's front door, the
        argument arrives from a command line or another module, and the
        forgiving reading of 'P3_1' when only one folder holds a P3_1 is
        the one every other SLDEA entry point gives it. An entry with a
        directory in it is matched as a path and only as a path, so the
        ambiguous case is never resolved by guessing."""
        names = {p for p in preselect if not os.path.dirname(p)}
        wanted = {sp.group_key(d) for d in preselect
                  if d not in names}
        if keep:
            wanted |= {sp.group_key(d) for d in self.selected_dirs()}
        self.runs = []
        multi = len(self.parents) > 1
        for i, parent in enumerate(self.parents, 1):
            for name, label in list_runs(parent):
                # WHERE IT CAME FROM, once there is more than one answer,
                # as a NUMBER keyed to the folder list above (`#323`).
                # Two runs in different parents can share a name, so the
                # list has to say which is which -- but the column is
                # ~250 px and the folder's own basename does not fit:
                # measured on the corpus, 'P3_6_2.5mL_20260729 ✓
                # processed ⟨SLDEA_data (1)⟩' clipped to '⟨SLDEA_da',
                # which distinguishes nothing. A leading tag is short,
                # never clipped, and sits directly under the numbered
                # list of folders it refers to.
                self.runs.append(
                    (os.path.join(parent, name),
                     (f"[{i}] " if multi else '') + label))
        self.run_box.delete(0, tk.END)
        for _dir, label in self.runs:
            self.run_box.insert(tk.END, label)
        self.lbl_parent.config(text=self._parent_label())
        self.btn_drop.config(state='normal' if len(self.parents) > 1
                             else 'disabled')
        for i, (rundir, _l) in enumerate(self.runs):
            if (sp.group_key(rundir) in wanted
                    or os.path.basename(rundir) in names):
                self.run_box.selection_set(i)
        if not self.runs:
            self._set_messages(
                [f"no runs (directories holding data.csv) in "
                 f"{'; '.join(self.parents)} — use Add folder… to point at "
                 f"a folder of runs"])
        self._mode_changed()

    def _parent_label(self):
        """What the label above the run list says: the folders in play,
        and -- once there is more than one -- which of them the memory
        and the default output folder are keyed on (`#323`).

        SAID rather than left to be discovered. The issue's own answer to
        'which key wins' was 'remember against the FIRST parent and say
        so'; this is the saying so."""
        if len(self.parents) == 1:
            return self.parents[0]
        rows = '\n'.join(f"[{i}] {p}"
                         for i, p in enumerate(self.parents, 1))
        return (f"{rows}\n(options and the default output folder are "
                f"remembered against [1])")

    def _browse(self):
        """Add a folder of runs to the list (`#323`)."""
        d = filedialog.askdirectory(initialdir=self.parent or DEFAULT_PARENT)
        if not d:
            return
        parent, name = split_target(d)
        parent = parent or d
        if parent not in self.parents:
            self.parents.append(parent)
        # the output folder follows the FIRST parent until the user picks
        # one of their own, and adding a second folder does not move it:
        # a figure combining two campaigns has to be filed somewhere, and
        # somewhere that jumps as folders are added is worse than a
        # somewhere that is merely arbitrary
        if not self._out_chosen:
            self.v_out.set(default_out_dir(self.parent))
        self.populate([os.path.join(parent, name)] if name else [])
        self.schedule()

    def _drop_extra_parents(self):
        """Back to the folder the window opened on (`#323`)."""
        if len(self.parents) < 2:
            return
        del self.parents[1:]
        self.populate()
        self.schedule()

    def _select_all(self):
        self.run_box.selection_set(0, tk.END)
        self.schedule()

    def selected_dirs(self):
        """The run directories currently selected. Held as full paths in
        `self.runs` since `#323` -- joining a name onto 'the' parent is
        what dropped every run that did not live under it."""
        return [self.runs[i][0] for i in self.run_box.curselection()]

    # -- groups (`#313`) ---------------------------------------------------

    def _assign_group(self):
        err = self.assign_group(self.v_group_name.get(),
                                self.selected_dirs())
        if err:
            messagebox.showwarning("Groups", err)
            return
        self._groups_changed()

    def _ungroup_selected(self):
        err = self.assign_group('', self.selected_dirs())
        if err:
            messagebox.showwarning("Groups", err)
            return
        self._groups_changed()

    def _clear_groups(self):
        self.groups = {}
        self._group_order = []
        self._groups_changed()

    def _groups_changed(self):
        """The grouping moved: re-read it out, then redraw like any other
        control. _sync_enabled too, because the aggregate's own greying
        does not change but the group label under the box reports on it."""
        self.lbl_groups.config(text=self.group_summary())
        self.schedule()

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
        # the budget bands reach ONE line of the engine, draw_area's
        # `budget_bands = opts['bands'] and not opts.get('aggregate')`, and
        # nothing outside draw_area reads the option -- so the box is inert
        # both under the aggregate, which deliberately suppresses the
        # ±1–2% budget in favour of the SEM, and in current/power, which
        # never had an area budget to draw (`#312`). The tooltip says which
        # of the two it is; the box greys rather than vanishing, as
        # everything else in this column does.
        agg = self.v_aggregate.get()
        live(self.cb_bands, area and not agg)
        self.tip_bands.text = bands_tip(area, agg)
        # _marker_key is called by draw_area alone -- and inside it, only
        # when the per-run curves are actually drawn: the key explains
        # THEIR open/closed markers, and with the runs hidden (`#313`)
        # there are none on the figure to explain, exactly as there are
        # none in current/power mode
        hidden = agg and self.v_aggregate_only.get()
        live(self.cb_marker_key, area and not hidden)
        # the normalized panel's units. Area mode has the only second
        # panel, and with subplots='first' there is no normalized panel on
        # the figure at all -- the box is inert in both cases and says so
        # by greying, like everything else in this column.
        live(self.cb_strain_pct,
             area and self.v_subplots.get() != 'first')
        # the aggregate pools PER-LEVEL curves, which only area mode has;
        # make_opts refuses the other pairing outright
        live(self.cb_aggregate, area)
        # nothing outside `if opts['aggregate']` reads the grid toggle
        live(self.cb_aggregate_exact, area and self.v_aggregate.get())
        # ...and make_opts REFUSES --aggregate-only without --aggregate,
        # so this one is not merely inert without it, it is an error
        # message where the figure goes. Greyed for the same reason as
        # every other child here, and the group summary below reports the
        # same state in words.
        live(self.cb_aggregate_only, area and self.v_aggregate.get())
        self.lbl_groups.config(text=self.group_summary())
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

        # LAST in this method: a greyed box heads a panel that is not
        # drawn, so its hint would promise a heading nothing carries -- and
        # the greying just above may have brought one back (`#315`).
        self._refresh_hints()

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
            # `#313`. Neutralised against the SAME condition the box is
            # greyed by, and for the reason vs_area and subplots are:
            # make_opts refuses --aggregate-only without --aggregate, and
            # unticking the aggregate must produce a figure rather than
            # an error message where the figure goes.
            aggregate_only=(self.v_aggregate_only.get()
                            and self.v_aggregate.get() and area),
            # the operator's grouping, in the engine's canonical form.
            # Passed in every mode: it draws nothing outside the
            # aggregate, and dropping it here would mean a figspec
            # exported from current mode forgot a grouping the window is
            # still showing.
            groups=self.group_list(),
            # 'second' outside area mode is the one combination make_opts
            # refuses. Neutralised to the default exactly as vs_area is
            # above: an error message where the figure goes is not what a
            # mode switch should produce.
            subplots='both' if which == 'second' and not area else which,
            # The normalized panel's UNITS. Area mode only -- it describes
            # the second panel, which no other mode has -- and neutralised
            # rather than refused, for the reason vs_area and subplots are:
            # a mode switch must produce a figure, not an error message.
            strain_pct=self.v_strain_pct.get() and area,
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
        """Draw, then re-hint the heading boxes -- ALWAYS, including the
        paths that return early (`#315`).

        In a `finally` because the hints have to follow the figure even
        when there is no figure: a redraw that stopped at 'pick some runs'
        or at an error message still changed what the headings would say,
        and a hint left over from the last good draw is exactly the stale
        text this feature exists not to show."""
        try:
            self._redraw()
        finally:
            self._refresh_hints()

    def _redraw(self):
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

    def _panel_for(self, event):
        """-> (axes, panel index) for the click, RESOLVED AGAINST THE FIGURE
        AS IT IS NOW, or (None, None) if the pointer is over no panel.

        `event.inaxes` is whatever matplotlib decided when it built the
        event. Trusting it and taking `list(self.fig.axes).index(...)` is
        what `#311` swallowed clicks on: if the figure is cleared and
        redrawn between the event being made and this running, that Axes
        object is not in the figure any more, the lookup raises ValueError
        and the click is dropped. Re-asking the CURRENT figure which panel
        holds those pixels answers the same question and cannot go stale --
        and the Axes it returns is the one whose transData nearest_point
        must measure with, which a stale one would get wrong too.
        """
        axes = list(self.fig.axes)
        if event.inaxes in axes:
            return event.inaxes, axes.index(event.inaxes)
        for i, ax in enumerate(axes):
            try:
                # the same test matplotlib's own canvas.inaxes applies
                if ax.get_visible() and ax.patch.contains_point(
                        (event.x, event.y)):
                    return ax, i
            except (ValueError, TypeError):
                continue
        return None, None

    def on_click(self, event):
        """matplotlib button_press_event -> the frame under the pointer.

        Returns what it resolved (run, row) so the live smoke and the
        tests can see the whole chain without watching for a process.

        EVERY path out of here either acts or says why, in `self.lbl_click`
        (`#311`). It used to have four silent returns, and an operator who
        double-clicked and got nothing -- no window, no message, no console
        line -- had no way to tell a mis-aimed click from a broken feature
        from a double-click that arrived as two singles. That silence is
        what made the report impossible to characterise, so it is treated
        here as part of the bug and not as tidiness.
        """
        dbl = bool(getattr(event, 'dblclick', False))
        opts, err = self.current_opts()
        if err:
            self.lbl_click.config(
                text=f"cannot open a frame while the draw options are "
                     f"unusable: {err}")
            return None
        if opts.get('aggregate_only') and opts.get('aggregate'):
            # BEFORE the where-did-you-click questions, and deliberately:
            # with the per-run curves hidden (`#313`) no click anywhere on
            # the figure can resolve to a frame, so "aim inside the
            # figure, at a marker" and "no data point within 30 px" are
            # both true and both send an operator hunting for markers
            # that are not there. `#311`'s rule is that every path either
            # acts or says why; this is the why, and it outranks where.
            self.lbl_click.config(
                text="the contributing runs are hidden, so there are no "
                     "snapshots on the figure to open — untick “…and hide "
                     "the contributing runs” to click through again")
            return None
        ax, panel = self._panel_for(event)
        if ax is None:
            self.lbl_click.config(
                text="that double-click was not over a panel — aim inside "
                     "the figure, at a marker" if dbl else CLICK_HINT)
            return None
        if not self._prepared:
            self.lbl_click.config(
                text="nothing is plotted to click through to — pick runs "
                     "that work in this mode (the messages below say which "
                     "were skipped, and why)")
            return None
        hit = nearest_point(ax, plot_points(self._prepared, opts, panel),
                            event.x, event.y)
        if hit is None:
            self.lbl_click.config(
                text=f"no data point within {PICK_PX} px of that "
                     f"{'double-click' if dbl else 'click'} — aim at a "
                     f"marker")
            return None
        run, row, _dist = hit
        if not dbl:
            # THE `#311` SYMPTOM MADE VISIBLE. A double-click can reach the
            # window as two separate single clicks -- the pair is split when
            # the desktop is busy handing focus back from the Edge Review
            # window that was just closed, and Tk then matches <Button-1>
            # twice instead of <Double-Button-1> once. That used to be
            # perfectly silent, which is exactly the reported "double-click
            # does nothing, sometimes the second one works". Now the click
            # lands ON a marker and SAYS so, and says what it wants.
            snap = str(row.get('snapshot') or '?')
            self.lbl_click.config(
                text=f"single click on {run['name']}, snapshot {snap} — "
                     f"DOUBLE-click it to open that frame in Edge Review")
            return None
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
    parents, preselect = initial_state(args)
    root = tk.Tk()
    PlotWindow(root, parents, preselect, opts=opts, out_dir=out_dir,
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
