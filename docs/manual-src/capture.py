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
    img.save(path)
    top = widget.winfo_toplevel()
    widgets = []
    _walk(top, l, t, widgets)
    if extra_widgets:
        widgets.extend(extra_widgets)
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
    root.withdraw()

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
    app = gui_mod.InstrumentControlGUI(root)
    root.deiconify()
    h = min(1000, root.winfo_screenheight() - 90)
    root.geometry(f"1320x{h}+40+30")
    root.attributes("-topmost", True)
    root.update_idletasks()
    root.update()
    time.sleep(0.8)

    def _extras():
        l, t, _, _ = _win_rect(root)
        cx = root.winfo_rootx() - l
        cy = root.winfo_rooty() - t
        return [
            {"class": "Menu", "text": "Tools",
             "x": cx + 4, "y": cy - 26, "w": 48, "h": 22},
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
