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

Console output is forced to ASCII (backslash-escaping anything else) --
suite output can carry emoji, and a Windows console that cannot encode
them would kill the runner mid-report, losing the very traceback this
exists to keep. The .log files are UTF-8 and hold the real characters.
"""
import glob
import locale
import os
import subprocess
import sys

# Per-run failure dumps. Overwritten every run, named in the summary
# footer, and .gitignore'd -- this is a test artifact, never a commit.
FAIL_DIRNAME = 'test_failures'


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
            f"\n--- stdout ---\n{out}"
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
        if result.returncode == 0:
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
            _say("--- stdout ---")
            _say(out.rstrip('\n') if out.strip() else '(empty)')
            _say("--- stderr ---")
            _say(err.rstrip('\n') if err.strip() else '(empty)')
            _say(f"===== end {name} =====")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
