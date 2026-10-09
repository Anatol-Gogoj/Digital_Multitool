#!/usr/bin/env python3
"""A drawn dot in every radio button (`#421`).

On the Linux bench's ttk theme a radio button is a bare diamond, filled
when selected and empty when not, the at-a-glance problem #407 fixed for
checkboxes; a classic tk.Radiobutton on X11 is a diamond filled with its
selectcolor. tk_checkmarks.install_radio_marks swaps the theme's radio
indicator for drawn images (a ring, and a ring with a dot when selected),
and install_check_marks calls it, so every window that installs the check
marks gets the rings too. These tests pin what the images are (a dot, by
shape, not only by color), that the disabled rings differ, that outside
the circle stays clear, that a radio button keeps its size, that Edge
Review's classic radios get the same ring without turning X11's dark red
when selected, that a failure leaves the theme as it was, and that every
window's root gets them.

Run: .venv/bin/python tests/test_radio_marks.py
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
    """Cancel what is still scheduled, then destroy."""
    try:
        for job in root.tk.splitlist(root.tk.call('after', 'info')):
            root.tk.call('after', 'cancel', job)
        root.destroy()
    except Exception:
        pass


def _kind(key):
    for k, inside, ring, dot in uiw._RADIO_KINDS:
        if k == key:
            return inside, ring, dot
    raise KeyError(key)


def _rows(key, size=13, bg='#f0f0f0'):
    inside, ring, dot = _kind(key)
    return uiw.radio_mark_rows(size, inside, ring, dot, bg)


def _dark(color):
    """True for a dark pixel ('#rrggbb'): its luminance under half."""
    r, g, b = uiw._rgb(color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b < 127.5


def _core(rows):
    """{(x, y)} of the dark pixels well inside the ring: within 0.35 of
    the image's side from its centre, where only a dot can be."""
    size = len(rows)
    c = (size - 1) / 2.0
    return {(x, y) for y, row in enumerate(rows) for x, col in enumerate(row)
            if col is not None and ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            <= 0.35 * size and _dark(col)}


def _ring(rows):
    """{(x, y)} of the dark pixels near the rim."""
    size = len(rows)
    c = (size - 1) / 2.0
    return {(x, y) for y, row in enumerate(rows) for x, col in enumerate(row)
            if col is not None and ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            >= 0.40 * size and _dark(col)}


# ---- the images themselves, without Tk ----------------------------------

def test_a_selected_radio_holds_a_dot_and_an_unselected_one_is_empty():
    """Dark against light is what survives any color vision and a
    greyscale print, so the shapes are compared on luminance alone."""
    for size in (11, 13, 17, 26):
        off, on = _rows('off', size), _rows('on', size)
        dot = _core(on)
        assert not _core(off), (size, sorted(_core(off)))
        # a filled disc around the centre, not a speck
        assert len(dot) >= max(5, int(0.10 * size * size)), (size, len(dot))
        c = size // 2
        assert (c, c) in dot, size
        # both draw a ring the pointer can find, all the way round
        for rows in (off, on):
            ring = _ring(rows)
            quadrants = {(x >= size / 2.0, y >= size / 2.0) for x, y in ring}
            assert len(quadrants) == 4, (size, quadrants)


def test_outside_the_circle_is_clear_and_the_rim_is_blended():
    for size in (13, 26):
        rows = _rows('off', size)
        for x, y in ((0, 0), (size - 1, 0), (0, size - 1),
                     (size - 1, size - 1)):
            assert rows[y][x] is None, (size, x, y)
        assert all(c is not None for c in rows[size // 2]), size
    # a rim pixel the circle only partly covers leans toward the background
    a = uiw.radio_mark_rows(13, '#FFFFFF', '#444444', None, '#000000')
    b = uiw.radio_mark_rows(13, '#FFFFFF', '#444444', None, '#FFFFFF')
    differs = [(x, y) for y in range(13) for x in range(13)
               if a[y][x] is not None and a[y][x] != b[y][x]]
    assert differs, "the rim ignores the background"
    assert a[6][6] == b[6][6] == '#ffffff', (a[6][6], b[6][6])


def test_the_disabled_radios_differ_from_the_enabled_ones():
    for enabled, disabled in (('off', 'off_disabled'), ('on', 'on_disabled')):
        assert _rows(enabled) != _rows(disabled), (enabled, disabled)
    # a disabled selected radio still carries its dot, in the Tol grey
    inside, ring, dot = _kind('on_disabled')
    assert dot == ring == uiw.CHECK_DISABLED == '#BBBBBB'
    assert _kind('on')[2] == uiw.CHECK_TICKED == '#4477AA'
    c = 6
    assert _rows('on_disabled')[c][c].lower() == '#bbbbbb'
    assert _rows('off_disabled')[c][c].lower() == inside.lower()


def test_the_module_still_imports_nothing_but_tkinter():
    import re
    src = open(uiw.__file__, encoding='utf-8').read()
    mods = re.findall(r'(?m)^\s*(?:from\s+(\S+)\s+import|import\s+(\S+))', src)
    names = {a or b for a, b in mods}
    assert names <= {'tkinter', 'tkinter.font', 'tkinter.ttk'}, names


# ---- on a Tk root -------------------------------------------------------

def _names(layout, out):
    for name, opts in layout:
        out.append(name)
        _names(opts.get('children', []), out)
    return out


def test_the_helper_installs_on_a_root_once_and_with_the_check_marks():
    root = _root()
    try:
        from tkinter import ttk
        style = ttk.Style(root)
        assert uiw.RADIO_ELEMENT not in style.element_names()
        images = uiw.install_radio_marks(root)
        assert images and set(images) == {k for k, *_ in uiw._RADIO_KINDS}
        names = _names(style.layout('TRadiobutton'), [])
        assert [n for n in names if n.endswith('indicator')] == \
            [uiw.RADIO_ELEMENT], names
        made = set(root.image_names())
        assert all(str(img) in made for img in images.values())
        assert root._ui_radio_marks is images
        assert uiw.install_radio_marks(root) is images
        assert uiw.install_radio_marks(ttk.Frame(root)) is images
    finally:
        _shut(root)
    # install_check_marks, the call every window already makes, brings them
    root = _root()
    try:
        from tkinter import ttk
        assert uiw.install_check_marks(root)
        assert uiw.RADIO_ELEMENT in ttk.Style(root).element_names()
        assert getattr(root, '_ui_radio_marks', None)
    finally:
        _shut(root)


def test_the_images_are_the_rows_with_the_corners_clear():
    root = _root()
    try:
        from tkinter import ttk
        images = uiw.install_radio_marks(root)
        size = uiw.check_mark_size(root)
        bg = uiw._theme_background(root, ttk.Style(root))
        for key, img in images.items():
            assert (img.width(), img.height()) == (size, size), key
            rows = _rows(key, size, bg)
            mid = size // 2
            got = '#%02x%02x%02x' % img.get(mid, mid)
            assert got == rows[mid][mid].lower(), (key, got, rows[mid][mid])
            assert img.transparency_get(0, 0), key
            assert not img.transparency_get(mid, mid), key
    finally:
        _shut(root)


def test_a_radio_button_keeps_its_size():
    """On the Windows theme the drawn ring takes exactly the native
    indicator's room (13 + 4 px at 96 dpi); on any theme the height holds."""
    root = _root()
    try:
        import tkinter as tk
        from tkinter import ttk
        root.tk.call('tk', 'scaling', 96.0 / 72.0)
        style = ttk.Style(root)
        var = tk.StringVar(root, value='a')

        def size_of(text, value):
            rb = ttk.Radiobutton(root, text=text, variable=var, value=value)
            rb.pack()
            root.update_idletasks()
            out = (rb.winfo_reqwidth(), rb.winfo_reqheight())
            rb.destroy()
            return out
        cases = (('kV', 'a'), ('elapsed time', 'b'), ('', 'a'))
        before = [size_of(*c) for c in cases]
        assert uiw.install_radio_marks(root)
        after = [size_of(*c) for c in cases]
        assert [h for _w, h in after] == [h for _w, h in before], \
            (before, after)
        if style.theme_use() == 'vista':
            assert after == before, (before, after)
        else:
            for (wb, _hb), (wa, _ha) in zip(before, after):
                assert abs(wa - wb) <= 8, (style.theme_use(), before, after)
    finally:
        _shut(root)


def test_a_classic_radiobutton_gets_the_ring_and_keeps_its_size():
    """Edge Review's candidate and calibration-mode radios are classic
    tk.Radiobuttons. With indicatoron off, Tk paints a selected radio in
    selectcolor (#b03060, a dark red, by default on X11), so the helper
    gives it the radio's own background."""
    root = _root()
    try:
        import tkinter as tk
        var = tk.IntVar(root, value=0)
        rbs, before = [], []
        for k, text in enumerate(("A: disc-fit  123456 px²  conf 0.97",
                                  "B · BY HAND: fit a circle")):
            rb = tk.Radiobutton(root, text=text, variable=var, value=k,
                                anchor='w', selectcolor='#b03060')
            rb.pack(fill='x')
            rbs.append(rb)
        root.update_idletasks()
        before = [(rb.winfo_reqwidth(), rb.winfo_reqheight()) for rb in rbs]
        for rb in rbs:
            assert uiw.mark_classic_radiobutton(rb)
        root.update_idletasks()
        after = [(rb.winfo_reqwidth(), rb.winfo_reqheight()) for rb in rbs]
        images = root._ui_radio_marks
        for rb in rbs:
            assert not int(rb.cget('indicatoron'))
            assert int(rb.cget('borderwidth')) == 0
            assert str(rb.cget('compound')) == 'left'
            assert str(rb.cget('selectcolor')) == str(rb.cget('background'))
            off, on = str(rb.cget('image')), str(rb.cget('selectimage'))
            assert off and on and off != on
            mid = images['on'].width() // 2
            assert root.tk.call(on, 'get', mid, mid) == \
                root.tk.call(str(images['on']), 'get', mid, mid)
            assert root.tk.call(off, 'get', mid, mid) == \
                root.tk.call(str(images['off']), 'get', mid, mid)
        assert [h for _w, h in after] == [h for _w, h in before], \
            (before, after)
        if _sys.platform == 'win32':
            assert after == before, (before, after)
        else:
            assert all(wa >= wb for (wa, _), (wb, _) in zip(after, before))
        # selecting works as before
        rbs[1].invoke()
        assert var.get() == 1
    finally:
        _shut(root)


def test_a_classic_radiobutton_with_sizes_in_units_is_marked():
    """#448: the same Tcl 'pixel object' trap as the classic checkbutton.
    Edge Review's candidate radios must get their ring when the bench's
    defaults give borderwidth, padx and pady in points."""
    root = _root()
    try:
        import tkinter as tk
        var = tk.StringVar(root, value='a')
        rb = tk.Radiobutton(root, text="candidate", variable=var, value='a',
                            indicatoron=True, borderwidth='1p', padx='3p',
                            pady='1p')
        rb.pack()
        root.update_idletasks()
        assert type(rb.cget('borderwidth')).__name__ == 'Tcl_Obj', (
            "this Tk returns plain ints for unit sizes; the test cannot "
            "reproduce the bench")
        border = rb.winfo_pixels('1p')
        padx, pady = rb.winfo_pixels('3p'), rb.winfo_pixels('1p')
        assert uiw.mark_classic_radiobutton(rb)
        assert rb.winfo_pixels(rb.cget('borderwidth')) == 0
        assert rb.winfo_pixels(rb.cget('padx')) == padx + (border + 1) // 2
        assert rb.winfo_pixels(rb.cget('pady')) == pady + border
        assert str(rb.cget('image')) and str(rb.cget('selectimage'))
    finally:
        _shut(root)


def test_a_layout_with_no_indicator_or_a_tk_error_changes_nothing():
    root = _root()
    try:
        from tkinter import ttk
        style = ttk.Style(root)
        plain = [('Radiobutton.focus',
                  {'children': [('Radiobutton.label', {'sticky': 'nswe'})]})]
        style.layout('TRadiobutton', plain)
        expected = style.layout('TRadiobutton')
        assert uiw.install_radio_marks(root) is None
        assert uiw.RADIO_ELEMENT not in style.element_names()
        assert style.layout('TRadiobutton') == expected
    finally:
        _shut(root)
    root = _root()
    import tkinter as tk
    saved = tk.PhotoImage

    def broken(*a, **k):
        raise tk.TclError("no images today")
    try:
        from tkinter import ttk
        before = ttk.Style(root).layout('TRadiobutton')
        uiw.tk.PhotoImage = broken
        assert uiw.install_radio_marks(root) is None
        assert ttk.Style(root).layout('TRadiobutton') == before
        rb = tk.Radiobutton(root, text='x')
        assert uiw.mark_classic_radiobutton(rb) is False
        assert int(rb.cget('indicatoron'))
    finally:
        uiw.tk.PhotoImage = saved
        _shut(root)


def _installed(root):
    from tkinter import ttk
    return (uiw.RADIO_ELEMENT in ttk.Style(root).element_names()
            and getattr(root, '_ui_radio_marks', None) is not None)


def test_every_window_installs_the_rings_on_its_root():
    """The main window (LCR sweep, Continuous Logging and Battery radios),
    Edge Review (with its classic candidate radios marked), the plot
    window (mode and x-axis radios), the tuner and the video review."""
    from tkinter import messagebox, filedialog
    saved_mb = {n: getattr(messagebox, n) for n in
                ('showinfo', 'showwarning', 'showerror', 'askyesno')}
    saved_fd = {n: getattr(filedialog, n) for n in
                ('askopenfilename', 'askdirectory')}
    for n in saved_mb:
        setattr(messagebox, n, lambda *a, **k: False)
    for n in saved_fd:
        setattr(filedialog, n, lambda *a, **k: '')
    tmp = tempfile.mkdtemp(prefix='radiomarks_')
    try:
        root = _root()
        try:
            import gui
            saved = gui.InstrumentControlGUI.auto_connect
            gui.InstrumentControlGUI.auto_connect = lambda self: None
            try:
                gui.InstrumentControlGUI(root)
            finally:
                gui.InstrumentControlGUI.auto_connect = saved
            assert _installed(root), 'main window'
        finally:
            _shut(root)
        root = _root()
        try:
            import sldea_edge_gui as eg
            app = eg.EdgeReviewApp(root, path=tmp)
            assert _installed(root), 'Edge Review'
            assert app.cand_radios
            for rb in app.cand_radios:
                assert not int(rb.cget('indicatoron')), 'candidate radio'
                assert str(rb.cget('selectcolor')) == \
                    str(rb.cget('background'))
                assert str(rb.cget('selectimage')) != str(rb.cget('image'))
        finally:
            _shut(root)
        root = _root()
        try:
            import sldea_plot_gui as pg
            pg.PlotWindow(root, tmp, remember=False)
            assert _installed(root), 'plot window'
        finally:
            _shut(root)

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
    # Failures are collected, not fatal (`#280`): every test runs, each
    # failure's traceback is printed after the count line, in name order,
    # in one bounded block -- run_tests.py explains why.
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
