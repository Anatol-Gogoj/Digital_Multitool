#!/usr/bin/env python3
"""Headless tests for sweep_plan.py (no Tk, no instruments).

This maths used to live inside gui.InstrumentControlGUI._parse_sweep_axis,
where nothing could reach it. It plans the LCR tab's sweep today and the
signal-generator sweep of `#65` next, so the numbers it produces are what
gets written to an instrument -- these pin them.

Run: .venv/bin/python tests/test_sweep_plan.py
"""
# Runnable from anywhere: put the repo root (one level up) on sys.path
# so the app modules import when this file is executed directly.
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import math

import sweep_plan as sp


def _rejects(fragment, **kwargs):
    """Assert plan_axis(**kwargs) raises ValueError mentioning `fragment`."""
    try:
        got = sp.plan_axis(**kwargs)
    except ValueError as e:
        assert fragment in str(e), f"wrong message for {kwargs}: {e}"
        return str(e)
    raise AssertionError(f"expected ValueError for {kwargs}, got {got}")


# -- list mode -------------------------------------------------------------

def test_list_basic():
    assert sp.plan_axis('list', list_text='1,2,3') == [1.0, 2.0, 3.0]


def test_list_whitespace_and_trailing_comma():
    # A pasted spreadsheet row: padding around the separators and a trailing
    # one. Blank fields are dropped, so the trailing comma is harmless.
    got = sp.plan_axis('list', list_text='  1 ,  2.5 , 3 ,  ')
    assert got == [1.0, 2.5, 3.0], got
    assert sp.plan_axis('list', list_text='1,2,3,') == [1.0, 2.0, 3.0]


def test_list_semicolons_accepted():
    # Some locales' spreadsheets export with ';'.
    assert sp.plan_axis('list', list_text='1;2;3') == [1.0, 2.0, 3.0]
    assert sp.plan_axis('list', list_text='1;2,3;') == [1.0, 2.0, 3.0]


def test_list_single_value():
    assert sp.plan_axis('list', list_text='4.2') == [4.2]


def test_list_order_is_preserved():
    # Not sorted: the operator's order is the visiting order.
    assert sp.plan_axis('list', list_text='3,1,2') == [3.0, 1.0, 2.0]


def test_list_empty_rejected():
    _rejects('list is empty', mode='list', list_text='')
    _rejects('list is empty', mode='list', list_text=' , , ')


def test_list_junk_rejected():
    _rejects('could not be parsed', mode='list', list_text='1,two,3')


def test_list_needs_separators():
    # Whitespace alone does NOT separate values here (unlike
    # webcam.parse_level_list) -- pinned so nobody "harmonises" the two
    # parsers without noticing this is a behaviour change for the LCR tab.
    _rejects('could not be parsed', mode='list', list_text='1 2 3')


# -- linear stepping -------------------------------------------------------

def test_linear_basic():
    assert sp.plan_axis('range', start='0', stop='10', points='5') == \
        [0.0, 2.5, 5.0, 7.5, 10.0]


def test_linear_two_points_is_just_the_ends():
    assert sp.plan_axis('range', start='1', stop='2', points='2') == [1.0, 2.0]


def test_linear_single_point_ignores_stop():
    # points == 1 has no step to take, so only start is visited.
    assert sp.plan_axis('range', start='3.5', stop='99', points='1') == [3.5]


def test_linear_start_equals_stop():
    # Degenerate but legal: n dwells at one setting (zero step).
    assert sp.plan_axis('range', start='2', stop='2', points='4') == \
        [2.0, 2.0, 2.0, 2.0]
    assert sp.plan_axis('range', start='2', stop='2', points='1') == [2.0]


def test_linear_descending_supported():
    # stop < start is a legal downward sweep, NOT an error.
    assert sp.plan_axis('range', start='10', stop='0', points='5') == \
        [10.0, 7.5, 5.0, 2.5, 0.0]


def test_linear_endpoint_is_exact():
    got = sp.plan_axis('range', start='0.1', stop='0.3', points='3')
    assert got[-1] == 0.3, got


def test_linear_accepts_numbers_as_well_as_text():
    # Tk hands over strings; a programmatic caller may pass numbers.
    assert sp.plan_axis('range', start=0, stop=10, points=3) == \
        [0.0, 5.0, 10.0]


# -- log stepping ----------------------------------------------------------

def test_log_decade_endpoint_is_exactly_stop():
    # The reason the endpoint snap exists: accumulating the ratio lands on
    # 100000.00000000003, which an operator reading the CSV does not trust.
    start, stop, points = 100.0, 100000.0, 4
    naive = start * ((stop / start) ** (1.0 / (points - 1))) ** (points - 1)
    assert naive != stop, "float drift vanished; is the snap still needed?"
    got = sp.plan_axis('range', start='100', stop='100000', points='4',
                       scale='log')
    assert got[-1] == stop, repr(got[-1])          # EXACTLY, not approximately
    assert len(got) == 4
    # decade spacing, to the drift the snap deliberately leaves in the middle
    for want, have in zip([100.0, 1000.0, 10000.0, 100000.0], got):
        assert math.isclose(want, have, rel_tol=1e-9), got


def test_log_endpoint_snap_over_the_lcr_band():
    got = sp.plan_axis('range', start='100', stop='500000', points='13',
                       scale='log', vmin=100, vmax=500000, name='Frequency')
    assert got[0] == 100.0 and got[-1] == 500000.0, (got[0], got[-1])
    assert all(b > a for a, b in zip(got, got[1:])), got


def test_log_descending_endpoint_is_exact():
    got = sp.plan_axis('range', start='100000', stop='100', points='4',
                       scale='log')
    assert got[0] == 100000.0 and got[-1] == 100.0, got
    assert all(b < a for a, b in zip(got, got[1:])), got


def test_log_single_point():
    assert sp.plan_axis('range', start='100', stop='100000', points='1',
                        scale='log') == [100.0]


def test_log_start_equals_stop():
    assert sp.plan_axis('range', start='1000', stop='1000', points='3',
                        scale='log') == [1000.0, 1000.0, 1000.0]


def test_log_rejects_zero_or_negative():
    # A zero or negative endpoint would give a complex or infinite ratio;
    # it must be refused, never turned into NaN/inf points to send to a box.
    for start, stop in [('0', '1000'), ('1000', '0'), ('-10', '1000'),
                        ('10', '-1000'), ('-10', '-1000')]:
        _rejects('requires positive start and stop', mode='range',
                 start=start, stop=stop, points='4', scale='log',
                 vmin=-1e9, vmax=1e9)


def test_log_never_returns_nan_or_inf():
    for start, stop in [('0', '1000'), ('-10', '-1000')]:
        try:
            got = sp.plan_axis('range', start=start, stop=stop, points='4',
                               scale='log', vmin=-1e9, vmax=1e9)
        except ValueError:
            continue
        raise AssertionError(f"expected rejection, got {got}")


def test_unknown_scale_falls_back_to_linear():
    # The Tk combobox is readonly, but a future caller could pass anything;
    # only 'log' switches scaling.
    assert sp.plan_axis('range', start='0', stop='10', points='3',
                        scale='quadratic') == [0.0, 5.0, 10.0]


# -- field validation ------------------------------------------------------

def test_points_below_one_rejected():
    for points in ('0', '-3'):
        _rejects('points must be', mode='range', start='0', stop='10',
                 points=points)


def test_non_numeric_fields_rejected():
    _rejects('must be numeric', mode='range', start='abc', stop='10',
             points='5')
    _rejects('must be numeric', mode='range', start='0', stop='',
             points='5')
    # points is an integer count -- '2.5' is not one
    _rejects('must be numeric', mode='range', start='0', stop='10',
             points='2.5')


# -- range validation against the instrument limits ------------------------

def test_range_validation_upper_end():
    _rejects('is outside [0, 10]', mode='range', start='0', stop='11',
             points='3', vmin=0, vmax=10, name='Voltage')
    _rejects('is outside [0, 10]', mode='list', list_text='1,2,11',
             vmin=0, vmax=10, name='Voltage')


def test_range_validation_lower_end():
    _rejects('is outside [0, 10]', mode='range', start='-1', stop='5',
             points='3', vmin=0, vmax=10, name='Voltage')
    _rejects('is outside [0, 10]', mode='list', list_text='-1,2',
             vmin=0, vmax=10, name='Voltage')


def test_range_validation_is_inclusive():
    # The limits themselves are legal values (the LCR sweep's defaults sit
    # exactly on them).
    assert sp.plan_axis('range', start='0.01', stop='2.0', points='2',
                        vmin=0.01, vmax=2.0) == [0.01, 2.0]


def test_range_validation_checks_the_single_point_too():
    _rejects('is outside [0, 10]', mode='range', start='99', stop='99',
             points='1', vmin=0, vmax=10, name='Voltage')


def test_message_names_the_axis():
    msg = _rejects('is outside', mode='list', list_text='11', vmin=0, vmax=10,
                   name='Frequency')
    assert msg.startswith('Frequency '), msg


# -- the GUI wrapper still asks the same question --------------------------

def test_gui_wrapper_delegates():
    """gui._parse_sweep_axis must read the widgets and return plan_axis'.

    Driven with a stub `self` exposing only .get(), which is all the method
    uses -- so this needs no display, and it catches a mis-wired widget name
    that no pure-function test could see.
    """
    try:
        import gui
    except Exception as e:                      # no tkinter on this box
        print(f"   (skipped: gui import failed: {e})")
        return

    class V:
        def __init__(self, s):
            self.s = s

        def get(self):
            return self.s

    stub = type('Stub', (), {})()
    for attr, val in [('mode', 'range'), ('list_var', '1000,2000'),
                      ('start_entry', '100'), ('stop_entry', '100000'),
                      ('points_entry', '4'), ('scale', 'log')]:
        setattr(stub, f'sw_freq_{attr}', V(val))

    got = gui.InstrumentControlGUI._parse_sweep_axis(
        stub, 'freq', 100, 500000, 'Frequency')
    assert got == sp.plan_axis('range', start='100', stop='100000',
                               points='4', scale='log', vmin=100,
                               vmax=500000, name='Frequency'), got
    assert got[-1] == 100000.0, got

    stub.sw_freq_mode = V('list')
    assert gui.InstrumentControlGUI._parse_sweep_axis(
        stub, 'freq', 100, 500000, 'Frequency') == [1000.0, 2000.0]

    stub.sw_freq_list_var = V('1000,999999')
    try:
        gui.InstrumentControlGUI._parse_sweep_axis(
            stub, 'freq', 100, 500000, 'Frequency')
    except ValueError as e:
        assert 'outside' in str(e), e
    else:
        raise AssertionError("out-of-range list should raise")


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
