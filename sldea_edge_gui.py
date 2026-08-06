#!/usr/bin/env python3
"""SLDEA Edge Review -- offline edge-detection GUI for SLDEA runs.

The companion program to the Digital Multitool's SLDEA tab: point it at a run
directory (SLDEA_<ts>/), it traces the active-area disc in every frame
(difference-imaging vs the 0 kV baseline + a Hough candidate), auto-accepts
confident detections, and queues the shaky ones for a human pick -- each
candidate outline is drawn over the photo and the user chooses A/B/C, a
hand-traced candidate D, or Reject. Breakdown heuristics (current spike,
area collapse) annotate suspect
steps. Results are written back to the run's data.csv only after an explicit
prompt (a .bak is kept), together with an area-vs-voltage plot and outline
overlays for audit.

    python sldea_edge_gui.py [run-or-parent-dir] [--auto]

SCALE GATE (operator decision 2026-08-05): the camera zoom moves between
runs, so every run's px→mm anchor is clicked by hand — Detect diverts to
the 📏 Calibrate dialog until the resting disc has been measured on THIS
run's baseline frame, Save hard-blocks without it, and the anchor resets
on every run switch. The manual calibration overrides every automatic
reference at Save (it used to be silently ignored when the baseline row
had an accepted result); the automatic disc fit is demoted to a
cross-check that warns when it disagrees with the clicks by >3%.

With --auto (used by the SLDEA tab's "auto process"), the calibrate
dialog opens on launch and detection chains automatically once the two
clicks land. Keyboard: 1/2/3 pick a candidate, R reject,
4/D/T open the manual tracer (#162/#172 -- its Done stages the polygon
as candidate D; Accept commits it like any other candidate),
Left/Right navigate, Enter accept + next.
"""
import os
import sys
import threading
import time
import queue as _queue
import tk_fontfix                      # must precede tkinter:
tk_fontfix.apply()                     # colour emoji crash Tk
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont

import numpy as np

import sldea_edge as se
import sldea_trace as strc

DEFAULT_PARENT = os.environ.get('SCPI_SLDEA_DIR',
                                '/mnt/shareDrive/robot_incubator/SLDEA_data')
# A green, B blue, C orange, D magenta (D = the manual trace, #172)
CAND_COLORS = ['#00c853', '#2196f3', '#ff9100', '#e040fb']
CAND_KEYS = ['A', 'B', 'C', 'D']
TRACE_SLOT = 3          # radio value / paint slot of the manual trace
VIEW_W = 780            # initial card view only -- once mapped, the card
VIEW_H = 560            # tracks the LIVE canvas size (#178)
MAX_UPSCALE = 2.0       # card upscale cap: past ~2x native a big monitor
                        # only interpolates mush (#178)
TAG_PX = 20             # letter-tag font size on the review card (#173)
SIDE_W = 330            # right panel width -- FIXED, propagation off (#179)
RADIO_TEXT_PX = SIDE_W - 100   # text budget in a candidate radio row: the
                               # panel + LabelFrame padding, colour swatch
                               # and radio indicator eat ~100 px of the row
INFO_LINES = 5          # info label height (text lines): 3 fixed lines +
                        # room for a flag line and its wrap -- a flag must
                        # change content, not layout (#179)

_TAG_FONT = None


def _tag_font():
    """Bold letter-tag font for the review card (#173: the default PIL
    font was unreadably small on 1080p frames downscaled to the card).
    Cached; falls back to PIL's builtin when no TrueType font resolves."""
    global _TAG_FONT
    if _TAG_FONT is None:
        from PIL import ImageFont
        for name in ('arialbd.ttf', 'DejaVuSans-Bold.ttf', 'arial.ttf',
                     'DejaVuSans.ttf'):
            try:
                _TAG_FONT = ImageFont.truetype(name, TAG_PX)
                break
            except OSError:
                continue
        else:
            try:
                _TAG_FONT = ImageFont.load_default(TAG_PX)
            except TypeError:              # Pillow < 10.1: no size arg
                _TAG_FONT = ImageFont.load_default()
    return _TAG_FONT


def card_geometry(img_w, img_h, view_w, view_h, max_upscale=MAX_UPSCALE):
    """Contain-fit an img_w x img_h frame in a view_w x view_h canvas
    (#178): aspect kept, upscale capped at max_upscale, centered.
    Returns (scale, w, h, x, y) with (x, y) the card's top-left inside
    the view. Pure so the math is testable without Tk."""
    scale = min(view_w / float(img_w), view_h / float(img_h), max_upscale)
    w = max(1, int(round(img_w * scale)))
    h = max(1, int(round(img_h * scale)))
    return scale, w, h, (view_w - w) // 2, (view_h - h) // 2


def elide(text, width_px, measure):
    """Longest prefix of `text` (plus an ellipsis) that `measure`s within
    width_px. The side panel is a fixed box (#179): text must fit the
    panel, never size it -- the tail (the wrinkle term, the point count)
    is the sacrificial end."""
    if measure(text) <= width_px:
        return text
    for n in range(len(text) - 1, 0, -1):
        s = text[:n].rstrip() + '…'
        if measure(s) <= width_px:
            return s
    return '…'


def hot_slot(entries, chosen, sel):
    """Which outline reads as SELECTED on the card. `entries` is
    [(slot, candidate)], `chosen` the frame's accepted result (or None),
    `sel` the radio selection (a slot). An accepted frame follows its
    result; an unreviewed frame follows the radio -- candidate A used to
    render at the thin weight until its already-selected radio was
    clicked, because only an accepted result set the weight (#171)."""
    if chosen:
        for slot, c in entries:
            if c['method'] == chosen['method']:
                return slot
    if any(slot == sel for slot, _c in entries):
        return sel
    return None


class EdgeReviewApp:
    def __init__(self, root, path=None, auto=False):
        self.root = root
        root.title("SLDEA Edge Review — Digital Multitool")
        root.geometry("1150x760")
        self.settings = dict(se.DEFAULT_SETTINGS)
        self.run = None
        self.rundir = None
        self.cands_all = {}     # frame row index -> candidate list
        self.results = {}       # row index -> chosen candidate | None=rejected
        self.traces = {}        # row index -> STAGED candidate D (#172)
        self._select_trace_once = False   # next _show selects D (just staged)
        self.auto_idx = set()   # auto-accepted row indices
        self.auto_rej = set()   # auto-rejected (no change / no edge)
        self.load_fail = {}     # row -> 'unreadable' | 'processing
        # failed: …' — frames not MEASURED this pass for file- or
        # code-level reasons, never a measurement verdict (audit
        # 2026-08-05: these used to launder into 'no change vs baseline'
        # / 'rejected (no reliable edge)'; the reason is kept so a
        # processing crash is not misreported as a missing file)
        self.frame_rows = []    # row indices that have a frame file
        self.pos = 0
        self.flags = {}         # CONFIRMED breakdown rows (rename + brand)
        self.advisories = {}    # notes-only (transient / uncorroborated)
        self.manual_ref = None  # px→mm anchor from 📏 — the SCALE GATE;
        self.base_ref = None    # reset per run (zoom moves between runs)
        self._base_ref_pending = None
        self._photo = None
        self._detq = _queue.Queue()
        # Detect-in-flight guard (audit 2026-08-05, critical): the Run
        # combobox and Browse… stayed live during a multi-minute detect,
        # and the stale worker/poll chain refilled cands_all, base_ref
        # and the Save button AFTER _pick_run's fail-closed reset —
        # writing run A's px areas through run B's anchor. Run switching
        # is disabled while a worker runs, and every queue item carries a
        # generation token so a stale chain can never resurrect state.
        self._detect_busy = False
        self._detect_gen = 0
        # auxiliary windows are modal or SINGLETON, never unbounded (#176)
        self._adv_win = None
        self._cal_win = None    # the gate dialog is a singleton too: the
        # grab is pointer-only, so review keys can pierce it and a second
        # gate dialog would chain a second detect worker (review 2026-08-05)
        self._build_ui()
        start = path or DEFAULT_PARENT
        self._populate_runs(start)
        if auto and self.rundir:
            root.after(300, self.detect)

    # ---------------- UI scaffolding ----------------
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill='x')
        ttk.Label(top, text="Run:").pack(side=tk.LEFT)
        self.run_box = ttk.Combobox(top, width=44, state='readonly')
        self.run_box.pack(side=tk.LEFT, padx=6)
        self.run_box.bind('<<ComboboxSelected>>', lambda _e: self._pick_run())
        self.browse_btn = ttk.Button(top, text="Browse…",
                                     command=self._browse)
        self.browse_btn.pack(side=tk.LEFT)
        self.detect_btn = ttk.Button(top, text="▶ Detect Edges",
                                     command=self.detect)
        self.detect_btn.pack(side=tk.LEFT, padx=10)
        # ONE settings-editing path in Edge Review: Advanced… covers every
        # knob with Apply+Save. The Tune button was removed (operator
        # decision 2026-07-31) — the tuner is a development instrument,
        # launched directly (deploy/Tune_SLDEA_Windows.bat unchanged).
        ttk.Button(top, text="Advanced…",
                   command=self._advanced).pack(side=tk.LEFT)
        ttk.Button(top, text="📏 Calibrate…",
                   command=self._calibrate_scale).pack(side=tk.LEFT,
                                                       padx=(6, 0))
        self.save_btn = ttk.Button(top, text="💾 Save to data.csv…",
                                   command=self.save, state='disabled')
        self.save_btn.pack(side=tk.RIGHT)
        # progress + session clock (from Detect until Save)
        self.clock_lbl = tk.Label(top, text="", fg='#1f3a5f',
                                  font=('TkDefaultFont', 10, 'bold'))
        self.clock_lbl.pack(side=tk.RIGHT, padx=10)
        self.prog = ttk.Progressbar(top, length=180, mode='determinate')
        self.prog.pack(side=tk.RIGHT, padx=6)
        self._t0 = None
        self._clock_on = False

        mid = ttk.Frame(self.root)
        mid.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(mid, width=VIEW_W, height=VIEW_H, bg='#222',
                                highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill='both', expand=True,
                         padx=(6, 0), pady=4)
        # the card follows the canvas, not a constant (#178): re-render on
        # resize, debounced -- <Configure> streams during a drag
        self._view_wh = (VIEW_W, VIEW_H)
        self._resize_job = None
        self.canvas.bind('<Configure>', self._canvas_resized)

        side = ttk.Frame(mid, padding=8, width=SIDE_W)
        side.pack(side=tk.RIGHT, fill='y')
        # FIXED box (#179): with geometry propagation on, the width above
        # is inert and the panel tracked its widest child -- the radio
        # text, which changes every frame -- sliding the buttons out from
        # under a rapid-clicking cursor
        side.pack_propagate(False)
        self._side = side
        self._side_font = tkfont.nametofont('TkDefaultFont')
        self.info = tk.Label(side, text="pick a run and Detect",
                             justify='left', anchor='nw',
                             font=('TkDefaultFont', 10),
                             height=INFO_LINES, wraplength=SIDE_W - 24)
        self.info.pack(fill='x', pady=(0, 6))
        self.cand_var = tk.IntVar(value=0)
        self.cand_frame = ttk.LabelFrame(side, text="Candidates", padding=6)
        self.cand_frame.pack(fill='x')
        self.cand_radios = []
        for k in range(4):
            row = ttk.Frame(self.cand_frame)
            row.pack(fill='x')
            # swatch carries the color; the TEXT stays readable (colored
            # label text was 1.6:1 and the mapping was color-only — audit
            # 2026-07-25; letters are also drawn ON the image now)
            tk.Label(row, width=2, bg=CAND_COLORS[k],
                     text=CAND_KEYS[k], fg='black').pack(side='left',
                                                         padx=(0, 4))
            rb = tk.Radiobutton(
                row, text="—", anchor='w',
                variable=self.cand_var, value=k,
                # D is a tool, not a precomputed candidate: its radio
                # opens the tracer; Done stages, Accept commits (#172)
                command=self._trace if k == TRACE_SLOT
                else self._choose_current)
            rb.pack(side='left', fill='x', expand=True)
            self.cand_radios.append(rb)
        bt = ttk.Frame(side)
        bt.pack(fill='x', pady=6)
        ttk.Button(bt, text="✔ Accept (Enter)",
                   command=self._accept_next).pack(side=tk.LEFT)
        ttk.Button(bt, text="✘ Reject (R)",
                   command=self._reject).pack(side=tk.LEFT, padx=6)
        nav = ttk.Frame(side)
        nav.pack(fill='x')
        ttk.Button(nav, text="◀ Prev",
                   command=lambda: self._step(-1)).pack(side=tk.LEFT)
        ttk.Button(nav, text="Next ▶",
                   command=lambda: self._step(+1)).pack(side=tk.LEFT, padx=6)
        ttk.Button(nav, text="Next unreviewed",
                   command=self._next_unreviewed).pack(side=tk.LEFT)
        self.queue_lbl = tk.Label(side, text="", fg='#8a5a00', anchor='w',
                                  justify='left')
        self.queue_lbl.pack(fill='x', pady=(8, 0))
        self.status = tk.Label(self.root, text="idle", bd=1, relief=tk.SUNKEN,
                               anchor='w')
        self.status.pack(side=tk.BOTTOM, fill='x')

        for key, fn in (('<Key-1>', lambda e: self._pick_k(0)),
                        ('<Key-2>', lambda e: self._pick_k(1)),
                        ('<Key-3>', lambda e: self._pick_k(2)),
                        ('<Key-a>', lambda e: self._pick_k(0)),
                        ('<Key-b>', lambda e: self._pick_k(1)),
                        ('<Key-c>', lambda e: self._pick_k(2)),
                        ('<Key-r>', lambda e: self._reject()),
                        ('<Key-R>', lambda e: self._reject()),
                        ('<Key-4>', lambda e: self._trace()),
                        ('<Key-d>', lambda e: self._trace()),
                        ('<Key-D>', lambda e: self._trace()),
                        ('<Key-t>', lambda e: self._trace()),
                        ('<Key-T>', lambda e: self._trace()),
                        ('<Return>', lambda e: self._accept_next()),
                        ('<Left>', lambda e: self._step(-1)),
                        ('<Right>', lambda e: self._step(+1))):
            self.root.bind(key, fn)

    # ---------------- run selection ----------------
    def _list_runs(self, parent):
        # Any directory holding a run CSV is a run — custom-named runs
        # (the SLDEA tab allows free names) were invisible before and
        # auto-open silently fell back to the newest SLDEA_* run instead
        # (audit 2026-07-25). se.run_csv also accepts a renamed data1.csv /
        # data2.csv, which the bench uses to open several runs in Excel at
        # once (2026-07-28).
        try:
            names = sorted(
                (n for n in os.listdir(parent)
                 if os.path.isdir(os.path.join(parent, n)) and
                 se.run_csv(os.path.join(parent, n))),
                reverse=True)
        except OSError:
            return []
        out = []
        for n in names:
            done = ''
            try:
                with open(se.run_csv(os.path.join(parent, n))) as f:
                    # length-guarded: a truncated/blank line used to raise
                    # IndexError and crash the whole listing
                    if 'active_area_px' in (f.readline() or '') and any(
                            len(c := line.split(',')) > 10 and c[10].strip()
                            for line in f):
                        done = '  ✓ processed'
            except OSError:
                pass
            out.append(n + done)
        return out

    def _populate_runs(self, path):
        """Accept a run dir (holds a run CSV) or a parent full of runs."""
        path = os.path.abspath(path)
        if se.run_csv(path):
            self.parent = os.path.dirname(path)
            preselect = os.path.basename(path)
        else:
            self.parent = path
            preselect = None
        runs = self._list_runs(self.parent)
        self.run_box['values'] = runs
        if runs:
            want = 0
            if preselect:
                for i, r in enumerate(runs):
                    if r.split('  ')[0] == preselect:
                        want = i
                        break
                else:
                    # NEVER silently fall back to a different run when an
                    # explicit target was given (audit 2026-07-25: auto-open
                    # used to process the newest run instead).
                    self.status.config(
                        text=f"target run '{preselect}' not found in "
                             f"{self.parent} — pick one manually")
                    return
            self.run_box.current(want)
            self._pick_run()
        else:
            self.status.config(text=f"no runs (dirs holding a data CSV) "
                                    f"in {self.parent}")

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.parent or DEFAULT_PARENT)
        if d:
            self._populate_runs(d)

    def _detect_ui(self, busy):
        """Run switching is closed while a detect worker runs — the
        combobox and Browse… used to stay live and cross-contaminate the
        freshly picked run with the old worker's output (audit
        2026-08-05)."""
        self.detect_btn.config(state='disabled' if busy else 'normal')
        self.run_box.config(state='disabled' if busy else 'readonly')
        self.browse_btn.config(state='disabled' if busy else 'normal')

    def _pick_run(self):
        name = (self.run_box.get() or '').split('  ')[0]
        if not name:
            return
        self.rundir = os.path.join(self.parent, name)
        # Fail CLOSED: reset the review state and the SCALE GATE before
        # anything that can raise -- an exception mid-load used to leave
        # the new run paired with the previous run's manual anchor,
        # results and live Save button (review 2026-08-05: that writes
        # run A's scale into run B, the exact error the gate prevents).
        # A programmatic switch mid-detect also invalidates the worker:
        # the generation bump makes every queued item stale, and
        # _base_ref_pending can never carry a previous run's disc into
        # _finish_detect (audit 2026-08-05).
        self._detect_gen += 1
        self._detect_busy = False
        self._base_ref_pending = None
        self._detect_ui(busy=False)
        self.run = None
        self.frame_rows = []
        self.cands_all, self.results, self.flags = {}, {}, {}
        self.advisories = {}
        self.traces = {}
        self.auto_idx, self.auto_rej = set(), set()
        self.load_fail = {}
        self.base_ref = None
        self.manual_ref = None
        self.pos = 0
        self.save_btn.config(state='disabled')
        try:
            self.run = se.load_run(self.rundir)
            self.settings = se.load_settings(self.rundir)
        except Exception as e:
            messagebox.showerror("Run", f"Cannot read {name}: {e}")
            self.run = None
            return
        self.frame_rows = [i for i, r in enumerate(self.run['rows'])
                           if (r.get('frame_file') or '').strip()]
        n = len(self.frame_rows)
        # the CSV listing a frame does not mean the disk holds it —
        # count the missing ones up front instead of discovering them as
        # blank cards mid-review (audit 2026-08-05)
        missing = sum(
            1 for i in self.frame_rows
            if not os.path.exists(se.frame_path(self.run,
                                                self.run['rows'][i]) or ''))
        miss_txt = (f" ({missing} MISSING on disk — kept unreadable, "
                    f"never re-measured)" if missing else "")
        self.status.config(
            text=f"{name}: {len(self.run['rows'])} snapshots, {n} frames "
                 f"listed{miss_txt} — 📏 Calibrate, then Detect "
                 f"(diam {self.settings['diam_mm']:g} mm; scale gate "
                 f"re-arms per run)")
        self.canvas.delete('all')
        self.info.config(text=f"{name}\n{n} frames ready")

    # ---------------- detection ----------------
    @staticmethod
    def _fmt_t(sec):
        sec = int(sec)
        return f"{sec // 60}:{sec % 60:02d}"

    def _tick_clock(self):
        if not self._clock_on or self._t0 is None:
            return
        self.clock_lbl.config(text=f"elapsed {self._fmt_t(time.time() - self._t0)}")
        self.root.after(1000, self._tick_clock)

    def _banner(self, text):
        """Big unmissable state banner drawn over the image area."""
        self.canvas.delete('banner')
        if text:
            w, h = self._view_size()
            self.canvas.create_rectangle(0, h // 2 - 42, w, h // 2 + 42,
                                         fill='#b36b00', outline='',
                                         tags='banner')
            self.canvas.create_text(w // 2, h // 2, text=text, fill='white',
                                    font=('TkDefaultFont', 20, 'bold'),
                                    tags='banner')

    def _no_baseline_refusal(self):
        """REFUSE-DON'T-FABRICATE (audit 2026-08-05, critical): with the
        baseline frame missing/0-byte/undecodable there is no difference
        to image — the old fallback auto-accepted the ROI *background*
        at 2.74x the true area under the operator's perfectly good
        manual anchor. Nothing is detected; every frame stays in the
        review queue for hand-tracing or until the baseline is
        restored."""
        messagebox.showerror(
            "Detect",
            "The BASELINE frame is unreadable (missing, 0-byte or "
            "truncated) — no difference imaging is possible, and every "
            "detected area would be a guess.\n\nRestore the baseline "
            "frame, or hand-trace frames individually (D). Nothing was "
            "detected or auto-accepted.")
        self.status.config(
            text="detection REFUSED: baseline frame unreadable — restore "
                 "it or hand-trace (D); nothing was measured")
        # the hand-trace escape hatch must be able to SAVE: traced +
        # accepted rows flow through the normal (gated, scaled) path,
        # while everything untouched stays untouched
        self.save_btn.config(state='normal')
        if self.frame_rows:
            self.pos = 0
            self._show()

    def detect(self):
        if not self.run:
            messagebox.showinfo("Detect", "Pick a run first")
            return
        if self._detect_busy:
            return
        if not self.frame_rows:
            messagebox.showinfo(
                "Detect", "This run has no frames on disk (the camera was "
                "busy or dry-run frames were skipped).")
            return
        if self.manual_ref is None:
            # SCALE GATE (operator decision 2026-08-05): the camera zoom
            # moves between runs, so the px→mm anchor is clicked by hand
            # on every run before any detection; the automatic disc fit
            # is a cross-check, not the anchor. Detection chains once the
            # clicks land.
            self._calibrate_scale(then_detect=True)
            return
        base = self._base_gray()
        if base is None:
            self._no_baseline_refusal()
            return
        # Every Detect pass starts CLEAN: stale results from a previous
        # pass (old settings, manual picks) used to survive re-detection
        # and get saved as a silent mix of two passes (audit 2026-07-25).
        # Staged traces clear too — their polygons are already safe in
        # edge_labels.json (appended at trace-Done, #172).
        self.cands_all, self.results, self.flags = {}, {}, {}
        self.advisories = {}
        self.traces = {}
        self.auto_idx, self.auto_rej = set(), set()
        self.load_fail = {}
        self.base_ref = None
        self._base_ref_pending = None
        self._detect_gen += 1
        self._detect_busy = True
        self._detect_ui(busy=True)
        # a re-detect must not leave the PREVIOUS pass's Save live while
        # the new results stream in (audit 2026-08-05)
        self.save_btn.config(state='disabled')
        self._t0 = time.time()
        self._clock_on = True
        self._tick_clock()
        self.prog.config(maximum=len(self.frame_rows), value=0)
        self.canvas.delete('all')
        self._banner(f"DETECTING…  0/{len(self.frame_rows)}")
        self.status.config(text="detecting…")
        gen = self._detect_gen
        threading.Thread(
            target=self._detect_worker,
            args=(gen, self.run, list(self.frame_rows),
                  dict(self.settings), base),
            daemon=True).start()
        self.root.after(100, lambda: self._poll_detect(gen))

    def _base_gray(self):
        for i in self.frame_rows:
            if self.run['rows'][i].get('tag') == 'baseline':
                return se.load_gray(se.frame_path(self.run,
                                                  self.run['rows'][i]))
        return None

    def _detect_worker(self, gen, run, frame_rows, settings, base):
        # Per-frame try + sentinel in finally: one bad frame (shape
        # mismatch, decode error) used to kill the thread silently and
        # leave 'DETECTING…' stuck forever (audit 2026-07-25). The
        # worker binds run/frame_rows/settings at start and tags every
        # queue item with its generation — it must never read live app
        # state, which a mid-flight run switch swaps out from under it
        # (audit 2026-08-05).
        try:
            self._detq.put((gen, 'base_ref',
                            se.baseline_disc(base, settings)))
            prev = None
            for i in frame_rows:
                fail = None
                try:
                    img = se.load_gray(se.frame_path(run, run['rows'][i]))
                    if img is None:
                        # a file that will not read is NOT an empty
                        # detection — the distinction must survive to
                        # the review queue (audit 2026-08-05)
                        fail = 'unreadable'
                        cands = []
                    else:
                        cands = se.candidates(base, img, settings,
                                              prev_method=prev)
                except Exception as e:
                    # a readable frame whose DETECTION raised is not a
                    # disk problem — record the true cause, or the
                    # operator chases a missing file that exists
                    # (review 2026-08-05)
                    print(f"detect: frame {i} failed: {e}")
                    fail = f'processing failed: {e}'
                    cands = []
                if cands:
                    prev = cands[0]['method']
                self._detq.put((gen, i, (cands, fail)))
        finally:
            self._detq.put((gen, None, None))

    def _poll_detect(self, gen):
        if gen != self._detect_gen:
            return                  # a run switch invalidated this chain
        done = False
        while True:
            try:
                item = self._detq.get_nowait()
            except _queue.Empty:
                break
            g, key, payload = item
            if g != self._detect_gen:
                continue            # stale worker output: drop, never apply
            if key is None:
                done = True
                break
            if key == 'base_ref':
                self._base_ref_pending = payload
                continue
            cands, fail = payload
            self.cands_all[key] = cands
            if fail:
                self.load_fail[key] = fail
        n, total = len(self.cands_all), len(self.frame_rows)
        self.prog.config(value=n)
        el = time.time() - self._t0
        eta = (el / n * (total - n)) if n else 0
        self.status.config(
            text=f"detecting… {n}/{total}  —  elapsed {self._fmt_t(el)}"
                 + (f", ~{self._fmt_t(eta)} left" if n else ""))
        self._banner(f"DETECTING…  {n}/{total}")
        if done:
            self._finish_detect()
        else:
            self.root.after(100, lambda: self._poll_detect(gen))

    def detect_all_sync(self):
        """Synchronous detection (used by --auto tests and headless runs)."""
        self._t0 = self._t0 or time.time()
        self.cands_all, self.results, self.flags = {}, {}, {}
        self.advisories = {}
        self.traces = {}
        self.auto_idx, self.auto_rej = set(), set()
        self.load_fail = {}
        base = self._base_gray()
        if base is None:
            self._base_ref_pending = None
            self._no_baseline_refusal()
            return
        self._base_ref_pending = se.baseline_disc(base, self.settings)
        prev = None
        for i in self.frame_rows:
            try:
                img = se.load_gray(
                    se.frame_path(self.run, self.run['rows'][i]))
                if img is None:
                    self.load_fail[i] = 'unreadable'
                    self.cands_all[i] = []
                    continue
                self.cands_all[i] = se.candidates(
                    base, img, self.settings, prev_method=prev)
            except Exception as e:
                # same per-frame containment as the threaded worker —
                # one bad frame must not abort the whole sync pass
                # (review 2026-08-05)
                print(f"detect: frame {i} failed: {e}")
                self.load_fail[i] = f'processing failed: {e}'
                self.cands_all[i] = []
                continue
            if self.cands_all[i]:
                prev = self.cands_all[i][0]['method']
        self._finish_detect()

    def _finish_detect(self):
        self.auto_rej = set()
        self._detect_busy = False
        self._detect_ui(busy=False)
        # px→mm reference traced on the BASELINE frame itself (non-diff);
        # manual calibration (📏) overrides it.
        self.base_ref = self._base_ref_pending
        # the pre/post pair is the run's own control: agreement raises
        # confidence, contradiction forces review on both members
        se.reconcile_pairs(self.run['rows'], self.cands_all, self.settings)
        for i in self.frame_rows:
            if i in self.load_fail:
                # an unreadable file or a per-frame processing crash is
                # not a measurement outcome: the row stays in the review
                # queue, clearly labeled with its true cause, and its
                # previously saved values survive a Save untouched
                # (audit 2026-08-05: these auto-rejected as 'no change
                # vs baseline' and Save blanked a hand-traced terminal-
                # breakdown measurement)
                continue
            cands = self.cands_all.get(i, [])
            if cands and not se.needs_review(cands, self.settings):
                self.results[i] = dict(cands[0])
                self.auto_idx.add(i)
            elif not cands:
                # honest no-change/no-edge: nothing to choose, so auto-reject
                # (browse back + lower min_diff in Advanced to disagree)
                self.results[i] = None
                self.auto_rej.add(i)
        self._recount()
        self.save_btn.config(state='normal')
        self.prog.config(value=len(self.frame_rows))
        self._banner(None)
        q = self._queue_list()
        took = self._fmt_t(time.time() - self._t0) if self._t0 else '?'
        if self.manual_ref:
            # the auto disc fit is a CROSS-CHECK of the operator's clicks,
            # not the anchor (scale gate, 2026-08-05). Two tiers: above
            # 3% diameter a modal warning (bad clicks, moved optics,
            # wrong-feature fit); above 1% — the scale-anchor term of
            # the ±1-2% absolute-area budget (SLDEA_MEASUREMENT §1.1) —
            # a status-line ⚠, because a silent green tick used to
            # cover disagreements 7x the budget (audit 2026-08-05).
            sc = f"; scale: manual {self.manual_ref['diam_px']:.0f} px"
            auto_px = (self.base_ref or {}).get('diam_px')
            if auto_px:
                mism = (100 * abs(auto_px - self.manual_ref['diam_px'])
                        / self.manual_ref['diam_px'])
                sc += (f" vs auto disc {auto_px:.0f} px "
                       + (f"⚠ {mism:.1f}% apart" if mism > 3.0 else
                          f"⚠ {mism:.1f}% apart (>1% budget)"
                          if mism > 1.0 else "✓"))
                if mism > 3.0:
                    messagebox.showwarning(
                        "Scale cross-check",
                        f"Your calibration "
                        f"({self.manual_ref['diam_px']:.0f} px) and the "
                        f"automatic baseline-disc fit ({auto_px:.0f} px) "
                        f"disagree by {mism:.1f}% in diameter (>3%).\n\n"
                        f"Re-check the two clicks, the optics, and the "
                        f"{self.settings['diam_mm']:g} mm nominal. The "
                        f"MANUAL anchor is what Save uses.")
            else:
                sc += " (auto disc cross-check unavailable)"
        else:
            # detect_all_sync (tests/headless) can reach here ungated
            sc = (f"; scale ref: baseline disc "
                  f"{self.base_ref['diam_px']:.0f} px"
                  if self.base_ref
                  else "; scale ref: NONE — use 📏 Calibrate")
        unread = (f"{len(self.load_fail)} UNREADABLE/FAILED (kept, not "
                  f"re-measured), " if self.load_fail else "")
        self.status.config(
            text=f"detected {len(self.frame_rows)} frames in {took}: "
                 f"{len(self.auto_idx)} auto-accepted, "
                 f"{len(self.auto_rej)} no-change/no-edge, {unread}"
                 f"{len(q)} need review{sc}")
        self.pos = self.frame_rows.index(q[0]) if q else 0
        self._show()

    def _queue_list(self):
        return [i for i in self.frame_rows if i not in self.results]

    def _recount(self):
        areas = {i: r['area_px'] for i, r in self.results.items() if r}
        self.flags, self.advisories = se.breakdown_flags(
            self.run['rows'], areas, self.settings)

    # ---------------- review ----------------
    def _current(self):
        return self.frame_rows[self.pos] if self.frame_rows else None

    def _show(self):
        i = self._current()
        if i is None:
            return
        row = self.run['rows'][i]
        cands = self.cands_all.get(i, [])
        chosen = self.results.get(i)
        trace_now = self.traces.get(i)
        # a staged D that is NOT the committed polygon must never read as
        # the accepted result — the card used to show the corrected
        # outline as 'accepted' while Save wrote the old one (audit
        # 2026-08-05)
        stale_d = (chosen is not None and trace_now is not None
                   and (chosen.get('method') != 'manual-trace'
                        or chosen.get('trace_points')
                        != trace_now.get('trace_points')))
        # info panel
        state = (('FRAME UNREADABLE — not measured (file missing/0-byte)'
                  if self.load_fail.get(i) == 'unreadable'
                  else 'FRAME PROCESSING FAILED — not measured')
                 if i in self.load_fail and i not in self.results else
                 'auto-accepted' if i in self.auto_idx else
                 'accepted' if chosen else
                 'no change vs baseline (auto)' if i in self.auto_rej
                 and i in self.results else
                 'REJECTED' if i in self.results else 'needs review')
        if stale_d:
            state += ' — ⚠ staged D NOT committed (Enter commits it)'
        txt = (f"frame {self.pos+1}/{len(self.frame_rows)}   step "
               f"{row.get('step')} [{row.get('tag')}]\n"
               f"nominal {row.get('nominal_kV')} kV   "
               f"measured {row.get('measured_kV') or '—'} kV   "
               f"{row.get('measured_uA') or '—'} µA\n"
               f"state: {state}")
        if i in self.flags:
            txt += f"\n⚠ {self.flags[i]}"
        elif i in self.advisories:      # elif keeps the fixed info height
            txt += f"\nⓘ {self.advisories[i]}"
        self.info.config(text=txt)
        # radio text is elided to the FIXED panel (#179): the tail (the
        # wrinkle term first) yields before the panel ever resizes
        meas = self._side_font.measure
        for k in range(3):
            if k < len(cands):
                c = cands[k]
                self.cand_radios[k].config(
                    text=elide(f"{CAND_KEYS[k]}: {c['method']}  "
                               f"{c['area_px']:.0f} px²  conf {c['conf']:.2f}"
                               f"  w{c.get('wrinkle', 1):.1f}",
                               RADIO_TEXT_PX, meas),
                    state='normal')
            else:
                self.cand_radios[k].config(text=f"{CAND_KEYS[k]}: —",
                                           state='disabled')
        # row D: the staged manual trace, or the invitation to make one
        trace = self.traces.get(i)
        if trace is not None:
            mmscale = se.mm_per_px(self.results, self.run['rows'],
                                   self.settings,
                                   baseline_ref=self.manual_ref or
                                   self.base_ref)
            mm = (f"  {trace['area_px'] * mmscale * mmscale:.1f} mm²"
                  if mmscale else "")
            staged = ' STAGED≠accepted' if stale_d else ''
            self.cand_radios[TRACE_SLOT].config(
                text=elide(f"D: manual-trace{staged}  "
                           f"{trace['area_px']:.0f} px²{mm}"
                           f"  ({trace['n_points']} pts)",
                           RADIO_TEXT_PX, meas),
                state='normal')
        else:
            self.cand_radios[TRACE_SLOT].config(
                text="D: ✏ trace by hand…", state='normal')
        # selection: just-staged D wins once, else the accepted result,
        # else a pending D on an unreviewed frame, else A
        sel = 0
        if self._select_trace_once:
            self._select_trace_once = False
            sel = TRACE_SLOT
        elif chosen:
            if chosen['method'] == 'manual-trace':
                sel = TRACE_SLOT
            else:
                for k, c in enumerate(cands):
                    if c['method'] == chosen['method']:
                        sel = k
                        break
        elif i not in self.results and trace is not None:
            sel = TRACE_SLOT
        self.cand_var.set(sel)
        q = self._queue_list()
        self.queue_lbl.config(
            text=f"review queue: {len(q)} frame(s) left"
                 + (f"\nbreakdown-flagged: {len(self.flags)}" if self.flags
                    else ""))
        self._draw(i, cands, chosen)

    def _view_size(self):
        """The card's view box: the live canvas size once mapped, else
        the last <Configure> size -- winfo reports 1x1 before layout
        (withdrawn roots in tests land there)."""
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            cw, ch = self._view_wh
        return cw, ch

    def _canvas_resized(self, ev):
        """<Configure> on the canvas (#178): remember the size and
        re-render the card to fill it. Debounced -- the event streams
        continuously during a drag-resize."""
        wh = (ev.width, ev.height)
        if wh == self._view_wh:
            return
        self._view_wh = wh
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(120, self._redraw_card)

    def _redraw_card(self):
        self._resize_job = None
        i = self._current()
        if self.run is None or i is None or i not in self.cands_all:
            return
        self._draw(i, self.cands_all.get(i, []), self.results.get(i))

    def _render_card(self, i, cands, chosen, view=None):
        """The review card as a PIL image (no Tk): frame + candidate
        outlines + letter tags, contain-fit to `view` (default: the live
        canvas size, #178). Line widths and TAG_PX stay in VIEW pixels
        so legibility is constant at any card size. Split from _draw so
        the rendering is checkable headlessly -- the card is what the
        operator judges."""
        from PIL import Image, ImageDraw
        import numpy as np
        path = se.frame_path(self.run, self.run['rows'][i])
        img = Image.open(path).convert('RGB')
        vw, vh = view or self._view_size()
        scale, w, h, _x, _y = card_geometry(img.width, img.height, vw, vh)
        img = img.resize((w, h))
        dr = ImageDraw.Draw(img)
        entries = list(enumerate(cands))
        trace = self.traces.get(i)
        if trace is not None:              # the staged D outline (#172)
            entries.append((TRACE_SLOT, trace))
        hot = hot_slot(entries, chosen, self.cand_var.get())
        # A committed manual trace with a NEWER D staged: the staged
        # polygon used to be the only one drawn — at the heavy selected
        # weight — while Save wrote the committed one (audit 2026-08-05).
        # Draw the committed outline too (heavy) and thin the staged one.
        stale_d = (chosen is not None and trace is not None
                   and (chosen.get('method') != 'manual-trace'
                        or chosen.get('trace_points')
                        != trace.get('trace_points')))
        committed_trace = (chosen if stale_d
                           and chosen.get('method') == 'manual-trace'
                           else None)
        font = _tag_font()
        for slot, c in entries:
            pts = [(float(x) * scale, float(y) * scale)
                   for x, y in np.asarray(c['contour'])]
            if len(pts) <= 2:
                continue
            # thicker lines, selection visibly heavier (#171/#173)
            wdt = 3 if slot == hot else 2
            if stale_d and slot == TRACE_SLOT and c is trace:
                wdt = 1                    # staged-but-uncommitted: thin
            dr.line(pts + [pts[0]], fill=CAND_COLORS[slot], width=wdt)
            # letter tag: candidate↔outline mapping must not rely on
            # color alone (audit 2026-07-25); large + solid halo (#173)
            tx, ty = max(pts, key=lambda p: p[0])
            tx = min(tx + 6, img.width - TAG_PX - 2)
            ty = min(max(ty - TAG_PX / 2, 0), img.height - TAG_PX - 4)
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if dx or dy:
                        dr.text((tx + dx, ty + dy), CAND_KEYS[slot],
                                fill='black', font=font)
            dr.text((tx, ty), CAND_KEYS[slot], fill=CAND_COLORS[slot],
                    font=font)
        if committed_trace is not None:
            pts = [(float(x) * scale, float(y) * scale)
                   for x, y in np.asarray(committed_trace['contour'])]
            if len(pts) > 2:
                dr.line(pts + [pts[0]], fill=CAND_COLORS[TRACE_SLOT],
                        width=3)
        return img

    def _draw(self, i, cands, chosen):
        from PIL import ImageTk
        vw, vh = self._view_size()
        try:
            img = self._render_card(i, cands, chosen, view=(vw, vh))
        except OSError:
            # frame missing/undecodable: SAY so on the card — a silently
            # blank canvas next to a physical-sounding state line is how
            # a missing file laundered into a measurement verdict (audit
            # 2026-08-05). Draw bugs stay loud.
            self.canvas.delete('all')
            row = self.run['rows'][i] if self.run else {}
            name = (row.get('frame_file') or '(no file)').strip()
            reason = self.load_fail.get(i)
            if reason and reason != 'unreadable':
                head, detail = 'FRAME PROCESSING FAILED', reason[:90]
            else:
                head = 'FRAME UNREADABLE'
                detail = '(missing / 0-byte / truncated on disk)'
            self.canvas.create_rectangle(0, vh // 2 - 46, vw, vh // 2 + 46,
                                         fill='#7a1f1f', outline='')
            self.canvas.create_text(
                vw // 2, vh // 2, fill='white', justify='center',
                font=('TkDefaultFont', 14, 'bold'),
                text=f"{head}\n{name}\n{detail}")
            return
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete('all')
        # centered on the canvas; the canvas itself is sized by the
        # packer, never by the card (#178)
        self.canvas.create_image(vw // 2, vh // 2, anchor='center',
                                 image=self._photo)

    def _pick_k(self, k):
        i = self._current()
        if i is None or k >= len(self.cands_all.get(i, [])):
            return
        self.cand_var.set(k)
        self._choose_current()

    def _choose_current(self):
        # review inputs are inert while a worker streams: the panel
        # still shows the PREVIOUS pass, so Enter/1/2/3 would accept a
        # candidate the operator has never seen — and _finish_detect
        # would then overwrite the pick as 'auto-accepted' (review
        # 2026-08-05)
        if self._detect_busy:
            return
        i = self._current()
        if i is None:
            return
        k = self.cand_var.get()
        if k == TRACE_SLOT:
            # Accept commits the STAGED trace (#172) -- staging alone
            # (closing the tracer) never touches results
            trace = self.traces.get(i)
            if trace is None:
                return
            chosen = dict(trace)
        else:
            cands = self.cands_all.get(i, [])
            if k >= len(cands):
                return
            chosen = dict(cands[k])
        chosen['chosen_by'] = 'user'
        self.results[i] = chosen
        self.auto_idx.discard(i)
        self._recount()
        self._show()

    def _accept_next(self):
        # ALWAYS (re)accept the selected candidate -- a frame that was
        # rejected earlier must flip back to accepted (bench bug 2026-07-23:
        # a "was it already decided?" guard swallowed the re-accept).
        self._choose_current()
        self._advance()

    def _reject(self):
        if self._detect_busy:          # same guard as _choose_current
            return
        i = self._current()
        if i is None:
            return
        self.results[i] = None
        self.auto_idx.discard(i)
        self._recount()
        self._advance()

    # ---------------- manual trace (#162, candidate D per #172) --------
    def _machine_pairing(self, i):
        """The machine candidate this frame's trace will be PAIRED with,
        and why there is none when there is none (#162, 2026-08-06).

        Every trace is a ground-truth label, and a label with
        machine:null yields None from sldea_trace.label_iou forever --
        worthless for the conf-vs-IoU curve #162 exists to build. It used
        to happen silently: a run opened WITHOUT --auto has never
        detected anything, cands_all is empty, and the label went out
        unpaired with no complaint (four of them in the 2026-07/08 batch
        control round; the operator's work had to be redone).

        So the pairing is CREATED here rather than reported: detecting
        ONE frame is cheap (candidates() works at DETECT_MAX_W=640) and
        writes nothing to disk, and it yields exactly the outlines a full
        pass would for this frame. What a single frame cannot reproduce
        is the ramp-order hysteresis bonus and the same-kV pair
        reconciliation, both worth up to 0.05 of conf -- so the
        candidates are tagged SCOPE_FRAME and the label records which
        pass its conf came from, instead of letting the calibration curve
        mix two conventions silently.

        Detection state only GROWS here: results, auto_idx/auto_rej and
        the scale gate (base_ref/manual_ref) are never touched, so an
        on-demand detect can neither accept nor reject anything.
        """
        if i not in self.cands_all and not self._detect_busy:
            # (the busy case cannot be reached from _trace, which is
            # inert while a worker streams; detecting here anyway would
            # put a second thread in sldea_edge's baseline caches)
            base = self._base_gray()
            if base is None:
                return None, strc.UNPAIRED_NO_BASELINE
            try:
                img = se.load_gray(se.frame_path(self.run,
                                                 self.run['rows'][i]))
            except Exception as e:
                print(f"trace: frame {i} did not load: {e}")
                img = None
            if img is None:
                return None, strc.UNPAIRED_FRAME_UNREADABLE
            self.status.config(text="detecting this frame on demand "
                                    "(so the trace can be paired)…")
            self.root.update_idletasks()
            try:
                cands = se.candidates(base, img, self.settings)
            except Exception as e:
                # same containment as the detect worker: a failed frame
                # must not block the recovery trace
                print(f"trace: on-demand detect for frame {i} failed: {e}")
                return None, strc.UNPAIRED_DETECT_FAILED
            for c in cands:
                c['detect_scope'] = strc.SCOPE_FRAME
            self.cands_all[i] = cands
            self.status.config(
                text=f"detected {len(cands)} candidate(s) for THIS frame "
                     f"on demand — ▶ Detect Edges covers the whole run "
                     f"(pair/ramp confidence needs the full pass)")
        cands = self.cands_all.get(i, [])
        if not cands and i in self.load_fail:
            # a file- or code-level failure is not 'the detector found
            # nothing' — the distinction survives into the label for the
            # same reason it survives into the review queue
            return None, (strc.UNPAIRED_FRAME_UNREADABLE
                          if self.load_fail[i] == 'unreadable'
                          else strc.UNPAIRED_DETECT_FAILED)
        return strc.machine_pairing(cands, detected=i in self.cands_all)

    def _trace(self):
        """Open the manual tracer: the recovery path when every candidate
        is rejected, and the labeling instrument for the conf-vs-IoU
        calibration. Allowed even when a candidate exists -- correcting a
        near-miss is a valuable label, not a rejection. The closed trace
        is STAGED as candidate D (row D + drawn on the card); Accept
        commits it like any other candidate (#172). Re-opening D edits
        the pending polygon rather than starting over."""
        if self._detect_busy:          # same guard as _choose_current
            return
        i = self._current()
        if self.run is None or i is None:
            messagebox.showinfo("Trace", "Pick a run first")
            return
        path = se.frame_path(self.run, self.run['rows'][i])
        if not path or not os.path.exists(path):
            messagebox.showinfo("Trace", "This row has no frame on disk.")
            self._show()               # the D radio may have grabbed sel
            return
        # the pairing is settled BEFORE the operator spends a minute
        # tracing: either it exists (detected on demand if need be), or
        # they are told plainly that this trace cannot be ground truth,
        # with a chance to repair the cause first (#162, 2026-08-06)
        _mach, why = self._machine_pairing(i)
        if why and not messagebox.askokcancel(
                "Trace with NO machine candidate",
                f"This frame has no machine candidate, so a trace of it "
                f"CANNOT serve as ground truth: the machine-vs-operator "
                f"IoU and the definitional-offset gate are not computable "
                f"from it, ever (#162).\n\n"
                f"{strc.unpaired_message(why)}\n\n"
                f"Tracing anyway still RECOVERS the measurement — the "
                f"polygon, its area and the label are saved as usual, and "
                f"the label is marked '{why}' so the calibration pass "
                f"reports it instead of silently ignoring it.\n\n"
                f"Trace anyway?"):
            self._show()               # the D radio may have grabbed sel
            return
        scale = se.mm_per_px(self.results, self.run['rows'], self.settings,
                             baseline_ref=self.manual_ref or self.base_ref)
        trace = self.traces.get(i) or {}
        TraceWindow(self, i, path, mm_per_px=scale,
                    seed=trace.get('trace_points'),
                    seed_snapped=bool(trace.get('snapped')),
                    unpaired_ack=why)

    def _trace_staged(self, i, points, meta):
        """TraceWindow Done -> the polygon is staged as candidate D and
        the ground-truth label is appended to edge_labels.json. Staging
        does NOT touch results -- Accept commits (#172). The label
        appends HERE, at Done, so a completed trace is never lost even
        if it is not accepted; a re-trace appends another record (repeat
        labels are how operator repeatability was measured). Tracing
        never touches data.csv/setup.txt -- the committed result flows
        through the normal Save path."""
        meta = dict(meta)
        # what the operator was told at tracer-open time (#162): a
        # pairing gap they have NOT seen gets stated here instead of
        # only landing in the sidecar
        ack = meta.pop('unpaired_ack', None)
        poly = np.asarray(points, np.float64)
        area = strc.polygon_area(poly)
        cx, cy = strc.polygon_centroid(poly)
        wrinkle = None
        gray = se.load_gray(se.frame_path(self.run, self.run['rows'][i]))
        try:
            base = self._base_gray()
            # se.wrinkle_index, NOT the raw-frame ratio: |Laplacian| is
            # linear in gain, and the un-normalized frame gave traced
            # rows an index 20-30% off at the P3 campaign's photometric
            # gain — the saved column silently mixed two normalizations
            # and P3_5 lost its wrinkle-mode onset to it (audit
            # 2026-08-05)
            wrinkle = se.wrinkle_index(base, gray, poly, self.settings)
        except Exception:
            wrinkle = None
        self.traces[i] = {
            'method': 'manual-trace', 'conf': 1.0, 'chosen_by': 'user',
            'area_px': float(area),
            'diam_px': strc.equivalent_diam(area),
            'cx': float(cx), 'cy': float(cy),
            'contour': poly.astype(np.int32), 'solidity': 1.0,
            'spread_pct': 0.0, 'ci85_pct': None, 'wrinkle': wrinkle,
            'n_points': len(poly),
            # full-precision points so re-opening D edits, not re-clicks
            'trace_points': [(float(x), float(y)) for x, y in poly],
            'snapped': bool(meta.get('snapped'))}
        # every trace is a label, stored with the machine's best candidate
        # at trace time so IoU is computable offline (#162). The pairing
        # is resolved through _machine_pairing, which DETECTS this frame
        # if nothing ever did — label_record refuses an unexplained
        # machine:null, so no path can write a dead label by omission.
        mach, why = self._machine_pairing(i)
        shape = gray.shape if gray is not None else (0, 0)
        self._select_trace_once = True
        try:
            # label_record inside the try on purpose: its refusal is a
            # ValueError, and an unhandled one here would print to a
            # console nobody is watching and lose the label silently --
            # the exact shape of failure this gate exists to end
            rec = strc.label_record(i, self.run['rows'][i], poly, shape,
                                    machine=mach, unpaired=why, **meta)
            strc.append_label(self.rundir, rec)
            n = len(strc.load_labels(self.rundir))
            self.status.config(
                text=f"trace staged as candidate D ({area:.0f} px², "
                     f"{len(poly)} points) — Accept (Enter) commits; "
                     f"label {n} in {strc.LABELS_NAME}"
                     + (f"  ⚠ UNPAIRED ({why}): recovery only, NOT usable "
                        f"as ground truth" if why else ""))
            if why and why != ack:
                # a label reached the sidecar without the operator having
                # seen the tracer-open warning (a caller that bypassed
                # _trace, or candidates that went away mid-trace): say it
                # now, rather than leaving it findable only offline
                messagebox.showwarning(
                    "Trace label is NOT ground truth",
                    f"This trace was saved as a recovery measurement, "
                    f"but it has no machine candidate to pair with, so no "
                    f"IoU can ever be computed from it (#162).\n\n"
                    f"{strc.unpaired_message(why)}")
        except (OSError, ValueError) as e:
            messagebox.showerror(
                "Trace label", f"The trace is staged as candidate D, but "
                f"appending the label sidecar failed:\n\n{e}")
        self._show()

    def _advance(self):
        """After accept/reject: jump to the next unreviewed frame (first one
        after the current position, wrapping), else just the next frame."""
        q = self._queue_list()
        if q:
            i_cur = self._current()
            later = [i for i in q if i > (i_cur if i_cur is not None else -1)]
            self.pos = self.frame_rows.index(later[0] if later else q[0])
            self._show()
        elif self.pos < len(self.frame_rows) - 1:
            self._step(+1)
        else:
            self._show()
            self.status.config(text="review complete — Save to data.csv "
                                    "when ready")

    def _step(self, d):
        if not self.frame_rows:
            return
        self.pos = max(0, min(len(self.frame_rows) - 1, self.pos + d))
        self._show()

    def _next_unreviewed(self):
        q = self._queue_list()
        if q:
            self.pos = self.frame_rows.index(q[0])
            self._show()
        else:
            self._show()
            self.status.config(text="review complete — Save to data.csv when "
                                    "ready")

    # ---------------- save ----------------
    def save(self):
        if not self.run:
            return
        if self.manual_ref is None:
            # the scale gate holds at Save too — no entry point may write
            # mm² off an unverified anchor (operator decision 2026-08-05)
            messagebox.showinfo(
                "Save", "Scale gate: 📏 Calibrate this run's resting disc "
                        "first — the manual px→mm anchor is required "
                        "before results are written.")
            return
        q = self._queue_list()
        accepted = sum(1 for r in self.results.values() if r)
        rejected = sum(1 for r in self.results.values() if r is None)
        n_unread = sum(1 for i in q if i in self.load_fail)
        # unreviewed rows KEEP their previous pass's px measurement,
        # re-scaled to this session's anchor (one scale per save, audit
        # 2026-08-05) — the dialog used to claim they were 'left blank'
        n_kept = sum(
            1 for i in q
            if (self.run['rows'][i].get('active_area_px') or '').strip())
        unrev = (f"unreviewed: {len(q)}"
                 + (f" ({n_kept} keep the previous pass's px, re-scaled "
                    f"to THIS anchor)" if n_kept else " (left blank)")
                 + (f"\n  incl. {n_unread} UNREADABLE frame(s) — kept, "
                    f"not re-measured" if n_unread else ""))
        n_bd = 0
        if self.flags:
            start = min(self.flags)
            n_bd = sum(1 for i in self.frame_rows if i >= start)
        # retracted brands rename BACK — the dialog must say so, not
        # only announce the branding direction (review 2026-08-05)
        first = min(self.flags) if self.flags else None
        n_unbrand = sum(
            1 for i, row in enumerate(self.run['rows'])
            if '_BREAKDOWN' in (row.get('frame_file') or '')
            and (first is None or i < first))
        msg = (f"Write results into this run's data.csv?\n\n"
               f"accepted: {accepted}  (auto {len(self.auto_idx)})\n"
               f"rejected: {rejected}\n"
               f"{unrev}\n"
               f"breakdown-flagged: {len(self.flags)}"
               + (f"  (+{len(self.advisories)} advisory note(s), no renames)"
                  if self.advisories else "") + "\n"
               + (f"\n⚠ {n_bd} frame file(s) from the first breakdown onward "
                  f"will be RENAMED with a _BREAKDOWN suffix (kept, never "
                  f"deleted — usable later as ML training data).\n"
                  if n_bd else "\n")
               + (f"⚠ {n_unbrand} file(s) carry a breakdown brand the "
                  f"current flags RETRACT — renamed back (un-branded), "
                  f"stale notes cleaned.\n" if n_unbrand else "")
               + "A backup is kept as data.csv.bak; an area-vs-voltage plot "
                 "and outline overlays are saved beside it.")
        if not messagebox.askyesno("Save results", msg):
            return
        ref = self.manual_ref or self.base_ref
        scale = se.mm_per_px(self.results, self.run['rows'], self.settings,
                             baseline_ref=ref)
        src = se.scale_source(self.results, self.run['rows'],
                              baseline_ref=ref)
        onset, annos = se.wrinkle_onset(self.run['rows'], self.results,
                                        self.settings)
        # physics the per-frame detector cannot see: pre/post pairs must
        # agree, and the area must not dip while the voltage rises
        for i, note in se.ramp_consistency(self.run['rows'], self.results,
                                           self.settings).items():
            annos[i] = (annos[i] + '; ' + note) if i in annos else note
        # advisory breakdown notes ride the anno channel: written to the
        # CSV, never renaming frames or seeding post-breakdown branding
        for i, note in self.advisories.items():
            annos[i] = (annos[i] + '; ' + note) if i in annos else note
        # a not-measured frame's row records WHY — a file- or code-level
        # fact, never a physical verdict (audit 2026-08-05). ASCII-safe
        # in the CSV.
        for i in q:
            if i in self.load_fail:
                note = ('frame unreadable - kept, not re-measured'
                        if self.load_fail[i] == 'unreadable' else
                        'frame processing failed - kept, not re-measured')
                annos[i] = (annos[i] + '; ' + note) if i in annos else note
        if 'wrinkle_idx' not in self.run['columns']:
            # older runs predate the column; slot it in before notes
            cols = self.run['columns']
            cols.insert(cols.index('notes') if 'notes' in cols else len(cols),
                        'wrinkle_idx')
        for row in self.run['rows']:
            row.setdefault('wrinkle_idx', '')
        # The destructive phase must NEVER fail silently, and its ORDER
        # is load-bearing (audit 2026-08-05): data.csv commits FIRST
        # (backup + atomic tmp+replace inside write_back), the frame
        # renames run after. A failure before the commit leaves the run
        # byte-identical on disk with zero files renamed; a failure
        # during the renames leaves a saved CSV whose links the next
        # Save's symmetric heal repairs. The old order renamed first, so
        # a full disk left renamed frames, a stale CSV and a dialog
        # promising a .bak that was never made.
        csv_path = self.run.get('csv_path') or ''
        try:
            se.apply_results(self.run['rows'], self.results, scale,
                             self.flags, annos)
            plan = se.plan_breakdown_marks(self.run, self.flags)
            se.write_back(self.rundir, self.run)
        except Exception as e:
            has_bak = csv_path and os.path.exists(csv_path + '.bak')
            messagebox.showerror(
                "Save FAILED",
                f"Writing results failed:\n\n{e}\n\nYour review is still "
                f"in memory — fix the problem (share up? disk full?) and "
                f"Save again. No frame files were renamed."
                + (f"\nA pre-save backup is at data.csv.bak."
                   if has_bak else ""))
            return
        renamed, rn_errors = se.apply_rename_plan(plan)
        if rn_errors:
            messagebox.showwarning(
                "Save: renames incomplete",
                f"data.csv is saved, but {len(rn_errors)} frame "
                f"rename(s) failed:\n\n" + '\n'.join(rn_errors[:4])
                + ('\n…' if len(rn_errors) > 4 else '')
                + "\n\nSave again once the files are reachable — the "
                  "branding self-heals in either direction.")
        # persist the anchor that produced every mm² in this save — the
        # run's absolute scale used to be a pair of clicks recorded
        # nowhere (audit 2026-08-05); the 📏 dialog offers it for reuse
        try:
            se.save_scale_anchor(self.rundir, {
                'method': self.manual_ref.get('method',
                                              'manual-calibration'),
                'diam_px': self.manual_ref['diam_px'],
                'diam_mm': self.settings['diam_mm'],
                'mm_per_px': scale,
                'anchor_frame': self.manual_ref.get('frame', ''),
                'anchor_is_baseline': self.manual_ref.get('is_baseline'),
                'auto_diam_px': (self.base_ref or {}).get('diam_px'),
            })
        except OSError as e:
            self.status.config(
                text=f"saved, but recording the scale anchor in "
                     f"setup.txt failed: {e}")
        self._clock_on = False
        took = self._fmt_t(time.time() - self._t0) if self._t0 else '?'
        self.clock_lbl.config(text=f"done in {took}")
        try:
            self._save_plot(scale)
            self._save_overlays()
        except Exception as e:
            self.status.config(text=f"saved CSV; plot/overlays failed: {e}")
            return
        scale_txt = (f"scale {scale:.5f} mm/px [{src}]" if scale
                     else "no mm scale — use 📏 Calibrate")
        bd_txt = f", {renamed} frame(s) renamed" if renamed else ""
        self.status.config(
            text=f"saved in {took} — data.csv updated ({scale_txt}){bd_txt}")

    def _save_plot(self, scale):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        xs, ys, tags = [], [], []
        for i, r in self.results.items():
            if not r:
                continue
            row = self.run['rows'][i]
            try:
                kv = float(row.get('nominal_kV') or '')
            except ValueError:
                continue
            area = r['area_px'] * (scale * scale) if scale else r['area_px']
            xs.append(kv)
            ys.append(area)
            tags.append(row.get('tag'))
        if not xs:
            return
        fig, ax = plt.subplots(figsize=(8, 5))
        # prefix match keeps old runs (tags 'post'/'pre') plottable alongside
        # new ones ('post-ramp'/'pre-ramp')
        for pref, mk, label in (('post', 'o', 'post-ramp'),
                                ('pre', 's', 'pre-ramp'),
                                ('baseline', '^', 'baseline')):
            px = [x for x, t in zip(xs, tags) if (t or '').startswith(pref)]
            py = [y for y, t in zip(ys, tags) if (t or '').startswith(pref)]
            if px:
                ax.plot(px, py, mk, label=label, alpha=0.8)
        ax.set_xlabel('nominal voltage (kV)')
        ax.set_ylabel('active area (mm²)' if scale else 'active area (px²)')
        ax.set_title(os.path.basename(self.rundir) + ' — active area vs voltage')
        ax.grid(alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(self.rundir, 'area_vs_voltage.png'), dpi=110)
        plt.close(fig)

    def _save_overlays(self):
        import cv2
        import numpy as np
        outdir = os.path.join(self.rundir, 'overlays')
        os.makedirs(outdir, exist_ok=True)
        for i, r in self.results.items():
            if not r:
                continue
            row = self.run['rows'][i]
            path = se.frame_path(self.run, row)
            img = cv2.imread(path)
            if img is None:
                continue
            cv2.polylines(img, [np.asarray(r['contour'], np.int32)], True,
                          (80, 200, 0), 2)
            cv2.imwrite(os.path.join(outdir, os.path.basename(path)), img)

    def _diam_recorded(self):
        """True when this run's setup.txt carries the capture-side
        'DEA nominal diameter' line (written from the SLDEA tab's
        'DEA diam (mm)' field) — if not, diam_mm is only the settings
        default and the gate dialog says so.

        utf-8 + errors='replace', like load_settings: the bare locale-
        codec open raised UnicodeDecodeError (a ValueError, NOT an
        OSError) on any hand-annotated non-ASCII byte, mid-dialog-build
        — which published a half-built singleton and silently bricked
        Detect for the rest of the session (audit 2026-08-05)."""
        try:
            with open(os.path.join(self.rundir, 'setup.txt'),
                      encoding='utf-8', errors='replace') as f:
                return 'DEA nominal diameter:' in f.read()
        except (OSError, TypeError, UnicodeError):
            return False

    def _anchor_frame(self):
        """-> (PIL image, is_baseline, tried, frame_name) — the first
        READABLE frame to calibrate on: baseline-tagged rows first, then
        the rest of the ramp. A baseline PNG can be listed in the CSV
        yet be 0-byte or truncated on disk (interrupted capture, e.g.
        the 2026-08-04 disk-full incident) — the gate must fall back,
        not crash, or the whole run becomes permanently unprocessable
        (review 2026-08-05). `tried` collects the unreadable names for
        the error dialog; `frame_name` feeds the anchor's provenance
        record."""
        from PIL import Image
        ordered = ([i for i in self.frame_rows
                    if self.run['rows'][i].get('tag') == 'baseline']
                   + [i for i in self.frame_rows
                      if self.run['rows'][i].get('tag') != 'baseline'])
        tried = []
        for i in ordered:
            row = self.run['rows'][i]
            path = se.frame_path(self.run, row)
            if not path or not os.path.exists(path):
                tried.append(os.path.basename(path or '(no file)'))
                continue
            try:
                img = Image.open(path).convert('RGB')
            except Exception as e:          # 0-byte, truncated, not-a-PNG
                tried.append(f"{os.path.basename(path)} ({e})")
                continue
            return (img, row.get('tag') == 'baseline', tried,
                    os.path.basename(path))
        return None, False, tried, ''

    def _gate_status(self):
        self.status.config(text="Detect is gated on the scale "
                                "calibration — 📏 Calibrate to proceed")

    def _calibrate_scale(self, then_detect=False):
        """Manual px→mm calibration: click the two opposite edges of the
        RESTING disc on the baseline frame; the known nominal diameter
        (diam_mm) between them sets the scale. This is the SCALE GATE
        (operator decision 2026-08-05): Detect and Save both require it
        per run, and it overrides EVERY automatic reference at Save.
        With then_detect, detection chains automatically once the two
        clicks land (Detect's gate path and --auto). SINGLETON like
        Advanced… (#176): the grab is pointer-only, so a pierced dialog
        must front the live one, never stack a second wait chain.

        Fail-CLOSED construction (audit 2026-08-05): the singleton
        handle publishes only once the dialog is fully built, and a
        try/finally destroys a half-built window and clears the handle
        no matter what raises — an exception mid-build used to leave a
        dead Toplevel in self._cal_win, and every later Detect lifted
        the corpse and returned, silently and forever.

        The frame is ZOOMABLE (wheel about the cursor, right-drag pans,
        F fits): the fixed 0.41x preview put one display pixel at ~2.5
        full-res px while the soft ink edge spans 8-15, so click scatter
        alone could move every absolute area by several % (audit
        2026-08-05). Clicks land in full-res image coordinates at any
        zoom. A previously RECORDED anchor (setup.txt) can be reused
        with P — reproducible re-saves instead of fresh scatter."""
        if not self.run:
            messagebox.showinfo("Calibrate", "Pick a run first")
            return
        if self._cal_win is not None and self._cal_win.winfo_exists():
            self._cal_win.lift()
            self._cal_win.focus_set()
            return
        from PIL import Image, ImageTk
        img, anchor_is_baseline, tried, frame_name = self._anchor_frame()
        if img is None:
            messagebox.showerror(
                "Calibrate",
                "No readable frame to calibrate on — Detect and Save "
                "stay gated until one exists (restore or re-export a "
                "frame).\nTried: " + '; '.join(tried[:4])
                + ('…' if len(tried) > 4 else ''))
            if then_detect:
                self._gate_status()
            return
        recorded = se.load_scale_anchor(self.rundir)
        win = tk.Toplevel(self.root)
        try:
            win.title("Calibrate scale — click the disc's two opposite "
                      "edges")
            win.transient(self.root)
            gate = (f"SCALE GATE — this run's px→mm anchor.\n"
                    f"Click LEFT edge then RIGHT edge of the resting disc "
                    f"(nominal {self.settings['diam_mm']:g} mm across). "
                    f"Click at the ink edge's HALF-HEIGHT (mid-gray), "
                    f"matching the machine convention — not the outer "
                    f"toe.\n"
                    f"Wheel zooms about the cursor, right-drag pans, F "
                    f"fits. Esc cancels.")
            if not anchor_is_baseline:
                gate += ("\n⚠ The baseline frame is missing/unreadable — "
                         "this is a LATER frame. Only calibrate here if "
                         "the disc is visibly AT REST; otherwise Esc and "
                         "restore the baseline frame.")
            if not self._diam_recorded():
                gate += (f"\n⚠ The diameter was NOT recorded at capture — "
                         f"{self.settings['diam_mm']:g} mm is the "
                         f"settings default. If this device used a "
                         f"different mask, fix diam_mm in Advanced… "
                         f"BEFORE calibrating.")
            if recorded:
                gate += (f"\n📏 On record from the last Save: "
                         f"{recorded['diam_px']:.1f} px "
                         f"({recorded.get('mm_per_px', 0):.5f} mm/px, "
                         f"saved {recorded.get('saved', '?')}) — "
                         f"press P to REUSE it.")
            tk.Label(win, text=gate, justify='left').pack(pady=(6, 2))
            ch = max(200, min(VIEW_H, int(VIEW_W * img.height / img.width)))
            cv = tk.Canvas(win, width=VIEW_W, height=ch, bg='#111',
                           cursor='crosshair')
            cv.pack(padx=8, pady=8)
            vt = strc.ViewTransform()
            vt.fit(img.width, img.height, VIEW_W, ch)
            pts = []            # clicks in FULL-RES image coordinates
            state = {'photo': None, 'pan': None}

            def repaint():
                ix0, iy0 = vt.to_image(0, 0)
                ix1, iy1 = vt.to_image(VIEW_W, ch)
                cx0, cy0 = max(0, int(ix0)), max(0, int(iy0))
                cx1 = min(img.width, int(ix1) + 2)
                cy1 = min(img.height, int(iy1) + 2)
                cv.delete('all')
                if cx1 > cx0 and cy1 > cy0:
                    crop = img.crop((cx0, cy0, cx1, cy1))
                    dw = max(1, int(round((cx1 - cx0) * vt.zoom)))
                    dh = max(1, int(round((cy1 - cy0) * vt.zoom)))
                    res = (Image.NEAREST if vt.zoom >= 2.0
                           else Image.BILINEAR)
                    state['photo'] = ImageTk.PhotoImage(
                        crop.resize((dw, dh), res))
                    vx, vy = vt.to_view(cx0, cy0)
                    cv.create_image(int(vx), int(vy), anchor='nw',
                                    image=state['photo'])
                for px, py in pts:
                    vx, vy = vt.to_view(px, py)
                    cv.create_oval(vx - 4, vy - 4, vx + 4, vy + 4,
                                   outline='#00e676', width=2)
                if len(pts) == 2:
                    a = vt.to_view(*pts[0])
                    b = vt.to_view(*pts[1])
                    cv.create_line(*a, *b, fill='#00e676', width=2)

            def accept(dpx_full, source_frame, src_is_baseline=None):
                self.manual_ref = {'method': 'manual-calibration',
                                   'diam_px': float(dpx_full),
                                   'frame': source_frame,
                                   'is_baseline': (anchor_is_baseline
                                                   if src_is_baseline
                                                   is None
                                                   else src_is_baseline)}
                self.status.config(
                    text=f"scale calibrated: "
                         f"{self.settings['diam_mm']:g} mm = "
                         f"{dpx_full:.0f} px "
                         f"({self.settings['diam_mm'] / dpx_full:.5f} "
                         f"mm/px) — overrides every automatic reference "
                         f"at Save")
                win.destroy()

            def click(ev):
                pts.append(vt.to_image(ev.x, ev.y))
                repaint()
                if len(pts) == 2:
                    dpx_full = ((pts[0][0] - pts[1][0]) ** 2 +
                                (pts[0][1] - pts[1][1]) ** 2) ** 0.5
                    if dpx_full < 10:
                        messagebox.showwarning(
                            "Calibrate", "Points are too close — retry.")
                        win.destroy()
                        return
                    accept(dpx_full, frame_name)

            def reuse(_ev=None):
                if recorded:
                    # a reused anchor keeps ITS OWN provenance — the
                    # frame it was clicked on and whether that was the
                    # baseline, not this session's (review 2026-08-05)
                    accept(recorded['diam_px'],
                           recorded.get('anchor_frame', '') or frame_name,
                           src_is_baseline=recorded.get(
                               'anchor_is_baseline'))

            def wheel(vx, vy, steps):
                vt.zoom_at(vx, vy, 1.15 ** steps)
                repaint()

            def pan_start(ev):
                state['pan'] = (ev.x, ev.y)

            def pan_move(ev):
                if state['pan'] is None:
                    return
                dx, dy = ev.x - state['pan'][0], ev.y - state['pan'][1]
                state['pan'] = (ev.x, ev.y)
                vt.pan_view(dx, dy)
                repaint()

            cv.bind('<Button-1>', click)
            cv.bind('<MouseWheel>',
                    lambda e: wheel(e.x, e.y, e.delta / 120.0))
            cv.bind('<Button-4>', lambda e: wheel(e.x, e.y, 1))
            cv.bind('<Button-5>', lambda e: wheel(e.x, e.y, -1))
            cv.bind('<Button-3>', pan_start)
            cv.bind('<B3-Motion>', pan_move)
            win.bind('<Key-f>', lambda e: (vt.fit(img.width, img.height,
                                                  VIEW_W, ch), repaint()))
            win.bind('<Key-F>', lambda e: (vt.fit(img.width, img.height,
                                                  VIEW_W, ch), repaint()))
            if recorded:
                win.bind('<Key-p>', reuse)
                win.bind('<Key-P>', reuse)
            win.bind('<Escape>', lambda e: win.destroy())
            repaint()
            cv.focus_set()
            self._cal_win = win
            win.grab_set()
            self.root.wait_window(win)
        finally:
            self._cal_win = None
            try:
                if win.winfo_exists():
                    win.destroy()
            except tk.TclError:
                pass
        if then_detect:
            if self.manual_ref is not None:
                self.detect()
            else:
                self._gate_status()

    # ---------------- advanced settings ----------------
    def _advanced(self):
        # SINGLETON (#176): stacked settings dialogs each hold the
        # values from their open time, so Apply on a stale one silently
        # reverts newer changes. Re-clicking fronts the live dialog.
        if self._adv_win is not None and self._adv_win.winfo_exists():
            self._adv_win.lift()
            self._adv_win.focus_set()
            return
        win = tk.Toplevel(self.root)
        self._adv_win = win
        win.title("Edge detection settings")
        entries = {}
        tips = {'diam_mm': "DEA resting active-area diameter (mm) — sets the "
                           "px→mm scale via the baseline detection",
                'blur_px': "Gaussian blur kernel (odd px)",
                'diff_thresh': "fixed diff threshold; 0 = auto (Otsu tiers)",
                'min_diff': "diff p99 below this = no change vs baseline "
                            "(frame auto-rejected; lower it to dig for "
                            "subtle changes; frames above it always yield "
                            "at least one candidate for review)",
                'electrode_lum': "mask pixels this bright in the BASELINE "
                                 "(plus the texture-derived foil "
                                 "footprint) — the electrodes are static, "
                                 "so the baseline knows where they are; "
                                 "0 disables",
                'min_solidity': "drop candidates below this solidity (0–1); "
                                "oblong shapes still score 1.0",
                'roi_frac': "central search window as a fraction of the "
                            "frame (ignores electrode glare at the edges)",
                'accept_conf': "auto-accept at/above this confidence (0–1)",
                'spread_pct': "candidate area disagreement (%) forcing review",
                'audit_nostep_pct': "self-audit gate: % of the winning "
                                    "boundary's arc with no measurable ink "
                                    "step under it above which the frame is "
                                    "capped to review; 0 disables",
                'audit_bias_px': "self-audit gate: median offset (px) "
                                 "between the fitted boundary and the "
                                 "measured ink step above which the frame "
                                 "is capped to review (catches resting "
                                 "claims gone stale); 0 disables",
                'breakdown_dev_ua': "current deviation (µA) from the run's "
                                    "median that marks a breakdown event "
                                    "row; two adjacent event rows (or one "
                                    "ending the run) confirm, a single "
                                    "recovered one is an advisory note",
                'breakdown_ua': "gross ABSOLUTE current limit (µA) — "
                                "fallback used only when the run has "
                                "fewer than 5 readable µA rows (no "
                                "median baseline)",
                'area_jump_pct': "area collapse (%) while voltage rises: "
                                 "confirms breakdown only with a current "
                                 "event at the same kV level, otherwise "
                                 "an advisory note",
                'wrinkle_ratio': "wrinkle index (texture vs baseline) at/"
                                 "above this = wrinkle-mode; first such "
                                 "frame is noted as the onset",
                'norm_bg': "photometric normalization vs the baseline "
                           "before diffing (cancels the camera's internal "
                           "auto-gain drift): 2 = gain+offset fit on ROI "
                           "quantiles (default), 1 = legacy scalar "
                           "border-band ratio, 0 = off"}
        for r, key in enumerate(se.DEFAULT_SETTINGS):
            ttk.Label(win, text=f"{key}:").grid(row=r, column=0, sticky='e',
                                                padx=6, pady=3)
            e = ttk.Entry(win, width=10)
            e.insert(0, f"{self.settings[key]:g}")
            e.grid(row=r, column=1, padx=6)
            ttk.Label(win, text=tips.get(key, ''), foreground='#666',
                      wraplength=380, justify='left').grid(
                row=r, column=2, sticky='w', padx=6)
            entries[key] = e

        # knobs that change what DETECTION produces — applying one of
        # these invalidates the current pass; the rest (breakdown
        # thresholds, wrinkle onset, diam_mm) are pure post-processing
        # and are recomputed live instead (audit 2026-08-05: Apply used
        # to leave Save armed with flags computed under the OLD
        # thresholds, and mark_breakdown_files renamed frames on them)
        detect_keys = ('blur_px', 'diff_thresh', 'min_diff',
                       'min_solidity', 'roi_frac', 'electrode_lum',
                       'accept_conf', 'spread_pct', 'audit_nostep_pct',
                       'audit_bias_px', 'wrinkle_ratio', 'tex_seg',
                       'norm_bg')

        def apply(save=False):
            if self._detect_busy:
                # the generation token protects run SWITCHES; a mid-
                # detect settings change would let the still-streaming
                # worker (bound to the OLD settings) refill a pass the
                # apply just cleared — auto-accepting old-settings
                # candidates under new-settings gates, and recording
                # settings that do not reproduce the outputs (review
                # 2026-08-05)
                messagebox.showinfo(
                    "Settings", "Detection is running — wait for it to "
                    "finish (or switch runs) before applying settings.",
                    parent=win)
                return
            try:
                new = {}
                for key, e in entries.items():
                    cast = type(se.DEFAULT_SETTINGS[key])
                    new[key] = cast(float(e.get()))
            except ValueError as err:
                messagebox.showerror("Settings", str(err), parent=win)
                return
            has_pass = bool(self.results or self.cands_all)
            invalidates = has_pass and any(
                new[k] != self.settings[k] for k in detect_keys)
            if invalidates:
                n_rev = sum(1 for i in self.results
                            if i not in self.auto_idx
                            and i not in self.auto_rej)
                if not messagebox.askyesno(
                        "Settings",
                        f"These change what detection produces — the "
                        f"current pass ({len(self.results)} decided "
                        f"frame(s), {n_rev} by hand) will be CLEARED and "
                        f"Detect must re-run.\n\nApply anyway?",
                        parent=win):
                    return
            self.settings.update(new)
            if save and self.rundir:
                se.save_settings(self.rundir, self.settings)
            win.destroy()
            saved_txt = " + saved to setup.txt" if save else ""
            if invalidates:
                self.cands_all, self.results, self.flags = {}, {}, {}
                self.advisories = {}
                self.traces = {}
                self.auto_idx, self.auto_rej = set(), set()
                self.load_fail = {}
                self.save_btn.config(state='disabled')
                self.status.config(
                    text=f"settings applied{saved_txt} — pass "
                         f"invalidated, re-run Detect")
                self._show()
            elif self.run and (self.results or self.cands_all):
                # post-processing knobs: flags, advisories and the info
                # panel refresh NOW, so Save can never rename frames on
                # thresholds the operator just changed away from
                self._recount()
                self._show()
                self.status.config(
                    text=f"settings applied{saved_txt} — breakdown/"
                         f"wrinkle flags recomputed "
                         f"({len(self.flags)} confirmed, "
                         f"{len(self.advisories)} advisory)")
            else:
                self.status.config(
                    text=f"settings applied{saved_txt} — run Detect")

        bf = ttk.Frame(win)
        bf.grid(row=len(se.DEFAULT_SETTINGS), column=0, columnspan=3, pady=8)
        ttk.Button(bf, text="Apply", command=apply).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="Apply + Save to setup.txt",
                   command=lambda: apply(True)).pack(side=tk.LEFT, padx=4)


class TraceWindow(tk.Toplevel):
    """Manual boundary tracing (#162): click points that close into the
    outer edge of the active area. All geometry/undo/coordinate state
    lives in sldea_trace (headless-tested); this class only translates
    Tk events into model calls and repaints. Done STAGES the polygon as
    candidate D in the review card (app._trace_staged); the operator
    commits it with Accept, same as any candidate (#172).

    Interaction: left-click add point (drag an existing point to move
    it, right-click deletes it), wheel zooms about the cursor, middle-
    or space-drag pans, F fits, Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z) undo/
    redo, Enter / double-click / clicking the first point closes,
    Esc cancels. The polygon is stored in FULL-RES image px throughout
    -- zoom can never desynchronize clicks from image coordinates."""

    CV_W, CV_H = 900, 620
    GRAB_PX = 8            # view-px radius: press on a point = drag it
    DEL_PX = 12            # view-px radius for right-click delete

    def __init__(self, app, row_index, img_path, mm_per_px=None,
                 seed=None, seed_snapped=False, unpaired_ack=None):
        super().__init__(app.root)
        from PIL import Image
        self.app = app
        self.row_index = row_index
        self.mm_per_px = mm_per_px
        # the pairing gap the operator acknowledged before this window
        # opened (#162) — travels back with Done so _trace_staged knows
        # whether it still has to say it, and dies with the window
        self._unpaired_ack = unpaired_ack
        self.img = Image.open(img_path).convert('RGB')
        self.gray = se.load_gray(img_path)
        row = app.run['rows'][row_index]
        self.title(f"Trace boundary — step {row.get('step')} "
                   f"[{row.get('tag')}] {row.get('nominal_kV')} kV")
        self.model = strc.TraceModel()
        self._seeded = bool(seed)
        if seed:
            # re-trace (#172): edit the pending D polygon instead of
            # re-clicking it. Seeded points are the baseline state (not
            # undoable ops); Restart still clears them in one step.
            self.model.points = [(float(x), float(y)) for x, y in seed]
        self.vt = strc.ViewTransform()
        self.vt.fit(self.img.width, self.img.height, self.CV_W, self.CV_H)
        self._t_open = time.time()
        # a seeded polygon traced with the magnet keeps its 'snapped'
        # tag -- the label must not launder snapped points as freehand
        self._snap_used = bool(seed_snapped)
        self._drag_idx = None
        self._drag_orig = None
        self._pan_from = None
        self._space = False
        self._cursor = None
        self._photo = None

        bar = ttk.Frame(self, padding=4)
        bar.pack(fill='x')
        self.undo_btn = ttk.Button(bar, text="↶ Undo",
                                   command=self._undo, state='disabled')
        self.undo_btn.pack(side=tk.LEFT)
        self.redo_btn = ttk.Button(bar, text="↷ Redo",
                                   command=self._redo, state='disabled')
        self.redo_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="⟲ Restart placements…",
                   command=self._restart).pack(side=tk.LEFT, padx=(8, 0))
        self.snap_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="edge snap",
                        variable=self.snap_var).pack(side=tk.LEFT,
                                                     padx=(12, 0))
        self.ov_rest = tk.BooleanVar(value=True)
        self.ov_cand = tk.BooleanVar(value=False)
        self.ov_prev = tk.BooleanVar(value=False)
        for var, txt in ((self.ov_rest, "resting disc"),
                         (self.ov_cand, "candidates"),
                         (self.ov_prev, "prev outline")):
            ttk.Checkbutton(bar, text=txt, variable=var,
                            command=self._repaint).pack(side=tk.LEFT,
                                                        padx=(6, 0))
        ttk.Button(bar, text="✔ Done (Enter)",
                   command=self._done).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Cancel (Esc)",
                   command=self._cancel).pack(side=tk.RIGHT, padx=6)
        self.zoom_lbl = ttk.Label(bar, text="")
        self.zoom_lbl.pack(side=tk.RIGHT, padx=8)

        self.cv = tk.Canvas(self, width=self.CV_W, height=self.CV_H,
                            bg='#111', highlightthickness=0,
                            cursor='crosshair')
        self.cv.pack(padx=4, pady=4)
        self.stat = tk.Label(self, anchor='w', justify='left',
                             text="click to place points — they close "
                                  "into the outer edge of the active area")
        self.stat.pack(fill='x', padx=6, pady=(0, 4))

        self.cv.bind('<Button-1>', self._press)
        self.cv.bind('<B1-Motion>', self._drag)
        self.cv.bind('<ButtonRelease-1>', self._release)
        self.cv.bind('<Button-3>', self._delete_near)
        self.cv.bind('<Double-Button-1>', lambda e: self._done())
        self.cv.bind('<Motion>', self._motion)
        self.cv.bind('<MouseWheel>',
                     lambda e: self._wheel(e.x, e.y, e.delta / 120.0))
        self.cv.bind('<Button-4>', lambda e: self._wheel(e.x, e.y, 1))
        self.cv.bind('<Button-5>', lambda e: self._wheel(e.x, e.y, -1))
        self.cv.bind('<Button-2>', self._pan_start)
        self.cv.bind('<B2-Motion>', self._pan_move)
        self.bind('<Control-z>', lambda e: self._undo())
        self.bind('<Control-y>', lambda e: self._redo())
        self.bind('<Control-Z>', lambda e: self._redo())   # Ctrl+Shift+Z
        self.bind('<Key-f>', lambda e: self._fit())
        self.bind('<Key-F>', lambda e: self._fit())
        self.bind('<Return>', lambda e: self._done())
        self.bind('<Escape>', lambda e: self._cancel())
        self.bind('<KeyPress-space>', lambda e: self._set_space(True))
        self.bind('<KeyRelease-space>', lambda e: self._set_space(False))
        self.protocol('WM_DELETE_WINDOW', self._cancel)
        self.transient(app.root)
        self.grab_set()
        self.cv.focus_set()
        self._repaint()

    # -- coordinate helpers ---------------------------------------------
    def _img_xy(self, ev):
        return self.vt.to_image(ev.x, ev.y)

    def _near_point(self, ev, r_view):
        ix, iy = self._img_xy(ev)
        return self.model.nearest(ix, iy, r_view / self.vt.zoom)

    # -- pointer events -------------------------------------------------
    def _press(self, ev):
        if self._space:
            self._pan_start(ev)
            return
        idx = self._near_point(ev, self.GRAB_PX)
        pts = self.model.points
        if idx == 0 and len(pts) >= 3:
            self._done()
            return
        if idx is not None:
            self._drag_idx = idx
            self._drag_orig = pts[idx]
            return
        ix, iy = self._img_xy(ev)
        if self.snap_var.get() and self.gray is not None:
            ix, iy = strc.edge_snap(self.gray, ix, iy)
            self._snap_used = True
        self.model.add(ix, iy)
        self._vectors()

    def _drag(self, ev):
        if self._pan_from is not None:
            self._pan_move(ev)
            return
        if self._drag_idx is None:
            return
        self.model.points[self._drag_idx] = self._img_xy(ev)
        self._vectors()

    def _release(self, ev):
        if self._pan_from is not None:
            self._pan_from = None
            return
        if self._drag_idx is None:
            return
        idx, orig = self._drag_idx, self._drag_orig
        self._drag_idx = self._drag_orig = None
        ix, iy = self._img_xy(ev)
        if self.snap_var.get() and self.gray is not None:
            ix, iy = strc.edge_snap(self.gray, ix, iy)
            self._snap_used = True
        # reconcile through the op stack: transient motion above was a
        # preview; the MOVE is one atomic, undoable op
        self.model.points[idx] = orig
        self.model.move(idx, ix, iy)
        self._vectors()

    def _delete_near(self, ev):
        idx = self._near_point(ev, self.DEL_PX)
        if idx is not None:
            self.model.delete(idx)
            self._vectors()

    def _motion(self, ev):
        self._cursor = (ev.x, ev.y)
        self._vectors()

    # -- view -----------------------------------------------------------
    def _wheel(self, vx, vy, steps):
        self.vt.zoom_at(vx, vy, 1.15 ** steps)
        self._repaint()

    def _pan_start(self, ev):
        self._pan_from = (ev.x, ev.y)

    def _pan_move(self, ev):
        if self._pan_from is None:
            return
        dx, dy = ev.x - self._pan_from[0], ev.y - self._pan_from[1]
        self._pan_from = (ev.x, ev.y)
        self.vt.pan_view(dx, dy)
        self._repaint()

    def _set_space(self, held):
        self._space = held
        if not held:
            self._pan_from = None

    def _fit(self):
        self.vt.fit(self.img.width, self.img.height, self.CV_W, self.CV_H)
        self._repaint()

    # -- history --------------------------------------------------------
    def _undo(self):
        if self.model.undo():
            self._vectors()

    def _redo(self):
        if self.model.redo():
            self._vectors()

    def _restart(self):
        if not self.model.points:
            return
        if messagebox.askyesno("Restart placements",
                               "Remove ALL placed points and start over?\n"
                               "(This is one undoable step.)",
                               parent=self):
            self.model.restart()
            self._vectors()

    # -- painting -------------------------------------------------------
    def _repaint(self):
        """Photo layer: the visible crop of the full-res frame, resized
        to the viewport (nearest-neighbour when zoomed in, so pixels stay
        honest). Vector layer painted on top."""
        from PIL import Image, ImageTk
        t = self.vt
        ix0, iy0 = t.to_image(0, 0)
        ix1, iy1 = t.to_image(self.CV_W, self.CV_H)
        cx0, cy0 = max(0, int(ix0)), max(0, int(iy0))
        cx1 = min(self.img.width, int(ix1) + 2)
        cy1 = min(self.img.height, int(iy1) + 2)
        self.cv.delete('img')
        if cx1 > cx0 and cy1 > cy0:
            crop = self.img.crop((cx0, cy0, cx1, cy1))
            dw = max(1, int(round((cx1 - cx0) * t.zoom)))
            dh = max(1, int(round((cy1 - cy0) * t.zoom)))
            res = Image.NEAREST if t.zoom >= 2.0 else Image.BILINEAR
            self._photo = ImageTk.PhotoImage(crop.resize((dw, dh), res))
            vx, vy = t.to_view(cx0, cy0)
            self.cv.create_image(int(vx), int(vy), anchor='nw',
                                 image=self._photo, tags='img')
        self.cv.tag_lower('img')
        self.zoom_lbl.config(text=f"zoom {100 * t.zoom:.0f}%")
        self._vectors()

    def _poly_view(self, contour):
        return [c for x, y in np.asarray(contour, float)
                for c in self.vt.to_view(x, y)]

    def _vectors(self):
        self.cv.delete('vec')
        t = self.vt
        # context overlays (recorded in the label so calibration knows
        # what the operator could see)
        if self.ov_rest.get() and self.app.base_ref is not None \
                and self.app.base_ref.get('contour') is not None:
            self.cv.create_polygon(
                *self._poly_view(self.app.base_ref['contour']),
                outline='#888888', fill='', dash=(4, 4), tags='vec')
        if self.ov_cand.get():
            for k, c in enumerate(self.app.cands_all.get(self.row_index,
                                                         [])):
                self.cv.create_polygon(
                    *self._poly_view(c['contour']),
                    outline=CAND_COLORS[k], fill='', dash=(2, 4),
                    tags='vec')
        if self.ov_prev.get():
            prev = None
            for j in self.app.frame_rows:
                if j >= self.row_index:
                    break
                r = self.app.results.get(j)
                if r:
                    prev = r
            if prev is not None:
                self.cv.create_polygon(
                    *self._poly_view(prev['contour']),
                    outline='#b39ddb', fill='', dash=(6, 3), tags='vec')
        pts = self.model.points
        vp = [self.vt.to_view(x, y) for x, y in pts]
        if len(vp) >= 2:
            for a, b in zip(vp[:-1], vp[1:]):
                self.cv.create_line(*a, *b, fill='#00e676', width=2,
                                    tags='vec')
        if len(vp) >= 3:
            self.cv.create_line(*vp[-1], *vp[0], fill='#00e676',
                                dash=(3, 4), tags='vec')
        if self._cursor and vp and self._drag_idx is None:
            self.cv.create_line(*vp[-1], *self._cursor, fill='#80cbc4',
                                dash=(2, 4), tags='vec')
        for k, (vx, vy) in enumerate(vp):
            r = 5 if k == 0 else 3
            self.cv.create_oval(vx - r, vy - r, vx + r, vy + r,
                                outline='#00e676',
                                width=2 if k == 0 else 1,
                                fill='#003322', tags='vec')
        self.undo_btn.config(
            state='normal' if self.model.can_undo() else 'disabled')
        self.redo_btn.config(
            state='normal' if self.model.can_redo() else 'disabled')
        area = strc.polygon_area(pts)
        mm = (f"  =  {area * self.mm_per_px ** 2:.1f} mm²"
              if self.mm_per_px and area else "")
        self.stat.config(
            text=f"{len(pts)} point(s) — area {area:.0f} px²{mm} — "
                 f"click add · drag move · right-click delete · wheel "
                 f"zoom · middle/space drag pan · Enter/double-click/"
                 f"first-point close · F fit · Esc cancel")

    # -- finish ---------------------------------------------------------
    def _done(self):
        pts = list(self.model.points)
        if len(pts) < 3:
            messagebox.showinfo("Trace", "Place at least 3 points to "
                                "close the outline.", parent=self)
            return
        if strc.self_intersects(pts) and not messagebox.askyesno(
                "Trace", "The outline crosses itself. Keep it anyway?",
                parent=self):
            return
        meta = {'zoom': self.vt.zoom,
                'overlays': {'resting': bool(self.ov_rest.get()),
                             'candidates': bool(self.ov_cand.get()),
                             'prev': bool(self.ov_prev.get())},
                'elapsed_s': time.time() - self._t_open,
                'snapped': self._snap_used,
                'unpaired_ack': self._unpaired_ack}
        self.grab_release()
        self.destroy()
        self.app._trace_staged(self.row_index, pts, meta)

    def _cancel(self):
        msg = ("Close the tracer? The previously staged D outline is "
               "kept; this session's edits are discarded."
               if self._seeded else "Discard the traced points?")
        if self.model.points and not messagebox.askyesno(
                "Trace", msg, parent=self):
            return
        self.grab_release()
        self.destroy()
        # clicking the D radio set the selection before opening the
        # tracer; a cancel must put it back where the frame's state says
        self.app._show()


def main():
    args = [a for a in sys.argv[1:]]
    auto = '--auto' in args
    path = next((a for a in args if not a.startswith('--')), None)
    root = tk.Tk()
    EdgeReviewApp(root, path=path, auto=auto)
    root.mainloop()


if __name__ == '__main__':
    main()
