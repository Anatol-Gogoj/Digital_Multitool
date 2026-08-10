#!/usr/bin/env python3
"""Headless tests for sldea_tuner's pure logic (no window).

Run: .venv/bin/python tests/test_sldea_tuner.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import sldea_tuner as st


def _rows(specs):
    # specs: list of (tag, kv, has_frame)
    out = []
    for k, (tag, kv, has) in enumerate(specs):
        out.append({'tag': tag, 'nominal_kV': ('' if kv is None else str(kv)),
                    'frame_file': (f'f{k}.png' if has else ''), 'step': k})
    return out


def test_choose_indices_baseline_mid_late():
    rows = _rows([('baseline', 0.0, True), ('post-ramp', 1.0, True),
                  ('post-ramp', 2.0, True), ('post-ramp', 3.0, True),
                  ('post-ramp', 4.0, True)])
    picks = st.choose_indices(rows)
    assert [p[0] for p in picks] == ['baseline', 'mid-run', 'late']
    assert picks[0][1] == 0           # baseline row
    assert picks[2][1] == 4           # highest kV
    assert picks[1][1] == 2           # nearest the 2.0 kV midpoint


def test_choose_indices_skips_frameless_and_finds_baseline_tag():
    # baseline not first; some rows have no frame file
    rows = _rows([('post-ramp', 1.0, False), ('baseline', 0.0, True),
                  ('post-ramp', 2.0, True), ('post-ramp', 5.0, True)])
    picks = st.choose_indices(rows)
    d = dict((l, i) for l, i in picks)
    assert d['baseline'] == 1
    assert d['late'] == 3
    # the frameless row 0 is never a content pick
    assert 0 not in [i for _, i in picks]


def test_choose_indices_unique_when_few_frames():
    rows = _rows([('baseline', 0.0, True), ('post-ramp', 4.0, True)])
    picks = st.choose_indices(rows)
    idxs = [i for _, i in picks]
    assert len(idxs) == len(set(idxs))        # no duplicate panels
    assert 0 in idxs and 1 in idxs


def test_choose_indices_missing_voltages_uses_median_index():
    rows = _rows([('baseline', None, True), ('post-ramp', None, True),
                  ('post-ramp', None, True), ('post-ramp', None, True)])
    picks = st.choose_indices(rows)
    assert len(picks) == 3
    assert picks[0][1] == 0
    # mid distinct from baseline and late
    assert len({i for _, i in picks}) == 3


def test_choose_indices_empty():
    assert st.choose_indices([]) == []


def _run_dir(parent, name, csv_name='data.csv'):
    import csv
    d = _os.path.join(parent, name)
    _os.makedirs(_os.path.join(d, 'frames'), exist_ok=True)
    with open(_os.path.join(d, csv_name), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['step', 'tag', 'nominal_kV',
                                          'frame_file'])
        w.writeheader()
        w.writerow({'step': 0, 'tag': 'baseline', 'nominal_kV': '0',
                    'frame_file': 'f0.png'})
    return d


def test_run_discovery_takes_custom_names_and_renamed_csvs():
    """Bench 2026-07-28: runs are named things like P3_1_2.5mL_20260728 and
    their data.csv gets renamed data1.csv so several open in Excel at once.
    Edge Review accepted both; the Tune buttons required an SLDEA_ prefix
    and the exact filename, so they saw no runs at all."""
    import tempfile
    parent = tempfile.mkdtemp(prefix='tuner_discovery_')
    custom = _run_dir(parent, 'P3_1_2.5mL_20260728', csv_name='data1.csv')
    assert st._newest_run(parent) == custom
    assert st.resolve_run(custom) == custom      # the run itself
    assert st.resolve_run(parent) == custom      # a parent full of runs
    # a directory that is not a run resolves to nothing rather than itself
    empty = _os.path.join(parent, 'not_a_run')
    _os.makedirs(empty, exist_ok=True)
    assert st.resolve_run(empty) is None
    assert st.resolve_run('') is None


def test_resolve_flag_prints_the_run_and_signals_failure():
    """The Windows launcher calls this instead of embedding Python in the
    batch file, so its contract is load-bearing: the path on stdout, a
    non-zero exit when nothing resolves."""
    import io
    import contextlib
    import tempfile
    parent = tempfile.mkdtemp(prefix='resolve_flag_')
    d = _run_dir(parent, 'P3_7_run', csv_name='data1.csv')
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = st.main(['--resolve', d])
    assert rc == 0, rc
    assert out.getvalue().strip() == d, out.getvalue()
    # a parent resolves to the run inside it
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert st.main(['--resolve', parent]) == 0
    assert out.getvalue().strip() == d
    # nothing to resolve: exit 2 and print no path for the caller to use
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = st.main(['--resolve', _os.path.join(parent, 'missing')])
    assert rc == 2, rc
    assert out.getvalue().strip() == ''


def test_resolve_flag_descends_into_a_campaign_wrapper():
    """`#261`, at the launcher's own front door. SCPI_SLDEA_DIR points at
    the campaign wrapper and the runs are nested in 'SLDEA_data (1)', so
    Tune_SLDEA_Windows.bat's --resolve step exited 2 -- "no run found" --
    on a machine holding 13 runs.

    The CONTRACT is unchanged and byte-compatible: the resolved directory
    on stdout with rc 0, and rc 0 with no stdout is impossible; anything
    unresolvable is still rc 2 with nothing printed, because the batch
    file reads that line as a path."""
    import io
    import contextlib
    import shutil
    import tempfile
    wrapper = tempfile.mkdtemp(prefix='resolve_wrap_')
    try:
        inner = _os.path.join(wrapper, 'SLDEA_data (1)')
        _os.makedirs(inner)
        older = _run_dir(inner, 'P3_1_2.5mL_20260728', csv_name='data1.csv')
        newer = _run_dir(inner, 'P3_2_2.5mL_20260728')
        t = _os.path.getmtime(newer)
        _os.utime(older, (t - 60, t - 60))
        _os.makedirs(_os.path.join(wrapper, '_analysis'), exist_ok=True)

        # THE FIX: the wrapper now resolves to the newest nested run
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = st.main(['--resolve', wrapper])
        assert rc == 0, rc
        assert out.getvalue().strip() == newer, out.getvalue()
        # ...and it is the same answer the picker's parent gives
        assert st.runs_parent(wrapper) == inner

        # UNCHANGED: a genuine non-run is still rc 2 with an empty stdout
        for path in (_os.path.join(wrapper, '_analysis'),
                     _os.path.join(wrapper, 'missing'), ''):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = st.main(['--resolve', path] if path else ['--resolve'])
            assert rc == 2, (path, rc)
            assert out.getvalue().strip() == '', (path, out.getvalue())
    finally:
        shutil.rmtree(wrapper, ignore_errors=True)


def test_windows_launcher_contract():
    """The Windows tuner launcher calls into this module by name. Batch
    files are not importable, so nothing else would notice a rename until a
    user double-clicks it on a machine none of us are sitting at."""
    bat = _os.path.join(_os.path.dirname(_os.path.dirname(
        _os.path.abspath(__file__))), 'deploy', 'Tune_SLDEA_Windows.bat')
    text = open(bat, encoding='utf-8', errors='replace').read()
    repo = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    assert 'sldea_tuner.py' in text
    # it resolves the run the same way the app's Tune buttons do, via the
    # --resolve flag rather than python -c: cmd mangles a quoted command
    # carrying quoted arguments, which broke every path with a space
    assert '--resolve' in text and callable(st.resolve_run)
    # Python must never be invoked from inside a for /f: that sub-shell runs
    # through cmd /c, which strips the outer quotes of a command that STARTS
    # with a quoted path and also carries quoted arguments. Every run path
    # containing a space then resolved to nothing. A direct call is fine.
    for line in text.splitlines():
        assert not ('for /f' in line and 'python.exe' in line), line
    # and that call's stderr must reach the log, never nul -- swallowing it
    # is what made the failure silent (bench 2026-07-28)
    resolve_line = next(ln for ln in text.splitlines() if '--resolve' in ln
                        and 'sldea_tuner.py' in ln)
    assert '2>>' in resolve_line and '2>nul' not in resolve_line
    # every script it can launch has to actually be there
    for script in ('sldea_tuner.py', 'sldea_diag.py'):
        assert script in text, script
        assert _os.path.exists(_os.path.join(repo, script)), script
    # A set-but-DANGLING SCPI_SLDEA_DIR must not skip the folder picker. The
    # value used to be taken unconditionally, so a stale pointer -- e.g. a
    # VirtualBox share no longer attached, live on the analysis VM
    # 2026-08-09 -- dead-ended the launcher instead of falling back to the
    # picker, which is what both Python front ends already do.
    assert 'if exist "%SCPI_SLDEA_DIR%\\"' in text, \
        'a dangling SCPI_SLDEA_DIR must not be taken as the target'
    # The trailing form is load-bearing and was measured under cmd:
    # `if exist "<path>\."` is TRUE for a plain FILE, so it would let a file
    # through as though it were a run folder. Only `"<path>\"` is true for a
    # directory and false for both a file and a dangling path.
    assert '"%SCPI_SLDEA_DIR%\\."' not in text, \
        'the "\\." form matches plain files too -- use "%SCPI_SLDEA_DIR%\\"'
    # `shift` moves %0 too, so %~dp0 must be banked BEFORE argument parsing
    # or the launcher cannot find the app it is sitting next to (bench
    # 2026-07-28). Batch has no unit tests; this is the guard.
    first_shift = text.find('\nshift')
    banked = text.find('set "HERE=%~dp0"')
    assert 0 <= banked < first_shift, (banked, first_shift)
    assert '%~dp0' not in text[first_shift:], "%~dp0 used after a shift"


# ---------------------------------------------------------------------------
# audit 2026-08-05 regressions
# ---------------------------------------------------------------------------

def test_norm_bg_checkbox_preserves_the_legacy_scalar():
    """audit 2026-08-05: norm_var was a two-state bool and recompute()
    wrote `2 if checked else 0` — merely OPENING the tuner on a
    norm_bg:1 run rewrote it to 2 in the startup recompute, and Save
    persisted the silent upgrade, breaking sldea_edge's 'a run tuned
    under it reprocesses identically'. Checked keeps the run's OWN
    mode."""
    assert st.norm_bg_value(True, 1) == 1      # the legacy run keeps 1
    assert st.norm_bg_value(True, 2) == 2
    assert st.norm_bg_value(True, 0) == 2      # never-normalized: default
    assert st.norm_bg_value(False, 1) == 0
    assert st.norm_bg_value(False, 2) == 0


def test_baseline_panel_is_picked_by_label_not_position():
    """audit 2026-08-05: load_panels drops unloadable picks, and
    panels[0] then silently promoted the MID-RUN (activated) frame to
    baseline — every diff, outline and mm² of the tuning session
    referenced to an activated state, while the footer promised Edge
    Review parity."""
    import numpy as np
    g = np.zeros((4, 4), np.float32)
    healthy = [{'label': 'baseline', 'idx': 0, 'row': {}, 'gray': g},
               {'label': 'mid-run', 'idx': 1, 'row': {}, 'gray': g},
               {'label': 'late', 'idx': 2, 'row': {}, 'gray': g}]
    assert st.baseline_panel(healthy) is healthy[0]
    # the failure state: the baseline pick did not load
    assert st.baseline_panel(healthy[1:]) is None
    assert st.baseline_panel([]) is None


def test_unreadable_baseline_drops_and_is_refused():
    """End to end on disk: a 0-byte baseline PNG drops out of
    load_panels, and baseline_panel reports the refusal instead of the
    old positional promotion of the next (activated) frame."""
    import csv
    import tempfile
    import cv2
    import numpy as np
    import shutil
    import sldea_edge as se
    d = tempfile.mkdtemp(prefix='tuner_nobase_')
    try:
        frames = _os.path.join(d, 'frames')
        _os.makedirs(frames)
        cols = ['snapshot', 'step', 'tag', 'nominal_kV', 'frame_file',
                'active_area_px', 'active_area_mm2', 'notes']
        rows = []
        for k, (tag, kv) in enumerate((('baseline', 0.0),
                                       ('post-ramp', 3.0),
                                       ('post-ramp', 6.0))):
            fn = f'SLDEA_s{k:02d}_{kv:05.2f}kV_{tag}.png'
            cv2.imwrite(_os.path.join(frames, fn),
                        np.full((60, 80), 120, np.uint8))
            rows.append({**{c: '' for c in cols}, 'tag': tag,
                         'nominal_kV': kv, 'frame_file': fn, 'step': k,
                         'snapshot': k + 1})
        with open(_os.path.join(d, 'data.csv'), 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        run = se.load_run(d)
        picks = st.choose_indices(run['rows'])
        assert st.baseline_panel(st.load_panels(run, picks)) is not None
        open(_os.path.join(frames, 'SLDEA_s00_00.00kV_baseline.png'),
             'wb').close()                       # truncate the baseline
        panels = st.load_panels(run, picks)
        assert len(panels) == 2
        assert st.baseline_panel(panels) is None
        assert panels[0]['label'] == 'mid-run', \
            "positional panels[0] would have been the activated frame"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_detect_panels_prefers_the_recorded_manual_anchor():
    """audit 2026-08-05: the tuner's mm² titles came from its own
    baseline_disc fit while Edge Review saved from the manual 📏 anchor
    — the two GUIs disagreed about one run's scale and neither said so.
    With a recorded anchor, detect_panels reports Edge Review's
    scale."""
    import numpy as np
    import sldea_edge as se
    yy, xx = np.mgrid[0:240, 0:320]
    base = np.full((240, 320), 190.0, np.float32)
    base[(xx - 160) ** 2 + (yy - 120) ** 2 <= 80 * 80] = 165.0
    img = base.copy()
    img[(xx - 160) ** 2 + (yy - 120) ** 2 <= 45 * 45] += 35
    panels = [{'label': 'baseline', 'idx': 0,
               'row': {'tag': 'baseline'}, 'gray': base},
              {'label': 'late', 'idx': 1,
               'row': {'tag': 'post-ramp'}, 'gray': img}]
    rows = [{'tag': 'baseline', 'nominal_kV': '0'},
            {'tag': 'post-ramp', 'nominal_kV': '3'}]
    s = dict(se.DEFAULT_SETTINGS)
    _r, _c, scale_auto = st.detect_panels(panels, base, s, rows)
    anchor = {'method': 'manual-calibration', 'diam_px': 200.0,
              'mm_per_px': 0.08}
    _r, _c, scale_anch = st.detect_panels(panels, base, s, rows,
                                          anchor=anchor)
    assert scale_anch is not None
    assert abs(scale_anch - s['diam_mm'] / 200.0) < 1e-12, scale_anch
    assert scale_auto is None or abs(scale_auto - scale_anch) > 1e-9, \
        "anchor preference is indistinguishable from the auto fit"


# ---------------------------------------------------------------------------
# `#197` — the run picker
# ---------------------------------------------------------------------------

_COLS = ['snapshot', 'step', 'tag', 'nominal_kV', 'frame_file',
         'active_area_px', 'active_area_mm2', 'notes']


def _frames_run(parent, name, csv_name='data.csv'):
    """A run the tuner can actually LOAD: baseline + two activated frames.

    Same shapes as the module's own --selftest, so detection finds a
    region in the late frame and the window reaches its loaded state."""
    import csv
    import cv2
    import numpy as np
    d = _os.path.join(parent, name)
    frames = _os.path.join(d, 'frames')
    _os.makedirs(frames, exist_ok=True)

    def disc(r, level):
        img = np.full((240, 320), 90.0, np.float32)
        yy, xx = np.mgrid[0:240, 0:320]
        m = (xx - 160) ** 2 + (yy - 120) ** 2 <= r * r
        img[m] += level
        return np.clip(img, 0, 255).astype(np.uint8)

    rows = []
    for k, (tag, kv, im) in enumerate([('baseline', 0.0, disc(0, 0)),
                                       ('post-ramp', 3.0, disc(45, 30)),
                                       ('post-ramp', 6.0, disc(70, 40))]):
        fn = f'SLDEA_s{k:02d}_{kv:05.2f}kV_{tag}.png'
        cv2.imwrite(_os.path.join(frames, fn), im)
        rows.append({**{c: '' for c in _COLS}, 'tag': tag, 'nominal_kV': kv,
                     'frame_file': fn, 'step': k, 'snapshot': k + 1})
    with open(_os.path.join(d, csv_name), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=_COLS)
        w.writeheader()
        w.writerows(rows)
    return d


def test_list_runs_is_names_only_and_newest_name_first():
    """Discovery goes through se.run_csv, the same test Edge Review's
    listing uses — so a custom-named run and a renamed data1.csv are runs
    here exactly as they are there, and a plain directory is not."""
    import shutil
    import tempfile
    parent = tempfile.mkdtemp(prefix='tuner_list_')
    try:
        _run_dir(parent, 'SLDEA_20260801_101010')
        _run_dir(parent, 'P3_9_2.5mL_20260802', csv_name='data2.csv')
        _os.makedirs(_os.path.join(parent, '_analysis'), exist_ok=True)
        names = st.list_runs(parent)
        assert names == ['SLDEA_20260801_101010', 'P3_9_2.5mL_20260802'], names
        # NAMES, never the labelled strings: the picker pairs index i with
        # its own label, so a run name containing the separator cannot be
        # read back as a different directory
        assert all('✓' not in n for n in names), names
        assert st.list_runs(_os.path.join(parent, 'nope')) == []
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_run_label_flags_a_run_that_already_carries_tuned_settings():
    """The tuner's Save OVERWRITES a run's tuned block, so what its picker
    flags is 'already tuned' — not Edge Review's 'processed'."""
    import shutil
    import tempfile
    import sldea_edge as se
    parent = tempfile.mkdtemp(prefix='tuner_label_')
    try:
        d = _run_dir(parent, 'SLDEA_20260801_101010')
        assert st.run_label(d) == ''
        se.save_settings(d, dict(se.DEFAULT_SETTINGS))
        assert st.run_label(d).strip() == '✓ tuned', st.run_label(d)
        assert st.run_label(_os.path.join(parent, 'nope')) == ''
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_runs_parent_descends_into_an_upload_wrapper():
    """The campaign layout: SCPI_SLDEA_DIR points at 'Upload 20260804' and
    the runs live in 'SLDEA_data (1)' inside it, where se.newest_run
    correctly finds nothing — which is why the no-argument tuner reported
    'no run found' on a machine holding 13 runs."""
    import shutil
    import tempfile
    root = tempfile.mkdtemp(prefix='tuner_wrap_')
    try:
        inner = _os.path.join(root, 'SLDEA_data (1)')
        _os.makedirs(inner)
        _run_dir(inner, 'P3_1_2.5mL_20260728', csv_name='data1.csv')
        _run_dir(inner, 'P3_2_2.5mL_20260728')
        _os.makedirs(_os.path.join(root, '_analysis'), exist_ok=True)
        assert st.runs_parent(root) == inner
        # a root that holds runs itself is never rewritten
        assert st.runs_parent(inner) == inner
        # exactly one level: a run two levels down does not move the parent
        deep = tempfile.mkdtemp(prefix='tuner_deep_')
        _run_dir(_os.path.join(deep, 'a', 'b'), 'R1')
        assert st.runs_parent(deep) == deep
        shutil.rmtree(deep, ignore_errors=True)
        # nothing anywhere: the caller's own path back, not None
        barren = tempfile.mkdtemp(prefix='tuner_barren_')
        assert st.runs_parent(barren) == barren
        shutil.rmtree(barren, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_pick_index_never_substitutes_another_run():
    """Edge Review's audit-2026-07-25 ruling, which the tuner needs more:
    a missing target is a message asking for a pick, never a silent 0."""
    names = ['B', 'A']
    assert st.pick_index(names, 'A') == 1
    assert st.pick_index(names, 'C') is None
    assert st.pick_index([], 'A') is None


def test_dirty_keys_is_exactly_what_save_would_change():
    import sldea_edge as se
    a = dict(se.DEFAULT_SETTINGS)
    assert st.dirty_keys(a, dict(a)) == []
    b = dict(a, blur_px=9)
    assert st.dirty_keys(a, b) == ['blur_px']
    # compared through save_settings' own '%g', so a nudge too small to
    # reach the file is not reported as unsaved work
    assert st.dirty_keys(a, dict(a, min_solidity=a['min_solidity'] + 1e-12)) \
        == []
    assert st.dirty_keys(a, dict(a, norm_bg=0)) == ['norm_bg']
    # an empty side (nothing loaded) never claims a difference it cannot
    # describe -- _confirm_discard leans on this
    assert st.dirty_keys({}, {}) == []


def _tk_or_skip(what):
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped {what}: no display for Tk: {e})")
        return None
    root.withdraw()
    return root


class _StubMB:
    """messagebox stub: records what was shown, answers askyesno with
    `yes`. The discard prompt is a decision, so the tests take both."""

    def __init__(self, yes=True):
        self.infos, self.asked = [], []
        self.yes = yes

    def showinfo(self, *a, **k):
        self.infos.append(a)

    def showwarning(self, *a, **k):
        pass

    def showerror(self, *a, **k):
        pass

    def askyesno(self, *a, **k):
        self.asked.append(a)
        return self.yes


def _close(root, win=None):
    if win is not None:
        win._cancel_job()
        try:
            win.plt.close(win.fig)
        except Exception:
            pass
    root.update_idletasks()
    root.destroy()


def _age(older, newer):
    """Make `newer` unambiguously the newest run by mtime.

    Pushing the other one BACK, not this one forward: writing anything
    into a run re-dates its directory, and two writes inside one clock
    tick tie — which se.newest_run breaks by directory order, so the
    fixture would silently test the opposite of what it says."""
    t = _os.path.getmtime(newer)
    _os.utime(older, (t - 60, t - 60))


def _two_runs():
    """(parent, older, newer) — two loadable runs, `newer` the newest."""
    import tempfile
    parent = tempfile.mkdtemp(prefix='tuner_pick_')
    old = _frames_run(parent, 'AAA_run_20260801')
    new = _frames_run(parent, 'ZZZ_run_20260802', csv_name='data1.csv')
    _age(old, new)
    return parent, old, new


def test_picker_lists_the_runs_and_names_the_loaded_one():
    """`#197`: with no argument the tuner still opens the newest run — but
    now it lists the others and says, in the title bar AND the identity
    bar, which one Save would rewrite."""
    import shutil
    root = _tk_or_skip('picker listing')
    if root is None:
        return
    parent, old, new = _two_runs()
    try:
        win = st.TunerWindow(root, parent=parent, messagebox=_StubMB())
        assert list(win.run_names) == ['ZZZ_run_20260802', 'AAA_run_20260801']
        assert win.rundir == new, win.rundir      # newest by mtime, as before
        assert _os.path.basename(new) in root.title()
        assert _os.path.basename(new) in win.banner_run.cget('text')
        # the identity bar names the FILE Save rewrites, not just the run
        assert win.banner_path.cget('text').endswith(
            _os.path.join(new, 'setup.txt'))
        assert str(win.save_btn.cget('state')) == 'normal'
        _close(root, win)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_switching_runs_loads_that_runs_own_settings():
    """Tuned values NEVER travel between runs: the new run's setup.txt is
    what lands on the sliders, and the title/banner follow the switch."""
    import shutil
    import sldea_edge as se
    root = _tk_or_skip('run switching')
    if root is None:
        return
    parent, old, new = _two_runs()
    try:
        se.save_settings(old, dict(se.DEFAULT_SETTINGS, blur_px=11))
        _age(old, new)                # that write re-dated `old`
        win = st.TunerWindow(root, parent=parent, messagebox=_StubMB())
        assert win.rundir == new
        assert win.settings['blur_px'] == se.DEFAULT_SETTINGS['blur_px']
        win.run_box.current(win.run_names.index(_os.path.basename(old)))
        win._pick_run()
        assert win.rundir == old, win.rundir
        assert win.settings['blur_px'] == 11, win.settings['blur_px']
        assert int(float(win.scales['blur_px'].get())) == 11
        assert _os.path.basename(old) in root.title()
        assert _os.path.basename(old) in win.banner_run.cget('text')
        # and it is not 'dirty' merely for having loaded a tuned run
        assert st.dirty_keys(win.loaded, win.settings) == []
        _close(root, win)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_switch_with_unsaved_tuning_asks_and_a_no_keeps_the_run():
    """The tuner had no dirty state at all, so adding a picker adds a way
    to bin a tuning session with one mis-click. A declined discard keeps
    the run AND puts the box back on it — a box disagreeing with the
    banner is the confusion `#197` is about."""
    import shutil
    root = _tk_or_skip('discard prompt')
    if root is None:
        return
    parent, old, new = _two_runs()
    try:
        mb = _StubMB(yes=False)
        win = st.TunerWindow(root, parent=parent, messagebox=mb)
        win.set_slider('blur_px', 9)
        assert st.dirty_keys(win.loaded, win.settings) == ['blur_px']
        win.run_box.current(win.run_names.index(_os.path.basename(old)))
        win._pick_run()
        assert mb.asked, "an unsaved switch must ask"
        assert win.rundir == new, "a declined discard must keep the run"
        assert win.run_box.get().split('  ')[0] == _os.path.basename(new)
        assert win.settings['blur_px'] == 9, "the tuning is still there"
        # ... and a yes goes through, dropping the unsaved value
        mb.yes = True
        win.run_box.current(win.run_names.index(_os.path.basename(old)))
        win._pick_run()
        assert win.rundir == old
        assert win.settings['blur_px'] != 9
        # re-picking the loaded run is a no-op, not a discard prompt
        n_asked = len(mb.asked)
        win.set_slider('blur_px', 7)
        win.run_box.current(win.run_names.index(_os.path.basename(old)))
        win._pick_run()
        assert len(mb.asked) == n_asked and win.settings['blur_px'] == 7
        _close(root, win)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_save_writes_only_the_loaded_runs_setup():
    """THE `#197` regression. Tune, switch, tune, Save: the values land in
    the run the banner names and the other run's setup.txt is untouched."""
    import shutil
    import sldea_edge as se
    root = _tk_or_skip('save targeting')
    if root is None:
        return
    parent, old, new = _two_runs()
    try:
        win = st.TunerWindow(root, parent=parent, messagebox=_StubMB())
        win.set_slider('diff_thresh', 21)          # tuning the newest run
        win.run_box.current(win.run_names.index(_os.path.basename(old)))
        win._pick_run()                            # ... then switching away
        assert win.rundir == old
        win.set_slider('diff_thresh', 33)
        win.do_save()
        assert se.load_settings(old)['diff_thresh'] == 33
        assert se.load_settings(new)['diff_thresh'] == \
            se.DEFAULT_SETTINGS['diff_thresh'], "wrote the wrong run"
        assert not _os.path.exists(_os.path.join(new, 'setup.txt'))
        # saved == no longer unsaved, and the row now says so
        assert st.dirty_keys(win.loaded, win.settings) == []
        assert '✓ tuned' in win.run_box['values'][
            win.run_names.index(_os.path.basename(old))]
        _close(root, win)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_a_cli_target_is_loaded_and_a_missing_one_refuses():
    """Scriptability: gui.py's Tune button and the Windows launcher pass a
    resolved path and must get THAT run with no picking — even when it is
    not the newest. A target that is not in the parent loads nothing at
    all rather than the newest (audit 2026-07-25's ruling, and here it
    would rewrite the setup.txt of a run nobody named)."""
    import shutil
    root = _tk_or_skip('cli target')
    if root is None:
        return
    parent, old, new = _two_runs()
    try:
        win = st.TunerWindow(root, target=old, messagebox=_StubMB())
        assert win.rundir == old, win.rundir       # NOT the newest
        assert win.parent == _os.path.abspath(parent)
        assert len(win.run_names) == 2, "the neighbours are still listed"
        win._populate(parent, preselect='not_a_run_20260101')
        assert win.rundir is None, "loaded a run that was not asked for"
        assert 'not_a_run_20260101' in win.status.cget('text')
        assert str(win.save_btn.cget('state')) == 'disabled'
        _close(root, win)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_an_unloadable_run_unloads_rather_than_keeping_the_old_one():
    """Fail CLOSED on a bad switch: Save must never stay pointed at run A
    while the operator believes they moved to run B."""
    import shutil
    root = _tk_or_skip('failed switch')
    if root is None:
        return
    parent, old, new = _two_runs()
    try:
        win = st.TunerWindow(root, target=new, messagebox=_StubMB())
        assert win.rundir == new
        # truncate the older run's baseline: unreadable, so untunable
        base = _os.path.join(old, 'frames', 'SLDEA_s00_00.00kV_baseline.png')
        open(base, 'wb').close()
        win.run_box.current(win.run_names.index(_os.path.basename(old)))
        win._pick_run()
        assert win.rundir is None, "a failed load must not keep run A live"
        assert str(win.save_btn.cget('state')) == 'disabled'
        assert 'baseline' in win.status.cget('text')
        _close(root, win)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_an_empty_parent_opens_the_picker_with_nothing_loaded():
    """A machine whose SCPI_SLDEA_DIR holds no runs used to get 'no run
    found' and exit code 2 — no window, nothing to click. Now the window
    opens with the picker live and Save closed until something loads."""
    import shutil
    import tempfile
    root = _tk_or_skip('empty parent')
    if root is None:
        return
    empty = tempfile.mkdtemp(prefix='tuner_empty_')
    try:
        win = st.TunerWindow(root, parent=empty, messagebox=_StubMB())
        assert win.rundir is None
        assert win.run_names == []
        assert str(win.save_btn.cget('state')) == 'disabled'
        assert str(win.reset_btn.cget('state')) == 'disabled'
        assert str(win.browse_btn.cget('state')) == 'normal'
        assert 'no run loaded' in win.banner_run.cget('text')
        assert 'no run loaded' in root.title()
        # and the actions are inert rather than raising on a runless window
        win.do_save()
        win.do_reset()
        assert win.rundir is None
        _close(root, win)
    finally:
        shutil.rmtree(empty, ignore_errors=True)


def _run():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
