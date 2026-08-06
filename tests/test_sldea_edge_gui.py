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
        # an exact-match anchor passes the >3% cross-check silently
        warns.clear()
        app.manual_ref = {'method': 'manual-calibration',
                          'diam_px': float(auto_px)}
        app.detect_all_sync()
        assert not warns, warns
        assert '✓' in app.status.cget('text')
        # a wildly different anchor trips it (mismatch is measured
        # against the MANUAL anchor: |auto−250|/250)
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 250.0}
        app.detect_all_sync()
        assert warns, "cross-check did not warn on a >3% mismatch"
        assert 'apart' in app.status.cget('text')
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


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
