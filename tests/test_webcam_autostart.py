#!/usr/bin/env python3
"""The Webcam tab starts its preview when opened, and says when it is off.

`#375`: the preview started only from the Start Preview button, and a
stopped preview left its last frame on screen, looking exactly like a live
one. Now opening the tab starts the preview through a start path that never
opens a dialog, a stopped preview shows a large PREVIEW OFF with the reason
over its dimmed last frame (or on black), and leaving the tab stops the
preview unless interval capture needs it (gui.CAM_STOP_PREVIEW_ON_TAB_LEAVE,
owner decision 2026-10-06).

`#393`: when whatever held that start off, or took the camera from the
preview, clears while the tab is shown (Apply & Lock, an SLDEA run, a timed
capture, a dialog), the reason watch starts the preview once (owner
decision 2026-10-06). A start that fails is not tried again on that visit,
and the operator's own Stop stays stopped.

Headless apart from a Tk root: the camera, the device scan and the dialogs
are stubbed, so no test here opens a real camera. Most tests build only the
real Webcam tab into a two-tab notebook; one builds the whole app, to check
the tab's binding lives beside the SLDEA tab's. Apply & Lock, the timed
capture and the SLDEA start path (into its real camera pre-flight dialog)
run their real methods, with the camera layer under them stubbed.

Run: .venv/bin/python tests/test_webcam_autostart.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import queue
import threading
import time
import types

import gui
import webcam

G = gui.InstrumentControlGUI
# One period of the reason watch, with room for a busy desktop: long
# enough for the watch to have looked at least once.
WATCH = gui.CAM_SPLASH_POLL_MS / 1000.0 + 0.2


class _MB:
    """messagebox stub: records every call, answers every question No
    (Yes with `yes`, for the tests that start a DRY SLDEA run)."""

    def __init__(self, yes=False):
        self.calls = []
        self.yes = yes

    def _ask(self, name, title, msg='', **kw):
        self.calls.append((name, title, msg))
        return self.yes

    def __getattr__(self, name):
        def show(title, msg='', **kw):
            return self._ask(name, title, msg, **kw)
        return show


class _FakeCam:
    """Stands in for webcam.Camera. Class-level knobs and one log, reset by
    _Patched: `fail` makes open() raise with that text, `blank` makes
    read_rgb() return no frame (an unplugged camera)."""
    log = []
    fail = None
    blank = False
    level = 200

    def __init__(self, index=0, width=None, height=None):
        self.index = index
        self._open = False

    @property
    def is_open(self):
        return self._open

    def open(self):
        _FakeCam.log.append(('open', self.index))
        if _FakeCam.fail:
            raise RuntimeError(_FakeCam.fail)
        self._open = True
        return self

    def read_rgb(self):
        import numpy as np
        if not self._open or _FakeCam.blank:
            return None
        return np.full((360, 480, 3), _FakeCam.level, dtype=np.uint8)

    def close(self):
        _FakeCam.log.append(('close', self.index))
        self._open = False


class _Patched:
    """Stub the camera layer and the dialogs; restore every module value a
    test may change, the gui switches included."""

    def __init__(self, yes=False):
        self.yes = yes

    def __enter__(self):
        self.saved_webcam = {n: getattr(webcam, n) for n in (
            'Camera', 'list_cameras', 'list_controls', 'v4l2_available',
            'apply_locked')}
        self.saved_gui = {n: getattr(gui, n) for n in (
            'messagebox', 'CAM_AUTOSTART_ON_TAB',
            'CAM_STOP_PREVIEW_ON_TAB_LEAVE', 'CAM_NO_FRAME_S',
            'CAM_AUTOSTART_DELAY_MS')}
        webcam.Camera = _FakeCam
        webcam.list_cameras = lambda max_index=8: [0]
        webcam.list_controls = lambda device: []
        webcam.v4l2_available = lambda: False
        webcam.apply_locked = lambda *a, **k: 0
        self.mb = gui.messagebox = _MB(self.yes)
        gui.CAM_AUTOSTART_ON_TAB = True
        gui.CAM_STOP_PREVIEW_ON_TAB_LEAVE = True
        _FakeCam.log = []
        _FakeCam.fail = None
        _FakeCam.blank = False
        return self

    def __exit__(self, *exc):
        for n, v in self.saved_webcam.items():
            setattr(webcam, n, v)
        for n, v in self.saved_gui.items():
            setattr(gui, n, v)
        return False


def _root():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return None
    root.geometry('900x760')
    return root


def _app():
    """(root, app): the real Webcam tab, built by the real builder into a
    notebook whose other tab is a blank 'Other', which is selected. None
    when there is no display or no capture deps (the tab then builds its
    install hint instead)."""
    from tkinter import ttk
    root = _root()
    if root is None:
        return None, None
    app = G.__new__(G)
    app.root = root
    app.notebook = ttk.Notebook(root)
    app.notebook.pack(fill='both', expand=True)
    app.other_tab = ttk.Frame(app.notebook)
    app.notebook.add(app.other_tab, text='Other')
    # a binding made before the tab is built, which it must not replace
    app.earlier_binding = []
    app.notebook.bind('<<NotebookTabChanged>>',
                      lambda _e: app.earlier_binding.append(1), add='+')
    # the footer's status line: the app builds it before the tabs, and the
    # capture and Apply & Lock paths write to it
    app.status_bar = ttk.Label(root)
    # the Webcam state __init__ sets and the tab's code reads directly
    app.sg = None
    app._bg_busy = set()
    app.cam = None
    app.cam_previewing = False
    app.cam_preview_job = None
    app.cam_last_frame = None
    app.cam_photo = None
    app.cam_interval_job = None
    app.cam_capture_index = 0
    app.cam_seq_running = False
    app.cam_seq_thread = None
    app.cam_seq_queue = queue.Queue()
    app._cam_seq_kind = app._cam_seq_ch = None
    app.create_webcam_tab()
    if not hasattr(app, 'cam_view'):
        print("   (skipped: the Webcam tab has no capture deps here)")
        root.destroy()
        return None, None
    app.notebook.select(app.other_tab)
    _pump(root, 0.1)
    return root, app


def _close(root, app):
    try:
        app.cam_stop_preview()
        for name in ('_cam_autostart_job', '_cam_watch_job',
                     '_cam_splash_idle', 'cam_interval_job'):
            job = getattr(app, name, None)
            if job is not None:
                try:
                    root.after_cancel(job)
                except Exception:
                    pass
    finally:
        root.destroy()


def _pump(root, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        root.update()
        time.sleep(0.01)


def _pump_until(root, cond, secs=3.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        root.update()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def _pump_in_mainloop(root, cond, secs=3.0):
    """_pump_until inside mainloop(). _run_bg's worker thread hands its
    result back with root.after(), and _tkinter refuses a call from another
    thread unless the Tk thread is in mainloop(): with update() alone that
    worker dies with "main thread is not in main loop"."""
    end = time.monotonic() + secs

    def check():
        if cond() or time.monotonic() >= end:
            root.quit()
        else:
            root.after(10, check)
    root.after(10, check)
    root.mainloop()
    return cond()


def _opens():
    return [e for e in _FakeCam.log if e[0] == 'open']


def _camera_boxes(p):
    """The boxes the Webcam start paths can show: none may appear."""
    return [c for c in p.mb.calls
            if c[1].startswith(('Webcam', 'Camera in use'))]


def _select_webcam(app):
    app.notebook.select(app._cam_tab)


def _shows_splash(app):
    """cam_view is showing the splash image, sized as _cam_show sizes."""
    v = app.cam_view
    return (app.cam_photo is not None
            and str(v.cget('image')) == str(app.cam_photo)
            and int(v.cget('width')) == 0 and int(v.cget('height')) == 0
            and app.cam_splash_img is not None)


def _disc_frame(paper=170, disc=110, h=240, w=320, r=60, seed=2):
    """A dark disc on lighter paper with a little noise, gray (R = G = B):
    the SLDEA pre-flight passes it, so its Start asks nothing, and
    Auto-WB once finds it balanced at the first try."""
    import numpy as np
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    g = np.full((h, w), float(paper))
    g[(xx - w / 2) ** 2 + (yy - h / 2) ** 2 <= r * r] = disc
    g = np.clip(g + rng.normal(0, 2.0, size=(h, w)), 0, 255).astype(np.uint8)
    return np.stack([g, g, g], axis=2)


class _CameraWork:
    """The camera layer under Stabilize, Auto-WB once, Auto-expose, Apply &
    Lock, the timed capture and the SLDEA pre-flight: v4l2-ctl, one-shot
    grabs and the lock file, all stubbed. A call that takes the camera OFF
    the Tk thread (the adjustment's or the capture's worker) waits for
    release(), so the work is still running while a test looks at the tab.
    The preview's own re-stamp and the pre-flight's grab run on the Tk
    thread and never wait."""

    NAMES = ('resolve_camera', 'oneshot_rgb', 'set_control', 'get_control',
             'bayer_format', '_v4l2', 'parse_frame_sizes', 'choose_size',
             'auto_exposure', 'apply_locked', 'save_camera_settings',
             'v4l2_available')

    def __init__(self, frame=None):
        self.frame = _disc_frame() if frame is None else frame
        self.gate = threading.Event()

    def _hold(self):
        if threading.current_thread() is not threading.main_thread():
            if not self.gate.wait(10):
                raise TimeoutError("the camera work was never released")

    def release(self):
        self.gate.set()

    def __enter__(self):
        self.saved = {n: getattr(webcam, n) for n in self.NAMES}
        self.locked = dict(webcam.LOCKED_CONTROLS)

        def oneshot(spec, count=2):
            self._hold()
            return self.frame

        def auto_exposure(*a, **kw):
            self._hold()
            return None, None        # "could not settle": no field to fill

        def apply_locked(device, exclude=None):
            self._hold()
            return 0

        webcam.resolve_camera = lambda idx: {'kind': 'cv2', 'index': int(idx)}
        webcam.oneshot_rgb = oneshot
        webcam.set_control = lambda device, name, value: True
        webcam.get_control = lambda device, name: 64
        webcam.bayer_format = lambda device: 'RGGB'
        webcam._v4l2 = lambda *a, **kw: ''
        webcam.parse_frame_sizes = lambda text, fourcc: [(640, 480)]
        webcam.choose_size = lambda sizes, max_width=1920: (640, 480)
        webcam.auto_exposure = auto_exposure
        webcam.apply_locked = apply_locked
        webcam.save_camera_settings = (
            lambda controls, path=None: 'nowhere/camera_controls.json')
        webcam.v4l2_available = lambda: True
        return self

    def __exit__(self, *exc):
        self.gate.set()              # never leave a worker waiting
        for n, v in self.saved.items():
            setattr(webcam, n, v)
        webcam.set_locked(self.locked)
        return False


def _var(value):
    return types.SimpleNamespace(get=lambda: value)


class _Vars(dict):
    """sldea_vars for the real sldea_run. A box it has no entry for reads
    empty, as an untouched box does."""

    def __missing__(self, key):
        return _var('')


def _sldea_ready(app):
    """Give the real-Webcam-tab app what the real sldea_run and
    _sldea_finished read, for a DRY run with no instruments. The worker is
    a stub that returns at once: the run lasts until the test calls
    app._sldea_finished(), the real worker's last act, on the Tk thread."""
    from sldea_profile import SldeaProfile
    app.sldea_dryrun = _var(True)
    app.sldea_vars = _Vars({k: _var(v) for k, v in {
        'sgch': '1', 'vch': '2', 'ich': '3', 'diam_mm': '16',
        'electrode': 'CNT', 'conc_ml': '', 'wd_ua': '100', 'wd_s': '3',
        'tel_hz': '2', 'vid_fps': '1'}.items()})
    for name in ('sldea_autoproc', 'sldea_trek_inv', 'sldea_wd_on',
                 'sldea_tel_on', 'sldea_vid_on', 'sldea_vid_detect'):
        setattr(app, name, _var(False))
    app.sldea_outdir, app.sldea_runname = _var('.'), _var('RUN')
    app.sldea_run_btn = app.sldea_abort_btn = types.SimpleNamespace(
        config=lambda **kw: None)
    app.scope = None
    app._sldea_running = app._sldea_stop = False
    app._sldea_prelog = app._sldea_runlog = None
    app._sldea_loglock = threading.Lock()
    app._sldea_recorder = None
    app._sldea_video_jobs = []
    app._sldea_live_ch = app._sldea_scope_chs = None
    app.sldea_lines = []
    app._sldea_log = lambda msg: app.sldea_lines.append(str(msg))
    app._sldea_build_profile = lambda: (SldeaProfile(
        start_kv=0.0, end_kv=1.0, step_kv=1.0, ramp_s=0.4, landing_s=1.2,
        settle_s=0.2, snap_lead_s=0.2), None)
    app._sldea_conc_applicable = lambda electrode=None: False
    app._sldea_animate_cursor = lambda: None
    app._sldea_worker = lambda *a, **kw: None


def _through_the_preflight(root, app, button, probe_ms=1000):
    """Press the real Run (sldea_run, DRY) and, from inside its real camera
    pre-flight dialog, open the Webcam tab as the keyboard can: a Tk grab
    holds the pointer, not the keyboard, so the arrow keys still move a
    tab strip that has the focus. Past the tab-click start's delay
    and a reason-watch period, note what the tab did, then press the
    dialog's `button`, 'start' or 'cancel'. Returns the notes; 'dialog' is
    False when sldea_run never showed the dialog."""
    import tkinter as tk
    from tkinter import ttk
    seen = {'dialog': False}

    def dialog():
        wins = [w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel) and w.winfo_exists()
                and w.title().startswith('Camera pre-flight')]
        return wins[-1] if wins else None

    def open_tab():
        seen['grab'] = root.grab_current() is not None
        _select_webcam(app)

    def probe():
        win = dialog()
        try:
            seen['dialog'] = win is not None
            seen['opens'] = list(_opens())
            seen['previewing'] = app.cam_previewing
            seen['blocker'] = app._cam_autostart_blocker()
            seen['splash'] = app.cam_splash
            if win is not None:
                start, _adjust, cancel = [
                    b for f in win.winfo_children()
                    if isinstance(f, ttk.Frame)
                    for b in f.winfo_children() if isinstance(b, ttk.Button)]
                (start if button == 'start' else cancel).invoke()
        except BaseException as e:      # a callback's traceback is lost
            seen['error'] = e
        finally:
            if win is not None and win.winfo_exists():
                win.destroy()           # never leave sldea_run waiting

    jobs = [root.after(200, open_tab), root.after(probe_ms, probe)]
    try:
        app.sldea_run()
    finally:
        for job in jobs:                # no dialog: they must not run later
            try:
                root.after_cancel(job)
            except Exception:
                pass
    if 'error' in seen:
        raise seen['error']
    return seen


# ---------------------------------------------------------------- tests

def test_the_splash_draws_large_centered_text_on_the_image():
    """The pure drawing: the image keeps its size, the headline is drawn
    in the middle band, and the corners are left as they were."""
    from PIL import Image
    img = Image.new('RGB', (640, 480), (70, 70, 70))
    out = gui.draw_preview_splash(img, 'PREVIEW OFF', 'Click Start Preview',
                                  'Last frame taken 12:00:00')
    assert out.size == img.size and out is not img
    assert img.getpixel((320, 240)) == (70, 70, 70), "input was modified"
    assert out.getpixel((2, 2)) == (70, 70, 70), "a corner changed"
    middle = out.crop((0, 160, 640, 320)).convert('L')
    assert middle.getextrema()[1] == 255, "no white text in the middle"
    # a reason too long for the width is shortened, never spilled
    long = gui.draw_preview_splash(Image.new('RGB', (320, 240)),
                                   'PREVIEW OFF', 'x' * 400)
    assert long.size == (320, 240)


def test_with_no_frame_yet_the_view_says_preview_off_on_black():
    with _Patched():
        root, app = _app()
        if root is None:
            return
        try:
            assert app.cam_splash == (gui.CAM_SPLASH_OFF, gui.CAM_OFF_CLICK,
                                      None), app.cam_splash
            assert _shows_splash(app), "the old text placeholder is showing"
            assert app.cam_splash_img.getpixel((1, 1)) == (0, 0, 0)
            assert _opens() == [], "building the tab opened the camera"
        finally:
            _close(root, app)


def test_opening_the_tab_starts_the_preview_once_with_no_dialog():
    with _Patched() as p:
        root, app = _app()
        if root is None:
            return
        try:
            _select_webcam(app)
            # a second event for the same visit must not start it twice
            app.notebook.event_generate('<<NotebookTabChanged>>')
            assert _pump_until(root, lambda: app.cam_previewing), (
                "opening the tab did not start the preview")
            _pump(root, 0.3)
            assert _opens() == [('open', 0)], _FakeCam.log
            assert p.mb.calls == [], p.mb.calls
            assert app.cam_preview_btn.cget('text') == "Stop Preview"
            assert app.cam_splash is None, "the splash is over live frames"
            assert app.earlier_binding, "the tab replaced an earlier binding"
        finally:
            _close(root, app)


def test_an_sldea_run_holds_the_start_off_with_no_dialog():
    """During a run, and while its video recorder is still letting go of
    the camera: no open, no refusal box, and the splash says why. When
    the run ends while the tab is shown, the reason watch starts the
    preview once (#393), still with no dialog."""
    for holder in ('run', 'recorder'):
        with _Patched() as p:
            root, app = _app()
            if root is None:
                return
            try:
                reading = [True]
                if holder == 'run':
                    app._sldea_running = True
                else:
                    # the recorder stays registered after its run
                    app._sldea_recorder = types.SimpleNamespace(
                        reader_alive=lambda: reading[0])
                _select_webcam(app)
                _pump(root, WATCH)                    # a watch period
                assert not app.cam_previewing, holder
                assert _opens() == [], (holder, _FakeCam.log)
                assert p.mb.calls == [], (holder, p.mb.calls)
                assert app.cam_splash[:2] == (gui.CAM_SPLASH_OFF,
                                              gui.CAM_OFF_SLDEA), app.cam_splash
                assert _shows_splash(app)
                # the run ends while the operator watches the tab
                app._sldea_running = False
                reading[0] = False
                assert _pump_until(root, lambda: app.cam_previewing,
                                   secs=2.0), (holder, app.cam_splash)
                _pump(root, WATCH)
                assert app.cam_previewing and app.cam_splash is None, holder
                assert _opens() == [('open', 0)], (holder, _FakeCam.log)
                assert p.mb.calls == [], (holder, p.mb.calls)
            finally:
                _close(root, app)


def test_a_modal_dialog_holds_the_start_off():
    """The SLDEA camera pre-flight is a grabbed dialog. By then sldea_run
    has closed the preview's camera for the run, and _sldea_running is
    not set until Start, so the run check alone does not see it. A grab
    stops the pointer, not the keyboard, so the tab can still be opened
    (the arrow keys on a focused tab strip; the app does not enable
    Ctrl+Tab): no open while any dialog holds the grab, and the splash
    says why. Once the dialog is gone the start this visit was owed runs,
    once (#393)."""
    import tkinter as tk
    with _Patched() as p:
        root, app = _app()
        if root is None:
            return
        try:
            dialog = tk.Toplevel(root)
            dialog.grab_set()
            _pump(root, 0.1)
            if root.grab_current() is None:
                print("   (skipped: this display gives no grab)")
                dialog.destroy()
                return
            _select_webcam(app)
            _pump(root, WATCH)                        # a watch period
            assert not app.cam_previewing
            assert _opens() == [], _FakeCam.log
            assert p.mb.calls == [], p.mb.calls
            assert app.cam_splash[1] == gui.CAM_OFF_DIALOG, app.cam_splash
            dialog.grab_release()
            dialog.destroy()
            assert _pump_until(root, lambda: app.cam_previewing,
                               secs=2.0), app.cam_splash
            _pump(root, WATCH)
            assert _opens() == [('open', 0)], _FakeCam.log
            assert p.mb.calls == [], p.mb.calls
        finally:
            _close(root, app)


def test_apply_and_lock_ending_resumes_the_preview_once():
    """The issue's own case (#393). Apply & Lock holds the camera-ctrl
    busy key while it writes the camera, without stopping the preview, so
    leaving the tab and coming back while it runs finds the start held
    off ("A camera adjustment is running"). When Apply & Lock ends, the
    watch starts the preview once, with no dialog."""
    with _Patched() as p, _CameraWork() as work:
        root, app = _app()
        if root is None:
            return
        try:
            app._cam_device = lambda: '/dev/video0'
            _select_webcam(app)
            assert _pump_until(root, lambda: app.cam_previewing)
            app.cam_apply_controls()                  # the real button
            assert 'camera-ctrl' in app._bg_busy
            app.notebook.select(app.other_tab)        # leave: it stops
            _pump(root, 0.1)
            assert not app.cam_previewing
            _select_webcam(app)                       # back, while it runs
            _pump(root, WATCH)                        # a watch period
            assert not app.cam_previewing
            assert app.cam_splash[1] == gui.CAM_OFF_ADJUSTING, app.cam_splash
            work.release()                            # Apply & Lock ends
            assert _pump_in_mainloop(root, lambda: app.cam_previewing,
                                     secs=3.0), app.cam_splash
            assert 'camera-ctrl' not in app._bg_busy
            _pump(root, WATCH)
            assert app.cam_previewing and app.cam_splash is None
            # the leave-tab stop kept the device open: no second open
            assert _opens() == [('open', 0)], _FakeCam.log
            assert p.mb.calls == [], p.mb.calls
        finally:
            work.release()
            _close(root, app)


def test_a_timed_capture_ending_resumes_the_preview_once():
    """A timed capture started on the shown tab stops the preview and
    closes the camera for its one-shot grabs. When it ends, the watch
    starts the preview again, once, with no dialog (#393)."""
    with _Patched() as p, _CameraWork() as work:
        root, app = _app()
        if root is None:
            return
        try:
            app._cam_save_frame = lambda *a, **kw: None    # no files
            app.cam_tm_delays.set('0')                     # one shot, t=0
            app.cam_tm_focus.set(False)                    # no CSV
            _select_webcam(app)
            assert _pump_until(root, lambda: app.cam_previewing)
            app.cam_toggle_timed()            # the real Start timed capture
            _pump(root, WATCH)                # its shot is held: running
            assert not app.cam_previewing
            assert app.cam_splash[1] == gui.CAM_OFF_TIMED, app.cam_splash
            assert _opens() == [('open', 0)], _FakeCam.log
            work.release()                    # the shot is taken: it ends
            assert _pump_until(root, lambda: app.cam_previewing,
                               secs=3.0), app.cam_splash
            assert not app.cam_seq_running and not app._cam_worker_alive()
            _pump(root, WATCH)
            assert _opens() == [('open', 0)] * 2, _FakeCam.log
            assert p.mb.calls == [], p.mb.calls
        finally:
            work.release()
            _close(root, app)


def test_an_sldea_run_ending_resumes_the_preview_once():
    """#393 through the real start path. The operator leaves the tab to
    press Run, opens the Webcam tab again from inside the camera
    pre-flight (its grab holds the start off), and presses Start there:
    the run holds it off until it ends, and then the preview starts once,
    with no dialog. With Cancel instead, the camera is free at once and
    the preview starts then."""
    for button in ('start', 'cancel'):
        with _Patched(yes=True) as p, _CameraWork():
            root, app = _app()
            if root is None:
                return
            _sldea_ready(app)
            try:
                _select_webcam(app)
                assert _pump_until(root, lambda: app.cam_previewing)
                app.notebook.select(app.other_tab)     # to the SLDEA tab
                _pump(root, 0.1)
                seen = _through_the_preflight(root, app, button)
                assert seen['dialog'], (button, p.mb.calls, app.sldea_lines)
                if not seen.get('grab'):
                    print("   (skipped: this display gives no grab)")
                    return
                # inside the pre-flight: held off, and no open
                assert seen['opens'] == [('open', 0)], (button, seen)
                assert not seen['previewing'], (button, seen)
                assert seen['splash'][1] == gui.CAM_OFF_DIALOG, (button, seen)
                if button == 'start':
                    assert app._sldea_running, (p.mb.calls, app.sldea_lines)
                    _pump(root, WATCH)                # into the run
                    assert not app.cam_previewing
                    assert _opens() == [('open', 0)], _FakeCam.log
                    assert app.cam_splash[1] == gui.CAM_OFF_SLDEA, (
                        app.cam_splash)
                    app._sldea_finished()             # the run ends
                else:
                    assert not app._sldea_running
                assert _pump_until(root, lambda: app.cam_previewing,
                                   secs=3.0), (button, app.cam_splash)
                _pump(root, WATCH)
                # sldea_run closed the preview's camera: one new open
                assert _opens() == [('open', 0)] * 2, (button, _FakeCam.log)
                assert not _camera_boxes(p), (button, p.mb.calls)
            finally:
                _close(root, app)


def test_a_resume_that_fails_is_tried_once_not_in_a_loop():
    """Once per clear (#393): a quiet start that fails puts the reason in
    the splash and is not tried again on that visit, by the watch or by
    the next hold-off that clears, even when the tab reported its opening
    twice. The next visit tries once more, as the tab-click start always
    has (how long a failed open holds the Tk thread is unmeasured, #393
    item 5)."""
    import tkinter as tk
    with _Patched() as p:
        _FakeCam.fail = "could not open camera index 0"
        reason = gui.CAM_OFF_NOT_FOUND.format(_FakeCam.fail)
        root, app = _app()
        if root is None:
            return
        try:
            # nothing in the way, and the tab says it opened twice
            _select_webcam(app)
            app.notebook.event_generate('<<NotebookTabChanged>>')
            assert _pump_until(root, lambda: len(_opens()) == 1, secs=2.0)
            _pump(root, 2 * WATCH)                    # two watch periods
            assert len(_opens()) == 1, _FakeCam.log
            assert app.cam_splash[1] == reason, app.cam_splash
            # held off on arrival, then cleared
            app.notebook.select(app.other_tab)
            _pump(root, 0.1)
            app._bg_busy.add('camera-ctrl')
            _select_webcam(app)
            _pump(root, WATCH)
            assert len(_opens()) == 1, _FakeCam.log
            app._bg_busy.discard('camera-ctrl')
            assert _pump_until(root, lambda: len(_opens()) == 2, secs=2.0)
            _pump(root, 2 * WATCH)
            assert len(_opens()) == 2, _FakeCam.log
            assert app.cam_splash[1] == reason, app.cam_splash
            # another hold-off comes and goes on this visit: no new try
            dialog = tk.Toplevel(root)
            dialog.grab_set()
            _pump(root, WATCH)
            dialog.grab_release()
            dialog.destroy()
            app._bg_busy.add('camera-ctrl')
            _pump(root, WATCH)
            app._bg_busy.discard('camera-ctrl')
            _pump(root, WATCH)
            assert len(_opens()) == 2, _FakeCam.log
            assert not app.cam_previewing
            assert p.mb.calls == [], p.mb.calls
        finally:
            _close(root, app)


def test_a_start_preview_that_fails_is_not_tried_again_quietly():
    """Start Preview, pressed while the tab-click start is held off, is
    that start's try. When its open fails, its dialog says so, and the
    watch does not try again when the hold-off clears (#393)."""
    with _Patched() as p:
        _FakeCam.fail = "could not open camera index 0"
        root, app = _app()
        if root is None:
            return
        try:
            app._bg_busy.add('camera-ctrl')           # held off on arrival
            _select_webcam(app)
            _pump(root, WATCH)
            assert _opens() == [], _FakeCam.log
            app.cam_toggle_preview()                  # Start Preview
            assert [c[0] for c in p.mb.calls] == ['showerror'], p.mb.calls
            app._bg_busy.discard('camera-ctrl')
            _pump(root, 2 * WATCH)
            assert len(_opens()) == 1, _FakeCam.log
            assert not app.cam_previewing
            assert len(p.mb.calls) == 1, p.mb.calls
        finally:
            _close(root, app)


def test_the_operators_stop_is_not_undone_when_a_blocker_clears():
    """Stop Preview means stopped for this visit: a hold-off that comes
    and goes after it (an adjustment's busy key, a dialog) does not start
    the preview again (#393)."""
    import tkinter as tk
    with _Patched() as p:
        root, app = _app()
        if root is None:
            return
        try:
            _select_webcam(app)
            assert _pump_until(root, lambda: app.cam_previewing)
            app.cam_toggle_preview()                  # Stop Preview
            app._bg_busy.add('camera-ctrl')           # e.g. Apply & Lock
            _pump(root, WATCH)
            app._bg_busy.discard('camera-ctrl')
            dialog = tk.Toplevel(root)
            dialog.grab_set()
            _pump(root, WATCH)
            dialog.grab_release()
            dialog.destroy()
            _pump(root, WATCH)
            assert not app.cam_previewing
            assert app.cam_splash[1] == gui.CAM_OFF_CLICK, app.cam_splash
            assert _opens() == [('open', 0)], _FakeCam.log
            assert p.mb.calls == [], p.mb.calls
        finally:
            _close(root, app)


def test_a_hold_off_that_clears_off_the_tab_waits_for_the_next_visit():
    """The resume is for the tab on screen: a run that ends while the
    operator is on another tab starts nothing, and the next visit starts
    the preview the usual way."""
    with _Patched() as p:
        root, app = _app()
        if root is None:
            return
        try:
            app._sldea_running = True
            _select_webcam(app)
            _pump(root, WATCH)
            app.notebook.select(app.other_tab)
            _pump(root, 0.1)
            app._sldea_running = False                # it ends off the tab
            _pump(root, WATCH)
            assert _opens() == [] and not app.cam_previewing, _FakeCam.log
            _select_webcam(app)
            assert _pump_until(root, lambda: app.cam_previewing)
            assert _opens() == [('open', 0)], _FakeCam.log
            assert p.mb.calls == [], p.mb.calls
        finally:
            _close(root, app)


def test_a_capture_or_adjustment_holds_the_start_off_with_no_dialog():
    cases = (
        ('timed', 'timed', None, gui.CAM_OFF_TIMED),
        ('sweep', 'sweep', None, gui.CAM_OFF_SWEEP),
        # Stop pressed: the worker is still finishing its step
        ('stopping', 'timed', 'alive', gui.CAM_OFF_TIMED),
        ('adjustment', None, 'camera-ctrl', gui.CAM_OFF_ADJUSTING),
    )
    for name, kind, extra, reason in cases:
        with _Patched() as p:
            root, app = _app()
            if root is None:
                return
            try:
                if kind is not None:
                    app._cam_seq_kind = kind
                    app.cam_seq_running = extra is None
                    app.cam_seq_thread = types.SimpleNamespace(
                        is_alive=lambda: True)
                if extra == 'camera-ctrl':
                    app._bg_busy.add('camera-ctrl')
                _select_webcam(app)
                _pump(root, 0.4)
                assert not app.cam_previewing, name
                assert _opens() == [], (name, _FakeCam.log)
                assert p.mb.calls == [], (name, p.mb.calls)
                assert app.cam_splash[1] == reason, (name, app.cam_splash)
            finally:
                _close(root, app)


def test_a_blocker_that_appears_before_the_delayed_start_still_holds():
    """The start waits CAM_AUTOSTART_DELAY_MS for the tab to paint. A
    capture or a run that takes the camera inside that window must still
    hold it off: the start checks again when it fires. The start is then
    still owed, and runs once that blocker clears (#393)."""
    with _Patched() as p:
        # wide enough that a slow update() on a busy desktop cannot run
        # the start in the same pass that scheduled it
        gui.CAM_AUTOSTART_DELAY_MS = 600
        root, app = _app()
        if root is None:
            return
        try:
            _select_webcam(app)
            assert _pump_until(root,
                               lambda: app._cam_autostart_job is not None)
            app._sldea_running = True              # e.g. Run, meanwhile
            _pump(root, 1.0)
            assert app._cam_autostart_job is None, "the start never fired"
            assert not app.cam_previewing and _opens() == [], _FakeCam.log
            assert p.mb.calls == [], p.mb.calls
            assert app.cam_splash[1] == gui.CAM_OFF_SLDEA, app.cam_splash
            app._sldea_running = False             # the run ends
            assert _pump_until(root, lambda: app.cam_previewing,
                               secs=3.0), app.cam_splash
            assert _opens() == [('open', 0)], _FakeCam.log
            assert p.mb.calls == [], p.mb.calls
        finally:
            _close(root, app)


def test_a_failed_open_goes_in_the_splash_and_the_button_still_asks():
    with _Patched() as p:
        _FakeCam.fail = "could not open camera index 0"
        root, app = _app()
        if root is None:
            return
        try:
            _select_webcam(app)
            assert _pump_until(root, lambda: len(_opens()) == 1), (
                "the tab-click start never tried the camera")
            _pump(root, 0.2)
            assert not app.cam_previewing
            assert p.mb.calls == [], p.mb.calls
            assert app.cam_splash[:2] == (
                gui.CAM_SPLASH_OFF,
                "Camera not found: could not open camera index 0"), (
                app.cam_splash)
            assert _shows_splash(app)
            # Start Preview keeps its dialog
            app.cam_toggle_preview()
            assert [c[0] for c in p.mb.calls] == ['showerror'], p.mb.calls
            assert "could not open camera index 0" in p.mb.calls[0][2]
            assert app.cam_splash[1].startswith("Camera not found")
            # Refresh finding cameras retires the stale reason
            app.cam_refresh_devices()
            assert app.cam_splash[1] == gui.CAM_OFF_CLICK, app.cam_splash
            # ...and a later good open clears it for good
            _FakeCam.fail = None
            app.cam_toggle_preview()
            assert app.cam_previewing and app._cam_open_error is None
        finally:
            _close(root, app)


def test_stopping_leaves_the_splash_over_the_dimmed_last_frame():
    with _Patched():
        root, app = _app()
        if root is None:
            return
        try:
            _select_webcam(app)
            assert _pump_until(root, lambda: app.cam_previewing
                               and app.cam_last_frame is not None)
            taken = app.cam_last_frame_at.strftime('%H:%M:%S')
            app.cam_toggle_preview()                       # Stop Preview
            _pump(root, 0.1)
            assert not app.cam_previewing
            headline, reason, stamp = app.cam_splash
            assert (headline, reason) == (gui.CAM_SPLASH_OFF,
                                          gui.CAM_OFF_CLICK), app.cam_splash
            # the stamp is the time of the frame the splash is over
            assert stamp == "Last frame taken " + taken, (stamp, taken)
            assert _shows_splash(app)
            # the frame is kept, dimmed: the fake frame is flat 200 gray
            r, g, b = app.cam_splash_img.getpixel((2, 2))
            want = round(200 * gui.CAM_SPLASH_DIM)
            assert abs(r - want) <= 2 and r == g == b, (r, g, b, want)
            assert app.cam_last_frame is not None, "the snapshot frame went"
        finally:
            _close(root, app)


def test_every_stop_path_gets_the_splash():
    """cam_stop_preview is what Stabilize, Auto-WB once, Auto-expose, the
    timed and stepped captures and an SLDEA run start all call; the splash
    is drawn after the caller has recorded what took the camera."""
    with _Patched():
        root, app = _app()
        if root is None:
            return
        try:
            _select_webcam(app)
            assert _pump_until(root, lambda: app.cam_previewing)
            # what _cam_start_timed does around its stop, in one callback
            app.cam_stop_preview()
            app.cam_seq_running = True
            app._cam_seq_kind = 'timed'
            app.cam_seq_thread = types.SimpleNamespace(is_alive=lambda: True)
            _pump(root, 0.1)
            assert app.cam_splash[1] == gui.CAM_OFF_TIMED, app.cam_splash
            assert _shows_splash(app)
        finally:
            _close(root, app)


def test_leaving_the_tab_stops_the_preview_unless_interval_capture_runs():
    with _Patched():
        root, app = _app()
        if root is None:
            return
        try:
            _select_webcam(app)
            assert _pump_until(root, lambda: app.cam_previewing)
            app.notebook.select(app.other_tab)
            _pump(root, 0.2)
            assert not app.cam_previewing, "leaving kept the preview on"
            # the Stop Preview button's stop: the device stays open, so
            # coming back resumes it without a second open
            assert app.cam is not None and app.cam.is_open
            assert ('close', 0) not in _FakeCam.log, _FakeCam.log
            _select_webcam(app)
            assert _pump_until(root, lambda: app.cam_previewing)
            assert _opens() == [('open', 0)], _FakeCam.log

            # interval capture needs the preview: leaving keeps it
            app.cam_interval_job = root.after(600000, lambda: None)
            app.notebook.select(app.other_tab)
            _pump(root, 0.2)
            assert app.cam_previewing, "leaving stopped interval capture's preview"
            # ...until the interval ends there
            app._cam_stop_interval()
            assert not app.cam_previewing
        finally:
            _close(root, app)


def test_the_leave_tab_switch_off_keeps_the_preview_running():
    with _Patched():
        gui.CAM_STOP_PREVIEW_ON_TAB_LEAVE = False
        root, app = _app()
        if root is None:
            return
        try:
            _select_webcam(app)
            assert _pump_until(root, lambda: app.cam_previewing)
            app.notebook.select(app.other_tab)
            _pump(root, 0.2)
            assert app.cam_previewing
        finally:
            _close(root, app)


def test_the_autostart_switch_off_is_click_to_start():
    """Off, nothing opens the camera by itself: not opening the tab, not
    a hold-off that clears on it, and not the end of a capture that
    stopped a preview started by hand (#393)."""
    with _Patched() as p:
        gui.CAM_AUTOSTART_ON_TAB = False
        root, app = _app()
        if root is None:
            return
        try:
            _select_webcam(app)
            _pump(root, 0.3)
            assert not app.cam_previewing and _opens() == []
            assert app.cam_splash[1] == gui.CAM_OFF_CLICK, app.cam_splash
            app._sldea_running = True
            _pump(root, WATCH)
            app._sldea_running = False
            _pump(root, WATCH)
            assert not app.cam_previewing and _opens() == [], _FakeCam.log
            app.cam_toggle_preview()                  # Start Preview
            assert app.cam_previewing
            # what a capture's start does: stop, then record it runs
            app.cam_stop_preview()
            app.cam_seq_running, app._cam_seq_kind = True, 'timed'
            _pump(root, WATCH)
            app.cam_seq_running = False               # ...and it ends
            _pump(root, WATCH)
            assert not app.cam_previewing, "the switch is off"
            assert _opens() == [('open', 0)], _FakeCam.log
            assert p.mb.calls == [], p.mb.calls
        finally:
            _close(root, app)


def test_a_camera_that_stops_sending_shows_no_frame():
    """`#48`'s dead camera: the preview kept its last image as if live."""
    with _Patched():
        gui.CAM_NO_FRAME_S = 0.2
        root, app = _app()
        if root is None:
            return
        try:
            _select_webcam(app)
            assert _pump_until(root, lambda: app.cam_splash is None
                               and app.cam_last_frame is not None)
            _FakeCam.blank = True
            assert _pump_until(root, lambda: app.cam_splash is not None,
                               secs=2.0), "no NO FRAME splash"
            assert app.cam_splash[:2] == (gui.CAM_SPLASH_NO_FRAME,
                                          gui.CAM_NO_FRAME_REASON)
            assert app.cam_previewing, "NO FRAME must not stop the preview"
            _FakeCam.blank = False
            assert _pump_until(root, lambda: app.cam_splash is None), (
                "a frame coming back did not clear NO FRAME")
        finally:
            _close(root, app)


def test_an_adjustment_resumes_the_preview_only_on_the_tab():
    """Stabilize, Auto-WB once and Auto-expose restart a preview they
    paused. Off the tab, the leave-tab rule wins; the next visit starts it."""
    with _Patched() as p:
        root, app = _app()
        if root is None:
            return
        try:
            app._cam_after_adjustment(True)           # on the Other tab
            _pump(root, 0.1)
            assert not app.cam_previewing and _opens() == []
            _select_webcam(app)
            assert _pump_until(root, lambda: app.cam_previewing)
            app.cam_stop_preview()
            app._cam_after_adjustment(True)           # on the Webcam tab
            assert app.cam_previewing
            assert p.mb.calls == []
        finally:
            _close(root, app)


def test_the_quiet_check_agrees_with_cam_owned_by_sldea():
    """_cam_sldea_holds_camera is _cam_owned_by_sldea without the box; if
    the two ever disagree, the tab-click start could take a run's camera."""
    with _Patched() as p:
        app = G.__new__(G)
        recorders = (None,
                     types.SimpleNamespace(reader_alive=lambda: True),
                     types.SimpleNamespace(reader_alive=lambda: False))
        for running in (False, True):
            for rec in recorders:
                app._sldea_running = running
                app._sldea_recorder = rec
                p.mb.calls.clear()
                quiet = app._cam_sldea_holds_camera()
                assert p.mb.calls == [], "the quiet check opened a box"
                loud = G._cam_owned_by_sldea(app)
                assert quiet == loud, (running, rec, quiet, loud)


def test_the_whole_app_keeps_both_tab_bindings():
    """The SLDEA tab binds <<NotebookTabChanged>> too (its camera line).
    In the real app both handlers run on every tab change."""
    with _Patched() as p:
        root = _root()
        if root is None:
            return
        G.auto_connect = lambda self: None     # no instrument hunt
        app = G(root)
        try:
            if not hasattr(app, 'cam_view'):
                print("   (skipped: no capture deps for the Webcam tab)")
                return
            seen = []
            app._sldea_cam_line_refresh = lambda: seen.append(1)
            _pump(root, 0.2)
            seen.clear()
            app.select_manual_tab('webcam')
            assert _pump_until(root, lambda: app.cam_previewing), (
                "the real app did not start the preview on its tab")
            assert seen, "the SLDEA camera line binding was clobbered"
            assert _opens() == [('open', 0)], _FakeCam.log
            app.select_manual_tab('sldea')
            _pump(root, 0.2)
            assert not app.cam_previewing
            assert len(seen) >= 2
            assert p.mb.calls == [], p.mb.calls
        finally:
            _close(root, app)


def _run():
    # Failures are collected, not fatal (`#280`); see run_tests.py.
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    failed = []
    for fn in fns:
        try:
            fn()
        except Exception:
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
        print(f"ok  {fn.__name__}")
    if not failed:
        print(f"\n{len(fns)} tests passed")
        return 0
    head = f"{len(failed)} of {len(fns)} tests failed"
    print(f"\n{head}")
    for name, tb in failed:
        print(f"===== FAIL {name} =====")
        print(tb.rstrip('\n'))
    print(f"===== end {head} =====")
    return 1


if __name__ == '__main__':
    raise SystemExit(_run())
