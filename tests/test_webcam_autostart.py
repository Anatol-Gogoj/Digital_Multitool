#!/usr/bin/env python3
"""The Webcam tab starts its preview when opened, and says when it is off.

`#375`: the preview started only from the Start Preview button, and a
stopped preview left its last frame on screen, looking exactly like a live
one. Now opening the tab starts the preview through a start path that never
opens a dialog, a stopped preview shows a large PREVIEW OFF with the reason
over its dimmed last frame (or on black), and leaving the tab stops the
preview unless interval capture needs it (gui.CAM_STOP_PREVIEW_ON_TAB_LEAVE,
an open owner question).

Headless apart from a Tk root: the camera, the device scan and the dialogs
are stubbed, so no test here opens a real camera. Most tests build only the
real Webcam tab into a two-tab notebook; one builds the whole app, to check
the tab's binding lives beside the SLDEA tab's.

Run: .venv/bin/python tests/test_webcam_autostart.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import queue
import time
import types

import gui
import webcam

G = gui.InstrumentControlGUI


class _MB:
    """messagebox stub: records every call, answers every question No."""

    def __init__(self):
        self.calls = []

    def _ask(self, name, title, msg='', **kw):
        self.calls.append((name, title, msg))
        return False

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
        self.mb = gui.messagebox = _MB()
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


def _opens():
    return [e for e in _FakeCam.log if e[0] == 'open']


def _select_webcam(app):
    app.notebook.select(app._cam_tab)


def _shows_splash(app):
    """cam_view is showing the splash image, sized as _cam_show sizes."""
    v = app.cam_view
    return (app.cam_photo is not None
            and str(v.cget('image')) == str(app.cam_photo)
            and int(v.cget('width')) == 0 and int(v.cget('height')) == 0
            and app.cam_splash_img is not None)


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
    the run ends the reason updates by itself while the tab is shown."""
    for holder in ('run', 'recorder'):
        with _Patched() as p:
            root, app = _app()
            if root is None:
                return
            try:
                if holder == 'run':
                    app._sldea_running = True
                else:
                    app._sldea_recorder = types.SimpleNamespace(
                        reader_alive=lambda: True)
                _select_webcam(app)
                _pump(root, 0.4)
                assert not app.cam_previewing, holder
                assert _opens() == [], (holder, _FakeCam.log)
                assert p.mb.calls == [], (holder, p.mb.calls)
                assert app.cam_splash[:2] == (gui.CAM_SPLASH_OFF,
                                              gui.CAM_OFF_SLDEA), app.cam_splash
                assert _shows_splash(app)
                # the run ends while the operator watches the tab
                app._sldea_running = False
                app._sldea_recorder = None
                assert _pump_until(
                    root, lambda: app.cam_splash[1] == gui.CAM_OFF_CLICK,
                    secs=2.0), app.cam_splash
                assert _opens() == [], "the watch must not start the preview"
            finally:
                _close(root, app)


def test_a_modal_dialog_holds_the_start_off():
    """The SLDEA camera pre-flight is a grabbed dialog. By then sldea_run
    has closed the preview's camera for the run, and _sldea_running is
    not set until Start, so the run check alone does not see it. A grab
    stops the pointer, not the keyboard, so the tab can still be opened
    (Ctrl+Tab): no open while any dialog holds the grab, and the splash
    says why. Closing the dialog does not start the preview by itself."""
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
            _pump(root, 0.4)
            assert not app.cam_previewing
            assert _opens() == [], _FakeCam.log
            assert p.mb.calls == [], p.mb.calls
            assert app.cam_splash[1] == gui.CAM_OFF_DIALOG, app.cam_splash
            dialog.grab_release()
            dialog.destroy()
            assert _pump_until(
                root, lambda: app.cam_splash[1] == gui.CAM_OFF_CLICK,
                secs=2.0), app.cam_splash
            assert _opens() == [], "closing the dialog must not open it"
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
    hold it off: the start checks again when it fires."""
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
    with _Patched():
        gui.CAM_AUTOSTART_ON_TAB = False
        root, app = _app()
        if root is None:
            return
        try:
            _select_webcam(app)
            _pump(root, 0.3)
            assert not app.cam_previewing and _opens() == []
            assert app.cam_splash[1] == gui.CAM_OFF_CLICK, app.cam_splash
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
