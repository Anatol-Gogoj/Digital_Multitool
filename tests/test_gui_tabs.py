#!/usr/bin/env python3
"""Real tabs stay reachable at narrow windows (`#26`, `#225`).

`#26` reported the LCR tab's lower controls cut off with no scrollbar
until the window was resized. Its VERTICAL half was fixed in 8d494e8,
which wrapped every tab in ScrollableTab; what stayed broken was
horizontal, and 790c0c7 papered over that by widening the default window
to 1320x800 ("the new LCR bias/correction column was clipped at the
default 1000px window width") rather than by making the column reachable.
`#225` removed the clip for real.

So this suite pins the property both of those fixes bought, on the REAL
tabs rather than a synthetic one, at a window narrow and short enough to
force both bars: nothing on any tab may be unreachable. Without it the
only thing standing between the app and a repeat of `#26` is the default
geometry, which is a comfort setting a user can change.

test_app_launch.py covers "does a window appear" but is Xvfb-gated and
skips on Windows, so these are also the only automated checks that touch
the real tabs on the lab PC.

Run: .venv/bin/python tests/test_gui_tabs.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

# Narrow AND short enough that most tabs overflow both ways.
NARROW, SHORT = 700, 600


def _app():
    """(root, app) with every tab built, or (None, None) with no display."""
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return None, None
    import gui
    # No instrument hunt: it is irrelevant here and starts threads.
    gui.InstrumentControlGUI.auto_connect = lambda self: None
    app = gui.InstrumentControlGUI(root)
    root.geometry(f'{NARROW}x{SHORT}')
    root.deiconify()
    _settle(root, 12)
    return root, app


def _settle(root, n=8):
    import time
    for _ in range(n):
        root.update_idletasks()
        root.update()
        time.sleep(0.02)


def _tabs(root, app):
    from ui_widgets import ScrollableTab
    out = []
    for tid in app.notebook.tabs():
        w = root.nametowidget(tid)
        out.append((app.notebook.tab(tid, 'text'), w))
    assert out, "no tabs at all"
    assert all(isinstance(w, ScrollableTab) for _n, w in out), (
        "a tab stopped being scrollable: %s"
        % [n for n, w in out if not isinstance(w, ScrollableTab)])
    return out


def test_the_lcr_tab_is_scrollable_at_all():
    """`#26` asked the question directly: is it wrapped at all?"""
    from ui_widgets import ScrollableTab
    root, app = _app()
    if root is None:
        return
    try:
        name, tab = _tabs(root, app)[0]
        assert 'LCR' in name, name
        assert isinstance(tab, ScrollableTab)
        # the vertical bar is unconditional -- it is never the missing piece
        assert tab.winfo_children(), "tab has no scrollbars"
    finally:
        root.destroy()


def test_nothing_on_any_tab_is_unreachable():
    """The `#225` property on real content: whatever does not fit must be
    scrollable to, in both directions, on every tab."""
    root, app = _app()
    if root is None:
        return
    try:
        for name, tab in _tabs(root, app):
            app.notebook.select(tab)
            _settle(root, 5)
            cv = tab._canvas
            cw, ch = cv.winfo_width(), cv.winfo_height()
            rw, rh = tab.body.winfo_reqwidth(), tab.body.winfo_reqheight()
            if rw > cw:
                assert tab._hbar.winfo_ismapped(), (
                    f"{name}: {rw - cw} px off to the right with no h-bar")
                assert cv.xview()[1] < 1.0, f"{name}: h-bar cannot scroll"
                cv.xview_moveto(1.0)
                _settle(root, 3)
                assert cv.bbox('all')[2] - int(cv.canvasx(0)) <= cw + 1, (
                    f"{name}: right edge still off screen after scrolling")
            else:
                assert not tab._hbar.winfo_ismapped(), (
                    f"{name}: h-bar shown though content fits")
            if rh > ch:
                assert cv.yview()[1] < 1.0, f"{name}: v-bar cannot scroll"
                cv.yview_moveto(1.0)
                _settle(root, 3)
                assert cv.yview()[1] >= 0.999, (
                    f"{name}: bottom unreachable ({rh - ch} px cut off)")
    finally:
        root.destroy()


def test_the_lcr_right_hand_column_is_reachable():
    """`#26`'s live remainder, concretely: the bias / speed / correction
    column that 790c0c7 could only rescue by widening the window.

    The old failure SQUEEZED the column rather than moving it off screen
    -- the content was pinned to the canvas width -- so "is the right edge
    inside the canvas" cannot see it. What gives it away is the body being
    laid out narrower than it asked for.
    """
    root, app = _app()
    if root is None:
        return
    try:
        _name, tab = _tabs(root, app)[0]
        app.notebook.select(tab)
        _settle(root, 5)
        cv = tab._canvas
        want = tab.body.winfo_reqwidth()
        assert want > cv.winfo_width(), (
            "window not narrow enough to exercise the bug")
        assert tab.body.winfo_width() >= want, (
            "LCR tab squeezed to %d px though it asked for %d -- the "
            "right-hand column is being clipped, not scrolled"
            % (tab.body.winfo_width(), want))
        config = app.lcr_speed.master        # the config LabelFrame
        cv.xview_moveto(1.0)
        _settle(root, 4)
        right = max(c.winfo_rootx() + c.winfo_width()
                    for c in config.winfo_children()) - cv.winfo_rootx()
        assert right <= cv.winfo_width() + 1, (
            "LCR right-hand column still off screen at a %d px window "
            "(right edge %d, canvas %d)"
            % (NARROW, right, cv.winfo_width()))
    finally:
        root.destroy()


def test_the_lcr_lower_controls_are_reachable():
    """`#26` as reported: the controls at the BOTTOM of the LCR tab, at a
    window short enough to cut them off.

    This one is a standing guard, not a bug-catcher -- it already passes
    against the pre-`#225` code, which is the measured evidence that
    `#26`'s vertical half was fixed by 8d494e8 and that nothing since has
    undone it. Reported vertical cut-offs from here on are new bugs.
    """
    root, app = _app()
    if root is None:
        return
    try:
        _name, tab = _tabs(root, app)[0]
        app.notebook.select(tab)
        _settle(root, 5)
        cv = tab._canvas
        assert tab.body.winfo_reqheight() > cv.winfo_height(), (
            "window not short enough to exercise the bug")
        bottom = max(c.winfo_rooty() + c.winfo_height()
                     for c in tab.body.winfo_children())
        assert bottom - cv.winfo_rooty() > cv.winfo_height(), (
            "expected the lower controls to start off screen")
        cv.yview_moveto(1.0)
        _settle(root, 4)
        bottom = max(c.winfo_rooty() + c.winfo_height()
                     for c in tab.body.winfo_children()) - cv.winfo_rooty()
        assert bottom <= cv.winfo_height() + 1, (
            "LCR lower controls still cut off after scrolling to the "
            "bottom (edge %d, canvas %d)" % (bottom, cv.winfo_height()))
    finally:
        root.destroy()


def test_the_manual_vocabulary_is_one_vocabulary():
    """Tab slugs, content.json keys and the manual's ids are ONE set.

    No display needed -- this is the half of the slug contract that can be
    checked anywhere, and it is the half that used to be checked nowhere:
    the manual's figures were named at capture time from each tab's DISPLAY
    LABEL plus its POSITION ("06_Data_Logging"), and every consumer
    hardcoded the result, so renaming or reordering a tab broke the manual
    build with no warning until someone next regenerated it.
    """
    import json
    import gui
    slugs = [s for s, _label, _builder in gui.MANUAL_TABS]
    assert len(set(slugs)) == len(slugs), f"duplicate tab slug: {slugs}"
    for slug in slugs:
        assert slug and slug.replace('-', '').isalnum() \
            and slug.lower() == slug, (
                f"{slug!r} is not a lowercase slug (it becomes a filename "
                "and an HTML anchor)")
    builders = [b for _s, _l, b in gui.MANUAL_TABS]
    missing = [b for b in builders
               if not hasattr(gui.InstrumentControlGUI, b)]
    assert not missing, f"MANUAL_TABS names no such builder(s): {missing}"

    here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    with open(_os.path.join(here, 'docs', 'manual-src', 'content.json'),
              encoding='utf-8') as fh:
        content = json.load(fh)
    for slug in slugs:
        assert slug in content, (
            f"tab {slug!r} has no docs/manual-src/content.json entry -- the "
            "manual would build a chapter-less tab")
    for key, sec in content.items():
        assert sec['key'] == key, (
            f"content.json {key!r} carries key={sec['key']!r}: the entry's "
            "own key field must be its slug, not its on-screen label")
    # The non-tab chapters. Spelled out so that dropping one is a failure
    # here rather than a silently shorter manual.
    assert set(content) == set(slugs) | {'start', 'arb', 'tools'}, sorted(
        set(content) ^ (set(slugs) | {'start', 'arb', 'tools'}))


def test_every_live_tab_carries_its_slug():
    """The other half: the real notebook, tagged, in order.

    docs/manual-src/capture.py names each screenshot `tab_<slug>` from this
    attribute and refuses to photograph a tab without one.
    """
    import gui
    root, app = _app()
    if root is None:
        return
    try:
        live = [getattr(root.nametowidget(tid), 'manual_slug', None)
                for tid in app.notebook.tabs()]
        assert live == [s for s, _l, _b in gui.MANUAL_TABS], (
            "notebook tabs do not carry MANUAL_TABS' slugs in order: %s"
            % (live,))
        for name, tab in _tabs(root, app):
            assert getattr(tab, 'manual_slug', None), (
                f"tab {name!r} carries no manual_slug")
        assert app.tab_widget('webcam') is not None, (
            "tab_widget() cannot find the webcam tab by slug")
        assert app.tab_widget('no-such-tab') is None
        assert app.select_manual_tab('webcam'), "select_manual_tab failed"
        assert app.notebook.select() == str(app.tab_widget('webcam'))
        assert not app.select_manual_tab('no-such-tab')
    finally:
        root.destroy()


def _run():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
