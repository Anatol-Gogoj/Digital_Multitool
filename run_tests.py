#!/usr/bin/env python3
"""Run every headless test suite in tests/ (no instruments needed).

Usage: .venv/bin/python run_tests.py
Exit code 0 only if every suite passes. Hardware-in-the-loop scripts
live in bench/ and are NOT run here -- see BENCH_TEST.md.

A failing suite's output is EVIDENCE and is kept twice (`#280`): replayed
after the summary, and written verbatim to test_failures/<suite>.log. The
runner-context flake in test_sldea_edge_gui.py has been seen twice with no
traceback surviving either time -- the dump used to be printed between the
per-suite lines, where 38 suites' worth of scrollback buried it. The
summary block is what people quote and grep, so nothing new is ever added
inside it; everything lands after it or in a file.

Each suite in tests/ follows that same shape internally. A suite runs
every one of its tests, recording failures instead of stopping at the
first -- fail-fast made a suite with five broken tests report one, and
"38/38 is one small fix away" was wrong by four. What a suite prints is
therefore: a line per test (`ok`/`FAIL`/`skip`), then its count line,
then -- only when something failed -- the tracebacks, in test-name order,
between a `K of M tests failed` header and an `end K of M tests failed`
footer. One grep for "tests failed" lands on both ends of a bounded
block. Skips are counted separately and are not failures: suites that
can skip print `N of M tests ran` and still exit 0.

A suite that exits 0 without a count line, or with a count of zero
cases, is a FAIL here (`#426`). Exit 0 alone proved nothing:
test_trek_polarity.py had no runner, ran none of its tests, and was
listed `ok` with "(no output)" until #426. The count lines accepted are
the ones the suites print: `N tests passed`, `All N <what> tests
passed.` and `N of M tests ran`. A suite whose every case skipped
(`0 of M tests ran`) still passes, because it named what it skipped.

Console output is forced to ASCII (backslash-escaping anything else) --
suite output can carry emoji, and a Windows console that cannot encode
them would kill the runner mid-report, losing the very traceback this
exists to keep. The .log files are UTF-8 and hold the real characters.
"""
import glob
import locale
import os
import re
import subprocess
import sys

# Per-run failure dumps. Overwritten every run, named in the summary
# footer, and .gitignore'd -- this is a test artifact, never a commit.
FAIL_DIRNAME = 'test_failures'

# The count line a suite prints after its cases (`#426`): `N tests
# passed`, `All N arb_build tests passed.`, or `N of M tests ran (...)`
# from a suite that can skip. The group is the number of cases it has.
_COUNT_PASSED = re.compile(r'^(?:All )?(\d+) (?:[\w-]+ )?tests passed\.?$')
_COUNT_RAN = re.compile(r'^\d+ of (\d+) tests ran\b')

# Why a suite that exited 0 is still a FAIL; said after the summary and
# in its dump, never inside the summary block.
NO_CASES = ("exit 0, but no test cases reported (no 'N tests passed' or "
            "'N of M tests ran' line, or a count of 0): nothing was "
            "checked (#426)")


def _cases_reported(out):
    """How many cases a suite says it has, from its LAST count line;
    None when it printed none (`#426`)."""
    for line in reversed(out.splitlines()):
        line = line.strip()
        m = _COUNT_RAN.match(line) or _COUNT_PASSED.match(line)
        if m:
            return int(m.group(1))
    return None


def _ascii(text):
    """`text` rendered so any console can print it (`#280`)."""
    return text.encode('ascii', 'backslashreplace').decode('ascii')


def _say(line=''):
    """print() that cannot raise UnicodeEncodeError."""
    sys.stdout.write(_ascii(line) + '\n')


def _decode(raw):
    """Suite bytes -> str, never raising.

    Captured as bytes rather than text=True on purpose: the child picks its
    own stdout encoding, and a strict decode here would turn a suite that
    merely printed an emoji into a crash of the runner itself.
    """
    if not raw:
        return ''
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode(locale.getpreferredencoding(False), errors='replace')


def _clear_fail_dir(fail_dir):
    """Drop the previous run's dumps so nothing stale is ever read."""
    try:
        for old in glob.glob(os.path.join(fail_dir, '*.log')):
            os.remove(old)
    except OSError:
        pass


def _write_dump(fail_dir, name, returncode, out, err):
    """Write one suite's full output; return its path, or None if it could
    not be written (a read-only checkout must not cost us the replay)."""
    path = os.path.join(fail_dir, os.path.splitext(name)[0] + '.log')
    body = (f"suite:     {name}\n"
            f"command:   {sys.executable} tests/{name}\n"
            f"exit code: {returncode}\n"
            + (f"failed:    {NO_CASES}\n" if returncode == 0 else '')
            + f"\n--- stdout ---\n{out}"
            f"\n--- stderr ---\n{err}")
    try:
        os.makedirs(fail_dir, exist_ok=True)
        with open(path, 'w', encoding='utf-8', errors='replace') as fh:
            fh.write(body)
    except OSError:
        return None
    return path


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    suites = sorted(glob.glob(os.path.join(root, 'tests', 'test_*.py')))
    fail_dir = os.path.join(root, FAIL_DIRNAME)
    _clear_fail_dir(fail_dir)
    failed = []
    for path in suites:
        name = os.path.basename(path)
        result = subprocess.run([sys.executable, path], cwd=root,
                                capture_output=True)
        out = _decode(result.stdout)
        err = _decode(result.stderr)
        lines = out.strip().splitlines()
        tail = lines[-1] if lines else '(no output)'
        # exit 0 is a pass only with at least one case reported (`#426`)
        if result.returncode == 0 and _cases_reported(out):
            _say(f"ok   {name:28s} {tail}")
        else:
            # The dump goes AFTER the summary, never between these lines.
            _say(f"FAIL {name}")
            failed.append((name, result.returncode, out, err))
    _say(f"\n{len(suites) - len(failed)}/{len(suites)} suites passed")

    # ---- everything below is the #280 evidence trail, outside the summary
    if failed:
        dumps = [(name, rc, out, err,
                  _write_dump(fail_dir, name, rc, out, err))
                 for name, rc, out, err in failed]
        _say()
        _say(f"failure output for {len(dumps)} suite(s) -- "
             f"full text in {FAIL_DIRNAME}{os.sep} (UTF-8, rewritten each run):")
        for name, _rc, _out, _err, dump in dumps:
            where = os.path.relpath(dump, root) if dump else '(could not write)'
            _say(f"  {name:28s} {where}")
        for name, rc, out, err, _dump in dumps:
            _say()
            _say(f"===== FAIL {name} (exit {rc}) =====")
            if rc == 0:
                _say(NO_CASES)
            _say("--- stdout ---")
            _say(out.rstrip('\n') if out.strip() else '(empty)')
            _say("--- stderr ---")
            _say(err.rstrip('\n') if err.strip() else '(empty)')
            _say(f"===== end {name} =====")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
