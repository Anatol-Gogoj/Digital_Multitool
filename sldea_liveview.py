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
  VideoRecorder.latest() (a lock held for one reference read, and a BGR
  copy made outside it; only the thumbnail is converted to RGB).
  (None, None) from it is shown as "NO FRAME (stream stalled)", the
  dead-camera signal #48 asks for. A stream that stalls or closes only
  once the run is finishing is expected, and is shown in grey as
  "RECORDING ENDED". One that had already stalled or closed, on show in
  red, before the run ended stays red until the run has ended (#388):
  an operator who pressed Abort because the camera died must not see
  that relabeled as expected;
* a video run whose stream gives no frame while the run hands over
  stills (its stream never started, so it goes on with one-shot stills,
  #392): the newest saved still, under a red "VIDEO STREAM DOWN: LAST
  STILL, NOT LIVE" banner (#388). A still handed over since the last
  stream frame shown takes the place of the red NO FRAME; without one,
  the rule above holds;
* a stills-only run: the newest SAVED still, which the run thread hands
  over in ONE attribute, app._sldea_live_still, as a LiveStill, once its
  save has succeeded: a still that could not be saved is never shown as
  one (#388). That is a plain reference swap: no copy, no lock the view
  could hold, no Tk call. The view reads it on the Tk thread and labels
  it a still with its age, so it is never read as live.

It is called "live view" in code because "preview" already means the
run-plan staircase on the SLDEA tab (sldea_preview).

HV-safety rules this module keeps (the run thread runs the watchdog and
the ramp):

* The run thread never calls anything here. Its only contact is the
  attribute swap above, and that never depends on whether this window is
  open, closed or destroyed.
* The run thread is not fully decoupled from this window, though. Its
  own root.after calls (_sldea_log, _sldea_set_status) are marshaled to
  the Tk thread by _tkinter and wait until that thread takes them, so
  one made while a tick of this loop runs waits for the tick to end.
  With a 1080p frame a tick costs about 10 ms, twice a second (#388:
  6.6 ms median and 7.3 ms max without the Tk paste in the review; 9.5
  ms median and 13 ms max with it on the development PC, 2026-10-06).
  Any Tk work delays those calls the same way; the coupling predates
  this window. A closed window has no tick and adds nothing.
* Everything here runs on the Tk thread, from a Tk `after` loop at about
  2 Hz that only reads. It never opens, grabs from or re-stamps the
  camera: in a stills-only run a stream would contend for the device
  exactly as the refused Webcam preview did.
* A frame from the run is never written to: the view works on its own
  thumbnail, and the full-size frame is dropped at the end of each tick.
  The run thread goes on reading a still's frame after the hand-over
  (the baseline picture check), so it may not write into it either;
  gui._sldea_capture says so, and a test pins it byte for byte.
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
    # the stream closing once the staircase is over or the run was
    # stopped: expected, so grey and in words. Only for a stream that was
    # still delivering until then; a NO FRAME already on show stays red
    # (#388, LiveView.poll)
    'finishing': ("RECORDING ENDED, NOT LIVE", TOL_GREY),
    # a video run whose stream gives no frame but which hands over
    # one-shot stills (its stream never started, #392): the newest saved
    # still, with the stream fault in words and in red (#388)
    'stream_down': ("VIDEO STREAM DOWN: LAST STILL, NOT LIVE", TOL_RED),
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
#   frame  the RGB frame just saved (the run's own array, not a copy: the
#          view only reads it, and the run thread does not write it)
#   step, kv, tag   the snapshot's step, nominal kV and tag
#   t_run  run time at `mono` (None without a run clock)
#   mono   time.monotonic() just before the save: the view's age clock,
#          and its key for "is this a new still"
#   wall   time.time() at the same moment, for the clock time shown
# The clock is read just before the save, after the capture's scope
# reads, so the shown age can understate the grab's by those reads (two
# scope round trips; zero without a scope). The hand-over itself comes
# after the save, and only when the save succeeded (#388), so a slow save
# delays the still on screen but does not make it look younger.
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


def thumbnail(frame, width=THUMB_W, bgr=False):
    """A NEW RGB uint8 array `width` wide with the frame's aspect ratio.
    The input is only read, never written. With `bgr` the input is in
    OpenCV's BGR order (VideoRecorder.latest()) and only the small result
    is reordered, so a 1080p frame is never converted whole."""
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
    if bgr and out.ndim == 3 and out.shape[2] == 3:
        out = out[:, :, ::-1]
    # always a fresh array the caller owns, whatever the path above did
    return np.array(out, dtype=np.uint8, copy=True)


def exposure_readout(frame, max_w=STATS_MAX_W):
    """The pre-flight's exposure statistics for one frame -> dict.

    Same definitions as sldea_profile.preflight_report: gray is the mean
    of the colour channels, 'saturated' is gray >= 250, the verdict is
    sldea_profile.exposure_verdict with sldea_edge.image_content's flat
    check. Taken on a strided sample (STATS_MAX_W), so on a frame wider
    than that the numbers are estimates of the full frame's. Every number
    is a mean over the colour channels, so RGB and BGR frames read the
    same.

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
    """The shared bold font at `size` px: TrueType first, cached per size
    (pil_fonts.bold_font, the chain Edge Review's letter tags use)."""
    import pil_fonts
    return pil_fonts.bold_font(size)


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
    also get the words large in the middle, on black. RECORDING ENDED
    keeps the last frame under its grey banner (words on black only when
    there is no frame)."""
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
    if kind in ('stalled', 'closed', 'waiting', 'idle', 'error',
                'finishing'):
        big = {'stalled': ("NO FRAME", "(stream stalled)"),
               'closed': ("NO FRAME", "(stream closed)"),
               'error': ("VIEW ERROR", "nothing shown here is current"),
               'finishing': ("RECORDING ENDED", "the run is finishing"),
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
    """A callable returning `obj`. For an object that takes weak
    references it is a weakref, which does not keep `obj` alive. For one
    that does not (an int, or a class with __slots__) it is a closure,
    which DOES keep it alive: identity must still be answerable. The GUI
    only hands this a VideoRecorder or None, and a VideoRecorder takes
    weak references, so the GUI never holds a recorder through it."""
    if obj is None:
        return lambda: None
    try:
        return weakref.ref(obj)
    except TypeError:
        return lambda: obj


def choose_place(root, area, size, gap=16, bottom_margin=48, slack=16):
    """Where the live view opens -> (x, y, covers_root).

    `root` is the main window's (x, y, width, height), `area` the
    (x0, y0, x1, y1) of the monitor it is on (LiveView._monitor_area),
    `size` the view's (width, height). Beside the main window, right then
    left, only where the whole view fits on that monitor: then it covers
    nothing. With no free room there (a maximised main window, a narrow
    screen), or when the main window is not on `area` at all, it goes
    INSIDE the main window's own rectangle, at its right edge, so it is
    on the main window's own monitor whatever the layout, and
    `covers_root` is True: the caller then keeps the main window above
    it, so an automatic open never covers the SLDEA tab or its status
    line, which carries the run's alarms.

    Owner decision 2026-10-06 (#388): keep it so. With no room beside
    the main window, the view opened at a run start stays behind it
    until "Live view..." is pressed, so it can never cover the run
    controls or Abort."""
    rx, ry, rw, rh = (int(v) for v in root)
    x0, y0, x1, y1 = (int(v) for v in area)
    w, h = (int(v) for v in size)
    on_area = (x0 - slack <= rx and rx + rw <= x1 + slack
               and y0 - slack <= ry <= y1)
    y = max(y0, min(ry, y1 - bottom_margin - h))
    if on_area and rx + rw + gap + w <= x1:
        return rx + rw + gap, y, False
    if on_area and rx - gap - w >= x0:
        return rx - gap - w, y, False
    return max(rx, rx + rw - w), ry, True


def win32_work_area(root):
    """(x0, y0, x1, y1) of the work area (the monitor less its taskbar)
    of the monitor that holds most of the Tk window `root`, in Tk's own
    coordinates; None off Windows or on any failure. A window-manager
    query only. In this DPI-unaware process user32 and Tk report the same
    virtualised coordinates (checked 2026-10-06 against four monitors at
    175 % on the development PC)."""
    import sys
    if sys.platform != 'win32':
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.DWORD),
                        ('rcMonitor', wintypes.RECT),
                        ('rcWork', wintypes.RECT),
                        ('dwFlags', wintypes.DWORD)]
        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR,
                                           ctypes.POINTER(MONITORINFO)]
        hwnd = int(root.wm_frame(), 16)
        hmon = user32.MonitorFromWindow(hwnd, 2)    # MONITOR_DEFAULTTONEAREST
        if not hmon:
            return None
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            return None
        r = mi.rcWork
        if r.right <= r.left or r.bottom <= r.top:
            return None
        return (r.left, r.top, r.right, r.bottom)
    except Exception:
        return None


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
    only, no widgets), open_with_run() after it (the window opens with the
    run, beside the main window when there is room and otherwise BEHIND
    it, and the keyboard focus goes back to the main window), end_run()
    from the tab's _sldea_finished (the window keeps its last frame,
    labelled RUN ENDED). open() and close() are the operator's: open()
    brings the window to the front, closing stops the loop, and a closed
    or never-opened window costs the run nothing.

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
        self._fault = False          # NO FRAME seen while the run went on
        self._stream_mono = None     # capture time of the last stream frame
        self._ended_wall = None
        self._covers_root = False    # placed inside the main window's area
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
        self._fault = False
        self._stream_mono = None
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

    def open(self, front=True):
        """Show the window (create it if needed), draw now, and run the
        loop while a run is going. `front` is the operator asking (the
        button): the window comes to the front. Without it (the run start)
        an existing window keeps its place in the stacking order, and a
        new one gives the keyboard back to the main window and stays
        behind it when it had to be put over it (_after_map)."""
        built = False
        if not self._alive():
            self._build()
            built = True
        elif front:
            # brought back if it was minimised or behind another window
            try:
                self.win.deiconify()
                self.win.lift()
            except Exception:
                pass
        self._img_key = None
        self._refresh()
        self._schedule()
        if built and not front:
            self._after_map()

    def open_with_run(self):
        """The run start's open (gui.sldea_run): never in front of the
        main window's tab, never holding the keyboard."""
        self.open(front=False)

    def _after_map(self):
        """Once the new window is on screen (that is when the window
        manager activates it): give the keyboard focus back to the main
        window, and raise the main window above the view if the view had
        to be placed over it. One-shot."""
        win = self.win
        done = {'once': False}

        def settle(ev=None):
            if done['once'] or (ev is not None and ev.widget is not win):
                return
            done['once'] = True
            root = self.app.root
            try:
                if self._covers_root:
                    root.lift()
                root.focus_force()
            except Exception:
                pass
        try:
            win.bind('<Map>', settle, add='+')
            if win.winfo_ismapped():
                settle()
        except Exception:
            pass

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
        # A window destroyed without close() leaves its image behind
        # (#388). _show would paste into it whenever the size matched and
        # never give the new label an image, so the new window starts
        # without one and _show makes its own.
        self._photo = None
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

    # the window's size, roughly: the picture plus four text rows
    VIEW_SIZE = (THUMB_W + 40, 600)

    def _monitor_area(self):
        """(x0, y0, x1, y1) of the MAIN WINDOW'S OWN monitor: on Windows
        its work area from user32 (win32_work_area); elsewhere the X
        screen. winfo_screenwidth alone is the primary monitor only, so a
        main window on a second monitor used to send the view to the
        first; and the virtual root (winfo_vroot*) is the bounding box of
        all monitors, which has holes where no monitor is (measured
        2026-10-06 on a four-monitor PC), so it is no help either."""
        root = self.app.root
        area = win32_work_area(root)
        if area is None:
            area = (0, 0, int(root.winfo_screenwidth()),
                    int(root.winfo_screenheight()))
        return area

    def _place(self):
        """choose_place for the main window as it stands. No event
        processing; a failure leaves the window manager's choice."""
        self._covers_root = False
        try:
            root = self.app.root
            rect = (root.winfo_rootx(), root.winfo_rooty(),
                    root.winfo_width(), root.winfo_height())
            x, y, covers = choose_place(rect, self._monitor_area(),
                                        self.VIEW_SIZE)
            self.win.geometry(f"+{x}+{y}")
            self._covers_root = covers
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
        never touches the camera.

        A stream that stalls or closes once the run is over (_run_over)
        is the run ending: grey 'finishing'. A stall or close this view
        already showed while the run was still going is a fault, and it
        stays red until _sldea_finished, Abort or not (#388). A frame
        coming back clears it. The view knows only what it polled, so a
        stream that died while the window was closed and is first seen
        after the run ended reads as the run ending.

        A still handed over since the last stream frame this view showed
        (or with none shown this run) comes first: while this run's
        stream gives no frame, that still is shown as 'stream_down', the
        still under a red VIDEO STREAM DOWN banner, Abort or not. That is
        a video run whose stream never started, which goes on with
        one-shot stills (#392). The red NO FRAME rule above applies only
        without such a still."""
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
            if kind in ('stalled', 'closed') and self._still_since_stream():
                # the stream gives no frame, but the run hands over stills
                # (the worker registers a recorder whose stream never
                # started, then goes on with one-shot stills): show the
                # newest, and say in red that the stream is down
                if (self._good or {}).get('src') != 'still':
                    self._still_key = None   # take the still, not _good
                self._poll_still(now_mono)
                kind = 'stream_down'
        else:
            kind = self._poll_still(now_mono)
        if kind in ('live', 'still'):
            self._fault = False          # a frame again: no fault on show
        elif kind in ('stalled', 'closed'):
            if not self._run_over():
                self._fault = True       # shown in red while the run goes
            elif not self._fault:
                # rec.stop() runs after the staircase (up to 10 s) before
                # _sldea_finished: a stream closing then is the run
                # ending, not a camera fault, and is not shown in red
                kind = 'finishing'
            # else it stays red: an Abort pressed BECAUSE the camera died
            # must not relabel that as the recording's expected end (#388)
        return self._state(kind, now_mono, now_wall)

    def _still_since_stream(self):
        """True when this run has handed over a still since the last
        stream frame this view showed, or with no stream frame shown this
        run at all. Both clocks are time.monotonic(): LiveStill.mono, and
        the stream frame's capture time (_poll_stream)."""
        still = getattr(self.app, '_sldea_live_still', None)
        if still is None:
            return False
        return self._stream_mono is None or still.mono > self._stream_mono

    def _run_over(self):
        """True once the run is on its way out: stopped (Abort, a
        breakdown, a baseline stop) or past the end of its staircase."""
        app = self.app
        if getattr(app, '_sldea_stop', False):
            return True
        try:
            return float(getattr(app, '_sldea_elapsed', 0.0) or 0.0) >= \
                float(self._p.total_duration_s)
        except Exception:
            return False

    def _poll_stream(self, rec, now_mono, now_wall):
        # latest(): the BGR copy. latest_rgb() would convert the whole
        # frame to RGB on this thread before it is shrunk; only the
        # thumbnail needs converting, and the exposure numbers are channel
        # means, which do not care about the order.
        frame, t = rec.latest()
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
        self._good = {'src': 'stream', 'thumb': thumbnail(frame, bgr=True),
                      'exposure': exposure_readout(frame),
                      'age_at_poll': age, 'mono': now_mono - (age or 0.0),
                      'wall': now_wall - (age or 0.0), 't_run': t,
                      'seq': now_mono}
        self._stream_mono = self._good['mono']
        del frame
        return 'live'

    def _poll_still(self, now_mono):
        still = getattr(self.app, '_sldea_live_still', None)
        if still is None:
            # a still from earlier in THIS run stays: begin_run cleared
            # the previous run's. A frame from this run's STREAM is not a
            # still: the recorder it came from is no longer readable, so
            # the stream has closed for this view.
            g = self._good
            if g is None:
                return 'waiting'
            return 'still' if g.get('src') == 'still' else 'closed'
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
        if kind in ('still', 'stream_down') and \
                (g is None or g.get('src') != 'still'):
            kind = 'waiting' if g is None and kind == 'still' else 'closed'
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
                f"so this window shows the newest still the run saved.")
        elif kind == 'stream_down':
            st['text'] = (
                f"VIDEO STREAM DOWN: the camera stream gives no frame, so "
                f"no video is being recorded and the run takes one-shot "
                f"stills. LAST STILL, not live: step {g['step']} "
                f"[{g['tag']}] at {float(g['kv']):.2f} kV, taken "
                f"{fmt_age(now_mono - g['mono'])} ago "
                f"({fmt_clock(g['wall'])}).")
        elif kind in ('stalled', 'closed'):
            why = ("the recorder has had no new frame for over 2 s"
                   if kind == 'stalled' else
                   "the recorder's camera stream is no longer running")
            last = ("" if g is None else
                    f" Last frame shown was taken {fmt_clock(g['wall'])}.")
            st['text'] = f"NO FRAME: {why}.{last}"
        elif kind == 'finishing':
            last = ("" if g is None else
                    f" Last frame shown was taken {fmt_clock(g['wall'])}.")
            st['text'] = ("RECORDING ENDED, not live: the run is finishing "
                          "(its staircase is over or it was stopped), so "
                          "its camera stream is closing. This is expected."
                          + last)
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
        shows_frame = g is not None and kind in ('live', 'still', 'ended',
                                                 'finishing', 'stream_down')
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
