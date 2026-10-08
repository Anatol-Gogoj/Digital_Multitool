"""Screenshot + widget-geometry capture for the Digital Multitool manual.

Launches the real gui.py, walks every notebook tab, saves a PNG of each,
opens the Arb Editor (+ its export dialogs), and writes widgets.json with
the on-screen bbox of every labelled widget so annotations can be placed
programmatically.
"""
import ctypes
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(_HERE))          # repo root (docs/manual-src -> repo)
OUT = os.path.join(_HERE, "build", "shots")
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, REPO)
os.chdir(REPO)

import tkinter as tk  # noqa: E402
from tkinter import messagebox, filedialog  # noqa: E402
from PIL import ImageGrab  # noqa: E402

# No modal dialogs during automated capture.
for _name in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, _name, lambda *a, **k: print(f"[msgbox suppressed] {a}"))
for _name in ("askyesno", "askokcancel", "askretrycancel"):
    setattr(messagebox, _name, lambda *a, **k: False)
for _name in ("askopenfilename", "asksaveasfilename", "askdirectory"):
    setattr(filedialog, _name, lambda *a, **k: "")

manifest = {"images": []}

# Display scaling (2026-10-05). The process is DPI-aware so that the
# screenshot and the widget boxes share one pixel grid. Left at that, Tk
# reads the display's real dpi (168 on a 175 % display) and draws its
# fonts 1.75 times larger while every size the app gives in pixels
# (window geometry, panel widths, wraplengths) stays put, so windows come
# out cramped and clipped. Resizing the window and shrinking the shot
# afterwards (the first fix) only covers the windows the script sizes
# itself: the Arb Editor, the splash and the dialogs size themselves and
# still came out cramped, and the resample softened the text. Pinning Tk
# to 96 dpi instead lays every window out exactly as a 100 % display (and
# the DPI-unaware app on the lab PCs) does, with sharp text and no
# resample. Only the window frame and the native menu bar are still drawn
# by Windows at the display scale; chrome_scale() is for those.
def pin_96dpi(root):
    """Make Tk lay out at 96 dpi. Call right after tk.Tk(), before any
    widget or font is built."""
    root.tk.call("tk", "scaling", 96.0 / 72.0)


def chrome_scale():
    """Display scale for what Windows draws itself (1.0 at 100 %)."""
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
    except Exception:
        return 1.0
    return max(1.0, dpi / 96.0)


def _fit_on_screen(root):
    """Keep the main window wholly on screen, or stop the capture.

    Windows does not always honour the requested +40+30: on a 1080 px
    screen (v1.4.4 build, 2026-10-08) the window landed at y=208 once and
    y=52 the next time, and every tab shot lost its bottom rows to black
    below the screen's edge. A window placed too low is moved to the top;
    one that still does not fit stops the run, because annotate.py would
    otherwise draw callouts on black."""
    sh = root.winfo_screenheight()
    l, t, r, b = _win_rect(root)
    if b > sh or t < 0:
        root.geometry(f"+{root.winfo_x()}+0")
        root.update_idletasks()
        root.update()
        time.sleep(0.5)
        l, t, r, b = _win_rect(root)
    if b > sh or t < 0:
        sys.exit(f"capture.py FAILED -- the window ({l}, {t})-({r}, {b}) "
                 f"does not fit the {sh} px screen. Use a taller display "
                 "(README.md, Regenerating).")


def _win_rect(widget):
    """Visual rect of the top-level window holding `widget` (DWM bounds)."""
    hwnd = ctypes.windll.user32.GetAncestor(widget.winfo_id(), 2)  # GA_ROOT
    rect = wintypes.RECT()
    try:
        DWMWA_EXTENDED_FRAME_BOUNDS = 9
        res = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect),
            ctypes.sizeof(rect))
        if res != 0:
            raise OSError(res)
    except Exception:
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def _walk(widget, origin_x, origin_y, out):
    for child in widget.winfo_children():
        try:
            cls = child.winfo_class()
            w, h = child.winfo_width(), child.winfo_height()
            x = child.winfo_rootx() - origin_x
            y = child.winfo_rooty() - origin_y
            text = ""
            try:
                text = str(child.cget("text"))
            except Exception:
                pass
            if (w > 1 and h > 1 and child.winfo_viewable()
                    and not text.startswith("PY_VAR")):
                out.append({"class": cls, "text": text,
                            "x": x, "y": y, "w": w, "h": h})
        except Exception:
            continue
        _walk(child, origin_x, origin_y, out)


def capture_window(widget, name, extra_widgets=None):
    """Screenshot the top-level window of `widget`; record widget geometry."""
    widget.update_idletasks()
    widget.update()
    time.sleep(0.35)
    l, t, r, b = _win_rect(widget)
    img = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)
    path = os.path.join(OUT, name + ".png")
    top = widget.winfo_toplevel()
    widgets = []
    _walk(top, l, t, widgets)
    if extra_widgets:
        widgets.extend(extra_widgets)
    img.save(path)
    entry = {"name": name, "file": path,
             "img_w": img.size[0], "img_h": img.size[1],
             "origin": [l, t],
             "client_offset": [top.winfo_rootx() - l, top.winfo_rooty() - t],
             "widgets": widgets}
    manifest["images"].append(entry)
    import numpy as np
    arr = np.asarray(img.convert("L"), dtype=float)
    print(f"captured {name}: {img.size[0]}x{img.size[1]} std={arr.std():.1f}")
    return entry


def main():
    root = tk.Tk()
    pin_96dpi(root)
    root.withdraw()
    k = chrome_scale()

    from ui_widgets import SplashScreen
    from version import version_string

    # -- splash --------------------------------------------------------
    splash = SplashScreen(root, version_string())
    splash.attributes("-topmost", True)
    splash.set_status("Loading LCR meter...")
    splash.update()
    time.sleep(0.4)
    capture_window(splash, "00_splash")
    splash.close()

    # -- main app ------------------------------------------------------
    import gui as gui_mod
    # Opening the Webcam tab starts its preview (#375). The manual must
    # never carry a photo from the build PC's camera: keep it off, so the
    # tab is photographed showing its PREVIEW OFF splash.
    gui_mod.CAM_AUTOSTART_ON_TAB = False
    app = gui_mod.InstrumentControlGUI(root)
    root.deiconify()
    h = min(1000, root.winfo_screenheight() - 90)
    root.geometry(f"1320x{h}+40+30")
    root.attributes("-topmost", True)
    root.update_idletasks()
    root.update()
    time.sleep(0.8)
    _fit_on_screen(root)

    def _extras():
        l, t, _, _ = _win_rect(root)
        cx = root.winfo_rootx() - l
        cy = root.winfo_rooty() - t
        # Windows draws the menu bar at the display scale, so its box
        # scales; the tab strip is Tk's and stays at 96 dpi.
        return [
            {"class": "Menu", "text": "Tools",
             "x": cx + int(4 * k), "y": cy - int(26 * k),
             "w": int(48 * k), "h": int(22 * k)},
            {"class": "TabStrip", "text": "__tabstrip__",
             "x": app.notebook.winfo_rootx() - l,
             "y": app.notebook.winfo_rooty() - t,
             "w": app.notebook.winfo_width(), "h": 26},
        ]

    # Shot names come from each tab's STABLE SLUG (gui.MANUAL_TABS), never
    # from its display label or its position in the notebook. They used to
    # be f"{i+1:02d}_{label-with-non-alnum-underscored}", which made every
    # consumer -- annotate.py's S[...] keys, build_manual.py's figure keys --
    # break on a tab rename or a reorder. `#30` (rename Data Logging) is
    # exactly that trap. See docs/manual-src/README.md "Tab slugs".
    tabs = []
    for tab_id in app.notebook.tabs():
        label = app.notebook.tab(tab_id, "text")
        tab_w = root.nametowidget(tab_id)
        slug = getattr(tab_w, "manual_slug", None)
        if not slug:
            # Fail closed. An untagged tab is either a NEW tab whose slug
            # nobody added, or a tab that failed to BUILD (gui.py leaves
            # the error placeholder untagged on purpose) -- photographing
            # either one ships a wrong manual page under a right-looking
            # name.
            sys.exit(
                f"capture.py FAILED -- notebook tab {label!r} carries no "
                "manual_slug.\n"
                "  A new tab: add it to MANUAL_TABS in gui.py (and give it "
                "a content.json entry + a section in build_manual.py).\n"
                "  An '(unavailable)' tab: the app did not start cleanly -- "
                "fix that first; the manual is built from a healthy app.")
        tabs.append({"slug": slug, "label": label})
        app.notebook.select(tab_id)
        root.update_idletasks()
        root.update()
        time.sleep(0.45)
        root.update()
        entry = capture_window(root, f"tab_{slug}", _extras())
        entry["tab"] = label
        entry["slug"] = slug
        # Tall scrollable tab? Grab a second, scrolled-to-bottom view.
        canvas = getattr(tab_w, "_canvas", None)
        body = getattr(tab_w, "body", None)
        if canvas is not None and body is not None:
            if body.winfo_reqheight() > canvas.winfo_height() + 12:
                canvas.yview_moveto(1.0)
                root.update_idletasks()
                root.update()
                time.sleep(0.35)
                e2 = capture_window(root, f"tab_{slug}_bottom", _extras())
                e2["tab"] = label + " (scrolled)"
                e2["slug"] = slug + "_bottom"
                canvas.yview_moveto(0.0)
                root.update()

    # -- arb editor + export dialogs ----------------------------------
    try:
        from arb_editor import ArbWaveformEditor
        import arb_build as ab
        ed = ArbWaveformEditor(app, 1)
        ed.attributes("-topmost", True)
        ed.update()
        # Preload a realistic drive pulse so the preview isn't a flat line.
        try:
            r = ed.recipe
            for (px, py) in ((0.15, 8.0), (0.45, 8.0), (0.55, 3.0),
                             (0.75, 3.0), (0.85, 0.0)):
                r = ab.add_point(r, px, py)
            ed._commit(r)
            ed.update()
        except Exception as ex:
            print("arb preload failed:", ex)
        time.sleep(0.6)
        e = capture_window(ed, "20_arb_editor")
        e["tab"] = "Arbitrary Waveform Editor"
        try:
            from arb_editor import BinExportDialog
            dlg = BinExportDialog(ed)
            dlg.attributes("-topmost", True)
            dlg.update()
            time.sleep(0.4)
            e2 = capture_window(dlg, "21_arb_bin_export")
            e2["tab"] = "Export .bin for 4055B flash drive"
            dlg.destroy()
        except Exception as ex:
            print("bin export dialog failed:", ex)
        try:
            from arb_editor import EasyWaveXExportDialog
            dlg = EasyWaveXExportDialog(ed)
            dlg.attributes("-topmost", True)
            dlg.update()
            time.sleep(0.4)
            e3 = capture_window(dlg, "22_arb_easywavex_export")
            e3["tab"] = "Export for EasyWaveX"
            dlg.destroy()
        except Exception as ex:
            print("easywavex dialog failed:", ex)
        ed.destroy()
    except Exception as ex:
        print("arb editor failed:", ex)

    # Replaces the old "tab_names" list of bare display strings: the slug is
    # the identity, the label rides along as data.
    manifest["tabs"] = tabs                      # [{"slug", "label"}, ...]
    with open(os.path.join(OUT, "widgets.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    print("DONE", len(manifest["images"]), "images")
    root.destroy()
    os._exit(0)


if __name__ == "__main__":
    main()
