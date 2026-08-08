#!/usr/bin/env python3
"""Headless tests for the sldea_plot window's non-widget logic (`#223`).

No Tk root is created here: everything tested lives in the module's run
discovery and its initial state, which is deliberately separate from the
widgets so it CAN be tested without a display. The drawing and export
paths belong to sldea_plot and are covered by test_sldea_plot.py -- that
split is the point, the window owns no plotting rules of its own.

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
        # a bare parent still preselects its newest run
        parent, pre = g.initial_state([p])
        assert parent == os.path.abspath(p) and pre == ['B_run']
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


def test_mode_hints_say_which_modes_need_reviewed_runs():
    """The issue's complaint: that current/power work on RAW runs while
    area needs REVIEWED ones was buried in --help. The window says it."""
    assert set(g.MODE_HINT) == set(sp.MODES)
    assert 'REVIEWED' in g.MODE_HINT['area']
    for m in ('current', 'power'):
        assert 'RAW' in g.MODE_HINT[m], m


def _run():
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    for n in names:
        globals()[n]()
        print('ok ', n)
    print(f"{len(names)} tests passed")


if __name__ == '__main__':
    _run()
