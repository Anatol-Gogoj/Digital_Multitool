#!/usr/bin/env python3
"""The Signal Gen tab's Set to Vpp/2 button (#498).

A DEA's drive should stay at or above 0 V, and operators used to halve the
Amplitude by hand and type it into DC Offset. The button does that sum.
What is pinned here:

* waveform_render.unipolar_offset is half the amplitude, and refuses an
  amplitude that is negative or not finite;
* the button fills DC Offset with Amplitude / 2 and sends NOTHING to the
  signal generator: Apply sends it, like a typed value, so the LIVE-run
  lock and the Apply-then-Output rule stay where they were;
* an Amplitude it cannot halve is refused with a box, and the offset is
  left as it was;
* on the real tab (skipped with no display) each channel has the button,
  it sits between the offset entry and its readout, it is shown for every
  waveform with an Amplitude and hidden for DC, and a click updates the
  field and the preview caption.

Run: .venv/bin/python tests/test_sg_offset_half_vpp.py
"""
import math as _math
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import gui  # noqa: E402
import waveform_render  # noqa: E402

G = gui.InstrumentControlGUI


class _Entry:
    """ttk.Entry stand-in: get(), delete(0, END), insert(0, text)."""

    def __init__(self, text=''):
        self.text = text

    def get(self):
        return self.text

    def delete(self, first, last=None):
        self.text = ''

    def insert(self, index, text):
        self.text = str(text) + self.text


class _Label:
    def __init__(self):
        self.text = None

    def config(self, text=None, **_kw):
        if text is not None:
            self.text = text


class _MB:
    def __init__(self):
        self.calls = []

    def showerror(self, title, message, **kw):
        self.calls.append(('showerror', title, message))


class _RecordingSG:
    """Any attribute access is a finding: the button must not talk to the
    signal generator at all."""

    def __getattr__(self, name):
        raise AssertionError(f"the button reached the SG: .{name}")


class _App:
    sg_offset_half_vpp = G.sg_offset_half_vpp
    _set_entry = staticmethod(G._set_entry)

    def __init__(self, amp='1.0', offset='0.0'):
        self.sg = _RecordingSG()
        self.status_bar = _Label()
        self.redrawn = []
        self.sg_channel_widgets = {
            ch: {'amp': _Entry(amp), 'offset': _Entry(offset)}
            for ch in (1, 2)}

    def _sg_redraw_preview(self, ch):
        self.redrawn.append(ch)


def _with_mb(fn):
    saved = gui.messagebox
    gui.messagebox = mb = _MB()
    try:
        fn(mb)
    finally:
        gui.messagebox = saved


# --------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------

def test_unipolar_offset_is_half_the_amplitude():
    for amp, want in ((1.0, 0.5), (3.3, 1.65), (0.0, 0.0), (10, 5.0),
                      ('2', 1.0), (' 4.5 ', 2.25), (1e-3, 5e-4)):
        got = waveform_render.unipolar_offset(amp)
        assert got == want, (amp, got, want)
        # the trough of the scaled waveform lands on 0 V, never below
        for wave in ('SINE', 'SQUARE', 'RAMP', 'PULSE'):
            unit = waveform_render.unit_waveform(wave, n_periods=2,
                                                 points_per_period=64)
            volts = waveform_render.scale_waveform(unit, float(amp), got)
            assert min(volts) >= 0.0, (wave, amp, min(volts))
            assert _math.isclose(max(volts), float(amp)), (wave, amp)


def test_unipolar_offset_refuses_what_it_cannot_halve():
    for bad in (-1.0, -1e-9, float('nan'), float('inf'), 'abc', ''):
        try:
            waveform_render.unipolar_offset(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


# --------------------------------------------------------------------------
# The button, on a Tk-free stub
# --------------------------------------------------------------------------

def test_the_button_fills_the_offset_and_sends_nothing():
    def body(mb):
        app = _App(amp='3.3', offset='0.0')
        app.sg_offset_half_vpp(1)
        assert app.sg_channel_widgets[1]['offset'].get() == '1.65'
        assert app.sg_channel_widgets[2]['offset'].get() == '0.0', \
            "the other channel's field moved"
        assert app.redrawn == [1], app.redrawn
        assert mb.calls == [], mb.calls
        assert 'Apply CH1 Settings' in app.status_bar.text, \
            app.status_bar.text
        assert '0 V to 3.3 V' in app.status_bar.text, app.status_bar.text
    _with_mb(body)


def test_the_button_writes_a_plain_number_the_entry_can_hold():
    """No float noise and no exponent in the field: Apply float()s it."""
    def body(mb):
        for amp, want in (('1', '0.5'), ('0.1', '0.05'), ('2.123456', '1.061728'),
                          ('7', '3.5'), ('0', '0')):
            app = _App(amp=amp, offset='9')
            app.sg_offset_half_vpp(2)
            got = app.sg_channel_widgets[2]['offset'].get()
            assert got == want, (amp, got, want)
            assert float(got) * 2 == float(amp), (amp, got)
        assert mb.calls == []
    _with_mb(body)


def test_an_amplitude_it_cannot_halve_is_refused_and_the_offset_kept():
    def body(mb):
        for bad in ('', '   ', 'abc', '-2', 'nan', 'inf'):
            mb.calls.clear()
            app = _App(amp=bad, offset='0.25')
            app.sg_offset_half_vpp(1)
            assert app.sg_channel_widgets[1]['offset'].get() == '0.25', bad
            assert app.redrawn == [] and app.status_bar.text is None, bad
            [(kind, title, msg)] = mb.calls
            assert (kind, title) == ('showerror', 'Set to Vpp/2'), mb.calls
            assert 'CH1 Amplitude' in msg, msg
    _with_mb(body)


# --------------------------------------------------------------------------
# The real tab (skipped with no display)
# --------------------------------------------------------------------------

def _app():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return None, None
    gui.InstrumentControlGUI.auto_connect = lambda self: None
    gui.CAM_AUTOSTART_ON_TAB = False
    app = gui.InstrumentControlGUI(root)
    root.update_idletasks()
    return root, app


def test_on_the_real_tab_it_follows_the_amplitude_row():
    root, app = _app()
    if root is None:
        return
    try:
        for ch in (1, 2):
            w = app.sg_channel_widgets[ch]
            half = w['offset_half']
            assert half.cget('text') == 'Set to Vpp/2'
            for wave in ('SINE', 'SQUARE', 'RAMP', 'PULSE', 'ARB', 'DC'):
                w['waveform'].set(wave)
                app._sg_waveform_changed(ch)
                shown = bool(half.winfo_manager())
                assert shown == (wave != 'DC'), (ch, wave, shown)
                if shown:
                    # entry, then the button, then the readout
                    order = w['rows']['offset'].pack_slaves()
                    assert order.index(w['offset']) < order.index(half) \
                        < order.index(w['applied']['offset']), (ch, wave)
            w['waveform'].set('SQUARE')
            app._sg_waveform_changed(ch)
            app._set_entry(w['amp'], '6')
            half.invoke()
            assert w['offset'].get() == '3', w['offset'].get()
            captions = [w['canvas'].itemcget(i, 'text')
                        for i in w['canvas'].find_all()
                        if w['canvas'].type(i) == 'text']
            assert any('6 Vpp  +3 V' in c for c in captions), captions
    finally:
        root.destroy()


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
