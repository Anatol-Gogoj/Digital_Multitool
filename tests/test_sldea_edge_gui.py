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


def test_clock_readouts_separate_detection_time_from_session_time():
    """`#237`: the one toolbar clock ran from Detect until Save, so the
    moment detection finished it started counting the human's review time
    instead — destroying the only number a run can be planned with. Two
    readouts now, and both strings are pure so their wording is pinned
    without a display."""
    import sldea_edge_gui as gui
    # fmt_dur: seconds below a minute, m+s below an hour, and it ROLLS
    # OVER (the old M:SS printed a 90-minute pass as '90:00')
    assert gui.fmt_dur(0) == '0s' and gui.fmt_dur(43) == '43s'
    assert gui.fmt_dur(59) == '59s' and gui.fmt_dur(60) == '1m00s'
    assert gui.fmt_dur(134) == '2m14s'          # the issue's own example
    assert gui.fmt_dur(3599) == '59m59s' and gui.fmt_dur(3600) == '1h00m'
    assert gui.fmt_dur(7500) == '2h05m'
    assert gui.fmt_dur(-5) == '0s'              # never a negative duration
    assert gui.fmt_dur(134.9) == '2m14s'        # truncates, never rounds up
    # the detection line, three states
    assert gui.detect_readout() == 'detect: not run'
    assert gui.detect_readout(3, None) == 'detect: not run'
    # ...frozen: the frame COUNT travels with the time, so it reads as a
    # rate an operator can extrapolate to the next run
    done = gui.detect_readout(81, 134.2)
    assert done == 'detect: 81 frames in 2m14s', done
    # ...in flight: progress, and never confusable with the frozen form
    live = gui.detect_readout(12, 35.0, 81)
    assert '12/81' in live and '35s' in live and ' in ' not in live, live
    # the in-flight form must not be the WIDEST of the three, or it grows
    # the toolbar's fixed clock box on the one screen it has to hold
    # still: the progress bar beside it is the toolbar's only give
    assert len(gui.detect_readout(999, 3599.0, 999)) <= \
        len(gui.detect_readout(999, 3599.0)), 'the live form is the widest'
    # the session line is a separate string, so neither can be mistaken
    # for the other on screen
    assert gui.session_readout(312) == 'session 5m12s'
    assert 'detect' not in gui.session_readout(312)


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
            # State the view size OUTRIGHT rather than relying on the
            # canvas being unrealized. _view_size() prefers the live canvas
            # and falls back to _view_wh only at 1x1; a withdrawn root used
            # to land there, so this loop's three sizes reached _draw by
            # accident. Since 2026-08-12 the window sizes itself to its
            # layout at construction, which realizes the canvas, and the
            # fallback stopped firing -- so the case is pinned explicitly
            # and the three sizes stay meaningful.
            real_view_size = app._view_size
            app._view_size = lambda vw=vw, vh=vh: (vw, vh)
            try:
                app._draw(i, cands, chosen)
            finally:
                app._view_size = real_view_size
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


def test_detection_clock_freezes_while_the_session_clock_runs_on():
    """`#237`: ONE clock ran from ▶ Detect Edges until 💾 Save, so the
    detection time was overwritten a second after it was produced and the
    readout became a session stopwatch. Now: the detection line freezes
    when the pass ends and is repainted by nothing else; the session line
    keeps counting through Save and across a run switch; and the
    detection line resets per run, because a saved run re-opened for a
    scale-only re-anchor (`#215`) runs NO detection and the absence of a
    fresh detection time is the signal that says so."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('two clocks')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_clocks_')
    mb = _StubMB(yes=True)
    real_mb = gui.messagebox
    gui.messagebox = mb
    try:
        _fake_run(os.path.join(d, 'SLDEA_A'))
        run_b = _fake_run(os.path.join(d, 'SLDEA_B'))
        app = gui.EdgeReviewApp(root, path=run_b)
        assert app.run is not None

        def detect_txt():
            return app.detect_lbl.cget('text')

        def session_txt():
            return app.clock_lbl.cget('text')

        # BEFORE any pass: the absence is stated, not left blank, and the
        # session clock is already running (the window is open)
        assert detect_txt() == 'detect: not run', detect_txt()
        assert session_txt().startswith('session '), session_txt()

        # THE BOX HOLDS BOTH LINES AND THE WIDEST TEXT. Found by measuring
        # the real window: the toolbar row is one button tall, so the
        # fixed box inherited 25 px and clipped the session line to 4 of
        # its 21. Asked of the geometry REQUESTS, so this holds on a
        # withdrawn root -- and a box too small is exactly what a font or
        # scaling change would do to a hard-coded pair of numbers.
        box = app.detect_lbl.master
        need_h = (app.detect_lbl.winfo_reqheight()
                  + app.clock_lbl.winfo_reqheight())
        assert int(box.cget('height')) >= need_h, \
            f"clock box {box.cget('height')} px cannot show both lines"
        for txt in (gui.detect_readout(999, 3600.0),
                    gui.detect_readout(999, 3599.0, 999),
                    gui.detect_readout()):
            app.detect_lbl.config(text=txt)
            assert app.detect_lbl.winfo_reqwidth() <= int(box.cget('width')), \
                f"clock box is narrower than {txt!r}"
        app.detect_lbl.config(text=gui.detect_readout())

        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app._t0 = None
        app.detect_all_sync()
        frozen = detect_txt()
        n = len(app.frame_rows)
        assert frozen.startswith(f'detect: {n} frames in '), frozen
        first_t0 = app._t0
        assert first_t0 is not None

        # THE BUG'S OWN SHAPE: let the clock tick as if five minutes of
        # review had passed. The session line must move; the detection
        # line must be byte-identical -- it is an answer, not a stopwatch.
        app._t_session -= 300
        app._tick_clock()
        moved = session_txt()
        assert moved == 'session 5m00s', moved
        assert detect_txt() == frozen, "detection time kept counting"

        # SAVE does not stop the session clock any more: a session
        # outlives a Save (the batch cockpit saves one run and moves on)
        app.save()
        assert app._clock_on, "Save stopped the session clock"
        app._t_session -= 60
        app._tick_clock()
        assert session_txt() == 'session 6m00s', session_txt()
        assert detect_txt() == frozen, "Save rewrote the detection time"

        # A RUN SWITCH re-arms the detection line (it belonged to run B's
        # pass) and leaves the session line alone (one session, many runs)
        other = [i for i, v in enumerate(app.run_box['values'])
                 if 'SLDEA_A' in v][0]
        app.run_box.current(other)
        app._pick_run()
        assert detect_txt() == 'detect: not run', detect_txt()
        assert app._t0 is None
        app._tick_clock()
        assert session_txt() == 'session 6m00s', session_txt()

        # THE SCALE-ONLY RE-ANCHOR PATH: run B is saved and carries px, so
        # re-opening it routes to re-anchor rather than calibrate -- and
        # that path never detects, so the readout must still say so.
        back = [i for i, v in enumerate(app.run_box['values'])
                if 'SLDEA_B' in v][0]
        app.run_box.current(back)
        app._pick_run()
        assert app._scale_intent()['intent'] == gui.SCALE_INTENT_REANCHOR
        assert detect_txt() == 'detect: not run', detect_txt()

        # A SECOND PASS IS TIMED ON ITS OWN: `_t0 = _t0 or now` made every
        # later pass report the time since the FIRST one of the session
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        time.sleep(0.01)
        app.detect_all_sync()
        assert app._t0 > first_t0, "the second pass reused the first's t0"
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


# ---------------------------------------------------------------------------
# `#238` -- the How-to-use workflow panel
#
# NOTE for anyone extending these: never interpolate the panel's text into an
# assertion message. The words carry emoji and en dashes, and a failure whose
# message cannot be encoded to cp1252 replaces the real failure with a
# UnicodeEncodeError on this repo's console.
# ---------------------------------------------------------------------------

def test_no_control_is_ever_discarded_by_a_small_window():
    """The bug: Tk's packer does not clip a too-small window, it DROPS the
    widgets that do not fit -- silently, with nothing on screen to say so.

    Measured on the shipped 1150x760 default before the fix: at 900x600
    Reject, Unreview and the How-to button were gone; at 700x500 the entire
    right-hand panel went with them, so no frame could be accepted,
    rejected or traced. The window looked normal.

    Every control must stay MAPPED at every size, reachable by scrolling
    rather than deleted. `winfo_ismapped` is the assertion because it is
    exactly what the packer turns off when it discards a slave.
    """
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    d = tempfile.mkdtemp(prefix='edge_gui_small_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        controls = ['run_box', 'browse_btn', 'detect_btn', 'adv_btn',
                    'scale_btn', 'save_btn', 'info', 'cand_frame',
                    'tracker_lbl', 'accept_btn', 'reject_btn', 'prev_btn',
                    'next_btn', 'unrev_btn', 'howto_btn', 'status', 'canvas']
        for w, h in ((1600, 1000), (1150, 760), (900, 600), (700, 500),
                     (560, 420)):
            root.geometry(f'{w}x{h}')
            root.update_idletasks()
            root.update()
            gone = [n for n in controls
                    if not getattr(app, n).winfo_ismapped()]
            assert not gone, f"at {w}x{h} the packer discarded: {gone}"

        # ...and at the small end that reachability is the SCROLLBARS doing
        # it, not the layout having quietly shrunk something to nothing.
        assert app._scroll._vbar_shown, "no vertical bar on a short window"
        assert app._scroll._hbar_shown, "no horizontal bar on a narrow window"
        assert app._scroll.body.winfo_reqwidth() > root.winfo_width(), (
            "the body should keep its natural width and overflow")

        # Roomy window: the bars go away and the image viewport GROWS into
        # the space, which is the behaviour a scroll container most easily
        # breaks (content pinned at its natural size forever).
        root.geometry('1600x1000')
        root.update_idletasks()
        root.update()
        assert not app._scroll._vbar_shown and not app._scroll._hbar_shown, (
            "bars still up on a window with room to spare")
        big = app.canvas.winfo_width()
        root.geometry('900x600')
        root.update_idletasks()
        root.update()
        assert app.canvas.winfo_width() < big, (
            "the image canvas did not track the window")
    finally:
        app._cancel_pending()
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_the_window_opens_at_the_size_its_layout_asks_for():
    """1150x760 was typed in and measured too narrow: the built layout wants
    ~1319 px, so the window opened with the fixed-width side panel already
    squeezed and the progress bar rendered 11 px wide -- on the default
    geometry, on every machine, since the panel was written.

    The size is now asked of the widgets. Capped to the screen, because a
    display smaller than the layout is what the scroller is for."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    d = tempfile.mkdtemp(prefix='edge_gui_size_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        root.update_idletasks()
        root.update()
        want_w = app._scroll.body.winfo_reqwidth()
        cap_w = max(640, root.winfo_screenwidth() - 80)
        if want_w > cap_w:
            print(f"   (screen too small to check the uncapped case: "
                  f"wants {want_w}, cap {cap_w})")
        else:
            assert root.winfo_width() >= want_w, (
                f"opened at {root.winfo_width()} for a layout wanting "
                f"{want_w} -- the side panel is squeezed again")
        assert root.winfo_width() >= 1150, "never smaller than the old default"
        assert root.winfo_width() <= cap_w, "wider than the screen allows"
    finally:
        app._cancel_pending()
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_howto_text_is_one_copy_and_carries_the_three_traps():
    """`#238`: the panel's words live in ONE module constant, they contain
    the campaign loop and the three things that cost real time, and the two
    thresholds they quote are read back against the code's own defaults --
    so a settings change cannot leave the help quoting a stale number.

    Headless: the words are data, and the point of keeping them as data is
    that they are testable without a display."""
    import sldea_edge as se
    import sldea_edge_gui as gui
    assert gui.HOWTO_SECTIONS, "no help text at all"
    for heading, paras in gui.HOWTO_SECTIONS:
        assert isinstance(heading, str) and heading
        assert paras, "a heading with nothing under it"
        for p in paras:
            assert isinstance(p, str) or (
                isinstance(p, tuple) and len(p) == 2 and p[0] == 'code'), p
    t = gui.howto_text()

    # THE PROCEDURE, all seven steps, in order. Rewritten to ASD-STE100
    # 2026-08-12: the three traps moved OUT of a trailing section and INTO
    # the steps they govern, because the standard puts a warning before the
    # action it applies to -- which is also where an operator meets it.
    for n in range(1, 8):
        assert f'{n}.' in t, f"step {n} missing from the procedure"
    order = [t.index(f'{n}.') for n in range(1, 8)]
    assert order == sorted(order), "the procedure steps are out of order"

    # TRAP 1 -- wash-out frames are traced, not rejected. This is the single
    # instruction a new operator gets wrong, and the reason is that the
    # missing boundary is the frame, not a fault.
    assert 'Trace a washed-out frame' in t
    assert 'Do not reject it' in t
    assert '5.5 kV' in t
    assert 'Reject a frame only if' in t, "the narrow meaning of Reject is gone"

    # TRAP 2 -- Accept stages, Save writes. The 2026-08-06 incident stays in
    # the text on purpose: STE has no room for the anecdote that carried it,
    # so it is kept as a dated NOTE rather than dropped. It is the evidence
    # that this trap is real and not hypothetical.
    assert 'STAGES the anchor' in t
    assert '2026-08-06' in t
    assert 'Save before you close' in t

    # TRAP 3 -- the scale-only re-anchor skips detection
    assert 'no detection' in t and 're-derives every mm' in t

    # THE BLANKET CLAIM MUST CARRY ITS EXCEPTION. "does not write until
    # Save" is false for a re-anchor on a saved run, which commits data.csv
    # the moment it is confirmed (_reanchor_scale). If the sentence is ever
    # tightened into the simple, wrong version, this fails.
    assert 'until' in t and 'exception' in t, "the Save claim lost its caveat"

    # THE TWO NUMBERS. These are now INTERPOLATED into HOWTO_SECTIONS from
    # se.DEFAULT_SETTINGS, so the help cannot quote a stale default at all --
    # this assertion confirms the interpolation still reaches the rendered
    # text, rather than being the only thing standing between us and drift.
    assert f"accept_conf is {se.DEFAULT_SETTINGS['accept_conf']:g}" in t
    assert f"wrinkle_ratio is {se.DEFAULT_SETTINGS['wrinkle_ratio']:g}" in t
    assert '1.0 means no' in t, "the w baseline value is not stated"
    assert 'not a probability' in t

    # SHORT, on purpose: it has to read as help, not as documentation, and
    # it points at the manual for the rest
    assert 'digital-multitool-manual.pdf' in t
    assert len(t) < 5000, f"the panel has grown into documentation: {len(t)}"

    # EVERY on-screen control the text names is listed for the drift check
    for label in gui.HOWTO_QUOTED_CONTROLS:
        assert label in t, "a quoted control is not actually quoted"


def test_howto_panel_is_a_singleton_scrolls_and_names_live_controls():
    """`#238`: the button sits at the bottom (the status strip keeps the
    window's own bottom edge), re-clicking fronts the live panel instead of
    stacking a second one, the panel takes NO grab, it really does scroll,
    and every control it names by label is a control that still exists.

    That last one is the drift latch: `annotate.py` merely PRINTS 'no match'
    when a button is renamed, and the manual silently loses a callout. Help
    that sends an operator hunting for a button that no longer exists is
    worse than no help, so it fails here instead."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_gui_howto_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None, "synthetic run failed to load"

        # ---- the button: bottom, right, and not in the top bar ----------
        assert app.howto_btn.cget('text') == gui.HOWTO_BTN_TEXT
        assert app.howto_btn.pack_info()['side'] == 'right'
        foot = app.howto_btn.master
        assert foot.pack_info()['side'] == 'bottom'
        # The status strip must still own the bottom edge of the content,
        # and with side=bottom that is decided by PACK ORDER (each slave
        # takes the bottom of what is left), so the order is what is
        # asserted -- a withdrawn root has no computed geometry to measure.
        #
        # The slaves are the SCROLLER's body, not the root, since 2026-08-12:
        # every control moved inside the scroll container so that a small
        # window scrolls instead of silently discarding widgets. The
        # ordering rule this asserts is unchanged.
        slaves = app._scroll.body.pack_slaves()
        assert slaves.index(app.status) < slaves.index(foot), "status moved"
        assert app.status.pack_info()['side'] == 'bottom'

        # ---- singleton, and non-modal ----------------------------------
        assert app._howto_win is None
        app._howto()
        w1 = app._howto_win
        assert w1 is not None and w1.winfo_exists()
        assert root.grab_current() is None, "the help panel took a grab"
        app._howto()
        assert app._howto_win is w1, "a second panel was stacked"
        tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        assert len(tops) == 1, f"stacked dialogs: {len(tops)}"

        # ---- it scrolls: the content is taller than the viewport --------
        cv = app._howto_scroll
        root.update_idletasks()
        w1.update_idletasks()
        region = [float(v) for v in str(cv.cget('scrollregion')).split()]
        assert len(region) == 4, "no scrollregion: nothing would scroll"
        assert region[3] > 300, "the scrollregion is empty"
        assert w1.bind('<Escape>'), "Escape does not close the panel"
        assert w1.bind('<MouseWheel>'), "the wheel does not scroll the panel"
        # sized for a 1080p bench screen, and never taller than the screen
        assert w1.winfo_reqheight() <= root.winfo_screenheight()

        # ---- opening help changed nothing about the review -------------
        assert not app.results and app.manual_ref is None

        # ---- a closed panel is not a live singleton --------------------
        w1.destroy()
        app._howto()
        assert app._howto_win is not w1 and app._howto_win.winfo_exists()
        app._howto_win.destroy()

        # ---- every control the text names is a real widget label -------
        texts = []

        def walk(w):
            for ch in w.winfo_children():
                try:
                    texts.append(str(ch.cget('text')))
                except tk.TclError:
                    pass
                walk(ch)

        walk(root)
        for label in gui.HOWTO_QUOTED_CONTROLS:
            assert label in texts, ("the help names a control that no "
                                    "longer exists on screen")
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_the_cockpit_descends_into_a_campaign_wrapper_like_the_tuner():
    """`#261`: with no argument Edge Review opens on SCPI_SLDEA_DIR, which
    on the analysis PC is the campaign WRAPPER with the runs nested one
    level down. It listed nothing there while the tuner's picker listed
    thirteen, so the two tools disagreed about the same folder. Both now
    go through se.runs_parent, and an EMPTY parent is still the cockpit."""
    import sldea_edge_gui as gui
    import sldea_edge as se
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    wrapper = tempfile.mkdtemp(prefix='edge_gui_wrapper_')
    try:
        inner = os.path.join(wrapper, 'SLDEA_data (1)')
        os.makedirs(inner)
        run = _fake_run(os.path.join(inner, 'P3_1_2.5mL_20260728'))
        os.makedirs(os.path.join(wrapper, '_analysis'), exist_ok=True)
        app = gui.EdgeReviewApp(root, path=wrapper)
        assert app.parent == inner, app.parent
        assert app.rundir == run, app.rundir
        assert [str(v).split('  ')[0] for v in app.run_box['values']] == \
            ['P3_1_2.5mL_20260728']
        # the same run the tuner's launcher resolves the wrapper to: one
        # rule, so the Tune button cannot open a different run than the
        # cockpit is showing
        assert se.resolve_run(wrapper) == run
        # a wrapper with nothing under it anywhere is still the cockpit --
        # the descent may not invent a run
        barren = tempfile.mkdtemp(prefix='edge_gui_barren_')
        try:
            os.makedirs(os.path.join(barren, 'notes'))
            app2 = gui.EdgeReviewApp(root, path=barren)
            assert app2.parent == barren, app2.parent
            assert app2.run is None
            assert app2._hint == gui.HINT_PICK_RUN
        finally:
            shutil.rmtree(barren, ignore_errors=True)
    finally:
        root.destroy()
        shutil.rmtree(wrapper, ignore_errors=True)


def test_detect_edges_is_the_primary_action_and_gates_on_a_run():
    """`#216`: ▶ Detect Edges must READ as the one thing to press, and
    its affordance must double as its state.

    - it carries an accent style the plain buttons do not, and that style
      really resolves to a bold face (a style name nothing configures
      would silently render identically);
    - it is DISABLED with no run loaded — including the cockpit case, a
      parent folder holding no runs — and live once a run is picked;
    - the detect-in-flight lock and the no-run gate are ANDed, so
      _detect_ui(busy=False) on a runless app may not re-arm it (the
      regression that made the old single-writer line wrong);
    - the empty canvas carries the hint, and the hint goes away as soon
      as a review card occupies the canvas."""
    import sldea_edge_gui as gui
    import tkinter as tk
    from tkinter import ttk, font as tkfont
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_gui_primary_')
    try:
        # ---- COCKPIT MODE on an EMPTY parent: no run, no live Detect ---
        empty = os.path.join(d, 'empty_parent')
        os.makedirs(empty)
        app = gui.EdgeReviewApp(root, path=empty)
        assert app.run is None, "an empty parent must load no run"
        assert str(app.detect_btn['state']) == 'disabled', \
            "Detect was live with nothing to detect"
        assert app._tips['detect_btn'].text == gui.TIPS['detect_btn_disabled']
        assert app._hint == gui.HINT_PICK_RUN, app._hint
        # the busy lock releasing must NOT re-arm a runless button
        app._detect_ui(busy=False)
        assert str(app.detect_btn['state']) == 'disabled', \
            "_detect_ui re-armed Detect on a run-less cockpit"
        # ---- the accent is real, not just a style name ------------------
        assert str(app.detect_btn['style']) == 'Primary.TButton'
        assert str(app.browse_btn['style']) == ''      # plain, by contrast
        assert str(app.adv_btn['style']) == 'Secondary.TButton'
        assert str(app.scale_btn['style']) == 'Secondary.TButton'
        st = ttk.Style()
        fname = st.lookup('Primary.TButton', 'font')
        assert fname, "Primary.TButton configures no font"
        assert tkfont.nametofont(fname).cget('weight') == 'bold', \
            "the accent style is not bold, so it renders as a plain button"
        assert st.lookup('Primary.TButton', 'foreground') == gui.PRIMARY_FG
        # Secondary is a HOOK, not a look: the first #216 version muted it
        # grey and the operator read that as DISABLED on the first real
        # drive (2026-08-07). Stock appearance is the fix — keep it.
        # (lookup falls back through the style tree, so an unconfigured
        # style reports TButton's own value: assert equality, not empty.)
        assert (st.lookup('Secondary.TButton', 'foreground')
                == st.lookup('TButton', 'foreground')), \
            "Secondary.TButton foreground diverges from stock TButton - " \
            "the grey mute read as disabled once; keep secondary stock"
        # ...and it makes the button visibly bigger than a plain one
        probe = ttk.Button(root, text=str(app.detect_btn['text']))
        probe.update_idletasks()
        app.detect_btn.update_idletasks()
        assert (app.detect_btn.winfo_reqwidth() > probe.winfo_reqwidth()
                and app.detect_btn.winfo_reqheight()
                > probe.winfo_reqheight()), (
            app.detect_btn.winfo_reqwidth(), probe.winfo_reqwidth())
        probe.destroy()
        # ---- pick a run: Detect arms, and the hint changes with it ------
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app._populate_runs(d)
        assert app.run is not None, "the run did not load"
        assert str(app.detect_btn['state']) == 'normal'
        assert app._tips['detect_btn'].text == gui.TIPS['detect_btn']
        assert app._hint == gui.HINT_DETECT, app._hint
        assert app.canvas.find_withtag('hint'), "the hint was never drawn"
        # ONE STORY: neither the hint nor the status line may tell the
        # operator to calibrate BEFORE pressing Detect (the gate chains)
        for line in (app._hint, str(app.status['text'])):
            assert 'Detect Edges' in line, line
            assert 'then Detect' not in line, line
        # ---- mid-detect: same button, a tip that says why ---------------
        app._detect_busy = True
        app._detect_ui(busy=True)
        assert str(app.detect_btn['state']) == 'disabled'
        assert app._tips['detect_btn'].text == gui.TIPS['detect_btn_busy']
        app._detect_busy = False
        app._detect_ui(busy=False)
        assert str(app.detect_btn['state']) == 'normal'
        # ---- a card on the canvas retires the hint ----------------------
        app.detect_all_sync()
        assert app._hint is None, app._hint
        assert not app.canvas.find_withtag('hint')
        # ---- and a failed run switch puts it back -----------------------
        real_mb = gui.messagebox
        gui.messagebox = _StubMB()
        try:
            os.remove(os.path.join(run, 'data.csv'))
            app._pick_run()
        finally:
            gui.messagebox = real_mb
        assert app.run is None
        assert str(app.detect_btn['state']) == 'disabled'
        assert app._hint == gui.HINT_PICK_RUN, app._hint
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_every_reviewed_control_explains_itself_on_hover():
    """`#216`: hover help on the whole top bar and the whole review card
    -- and the two claims that are easy to get wrong.

    The 💾 Save tip must say WHY the button is grey (it blocks on the
    detection pass AND on the scale gate), and the D slot's tip must
    quote the keys that are really bound. Coverage is asserted against
    the app's live control list, so a control added without a tooltip
    fails here rather than shipping mute."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    root.withdraw()
    d = tempfile.mkdtemp(prefix='edge_gui_tips_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None, "synthetic run failed to load"
        # EVERY control the issue names carries a live tooltip
        want = ['run_box', 'browse_btn', 'detect_btn', 'adv_btn',
                'scale_btn', 'save_btn', 'accept_btn', 'reject_btn',
                'prev_btn', 'next_btn', 'unrev_btn',
                'cand0', 'cand1', 'cand2', 'trace']
        missing = [k for k in want if k not in app._tips]
        assert not missing, f"no tooltip on: {missing}"
        for k in want:
            assert app._tips[k].text.strip(), f"empty tooltip on {k}"
        # ...on the widget itself, not merely in a dict
        for widget in (app.run_lbl, app.run_box, app.browse_btn,
                       app.detect_btn, app.adv_btn, app.scale_btn,
                       app.save_btn, app.accept_btn, app.reject_btn,
                       app.prev_btn, app.next_btn, app.unrev_btn,
                       *app.cand_radios):
            assert str(widget.bind('<Enter>')).strip(), \
                f"{widget} has no hover binding"
        # the D slot quotes the keys that are ACTUALLY bound to _trace
        bound = {k for k in ('4', 'd', 'D', 't', 'T')
                 if str(root.bind(f'<Key-{k}>')).strip()}
        assert bound == {'4', 'd', 'D', 't', 'T'}, bound
        for key in ('4', 'D', 'T'):
            assert key in app._tips['trace'].text, app._tips['trace'].text
        # ...and says Done only STAGES: Accept is what commits (#172)
        assert 'Accept' in app._tips['trace'].text
        # A/B/C name their own key and refuse to oversell conf
        for k, letter in enumerate('ABC'):
            txt = app._tips[f'cand{k}'].text
            assert txt.startswith(f"Machine candidate {letter}"), txt
            assert str(k + 1) in txt, txt
        assert 'not a probability' in app._tips['cand0'].text
        # 💾 Save explains its OWN grey: the pass and the scale gate
        save_tip = app._tips['save_btn'].text
        assert str(app.save_btn['state']) == 'disabled'
        assert '▶ Detect Edges' in save_tip and '📏' in save_tip, save_tip
        assert '.bak' in save_tip, save_tip
        # the popup really renders, with that text in it
        tip = app._tips['save_btn']
        tip._show()
        try:
            assert tip._tip is not None, "no tooltip window appeared"
            labels = _widgets(tip._tip, 'label')
            assert labels and str(labels[0]['text']) == save_tip
        finally:
            tip._hide()
        assert tip._tip is None, "the tooltip did not go away"
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# `--goto ROW` -- the plot window's click-through target (`#274`)
# ---------------------------------------------------------------------------

def _fake_run_with_gaps(dirpath):
    """A run whose CSV carries snapshots with NO frame of their own.

    Real runs do: current and power are recorded per snapshot while
    frames are not, so the plot window can legitimately point at a row
    that was never photographed. Rows 0, 2, 4 carry frames; 1, 3, 5 do
    not -- so frame_rows == [0, 2, 4]."""
    d = _fake_run(dirpath)
    path = os.path.join(d, 'data.csv')
    with open(path, newline='') as f:
        rows = list(csv.DictReader(f))
    cols = list(rows[0].keys())
    out = []
    for r in rows:
        out.append(r)
        blank = {c: '' for c in cols}
        blank['tag'] = 'telemetry'
        blank['snapshot'] = str(len(out) + 1)
        out.append(blank)
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    return d


def test_goto_parses_without_swallowing_the_run_path():
    """`#274`: `--goto ROW` consumes its VALUE. The old parser took the
    first non-`--` argument as the path, so an unconsumed '7' would have
    become the run to open."""
    import sldea_edge_gui as gui
    assert gui.parse_args([]) == (None, False, None)
    assert gui.parse_args(['C:\\runs\\P3_1']) == ('C:\\runs\\P3_1',
                                                  False, None)
    assert gui.parse_args(['C:\\runs\\P3_1', '--goto', '7']) == (
        'C:\\runs\\P3_1', False, 7)
    assert gui.parse_args(['--goto', '7', 'C:\\runs\\P3_1']) == (
        'C:\\runs\\P3_1', False, 7)
    assert gui.parse_args(['--goto=7', 'r']) == ('r', False, 7)
    # existing flags are untouched, and the two compose
    assert gui.parse_args(['r', '--auto']) == ('r', True, None)
    assert gui.parse_args(['r', '--auto', '--goto', '3']) == ('r', True, 3)
    assert gui.parse_args(['r', '--goto', '0'])[2] == 0     # not falsy-None


def test_goto_junk_never_costs_the_operator_the_window():
    """A shortcut that cannot be honoured must still open the program --
    and must not leave its own argument lying around to be mistaken for
    the run path."""
    import sldea_edge_gui as gui
    for junk in ('abc', '', '3.5', '12x'):
        path, auto, goto = gui.parse_args(['R', '--goto', junk])
        assert goto is None, junk
        assert path == 'R', (junk, path)      # the junk is consumed
    # ...and a trailing --goto with nothing after it
    assert gui.parse_args(['R', '--goto']) == ('R', False, None)
    # a value that LOOKS LIKE A FLAG is left alone -- sldea_plot's rule
    # for its own valued flags. `--goto --auto` is a --goto with no value
    # and an --auto, not a swallowed --auto.
    assert gui.parse_args(['R', '--goto', '--auto']) == ('R', True, None)


def test_goto_lands_on_the_frame_that_shows_that_data_row():
    """The mapping is `frame_rows` -- the rows that HAVE a frame file --
    the rule `#255` documented when 0-based report rows met 1-based GUI
    frames and mis-targeted a trace by one."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('edge review')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_goto_')
    try:
        run = _fake_run_with_gaps(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run, goto=2)
        assert app.frame_rows == [0, 2, 4], app.frame_rows
        assert app._current() == 2, 'did not land on the requested row'
        assert app.pos == 1, 'landed on the wrong FRAME for that row'
        assert 'frame 2/3' in app.status.cget('text'), app.status.cget('text')
        assert 'data row 2' in app.status.cget('text')
        # every framed row is reachable, and the frame number is
        # frame_rows.index(row) + 1 -- nothing else
        for want_pos, row in enumerate(app.frame_rows):
            assert app.goto_row(row) == row
            assert app.pos == want_pos and app._current() == row
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_goto_a_row_with_no_frame_lands_next_door_and_says_so():
    """Refusing throws away a click that meant something; silently
    landing on frame 1 is a wrong answer that looks like a right one."""
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('edge review')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_goto_gap_')
    try:
        run = _fake_run_with_gaps(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.frame_rows == [0, 2, 4]
        # row 1 sits between frames 0 and 2 -- ties go to the LOWER row
        assert app.goto_row(1) == 0
        txt = app.status.cget('text')
        assert 'no frame of its own' in txt and 'nearest is row 0' in txt
        assert 'data row 1' in txt
        # row 3 likewise, and rows off both ends clamp to the end frames
        assert app.goto_row(3) == 2
        assert app.goto_row(99) == 4 and app.pos == 2
        assert app.goto_row(-5) == 0 and app.pos == 0
        assert 'nearest is row' in app.status.cget('text')
        # a run with no frames at all says so instead of raising
        app.frame_rows = []
        assert app.goto_row(0) is None
        assert 'no frames' in app.status.cget('text')
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# run health strip (2026-10-02) and the capture notes Save used to erase
# ---------------------------------------------------------------------------

def test_run_health_words_put_stop_first_and_never_lean_on_colour():
    """The strip's wording is pure, so it is pinned without a display:
    STOP leads the canvas hint, a run with no STOP starts exactly as it
    always did, and every level is a symbol AND a word (the colour behind
    the mark only repeats them)."""
    import sldea_edge as se
    import sldea_edge_gui as gui
    import sldea_plot
    stop = {'level': 'stop', 'code': 'image_flat',
            'text': 'The baseline picture is blank.'}
    warn = {'level': 'warn', 'code': 'kv_missing',
            'text': 'No measured voltage on 3 of 7 powered frames.'}
    note = {'level': 'info', 'code': 'kv_sign', 'text': 'A note.'}
    assert gui.health_counts([]) == 'nothing found'
    assert gui.health_counts([warn]) == '1 warning'
    assert gui.health_counts([stop, warn, warn, note]) == \
        '1 STOP, 2 warnings, 1 note'
    # no STOP: the hint is HINT_DETECT word for word
    assert gui.health_hint([]) == gui.HINT_DETECT
    assert gui.health_hint([warn, note]) == gui.HINT_DETECT
    assert gui.health_hint(None) == gui.HINT_DETECT
    # a STOP: it is the FIRST thing on the canvas, behind its mark, and
    # 'press Detect to start' is not printed under 'cannot be measured'
    hint = gui.health_hint([stop, warn])
    assert hint.startswith(gui.HEALTH_MARKS['stop'] + ': ' + stop['text'])
    assert warn['text'] not in hint and gui.HINT_DETECT not in hint
    assert hint.endswith(gui.HINT_AFTER_STOP)
    assert 'Detect Edges' in gui.HINT_AFTER_STOP     # advice, not a lock
    # ...and it says what the button will DO on such a run, not that it
    # "still works": the scale gate opens on the hand measurement the
    # STOP has just told the student not to make
    assert 'measure the scale by hand' in gui.HINT_AFTER_STOP
    assert 'frames folder' in gui.HINT_AFTER_STOP
    assert 'still works' not in gui.HINT_AFTER_STOP
    # the same STOP lines lead the scale dialog's banner
    assert gui.health_stops(None) == []
    assert gui.health_stops([warn, note]) == []
    assert gui.health_stops([stop, warn]) == [
        gui.HEALTH_MARKS['stop'] + ': ' + stop['text']]
    assert hint.startswith(gui.health_stops([stop, warn])[0])
    # ...and under a STOP that banner does not ORDER a hand measurement:
    # it says what the window can do, points at the STOP and names the
    # way out. Without a STOP the sentence is the one it always was.
    assert gui.GATE_NO_FIT.endswith('measure the disc BY HAND.')
    assert gui.GATE_NO_FIT not in gui.GATE_NO_FIT_STOP
    for words in ('NO automatic fit on this run', 'nothing to verify',
                  'BY HAND', 'Read the STOP above first', 'Cancel (Esc)'):
        assert words in gui.GATE_NO_FIT_STOP, words
    # a short screen may shorten the strip, never to less than a header
    # and something under it
    assert 2 <= gui.HEALTH_MIN_LINES < gui.HEALTH_LINES
    assert 300 <= gui.VIEW_MIN_H < gui.VIEW_H
    # the help panel names the strip, and its STOP mark as it is drawn
    assert f"{gui.HEALTH_TITLE} strip" in gui.howto_text()
    assert gui.HEALTH_MARKS['stop'] in gui.howto_text()
    # one mark per level, each a symbol plus a word, all different
    assert set(gui.HEALTH_MARKS) == set(se.HEALTH_LEVELS)
    marks = list(gui.HEALTH_MARKS.values()) + [gui.HEALTH_OK_MARK]
    assert len(set(marks)) == len(marks)
    for mark in marks:
        symbol, word = mark.split(' ', 1)
        assert symbol and word.isalpha() and not symbol.isalpha(), mark
    # colours come from the Paul Tol bright scheme the plots use
    assert set(gui.HEALTH_COLORS) == set(se.HEALTH_LEVELS) | {'ok'}
    tol = {c.lower() for c in sldea_plot.TOL_BRIGHT}
    for level, colour in gui.HEALTH_COLORS.items():
        assert colour.lower() in tol, (level, colour)
    assert len(set(gui.HEALTH_COLORS.values())) == len(gui.HEALTH_COLORS)


def _strip_text(app):
    # without the 'more below' cue: whether it is on the header depends
    # on the strip's width, which is not what these tests are about
    return app.health_txt.get('1.0', 'end-1c').replace(
        f"   {gui_more()}", '')


def gui_more():
    import sldea_edge_gui as gui
    return gui.HEALTH_MORE


def test_run_health_strip_shows_on_pick_and_blocks_nothing():
    """U20 / U51: the 2026-10-01 run was calibrated by hand on a blank
    picture because nothing on screen said the picture was blank. Picking
    a run now says so at once, STOP first, in the strip and on the empty
    canvas, and it stays ADVICE: Detect and Save work as before."""
    import cv2
    import sldea_edge as se
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('run health strip')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_health_')
    mb = _StubMB(yes=True)
    real_mb = gui.messagebox
    gui.messagebox = mb
    app = None
    try:
        good = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        blank = _fake_run(os.path.join(d, 'SLDEA_20260102_000000'))
        cv2.imwrite(os.path.join(blank, 'frames',
                                 'SLDEA_s00_00.00kV_baseline.png'),
                    np.full((240, 320), 67, np.uint8))
        app = gui.EdgeReviewApp(root, path=blank)
        assert app.run is not None, "synthetic run failed to load"
        root.update_idletasks()
        # the strip is a real, packed part of the window under the toolbar
        assert app.health_txt.winfo_manager() == 'pack'
        assert int(app.health_txt.cget('height')) == gui.HEALTH_LINES
        assert str(app.health_txt.cget('state')) == 'disabled'
        codes = [(it['level'], it['code']) for it in app.health]
        assert codes[0] == ('stop', 'image_flat'), codes
        text = _strip_text(app)
        assert text.startswith(f"{gui.HEALTH_TITLE}: 1 STOP"), text
        assert gui.HEALTH_ADVICE in text
        # STOP is stated before any warning, each behind its text mark
        at_stop = text.index(gui.HEALTH_MARKS['stop'])
        at_warn = text.index(gui.HEALTH_MARKS['warn'])
        assert 0 < at_stop < at_warn, (at_stop, at_warn)
        assert 'The baseline picture is blank' in text
        # ...and the mark, not only the sentence, carries the level tag
        ranges = app.health_txt.tag_ranges('stop')
        assert ranges and gui.HEALTH_MARKS['stop'] in \
            app.health_txt.get(ranges[0], ranges[1])
        # the empty canvas leads with the STOP sentence
        assert app._hint.startswith(gui.HEALTH_MARKS['stop']), app._hint
        assert 'The baseline picture is blank' in app._hint
        assert app.canvas.find_withtag('hint'), "the hint was never drawn"
        assert 'run health: 1 STOP' in app.info.cget('text')
        # ADVISORY ONLY: Detect is armed, detection runs, Save arms
        assert str(app.detect_btn['state']) == 'normal'
        # WHAT THE HINT PROMISES IS WHAT DETECT DOES (review 2026-10-02):
        # with no anchor the press goes to the scale gate, and on this
        # picture the gate has no automatic fit to verify, so it opens on
        # a hand measurement
        assert app._hint.endswith(gui.HINT_AFTER_STOP), app._hint
        gate = []
        app._calibrate_scale = lambda **kw: gate.append(kw)
        try:
            app.detect()
        finally:
            del app._calibrate_scale
        assert gate == [{'then_detect': True}], gate
        assert app._auto_disc() is None
        assert se.cal_open_mode(app._auto_disc()) != se.CAL_MODE_VERIFY
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app.detect_all_sync()
        assert str(app.save_btn['state']) == 'normal'
        assert app.health and _strip_text(app) == text, \
            "the strip belongs to the run, not to the pass"
        app.save()
        assert 'saved' in app.status.cget('text'), app.status.cget('text')
        assert not mb.errors, mb.errors

        # a run with a usable picture: no STOP, the usual hint, and the
        # strip is the SAME HEIGHT (content changes, layout does not)
        app._populate_runs(good)
        root.update_idletasks()
        assert app.rundir == good
        assert not [it for it in app.health if it['level'] == 'stop']
        assert gui.HEALTH_MARKS['stop'] not in _strip_text(app)
        assert app._hint == gui.HINT_DETECT, app._hint
        assert int(app.health_txt.cget('height')) == gui.HEALTH_LINES
        # the fixture has no electrical readings, and the strip says so
        assert gui.HEALTH_MARKS['warn'] in _strip_text(app)

        # nothing wrong at all -> the OK line, with its own mark
        app._show_health([])
        assert gui.HEALTH_OK_MARK in _strip_text(app)
        assert 'nothing found' in _strip_text(app)
        # no run loaded -> the strip says that, and holds no verdict
        app._show_health(None)
        assert app.health is None
        assert _strip_text(app) == \
            f"{gui.HEALTH_TITLE}: {gui.HEALTH_NO_RUN}"

        # the check itself failing costs the advice, never the pick
        real = se.run_health

        def boom(*a, **k):
            raise RuntimeError('health exploded')

        se.run_health = boom
        try:
            app._populate_runs(good)
        finally:
            se.run_health = real
        assert app.run is not None and app.rundir == good
        assert [it['code'] for it in app.health] == ['health_failed']
        assert str(app.detect_btn['state']) == 'normal'
        assert app._hint == gui.HINT_DETECT

        # a run that fails to LOAD leaves no verdict behind: the strip
        # held the previous run's items a moment ago, and they must not
        # stay on screen under the new run's name
        assert app.health and gui.HEALTH_MARKS['info'] in _strip_text(app)
        real_load = se.load_run

        def no_load(*a, **k):
            raise OSError('disk gone')

        se.load_run = no_load
        try:
            app._populate_runs(blank)
        finally:
            se.load_run = real_load
        assert app.run is None and app.health is None
        assert _strip_text(app) == \
            f"{gui.HEALTH_TITLE}: {gui.HEALTH_NO_RUN}"
        assert app._hint == gui.HINT_PICK_RUN, app._hint
    finally:
        gui.messagebox = real_mb
        if app is not None:
            app._cancel_pending()
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_auto_holds_its_detect_press_on_a_stop_run_and_says_why():
    """Decision 16 (2026-10-03). The strip is advice and locks no button,
    but the --auto launch's own 300 ms Detect press is held back when
    Run health holds a STOP: the window opens, the STOP leads the strip
    and the canvas, the canvas says that nothing was started and why,
    and the Detect button is live for a hand press. A run without a
    STOP is pressed exactly as before. (Review 2026-10-02 had kept the
    press on a STOP run pending this decision.)"""
    import cv2
    import sldea_edge_gui as gui
    pressed = []
    real_detect = gui.EdgeReviewApp.detect
    gui.EdgeReviewApp.detect = lambda self: pressed.append(self.rundir)
    d = tempfile.mkdtemp(prefix='edge_gui_auto_')
    try:
        good = _fake_run(os.path.join(d, 'good', 'SLDEA_20260101_000000'))
        blank = _fake_run(os.path.join(d, 'blank', 'SLDEA_20260102_000000'))
        cv2.imwrite(os.path.join(blank, 'frames',
                                 'SLDEA_s00_00.00kV_baseline.png'),
                    np.full((240, 320), 67, np.uint8))
        for run in (blank, good):
            root = _tk_root_or_skip('auto over a stop')
            if root is None:
                return
            app = None
            try:
                app = gui.EdgeReviewApp(root, path=run, auto=True)
                stops = [it for it in app.health if it['level'] == 'stop']
                assert bool(stops) == (run == blank), (run, app.health)
                end = time.time() + 0.7          # past the 300 ms timer
                while time.time() < end:
                    root.update()
                    time.sleep(0.02)
                assert str(app.detect_btn['state']) == 'normal'
                if run == blank:
                    # held: no press, and the canvas says so, STOP first
                    assert pressed == [], (run, pressed)
                    assert gui.HEALTH_MARKS['stop'] in _strip_text(app)
                    assert app._hint.startswith(gui.HEALTH_MARKS['stop'])
                    assert gui.HINT_AUTO_HELD in app._hint, app._hint
                    assert app._hint.endswith(gui.HINT_AFTER_STOP)
                    assert app.status.cget('text') == gui.AUTO_HELD_TEXT
                    # the words: what did not happen, why, what still can
                    for words in ('NOT started', 'STOP', 'by hand',
                                  'Detect Edges'):
                        assert words in gui.HINT_AUTO_HELD, words
                    # the button itself is live: a press on the WIDGET
                    # goes through its own command (not a direct call,
                    # which the patch above could not fail)
                    app.detect_btn.invoke()
                    assert pressed == [run], (run, pressed)
                    # the status line names the auto-process, not the
                    # command-line flag (review 2026-10-04)
                    assert gui.AUTO_HELD_TEXT.startswith('Auto-process')
                    assert '--auto' not in gui.AUTO_HELD_TEXT
                else:
                    assert pressed == [run], (run, pressed)
                    assert app._hint == gui.HINT_DETECT, app._hint
            finally:
                if app is not None:
                    app._cancel_pending()
                root.destroy()
            del pressed[:]
        # the hold is the --auto launch's alone: the same STOP run opened
        # by hand reads as it did (no 'NOT started' line), and without a
        # STOP the auto flag changes nothing in the hint
        root = _tk_root_or_skip('stop run by hand')
        if root is None:
            return
        app = None
        try:
            app = gui.EdgeReviewApp(root, path=blank)
            assert app._hint.startswith(gui.HEALTH_MARKS['stop'])
            assert gui.HINT_AUTO_HELD not in app._hint, app._hint
            assert pressed == []
        finally:
            if app is not None:
                app._cancel_pending()
            root.destroy()
        assert gui.health_hint([], auto_held=True) == gui.HINT_DETECT
        warn = [{'level': 'warn', 'code': 'x', 'text': 'y'}]
        assert gui.health_hint(warn, auto_held=True) == gui.HINT_DETECT
    finally:
        gui.EdgeReviewApp.detect = real_detect
        shutil.rmtree(d, ignore_errors=True)


# The notes decision 17 writes (the four the corpus produces, measured
# 2026-10-03, and the trip texts), as the review card receives them.
_CARD_NOTES = {
    'Assctuator row 1': (
        'monitor log: current up to 112 uA from rest for 0.5 s from 1.5 s '
        'into the run (0.15 to 0.20 kV, 2 samples)'),
    'Assctuator row 3': (
        'monitor log: current off-screen for 12.9 s from 36.6 s into the '
        'run (0.66 to 1.00 kV, 24 samples, to the end of the log)'),
    'Assctuator2 row 17': (
        'monitor log: current off-screen for 1.7 s from 248.4 s into the '
        'run (4.42 to 4.50 kV, 4 samples)'),
    'SquareStack-1 row 1': (
        'monitor log: current up to 800 uA from rest for 352.7 s from '
        '7.2 s into the run (0.36 to 6.00 kV, 636 samples, 267 off-screen, '
        'to the end of the log)'),
    'sentinel advisory': (
        "watchdog trip not confirmed: the reading that tripped it was the "
        "off-screen sentinel (telemetry.csv)"),
    'two notes on one row': (
        'collapse? area -36% (no current signature); monitor log: current '
        'off-screen for 12.9 s from 36.6 s into the run (0.66 to 1.00 kV, '
        '24 samples, to the end of the log)'),
    'flag: trip': 'breakdown? watchdog trip (I -240uA, telemetry.csv)',
    'flag: trip, cell': ('breakdown? watchdog trip (frame read -16uA, trip '
                         'reading not on file)'),
    'flag: trip, nothing': 'breakdown? watchdog trip (reading not on file)',
}
_CARD_SHORT = {
    'Assctuator row 1': ('monitor log: from 1.5 s for 0.5 s, 0.15 to 0.20 '
                         'kV, up to 112 uA, 2 samples'),
    'Assctuator row 3': ('monitor log: 36.6 s to the end (12.9 s), 0.66 to '
                         '1.00 kV, off-screen, 24 samples'),
    'Assctuator2 row 17': ('monitor log: from 248.4 s for 1.7 s, 4.42 to '
                           '4.50 kV, off-screen, 4 samples'),
    'SquareStack-1 row 1': ('monitor log: 7.2 s to the end (352.7 s), 0.36 '
                            'to 6.00 kV, up to 800 uA, 636 samples, 267 '
                            'off-screen'),
    'two notes on one row': ('collapse? area -36% (no current signature); '
                             'monitor log: 36.6 s to the end (12.9 s), '
                             '0.66 to 1.00 kV, off-screen, 24 samples'),
}


def test_the_card_cuts_a_long_note_to_its_box_and_tips_the_full_text():
    """Review 2026-10-04 of decision 17. The info panel is a fixed box of
    INFO_LINES text lines (#179: a flag changes content, never layout),
    and every monitor-log note of the corpus needed six, so the card
    showed half a sentence and never the kV or the counts. Measured
    here on the real label at its own font: the long forms do not fit;
    wrap_lines counts lines exactly as Tk lays them out; the card's
    line for every note fits the box, in the short words of
    se.short_note (time, kV, what the current did, counts) and cut
    with an ellipsis only past that; whatever the card does not carry
    whole is the info panel's tooltip, which a frame without a note
    clears; and the label never changes height."""
    import random
    import sldea_edge as se
    import sldea_edge_gui as gui
    import tkinter as tk
    root = _tk_root_or_skip('card note fit')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_card_note_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        assert app.run is not None, "synthetic run failed to load"
        app.detect_all_sync()
        meas = app._info_font.measure
        assert str(app.info.cget('font')) == str(app._info_font)
        # a probe drawn with the info label's font and wrap says how many
        # lines a text really takes
        probe = tk.Label(root, font=app._info_font, justify='left',
                         anchor='nw', wraplength=gui.INFO_WRAP)
        one = tk.Label(root, font=app._info_font, text='x')
        one.update_idletasks()
        lsp = app._info_font.metrics('linespace')
        pad = one.winfo_reqheight() - lsp

        def tk_lines(text):
            probe.config(text=text)
            probe.update_idletasks()
            return round((probe.winfo_reqheight() - pad) / lsp)

        fixed = ("frame 4/4   step 2 [post-ramp]\n"
                 "nominal 1.0 kV   measured 0.1695 kV   — µA\n"
                 "state: needs review")
        assert tk_lines(fixed) == 3
        # the review's finding: the long forms overflow the box
        for name in ('Assctuator row 3', 'SquareStack-1 row 1'):
            assert tk_lines(fixed + '\nⓘ ' + _CARD_NOTES[name]) \
                > gui.INFO_LINES, name
        # wrap_lines is Tk's count, on these texts and on word soups
        soup = (fixed + ' ' + ' '.join(_CARD_NOTES.values())).split(' ')
        rng = random.Random(7)
        texts = [fixed + '\nⓘ ' + n for n in _CARD_NOTES.values()]
        texts += [' '.join(rng.choice(soup) for _ in range(rng.randint(1, 30)))
                  for _ in range(120)]
        for text in texts:
            assert gui.wrap_lines(text, gui.INFO_WRAP, meas) == tk_lines(text), \
                text
        # the short grammar on the corpus notes, token by token
        for name, want in _CARD_SHORT.items():
            assert se.short_note(_CARD_NOTES[name]) == want, name
        for name in ('sentinel advisory', 'flag: trip'):
            assert se.short_note(_CARD_NOTES[name]) == _CARD_NOTES[name]
        # on the card: every note fits the box, the label keeps its
        # height, and the tip holds the full text exactly when the card
        # does not
        j = app.frame_rows[2]
        app.pos = app.frame_rows.index(j)
        app._show()
        root.update_idletasks()
        info_h = app.info.winfo_reqheight()
        assert 'info' in app._tips and app._tips['info'].text == ''
        for name, note in _CARD_NOTES.items():
            app.flags.pop(j, None)
            app.advisories.pop(j, None)
            if name.startswith('flag'):
                app.flags[j] = note
            else:
                app.advisories[j] = note
            app._show()
            root.update_idletasks()
            text = app.info.cget('text')
            assert tk_lines(text) <= gui.INFO_LINES, (name, text)
            assert app.info.winfo_reqheight() == info_h, name
            line = text.split('\n')[-1]
            mark = '⚠' if name.startswith('flag') else 'ⓘ'
            assert line.startswith(mark + ' '), (name, line)
            tip = app._tips['info'].text
            if line == f"{mark} {note}":
                assert tip == '', (name, tip)
            else:
                assert tip == note, (name, tip)
                assert line.endswith('…') or line[2:] == se.short_note(note)
            if name in ('Assctuator row 1', 'Assctuator row 3',
                        'Assctuator2 row 17', 'SquareStack-1 row 1'):
                # the time and the kV lead the short form, so they are
                # on the card whatever the font cuts off the tail
                when, kv = _CARD_SHORT[name].split(', ')[:2]
                assert kv.endswith('kV') and kv in line, (name, line)
                assert when in line, (name, line)
        # the state line wrapping (a staged D) takes a line from the note:
        # the note yields and the box still holds
        tri = np.array([[10, 10], [100, 10], [100, 100]], np.int32)
        app.traces[j] = {
            'method': 'manual-trace', 'conf': 1.0, 'chosen_by': 'user',
            'area_px': 1000.0, 'diam_px': 35.7, 'cx': 50.0, 'cy': 50.0,
            'contour': tri, 'solidity': 1.0, 'spread_pct': 0.0,
            'ci85_pct': None, 'wrinkle': None, 'n_points': 3,
            'trace_points': [(10.0, 10.0), (100.0, 10.0), (100.0, 100.0)],
            'snapped': False}
        app.flags.pop(j, None)
        app.advisories[j] = _CARD_NOTES['SquareStack-1 row 1']
        app._show()
        root.update_idletasks()
        text = app.info.cget('text')
        assert 'staged D NOT committed' in text
        assert tk_lines(text) <= gui.INFO_LINES, text
        assert app.info.winfo_reqheight() == info_h
        assert app._tips['info'].text == _CARD_NOTES['SquareStack-1 row 1']
        del app.traces[j]
        # a frame without a note clears the tip
        app.advisories.pop(j, None)
        app._show()
        assert app.info.cget('text').count('\n') == 2
        assert app._tips['info'].text == ''
        # fit_lines on its own: whole when it fits, cut by words past that
        assert gui.fit_lines('a b c', 1000, 1, meas) == 'a b c'
        long = ' '.join(['word'] * 60)
        cut = gui.fit_lines(long, gui.INFO_WRAP, 2, meas)
        assert cut.endswith('…') and cut != long
        assert gui.wrap_lines(cut, gui.INFO_WRAP, meas) == 2
        assert gui.wrap_lines(cut[:-1] + ' word' + '…', gui.INFO_WRAP,
                              meas) == 3
    finally:
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_the_health_strip_adds_its_height_to_the_window_not_to_the_image():
    """Review 2026-10-02: on the old 760 px floor the strip's 85 px came
    straight out of the review canvas (563 px tall against 648 before the
    strip existed), on every run and for the whole review. The floor now
    grows by the strip, so the image keeps its height; what the strip
    SAYS never moves the image, however many lines it holds; and when it
    holds more than it shows, the header says so."""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    d = tempfile.mkdtemp(prefix='edge_gui_strip_h_')
    app = None

    def settle():
        for _ in range(3):
            root.update_idletasks()
            root.update()

    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        settle()
        strip_h = app._health_box.winfo_reqheight()
        body_h = app._scroll.body.winfo_reqheight()
        assert strip_h >= 40, strip_h         # HEALTH_LINES lines of text
        want_h = max(body_h, 760 + strip_h)
        cap_h = max(480, root.winfo_screenheight() - 120)
        if want_h > cap_h:
            print(f"   (screen too small to check the uncapped case: "
                  f"wants {want_h}, cap {cap_h})")
        else:
            # a window manager may round the request by a pixel or two;
            # the strip this is about is some 80 px
            assert abs(root.winfo_height() - want_h) <= 4, (
                f"opened {root.winfo_height()} px tall for a layout "
                f"wanting {want_h}")
            # what the image had to spare under the 760 floor before the
            # strip existed is still the image's
            slack = max(0, 760 - (body_h - strip_h))
            assert app.canvas.winfo_height() >= gui.VIEW_H + slack - 2, (
                app.canvas.winfo_height(), gui.VIEW_H, slack)

        def header():
            return app.health_txt.get('1.0', '1.end')

        # the content changes, the image does not move
        h0 = app.canvas.winfo_height()
        many = [{'level': 'warn', 'code': f'c{k}',
                 'text': 'A sentence long enough to fill a line. ' * 4}
                for k in range(8)]
        app._show_health(many)
        settle()
        assert app.canvas.winfo_height() == h0
        assert int(app.health_txt.cget('height')) == gui.HEALTH_LINES
        # more lines than the strip shows: the header says to scroll
        assert header().endswith(gui.HEALTH_MORE), header()
        ranges = app.health_txt.tag_ranges('more')
        assert ranges and gui.HEALTH_MORE in \
            app.health_txt.get(ranges[0], ranges[1])
        assert str(app.health_txt.cget('state')) == 'disabled'
        # everything fits: no cue, and still the same image
        app._show_health([])
        settle()
        assert app.canvas.winfo_height() == h0
        assert gui.HEALTH_MORE not in app.health_txt.get('1.0', 'end-1c')
        assert not app.health_txt.tag_ranges('more')
        # the cue is painted once, not once per repaint
        app._show_health(many)
        app._health_more_cue()
        app._health_more_cue()
        settle()
        assert app.health_txt.get('1.0', 'end-1c').count(
            gui.HEALTH_MORE) == 1
    finally:
        if app is not None:
            app._cancel_pending()
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_a_short_screen_gets_a_shorter_strip_and_the_whole_image():
    """Review 2026-10-02: with the screen height forced to 768 the window
    is capped at 648 px, the page with the five-line strip asked 757, and
    the review canvas ended 55 px under the window's bottom edge (main
    shows it whole). Frames are drawn to fit the canvas, so a tenth of
    every picture was hidden unless the page was scrolled, which scrolls
    the strip and the toolbar away.

    On such a screen the strip now gives lines back (never fewer than
    HEALTH_MIN_LINES) and the canvas asks for a little less, so the whole
    image is inside the window and above the page's own horizontal bar,
    and the page is no taller than it was before the strip existed.
    Decided once per window: the strip still does not change height with
    what it says.

    Three forced heights, because on the analysis PC they take three
    different paths (the assertions do not assume which):
      864 (1080p at 125 % scaling)  the strip alone gives enough back
                                    and the whole page fits, status line
                                    included, as it does on main
      768                           the strip and the canvas both give
      720                           the page is still taller than the
                                    window (it is on main too), so the
                                    image must also clear the page's
                                    horizontal bar"""
    import sldea_edge_gui as gui
    import tkinter as tk
    try:
        probe = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    real_h = probe.winfo_screenheight()
    probe.destroy()
    real_sh = tk.Misc.winfo_screenheight
    d = tempfile.mkdtemp(prefix='edge_gui_short_')
    run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))

    def case(forced, full):
        """Open the window with the screen height forced. `full` is the
        (page, strip) height of a window with room for everything, or
        None to measure exactly that and return it."""
        root = tk.Tk()
        app = None

        def settle():
            for _ in range(3):
                root.update_idletasks()
                root.update()

        try:
            tk.Misc.winfo_screenheight = lambda self: forced
            app = gui.EdgeReviewApp(root, path=run)
            settle()
            body_h = app._scroll.body.winfo_reqheight()
            lines = int(app.health_txt.cget('height'))
            asked = int(app.canvas.cget('height'))
            if full is None:
                assert lines == gui.HEALTH_LINES, lines
                assert asked == gui.VIEW_H, asked
                return body_h, app._health_box.winfo_reqheight()
            cap_h = forced - 120
            if full[0] <= cap_h:
                print(f"   (skipped {forced}: the page fits this screen "
                      f"with the whole strip)")
                return None
            assert abs(root.winfo_height() - cap_h) <= 4, (
                forced, root.winfo_height())
            assert gui.HEALTH_MIN_LINES <= lines < gui.HEALTH_LINES, (
                forced, lines)
            # THE STRIP COSTS THE PAGE NOTHING HERE: the page is no
            # taller than the window, or than it was without the strip
            old_page = full[0] - full[1]
            assert body_h <= max(cap_h, old_page), (
                forced, body_h, cap_h, full)
            # THE WHOLE IMAGE CANVAS IS ON SCREEN: inside the page's
            # viewport, which ends above the scroller's horizontal bar,
            # and so inside the window
            view = app._scroll._canvas
            view_top = view.winfo_rooty()
            view_bottom = view_top + view.winfo_height()
            top = app.canvas.winfo_rooty()
            bottom = top + app.canvas.winfo_height()
            assert view_top <= top and bottom <= view_bottom, (
                f"screen {forced}: canvas y {top}..{bottom}, viewport "
                f"{view_top}..{view_bottom}")
            assert bottom <= root.winfo_rooty() + root.winfo_height()
            assert app.canvas.winfo_height() >= gui.VIEW_MIN_H, (
                forced, app.canvas.winfo_height())
            # the strip is whole too, and sits above the image
            s_top = app.health_txt.winfo_rooty()
            s_bottom = s_top + app.health_txt.winfo_height()
            assert view_top <= s_top and s_bottom <= top, (
                forced, s_top, s_bottom, top)
            # no control was dropped to make the room
            for name in ('run_box', 'detect_btn', 'save_btn', 'accept_btn',
                         'reject_btn', 'howto_btn', 'status', 'canvas'):
                assert getattr(app, name).winfo_ismapped(), (forced, name)
            if old_page <= cap_h:
                # where the page fitted before the strip, it fits now,
                # status line included
                st_bottom = (app.status.winfo_rooty()
                             + app.status.winfo_height())
                assert body_h <= cap_h, (forced, body_h, cap_h)
                assert st_bottom <= view_bottom, (
                    forced, st_bottom, view_bottom)
            # THE IMAGE GAVE BACK NO MORE THAN WAS OWED. The strip pays
            # first; a canvas that asks for less than VIEW_H paid the
            # rest, and then the page is exactly as tall as the window
            # or as it was before the strip, or the image ends at the
            # bottom of the view (its own 4 px of padding above it)
            if gui.VIEW_MIN_H < asked < gui.VIEW_H:
                assert (abs(body_h - max(cap_h, old_page)) <= 2
                        or 0 <= view_bottom - bottom <= 6), (
                    forced, body_h, cap_h, full, bottom, view_bottom)
            else:
                assert asked == gui.VIEW_H or asked == gui.VIEW_MIN_H, asked

            # the shorter strip still does not change height with its
            # text, and its 'more below' cue counts against the lines it
            # SHOWS: one item per shown line is one display line too many
            h0 = app.canvas.winfo_height()
            few = [{'level': 'warn', 'code': f'c{k}', 'text': 'Short.'}
                   for k in range(lines)]
            assert 1 + len(few) <= gui.HEALTH_LINES
            app._show_health(few)
            settle()
            assert int(app.health_txt.cget('height')) == lines
            assert app.canvas.winfo_height() == h0
            assert app.health_txt.get('1.0', '1.end').endswith(
                gui.HEALTH_MORE), app.health_txt.get('1.0', '1.end')
            app._show_health(few[:lines - 1])
            settle()
            assert gui.HEALTH_MORE not in app.health_txt.get('1.0',
                                                             'end-1c')
            # a run switch does not give the lines back either
            app._populate_runs(run)
            settle()
            assert int(app.health_txt.cget('height')) == lines
            assert app.canvas.winfo_height() == h0
            return None
        finally:
            tk.Misc.winfo_screenheight = real_sh
            if app is not None:
                app._cancel_pending()
            root.destroy()

    try:
        full = case(4000, None)
        for forced in (864, 768, 720):
            if real_h < forced:
                print(f"   (skipped {forced}: this display is only "
                      f"{real_h} px tall)")
                continue
            case(forced, full)
    finally:
        tk.Misc.winfo_screenheight = real_sh
        shutil.rmtree(d, ignore_errors=True)


def test_the_scale_dialog_leads_with_the_runs_stop():
    """Review 2026-10-02: on a STOP run the scale dialog is what the
    student actually reads. It is modal, it opens over the Run health
    strip, and with --auto it is up 300 ms after the window. Its banner
    said 'measure the disc BY HAND' with the fitter's gray-level reason
    and not one word of the STOP behind it.

    The STOP sentence now leads that banner, the hand line points at it
    and names Cancel, and what the banner gained in height comes off the
    picture so the window is no taller than before. Advice still: the
    dialog opens, in a hand mode, with every button. A refused fit on a
    picture that is NOT blank (P3_7) keeps the sentence it always had.

    The verify mode hides that banner, so a STOP run that still has a fit
    to verify shows the STOP there as the banner's only line."""
    import cv2
    import sldea_edge_gui as gui
    import tkinter as tk
    root = _tk_root_or_skip('scale dialog STOP')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_cal_stop_')
    mb = _StubMB(yes=True)
    real_mb, real_spawn = gui.messagebox, gui.spawn_circle
    gui.messagebox = mb
    gui.spawn_circle = lambda *_a, **_k: (160.0, 120.0, 80.0)
    app = None
    saw = {}

    def poke(win):
        p = app._cal_probe
        win.update_idletasks()
        saw['gate'] = p['gate_lbl'].cget('text')
        saw['shown'] = _cal_rendered(p['gate_lbl'], win)
        saw['lines'] = _cal_visible_lines(win)
        saw['stop_px'] = p['stop_px']
        saw['canvas_h'] = int(p['canvas'].cget('height'))
        saw['reqh'] = win.winfo_reqheight()
        saw['mode'] = p['mode_var'].get()
        saw['buttons'] = [b.cget('text') for b in _widgets(win, 'button')]
        saw['stop_vfy_px'] = p['stop_vfy_px']
        if todo['switch_to']:
            # the same dialog after a switch to another method
            for rb in _widgets_of(win, tk.Radiobutton):
                if rb.cget('value') == todo['switch_to']:
                    rb.invoke()
            win.update_idletasks()
            saw['gate2'] = p['gate_lbl'].cget('text')
            saw['shown2'] = _cal_rendered(p['gate_lbl'], win)
            saw['lines2'] = _cal_visible_lines(win)
            saw['canvas_h2'] = int(p['canvas'].cget('height'))
            saw['mode2'] = p['mode_var'].get()
        win.destroy()

    todo = {'switch_to': None}
    try:
        base = os.path.join('frames', 'SLDEA_s00_00.00kV_baseline.png')
        blank = _fake_run(os.path.join(d, 'SLDEA_20260102_000000'))
        cv2.imwrite(os.path.join(blank, base),
                    np.full((240, 320), 67, np.uint8))
        app = gui.EdgeReviewApp(root, path=blank)
        app.root.wait_window = poke
        stops = [it for it in app.health if it['level'] == 'stop']
        assert [it['code'] for it in stops] == ['image_flat'], app.health

        # through Detect, which is the press --auto makes after 300 ms
        app.detect()
        assert saw, "Detect did not open the scale dialog"
        with_stop = dict(saw)
        gate = with_stop['gate']
        first = f"{gui.HEALTH_MARKS['stop']}: {stops[0]['text']}"
        assert gate.startswith(first + '\n'), gate[:300]
        assert with_stop['shown'], "the banner is not on screen"
        assert first in with_stop['lines'], with_stop['lines']
        for words in ('The baseline picture is blank',
                      'cannot be measured', 'Do not calibrate by hand'):
            assert words in gate, (words, gate)
        # the STOP is ahead of the fit's refusal and of its reason, and
        # the refusal no longer orders the hand measurement
        assert gate.index('The baseline picture is blank') \
            < gate.index('NO automatic fit on this run') \
            < gate.index('Reason:'), gate
        assert gui.GATE_NO_FIT_STOP in gate and gui.GATE_NO_FIT not in gate
        assert any(b.startswith('Cancel (Esc)')
                   for b in with_stop['buttons']), with_stop['buttons']
        # ADVICE: the dialog opened, on a hand mode, and closing it left
        # Detect gated on the scale exactly as on any run
        assert with_stop['mode'] == gui.se.CAL_DEFAULT_MODE, with_stop
        assert 'gated' in app.status.cget('text'), app.status.cget('text')
        assert str(app.detect_btn['state']) == 'normal'
        assert not mb.errors and not mb.infos, (mb.errors, mb.infos)
        # the banner's extra height came off the picture
        sh = root.winfo_screenheight()
        assert with_stop['stop_px'] > 0, with_stop
        assert with_stop['canvas_h'] == max(
            300, min(760, sh - 400 - with_stop['stop_px'])), (with_stop, sh)

        # the SAME run with nothing on the strip: the dialog is the one
        # it always was, and no taller or shorter than the one above
        saw.clear()
        app._show_health([])
        app._calibrate_scale()
        plain = dict(saw)
        assert gui.HEALTH_MARKS['stop'] not in plain['gate'], plain['gate']
        assert plain['gate'].startswith(gui.GATE_NO_FIT + ' Reason:'), \
            plain['gate']
        assert plain['stop_px'] == 0
        assert plain['canvas_h'] == max(300, min(760, sh - 400)), plain
        if min(plain['canvas_h'], with_stop['canvas_h']) > 300:
            assert abs(with_stop['reqh'] - plain['reqh']) <= 2, (
                with_stop['reqh'], plain['reqh'])
        else:
            print("   (screen too short to compare the two window "
                  "heights: the picture is at its 300 px floor)")

        # a refused fit on a picture that is not blank is a WARNING on
        # the strip, and its dialog carries no STOP
        faint = _fake_run(os.path.join(d, 'SLDEA_20260103_000000'))
        img = np.full((240, 320), 150, np.uint8)
        img[:, :110] = 200
        cv2.imwrite(os.path.join(faint, base), img)
        app._populate_runs(faint)
        assert app.rundir == faint
        codes = [(it['level'], it['code']) for it in app.health]
        assert ('warn', 'disc_fit_refused') in codes, codes
        assert not [c for c in codes if c[0] == 'stop'], codes
        saw.clear()
        app.detect()
        assert saw, "Detect did not open the scale dialog"
        assert gui.HEALTH_MARKS['stop'] not in saw['gate'], saw['gate']
        assert saw['gate'].startswith(gui.GATE_NO_FIT + ' Reason:'), \
            saw['gate']
        assert 'seed' in saw['gate'] and saw['stop_px'] == 0, saw

        # A STOP WITH A FIT TO VERIFY. A disc only 15 gray levels darker
        # than its paper is 'blank' to image_content (under 20) and the
        # automatic fit still finds it, so the dialog opens in the verify
        # mode, whose screen hides the warnings banner. The STOP is the
        # one line that stays there, alone, and its height comes off the
        # picture in that mode too.
        dim = _fake_run(os.path.join(d, 'SLDEA_20260104_000000'))
        yy, xx = np.mgrid[0:240, 0:320]
        img = np.full((240, 320), 190, np.uint8)
        img[(xx - 160) ** 2 + (yy - 120) ** 2 <= 80 * 80] = 175
        cv2.imwrite(os.path.join(dim, base), img)
        # no diameter line in setup.txt: the banner of the hand modes
        # then holds a second warning, which the verify mode must leave
        # to its own evidence block
        with open(os.path.join(dim, 'setup.txt'), 'w') as f:
            f.write("SLDEA Test -- synthetic\n")
        app._populate_runs(dim)
        assert app.rundir == dim
        stops = [it for it in app.health if it['level'] == 'stop']
        assert [it['code'] for it in stops] == ['image_flat'], app.health
        first = f"{gui.HEALTH_MARKS['stop']}: {stops[0]['text']}"
        saw.clear()
        todo['switch_to'] = gui.se.CAL_MODE_CIRCLE
        app.detect()
        assert saw, "Detect did not open the scale dialog"
        assert saw['mode'] == gui.se.CAL_MODE_VERIFY, saw['mode']
        assert saw['shown'], "the verify mode hid the run's STOP"
        assert saw['gate'] == first, saw['gate']
        assert first in saw['lines'], saw['lines']
        assert 'NO automatic fit' not in ' '.join(saw['lines']), saw['lines']
        assert saw['stop_vfy_px'] > 0, saw
        assert saw['canvas_h'] == max(
            300, min(760, sh - 300 - saw['stop_vfy_px'])), (saw, sh)
        # ...and a switch to a hand method keeps it on screen, with the
        # measuring modes' height
        assert saw['mode2'] == gui.se.CAL_MODE_CIRCLE, saw['mode2']
        assert saw['shown2'], "the hand mode lost the banner"
        assert saw['gate2'].startswith(first + '\n'), saw['gate2']
        assert 'settings DEFAULT' in saw['gate2'], saw['gate2']
        assert 'settings DEFAULT' not in saw['gate'], saw['gate']
        assert first in saw['lines2'], saw['lines2']
        assert saw['canvas_h2'] == max(
            300, min(760, sh - 400 - saw['stop_px'])), (saw, sh)
        # the same picture with nothing on the strip: the verify screen
        # carries no banner at all, as on every ordinary run, and the
        # window is as tall as the one with the STOP in it
        vfy_stop = dict(saw)
        saw.clear()
        todo['switch_to'] = None
        app._show_health([])
        app._calibrate_scale()
        assert saw['mode'] == gui.se.CAL_MODE_VERIFY, saw['mode']
        assert not saw['shown'], saw['gate']
        assert gui.HEALTH_MARKS['stop'] not in ' '.join(saw['lines'])
        assert saw['stop_vfy_px'] == 0
        assert saw['canvas_h'] == max(300, min(760, sh - 300)), (saw, sh)
        if 300 < vfy_stop['canvas_h'] and saw['canvas_h'] < 760:
            assert abs(vfy_stop['reqh'] - saw['reqh']) <= 2, (
                vfy_stop['reqh'], saw['reqh'])
        else:
            print("   (this screen pins the verify picture at its 300 or "
                  "760 px limit: the two window heights are not compared)")
    finally:
        gui.messagebox, gui.spawn_circle = real_mb, real_spawn
        if app is not None:
            app._cancel_pending()
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_save_keeps_the_runners_capture_notes():
    """S6 / U25: Save rebuilt every reviewed row's notes cell, so the
    first Save erased the runner's 'V_Out off-screen (clipped)' and the
    watchdog's WATCHDOG note. Two Saves through the real window: both
    tokens are still there, once each, in front of the fresh edge note."""
    import sldea_edge as se
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('save keeps capture notes')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_notes_')
    mb = _StubMB(yes=True)
    real_mb = gui.messagebox
    gui.messagebox = mb
    app = None
    wd = 'WATCHDOG: breakdown confirmed (dev >100µA for 3s)'
    voff = 'V_Out off-screen (clipped)'
    try:
        rundir = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        # what the runner leaves behind: capture notes, written UTF-8
        run = se.load_run(rundir)
        run['rows'][1]['notes'] = voff
        run['rows'][2]['notes'] = f'{wd}; {voff}'
        se.write_back(rundir, run)
        os.remove(os.path.join(rundir, 'data.csv.bak'))

        def saved_notes():
            with open(os.path.join(rundir, 'data.csv'), newline='',
                      encoding='utf-8-sig') as f:
                return [r['notes'] for r in csv.DictReader(f)]

        assert saved_notes()[1:] == [voff, f'{wd}; {voff}']
        for n_save in (1, 2):
            if app is None:
                app = gui.EdgeReviewApp(root, path=rundir)
            else:
                app._populate_runs(rundir)       # a fresh look at the disk
            # the strip already reports the trip the note records
            assert 'watchdog_trip' in [it['code'] for it in app.health]
            app.manual_ref = {'method': 'manual-calibration',
                              'diam_px': 160.0}
            app.detect_all_sync()
            # decide every frame, so each row takes the REBUILT-notes path
            for i in app.frame_rows:
                if i not in app.results:
                    cands = app.cands_all.get(i) or []
                    app.results[i] = cands[0] if cands else None
            assert set(app.frame_rows) <= set(app.results)
            app.save()
            assert not mb.errors, mb.errors
            notes = saved_notes()
            assert notes[1].startswith(f'{voff}; '), (n_save, notes[1])
            assert notes[2].startswith(f'{wd}; {voff}; '), (n_save, notes[2])
            for note in notes[1:]:
                assert note.count(voff) == 1, (n_save, note)
                assert note.count('WATCHDOG') <= 1, (n_save, note)
                # exactly one measurement verdict, never a pile of them
                assert note.count('edge:') + note.count('rejected (') == 1, \
                    (n_save, note)
            assert notes[2].count('WATCHDOG') == 1, (n_save, notes[2])
            assert 'WATCHDOG' not in notes[0] and voff not in notes[0]
        # the second Save's backup is the first Save's output: the
        # capture notes are in that copy too
        with open(os.path.join(rundir, 'data.csv.bak'), newline='',
                  encoding='utf-8-sig') as f:
            bak = [r['notes'] for r in csv.DictReader(f)]
        assert bak[2].startswith(f'{wd}; {voff}'), bak[2]
    finally:
        gui.messagebox = real_mb
        if app is not None:
            app._cancel_pending()
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_save_empties_old_estimator_rows_and_stamps_the_provenance():
    """2026-10-02: the disc-fit area changed from the fitted ellipse to
    the common-ray ratio. A Save keeps the previous pass's px on rows
    still in the review queue, so on a run last saved by the OLD method
    a re-save would put old and new numbers in one column and on one
    plot axis. Save must (a) say in its yes/no dialog how many rows
    will be emptied, before anything is written, (b) empty each such
    row with the note in place of its old one (data.csv.bak keeps the
    numbers), (c) stamp the run with the current method and the
    baseline's provenance only after the CSV is written, (d) keep such
    rows on the next Save, when the stamp is current, and (e) on a
    trace-only Save (no Detect this session) of an old run say that the
    emptied rows are NOT re-measured."""
    import sldea_edge as se
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('estimator stamp')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_est_')
    mb = _StubMB(yes=True)
    real_mb = gui.messagebox
    gui.messagebox = mb
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        # a previous Save by the old method: row 1 a machine ellipse
        # area, row 2 a hand trace. No stamp in setup.txt = old method.
        csv_path = os.path.join(run, 'data.csv')
        with open(csv_path, newline='') as f:
            r = csv.DictReader(f)
            rows, cols = list(r), r.fieldnames
        rows[1].update(active_area_px='9000', active_area_mm2='90.000',
                       active_diam_mm='10.700', wrinkle_idx='1.10',
                       notes='edge:disc-fit conf 0.93')
        rows[2].update(active_area_px='15000', active_area_mm2='150.000',
                       active_diam_mm='13.800',
                       notes='edge:manual-trace conf 1.00 (user)')
        with open(csv_path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        assert se.load_stamp(run) == {}
        app = gui.EdgeReviewApp(root, path=run)
        app.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app.detect_all_sync()
        # both activated rows are still in the review queue at Save
        app.results.pop(1, None)
        app.results.pop(2, None)
        app.auto_idx.discard(1)
        app.auto_idx.discard(2)
        assert app._queue_list() == [1, 2]
        # ...and row 1's frame could not be read this session: it is
        # emptied like any stale row, so the dialog must not count it
        # as 'kept, not re-measured' and its note must not say 'kept'
        # (review 2026-10-02)
        app.load_fail[1] = 'unreadable'
        app.save()
        msg = mb.asked[-1][1]
        assert '1 unreviewed row(s) hold an automatic area' in msg, msg
        assert 'OLD area method' in msg and 'EMPTIED' in msg, msg
        # the .bak is one generation deep, and the dialog says so
        assert 'data.csv.bak until the NEXT Save' in msg, msg
        assert 'UNREADABLE' not in msg, msg
        assert "1 keep the previous pass's px" in msg, msg   # the trace
        assert 'NO detection pass' not in msg, msg
        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            saved = list(csv.DictReader(f))
        for col in ('active_area_px', 'active_area_mm2', 'active_diam_mm',
                    'wrinkle_idx'):
            assert saved[1][col] == '', (col, saved[1][col])
        assert saved[1]['notes'] == se.AREA_ESTIMATOR_STALE_NOTE
        assert 'kept, not re-measured' not in saved[1]['notes'], \
            saved[1]['notes']
        app.load_fail.pop(1, None)
        assert saved[2]['active_area_px'] == '15000'
        assert se.AREA_ESTIMATOR_STALE_NOTE not in saved[2]['notes']
        assert se.AREA_ESTIMATOR_STALE_NOTE not in saved[0]['notes']
        assert os.path.exists(csv_path + '.bak')
        # the stamp: current version plus the baseline's provenance, in
        # the edge-settings block, pinning no detection setting; since
        # owner decision 6 (2026-10-03) the tracker's window limits the
        # rows were measured under ride on it as the constants the
        # tracker really read
        stamp = se.load_stamp(run)
        assert stamp['area_estimator'] == se.AREA_ESTIMATOR_VERSION, stamp
        assert stamp.get('base_rays', 0) >= se.RAY_MIN_COMMON, stamp
        assert 0.0 <= stamp['base_hidden_pct'] < 100.0, stamp
        assert 'base_one_sided' in stamp, stamp
        assert stamp['ray_win_hi'] == se.RAY_WIN_HI, stamp
        assert stamp['disc_fit_r_max'] == se.DISC_FIT_R_MAX, stamp
        assert not se.has_saved_settings(run)
        assert not any(k in se.load_settings(run)
                       for k in se.TRACKER_LIMIT_KEYS)
        assert se.load_scale_anchor(run)['diam_px'] == 160.0
        assert not mb.warnings, mb.warnings
        # a second Save: the stamp is current, so a kept tracker row is
        # this estimator's and stays (re-scaled to the anchor, as before)
        app.run['rows'][1].update(active_area_px='9100',
                                  notes='edge:disc-fit conf 0.93')
        app.save()
        msg = mb.asked[-1][1]
        assert 'OLD area method' not in msg, msg
        assert "2 keep the previous pass's px" in msg, msg
        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            saved = list(csv.DictReader(f))
        assert saved[1]['active_area_px'] == '9100'
        assert saved[1]['notes'] == 'edge:disc-fit conf 0.93'
        assert se.load_stamp(run)['base_rays'] == stamp['base_rays']
        # a trace-only Save on a STAMPED run keeps every row and the
        # stamp exactly as recorded
        app2 = gui.EdgeReviewApp(root, path=run)
        app2.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        assert not app2.cands_all
        app2.save()
        assert 'OLD area method' not in mb.asked[-1][1]
        assert se.load_stamp(run) == stamp
        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            assert list(csv.DictReader(f))[1]['active_area_px'] == '9100'
        # ...the tracker limits included: a run whose rows were measured
        # under another window (the 2026-10-02 one, 1.38 r0 and 1.3 r0)
        # keeps that window on record through a Save with no Detect,
        # because the rows on file are still that window's
        old_win = dict(stamp, ray_win_hi=1.38, disc_fit_r_max=1.3)
        se.save_settings(run, None, stamp=old_win)
        app2b = gui.EdgeReviewApp(root, path=run)
        app2b.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        assert not app2b.cands_all
        app2b.save()
        assert se.load_stamp(run) == old_win, se.load_stamp(run)
        se.save_settings(run, None, stamp=stamp)
        assert se.load_stamp(run) == stamp
        # a trace-only Save on an OLD run cannot convert it quietly: the
        # dialog says the rows are emptied and not re-measured
        se.save_settings(run, None, stamp=se.estimator_stamp(None, version=1))
        assert se.saved_area_estimator(run) == 1
        app3 = gui.EdgeReviewApp(root, path=run)
        app3.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        mb3 = _StubMB(yes=False)                  # the operator cancels
        gui.messagebox = mb3
        app3.save()
        msg = mb3.asked[-1][1]
        assert '1 unreviewed row(s) hold an automatic area' in msg, msg
        assert 'NO detection pass' in msg and 'NOT re-measured' in msg, msg
        assert 'Detect Edges first' in msg, msg
        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            assert list(csv.DictReader(f))[1]['active_area_px'] == '9100'
        assert se.saved_area_estimator(run) == 1        # nothing written
        gui.messagebox = mb
        # a stamp that cannot be written is SAID, not swallowed
        real_stamp = se.stamp_area_estimator

        def boom(*a, **k):
            raise OSError(13, 'Permission denied')

        se.stamp_area_estimator = boom
        try:
            app.save()
        finally:
            se.stamp_area_estimator = real_stamp
        assert mb.warnings and 'stamp not written' in mb.warnings[-1][0], \
            mb.warnings
    finally:
        gui.messagebox = real_mb
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_tracker_card_says_what_the_number_is_and_what_the_outline_is():
    """2026-10-02: the tracker's number is the common-ray ratio while
    the outline it draws is the ellipse, which encloses a different
    area (7 % more on DOT_P3_1 at rest). The panel under the candidate
    radios says so in plain words for the tracker candidate on the
    card, with the audit fields the number rests on (rays used, hidden
    share, trim share, one-sidedness), and says nothing when there is
    no tracker candidate. Since 2026-10-03 (owner decisions 2 and 9)
    the trim share sits beside the trimmed count, the last sentence
    names the two review-only limits, and on a candidate past one of
    them it says REVIEW ONLY and which limit tripped."""
    import sldea_edge as se
    import sldea_edge_gui as gui
    disc = {'method': 'disc-fit', 'area_px': 217500.0, 'conf': 0.98,
            'area_ratio': 1.0003, 'n_common': 211, 'n_trimmed': 33,
            'trim_share': 0.135, 'one_sided': 0.062, 'hidden_pct': 41.4,
            'ellipse_over_circle': 1.07418}
    rest = {'method': 'resting', 'area_px': 217438.0, 'conf': 0.95}
    patch = {'method': 'diff-hi', 'area_px': 63040.0, 'conf': 0.63}
    text = gui.tracker_card_text([rest, disc, patch])
    assert text.startswith('B is the ray ratio: 1.0003 x A0'), text
    assert '211 rays' in text, text
    assert '(33 more trimmed, 14% of the rays)' in text, text
    # the share the number did not use is NOT all 'hidden': it counts
    # the trimmed rays and the rays with no ink step too (review
    # 2026-10-02), and the text says what it is made of
    assert 'Not used: 41% of the edge' in text, text
    assert 'behind leads or foil, no ink step, or trimmed' in text, text
    assert 'hidden' not in text, text
    assert 'assumed to strain like the rest' in text, text
    assert 'One-sidedness 0.06.' in text, text
    assert 'refused' not in text, text
    assert text.endswith(f'Review only above 20% trimmed or '
                         f'{se.RAY_MAX_ONE_SIDED:g} one-sided.'), text
    assert 'REVIEW ONLY' not in text, text
    assert 'The drawn outline is the ellipse, not the number' in text, text
    assert 'encloses 1.074 x A0' in text, text
    # the outline sentence follows the number directly: it is the one
    # sentence the panel exists for, so it sits where it is read first
    assert text.index('The drawn outline') < text.index('Not used'), text
    # no tracker candidate: nothing is claimed
    assert gui.tracker_card_text([rest, patch]) == ''
    assert gui.tracker_card_text([]) == ''
    # no trimmed rays: the clause is absent; no ellipse figure: said
    d2 = dict(disc, n_trimmed=0, trim_share=0.0, ellipse_over_circle=None)
    t2 = gui.tracker_card_text([d2])
    assert t2.startswith('A is the ray ratio') and 'more trimmed' not in t2, t2
    assert 'encloses a different area' in t2, t2
    # a candidate the ray ratio marked review only says so in words and
    # names the limit that tripped (one, the other, both)
    t3 = gui.tracker_card_text([dict(disc, trim_share=0.24,
                                     ray_trim_share=0.24)])
    assert t3.endswith('REVIEW ONLY, never auto-accepted: 24% trimmed '
                       '(limit 20%).'), t3
    assert '(33 more trimmed, 24% of the rays)' in t3, t3
    assert 'Review only above' not in t3, t3
    t4 = gui.tracker_card_text([dict(disc, one_sided=0.71,
                                     ray_one_sided=0.71)])
    assert t4.endswith('One-sidedness 0.71. REVIEW ONLY, never '
                       'auto-accepted: one-sided 0.71 (limit 0.6).'), t4
    t5 = gui.tracker_card_text([dict(disc, trim_share=0.31, one_sided=0.66,
                                     ray_trim_share=0.31,
                                     ray_one_sided=0.66)])
    assert t5.endswith('REVIEW ONLY, never auto-accepted: 31% trimmed '
                       '(limit 20%), one-sided 0.66 (limit 0.6).'), t5
    # the gate compares the unrounded figures (review 2026-10-04:
    # retired 233451 row 47 trips at 0.60012), so a figure just past
    # the limit is printed with enough decimals to read past it, never
    # as "0.60 (limit 0.6)"; the sentence before it keeps two decimals
    t6 = gui.tracker_card_text([dict(disc, trim_share=0.20277,
                                     one_sided=0.60012,
                                     ray_trim_share=0.20277,
                                     ray_one_sided=0.60012)])
    assert t6.endswith('One-sidedness 0.60. REVIEW ONLY, never '
                       'auto-accepted: 20.3% trimmed (limit 20%), '
                       'one-sided 0.6001 (limit 0.6).'), t6
    assert '(33 more trimmed, 20% of the rays)' in t6, t6
    assert gui.past_limit_text(0.71, 0.6, (2, 3, 4)) == '0.71'
    assert gui.past_limit_text(0.60012, 0.6, (2, 3, 4)) == '0.6001'
    assert gui.past_limit_text(0.6004, 0.6, (2, 3, 4)) == '0.6004'
    assert gui.past_limit_text(0.60004, 0.6, (2, 3, 4)) == 'over 0.6'
    assert gui.past_limit_text(24.0, 20.0, (0, 1, 2), '%') == '24%'
    assert gui.past_limit_text(20.04, 20.0, (0, 1, 2), '%') == '20.04%'
    assert gui.past_limit_text(20.004, 20.0, (0, 1, 2), '%') == 'over 20%'
    # the panel follows the frame on screen, and SHOWS the whole text:
    # the label has a fixed height in lines, and Tk clips a text that
    # wraps to more lines than that without a word of complaint. With
    # TRACKER_LINES at 4 the outline sentence was the part the operator
    # never saw (review 2026-10-02). An unconstrained probe Label with
    # the same font and wraplength says how tall each text really is.
    # The window is MAPPED (not withdrawn) so winfo_height is the height
    # the packer really gave the panel, not the 1 px of an unmapped
    # widget.
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    d = tempfile.mkdtemp(prefix='edge_gui_card_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        app = gui.EdgeReviewApp(root, path=run)
        app.detect_all_sync()
        assert app.tracker_lbl.cget('height') == gui.TRACKER_LINES
        root.update_idletasks()
        root.update()
        assert app.tracker_lbl.winfo_ismapped()
        shown_h = app.tracker_lbl.winfo_height()
        wrap = int(app.tracker_lbl.cget('wraplength'))
        font = app.tracker_lbl.cget('font')

        def _needed(txt):
            probe = tk.Label(root, text=txt, justify='left', anchor='nw',
                             font=font, wraplength=wrap)
            probe.update_idletasks()
            h = probe.winfo_reqheight()
            probe.destroy()
            return h

        seen_tracker = False
        for pos in range(len(app.frame_rows)):
            app.pos = pos
            app._show()
            i = app.frame_rows[pos]
            txt = gui.tracker_card_text(app.cands_all.get(i, []))
            assert app.tracker_lbl.cget('text') == txt
            if txt:
                seen_tracker = True
                assert _needed(txt) <= shown_h, (
                    f"frame {i}: the card text needs {_needed(txt)} px, "
                    f"the panel shows {shown_h}")
        assert seen_tracker, 'no tracker candidate on the fake run'
        # ...and the LONGEST text the function can produce (3-digit ray
        # counts, a 3-digit trim with its share, a 1.xxx ellipse figure,
        # both review-only limits tripped by figures just past them, so
        # each is printed with its most decimals) fits too, so a real
        # run cannot find a longer one than the fake run did
        worst = dict(disc, n_common=299, n_trimmed=103, hidden_pct=69.9,
                     trim_share=0.2004, one_sided=0.60012,
                     ray_trim_share=0.2004, ray_one_sided=0.60012,
                     ellipse_over_circle=1.14699, area_ratio=1.55665)
        assert gui.tracker_card_text([worst, rest]).endswith(
            '20.04% trimmed (limit 20%), one-sided 0.6001 (limit 0.6).')
        need = _needed(gui.tracker_card_text([worst, rest]))
        assert need <= shown_h, (f"the longest card text needs {need} px, "
                                 f"the panel shows {shown_h}")
        assert _needed(gui.tracker_card_text([rest, disc])) <= shown_h
    finally:
        app._cancel_pending()
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_edge_review_warns_in_one_line_off_the_pinned_opencv():
    """Owner decision 29 (2026-10-03): every corpus number is OpenCV
    4.13, the version requirements.txt pins. When another cv2 is
    running, Edge Review shows one plain line at the bottom left (the
    footer row, beside the How to use button) and changes nothing
    else: Detect, Save and the dialogs are untouched. On the pinned
    version the row holds the button alone. The text comes from
    se.opencv_version_warning, so the pin, the comparison and the
    wording are tested headlessly in test_sldea_edge.py; this test
    pins where it is shown and that it blocks nothing."""
    import sldea_edge as se
    import sldea_edge_gui as gui
    root = _tk_root_or_skip('edge-review cv2 warning')
    if root is None:
        return
    d = tempfile.mkdtemp(prefix='edge_gui_cv_')
    orig = se.opencv_version_warning
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        # the pinned version: no line, nothing packed in the footer
        se.opencv_version_warning = lambda running=None, pin=None: ''
        app = gui.EdgeReviewApp(root, path=run)
        assert app.cv_warn == ''
        assert app.cv_warn_lbl.cget('text') == ''
        assert not app.cv_warn_lbl.winfo_manager()
        foot = app.howto_btn.master
        assert app.cv_warn_lbl.master is foot
        app._cancel_pending()
        # another version: the one line, in the footer, with the glyph
        # beside the colour, and the app still detects and saves
        msg = orig('4.12.0', '4.13.0')
        assert msg and '\n' not in msg
        se.opencv_version_warning = lambda running=None, pin=None: msg
        app2 = gui.EdgeReviewApp(root, path=run)
        assert app2.cv_warn == msg
        assert app2.cv_warn_lbl.cget('text') == '\u26a0 ' + msg
        assert app2.cv_warn_lbl.winfo_manager() == 'pack'
        assert app2.cv_warn_lbl.master is app2.howto_btn.master
        assert app2.cv_warn_lbl.pack_info()['side'] == 'left'
        assert app2.cv_warn_lbl.cget('fg') == app2.queue_lbl.cget('fg')
        assert str(app2.detect_btn.cget('state')) == 'normal'
        app2.manual_ref = {'method': 'manual-calibration', 'diam_px': 160.0}
        app2.detect_all_sync()
        assert app2.cands_all, 'detection did not run under the warning'
        real_mb = gui.messagebox
        mb = _StubMB(yes=True)
        gui.messagebox = mb
        try:
            app2.save()
        finally:
            gui.messagebox = real_mb
        assert not mb.errors, mb.errors
        assert se.saved_area_estimator(run) == se.AREA_ESTIMATOR_VERSION
        # the stamp records the versions that really ran, not the pin,
        # and the tracker limits that really measured the rows
        stamp = se.load_stamp(run)
        assert stamp['opencv_version'] == se.library_versions()['opencv_version']
        assert stamp['numpy_version'] == se.library_versions()['numpy_version']
        assert {k: stamp[k] for k in se.TRACKER_LIMIT_KEYS} \
            == se.tracker_limits(), stamp
        app2._cancel_pending()
    finally:
        se.opencv_version_warning = orig
        root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import gc
    import traceback

    def _reap():
        """Collect Tk garbage HERE, in the main thread. (`#280`)

        Diagnosed 2026-08-12. Each display-gated case builds a Tk root and
        a window, destroys the root, and drops the references -- but the
        Python objects are freed whenever CPython next collects, which can
        be inside a detection worker thread. Tk's C layer refuses that:
        'Tcl_AsyncDelete: async handler deleted by the wrong thread', which
        ABORTS the process rather than raising, so the summary line never
        prints and the suite looks like an infrastructure failure instead
        of a test result.

        It is a race, which is why it read as a box-context flake: it
        depends on how many objects a case leaves for the collector and on
        when a thread happens to run. Adding a scroll container to Edge
        Review made it deterministic by raising the object count, which is
        how it was finally caught.

        Collecting after every case keeps the freeing on this thread, where
        Tk allows it.
        """
        gc.collect()

    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = []
    for fn in fns:
        try:
            fn()
        except Exception:
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            _reap()
            continue
        _reap()
        print(f"ok  {fn.__name__}")
    if not failed:
        print(f"\n{len(fns)} tests passed")
        return 0
    head = f"{len(failed)} of {len(fns)} tests failed"
    print(f"\n{head}")
    for name, tb in failed:
        print(f"===== FAIL {name} =====")
        print(tb.rstrip('\n'))
    print(f"===== end {head} =====")
    return 1


if __name__ == '__main__':
    raise SystemExit(_run())
