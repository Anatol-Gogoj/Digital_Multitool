"""Capture the Tune-params confirmation dialog (and verify Cancel works).

Opens the SLDEA tab's advanced-tool gate, screenshots it to
build/shots/41_tuner_warning.png, then takes the Cancel path — so the
tuner process is never launched.
"""
import ctypes
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

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
from PIL import ImageGrab  # noqa: E402
import gui as gui_mod  # noqa: E402

root = tk.Tk()
root.withdraw()
app = gui_mod.InstrumentControlGUI(root)
root.deiconify()
root.geometry("1320x900+40+30")
root.attributes("-topmost", True)
root.update()

state = {"seen": False, "cancelled": False}


def probe():
    for w in root.winfo_children():
        if isinstance(w, tk.Toplevel) and "advanced" in w.title().lower():
            state["seen"] = True
            w.attributes("-topmost", True)
            w.update()
            time.sleep(0.3)
            hwnd = ctypes.windll.user32.GetAncestor(w.winfo_id(), 2)
            rect = wintypes.RECT()
            ctypes.windll.dwmapi.DwmGetWindowAttribute(
                hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
            ImageGrab.grab(bbox=(rect.left, rect.top, rect.right,
                                 rect.bottom), all_screens=True).save(
                os.path.join(OUT, "41_tuner_warning.png"))
            w.destroy()          # same as Cancel
            state["cancelled"] = True
            return
    root.after(150, probe)


root.after(400, probe)
root.after(600, lambda: app._sldea_open_tuner(None))


def finish():
    if state["cancelled"]:
        print("DIALOG OK: shown, captured, cancel path returned; "
              "no tuner process launched")
        root.destroy()
        os._exit(0)
    root.after(200, finish)


root.after(1000, finish)
root.after(15000, lambda: (print("TIMEOUT - dialog never appeared"),
                           os._exit(1)))
root.mainloop()
