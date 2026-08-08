#!/usr/bin/env python3
"""Tests for the sldea_plot window (`#223`, `#271`).

Most of it is headless: run discovery and initial state are deliberately
separate from the widgets so they CAN be tested without a display. The
drawing and export paths belong to sldea_plot and are covered by
test_sldea_plot.py -- that split is the point, the window owns no
plotting rules of its own.

The `#271` LAYOUT cases are the exception and cannot be faked. A
withdrawn root computes no geometry at all (measured: every winfo_height
comes back 1), so the window has to be on screen for "is the figure the
size of its widget", "is the warnings pane still there" and "did the
scrollbar appear" to mean anything -- the same reason
test_sldea_edge_gui deiconifies for its synthetic-event cases. They skip
cleanly with no display.

Run: .venv/bin/python tests/test_sldea_plot_gui.py
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

import sldea_plot as sp
import sldea_plot_gui as g

COLS = ['snapshot', 'step', 'tag', 'nominal_kV', 'control_V',
        'measured_kV', 'measured_uA', 't_planned_s', 'timestamp',
        'frame_file', 'active_area_px', 'active_area_mm2',
        'active_diam_mm', 'wrinkle_idx', 'notes']


def _mktmp():
    return tempfile.mkdtemp(prefix='sldea_plot_gui_test_')


def _fake_run(parent, name, processed=True, csv_name='data.csv'):
    d = os.path.join(parent, name)
    os.makedirs(os.path.join(d, 'frames'), exist_ok=True)
    rows = [{'snapshot': 1, 'tag': 'baseline', 'nominal_kV': 0,
             'measured_uA': -16.0, 'timestamp': '2026-08-05T10:00:00'},
            {'snapshot': 2, 'tag': 'post-ramp', 'nominal_kV': 1.0,
             'measured_uA': -15.9, 'timestamp': '2026-08-05T10:01:00'}]
    if processed:
        for r in rows:
            r['active_area_px'] = 288555
            r['active_area_mm2'] = 201.062
    with open(os.path.join(d, csv_name), 'w', newline='',
              encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({**{c: '' for c in COLS}, **r})
    return d


def test_importing_the_module_opens_no_window():
    # It is imported by test collectors, by sldea_plot --gui and by the
    # app's button. Only launch() may create a Tk root.
    import tkinter as tk
    assert tk._default_root is None, 'importing the module connected to Tk'
    assert hasattr(g, 'launch') and hasattr(g, 'PlotWindow')


def test_list_runs_labels_processed_runs_like_edge_review():
    p = _mktmp()
    try:
        _fake_run(p, 'P3_1_20260728', processed=True)
        _fake_run(p, 'P3_2_20260728', processed=False)
        os.makedirs(os.path.join(p, 'not_a_run'), exist_ok=True)
        runs = g.list_runs(p)
        assert [n for n, _ in runs] == ['P3_2_20260728', 'P3_1_20260728'], \
            'newest name first, non-runs excluded'
        by_name = dict(runs)
        assert by_name['P3_1_20260728'].endswith('✓ processed')
        assert by_name['P3_2_20260728'] == 'P3_2_20260728'
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_list_runs_sees_a_renamed_run_csv():
    # se.run_csv accepts data1.csv/data2.csv -- the bench renames them to
    # open several runs in Excel at once, and a renamed run is still a run.
    p = _mktmp()
    try:
        _fake_run(p, 'renamed', processed=True, csv_name='data2.csv')
        assert [n for n, _ in g.list_runs(p)] == ['renamed']
        assert g.list_runs(p)[0][1].endswith('✓ processed')
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_list_runs_survives_an_unreadable_parent():
    assert g.list_runs(os.path.join(_mktmp(), 'nope')) == []
    assert g.list_runs('') == []


def test_is_processed_guards_short_lines():
    # The Edge Review lesson: a truncated/blank line used to raise
    # IndexError and take the whole listing with it.
    p = _mktmp()
    try:
        d = _fake_run(p, 'trunc', processed=True)
        with open(os.path.join(d, 'data.csv'), 'a', encoding='utf-8') as f:
            f.write('1,2,3\n\n')
        assert g.is_processed(d) is True
        assert g.is_processed(os.path.join(p, 'missing')) is False
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_split_target_accepts_a_run_a_parent_or_nothing():
    p = _mktmp()
    try:
        run = _fake_run(p, 'R1')
        assert g.split_target(run) == (os.path.abspath(p), 'R1')
        # a parent resolves to its newest run (the house resolver's rule),
        # so opening on a folder still lands on something plottable
        parent, name = g.split_target(p)
        assert parent == os.path.abspath(p) and name == 'R1'
        assert g.split_target(None) == (None, None)
        assert g.split_target(os.path.join(p, 'nope')) == (None, None)
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_initial_state_preselects_several_runs():
    """Multi-run selection is the reason `#223` exists -- several run
    arguments must arrive as several preselected runs, not just the last
    one."""
    p, other = _mktmp(), _mktmp()
    try:
        a = _fake_run(p, 'A_run')
        b = _fake_run(p, 'B_run')
        elsewhere = _fake_run(other, 'C_run')
        parent, pre = g.initial_state([a, b])
        assert parent == os.path.abspath(p)
        assert sorted(pre) == ['A_run', 'B_run']
        # the first argument picks the parent; a run from another parent
        # cannot be listed alongside it, so it does not preselect
        parent, pre = g.initial_state([a, elsewhere])
        assert parent == os.path.abspath(p) and pre == ['A_run']
        # a bare parent still preselects its newest run. se.newest_run
        # orders by MTIME, and two directories created back to back can
        # land on the same tick -- so the fixture states which is newer
        # instead of racing the clock.
        os.utime(a, (1_700_000_000, 1_700_000_000))
        os.utime(b, (1_800_000_000, 1_800_000_000))
        parent, pre = g.initial_state([p])
        assert parent == os.path.abspath(p) and pre == ['B_run'], pre
    finally:
        for d in (p, other):
            shutil.rmtree(d, ignore_errors=True)


def test_initial_state_falls_back_without_arguments():
    parent, pre = g.initial_state([])
    assert parent, 'no parent at all'
    assert isinstance(pre, list)


def test_a_junk_target_cannot_take_the_window_down_before_it_draws():
    """split_target is the front door -- the argument comes from a command
    line, a drop, or whatever is typed in the SLDEA tab's output-dir box.
    se.run_csv guards OSError but not the ValueError an embedded NUL
    raises, and that used to propagate out of initial_state()."""
    for junk in ('\x00nul', 'C:\\nope\x00', '???', 'x' * 400):
        assert g.split_target(junk) == (None, None), junk
        assert g.initial_state([junk])[0] == g.initial_state([])[0]


def test_default_out_dir_is_never_the_working_directory():
    """`#223` asked for a sane default output dir. cwd is right for a
    shell and wrong for a double-clicked window, where it is wherever the
    launcher happened to be -- figures went missing that way."""
    p = _mktmp()
    try:
        out = g.default_out_dir(p)
        assert out == os.path.join(p, g.OUT_SUBDIR)
        assert os.path.abspath(out) != os.path.abspath(os.getcwd())
        # never inside a run folder: it sits beside them
        assert os.path.dirname(out) == p
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_help_text_is_ascii_and_opens_no_window():
    # The one thing this module prints to a console. A Windows cp1252
    # console cannot carry the docstring's prose, and --help must not
    # start a mainloop.
    g.USAGE.encode('ascii')
    assert 'sldea_plot_gui.py' in g.USAGE
    for flag in ('-h', '--help'):
        assert g.main([flag]) == 0


def test_mode_hints_say_which_modes_need_reviewed_runs():
    """The issue's complaint: that current/power work on RAW runs while
    area needs REVIEWED ones was buried in --help. The window says it."""
    assert set(g.MODE_HINT) == set(sp.MODES)
    assert 'REVIEWED' in g.MODE_HINT['area']
    for m in ('current', 'power'):
        assert 'RAW' in g.MODE_HINT[m], m


def test_uncertainty_band_tooltip_says_where_the_numbers_come_from():
    """`#266`: the bands are a CALIBRATED ERROR BUDGET
    (SLDEA_MEASUREMENT.md), not a fit residual and not anything this
    window computed -- and nothing on screen said so."""
    tip = g.BANDS_TIP
    assert 'SLDEA_MEASUREMENT.md' in tip, 'the budget is not cited'
    for phrase in ('scale anchor', 'repeatability', 'half-height',
                   'outer toe'):
        assert phrase in tip, phrase
    # the two levels, and the rule for a level that mixes them
    assert f"±{sp.MACHINE_BAND_PCT:g}%" in tip
    assert f"±{sp.TRACED_BAND_PCT:g}%" in tip
    assert 'MIXES' in tip and 'machine member(s) only' in tip
    assert '5.2–5.7%' in tip, 'the definitional offset is not named'


def test_uncertainty_band_tooltip_refuses_conf_as_an_uncertainty():
    """`#266`'s sharp end. `conf` is the one number an operator sees
    beside every area, it looks exactly like an error bar, and it is a
    review-ORDERING score -- measured ANTI-calibrated across methods
    (SLDEA_MEASUREMENT.md §3.3). The tooltip has to say so, not merely
    omit it."""
    tip = g.BANDS_TIP
    assert 'conf' in tip
    assert 'ordering' in tip.lower() and 'ANTI-calibrated' in tip
    assert 'Never quote it as an uncertainty.' in tip


def test_the_band_percentages_are_never_typed_twice():
    """The `#224` scar: a number hand-kept in several places drifts. Both
    the checkbox label and the tooltip interpolate sldea_plot's
    constants, so the window cannot name a band it does not draw."""
    assert f"±{sp.MACHINE_BAND_PCT:g}%" in g.BANDS_TIP
    with _Win('1200x800') as w:
        if not w.ok:
            return
        label = w.win.cb_bands.cget('text')
        assert f"±{sp.MACHINE_BAND_PCT:g}%" in label, label
        assert f"±{sp.TRACED_BAND_PCT:g}%" in label, label
        assert w.win.tip_bands.text == g.BANDS_TIP
        # ...and it is really hung on the checkbox, not just stored
        assert '<Enter>' in w.win.cb_bands.bind()


def test_the_tooltip_is_a_copy_not_a_cross_seam_import():
    """The module keeps its own ~35-line Tooltip, exactly as
    sldea_edge_gui does, because ui_widgets is on the other side of the
    open-decision-2 repo split. Importing it here would plant a
    dependency on the split's own boundary."""
    import re
    import sldea_plot_gui
    src = open(sldea_plot_gui.__file__, encoding='utf-8').read()
    # a real import STATEMENT, not the comment that names the one to
    # write if the split is ever abandoned
    assert not re.search(r'(?m)^\s*(from|import)\s+ui_widgets\b', src)
    # nothing this file imports drags it in transitively either
    assert 'ui_widgets' not in _sys.modules, 'pulled in through the seam'
    assert hasattr(g, 'Tooltip') and hasattr(g, 'add_tooltip')
    assert 'COPIED, NOT IMPORTED' in src, 'the copy does not say it is one'


# ---------------------------------------------------------------------------
# `#271` -- resize, scrollbars, minimum size
#
# NOTE ON ORDERING: _run() calls the tests in sorted order and
# test_importing_the_module_opens_no_window asserts tk._default_root is
# None. Every window below is destroyed in a finally, which resets it
# (verified), so the two cannot collide either way round.
# ---------------------------------------------------------------------------

class _Win:
    """A real, on-screen plot window over a two-run fixture, or None-ish.

    Context manager: builds the fixture, opens the window, destroys both.
    `ok` is False when there is no display, and the caller returns.
    """

    def __init__(self, size='1400x900'):
        self.size = size
        self.ok = False

    def __enter__(self):
        import tkinter as tk
        self.tmp = _mktmp()
        _fake_run(self.tmp, 'P3_1_20260805')
        _fake_run(self.tmp, 'P3_2_20260805')
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            print(f"   (skipped: no display for Tk: {e})")
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.root = None
            return self
        self.root.geometry(self.size)
        self.win = g.PlotWindow(self.root, self.tmp,
                                preselect=['P3_1_20260805'])
        self.root.update()
        self.settle()
        self.ok = True
        return self

    def settle(self, secs=0.6):
        """Pump the loop until the coalesced redraw has fired and Tk has
        finished re-laying the window out."""
        t0 = time.time()
        while time.time() - t0 < secs:
            self.root.update()
            time.sleep(0.02)

    def resize(self, size):
        self.root.geometry(size)
        self.settle()

    def __exit__(self, *_exc):
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


def test_resize_the_figure_follows_the_window():
    """THE `#271` bug. The window bound <Configure> on the matplotlib
    widget WITHOUT add='+', which REPLACES FigureCanvasTkAgg's own
    `resize` -- the only thing that tells the Figure how many inches it
    has. So the figure stayed 12.6x5.4 in forever and tight_layout laid
    every redraw out against a size the window had not had since it
    opened: clipped on the right, blank below, at every size including
    the default."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        for size in ('1400x900', '1000x640', '820x520', '1200x780'):
            w.resize(size)
            widget = w.win.canvas.get_tk_widget()
            px = w.win.fig.get_size_inches() * w.win.fig.dpi
            assert abs(px[0] - widget.winfo_width()) <= 2, (size, px)
            assert abs(px[1] - widget.winfo_height()) <= 2, (size, px)
        # ...and the binding that carries it is still BOTH handlers: a
        # future plain bind() here would silently restore the bug, so the
        # tag itself is pinned, not just today's symptom
        script = w.win.canvas.get_tk_widget().bind('<Configure>')
        assert 'resize' in script, "matplotlib's resize was unbound again"
        assert script.count('\n\nif ') >= 1, "our handler replaced it"


def test_short_window_keeps_the_toolbar_and_the_warnings_pane():
    """`#271`: pack fills each slave's request from the cavity IN ORDER,
    so with the figure packed first it took its full requested height and
    pushed the toolbar and the message pane off the bottom -- measured at
    900x560, both unmapped, the warnings simply gone with nothing saying
    so. They claim their space first now."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        for size in ('1400x900', '900x560', '760x500'):
            w.resize(size)
            assert w.win.msg.winfo_ismapped(), f"warnings pane gone at {size}"
            assert w.win.toolbar.winfo_ismapped(), f"toolbar gone at {size}"
            assert w.win.canvas.get_tk_widget().winfo_height() > 40, size


def test_the_controls_column_scrolls_only_when_it_overflows():
    """`#271` + the `#225` decision: the bar is a REPORT of overflow, not
    furniture. It appears when the controls do not fit, goes away when
    they do -- and rewinds on the way out, or a column scrolled halfway
    down and then given room would keep an offset nobody can undo."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        col = w.win.column
        tall = col.body.winfo_reqheight()
        assert tall > 200, 'fixture built no controls to overflow'
        w.resize(f'1000x{tall + 120}')
        assert not col.bar_shown, 'bar shown with room to spare'
        assert not col.bar.winfo_ismapped()
        w.resize(f'1000x{max(g.MIN_H, tall - 200)}')
        assert col.bar_shown, 'no bar with the controls cut off'
        assert col.bar.winfo_ismapped()
        col._cv.yview_moveto(0.5)
        w.resize(f'1000x{tall + 120}')
        assert not col.bar_shown and not col.bar.winfo_ismapped()
        assert col._cv.yview()[0] == 0.0, 'hidden bar left the column scrolled'


def test_the_window_has_a_floor_it_cannot_collapse_below():
    """`#271`: minsize was (120, 1) -- the layout could be squeezed to
    nothing. The width is MEASURED from the controls column, because a
    number that is right on the analysis PC is wrong at another DPI."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        mw, mh = w.win.root.minsize()
        assert (mw, mh) == w.win.min_size, (mw, mh, w.win.min_size)
        assert mh == g.MIN_H, (mw, mh)
        # the width is the MEASURED column plus a figure worth drawing,
        # and it is the same number before and after the window is laid
        # out -- the canvas does not know its own width until then, so a
        # floor read off IT came out 34 px
        assert mw == w.win.apply_minsize()[0], 'not re-measurable'
        assert mw == w.win.column.natural_width() + g.MIN_FIG_W, (mw, mh)
        assert mw > g.MIN_FIG_W + 150 and mh > 100
        # the floor is a floor: the figure still has room to be a figure
        w.resize(f'{mw}x{mh}')
        assert w.win.canvas.get_tk_widget().winfo_width() >= 100
        assert w.win.msg.winfo_ismapped() and w.win.toolbar.winfo_ismapped()


def test_moving_the_window_does_not_cost_a_redraw():
    """`#271`: <Configure> also fires when the canvas merely MOVES -- and
    it does move, by the scrollbar's width, every time the bar appears. A
    full prepare_runs + matplotlib pass for that is work nobody asked
    for, so the handler compares the SIZE."""
    with _Win('1200x800') as w:
        if not w.ok:
            return
        class _E:
            def __init__(self, wd, ht):
                self.width, self.height = wd, ht
        n = []
        w.win.schedule = lambda *_a: n.append(1)
        cur = w.win._canvas_size
        w.win._canvas_configured(_E(*cur))          # same size: a move
        assert n == [], 'a move scheduled a redraw'
        w.win._canvas_configured(_E(cur[0] - 60, cur[1]))
        assert n == [1], 'a real resize did not schedule a redraw'


# ---------------------------------------------------------------------------
# `#274` -- double-click through to Edge Review
# ---------------------------------------------------------------------------

def _prepared(parent, names, **opt_kw):
    """(runs, opts) as the window holds them -- through sldea_plot's own
    prepare_runs, so the tests see exactly what the figure was drawn
    from."""
    opts, err = sp.make_opts(**opt_kw)
    assert not err, err
    runs = sp.prepare_runs([os.path.join(parent, n) for n in names], opts,
                           lambda _m: None, allow_suspect=False)
    return runs, opts


class _Popen:
    """Records the argv instead of starting a program."""

    def __init__(self):
        self.calls = []

    def Popen(self, cmd, **kw):
        self.calls.append((list(cmd), kw))
        return self


def test_plot_points_indexes_the_rows_the_mode_actually_draws():
    """`#274`: what a double-click asks is 'which snapshot is that', and
    a snapshot IS a row -- the frame Edge Review would open. The index
    must therefore hold rows, and only the ones the mode plots."""
    p = _mktmp()
    try:
        _fake_run(p, 'A_run', processed=True)
        _fake_run(p, 'B_run', processed=False)      # raw: no areas
        runs, opts = _prepared(p, ['A_run'], mode='area')
        pts = g.plot_points(runs, opts, panel=0)
        assert [r['index'] for _x, _y, _run, r in pts] == [0, 1]
        assert [(x, y) for x, y, _r, _w in pts] == [
            (0.0, 201.062), (1.0, 201.062)]
        # the A/A0 panel plots the SAME rows against the normalized value
        norm = g.plot_points(runs, opts, panel=1)
        a0 = runs[0]['a0']
        assert [r['index'] for _x, _y, _run, r in norm] == [0, 1]
        assert all(abs(y - 201.062 / a0) < 1e-9 for _x, y, _r, _w in norm)
        # current mode works on a RAW run, and indexes it
        runs, opts = _prepared(p, ['B_run'], mode='current')
        pts = g.plot_points(runs, opts)
        assert [r['index'] for _x, _y, _run, r in pts] == [0, 1]
        assert [y for _x, y, _r, _w in pts] == [-16.0, -15.9]
        # power is the offset-corrected product, through sldea_plot's own
        # power_mw -- this module owns no measurement rule of its own
        runs, opts = _prepared(p, ['B_run'], mode='power')
        med = sp.run_ua_median(runs[0])
        assert [y for _x, y, _r, _w in g.plot_points(runs, opts)] == [
            sp.power_mw(r, med) for r in runs[0]['rows']]
        # a row with no plottable coordinate is not a click target
        runs, opts = _prepared(p, ['B_run'], mode='current', vs_area=True)
        assert g.plot_points(runs, opts) == [], 'raw run has no areas'
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_nearest_point_measures_in_screen_pixels_not_data_units():
    """The trap `#274` had to avoid: kV runs 0-10 while mm² runs 150-250,
    so a distance in DATA space is dominated by whichever axis carries
    the bigger numbers and 'nearest' quietly means 'nearest in y'."""
    from matplotlib.figure import Figure
    p = _mktmp()
    try:
        _fake_run(p, 'A_run', processed=True)
        runs, opts = _prepared(p, ['A_run'], mode='area')
        fig = Figure(figsize=(12.6, 5.4), dpi=100)
        sp.draw(fig, runs, opts)
        fig.canvas.draw()
        ax = fig.axes[0]
        pts = g.plot_points(runs, opts, panel=0)
        (x0, y0, _r0, row0), (x1, y1, _r1, row1) = pts
        px0, py0 = ax.transData.transform((x0, y0))
        px1, py1 = ax.transData.transform((x1, y1))
        # dead on a marker
        hit = g.nearest_point(ax, pts, px0, py0)
        assert hit is not None and hit[1]['index'] == row0['index']
        assert hit[2] < 1e-6
        # a few pixels away is still that marker...
        hit = g.nearest_point(ax, pts, px0 + 8, py0 - 6)
        assert hit is not None and hit[1]['index'] == row0['index']
        # ...and past the tolerance nothing is returned rather than
        # something arbitrary
        assert g.nearest_point(ax, pts, px0, py0 - g.PICK_PX - 40) is None
        # THE PIXEL RULE. The two rows share a y (both 201.062 mm2) and
        # differ by 1.0 in x, which is a small number in DATA units and a
        # long way in pixels -- so a click by the second marker resolves
        # to the second row, which a data-space metric would fumble.
        assert abs(px1 - px0) > 200, 'fixture is not separated on screen'
        hit = g.nearest_point(ax, pts, px1 + 4, py1)
        assert hit is not None and hit[1]['index'] == row1['index']
        assert g.nearest_point(ax, [], px0, py0) is None
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_a_double_click_launches_edge_review_on_that_exact_frame():
    """The whole `#274` chain: event -> nearest row -> a sibling process
    on that run with `--goto` carrying the 0-BASED CSV row. The row
    number is the hand-off `#255` is on record about, so it is pinned
    here and translated at the Edge Review end, never here."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        win = w.win
        assert win._prepared, 'nothing was prepared to click on'
        opts, err = win.current_opts()
        assert not err
        ax = win.fig.axes[0]
        pts = g.plot_points(win._prepared, opts, panel=0)
        _x, _y, run, row = pts[1]
        px, py = ax.transData.transform((_x, _y))

        class _Ev:
            def __init__(self, dbl=True):
                self.dblclick, self.inaxes = dbl, ax
                self.x, self.y = px, py
        spy = _Popen()
        real = g.subprocess
        g.subprocess = spy
        try:
            got = win.on_click(_Ev())
            assert got is not None, 'the double-click resolved nothing'
            assert got[1]['index'] == row['index']
            assert len(spy.calls) == 1, spy.calls
            cmd, kw = spy.calls[0]
            assert cmd[0] == _sys.executable
            assert os.path.basename(cmd[1]) == 'sldea_edge_gui.py'
            assert os.path.exists(cmd[1]), cmd[1]
            assert os.path.abspath(cmd[2]) == os.path.abspath(run['dir'])
            assert cmd[3] == '--goto' and cmd[4] == str(row['index'])
            assert kw.get('start_new_session') is True   # it outlives us
            # the window SAYS what it opened -- a click that silently
            # started a program somewhere is worse than one that did
            # nothing
            said = win.lbl_click.cget('text')
            assert run['name'] in said and str(row['index']) in said
            # a SINGLE click is not a launch: single-click belongs to the
            # toolbar's pan and zoom rectangles
            spy.calls.clear()
            assert win.on_click(_Ev(dbl=False)) is None
            assert spy.calls == []
            # neither is a double-click off the axes, or on empty space
            class _Off:
                dblclick, inaxes, x, y = True, None, 0, 0
            assert win.on_click(_Off()) is None and spy.calls == []
            class _Miss:
                dblclick, inaxes = True, ax
                x, y = px, py - g.PICK_PX - 200
            assert win.on_click(_Miss()) is None and spy.calls == []
            assert 'no data point within' in win.lbl_click.cget('text')
        finally:
            g.subprocess = real


def test_the_click_through_is_discoverable_and_does_not_go_stale():
    """`#274` asked for a hint, because an undocumented double-click is
    a feature nobody finds. The same line reports what the last click
    resolved to -- and a redraw takes that report back down, since the
    answer belonged to the figure that was on screen when it was made."""
    assert 'Double-click' in g.CLICK_HINT and 'Edge Review' in g.CLICK_HINT
    with _Win('1200x800') as w:
        if not w.ok:
            return
        assert w.win.lbl_click.cget('text') == g.CLICK_HINT
        spy = _Popen()
        real = g.subprocess
        g.subprocess = spy
        try:
            run = w.win._prepared[0]
            w.win.open_in_edge_review(run, run['rows'][1])
            assert w.win.lbl_click.cget('text') != g.CLICK_HINT
            w.win.redraw()
            assert w.win.lbl_click.cget('text') == g.CLICK_HINT
        finally:
            g.subprocess = real


def _run():
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    for n in names:
        globals()[n]()
        print('ok ', n)
    print(f"{len(names)} tests passed")


if __name__ == '__main__':
    _run()
