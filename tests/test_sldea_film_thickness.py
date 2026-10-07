#!/usr/bin/env python3
"""The SLDEA tab's film thickness box (`#398`): where it sits, what it
says, how a preset carries it, and the run-start check that guards it.

The thickness is t0 for the plot window's field axis, E = V / t0 in
V/um, measured with the film mounted and prestretched (owner decision
2026-10-06). What is pinned here:

* The box sits under Concentration, with the device fields, and its hover
  says to measure the film mounted and prestretched. A preset carries it,
  and a preset older than the box clears it rather than leaving the last
  film's number in it.
* At Run it is checked the way the concentration is, before the worker
  exists and so before anything drives the HV: a positive number, or
  blank after a yes/no question whose default is No. A number that is
  not one is refused with nothing started.
* What reaches setup.txt, through the REAL worker: the number with its
  unit, or '(not specified)' after a Yes, and it reads back as t0 through
  the one reader whatever codec the PC's locale wrote it in.

The run-start cases drive the real sldea_run on test_sldea_interlock's
stub app: its fake signal generator records every write, and its
messagebox stand-in fails on any question it was not told to expect. The
layout case builds the real app and skips with no display.

Run: .venv/bin/python tests/test_sldea_film_thickness.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import os  # noqa: E402
import tempfile  # noqa: E402

import gui  # noqa: E402
import sldea_edge as se  # noqa: E402
import sldea_presets  # noqa: E402
import sldea_profile as sprof  # noqa: E402
import test_sldea_interlock as T  # noqa: E402

NO_T0 = 'No film thickness specified'
UM = 'µm'


def _app(tmp, thickness, dry=True, real_worker=False):
    """The interlock suite's stub app, with the thickness box typed in."""
    app = T._App(tmp, dry=dry, sgch=1, real_worker=real_worker)
    app.sldea_vars['thick_um'] = T._var(thickness)
    return app


def _not_started(app):
    """Nothing the run does happened: no claim, no worker, no camera
    pre-flight, the run.log buffer disarmed, and not one write to the
    signal generator."""
    assert not app._sldea_running
    assert getattr(app, '_sldea_live_ch', None) is None
    assert not app.worker_done.is_set()
    assert app._sldea_prelog is None
    assert 'preflight' not in app.events, app.events
    assert app.sg.writes == [], app.sg.writes


def test_a_blank_thickness_is_asked_about_and_no_stops_before_any_hv():
    """Blank: the run asks, with No as the default, and No ends it there.
    On a LIVE run the question comes after the HV questions, where the
    concentration's does, and still before the worker that drives the
    Trek exists."""
    for dry in (True, False):
        mb = T._MB(dict(T.LIVE_OK, **{NO_T0: False}))
        with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
            app = _app(tmp, '  ', dry=dry)
            app.sldea_run()
            want = ([] if dry else ['No current monitoring',
                                    'Energize HV?']) + [NO_T0]
            assert mb.titles('askyesno') == want, (dry, mb.calls)
            [(_kind, _title, msg, kw)] = [c for c in mb.calls
                                          if c[1] == NO_T0]
            assert kw.get('default') == 'no', kw
            assert 'mounted and prestretched' in msg, msg
            assert f'V/{UM}' in msg and 'by hand' in msg, msg
            _not_started(app)
            assert any(l.endswith('film thickness not specified')
                       for l in app.lines), app.lines


def test_yes_starts_without_it_and_setup_txt_says_not_specified():
    mb = T._MB({NO_T0: True})
    with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
        app = _app(tmp, '', real_worker=True)
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        T._assert_clean_run(app)
        assert mb.titles('askyesno') == [NO_T0], mb.calls
        assert app.worker_kw['film_thickness_um'] == ''
        recorded = se.film_thickness_of(os.path.join(tmp, 'RUN'))
        assert recorded == '(not specified)', recorded
        assert sprof.film_thickness_um(recorded) is None
        app.root.run_pending()


def test_a_typed_thickness_is_recorded_and_reads_back_as_t0():
    """No question, the number to the worker by keyword, and a setup.txt
    line that reads back as t0. The worker writes setup.txt with the
    locale's codec, so on a cp1252 PC the micro sign comes back as U+FFFD
    through every reader here, and t0 must survive that too."""
    for dry in (True, False):
        mb = T._MB(T.LIVE_OK)
        with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
            app = _app(tmp, ' 47.5 ', dry=dry, real_worker=True)
            app.sldea_run()
            assert app.worker_done.wait(30), (dry, app.lines)
            T._assert_clean_run(app)
            assert NO_T0 not in mb.titles(), mb.calls
            assert app.worker_kw['film_thickness_um'] == '47.5'
            recorded = se.film_thickness_of(os.path.join(tmp, 'RUN'))
            assert recorded in (f'47.5 {UM}', '47.5 \ufffdm'), recorded
            assert sprof.film_thickness_um(recorded) == 47.5
            app.root.run_pending()


def test_a_thickness_that_is_not_a_positive_number_is_refused_up_front():
    """Refused with an error, asked nothing, started nothing: the
    concentration box's rule, and a typed unit is not a number."""
    for bad in ('abc', '0', '-5', 'nan', '50 um', '5,0'):
        mb = T._MB()                          # any question at all fails
        with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
            app = _app(tmp, bad)
            app.sldea_run()
            [msg] = [c[2] for c in mb.calls if c[0] == 'showerror']
            assert (f'Film thickness ({UM}) must be a positive number'
                    in msg), msg
            assert f"'{bad}' is not one" in msg, msg
            assert mb.titles('askyesno') == [], mb.calls
            _not_started(app)
            assert app.events == [], app.events


def test_a_tab_with_no_thickness_box_asks_nothing_and_writes_no_line():
    """The stub apps of the other run-start suites have no such box, and
    a caller that predates it must start exactly as before: no question,
    None to the worker, and no line in setup.txt, as a run from before
    the box has none."""
    mb = T._MB()
    with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
        app = T._App(tmp, dry=True, sgch=1, real_worker=True)
        assert 'thick_um' not in app.sldea_vars
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        T._assert_clean_run(app)
        assert mb.titles('askyesno') == [], mb.calls
        assert app.worker_kw['film_thickness_um'] is None
        assert se.film_thickness_of(os.path.join(tmp, 'RUN')) is None
        app.root.run_pending()


def test_the_box_sits_under_concentration_and_a_preset_carries_it():
    """The real tab: the box is on the row under Concentration with its
    label, the Trek checkbutton (a drive setting) below the device
    fields, the hover says mounted and prestretched, and the preset
    round trip, including a preset older than the box."""
    import tkinter as tk
    from tkinter import ttk
    tips = []
    real_tip = gui.add_tooltip
    real_connect = gui.InstrumentControlGUI.auto_connect
    real_autostart = gui.CAM_AUTOSTART_ON_TAB

    def spy(widget, text):
        tips.append((widget, text))
        return real_tip(widget, text)
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"   (skipped: no display for Tk: {e})")
        return
    gui.add_tooltip = spy
    # no instrument hunt and no camera, as tests/test_gui_tabs.py builds it
    gui.InstrumentControlGUI.auto_connect = lambda self: None
    gui.CAM_AUTOSTART_ON_TAB = False
    try:
        app = gui.InstrumentControlGUI(root)
        box = app.sldea_vars['thick_um']
        conc = app.sldea_vars['conc_ml']
        bi, ci = box.grid_info(), conc.grid_info()
        assert int(bi['row']) == int(ci['row']) + 1, (bi, ci)
        assert int(bi['column']) == int(ci['column'])
        outf = box.master
        [label] = outf.grid_slaves(row=int(bi['row']), column=0)
        assert label.cget('text') == f'Film thickness ({UM}):'
        trek = [w for w in outf.grid_slaves()
                if isinstance(w, ttk.Checkbutton)
                and 'Trek inverts' in str(w.cget('text'))]
        assert len(trek) == 1, trek
        assert int(trek[0].grid_info()['row']) > int(bi['row'])
        [tip] = [t for w, t in tips if w is box]
        assert 'MOUNTED AND PRESTRETCHED' in tip, tip
        assert f'Film thickness: 50 {UM}' in tip, tip
        assert box.get() == ''
        box.insert(0, '47.5')
        snap = app._sldea_collect_preset()
        assert snap['thick_um'] == '47.5'
        older = {k: v for k, v in snap.items() if k != 'thick_um'}
        fields, warnings = sldea_presets.normalise_for_load(older)
        assert warnings == [], warnings
        app._sldea_apply_preset(fields)
        assert box.get() == '', "an older preset kept the last film's t0"
        app._sldea_apply_preset(dict(fields, thick_um='30'))
        assert box.get() == '30'
    finally:
        gui.add_tooltip = real_tip
        gui.InstrumentControlGUI.auto_connect = real_connect
        gui.CAM_AUTOSTART_ON_TAB = real_autostart
        root.destroy()


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
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
