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

    python sldea_tuner.py [RUNDIR]              # or newest under the default
    python sldea_tuner.py 1                     # bench shortcut (see
                                                # sldea_edge.BENCH_RUNS)
    python sldea_tuner.py --selftest OUT.png    # headless render, no window
    python sldea_tuner.py --resolve PATH        # print the resolved run

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
    'electrode_lum': 'baseline pixels this bright are masked (copper)',
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
# GUI
# ---------------------------------------------------------------------------

# Run resolution lives in sldea_edge -- the Tk-free module every reader
# already imports, so the diagnostic gets the same rules without dragging
# the font workaround in. Kept under the old names: gui.py calls
# _newest_run, and the Windows launcher calls resolve_run.
_newest_run = se.newest_run
resolve_run = se.resolve_run


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

    rundir = resolve_run(args[0]) if args else _newest_run(DEFAULT_DIR)
    if not rundir:
        where = args[0] if args else DEFAULT_DIR
        print(f"no run found (looked in {where}); pass a run directory -- "
              f"one holding data.csv (or data1.csv, data2.csv ...) and a "
              f"frames/ folder")
        return 2

    import tkinter as tk
    from tkinter import messagebox, ttk
    import matplotlib
    matplotlib.use('TkAgg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

    run = se.load_run(rundir)
    panels = load_panels(run, choose_indices(run['rows']))
    if not panels:
        print("no loadable frames in", rundir)
        return 2
    bp = baseline_panel(panels)
    if bp is None:
        # refuse-don't-fabricate, same ruling as Edge Review (audit
        # 2026-08-05): tuning against a mid-run frame references every
        # diff to an ACTIVATED state and persists thresholds Edge
        # Review will never reproduce
        print(f"the baseline frame of {rundir} is unreadable "
              f"(missing/0-byte/truncated) — no difference imaging is "
              f"possible. Restore it before tuning.")
        return 2
    settings = build_settings(rundir)
    base_gray = bp['gray']
    anchor = se.load_scale_anchor(rundir)

    root = tk.Tk()
    root.title(f"SLDEA edge tuner — {os.path.basename(rundir)}")
    fig, axs = plt.subplots(1, len(panels), figsize=(5 * len(panels), 5))
    if len(panels) == 1:
        axs = [axs]
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack(fill='both', expand=True)

    ctl = ttk.Frame(root, padding=8)
    ctl.pack(fill='x')
    scales, vallabels = {}, {}
    fill_var = tk.BooleanVar(value=True)
    # the checkbox is on/off; ON keeps the run's OWN normalizing mode
    # (norm_bg_value): a norm_bg:1 run keeps the legacy scalar until it
    # is retuned — the old unconditional `2 if checked` upgraded it at
    # the startup recompute and Save persisted that silently (audit
    # 2026-08-05)
    norm_var = tk.BooleanVar(value=bool(settings.get('norm_bg', 2)))
    orig_norm = [int(settings.get('norm_bg', 2) or 0)]
    job = {'id': None}

    def recompute():
        job['id'] = None
        settings['norm_bg'] = norm_bg_value(norm_var.get(), orig_norm[0])
        _, cands, scale = detect_panels(panels, base_gray, settings,
                                        run['rows'], anchor=anchor)
        for ax, p in zip(axs, panels):
            render(ax, p, cands[p['idx']], scale, fill=fill_var.get(),
                   settings=settings)
        fig.tight_layout()
        canvas.draw_idle()

    def schedule(*_):
        # debounce: candidates() on 3 frames is ~0.2 s, so coalesce drags
        if job['id'] is not None:
            root.after_cancel(job['id'])
        job['id'] = root.after(120, recompute)

    def on_slider(key, is_int, lbl):
        def cb(v):
            val = int(round(float(v))) if is_int else round(float(v), 3)
            if key == 'blur_px':
                val = val | 1                     # keep odd
            settings[key] = val
            lbl.config(text=(f"{val}" if is_int else f"{val:g}"))
            schedule()
        return cb

    for r, (key, label, lo, hi, res, is_int) in enumerate(SLIDERS):
        ttk.Label(ctl, text=label, width=24, anchor='e').grid(
            row=r, column=0, sticky='e', padx=(0, 6), pady=1)
        cur = float(settings.get(key, se.DEFAULT_SETTINGS.get(key, lo)))
        vlab = ttk.Label(ctl, width=6,
                         text=(f"{int(cur)}" if is_int else f"{cur:g}"))
        vlab.grid(row=r, column=2, padx=6)
        sc = tk.Scale(ctl, from_=lo, to=hi, resolution=res,
                      orient='horizontal', showvalue=False, length=360,
                      command=on_slider(key, is_int, vlab))
        sc.set(cur)
        sc.grid(row=r, column=1, sticky='ew')
        scales[key] = sc
        vallabels[key] = vlab
        hint = SLIDER_HINTS.get(key)
        if hint:
            ttk.Label(ctl, text=hint, foreground='#555').grid(
                row=r, column=3, sticky='w', padx=(10, 0))
    ctl.columnconfigure(1, weight=1)

    opts = ttk.Frame(root, padding=(8, 0))
    opts.pack(fill='x')
    ttk.Checkbutton(opts, text="Match frame to baseline: gain+offset "
                    "(norm_bg)",
                    variable=norm_var, command=schedule).pack(side='left')
    ttk.Checkbutton(opts, text="Shade detected region", variable=fill_var,
                    command=schedule).pack(side='left', padx=12)

    def do_save():
        se.save_settings(rundir, settings)
        messagebox.showinfo(
            "Saved", "Tuned settings written to setup.txt.\n\nEdge Review "
            "and auto-process on this run will now use them.")

    def do_reset():
        for key, _, lo, hi, res, is_int in SLIDERS:
            dv = float(se.DEFAULT_SETTINGS.get(key, lo))
            settings[key] = int(dv) if is_int else dv
            scales[key].set(dv)
            vallabels[key].config(text=(f"{int(dv)}" if is_int else f"{dv:g}"))
        # reset to DEFAULTS is an explicit retune: the affine default
        # applies from here on, unlike the mere open/Save path
        orig_norm[0] = int(se.DEFAULT_SETTINGS.get('norm_bg', 2))
        norm_var.set(bool(se.DEFAULT_SETTINGS.get('norm_bg', 2)))
        schedule()

    bar = ttk.Frame(root, padding=8)
    bar.pack(fill='x')
    tk.Button(bar, text="💾 Save to setup.txt", command=do_save,
              font=('TkDefaultFont', 9, 'bold')).pack(side='left')
    ttk.Button(bar, text="Reset to defaults", command=do_reset).pack(
        side='left', padx=8)
    ttk.Label(bar, foreground='#666',
              text="outlines here = exactly what Edge Review will produce"
              ).pack(side='right')

    recompute()
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
