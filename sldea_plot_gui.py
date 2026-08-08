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
import os
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

    # -- construction ------------------------------------------------------

    def _build(self, root):
        from matplotlib.backends.backend_tkagg import (FigureCanvasTkAgg,
                                                       NavigationToolbar2Tk)
        from matplotlib.figure import Figure

        left = ttk.Frame(root, padding=8)
        left.pack(side=tk.LEFT, fill=tk.Y)
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
        for var, text in ((self.v_bands, "uncertainty bands (±2% / ±1%)"),
                          (self.v_breakdown, "breakdown marks (recomputed)")):
            ttk.Checkbutton(df, text=text, variable=var,
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

        # --- canvas
        self.fig = Figure(figsize=sp.FIGSIZE['area'], dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        widget = self.canvas.get_tk_widget()
        widget.pack(fill=tk.BOTH, expand=True)
        # the captions and legends are laid out by tight_layout against the
        # size at draw time, so a resized window needs one more pass (the
        # 120 ms coalescing keeps a drag from redrawing per pixel)
        widget.bind('<Configure>', lambda _e: self.schedule())
        toolbar = NavigationToolbar2Tk(self.canvas, right)
        toolbar.update()
        toolbar.pack(fill=tk.X)

        # --- messages: the CLI's warnings, which are the tool's whole
        # safety story (scale eras, stale brands, mixed conventions). A
        # window that swallowed them would be strictly less safe than the
        # command line it replaces.
        self.msg = tk.Text(right, height=6, wrap='word', state='disabled')
        self.msg.pack(fill=tk.X)

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
        self._redraw_after = self.root.after(120, self.redraw)

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
