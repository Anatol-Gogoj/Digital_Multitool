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
    # LEAVE NO ROOT BEHIND, even when Tcl teardown was untidy.
    #
    # Tk.destroy() clears tkinter._default_root on the way OUT, so a raise
    # anywhere inside it -- a child whose Tcl command has already gone, a
    # callback cancelled out from under a widget -- leaves the interpreter
    # marked live. Nothing in THIS case fails; the next test that asserts a
    # clean interpreter does, which is how a teardown fault gets reported
    # as somebody else's bug. Seen 2026-08-10: the failure surfaced in
    # test_importing_the_module_opens_no_window, four cases later.
    #
    # This helper's whole contract is "the root is gone afterwards", so it
    # ends by making that true rather than hoping destroy() got there.
    import tkinter as _tk
    if getattr(_tk, '_default_root', None) is root:
        _tk._default_root = None


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
    window, which wants MORE THAN 1200 px of screen once the title bar
    and taskbar are taken -- note that the 1920x1080 vm-setup asks for
    does not come close. `#268` added two more Draw rows, which is what
    finally pushed this desktop under the line and exposed the bug below.

    That figure was written as "~1150 px" and is corrected here because
    it was measured, not estimated: on a 1920x1200 desktop 2026-08-12 the
    column asked for 1186 px and the window could give it 1181 -- short
    by five. Prefer the numbers this guard PRINTS over any threshold
    quoted in prose; they are the two that decide it.

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
        parents, pre = g.initial_state([a, b])
        assert parents == [os.path.abspath(p)]
        assert sorted(pre) == sorted([a, b])
        # a bare parent still preselects its newest run. se.newest_run
        # orders by MTIME, and two directories created back to back can
        # land on the same tick -- so the fixture states which is newer
        # instead of racing the clock.
        os.utime(a, (1_700_000_000, 1_700_000_000))
        os.utime(b, (1_800_000_000, 1_800_000_000))
        parents, pre = g.initial_state([p])
        assert parents == [os.path.abspath(p)] and pre == [b], pre
    finally:
        for d in (p, other):
            shutil.rmtree(d, ignore_errors=True)


def test_runs_from_several_parents_all_reach_the_selection():
    """THE `#323` BUG. The first argument picked THE parent and every run
    living anywhere else was dropped without a word -- so the comparison
    the campaign is for (carbon black under one Upload folder, the P3
    family under another) could not be put on one figure at all.

    Both halves are asserted, because the resolver being right is not the
    same claim as the window listing them: initial_state has to return
    both parents AND both runs, and the window has to end up with both
    rows selected and both directories in selected_dirs()."""
    import tkinter as tk
    p, other = _mktmp(), _mktmp()
    try:
        a = _fake_run(p, 'CB_run')
        elsewhere = _fake_run(other, 'P3_run')
        parents, pre = g.initial_state([a, elsewhere])
        assert parents == [os.path.abspath(p), os.path.abspath(other)]
        assert sorted(pre) == sorted([a, elsewhere]), pre
        try:
            root = tk.Tk()
        except tk.TclError as e:
            print(f"   (skipped: no display for Tk: {e})")
            return
        try:
            root.withdraw()
            win = g.PlotWindow(root, parents, pre, remember=False)
            assert len(win.runs) == 2, win.runs
            assert sorted(os.path.abspath(d)
                          for d in win.selected_dirs()) == sorted(
                              [os.path.abspath(a),
                               os.path.abspath(elsewhere)])
            # the list SAYS where each run came from, since two runs in
            # different folders can share a name -- as a tag keyed to the
            # numbered folder list above it, because the column is ~250 px
            # and the folder's own name does not fit in it
            tags = sorted(l.split(']')[0] + ']' for _d, l in win.runs)
            assert tags == ['[1]', '[2]'], tags
            label = win.lbl_parent.cget('text')
            assert label.startswith('[1] ' + os.path.abspath(p)), \
                'the folder list is not numbered to match'
            assert '[2] ' + os.path.abspath(other) in label
            # ...and the memory names the folder it is keyed on
            assert win.parent == os.path.abspath(p)
            assert 'remembered against [1]' in label
            # one parent only: no tag at all, and nothing to say
            win2 = g.PlotWindow(root, [os.path.abspath(p)], remember=False)
            assert not any(l.startswith('[') for _d, l in win2.runs)
            assert win2.lbl_parent.cget('text') == os.path.abspath(p)
        finally:
            _shut(root)
    finally:
        for d in (p, other):
            shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# `#374`: the run picker's Material and Group columns
# ---------------------------------------------------------------------------

def _setup_txt(rundir, electrode=None):
    """A setup.txt in the app's shape, CRLF as a Windows bench writes it,
    with a `Compliant electrode:` line only when `electrode` is given."""
    lines = ['SLDEA Test: fixture', 'Started: 2026-10-06T10:00:00', '',
             'DEA nominal diameter: 16 mm', '']
    if electrode is not None:
        lines.append(f'Compliant electrode: {electrode}')
    lines += ['', '--- Snapshots ---', 'baseline @ 0 kV', '']
    path = os.path.join(rundir, 'setup.txt')
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\r\n'.join(lines))
    return path


def _cells_by_name(win):
    """{run folder name: its picker cells}, from the window's read-out."""
    return {os.path.basename(d): c for d, c in win.displayed_runs()}


def test_electrode_of_returns_the_line_as_recorded():
    """The one reader `#373` and `#374` share. Absent and `(not
    specified)` are different answers and both must survive: None means
    the run predates the field, `(not specified)` that the operator
    declined to say. Nothing is interpreted: electrode_family() would
    call both Invisicon strings 'cnt', and this must not."""
    p = _mktmp()
    try:
        bare = os.path.join(p, 'no_setup')
        os.makedirs(bare)
        assert g.se.electrode_of(bare) is None
        old = os.path.join(p, 'predates_the_field')
        os.makedirs(old)
        _setup_txt(old)
        assert g.se.electrode_of(old) is None
        for i, (raw, want) in enumerate((
                ('nano-c Invisicon 3900', 'nano-c Invisicon 3900'),
                ('  Meijo 1   ', 'Meijo 1'),
                ('(not specified)', '(not specified)'),
                ('', ''))):
            d = os.path.join(p, f'r{i}')
            os.makedirs(d)
            _setup_txt(d, raw)
            assert g.se.electrode_of(d) == want, (raw, g.se.electrode_of(d))
        # what the Material column makes of each answer
        assert g.material_text(None) == g.NO_ELECTRODE \
            == '(no electrode recorded)'
        assert g.material_text('(not specified)') == '(not specified)'
        assert g.material_text('') == '(not specified)'   # the app's word
        assert g.material_text('Invisicon 3900') == 'Invisicon 3900'
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_setup_reads_are_cached_by_path_and_mtime():
    """The lab share lists slowly already, so a re-listing must not
    re-read every run's setup.txt: one stat each, and a read only for a
    file that changed."""
    import tkinter as tk
    p = _mktmp()
    real = g.se.electrode_of
    reads = []

    def spy(rundir):
        reads.append(rundir)
        return real(rundir)
    try:
        d = _fake_run(p, 'R1')
        path = _setup_txt(d, 'carbon black')
        g._ELECTRODE_CACHE.clear()
        g.se.electrode_of = spy
        assert g.recorded_electrode(d) == 'carbon black'
        assert g.recorded_electrode(d) == 'carbon black'
        assert len(reads) == 1, reads
        # an edit is seen: new text AND a new mtime, stated rather than
        # left to the clock, since two writes can share a tick
        _setup_txt(d, 'eGaIn')
        os.utime(path, (1_800_000_000, 1_800_000_000))
        assert g.recorded_electrode(d) == 'eGaIn'
        assert len(reads) == 2, reads
        # a vanished file reads as no line, and costs no read
        os.remove(path)
        assert g.recorded_electrode(d) is None
        assert len(reads) == 2, reads
        # ...and through the window: a re-listing and a redraw read
        # nothing that has not changed
        r2 = _fake_run(p, 'R2')
        _setup_txt(r2, 'carbon black')
        try:
            root = tk.Tk()
        except tk.TclError as e:
            print(f"   (skipped: no display for Tk: {e})")
            return
        try:
            root.withdraw()
            win = g.PlotWindow(root, p, remember=False)
            n = len(reads)
            assert n >= 3, reads           # R2's first read happened
            win.populate()
            win.set_selected_dirs([d, r2])
            win.redraw()
            assert len(reads) == n, reads[n:]
            # CREATING a group reads its own runs once more, and only
            # them: `#373` gives a new group the material its runs
            # recorded, read at that moment. Moving runs into a group
            # that exists reads nothing; it keeps the group's material.
            win.set_selected_dirs([r2])
            assert win.move_to_group('CB') is None
            assert [sp.group_key(r) for r in reads[n:]] == \
                [sp.group_key(r2)], reads[n:]
            n = len(reads)
            win.set_selected_dirs([d])
            assert win.move_to_group('CB') is None
            win.redraw()
            assert len(reads) == n, reads[n:]
        finally:
            _shut(root)
    finally:
        g.se.electrode_of = real
        shutil.rmtree(p, ignore_errors=True)


def test_the_run_picker_shows_each_runs_material_and_group():
    """`#374`'s 'see': each row carries the material setup.txt recorded
    and the group the window plots it in, and Group follows EVERY way the
    grouping changes: Assign, Ungroup, Clear all, the menu, and the
    remembered grouping a window opens on."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        _setup_txt(_fake_run(b.tmp, 'S2_3900'), 'nano-c Invisicon 3900')
        _setup_txt(_fake_run(b.tmp, 'S3_unspec', processed=False),
                   '(not specified)')
        _setup_txt(_fake_run(b.tmp, 'S4_hand'), 'Invisicon 3900')
        win.populate()
        rows = _cells_by_name(win)
        assert rows['R1']['material'] == g.NO_ELECTRODE
        assert rows['S2_3900']['material'] == 'nano-c Invisicon 3900'
        assert rows['S3_unspec']['material'] == '(not specified)'
        assert rows['S4_hand']['material'] == 'Invisicon 3900'
        # the processed mark sits IN FRONT of the name, where no column
        # width can clip it, and an unprocessed run is padded to the
        # same width (to the nearest space) so the names line up
        assert rows['S2_3900']['run'] == g.RUN_MARK + 'S2_3900'
        assert rows['S3_unspec']['run'] == win._mark_pad + 'S3_unspec'
        assert not win._mark_pad.strip()
        font = win._run_font
        assert abs(font.measure(win._mark_pad)
                   - font.measure(g.RUN_MARK)) <= font.measure(' ') / 2
        # the hover text says which, in words
        tips = {os.path.basename(d): win.row_tip(win._iid(i))
                for i, (d, _l) in enumerate(win.runs)}
        assert 'processed: Edge Review saved areas' in tips['S2_3900']
        assert 'not processed' in tips['S3_unspec']
        assert all(c['group'] == '' for c in rows.values())
        # what Tk shows is the window's record, cell for cell
        for iid in win.run_box.get_children():
            i = win._row_of(iid)
            assert [str(v) for v in win.run_box.item(iid, 'values')] == \
                [win._cells[i][c] for c, _h in g.RUN_COLUMNS], iid
        by = {os.path.basename(d): d for d, _l in win.runs}

        def group_of(name):
            return _cells_by_name(win)[name]['group']
        # Assign, from the Groups box
        win.set_selected_dirs([by['S2_3900'], by['S4_hand']])
        win.v_group_name.set('3900')
        win._assign_group()
        assert group_of('S2_3900') == group_of('S4_hand') == '3900'
        # Ungroup selected
        win.set_selected_dirs([by['S4_hand']])
        win._ungroup_selected()
        assert group_of('S4_hand') == '' and group_of('S2_3900') == '3900'
        # the menu's path
        assert win.move_to_group('3900') is None
        assert group_of('S4_hand') == '3900'
        # Material is what setup.txt says, whatever the group says: the
        # two cells disagree on screen rather than hide the override
        assert _cells_by_name(win)['S4_hand']['material'] == 'Invisicon 3900'
        # Clear all
        win._clear_groups()
        assert all(c['group'] == '' for _d, c in win.displayed_runs())
        # the [folder#] tag stays in the Run column (`#323`), first, with
        # the mark after it
        other = _mktmp()
        try:
            _fake_run(other, 'X1')
            win.parents.append(other)
            win.populate()
            tags = {c['run'].split(']')[0] + ']'
                    for _d, c in win.displayed_runs()}
            assert tags == {'[1]', '[2]'}, tags
            assert _cells_by_name(win)['X1']['run'] == \
                '[2] ' + g.RUN_MARK + 'X1'
        finally:
            shutil.rmtree(other, ignore_errors=True)
        # a REMEMBERED grouping shows the moment the window opens
        cfg = os.path.join(b.tmp, 'opts.json')
        opts, err = sp.make_opts(groups=[['CB', [by['R1']]]])
        assert err is None, err
        assert g.save_options(b.tmp, opts, path=cfg) == cfg
        real = g.OPTIONS_PATH
        g.OPTIONS_PATH = cfg
        try:
            win2 = g.PlotWindow(b.root, b.tmp)
        finally:
            g.OPTIONS_PATH = real
        assert _cells_by_name(win2)['R1']['group'] == 'CB'
        assert _cells_by_name(win2)['S2_3900']['group'] == ''


def test_sorting_the_picker_reorders_the_list_and_not_the_figure():
    """A heading click sorts by that column (again: reversed), so one
    material lines up for one Shift-click. It reorders the LIST only: the
    figure takes its run colors from the selection's order, and a sort
    that repainted the figure would be a control with a side effect
    nobody asked for."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        for name, mat in (('S2', 'nano-c Invisicon 3900'),
                          ('S3', '(not specified)'),
                          ('S4', 'Invisicon 3900'),
                          ('S5', 'carbon black')):
            _setup_txt(_fake_run(b.tmp, name, processed=(name != 'S3')),
                       mat)
        win.populate()
        listing = [d for d, _l in win.runs]
        by = {os.path.basename(d): d for d in listing}
        win.set_selected_dirs(listing)
        key = win._figure_key()

        def column(col):
            return [c[col] for _d, c in win.displayed_runs()]

        def names():
            return [os.path.basename(d) for d, _c in win.displayed_runs()]
        # Run sorts by NAME: the mark in front (S3 is unprocessed) must
        # not split the list into processed and not
        win.sort_runs('run')
        assert names() == ['R1', 'S2', 'S3', 'S4', 'S5'], names()
        assert win.run_box.heading('run', 'text') == 'Run ▲'
        win.sort_runs('run')
        assert names() == ['S5', 'S4', 'S3', 'S2', 'R1'], names()
        win.sort_runs('material')
        assert column('material') == sorted(column('material'),
                                            key=str.casefold)
        assert win.run_box.heading('material', 'text') == 'Material ▲'
        win.sort_runs('material')
        assert column('material') == sorted(column('material'),
                                            key=str.casefold, reverse=True)
        assert win.run_box.heading('material', 'text') == 'Material ▼'
        assert win.run_box.heading('run', 'text') == 'Run'
        assert win.run_box.heading('group', 'text') == 'Group'
        # the figure's inputs did not move
        assert win.selected_dirs() == listing
        assert win._figure_key() == key
        # Group: a run in no group goes last in both directions
        win.set_selected_dirs([by['S5']])
        assert win.move_to_group('CB') is None
        win.set_selected_dirs([by['S2']])
        assert win.move_to_group('3900') is None
        win.sort_runs('group')
        assert column('group')[:2] == ['3900', 'CB'], column('group')
        assert set(column('group')[2:]) == {''}
        win.sort_runs('group')
        assert column('group')[:2] == ['CB', '3900'], column('group')
        assert set(column('group')[2:]) == {''}
        # the sort survives a grouping change and a re-listing
        win.set_selected_dirs([by['S3']])
        assert win.move_to_group('AA') is None
        assert column('group')[:3] == ['CB', 'AA', '3900'], column('group')
        win.populate()
        assert column('group')[:3] == ['CB', 'AA', '3900'], column('group')
        assert win.run_box.heading('group', 'text') == 'Group ▼'


def test_the_move_to_group_menu_goes_through_assign_group():
    """`#374`'s 'adjust': right-click the selected runs, Move to group,
    then an existing group, a new one, or none. Every entry is
    assign_group, so sp.check_groups keeps the last word, and a name it
    REFUSES changes nothing (`#373`'s assign_group undoes it)."""
    with _Bare() as b, _Boxes() as boxes:
        if not b.ok:
            return
        win = b.win
        _setup_txt(_fake_run(b.tmp, 'S2'), 'nano-c Invisicon 3900')
        _setup_txt(_fake_run(b.tmp, 'S3'), 'Invisicon 3900')
        win.populate()
        by = {os.path.basename(d): d for d, _l in win.runs}
        win.set_selected_dirs([by['S2']])
        assert win.move_to_group('P3') is None
        win.set_selected_dirs([by['R1'], by['S3']])
        menu = win.group_menu()
        assert menu.type(0) == 'cascade'
        assert menu.entrycget(0, 'label') == 'Move to group'
        sub = win.root.nametowidget(menu.entrycget(0, 'menu'))
        labels = ['-' if sub.type(i) == 'separator'
                  else sub.entrycget(i, 'label')
                  for i in range(sub.index('end') + 1)]
        assert labels == ['P3', '-', 'New group…', 'No group'], labels

        def checks(m):
            """{entry label: is its check shown} for a built menu, and
            every checkable entry must still be LIVE: a check, never a
            grayed entry."""
            s = win.root.nametowidget(m.entrycget(0, 'menu'))
            out = {}
            for i in range(s.index('end') + 1):
                if s.type(i) == 'checkbutton':
                    assert str(s.entrycget(i, 'state')) == 'normal', i
                    var = str(s.entrycget(i, 'variable'))
                    out[s.entrycget(i, 'label')] = \
                        win.root.getboolean(win.root.getvar(var))
            return out
        # the CURRENT group carries the check. None of the selection is
        # grouped: No group is checked
        assert win.selection_group() == ''
        assert checks(menu) == {'P3': False, 'No group': True}
        # every selected run in one group: that group is checked
        win.set_selected_dirs([by['S2']])
        assert win.selection_group() == 'P3'
        assert checks(win.group_menu()) == {'P3': True, 'No group': False}
        # a mixed selection: no check anywhere
        win.set_selected_dirs([by['R1'], by['S2']])
        assert win.selection_group() is None
        assert checks(win.group_menu()) == {'P3': False, 'No group': False}
        # choosing the checked entry is allowed, and changes nothing
        win.set_selected_dirs([by['S2']])
        before = win.group_list()
        m = win.group_menu()
        s = win.root.nametowidget(m.entrycget(0, 'menu'))
        s.invoke(0)
        assert win.group_list() == before
        # back to the case the menu above was built for
        win.set_selected_dirs([by['R1'], by['S3']])
        menu = win.group_menu()
        sub = win.root.nametowidget(menu.entrycget(0, 'menu'))

        def groups():
            return {n: c['group'] for n, c in _cells_by_name(win).items()}
        # an existing group: this is also how two spellings of one
        # material become one series
        sub.invoke(labels.index('P3'))
        assert groups() == {'R1': 'P3', 'S2': 'P3', 'S3': 'P3'}, groups()
        assert [n for n, _m in win.current_opts()[0]['groups']] == ['P3']
        # no group
        sub.invoke(labels.index('No group'))
        assert groups() == {'R1': '', 'S2': 'P3', 'S3': ''}, groups()
        # a new group: a cancelled or blank prompt changes nothing...
        for typed in (None, '   '):
            win.ask_group_name = lambda typed=typed: typed
            sub.invoke(labels.index('New group…'))
            assert groups() == {'R1': '', 'S2': 'P3', 'S3': ''}, typed
        # ...and a name makes the group, spelled as typed but trimmed
        win.ask_group_name = lambda: '  Invisicon  '
        sub.invoke(labels.index('New group…'))
        assert groups() == {'R1': 'Invisicon', 'S2': 'P3',
                            'S3': 'Invisicon'}, groups()
        # with two groups: the shared one is checked, and runs from two
        # different groups are a mixed selection like any other
        win.set_selected_dirs([by['R1'], by['S3']])
        assert checks(win.group_menu()) == {'P3': False, 'Invisicon': True,
                                            'No group': False}
        win.set_selected_dirs([by['R1'], by['S2']])
        assert checks(win.group_menu()) == {'P3': False, 'Invisicon': False,
                                            'No group': False}
        assert boxes.said == [], boxes.said
        # a name typed in another case JOINS the group of that name,
        # since assign_group matches names case-insensitively (`#373`),
        # rather than being refused as a second group of the same name
        win.ask_group_name = lambda: 'p3'
        win.set_selected_dirs([by['S3']])
        assert win._move_to_new_group() is None
        assert groups() == {'R1': 'Invisicon', 'S2': 'P3', 'S3': 'P3'}, \
            groups()
        # REFUSED WHOLE: an over-long name moves nothing
        before = win.group_list()
        bad = 'x' * (sp.GROUP_NAME_MAX + 1)
        win.ask_group_name = lambda: bad
        win.set_selected_dirs([by['R1']])
        assert win._move_to_new_group()
        assert boxes.said[-1][0] == 'showwarning', boxes.said
        assert win.group_list() == before, win.group_list()
        assert win.current_opts()[1] is None, win.current_opts()[1]
        assert groups()['R1'] == 'Invisicon', groups()
        # the same refusal through the Groups box's own Assign
        win.v_group_name.set(bad)
        win._assign_group()
        assert win.group_list() == before


def test_moving_runs_between_groups_never_writes_setup_txt():
    """The grouping lives in the plot window and the figspec. setup.txt
    is a lab-notebook document whose corrections are a reviewed batch,
    so the picker reads it and nothing in the window may touch it: not a
    byte, not an mtime, not a sidecar beside it."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        paths = [_setup_txt(_fake_run(b.tmp, n), m)
                 for n, m in (('S2', 'nano-c Invisicon 3900'),
                              ('S3', '(not specified)'))]
        win.populate()
        before = {p: (open(p, 'rb').read(), os.stat(p).st_mtime_ns)
                  for p in paths}
        listing = {d: sorted(os.listdir(d)) for d, _l in win.runs}
        win.set_selected_dirs([d for d, _l in win.runs])
        assert win.move_to_group('Invisicon') is None
        win.sort_runs('material')
        win.set_selected_dirs([d for d, _l in win.runs][:1])
        assert win.move_to_group('') is None
        win._clear_groups()
        win.populate()
        win.redraw()
        after = {p: (open(p, 'rb').read(), os.stat(p).st_mtime_ns)
                 for p in paths}
        assert after == before
        assert {d: sorted(os.listdir(d)) for d, _l in win.runs} == listing


def test_the_group_column_follows_a_seed_and_the_menu_keeps_materials():
    """`#373`'s two seed buttons are grouping changes like any other, so
    the Group column shows what they made the moment one is pressed. And
    the menu's paths are assign_group's, so a group's material (its line
    style) is set when the group is CREATED and kept when runs are moved
    into it: that is how two spellings of one material become one
    series, with the override still visible as Material against Group."""
    with _Bare() as b, _Boxes() as boxes:
        if not b.ok:
            return
        win = b.win
        _campaign(b)
        _label(_fake_run(b.tmp, 'N39hand'), 'Invisicon 3900')
        win.populate()
        by = {os.path.basename(d): d for d, _l in win.runs}

        def cells():
            return _cells_by_name(win)

        def column_matches_grouping():
            want = {os.path.basename(m): name
                    for name, members in win.group_list() for m in members}
            got = {n: c['group'] for n, c in cells().items()}
            assert got == {n: want.get(n, '') for n in got}, (got, want)

        def materials():
            return dict(win.group_material_list())
        # the material seed, through its button
        _select(win, 'R1', 'P3a', 'P3b', 'P3c', 'N39', 'N39hand', 'CB1',
                'NS')
        win.btn_seed_material.invoke()
        column_matches_grouping()
        assert cells()['P3a']['group'] == P3
        assert cells()['N39']['group'] == N3900
        assert cells()['N39hand']['group'] == 'Invisicon 3900'
        assert cells()['R1']['group'] == sp.NO_ELECTRODE_GROUP
        assert cells()['NS']['group'] == sp.NOT_SPECIFIED
        # a seeded run's two cells say the same thing
        for name in ('R1', 'NS', 'N39', 'CB1'):
            assert cells()[name]['material'] == cells()[name]['group'], name
        # its child, through its button: the P3 runs split by volume
        _select(win, 'P3a', 'P3b', 'P3c')
        win.btn_seed_concentration.invoke()
        column_matches_grouping()
        assert cells()['P3a']['group'] == cells()['P3b']['group']
        assert cells()['P3a']['group'] != cells()['P3c']['group']
        assert '2.5 mL' in cells()['P3a']['group'], cells()['P3a']
        # MOVE TO GROUP, from the menu, into an existing group: the run
        # takes that group's material, the spelling it left is emptied
        # and goes with its material, and Material still shows what the
        # run's own setup.txt says
        win.set_selected_dirs([by['N39hand']])
        sub = win.root.nametowidget(win.group_menu().entrycget(0, 'menu'))
        sub.invoke([sub.entrycget(i, 'label')
                    if sub.type(i) != 'separator' else None
                    for i in range(sub.index('end') + 1)].index(N3900))
        column_matches_grouping()
        assert cells()['N39hand']['group'] == N3900
        assert cells()['N39hand']['material'] == 'Invisicon 3900'
        assert materials()[N3900] == N3900
        assert 'Invisicon 3900' not in dict(win.group_list())
        assert 'Invisicon 3900' not in materials()
        # NEW GROUP of one material takes that material; of two, none
        win.ask_group_name = lambda: 'cb only'
        win.set_selected_dirs([by['CB1']])
        assert win._move_to_new_group() is None
        assert materials()['cb only'] == CB
        win.ask_group_name = lambda: 'mixed'
        win.set_selected_dirs([by['CB1'], by['N39hand']])
        assert win._move_to_new_group() is None
        assert 'mixed' not in materials()
        assert 'cb only' not in dict(win.group_list())   # emptied: gone
        assert materials()[N3900] == N3900   # N39 still holds it
        column_matches_grouping()
        # NO GROUP empties 'mixed', and its (absent) material cannot
        # outlive it into a later group of the same name
        assert win.move_to_group('') is None
        assert 'mixed' not in dict(win.group_list())
        column_matches_grouping()
        assert boxes.said == [], boxes.said


class _StatSpy:
    """Stands in for sldea_plot_gui's `os` module, recording each stat of
    a setup.txt and passing everything else through to the real one."""

    def __init__(self, real):
        self.real = real
        self.setups = []

    def stat(self, path, *a, **kw):
        if os.path.basename(path) == 'setup.txt':
            self.setups.append(os.path.normcase(os.path.abspath(path)))
        return self.real.stat(path, *a, **kw)

    def __getattr__(self, name):
        return getattr(self.real, name)


def test_material_follows_a_setup_txt_edit_at_the_next_grouping_change():
    """`#390`: the Material cell was read only when the list was filled,
    while the seed buttons read setup.txt FRESH. An operator who fixed a
    run's electrode, as the Material tooltip tells them to, and then
    pressed Group by material saw the new electrode in Group and the old
    one in Material: the disagreement the column's comment rules out.
    Every grouping change now re-reads Material through the cache, so an
    unchanged file still costs one stat and no read."""
    with _Bare() as b, _Boxes() as boxes:
        if not b.ok:
            return
        win = b.win
        s2 = _fake_run(b.tmp, 'S2')
        path = _setup_txt(s2, 'Invisicon 3500')
        s3 = _fake_run(b.tmp, 'S3')
        path3 = _setup_txt(s3, CB)
        win.populate()
        assert _cells_by_name(win)['S2']['material'] == 'Invisicon 3500'
        # the operator corrects the run's setup.txt outside the window,
        # with a new stamp stated rather than left to the clock
        _setup_txt(s2, N3900)
        os.utime(path, (1_800_000_000, 1_800_000_000))
        _select(win, 'S2', 'S3')
        win.btn_seed_material.invoke()
        cells = _cells_by_name(win)
        assert cells['S2']['group'] == N3900, cells['S2']
        assert cells['S2']['material'] == N3900, cells['S2']
        assert cells['S3']['material'] == cells['S3']['group'] == CB
        # ...and so do Tk's copy of the cell and the row's hover text
        i = [os.path.basename(d) for d, _l in win.runs].index('S2')
        assert win.run_box.set(win._iid(i), 'material') == N3900
        assert f"Material (setup.txt): {N3900}" in win.row_tip(win._iid(i))
        # any grouping change re-reads it, the menu's path included
        _setup_txt(s3, '(not specified)')
        os.utime(path3, (1_800_000_100, 1_800_000_100))
        _select(win, 'S3')
        assert win.move_to_group('later') is None
        assert _cells_by_name(win)['S3']['material'] == '(not specified)'
        assert _cells_by_name(win)['S3']['group'] == 'later'
        # THE COST: with nothing changed, one stat per listed run and no
        # read, both for a grouping change and for a re-listing
        real_os, real_read = g.os, g.se.electrode_of
        spy, reads = _StatSpy(real_os), []

        def read(rundir):
            reads.append(rundir)
            return real_read(rundir)
        want = sorted(os.path.normcase(os.path.abspath(
            os.path.join(d, 'setup.txt'))) for d, _l in win.runs)
        assert len(want) == 3, want
        try:
            g.os, g.se.electrode_of = spy, read
            win._refresh_group_column()
            assert sorted(spy.setups) == want, spy.setups
            del spy.setups[:]
            win.populate()
            assert sorted(spy.setups) == want, spy.setups
        finally:
            g.os, g.se.electrode_of = real_os, real_read
        assert reads == [], reads
        assert boxes.said == [], boxes.said


def test_fit_widths_gives_way_in_order_and_never_below_a_floor():
    """The picker's column arithmetic, on the case `#373`'s seeds produce:
    three long cells in a list too narrow for them, the group name the
    longest."""
    nat = {'run': 190, 'material': 155, 'group': 200}
    floor = {'run': 138, 'material': 134, 'group': 56}
    order = g.RUN_COL_GIVE
    # room to spare: Run, the name column, takes the slack
    assert g.fit_widths(nat, floor, 600, order) == \
        {'run': 245, 'material': 155, 'group': 200}
    # a little short: Run alone gives way
    assert g.fit_widths(nat, floor, 520, order) == \
        {'run': 165, 'material': 155, 'group': 200}
    # shorter: Run down to its floor, then Material, and Group keeps its
    # width, since a seeded group name is the longest cell (`#373`)
    out = g.fit_widths(nat, floor, 490, order)
    assert out == {'run': 138, 'material': 152, 'group': 200}, out
    assert sum(out.values()) == 490
    # shorter still: Material at its floor too, then Group gives way
    out = g.fit_widths(nat, floor, 328, order)
    assert out == {'run': 138, 'material': 134, 'group': 56}, out
    assert sum(out.values()) == 328
    # shorter than the floors: none goes under one; the list scrolls
    assert g.fit_widths(nat, floor, 200, order) == floor
    # the order the owner chose once `#373` seeded long group names
    assert order == ('run', 'material', 'group'), order


def test_the_headings_are_measured_in_the_heading_font():
    """`#390`: _fit_columns measured each heading in the CELL font, but
    ttk draws headings in TkHeadingFont, which is bold on X11 (the
    bench), so Group's heading with its sort arrow could clip at Group's
    floor there. Here the heading font is made bolder and larger than
    the cells' on purpose, so the two cannot measure alike on any
    desktop: each heading with its arrow has to fit the width its column
    is given and its floor, and the heading alone the separator's
    minimum. Then again through a theme that gives the headings a font
    DESCRIPTION rather than a named font, which must not stop the window
    from opening."""
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import ttk
    p = _mktmp()
    try:
        _fake_run(p, 'R1')
        for how in ('named font', 'description'):
            try:
                root = tk.Tk()
            except tk.TclError as e:
                print(f"   (skipped: no display for Tk: {e})")
                return
            try:
                root.withdraw()
                cell = tkfont.nametofont('TkDefaultFont')
                size = abs(int(cell.actual('size'))) + 3
                if how == 'named font':
                    head = tkfont.nametofont('TkHeadingFont')
                    head.configure(weight='bold', size=size)
                else:
                    desc = f"{{{cell.actual('family')}}} {size} bold"
                    ttk.Style(root).configure('Heading', font=desc)
                    head = tkfont.Font(root=root, font=desc)
                assert head.measure('Group ▲') > cell.measure('Group ▲')
                win = g.PlotWindow(root, p, remember=False)
                tree, inset = win.run_box, win._text_w('')
                for col, text in g.RUN_COLUMNS:
                    need = head.measure(text + ' ▲') + inset
                    assert tree.column(col, 'width') >= need, \
                        (how, col, tree.column(col, 'width'), need)
                    assert win._col_floor(col) >= need, (how, col)
                    assert tree.column(col, 'minwidth') >= \
                        head.measure(text) + inset, (how, col)
            finally:
                _shut(root)
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_initial_state_falls_back_without_arguments():
    parents, pre = g.initial_state([])
    assert parents and parents[0], 'no parent at all'
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


def test_uncertainty_band_tooltip_does_not_call_the_spread_a_ci():
    """2026-10-02: the disc-fit spread is the block-bootstrap spread of
    the common-ray ratio and nothing user-facing may call it a
    confidence interval (its predecessor held 21-49 % where it claimed
    85 %). The tooltip used to quote "the disc-fit's own CI (0.2-0.7%)"."""
    tip = g.BANDS_TIP
    assert 'own CI' not in tip and '0.2–0.7%' not in tip, tip
    assert "disc-fit's own spread" in tip, tip
    assert 'not a confidence interval' in tip, tip


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
        """Pump the loop until Tk has finished re-laying the window out AND
        the coalesced redraw has fired. -> True when none is left pending.

        `secs` of pumping covers the first half. It used to be all of it,
        sized when every redraw was coalesced over REDRAW_MS -- and `#316`
        then gave a resize its own RESIZE_MS, which left the <Configure>
        100 ms to arrive in. The Linux runs this suite passed on made
        that; a Windows 11 PC did not. There the canvas heard of a
        geometry() 120-320 ms later (the toplevel alone took 80-130 ms to
        resize), the redraw landed 575-730 ms after it, mostly once the
        pumping had stopped, and the resize case compared the PREVIOUS
        size's layout with a rebuild at this one (2026-09-23).

        So the second half waits for the redraw itself, however late the
        platform delivers the event. The bound is the module's own
        promise: a pending redraw is held back at most MAX_DEFER_MS past
        its window, and one still pending after that is a figure that
        stopped tracking its window."""
        t0 = time.time()
        while time.time() - t0 < secs:
            self.root.update()
            time.sleep(0.02)
        limit = time.time() + (g.RESIZE_MS + g.MAX_DEFER_MS) / 1000.0 + 1.0
        while self.win._redraw_after is not None and time.time() < limit:
            self.root.update()
            time.sleep(0.02)
        return self.win._redraw_after is None

    def resize(self, size):
        self.root.geometry(size)
        assert self.settle(), \
            f'the coalesced redraw never landed after resizing to {size}'

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
        #
        # Only a shortcut that RAN, at THIS size, is worth comparing, so
        # that is pinned first, through a spy on the one method it goes
        # through. Unpinned, a resize that stopped taking the shortcut
        # would compare a rebuild with a rebuild and pass -- and a settle
        # that ended too early compared the PREVIOUS size's layout and
        # failed as though the shortcut had landed somewhere else, which
        # read as a DPI bug. Once landed, the shortcut was identical to
        # the rebuild to the last bit, both at 96 dpi and in a DPI-aware
        # process at 175% (Windows 11, 2026-09-23; see _Win.settle).
        ran = []                   # (figure inches, shortcut taken) per call
        real_relayout = w.win.relayout

        def inches():
            return tuple(float(v) for v in w.win.fig.get_size_inches())

        def relayout():
            took = real_relayout()
            ran.append((inches(), took))
            return took
        w.win.relayout = relayout
        for size in ('900x600', '1300x850', '900x600'):
            del ran[:]
            w.resize(size)
            assert ran and ran[-1] == (inches(), True), (
                f'the resize to {size} never took the shortcut at the size '
                f'it left the figure: relayout calls {ran}, now {inches()}')
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


def test_the_run_picker_scrolls_sideways_and_never_widens_the_window():
    """`#374` put three columns where one used to be. A Treeview asks for
    the SUM of its column widths, so left alone a long material, or a
    separator dragged wide, would widen the controls column and with it
    `#271`'s measured floor. The list asks for its column floors and no
    more; anything wider scrolls the list, with a bar that is a report
    of overflow (`#225`)."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        win, col = w.win, w.win.column
        tree = win.run_box
        box = tree.master
        vbar = [c for c in box.winfo_children()
                if c is not tree and c is not win.run_xbar][0]
        assert box.winfo_reqwidth() == \
            win._list_width() + vbar.winfo_reqwidth()
        # the fixture's names and its placeholder material show whole,
        # with no sideways bar
        for c in ('run', 'material'):
            assert tree.column(c, 'width') >= win._col_floor(c), c
        assert not win.run_xbar.winfo_manager()
        # a column dragged wide scrolls the LIST and moves no floor
        natural = col.natural_width()
        floor = win.apply_minsize()
        tree.column('material', width=1500)
        w.settle(0.3)
        assert col.natural_width() == natural
        assert win.apply_minsize() == floor
        assert win.run_xbar.winfo_manager() == 'grid', 'no sideways bar'
        # the next content change re-fits it, and the bar goes again
        win._refresh_group_column()
        w.settle(0.3)
        assert not win.run_xbar.winfo_manager(), tree.xview()
        # the hover text: a heading explains its column, a row shows
        # itself whole, since the columns are narrow and clip
        # (mid-column: within a few px of a boundary Tk reports the
        # column SEPARATOR, which is where a drag starts)
        x_mat = tree.column('run', 'width') + tree.column('material',
                                                          'width') // 2
        assert win._picker_tip(x_mat, 5) == (('heading', 'material'),
                                             g.RUN_HEADING_TIPS['material'])
        rows = tree.get_children()
        bx, by, _bw, bh = tree.bbox(rows[0])
        key, text = win._picker_tip(bx + 5, by + bh // 2)
        assert key == ('row', rows[0]), key
        first = win.displayed_runs()[0]
        assert first[0] in text and os.path.basename(first[0]) in text
        assert 'processed: Edge Review saved areas' in text
        assert g.NO_ELECTRODE in text and g.RUN_ROW_HINT in text
        # the mark leads the cell, so the column's own width cannot clip
        # it: the cell starts with it
        assert first[1]['run'].startswith(g.RUN_MARK), first[1]['run']

        # right-click on a row OUTSIDE the selection makes it the
        # selection, as file managers do; inside a multi-selection it
        # keeps the selection. The menu itself is stubbed: on Windows a
        # real tk_popup is modal and would hold the suite. Its grab is
        # Tk's to release: on X11 a grab_release() straight after
        # tk_popup leaves a menu that an outside click does not close.
        class _Menu:
            at = None

            def tk_popup(self, x, y):
                self.at = (x, y)

            def grab_release(self):
                raise AssertionError('the popup grab is released by Tk '
                                     'when the menu unposts')
        menu = _Menu()
        win.group_menu = lambda: menu
        second = win.displayed_runs()[1][0]
        bx, by, _bw, bh = tree.bbox(rows[1])

        class _E:
            x, y = bx + 5, by + bh // 2
            x_root, y_root = 400, 300
        # 'break' (`#390`), so no class binding runs after the menu: on
        # macOS a Control-click is a Button-1 press, and the Treeview's
        # own binding would select the clicked row alone
        win.set_selected_dirs([first[0]])
        assert win._run_menu(_E()) == 'break' and menu.at == (400, 300)
        assert win.selected_dirs() == [second], win.selected_dirs()
        everything = [d for d, _l in win.runs]
        win.set_selected_dirs(everything)
        menu.at = None
        assert win._run_menu(_E()) == 'break' and menu.at == (400, 300)
        assert win.selected_dirs() == everything


def test_the_window_opens_wide_enough_for_a_seeded_group_name():
    """Owner decision 2026-10-06 (`#374`): the window keeps its `#271`
    floor but OPENS wider, so the Group column shows a `#373`-seeded
    name like RUN_GROUP_SAMPLE whole beside the other two columns. The
    room has to reach Group, not the figure and not Run; the opening is
    clamped to the work area; and the window still shrinks to its floor,
    where the column hands the room back and the figure keeps
    MIN_FIG_W."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        win, tree = w.win, w.win.run_box
        for name in ('P3a', 'P3b'):
            _label(_fake_run(w.tmp, name), P3, '2.5 mL')
        win.populate()
        _select(win, 'P3a', 'P3b')
        win.btn_seed_concentration.invoke()
        seeded = f'{P3}, 2.5 mL'
        assert seeded == g.RUN_GROUP_SAMPLE
        assert seeded in dict(win.group_list()), win.group_list()
        floor = win.apply_minsize()
        assert floor[0] == win.column.natural_width() + g.MIN_FIG_W
        left, top, right, bottom = g.work_area(win.root)
        # the frame counts (`#390`): +x+y places it, WxH sizes the inside
        fw, fh = win.frame_size()
        if right - left - fw < floor[0] + win.column.extra:
            raise _Skip(f'desktop too narrow: the opening wants '
                        f'{floor[0] + win.column.extra + fw}px with its '
                        f'frame and the work area is {right - left}px')
        width, height, x, y = win.apply_opening_size()
        assert left <= x and x + width + fw <= right, (x, width, left, right)
        assert top <= y and y + height + fh <= bottom, \
            (y, height, top, bottom)
        assert w.settle(), 'the redraw never landed after opening'
        assert win.root.winfo_width() == width
        # the room reached GROUP: the seeded name shows whole...
        assert tree.column('group', 'width') >= \
            win._run_font.measure(seeded), tree.column('group', 'width')
        assert tree.column('group', 'width') >= win._text_w(seeded)
        # ...the figure still has more than its floor, and the floor
        # itself did not move
        assert win.canvas.get_tk_widget().winfo_width() > g.MIN_FIG_W
        assert win.apply_minsize() == floor
        # shrunk to the floor, the column hands the room back and the
        # figure keeps MIN_FIG_W
        w.resize(f'{floor[0]}x{max(floor[1], 600)}')
        assert win.column.winfo_width() == win.column.natural_width()
        assert win.canvas.get_tk_widget().winfo_width() >= g.MIN_FIG_W - 2


def test_the_opening_clamp_counts_the_window_frame():
    """`#390`: `+x+y` places the window's OUTER frame and `WxH` sizes its
    inside, so opening_size, clamping the inside to the work area, opened
    a too-wide window a border's width past the work area's right edge
    on Windows, and a title bar and a border past its bottom. work_area
    is monkeypatched to an area narrower and shorter than the window
    asks for, so the clamp branch is the one taken (the case above
    cannot reach it on a desktop wide enough for it), and on Windows the
    frame that was really drawn is checked against that area."""
    import sys
    with _Win('1400x900') as w:
        if not w.ok:
            return
        win, root = w.win, w.win.root
        root.update_idletasks()
        fw, fh = win.frame_size()
        floor_w, floor_h = win.min_size
        req_w, req_h = root.winfo_reqwidth(), root.winfo_reqheight()
        # above the floor with its frame, below what the window asks for
        area_w = min(req_w + fw - 20, floor_w + fw + 100)
        area_h = min(req_h + fh - 20, floor_h + fh + 100)
        if area_w <= floor_w + fw or area_h <= floor_h + fh:
            raise _Skip(f'no area between the floor {win.min_size} and '
                        f'the request {(req_w, req_h)} to clamp into')
        left, top = 30, 20
        right, bottom = left + area_w, top + area_h
        real = g.work_area
        g.work_area = lambda _widget: (left, top, right, bottom)
        try:
            width, height, x, y = win.apply_opening_size()
        finally:
            g.work_area = real
        # the clamp branch, and the frame inside the area, centered
        assert width < req_w and height < req_h, (width, height, req_w,
                                                  req_h)
        assert left <= x and x + width + fw <= right, (x, width, fw, right)
        assert top <= y and y + height + fh <= bottom, (y, height, fh,
                                                        bottom)
        assert abs((x - left) - (right - x - width - fw)) <= 1
        assert w.settle(), 'the redraw never landed after opening'
        assert (root.winfo_width(), root.winfo_height()) == (width, height)
        if sys.platform != 'win32':
            return
        # where Windows really drew the frame, asked of Windows
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        assert ctypes.windll.user32.GetWindowRect(
            int(root.wm_frame(), 16), ctypes.byref(rect))
        assert left <= rect.left and rect.right <= right, \
            (rect.left, rect.right, left, right)
        assert top <= rect.top and rect.bottom <= bottom, \
            (rect.top, rect.bottom, top, bottom)
        # ...and it is the frame frame_size reported
        assert (rect.right - rect.left - width,
                rect.bottom - rect.top - height) == (fw, fh)


def test_a_bar_that_appears_never_puts_the_figure_under_its_floor():
    """`#390`: ScrollColumn took its width BEFORE deciding the bar, and
    width_for leaves room for the bar only while it shows. So in a window
    between the floor and the floor plus the room Group asks for, where
    the column is held to what leaves the figure MIN_FIG_W, a bar that
    appeared because the window got SHORTER widened the column by its
    own width, and the figure sat that much under MIN_FIG_W until the
    next resize.

    Usually a second <Configure> hid it: the body is stretched to the
    canvas height, so it shrinks when the bar appears, and its own
    <Configure> refit the column with the bar counted. Not when the
    canvas was already within SLACK px under the body's request, where
    the body's height does not change: a slow drag of the bottom edge
    passes through that band. The sizes below go through it (measured
    2026-10-06: the old order left the figure at 343 px, 17 under).

    A bare column over a body of known size, so the case runs on any
    desktop: the window's own controls are taller than some screens,
    which is why the two scroll cases above can skip."""
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    try:
        col = g.ScrollColumn(root)
        col.pack(side=tk.LEFT, fill=tk.Y)
        tk.Frame(col.body, width=200, height=400).pack()
        fig = tk.Frame(root)
        fig.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        col.set_room(extra=140)

        def configured(event):         # PlotWindow._root_configured's rule
            if event.widget is root:
                col.set_room(limit=event.width - g.MIN_FIG_W)
        root.bind('<Configure>', configured, add='+')
        # between the floor (body, bar and figure) and the floor plus the
        # 140 px of room, so it is `limit` that holds the column
        width = 200 + col.bar.winfo_reqwidth() + g.MIN_FIG_W + 60
        room = width - g.MIN_FIG_W
        root.update_idletasks()
        need = col.body.winfo_reqheight()
        assert need == 400, need
        # room to spare; then just under the body's request, inside the
        # SLACK, still no bar; then short, where the bar appears and the
        # body keeps its height; and back
        for height, bar in ((need + 200, False), (need - 2, False),
                            (need - 100, True), (need - 2, False),
                            (need - 100, True), (need + 200, False)):
            root.geometry(f'{width}x{height}')

            def landed():
                return ((root.winfo_width(), root.winfo_height())
                        == (width, height) and col.bar_shown is bar
                        and col.winfo_width() == room
                        and fig.winfo_width() == g.MIN_FIG_W)
            t0 = time.time()
            while time.time() - t0 < 3.0:
                root.update()
                if time.time() - t0 > 0.5 and landed():
                    break
                time.sleep(0.02)
            assert (root.winfo_width(), root.winfo_height()) == \
                (width, height), 'the window did not take the size asked'
            assert col.bar_shown is bar, (height, col.bar_shown)
            assert col.winfo_width() == room, \
                (height, col.winfo_width(), room)
            assert fig.winfo_width() == g.MIN_FIG_W, \
                (height, fig.winfo_width())
    finally:
        _shut(root)


def _more_runs(w, n=12):
    """Add `n` runs to a _Win's folder and re-list. -> the picker's row
    ids in the order shown: 2 + n of them, about 9 on screen."""
    for i in range(n):
        _fake_run(w.tmp, f'D{i:02d}')
    w.win.populate()
    w.settle(0.3)
    return list(w.win.run_box.get_children())


def _whole_rows(tree, rows):
    """-> the rows wholly inside the list widget, top to bottom: the
    test's own reading, kept apart from DragSelect's."""
    out = []
    for r in rows:
        box = tree.bbox(r)
        if box and box[1] + box[3] <= tree.winfo_height():
            out.append(r)
    return out


class _MenuStub:
    """The run menu, stubbed: a real tk_popup is modal on Windows and
    would hold the suite. It counts the posts, and it takes the entries
    #395's Video review item adds after the group menu is built."""

    def __init__(self):
        self.posted = 0

    def tk_popup(self, _x, _y):
        self.posted += 1

    def add_separator(self):
        pass

    def add_command(self, **_kw):
        pass


def test_a_drag_selects_the_rows_it_passes_and_clicks_keep_their_jobs():
    """`#390`: click-drag range selection went with the Listbox, because
    a Tk 8.6 Treeview's own drag only moves column separators, and
    DragSelect puts it back. Driven through generated events, since what
    is under test is which bindings run and in what order.

    A plain drag selects the rows it passes, either way and back again,
    and a wobble inside the pressed row changes nothing. A Ctrl-drag
    adds the rows it passes, or takes them out when it starts on a row
    the Ctrl-click deselected. Past the bottom edge the list scrolls and
    the range keeps growing. And the Treeview keeps its own jobs: Ctrl-
    click toggles one row, Shift-click selects from the anchor, a
    separator drag resizes its column, and a drag that starts on a
    heading selects nothing."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        win, tree = w.win, w.win.run_box
        for i in range(12):
            _fake_run(w.tmp, f'D{i:02d}')
        win.populate()
        w.settle(0.3)
        rows = list(tree.get_children())
        shown = [r for r in rows if tree.bbox(r)]
        assert len(rows) == 14 and len(shown) < len(rows), \
            (len(rows), len(shown))

        def at(iid, dx=10, dy=0):
            x, y, _w, h = tree.bbox(iid)
            return {'x': x + dx, 'y': y + h // 2 + dy}

        def sel():
            chosen = set(tree.selection())
            return [r for r in rows if r in chosen]

        def ev(sequence, **where):
            tree.event_generate(sequence, **where)
        # a plain drag
        ev('<ButtonPress-1>', **at(rows[1]))
        assert sel() == [rows[1]]
        ev('<B1-Motion>', **at(rows[1], dx=14, dy=3))       # a wobble
        assert sel() == [rows[1]]
        ev('<B1-Motion>', **at(rows[4]))
        assert sel() == rows[1:5], sel()
        ev('<B1-Motion>', **at(rows[2]))
        assert sel() == rows[1:3], sel()
        ev('<B1-Motion>', **at(rows[0]))
        assert sel() == rows[0:2], sel()
        ev('<ButtonRelease-1>', **at(rows[0]))
        # ...which reaches the figure like any other selection (listing
        # order and display order agree here: nothing is sorted)
        assert win.selected_dirs() == [d for d, _l in win.runs[0:2]]
        # Ctrl-click toggles one row, and a Ctrl-drag adds the rows it
        # passes...
        ev('<Control-ButtonPress-1>', **at(rows[5]))
        ev('<Control-ButtonRelease-1>', **at(rows[5]))
        assert sel() == rows[0:2] + [rows[5]], sel()
        ev('<Control-ButtonPress-1>', **at(rows[7]))
        ev('<Control-B1-Motion>', **at(rows[8]))
        ev('<Control-ButtonRelease-1>', **at(rows[8]))
        assert sel() == rows[0:2] + [rows[5], rows[7], rows[8]], sel()
        # ...or, from a row its Ctrl-click deselected, takes them out
        ev('<Control-ButtonPress-1>', **at(rows[8]))
        ev('<Control-B1-Motion>', **at(rows[7]))
        ev('<Control-ButtonRelease-1>', **at(rows[7]))
        assert sel() == rows[0:2] + [rows[5]], sel()
        # Shift-click selects from the anchor, the last plain click's row
        ev('<ButtonPress-1>', **at(rows[2]))
        ev('<ButtonRelease-1>', **at(rows[2]))
        assert sel() == [rows[2]], sel()
        ev('<Shift-ButtonPress-1>', **at(rows[4]))
        ev('<Shift-ButtonRelease-1>', **at(rows[4]))
        assert sel() == rows[2:5], sel()
        # past the bottom edge, each motion scrolls one row and extends
        ev('<ButtonPress-1>', **at(rows[0]))
        below = {'x': 20, 'y': tree.winfo_height() + 15}
        for _ in range(3):
            ev('<B1-Motion>', **below)
        ev('<ButtonRelease-1>', **below)
        got = sel()
        assert tree.yview()[0] > 0.0, tree.yview()
        assert got == rows[:len(got)] and len(got) > len(shown), \
            (len(got), len(shown))
        # wholly on screen, not just with a box: Tk also gives one to the
        # row past the last whole row (`#390` review)
        assert got[-1] in _whole_rows(tree, rows), \
            'the last row selected is not wholly on screen'
        tree.yview_moveto(0)
        w.settle(0.2)
        before = sel()
        # a separator drag still resizes its column, even wandering over
        # the rows, and selects nothing
        x = tree.column('run', 'width')
        assert tree.identify_region(x, 5) == 'separator', \
            tree.identify_region(x, 5)
        ev('<ButtonPress-1>', x=x, y=5)
        ev('<B1-Motion>', x=x + 30, y=5)
        ev('<B1-Motion>', x=x + 30, y=at(rows[3])['y'])
        ev('<ButtonRelease-1>', x=x + 30, y=at(rows[3])['y'])
        assert tree.column('run', 'width') > x, (tree.column('run', 'width'),
                                                 x)
        assert sel() == before, sel()
        # ...and a drag that starts on a heading selects nothing either
        hx = tree.column('run', 'width') + \
            tree.column('material', 'width') // 2
        assert tree.identify_region(hx, 5) == 'heading'
        ev('<ButtonPress-1>', x=hx, y=5)
        ev('<B1-Motion>', x=hx, y=at(rows[5])['y'])
        ev('<ButtonRelease-1>', x=hx, y=at(rows[5])['y'])
        w.settle(0.2)
        assert sel() == before, sel()


def test_a_menu_click_keeps_the_selection_it_was_opened_for():
    """`#390`: on macOS the run menu also answers Control-click, which is
    a Button-1 press, and _run_menu did not return 'break', so the
    Treeview's own Button-1 binding ran after it and the selection the
    menu was opened for collapsed to the clicked row. Driven through a
    real event with the binding macOS gets, bound here by hand since
    this is not a Mac; on Windows the class binding that would run next
    is Ctrl-click's toggle, which takes the row out instead. The menu is
    stubbed (_MenuStub)."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        win, tree = w.win, w.win.run_box
        menu = _MenuStub()
        win.group_menu = lambda: menu
        tree.bind('<Control-Button-1>', win._run_menu)
        everything = [d for d, _l in win.runs]
        assert len(everything) == 2, everything
        win.set_selected_dirs(everything)
        x, y, _w, h = tree.bbox(tree.get_children()[1])
        tree.event_generate('<Control-ButtonPress-1>', x=x + 10,
                            y=y + h // 2)
        tree.event_generate('<Control-ButtonRelease-1>', x=x + 10,
                            y=y + h // 2)
        assert menu.posted == 1, menu.posted
        assert win.selected_dirs() == everything, win.selected_dirs()


def test_a_drag_over_the_headings_scrolls_and_takes_only_rows_on_screen():
    """`#390` review: over the headings of a list scrolled down, Tk's
    identify_row names a row scrolled out of sight above them (Tk 8.6
    IdentifyItem counts rows from where the top row would be, with no
    lower bound). The drag took that row: dragged up and released over
    the headings, it selected runs nobody could see, which the figure
    and the export then drew, and the list did not scroll. The headings
    now count as above the top row, so each motion there scrolls up one
    row, and only rows on screen are taken."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        tree = w.win.run_box
        rows = _more_runs(w)
        tree.yview_scroll(3, 'units')
        w.settle(0.3)
        assert _whole_rows(tree, rows)[0] == rows[3], tree.yview()
        # the Tk behavior the guard is for: a hidden row, named there
        hidden = tree.identify_row(5)
        assert hidden in rows[:3] and not tree.bbox(hidden), hidden

        def sel():
            chosen = set(tree.selection())
            return [r for r in rows if r in chosen]
        x, y, _w, h = tree.bbox(rows[6])
        tree.event_generate('<ButtonPress-1>', x=x + 10, y=y + h // 2)
        assert sel() == [rows[6]], sel()
        tree.event_generate('<B1-Motion>', x=x + 10, y=5)
        assert _whole_rows(tree, rows)[0] == rows[2], \
            'the list did not scroll up a row'
        assert sel() == rows[2:7], sel()
        tree.event_generate('<B1-Motion>', x=x + 10, y=5)
        tree.event_generate('<ButtonRelease-1>', x=x + 10, y=5)
        assert sel() == rows[1:7], sel()
        whole = _whole_rows(tree, rows)
        assert all(r in whole for r in sel()), (sel(), whole)


def test_a_drag_past_the_bottom_takes_only_rows_wholly_on_screen():
    """`#390` review: Tk's bbox() gives a box to the row just past the
    last whole row as well, and that row can be entirely out of sight.
    _edge_row took the last row with a box, so a drag past the bottom
    could select a run nobody could see. It now stops at the last row
    wholly inside the widget.

    On this PC's Tk 8.6.14, bbox() reads the scroll state the last
    redraw left, so right after a scroll it happened to name the right
    row; the review reads Tk 8.6.15's bbox() as bringing that state up
    to date first. The case does that after each scroll, so it holds
    the drag to the newer behavior here too."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        tree = w.win.run_box
        rows = _more_runs(w)
        whole = _whole_rows(tree, rows)
        assert len(whole) < len(rows), (len(whole), len(rows))
        real = tree.yview_scroll

        def scroll(number, what):
            real(number, what)
            tree.update_idletasks()        # the scroll state, made current
        tree.yview_scroll = scroll

        def sel():
            chosen = set(tree.selection())
            return [r for r in rows if r in chosen]
        start = whole[len(whole) // 2]
        x, y, _w, h = tree.bbox(start)
        tree.event_generate('<ButtonPress-1>', x=x + 10, y=y + h // 2)
        below = {'x': x + 10, 'y': tree.winfo_height() + 15}
        for step in (1, 2):
            tree.event_generate('<B1-Motion>', **below)
            got, whole = sel(), _whole_rows(tree, rows)
            assert got[0] == start and got[-1] == whole[-1], \
                (step, got, whole)
            assert all(r in whole for r in got), (step, got, whole)
        tree.event_generate('<ButtonRelease-1>', **below)
        assert tree.yview()[0] > 0.0, tree.yview()


def test_a_click_on_the_headings_of_a_scrolled_list_names_no_hidden_run():
    """`#390` review, the same Tk behavior as the drag's: a right-click on
    the headings of a list scrolled down made the hidden row Tk names
    there the whole selection, and opened the menu for it; the hover
    text over a heading separator described that row. Neither takes a
    row that is not on screen now: the menu keeps the selection it was
    opened over, and the separator has no hover text of its own."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        win, tree = w.win, w.win.run_box
        rows = _more_runs(w)
        menu = _MenuStub()
        win.group_menu = lambda: menu
        picked = [win.runs[win._row_of(r)][0] for r in rows[4:6]]
        win.set_selected_dirs(picked)
        tree.yview_scroll(3, 'units')
        w.settle(0.3)
        hidden = tree.identify_row(5)
        assert hidden and not tree.bbox(hidden), hidden
        x = tree.column('run', 'width') // 2
        assert tree.identify_region(x, 5) == 'heading'
        tree.event_generate('<ButtonPress-3>', x=x, y=5)
        tree.event_generate('<ButtonRelease-3>', x=x, y=5)
        assert menu.posted == 1, menu.posted
        assert win.selected_dirs() == picked, win.selected_dirs()
        # the hover text: a heading still explains its column...
        assert win._picker_tip(x, 5)[0] == ('heading', 'run')
        # ...and a separator in the heading row is no row at all
        sep = tree.column('run', 'width')
        assert tree.identify_region(sep, 5) == 'separator'
        assert win._picker_tip(sep, 5) == (None, ''), win._picker_tip(sep, 5)
        # while a row on screen still shows itself
        bx, by, _bw, bh = tree.bbox(rows[4])
        assert win._picker_tip(bx + 5, by + bh // 2)[0] == ('row', rows[4])


def test_a_drag_from_a_cut_off_bottom_row_keeps_that_row_as_its_anchor():
    """`#390` review: a plain press on the row cut off at the bottom of
    the list makes Tk scroll that row into view ('see' in its press
    handler), and DragSelect, after the Treeview class, then read the row
    from event.y, which by that time named the row below it (or no row,
    when the pressed one was the last). Dragging up from it cleared the
    selection instead of selecting the rows passed. The row is now read
    on a tag before the class, where Tk has not scrolled yet.

    The list is made half a row taller than its nine rows so that one
    row is cut off, and packed without expand, so that a taller desktop,
    which stretches the controls, cannot change that.

    This PC's Tk 8.6.14 counts a cut-off row as on screen and does not
    scroll on that press (measured 2026-10-07), while the Tk sources the
    review read do. The case puts that scroll in on a tag of its own
    right after the Treeview class, where the newer handler's would run,
    so the drag is held to it here too."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        tree = w.win.run_box
        rows = _more_runs(w)
        box = tree.master
        box.pack_configure(expand=False)
        box.configure(height=box.winfo_height() + tree.bbox(rows[0])[3] // 2)
        w.settle(0.4)
        height = tree.winfo_height()
        cut = rows[rows.index(_whole_rows(tree, rows)[-1]) + 1]
        bx, by, _bw, bh = tree.bbox(cut)
        assert by < height - 3 < by + bh, ('not cut off', by, bh, height)

        def see_it(event):
            """The newer press handler's 'see': a cut-off row pressed is
            scrolled wholly into view."""
            row = tree.identify_row(event.y)
            box = tree.bbox(row) if row else ''
            if box and box[1] + box[3] > tree.winfo_height():
                tree.yview_scroll(1, 'units')
        tags = list(tree.bindtags())
        at = tags.index(tree.winfo_class()) + 1
        tree.bindtags(tuple(tags[:at] + ['SeeLikeNewerTk'] + tags[at:]))
        tree.bind_class('SeeLikeNewerTk', '<ButtonPress-1>', see_it)

        def sel():
            chosen = set(tree.selection())
            return [r for r in rows if r in chosen]
        top = tree.yview()[0]
        tree.event_generate('<ButtonPress-1>', x=bx + 10, y=by + 3)
        assert tree.yview()[0] > top, 'Tk did not scroll the row into view'
        assert sel() == [cut], sel()
        i = rows.index(cut)
        tx, ty, _tw, th = tree.bbox(rows[i - 4])
        tree.event_generate('<B1-Motion>', x=tx + 10, y=ty + th // 2)
        tree.event_generate('<ButtonRelease-1>', x=tx + 10, y=ty + th // 2)
        assert sel() == rows[i - 4:i + 1], sel()


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


class _Ev:
    """A button_press_event as matplotlib delivers one."""

    def __init__(self, ax, x, y, dbl=True):
        self.inaxes, self.x, self.y, self.dblclick = ax, x, y, dbl


def _marker(win, panel=0):
    """(axes, px, py, run, row) for a marker of the CURRENT figure."""
    opts, err = win.current_opts()
    assert not err, err
    ax = win.fig.axes[panel]
    pts = g.plot_points(win._prepared, opts, panel)
    x, y, run, row = pts[1]
    px, py = ax.transData.transform((x, y))
    return ax, px, py, run, row


def test_a_double_click_survives_a_redraw_under_it():
    """THE `#311` BUG. `on_click` resolved the panel with
    `list(self.fig.axes).index(event.inaxes)`, which raises ValueError the
    moment the figure is cleared and redrawn between the event being built
    and the handler running -- and the except returned None SILENTLY. The
    operator saw a double-click open Edge Review once and then do nothing
    at all, with no message anywhere to say what had happened.

    A redraw is forced between the two clicks here, which is the condition
    itself rather than a stand-in for it: the second click carries an Axes
    that is genuinely no longer in the figure."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        win = w.win
        spy = _Popen()
        real = g.subprocess
        g.subprocess = spy
        try:
            ax_old, px, py, _run, row = _marker(win)
            assert win.on_click(_Ev(ax_old, px, py)) is not None
            assert len(spy.calls) == 1

            # The figure is rebuilt under the pointer -- every Axes object
            # the first click knew is gone.
            #
            # `_drawn_key` is cleared FIRST because `#316` made a redraw
            # whose inputs are unchanged re-run the layout instead of
            # rebuilding, which keeps the Axes alive. That is the whole
            # point of that change and it is not being worked around: this
            # case needs a genuine rebuild, so it asks for one. Landing
            # `#311` and `#316` in the same wave took main to 38/39 for
            # exactly this reason -- each was green alone, and the clash is
            # semantic, so git merged both without a murmur.
            win._drawn_key = None
            win.redraw()
            w.settle(0.3)
            assert ax_old not in win.fig.axes, 'redraw kept the same Axes'

            # a click carrying the STALE axes still resolves, on the same
            # row, because the panel is re-asked of the figure as it is now
            ax_new, px2, py2, _r2, row2 = _marker(win)
            spy.calls.clear()
            got = win.on_click(_Ev(ax_old, px2, py2))
            assert got is not None, 'the stale-axes double-click was dropped'
            assert got[1]['index'] == row2['index'] == row['index']
            assert len(spy.calls) == 1, spy.calls
            assert spy.calls[0][1].get('start_new_session') is True

            # and so does the ordinary one that carries the current axes
            spy.calls.clear()
            assert win.on_click(_Ev(ax_new, px2, py2)) is not None
            assert len(spy.calls) == 1

            # repeatedly: three redraws, three double-clicks, three launches
            spy.calls.clear()
            for _i in range(3):
                win.redraw()
                w.settle(0.2)
                ax_i, pxi, pyi, _ri, _rowi = _marker(win)
                assert win.on_click(_Ev(ax_i, pxi, pyi)) is not None
            assert len(spy.calls) == 3, spy.calls
        finally:
            g.subprocess = real


def test_no_click_leaves_the_window_without_an_answer():
    """`#311`'s other half, and the reason it took an operator report to
    find at all: FOUR paths out of `on_click` returned None in silence --
    not a double-click, off the panels, nothing prepared, unusable
    options. A swallowed interaction cannot be told apart from a broken
    feature, so every path now either acts or says why, in the one line
    that was already there to report what the last click resolved."""
    with _Win('1400x900') as w:
        if not w.ok:
            return
        win = w.win
        spy = _Popen()
        real = g.subprocess
        g.subprocess = spy
        try:
            ax, px, py, run, row = _marker(win)

            def said(ev):
                """-> what the window said, having said nothing before."""
                win.lbl_click.config(text='')
                spy.calls.clear()
                assert win.on_click(ev) is None
                assert spy.calls == [], 'a refused click still launched'
                text = win.lbl_click.cget('text')
                assert text, 'the click was swallowed in silence'
                return text

            # 1 -- a SINGLE click on a marker. This is the reported
            # symptom: a double-click that reaches the window as two
            # singles used to do nothing and say nothing. It names the
            # frame it is on and asks for the second click.
            text = said(_Ev(ax, px, py, dbl=False))
            assert 'single click' in text.lower()
            assert run['name'] in text and 'DOUBLE-click' in text

            # 2 -- a double-click that is not over a panel
            text = said(_Ev(None, 2.0, 2.0))
            assert 'not over a panel' in text

            # 3 -- a double-click with nothing plotted to click through to
            prepared, win._prepared = win._prepared, []
            try:
                text = said(_Ev(ax, px, py))
                assert 'nothing is plotted' in text
            finally:
                win._prepared = prepared

            # 4 -- a double-click while the draw options cannot be built
            opts_real = win.current_opts
            win.current_opts = lambda: (None, 'mode is not usable here')
            try:
                text = said(_Ev(ax, px, py))
                assert 'mode is not usable here' in text
            finally:
                win.current_opts = opts_real

            # 5 -- the miss that always did report, still reports
            text = said(_Ev(ax, px, py - g.PICK_PX - 200))
            assert 'no data point within' in text

            # ...and after all of that the ordinary double-click still works
            spy.calls.clear()
            assert win.on_click(_Ev(ax, px, py)) is not None
            assert len(spy.calls) == 1
            assert run['name'] in win.lbl_click.cget('text')
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
                       # `#313`. 'aggregate_only' is an ordinary drawing
                       # answer and joins like the rest. 'groups' is the
                       # one entry here that names PARTICULAR RUNS, which
                       # is what the run selection is deliberately kept
                       # out for -- it joins anyway because it is a
                       # LABELLING of runs and not a choice of them: it
                       # is keyed on absolute run directories, so a group
                       # naming a run nobody selected draws nothing, and
                       # a stale one is inert rather than wrong. Re-typing
                       # 'these six are P3' every session is not.
                       'groups': [], 'aggregate_only': False,
                       # `#373`: the material each group was formed with
                       # travels WITH the grouping; re-reading setup.txt
                       # on reopening would let an edit made in between
                       # restyle groups the operator already looked at
                       'group_materials': [],
                       # the normalized panel's units joins as an ordinary
                       # drawing answer: a lab that quotes strain quotes it
                       # every session, and re-ticking it each time is the
                       # annoyance this file exists to end.
                       'strain_pct': False,
                       # 2026-09-23: the x axis and the up/down leg view
                       # join as drawing answers too -- a lab that reads
                       # its runs against time, or never wants arrows,
                       # does so every session
                       'x': 'kv', 'split_legs': True, 'arrows': True,
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


def _heads(win):
    """The headings the drawn figure is actually carrying, per panel."""
    return [ax.get_title(loc='left') for ax in win.fig.axes]


def test_an_empty_heading_box_hints_at_the_heading_the_figure_will_use():
    """`#315`: three empty boxes said nothing about being editable.

    The hint is what the panel WILL READ, measured off the drawn figure
    rather than recomputed here -- a hint that agreed with a second copy
    of the wording and not with the axes would be exactly the wrong
    label that looks like a right one."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        win.redraw()
        first, second = _heads(win)
        hints = win.title_hints()
        # Title and Panel 1 both head the FIRST panel, so both hint at it
        assert hints['title'] == first, hints
        assert hints['title_first'] == first, hints
        assert hints['title_second'] == second, hints
        assert 'Active area' in first and 'A₀' in second
        # ...and it is a HINT, not a value: nothing reached the options,
        # so the figure still derived every one of those headings itself
        opts, err = win.current_opts()
        assert not err, err
        for k in ('title', 'title_first', 'title_second'):
            assert opts[k] is None, (k, opts[k])


def test_a_heading_hint_follows_the_mode_while_the_box_is_untouched():
    """The staleness trap. Switching area -> current changes what the
    first panel's heading says, and a hint left showing the old one would
    be worse than an empty box."""
    # the second panel's default names the baseline it divides by, so it
    # moves with the RUN SELECTION and not only with the mode -- which is
    # why the window may not treat it as a fixed string it can pre-fill
    # once
    area, _e = sp.make_opts(mode='area')
    one = sp.default_panel_titles(area, [{'a0': 201.062}])['second']
    many = sp.default_panel_titles(area, [{'a0': 201.062},
                                          {'a0': 98.4}])['second']
    assert '201.1' in one and 'per-run' in many, (one, many)
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        win.redraw()
        was = win.title_hints()['title_first']
        win.v_mode.set('current')
        win._mode_changed()
        win.redraw()
        now = win.title_hints()
        assert now['title_first'] != was, 'the hint went stale'
        assert now['title_first'] == _heads(win)[0] == 'Current -- per '\
            'snapshot', now
        assert now['title'] == now['title_first']
        # current draws ONE panel, so the second box heads nothing: greyed,
        # and hinting at a heading nothing carries would contradict that
        assert now['title_second'] == '', now
        assert _state(win.e_title_second) == 'disabled'


def test_a_typed_heading_is_never_clobbered_by_a_mode_switch():
    """The other half of the staleness trap: the hint may follow the mode
    only while the box is UNTOUCHED. Once there is text in it, it is the
    operator's, and the box shows exactly what the figure shows."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        win.v_title_first.set('mm² vs kV')
        win._title_typed()
        win.redraw()
        assert win.title_hints()['title_first'] == '', 'hint over the text'
        assert _heads(win)[0] == 'mm² vs kV'
        win.v_mode.set('current')
        win._mode_changed()
        win.redraw()
        assert win.v_title_first.get() == 'mm² vs kV', 'the mode ate it'
        assert _heads(win)[0] == 'mm² vs kV'
        assert win.title_hints()['title_first'] == ''
        # the legacy Title box is still empty and still truthful: it heads
        # the same panel, which now reads the text typed above
        assert win.current_opts()[0]['title'] is None
        assert win.title_hints()['title'] == 'mm² vs kV'


def test_clearing_a_heading_returns_to_the_derived_one():
    """Emptying a box must give the DERIVED heading back, never a
    literally empty one. It does so because the hint was never a value:
    there is no pre-fill to undo, so `_panel_title` reads blank as 'no
    override' exactly as it always has."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        win.redraw()
        derived = _heads(win)[1]
        win.v_title_second.set('normalized')
        win._title_typed()
        win.redraw()
        assert _heads(win)[1] == 'normalized'
        for blank in ('', '   '):
            win.v_title_second.set(blank)
            win._title_typed()
            win.redraw()
            assert win.current_opts()[0]['title_second'] is None, blank
            assert _heads(win)[1] == derived, blank
            assert win.title_hints()['title_second'] == derived, blank


def test_no_derived_heading_reaches_the_remembered_options_file():
    """The failure that would only show up NEXT session (`#275` + `#315`).

    Closing writes the WHOLE remembered set at once, so a derived heading
    that had leaked into a variable would be saved as if the operator had
    chosen it, and next week's figure would open captioned with last
    week's default. Checked against the file's BYTES rather than its
    keys: a leak into any key at all is a leak.

    The figspec (`#273`) is the same hazard with a longer reach -- it
    records `dict(opts)` verbatim beside every exported PNG, unfiltered by
    any key list, and --from-spec re-renders from it."""
    import json
    import tkinter as tk
    p = _mktmp()
    was = (g.OPTIONS_PATH, g.OPTIONS_FALLBACK)
    try:
        cfg = os.path.join(p, 'opts.json')
        # BOTH, so a real user's file cannot be read or written even if
        # the primary is the one this desktop would fall back from
        g.OPTIONS_PATH = g.OPTIONS_FALLBACK = cfg
        _fake_run(p, 'R1')
        try:
            root = tk.Tk()
        except tk.TclError as e:
            print(f"   (skipped: no display for Tk: {e})")
            return
        root.withdraw()
        win = g.PlotWindow(root, p, preselect=['R1'], remember=True)
        win.redraw()
        hints = win.title_hints()
        assert hints['title_first'] and hints['title_second'], hints
        opts, err = win.current_opts()
        assert not err, err
        # the sidecar first, while the window is still alive
        spec = sp.build_figspec([], opts, 'sldea_plot_area')
        for k in ('title', 'title_first', 'title_second'):
            assert spec['opts'][k] is None, (k, spec['opts'][k])
        win._closing()                 # the real on-close write
        with open(cfg, encoding='utf-8') as f:
            blob = f.read()
        entry = json.loads(blob)['parents'][g.options_key(p)]
        assert set(entry) == set(g.REMEMBERED), set(entry) ^ set(
            g.REMEMBERED)
        for text in hints.values():
            assert text and text not in blob, f"{text!r} was remembered"
        back = g.load_options(p, path=cfg)
        for k in ('title', 'title_first', 'title_second'):
            assert k not in back, k
    finally:
        g.OPTIONS_PATH, g.OPTIONS_FALLBACK = was
        shutil.rmtree(p, ignore_errors=True)
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


# ---------------------------------------------------------------------------
# operator-assigned groups in the window (`#313`)
# ---------------------------------------------------------------------------

def test_assigning_runs_to_groups_reaches_the_opts_the_figure_is_drawn_from():
    """The whole chain in one case: select runs, type a name, press
    Assign -- and the grouping has to arrive in current_opts, because a
    group box that edited state the redraw never read would be the exact
    wiring gap this window has had before."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        _fake_run(b.tmp, 'R2')
        win.populate()
        assert len(win.runs) == 2, win.runs
        first, second = [d for d, _l in win.runs]
        assert win.current_opts()[0]['groups'] == []
        # nothing selected: refused with a sentence, not a traceback
        assert win.set_selected_dirs([]) == []
        assert win.assign_group('CB', win.selected_dirs())
        win.set_selected_dirs([first])
        assert win.assign_group('CB', win.selected_dirs()) is None
        win.set_selected_dirs([second])
        assert win.assign_group('P3', win.selected_dirs()) is None
        opts, err = win.current_opts()
        assert not err, err
        assert [n for n, _m in opts['groups']] == ['CB', 'P3'], opts['groups']
        assert opts['groups'][0][1] == [os.path.abspath(win.runs[0][0])]
        # ORDER IS THE OPERATOR'S: it picks the colours, so it survives
        assert win.group_list() == opts['groups']
        # a run moves between groups rather than being in both, which is
        # what the engine refuses outright
        win.set_selected_dirs([first])
        assert win.assign_group('P3', win.selected_dirs()) is None
        assert [n for n, _m in win.group_list()] == ['P3'], win.group_list()
        assert len(win.group_list()[0][1]) == 2
        # ...and 'ungroup' takes them back out without touching the rest
        win.set_selected_dirs([d for d, _l in win.runs])
        assert win.assign_group('', win.selected_dirs()) is None
        assert win.group_list() == []
        assert win.current_opts()[0]['groups'] == []


def test_the_group_box_reports_what_it_will_and_will_not_draw():
    """A grouping draws nothing unless the aggregate is on and the mode is
    area. The box is left LIVE in every mode -- it edits runs, like the
    run list, not the drawing -- so what would otherwise be a greying
    rule has to be said in words instead."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        assert 'No groups' in win.group_summary()
        win.set_selected_dirs([win.runs[0][0]])
        win.assign_group('CB', win.selected_dirs())
        win._groups_changed()
        assert 'CB (1)' in win.group_summary()
        assert 'Turn on the cross-run aggregate' in win.group_summary()
        win.v_aggregate.set(True)
        win._toggled()
        assert 'Turn on the cross-run aggregate' not in win.group_summary()
        assert win.lbl_groups.cget('text') == win.group_summary()
        # the aggregate is area-only, so the summary says so there too
        win.v_mode.set('current')
        win._mode_changed()
        assert 'Area mode only' in win.group_summary(), win.group_summary()
        # ...and the grouping is still carried in opts in that mode: a
        # figspec exported from current mode must not forget a grouping
        # the window is still showing
        assert win.current_opts()[0]['groups'], win.current_opts()[0]


def test_hiding_the_runs_greys_what_it_makes_inert_and_silences_the_click():
    """Two consequences of `#313`'s hide, both of which would otherwise be
    a control or a message that lies.

    The marker key explains the open/closed RUN markers, and with no run
    markers on the figure it explains nothing -- greyed, like every other
    inert control here. And the click-through resolves a double-click
    against per-run rows; with the runs hidden there are none, and the
    fall-through message ('no data point within 30 px') would send an
    operator on to aim more carefully at markers that are not there."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        assert _state(win.cb_aggregate_only) == 'disabled', 'live with no aggregate'
        assert _state(win.cb_marker_key) == 'normal'
        win.v_aggregate.set(True)
        win._toggled()
        assert _state(win.cb_aggregate_only) == 'normal'
        win.v_aggregate_only.set(True)
        win._toggled()
        assert _state(win.cb_marker_key) == 'disabled', 'key still live'
        win.redraw()
        opts, err = win.current_opts()
        assert not err and opts['aggregate_only'] is True
        # nothing on the figure is clickable, and the window says why
        assert g.plot_points(win._prepared, opts) == []

        class _E:
            dblclick = True
            x = y = 100
            inaxes = None
        assert win.on_click(_E()) is None
        said = win.lbl_click.cget('text')
        assert 'hidden' in said, said
        # UNTICKING THE AGGREGATE cannot leave an unusable combination:
        # make_opts refuses aggregate_only without it, and an error where
        # the figure goes is not what unticking a box should produce
        win.v_aggregate.set(False)
        win._toggled()
        opts2, err2 = win.current_opts()
        assert err2 is None, err2
        assert opts2['aggregate_only'] is False
        assert _state(win.cb_marker_key) == 'normal', 'key stayed greyed'


def test_a_grouping_survives_a_round_trip_through_the_options_file():
    """`#313`'s open question, answered: groups PERSIST, per parent
    folder, alongside the other remembered options.

    They are the one remembered entry that names particular runs, which
    the run SELECTION is deliberately kept out of the file for. The
    difference is that a grouping is keyed on absolute run directories
    and draws nothing unless a run it names is both selected and the
    aggregate is on -- so a stale group is inert, where a stale selection
    would silently plot the wrong batch."""
    import tkinter as tk
    p = _mktmp()
    try:
        cfg = os.path.join(p, 'opts.json')
        a = _fake_run(p, 'A_run')
        groups = [['CB', [a]]]
        opts, err = sp.make_opts(aggregate=True, groups=groups)
        assert err is None, err
        assert g.save_options(p, opts, path=cfg) == cfg
        back = g.load_options(p, path=cfg)
        assert back['groups'] == opts['groups'], back.get('groups')
        assert back['aggregate_only'] is False
        # a hand-edited file cannot smuggle past what the window itself
        # would refuse -- STRUCTURED_OPTIONS is the site `#314`'s
        # NUMERIC_OPTIONS was, one category further out
        assert 'groups' in g.STRUCTURED_OPTIONS
        for bad in ({'groups': 'not a list'}, {'groups': None},
                    {'groups': [['CB', ['x']], ['CB', ['y']]]},
                    {'groups': [['CB', ['x']], ['P3', ['x']]]}):
            assert 'groups' not in g._clean_options(bad), bad
        # ...and an empty one round-trips as itself rather than vanishing
        assert g._clean_options({'groups': []})['groups'] == []
        # the window OPENS on the remembered grouping
        try:
            root = tk.Tk()
        except tk.TclError as e:
            print(f"   (skipped: no display for Tk: {e})")
            return
        try:
            root.withdraw()
            real = g.OPTIONS_PATH
            g.OPTIONS_PATH = cfg
            try:
                win = g.PlotWindow(root, p, preselect=['A_run'])
            finally:
                g.OPTIONS_PATH = real
            assert [n for n, _m in win.group_list()] == ['CB'], \
                win.group_list()
            assert win.current_opts()[0]['groups'] == opts['groups']
        finally:
            _shut(root)
    finally:
        shutil.rmtree(p, ignore_errors=True)


# ---------------------------------------------------------------------------
# "Group by material" and its "...and by concentration" child (`#373`)
# ---------------------------------------------------------------------------

_ABSENT = object()
P3 = 'Carbon Solutions P3-SWNT'
N3900 = 'nano-c Invisicon 3900'
CB = 'carbon black'


def _label(rundir, electrode=_ABSENT, conc=_ABSENT):
    """Give a run a setup.txt carrying these lines; _ABSENT leaves one out,
    which is not the same as recording '(not specified)'."""
    lines = [f"SLDEA Test  --  {os.path.basename(rundir)}", '']
    if electrode is not _ABSENT:
        lines.append(f"Compliant electrode: {electrode}")
    if conc is not _ABSENT:
        lines.append(f"Ink concentration: {conc}")
    with open(os.path.join(rundir, 'setup.txt'), 'w',
              encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return rundir


def _select(win, *names):
    """Select exactly the runs with these folder names, through the
    window's one selection setter (`#374`), so no case here touches the
    run widget's own API."""
    win.set_selected_dirs([rundir for rundir, _text in win.runs
                           if os.path.basename(rundir) in names])


def _campaign(b):
    """The fixture runs beside _Bare's R1 (which has no setup.txt)."""
    for name, electrode, conc in (('P3a', P3, '2.5 mL'),
                                  ('P3b', P3, '2.50 mL'),
                                  ('P3c', 'carbon solutions p3-swnt',
                                   '1.5mL'),
                                  ('N39', N3900, _ABSENT),
                                  ('CB1', CB, _ABSENT),
                                  ('NS', '(not specified)', _ABSENT)):
        _label(_fake_run(b.tmp, name), electrode, conc)
    b.win.populate()


def test_group_by_material_seeds_ordinary_groups_from_the_selection():
    """One click: the SELECTED runs land in one group per recorded
    material, the two kinds of 'no material' apart. Then they are
    ordinary groups: Assign, Ungroup and Clear all work on top, an
    unselected run's group is left alone, and current_opts carries the
    grouping and each group's material to the figure."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        _campaign(b)
        _select(win, 'NS')
        assert win.assign_group('mine', win.selected_dirs()) is None
        _select(win, 'R1', 'P3a', 'P3b', 'P3c', 'N39', 'CB1')
        assert win.seed_groups('material') is None
        rows = {n: sorted(os.path.basename(p) for p in m)
                for n, m in win.group_list()}
        assert list(rows) == ['mine', CB, P3, N3900,
                              sp.NO_ELECTRODE_GROUP], list(rows)
        assert rows[P3] == ['P3a', 'P3b', 'P3c'], rows
        assert rows['mine'] == ['NS'], 'the seed touched an unselected run'
        assert dict(win.group_material_list()) == {CB: CB, P3: P3,
                                                   N3900: N3900}
        opts, err = win.current_opts()
        assert err is None, err
        assert opts['groups'] == win.group_list()
        assert opts['group_materials'] == win.group_material_list()
        # ORDINARY groups: a run moved by hand goes where it is put, and
        # the group it joins keeps its own material (`#313`: the
        # operator's grouping wins)
        _select(win, 'P3c')
        assert win.assign_group(CB, win.selected_dirs()) is None
        assert dict(win.group_material_list())[CB] == CB
        _select(win, 'R1')
        assert win.assign_group('', win.selected_dirs()) is None
        assert sp.NO_ELECTRODE_GROUP not in dict(win.group_list())
        # nothing selected: refused in words, and nothing moves
        before = win.group_list()
        _select(win)
        assert win.seed_groups('material')
        assert win.group_list() == before
        win._clear_groups()
        assert win.group_list() == [] and win.group_material_list() == []
        assert 'No groups' in win.group_summary()


def test_by_concentration_is_the_material_seeds_child_and_splits_volumes():
    """The owner asked for it as a SUB-button: indented under 'Group by
    material' the way the cadence guard sits under the breakdown marks,
    right after it in the same box. Pressed, it splits each material by
    its normalized ink volume, and the subgroups keep their material."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        parent, child = win.btn_seed_material, win.btn_seed_concentration
        assert parent.winfo_parent() == child.winfo_parent()
        slaves = parent.master.pack_slaves()
        assert slaves.index(child) == slaves.index(parent) + 1

        def left_pad(widget):
            pad = widget.pack_info().get('padx', 0)
            if isinstance(pad, (tuple, list)):
                return int(pad[0])
            return int(str(pad).split()[0])
        assert left_pad(child) > left_pad(parent), 'child is not indented'
        assert str(child.cget('text')).startswith('…')
        assert str(win.cb_cadence.cget('text')).startswith('…')
        _campaign(b)
        # runs with NO material but an ink volume: owner decision
        # 2026-10-06, they stay one group each and are never split
        _label(_fake_run(b.tmp, 'NS2'), '(not specified)', '1.5 mL')
        _label(_fake_run(b.tmp, 'NOEL'), _ABSENT, '2.5 mL')
        win.populate()
        _select(win, 'P3a', 'P3b', 'P3c', 'N39', 'CB1', 'NS', 'NS2', 'NOEL',
                'R1')
        child.invoke()
        rows = {n: sorted(os.path.basename(p) for p in m)
                for n, m in win.group_list()}
        assert list(rows) == [CB, f"{P3}, 1.5 mL", f"{P3}, 2.5 mL", N3900,
                              sp.NOT_SPECIFIED, sp.NO_ELECTRODE_GROUP], \
            list(rows)
        assert rows[f"{P3}, 2.5 mL"] == ['P3a', 'P3b'], rows
        assert rows[sp.NOT_SPECIFIED] == ['NS', 'NS2'], rows
        assert rows[sp.NO_ELECTRODE_GROUP] == ['NOEL', 'R1'], rows
        mats = dict(win.group_material_list())
        assert mats[f"{P3}, 1.5 mL"] == mats[f"{P3}, 2.5 mL"] == P3
        assert sp.NOT_SPECIFIED not in mats
        assert win.lbl_groups.cget('text') == win.group_summary()
        # ...and the plain seed over the same selection merges them back
        parent.invoke()
        assert [n for n, _m in win.group_list()] == [
            CB, P3, N3900, sp.NOT_SPECIFIED, sp.NO_ELECTRODE_GROUP]


def test_a_new_group_takes_its_material_and_moved_runs_take_the_groups():
    """When the material is decided: at the moment a group is FORMED.
    A new group of one material gets it; a mixed one gets none (a style
    of its own); a run moved into an existing group takes that group's
    material, so moving a hand-typed 'Invisicon 3900' into the dropdown
    spelling's group merges the two into one series (`#374`)."""
    with _Bare() as b:
        if not b.ok:
            return
        win = b.win
        _campaign(b)
        _label(_fake_run(b.tmp, 'N39hand'), 'Invisicon 3900')
        win.populate()
        _select(win, 'P3a', 'P3c')
        assert win.assign_group('ink', win.selected_dirs()) is None
        assert win.group_material_list() == [['ink', P3]]
        _select(win, 'P3b', 'CB1')
        assert win.assign_group('mixed', win.selected_dirs()) is None
        assert 'mixed' not in dict(win.group_material_list())
        _select(win, 'N39')
        assert win.assign_group('3900', win.selected_dirs()) is None
        _select(win, 'N39hand')
        assert win.assign_group('3900', win.selected_dirs()) is None
        assert dict(win.group_material_list())['3900'] == N3900
        # a name differing only in case lands in the existing group
        # instead of being refused as a second group of the same name
        _select(win, 'NS')
        assert win.assign_group('INK', win.selected_dirs()) is None
        assert [n for n, _m in win.group_list()] == ['ink', 'mixed', '3900']
        assert dict(win.group_material_list())['ink'] == P3
        # emptied, the group and its material go; formed again, it is
        # read afresh from its new runs
        _select(win, 'P3a', 'P3c', 'NS')
        assert win.assign_group('', win.selected_dirs()) is None
        assert 'ink' not in dict(win.group_list())
        _select(win, 'CB1')
        assert win.assign_group('ink', win.selected_dirs()) is None
        assert dict(win.group_material_list())['ink'] == CB


def test_a_seeded_grouping_round_trips_through_the_figspec_and_tidy_csv():
    """Seeded in the window, exported, read back: the tidy CSV's group
    column names each run's seeded group, the figspec holds the grouping
    and the materials verbatim, and a window opened on that spec shows
    the same groups with the same materials, whatever setup.txt says
    by then."""
    out = _mktmp()
    try:
        with _Bare() as b:
            if not b.ok:
                return
            win = b.win
            _campaign(b)
            _select(win, 'R1', 'P3a', 'P3b', 'N39', 'CB1', 'NS')
            assert win.seed_groups('concentration') is None
            # current mode: the fixtures carry no estimator stamp, and the
            # grouping rides in opts in every mode
            win.v_mode.set('current')
            win._mode_changed()
            opts, err = win.current_opts()
            assert err is None, err
            runs = sp.prepare_runs(win.selected_dirs(), opts)
            img, tidy = sp.export(runs, opts, out, 'w')
            with open(tidy, newline='', encoding='utf-8') as f:
                got = {r['run']: r['group'] for r in csv.DictReader(f)}
            assert got == {'R1': sp.NO_ELECTRODE_GROUP,
                           'P3a': f"{P3}, 2.5 mL", 'P3b': f"{P3}, 2.5 mL",
                           'N39': N3900, 'CB1': CB,
                           'NS': sp.NOT_SPECIFIED}, got
            spec, err = sp.load_figspec(sp.figspec_path(img))
            assert err is None, err
            assert spec['opts']['groups'] == opts['groups']
            assert spec['opts']['group_materials'] == opts['group_materials']
            # relabel a run AFTER the export: the spec must not care
            _label(os.path.join(b.tmp, 'N39'), CB)
            again = g.PlotWindow(b.root, b.tmp, preselect=['N39'],
                                 opts=spec['opts'], remember=False)
            assert again.group_list() == win.group_list()
            assert again.group_material_list() == win.group_material_list()
            _select(again)
            assert again.current_opts()[0]['group_materials'] == \
                opts['group_materials']
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_remembered_materials_travel_with_their_groups_only():
    """group_materials is remembered beside the grouping, and only
    beside it: groups given explicitly (a spec, a command line) never
    borrow a remembered material for a group that happens to share a
    name, or a figure would be styled by a file it never named."""
    import tkinter as tk
    p = _mktmp()
    try:
        cfg = os.path.join(p, 'opts.json')
        a = _label(_fake_run(p, 'A_run'), P3)
        opts, err = sp.make_opts(aggregate=True, groups=[['P3', [a]]],
                                 group_materials=[['P3', P3]])
        assert err is None, err
        assert g.save_options(p, opts, path=cfg) == cfg
        back = g.load_options(p, path=cfg)
        assert back['group_materials'] == [['P3', P3]], back
        assert 'group_materials' in g.STRUCTURED_OPTIONS
        for bad in ({'group_materials': 'P3'},
                    {'group_materials': [['P3']]},
                    {'group_materials': [['P3', P3], ['p3', CB]]}):
            assert 'group_materials' not in g._clean_options(bad), bad
        try:
            root = tk.Tk()
        except tk.TclError as e:
            print(f"   (skipped: no display for Tk: {e})")
            return
        try:
            root.withdraw()
            real = g.OPTIONS_PATH
            g.OPTIONS_PATH = cfg
            try:
                win = g.PlotWindow(root, p, preselect=['A_run'])
                spec_opts = sp.make_opts(aggregate=True,
                                         groups=[['P3', [a]]])[0]
                bare = g.PlotWindow(root, p, preselect=['A_run'],
                                    opts=spec_opts)
            finally:
                g.OPTIONS_PATH = real
            assert win.group_material_list() == [['P3', P3]]
            assert bare.group_list() == spec_opts['groups']
            assert bare.group_material_list() == [], \
                'explicit groups borrowed a remembered material'
        finally:
            _shut(root)
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_the_group_tips_say_what_is_read_from_setup_txt():
    """`#373` made two sentences of GROUP_ASSIGN_TIP false: the backfill
    put 'Electrode family:' in the corpus on 2026-08-12, and the seed now
    reads setup.txt. The tips must say what the window really does."""
    tip = g.GROUP_ASSIGN_TIP
    assert 'no run in the corpus carries it' not in tip
    assert 'nothing is read from setup.txt' not in tip
    assert 'Group by material' in tip
    assert 'existing group' in tip
    for phrase in ('SELECTED', 'Compliant electrode:',
                   sp.NO_ELECTRODE_GROUP, sp.NOT_SPECIFIED,
                   'not a mode', 'line style'):
        assert phrase in g.GROUP_SEED_TIP, phrase
    for phrase in ('Ink concentration:', '2.5mL', sp.NO_CONCENTRATION,
                   'line style'):
        assert phrase in g.GROUP_SEED_CONC_TIP, phrase


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


def test_plot_points_follow_the_strain_percent_panel():
    """With the normalized panel as strain %, the markers sit at
    (A-A0)/A0*100 -- but plot_points divided by A0 inline and kept the
    click targets at A/A0, so on that panel a double-click resolved
    against coordinates the figure never drew and opened the wrong frame
    (found 2026-09-23). Here every area equals A0: the panel draws both
    rows at 0 % while the old targets sat at 1.0."""
    p = _mktmp()
    try:
        _fake_run(p, 'A_run', processed=True)
        runs, opts = _prepared(p, ['A_run'], mode='area', strain_pct=True)
        a0 = runs[0]['a0']
        pts = g.plot_points(runs, opts, panel=1)
        assert [r['index'] for _x, _y, _run, r in pts] == [0, 1]
        for _x, y, _run, r in pts:
            want = sp.norm_y(r['area_mm2'], a0, True)
            assert abs(y - want) < 1e-9, (y, want)
        assert all(abs(y) < 1e-9 for _x, y, _r, _w in pts), pts
        # the ratio panel is untouched with strain % off
        runs, opts = _prepared(p, ['A_run'], mode='area')
        assert all(abs(y - 1.0) < 1e-9
                   for _x, y, _r, _w in g.plot_points(runs, opts, panel=1))
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_plot_points_follow_the_time_axis():
    """On the elapsed-time axis a double-click has to resolve against the
    snapshots' TIMES. plot_points placed every target at its kV, which on
    that axis is where no marker was drawn (2026-09-23)."""
    p = _mktmp()
    try:
        _fake_run(p, 'A_run', processed=True)
        # the fixture's two snapshots are a minute apart on the wall clock
        for mode in ('area', 'current'):
            runs, opts = _prepared(p, ['A_run'], mode=mode, x='time')
            xs = [x for x, _y, _r, _w in g.plot_points(runs, opts)]
            assert xs == [0.0, 1.0], (mode, xs)
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_the_time_axis_greys_and_neutralises_the_kv_only_options():
    """Pre/post, the mean line and the aggregate pool by kV; make_opts
    refuses them beside --x time. The window greys them and neutralises
    them -- a figure, not an error, when the axis is switched -- and KEEPS
    the ticks, so switching back restores what the operator had."""
    with _Win() as w:
        if not w.ok:
            return
        win = w.win
        win.v_prepost.set(True)
        win.v_aggregate.set(True)
        win.v_x.set('time')
        win._toggled()
        w.settle()
        for cb in (win.cb_prepost, win.cb_mean, win.cb_aggregate,
                   win.cb_aggregate_only, win.cb_arrows):
            assert str(cb.cget('state')) == 'disabled', cb.cget('text')
        opts, err = win.current_opts()
        assert err is None, err
        assert opts['x'] == 'time' and not opts['prepost'] \
            and not opts['aggregate'], opts
        win.v_x.set('kv')
        win._toggled()
        opts, err = win.current_opts()
        assert err is None and opts['prepost'] and opts['aggregate'], opts
        assert str(win.cb_prepost.cget('state')) == 'normal'
        # the arrows are the leg split's CHILD: inert without it
        assert str(win.cb_arrows.cget('state')) == 'normal'
        win.v_split_legs.set(False)
        win._toggled()
        assert str(win.cb_arrows.cget('state')) == 'disabled'


def test_the_axis_and_leg_controls_explain_themselves():
    for key in ('x', 'split_legs', 'arrows'):
        assert len(g.DRAW_TIPS[key]) > 60, key
    # the two facts an operator most needs from the hover
    assert 'first rising leg' in g.DRAW_TIPS['split_legs']
    assert 'point right' in g.DRAW_TIPS['arrows']
    assert set(g.ENUM_OPTIONS['x']) == set(sp.X_AXES)


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
