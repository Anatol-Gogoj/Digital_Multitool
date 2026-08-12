#!/usr/bin/env python3
"""Small reusable Tk UI helpers: hover tooltips and scrollable tabs.

Both address long-standing GUI complaints (2026-07-10): content taller
than the window was simply CUT OFF with no scrollbar, and none of the
controls explained themselves (e.g. the LCR Speed/Avg fields).
"""
import tkinter as tk
from tkinter import ttk


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
                 wraplength=self.wraplength, bg='#ffffe0', fg='black',
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
        self.configure(bg='#1f3a5f')
        # centre on screen (the main window is not sized yet)
        x = (self.winfo_screenwidth() - self.W) // 2
        y = (self.winfo_screenheight() - self.H) // 3
        self.geometry(f'{self.W}x{self.H}+{x}+{y}')

        frame = tk.Frame(self, bg='#1f3a5f', padx=24, pady=18)
        frame.pack(fill='both', expand=True)
        # Name transition (2026-07-20): "SCPI Control" -> "Digital
        # Multitool", starting here on the splash. Same look, new name.
        tk.Label(frame, text='Digital Multitool', bg='#1f3a5f', fg='white',
                 font=('TkDefaultFont', 17, 'bold')).pack(anchor='w')
        tk.Label(frame, text='Lab instrument control suite', bg='#1f3a5f',
                 fg='#b8c7dc', font=('TkDefaultFont', 10)).pack(anchor='w')

        self._status = tk.Label(frame, text='Starting...', bg='#1f3a5f',
                                fg='#e6edf5', font=('TkDefaultFont', 10),
                                anchor='w')
        self._status.pack(anchor='w', pady=(14, 4), fill='x')
        self._bar = ttk.Progressbar(frame, mode='indeterminate', length=400)
        self._bar.pack(fill='x')
        self._bar.start(12)
        if version_text:
            tk.Label(frame, text=version_text, bg='#1f3a5f', fg='#8fa4bd',
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
