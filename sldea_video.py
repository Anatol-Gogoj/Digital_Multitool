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
  video_edges.png      area against elapsed time, with the kV staircase

Usage:
    python sldea_video.py RUN [--stride N] [--limit N] [--no-plot]
    python sldea_video.py --finalize STAGING RUN [--detect]
    python sldea_video.py --selftest

Headless tests: .venv/bin/python tests/test_sldea_video.py
"""
import csv
import datetime
import os
import queue
import sys
import threading
import time

VIDEO_FILENAME = 'video.mkv'
VIDEO_INDEX_FILENAME = 'video_frames.csv'
VIDEO_EDGES_FILENAME = 'video_edges.csv'
VIDEO_PLOT_FILENAME = 'video_edges.png'
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


def codec_available(tmpdir=None):
    """-> (True, '') when this OpenCV can write AND read back an FFV1 gray
    file bit-exactly, else (False, why). Never raises. Checked before a
    run starts -- before any HV -- because a build without the encoder
    would otherwise fail at the first frame, halfway into an hour."""
    import tempfile
    try:
        import cv2
        import numpy as np
    except ImportError as e:
        return False, f"OpenCV/numpy not importable ({e})"
    own = tmpdir is None
    d = path = None
    try:
        d = tempfile.mkdtemp(prefix='sldea_codec_') if own else tmpdir
        path = os.path.join(d, 'probe.mkv')
        frames = [np.full((48, 64), 40 * i, np.uint8) for i in range(1, 4)]
        frames[1][10:20, 10:30] = 200
        w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*VIDEO_FOURCC),
                            1.0, (64, 48), isColor=False)
        if not w.isOpened():
            return False, (f"this OpenCV build has no {VIDEO_FOURCC} "
                           f"encoder")
        for f in frames:
            w.write(f)
        w.release()
        cap = cv2.VideoCapture(path)
        try:
            for f in frames:
                ok, g = cap.read()
                if not ok:
                    return False, f"{VIDEO_FOURCC} file did not read back"
                g = g if g.ndim == 2 else g[:, :, 0]
                if not np.array_equal(g, f):
                    return False, (f"{VIDEO_FOURCC} round trip was NOT "
                                   f"lossless")
        finally:
            cap.release()
        return True, ''
    except Exception as e:
        return False, f"{VIDEO_FOURCC} probe failed: {e}"
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
        import cv2
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
            gray = frame if frame.ndim == 2 else cv2.cvtColor(
                frame, cv2.COLOR_BGR2GRAY)
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
                vw.write(gray)
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

    No human review queue: a video is thousands of frames. Every row
    carries the detector's own conf and needs_review verdict instead, so
    the doubtful stretches can be found and checked against the stills.
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
    ref = se.load_scale_anchor(rundir) or se.baseline_disc(base, settings)
    scale = se.mm_per_px({}, run['rows'], settings, baseline_ref=ref)
    src = se.scale_source({}, run['rows'], baseline_ref=ref)
    index = read_index(src_dir)
    out_path = os.path.join(rundir, VIDEO_EDGES_FILENAME)
    t_start = time.monotonic()
    rows, prev, done, decoded = [], None, 0, 0
    with open(out_path, 'w', newline='', encoding='utf-8') as fh:
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
    if limit is None and decoded != len(index):
        log(f"⚠ video edges: the video decoded {decoded} frames but its "
            f"index lists {len(index)} -- rows past the shorter one have "
            f"no time or kV")
    summary = {'frames': done, 'scale_mm_per_px': scale, 'scale_source': src,
               'needs_review': sum(1 for r in rows if r['needs_review']),
               'csv': out_path, 'seconds': time.monotonic() - t_start}
    if plot and rows:
        try:
            summary['png'] = plot_edges(rundir, rows, scale, src)
        except Exception as e:
            log(f"video edges: figure failed ({e}); the CSV is complete")
    return summary


def plot_edges(rundir, rows, scale, src):
    """Area against elapsed time, the kV staircase on a second axis. Open
    markers = the detector's own needs-review verdict. Paul Tol bright
    (CLAUDE.md): the measurement in blue, the drive in grey."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    pts = [r for r in rows if r['area_px'] != '' and r['t_s'] != '']
    fig = Figure(figsize=(12, 5))
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    key = 'area_mm2' if scale else 'area_px'
    for review, face in ((False, '#4477AA'), (True, 'white')):
        sel = [r for r in pts if bool(r['needs_review']) == review]
        if sel:
            ax.plot([r['t_s'] / 60.0 for r in sel], [r[key] for r in sel],
                    'o', markersize=3, color='#4477AA',
                    markerfacecolor=face, markeredgewidth=0.8,
                    label='needs review' if review else 'confident',
                    linestyle='')
    ax.set_xlabel('Elapsed time (min)')
    ax.set_ylabel('Active area (mm²)' if scale else 'Active area (px²)')
    ax.grid(alpha=0.3)
    kv = [(r['t_s'] / 60.0, r['nominal_kV']) for r in rows
          if r['t_s'] != '' and r['nominal_kV'] not in ('', None)]
    if kv:
        tw = ax.twinx()
        tw.step([k[0] for k in kv], [k[1] for k in kv], where='post',
                color='#BBBBBB', linewidth=1.0, zorder=0)
        tw.set_ylabel('Nominal kV', color='#777777')
    ax.legend(loc='upper left', fontsize=8)
    ax.set_title(f"{os.path.basename(os.path.abspath(rundir))} — every "
                 f"recorded frame", loc='left', fontweight='bold')
    fig.text(0.01, 0.01, f"Scale: {src}.  Open markers: the detector's own "
                         f"needs-review verdict (conf / spread / fallback).",
             fontsize=7, color='#555555')
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    path = os.path.join(rundir, VIDEO_PLOT_FILENAME)
    fig.savefig(path, dpi=150)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_log(rundir):
    """A logger that appends to the run's own run.log (and prints)."""
    path = os.path.join(rundir, 'run.log')

    def log(msg):
        line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
        print(line)
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
                f"s, {s['needs_review']} flagged for review -> "
                f"{VIDEO_EDGES_FILENAME}"
                + (f", {VIDEO_PLOT_FILENAME}" if s.get('png') else ''))
        except Exception as e:
            log(f"⚠ video edges: detection failed ({e}) -- run `python "
                f"sldea_video.py \"{rundir}\"` once the video is in place")
    elif detect:
        log("⚠ video edges: not run -- the recording or its index is "
            "missing from staging")
    moved = finalize(staging, rundir, log=log)
    return 0 if moved.get(VIDEO_FILENAME) else 1


def _selftest():
    ok, why = codec_available()
    print(f"{VIDEO_FOURCC} lossless round trip: "
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
    run, stride, limit, plot = None, 1, None, True
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
    s = detect_video(rundir, stride=stride, limit=limit, plot=plot)
    print(f"video edges: {s['frames']} frames in {s['seconds']:.0f} s, "
          f"{s['needs_review']} flagged for review -> {s['csv']}"
          + (f", {s['png']}" if s.get('png') else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
