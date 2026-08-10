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


def _shut(root):
    """Destroy a test root WITHOUT the orphaned-callback noise.

    PlotWindow debounces every redraw through root.after, so a window
    built and torn down before the loop ever runs leaves one pending and
    Tk's background error handler prints `invalid command name
    ...redraw`. Harmless -- but noise on a test console is where a real
    failure goes to hide, and these cases are read by counting.

    Cancelled by Tcl id rather than per window, because the precedence
    case builds several on one root and keeps only the last."""
    try:
        for after_id in root.tk.splitlist(root.tk.call('after', 'info')):
            try:
                root.after_cancel(after_id)
            except Exception:
                pass
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


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


class _Skip(Exception):
    """Raised by a case this desktop cannot host. Counted, never silent."""


def _need_room(w, col, tall):
    """Skip unless the window actually GOT the height the case asked for.

    Tk clamps a geometry request to the work area silently. On a 1573x841
    desktop the window stopped at 822 px, the controls really did still
    overflow, and `assert not col.bar_shown` failed -- reported for a week
    as a fifth "environmental" suite failure when the code was correct and
    the SCREEN was too short (diagnosed 2026-08-09).

    Two cases share this premise, so guarding only one leaves the other
    failing identically. The Draw column needs roughly `tall + 120` of
    window, which wants ~1150 px of screen once the title bar and taskbar
    are taken -- note that the 1920x1080 vm-setup asks for does NOT clear
    it. `#268` added two more Draw rows, which is what finally pushed this
    desktop under the line and exposed the bug below.

    The screen size goes in the message through `w.win.root`: `w.win` is a
    PlotWindow, not a Tk widget, so the original `w.win.winfo_screenwidth()`
    raised AttributeError instead of skipping -- the guard turned every
    too-short desktop into a hard error, which is precisely the failure it
    was written to prevent. It had never fired on a desktop tall enough to
    run both cases, so nothing caught it (fixed 2026-08-10).
    """
    have = col._cv.winfo_height()
    if have < tall:
        raise _Skip(
            f'desktop too short: the column needs {tall}px and the window '
            f'could only give it {have}px (screen '
            f'{w.win.root.winfo_screenwidth()}x'
            f'{w.win.root.winfo_screenheight()})')


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
        # remember=False: these cases are about layout and clicking, and
        # they must not read (or write) the real user's `#275` options
        self.win = g.PlotWindow(self.root, self.tmp,
                                preselect=['P3_1_20260805'],
                                remember=False)
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
            _shut(self.root)
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
        # ...and the CHEAP resize path lays the figure out where the
        # expensive one would (`#316`). A resize re-runs the remembered
        # tight_layout instead of rebuilding 742 artists to rediscover
        # it, and a shortcut that landed somewhere else would be a second
        # layout engine rather than a shortcut. It is not automatic:
        # tight_layout reads wspace off the axes it finds, so run on its
        # own output it drifted the panels 8-12% narrower.
        for size in ('900x600', '1300x850', '900x600'):
            w.resize(size)
            shortcut = [tuple(ax.get_position().bounds)
                        for ax in w.win.fig.axes]
            assert shortcut, f'nothing drawn to lay out at {size}'
            w.win._drawn_key = None            # forces the full rebuild
            w.win.redraw()
            assert [tuple(ax.get_position().bounds)
                    for ax in w.win.fig.axes] == shortcut, \
                f'the resize shortcut is not what a rebuild lays out ({size})'


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
        _need_room(w, col, tall)
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


def _settled_redraws(w, n, secs=3.0):
    """Pump until the coalesced redraw lands. -> the redraws counted."""
    t0 = time.time()
    while time.time() - t0 < secs and not n:
        w.root.update()
        time.sleep(0.01)
    return n


def test_a_resize_burst_costs_one_redraw():
    """`#316`: the 120 ms debounce coalesced NOTHING during a resize drag.

    Measured against the campaign corpus -- 13 runs on one area figure, a
    real 3.5 s mouse drag on the window edge -- 3 to 5 <Configure> events
    reached the canvas and 3 to 5 FULL REDRAWS came back. One for one.
    A drag does not fire <Configure> per pixel: each redraw costs 480 ms
    there and BLOCKS THE TK LOOP for all of it, so the next event cannot
    arrive until long after a 120 ms timer has expired and fired. The
    debounce was not late to the drag; the drag was throttled to the
    debounce.

    Both halves of the fix are asked for separately, because either alone
    passes one of these and fails the other:

      * the resize window has to outlast the gap a drag really leaves
        between events (280-500 ms measured, being matplotlib's own
        resize render plus the WM's dispatch) -- so the first burst
        spaces its events over that gap with the loop FREE;
      * and it cannot be only a longer number, because that gap is the
        cost of servicing one resize and grows with the series count --
        so the second burst BLOCKS the loop past the window, and the
        redraw has to keep deferring while its timer comes up late.

    COUNTS, not durations: a duration would pin this desktop's speed,
    which is not what went wrong.
    """
    with _Win('1200x800') as w:
        if not w.ok:
            return

        class _E:
            def __init__(self, wd, ht):
                self.width, self.height = wd, ht
        n = []
        w.win.redraw = lambda: n.append(1)
        wide, tall = w.win._canvas_size

        def burst(count, gap, block, start):
            """`count` resize events `gap` apart; `block` of that gap is
            the loop being unavailable, as a matplotlib render makes it."""
            for i in range(count):
                w.win._canvas_configured(_E(wide - start - 10 * i, tall))
                time.sleep(block)
                t0 = time.time()
                while time.time() - t0 < gap - block:
                    w.root.update()
                    time.sleep(0.01)
                w.root.update()

        # a drag the loop keeps up with: the events are simply further
        # apart than a click's worth of quiet
        burst(6, 0.35, 0.0, 20)
        assert n == [], f'a live drag redrew {len(n)} times'
        assert _settled_redraws(w, n) == [1], \
            f'a settled drag redrew {len(n)} times, want 1'
        # a drag the loop CANNOT keep up with: every timer comes up late
        del n[:]
        burst(4, 0.0, (g.RESIZE_MS + g.LATE_MS + 80) / 1000.0, 120)
        assert n == [], f'a blocked drag redrew {len(n)} times'
        assert _settled_redraws(w, n) == [1], \
            f'a settled blocked drag redrew {len(n)} times, want 1'
        # ...and the ordinary case is untouched: a toggle blocks nothing,
        # so its timer is on time and its redraw is not held back
        del n[:]
        for _ in range(5):
            w.win.schedule()
            w.root.update()
        assert _settled_redraws(w, n) == [1], \
            f'a burst on an idle loop redrew {len(n)} times'


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


# ---------------------------------------------------------------------------
# `#275` -- remembered options, per parent folder
# ---------------------------------------------------------------------------

def test_remembered_options_live_outside_the_repo_and_the_run_folders():
    """`#275`: user scope. Run data never carries a UI preference, the
    campaign corpus is read-only, and nothing may need a .gitignore entry
    because nothing can land in the tree."""
    here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    home = os.path.expanduser('~')
    for p in (g.OPTIONS_PATH, g.OPTIONS_FALLBACK):
        assert os.path.isabs(p), p
        assert p.startswith(home), p
        rel = os.path.relpath(p, here)
        assert rel.startswith(os.pardir), f"{p} is inside the checkout"
    assert g.OPTIONS_PATH != g.OPTIONS_FALLBACK
    # the fallback is the launcher's own cache dir -- the primary was left
    # root-owned in one user's home by the desktop installer
    assert '.cache' in g.OPTIONS_FALLBACK


def test_remembered_options_round_trip_per_parent_folder():
    p = _mktmp()
    try:
        cfg = os.path.join(p, 'opts.json')
        a, b = os.path.join(p, 'campaignA'), os.path.join(p, 'campaignB')
        opts, _e = sp.make_opts(mode='power', prepost=True, bands=False)
        assert g.save_options(a, opts, out_dir=None, path=cfg) == cfg
        got = g.load_options(a, path=cfg)
        assert got == {'mode': 'power', 'prepost': True, 'mean': False,
                       'bands': False, 'breakdown': True,
                       'vs_area': False, 'logx': False, 'logy': False,
                       'marker_key': True, 'subplots': 'both',
                       'cadence_guard': False, 'aggregate': False,
                       'aggregate_exact': False,
                       # `#314`'s pair joins for a different reason from
                       # every key above it: not how the figure is drawn,
                       # but what it is written as. A house that exports
                       # SVG at 600 dpi does so every time, and having to
                       # re-pick the format per session is the same
                       # annoyance the draw options were remembered to
                       # end. The stem and the titles still stay out --
                       # they name ONE figure; a format does not.
                       'fmt': 'png', 'dpi': 300}, got
        # the `#268` pair joins because both are HOW THE FIGURE IS DRAWN,
        # which is the whole membership rule: whether a reader wants the
        # cross-run mean, and whether they want it pooled on exact keys,
        # are house-style answers that outlive one figure -- unlike a
        # title, which names one. Neither is a run selection either.
        # spelled out rather than derived, so a key that quietly joins
        # REMEMBERED has to be argued for here too
        assert set(got) == set(g.REMEMBERED), set(got) ^ set(g.REMEMBERED)
        # a different parent is a different memory, and saving one does
        # not disturb the other
        assert g.load_options(b, path=cfg) == {}
        opts2, _e = sp.make_opts(mode='current')
        g.save_options(b, opts2, out_dir=os.path.join(p, 'figs'), path=cfg)
        assert g.load_options(a, path=cfg)['mode'] == 'power'
        assert g.load_options(b, path=cfg)['out_dir'] == os.path.join(p,
                                                                     'figs')
        # the key is case-insensitive on Windows, where a path differs in
        # case without differing
        assert g.options_key(a) == g.options_key(a.upper()) or \
            os.path.normcase('A') == 'A'
        # NO title and no stem is ever remembered: they name one figure,
        # and last week's caption over this week's runs is a wrong label
        # that looks like a right one. The two PANEL headings are the same
        # answer for the same reason -- they caption two panels of one
        # figure, so they stay out while every other drawing option went in
        opts3, _e = sp.make_opts(title='P3 batch, first pass',
                                 title_first='mm² vs kV',
                                 title_second='normalized')
        g.save_options(a, opts3, path=cfg)
        back = g.load_options(a, path=cfg)
        for k in ('title', 'title_first', 'title_second', 'stem'):
            assert k not in back, k
        # and the on-disk file cannot carry one back in either, however it
        # got there -- _clean_options drops what it does not recognize
        assert 'title_first' not in g._clean_options(
            {'title_first': 'from a hand edit', 'logy': True})
        assert g._clean_options({'logy': True})['logy'] is True
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_a_corrupt_or_stale_options_file_can_only_cost_the_memory():
    """`#275`'s hard requirement: it must never prevent launch. Every one
    of these yields {} and the window opens on the defaults."""
    p = _mktmp()
    try:
        cfg = os.path.join(p, 'opts.json')
        assert g.load_options(p, path=os.path.join(p, 'nope.json')) == {}
        for junk in ('', '{', 'null', '[]', '"a string"',
                     '{"parents": 7}', '{"parents": {"x": 7}}',
                     '\x00\xff binary'):
            with open(cfg, 'w', encoding='utf-8', errors='replace') as f:
                f.write(junk)
            assert g.load_options(p, path=cfg) == {}, junk
        # a file of the right shape carrying values that are no longer
        # valid: each bad field is dropped, the good ones survive
        with open(cfg, 'w', encoding='utf-8') as f:
            f.write('{"version": 1, "parents": {"%s": {"mode": "spectrum",'
                    ' "bands": "yes", "prepost": true, "junk": 1,'
                    ' "subplots": "third", "logy": "on", "out_dir": ""}}}'
                    % g.options_key(p).replace('\\', '\\\\'))
        got = g.load_options(p, path=cfg)
        # 'third' is dropped like 'spectrum' and for the same reason: both
        # are NAMES, checked against sldea_plot's own vocabulary rather
        # than against a list retyped here
        assert got == {'prepost': True}, got
        # and saving over junk starts clean instead of failing
        opts, _e = sp.make_opts(mode='current')
        with open(cfg, 'w', encoding='utf-8') as f:
            f.write('not json at all')
        assert g.save_options(p, opts, path=cfg) == cfg
        assert g.load_options(p, path=cfg)['mode'] == 'current'
        # an unwritable target is reported, not raised
        assert g.save_options(p, opts,
                              path=os.path.join(p, 'no', 'such', 'x', '')) \
            is None
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_explicit_arguments_beat_remembered_which_beat_defaults():
    """The `#275` precedence rule, and the one thing it cannot see: the
    CLI hands over a COMPLETE opts dict whether or not a flag was given,
    so a field on its default is indistinguishable from an unset one."""
    base, _e = sp.make_opts()
    assert g.explicit_opts(None) == set()
    assert g.explicit_opts(base) == set(), 'defaults are not statements'
    said, _e = sp.make_opts(mode='power', bands=False)
    assert g.explicit_opts(said) == {'mode', 'bands'}
    # `--mode area` IS the default, so it reads as unset -- stated, not
    # hidden, in explicit_opts' docstring
    same, _e = sp.make_opts(mode='area')
    assert 'mode' not in g.explicit_opts(same)
    # It diffs against make_opts' OWN defaults, so an option added to the
    # engine is picked up with no edit here -- pinned, because the wiring
    # that carries a `--logy --gui` preselection into the window rests on
    # it. Each of the seven, including the two whose default is not False.
    for kw, want in ((dict(logx=True), 'logx'), (dict(logy=True), 'logy'),
                     (dict(marker_key=False), 'marker_key'),
                     (dict(cadence_guard=True), 'cadence_guard'),
                     (dict(subplots='first'), 'subplots'),
                     (dict(title_first='mm² vs kV'), 'title_first'),
                     (dict(title_second='A/A₀'), 'title_second')):
        said, _e = sp.make_opts(**kw)
        assert g.explicit_opts(said) == {want}, (kw, g.explicit_opts(said))
    # ...and the defaults of those same seven are still not statements
    assert g.explicit_opts(base) == set()
    for k in ('logx', 'logy', 'marker_key', 'cadence_guard', 'subplots',
              'title_first', 'title_second'):
        assert k in base, f"{k} is not in make_opts' defaults to diff against"


def test_the_window_applies_the_precedence_it_documents():
    p = _mktmp()
    try:
        _fake_run(p, 'R1')
        cfg = os.path.join(p, 'opts.json')
        remembered, _e = sp.make_opts(mode='power', prepost=True,
                                      bands=False)
        g.save_options(p, remembered, out_dir=os.path.join(p, 'figs'),
                       path=cfg)
        real = g.OPTIONS_PATH
        g.OPTIONS_PATH = cfg
        import tkinter as tk
        try:
            try:
                root = tk.Tk()
            except tk.TclError as e:
                print(f"   (skipped: no display for Tk: {e})")
                return
            root.withdraw()
            try:
                # no args at all: remembered beats the defaults
                w = g.PlotWindow(root, p)
                assert w.v_mode.get() == 'power'
                assert w.v_prepost.get() is True
                assert w.v_bands.get() is False
                assert w.v_out.get() == os.path.join(p, 'figs')
                assert w._out_chosen is True
                # an explicit option beats the remembered one, and the
                # ones it does not mention stay remembered
                cli, _e = sp.make_opts(mode='current', bands=False)
                w = g.PlotWindow(root, p, opts=cli)
                assert w.v_mode.get() == 'current'
                assert w.v_prepost.get() is True, 'lost the remembered one'
                # an explicit out_dir beats the remembered one
                w = g.PlotWindow(root, p, out_dir=os.path.join(p, 'other'))
                assert w.v_out.get() == os.path.join(p, 'other')
                # remember=False is the defaults, whatever is on disk
                w = g.PlotWindow(root, p, remember=False)
                assert w.v_mode.get() == 'area' and w.v_bands.get() is True
                assert w.remember_now() is None, 'wrote anyway'
                # ...and the round trip: change something, remember it
                w = g.PlotWindow(root, p)
                w.v_mode.set('current')
                w.v_breakdown.set(False)
                assert w.remember_now() == cfg
                assert g.load_options(p, path=cfg)['mode'] == 'current'
                assert g.load_options(p, path=cfg)['breakdown'] is False
                # the new drawing options round-trip with the rest, and
                # the panel headings deliberately do not come back
                w = g.PlotWindow(root, p)
                w.v_mode.set('area')
                w.v_logy.set(True)
                w.v_marker_key.set(False)
                w.v_cadence.set(True)
                w.v_subplots.set('first')
                w.v_title_first.set('one figure, one caption')
                assert w.remember_now() == cfg
                back = g.load_options(p, path=cfg)
                assert back['logy'] is True and back['marker_key'] is False
                assert back['cadence_guard'] is True
                assert back['subplots'] == 'first'
                assert 'title_first' not in back and 'title' not in back
                w = g.PlotWindow(root, p)
                assert w.v_logy.get() is True
                assert w.v_subplots.get() == 'first'
                assert w.v_cadence.get() is True
                assert w.v_title_first.get() == '', 'a caption came back'
                # a HAND-EDITED file is the only route to the one pair
                # make_opts refuses (the window can never save it), and
                # populate() -> _mode_changed corrects it BEFORE the first
                # redraw rather than showing an error where the figure goes
                import json
                with open(cfg, encoding='utf-8') as f:
                    blob = json.load(f)
                blob['parents'][g.options_key(p)].update(
                    {'mode': 'current', 'subplots': 'second'})
                with open(cfg, 'w', encoding='utf-8') as f:
                    json.dump(blob, f)
                w = g.PlotWindow(root, p)
                assert w.v_mode.get() == 'current'
                assert w.v_subplots.get() == 'both', w.v_subplots.get()
                assert not w.current_opts()[1], 'opened on an error'
            finally:
                _shut(root)
        finally:
            g.OPTIONS_PATH = real
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_closing_cancels_the_pending_redraw_before_it_destroys_the_root():
    """`#283`: _closing destroyed the root with the debounced redraw still
    queued, so a close landing inside REDRAW_MS -- pick a run, reach
    straight for the X -- left a callback pointing at a command Tk had
    just deleted and printed `invalid command name ...redraw`.

    Measured AT THE MOMENT OF DESTROY, because that is the last instant
    the interpreter can be asked what it still has queued; a pending id
    naming a deleted command IS the Tcl error, one step earlier. The
    `#275` order is pinned with it: the options are on disk by then, so
    remember_now ran while the widgets it reads were still alive.

    The module's only other after() is Tooltip's hover timer, which
    cancels itself on <Destroy> -- asserted here rather than assumed,
    since _closing's docstring leans on it."""
    import tkinter as tk
    p = _mktmp()
    root = None
    try:
        _fake_run(p, 'R1')
        cfg = os.path.join(p, 'opts.json')
        real = g.OPTIONS_PATH
        g.OPTIONS_PATH = cfg
        try:
            try:
                root = tk.Tk()
            except tk.TclError as e:
                print(f"   (skipped: no display for Tk: {e})")
                return
            root.withdraw()
            win = g.PlotWindow(root, p, preselect=['R1'])     # remember=True
            win.schedule()                     # THE BUG'S STATE: one pending
            pending = win._redraw_after
            queued = set(root.tk.splitlist(root.tk.call('after', 'info')))
            assert pending is not None and pending in queued, \
                'the fixture never armed a redraw to be orphaned'
            win.tip_bands._schedule()
            tip_id = win.tip_bands._after_id
            assert tip_id in set(root.tk.splitlist(
                root.tk.call('after', 'info')))

            seen = {}
            real_destroy = root.destroy

            def spy():
                seen['queued'] = set(root.tk.splitlist(
                    root.tk.call('after', 'info')))
                seen['remembered'] = os.path.exists(cfg)
                real_destroy()

            root.destroy = spy
            try:
                win._closing()
            finally:
                del root.destroy
            assert seen, '_closing never reached destroy'
            assert pending not in seen['queued'], \
                'the debounced redraw was still queued when the root died'
            assert win._redraw_after is None, 'the id was left behind'
            assert seen['remembered'], \
                'the options were not remembered before the destroy'
            assert g.load_options(p, path=cfg), 'remember_now wrote nothing'
            # the tooltip timer goes with the widget it hangs off, during
            # the destroy rather than before it -- which is why _closing
            # does not repeat the cancellation
            assert win.tip_bands._after_id is None, \
                'a hover timer outlived the window'
        finally:
            g.OPTIONS_PATH = real
    finally:
        if root is not None:
            _shut(root)
        shutil.rmtree(p, ignore_errors=True)


# ---------------------------------------------------------------------------
# the engine options in the Draw column (`#263` log scales, `#267` marker
# key, `#269` panel headings, `#270` panel selection, `#264` cadence guard)
#
# These ask what reached make_opts and what reached the FIGURE -- axis
# scale, axes count, headings, which legend the key made -- rather than how
# any of it looks, so they run on a withdrawn root. The layout case at the
# end is the one that needs a real window, for the `#271` reason.
# ---------------------------------------------------------------------------

class _Bare:
    """A WITHDRAWN plot window over a one-run fixture, or None-ish.

    Context manager: builds the fixture, opens the window, destroys both.
    `ok` is False when there is no display, and the caller returns.

    remember=False throughout: the wiring cases must not read -- or
    write -- the real user's `#275` options file.
    """

    def __init__(self, **kw):
        self.kw = kw
        self.ok = False

    def __enter__(self):
        import tkinter as tk
        self.tmp = _mktmp()
        _fake_run(self.tmp, 'R1')
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            print(f"   (skipped: no display for Tk: {e})")
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.root = None
            return self
        self.root.withdraw()
        self.win = g.PlotWindow(self.root, self.tmp, preselect=['R1'],
                                remember=False, **self.kw)
        self.ok = True
        return self

    def __exit__(self, *_exc):
        if self.root is not None:
            _shut(self.root)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


def _state(widget):
    """ttk hands `state` back as a Tcl object; compare it as text."""
    return str(widget.cget('state'))


def test_every_draw_option_reaches_the_opts_the_figure_is_drawn_from():
    """THE wiring gap. current_opts() built its dict from seven variables
    and let the other seven fall back to make_opts' defaults, so a tick
    box could sit on screen saying one thing while every redraw drew
    another."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        base, _e = win.current_opts()
        assert base['logx'] is False and base['marker_key'] is True
        assert base['subplots'] == 'both' and base['cadence_guard'] is False
        win.v_logx.set(True)
        win.v_logy.set(True)
        win.v_marker_key.set(False)
        win.v_cadence.set(True)
        win.v_subplots.set('first')
        win.v_title_first.set('  mm² vs kV  ')
        win.v_title_second.set('A/A₀')
        opts, err = win.current_opts()
        assert not err, err
        assert opts['logx'] is True and opts['logy'] is True
        assert opts['marker_key'] is False
        assert opts['cadence_guard'] is True
        assert opts['subplots'] == 'first'
        # stripped, and None rather than '' when blank -- the same rule the
        # legacy title row has always followed, because _panel_title reads
        # blank as 'no override' and not as an empty heading
        assert opts['title_first'] == 'mm² vs kV'
        assert opts['title_second'] == 'A/A₀'
        win.v_title_first.set('   ')
        assert win.current_opts()[0]['title_first'] is None


def test_the_draw_options_reach_the_figure_not_just_the_dict():
    """Measured off the drawn Figure, because a dict that says 'logy' and
    a figure that is linear is exactly the bug this wiring is for."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        win.redraw()
        assert len(win.fig.axes) == 2, 'area mode draws two panels'
        assert win.fig.axes[0].get_yscale() == 'linear'
        # `#270`: a single chosen panel is the figure's ONLY axes, so it
        # gets the whole canvas instead of half a two-column grid
        win.v_subplots.set('second')
        win.redraw()
        assert len(win.fig.axes) == 1
        win.v_subplots.set('both')
        # `#263`: every plotted area is positive here, so this is log10
        win.v_logy.set(True)
        win.redraw()
        assert win.fig.axes[0].get_yscale() == 'log'
        win.v_logy.set(False)
        # `#269`: each heading lands on its own panel, and only there
        win.v_title_first.set('first heading')
        win.v_title_second.set('second heading')
        win.redraw()
        assert win.fig.axes[0].get_title(loc='left') == 'first heading'
        assert win.fig.axes[1].get_title(loc='left') == 'second heading'
        win.v_title_first.set('')
        win.v_title_second.set('')
        win.redraw()
        assert win.fig.axes[0].get_title(loc='left') != 'first heading'
        # `#267`: the key is its own second legend, the one carrying the
        # 'marker fill' title -- the run legend has no title at all
        assert win.fig.axes[0].get_legend().get_title().get_text() == \
            'marker fill'
        win.v_marker_key.set(False)
        win.redraw()
        assert win.fig.axes[0].get_legend().get_title().get_text() != \
            'marker fill'


def test_a_cli_preselection_survives_the_first_redraw():
    """`python sldea_plot.py --logy --gui` used to lose its flag to the
    window's OWN first redraw: launch() handed the opts over, __init__ had
    no variable to put logy in, and current_opts() rebuilt the dict
    without it. The flag has to still be on the figure AFTER it is drawn,
    which is a different claim from 'it arrived'."""
    cli, err = sp.make_opts(logy=True, marker_key=False, subplots='first')
    assert not err, err
    assert g.explicit_opts(cli) == {'logy', 'marker_key', 'subplots'}
    with _Bare(opts=cli) as b:
        if not b.ok:
            return
        win = b.win
        assert win.v_logy.get() is True, 'the flag never reached a widget'
        assert win.v_marker_key.get() is False
        assert win.v_subplots.get() == 'first'
        win.redraw()
        opts, e2 = win.current_opts()
        assert not e2 and opts['logy'] is True, 'the redraw threw it away'
        assert len(win.fig.axes) == 1, '--subplots first drew both panels'
        assert win.fig.axes[0].get_yscale() == 'log'
        assert win.fig.axes[0].get_legend().get_title().get_text() != \
            'marker fill'


def test_a_control_is_greyed_exactly_when_it_is_inert():
    """Live conditionality, the pattern the mean child already set: a
    control that cannot change the figure is GREYED, never hidden -- one
    that vanishes says nothing about why -- and it is live again the
    moment it can. Every rule here is sldea_plot's, named in place."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        # the mean line is a child of pre/post: without separated lines
        # the single drawn line already IS the level mean
        assert _state(win.cb_mean) == 'disabled'
        win.v_prepost.set(True)
        win._toggled()
        assert _state(win.cb_mean) == 'normal'
        # the cadence guard is a child of the breakdown marks: sldea_plot
        # consults coarse_cadence only inside `if opts['breakdown']`, so
        # with the X marks off it has nothing left to annotate
        assert _state(win.cb_cadence) == 'normal'
        win.v_breakdown.set(False)
        win._toggled()
        assert _state(win.cb_cadence) == 'disabled'
        win.v_breakdown.set(True)
        win._toggled()
        assert _state(win.cb_cadence) == 'normal'
        # the budget bands reach ONE line of the engine, draw_area's
        # `budget_bands = opts['bands'] and not opts.get('aggregate')`, and
        # nothing outside draw_area reads the option at all -- so the box
        # is inert in exactly two states (`#312`). Under the aggregate
        # first: the band there is the SEM across runs and the ±1–2%
        # budget is deliberately suppressed, so the tick did nothing while
        # looking every bit as operative as the ones above it.
        assert _state(win.cb_bands) == 'normal'
        win.v_aggregate.set(True)
        win._toggled()
        assert _state(win.cb_bands) == 'disabled', \
            'the aggregate suppresses the budget band, so the box is inert'
        assert win.tip_bands.text == g.BANDS_OFF_AGGREGATE_TIP
        win.v_aggregate.set(False)
        win._toggled()
        assert _state(win.cb_bands) == 'normal'
        assert win.tip_bands.text == g.BANDS_TIP
        # the marker key is drawn by draw_area alone
        assert win.v_mode.get() == 'area'
        assert _state(win.cb_marker_key) == 'normal'
        assert _state(win.cb_vs_area) == 'disabled'
        assert _state(win.rb_subplots['second']) == 'normal'
        win.v_mode.set('current')
        win._mode_changed()
        assert _state(win.cb_marker_key) == 'disabled', \
            'a key in current mode claims a distinction the figure does ' \
            'not make'
        # ...and the bands go with it: the budget is an AREA budget, and
        # draw_current never reads the option
        assert _state(win.cb_bands) == 'disabled', \
            'an area budget offered over a microamp figure'
        assert win.tip_bands.text == g.BANDS_OFF_MODE_TIP
        assert _state(win.cb_vs_area) == 'normal'
        # ...and 'second' names a panel current and power do not have
        assert _state(win.rb_subplots['second']) == 'disabled'
        assert _state(win.e_title_second) == 'disabled'
        assert _state(win.e_title_first) == 'normal'
        win.v_mode.set('area')
        win._mode_changed()
        assert _state(win.cb_marker_key) == 'normal'
        assert _state(win.cb_bands) == 'normal'
        assert win.tip_bands.text == g.BANDS_TIP
        assert _state(win.e_title_second) == 'normal'
        # a heading only lands on a panel that RENDERS (`#270`): area_axes
        # creates neither axes when the selection switched it off
        win.v_subplots.set('first')
        win._toggled()
        assert _state(win.e_title_second) == 'disabled'
        assert _state(win.e_title_first) == 'normal'
        win.v_subplots.set('second')
        win._toggled()
        assert _state(win.e_title_second) == 'normal'
        assert _state(win.e_title_first) == 'disabled'
        # ...and the legacy Title, which has ALWAYS meant the first panel,
        # greys with its precise successor rather than pretending to work
        assert _state(win.e_title) == 'disabled'
        # the dpi is dots per INCH OF RASTER and an SVG has none: the
        # backend pins it to 72 and scales in user units, so _savefig does
        # not pass one at all. The same invariant as every rule above --
        # the box greys, it does not silently stop mattering (`#314`).
        assert win.v_fmt.get() == 'png'
        assert _state(win.sb_dpi) == 'normal'
        assert _state(win.lbl_dpi) == 'normal'
        win.v_fmt.set('svg')
        win._format_changed()
        assert _state(win.sb_dpi) == 'disabled', \
            'a dpi box left live beside a vector format'
        assert _state(win.lbl_dpi) == 'disabled'
        win.v_fmt.set('png')
        win._format_changed()
        assert _state(win.sb_dpi) == 'normal'
        # ...and the format itself is never inert: it is the one control
        # here with no condition on it
        for name in sp.FORMATS:
            assert _state(win.rb_fmt[name]) == 'normal', name


class _Boxes:
    """Stands in for tkinter.messagebox for one case, recording what the
    window would have said. A real dialog would block the suite."""

    def __init__(self):
        self.said = []

    def _record(self, kind):
        def box(title, message, **_kw):
            self.said.append((kind, title, message))
        return box

    def __enter__(self):
        self._real = g.messagebox
        g.messagebox = self
        for kind in ('showinfo', 'showwarning', 'showerror'):
            setattr(self, kind, self._record(kind))
        return self

    def __exit__(self, *_exc):
        g.messagebox = self._real
        return False


def test_the_window_exports_the_format_and_dpi_it_shows():
    """`#314` through the window end to end: the two controls reach
    make_opts, the file that lands is the one the targets line promised,
    and the CSV and the figspec land with it for BOTH formats -- the
    three-files rule is sldea_plot's and does not know about formats."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        out = os.path.join(b.tmp, 'figs')
        win.v_out.set(out)
        win.v_stem.set('w')
        base, err = win.current_opts()
        assert not err and base['fmt'] == 'png' and base['dpi'] == 300
        # the targets line names all three files, and follows the format
        win.v_fmt.set('svg')
        win._format_changed()
        shown = win.lbl_targets.cget('text')
        assert 'w.svg' in shown and 'w.csv' in shown, shown
        assert 'w.figspec.json' in shown, shown
        opts, err = win.current_opts()
        assert not err and opts['fmt'] == 'svg'
        win.redraw()
        with _Boxes() as boxes:
            win._export()
        assert [k for k, _t, _m in boxes.said] == ['showinfo'], boxes.said
        for name in ('w.svg', 'w.csv', 'w.figspec.json'):
            p = os.path.join(out, name)
            assert os.path.exists(p) and os.path.getsize(p) > 0, name
        with open(os.path.join(out, 'w.svg'), encoding='utf-8') as f:
            assert '<svg' in f.read()
        # the confirmation says what it wrote, size included, because an
        # SVG can be tens of MB where the PNG was one
        said = boxes.said[0][2]
        assert 'SVG' in said and ('kB' in said or 'MB' in said), said
        # ...and the PNG path honours the dpi, measured off the file
        win.v_fmt.set('png')
        win.v_dpi.set('120')
        win._format_changed()
        assert win.current_opts()[0]['dpi'] == 120
        with _Boxes() as boxes:
            win._export()
        with open(os.path.join(out, 'w.png'), 'rb') as f:
            head = f.read(24)
        width = int.from_bytes(head[16:20], 'big')
        assert abs(width - sp.FIGSIZE['area'][0] * 120) <= 1, width
        assert '120 dpi' in boxes.said[0][2], boxes.said
        # the figspec the window wrote records both, so the CLI can
        # re-render exactly what the window made
        import json
        with open(os.path.join(out, 'w.figspec.json'), encoding='utf-8') as f:
            spec = json.load(f)
        assert spec['opts']['fmt'] == 'png' and spec['opts']['dpi'] == 120


def test_a_typo_in_the_dpi_box_is_refused_not_rendered():
    """The `#314` refusal, in the window. It is REPORTED where the
    filenames are (a bad number does not spoil the preview -- the canvas
    is at screen dpi) and it stops the export rather than falling back to
    a resolution nobody typed."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        win.v_out.set(os.path.join(b.tmp, 'figs'))
        win.v_stem.set('nope')
        win.redraw()
        for bad in ('30000', '0', 'lots'):
            win.v_dpi.set(bad)
            win._show_targets()
            opts, err = win.current_opts()
            assert opts is None and '--dpi' in err, (bad, err)
            assert 'REFUSED' in win.lbl_targets.cget('text'), bad
            with _Boxes() as boxes:
                win._export()
            assert [k for k, _t, _m in boxes.said] == ['showwarning'], bad
            assert '--dpi' in boxes.said[0][2], boxes.said
            assert not os.path.exists(os.path.join(b.tmp, 'figs')), \
                f"a refused dpi ({bad}) still wrote something"
        # a blank box is the ABSENCE of a request, not a bad one: the
        # default stands, so mid-edit the window never blocks on an empty
        # field it is about to be given a number for
        win.v_dpi.set('')
        opts, err = win.current_opts()
        assert not err and opts['dpi'] == sp.DEFAULT_DPI, (opts, err)
        # ...and a hand-edited options file cannot smuggle one past the
        # range the window itself enforces
        assert g._clean_options({'dpi': 30000}) == {}
        assert g._clean_options({'dpi': 'lots'}) == {}
        assert g._clean_options({'dpi': True}) == {}
        assert g._clean_options({'dpi': 600})['dpi'] == 600
        assert g._clean_options({'fmt': 'tiff'}) == {}
        assert g._clean_options({'fmt': 'svg'})['fmt'] == 'svg'


def test_switching_away_from_area_cannot_leave_second_selected():
    """make_opts REFUSES `--subplots second` outside area mode, so the
    combination would have put an error message where the figure goes.
    Two guards, and both earn their place: the radio snaps back so the
    row cannot sit there contradicting the picture, and current_opts
    neutralises the pair so it cannot reach make_opts at all, however the
    variable came to be set."""
    assert sp.make_opts(mode='current', subplots='second')[0] is None
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        win.v_subplots.set('second')
        win.v_mode.set('current')
        win._mode_changed()
        assert win.v_subplots.get() == 'both', 'a greyed radio left filled'
        opts, err = win.current_opts()
        assert not err and opts['subplots'] == 'both'
        # the belt and the braces: set behind the widgets' back, it is
        # still neutralised rather than raised
        win.v_subplots.set('second')
        opts, err = win.current_opts()
        assert not err, 'an invalid pair reached make_opts'
        assert opts['subplots'] == 'both'
        win.redraw()
        assert len(win.fig.axes) == 1
        assert win.fig.axes[0].get_title(loc='left').startswith('Current')
        # 'first' outside area mode stays a no-op naming the only panel,
        # which is sldea_plot's rule, not a second one invented here
        win.v_subplots.set('first')
        assert win.current_opts()[0]['subplots'] == 'first'


def test_the_cadence_guard_tooltip_says_it_annotates_not_suppresses():
    """`#264`'s two load-bearing facts. The guard RESTYLES a breakdown
    mark and never removes one -- hiding a real event because the camera
    was slow would be the P3_5 mistake pointing the other way -- and
    whether it belongs on by default is a bench decision that does not
    exist yet, not a rendering preference."""
    tip = g.DRAW_TIPS['cadence_guard']
    low = tip.lower()
    assert 'annotates' in low and 'suppressing' in low, tip
    assert 'open decision' in low, tip
    assert '`#264`' in tip, 'the tooltip does not cite the open decision'
    # every new control has one, and none of them is a stub
    for key in ('logx', 'logy', 'marker_key', 'cadence_guard', 'subplots',
                'title_first', 'title_second'):
        assert len(g.DRAW_TIPS[key]) > 60, key
    # the marker key's says which mode it belongs to, since that is what
    # the greyed box in current/power leaves an operator asking
    assert 'area mode only' in g.DRAW_TIPS['marker_key'].lower()
    # the `#314` pair is held to the same bar, and the dpi's has the one
    # sentence a greyed box makes someone ask for: WHY it went
    for key in ('fmt', 'dpi'):
        assert len(g.EXPORT_TIPS[key]) > 60, key
    assert 'svg' in g.EXPORT_TIPS['dpi'].lower(), g.EXPORT_TIPS['dpi']
    assert 'refused' in g.EXPORT_TIPS['dpi'].lower()
    assert str(sp.DPI_MAX) in g.EXPORT_TIPS['dpi']
    # ...and they are ATTACHED, not merely declared up here
    with _Bare() as b:
        if not b.ok:
            return
        for w in (b.win.cb_marker_key, b.win.cb_cadence,
                  b.win.e_title_first, b.win.e_title_second,
                  b.win.rb_subplots['both'], b.win.rb_fmt['svg'],
                  b.win.sb_dpi):
            assert w.bind('<Enter>'), f"no tooltip attached to {w}"


def test_a_greyed_bands_box_says_which_of_its_two_reasons_it_is():
    """`#312`. Greying the box is half the fix: 'a control that vanishes
    tells an operator nothing about why it went, while a greyed one with
    a tooltip says what would bring it back' is this column's own rule,
    and the bands box has TWO ways to go inert, which want different
    sentences. Each names the state and the way out, and each keeps the
    budget text behind it -- the `#266` warning about `conf` must not be
    the thing that falls off when the box greys."""
    assert g.bands_tip(True, False) == g.BANDS_TIP
    assert g.bands_tip(True, True) == g.BANDS_OFF_AGGREGATE_TIP
    assert g.bands_tip(False, False) == g.BANDS_OFF_MODE_TIP
    # mode wins the wording: the aggregate cannot be on outside area mode
    # (current_opts neutralises it), so a reader in current mode is told
    # about the mode
    assert g.bands_tip(False, True) == g.BANDS_OFF_MODE_TIP
    for tip, must in ((g.BANDS_OFF_AGGREGATE_TIP,
                       ('aggregate', 'standard error of the mean',
                        '`#268`', 'Turn the aggregate off')),
                      (g.BANDS_OFF_MODE_TIP,
                       ('area', 'Switch to area mode'))):
        assert tip.startswith('Greyed:'), tip[:40]
        for phrase in must:
            assert phrase in tip, (phrase, tip[:200])
        # ...and the budget itself is still one hover away
        assert tip.endswith(g.BANDS_TIP), 'the greyed tip dropped the budget'
        assert 'Never quote it as an uncertainty.' in tip


def test_the_taller_draw_column_still_measures_and_still_scrolls():
    """The Draw column grew by seven controls and `#271`'s floor is
    MEASURED off it, so the two have to still agree. The bar stays a
    report of overflow (`#225`) -- it just trips at a taller window than
    it used to."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        win, col = w.win, w.win.column
        # the new rows are inside the MEASURED body, not floating beside it
        body = str(col.body) + '.'
        for widget in (win.cb_marker_key, win.cb_cadence, win.e_title_first,
                       win.e_title_second, win.rb_subplots['both'],
                       win.e_title,
                       # `#314`'s row is in the Export box, which is in
                       # the same measured body -- a control floating
                       # beside the scrolled column is unreachable in a
                       # short window exactly as `#271` found
                       win.rb_fmt['png'], win.sb_dpi):
            assert str(widget).startswith(body), \
                f"{widget} is outside the scrolled body"
        tall = col.body.winfo_reqheight()
        assert tall > 200, 'fixture built no controls to overflow'
        # the floor still tracks the column it is measured from, and it is
        # still the BODY's width plus the bar -- never the canvas's, which
        # does not know its own until the window is laid out
        assert win.apply_minsize()[0] == col.natural_width() + g.MIN_FIG_W
        assert win.root.minsize()[0] == win.min_size[0]
        assert col.natural_width() >= col.body.winfo_reqwidth()
        # appears on genuine overflow, goes away with room -- and rewinds
        w.resize(f'1000x{tall + 120}')
        _need_room(w, col, tall)
        assert not col.bar_shown, 'bar shown with room to spare'
        assert not col.bar.winfo_ismapped()
        w.resize(f'1000x{max(g.MIN_H, tall - 150)}')
        assert col.bar_shown, 'no bar with the taller column cut off'
        assert col.bar.winfo_ismapped()
        col._cv.yview_moveto(0.5)
        w.resize(f'1000x{tall + 120}')
        assert not col.bar_shown and not col.bar.winfo_ismapped()
        assert col._cv.yview()[0] == 0.0, 'hidden bar left the column scrolled'


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    ran = skipped = 0
    failed = []
    for n in names:
        try:
            globals()[n]()
        except _Skip as why:
            skipped += 1
            print('skip', n, f'({why})')
            continue
        except Exception:
            # A test that blew up still RAN -- only a skip is "did not run".
            ran += 1
            failed.append((n, traceback.format_exc()))
            print('FAIL', n)
            continue
        ran += 1
        print('ok ', n)
    tail = f"{ran} of {len(names)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped, desktop too short)"
    print(tail)
    if not failed:
        return 0
    head = f"{len(failed)} of {len(names)} tests failed"
    print(f"\n{head}")
    for name, tb in failed:
        print(f"===== FAIL {name} =====")
        print(tb.rstrip('\n'))
    print(f"===== end {head} =====")
    return 1


if __name__ == '__main__':
    raise SystemExit(_run())
