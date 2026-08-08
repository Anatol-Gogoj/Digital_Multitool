#!/usr/bin/env python3
"""Interactive live tuner for the SLDEA edge-detection parameters.

A low-weight slider screen: it picks three frames from a run -- baseline,
mid-run and late -- and redraws the current algorithm's outlines live as you
drag the thresholds. When the outlines look right, Save writes the values
into the run's setup.txt so Edge Review (and any later auto-process) uses
exactly what you tuned.

It reuses sldea_edge.candidates() unchanged, so the outlines here ARE what
the pipeline produces -- this is a viewfinder on the real algorithm, not a
reimplementation.

    python sldea_tuner.py [RUNDIR]              # or pick one in the window
    python sldea_tuner.py 1                     # bench shortcut (see
                                                # sldea_edge.BENCH_RUNS)
    python sldea_tuner.py --selftest OUT.png    # headless render, no window
    python sldea_tuner.py --resolve PATH        # print the resolved run

Without a RUNDIR it opens on the newest run under SCPI_SLDEA_DIR, the same
one it has always opened -- but now the Run box lists the others and says
which one is loaded, because Save rewrites THAT run's setup.txt (`#197`).

Also doubles as the labelling front-end for the ML route: tune until the
masks are right, then the saved outlines are weak labels to correct/export.
"""
import os
import sys

import numpy as np

import sldea_edge as se
import tk_fontfix                      # must run before tkinter connects:
tk_fontfix.apply()                     # colour-emoji glyphs hard-crash Tk

DEFAULT_DIR = os.environ.get(
    'SCPI_SLDEA_DIR', '/mnt/shareDrive/robot_incubator/SLDEA_data')

# (key, label, lo, hi, resolution, is_int) -- the image-affecting settings
SLIDERS = [
    ('blur_px',       'Blur (px, odd)',            1,   21,  2,    True),
    ('diff_thresh',   'Diff thresh (0=auto Otsu)', 0,   60,  1,    True),
    ('min_diff',      'No-change gate (diff p99)', 0,   40,  1,    False),
    ('min_solidity',  'Min fill of outline',       0.0, 1.0, 0.01, False),
    ('roi_frac',      'Search ROI fraction',       0.3, 1.0, 0.01, False),
    ('electrode_lum', 'Electrode mask (0=off)',    0,   255, 1,    False),
    ('wrinkle_ratio', 'Wrinkle-mode ratio',        1.0, 3.0, 0.05, False),
]
# one-line explanations shown as a hint row under the sliders (audit
# 2026-07-25: the Edge Review twins have tips; the tuner had none)
SLIDER_HINTS = {
    'blur_px': 'noise smoothing before differencing — higher = smoother',
    'diff_thresh': 'fixed change threshold; 0 lets Otsu pick it per frame',
    'min_diff': 'below this the frame counts as unchanged vs baseline',
    'min_solidity': 'outlines emptier than this go to review, never auto',
    'roi_frac': 'central search window (electrode glare lives at edges)',
    'electrode_lum': 'baseline pixels this BRIGHT are masked; default 255 '
                     '= off (a carbon-black electrode is dark, so masking '
                     'by brightness catches paper instead and breaks '
                     'detection). Lower it only for a bright/copper '
                     'electrode.',
    'wrinkle_ratio': 'texture-vs-baseline index that counts as wrinkled',
}
PANEL_COLORS = ['#00e676', '#40c4ff', '#ff9100']   # best, 2nd, 3rd


def _fkv(row):
    try:
        return float(row.get('nominal_kV') or row.get('nominal_kv') or 'nan')
    except (TypeError, ValueError):
        return float('nan')


def choose_indices(rows):
    """Pick (label, row_index) for baseline / mid-run / late frames.

    Returns 1-3 unique pairs, in that order. Baseline is the tagged baseline
    row (else row 0); late is the highest-nominal-kV content frame; mid-run
    is the content frame nearest the voltage midpoint (or the median index
    when voltages are missing)."""
    n = len(rows)
    if n == 0:
        return []
    base = next((i for i, r in enumerate(rows)
                 if (r.get('tag') or '') == 'baseline'), 0)
    content = [i for i, r in enumerate(rows)
               if i != base and (r.get('frame_file') or '').strip()]
    if not content:
        content = [i for i in range(n) if i != base] or [base]

    def kv_key(i):
        kv = _fkv(rows[i])
        return (-1e9 if np.isnan(kv) else kv, i)

    late = max(content, key=kv_key)
    kv_b, kv_l = _fkv(rows[base]), _fkv(rows[late])
    if not np.isnan(kv_b) and not np.isnan(kv_l) and kv_l > kv_b:
        target = 0.5 * (kv_b + kv_l)
        mid = min(content, key=lambda i: abs(_fkv(rows[i]) - target)
                  if not np.isnan(_fkv(rows[i])) else 1e9)
    else:
        mid = content[len(content) // 2]
    # if mid collided, try the median-index content frame not already used
    if mid in (base, late):
        spare = [i for i in content if i not in (base, late)]
        if spare:
            mid = spare[len(spare) // 2]

    out = []
    for label, idx in (('baseline', base), ('mid-run', mid), ('late', late)):
        if idx not in [o[1] for o in out]:
            out.append((label, idx))
    return out


def load_panels(run, picks):
    """[(label, idx)] -> [{label, idx, row, gray}] with full-res gray frames
    actually loadable (skips ones whose image is missing)."""
    panels = []
    for label, idx in picks:
        row = run['rows'][idx]
        gray = se.load_gray(se.frame_path(run, row))
        if gray is not None:
            panels.append({'label': label, 'idx': idx, 'row': row,
                           'gray': gray})
    return panels


def baseline_panel(panels):
    """The panel that IS the baseline, by label — or None when the
    baseline frame did not load. Positional panels[0] silently promoted
    a mid-run (activated) frame to baseline whenever the real one was
    0-byte/truncated, referencing every diff, outline and mm² of the
    tuning session to an activated state while the footer promised Edge
    Review parity (audit 2026-08-05). No baseline -> refuse, exactly
    like Edge Review."""
    return next((p for p in panels if p['label'] == 'baseline'), None)


def detect_panels(panels, base_gray, settings, rows, anchor=None):
    """Run candidates() for each panel; return (results_by_idx, cands_by_idx,
    mm_scale).

    The scale prefers the run's RECORDED manual anchor (`anchor`, from
    se.load_scale_anchor — what Edge Review's Save actually used and
    persisted since 2026-08-05), then the automatic baseline-disc trace.
    Before that, this docstring claimed baseline-disc parity 'exactly
    like Edge Review', which stopped being true the day the scale gate
    made the manual anchor mandatory there (audit 2026-08-05)."""
    results, cands = {}, {}
    for p in panels:
        cl = se.candidates(base_gray, p['gray'], settings)
        cands[p['idx']] = cl
        results[p['idx']] = cl[0] if cl else None
    ref = se.baseline_disc(base_gray, settings)
    if anchor and anchor.get('diam_px'):
        ref = anchor
    scale = se.mm_per_px(results, rows, settings, baseline_ref=ref)
    return results, cands, scale


def norm_bg_value(checked, orig):
    """The norm_bg value the tuner's two-state checkbox stands for.

    The checkbox collapses a three-state int (0=off, 1=legacy scalar,
    2=affine); merely OPENING the tuner on a norm_bg:1 run used to
    rewrite it to 2 in the startup recompute, and Save persisted the
    silent upgrade into setup.txt — breaking sldea_edge's promise that
    'a run tuned under it reprocesses identically' (audit 2026-08-05).
    Checked keeps the run's own normalizing mode; only a run that never
    had one gets the affine default."""
    if not checked:
        return 0
    return orig if orig in (1, 2) else 2


def _panel_title(panel, cands, scale, settings=None):
    row = panel['row']
    kv = row.get('nominal_kV') or '?'
    head = f"{panel['label']}  ·  {kv} kV"
    if not cands:
        return head + "\nno change (gated)"
    c = cands[0]
    area = c['area_px']
    mm2 = f"{area * scale * scale:.1f} mm²  ·  " if scale else ""
    # the run's LIVE settings, not defaults — the footer promises this
    # matches Edge Review exactly (audit 2026-07-25)
    rev = "REVIEW" if se.needs_review(
        cands, settings or se.DEFAULT_SETTINGS) else "ok"
    return (head + f"  ·  {c['method']}\n{mm2}{area:.0f} px²  ·  "
            f"fill {c['solidity']:.2f}  ·  wrinkle {c.get('wrinkle', 0):.2f}"
            f"  ·  conf {c['conf']:.2f}  ·  {rev}")


def render(ax, panel, cands, scale, fill=True, settings=None):
    """Draw one panel: the frame + candidate outlines (best thick), optional
    translucent fill of the chosen region, and a stats title. Reuses a
    persistent imshow so live updates only touch the overlays."""
    im = ax._tuner_im if hasattr(ax, '_tuner_im') else None
    if im is None:
        ax._tuner_im = ax.imshow(panel['gray'], cmap='gray', vmin=0, vmax=255)
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        im.set_data(panel['gray'])
    # clear previous overlay artists
    for art in list(ax.lines) + list(ax.collections) + list(ax.patches):
        art.remove()
    for k, c in enumerate(cands):
        pts = np.asarray(c['contour'], float)
        if len(pts) < 3:
            continue
        xs = np.append(pts[:, 0], pts[0, 0])
        ys = np.append(pts[:, 1], pts[0, 1])
        col = PANEL_COLORS[min(k, len(PANEL_COLORS) - 1)]
        ax.plot(xs, ys, color=col, lw=2.0 if k == 0 else 1.0)
        if k == 0 and fill:
            ax.fill(xs, ys, color=col, alpha=0.18)
    ax.set_title(_panel_title(panel, cands, scale, settings), fontsize=8.5,
                 loc='left')


def build_settings(rundir):
    return se.load_settings(rundir)


# ---------------------------------------------------------------------------
# headless self-test: synthesise a tiny run, render, save a PNG (no window)
# ---------------------------------------------------------------------------

def _selftest(out_png):
    import csv
    import tempfile

    import cv2
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    d = tempfile.mkdtemp(prefix='tuner_selftest_')
    frames = os.path.join(d, 'frames')
    os.makedirs(frames)
    cols = ['snapshot', 'step', 'tag', 'nominal_kV', 'control_V',
            'measured_kV', 'measured_uA', 't_planned_s', 'timestamp',
            'frame_file', 'active_area_px', 'active_area_mm2',
            'active_diam_mm', 'notes']

    def disc(r, level, texture=False):
        img = np.full((240, 320), 90.0, np.float32)
        yy, xx = np.mgrid[0:240, 0:320]
        m = (xx - 160) ** 2 + (yy - 120) ** 2 <= r * r
        img[m] += level + (30 * ((xx[m] // 4) % 2) if texture else 0)
        return np.clip(img, 0, 255).astype(np.uint8)

    rows = []
    specs = [('baseline', 0.0, disc(0, 0)),
             ('post-ramp', 3.0, disc(45, 30)),
             ('post-ramp', 6.0, disc(70, 40, texture=True))]
    for k, (tag, kv, im) in enumerate(specs):
        fn = f'SLDEA_s{k:02d}_{kv:05.2f}kV_{tag}.png'
        cv2.imwrite(os.path.join(frames, fn), im)
        rows.append({**{c: '' for c in cols}, 'tag': tag, 'nominal_kV': kv,
                     'frame_file': fn, 'step': k})
    with open(os.path.join(d, 'data.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    run = se.load_run(d)
    picks = choose_indices(run['rows'])
    assert [p[0] for p in picks] == ['baseline', 'mid-run', 'late'], picks
    panels = load_panels(run, picks)
    assert len(panels) == 3, panels
    settings = build_settings(d)
    bp = baseline_panel(panels)
    assert bp is not None and bp['label'] == 'baseline', panels
    base_gray = bp['gray']
    _, cands, scale = detect_panels(panels, base_gray, settings,
                                    run['rows'])
    assert cands[panels[2]['idx']], "late frame should detect a region"

    fig, axs = plt.subplots(1, 3, figsize=(15, 5))
    for ax, p in zip(axs, panels):
        render(ax, p, cands[p['idx']], scale)
    fig.tight_layout()
    fig.savefig(out_png, dpi=90)
    print(f"selftest OK -> {out_png}  (picks {[(l, i) for l, i in picks]}, "
          f"late area {cands[panels[2]['idx']][0]['area_px']:.0f} px)")


# ---------------------------------------------------------------------------
# run discovery for the picker -- NO Tk in this section
# ---------------------------------------------------------------------------

# Run resolution lives in sldea_edge -- the Tk-free module every reader
# already imports, so the diagnostic gets the same rules without dragging
# the font workaround in. Kept under the old names: gui.py calls
# _newest_run, and the Windows launcher calls resolve_run.
#
# runs_parent -- the one-level descent into a campaign wrapper -- was
# written here for `#197`'s picker and moved to sldea_edge for `#261`, so
# se.newest_run and se.resolve_run descend too and the launcher's
# --resolve step stops reporting "no run found" about a wrapper holding
# 13 runs. The rule itself is documented at se.runs_parent; this name
# stays because the picker and the tests below call it.
_newest_run = se.newest_run
resolve_run = se.resolve_run
runs_parent = se.runs_parent


def list_runs(parent):
    """Run directory NAMES directly under `parent`, newest name first.

    A run is anything se.run_csv() accepts -- the same test Edge Review's
    listing uses -- so a custom-named run (P3_1_2.5mL_20260728) or one
    whose data.csv was renamed data1.csv is a run here exactly as it is
    there. Sorted like Edge Review's box (name, descending) so the two
    windows show one operator the same list in the same order.

    NAMES only. The picker pairs index i with its own label, so a run name
    that happens to contain the label separator cannot be mis-read back
    into a different directory."""
    try:
        names = [n for n in os.listdir(parent)
                 if os.path.isdir(os.path.join(parent, n))
                 and se.run_csv(os.path.join(parent, n))]
    except OSError:
        return []
    return sorted(names, reverse=True)


def run_label(rundir):
    """The suffix the picker shows after a run's name ('' for none).

    Edge Review flags '✓ processed' -- has this run got detected areas.
    The tuner's question is the other one, because its Save OVERWRITES a
    run's tuned block: has this run been tuned already. Found through
    se.EDGE_HDR, the constant load_settings/save_settings key off, rather
    than a second copy of the parsing."""
    try:
        with open(os.path.join(rundir, 'setup.txt'), encoding='utf-8',
                  errors='replace') as f:
            return '  ✓ tuned' if se.EDGE_HDR in f.read() else ''
    except OSError:
        return ''


def pick_index(names, target):
    """Index of the run NAMED `target` in `names`, or None if absent.

    None means 'not there', never 'use 0'. Edge Review learned this in
    audit 2026-07-25, when a missing target silently processed the newest
    run instead; the tuner writes setup.txt, so the same substitution
    would rewrite the detection settings of a run nobody named."""
    try:
        return names.index(target)
    except ValueError:
        return None


def dirty_keys(loaded, current):
    """Setting keys whose SAVED value differs between `loaded` and
    `current` -- i.e. what Save would change in setup.txt, and therefore
    exactly what switching runs would throw away.

    Compared over se.DEFAULT_SETTINGS (what save_settings writes) and
    through the same '%g' formatting it writes with, so a slider nudge too
    small to reach the file never raises a discard prompt."""
    out = []
    for k in se.DEFAULT_SETTINGS:
        a, b = loaded.get(k), current.get(k)
        try:
            same = f"{float(a):g}" == f"{float(b):g}"
        except (TypeError, ValueError):
            same = a == b
        if not same:
            out.append(k)
    return out


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

TITLE = "SLDEA edge tuner"
BANNER_LOADED = '#0f2b46'          # the run-identity bar: loaded / nothing
BANNER_EMPTY = '#4a4a4a'


class TunerWindow:
    """The tuner window: run picker, panels, sliders, Save.

    Lifted out of main() for `#197`. The run can now change while the
    window is open, so the per-run state -- run, panels, baseline frame,
    settings, scale anchor -- has to live somewhere one callback can
    replace as a unit, and the loaded run has to be visible at all times
    because Save rewrites THAT run's setup.txt.

    Everything here is UI. Run discovery is the Tk-free block above
    (list_runs / runs_parent / pick_index), which goes through se.run_csv
    and se.newest_run, so the tuner and Edge Review cannot end up
    disagreeing about what a run is or which one is newest."""

    def __init__(self, root, target=None, parent=None, messagebox=None):
        import tkinter as tk
        from tkinter import filedialog, messagebox as mb, ttk
        import matplotlib
        matplotlib.use('TkAgg')
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

        self.tk, self.ttk, self.filedialog = tk, ttk, filedialog
        self.mb = messagebox or mb          # injectable: the tests drive the
        self.plt = plt                      # discard prompt without a modal
        self.root = root
        # per-run state -- all of it replaced together by _load/_unload
        self.rundir = None
        self.parent = ''
        self.run_names = []
        self.run = None
        self.panels = []
        self.base_gray = None
        self.anchor = None
        self.settings = {}
        self.loaded = {}                    # settings as they came off disk
        self.orig_norm = 2
        self.axs = []
        self._loading = False               # programmatic slider moves
        self._job = None
        self._build(FigureCanvasTkAgg)
        self._start(target, parent)

    # ---------------- construction ----------------
    def _build(self, canvas_cls):
        tk, ttk = self.tk, self.ttk
        self.root.title(TITLE)
        # a debounced recompute outliving the window is a Tcl error on the
        # console at every close ("invalid command name ...recompute")
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        # THE PICKER, top left, in Edge Review's order: pick the run, then
        # everything below it belongs to that run.
        top = ttk.Frame(self.root, padding=(8, 6, 8, 2))
        top.pack(fill='x')
        ttk.Label(top, text="Run:").pack(side='left')
        self.run_box = ttk.Combobox(top, width=42, state='readonly')
        self.run_box.pack(side='left', padx=6)
        self.run_box.bind('<<ComboboxSelected>>', self._pick_run)
        self.browse_btn = ttk.Button(top, text="Browse…",
                                     command=self._browse)
        self.browse_btn.pack(side='left')
        self.status = ttk.Label(top, foreground='#666', text='')
        self.status.pack(side='left', padx=12)

        # THE IDENTITY BAR. The issue's second ask: the loaded run has to
        # be unmissable, because tuning the wrong one silently rewrites its
        # detection settings. Title bar AND this, and it spells out the
        # file Save writes -- not just the run name.
        self.banner = tk.Frame(self.root, bg=BANNER_EMPTY)
        self.banner.pack(fill='x')
        self.banner_run = tk.Label(self.banner, bg=BANNER_EMPTY, fg='#ffffff',
                                   anchor='w', padx=10, pady=3,
                                   font=('TkDefaultFont', 12, 'bold'))
        self.banner_run.pack(fill='x')
        self.banner_path = tk.Label(self.banner, bg=BANNER_EMPTY,
                                    fg='#cfd8e3', anchor='w', padx=10,
                                    pady=0, font=('TkDefaultFont', 8))
        self.banner_path.pack(fill='x')

        self.fig = self.plt.figure(figsize=(15, 5))
        self.canvas = canvas_cls(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)

        ctl = ttk.Frame(self.root, padding=8)
        ctl.pack(fill='x')
        self.scales, self.vallabels, self._slider_cb = {}, {}, {}
        self.fill_var = tk.BooleanVar(value=True)
        # the checkbox is on/off; ON keeps the run's OWN normalizing mode
        # (norm_bg_value): a norm_bg:1 run keeps the legacy scalar until it
        # is retuned — the old unconditional `2 if checked` upgraded it at
        # the startup recompute and Save persisted that silently (audit
        # 2026-08-05)
        self.norm_var = tk.BooleanVar(value=True)
        for r, (key, label, lo, hi, res, is_int) in enumerate(SLIDERS):
            ttk.Label(ctl, text=label, width=24, anchor='e').grid(
                row=r, column=0, sticky='e', padx=(0, 6), pady=1)
            vlab = ttk.Label(ctl, width=6, text='')
            vlab.grid(row=r, column=2, padx=6)
            cb = self._on_slider(key, is_int, vlab)
            sc = tk.Scale(ctl, from_=lo, to=hi, resolution=res,
                          orient='horizontal', showvalue=False, length=360,
                          command=cb)
            sc.grid(row=r, column=1, sticky='ew')
            self.scales[key] = sc
            self.vallabels[key] = vlab
            self._slider_cb[key] = cb
            hint = SLIDER_HINTS.get(key)
            if hint:
                ttk.Label(ctl, text=hint, foreground='#555').grid(
                    row=r, column=3, sticky='w', padx=(10, 0))
        ctl.columnconfigure(1, weight=1)

        opts = ttk.Frame(self.root, padding=(8, 0))
        opts.pack(fill='x')
        ttk.Checkbutton(opts, text="Match frame to baseline: gain+offset "
                        "(norm_bg)", variable=self.norm_var,
                        command=self._on_norm).pack(side='left')
        ttk.Checkbutton(opts, text="Shade detected region",
                        variable=self.fill_var,
                        command=self.schedule).pack(side='left', padx=12)

        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill='x')
        self.save_btn = tk.Button(bar, text="💾 Save to setup.txt",
                                  command=self.do_save, state='disabled',
                                  font=('TkDefaultFont', 9, 'bold'))
        self.save_btn.pack(side='left')
        self.reset_btn = ttk.Button(bar, text="Reset to defaults",
                                    command=self.do_reset, state='disabled')
        self.reset_btn.pack(side='left', padx=8)
        ttk.Label(bar, foreground='#666',
                  text="outlines here = exactly what Edge Review will produce"
                  ).pack(side='right')

    def _on_close(self):
        """Closing is a deliberate act, so it does NOT ask about unsaved
        sliders -- the discard prompt guards the mis-click (a run switch),
        not the decision to leave. Named here so the ruling is on the
        record rather than an omission."""
        self._cancel_job()
        self.root.destroy()

    def _start(self, target, parent):
        """Open on the CLI/gui.py target when there is one, else on the
        default directory -- and list the neighbours either way, so the
        argument route keeps its exact meaning (that run, no picking) while
        the operator can still see what else is there."""
        if target:
            self._populate(target)
        else:
            self._populate(runs_parent(parent or DEFAULT_DIR))

    # ---------------- run selection ----------------
    def _populate(self, path, preselect=None):
        """Accept a run dir (holds a run CSV) or a parent full of runs.

        Mirrors Edge Review's _populate_runs, including its ruling: an
        explicit target that is not in the list is a message asking for a
        pick, NEVER a silent fallback to a different run."""
        path = os.path.abspath(path)
        if se.run_csv(path):
            parent = os.path.dirname(path)
            preselect = preselect or os.path.basename(path)
        else:
            parent = runs_parent(path)
        self.parent = parent
        self.run_names = list_runs(parent)
        self.run_box['values'] = [
            n + run_label(os.path.join(parent, n)) for n in self.run_names]
        if not self.run_names:
            self.run_box.set('')
            self._unload(f"no runs (dirs holding a data CSV) in {parent} — "
                         f"use Browse…")
            return
        if preselect is None:
            # the no-argument default is UNCHANGED: newest by mtime, from
            # the shared resolver. `#197` makes it visible, it does not
            # move it to a different run.
            newest = se.newest_run(parent)
            preselect = os.path.basename(newest) if newest else None
        want = pick_index(self.run_names, preselect) if preselect else 0
        if want is None:
            self.run_box.set('')
            self._unload(f"run '{preselect}' is not in {parent} — pick one")
            return
        self.run_box.current(want)
        self._load(self.run_names[want])

    def _browse(self):
        d = self.filedialog.askdirectory(
            initialdir=self.parent or DEFAULT_DIR)
        if not d:
            return
        if not self._confirm_discard(os.path.basename(os.path.normpath(d))):
            return
        self._populate(d)

    def _pick_run(self, *_):
        i = self.run_box.current()
        if not 0 <= i < len(self.run_names):
            return
        name = self.run_names[i]
        if self.rundir and os.path.join(self.parent, name) == self.rundir:
            return                       # re-picked the loaded run: no-op
        if not self._confirm_discard(name):
            self._restore_selection()
            return
        self._load(name)

    def _restore_selection(self):
        """Put the box back on the run that is actually loaded — after a
        declined discard the widget already shows the other name, and a box
        that disagrees with the banner is the confusion `#197` is about."""
        if not self.rundir:
            self.run_box.set('')
            return
        i = pick_index(self.run_names, os.path.basename(self.rundir))
        if i is not None:
            self.run_box.current(i)

    def _confirm_discard(self, newname):
        """True when it is safe to leave the current run.

        The tuner had no dirty state at all: sliders mutate one settings
        dict and nothing recorded what came off disk, so a mis-click in a
        picker would have silently binned a tuning session. Unsaved values
        are NEVER carried into the next run -- each run's setup.txt is its
        own, and carrying tuned values across is the wrong-run bug wearing
        a different hat -- so the only question is discard or stay."""
        self._flush()
        keys = dirty_keys(self.loaded, self.settings)
        if not keys or not self.rundir:
            return True
        return self.mb.askyesno(
            "Discard unsaved tuning?",
            f"{len(keys)} tuned value(s) on {os.path.basename(self.rundir)} "
            f"were never saved:\n    {', '.join(keys)}\n\n"
            f"Loading {newname} discards them and loads ITS saved settings "
            f"— tuning never carries across runs.\n\nDiscard and switch?")

    # ---------------- load / unload ----------------
    def _load(self, name):
        rundir = os.path.join(self.parent, name)
        # Fail CLOSED, the same ruling as Edge Review's _pick_run: drop the
        # old run's state BEFORE anything that can raise. A half-loaded
        # switch must never leave Save pointing at run A while run B's
        # sliders are on screen -- that writes B's values into A's
        # setup.txt, which is the accident `#197` exists to stop.
        self._unload(f"loading {name}…")
        try:
            run = se.load_run(rundir)
            panels = load_panels(run, choose_indices(run['rows']))
        except Exception as e:                    # unreadable CSV, bad dir
            self._unload(f"{name}: {e}")
            return
        if not panels:
            self._unload(f"{name}: no loadable frames")
            return
        if baseline_panel(panels) is None:
            # refuse-don't-fabricate, same ruling as Edge Review (audit
            # 2026-08-05): tuning against a mid-run frame references every
            # diff to an ACTIVATED state
            self._unload(f"{name}: the baseline frame is unreadable "
                         f"(missing/0-byte/truncated) — no difference "
                         f"imaging is possible. Restore it before tuning.")
            return
        self.rundir = rundir
        self.run = run
        self.panels = panels
        self.base_gray = baseline_panel(panels)['gray']
        self.settings = build_settings(rundir)
        self.anchor = se.load_scale_anchor(rundir)
        self.orig_norm = int(self.settings.get('norm_bg', 2) or 0)
        self._new_axes(len(panels))
        self._sync_controls()
        # snapshot AFTER the sliders are in place: what the operator can
        # see is the reference for "unsaved", so a value the slider
        # rounded on the way in is not reported as their unsaved work
        self.loaded = dict(self.settings)
        self.save_btn.config(state='normal')
        self.reset_btn.config(state='normal')
        self._show_run()
        self.status.config(text=f"{len(self.run_names)} run(s) in "
                                f"{self.parent}")
        self.recompute()

    def _unload(self, status):
        self._cancel_job()
        self.rundir = None
        self.run = None
        self.panels = []
        self.base_gray = None
        self.anchor = None
        self.settings, self.loaded = {}, {}
        self.save_btn.config(state='disabled')
        self.reset_btn.config(state='disabled')
        self.status.config(text=status)
        self._show_run(status)
        self._blank_figure(status)

    def _show_run(self, empty_msg=None):
        """Name the loaded run in the title bar AND the identity bar."""
        if not self.rundir:
            self.root.title(f"{TITLE} — no run loaded")
            self.banner.config(bg=BANNER_EMPTY)
            self.banner_run.config(bg=BANNER_EMPTY,
                                   text="🎚 no run loaded — pick one above")
            self.banner_path.config(bg=BANNER_EMPTY,
                                    text=(empty_msg or ''))
            return
        name = os.path.basename(self.rundir)
        self.root.title(f"{TITLE} — {name}")
        self.banner.config(bg=BANNER_LOADED)
        self.banner_run.config(bg=BANNER_LOADED, text=f"🎚 TUNING   {name}")
        self.banner_path.config(
            bg=BANNER_LOADED,
            text=f"Save rewrites  {os.path.join(self.rundir, 'setup.txt')}")

    # ---------------- figure ----------------
    def _new_axes(self, n):
        self.fig.clf()
        self.fig.set_size_inches(5 * max(n, 1), 5, forward=False)
        self.axs = list(self.fig.subplots(1, n, squeeze=False)[0])

    def _blank_figure(self, msg):
        self.fig.clf()
        self.axs = []
        ax = self.fig.add_subplot(111)
        ax.axis('off')
        ax.text(0.5, 0.5, msg or "pick a run to tune", ha='center',
                va='center', wrap=True, fontsize=11, color='#555')
        self.canvas.draw_idle()

    # ---------------- live update ----------------
    def _cancel_job(self):
        if self._job is not None:
            try:
                self.root.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def recompute(self):
        self._job = None
        if not self.rundir:
            return
        self.settings['norm_bg'] = norm_bg_value(self.norm_var.get(),
                                                 self.orig_norm)
        _, cands, scale = detect_panels(self.panels, self.base_gray,
                                        self.settings, self.run['rows'],
                                        anchor=self.anchor)
        for ax, p in zip(self.axs, self.panels):
            render(ax, p, cands[p['idx']], scale, fill=self.fill_var.get(),
                   settings=self.settings)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def schedule(self, *_):
        # debounce: candidates() on 3 frames is ~0.2 s, so coalesce drags
        if self._loading or not self.rundir:
            return
        self._cancel_job()
        self._job = self.root.after(120, self.recompute)

    def _on_slider(self, key, is_int, lbl):
        def cb(v):
            val = int(round(float(v))) if is_int else round(float(v), 3)
            if key == 'blur_px':
                val = val | 1                     # keep odd
            self.settings[key] = val
            lbl.config(text=(f"{val}" if is_int else f"{val:g}"))
            self.schedule()
        return cb

    def set_slider(self, key, value):
        """Move one slider the way a drag does: the widget AND the settings
        dict behind it.

        Tk invokes a Scale's -command from the widget's REDRAW, which never
        happens while the window is unmapped -- so a plain .set() is a
        silent no-op in a headless test, and the tests move sliders through
        here instead. _flush() covers the mapped case, where the same
        callback also arrives later off the idle queue; running it twice
        with the same value changes nothing."""
        self.scales[key].set(value)
        self._slider_cb[key](self.scales[key].get())

    def _on_norm(self):
        # written through IMMEDIATELY, not only in the debounced
        # recompute: a run switch one click after the toggle would
        # otherwise compare against a settings dict the operator has
        # already changed on screen
        if self.rundir:
            self.settings['norm_bg'] = norm_bg_value(self.norm_var.get(),
                                                     self.orig_norm)
        self.schedule()

    def _flush(self):
        """Run the callbacks Tk queued for the sliders we just .set().

        A PROGRAMMATIC Scale.set() does not call -command there and then;
        Tk defers it to the idle queue. Left to fire on its own the write
        lands after the post-load snapshot, so a value the slider rounds on
        the way in (setup.txt blur_px 4 -> the odd-only slider's 5) would
        read as unsaved operator work and pop a discard prompt on a run
        nobody had touched."""
        try:
            self.root.update_idletasks()
        except Exception:                 # root already destroyed
            pass

    def _sync_controls(self):
        """Put the loaded run's values on the sliders. _loading suppresses
        the redraw each .set() would otherwise schedule -- the callback
        still writes settings, so what is on screen and what Save would
        write stay the same thing."""
        self._loading = True
        try:
            for key, _label, lo, _hi, _res, is_int in SLIDERS:
                cur = float(self.settings.get(
                    key, se.DEFAULT_SETTINGS.get(key, lo)))
                self.scales[key].set(cur)
                self.vallabels[key].config(
                    text=(f"{int(cur)}" if is_int else f"{cur:g}"))
            self.norm_var.set(bool(self.settings.get('norm_bg', 2)))
            self._flush()
            self.settings['norm_bg'] = norm_bg_value(self.norm_var.get(),
                                                     self.orig_norm)
        finally:
            self._loading = False

    # ---------------- actions ----------------
    def do_save(self):
        if not self.rundir:
            return
        self._flush()          # what the sliders show IS what gets written
        path = se.save_settings(self.rundir, self.settings)
        self.loaded = dict(self.settings)         # saved == no longer dirty
        name = os.path.basename(self.rundir)
        self.run_box['values'] = [
            n + run_label(os.path.join(self.parent, n))
            for n in self.run_names]              # this run is '✓ tuned' now
        self._restore_selection()
        self.status.config(text=f"saved {name}\\setup.txt")
        self.mb.showinfo(
            "Saved", f"Tuned settings written to\n\n    {path}\n\nEdge "
            f"Review and auto-process on {name} will now use them.")

    def do_reset(self):
        if not self.rundir:
            return
        self._loading = True
        try:
            for key, _label, lo, _hi, _res, is_int in SLIDERS:
                dv = float(se.DEFAULT_SETTINGS.get(key, lo))
                self.settings[key] = int(dv) if is_int else dv
                self.scales[key].set(dv)
                self.vallabels[key].config(
                    text=(f"{int(dv)}" if is_int else f"{dv:g}"))
            # reset to DEFAULTS is an explicit retune: the affine default
            # applies from here on, unlike the mere open/Save path
            self.orig_norm = int(se.DEFAULT_SETTINGS.get('norm_bg', 2))
            self.norm_var.set(bool(se.DEFAULT_SETTINGS.get('norm_bg', 2)))
            self._flush()
            self.settings['norm_bg'] = norm_bg_value(self.norm_var.get(),
                                                     self.orig_norm)
        finally:
            self._loading = False
        self.schedule()


def main(argv):
    args = [a for a in argv if not a.startswith('--')]
    if '--selftest' in argv:
        _selftest(args[0] if args else 'tuner_selftest.png')
        return 0
    if '--resolve' in argv:
        # For the Windows launcher: print the resolved run directory and
        # exit. A flag rather than `python -c "..."` in the batch file --
        # cmd mangles a command that starts with a quoted path and carries
        # further quoted arguments, which silently broke every path
        # containing a space (bench 2026-07-28).
        target = resolve_run(args[0] if args else None)
        if not target:
            return 2
        print(target)
        return 0

    target = None
    if args:
        # THE ARGUMENT ROUTE IS UNCHANGED and still bypasses the picker:
        # gui.py's Tune button, the Windows launcher and every script pass
        # a path, and they must keep getting that run with no interaction.
        # A path that does not resolve stays a hard error rather than
        # quietly opening a picker on something else (`#197`).
        target = resolve_run(args[0])
        if not target:
            print(f"no run found (looked in {args[0]}); pass a run directory "
                  f"-- one holding data.csv (or data1.csv, data2.csv ...) "
                  f"and a frames/ folder")
            return 2
    elif not list_runs(runs_parent(DEFAULT_DIR)):
        # not fatal any more: the window opens on the picker so Browse...
        # can reach runs the default directory does not hold (ASCII: this
        # goes to a console)
        print(f"no run found under {DEFAULT_DIR}; opening the run picker -- "
              f"use Browse... to reach the run folder")

    import tkinter as tk
    root = tk.Tk()
    TunerWindow(root, target=target, parent=DEFAULT_DIR)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
