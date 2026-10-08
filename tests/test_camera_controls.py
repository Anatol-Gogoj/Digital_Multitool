#!/usr/bin/env python3
"""Headless tests for the camera-control lock layer (no camera).

Run: .venv/bin/python tests/test_camera_controls.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import os
import shutil
import tempfile

import webcam

# the exact --list-ctrls-menus output of the bench DFK 37BUX250 (2026-07-24)
SAMPLE = """
User Controls

                     brightness 0x00980900 (int)    : min=0 max=4095 step=1 default=240 value=240
        white_balance_automatic 0x0098090c (bool)   : default=1 value=0
                    red_balance 0x0098090e (int)    : min=0 max=255 step=1 default=64 value=204
                   blue_balance 0x0098090f (int)    : min=0 max=255 step=1 default=64 value=104
                           gain 0x00980913 (int)    : min=0 max=480 step=1 default=0 value=44

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=1
\t\t\t\t1: Manual Mode
\t\t\t\t3: Aperture Priority Mode
         exposure_time_absolute 0x009a0902 (int)    : min=1 max=40000 step=1 default=3 value=20
"""


def test_parse_controls_real_output():
    ctrls = webcam.parse_controls(SAMPLE)
    byname = {c['name']: c for c in ctrls}
    assert set(byname) == {'brightness', 'white_balance_automatic',
                           'red_balance', 'blue_balance', 'gain',
                           'auto_exposure', 'exposure_time_absolute'}
    assert byname['brightness']['min'] == 0
    assert byname['brightness']['max'] == 4095
    assert byname['gain']['value'] == 44
    assert byname['white_balance_automatic']['type'] == 'bool'
    assert byname['auto_exposure']['type'] == 'menu'
    assert byname['auto_exposure']['menu'] == {1: 'Manual Mode',
                                               3: 'Aperture Priority Mode'}
    assert byname['exposure_time_absolute']['max'] == 40000


def test_apply_locked_orders_autos_first():
    calls = []
    orig = webcam.set_control
    webcam.set_control = lambda dev, name, val: calls.append((name, val))
    try:
        webcam.set_locked({'red_balance': 92, 'auto_exposure': 1,
                           'exposure_time_absolute': 20,
                           'white_balance_automatic': 0})
        n = webcam.apply_locked('/dev/videoX')
        assert n == 4
        names = [c[0] for c in calls]
        # both autos land before any dependent value
        assert names.index('auto_exposure') < names.index(
            'exposure_time_absolute')
        assert names.index('white_balance_automatic') < names.index(
            'red_balance')
    finally:
        webcam.set_control = orig
        webcam.set_locked({})


def test_apply_locked_noop_when_unlocked():
    webcam.set_locked({})
    assert webcam.apply_locked('/dev/videoX') == 0


def test_apply_locked_can_exclude_gain():
    # The live-preview re-stamp skips 'gain' (firmware AGC overrides it and
    # re-writing just flickers) but must still hold everything else.
    calls = []
    orig = webcam.set_control
    webcam.set_control = lambda dev, name, val: calls.append(name)
    try:
        webcam.set_locked({'gain': 44, 'exposure_time_absolute': 20,
                           'white_balance_automatic': 0, 'red_balance': 92})
        n = webcam.apply_locked('/dev/videoX', exclude={'gain'})
        assert 'gain' not in calls
        assert 'exposure_time_absolute' in calls and 'red_balance' in calls
        assert n == 3
    finally:
        webcam.set_control = orig
        webcam.set_locked({})


def test_settings_persist_roundtrip():
    d = tempfile.mkdtemp(prefix='camctl_')
    try:
        path = os.path.join(d, 'sub', 'camera_controls.json')
        webcam.save_camera_settings({'gain': 44, 'red_balance': 92},
                                    path=path)
        back = webcam.load_camera_settings(path=path)
        assert back == {'gain': 44, 'red_balance': 92}
        assert webcam.load_camera_settings(
            path=os.path.join(d, 'missing.json')) == {}
    finally:
        shutil.rmtree(d)


def test_save_falls_back_when_primary_unwritable():
    # A root-owned ~/.local/share/scpi_control (installer artefact) must not
    # break persistence: save lands in the fallback, load finds it there.
    #
    # The unwritable parent is faked by NOT BEING A DIRECTORY rather than by
    # chmod, which Windows ignores on directories -- that is why this case
    # was long filed as an environmental failure (2026-08-09). webcam.py:388
    # catches plain OSError, so the FileExistsError/NotADirectoryError this
    # raises lands in the same branch a permission denial would.
    # The root-owned cause itself stays POSIX-only; the FALLBACK CHAIN is
    # what this exercises, and it is exercised identically.
    d = tempfile.mkdtemp(prefix='camctl_fb_')
    ro = os.path.join(d, 'ro')
    open(ro, 'wb').close()                    # unwritable "primary" parent
    prim_bak = webcam.CAMERA_SETTINGS_PATH
    fall_bak = webcam.CAMERA_SETTINGS_FALLBACK
    webcam.CAMERA_SETTINGS_PATH = os.path.join(ro, 'sub', 'cam.json')
    webcam.CAMERA_SETTINGS_FALLBACK = os.path.join(d, 'cache', 'cam.json')
    try:
        saved = webcam.save_camera_settings({'gain': 7})
        assert saved == webcam.CAMERA_SETTINGS_FALLBACK, saved
        assert webcam.load_camera_settings() == {'gain': 7}
    finally:
        webcam.CAMERA_SETTINGS_PATH = prim_bak
        webcam.CAMERA_SETTINGS_FALLBACK = fall_bak
        shutil.rmtree(d, ignore_errors=True)


def test_a_stale_primary_never_shadows_a_newer_fallback():
    """2026-10-05: with a readable but unwritable primary (the root-owned
    installer directory) holding an OLD lock, every save lands in the
    fallback, yet load read the primary first -- so each start and each
    Webcam-panel rebuild brought the old exposure back. The newer file
    must win, whichever location it is in."""
    import time
    d = tempfile.mkdtemp(prefix='camctl_stale_')
    prim_bak = webcam.CAMERA_SETTINGS_PATH
    fall_bak = webcam.CAMERA_SETTINGS_FALLBACK
    webcam.CAMERA_SETTINGS_PATH = os.path.join(d, 'share', 'cam.json')
    webcam.CAMERA_SETTINGS_FALLBACK = os.path.join(d, 'cache', 'cam.json')
    try:
        webcam.save_camera_settings({'exposure_time_absolute': 20},
                                    path=webcam.CAMERA_SETTINGS_PATH)
        old = time.time() - 3600
        os.utime(webcam.CAMERA_SETTINGS_PATH, (old, old))
        webcam.save_camera_settings({'exposure_time_absolute': 4},
                                    path=webcam.CAMERA_SETTINGS_FALLBACK)
        assert webcam.load_camera_settings() == \
            {'exposure_time_absolute': 4}, webcam.load_camera_settings()
        # and the other way round: a newer primary still wins
        os.utime(webcam.CAMERA_SETTINGS_FALLBACK, (old - 60, old - 60))
        os.utime(webcam.CAMERA_SETTINGS_PATH, None)
        assert webcam.load_camera_settings() == \
            {'exposure_time_absolute': 20}
    finally:
        webcam.CAMERA_SETTINGS_PATH = prim_bak
        webcam.CAMERA_SETTINGS_FALLBACK = fall_bak
        shutil.rmtree(d, ignore_errors=True)


class _Swap:
    """Replace module attributes for one test and put them back."""

    def __init__(self, **values):
        self.values = values

    def __enter__(self):
        self.saved = {n: getattr(webcam, n) for n in self.values}
        for n, v in self.values.items():
            setattr(webcam, n, v)
        return self

    def __exit__(self, *exc):
        for n, v in self.saved.items():
            setattr(webcam, n, v)
        return False


def test_a_trial_grab_stamps_its_own_controls_not_the_lock():
    """#400: a camera adjustment's trial picture is shot under the trial's
    controls. oneshot_rgb stamped the LOCK before every grab, so with a
    lock in place (one is restored at every start) Stabilize's and Auto-WB
    once's trial pictures were all shot at the locked exposure and
    balance."""
    stamped = []
    spec = {'kind': 'bayer', 'device': '/dev/videoX', 'fourcc': 'RGGB',
            'w': 8, 'h': 6}
    with _Swap(set_control=lambda dev, name, val: stamped.append((name,
                                                                   val)),
               grab_raw=lambda *a, **kw: bytes(8 * 6)):
        webcam.set_locked({'exposure_time_absolute': 20, 'red_balance': 92})
        try:
            frame = webcam.oneshot_rgb(spec, count=1, controls={
                'exposure_time_absolute': 64, 'gain': 0})
            assert frame is not None and frame.shape == (6, 8, 3)
            assert ('exposure_time_absolute', 64) in stamped, stamped
            assert ('exposure_time_absolute', 20) not in stamped, stamped
            assert not [s for s in stamped if s[0] == 'red_balance'], stamped
            # ...and without trial controls the lock still wins, as before
            stamped.clear()
            webcam.oneshot_rgb(spec, count=1)
            assert ('exposure_time_absolute', 20) in stamped, stamped
            assert ('red_balance', 92) in stamped, stamped
            assert webcam.LOCKED_CONTROLS == {'exposure_time_absolute': 20,
                                              'red_balance': 92}
        finally:
            webcam.set_locked({})


class _Scene:
    """A camera model for the searches: the picture's mean follows the
    exposure (2 gray levels per unit, clipped at 255), and its red and blue
    means follow their balance, gray at red 92 and blue 151. Every call's
    controls are kept."""

    def __init__(self, per_unit=2.0):
        self.per_unit = per_unit
        self.calls = []

    def oneshot(self, spec, count=2, controls=None):
        import numpy as np
        self.calls.append(dict(controls or {}))
        c = controls or {}
        level = min(255.0, self.per_unit * c.get('exposure_time_absolute',
                                                 20))
        r = level * c.get('red_balance', 92) / 92.0
        b = level * c.get('blue_balance', 151) / 151.0
        frame = np.empty((4, 4, 3), np.float64)
        frame[..., 0], frame[..., 1], frame[..., 2] = r, level, b
        return frame


def test_the_exposure_search_shoots_each_trial_under_its_own_exposure():
    scene = _Scene()
    base = {'brightness': 240, 'exposure_time_absolute': 20, 'gain': 44,
            'red_balance': 92}
    webcam.set_locked({'exposure_time_absolute': 20, 'gain': 44})
    try:
        with _Swap(oneshot_rgb=scene.oneshot):
            found = webcam.find_exposure({'kind': 'bayer'}, base)
        # 64 -> mean 128 and 80 -> mean 160: 80 is nearer 150, and the
        # search stops at the first picture at or above it
        assert found == (80, 160.0), found
        tried = [c['exposure_time_absolute'] for c in scene.calls]
        assert tried == [16, 24, 32, 40, 50, 64, 80], tried
        for c in scene.calls:
            assert c['gain'] == webcam.GAIN_FLOOR, c
            assert c['auto_exposure'] == 1, c
            assert c['white_balance_automatic'] == 0, c
            assert c['brightness'] == 240 and c['red_balance'] == 92, c
        # the search never touches the lock
        assert webcam.LOCKED_CONTROLS == {'exposure_time_absolute': 20,
                                          'gain': 44}
    finally:
        webcam.set_locked({})


def test_the_exposure_found_does_not_depend_on_the_white_balance():
    """The search judges the green channel, which red and blue balance do
    not touch. On the whole RGB mean, the stale bench balance (red 204,
    blue 104) brightened every trial, the search stopped at 64, and the
    picture fell to a mean of 128 once the white was balanced."""
    found = []
    for red, blue in ((92, 151), (204, 104)):
        scene = _Scene()
        with _Swap(oneshot_rgb=scene.oneshot):
            found.append(webcam.find_exposure(
                {'kind': 'bayer'}, {'red_balance': red, 'blue_balance': blue}))
    assert found[0] == found[1] == (80, 160.0), found
    import numpy as np
    gray = np.full((2, 2), 90.0)
    assert webcam.picture_level(gray) == 90.0     # a mono picture


def test_an_exposure_search_with_no_picture_finds_nothing():
    with _Swap(oneshot_rgb=lambda spec, count=2, controls=None: None):
        assert webcam.find_exposure({'kind': 'bayer'}, {}) is None


def test_gray_world_moves_red_and_blue_to_where_the_scene_is_gray():
    scene = _Scene()
    base = webcam.exposure_trial({'brightness': 240}, 64)
    with _Swap(oneshot_rgb=scene.oneshot):
        err, red, blue = webcam.balance_gray_world({'kind': 'bayer'}, base,
                                                   red=64, blue=64)
    assert err < webcam.GRAY_WORLD_TOL, err
    assert abs(red - 92) <= 2 and abs(blue - 151) <= 3, (red, blue)
    assert len(scene.calls) <= webcam.GRAY_WORLD_ROUNDS
    for c in scene.calls:
        assert c['white_balance_automatic'] == 0, c
        assert c['exposure_time_absolute'] == 64 and c['gain'] == 0, c
    # the first trial is shot at the starting balance, the next ones moved
    assert (scene.calls[0]['red_balance'],
            scene.calls[0]['blue_balance']) == (64, 64)
    assert scene.calls[1]['red_balance'] > 64
    assert scene.calls[1]['blue_balance'] > 64


def test_gray_world_refuses_a_picture_with_a_black_channel():
    import numpy as np
    with _Swap(oneshot_rgb=lambda spec, count=2, controls=None:
               np.zeros((4, 4, 3))):
        try:
            webcam.balance_gray_world({'kind': 'bayer'}, {})
        except RuntimeError as e:
            assert 'black' in str(e), e
        else:
            raise AssertionError("a black picture was balanced")


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
