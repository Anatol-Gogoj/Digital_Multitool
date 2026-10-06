#!/usr/bin/env python3
"""SLDEA live view (#376): what the camera sees during a run, without
ever opening the camera.

During a run the Webcam tab's preview is refused on purpose
(gui._cam_owned_by_sldea): a preview once took the device the run's stills
needed. Until this window the last picture an operator saw was the
pre-flight snapshot, and run 13_backlight (2026-10-05) shot all 60 frames
57 to 66 % saturated with nothing on screen to say so. This window shows
frames the run ALREADY holds in memory:

* a video run: the recorder's newest stream frame, through
  VideoRecorder.latest_rgb() (a lock held for one reference read, and a
  copy made outside it). (None, None) from it is shown as
  "NO FRAME (stream stalled)", the dead-camera signal #48 asks for;
* a stills-only run: the newest still, which the run thread hands over in
  ONE attribute, app._sldea_live_still, as a LiveStill. That is a plain
  reference swap: no copy, no lock the view could hold, no Tk call. The
  view reads it on the Tk thread and labels it a still with its age, so
  it is never read as live.

It is called "live view" in code because "preview" already means the
run-plan staircase on the SLDEA tab (sldea_preview).

HV-safety rules this module keeps (the run thread runs the watchdog and
the ramp):

* The run thread never calls anything here and never waits on it. Its
  only contact is the attribute swap above, and that never depends on
  whether this window is open, closed or destroyed.
* Everything here runs on the Tk thread, from a Tk `after` loop at about
  2 Hz that only reads. It never opens, grabs from or re-stamps the
  camera: in a stills-only run a stream would contend for the device
  exactly as the refused Webcam preview did.
* A frame from the run is never written to: the view works on its own
  thumbnail, and the full-size frame is dropped at the end of each tick.
* A new run forgets the previous one before that run's worker exists
  (begin_run), and a recorder left over from an earlier run is never
  taken for this run's (they are told apart by identity), so nothing
  from an earlier run is ever shown as current.
* After the run the window keeps its last frame, labelled RUN ENDED with
  the clock time it was taken, and says nothing about the HV state: the
  Run log is the record of how the run ended.

Colours are Paul Tol's bright scheme (the values sldea_edge_gui's
HEALTH_COLORS uses, black text on each), and every state is also spelled
out in words, so nothing depends on colour alone.
"""
import collections
import time
import weakref
from datetime import datetime

# The Tk loop's period: about 2 Hz, as the issue asks. Each tick copies
# at most one stream frame (latest_rgb) and shrinks it to THUMB_W.
PERIOD_MS = 500
THUMB_W = 480
# The shape shown before any frame (16:9, the bench camera's 1920x1080).
BLANK_SIZE = (THUMB_W, 270)
# Exposure statistics are taken on every n-th pixel, n chosen so the
# sample is at most this wide: a 1080p frame is read as 480x270 instead
# of copying 6 MB into floats twice a second. Strided sampling keeps
# pixel values as they are (no averaging), so the saturated share is an
# unbiased estimate of the whole frame's.
STATS_MAX_W = 480

# Paul Tol bright, the same four sldea_edge_gui.HEALTH_COLORS uses (black
# text on each of them clears 4.5:1 there), plus Tol's grey.
TOL_GREEN = '#228833'
TOL_YELLOW = '#CCBB44'
TOL_RED = '#EE6677'
TOL_CYAN = '#66CCEE'
TOL_GREY = '#BBBBBB'

# What each display state is called on the picture (banner) and its
# colour. The words carry the meaning; the colour only repeats it. LIVE
# is Tol cyan (information), not green: next to high voltage, green reads
# as "all is well", and a live picture says nothing of the sort.
BANNERS = {
    'idle': ("NO RUN YET", TOL_GREY),
    'waiting': ("WAITING FOR THE FIRST FRAME", TOL_GREY),
    'live': ("LIVE (video stream)", TOL_CYAN),
    'still': ("LAST STILL, NOT LIVE", TOL_YELLOW),
    'stalled': ("NO FRAME (stream stalled)", TOL_RED),
    'closed': ("NO FRAME (stream closed)", TOL_RED),
    'ended': ("RUN ENDED, NOT LIVE", TOL_GREY),
    'error': ("LIVE VIEW ERROR, NOT LIVE", TOL_RED),
}

# exposure_verdict's levels, in words and in colour
LEVEL_WORDS = {'ok': 'OK', 'dark': 'DARK', 'bright': 'BRIGHT',
               'clipped': 'CLIPPED', 'flat': 'FLAT (no picture)'}
LEVEL_COLORS = {'ok': TOL_GREEN, 'dark': TOL_YELLOW, 'bright': TOL_YELLOW,
                'clipped': TOL_RED, 'flat': TOL_RED}

NOTE = ("Read-only: this window shows frames the run already holds and "
        "never opens the camera. Closing it does not affect the run. "
        "Abort is on the SLDEA tab.")

# One still, as the run thread hands it over (gui._sldea_capture):
#   frame  the RGB frame about to be saved (the run's own array: the view
#          only reads it)
#   step, kv, tag   the snapshot's step, nominal kV and tag
#   t_run  run time when it was handed over (None without a run clock)
#   mono   time.monotonic() then: the view's age clock, and its key for
#          "is this a new still"
#   wall   time.time() then, for the clock time shown
# The hand-over happens just before the save, after the capture's scope
# reads, so the shown age can understate the grab's by those reads (two
# scope round trips; zero without a scope).
LiveStill = collections.namedtuple(
    'LiveStill', 'frame step kv tag t_run mono wall')


# ---------------------------------------------------------------------------
# small pure helpers (no Tk)
# ---------------------------------------------------------------------------

def fmt_age(seconds):
    """'0.3 s', '8 s', '2 min 05 s', '1 h 03 min'. None -> 'unknown'."""
    if seconds is None:
        return 'unknown'
    s = max(0.0, float(seconds))
    if s < 10:
        return f"{s:.1f} s"
    if s < 60:
        return f"{s:.0f} s"
    n = int(round(s))
    if n < 3600:
        return f"{n // 60} min {n % 60:02d} s"
    return f"{n // 3600} h {(n % 3600) // 60:02d} min"


def fmt_clock(wall):
    """Wall-clock time as HH:MM:SS, or '?' when it is not known."""
    try:
        return datetime.fromtimestamp(float(wall)).strftime('%H:%M:%S')
    except (TypeError, ValueError, OverflowError, OSError):
        return '?'


def fmt_run_time(seconds):
    """Run time as H:MM:SS, the SLDEA tab's own format (fmt_duration)."""
    import sldea_profile
    return sldea_profile.fmt_duration(max(0.0, float(seconds)))


def thumbnail(frame, width=THUMB_W):
    """A NEW RGB uint8 array `width` wide with the frame's aspect ratio.
    The input is only read, never written."""
    import numpy as np
    arr = np.asarray(frame)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=2)
    elif arr.ndim == 3 and arr.shape[2] > 3:
        arr = arr[:, :, :3]
    h, w = arr.shape[:2]
    if h < 1 or w < 1:
        raise ValueError("empty frame")
    th = max(1, int(round(h * float(width) / w)))
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    try:
        import cv2
        out = cv2.resize(np.ascontiguousarray(arr), (int(width), th),
                         interpolation=cv2.INTER_AREA)
    except ImportError:
        from PIL import Image
        out = np.asarray(Image.fromarray(np.ascontiguousarray(arr))
                         .resize((int(width), th)))
    # always a fresh array the caller owns, whatever the path above did
    return np.array(out, dtype=np.uint8, copy=True)


def exposure_readout(frame, max_w=STATS_MAX_W):
    """The pre-flight's exposure statistics for one frame -> dict.

    Same definitions as sldea_profile.preflight_report: gray is the mean
    of the colour channels, 'saturated' is gray >= 250, the verdict is
    sldea_profile.exposure_verdict with sldea_edge.image_content's flat
    check. Taken on a strided sample (STATS_MAX_W), so on a frame wider
    than that the numbers are estimates of the full frame's.

      mean, sat_pct   the numbers
      contrast        image_content's p95 - p5, or None if not checked
      level           'ok' | 'dark' | 'bright' | 'clipped' | 'flat'
    """
    import numpy as np
    import sldea_profile
    arr = np.asarray(frame)
    step = max(1, int(arr.shape[1]) // int(max_w)) if arr.ndim >= 2 else 1
    sub = arr[::step, ::step]
    gray = (sub.mean(axis=2) if sub.ndim == 3
            else sub.astype(np.float64))
    mean = float(gray.mean())
    sat = float((gray >= 250).mean() * 100)
    content = None
    try:
        import sldea_edge
        content = sldea_edge.image_content(gray)
    except Exception:
        content = None
    level, _hint = sldea_profile.exposure_verdict(mean, sat, content)
    return {'mean': mean, 'sat_pct': sat,
            'contrast': (None if not content
                         else float(content.get('contrast', 0.0))),
            'level': level}


def exposure_words(readout):
    """-> (the numbers in words, the level word, its colour); all empty
    when there is no frame to judge."""
    if not readout:
        return "", "", None
    ctxt = ("" if readout.get('contrast') is None
            else f", contrast {readout['contrast']:.0f} gray levels")
    level = readout.get('level', '')
    return (f"Exposure of the frame shown: mean {readout['mean']:.0f}, "
            f"saturated {readout['sat_pct']:.1f} %{ctxt}",
            LEVEL_WORDS.get(level, str(level).upper()),
            LEVEL_COLORS.get(level))


def _font(size):
    """PIL's built-in font at `size` where this Pillow can scale it."""
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                     # Pillow < 10.1: one fixed size
        return ImageFont.load_default()


def _text_w(draw, text, font):
    try:
        x0, _y0, x1, _y1 = draw.textbbox((0, 0), text, font=font)
        return x1 - x0
    except Exception:
        return 7 * len(text)


def render(thumb, kind, size=None):
    """The picture for one display state -> a PIL image.

    `thumb` is the view's own thumbnail (or None for a black field of
    `size`); it is copied, never drawn on. With a picture, the pre-flight
    reticle is drawn on it (same geometry as gui._sldea_preflight: a
    crosshair through the centre and a circle of 0.32 x the height), in
    Tol cyan over a black under-stroke so it shows on light and dark
    backgrounds. Every state gets a banner naming it; the NO FRAME states
    also get the words large in the middle, on black."""
    import numpy as np
    from PIL import Image, ImageDraw
    banner, color = BANNERS.get(kind, (str(kind).upper(), TOL_GREY))
    if thumb is not None and kind not in ('stalled', 'closed', 'error'):
        img = Image.fromarray(np.array(thumb, dtype=np.uint8, copy=True))
    else:
        w, h = size or BLANK_SIZE
        img = Image.new('RGB', (int(w), int(h)), (0, 0, 0))
    dr = ImageDraw.Draw(img)
    w, h = img.width, img.height
    if thumb is not None and kind not in ('stalled', 'closed', 'error'):
        cx, cy = w / 2.0, h / 2.0
        r = h * 0.32
        for fill, lw, cw in (('#000000', 3, 4), (TOL_CYAN, 1, 2)):
            dr.line([(cx, 0), (cx, h)], fill=fill, width=lw)
            dr.line([(0, cy), (w, cy)], fill=fill, width=lw)
            dr.ellipse([cx - r, cy - r, cx + r, cy + r], outline=fill,
                       width=cw)
    if kind in ('stalled', 'closed', 'waiting', 'idle', 'error'):
        big = {'stalled': ("NO FRAME", "(stream stalled)"),
               'closed': ("NO FRAME", "(stream closed)"),
               'error': ("VIEW ERROR", "nothing shown here is current"),
               'waiting': ("WAITING", "for this run's first frame"),
               'idle': ("NO RUN YET", "")}[kind]
        if thumb is None or kind in ('stalled', 'closed', 'error'):
            f1, f2 = _font(40), _font(18)
            y = h / 2.0 - 34
            dr.text(((w - _text_w(dr, big[0], f1)) / 2.0, y), big[0],
                    fill='#FFFFFF', font=f1)
            if big[1]:
                dr.text(((w - _text_w(dr, big[1], f2)) / 2.0, y + 50),
                        big[1], fill='#FFFFFF', font=f2)
    fb = _font(16)
    dr.rectangle([0, 0, w, 24], fill=color)
    dr.text((8, 3), banner, fill='#000000', font=fb)
    return img


def _ref(obj):
    """A callable returning `obj` without keeping it alive (a weakref),
    or a plain closure for an object that takes no weak reference."""
    if obj is None:
        return lambda: None
    try:
        return weakref.ref(obj)
    except TypeError:
        return lambda: obj


def notify(app, action, *args):
    """Call `action` on the app's live view, if it has one -> True when it
    ran. Never raises: the view is a convenience, and the run's start and
    end paths call this. A failure is put in the Run log, not raised."""
    view = getattr(app, '_sldea_live_view', None)
    if view is None:
        return False
    try:
        getattr(view, action)(*args)
        return True
    except Exception as e:
        try:
            app._sldea_log(f"live view: {action} failed ({e}); the run is "
                           f"not affected")
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# the window (Tk thread only)
# ---------------------------------------------------------------------------

class LiveView:
    """The detachable live-view window and its 2 Hz loop.

    `app` is the GUI (or a stand-in) and is only READ: `root`,
    `_sldea_running`, `_sldea_stop`, `_sldea_elapsed`, `_sldea_recorder`
    and `_sldea_live_still`. The one write is end_run() releasing the
    finished run's still (`_sldea_live_still = None`) after its worker has
    ended. Every method runs on the Tk thread.

    Per run: begin_run(p, dry) BEFORE the worker thread starts (state
    only, no widgets), open() after it (the window opens with the run),
    end_run() from the tab's _sldea_finished (the window keeps its last
    frame, labelled RUN ENDED). open() and close() are also the
    operator's: closing stops the loop, and a closed or never-opened
    window costs the run nothing.

    `state` is the last thing shown (a dict), for tests and for reading
    what the operator was looking at."""

    def __init__(self, app, period_ms=PERIOD_MS):
        self.app = app
        self.period_ms = int(period_ms)
        self.win = None
        self._job = None
        self._photo = None
        self._img_key = None
        self._mode = 'idle'          # 'idle' | 'running' | 'ended'
        self._p = None
        self._dry = True
        self._prev_rec = _ref(None)  # the recorder that predates this run
        self._good = None            # the last real frame shown this run
        self._still_key = None       # LiveStill.mono of the one in _good
        self._ended_wall = None
        self.state = None

    # per run

    def begin_run(self, p, dry):
        """Forget the previous run. Called on the Tk thread BEFORE this
        run's worker exists, so nothing it hands over can be cleared here
        and nothing from before can pass as its own. State only."""
        self._p, self._dry = p, bool(dry)
        self._prev_rec = _ref(getattr(self.app, '_sldea_recorder', None))
        self._good = None
        self._still_key = None
        self._ended_wall = None
        self._img_key = None
        self._mode = 'running'

    def end_run(self):
        """The run's worker has ended (gui._sldea_finished). One last look
        for the final still, then freeze: the window stays up with its
        last frame, labelled RUN ENDED, and the loop stops."""
        if self._mode == 'running':
            try:
                self._poll_still(time.monotonic())
            except Exception:
                pass
            self._finish()
        self._cancel()
        self._refresh()

    def _finish(self):
        self._mode = 'ended'
        self._ended_wall = time.time()
        self._prev_rec = _ref(None)
        # the worker is done: release the full-size still it handed over
        try:
            self.app._sldea_live_still = None
        except Exception:
            pass

    # the window

    def is_open(self):
        return self._alive()

    def open(self):
        """Show the window (create it if needed), draw now, and run the
        loop while a run is going."""
        if not self._alive():
            self._build()
        else:
            # brought back if it was minimised or behind another window;
            # stacking only, no focus is taken
            try:
                self.win.deiconify()
                self.win.lift()
            except Exception:
                pass
        self._img_key = None
        self._refresh()
        self._schedule()

    def close(self):
        """Stop the loop and destroy the window. The run goes on as it
        was; reopening shows the newest frame again."""
        self._cancel()
        win, self.win = self.win, None
        self._photo = None
        self._img_key = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

    def _alive(self):
        if self.win is None:
            return False
        try:
            return bool(self.win.winfo_exists())
        except Exception:
            return False

    def _build(self):
        import tkinter as tk
        root = self.app.root
        win = tk.Toplevel(root)
        win.title("SLDEA live view")
        win.resizable(False, False)
        # Not transient and no grab: the main window, with Abort on it,
        # comes to the front with one click on it.
        win.protocol('WM_DELETE_WINDOW', self.close)
        self.win = win
        self._img_lbl = tk.Label(win, bg='black', bd=0)
        self._img_lbl.pack(padx=8, pady=(8, 4))
        self._state_lbl = tk.Label(win, text="", anchor='w', justify='left',
                                   wraplength=THUMB_W,
                                   font=('TkDefaultFont', 9, 'bold'))
        self._state_lbl.pack(fill='x', padx=8)
        self._run_lbl = tk.Label(win, text="", anchor='w', justify='left',
                                 wraplength=THUMB_W)
        self._run_lbl.pack(fill='x', padx=8, pady=(2, 0))
        row = tk.Frame(win)
        row.pack(fill='x', padx=8, pady=(2, 0))
        self._level_lbl = tk.Label(row, text="", fg='#000000', padx=4)
        self._level_lbl.pack(side=tk.LEFT)
        self._exp_lbl = tk.Label(row, text="", anchor='w', justify='left',
                                 wraplength=THUMB_W - 90)
        self._exp_lbl.pack(side=tk.LEFT, padx=(4, 0))
        self._note_lbl = tk.Label(win, text=NOTE, anchor='w', justify='left',
                                  wraplength=THUMB_W, fg='#555555')
        self._note_lbl.pack(fill='x', padx=8, pady=(4, 8))
        self._level_bg = self._level_lbl.cget('bg')
        self._place()

    def _place(self):
        """Beside the main window when the screen has room, else at the
        screen's top right, so it does not open over the SLDEA tab's run
        controls (Run and Abort sit at the left). No event processing."""
        try:
            root = self.app.root
            sw = int(root.winfo_screenwidth())
            sh = int(root.winfo_screenheight())
            # the window's size, roughly: the picture plus four text rows
            w, h = THUMB_W + 40, 600
            x = int(root.winfo_rootx()) + int(root.winfo_width()) + 8
            if x + w > sw:
                x = max(0, sw - w - 8)
            # ...and never below the bottom of the screen (48 px for a
            # taskbar)
            y = max(0, min(int(root.winfo_rooty()), sh - h - 48))
            self.win.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # the loop

    def _schedule(self):
        if self._job is None and self._mode == 'running' and self._alive():
            try:
                self._job = self.app.root.after(self.period_ms, self._tick)
            except Exception:
                self._job = None

    def _cancel(self):
        job, self._job = self._job, None
        if job is not None:
            try:
                self.app.root.after_cancel(job)
            except Exception:
                pass

    def _tick(self):
        self._job = None
        try:
            if self._alive():
                self._refresh()
        finally:
            self._schedule()

    def _refresh(self):
        """poll() and show the answer. Anything that fails on the way
        replaces the picture with the 'error' state: a frame shown under
        a LIVE banner must never outlast the tick that could not renew
        it. Never raises."""
        try:
            st = self.poll()
            if self._alive():
                self._show(st)
            return
        except Exception as e:
            err = e
        try:
            self._show_error(err)
        except Exception:
            pass

    def _show_error(self, err):
        try:
            run = self._run_words('error')
        except Exception:
            run = ""
        st = {'kind': 'error', 'banner': BANNERS['error'][0],
              'text': (f"LIVE VIEW ERROR, not live: {err}. Nothing shown "
                       f"here is current. The run is not affected."),
              'run': run, 'exposure': ("", "", None), 'thumb': None,
              'img_key': ('error', None)}
        self.state = st
        if self._alive():
            self._show(st)

    # what to show

    def poll(self, now_mono=None, now_wall=None):
        """One look at what the run holds -> the display state (a dict,
        also kept as self.state). Reads only; never waits on the run and
        never touches the camera."""
        now_mono = time.monotonic() if now_mono is None else now_mono
        now_wall = time.time() if now_wall is None else now_wall
        app = self.app
        if self._mode == 'running' and not getattr(app, '_sldea_running',
                                                   False):
            self._finish()           # the end hook did not come: say so
        if self._mode != 'running':
            return self._state(self._mode, now_mono, now_wall)
        rec = getattr(app, '_sldea_recorder', None)
        if rec is not None and rec is self._prev_rec():
            rec = None               # an earlier run's: never this one's
        if rec is not None:
            kind = self._poll_stream(rec, now_mono, now_wall)
        else:
            kind = self._poll_still(now_mono)
        return self._state(kind, now_mono, now_wall)

    def _poll_stream(self, rec, now_mono, now_wall):
        frame, t = rec.latest_rgb()
        if frame is None:
            try:
                alive = rec.reader_alive()
            except Exception:
                alive = True
            return 'stalled' if alive else 'closed'
        age = None
        t0 = getattr(rec, 't0', None)
        if t is not None and t0 is not None:
            age = max(0.0, (now_mono - t0) - t)
        self._good = {'src': 'stream', 'thumb': thumbnail(frame),
                      'exposure': exposure_readout(frame),
                      'age_at_poll': age, 'mono': now_mono - (age or 0.0),
                      'wall': now_wall - (age or 0.0), 't_run': t,
                      'seq': now_mono}
        del frame
        return 'live'

    def _poll_still(self, now_mono):
        still = getattr(self.app, '_sldea_live_still', None)
        if still is None:
            # a still from earlier in THIS run stays: begin_run cleared
            # the previous run's
            return 'still' if self._good is not None else 'waiting'
        if still.mono != self._still_key:
            self._good = {'src': 'still', 'thumb': thumbnail(still.frame),
                          'exposure': exposure_readout(still.frame),
                          'step': still.step, 'kv': still.kv,
                          'tag': still.tag, 't_run': still.t_run,
                          'mono': still.mono, 'wall': still.wall,
                          'seq': still.mono}
            self._still_key = still.mono
        del still
        return 'still'

    def _state(self, kind, now_mono, now_wall):
        g = self._good
        st = {'kind': kind, 'banner': BANNERS[kind][0]}
        if kind == 'idle':
            st['text'] = ("No SLDEA run yet. This window opens by itself "
                          "when a run starts.")
        elif kind == 'waiting':
            st['text'] = ("Waiting for this run's first camera frame. "
                          "Nothing from an earlier run is shown.")
        elif kind == 'live':
            age = g.get('age_at_poll')
            st['text'] = (
                f"LIVE video stream: frame {fmt_age(age)} old, taken "
                f"{fmt_clock(g['wall'])}" if age is not None else
                f"LIVE video stream: frame under 2 s old (the run clock "
                f"has not started), taken about {fmt_clock(g['wall'])}")
        elif kind == 'still':
            st['text'] = (
                f"LAST STILL, not live: step {g['step']} [{g['tag']}] at "
                f"{float(g['kv']):.2f} kV, taken "
                f"{fmt_age(now_mono - g['mono'])} ago "
                f"({fmt_clock(g['wall'])}). This run takes stills only, "
                f"so this window shows the newest still the run took.")
        elif kind in ('stalled', 'closed'):
            why = ("the recorder has had no new frame for over 2 s"
                   if kind == 'stalled' else
                   "the recorder's camera stream is no longer running")
            last = ("" if g is None else
                    f" Last frame shown was taken {fmt_clock(g['wall'])}.")
            st['text'] = f"NO FRAME: {why}.{last}"
        else:                                           # 'ended'
            if g is None:
                what = "No camera frame was shown during this run."
            elif g['src'] == 'still':
                what = (f"Last frame shown: still step {g['step']} "
                        f"[{g['tag']}] at {float(g['kv']):.2f} kV, taken "
                        f"{fmt_clock(g['wall'])}.")
            else:
                what = (f"Last frame shown: video stream frame taken "
                        f"{fmt_clock(g['wall'])}.")
            st['text'] = (f"RUN ENDED at {fmt_clock(self._ended_wall)}, "
                          f"not live. {what}")
        st['run'] = self._run_words(kind)
        shows_frame = g is not None and kind in ('live', 'still', 'ended')
        st['exposure'] = exposure_words(g['exposure'] if shows_frame
                                        else None)
        st['thumb'] = g['thumb'] if shows_frame else None
        st['img_key'] = (kind, g['seq'] if shows_frame else None)
        self.state = st
        return st

    def _run_words(self, kind):
        if kind == 'idle':
            return ""
        if kind == 'ended':
            return ("The Run log on the SLDEA tab says how the run ended.")
        p = self._p
        app = self.app
        if getattr(app, '_sldea_stop', False):
            return ("Stopping: abort or a stop condition. See the Run log "
                    "on the SLDEA tab.")
        try:
            el = float(getattr(app, '_sldea_elapsed', 0.0) or 0.0)
            total = float(p.total_duration_s)
            if el >= total:
                return (f"The staircase has finished "
                        f"({fmt_run_time(total)}); the run is shutting "
                        f"down.")
            head = ("DRY run (no HV): plan at" if self._dry
                    else "LIVE HV run: commanded")
            return (f"{head} {p.kv_at(el):.2f} kV, run time "
                    f"{fmt_run_time(el)} of {fmt_run_time(total)}")
        except Exception:
            return ""

    def _show(self, st):
        """Put a display state on the window (Tk thread)."""
        if not self._alive():
            return
        if st['img_key'] != self._img_key or self._photo is None:
            from PIL import ImageTk
            size = None
            if self._photo is not None:
                size = (self._photo.width(), self._photo.height())
            img = render(st['thumb'], st['kind'], size=size)
            if self._photo is not None and size == (img.width, img.height):
                self._photo.paste(img)
            else:
                self._photo = ImageTk.PhotoImage(img, master=self.win)
                self._img_lbl.config(image=self._photo)
            self._img_key = st['img_key']
        self._state_lbl.config(text=st['text'])
        self._run_lbl.config(text=st['run'])
        words, level, color = st['exposure']
        self._exp_lbl.config(text=words)
        self._level_lbl.config(text=level,
                               bg=color if color else self._level_bg)
