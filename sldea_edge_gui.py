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

With --auto (used by the SLDEA tab's "auto process"), detection starts
immediately on launch. Keyboard: 1/2/3 pick a candidate, R reject,
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

import numpy as np

import sldea_edge as se
import sldea_trace as strc

DEFAULT_PARENT = os.environ.get('SCPI_SLDEA_DIR',
                                '/mnt/shareDrive/robot_incubator/SLDEA_data')
# A green, B blue, C orange, D magenta (D = the manual trace, #172)
CAND_COLORS = ['#00c853', '#2196f3', '#ff9100', '#e040fb']
CAND_KEYS = ['A', 'B', 'C', 'D']
TRACE_SLOT = 3          # radio value / paint slot of the manual trace
VIEW_W = 780
TAG_PX = 20             # letter-tag font size on the review card (#173)

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
        self.frame_rows = []    # row indices that have a frame file
        self.pos = 0
        self.flags = {}
        self._photo = None
        self._detq = _queue.Queue()
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
        ttk.Button(top, text="Browse…",
                   command=self._browse).pack(side=tk.LEFT)
        self.detect_btn = ttk.Button(top, text="▶ Detect Edges",
                                     command=self.detect)
        self.detect_btn.pack(side=tk.LEFT, padx=10)
        ttk.Button(top, text="Advanced…",
                   command=self._advanced).pack(side=tk.LEFT)
        ttk.Button(top, text="🎚 Tune…",
                   command=self._open_tuner).pack(side=tk.LEFT, padx=(6, 0))
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
        self.canvas = tk.Canvas(mid, width=VIEW_W, height=560, bg='#222',
                                highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill='both', expand=True,
                         padx=(6, 0), pady=4)

        side = ttk.Frame(mid, padding=8, width=330)
        side.pack(side=tk.RIGHT, fill='y')
        self.info = tk.Label(side, text="pick a run and Detect", justify='left',
                             anchor='nw', font=('TkDefaultFont', 10))
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

    def _pick_run(self):
        name = (self.run_box.get() or '').split('  ')[0]
        if not name:
            return
        self.rundir = os.path.join(self.parent, name)
        try:
            self.run = se.load_run(self.rundir)
        except Exception as e:
            messagebox.showerror("Run", f"Cannot read {name}: {e}")
            self.run = None
            return
        self.settings = se.load_settings(self.rundir)
        self.frame_rows = [i for i, r in enumerate(self.run['rows'])
                           if (r.get('frame_file') or '').strip()]
        self.cands_all, self.results, self.flags = {}, {}, {}
        self.traces = {}
        self.auto_idx, self.auto_rej = set(), set()
        self.base_ref = None
        self.manual_ref = None
        self.pos = 0
        self.save_btn.config(state='disabled')
        n = len(self.frame_rows)
        self.status.config(
            text=f"{name}: {len(self.run['rows'])} snapshots, {n} frames "
                 f"on disk — Detect to trace edges "
                 f"(diam {self.settings['diam_mm']:g} mm)")
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
            w = int(self.canvas['width'] or VIEW_W)
            h = int(self.canvas['height'] or 560)
            self.canvas.create_rectangle(0, h // 2 - 42, w, h // 2 + 42,
                                         fill='#b36b00', outline='',
                                         tags='banner')
            self.canvas.create_text(w // 2, h // 2, text=text, fill='white',
                                    font=('TkDefaultFont', 20, 'bold'),
                                    tags='banner')

    def detect(self):
        if not self.run:
            messagebox.showinfo("Detect", "Pick a run first")
            return
        if not self.frame_rows:
            messagebox.showinfo(
                "Detect", "This run has no frames on disk (the camera was "
                "busy or dry-run frames were skipped).")
            return
        self.detect_btn.config(state='disabled')
        # Every Detect pass starts CLEAN: stale results from a previous
        # pass (old settings, manual picks) used to survive re-detection
        # and get saved as a silent mix of two passes (audit 2026-07-25).
        # Staged traces clear too — their polygons are already safe in
        # edge_labels.json (appended at trace-Done, #172).
        self.cands_all, self.results, self.flags = {}, {}, {}
        self.traces = {}
        self.auto_idx, self.auto_rej = set(), set()
        self.base_ref = None
        self._t0 = time.time()
        self._clock_on = True
        self._tick_clock()
        self.prog.config(maximum=len(self.frame_rows), value=0)
        self.canvas.delete('all')
        self._banner(f"DETECTING…  0/{len(self.frame_rows)}")
        self.status.config(text="detecting…")
        threading.Thread(target=self._detect_worker, daemon=True).start()
        self.root.after(100, self._poll_detect)

    def _base_gray(self):
        for i in self.frame_rows:
            if self.run['rows'][i].get('tag') == 'baseline':
                return se.load_gray(se.frame_path(self.run,
                                                  self.run['rows'][i]))
        return None

    def _detect_worker(self):
        # Per-frame try + sentinel in finally: one bad frame (shape
        # mismatch, decode error) used to kill the thread silently and
        # leave 'DETECTING…' stuck forever (audit 2026-07-25).
        try:
            base = self._base_gray()
            self._base_ref_pending = se.baseline_disc(base, self.settings)
            prev = None
            for i in self.frame_rows:
                try:
                    img = se.load_gray(
                        se.frame_path(self.run, self.run['rows'][i]))
                    cands = [] if img is None else se.candidates(
                        base, img, self.settings, prev_method=prev)
                except Exception as e:
                    print(f"detect: frame {i} failed: {e}")
                    cands = []
                if cands:
                    prev = cands[0]['method']
                self._detq.put((i, cands))
        finally:
            self._detq.put(None)

    def _poll_detect(self):
        done = False
        while True:
            try:
                item = self._detq.get_nowait()
            except _queue.Empty:
                break
            if item is None:
                done = True
                break
            i, cands = item
            self.cands_all[i] = cands
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
            self.root.after(100, self._poll_detect)

    def detect_all_sync(self):
        """Synchronous detection (used by --auto tests and headless runs)."""
        self._t0 = self._t0 or time.time()
        self.cands_all, self.results, self.flags = {}, {}, {}
        self.traces = {}
        self.auto_idx, self.auto_rej = set(), set()
        base = self._base_gray()
        self._base_ref_pending = se.baseline_disc(base, self.settings)
        prev = None
        for i in self.frame_rows:
            img = se.load_gray(se.frame_path(self.run, self.run['rows'][i]))
            self.cands_all[i] = [] if img is None else se.candidates(
                base, img, self.settings, prev_method=prev)
            if self.cands_all[i]:
                prev = self.cands_all[i][0]['method']
        self._finish_detect()

    def _finish_detect(self):
        self.auto_rej = set()
        # px→mm reference traced on the BASELINE frame itself (non-diff);
        # manual calibration (📏) overrides it.
        self.base_ref = getattr(self, '_base_ref_pending', None)
        # the pre/post pair is the run's own control: agreement raises
        # confidence, contradiction forces review on both members
        se.reconcile_pairs(self.run['rows'], self.cands_all, self.settings)
        for i in self.frame_rows:
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
        self.detect_btn.config(state='normal')
        self.save_btn.config(state='normal')
        self.prog.config(value=len(self.frame_rows))
        self._banner(None)
        q = self._queue_list()
        took = self._fmt_t(time.time() - self._t0) if self._t0 else '?'
        sc = (f"; scale ref: baseline disc {self.base_ref['diam_px']:.0f} px"
              if self.base_ref else "; scale ref: NONE — use 📏 Calibrate")
        self.status.config(
            text=f"detected {len(self.frame_rows)} frames in {took}: "
                 f"{len(self.auto_idx)} auto-accepted, "
                 f"{len(self.auto_rej)} no-change/no-edge, "
                 f"{len(q)} need review{sc}")
        self.pos = self.frame_rows.index(q[0]) if q else 0
        self._show()

    def _queue_list(self):
        return [i for i in self.frame_rows if i not in self.results]

    def _recount(self):
        areas = {i: r['area_px'] for i, r in self.results.items() if r}
        self.flags = se.breakdown_flags(self.run['rows'], areas, self.settings)

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
        # info panel
        state = ('auto-accepted' if i in self.auto_idx else
                 'accepted' if chosen else
                 'no change vs baseline (auto)' if i in self.auto_rej
                 and i in self.results else
                 'REJECTED' if i in self.results else 'needs review')
        txt = (f"frame {self.pos+1}/{len(self.frame_rows)}   step "
               f"{row.get('step')} [{row.get('tag')}]\n"
               f"nominal {row.get('nominal_kV')} kV   "
               f"measured {row.get('measured_kV') or '—'} kV   "
               f"{row.get('measured_uA') or '—'} µA\n"
               f"state: {state}")
        if i in self.flags:
            txt += f"\n⚠ {self.flags[i]}"
        self.info.config(text=txt)
        for k in range(3):
            if k < len(cands):
                c = cands[k]
                self.cand_radios[k].config(
                    text=f"{CAND_KEYS[k]}: {c['method']}  "
                         f"{c['area_px']:.0f} px²  conf {c['conf']:.2f}"
                         f"  w{c.get('wrinkle', 1):.1f}",
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
            self.cand_radios[TRACE_SLOT].config(
                text=f"D: manual-trace  {trace['area_px']:.0f} px²{mm}"
                     f"  ({trace['n_points']} pts)",
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

    def _render_card(self, i, cands, chosen):
        """The review card as a PIL image (no Tk): frame + candidate
        outlines + letter tags. Split from _draw so the rendering is
        checkable headlessly -- the card is what the operator judges."""
        from PIL import Image, ImageDraw
        import numpy as np
        path = se.frame_path(self.run, self.run['rows'][i])
        img = Image.open(path).convert('RGB')
        scale = VIEW_W / img.width
        img = img.resize((VIEW_W, int(img.height * scale)))
        dr = ImageDraw.Draw(img)
        entries = list(enumerate(cands))
        trace = self.traces.get(i)
        if trace is not None:              # the staged D outline (#172)
            entries.append((TRACE_SLOT, trace))
        hot = hot_slot(entries, chosen, self.cand_var.get())
        font = _tag_font()
        for slot, c in entries:
            pts = [(float(x) * scale, float(y) * scale)
                   for x, y in np.asarray(c['contour'])]
            if len(pts) <= 2:
                continue
            # thicker lines, selection visibly heavier (#171/#173)
            wdt = 3 if slot == hot else 2
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
        return img

    def _draw(self, i, cands, chosen):
        from PIL import ImageTk
        try:
            img = self._render_card(i, cands, chosen)
        except OSError:        # frame missing/undecodable; draw bugs stay loud
            self.canvas.delete('all')
            return
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete('all')
        self.canvas.config(width=img.width, height=img.height)
        self.canvas.create_image(0, 0, anchor='nw', image=self._photo)

    def _pick_k(self, k):
        i = self._current()
        if i is None or k >= len(self.cands_all.get(i, [])):
            return
        self.cand_var.set(k)
        self._choose_current()

    def _choose_current(self):
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
        i = self._current()
        if i is None:
            return
        self.results[i] = None
        self.auto_idx.discard(i)
        self._recount()
        self._advance()

    # ---------------- manual trace (#162, candidate D per #172) --------
    def _trace(self):
        """Open the manual tracer: the recovery path when every candidate
        is rejected, and the labeling instrument for the conf-vs-IoU
        calibration. Allowed even when a candidate exists -- correcting a
        near-miss is a valuable label, not a rejection. The closed trace
        is STAGED as candidate D (row D + drawn on the card); Accept
        commits it like any other candidate (#172). Re-opening D edits
        the pending polygon rather than starting over."""
        i = self._current()
        if self.run is None or i is None:
            messagebox.showinfo("Trace", "Pick a run first")
            return
        path = se.frame_path(self.run, self.run['rows'][i])
        if not path or not os.path.exists(path):
            messagebox.showinfo("Trace", "This row has no frame on disk.")
            self._show()               # the D radio may have grabbed sel
            return
        scale = se.mm_per_px(self.results, self.run['rows'], self.settings,
                             baseline_ref=self.manual_ref or self.base_ref)
        trace = self.traces.get(i) or {}
        TraceWindow(self, i, path, mm_per_px=scale,
                    seed=trace.get('trace_points'),
                    seed_snapped=bool(trace.get('snapped')))

    def _trace_staged(self, i, points, meta):
        """TraceWindow Done -> the polygon is staged as candidate D and
        the ground-truth label is appended to edge_labels.json. Staging
        does NOT touch results -- Accept commits (#172). The label
        appends HERE, at Done, so a completed trace is never lost even
        if it is not accepted; a re-trace appends another record (repeat
        labels are how operator repeatability was measured). Tracing
        never touches data.csv/setup.txt -- the committed result flows
        through the normal Save path."""
        poly = np.asarray(points, np.float64)
        area = strc.polygon_area(poly)
        cx, cy = strc.polygon_centroid(poly)
        wrinkle = None
        gray = se.load_gray(se.frame_path(self.run, self.run['rows'][i]))
        try:
            base = self._base_gray()
            if base is not None and gray is not None:
                wrinkle = se._wrinkle_ratio(base, gray,
                                            poly.astype(np.int32))
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
        # at trace time so IoU is computable offline (#162)
        cands = self.cands_all.get(i, [])
        shape = gray.shape if gray is not None else (0, 0)
        rec = strc.label_record(i, self.run['rows'][i], poly, shape,
                                machine=cands[0] if cands else None,
                                **meta)
        self._select_trace_once = True
        try:
            strc.append_label(self.rundir, rec)
            n = len(strc.load_labels(self.rundir))
            self.status.config(
                text=f"trace staged as candidate D ({area:.0f} px², "
                     f"{len(poly)} points) — Accept (Enter) commits; "
                     f"label {n} in {strc.LABELS_NAME}")
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
        q = self._queue_list()
        accepted = sum(1 for r in self.results.values() if r)
        rejected = sum(1 for r in self.results.values() if r is None)
        n_bd = 0
        if self.flags:
            start = min(self.flags)
            n_bd = sum(1 for i in self.frame_rows if i >= start)
        msg = (f"Write results into this run's data.csv?\n\n"
               f"accepted: {accepted}  (auto {len(self.auto_idx)})\n"
               f"rejected: {rejected}\n"
               f"unreviewed (left blank): {len(q)}\n"
               f"breakdown-flagged: {len(self.flags)}\n"
               + (f"\n⚠ {n_bd} frame file(s) from the first breakdown onward "
                  f"will be RENAMED with a _BREAKDOWN suffix (kept, never "
                  f"deleted — usable later as ML training data).\n"
                  if n_bd else "\n")
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
        if 'wrinkle_idx' not in self.run['columns']:
            # older runs predate the column; slot it in before notes
            cols = self.run['columns']
            cols.insert(cols.index('notes') if 'notes' in cols else len(cols),
                        'wrinkle_idx')
        for row in self.run['rows']:
            row.setdefault('wrinkle_idx', '')
        # The destructive phase (renames + CSV rewrite) must NEVER fail
        # silently: an hour of review used to vanish without a dialog on a
        # NAS hiccup (audit 2026-07-25). write_back is atomic now, and
        # data.csv.bak always predates the renames.
        try:
            se.apply_results(self.run['rows'], self.results, scale,
                             self.flags, annos)
            renamed = se.mark_breakdown_files(self.run, self.flags)
            se.write_back(self.rundir, self.run)
        except Exception as e:
            messagebox.showerror(
                "Save FAILED",
                f"Writing results failed:\n\n{e}\n\nYour review is still in "
                f"memory — fix the problem (share up? disk full?) and Save "
                f"again. A pre-save backup is at data.csv.bak.")
            return
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
        bd_txt = f", {renamed} frame(s) renamed _BREAKDOWN" if renamed else ""
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

    def _calibrate_scale(self):
        """Manual px→mm calibration: click the two opposite edges of the
        RESTING disc on the baseline frame; the known nominal diameter
        (diam_mm) between them sets the scale. Overrides the automatic
        baseline-disc detection."""
        if not self.run:
            messagebox.showinfo("Calibrate", "Pick a run first")
            return
        base_row = None
        for i in self.frame_rows:
            if self.run['rows'][i].get('tag') == 'baseline':
                base_row = self.run['rows'][i]
                break
        if base_row is None and self.frame_rows:
            base_row = self.run['rows'][self.frame_rows[0]]
        path = se.frame_path(self.run, base_row) if base_row else None
        if not path or not os.path.exists(path):
            messagebox.showinfo("Calibrate", "No baseline frame on disk.")
            return
        from PIL import Image, ImageTk
        img = Image.open(path).convert('RGB')
        scale_v = VIEW_W / img.width
        disp = img.resize((VIEW_W, int(img.height * scale_v)))
        win = tk.Toplevel(self.root)
        win.title("Calibrate scale — click the disc's two opposite edges")
        win.transient(self.root)
        tk.Label(win, text=f"Click LEFT edge then RIGHT edge of the resting "
                           f"disc (nominal {self.settings['diam_mm']:g} mm "
                           f"across). Esc cancels.").pack(pady=(6, 2))
        cv = tk.Canvas(win, width=disp.width, height=disp.height)
        cv.pack(padx=8, pady=8)
        photo = ImageTk.PhotoImage(disp)
        cv.create_image(0, 0, anchor='nw', image=photo)
        cv.image = photo
        pts = []

        def click(ev):
            pts.append((ev.x, ev.y))
            cv.create_oval(ev.x - 4, ev.y - 4, ev.x + 4, ev.y + 4,
                           outline='#00e676', width=2)
            if len(pts) == 2:
                cv.create_line(*pts[0], *pts[1], fill='#00e676', width=2)
                dpx_disp = ((pts[0][0] - pts[1][0]) ** 2 +
                            (pts[0][1] - pts[1][1]) ** 2) ** 0.5
                dpx_full = dpx_disp / scale_v
                if dpx_full < 10:
                    messagebox.showwarning("Calibrate",
                                           "Points are too close — retry.")
                    win.destroy()
                    return
                self.manual_ref = {'method': 'manual-calibration',
                                   'diam_px': dpx_full}
                self.status.config(
                    text=f"scale calibrated manually: "
                         f"{self.settings['diam_mm']:g} mm = "
                         f"{dpx_full:.0f} px "
                         f"({self.settings['diam_mm'] / dpx_full:.5f} mm/px)"
                         f" — used at Save")
                win.destroy()

        cv.bind('<Button-1>', click)
        win.bind('<Escape>', lambda e: win.destroy())
        cv.focus_set()
        win.grab_set()
        self.root.wait_window(win)

    def _open_tuner(self):
        """Launch the live slider tuner on the current run (own process)."""
        if not self.rundir:
            messagebox.showinfo("Tune", "Pick a run first")
            return
        import subprocess
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'sldea_tuner.py')
        try:
            subprocess.Popen([sys.executable, script, self.rundir],
                             start_new_session=True)
        except Exception as e:
            messagebox.showerror("Tune", f"Could not launch: {e}")

    # ---------------- advanced settings ----------------
    def _advanced(self):
        win = tk.Toplevel(self.root)
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
                'electrode_lum': "mask pixels near-saturated in either frame "
                                 "(copper electrode glints shift with "
                                 "voltage); 0 disables",
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
                'breakdown_ua': "flag breakdown above this Trek current (µA)",
                'area_jump_pct': "flag breakdown on area collapse (%) while "
                                 "voltage rises",
                'wrinkle_ratio': "wrinkle index (texture vs baseline) at/"
                                 "above this = wrinkle-mode; first such "
                                 "frame is noted as the onset",
                'norm_bg': "1 = rescale each frame's brightness to the "
                           "baseline (via the static border) before diffing "
                           "— cancels the camera's internal auto-gain drift; "
                           "0 = off"}
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

        def apply(save=False):
            try:
                for key, e in entries.items():
                    cast = type(se.DEFAULT_SETTINGS[key])
                    self.settings[key] = cast(float(e.get()))
            except ValueError as err:
                messagebox.showerror("Settings", str(err), parent=win)
                return
            if save and self.rundir:
                se.save_settings(self.rundir, self.settings)
            win.destroy()
            self.status.config(
                text="settings applied" + (" + saved to setup.txt" if save
                                           else "") + " — re-run Detect")

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
                 seed=None, seed_snapped=False):
        super().__init__(app.root)
        from PIL import Image
        self.app = app
        self.row_index = row_index
        self.mm_per_px = mm_per_px
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
                'snapped': self._snap_used}
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
