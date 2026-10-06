#!/usr/bin/env python3
"""The SLDEA camera pre-flight shoots under the lock the run will hold.

Run 13_backlight (2026-10-05): the pre-flight wrote the panel's exposure
and gain, then grabbed through oneshot_rgb, which re-stamps the Webcam
tab's LOCK before the shutter -- so the dialog showed the lock's exposure,
while the run overrides the lock with the panel's values for every grab.
The dialog looked reasonable and all 60 frames came out 57-66 % saturated
at the panel's exposure 20. Headless: the camera, v4l2 and the dialog are
stubbed.

Run: .venv/bin/python tests/test_sldea_camera_lock.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import gui
import webcam

G = gui.InstrumentControlGUI
# the Webcam tab's lock, as the backlight session left it: a short
# exposure the preview looked right at
TAB_LOCK = {'auto_exposure': 1, 'white_balance_automatic': 0,
            'exposure_time_absolute': 4, 'gain': 0, 'red_balance': 92}


class _MB:
    """messagebox stub: records every call, answers askyesno No."""

    def __init__(self):
        self.calls = []

    def askyesno(self, title, msg='', **kw):
        self.calls.append(('askyesno', title, msg))
        return False

    def __getattr__(self, name):
        def show(title, msg='', **kw):
            self.calls.append((name, title, msg))
        return show


class _App:
    _sldea_preflight = G._sldea_preflight

    def __init__(self):
        self.lines = []

    def _sldea_log(self, msg):
        self.lines.append(str(msg))


class _Patched:
    """A Bayer camera whose one-shot grab records the lock in force at
    the shutter and returns no frame (so the dialog is never built)."""

    def __enter__(self):
        self.at_grab = []
        self.written = []
        self.saved = (webcam.resolve_camera, webcam.set_control,
                      webcam.oneshot_rgb, gui.messagebox,
                      dict(webcam.LOCKED_CONTROLS))
        webcam.resolve_camera = lambda idx: {
            'kind': 'bayer', 'device': '/dev/video0', 'fourcc': 'BA81',
            'w': 1920, 'h': 1080}
        webcam.set_control = \
            lambda dev, name, val: self.written.append((name, val)) or True

        def grab(spec, count=2):
            self.at_grab.append(dict(webcam.LOCKED_CONTROLS))
            return None
        webcam.oneshot_rgb = grab
        self.mb = gui.messagebox = _MB()
        webcam.set_locked(TAB_LOCK)
        return self

    def __exit__(self, *exc):
        (webcam.resolve_camera, webcam.set_control, webcam.oneshot_rgb,
         gui.messagebox, lock) = self.saved
        webcam.set_locked(lock)
        return False


def test_the_run_lock_is_the_tab_lock_with_the_runs_four_controls():
    got = gui.sldea_run_lock(TAB_LOCK, 20, 0)
    assert got == dict(TAB_LOCK, exposure_time_absolute=20), got
    assert gui.sldea_run_lock({}, 7, 3) == {
        'auto_exposure': 1, 'white_balance_automatic': 0,
        'exposure_time_absolute': 7, 'gain': 3}
    # the input is not modified
    assert TAB_LOCK['exposure_time_absolute'] == 4


def test_a_mismatch_is_named_and_agreement_or_no_lock_says_nothing():
    msg = gui.sldea_lock_mismatch(TAB_LOCK, 20, 0)
    assert 'exposure 20 (locked: 4)' in msg, msg
    assert 'gain' not in msg.split('.')[0], msg
    assert 'Apply & Lock' in msg, msg
    both = gui.sldea_lock_mismatch(TAB_LOCK, 20, 16)
    assert 'exposure 20 (locked: 4)' in both and 'gain 16 (locked: 0)' in both
    assert gui.sldea_lock_mismatch(TAB_LOCK, 4, 0) == ''
    assert gui.sldea_lock_mismatch({}, 20, 0) == ''
    assert gui.sldea_lock_mismatch({'red_balance': 92}, 20, 0) == ''


def test_the_preflight_grabs_under_the_runs_lock_and_puts_the_tabs_back():
    """The bug: at the shutter, the Webcam tab's lock (exposure 4) was in
    force, not the run's (exposure 20). Now the grab sees exactly the lock
    the run will hold, and the tab's lock is restored afterwards."""
    with _Patched() as p:
        app = _App()
        ok = app._sldea_preflight(20, 0)
        assert ok is False, ok                   # no frame -> asked, No
        assert p.at_grab == [gui.sldea_run_lock(TAB_LOCK, 20, 0)], p.at_grab
        assert p.at_grab[0]['exposure_time_absolute'] == 20
        assert dict(webcam.LOCKED_CONTROLS) == TAB_LOCK, \
            webcam.LOCKED_CONTROLS
        # the mismatch reaches run.log via the prelog, in plain words
        assert any('exposure 20 (locked: 4)' in l for l in app.lines), \
            app.lines


def test_the_tabs_lock_is_restored_even_when_the_grab_raises():
    with _Patched() as p:
        def boom(spec, count=2):
            raise RuntimeError('EBUSY')
        webcam.oneshot_rgb = boom
        _App()._sldea_preflight(20, 0)
        assert dict(webcam.LOCKED_CONTROLS) == TAB_LOCK, \
            webcam.LOCKED_CONTROLS
        assert p.mb.calls and p.mb.calls[0][1] == 'Camera pre-flight'


def test_fields_that_match_the_lock_log_nothing():
    with _Patched() as p:
        app = _App()
        app._sldea_preflight(4, 0)
        assert p.at_grab[0]['exposure_time_absolute'] == 4
        assert not any('differ' in l for l in app.lines), app.lines


def test_the_worker_builds_its_lock_through_the_same_helper():
    """Source check, because driving _sldea_worker needs the whole run
    harness: the run's lock and the pre-flight's must come from one
    definition, or they can drift apart again."""
    import inspect
    src = inspect.getsource(G._sldea_worker)
    assert 'sldea_run_lock(cam_lock_saved, cam_exp, cam_gain)' in \
        ' '.join(src.split()), 'the worker no longer uses sldea_run_lock'


def _run():
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
