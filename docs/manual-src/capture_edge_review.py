"""Screenshot the SLDEA Edge Review GUI on a real run for the manual.

Opens sldea_edge_gui.EdgeReviewApp on a bench run, runs the blocking
detection pass, positions on a frame with all three machine candidates,
captures the window and appends its widget map to build/shots/widgets.json.
Never clicks Save — nothing in the run folder is modified except what the
detector itself writes (setup.txt is untouched; picks are in-memory only).

Usage: python capture_edge_review.py [run_dir]   (defaults to bench run 1)
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
REPO = os.path.dirname(os.path.dirname(_HERE))
OUT = os.path.join(_HERE, "build", "shots")
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, REPO)
os.chdir(REPO)

import tkinter as tk  # noqa: E402
from tkinter import messagebox  # noqa: E402
from PIL import ImageGrab  # noqa: E402

for _name in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, _name, lambda *a, **k: print(f"[msgbox] {a}"))
for _name in ("askyesno", "askokcancel"):
    setattr(messagebox, _name, lambda *a, **k: False)


def _win_rect(widget):
    hwnd = ctypes.windll.user32.GetAncestor(widget.winfo_id(), 2)
    rect = wintypes.RECT()
    try:
        res = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
        if res != 0:
            raise OSError(res)
    except Exception:
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def _walk(widget, ox, oy, out):
    for child in widget.winfo_children():
        try:
            w, h = child.winfo_width(), child.winfo_height()
            text = ""
            try:
                text = str(child.cget("text"))
            except Exception:
                pass
            if (w > 1 and h > 1 and child.winfo_viewable()
                    and not text.startswith("PY_VAR")):
                out.append({"class": child.winfo_class(), "text": text,
                            "x": child.winfo_rootx() - ox,
                            "y": child.winfo_rooty() - oy, "w": w, "h": h})
        except Exception:
            continue
        _walk(child, ox, oy, out)


def main():
    import sldea_edge as se
    import sldea_edge_gui as eg

    run = sys.argv[1] if len(sys.argv) > 1 else se.BENCH_RUNS.get("1")
    if not run or not os.path.isdir(run):
        print("no run dir available:", run)
        sys.exit(2)
    print("run:", run)

    root = tk.Tk()
    root.geometry("1150x760+40+30")
    app = eg.EdgeReviewApp(root, path=run, auto=False)
    root.attributes("-topmost", True)
    root.update_idletasks()
    root.update()

    t0 = time.time()
    app.detect_all_sync()
    print(f"detection done in {time.time() - t0:.0f}s")
    root.update_idletasks()
    root.update()

    # Prefer a frame where all three machine candidates exist.
    try:
        rich = next((i for i in app.frame_rows
                     if len(app.cands_all.get(i, [])) >= 3), None)
        if rich is not None:
            app.pos = app.frame_rows.index(rich)
            app._show()
    except Exception as e:
        print("frame pick fallback:", e)
    root.update_idletasks()
    root.update()
    time.sleep(0.6)          # let the resize-debounced card settle
    root.update()

    l, t, r, b = _win_rect(root)
    img = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)
    path = os.path.join(OUT, "40_edge_review.png")
    img.save(path)
    widgets = []
    _walk(root, l, t, widgets)
    entry = {"name": "40_edge_review", "file": path,
             "img_w": img.size[0], "img_h": img.size[1],
             "origin": [l, t], "client_offset": [0, 0],
             "widgets": widgets, "tab": "SLDEA Edge Review"}

    mpath = os.path.join(OUT, "widgets.json")
    manifest = json.load(open(mpath, encoding="utf-8"))
    manifest["images"] = [i for i in manifest["images"]
                          if i["name"] != "40_edge_review"] + [entry]
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    print("captured 40_edge_review:", img.size, len(widgets), "widgets")
    root.destroy()
    os._exit(0)


if __name__ == "__main__":
    main()
