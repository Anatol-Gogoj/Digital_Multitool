# Manual regeneration pipeline

`../digital-multitool-manual.html` is the illustrated user manual — a single
self-contained file (all screenshots embedded as base64). It was built from
the **live app** at v0.32.2+9725a59 on 2026-08-02: every screenshot is a real
capture and every red callout is anchored to the actual widget's on-screen
coordinates. When the GUI changes visibly, regenerate rather than hand-edit.

## The three stages

| Script | What it does | Output (in `build/`, untracked) |
|---|---|---|
| `capture.py` | Launches the real `gui.py` (window pops up briefly), screenshots the splash, all 9 tabs, the Arb Editor and both export dialogs, and records the bbox of every labelled widget | `shots/*.png`, `shots/widgets.json` |
| `capture_edge_review.py` | Opens Edge Review on a real run (defaults to bench run 1), runs a blocking detection pass, screenshots a frame showing all three candidates. Never clicks Save | `shots/40_edge_review.png` (+ appends to `widgets.json`) |
| `capture_tuner_dialog.py` | Screenshots the Tune-params advanced-tool gate, then takes the Cancel path | `shots/41_tuner_warning.png` |
| `annotate.py` | Draws the red capsules, arrows and numbered badges from curated per-image specs, matching callouts to exact widget `text=` strings | `annotated/*.png`, `annotated/legends.json` |
| `build_manual.py` | Assembles the HTML from `content.json` (the manual copy) + legends + images | `../digital-multitool-manual.html`, `sections.json` |
| `make_pdf.py` | Renders the HTML to the hand-out PDF via headless Edge, then adds chapter bookmarks, clickable contents, running footers with page numbers, and metadata. `<details>` tables are forced open so the PDF is complete | `../digital-multitool-manual.pdf` |

## Regenerating

Windows, with a Python 3.10+ that has tkinter ("tcl/tk and IDLE" ticked):

```
py -3 -m venv .venv
.venv\Scripts\pip install numpy pillow opencv-python-headless pandas matplotlib openpyxl pyvisa pyvisa-py pyserial pypdf reportlab
.venv\Scripts\python capture.py
.venv\Scripts\python capture_edge_review.py     [run folder]
.venv\Scripts\python capture_tuner_dialog.py
.venv\Scripts\python "%REPO%\sldea_tuner.py" --selftest build\shots\30_tuner_selftest.png
.venv\Scripts\python "%REPO%\sldea_diag.py"  --selftest build\shots\31_diag_selftest.png
.venv\Scripts\python annotate.py
.venv\Scripts\python build_manual.py
.venv\Scripts\python make_pdf.py
```

**Hand the PDF to people** (`docs/digital-multitool-manual.pdf`) — it is the
labmate-facing copy: cover + clickable contents, one chapter per page run,
bookmarks sidebar, running footer with section + page numbers. The HTML is
the same content for browser use and stays the build source. Keep both
committed and regenerate them together. `make_pdf.py` needs Microsoft Edge
on the machine (used headless as the renderer) and works while Edge is open.

Notes:

- `capture.py` needs a **headed** desktop session (it screenshots the actual
  window; a locked screen or RDP-disconnected session gives black images).
  It is DPI-aware and forces the window topmost. On Windows the app runs in
  view/edit mode, so no instrument is ever touched.
- Watch `annotate.py`'s output for `!! no match` lines — a renamed button
  means its spec in the `S[...]` tables needs the new `text=` string.
- `content.json` is the manual's written copy (per-tab purpose, controls,
  steps, cautions). Edit it directly for wording changes — several entries
  were **corrected after a code audit** (notably: closing the app does NOT
  switch off the DC supply output, and a live SLDEA run only gets a
  best-effort ~3 s ramp — keep the shutdown wording precise).
- `annotate.py` uses `C:/Windows/Fonts/arialbd.ttf`; on another OS point it
  at any bold TrueType font.
- After rebuilding, spot-check the annotated PNGs in `build/annotated/` —
  layout drift can put a badge on top of a label. Badge placement is
  automatic but overridable per callout with `badge_side` (`left`/`right`/
  `top`/`bottom`/`tl`/`tr`/`bl`/`br`) or an exact `badge_at: [x, y]`.
- `capture_edge_review.py` needs a hydrated run folder with frames. It runs
  a real detection pass (~15 s for 81 frames) and never clicks Save, so the
  run's `data.csv` and `setup.txt` are left alone.
