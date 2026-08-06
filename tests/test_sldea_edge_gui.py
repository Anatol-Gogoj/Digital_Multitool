#!/usr/bin/env python3
"""Review-card + window semantics for sldea_edge_gui (#171-#173, #176,
#178, #179).

The selection-highlight rule (hot_slot), the card contain-fit math
(card_geometry) and the panel-text elide are pure and tested headlessly.
The candidate-D flow -- trace Done STAGES + labels, Accept commits, a
re-trace replaces the pending polygon -- the #176 Advanced... singleton
(and the one-settings-path doctrine: no Tune button since 2026-07-31),
the #178 view-tracking card and the #179 fixed side panel drive a real
EdgeReviewApp on a synthetic run; those parts need a Tk display and
skip cleanly when one cannot be opened (headless CI without Xvfb).

Run: .venv/bin/python tests/test_sldea_edge_gui.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import csv
import os
import re
import shutil
import tempfile
import time

import numpy as np


def test_hot_slot_follows_selection_before_any_result():
    """#171: an unreviewed frame must highlight the radio selection --
    it used to draw every outline thin because only an accepted result
    ever set the line weight."""
    import sldea_edge_gui as gui
    A = {'method': 'disc-fit'}
    B = {'method': 'diff-hi'}
    D = {'method': 'manual-trace'}
    entries = [(0, A), (1, B)]
    assert gui.hot_slot(entries, None, 0) == 0          # the bug's case
    assert gui.hot_slot(entries, None, 1) == 1
    # selection points at an empty slot -> nothing reads as selected
    assert gui.hot_slot(entries, None, gui.TRACE_SLOT) is None
    # an accepted frame follows its result, not the radio
    assert gui.hot_slot(entries, A, 1) == 0
    # a manual-trace result / staged D highlights slot D
    entries_d = entries + [(gui.TRACE_SLOT, D)]
    assert gui.hot_slot(entries_d, D, 0) == gui.TRACE_SLOT
    assert gui.hot_slot(entries_d, None, gui.TRACE_SLOT) == gui.TRACE_SLOT
    assert gui.hot_slot([], None, 0) is None


def test_card_geometry_contain_fit_center_and_cap():
    """#178: the card contain-fits the view (aspect kept), is centered,
    and upscale is capped so a huge monitor does not interpolate mush."""
    import sldea_edge_gui as gui
    # 1080p frame in the legacy 780x560 view: width-limited, letterboxed
    s, w, h, x, y = gui.card_geometry(1920, 1080, 780, 560)
    assert abs(s - 780 / 1920) < 1e-9
    assert (w, h) == (780, 439) and (x, y) == (0, 60)
    # a wider view: the card GROWS to fill it (the bug: it never did)
    s, w, h, x, y = gui.card_geometry(1920, 1080, 1400, 900)
    assert (w, h) == (1400, 788) and (x, y) == (0, 56)
    # height-limited view: letterbox left/right, still centered
    s, w, h, x, y = gui.card_geometry(1920, 1080, 500, 200)
    assert h == 200 and x == (500 - w) // 2 and y == 0
    # upscale cap: a small frame in a huge view stops at MAX_UPSCALE
    s, w, h, x, y = gui.card_geometry(320, 240, 1400, 1200)
    assert s == gui.MAX_UPSCALE and (w, h) == (640, 480)
    assert (x, y) == (380, 360)
    # invariants: the card never exceeds the view; degenerate views are
    # clamped to >= 1 px so PIL resize cannot be asked for a 0-size image
    for vw, vh in ((780, 560), (1400, 900), (10, 10), (1, 1)):
        s, w, h, x, y = gui.card_geometry(1920, 1080, vw, vh)
        assert 1 <= w <= max(vw, 1) and 1 <= h <= max(vh, 1)
        assert x == (vw - w) // 2 and y == (vh - h) // 2


def test_side_text_elide_drops_the_tail_first():
    """#179: over-long panel text is elided to the budget instead of
    resizing the panel; the tail (the wrinkle term) goes first, conf
    survives longer."""
    import sldea_edge_gui as gui
    m = len                                 # 1 px per char
    assert gui.elide("short", 10, m) == "short"
    txt = "A: disc-fit  123456 px2  conf 0.97  w1.2"        # 40 chars
    out = gui.elide(txt, 35, m)
    assert m(out) <= 35 and out.endswith('…')
    assert 'conf 0.97' in out and 'w1.2' not in out
    out = gui.elide(txt, 30, m)
    assert m(out) <= 30 and out.startswith("A: disc-fit")
    # exact fit is untouched; the degenerate budget still returns a mark
    assert gui.elide(txt, 40, m) == txt
    assert gui.elide("abc", 0, m) == '…'


def _fake_run(dirpath):
    """Minimal synthetic SLDEA run (baseline + two activated frames) --
    the same scene test_app_launch boots the real GUI on."""
    import cv2
    frames = os.path.join(dirpath, 'frames')
    os.makedirs(frames, exist_ok=True)
    cols = ['snapshot', 'step', 'tag', 'nominal_kV', 'control_V',
            'measured_kV', 'measured_uA', 't_planned_s', 'timestamp',
            'frame_file', 'active_area_px', 'active_area_mm2',
            'active_diam_mm', 'wrinkle_idx', 'notes']
    rows = []
    yy, xx = np.mgrid[0:240, 0:320]
    # resting disc r=80 (160 px dia): INSIDE baseline_disc's upper size
    # gate (2r <= 0.85*dmin = 173 px for a 240-px frame) so the scale
    # cross-check has a real auto fit to test against — r=90 silently
    # made that branch dead code (review 2026-08-05)
    for k, (tag, kv, r) in enumerate((('baseline', 0.0, 0),
                                      ('post-ramp', 3.0, 45),
                                      ('post-ramp', 6.0, 70))):
        img = np.full((240, 320), 190.0, np.float32)
        img[(xx - 160) ** 2 + (yy - 120) ** 2 <= 80 * 80] = 165.0
        if r:
            img[(xx - 160) ** 2 + (yy - 120) ** 2 <= r * r] += 35
        fn = f'SLDEA_s{k:02d}_{kv:05.2f}kV_{tag}.png'
        cv2.imwrite(os.path.join(frames, fn),
                    np.clip(img, 0, 255).astype(np.uint8))
        rows.append({**{c: '' for c in cols}, 'tag': tag, 'nominal_kV': kv,
                     'frame_file': fn, 'step': k, 'snapshot': k + 1})
    with open(os.path.join(dirpath, 'data.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(dirpath, 'setup.txt'), 'w') as f:
        f.write("SLDEA Test -- synthetic\nDEA nominal diameter: 16 mm\n")
    return dirpath


def test_trace_stages_as_candidate_D_then_accept_commits():
    """#172 acceptance: Done stages (results untouched, label appended,
    D selected + row populated); a re-trace replaces the pending polygon
    and appends another label; Accept commits through the normal path
    WITHOUT appending a third label (labels belong to Done)."""
    import sldea_edge_gui as gui       # applies tk_fontfix before Tk
    import sldea_trace as strc
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_gui_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None, "synthetic run failed to load"
        app.detect_all_sync()
        i = app.frame_rows[1]                    # first activated frame
        app.pos = app.frame_rows.index(i)        # the tracer's invariant
        before = app.results.get(i)
        meta = {'zoom': 1.0,
                'overlays': {'resting': True, 'candidates': False,
                             'prev': False},
                'elapsed_s': 5.0, 'snapped': False}
        poly1 = [(60.0, 40.0), (260.0, 40.0), (260.0, 200.0),
                 (60.0, 200.0)]
        app._trace_staged(i, poly1, meta)
        # staged, NOT committed: the frame's result is untouched...
        assert app.results.get(i) is before
        t = app.traces[i]
        assert t['method'] == 'manual-trace' and t['conf'] == 1.0
        assert t['trace_points'] == poly1
        # ...the D radio is selected and shows the trace's details...
        assert app.cand_var.get() == gui.TRACE_SLOT
        assert 'manual-trace' in app.cand_radios[gui.TRACE_SLOT]['text']
        # ...and the label is already in the sidecar (appended at Done)
        assert len(strc.load_labels(run)) == 1
        # re-trace: the pending polygon is REPLACED, a second label
        # appends (repeat traces measure operator repeatability)
        poly2 = [(65.0, 45.0), (255.0, 45.0), (255.0, 195.0),
                 (65.0, 195.0)]
        app._trace_staged(i, poly2, meta)
        assert app.traces[i]['trace_points'] == poly2
        assert len(strc.load_labels(run)) == 2
        # Accept commits the staged D through the normal path; no third
        # label is appended by the commit
        app.cand_var.set(gui.TRACE_SLOT)
        app._choose_current()
        r = app.results[i]
        assert r['method'] == 'manual-trace' and r['conf'] == 1.0
        assert r['chosen_by'] == 'user'
        assert abs(r['area_px'] - strc.polygon_area(poly2)) < 1e-6
        assert len(strc.load_labels(run)) == 2
        # navigating away and back keeps D selected via the result
        app._show()
        assert app.cand_var.get() == gui.TRACE_SLOT
        # Accept with D selected but nothing staged must be a no-op
        j = app.frame_rows[2]
        app.pos = app.frame_rows.index(j)
        before_j = app.results.get(j)
        app.cand_var.set(gui.TRACE_SLOT)
        app._choose_current()
        assert app.results.get(j) is before_j
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_aux_windows_are_singletons_and_tune_is_gone():
    """#176: re-clicking Advanced... fronts the live dialog instead of
    stacking another. And Edge Review has ONE settings-editing path
    (operator decision 2026-07-31): the Tune button is gone -- the tuner
    is a development instrument, launched directly -- while Calibrate
    stays, the manual half of baseline_disc's refuse-don't-fabricate
    contract."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_gui_win_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None, "synthetic run failed to load"
        # Advanced...: one dialog, re-click fronts it
        app._advanced()
        w1 = app._adv_win
        assert w1 is not None and w1.winfo_exists()
        app._advanced()
        assert app._adv_win is w1
        tops = [w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel)]
        assert len(tops) == 1, f"stacked dialogs: {len(tops)}"
        # a closed dialog is not a live singleton: reopen builds anew
        w1.destroy()
        app._advanced()
        assert app._adv_win is not w1 and app._adv_win.winfo_exists()
        app._adv_win.destroy()
        # one settings path: no Tune affordance anywhere; Calibrate stays
        texts = []

        def walk(w):
            for ch in w.winfo_children():
                try:
                    texts.append(str(ch.cget('text')))
                except tk.TclError:
                    pass
                walk(ch)

        walk(root)
        assert not any('Tune' in t for t in texts), texts
        assert any('Calibrate' in t for t in texts), texts
        assert not hasattr(app, '_open_tuner')
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_card_tracks_the_view_and_draws_centered():
    """#178: _render_card fills whatever view it is given (not VIEW_W),
    _draw centers the card on the canvas, and a canvas resize re-renders
    exactly once after the debounce."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_gui_view_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None, "synthetic run failed to load"
        app.detect_all_sync()
        i = app.frame_rows[1]
        app.pos = app.frame_rows.index(i)
        cands = app.cands_all.get(i, [])
        chosen = app.results.get(i)
        # frames are 320x240; exercise cap, downscale and odd aspects
        for vw, vh in ((780, 560), (400, 260), (300, 500)):
            _s, w, h, _x, _y = gui.card_geometry(320, 240, vw, vh)
            img = app._render_card(i, cands, chosen, view=(vw, vh))
            assert (img.width, img.height) == (w, h), (vw, vh)
            app._view_wh = (vw, vh)        # what <Configure> would track
            app._draw(i, cands, chosen)
            items = app.canvas.find_all()
            assert len(items) == 1
            assert app.canvas.coords(items[0]) == [vw // 2, vh // 2]
        # resize storm -> ONE debounced re-render at the final size
        calls = []
        app._draw = lambda *a, **k: calls.append(a)

        class Ev:
            def __init__(self, w, h):
                self.width, self.height = w, h

        app._canvas_resized(Ev(1000, 700))
        app._canvas_resized(Ev(1200, 800))     # supersedes the first
        assert app._view_wh == (1200, 800)
        t0 = time.time()
        while not calls and time.time() - t0 < 3.0:
            root.update()
            time.sleep(0.01)
        t0 = time.time()                       # settle: no second render
        while time.time() - t0 < 0.3:
            root.update()
            time.sleep(0.01)
        assert len(calls) == 1, f"debounce broke: {len(calls)} renders"
        # a same-size event must not schedule anything
        app._canvas_resized(Ev(1200, 800))
        assert app._resize_job is None
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_side_panel_geometry_is_fixed_across_frames():
    """#179 acceptance: the side panel's geometry must not follow its
    content -- absurd radio text, a staged D row and a wrapping flag
    line change what is SHOWN, never where the buttons sit."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_gui_side_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None, "synthetic run failed to load"
        app.detect_all_sync()
        i, j = app.frame_rows[1], app.frame_rows[2]
        app.pos = app.frame_rows.index(i)
        app._show()
        root.update_idletasks()
        side_w = app._side.winfo_reqwidth()
        info_h = app.info.winfo_reqheight()
        radio_h = app.cand_radios[0].winfo_reqheight()
        assert side_w == gui.SIDE_W, "pack_propagate(False) is off"
        # frame j: worst-case content on every geometry axis
        tri = np.array([[10, 10], [100, 10], [100, 100]], np.int32)
        app.cands_all[j] = [
            {'method': 'disc-fit-with-an-absurdly-long-method-name-tail',
             'area_px': 123456789.0, 'conf': 0.97, 'wrinkle': 1.23,
             'contour': tri}]
        app.traces[j] = {
            'method': 'manual-trace', 'conf': 1.0, 'chosen_by': 'user',
            'area_px': 1234567890123.0, 'diam_px': 1.0, 'cx': 50.0,
            'cy': 50.0, 'contour': tri, 'solidity': 1.0,
            'spread_pct': 0.0, 'ci85_pct': None, 'wrinkle': None,
            'n_points': 12345,
            'trace_points': [(10.0, 10.0), (100.0, 10.0), (100.0, 100.0)],
            'snapped': False}
        app.flags[j] = ("breakdown suspected: current spike beyond the "
                        "configured threshold while the area collapsed "
                        "against a rising voltage (details wrap)")
        app.pos = app.frame_rows.index(j)
        app._show()
        root.update_idletasks()
        assert app._side.winfo_reqwidth() == side_w
        assert app.info.winfo_reqheight() == info_h, \
            "flag line changed the info label's height"
        assert app.cand_radios[0].winfo_reqheight() == radio_h
        # every radio text fits the fixed budget (elided, never clipped
        # by luck) -- measured with the same font the widget renders in
        meas = app._side_font.measure
        for rb in app.cand_radios:
            assert meas(rb['text']) <= gui.RADIO_TEXT_PX, rb['text']
        # and going back to the plain frame restores nothing -- there was
        # nothing to restore
        app.pos = app.frame_rows.index(i)
        app._show()
        root.update_idletasks()
        assert app._side.winfo_reqwidth() == side_w
        assert app.info.winfo_reqheight() == info_h
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_scale_gate_blocks_detect_and_save_until_calibrated():
    """Operator decision 2026-08-05: the px→mm anchor is clicked by hand
    on every run — Detect diverts to the Calibrate dialog, Save hard-
    blocks, detection chains once the anchor exists, and the status line
    reports the manual anchor with the auto disc demoted to cross-check."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_gui_')
    infos, warns = [], []
    real_mb = gui.messagebox

    class _MB:
        @staticmethod
        def showinfo(*a, **k):
            infos.append(a)

        @staticmethod
        def showwarning(*a, **k):
            warns.append(a)

        def __getattr__(self, name):
            return getattr(real_mb, name)

    gui.messagebox = _MB()
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None, "synthetic run failed to load"
        assert app.manual_ref is None
        assert app._diam_recorded()      # fixture setup.txt has the line
        # Detect must divert to the Calibrate dialog, not run detection
        opened = []
        app._calibrate_scale = lambda then_detect=False: opened.append(
            then_detect)
        app.detect()
        assert opened == [True], "gate did not divert to Calibrate"
        assert not app.cands_all, "detection ran without calibration"
        # Save hard-blocks without the anchor
        app.save()
        assert infos, "save() did not block on the scale gate"
        # with the anchor, detection runs and the auto disc fit MUST
        # exist (r=80 fixture sits inside baseline_disc's size gates) —
        # unconditional, so the cross-check can never silently lose its
        # only coverage again (review 2026-08-05)
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app.detect_all_sync()
        assert app.cands_all, "detection did not run once calibrated"
        assert 'scale: manual 160 px' in app.status.cget('text')
        auto_px = (app.base_ref or {}).get('diam_px')
        assert auto_px, ("fixture disc no longer fittable by "
                         "baseline_disc — the cross-check is untested")
        # an exact-match anchor passes the cross-check silently
        warns.clear()
        app.manual_ref = {'method': 'manual-calibration',
                          'diam_px': float(auto_px)}
        app.detect_all_sync()
        assert not warns, warns
        assert '✓' in app.status.cget('text')
        # a wildly different anchor trips it. Deviation is measured
        # against the automatic fit — the REFERENCE — since #215:
        # (250−auto)/auto, matching how the P3_2 field failure was
        # reported (+2.28% of 577.1 px, not of the operator's 590.26)
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 250.0}
        app.detect_all_sync()
        assert warns, "cross-check did not warn on a >3% mismatch"
        assert 'apart' in app.status.cget('text')
        assert 'mask area' in app.status.cget('text')
        # #215: a fresh three-round anchor reports its own spread, and a
        # deviation between the ~1% guard and the 3% modal tier shows the
        # ⚠ WITHOUT a modal (nagging every honest run would train the
        # operator to click through the one that matters)
        warns.clear()
        mid = float(auto_px) * 1.015
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': mid,
                          'n_rounds': 3, 'spread_pct': 0.31,
                          'rounds_px': [mid, mid, mid], 'spread_px': 0.5}
        app.detect_all_sync()
        txt = app.status.cget('text')
        assert 'spread 0.31%' in txt and 'mean of 3' in txt, txt
        assert '⚠' in txt and not warns, (txt, warns)
        # ... but the SAME deviation on a REUSED anchor does warn: that
        # path skipped the calibration-time guard entirely, so this is
        # its only chance to be questioned
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': mid,
                          'reused': True}
        app.detect_all_sync()
        assert warns, "a reused anchor never met the guard and never will"
        assert 'REUSED' in warns[0][1]
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_scale_gate_survives_unreadable_baseline_frame():
    """Review 2026-08-05: a 0-byte/truncated baseline PNG (interrupted
    capture — the disk-full failure mode) used to crash the gate path as
    a stderr-only traceback and permanently lock the run out of Detect,
    Save and --auto. The gate now falls back to the next readable frame
    (flagged non-baseline in the dialog) and, with nothing readable,
    surfaces an error dialog instead of an exception."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_gui_')
    errors = []
    real_mb = gui.messagebox

    class _MB:
        @staticmethod
        def showerror(*a, **k):
            errors.append(a)

        def __getattr__(self, name):
            return getattr(real_mb, name)

    gui.messagebox = _MB()
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        frames = os.path.join(run, 'frames')
        base_png = os.path.join(frames, 'SLDEA_s00_00.00kV_baseline.png')
        open(base_png, 'wb').close()             # 0-byte baseline
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None
        # anchor selection skips the unreadable baseline and falls back
        # to a later, readable frame — flagged as non-baseline, with the
        # frame's name reported for the anchor's provenance record
        img, is_baseline, tried, name = app._anchor_frame()
        assert img is not None and not is_baseline, (is_baseline, tried)
        assert any('baseline' in t for t in tried), tried
        assert name and name.endswith('.png'), name
        # with EVERY frame unreadable, the gate surfaces an error dialog
        # and neither _calibrate_scale nor the Detect gate path raises
        for fn in os.listdir(frames):
            open(os.path.join(frames, fn), 'wb').close()
        img, _, tried, _n = app._anchor_frame()
        assert img is None and len(tried) == 3, tried
        app._calibrate_scale()
        assert errors, "no error dialog for an uncalibratable run"
        errors.clear()
        app.detect()                             # gate path, must not raise
        assert errors and app.manual_ref is None
        assert 'gated' in app.status.cget('text')
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# audit 2026-08-05 regressions
# ---------------------------------------------------------------------------

def _tk_root_or_skip(gui_name):
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped {gui_name}: no display for Tk: {e})")
        return None
    root.withdraw()
    return root


class _StubMB:
    """messagebox stub: records calls, answers askyesno with `yes`."""

    def __init__(self, yes=True):
        self.infos, self.warnings, self.errors, self.asked = [], [], [], []
        self._yes = yes

    def showinfo(self, *a, **k):
        self.infos.append(a)

    def showwarning(self, *a, **k):
        self.warnings.append(a)

    def showerror(self, *a, **k):
        self.errors.append(a)

    def askyesno(self, *a, **k):
        self.asked.append(a)
        return self._yes


def _set_ua(rundir, uas):
    """Rewrite the fixture CSV's measured_uA column (row order)."""
    p = os.path.join(rundir, 'data.csv')
    with open(p, newline='') as f:
        r = csv.DictReader(f)
        rows, cols = list(r), r.fieldnames
    for row, ua in zip(rows, uas):
        row['measured_uA'] = ua
    with open(p, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _widgets(w, kind):
    import tkinter as tk
    cls = tk.Button if kind == 'button' else tk.Label
    out = []
    for c in w.winfo_children():
        if isinstance(c, cls):
            out.append(c)
        out.extend(_widgets(c, kind))
    return out


def _cal_step_button(win):
    btn = [b for b in _widgets(win, 'button')
           if b.cget('text').startswith('Continue')
           or 'Finish' in b.cget('text')]
    assert btn, "no Continue/Finish button in the dialog"
    return btn[0]


def _cal_display(win):
    """Everything the operator can READ in the dialog right now — the
    instruction block, the round header and the live readout. Used to
    prove that a previous round's diameter is nowhere in it."""
    try:
        return ' | '.join(w.cget('text') for w in _widgets(win, 'label'))
    except Exception:
        return ''


class _ModalSpy:
    """messagebox stand-in that records every yes/no question, its
    kwargs, and what the dialog looked like when it was asked.

    `answers` is popped per question; when it runs out the spy answers
    with the question's OWN default=, which is the reviewer's harness for
    finding 1: a prompt with no explicit default, or one defaulting to
    the dangerous button, accepts an anchor nobody read."""

    def __init__(self, real, app=None, answers=None):
        self._real = real
        self._app = app
        self.answers = list(answers or [])
        self.asked = []          # [(title, kwargs)]
        self.msgs = []           # the question text itself
        self.seen = []           # dialog text at the moment of asking

    def _record(self, title, kw, three, msg=''):
        self.asked.append((title, dict(kw)))
        self.msgs.append(msg)
        win = getattr(self._app, '_cal_win', None)
        self.seen.append(_cal_display(win) if win is not None else '')
        assert 'default' in kw, (f"{title}: asked with NO default= — "
                                 f"tkinter's askyesno defaults to YES")
        if self.answers:
            return self.answers.pop(0)
        dflt = kw['default']
        if three:
            return {'yes': True, 'no': False}.get(dflt)   # cancel -> None
        return dflt == 'yes'

    def askyesno(self, title, msg='', **kw):
        return self._record(title, kw, False, msg)

    def askyesnocancel(self, title, msg='', **kw):
        return self._record(title, kw, True, msg)

    def defaults(self):
        return [kw.get('default') for _t, kw in self.asked]

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_calibration_dialog_drives_three_rounds_and_both_gates():
    """#215 end to end THROUGH THE REAL DIALOG (display required; this
    case skips headlessly, so 'tests pass' is not evidence the window
    opens — the geometry and the arithmetic are pinned separately in
    tests/test_sldea_calibration.py).

    Drives the operator's actual path: accept each randomized spawn as
    the fit, three times. Because the spawns are randomized and nothing
    is dragged onto the disc, this deliberately trips BOTH gates — the
    spread gate first, then the anchor guard — and the test answers them,
    which is the point: every gate is a decision, and the decision is
    recorded in the anchor."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_cal_')
    real_mb = gui.messagebox
    spy = _ModalSpy(real_mb)
    answers, asked = spy.answers, spy.asked
    gui.messagebox = spy

    def advance(win, taken):
        """Stand in for root.wait_window: press the Continue/Finish
        button until the dialog closes itself."""
        for _ in range(12):
            if not win.winfo_exists():
                return
            btn = _cal_step_button(win)
            taken.append(btn.cget('text'))
            btn.invoke()

    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None and app.manual_ref is None
        # spread gate (yes/no/cancel: refit / accept as measured / leave
        # the gate closed) -> No, accept as measured; anchor guard
        # ("use anyway?") -> Yes, a deliberate override
        answers[:] = [False, True]
        taken = []
        app.root.wait_window = lambda win: advance(win, taken)
        app._calibrate_scale()
        assert len(asked) == 2, asked
        assert taken[:2] == ['Continue →', 'Continue →'], taken
        assert '✔ Finish calibration' in taken[2]
        ref = app.manual_ref
        assert ref is not None, "three rounds produced no anchor"
        assert ref['n_rounds'] == gui.CAL_ROUNDS == 3
        assert len(ref['rounds_px']) == 3
        # the rounds RESPAWN randomized, so three untouched fits must
        # differ — if they were ever equal the decorrelation is gone and
        # the spread would be a fiction
        assert len(set(ref['rounds_px'])) == 3, ref['rounds_px']
        assert abs(ref['diam_px'] - sum(ref['rounds_px']) / 3.0) < 1e-9
        assert ref['spread_px'] > 0 and ref['spread_pct'] > 0
        assert ref['guard'].startswith('OVERRIDDEN by operator'), ref
        ref['guard'].encode('ascii')          # setup.txt field
        # the override is what Save persists, and it survives the round
        # trip that sldea_diag reads back
        app.manual_ref = dict(ref)
        se_mod = gui.se
        se_mod.save_scale_anchor(app.rundir, {
            'method': 'manual-calibration', 'diam_px': ref['diam_px'],
            'diam_mm': 16.0, 'mm_per_px': 16.0 / ref['diam_px'],
            'n_rounds': ref['n_rounds'], 'rounds_px': ref['rounds_px'],
            'spread_px': ref['spread_px'],
            'spread_pct': ref['spread_pct'], 'guard': ref['guard']})
        back = se_mod.load_scale_anchor(app.rundir)
        assert back['n_rounds'] == 3 and len(back['rounds_px']) == 3
        assert back['guard'] == ref['guard']

        # answering NO to the anchor guard must RESTART, not accept: the
        # override has to be an affirmative act
        app.manual_ref = None
        asked.clear()
        # spread No, guard No (restart), then spread No, guard Yes
        answers[:] = [False, False, False, True]
        taken = []
        app._calibrate_scale()
        assert app.manual_ref is not None
        assert app.manual_ref['n_rounds'] == 3, app.manual_ref
        # 3 rounds, restart, 3 rounds again = 6 presses, and 4 questions
        assert len(taken) == 6, taken
        assert len(asked) == 4, asked
        # EVERY question carried an explicit default (finding 1)
        assert all(kw.get('default') for _t, kw in asked), asked
        # the guard's modal had to print the mean and the reference for
        # its warning to be actionable, so the rounds fitted AFTER it
        # were not blind — and the record says so (review 2026-08-06)
        assert 'refit after a disclosed cross-check' \
            in app.manual_ref['guard'], app.manual_ref['guard']
        app.manual_ref['guard'].encode('ascii')
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def _fixed_spawn(gui, circles):
    """Replace the randomized spawn with a scripted one so a dialog run
    is deterministic. Returns the original for restoring."""
    seq = list(circles)
    orig = gui.spawn_circle

    def fake(_w, _h, _rf, _rnd=None):
        return seq.pop(0) if seq else circles[-1]

    gui.spawn_circle = fake
    return orig


def test_calibration_warnings_default_to_declining_them():
    """FINDING 1 (review 2026-08-06), the reviewer's own harness: stub the
    messagebox so every question is answered with its OWN default, and the
    anchor must NOT be accepted.

    The demonstrated failure: the Toplevel bound <Return> to
    Continue/Finish while the gates used askyesno, which defaults to YES
    and was passed no default=. Six Enter presses produced four "Rounds
    disagree" prompts and then the "Anchor sanity check", and the
    out-of-tolerance anchor was ACCEPTED — the guard that exists to catch
    a P3_2-style error could be dismissed without being read."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_cal_dflt_')
    real_mb, real_spawn = gui.messagebox, gui.spawn_circle
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        spy = _ModalSpy(real_mb, app)             # no answers: all defaults
        gui.messagebox = spy

        def advance(win, taken):
            for _ in range(12):
                if not win.winfo_exists():
                    return
                btn = _cal_step_button(win)
                taken.append(btn.cget('text'))
                btn.invoke()

        app.root.wait_window = lambda win: advance(win, [])
        # (a) three fits that disagree, so the SPREAD gate asks first: its
        # default must leave the gate closed, not accept. Scripted rather
        # than randomized so the question order is deterministic.
        _fixed_spawn(gui, [(160.0, 120.0, 65.0), (160.0, 120.0, 70.0),
                           (160.0, 120.0, 75.0)])
        app._calibrate_scale()
        assert app.manual_ref is None, ("an anchor nobody read was "
                                        "accepted: " + str(app.manual_ref))
        assert spy.asked and spy.asked[0][0] == 'Rounds disagree'
        assert spy.defaults()[0] == 'cancel', spy.asked[0]

        # (b) now make the rounds AGREE so the spread gate passes and the
        # ANCHOR GUARD is the question: a 130 px circle against the
        # fixture's ~160 px disc is a P3_2-shaped miss, 18% out
        spy.asked.clear()
        gui.spawn_circle = lambda *_a, **_k: (160.0, 120.0, 65.0)
        app._calibrate_scale()
        assert app.manual_ref is None, app.manual_ref
        titles = [t for t, _kw in spy.asked]
        assert titles and set(titles) == {'Anchor sanity check'}, titles
        assert set(spy.defaults()) == {'no'}, spy.asked
        # the guard question is asked EVERY time (it restarts the rounds),
        # and never resolves into an acceptance by repetition
        assert len(titles) >= 2, titles
        # (c) an unavailable cross-check is its own question, and it
        # defaults to declining too (finding 3)
        spy.asked.clear()
        app._auto_disc = lambda: None
        app._calibrate_scale()
        assert app.manual_ref is None, app.manual_ref
        assert [t for t, _kw in spy.asked][0] == 'Anchor NOT cross-checked'
        assert set(spy.defaults()) == {'no'}, spy.asked
    finally:
        gui.messagebox, gui.spawn_circle = real_mb, real_spawn
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_return_key_cannot_finish_a_calibration():
    """FINDING 1, the other half: Enter may advance an intermediate round,
    but it must never reach finish() — so it can never reach the spread
    gate or the anchor guard, and therefore can never answer them. The
    last round needs the button."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_cal_ret_')
    real_mb, real_spawn = gui.messagebox, gui.spawn_circle
    seen = {}
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        spy = _ModalSpy(real_mb, app)
        gui.messagebox = spy
        # a fit that would pass both gates if it were ever accepted, so a
        # failure here is unambiguous: only Enter is under test
        gui.spawn_circle = lambda *_a, **_k: (160.0, 120.0, 80.0)

        def hammer(win, _n=14):
            # A synthetic key press only reaches a VIEWABLE, FOCUSED
            # window, and every other case here runs on a withdrawn root
            # (after the first Tk interpreter in a process, an unviewable
            # Toplevel cannot take focus and event_generate is silently
            # dropped). So this one case actually puts the dialog on
            # screen — the only way to test a key binding as an event.
            root.deiconify()
            root.update()
            win.deiconify()
            win.update()
            win.focus_force()
            win.update()
            rounds = set()
            for _ in range(_n):
                if not win.winfo_exists():
                    break
                win.event_generate('<Return>', when='now')
                win.update()
                if win.winfo_exists():
                    mm = re.search(r'Round (\d+) of',
                                   _cal_display(win))
                    if mm:
                        rounds.add(int(mm.group(1)))
            seen['rounds'] = rounds
            seen['alive'] = win.winfo_exists()
            seen['btn'] = (_cal_step_button(win).cget('text')
                           if seen['alive'] else '')
            seen['text'] = _cal_display(win) if seen['alive'] else ''

        app.root.wait_window = hammer
        app._calibrate_scale()
        assert seen.get('alive'), "Enter closed the calibration dialog"
        # self-check FIRST: if this environment refuses to deliver a
        # synthetic key press, the rest of the case proves nothing
        assert seen['rounds'] == {2, 3}, (
            "no <Return> reached the dialog, so nothing here was tested "
            f"(rounds seen: {seen['rounds']})")
        # two Enters advanced rounds 1 and 2; every one after that was
        # refused, so the dialog is parked on the LAST round
        assert 'Finish' in seen['btn'], seen['btn']
        assert app.manual_ref is None, ("Enter accepted an anchor: "
                                        + str(app.manual_ref))
        assert not spy.asked, ("Enter reached a modal warning: "
                               + str(spy.asked))
        assert 'Enter cannot accept an anchor' in seen['text'], seen['text']
    finally:
        gui.messagebox, gui.spawn_circle = real_mb, real_spawn
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_mid_round_display_never_reveals_a_previous_fit():
    """FINDING 2 (review 2026-08-06): the header rendered "accepted so
    far: N px" beside a live "circle: N px across" readout, so an operator
    could wheel round 2 until the two numbers matched. Randomizing the
    spawn is worthless against a printed target — the spread would be
    biased toward zero by construction, the spread gate could never fire,
    and the repeatability figure SLDEA_MEASUREMENT §2.1a converts into an
    error term would be fabricated precision entering the budget.

    Nothing about a previous round may appear in the dialog while rounds
    are still being fitted; everything appears once the last one is in."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_cal_blind_')
    real_mb, real_spawn = gui.messagebox, gui.spawn_circle
    # scripted, distinguishable fits: 130.0, 140.0 then 150.0 px across
    real_spawn = _fixed_spawn(gui, [(160.0, 120.0, 65.0),
                                    (160.0, 120.0, 70.0),
                                    (160.0, 120.0, 75.0)])
    snaps = []
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        # spread gate -> accept as measured; anchor guard -> override
        spy = _ModalSpy(real_mb, app, answers=[False, True])
        gui.messagebox = spy

        def advance(win):
            for _ in range(6):
                if not win.winfo_exists():
                    return
                snaps.append(_cal_display(win))
                _cal_step_button(win).invoke()

        app.root.wait_window = advance
        app._calibrate_scale()
        assert len(snaps) == 3, snaps
        assert app.manual_ref['rounds_px'] == [130.0, 140.0, 150.0]
        # round 1 shows only its own circle; rounds 2 and 3 must contain
        # NO earlier diameter and no running mean (140.0 = the mean of
        # 130/150 too, so its absence in round 3 covers both)
        for i, prior in ((1, ('130.0',)), (2, ('130.0', '140.0'))):
            for v in prior:
                assert v not in snaps[i], (i, v, snaps[i])
        for s in snaps:
            assert 'accepted so far' not in s, s
            assert 'mean' not in s.lower(), s
            assert 'HIDDEN until the last fit' in s, s
        # each round DOES show the circle currently under the cursor —
        # that is the fit being made, not a target to match
        assert 'circle: 130.0 px across' in snaps[0], snaps[0]
        assert 'circle: 140.0 px across' in snaps[1], snaps[1]
        # the spread gate is one of the questions a REFIT can answer, so
        # it too quotes only the percentage — a refit fitted against a
        # disclosed target would be no more independent than round 2 was
        assert spy.asked[0][0] == 'Rounds disagree', spy.asked
        prompt = spy.msgs[0]
        assert '14.29%' in prompt, prompt
        for v in ('130.0', '140.0', '150.0'):
            assert v not in prompt, (v, prompt)
        # nor on the dialog behind it — where the only diameter on screen
        # is the CURRENT circle's own live readout
        for s in spy.seen:
            for v in ('130.0', '140.0', '150.0'):
                assert v not in s.replace(f"circle: {v} px across", ''), \
                    (v, s)
        # THE REVEAL lands once the fitting is over, on the surface that
        # outlives the dialog
        txt = app.status.cget('text')
        assert 'mean of 3: 130.0, 140.0, 150.0 px' in txt, txt
        assert 'spread 20.0 px = 14.29%' in txt, txt
        assert 'OVER GATE' in txt, txt
    finally:
        gui.messagebox, gui.spawn_circle = real_mb, real_spawn
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_unavailable_cross_check_is_stated_not_implied():
    """FINDING 3 (review 2026-08-06): on the fallback-frame path
    _anchor_frame() serves a later frame precisely because the baseline
    row will not load, and _auto_disc() goes through _base_gray(), which
    needs that row — so anchor_guard returned available=False with an
    EMPTY warn list and finish() accepted in silence, one line after the
    dialog announced "cross-checking the mean against the automatic disc
    fit…". Which reads as a check that passed.

    An absent cross-check must now be as loud as a failed one, and it must
    be recorded as a gap in the run's own anchor record."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_cal_nox_')
    real_mb, real_spawn = gui.messagebox, gui.spawn_circle
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        # the real fallback path: a 0-byte baseline PNG. _anchor_frame
        # falls back to a later frame; _base_gray (and so _auto_disc)
        # cannot serve one at all.
        open(os.path.join(run, 'frames',
                          'SLDEA_s00_00.00kV_baseline.png'), 'wb').close()
        app = gui.EdgeReviewApp(root, path=run)
        assert app._base_gray() is None and app._auto_disc() is None
        img, is_base, _tried, _nm = app._anchor_frame()
        assert img is not None and not is_base, "fixture no longer falls back"
        # three identical fits: the spread gate passes, so the ONLY thing
        # standing between this anchor and Save is the cross-check
        gui.spawn_circle = lambda *_a, **_k: (160.0, 120.0, 80.0)
        spy = _ModalSpy(real_mb, app, answers=[True])
        gui.messagebox = spy

        def advance(win):
            for _ in range(6):
                if not win.winfo_exists():
                    return
                _cal_step_button(win).invoke()

        app.root.wait_window = advance
        app._calibrate_scale()
        # it ASKED — silence was the bug
        assert [t for t, _kw in spy.asked] == ['Anchor NOT cross-checked'], \
            spy.asked
        assert spy.defaults() == ['no'], spy.asked
        msg = spy.seen[0]
        assert 'NO automatic cross-check' in msg, msg
        ref = app.manual_ref
        assert ref is not None and ref['n_rounds'] == 3
        # ... and the record says so, in the same voice as a trip
        assert ref['guard'].startswith('NOT CROSS-CHECKED'), ref['guard']
        ref['guard'].encode('ascii')
        assert 'NOT cross-checked' in app.status.cget('text'), \
            app.status.cget('text')
        # (the offline half of finding 3 — sldea_diag reporting the same
        # gap above OK severity — is pinned in
        # tests/test_sldea_calibration.py, which needs no display)
    finally:
        gui.messagebox, gui.spawn_circle = real_mb, real_spawn
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_scale_gate_rearms_on_every_run_switch():
    """audit 2026-08-05 (mutation finding): deleting the manual_ref
    reset in _pick_run left the WHOLE suite green — the branch's
    headline property ('the anchor resets on every run switch') had no
    test. Two runs, calibrate+detect the first, switch: every piece of
    per-run state must re-arm, and Save must block."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('gate rearm')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_rearm_')
    mb = _StubMB()
    real_mb = gui.messagebox
    gui.messagebox = mb
    try:
        _fake_run(os.path.join(d, 'SLDEA_A'))
        _fake_run(os.path.join(d, 'SLDEA_B'))
        app = gui.EdgeReviewApp(root, path=os.path.join(d, 'SLDEA_B'))
        assert app.run is not None
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app.detect_all_sync()
        assert app.results and app.manual_ref is not None
        assert str(app.save_btn['state']) == 'normal'
        other = [i for i, v in enumerate(app.run_box['values'])
                 if 'SLDEA_A' in v][0]
        app.run_box.current(other)
        app._pick_run()
        assert app.manual_ref is None, "gate did NOT re-arm on run switch"
        assert app.base_ref is None and app._base_ref_pending is None
        assert app.results == {} and app.cands_all == {}
        assert app.traces == {} and app.load_fail == {}
        assert str(app.save_btn['state']) == 'disabled'
        # Save blocks on the re-armed gate; Detect diverts to Calibrate
        mb.infos.clear()
        app.save()
        assert mb.infos, "save() did not block after the run switch"
        opened = []
        app._calibrate_scale = lambda then_detect=False: opened.append(1)
        app.detect()
        assert opened, "detect() did not divert after the run switch"
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_run_switch_mid_detect_cannot_cross_contaminate():
    """CRITICAL (audit 2026-08-05): the Run combobox and Browse… stayed
    live during a multi-minute detect, and the stale worker/poll chain
    refilled cands_all, base_ref and the Save button AFTER _pick_run's
    fail-closed reset — run A's areas written through run B's anchor.
    Now: switching is disabled while a worker runs, and even a forced
    switch (the pierced-event case) leaves stale output dropped by the
    generation token."""
    import sldea_edge as se
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('mid-detect switch')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_switch_')
    mb = _StubMB()
    real_mb = gui.messagebox
    real_cands = se.candidates
    gui.messagebox = mb

    def slow_cands(*a, **k):
        time.sleep(0.15)
        return real_cands(*a, **k)

    se.candidates = slow_cands
    try:
        import cv2
        run_a = _fake_run(os.path.join(d, 'SLDEA_A'))
        _fake_run(os.path.join(d, 'SLDEA_B'))
        # run A gets a FOURTH frame so stale run-B output (3 frames,
        # same indices) is distinguishable — without this, a mutant
        # that drops the per-item generation check passed end to end
        # (review 2026-08-05)
        yy, xx = np.mgrid[0:240, 0:320]
        img = np.full((240, 320), 190.0, np.float32)
        img[(xx - 160) ** 2 + (yy - 120) ** 2 <= 80 * 80] = 165.0
        img[(xx - 160) ** 2 + (yy - 120) ** 2 <= 75 * 75] += 35
        fn4 = 'SLDEA_s03_08.00kV_post-ramp.png'
        cv2.imwrite(os.path.join(run_a, 'frames', fn4),
                    np.clip(img, 0, 255).astype(np.uint8))
        pa = os.path.join(run_a, 'data.csv')
        with open(pa, newline='') as f:
            r = csv.DictReader(f)
            rows_a, cols_a = list(r), r.fieldnames
        rows_a.append({**{c: '' for c in cols_a}, 'tag': 'post-ramp',
                       'nominal_kV': '8.0', 'frame_file': fn4,
                       'step': 3, 'snapshot': 4})
        with open(pa, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols_a)
            w.writeheader()
            w.writerows(rows_a)
        app = gui.EdgeReviewApp(root, path=os.path.join(d, 'SLDEA_B'))
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app.detect()
        assert app._detect_busy
        # the UI path is CLOSED during detection
        assert str(app.run_box.cget('state')) == 'disabled'
        assert str(app.browse_btn['state']) == 'disabled'
        assert str(app.save_btn['state']) == 'disabled'
        # force the switch anyway (a queued event / programmatic path)
        app.run_box.config(state='readonly')
        other = [i for i, v in enumerate(app.run_box['values'])
                 if 'SLDEA_A' in v][0]
        app.run_box.current(other)
        app._pick_run()
        assert not app._detect_busy and app.cands_all == {}
        assert app._base_ref_pending is None
        assert len(app.frame_rows) == 4        # run A's extra frame
        # let the STALE worker finish; its output must never apply
        t0 = time.time()
        while time.time() - t0 < 3.0:
            root.update()
            time.sleep(0.02)
        assert app.cands_all == {}, "stale worker refilled cands_all"
        assert app.base_ref is None and app._base_ref_pending is None
        assert str(app.save_btn['state']) == 'disabled'
        # a fresh detect on the new run drains the stale items without
        # applying them and completes cleanly. Run B's stale queue
        # entries (3 frames + sentinel) all precede run A's — a poll
        # that fails to drop them per-item would finish early with B's
        # 3-frame pass and report 'detected 3 frames' (review
        # 2026-08-05: this exact mutant survived the earlier version).
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app.detect()
        t0 = time.time()
        while app._detect_busy and time.time() - t0 < 15.0:
            root.update()
            time.sleep(0.02)
        assert not app._detect_busy, "fresh detect never finished"
        assert sorted(app.cands_all) == app.frame_rows
        assert len(app.cands_all) == 4, \
            "stale sentinel finished the pass on the OLD run's output"
        assert 'detected 4 frames' in app.status.cget('text')
    finally:
        se.candidates = real_cands
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_unreadable_frame_is_refused_not_laundered():
    """CRITICAL (audit 2026-08-05): a missing/undecodable frame produced
    cands=[], which auto-rejected as 'no change vs baseline (auto)',
    skipped the review queue, and Save blanked a previously saved
    hand-traced measurement into 'rejected (no reliable edge)' — a
    confident physical verdict about a file that was never opened (the
    live state of 155425 row 48). Now the row stays queued as UNREADABLE
    and its saved values survive, re-scaled to this session's anchor."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('unreadable frame')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_unread_')
    mb = _StubMB(yes=True)
    real_mb = gui.messagebox
    gui.messagebox = mb
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        # a previous pass's saved measurement on the row whose frame is
        # about to go missing (old anchor: 0.05 mm/px)
        p = os.path.join(run, 'data.csv')
        with open(p, newline='') as f:
            r = csv.DictReader(f)
            rows, cols = list(r), r.fieldnames
        rows[2]['active_area_px'] = '5000'
        rows[2]['active_area_mm2'] = '12.500'
        rows[2]['active_diam_mm'] = '3.989'
        rows[2]['wrinkle_idx'] = '1.63'
        rows[2]['notes'] = 'edge:manual-trace conf 1.00 (user)'
        with open(p, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        os.remove(os.path.join(run, 'frames',
                               'SLDEA_s02_06.00kV_post-ramp.png'))
        app = gui.EdgeReviewApp(root, path=run)
        assert 'MISSING on disk' in app.status.cget('text')
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app.detect_all_sync()
        i = app.frame_rows[2]
        assert i in app.load_fail
        assert i not in app.results, "unreadable frame left the queue"
        assert i in app._queue_list()
        assert i not in app.auto_rej, "unreadable frame auto-rejected"
        assert 'UNREADABLE' in app.status.cget('text')
        # the card SAYS unreadable, not 'no change vs baseline'
        app.pos = app.frame_rows.index(i)
        app._show()
        assert 'UNREADABLE' in app.info.cget('text')
        assert 'no change' not in app.info.cget('text')
        # Save keeps the measurement: px preserved, mm² on THIS anchor
        app.save()
        with open(p, newline='', encoding='utf-8-sig') as f:
            saved = list(csv.DictReader(f))
        assert saved[2]['active_area_px'] == '5000'
        scale = 16.0 / 160.0
        assert saved[2]['active_area_mm2'] == f"{5000 * scale * scale:.3f}"
        assert saved[2]['wrinkle_idx'] == '1.63'
        assert 'frame unreadable' in saved[2]['notes']
        assert 'rejected (no reliable edge)' not in saved[2]['notes']
        # and the dialog told the operator the truth
        dlg = mb.asked[-1][1]
        assert 'UNREADABLE' in dlg and 're-scaled' in dlg
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_missing_baseline_refuses_detection():
    """CRITICAL (audit 2026-08-05): with the baseline unreadable,
    prepared_diff's fallback let the Otsu tiers outline the ROI
    *background* at conf 0.85-0.90 — every frame AUTO-ACCEPTED at 2.74x
    the true area under a perfectly good manual anchor. Detection must
    refuse outright."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('missing baseline')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_nobase_')
    mb = _StubMB()
    real_mb = gui.messagebox
    gui.messagebox = mb
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        base_png = os.path.join(run, 'frames',
                                'SLDEA_s00_00.00kV_baseline.png')
        open(base_png, 'wb').close()             # 0-byte baseline
        app = gui.EdgeReviewApp(root, path=run)
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app.detect_all_sync()
        assert mb.errors, "no refusal dialog for an unreadable baseline"
        assert not app.results and not app.auto_idx, \
            "detection fabricated results without a baseline"
        assert 'REFUSED' in app.status.cget('text')
        # the threaded path refuses identically
        mb.errors.clear()
        app.detect()
        assert mb.errors and not app._detect_busy
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_save_commits_csv_before_renames():
    """audit 2026-08-05: save() renamed frames BEFORE the CSV commit —
    a failed write_back left renamed frames, a stale CSV and a dialog
    promising a .bak that was never made. Now a write_back failure
    leaves the run byte-identical with ZERO files renamed."""
    import sldea_edge as se
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('save ordering')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_order_')
    mb = _StubMB(yes=True)
    real_mb = gui.messagebox
    real_wb = se.write_back
    gui.messagebox = mb
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        # legacy absolute rule (<5 uA rows): row 2 at -90 uA confirms
        _set_ua(run, ['-16', '-10', '-90'])
        app = gui.EdgeReviewApp(root, path=run)
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app.detect_all_sync()
        assert app.flags, "fixture no longer produces a breakdown flag"
        csv_path = app.run['csv_path']
        before = open(csv_path, 'rb').read()

        def boom(*a, **k):
            raise OSError(28, 'No space left on device')

        se.write_back = boom
        app.save()
        assert mb.errors and 'FAILED' in mb.errors[-1][0]
        assert 'No frame files were renamed' in mb.errors[-1][1]
        frames = os.listdir(os.path.join(run, 'frames'))
        assert not any('_BREAKDOWN' in f for f in frames), frames
        assert open(csv_path, 'rb').read() == before, \
            "failed save mutated data.csv"
        # with the disk back, the SAME session saves clean
        se.write_back = real_wb
        app.save()
        frames = os.listdir(os.path.join(run, 'frames'))
        assert any('_BREAKDOWN' in f for f in frames), frames
        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            saved = list(csv.DictReader(f))
        assert '_BREAKDOWN' in saved[2]['frame_file']
        assert os.path.exists(os.path.join(
            run, 'frames', saved[2]['frame_file']))
        assert 'saved' in app.status.cget('text')
    finally:
        se.write_back = real_wb
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_0723_era_run_saves_end_to_end():
    """audit 2026-08-05 (mutation finding): the 14-column-era compat
    branch in save() never executed under any test, and without it a
    07-23 run's Save raised mid-way. Drive a full save on the era
    schema: wrinkle_idx lands before notes, every frame_file resolves
    on disk, and the era tags plot."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('era save')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_era_')
    mb = _StubMB(yes=True)
    real_mb = gui.messagebox
    gui.messagebox = mb
    try:
        import cv2
        rundir = os.path.join(d, 'SLDEA_20260723_000000')
        frames = os.path.join(rundir, 'frames')
        os.makedirs(frames)
        cols = ['snapshot', 'step', 'tag', 'nominal_kV', 'control_V',
                'measured_kV', 'measured_uA', 't_planned_s', 'timestamp',
                'frame_file', 'active_area_px', 'active_area_mm2',
                'active_diam_mm', 'notes']            # 14 cols, no wrinkle
        yy, xx = np.mgrid[0:240, 0:320]
        rows = []
        specs = (('baseline', 0.0, 0, '-1'), ('pre', 3.0, 45, '-2'),
                 ('post', 6.0, 70, '-90'))            # terminal event
        for k, (tag, kv, r, ua) in enumerate(specs):
            img = np.full((240, 320), 190.0, np.float32)
            img[(xx - 160) ** 2 + (yy - 120) ** 2 <= 80 * 80] = 165.0
            if r:
                img[(xx - 160) ** 2 + (yy - 120) ** 2 <= r * r] += 35
            fn = f'SLDEA_s{k:02d}_{kv:05.2f}kV_{tag}.png'
            cv2.imwrite(os.path.join(frames, fn),
                        np.clip(img, 0, 255).astype(np.uint8))
            rows.append({**{c: '' for c in cols}, 'tag': tag,
                         'nominal_kV': kv, 'frame_file': fn, 'step': k,
                         'snapshot': k + 1, 'measured_uA': ua})
        with open(os.path.join(rundir, 'data.csv'), 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        with open(os.path.join(rundir, 'setup.txt'), 'w') as f:
            f.write("SLDEA Test\nDEA nominal diameter: 16 mm\n")

        app = gui.EdgeReviewApp(root, path=rundir)
        assert 'wrinkle_idx' not in app.run['columns']
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app.detect_all_sync()
        # hand-trace one frame so a manual wrinkle value rides through
        i = app.frame_rows[1]
        app.pos = app.frame_rows.index(i)
        app._trace_staged(i, [(60.0, 40.0), (260.0, 40.0),
                              (260.0, 200.0), (60.0, 200.0)],
                          {'zoom': 1.0, 'overlays': {},
                           'elapsed_s': 1.0, 'snapped': False})
        app.cand_var.set(gui.TRACE_SLOT)
        app._choose_current()
        app.save()
        path = app.run['csv_path']
        with open(path, newline='', encoding='utf-8-sig') as f:
            r = csv.DictReader(f)
            saved_cols = r.fieldnames
            saved = list(r)
        assert 'wrinkle_idx' in saved_cols
        assert (saved_cols.index('wrinkle_idx')
                == saved_cols.index('notes') - 1)
        for row in saved:
            name = (row['frame_file'] or '').strip()
            if name:
                assert os.path.exists(os.path.join(frames, name)), name
        assert os.path.exists(os.path.join(rundir,
                                           'area_vs_voltage.png'))
        assert 'saved' in app.status.cget('text')
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def _advanced_widgets(app):
    """(entries by settings key, buttons by label) of the open dialog."""
    import sldea_edge as se
    import tkinter as tk
    from tkinter import ttk
    win = app._adv_win
    entries, buttons = {}, {}
    keys = list(se.DEFAULT_SETTINGS)

    def walk(w):
        for ch in w.winfo_children():
            if isinstance(ch, ttk.Entry):
                entries[keys[len(entries)]] = ch
            elif isinstance(ch, (ttk.Button, tk.Button)):
                buttons[str(ch.cget('text'))] = ch
            walk(ch)

    walk(win)
    return entries, buttons


def test_advanced_apply_recomputes_flags_or_invalidates_pass():
    """audit 2026-08-05: Advanced… Apply changed the breakdown
    thresholds but never recomputed flags — Save stayed armed and
    renamed frames *_BREAKDOWN on thresholds the operator had just
    changed away from. Post-processing knobs now recompute live;
    detection knobs invalidate the pass after an explicit confirm."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('advanced apply')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_adv_')
    mb = _StubMB(yes=True)
    real_mb = gui.messagebox
    gui.messagebox = mb
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        _set_ua(run, ['-16', '-10', '-90'])       # legacy rule: row 2
        app = gui.EdgeReviewApp(root, path=run)
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app.detect_all_sync()
        assert app.flags, "fixture no longer produces a breakdown flag"
        # post-processing knob: flags recompute NOW, review survives
        app._advanced()
        entries, buttons = _advanced_widgets(app)
        entries['breakdown_ua'].delete(0, 'end')
        entries['breakdown_ua'].insert(0, '400')
        n_results = len(app.results)
        buttons['Apply'].invoke()
        assert app.settings['breakdown_ua'] == 400.0
        assert app.flags == {}, "stale flags survived Apply"
        assert len(app.results) == n_results
        assert str(app.save_btn['state']) == 'normal'
        assert 'recomputed' in app.status.cget('text')
        # detection knob: explicit confirm, then the pass is cleared
        app._advanced()
        entries, buttons = _advanced_widgets(app)
        entries['blur_px'].delete(0, 'end')
        entries['blur_px'].insert(0, '9')
        buttons['Apply'].invoke()
        assert mb.asked, "no confirm before invalidating the pass"
        assert app.results == {} and app.cands_all == {}
        assert str(app.save_btn['state']) == 'disabled'
        assert 'invalidated' in app.status.cget('text')
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_retrace_after_accept_is_visibly_staged_not_silently_shown():
    """audit 2026-08-05: after committing a trace, re-tracing and
    pressing Done showed the NEW polygon as 'accepted' (radio D filled
    from it, drawn at the heavy selected weight) while Save wrote the
    OLD one. The divergence must be visible everywhere the operator
    looks."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('retrace staging')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_retrace_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None
        app.detect_all_sync()
        i = app.frame_rows[1]
        app.pos = app.frame_rows.index(i)
        meta = {'zoom': 1.0, 'overlays': {}, 'elapsed_s': 1.0,
                'snapped': False}
        poly1 = [(40.0, 40.0), (280.0, 40.0), (280.0, 200.0),
                 (40.0, 200.0)]                       # 38400 px²
        app._trace_staged(i, poly1, meta)
        app.cand_var.set(gui.TRACE_SLOT)
        app._choose_current()                          # commit P1
        committed = app.results[i]['area_px']
        poly2 = [(100.0, 80.0), (220.0, 80.0), (220.0, 160.0),
                 (100.0, 160.0)]                       # 9600 px²
        app._trace_staged(i, poly2, meta)              # stage P2 only
        # results untouched (the #172 contract)…
        assert app.results[i]['area_px'] == committed
        # …but the UI now SAYS so instead of impersonating acceptance
        assert 'staged D NOT committed' in app.info.cget('text')
        assert 'STAGED≠accepted' in \
            app.cand_radios[gui.TRACE_SLOT]['text']
        # the card renders both outlines without error
        img = app._render_card(i, app.cands_all.get(i, []),
                               app.results.get(i))
        assert img is not None
        # Enter commits the staged P2, and the warning clears
        app.cand_var.set(gui.TRACE_SLOT)
        app._choose_current()
        assert app.results[i]['area_px'] == strc_area(poly2)
        assert 'staged D NOT committed' not in app.info.cget('text')
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def strc_area(poly):
    import sldea_trace as strc
    return strc.polygon_area(poly)


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
