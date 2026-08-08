#!/usr/bin/env python3
"""Do the apps ACTUALLY start? (launches each one for real, under Xvfb)

Every other suite here is logic-only or builds widgets in-process. None of
them answers the question a user cares about: does a window appear?

2026-07-27: a single emoji (U+1F39A, on the tuner button) resolved to a
colour BITMAP font; Tk's RenderAddGlyphs upload overflowed and X returned
BadLength, which ABORTS the process. The GUI was dead on arrival over
forwarded X for five releases. Static review could not see it (it is a
render-time protocol failure), and the in-process smokes missed it because
the developer's environment carried a font workaround that production did
not have.

So these tests launch the real programs the way a user does, with any
external font workaround REMOVED, and assert a mapped window appears.
Every Tk entry point is covered -- Edge Review, the tuner and the plot
window are separate processes carrying the same emoji, and would have died
the same way, but nothing was checking them.

Run: .venv/bin/python tests/test_app_launch.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import csv
import os
import shutil
import subprocess
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISPLAY = ':' + os.environ.get('SCPI_TEST_DISPLAY', '97')
BOOT_TIMEOUT = 150          # a cold main-GUI start builds every tab


def _have(*tools):
    return all(shutil.which(t) for t in tools)


def _clean_env():
    """The user's environment, minus any developer font workaround: the app
    must stand on its own exactly as it does for a user."""
    env = {k: v for k, v in os.environ.items()
           if k not in ('FONTCONFIG_FILE', 'XDG_CONFIG_HOME')}
    env['DISPLAY'] = DISPLAY
    return env


def _fake_run(dirpath):
    """Minimal SLDEA run dir so Edge Review / the tuner have something to
    open (baseline + two activated frames)."""
    import numpy as np
    import cv2
    frames = os.path.join(dirpath, 'frames')
    os.makedirs(frames, exist_ok=True)
    cols = ['snapshot', 'step', 'tag', 'nominal_kV', 'control_V',
            'measured_kV', 'measured_uA', 't_planned_s', 'timestamp',
            'frame_file', 'active_area_px', 'active_area_mm2',
            'active_diam_mm', 'wrinkle_idx', 'notes']
    rows = []
    yy, xx = np.mgrid[0:240, 0:320]
    for k, (tag, kv, r) in enumerate((('baseline', 0.0, 0),
                                      ('post-ramp', 3.0, 45),
                                      ('post-ramp', 6.0, 70))):
        img = np.full((240, 320), 190.0, np.float32)
        img[(xx - 160) ** 2 + (yy - 120) ** 2 <= 90 * 90] = 165.0
        if r:
            img[(xx - 160) ** 2 + (yy - 120) ** 2 <= r * r] += 35
        fn = f'SLDEA_s{k:02d}_{kv:05.2f}kV_{tag}.png'
        cv2.imwrite(os.path.join(frames, fn),
                    np.clip(img, 0, 255).astype(np.uint8))
        rows.append({**{c: '' for c in cols}, 'tag': tag, 'nominal_kV': kv,
                     'frame_file': fn, 'step': k, 'snapshot': k + 1})
    with open(os.path.join(dirpath, 'data.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(dirpath, 'setup.txt'), 'w') as f:
        f.write("SLDEA Test -- synthetic\nDEA nominal diameter: 16 mm\n")
    return dirpath


def _launch_expecting_window(argv, title_fragment, timeout=BOOT_TIMEOUT):
    """Start a program, wait for a VIEWABLE window whose title contains
    `title_fragment`. Raises with the captured output on failure."""
    env = _clean_env()
    xvfb = subprocess.Popen(['Xvfb', DISPLAY, '-screen', '0', '1400x900x24'],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    app = None
    name = os.path.basename(argv[1])
    try:
        time.sleep(2)
        app = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if app.poll() is not None:
                out = (app.stdout.read() or '')[-2500:]
                raise AssertionError(
                    f"{name} exited with {app.returncode} before showing a "
                    f"window:\n{out}")
            r = subprocess.run(['xwininfo', '-root', '-children'],
                               env=env, capture_output=True, text=True)
            for line in r.stdout.splitlines():
                if title_fragment in line:
                    wid = line.split()[0]
                    st = subprocess.run(['xwininfo', '-id', wid], env=env,
                                        capture_output=True, text=True)
                    if 'IsViewable' in st.stdout:
                        return True
            time.sleep(1)
        raise AssertionError(
            f"{name}: no viewable window containing {title_fragment!r} "
            f"within {timeout}s")
    finally:
        for p in (app, xvfb):
            if p is not None:
                p.kill()
                try:
                    p.wait(timeout=10)
                except Exception:
                    pass


def test_main_gui_starts_and_maps_a_window():
    if not _have('Xvfb', 'xwininfo'):
        print("   (skipped: Xvfb/xwininfo not installed)")
        return
    _launch_expecting_window(
        [_sys.executable, os.path.join(REPO, 'gui.py')], 'Lab Instrument')


def test_edge_review_starts_and_maps_a_window():
    if not _have('Xvfb', 'xwininfo'):
        print("   (skipped: Xvfb/xwininfo not installed)")
        return
    d = tempfile.mkdtemp(prefix='launch_edge_')
    try:
        _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        _launch_expecting_window(
            [_sys.executable, os.path.join(REPO, 'sldea_edge_gui.py'), d],
            'SLDEA Edge Review', timeout=60)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_tuner_starts_and_maps_a_window():
    if not _have('Xvfb', 'xwininfo'):
        print("   (skipped: Xvfb/xwininfo not installed)")
        return
    d = tempfile.mkdtemp(prefix='launch_tuner_')
    run = os.path.join(d, 'SLDEA_20260101_000000')
    try:
        _fake_run(run)
        _launch_expecting_window(
            [_sys.executable, os.path.join(REPO, 'sldea_tuner.py'), run],
            'SLDEA edge tuner', timeout=60)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_plot_window_starts_and_maps_a_window():
    # `#223`: a fourth Tk entry point, launched by 📊 Plot runs… and
    # carrying emoji of its own (📊, 💾, ✓) -- the exact shape of the
    # 2026-07-27 colour-bitmap-font abort this suite exists to catch.
    if not _have('Xvfb', 'xwininfo'):
        print("   (skipped: Xvfb/xwininfo not installed)")
        return
    d = tempfile.mkdtemp(prefix='launch_plot_')
    try:
        _fake_run(os.path.join(d, 'SLDEA_20260101_000000'))
        _launch_expecting_window(
            [_sys.executable, os.path.join(REPO, 'sldea_plot_gui.py'), d],
            'SLDEA plot', timeout=60)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _run():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
