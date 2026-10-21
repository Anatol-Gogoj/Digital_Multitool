#!/usr/bin/env python3
"""Small reusable Tk UI helpers: hover tooltips and scrollable tabs.

Both address long-standing GUI complaints (2026-07-10): content taller
than the window was simply CUT OFF with no scrollbar, and none of the
controls explained themselves (e.g. the LCR Speed/Avg fields).

The Usage Tips window every instrument tab opens (#480) is here too, after
the scrollable tabs; its words are in usage_tips.py.

The output-folder pickers' Browse and New folder... buttons (#394) live
here too, at the end; their decisions are in output_folder.py.
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter import font as tkfont

import output_folder
import ui_colors as uc


class Tooltip:
    """Show `text` in a small popup after hovering `widget` for `delay` ms.

    Tk has no built-in tooltip; this is the standard Toplevel +
    overrideredirect pattern. Hides on leave/click/destroy.
    """

    def __init__(self, widget, text, delay=650, wraplength=340):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self._after_id = None
        self._tip = None
        widget.bind('<Enter>', self._schedule, add='+')
        widget.bind('<Leave>', self._hide, add='+')
        widget.bind('<ButtonPress>', self._hide, add='+')
        widget.bind('<Destroy>', self._hide, add='+')

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 14
            y = (self.widget.winfo_rooty()
                 + self.widget.winfo_height() + 6)
        except tk.TclError:      # widget died while the timer was pending
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f'+{x}+{y}')
        tk.Label(tip, text=self.text, justify='left',
                 wraplength=self.wraplength, bg=uc.TOOLTIP_BG, fg='black',
                 relief='solid', borderwidth=1, padx=7, pady=5).pack()
        self._tip = tip

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


def add_tooltip(widget, text):
    """Attach a hover tooltip; returns the widget for chaining."""
    Tooltip(widget, text)
    return widget


class SplashScreen(tk.Toplevel):
    """Borderless "starting up" window shown while the tabs are built.

    Building the six tabs takes ~2.6 s on the bench PC (measured), during
    which nothing appeared on screen at all -- a user double-clicking the
    desktop icon had no idea anything was happening. This paints
    immediately and reports each phase, then goes away.
    """

    W, H = 460, 170

    def __init__(self, root, version_text=''):
        super().__init__(root)
        self.overrideredirect(True)          # no title bar / decorations
        self.configure(bg=uc.BANNER_INFO)
        # centre on screen (the main window is not sized yet)
        x = (self.winfo_screenwidth() - self.W) // 2
        y = (self.winfo_screenheight() - self.H) // 3
        self.geometry(f'{self.W}x{self.H}+{x}+{y}')

        frame = tk.Frame(self, bg=uc.BANNER_INFO, padx=24, pady=18)
        frame.pack(fill='both', expand=True)
        # Name transition (2026-07-20): "SCPI Control" -> "Digital
        # Multitool", starting here on the splash. Same look, new name.
        tk.Label(frame, text='Digital Multitool', bg=uc.BANNER_INFO, fg='white',
                 font=('TkDefaultFont', 17, 'bold')).pack(anchor='w')
        tk.Label(frame, text='Lab instrument control suite', bg=uc.BANNER_INFO,
                 fg=uc.TEXT_ON_FILL_MUTED, font=('TkDefaultFont', 10)).pack(anchor='w')

        self._status = tk.Label(frame, text='Starting...', bg=uc.BANNER_INFO,
                                fg=uc.TEXT_ON_FILL, font=('TkDefaultFont', 10),
                                anchor='w')
        self._status.pack(anchor='w', pady=(14, 4), fill='x')
        self._bar = ttk.Progressbar(frame, mode='indeterminate', length=400)
        self._bar.pack(fill='x')
        self._bar.start(12)
        if version_text:
            tk.Label(frame, text=version_text, bg=uc.BANNER_INFO, fg=uc.TEXT_ON_FILL_MUTED,
                     font=('TkDefaultFont', 8)).pack(anchor='e',
                                                     pady=(8, 0))
        self.update_idletasks()
        self.update()                         # paint before the slow work

    def set_status(self, text):
        """Update the phase line and repaint (called from the build loop)."""
        try:
            self._status.config(text=text)
            self.update_idletasks()
            self.update()
        except tk.TclError:                   # already closed
            pass

    def close(self):
        try:
            self._bar.stop()
            self.destroy()
        except tk.TclError:
            pass


def content_width(canvas_width, content_reqwidth):
    """Width to give a ScrollableTab's content inside a canvas that wide.

    Stretching the content to the canvas width is load-bearing: it is what
    makes every tab frame fill the window at comfortable widths. Doing it
    UNCONDITIONALLY was the `#225` bug -- content wider than the window got
    squeezed and clipped instead of becoming scrollable, with no way to
    reach it. Taking the max keeps the stretch and lets genuinely wide
    content overflow into scrollable territory.
    """
    return max(int(canvas_width), int(content_reqwidth))


def needs_hscroll(canvas_width, content_reqwidth):
    """Should the horizontal scrollbar be on screen?

    Only when something is actually off to the right -- a permanent h-bar
    under every tab would be its own annoyance. Strict `>`: showing the bar
    costs VERTICAL space and never horizontal, so the decision cannot
    oscillate the way a conditional v-bar would.
    """
    return int(content_reqwidth) > int(canvas_width)


def content_height(canvas_height, content_reqheight):
    """Height to give the content inside a canvas that tall.

    The vertical mirror of content_width, and wanted for the same reason:
    a container whose content must FILL it when there is room and become
    scrollable when there is not. ScrollableTab does not use this -- its
    tabs are top-aligned stacks that should keep their natural height and
    leave space below -- so it is opt-in per container.
    """
    return max(int(canvas_height), int(content_reqheight))


def needs_vscroll(canvas_height, content_reqheight):
    """Should the vertical scrollbar be on screen? (mirror of needs_hscroll)"""
    return int(content_reqheight) > int(canvas_height)


def scroll_bars_needed(width, height, reqwidth, reqheight,
                       vbar_w=16, hbar_h=16):
    """Which bars a viewport needs, decided so the answer cannot FLAP.

    With only one conditional bar the decision is trivial. With two it is
    not: a v-bar costs horizontal space, which can call for an h-bar, which
    costs vertical space, which can call for the v-bar -- and a naive
    implementation toggles both forever, because each <Configure> the
    toggle causes re-runs the decision.

    The fix is to make every step MONOTONE. Space is only ever taken away,
    never given back, within one decision: ask for the v-bar, subtract its
    width, ask for the h-bar against what is left, subtract its height, and
    only then re-ask the v-bar question if it was previously no. Each
    answer can flip from no to yes and never back, so this settles in at
    most two passes and returns the same answer if fed its own result.

    `width`/`height` are the CONTAINER's size -- not the canvas's -- so the
    inputs do not move when a bar appears. Returns (show_v, show_h).
    """
    avail_w, avail_h = int(width), int(height)
    reqw, reqh = int(reqwidth), int(reqheight)

    show_v = needs_vscroll(avail_h, reqh)
    if show_v:
        avail_w -= int(vbar_w)
    show_h = needs_hscroll(avail_w, reqw)
    if show_h:
        avail_h -= int(hbar_h)
        if not show_v:                      # the h-bar just ate the margin
            show_v = needs_vscroll(avail_h, reqh)
    return show_v, show_h


class ScrollableFrame(ttk.Frame):
    """A frame whose content stays reachable when the window is too small.

    Build content into `.body` instead of the frame itself.

    Two knobs, because the two users want different things:

    `always_vbar` -- keep the vertical bar on screen unconditionally.
    ScrollableTab's long-standing contract, preserved exactly.

    `stretch_height` -- also stretch content to the viewport HEIGHT when
    there is room. Off for notebook tabs, which are top-aligned stacks that
    should keep their natural height. On for a whole window whose middle
    pane must grow into the space available.

    Why this exists as its own class (2026-08-12): Edge Review had no
    scroll container at all, and Tk's packer does not clip an overflowing
    window -- it DISCARDS the widgets that do not fit. Measured on the
    shipped default geometry, a 900x600 Edge Review window silently lost
    Reject, Unreview and the How-to button; at 700x500 the entire review
    panel was gone and no frame could be accepted or rejected. Nothing on
    screen said so.
    """

    def __init__(self, parent, always_vbar=False, stretch_height=False):
        super().__init__(parent)
        self._always_vbar = bool(always_vbar)
        self._stretch_height = bool(stretch_height)
        bg = ttk.Style().lookup('TFrame', 'background') or None
        self._canvas = tk.Canvas(self, highlightthickness=0,
                                 **({'bg': bg} if bg else {}))
        vbar = ttk.Scrollbar(self, orient='vertical',
                             command=self._canvas.yview)
        self._hbar = ttk.Scrollbar(self, orient='horizontal',
                                   command=self._canvas.xview)
        self._canvas.configure(yscrollcommand=vbar.set,
                               xscrollcommand=self._hbar.set)
        # grid rather than pack: the h-bar has to come and go underneath the
        # canvas without disturbing the v-bar, and grid_remove()/grid()
        # restores its slot exactly. Nothing outside this class is placed in
        # the tab frame itself -- callers only ever touch `.body`.
        self._canvas.grid(row=0, column=0, sticky='nsew')
        self._vbar = vbar
        vbar.grid(row=0, column=1, sticky='ns')
        self._hbar.grid(row=1, column=0, sticky='ew')
        self._hbar.grid_remove()             # on demand only
        self._hbar_shown = False
        self._vbar_shown = True
        if not self._always_vbar:
            vbar.grid_remove()               # on demand too
            self._vbar_shown = False
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.body = ttk.Frame(self._canvas)
        self._win = self._canvas.create_window((0, 0), window=self.body,
                                               anchor='nw')
        self.body.bind('<Configure>', self._on_body_configure)
        self._canvas.bind('<Configure>', self._on_canvas_configure)
        # keyboard scrolling (audit 2026-07-25: tabs were mouse-wheel only)
        self._canvas.configure(takefocus=1)
        for key, n in (('<Up>', -1), ('<Down>', 1),
                       ('<Prior>', -5), ('<Next>', 5)):
            self._canvas.bind(key,
                              lambda e, n=n: self._canvas.yview_scroll(
                                  n, 'units'))
        for key, n in (('<Left>', -1), ('<Right>', 1)):
            self._canvas.bind(key,
                              lambda e, n=n: self._canvas.xview_scroll(
                                  n, 'units'))
        # Mouse wheel scrolls whichever tab the pointer is over. bind_all
        # is grabbed on Enter and released on Leave so tabs don't fight.
        self.bind('<Enter>', self._bind_wheel)
        self.bind('<Leave>', self._unbind_wheel)
        # ...and released on destroy, or an application-wide binding is left
        # pointing at a canvas that no longer exists. A notebook tab lives
        # as long as its app so this never bit, but Edge Review builds a
        # whole window's worth per instance -- and a test process that
        # builds dozens then tears them down turns the dangling handlers
        # into 'Tcl_AsyncDelete: async handler deleted by the wrong thread'
        # and aborts. add='+' so this never displaces a caller's own bind.
        self.bind('<Destroy>', self._release_on_destroy, add='+')

    # ---- layout ---------------------------------------------------------

    def _refit(self, canvas_w=None):
        """Re-apply the content size and the bar show/hide decisions."""
        if canvas_w is None:
            canvas_w = self._canvas.winfo_width()
        if canvas_w <= 1:
            return              # not laid out yet -- nothing to decide on
        need = self.body.winfo_reqwidth()
        self._canvas.itemconfigure(self._win,
                                   width=content_width(canvas_w, need))
        if not self._always_vbar:
            self._refit_both(need)
            return
        show = needs_hscroll(canvas_w, need)
        if show != self._hbar_shown:
            (self._hbar.grid if show else self._hbar.grid_remove)()
            self._hbar_shown = show

    def _refit_both(self, need_w):
        """The two-conditional-bar case, decided off the CONTAINER's size.

        Measuring the container rather than the canvas is what keeps this
        stable: the container does not change size when a bar is added, so
        the inputs to the decision are the same before and after, and a
        toggle cannot feed itself. See scroll_bars_needed for the rest.
        """
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1:
            return
        need_h = self.body.winfo_reqheight()
        if self._stretch_height:
            # Only stretch to the space the content would actually get; a
            # body stretched to the full container height while an h-bar is
            # showing would be exactly one bar too tall to fit.
            avail_h = h - (self._hbar.winfo_reqheight()
                           if self._hbar_shown else 0)
            self._canvas.itemconfigure(
                self._win, height=content_height(avail_h, need_h))
        show_v, show_h = scroll_bars_needed(
            w, h, need_w, need_h,
            vbar_w=self._vbar.winfo_reqwidth(),
            hbar_h=self._hbar.winfo_reqheight())
        if show_v != self._vbar_shown:
            (self._vbar.grid if show_v else self._vbar.grid_remove)()
            self._vbar_shown = show_v
        if show_h != self._hbar_shown:
            (self._hbar.grid if show_h else self._hbar.grid_remove)()
            self._hbar_shown = show_h

    def _on_body_configure(self, _event):
        # Content changed size: the scrollregion AND the width / bar
        # decisions both follow it, so a tab that grows at runtime does not
        # keep the width it was born with.
        self._canvas.configure(scrollregion=self._canvas.bbox('all'))
        self._refit()

    def _on_canvas_configure(self, event):
        # event.width, not winfo_width(): during <Configure> the widget may
        # still report its previous size.
        self._refit(event.width)

    # ---- pointer --------------------------------------------------------

    def _wheel(self, event):
        if event.num == 4 or event.delta > 0:
            self._canvas.yview_scroll(-2, 'units')
        elif event.num == 5 or event.delta < 0:
            self._canvas.yview_scroll(2, 'units')

    def _wheel_x(self, event):
        """Shift+wheel (and an X11 tilt wheel) scrolls sideways -- the
        platform convention, and the pointer route to off-screen content."""
        if event.num in (4, 6) or event.delta > 0:
            self._canvas.xview_scroll(-2, 'units')
        elif event.num in (5, 7) or event.delta < 0:
            self._canvas.xview_scroll(2, 'units')

    _WHEEL_SEQS = (
        ('<Button-4>', '_wheel'),            # X11 up
        ('<Button-5>', '_wheel'),            # X11 down
        ('<MouseWheel>', '_wheel'),          # other OSes
        # Horizontal. The Shift- patterns are more specific than the plain
        # ones above, so Tk prefers them while Shift is held.
        ('<Shift-Button-4>', '_wheel_x'),
        ('<Shift-Button-5>', '_wheel_x'),
        ('<Shift-MouseWheel>', '_wheel_x'),
        ('<Button-6>', '_wheel_x'),          # X11 tilt wheel left
        ('<Button-7>', '_wheel_x'),          # X11 tilt wheel right
    )

    def _bind_wheel(self, _event=None):
        for seq, handler in self._WHEEL_SEQS:
            try:
                self._canvas.bind_all(seq, getattr(self, handler))
            except tk.TclError:
                # Windows Tk knows buttons 1-5 only and rejects the X11
                # tilt wheel outright. Bind what the platform accepts.
                pass

    def _unbind_wheel(self, _event=None):
        for seq, _handler in self._WHEEL_SEQS:
            try:
                self._canvas.unbind_all(seq)
            except tk.TclError:
                pass

    def _release_on_destroy(self, event=None):
        """Drop the application-wide wheel bindings when this frame goes.

        Guarded on the widget: <Destroy> fires for every descendant too, and
        releasing on the first child teardown would unbind the wheel while
        the frame is still alive and under the pointer.
        """
        if event is not None and event.widget is not self:
            return
        self._unbind_wheel()


class ScrollableTab(ScrollableFrame):
    """Notebook tab with scrollbars when content doesn't fit the window.

    Build the tab's content into `.body` instead of the tab itself.

    Vertical: the bar is always there and scrolls when content is taller
    than the window -- the original cut-off case.
    Horizontal (`#225`): the bar appears ONLY when content is genuinely
    wider than the canvas. Wide content used to be pinned to the canvas
    width and clipped, unreachable by any means; Shift+wheel and
    Left/Right now reach it.

    Both behaviours are the pre-2026-08-12 ones exactly. The class became a
    thin subclass when Edge Review needed the same machinery with two
    conditional bars; nothing about a tab changed, and the ten call sites
    did not move.
    """

    def __init__(self, notebook):
        super().__init__(notebook, always_vbar=True, stretch_height=False)


# ---- Usage Tips window (#480) ---------------------------------------------
# Each instrument tab's "Show Usage Tips" used to call messagebox.showinfo.
# On Windows that is the native message box: narrow, fixed in size and
# unable to scroll, so a 630-word tip wrapped line by line down the screen.
# This is one window for all six tabs:
#   * resizable, with a vertical scrollbar, and words that wrap to the
#     window's width as it is resized (a Text widget, wrap='word');
#   * modeless: no grab, so the tab stays usable beside it;
#   * one per tab: pressing the button again raises the open window rather
#     than stacking a second copy;
#   * Esc and a Close button close it;
#   * a starting size for the 1920x1080 bench monitor, never larger than
#     the screen it opens on;
#   * placed at the screen's right edge, level with the top of the app's
#     window, so it covers as little of the app as the screen allows. It is
#     transient (it stays above the app), so where it opens matters: left
#     open during a LIVE run it must not sit over the middle of a tab.
# Words are uc.TEXT on white, headings uc.TEXT_ACCENT, and a page's safety
# heading uc.TEXT_ALERT behind a warning sign, so its words say what the
# color repeats. All three reach 4.5:1 on white (tests/test_usage_tips.py).

TIPS_SIZE_96DPI = (640, 560)    # starting width, height in px at 96 dpi
TIPS_MIN_SIZE = (360, 240)      # the smallest the window may be dragged to
TIPS_SCREEN_MARGIN = 80         # px left free for a taskbar and title bar
TIPS_FRAME_PAD = 16             # px for the window border at the right edge
TIPS_BG = 'white'               # the page the words are written on
ALERT_SIGN = '⚠'           # the warning sign before a safety heading
BULLET = '•'


def tips_size(dpi, screen_w, screen_h):
    """(width, height) in px the tips window starts at.

    TIPS_SIZE_96DPI scaled by the screen's dots per inch (a Tk that reports
    a high dpi gets a window of the same physical size), and never more
    than the screen less TIPS_SCREEN_MARGIN, nor less than TIPS_MIN_SIZE
    (the minimum wins on a screen smaller than that)."""
    scale = max(1.0, float(dpi) / 96.0)
    out = []
    for want, screen, least in zip(TIPS_SIZE_96DPI, (screen_w, screen_h),
                                   TIPS_MIN_SIZE):
        room = int(screen) - TIPS_SCREEN_MARGIN
        out.append(max(least, min(int(round(want * scale)), room)))
    return tuple(out)


def tips_place(screen_w, screen_h, w, h, app_top):
    """(x, y) of the top-left corner of a w x h tips window.

    At the screen's right edge (less TIPS_FRAME_PAD for the border), level
    with `app_top`, the top of the app's window. Clamped onto the screen:
    never left of 0, never above 0, and its bottom never in the last
    TIPS_SCREEN_MARGIN px (the taskbar), however low the app sits."""
    x = max(0, int(screen_w) - int(w) - TIPS_FRAME_PAD)
    y = max(0, min(int(app_top),
                   int(screen_h) - int(h) - TIPS_SCREEN_MARGIN))
    return x, y


def tips_text(page):
    """A usage_tips page as plain text, in the order the window shows it.

    The window inserts exactly these lines, so tests that read this read
    what an operator sees. `page` has .heading, .sections and .manual; a
    section is (heading, lines) or (heading, lines, alert)."""
    out = [page.heading]
    for section in page.sections:
        heading, lines = section[0], section[1]
        alert = len(section) > 2 and bool(section[2])
        out.append(f"{ALERT_SIGN} {heading}" if alert else heading)
        out.extend(f"{BULLET}\t{line}" for line in lines)
    if page.manual:
        out.append(page.manual)
    return '\n'.join(out)


class TipsWindow(tk.Toplevel):
    """One tab's Usage Tips: a resizable, scrolled, read-only page.

    Built fail-closed, like Edge Review's How-to panel: a failure part way
    through destroys the half-built window rather than leaving one that a
    later press would raise and show empty."""

    def __init__(self, master, page):
        super().__init__(master)
        try:
            self._build(master, page)
        except Exception:
            self.destroy()
            raise

    def _build(self, master, page):
        self.title(page.title)
        self.transient(master)              # stays with its app; no grab
        self.resizable(True, True)
        self.minsize(*TIPS_MIN_SIZE)
        self.configure(bg=TIPS_BG)

        # Fonts: the platform's own default, bold for headings and a size
        # up for the page heading. Kept on self: a tkfont.Font is deleted
        # from Tk when its Python object goes.
        base = tkfont.nametofont('TkDefaultFont')
        self._font_body = base.copy()
        self._font_head = base.copy()
        self._font_head.configure(weight='bold')
        self._font_title = base.copy()
        size = int(str(base.actual('size')))
        self._font_title.configure(weight='bold',
                                   size=size + 3 if size > 0 else size - 4)

        foot = ttk.Frame(self, padding=(8, 6))
        foot.pack(side=tk.BOTTOM, fill='x')
        self.close_btn = ttk.Button(foot, text="Close",
                                    command=self.destroy)
        self.close_btn.pack(side=tk.RIGHT)

        body = tk.Frame(self, bg=TIPS_BG)
        body.pack(side=tk.TOP, fill='both', expand=True)
        self.text = tk.Text(body, wrap='word', bg=TIPS_BG, fg=uc.TEXT,
                            font=self._font_body, relief='flat', bd=0,
                            highlightthickness=0, padx=16, pady=12,
                            cursor='arrow', spacing1=1, spacing3=3)
        self.vbar = ttk.Scrollbar(body, orient='vertical',
                                  command=self.text.yview)
        self.text.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side=tk.RIGHT, fill='y')
        self.text.pack(side=tk.LEFT, fill='both', expand=True)

        # A bullet hangs in the left margin and its wrapped lines line up
        # under the words, not under the bullet.
        hang = self.text.winfo_pixels('0.25i')
        self.text.tag_configure('title', font=self._font_title,
                                foreground=uc.TEXT, spacing3=6)
        self.text.tag_configure('head', font=self._font_head,
                                foreground=uc.TEXT_ACCENT,
                                spacing1=12, spacing3=3)
        self.text.tag_configure('alert', font=self._font_head,
                                foreground=uc.TEXT_ALERT,
                                spacing1=12, spacing3=3)
        self.text.tag_configure('item', lmargin1=4, lmargin2=hang,
                                tabs=(hang,))
        self.text.tag_configure('manual', foreground=uc.TEXT_MUTED,
                                spacing1=14)
        self._fill(page)
        self.text.configure(state='disabled')

        # A click puts the focus in the text, so a selection can be copied.
        self.text.bind('<Button-1>', lambda _e: self.text.focus_set(),
                       add='+')
        # Keys and the wheel scroll the page from anywhere in the window.
        # Each is bound on the text, its scrollbar AND the window, and
        # returns 'break': over (or with the focus in) the text, its own
        # binding scrolls once and nothing else runs. The Text class would
        # move a cursor too, the scrollbar class would scroll a second time,
        # and a tab's application-wide wheel binding would scroll the tab.
        def scroll(n, what):
            self.text.yview_scroll(n, what)
            return 'break'

        def wheel(event):
            up = event.num == 4 or getattr(event, 'delta', 0) > 0
            return scroll(-3 if up else 3, 'units')

        for key, n, what in (('<Prior>', -1, 'pages'),
                             ('<Next>', 1, 'pages'),
                             ('<Up>', -1, 'units'), ('<Down>', 1, 'units')):
            for w in (self.text, self):
                w.bind(key, lambda _e, n=n, what=what: scroll(n, what))
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            for w in (self.text, self.vbar, self):
                w.bind(seq, wheel)
        self.bind('<Escape>', lambda _e: self.destroy())

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = tips_size(self.winfo_fpixels('1i'), sw, sh)
        app_top = master.winfo_toplevel().winfo_rooty()
        x, y = tips_place(sw, sh, w, h, app_top)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.focus_set()

    def _fill(self, page):
        lines = tips_text(page).split('\n')
        self.text.insert('end', lines[0] + '\n', 'title')
        rest = lines[1:]
        for i, line in enumerate(rest):
            end = '' if i == len(rest) - 1 else '\n'
            if line.startswith(BULLET + '\t'):
                tag = 'item'
            elif page.manual and i == len(rest) - 1:
                tag = 'manual'
            elif line.startswith(ALERT_SIGN + ' '):
                tag = 'alert'
            else:
                tag = 'head'
            self.text.insert('end', line + end, tag)


# The open tips windows: (app window, tab key) -> TipsWindow.
_TIPS_OPEN = {}


def show_tips(master, key, page):
    """Open tab `key`'s Usage Tips window, or raise it if it is open.

    -> the window. `page` is a usage_tips page. Modeless: nothing waits on
    the window and it takes no grab."""
    top = master.winfo_toplevel()
    win = _TIPS_OPEN.get((top, key))
    if win is not None:
        try:
            alive = bool(win.winfo_exists())
        except tk.TclError:                   # its Tk has gone
            alive = False
        if alive:
            win.deiconify()
            win.lift()
            win.focus_set()
            return win
        _TIPS_OPEN.pop((top, key), None)
    win = TipsWindow(top, page)
    _TIPS_OPEN[(top, key)] = win

    def forget(event, slot=(top, key)):
        # <Destroy> fires for every child too; only the window itself counts
        if event.widget is win and _TIPS_OPEN.get(slot) is win:
            _TIPS_OPEN.pop(slot, None)
    win.bind('<Destroy>', forget, add='+')
    return win


# ---- output-folder pickers (#394) ---------------------------------------
# The bench's Tk folder dialog (tk_chooseDirectory) has no New Folder
# button, so a fresh folder for a session meant a trip to the system file
# manager. Each picker that chooses where output goes now has Browse, which
# opens at the folder in its box, and New folder..., which makes a folder
# inside that one and puts it in the box. The dialogs are this module's
# filedialog / simpledialog / messagebox, so tests swap them for fakes.

def browse_folder(var, parent=None):
    """Browse for a folder, opening at the one in `var`.

    Sets `var` to the folder chosen and returns it; Cancel changes nothing
    and returns None. Where it opens: output_folder.browse_start.
    """
    opts = {'initialdir': output_folder.browse_start(var.get())}
    if parent is not None:
        opts['parent'] = parent
    chosen = filedialog.askdirectory(**opts)
    if not chosen:
        return None
    var.set(chosen)
    return chosen


def new_folder(var, box, parent=None, share=None):
    """New folder...: make a folder inside the one in `var`, and put the new
    folder in `var`. -> its path, or None when nothing was made.

    `box` is the box's name as its label shows it, for the messages. A box
    that is empty or names no folder is explained and nothing is asked, and
    so is a box under the lab share's mount point while the share is not
    mounted, when `share` (a path on the share) says where that is. A
    refused name is explained and the prompt comes back holding it, to be
    fixed rather than retyped; Cancel leaves. A folder the system will not
    make (a read-only or missing share) is explained and ends it.
    """
    title = "New folder"
    opts = {} if parent is None else {'parent': parent}
    where = var.get().strip()
    problem = output_folder.parent_problem(
        where, box, mount=output_folder.share_mount(share))
    if problem:
        messagebox.showerror(title, problem, **opts)
        return None
    typed = ''
    while True:
        typed = simpledialog.askstring(
            title, f"Make a new folder inside\n{where}\n\nName:",
            initialvalue=typed, **opts)
        if typed is None:                       # Cancel
            return None
        try:
            path = output_folder.make(where, typed)
        except ValueError as e:                 # refused: say why, ask again
            messagebox.showerror(title, str(e), **opts)
            continue
        except OSError as e:                    # e.g. a read-only share
            messagebox.showerror(
                title, output_folder.failed_text(where, typed, e), **opts)
            return None
        var.set(path)
        return path


def folder_buttons(master, browse, new, box, what):
    """Browse and New folder... side by side, in a frame of their own.

    `browse` and `new` are the two commands; `box` (the box's name) and
    `what` (what goes into the folder) word the New folder... tooltip.
    -> (frame, browse_button, new_folder_button). The caller places the
    frame where Browse alone used to go, so the pair always sits together.
    """
    frame = ttk.Frame(master)
    browse_btn = ttk.Button(frame, text="Browse", command=browse)
    browse_btn.pack(side=tk.LEFT)
    new_btn = ttk.Button(frame, text=output_folder.NEW_FOLDER_LABEL,
                         command=new)
    new_btn.pack(side=tk.LEFT, padx=(4, 0))
    add_tooltip(new_btn,
                f"Make a new, empty folder inside the folder in the {box} "
                f"box and put it in the box, so {what} go into it. You type "
                f"the name; a name already in use is refused.")
    return frame, browse_btn, new_btn
