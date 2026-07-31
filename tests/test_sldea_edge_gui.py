#!/usr/bin/env python3
"""Review-card + window semantics for sldea_edge_gui (#171-#173, #176,
#178, #179).

The selection-highlight rule (hot_slot), the card contain-fit math
(card_geometry) and the panel-text elide are pure and tested headlessly.
The candidate-D flow -- trace Done STAGES + labels, Accept commits, a
re-trace replaces the pending polygon -- the #176 singleton guards for
Advanced.../Tune..., the #178 view-tracking card and the #179 fixed side
panel drive a real EdgeReviewApp on a synthetic run; those parts need a
Tk display and skip cleanly when one cannot be opened (headless CI
without Xvfb).

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
    for k, (tag, kv, r) in enumerate((('baseline', 0.0, 0),
                                      ('post-ramp', 3.0, 45),
                                      ('post-ramp', 6.0, 70))):
        img = np.full((240, 320), 190.0, np.float32)
        img[(xx - 160) ** 2 + (yy - 120) ** 2 <= 90 * 90] = 165.0
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


def test_aux_windows_are_singletons_not_unbounded():
    """#176: re-clicking Advanced... fronts the live dialog instead of
    stacking another; Tune... refuses a second tuner while the child
    process runs and spawns fresh only after it exits."""
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
        # Tune...: no second process while the child lives
        import subprocess as sp

        class FakeProc:
            def __init__(self):
                self.rc = None

            def poll(self):
                return self.rc

        calls = []
        orig = sp.Popen

        def fake_popen(*a, **k):
            calls.append(a)
            return FakeProc()

        sp.Popen = fake_popen
        try:
            app._open_tuner()
            assert len(calls) == 1
            app._open_tuner()                      # child still alive
            assert len(calls) == 1, "second tuner spawned"
            assert 'already running' in app.status['text']
            app._tuner_proc.rc = 0                 # child exited
            app._open_tuner()
            assert len(calls) == 2, "respawn after exit refused"
        finally:
            sp.Popen = orig
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


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
