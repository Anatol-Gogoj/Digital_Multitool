#!/usr/bin/env python3
"""Footer packing rule (`#27`): the version readout must survive.

The footer is a status bar that stretches plus a fixed-width version
readout. Tk's packer serves slaves in PACKING order, each taking its
requested size out of what is left of the cavity -- so whoever is packed
first is the one guaranteed to get its width. The status bar used to be
packed first, so a status message wider than the window swallowed the
whole footer and the version readout vanished (measured: 96 px -> 3 px at
a 500 px window with a 497 px status line).

The footer is at ROOT level, not inside a ScrollableTab, so the `#225`
horizontal-scroll fix cannot reach it -- this is its own fix and its own
test.

`build_footer` is exercised directly rather than through a full
InstrumentControlGUI, which would build all nine tabs first. Skips
cleanly when no display can be opened.

Run: .venv/bin/python tests/test_gui_footer.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

# A status line long enough to overrun a narrow window -- the real one is
# set from file paths and sweep progress, which get this long easily.
LONG_STATUS = ("Sweep written to C:/Users/Anatol Gogoj/Documents/"
               "bench-logs/sweep_20260807_142233.csv")


def _footer():
    """(root, app-ish, footer) or (None, None, None) with no display."""
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return None, None, None
    import gui
    # __init__ builds nine tabs and opens the camera; the footer rule does
    # not need any of that.
    app = object.__new__(gui.InstrumentControlGUI)
    footer = app.build_footer(root)
    root.geometry('900x120')
    root.deiconify()
    for _ in range(6):
        root.update_idletasks()
        root.update()
    return root, app, footer


def _settle(root, n=6):
    for _ in range(n):
        root.update_idletasks()
        root.update()


def test_version_readout_is_packed_before_the_status_bar():
    """The rule itself. Order is the whole fix -- assert it directly so a
    later edit that 'tidies' the two lines back cannot pass silently."""
    root, app, footer = _footer()
    if root is None:
        return
    try:
        order = footer.pack_slaves()
        assert order[0] is app.version_label, (
            "version readout must be packed FIRST or a long status line "
            "eats it: got %r" % (order,))
        assert order[1] is app.status_bar, order
    finally:
        root.destroy()


def test_version_readout_keeps_its_width_at_every_window_width():
    root, app, _footer_ = _footer()
    if root is None:
        return
    try:
        want = app.version_label.winfo_reqwidth()
        assert want > 20, want            # sanity: it asks for real space
        for status in ("Ready", LONG_STATUS):
            app.status_bar.config(text=status)
            for w in (1600, 1320, 900, 700, 600, 500, 400):
                root.geometry('%dx120' % w)
                _settle(root)
                got = app.version_label.winfo_width()
                assert got >= want, (
                    "version readout squeezed to %d px (wants %d) at a "
                    "%d px window with a %d px status line"
                    % (got, want, w, app.status_bar.winfo_reqwidth()))
    finally:
        root.destroy()


def test_the_status_bar_is_what_gives_way():
    """The other half of the trade: the status bar still stretches when
    there is room, and is the one that truncates when there is not."""
    root, app, _footer_ = _footer()
    if root is None:
        return
    try:
        app.status_bar.config(text="Ready")
        root.geometry('900x120')
        _settle(root)
        wide = app.status_bar.winfo_width()
        assert wide > app.status_bar.winfo_reqwidth(), (
            "status bar stopped stretching to fill the footer")
        app.status_bar.config(text=LONG_STATUS)
        root.geometry('400x120')
        _settle(root)
        narrow = app.status_bar.winfo_width()
        assert narrow < app.status_bar.winfo_reqwidth(), (
            "status bar should truncate, not push the version off")
        assert narrow < wide
        # and the version is still whole
        assert (app.version_label.winfo_width()
                >= app.version_label.winfo_reqwidth())
    finally:
        root.destroy()


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    failed = []
    for fn in fns:
        try:
            fn()
        except Exception:
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
        print(f"ok  {fn.__name__}")
    if not failed:
        print(f"\n{len(fns)} tests passed")
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
