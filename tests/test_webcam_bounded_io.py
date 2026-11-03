#!/usr/bin/env python3
"""Headless tests: the camera layer never waits without a limit.

Background (bench, 2026-11-03): the DFK stopped answering over USB
(uvcvideo -71 errors). The Webcam preview read the v4l2-ctl Bayer stream on
the Tk thread with a blocking pipe read, and the window froze until it was
killed (tk_stall.log: _cam_preview_tick -> V4L2BayerCamera._read_exactly).
Calls through subprocess.run(timeout=) each waited out 10 s on the dead
camera, and could wait forever on a child stuck in the kernel, because
CPython waits for the killed child with no limit. The killed app left its
v4l2-ctl stream holding the camera, so the next user had none.

No camera needed: the stream is an os.pipe() behind a stand-in process,
and a child "stuck in the kernel" is a stand-in whose wait never returns.
The real camera was checked on the bench (SLDEA_DECISIONS.md 2026-11-03).

Run: .venv/bin/python tests/test_webcam_bounded_io.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import os
import subprocess
import threading
import time

import webcam

W, H = 16, 8                     # a tiny Bayer frame: 128 bytes
N = W * H


class _Skip(Exception):
    """A case that cannot run on this platform; _run counts it skipped."""


def _needs_pipe_select():
    """The stream read waits in select() on the v4l2-ctl pipe. Windows'
    select() takes sockets only (WinError 10093 on a pipe), so there the
    read fails at once and a timing or alignment check would test
    nothing. The Bayer stream is Linux-bench-only, so these cases run on
    POSIX and skip on Windows."""
    if _sys.platform.startswith('win'):
        raise _Skip("select() on a pipe needs POSIX; the Bayer stream "
                    "is Linux-only")


class _PipeProc:
    """A stand-in for the v4l2-ctl Popen: stdout is the read end of a real
    pipe, the test writes the other end. `stuck` makes it ignore SIGTERM
    and SIGKILL, as a process stuck inside an ioctl does."""

    def __init__(self, stuck=False):
        r, self.w = os.pipe()
        self.stdout = os.fdopen(r, 'rb', buffering=0)
        self.stuck = stuck
        self.signals = []
        self._gone = threading.Event()
        self.pid = -1

    def poll(self):
        return 0 if self._gone.is_set() else None

    def terminate(self):
        self.signals.append('TERM')
        if not self.stuck:
            self._gone.set()

    def kill(self):
        self.signals.append('KILL')
        if not self.stuck:
            self._gone.set()

    def wait(self, timeout=None):
        if not self._gone.wait(timeout):
            raise subprocess.TimeoutExpired('v4l2-ctl', timeout)
        return 0

    def write(self, data):
        os.write(self.w, data)

    def eof(self):
        os.close(self.w)


def _cam(proc):
    cam = webcam.V4L2BayerCamera('/dev/video99', 'RGGB', W, H, fps=15)
    cam._proc = proc
    cam._last_frame_at = time.monotonic()
    return cam


def _frame(value):
    return bytes([value]) * N


def _timed(fn):
    t = time.monotonic()
    out = fn()
    return out, time.monotonic() - t


def test_a_silent_stream_read_returns_within_its_timeout():
    """The freeze itself: v4l2-ctl alive, no bytes. read() must come back."""
    _needs_pipe_select()
    cam = _cam(_PipeProc())
    got, dt = _timed(lambda: cam._read_frame(cam._proc, 0.2))
    assert got is None
    assert 0.15 <= dt < 0.6, dt


def test_a_partial_frame_waits_its_timeout_then_completes_aligned():
    """The bench's stack: select() saw bytes, then the read waited forever
    for the rest of the frame. The half frame must stay buffered, and the
    frame it completes must be exactly the bytes that were written."""
    _needs_pipe_select()
    proc = _PipeProc()
    cam = _cam(proc)
    frame = bytes(range(N))
    proc.write(frame[:N // 2])
    got, dt = _timed(lambda: cam._read_frame(proc, 0.2))
    assert got is None and dt < 0.6, dt
    proc.write(frame[N // 2:])
    got = cam._read_frame(proc, 0.2)
    assert got == frame, "the frame came back shifted"


def test_the_newest_complete_frame_is_returned_and_the_rest_kept():
    _needs_pipe_select()
    proc = _PipeProc()
    cam = _cam(proc)
    proc.write(_frame(1) + _frame(2) + _frame(3)[:N // 4])
    assert cam._read_frame(proc, 0.2) == _frame(2)
    proc.write(_frame(3)[N // 4:])
    assert cam._read_frame(proc, 0.2) == _frame(3)


def test_a_stream_silent_past_stall_s_is_not_waited_on():
    _needs_pipe_select()
    cam = _cam(_PipeProc())
    cam._last_frame_at = time.monotonic() - cam.STALL_S - 0.1
    got, dt = _timed(lambda: cam._read_frame(cam._proc, 5.0))
    assert got is None and dt < 0.1, dt


def test_a_stalled_stream_still_takes_a_frame_that_has_arrived():
    _needs_pipe_select()
    proc = _PipeProc()
    cam = _cam(proc)
    cam._last_frame_at = time.monotonic() - cam.STALL_S - 0.1
    proc.write(_frame(7))
    time.sleep(0.02)
    assert cam._read_frame(proc, 5.0) == _frame(7)
    # ...and having had one, it waits again
    got, dt = _timed(lambda: cam._read_frame(proc, 0.2))
    assert got is None and dt >= 0.15, dt


def test_an_exited_stream_returns_none_at_once():
    _needs_pipe_select()
    proc = _PipeProc()
    cam = _cam(proc)
    proc.eof()
    got, dt = _timed(lambda: cam._read_frame(proc, 5.0))
    assert got is None and dt < 0.1, dt


def test_read_on_a_closed_camera_is_none():
    cam = _cam(_PipeProc())
    cam.close()
    assert cam.read(0.1) is None and cam.read_rgb(0.1) is None


def test_close_of_a_stream_stuck_in_the_kernel_is_bounded():
    """close() used to wait 3 s, and the preview stops on the Tk thread."""
    proc = _PipeProc(stuck=True)
    cam = _cam(proc)
    _, dt = _timed(cam.close)
    assert dt < cam.CLOSE_WAIT_S + webcam.V4L2_KILL_WAIT_S + 0.3, dt
    assert proc.signals == ['TERM', 'KILL'], proc.signals
    assert cam._proc is None
    proc._gone.set()                  # let the reaper thread finish


def test_close_of_a_healthy_stream_stops_at_sigterm():
    proc = _PipeProc()
    cam = _cam(proc)
    cam.close()
    assert proc.signals == ['TERM'], proc.signals


def test_end_child_never_waits_past_its_grace():
    proc = _PipeProc(stuck=True)
    out, dt = _timed(lambda: webcam._end_child(proc, 0.2))
    assert out is False and dt < 0.5, dt
    proc._gone.set()


class _StuckPopen:
    """subprocess.Popen whose child is stuck in the kernel: communicate()
    times out, and wait() returns only once released. That is the call
    that hung the app inside subprocess.run."""
    made = []

    def __init__(self, cmd, **kw):
        self.cmd = cmd
        self.released = threading.Event()
        self.killed = False
        _StuckPopen.made.append(self)

    def communicate(self, input=None, timeout=None):
        time.sleep(timeout or 0)
        raise subprocess.TimeoutExpired(self.cmd, timeout)

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        if not self.released.wait(timeout):
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        return -9


class _PatchPopen:
    def __init__(self, cls):
        self.cls = cls

    def __enter__(self):
        self.saved = webcam.subprocess.Popen
        webcam.subprocess.Popen = self.cls
        webcam.clear_unresponsive()
        return self

    def __exit__(self, *exc):
        webcam.subprocess.Popen = self.saved
        webcam.clear_unresponsive()
        return False


def test_a_call_whose_child_cannot_die_still_returns():
    _StuckPopen.made = []
    with _PatchPopen(_StuckPopen):
        out, dt = _timed(lambda: webcam._v4l2('--list-formats',
                                              device='/dev/video99',
                                              timeout=0.2))
    assert out == ''
    assert dt < 0.2 + webcam.V4L2_KILL_WAIT_S + 0.3, dt
    assert _StuckPopen.made[0].killed
    _StuckPopen.made[0].released.set()


def test_a_timed_out_device_is_held_off_then_asked_again():
    _StuckPopen.made = []
    with _PatchPopen(_StuckPopen):
        webcam._v4l2('--list-formats', device='/dev/video99', timeout=0.1)
        assert webcam.camera_unresponsive('/dev/video99') > 0
        # a dozen more calls (opening the preview makes about that many)
        _, dt = _timed(lambda: [webcam.get_control('/dev/video99', 'gain')
                                for _ in range(12)])
        assert dt < 0.1, dt
        assert len(_StuckPopen.made) == 1, "a held device was asked again"
        assert webcam.grab_raw('/dev/video99', 'RGGB', W, H) is None
        assert len(_StuckPopen.made) == 1
        # another device is not held
        assert webcam.camera_unresponsive('/dev/video98') == 0.0
        # the hold ends, by time or by clear_unresponsive (Refresh)
        webcam.mark_unresponsive('/dev/video99', hold_s=0.05)
        time.sleep(0.1)
        assert webcam.camera_unresponsive('/dev/video99') == 0.0
        webcam.mark_unresponsive('/dev/video99')
        webcam.clear_unresponsive()
        assert webcam.camera_unresponsive('/dev/video99') == 0.0
    for p in _StuckPopen.made:
        p.released.set()


def test_a_real_overrun_returns_on_time():
    """A real child that outlives its timeout (no stand-in Popen)."""
    webcam.clear_unresponsive()
    out, dt = _timed(lambda: webcam._run_bounded(['sleep', '30'], 0.3,
                                                 device='/dev/video97'))
    assert out is None and dt < 1.0, dt
    assert webcam.camera_unresponsive('/dev/video97') > 0
    webcam.clear_unresponsive()


def test_a_real_call_returns_its_output():
    out = webcam._run_bounded(['echo', 'hello'], 5.0, text=True)
    assert out is not None and out.returncode == 0
    assert out.stdout.strip() == 'hello'


def test_every_v4l2_ctl_runs_under_the_parent_death_signal():
    """A killed app must not leave its stream holding the camera."""
    import shutil
    cmd = ['v4l2-ctl', '-d', '/dev/video0', '--all']
    out = webcam._with_pdeathsig(cmd)
    assert out[-len(cmd):] == cmd
    if _sys.platform.startswith('linux') and shutil.which('setpriv'):
        assert out[1:4] == ['--pdeathsig', 'KILL', '--'], out
    else:
        assert out == cmd, out


def test_a_child_dies_with_the_thread_that_started_it():
    """setpriv's death signal, end to end with a real child."""
    import shutil
    if not (_sys.platform.startswith('linux') and shutil.which('setpriv')):
        print("   (skipped: no setpriv)")
        return
    box = []

    def start():
        proc = subprocess.Popen(webcam._with_pdeathsig(['sleep', '30']))
        box.append(proc)
        # setpriv arms the signal after it starts and before it execs the
        # command; a thread that ends inside that window (well under 1 ms
        # of the start) arms it for nobody. Wait for the exec, as the app's
        # threads do by living on.
        end = time.monotonic() + 3
        while time.monotonic() < end:
            try:
                with open(f'/proc/{proc.pid}/cmdline', 'rb') as f:
                    if f.read().split(b'\0')[0].endswith(b'sleep'):
                        break
            except OSError:
                break
            time.sleep(0.005)
    t = threading.Thread(target=start)
    t.start()
    t.join()                       # the starting thread has now ended
    proc = box[0]
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise AssertionError("the child outlived the thread that started it")
    assert proc.returncode == -9, proc.returncode


def test_stamp_controls_stops_when_told():
    calls = []
    saved = webcam.set_control
    webcam.set_control = lambda dev, name, val: calls.append(name) or True
    try:
        left = [2]

        def keep_going():
            left[0] -= 1
            return left[0] >= 0
        n = webcam.stamp_controls('/dev/video99',
                                  {'auto_exposure': 1,
                                   'white_balance_automatic': 0,
                                   'exposure_time_absolute': 100,
                                   'red_balance': 106},
                                  keep_going=keep_going)
        assert calls == ['auto_exposure', 'white_balance_automatic'], calls
        assert n == 2
        calls.clear()
        webcam.stamp_controls('/dev/video99', {'gain': 0},
                              keep_going=lambda: 1 / 0)
        assert calls == [], "a keep_going that raises must stop the stamp"
    finally:
        webcam.set_control = saved


class _FakeV4l2:
    """webcam._v4l2 stand-in: `formats` answers --list-formats, writes are
    logged with the thread that made them, `slow` delays a --set-ctrl."""

    def __init__(self, formats='', slow=0.0):
        self.formats = formats
        self.slow = slow
        self.log = []
        self.lock = threading.Lock()

    def __call__(self, *args, device=None, timeout=10):
        arg = args[0]
        if arg == '--list-formats':
            return self.formats
        if arg.startswith('--set-ctrl='):
            name, val = arg[len('--set-ctrl='):].split('=')
            with self.lock:
                self.log.append(('start', name, int(val)))
            time.sleep(self.slow)
            with self.lock:
                self.log.append(('done', name, int(val)))
            self.last = int(val)
            return ''
        if arg.startswith('--get-ctrl='):
            return f"x: {getattr(self, 'last', 0)}"
        return ''


class _PatchV4l2:
    def __init__(self, fake):
        self.fake = fake

    def __enter__(self):
        self.saved = webcam._v4l2
        webcam._v4l2 = self.fake
        webcam.clear_unresponsive()
        return self.fake

    def __exit__(self, *exc):
        webcam._v4l2 = self.saved
        webcam.clear_unresponsive()
        return False


BAYER = "\t[0]: 'RGGB' (8-bit Bayer RGRG/GBGB)\n"
YUYV = "\t[0]: 'YUYV' (YUYV 4:2:2)\n"


def test_a_camera_that_did_not_answer_is_not_taken_for_a_webcam():
    """Review 2026-11-03: a held DFK answered '' to --list-formats, so
    bayer_format said "not Bayer" and resolve_camera described it as an
    OpenCV webcam, which cannot open it: every still of a run started then
    was NO FRAME. Not answering must raise, and say what to do."""
    with _PatchV4l2(_FakeV4l2(formats='')):
        webcam.mark_unresponsive('/dev/video99')
        try:
            webcam.bayer_format('/dev/video99')
            raise AssertionError("a held camera was answered for")
        except webcam.CameraUnresponsive as e:
            assert 'Refresh' in str(e) and 'replug' in str(e).lower(), e
        saved = (webcam.v4l2_available, webcam.os.path.exists)
        webcam.v4l2_available = lambda: True
        webcam.os.path.exists = lambda p: True
        try:
            try:
                spec = webcam.resolve_camera(99)
                raise AssertionError(f"resolved a held camera as {spec}")
            except webcam.CameraUnresponsive:
                pass
        finally:
            webcam.v4l2_available, webcam.os.path.exists = saved


def test_a_camera_that_answers_resolves_as_before():
    with _PatchV4l2(_FakeV4l2(formats=BAYER)):
        assert webcam.bayer_format('/dev/video99') == 'RGGB'
    with _PatchV4l2(_FakeV4l2(formats=YUYV)):
        assert webcam.bayer_format('/dev/video99') is None
    with _PatchV4l2(_FakeV4l2(formats='')):
        # no answer and no hold: a node that is not a capture node
        assert webcam.bayer_format('/dev/video99') is None


def test_a_resumed_stream_gives_its_frame_in_one_read():
    """Review 2026-11-03: past STALL_S a read took ONE pipe-full, so a 1080p
    frame (32 pipe-fulls) took 32 reads and 31 counted failures."""
    _needs_pipe_select()
    w, h = 1920, 1080
    proc = _PipeProc()
    cam = webcam.V4L2BayerCamera('/dev/video99', 'RGGB', w, h)
    cam._proc = proc
    cam._last_frame_at = time.monotonic() - cam.STALL_S - 0.1
    frame = bytes(range(256)) * (w * h // 256)
    t = threading.Thread(target=proc.write, args=(frame,), daemon=True)
    t.start()
    time.sleep(0.05)               # the first pipe-full is waiting
    got, dt = _timed(lambda: cam._read_frame(proc, 0.0))
    assert got == frame, "a resumed stream's frame took more than one read"
    assert dt < cam.DRAIN_MAX_S + 0.1, dt
    t.join(1)


def test_the_recorder_does_not_reopen_a_stream_that_comes_back_itself():
    """The same, as the SLDEA recorder saw it: a 3 s dropout that ends by
    itself was cut off by a forced reopen (REOPEN_AFTER_FAILS)."""
    _needs_pipe_select()
    import tempfile
    import sldea_video as sv
    w, h = 1920, 1080
    opens = []

    def opener():
        cam = webcam.V4L2BayerCamera('/dev/video99', 'RGGB', w, h)
        proc = _PipeProc()
        cam._proc = proc
        cam._last_frame_at = time.monotonic()
        first = not opens
        opens.append(proc)

        def writer():
            frame = bytes(w * h)
            t0 = time.monotonic()
            paused = False
            while not proc._gone.is_set():
                if first and not paused and time.monotonic() - t0 > 1.0:
                    time.sleep(3.0)             # the camera hiccups
                    paused = True
                try:
                    os.write(proc.w, frame)
                except OSError:
                    break
                time.sleep(0.05)
        threading.Thread(target=writer, daemon=True).start()
        return cam
    out = tempfile.mkdtemp(prefix='bounded_io_rec_')
    rec = sv.VideoRecorder(opener, out, fps=1, log=lambda s: None)
    try:
        rec.start()
        assert rec.wait_first_frame(5)
        time.sleep(1.0 + 3.0 + 2.0)
        assert rec.reopens == 0, (rec.reopens, rec.read_failures)
        assert rec.latest()[0] is not None, "the stream did not come back"
    finally:
        rec.stop(3)
        rec.wait_finished(10)
        import shutil
        shutil.rmtree(out, ignore_errors=True)


def test_a_capture_stamps_after_the_relock_it_stopped():
    """Review 2026-11-03: the preview's re-stamp left the Tk thread, so one
    of its writes could land after a capture had stamped its own values.
    Writes now go one at a time, and the re-stamp asks keep_going under the
    same lock: the capture's value is the camera's last."""
    fake = _FakeV4l2(slow=0.2)
    with _PatchV4l2(fake):
        live = [True]
        relock = threading.Thread(target=webcam.stamp_controls, args=(
            '/dev/video99', {'exposure_time_absolute': 50, 'gain': 3,
                             'red_balance': 90}),
            kwargs={'keep_going': lambda: live[0]})
        relock.start()
        while not fake.log:                        # its first write is on
            time.sleep(0.005)
        live[0] = False                            # the preview stops...
        webcam.stamp_controls('/dev/video99',      # ...and a capture stamps
                              {'exposure_time_absolute': 130})
        relock.join(5)
    writes = [e for e in fake.log if e[0] == 'done']
    assert writes[-1] == ('done', 'exposure_time_absolute', 130), fake.log
    starts = [e for e in fake.log if e[0] == 'start']
    assert len(starts) == 2, f"the stopped re-stamp wrote on: {fake.log}"
    # never two writes at once
    depth = 0
    for kind, _, _ in fake.log:
        depth += 1 if kind == 'start' else -1
        assert depth <= 1, fake.log


def _run():
    # Failures are collected, not fatal (`#280`); see run_tests.py.
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    ran = skipped = 0
    failed = []
    for fn in fns:
        try:
            fn()
        except _Skip as why:
            skipped += 1
            print(f"skip {fn.__name__} ({why})")
            continue
        except Exception:
            ran += 1
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
        ran += 1
        print(f"ok  {fn.__name__}")
    if not failed:
        if skipped:
            print(f"\n{ran} of {len(fns)} tests ran ({skipped} skipped, "
                  f"see above)")
        else:
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
