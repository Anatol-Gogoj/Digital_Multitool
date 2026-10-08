#!/usr/bin/env python3
"""The Webcam tab's Auto-set camera, its Advanced section and the focus
overlay, and the camera block a run writes into setup.txt (#400).

The tab showed every control the camera reports and needed up to four
presses, in an order it never stated, before a run had a locked setup. Now
the main view keeps exposure and gain (a run takes them from these boxes)
and one Auto-set camera button, which pins gain at its floor, finds the
exposure for a mid-gray picture, balances the white on the scene, and
writes and locks it all; everything else sits under Advanced, closed until
opened. The focus score is on by default, with a label about twice as
tall. setup.txt records the camera state the run stamps (owner decisions
2026-10-07: Auto-set redoes the white balance every time, and setup.txt
records as much as possible).

Headless apart from a Tk root: the camera is a model (a picture whose mean
follows the exposure and whose red and blue follow their balance), so no
test here opens a real camera. The tab is the real one, built by the real
builder (test_webcam_autostart's harness), and the run start is the real
sldea_run on the interlock suite's stub app.

Run: .venv/bin/python tests/test_webcam_autoset.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import os
import tempfile
import types

import gui
import sldea_profile
import webcam
import test_camera_controls as CC  # noqa: E402
import test_sldea_interlock as T  # noqa: E402
import test_webcam_autostart as WA  # noqa: E402

DFK_CONTROLS = webcam.parse_controls(CC.SAMPLE)
# a stale lock, as the bench had it before 2026-07-24 (red 204, gain 44)
STALE_LOCK = {'auto_exposure': 1, 'white_balance_automatic': 0,
              'exposure_time_absolute': 20, 'gain': 44, 'brightness': 240,
              'red_balance': 204, 'blue_balance': 104}


class _Scene:
    """The camera model: the picture's mean is 2 gray levels per exposure
    unit (clipped at 255), and red and blue follow their balance, gray at
    red 92 and blue 151. A grab with no trial controls is shot under the
    lock, as the real oneshot_rgb stamps it. Every grab's controls are
    kept, with None for a grab under the lock."""

    def __init__(self):
        self.calls = []
        self.black_from = None       # grab number from which red is black

    def oneshot(self, spec, count=2, controls=None):
        import numpy as np
        self.calls.append(None if controls is None else dict(controls))
        c = dict(webcam.LOCKED_CONTROLS if controls is None else controls)
        level = min(255.0, 2.0 * c.get('exposure_time_absolute', 20))
        r = level * c.get('red_balance', 92) / 92.0
        b = level * c.get('blue_balance', 151) / 151.0
        if self.black_from is not None and len(self.calls) >= self.black_from:
            r = 0.0
        frame = np.empty((4, 4, 3), np.float64)
        frame[..., 0], frame[..., 1], frame[..., 2] = r, level, b
        return frame


class _Camera:
    """The camera layer under the Webcam tab: the bench DFK's controls, a
    saved lock, the scene, and every stamp and save recorded."""

    NAMES = ('list_controls', 'load_camera_settings', 'v4l2_available',
             'oneshot_rgb', 'resolve_camera', 'apply_locked',
             'save_camera_settings', 'set_control', 'get_control')

    def __init__(self, saved=None):
        self.saved_lock = dict(STALE_LOCK if saved is None else saved)
        self.scene = _Scene()
        self.stamps = []
        self.saves = []
        self.fail_stamp = False
        self.reached = None          # how many controls a stamp sets

    def __enter__(self):
        self.restore = {n: getattr(webcam, n) for n in self.NAMES}
        self.lock_before = dict(webcam.LOCKED_CONTROLS)

        def apply_locked(device, exclude=None):
            self.stamps.append(dict(webcam.LOCKED_CONTROLS))
            if self.fail_stamp:
                raise RuntimeError("the camera went away")
            if self.reached is not None:
                return self.reached
            return len(webcam.LOCKED_CONTROLS)

        def save(controls, path=None):
            self.saves.append(dict(controls))
            return 'nowhere/camera_controls.json'

        webcam.list_controls = lambda device: [dict(c) for c in DFK_CONTROLS]
        webcam.load_camera_settings = lambda path=None: dict(self.saved_lock)
        webcam.v4l2_available = lambda: True
        webcam.oneshot_rgb = self.scene.oneshot
        webcam.resolve_camera = lambda idx: {
            'kind': 'bayer', 'device': f'/dev/video{idx}', 'fourcc': 'RGGB',
            'w': 4, 'h': 4}
        webcam.apply_locked = apply_locked
        webcam.save_camera_settings = save
        webcam.set_control = lambda device, name, value: True
        webcam.get_control = lambda device, name: None
        return self

    def __exit__(self, *exc):
        for n, v in self.restore.items():
            setattr(webcam, n, v)
        webcam.set_locked(self.lock_before)
        return False


def _tab():
    """(root, app) with the real Webcam tab built on the DFK's controls;
    (None, None) when there is no display or no capture deps."""
    root, app = WA._app()
    if root is None:
        return None, None
    app._cam_device = lambda: '/dev/video0'
    return root, app


def _box(app, name):
    return app.camctl_rows[name][1].get()


def _press(root, app, method):
    """Press a camera button and let its background job finish."""
    method()
    done = WA._pump_in_mainloop(
        root, lambda: 'camera-ctrl' not in app._bg_busy, secs=10)
    assert done, "the camera job never finished"
    WA._pump(root, 0.1)


def _descends(widget, ancestor):
    w = widget
    while w is not None:
        if w is ancestor:
            return True
        w = w.master
    return False


def test_the_main_view_keeps_what_a_run_uses_and_advanced_starts_closed():
    with WA._Patched() as p, _Camera():
        root, app = _tab()
        if root is None:
            return
        try:
            WA._select_webcam(app)
            WA._pump(root, 0.2)
            rows = app.camctl_rows
            assert set(rows) == {c['name'] for c in DFK_CONTROLS}, rows
            for name in gui.CAM_MAIN_CONTROLS:
                assert _descends(rows[name][1], app.camctl_main), name
            # exposure first, though the camera reports gain first
            col = {name: int(rows[name][1].master.grid_info()['column'])
                   for name in gui.CAM_MAIN_CONTROLS}
            assert col['exposure_time_absolute'] < col['gain'], col
            assert app.cam_exposure is rows['exposure_time_absolute'][1]
            assert app.cam_gain is rows['gain'][1]
            others = set(rows) - set(gui.CAM_MAIN_CONTROLS)
            for name in others:
                w = rows[name][1]
                if not hasattr(w, 'master'):          # a Checkbutton's var
                    continue
                assert _descends(w, app.cam_adv_frame), name
            # Advanced is closed: not packed, the main view's button shows
            assert app.cam_adv_frame.winfo_manager() == ''
            assert not app.cam_adv_shown
            assert app.cam_adv_btn.cget('text') == gui.CAM_ADVANCED_SHOW
            assert app.cam_autoset_btn.winfo_ismapped()
            assert app.cam_autoset_btn.cget('text') == gui.CAM_AUTOSET_TEXT
            # Apply & Lock sits beside the boxes it locks, in view with
            # Advanced closed, and is the tab's only one (owner decision
            # 2026-10-08)
            assert app.cam_apply_btn.cget('text') == "🔒 Apply & Lock"
            assert app.cam_apply_btn.winfo_ismapped()
            assert app.cam_apply_btn.master is app.camctl_main.master
            assert not _descends(app.cam_apply_btn, app.cam_adv_frame)
            everything = [app._cam_tab]
            applies = []
            while everything:
                w = everything.pop()
                everything.extend(w.winfo_children())
                try:
                    if w.cget('text') == "🔒 Apply & Lock":
                        applies.append(w)
                except Exception:
                    pass
            assert applies == [app.cam_apply_btn], applies
            # the single steps and Read camera are all under Advanced
            labels = {}
            stack = [app.cam_adv_frame]
            while stack:
                w = stack.pop()
                stack.extend(w.winfo_children())
                try:
                    labels[w.cget('text')] = w
                except Exception:
                    pass
            for text in ("Read camera", "Auto-expose", "Auto-WB once",
                         "Stabilize (pin gain 0)"):
                assert text in labels, (text, sorted(labels))
            # ...and the toggle opens and closes it
            app._cam_toggle_advanced()
            WA._pump(root, 0.1)
            assert app.cam_adv_frame.winfo_manager() == 'pack'
            assert app.cam_adv_btn.cget('text') == gui.CAM_ADVANCED_HIDE
            assert labels["Read camera"].winfo_ismapped()
            app._cam_toggle_advanced()
            WA._pump(root, 0.1)
            assert app.cam_adv_frame.winfo_manager() == ''
            assert app.cam_adv_btn.cget('text') == gui.CAM_ADVANCED_SHOW
            assert WA._camera_boxes(p) == []
        finally:
            WA._close(root, app)
            WA._reap()


def test_auto_set_runs_its_steps_in_order_and_locks_what_it_found():
    with WA._Patched() as p, _Camera() as cam:
        root, app = _tab()
        if root is None:
            return
        try:
            assert webcam.LOCKED_CONTROLS == STALE_LOCK
            _press(root, app, app.cam_auto_set)
            calls = cam.scene.calls
            assert None not in calls, "a trial was shot under the lock"
            # 1: the exposure trials, gain at its floor, from short to long,
            # judged on green, which the stale red balance does not touch
            trials, wb = calls[:7], calls[7:]
            assert [c['exposure_time_absolute'] for c in trials] == \
                [16, 24, 32, 40, 50, 64, 80], trials
            assert all(c['gain'] == webcam.GAIN_FLOOR for c in trials)
            # 2: the white balance, shot at the exposure just found, from
            # the panel's balance toward gray
            assert 1 <= len(wb) <= webcam.GRAY_WORLD_ROUNDS, wb
            assert all(c['exposure_time_absolute'] == 80 for c in wb), wb
            assert all(c['white_balance_automatic'] == 0 for c in wb), wb
            assert (wb[0]['red_balance'], wb[0]['blue_balance']) == \
                (204, 104), wb[0]
            # 3: the lock is what was found, stamped once and saved
            lock = dict(webcam.LOCKED_CONTROLS)
            assert lock['exposure_time_absolute'] == 80, lock
            assert lock['gain'] == webcam.GAIN_FLOOR, lock
            assert abs(lock['red_balance'] - 92) <= 2, lock
            assert abs(lock['blue_balance'] - 151) <= 3, lock
            assert lock['auto_exposure'] == 1, lock
            assert lock['white_balance_automatic'] == 0, lock
            assert lock['brightness'] == 240, lock     # kept from the panel
            assert cam.stamps == [lock], cam.stamps
            assert cam.saves == [lock], cam.saves
            # the boxes now say what is locked, so the run (boxes) and the
            # preview (lock) see the same picture
            assert _box(app, 'exposure_time_absolute') == '80'
            assert _box(app, 'gain') == str(webcam.GAIN_FLOOR)
            assert _box(app, 'red_balance') == str(lock['red_balance'])
            assert _box(app, 'blue_balance') == str(lock['blue_balance'])
            status = app.cam_sensor_status.cget('text')
            assert status.startswith("🔒 locked: exposure 80, gain 0, "
                                     f"red {lock['red_balance']}, blue "
                                     f"{lock['blue_balance']}"), status
            assert 'saved for next start' in status, status
            assert str(app.cam_sensor_status.cget('foreground')) == \
                gui.CAM_STATUS_DONE
            assert WA._camera_boxes(p) == []
            assert not [c for c in p.mb.calls if c[0] == 'showerror'], \
                p.mb.calls
        finally:
            WA._close(root, app)
            WA._reap()


def test_a_failing_step_names_it_and_leaves_the_previous_lock():
    def no_picture(cam):
        cam.scene.oneshot = lambda spec, count=2, controls=None: None
        webcam.oneshot_rgb = cam.scene.oneshot

    def black_red(cam):
        cam.scene.black_from = 8         # the first white balance picture

    def stamp_fails(cam):
        cam.fail_stamp = True

    for setup, step in ((no_picture, 'finding the exposure'),
                        (black_red, 'balancing the white'),
                        (stamp_fails, 'locking')):
        with WA._Patched() as p, _Camera() as cam:
            root, app = _tab()
            if root is None:
                return
            try:
                setup(cam)
                before = {name: _box(app, name) for name in app.camctl_rows
                          if app.camctl_rows[name][0] == 'int'}
                _press(root, app, app.cam_auto_set)
                assert webcam.LOCKED_CONTROLS == STALE_LOCK, (
                    step, webcam.LOCKED_CONTROLS)
                assert not cam.saves, (step, cam.saves)
                after = {name: _box(app, name) for name in before}
                assert after == before, (step, before, after)
                status = app.cam_sensor_status.cget('text')
                assert status.startswith(f"Auto-set stopped while {step}:"), \
                    (step, status)
                assert 'previous lock is unchanged' in status, status
                assert str(app.cam_sensor_status.cget('foreground')) == \
                    gui.CAM_STATUS_WARN
                [box] = [c for c in p.mb.calls if c[0] == 'showerror']
                assert box[1] == "Auto-set camera" and step in box[2], box
                assert 'previous lock is unchanged' in box[2], box
            finally:
                WA._close(root, app)
                WA._reap()


def test_a_lock_that_reached_no_control_is_a_failure():
    """Review of #400: Apply & Lock and Auto-set's last step count the
    controls the lock set on the camera, and a count of 0 was reported as
    a success ("locked 0 controls; saved for next start"): the previous
    lock was replaced, in the app and in the file the next start restores,
    by one that had reached nothing. A count of 0 is now a failure that
    says why, and the previous lock stays."""
    # Apply & Lock on a panel the camera reported no controls for: the
    # empty lock cleared the previous one and was saved over it
    with WA._Patched() as p, _Camera() as cam:
        webcam.list_controls = lambda device: []
        root, app = _tab()
        if root is None:
            return
        try:
            assert app.camctl_rows == {}
            webcam.set_locked(STALE_LOCK)
            _press(root, app, app.cam_apply_controls)
            assert webcam.LOCKED_CONTROLS == STALE_LOCK, \
                webcam.LOCKED_CONTROLS
            assert not cam.saves, cam.saves
            status = app.cam_sensor_status.cget('text')
            assert status.startswith("Nothing locked: the camera reported "
                                     "no controls"), status
            assert 'Read camera' in status, status
            assert status.endswith("The previous lock is unchanged."), \
                status
            assert str(app.cam_sensor_status.cget('foreground')) == \
                gui.CAM_STATUS_WARN
            [box] = [c for c in p.mb.calls if c[0] == 'showerror']
            assert box[1] == "Camera", box
            assert box[2].startswith("Nothing locked: the camera reported "
                                     "no controls"), box
            assert 'previous lock is unchanged' in box[2], box
        finally:
            WA._close(root, app)
            WA._reap()
    # Apply & Lock and Auto-set when no control reached the camera
    for press, start in (('cam_apply_controls', "Nothing locked: "),
                         ('cam_auto_set', "Auto-set stopped while locking: ")):
        with WA._Patched() as p, _Camera() as cam:
            root, app = _tab()
            if root is None:
                return
            try:
                assert webcam.LOCKED_CONTROLS == STALE_LOCK
                app._set_entry(app.cam_exposure, 31)    # typed, not locked
                before = {name: _box(app, name) for name in app.camctl_rows
                          if app.camctl_rows[name][0] == 'int'}
                cam.reached = 0
                _press(root, app, getattr(app, press))
                assert webcam.LOCKED_CONTROLS == STALE_LOCK, (
                    press, webcam.LOCKED_CONTROLS)
                assert not cam.saves, (press, cam.saves)
                after = {name: _box(app, name) for name in before}
                assert after == before, (press, before, after)
                status = app.cam_sensor_status.cget('text')
                assert status.startswith(
                    start + "none of the 7 controls reached the camera at "
                            "/dev/video0"), (press, status)
                assert 'previous lock is unchanged' in status, status
                assert str(app.cam_sensor_status.cget('foreground')) == \
                    gui.CAM_STATUS_WARN
                [box] = [c for c in p.mb.calls if c[0] == 'showerror']
                assert 'none of the 7 controls reached the camera' in \
                    box[2], box
                assert 'previous lock is unchanged' in box[2], box
                if press == 'cam_auto_set':
                    # a failed Auto-set does not start an off preview
                    assert not app.cam_previewing
            finally:
                WA._close(root, app)
                WA._reap()


def test_auto_set_refuses_while_a_run_or_another_adjustment_has_the_camera():
    with WA._Patched() as p, _Camera() as cam:
        root, app = _tab()
        if root is None:
            return
        try:
            # the run holds the camera before the tab is opened, so the
            # tab's own start (#375) is held off too
            app._sldea_running = True
            WA._select_webcam(app)
            WA._pump(root, 0.6)
            app.cam_auto_set()
            WA._pump(root, 0.2)
            assert [c[1] for c in p.mb.calls] == [
                "Camera in use — SLDEA run"], p.mb.calls
            assert cam.scene.calls == [] and cam.saves == []
            assert not app.cam_previewing and WA._opens() == [], \
                WA._FakeCam.log
            app._sldea_running = False
            app._bg_busy.add('camera-ctrl')
            app.cam_auto_set()
            WA._pump(root, 0.2)
            assert cam.scene.calls == [] and cam.saves == []
            status = app.cam_sensor_status.cget('text')
            assert 'another camera adjustment is still running' in status, \
                status
            assert webcam.LOCKED_CONTROLS == STALE_LOCK
        finally:
            app._bg_busy.discard('camera-ctrl')
            WA._close(root, app)
            WA._reap()


def _preview_stopped_by_the_operator(root, app):
    """The Webcam tab on screen with its preview off: opened (the tab
    starts its preview, #375), then stopped with Start/Stop Preview."""
    WA._select_webcam(app)
    WA._pump_until(root, lambda: app.cam_previewing, 3.0)
    if app.cam_previewing:
        app.cam_toggle_preview()
    WA._pump(root, 0.2)
    assert not app.cam_previewing


def test_auto_set_shows_its_result_even_when_the_preview_was_off():
    """Owner decision 2026-10-08: Auto-set starts the preview at its end,
    also when it was off before, so the operator sees the result. A failed
    Auto-set leaves an off preview off: one error box, not a second one
    from a camera that may have gone."""
    with WA._Patched() as p, _Camera():
        root, app = _tab()
        if root is None:
            return
        try:
            _preview_stopped_by_the_operator(root, app)
            opens = len(WA._opens())
            _press(root, app, app.cam_auto_set)
            assert app.cam_previewing, "Auto-set left the preview off"
            assert len(WA._opens()) == opens + 1, WA._FakeCam.log
            assert not [c for c in p.mb.calls if c[0] == 'showerror'], \
                p.mb.calls
        finally:
            WA._close(root, app)
            WA._reap()
    with WA._Patched() as p, _Camera() as cam:
        root, app = _tab()
        if root is None:
            return
        try:
            _preview_stopped_by_the_operator(root, app)
            cam.scene.oneshot = lambda spec, count=2, controls=None: None
            webcam.oneshot_rgb = cam.scene.oneshot
            _press(root, app, app.cam_auto_set)
            assert not app.cam_previewing
            assert [c[1] for c in p.mb.calls] == ["Auto-set camera"], \
                p.mb.calls
        finally:
            WA._close(root, app)
            WA._reap()


def test_stabilize_and_auto_set_are_one_search():
    """Owner decision 2026-10-08: Stabilize uses Auto-set's own exposure
    search (webcam.find_exposure, judged on the green channel), so the two
    cannot pick different exposures. Under the stale balance both land on
    80; a whole-mean search would stop at 64 there."""
    with WA._Patched(), _Camera():
        root, app = _tab()
        if root is None:
            return
        real = webcam.find_exposure
        found = []

        def spy(spec, base, *a, **kw):
            found.append(real(spec, base, *a, **kw))
            return found[-1]

        webcam.find_exposure = spy
        try:
            _press(root, app, app.cam_stabilize)
            stabilized = _box(app, 'exposure_time_absolute')
            _press(root, app, app.cam_auto_set)
            assert len(found) == 2 and found[0] == found[1], found
            assert stabilized == '80', stabilized
            assert webcam.LOCKED_CONTROLS['exposure_time_absolute'] == 80
        finally:
            webcam.find_exposure = real
            WA._close(root, app)
            WA._reap()


def test_the_single_steps_search_the_scene_not_the_lock():
    """Stabilize and Auto-WB once used to shoot every trial under the lock
    (oneshot_rgb stamped it), so with the stale lock in place Stabilize
    filled in the shortest exposure and Auto-WB once kept red 204."""
    with WA._Patched(), _Camera() as cam:
        root, app = _tab()
        if root is None:
            return
        try:
            _press(root, app, app.cam_stabilize)
            assert _box(app, 'exposure_time_absolute') == '80'
            assert _box(app, 'gain') == str(webcam.GAIN_FLOOR)
            assert None not in cam.scene.calls
            # Stabilize fills the boxes and locks nothing, as before
            assert webcam.LOCKED_CONTROLS == STALE_LOCK
            _press(root, app, app.cam_grey_world)
            red = int(_box(app, 'red_balance'))
            blue = int(_box(app, 'blue_balance'))
            assert abs(red - 92) <= 2 and abs(blue - 151) <= 3, (red, blue)
            assert webcam.LOCKED_CONTROLS == STALE_LOCK
        finally:
            WA._close(root, app)
            WA._reap()


def test_a_value_typed_in_the_main_view_and_not_locked_is_named():
    with WA._Patched(), _Camera():
        root, app = _tab()
        if root is None:
            return
        try:
            WA._select_webcam(app)
            WA._pump(root, 0.2)
            box = app.cam_exposure
            box.focus_force()
            box.delete(0, 'end')
            box.insert(0, '25')
            box.event_generate('<KeyRelease>')
            WA._pump(root, 0.1)
            status = app.cam_sensor_status.cget('text')
            assert status.startswith(
                "Typed, not locked: exposure 25 (locked 20)"), status
            assert 'Auto-set camera' in status and 'Apply & Lock' in status
            assert str(app.cam_sensor_status.cget('foreground')) == \
                gui.CAM_STATUS_WARN
            box.delete(0, 'end')
            box.insert(0, '20')
            box.event_generate('<KeyRelease>')
            WA._pump(root, 0.1)
            assert app.cam_sensor_status.cget('text') == '', \
                app.cam_sensor_status.cget('text')
            # the Apply & Lock beside the boxes locks what they say, with
            # Advanced closed (owner decision 2026-10-08)
            box.delete(0, 'end')
            box.insert(0, '31')
            box.event_generate('<KeyRelease>')
            assert not app.cam_adv_shown
            app.cam_apply_btn.invoke()
            assert WA._pump_in_mainloop(
                root, lambda: 'camera-ctrl' not in app._bg_busy, secs=10)
            WA._pump(root, 0.1)
            assert webcam.LOCKED_CONTROLS['exposure_time_absolute'] == 31, \
                webcam.LOCKED_CONTROLS
            status = app.cam_sensor_status.cget('text')
            assert status.startswith("🔒 locked"), status
            box.event_generate('<KeyRelease>')
            WA._pump(root, 0.1)
            assert app.cam_sensor_status.cget('text') == status, \
                "a locked value was named as not locked"
        finally:
            WA._close(root, app)
            WA._reap()


def test_the_focus_score_is_on_by_default_and_its_label_is_twice_as_tall():
    from PIL import Image, ImageDraw
    with WA._Patched(), _Camera():
        root, app = _tab()
        if root is None:
            return
        try:
            assert app.cam_focus_var.get() is True
        finally:
            WA._close(root, app)
            WA._reap()
    old = ImageDraw.Draw(Image.new('RGB', (10, 10))).textbbox(
        (6, 4), "focus 1234  (higher = sharper)")
    old_h = old[3] - old[1]                  # 11 px in Pillow's own font
    img = Image.new('RGB', (640, 480), (128, 128, 128))
    height = gui.draw_focus_overlay(img, 1234)
    assert height >= 2 * old_h - 1, (height, old_h)
    # Tol cyan over a black under-stroke, on the circle and in the label
    cx, cy = 320, 240
    r = int(webcam.FOCUS_AOI_RADIUS_FRAC * 480)
    cyan = tuple(int(gui.sldea_liveview.TOL_CYAN[i:i + 2], 16)
                 for i in (1, 3, 5))
    assert img.getpixel((cx + r - 1, cy)) == cyan, img.getpixel((cx + r - 1,
                                                                 cy))
    label = [img.getpixel((x, y)) for x in range(6, 300)
             for y in range(4, 4 + height)]
    assert cyan in label and (0, 0, 0) in label
    # a picture too narrow for the label shrinks it instead of cutting it
    small = Image.new('RGB', (200, 150))
    assert 0 < gui.draw_focus_overlay(small, 1234) < height


def test_sldea_run_hands_the_worker_the_camera_block():
    """The camera block is built on the Tk thread in sldea_run, from the
    lock the run stamps and the camera the pre-flight found, and the
    worker writes it into setup.txt as handed."""
    dfk = {'kind': 'bayer', 'device': '/dev/video0', 'fourcc': 'RGGB',
           'w': 1920, 'h': 1080, 'frame': (1920, 1080)}
    saved = dict(webcam.LOCKED_CONTROLS)
    try:
        webcam.set_locked({'brightness': 240, 'red_balance': 92,
                           'blue_balance': 151})
        mb = T._MB({'No film thickness specified': True})
        with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
            app = T._App(tmp, real_worker=True)
            app._sldea_cam_defaults = types.MethodType(
                gui.InstrumentControlGUI._sldea_cam_defaults, app)
            app.on_preflight = lambda: setattr(app, '_sldea_preflight_camera',
                                               dfk)
            app.sldea_run()
            assert app.worker_done.wait(30), app.lines
            T._assert_clean_run(app)
            rec = app.worker_kw['cam_record']
            want = sldea_profile.camera_record(
                6, 60, gui.sldea_run_lock(webcam.LOCKED_CONTROLS, 6, 60),
                camera=dfk, defaults=['exposure', 'gain'])
            assert rec == want, (rec, want)
            assert "Camera device: /dev/video0" in rec.splitlines()
            assert rec.splitlines()[0].startswith(
                "exposure 6, gain 60, white balance manual, red 92, blue "
                "151"), rec
            import sldea_edge
            health = sldea_edge._health_setup(os.path.join(tmp, 'RUN'))
            assert health['camera'] == rec.splitlines()[0], health
            app.root.run_pending()
        # a pre-flight that does not report a camera leaves it unknown,
        # never the camera an earlier run found
        mb = T._MB({'No film thickness specified': True})
        with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
            app = T._App(tmp)
            app._sldea_cam_defaults = types.MethodType(
                gui.InstrumentControlGUI._sldea_cam_defaults, app)
            app._sldea_preflight_camera = dfk          # stale
            app.sldea_run()
            assert app.worker_done.wait(30), app.lines
            rec = app.worker_kw['cam_record']
            assert (f"Camera device: {sldea_profile.CAMERA_NOT_KNOWN}"
                    in rec.splitlines()), rec
            app.root.run_pending()
    finally:
        webcam.set_locked(saved)


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
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
