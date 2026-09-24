#!/usr/bin/env python3
"""Headless tests for the LIVE-run lock on the monitor scope (no hardware,
no Tk).

A LIVE SLDEA run reads the Trek's V_Out and I_Out monitors off two MSO24
channels (the SLDEA tab's "V_Out scope CH" / "I_Out scope CH"). Its
breakdown watchdog samples I_Out every 0.5 s, telemetry and data.csv record
both, and setup.txt records their vertical setup as read back at the start.
Until 2026-09-24 nothing kept the Oscilloscope tab or a bench-profile load
off those channels mid-run: AC coupling on I_Out, Stop, Single or AutoSet
could blind or mis-scale the watchdog, and it would not know (how Tek
scopes are expected to behave; not bench-verified). The rule the owner
agreed on 2026-09-24, pinned here:

* a LIVE run claims its V_Out and I_Out channels and the settings every
  channel shares. Enable and Apply on those two channels, Stop, Single and
  AutoSet refuse with a loud note and send nothing;
* Apply All Settings -- and so a bench-profile load, which pushes the
  scope through it -- sends the other channels only, with one note naming
  what it held back;
* the other channels, Run, the reads (measurements, waveform capture) and
  Reconnect stay usable -- and, on the REAL driver, reopening the scope
  and the reads send nothing a LIVE run's reads depend on;
* a DRY run claims nothing, like the SG lock; the claim holds through
  ■ Abort and a BREAKDOWN-ABORT, and only _sldea_finished releases it;
* an inventory of the scope calls in the app modules, per function, in
  the spellings the app uses: a new one fails here until someone decides
  whether the lock applies to it.

Everything drives the REAL methods on a Tk-free stub app, against a fake
scope that records every call that changes it and who made each read.
The claim is driven through the real sldea_run and, end to end, the real
run worker; two tests build the real TekMSO24 on a recording session.

Run: .venv/bin/python tests/test_scope_live_lock.py
"""
import ast as _ast
import collections as _collections
import contextlib as _contextlib
import glob as _glob
import os as _os
import sys as _sys
import tempfile as _tempfile
import threading as _threading
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _ROOT)

import gui  # noqa: E402
from instruments import TekMSO24  # noqa: E402

G = gui.InstrumentControlGUI
LOCK = 'Scope in use — LIVE HV run'
READS = 'The run reads CH2 (V_Out) and CH3 (I_Out).'
LIVE_OK = {'Energize HV?': True}  # all a LIVE run asks here, scope on


class _Field:
    """Entry / Combobox / Tk variable stand-in: get and set, and the
    delete + insert pair _set_entry uses."""

    def __init__(self, value=''):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def delete(self, *_a):
        self.value = ''

    def insert(self, _index, text):
        self.value = text


class _Label:
    def __init__(self):
        self.text = None

    def config(self, text=None, **_kw):
        if text is not None:
            self.text = text


class _Root:
    """Tk root stand-in: after() queues its callbacks, and run_pending()
    plays them the way the mainloop would once it gets round to it."""

    def __init__(self):
        self.pending = []
        self._lock = _threading.Lock()

    def after(self, _ms, fn=None, *args):
        if fn is not None:
            with self._lock:
                self.pending.append((fn, args))
        return 'after#'

    def run_pending(self):
        while True:
            with self._lock:
                if not self.pending:
                    return
                fn, args = self.pending.pop(0)
            fn(*args)


class _FakeScope:
    """TekMSO24 stand-in. Records every call that changes the scope as
    (call, args); the signatures follow the real driver's. `ask` never
    answers, so the run's pre-start checks skip, as on a failed query.
    measure_raw records (type, channel, the function that asked) -- the
    run's watchdog reads from _sldea_worker, its snapshots from
    _sldea_capture -- calls `on_read(channel, caller)` first when that is
    set, and returns `volts(channel)`: 0.05 V everywhere by default, which
    is 10 uA on I_Out."""
    idn = 'FAKE,MSO24'

    def __init__(self, volts=None):
        self.volts = volts or (lambda channel: 0.05)
        self.writes = []
        self.reads = []
        self.on_read = None
        self.closed = False

    def _rec(self, call, *args):
        self.writes.append((call, args))

    def set_channel_enable(self, channel, enable=True):
        self._rec('set_channel_enable', channel, enable)

    def set_vertical(self, channel, scale, position=0, coupling='DC'):
        self._rec('set_vertical', channel, scale, position, coupling)

    def set_horizontal(self, scale, position=0):
        self._rec('set_horizontal', scale)

    def set_trigger_edge(self, source='CH1', level=0, slope='RISE'):
        self._rec('set_trigger_edge', source, level, slope)

    def single(self):
        self._rec('single')

    def run(self):
        self._rec('run')

    def stop(self):
        self._rec('stop')

    def autoset(self):
        self._rec('autoset')

    def write(self, command):
        self._rec('write', command)

    def ask(self, command):
        self.reads.append(('ask', command))
        raise IOError('no answer in tests')

    def measure_raw(self, meas_type, channel):
        caller = _sys._getframe(1).f_code.co_name
        if self.on_read is not None:
            self.on_read(channel, caller)
        self.reads.append((meas_type, channel, caller))
        return self.volts(channel), 'ok'

    def get_all_measurements(self, channel):
        self.reads.append(('all', channel))
        return {'mean': self.volts(channel)}

    def get_waveform(self, channel):
        self.reads.append(('waveform', channel))
        return {'t': [0.0], 'v': [0.0], 'dt': 1e-3, 'npts': 1}

    def close(self):
        self.closed = True

    def calls(self):
        return [call for call, _ in self.writes]

    def channels_written(self):
        return {args[0] for call, args in self.writes
                if call in ('set_channel_enable', 'set_vertical')}


class _Session:
    """pyvisa resource stand-in under the REAL TekMSO24: records every
    command it is sent and answers queries from `answers` ('0' otherwise).
    `raw` holds the replies read_raw hands out, in order."""

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.sent, self.raw = [], []
        self.timeout = self.read_termination = self.write_termination = None

    def clear(self):
        self.sent.append('<device clear>')

    def write(self, command):
        self.sent.append(command)

    def query(self, command):
        self.sent.append(command)
        return self.answers.get(command, '0')

    def read_raw(self):
        return self.raw.pop(0) if self.raw else b''

    def close(self):
        self.sent.append('<close>')


class _RM:
    def __init__(self, session):
        self.session = session

    def open_resource(self, _resource):
        return self.session


class _FakeSG:
    """BK4055B stand-in for the LIVE run's own writes."""

    def __init__(self):
        self.writes = []

    def set_load_polarity(self, channel, load=None, polarity=None):
        self.writes.append(('set_load_polarity', channel, load))

    def set_basic_wave(self, channel, **params):
        self.writes.append(('set_basic_wave', channel, params))

    def set_output(self, channel, on):
        self.writes.append(('set_output', channel, on))

    def set_offset(self, channel, offset_v):
        self.writes.append(('set_offset', channel, offset_v))


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

    def notes(self):
        """The messages of the lock notes, in order."""
        return [c[2] for c in self.calls if c[:2] == ('showwarning', LOCK)]


def _scope_widgets():
    """The Oscilloscope tab's four channel forms, as the tab builds them."""
    return {ch: {'enable': _Field(ch == 1), 'vscale': _Field('1.0'),
                 'position': _Field('0'), 'coupling': _Field('DC'),
                 'trigger': _Field(ch == 1)} for ch in range(1, 5)}


class _App:
    """Just enough app for the Oscilloscope tab, a bench-profile load and
    sldea_run: the real methods under test, stubs for Tk, the camera and
    the pre-flight. `_run_bg` runs a job inline and records its busy key,
    so a test reads the outcome rather than racing a thread."""
    SLDEA_POLL_S = G.SLDEA_POLL_S
    _scope_live_roles = G._scope_live_roles
    _scope_live_note = G._scope_live_note
    _scope_live_locked = G._scope_live_locked
    _and_list = staticmethod(G._and_list)
    toggle_channel = G.toggle_channel
    apply_channel_config = G.apply_channel_config
    apply_all_scope_config = G.apply_all_scope_config
    scope_single = G.scope_single
    scope_run = G.scope_run
    scope_stop = G.scope_stop
    scope_autoset = G.scope_autoset
    scope_get_measurements = G.scope_get_measurements
    scope_capture_waveform = G.scope_capture_waveform
    reconnect_scope = G.reconnect_scope
    _reconnect = G._reconnect
    _transport = staticmethod(G._transport)
    _bg_simple = G._bg_simple
    _apply_bench_profile = G._apply_bench_profile
    _set_entry = staticmethod(G._set_entry)
    sldea_run = G.sldea_run
    sldea_abort = G.sldea_abort
    _sldea_finished = G._sldea_finished
    _sldea_check_monitors = G._sldea_check_monitors
    _sldea_scope_readback = G._sldea_scope_readback
    _sldea_cam_value = G._sldea_cam_value
    _sldea_capture = G._sldea_capture
    # Unmerged on 2026-09-24: PR #334's start gate and the video branch's
    # hooks, both called from sldea_run. Bound when present, so this suite
    # survives those merges as it stands; on main nothing calls them.
    if hasattr(G, '_sldea_start_gate'):
        _sldea_start_gate = G._sldea_start_gate
        _sldea_start_conflicts = G._sldea_start_conflicts
        _cam_worker_alive = G._cam_worker_alive
    if hasattr(G, '_sldea_video_preflight'):
        _sldea_video_preflight = G._sldea_video_preflight
    if hasattr(G, '_cam_owned_by_sldea'):
        _cam_owned_by_sldea = G._cam_owned_by_sldea

    def __init__(self, tmp='.', dry=True, live=None, real_worker=False,
                 wd_on=False):
        self.root = _Root()
        self.scope, self.sg = _FakeScope(), _FakeSG()
        self.lcr = self.cam = None
        self.bg, self.lines, self.traces, self.sg_states = [], [], [], []
        self.status_bar, self.scope_status = _Label(), _Label()
        # Oscilloscope tab
        self.channel_widgets = _scope_widgets()
        self.scope_hscale = _Field('0.001')
        self.scope_trig_level = _Field('0')
        self.scope_trig_slope = _Field('RISE')
        self.scope_meas_labels = {
            ch: {k: _Label() for k in ('frequency', 'period', 'mean',
                                       'pkpk', 'rms', 'amplitude')}
            for ch in range(1, 5)}
        # SLDEA tab; `live` = the (V_Out, I_Out) claim of a run in progress
        self._sldea_scope_chs = live
        self._sldea_running = live is not None
        self._sldea_live_ch = 1 if live is not None else None
        self._sldea_stop = False
        self._sldea_prelog = self._sldea_runlog = None
        self._sldea_loglock = _threading.Lock()
        self.sldea_dryrun = _Field(dry)
        self.sldea_vars = {k: _Field(v) for k, v in {
            'sgch': '1', 'vch': '2', 'ich': '3', 'diam_mm': '16',
            'electrode': 'CNT', 'conc_ml': '', 'wd_ua': '100', 'wd_s': '3',
            'tel_hz': '2'}.items()}
        self.sldea_wd_on = _Field(wd_on)
        for name in ('sldea_autoproc', 'sldea_trek_inv', 'sldea_tel_on'):
            setattr(self, name, _Field(False))
        self.sldea_outdir, self.sldea_runname = _Field(tmp), _Field('RUN')
        self.sldea_run_btn, self.sldea_abort_btn = _Label(), _Label()
        self.real_worker = real_worker
        self.worker_done = _threading.Event()
        self.worker_args = self.worker_error = None
        # what PR #334's gate and the video branch's hooks read
        self._bg_busy = set()
        self.cam_seq_running, self.cam_seq_thread = False, None
        self._cam_seq_kind = self._cam_seq_ch = None
        self.sldea_vid_on = self.sldea_vid_detect = _Field(False)
        self._sldea_video_jobs, self._sldea_recorder = [], None

    def _run_bg(self, work, done, busy=None, quiet=False):
        self.bg.append(busy)
        result = error = None
        try:
            result = work()
        except Exception as e:
            error = e
        done(result, error)
        return True

    def _sg_apply_state(self, channels):
        self.sg_states.append(channels)   # the SG's own lock is not in scope

    # --- SLDEA side -----------------------------------------------------
    def _sldea_log(self, msg):
        self.lines.append(str(msg))

    def _sldea_set_status(self, *a, **k):
        pass

    def _sldea_build_profile(self):
        return _short_profile(), None

    def _sldea_conc_applicable(self, electrode=None):
        return False

    def _sldea_preflight(self, cam_exp, cam_gain):
        return True

    def cam_stop_preview(self):
        pass

    def _sldea_animate_cursor(self):
        pass

    def _sldea_worker(self, *args, **kw):
        self.worker_args = args
        try:
            if self.real_worker:
                G._sldea_worker(self, *args, **kw)
        except BaseException as e:           # a thread's traceback is lost
            self.worker_error = e
        finally:
            self.worker_done.set()


def _short_profile(**kw):
    from sldea_profile import SldeaProfile
    opts = dict(start_kv=0.0, end_kv=1.0, step_kv=1.0, ramp_s=0.4,
                landing_s=1.2, settle_s=0.2, snap_lead_s=0.2)
    opts.update(kw)
    return SldeaProfile(**opts)


@_contextlib.contextmanager
def _patched(mb):
    """The messagebox stub, a camera that yields no frames, a waveform
    window that only records, and the Linux gate opened so the LIVE path
    and Reconnect run on any OS."""
    saved = (gui.messagebox, gui.INSTRUMENTS_SUPPORTED,
             gui.webcam.resolve_camera, gui.webcam.oneshot_rgb,
             gui.scope_trace.TraceWindow)
    gui.messagebox = mb
    gui.INSTRUMENTS_SUPPORTED = True
    gui.webcam.resolve_camera = lambda idx: {'kind': 'cv2',
                                             'index': int(idx)}
    gui.webcam.oneshot_rgb = lambda spec, count=2: None
    gui.scope_trace.TraceWindow = \
        lambda app, channel, waveform: app.traces.append(channel)
    try:
        yield mb
    finally:
        (gui.messagebox, gui.INSTRUMENTS_SUPPORTED,
         gui.webcam.resolve_camera, gui.webcam.oneshot_rgb,
         gui.scope_trace.TraceWindow) = saved


def _assert_noted(mb, head):
    """Exactly one dialog: the lock note, opening with `head`."""
    [(kind, title, msg, kw)] = mb.calls
    assert (kind, title) == ('showwarning', LOCK), mb.calls
    assert msg.startswith(head), msg
    assert READS in msg, msg
    assert 'Reconnect stay available' in msg, msg
    assert set(kw) <= {'parent'}, kw


# --------------------------------------------------------------------------
# The lock itself
# --------------------------------------------------------------------------

def test_the_lock_holds_the_monitor_channels_and_the_shared_settings():
    with _patched(_MB()) as mb:
        app = _App(live=(2, 3))
        assert not app._scope_live_locked(1) and not app._scope_live_locked(4)
        assert mb.calls == [], "a free channel is not even mentioned"
        for ch, head in ((2, 'CH2 (V_Out) is locked'),
                         (3, 'CH3 (I_Out) is locked')):
            assert app._scope_live_locked(ch) is True
            _assert_noted(mb, head)
            mb.calls.clear()
        # no channel = a setting every channel shares: always held
        assert app._scope_live_locked(what='AutoSet') is True
        _assert_noted(mb, 'AutoSet is locked while a LIVE SLDEA run is on.')


def test_no_live_claim_locks_nothing():
    # no run, a DRY run, or a run that has finished: nothing is claimed
    with _patched(_MB()) as mb:
        app = _App(live=None)
        assert not any(app._scope_live_locked(ch) for ch in (1, 2, 3, 4))
        assert not app._scope_live_locked(what='AutoSet')
        assert app._scope_live_roles() == {} and mb.calls == []


def test_one_channel_set_for_both_monitors_is_held_once():
    """A run set up with V_Out and I_Out on the same channel holds just
    that one, and says what it is."""
    with _patched(_MB()) as mb:
        app = _App(live=(3, 3))
        assert app._scope_live_roles() == {3: 'V_Out and I_Out'}
        assert not app._scope_live_locked(2)
        assert app._scope_live_locked(3)
        [(_, _, msg, _)] = mb.calls
        assert msg.startswith('CH3 (V_Out and I_Out) is locked'), msg
        assert 'The run reads CH3 (V_Out and I_Out).' in msg, msg
        mb.calls.clear()
        app.apply_all_scope_config()
        assert app.scope.channels_written() == {1, 2, 4}, app.scope.writes
        assert 'sends only CH1, CH2 and CH4' in mb.notes()[0], mb.calls


def test_the_claim_is_released_when_the_run_finishes():
    """_sldea_finished runs on the Tk side once the worker is done; from
    then on the scope is the operator's again."""
    with _patched(_MB()) as mb:
        app = _App(live=(2, 3))
        app.scope_autoset()
        assert app.scope.writes == [] and len(mb.calls) == 1
        app._sldea_finished()
        assert app._sldea_scope_chs is None and not app._sldea_running
        app.scope_autoset()
        app.apply_channel_config(3)
        assert app.scope.calls() == ['autoset', 'set_channel_enable',
                                     'set_vertical'], app.scope.writes
        assert len(mb.calls) == 1, "no second note after the release"


def test_abort_keeps_the_claim_until_the_run_has_finished():
    """■ Abort only asks the worker to stop. Like the SG's, the claim holds
    until _sldea_finished, which runs after the Trek is zeroed and the
    run's files are closed."""
    with _patched(_MB()) as mb:
        app = _App(live=(2, 3))
        app.sldea_abort()
        assert app._sldea_stop and app._sldea_scope_chs == (2, 3)
        app.scope_stop()
        assert app.scope.writes == [] and len(mb.notes()) == 1, mb.calls
        app._sldea_finished()
        app.scope_stop()
        assert app.scope.calls() == ['stop'], app.scope.writes


# --------------------------------------------------------------------------
# Oscilloscope tab: Enable, Apply CHx, Stop, Single, AutoSet -- and what
# stays usable: the free channels, Run, the reads, Reconnect
# --------------------------------------------------------------------------

def test_apply_refuses_a_monitor_channel_and_the_other_channels_still_apply():
    with _patched(_MB()) as mb:
        app = _App(live=(2, 3))
        app.channel_widgets[3]['coupling'].set('AC')   # would blind I_Out
        app.apply_channel_config(3)
        assert app.scope.writes == [] and app.bg == [], app.scope.writes
        _assert_noted(mb, 'CH3 (I_Out) is locked')
        mb.calls.clear()
        # the lock is asked before the fields are: a half-typed field on a
        # held channel gets the lock note, not a Configuration Error
        app.channel_widgets[2]['vscale'].set('')
        app.apply_channel_config(2)
        assert app.scope.writes == [], app.scope.writes
        _assert_noted(mb, 'CH2 (V_Out) is locked')
        mb.calls.clear()
        app.apply_channel_config(4)
        assert app.scope.writes == [
            ('set_channel_enable', (4, False)),
            ('set_vertical', (4, 1.0, 0.0, 'DC'))], app.scope.writes
        assert app.bg == ['scope-io'] and mb.calls == [], mb.calls


def test_enable_refuses_a_monitor_channel_and_puts_its_tick_back():
    """The tick box flips BEFORE its command runs, so a refused click must
    put it back, whichever way it went. CH2-CH4 start unticked, so the
    usual refused click is unticked -> ticked."""
    with _patched(_MB()) as mb:
        app = _App(live=(2, 3))
        for ch, was in ((3, False), (2, True)):
            tick = app.channel_widgets[ch]['enable']
            tick.set(was)
            tick.set(not was)                    # the click...
            app.toggle_channel(ch, tick)         # ...then its command
            assert tick.get() is was, (ch, "the refused click left its tick")
            _assert_noted(mb, f"CH{ch} ({app._scope_live_roles()[ch]}) is "
                              f"locked")
            mb.calls.clear()
        assert app.scope.writes == [] and app.bg == [], app.scope.writes
        free = app.channel_widgets[4]['enable']
        free.set(True)
        app.toggle_channel(4, free)
        assert app.scope.writes == [('set_channel_enable', (4, True))]
        assert free.get() is True and mb.calls == []


def test_stop_single_and_autoset_refuse_and_send_nothing():
    """Stop and Single freeze the record every later read returns, and
    AutoSet rescales everything: each would leave the watchdog reading
    something other than the live I_Out, with nothing marking it."""
    for press, name in (('scope_stop', 'Stop'), ('scope_single', 'Single'),
                        ('scope_autoset', 'AutoSet')):
        with _patched(_MB()) as mb:
            app = _App(live=(2, 3))
            getattr(app, press)()
            assert app.scope.writes == [] and app.bg == [], (press,
                                                              app.scope.writes)
            assert app.status_bar.text is None, (press, app.status_bar.text)
            _assert_noted(mb, f'{name} is locked while a LIVE SLDEA run is '
                              f'on.')


def test_run_and_the_reads_stay_usable_during_a_live_run():
    """Run can only restart acquisition, which the run's reads need; Get
    Measurements and Capture Waveform read under the instrument lock like
    the run does, and change no setting."""
    with _patched(_MB()) as mb:
        app = _App(live=(2, 3))
        app.scope_run()
        assert app.scope.writes == [('run', ())], app.scope.writes
        app.scope_get_measurements(3)
        app.scope_capture_waveform(3)
        assert app.scope.reads == [('all', 3), ('waveform', 3)]
        assert app.traces == [3] and mb.calls == [], mb.calls
        assert app.bg == ['scope-io'] * 3, app.bg


def test_reconnect_stays_usable_during_a_live_run():
    """The owner's decision of 2026-09-24: reopening the scope changes no
    vertical, timebase or trigger setting, and it is how monitoring comes
    back after a link drop. Unlike the SG, whose Reconnect is refused."""
    opened = []

    class _Reopened(_FakeScope):
        def __init__(self):
            super().__init__()
            opened.append(self)

    saved = gui.TekMSO24
    gui.TekMSO24 = _Reopened
    try:
        with _patched(_MB()) as mb:
            app = _App(live=(2, 3))
            old = app.scope
            app.reconnect_scope()
            assert old.closed and [app.scope] == opened, (old.closed, opened)
            assert app.bg == ['connect'] and mb.calls == [], mb.calls
            assert app.scope_status.text.startswith('Connected'), \
                app.scope_status.text
            assert old.writes == [] and app.scope.writes == []
    finally:
        gui.TekMSO24 = saved


def test_reopening_the_scope_sends_no_setting_a_live_run_reads_through():
    """The premise of the Reconnect decision, pinned on the REAL driver:
    opening a TekMSO24 sends a device clear, *IDN? and the waveform-
    transfer format, and nothing else. A new command here -- a *RST, an
    ACQUIRE, a channel or trigger setting -- fails this test: re-check
    whether Reconnect may stay usable during a LIVE run first."""
    s = _Session({'*IDN?': 'TEKTRONIX,MSO24,FAKE,1.0'})
    TekMSO24(resource='USB0::FAKE::INSTR', rm=_RM(s))
    assert s.sent == ['<device clear>', '*IDN?', 'DATA:ENCDG RIBINARY',
                      'DATA:WIDTH 2'], s.sent


def test_the_reads_change_only_the_measurement_and_data_source():
    """What 'probe' means in SCOPE_DRIVER, pinned on the REAL driver: a
    measurement programs the scope's one MEASUREMENT:IMMED slot and a
    waveform capture its DATA source, and nothing else. That is why Get
    Measurements, Capture Waveform and Data Logging stay usable during a
    LIVE run: the run's measure_raw re-programs the slot on every read."""
    s = _Session({'MEASUREMENT:IMMED:VALUE?': '0.05', 'WFMPRE:NR_PT?': '2',
                  'WFMPRE:XINCR?': '0.001'})
    scope = TekMSO24(resource='USB0::FAKE::INSTR', rm=_RM(s))
    del s.sent[:]
    assert scope.measure_raw('MEAN', 3) == (0.05, 'ok')
    assert s.sent == ['MEASUREMENT:IMMED:TYPE MEAN',
                      'MEASUREMENT:IMMED:SOURCE CH3',
                      'MEASUREMENT:IMMED:VALUE?'], s.sent
    del s.sent[:]
    scope.get_all_measurements(3)
    assert len(s.sent) == 18 and all(
        c.startswith('MEASUREMENT:IMMED:') for c in s.sent), s.sent
    del s.sent[:]
    s.raw = [b'#14\x00\x01\x00\x02\n']           # two int16 samples
    assert scope.get_waveform(3)['npts'] == 2
    assert s.sent[0] == 'DATA:SOURCE CH3' and all(
        c.startswith(('DATA:SOURCE CH3', 'WFMPRE:', 'CURVE?'))
        for c in s.sent), s.sent


# --------------------------------------------------------------------------
# Apply All Settings, and a bench-profile load through it
# --------------------------------------------------------------------------

def test_apply_all_sends_only_the_free_channels_and_names_what_it_held_back():
    with _patched(_MB()) as mb:
        app = _App(live=(2, 3))
        app.scope_hscale.set('10')               # a 100 s MEAN window
        app.apply_all_scope_config()
        assert app.scope.writes == [
            ('set_channel_enable', (1, True)),
            ('set_vertical', (1, 1.0, 0.0, 'DC')),
            ('set_channel_enable', (4, False)),
            ('set_vertical', (4, 1.0, 0.0, 'DC'))], app.scope.writes
        _assert_noted(mb, 'Apply All Settings sends only CH1 and CH4 while a '
                          'LIVE SLDEA run is on. CH2 (V_Out), CH3 (I_Out), '
                          'the timebase and the trigger are held back.')
        assert app.status_bar.text == (
            'CH1 and CH4 applied; CH2, CH3, the timebase and the trigger '
            'held back for the LIVE SLDEA run'), app.status_bar.text


def test_apply_all_validates_only_what_it_sends():
    with _patched(_MB()) as mb:
        app = _App(live=(2, 3))
        # half-typed fields the run holds back cannot block the rest...
        app.channel_widgets[3]['vscale'].set('')
        app.scope_hscale.set('fast')
        app.apply_all_scope_config()
        assert app.scope.channels_written() == {1, 4}, app.scope.writes
        assert mb.titles() == [LOCK], mb.calls
    with _patched(_MB()) as mb:
        app = _App(live=(2, 3))
        # ...but a bad one it would send still stops everything, and the
        # lock note never shows for an apply that sends nothing
        app.channel_widgets[4]['vscale'].set('')
        app.apply_all_scope_config()
        assert app.scope.writes == [] and app.bg == [], app.scope.writes
        assert mb.titles() == ['Configuration Error'], mb.calls


def test_apply_all_with_no_live_run_is_unchanged():
    with _patched(_MB()) as mb:
        app = _App(live=None)
        app.apply_all_scope_config()
        assert app.scope.channels_written() == {1, 2, 3, 4}
        assert app.scope.writes[-2:] == [
            ('set_horizontal', (0.001,)),
            ('set_trigger_edge', ('CH1', 0.0, 'RISE'))], app.scope.writes
        assert mb.calls == [], mb.calls
        assert app.status_bar.text == \
            'All settings applied. Trigger: CH1 @ 0.0V', app.status_bar.text


def test_a_bench_profile_mid_run_fills_the_fields_but_sends_only_free_ones():
    """The brief's own example: a profile that puts I_Out on AC coupling.
    Its values land in every field -- to send after the run -- but only
    the free channels reach the scope, and the profile's SG part still goes
    to the SG path (whose own LIVE lock decides there)."""
    chans = {str(ch): {'enable': True, 'vscale': '0.5', 'position': '1',
                       'coupling': 'AC', 'trigger': ch == 3}
             for ch in range(1, 5)}
    profile = {'version': 1,
               'scope': {'channels': chans, 'hscale': '10',
                         'trig_level': '2', 'trig_slope': 'FALL'},
               'siggen': {'1': {'waveform': 'DC'}}}
    with _patched(_MB()) as mb:
        app = _App(live=(2, 3))
        app._apply_bench_profile(profile)
        w = app.channel_widgets
        assert (w[3]['coupling'].get(), w[3]['vscale'].get(),
                w[3]['trigger'].get()) == ('AC', '0.5', True)
        assert (app.scope_hscale.get(), app.scope_trig_slope.get()) == \
            ('10', 'FALL')
        assert app.scope.writes == [
            ('set_channel_enable', (1, True)),
            ('set_vertical', (1, 0.5, 1.0, 'AC')),
            ('set_channel_enable', (4, True)),
            ('set_vertical', (4, 0.5, 1.0, 'AC'))], app.scope.writes
        assert mb.titles() == [LOCK], mb.calls
        assert 'values stay in the fields' in mb.notes()[0]
        assert app.sg_states == [profile['siggen']], app.sg_states


# --------------------------------------------------------------------------
# The claim, made by the real sldea_run
# --------------------------------------------------------------------------

def test_a_live_run_claims_its_monitor_channels_and_a_dry_run_none():
    for dry, questions, claim in ((False, list(LIVE_OK), (2, 3)),
                                  (True, [], None)):
        mb = _MB(LIVE_OK)
        with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
            app = _App(tmp, dry=dry)
            app.sldea_run()
            assert app.worker_done.wait(5), app.lines
            assert mb.titles() == questions, mb.calls
            assert app._sldea_running
            assert app._sldea_scope_chs == claim, app._sldea_scope_chs
            # the run's channels travel to the worker as the same pair
            assert app.worker_args[4:7] == (2, 3, dry), app.worker_args
            app.scope_autoset()                  # held only by the LIVE one
            assert (app.scope.calls() == []) is (not dry), app.scope.writes


def test_a_live_run_with_no_scope_still_claims_its_channels():
    """Started without a scope (the operator said yes to 'No current
    monitoring'), a LIVE run still claims: a scope connected mid-run is
    read at every snapshot, so it gets the same protection."""
    mb = _MB({'No current monitoring': True, 'Energize HV?': True})
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=False)
        app.scope = None
        app.sldea_run()
        assert app.worker_done.wait(5), app.lines
        assert mb.titles() == ['No current monitoring', 'Energize HV?']
        assert app._sldea_scope_chs == (2, 3)
        app.scope = _FakeScope()                 # Reconnect, mid-run
        app.scope_autoset()
        app.apply_channel_config(3)
        assert app.scope.writes == [] and len(mb.notes()) == 2, mb.calls


def test_a_live_run_cancelled_before_the_commit_point_claims_nothing():
    """The claim is made where the SG's is, after the last question: a run
    the operator backs out of leaves the scope as it found it."""
    for where in ('Energize HV?', 'camera pre-flight'):
        mb = _MB({'Energize HV?': where != 'Energize HV?'})
        with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
            app = _App(tmp, dry=False)
            if where == 'camera pre-flight':
                app._sldea_preflight = lambda cam_exp, cam_gain: False
            app.sldea_run()
            assert not app._sldea_running and app.worker_args is None
            assert app._sldea_scope_chs is None, where
            app.scope_autoset()
            assert app.scope.calls() == ['autoset'], (where, app.scope.writes)
            assert mb.titles() == ['Energize HV?'], (where, mb.calls)


def test_the_claim_follows_the_channels_the_run_started_with():
    """Not the SLDEA tab's boxes, which stay editable during a run: the
    worker reads what it was started with, so that is what stays held."""
    mb = _MB(LIVE_OK)
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=False)
        app.sldea_run()
        assert app.worker_done.wait(5), app.lines
        app.sldea_vars['ich'].set('4')           # retargeted mid-run
        mb.calls.clear()
        app.apply_channel_config(4)
        assert app.scope.channels_written() == {4} and mb.calls == []
        app.apply_channel_config(3)
        assert app.scope.channels_written() == {4}, app.scope.writes
        assert mb.titles() == [LOCK], mb.calls


def _ramping(app):
    return any(w[0] == 'set_offset' and w[2] > 0 for w in app.sg.writes)


def test_end_to_end_the_claim_holds_while_the_run_reads_the_scope():
    """A real LIVE run with its watchdog armed. At the watchdog's first
    I_Out read after the ramp has started, every locked control is
    pressed: none of them reaches the scope, the watchdog keeps reading
    I_Out, and the scope is free again only once the run has finished on
    the Tk side."""
    mb = _MB(LIVE_OK)
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=False, real_worker=True, wd_on=True)
        app._sldea_build_profile = lambda: (_short_profile(landing_s=2.0),
                                            None)
        pressed = []

        def meddle(channel, caller):
            if (channel == 3 and caller == '_sldea_worker' and _ramping(app)
                    and not pressed):
                pressed.append(len(app.scope.reads))
                app.scope_autoset()
                app.scope_stop()
                app.scope_single()
                app.toggle_channel(3, _Field(False))
                app.apply_channel_config(2)
                app.apply_all_scope_config()
        app.scope.on_read = meddle
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert any(l.startswith('run complete') for l in app.lines), \
            app.lines
        assert not app._sldea_bd_tripped, app.lines
        assert pressed, "the watchdog never read I_Out while ramping"
        # six refusals; Apply All's note is the one that also sends
        assert len(mb.notes()) == 6, mb.calls
        assert app.scope.channels_written() == {1, 4}, app.scope.writes
        assert not {'autoset', 'stop', 'single', 'set_horizontal',
                    'set_trigger_edge'} & set(app.scope.calls())
        # the WATCHDOG kept reading I_Out after the presses -- not just the
        # snapshots, which read it too
        later = [r for r in app.scope.reads[pressed[0]:]
                 if r == ('MEAN', 3, '_sldea_worker')]
        assert len(later) >= 2, app.scope.reads
        # held until _sldea_finished runs on the Tk side
        assert app._sldea_scope_chs == (2, 3)
        app.root.run_pending()
        assert app._sldea_scope_chs is None and not app._sldea_running
        app.scope_autoset()
        assert app.scope.calls()[-1] == 'autoset', app.scope.writes


def test_end_to_end_a_breakdown_trip_holds_the_claim_until_the_end():
    """The watchdog trips (120 uA once the ramp starts, 1 s confirm): the
    breakdown frame's own reads happen under the claim, and it is released
    by _sldea_finished like any other ending, not before."""
    mb = _MB(LIVE_OK)
    with _tempfile.TemporaryDirectory() as tmp, _patched(mb):
        app = _App(tmp, dry=False, real_worker=True, wd_on=True)
        app.sldea_vars['wd_s'].set('1')
        app._sldea_build_profile = lambda: (_short_profile(landing_s=6.0),
                                            None)
        app.scope.volts = lambda ch: 0.6 if ch == 3 and _ramping(app) \
            else 0.0
        tried = []

        def at_the_frame(channel, caller):
            if caller == '_sldea_capture' and app._sldea_bd_tripped \
                    and not tried:
                tried.append(channel)
                app.scope_autoset()
        app.scope.on_read = at_the_frame
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        assert app._sldea_bd_tripped, app.lines
        assert any(l.startswith('run BREAKDOWN-ABORT') for l in app.lines), \
            app.lines
        assert tried and app.scope.writes == [], app.scope.writes
        assert len(mb.notes()) == 1, mb.calls
        assert app._sldea_scope_chs == (2, 3)
        app.root.run_pending()
        assert app._sldea_scope_chs is None
        app.scope_autoset()
        assert app.scope.calls() == ['autoset'], app.scope.writes


# --------------------------------------------------------------------------
# Inventory: every scope call in the app is one somebody has looked at
# --------------------------------------------------------------------------

# Every public method of the scope driver, by what it does to the scope. A
# new driver method fails the suite until it is classified here.
SCOPE_DRIVER = {
    # change the setup or the acquisition
    'autoset': 'write', 'reset': 'write', 'run': 'write', 'single': 'write',
    'stop': 'write', 'set_channel_enable': 'write', 'set_vertical': 'write',
    'set_horizontal': 'write', 'set_trigger_edge': 'write',
    'write': 'write', 'write_raw': 'write', 'write_raw_oneshot': 'write',
    # program the scope's ONE shared measurement / data source, then read it
    # back, all under the instrument lock -- the run's own reads do this too
    'measure': 'probe', 'measure_raw': 'probe',
    'get_all_measurements': 'probe', 'get_waveform': 'probe',
    # end the session: hands the front panel back / closes the link
    'close': 'session', 'go_local': 'session',
    # read only -- though ask()/query() send whatever they are given
    'ask': 'read', 'query': 'read', 'read': 'read', 'read_raw': 'read',
}
SCOPE_CALLS = frozenset(n for n, kind in SCOPE_DRIVER.items()
                        if kind in ('write', 'probe', 'session'))

# Every function in the app modules that calls the scope's writes, probes
# or session calls: its kind, why, and the calls it makes (method ->
# count). The scan below must find exactly this. A call in a function not
# listed, or a new call in one that is, fails the suite: decide whether a
# LIVE run's scope lock applies to it, guard it and test it above, then
# update this table.
# 'locked' must ask _scope_live_locked in a top-level `if ...: return`
# before the statement holding its first call; 'partial' must read
# _scope_live_roles first -- both checked below, not taken on trust.
SCOPE_USERS = {
    'gui.InstrumentControlGUI._sldea_check_monitors': (
        'owner', "the run's own pre-start rescale, answered in its Scope "
                 "monitor setup dialog before the claim", {'write': 6}),
    'gui.InstrumentControlGUI._sldea_worker': (
        'owner', 'the run: watchdog baseline, watchdog and telemetry',
        {'measure_raw': 3}),
    'gui.InstrumentControlGUI._sldea_capture': (
        'owner', 'the run: V_Out and I_Out at every snapshot',
        {'measure_raw': 2}),
    'gui.InstrumentControlGUI.toggle_channel': (
        'locked', 'Enable Channel', {'set_channel_enable': 1}),
    'gui.InstrumentControlGUI.apply_channel_config': (
        'locked', 'Apply CHx Config',
        {'set_channel_enable': 1, 'set_vertical': 1}),
    'gui.InstrumentControlGUI.scope_single': (
        'locked', 'Single', {'single': 1}),
    'gui.InstrumentControlGUI.scope_stop': ('locked', 'Stop', {'stop': 1}),
    'gui.InstrumentControlGUI.scope_autoset': (
        'locked', 'AutoSet', {'autoset': 1}),
    'gui.InstrumentControlGUI.apply_all_scope_config': (
        'partial', 'Apply All Settings, and every bench-profile load '
                   'through it: sends only the channels the run does not '
                   'read', {'set_channel_enable': 1, 'set_vertical': 1,
                            'set_horizontal': 1, 'set_trigger_edge': 1}),
    'gui.InstrumentControlGUI.scope_run': (
        'free', 'Run: it can only restart acquisition, which the run '
                'needs (decision 2026-09-24)', {'run': 1}),
    'gui.InstrumentControlGUI.scope_get_measurements': (
        'read', 'Get CHx Measurements', {'get_all_measurements': 1}),
    'gui.InstrumentControlGUI.scope_capture_waveform': (
        'read', 'Capture CHx Waveform', {'get_waveform': 1}),
    'gui.InstrumentControlGUI.logging_loop': (
        'read', 'the Data Logging tab', {'get_all_measurements': 1}),
}


def _is_scope_handle(node):
    """`scope`, `self.scope`, `app.scope`, `self.app.scope`."""
    return ((isinstance(node, _ast.Name) and node.id == 'scope')
            or (isinstance(node, _ast.Attribute) and node.attr == 'scope'))


def _scope_calls(node):
    """The scope writes, probes and session calls under `node`, as method
    names in source order: a listed method named on a scope handle (called
    or not -- a callback counts) or on the TekMSO24 class, getattr(<handle>,
    '<listed method>'), and any use of the raw VISA handle (<handle>.inst,
    getattr'd or not, which can send anything). A tripwire for the
    spellings the app uses, not a proof. Not seen: an alias under another
    name (the shutdown loop's `inst`, Reconnect's `old`), type(<handle>),
    a getattr on a computed name, a command smuggled through ask() or
    query(), and anything inside the driver itself."""
    found = []
    watched = SCOPE_CALLS | {'inst'}
    for n in _ast.walk(node):
        if isinstance(n, _ast.Attribute) and n.attr in watched and (
                _is_scope_handle(n.value)
                or (isinstance(n.value, _ast.Name)
                    and n.value.id == 'TekMSO24')):
            found.append((n.lineno, n.col_offset, n.attr))
        elif (isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
              and n.func.id == 'getattr' and len(n.args) >= 2
              and _is_scope_handle(n.args[0])
              and isinstance(n.args[1], _ast.Constant)
              and n.args[1].value in watched):
            found.append((n.lineno, n.col_offset, n.args[1].value))
    return [name for _, _, name in sorted(found)]


def _scope_call_sites(modules):
    """({'module.Class.method': Counter(call -> count)}, {same: its def})
    for every scope call in `modules` ({name: source}), charged to the
    outermost def around it: a worker closure or a lambda counts as its
    method's. A call outside any def is charged to its module or class."""
    counts, defs = {}, {}

    def visit(body, prefix):
        for stmt in body:
            if isinstance(stmt, _ast.ClassDef):
                visit(stmt.body, f"{prefix}.{stmt.name}")
                continue
            owner = prefix
            if isinstance(stmt, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                owner = f"{prefix}.{stmt.name}"
                defs[owner] = stmt
            calls = _scope_calls(stmt)
            if calls:
                counts.setdefault(owner,
                                  _collections.Counter()).update(calls)

    for name, source in modules.items():
        visit(_ast.parse(source, name).body, name)
    return counts, {k: v for k, v in defs.items() if k in counts}


def _calls_method(node, method):
    return any(isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)
               and n.func.attr == method for n in _ast.walk(node))


def _asks_the_lock_first(fn):
    """True when `fn` has a top-level `if <x>._scope_live_locked(...): ...
    return` BEFORE the first top-level statement that holds a scope call.
    A check nested in a branch, one that does not return, or one placed
    after the call does not count."""
    for stmt in fn.body:
        if (isinstance(stmt, _ast.If) and isinstance(stmt.test, _ast.Call)
                and isinstance(stmt.test.func, _ast.Attribute)
                and stmt.test.func.attr == '_scope_live_locked'
                and isinstance(stmt.body[-1], _ast.Return)):
            return True
        if _scope_calls(stmt):
            return False
    return False


def _reads_the_claim_first(fn):
    """True when a top-level statement reading _scope_live_roles() comes
    before the first top-level statement that holds a scope call."""
    for stmt in fn.body:
        if _scope_calls(stmt):
            return False
        if _calls_method(stmt, '_scope_live_roles'):
            return True
    return False


def _app_modules():
    """Every module at the repo root except the driver itself."""
    out = {}
    for path in sorted(_glob.glob(_os.path.join(_ROOT, '*.py'))):
        name = _os.path.basename(path)[:-3]
        if name != 'instruments':
            with open(path, encoding='utf-8') as f:
                out[name] = f.read()
    return out


def test_every_scope_driver_method_is_classified():
    public = {n for n in dir(TekMSO24)
              if not n.startswith('_') and callable(getattr(TekMSO24, n))}
    assert public == set(SCOPE_DRIVER), (
        f"unclassified driver methods: {sorted(public - set(SCOPE_DRIVER))}"
        f"; gone from the driver: {sorted(set(SCOPE_DRIVER) - public)}. "
        f"Does a new one change the scope? Classify it in SCOPE_DRIVER.")


def test_every_scope_call_in_the_app_is_accounted_for():
    counts, _ = _scope_call_sites(_app_modules())
    found = {k: dict(v) for k, v in counts.items()}
    listed = {k: calls for k, (_, _, calls) in SCOPE_USERS.items()}
    new = {k: v for k, v in found.items() if k not in listed}
    assert not new, (
        f"scope calls in unlisted functions: {new}. A LIVE SLDEA run reads "
        f"its V_Out / I_Out channels -- may this path change them, or the "
        f"timebase, trigger or acquisition? Guard it and test it above, "
        f"then list it in SCOPE_USERS.")
    gone = set(listed) - set(found)
    assert not gone, (
        f"listed in SCOPE_USERS but no longer calling the scope: {gone} -- "
        f"moved or renamed? Re-check the guard where the call went.")
    changed = {k: {'found': found[k], 'listed': c}
               for k, c in listed.items() if k in found and found[k] != c}
    assert not changed, (
        f"the scope calls changed in: {changed}. A new call in a listed "
        f"function is still a new call: check it against the LIVE lock, "
        f"then update SCOPE_USERS.")


def test_every_locked_writer_asks_the_lock_before_its_first_write():
    _, defs = _scope_call_sites(_app_modules())
    for name, (kind, _, _) in SCOPE_USERS.items():
        if kind == 'locked':
            assert name in defs and _asks_the_lock_first(defs[name]), (
                f"{name} is listed as locked but does not ask "
                f"_scope_live_locked in a top-level `if ...: return` before "
                f"its first scope call")
        elif kind == 'partial':
            assert name in defs and _reads_the_claim_first(defs[name]), (
                f"{name} is listed as partial but does not read "
                f"_scope_live_roles before its first scope call")


def test_the_inventory_sees_the_spellings_it_claims():
    """Pin the scan on a module whose answer is known: every spelling
    `_scope_calls` claims is caught, counted and charged to the right def
    -- a nested class and a module-level function included -- a read is
    not a write, another instrument's method of the same name is not the
    scope's, a dict called `scope` is not the scope, and an alias or
    type(<handle>) is the stated blind spot."""
    src = ("class A:\n"
           "    def a(self):\n"
           "        self.scope.set_vertical(3, 1.0, coupling='AC')\n"
           "    def b(self, app):\n"
           "        app.scope.stop()\n"
           "        app.scope.stop()\n"
           "    def c(self):\n"
           "        run = lambda: self.scope.autoset()\n"
           "    def d(self):\n"
           "        self.sg.set_output(1, False)\n"
           "        self.scope.ask('CH3:SCALE?')\n"
           "    class B:\n"
           "        def e(self):\n"
           "            def work():\n"
           "                self.app.scope.set_horizontal(10)\n"
           "    def g(self):\n"
           "        return self._run_bg(self.scope.autoset, None)\n"
           "    def h(self):\n"
           "        getattr(self.scope, 'single')()\n"
           "    def i(self):\n"
           "        self.scope.inst.write('CH3:COUPLING AC')\n"
           "    def j(self, p):\n"
           "        scope = p.get('scope') or {}\n"
           "        return scope.get('hscale')\n"
           "    def k(self):\n"
           "        dso = self.scope\n"
           "        dso.stop()\n"
           "        type(self.scope).autoset(self.scope)\n"
           "    def m(self):\n"
           "        self.scope.close()\n"
           "        getattr(self.scope, 'inst').write('*RST')\n"
           "        TekMSO24.stop(self.scope)\n"
           "def f(scope):\n"
           "    scope.write('ACQUIRE:STATE STOP')\n")
    counts, _ = _scope_call_sites({'m': src})
    assert {k: dict(v) for k, v in counts.items()} == {
        'm.A.a': {'set_vertical': 1}, 'm.A.b': {'stop': 2},
        'm.A.c': {'autoset': 1}, 'm.A.B.e': {'set_horizontal': 1},
        'm.A.g': {'autoset': 1}, 'm.A.h': {'single': 1},
        'm.A.i': {'inst': 1},
        'm.A.m': {'close': 1, 'inst': 1, 'stop': 1},
        'm.f': {'write': 1}}, counts


def test_the_lock_checks_must_come_first_and_must_return():
    src = ("class C:\n"
           "    def ok(self):\n"
           "        '''doc'''\n"
           "        if not self.scope:\n"
           "            return\n"
           "        on = self.v.get()\n"
           "        if self._scope_live_locked(3):\n"
           "            self.v.set(not on)\n"
           "            return\n"
           "        self._bg(lambda: self.scope.set_channel_enable(3, on))\n"
           "    def late(self):\n"
           "        self.scope.stop()\n"
           "        if self._scope_live_locked(what='Stop'):\n"
           "            return\n"
           "    def nested(self, ch):\n"
           "        if ch:\n"
           "            if self._scope_live_locked(ch):\n"
           "                return\n"
           "        self.scope.stop()\n"
           "    def no_return(self):\n"
           "        if self._scope_live_locked(what='Stop'):\n"
           "            pass\n"
           "        self.scope.stop()\n"
           "    def missing(self):\n"
           "        self.scope.stop()\n"
           "    def partial(self):\n"
           "        held = self._scope_live_roles()\n"
           "        def work():\n"
           "            self.scope.set_horizontal(1)\n"
           "    def partial_late(self):\n"
           "        self.scope.set_horizontal(1)\n"
           "        held = self._scope_live_roles()\n")
    _, defs = _scope_call_sites({'m': src})
    verdict = {k.rsplit('.', 1)[1]: (_asks_the_lock_first(v),
                                     _reads_the_claim_first(v))
               for k, v in defs.items()}
    assert verdict == {'ok': (True, False), 'late': (False, False),
                       'nested': (False, False), 'no_return': (False, False),
                       'missing': (False, False), 'partial': (False, True),
                       'partial_late': (False, False)}, verdict


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
