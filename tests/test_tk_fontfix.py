#!/usr/bin/env python3
"""Tests for the colour-emoji crash guard (no display needed).

Run: .venv/bin/python tests/test_tk_fontfix.py

Two of these need fontconfig's `fc-list` and are SKIPPED where it does not
exist, which is every Windows box. The skips are counted and named in the
tail line rather than being reported as passes -- `run_tests.py` echoes a
suite's last stdout line verbatim, so a silent skip would read in the
runner summary exactly like coverage that ran.
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import glob
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

import tk_fontfix

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(REPO, 'deploy', 'fonts.conf')

# The Tk entry points as of 2026-08-09. The real list is DERIVED below; this
# is a floor, so that a detection change cannot quietly shrink the set.
KNOWN_TK_ENTRY_POINTS = ('gui.py', 'sldea_edge_gui.py', 'sldea_plot_gui.py',
                         'sldea_tuner.py')


class _Skip(Exception):
    """Raised by a test that cannot run in this environment."""


def _need(binary):
    """Skip the calling test when `binary` is not on PATH."""
    if shutil.which(binary) is None:
        raise _Skip(f'{binary} not on PATH')


def _tk_entry_points():
    """Every module that opens a Tk root -- found, not listed.

    Listed, this drifted: `sldea_plot_gui.py` opens a root and was absent
    from the hard-coded tuple for its whole life (found 2026-08-09), which
    is why the ordering bug in it went unnoticed. `arb_editor.py` imports
    tkinter but never calls `tk.Tk()`, so it is correctly not here.
    """
    found = []
    for path in sorted(glob.glob(os.path.join(REPO, '*.py'))):
        with open(path, encoding='utf-8') as fh:
            if 'tk.Tk()' in fh.read():
                found.append(os.path.basename(path))
    return found


def test_config_exists_and_is_valid_xml():
    # An invalid comment (a stray double hyphen) made fontconfig refuse the
    # whole file and the crash came straight back — silently (2026-07-27).
    assert os.path.exists(CONF), CONF
    ET.parse(CONF)                     # raises on malformed XML


def test_fontconfig_actually_accepts_the_file():
    # Parsing as XML is not enough: fontconfig must load it without error.
    # Linux-verified only -- the 2026-07-27 regression this pins can only
    # be reproduced where fontconfig exists.
    _need('fc-list')
    r = subprocess.run(['fc-list'], env={**os.environ,
                                         'FONTCONFIG_FILE': CONF},
                       capture_output=True, text=True)
    assert 'Fontconfig error' not in (r.stderr or ''), r.stderr
    assert r.stdout.strip(), "no fonts at all -- the system include broke"


def test_colour_emoji_is_rejected_but_fonts_remain():
    # Linux-verified only, same reason as above.
    _need('fc-list')

    def n_colour(env):
        r = subprocess.run(['fc-list'], env=env, capture_output=True,
                           text=True)
        return (sum('color emoji' in l.lower()
                    for l in r.stdout.splitlines()),
                len(r.stdout.splitlines()))
    with_fix, total_fix = n_colour({**os.environ, 'FONTCONFIG_FILE': CONF})
    assert with_fix == 0, "colour emoji font still visible -> Tk will crash"
    assert total_fix > 10, "the reject nuked the whole font set"


def test_apply_sets_env_and_respects_an_existing_value():
    """Both halves of `apply()`'s documented contract.

    The already-configured guard (`tk_fontfix.py:35-36`) runs everywhere and
    is tested everywhere. The POSIX-only no-op (`:37-38`) is the whole
    behaviour on Windows and had NO test at all before 2026-08-09 -- this
    suite simply asserted the POSIX return value and failed on Windows,
    which is one of the four failures that made it a documented
    "environmental" red.
    """
    saved = os.environ.pop('FONTCONFIG_FILE', None)
    try:
        used = tk_fontfix.apply()
        if os.name == 'posix':
            assert used == CONF, used
            assert os.environ['FONTCONFIG_FILE'] == CONF
        else:
            assert used is None, f'non-POSIX must be a no-op, got {used!r}'
            assert 'FONTCONFIG_FILE' not in os.environ, \
                'non-POSIX must not touch the environment'

        # a user/admin who already configured fontconfig wins, everywhere
        os.environ['FONTCONFIG_FILE'] = '/somewhere/else.conf'
        assert tk_fontfix.apply() is None
        assert os.environ['FONTCONFIG_FILE'] == '/somewhere/else.conf'
    finally:
        os.environ.pop('FONTCONFIG_FILE', None)
        if saved:
            os.environ['FONTCONFIG_FILE'] = saved


def test_every_tk_entry_point_applies_the_fix_before_tkinter():
    names = _tk_entry_points()
    missing = set(KNOWN_TK_ENTRY_POINTS) - set(names)
    assert not missing, f"known Tk entry points no longer detected: {missing}"
    for name in names:
        # encoding is explicit: the default is cp1252 on Windows and gui.py
        # carries non-ASCII, so this read used to raise UnicodeDecodeError
        # rather than test anything.
        with open(os.path.join(REPO, name), encoding='utf-8') as fh:
            src = fh.read()
        assert 'tk_fontfix.apply()' in src, f"{name} unprotected"
        fix_at = src.index('tk_fontfix.apply()')
        tk_at = src.index('import tkinter')
        assert fix_at < tk_at, f"{name}: fix must precede tkinter import"


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    ran = skipped = 0
    failed = []
    for fn in fns:
        try:
            fn()
        except _Skip as why:
            skipped += 1
            print(f"skip {fn.__name__}  ({why})")
            continue
        except Exception:
            # A test that blew up still RAN -- only a skip is "did not run".
            ran += 1
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
        ran += 1
        print(f"ok  {fn.__name__}")
    tail = f"{ran} of {len(fns)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped, needs fontconfig)"
    print(f"\n{tail}")
    if not failed:
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
