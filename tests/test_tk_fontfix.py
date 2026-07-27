#!/usr/bin/env python3
"""Tests for the colour-emoji crash guard (no display needed).

Run: .venv/bin/python tests/test_tk_fontfix.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import os
import subprocess
import xml.etree.ElementTree as ET

import tk_fontfix

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(REPO, 'deploy', 'fonts.conf')


def test_config_exists_and_is_valid_xml():
    # An invalid comment (a stray double hyphen) made fontconfig refuse the
    # whole file and the crash came straight back — silently (2026-07-27).
    assert os.path.exists(CONF), CONF
    ET.parse(CONF)                     # raises on malformed XML


def test_fontconfig_actually_accepts_the_file():
    # Parsing as XML is not enough: fontconfig must load it without error.
    r = subprocess.run(['fc-list'], env={**os.environ,
                                         'FONTCONFIG_FILE': CONF},
                       capture_output=True, text=True)
    assert 'Fontconfig error' not in (r.stderr or ''), r.stderr
    assert r.stdout.strip(), "no fonts at all -- the system include broke"


def test_colour_emoji_is_rejected_but_fonts_remain():
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
    saved = os.environ.pop('FONTCONFIG_FILE', None)
    try:
        used = tk_fontfix.apply()
        assert used == CONF, used
        assert os.environ['FONTCONFIG_FILE'] == CONF
        # a user/admin who already configured fontconfig wins
        os.environ['FONTCONFIG_FILE'] = '/somewhere/else.conf'
        assert tk_fontfix.apply() is None
        assert os.environ['FONTCONFIG_FILE'] == '/somewhere/else.conf'
    finally:
        os.environ.pop('FONTCONFIG_FILE', None)
        if saved:
            os.environ['FONTCONFIG_FILE'] = saved


def test_every_tk_entry_point_applies_the_fix_before_tkinter():
    for name in ('gui.py', 'sldea_edge_gui.py', 'sldea_tuner.py'):
        src = open(os.path.join(REPO, name)).read()
        assert 'tk_fontfix.apply()' in src, f"{name} unprotected"
        fix_at = src.index('tk_fontfix.apply()')
        tk_at = src.index('import tkinter')
        assert fix_at < tk_at, f"{name}: fix must precede tkinter import"


def _run():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
