#!/usr/bin/env python3
"""Headless tests for LCR Apply checking every field first (#483, no
hardware, no Tk).

The bug: `apply_lcr_config` sent the mode and the frequency to the BK 894
before `set_voltage` refused a level outside 0.01 to 2.0 V. Apply then
showed "Configuration Error", but the meter had already changed mode and
frequency, and `lcr_applied_mode` still named the old mode, so readouts
were labeled with it. A bad bias or Avg went further: everything up to
auto-range had been sent. What is pinned here:

* a bad mode, frequency, voltage, speed, Avg or bias sends NOTHING, shows
  exactly one Configuration Error carrying the setter's own message, and
  leaves `lcr_applied_mode` and the busy keys as they were;
* a valid Apply sends the same commands, in the same order, as before;
* `lcr_applied_mode` changes only when every command went out, so a
  transport error part way through leaves it alone.

The meter is the REAL `BK894` driver with its transport stubbed, and
Apply runs the REAL `apply_lcr_config` and `_run_bg` on a Tk-free stub app
whose root queues callbacks for the test to run.

Run: .venv/bin/python tests/test_lcr_apply_validates.py
"""
import os as _os
import queue as _queue
import sys as _sys
import types as _types
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import gui  # noqa: E402
from instruments import BK894  # noqa: E402

G = gui.InstrumentControlGUI

# What a valid Apply sent before #483, captured from the code on #497's
# head (59872cc) with the fields below. The order matters to the meter:
# the mode comes first because it can change what the level means.
GOOD = {'mode': 'cpd', 'freq': '1000', 'volt': '1.0', 'bias_v': '0.5',
        'avg': '8', 'speed': 'SLOW', 'bias_on': True, 'autorange': False}
GOOD_SENT = [':FUNC:IMP CPD', ':FREQ 1000.0', ':VOLT 1.0', ':APER SLOW,8',
             ':FUNC:IMP:RANG:AUTO 0', ':BIAS:VOLT 0.5', ':BIAS:STAT 1']


class FakeLCR(BK894):
    """BK894 with the transport stubbed (skips VisaInstrument.__init__).
    `fail_on` makes the write that starts with it raise, as a VISA
    timeout would."""

    def __init__(self, fail_on=None):
        self.sent = []
        self.fail_on = fail_on
        self.inst = _types.SimpleNamespace(timeout=2000)

    def write(self, command):
        if self.fail_on and command.startswith(self.fail_on):
            raise TimeoutError("VI_ERROR_TMO")
        self.sent.append(command)


class _Var:
    def __init__(self, value=''):
        self.value = value

    def get(self):
        return self.value


class _Widget:
    def __init__(self):
        self.text = None

    def config(self, text=None, **_kw):
        if text is not None:
            self.text = text

    configure = config


class _Root:
    """Queues after() callbacks; the test runs them in the main loop's
    place."""

    def __init__(self):
        self.q = _queue.Queue()

    def after(self, _ms, fn, *args):
        self.q.put((fn, args))

    def run_pending(self, rounds=50):
        for _ in range(rounds):
            try:
                fn, args = self.q.get(timeout=2.0)
            except _queue.Empty:
                return
            fn(*args)


class _App:
    """Tk-free stand-in carrying the real apply_lcr_config and _run_bg."""

    apply_lcr_config = G.apply_lcr_config
    _run_bg = G._run_bg

    def __init__(self, lcr, **fields):
        f = dict(GOOD, **fields)
        self.lcr = lcr
        self.root = _Root()
        self._bg_busy = set()
        self.lcr_applied_mode = 'CSRS'      # what the meter was left in
        self.lcr_mode = _Var(f['mode'])
        self.lcr_freq = _Var(f['freq'])
        self.lcr_volt = _Var(f['volt'])
        self.lcr_bias_volt = _Var(f['bias_v'])
        self.lcr_avg = _Var(f['avg'])
        self.lcr_speed = _Var(f['speed'])
        self.lcr_bias_on = _Var(f['bias_on'])
        self.lcr_autorange = _Var(f['autorange'])
        self.status_bar = _Widget()

    def apply(self):
        self.apply_lcr_config()
        self.root.run_pending()


class _Boxes:
    """Records messagebox calls instead of opening windows."""

    def __enter__(self):
        self.calls = []
        self.saved = {n: getattr(gui.messagebox, n)
                      for n in ('showerror', 'showwarning', 'showinfo')}
        for n in self.saved:
            setattr(gui.messagebox, n,
                    lambda *a, _n=n, **k: self.calls.append((_n, a)))
        return self

    def __exit__(self, *exc):
        for n, fn in self.saved.items():
            setattr(gui.messagebox, n, fn)


def _refused(field, value, message):
    """Apply with one bad field: nothing sent, one box with `message`."""
    lcr = FakeLCR()
    app = _App(lcr, **{field: value})
    with _Boxes() as boxes:
        app.apply()
    assert lcr.sent == [], (field, value, lcr.sent)
    assert len(boxes.calls) == 1, (field, value, boxes.calls)
    kind, (title, text) = boxes.calls[0]
    assert (kind, title) == ('showerror', 'Configuration Error'), \
        boxes.calls
    assert message in text, (field, value, text)
    assert app.lcr_applied_mode == 'CSRS', app.lcr_applied_mode
    assert app._bg_busy == set(), app._bg_busy
    assert app.status_bar.text is None, app.status_bar.text


def test_a_bad_voltage_sends_nothing():
    for v in ('2.5', '0.005', '-1', 'nan'):
        _refused('volt', v, 'Voltage must be 0.01 to 2.0 V')


def test_a_bad_frequency_sends_nothing():
    for f in ('10', '19.9', '600000', 'inf'):
        _refused('freq', f, 'Frequency must be 20 Hz to 500 kHz')


def test_a_bad_bias_sends_nothing():
    for b in ('5.5', '-6'):
        _refused('bias_v', b, 'Bias must be within +/-5 V')


def test_a_bad_average_sends_nothing():
    for a in ('0', '257'):
        _refused('avg', a, 'Averaging count must be 1 to 256')


def test_a_bad_mode_or_speed_sends_nothing():
    _refused('mode', 'XYZ', 'Invalid mode')
    _refused('speed', 'TURBO', 'Speed must be one of')


def test_an_unparsable_field_sends_nothing():
    # Caught by the float()/int() reads, as before #483.
    _refused('volt', 'abc', 'could not convert')
    _refused('avg', '2.5', 'invalid literal')


def test_a_valid_apply_sends_the_same_commands_in_the_same_order():
    lcr = FakeLCR()
    app = _App(lcr)
    with _Boxes() as boxes:
        app.apply()
    assert not boxes.calls, boxes.calls
    assert lcr.sent == GOOD_SENT, lcr.sent
    assert app.lcr_applied_mode == 'CPD', app.lcr_applied_mode
    assert app._bg_busy == set(), app._bg_busy
    assert app.status_bar.text.startswith('LCR configured: cpd'), \
        app.status_bar.text


def test_the_ranges_ends_are_accepted():
    for fields, sent in (({'freq': '20', 'volt': '0.01', 'avg': '1',
                           'bias_v': '-5'},
                          [':FREQ 20.0', ':VOLT 0.01', ':APER SLOW,1',
                           ':BIAS:VOLT -5.0']),
                         ({'freq': '500000', 'volt': '2.0', 'avg': '256',
                           'bias_v': '5'},
                          [':FREQ 500000.0', ':VOLT 2.0', ':APER SLOW,256',
                           ':BIAS:VOLT 5.0'])):
        lcr = FakeLCR()
        app = _App(lcr, **fields)
        with _Boxes() as boxes:
            app.apply()
        assert not boxes.calls, (fields, boxes.calls)
        for cmd in sent:
            assert cmd in lcr.sent, (cmd, lcr.sent)
        assert len(lcr.sent) == len(GOOD_SENT), lcr.sent


def test_applied_mode_changes_only_when_every_command_went_out():
    # A transport error part way through is not a validation refusal:
    # the mode went out, but Apply did not finish, and the label stays
    # where it was (one Configuration Error, the busy key let go).
    lcr = FakeLCR(fail_on=':VOLT')
    app = _App(lcr)
    with _Boxes() as boxes:
        app.apply()
    assert lcr.sent == GOOD_SENT[:2], lcr.sent
    assert [(k, a[0]) for k, a in boxes.calls] == \
        [('showerror', 'Configuration Error')], boxes.calls
    assert 'VI_ERROR_TMO' in boxes.calls[0][1][1]
    assert app.lcr_applied_mode == 'CSRS', app.lcr_applied_mode
    assert app._bg_busy == set(), app._bg_busy


def test_apply_while_the_meter_is_busy_sends_nothing():
    lcr = FakeLCR()
    app = _App(lcr)
    app._bg_busy.add('lcr-io')
    with _Boxes() as boxes:
        app.apply()
    assert lcr.sent == [] and not boxes.calls, (lcr.sent, boxes.calls)
    assert app.lcr_applied_mode == 'CSRS'
    assert 'Still working' in app.status_bar.text, app.status_bar.text


def _run():
    # Failures are collected, not fatal (`#280`), as in the other suites.
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
