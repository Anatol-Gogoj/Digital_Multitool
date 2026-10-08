#!/usr/bin/env python3
"""A check mark in every checkbox, on every platform (#407).

A ttk checkbox shows whatever the platform's theme draws. Windows' theme
draws a check mark, and the manual is captured on Windows; Tk's 'default'
theme, which the Linux bench uses, draws a filled square for ticked and an
empty one for unticked, hard to read at a glance. The images drawn here
replace the theme's indicator, so a tick is a check mark everywhere and
the bench looks like the manual. The shape carries the meaning; the fill
repeats it.

Call install_check_marks(root) once per Tk root, before the window's first
widget, and mark_classic_checkbutton(cb) on a classic tk.Checkbutton.

This module imports only tkinter, like tk_fontfix and tk_stall, so every
window may use it: the plot window must not import ui_widgets, which is on
the other side of the open-decision-2 repo split.
"""
import tkinter as tk
from tkinter import ttk

CHECK_ELEMENT = 'Mark.indicator'
CHECK_TICKED = '#4477AA'     # Paul Tol bright blue: a ticked box
CHECK_DISABLED = '#BBBBBB'   # Paul Tol bright grey: a disabled box
CHECK_EDGE = '#444444'       # an unticked box's edge
CHECK_EMPTY = '#FFFFFF'      # an unticked box's inside, and the mark
CHECK_DISABLED_EMPTY = '#F2F2F2'

# The mark, in units of the box's inside: a check through three points,
# and the dash of an alternate (mixed) state.
_CHECK_POINTS = ((0.17, 0.52), (0.40, 0.75), (0.84, 0.25))
_DASH_POINTS = ((0.22, 0.5), (0.78, 0.5))


def check_mark_size(master):
    """The box's side in pixels: 13/15 of the default font's line height,
    the proportion of the Windows box at Segoe UI 9 (13 px on a 15 px
    line), so it follows the font scaling the app runs at. Never under
    11 px."""
    import tkinter.font as tkfont
    try:
        line = tkfont.nametofont('TkDefaultFont',
                                 root=master).metrics('linespace')
    except (tk.TclError, TypeError):
        line = 15
    return max(11, int(round(line * 13 / 15.0)))


def _mark_coverage(px, py, points, half):
    """How much of pixel (px, py) the polyline `points`, `half` wide on
    each side, covers: 4 x 4 samples, so the mark's edges are smooth."""
    hit = 0
    for i in range(4):
        for j in range(4):
            x, y = px + (i + 0.5) / 4.0, py + (j + 0.5) / 4.0
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                dx, dy = x1 - x0, y1 - y0
                t = ((x - x0) * dx + (y - y0) * dy) / float(dx * dx + dy * dy)
                t = min(1.0, max(0.0, t))
                ex, ey = x0 + t * dx - x, y0 + t * dy - y
                if ex * ex + ey * ey <= half * half:
                    hit += 1
                    break
    return hit / 16.0


def _blend(a, b, k):
    """Color `a` moved a fraction `k` of the way to `b` ('#rrggbb')."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(int(round(x + (y - x) * k))
                                   for x, y in zip(ca, cb))


def check_mark_rows(size, fill, edge, mark=None):
    """The box as rows of '#rrggbb' strings, `size` pixels square: an
    `edge` border, a `fill` inside, and a white `mark` ('check', 'dash' or
    None) drawn on the inside. Pure Python, so it is testable without Tk."""
    border = max(1, int(round(size / 13.0)))
    inner = size - 2 * border
    points = None
    if mark is not None:
        unit = _CHECK_POINTS if mark == 'check' else _DASH_POINTS
        points = [(border + x * inner, border + y * inner) for x, y in unit]
    half = max(0.75, 0.075 * inner)
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            if (x < border or y < border or x >= size - border
                    or y >= size - border):
                row.append(edge)
                continue
            color = fill
            if points is not None:
                k = _mark_coverage(x, y, points, half)
                if k:
                    color = _blend(fill, CHECK_EMPTY, k)
            row.append(color)
        rows.append(row)
    return rows


# (key, inside, edge, mark) for every image the element uses
_CHECK_KINDS = (
    ('off', CHECK_EMPTY, CHECK_EDGE, None),
    ('off_hover', CHECK_EMPTY, CHECK_TICKED, None),
    ('on', CHECK_TICKED, CHECK_TICKED, 'check'),
    ('alt', CHECK_TICKED, CHECK_TICKED, 'dash'),
    ('off_disabled', CHECK_DISABLED_EMPTY, CHECK_DISABLED, None),
    ('on_disabled', CHECK_DISABLED, CHECK_DISABLED, 'check'),
    ('alt_disabled', CHECK_DISABLED, CHECK_DISABLED, 'dash'),
)


def _check_image(master, rows):
    """A PhotoImage of `rows`, made in `master`'s interpreter, with its
    four corner pixels clear so the box reads slightly rounded."""
    size = len(rows)
    img = tk.PhotoImage(master=master, width=size, height=size)
    img.put(' '.join('{' + ' '.join(r) + '}' for r in rows), to=(0, 0))
    if size >= 12:
        for x, y in ((0, 0), (size - 1, 0), (0, size - 1),
                     (size - 1, size - 1)):
            img.transparency_set(x, y, True)
    return img


def _swap_indicator(layout, element):
    """`layout` (a ttk layout list) with every '*indicator' element
    replaced by `element`; True in the second item when one was found."""
    out, found = [], False
    for name, opts in layout:
        opts = dict(opts)
        if 'children' in opts:
            opts['children'], sub = _swap_indicator(opts['children'],
                                                    element)
            found = found or sub
        if name.endswith('indicator'):
            name, found = element, True
        out.append((name, opts))
    return out, found


def install_check_marks(master):
    """Make every ttk checkbox in `master`'s Tk interpreter draw its box
    with the images above, and return them as {key: PhotoImage}.

    The images become an element of the current theme, CHECK_ELEMENT, and
    the TCheckbutton layout uses it in place of the theme's own indicator;
    styles derived from TCheckbutton follow it. Call it once per Tk root,
    before the window's first widget; a second call in the same
    interpreter returns the first call's images. The images are kept on
    the root, so Tk never loses them while the window lives. On any Tk
    error it changes nothing and returns None: a checkbox drawn by the
    theme is better than a window that does not open."""
    try:
        root = master._root()
        made = getattr(root, '_ui_check_marks', None)
        style = ttk.Style(master)
        if made and CHECK_ELEMENT in style.element_names():
            return made
        size = check_mark_size(master)
        images = {key: _check_image(master,
                                    check_mark_rows(size, fill, edge, mark))
                  for key, fill, edge, mark in _CHECK_KINDS}
        layout, found = _swap_indicator(style.layout('TCheckbutton'),
                                        CHECK_ELEMENT)
        if not found:
            return None
        # The element is as wide as the box plus the gap before the label,
        # the box held left, as the Windows indicator is (13 + 4 px at
        # 96 dpi), so a checkbox there keeps its size to the pixel. An
        # image element's padding would not add to its size.
        gap = max(2, int(round(size * 4 / 13.0)))
        style.element_create(
            CHECK_ELEMENT, 'image', images['off'],
            ('disabled', 'selected', images['on_disabled']),
            ('disabled', 'alternate', images['alt_disabled']),
            ('disabled', images['off_disabled']),
            ('selected', images['on']),
            ('alternate', images['alt']),
            ('active', images['off_hover']),
            width=size + gap, sticky='w')
        style.layout('TCheckbutton', layout)
        root._ui_check_marks = images
        return images
    except (tk.TclError, AttributeError, ValueError):
        return None


def mark_classic_checkbutton(cb):
    """Give a classic tk.Checkbutton the same drawn box as the ttk ones:
    the images in place of its indicator, which on X11 is a square filled
    with `selectcolor` (on the SLDEA tab's DRY RUN box that color is the
    background, so ticked and unticked looked alike). With indicatoron off,
    Tk shows `selectcolor` behind the whole widget while it is ticked and
    draws a ticked one sunken, so the border goes to keep its flat look,
    and comes back as padding, so its size holds. With an image Tk also
    puts padx between the image and the text, so padding alone can miss
    the width by a pixel or two; clear columns on the images' right make
    up the rest. -> True when the images were applied."""
    images = install_check_marks(cb)
    if not images:
        return False
    try:
        width = cb.winfo_reqwidth()
        border = int(cb.cget('borderwidth'))
        cb.configure(image=images['off'], selectimage=images['on'],
                     compound='left', indicatoron=False, borderwidth=0,
                     padx=int(cb.cget('padx')) + (border + 1) // 2,
                     pady=int(cb.cget('pady')) + border)
        short = width - cb.winfo_reqwidth()
        if short > 0:
            off, on = (_widened(cb, images[k], short) for k in ('off', 'on'))
            cb._ui_check_images = (off, on)     # Tk keeps only the names
            cb.configure(image=off, selectimage=on)
    except (tk.TclError, ValueError):
        return False
    return True


def _widened(master, img, extra):
    """A copy of `img` with `extra` clear columns on its right."""
    wide = tk.PhotoImage(master=master, width=img.width() + extra,
                         height=img.height())
    wide.tk.call(str(wide), 'copy', str(img))
    return wide
