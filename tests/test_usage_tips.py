#!/usr/bin/env python3
"""Usage Tips open in a window built for them, and say little (#480).

Each instrument tab's "Show Usage Tips" button used to call
messagebox.showinfo. On Windows that is the native message box: narrow,
fixed in size and unable to scroll, so the Signal Gen tab's 630 words
wrapped line by line down the screen. What these pin down (2026-10-20):

  * every instrument tab's button opens ui_widgets' tips window with that
    tab's page from usage_tips.PAGES, and no message box;
  * the window is resizable, scrolls, wraps its words to its own width,
    starts at a size for the 1920x1080 bench monitor and is never larger
    than the screen;
  * it is modeless (no grab), Esc and Close shut it, and a second press of
    the button raises the open window instead of stacking another;
  * it is transient for the app and opens at the screen's right edge,
    whole and above the taskbar margin, wherever the app sits;
  * the wheel scrolls the page both ways (X11's Button-4 and Button-5
    too) and goes no further: a tab's application-wide wheel binding never
    sees it;
  * its words reach WCAG 2.1 SC 1.4.3's 4.5:1 on the page they sit on, in
    Tol colors (with the helpers of tests/test_ui_colors.py);
  * the pages stay short, keep their safety lines and keep them first,
    and say what the code does: closing the window is a best-effort stop
    that Restart now does not make, and the LCR refuses a level outside
    0.01 to 2.0 V rather than clamping it;
    every control a page names is a real widget label; every page names a
    real manual section; and the CSV columns the logging tip no longer
    lists are in the manual, as the code writes them.

The cases that build the app are skipped, and counted as skipped, when
there is no display.

Run: .venv/bin/python tests/test_usage_tips.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import ast
import json
import os
import re

import test_ui_colors as tuc
import ui_colors as uc
import ui_widgets
import usage_tips
from ui_widgets import ALERT_SIGN, BULLET, tips_place, tips_size, tips_text

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUTTON_TEXT = "📖 Show Usage Tips"
INSTRUMENT_TABS = {'lcr', 'scope', 'siggen', 'psu', 'dmm', 'logging'}


class _Skip(Exception):
    """The test could not run here (no display): reported, not passed."""


def _words(text):
    """Whitespace-separated tokens with a letter or digit in them, so a
    bullet or a warning sign is not a word."""
    return [t for t in text.split() if re.search(r'\w', t)]


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding='utf-8') as fh:
        return fh.read()


# ---------------------------------------------------------------- headless

def test_every_instrument_tab_has_a_page():
    assert set(usage_tips.PAGES) == INSTRUMENT_TABS, sorted(usage_tips.PAGES)
    assert set(usage_tips.NAMED_CONTROLS) == INSTRUMENT_TABS
    for slug, page in usage_tips.PAGES.items():
        assert page.title.endswith(' Tips'), (slug, page.title)
        assert page.heading and page.sections and page.manual, slug
        for section in page.sections:
            assert len(section) in (2, 3), (slug, section)
            heading, lines = section[0], section[1]
            assert heading and lines, (slug, heading)
            assert all(isinstance(s, str) and s for s in lines), heading


def test_the_text_is_in_the_order_the_window_shows_it():
    page = usage_tips.SIGGEN
    lines = tips_text(page).split('\n')
    assert lines[0] == page.heading
    assert lines[1] == f"{ALERT_SIGN} Safety", lines[1]
    assert lines[2].startswith(BULLET + '\t'), lines[2]
    assert lines[-1] == page.manual
    heads = [s[0] for s in page.sections if len(s) == 2]
    assert all(h in lines for h in heads), heads
    n_bullets = sum(len(s[1]) for s in page.sections)
    assert sum(ln.startswith(BULLET + '\t') for ln in lines) == n_bullets


def test_the_safety_lines_stay_and_come_first():
    """The issue: cut the words, never the safety ones. A page with a
    safety section has it first, drawn as an alert."""
    for slug, page in usage_tips.PAGES.items():
        alerts = [i for i, s in enumerate(page.sections)
                  if len(s) > 2 and s[2]]
        assert alerts in ([], [0]), (slug, alerts)
    sg = tips_text(usage_tips.SIGGEN)
    for must in ("1 V from this generator is 1 kV at the DEA",
                 "Enter = No",
                 "Closing the window tries to switch both outputs off (best "
                 "effort); Restart now leaves them as they are.",
                 "LIVE SLDEA run locks the channel driving the Trek",
                 "End the run with ■ Abort on the SLDEA tab, never by "
                 "closing the window."):
        assert must in sg, must
    psu = tips_text(usage_tips.PSU)
    for must in ("Closing the app leaves the supply as it is",
                 "Only Output: OFF energizes the terminals",
                 "asks first", "not a fuse", "Set Protection"):
        assert must in psu, must
    scope = tips_text(usage_tips.SCOPE)
    assert "breakdown watchdog reads I_Out" in scope
    assert "Say Yes only if the scope has stopped answering" in scope
    lcr = tips_text(usage_tips.LCR)
    assert "stays on until you untick it" in lcr
    assert ("Closing the window tries to switch the bias off (best "
            "effort); Restart now leaves it on.") in lcr
    # Closing is a best-effort stop, never a safe one (#480 review): no
    # page may say closing switches anything off outright
    for slug, page in usage_tips.PAGES.items():
        text = tips_text(page)
        assert not re.search(r'[Cc]losing the (app|window) switch',
                             text), slug
    for slug in ('siggen', 'psu', 'scope'):
        first = usage_tips.PAGES[slug].sections[0]
        assert len(first) == 3 and first[2] == usage_tips.ALERT, slug


def test_the_safety_lines_say_what_the_code_does():
    """What the safety lines promise about closing the app and confirming
    Output ON, read from gui.py's own source."""
    src = _read('gui.py')
    close = src[src.index('def _on_app_close'):]
    close = close[:close.index('\n    def ')]
    assert 'self.sg.set_output(ch, False)' in close      # SG outputs off
    assert 'set_bias_enabled(False)' in close             # LCR bias off
    assert 'self.psu.set_output' not in close             # PSU left as is
    # ... each only TRIED: every write swallows its own failure
    for write in ('self.sg.set_output(ch, False)',
                  'self.lcr.set_bias_enabled(False)'):
        before = close[:close.index(write)].rstrip().splitlines()[-1]
        assert before.strip() == 'try:', (write, before)
    # Restart now is not that shutdown: it leaves outputs and bias as is
    restart = src[src.index('def _restart_app'):]
    restart = restart[:restart.index('\n    def ')]
    for call in ('_on_app_close', 'set_output', 'set_bias_enabled'):
        assert call not in restart, call
    sg_on = src[src.index('def sg_toggle_output'):]
    sg_on = sg_on[:sg_on.index('\n    def ')]
    assert "1 V = 1 kV at the DEA" in sg_on and "default='no'" in sg_on
    psu_on = src[src.index('def psu_toggle_output'):]
    psu_on = psu_on[:psu_on.index('\n    def ')]
    assert 'askyesno' in psu_on and "default='no'" in psu_on


def test_the_lcr_voltage_line_says_what_apply_does():
    """The meter's level is 0.01 to 2.0 V, and the app refuses anything
    else before it reaches the meter: BK894.set_voltage raises, and
    apply_lcr_config shows that as a Configuration Error. The old tip,
    and this page's first draft, said the meter clamps it silently."""
    lcr = tips_text(usage_tips.LCR)
    assert 'clamp' not in lcr.lower()
    assert '0.01 to 2.0 V' in lcr and 'Configuration Error' in lcr
    drv = _read('instruments.py')
    from instruments import BK894
    assert BK894.VOLT_MIN == 0.01 and BK894.VOLT_MAX == 2.0
    check = drv[drv.index('    def check_voltage(cls, voltage):'):]
    check = check[:check.index('\n    @')]
    assert 'if not cls.VOLT_MIN <= voltage <= cls.VOLT_MAX:' in check
    assert 'raise ValueError("Voltage must be 0.01 to 2.0 V")' in check
    setter = drv[drv.index('    def set_voltage(self, voltage):'):]
    setter = setter[:setter.index('\n    def ')]
    assert 'self.check_voltage(voltage)' in setter
    src = _read('gui.py')
    apply = src[src.index('def apply_lcr_config'):]
    apply = apply[:apply.index('\n    def ')]
    assert 'self.lcr.set_voltage(volt)' in apply
    # and Apply runs the same check before it sends anything (#483)
    assert apply.index('self.lcr.validate_config(') < apply.index(
        'self.lcr.set_mode(mode)')
    assert 'messagebox.showerror("Configuration Error", str(error))' in apply
    # nor do the Voltage tooltip or the manual's LCR entry say it clamps
    tab = src[src.index('def create_lcr_tab'):]
    tab = tab[:tab.index('\n    def ')]
    assert 'clamp' not in tab, "the LCR tab still says the meter clamps"
    content = json.loads(_read('docs', 'manual-src', 'content.json'))
    assert 'clamp' not in json.dumps(content['lcr']).lower()


def test_the_pages_are_short():
    """630 words was the Signal Gen tab's. A page fits the window at a
    glance or two, and a bullet is one thought."""
    for slug, page in usage_tips.PAGES.items():
        words = _words(tips_text(page))
        assert len(words) <= 240, (slug, len(words))
        for section in page.sections:
            for line in section[1]:
                assert len(_words(line)) <= 32, (slug, line)
            assert len(section[1]) <= 6, (slug, section[0])


def test_no_dash_made_of_hyphens():
    """House style: never -- or --- as a dash. The one "--" allowed is the
    live table's own placeholder, quoted as it appears on screen."""
    for slug, page in usage_tips.PAGES.items():
        text = tips_text(page).replace('"--"', '')
        assert '--' not in text, slug


def test_each_page_names_a_real_manual_section():
    src = _read('docs', 'manual-src', 'build_manual.py')
    block = src[src.index('SECTIONS = ['):]
    block = block[:block.index(']\n') + 1]
    titles = {t for _slug, t in ast.literal_eval(block[len('SECTIONS = '):])}
    for slug, page in usage_tips.PAGES.items():
        quoted = re.findall(r'"([^"]+)"', page.manual)
        assert quoted and quoted[-1] in titles, (slug, page.manual)


def test_the_logging_columns_moved_to_the_manual_as_written():
    """The logging tip listed every CSV's columns; they moved to the
    manual's Continuous Logging entry. Each header row logging_loop
    writes is checked there, in order, with its file name."""
    src = _read('gui.py')
    loop = src[src.index('def logging_loop'):]
    loop = loop[:loop.index('\n    def ')]
    found = re.findall(r"_open\([^,]+,\s*f\"(\w+?)_[^\"]*\.csv\",\s*"
                       r"(\[[^\]]*\])", loop)
    assert len(found) == 5, found
    content = json.loads(_read('docs', 'manual-src', 'content.json'))
    words = ' '.join(c['what'] for c in content['logging']['controls'])
    for stem, header in found:
        cols = ast.literal_eval(header)
        assert ', '.join(cols) in words, (stem, cols)
        assert stem in words, stem
    assert 'YYYY-MM-DD HH:MM:SS.mmm' in words
    assert '"%Y-%m-%d %H:%M:%S.%f")[:-3]' in loop


def test_the_starting_size_suits_the_bench_and_fits_any_screen():
    assert tips_size(96, 1920, 1080) == (640, 560)
    # a high-dpi Tk gets the same physical size, cut to the screen
    assert tips_size(144, 1920, 1080) == (960, 840)
    assert tips_size(192, 1920, 1080) == (1280, 1000)
    # a short screen: never taller than the screen less the margin
    assert tips_size(96, 1366, 600) == (640, 520)
    # a tiny one: the minimum wins
    assert tips_size(96, 300, 200) == ui_widgets.TIPS_MIN_SIZE
    # below 96 dpi it does not shrink
    assert tips_size(72, 1920, 1080) == (640, 560)


def test_it_opens_at_the_screens_right_edge_and_stays_on_screen():
    """Transient, so it stays above the app: it opens where it covers the
    least of the app, the screen's right edge, level with the app's top."""
    pad, margin = ui_widgets.TIPS_FRAME_PAD, ui_widgets.TIPS_SCREEN_MARGIN
    assert tips_place(1920, 1080, 640, 560, 30) == (1920 - 640 - pad, 30)
    # the app low on the screen: the window rises to clear the taskbar
    assert tips_place(1920, 1080, 640, 560, 900) == (
        1920 - 640 - pad, 1080 - 560 - margin)
    # the app partly above the screen
    assert tips_place(1920, 1080, 640, 560, -50) == (1920 - 640 - pad, 0)
    # a screen narrower than the window: its left edge stays on screen
    assert tips_place(300, 200, 360, 240, 10) == (0, 0)


def test_the_page_colors_are_tol_and_read():
    for name, c in (('TIPS_BG', ui_widgets.TIPS_BG), ('TEXT', uc.TEXT),
                    ('TEXT_ACCENT', uc.TEXT_ACCENT),
                    ('TEXT_ALERT', uc.TEXT_ALERT),
                    ('TEXT_MUTED', uc.TEXT_MUTED)):
        hexed = tuc.NAMED.get(c.lower(), c).upper()
        assert hexed in tuc.TOL, (name, c)
        if name != 'TIPS_BG':
            r = tuc._contrast(c, '#FFFFFF')
            assert r >= tuc.TEXT_MIN, (name, r)


def test_no_tab_opens_a_message_box_for_its_tips():
    src = _read('gui.py')
    for name in ('show_lcr_tips', 'show_scope_tips', 'show_sg_tips',
                 'show_psu_tips', 'show_dmm_tips', 'show_logging_tips'):
        body = src[src.index(f'def {name}(self):'):]
        body = body[:body.index('\n    def ')]
        assert '_show_usage_tips(' in body and 'messagebox' not in body, \
            name
    # the old strings' first lines read "<instrument> - Usage Tips"
    assert not re.search(r'\S - Usage Tips', src)


# ---------------------------------------------------------------- on screen

_APP = []


def _app():
    """(root, app) with every tab built, shared by the cases below; built
    the way tests/test_ui_colors.py builds it."""
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
    root.geometry('1320x800')
    _settle(root, 6)
    _APP.append((root, app))
    return root, app


def _settle(root, n=4):
    for _ in range(n):
        root.update_idletasks()
        root.update()


def _descendants(w):
    out, todo = [], [w]
    while todo:
        x = todo.pop()
        kids = x.winfo_children()
        out.extend(kids)
        todo.extend(kids)
    return out


def _tips_button(app, slug):
    from tkinter import ttk
    tab = app.tab_widget(slug)
    assert tab is not None, f"the {slug} tab did not build"
    found = [w for w in _descendants(tab) if isinstance(w, ttk.Button)
             and str(w.cget('text')) == BUTTON_TEXT]
    assert len(found) == 1, (slug, len(found))
    return found[0]


def _open_windows(root):
    return [w for w in root.winfo_children()
            if isinstance(w, ui_widgets.TipsWindow) and w.winfo_exists()]


def _close_all(root):
    for w in _open_windows(root):
        w.destroy()
    _settle(root, 2)


def test_each_tabs_button_opens_its_own_page_and_no_message_box():
    import gui
    root, app = _app()
    boxes = []
    real = gui.messagebox.showinfo
    gui.messagebox.showinfo = lambda *a, **k: boxes.append(a)
    content = _read('docs', 'manual-src', 'content.json')
    try:
        for slug, page in usage_tips.PAGES.items():
            btn = _tips_button(app, slug)
            btn.invoke()
            _settle(root, 2)
            wins = _open_windows(root)
            assert len(wins) == 1, (slug, len(wins))
            win = wins[0]
            assert ui_widgets._TIPS_OPEN[(root, slug)] is win, slug
            assert str(win.title()) == page.title, (slug, win.title())
            shown = win.text.get('1.0', 'end-1c')
            assert shown == tips_text(page), slug
            # the button's words are the ones the manual quotes
            assert json.dumps(BUTTON_TEXT, ensure_ascii=False) in content
            win.destroy()
            _settle(root, 2)
        assert not boxes, f"a message box opened: {boxes}"
    finally:
        gui.messagebox.showinfo = real
        _close_all(root)


def test_the_window_resizes_scrolls_and_rewraps():
    root, app = _app()
    try:
        win = app.show_sg_tips()
        _settle(root, 4)
        resizable = [bool(int(str(v)))
                     for v in win.tk.splitlist(win.resizable())]
        assert resizable == [True, True], resizable
        w, h = tips_size(win.winfo_fpixels('1i'), win.winfo_screenwidth(),
                         win.winfo_screenheight())
        assert (win.winfo_width(), win.winfo_height()) == (w, h), \
            (win.winfo_width(), win.winfo_height(), w, h)
        assert win.winfo_height() <= win.winfo_screenheight()
        assert str(win.text.cget('wrap')) == 'word'
        assert str(win.text.cget('state')) == 'disabled', \
            "the page is editable"
        # a scrollbar on screen, wired to the text
        assert win.vbar.winfo_ismapped()
        assert str(win.text.cget('yscrollcommand')), "the bar is not wired"
        # shrink it: the words rewrap to the narrower window (more display
        # lines) and the page scrolls
        wide = win.text.count('1.0', 'end', 'displaylines')
        win.geometry('420x300')
        _settle(root, 4)
        assert win.winfo_width() == 420, win.winfo_width()
        narrow = win.text.count('1.0', 'end', 'displaylines')
        wide, narrow = (int(str(x[0] if isinstance(x, tuple) else x))
                        for x in (wide, narrow))
        assert narrow > wide, (wide, narrow)
        top, bottom = win.text.yview()
        assert top == 0.0 and bottom < 1.0, "nothing to scroll"
        win.text.yview_moveto(1.0)
        _settle(root, 2)
        assert win.text.yview()[0] > 0.0, "the page did not scroll"
        # the wheel and Page Down scroll it too, from the window
        win.text.yview_moveto(0.0)
        _settle(root, 2)
        win.event_generate('<MouseWheel>', delta=-120)
        _settle(root, 2)
        assert win.text.yview()[0] > 0.0, "the wheel did not scroll it"
    finally:
        _close_all(root)


def test_on_screen_it_opens_at_the_right_edge_above_the_app():
    """With the app's window low on the screen, the tips window still
    opens whole, above the taskbar margin, at the screen's right edge, and
    transient for the app."""
    root, app = _app()
    old = root.geometry()
    try:
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f'+0+{sh - 300}')
        _settle(root, 4)
        win = app.show_lcr_tips()
        _settle(root, 4)
        x, y = win.winfo_rootx(), win.winfo_rooty()
        w, h = win.winfo_width(), win.winfo_height()
        assert x >= 0 and y >= 0, (x, y)
        assert x + w <= sw, (x, w, sw)
        assert y + h <= sh - ui_widgets.TIPS_SCREEN_MARGIN // 2, (y, h, sh)
        assert x + w >= sw - 3 * ui_widgets.TIPS_FRAME_PAD, (
            "not at the screen's right edge", x, w, sw)
        assert str(win.transient()) == str(root), "not transient for the app"
    finally:
        root.geometry(old)
        _close_all(root)


def test_the_wheel_scrolls_both_ways_and_reaches_nothing_behind():
    """The bench is X11, where the wheel is Button-4 (up) and Button-5
    (down). A wheel turn over the page scrolls the page and stops there:
    a tab's ScrollableFrame binds the wheel application-wide while the
    pointer is over it, and that binding must not scroll the tab too."""
    root, app = _app()
    seqs = ('<MouseWheel>', '<Button-4>', '<Button-5>')
    saved = {seq: root.bind_all(seq) for seq in seqs}
    leaked = []
    try:
        for seq in seqs:
            root.bind_all(seq, lambda _e, seq=seq: leaked.append(seq))
        win = app.show_sg_tips()
        win.geometry('420x300')
        _settle(root, 4)
        t = win.text
        t.yview_moveto(0.0)
        _settle(root, 2)
        t.event_generate('<Button-5>')
        t.event_generate('<ButtonRelease-5>')
        _settle(root, 2)
        down = t.yview()[0]
        assert down > 0.0, "Button-5 did not scroll the page down"
        t.event_generate('<Button-4>')
        t.event_generate('<ButtonRelease-4>')
        _settle(root, 2)
        assert t.yview()[0] < down, "Button-4 did not scroll the page up"
        before = t.yview()[0]
        t.event_generate('<MouseWheel>', delta=-120)
        _settle(root, 2)
        assert t.yview()[0] > before, "the wheel did not scroll the page"
        win.vbar.event_generate('<MouseWheel>', delta=120)
        _settle(root, 2)
        assert not leaked, f"the wheel reached a binding behind: {leaked}"
    finally:
        for seq in seqs:
            root.unbind_all(seq)
            if saved[seq]:
                root.tk.call('bind', 'all', seq, saved[seq])
        _close_all(root)


def test_it_is_modeless_and_a_second_press_raises_it():
    root, app = _app()
    try:
        btn = _tips_button(app, 'siggen')
        btn.invoke()
        _settle(root, 2)
        first = ui_widgets._TIPS_OPEN[(root, 'siggen')]
        assert root.grab_current() is None, "the tips window took a grab"
        btn.invoke()
        _settle(root, 2)
        assert ui_widgets._TIPS_OPEN[(root, 'siggen')] is first
        assert _open_windows(root) == [first], "a second window was stacked"
        # another tab's tips open beside it, one each
        _tips_button(app, 'psu').invoke()
        _settle(root, 2)
        assert len(_open_windows(root)) == 2
        # the tab stays usable meanwhile
        app.sg_advanced.set(True)
        app._sg_advanced_toggled()
        app.sg_advanced.set(False)
        app._sg_advanced_toggled()
        # a closed window is no longer the one a press raises
        first.destroy()
        _settle(root, 2)
        assert (root, 'siggen') not in ui_widgets._TIPS_OPEN
        btn.invoke()
        _settle(root, 2)
        again = ui_widgets._TIPS_OPEN[(root, 'siggen')]
        assert again is not first and again.winfo_exists()
    finally:
        _close_all(root)


def test_escape_and_close_shut_it():
    root, app = _app()
    try:
        win = app.show_dmm_tips()
        _settle(root, 2)
        assert win.bind('<Escape>'), "Esc is not bound"
        win.focus_force()
        _settle(root, 2)
        win.event_generate('<Escape>')
        _settle(root, 2)
        assert not _open_windows(root), "Esc did not close the window"
        win = app.show_dmm_tips()
        _settle(root, 2)
        assert str(win.close_btn.cget('text')) == 'Close'
        win.close_btn.invoke()
        _settle(root, 2)
        assert not _open_windows(root), "Close did not close the window"
    finally:
        _close_all(root)


def test_its_words_reach_the_bar_in_tol_colors():
    root, app = _app()
    try:
        for opener in (app.show_sg_tips, app.show_psu_tips):
            win = opener()
            _settle(root, 2)
            words = tuc._colored_words(win)
            assert any(w is win.text for w, *_rest in words), \
                "the walk did not see the page's words"
            for w, fg, bg, on_default, large in words:
                need = tuc.LARGE_TEXT_MIN if large else tuc.TEXT_MIN
                f, b = tuc._hex(w, fg), tuc._hex(w, bg)
                for against in ((b, tuc.BENCH_BG) if on_default else (b,)):
                    r = tuc._contrast(f, against)
                    assert r >= need, (str(w), fg, against, r)
            page_bg = tuc._hex(win.text, str(win.text.cget('bg')))
            tags = ('title', 'head', 'alert', 'item', 'manual')
            for tag in tags:
                assert tag in win.text.tag_names(), tag
                fg = str(win.text.tag_cget(tag, 'foreground')) or \
                    str(win.text.cget('fg'))
                f = tuc._hex(win.text, fg)
                assert f in tuc.TOL, (tag, f)
                r = tuc._contrast(f, page_bg)
                assert r >= tuc.TEXT_MIN, (tag, f, page_bg, r)
            # the safety heading is the alert color, and says so in words
            alert = win.text.tag_ranges('alert')
            if opener == app.show_sg_tips:
                assert alert, "no safety heading"
                said = win.text.get(alert[0], alert[1])
                assert said.startswith(ALERT_SIGN) and 'Safety' in said
            win.destroy()
            _settle(root, 2)
    finally:
        _close_all(root)


def test_every_control_a_page_names_is_a_real_label():
    """A renamed button must not leave a tip that names the old label."""
    root, _app_ = _app()
    texts = set()
    for w in _descendants(root):
        try:
            texts.add(str(w.cget('text')))
        except Exception:
            pass
    for slug, labels in usage_tips.NAMED_CONTROLS.items():
        page = tips_text(usage_tips.PAGES[slug])
        for label in labels:
            assert label in page, (slug, label)
            assert label in texts, f"{slug}: no widget reads {label!r}"


def _run():
    # Failures are collected, not fatal (`#280`), and tracebacks land after
    # the count line, in name order, in one bounded block.
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
