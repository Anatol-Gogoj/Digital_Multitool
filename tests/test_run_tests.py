#!/usr/bin/env python3
"""Headless tests for run_tests.py's zero-case check (#426).

run_tests.py passes a suite that exits 0 only when the suite's stdout
has a count line naming at least one case. test_trek_polarity.py once had
no runner and was listed `ok` having run nothing. These tests pin which
count lines are read (run_tests.py's docstring lists them), which are
not, and that a count printed only to stderr is not read at all.

Run: .venv/bin/python tests/test_run_tests.py
"""
# Runnable from anywhere: put the repo root (one level up) on sys.path
# so the app modules import when this file is executed directly.
import os as _os
import shutil as _shutil
import subprocess as _subprocess
import sys as _sys
import tempfile as _tempfile
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _ROOT)

import run_tests  # noqa: E402

_cases = run_tests._cases_reported


def test_n_tests_passed():
    assert _cases('ok  test_a\n\n5 tests passed\n') == 5
    assert _cases('5 tests passed') == 5


def test_one_test_passed():
    assert _cases('ok  test_a\n\n1 test passed\n') == 1


def test_all_n_label_tests_passed():
    for line, n in (('All 16 arb_build tests passed.', 16),
                    ('All 5 run-folder tests passed.', 5),
                    ('All 5 run folder tests passed.', 5),
                    ('All 1 waveform-render test passed.', 1),
                    ('All 7 tests passed.', 7)):
        assert _cases(f'PASS test_a\n\n{line}\n') == n, line


def test_n_tests_passed_with_a_note():
    for line in ('5 tests passed (1 skipped)',
                 '5 tests passed (1 skipped).'):
        assert _cases(f'ok  test_a\n\n{line}\n') == 5, line


def test_n_of_m_tests_ran():
    # the count read is M, the cases the suite has: a suite whose every
    # case skipped still passes, because it named what it skipped
    for line, m in (('3 of 3 tests ran', 3),
                    ('2 of 3 tests ran (1 skipped)', 3),
                    ('0 of 4 tests ran (4 skipped, needs Xvfb+xwininfo)', 4),
                    ('1 of 1 test ran', 1)):
        assert _cases(f'ok  test_a\n\n{line}\n') == m, line


def test_the_last_count_line_is_the_one_read():
    assert _cases('3 tests passed\nok  test_b\n\n0 tests passed\n') == 0
    assert _cases('0 tests passed\nok  test_b\n\n4 tests passed\n') == 4


def test_a_count_of_zero_or_no_count_line_does_not_pass():
    for text in ('0 tests passed\n', '\n0 tests passed\n',
                 '0 of 0 tests ran\n', 'All 0 parser tests passed.\n',
                 '0 tests passed (3 skipped)\n'):
        assert not _cases(text), text
    for text in ('', '\n', 'ok  test_a\n', 'FAIL test_a\n',
                 '2 of 3 tests failed\n', 'tests passed\n'):
        assert _cases(text) is None, text


def test_a_count_only_on_stderr_is_a_fail():
    """End to end: a copy of run_tests.py in a scratch root, with one suite
    that prints its count line to stderr, one that prints it to stdout and
    one that prints nothing (the old test_trek_polarity.py)."""
    root = _tempfile.mkdtemp(prefix='run_tests_test_')
    try:
        _os.makedirs(_os.path.join(root, 'tests'))
        _shutil.copy(_os.path.join(_ROOT, 'run_tests.py'), root)
        suites = {
            'test_counts_on_stderr.py':
                "import sys\nprint('ok  test_a')\n"
                "print('1 test passed', file=sys.stderr)\n",
            'test_counts_on_stdout.py':
                "print('ok  test_a')\nprint()\nprint('1 test passed')\n",
            'test_counts_nothing.py': "pass\n",
        }
        for name, body in suites.items():
            with open(_os.path.join(root, 'tests', name), 'w',
                      encoding='ascii') as f:
                f.write(body)
        r = _subprocess.run([_sys.executable, 'run_tests.py'], cwd=root,
                            capture_output=True, text=True, timeout=120)
        lines = r.stdout.splitlines()
        assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
        assert 'FAIL test_counts_on_stderr.py' in lines, r.stdout
        assert 'FAIL test_counts_nothing.py' in lines, r.stdout
        assert any(ln.startswith('ok   test_counts_on_stdout.py')
                   and ln.endswith('1 test passed') for ln in lines), r.stdout
        assert '1/3 suites passed' in lines, r.stdout
        assert r.stdout.count(run_tests.NO_CASES) == 2, r.stdout
    finally:
        _shutil.rmtree(root, ignore_errors=True)


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block (run_tests.py explains why).
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = []
    for fn in fns:
        try:
            fn()
        except Exception:
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
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
