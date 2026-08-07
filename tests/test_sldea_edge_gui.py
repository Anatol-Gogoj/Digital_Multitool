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
        # the range is still quoted, but the number the GATE judges and
        # SLDEA_MEASUREMENT §2.1 budgets is the MEAN SE, so that is quoted
        # too and derived n-awarely (0.31/d2(3)/sqrt(3) = 0.11%). A bare
        # range is not comparable between an n=3 and an n=5 anchor
        # (2026-08-06 evening).
        assert 'range 0.31%' in txt and 'avg of 3' in txt, txt
        assert 'SE 0.11%' in txt, txt
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

    def askokcancel(self, *a, **k):
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


# The three calibration modes by NAME (2026-08-06 late). The
# dialog's A/B/C are LABELS only -- se.CAL_MODE_LABELS -- and the
# letters were renumbered once, so a test that spelled a letter
# would be asserting the presentation and not the behaviour.
VERIFY = 'verify'
CIRCLE = 'circle'
TWOPOINT = 'twopoint'


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
    prove that a previous round's diameter is nowhere in it.

    Reads every Label the dialog OWNS, mapped or not, which is what a
    "this string is nowhere" assertion wants. For "how much text is on
    screen" use _cal_visible_lines: a pack_forget()-ed label still has
    text, it just is not shown."""
    try:
        return ' | '.join(w.cget('text') for w in _widgets(win, 'label'))
    except Exception:
        return ''


def _cal_rendered(w, top):
    """True when `w` is actually rendered inside `top` — i.e. it AND every
    frame between it and the Toplevel has a geometry manager.

    The parent walk is not decoration. Since `#215`'s de-rendering pass
    (2026-08-07) the chooser's per-mode controls live in sub-frames that get
    pack_forget()-ed as a unit, and a Label inside an unpacked Frame still
    reports `winfo_manager() == 'pack'` for ITSELF — so the naive check would
    count text nobody can see, which is precisely the failure mode the line
    budget exists to catch. `winfo_ismapped()` is not usable instead: most of
    these cases never put the window on screen."""
    while w is not None and w is not top:
        try:
            if not w.winfo_manager():
                return False
            w = w.master
        except Exception:
            return False
    return True


def _cal_visible_lines(win, skip=('METHOD:', 'rounds:', 'A stroke:',
                                  'B stroke:', 'C stroke:')):
    """The text lines actually ON SCREEN, as a list.

    Only labels the geometry manager is showing — the label's own manager AND
    every frame above it (see _cal_rendered) — split on newlines, blanks
    dropped, so a hidden or emptied label costs nothing. That is the whole
    mechanism the verify mode's line budget uses. The chooser row's field
    captions are skipped: they label the radio buttons and the two option
    menus, i.e. they are part of the CONTROLS, not the prose the budget is
    about."""
    out = []
    for w in _widgets(win, 'label'):
        try:
            if not _cal_rendered(w, win):
                continue
            txt = w.cget('text')
        except Exception:
            continue
        if txt in skip:
            continue
        out.extend(ln for ln in txt.split('\n') if ln.strip())
    return out


def _cal_shown_controls(probe):
    """Which of the four per-mode control groups the dialog is RENDERING —
    as a set of names, with '(disabled)' appended to any that is on screen
    but greyed out.

    `#215`, operator 2026-08-07: the controls that do not apply to the active
    mode are DE-RENDERED rather than disabled, because *"a disabled control
    still costs a line of visual scanning and invites a click; an absent one
    does not."* So what a test has to be able to say is "absent", which is a
    claim about `winfo_manager()` and not about `state` — and the
    '(disabled)' tag is here so that quietly going back to greying them out
    fails the same assertion rather than passing it."""
    out = set()
    for name, inner in (('round_box', 'back_btn'),
                        ('rounds_box', 'n_menu'),
                        ('stroke_box', 'stroke_menu')):
        box = probe.get(name)
        if box is None or not box.winfo_manager():
            continue
        tag = name
        try:
            if str(probe[inner].cget('state')) == 'disabled':
                tag += '(disabled)'
        except Exception:
            pass
        out.add(tag)
    return out


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

    Drives the operator's actual path: accept each spawned circle as the
    fit, three times, so BOTH gates fire — the spread gate first, then
    the anchor guard — and the test answers them, which is the point:
    every gate is a decision, and the decision is recorded in the anchor.

    The spawns are SCRIPTED, not randomized (2026-08-07, de-flaked at a
    measured 6 failures in 300 harness runs, 5/200 standalone): a
    randomized 3-round set can silence EITHER gate by luck — agree to
    within the 0.4 % SE gate (range/mean under ~1.17 % = 0.4 % x d2(3)
    x sqrt(3); 4 of the 6), or average to within the guard's 1 % of the
    fixture's ~159.9 px auto fit, which the spawn range (~122-163 px
    diameter) straddles (2 of the 6). A silent gate is CORRECT dialog
    behavior — nothing to warn about — but the hard-coded answer script
    then falls one slot out of register and the run cascades through
    restarts to a wrong assert. So the cure is not a wider script but
    spawns that cannot agree and cannot land near the reference; the
    question titles are asserted exactly below, so a spawn script that
    stopped tripping a gate fails loudly instead of skipping it.
    spawn_circle's own randomization stays pinned in
    tests/test_sldea_calibration.py."""
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
    # Nine circles, one per round: half 1's set, then half 2's set and
    # its post-restart set. Every triple has range/mean >= 14 % (the SE
    # gate only goes silent under ~1.17 %) so the spread gate always
    # asks, and every mean is ~140 px against the fixture's ~160 px auto
    # fit — ~12 % out, guard tolerance 1 % — so the anchor guard always
    # asks. All nine radii differ, so equal recorded rounds would expose
    # a dialog that stopped respawning per round.
    real_spawn = _fixed_spawn(gui, [
        (160.0, 120.0, 65.0), (160.0, 120.0, 70.0), (160.0, 120.0, 75.0),
        (160.0, 120.0, 64.0), (160.0, 120.0, 71.0), (160.0, 120.0, 76.0),
        (160.0, 120.0, 63.0), (160.0, 120.0, 69.0), (160.0, 120.0, 77.0)])

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
        app._calibrate_scale(mode=CIRCLE)
        # BOTH gates fired, in order — not merely two questions. This is
        # the assertion that keeps the scripted spawns honest: circles
        # that stopped tripping a gate turn up here as a missing title,
        # not as a silently skipped gate.
        assert [t for t, _kw in asked] == \
            ['Rounds disagree', 'Anchor sanity check'], asked
        assert taken[:2] == ['Continue →', 'Continue →'], taken
        assert '✔ Finish calibration' in taken[2]
        ref = app.manual_ref
        assert ref is not None, "three rounds produced no anchor"
        assert ref['n_rounds'] == gui.CAL_ROUNDS == 3
        assert len(ref['rounds_px']) == 3
        # the dialog takes a FRESH spawn each round — the scripted
        # circles are all different, so three equal fits would mean the
        # per-round respawn (the decorrelation the dialog promises)
        # stopped happening and the spread would be a fiction
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
        app._calibrate_scale(mode=CIRCLE)
        assert app.manual_ref is not None
        assert app.manual_ref['n_rounds'] == 3, app.manual_ref
        # 3 rounds, restart, 3 rounds again = 6 presses, and 4 questions
        # — both gates, both cycles, in order. The desync this test used
        # to be flaky through showed up as exactly this list losing a
        # 'Rounds disagree' or an 'Anchor sanity check'.
        assert len(taken) == 6, taken
        assert [t for t, _kw in asked] == \
            ['Rounds disagree', 'Anchor sanity check',
             'Rounds disagree', 'Anchor sanity check'], asked
        # EVERY question carried an explicit default (finding 1)
        assert all(kw.get('default') for _t, kw in asked), asked
        # the guard's modal had to print the mean and the reference for
        # its warning to be actionable, so the rounds fitted AFTER it
        # were not blind — and the record says so (review 2026-08-06)
        assert 'refit after a disclosed cross-check' \
            in app.manual_ref['guard'], app.manual_ref['guard']
        app.manual_ref['guard'].encode('ascii')
    finally:
        gui.messagebox, gui.spawn_circle = real_mb, real_spawn
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
        app._calibrate_scale(mode=CIRCLE)
        assert app.manual_ref is None, ("an anchor nobody read was "
                                        "accepted: " + str(app.manual_ref))
        assert spy.asked and spy.asked[0][0] == 'Rounds disagree'
        assert spy.defaults()[0] == 'cancel', spy.asked[0]

        # (b) now make the rounds AGREE so the spread gate passes and the
        # ANCHOR GUARD is the question: a 130 px circle against the
        # fixture's ~160 px disc is a P3_2-shaped miss, 18% out
        spy.asked.clear()
        gui.spawn_circle = lambda *_a, **_k: (160.0, 120.0, 65.0)
        app._calibrate_scale(mode=CIRCLE)
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
        app._calibrate_scale(mode=CIRCLE)
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
        app._calibrate_scale(mode=CIRCLE)
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
        app._calibrate_scale(mode=CIRCLE)
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
            # WHICH ROUND, and nothing about the ones before it. The header
            # used to carry a sentence explaining the blinding as well; that
            # went in the 2026-08-07 trim (`#215`) and the property it
            # described is what the assertions above and below measure.
            assert 'Round' in s, s
            assert 'HIDDEN until the last fit' not in s, s
        # each round DOES show the circle currently under the cursor —
        # that is the fit being made, not a target to match
        assert 'circle: 130.0 px across' in snaps[0], snaps[0]
        assert 'circle: 140.0 px across' in snaps[1], snaps[1]
        # the spread gate is one of the questions a REFIT can answer, so
        # it too quotes only the percentage — a refit fitted against a
        # disclosed target would be no more independent than round 2 was.
        # It quotes SIGMA and the AREA error since the 2026-08-07 trim; the
        # raw range came off the prompt and is still in the log's `range=`
        # and setup.txt's `spread_pct` (and on the reveal line below).
        assert spy.asked[0][0] == 'Rounds disagree', spy.asked
        prompt = spy.msgs[0]
        assert '8.44 %' in prompt and '% of diameter' in prompt, prompt
        assert '9.74 %' in prompt and '% in area' in prompt, prompt
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


def _cal_onscreen(root, win):
    """Put the calibration dialog on screen so synthetic MOUSE events
    reach it. A <Button-1> generated on an unviewable widget is silently
    dropped (verified: the clicks simply never arrived), the same trap
    test_return_key_cannot_finish_a_calibration documents for keys. Every
    mode-B case below therefore self-checks that its clicks LANDED, so it
    fails loudly rather than passing vacuously."""
    root.deiconify()
    root.update()
    win.deiconify()
    win.update()


def _finish_if_last(win):
    """Press the primary button ONLY when it is the Finish button.

    Since AUTO-ADVANCE (operator 2026-08-06 late) the two-point mode banks a
    round on its second click and moves to the next one by itself, so there
    is no Continue to press mid-set — and pressing one would only produce
    the "place BOTH edge points" refusal. The LAST round still needs the
    button, because what follows it is the acceptance gate, the anchor guard
    and an anchor.

    Every mode-B driver below goes through here rather than pressing
    unconditionally, which also makes auto-advance load-bearing in these
    cases: if the second click stopped banking the round, the round count
    would never reach the last one and the loop would run out."""
    btn = _cal_step_button(win)
    if 'Finish' in btn.cget('text'):
        btn.invoke()
        return True
    return False


def _click_at_original(app, orig_xy, img_w=320, img_h=240):
    """Click the point that currently DISPLAYS the original-image
    coordinate `orig_xy`, as a real <Button-1> on the dialog's canvas.

    The test does the FORWARD mapping (original -> rotated) and the dialog
    does the inverse, so what is under test is the dialog's own
    click->original path: its rotation angle, its rotated canvas, its view
    transform and its press handler. Uses app._cal_probe — the dialog's own
    objects — so nothing here is a second copy of that arithmetic.
    Returns the original coordinate the dialog is expected to store."""
    import math as _math
    import sldea_edge_gui as gui
    p = app._cal_probe
    assert p, "the calibration dialog published no probe"
    vt, cv = p['vt'], p['canvas']
    _im, rw, rh = p['disp']()
    deg = p['st']['rot']
    phi = _math.radians(-float(deg))
    c, s = _math.cos(phi), _math.sin(phi)
    ox = float(orig_xy[0]) - img_w / 2.0
    oy = float(orig_xy[1]) - img_h / 2.0
    rx = c * ox - s * oy + rw / 2.0        # inverse of unrotate_point
    ry = s * ox + c * oy + rh / 2.0
    back = gui.unrotate_point(rx, ry, rw, rh, img_w, img_h, deg)
    assert abs(back[0] - orig_xy[0]) < 1e-6, (back, orig_xy)
    assert abs(back[1] - orig_xy[1]) < 1e-6, (back, orig_xy)
    before = len(p['st']['pts'])
    banked_before = len(p['st']['diams'])
    vx, vy = vt.to_view(rx, ry)
    cv.event_generate('<Button-1>', x=int(round(vx)), y=int(round(vy)),
                      when='now')
    cv.update()
    # SELF-CHECK: a <Button-1> on an unviewable widget is silently dropped,
    # so without this the whole case would pass while testing nothing.
    #
    # THREE possible outcomes since AUTO-ADVANCE (operator 2026-08-06 late):
    # a first point lands (0 -> 1); a SECOND point lands and BANKS the round,
    # which clears the pair for the next one (1 -> 0 with diams up by one);
    # or, on the last round, the second point stays put (1 -> 2) because
    # finishing still needs the button. A third click restarts the pair
    # (2 -> 1).
    now = len(p['st']['pts'])
    banked = len(p['st']['diams'])
    if before == 1 and banked == banked_before + 1:
        assert now == 0, (
            f"a round was banked but its clicks were not cleared "
            f"(points {before} -> {now})")
    else:
        want = before + 1 if before < 2 else 1
        assert now == want and banked == banked_before, (
            f"the click never reached the dialog (points {before} -> {now}, "
            f"expected {want}; banked {banked_before} -> {banked}) — "
            f"nothing here was tested; is the window on screen?")
    return orig_xy


def test_mode_b_measures_in_original_coordinates_under_rotation():
    """MODE B end to end THROUGH THE REAL DIALOG (display required; this
    case skips headlessly, so a green suite is not evidence the window
    opens — the geometry is pinned separately in
    tests/test_sldea_calibration.py).

    The display is rotated by a fresh random angle every round and the two
    clicks are pushed back through the inverse rotation, so clicking the
    SAME two physical points must produce the SAME diameter whatever the
    rotation happened to be. The fixture's resting disc is r=80 at
    (160, 120), so the poles of a diameter are 160 px apart in ORIGINAL px
    and every round must land on 160."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_cal_b_')
    real_mb = gui.messagebox
    seen = {'rots': [], 'heads': []}
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        # 160 px against the fixture's ~160 px automatic fit still misses
        # the mask-area guard slightly, so answer every question with the
        # override — the gates are tested elsewhere; this is the geometry
        spy = _ModalSpy(real_mb, app, answers=[True] * 8)
        gui.messagebox = spy

        def advance(win):
            _cal_onscreen(root, win)
            for _ in range(12):
                if not win.winfo_exists():
                    return
                head = _cal_display(win)
                seen['heads'].append(head)
                # THE ANGLE COMES FROM THE DIALOG'S OWN STATE, not off the
                # screen (`#215`, operator 2026-08-07: the header stopped
                # printing "view rotated N deg" because the picture is
                # visibly rotated). Reading st['rot'] is the stronger check
                # anyway -- it is the angle actually MEASURED at, where the
                # header was only the angle displayed.
                seen['rots'].append(float(app._cal_probe['st']['rot']))
                _click_at_original(app, (80.0, 120.0))
                _click_at_original(app, (240.0, 120.0))
                _finish_if_last(win)

        app.root.wait_window = advance
        app._calibrate_scale(mode=TWOPOINT)
        ref = app.manual_ref
        assert ref is not None, "mode B produced no anchor"
        assert ref['cal_mode'] == TWOPOINT
        assert ref['n_rounds'] == gui.CAL_ROUNDS_TWOPOINT == 5
        assert len(ref['rounds_px']) == 5
        # THE POINT: same two physical points, five display rotations, the
        # same measured diameter. The residual is view-pixel quantization
        # of the synthetic click (the test rounds to integer view px at
        # ~2.6x zoom), not method error.
        for v in ref['rounds_px']:
            assert abs(v - 160.0) < 2.0, (v, ref['rounds_px'])
        assert abs(ref['diam_px'] - 160.0) < 1.5, ref['diam_px']
        # sigma/SE travel with it, n-awarely
        assert ref['sigma_pct'] is not None and ref['se_pct'] is not None
        s = gui.se.calibration_stats(ref['rounds_px'])
        assert abs(ref['se_pct'] - s['se_pct']) < 1e-9
        assert abs(s['sigma_pct'] - s['spread_pct'] / 2.326) < 1e-9
        # the rotations really happened, one per sector of the FULL circle
        # — that is the mechanism, so its absence would be the bug
        assert len(seen['rots']) == 5, seen['rots']
        assert len(set(seen['rots'])) == 5, seen['rots']
        assert sorted(int(a // 72.0) for a in seen['rots']) == [0, 1, 2, 3, 4]
        assert max(seen['rots']) - min(seen['rots']) > 180.0, seen['rots']
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_mode_b_is_blind_mid_round_and_shows_no_length_at_all():
    """The blind-rounds rule of the review round, in mode B — and stricter:
    mode B never shows the chord's LENGTH either, because two clicks on an
    edge need no numeric feedback to place. So nothing on screen while
    rounds remain is a number a later round could be steered onto.

    Everything is revealed once the fitting is over, on the status line,
    which is the surface that outlives the dialog."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_cal_bblind_')
    real_mb = gui.messagebox
    snaps, diams = [], []
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        # the chords below differ wildly on purpose, so the SE gate trips:
        # answer it with "accept as measured" (No), then override the
        # anchor guard (Yes). Answering Yes to the gate would REFIT, which
        # is the remedy an SE gate can offer and a range gate could not.
        spy = _ModalSpy(real_mb, app, answers=[False, True])
        gui.messagebox = spy

        def advance(win):
            _cal_onscreen(root, win)
            for k in range(12):
                if not win.winfo_exists():
                    return
                # deliberately DIFFERENT chords per round (160, 150, 140,
                # 130, 120 px in original space) so any leak of a previous
                # round's value would be a distinguishable string
                half = 80.0 - 5.0 * k
                _click_at_original(app, (160.0 - half, 120.0))
                snaps.append(_cal_display(win))    # mid-round: one point in
                _click_at_original(app, (160.0 + half, 120.0))
                diams.append(2.0 * half)
                _finish_if_last(win)

        app.root.wait_window = advance
        app._calibrate_scale(mode=TWOPOINT)
        assert len(snaps) == 5, len(snaps)
        ref = app.manual_ref
        assert ref is not None and ref['n_rounds'] == 5
        for got, want in zip(ref['rounds_px'], diams):
            assert abs(got - want) < 2.0, (got, want, ref['rounds_px'])
        for i, s in enumerate(snaps):
            # no previous round's diameter, no running average, and no
            # length for the CURRENT pair either
            for v in diams[:i + 1]:
                assert f"{v:.1f}" not in s, (i, v, s)
                assert f"{v:.0f} px" not in s, (i, v, s)
            assert 'accepted so far' not in s, s
            assert 'mean' not in s.lower(), s
            # the sentence explaining the blinding came off the header in the
            # 2026-08-07 trim (`#215`); the blinding is what the loop above
            # measures, round by round, which is the stronger claim anyway
            assert 'HIDDEN until the last fit' not in s, s
            assert 'px across' not in s, s          # the circle's readout
            # what it DOES show: progress, the rotation, and the count
            # the two-point mode's LABEL is C since the 2026-08-06
            # swap (A = verify, B = circle, C = twopoint)
            assert re.search(r'Method C · Round \d of 5', s), s
            assert re.search(r'\d of 2 points', s), s            # the header
            assert 'of 2 edge points placed' in s, s             # the readout
        # THE REVEAL, after the fitting, with sigma leading
        txt = app.status.cget('text')
        assert 'mean of 5:' in txt, txt
        assert 'σ ' in txt and '%/fit' in txt, txt
        assert 'SE ' in txt and '% area' in txt, txt
        assert f"gate {gui.se.CAL_SE_PCT:g}%" in txt, txt
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_every_round_set_is_logged_accepted_or_declined():
    """The capture that was missing last time: the six mode-A spreads that
    motivated mode B exist only as numbers typed into a chat, because every
    one of those calibrations was DECLINED at a gate and setup.txt is only
    written at Save.

    Drives one DECLINED round-set and one ACCEPTED one and requires both in
    the run folder's log — with the method, n, the individual diameters,
    the range, sigma, the mean SE, the rotation angles and the automatic
    disc fit."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_cal_log_')
    real_mb, real_spawn = gui.messagebox, gui.spawn_circle
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        log = os.path.join(run, gui.se.CAL_LOG_NAME)
        assert not os.path.exists(log)

        def advance(win):
            for _ in range(12):
                if not win.winfo_exists():
                    return
                _cal_step_button(win).invoke()

        app.root.wait_window = advance
        # (a) mode A, three scattered fits, and the operator CANCELS at the
        # gate — the exact case that lost the six measurements
        _fixed_spawn(gui, [(160.0, 120.0, 65.0), (160.0, 120.0, 70.0),
                           (160.0, 120.0, 75.0)])
        spy = _ModalSpy(real_mb, app, answers=[None])
        gui.messagebox = spy
        app._calibrate_scale(mode=CIRCLE)
        assert app.manual_ref is None, "cancel accepted an anchor"
        assert os.path.exists(log), "a declined round-set was not logged"
        lines = _log_lines(log)
        assert len(lines) == 1, lines
        one = lines[0]
        assert 'mode=circle n=3' in one, one
        assert 'outcome=declined-cancel' in one, one
        assert 'verdict=OVER-GATE' in one, one
        assert 'diams=130.00,140.00,150.00px' in one, one
        assert 'range=14.29%' in one and 'sigma=8.44%' in one, one
        assert 'se=4.87%' in one and 'area_se=9.74%' in one, one
        assert 'gate=0.40%' in one, one
        assert 'stroke=3 px solid' in one and 'rot=-deg' in one, one
        assert re.search(r'auto=\d+\.\d+px\([-+]\d+\.\d+%\)', one), one
        assert one.startswith('SLDEA-CAL 20'), one          # timestamp

        # (b) mode B, accepted with an override: a SECOND line, appended,
        # carrying the rotation angles this time
        gui.spawn_circle = real_spawn
        spy = _ModalSpy(real_mb, app, answers=[True] * 8)
        gui.messagebox = spy

        def advance_b(win):
            _cal_onscreen(root, win)
            for _ in range(12):
                if not win.winfo_exists():
                    return
                _click_at_original(app, (80.0, 120.0))
                _click_at_original(app, (240.0, 120.0))
                _finish_if_last(win)

        app.root.wait_window = advance_b
        app._calibrate_scale(mode=TWOPOINT)
        assert app.manual_ref is not None
        lines = _log_lines(log)
        assert len(lines) == 2, lines
        two = lines[1]
        assert 'mode=twopoint n=5' in two, two
        assert two.startswith('SLDEA-CAL 20')
        assert 'outcome=accepted' in two, two
        assert 'stroke=-' in two, two
        rots = re.search(r'rot=([0-9.,]+)deg', two)
        assert rots, two
        angs = [float(v) for v in rots.group(1).split(',')]
        assert len(angs) == 5 and len(set(angs)) == 5, angs
        assert sorted(int(a // 72.0) for a in angs) == [0, 1, 2, 3, 4], angs
        # the whole file is one line per round-set plus a header block,
        # ASCII, so it can be grepped and pasted into an issue
        with open(log, encoding='utf-8') as f:
            body = f.read()
        body.encode('ascii')
        assert body.count('# SLDEA Edge Review scale calibrations') == 1
    finally:
        gui.messagebox, gui.spawn_circle = real_mb, real_spawn
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def _log_lines(path):
    with open(path, encoding='utf-8') as f:
        return [ln.strip() for ln in f if ln.startswith('SLDEA-CAL')]


def test_mode_b_keeps_every_safety_fix_of_the_review_round():
    """The review round's four fixes are properties of the GATES, not of
    the circle, so mode B has to inherit all of them. Checked here:

    * FINDING 1a — every yes/no question carries an explicit declining
      default=, and answering everything with its own default must NOT
      accept an anchor (tkinter's askyesno defaults to YES);
    * FINDING 1b — <Return> may advance an intermediate round and can
      never reach finish(), so it can never answer a gate;
    * FINDING 3 — an unavailable cross-check is its own modal, and the
      anchor records the gap in the same voice as a trip."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_cal_bsafe_')
    real_mb = gui.messagebox
    seen = {}
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        spy = _ModalSpy(real_mb, app)          # no answers: all defaults
        gui.messagebox = spy

        # (a) five deliberately scattered chords, every question answered
        # with its OWN default -> no anchor
        def advance(win):
            _cal_onscreen(root, win)
            for k in range(14):
                if not win.winfo_exists():
                    return
                half = 80.0 - 6.0 * k
                _click_at_original(app, (160.0 - half, 120.0))
                _click_at_original(app, (160.0 + half, 120.0))
                _finish_if_last(win)

        app.root.wait_window = advance
        app._calibrate_scale(mode=TWOPOINT)
        assert app.manual_ref is None, ("an anchor nobody read was "
                                        "accepted: " + str(app.manual_ref))
        assert spy.asked and spy.asked[0][0] == 'Rounds disagree', spy.asked
        assert spy.defaults()[0] == 'cancel', spy.asked[0]
        assert all(kw.get('default') for _t, kw in spy.asked), spy.asked
        # the gate quotes PERCENTAGES only — a refit is one of its answers,
        # so no diameter and no average may appear in it
        prompt = spy.msgs[0]
        # AT A GLANCE (`#215`, operator 2026-08-07): the round σ, what it
        # implies as AREA error, the budget, and the three-way choice. Twelve
        # lines of prose became three, so what is pinned is those four things
        # and nothing else.
        assert 'σ = ' in prompt and '% of diameter' in prompt, prompt
        assert '% in area' in prompt and 'budget ±' in prompt, prompt
        assert 'Yes = refit' in prompt and 'No = accept as measured' in prompt
        assert 'Cancel' in prompt, prompt
        # AND IT STAYS SHORT. This prompt was 7 non-blank lines / 862 chars
        # and the operator met it on real data; three lines is what was asked
        # for, so three is what is pinned. The per-line cap is what keeps the
        # choice list on ONE display line -- the native message box wraps at
        # about 70 characters, and a list that breaks mid-choice is not
        # readable at a glance, which was the whole request.
        body = [ln for ln in prompt.split('\n') if ln.strip()]
        assert len(body) <= 3, (f"{len(body)} lines in the disagreement "
                                f"prompt:\n" + prompt)
        assert len(prompt) <= 300, (len(prompt), prompt)
        for ln in body:
            assert len(ln) <= 130, (len(ln), ln)
        # ... and the DERIVATION is gone from the screen, which is where it
        # was reference material. It is in SLDEA_MEASUREMENT §2.1a, and every
        # number it produced is still in the record: `se=` and `range=` in
        # scale_calibration_log.txt, `se_pct`/`spread_pct` in setup.txt, and
        # d₂ fixed by the `n=` both of them carry.
        for gone in ('standard error', 'd₂(5) = 2.326', 'range/d₂',
                     'Raw range', 'SLDEA_MEASUREMENT',
                     'stay hidden until you accept'):
            assert gone not in prompt, (gone, prompt)
        for v in (160.0, 148.0, 136.0, 124.0, 112.0):
            assert f"{v:.1f}" not in prompt, (v, prompt)
        # ... and it still names the round count that WOULD clear it, which is
        # the remedy only an SE gate can offer — and the one thing on this
        # prompt beyond the operator's three, kept because it is a NUMBER and
        # it decides WHICH of the three answers is right
        assert re.search(r'\d+ rounds would meet the gate|would take '
                         r'\d+ rounds', prompt), prompt

        # (b) <Return> may advance a round; it must never finish
        spy.asked.clear()
        app.manual_ref = None

        def hammer(win, _n=16):
            """Enter, hammered, on the round where it could do damage.

            REWRITTEN FOR AUTO-ADVANCE (operator 2026-08-06 late). Enter used
            to be what advanced an intermediate round, so seeing rounds
            2..5 go by proved the key had been delivered. The CLICKS advance
            the rounds now, so that evidence is gone and the old self-check
            would pass without a single key press arriving. What proves
            delivery instead is the refusal MESSAGE, which only
            continue_key can write.

            So: click through to the LAST round, where Enter is one press
            away from an anchor and the gates behind it, and hammer there."""
            _cal_onscreen(root, win)
            win.focus_force()
            win.update()
            rounds = set()
            st = app._cal_probe['st']
            for _ in range(_n):
                if not win.winfo_exists():
                    break
                m = re.search(r'Round (\d+) of', _cal_display(win))
                if m:
                    rounds.add(int(m.group(1)))
                if len(st['pts']) < 2:
                    _click_at_original(app, (80.0, 120.0))
                    _click_at_original(app, (240.0, 120.0))
                win.event_generate('<Return>', when='now')
                win.update()
            seen['rounds'] = rounds
            seen['alive'] = win.winfo_exists()
            seen['btn'] = (_cal_step_button(win).cget('text')
                           if seen['alive'] else '')
            seen['text'] = _cal_display(win) if seen['alive'] else ''

        app.root.wait_window = hammer
        app._calibrate_scale(mode=TWOPOINT)
        assert seen.get('alive'), "Enter closed the calibration dialog"
        # the clicks walked the set to its last round and stopped there --
        # auto-advance never carries a set past the round that needs the
        # button
        assert seen['rounds'] == {1, 2, 3, 4, 5}, seen['rounds']
        assert 'Finish' in seen['btn'], seen['btn']
        # SELF-CHECK: the refusal message is the only thing continue_key
        # writes, so it is what proves a key press actually arrived. Without
        # it this case would pass while testing nothing (a synthetic key on
        # an unviewable widget is silently dropped).
        assert 'Enter cannot accept an anchor' in seen['text'], (
            "no <Return> reached the dialog, so nothing here was tested: "
            + seen['text'][:300])
        assert app.manual_ref is None, ("Enter accepted an anchor: "
                                        + str(app.manual_ref))
        assert not spy.asked, ("Enter reached a modal warning: "
                               + str(spy.asked))

        # (c) FINDING 3 in mode B: no automatic disc fit -> its own modal,
        # declining by default, and the gap on the record when overridden
        spy.asked.clear()
        app.manual_ref = None
        app._auto_disc = lambda: None
        spy.answers[:] = [True]                # override the missing check

        def advance_ok(win):
            _cal_onscreen(root, win)
            for _ in range(12):
                if not win.winfo_exists():
                    return
                _click_at_original(app, (80.0, 120.0))
                _click_at_original(app, (240.0, 120.0))
                _finish_if_last(win)

        app.root.wait_window = advance_ok
        app._calibrate_scale(mode=TWOPOINT)
        titles = [t for t, _kw in spy.asked]
        assert titles == ['Anchor NOT cross-checked'], titles
        assert spy.defaults() == ['no'], spy.asked
        ref = app.manual_ref
        assert ref is not None and ref['cal_mode'] == TWOPOINT
        assert ref['guard'].startswith('NOT CROSS-CHECKED'), ref['guard']
        ref['guard'].encode('ascii')
        assert 'NOT cross-checked' in app.status.cget('text')
        # and the log records the gap too, with no automatic reference
        line = _log_lines(os.path.join(run, gui.se.CAL_LOG_NAME))[-1]
        assert 'mode=twopoint n=5' in line and 'auto=none' in line, line
        assert 'outcome=accepted-override' in line, line
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_mode_chooser_restarts_the_set_and_carries_the_modes_default_n():
    """The chooser is per calibration so both methods can be driven on the
    SAME disc minutes apart. Switching mode must RESTART: half a circle set
    plus half a two-point set is not a measurement of either method. And it
    adopts that mode's own default round count (3 for A, 5 for B), so the
    operator who just wants "the other method" gets the count it was
    designed around."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_cal_mode_')
    real_mb, real_spawn = gui.messagebox, gui.spawn_circle
    saw = {}
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        gui.messagebox = _ModalSpy(real_mb, app, answers=[None])
        gui.spawn_circle = lambda *_a, **_k: (160.0, 120.0, 80.0)

        def poke(win):
            p = app._cal_probe
            # opens on the DEFAULT mode with that mode's round count
            saw['open'] = (p['mode_var'].get(), p['n_var'].get(),
                           p['st']['mode'], p['st']['n'])
            # one round in ...
            _cal_step_button(win).invoke()
            saw['mid'] = (p['st']['round'], len(p['st']['diams']))
            # ... then switch to B: restarted, 5 rounds, rotated display
            p['mode_var'].set(TWOPOINT)
            p['mode_var'].get()
            win.tk.call('after', 'idle', '')          # let Tk settle
            app._cal_probe['st']  # (the switch runs on the radio command)
            saw['switched_before_cmd'] = p['st']['mode']
            # the radio's command is what the operator's click invokes
            for rb in _widgets_of(win, tk.Radiobutton):
                if rb.cget('value') == TWOPOINT:
                    rb.invoke()
            saw['after'] = (p['st']['mode'], p['st']['n'],
                            p['n_var'].get(), p['st']['round'],
                            len(p['st']['diams']),
                            len(p['st']['pending_rots']),
                            p['st']['rimg'] is not None)
            saw['header'] = _cal_display(win)
            # a round count with no d2 factor is not offerable at all
            saw['n_choices'] = _option_values(win, p['n_var'])
            win.destroy()

        app.root.wait_window = poke
        app._calibrate_scale(mode=CIRCLE)
        assert saw['open'] == (gui.se.CAL_DEFAULT_MODE, '3', CIRCLE, 3), saw
        assert saw['mid'] == (2, 1), saw
        mode, n, nv, rnd_i, ndiams, npend, rotated = saw['after']
        assert mode == TWOPOINT and n == 5 and nv == '5', saw
        assert rnd_i == 1 and ndiams == 0, ("switching mode kept fits from "
                                            "the other method: " + str(saw))
        assert npend == 4, saw            # 5 angles, round 1's already used
        assert rotated, "the two-point mode did not rotate the display"
        # the LETTER on screen is the two-point mode's NEW label, C
        assert 'Method C · Round 1 of 5' in saw['header'], saw['header']
        # ... and the ANGLE is no longer printed anywhere on the screen
        # (`#215`, operator 2026-08-07): the rotation still happens (asserted
        # on st['rimg'] and st['rot'] above, which is the stronger claim), but
        # the picture is visibly rotated so the header was quoting a fact the
        # operator can see. The number stays in the record -- `rot=` on the log
        # line, which is what the A/B comparison reads.
        assert 'view rotated' not in saw['header'], saw['header']
        for v in saw['n_choices']:
            assert gui.se.d2(int(v)) is not None, v
        assert set(saw['n_choices']) == {str(k) for k
                                         in gui.se.D2_RANGE_FACTORS}
    finally:
        gui.messagebox, gui.spawn_circle = real_mb, real_spawn
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def _widgets_of(w, cls):
    out = []
    for c in w.winfo_children():
        if isinstance(c, cls):
            out.append(c)
        out.extend(_widgets_of(c, cls))
    return out


def _option_values(win, var):
    """The values an OptionMenu bound to `var` offers, read off its menu."""
    import tkinter as tk
    for mb in _widgets_of(win, tk.Menubutton):
        try:
            menu = win.nametowidget(mb.cget('menu'))
            n = menu.index('end')
            vals = [menu.entrycget(i, 'label') for i in range(n + 1)]
        except (tk.TclError, KeyError, TypeError):
            continue
        if var.get() in vals:
            return vals
    return []


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


class _StubTracer:
    """Stands in for TraceWindow so the tracer-OPEN path (#162's gate) is
    testable without a mapped Toplevel: records the args it was built
    with, and can play Done back through the real _trace_staged."""
    opened = []

    def __init__(self, app, row_index, img_path, **kw):
        self.app, self.row_index, self.kw = app, row_index, kw
        _StubTracer.opened.append(self)

    def done(self, poly, **extra):
        meta = {'zoom': 1.0, 'overlays': {}, 'elapsed_s': 2.0,
                'snapped': False,
                'unpaired_ack': self.kw.get('unpaired_ack')}
        meta.update(extra)
        self.app._trace_staged(self.row_index, poly, meta)


def test_trace_gate_is_shown_once_and_can_be_declined():
    """The operator-facing half of #162's pairing gate, through the REAL
    _trace: an unpairable frame asks BEFORE the tracing effort, Cancel
    writes nothing at all, and OK carries the acknowledgement into the
    tracer so Done does not nag a second time about the same gap.

    Driving _trace_staged directly (as the first version of this test
    did) proves none of that -- with no 'unpaired_ack' key it exercises a
    path no operator takes, and both the gate and the double-nag
    suppression could be deleted with the suite still green (review
    2026-08-06)."""
    import sldea_edge_gui as gui
    import sldea_trace as strc
    root = _tk_root_or_skip('trace pairing gate')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_gate_')
    mb = _StubMB(yes=False)                      # operator clicks Cancel
    real_mb, real_tw = gui.messagebox, gui.TraceWindow
    gui.messagebox, gui.TraceWindow = mb, _StubTracer
    _StubTracer.opened = []
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None, "synthetic run failed to load"
        # no baseline on disk -> the one gap no on-demand detect can close
        open(os.path.join(run, 'frames',
                          'SLDEA_s00_00.00kV_baseline.png'), 'wb').close()
        i = app.frame_rows[1]
        app.pos = app.frame_rows.index(i)
        app._trace()
        assert len(mb.asked) == 1, mb.asked
        gate = ' '.join(str(x) for x in mb.asked[0])
        assert 'ground truth' in gate and 'BASELINE' in gate, gate
        assert not _StubTracer.opened, "Cancel still opened the tracer"
        assert not app.traces and not strc.load_labels(run)
        # ...and OK opens it WITH the acknowledgement, which Done honours
        mb._yes = True
        app._trace()
        assert len(mb.asked) == 2
        assert len(_StubTracer.opened) == 1
        tw = _StubTracer.opened[0]
        assert tw.kw['unpaired_ack'] == strc.UNPAIRED_NO_BASELINE
        tw.done([(80.0, 60.0), (240.0, 60.0), (240.0, 180.0),
                 (80.0, 180.0)])
        assert app.traces[i]['method'] == 'manual-trace'
        rec = strc.load_labels(run)[-1]
        assert rec['unpaired'] == strc.UNPAIRED_NO_BASELINE
        assert not mb.warnings, "nagged twice about one acknowledged gap"
        assert 'UNPAIRED' in app.status.cget('text')
        # a label that reaches the sidecar WITHOUT the operator having
        # seen the gate (a caller that bypassed _trace) still says so
        j = app.frame_rows[2]
        app.pos = app.frame_rows.index(j)
        app._trace_staged(j, [(80.0, 60.0), (240.0, 60.0), (240.0, 180.0),
                              (80.0, 180.0)],
                          {'zoom': 1.0, 'overlays': {}, 'snapped': False})
        assert len(mb.warnings) == 1, mb.warnings
    finally:
        gui.messagebox, gui.TraceWindow = real_mb, real_tw
        _StubTracer.opened = []
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_trace_of_an_undecodable_frame_says_so_instead_of_crashing():
    """A frame that EXISTS but does not decode (truncated, 0-byte) passed
    the os.path.exists check and then raised PIL.UnidentifiedImageError
    out of TraceWindow.__init__ -- an unhandled traceback into a console
    nobody is watching, where the operator expected a tracer. The #162
    gate made it worse by first promising that 'tracing anyway still
    RECOVERS the measurement', which this branch cannot deliver (review
    2026-08-06). Now the gate says the tracer may not open at all, and
    when it does not, the operator is told."""
    import sldea_edge_gui as gui
    import sldea_trace as strc
    root = _tk_root_or_skip('undecodable frame trace')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_trunc_')
    mb = _StubMB(yes=True)
    real_mb = gui.messagebox
    gui.messagebox = mb
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        i = app.frame_rows[1]
        with open(os.path.join(run, 'frames',
                              app.run['rows'][i]['frame_file']), 'r+b') as f:
            f.truncate(40)                     # exists, does not decode
        app.pos = app.frame_rows.index(i)
        assert app._machine_pairing(i)[1] == strc.UNPAIRED_FRAME_UNREADABLE
        app._trace()                           # must not raise
        gate = ' '.join(str(x) for x in mb.asked[-1])
        assert 'may not be able to open it' in gate, gate
        assert 'still RECOVERS' not in gate, "promised what it cannot do"
        assert mb.errors, "the tracer failed to open and said nothing"
        assert not app.traces and not strc.load_labels(run)
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_on_demand_pairing_does_not_fake_a_detection_pass():
    """#162's on-demand detect must not make a never-detected session
    LOOK detected. It used to write into cands_all, which flipped
    Advanced -> Apply's `has_pass`: changing a detect key then offered to
    clear a 'pass' of '0 decided frame(s)' and wiped self.traces with it,
    so every staged hand trace had to be re-clicked -- the exact harm
    #162 exists to end, and the new no-candidate dialog steers the
    operator into it ('lower min_diff in Advanced and re-detect').
    Reproduced on this fixture 2026-08-06: traces [1, 2] -> []."""
    import sldea_edge_gui as gui
    import sldea_trace as strc
    root = _tk_root_or_skip('on-demand pairing vs Apply')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_ondemand_')
    mb = _StubMB(yes=True)
    real_mb = gui.messagebox
    gui.messagebox = mb
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None and not app.cands_all
        poly = [(80.0, 60.0), (240.0, 60.0), (240.0, 180.0), (80.0, 180.0)]
        meta = {'zoom': 1.0, 'overlays': {}, 'snapped': False}
        for k in (1, 2):
            i = app.frame_rows[k]
            app.pos = app.frame_rows.index(i)
            app._trace_staged(i, poly, dict(meta))
        staged = sorted(app.traces)
        assert len(staged) == 2
        assert all(strc.is_paired(r) for r in strc.load_labels(run))
        # the pairing exists, and it lives OUTSIDE the review pass
        assert not app.cands_all, "on-demand candidates leaked into the pass"
        assert app.pair_cands and not app.results
        # ...so a detect-key change is not a 'pass invalidation' at all
        app._advanced()
        entries, buttons = _advanced_widgets(app)
        entries['min_diff'].delete(0, 'end')
        entries['min_diff'].insert(0, '4')
        buttons['Apply'].invoke()
        assert app.settings['min_diff'] == 4
        assert not mb.asked, mb.asked
        assert sorted(app.traces) == staged, "staged traces were wiped"
        # the pairings themselves ARE settings-dependent, so they drop:
        # the next trace must not pair with a candidate these settings do
        # not reproduce
        assert not app.pair_cands, "stale-settings pairings survived"
        # a REAL pass still clears both, and still says what it clears
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app.detect_all_sync()
        assert app.cands_all and not app.pair_cands
        i = app.frame_rows[1]
        app.pos = app.frame_rows.index(i)
        app._trace_staged(i, poly, dict(meta))
        assert app.traces
        app._advanced()
        entries, buttons = _advanced_widgets(app)
        entries['min_diff'].delete(0, 'end')
        entries['min_diff'].insert(0, '5')
        buttons['Apply'].invoke()
        assert mb.asked, "a real pass must still confirm before clearing"
        said = ' '.join(str(x) for x in mb.asked[-1])
        assert 'STAGED manual trace' in said, said
        assert not app.traces and not app.cands_all
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_trace_without_a_detection_pass_is_still_paired():
    """The 2026-08-06 repro (#162): open a run WITHOUT --auto, trace a
    frame, and the label used to go out with machine:null — half of
    #162's stated purpose (ground truth) silently lost, four real labels
    in the 2026-07/08 batch control round.

    The tracer now detects THAT ONE frame on demand, so the pairing
    exists and nobody is nagged about it. And when the detector genuinely
    cannot produce a candidate — unreadable baseline, refuse-don't-
    fabricate — the label NAMES the reason and the operator is told."""
    import sldea_edge_gui as gui
    import sldea_trace as strc
    root = _tk_root_or_skip('trace pairing without a detect pass')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_pair_')
    mb = _StubMB()
    real_mb = gui.messagebox
    gui.messagebox = mb
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None, "synthetic run failed to load"
        # exactly the operator's state: reviewed run, no detection pass
        assert not app.cands_all, "fixture pre-detected; repro invalid"
        meta = {'zoom': 1.0, 'overlays': {}, 'elapsed_s': 3.0,
                'snapped': False}
        poly = [(80.0, 60.0), (240.0, 60.0), (240.0, 180.0),
                (80.0, 180.0)]
        i = app.frame_rows[1]
        app.pos = app.frame_rows.index(i)
        app._trace_staged(i, poly, meta)
        rec = strc.load_labels(run)[-1]
        assert rec['machine'] is not None, "machine:null came back (#162)"
        assert strc.is_paired(rec) and rec['unpaired'] is None
        assert strc.label_iou(rec) is not None
        # tagged as the narrower pass: its conf carries no ramp
        # hysteresis and no same-kV pair reconciliation
        assert rec['machine']['detect_scope'] == strc.SCOPE_FRAME
        assert not mb.warnings, "warned about a pairing it just created"
        # the on-demand pairing may only ADD a PAIRING — never a review
        # candidate, an acceptance, a rejection or a scale reference
        assert i in app.pair_cands and i not in app.cands_all
        assert not app.results
        assert not app.auto_idx and not app.auto_rej
        assert app.base_ref is None and app.manual_ref is None
        # the tracer may still DRAW it: the operator should see what
        # their polygon is being compared with
        assert app.trace_overlay_cands(i), "pairing not drawable"
        # ---- the honest limit: no baseline, no candidate, ever --------
        base_png = os.path.join(run, 'frames',
                                'SLDEA_s00_00.00kV_baseline.png')
        open(base_png, 'wb').close()                  # 0-byte baseline
        j = app.frame_rows[2]
        app.pos = app.frame_rows.index(j)
        assert j not in app.cands_all
        # the verdict is cached, FAILURES INCLUDED: _trace and Done both
        # ask, and an uncached failure branch made the operator sit
        # through the baseline decode + detect twice per traced frame
        # (~1 s each at 3840x2160 -- review 2026-08-06)
        calls, real_one = [], app._detect_one

        def counted(k):
            calls.append(k)
            return real_one(k)

        app._detect_one = counted
        # NOTE this calls _trace_staged directly, i.e. the BYPASS path (no
        # 'unpaired_ack' in meta): the warning below is what a caller that
        # skipped the tracer-open gate must still get. The real operator
        # flow -- gate at open, no warning at Done -- is
        # test_trace_gate_is_shown_once_and_can_be_declined.
        app._trace_staged(j, poly, meta)
        assert app._machine_pairing(j)[1] == strc.UNPAIRED_NO_BASELINE
        assert calls == [j], calls
        rec = strc.load_labels(run)[-1]
        assert rec['machine'] is None
        assert rec['unpaired'] == strc.UNPAIRED_NO_BASELINE
        assert len(mb.warnings) == 1, mb.warnings
        assert 'UNPAIRED' in app.status.cget('text')
        # the trace itself still SURVIVED — #162's recovery job outranks
        # its calibration job
        assert app.traces[j]['method'] == 'manual-trace'
        assert abs(app.traces[j]['area_px'] - strc_area(poly)) < 1e-6
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def strc_area(poly):
    import sldea_trace as strc
    return strc.polygon_area(poly)


# ---------------------------------------------------------------------------
# MODE C -- the machine measures, the operator VERIFIES (2026-08-06 evening)
# ---------------------------------------------------------------------------

def _cal_buttons(win, rendered_only=False):
    """The dialog's buttons by label. `rendered_only` restricts it to the ones
    the geometry manager is actually showing — needed since `#215`'s
    de-rendering pass (2026-08-07), because the round controls now go away by
    being unpacked rather than by being disabled, and an unpacked Button still
    answers cget('text') perfectly happily."""
    return {b.cget('text'): b for b in _widgets(win, 'button')
            if not rendered_only or _cal_rendered(b, win)}


def test_mode_C_is_where_the_gate_opens_and_Accept_needs_the_button():
    """`#215` 2026-08-06 evening, THROUGH THE REAL DIALOG.

    Four things at once, because they are one behaviour: the gate opens in
    mode C when there is a fit to verify; <Return> cannot approve it; the
    ✔ Accept button produces an `auto-verified` anchor carrying the fit's
    quality and a named approver; and NOTHING on screen or in the record
    claims a cross-check -- the only one available is vacuous.

    Skips headlessly like every other dialog case here, so a green suite is
    not evidence the window opens; the text and arithmetic are pinned
    separately in tests/test_sldea_calibration.py."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('mode C verify')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_cal_verify_')
    real_mb = gui.messagebox
    saw = {}
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        spy = _ModalSpy(real_mb, app)          # no answers: all defaults
        gui.messagebox = spy
        fit = app._auto_disc()
        assert fit and fit.get('diam_px'), "fixture has no automatic fit"

        def poke(win):
            p = app._cal_probe
            saw['mode'] = (p['mode_var'].get(), p['st']['mode'])
            saw['text'] = _cal_display(win)
            saw['title'] = win.title()
            saw['stretch'] = p['st']['stretch']
            btns = _cal_buttons(win)
            saw['btns'] = sorted(btns)
            saw['btns_shown'] = sorted(_cal_buttons(win, rendered_only=True))
            step = p['step_btn']
            saw['step_text'] = step.cget('text')
            saw['step_default'] = str(step.cget('default'))
            saw['back_state'] = str(p['back_btn'].cget('state'))
            saw['shown'] = _cal_shown_controls(p)
            # (1) ENTER MUST NOT APPROVE. Put the dialog on screen first --
            # a synthetic key press is silently dropped by an unviewable
            # widget, so without this the case would pass vacuously.
            _cal_onscreen(root, win)
            win.focus_force()
            win.update()
            for _ in range(6):
                if not win.winfo_exists():
                    break
                win.event_generate('<Return>', when='now')
                win.update()
            saw['alive_after_enter'] = win.winfo_exists()
            saw['ref_after_enter'] = app.manual_ref
            saw['live'] = _cal_display(win) if win.winfo_exists() else ''
            # (2) the BUTTON approves
            step.invoke()

        app.root.wait_window = poke
        app._calibrate_scale()
        # --- opened in C, on the strength of a real fit
        assert saw['mode'] == (VERIFY, VERIFY), saw['mode']
        # THE INTENT IS ON THE BUTTON (`#215` fold, 2026-08-06 late): the
        # one 📏 entry point can either hold the anchor for Save or
        # rewrite data.csv now, and the verify mode hides the block that
        # says which in words, so the button the operator presses carries
        # it. A plain '✔ Accept' would be ambiguous between the two.
        assert saw['step_text'] == ('✔ Accept the automatic fit '
                                   '(at Save)'), saw
        assert saw['step_default'] == 'active', saw   # primary, as intended
        # THE ROUND CONTROLS ARE ABSENT, NOT GREYED (`#215`, operator
        # 2026-08-07): *"a disabled control still costs a line of visual
        # scanning and invites a click; an absent one does not."* So this is an
        # existence claim about what the geometry manager is showing -- and
        # `state` staying 'normal' is part of it, because the mode is what
        # decides whether they exist and nothing is ever shown greyed.
        assert saw['shown'] == set(), saw['shown']
        assert saw['back_state'] == 'normal', saw
        assert not any('Back' in b for b in saw['btns_shown']), \
            saw['btns_shown']
        assert not any('Restart' in b for b in saw['btns_shown']), \
            saw['btns_shown']
        # ... and they still EXIST as widgets, so a switch to a measuring mode
        # brings them back rather than having to rebuild the row
        assert any('Back' in b for b in saw['btns']), saw['btns']
        # ✎ Measure by hand instead is GONE (operator 2026-08-06 late):
        # the radio row already switches methods, so it was a second
        # control for one job. The radios are the route now.
        assert not any('Measure by hand' in b for b in saw['btns']), \
            saw['btns']
        assert 'hand_btn' not in (app._cal_probe or {})
        assert saw['stretch'] is not None, "no contrast stretch was applied"
        # --- Enter was refused, and said why
        assert saw['alive_after_enter'], "Enter closed the dialog"
        assert saw['ref_after_enter'] is None, (
            "Enter approved an anchor nobody had read: "
            + str(saw['ref_after_enter']))
        assert 'Enter cannot approve an anchor' in saw['live'], saw['live']
        assert not spy.asked, ("mode C asked a yes/no question it should "
                              "not: " + str(spy.asked))
        # --- the evidence was on screen BEFORE the button was pressed
        t = saw['text']
        for needle in ('Automatic fit', 'px across', 'Quality',
                       'of diameter', 'circularity'):
            assert needle in t, (needle, t[:400])
        assert f"{fit['diam_px']:.1f} px" in t, t[:400]
        # THE STANDING DISCLAIMER IS OFF THE SCREEN (operator 2026-08-06
        # late) -- and still in the RECORD, which is asserted below on
        # ref['guard'] and on the log line. That split is the whole point:
        # the honesty belongs where a later reader needs it, not in front of
        # the person judging one boundary in one moment.
        for dropped in ('contrast-stretched', 'raw frame',
                        'Nothing cross-checks it',
                        'your eye is the check'):
            assert dropped not in t, (dropped, t[:400])
        # WHICH OF THE TWO FOLDED ACTIONS this is: the plain 📏 entry point
        # holds the anchor for Save here and writes nothing.
        #
        # ON THE BUTTON AND THE TITLE, not in the label text -- and that is a
        # correction, not a relaxation. The verify mode has always hidden the
        # gate block, so before the 2026-08-07 trim this assertion was
        # reading the banner out of a label the operator could not see: it
        # passed on text that was never on screen. The two surfaces that
        # really carry it here are the ones checked now (and
        # test_the_dialog_says_which_of_the_two_folded_actions_it_serves
        # covers both intents in both kinds of mode).
        assert 'at Save' in saw['step_text'], saw['step_text']
        assert 'RE-ANCHOR' not in saw['step_text'], saw['step_text']
        assert 'applied at Save' in saw['title'], saw['title']
        assert 'RE-ANCHOR' not in saw['title'], saw['title']
        # NO VACUOUS CROSS-CHECK IS CLAIMED anywhere the operator can read
        for lie in ('apart in diam', 'mask area +0.0', 'cross-check passed',
                    '✓'):
            assert lie not in t, (lie, t)
        # --- the anchor: provenance distinct from a hand measurement
        ref = app.manual_ref
        assert ref is not None, "Accept produced no anchor"
        assert ref['method'] == gui.se.ANCHOR_METHOD_VERIFIED == \
            'auto-verified'
        assert ref['method'] != gui.se.ANCHOR_METHOD_MANUAL
        assert ref['cal_mode'] == VERIFY
        assert abs(ref['diam_px'] - fit['diam_px']) < 1e-9
        assert ref['fit_n_edge'] == fit['n_edge']
        assert abs(ref['fit_resid_px'] - fit['fit_resid_px']) < 1e-9
        assert ref['verified_by'] and ref['verified_at'], ref
        # NO rounds and NO spread -- nothing was fitted
        for k in ('rounds_px', 'n_rounds', 'spread_px', 'spread_pct',
                  'sigma_pct', 'se_pct'):
            assert ref.get(k) is None, (k, ref.get(k))
        # the record says in words what was not checked
        assert 'NOT cross-checked' in ref['guard']
        assert 'vacuous' in ref['guard']
        ref['guard'].encode('ascii')
        # THE STATUS LINE says VERIFIED, not calibrated -- and its FOOTER is
        # gone (`#215`, operator 2026-08-07). It used to end with 160
        # characters of honesty ("σ/SE undefined (one fit, no rounds); NOT
        # cross-checked, and no independent check of an automatic anchor
        # exists — overrides every automatic reference at Save") arriving
        # AFTER the decision had been made, on the surface a person reads
        # next while doing something else.
        #
        # It claims no tick either way: what is asserted here is that it
        # states the VALUE, the APPROVER and the fit's own quality, and
        # nothing that reads as a check having been performed.
        stat = app.status.cget('text')
        assert 'VERIFIED' in stat, stat
        assert ref['verified_by'] in stat, stat
        assert 'circ 1.000' in stat and 'resid' in stat, stat
        assert f"{ref['diam_px']:.0f} px" in stat, stat
        for gone in ('σ/SE undefined', 'NOT cross-checked',
                     'no independent check', 'overrides every automatic'):
            assert gone not in stat, (gone, stat)
        # ... and every word of that footer is still in the RECORD, which is
        # the whole trade. Two of the three surfaces are asserted right here
        # (ref['guard'] above and the log line below); sldea_diag's two
        # verdicts and its text report are pinned by
        # test_verify_note_and_the_log_keep_every_number_the_screen_dropped.
        assert 'NOT cross-checked' in ref['guard'], ref['guard']
        assert 'vacuous' in ref['guard'], ref['guard']
        # --- the log line: mode=verify, undefined precision, never 0.00%
        with open(os.path.join(app.rundir, gui.se.CAL_LOG_NAME),
                  encoding='utf-8') as f:
            log = f.read()
        line = [L for L in log.splitlines()
                if L.startswith('SLDEA-CAL')][-1]
        assert 'mode=verify' in line and 'n=1' in line, line
        for f_ in ('sigma=undefined', 'se=undefined', 'range=undefined',
                   'verdict=NOT-GATED', 'outcome=accepted-verified',
                   '(IS-the-anchor)'):
            assert f_ in line, (f_, line)
        assert '0.00%' not in line, line
        # --- and Save persists all of it
        gui.se.save_scale_anchor(app.rundir, {
            'method': ref['method'], 'cal_mode': ref['cal_mode'],
            'diam_px': ref['diam_px'], 'diam_mm': 16.0,
            'mm_per_px': 16.0 / ref['diam_px'],
            'fit_circ': ref['fit_circ'], 'fit_conf': ref['fit_conf'],
            'fit_resid_px': ref['fit_resid_px'],
            'fit_arc_cov': ref['fit_arc_cov'],
            'fit_n_edge': ref['fit_n_edge'],
            'verified_by': ref['verified_by'],
            'verified_at': ref['verified_at'], 'guard': ref['guard']})
        back = gui.se.load_scale_anchor(app.rundir)
        assert back['method'] == 'auto-verified'
        assert back['cal_mode'] == VERIFY
        assert back['verified_by'] == ref['verified_by']
        assert gui.se._is_manual_cal(back), "a verified anchor must still " \
                                           "override every automatic ref"
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_every_mode_holds_the_on_screen_line_budget():
    """THE LINE BUDGET, through the real dialog, IN ALL THREE MODES
    (`#215`: verify decluttered 2026-08-06 late, extended to the two
    measuring modes 2026-08-07).

    The verify mode was driven on a real disc and the fit was accepted as
    correct, so the premise held -- but the operator's verdict on the screen
    it was accepted on was "wayyyyy too busy with text and unnecessary
    garbage": 13 lines of prose wrapping to 19, above a canvas showing the
    577 px disc at 282 px because the view opened fit-to-frame with a "below
    1:1 -- press Z" nag under it. That got cut to two lines.

    Then the operator drove the two MEASURING modes on real data and said the
    same thing about them -- "trim the wall of text". Measured at a simulated
    1080p they were showing NINE lines each (1155 and 1393 chars) against the
    verify mode's two, because the declutter had only ever been applied to
    one mode's block. So the budget stops being the verify block's private
    rule: it is the SCREEN's rule, and this case is the thing that keeps it
    that way in every mode.

    Then the operator drove all three on real runs that evening and cut six
    more things (`#215`, 2026-08-07 second pass), so the ORDINARY worst case
    is now THREE lines in every mode and the caps here came down with it:

    * the folded action's tag left the round header (it is on the title, the
      primary button and the re-anchor confirmation, which are the three
      places where it decides something);
    * the "N row(s) already carry px" row left the top of the window for the
      button's own confirmation, which now opens by asking whether to
      OVERWRITE the calibration on record;
    * `disc 16 mm` and `view rotated N deg` left the round header;
    * the aim rule became an INSTRUCTION ("straddle the edge") instead of the
      metrology convention it achieves, which stays in §1.3;
    * and the controls that do not apply to a mode are DE-RENDERED rather
      than greyed out, which is a screen claim too and is asserted here.

    Re-inflation is the likely regression, and it is likelier in the
    measuring modes than it was in the verify mode: every number cut is still
    in the record, and every sentence cut was TRUE -- why the rounds are
    blind, why the view rotates, what the keys do. A true sentence is the
    easiest kind to put back. THE CAPS ARE THEREFORE TIGHT ON PURPOSE: slack
    left in a budget is slack that gets spent.

    Pinned here rather than only on verify_evidence() because the budget is
    a property of the SCREEN: the gate block, the instruction, the round
    header and the live readout are four separate widgets, and re-inflating
    any of them would leave a pure-function test green."""
    import sldea_edge_gui as gui
    import tkinter as tk
    root = _tk_root_or_skip('on-screen line budget')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_cal_budget_')
    real_mb, real_spawn = gui.messagebox, gui.spawn_circle
    saw = {}
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        # THE WORST CASE, because a budget that only holds when a line
        # happens to be absent is not a budget: a PRIOR ANCHOR that differs
        # (so the conditional consequence line is present) plus already-
        # measured px rows (so it carries its longest wording).
        gui.se.save_scale_anchor(run, {
            'method': 'manual-calibration', 'cal_mode': CIRCLE,
            'diam_px': 163.5, 'diam_mm': 16.0, 'mm_per_px': 16.0 / 163.5,
            'n_rounds': 3, 'spread_pct': 0.5, 'spread_px': 0.8})
        csvp = os.path.join(run, 'data.csv')
        with open(csvp, encoding='utf-8') as f:
            rd = list(csv.DictReader(f))
        for r in rd[1:]:
            r['active_area_px'] = '12345.0'
            r['active_area_mm2'] = '123.45'
        with open(csvp, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(rd[0]))
            w.writeheader()
            w.writerows(rd)
        app = gui.EdgeReviewApp(root, path=run)
        assert app._px_rows() == 2, app._px_rows()
        gui.messagebox = _ModalSpy(real_mb, app)
        gui.spawn_circle = lambda *_a, **_k: (160.0, 120.0, 80.0)
        fit = app._auto_disc()
        assert fit and fit.get('diam_px'), "fixture has no automatic fit"

        def poke(win):
            _cal_onscreen(root, win)
            win.update_idletasks()
            p = app._cal_probe
            assert p['st']['mode'] == VERIFY, p['st']['mode']
            saw['lines'] = _cal_visible_lines(win)
            saw['zoom'] = p['vt'].zoom
            saw['canvas'] = (int(p['canvas'].cget('width')),
                             int(p['canvas'].cget('height')))
            saw['reqh'] = win.winfo_reqheight()
            saw['shown_' + VERIFY] = _cal_shown_controls(p)
            # the <Return> refusal must still be SEEN, even though the line
            # it lands on is hidden in the steady state
            win.focus_force()
            win.update()
            for _ in range(4):
                if not win.winfo_exists():
                    break
                win.event_generate('<Return>', when='now')
                win.update()
            saw['after_enter'] = _cal_visible_lines(win)
            # SELF-CHECK, because a synthetic key press is silently dropped
            # by an unviewable widget (see _cal_onscreen) and a dropped one
            # must SKIP the visibility claim, not launder a real failure of
            # it: `delivered` reads the label's text whether it is mapped or
            # not, so it is true exactly when continue_key ran.
            saw['enter_delivered'] = ('Enter cannot approve'
                                      in _cal_display(win))
            # ... and switching away and back must not leave it behind
            saw['chooser_order'] = []
            for val in (CIRCLE, VERIFY, CIRCLE):
                for rb in _widgets_of(win, tk.Radiobutton):
                    if rb.cget('value') == val:
                        rb.invoke()
                win.update_idletasks()
                saw['lines_' + val] = _cal_visible_lines(win)
                saw['shown_after_switch_' + val] = _cal_shown_controls(p)
                if val == CIRCLE:
                    # the chooser's left-to-right order, so a round trip that
                    # re-packed the two per-mode boxes the WRONG WAY ROUND is
                    # caught. pack_slaves() IS the packing order.
                    saw['chooser_order'].append(
                        [str(w) for w in p['rounds_box'].master.pack_slaves()])
            win.destroy()

        app.root.wait_window = poke
        app._calibrate_scale()
        # ---- and each MEASURING mode, opened in its own dialog ------------
        # One dialog per mode rather than a switch, so what is measured is
        # what the operator gets when the gate opens there. (The switch path
        # keeps its own coverage at the end of this case.)
        for m in (CIRCLE, TWOPOINT):
            def look(win, m=m):
                p = app._cal_probe
                assert p['st']['mode'] == m, (m, p['st']['mode'])
                saw['open_' + m] = _cal_visible_lines(win)
                saw['reqh_' + m] = win.winfo_reqheight()
                saw['shown_' + m] = _cal_shown_controls(p)
                win.destroy()
            app.root.wait_window = look
            app.manual_ref = None
            app._calibrate_scale(mode=m)

        # ---- THE BUDGET, every mode --------------------------------------
        # FOUR is the pathological ceiling and it is what verify_evidence
        # shares (value + quality + a stretch that could not be computed + a
        # prior anchor that differs). THREE is the ORDINARY worst case, which
        # is what this fixture drives and what the 2026-08-07 cuts brought it
        # down to in every mode -- so both are pinned, and the ordinary one is
        # the one that catches a re-inflation.
        assert gui.CAL_SCREEN_MAX_LINES == 4, gui.CAL_SCREEN_MAX_LINES
        assert gui.CAL_VERIFY_MAX_LINES == gui.CAL_SCREEN_MAX_LINES
        assert gui.CAL_SCREEN_MAX_LINES_ORDINARY == 3, \
            gui.CAL_SCREEN_MAX_LINES_ORDINARY
        for m, got in ((VERIFY, saw['lines']),
                       (CIRCLE, saw['open_' + CIRCLE]),
                       (TWOPOINT, saw['open_' + TWOPOINT])):
            assert got, f"mode {m} put NOTHING on screen"
            assert len(got) <= gui.CAL_SCREEN_MAX_LINES_ORDINARY, (
                f"mode {m}: {len(got)} lines on screen in the ORDINARY worst "
                f"case, budget is {gui.CAL_SCREEN_MAX_LINES_ORDINARY}:\n"
                + '\n'.join(got))
            # SHORT lines, not three paragraphs. The longest legitimate line
            # is the verify mode's consequence line (~170 chars); the cap
            # leaves room for wording, not for a re-inflated paragraph.
            for ln in got:
                assert len(ln) <= gui.CAL_SCREEN_MAX_LINE_CHARS, (
                    m, len(ln), ln)
            # TIGHT, because a budget with slack in it is a budget that gets
            # spent. Two numbers, not one: a measuring mode carries a live
            # per-click readout and a gesture instruction that the verify
            # mode has no equivalent of.
            cap = (gui.CAL_SCREEN_MAX_CHARS if m == VERIFY
                   else gui.CAL_SCREEN_MAX_CHARS_MEASURING)
            assert sum(len(ln) for ln in got) <= cap, (
                f"mode {m}: {sum(len(ln) for ln in got)} chars on screen "
                f"(cap {cap}):\n" + '\n'.join(got))

        # ---- THE MEASURING MODES: what has to survive, and what went -----
        for m, gesture in ((CIRCLE, 'a handle to resize'),
                           (TWOPOINT, 'the point OPPOSITE it')):
            j = '\n'.join(saw['open_' + m])
            # WHICH ROUND THEY ARE ON, and THE IMMEDIATE INSTRUCTION -- the
            # two things the operator asked to keep, and now the ONLY two.
            assert f"Method {'B' if m == CIRCLE else 'C'} · Round 1 of" in j, j
            assert gesture in j, j
            # THE AIM RULE, as an instruction about where to put the mark
            # (`#215`, operator 2026-08-07). It is the one instruction on this
            # screen with a measured cost behind it (§1.3: the point a human
            # picks by eye is the outer toe, +2.6 % in diameter), so its
            # PRESENCE is pinned -- and its old wording, which named the
            # metrology convention instead of the gesture, is pinned ABSENT
            # below.
            assert 'straddle the edge' in j.lower(), (
                "the aim rule went: it is the one instruction here with a "
                "measured cost behind it\n" + j)
            assert 'half on the paper' in j, j
            assert ('half the stroke' if m == CIRCLE else 'half the ring') \
                in j, j
            # ... and the REFERENCE MATERIAL that came off (`#215`,
            # 2026-08-07, both passes). Every one of these is still true; that
            # is exactly why it is worth pinning that it is not on screen.
            for gone in (
                    # why the rounds are blind / randomised
                    'HIDDEN until the last fit', 'scatter is a fiction',
                    'independent',
                    # why the view rotates -- and, since the second pass, the
                    # ANGLE itself: the picture is visibly rotated
                    'random one', 'fixed error', 'view rotated',
                    # the key catalogue
                    'Ctrl+wheel', 'right-drag', 'F fits', 'Z = 1:1',
                    'Esc cancels', 'Shift = coarse', 'Shift+arrows',
                    # the standing prose the gate block used to open with
                    'SCALE GATE', 'nominal disc', 'held for this session',
                    'METHOD B (circle)', 'METHOD C (two points)',
                    # the round header's third copy of the Finish button
                    'this is the LAST round',
                    # the recorded anchor's DIAMETER: a printed target
                    # standing on screen through a blind measurement
                    '163.5 px', 'mm/px, saved',
                    # SECOND PASS (operator 2026-08-07 evening) ------------
                    # the aim rule's old wording: a definition, not an
                    # instruction. The convention it achieves is §1.3's.
                    'HALF-HEIGHT', 'mid-gray', 'outer toe',
                    # the folded action's tag: on the title, the primary
                    # button and the re-anchor confirmation instead
                    'NOTHING is written', 'RE-ANCHOR — WRITTEN',
                    'WRITTEN TO data.csv',
                    # the "already calibrated" row: in the button's own
                    # confirmation now, which asks whether to OVERWRITE
                    'already carry px', 'RE-SCALES every recorded',
                    'press P to REUSE it', 'never re-review',
                    # the nominal disc size off the round header
                    'disc 16 mm'):
                assert gone not in j, (m, gone, j)
            # the window still fits a 1080p bench screen
            assert saw['reqh_' + m] <= root.winfo_screenheight(), (
                m, saw['reqh_' + m], root.winfo_screenheight())

        # ---- DE-RENDERED, NOT GREYED OUT (`#215`, operator 2026-08-07) ----
        # "A disabled control still costs a line of visual scanning and
        # invites a click; an absent one does not." So this is an EXISTENCE
        # claim, and it is checked on winfo_manager(): a state='disabled'
        # widget would satisfy any weaker check while still being on screen.
        assert saw['shown_' + VERIFY] == set(), (
            "the verify mode still renders round-based controls: "
            + str(saw['shown_' + VERIFY]))
        assert saw['shown_' + CIRCLE] == {'round_box', 'rounds_box',
                                          'stroke_box'}, \
            saw['shown_' + CIRCLE]
        # the stroke belongs to the CIRCLE alone -- the two-point mode's
        # markers are specified by marker_shapes and have no width to choose
        assert saw['shown_' + TWOPOINT] == {'round_box', 'rounds_box'}, \
            saw['shown_' + TWOPOINT]

        lines = saw['lines']
        joined = '\n'.join(lines)
        # what stayed
        assert 'Automatic fit' in joined and 'px across' in joined, joined
        assert 'of diameter' in joined and 'circularity' in joined, joined
        assert '% from the' in joined and 'next Save' in joined, joined
        # ... and the standing stretch / no-cross-check sentence that came
        # OFF it (operator 2026-08-06 late). It is still in the run's
        # `guard:` field, the log line and sldea_diag -- pinned by
        # test_verify_note_and_the_log_keep_every_number_the_screen_dropped.
        for dropped in ('contrast-stretched', 'raw frame',
                        'Nothing cross-checks it',
                        'your eye is the check'):
            assert dropped not in joined, (dropped, joined)
        # ... and the garbage that went. Each of these is still in the
        # RECORD (test_mode_C_is_where_the_gate_opens covers that end); what
        # is asserted here is only that it is not on the SCREEN.
        for gone in ('conf ', 'confidence', 'edge point', 'edge pts',
                     'arc coverage', 'interior fill', 'resting area',
                     'press Z', 'below 1:1', 'BY CONSTRUCTION',
                     'no rounds and no spread', 'SCALE GATE',
                     'ALL ELEVEN', '+0.00'):
            assert gone not in joined, (gone, joined)
        # OPENS ZOOMED ON THE FIT -- which is what removes the nag rather
        # than hiding it. Fit-to-frame on this 320x240 fixture would be
        # ~2.4x for a 1000-wide canvas; verify_zoom frames the CIRCLE, so
        # the disc spans ~82% of the canvas's shorter side either way.
        span = fit['diam_px'] * saw['zoom']
        assert span <= min(saw['canvas']) + 1, (span, saw['canvas'])
        assert span >= 0.70 * min(saw['canvas']), (
            f"the fitted disc spans {span:.0f} px of a "
            f"{saw['canvas']} canvas -- mode C opened surveying the frame "
            f"instead of framing the circle")
        # the whole window still fits a 1080p bench screen
        assert saw['reqh'] <= root.winfo_screenheight(), (
            saw['reqh'], root.winfo_screenheight())
        # the <Return> refusal was VISIBLE (a 5th line, transiently, in
        # answer to a key press -- not standing clutter). Mode C hides the
        # live line to hold the budget, so a refusal written to it with the
        # line still hidden would be a SILENT refusal, and an operator who
        # gets no answer taps again harder.
        if saw['enter_delivered']:
            assert any('Enter cannot approve' in ln
                       for ln in saw['after_enter']), (
                "the <Return> refusal was written but never shown: mode C "
                "hides the live line and this message has to bring it back")
        else:
            print("   (skipped the <Return>-refusal visibility claim: no "
                  "synthetic key press reached the dialog)")
        # THE SWITCH: the circle mode brings its own text back, and returning
        # to the verify mode sheds it again -- and neither may exceed the
        # budget on the way through, which is what the counts used to prove
        # and no longer can now that both sides are short.
        assert any('Round 1 of 3' in ln
                   for ln in saw['lines_' + CIRCLE]), saw['lines_' + CIRCLE]
        assert any('straddle the edge' in ln
                   for ln in saw['lines_' + CIRCLE]), saw['lines_' + CIRCLE]
        assert not any('Automatic fit' in ln
                       for ln in saw['lines_' + CIRCLE]), (
            "the verify mode's evidence block survived the switch, so the "
            "fit's diameter is a printed target for a blind round: "
            + str(saw['lines_' + CIRCLE]))
        # ... INCLUDING the live readout, which the first cut of this left
        # forgotten: text set, label unpacked, so a circle-mode round ran with
        # its diameter readout -- the one number it needs -- invisible.
        # Found by rendering the dialog after a C->A switch, not by a test.
        assert any('px across' in ln and 'mm/px' in ln
                   for ln in saw['lines_' + CIRCLE]), (
            "the circle mode came back from the verify mode without its "
            "diameter readout on screen: " + str(saw['lines_' + CIRCLE]))
        for val in (CIRCLE, VERIFY):
            got = saw['lines_' + val]
            assert len(got) <= gui.CAL_SCREEN_MAX_LINES, (val, got)
        # ... and the CONTROLS come back with the mode, not just the text: the
        # circle mode is the only one with a stroke to choose, and a switch
        # that re-rendered them in the wrong ORDER (or not at all) is the
        # failure mode of doing this with pack_forget rather than `state`.
        assert saw['shown_after_switch_' + CIRCLE] == {
            'round_box', 'rounds_box', 'stroke_box'}, \
            saw['shown_after_switch_' + CIRCLE]
        assert saw['shown_after_switch_' + VERIFY] == set(), \
            saw['shown_after_switch_' + VERIFY]
        assert saw['chooser_order'][0] == saw['chooser_order'][1], (
            "the chooser row's controls came back in a different order after "
            "a mode round trip: " + str(saw['chooser_order']))
    finally:
        gui.messagebox, gui.spawn_circle = real_mb, real_spawn
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_a_refused_fit_falls_through_to_the_hand_measurement_and_says_why():
    """When `baseline_disc` refuses there is nothing to verify, so mode C is
    WITHDRAWN (not offered as an empty screen) and the gate opens on the
    hand measurement -- stating plainly that the fit refused, and quoting
    the fitter's own reason. `P3_7_2.3mL_20260729` is the real run this
    covers."""
    import sldea_edge_gui as gui
    import tkinter as tk
    import cv2
    root = _tk_root_or_skip('mode C refusal')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_cal_refuse_')
    real_mb, real_spawn = gui.messagebox, gui.spawn_circle
    saw = {}
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        # overwrite the baseline with a FLAT field: readable, but the fit
        # has nothing to seed on. (Not a 0-byte file -- that is the
        # fallback-frame path, which test_unavailable_cross_check covers.)
        base = os.path.join(run, 'frames', 'SLDEA_s00_00.00kV_baseline.png')
        cv2.imwrite(base, np.full((240, 320), 190, np.uint8))
        app = gui.EdgeReviewApp(root, path=run)
        assert app._base_gray() is not None, "the baseline must still read"
        assert app._auto_disc() is None, "the fixture no longer refuses"
        why = app._auto_disc_refusal()
        assert why and 'seed' in why, why
        gui.messagebox = _ModalSpy(real_mb, app)
        gui.spawn_circle = lambda *_a, **_k: (160.0, 120.0, 80.0)

        def poke(win):
            p = app._cal_probe
            saw['mode'] = (p['mode_var'].get(), p['st']['mode'])
            saw['text'] = _cal_display(win)
            saw['radios'] = [rb.cget('value')
                             for rb in _widgets_of(win, tk.Radiobutton)]
            saw['step'] = p['step_btn'].cget('text')
            saw['back'] = str(p['back_btn'].cget('state'))
            saw['radio_text'] = [rb.cget('text')
                                 for rb in _widgets_of(win,
                                                       tk.Radiobutton)]
            win.destroy()

        app.root.wait_window = poke
        app._calibrate_scale()
        # opened on the HAND measurement, mode C not on offer at all
        assert saw['mode'] == (gui.se.CAL_DEFAULT_MODE, CIRCLE), saw['mode']
        assert VERIFY not in saw['radios'], saw['radios']
        assert saw['step'].startswith('Continue'), saw['step']
        assert saw['back'] == 'normal', saw
        # THE RADIOS ARE THE ONLY ROUTE to a hand measurement now, so they
        # have to READ as one -- each manual entry says so in words, and
        # the letters keep their positions when A is withdrawn (B is the
        # circle whether or not the verify mode is on offer).
        rt = saw['radio_text']
        assert all('BY HAND' in t for t in rt), rt
        assert any(t.startswith('B ·') for t in rt), rt
        assert any(t.startswith('C ·') for t in rt), rt
        assert not any(t.startswith('A ·') for t in rt), rt
        # and it SAID so, with the fitter's own reason. ONE LINE since the
        # 2026-08-07 trim (`#215`) -- the refusal and its reason were two
        # lines and are now one; what has to survive is that the operator is
        # told there is nothing to verify, that the job is now BY HAND, and
        # WHY the fitter said no in the fitter's own words.
        t = saw['text']
        assert 'NO automatic fit on this run' in t, t[:400]
        assert 'nothing to verify' in t, t[:400]
        assert 'BY HAND' in t, t[:400]
        assert 'Reason:' in t and 'seed' in t, t[:600]
        # asking for mode C explicitly on such a run is refused the same way
        app.manual_ref = None
        saw.clear()
        app._calibrate_scale(mode=gui.se.CAL_MODE_VERIFY)
        assert saw['mode'] == (gui.se.CAL_DEFAULT_MODE, CIRCLE), saw['mode']
        assert 'NO automatic fit on this run' in saw['text']
    finally:
        gui.messagebox, gui.spawn_circle = real_mb, real_spawn
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_switching_into_mode_C_gives_it_the_same_room_as_opening_in_it():
    """The canvas height must follow the MODE, not the mode the dialog
    happened to open in -- a canvas sized once and then re-used across a
    switch overflowed a 1080p bench screen by ~80 px.

    The DIRECTION of the split flipped with the declutter (`#215`,
    2026-08-06 late): mode C used to need ~180 px more text room than A/B
    and gave the canvas up for it; it now shows four lines against A/B's
    gate block plus gesture help plus round header, so C is the mode with
    height to SPARE and the picture gets it. Either way the invariant under
    test is the same one -- switching in gives C exactly what opening in it
    does, and A gets its own height back -- and it is asserted
    screen-independently rather than as a pixel count.

    The window fitting the screen is checked in both modes, because that is
    what a wrong height actually breaks."""
    import sldea_edge_gui as gui
    import tkinter as tk
    root = _tk_root_or_skip('mode C canvas height')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_cal_room_')
    real_mb, real_spawn = gui.messagebox, gui.spawn_circle
    saw = {}
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        gui.messagebox = _ModalSpy(real_mb, app)
        gui.spawn_circle = lambda *_a, **_k: (160.0, 120.0, 80.0)

        def grab(win, key):
            win.update_idletasks()
            p = app._cal_probe
            saw[key] = (p['st']['mode'],
                        int(p['canvas'].cget('height')),
                        win.winfo_reqheight(),
                        round(p['vt'].zoom, 4))

        def opened_in_C(win):
            grab(win, 'openC')
            win.destroy()

        def opened_in_A_then_C(win):
            grab(win, 'openA')
            for rb in _widgets_of(win, tk.Radiobutton):
                if rb.cget('value') == VERIFY:
                    rb.invoke()
            grab(win, 'switchC')
            # and back to A: the height must be RETURNED, not kept
            for rb in _widgets_of(win, tk.Radiobutton):
                if rb.cget('value') == CIRCLE:
                    rb.invoke()
            grab(win, 'backA')
            win.destroy()

        app.root.wait_window = opened_in_C
        app._calibrate_scale()
        app.manual_ref = None
        app.root.wait_window = opened_in_A_then_C
        app._calibrate_scale(mode=CIRCLE)
        assert saw['openC'][0] == VERIFY and saw['openA'][0] == CIRCLE, saw
        assert saw['switchC'][0] == VERIFY and saw['backA'][0] == CIRCLE, saw
        # switching in gives mode C exactly the room opening in it does
        assert saw['switchC'][1] == saw['openC'][1], saw
        assert saw['switchC'][2] == saw['openC'][2], saw
        # ... and A gets its own canvas back, which since the declutter is
        # the SHORTER one: mode C's four lines free the height up and the
        # picture is what mode C spends it on
        assert saw['backA'][1] == saw['openA'][1], saw
        assert saw['openC'][1] >= saw['backA'][1], saw
        # the view was RE-FRAMED for the new canvas, not left cropping
        # against a stale height
        if saw['openC'][1] != saw['openA'][1]:
            assert saw['switchC'][3] == saw['openC'][3], saw
        # and neither mode's window overflows the screen it is sized against
        for k in ('openC', 'openA', 'switchC', 'backA'):
            assert saw[k][2] <= root.winfo_screenheight(), (k, saw[k])
    finally:
        gui.messagebox, gui.spawn_circle = real_mb, real_spawn
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_reusing_a_verified_anchor_keeps_it_verified_not_hand_measured():
    """Found while writing mode C: `reuse` hardcoded
    method='manual-calibration', so pressing P on a run whose anchor was
    AUTO-VERIFIED would silently relabel it as a hand measurement -- losing
    the one distinction the provenance field exists for, and then collecting
    a vacuous cross-check tick at detect time as a bonus."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('reuse provenance')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_cal_reuse_')
    real_mb = gui.messagebox
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        gui.se.save_scale_anchor(run, {
            'method': gui.se.ANCHOR_METHOD_VERIFIED, 'cal_mode': VERIFY,
            'diam_px': 159.9, 'diam_mm': 16.0, 'mm_per_px': 16.0 / 159.9,
            'fit_circ': 0.999, 'fit_conf': 0.871, 'fit_resid_px': 0.5,
            'fit_n_edge': 360, 'verified_by': 'anatol',
            'verified_at': '2026-08-06T18:30:00',
            'guard': 'AUTO-VERIFIED by eye: ... NOT cross-checked'})
        app = gui.EdgeReviewApp(root, path=run)
        gui.messagebox = _ModalSpy(real_mb, app)

        def poke(win):
            btns = _cal_buttons(win)
            key = [t for t in btns if 'Reuse' in t]
            assert key, sorted(btns)
            btns[key[0]].invoke()

        app.root.wait_window = poke
        app._calibrate_scale()
        ref = app.manual_ref
        assert ref is not None and ref['reused'] is True
        assert ref['method'] == gui.se.ANCHOR_METHOD_VERIFIED, ref['method']
        assert ref['cal_mode'] == VERIFY
        assert ref['verified_by'] == 'anatol', ref
        assert ref['fit_n_edge'] == 360
        assert gui.se.guard_is_vacuous(ref)
        assert 'auto-verified' in app.status.cget('text')
        # and the detect-time restatement does NOT print a cross-check tick
        app.detect_all_sync()
        stat = app.status.cget('text')
        assert 'AUTO-VERIFIED' in stat, stat
        assert 'NOT cross-checked' in stat, stat
        assert 'apart in diam' not in stat, stat
        assert '✓' not in stat, stat
        # a two-click anchor on the same run still reuses as one
        gui.se.save_scale_anchor(run, {
            'method': gui.se.ANCHOR_METHOD_MANUAL, 'diam_px': 170.0,
            'diam_mm': 16.0, 'mm_per_px': 16.0 / 170.0})
        app.manual_ref = None
        app._calibrate_scale(mode=CIRCLE)
        assert app.manual_ref['method'] == gui.se.ANCHOR_METHOD_MANUAL
        for k in ('fit_n_edge', 'verified_by', 'cal_mode'):
            assert k not in app.manual_ref, k
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_a_verified_anchor_still_reports_when_the_fit_has_MOVED():
    """The one thing that is NOT vacuous on a verified anchor: whether the
    fit this detection pass just made is still the fit that was approved.
    Normally it is, to the bit. Daylight means the baseline or the settings
    changed underneath a reused anchor -- real information, and the only
    signal the anchor guard's arithmetic can still carry here."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('verified anchor drift')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_cal_drift_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        fit = app._auto_disc()
        assert fit and fit.get('diam_px')
        # (a) approved against THIS fit -> no drift warning, no tick either
        app.manual_ref = {'method': gui.se.ANCHOR_METHOD_VERIFIED,
                          'cal_mode': VERIFY, 'diam_px': fit['diam_px'],
                          'fit_circ': fit['circ'], 'fit_conf': fit['conf'],
                          'fit_resid_px': fit['fit_resid_px'],
                          'fit_n_edge': fit['n_edge'],
                          'verified_by': 'anatol'}
        app.detect_all_sync()
        stat = app.status.cget('text')
        assert 'NOT cross-checked' in stat and 'the automatic fit on this ' \
                                              'run is NOW' not in stat, stat
        # (b) the same anchor 4 % off the fit now on the run: the fit moved
        app.manual_ref = dict(app.manual_ref,
                              diam_px=fit['diam_px'] * 1.04, reused=True)
        app.detect_all_sync()
        stat = app.status.cget('text')
        assert 'the automatic fit on this run is NOW' in stat, stat
        assert 'Re-verify it' in stat, stat
        assert '✓' not in stat, stat
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_measure_by_hand_leaves_mode_C_for_a_BLIND_mode_A_round_set():
    """Mode C's second action must be a real escape hatch, not a
    decoration: it drops into the existing hand measurement, from round 1,
    with NOTHING carried over. In particular the fit's diameter must not
    survive onto the screen -- a printed target is exactly what review
    2026-08-06 removed, and mode C is the one place a number the operator
    could aim at was just on display."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('mode C hand fallback')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_cal_hand_')
    real_mb, real_spawn = gui.messagebox, gui.spawn_circle
    saw = {}
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        gui.messagebox = _ModalSpy(real_mb, app)
        gui.spawn_circle = lambda *_a, **_k: (160.0, 120.0, 70.0)
        fit = app._auto_disc()
        assert fit and fit.get('diam_px')

        def poke(win):
            p = app._cal_probe
            assert p['st']['mode'] == VERIFY
            # THE RADIO is the route now -- the ✎ button is gone
            for rb in _widgets_of(win, __import__('tkinter').Radiobutton):
                if rb.cget('value') == CIRCLE:
                    rb.invoke()
            saw['mode'] = (p['mode_var'].get(), p['st']['mode'])
            saw['n'] = (p['n_var'].get(), p['st']['n'])
            saw['round'] = (p['st']['round'], len(p['st']['diams']))
            saw['stretch'] = p['st']['stretch']
            saw['step'] = p['step_btn'].cget('text')
            saw['back'] = str(p['back_btn'].cget('state'))
            saw['shown'] = _cal_shown_controls(p)
            saw['text'] = _cal_display(win)
            win.destroy()

        app.root.wait_window = poke
        app._calibrate_scale()
        assert saw['mode'] == (CIRCLE, CIRCLE), saw['mode']
        assert saw['n'] == ('3', 3), saw['n']
        assert saw['round'] == (1, 0), saw['round']
        assert saw['step'].startswith('Continue'), saw['step']
        assert saw['back'] == 'normal', saw
        # ... and the round controls the verify mode DE-RENDERS are back with
        # the mode (`#215`, operator 2026-08-07): the radio row is the only
        # route into a hand measurement, so a switch that left ◀ Back and the
        # round count absent would leave the hand measurement unusable.
        assert saw['shown'] == {'round_box', 'rounds_box', 'stroke_box'}, \
            saw['shown']
        t = saw['text']
        # the hand measurement's own instructions are back, under the
        # circle's NEW label (B; it was A before the 2026-08-06 swap). The
        # "METHOD B (circle):" prefix on the instruction line went in the
        # 2026-08-07 trim -- the round header beside it says Method B, so the
        # letter is what is checked here now, not the deleted prefix.
        assert 'Method B · Round 1 of' in t, t[:400]
        assert 'straddle the edge' in t, t[:400]
        # ... the evidence block is gone, and with it the fit's diameter:
        # no target to wheel a circle onto
        assert 'Automatic fit' not in t, t[:400]
        assert 'your eye is the check' not in t, t[:400]
        assert f"{fit['diam_px']:.1f} px" not in t, t
        # THE BLINDNESS ITSELF, not the paragraph that used to explain it
        # (`#215` trim, 2026-08-07 -- "the earlier rounds are HIDDEN until the
        # last fit is in" came off the header). What must hold is that no
        # earlier round and no fitted diameter is anywhere on this screen,
        # which the two assertions above are, so this one only pins that the
        # sentence did not quietly come back as the whole evidence for it.
        assert 'HIDDEN until the last fit' not in t, t[:400]
        assert app.manual_ref is None
    finally:
        gui.messagebox, gui.spawn_circle = real_mb, real_spawn
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_one_scale_button_routes_by_the_runs_state():
    """THE FOLD (operator 2026-08-06 late, `#215`). One 📏 button replaces
    📏 Calibrate… and 📏 Re-anchor scale…, because they open the same dialog
    and having two was confusing. What differs is what happens to the number
    AFTERWARDS, and that follows the run:

    - an open review pass -> CALIBRATE, applied at Save. This is the
      `[critical]` mixed-scale bug's own shape (SLDEA_HANDOFF 2026-08-05):
      committing a scale while a half-finished pass sits in self.results puts
      two writers on one mm² column. The old button REFUSED here, and the
      fold must not turn that refusal into a silent commit.
    - a detect worker in flight -> CALIBRATE, same reason: nothing may
      rewrite data.csv under a running pass.
    - nothing measured yet -> CALIBRATE; there are no px to re-derive.
    - a saved run with px and no pass -> RE-ANCHOR, committed immediately.

    And the intent is computed at CLICK TIME, never cached on the button,
    because a stale label would be lying about the one thing that differs:
    whether pressing this writes data.csv now."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('folded scale button')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_scale_fold_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)

        # ONE button, and it names BOTH outcomes so it can never be stale
        labels = [b.cget('text') for b in _widgets_of(root, __import__(
            'tkinter').ttk.Button) if '📏' in b.cget('text')]
        assert len(labels) == 1, labels
        assert 'Calibrate' in labels[0] and 're-anchor' in labels[0].lower()

        # (1) nothing measured yet -> calibrate
        assert app._px_rows() == 0
        i = app._scale_intent()
        assert i['intent'] == gui.SCALE_INTENT_CALIBRATE, i
        assert 'nothing to re-derive' in i['why'], i

        # (2) px on record, no pass open -> RE-ANCHOR
        for r in app.run['rows'][1:]:
            r['active_area_px'] = '12345.0'
            r['active_area_mm2'] = '123.45'
        assert app._px_rows() == 2
        i = app._scale_intent()
        assert i['intent'] == gui.SCALE_INTENT_REANCHOR, i
        assert i['n_px_rows'] == 2 and 'commits immediately' in i['why']

        # (3) an UNSAVED review pass -> back to calibrate, every kind of it
        for attr, val in (('results', {1: 0}), ('traces', {1: [(0, 0)]}),
                          ('flags', {1: True}), ('advisories', {1: 'x'})):
            setattr(app, attr, val)
            i = app._scale_intent()
            assert i['intent'] == gui.SCALE_INTENT_CALIBRATE, (attr, i)
            assert i['dirty'], (attr, i)
            assert 'two writers' in i['why'], (attr, i)
            setattr(app, attr, {})
        assert app._scale_intent()['intent'] == gui.SCALE_INTENT_REANCHOR

        # (4) a detect worker in flight -> calibrate; nothing may write
        app._detect_busy = True
        i = app._scale_intent()
        assert i['intent'] == gui.SCALE_INTENT_CALIBRATE, i
        assert 'detection pass is running' in i['why'], i
        app._detect_busy = False

        # (5) THE DISPATCH itself, both ways
        went = []
        app._calibrate_scale = lambda **kw: went.append(('cal', kw))
        app._reanchor_scale = lambda: went.append(('reanchor', {}))
        app._scale_action()
        assert went == [('reanchor', {})], went
        app.results = {1: 0}
        app._scale_action()
        assert went[-1][0] == 'cal', went
        # ... and with no run at all it asks for one rather than guessing.
        # showinfo is stubbed explicitly: _ModalSpy delegates anything it
        # does not implement to the REAL messagebox, which would put a live
        # modal on screen and block the suite for ever.
        went.clear()
        app.run = None
        told = []

        class _Info:
            def showinfo(self, title, msg='', **_kw):
                told.append((title, msg))

            def __getattr__(self, name):
                raise AssertionError('unexpected messagebox.' + name)

        real_mb = gui.messagebox
        try:
            gui.messagebox = _Info()
            app._scale_action()
        finally:
            gui.messagebox = real_mb
        assert went == [], went
        assert told and 'Pick a run' in told[0][1], told
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_the_dialog_says_which_of_the_two_folded_actions_it_serves():
    """One 📏 button, two blast radii — so the dialog itself has to say which
    one it is, in every mode. The verify mode hides the gate block that says
    it in words, so the PRIMARY BUTTON carries it there, and the window title
    carries it everywhere. Never a bare "Accept": accepting means two
    different things now."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('folded scale intent on screen')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_scale_intent_')
    real_mb, real_spawn = gui.messagebox, gui.spawn_circle
    saw = {}
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        gui.messagebox = _ModalSpy(real_mb, app)
        gui.spawn_circle = lambda *_a, **_k: (160.0, 120.0, 80.0)

        def look(tag):
            def poke(win):
                p = app._cal_probe
                saw[tag] = {'title': win.title(),
                            'step': p['step_btn'].cget('text'),
                            'text': _cal_display(win),
                            # ON SCREEN, not merely set: a pack_forget()-ed
                            # label still has text, and an assertion that
                            # read one used to pass on a banner the operator
                            # could not see (found in the 2026-08-07 trim)
                            'shown': '\n'.join(_cal_visible_lines(win)),
                            'intent': p['intent'],
                            'mode': p['st']['mode']}
                win.destroy()
            return poke

        # the plain calibration: applied at Save, nothing written
        app.root.wait_window = look('cal')
        app._calibrate_scale()
        # the re-anchor's dialog: the SAME dialog, told what it serves
        app.root.wait_window = look('re')
        app._calibrate_scale(intent=gui.SCALE_INTENT_REANCHOR)
        # ... and the same pair in a MEASURING mode, where the gate block is
        # on screen and states it in full
        app.root.wait_window = look('cal_circle')
        app._calibrate_scale(mode=CIRCLE)
        app.root.wait_window = look('re_circle')
        app._calibrate_scale(mode=CIRCLE,
                             intent=gui.SCALE_INTENT_REANCHOR)
    finally:
        gui.messagebox, gui.spawn_circle = real_mb, real_spawn
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)

    # THE VERIFY MODE: the button is where the asymmetry has to live, since
    # the block that would say it in words is hidden for the line budget
    assert saw['cal']['mode'] == VERIFY and saw['re']['mode'] == VERIFY
    assert 'at Save' in saw['cal']['step'], saw['cal']
    assert 'RE-ANCHOR' not in saw['cal']['step'], saw['cal']
    assert 'RE-ANCHOR NOW' in saw['re']['step'], saw['re']
    assert 'at Save' not in saw['re']['step'], saw['re']
    # the TITLE too, in both modes, so the bar and the button agree
    for k, needle in (('cal', 'applied at Save'),
                      ('re', 'writes data.csv'),
                      ('cal_circle', 'applied at Save'),
                      ('re_circle', 'writes data.csv')):
        assert needle in saw[k]['title'], (k, saw[k]['title'])
    assert 'RE-ANCHOR' in saw['re']['title']
    assert 'RE-ANCHOR' not in saw['cal']['title']
    # NO MODE PUTS IT ON THE SCREEN ANY MORE (`#215`, operator 2026-08-07,
    # second pass). It was a 127-character paragraph opening the measuring
    # modes' gate block; the morning's trim shortened it to a tag on the round
    # header; the operator then drove all three modes and cut the tag too --
    # *"the commit warning belongs in one place, on the primary button and in
    # its confirmation, not repeated in every mode's header."*
    #
    # So the surfaces are the TITLE (asserted above, both branches, in both
    # kinds of mode), the PRIMARY BUTTON on the press that commits (below),
    # and the re-anchor CONFIRMATION (tests/test_sldea_reanchor.py). Still
    # three, and all three are places where it decides something.
    for k in ('cal', 're', 'cal_circle', 're_circle'):
        for phrase in ('NOTHING is written',
                       'WRITTEN TO data.csv IMMEDIATELY',
                       'RE-ANCHOR — WRITTEN'):
            assert phrase not in saw[k]['shown'], (k, phrase, saw[k]['shown'])
    # ... and neither branch may borrow the other's promise on the surfaces it
    # DOES have. In a measuring mode round 1's button is "Continue →" -- the
    # press that commits is the LAST round's, and it says so there
    # (test_the_second_click_banks_the_round_and_Back_undoes_it drives that).
    for k in ('cal_circle', 're_circle'):
        assert 'Continue' in saw[k]['step'], saw[k]
        assert 'RE-ANCHOR' not in saw[k]['step'], saw[k]
    assert 'writes data.csv' not in saw['cal_circle']['title'], saw
    assert 'applied at Save' not in saw['re_circle']['title'], saw


def test_the_second_click_banks_the_round_and_Back_undoes_it():
    """AUTO-ADVANCE AND ITS UNDO (operator 2026-08-06 late, `#215`).

    The operator asked for the second click to advance to the next round with
    no Continue press. That removes the only moment a bad second click could
    have been noticed before it counted, so the round just banked has to be
    recoverable: ◀ Back (and Backspace) step one round back and re-randomise
    it. Well defined at any point, because the mean is not computed until the
    last round is in.

    TWO deliberate limits are pinned here as well:

    - the LAST round does NOT auto-advance. There is no next round to advance
      to; what follows is finish(), i.e. the acceptance gate, the anchor guard
      and an anchor. Auto-advancing into that would let a stray click accept a
      scale and then meet warnings it never read -- the hazard <Return> is
      refused for.
    - a round that comes back is RE-RANDOMISED. Restoring the old rotation
      with the old clicks on it would be a correlated second look at one fit,
      which is what the blind independent rounds exist to prevent."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('two-point auto-advance and undo')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_autoadv_')
    real_mb = gui.messagebox
    saw = {}
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        gui.messagebox = _ModalSpy(real_mb, app)

        def poke(win):
            _cal_onscreen(root, win)
            p = app._cal_probe
            st = p['st']
            saw['back_label_r1'] = p['back_btn'].cget('text')
            # ---- round 1: two clicks, and the round BANKS itself ---------
            rot1 = st['rot']
            _click_at_original(app, (80.0, 120.0))
            assert len(st['pts']) == 1, st['pts']
            _click_at_original(app, (240.0, 120.0))
            saw['after_two'] = (st['round'], len(st['diams']),
                                len(st['pts']))
            saw['banked'] = list(st['diams'])
            saw['rot_changed'] = (st['rot'] != rot1)
            saw['back_label_r2'] = p['back_btn'].cget('text')
            # ---- ◀ Back: the round comes off again ----------------------
            rot2 = st['rot']
            p['back_btn'].invoke()
            saw['after_back'] = (st['round'], len(st['diams']),
                                 len(st['pts']))
            saw['rerandomised'] = (st['rot'] != rot2)
            # ---- BACKSPACE does the same thing --------------------------
            _click_at_original(app, (80.0, 120.0))
            _click_at_original(app, (240.0, 120.0))
            assert len(st['diams']) == 1, st['diams']
            win.focus_force()
            win.update()
            win.event_generate('<BackSpace>', when='now')
            win.update()
            saw['after_key'] = (st['round'], len(st['diams']))
            # ---- walk to the LAST round, which must NOT auto-advance ----
            for _ in range(4):
                if len(st['diams']) >= 4:
                    break
                _click_at_original(app, (80.0, 120.0))
                _click_at_original(app, (240.0, 120.0))
            saw['at_last'] = (st['round'], len(st['diams']))
            saw['step_last'] = p['step_btn'].cget('text')
            _click_at_original(app, (80.0, 120.0))
            _click_at_original(app, (240.0, 120.0))
            saw['last_pts'] = len(st['pts'])
            saw['last_banked'] = len(st['diams'])
            saw['alive'] = win.winfo_exists()
            saw['live'] = _cal_display(win)
            win.destroy()

        app.root.wait_window = poke
        app._calibrate_scale(mode=TWOPOINT)
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)

    # THE SECOND CLICK BANKED THE ROUND AND MOVED ON -- no button press
    assert saw['after_two'] == (2, 1, 0), saw['after_two']
    assert len(saw['banked']) == 1 and saw['banked'][0] > 0, saw['banked']
    assert saw['rot_changed'], "the next round reused the same rotation"
    # ◀ BACK took it off again and put the operator back in that round
    assert saw['after_back'] == (1, 0, 0), saw['after_back']
    assert saw['rerandomised'], ("a redone round came back with the same "
                                 "rotation, so the refit would not be "
                                 "independent")
    assert saw['after_key'] == (1, 0), saw['after_key']
    # THE LABEL NAMES THE ROUND IT LANDS ON, and its key -- an undo nobody
    # can find is not an undo, and there is no room for a paragraph
    assert 'Backspace' in saw['back_label_r1'], saw['back_label_r1']
    assert 'round 1' in saw['back_label_r1'], saw['back_label_r1']
    assert 'round 1' in saw['back_label_r2'], saw['back_label_r2']
    # THE LAST ROUND KEEPS ITS BUTTON: two points placed, nothing banked,
    # the dialog still open and no anchor taken by a click
    assert saw['at_last'] == (5, 4), saw['at_last']
    assert 'Finish' in saw['step_last'], saw['step_last']
    assert saw['last_pts'] == 2, saw['last_pts']
    assert saw['last_banked'] == 4, saw['last_banked']
    assert saw['alive'], "the last round's second click finished the set"
    # ... and it SAYS so where the operator is looking
    assert 'Finish' in saw['live'], saw['live']


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
