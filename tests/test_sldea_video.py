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
  * the REAL run worker: stills come off the stream (no one-shot grab),
    setup.txt says what happened, a dead stream falls back to one-shot
    stills, the SG is zeroed BEFORE the recorder is stopped, the tab is
    released even when the video shutdown throws, and an abort during
    the camera startup never switches the SG output on.

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
        for i in range(n):
            vw.write(_scene(30 + 6 * i, rng))
            w.writerow([i, 2.0 + i, 0.5 * i, '', i + 1])
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
    _sldea_video_postrun = _G._sldea_video_postrun
    _sldea_run_logger = _G._sldea_run_logger

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
        self.lines = []
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
        pass

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


def _drive(app, tmp, stream, oneshot, dry=True):
    with _Patched(tmp, stream, oneshot):
        app._sldea_worker(_short_profile(), tmp, 'RUN', 1, 2, 3, dry,
                          tel_on=False, vid_on=True, vid_fps=5.0)
    return os.path.join(tmp, 'RUN')


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
