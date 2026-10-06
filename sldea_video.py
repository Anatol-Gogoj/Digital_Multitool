#!/usr/bin/env python3
"""SLDEA run video: a lossless recording beside the stills, and edge
detection on every one of its frames afterwards.

TWO HALVES, in one module so the file names and the codec cannot drift
between the side that writes a video and the side that reads it:

  VideoRecorder   used by the SLDEA tab's runner. It OWNS the camera for
                  the whole run, on threads of its own: one reads the
                  stream and keeps the newest frame, one encodes. The HV
                  loop only ever calls latest() / end_recording() /
                  request_restamp() -- a lock, a copy, a flag -- and
                  stop(), which is bounded. It never waits on the camera,
                  which one-shot grabs made it do: each still re-stamped
                  every locked control through v4l2-ctl (10 s timeouts)
                  and then streamed with a 45 s timeout, once retried, all
                  on the thread that runs the watchdog and the ramp.

  detect_video()  after the run, never during it: runs the same detector
                  Edge Review runs (sldea_edge.candidates, same baseline,
                  same saved settings, same frame-to-frame method bonus)
                  on every frame, and writes video_edges.csv plus a figure.

  finalize()      moves a finished recording from local staging into the
                  run folder (copy to .part, then rename; throttled). The
                  tab runs it, and the detection, in a DETACHED process
                  (--finalize), so closing the app cannot cut either off.

The video is 8-bit GRAY, FFV1, LOSSLESS -- measured 2026-09-23 on
1920x1080 frames carrying the sensor's sigma ~2.5 noise: 0.97 MB a frame,
40-50 ms to encode, bit-exact on decode. Gray, because the detector reads
gray and colour would triple the file for nothing it uses; lossless,
because compression smears exactly the fine texture the wrinkle channel
measures. The stills keep coming as PNGs at their scheduled times, from
the same stream, so data.csv and every tool that reads it are unchanged.

Files, beside data.csv in the run folder:
  video.mkv            the recording (staged on local disk during the run)
  video_frames.csv     one row per recorded frame: its time on the run's
                       own clock (telemetry.csv's), the commanded kV then
  video_edges.csv      written by detect_video: one row per analysed frame
  video_edges.json     what that pass ran with (settings, baseline fit,
                       area method, scale anchor): edges_stale reads it
  video_edges.png      area against elapsed time, with the kV staircase,
                       the frames flagged for review and the accepted
                       stills they were checked against
  video_review.csv     the operator's accept/reject decisions from the
                       video review window (sldea_video_review.py)

REVIEW BY EXCEPTION (2026-10-06): Edge Review's Save re-runs the video
pass when its edges are stale (after_save), and review_flags sends to a
human only the frames the detector doubts or that disagree with the run's
accepted stills.

Usage:
    python sldea_video.py RUN [--stride N] [--limit N] [--no-plot]
    python sldea_video.py RUN --after-save       (what Save starts)
    python sldea_video.py --finalize STAGING RUN [--detect]
    python sldea_video.py --selftest

Headless tests: .venv/bin/python tests/test_sldea_video.py
"""
import csv
import datetime
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time

VIDEO_FILENAME = 'video.mkv'
VIDEO_INDEX_FILENAME = 'video_frames.csv'
VIDEO_EDGES_FILENAME = 'video_edges.csv'
VIDEO_PLOT_FILENAME = 'video_edges.png'
# What the video pass was run WITH (2026-10-06): the anchor, settings,
# baseline fit and area method behind video_edges.csv, so a reader can
# tell edges written before the operator calibrated from current ones.
VIDEO_STAMP_FILENAME = 'video_edges.json'
# The operator's per-frame decisions from the video review window. Kept
# apart from video_edges.csv so a re-run of the detector never overwrites
# a human decision, and a decision about an area the detector no longer
# reports is recognisably stale (read_decisions drops it).
VIDEO_REVIEW_FILENAME = 'video_review.csv'
VIDEO_FOURCC = 'FFV1'

# Frames per second RECORDED. The operator's choice (2026-09-23) was
# lossless at 1-2 fps: measurement grade, 2.5-5 GB for a 43-minute run.
VIDEO_FPS_DEFAULT = 1.0
VIDEO_FPS_MIN = 0.1
VIDEO_FPS_MAX = 5.0

# The stream's own rate, kept ABOVE the fastest recording rate so the
# gating never has to skip alternate frames: it bounds how old the newest
# frame can be (0.1 s) and costs one demosaic per frame on the reader.
STREAM_FPS = 10

# FFV1 8-bit gray, bytes per pixel, measured 2026-09-23 (0.97 MB / 1080p
# frame at sensor sigma 2.5). An ESTIMATE for the tab's disk-space line --
# noise sets it, and a darker or noisier scene moves it.
BYTES_PER_PIXEL_EST = 0.47

# A still taken off the stream must be at most this old; older means the
# stream has stalled, and the snapshot is logged as NO FRAME rather than
# filed as a picture of a moment it was not.
STILL_MAX_AGE_S = 2.0

# The reader reopens a stream that has delivered nothing for this many
# consecutive reads (~2 s): a v4l2-ctl that exits mid-run (USB hiccup,
# arc interference) used to lose every remaining still, where a one-shot
# grab re-opened the camera for each one. Backoff between attempts.
REOPEN_AFTER_FAILS = 40
REOPEN_BACKOFF_MAX_S = 5.0

# The post-run copy into the run folder is throttled: gigabytes pushed at
# full speed to the share compete with the NEXT run's own writes there.
COPY_MAX_BPS = 40e6

INDEX_COLUMNS = ['frame', 't_s', 'nominal_kV', 'timestamp', 'stream_seq']
EDGE_COLUMNS = ['frame', 't_s', 'nominal_kV', 'area_px', 'area_mm2',
                'conf', 'method', 'wrinkle', 'needs_review',
                'scale_source']
REVIEW_COLUMNS = ['frame', 't_s', 'decision', 'area_px', 'reasons',
                  'user', 'when']
REVIEW_DECISIONS = ('accept', 'reject')

# REVIEW BY EXCEPTION (2026-10-06). A video is hundreds to thousands of
# frames; nobody reviews them one by one. The stills ARE frames of the
# same stream, and Edge Review's Save writes their accepted areas into
# data.csv, so each still is a checkpoint: a known area at a known time.
# A video frame needs a human only when it disagrees with them, or when
# the detector itself doubts it (review_flags).
#
# REVIEW_BAND_PCT: how far a frame may sit outside the range of the
# accepted stills of its own landing. SLDEA_MEASUREMENT.md 1.1 quotes the
# expansion ratio at +-1-2 %, and same-landing pre/post stills scatter
# 0.3-0.4 % (robust SD, up to 4 kV); 2 % is the top of the quoted budget.
REVIEW_BAND_PCT = 2.0
# REVIEW_JUMP_PCT: outside a landing (on a ramp, or where no still was
# accepted) a frame is compared with the median of its two neighbours on
# each side. Per-frame repeatability is 0.08-0.26 % SD (SLDEA_MEASUREMENT
# 2.1), so a 2 % step between neighbours a second apart is many times the
# noise: a real event or a tracking error, either worth a look.
REVIEW_JUMP_PCT = 2.0
# A still and the recorded frame it is matched to may differ by up to half
# the recorded frame spacing; with no spacing to measure, this.
REVIEW_MATCH_S = 0.5


# ---------------------------------------------------------------------------
# small pure helpers
# ---------------------------------------------------------------------------

def clamp_fps(value):
    """The recording rate from whatever the entry box holds: a number is
    clamped to [VIDEO_FPS_MIN, VIDEO_FPS_MAX], anything else is the
    default -- a half-typed box never fails a run."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return VIDEO_FPS_DEFAULT
    if f != f:                                   # NaN
        return VIDEO_FPS_DEFAULT
    return min(VIDEO_FPS_MAX, max(VIDEO_FPS_MIN, f))


def estimate_bytes(duration_s, fps, width=1920, height=1080):
    """Rough size of the recording (see BYTES_PER_PIXEL_EST)."""
    return max(0.0, float(duration_s)) * clamp_fps(fps) * width * height \
        * BYTES_PER_PIXEL_EST


def fmt_bytes(n):
    n = float(n)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1000 or unit == 'TB':
            return f"{n:.0f} {unit}" if unit in ('B', 'KB') \
                else f"{n:.1f} {unit}"
        n /= 1000.0
    return f"{n:.1f} TB"


def staging_root():
    """Where a recording is written DURING a run: local disk, per user.

    Never the run folder itself -- that is normally the network share, and
    the share has measured multi-second write stalls (SLDEA_HANDOFF
    2026-08-05); a share that drops mid-run would take the whole
    recording with it. `SCPI_SLDEA_VIDEO_STAGING` overrides."""
    env = os.environ.get('SCPI_SLDEA_VIDEO_STAGING')
    if env:
        return env
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'scpi_control', 'sldea_video')
    return os.path.join(os.path.expanduser('~'), '.cache', 'scpi_control',
                        'sldea_video')


# FFmpeg READS PAST THE END OF A GRAY FRAME (measured 2026-10-06 on
# Windows OpenCV 4.13, whose bundled FFmpeg is 4.4). FFmpeg 4.x treats
# 8-bit gray as "pseudo-paletted". OpenCV hands it the frame in place,
# and FFmpeg's copy of that frame then reads a 1024 B palette that starts
# at the byte after the last pixel. When unmapped memory begins inside
# those 1024 B, write() throws "Unknown C++ exception". That is the
# 1632 x 918 failure, where the allocator ends the frame at the same place
# in every process, and the test suite's flake (64 x 48 and 320 x 240
# frames, one process in five). OpenCV's own guard looks only 32 B past
# the end, and the copy it makes when that guard trips keeps only 32 B
# spare. ffmpeg_safe lays every frame out so that the read lands inside a
# buffer this module owns. FFmpeg 5.0 dropped the pseudo-palette. Which
# FFmpeg the bench's Linux wheel bundles has not been checked (#369).
FFMPEG_OVERREAD = 1024
_PAGE = 4096


def ffmpeg_safe(gray, buf=None):
    """-> (`gray` copied into `buf` where FFmpeg cannot read past it, the
    buffer). Pass the buffer back in for the next frame.

    The copy's row stride is a multiple of 32, and its last row ends in
    the middle of a 4 KB page, so OpenCV hands it to FFmpeg in place
    without its own copy, because its 32 B guard is satisfied. The buffer
    runs on for more than a page past that end, so FFmpeg's
    FFMPEG_OVERREAD bytes stay inside it. The pixels are unchanged, and
    the decode is still bit-exact. Anything but a 2-D uint8 frame is
    returned as it came: copyto would silently narrow a 16-bit one."""
    import numpy as np
    if gray.ndim != 2 or gray.dtype != np.uint8:
        return gray, buf
    h, w = gray.shape
    step = (w + 31) & ~31
    need = step * h + 3 * _PAGE
    if buf is None or buf.size < need:
        buf = np.empty(need, np.uint8)
    off = (_PAGE // 2 - (buf.ctypes.data + step * h)) % _PAGE
    view = buf[off:off + step * h].reshape(h, step)[:, :w]
    np.copyto(view, gray)
    return view, buf


def _gray(frame):
    """The recorded picture of a stream frame: 8-bit gray, as the reader
    queues it for the encoder."""
    if frame.ndim == 2:
        return frame
    import cv2
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def codec_available(tmpdir=None, frame=None):
    """-> (True, '') when this OpenCV can write AND read back an FFV1 gray
    file bit-exactly, else (False, why). Never raises. Checked before a
    run starts -- before any HV -- because a build without the encoder
    would otherwise fail at the first frame, halfway into an hour.

    Without `frame` the probe is 64 x 48: it shows only that there is an
    encoder. With `frame` (gray or BGR) it runs at THAT frame's size and
    writes the frame itself, then a noise frame of the same size. The
    recorder passes its stream's own frame (VideoRecorder.check_codec)
    because the size matters. Measured 2026-10-06 on Windows OpenCV 4.13:
    OpenCV silently crops an odd width or height to even, so 1081 x 1080
    reads back as 1080 x 1080, and at some even sizes (1632 x 918) the
    first write threw "Unknown C++ exception" until frames went through
    ffmpeg_safe. The probe writes through it too, as the recorder does."""
    import tempfile
    try:
        import cv2
        import numpy as np
    except ImportError as e:
        return False, f"OpenCV/numpy not importable ({e})"
    own = tmpdir is None
    d = path = None
    size = "64 x 48"
    try:
        if frame is None:
            frames = [np.full((48, 64), 40 * i, np.uint8)
                      for i in range(1, 4)]
            frames[1][10:20, 10:30] = 200
        else:
            g0 = _gray(frame)
            frames = [g0, np.random.default_rng(0).integers(
                0, 256, g0.shape, dtype=np.uint8)]
        h, wd = frames[0].shape
        size = f"{wd} x {h}"
        d = tempfile.mkdtemp(prefix='sldea_codec_') if own else tmpdir
        path = os.path.join(d, 'probe.mkv')
        w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*VIDEO_FOURCC),
                            1.0, (wd, h), isColor=False)
        if not w.isOpened():
            return False, (f"this OpenCV build has no {VIDEO_FOURCC} "
                           f"encoder for {size}")
        buf = None
        try:
            for f in frames:
                safe, buf = ffmpeg_safe(f, buf)
                w.write(safe)
        finally:
            w.release()
        cap = cv2.VideoCapture(path)
        try:
            for f in frames:
                ok, g = cap.read()
                if not ok:
                    return False, (f"{VIDEO_FOURCC} file at {size} did not "
                                   f"read back")
                g = g if g.ndim == 2 else g[:, :, 0]
                if g.shape != f.shape:
                    return False, (f"{VIDEO_FOURCC} at {size} read back as "
                                   f"{g.shape[1]} x {g.shape[0]}: NOT "
                                   f"lossless")
                if not np.array_equal(g, f):
                    return False, (f"{VIDEO_FOURCC} round trip at {size} "
                                   f"was NOT lossless")
        finally:
            cap.release()
        return True, ''
    except Exception as e:
        return False, f"{VIDEO_FOURCC} probe at {size} failed: {e}"
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
        if own and d:
            try:
                os.rmdir(d)
            except OSError:
                pass


def codec_stop_words(why, dry):
    """The words for a video run that stops itself before any HV because
    the codec failed at the stream's own size (VideoRecorder.check_codec).

    -> dict(stopped, status, title, box), as
    sldea_profile.baseline_stop_words: the run.log line, the red status
    line and the operator's box. Never raises."""
    drive = ("This was a DRY run: no voltage was driven." if dry else
             "The signal generator output was never switched on by this "
             "run.")
    return {
        'stopped': (f"run stopped before any HV: the video cannot be "
                    f"recorded at the camera's frame size ({why}). {drive}"),
        'status': ("STOPPED before HV: the video cannot be recorded at "
                   "this frame size (see Run log)"),
        'title': "Run stopped: video cannot be recorded",
        'box': ("The run stopped itself before any high voltage.\n\n"
                f"The lossless video could not be written at the size the "
                f"camera delivers: {why}.\n\n{drive}\n\nUntick Record to "
                f"run with snapshots only, then press Run again.\n\nThe "
                f"Run log has the details.")}


def open_stream(spec, fps=STREAM_FPS):
    """A continuously streaming camera for a resolve_camera() spec: the
    v4l2-ctl Bayer stream for the bench's DFK (OpenCV cannot open SRGGB8),
    an ordinary cv2 capture otherwise. Called ON the recorder's reader
    thread, so an open that hangs cannot hang the caller."""
    import webcam
    if spec.get('kind') == 'bayer':
        return webcam.V4L2BayerCamera(spec['device'], spec['fourcc'],
                                      spec['w'], spec['h'], fps=fps).open()
    return webcam.Camera(spec.get('index', 0)).open()


# ---------------------------------------------------------------------------
# the recorder
# ---------------------------------------------------------------------------

class VideoRecorder:
    """Owns one camera stream for a run; records it and serves stills.

    open_camera()  -> an object with read() (a BGR frame or None, may
                      block up to a frame period) and close(). Called on
                      the reader thread, and again to REOPEN a stream that
                      stopped delivering (REOPEN_AFTER_FAILS).
    out_dir        where video.mkv and video_frames.csv are written.
    fps            frames per second RECORDED (clamp_fps).
    kv_at(t)       the commanded kV at run time t, for the frame index.
    refresh()      optional, every `refresh_s` on the reader thread: the
                   tab re-stamps the locked controls there, gain excluded,
                   as the live preview does.
    restamp()      optional, on request_restamp(): the FULL lock, gain
                   included -- what a one-shot grab stamps before every
                   still, so a still off the stream is exposed like one.

    Frames are stamped on `clock` (time.monotonic by default) against
    `t0`, the run's own origin, so a frame's t_s joins telemetry.csv and
    t_planned_s directly. Nothing is recorded before set_t0() or after
    end_recording(). The first frame read after any refresh/restamp stall
    is DISCARDED: a stream drained after a stall hands back a frame
    captured during it, and it would be stamped as now.

    The HV loop's calls are latest(), end_recording(), request_restamp()
    -- a lock and a copy, a flag, an event -- and stop(), which gives up
    after its timeout. If the encoder falls behind, frames are DROPPED and
    counted; the reader never blocks on it.
    """

    def __init__(self, open_camera, out_dir, fps=VIDEO_FPS_DEFAULT,
                 kv_at=None, log=print, refresh=None, refresh_s=5.0,
                 restamp=None, queue_max=16, clock=time.monotonic):
        self._open_camera = open_camera
        self.out_dir = out_dir
        self.fps = clamp_fps(fps)
        self._kv_at = kv_at
        self._log = log
        self._refresh = refresh
        self._refresh_s = float(refresh_s)
        self._restamp = restamp
        self._clock = clock
        self._q = queue.Queue(maxsize=max(1, int(queue_max)))
        self._lock = threading.Lock()          # _latest and _cam
        self._stats = threading.Lock()         # counters shared by threads
        self._stop = threading.Event()
        self._recording = True                 # cleared by end_recording()
        self._restamp_req = threading.Event()
        self._latest = None                    # (bgr frame, clock time, seq)
        self._cam = None
        self.t0 = None
        self.video_path = os.path.join(out_dir, VIDEO_FILENAME)
        self.index_path = os.path.join(out_dir, VIDEO_INDEX_FILENAME)
        self.seen = self.written = self.dropped = self.read_failures = 0
        self.reopens = 0
        self.first_t = self.last_t = None
        self.first_seen_clock = self.last_seen_clock = None
        self.restamp_done = None               # clock time of the last one
        self.error = None
        self.size = None                       # (w, h) of the recording
        self.probed_size = None                # (w, h) check_codec passed
        self._reader_t = threading.Thread(target=self._reader, daemon=True,
                                          name='sldea-video-reader')
        self._writer_t = threading.Thread(target=self._writer, daemon=True,
                                          name='sldea-video-writer')
        self._started = False

    # -- the HV loop's side --------------------------------------------------

    def start(self):
        os.makedirs(self.out_dir, exist_ok=True)
        self._writer_t.start()
        self._started = True
        try:
            self._reader_t.start()
        except Exception:
            self._stop.set()                   # let the writer go too
            raise
        return self

    def set_t0(self, t0):
        """Start the run clock: frames from now on are recorded."""
        self.t0 = t0

    def end_recording(self):
        """Stop RECORDING (stills can still be served). Called when the
        staircase ends, BEFORE the SG is zeroed: frames after that would
        be filed under the planned kV while the SG is already at 0. A
        flag -- it cannot block."""
        self._recording = False

    def request_restamp(self):
        """Ask the reader to stamp the full control lock (gain included)
        before the next still; the HV loop then takes a frame captured
        after it (latest(not_before=...)). An event -- it cannot block."""
        self._restamp_req.set()

    def set_log(self, log):
        """Redirect this recorder's log lines (the tab points a finished
        run's recorder at THAT run's log, not whichever run is next)."""
        self._log = log

    def wait_first_frame(self, timeout):
        """True once the stream has delivered a frame, False at `timeout`
        or when the camera failed to open. Meant for the moment before the
        staircase starts, at 0 V."""
        end = self._clock() + timeout
        while self._clock() < end:
            with self._lock:
                if self._latest is not None:
                    return True
            if self.error or (self._started
                              and not self._reader_t.is_alive()):
                return False
            time.sleep(0.05)
        with self._lock:
            return self._latest is not None

    def check_codec(self):
        """-> (True, '') when the codec writes AND reads back, bit-exactly,
        a frame of the size this stream ACTUALLY delivers, else (False,
        why). Never raises. It probes with the newest frame the reader
        already holds (codec_available(frame=...)), so it adds no camera
        I/O. Meant for after wait_first_frame(), at 0 V: a size the codec
        cannot record must stop the run before any HV, not turn up at the
        first recorded frame (2026-10-06)."""
        with self._lock:
            got = self._latest
        if got is None:
            return False, "the stream gave no frame to check the codec with"
        try:
            gray = _gray(got[0])
        except Exception as e:
            return False, f"the stream's frame could not be made gray ({e})"
        ok, why = codec_available(frame=gray)
        if ok:
            self.probed_size = (gray.shape[1], gray.shape[0])
        return ok, why

    def latest(self, max_age_s=STILL_MAX_AGE_S, not_before=None):
        """-> (a COPY of the newest BGR frame, its run time t_s), or
        (None, None) when there is none younger than `max_age_s` -- or,
        with `not_before` (run time), none captured at or after it: a
        still must never be a picture from BEFORE its scheduled moment."""
        with self._lock:
            got = self._latest
        if got is None:
            return None, None
        frame, t, _seq = got
        if self._clock() - t > max_age_s:
            return None, None
        t_run = None if self.t0 is None else t - self.t0
        if not_before is not None and (t_run is None or t_run < not_before):
            return None, None
        return frame.copy(), t_run

    def latest_rgb(self, max_age_s=STILL_MAX_AGE_S, not_before=None):
        """(the newest frame as RGB -- what webcam.oneshot_rgb returns --
        and its run time), or (None, None); see latest()."""
        frame, t = self.latest(max_age_s, not_before)
        if frame is None:
            return None, None
        import cv2
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), t

    def restamp_done_t(self):
        """Run time of the last completed full restamp, or None."""
        if self.restamp_done is None or self.t0 is None:
            return None
        return self.restamp_done - self.t0

    @property
    def can_restamp(self):
        """False when there is nothing to restamp (no device controls):
        the tab then asks only that a still postdate its schedule."""
        return self._restamp is not None

    def reader_alive(self):
        return self._reader_t.is_alive()

    def stop(self, timeout=10.0):
        """Stop reading, drain the encoder, close both files. Gives up
        after `timeout` (logging it) and never raises. The caller runs this
        AFTER the SG is zeroed: nothing about the HV shutdown waits on it."""
        end = time.monotonic() + max(0.1, timeout)
        self._recording = False
        self._stop.set()
        try:
            if self._reader_t.is_alive():
                self._reader_t.join(max(0.0, min(2.0,
                                                 end - time.monotonic())))
            if self._reader_t.is_alive():
                # blocked inside the camera's read(): closing the stream
                # from here is what unblocks it (a v4l2-ctl pipe hits EOF)
                self._close_camera()
                self._reader_t.join(max(0.0, end - time.monotonic()))
            if self._writer_t.is_alive():
                try:                  # a sentinel only if there is room;
                    self._q.put_nowait(None)     # it exits by itself too
                except queue.Full:
                    pass
                self._writer_t.join(max(0.0, end - time.monotonic()))
            if self._reader_t.is_alive() or self._writer_t.is_alive():
                self._log("⚠ video: the recorder did not stop within "
                          f"{timeout:g} s -- the files are finished off "
                          f"in the background")
            self._close_camera()
        except Exception as e:
            try:
                self._log(f"⚠ video: stop failed: {e}")
            except Exception:
                pass

    def wait_finished(self, timeout):
        """True once the ENCODER has exited -- the files are closed and
        safe to move. The reader is not waited for: it touches no file.
        For the post-run thread; the HV loop never calls this."""
        if self._writer_t.is_alive():
            self._writer_t.join(max(0.0, timeout))
        return not self._writer_t.is_alive()

    def achieved_fps(self):
        if self.written < 2 or self.first_t is None or self.last_t is None \
                or self.last_t <= self.first_t:
            return None
        return (self.written - 1) / (self.last_t - self.first_t)

    def stream_fps(self):
        """The stream's own delivered rate -- the bench check that the
        requested STREAM_FPS actually took (BENCH_TEST §Q)."""
        if self.seen < 2 or self.first_seen_clock is None \
                or self.last_seen_clock <= self.first_seen_clock:
            return None
        return (self.seen - 1) / (self.last_seen_clock
                                  - self.first_seen_clock)

    def summary(self):
        fps, sfps = self.achieved_fps(), self.stream_fps()
        size = ''
        try:
            size = f", {fmt_bytes(os.path.getsize(self.video_path))}"
        except OSError:
            pass
        return (f"video: {self.written} frames recorded"
                + (f" at {fps:.2f} fps (target {self.fps:g})"
                   if fps else f" (target {self.fps:g} fps)")
                + size
                + (f"; stream {sfps:.1f} fps" if sfps else "")
                + (f"; stream REOPENED {self.reopens}x" if self.reopens
                   else "")
                + (f", {self.dropped} DROPPED -- the encoder could not keep "
                   f"up" if self.dropped else "")
                + (f"; ERROR: {self.error}" if self.error else ""))

    # -- the threads -----------------------------------------------------------

    def _close_camera(self):
        with self._lock:
            cam, self._cam = self._cam, None
        if cam is not None:
            try:
                cam.close()
            except Exception:
                pass

    def _open(self):
        """Open the stream and install it -- unless stop() came first, in
        which case the new stream is closed at once rather than orphaned
        (a dropped v4l2-ctl would hold the device until the app exits)."""
        cam = self._open_camera()
        with self._lock:
            if not self._stop.is_set():
                self._cam = cam
                return cam
        try:
            cam.close()
        except Exception:
            pass
        return None

    def _count(self, attr):
        with self._stats:
            setattr(self, attr, getattr(self, attr) + 1)

    def _reader(self):
        try:
            cam = self._open()
        except Exception as e:
            self.error = f"camera stream did not open ({e})"
            self._log(f"⚠ video: {self.error}")
            return
        if cam is None:
            return
        next_t = None
        last_refresh = self._clock()
        fails = 0
        skip_next = False
        while not self._stop.is_set():
            if self._restamp_req.is_set() and self._restamp is not None:
                self._restamp_req.clear()
                try:
                    self._restamp()
                except Exception:
                    pass
                self.restamp_done = self._clock()
                skip_next = True
            elif self._refresh is not None \
                    and self._clock() - last_refresh >= self._refresh_s:
                try:
                    self._refresh()
                except Exception:
                    pass
                last_refresh = self._clock()
                skip_next = True
            with self._lock:
                cam = self._cam
            if cam is None:
                break
            try:
                frame = cam.read()
            except Exception:
                frame = None
            now = self._clock()
            if frame is None:
                self.read_failures += 1
                fails += 1
                if fails >= REOPEN_AFTER_FAILS:
                    fails = 0
                    if not self._reopen():
                        break
                    skip_next = True
                else:
                    time.sleep(0.05)
                continue
            fails = 0
            if skip_next:            # possibly buffered during the stall
                skip_next = False
                continue
            self.seen += 1
            if self.first_seen_clock is None:
                self.first_seen_clock = now
            self.last_seen_clock = now
            with self._lock:
                self._latest = (frame, now, self.seen)
            if self.t0 is None or not self._recording:
                continue
            t = now - self.t0
            if t < 0:
                continue
            if next_t is None:
                next_t = t
            if t + 1e-9 < next_t:
                continue
            next_t += 1.0 / self.fps
            if next_t < t:                   # fell behind: never burst
                next_t = t + 1.0 / self.fps
            gray = _gray(frame)
            item = (gray, t, datetime.datetime.now().isoformat(
                timespec='milliseconds'), self.seen)
            try:
                self._q.put_nowait(item)
            except queue.Full:
                self._count('dropped')
        self._close_camera()

    def _reopen(self):
        """Close and reopen a stream that stopped delivering, with
        backoff, until it comes back or stop() is called. -> True when a
        stream is installed again."""
        self._close_camera()
        delay = 0.5
        attempt = 0
        while not self._stop.is_set():
            attempt += 1
            self._log(f"⚠ video: the camera stream stopped delivering -- "
                      f"reopening (attempt {attempt}); snapshots log NO "
                      f"FRAME until it is back")
            try:
                if self._open() is not None:
                    self.reopens += 1
                    self._log("video: camera stream reopened")
                    return True
            except Exception as e:
                self._log(f"⚠ video: reopen failed ({e})")
            if self._stop.wait(delay):
                break
            delay = min(REOPEN_BACKOFF_MAX_S, delay * 2)
        return False

    def _writer(self):
        import cv2
        vw, fh, w = None, None, None
        buf = None                           # ffmpeg_safe's, reused per frame
        try:
            while True:
                try:
                    item = self._q.get(timeout=0.5)
                except queue.Empty:
                    # exits by itself once the reader is gone and nothing
                    # is left: a sentinel stop() could not queue (a full
                    # queue behind a stalled disk) must not strand it
                    if self._stop.is_set() and not self._reader_t.is_alive():
                        break
                    continue
                if item is None:
                    break
                gray, t, stamp, seq = item
                if self.error and vw is None:
                    continue                 # failed to open: drain only
                if vw is None:
                    h, wd = gray.shape[:2]
                    self.size = (wd, h)
                    if self.probed_size not in (None, self.size):
                        # a stream reopened at another size between the
                        # check and the first recorded frame
                        self._log(f"⚠ video: recording {wd} x {h}, but the "
                                  f"codec was checked at "
                                  f"{self.probed_size[0]} x "
                                  f"{self.probed_size[1]}: this size was "
                                  f"never checked")
                    vw = cv2.VideoWriter(
                        self.video_path,
                        cv2.VideoWriter_fourcc(*VIDEO_FOURCC), self.fps,
                        (wd, h), isColor=False)
                    if not vw.isOpened():
                        self.error = (f"could not open the {VIDEO_FOURCC} "
                                      f"writer for {self.video_path}")
                        self._log(f"⚠ video: {self.error}")
                        vw = None
                        continue
                    fh = open(self.index_path, 'w', newline='',
                              encoding='utf-8')
                    w = csv.writer(fh)
                    w.writerow(INDEX_COLUMNS)
                if gray.shape[:2] != (self.size[1], self.size[0]):
                    self._count('dropped')   # a size change cannot encode
                    continue
                safe, buf = ffmpeg_safe(gray, buf)
                vw.write(safe)
                kv = ''
                if self._kv_at is not None:
                    try:
                        kv = round(float(self._kv_at(t)), 4)
                    except Exception:
                        kv = ''
                w.writerow([self.written, round(t, 3), kv, stamp, seq])
                if self.first_t is None:
                    self.first_t = t
                self.last_t = t
                self.written += 1
                if self.written % 10 == 0:
                    fh.flush()
        except Exception as e:
            self.error = f"encoder failed: {e}"
            self._log(f"⚠ video: {self.error}")
        finally:
            if vw is not None:
                try:
                    vw.release()
                except Exception:
                    pass
            if fh is not None:
                try:
                    fh.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# moving a finished recording into the run folder
# ---------------------------------------------------------------------------

def _copy_throttled(src, dst, max_bps=COPY_MAX_BPS, chunk=8 << 20):
    """Copy `src` to `dst` at no more than `max_bps` bytes a second."""
    t0 = time.monotonic()
    done = 0
    with open(src, 'rb') as fi, open(dst, 'wb') as fo:
        while True:
            buf = fi.read(chunk)
            if not buf:
                break
            fo.write(buf)
            done += len(buf)
            if max_bps:
                ahead = done / max_bps - (time.monotonic() - t0)
                if ahead > 0:
                    time.sleep(ahead)
        fo.flush()
        os.fsync(fo.fileno())


def finalize(staging_dir, rundir, log=print, max_bps=COPY_MAX_BPS):
    """Move a finished recording from local staging into the run folder.
    -> {filename: path in the run folder, or None when it did not move}.

    A rename when both are on one volume. Otherwise a throttled copy to
    `<name>.part`, renamed into place only when complete, the staged
    original removed only after that -- so an interrupted move leaves an
    obvious .part beside an intact original, never a truncated video.mkv.
    Every file is reported; a failure says where the original still is."""
    out = {}
    for name in (VIDEO_FILENAME, VIDEO_INDEX_FILENAME):
        src = os.path.join(staging_dir, name)
        if not os.path.exists(src):
            out[name] = None
            continue
        dst = os.path.join(rundir, name)
        try:
            try:
                os.replace(src, dst)          # same volume: instant
            except OSError:
                part = dst + '.part'
                _copy_throttled(src, part, max_bps)
                os.replace(part, dst)
                os.remove(src)
            out[name] = dst
            log(f"video: {name} is in the run folder")
        except Exception as e:
            out[name] = None
            log(f"⚠ video: could not move {name} into the run folder ({e})"
                f" -- the original is still at {src}; copy it in by hand")
    try:
        os.rmdir(staging_dir)
    except OSError:
        pass
    return out


# ---------------------------------------------------------------------------
# reading a recording back, and detecting edges on every frame
# ---------------------------------------------------------------------------

def read_index(folder):
    """video_frames.csv as a list of dicts, frame order, typed."""
    path = os.path.join(folder, VIDEO_INDEX_FILENAME)
    out = []
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            def num(k):
                try:
                    return float(r.get(k) or '')
                except ValueError:
                    return None
            out.append({'frame': int(r['frame']), 't_s': num('t_s'),
                        'nominal_kV': num('nominal_kV'),
                        'timestamp': r.get('timestamp', '')})
    return out


def iter_frames(video_path):
    """-> (frame number, 8-bit gray frame) for every frame of a
    recording, in order."""
    import cv2
    cap = cv2.VideoCapture(video_path)
    try:
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                return
            yield i, (frame if frame.ndim == 2 else frame[:, :, 0])
            i += 1
    finally:
        cap.release()


def video_gray(path):
    """A still as float32 grey, converted the way the RECORDER converts
    video frames (cv2.cvtColor BGR2GRAY) -- not the way se.load_gray
    decodes a PNG. Measured 2026-09-23: imread's grey decode and cvtColor
    round differently, by up to 1 grey level on half of all pixels, and a
    reference converted one way against frames converted the other would
    build that into every difference image. None if unreadable."""
    import cv2
    import numpy as np
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        return None
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)


def detect_video(rundir, stride=1, limit=None, log=print, plot=True,
                 video_dir=None):
    """Run Edge Review's detector on every `stride`-th recorded frame.

    The SAME detection as the stills get: sldea_edge.candidates against the
    run's own 0 kV baseline still (converted as the video frames were --
    video_gray), with the run's saved settings, frames in time order
    carrying the previous frame's winning method (the ramp-order bonus Edge
    Review applies). Scale: the anchor Edge Review saved when it has one,
    else the automatic fit to the baseline disc -- named on every row.

    `video_dir` reads video.mkv and its index from there (the local
    staging copy, before it is moved) instead of the run folder; the
    results are always written into the run folder.

    No human review queue here: a video is thousands of frames. Every row
    carries the detector's own conf and needs_review verdict, and the
    summary counts the frames review_flags sends to a human (the detector's
    doubt, or disagreement with the run's accepted stills); the video
    review window (sldea_video_review.py) walks exactly those.

    WRITTEN WHOLE OR NOT AT ALL (2026-10-06): the rows go to a .part file
    that replaces video_edges.csv only when the pass is complete, and the
    inputs it ran with go to video_edges.json beside it (edges_stamp). A
    pass re-run after Save can then never leave a reader, or the window,
    with half a new file over half an old one, and two passes that overlap
    leave whichever finished last, whose stamp says what it measured with.
    -> summary dict."""
    import sldea_edge as se
    stride = max(1, int(stride))
    src_dir = video_dir or rundir
    run = se.load_run(rundir)
    settings = se.load_settings(rundir)
    base_row = next((r for r in run['rows'] if r.get('tag') == 'baseline'
                     and (r.get('frame_file') or '').strip()), None)
    if base_row is None:
        raise RuntimeError("no baseline still in this run -- the detector "
                           "measures every frame against it")
    base = video_gray(se.frame_path(run, base_row))
    if base is None:
        raise RuntimeError("the baseline still does not read")
    anchor = se.load_scale_anchor(rundir)
    base_ref = se.baseline_disc(base, settings)
    ref = anchor or base_ref
    scale = se.mm_per_px({}, run['rows'], settings, baseline_ref=ref)
    src = se.scale_source({}, run['rows'], baseline_ref=ref)
    index = read_index(src_dir)
    out_path = os.path.join(rundir, VIDEO_EDGES_FILENAME)
    part = f"{out_path}.{os.getpid()}.part"
    t_start = time.monotonic()
    rows, prev, done, decoded = [], None, 0, 0
    # whole or not at all: a pass that dies leaves no .part behind and
    # the previous video_edges.csv untouched
    try:
        with open(part, 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=EDGE_COLUMNS)
            w.writeheader()
            for i, gray in iter_frames(os.path.join(src_dir, VIDEO_FILENAME)):
                decoded = i + 1
                if i % stride:
                    continue
                if limit is not None and done >= limit:
                    break
                meta = index[i] if i < len(index) else {}
                row = {'frame': i, 't_s': meta.get('t_s', ''),
                       'nominal_kV': meta.get('nominal_kV', ''),
                       'area_px': '', 'area_mm2': '', 'conf': '', 'method': '',
                       'wrinkle': '', 'needs_review': True,
                       # on every row, so the CSV carries its own provenance
                       # and no reader has to skip a comment line to get it
                       'scale_source': src}
                if gray.shape != base.shape:
                    row['method'] = 'size-mismatch'
                else:
                    try:
                        # float32, exactly as se.load_gray hands the stills
                        # to the detector (it raises on mixed types)
                        cands = se.candidates(base, gray.astype('float32'),
                                              settings, prev_method=prev)
                    except Exception as e:
                        cands = []
                        row['method'] = f'failed: {e}'
                    if cands:
                        best = cands[0]
                        prev = best['method']
                        a = float(best['area_px'])
                        row.update(area_px=round(a, 1),
                                   area_mm2=(round(a * scale * scale, 4)
                                             if scale else ''),
                                   conf=round(float(best['conf']), 3),
                                   method=best['method'],
                                   wrinkle=round(float(best.get('wrinkle', 1.0)),
                                                 3),
                                   needs_review=bool(
                                       se.needs_review(cands, settings)))
                w.writerow(row)
                fh.flush()
                rows.append(row)
                done += 1
                if done % 50 == 0:
                    el = time.monotonic() - t_start
                    log(f"video edges: {done} frames, {el / done:.2f} s each")
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    os.replace(part, out_path)
    stamp = edges_stamp(settings, anchor, base_ref, scale, src, stride,
                        limit)
    _write_json_atomic(os.path.join(rundir, VIDEO_STAMP_FILENAME), stamp)
    if limit is None and decoded != len(index):
        log(f"⚠ video edges: the video decoded {decoded} frames but its "
            f"index lists {len(index)} -- rows past the shorter one have "
            f"no time or kV")
    edges = read_edges(rundir)
    try:
        checkpoints = still_checkpoints(rundir, run=run)
    except Exception as e:             # a malformed data.csv row or run.log
        log(f"video edges: the stills could not be read as checkpoints "
            f"({e}); flagging on the detector alone")
        checkpoints = []
    offset = still_offset(edges, checkpoints)
    flags = review_flags(edges, checkpoints, offset=offset)
    summary = {'frames': done, 'scale_mm_per_px': scale, 'scale_source': src,
               'needs_review': sum(1 for r in rows if r['needs_review']),
               'flagged': sum(1 for f in flags if f['reasons']),
               'checkpoints': len(checkpoints), 'still_offset': offset,
               'csv': out_path, 'seconds': time.monotonic() - t_start}
    if plot and rows:
        try:
            summary['png'] = plot_edges(rundir, edges, scale, src,
                                        flags=flags, checkpoints=checkpoints)
        except Exception as e:
            log(f"video edges: figure failed ({e}); the CSV is complete")
    return summary


# Paul Tol bright (CLAUDE.md), and every series also has its own MARKER
# SHAPE, so nothing on the figure or in the review window depends on
# colour alone: circles = frames nobody needs to look at, open triangles =
# frames sent to a human, filled diamonds = accepted by a human, crosses =
# rejected by a human, squares = the accepted stills (checkpoints).
TOL_BLUE, TOL_RED, TOL_GREEN = '#4477AA', '#EE6677', '#228833'
TOL_YELLOW, TOL_PURPLE, TOL_GREY = '#CCBB44', '#AA3377', '#BBBBBB'


def plot_series(edges, flags=None, checkpoints=None, decisions=None):
    """The points of the area-against-time figure, split by what a reader
    must do with them. Shared by plot_edges and the review window, so the
    PNG and the window can never disagree about which frame is which.

    -> {'clear' | 'flagged' | 'accepted' | 'rejected': [(t_s, area_px,
    frame)], 'stills': [(t_s, area_px, frame_file)], 'kv': [(t_s, kV)]}.
    A human decision outranks a flag; frames with no area or no time are
    left out (there is nothing to draw)."""
    flagged = {f['frame'] for f in (flags or []) if f['reasons']}
    decisions = decisions or {}
    out = {'clear': [], 'flagged': [], 'accepted': [], 'rejected': [],
           'stills': [], 'kv': []}
    for e in edges:
        if e['t_s'] is None:
            continue
        if e['nominal_kV'] is not None:
            out['kv'].append((e['t_s'], e['nominal_kV']))
        if e['area_px'] is None:
            continue
        d = decisions.get(e['frame'], {}).get('decision')
        key = ('accepted' if d == 'accept' else
               'rejected' if d == 'reject' else
               'flagged' if e['frame'] in flagged else 'clear')
        out[key].append((e['t_s'], e['area_px'], e['frame']))
    for c in checkpoints or []:
        out['stills'].append((c['t_s'], c['area_px'], c['frame_file']))
    return out


SERIES_STYLE = (
    # key, label, marker, face, edge, size
    ('clear', 'confident, agrees with the stills', 'o', TOL_BLUE, TOL_BLUE,
     3),
    ('flagged', 'flagged for review', '^', 'white', TOL_RED, 5),
    ('accepted', 'accepted in review', 'D', TOL_GREEN, TOL_GREEN, 4),
    ('rejected', 'rejected in review', 'x', TOL_PURPLE, TOL_PURPLE, 5),
    ('stills', 'accepted still (checkpoint)', 's', TOL_YELLOW, 'black', 6),
)


def draw_series(ax, series, scale=None):
    """Draw plot_series' output on a matplotlib axis, in mm^2 when `scale`
    (mm per px) is given, else px^2. -> the twin kV axis or None."""
    k = (scale * scale) if scale else 1.0
    for key, label, marker, face, edge, size in SERIES_STYLE:
        pts = series[key]
        if not pts:
            continue
        ax.plot([p[0] / 60.0 for p in pts], [p[1] * k for p in pts],
                linestyle='', marker=marker, markersize=size,
                markerfacecolor=face, markeredgecolor=edge,
                markeredgewidth=0.9, color=edge, label=label,
                zorder=4 if key == 'stills' else 3)
    ax.set_xlabel('Elapsed time (min)')
    ax.set_ylabel('Active area (mm²)' if scale else 'Active area (px²)')
    ax.grid(alpha=0.3)
    tw = None
    if series['kv']:
        tw = ax.twinx()
        tw.step([p[0] / 60.0 for p in series['kv']],
                [p[1] for p in series['kv']], where='post', color=TOL_GREY,
                linewidth=1.0, zorder=0)
        tw.set_ylabel('Nominal kV', color='#777777')
    return tw


def plot_edges(rundir, edges, scale, src, flags=None, checkpoints=None,
               decisions=None):
    """Area against elapsed time, the kV staircase on a second axis: every
    recorded frame (read_edges rows), sorted into what a reader must do
    with it (plot_series), the accepted stills over them as checkpoints.
    -> the PNG's path."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    fig = Figure(figsize=(12, 5))
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    draw_series(ax, plot_series(edges, flags, checkpoints, decisions),
                scale)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(loc='upper left', fontsize=8)
    ax.set_title(f"{os.path.basename(os.path.abspath(rundir))} — every "
                 f"recorded frame", loc='left', fontweight='bold')
    n_flag = sum(1 for f in (flags or []) if f['reasons'])
    fig.text(0.01, 0.01,
             f"Scale: {src}.  Triangles: {n_flag} frame(s) flagged for "
             f"review (the detector's own doubt, more than "
             f"{REVIEW_BAND_PCT:g} % outside the accepted stills of their "
             f"landing, or a jump of more than {REVIEW_JUMP_PCT:g} % from "
             f"their neighbours).",
             fontsize=7, color='#555555')
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    path = os.path.join(rundir, VIDEO_PLOT_FILENAME)
    fig.savefig(path, dpi=150)
    return path


# ---------------------------------------------------------------------------
# what the video pass ran with, and whether that is still current
# ---------------------------------------------------------------------------

def _num(v):
    """float, or None for blank / unparseable / non-finite."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float('inf'), float('-inf')) else None


def _write_json_atomic(path, obj):
    part = f"{path}.{os.getpid()}.part"
    with open(part, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1, sort_keys=True)
    os.replace(part, path)


def edges_stamp(settings, anchor, base_ref, scale, src, stride=1,
                limit=None):
    """The inputs a video pass ran with, as written to video_edges.json.

    Everything that changes a row of video_edges.csv: the detection
    settings, the baseline fit the tracker measures from, the area method,
    and the scale anchor (it sets area_mm2 and the scale named on every
    row). The OpenCV version is recorded for the reader, not compared:
    the review is often done on another machine than the bench."""
    import sldea_edge as se
    fit = base_ref.get('diam_px') if base_ref else None
    return {
        'written': datetime.datetime.now().isoformat(timespec='seconds'),
        'stride': int(stride), 'limit': limit,
        'scale_source': src, 'mm_per_px': scale,
        'anchor_diam_px': (round(float(anchor['diam_px']), 3)
                           if anchor and anchor.get('diam_px') else None),
        'anchor_saved': (anchor or {}).get('saved'),
        'baseline_fit_diam_px': round(float(fit), 1) if fit else None,
        'area_estimator': se.AREA_ESTIMATOR_VERSION,
        'settings': {k: settings.get(k)
                     for k in sorted(se.DEFAULT_SETTINGS)},
        'opencv_version': se.library_versions().get('opencv_version'),
    }


def read_stamp(rundir):
    """video_edges.json as a dict, or None (absent or unreadable)."""
    try:
        with open(os.path.join(rundir, VIDEO_STAMP_FILENAME),
                  encoding='utf-8') as f:
            out = json.load(f)
    except (OSError, ValueError):
        return None
    return out if isinstance(out, dict) else None


# The automatic baseline fit is recomputed by the reader, possibly on
# another machine and OpenCV; it moves by at most one pixel across the
# settings and optics on record (test_electrode_mask_255_only_costs_...),
# so two pixels is a change of fit, not of machine.
STAMP_FIT_TOL_PX = 2.0


def edges_stale(rundir):
    """None when video_edges.csv measured every frame with this run's
    CURRENT settings, baseline fit, area method and scale anchor; else
    one sentence naming each input that changed since.

    The usual reason is the order of a run's day: the post-run job
    measures the video minutes after the last still, before the operator
    has calibrated or reviewed anything, so its rows carry no scale and
    whatever baseline fit the uncalibrated run had."""
    import sldea_edge as se
    if not os.path.exists(os.path.join(rundir, VIDEO_EDGES_FILENAME)):
        return "there are no video edges yet"
    stamp = read_stamp(rundir)
    if stamp is None:
        return ("they were written before the video pass recorded what it "
                "ran with")
    why = []
    if stamp.get('stride', 1) != 1:
        why.append(f"only every {stamp['stride']}th frame was measured")
    if stamp.get('limit') is not None:
        why.append(f"only the first {stamp['limit']} frames were measured")
    if stamp.get('area_estimator') != se.AREA_ESTIMATOR_VERSION:
        why.append(f"the area method changed (estimator "
                   f"{stamp.get('area_estimator')} -> "
                   f"{se.AREA_ESTIMATOR_VERSION})")
    settings = se.load_settings(rundir)
    old = stamp.get('settings') or {}
    moved = []
    for k in sorted(se.DEFAULT_SETTINGS):
        a, b = old.get(k), settings.get(k)
        na, nb = _num(a), _num(b)
        same = (abs(na - nb) <= 1e-9 * max(1.0, abs(nb))
                if na is not None and nb is not None else a == b)
        if not same:
            moved.append(f"{k} {a} -> {b}")
    if moved:
        why.append("detection settings changed (" + ", ".join(moved) + ")")
    run = se.load_run(rundir)
    base_row = next((r for r in run['rows'] if r.get('tag') == 'baseline'
                     and (r.get('frame_file') or '').strip()), None)
    base = (video_gray(se.frame_path(run, base_row))
            if base_row is not None else None)
    ref = se.baseline_disc(base, settings) if base is not None else None
    fit_now = round(float(ref['diam_px']), 1) if ref else None
    fit_then = stamp.get('baseline_fit_diam_px')
    if (fit_now is None) != (fit_then is None) or (
            fit_now is not None
            and abs(fit_now - float(fit_then)) > STAMP_FIT_TOL_PX):
        why.append(f"the automatic baseline fit changed "
                   f"({_fit_text(fit_then)} -> {_fit_text(fit_now)})")
    anchor = se.load_scale_anchor(rundir)
    a_now = (round(float(anchor['diam_px']), 3)
             if anchor and anchor.get('diam_px') else None)
    a_then = stamp.get('anchor_diam_px')
    if (a_now is None) != (a_then is None) or (
            a_now is not None and abs(a_now - float(a_then)) > 1e-3):
        why.append(f"the scale anchor changed ({_fit_text(a_then)} -> "
                   f"{_fit_text(a_now)})")
    return "; ".join(why) if why else None


def _fit_text(d):
    return 'none' if d is None else f"{float(d):.1f} px"


# ---------------------------------------------------------------------------
# re-running the video pass after Edge Review's Save
# ---------------------------------------------------------------------------

def has_video(rundir):
    return all(os.path.exists(os.path.join(rundir, n))
               for n in (VIDEO_FILENAME, VIDEO_INDEX_FILENAME))


def launch_rerun(rundir, popen=None):
    """Start `sldea_video.py RUN --after-save` as a DETACHED, low-priority
    process (it logs into the run's run.log), so closing Edge Review, which
    a clean Save may now do by itself, cannot cut it off. -> the Popen.
    `popen` is for tests."""
    cmd = [sys.executable, os.path.abspath(__file__), rundir, '--after-save']
    # UTF-8 output: run.log lines carry warning signs, and a Windows
    # child writing to DEVNULL would otherwise encode them as cp1252
    kw = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
          'stderr': subprocess.DEVNULL,
          'env': dict(os.environ, PYTHONIOENCODING='utf-8')}
    if os.name == 'nt':
        kw['creationflags'] = (getattr(subprocess, 'DETACHED_PROCESS', 0)
                               | getattr(subprocess,
                                         'CREATE_NEW_PROCESS_GROUP', 0)
                               | getattr(subprocess,
                                         'BELOW_NORMAL_PRIORITY_CLASS', 0))
    else:
        kw['start_new_session'] = True
    return (popen or subprocess.Popen)(cmd, **kw)


def after_save(rundir, popen=None):
    """Edge Review's Save hook: re-run the video pass when its edges are
    out of date. -> one plain sentence for the status strip, or None when
    the run has no video in its folder (most runs; then nothing is said).

    No video in the folder also covers a run whose recording is still in
    local staging: the post-run job detects there first and moves the
    files in only afterwards, so a video in the folder means that job's
    detection is over and a re-run cannot race it."""
    if not has_video(rundir):
        return None
    try:
        why = edges_stale(rundir)
    except Exception as e:             # a staleness check must not cost a Save
        why = f"their inputs could not be checked ({e})"
    if why is None:
        return "video edges are current"
    try:
        launch_rerun(rundir, popen=popen)
    except Exception as e:
        return (f"video edges are out of date ({why}) and the re-run could "
                f"not start ({e}): run `python sldea_video.py \"{rundir}\"`")
    return f"video edges re-running in the background ({why})"


# ---------------------------------------------------------------------------
# reviewing the video by exception: the accepted stills as checkpoints
# ---------------------------------------------------------------------------

def read_edges(rundir):
    """video_edges.csv as typed dicts, frame order: numbers are floats or
    None, needs_review a bool. [] when there is no file."""
    path = os.path.join(rundir, VIDEO_EDGES_FILENAME)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            out.append({'frame': int(r['frame']), 't_s': _num(r['t_s']),
                        'nominal_kV': _num(r['nominal_kV']),
                        'area_px': _num(r['area_px']),
                        'area_mm2': _num(r['area_mm2']),
                        'conf': _num(r['conf']),
                        'method': r.get('method') or '',
                        'wrinkle': _num(r.get('wrinkle')),
                        'needs_review': (r.get('needs_review') or '')
                        .strip().lower() in ('true', '1', 'yes'),
                        'scale_source': r.get('scale_source') or ''})
    return out


# run.log's snapshot line names the still and the run-clock time of the
# stream frame it was taken from: "... -> NAME.png  (frame t=2.12s)".
_SNAP_FRAME_T = re.compile(r"(\S+\.png)\s+\(frame t=([0-9]+(?:\.[0-9]+)?)s\)")


def still_times(rundir):
    """{still file name: run-clock time of its stream frame} from run.log.
    {} when there is no run.log or no video-era snapshot lines."""
    out = {}
    try:
        with open(os.path.join(rundir, 'run.log'), encoding='utf-8',
                  errors='replace') as f:
            for line in f:
                m = _SNAP_FRAME_T.search(line)
                if m:
                    out[m.group(1)] = float(m.group(2))
    except OSError:
        pass
    return out


def _unbranded(name):
    """A still's name before a breakdown mark renamed it (the mark adds
    `_BREAKDOWN` before the extension; run.log keeps the original)."""
    return re.sub(r'_BREAKDOWN(?=\.png$)', '', name or '')


def still_checkpoints(rundir, run=None):
    """The run's ACCEPTED stills, as checkpoints on the video's clock.

    -> [{'frame_file', 'tag', 'step', 'nominal_kV', 't_s', 'area_px'}],
    time order. Accepted = data.csv holds an area for it (what Edge
    Review's Save wrote, machine-accepted or reviewed). The time is that
    of the stream frame the still was taken from (run.log); a run whose
    log lacks the line falls back to the planned time, which the scheduler
    keeps to within the grab latency. A still with neither is skipped."""
    import sldea_edge as se
    run = run or se.load_run(rundir)
    times = still_times(rundir)
    out = []
    for row in run['rows']:
        a = _num(row.get('active_area_px'))
        if a is None or a <= 0:
            continue
        name = (row.get('frame_file') or '').strip()
        t = times.get(name)
        if t is None:
            t = times.get(_unbranded(name))
        if t is None:
            t = _num(row.get('t_planned_s'))
        if t is None:
            continue
        out.append({'frame_file': name, 'tag': row.get('tag') or '',
                    'step': (row.get('step') or '').strip()
                    or f"kV {row.get('nominal_kV')}",
                    'nominal_kV': _num(row.get('nominal_kV')),
                    't_s': t, 'area_px': a})
    out.sort(key=lambda c: c['t_s'])
    return out


def landing_bands(checkpoints, band_pct=REVIEW_BAND_PCT):
    """[(t_first, t_last, area_lo, area_hi, stills)] per landing: the
    stills of one step bracket a stretch of constant drive, and a frame
    inside it should read within `band_pct` of their range."""
    by_step = {}
    for c in checkpoints:
        by_step.setdefault(c['step'], []).append(c)
    out = []
    for cs in by_step.values():
        areas = [c['area_px'] for c in cs]
        out.append((min(c['t_s'] for c in cs), max(c['t_s'] for c in cs),
                    min(areas) * (1.0 - band_pct / 100.0),
                    max(areas) * (1.0 + band_pct / 100.0), cs))
    out.sort(key=lambda b: b[0])
    return out


def still_offset(edges, checkpoints, min_n=3):
    """The run-wide ratio of the video's area to the stills' at the stills'
    own times (median over the stills that land on a recorded frame), or
    None with fewer than `min_n` of them.

    It is not 1.0 even when nothing is wrong: the video pass fits the
    baseline on the recorder's cvtColor decode and the stills on the PNG
    decode, and on a low-contrast disc the two fits differ. On
    13_backlight_2 (end-to-end check, 2026-10-06) the video read -1.19 %
    against the stills (p10 -1.54, p90 -0.80) from a 405.2 vs 407.2 px
    baseline fit. review_flags divides this out, so the band judges each
    frame against the stills, not the decode against the decode."""
    if not checkpoints or not edges:
        return None
    ts = [(e['t_s'], e['area_px']) for e in edges
          if e['t_s'] is not None and e['area_px']]
    if not ts:
        return None
    t_all = sorted(t for t, _a in ts)
    gaps = sorted(b - a for a, b in zip(t_all, t_all[1:]) if b > a)
    half = 0.5 * gaps[len(gaps) // 2] if gaps else REVIEW_MATCH_S
    ratios = []
    for c in checkpoints:
        t, a = min(ts, key=lambda p: abs(p[0] - c['t_s']))
        if abs(t - c['t_s']) <= half:
            ratios.append(a / c['area_px'])
    if len(ratios) < min_n:
        return None
    ratios.sort()
    k = len(ratios)
    return (ratios[k // 2] if k % 2
            else 0.5 * (ratios[k // 2 - 1] + ratios[k // 2]))


def review_flags(edges, checkpoints, band_pct=REVIEW_BAND_PCT,
                 jump_pct=REVIEW_JUMP_PCT, offset='auto'):
    """Which recorded frames a human should look at, and why.

    -> one dict per read_edges row, same order: {'frame', 't_s',
    'nominal_kV', 'area_px', 'reasons': [...], 'band': (lo, hi) or None}.
    An empty `reasons` means nobody needs to look. Reasons:

      'no edge' / 'failed: ...' / 'size-mismatch'
                     the detector produced no area for the frame;
      'detector'     its own needs_review verdict (conf, spread, fallback);
      'off-stills'   the frame lies in a landing bracketed by accepted
                     stills and reads more than band_pct outside their
                     range;
      'jump'         outside any landing: a one-frame spike (more than
                     jump_pct off both measured neighbours, the same way),
                     or the frame a step lands on (more than jump_pct off
                     the last measured frame that was not a spike). Only
                     the frame the step lands on is flagged, not the
                     neighbours on either side of it.

    The detector's doubt and the stills' agreement are BOTH required to
    pass a frame: the stills vouch for an area, not for an outline the
    detector itself would not accept.

    `offset`: the run-wide video/still ratio the bands are scaled by;
    'auto' measures it (still_offset), None or 1.0 compares raw areas."""
    if offset == 'auto':
        offset = still_offset(edges, checkpoints)
    k_off = float(offset) if offset else 1.0
    bands = [(t0, t1, lo * k_off, hi * k_off, cs)
             for t0, t1, lo, hi, cs in landing_bands(checkpoints, band_pct)]
    ts = sorted(e['t_s'] for e in edges if e['t_s'] is not None)
    gaps = sorted(b - a for a, b in zip(ts, ts[1:]) if b > a)
    half = 0.5 * gaps[len(gaps) // 2] if gaps else REVIEW_MATCH_S
    jumps = _jump_frames(edges, jump_pct)
    out = []
    for i, e in enumerate(edges):
        reasons = []
        a, t = e['area_px'], e['t_s']
        if a is None:
            m = e.get('method') or ''
            reasons.append(m if (m.startswith('failed')
                                 or m == 'size-mismatch') else 'no edge')
        elif e.get('needs_review'):
            reasons.append('detector')
        band = None
        if t is not None:
            for t0, t1, lo, hi, _cs in bands:
                if t0 - half <= t <= t1 + half:
                    band = (lo, hi)
                    break
        if a is not None:
            if band is not None:
                if not band[0] <= a <= band[1]:
                    reasons.append('off-stills')
            elif i in jumps:
                reasons.append('jump')
        out.append({'frame': e['frame'], 't_s': t,
                    'nominal_kV': e['nominal_kV'], 'area_px': a,
                    'reasons': reasons, 'band': band})
    return out


def _jump_frames(edges, jump_pct):
    """Indices of the frames that are a one-frame spike or the frame a
    step lands on (review_flags' 'jump'), over the whole series in frame
    order, so a landing in between still carries the reference across."""
    lim = jump_pct / 100.0
    meas = [i for i, e in enumerate(edges) if e['area_px'] is not None]
    out = set()
    ref = None
    for k, i in enumerate(meas):
        a = edges[i]['area_px']
        prev = edges[meas[k - 1]]['area_px'] if k > 0 else None
        nxt = edges[meas[k + 1]]['area_px'] if k + 1 < len(meas) else None
        if prev and nxt:
            dp, dn = a / prev - 1.0, a / nxt - 1.0
            if abs(dp) > lim and abs(dn) > lim and (dp > 0) == (dn > 0):
                out.add(i)              # a spike: the reference stays put
                continue
        if ref and abs(a / ref - 1.0) > lim:
            out.add(i)
        ref = a
    return out


def read_decisions(rundir, edges=None):
    """The review window's decisions -> ({frame: record}, dropped).

    A decision is about the AREA the detector reported when it was made;
    with `edges` given, a decision whose recorded area no longer matches
    the frame's current one (a re-run since) is dropped and counted, never
    silently carried onto a different measurement."""
    path = os.path.join(rundir, VIDEO_REVIEW_FILENAME)
    if not os.path.exists(path):
        return {}, 0
    now = ({e['frame']: e['area_px'] for e in edges}
           if edges is not None else None)
    out, dropped = {}, 0
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            try:
                frame = int(r['frame'])
            except (KeyError, ValueError):
                continue
            if r.get('decision') not in REVIEW_DECISIONS:
                continue
            a = _num(r.get('area_px'))
            if now is not None:
                cur = now.get(frame)
                if frame not in now or (a is None) != (cur is None) or (
                        a is not None and abs(a - cur) > 0.5):
                    dropped += 1
                    continue
            out[frame] = {'frame': frame, 't_s': _num(r.get('t_s')),
                          'decision': r['decision'], 'area_px': a,
                          'reasons': r.get('reasons') or '',
                          'user': r.get('user') or '',
                          'when': r.get('when') or ''}
    return out, dropped


def write_decisions(rundir, decisions):
    """Write {frame: record} to video_review.csv, frame order, whole or
    not at all (a .part renamed into place)."""
    path = os.path.join(rundir, VIDEO_REVIEW_FILENAME)
    part = f"{path}.{os.getpid()}.part"
    with open(part, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        w.writeheader()
        for frame in sorted(decisions):
            r = decisions[frame]
            w.writerow({'frame': frame,
                        't_s': '' if r.get('t_s') is None else r['t_s'],
                        'decision': r['decision'],
                        'area_px': ('' if r.get('area_px') is None
                                    else r['area_px']),
                        'reasons': r.get('reasons') or '',
                        'user': r.get('user') or '',
                        'when': r.get('when') or ''})
    os.replace(part, path)


def read_frame(cap, frame):
    """Frame `frame` of an open cv2.VideoCapture as 8-bit grey, or None.
    FFV1 is intra-only, so a seek lands exactly (measured 2026-10-06 with
    OpenCV 4.13: 45 of 45 random seeks returned the frame asked for)."""
    import cv2
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame))
    ok, img = cap.read()
    if not ok or img is None:
        return None
    return img if img.ndim == 2 else img[:, :, 0]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_log(rundir):
    """A logger that appends to the run's own run.log (and prints)."""
    path = os.path.join(rundir, 'run.log')

    def log(msg):
        line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
        try:
            print(line)
        except UnicodeEncodeError:       # a cp1252 console (Windows)
            print(line.encode('ascii', 'backslashreplace').decode())
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except OSError:
            pass
    return log


def finalize_and_detect(staging, rundir, detect=False):
    """The detached post-run job: detect on the LOCAL copy first (so the
    gigabytes are read from local disk, not back over the share), then
    move the files in. -> 0 when the video reached the run folder."""
    log = _run_log(rundir)
    have = all(os.path.exists(os.path.join(staging, n))
               for n in (VIDEO_FILENAME, VIDEO_INDEX_FILENAME))
    if detect and have:
        try:
            try:
                os.nice(10)          # a long background job: yield the CPU
            except (AttributeError, OSError):
                pass
            s = detect_video(rundir, log=log, video_dir=staging)
            log(f"video edges: {s['frames']} frames in {s['seconds']:.0f} "
                f"s, {_flag_text(s)} -> {VIDEO_EDGES_FILENAME}"
                + (f", {VIDEO_PLOT_FILENAME}" if s.get('png') else ''))
        except Exception as e:
            log(f"⚠ video edges: detection failed ({e}) -- run `python "
                f"sldea_video.py \"{rundir}\"` once the video is in place")
    elif detect:
        log("⚠ video edges: not run -- the recording or its index is "
            "missing from staging")
    moved = finalize(staging, rundir, log=log)
    return 0 if moved.get(VIDEO_FILENAME) else 1


def _ffmpeg_version():
    """'OpenCV x, avcodec y' for the record: FFmpeg 4.x reads past a gray
    frame (see FFMPEG_OVERREAD), 5.0 and later do not. '' when unknown."""
    try:
        import cv2
        avc = re.search(r'avcodec:\s*YES\s*\(([^)]*)\)',
                        cv2.getBuildInformation())
        return (f"OpenCV {cv2.__version__}, avcodec "
                f"{avc.group(1) if avc else 'not found'}")
    except Exception:
        return ''


def _selftest():
    """The encoder at all (64 x 48), then at the camera's 1920 x 1080, as
    a run's check_codec would see it (BENCH_TEST Q1)."""
    print(_ffmpeg_version())
    ok, why = codec_available()
    print(f"{VIDEO_FOURCC} lossless round trip: "
          + ("OK" if ok else f"FAILED -- {why}"))
    if not ok:
        return 1
    import numpy as np                  # importable: the probe just used it
    ok, why = codec_available(frame=np.random.default_rng(1).integers(
        0, 256, (1080, 1920), dtype=np.uint8))
    print(f"{VIDEO_FOURCC} lossless round trip at 1920 x 1080: "
          + ("OK" if ok else f"FAILED -- {why}"))
    return 0 if ok else 1


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__.split('Usage:')[1].split('Headless')[0].rstrip())
        return 0 if argv else 2
    if argv[0] == '--selftest':
        return _selftest()
    if argv[0] == '--finalize':
        rest = [a for a in argv[1:] if a != '--detect']
        if len(rest) != 2:
            print("--finalize needs STAGING and RUN")
            return 2
        return finalize_and_detect(rest[0], rest[1],
                                   detect='--detect' in argv)
    run, stride, limit, plot, after = None, 1, None, True, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ('--stride', '--limit') and i + 1 < len(argv):
            try:
                v = int(argv[i + 1])
            except ValueError:
                print(f"{a} needs a whole number")
                return 2
            if a == '--stride':
                stride = v
            else:
                limit = v
            i += 2
            continue
        if a == '--no-plot':
            plot = False
        elif a == '--after-save':
            after = True
        elif a.startswith('--'):
            print(f"unknown flag: {a}")
            return 2
        else:
            run = a
        i += 1
    if not run:
        print("give a run folder")
        return 2
    import sldea_edge as se
    rundir = se.resolve_run(run) or run
    if not os.path.exists(os.path.join(rundir, VIDEO_FILENAME)):
        print(f"no {VIDEO_FILENAME} in {rundir}")
        return 2
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass
    if after:
        return rerun_after_save(rundir, plot=plot)
    s = detect_video(rundir, stride=stride, limit=limit, plot=plot)
    print(f"video edges: {s['frames']} frames in {s['seconds']:.0f} s, "
          f"{_flag_text(s)} -> {s['csv']}"
          + (f", {s['png']}" if s.get('png') else ''))
    return 0


def _flag_text(s):
    off = s.get('still_offset')
    return (f"{s['flagged']} flagged for review against "
            f"{s['checkpoints']} accepted still(s) "
            f"({s['needs_review']} by the detector's own verdict"
            + (f"; the video reads {100.0 * (off - 1.0):+.2f} % against the "
               f"stills overall" if off else "") + ")")


def rerun_after_save(rundir, plot=True):
    """The detached job Edge Review's Save starts (launch_rerun): say why
    in run.log, measure every frame again, say what came of it. -> 0."""
    log = _run_log(rundir)
    try:
        why = edges_stale(rundir)
    except Exception as e:
        why = f"inputs not checked ({e})"
    log(f"video edges: re-running after Save ({why or 'current'})")
    try:
        s = detect_video(rundir, log=log, plot=plot)
    except Exception as e:
        log(f"⚠ video edges: the re-run after Save failed ({e}) -- run "
            f"`python sldea_video.py \"{rundir}\"`")
        return 1
    log(f"video edges: {s['frames']} frames in {s['seconds']:.0f} s, "
        f"{_flag_text(s)} -> {VIDEO_EDGES_FILENAME}"
        + (f", {VIDEO_PLOT_FILENAME}" if s.get('png') else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
