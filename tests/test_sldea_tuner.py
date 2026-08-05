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


def _run():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
