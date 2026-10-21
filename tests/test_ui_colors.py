#!/usr/bin/env python3
"""The app's words, and the fills they sit on, are Tol colors that read (#462).

#450 and #454 moved the drawn lines to Paul Tol's colors; this is the text.
What these pin down (2026-10-19):

  * every color in ui_colors is from one of Tol's qualitative schemes, as
    his page lists them today (section dated 16 August 2026);
  * words reach WCAG 2.1 SC 1.4.3's 4.5:1 against what they sit on: the
    Linux bench's #d9d9d9 (Tk's NORMAL_BG), Windows' #f0f0f0 and white;
    white words on every fill and banner; black words on every pale
    background; light words on the dark image viewers;
  * the state colors that appear together (plain, muted, OK, alert) stay
    apart under simulated color blindness: worst-case CIEDE2000 >= 18 over
    normal and Machado-2009 deutan, protan and tritan vision, with the
    simulator and floor of tests/test_sldea_preview.py. So do the DRY and
    LIVE run buttons, with and without the pointer over them, and the
    DRY and LIVE rows: they never show together, but they are the HV
    indicator. The colors each one replaced must FAIL the same bars, so
    the checks are ones that can fail;
  * on a button, red means energized: the LIVE run button and an SG or
    PSU Output: ON share it, and the DRY button is blue;
  * ui_colors' docstring says no other Tol set does the job; that is
    measured here, not taken on trust;
  * no module #462 moved still writes a word in a color outside Tol's
    (a source scan: widget color keywords, canvas and plot text, module
    and class constants, and either branch of a keyword's conditional);
  * on the built app, every widget that sets its own text color reaches
    the bar on its own background, and on the bench's #d9d9d9 where it
    sits on the platform default, with the pointer over it too (the run
    button once turned its words black under the pointer); and the
    DRY/LIVE row says its state in words as well as in color.

The cases that build the app are skipped, and counted as skipped, when
there is no display.

Run: .venv/bin/python tests/test_ui_colors.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import ast
import itertools
import os
import re

import test_sldea_preview as cvd
import ui_colors as uc

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Skip(Exception):
    """The test could not run here (no display) -- reported, not passed."""


# Paul Tol, "Colour schemes", https://sronpersonalpages.nl/~pault/, section
# "Qualitative colour schemes" dated 16 August 2026, Figs. 1 to 8 (read
# 2026-10-19). The high-contrast and medium-contrast schemes are drawn
# between white and black; the repo has always counted those two as Tol
# (tests/test_sldea_preview.TOL_HIGH_CONTRAST, from TN/09-002 issue 3.2).
TOL_SCHEMES = {
    'bright': ['#4477AA', '#EE6677', '#228833', '#CCBB44', '#66CCEE',
               '#AA3377', '#BBBBBB'],
    'high-contrast': ['#004488', '#DDAA33', '#BB5566', '#FFFFFF',
                      '#000000'],
    'vibrant': ['#EE7733', '#0077BB', '#33BBEE', '#EE3377', '#CC3311',
                '#009988', '#BBBBBB'],
    'muted': ['#CC6677', '#332288', '#DDCC77', '#117733', '#88CCEE',
              '#882255', '#44AA99', '#999933', '#AA4499', '#DDDDDD'],
    'medium-contrast': ['#6699CC', '#004488', '#EECC66', '#994455',
                        '#997700', '#EE99AA', '#FFFFFF', '#000000'],
    'dark': ['#4477BB', '#CC4466', '#228833', '#2255AA', '#993366',
             '#006644', '#117788', '#882288', '#BB4488', '#775500',
             '#444444'],
    'pale': ['#AACCEE', '#CCEEFF', '#BBDDBB', '#EEEEBB', '#FFBBCC',
             '#EEBBDD', '#DDDDDD'],
    'light': ['#77AADD', '#EE8866', '#EEDD88', '#FFAABB', '#99DDFF',
              '#44BB99', '#BBCC33', '#AAAA00', '#DDDDDD'],
}
TOL = {c for cs in TOL_SCHEMES.values() for c in cs}

BENCH_BG = '#D9D9D9'      # Tk's NORMAL_BG on X11, and ttk's default -frame
WINDOWS_BG = '#F0F0F0'    # SystemButtonFace
LIGHT_BGS = (BENCH_BG, WINDOWS_BG, '#FFFFFF')
TEXT_MIN, LARGE_TEXT_MIN = 4.5, 3.0      # WCAG 2.1 SC 1.4.3

WORDS = {'TEXT': uc.TEXT, 'TEXT_MUTED': uc.TEXT_MUTED,
         'TEXT_OK': uc.TEXT_OK, 'TEXT_ALERT': uc.TEXT_ALERT}
WHITE_ON = ('FILL_DRY', 'FILL_DRY_ACTIVE', 'FILL_LIVE', 'FILL_LIVE_ACTIVE',
            'BANNER_ALERT', 'BANNER_ERROR', 'BANNER_INFO', 'BANNER_EMPTY')
BLACK_ON = ('ROW_DRY', 'ROW_LIVE', 'TOOLTIP_BG', 'PALE_CODE')


def _lum(hex_color):
    h = hex_color.lstrip('#')
    r, g, b = (cvd._lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(hex1, hex2):
    """WCAG contrast ratio between two sRGB colors."""
    hi, lo = sorted((_lum(hex1), _lum(hex2)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _worst(palette):
    """(worst-case CIEDE2000, a, b) over every pair in `palette`."""
    return min((cvd._worst_de(a, b), a, b)
               for a, b in itertools.combinations(palette, 2))


def _palette():
    """Every color ui_colors defines, by name."""
    return {k: v for k, v in vars(uc).items()
            if k.isupper() and isinstance(v, str)}


# ---------------------------------------------------------------- headless

def test_every_color_is_from_a_tol_scheme():
    pal = _palette()
    assert len(pal) >= 20, f"ui_colors lost its colors: {sorted(pal)}"
    stray = {k: v for k, v in pal.items() if v.upper() not in TOL}
    assert not stray, f"outside Paul Tol's schemes: {stray}"


def test_words_reach_4_5_on_every_light_background():
    """The bench's #d9d9d9 is the darkest of the three, so it is the bar;
    a color that passes there passes on Windows and on white."""
    for name, c in WORDS.items():
        for bg in LIGHT_BGS:
            r = _contrast(c, bg)
            assert r >= TEXT_MIN, f"{name} {c} on {bg}: {r:.2f}:1"
        assert min(_contrast(c, bg) for bg in LIGHT_BGS) == \
            _contrast(c, BENCH_BG), name
    assert uc.TEXT_ACCENT == uc.TEXT_OK


def test_white_words_reach_4_5_on_every_fill_and_banner():
    for name in WHITE_ON:
        r = _contrast(uc.TEXT_ON_FILL, getattr(uc, name))
        assert r >= TEXT_MIN, f"white on {name}: {r:.2f}:1"
    # the splash's subtitle and version, the tuner's path line: 8-10 pt
    for name in ('BANNER_INFO', 'BANNER_EMPTY'):
        r = _contrast(uc.TEXT_ON_FILL_MUTED, getattr(uc, name))
        assert r >= TEXT_MIN, f"muted words on {name}: {r:.2f}:1"


def test_black_words_reach_4_5_on_every_pale_background():
    for name in BLACK_ON:
        r = _contrast(uc.TEXT, getattr(uc, name))
        assert r >= TEXT_MIN, f"black on {name}: {r:.2f}:1"


def test_words_on_the_dark_image_viewers_read():
    # Edge Review's empty canvas (#222) carries the hint, the Webcam
    # tab's black view its "(preview off)" (gray on black there was
    # 2.8:1), and the video review's #111 its white "no frame" line
    assert _contrast(uc.TEXT_ON_DARK, '#222222') >= TEXT_MIN
    assert _contrast(uc.TEXT_ON_DARK, '#000000') >= TEXT_MIN
    assert _contrast('#555555', '#000000') < TEXT_MIN
    assert _contrast('#FFFFFF', '#111111') >= TEXT_MIN


def test_state_colors_that_show_together_survive_color_blindness():
    """The SLDEA tab shows all four at once: a muted job line, an OK
    status, an alert camera line, plain labels."""
    worst, a, b = _worst(WORDS.values())
    assert worst >= cvd.CVD_FLOOR, (
        f"worst-case CIEDE2000 {worst:.2f} ({a} vs {b}) < {cvd.CVD_FLOOR}")


def test_dry_and_live_survive_color_blindness():
    """They never show together, but they are the HV indicator, so they
    clear the same bar: each DRY button color (with the pointer off and
    on it) against each LIVE one, and the two rows. Brown for DRY would
    not (17.74 against the red), nor maroon for LIVE under the pointer
    (10.05), nor Tol's pale red for the LIVE row (10.55)."""
    for dry in (uc.FILL_DRY, uc.FILL_DRY_ACTIVE):
        for live in (uc.FILL_LIVE, uc.FILL_LIVE_ACTIVE):
            worst = cvd._worst_de(dry, live)
            assert worst >= cvd.CVD_FLOOR, (dry, live, worst)
    assert cvd._worst_de(uc.ROW_DRY, uc.ROW_LIVE) >= cvd.CVD_FLOOR
    assert cvd._worst_de(uc.TEXT_ALERT, uc.FILL_LIVE) < cvd.CVD_FLOOR
    assert cvd._worst_de(uc.FILL_DRY_ACTIVE, '#993366') < cvd.CVD_FLOOR
    assert cvd._worst_de(uc.ROW_DRY, '#FFBBCC') < cvd.CVD_FLOOR


def test_the_colors_they_replace_fail_those_bars():
    # the instrument lines and the run status: green, amber, red
    worst, _a, _b = _worst(['#2e7d32', '#8a5a00', '#c62828'])
    assert worst < cvd.CVD_FLOOR, worst
    # the job, folder and camera lines: gray, muted green, muted wine
    # (the gray and the wine are 1.2 apart for a deuteranope)
    worst, _a, _b = _worst(['#555555', '#117733', '#882255'])
    assert worst < 2.0, worst
    # the old DRY and LIVE buttons, pointer off and on, and their rows
    assert min(cvd._worst_de(d, lv) for d in ('#8a5a00', '#6d4700')
               for lv in ('#c62828', '#8e1a1a')) < cvd.CVD_FLOOR
    assert cvd._worst_de('#fff3cd', '#f8d7da') < cvd.CVD_FLOOR
    # and, as words on the bench gray: the muted green, Tk's 'green',
    # 'red', 'orange' and X11 'gray', and the plot window's old hint gray
    # on its white entry field
    for c, bg in (('#117733', BENCH_BG), ('#008000', BENCH_BG),
                  ('#FF0000', BENCH_BG), ('#FFA500', BENCH_BG),
                  ('#BEBEBE', BENCH_BG), ('#8A8A8A', '#FFFFFF')):
        assert _contrast(c, bg) < TEXT_MIN, (c, bg, _contrast(c, bg))


def test_no_other_tol_set_does_the_job():
    """ui_colors' docstring, measured: of Tol's colors, these ten reach
    4.5:1 on the bench gray; the one green among them is too close to
    every red, to the brown and to the gray; and beside the gray and
    black, blue and brown are the only pair of state colors that clears
    the floor against each other and against both."""
    passing = sorted(c for c in TOL if _contrast(c, BENCH_BG) >= TEXT_MIN)
    assert passing == sorted(['#2255AA', '#993366', '#006644', '#882288',
                              '#775500', '#444444', '#332288', '#882255',
                              '#004488', '#000000']), passing
    pine = '#006644'
    for other in ('#993366', '#882255', '#775500'):
        assert cvd._worst_de(pine, other) <= 11.95, other
    assert cvd._worst_de(pine, uc.TEXT_MUTED) <= 10.0
    colored = [c for c in passing if c not in (uc.TEXT, uc.TEXT_MUTED)]
    ok = [{a, b} for a, b in itertools.combinations(colored, 2)
          if all(cvd._worst_de(x, y) >= cvd.CVD_FLOOR for x, y in
                 ((a, b), (a, uc.TEXT_MUTED), (b, uc.TEXT_MUTED),
                  (a, uc.TEXT), (b, uc.TEXT)))]
    assert ok == [{uc.TEXT_OK, uc.TEXT_ALERT}], ok


# The modules #462 moved. The scan reads widget color keywords, canvas
# create_text fills and matplotlib .text colors; drawn lines and marks are
# #450's and #454's.
SCANNED = ('gui.py', 'sldea_edge_gui.py', 'sldea_plot_gui.py',
           'ui_widgets.py', 'arb_editor.py', 'battery_tab.py',
           'sldea_tuner.py', 'sldea_video_review.py', 'sldea_liveview.py',
           'scope_trace.py')
NAMED = {'black': '#000000', 'white': '#FFFFFF', '#000': '#000000',
         '#fff': '#FFFFFF'}
# Image-viewer surrounds: dark canvases a frame is shown on, not text
# backgrounds. The words drawn on them are checked above.
VIEWER_SURROUNDS = {('sldea_edge_gui.py', '#222'),
                    ('sldea_edge_gui.py', '#111'),
                    ('sldea_video_review.py', '#111')}
_KW = re.compile(r"(?<![A-Za-z_])(?:fg|foreground|bg|background|"
                 r"selectcolor|activebackground|activeforeground)"
                 r"\s*=\s*(['\"])([^'\"]+)\1")
_CANVAS_TEXT = re.compile(r"create_text\((?:[^()]|\([^()]*\))*?"
                          r"fill\s*=\s*(['\"])([^'\"]+)\1", re.S)
_PLOT_TEXT = re.compile(r"\.text\((?:[^()]|\([^()]*\))*?"
                        r"color\s*=\s*(['\"])([^'\"]+)\1", re.S)


# The three patterns above see a color written where it is used. A color
# kept in a constant (HINT_FG = '#8a8a8a', or a dict or list of them) and
# the branches of a keyword's conditional (fg=A if x else '#a01010') are
# words too, so the parsed source is walked for those (#462 review). Two
# constants hold drawn lines, not words: #450's and #454's to choose.
DRAWN_CONSTANTS = {('sldea_edge_gui.py', 'CAND_COLORS'),
                   ('sldea_tuner.py', 'PANEL_COLORS')}
_COLOR_KWS = {'fg', 'foreground', 'bg', 'background', 'selectcolor',
              'activebackground', 'activeforeground', 'fill', 'color'}
_HEX = re.compile(r"#(?:[0-9A-Fa-f]{3}){1,2}")
_TK_NAME = re.compile(r"(?:dark|light|medium)? ?(?:red|green|blue|orange|"
                      r"yellow|gr[ae]y|purple|brown|pink|cyan|magenta|navy|"
                      r"maroon|gold|violet)\d?", re.I)


def _is_color(text):
    return bool(_HEX.fullmatch(text) or _TK_NAME.fullmatch(text)
                or text.lower() in NAMED)


def _parsed_colors(name, src):
    """(line, literal) of every color string kept in an UPPER_CASE
    constant, and of either branch of a color keyword's conditional."""
    found = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
            names = [t.id if isinstance(t, ast.Name) else t.attr
                     for t in targets
                     if isinstance(t, (ast.Name, ast.Attribute))]
            if (node.value is None or not any(n.isupper() for n in names)
                    or any((name, n) in DRAWN_CONSTANTS for n in names)):
                continue
            for sub in ast.walk(node.value):
                if (isinstance(sub, ast.Constant)
                        and isinstance(sub.value, str)
                        and _is_color(sub.value)):
                    found.append((sub.lineno, sub.value))
        elif (isinstance(node, ast.keyword) and node.arg in _COLOR_KWS
              and isinstance(node.value, ast.IfExp)):
            todo = [node.value]
            while todo:
                cond = todo.pop()
                for branch in (cond.body, cond.orelse):
                    if isinstance(branch, ast.IfExp):
                        todo.append(branch)
                    elif (isinstance(branch, ast.Constant)
                          and isinstance(branch.value, str)):
                        found.append((branch.lineno, branch.value))
    return found


def _strays(name, src):
    """'name:line literal' for every color in `src` outside Tol's."""
    hits = []
    for pat in (_KW, _CANVAS_TEXT, _PLOT_TEXT):
        for m in pat.finditer(src):
            hits.append((src.count('\n', 0, m.start()) + 1, m.group(2)))
    hits += _parsed_colors(name, src)
    stray = []
    for line, lit in sorted(set(hits)):
        color = NAMED.get(lit.lower(), lit).upper()
        if color in TOL or (name, lit) in VIEWER_SURROUNDS:
            continue
        stray.append(f"{name}:{line} {lit}")
    return stray


def test_the_moved_modules_write_no_word_in_a_stray_color():
    stray = []
    for name in SCANNED:
        with open(os.path.join(REPO, name), encoding='utf-8') as fh:
            stray += _strays(name, fh.read())
    assert not stray, "colors outside Tol's schemes:\n  " + "\n  ".join(stray)


def test_the_scan_finds_what_it_is_looking_for():
    """The source scan above passes on a file with no colors at all, so
    show it catching each kind of literal it is meant to catch, and
    passing the Tol and drawn-line ones it must leave alone."""
    src = ("tk.Label(f, fg='#c62828')\n"
           "x.config(highlightbackground='#999')\n"
           "c.create_text(1, 2, text='a', font=('A', 8), fill='#999')\n"
           "ax.text(0.5, 0.5, 'b', ha='center', color='#555')\n"
           "tk.Label(f, fg='red')\n"
           "HINT_FG = '#8a8a8a'\n"
           "STATE_COLORS = {'ok': '#2255AA', 'bad': 'dark green'}\n"
           "tk.Label(f, fg=uc.TEXT_OK if ok else '#a01010')\n"
           "tk.Label(f, fg=COLORS['warn' if warn else 'ok'])\n"
           "CAND_COLORS = ['#00c853']\n"
           "TITLE = 'Edge Review'\n")
    found = _strays('sldea_edge_gui.py', src)
    want = ['sldea_edge_gui.py:' + s for s in (
        '1 #c62828', '3 #999', '4 #555', '5 red', '6 #8a8a8a',
        '7 dark green', '8 #a01010')]
    assert found == want, found


# ---------------------------------------------------------------- on screen

_APP = []


def _app():
    """(root, app) with every tab built, shared by the cases below."""
    if _APP:
        return _APP[0]
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    import gui
    gui.InstrumentControlGUI.auto_connect = lambda self: None
    gui.CAM_AUTOSTART_ON_TAB = False        # never open this PC's camera
    app = gui.InstrumentControlGUI(root)
    for _ in range(6):
        root.update_idletasks()
        root.update()
    _APP.append((root, app))
    return root, app


def _hex(widget, color):
    r, g, b = widget.winfo_rgb(color)
    return '#%02X%02X%02X' % (r // 257, g // 257, b // 257)


def _is_large(widget, font):
    """WCAG large text: 18 pt, or 14 pt bold."""
    from tkinter import font as tkfont
    try:
        f = tkfont.Font(root=widget, font=font).actual()
    except Exception:
        return False
    size = f['size']
    if size < 0:                                   # pixels
        size = -size * 72.0 / widget.winfo_fpixels('1i')
    return size >= 18 or (size >= 14 and f['weight'] == 'bold')


def _colored_words(root):
    """(widget, fg, bg, on_default_bg, large) for every widget that sets
    its own text color."""
    from tkinter import ttk
    style = ttk.Style(root)
    out, todo = [], [root]
    while todo:
        w = todo.pop()
        todo.extend(w.winfo_children())
        if isinstance(w, ttk.Widget):
            if 'foreground' not in w.keys():
                continue
            fg = str(w.cget('foreground'))
            if not fg:
                continue
            own_bg = str(w.cget('background')) if 'background' in w.keys() \
                else ''
            cls = str(w.cget('style')) or w.winfo_class()
            bg = own_bg or style.lookup(cls, 'background') or \
                style.lookup('.', 'background')
            out.append((w, fg, bg, not own_bg,
                        _is_large(w, w.cget('font') or 'TkDefaultFont')))
            continue
        if 'fg' not in w.keys() or 'bg' not in w.keys():
            continue
        large = _is_large(w, w.cget('font'))
        cfg_fg, cfg_bg = w.configure('fg'), w.configure('bg')
        if str(cfg_fg[4]) != str(cfg_fg[3]):       # not the default color
            out.append((w, str(cfg_fg[4]), str(cfg_bg[4]),
                        str(cfg_bg[4]) == str(cfg_bg[3]), large))
        if 'activeforeground' in w.keys():
            # the colors Tk paints while the pointer is over a button
            afg = w.configure('activeforeground')
            abg = w.configure('activebackground')
            if str(afg[4]) != str(afg[3]) or str(abg[4]) != str(abg[3]):
                out.append((w, str(afg[4]), str(abg[4]), False, large))
    return out


def test_on_the_built_app_every_colored_word_reads():
    root, _app_ = _app()
    words = _colored_words(root)
    assert len(words) >= 30, f"the walk found only {len(words)} widgets"
    bad = []
    for w, fg, bg, on_default, large in words:
        need = LARGE_TEXT_MIN if large else TEXT_MIN
        f, b = _hex(w, fg), _hex(w, bg)
        for against in ((b, BENCH_BG) if on_default else (b,)):
            r = _contrast(f, against)
            if r < need:
                bad.append(f"{w} fg {fg} on {against}: {r:.2f}:1 < {need}")
    assert not bad, "\n  ".join(['words that do not read:'] + bad)


def test_the_dry_live_row_says_its_state_in_words_and_tol_colors():
    _root, app = _app()
    seen = {}
    try:
        for dry in (True, False):
            app.sldea_dryrun.set(dry)
            app._sldea_dry_toggle()
            cb, btn = app.sldea_dry_cb, app.sldea_run_btn
            seen[dry] = (str(cb.cget('text')), str(btn.cget('text')))
            want = ((uc.ROW_DRY, uc.FILL_DRY, uc.FILL_DRY_ACTIVE) if dry
                    else (uc.ROW_LIVE, uc.FILL_LIVE, uc.FILL_LIVE_ACTIVE))
            got = (str(cb.cget('bg')), str(btn.cget('bg')),
                   str(btn.cget('activebackground')))
            assert got == want, (dry, got)
            assert str(cb.cget('fg')) == uc.TEXT
            assert str(btn.cget('fg')).lower() == 'white'
            assert str(btn.cget('activeforeground')) == uc.TEXT_ON_FILL, \
                "the run button's words turn black under the pointer"
    finally:
        app.sldea_dryrun.set(True)
        app._sldea_dry_toggle()
    assert 'DRY' in seen[True][0] and 'DRY' in seen[True][1], seen
    assert 'LIVE' in seen[False][0] and 'LIVE' in seen[False][1], seen
    assert 'LIVE' not in ''.join(seen[True]), seen


def test_output_on_is_the_energized_red_on_both_tabs():
    """An SG output can drive the Trek, so Output: ON wears the LIVE red,
    not the OK blue the DRY button and "Connected" use. Only the button's
    look is set here; no instrument is touched."""
    _root, app = _app()
    for setter, widgets in ((app._sg_set_output_button,
                             app.sg_channel_widgets),
                            (app._psu_set_output_button,
                             app.psu_channel_widgets)):
        assert widgets, "no output buttons were built"
        for ch in widgets:
            btn = widgets[ch]['out_btn']
            try:
                setter(ch, True)
                assert str(btn.cget('text')) == 'Output: ON'
                got = (str(btn.cget('bg')), str(btn.cget('activebackground')),
                       str(btn.cget('fg')), str(btn.cget('activeforeground')))
                assert got == (uc.FILL_LIVE, uc.FILL_LIVE_ACTIVE,
                               uc.TEXT_ON_FILL, uc.TEXT_ON_FILL), (ch, got)
            finally:
                setter(ch, False)
            assert str(btn.cget('text')) == 'Output: OFF'
            assert str(btn.cget('bg')) != uc.FILL_LIVE


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    ran = skipped = 0
    failed = []
    try:
        for n in names:
            try:
                globals()[n]()
            except _Skip as why:
                skipped += 1
                print('skip', n, f'({why})')
                continue
            except Exception:
                # A test that blew up still RAN -- only a skip is "did not
                # run".
                ran += 1
                failed.append((n, traceback.format_exc()))
                print('FAIL', n)
                continue
            ran += 1
            print('ok ', n)
    finally:
        for root, _app_ in _APP:
            try:
                root.destroy()
            except Exception:
                pass
    tail = f"{ran} of {len(names)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped, no display)"
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
