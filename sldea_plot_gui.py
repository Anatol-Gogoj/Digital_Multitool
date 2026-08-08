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
    both files it wrote in the window. A preview that quietly littered the
    run folder with PNGs would be worse than the CLI, not better.
  * Export always writes the tidy per-snapshot CSV beside the PNG. That
    CSV is the figure's evidence -- it is what makes a figure traceable
    back to its numbers -- so there is no "just the picture" option here
    (sldea_plot.export enforces it for both front ends).
"""
import math
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import sldea_edge as se
import sldea_plot as sp
import tk_fontfix                      # must run before tkinter connects:
tk_fontfix.apply()                     # colour-emoji glyphs hard-crash Tk

# ASCII only: this is the one thing the module prints to a console, and a
# Windows cp1252 console cannot carry the docstring's prose.
USAGE = """\
Usage:
    python sldea_plot_gui.py [RUN_OR_PARENT]   # a run, a folder of runs,
                                               # or a bench shortcut (1/2/3)
    python sldea_plot.py --gui [RUN ...]       # the same window, via the CLI

Pick several runs, choose area / current / power, tick what to draw.
Export writes the 300 dpi PNG and its tidy per-snapshot CSV together.
For headless and batch use, see sldea_plot.py --help."""

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

# Redraw coalescing. 120 ms was already the run-list debounce; a resize
# drag fires <Configure> per pixel and each redraw is a full matplotlib
# pass, so it is the same number for the same reason.
REDRAW_MS = 120


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
                 out_dir=None, stem=None):
        self.root = root
        self.parent = parent_dir
        self.runs = []                 # [(name, label)] currently listed
        self._loaded = {}              # rundir -> loaded run dict (cache)
        self._prepared = []            # what the canvas is currently showing
        self._redraw_after = None
        self._canvas_size = None       # last figure-canvas size (`#271`)
        self.min_size = (MIN_FIG_W, MIN_H)   # replaced by apply_minsize
        self._warns = []
        root.title("SLDEA plot — cross-run figures")

        o = opts or sp.make_opts()[0]
        self.v_mode = tk.StringVar(value=o['mode'])
        self.v_prepost = tk.BooleanVar(value=o['prepost'])
        self.v_mean = tk.BooleanVar(value=o['mean'])
        self.v_bands = tk.BooleanVar(value=o['bands'])
        self.v_breakdown = tk.BooleanVar(value=o['breakdown'])
        self.v_vs_area = tk.BooleanVar(value=o['vs_area'])
        self.v_title = tk.StringVar(value=o['title'] or '')
        self.v_out = tk.StringVar(value=out_dir or default_out_dir(parent_dir))
        self.v_stem = tk.StringVar(value=stem or '')
        self._out_chosen = bool(out_dir)   # did someone pick it themselves?

        self._build(root)
        self.populate(preselect)
        # AFTER populate: the floor is measured off the finished column,
        # and the run list and the parent-path label are part of it.
        self.apply_minsize()

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
                        command=self._prepost_changed).pack(anchor=tk.W)
        # "…and the mean line" is a CHILD option: without separated
        # pre/post lines the single drawn line already IS the level mean
        # (draw_area: `if opts['mean'] or not opts['prepost']`), so the
        # toggle only means something on top of them — indented and
        # disabled to say so (operator review 2026-08-07).
        self.cb_mean = ttk.Checkbutton(df, text="…and the mean line on top",
                                       variable=self.v_mean,
                                       command=self.schedule)
        self.cb_mean.pack(anchor=tk.W, padx=(18, 0))
        self._sync_mean_enabled()
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
        ttk.Checkbutton(df, text="breakdown marks (recomputed)",
                        variable=self.v_breakdown,
                        command=self.schedule).pack(anchor=tk.W)
        self.cb_vs_area = ttk.Checkbutton(
            df, text="x axis = active area (needs reviewed runs)",
            variable=self.v_vs_area, command=self.schedule)
        self.cb_vs_area.pack(anchor=tk.W)
        trow = ttk.Frame(df)
        trow.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(trow, text="Title:").pack(side=tk.LEFT)
        e_title = ttk.Entry(trow, textvariable=self.v_title)
        e_title.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        e_title.bind('<KeyRelease>', lambda _e: self.schedule())

        # --- export
        xf = ttk.LabelFrame(left, text="Export (PNG + tidy CSV)", padding=6)
        xf.pack(fill=tk.X, pady=(8, 0))
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

    def _sync_mean_enabled(self):
        """The mean checkbox is live exactly when pre/post lines are drawn
        separately — see the comment where it is built."""
        self.cb_mean.config(state='normal' if self.v_prepost.get()
                            else 'disabled')

    def _prepost_changed(self):
        self._sync_mean_enabled()
        self.schedule()

    def _mode_changed(self):
        mode = self.v_mode.get()
        self.lbl_mode.config(text=MODE_HINT.get(mode, ''))
        # --vs-area is meaningless in area mode (the x axis IS area there);
        # the CLI refuses the combination, so the window does not offer it
        self.cb_vs_area.config(
            state='disabled' if mode == 'area' else 'normal')
        self.schedule()

    def current_opts(self):
        """-> (opts, error). Same builder the CLI uses, so the window
        cannot invent an options combination the CLI would refuse."""
        return sp.make_opts(
            mode=self.v_mode.get(),
            vs_area=self.v_vs_area.get() and self.v_mode.get() != 'area',
            prepost=self.v_prepost.get(), mean=self.v_mean.get(),
            bands=self.v_bands.get(), breakdown=self.v_breakdown.get(),
            title=self.v_title.get().strip() or None)

    # -- drawing -----------------------------------------------------------

    def schedule(self, _event=None):
        """Coalesce redraws: dragging through the run list fires a select
        event per row, and each redraw is a full matplotlib pass."""
        if self._redraw_after is not None:
            self.root.after_cancel(self._redraw_after)
        self._redraw_after = self.root.after(REDRAW_MS, self.redraw)

    def _canvas_configured(self, event):
        """The figure canvas changed size — relayout, coalesced (`#271`).

        SIZE, not every <Configure>: the event also fires when the widget
        merely MOVES (the scrollbar appearing beside it shifts it by its
        own width), and a full prepare_runs + draw for a move is work
        nobody asked for."""
        size = (event.width, event.height)
        if size == self._canvas_size:
            return
        self._canvas_size = size
        self.schedule()

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

    def redraw(self):
        self._redraw_after = None
        # the click line goes back to being a hint: what it says otherwise
        # is which frame the LAST double-click opened, and that answer
        # belongs to the figure that was on screen when it was clicked
        self.lbl_click.config(text=CLICK_HINT)
        opts, err = self.current_opts()
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
        """Name both files BEFORE the click. The CLI prints what it wrote;
        a window that only said 'Saved' would be a step backwards."""
        opts, err = self.current_opts()
        mode = self.v_mode.get() if err else opts['mode']
        png, csvp = sp.output_paths(self.v_out.get(), self.v_stem.get(), mode)
        self.lbl_targets.config(
            text=f"→ {os.path.basename(png)}\n→ {os.path.basename(csvp)}")
        return png, csvp

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
            png, csvp = sp.export(self._prepared, opts, out_dir,
                                  self.v_stem.get(), warns.append)
        except OSError as e:
            messagebox.showerror("Plot", f"Could not write the figure:\n{e}")
            return
        self._set_messages(warns)
        messagebox.showinfo(
            "Exported",
            f"Figure (300 dpi) and its tidy per-snapshot CSV:\n\n"
            f"{png}\n{csvp}\n\nThe CSV is the figure's evidence — keep the "
            f"pair together.")


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------

def launch(args=(), opts=None, out_dir=None, stem=None):
    """Open the window. Returns an exit code (0)."""
    parent, preselect = initial_state(args)
    root = tk.Tk()
    PlotWindow(root, parent, preselect, opts=opts, out_dir=out_dir,
               stem=stem)
    root.mainloop()
    return 0


def main(argv):
    if argv and argv[0] in ('-h', '--help'):
        print(USAGE)
        return 0
    return launch(argv)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
