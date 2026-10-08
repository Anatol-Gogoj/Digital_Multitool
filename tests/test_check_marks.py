#!/usr/bin/env python3
"""Check marks in every checkbox (`#407`).

A ttk checkbox showed whatever the platform's theme draws: a check mark on
Windows, where the manual is captured, but a filled square in Tk's
'default' theme on the Linux bench. tk_checkmarks.install_check_marks swaps
the theme's indicator for drawn images on each Tk root. These tests pin
what the images are (a check mark, by shape, not only by color), that the
disabled boxes differ, that every window's root gets them, that a
checkbox keeps its size on the Windows theme, that the SLDEA tab's
classic DRY RUN box gets the same box, that a failure leaves the theme as
it was, and that the module imports nothing but tkinter, so the plot
window can use it without crossing the repo-split seam.

Run: .venv/bin/python tests/test_check_marks.py
"""
import os as _os
import sys as _sys
import tempfile
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import tk_checkmarks as uiw


class _Skip(Exception):
    """This test needs something the machine does not have."""


def _root():
    """A withdrawn Tk root, or _Skip when no display can be opened."""
    try:
        import tkinter as tk
    except ImportError as e:
        raise _Skip(f"no tkinter: {e}")
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    root.withdraw()
    return root


def _shut(root):
    """Cancel what is still scheduled, then destroy: a matplotlib idle
    draw left pending would print a Tcl error on its way out."""
    try:
        for job in root.tk.splitlist(root.tk.call('after', 'info')):
            root.tk.call('after', 'cancel', job)
        root.destroy()
    except Exception:
        pass


def _light(color):
    """True for a light pixel ('#rrggbb'): its luminance over half."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 127.5


def _inside(rows):
    """The rows without their one-pixel border (13 px boxes have one)."""
    b = max(1, int(round(len(rows) / 13.0)))
    return [row[b:-b] for row in rows[b:-b]]


def _mask(rows):
    """{(x, y)} of the light pixels inside the border."""
    return {(x, y) for y, row in enumerate(_inside(rows))
            for x, c in enumerate(row) if _light(c)}


def _marked(key, size=13):
    """{(x, y)} of the pixels inside the border that are not the fill:
    where the mark is drawn, whatever its contrast."""
    fill = _kind(key)[0].lower()
    return {(x, y) for y, row in enumerate(_inside(_rows(key, size)))
            for x, c in enumerate(row) if c.lower() != fill}


def _kind(key):
    for k, fill, edge, mark in uiw._CHECK_KINDS:
        if k == key:
            return fill, edge, mark
    raise KeyError(key)


def _rows(key, size=13):
    fill, edge, mark = _kind(key)
    return uiw.check_mark_rows(size, fill, edge, mark)


# ---- the images themselves, without Tk ----------------------------------

def test_a_ticked_box_holds_a_check_shape_and_an_unticked_one_is_empty():
    """Light against dark is what survives any color vision and a
    greyscale print, so the shapes are compared on luminance alone."""
    for size in (11, 13, 17, 26):
        inner = (size - 2 * max(1, int(round(size / 13.0)))) ** 2
        off, on = _mask(_rows('off', size)), _mask(_rows('on', size))
        assert len(off) == inner, (size, len(off), inner)
        assert 0.12 * inner <= len(on) <= 0.45 * inner, (size, len(on))
        # a check, not a blob: its light pixels reach the lower middle
        # (the vertex) and the top right (the long stroke's end), and
        # leave the top left and the bottom right dark
        side = int(inner ** 0.5)
        third = side // 3
        assert any(x >= side - third and y <= third for x, y in on), size
        assert any(third <= x < side - third and y >= side - third
                   for x, y in on), size
        assert not any(x < third and y < third for x, y in on), size
        assert not any(x >= side - third and y >= side - third
                       for x, y in on), size
        # and the two masks share little: the shape, not only the
        # color, tells ticked from unticked
        jaccard = len(off & on) / float(len(off | on))
        assert jaccard < 0.5, (size, jaccard)


def test_the_alternate_box_holds_a_dash_not_a_check():
    for size in (13, 26):
        dash, check = _mask(_rows('alt', size)), _mask(_rows('on', size))
        rows = {y for _x, y in dash}
        cols = {x for x, _y in dash}
        assert dash and len(rows) <= max(3, size // 4), (size, sorted(rows))
        assert len(cols) >= 2 * len(rows), (size, len(cols), len(rows))
        assert dash != check


def test_the_disabled_boxes_differ_from_the_enabled_ones():
    for enabled, disabled in (('off', 'off_disabled'), ('on', 'on_disabled'),
                              ('alt', 'alt_disabled')):
        assert _rows(enabled) != _rows(disabled), (enabled, disabled)
    # a disabled ticked box still carries the same check, drawn where
    # the enabled one is (its white on the light grey is fainter, as a
    # disabled control is)
    assert _marked('on_disabled') == _marked('on')
    assert _marked('on') and not _marked('off')
    # and its fill and edge are the Tol grey, not the Tol blue
    fill, edge, _mark = _kind('on_disabled')
    assert fill == uiw.CHECK_DISABLED == '#BBBBBB' and edge == fill
    assert _kind('on')[0] == uiw.CHECK_TICKED == '#4477AA'


def test_the_module_imports_nothing_but_tkinter():
    """Like tk_fontfix and tk_stall it sits on both sides of the
    open-decision-2 repo split: the plot window may not import ui_widgets
    (test_sldea_plot_gui pins that), so the helper cannot live there."""
    import re
    src = open(uiw.__file__, encoding='utf-8').read()
    mods = re.findall(r'(?m)^\s*(?:from\s+(\S+)\s+import|import\s+(\S+))', src)
    names = {a or b for a, b in mods}
    assert names <= {'tkinter', 'tkinter.font', 'tkinter.ttk'}, names


# ---- on a Tk root -------------------------------------------------------

def test_the_helper_installs_on_a_root_once():
    root = _root()
    try:
        from tkinter import ttk
        style = ttk.Style(root)
        assert uiw.CHECK_ELEMENT not in style.element_names()
        images = uiw.install_check_marks(root)
        assert images and set(images) == {k for k, *_ in uiw._CHECK_KINDS}
        assert uiw.CHECK_ELEMENT in style.element_names()
        names = []

        def walk(layout):
            for name, opts in layout:
                names.append(name)
                walk(opts.get('children', []))
        walk(style.layout('TCheckbutton'))
        assert uiw.CHECK_ELEMENT in names, names
        assert [n for n in names if n.endswith('indicator')] == \
            [uiw.CHECK_ELEMENT], names
        # the images live in this root's interpreter and are kept on it
        made = set(root.image_names())
        assert all(str(img) in made for img in images.values())
        assert root._ui_check_marks is images
        # a second call in the same interpreter changes nothing
        assert uiw.install_check_marks(root) is images
        assert uiw.install_check_marks(ttk.Frame(root)) is images
    finally:
        _shut(root)


def test_the_images_are_the_rows_with_rounded_corners():
    root = _root()
    try:
        images = uiw.install_check_marks(root)
        size = uiw.check_mark_size(root)
        for key, img in images.items():
            assert (img.width(), img.height()) == (size, size), key
            rows = _rows(key, size)
            mid = size // 2
            want = rows[mid][mid]
            got = '#%02x%02x%02x' % img.get(mid, mid)
            assert got == want.lower(), (key, got, want)
            assert img.transparency_get(0, 0), key
            assert not img.transparency_get(mid, mid), key
    finally:
        _shut(root)


def test_the_size_follows_the_default_font():
    root = _root()
    try:
        import tkinter.font as tkfont
        font = tkfont.nametofont('TkDefaultFont', root=root)
        sizes = []
        for pt in (9, 18):
            font.configure(size=pt)
            line = font.metrics('linespace')
            got = uiw.check_mark_size(root)
            assert got == max(11, int(round(line * 13 / 15.0))), (pt, got)
            sizes.append(got)
        assert sizes[1] > sizes[0], sizes
    finally:
        _shut(root)


def test_a_checkbox_keeps_its_size():
    """On the Windows theme the drawn box takes exactly the native
    indicator's room (13 + 4 px at 96 dpi), so no layout moves; on any
    theme the height holds, because the box is shorter than a text line."""
    root = _root()
    try:
        import tkinter as tk
        from tkinter import ttk
        root.tk.call('tk', 'scaling', 96.0 / 72.0)
        style = ttk.Style(root)
        var = tk.BooleanVar(root, value=True)

        def size_of(text):
            cb = ttk.Checkbutton(root, text=text, variable=var)
            cb.pack()
            root.update_idletasks()
            out = (cb.winfo_reqwidth(), cb.winfo_reqheight())
            cb.destroy()
            return out
        texts = ('Enabled', 'Up/down (hysteresis)', '')
        before = [size_of(t) for t in texts]
        assert uiw.install_check_marks(root)
        after = [size_of(t) for t in texts]
        assert [h for _w, h in after] == [h for _w, h in before], \
            (before, after)
        if style.theme_use() == 'vista':
            assert after == before, (before, after)
        else:
            for (wb, _hb), (wa, _ha) in zip(before, after):
                assert 0 <= wa - wb <= 8, (style.theme_use(), before, after)
    finally:
        _shut(root)


def test_a_classic_checkbutton_gets_the_box_and_keeps_its_size():
    """The SLDEA tab's DRY RUN box is a classic tk.Checkbutton. Its X11
    indicator is a square filled with selectcolor, its own background, so
    DRY and LIVE drew the same square."""
    root = _root()
    try:
        import tkinter as tk
        var = tk.BooleanVar(root, value=True)
        cb = tk.Checkbutton(root, text="DRY RUN — HV OFF", variable=var,
                            font=('TkDefaultFont', 10, 'bold'),
                            indicatoron=True, padx=6)
        cb.config(bg='#fff3cd', fg='#8a5a00', selectcolor='#fff3cd')
        cb.pack()
        root.update_idletasks()
        before = (cb.winfo_reqwidth(), cb.winfo_reqheight())
        assert uiw.mark_classic_checkbutton(cb)
        root.update_idletasks()
        after = (cb.winfo_reqwidth(), cb.winfo_reqheight())
        images = root._ui_check_marks
        assert not int(cb.cget('indicatoron'))
        assert int(cb.cget('borderwidth')) == 0
        assert str(cb.cget('compound')) == 'left'
        off, on = str(cb.cget('image')), str(cb.cget('selectimage'))
        assert off and on and off != on
        # the images it shows carry the drawn boxes
        img_off = images['off']
        assert root.tk.call(off, 'get', 6, 6) == \
            root.tk.call(str(img_off), 'get', 6, 6)
        assert root.tk.call(on, 'get', 6, 6) == \
            root.tk.call(str(images['on']), 'get', 6, 6)
        assert after[1] == before[1], (before, after)
        if _sys.platform == 'win32':
            assert after == before, (before, after)
        else:
            assert after[0] >= before[0], (before, after)
    finally:
        _shut(root)


def test_a_layout_with_no_indicator_or_a_tk_error_changes_nothing():
    """A checkbox the theme draws is better than a window that does not
    open: any failure returns None and leaves the style alone."""
    root = _root()
    try:
        from tkinter import ttk
        style = ttk.Style(root)
        plain = [('Checkbutton.focus',
                  {'children': [('Checkbutton.label', {'sticky': 'nswe'})]})]
        style.layout('TCheckbutton', plain)
        expected = style.layout('TCheckbutton')
        assert uiw.install_check_marks(root) is None
        assert uiw.CHECK_ELEMENT not in style.element_names()
        assert style.layout('TCheckbutton') == expected
    finally:
        _shut(root)
    root = _root()
    import tkinter as tk
    saved = tk.PhotoImage

    def broken(*a, **k):
        raise tk.TclError("no images today")
    try:
        from tkinter import ttk
        before = ttk.Style(root).layout('TCheckbutton')
        uiw.tk.PhotoImage = broken
        assert uiw.install_check_marks(root) is None
        assert ttk.Style(root).layout('TCheckbutton') == before
    finally:
        uiw.tk.PhotoImage = saved
        _shut(root)


def _installed(root):
    from tkinter import ttk
    return (uiw.CHECK_ELEMENT in ttk.Style(root).element_names()
            and getattr(root, '_ui_check_marks', None) is not None)


def test_every_window_installs_them_on_its_root():
    """The main window (with the DRY RUN box), Edge Review, the plot
    window, the tuner and the video review each install the marks on the
    root they are given, before their first widget."""
    from tkinter import messagebox, filedialog
    saved_mb = {n: getattr(messagebox, n) for n in
                ('showinfo', 'showwarning', 'showerror', 'askyesno')}
    saved_fd = {n: getattr(filedialog, n) for n in
                ('askopenfilename', 'askdirectory')}
    for n in saved_mb:
        setattr(messagebox, n, lambda *a, **k: False)
    for n in saved_fd:
        setattr(filedialog, n, lambda *a, **k: '')
    tmp = tempfile.mkdtemp(prefix='checkmarks_')
    try:
        # the main window
        root = _root()
        try:
            import gui
            saved = gui.InstrumentControlGUI.auto_connect
            gui.InstrumentControlGUI.auto_connect = lambda self: None
            # the window's own call, on its root, before any tab is built:
            # the DRY RUN box's mark_classic_checkbutton would install them
            # too, later, so _installed alone cannot tell the two apart
            real, calls = gui.install_check_marks, []
            gui.install_check_marks = \
                lambda master: (calls.append(master), real(master))[1]
            try:
                app = gui.InstrumentControlGUI(root)
            finally:
                gui.InstrumentControlGUI.auto_connect = saved
                gui.install_check_marks = real
            assert calls and calls[0] is root, calls
            assert _installed(root), 'main window'
            images = root._ui_check_marks
            cb = app.sldea_dry_cb
            assert not int(cb.cget('indicatoron'))
            assert str(cb.cget('selectimage')) and \
                str(cb.cget('selectimage')) != str(cb.cget('image'))
            on = str(cb.cget('selectimage'))
            assert root.tk.call(on, 'get', 6, 6) == \
                root.tk.call(str(images['on']), 'get', 6, 6)
        finally:
            _shut(root)
        # Edge Review on an empty folder
        root = _root()
        try:
            import sldea_edge_gui as eg
            eg.EdgeReviewApp(root, path=tmp)
            assert _installed(root), 'Edge Review'
        finally:
            _shut(root)
        # the plot window on an empty folder
        root = _root()
        try:
            import sldea_plot_gui as pg
            pg.PlotWindow(root, tmp, remember=False)
            assert _installed(root), 'plot window'
        finally:
            _shut(root)
        # the tuner on an empty folder

        class _MB:
            def __getattr__(self, name):
                return lambda *a, **k: None
        root = _root()
        try:
            import sldea_tuner as st
            st.TunerWindow(root, parent=tmp, messagebox=_MB())
            assert _installed(root), 'tuner'
        finally:
            _shut(root)
        # the video review: it installs before it reads the run, so a
        # folder with no video (which makes it raise) still shows it
        root = _root()
        try:
            import sldea_video_review as vr
            try:
                vr.VideoReviewWindow(root, tmp)
            except Exception:
                pass
            assert _installed(root), 'video review'
        finally:
            _shut(root)
    finally:
        for n, f in saved_mb.items():
            setattr(messagebox, n, f)
        for n, f in saved_fd.items():
            setattr(filedialog, n, f)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    try:
        _sys.stdout.reconfigure(errors='backslashreplace')
    except AttributeError:
        pass
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    ran = skipped = 0
    failed = []
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
    tail = f"{ran} of {len(names)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped, see above)"
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
