#!/usr/bin/env python3
"""Tests for the SLDEA live view (#376): no camera, no instruments, fakes
throughout.

The view shows what a run already holds in memory and nothing else: a
video run's newest stream frame (VideoRecorder.latest_rgb), or a
stills-only run's newest still, which the run thread hands over in one
attribute (app._sldea_live_still). What is pinned here:

* The run thread's side: the hand-over is one reference swap of the very
  frame about to be saved (no copy), only for one-shot stills, and it
  never touches the view object. A closed, destroyed or never-opened
  view costs the run nothing, and a hand-over that raises is swallowed:
  the still is saved and its row written as before.
* The Tk side: the loop picks up a swapped still and labels it a still
  with its age, never as live; (None, None) from the recorder shows
  NO FRAME (stream stalled), and a NO FRAME on show before the run ended
  stays red through Abort (#388); a recorder left over from an earlier
  run is never read; the window survives the run end with its last frame
  labelled RUN ENDED; a new run clears the previous frame; a window
  destroyed without close() reopens with its picture (#388).
* The view never opens, grabs from or re-stamps the camera: every webcam
  entry point is replaced by a stub that fails the test if called.
* The start and end paths: sldea_run forgets the previous run before the
  worker thread exists and opens the view after it; _sldea_finished
  freezes it once the tab is released. The SLDEA tab has a button that
  opens it.

The window cases need a display and are skipped without one.

Run: .venv/bin/python tests/test_sldea_live_view.py
"""
import contextlib as _contextlib
import csv as _csv
import inspect as _inspect
import os as _os
import sys as _sys
import tempfile as _tempfile
import threading as _threading
import time as _time
import types as _types
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import numpy as _np  # noqa: E402

import gui  # noqa: E402
import sldea_liveview as lv  # noqa: E402
import sldea_profile  # noqa: E402
import sldea_video  # noqa: E402
import webcam  # noqa: E402
from sldea_profile import SldeaProfile  # noqa: E402

G = gui.InstrumentControlGUI


class _Skip(Exception):
    """Raised by a test that cannot run here (no display)."""


# --------------------------------------------------------------------------
# frames
# --------------------------------------------------------------------------

def _rgb(gray):
    g = _np.clip(gray, 0, 255).astype(_np.uint8)
    return _np.stack([g, g, g], axis=2)


def _disc_frame(paper=170, disc=110, h=240, w=320, r=60, seed=2):
    """A dark resting disc on lighter paper: a picture that reads OK."""
    rng = _np.random.default_rng(seed)
    yy, xx = _np.mgrid[0:h, 0:w]
    g = _np.full((h, w), float(paper))
    g[(xx - w / 2) ** 2 + (yy - h / 2) ** 2 <= r * r] = disc
    return _rgb(g + rng.normal(0, 2.0, size=(h, w)))


def _backlit_frame(h=240, w=320):
    """Run 13_backlight's look: about 60 % of the picture at 255."""
    g = _np.full((h, w), 255.0)
    g[:, : int(w * 0.4)] = 140.0
    return _rgb(g)


def _still(step=3, kv=1.25, tag='landing', age=0.0, frame=None):
    now = _time.monotonic() - age
    return lv.LiveStill(_disc_frame() if frame is None else frame, step,
                        kv, tag, 12.0, now, _time.time() - age)


def _profile(**kw):
    """Two landings, 2.1 s end to end (test_sldea_preflight's profile)."""
    opts = dict(start_kv=0.0, end_kv=0.5, step_kv=0.25, ramp_s=0.4,
                landing_s=0.5, settle_s=0.1, snap_lead_s=0.1,
                baseline_warmup_s=0.3)
    opts.update(kw)
    return SldeaProfile(**opts)


# --------------------------------------------------------------------------
# pure helpers
# --------------------------------------------------------------------------

def test_the_loop_runs_at_about_two_hz_and_the_ages_read_plainly():
    assert lv.PERIOD_MS == 500, lv.PERIOD_MS
    assert lv.fmt_age(0.25) == '0.2 s' or lv.fmt_age(0.25) == '0.3 s'
    assert lv.fmt_age(8.04) == '8.0 s'
    assert lv.fmt_age(42.4) == '42 s'
    assert lv.fmt_age(125) == '2 min 05 s'
    assert lv.fmt_age(3780) == '1 h 03 min'
    assert lv.fmt_age(None) == 'unknown'
    assert lv.fmt_age(-3) == '0.0 s'
    assert lv.fmt_clock(None) == '?'
    assert len(lv.fmt_clock(_time.time())) == 8
    assert lv.fmt_run_time(125) == '0:02:05'


def test_the_thumbnail_is_a_new_480_wide_array_and_the_frame_is_untouched():
    f = _disc_frame(h=1080, w=1920, r=300)
    before = f.copy()
    th = lv.thumbnail(f)
    assert th.shape == (270, 480, 3) and th.dtype == _np.uint8, th.shape
    assert not _np.shares_memory(th, f)
    assert _np.array_equal(f, before), "the run's frame was written to"
    # a 4:3 webcam keeps its aspect; a gray frame becomes RGB
    assert lv.thumbnail(_np.zeros((480, 640, 3), _np.uint8)).shape == \
        (360, 480, 3)
    assert lv.thumbnail(_np.zeros((96, 128), _np.uint8)).shape == \
        (360, 480, 3)


def test_the_exposure_readout_is_the_preflights_numbers():
    """Same definitions as the pre-flight: on a frame no wider than the
    sample the numbers are identical, and so is the verdict."""
    for frame in (_disc_frame(), _backlit_frame()):
        ro = lv.exposure_readout(frame)
        rep = sldea_profile.preflight_report(frame, 6, 60)
        assert abs(ro['mean'] - rep['mean']) < 1e-9, (ro, rep['mean'])
        assert abs(ro['sat_pct'] - rep['sat_pct']) < 1e-9
        assert ro['level'] == rep['level'], (ro, rep['level'])
    # a 1080p frame is sampled, and the estimate stays close
    big = _disc_frame(h=1080, w=1920, r=300)
    ro = lv.exposure_readout(big)
    rep = sldea_profile.preflight_report(big, 6, 60)
    assert abs(ro['mean'] - rep['mean']) < 1.0, (ro, rep['mean'])
    assert ro['level'] == rep['level'] == 'ok'


def test_a_backlit_frame_reads_clipped_from_its_first_look():
    """13_backlight shot 60 frames 57-66 % saturated with nothing on
    screen to say so. Here the words say it, not only the colour."""
    words, level, color = lv.exposure_words(
        lv.exposure_readout(_backlit_frame()))
    assert level == 'CLIPPED' and color == lv.TOL_RED, (level, color)
    assert 'saturated 60.0 %' in words, words
    words, level, color = lv.exposure_words(
        lv.exposure_readout(_disc_frame()))
    assert level == 'OK' and color == lv.TOL_GREEN, (level, words)
    assert lv.exposure_words(None) == ("", "", None)


def _px(img, x, y):
    return img.getpixel((int(x), int(y)))[:3]


def _hex(rgb):
    return '#%02X%02X%02X' % rgb


def test_every_state_is_named_on_the_picture_in_a_tol_colour():
    th = lv.thumbnail(_disc_frame())
    for kind, (word, color) in lv.BANNERS.items():
        thumb = th if kind in ('live', 'still', 'ended') else None
        img = lv.render(thumb, kind)
        assert img.size == (480, 360 if thumb is not None else 270), \
            (kind, img.size)
        assert _hex(_px(img, img.width - 3, 4)) == color, (kind, color)
        assert color in (lv.TOL_GREEN, lv.TOL_YELLOW, lv.TOL_RED,
                         lv.TOL_CYAN, lv.TOL_GREY)
        assert word, kind
    assert lv.BANNERS['stalled'][0] == "NO FRAME (stream stalled)"
    assert 'NOT LIVE' in lv.BANNERS['still'][0]
    assert 'NOT LIVE' in lv.BANNERS['ended'][0]


def test_the_reticle_has_the_preflights_geometry_and_never_marks_the_frame():
    th = lv.thumbnail(_disc_frame())
    before = th.copy()
    img = lv.render(th, 'live')
    assert _np.array_equal(th, before), "render drew into the thumbnail"
    w, h = img.size
    cx, cy, r = w / 2.0, h / 2.0, h * 0.32
    assert _hex(_px(img, cx, h * 0.8)) == lv.TOL_CYAN    # vertical line
    assert _hex(_px(img, w * 0.1, cy)) == lv.TOL_CYAN    # horizontal line
    # the circle: where it crosses the row 40 px below the centre
    xs = cx + (r * r - 40 * 40) ** 0.5
    hit = [_hex(_px(img, xs + d, cy + 40)) for d in (-1, 0, 1)]
    assert lv.TOL_CYAN in hit, hit
    # a NO FRAME picture carries no old frame at all
    img = lv.render(th, 'stalled')
    arr = _np.asarray(img)[30:]
    assert (arr < 8).mean() > 0.9, "NO FRAME must be on black"


def test_notify_never_raises():
    app = _types.SimpleNamespace(lines=[])
    app._sldea_log = app.lines.append
    assert lv.notify(app, 'open') is False            # no view at all

    class Broken:
        def open(self):
            raise RuntimeError('boom')
    app._sldea_live_view = Broken()
    assert lv.notify(app, 'open') is False
    assert app.lines and 'boom' in app.lines[0], app.lines
    assert lv.notify(app, 'no_such_action') is False
    # and with no log to write to either
    bare = _types.SimpleNamespace(_sldea_live_view=Broken())
    assert lv.notify(bare, 'open') is False


# --------------------------------------------------------------------------
# the run thread's side: one reference swap, nothing else
# --------------------------------------------------------------------------

class _Bomb:
    """A view the run thread must never touch: any attribute fails."""

    def __init__(self):
        object.__setattr__(self, 'touched', [])

    def __getattr__(self, name):
        self.touched.append(name)
        raise AssertionError(f"the run thread touched the view: {name}")


class _RunApp:
    """Just enough app for the REAL _sldea_worker and _sldea_capture."""
    SLDEA_POLL_S = G.SLDEA_POLL_S
    SLDEA_STAMP_LEAD_S = G.SLDEA_STAMP_LEAD_S
    SLDEA_STILL_WAIT_S = G.SLDEA_STILL_WAIT_S
    _sldea_worker = G._sldea_worker
    _sldea_capture = G._sldea_capture

    def __init__(self):
        self.scope = self.sg = None
        self._sldea_stop = False
        self._sldea_bd_tripped = False
        self._sldea_elapsed = 0.0
        self._sldea_prelog, self._sldea_runlog = [], None
        self._sldea_loglock = _threading.Lock()
        self._sldea_recorder = None
        self._sldea_video_jobs = []
        self.lines = []
        self.root = _types.SimpleNamespace(after=lambda *a, **k: None)

    def _sldea_log(self, msg):
        self.lines.append(str(msg))

    def _sldea_set_status(self, *a, **k):
        pass

    def _sldea_finished(self):
        pass


class _HandOverApp(_RunApp):
    """Records every hand-over the run thread makes."""

    def __init__(self):
        super().__init__()
        self.handed = []

    @property
    def _sldea_live_still(self):
        return self.__dict__.get('_still')

    @_sldea_live_still.setter
    def _sldea_live_still(self, value):
        self.__dict__['_still'] = value
        self.handed.append(value)


class _RaisingApp(_RunApp):
    """An app on which the hand-over itself raises."""

    @property
    def _sldea_live_still(self):
        return None

    @_sldea_live_still.setter
    def _sldea_live_still(self, value):
        raise RuntimeError("hand-over refused")


@_contextlib.contextmanager
def _oneshot(frame):
    saved = (webcam.resolve_camera, webcam.oneshot_rgb)
    seen = {'grabs': 0}

    def grab(_spec, count=2):
        seen['grabs'] += 1
        return frame
    webcam.resolve_camera = lambda idx: {'kind': 'cv2', 'index': 0}
    webcam.oneshot_rgb = grab
    try:
        yield seen
    finally:
        webcam.resolve_camera, webcam.oneshot_rgb = saved


def _capture(app, frame, stream=False, tmp=None):
    """The REAL _sldea_capture for one landing still -> (its return,
    the data.csv rows)."""
    p = _profile()
    snap = {'t': 1.0, 'step': 3, 'nominal_kv': 0.5, 'tag': 'landing'}
    framedir = _os.path.join(tmp, 'frames')
    _os.makedirs(framedir, exist_ok=True)
    path = _os.path.join(tmp, 'data.csv')
    with open(path, 'w', newline='') as fh:
        writer = _csv.DictWriter(fh, fieldnames=p.CSV_COLUMNS)
        writer.writeheader()
        with _oneshot(frame):
            got = app._sldea_capture(
                p, snap, 4, {'kind': 'cv2', 'index': 0}, framedir, writer,
                fh, 2, 3, True, t0=_time.monotonic() - 10.0, stream=stream,
                stream_frame=(frame, 1.0) if stream else (None, None))
    with open(path, newline='') as f:
        rows = list(_csv.DictReader(f))
    return got, rows


def test_a_still_is_handed_over_as_one_reference_to_the_saved_frame():
    frame = _disc_frame()
    app = _HandOverApp()
    with _tempfile.TemporaryDirectory() as tmp:
        got, rows = _capture(app, frame, tmp=tmp)
    assert got is frame
    assert len(app.handed) == 1, app.handed
    st = app.handed[0]
    assert isinstance(st, lv.LiveStill)
    assert st.frame is frame, "the hand-over must not copy the frame"
    assert (st.step, st.kv, st.tag) == (3, 0.5, 'landing'), st[1:4]
    assert 9.0 < st.t_run < 11.0, st.t_run
    assert abs(st.mono - _time.monotonic()) < 5.0
    assert rows and rows[0]['frame_file'], rows


def test_a_video_runs_stills_are_not_handed_over():
    """A video run's view reads the recorder's stream instead; the run
    thread keeps no second full-size frame for it."""
    app = _HandOverApp()
    with _tempfile.TemporaryDirectory() as tmp:
        _capture(app, _disc_frame(), stream=True, tmp=tmp)
    assert app.handed == [], app.handed


def test_a_hand_over_that_raises_never_reaches_the_run():
    frame = _disc_frame()
    app = _RaisingApp()
    with _tempfile.TemporaryDirectory() as tmp:
        got, rows = _capture(app, frame, tmp=tmp)
        assert got is frame
        assert rows and rows[0]['frame_file'], rows
        assert _os.path.exists(_os.path.join(tmp, 'frames',
                                             rows[0]['frame_file']))
    # ...and the same when the record itself cannot be built
    saved = lv.LiveStill

    def broken(*a, **k):
        raise TypeError("cannot build the record")
    lv.LiveStill = broken
    try:
        app = _HandOverApp()
        with _tempfile.TemporaryDirectory() as tmp:
            got, rows = _capture(app, frame, tmp=tmp)
        assert got is frame and rows and rows[0]['frame_file'], rows
        assert app.handed == []
    finally:
        lv.LiveStill = saved
    assert not any(ln.startswith('ERROR') for ln in app.lines), app.lines


def test_the_run_thread_never_touches_the_view_closed_or_never_opened():
    """A whole stills-only DRY run with a view that fails on any touch:
    the run completes, every still is handed over in order, and the view
    object was never looked at."""
    p = _profile()
    app = _HandOverApp()
    bomb = _Bomb()
    app._sldea_live_view = bomb
    with _tempfile.TemporaryDirectory() as tmp, _oneshot(_disc_frame()):
        t = _threading.Thread(
            target=app._sldea_worker, args=(p, tmp, 'RUN', 1, 2, 3, True),
            kwargs=dict(cam_exp=3, cam_gain=0), daemon=True)
        t.start()
        t.join(60)
        assert not t.is_alive(), ("the worker stalled", app.lines)
    assert bomb.touched == [], bomb.touched
    assert not any(ln.startswith('ERROR') for ln in app.lines), app.lines
    snaps = sorted(p.snapshots, key=lambda s: s['t'])
    assert [h.step for h in app.handed] == [s['step'] for s in snaps], \
        ([h.step for h in app.handed], snaps)
    assert [h.tag for h in app.handed] == [s['tag'] for s in snaps]
    monos = [h.mono for h in app.handed]
    assert monos == sorted(monos) and len(set(monos)) == len(monos)


def test_the_run_threads_code_has_one_hand_over_and_no_view_call():
    cap = _inspect.getsource(G._sldea_capture)
    work = _inspect.getsource(G._sldea_worker)
    assert cap.count('self._sldea_live_still =') == 1, cap
    for src, name in ((cap, '_sldea_capture'), (work, '_sldea_worker')):
        for word in ('_sldea_live_view', 'notify(', 'LiveView',
                     'begin_run', 'end_run'):
            assert word not in src, (name, word)
    assert '_sldea_live_still' not in work, "the worker swaps nothing"
    # the swap sits in a try that swallows everything, inside the
    # one-shot branch only
    i = cap.index('self._sldea_live_still =')
    head = cap[:i]
    assert head.rstrip().endswith('now = time.monotonic()'), head[-200:]
    assert 'if not stream:' in head[head.rindex('fname = p.frame_filename'):]
    tail = cap[i:]
    assert 'except Exception:' in tail[:600] and 'pass' in tail[:600]


def test_the_start_path_forgets_the_last_run_before_the_worker_exists():
    src = _inspect.getsource(G.sldea_run)
    clear = src.index('self._sldea_live_still = None')
    begin = src.index("sldea_liveview.notify(self, 'begin_run', p, dry)")
    thread = src.index('threading.Thread(')
    start = src.index('daemon=True).start()')
    opened = src.index("sldea_liveview.notify(self, 'open_with_run')")
    assert clear < begin < thread < start < opened, \
        (clear, begin, thread, start, opened)
    fin = _inspect.getsource(G._sldea_finished)
    assert fin.index("self.sldea_abort_btn.config(state='disabled')") < \
        fin.index("sldea_liveview.notify(self, 'end_run')"), fin
    assert fin.rstrip().endswith("sldea_liveview.notify(self, 'end_run')")


# --------------------------------------------------------------------------
# the window (needs a display)
# --------------------------------------------------------------------------

def _tk():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    root.geometry('240x60+30+30')
    return root


def _pump(root, secs):
    end = _time.monotonic() + secs
    while _time.monotonic() < end:
        root.update()
        _time.sleep(0.02)


class _App:
    """What the view reads: the GUI's run state, nothing else."""

    def __init__(self, root):
        self.root = root
        self._sldea_running = False
        self._sldea_stop = False
        self._sldea_elapsed = 0.0
        self._sldea_recorder = None
        self._sldea_live_still = None
        self.lines = []

    def _sldea_log(self, msg):
        self.lines.append(str(msg))


class _Rec:
    """A recorder stand-in: latest() hands out a COPY of `frame` (BGR, as
    VideoRecorder.latest does) aged `age` s on the run clock, or
    (None, None). latest_rgb() is the whole-frame conversion the view must
    not use (review finding 6): it fails the test."""

    def __init__(self, frame=None, age=0.2, alive=True, t0=None):
        self.frame, self.age, self.alive = frame, age, alive
        self.t0 = _time.monotonic() - 30.0 if t0 is None else t0
        self.calls = 0

    def latest(self, max_age_s=sldea_video.STILL_MAX_AGE_S,
               not_before=None):
        self.calls += 1
        if self.frame is None:
            return None, None
        return self.frame.copy(), (_time.monotonic() - self.age - self.t0)

    def latest_rgb(self, *a, **k):
        raise AssertionError("the view converted a whole frame "
                             "(latest_rgb); it must use latest()")

    def reader_alive(self):
        return self.alive


@_contextlib.contextmanager
def _view(period_ms=100):
    """(root, app, view) with the view's window open on an idle app."""
    root = _tk()
    app = _App(root)
    view = lv.LiveView(app, period_ms=period_ms)
    app._sldea_live_view = view
    try:
        yield root, app, view
    finally:
        try:
            view.close()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass


def _start(app, view, p=None, dry=True):
    """What sldea_run does: clear, begin, (worker), open with the run."""
    app._sldea_running = True
    app._sldea_stop = False
    app._sldea_elapsed = 0.0
    app._sldea_live_still = None
    assert lv.notify(app, 'begin_run', p or _profile(), dry)
    assert lv.notify(app, 'open_with_run')


def _finish(app):
    """What _sldea_finished does."""
    app._sldea_running = False
    assert lv.notify(app, 'end_run')


def _texts(view):
    return ' | '.join(str(w.cget('text')) for w in (
        view._state_lbl, view._run_lbl, view._level_lbl, view._exp_lbl))


def test_the_loop_picks_up_a_swapped_still():
    with _view() as (root, app, view):
        _start(app, view)
        assert view.state['kind'] == 'waiting', view.state
        app._sldea_live_still = _still(step=3)          # the run thread
        _pump(root, 0.5)
        assert view.state['kind'] == 'still', view.state
        assert 'step 3 [landing]' in view._state_lbl.cget('text')
        assert view._job is not None, "the loop stopped"
        app._sldea_live_still = _still(step=4, kv=0.5)  # the next one
        _pump(root, 0.5)
        assert 'step 4 [landing] at 0.50 kV' in \
            view._state_lbl.cget('text'), _texts(view)
        assert view._photo is not None


def test_a_still_says_it_is_a_still_and_how_old_it_is():
    with _view() as (root, app, view):
        _start(app, view)
        app._sldea_live_still = _still(step=12, age=8.0)
        _pump(root, 0.3)
        text = view._state_lbl.cget('text')
        assert text.startswith('LAST STILL, not live: step 12'), text
        assert '8.' in text and 's ago' in text, text
        assert 'LIVE video' not in _texts(view)
        assert view.state['banner'] == "LAST STILL, NOT LIVE"
        # its exposure is the still's own, in words
        assert view._level_lbl.cget('text') == 'OK', _texts(view)


def test_no_frame_from_the_recorder_shows_no_frame_stream_stalled():
    with _view() as (root, app, view):
        _start(app, view)
        rec = _Rec(frame=None, alive=True)
        app._sldea_recorder = rec                       # this run's
        _pump(root, 0.3)
        assert view.state['kind'] == 'stalled', view.state
        assert view.state['banner'] == "NO FRAME (stream stalled)"
        assert view._state_lbl.cget('text').startswith('NO FRAME'), \
            _texts(view)
        assert view._level_lbl.cget('text') == ''      # nothing to judge
        assert rec.calls >= 1
        rec.alive = False                               # reader gone
        _pump(root, 0.3)
        assert view.state['banner'] == "NO FRAME (stream closed)"


def test_a_stream_frame_is_live_with_its_age_and_run_words():
    with _view() as (root, app, view):
        p = _profile()
        _start(app, view, p, dry=False)
        app._sldea_elapsed = 0.9
        app._sldea_recorder = _Rec(frame=_backlit_frame(), age=0.2)
        _pump(root, 0.3)
        assert view.state['kind'] == 'live', view.state
        text = view._state_lbl.cget('text')
        assert text.startswith('LIVE video stream: frame 0.'), text
        run = view._run_lbl.cget('text')
        assert run == (f"LIVE HV run: commanded {p.kv_at(0.9):.2f} kV, run "
                       f"time 0:00:01 of 0:00:02"), run
        assert view._level_lbl.cget('text') == 'CLIPPED', _texts(view)
        # a stall right after is shown at once, not as the old frame
        app._sldea_recorder.frame = None
        _pump(root, 0.3)
        assert view.state['kind'] == 'stalled'
        assert view.state['thumb'] is None


def test_a_tick_that_fails_after_a_live_frame_blanks_the_picture():
    """Adversarial review: a tick that raised used to leave the previous
    frame up under its LIVE banner. Now the picture goes black under an
    error banner, the loop carries on, and a recovery shows LIVE again."""
    with _view() as (root, app, view):
        _start(app, view)
        rec = _Rec(frame=_disc_frame(), age=0.1)
        app._sldea_recorder = rec
        _pump(root, 0.3)
        assert view.state['kind'] == 'live'

        def broken(*a, **k):
            raise RuntimeError("decoder hiccup")
        rec.latest = broken
        _pump(root, 0.3)
        assert view.state['kind'] == 'error', view.state
        assert view.state['thumb'] is None
        assert view.state['banner'] == "LIVE VIEW ERROR, NOT LIVE"
        text = view._state_lbl.cget('text')
        assert 'not live' in text and 'decoder hiccup' in text, text
        assert view._img_key == ('error', None)
        assert view._job is not None, "the loop died with the error"
        del rec.latest                             # it recovers
        _pump(root, 0.3)
        assert view.state['kind'] == 'live', view.state


def test_the_run_line_says_dry_and_stopping_and_never_claims_hv_off():
    with _view() as (root, app, view):
        _start(app, view, dry=True)
        _pump(root, 0.2)
        assert view._run_lbl.cget('text').startswith(
            'DRY run (no HV): plan at 0.00 kV'), _texts(view)
        app._sldea_stop = True
        _pump(root, 0.3)
        assert view._run_lbl.cget('text').startswith('Stopping'), \
            _texts(view)
        app._sldea_stop = False
        app._sldea_elapsed = 99.0
        _pump(root, 0.3)
        assert 'shutting down' in view._run_lbl.cget('text')
        _finish(app)
        ended = _texts(view)
        assert 'Run log' in ended, ended
        for claim in ('HV off', 'HV is off', 'zeroed', 'safe'):
            assert claim not in ended, (claim, ended)


def test_an_earlier_runs_recorder_is_never_shown_as_this_runs():
    with _view() as (root, app, view):
        old = _Rec(frame=_disc_frame(), age=0.1)        # still "fresh"
        app._sldea_recorder = old
        _start(app, view)
        _pump(root, 0.3)
        assert view.state['kind'] == 'waiting', view.state
        assert old.calls == 0, "the earlier run's recorder was read"
        # a stills-only run with an old recorder lying about
        app._sldea_live_still = _still(step=1)
        _pump(root, 0.3)
        assert view.state['kind'] == 'still' and old.calls == 0
        # this run's own recorder takes over
        app._sldea_recorder = _Rec(frame=_disc_frame(), age=0.1)
        _pump(root, 0.3)
        assert view.state['kind'] == 'live', view.state


def test_the_window_survives_the_run_end_with_its_last_frame_labelled():
    with _view() as (root, app, view):
        _start(app, view)
        app._sldea_live_still = _still(step=5, kv=0.5, tag='pre-ramp')
        _pump(root, 0.3)
        _finish(app)
        assert view.is_open(), "the window closed with the run"
        assert view.state['kind'] == 'ended', view.state
        text = view._state_lbl.cget('text')
        assert text.startswith('RUN ENDED at '), text
        assert 'not live' in text and 'still step 5 [pre-ramp]' in text, \
            text
        assert view.state['thumb'] is not None and view._photo is not None
        assert view.state['banner'] == "RUN ENDED, NOT LIVE"
        assert view._job is None, "the loop outlived the run"
        assert app._sldea_live_still is None, "the full frame was kept"
        _pump(root, 0.4)
        assert view.state['kind'] == 'ended' and view._job is None
        # closing and reopening after the run shows the same last frame
        view.close()
        assert lv.notify(app, 'open')
        assert view.state['kind'] == 'ended' and 'step 5' in \
            view._state_lbl.cget('text')


def test_the_final_still_is_picked_up_at_the_end_without_a_tick():
    with _view(period_ms=10000) as (root, app, view):
        _start(app, view)
        app._sldea_live_still = _still(step=7, tag='post-ramp')
        _finish(app)                    # no tick ran in between
        assert 'still step 7 [post-ramp]' in \
            view._state_lbl.cget('text'), _texts(view)


def test_a_video_run_that_ends_keeps_its_last_good_frame_not_the_stall():
    with _view() as (root, app, view):
        _start(app, view)
        rec = _Rec(frame=_disc_frame(), age=0.1)
        app._sldea_recorder = rec
        _pump(root, 0.3)
        assert view.state['kind'] == 'live'
        rec.frame, rec.alive = None, False          # the recorder stops
        _pump(root, 0.3)
        assert view.state['kind'] == 'closed'
        _finish(app)
        text = view._state_lbl.cget('text')
        assert 'video stream frame taken' in text, text
        assert view.state['thumb'] is not None


def test_a_new_run_clears_the_previous_frame():
    with _view() as (root, app, view):
        _start(app, view)
        app._sldea_live_still = _still(step=5)
        _pump(root, 0.3)
        _finish(app)
        assert 'step 5' in view._state_lbl.cget('text')
        _start(app, view)                       # the next run
        assert view.state['kind'] == 'waiting', view.state
        assert view.state['thumb'] is None
        assert 'step 5' not in _texts(view), _texts(view)
        assert view._good is None
        _pump(root, 0.3)
        assert view.state['kind'] == 'waiting'


def test_closing_stops_the_loop_and_reopening_shows_the_newest():
    with _view() as (root, app, view):
        _start(app, view)
        app._sldea_live_still = _still(step=2)
        _pump(root, 0.3)
        lv.notify(app, 'close')
        assert not view.is_open() and view._job is None
        # the run goes on handing over stills with nobody looking
        app._sldea_live_still = _still(step=3)
        _pump(root, 0.3)
        assert view._job is None
        assert lv.notify(app, 'open')
        assert 'step 3' in view._state_lbl.cget('text'), _texts(view)
        assert view._job is not None


def test_a_destroyed_window_or_root_never_raises():
    """...and a window destroyed without close() reopens WITH its picture
    (#388). The new window's label gets an image of its own; it used to
    be left blank while _show pasted into the dead window's image, which
    it did whenever the two pictures were the same size."""
    with _view() as (root, app, view):
        _start(app, view)
        app._sldea_live_still = _still(step=1)
        _pump(root, 0.3)
        assert view.state['kind'] == 'still' and view._photo is not None
        old = view._photo
        view.win.destroy()                       # the window manager's way
        _pump(root, 0.3)
        assert view._job is None
        app._sldea_live_still = _still(step=2)   # the same size as step 1
        _finish(app)
        assert view.state['kind'] == 'ended'
        assert lv.notify(app, 'open')            # reopens cleanly
        assert view.is_open() and 'step 2' in view._state_lbl.cget('text')
        shown = str(view._img_lbl.cget('image'))
        assert shown and shown == str(view._photo), (shown, view._photo)
        assert view._photo is not old
        root.destroy()
        view._tick()                             # a late tick: no raise
        assert lv.notify(app, 'end_run') in (True, False)
        assert lv.notify(app, 'open') in (True, False)


# The camera's every entry point, for the "never opens it" test.
_WEBCAM_FUNCS = ('list_cameras', '_v4l2', 'device_formats', 'bayer_format',
                 'set_locked', 'apply_locked', 'list_controls',
                 'get_control', 'set_control', 'set_manual_exposure',
                 'grab_raw', 'auto_exposure', 'resolve_camera',
                 'oneshot_rgb')
_WEBCAM_METHODS = (('V4L2BayerCamera', 'open'), ('V4L2BayerCamera', 'read'),
                   ('V4L2BayerCamera', 'read_rgb'), ('Camera', 'open'),
                   ('Camera', 'read'), ('Camera', 'read_rgb'))


@_contextlib.contextmanager
def _no_camera():
    import subprocess
    calls = []

    def stub(name):
        def fail(*a, **k):
            calls.append(name)
            raise AssertionError(f"the live view called {name}")
        return fail
    saved = []
    for name in _WEBCAM_FUNCS:
        saved.append((webcam, name, getattr(webcam, name)))
        setattr(webcam, name, stub('webcam.' + name))
    for cls, meth in _WEBCAM_METHODS:
        owner = getattr(webcam, cls)
        saved.append((owner, meth, getattr(owner, meth)))
        setattr(owner, meth, stub(f'webcam.{cls}.{meth}'))
    saved.append((sldea_video, 'open_stream', sldea_video.open_stream))
    sldea_video.open_stream = stub('sldea_video.open_stream')
    for name in ('Popen', 'run'):
        saved.append((subprocess, name, getattr(subprocess, name)))
        setattr(subprocess, name, stub('subprocess.' + name))
    try:
        import cv2
        saved.append((cv2, 'VideoCapture', cv2.VideoCapture))
        cv2.VideoCapture = stub('cv2.VideoCapture')
    except ImportError:
        pass
    try:
        yield calls
    finally:
        for owner, name, value in reversed(saved):
            setattr(owner, name, value)


def test_the_view_never_opens_or_grabs_the_camera():
    with _no_camera() as calls, _view() as (root, app, view):
        assert lv.notify(app, 'open')                     # idle
        assert view.state['kind'] == 'idle'
        _start(app, view)                                 # waiting
        _pump(root, 0.3)
        app._sldea_live_still = _still(step=1)            # still
        _pump(root, 0.3)
        assert view.state['kind'] == 'still'
        _finish(app)                                      # ended
        _start(app, view)                                 # video run
        rec = _Rec(frame=_disc_frame())
        app._sldea_recorder = rec
        _pump(root, 0.3)
        assert view.state['kind'] == 'live'
        rec.frame = None                                  # stalled
        _pump(root, 0.3)
        assert view.state['kind'] == 'stalled'
        rec.alive = False                                 # closed
        _pump(root, 0.3)
        lv.notify(app, 'close')
        lv.notify(app, 'open')
        _finish(app)
        assert view.state['kind'] == 'ended'
    assert calls == [], calls


def test_the_sldea_tab_has_a_button_that_opens_the_view():
    """On the REAL GUI: the button exists, opens the window on an idle
    app, and the window says there has been no run."""
    import tkinter as tk
    from tkinter import ttk
    root = _tk()
    try:
        gui.InstrumentControlGUI.auto_connect = lambda self: None
        app = gui.InstrumentControlGUI(root)
        root.geometry('1300x900')
        root.deiconify()
        assert app.select_manual_tab('sldea'), "cannot find the SLDEA tab"
        _pump(root, 0.3)

        def buttons(w):
            out = []
            for c in w.winfo_children():
                if isinstance(c, (ttk.Button, tk.Button)):
                    out.append(c)
                out += buttons(c)
            return out
        [btn] = [b for b in buttons(app.sldea_run_btn.master)
                 if str(b.cget('text')).startswith('Live view')]
        assert isinstance(app._sldea_live_view, lv.LiveView)
        assert app._sldea_live_still is None
        btn.invoke()
        _pump(root, 0.2)
        view = app._sldea_live_view
        assert view.is_open() and view.state['kind'] == 'idle', view.state
        assert view._job is None, "an idle view polls nothing"
        view.close()
    finally:
        root.destroy()


# --------------------------------------------------------------------------
# review findings (2026-10-06)
# --------------------------------------------------------------------------

def test_placement_opens_beside_only_with_room_on_the_main_windows_monitor():
    """Findings 1 and 2. Beside the main window when the whole view fits
    on the main window's own monitor; otherwise inside the main window's
    own rectangle, flagged so the caller keeps the main window above."""
    size = (520, 600)
    primary = (0, 0, 1646, 1029)
    # room on the right
    assert lv.choose_place((100, 100, 700, 500), primary, size) == \
        (816, 100, False)
    # no room right, room left
    assert lv.choose_place((900, 50, 700, 500), primary, size) == \
        (364, 50, False)
    # a maximised main window: no room anywhere -> inside it, covering
    x, y, covers = lv.choose_place((0, 0, 1646, 1000), primary, size)
    assert covers and (x, y) == (1126, 0), (x, y, covers)
    # never below the monitor's bottom (48 px for a taskbar)
    assert lv.choose_place((100, 700, 700, 300), primary, size)[1] == 381
    # Finding 2: the main window on a second monitor right of the
    # primary. The old rule clamped to the primary's width and opened
    # the view on the FIRST monitor, at x = 1118.
    second = (1646, 0, 3566, 1050)
    x, y, covers = lv.choose_place((1700, 100, 900, 600), second, size)
    assert (x, covers) == (2616, False) and x >= 1646, (x, covers)
    # ...and maximised there: inside it, on the second monitor
    x, y, covers = lv.choose_place((1646, 0, 1920, 1010), second, size)
    assert covers and 1646 <= x <= 3566 - 520, (x, covers)
    # a main window that is not on the area handed in is never placed
    # "beside" on that area: the area is some other monitor
    x, y, covers = lv.choose_place((2000, 100, 700, 500), primary, size)
    assert covers and x >= 2000, (x, covers)


def test_the_main_windows_monitor_is_its_own_on_windows():
    """Finding 2: user32's work area of the monitor that holds the main
    window, in Tk's coordinates."""
    if _sys.platform != 'win32':
        raise _Skip("Windows only: elsewhere the X screen is used")
    root = _tk()
    try:
        root.geometry('300x200+120+140')
        root.update()
        area = lv.win32_work_area(root)
        assert area is not None, "no work area from user32"
        x0, y0, x1, y1 = area
        rx, ry = root.winfo_rootx(), root.winfo_rooty()
        assert x0 <= rx < x1 and y0 <= ry < y1, (area, rx, ry)
        # ...and it is what the view places itself against, not the
        # primary screen's width
        view = lv.LiveView(_types.SimpleNamespace(root=root))
        assert view._monitor_area() == area, (view._monitor_area(), area)
        # (here the primary's work area may equal the screen, so prove it
        # with a monitor that is clearly not the primary)
        saved = lv.win32_work_area
        lv.win32_work_area = lambda _root: (1646, -1080, 3566, 0)
        try:
            assert view._monitor_area() == (1646, -1080, 3566, 0)
        finally:
            lv.win32_work_area = saved
    finally:
        root.destroy()
    assert lv.win32_work_area(_types.SimpleNamespace(
        wm_frame=lambda: 'not a handle')) is None


class _Spy:
    """Wraps a root method, recording calls and passing them through."""

    def __init__(self, root, name, calls):
        self.real = getattr(root, name)
        self.name, self.calls = name, calls

    def __call__(self, *a, **k):
        self.calls.append(self.name)
        return self.real(*a, **k)


def _spy(root):
    calls = []
    root.focus_force = _Spy(root, 'focus_force', calls)
    root.lift = _Spy(root, 'lift', calls)
    return calls


def _stack(root):
    return root.tk.eval('wm stackorder .').split()


def test_the_run_start_open_gives_the_keyboard_back_to_the_main_window():
    """Finding 3: the window built at a run start hands the focus back to
    the main window once it is mapped, and with room beside the main
    window it opens there, covering nothing."""
    with _view() as (root, app, view):
        root.geometry('240x60+30+30')
        root.update()
        calls = _spy(root)
        view._monitor_area = lambda: (0, 0, 3000, 2000)
        _start(app, view)
        _pump(root, 0.4)
        assert calls.count('focus_force') == 1, calls
        assert 'lift' not in calls, calls
        assert not view._covers_root
        assert view.win.winfo_rootx() > root.winfo_rootx() + 240, \
            view.win.winfo_geometry()


def test_with_no_room_the_run_start_open_stays_behind_the_main_window():
    """Finding 1: no free room (here: the monitor is exactly the main
    window) puts the view inside the main window's rectangle, and the
    main window is raised above it once it is mapped. The button still
    brings it to the front."""
    with _view() as (root, app, view):
        root.geometry('700x620+30+30')
        root.update()
        calls = _spy(root)
        rx, ry = root.winfo_rootx(), root.winfo_rooty()
        view._monitor_area = lambda: (rx, ry, rx + root.winfo_width(),
                                      ry + root.winfo_height())
        _start(app, view)
        _pump(root, 0.5)
        assert view._covers_root
        assert calls == ['lift', 'focus_force'], calls
        order = _stack(root)
        assert order[-1] == '.', ("the view opened over the main window",
                                  order)
        vx = view.win.winfo_rootx()
        assert rx <= vx <= rx + root.winfo_width(), (vx, rx)
        # the operator's button: in front, and no focus taken back
        del calls[:]
        assert lv.notify(app, 'open')
        _pump(root, 0.3)
        assert _stack(root)[-1] == str(view.win), _stack(root)
        assert calls == [], calls
        # a later run start leaves an existing window where it is
        _finish(app)
        _start(app, view)
        _pump(root, 0.3)
        assert calls == [], calls


def test_a_stream_frame_is_never_shown_as_a_still():
    """Finding 4: a recorder that stops being readable (a natural cleanup
    of _sldea_recorder would do it) leaves a STREAM frame in hand. That
    is not a still: no 'still' state, no VIEW ERROR, and the run end
    still shows the stream frame. Mid-run it is a red NO FRAME that the
    staircase's end does not relabel (#388); once the staircase is over
    it is the run ending."""
    with _view() as (root, app, view):
        _start(app, view)
        app._sldea_recorder = _Rec(frame=_disc_frame(), age=0.1)
        _pump(root, 0.3)
        assert view.state['kind'] == 'live'
        app._sldea_recorder = None                       # cleaned up
        _pump(root, 0.3)
        assert view.state['kind'] == 'closed', view.state
        assert 'error' not in view.state['kind']
        app._sldea_elapsed = 99.0                        # staircase over
        _pump(root, 0.3)
        assert view.state['kind'] == 'closed', view.state
        _finish(app)
        text = view._state_lbl.cget('text')
        assert view.state['kind'] == 'ended'
        assert 'video stream frame taken' in text, text
        # cleaned up only after the staircase: the run ending, in grey
        _start(app, view)
        app._sldea_recorder = _Rec(frame=_disc_frame(), age=0.1)
        _pump(root, 0.3)
        assert view.state['kind'] == 'live'
        app._sldea_elapsed = 99.0
        app._sldea_recorder = None
        _pump(root, 0.3)
        assert view.state['kind'] == 'finishing', view.state
    # and the state builder refuses a still state on a stream frame
    view = lv.LiveView(_types.SimpleNamespace(root=None))
    view._good = {'src': 'stream', 'wall': _time.time(), 'thumb': None,
                  'exposure': None, 'seq': 1.0}
    view._p = _profile()
    st = view._state('still', _time.monotonic(), _time.time())
    assert st['kind'] == 'closed', st


def test_a_stream_closing_as_the_run_finishes_is_grey_not_a_fault():
    """Finding 5: between rec.stop() and _sldea_finished the stream
    closes at every normal video-run end. A stream still delivering when
    the staircase ended or the run was stopped, which closes or stalls
    only after that, is RECORDING ENDED in grey, with the last frame
    kept. (A NO FRAME already on show before the run ended stays red:
    the next test, #388.)"""
    with _view() as (root, app, view):
        p = _profile()
        _start(app, view, p)
        rec = _Rec(frame=_disc_frame(), age=0.1)
        app._sldea_recorder = rec
        app._sldea_elapsed = 1.0
        _pump(root, 0.3)
        assert view.state['kind'] == 'live'
        # the staircase is over; the stream delivers until rec.stop()
        app._sldea_elapsed = p.total_duration_s + 0.1
        _pump(root, 0.3)
        assert view.state['kind'] == 'live', view.state
        # ...and then closes: grey, in words, with the last frame
        rec.frame, rec.alive = None, False
        _pump(root, 0.3)
        st = view.state
        assert st['kind'] == 'finishing', st
        assert st['banner'] == "RECORDING ENDED, NOT LIVE"
        assert lv.BANNERS['finishing'][1] == lv.TOL_GREY
        assert 'expected' in st['text'] and 'NO FRAME' not in st['text']
        assert st['thumb'] is not None
        # a stall that starts only after an Abort is the run ending too
        _finish(app)
        _start(app, view, p)
        rec = _Rec(frame=_disc_frame(), age=0.1)
        app._sldea_recorder = rec
        app._sldea_elapsed = 1.0
        _pump(root, 0.3)
        assert view.state['kind'] == 'live'
        app._sldea_stop = True                           # Abort
        _pump(root, 0.3)
        assert view.state['kind'] == 'live', view.state
        rec.frame = None                                 # stalls after it
        _pump(root, 0.3)
        assert view.state['kind'] == 'finishing', view.state


def test_a_no_frame_on_show_before_the_run_ended_stays_red():
    """#388: the camera dies, the view says NO FRAME in red, and the
    operator presses Abort BECAUSE of it. That used to turn into the grey
    "RECORDING ENDED ... This is expected." A stall or close the view
    showed while the run was still going now stays red until the run has
    ended: after an Abort and at the staircase's end alike, and through
    a close and reopen of the window. A frame coming back clears it, and
    a new run starts clean."""
    with _view() as (root, app, view):
        p = _profile()
        _start(app, view, p)
        rec = _Rec(frame=_disc_frame(), age=0.1)
        app._sldea_recorder = rec
        app._sldea_elapsed = 1.0
        _pump(root, 0.3)
        assert view.state['kind'] == 'live'
        rec.frame = None                                 # camera unplugged
        _pump(root, 0.3)
        assert view.state['kind'] == 'stalled'
        app._sldea_stop = True                           # Abort, for that
        _pump(root, 0.3)
        st = view.state
        assert st['kind'] == 'stalled', st
        assert st['banner'] == "NO FRAME (stream stalled)"
        assert lv.BANNERS['stalled'][1] == lv.TOL_RED
        assert st['text'].startswith('NO FRAME'), st['text']
        assert 'expected' not in st['text'], st['text']
        assert view._run_lbl.cget('text').startswith('Stopping'), \
            _texts(view)
        rec.alive = False                                # rec.stop()
        _pump(root, 0.3)
        assert view.state['kind'] == 'closed', view.state
        lv.notify(app, 'close')                          # and reopened
        assert lv.notify(app, 'open')
        assert view.state['kind'] == 'closed', view.state
        _finish(app)
        assert view.state['kind'] == 'ended'
        # a new run forgets that: stopped before its stream gave a frame,
        # its stall comes after the stop and is the run ending
        _start(app, view, p)
        app._sldea_stop = True
        app._sldea_recorder = _Rec(frame=None)
        _pump(root, 0.3)
        assert view.state['kind'] == 'finishing', view.state
        _finish(app)
        # the staircase's end after a death mid-run: red as well
        _start(app, view, p)
        rec = _Rec(frame=_disc_frame(), age=0.1)
        app._sldea_recorder = rec
        app._sldea_elapsed = 1.0
        _pump(root, 0.3)
        assert view.state['kind'] == 'live'
        rec.frame, rec.alive = None, False               # dies mid-run
        _pump(root, 0.3)
        assert view.state['kind'] == 'closed'
        app._sldea_elapsed = p.total_duration_s + 0.1    # staircase over
        _pump(root, 0.3)
        assert view.state['kind'] == 'closed', view.state
        assert lv.BANNERS['closed'][1] == lv.TOL_RED
        # a frame coming back clears it: a stall after that is the end
        rec.frame, rec.alive = _disc_frame(), True
        _pump(root, 0.3)
        assert view.state['kind'] == 'live', view.state
        rec.frame = None
        _pump(root, 0.3)
        assert view.state['kind'] == 'finishing', view.state


def test_only_the_thumbnail_is_converted_from_bgr():
    """Finding 6: the view reads latest() (BGR) and converts the small
    thumbnail alone. A pure-blue BGR frame must come out blue."""
    bgr = _np.zeros((1080, 1920, 3), _np.uint8)
    bgr[:, :, 0] = 255                                  # B in BGR
    th = lv.thumbnail(bgr, bgr=True)
    assert th.shape == (270, 480, 3)
    assert tuple(th[100, 100]) == (0, 0, 255), th[100, 100]
    assert tuple(lv.thumbnail(bgr)[100, 100]) == (255, 0, 0)
    # the exposure numbers do not depend on the channel order (a frame
    # with real colour, so the check is not trivially true)
    rng = _np.random.default_rng(5)
    rgb = rng.integers(0, 256, size=(240, 320, 3), dtype=_np.uint8)
    a = lv.exposure_readout(rgb)
    b = lv.exposure_readout(rgb[:, :, ::-1].copy())
    assert a == b, (a, b)
    with _view() as (root, app, view):
        _start(app, view)
        rec = _Rec(frame=bgr[:240, :320].copy(), age=0.1)
        app._sldea_recorder = rec
        _pump(root, 0.3)
        assert view.state['kind'] == 'live', view.state  # latest_rgb fails
        assert rec.calls >= 1
        assert tuple(view.state['thumb'][50, 50]) == (0, 0, 255)


def test_fonts_are_truetype_first_cached_and_shared_with_edge_review():
    """Finding 7: one fallback chain (pil_fonts.bold_font), cached per
    size; Edge Review's letter tags use the same font object."""
    import pil_fonts
    from PIL import ImageFont
    f40 = pil_fonts.bold_font(40)
    assert pil_fonts.bold_font(40) is f40
    assert pil_fonts.bold_font(18) is not f40
    if isinstance(f40, ImageFont.FreeTypeFont):
        assert f40.size == 40
    import sldea_edge_gui
    saved = sldea_edge_gui._TAG_FONT
    sldea_edge_gui._TAG_FONT = None
    try:
        assert sldea_edge_gui._tag_font() is \
            pil_fonts.bold_font(sldea_edge_gui.TAG_PX)
        assert sldea_edge_gui._tag_font() is sldea_edge_gui._tag_font()
    finally:
        sldea_edge_gui._TAG_FONT = saved
    # rendering builds no font once the sizes are cached
    lv.render(None, 'stalled')
    real = ImageFont.truetype
    built = []

    def counting(*a, **k):
        built.append(a)
        return real(*a, **k)
    ImageFont.truetype = counting
    try:
        for kind in ('stalled', 'finishing', 'live'):
            lv.render(lv.thumbnail(_disc_frame()), kind)
    finally:
        ImageFont.truetype = real
    assert built == [], built


def test_the_font_chain_falls_back_to_the_bitmap_on_an_old_pillow():
    """Finding 7: with no TrueType face and a Pillow whose load_default
    takes no size, the chain still returns a font, and caches it."""
    import pil_fonts
    from PIL import ImageFont
    saved = (ImageFont.truetype, ImageFont.load_default,
             dict(pil_fonts._CACHE))
    tried = []

    def no_ttf(name, size):
        tried.append(name)
        raise OSError("cannot open resource")
    bitmap = object()                      # stands for the bitmap font

    def old_default(*a, **k):
        if a or k:
            raise TypeError("load_default() takes no arguments")
        return bitmap
    ImageFont.truetype, ImageFont.load_default = no_ttf, old_default
    pil_fonts._CACHE.clear()
    try:
        f = pil_fonts.bold_font(77)
        assert f is bitmap
        assert tuple(tried) == pil_fonts.BOLD_CHAIN, tried
        assert pil_fonts.bold_font(77) is f
        assert len(tried) == len(pil_fonts.BOLD_CHAIN)   # cached
    finally:
        ImageFont.truetype, ImageFont.load_default = saved[:2]
        pil_fonts._CACHE.clear()
        pil_fonts._CACHE.update(saved[2])


def test_ref_keeps_no_recorder_alive_and_says_when_it_must():
    """Finding 8: a weakref for what takes one (a VideoRecorder does), a
    documented strong reference only for what cannot."""
    import gc
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        rec = sldea_video.VideoRecorder(lambda: None, tmp)
        r = lv._ref(rec)
        assert r() is rec
        del rec
        gc.collect()
        assert r() is None, "the recorder was kept alive"
    assert lv._ref(None)() is None
    assert lv._ref(5)() == 5                 # no weakref: strong, as said
    assert 'DOES keep it alive' in lv._ref.__doc__


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block (run_tests.py explains why).
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    ran = skipped = 0
    failed = []
    for fn in fns:
        try:
            fn()
        except _Skip as why:
            skipped += 1
            print(f"skip {fn.__name__}  ({why})")
            continue
        except Exception:
            # A test that blew up still RAN: only a skip is "did not run".
            ran += 1
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
        ran += 1
        print(f"ok  {fn.__name__}")
    tail = f"{ran} of {len(fns)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped)"
    print(f"\n{tail}")
    if not failed:
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
