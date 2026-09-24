#!/usr/bin/env python3
"""Headless tests for the SLDEA Run <-> Webcam-tab interlock (no hardware,
no Tk).

The gap (adversarial review 2026-09-23, on 78315cc): ▶ Run never looked at
the Webcam tab. A stepped sweep started BEFORE a run kept writing the
signal generator, and on the run's own channel it overwrote the Trek
drive. The run loop re-sends its offset only when the commanded kV
changes, so one foreign write could hold the wrong voltage for a whole
landing. What is pinned here:

* Run refuses beside a stepped sweep on its own SG channel, a timed
  capture, a capture that is still stopping, or a camera adjustment; it
  ASKS (Enter = No) beside a sweep on the other channel.
* The check comes before any HV question, before the camera is touched,
  and again at the commit point, after the last dialog.
* The sweep worker checks channel ownership before EVERY write, so a
  sweep started during a LIVE run never lands a write on its channel. The
  timed capture's burst trigger follows the same rule.

Everything below drives the REAL methods -- sldea_run, the Webcam
starters, both capture workers, and the real _sldea_worker where it
matters -- on a stub app, against a fake signal generator that records
which thread wrote what.

Run: .venv/bin/python tests/test_sldea_interlock.py
"""
import contextlib as _contextlib
import os as _os
import queue as _queue
import sys as _sys
import tempfile as _tempfile
import threading as _threading
import time as _time
import types as _types
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import gui  # noqa: E402

G = gui.InstrumentControlGUI
# every question the interlock never asks, answered for the LIVE path with
# no scope connected (the stub has none)
LIVE_OK = {'No current monitoring': True, 'Energize HV?': True}
SWEEP_Q = 'Stepped sweep still running'
BUSY = 'SLDEA — Webcam tab busy'


def _var(value):
    return _types.SimpleNamespace(get=lambda: value)


class _Widget:
    def config(self, **_kw):
        pass


class _FakeSG:
    """BK4055B stand-in. Records every write as (thread name, call,
    channel, args). `on_write` runs after each set_basic_wave: a hook for
    claiming the channel between two sweep levels."""

    def __init__(self):
        self.writes = []
        self.on_write = None
        self._lock = _threading.Lock()

    def _rec(self, call, channel, *args):
        with self._lock:
            self.writes.append((_threading.current_thread().name, call,
                                channel, args))

    def set_basic_wave(self, channel, **params):
        self._rec('set_basic_wave', channel, params)
        if self.on_write is not None:
            self.on_write(channel, params)

    def set_offset(self, channel, offset_v):
        self._rec('set_offset', channel, offset_v)

    def set_output(self, channel, on):
        self._rec('set_output', channel, on)

    def set_load_polarity(self, channel, load=None, polarity=None):
        self._rec('set_load_polarity', channel, load, polarity)

    def burst_trigger(self, channel):
        self._rec('burst_trigger', channel)

    def from_thread(self, fragment):
        return [w for w in self.writes if fragment in w[0]]


class _MB:
    """tkinter.messagebox stand-in: records (kind, title, message, kw) and
    answers questions by title. A question it has no answer for fails the
    test -- an unexpected dialog is a finding, not something to guess."""

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.calls = []

    def askyesno(self, title, message, **kw):
        self.calls.append(('askyesno', title, message, kw))
        if title not in self.answers:
            raise AssertionError(f"unexpected question: {title!r}")
        return self.answers[title]

    def _note(self, kind):
        def show(title, message, **kw):
            self.calls.append((kind, title, message, kw))
        return show

    def __getattr__(self, name):
        if name.startswith('show'):
            return self._note(name)
        raise AttributeError(name)

    def titles(self, kind=None):
        return [c[1] for c in self.calls if kind in (None, c[0])]

    def message(self, title):
        [msg] = [c[2] for c in self.calls if c[1] == title]
        return msg


class _App:
    """Just enough app for sldea_run and the Webcam capture paths: the real
    methods under test, stubs for Tk, the camera and the pre-flight."""
    SLDEA_POLL_S = G.SLDEA_POLL_S
    sldea_run = G.sldea_run
    _sldea_webcam_conflict = G._sldea_webcam_conflict
    _sldea_webcam_gate = G._sldea_webcam_gate
    _sldea_cam_value = G._sldea_cam_value
    _sldea_capture = G._sldea_capture
    cam_toggle_sequence = G.cam_toggle_sequence
    _cam_start_sequence = G._cam_start_sequence
    _cam_start_timed = G._cam_start_timed
    _cam_seq_worker = G._cam_seq_worker
    _cam_timed_worker = G._cam_timed_worker
    # claude/sldea-video-capture (unmerged 2026-09-23) calls these from the
    # paths driven here. Bound when present, so this suite survives that
    # merge as it stands; on main they do not exist and nothing calls them.
    if hasattr(G, '_sldea_video_preflight'):
        _sldea_video_preflight = G._sldea_video_preflight
    if hasattr(G, '_cam_owned_by_sldea'):
        _cam_owned_by_sldea = G._cam_owned_by_sldea

    def __init__(self, tmp, dry=True, sgch=1, real_worker=False):
        self.real_worker = real_worker
        self.worker_done = _threading.Event()
        self.worker_args = self.worker_error = None
        self.lines, self.events = [], []
        self.on_preflight = None
        self.root = _types.SimpleNamespace(after=lambda *a, **k: None)
        self.sg, self.scope, self.cam = _FakeSG(), None, None
        # SLDEA tab
        self._sldea_running = False
        self._sldea_stop = False
        self._sldea_prelog = self._sldea_runlog = None
        self._sldea_loglock = _threading.Lock()
        self.sldea_dryrun = _var(dry)
        self.sldea_vars = {k: _var(v) for k, v in {
            'sgch': str(sgch), 'vch': '2', 'ich': '3', 'diam_mm': '16',
            'electrode': 'CNT', 'conc_ml': '', 'wd_ua': '100', 'wd_s': '3',
            'tel_hz': '2'}.items()}
        for name in ('sldea_autoproc', 'sldea_trek_inv', 'sldea_wd_on',
                     'sldea_tel_on'):
            setattr(self, name, _var(False))
        self.sldea_outdir, self.sldea_runname = _var(tmp), _var('RUN')
        self.sldea_run_btn = self.sldea_abort_btn = _Widget()
        # what the video branch's hooks read (see the class body)
        self.sldea_vid_on = self.sldea_vid_detect = _var(False)
        self._sldea_video_jobs, self._sldea_recorder = [], None
        # Webcam tab
        self._bg_busy = set()
        self.cam_seq_running = False
        self.cam_seq_thread = None
        self.cam_seq_queue = _queue.Queue()
        self._cam_seq_kind = self._cam_seq_ch = None
        self.cam_index_var = _var('0')
        self.cam_sg_ch = _var('1')
        self.cam_sg_param = _var('DC offset (V)')
        self.cam_step_levels = _var('2.5')
        self.cam_step_start = _var('0')
        self.cam_step_stop = _var('1')
        self.cam_step_step = _var('1')
        self.cam_step_dwell = _var('0')
        self.cam_seq_focus = self.cam_tm_focus = _var(False)
        self.cam_dir_var, self.cam_prefix_var = _var(tmp), _var('cap')
        self.cam_tm_trigger = _var('on Start click')
        self.cam_tm_delays = _var('0')
        self.cam_tm_start = _var('0')
        self.cam_tm_interval = _var('1')
        self.cam_tm_count = _var('1')
        self.cam_seq_btn = self.cam_seq_status = _Widget()
        self.cam_tm_btn = self.cam_tm_status = _Widget()

    # --- SLDEA side -----------------------------------------------------
    def _sldea_log(self, msg):
        self.lines.append(str(msg))
        G._sldea_log(self, msg)          # the real prelog -> run.log path

    def _sldea_set_status(self, *a, **k):
        pass

    def _sldea_build_profile(self):
        return _short_profile(), None

    def _sldea_conc_applicable(self, electrode=None):
        return False

    def _sldea_preflight(self, cam_exp, cam_gain):
        self.events.append('preflight')
        if self.on_preflight is not None:
            self.on_preflight()          # "meanwhile, on the Webcam tab..."
        return True

    def _sldea_worker(self, *args, **kw):
        self.worker_args = args
        try:
            if self.real_worker:
                G._sldea_worker(self, *args, **kw)
        except BaseException as e:           # a thread's traceback is lost
            self.worker_error = e
        finally:
            self.worker_done.set()

    def _sldea_finished(self):
        pass

    def _sldea_animate_cursor(self):
        pass

    # --- Webcam side ----------------------------------------------------
    def cam_stop_preview(self):
        self.events.append('cam_stop_preview')

    def _drain_cam_queue(self):
        pass

    def _cam_save_frame(self, *a, **k):
        return None


def _short_profile(**kw):
    from sldea_profile import SldeaProfile
    opts = dict(start_kv=0.0, end_kv=1.0, step_kv=1.0, ramp_s=0.4,
                landing_s=1.2, settle_s=0.2, snap_lead_s=0.2)
    opts.update(kw)
    return SldeaProfile(**opts)


@_contextlib.contextmanager
def _patched(mb):
    """Swap in the messagebox stub, a camera that yields no frames, and the
    Linux gate opened so the LIVE path runs on any OS."""
    saved = (gui.messagebox, gui.INSTRUMENTS_SUPPORTED,
             gui.webcam.resolve_camera, gui.webcam.oneshot_rgb)
    gui.messagebox = mb
    gui.INSTRUMENTS_SUPPORTED = True
    gui.webcam.resolve_camera = lambda idx: {'kind': 'cv2',
                                             'index': int(idx)}
    gui.webcam.oneshot_rgb = lambda spec, count=2: None
    try:
        yield mb
    finally:
        (gui.messagebox, gui.INSTRUMENTS_SUPPORTED,
         gui.webcam.resolve_camera, gui.webcam.oneshot_rgb) = saved


def _busy(app, kind='sweep', ch=1, running=True, alive=True):
    """Leave the app as a Webcam-tab capture does: flag, thread, and what
    the starter recorded. A fresh token each call = a fresh job."""
    app.cam_seq_running = running
    app.cam_seq_thread = _types.SimpleNamespace(is_alive=lambda: alive)
    app._cam_seq_kind = kind
    app._cam_seq_ch = ch if kind == 'sweep' else None
    app._cam_seq_gen = object()


def _drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except _queue.Empty:
            return out


def _assert_refused(app, mb):
    """Nothing the run does happened: no claim, no worker, no SG write, no
    camera touched, and the run.log buffer disarmed."""
    assert not app._sldea_running
    assert getattr(app, '_sldea_live_ch', None) is None
    assert not app.worker_done.is_set()
    assert app.sg.writes == [], app.sg.writes
    assert app._sldea_prelog is None
    assert mb.titles('showerror') == [BUSY], mb.calls


def _wait_for(pred, timeout=5.0):
    end = _time.monotonic() + timeout
    while _time.monotonic() < end:
        if pred():
            return True
        _time.sleep(0.01)
    return pred()


# --------------------------------------------------------------------------
# Run refuses (or asks) while a Webcam-tab job is running
# --------------------------------------------------------------------------

def test_live_run_refuses_beside_a_sweep_on_its_own_channel():
    mb = _MB()                            # any question at all fails
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=False, sgch=1)
        _busy(app, 'sweep', ch=1)
        app.sldea_run()
        _assert_refused(app, mb)
        assert mb.titles() == [BUSY], "refused BEFORE any HV question"
        assert app.events == [], "refused before the camera was touched"
        msg = mb.message(BUSY)
        assert 'SG CH1' in msg and 'whole landing' in msg, msg
        assert 'Webcam tab → Stop sweep' in msg, msg
        assert any(l.startswith('run refused') and 'SG CH1' in l
                   for l in app.lines), app.lines


def test_live_run_asks_about_a_sweep_on_the_other_channel_enter_is_no():
    mb = _MB({SWEEP_Q: False})
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=False, sgch=1)
        _busy(app, 'sweep', ch=2)
        app.sldea_run()
        [(kind, title, msg, kw)] = mb.calls
        assert (kind, title) == ('askyesno', SWEEP_Q)
        assert kw.get('default') == 'no', kw
        assert 'SG CH2' in msg and '(CH1)' in msg and 'NO FRAME' in msg, msg
        assert not app._sldea_running and not app.worker_done.is_set()
        assert app.sg.writes == [] and app._sldea_prelog is None
        assert any('run cancelled' in l for l in app.lines), app.lines


def test_an_allowed_sweep_is_asked_about_once_and_lands_in_run_log():
    """Yes means yes for THAT sweep: the commit-point re-check must not ask
    again, and the choice is recorded where the run's data lives."""
    mb = _MB({SWEEP_Q: True})
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=True, sgch=1, real_worker=True)
        _busy(app, 'sweep', ch=2)
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert mb.titles() == [SWEEP_Q], mb.calls
        with open(_os.path.join(tmp, 'RUN', 'run.log'),
                  encoding='utf-8') as f:
            log = f.read()
        assert 'run-anyway beside a stepped sweep on SG CH2' in log, log


def test_a_timed_capture_refuses_live_and_dry():
    for dry in (False, True):
        mb = _MB()
        with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
            app = _App(tmp, dry=dry, sgch=1)
            _busy(app, 'timed')
            app.sldea_run()
            _assert_refused(app, mb)
            msg = mb.message(BUSY)
            assert 'timed capture' in msg and 'Webcam tab → Stop.' in msg


def test_a_capture_still_stopping_refuses_it_is_judged_by_its_thread():
    """Stop clears the flag at once; the worker still finishes the step it
    was on (a camera grab, or an SG write already under way)."""
    for kind, ch in (('sweep', 1), ('sweep', 2), ('timed', None)):
        mb = _MB()
        with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
            app = _App(tmp, dry=False, sgch=1)
            _busy(app, kind, ch=ch, running=False, alive=True)
            app.sldea_run()
            _assert_refused(app, mb)
            assert 'still stopping' in mb.message(BUSY)


def test_a_finished_worker_is_not_in_the_way():
    # its 'done' can sit undrained for up to 50 ms with the flag still set
    mb = _MB()
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=True, sgch=1)
        _busy(app, 'sweep', ch=1, running=True, alive=False)
        app.sldea_run()
        assert app.worker_done.wait(5) and mb.calls == [], mb.calls


def test_a_camera_adjustment_in_flight_refuses():
    mb = _MB()
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=True, sgch=1)
        app._bg_busy.add('camera-ctrl')
        app.sldea_run()
        _assert_refused(app, mb)
        assert 'Apply & Lock' in mb.message(BUSY)


def test_every_reason_is_listed_in_one_dialog():
    mb = _MB()
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=False, sgch=1)
        _busy(app, 'sweep', ch=1)
        app._bg_busy.add('camera-ctrl')
        app.sldea_run()
        _assert_refused(app, mb)
        msg = mb.message(BUSY)
        assert 'SG CH1' in msg and 'Apply & Lock' in msg, msg
        [line] = [l for l in app.lines if l.startswith('run refused')]
        assert 'SG CH1' in line and 'camera adjustment' in line, line


def test_dry_runs_follow_the_same_channel_rule_in_their_own_words():
    """A DRY run writes no SG channel, but a sweep on the channel it is set
    to drive the Trek with can still energize the Trek."""
    mb = _MB()
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=True, sgch=2)
        _busy(app, 'sweep', ch=2)
        app.sldea_run()
        _assert_refused(app, mb)
        assert 'would not be dry' in mb.message(BUSY)
    mb = _MB({SWEEP_Q: False})
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=True, sgch=2)
        _busy(app, 'sweep', ch=1)
        app.sldea_run()
        msg = mb.message(SWEEP_Q)
        assert 'This DRY run writes no SG channel' in msg, msg
        assert not app._sldea_running


def test_nothing_running_starts_exactly_as_before():
    # unrelated background work never blocks a run
    for dry, questions in ((True, []),
                           (False, ['No current monitoring',
                                    'Energize HV?'])):
        mb = _MB(LIVE_OK)
        with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
            app = _App(tmp, dry=dry, sgch=2)
            app._bg_busy.update({'sg-io', 'connect'})
            app.sldea_run()
            assert app.worker_done.wait(5), app.lines
            assert mb.titles() == questions, mb.calls
            assert app._sldea_running
            assert app._sldea_live_ch == (None if dry else 2)
            assert app.worker_args[3] == 2 and app.worker_args[6] is dry


# --------------------------------------------------------------------------
# The commit-point re-check: the dialogs can take as long as the operator
# likes, so what was clear at the top may not be clear at the end
# --------------------------------------------------------------------------

def test_the_commit_recheck_refuses_a_sweep_started_during_the_dialogs():
    mb = _MB(LIVE_OK)
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=False, sgch=1)
        app.on_preflight = lambda: _busy(app, 'sweep', ch=1)
        app.sldea_run()
        assert 'preflight' in app.events          # it got that far...
        _assert_refused(app, mb)                  # ...and stopped there
        assert mb.titles() == ['No current monitoring', 'Energize HV?',
                               BUSY], mb.calls


def test_the_commit_recheck_asks_again_only_about_a_different_sweep():
    mb = _MB(dict(LIVE_OK, **{SWEEP_Q: True}))
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=False, sgch=1)
        _busy(app, 'sweep', ch=2)
        app.on_preflight = lambda: _busy(app, 'sweep', ch=2)  # a NEW sweep
        app.sldea_run()
        assert mb.titles('askyesno').count(SWEEP_Q) == 2, mb.calls
        assert app.worker_done.wait(5)


# --------------------------------------------------------------------------
# The workers: channel ownership checked before EVERY SG write
# --------------------------------------------------------------------------

def _sweep(app, ch=1, key='OFST', values=(2.0, 3.0, 4.0)):
    """Run the real sweep worker to completion, as its thread would."""
    app.cam_seq_running = True
    app._cam_seq_gen = object()
    app._cam_seq_worker(ch, key, list(values), 0.0, None, '.', 'cap',
                        {'kind': 'cv2', 'index': 0})
    return _drain(app.cam_seq_queue)


def test_the_sweep_writes_nothing_to_a_channel_a_live_run_owns():
    for key in ('OFST', 'AMP'):               # an amplitude sweep as well
        with _tempfile.TemporaryDirectory() as tmp, _patched(_MB()):
            app = _App(tmp)
            app._sldea_live_ch = 1
            events = _sweep(app, ch=1, key=key)
            assert app.sg.writes == [], app.sg.writes
            [(kind, text)] = events
            assert kind == 'error', events
            assert 'SG CH1' in text and 'LIVE SLDEA run' in text, text
            assert 'before writing 2' in text, text


def test_the_sweep_checks_before_every_write_not_only_the_first():
    with _tempfile.TemporaryDirectory() as tmp, _patched(_MB()):
        app = _App(tmp)
        app._sldea_live_ch = None
        # a LIVE run claims CH1 the moment the sweep's first level lands
        app.sg.on_write = lambda ch, params: setattr(app, '_sldea_live_ch',
                                                     1)
        events = _sweep(app, ch=1)
        assert [w[3][0] for w in app.sg.writes] == [{'OFST': 2.0}], \
            app.sg.writes
        assert [e[0] for e in events] == ['step', 'error'], events
        assert 'before writing 3' in events[-1][1]


def test_the_sweep_leaves_a_live_runs_other_channel_alone():
    with _tempfile.TemporaryDirectory() as tmp, _patched(_MB()):
        app = _App(tmp)
        app._sldea_live_ch = 2
        events = _sweep(app, ch=1)
        assert [w[3][0]['OFST'] for w in app.sg.writes] == [2.0, 3.0, 4.0]
        assert events[-1][0] == 'done', events


def test_the_timed_capture_never_fires_a_trigger_on_a_live_channel():
    def timed(app, trigger_ch):
        app.cam_seq_running = True
        app._cam_seq_gen = object()
        app._cam_timed_worker(trigger_ch, [0.0], None, '.', 'cap',
                              {'kind': 'cv2', 'index': 0})
        return _drain(app.cam_seq_queue)

    with _tempfile.TemporaryDirectory() as tmp, _patched(_MB()):
        app = _App(tmp)
        app._sldea_live_ch = 1
        [(kind, text)] = timed(app, 1)
        assert kind == 'error' and 'burst trigger not fired' in text, text
        assert app.sg.writes == []
        # the other channel, and no trigger at all, are untouched by it
        assert timed(app, 2)[-1][0] == 'done'
        assert timed(app, None)[-1][0] == 'done'
        assert [w[1:3] for w in app.sg.writes] == [('burst_trigger', 2)]


def test_the_webcam_starters_record_what_they_started():
    """The interlock reads these, never the widgets: the operator can
    retarget the channel box while the sweep is running."""
    with _tempfile.TemporaryDirectory() as tmp, _patched(_MB()):
        app = _App(tmp)
        app.cam_sg_ch = _var('2')
        app._cam_start_sequence()
        assert (app._cam_seq_kind, app._cam_seq_ch) == ('sweep', 2)
        app.cam_seq_thread.join(5)
        app.cam_sg_ch = _var('1')                # retargeted afterwards
        assert app._cam_seq_ch == 2
        app.cam_seq_running = False              # as the drain would
        app._cam_start_timed()
        assert (app._cam_seq_kind, app._cam_seq_ch) == ('timed', None)
        app.cam_seq_thread.join(5)


# --------------------------------------------------------------------------
# End to end: the real starters and runners on both sides
# --------------------------------------------------------------------------

def test_end_to_end_a_real_sweep_holds_off_a_live_run_until_it_stops():
    mb = _MB(LIVE_OK)
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=False, sgch=1)
        app.cam_step_dwell = _var('30')          # parked mid-dwell
        app._cam_start_sequence()
        assert _wait_for(lambda: app.sg.writes), "sweep never wrote"
        app.sldea_run()
        assert mb.titles() == [BUSY], mb.calls
        assert not app._sldea_running and not app.worker_done.is_set()
        assert getattr(app, '_sldea_live_ch', None) is None
        app.cam_toggle_sequence()                # the real Stop
        app.cam_seq_thread.join(5)
        assert not app.cam_seq_thread.is_alive()
        app.sldea_run()
        assert app.worker_done.wait(5) and app._sldea_live_ch == 1
        # the sweep wrote exactly its one level, all before the run began
        assert [w[1:] for w in app.sg.writes] == [
            ('set_basic_wave', 1, ({'OFST': 2.5},))], app.sg.writes


def test_end_to_end_a_sweep_during_a_live_run_never_writes_its_channel():
    """The worker check on its own, behind every start-time guard: a real
    LIVE run (the real _sldea_worker) owns CH1 while a sweep worker targets
    CH1. The run's drive must be the run's alone, start to finish."""
    mb = _MB(LIVE_OK)
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=False, sgch=1, real_worker=True)
        app.sldea_run()
        assert _wait_for(lambda: ('set_output', 1, (True,)) in
                         [w[1:] for w in app.sg.writes]), app.lines
        app.cam_seq_running = True
        app._cam_seq_gen = object()
        sweep = _threading.Thread(
            target=app._cam_seq_worker, name='sweep-worker',
            args=(1, 'OFST', [2.5, 3.5], 0.0, None, tmp, 'cap',
                  {'kind': 'cv2', 'index': 0}), daemon=True)
        sweep.start()
        sweep.join(5)
        assert app.worker_done.wait(30), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert any(l.startswith('run complete') for l in app.lines), \
            app.lines
        assert app.sg.from_thread('sweep-worker') == [], app.sg.writes
        [(kind, text)] = _drain(app.cam_seq_queue)
        assert kind == 'error' and 'LIVE SLDEA run' in text, text
        # every write came from the run, and it ended zeroed and off
        run = app.sg.from_thread('_sldea_worker')
        assert run == app.sg.writes, app.sg.writes
        assert [w[1:] for w in run[-2:]] == [('set_offset', 1, (0.0,)),
                                             ('set_output', 1, (False,))]


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
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
