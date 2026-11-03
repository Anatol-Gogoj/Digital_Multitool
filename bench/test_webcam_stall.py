#!/usr/bin/env python3
"""
Camera stall probe: the DFK 37BUX250 on the Linux bench, NO HV, ~1 min.

Bench findings 2026-11-03 (BENCH_TEST section U, SLDEA_DECISIONS.md
2026-11-03):
after uvcvideo -71 errors the DFK's v4l2-ctl stream went silent WITHOUT
exiting. The Webcam preview read it on the Tk thread with a blocking pipe
read and froze the window for good; the killed app left its v4l2-ctl
behind, which held the camera through the disconnect so the next user had
none. This probe makes the same silent stream on a healthy camera, by
stopping v4l2-ctl with SIGSTOP (alive, silent: what the dead camera did),
and checks every bound the fix put in:

  1. a healthy stream delivers, frame-aligned
  2. silent stream: reads give up within READ_WAIT_S + DRAIN_MAX_S, then at once
     past STALL_S; the preview's own read (CAM_PREVIEW_READ_WAIT_S) too
  3. SIGCONT: frames come back, still aligned
  4. close() of a stopped stream returns within ~1.5 s and the
     process is gone
  5. a parent killed with SIGKILL takes its v4l2-ctl stream with it
  6. the SLDEA VideoRecorder, its stream stopped mid-recording, reopens
     it and records on (before the fix: no frame for the rest of the run,
     and stop() took 5 s)

Close the app's Webcam preview first (the probe needs the camera free):

    .venv/bin/python bench/test_webcam_stall.py [--device /dev/video0]

Exit 0 only when every check passes.
"""
import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import numpy as np        # noqa: E402
import webcam             # noqa: E402
import sldea_video as sv  # noqa: E402

FAILS = []


def check(ok, text):
    print(f"  [{'PASS' if ok else 'FAIL'}] {text}")
    if not ok:
        FAILS.append(text)


def reads(cam, seconds, timeout=None):
    out = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        t = time.monotonic()
        f = cam.read(timeout)
        out.append((time.monotonic() - t, f))
        if f is None:
            time.sleep(0.05)          # the recorder's own back-off
    return out


def stream_checks(dev, fourcc):
    C = webcam.V4L2BayerCamera
    cam = C(dev, fourcc, 1920, 1080, fps=15).open()
    pid = cam._proc.pid
    print(f"1. healthy stream (pid {pid})")
    r = reads(cam, 3.0)
    good = [f for _, f in r if f is not None]
    check(len(good) >= 10, f"{len(good)} frames in 3 s")
    ref = good[-1].astype(np.float32) if good else None

    print("2. stream stopped (SIGSTOP: v4l2-ctl alive, silent)")
    os.kill(pid, signal.SIGSTOP)
    r = reads(cam, C.STALL_S + 2.0)
    longest = max(d for d, _ in r)
    check(all(f is None for _, f in r), "no frame while silent")
    bound = C.READ_WAIT_S + C.DRAIN_MAX_S
    check(longest <= bound + 0.05,
          f"longest read {longest:.3f} s (bound {bound:g} s)")
    tail = [d for d, _ in r[-5:]]
    check(max(tail) < 0.05, f"past STALL_S reads return at once "
                            f"({max(tail) * 1000:.1f} ms)")
    t = time.monotonic()
    cam.read_rgb(timeout=0.03)
    check(time.monotonic() - t < 0.1, "the preview's read returns")

    print("3. SIGCONT")
    os.kill(pid, signal.SIGCONT)
    r = reads(cam, 3.0)
    good = [f for _, f in r if f is not None]
    check(len(good) >= 10, f"{len(good)} frames in 3 s after resuming")
    if good and ref is not None:
        corr = np.corrcoef(ref.ravel()[::97],
                           good[-1].astype(np.float32).ravel()[::97])[0, 1]
        check(corr > 0.9, f"correlation with the pre-stall frame "
                          f"{corr:.3f} (a shifted stream reads far lower)")

    print("4. close() of a stopped stream")
    os.kill(pid, signal.SIGSTOP)
    t = time.monotonic()
    cam.close()
    dt = time.monotonic() - t
    time.sleep(0.3)
    check(dt < C.CLOSE_WAIT_S + webcam.V4L2_KILL_WAIT_S + 0.2,
          f"close() {dt:.2f} s")
    check(not os.path.exists(f'/proc/{pid}'), "the stream process is gone")


def death_check(dev, fourcc):
    print("5. parent killed with SIGKILL")
    child = subprocess.Popen([sys.executable, '-c', f'''
import sys, time; sys.path.insert(0, {REPO!r}); import webcam
c = webcam.V4L2BayerCamera({dev!r}, {fourcc!r}, 1920, 1080).open()
print(c._proc.pid, flush=True); time.sleep(60)'''],
        stdout=subprocess.PIPE, text=True)
    spid = int(child.stdout.readline())
    time.sleep(1.0)
    before = os.path.exists(f'/proc/{spid}')
    child.kill()
    child.wait()
    time.sleep(0.5)
    check(before and not os.path.exists(f'/proc/{spid}'),
          f"stream alive before the kill: {before}; after: "
          f"{os.path.exists(f'/proc/{spid}')}")


def recorder_check(dev):
    print("6. SLDEA VideoRecorder, stream stopped mid-recording")
    spec = webcam.resolve_camera(int(dev.rsplit('video', 1)[1]))
    out = tempfile.mkdtemp(prefix='webcam_stall_')
    lines = []
    rec = sv.VideoRecorder(lambda: sv.open_stream(spec), out, fps=1,
                           log=lines.append)
    rec.start()
    check(rec.wait_first_frame(10), "first frame")
    rec.set_t0(time.monotonic())
    time.sleep(3)
    pid = rec._cam._proc.pid
    os.kill(pid, signal.SIGSTOP)
    t = time.monotonic()
    while time.monotonic() - t < 15 and rec.reopens == 0:
        time.sleep(0.1)
    dt = time.monotonic() - t
    check(rec.reopens >= 1 and dt < 8, f"reopened after {dt:.1f} s")
    seen = rec.seen
    time.sleep(3)
    check(rec.seen - seen >= 10, f"{rec.seen - seen} frames after reopening")
    t = time.monotonic()
    rec.stop(timeout=10.0)
    check(time.monotonic() - t < 3, f"stop() {time.monotonic() - t:.2f} s")
    rec.wait_finished(30)
    print("   " + rec.summary())
    import shutil
    shutil.rmtree(out, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--device', default='/dev/video0')
    dev = ap.parse_args().device
    fourcc = webcam.bayer_format(dev)
    if not fourcc:
        print(f"{dev}: no Bayer-only camera there (is the DFK plugged in, "
              f"and the Webcam preview closed?)")
        return 2
    print(f"{dev} {fourcc}; v4l2-ctl prefix: {webcam._with_pdeathsig([])}")
    stream_checks(dev, fourcc)
    death_check(dev, fourcc)
    recorder_check(dev)
    print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED'}")
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
