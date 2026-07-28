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


def _run():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
