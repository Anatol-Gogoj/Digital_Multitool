#!/usr/bin/env python3
"""SLDEA video review: walk the recorded frames that need a human.

A run's video is hundreds to thousands of frames, and nobody reviews them
one by one. sldea_video.review_flags sends to a human only the frames the
detector doubts, or that disagree with the run's ACCEPTED stills (the
stills are frames of the same stream, so each one is a checkpoint: a known
area at a known time). This window shows those frames, one at a time, on
the area-against-time figure and as the picture with the detector's
outline, and records accept / reject decisions in video_review.csv.

Decisions never touch data.csv or video_edges.csv: the stills keep their
own review in Edge Review, and a re-run of the video pass (Edge Review's
Save starts one when the edges are stale) never overwrites a decision; a
decision about an area the detector no longer reports is dropped and
counted on the next open (sldea_video.read_decisions).

Keys: Left / Right step one frame; N / P (or Down / Up) the next /
previous flagged frame nobody has decided; A accept, R reject, C clear;
Shift+A / Shift+R decide the whole stretch of consecutive flagged frames
around the current one; Esc closes. A click on the figure jumps to the
nearest frame.

Usage:
    python sldea_video_review.py RUN

Opened from Edge Review's "Video review" button (in Edge Review's own
process), and as this program from the SLDEA tab's button and the plot
window's run menu (#395). Headless tests:
.venv/bin/python tests/test_sldea_video_review.py
"""
import datetime
import getpass
import os
import queue
import sys
import threading
import tk_fontfix                      # must precede tkinter:
tk_fontfix.apply()                     # colour emoji crash Tk
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np

import sldea_video as sv


def _user():
    try:
        return getpass.getuser()
    except Exception:
        return ''


def _fmt_t(t):
    if t is None:
        return '—'
    m, s = divmod(int(round(t)), 60)
    return f"{m}:{s:02d}"


class _OutlineJobs:
    """The outline worker's whole state, and NOTHING of Tk's.

    The worker thread runs a bound method of this object, so this object
    is what the thread keeps alive. Were it the window, the last reference
    to a Tk-holding object could be dropped on the worker thread, and Tk
    aborts the process when that happens (Tcl_AsyncDelete, the defect
    test_sldea_edge_gui's _reap documents). One detection at a time: the
    detector's caches are module-level. A request already superseded by
    the time the lock frees is not computed at all."""

    def __init__(self, se, base, settings):
        self.se, self.base, self.settings = se, base, settings
        self.gen = 0
        self.closed = False
        self.q = queue.Queue()
        self.lock = threading.Lock()

    def next_gen(self):
        self.gen += 1
        return self.gen

    def run(self, gen, img, prev):
        with self.lock:
            if gen != self.gen or self.closed:
                return
            try:
                cands = self.se.candidates(self.base, img, self.settings,
                                           prev_method=prev)
            except Exception as e:
                self.q.put((gen, None, None, f"detection failed: {e}"))
                return
            if not cands:
                self.q.put((gen, None, None, None))
                return
            best = cands[0]
            ct = best.get('contour')
            self.q.put((gen, None if ct is None else np.asarray(ct),
                        float(best['area_px']), None))


class VideoReviewWindow:
    """The review window. `master` is the Tk root (or any widget) it opens
    over; with `standalone` the master itself is the window (the CLI).

    All state a test needs is on the instance: `edges`, `flags`,
    `decisions`, `cur` (index into edges), `stale`, `dropped`."""

    CV_W, CV_H = 720, 480          # the frame view, fixed so nothing moves
    FIG_W_IN, FIG_H_IN = 9.0, 2.5
    OUTLINE_POLL_MS = 40

    def __init__(self, master, rundir, standalone=False, on_close=None):
        import sldea_edge as se
        self.se = se
        self.rundir = rundir
        self.on_close = on_close
        self.win = master if standalone else tk.Toplevel(master)
        self.win.title(f"Video review — {os.path.basename(rundir)}")
        self._cap = None
        self._photo = None
        self._closed = False
        self._img = None
        self.cur = 0
        self._changed = False         # a decision was made this session
        self._poll_job = None
        self.outline = None           # (gen, contour or None, area or None)
        self._load()
        self._build()
        first = self._next_flagged(-1, +1)
        self.show(first if first is not None else 0)

    # ------------------------------------------------------------- data
    def _load(self):
        se = self.se
        self.run = se.load_run(self.rundir)
        self.settings = se.load_settings(self.rundir)
        self.edges = sv.read_edges(self.rundir)
        try:
            self.checkpoints = sv.still_checkpoints(self.rundir, run=self.run)
        except Exception:
            self.checkpoints = []
        self.offset = sv.still_offset(self.edges, self.checkpoints)
        self.flags = sv.review_flags(self.edges, self.checkpoints,
                                     offset=self.offset)
        self.decisions, self.dropped = sv.read_decisions(self.rundir,
                                                         self.edges)
        try:
            self.stale = sv.edges_stale(self.rundir)
        except Exception as e:
            self.stale = f"their inputs could not be checked ({e})"
        self.stamp = sv.read_stamp(self.rundir) or {}
        self.scale = self.stamp.get('mm_per_px')
        base_row = next((r for r in self.run['rows']
                         if r.get('tag') == 'baseline'
                         and (r.get('frame_file') or '').strip()), None)
        self.base = (sv.video_gray(se.frame_path(self.run, base_row))
                     if base_row is not None else None)
        self.ref = (se.baseline_disc(self.base, self.settings)
                    if self.base is not None else None)
        if self.ref is None:
            a = se.load_scale_anchor(self.rundir) or {}
            disc = se.anchor_disc(
                dict(a, cx=a.get('disc_cx_px'), cy=a.get('disc_cy_px'),
                     is_baseline=a.get('anchor_is_baseline')),
                None if self.base is None else self.base.shape)
            self.ref = disc
        base_ck = next((c for c in self.checkpoints
                        if c['tag'] == 'baseline'), None)
        # A0 in the VIDEO's terms: the stills' A0 times the run-wide
        # video/still offset, so "% vs A0" on a 0 kV frame reads about
        # zero rather than the decode offset (-1.0 % on 13_backlight_2)
        self.a0 = (base_ck['area_px'] * (self.offset or 1.0) if base_ck
                   else (self.ref['area_px'] if self.ref else None))
        self.jobs = _OutlineJobs(se, self.base, self.settings)

    def flagged_count(self):
        return sum(1 for f in self.flags if f['reasons'])

    def undecided_flagged(self):
        return sum(1 for f in self.flags
                   if f['reasons'] and f['frame'] not in self.decisions)

    # ------------------------------------------------------------ layout
    def _build(self):
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
        w = self.win
        wrap = int(self.CV_W * 1.25)
        top = ttk.Frame(w, padding=(8, 6, 8, 2))
        top.pack(fill='x')
        lines = []
        if self.stale:
            lines.append(f"⚠ These video edges are out of date: {self.stale}."
                         f" Edge Review's Save re-runs them; or press "
                         f"Re-run.")
        else:
            lines.append("Video edges are current: measured with this run's "
                         "settings, baseline fit and scale anchor.")
        if self.dropped:
            lines.append(f"{self.dropped} earlier decision(s) were about "
                         f"areas the detector no longer reports, and were "
                         f"dropped.")
        if self.offset:
            pct = 100.0 * (self.offset - 1.0)
            line = (f"The video reads {pct:+.2f} % against the accepted "
                    f"stills overall; the bands allow for it.")
            if abs(pct) > sv.REVIEW_BAND_PCT:
                line = (f"⚠ The video and the accepted stills disagree "
                        f"by {pct:+.2f} % overall, more than the "
                        f"{sv.REVIEW_BAND_PCT:g} % band: check the scale "
                        f"anchor and the baseline before trusting either.")
            lines.append(line)
        if not self.checkpoints:
            lines.append("No accepted stills in data.csv yet: frames are "
                         "flagged on the detector's own doubt and on jumps "
                         "only. Review and Save the stills in Edge Review "
                         "first.")
        self.head = tk.Label(top, anchor='w', justify='left',
                             wraplength=wrap,
                             text="\n".join(lines))
        self.head.pack(side='left', fill='x', expand=True)
        self.rerun_btn = ttk.Button(top, text="↻ Re-run video edges",
                                    command=self.rerun)
        self.rerun_btn.pack(side='right')
        if not (self.stale and sv.has_video(self.rundir)):
            self.rerun_btn.config(state='disabled')

        self.fig = Figure(figsize=(self.FIG_W_IN, self.FIG_H_IN), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.fig_canvas = FigureCanvasTkAgg(self.fig, master=w)
        self.fig_canvas.get_tk_widget().pack(fill='x', padx=8)
        self.fig_canvas.mpl_connect('button_press_event', self._on_fig_click)
        self._cursor_line = None
        self._draw_figure()

        self.cv = tk.Canvas(w, width=self.CV_W, height=self.CV_H, bg='#111',
                            highlightthickness=0)
        self.cv.pack(padx=8, pady=(6, 2))
        tk.Label(w, anchor='w', fg='#555555', wraplength=wrap,
                 text="Solid blue: the detector's outline on this frame. "
                      "Dashed grey: the resting disc. Display "
                      "contrast-stretched.").pack(fill='x', padx=8)
        self.stat1 = tk.Label(w, anchor='w', justify='left', wraplength=wrap,
                              font=('TkDefaultFont', 10, 'bold'))
        self.stat1.pack(fill='x', padx=8, pady=(4, 0))
        self.stat2 = tk.Label(w, anchor='w', justify='left', wraplength=wrap)
        self.stat2.pack(fill='x', padx=8)

        bar = ttk.Frame(w, padding=(8, 4, 8, 8))
        bar.pack(fill='x')
        for text, cmd in (("⏮ Prev flagged (P)", lambda: self.step_flagged(-1)),
                          ("◀ Prev (←)", lambda: self.step(-1)),
                          ("Next (→) ▶", lambda: self.step(+1)),
                          ("Next flagged (N) ⏭", lambda: self.step_flagged(+1))):
            ttk.Button(bar, text=text, command=cmd).pack(side='left',
                                                          padx=(0, 4))
        for text, cmd in (("Close (Esc)", self.close),
                          ("Clear (C)", lambda: self.decide(None)),
                          ("✘ Reject (R)", lambda: self.decide('reject')),
                          ("✔ Accept (A)", lambda: self.decide('accept'))):
            ttk.Button(bar, text=text, command=cmd).pack(side='right',
                                                          padx=(4, 0))
        bar2 = ttk.Frame(w, padding=(8, 0, 8, 8))
        bar2.pack(fill='x')
        ttk.Button(bar2, text="✔ Accept stretch (Shift+A)",
                   command=lambda: self.decide_stretch('accept')).pack(
            side='right', padx=(4, 0))
        ttk.Button(bar2, text="✘ Reject stretch (Shift+R)",
                   command=lambda: self.decide_stretch('reject')).pack(
            side='right', padx=(4, 0))
        self.count_lbl = ttk.Label(bar2, text="")
        self.count_lbl.pack(side='left')

        for seq, fn in (('<Left>', lambda e: self.step(-1)),
                        ('<Right>', lambda e: self.step(+1)),
                        ('<Up>', lambda e: self.step_flagged(-1)),
                        ('<Down>', lambda e: self.step_flagged(+1)),
                        ('<KeyPress-p>', lambda e: self.step_flagged(-1)),
                        ('<KeyPress-n>', lambda e: self.step_flagged(+1)),
                        ('<KeyPress-a>', lambda e: self.decide('accept')),
                        ('<KeyPress-r>', lambda e: self.decide('reject')),
                        ('<KeyPress-c>', lambda e: self.decide(None)),
                        ('<KeyPress-A>',
                         lambda e: self.decide_stretch('accept')),
                        ('<KeyPress-R>',
                         lambda e: self.decide_stretch('reject')),
                        ('<Escape>', lambda e: self.close())):
            w.bind(seq, fn)
        w.protocol('WM_DELETE_WINDOW', self.close)

    def _draw_figure(self):
        ax = self.ax
        ax.clear()
        for extra in list(self.fig.axes):
            if extra is not ax:
                self.fig.delaxes(extra)
        k = (self.scale * self.scale) if self.scale else 1.0
        ko = k * (self.offset or 1.0)
        for t0, t1, lo, hi, _cs in sv.landing_bands(self.checkpoints):
            ax.fill_between([t0 / 60.0, t1 / 60.0], lo * ko, hi * ko,
                            color=sv.TOL_GREY, alpha=0.35, linewidth=0,
                            zorder=1)
        sv.draw_series(ax, sv.plot_series(self.edges, self.flags,
                                          self.checkpoints, self.decisions),
                       self.scale)
        if ax.get_legend_handles_labels()[0]:
            ax.legend(loc='upper left', fontsize=7, ncol=3)
        self._cursor_line = ax.axvline(0, color=sv.TOL_PURPLE,
                                       linestyle='--', linewidth=1.0)
        self.fig.tight_layout()
        self.fig_canvas.draw_idle()

    # --------------------------------------------------------- navigation
    def _row(self, i):
        return self.edges[i] if 0 <= i < len(self.edges) else None

    def _next_flagged(self, i, d):
        j = i + d
        while 0 <= j < len(self.flags):
            f = self.flags[j]
            if f['reasons'] and f['frame'] not in self.decisions:
                return j
            j += d
        return None

    def step(self, d):
        if self.edges:
            self.show(min(len(self.edges) - 1, max(0, self.cur + d)))

    def step_flagged(self, d):
        j = self._next_flagged(self.cur, d)
        if j is None:
            self.stat2.config(text=("No undecided flagged frame "
                                    + ("after" if d > 0 else "before")
                                    + " this one."))
            return
        self.show(j)

    def _on_fig_click(self, event):
        if event.xdata is None or not self.edges:
            return
        t = event.xdata * 60.0
        best = min(range(len(self.edges)),
                   key=lambda i: abs((self.edges[i]['t_s'] or -1e9) - t))
        self.show(best)

    def show(self, i):
        """Make edges[i] the current frame: picture, figure cursor, status,
        and an outline request to the worker."""
        self.cur = i
        row = self._row(i)
        if row is None:
            self.stat1.config(text="video_edges.csv has no rows: run the "
                                   "video pass first (Re-run).")
            return
        if self._cursor_line is not None and row['t_s'] is not None:
            self._cursor_line.set_xdata([row['t_s'] / 60.0] * 2)
            self.fig_canvas.draw_idle()
        img = self._read(row['frame'])
        self._img = img
        self.outline = None
        self._paint()
        self._status()
        if img is not None and self.base is not None \
                and img.shape == self.base.shape:
            self._request_outline(i, img)

    def _read(self, frame):
        import cv2
        if self._cap is None:
            path = os.path.join(self.rundir, sv.VIDEO_FILENAME)
            if not os.path.exists(path):
                return None
            self._cap = cv2.VideoCapture(path)
        return sv.read_frame(self._cap, frame)

    # ----------------------------------------------------------- picture
    def _view_box(self, shape):
        """(x0, y0, x1, y1) of the frame region shown: a square around the
        resting disc wide enough for the tracker's search (RAY_WIN_HI),
        or the whole frame when there is no disc to centre on."""
        h, w = shape[:2]
        if not self.ref:
            return 0, 0, w, h
        r = 0.5 * float(self.ref['diam_px'])
        half = max(r * (self.se.RAY_WIN_HI + 0.05), 32.0)
        cx, cy = float(self.ref['cx']), float(self.ref['cy'])
        x0, x1 = int(max(0, cx - half)), int(min(w, cx + half))
        y0, y1 = int(max(0, cy - half)), int(min(h, cy + half))
        return x0, y0, x1, y1

    def _paint(self):
        from PIL import Image, ImageTk
        self.cv.delete('all')
        img = self._img
        if img is None:
            self.cv.create_text(self.CV_W // 2, self.CV_H // 2, fill='white',
                                text="this frame does not read from "
                                     "video.mkv")
            return
        x0, y0, x1, y1 = self._view_box(img.shape)
        crop = img[y0:y1, x0:x1].astype(np.float32)
        lo, hi = np.percentile(crop, (1, 99))
        crop = np.clip((crop - lo) / max(hi - lo, 1.0) * 255.0, 0, 255)
        s = min(self.CV_W / float(x1 - x0), self.CV_H / float(y1 - y0))
        dw, dh = max(1, int((x1 - x0) * s)), max(1, int((y1 - y0) * s))
        pil = Image.fromarray(crop.astype(np.uint8)).resize(
            (dw, dh), Image.BILINEAR)
        self._photo = ImageTk.PhotoImage(pil)
        ox, oy = (self.CV_W - dw) // 2, (self.CV_H - dh) // 2
        self.cv.create_image(ox, oy, anchor='nw', image=self._photo)
        self._xf = (x0, y0, s, ox, oy)
        if self.ref:
            r = 0.5 * float(self.ref['diam_px'])
            cx, cy = self._to_view(float(self.ref['cx']),
                                   float(self.ref['cy']))
            self.cv.create_oval(cx - r * s, cy - r * s, cx + r * s,
                                cy + r * s, outline=sv.TOL_GREY, width=2,
                                dash=(6, 4))
        if self.outline is not None and self.outline[1] is not None:
            pts = []
            for x, y in self.outline[1]:
                pts.extend(self._to_view(float(x), float(y)))
            if len(pts) >= 6:
                self.cv.create_polygon(pts, outline=sv.TOL_BLUE, fill='',
                                       width=2)

    def _to_view(self, x, y):
        x0, y0, s, ox, oy = self._xf
        return ox + (x - x0) * s, oy + (y - y0) * s

    # ------------------------------------------------------------ outline
    def _prev_method(self, i):
        """The winning method of the frame detect_video measured just
        before this one, so the re-detection gets the same hysteresis
        bonus the pass gave it, and with it the same outline."""
        for j in range(i - 1, -1, -1):
            m = self.edges[j]['method']
            if self.edges[j]['area_px'] is not None and m:
                return m
        return None

    def _request_outline(self, i, img):
        gen = self.jobs.next_gen()
        threading.Thread(target=self.jobs.run,
                         args=(gen, img.astype(np.float32),
                               self._prev_method(i)),
                         daemon=True).start()
        if self._poll_job is None:
            self._poll_job = self.win.after(self.OUTLINE_POLL_MS,
                                            self._poll_outline)

    def _poll_outline(self):
        self._poll_job = None
        if self._closed:
            return
        while True:
            try:
                got = self.jobs.q.get_nowait()
            except queue.Empty:
                break
            if got[0] == self.jobs.gen:
                self.outline = got
        if self.outline is not None and self.outline[0] == self.jobs.gen:
            self._paint()
            self._status()
        else:
            self._poll_job = self.win.after(self.OUTLINE_POLL_MS,
                                            self._poll_outline)

    def wait_outline(self, timeout=30.0):
        """Pump events until the current frame's outline is in (tests)."""
        import time
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.win.update()
            out = self.outline
            if out is not None and out[0] == self.jobs.gen:
                return True
            time.sleep(0.02)
        return False

    # -------------------------------------------------------------- status
    def _status(self):
        row = self._row(self.cur)
        f = self.flags[self.cur]
        k = (self.scale * self.scale) if self.scale else None
        if row['area_px'] is None:
            area = "no area"
        else:
            area = f"area {row['area_px']:,.0f} px"
            if k:
                area += f" ({row['area_px'] * k:.2f} mm²)"
            if self.a0:
                area += f", {100.0 * (row['area_px'] / self.a0 - 1):+.2f} % vs A0"
        kv = row['nominal_kV']
        self.stat1.config(
            text=f"frame {row['frame']} of {len(self.edges)}   "
                 f"t {_fmt_t(row['t_s'])}   "
                 f"{'—' if kv is None else f'{kv:g}'} kV   {area}   "
                 f"{row['method'] or '—'}"
                 + (f" conf {row['conf']:.2f}" if row['conf'] is not None
                    else ""))
        parts = []
        if f['reasons']:
            why = ", ".join(f['reasons'])
            if f['band'] and 'off-stills' in f['reasons']:
                why += (f" (accepted stills of this landing allow "
                        f"{f['band'][0]:,.0f}–{f['band'][1]:,.0f} px)")
            parts.append(f"FLAGGED: {why}")
        else:
            parts.append("not flagged")
        d = self.decisions.get(row['frame'])
        parts.append(f"decision: {d['decision']}" if d else "decision: none")
        if self.outline is not None and self.outline[0] == self.jobs.gen:
            _g, _ct, a, err = self.outline
            if err:
                parts.append(err)
            elif a is not None and row['area_px'] is not None and \
                    abs(a / row['area_px'] - 1.0) > 0.005:
                parts.append(f"the outline drawn re-detects {a:,.0f} px, "
                             f"not the file's {row['area_px']:,.0f}: the "
                             f"edges may be out of date")
        elif self._img is not None:
            parts.append("outline: detecting…")
        self.stat2.config(text="   ·   ".join(parts))
        self.count_lbl.config(
            text=f"flagged {self.flagged_count()} · decided "
                 f"{sum(1 for f2 in self.flags if f2['reasons'] and f2['frame'] in self.decisions)}"
                 f" · left {self.undecided_flagged()}")

    # ----------------------------------------------------------- decisions
    def _record(self, i, decision):
        row = self._row(i)
        frame = row['frame']
        if decision is None:
            self.decisions.pop(frame, None)
        else:
            self.decisions[frame] = {
                'frame': frame, 't_s': row['t_s'], 'decision': decision,
                'area_px': row['area_px'],
                'reasons': ";".join(self.flags[i]['reasons']),
                'user': _user(),
                'when': datetime.datetime.now().isoformat(
                    timespec='seconds')}

    def _commit(self):
        sv.write_decisions(self.rundir, self.decisions)
        self._changed = True
        self._draw_figure()
        if self.edges and self._row(self.cur)['t_s'] is not None:
            self._cursor_line.set_xdata(
                [self._row(self.cur)['t_s'] / 60.0] * 2)
        self._status()

    def decide(self, decision):
        """Accept / reject (or clear, None) the current frame, then move to
        the next undecided flagged frame when there is one."""
        if not self.edges:
            return
        self._record(self.cur, decision)
        self._commit()
        if decision is not None:
            j = self._next_flagged(self.cur, +1)
            if j is not None:
                self.show(j)

    def stretch(self, i):
        """Indices of the run of consecutive flagged frames containing i
        (empty when i itself is not flagged)."""
        if not (0 <= i < len(self.flags)) or not self.flags[i]['reasons']:
            return []
        lo = i
        while lo > 0 and self.flags[lo - 1]['reasons']:
            lo -= 1
        hi = i
        while hi < len(self.flags) - 1 and self.flags[hi + 1]['reasons']:
            hi += 1
        return list(range(lo, hi + 1))

    def decide_stretch(self, decision):
        idx = self.stretch(self.cur)
        if not idx:
            self.stat2.config(text="This frame is not flagged, so there is "
                                   "no flagged stretch around it to decide.")
            return
        for i in idx:
            self._record(i, decision)
        self._commit()
        j = self._next_flagged(idx[-1], +1)
        self.show(j if j is not None else idx[-1])

    # ---------------------------------------------------------- re-run/close
    def rerun(self):
        try:
            sv.launch_rerun(self.rundir)
        except Exception as e:
            self.head.config(text=f"The re-run could not start ({e}).")
            return
        self.rerun_btn.config(state='disabled')
        self.head.config(text="Re-running the video pass in the background "
                              "(progress in this run's run.log). Close and "
                              "reopen this window when it has finished.")

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.jobs.closed = True
        if self._poll_job is not None:
            try:
                self.win.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        # matplotlib's Tk canvas queues its redraw with after_idle; left
        # pending it fires into the destroyed window (Edge Review's
        # _cancel_pending documents the same defect for its own jobs).
        # Only this window's jobs are cancelled: the master's are not ours.
        idle = getattr(self.fig_canvas, '_idle_draw_id', None)
        if idle:
            try:
                self.fig_canvas.get_tk_widget().after_cancel(idle)
            except Exception:
                pass
            self.fig_canvas._idle_draw_id = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        if self._changed and self.edges:
            # the PNG beside the CSV says what the review decided, so a
            # reader of the run folder sees it without opening this window
            try:
                sv.plot_edges(self.rundir, self.edges, self.scale,
                              self.stamp.get('scale_source', ''),
                              flags=self.flags,
                              checkpoints=self.checkpoints,
                              decisions=self.decisions)
            except Exception as e:
                print(f"video review: figure not redrawn ({e})")
        try:
            self.fig.clear()
        except Exception:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self.on_close is not None:
            self.on_close(self)


def _tell(text, root=None, error=True):
    """Say `text` on the console and in a box over `root` (withdrawn), or
    over a root of its own when none is given. Never raises.

    The SLDEA tab and the plot window start this program as a process of
    its own (#395), with no console that anyone reads, so what it has to
    say goes on screen as well, as Edge Review says it for the window it
    opens in its own process. With no display only the console line is
    left, which is what the command line had before."""
    try:
        print(text)
    except Exception:               # a console that cannot encode it
        pass
    own = root is None
    try:
        if own:
            root = tk.Tk()
        root.withdraw()
        show = messagebox.showerror if error else messagebox.showinfo
        show("Video review", text, parent=root)
    except Exception:
        pass
    finally:
        if own and root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def open_standalone(root, rundir):
    """The window as its own program, on the Tk root `root`. -> the
    window, or None once a box has said why it could not open and `root`
    is destroyed."""
    try:
        return VideoReviewWindow(root, rundir, standalone=True)
    except Exception as e:
        _tell(f"The video review of {os.path.basename(rundir)} could not "
              f"open:\n\n{e}", root)
        try:
            root.destroy()
        except Exception:
            pass
        return None


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__.split('Usage:')[1].split('Opened from')[0].rstrip())
        return 0 if argv else 2
    import sldea_edge as se
    rundir = se.resolve_run(argv[0]) or argv[0]
    # A run whose recording is in its folder opens before its video edges
    # exist (#395). That is every video run for a while after it ends,
    # and every run recorded without "edges after": the window itself
    # says there are no edges yet and offers Re-run. Only a folder with no
    # video at all is refused, here, before any window, and in words: the
    # SLDEA tab starts this program without looking in the folder itself.
    if not (sv.has_video(rundir) or os.path.exists(
            os.path.join(rundir, sv.VIDEO_EDGES_FILENAME))):
        _tell(f"There is no video of {os.path.basename(rundir)} to review "
              f"yet: neither {sv.VIDEO_FILENAME} with "
              f"{sv.VIDEO_INDEX_FILENAME} nor {sv.VIDEO_EDGES_FILENAME} is "
              f"in\n{rundir}\nor that folder cannot be reached.\n\n"
              f"When a run records video, a separate program moves the "
              f"recording into its run folder after the run, after edge "
              f"detection on every frame when that was ticked. Its "
              f"progress, or the reason it stopped, is in run.log in that "
              f"folder.", error=False)
        return 2
    root = tk.Tk()
    if open_standalone(root, rundir) is None:
        return 1
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
