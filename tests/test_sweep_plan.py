#!/usr/bin/env python3
"""Headless tests for sweep_plan.py (no Tk, no instruments).

This maths used to live inside gui.InstrumentControlGUI._parse_sweep_axis,
where nothing could reach it. It plans the LCR tab's sweep and the
signal-generator sweep of `#65`, so the numbers it produces are what gets
written to an instrument -- these pin them.

For the Signal Gen sweep that means the visiting order of both Order
choices, the 0 V to Vpp offset, the extremes the start check uses, the
read-back tolerance (a clamped amplitude must fail it), the read-back's
band that the worker holds to those extremes (None when it cannot be
read, so it never stops a sweep on a bad field alone), and the order
level_writes sends each change in: brute-forced over seeded random pairs,
no in-between state the box holds may reach beyond the two settings it
sits between, and a 0 V to Vpp sweep may never dip below 0 V.

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


# -- Signal Gen sweep (#65): the points, their extremes, the read-back -----
# and the order each level change is sent in. Through the Trek 1 V = 1 kV,
# so the level-write order is pinned by brute force, not by example.

def test_sg_points_amplitude_outer_holds_each_amplitude_across_every_freq():
    got = sp.sg_points([1, 10, 100], [0.5, 2], sp.SG_ORDER_AMP_OUTER)
    assert got == [(1.0, 0.5, 0.25), (10.0, 0.5, 0.25), (100.0, 0.5, 0.25),
                   (1.0, 2.0, 1.0), (10.0, 2.0, 1.0), (100.0, 2.0, 1.0)], got
    # and it is the default order
    assert sp.sg_points([1, 10, 100], [0.5, 2]) == got


def test_sg_points_frequency_outer_steps_every_amplitude_per_freq():
    got = sp.sg_points([1, 10], [0.5, 1, 2], sp.SG_ORDER_FREQ_OUTER)
    assert [(f, a) for f, a, _ in got] == [
        (1.0, 0.5), (1.0, 1.0), (1.0, 2.0),
        (10.0, 0.5), (10.0, 1.0), (10.0, 2.0)], got


def test_sg_points_unipolar_offset_is_half_of_each_amplitude():
    for order in sp.SG_ORDERS:
        got = sp.sg_points([5, 50], [0.3, 1.7, 4], order, unipolar=True,
                           offset_v=-3.0)          # ignored when unipolar
        assert len(got) == 6, got
        for f, a, o in got:
            assert o == a / 2.0, (f, a, o)
            assert isinstance(f, float) and isinstance(a, float), got


def test_sg_points_bipolar_uses_the_fixed_offset_for_every_point():
    for order in sp.SG_ORDERS:
        got = sp.sg_points([5, 50], [0.3, 1.7], order, unipolar=False,
                           offset_v='-1.25')       # a Tk string is fine
        assert [o for _, _, o in got] == [-1.25] * 4, got


def test_sg_points_rejects_an_unknown_order():
    for bad in ('', 'Freq outer', None, 'vpp outer, freq inner'):
        try:
            got = sp.sg_points([1], [1], bad)
        except ValueError as e:
            assert 'Order must be one of' in str(e), e
        else:
            raise AssertionError(f"order {bad!r} accepted: {got}")


def test_sg_extremes_are_the_lowest_trough_and_the_highest_peak():
    pts = [(1.0, 2.0, 1.0), (1.0, 4.0, -1.0), (1.0, 1.0, 1.5)]
    # troughs 0, -3, 1; peaks 2, 1, 2
    assert sp.sg_extremes(pts) == (-3.0, 2.0)
    assert sp.sg_extremes(sp.sg_points([1, 2], [0.5, 2.5])) == (0.0, 2.5)


def test_sg_extremes_of_no_points_raises():
    try:
        got = sp.sg_extremes([])
    except ValueError:
        return
    raise AssertionError(f"expected ValueError, got {got}")


def _bswv(f, a, o, **extra):
    """A read-back as BK4055B.get_basic_wave_dict returns one."""
    d = {'WVTP': 'SINE', 'FRQ': f, 'AMP': a, 'OFST': o}
    d.update(extra)
    return d


def test_readback_matches_an_exact_echo():
    assert sp.readback_matches((1000.0, 2.0, 1.0), _bswv(1000.0, 2.0, 1.0))


def test_readback_matches_within_a_tenth_of_a_percent():
    asked = (1000.0, 2.0, 1.0)
    assert sp.readback_matches(asked, _bswv(1000.9, 2.0019, 1.0009))
    assert sp.readback_matches(asked, _bswv(999.1, 1.9981, 0.9991))
    # but not a different setting
    assert not sp.readback_matches(asked, _bswv(1002.0, 2.0, 1.0))
    assert not sp.readback_matches(asked, _bswv(1000.0, 2.0, 1.003))


def test_readback_fails_a_clamped_amplitude():
    # 25 Vpp asked, the box held 20
    assert not sp.readback_matches((100.0, 25.0, 12.5),
                                   _bswv(100.0, 20.0, 12.5))


def test_readback_fails_a_missing_or_unreadable_field():
    asked = (1000.0, 2.0, 1.0)
    good = _bswv(1000.0, 2.0, 1.0)
    for key in ('FRQ', 'AMP', 'OFST'):
        missing = dict(good)
        del missing[key]
        assert not sp.readback_matches(asked, missing), key
        for junk in (None, 'abc', '', float('nan')):
            bad = dict(good, **{key: junk})
            assert not sp.readback_matches(asked, bad), (key, junk)
    assert not sp.readback_matches(asked, None)
    assert not sp.readback_matches(asked, {})


def test_readback_near_zero_offset_uses_the_absolute_tolerance():
    asked = (1000.0, 2.0, 0.0)
    assert sp.readback_matches(asked, _bswv(1000.0, 2.0, 0.0))
    assert sp.readback_matches(asked, _bswv(1000.0, 2.0, 0.0005))
    assert sp.readback_matches(asked, _bswv(1000.0, 2.0, -0.0005))
    assert not sp.readback_matches(asked, _bswv(1000.0, 2.0, 0.002))
    assert not sp.readback_matches(asked, _bswv(1000.0, 2.0, -0.002))


def test_readback_shape_matches_checks_the_waveform_and_a_squares_duty():
    assert sp.readback_shape_matches('SINE', None, {'WVTP': 'SINE'})
    assert sp.readback_shape_matches('SINE', None, {'WVTP': ' sine '})
    assert not sp.readback_shape_matches('SINE', None, {'WVTP': 'DC'})
    assert not sp.readback_shape_matches('SINE', None, {})
    sq = {'WVTP': 'SQUARE', 'DUTY': 50.0}
    assert sp.readback_shape_matches('SQUARE', 50.0, sq)
    assert sp.readback_shape_matches('SQUARE', 50.0, dict(sq, DUTY=50.05))
    assert not sp.readback_shape_matches('SQUARE', 50.0, dict(sq, DUTY=49.5))
    assert not sp.readback_shape_matches('SQUARE', 50.0, {'WVTP': 'SQUARE'})
    for junk in (None, 'abc', ''):
        assert not sp.readback_shape_matches('SQUARE', 50.0,
                                             dict(sq, DUTY=junk)), junk
    assert not sp.readback_shape_matches('SQUARE', 50.0,
                                         dict(sq, WVTP='SINE'))


def test_readback_band_is_offset_minus_and_plus_half_the_amplitude():
    assert sp.readback_band(_bswv(1000.0, 2.0, 1.0)) == (0.0, 2.0)
    assert sp.readback_band(_bswv(1000.0, 4.0, -1.0)) == (-3.0, 1.0)
    assert sp.readback_band(_bswv(1000.0, 0.0, 0.5)) == (0.5, 0.5)
    # numeric strings are read as numbers, as readback_matches reads them
    assert sp.readback_band({'AMP': '2', 'OFST': '-0.5'}) == (-1.5, 0.5)
    # FRQ plays no part
    assert sp.readback_band({'AMP': 1.0, 'OFST': 0.0}) == (-0.5, 0.5)


def test_readback_band_is_none_without_a_usable_amp_and_offset():
    good = _bswv(1000.0, 2.0, 1.0)
    for key in ('AMP', 'OFST'):
        missing = dict(good)
        del missing[key]
        assert sp.readback_band(missing) is None, key
        for junk in (None, 'abc', '', float('nan'), float('inf'),
                     float('-inf')):
            assert sp.readback_band(dict(good, **{key: junk})) is None, \
                (key, junk)
    assert sp.readback_band(None) is None
    assert sp.readback_band({}) is None


def test_readback_band_of_an_exact_echo_equals_the_asked_extremes():
    pts = sp.sg_points([1, 10], [0.5, 1.5, 2.5])
    for f, a, o in pts:
        assert sp.readback_band(_bswv(f, a, o)) == sp.sg_extremes(
            [(f, a, o)]), (f, a, o)


def test_level_writes_send_frequency_first():
    # amplitude growing: FRQ, then the offset, then the amplitude
    assert sp.level_writes((1.0, 1.0, 0.5), (10.0, 2.0, 1.0)) == [
        {'FRQ': 10.0}, {'OFST': 1.0}, {'AMP': 2.0}]
    # amplitude shrinking: FRQ, then the amplitude, then the offset
    assert sp.level_writes((1.0, 2.0, 1.0), (10.0, 0.5, 0.25)) == [
        {'FRQ': 10.0}, {'AMP': 0.5}, {'OFST': 0.25}]


def test_level_writes_send_only_what_changed():
    prev = (100.0, 1.0, 0.5)
    assert sp.level_writes(prev, (200.0, 1.0, 0.5)) == [{'FRQ': 200.0}]
    assert sp.level_writes(prev, (100.0, 3.0, 0.5)) == [{'AMP': 3.0}]
    assert sp.level_writes(prev, (100.0, 1.0, -0.5)) == [{'OFST': -0.5}]
    assert sp.level_writes(prev, (200.0, 1.0, -0.5)) == [
        {'FRQ': 200.0}, {'OFST': -0.5}]


def test_level_writes_nothing_changed_is_nothing_sent():
    assert sp.level_writes((100.0, 1.0, 0.5), (100.0, 1.0, 0.5)) == []


def _random_pair(rng):
    """One (prev, new, unipolar) pair: amplitudes above 0, offsets of any
    sign, and a fair share of equal frequencies, amplitudes and offsets."""
    def amp():
        return rng.choice((rng.uniform(0.001, 20.0),
                           float(rng.randint(1, 20)) / 2.0))

    f0 = rng.choice((1.0, 10.0, rng.uniform(0.1, 1e5)))
    f1 = f0 if rng.random() < 0.4 else rng.uniform(0.1, 1e5)
    a0 = amp()
    a1 = a0 if rng.random() < 0.25 else amp()
    unipolar = rng.random() < 0.35
    if unipolar:
        o0, o1 = a0 / 2.0, a1 / 2.0
    else:
        o0 = rng.uniform(-10.0, 10.0)
        o1 = o0 if rng.random() < 0.25 else rng.uniform(-10.0, 10.0)
    return (f0, a0, o0), (f1, a1, o1), unipolar


def test_level_writes_never_leave_the_hull_of_the_two_settings_brute_force():
    """Every in-between state the box holds while the writes land one at a
    time stays inside [lowest trough, highest peak] of the two settings;
    a 0 V to Vpp pair never dips below 0 V; the last state is `new`."""
    import random
    rng = random.Random(65)
    seen = {'equal_amp': 0, 'equal_off': 0, 'unipolar': 0, 'both': 0}
    for _ in range(5000):
        prev, new, unipolar = _random_pair(rng)
        writes = sp.level_writes(prev, new)
        state = {'FRQ': prev[0], 'AMP': prev[1], 'OFST': prev[2]}
        lo = min(prev[2] - prev[1] / 2.0, new[2] - new[1] / 2.0)
        hi = max(prev[2] + prev[1] / 2.0, new[2] + new[1] / 2.0)
        keys = [k for w in writes for k in w]
        assert len(keys) == len(set(keys)), (prev, new, writes)
        if 'FRQ' in keys:
            assert writes[0] == {'FRQ': new[0]}, (prev, new, writes)
        for w in writes:
            for k, v in w.items():
                assert state[k] != v, ("sent an unchanged value", prev, new,
                                       writes)
            state.update(w)
            a, o = state['AMP'], state['OFST']
            assert lo - 1e-12 <= o - a / 2.0 and o + a / 2.0 <= hi + 1e-12, (
                "left the hull", prev, new, writes, state)
            if unipolar:
                assert o - a / 2.0 >= -1e-12, ("dipped below 0 V", prev, new,
                                               writes, state)
        assert (state['FRQ'], state['AMP'], state['OFST']) == new, (
            prev, new, writes, state)
        seen['equal_amp'] += prev[1] == new[1]
        seen['equal_off'] += prev[2] == new[2]
        seen['unipolar'] += unipolar
        seen['both'] += prev[1] != new[1] and prev[2] != new[2]
    # the generator really did cover the cases it claims
    assert min(seen.values()) > 500, seen


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block (run_tests.py explains why).
    # This runner stopped at the first failure until #426, so every case
    # after a broken one went unrun and unreported.
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
