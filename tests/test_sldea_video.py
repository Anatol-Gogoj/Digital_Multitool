#!/usr/bin/env python3
"""The SLDEA run video: a lossless recording beside the stills, and edge
detection on every frame afterwards (sldea_video.py, 2026-09-23).

What these pin down:
  * the recorder writes a LOSSLESS file at its rate, on the run's own
    clock, with the commanded kV per frame -- nothing before t0, nothing
    after end_recording();
  * every call the HV loop makes is safe: latest() is a copy that ages
    out and never serves a frame from before `not_before`, a camera that
    never opens fails fast, stop() gives up at its timeout even when the
    camera's read() blocks forever, a slow encoder DROPS frames (counted)
    rather than stalling the reader, and the encoder exits by itself when
    stop() could not queue its sentinel;
  * a stream that dies mid-run is REOPENED; a stream opened after stop()
    is closed, not orphaned; a still-time restamp runs on the reader and
    the frame read straight after it is discarded (it may be stale);
  * finalize moves the files in (a .part copy across volumes, renamed
    only when complete) and says where a failure left them;
  * detect_video runs the stills' own detector on every frame, from the
    run folder or from the staging copy; the detached --finalize job
    detects first and moves second;
  * the codec is checked at the stream's OWN size, with its own frame,
    and frames reach FFmpeg laid out so that its read past the last pixel
    stays in memory the recorder owns (2026-10-06: the cause of this
    suite's one-process-in-five FFV1 failure on Windows);
  * the REAL run worker: stills come off the stream (no one-shot grab),
    setup.txt says what happened, a dead stream falls back to one-shot
    stills, the SG is zeroed BEFORE the recorder is stopped, the tab is
    released even when the video shutdown throws, an abort during the
    camera startup never switches the SG output on, and neither does a
    stream size the codec cannot record;
  * #392: setup.txt ends with how the recording ENDED (the frames it
    holds, or NOT recorded, and why it stopped), written after the HV
    shutdown; a codec check that hangs is given up on and stops the run
    before HV; the guard-page test counts only the real fault.

Run: .venv/bin/python tests/test_sldea_video.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import csv
import os
import shutil
import tempfile
import threading
import time

import sldea_video as sv


class _Skip(Exception):
    """Could not run here -- reported, never counted as a pass."""


def _need_cv():
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as e:
        raise _Skip(f"no OpenCV/numpy: {e}")
    ok, why = sv.codec_available()
    if not ok:
        raise _Skip(f"this OpenCV cannot write {sv.VIDEO_FOURCC}: {why}")


def _frame_for(seq, shape=(96, 128)):
    """The deterministic BGR frame _FakeCam delivers as stream frame
    `seq`, so a decoded video frame can be checked against it exactly."""
    import numpy as np
    h, w = shape
    img = np.zeros((h, w, 3), np.uint8)
    img[:, :, 0] = (seq * 7) % 251
    img[:, :, 1] = (seq * 13) % 241
    img[:, :, 2] = (seq * 29) % 239
    img[(seq % h), :, :] = 255                 # a line that moves
    return img


class _FakeCam:
    """A streaming camera: read() sleeps a frame period and returns the
    next deterministic frame. `block` makes read() hang until close();
    `die_after` makes it return None forever after that many frames."""

    def __init__(self, period=0.02, block=False, shape=(96, 128),
                 die_after=None):
        self.period, self.block, self.shape = period, block, shape
        self.die_after = die_after
        self.n = 0
        self.closed = threading.Event()

    def read(self):
        if self.block:
            self.closed.wait()
            return None
        if self.closed.is_set():
            return None
        time.sleep(self.period)
        if self.die_after is not None and self.n >= self.die_after:
            return None
        self.n += 1
        return _frame_for(self.n, self.shape)

    def close(self):
        self.closed.set()


def _read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _wait(cond, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


# ------------------------------------------------------------ pure helpers

def test_fps_is_clamped_and_a_half_typed_box_is_the_default():
    assert sv.clamp_fps('2') == 2.0
    assert sv.clamp_fps(99) == sv.VIDEO_FPS_MAX
    assert sv.clamp_fps('0') == sv.VIDEO_FPS_MIN
    for junk in ('', None, 'fast', float('nan')):
        assert sv.clamp_fps(junk) == sv.VIDEO_FPS_DEFAULT, junk
    # the stream runs faster than the fastest recording, so the rate gate
    # never has to skip alternate frames (review 2026-09-23)
    assert sv.STREAM_FPS > sv.VIDEO_FPS_MAX


def test_the_size_estimate_is_the_measured_rate():
    # 0.97 MB per 1080p frame, measured 2026-09-23: a 43-minute run at
    # 1 fps is ~2.5 GB -- the number the tab shows the operator
    est = sv.estimate_bytes(43 * 60, 1.0)
    assert 2.3e9 < est < 2.8e9, est
    assert sv.estimate_bytes(43 * 60, 2.0) == 2 * est
    assert sv.fmt_bytes(2.5e9) == '2.5 GB' and sv.fmt_bytes(512) == '512 B'


def test_staging_is_local_and_overridable():
    old = os.environ.get('SCPI_SLDEA_VIDEO_STAGING')
    try:
        os.environ['SCPI_SLDEA_VIDEO_STAGING'] = '/somewhere/else'
        assert sv.staging_root() == '/somewhere/else'
        del os.environ['SCPI_SLDEA_VIDEO_STAGING']
        root = sv.staging_root()
        assert 'scpi_control' in root and 'sldea_video' in root, root
    finally:
        if old is not None:
            os.environ['SCPI_SLDEA_VIDEO_STAGING'] = old
        else:
            os.environ.pop('SCPI_SLDEA_VIDEO_STAGING', None)


def test_the_codec_is_lossless_here_and_the_probe_never_raises():
    _need_cv()                     # _need_cv already ran the round trip
    assert sv.codec_available() == (True, '')
    ok, why = sv.codec_available(tmpdir=os.path.join(
        tempfile.gettempdir(), 'no', 'such', 'dir'))
    assert ok is False and why, "an unwritable probe dir must be an answer"


def test_the_probe_runs_at_the_frame_size_and_refuses_an_odd_one():
    """2026-10-06: the 64 x 48 probe passed sizes FFV1 cannot record.
    Handed a frame, the probe writes and reads back THAT size. OpenCV's
    FFmpeg writer truncates an odd width or height to even (its
    cap_ffmpeg_impl.hpp, "we truncate the rightmost column/the bottom
    row"), so an odd frame comes back a column short: not lossless."""
    _need_cv()
    import numpy as np
    rng = np.random.default_rng(5)
    even = rng.integers(0, 256, (48, 64, 3), dtype=np.uint8)   # BGR
    assert sv.codec_available(frame=even) == (True, '')
    ok, why = sv.codec_available(frame=rng.integers(
        0, 256, (48, 65), dtype=np.uint8))
    # a refusal of any kind is right (here: "read back as 64 x 48")
    assert ok is False, "an odd width must not pass as lossless"
    assert '65 x 48' in why, why


def test_a_writer_that_throws_fails_the_probe_and_names_the_size():
    """The other 2026-10-06 failure: at some sizes write() threw "Unknown
    C++ exception" on the first frame. The probe turns that into an
    answer naming the size, and releases the writer it opened."""
    _need_cv()
    import cv2
    import numpy as np
    real = cv2.VideoWriter
    released = []

    class Throws:
        def __init__(self, *a, **k):
            pass

        def isOpened(self):
            return True

        def write(self, img):
            raise cv2.error("Unknown C++ exception from OpenCV code")

        def release(self):
            released.append(True)
    cv2.VideoWriter = Throws
    try:
        ok, why = sv.codec_available(frame=np.zeros((918, 1632), np.uint8))
    finally:
        cv2.VideoWriter = real
    assert ok is False and released == [True], (ok, released)
    assert '1632 x 918' in why and 'Unknown C++ exception' in why, why


def test_a_folder_the_probe_cannot_write_in_is_not_blamed_on_the_encoder():
    """#392: this OpenCV reports a writer it could not open in the same way
    for a missing encoder and for a folder it cannot write in, here one
    that is not there and one that is a file. The reason used to say "this
    OpenCV build has no FFV1 encoder"; it now names both causes."""
    _need_cv()
    import numpy as np
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        a_file = os.path.join(d, 'a_file')
        with open(a_file, 'w') as f:
            f.write('x')
        for where in (os.path.join(d, 'no', 'such'), a_file):
            ok, why = sv.codec_available(
                tmpdir=where, frame=np.zeros((96, 128), np.uint8))
            assert ok is False and why == (
                f"could not open the {sv.VIDEO_FOURCC} writer (encoder or "
                f"disk) for 128 x 96"), (where, why)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ffmpeg_safe_keeps_the_pixels_and_room_past_the_last_one():
    """The layout ffmpeg_safe promises: the same pixels; a row stride that
    is a multiple of 32 and a last row ending mid-page, so OpenCV passes
    the frame in place (its own copy keeps only 32 B spare); and more
    than FFMPEG_OVERREAD bytes of the buffer past that end. The buffer is
    reused for the next frame of the same size."""
    import numpy as np
    rng = np.random.default_rng(9)
    for h, w in ((48, 64), (96, 128), (240, 320), (918, 1632),
                 (1080, 1920), (96, 129), (1080, 1081)):
        gray = rng.integers(0, 256, (h, w), dtype=np.uint8)
        view, buf = sv.ffmpeg_safe(gray)
        assert np.array_equal(view, gray), (h, w)
        step = view.strides[0]
        assert view.strides[1] == 1 and step % 32 == 0 and step >= w, \
            (h, w, view.strides)
        end = view.ctypes.data + step * h
        assert end % sv._PAGE == sv._PAGE // 2, (h, w, end % sv._PAGE)
        room = buf.ctypes.data + buf.size - end
        assert room > sv.FFMPEG_OVERREAD, (h, w, room)
        again, buf2 = sv.ffmpeg_safe(gray[::-1].copy(), buf)
        assert buf2 is buf and np.array_equal(again, gray[::-1])
    # not an 8-bit gray frame: handed back untouched, never narrowed
    deep = np.full((4, 64), 1000, np.uint16)
    same, nobuf = sv.ffmpeg_safe(deep)
    assert same is deep and nobuf is None


# Run in a child process, so the deliberate fault cannot touch the suite:
# on Windows it is a C++ exception, on Linux a SIGSEGV that kills the
# process. The child maps memory with an inaccessible page right after
# it and writes one 1920 x 1080 frame. 'raw' is a contiguous frame ending
# 100 B before that page, as a cv2-allocated frame sits when it fails.
# 'safe' is the same picture through ffmpeg_safe, whose buffer is handed
# in ending exactly at that page.
_GUARD_CHILD = r'''
import ctypes, json, os, sys, tempfile
sys.path.insert(0, sys.argv[1])
mode = sys.argv[2]
import numpy as np, cv2
import sldea_video as sv
PAGE = 4096

def guarded(nbytes):
    pages = (nbytes + PAGE - 1) // PAGE
    total = (pages + 1) * PAGE
    if os.name == 'nt':
        k32 = ctypes.windll.kernel32
        k32.VirtualAlloc.restype = ctypes.c_void_p
        k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                     ctypes.c_uint32, ctypes.c_uint32]
        k32.VirtualProtect.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                       ctypes.c_uint32,
                                       ctypes.POINTER(ctypes.c_uint32)]
        base = k32.VirtualAlloc(None, total, 0x3000, 0x04)
        old = ctypes.c_uint32()
        assert k32.VirtualProtect(base + pages * PAGE, PAGE, 0x01,
                                  ctypes.byref(old))
        keep = None
    else:
        import mmap
        keep = mmap.mmap(-1, total)
        base = ctypes.addressof(ctypes.c_char.from_buffer(keep))
        libc = ctypes.CDLL(None)
        libc.mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.c_int]
        assert libc.mprotect(base + pages * PAGE, PAGE, 0) == 0
    start = base + pages * PAGE - nbytes
    arr = np.frombuffer((ctypes.c_uint8 * nbytes).from_address(start),
                        np.uint8)
    return arr, keep

def write_one(img, want, d, name):
    path = os.path.join(d, name)
    h, w = want.shape
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*sv.VIDEO_FOURCC),
                         1.0, (w, h), isColor=False)
    try:
        print('WRITING', flush=True)
        vw.write(img)
        out = 'ok'
    except Exception as e:
        out = 'threw: %s' % e
    vw.release()
    cap = cv2.VideoCapture(path)
    ok, g = cap.read()
    cap.release()
    exact = bool(ok) and np.array_equal(g[:, :, 0] if g.ndim == 3 else g,
                                        want)
    return out, exact

h, w = 1080, 1920
gray = np.random.default_rng(4).integers(0, 256, (h, w), dtype=np.uint8)
with tempfile.TemporaryDirectory() as d:
    if mode == 'raw':
        img, keep = guarded(h * w + 100)
        img = img[:h * w].reshape(h, w)
        img[:] = gray
    else:
        buf, keep = guarded(((w + 31) & ~31) * h + 3 * PAGE)
        img, _ = sv.ffmpeg_safe(gray, buf)
    print(json.dumps(write_one(img, gray, d, mode + '.mkv')))
'''


def _guard_child(mode, root=None):
    """-> (returncode, [write outcome, decoded bit-exactly] or None when
    the child died before it could say, its stdout lines, its stderr).
    `root` is where the child imports sldea_video from (this checkout by
    default). It runs in the temp folder, so that the '' a `-c` child has
    on sys.path cannot find this checkout's modules for it."""
    import json
    import subprocess
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(
        __file__)))
    p = subprocess.run([_sys.executable, '-c', _GUARD_CHILD, root, mode],
                       capture_output=True, text=True, timeout=120,
                       cwd=tempfile.gettempdir())
    lines = p.stdout.strip().splitlines()
    res = (json.loads(lines[-1]) if lines and lines[-1].startswith('[')
           else None)
    return p.returncode, res, lines, p.stderr


# THE fault, and nothing else (#392). The child prints 'WRITING' just
# before its write, and after that only these count: "Unknown C++
# exception" from the write (Windows, where OpenCV turns the access
# violation into one), or the child killed by SIGSEGV (Linux, returncode
# -11) or by STATUS_ACCESS_VIOLATION (a Windows build that does not
# convert it, returncode 0xC0000005). Both codes were measured with a
# NULL read in a child, 2026-10-06. The old test took `rc != 0`, so a
# child that died of an ImportError or an assertion counted as faulted.
_GUARD_WRITING = 'WRITING'
_ACCESS_VIOLATION = 0xC0000005


def _guard_faulted(rc, res, lines):
    """Did the guard child fault reading past its frame? See above."""
    import signal
    if _GUARD_WRITING not in lines:
        return False
    if res and 'Unknown C++ exception' in str(res[0]):
        return True
    return rc in (-signal.SIGSEGV, _ACCESS_VIOLATION)


def test_a_frame_through_ffmpeg_safe_survives_where_a_raw_one_faults():
    """The fix measured, in a child process each: with unmapped memory
    right behind the buffer, the raw frame faults on this OpenCV/FFmpeg
    (an exception on Windows, a crash on Linux), and the ffmpeg_safe one
    writes and decodes bit-exactly. An FFmpeg that does not read past the
    frame (5.0 and later) passes both, and the test says it showed
    nothing. Only the fault itself counts (_guard_faulted): a raw child
    that failed in any other way fails this test."""
    _need_cv()
    rc, res, lines, err = _guard_child('safe')
    assert rc == 0 and res == ['ok', True], (rc, res, err[-800:])
    rc, res, lines, err = _guard_child('raw')
    if rc == 0 and res and res[0] == 'ok':
        raise _Skip(f"{sv._ffmpeg_version()} does not read past a raw "
                    f"frame, so the layouts cannot be told apart here (the "
                    f"ffmpeg_safe half passed)")
    assert _guard_faulted(rc, res, lines), (rc, res, lines, err[-800:])


def test_the_guard_test_counts_only_the_real_fault():
    """#392: the test above used to count ANY failed child as the fault
    (`rc != 0 or ...`), so a child that died before it wrote a frame, of
    an ImportError or an assertion, passed it. Here are such children
    for real: the old rule counts them, _guard_faulted does not. A child
    that really faults (a NULL read) after it says it is writing counts,
    with whatever code this platform gives it, and the same child does
    not count without that line."""
    import subprocess

    def old_rule(rc, res):
        return rc != 0 or bool(res and 'Unknown C++ exception' in res[0])

    def child(code):
        p = subprocess.run([_sys.executable, '-c', code],
                           capture_output=True, text=True, timeout=120,
                           cwd=tempfile.gettempdir())
        return p.returncode, p.stdout.strip().splitlines(), p.stderr
    # the guard child itself, from a root with no sldea_video in it
    rc, res, lines, err = _guard_child(
        'raw', root=os.path.join(tempfile.gettempdir(), 'no_such_root_392'))
    assert rc != 0 and 'ModuleNotFoundError' in err, (rc, err[-400:])
    assert old_rule(rc, res), "the old rule should count this child"
    assert not _guard_faulted(rc, res, lines), (rc, res, lines)
    # an assertion inside the child, even after it said it was writing
    rc, lines, err = child(f"print({_GUARD_WRITING!r}, flush=True)\n"
                           f"assert False, 'not the fault'\n")
    assert rc != 0 and 'AssertionError' in err, (rc, err[-400:])
    assert old_rule(rc, None) and not _guard_faulted(rc, None, lines)
    # a real fault; on Windows, no error-report dialog may hold the child
    rc, lines, err = child(
        "import ctypes, faulthandler, os\n"
        "if os.name == 'nt':\n"
        "    ctypes.windll.kernel32.SetErrorMode(0x0002)\n"
        f"print({_GUARD_WRITING!r}, flush=True)\n"
        "faulthandler._read_null()\n")
    assert _guard_faulted(rc, None, lines), (rc, lines, err[-400:])
    assert not _guard_faulted(rc, None, [ln for ln in lines
                                         if ln != _GUARD_WRITING])


# ---------------------------------------------------------------- recorder

def test_the_recorder_writes_a_lossless_file_on_the_run_clock():
    _need_cv()
    import cv2
    import numpy as np
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        rec = sv.VideoRecorder(lambda: _FakeCam(), d, fps=5,
                               kv_at=lambda t: 2.0 * t, log=lambda m: None)
        rec.start()
        assert rec.wait_first_frame(3.0)
        rec.set_t0(time.monotonic())
        time.sleep(1.0)
        rec.stop(timeout=5.0)
        rows = _read_csv(os.path.join(d, sv.VIDEO_INDEX_FILENAME))
        assert list(rows[0]) == sv.INDEX_COLUMNS
        assert 3 <= len(rows) <= 8, len(rows)            # ~5 fps for 1 s
        ts = [float(r['t_s']) for r in rows]
        assert ts == sorted(ts) and 0.0 <= ts[0] < 0.3, ts
        for r in rows:                     # the commanded kV at that time
            assert abs(float(r['nominal_kV']) - 2.0 * float(r['t_s'])) \
                < 0.01, r
        # bit-exact: each decoded frame is the grey of the stream frame
        # its row names
        got = list(sv.iter_frames(os.path.join(d, sv.VIDEO_FILENAME)))
        assert len(got) == len(rows) == rec.written
        for (i, gray), r in zip(got, rows):
            want = cv2.cvtColor(_frame_for(int(r['stream_seq'])),
                                cv2.COLOR_BGR2GRAY)
            assert np.array_equal(gray, want), f"frame {i} is not lossless"
        assert rec.dropped == 0 and rec.error is None
        s = rec.summary()
        assert 'frames recorded' in s and 'stream' in s, s
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_check_codec_probes_with_the_streams_own_frame():
    """VideoRecorder.check_codec: no camera I/O of its own. It hands the
    codec probe the frame the reader already holds, gray as recorded,
    probes on the recording's own disk and leaves nothing there, and
    remembers the size that passed; with no frame yet it refuses."""
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    real = sv.codec_available
    seen = []

    def spy(tmpdir=None, frame=None):
        seen.append((tmpdir, None if frame is None else frame.shape))
        return real(tmpdir=tmpdir, frame=frame)
    try:
        idle = sv.VideoRecorder(lambda: _FakeCam(), d, log=lambda m: None)
        ok, why = idle.check_codec()
        assert ok is False and 'no frame' in why, why
        sv.codec_available = spy
        rec = sv.VideoRecorder(lambda: _FakeCam(shape=(96, 128)), d,
                               log=lambda m: None).start()
        assert rec.wait_first_frame(3.0)
        assert rec.check_codec() == (True, '')
        assert seen == [(d, (96, 128))], seen
        assert rec.probed_size == (128, 96)
        rec.stop(timeout=5.0)
        assert os.listdir(d) == [], os.listdir(d)
    finally:
        sv.codec_available = real
        shutil.rmtree(d, ignore_errors=True)


def test_a_stream_of_an_odd_size_fails_check_codec():
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        rec = sv.VideoRecorder(lambda: _FakeCam(shape=(96, 129)), d,
                               log=lambda m: None).start()
        assert rec.wait_first_frame(3.0)
        ok, why = rec.check_codec()
        rec.stop(timeout=5.0)
        assert ok is False and '129 x 96' in why, why
        assert rec.probed_size is None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_size_other_than_the_checked_one_is_not_recorded():
    """A stream reopened at another size between the check and the
    first recorded frame: that size was never checked, so it is not
    recorded (an odd one would be cropped), the log says so, and the
    stills are still served."""
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    logs = []
    try:
        rec = sv.VideoRecorder(lambda: _FakeCam(), d, fps=5,
                               log=logs.append).start()
        assert rec.wait_first_frame(3.0)
        assert rec.check_codec() == (True, '')
        rec.probed_size = (64, 48)       # as if checked on another stream
        rec.set_t0(time.monotonic())
        assert _wait(lambda: rec.error is not None, 3.0)
        time.sleep(0.5)
        assert rec.latest()[0] is not None, "the stills must go on"
        rec.stop(timeout=5.0)
        assert rec.written == 0, rec.written
        assert 'delivers 128 x 96' in rec.error \
            and 'never checked' in rec.error, rec.error
        assert any(rec.error in m for m in logs), logs
        assert not os.path.exists(os.path.join(d, sv.VIDEO_FILENAME))
        # and setup.txt's end line says so (#392)
        assert rec.end_outcome() == "NOT recorded: " + rec.error
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_nothing_is_recorded_before_t0_or_after_end_recording():
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        rec = sv.VideoRecorder(lambda: _FakeCam(), d, fps=5,
                               log=lambda m: None).start()
        assert rec.wait_first_frame(3.0)
        time.sleep(0.3)
        frame, t = rec.latest()
        assert frame is not None and t is None, "no run time before t0"
        assert rec.written == 0
        rec.set_t0(time.monotonic())
        assert _wait(lambda: rec.written >= 2, 3.0)
        # the staircase is over: frames from here would be filed under
        # the planned kV while the SG is already at 0
        rec.end_recording()
        time.sleep(0.3)                 # let a frame already queued land
        n, seen = rec.written, rec.seen
        time.sleep(0.8)
        assert rec.seen > seen, "stills must still be served"
        assert rec.written == n, "recorded after end_recording()"
        rec.stop(timeout=5.0)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_latest_is_a_copy_that_ages_out_and_never_predates_its_moment():
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        rec = sv.VideoRecorder(lambda: _FakeCam(), d, fps=1,
                               log=lambda m: None).start()
        assert rec.wait_first_frame(3.0)
        rec.set_t0(time.monotonic())
        time.sleep(0.2)
        a, ta = rec.latest()
        a[:] = 0                              # scribbling on the copy...
        b, _t = rec.latest()
        assert b.any(), "...must not reach the recorder's own frame"
        rgb, trgb = rec.latest_rgb()
        assert rgb is not None and rgb.shape == b.shape and trgb >= 0
        # a still scheduled in the future cannot be served yet...
        future = ta + 5.0
        assert rec.latest(not_before=future) == (None, None)
        # ...and once the stream has passed a moment, it can
        mark = ta + 0.2
        assert _wait(lambda: rec.latest(not_before=mark)[0] is not None,
                     2.0)
        assert rec.latest(not_before=mark)[1] >= mark
        rec.stop(timeout=5.0)
        time.sleep(0.25)
        assert rec.latest(max_age_s=0.1) == (None, None), \
            "a stalled stream must not keep serving an old picture"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_restamp_runs_on_the_reader_and_drops_the_stale_frame_after():
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        stamps = []
        rec = sv.VideoRecorder(lambda: _FakeCam(period=0.02), d, fps=1,
                               restamp=lambda: (stamps.append(
                                   threading.current_thread().name),
                                   time.sleep(0.2)),
                               log=lambda m: None).start()
        assert rec.can_restamp
        assert rec.wait_first_frame(3.0)
        rec.set_t0(time.monotonic())
        seen = rec.seen
        rec.request_restamp()
        assert _wait(lambda: rec.restamp_done_t() is not None, 3.0)
        assert stamps == ['sldea-video-reader'], stamps
        done = rec.restamp_done_t()
        # the first frame read after the stamp stall is discarded: the
        # stream hands back what was buffered DURING it
        assert _wait(lambda: rec.latest(not_before=done)[0] is not None,
                     2.0)
        assert rec.latest(not_before=done)[1] >= done
        assert rec.seen > seen
        rec.stop(timeout=5.0)
        # nothing to stamp: the tab only asks that a still postdate its
        # scheduled moment
        assert not sv.VideoRecorder(lambda: _FakeCam(), d).can_restamp
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_stream_that_dies_mid_run_is_reopened():
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        cams = [_FakeCam(period=0.005, die_after=5), _FakeCam(period=0.005)]
        opened = []

        def open_cam():
            cam = cams[min(len(opened), len(cams) - 1)]
            opened.append(cam)
            return cam
        logs = []
        rec = sv.VideoRecorder(open_cam, d, log=logs.append).start()
        assert rec.wait_first_frame(3.0)
        # the first stream dies after 5 frames; ~40 empty reads later the
        # reader closes it and opens the second, which keeps going
        assert _wait(lambda: rec.reopens == 1 and rec.seen > 10, 8.0), (
            rec.reopens, rec.seen, logs)
        assert cams[0].closed.is_set(), "the dead stream was not closed"
        assert any('reopened' in m for m in logs), logs
        assert 'REOPENED' in rec.summary()
        rec.stop(timeout=5.0)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_camera_that_never_opens_fails_fast():
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        def boom():
            raise RuntimeError('device busy')
        logs = []
        rec = sv.VideoRecorder(boom, d, log=logs.append).start()
        t = time.monotonic()
        assert not rec.wait_first_frame(3.0)
        assert time.monotonic() - t < 1.5, "waited out the whole timeout"
        assert 'device busy' in (rec.error or '') and logs
        t = time.monotonic()
        rec.stop(timeout=3.0)
        assert time.monotonic() - t < 1.5
        assert rec.latest() == (None, None)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_stream_that_opens_after_stop_is_closed_not_orphaned():
    """A slow open finishing AFTER stop() must not leave a live stream
    holding the device until the app exits (review 2026-09-23, F9)."""
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        cam = _FakeCam()
        gate = threading.Event()

        def slow_open():
            gate.wait(5)
            return cam
        rec = sv.VideoRecorder(slow_open, d, log=lambda m: None).start()
        rec.stop(timeout=0.5)                  # gives up while opening
        gate.set()                              # ...and now the open lands
        assert _wait(lambda: cam.closed.is_set(), 3.0), \
            "the late stream was orphaned"
        assert _wait(lambda: not rec.reader_alive(), 3.0)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_stop_gives_up_on_a_read_that_hangs_and_unblocks_it():
    """The HV loop's finally calls stop(): it must come back even when the
    camera is wedged inside read(). Closing the stream from stop() is what
    unblocks the reader."""
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        cam = _FakeCam(block=True)
        rec = sv.VideoRecorder(lambda: cam, d, log=lambda m: None).start()
        time.sleep(0.2)
        t = time.monotonic()
        rec.stop(timeout=3.0)
        took = time.monotonic() - t
        assert took < 3.5, took
        assert cam.closed.is_set(), "stop() never closed the stream"
        assert rec.wait_finished(2.0)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_slow_encoder_drops_frames_and_still_finishes_by_itself():
    """Frames are dropped (and counted) rather than stalling the reader --
    and when stop() cannot even queue its sentinel behind a stalled disk,
    the encoder still exits by itself and closes its files (F4)."""
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        def slow_kv(t):                 # runs on the WRITER, per frame
            time.sleep(0.3)
            return 0.0
        rec = sv.VideoRecorder(lambda: _FakeCam(period=0.01), d, fps=5,
                               kv_at=slow_kv, queue_max=1,
                               log=lambda m: None).start()
        assert rec.wait_first_frame(3.0)
        rec.set_t0(time.monotonic())
        time.sleep(1.5)
        seen_mid = rec.seen
        frame, _t = rec.latest(max_age_s=0.5)
        assert frame is not None, "the reader stalled behind the encoder"
        time.sleep(0.3)
        assert rec.seen > seen_mid, "the reader stopped reading"
        rec.stop(timeout=0.2)           # far too short to drain
        assert rec.wait_finished(10.0), "the encoder never exited"
        assert rec.dropped > 0, "expected dropped frames, and a count"
        assert 'DROPPED' in rec.summary()
        rows = _read_csv(os.path.join(d, sv.VIDEO_INDEX_FILENAME))
        assert len(rows) == rec.written, "the index was not closed"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_check_codec_gives_up_on_a_hung_probe_and_refuses_while_it_runs():
    """#392: a probe that hangs (encoder or staging disk) must not hold the
    runner at 0 V, with Abort waiting on it. check_codec gives up after
    its timeout and fails, naming the size and the limit. The probe it
    gave up on runs on; while it does, the next check refuses at once
    and starts no second probe, and once it returns, checks run again."""
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    real = sv.codec_available
    release = threading.Event()
    calls = []

    def hangs(tmpdir=None, frame=None):
        calls.append(tmpdir)
        release.wait(30)
        return real(tmpdir=tmpdir, frame=frame)
    try:
        sv.codec_available = hangs
        rec = sv.VideoRecorder(lambda: _FakeCam(), d,
                               log=lambda m: None).start()
        assert rec.wait_first_frame(3.0)
        t = time.monotonic()
        ok, why = rec.check_codec(timeout=0.5)
        took = time.monotonic() - t
        assert ok is False and 0.4 < took < 2.0, (ok, took)
        assert why.startswith('the FFV1 check at 128 x 96 was still '
                              'running after 0.5 s, so it was given up'), why
        assert rec.probed_size is None and rec.codec_check_running()
        t = time.monotonic()
        ok, why = rec.check_codec(timeout=0.5)
        assert ok is False and time.monotonic() - t < 0.3, why
        assert 'earlier run' in why and 'restart the app' in why, why
        assert calls == [d], calls             # no second probe started
        release.set()
        assert _wait(lambda: not rec.codec_check_running(), 10.0)
        sv.codec_available = real
        assert rec.check_codec() == (True, '')
        assert rec.probed_size == (128, 96)
        rec.stop(timeout=5.0)
    finally:
        release.set()
        sv.codec_available = real
        sv._abandoned_probe = None
        shutil.rmtree(d, ignore_errors=True)


def test_runs_preflight_probes_nothing_while_a_given_up_check_runs():
    """#392 review: Run's own pre-flight runs on the Tk thread before any
    worker exists: a 64 x 48 codec probe, then disk_usage on the staging
    disk. While a check given up on in an earlier run is still running,
    either could hang the whole window. The pre-flight then probes
    nothing and asks the existing "Video unavailable" question in the
    refusal's words: Yes is a snapshots-only run, No cancels. Once that
    check has returned, both probes run as before."""
    import shutil as _shutil
    import types
    import gui
    calls, asked, answer = [], [], [True]
    release = threading.Event()
    stuck = threading.Thread(target=release.wait, args=(30,), daemon=True)
    real_probe, real_usage = sv.codec_available, _shutil.disk_usage
    real_ask = gui.messagebox.askyesno

    def probe(*a, **k):
        calls.append('codec_available')
        return True, ''

    def usage(path):
        calls.append('disk_usage')
        return real_usage(path)

    def ask(title, message, **k):
        asked.append((title, message, k.get('default')))
        return answer[0]
    app = types.SimpleNamespace(
        sldea_vid_on=types.SimpleNamespace(get=lambda: True),
        sldea_vars={'vid_fps': types.SimpleNamespace(get=lambda: '1')},
        lines=[])
    app._sldea_log = app.lines.append
    preflight = gui.InstrumentControlGUI._sldea_video_preflight
    p = _short_profile()
    try:
        sv.codec_available, _shutil.disk_usage = probe, usage
        gui.messagebox.askyesno = ask
        stuck.start()
        sv._abandoned_probe = stuck
        assert preflight(app, p) == (False, None)     # Yes: snapshots only
        title, message, default = asked[-1]
        assert title == 'Video unavailable' and default == 'no', asked
        assert 'given up on in an earlier run is still running' in message \
            and 'restart the app to record video' in message, message
        assert any('snapshots only' in ln for ln in app.lines), app.lines
        answer[0] = False
        assert preflight(app, p) == (None, None)      # No: nothing starts
        assert calls == [], calls
        release.set()
        stuck.join(5.0)
        assert preflight(app, p) == (True, 1.0)
        assert calls == ['codec_available', 'disk_usage'], calls
        assert len(asked) == 2, asked
    finally:
        release.set()
        sv.codec_available, _shutil.disk_usage = real_probe, real_usage
        gui.messagebox.askyesno = real_ask
        sv._abandoned_probe = None


def test_the_end_outcome_of_a_clean_recording_and_of_one_never_begun():
    """#392: the words for setup.txt's `Video outcome (end):` line. A clean
    recording gives its frame count, which is the row count of
    video_frames.csv, and its span on the run's clock, and nothing about
    stopping. A run that ended before its clock started was NOT
    recorded, and the line says why."""
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        rec = sv.VideoRecorder(lambda: _FakeCam(), d, fps=5,
                               log=lambda m: None).start()
        assert rec.wait_first_frame(3.0)
        rec.set_t0(time.monotonic())
        assert _wait(lambda: rec.written >= 3, 3.0)
        rec.end_recording()
        rec.stop(timeout=5.0)
        rows = _read_csv(os.path.join(d, sv.VIDEO_INDEX_FILENAME))
        assert len(rows) == rec.written >= 3, (len(rows), rec.written)
        assert rec.end_outcome() == (
            f"recorded {len(rows)} frames, {rec.first_t:.1f} to "
            f"{rec.last_t:.1f} s on the run's clock")
        early = sv.VideoRecorder(lambda: _FakeCam(),
                                 os.path.join(d, 'early'),
                                 log=lambda m: None).start()
        assert early.wait_first_frame(3.0)
        early.end_recording()
        early.stop(timeout=5.0)
        assert early.end_outcome() == \
            "NOT recorded: the run ended before recording began"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_end_outcome_names_a_stream_that_stopped_delivering():
    """The bench case behind #392: the camera unplugged mid-run. The frames
    before it are recorded and rec.error stays None, since the reader only
    tries to reopen, yet the video ended there. The end line says how
    many frames, then that the stream stopped, and when."""
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    opened = []

    def open_cam():
        # the first stream dies after 25 frames; a reopened one delivers
        # nothing, as with the cable still out
        opened.append(1)
        return _FakeCam(die_after=25 if len(opened) == 1 else 0)
    try:
        rec = sv.VideoRecorder(open_cam, d, fps=5,
                               log=lambda m: None).start()
        assert rec.wait_first_frame(3.0)
        rec.set_t0(time.monotonic())
        assert _wait(lambda: rec.written >= 1, 3.0)
        # silent for longer than a still may be old
        assert _wait(lambda: time.monotonic() - rec.last_seen_clock
                     > sv.STILL_MAX_AGE_S + 0.3, 8.0)
        rec.end_recording()
        rec.stop(timeout=5.0)
        assert rec.error is None and rec.written >= 1, rec.summary()
        lost = rec.last_seen_clock - rec.t0
        assert rec.end_outcome() == (
            f"recorded {rec.written} frames, {rec.first_t:.1f} to "
            f"{rec.last_t:.1f} s on the run's clock, then stopped: the "
            f"camera stream stopped delivering at {lost:.1f} s and had not "
            f"come back by the end of the run")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_end_outcome_does_not_blame_the_camera_for_a_control_call():
    """#392 review: the reader itself runs the camera control calls (the
    refresh every 5 s and the restamp before each still: apply_locked, two
    v4l2-ctl runs per control, 10 s timeouts), and reads no frame
    meanwhile. A stop() 2.2 s into a 2.5 s refresh found the newest frame
    over 2 s old, and the end line said the stream stopped delivering.
    The reader now notes the call, and the line names it instead; the
    summary gives the longest call (BENCH_TEST Q18)."""
    import re
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    started = threading.Event()

    def slow_refresh():
        started.set()
        time.sleep(2.5)
    try:
        rec = sv.VideoRecorder(lambda: _FakeCam(), d, fps=5,
                               refresh=slow_refresh, refresh_s=1.0,
                               log=lambda m: None).start()
        assert rec.wait_first_frame(3.0)
        rec.set_t0(time.monotonic())
        assert _wait(lambda: rec.written >= 1, 3.0)
        assert started.wait(5.0), "the refresh never ran"
        time.sleep(2.2)
        rec.end_recording()
        rec.stop(timeout=5.0)
        out = rec.end_outcome()
        assert 'stopped delivering' not in out and 'then stopped' not in out, \
            out
        assert re.fullmatch(
            r"recorded \d+ frames, \d+\.\d to \d+\.\d s on the run's clock; "
            r"the reader was inside a camera control call for 2\.\d s at the "
            r"end", out), out
        assert 'camera control calls up to 2.' in rec.summary(), \
            rec.summary()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_stream_already_quiet_when_a_control_call_began_is_still_named():
    """The other side of the rule above, on the recorder's own numbers: a
    control call in progress at stop() explains the quiet only if the
    stream was live when the call began. A stream that had been quiet for
    longer than a still may be old before then had stopped delivering."""
    rec = sv.VideoRecorder(lambda: _FakeCam(), tempfile.gettempdir())
    rec.t0, rec.written, rec.first_t, rec.last_t = 100.0, 10, 0.0, 9.0
    rec.last_seen_clock, rec.stopped_at = 109.5, 130.0
    rec.stopped_in_control = 110.0           # 0.5 s after the last frame
    assert rec.end_outcome() == (
        "recorded 10 frames, 0.0 to 9.0 s on the run's clock; the reader "
        "was inside a camera control call for 20.0 s at the end")
    rec.stopped_in_control = 128.0           # 18.5 s after it
    assert rec.end_outcome() == (
        "recorded 10 frames, 0.0 to 9.0 s on the run's clock, then stopped: "
        "the camera stream stopped delivering at 9.5 s and had not come "
        "back by the end of the run")
    rec.stopped_in_control = None            # no call at all
    assert 'then stopped: the camera stream stopped delivering at 9.5 s' \
        in rec.end_outcome()


def test_the_end_outcome_names_a_dropout_the_stream_came_back_from():
    """#392 review: a stream that dropped out and came back read as a clean
    recording ("recorded 8 frames, 0.1 to 7.0 s") while run.log said
    "stream REOPENED 1x". The end line now counts the returns: reopens
    followed by a frame. A reopen that brings nothing back is not one,
    since on the bench's Bayer path a reopen "succeeds" with the camera
    still unplugged."""
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    cams = [_FakeCam(period=0.005, die_after=40), _FakeCam(period=0.005)]
    opened = []

    def open_cam():
        cam = cams[min(len(opened), len(cams) - 1)]
        opened.append(cam)
        return cam
    try:
        rec = sv.VideoRecorder(open_cam, d, fps=5,
                               log=lambda m: None).start()
        assert rec.wait_first_frame(3.0)
        rec.set_t0(time.monotonic())
        assert _wait(lambda: rec.stream_returns == 1, 8.0), rec.summary()
        n = rec.written
        assert _wait(lambda: rec.written > n, 3.0), "not recording again"
        rec.end_recording()
        rec.stop(timeout=5.0)
        assert rec.reopens == 1, rec.summary()
        assert rec.end_outcome() == (
            f"recorded {rec.written} frames, {rec.first_t:.1f} to "
            f"{rec.last_t:.1f} s on the run's clock; the camera stream "
            f"dropped out for ~2 s or more and came back 1x")
        rec.stream_returns = 0                   # reopened, never came back
        assert 'came back' not in rec.end_outcome()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_end_outcome_counts_the_frames_before_an_encoder_failure():
    _need_cv()
    import cv2
    real = cv2.VideoWriter

    class FailsOnTheFourth:
        def __init__(self, *a, **k):
            self.n = 0

        def isOpened(self):
            return True

        def write(self, img):
            self.n += 1
            if self.n == 4:
                raise cv2.error("Unknown C++ exception from OpenCV code")

        def release(self):
            pass
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        cv2.VideoWriter = FailsOnTheFourth
        try:
            rec = sv.VideoRecorder(lambda: _FakeCam(), d, fps=5,
                                   log=lambda m: None).start()
            assert rec.wait_first_frame(3.0)
            rec.set_t0(time.monotonic())
            assert _wait(lambda: rec.error is not None, 5.0)
            rec.end_recording()
            rec.stop(timeout=5.0)
        finally:
            cv2.VideoWriter = real
        assert rec.written == 3, rec.written
        assert rec.end_outcome() == (
            f"recorded 3 frames, {rec.first_t:.1f} to {rec.last_t:.1f} s on "
            f"the run's clock, then stopped: encoder failed: Unknown C++ "
            f"exception from OpenCV code")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_end_outcome_while_the_encoder_is_still_writing():
    """stop() gave up on an encoder that was still writing: the line gives
    the count so far, says the encoder was still at it and where the final
    count is; once it has finished, the final count, dropped frames
    counted."""
    _need_cv()
    d = tempfile.mkdtemp(prefix='sldea_video_test_')
    try:
        def slow_kv(t):                 # runs on the WRITER, per frame
            time.sleep(0.4)
            return 0.0
        rec = sv.VideoRecorder(lambda: _FakeCam(period=0.01), d, fps=5,
                               kv_at=slow_kv, queue_max=1,
                               log=lambda m: None).start()
        assert rec.wait_first_frame(3.0)
        rec.set_t0(time.monotonic())
        time.sleep(1.0)
        rec.end_recording()
        rec.stop(timeout=0.1)
        busy = rec.end_outcome()
        assert rec.wait_finished(10.0), "the encoder never exited"
        assert 'the encoder was still writing then, so video_frames.csv ' \
               'has the final count' in busy, busy
        so_far = busy.split(' ', 1)[0]           # the count kept growing
        assert busy.startswith(f"{so_far} frames recorded by the end of the "
                               f"run") and int(so_far) <= rec.written, busy
        done = rec.end_outcome()
        assert done.startswith(f"recorded {rec.written} frames, "), done
        assert rec.dropped > 0 and done.endswith(
            f"; {rec.dropped} frames dropped"), done
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_end_outcome_is_one_line_of_ascii():
    """The tab appends it to setup.txt through a locale-encoded open, as it
    does the start line, and setup.txt is read line by line: a newline or
    a non-ASCII character in an error must not break either."""
    rec = sv.VideoRecorder(lambda: _FakeCam(), tempfile.gettempdir())
    rec.error = "encoder failed: café\n  second line"
    assert rec.end_outcome() == \
        "NOT recorded: encoder failed: caf? second line"


# ---------------------------------------------------------------- finalize

def _staged(d, names=(sv.VIDEO_FILENAME, sv.VIDEO_INDEX_FILENAME)):
    os.makedirs(d, exist_ok=True)
    for name in names:
        with open(os.path.join(d, name), 'w') as f:
            f.write('x' * 1000)
    return d


def test_finalize_moves_the_files_and_says_where_a_failure_left_them():
    root = tempfile.mkdtemp(prefix='sldea_video_fin_')
    try:
        stage = _staged(os.path.join(root, 'stage'))
        run = os.path.join(root, 'run')
        os.makedirs(run)
        logs = []
        moved = sv.finalize(stage, run, log=logs.append)
        assert moved == {
            sv.VIDEO_FILENAME: os.path.join(run, sv.VIDEO_FILENAME),
            sv.VIDEO_INDEX_FILENAME: os.path.join(run,
                                                  sv.VIDEO_INDEX_FILENAME)}
        assert not os.path.exists(stage), "empty staging dir left behind"
        assert len(logs) == 2, "every file is reported"
        # a destination that is not there: nothing lost, and it SAYS so
        stage2 = _staged(os.path.join(root, 'stage2'),
                         (sv.VIDEO_FILENAME,))
        logs = []
        moved = sv.finalize(stage2, os.path.join(root, 'no', 'such'),
                            log=logs.append)
        assert moved == {sv.VIDEO_FILENAME: None,
                         sv.VIDEO_INDEX_FILENAME: None}
        assert os.path.exists(os.path.join(stage2, sv.VIDEO_FILENAME))
        assert any(stage2 in m for m in logs), logs
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_move_across_volumes_goes_through_part_and_never_truncates():
    """A rename cannot cross volumes (staging is local, the run folder is
    usually the share), so finalize copies -- to .part, renamed only when
    complete. An interrupted copy leaves the original intact and an
    obvious .part, never a truncated video.mkv (F12)."""
    root = tempfile.mkdtemp(prefix='sldea_video_fin_')
    real_replace, real_copy = sv.os.replace, sv._copy_throttled
    try:
        stage = _staged(os.path.join(root, 'stage'))
        run = os.path.join(root, 'run')
        os.makedirs(run)

        def cross_device(src, dst):
            if os.path.dirname(os.path.abspath(src)) == \
                    os.path.abspath(stage):
                raise OSError(18, 'Invalid cross-device link')
            return real_replace(src, dst)
        sv.os.replace = cross_device
        moved = sv.finalize(stage, run, log=lambda m: None, max_bps=None)
        assert all(moved.values()), moved
        assert sorted(os.listdir(run)) == sorted(
            (sv.VIDEO_FILENAME, sv.VIDEO_INDEX_FILENAME)), os.listdir(run)
        # now a copy that dies half way
        stage = _staged(os.path.join(root, 'stage3'), (sv.VIDEO_FILENAME,))
        run2 = os.path.join(root, 'run2')
        os.makedirs(run2)

        def dying_copy(src, dst, max_bps=None, chunk=0):
            with open(dst, 'wb') as f:
                f.write(b'half')
            raise OSError(5, 'share went away')
        sv._copy_throttled = dying_copy
        moved = sv.finalize(stage, run2, log=lambda m: None)
        assert moved[sv.VIDEO_FILENAME] is None
        assert not os.path.exists(os.path.join(run2, sv.VIDEO_FILENAME)), \
            "a truncated video.mkv reached the run folder"
        assert os.path.exists(os.path.join(stage, sv.VIDEO_FILENAME))
    finally:
        sv.os.replace, sv._copy_throttled = real_replace, real_copy
        shutil.rmtree(root, ignore_errors=True)


# --------------------------------------------------------- detect_video

def _scene(r, rng, size=(240, 320)):
    """sldea_diag's synthetic rig: a brighter disc that grows with voltage,
    structure on both axes, sensor noise."""
    import numpy as np
    h, w = size
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.full((h, w), 90.0, np.float32)
    img[np.abs(xx - 20) < 6] = 230.0
    img[np.abs(yy - 18) < 5] = 215.0
    if r:
        img[(xx - 160) ** 2 + (yy - 120) ** 2 <= r * r] += 34
    img += rng.normal(0, 1.6, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def _write_video(folder, n, rng):
    import cv2
    os.makedirs(folder, exist_ok=True)
    vw = cv2.VideoWriter(os.path.join(folder, sv.VIDEO_FILENAME),
                         cv2.VideoWriter_fourcc(*sv.VIDEO_FOURCC), 1.0,
                         (320, 240), isColor=False)
    with open(os.path.join(folder, sv.VIDEO_INDEX_FILENAME), 'w',
              newline='') as f:
        w = csv.writer(f)
        w.writerow(sv.INDEX_COLUMNS)
        buf = None
        try:
            for i in range(n):
                # through ffmpeg_safe, as the recorder writes: a raw
                # 320 x 240 frame is in place for FFmpeg's read past its
                # end, which threw in about one process in five here
                # (Windows, OpenCV 4.13, measured 2026-10-06)
                safe, buf = sv.ffmpeg_safe(_scene(30 + 6 * i, rng), buf)
                vw.write(safe)
                w.writerow([i, 2.0 + i, 0.5 * i, '', i + 1])
        except cv2.error as e:
            # still reported as could-not-run, never as a pass or a
            # failure, should an OpenCV fail here for another reason
            vw.release()
            raise _Skip(f"this OpenCV's {sv.VIDEO_FOURCC} writer failed "
                        f"mid-file: {e}")
    vw.release()


def _video_run(n=8, video=True):
    """A run folder with a baseline still, data.csv, setup.txt and (with
    `video`) an FFV1 recording of a disc growing over `n` frames."""
    import cv2
    import numpy as np
    rng = np.random.default_rng(7)
    d = tempfile.mkdtemp(prefix='sldea_video_run_')
    os.makedirs(os.path.join(d, 'frames'))
    cv2.imwrite(os.path.join(d, 'frames', 'base.png'), _scene(0, rng))
    with open(os.path.join(d, 'data.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['snapshot', 'step', 'tag',
                                          'nominal_kV', 'frame_file'])
        w.writeheader()
        w.writerow({'snapshot': 1, 'step': 0, 'tag': 'baseline',
                    'nominal_kV': 0, 'frame_file': 'base.png'})
    with open(os.path.join(d, 'setup.txt'), 'w') as f:
        f.write('DEA nominal diameter: 16 mm\n')
    if video:
        _write_video(d, n, rng)
    return d


def test_detect_video_runs_the_stills_detector_on_every_frame():
    _need_cv()
    d = _video_run(8)
    try:
        s = sv.detect_video(d, log=lambda m: None, plot=False)
        rows = _read_csv(os.path.join(d, sv.VIDEO_EDGES_FILENAME))
        assert list(rows[0]) == sv.EDGE_COLUMNS
        assert [int(r['frame']) for r in rows] == list(range(8))
        # time and kV come from the index, not from guesses
        assert [float(r['t_s']) for r in rows] == [2.0 + i for i in range(8)]
        assert [float(r['nominal_kV']) for r in rows] == [0.5 * i
                                                          for i in range(8)]
        found = [(int(r['frame']), float(r['area_px'])) for r in rows
                 if r['area_px']]
        assert len(found) >= 6, rows
        assert found[-1][1] > found[0][1], "the disc grew; the area did not"
        assert all(r['scale_source'] for r in rows)
        assert s['frames'] == 8 and s['csv'].endswith(sv.VIDEO_EDGES_FILENAME)
        # a stride and a limit
        sv.detect_video(d, stride=3, log=lambda m: None, plot=False)
        rows = _read_csv(os.path.join(d, sv.VIDEO_EDGES_FILENAME))
        assert [int(r['frame']) for r in rows] == [0, 3, 6]
        sv.detect_video(d, limit=2, log=lambda m: None, plot=False)
        assert len(_read_csv(os.path.join(d, sv.VIDEO_EDGES_FILENAME))) == 2
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_detect_video_draws_its_figure_and_refuses_without_a_baseline():
    _need_cv()
    d = _video_run(4)
    try:
        s = sv.detect_video(d, log=lambda m: None, plot=True)
        assert s.get('png') and os.path.getsize(s['png']) > 1000
        os.remove(os.path.join(d, 'frames', 'base.png'))
        try:
            sv.detect_video(d, log=lambda m: None, plot=False)
        except RuntimeError as e:
            assert 'baseline' in str(e)
        else:
            raise AssertionError("no baseline must be refused, loudly")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_finalize_job_detects_on_the_local_copy_then_moves_it_in():
    _need_cv()
    import numpy as np
    run = _video_run(video=False)
    stage = tempfile.mkdtemp(prefix='sldea_video_stage_')
    try:
        _write_video(stage, 4, np.random.default_rng(3))
        assert sv.main(['--finalize', stage, run, '--detect']) == 0
        assert len(_read_csv(os.path.join(run, sv.VIDEO_EDGES_FILENAME))) \
            == 4
        for name in (sv.VIDEO_FILENAME, sv.VIDEO_INDEX_FILENAME):
            assert os.path.exists(os.path.join(run, name)), name
        with open(os.path.join(run, 'run.log'), encoding='utf-8') as f:
            text = f.read()
        assert 'video edges:' in text and 'is in the run folder' in text
        assert sv.main(['--finalize', stage]) == 2
    finally:
        shutil.rmtree(run, ignore_errors=True)
        shutil.rmtree(stage, ignore_errors=True)


def test_the_cli_says_what_it_did():
    _need_cv()
    d = _video_run(3)
    try:
        assert sv.main([d, '--stride', '2', '--no-plot']) == 0
        assert len(_read_csv(os.path.join(d, sv.VIDEO_EDGES_FILENAME))) == 2
        assert sv.main([d, '--stride', 'x']) == 2
        assert sv.main(['--bogus']) == 2
        assert sv.main([os.path.join(d, 'frames')]) == 2      # no video
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ------------------------------------- review by exception (2026-10-06)

def _edge(frame, t, area, review=False, method='disc-fit', kv=1.0):
    return {'frame': frame, 't_s': t, 'nominal_kV': kv, 'area_px': area,
            'area_mm2': None, 'conf': 0.9, 'method': method, 'wrinkle': 1.0,
            'needs_review': review, 'scale_source': 'x'}


def test_review_flags_send_only_doubt_and_disagreement_to_a_human():
    """A landing bracketed by two accepted stills (t 10 and 14, areas 1000
    and 1010) passes frames inside its 2 % band and flags one outside it;
    the detector's own doubt and a frame with no area are flagged whatever
    the stills say; outside any landing a 2 % step from the neighbours is
    a 'jump' and a smooth ramp is not."""
    cks = [{'frame_file': 'a.png', 'tag': 'post-ramp', 'step': '3',
            'nominal_kV': 1.0, 't_s': 10.0, 'area_px': 1000.0},
           {'frame_file': 'b.png', 'tag': 'pre-ramp', 'step': '3',
            'nominal_kV': 1.0, 't_s': 14.0, 'area_px': 1010.0}]
    edges = [_edge(0, 4.0, 900.0), _edge(1, 5.0, 905.0),
             _edge(2, 6.0, 960.0),                    # ramp: +6 % jump
             _edge(3, 7.0, 965.0), _edge(4, 8.0, 970.0),
             _edge(5, 10.0, 1001.0), _edge(6, 11.0, 1000.0),
             _edge(7, 12.0, 1050.0),                  # +4 % off the band
             _edge(8, 13.0, 1005.0, review=True),     # detector doubts it
             _edge(9, 14.0, None, method=''),         # no edge
             _edge(10, 15.0, 1012.0)]                 # last landing frame
    flags = sv.review_flags(edges, cks)
    by = {f['frame']: f['reasons'] for f in flags}
    assert by[5] == [] and by[6] == [] and by[10] == [], by
    assert by[7] == ['off-stills'], by
    assert by[8] == ['detector'], by
    assert by[9] == ['no edge'], by
    assert 'jump' in by[2], by
    assert by[0] == [] and by[4] == [], by
    band = next(f['band'] for f in flags if f['frame'] == 6)
    assert abs(band[0] - 980.0) < 1e-6 and abs(band[1] - 1030.2) < 1e-6, \
        band
    # with no stills at all, only doubt and jumps are left to flag
    bare = {f['frame']: f['reasons'] for f in sv.review_flags(edges, [])}
    assert bare[7] == ['jump'] and bare[6] == [], bare


def test_a_run_wide_video_offset_is_divided_out_and_a_local_error_is_not():
    """The video's baseline fit comes from another decode than the stills',
    so its areas can sit a percent or so off theirs on every frame
    (13_backlight_2: -1.19 %). still_offset measures that ratio, the bands
    are scaled by it, and a single frame that is off still is off."""
    cks = [{'frame_file': f'{k}.png', 'tag': 'post-ramp', 'step': str(k),
            'nominal_kV': 0.2 * k, 't_s': 10.0 * k, 'area_px': 1000.0 + k}
           for k in range(1, 6)]
    edges = []
    for k in range(1, 6):
        for j in range(3):
            edges.append(_edge(len(edges), 10.0 * k + j - 1.0,
                               (1000.0 + k) * 0.975))
    off = sv.still_offset(edges, cks)
    assert abs(off - 0.975) < 1e-9, off
    raw = sv.review_flags(edges, cks, offset=None)
    assert all('off-stills' in f['reasons'] for f in raw
               if f['band'] is not None), raw
    flags = sv.review_flags(edges, cks)          # 'auto'
    assert not any(f['reasons'] for f in flags), flags
    edges[7]['area_px'] *= 1.05                  # one frame really is off
    flags = sv.review_flags(edges, cks)
    assert [f['frame'] for f in flags if f['reasons']] == [7], flags
    assert sv.still_offset(edges[:2], cks) is None   # too few matches


def test_still_checkpoints_take_the_stream_frame_time_from_run_log():
    """Accepted = data.csv holds an area. The time is the stream frame's,
    from run.log, under the still's original name even after a breakdown
    mark renamed it; without the line, the planned time; rows with no
    area are not checkpoints."""
    d = tempfile.mkdtemp(prefix='sldea_ck_')
    try:
        os.makedirs(os.path.join(d, 'frames'))
        cols = ['snapshot', 'step', 'tag', 'nominal_kV', 't_planned_s',
                'frame_file', 'active_area_px']
        with open(os.path.join(d, 'data.csv'), 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerow({'snapshot': 1, 'step': 0, 'tag': 'baseline',
                        'nominal_kV': 0, 't_planned_s': 2.0,
                        'frame_file': 's00.png', 'active_area_px': 1000})
            w.writerow({'snapshot': 2, 'step': 1, 'tag': 'post-ramp',
                        'nominal_kV': 0.2, 't_planned_s': 9.0,
                        'frame_file': 's01_BREAKDOWN.png',
                        'active_area_px': 1010})
            w.writerow({'snapshot': 3, 'step': 1, 'tag': 'pre-ramp',
                        'nominal_kV': 0.2, 't_planned_s': 16.0,
                        'frame_file': 's01b.png', 'active_area_px': ''})
            w.writerow({'snapshot': 4, 'step': 2, 'tag': 'post-ramp',
                        'nominal_kV': 0.4, 't_planned_s': 24.0,
                        'frame_file': 's02.png', 'active_area_px': 1020})
        with open(os.path.join(d, 'run.log'), 'w', encoding='utf-8') as f:
            f.write("[20:39:17] snap s00 0.00 kV [baseline]  meas -0.02 kV "
                    "/ 1 µA  → s00.png  (frame t=2.12s)\n")
            f.write("[20:39:24] snap s01 0.20 kV [post-ramp]  meas 0.20 kV "
                    "/ -1 µA  → s01.png  (frame t=9.05s)\n")
        cks = sv.still_checkpoints(d)
        assert [c['frame_file'] for c in cks] == \
            ['s00.png', 's01_BREAKDOWN.png', 's02.png'], cks
        assert [c['t_s'] for c in cks] == [2.12, 9.05, 24.0], cks
        assert [c['area_px'] for c in cks] == [1000.0, 1010.0, 1020.0]
        assert [c['step'] for c in cks] == ['0', '1', '2']
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_video_pass_stamps_its_inputs_and_says_what_went_stale():
    """video_edges.json records what the pass ran with; edges_stale reads
    it back as None while nothing moved, and names each input that did:
    a partial pass, a settings change, a scale anchor saved since."""
    _need_cv()
    import sldea_edge as se
    d = _video_run(4)
    try:
        assert sv.edges_stale(d) == "there are no video edges yet"
        sv.detect_video(d, log=lambda m: None, plot=False)
        stamp = sv.read_stamp(d)
        assert stamp and stamp['stride'] == 1 and stamp['limit'] is None
        assert stamp['area_estimator'] == se.AREA_ESTIMATOR_VERSION
        assert sv.edges_stale(d) is None
        sv.detect_video(d, stride=2, log=lambda m: None, plot=False)
        assert 'every 2th frame' in sv.edges_stale(d)
        sv.detect_video(d, log=lambda m: None, plot=False)
        s = se.load_settings(d)
        s['min_diff'] = float(s['min_diff']) + 1.0
        se.save_settings(d, s)
        why = sv.edges_stale(d)
        assert why and 'min_diff' in why, why
        sv.detect_video(d, log=lambda m: None, plot=False)
        assert sv.edges_stale(d) is None
        se.save_scale_anchor(d, {'method': se.ANCHOR_METHOD_MANUAL,
                                 'diam_px': 120.0, 'diam_mm': 16.0,
                                 'mm_per_px': 16.0 / 120.0})
        why = sv.edges_stale(d)
        assert why and 'scale anchor changed (none -> 120.0 px)' in why, why
        # a stamp that is missing is a stale pass, never a current one
        os.remove(os.path.join(d, sv.VIDEO_STAMP_FILENAME))
        assert 'before the video pass recorded' in sv.edges_stale(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_failed_pass_leaves_the_previous_edges_whole():
    """The rows go to a .part file renamed into place at the end, so a pass
    that dies half way leaves the previous video_edges.csv untouched."""
    _need_cv()
    d = _video_run(4)
    real = sv.iter_frames
    try:
        sv.detect_video(d, log=lambda m: None, plot=False)
        with open(os.path.join(d, sv.VIDEO_EDGES_FILENAME), 'rb') as f:
            before = f.read()

        def dies(path):
            for i, g in real(path):
                if i == 2:
                    raise OSError("decoder lost the file")
                yield i, g
        sv.iter_frames = dies
        try:
            sv.detect_video(d, log=lambda m: None, plot=False)
        except OSError:
            pass
        else:
            raise AssertionError("the decoder error must surface")
        with open(os.path.join(d, sv.VIDEO_EDGES_FILENAME), 'rb') as f:
            assert f.read() == before
        assert not [n for n in os.listdir(d) if n.endswith('.part')], \
            os.listdir(d)
    finally:
        sv.iter_frames = real
        shutil.rmtree(d, ignore_errors=True)


def test_after_save_reruns_stale_edges_detached_and_only_then():
    """No video in the folder: nothing to say, nothing started. Stale
    edges: a detached `--after-save` job. Current edges: said, not
    re-run."""
    _need_cv()
    calls = []

    def popen(cmd, **kw):
        calls.append((cmd, kw))
        return None
    bare = _video_run(video=False)
    d = _video_run(3)
    try:
        assert sv.after_save(bare, popen=popen) is None and not calls
        msg = sv.after_save(d, popen=popen)
        assert msg.startswith('video edges re-running in the background'), \
            msg
        assert 'there are no video edges yet' in msg
        cmd, kw = calls[-1]
        assert cmd[-2:] == [d, '--after-save'], cmd
        assert cmd[1].endswith('sldea_video.py'), cmd
        if os.name == 'nt':
            assert kw['creationflags'], kw
        else:
            assert kw['start_new_session'] is True, kw
        assert kw['env']['PYTHONIOENCODING'] == 'utf-8'
        sv.detect_video(d, log=lambda m: None, plot=False)
        n = len(calls)
        assert sv.after_save(d, popen=popen) == 'video edges are current'
        assert len(calls) == n
    finally:
        shutil.rmtree(bare, ignore_errors=True)
        shutil.rmtree(d, ignore_errors=True)


def test_the_after_save_job_says_why_and_what_in_run_log():
    _need_cv()
    d = _video_run(3)
    try:
        assert sv.main([d, '--after-save', '--no-plot']) == 0
        with open(os.path.join(d, 'run.log'), encoding='utf-8') as f:
            text = f.read()
        assert 're-running after Save (there are no video edges yet)' \
            in text, text
        assert 'flagged for review against 0 accepted still(s)' in text, text
        assert sv.edges_stale(d) is None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_decisions_round_trip_and_a_decision_on_a_changed_area_is_dropped():
    d = tempfile.mkdtemp(prefix='sldea_dec_')
    try:
        assert sv.read_decisions(d) == ({}, 0)
        dec = {3: {'frame': 3, 't_s': 5.0, 'decision': 'accept',
                   'area_px': 1000.0, 'reasons': 'jump', 'user': 'u',
                   'when': 'w'},
               5: {'frame': 5, 't_s': 7.0, 'decision': 'reject',
                   'area_px': None, 'reasons': 'no edge', 'user': 'u',
                   'when': 'w'}}
        sv.write_decisions(d, dec)
        got, dropped = sv.read_decisions(d)
        assert dropped == 0 and set(got) == {3, 5}
        assert got[3]['decision'] == 'accept' and got[3]['area_px'] == 1000.0
        assert got[5]['area_px'] is None
        # the detector re-ran: frame 3 now reads 1004 px, frame 5 is gone
        edges = [_edge(3, 5.0, 1004.0)]
        got, dropped = sv.read_decisions(d, edges)
        assert got == {} and dropped == 2, (got, dropped)
        edges = [_edge(3, 5.0, 1000.2), _edge(5, 7.0, None, method='')]
        got, dropped = sv.read_decisions(d, edges)
        assert set(got) == {3, 5} and dropped == 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_figure_sorts_frames_by_what_a_reader_must_do():
    """A decision outranks a flag; flagged frames are apart from clear
    ones; frames with no area are left out; the stills are their own
    series."""
    edges = [_edge(0, 1.0, 100.0), _edge(1, 2.0, 101.0),
             _edge(2, 3.0, 150.0), _edge(3, 4.0, 160.0),
             _edge(4, 5.0, None, method='')]
    flags = [{'frame': i, 'reasons': r} for i, r in
             enumerate([[], [], ['jump'], ['jump'], ['no edge']])]
    dec = {3: {'decision': 'reject'}, 0: {'decision': 'accept'}}
    cks = [{'t_s': 1.0, 'area_px': 100.0, 'frame_file': 'a.png'}]
    s = sv.plot_series(edges, flags, cks, dec)
    assert [p[2] for p in s['clear']] == [1]
    assert [p[2] for p in s['flagged']] == [2]
    assert [p[2] for p in s['accepted']] == [0]
    assert [p[2] for p in s['rejected']] == [3]
    assert s['stills'] == [(1.0, 100.0, 'a.png')]
    assert len(s['kv']) == 5
    styles = {k[0]: k[2] for k in sv.SERIES_STYLE}
    assert len(set(styles.values())) == len(styles), \
        "every series needs its own marker shape, not just a colour"


# ------------------------------------------------ the real run worker

class _FakeSG:
    """Records every call, stamped, so the order of shutdown is visible."""

    def __init__(self, events):
        self.events = events

    def __getattr__(self, name):
        def call(*a, **k):
            self.events.append((time.monotonic(), 'sg.' + name, a, k))
        return call


class _StubApp:
    """Just enough app for _sldea_worker (the pattern of
    test_sldea_telemetry): no Tk, no scope."""
    import gui as _gui
    _G = _gui.InstrumentControlGUI
    SLDEA_POLL_S = _G.SLDEA_POLL_S
    SLDEA_STAMP_LEAD_S = _G.SLDEA_STAMP_LEAD_S
    SLDEA_STILL_WAIT_S = _G.SLDEA_STILL_WAIT_S
    _sldea_worker = _G._sldea_worker
    _sldea_capture = _G._sldea_capture
    _sldea_run_logger = _G._sldea_run_logger

    @property
    def _sldea_video_postrun(self):
        """The real post-run job, wrapped so _drive can wait for it and
        for the detached move it starts. The worker looks this up on its
        own thread while starting the post-run thread, so the Event exists
        before the worker returns. A test that deleted its folder while
        the job still wrote into it failed with WinError 145 "The
        directory is not empty" (2 of 14 runs of origin/main under load,
        2026-10-06)."""
        done = threading.Event()
        self.postruns.append(done)

        def run(*a, **k):
            try:
                self._G._sldea_video_postrun(self, *a, **k)
                for proc in list(self._sldea_video_jobs):
                    proc.wait(timeout=120)
            finally:
                done.set()
        return run

    def __init__(self, sg=None):
        import types
        self.scope, self.sg = None, sg
        self._sldea_stop = False
        self._sldea_bd_tripped = False
        self._sldea_elapsed = 0.0
        self._sldea_prelog, self._sldea_runlog = [], None
        self._sldea_loglock = threading.Lock()
        self._sldea_recorder = None
        self._sldea_video_jobs = []
        self.postruns = []
        self.lines = []
        self.statuses = []
        self.finished = 0
        self.root = types.SimpleNamespace(after=self._after)

    def _after(self, _ms, fn=None, *a):
        # run _sldea_finished for real (it is what releases the tab);
        # everything else is Tk-only and stays a no-op here
        if getattr(fn, '__name__', '') == '_sldea_finished':
            fn()

    def _sldea_log(self, msg):
        self.lines.append(str(msg))

    def _sldea_set_status(self, *a, **k):
        self.statuses.append(a[0] if a else '')

    def _sldea_finished(self):
        self.finished += 1


def _short_profile():
    from sldea_profile import SldeaProfile
    return SldeaProfile(start_kv=0.0, end_kv=1.0, step_kv=1.0, ramp_s=0.4,
                        landing_s=1.8, settle_s=0.4, snap_lead_s=0.4)


class _Patched:
    """Fake camera + stream + staging for one worker run; restores all."""

    def __init__(self, tmp, stream, oneshot):
        self.tmp, self.stream, self.oneshot = tmp, stream, oneshot

    def __enter__(self):
        import gui
        self.gui = gui
        self.saved = (gui.webcam.resolve_camera, gui.webcam.oneshot_rgb,
                      gui.sldea_video.open_stream,
                      os.environ.get('SCPI_SLDEA_VIDEO_STAGING'))
        gui.webcam.resolve_camera = lambda i: {'kind': 'cv2', 'index': 0}
        gui.webcam.oneshot_rgb = self.oneshot
        gui.sldea_video.open_stream = self.stream
        os.environ['SCPI_SLDEA_VIDEO_STAGING'] = os.path.join(self.tmp,
                                                              'staging')
        return self

    def __exit__(self, *exc):
        gui = self.gui
        (gui.webcam.resolve_camera, gui.webcam.oneshot_rgb,
         gui.sldea_video.open_stream) = self.saved[:3]
        if self.saved[3] is None:
            os.environ.pop('SCPI_SLDEA_VIDEO_STAGING', None)
        else:
            os.environ['SCPI_SLDEA_VIDEO_STAGING'] = self.saved[3]
        return False


def _drive(app, tmp, stream, oneshot, dry=True, override=True,
           cam_expected=False):
    # _FakeCam's frames are flat by construction (uniform planes and one
    # moving line), and since #348 a flat baseline stops the run. The
    # plumbing tests start as an operator would on a faint device: with
    # the pre-flight override, which keeps the baseline check and its log
    # line but not its stop (merged 2026-10-06). The baseline-stop tests
    # below pass override=False.
    import sldea_profile
    pov = sldea_profile.PREFLIGHT_OVERRIDE_NO_PICTURE if override else ''
    with _Patched(tmp, stream, oneshot):
        app._sldea_worker(
            _short_profile(), tmp, 'RUN', 1, 2, 3, dry, tel_on=False,
            vid_on=True, vid_fps=5.0, picture_override=pov,
            cam_expected=cam_expected)
        # the post-run job and its detached move write into the run
        # folder after the worker returns; the caller deletes that folder
        for done in app.postruns:
            assert done.wait(150), "the post-run video job never finished"
    return os.path.join(tmp, 'RUN')


class _FlatCam(_FakeCam):
    """A stream whose every frame is one gray level: no picture at all."""

    def read(self):
        f = super().read()
        return None if f is None else f * 0 + 120


class _DiscCam(_FakeCam):
    """A stream showing a dark disc on a bright field: a real picture."""

    def read(self):
        import numpy as np
        f = super().read()
        if f is None:
            return None
        h, w = f.shape[:2]
        img = np.full((h, w, 3), 200, np.uint8)
        yy, xx = np.mgrid[0:h, 0:w]
        img[(yy - h // 2) ** 2 + (xx - w // 2) ** 2 < (h // 3) ** 2] = 60
        return img


def _stop_recorder_spy(events):
    real_stop = sv.VideoRecorder.stop

    def stop(self, timeout=10.0):
        events.append((time.monotonic(), 'rec.stop', (), {}))
        return real_stop(self, timeout)
    sv.VideoRecorder.stop = stop
    return real_stop


def test_a_flat_video_baseline_stops_a_live_run_with_the_sg_zeroed():
    """#348 meets #359 (merged 2026-10-06). In a video run the baseline
    still comes off the recorder's stream; a flat one stops a LIVE run at
    the baseline, through the stop flag Abort uses: the SG is zeroed and
    switched off before the recorder stops, and only the warm-up and the
    baseline rows are written."""
    _need_cv()
    events = []
    real_stop = _stop_recorder_spy(events)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            app = _StubApp(sg=_FakeSG(events))
            rundir = _drive(app, tmp, lambda spec, fps=10: _FlatCam(),
                            _no_oneshot, dry=False, override=False,
                            cam_expected=True)
            # the recording is moved into the run folder by a thread of
            # its own; wait for it before the folder is deleted
            assert _wait(lambda: os.path.exists(os.path.join(
                rundir, sv.VIDEO_INDEX_FILENAME)) and os.path.exists(
                os.path.join(rundir, sv.VIDEO_FILENAME)), 30), \
                os.listdir(rundir)
            assert app._sldea_stop, app.lines
            assert any('STOPPING NOW' in ln for ln in app.lines), app.lines
            rows = _read_csv(os.path.join(rundir, 'data.csv'))
            assert [r['tag'] for r in rows] == ['warmup', 'baseline'], rows
            names = [e[1] for e in events]
            offs = [e for e in events if e[1] == 'sg.set_offset']
            assert offs and float(offs[-1][2][1]) == 0.0, offs[-3:]
            last_off = max(i for i, e in enumerate(events)
                           if e[1] == 'sg.set_output' and e[2][1] is False)
            assert last_off < names.index('rec.stop'), names
            assert app.finished == 1
    finally:
        sv.VideoRecorder.stop = real_stop


def test_a_video_baseline_with_a_picture_runs_to_the_end():
    """The same LIVE video run on a stream that shows a disc: the
    baseline check passes and every still gets its row."""
    _need_cv()
    events = []
    real_stop = _stop_recorder_spy(events)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            app = _StubApp(sg=_FakeSG(events))
            rundir = _drive(app, tmp, lambda spec, fps=10: _DiscCam(),
                            _no_oneshot, dry=False, override=False,
                            cam_expected=True)
            # the recording is moved into the run folder by a thread of
            # its own; wait for it before the folder is deleted
            assert _wait(lambda: os.path.exists(os.path.join(
                rundir, sv.VIDEO_INDEX_FILENAME)) and os.path.exists(
                os.path.join(rundir, sv.VIDEO_FILENAME)), 30), \
                os.listdir(rundir)
            assert not app._sldea_stop, app.lines
            rows = _read_csv(os.path.join(rundir, 'data.csv'))
            assert len(rows) == len(_short_profile().snapshots), rows
            assert app.finished == 1
    finally:
        sv.VideoRecorder.stop = real_stop


def _no_oneshot(*a, **k):
    raise AssertionError("a one-shot grab in a video run")


def test_a_video_run_takes_its_stills_off_the_stream():
    _need_cv()
    with tempfile.TemporaryDirectory() as tmp:
        app = _StubApp()
        rundir = _drive(app, tmp, lambda spec, fps=10: _FakeCam(),
                        _no_oneshot)
        assert app.finished == 1
        data = _read_csv(os.path.join(rundir, 'data.csv'))
        p = _short_profile()
        assert len(data) == len(p.snapshots)
        for row, snap in zip(data, sorted(p.snapshots,
                                          key=lambda s: s['t'])):
            assert row['frame_file'], row
            assert os.path.exists(os.path.join(rundir, 'frames',
                                               row['frame_file']))
            # no still is a picture from before its scheduled moment
            ft = float(row['notes'].split('video frame t=')[1].rstrip('s'))
            assert ft >= snap['t'] - 1e-6, (snap, row['notes'])
        # the detached job moves the recording in; give it a moment
        index = os.path.join(rundir, sv.VIDEO_INDEX_FILENAME)
        assert _wait(lambda: os.path.exists(index)
                     and os.path.exists(os.path.join(rundir,
                                                     sv.VIDEO_FILENAME)),
                     30), os.listdir(rundir)
        rows = _read_csv(index)
        assert len(rows) >= 5, len(rows)       # ~5 fps over a ~5 s run
        assert all(r['nominal_kV'] != '' for r in rows)
        with open(os.path.join(rundir, 'setup.txt')) as f:
            setup = f.read()
        assert '--- Video ---' in setup
        assert 'Video outcome: recording started' in setup
        assert any(l.startswith('video:') and 'frames recorded' in l
                   for l in app.lines), app.lines
        # how the recording ended (#392), last, after the start line: the
        # video's own frame count, and nothing about stopping
        lines = setup.splitlines()
        assert lines[-2].startswith('Video outcome: recording started'), \
            lines[-3:]
        assert lines[-1].startswith(
            f"Video outcome (end): recorded {len(rows)} frames, "), lines[-1]
        assert lines[-1].endswith(" s on the run's clock"), lines[-1]


def test_a_stream_that_delivers_nothing_falls_back_to_one_shot_stills():
    _need_cv()
    import numpy as np
    with tempfile.TemporaryDirectory() as tmp:
        grabs = []

        def oneshot(*a, **k):
            grabs.append(a)
            return np.full((48, 64, 3), 120, np.uint8)

        def dead(spec, fps=10):
            raise RuntimeError('EBUSY')
        app = _StubApp()
        rundir = _drive(app, tmp, dead, oneshot)
        data = _read_csv(os.path.join(rundir, 'data.csv'))
        assert grabs and all(r['frame_file'] for r in data), \
            "the snapshots were lost along with the video"
        assert not os.path.exists(os.path.join(rundir, sv.VIDEO_FILENAME))
        assert any('NO recording' in l for l in app.lines), app.lines
        with open(os.path.join(rundir, 'setup.txt')) as f:
            assert 'Video outcome: NOT recorded' in f.read()
        assert not os.listdir(os.path.join(tmp, 'staging')), \
            "an empty staging dir was left behind"


def test_a_camera_setup_that_fails_says_so_in_setup_txt():
    """#392 review: with no camera attached the stream fails to open and
    the branch above writes its NOT recorded line. Only a camera setup
    that raises (no spec at all) wrote nothing, and setup.txt kept its
    promise of a video.mkv. The run still goes on without frames, as it
    always did; setup.txt now ends "NOT recorded: camera setup failed"."""
    import gui
    with tempfile.TemporaryDirectory() as tmp:
        app = _StubApp()

        def broken(index):
            raise RuntimeError('v4l2-ctl went away')
        with _Patched(tmp, lambda spec, fps=10: _FakeCam(), _no_oneshot):
            gui.webcam.resolve_camera = broken     # _Patched puts it back
            app._sldea_worker(_short_profile(), tmp, 'RUN', 1, 2, 3, True,
                              tel_on=False, vid_on=True, vid_fps=5.0)
        rundir = os.path.join(tmp, 'RUN')
        assert app.finished == 1, app.lines
        assert any('camera setup failed (v4l2-ctl went away)' in ln
                   for ln in app.lines), app.lines
        with open(os.path.join(rundir, 'setup.txt')) as f:
            lines = f.read().splitlines()
        assert lines[-1] == "Video outcome: NOT recorded: camera setup " \
            "failed", lines[-3:]
        assert not os.path.exists(os.path.join(tmp, 'staging'))
        data = _read_csv(os.path.join(rundir, 'data.csv'))
        assert data and not any(r['frame_file'] for r in data), data


def test_the_last_still_gets_its_row_even_when_its_frame_never_comes():
    """Adversarial review 2026-10-05: the loop ends 0.3 s after the
    staircase, the final pre-ramp is snap_lead_s before it, and a stream
    still waits up to STILL_WAIT_S for its frame -- so a last still with no
    frame in time was DROPPED: no data.csv row at all. Here the camera
    stops delivering well before the last still. Every scheduled still
    must still have its row; the last one is a NO FRAME row (blank
    frame_file), and the run still ends complete with N/N."""
    _need_cv()
    p = _short_profile()
    snaps = sorted(p.snapshots, key=lambda s: s['t'])
    with tempfile.TemporaryDirectory() as tmp:
        first_open = []

        class _StopsEarly(_FakeCam):
            # frames until shortly before the last still, then nothing,
            # for this stream and any the reader reopens
            def read(self):
                if time.monotonic() > first_open[0] + snaps[-1]['t'] - 0.6:
                    time.sleep(self.period)
                    return None
                return super().read()

        def stream(spec, fps=10):
            if not first_open:
                first_open.append(time.monotonic())
            return _StopsEarly()

        app = _StubApp()
        rundir = _drive(app, tmp, stream, _no_oneshot)
        data = _read_csv(os.path.join(rundir, 'data.csv'))
        assert len(data) == len(snaps), (len(data), len(snaps), app.lines)
        assert data[-1]['frame_file'] == '', data[-1]
        assert data[-1]['tag'] == snaps[-1]['tag'], data[-1]
        assert data[0]['frame_file'], data[0]
        assert any(l == f"run complete: {len(snaps)}/{len(snaps)} frames"
                   for l in app.lines), app.lines


def test_the_sg_is_zeroed_before_the_recorder_is_stopped():
    """A LIVE run's shutdown order, with a fake SG: nothing about the
    video may come before the HV is at zero."""
    _need_cv()
    events = []
    real_stop = sv.VideoRecorder.stop

    def stop(self, timeout=10.0):
        events.append((time.monotonic(), 'rec.stop', (), {}))
        return real_stop(self, timeout)
    sv.VideoRecorder.stop = stop
    try:
        with tempfile.TemporaryDirectory() as tmp:
            app = _StubApp(sg=_FakeSG(events))
            _drive(app, tmp, lambda spec, fps=10: _FakeCam(), _no_oneshot,
                   dry=False)
            names = [e[1] for e in events]
            assert 'sg.set_output' in names and 'rec.stop' in names, names
            last_off = max(i for i, e in enumerate(events)
                           if e[1] == 'sg.set_output' and e[2][1] is False)
            assert last_off < names.index('rec.stop'), names
            assert app.finished == 1
    finally:
        sv.VideoRecorder.stop = real_stop


def test_the_tab_is_released_even_when_the_video_shutdown_throws():
    _need_cv()
    real_stop = sv.VideoRecorder.stop

    def boom(self, timeout=10.0):
        real_stop(self, 1.0)
        raise RuntimeError('encoder exploded')
    sv.VideoRecorder.stop = boom
    try:
        with tempfile.TemporaryDirectory() as tmp:
            app = _StubApp()
            _drive(app, tmp, lambda spec, fps=10: _FakeCam(), _no_oneshot)
            assert app.finished == 1, "the tab was left 'running'"
            assert any('video shutdown failed' in l for l in app.lines)
    finally:
        sv.VideoRecorder.stop = real_stop


def test_an_abort_during_camera_startup_never_switches_the_sg_on():
    _need_cv()
    events = []
    with tempfile.TemporaryDirectory() as tmp:
        app = _StubApp(sg=_FakeSG(events))

        def aborting_stream(spec, fps=10):
            app._sldea_stop = True           # the operator hit Abort
            return _FakeCam()
        _drive(app, tmp, aborting_stream, _no_oneshot, dry=False)
        assert not [e for e in events if e[1] == 'sg.set_output'
                    and e[2][1] is True], [e[1:3] for e in events]
        assert app.finished == 1


def test_a_stream_size_the_codec_cannot_record_stops_the_run_before_hv():
    """2026-10-06: the codec is checked at the stream's OWN size, with its
    own frame, before the SG output is switched on. A LIVE run whose
    camera delivers a size FFV1 cannot record losslessly (odd, here)
    stops there: the SG output is never switched on, the SG is still
    zeroed and switched off on the way out, nothing is recorded or
    shot, and setup.txt, run.log and the status line say why."""
    _need_cv()
    events = []
    with tempfile.TemporaryDirectory() as tmp:
        app = _StubApp(sg=_FakeSG(events))
        rundir = _drive(app, tmp,
                        lambda spec, fps=10: _FakeCam(shape=(96, 129)),
                        _no_oneshot, dry=False)
        assert app.finished == 1
        assert app._sldea_stop, app.lines
        assert not [e for e in events if e[1] == 'sg.set_output'
                    and e[2][1] is True], [e[1:3] for e in events]
        offs = [e for e in events if e[1] == 'sg.set_output']
        assert offs and offs[-1][2][1] is False, [e[1:3] for e in events]
        assert any('run stopped before any HV' in ln and '129 x 96' in ln
                   and 'never switched on' in ln for ln in app.lines), \
            app.lines
        assert any(ln.startswith('run aborted: 0/') for ln in app.lines), \
            app.lines
        assert any(s.startswith('STOPPED before HV') for s in app.statuses), \
            app.statuses
        assert _read_csv(os.path.join(rundir, 'data.csv')) == []
        assert not os.path.exists(os.path.join(rundir, sv.VIDEO_FILENAME))
        with open(os.path.join(rundir, 'setup.txt')) as f:
            setup = f.read()
        assert ('Video outcome: NOT recorded: the codec check at the '
                "camera's frame size failed (FFV1 at 129 x 96") in setup, \
            setup
        assert 'stopped before any HV' in setup
        assert not os.listdir(os.path.join(tmp, 'staging')), \
            "an empty staging dir was left behind"
        # registered before it was stopped, so the camera guards that ask
        # reader_alive() would have seen a reader that outlasted stop()
        assert app._sldea_recorder is not None
        assert not app._sldea_recorder.reader_alive()


def test_a_video_run_logs_the_size_its_codec_was_checked_at():
    _need_cv()
    with tempfile.TemporaryDirectory() as tmp:
        app = _StubApp()
        rundir = _drive(app, tmp, lambda spec, fps=10: _FakeCam(),
                        _no_oneshot)
        assert app.finished == 1 and not app._sldea_stop, app.lines
        assert any(ln == f"video: {sv.VIDEO_FOURCC} checked at 128 x 96, "
                   f"the stream's own size: lossless" for ln in app.lines), \
            app.lines


def test_a_stream_that_dies_mid_run_is_named_at_the_end_of_setup_txt():
    """The bench check for #392, at the desk: the camera stops delivering
    mid-run and does not come back. The run still ends complete on its
    stills schedule (the later stills are NO FRAME rows), and setup.txt,
    which said "recording started", ends with the frames the video holds
    and that the stream stopped."""
    _need_cv()
    snaps = sorted(_short_profile().snapshots, key=lambda s: s['t'])
    with tempfile.TemporaryDirectory() as tmp:
        first_open = []

        class _Unplugged(_FakeCam):
            # frames for a second after the stream first opened, then
            # none, from this stream or any the reader reopens
            def read(self):
                if time.monotonic() > first_open[0] + 1.0:
                    time.sleep(self.period)
                    return None
                return super().read()

        def stream(spec, fps=10):
            if not first_open:
                first_open.append(time.monotonic())
            return _Unplugged()
        app = _StubApp()
        rundir = _drive(app, tmp, stream, _no_oneshot)
        data = _read_csv(os.path.join(rundir, 'data.csv'))
        assert len(data) == len(snaps), (len(data), app.lines)
        assert data[0]['frame_file'] and not data[-1]['frame_file'], data
        assert f"run complete: {len(snaps)}/{len(snaps)} frames" \
            in app.lines, app.lines
        index = os.path.join(rundir, sv.VIDEO_INDEX_FILENAME)
        assert _wait(lambda: os.path.exists(index), 30), os.listdir(rundir)
        n = len(_read_csv(index))
        with open(os.path.join(rundir, 'setup.txt')) as f:
            lines = f.read().splitlines()
        assert lines[-2] == ("Video outcome: recording started; snapshots "
                             "taken off the stream"), lines[-3:]
        end = lines[-1]
        assert n >= 1 and end.startswith(
            f"Video outcome (end): recorded {n} frames, "), (n, end)
        assert ", then stopped: the camera stream stopped delivering at " \
            in end and end.endswith(
                " s and had not come back by the end of the run"), end


def test_the_end_line_follows_the_hv_shutdown_and_a_failed_one_is_logged():
    """#392's line is written in the finally block after the SG is zeroed
    and switched off and after the recorder is stopped. A failure to write
    it goes to the run log and goes no further: the tab is released and
    the recording is still moved into the run folder."""
    _need_cv()
    events = []
    real_stop = _stop_recorder_spy(events)
    real_outcome = sv.VideoRecorder.end_outcome

    def outcome(self):
        events.append((time.monotonic(), 'rec.end_outcome', (), {}))
        raise RuntimeError('setup.txt went away')
    sv.VideoRecorder.end_outcome = outcome
    try:
        with tempfile.TemporaryDirectory() as tmp:
            app = _StubApp(sg=_FakeSG(events))
            rundir = _drive(app, tmp, lambda spec, fps=10: _FakeCam(),
                            _no_oneshot, dry=False)
            names = [e[1] for e in events]
            last_off = max(i for i, e in enumerate(events)
                           if e[1] == 'sg.set_output' and e[2][1] is False)
            assert last_off < names.index('rec.stop') \
                < names.index('rec.end_outcome'), names
            assert app.finished == 1
            assert any('setup.txt did not get its end-of-run video line '
                       '(setup.txt went away)' in ln for ln in app.lines), \
                app.lines
            with open(os.path.join(rundir, 'setup.txt')) as f:
                assert 'Video outcome (end)' not in f.read()
            assert os.path.exists(os.path.join(rundir, sv.VIDEO_FILENAME)), \
                os.listdir(rundir)
    finally:
        sv.VideoRecorder.stop = real_stop
        sv.VideoRecorder.end_outcome = real_outcome


def test_a_codec_check_that_hangs_stops_the_run_before_hv():
    """#392: a check given up on after CODEC_CHECK_TIMEOUT_S stops a LIVE
    run as a failed check does. The SG output is never switched on and is
    still zeroed and switched off on the way out, the camera is let go,
    and setup.txt, run.log and the status line say why. The run's staging
    folder is left alone while the probe may still be writing in it."""
    _need_cv()
    events = []
    real, real_limit = sv.codec_available, sv.CODEC_CHECK_TIMEOUT_S
    release = threading.Event()

    def hangs(tmpdir=None, frame=None):
        release.wait(60)
        return real(tmpdir=tmpdir, frame=frame)
    sv.codec_available, sv.CODEC_CHECK_TIMEOUT_S = hangs, 0.5
    try:
        with tempfile.TemporaryDirectory() as tmp:
            app = _StubApp(sg=_FakeSG(events))
            rundir = _drive(app, tmp, lambda spec, fps=10: _FakeCam(),
                            _no_oneshot, dry=False)
            assert app.finished == 1 and app._sldea_stop, app.lines
            assert not [e for e in events if e[1] == 'sg.set_output'
                        and e[2][1] is True], [e[1:3] for e in events]
            offs = [e for e in events if e[1] == 'sg.set_output']
            assert offs and offs[-1][2][1] is False, [e[1:3] for e in events]
            assert any('run stopped before any HV' in ln
                       and 'was still running after 0.5 s' in ln
                       for ln in app.lines), app.lines
            assert any(s.startswith('STOPPED before HV')
                       for s in app.statuses), app.statuses
            assert _read_csv(os.path.join(rundir, 'data.csv')) == []
            with open(os.path.join(rundir, 'setup.txt')) as f:
                setup = f.read()
            assert ("Video outcome: NOT recorded: the codec check at the "
                    "camera's frame size failed (the FFV1 check at 128 x 96 "
                    "was still running after 0.5 s") in setup, setup
            assert 'Video outcome (end)' not in setup, setup
            rec = app._sldea_recorder
            assert not rec.reader_alive() and rec.codec_check_running()
            assert os.listdir(os.path.join(tmp, 'staging')), \
                "the folder the probe was still writing in was removed"
            release.set()
            assert _wait(lambda: not rec.codec_check_running(), 30)
    finally:
        release.set()
        sv.codec_available, sv.CODEC_CHECK_TIMEOUT_S = real, real_limit
        sv._abandoned_probe = None


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    ran = skipped = 0
    failed = []
    for n in names:
        try:
            globals()[n]()
        except _Skip as why:
            skipped += 1
            print('skip', n, f'({why})')
            continue
        except Exception:
            ran += 1
            failed.append((n, traceback.format_exc()))
            print('FAIL', n)
            continue
        ran += 1
        print('ok ', n)
    tail = f"{ran} of {len(names)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped)"
    print(tail)
    if not failed:
        return 0
    head = f"{len(failed)} of {len(names)} tests failed"
    print(f"\n{head}")
    for name, tb in failed:
        print(f"===== FAIL {name} =====")
        print(tb.rstrip('\n'))
    print(f"===== end {head} =====")
    return 1


if __name__ == '__main__':
    raise SystemExit(_run())
