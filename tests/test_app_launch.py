#!/usr/bin/env python3
"""Does the app ACTUALLY start? (launches gui.py for real, under Xvfb)

Every other suite here is logic-only or builds widgets in-process. None of
them answers the one question a user cares about: does a window appear?

2026-07-27: a single emoji (U+1F39A, on the tuner button) resolved to a
colour BITMAP font; Tk's RenderAddGlyphs upload overflowed and X returned
BadLength, which ABORTS the process. The GUI was dead on arrival over
forwarded X for five releases. Static review could not see it (it is a
render-time protocol failure), and the in-process smokes missed it because
the test environment carried a font workaround that production did not.

So this test launches the real program the way a user does, with any
external font workaround REMOVED, and asserts a mapped window appears.

Run: .venv/bin/python tests/test_app_launch.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import os
import shutil
import subprocess
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISPLAY = ':' + os.environ.get('SCPI_TEST_DISPLAY', '97')
BOOT_TIMEOUT = 150          # cold start builds every tab


def _have(*tools):
    return all(shutil.which(t) for t in tools)


def test_gui_starts_and_maps_a_window():
    if not _have('Xvfb', 'xwininfo'):
        print("   (skipped: Xvfb/xwininfo not installed)")
        return
    xvfb = subprocess.Popen(['Xvfb', DISPLAY, '-screen', '0', '1400x900x24'],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    # Deliberately strip any workaround the developer's shell may carry:
    # the app must stand on its own, exactly as it does for a user.
    env = {k: v for k, v in os.environ.items()
           if k not in ('FONTCONFIG_FILE', 'XDG_CONFIG_HOME')}
    env['DISPLAY'] = DISPLAY
    app = None
    try:
        time.sleep(2)
        app = subprocess.Popen([_sys.executable, os.path.join(REPO, 'gui.py')],
                               env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
        mapped, deadline = False, time.time() + BOOT_TIMEOUT
        while time.time() < deadline:
            if app.poll() is not None:
                out = app.stdout.read()[-2000:]
                raise AssertionError(
                    f"gui.py exited with {app.returncode} before showing a "
                    f"window:\n{out}")
            r = subprocess.run(['xwininfo', '-root', '-children'],
                               env=env, capture_output=True, text=True)
            for line in r.stdout.splitlines():
                if 'Lab Instrument' in line:
                    wid = line.split()[0]
                    st = subprocess.run(['xwininfo', '-id', wid], env=env,
                                        capture_output=True, text=True)
                    if 'IsViewable' in st.stdout:
                        mapped = True
                        break
            if mapped:
                break
            time.sleep(1)
        assert mapped, (f"no viewable window within {BOOT_TIMEOUT}s — the "
                        f"app started but never became visible")
    finally:
        for p in (app, xvfb):
            if p is not None:
                p.kill()
                try:
                    p.wait(timeout=10)
                except Exception:
                    pass


def _run():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
