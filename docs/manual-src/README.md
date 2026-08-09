# Manual regeneration pipeline

`../digital-multitool-manual.html` is the illustrated user manual — a single
self-contained file (all screenshots embedded as base64). It was last built
from the **live app** at v1.2.0+91f5bfd-era tree on 2026-08-08 (59 pages incl. Part II): every
screenshot is a real capture and every red callout is anchored to the actual
widget's on-screen coordinates. When the GUI changes visibly, regenerate
rather than hand-edit. This line is easy to forget — check it against the
manual's own footer after every rebuild.

## The three stages

| Script | What it does | Output (in `build/`, untracked) |
|---|---|---|
| `capture.py` | Launches the real `gui.py` (window pops up briefly), screenshots the splash, all 9 tabs, the Arb Editor and both export dialogs, and records the bbox of every labelled widget | `shots/*.png`, `shots/widgets.json` |
| `capture_edge_review.py` | Opens Edge Review on a real run (defaults to bench run 1), runs a blocking detection pass, screenshots a frame showing all three candidates. Never clicks Save | `shots/40_edge_review.png` (+ appends to `widgets.json`) |
| `capture_tuner_dialog.py` | Screenshots the Tune-params advanced-tool gate, then takes the Cancel path | `shots/41_tuner_warning.png` |
| `annotate.py` | Draws the red capsules, arrows and numbered badges from curated per-image specs, matching callouts to exact widget `text=` strings | `annotated/*.png`, `annotated/legends.json` |
| `build_manual.py` | Assembles the HTML from `content.json` (the manual copy) + legends + images, then appends the Part II chapters from `addendum_*.json` | `../digital-multitool-manual.html`, `sections.json` |
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
.venv\Scripts\python "%REPO%\sldea_plot.py"  --selftest build\shots\32_plot_selftest.png
.venv\Scripts\python annotate.py
.venv\Scripts\python build_manual.py
.venv\Scripts\python make_pdf.py
```

## Part II — the "How it works" addendum

The tab chapters (Part I) answer *how do I drive this?*. Part II answers *how
does it work?*, for the labmate who has to understand or extend the stack
rather than operate it. Those chapters are **prose, not captures**, so they
live outside `content.json`: one file per chapter, `addendum_a_*.json`,
`addendum_b_*.json`, … in this folder. `build_manual.py` renders them in
filename order after the tab chapters, and — because they join `SECTIONS`
before `sections.json` is written — they pick up the print contents entry,
the PDF bookmark and the running footer with no change to `make_pdf.py`.

```
{"id": "addendum-stack",                    # slug; the HTML anchor
 "title": "How it works — the ...",         # the <h2>, and the PDF bookmark
 "nav": "The instrument stack",             # optional short sticky-nav label
 "sections": [{"heading": "...",                             # required
               "paras":   ["...", ...],                      # optional
               "bullets": ["...", ...],                      # optional
               "table":   {"cols": [...], "rows": [[...]]},  # optional
               "code":    "verbatim block"}]}                # optional
```

- **No addendum files is a valid manual** — the build simply has no Part II.
- **A malformed file fails the build (exit 1) naming the file**, in the same
  fail-closed spirit as `annotate.py`. That includes an *unknown* key: a
  chapter that needs one teaches `build_manual.py` to render it in the same
  PR, rather than shipping a chapter with a paragraph silently missing.
- **Keep the title to one printed line.** `make_pdf.py` locates a chapter's
  page by matching the title in the extracted page text; a wrapped `<h2>`
  extracts with a newline through the middle and loses its bookmark (it says
  so — `!! section not located`, and the bookmark tally at the end drops
  below `n/n`). Check that tally after adding a chapter.
- Prose blocks reuse the manual's own classes (`band`, `subh`, `tblwrap`),
  so a Part II chapter looks native next to a tab chapter. Table column
  names render in the control-table style — keep them short.

**Hand the PDF to people** (`docs/digital-multitool-manual.pdf`) — it is the
labmate-facing copy: cover + clickable contents, one chapter per page run,
bookmarks sidebar, running footer with section + page numbers. The HTML is
the same content for browser use and stays the build source. Keep both
committed and regenerate them together. `make_pdf.py` needs Microsoft Edge
on the machine (used headless as the renderer) and works while Edge is open.

## Releasing

**Every release ships both manuals.** After bumping `__version__` in the
repo's `version.py` (and committing, so the footer hash is real), re-run the
full pipeline above and commit the regenerated
`docs/digital-multitool-manual.html` **and** `.pdf` in the release PR. The
cover, build line and version callout all read `version.py` automatically —
there is nothing to edit by hand, but screenshots keep the old version stamp
in their footers until the pipeline is re-run, so a release without a manual
regeneration ships docs that contradict the app. Attach the fresh PDF to the
GitHub release so labmates always download the matching copy.

**Edge Review's ❓ How to use panel is a HAND-KEPT COPY of workflow prose**
(`#238`). Its words live in `HOWTO_SECTIONS` in `sldea_edge_gui.py`, not in
`content.json` — deliberately, so the panel ships in the same commit as the
code it describes instead of lagging by a release (this file's own Edge
Review copy still described the pre-`#215` two-click calibration long after
the app had stopped doing it). Nothing enforces the two staying in step, so
**when the review workflow changes, change both**: `HOWTO_SECTIONS` and the
`Companion tools` entries here. The panel names on-screen controls by their
exact labels; those are listed in `HOWTO_QUOTED_CONTROLS` beside it and the
GUI tests fail if one stops being a real widget label.

Notes:

- `capture.py` needs a **headed** desktop session (it screenshots the actual
  window; a locked screen or RDP-disconnected session gives black images).
  It is DPI-aware and forces the window topmost. On Windows the app runs in
  view/edit mode, so no instrument is ever touched.
- `annotate.py` **fails (exit 1) when any callout string matches no widget**:
  it lists every miss and deletes `annotated/legends.json`, so a chained
  `build_manual.py` stops instead of assembling the manual from the previous
  run's legends. A renamed control means its spec in the `S[...]` tables
  needs the new literal `text=` string; stale screenshots mean the capture
  stage needs re-running first. (Until 2026-08-07 a miss only printed
  `!! no match` and the callout silently vanished from the shipped manual —
  the 📏 Calibrate… callout was lost that way when the button grew
  " / re-anchor".)
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
