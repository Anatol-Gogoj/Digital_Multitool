#!/usr/bin/env python3
"""Tests for the colour-emoji crash guard (no display needed).

Run: .venv/bin/python tests/test_tk_fontfix.py

Two of these ask fontconfig's `fc-list` about deploy/fonts.conf, so they run
only where the app hands that file to fontconfig (POSIX) and `fc-list` is on
PATH. Everywhere else they are SKIPPED -- on every Windows box, including one
where MiKTeX has put its own fc-list.exe on PATH. The skips are counted and
their reason named in the tail line rather than being reported as passes --
`run_tests.py` echoes a suite's last stdout line verbatim, so a silent skip
would read in the runner summary exactly like coverage that ran.
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import glob
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import tk_fontfix

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(REPO, 'deploy', 'fonts.conf')

# The Tk entry points as of 2026-08-09. The real list is DERIVED below; this
# is a floor, so that a detection change cannot quietly shrink the set.
KNOWN_TK_ENTRY_POINTS = ('gui.py', 'sldea_edge_gui.py', 'sldea_plot_gui.py',
                         'sldea_tuner.py')


class _Skip(Exception):
    """Raised by a test that cannot run in this environment.

    `reason` is short and is what the tail line names; `detail`, when given,
    is printed only on the test's own skip line.
    """

    def __init__(self, reason, detail=None):
        super().__init__(f'{reason} -- {detail}' if detail else reason)
        self.reason = reason


def _need(binary):
    """Skip the calling test when `binary` is not on PATH."""
    if shutil.which(binary) is None:
        raise _Skip(f'{binary} not on PATH')


def _need_tk_fontconfig():
    """Skip unless the app hands deploy/fonts.conf to a fontconfig here.

    `tk_fontfix.apply()` points FONTCONFIG_FILE at the file on POSIX and is a
    no-op everywhere else; the platform check below is the one it makes, and
    test_apply_sets_env_and_respects_an_existing_value pins that. On Windows
    Tk draws through GDI and never reads fontconfig at all.

    `fc-list` on PATH is not the same question. MiKTeX installs its own
    fc-list.exe on PATH, so on the Windows 11 PC (2026-09-23) the old
    `_need('fc-list')` gate let both cases run. They died decoding its
    output (see `_fc_list`) -- and decoded, they PASS on a file nothing read:
    MiKTeX builds fontconfig with its getenv("FONTCONFIG_FILE") compiled out,
    and its fc-list prints byte-identical output for this file, a non-XML
    one, or none at all.
    """
    if os.name != 'posix':
        found = shutil.which('fc-list')
        raise _Skip(f'Tk on {sys.platform} does not use fontconfig',
                    'tk_fontfix.apply() is a no-op off POSIX, so nothing '
                    'here hands deploy/fonts.conf to fontconfig'
                    + (f'; ignoring {found}' if found else ''))
    _need('fc-list')


def _fc_list(env):
    """Run `fc-list` under `env`; stdout and stderr always come back as str.

    Decoded as UTF-8, fontconfig's own encoding, with undecodable bytes
    replaced: a replaced byte cannot hide or forge the ASCII these cases
    look for, so decoding can neither fail a case nor pass one. With
    `text=True` it could do both. On Linux one font whose FILE NAME is not
    UTF-8 raised UnicodeDecodeError out of run(), failing both cases over a
    font they never asked about (reproduced under WSL, 2026-09-23). On
    Windows subprocess decodes in a reader thread: MiKTeX's UTF-8 hit
    cp1252's unmapped byte 0x8d, the thread died and the stream came back
    None -- the cases died on `None.splitlines()`, and `r.stderr or ''`
    would have read an undecoded stderr as one free of "Fontconfig error".
    """
    r = subprocess.run(['fc-list'], env=env, capture_output=True,
                       encoding='utf-8', errors='replace')
    assert r.returncode == 0, f'fc-list exited {r.returncode}: {r.stderr}'
    return r


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
    # be reproduced where Tk reads fontconfig.
    _need_tk_fontconfig()
    r = _fc_list({**os.environ, 'FONTCONFIG_FILE': CONF})
    assert 'Fontconfig error' not in r.stderr, r.stderr
    assert r.stdout.strip(), "no fonts at all -- the system include broke"


def test_colour_emoji_is_rejected_but_fonts_remain():
    # Linux-verified only, same reason as above.
    _need_tk_fontconfig()

    def n_colour(env):
        r = _fc_list(env)
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
    reasons = []                        # each distinct skip reason, in order
    failed = []
    for fn in fns:
        try:
            fn()
        except _Skip as why:
            skipped += 1
            if why.reason not in reasons:
                reasons.append(why.reason)
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
        # Named by the skips themselves, not a fixed label: "needs
        # fontconfig" was false on a box that has one (MiKTeX's).
        tail += f" ({skipped} skipped, {'; '.join(reasons)})"
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
