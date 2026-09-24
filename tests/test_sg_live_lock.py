#!/usr/bin/env python3
"""Headless tests for the LIVE-run lock on every signal-generator writer
(no hardware, no Tk).

A LIVE SLDEA run owns the SG channel that drives the Trek (1 V = 1 kV at
the DEA). Its loop re-sends the offset only when the commanded kV changes,
so a foreign write to that channel can hold the Trek at the wrong voltage
for a whole landing. `_sg_live_locked` (2026-07-25) guarded Apply, Output
and Reconnect. Two writers skipped it until 2026-09-24: the Signal Gen
tab's Fire button (`sg_fire_burst`) and the Waveform Editor's LAN upload,
which would swap the run's DC drive for an arb. What is pinned here:

* every writer refuses the channel a LIVE run owns, shows the standard
  warning, and sends the instrument nothing;
* the other channel stays usable (user decision 2026-07-25: lock the
  driven channel, leave the other usable), and with no LIVE claim -- no
  run, or a DRY run, which claims nothing -- every writer works;
* `_sldea_finished` releases the claim;
* the Waveform Editor's lock follows its Send-to channel, not the channel
  the editor was opened on;
* an inventory of every SG write in the app modules, per function: a new
  write fails here until someone decides whether the lock applies to it,
  and every writer listed as locked must ask the lock before it writes.

Everything drives the REAL methods on a Tk-free stub app, against a fake
signal generator that records every write. How `sldea_run` makes the
claim, and holds it through the ramp-down and ■ Abort, is the Run gate's
suite's job (tests/test_sldea_interlock.py, PR #334).

Run: .venv/bin/python tests/test_sg_live_lock.py
"""
import ast as _ast
import collections as _collections
import contextlib as _contextlib
import glob as _glob
import os as _os
import sys as _sys
import threading as _threading
import types as _types
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _ROOT)

import arb_editor  # noqa: E402
import gui  # noqa: E402
from instruments import BK4055B  # noqa: E402

G = gui.InstrumentControlGUI
E = arb_editor.ArbWaveformEditor
LOCK = 'Channel in use — LIVE HV run'


class _Var:
    """Tk variable / Entry stand-in: get() and set()."""

    def __init__(self, value=''):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Label:
    def __init__(self):
        self.text = None

    def config(self, text=None, **_kw):
        if text is not None:
            self.text = text


class _FakeSG:
    """BK4055B stand-in. Records every write as (call, channel, args); the
    signatures follow the real driver's."""
    idn = 'FAKE,4055B'
    ARB_DEFAULT_POINTS = 1024

    def __init__(self):
        self.writes = []
        self.closed = False

    def _rec(self, call, channel, *args):
        self.writes.append((call, channel, args))

    def burst_trigger(self, channel):
        self._rec('burst_trigger', channel)

    def set_output(self, channel, on):
        self._rec('set_output', channel, on)

    def set_basic_wave(self, channel, **params):
        self._rec('set_basic_wave', channel, params)

    def select_arb(self, channel, name):
        self._rec('select_arb', channel, name)

    def set_load_polarity(self, channel, load=None, polarity=None):
        self._rec('set_load_polarity', channel, load, polarity)

    def set_burst(self, channel, on, ncycles=1, trigger='MAN',
                  period_s=None):
        self._rec('set_burst', channel, on)

    def set_sync(self, channel, on):
        self._rec('set_sync', channel, on)

    def set_sample_rate(self, channel, mode=None, value=None):
        self._rec('set_sample_rate', channel, mode, value)

    def upload_arb(self, channel, name, samples, freq_hz=None, amp_vpp=None,
                   offset_v=None, phase_deg=None, points=None):
        self._rec('upload_arb', channel, name, amp_vpp, offset_v)
        return name

    def close(self):
        self.closed = True

    def calls(self):
        return [(call, ch) for call, ch, _ in self.writes]


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

    def titles(self):
        return [c[1] for c in self.calls]


def _channel_widgets():
    """One channel's Signal Gen widgets, set up as a plain DC level."""
    return {'waveform': _Var('DC'), 'offset': _Var('0.5'),
            'output': _Var(False), 'load': _Var('HZ'),
            'polarity': _Var('NOR'), 'burst_on': _Var(False),
            'burst_ncyc': _Var('1'), 'burst_trsr': _Var('MAN'),
            'burst_prd': _Var(''), 'sync_on': _Var(False),
            'arb_name_var': _Var(''), 'arb_samples': None,
            'freq': _Var('1000'), 'amp': _Var('1')}


class _App:
    """Just enough app for the Signal Gen writers: the real methods under
    test, stubs for Tk. `_run_bg` runs the job inline and records its busy
    key, so a test reads the outcome rather than racing a thread."""
    _sg_live_locked = G._sg_live_locked
    sg_fire_burst = G.sg_fire_burst
    sg_toggle_output = G.sg_toggle_output
    apply_sg_channel = G.apply_sg_channel
    _sg_load_to_wire = G._sg_load_to_wire
    _reconnect = G._reconnect
    _bg_simple = G._bg_simple
    _sldea_finished = G._sldea_finished

    def __init__(self, live=None):
        self.sg = _FakeSG()
        self._sldea_live_ch = live       # None = no run, or a DRY run
        # what _sldea_finished tidies up when a run ends
        self._sldea_running = live is not None
        self._sldea_loglock = _threading.Lock()
        self._sldea_runlog = self._sldea_prelog = None
        self.sldea_run_btn = self.sldea_abort_btn = _Label()
        self.bg = []
        self.status_bar = _Label()
        self.sg_status = _Label()
        self.sg_channel_widgets = {1: _channel_widgets(),
                                   2: _channel_widgets()}
        self.library = []                # Waveform Editor library saves
        self.sg_presets = _types.SimpleNamespace(
            save_arb=lambda name, samples, recipe=None:
            self.library.append(name))

    def _run_bg(self, work, done, busy=None, quiet=False):
        self.bg.append(busy)
        result = error = None
        try:
            result = work()
        except Exception as e:
            error = e
        done(result, error)
        return True

    def _sg_fetch_channel(self, ch, bswv=None, outp=None):
        return None                      # read-back is not under test

    def _sg_set_output_button(self, ch, on):
        pass

    def _sg_update_visibility(self, ch):
        pass

    def _sg_redraw_preview(self, ch):
        pass

    def _sg_refresh_applied(self, ch):
        pass


class _Editor:
    """Just enough ArbWaveformEditor for upload(): the real upload and the
    real channel staging, on fixed editor state -- no Toplevel."""
    upload = E.upload
    stage_on_channel = E.stage_on_channel
    _set_channel_value = E._set_channel_value

    def __init__(self, app, channel=1, target=None):
        self.app = app
        self.channel = channel           # the channel it was opened on
        self.target_var = _Var(str(channel if target is None else target))
        self.name_entry = _Var('pulse')
        self.samples = [0.0, 1.0, 0.0, -1.0]
        self.recipe = {'total_points': 4}
        self.y_scale = 10.0              # the editor's default full scale
        self._dirty = True
        self.refreshed = 0

    def _duration_s(self):
        return 0.01                      # one period = 10 ms -> 100 Hz

    def _lib_refresh(self):
        self.refreshed += 1


@_contextlib.contextmanager
def _patched(mb):
    """The messagebox stub in both modules (the lock's warning is gui's,
    the editor's own errors are arb_editor's), and the Linux gate opened so
    Reconnect gets as far as the lock on any OS."""
    saved = (gui.messagebox, arb_editor.messagebox,
             gui.INSTRUMENTS_SUPPORTED)
    gui.messagebox = arb_editor.messagebox = mb
    gui.INSTRUMENTS_SUPPORTED = True
    try:
        yield mb
    finally:
        (gui.messagebox, arb_editor.messagebox,
         gui.INSTRUMENTS_SUPPORTED) = saved


def _assert_warned(mb, ch, parent=None):
    """Exactly one dialog: the standard LIVE-lock warning for SG CH`ch`."""
    [(kind, title, msg, kw)] = mb.calls
    assert (kind, title) == ('showwarning', LOCK), mb.calls
    assert f"SG CH{ch} is driving the Trek" in msg, msg
    assert 'the other channel stays available' in msg, msg
    assert kw == ({} if parent is None else {'parent': parent}), kw


# --------------------------------------------------------------------------
# The lock itself
# --------------------------------------------------------------------------

def test_the_lock_names_the_live_channel_and_only_that_channel():
    with _patched(_MB()) as mb:
        app = _App(live=2)
        assert app._sg_live_locked(1) is False and mb.calls == []
        assert app._sg_live_locked(2) is True
        _assert_warned(mb, 2)
    with _patched(_MB()) as mb:
        # no channel = "any channel": what Reconnect asks
        assert _App(live=1)._sg_live_locked() is True
        _assert_warned(mb, 1)
    with _patched(_MB()) as mb:
        app = _App(live=None)            # no run, or a DRY one
        assert not any(app._sg_live_locked(c) for c in (None, 1, 2))
        assert mb.calls == []


def test_the_warning_goes_to_the_window_that_asked():
    """The editor passes itself, as its own dialogs do; every other caller
    passes nothing and gets the root-parented warning it always had."""
    with _patched(_MB()) as mb:
        editor_window = object()
        assert _App(live=1)._sg_live_locked(1, parent=editor_window)
        _assert_warned(mb, 1, parent=editor_window)


def test_the_claim_is_released_when_the_run_finishes():
    """_sldea_finished runs on the Tk side once the worker has zeroed the
    SG; from then on the channel is the operator's again."""
    with _patched(_MB()) as mb:
        app = _App(live=1)
        app.sg_fire_burst(1)
        assert app.sg.writes == [], app.sg.writes
        _assert_warned(mb, 1)
        app._sldea_finished()
        assert app._sldea_live_ch is None and not app._sldea_running
        app.sg_fire_burst(1)
        assert app.sg.writes == [('burst_trigger', 1, ())], app.sg.writes
        assert len(mb.calls) == 1, "no second warning after the release"


# --------------------------------------------------------------------------
# Signal Gen tab: Fire (the new lock), Apply, Output, Reconnect
# --------------------------------------------------------------------------

def test_fire_refuses_the_live_channel_and_sends_nothing():
    with _patched(_MB()) as mb:
        app = _App(live=1)
        app.sg_fire_burst(1)
        assert app.sg.writes == [], app.sg.writes
        assert app.bg == [], "no background job may even start"
        assert app.status_bar.text is None, app.status_bar.text
        _assert_warned(mb, 1)


def test_fire_on_the_other_channel_still_fires_during_a_live_run():
    with _patched(_MB()) as mb:
        app = _App(live=1)
        app.sg_fire_burst(2)
        assert app.sg.writes == [('burst_trigger', 2, ())], app.sg.writes
        assert app.bg == ['sg-io'] and mb.calls == [], mb.calls
        assert app.status_bar.text == 'CH2: burst fired'


def test_fire_with_no_live_run_is_unchanged():
    # a DRY run leaves _sldea_live_ch at None too: it writes no SG channel
    with _patched(_MB()) as mb:
        app = _App(live=None)
        for ch in (1, 2):
            app.sg_fire_burst(ch)
        assert app.sg.calls() == [('burst_trigger', 1),
                                  ('burst_trigger', 2)], app.sg.writes
        assert mb.calls == []


def test_apply_refuses_the_live_channel_and_a_preset_chain_moves_on():
    """A preset load applies CH1 then CH2 through `_then`: the live channel
    is refused with the warning, and the other one is still applied."""
    with _patched(_MB()) as mb:
        app = _App(live=1)
        app.apply_sg_channel(1, _then=lambda: app.apply_sg_channel(2))
        assert {ch for _, ch in app.sg.calls()} == {2}, app.sg.writes
        assert ('set_basic_wave', 2, ({'WVTP': 'DC', 'OFST': 0.5},)) \
            in app.sg.writes, app.sg.writes
        _assert_warned(mb, 1)


def test_output_refuses_the_live_channel_and_the_other_still_switches():
    with _patched(_MB({'Enable SG output': True})) as mb:
        app = _App(live=1)
        app.sg_toggle_output(1)
        assert app.sg.writes == [] and app.bg == [], app.sg.writes
        _assert_warned(mb, 1)
        mb.calls.clear()
        app.sg_toggle_output(2)
        assert app.sg.writes == [('set_output', 2, (True,))], app.sg.writes
        assert mb.titles() == ['Enable SG output'], mb.calls


def test_reconnect_refuses_while_any_channel_is_live():
    """Reconnect closes the handle both channels share, and nulling it
    mid-run once skipped the safety ramp-down (audit 2026-07-25, C1)."""
    with _patched(_MB()) as mb:
        app = _App(live=2)
        sg = app.sg
        opened = []
        app._reconnect('sg', lambda: opened.append(1), app.sg_status)
        assert app.sg is sg and not sg.closed and opened == []
        assert app.bg == [], app.bg
        _assert_warned(mb, 2)


# --------------------------------------------------------------------------
# Waveform Editor: the LAN upload (the new lock)
# --------------------------------------------------------------------------

def test_editor_upload_refuses_the_live_channel_and_touches_nothing():
    """Not a byte to the box, nothing saved or staged: on the live channel
    this upload would have swapped the Trek's DC drive for a 20 Vpp arb."""
    with _patched(_MB()) as mb:
        app = _App(live=1)
        ed = _Editor(app, channel=1)
        ed.upload()
        assert app.sg.writes == [], app.sg.writes
        _assert_warned(mb, 1, parent=ed)
        assert app.library == [], "nothing saved to the library"
        w = app.sg_channel_widgets[1]
        assert (w['waveform'].get(), w['arb_name_var'].get()) == ('DC', ''), \
            "the live channel's fields were restaged"
        assert app.status_bar.text is None, app.status_bar.text
        assert ed._dirty and ed.refreshed == 0, "the edits were not sent"


def test_editor_upload_to_the_other_channel_still_works_during_a_live_run():
    with _patched(_MB()) as mb:
        app = _App(live=1)
        ed = _Editor(app, channel=1, target=2)
        ed.upload()
        assert mb.calls == [], mb.calls
        assert app.sg.calls() == [('upload_arb', 2), ('select_arb', 2),
                                  ('set_sample_rate', 2),
                                  ('set_basic_wave', 2)], app.sg.writes
        assert app.sg.writes[-1][2] == ({'AMP': 20.0, 'OFST': 0.0},)
        assert app.library == ['pulse'] and not ed._dirty
        assert app.sg_channel_widgets[2]['waveform'].get() == 'ARB'
        assert app.sg_channel_widgets[1]['waveform'].get() == 'DC'


def test_editor_lock_follows_the_send_to_channel_not_the_editor_channel():
    # opened on CH2, sending to the live CH1: refused
    with _patched(_MB()) as mb:
        app = _App(live=1)
        ed = _Editor(app, channel=2, target=1)
        ed.upload()
        assert app.sg.writes == [], app.sg.writes
        _assert_warned(mb, 1, parent=ed)
    # opened on the live CH1, sending to CH2: allowed
    with _patched(_MB()) as mb:
        app = _App(live=1)
        _Editor(app, channel=1, target=2).upload()
        assert {ch for _, ch in app.sg.calls()} == {2}, app.sg.writes
        assert mb.calls == []


def test_editor_upload_with_no_live_run_is_unchanged():
    with _patched(_MB()) as mb:
        app = _App(live=None)
        _Editor(app, channel=1).upload()
        assert [c for c, _ in app.sg.calls()] == [
            'upload_arb', 'select_arb', 'set_sample_rate',
            'set_basic_wave'], app.sg.writes
        assert {ch for _, ch in app.sg.calls()} == {1}
        assert mb.calls == []


# --------------------------------------------------------------------------
# Inventory: every SG write in the app is one somebody has looked at
# --------------------------------------------------------------------------

# Every function in the app modules that writes the signal generator: its
# kind, why it may write, and the writes it makes (method -> count). The
# scan below must find exactly this. A write in a function not listed, or a
# new write in one that is, fails the suite: decide whether a LIVE run's
# channel lock applies to it, guard it and test it above if it does, then
# update this table. A 'locked' writer must also ask _sg_live_locked in a
# top-level `if ...: return` before the statement that holds its first
# write -- checked below, not taken on trust.
SG_WRITERS = {
    'gui.InstrumentControlGUI._sldea_worker': (
        'owner', 'the LIVE run itself: it owns the channel',
        {'set_load_polarity': 1, 'set_basic_wave': 1, 'set_output': 1,
         'set_offset': 1}),
    'gui.InstrumentControlGUI._on_app_close': (
        'shutdown', 'window close: stops a running run first, then '
                    'switches both outputs OFF',
        {'set_output': 1}),
    'gui.InstrumentControlGUI.apply_sg_channel': (
        'locked', 'Apply, and every preset / bench-profile load through it',
        {'set_basic_wave': 1, 'select_arb': 1, 'set_load_polarity': 1,
         'set_burst': 1, 'set_sync': 1}),
    'gui.InstrumentControlGUI.sg_toggle_output': (
        'locked', 'Output', {'set_output': 1}),
    'gui.InstrumentControlGUI.sg_fire_burst': (
        'locked', 'Fire', {'burst_trigger': 1}),
    'arb_editor.ArbWaveformEditor.upload': (
        'locked', 'Upload && Select, on the Send-to channel',
        {'upload_arb': 1, 'select_arb': 1, 'set_sample_rate': 1,
         'set_basic_wave': 1}),
    # Worker threads cannot show the note. PR #334
    # (claude/sldea-sweep-interlock) has each of these two read
    # _sldea_live_ch before every write instead; without it they do not
    # check at all.
    'gui.InstrumentControlGUI._cam_seq_worker': (
        'worker', 'Webcam stepped sweep', {'set_basic_wave': 1}),
    'gui.InstrumentControlGUI._cam_timed_worker': (
        'worker', 'Webcam timed capture: its burst trigger',
        {'burst_trigger': 1}),
}

# Driver calls that change the instrument: every setter, upload, select,
# trigger and raw write -- read off the driver, so a new setter counts.
SG_WRITE_CALLS = frozenset(
    n for n in dir(BK4055B)
    if n.startswith(('set_', 'upload_', 'select_', 'burst_', 'write')))


def _is_sg_handle(node):
    """`sg`, `self.sg`, `app.sg`, `self.app.sg`: the spellings the app
    uses for the signal generator."""
    return ((isinstance(node, _ast.Name) and node.id == 'sg')
            or (isinstance(node, _ast.Attribute) and node.attr == 'sg'))


def _sg_writes(node):
    """The SG writes under `node`, as method names in source order: a write
    method named on an SG handle (called or not -- a callback counts),
    getattr(<handle>, '<write method>'), and any use of the raw VISA handle
    (<handle>.inst, which can send anything). A tripwire for the spellings
    the app uses, not a proof: an alias under another name (the run's own
    `target` in its shutdown loop), a getattr on a computed name, and a
    command smuggled through ask()/query() are not seen."""
    found = []
    for n in _ast.walk(node):
        if isinstance(n, _ast.Attribute) and _is_sg_handle(n.value):
            if n.attr in SG_WRITE_CALLS or n.attr == 'inst':
                found.append((n.lineno, n.col_offset, n.attr))
        elif (isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
              and n.func.id == 'getattr' and len(n.args) >= 2
              and _is_sg_handle(n.args[0])
              and isinstance(n.args[1], _ast.Constant)
              and n.args[1].value in SG_WRITE_CALLS):
            found.append((n.lineno, n.col_offset, n.args[1].value))
    return [name for _, _, name in sorted(found)]


def _sg_write_sites(modules):
    """({'module.Class.method': Counter(write -> count)}, {same: its def})
    for every SG write in `modules` ({name: source}), charged to the
    outermost def around it: a worker closure or a lambda counts as its
    method's. A write outside any def is charged to its module or class."""
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
            writes = _sg_writes(stmt)
            if writes:
                counts.setdefault(owner,
                                  _collections.Counter()).update(writes)

    for name, source in modules.items():
        visit(_ast.parse(source, name).body, name)
    return counts, {k: v for k, v in defs.items() if k in counts}


def _asks_the_lock_first(fn):
    """True when `fn` has a top-level `if <x>._sg_live_locked(...): ...
    return` BEFORE the first top-level statement that holds an SG write. A
    check nested in a branch, one that does not return, or one placed after
    the write does not count."""
    for stmt in fn.body:
        if (isinstance(stmt, _ast.If) and isinstance(stmt.test, _ast.Call)
                and isinstance(stmt.test.func, _ast.Attribute)
                and stmt.test.func.attr == '_sg_live_locked'
                and isinstance(stmt.body[-1], _ast.Return)):
            return True
        if _sg_writes(stmt):
            return False
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


def test_every_sg_write_in_the_app_is_accounted_for():
    counts, _ = _sg_write_sites(_app_modules())
    found = {k: dict(v) for k, v in counts.items()}
    listed = {k: writes for k, (_, _, writes) in SG_WRITERS.items()}
    new = {k: v for k, v in found.items() if k not in listed}
    assert not new, (
        f"SG writes in unlisted functions: {new}. A LIVE SLDEA run owns "
        f"its channel -- does this path ask _sg_live_locked? Guard it and "
        f"test it above, then list it in SG_WRITERS.")
    gone = set(listed) - set(found)
    assert not gone, (
        f"listed in SG_WRITERS but no longer writing the SG: {gone} -- "
        f"moved or renamed? Re-check the guard where the write went.")
    changed = {k: {'found': found[k], 'listed': w}
               for k, w in listed.items() if k in found and found[k] != w}
    assert not changed, (
        f"the SG writes changed in: {changed}. A new write in a listed "
        f"function is still a new write: check it against the LIVE lock, "
        f"then update SG_WRITERS.")


def test_every_locked_writer_asks_the_lock_before_its_first_write():
    _, defs = _sg_write_sites(_app_modules())
    for name, (kind, _, _) in SG_WRITERS.items():
        if kind == 'locked':
            assert name in defs and _asks_the_lock_first(defs[name]), (
                f"{name} is listed as locked but does not ask "
                f"_sg_live_locked in a top-level `if ...: return` before "
                f"its first SG write")


def test_the_inventory_sees_the_spellings_it_claims():
    """Pin the scan on a module whose answer is known: every spelling
    `_sg_writes` claims is caught, counted and charged to the right def --
    a nested class and a module-level function included -- another
    instrument's setter of the same name is not an SG write, and an alias
    is the stated blind spot."""
    src = ("class A:\n"
           "    def a(self):\n"
           "        self.sg.set_output(1, False)\n"
           "    def b(self, app):\n"
           "        app.sg.burst_trigger(1)\n"
           "        app.sg.burst_trigger(2)\n"
           "    def c(self):\n"
           "        sg = self.sg\n"
           "        run = lambda: sg.set_offset(1, 0.0)\n"
           "    def d(self):\n"
           "        self.psu.set_output(1, False)\n"
           "    class B:\n"
           "        def e(self):\n"
           "            def work():\n"
           "                self.app.sg.upload_arb(1, 'w', [])\n"
           "    def g(self):\n"
           "        return self.sg.burst_trigger\n"
           "    def h(self):\n"
           "        getattr(self.sg, 'set_output')(1, True)\n"
           "    def i(self):\n"
           "        self.sg.inst.write('C1:OUTP ON')\n"
           "    def j(self):\n"
           "        gen = self.sg\n"
           "        gen.set_output(1, True)\n"
           "def f(sg):\n"
           "    sg.write('C1:OUTP ON')\n")
    counts, _ = _sg_write_sites({'m': src})
    assert {k: dict(v) for k, v in counts.items()} == {
        'm.A.a': {'set_output': 1}, 'm.A.b': {'burst_trigger': 2},
        'm.A.c': {'set_offset': 1}, 'm.A.B.e': {'upload_arb': 1},
        'm.A.g': {'burst_trigger': 1}, 'm.A.h': {'set_output': 1},
        'm.A.i': {'inst': 1}, 'm.f': {'write': 1}}, counts
    assert {'set_output', 'burst_trigger', 'set_offset', 'upload_arb',
            'select_arb', 'set_basic_wave', 'write'} <= SG_WRITE_CALLS


def test_the_lock_check_must_come_first_and_must_return():
    src = ("class C:\n"
           "    def ok(self, ch):\n"
           "        '''doc'''\n"
           "        if self._sg_live_locked(ch):\n"
           "            return\n"
           "        self.sg.burst_trigger(ch)\n"
           "    def chained(self, ch, then=None):\n"
           "        if self._sg_live_locked(ch):\n"
           "            if then:\n"
           "                then()\n"
           "            return\n"
           "        def work():\n"
           "            self.sg.set_output(ch, True)\n"
           "        self._run_bg(work)\n"
           "    def late(self, ch):\n"
           "        self.sg.burst_trigger(ch)\n"
           "        if self._sg_live_locked(ch):\n"
           "            return\n"
           "    def nested(self, ch):\n"
           "        if ch:\n"
           "            if self._sg_live_locked(ch):\n"
           "                return\n"
           "        self.sg.burst_trigger(ch)\n"
           "    def no_return(self, ch):\n"
           "        if self._sg_live_locked(ch):\n"
           "            pass\n"
           "        self.sg.burst_trigger(ch)\n"
           "    def missing(self, ch):\n"
           "        self.sg.burst_trigger(ch)\n")
    _, defs = _sg_write_sites({'m': src})
    verdict = {k.rsplit('.', 1)[1]: _asks_the_lock_first(v)
               for k, v in defs.items()}
    assert verdict == {'ok': True, 'chained': True, 'late': False,
                       'nested': False, 'no_return': False,
                       'missing': False}, verdict


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
