#!/usr/bin/env python3
"""Headless tests for the Signal Gen tab's stepped sweep, #65 (no hardware,
no Tk).

The sweep steps one SG channel through a frequency axis x an amplitude
axis. Through the Trek that channel is 1 V = 1 kV at the DEA, so what is
pinned here is mostly about when the channel is energized and who else may
write it:

* the worker's I/O, in order: a drain of stale replies, OFF, load and
  polarity, burst off, the waveform (and duty for SQUARE), point 1; then
  point 1's read-back with the output still OFF, and ON only if it
  matched (its CSV row after the ON); each later point exactly
  sweep_plan.level_writes(prev, point) and its read-back; then OFF, and
  an OUTP? that must read OFF. Every write is on the sweep's channel,
  every read checks the echo, and each read is drained and asked under
  one hold of the SG's I/O lock;
* the point-1 gate: a point 1 that reads back wrong (its row is kept,
  marked no, and no last point is named), or a read that raises or
  answers for another query, never gets the output switched ON, and Stop
  or a LIVE claim between that read-back and ON does not either;
* the band guard: a read-back whose trough or peak leaves the volts the
  question approved by more than 10 mV ends the sweep with OFF; a
  mismatch inside them, or a read-back with no usable band, is counted;
* the set-up, ON and every point's writes are made holding the SG's I/O
  lock, and a window close that took that lock first leaves the worker
  doing nothing at all;
* the channel is switched OFF, and the OFF read back, however the sweep
  ends: it runs out, Stop, a write that raises (the last event then says
  the point was mixed and names no last point), a read-back that raises
  or answers for another query; and on a window close the OFF is sent
  with no drain or read after it;
* a LIVE SLDEA run claiming the channel mid-sweep stops every write, the
  output-off included;
* the last event: an OFF the box does not read back as OFF (it reads ON,
  the read fails, the OFF fails) raises exactly one NOT SWITCHED OFF
  alarm, forces the Output button ON, comes before anything that can
  fail, and is never followed by a read that could turn the button back;
  a confirmed OFF turns the button OFF; the panel is left holding the
  last point written in full, then the box is read back into it (drained
  and echo-checked under the lock), waiting for a busy Signal Gen tab
  and saying so when it cannot;
* the CSV: the header, and one row per point read back, with what was
  asked, its trough and peak, what the box echoed, and whether it matched;
* _sg_sweep_locked, and every other writer of the channel refused while
  the sweep owns it (Apply, Fire, the Waveform Editor's upload, Reconnect,
  the Webcam tab's stepped sweep and timed-capture trigger), the other
  channel still usable, and the channel's Output button meaning Stop;
* Start Sweep's refusals (no SG, a sweep already running, the LIVE lock,
  the channel a DRY run is set to, a Webcam stepped sweep on the channel,
  a Signal Gen command in flight, a load other than High-Z, a polarity
  other than NOR, a point beyond +/-10 V, more points than the cap, bad
  fields), its one confirmation (default No) and the re-check after it,
  what a start hands the worker, and the claim given back when the start
  fails;
* the running sweep's inputs locked (the Range/List radios and the 0 V to
  Vpp box included) and given back;
* _sg_sweep_blocks, which holds off Restart now and Update Software.

Everything drives the REAL methods of gui.InstrumentControlGUI on a
Tk-free stub app, against a fake signal generator that records every write
and whether the SG's I/O lock was held for it, and checks echoes with the
real BK4055B._check_echo. The worker runs in the test's thread, with a stub
_interruptible_sleep whose hook (or the fake's read hook) is how Stop, a
window close or a LIVE claim arrives mid-sweep.

How a LIVE run is refused beside the sweep is pinned in
tests/test_sldea_interlock.py, Restart and Update in
tests/test_update_restart_guard.py, the echo check itself in
tests/test_bk4055b_parse.py, and the SG write inventory (which lists the
sweep worker) in tests/test_sg_live_lock.py.

Run: .venv/bin/python tests/test_sg_sweep.py
"""
import contextlib as _contextlib
import csv as _csv
import os as _os
import queue as _queue
import re as _re
import shutil as _shutil
import sys as _sys
import tempfile as _tempfile
import threading as _threading
import types as _types
_TESTS = _os.path.dirname(_os.path.abspath(__file__))
_sys.path.insert(0, _os.path.dirname(_TESTS))
_sys.path.insert(0, _TESTS)

import arb_editor  # noqa: E402
import gui  # noqa: E402
import sweep_plan  # noqa: E402
import ui_colors as uc  # noqa: E402
from instruments import BK4055B  # noqa: E402
import test_sg_live_lock as L  # noqa: E402  (its Waveform Editor stub)
import test_sldea_interlock as T  # noqa: E402  (its Webcam-tab stub app)

G = gui.InstrumentControlGUI
SWEEP_LOCK = 'Channel in use — SG sweep'
LIVE_LOCK = 'Channel in use — LIVE HV run'
START_Q = 'Start SG sweep'
BAD = 'Invalid sweep parameters'
# Four points, 0 V to Vpp, amplitude outer:
# (1, 1, 0.5), (10, 1, 0.5), (1, 2, 1), (10, 2, 1)
POINTS = sweep_plan.sg_points([1.0, 10.0], [1.0, 2.0])
DRAIN = ('drain',)


class _Entry:
    """Tk Entry / Combobox / variable / button stand-in."""

    def __init__(self, value=''):
        self.value = value
        self.cfg = {}

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def delete(self, first, last=None):
        self.value = ''

    def insert(self, index, s):
        self.value = str(s) + str(self.value)

    def configure(self, **kw):
        self.cfg.update(kw)

    config = configure


class _Label:
    """Label / Progressbar stand-in: the last text and colour, and every
    other option set."""

    def __init__(self):
        self.text = self.fg = None
        self.cfg = {}

    def config(self, text=None, foreground=None, **kw):
        if text is not None:
            self.text = text
        if foreground is not None:
            self.fg = foreground
        self.cfg.update(kw)

    configure = config


class _Root:
    """Tk root stand-in: after() records the call and never runs it;
    run_pending() plays the recorded calls the way the mainloop would."""

    def __init__(self):
        self.pending = []
        self.played = 0

    def after(self, ms, fn=None, *args):
        self.pending.append((ms, fn, args))
        return 'after#'

    def run_pending(self, limit=1000):
        while self.pending and self.played < limit:
            _ms, fn, args = self.pending.pop(0)
            self.played += 1
            fn(*args)


class _FakeSG:
    """BK4055B stand-in. Records every write as (call, channel, ...) and,
    beside it, whether the writing thread held the SG's I/O lock (the
    RLock instruments._io_lock keeps in the object's __dict__). The
    timeline also holds the drains (DRAIN), the read-backs ('read', ch)
    and the output reads ('outp', ch). Echoes are checked with the real
    BK4055B._check_echo when the caller asks.

    Switches: `fail(entry)` true -> that write raises instead of landing;
    `read_fail(n)` true -> the n-th read-back raises; `bswv_head(n, ch)`
    -> the echo the n-th read-back carries (None: its own); `clamp_amp`
    -> the read-back's AMP clamped to it; `edit(n, got)` -> the n-th
    read-back as it returns; `on_read(n)` runs inside the n-th read-back;
    `outp_fail`, `outp_head`, `outp_says_on` -> the OUTP? read raises,
    carries another echo, or reads ON whatever the last write;
    `on_write(entry)` runs after each write lands. Every drain and read
    records whether the SG's I/O lock was held for it."""
    idn = 'FAKE,4055B'
    ARB_DEFAULT_POINTS = 1024

    def __init__(self):
        self.writes, self.owned, self.timeline = [], [], []
        self.drain_owned, self.read_owned = [], []
        self.state = {1: {}, 2: {}}
        self.out_state = {1: False, 2: False}
        self.fail = self.read_fail = self.on_write = self.on_read = None
        self.bswv_head = self.edit = None
        self.clamp_amp = None
        self.outp_fail = self.outp_says_on = False
        self.outp_head = None
        self.reads = 0
        self.read_kw, self.outp_kw = [], []
        self.closed = False

    def lock_owned(self):
        lock = self.__dict__.get('_io_rlock')
        return lock is not None and lock._is_owned()

    def _rec(self, call, channel, *what):
        entry = (call, channel) + what
        if self.fail is not None and self.fail(entry):
            raise IOError(f'VISA timeout on {call}')
        self.writes.append(entry)
        self.owned.append(self.lock_owned())
        self.timeline.append(entry)
        if self.on_write is not None:
            self.on_write(entry)

    def _drain(self):
        self.timeline.append(DRAIN)
        self.drain_owned.append(self.lock_owned())

    def set_output(self, channel, on):
        self._rec('set_output', channel, on)
        self.out_state[channel] = on

    def set_load_polarity(self, channel, load=None, polarity=None):
        self._rec('set_load_polarity', channel, load, polarity)

    def set_burst(self, channel, on, ncycles=1, trigger='MAN',
                  period_s=None):
        self._rec('set_burst', channel, on)

    def set_basic_wave(self, channel, **params):
        self._rec('set_basic_wave', channel, dict(params))
        self.state[channel].update(params)

    def burst_trigger(self, channel):
        self._rec('burst_trigger', channel)

    def select_arb(self, channel, name):
        self._rec('select_arb', channel, name)

    def set_sync(self, channel, on):
        self._rec('set_sync', channel, on)

    def set_sample_rate(self, channel, mode=None, value=None):
        self._rec('set_sample_rate', channel, mode)

    def upload_arb(self, channel, name, samples, freq_hz=None, amp_vpp=None,
                   offset_v=None, phase_deg=None, points=None):
        self._rec('upload_arb', channel, name)
        return name

    def get_basic_wave_dict(self, channel, check_echo=False):
        self.reads += 1
        n = self.reads
        self.read_kw.append(check_echo)
        self.read_owned.append(self.lock_owned())
        self.timeline.append(('read', channel))
        if self.on_read is not None:
            self.on_read(n)
        if self.read_fail is not None and self.read_fail(n):
            raise IOError('BSWV? read-back timed out')
        head = (self.bswv_head(n, channel) if self.bswv_head else None) \
            or f'C{channel}:BSWV'
        if check_echo:
            BK4055B._check_echo(f'{head} WVTP,SINE', channel, 'BSWV')
        got = dict(self.state[channel])
        if self.clamp_amp is not None and 'AMP' in got:
            got['AMP'] = min(got['AMP'], self.clamp_amp)
        if self.edit is not None:
            got = self.edit(n, got)
        return got

    def get_output_dict(self, channel, check_echo=False):
        self.outp_kw.append(check_echo)
        self.read_owned.append(self.lock_owned())
        self.timeline.append(('outp', channel))
        if self.outp_fail:
            raise IOError('OUTP? timed out')
        if check_echo:
            BK4055B._check_echo(f"{self.outp_head or f'C{channel}:OUTP'} "
                                f"OFF", channel, 'OUTP')
        return {'state': self.outp_says_on or self.out_state[channel],
                'load': 'HZ', 'polarity': 'NOR'}

    def close(self):
        self.closed = True

    def channels(self):
        return {w[1] for w in self.writes}


class _MB:
    """tkinter.messagebox stand-in: records (kind, title, message, kw), and
    ('box', title) on `log` when given. A question is answered from
    `answers` by title (a value, or a callable run at the moment the
    dialog would be up); one it has no answer for fails the test -- an
    unexpected dialog is a finding."""

    def __init__(self, answers=None, log=None):
        self.answers = dict(answers or {})
        self.calls = []
        self.log = log

    def _record(self, kind, title, message, kw):
        self.calls.append((kind, title, message, kw))
        if self.log is not None:
            self.log.append(('box', title))

    def askyesno(self, title, message, **kw):
        self._record('askyesno', title, message, kw)
        if title not in self.answers:
            raise AssertionError(f"unexpected question: {title!r}")
        answer = self.answers[title]
        return answer() if callable(answer) else answer

    def _note(self, kind):
        def show(title, message, **kw):
            self._record(kind, title, message, kw)
        return show

    def __getattr__(self, name):
        if name.startswith('show'):
            return self._note(name)
        raise AttributeError(name)

    def kinds_titles(self):
        return [(c[0], c[1]) for c in self.calls]


class _Threads:
    """gui's `threading` while sg_start_sweep runs: Thread records what it
    was handed and never runs it (with `fail_start`, start() raises);
    everything else is the real module."""

    def __init__(self, fail_start=False):
        self.made = []
        made = self.made

        class Thread:
            def __init__(self, target=None, args=(), kwargs=None,
                         daemon=None, **_kw):
                self.target, self.args, self.daemon = target, tuple(args), \
                    daemon
                self.started = False
                made.append(self)

            def start(self):
                if fail_start:
                    raise RuntimeError("can't start new thread")
                self.started = True

            def is_alive(self):
                return False

        self.Thread = Thread

    def __getattr__(self, name):
        return getattr(_threading, name)


class _SpyLock:
    """The SG's I/O lock, with a flag set when a thread starts to take it,
    so a test can act while the worker waits at the lock."""

    def __init__(self):
        self.inner = _threading.RLock()
        self.waiting = _threading.Event()

    def __enter__(self):
        self.waiting.set()
        self.inner.acquire()
        return self

    def __exit__(self, *exc):
        self.inner.release()
        return False

    def _is_owned(self):
        return self.inner._is_owned()


def _channel_widgets():
    """One channel's Signal Gen panel, set up as a plain DC level."""
    return {'waveform': _Entry('DC'), 'freq': _Entry('1000'),
            'amp': _Entry('1'), 'offset': _Entry('0.5'),
            'duty': _Entry('50'), 'output': _Entry(False),
            'load': _Entry('HZ'), 'polarity': _Entry('NOR'),
            'burst_on': _Entry(False), 'burst_ncyc': _Entry('1'),
            'burst_trsr': _Entry('MAN'), 'burst_prd': _Entry(''),
            'sync_on': _Entry(False), 'arb_name_var': _Entry(''),
            'arb_samples': None}


class _App:
    """Just enough app for the sweep and the channel's other writers: the
    real methods under test, stubs for Tk. `_run_bg` runs the job inline
    and records (busy key, quiet); with `bg_refuse` > 0 it refuses that
    many jobs first, as a busy key would. `order` logs the Tk-side steps
    the finish handler takes, and the message boxes when the _MB shares
    it."""
    # the sweep
    sg_start_sweep = G.sg_start_sweep
    sg_stop_sweep = G.sg_stop_sweep
    _sg_sweep_worker = G._sg_sweep_worker
    _drain_sg_sweep_queue = G._drain_sg_sweep_queue
    _sg_sweep_finished = G._sg_sweep_finished
    _sg_sweep_refresh = G._sg_sweep_refresh
    _sg_sweep_locked = G._sg_sweep_locked
    _sg_sweep_blocks = G._sg_sweep_blocks
    _sg_sweep_read_plan = G._sg_sweep_read_plan
    _sg_sweep_start_refused = G._sg_sweep_start_refused
    _default_sg_sweep_path = G._default_sg_sweep_path
    # what it asks
    _sg_live_locked = G._sg_live_locked
    _sg_load_to_wire = G._sg_load_to_wire
    _cam_worker_alive = G._cam_worker_alive
    _set_entry = staticmethod(G._set_entry)
    # the channel's other writers
    apply_sg_channel = G.apply_sg_channel
    sg_fire_burst = G.sg_fire_burst
    sg_toggle_output = G.sg_toggle_output
    _reconnect = G._reconnect
    _bg_simple = G._bg_simple

    def __init__(self, tmp='.'):
        self.root = _Root()
        self.sg = _FakeSG()
        self.status_bar, self.sg_status = _Label(), _Label()
        self.sgsw_status, self.sgsw_progress = _Label(), _Label()
        self.sg_channel_widgets = {1: _channel_widgets(),
                                   2: _channel_widgets()}
        self.sg_sweeping = False
        self._sg_sweep_gen = self._sg_sweep_ch = None
        self.sg_sweep_thread = None
        self.sg_sweep_queue = _queue.Queue()
        self._sldea_live_ch = self._sldea_dry_ch = None
        self._app_closing = False
        self._bg_busy = set()
        self.cam_seq_thread = None
        self._cam_seq_kind = self._cam_seq_ch = None
        self.bg, self.bg_refused, self.bg_refuse = [], [], 0
        self.out_btn, self.ui_state, self.order = [], [], []
        self.populated, self.sleeps, self.parsed = [], [], []
        self.fetch_args = []
        self.sleep_hook = None
        self.ui_state_raises = False
        self.fetch_error = None
        self.library = []                # Waveform Editor library saves
        self.sg_presets = _types.SimpleNamespace(
            save_arb=lambda name, samples, recipe=None:
            self.library.append(name))
        self.log_dir = _Entry(tmp)
        # the Stepped sweep box, at a valid 4-point sweep on CH1
        self.sgsw_ch = _Entry('1')
        self.sgsw_wave = _Entry('SINE')
        self.sgsw_duty = _Entry('50')
        self.sgsw_order = _Entry(sweep_plan.SG_ORDER_AMP_OUTER)
        self.sgsw_dwell = _Entry('0')
        self.sgsw_unipolar = _Entry(True)
        self.sgsw_offset = _Entry('0')
        self.sgsw_output = _Entry(_os.path.join(tmp, 'sg_sweep_test.csv'))
        for axis, values in (('sgfreq', '1, 10'), ('sgamp', '1, 2')):
            for attr, val in (('mode', 'list'), ('list_var', values),
                              ('start_entry', '1'), ('stop_entry', '2'),
                              ('points_entry', '2'), ('scale', 'linear')):
                setattr(self, f'sw_{axis}_{attr}', _Entry(val))

    def _parse_sweep_axis(self, axis, vmin, vmax, name):
        """The real one, and a note that the axis was planned."""
        self.parsed.append(axis)
        return G._parse_sweep_axis(self, axis, vmin, vmax, name)

    def _run_bg(self, work, done, busy=None, quiet=False):
        if self.bg_refuse > 0:
            self.bg_refuse -= 1
            self.bg_refused.append((busy, quiet))
            return False
        self.bg.append((busy, quiet))
        self.order.append(('bg', busy))
        result = error = None
        try:
            result = work()
        except Exception as e:
            error = e
        done(result, error)
        return True

    def _interruptible_sleep(self, seconds, chunk=0.05, alive=None):
        """Returns at once; the hook gets the 1-based count of sleeps."""
        self.sleeps.append(seconds)
        if self.sleep_hook is not None:
            self.sleep_hook(len(self.sleeps))

    def _sg_fetch_channel(self, ch, bswv=None, outp=None):
        self.fetch_args.append((ch, bswv, outp))
        if self.fetch_error is not None:
            raise self.fetch_error
        return {'fetched': ch}

    def _sg_populate_inputs(self, ch, data):
        self.populated.append((ch, data))

    def _sg_show_applied(self, ch, data):
        pass

    def _sg_set_output_button(self, ch, on):
        self.out_btn.append((ch, on))

    def _sg_update_visibility(self, ch):
        self.order.append(('panel', ch))

    def _sg_redraw_preview(self, ch):
        pass

    def _sg_refresh_applied(self, ch):
        pass

    def _sg_sweep_ui_state(self, running):
        self.ui_state.append(running)
        self.order.append(('ui_state', running))
        if self.ui_state_raises:
            raise RuntimeError('widget gone')


@_contextlib.contextmanager
def _patched(mb, threads=None):
    """The messagebox recorder in gui and arb_editor, the Linux gate open
    so Reconnect gets as far as the locks on any OS, and (optionally) the
    Thread recorder in gui."""
    saved = (gui.messagebox, arb_editor.messagebox,
             gui.INSTRUMENTS_SUPPORTED, gui.threading)
    gui.messagebox = arb_editor.messagebox = mb
    gui.INSTRUMENTS_SUPPORTED = True
    if threads is not None:
        gui.threading = threads
    try:
        yield mb
    finally:
        (gui.messagebox, arb_editor.messagebox,
         gui.INSTRUMENTS_SUPPORTED, gui.threading) = saved


@_contextlib.contextmanager
def _tmpdir():
    path = _tempfile.mkdtemp(prefix='sg_sweep_test_')
    try:
        yield path
    finally:
        _shutil.rmtree(path, ignore_errors=True)


def _drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except _queue.Empty:
            return out


def _claim(app, ch):
    """What sg_start_sweep does just before it starts the worker."""
    app._sg_sweep_ch = ch
    app.sg_sweeping = True
    app._sg_sweep_gen = object()
    return app._sg_sweep_gen


def _run_worker(app, path, ch=1, wave='SINE', duty=None, points=POINTS,
                dwell=0.0, load='HZ', polarity='NOR', drain=True):
    """Run the real worker to its end in this thread -> its events (or
    None with drain=False, leaving them for _drain_sg_sweep_queue)."""
    tok = _claim(app, ch)
    app._sg_sweep_worker(ch, wave, duty, list(points), dwell, load, polarity,
                         path, tok)
    return _drain(app.sg_sweep_queue) if drain else None


def _finish(app, mb=None):
    """Play the queued events through the real drain -> the _MB."""
    mb = _MB() if mb is None else mb
    with _patched(mb):
        app._drain_sg_sweep_queue()
    return mb


def _final(events):
    assert events and events[-1][0] == 'final', events
    assert [e[0] for e in events].count('final') == 1, events
    return events[-1][1]


def _on(ch):
    return ('set_output', ch, True)


def _off(ch):
    return ('set_output', ch, False)


def _setup(ch, first, load='HZ', polarity='NOR', wave='SINE', duty=None):
    """Point 1's lock block: the set-up writes and point 1 (no ON)."""
    shape = {'WVTP': wave}
    if wave == 'SQUARE':
        shape['DUTY'] = duty
    f, a, o = first
    return [('set_output', ch, False),
            ('set_load_polarity', ch, load, polarity),
            ('set_burst', ch, False),
            ('set_basic_wave', ch, shape),
            ('set_basic_wave', ch, {'FRQ': f, 'AMP': a, 'OFST': o})]


def _levels(ch, prev, new):
    return [('set_basic_wave', ch, w)
            for w in sweep_plan.level_writes(prev, new)]


def _expected(ch, n, points=POINTS, on=True, **setup):
    """Every write for the first `n` points, in order (no final OFF)."""
    out = _setup(ch, points[0], **setup) + ([_on(ch)] if on else [])
    for prev, new in zip(points, points[1:n]):
        out += _levels(ch, prev, new)
    return out


def _rb(ch):
    """A read-back: drained and asked under one hold of the lock."""
    return [DRAIN, ('read', ch)]


def _tail(ch):
    """The end of every touched sweep not taken by a LIVE run or ended by
    a window close: OFF, then a drain and the OUTP? read that must say
    OFF."""
    return [_off(ch), DRAIN, ('outp', ch)]


def _full_timeline(ch, points=POINTS, **setup):
    """Every write, drain and read of a sweep that runs to its end."""
    out = [DRAIN] + _setup(ch, points[0], **setup) + _rb(ch) + [_on(ch)]
    for prev, new in zip(points, points[1:]):
        out += _levels(ch, prev, new) + _rb(ch)
    return out + _tail(ch)


def _refresh(ch):
    """The read of the box after a sweep: drained, BSWV? and OUTP?, all
    under one hold of the lock."""
    return [DRAIN, ('read', ch), ('outp', ch)]


def _rows(path):
    with open(path, newline='') as f:
        return list(_csv.reader(f))


def _warned(mb, ch, state='is being stepped by the sweep', parent=None):
    """Exactly one dialog: the sweep lock's warning for SG CH`ch`."""
    [(kind, title, msg, kw)] = mb.calls
    assert (kind, title) == ('showwarning', SWEEP_LOCK), mb.calls
    assert f"SG CH{ch} {state}" in msg, msg
    assert 'the other channel stays available' in msg, msg
    assert kw == ({} if parent is None else {'parent': parent}), kw


# --------------------------------------------------------------------------
# The worker: what it writes and reads, in what order, holding what
# --------------------------------------------------------------------------

def test_the_io_is_setup_point1_readback_on_then_each_level_then_off():
    for ch, wave, duty in ((1, 'SINE', None), (2, 'SQUARE', 30.0)):
        with _tmpdir() as tmp:
            app = _App(tmp)
            path = _os.path.join(tmp, 'out.csv')
            events = _run_worker(app, path, ch=ch, wave=wave, duty=duty)
            setup = dict(wave=wave, duty=duty)
            assert app.sg.timeline == _full_timeline(ch, **setup), \
                app.sg.timeline
            assert app.sg.writes == _expected(ch, 4, **setup) + [_off(ch)]
            assert app.sg.channels() == {ch}, app.sg.writes
            # every read checks that the reply is its own, and is drained
            # and asked under one hold of the SG's I/O lock
            assert app.sg.read_kw == [True] * 4, app.sg.read_kw
            assert app.sg.outp_kw == [True], app.sg.outp_kw
            assert app.sg.read_owned == [True] * 5, app.sg.read_owned
            assert app.sg.drain_owned == [True] * 6, app.sg.drain_owned
            assert [e[0] for e in events] == ['on'] + ['point'] * 4 + \
                ['final'], events
            r = _final(events)
            assert (r['ch'], r['wave'], r['duty']) == (ch, wave, duty), r
            assert (r['touched'], r['off_ok'], r['live']) == (True, True,
                                                              False), r
            assert (r['done'], r['total'], r['mismatches']) == (4, 4, 0), r
            assert r['last'] == POINTS[-1] and r['mixed'] is False, r
            assert r['error'] is None and r['stopped'] is False, r
            assert r['path'] == path, r
            assert app.sleeps == [0.2] * 4, app.sleeps


def test_the_dwell_is_counted_from_on_and_then_from_each_points_writes():
    with _tmpdir() as tmp:
        app = _App(tmp)
        _run_worker(app, _os.path.join(tmp, 'out.csv'), dwell=3.0)
        assert app.sleeps[0::2] == [0.2] * 4, app.sleeps
        # point 1's dwell starts at ON, after its read-back: nearly whole
        assert 2.9 < app.sleeps[1] <= 3.0, app.sleeps
        assert all(2.5 < s <= 3.0 for s in app.sleeps[1::2]), app.sleeps


def test_the_set_up_on_and_every_points_writes_hold_the_sg_io_lock():
    """Checked from the writing thread (RLock._is_owned) at every write,
    and once from another thread at ON, which must find the lock taken."""
    with _tmpdir() as tmp:
        app = _App(tmp)
        other = []

        def probe(entry):
            if entry == _on(1):
                lock = app.sg.__dict__['_io_rlock']

                def try_it():
                    got = lock.acquire(blocking=False)
                    other.append(got)
                    if got:
                        lock.release()
                t = _threading.Thread(target=try_it)
                t.start()
                t.join(5)
        app.sg.on_write = probe
        _run_worker(app, _os.path.join(tmp, 'out.csv'))
        # every write but the closing OFF, which the driver locks itself
        assert len(app.sg.owned) == len(_expected(1, 4)) + 1, app.sg.writes
        assert all(app.sg.owned[:-1]), list(zip(app.sg.writes,
                                                app.sg.owned))
        assert all(app.sg.drain_owned), app.sg.drain_owned
        assert all(app.sg.read_owned), app.sg.read_owned
        assert other == [False], "another thread got the lock at ON"
        lock = app.sg.__dict__['_io_rlock']
        res = []
        t = _threading.Thread(target=lambda: res.append(
            lock.acquire(blocking=False)))
        t.start()
        t.join(5)
        assert res == [True], "the worker left the SG's I/O lock held"


def test_a_close_that_took_the_lock_first_leaves_the_worker_doing_nothing():
    """Window close sets _app_closing and clears sg_sweeping, then takes
    the SG's I/O lock for its outputs-off. A worker already past its first
    check and waiting at that lock must, once it gets the lock, find the
    flags and do nothing at all: no drain, no write, no read."""
    for flags in ({'_app_closing': True}, {'sg_sweeping': False},
                  {'_app_closing': True, 'sg_sweeping': False}):
        with _tmpdir() as tmp:
            app = _App(tmp)
            spy = _SpyLock()
            app.sg.__dict__['_io_rlock'] = spy
            tok = _claim(app, 1)
            spy.inner.acquire()              # the close's outputs-off
            worker = _threading.Thread(
                target=app._sg_sweep_worker,
                args=(1, 'SINE', None, list(POINTS), 0.0, 'HZ', 'NOR',
                      _os.path.join(tmp, 'out.csv'), tok), daemon=True)
            worker.start()
            try:
                assert spy.waiting.wait(5), "the worker never reached the lock"
                for name, value in flags.items():
                    setattr(app, name, value)
            finally:
                spy.inner.release()
            worker.join(5)
            assert not worker.is_alive(), flags
            assert app.sg.timeline == [], (flags, app.sg.timeline)
            events = _drain(app.sg_sweep_queue)
            assert [e[0] for e in events] == ['final'], (flags, events)
            r = _final(events)
            assert r['touched'] is False and r['off_ok'] is None, r
            assert (r['done'], r['last'], r['live']) == (0, None, False), r
            assert r['stopped'] is True and r['mixed'] is False, r
            # nothing touched: nothing to read back into the panel
            for e in events:
                app.sg_sweep_queue.put(e)
            mb = _finish(app)
            assert mb.calls == [] and app.bg == [], (mb.calls, app.bg)
            assert 'Stopped before any write' in app.sgsw_status.text
    with _tmpdir() as tmp:              # a close done before the first check
        app = _App(tmp)
        app._app_closing = True
        r = _final(_run_worker(app, _os.path.join(tmp, 'out.csv')))
        assert app.sg.timeline == [] and r['touched'] is False


# --------------------------------------------------------------------------
# The point-1 gate: read back with the output OFF, ON only if it matched
# --------------------------------------------------------------------------

def test_a_point1_whose_shape_was_refused_is_never_switched_on():
    """The gate checks the waveform (and a SQUARE's duty) too: a box that
    refused WVTP or DUTY would leave another waveform at the right
    FRQ/AMP/OFST, which the volts alone cannot show."""
    def edit(field, value):
        def apply(n, got):
            if n == 1:
                got = dict(got)
                got[field] = value
            return got
        return apply
    for wave, duty, field, value in (('SINE', None, 'WVTP', 'DC'),
                                     ('SQUARE', 50.0, 'WVTP', 'SINE'),
                                     ('SQUARE', 50.0, 'DUTY', 49.5),
                                     ('SQUARE', 50.0, 'DUTY', None)):
        with _tmpdir() as tmp:
            app = _App(tmp)
            path = _os.path.join(tmp, 'out.csv')
            app.sg.edit = edit(field, value)
            r = _final(_run_worker(app, path, wave=wave, duty=duty))
            assert _on(1) not in app.sg.writes, (field, value, app.sg.writes)
            assert 'never switched on' in r['error'], r
            assert (r['off_ok'], r['done'], r['mismatches']) == \
                (True, 0, 1), r
            rows = _rows(path)
            assert len(rows) == 2 and rows[1][13] == 'no', rows
    # the same shape, read back as sent, switches ON
    with _tmpdir() as tmp:
        app = _App(tmp)
        r = _final(_run_worker(app, _os.path.join(tmp, 'out.csv'),
                               wave='SQUARE', duty=50.0))
        assert _on(1) in app.sg.writes and r['error'] is None, r


def test_a_point1_that_reads_back_wrong_is_never_switched_on():
    with _tmpdir() as tmp:
        app = _App(tmp)
        path = _os.path.join(tmp, 'out.csv')
        app.sg.clamp_amp = 0.5                   # point 1 asks 1 Vpp
        events = _run_worker(app, path)
        assert _on(1) not in app.sg.writes, app.sg.writes
        assert app.sg.timeline == [DRAIN] + _setup(1, POINTS[0]) + _rb(1) \
            + _tail(1), app.sg.timeline
        rows = _rows(path)
        assert len(rows) == 2, rows              # the evidence, marked no
        assert rows[1][1] == '1' and rows[1][13] == 'no', rows[1]
        assert float(rows[1][11]) == 0.5, rows[1]
        assert [e[0] for e in events] == ['final'], events
        r = _final(events)
        assert 'point 1 read back as' in r['error'], r
        assert 'never switched on' in r['error'], r
        assert (r['off_ok'], r['done'], r['touched']) == (True, 0, True), r
        # the box holds what it read, not point 1: no last point
        assert r['last'] is None and r['mixed'] is False, r
        for e in events:
            app.sg_sweep_queue.put(e)
        mb = _finish(app)
        assert mb.kinds_titles() == [('showerror', 'SG sweep error')], \
            mb.calls
        assert app.out_btn == [(1, False)], app.out_btn
        w = app.sg_channel_widgets[1]
        assert (w['waveform'].get(), w['freq'].get()) == ('DC', '1000'), \
            "the panel was filled with a point the box does not hold"


def test_a_read_back_that_ends_the_sweep_is_not_reported_as_matching():
    """KNOWN BUG (2026-10-27): a read-back that ends the sweep -- point 1's
    mismatch, or a band outside the approved volts -- writes its CSV row
    marked 'no' and raises before `mismatches` counts it, so the status
    line and the error box say "every read-back matches" beside an error
    that says it did not."""
    for name, switch, value in (
            ('point 1 mismatch', 'clamp_amp', 0.5),
            ('band outside', 'edit', _shift_ofst(3, -0.02))):
        with _tmpdir() as tmp:
            app = _App(tmp)
            path = _os.path.join(tmp, 'out.csv')
            setattr(app.sg, switch, value)
            _run_worker(app, path, drain=False)
            assert _rows(path)[-1][13] == 'no', (name, _rows(path))
            mb = _finish(app)
            [(_kind, _title, box, _kw)] = mb.calls
            assert 'every read-back matches' not in app.sgsw_status.text, \
                (name, app.sgsw_status.text)
            assert 'every read-back matches' not in box, (name, box)


def test_a_point1_read_back_that_fails_or_is_not_its_own_never_switches_on():
    cases = [
        ('raises', dict(read_fail=lambda n: n == 1),
         'BSWV? read-back timed out'),
        ('another channel', dict(bswv_head=lambda n, ch: 'C2:BSWV'),
         'not its own'),
        ('an OUTP? answer', dict(bswv_head=lambda n, ch: 'C1:OUTP'),
         'not its own'),
    ]
    for name, switches, says in cases:
        with _tmpdir() as tmp:
            app = _App(tmp)
            path = _os.path.join(tmp, 'out.csv')
            for k, v in switches.items():
                setattr(app.sg, k, v)
            r = _final(_run_worker(app, path))
            assert _on(1) not in app.sg.writes, (name, app.sg.writes)
            assert app.sg.timeline == [DRAIN] + _setup(1, POINTS[0]) + \
                _rb(1) + _tail(1), (name, app.sg.timeline)
            assert says in r['error'], (name, r)
            assert r['off_ok'] is True and r['done'] == 0, (name, r)
            assert len(_rows(path)) == 1, (name, _rows(path))


def test_stop_or_a_live_claim_between_point1s_read_back_and_on():
    """The ON block asks again under the lock: Stop then gives OFF and its
    read-back, and a LIVE claim gives nothing at all -- the output was
    never switched on, so the run inherits an OFF channel. Point 1's row
    is written after its ON, so neither leaves a row."""
    with _tmpdir() as tmp:
        app = _App(tmp)
        path = _os.path.join(tmp, 'out.csv')
        app.sg.on_read = lambda n: app.sg_stop_sweep() if n == 1 else None
        r = _final(_run_worker(app, path))
        assert app.sg.timeline == [DRAIN] + _setup(1, POINTS[0]) + \
            _rb(1) + _tail(1), app.sg.timeline
        assert (r['stopped'], r['off_ok'], r['error']) == (True, True,
                                                           None), r
        assert (r['done'], r['last']) == (0, POINTS[0]), r
        assert len(_rows(path)) == 1, _rows(path)
    with _tmpdir() as tmp:
        app = _App(tmp)
        path = _os.path.join(tmp, 'out.csv')
        app.sg.on_read = lambda n: setattr(app, '_sldea_live_ch', 1)
        r = _final(_run_worker(app, path))
        assert app.sg.timeline == [DRAIN] + _setup(1, POINTS[0]) + \
            _rb(1), app.sg.timeline
        assert (r['live'], r['off_ok'], r['touched']) == (True, None, True), r
        assert len(_rows(path)) == 1, _rows(path)


def test_point1s_row_is_written_after_its_on():
    with _tmpdir() as tmp:
        app = _App(tmp)
        path = _os.path.join(tmp, 'out.csv')
        seen = []
        app.sg.on_write = lambda e: seen.append(len(_rows(path))) \
            if e == _on(1) else None
        _run_worker(app, path)
        assert seen == [1], "point 1's row was written before its ON"
        assert len(_rows(path)) == 5


def test_a_wrong_echo_on_a_later_read_back_stops_the_sweep_with_off():
    with _tmpdir() as tmp:
        app = _App(tmp)
        path = _os.path.join(tmp, 'out.csv')
        app.sg.bswv_head = lambda n, ch: 'C1:OUTP' if n == 3 else None
        r = _final(_run_worker(app, path))
        assert app.sg.writes == _expected(1, 3) + [_off(1)], app.sg.writes
        assert app.sg.timeline[-5:] == _rb(1) + _tail(1), app.sg.timeline
        assert 'not its own' in r['error'], r
        assert (r['off_ok'], r['done']) == (True, 2), r
        assert r['last'] == POINTS[2] and r['mixed'] is False, r
        assert len(_rows(path)) == 3, _rows(path)


# --------------------------------------------------------------------------
# The band guard: a read-back outside the approved volts ends the sweep
# --------------------------------------------------------------------------

def _shift_ofst(at, by):
    """An `edit` that moves the at-th read-back's OFST by `by` volts."""
    def edit(n, got):
        if n == at:
            got = dict(got, OFST=got['OFST'] + by)
        return got
    return edit


def test_a_read_back_below_the_approved_trough_stops_the_sweep_with_off():
    """The question approved 0 V to 2 V. Point 3 (2 Vpp at 1 V) reads back
    20 mV low, so its trough is below 0 V: the row is written, then the
    sweep ends with OFF and its read."""
    with _tmpdir() as tmp:
        app = _App(tmp)
        path = _os.path.join(tmp, 'out.csv')
        app.sg.edit = _shift_ofst(3, -0.02)
        r = _final(_run_worker(app, path))
        assert app.sg.writes == _expected(1, 3) + [_off(1)], app.sg.writes
        assert app.sg.timeline[-5:] == _rb(1) + _tail(1), app.sg.timeline
        assert r['error'] == ('point 3 read back as -0.02 V to 1.98 V, '
                              'outside the 0 V to 2 V approved'), r
        # the stopping read-back is counted too (it was not, before the fix
        # test_a_read_back_that_ends_the_sweep_is_not_reported_as_matching)
        assert (r['off_ok'], r['done'], r['mismatches']) == (True, 2, 1), r
        rows = _rows(path)
        assert len(rows) == 4 and rows[3][13] == 'no', rows


def test_a_read_back_above_the_approved_peak_stops_the_sweep():
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sg.edit = _shift_ofst(4, 0.5)        # 2 Vpp at 1.5 V: 2.5 V
        r = _final(_run_worker(app, _os.path.join(tmp, 'out.csv')))
        assert 'point 4 read back as 0.5 V to 2.5 V' in r['error'], r
        assert r['off_ok'] is True and r['done'] == 3, r


def test_the_band_guard_allows_ten_millivolts_of_slack():
    for by, stops in ((0.009, False), (0.011, True),
                      (-0.009, False), (-0.011, True)):
        with _tmpdir() as tmp:
            app = _App(tmp)
            # the peak (point 4: 2 Vpp at 1 V) or the trough (point 3)
            app.sg.edit = _shift_ofst(4 if by > 0 else 3, by)
            r = _final(_run_worker(app, _os.path.join(tmp, 'out.csv')))
            if stops:
                assert 'outside the 0 V to 2 V approved' in r['error'], \
                    (by, r)
            else:
                # a mismatch inside the band is counted, not fatal
                assert r['error'] is None and r['done'] == 4, (by, r)
                assert r['mismatches'] == 1, (by, r)


def test_a_mismatch_inside_the_band_or_with_no_band_is_only_counted():
    for name, edit in (
            ('narrower', lambda n, got: dict(got, AMP=got['AMP'] * 0.5)
             if n == 2 else got),
            ('moved inside', _shift_ofst(2, 0.4)),
            ('no AMP', lambda n, got: {k: v for k, v in got.items()
                                       if k != 'AMP'} if n == 2 else got),
            ('OFST junk', lambda n, got: dict(got, OFST='?')
             if n == 2 else got),
            ('AMP nan', lambda n, got: dict(got, AMP=float('nan'))
             if n == 2 else got)):
        with _tmpdir() as tmp:
            app = _App(tmp)
            app.sg.edit = edit
            r = _final(_run_worker(app, _os.path.join(tmp, 'out.csv')))
            assert r['error'] is None, (name, r)
            assert (r['done'], r['mismatches']) == (4, 1), (name, r)
            assert app.sg.timeline == _full_timeline(1), name


def test_the_band_is_the_one_the_question_named_for_a_bipolar_sweep():
    """Offset -0.5 V, 1 and 2 Vpp: approved -1.5 V to 0.5 V. A read-back
    within it passes even far from 0 V; one past it stops the sweep."""
    pts = sweep_plan.sg_points([1.0, 10.0], [1.0, 2.0], unipolar=False,
                               offset_v=-0.5)
    assert sweep_plan.sg_extremes(pts) == (-1.5, 0.5)
    with _tmpdir() as tmp:
        app = _App(tmp)
        r = _final(_run_worker(app, _os.path.join(tmp, 'out.csv'),
                               points=pts))
        assert r['error'] is None and r['done'] == 4, r
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sg.edit = _shift_ofst(3, -0.1)
        r = _final(_run_worker(app, _os.path.join(tmp, 'out.csv'),
                               points=pts))
        assert 'outside the -1.5 V to 0.5 V approved' in r['error'], r


# --------------------------------------------------------------------------
# OFF at the end, however the sweep ends
# --------------------------------------------------------------------------

def test_stop_mid_sweep_switches_the_channel_off():
    with _tmpdir() as tmp:
        app = _App(tmp)
        path = _os.path.join(tmp, 'out.csv')
        app.sleep_hook = lambda n: app.sg_stop_sweep() if n == 2 else None
        r = _final(_run_worker(app, path))
        assert app.sg.writes == _expected(1, 2) + [_off(1)], app.sg.writes
        assert app.sg.timeline[-3:] == _tail(1), app.sg.timeline
        assert (r['stopped'], r['done'], r['off_ok']) == (True, 1, True), r
        assert r['error'] is None, r
        # point 2 was written in full; its read-back never happened
        assert r['last'] == POINTS[1] and r['mixed'] is False, r
        assert len(_rows(path)) == 2, _rows(path)
        assert 'Stop requested' in app.sgsw_status.text, app.sgsw_status.text


def test_a_write_that_raises_mid_point_switches_off_and_names_no_last_point():
    """Point 3 changes the frequency, the offset and then the amplitude;
    the amplitude write fails, so the box holds a mix of points 2 and 3.
    Nothing more is sent but the OFF, the last event says the point was
    mixed and names no last point, and the panel is left alone until the
    box is read back."""
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sg.fail = lambda e: (e[0] == 'set_basic_wave'
                                 and e[2].get('AMP') == 2.0)
        events = _run_worker(app, _os.path.join(tmp, 'out.csv'))
        assert app.sg.writes == _expected(1, 2) + [
            ('set_basic_wave', 1, {'FRQ': 1.0}),
            ('set_basic_wave', 1, {'OFST': 1.0}), _off(1)], app.sg.writes
        assert app.sg.timeline[-3:] == _tail(1), app.sg.timeline
        r = _final(events)
        assert 'VISA timeout on set_basic_wave' in r['error'], r
        assert (r['off_ok'], r['done'], r['touched']) == (True, 2, True), r
        assert r['mixed'] is True and r['last'] is None, r
        for e in events:
            app.sg_sweep_queue.put(e)
        mb = _finish(app)
        assert mb.kinds_titles() == [('showerror', 'SG sweep error')]
        w = app.sg_channel_widgets[1]
        assert (w['waveform'].get(), w['freq'].get(), w['offset'].get()) \
            == ('DC', '1000', '0.5'), "the panel was filled from a mix"
        assert "writes did not all land" in app.sgsw_status.text, \
            app.sgsw_status.text
        assert app.populated == [(1, {'fetched': 1})], app.populated
    # a write that fails in point 1's set-up: mixed too, no last point
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sg.fail = lambda e: e[0] == 'set_burst'
        r = _final(_run_worker(app, _os.path.join(tmp, 'out.csv')))
        assert app.sg.writes == _setup(1, POINTS[0])[:2] + [_off(1)]
        assert r['mixed'] is True and r['last'] is None, r


def test_a_read_back_that_raises_stops_the_sweep_and_switches_off():
    """A late reply would shift every later row (#495 on the LCR), so a
    failed read-back ends the sweep: after it come only the OFF and its
    read, and the CSV holds only the rows before it."""
    with _tmpdir() as tmp:
        app = _App(tmp)
        path = _os.path.join(tmp, 'out.csv')
        app.sg.read_fail = lambda n: n == 2
        r = _final(_run_worker(app, path))
        assert app.sg.timeline[-4:] == [('read', 1)] + _tail(1), \
            app.sg.timeline
        assert app.sg.writes == _expected(1, 2) + [_off(1)], app.sg.writes
        rows = _rows(path)
        assert len(rows) == 2 and rows[1][1] == '1', rows
        assert 'BSWV? read-back timed out' in r['error'], r
        assert (r['off_ok'], r['done']) == (True, 1), r
        assert r['last'] == POINTS[1] and r['mixed'] is False, r


def test_a_window_close_mid_sweep_switches_off_and_reads_nothing_more():
    """The close's own OFF covers the channel and its session is closing:
    the worker still sends its OFF, then no drain and no OUTP? read that
    could hang it, and the OFF counts as unconfirmed."""
    with _tmpdir() as tmp:
        app = _App(tmp)

        def close(n):
            if n == 2:
                app._app_closing = True
        app.sleep_hook = close
        r = _final(_run_worker(app, _os.path.join(tmp, 'out.csv')))
        assert app.sg.writes == _expected(1, 2) + [_off(1)], app.sg.writes
        assert app.sg.timeline[-1] == _off(1), app.sg.timeline
        assert ('outp', 1) not in app.sg.timeline, app.sg.timeline
        assert app.sg.timeline.count(DRAIN) == 2, app.sg.timeline  # 1 + rb
        assert (r['stopped'], r['off_ok']) == (True, False), r
        assert r['error'] == 'switching the output OFF was not confirmed: ' \
                             'window closed', r


def test_a_live_claim_mid_sweep_stops_every_write_the_off_included():
    """The run owns the channel from its claim on: the sweep writes
    nothing more, not even its OFF, and says so in its last event."""
    with _tmpdir() as tmp:
        app = _App(tmp)
        mark = []

        def claim(n):
            if n == 2:
                mark.append(len(app.sg.writes))
                app._sldea_live_ch = 1
        app.sleep_hook = claim
        events = _run_worker(app, _os.path.join(tmp, 'out.csv'))
        assert app.sg.writes[mark[0]:] == [], app.sg.writes
        assert app.sg.writes == _expected(1, 2), app.sg.writes
        assert ('outp', 1) not in app.sg.timeline, app.sg.timeline
        r = _final(events)
        assert (r['live'], r['off_ok'], r['touched']) == (True, None, True), r
        for e in events:
            app.sg_sweep_queue.put(e)
        mb = _finish(app)
        assert mb.calls == [], mb.calls
        assert 'A LIVE SLDEA run took CH1' in app.sgsw_status.text
        assert (1, False) not in app.out_btn, app.out_btn
        assert app._sg_sweep_ch is None
    # a LIVE claim on the OTHER channel does not stop it
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sleep_hook = lambda n: setattr(app, '_sldea_live_ch', 2)
        r = _final(_run_worker(app, _os.path.join(tmp, 'out.csv')))
        assert app.sg.timeline == _full_timeline(1), app.sg.timeline
        assert r['live'] is False and r['done'] == 4, r


# --------------------------------------------------------------------------
# The OFF is believed only when the box reads it back
# --------------------------------------------------------------------------

def _second_off_fails():
    seen = []

    def fail(entry):
        if entry == _off(entry[1]):
            seen.append(entry)
            return len(seen) >= 2        # the set-up's OFF lands
        return False
    return fail


def test_the_off_is_confirmed_only_by_an_outp_read_that_says_off():
    cases = [  # (name, switches, off_ok, error, OUTP? read)
        ('reads OFF', {}, True, None, True),
        ('reads ON', {'outp_says_on': True}, False,
         'the output still reads ON after the OFF', True),
        ('OUTP? raises', {'outp_fail': True}, False,
         'switching the output OFF was not confirmed: OUTP? timed out',
         True),
        ('another echo', {'outp_head': 'C1:BSWV'}, False, 'not its own',
         True),
        ('the OFF raises', {'fail': _second_off_fails()}, False,
         'switching the output OFF was not confirmed: VISA timeout', False),
    ]
    for name, switches, off_ok, says, read in cases:
        with _tmpdir() as tmp:
            app = _App(tmp)
            for k, v in switches.items():
                setattr(app.sg, k, v)
            r = _final(_run_worker(app, _os.path.join(tmp, 'out.csv')))
            assert r['off_ok'] is off_ok, (name, r)
            if says is None:
                assert r['error'] is None, (name, r)
            else:
                assert says in r['error'], (name, r)
            assert (('outp', 1) in app.sg.timeline) is read, (
                name, app.sg.timeline)


def test_an_earlier_error_is_kept_when_the_off_reads_on_too():
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sg.read_fail = lambda n: n == 2
        app.sg.outp_says_on = True
        r = _final(_run_worker(app, _os.path.join(tmp, 'out.csv')))
        assert r['off_ok'] is False, r
        assert r['error'] == 'BSWV? read-back timed out', r


def test_an_unconfirmed_off_raises_one_alarm_and_forces_the_button_on():
    cases = [  # (name, switches, out_btn, quoted in the alarm)
        ('reads ON', {'outp_says_on': True}, [(1, True), (1, True)],
         'still reads ON'),
        ('OUTP? raises', {'outp_fail': True}, [(1, True), (1, True)],
         'OUTP? timed out'),
        ('the OFF raises', {'fail': _second_off_fails()},
         [(1, True), (1, True)], 'VISA timeout on set_output'),
        # never switched ON (point 1 gate), and still forced ON: the ON
        # may have landed even when its confirmation never came back
        ('point 1 refused', {'clamp_amp': 0.5, 'outp_says_on': True},
         [(1, True)], 'point 1 read back as'),
    ]
    for name, switches, out_btn, quoted in cases:
        with _tmpdir() as tmp:
            app = _App(tmp)
            for k, v in switches.items():
                setattr(app.sg, k, v)
            _run_worker(app, _os.path.join(tmp, 'out.csv'), drain=False)
            mb = _finish(app)
            [(kind, title, msg, kw)] = mb.calls
            assert (kind, title) == ('showerror', 'SG CH1 NOT SWITCHED OFF'), \
                (name, mb.calls)
            assert 'could not confirm SG CH1 is off' in msg, msg
            assert quoted in msg and 'front panel' in msg, (name, msg)
            assert msg.endswith('then press Read Instrument on the Channel '
                                '1 tab.'), msg
            # no read of the box: a stale reply could read OFF and turn
            # the alarm's red button back to OFF
            assert app.bg == [] and app.bg_refused == [], (name, app.bg)
            assert app.root.pending == [], app.root.pending
            assert app.out_btn == out_btn, (name, app.out_btn)
            assert app.sg_channel_widgets[1]['output'].get() is True, name
            assert 'NOT confirmed off' in app.sgsw_status.text, name
            assert app.sgsw_status.fg == uc.TEXT_ALERT
            assert app.status_bar.text == app.sgsw_status.text
            assert app._sg_sweep_ch is None and not app.sg_sweeping
            assert app.ui_state == [False], app.ui_state


def test_the_alarm_comes_first_and_survives_a_panel_that_fails():
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sg.outp_says_on = True
        _run_worker(app, _os.path.join(tmp, 'out.csv'), drain=False)
        mb = _finish(app, _MB(log=app.order))
        assert app.order == [('box', 'SG CH1 NOT SWITCHED OFF'),
                             ('ui_state', False), ('panel', 1)], app.order
        assert len(mb.calls) == 1, mb.calls
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sg.outp_says_on = True
        app.ui_state_raises = True
        _run_worker(app, _os.path.join(tmp, 'out.csv'), drain=False)
        mb = _finish(app)
        assert mb.kinds_titles() == [('showerror', 'SG CH1 NOT SWITCHED OFF')]
        assert app._sg_sweep_ch is None and not app.sg_sweeping
        assert app.out_btn[-1] == (1, True), app.out_btn
        assert 'NOT confirmed off' in app.sgsw_status.text
        assert 'Updating the CH1 panel failed: widget gone' in \
            app.status_bar.text, app.status_bar.text
    # a confirmed OFF whose panel update fails still reads the box back
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.ui_state_raises = True
        _run_worker(app, _os.path.join(tmp, 'out.csv'), drain=False)
        mb = _finish(app)
        assert mb.calls == [], mb.calls
        assert app.out_btn == [(1, True), (1, False)], app.out_btn
        assert 'Updating the CH1 panel failed' in app.status_bar.text
        assert app.bg == [('sg-io', True)], "the read-back was skipped"


# --------------------------------------------------------------------------
# The last event, on the Tk side
# --------------------------------------------------------------------------

def test_a_clean_finish_turns_the_button_off_and_fills_the_panel():
    with _tmpdir() as tmp:
        app = _App(tmp)
        _run_worker(app, _os.path.join(tmp, 'out.csv'), ch=2,
                    wave='SQUARE', duty=30.0, drain=False)
        mb = _finish(app)
        assert mb.calls == [], mb.calls
        assert app.out_btn == [(2, True), (2, False)], app.out_btn
        w = app.sg_channel_widgets[2]
        assert w['output'].get() is False
        assert (w['waveform'].get(), w['freq'].get(), w['amp'].get(),
                w['offset'].get(), w['duty'].get()) == (
            'SQUARE', '10', '2', '1', '30'), w
        other = app.sg_channel_widgets[1]
        assert (other['waveform'].get(), other['freq'].get()) == ('DC',
                                                                  '1000')
        assert app._sg_sweep_ch is None and not app.sg_sweeping
        assert app.ui_state == [False], app.ui_state
        text = app.sgsw_status.text
        assert '4/4 points' in text and 'every read-back matches' in text, \
            text
        assert 'Output OFF.' in text and app.sgsw_status.fg == uc.TEXT_OK
        assert app.status_bar.text == text
        assert app.sgsw_progress.cfg.get('value') == 4, app.sgsw_progress.cfg
        # then the panel is read back from the box, quietly
        assert app.bg == [('sg-io', True)], app.bg
        assert app.populated == [(2, {'fetched': 2})], app.populated
        assert app.sg.timeline == _full_timeline(
            2, wave='SQUARE', duty=30.0) + _refresh(2), app.sg.timeline
        assert app.root.pending == [], "polled again after the last event"


def test_the_panel_holds_the_last_point_written_when_stopped_in_its_settle():
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sleep_hook = lambda n: app.sg_stop_sweep() if n == 2 else None
        _run_worker(app, _os.path.join(tmp, 'out.csv'), drain=False)
        mb = _finish(app)
        assert mb.calls == [], mb.calls
        w = app.sg_channel_widgets[1]
        assert (w['waveform'].get(), w['freq'].get(), w['amp'].get(),
                w['offset'].get()) == ('SINE', '10', '1', '0.5'), w
        assert w['duty'].get() == '50', "duty written for a SINE sweep"
        assert app.out_btn == [(1, True), (1, False)], app.out_btn
        assert 'Stopped; output OFF.' in app.sgsw_status.text


def test_read_back_mismatches_reach_the_status_line():
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sg.clamp_amp = 1.5                   # both 2 Vpp points clamp
        r = _final(_run_worker(app, _os.path.join(tmp, 'out.csv')))
        assert (r['done'], r['mismatches'], r['error']) == (4, 2, None), r
        app.sg_sweep_queue.put(('final', r))
        mb = _finish(app)
        assert mb.calls == [], mb.calls
        assert '2 read-back(s) differ' in app.sgsw_status.text, \
            app.sgsw_status.text
        assert app.sgsw_status.fg == uc.TEXT_ALERT


def test_an_error_shows_one_error_box_and_switches_the_button_off():
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sg.read_fail = lambda n: n == 3
        _run_worker(app, _os.path.join(tmp, 'out.csv'), drain=False)
        mb = _finish(app)
        assert mb.kinds_titles() == [('showerror', 'SG sweep error')], \
            mb.calls
        assert app.out_btn == [(1, True), (1, False)], app.out_btn
        assert 'Stopped by an error' in app.sgsw_status.text


def test_the_drain_polls_again_until_the_final_event():
    app = _App()
    _claim(app, 1)
    app.sg_sweep_queue.put(('on', 1))
    app.sg_sweep_queue.put(('point', 1, 4, POINTS[0], True))
    mb = _finish(app)
    assert mb.calls == []
    assert app.root.pending == [(50, app._drain_sg_sweep_queue, ())], \
        app.root.pending
    assert app.out_btn == [(1, True)]
    assert app.sg_channel_widgets[1]['output'].get() is True
    assert app.sgsw_progress.cfg.get('value') == 1
    assert app.sgsw_status.text.startswith('Point 1/4'), app.sgsw_status.text
    assert app._sg_sweep_ch == 1 and app.sg_sweeping, "released too early"


# --------------------------------------------------------------------------
# The read of the box after a sweep
# --------------------------------------------------------------------------

def test_the_read_after_a_sweep_is_drained_and_echo_checked_under_the_lock():
    app = _App()
    app.sg.state[1] = {'WVTP': 'SINE', 'FRQ': 10.0, 'AMP': 2.0, 'OFST': 1.0}
    app._sg_sweep_refresh(1)
    assert app.sg.timeline == _refresh(1), app.sg.timeline
    assert app.sg.drain_owned == [True] and app.sg.read_owned == [True,
                                                                  True]
    assert app.sg.read_kw == [True] and app.sg.outp_kw == [True]
    # what the box said is what the panel is filled from
    [(ch, bswv, outp)] = app.fetch_args
    assert ch == 1 and bswv == app.sg.state[1], bswv
    assert outp['state'] is False, outp
    assert app.populated == [(1, {'fetched': 1})], app.populated
    # a reply that is not its own is refused and said, not shown
    for switch, value in (('bswv_head', lambda n, ch: 'C2:BSWV'),
                          ('outp_head', 'C1:BSWV')):
        app = _App()
        app._sgsw_msg = 'MSG.'
        setattr(app.sg, switch, value)
        app._sg_sweep_refresh(1)
        assert app.populated == [] and app.fetch_args == [], switch
        assert 'CH1 was not read back (' in app.sgsw_status.text
        assert 'not its own' in app.sgsw_status.text, app.sgsw_status.text


def test_the_read_after_a_sweep_waits_for_a_busy_signal_gen():
    app = _App()
    app.bg_refuse = 3
    app._sg_sweep_refresh(1)
    assert app.root.pending == [(500, app._sg_sweep_refresh, (1, 19))], \
        app.root.pending
    assert app.sg.timeline == [], "read the box while it was busy"
    app.root.run_pending()
    assert app.bg_refused == [('sg-io', True)] * 3, app.bg_refused
    assert app.bg == [('sg-io', True)], app.bg
    assert app.populated == [(1, {'fetched': 1})], app.populated
    assert app.sg.timeline == _refresh(1), app.sg.timeline
    assert app.sgsw_status.text is None, app.sgsw_status.text


def test_a_read_that_never_gets_its_turn_is_said_on_the_status_line():
    app = _App()
    app._sgsw_msg = 'SG sweep CH2: 4/4 points.'
    app.bg_refuse = 10 ** 6
    app._sg_sweep_refresh(2)
    app.root.run_pending()
    assert len(app.bg_refused) == 21, len(app.bg_refused)   # 1 + 20 retries
    assert app.root.played == 20 and app.root.pending == []
    assert app.bg == [] and app.populated == []
    text = app.sgsw_status.text
    assert text.startswith('SG sweep CH2: 4/4 points.'), text
    assert 'CH2 was not read back (another Signal Gen command kept it busy)' \
        in text, text
    assert 'Read Instrument before Output ON' in text, text
    assert app.sgsw_status.fg == uc.TEXT_ALERT


def test_a_read_after_a_sweep_that_fails_is_said_on_the_status_line():
    app = _App()
    app._sgsw_msg = 'MSG.'
    app.fetch_error = IOError('BSWV? timed out')
    app._sg_sweep_refresh(1)
    assert app.populated == [] and app.root.pending == []
    assert 'CH1 was not read back (BSWV? timed out)' in app.sgsw_status.text
    assert app.sgsw_status.fg == uc.TEXT_ALERT


# --------------------------------------------------------------------------
# The CSV
# --------------------------------------------------------------------------

def test_the_csv_has_one_row_per_point_asked_and_read_back():
    stamp = _re.compile(r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}$')
    for wave, duty in (('SINE', None), ('SQUARE', 30.0)):
        with _tmpdir() as tmp:
            app = _App(tmp)
            path = _os.path.join(tmp, 'out.csv')
            app.sg.clamp_amp = 1.5
            r = _final(_run_worker(app, path, ch=2, wave=wave, duty=duty))
            assert r['mismatches'] == 2, r
            rows = _rows(path)
            assert rows[0] == list(gui.SG_SWEEP_CSV_HEADER), rows[0]
            assert len(rows) == 1 + len(POINTS), rows
            for n, (row, (f, a, o)) in enumerate(zip(rows[1:], POINTS), 1):
                assert len(row) == len(gui.SG_SWEEP_CSV_HEADER), row
                assert stamp.match(row[0]), row
                assert row[1:4] == [str(n), '2', wave], row
                if duty is None:
                    assert row[4] == '', row
                else:
                    assert float(row[4]) == duty, row
                asked = [float(x) for x in row[5:10]]
                assert asked == [f, a, o, o - a / 2.0, o + a / 2.0], row
                got = [float(x) for x in row[10:13]]
                assert got == [f, min(a, 1.5), o], row
                assert row[13] == ('yes' if a <= 1.5 else 'no'), row


# --------------------------------------------------------------------------
# _sg_sweep_locked
# --------------------------------------------------------------------------

def test_the_lock_is_off_with_no_sweep():
    with _patched(_MB()) as mb:
        app = _App()
        assert not any(app._sg_sweep_locked(c) for c in (None, 1, 2))
        assert not app._sg_sweep_locked(1, stop=True)
        assert mb.calls == []


def test_the_lock_names_the_sweeps_channel_and_only_that_channel():
    with _patched(_MB()) as mb:
        app = _App()
        _claim(app, 1)
        assert app._sg_sweep_locked(2) is False and mb.calls == []
        assert app._sg_sweep_locked(1) is True
        _warned(mb, 1)
        assert app.sg_sweeping, "a warning must not stop the sweep"
    with _patched(_MB()) as mb:
        app = _App()
        _claim(app, 2)
        window = object()
        assert app._sg_sweep_locked(2, parent=window) is True
        _warned(mb, 2, parent=window)


def test_no_channel_means_any_channel():
    for owner in (1, 2):
        with _patched(_MB()) as mb:
            app = _App()
            _claim(app, owner)
            assert app._sg_sweep_locked() is True
            _warned(mb, owner)


def test_stop_true_stops_the_sweep_with_no_box():
    with _patched(_MB()) as mb:
        app = _App()
        tok = _claim(app, 1)
        assert app._sg_sweep_locked(1, stop=True) is True
        assert mb.calls == [], mb.calls
        assert app.sg_sweeping is False and app._sg_sweep_gen is not tok
        assert app._sg_sweep_ch == 1, "released before the worker's OFF"
        assert 'the sweep is stopping' in app.status_bar.text
        # another click on the other channel is not a stop
        app.sg_sweeping = True
        assert app._sg_sweep_locked(2, stop=True) is False
        assert app.sg_sweeping is True


def test_a_sweep_that_is_still_stopping_still_locks():
    with _patched(_MB()) as mb:
        app = _App()
        _claim(app, 1)
        app.sg_sweeping = False                  # Stop pressed, worker busy
        assert app._sg_sweep_locked(1) is True
        _warned(mb, 1, state='is still stopping its sweep')
        mb.calls.clear()
        assert app._sg_sweep_locked(1, stop=True) is True
        assert mb.calls == []


# --------------------------------------------------------------------------
# Every other writer of the channel, while the sweep owns it
# --------------------------------------------------------------------------

def test_apply_refuses_the_sweeps_channel_and_a_preset_chain_moves_on():
    with _patched(_MB()) as mb:
        app = _App()
        _claim(app, 1)
        app.apply_sg_channel(1)
        assert app.sg.writes == [] and app.bg == [], app.sg.writes
        _warned(mb, 1)
        mb.calls.clear()
        app.apply_sg_channel(1, _then=lambda: app.apply_sg_channel(2))
        assert app.sg.channels() == {2}, app.sg.writes
        assert ('set_basic_wave', 2, {'WVTP': 'DC', 'OFST': 0.5}) \
            in app.sg.writes, app.sg.writes
        _warned(mb, 1)


def test_fire_refuses_the_sweeps_channel_and_the_other_still_fires():
    with _patched(_MB()) as mb:
        app = _App()
        _claim(app, 1)
        app.sg_fire_burst(1)
        assert app.sg.writes == [] and app.bg == [], app.sg.writes
        _warned(mb, 1)
        mb.calls.clear()
        app.sg_fire_burst(2)
        assert app.sg.writes == [('burst_trigger', 2)], app.sg.writes
        assert mb.calls == []


def test_the_editor_upload_refuses_the_sweeps_channel():
    with _patched(_MB()) as mb:
        app = _App()
        _claim(app, 1)
        ed = L._Editor(app, channel=2, target=1)
        ed.upload()
        assert app.sg.writes == [] and app.library == [], app.sg.writes
        _warned(mb, 1, parent=ed)
        assert app.sg_channel_widgets[1]['waveform'].get() == 'DC'
        assert ed._dirty
        mb.calls.clear()
        L._Editor(app, channel=1, target=2).upload()
        assert mb.calls == [], mb.calls
        assert [w[0] for w in app.sg.writes] == [
            'upload_arb', 'select_arb', 'set_sample_rate',
            'set_basic_wave'], app.sg.writes
        assert app.sg.channels() == {2}, app.sg.writes


def test_the_output_button_on_the_sweeps_channel_means_stop():
    with _patched(_MB({'Enable SG output': True})) as mb:
        app = _App()
        tok = _claim(app, 1)
        app.sg_channel_widgets[1]['output'].set(True)    # the sweep's ON
        app.sg_toggle_output(1)
        assert mb.calls == [], mb.calls
        assert app.sg.writes == [] and app.bg == [], app.sg.writes
        assert app.sg_sweeping is False and app._sg_sweep_gen is not tok
        assert app._sg_sweep_ch == 1
        assert app.sg_channel_widgets[1]['output'].get() is True, \
            "the button flipped before the worker's OFF"
        app.sg_toggle_output(1)                  # again, while stopping
        assert mb.calls == [] and app.sg.writes == []
        app.sg_toggle_output(2)
        assert [c[1] for c in mb.calls] == ['Enable SG output'], mb.calls
        assert app.sg.writes == [('set_output', 2, True)], app.sg.writes


def test_reconnect_is_refused_while_a_sweep_owns_either_channel():
    """Reconnect closes the handle both channels share, and only the
    worker switches its channel OFF at the end."""
    for owner in (1, 2):
        with _patched(_MB()) as mb:
            app = _App()
            _claim(app, owner)
            sg, opened = app.sg, []
            app._reconnect('sg', lambda: opened.append(1), app.sg_status)
            assert app.sg is sg and not sg.closed and opened == []
            assert app.bg == [] and app.sg_status.text is None, app.bg
            _warned(mb, owner)
            assert app.sg_sweeping, "Reconnect must not stop the sweep"


def test_the_webcam_sweep_and_timed_trigger_refuse_the_sweeps_channel():
    """Refused before the preview is stopped or the camera is touched;
    the other channel still starts."""
    with _tempfile.TemporaryDirectory() as tmp, T._patched(T._MB()) as mb:
        app = T._App(tmp)
        app._sg_sweep_ch, app.sg_sweeping = 1, True
        app.cam_sg_ch = T._var('1')
        app._cam_start_sequence()
        app.cam_tm_trigger = T._var('CH1 burst trigger')
        app._cam_start_timed()
        assert mb.titles() == [SWEEP_LOCK, SWEEP_LOCK], mb.calls
        assert all('SG CH1 is being stepped' in c[2] for c in mb.calls)
        assert app.events == [], "the camera was touched before refusing"
        assert app.cam_seq_thread is None and not app.cam_seq_running
        assert app.sg.writes == [], app.sg.writes
        # the other channel
        app.cam_sg_ch = T._var('2')
        app._cam_start_sequence()
        assert (app._cam_seq_kind, app._cam_seq_ch) == ('sweep', 2)
        app.cam_seq_thread.join(5)
        app.cam_seq_running = False              # as the drain would
        app.cam_tm_trigger = T._var('CH2 burst trigger')
        app._cam_start_timed()
        app.cam_seq_thread.join(5)
        assert mb.titles() == [SWEEP_LOCK, SWEEP_LOCK], mb.calls
        assert {w[2] for w in app.sg.writes} == {2}, app.sg.writes
        assert ('burst_trigger', 2) in [w[1:3] for w in app.sg.writes]


# --------------------------------------------------------------------------
# Start Sweep
# --------------------------------------------------------------------------

def _start(app, mb, threads=None):
    threads = _Threads() if threads is None else threads
    with _patched(mb, threads):
        app.sg_start_sweep()
    return threads


def _not_started(app, threads):
    assert app._sg_sweep_ch is None and not app.sg_sweeping
    assert threads.made == [], "a worker was started"
    assert app.ui_state == [] and app.root.pending == []
    assert app.sg.writes == [], app.sg.writes


def _refused_with(app, mb, threads, says):
    """One error box, the plan refused for `says`, nothing started."""
    [(kind, title, msg, _)] = mb.calls
    assert (kind, title) == ('showerror', BAD), mb.calls
    assert says in msg, (says, msg)
    _not_started(app, threads)


def test_start_is_refused_with_no_signal_generator():
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sg = None
        mb = _MB()
        threads = _start(app, mb)
        assert mb.kinds_titles() == [('showerror', 'SG sweep')], mb.calls
        assert 'not connected' in mb.calls[0][2]
        assert app._sg_sweep_ch is None and threads.made == []


def test_start_does_nothing_while_a_sweep_owns_a_channel():
    for sweeping in (True, False):               # running, or stopping
        with _tmpdir() as tmp:
            app = _App(tmp)
            tok = _claim(app, 2)
            app.sg_sweeping = sweeping
            mb = _MB()
            threads = _start(app, mb)
            assert mb.calls == [] and threads.made == [], mb.calls
            assert app._sg_sweep_ch == 2 and app._sg_sweep_gen is tok
            assert app.sg_sweeping is sweeping
            # and the check Start asks (again after its dialog) says why
            with _patched(mb):
                assert app._sg_sweep_start_refused(1) is True
            [(kind, title, msg, _)] = mb.calls
            assert (kind, title) == ('showinfo', 'SG sweep'), mb.calls
            assert 'SG CH2 is still ' + ('running' if sweeping
                                         else 'stopping') in msg, msg


def test_start_is_refused_on_the_live_runs_channel():
    with _tmpdir() as tmp:
        app = _App(tmp)
        app._sldea_live_ch = 1
        mb = _MB()
        threads = _start(app, mb)
        assert mb.kinds_titles() == [('showwarning', LIVE_LOCK)], mb.calls
        _not_started(app, threads)
    with _tmpdir() as tmp:                       # the other channel asks
        app = _App(tmp)
        app._sldea_live_ch = 2
        mb = _MB({START_Q: False})
        threads = _start(app, mb)
        assert mb.kinds_titles() == [('askyesno', START_Q)], mb.calls
        _not_started(app, threads)


def test_start_is_refused_on_the_channel_a_dry_run_is_set_to():
    """The other order of the run gate's DRY refusal (owner 2026-10-27): a
    DRY run writes no SG channel, but a sweep on the one it is set to
    would energize the Trek, so the run would not be dry. Refused before
    the dialog; the other channel still sweeps."""
    with _tmpdir() as tmp:
        app = _App(tmp)
        app._sldea_dry_ch = 1
        mb = _MB()
        threads = _start(app, mb)
        [(kind, title, msg, kw)] = mb.calls
        assert (kind, title, kw) == ('showwarning', 'SG sweep', {}), mb.calls
        assert 'DRY run' in msg and 'SG CH1' in msg, msg
        assert 'would not be dry' in msg, msg
        _not_started(app, threads)
    with _tmpdir() as tmp:
        app = _App(tmp)
        app._sldea_dry_ch = 1
        app.sgsw_ch.set('2')
        mb = _MB({START_Q: True})
        threads = _start(app, mb)
        assert mb.kinds_titles() == [('askyesno', START_Q)], mb.calls
        assert app._sg_sweep_ch == 2 and app.sg_sweeping
        [t] = threads.made
        assert t.started and t.args[0] == 2, t.args


def test_start_is_refused_beside_a_webcam_sweep_on_its_channel():
    for cam_ch, refused in ((1, True), (2, False)):
        with _tmpdir() as tmp:
            app = _App(tmp)
            app.cam_seq_thread = _types.SimpleNamespace(is_alive=lambda: True)
            app._cam_seq_kind, app._cam_seq_ch = 'sweep', cam_ch
            mb = _MB({START_Q: False})
            threads = _start(app, mb)
            if refused:
                [(kind, title, msg, _)] = mb.calls
                assert (kind, title) == ('showwarning', 'SG sweep'), mb.calls
                assert "Webcam tab's stepped capture is writing SG CH1" \
                    in msg, msg
            else:
                assert mb.kinds_titles() == [('askyesno', START_Q)], mb.calls
            _not_started(app, threads)


def test_start_is_refused_while_a_signal_gen_command_is_in_flight():
    with _tmpdir() as tmp:
        app = _App(tmp)
        app._bg_busy.add('sg-io')
        mb = _MB()
        threads = _start(app, mb)
        assert mb.kinds_titles() == [('showinfo', 'SG sweep')], mb.calls
        assert 'still being sent' in mb.calls[0][2]
        _not_started(app, threads)


def test_start_is_refused_unless_the_load_is_high_z_and_polarity_nor():
    """The volts are checked against the High-Z limit, and whether INVT
    also inverts the offset is not bench-checked (adversarial review,
    2026-10-27), so the sweep runs at High-Z / NOR only."""
    for ch in (1, 2):
        for load in ('50', '1000', '10000'):
            with _tmpdir() as tmp:
                app = _App(tmp)
                app.sgsw_ch.set(str(ch))
                app.sg_channel_widgets[ch]['load'].set(load)
                mb = _MB()
                threads = _start(app, mb)
                _refused_with(app, mb, threads,
                              f"only with CH{ch}'s Load at High-Z")
        with _tmpdir() as tmp:
            app = _App(tmp)
            app.sgsw_ch.set(str(ch))
            app.sg_channel_widgets[ch]['polarity'].set('INVT')
            mb = _MB()
            threads = _start(app, mb)
            _refused_with(app, mb, threads,
                          f"only with CH{ch}'s Polarity at NOR")
    # the other channel's settings do not matter
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sg_channel_widgets[2]['load'].set('50')
        app.sg_channel_widgets[2]['polarity'].set('INVT')
        mb = _MB({START_Q: False})
        threads = _start(app, mb)
        assert mb.kinds_titles() == [('askyesno', START_Q)], mb.calls
        _not_started(app, threads)


def test_start_is_refused_beyond_ten_volts():
    cases = [  # (amplitudes, unipolar, offset, refused, says)
        ('25', True, '0', True, '0 V to 25 V'),
        ('20.5', True, '0', True, '0 V to 20.5 V'),
        ('20', False, '0.5', True, '-9.5 V to 10.5 V'),
        ('20', False, '-0.5', True, '-10.5 V to 9.5 V'),
        ('20', False, '0', False, None),                 # exactly +/-10 V
        ('10', True, '0', False, None),                  # 0 V to 10 V
    ]
    for amps, unipolar, offset, refused, says in cases:
        with _tmpdir() as tmp:
            app = _App(tmp)
            app.sw_sgamp_list_var.set(amps)
            app.sgsw_unipolar.set(unipolar)
            app.sgsw_offset.set(offset)
            mb = _MB({START_Q: False})
            threads = _start(app, mb)
            if refused:
                _refused_with(app, mb, threads, says)
                assert 'High-Z' in mb.calls[0][2], mb.calls
            else:
                assert mb.kinds_titles() == [('askyesno', START_Q)], \
                    (amps, mb.calls)
                _not_started(app, threads)


def test_start_is_refused_beyond_the_point_cap():
    cap = gui.SG_SWEEP_MAX_POINTS
    assert cap == 10000, cap
    # one axis in Range mode: refused on its Points field, before planning
    for axis, name in (('sgfreq', 'Frequency'), ('sgamp', 'Amplitude')):
        with _tmpdir() as tmp:
            app = _App(tmp)
            getattr(app, f'sw_{axis}_mode').set('range')
            getattr(app, f'sw_{axis}_points_entry').set(str(cap + 1))
            mb = _MB()
            threads = _start(app, mb)
            _refused_with(app, mb, threads,
                          f"{name} points must be at most {cap}")
            assert app.parsed == [], "the axis was planned before the cap"
    # in all: 101 x 100 in Range mode, and 10001 x 1 in List mode
    with _tmpdir() as tmp:
        app = _App(tmp)
        for attr, val in (('sw_sgfreq_mode', 'range'),
                          ('sw_sgfreq_start_entry', '1'),
                          ('sw_sgfreq_stop_entry', '101'),
                          ('sw_sgfreq_points_entry', '101'),
                          ('sw_sgamp_mode', 'range'),
                          ('sw_sgamp_start_entry', '0.1'),
                          ('sw_sgamp_stop_entry', '10'),
                          ('sw_sgamp_points_entry', '100')):
            getattr(app, attr).set(val)
        mb = _MB({START_Q: False})
        threads = _start(app, mb)
        _refused_with(app, mb, threads,
                      f"101 × 100 points is more than the {cap}")
        # 100 x 100 is exactly the cap: asked about
        app.sw_sgfreq_points_entry.set('100')
        mb = _MB({START_Q: False})
        threads = _start(app, mb)
        assert mb.kinds_titles() == [('askyesno', START_Q)], mb.calls
        assert '10000 points' in mb.calls[0][2], mb.calls[0][2]
        _not_started(app, threads)
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sw_sgfreq_list_var.set(','.join(str(i) for i in
                                            range(1, cap + 2)))
        app.sw_sgamp_list_var.set('1')
        mb = _MB()
        threads = _start(app, mb)
        _refused_with(app, mb, threads,
                      f"{cap + 1} × 1 points is more than the {cap}")


def test_start_is_refused_on_bad_fields():
    cases = [
        ('sw_sgfreq_list_var', '0', 'Every frequency must be above 0 Hz'),
        ('sw_sgfreq_list_var', '10, -1', 'Frequency value -1.0 is outside'),
        ('sw_sgamp_list_var', '1, nan', 'Amplitude value nan is outside'),
        ('sw_sgamp_list_var', '0', 'Every amplitude must be above 0 Vpp'),
        ('sgsw_duty', '150', 'Duty must be between 0 and 100'),
        ('sgsw_duty', 'nan', 'Duty must be between 0 and 100'),
        ('sgsw_dwell', '-1', 'Dwell must be 0 s or more'),
        ('sgsw_dwell', 'nan', 'Dwell must be 0 s or more'),
        ('sgsw_dwell', 'inf', 'Dwell must be 0 s or more'),
        ('sgsw_offset', 'nan', 'Offset must be a number'),
        ('sgsw_order', 'sideways', 'Order must be one of'),
    ]
    for attr, value, says in cases:
        with _tmpdir() as tmp:
            app = _App(tmp)
            app.sgsw_wave.set('SQUARE')          # so the duty is read
            app.sgsw_unipolar.set(attr != 'sgsw_offset')
            getattr(app, attr).set(value)
            mb = _MB()
            threads = _start(app, mb)
            _refused_with(app, mb, threads, says)


def test_start_asks_once_with_no_as_the_default_and_no_means_no():
    with _tmpdir() as tmp:
        app = _App(tmp)
        mb = _MB({START_Q: False})
        threads = _start(app, mb)
        [(kind, title, _msg, kw)] = mb.calls
        assert (kind, title) == ('askyesno', START_Q)
        assert kw == {'default': 'no'}, kw
        _not_started(app, threads)
        assert not _os.path.exists(app.sgsw_output.get()), "CSV created"


def test_a_refusal_that_arrives_during_the_dialog_still_refuses():
    """The dialog yields to Tk; whatever the first check refused for may
    have started by the time Yes is pressed."""
    def busy(app):
        app._bg_busy.add('sg-io')
        return True

    def live(app):
        app._sldea_live_ch = 1
        return True

    def dry(app):
        app._sldea_dry_ch = 1
        return True

    for during, then in ((busy, ('showinfo', 'SG sweep')),
                         (live, ('showwarning', LIVE_LOCK)),
                         (dry, ('showwarning', 'SG sweep'))):
        with _tmpdir() as tmp:
            app = _App(tmp)
            mb = _MB({START_Q: lambda: during(app)})
            threads = _start(app, mb)
            assert mb.kinds_titles() == [('askyesno', START_Q), then], \
                mb.calls
            _not_started(app, threads)


def test_a_start_claims_the_channel_and_hands_the_plan_to_the_worker():
    cases = [  # (ch, unipolar, offset, extremes)
        (2, True, '0', 'Lowest 0 V, highest 2 V'),
        (1, False, '-0.5', 'Lowest -1.5 V, highest 0.5 V'),
    ]
    for ch, uni, offset, extremes in cases:
        with _tmpdir() as tmp:
            app = _App(tmp)
            app.sgsw_ch.set(str(ch))
            app.sgsw_unipolar.set(uni)
            app.sgsw_offset.set(offset)
            path = app.sgsw_output.get()
            mb = _MB({START_Q: True})
            threads = _start(app, mb)
            # the one question, and what it says
            [(kind, title, msg, kw)] = mb.calls
            assert (kind, title, kw) == ('askyesno', START_Q,
                                         {'default': 'no'}), mb.calls
            for part in (f'Sweep SG CH{ch}:', '4 points', extremes,
                         'Load High-Z, polarity NOR', '1 V = 1 kV',
                         "bench's Trek inverts", 'minus kV',
                         f'switches CH{ch} OFF, sets point 1, reads it back',
                         f'switches CH{ch} ON only if it matches'):
                assert part in msg, (part, msg)
            # the claim, and the worker it started
            assert app._sg_sweep_ch == ch and app.sg_sweeping is True
            [t] = threads.made
            assert t.started and t.daemon is True
            assert t.target == app._sg_sweep_worker, t.target
            points = sweep_plan.sg_points(
                [1.0, 10.0], [1.0, 2.0], sweep_plan.SG_ORDER_AMP_OUTER,
                uni, float(offset))
            assert t.args == (ch, 'SINE', None, points, 0.0, 'HZ', 'NOR',
                              path, app._sg_sweep_gen), t.args
            assert app.ui_state == [True], app.ui_state
            assert app.root.pending == [(50, app._drain_sg_sweep_queue, ())]
            assert app.sgsw_progress.cfg == {'maximum': 4, 'value': 0}
            assert app.sg.writes == [], "Start wrote before the worker"
            # and run it: the worker, then the drain the start scheduled
            with _patched(_MB()) as mb2:
                t.target(*t.args)
                app._drain_sg_sweep_queue()
            assert mb2.calls == [], mb2.calls
            assert app.sg.timeline == _full_timeline(ch, points=points) + \
                _refresh(ch), app.sg.timeline
            assert len(_rows(path)) == 5, _rows(path)
            assert app._sg_sweep_ch is None and not app.sg_sweeping
            assert app.out_btn == [(ch, True), (ch, False)], app.out_btn


def test_a_start_that_cannot_start_its_worker_gives_the_channel_back():
    """With no worker no last event would ever release the channel, and
    with it Reconnect, Restart and the SLDEA run gate."""
    with _tmpdir() as tmp:
        app = _App(tmp)
        mb = _MB({START_Q: True})
        threads = _start(app, mb, _Threads(fail_start=True))
        assert mb.kinds_titles() == [('askyesno', START_Q),
                                     ('showerror', 'SG sweep')], mb.calls
        assert "could not start: can't start new thread" in mb.calls[1][2]
        assert app._sg_sweep_ch is None and not app.sg_sweeping
        assert app.ui_state == [True, False], app.ui_state
        assert len(threads.made) == 1 and not threads.made[0].started
        assert app.root.pending == [], "a drain was scheduled for no worker"
        assert app.sg.writes == []
        # nothing is left locked
        with _patched(_MB()) as mb2:
            assert app._sg_sweep_locked() is False
            assert app._sg_sweep_blocks('restart') is False
        assert mb2.calls == []


def test_a_log_folder_that_cannot_be_made_is_said_before_any_claim():
    with _tmpdir() as tmp:
        app = _App(tmp)
        blocker = _os.path.join(tmp, 'a_file')
        with open(blocker, 'w') as f:
            f.write('x')
        app.log_dir.set(_os.path.join(blocker, 'logs'))
        app.sgsw_output.set('')
        mb = _MB({START_Q: True})
        threads = _start(app, mb)
        assert mb.kinds_titles() == [('askyesno', START_Q),
                                     ('showerror', 'SG sweep')], mb.calls
        assert 'Could not make the log folder' in mb.calls[1][2]
        _not_started(app, threads)


def test_a_blank_output_path_goes_to_the_log_folder():
    with _tmpdir() as tmp:
        app = _App(tmp)
        app.sgsw_output.set('  ')
        threads = _start(app, _MB({START_Q: True}))
        path = app.sgsw_output.get()
        assert _os.path.dirname(path) == tmp, path
        assert _re.match(r'^sg_sweep_\d{8}_\d{6}\.csv$',
                         _os.path.basename(path)), path
        [t] = threads.made
        assert t.args[7] == path, t.args


# --------------------------------------------------------------------------
# The sweep box's inputs, locked while it runs (the real _sg_sweep_ui_state)
# --------------------------------------------------------------------------

class _UiApp:
    _sg_sweep_ui_state = G._sg_sweep_ui_state
    _sg_sweep_field_state = G._sg_sweep_field_state

    def __init__(self):
        self.mode_updates = []
        self._sg_sweep_ch = None
        for axis in ('sgfreq', 'sgamp'):
            setattr(self, f'sw_{axis}_range_widgets',
                    [_Entry(), _Entry(), _Entry()])
            setattr(self, f'sw_{axis}_list_widget', _Entry())
            setattr(self, f'sw_{axis}_radios', [_Entry(), _Entry()])
        for name in ('sgsw_ch', 'sgsw_wave', 'sgsw_order', 'sgsw_dwell',
                     'sgsw_output_entry', 'sgsw_browse_btn',
                     'sgsw_unipolar_cb', 'sgsw_start_btn', 'sgsw_stop_btn',
                     'sgsw_duty', 'sgsw_offset'):
            setattr(self, name, _Entry())
        self.sgsw_wave.set('SQUARE')
        self.sgsw_unipolar = _Entry(True)

    def _update_sweep_mode_state(self, axis):
        self.mode_updates.append(axis)

    def state(self, name):
        return getattr(self, name).cfg.get('state')


def test_a_running_sweep_locks_every_input_and_gives_them_back():
    app = _UiApp()
    app._sg_sweep_ch = 1
    app._sg_sweep_ui_state(running=True)
    for axis in ('sgfreq', 'sgamp'):
        for w in (getattr(app, f'sw_{axis}_range_widgets')
                  + [getattr(app, f'sw_{axis}_list_widget')]
                  + getattr(app, f'sw_{axis}_radios')):
            assert w.cfg.get('state') == 'disabled', (axis, w.cfg)
    for name in ('sgsw_ch', 'sgsw_wave', 'sgsw_order', 'sgsw_dwell',
                 'sgsw_output_entry', 'sgsw_browse_btn', 'sgsw_unipolar_cb',
                 'sgsw_start_btn', 'sgsw_duty', 'sgsw_offset'):
        assert app.state(name) == 'disabled', name
    assert app.state('sgsw_stop_btn') == 'normal'
    assert app.mode_updates == []
    # idle again
    app._sg_sweep_ch = None
    app._sg_sweep_ui_state(running=False)
    for axis in ('sgfreq', 'sgamp'):
        for w in getattr(app, f'sw_{axis}_radios'):
            assert w.cfg.get('state') == 'normal', (axis, w.cfg)
    for name in ('sgsw_ch', 'sgsw_wave', 'sgsw_order'):
        assert app.state(name) == 'readonly', name
    for name in ('sgsw_dwell', 'sgsw_output_entry', 'sgsw_browse_btn',
                 'sgsw_unipolar_cb', 'sgsw_start_btn', 'sgsw_duty'):
        assert app.state(name) == 'normal', name
    assert app.state('sgsw_stop_btn') == 'disabled'
    assert app.state('sgsw_offset') == 'disabled', "offset with 0 V to Vpp"
    assert app.mode_updates == ['sgfreq', 'sgamp'], app.mode_updates


# --------------------------------------------------------------------------
# _sg_sweep_blocks: Restart now and Update Software
# --------------------------------------------------------------------------

def test_restart_and_update_wait_for_the_sweep():
    for sweeping in (True, False):
        for action, title, then in (
                ('restart', 'Restart refused — SG sweep running',
                 'press Restart now again'),
                ('update', 'Update refused — SG sweep running',
                 'Update Software… again')):
            with _patched(_MB()) as mb:
                app = _App()
                _claim(app, 2)
                app.sg_sweeping = sweeping
                window = object()
                assert app._sg_sweep_blocks(action, parent=window) is True
                [(kind, got, msg, kw)] = mb.calls
                assert (kind, got) == ('showwarning', title), mb.calls
                assert 'owns SG CH2' in msg and 'Stop Sweep' in msg, msg
                assert then in msg, msg
                assert kw == {'parent': window}, kw
                assert app.sg_sweeping is sweeping, "the gate stopped it"
    with _patched(_MB()) as mb:
        app = _App()
        assert app._sg_sweep_blocks('restart') is False
        assert app._sg_sweep_blocks('update') is False
        assert mb.calls == []


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
