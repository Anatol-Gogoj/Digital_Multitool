#!/usr/bin/env python3
"""Every run names its breakdown watchdog's state; the box starts ticked
(#406).

Owner decision 2026-10-08: the box stays ticked by default. Its 100 uA /
3 s rule misses small breakdowns (#219), but it is the only thing that
stops a LIVE run on a breakdown, and replayed on the single-layer runs on
file it stops none that was not breaking down. An unticked box means
nothing stops a LIVE run on a breakdown, so "Energize HV?" names the
watchdog's state, and run.log and setup.txt record it in every run, ON
with its rule or OFF with the reason. One function words all three
(sldea_profile.watchdog_record), from the same reading sldea_run hands
the worker. A preset saved unticked still loads unticked.

The LIVE runs below are the real sldea_run and the real worker, on the
scope-lock suite's fakes (tests/test_scope_live_lock.py): a scope that
answers, an SG that records, no camera.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import gui  # noqa: E402
import sldea_edge as se  # noqa: E402
import sldea_presets  # noqa: E402
import sldea_profile as sp  # noqa: E402
import test_scope_live_lock as L  # noqa: E402

OFF_DIALOG = ("Breakdown watchdog: OFF. Nothing stops this run on a "
              "breakdown; only ■ Abort or the end of the run does.")


class _Skip(Exception):
    pass


def _real_app():
    """(root, app): the real main window, every tab built, or _Skip."""
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    gui.InstrumentControlGUI.auto_connect = lambda self: None
    app = gui.InstrumentControlGUI(root)
    root.update_idletasks()
    return root, app


def _rundir(tmp):
    return os.path.join(tmp, 'RUN')


def _read(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()


def _start_line(app):
    hits = [ln for ln in app.lines if ' start — ' in ln]
    assert len(hits) == 1, app.lines
    return hits[0]


def _live_run(tmp, ticked, trip_ua='100', confirm_s='3', current_v=None,
              landing_s=2.0):
    """A real LIVE run to its end; -> (app, mb). `current_v` is the I_Out
    monitor voltage once the ramp has started (0.6 V = 120 uA)."""
    mb = L._MB(L.LIVE_OK)
    with L._patched(mb):
        app = L._App(tmp, dry=False, real_worker=True, wd_on=ticked)
        app.sldea_vars['wd_ua'].set(trip_ua)
        app.sldea_vars['wd_s'].set(confirm_s)
        app._sldea_build_profile = lambda: (
            L._short_profile(landing_s=landing_s), None)
        if current_v is not None:
            app.scope.volts = lambda ch: (current_v if ch == 3
                                          and L._ramping(app) else 0.0)
        app.sldea_run()
        assert app.worker_done.wait(60), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        app.root.run_pending()
    return app, mb


# --------------------------------------------------------------------------
# The default, and presets
# --------------------------------------------------------------------------

def test_the_box_starts_ticked_on_the_real_tab():
    root, app = _real_app()
    try:
        assert app.sldea_wd_on.get() is True
        # and it is the variable the watchdog frame's "Enabled" box shows
        # (the telemetry frame has an "Enabled" box of its own)
        boxes = []

        def walk(w):
            for c in w.winfo_children():
                if (c.winfo_class() == 'TCheckbutton'
                        and c.cget('text') == 'Enabled'
                        and c.master.winfo_class() == 'TLabelframe'
                        and str(c.master.cget('text')).startswith(
                            '⚡ Breakdown watchdog')):
                    boxes.append(c)
                walk(c)
        walk(root)
        assert [str(b.cget('variable')) for b in boxes] == \
            [str(app.sldea_wd_on)], boxes
    finally:
        root.destroy()


def test_a_preset_loads_the_box_as_it_was_saved():
    root, app = _real_app()
    try:
        # a preset written before the box existed, on a fresh tab, leaves
        # the default (ticked) as it is, and says so
        fields, warn = sldea_presets.normalise_for_load({'wd_ua': '100'})
        app._sldea_apply_preset(fields)
        assert app.sldea_wd_on.get() is True
        assert any(w.startswith('Watchdog enabled is not in this preset')
                   for w in warn), warn
        # a preset saved unticked loads unticked, one saved ticked ticked
        for saved in (False, True, False):
            fields, _warn = sldea_presets.normalise_for_load(
                {'wd_on': saved})
            app._sldea_apply_preset(fields)
            assert app.sldea_wd_on.get() is saved, saved
    finally:
        root.destroy()


# --------------------------------------------------------------------------
# The words
# --------------------------------------------------------------------------

def test_one_function_words_every_state():
    on = sp.watchdog_record(True, True, False, 75.0, 2.0)
    assert on == (
        "Breakdown watchdog: ON, trips when |I - baseline| >= 75 uA for "
        "2 s of consecutive reads (baseline learned at 0 kV; absolute |I| "
        "if that baseline is refused)",
        "watchdog: dev ≥75 µA for 2s, baseline learned at 0 kV",
        "Breakdown watchdog: ON. The run stops itself when the current "
        "stays 75 µA or more away from the baseline it learns at 0 kV, "
        "for 2 s of consecutive reads."), on
    assert sp.watchdog_record(False, False, False, 75.0, 2.0) == (
        "Breakdown watchdog: OFF (box unticked)",
        "watchdog: OFF (box unticked)", OFF_DIALOG)
    no_scope = sp.watchdog_record(True, False, False, 75.0, 2.0)
    assert no_scope[0] == ("Breakdown watchdog: OFF (no scope to read the "
                           "current)"), no_scope
    assert no_scope[2].startswith("Breakdown watchdog: OFF (no scope to "
                                  "read the current). Nothing stops"), \
        no_scope
    for ticked in (True, False):
        dry = sp.watchdog_record(ticked, False, True, 75.0, 2.0)
        assert dry[:2] == ("Breakdown watchdog: OFF (dry run, no HV)",
                           "watchdog: OFF (dry run, no HV)"), dry
    # the setup.txt line is ASCII: the worker writes it in the locale
    # encoding, and a cp1252 or C locale must not refuse it
    for args in ((True, True, False, 100.0, 3.0),
                 (False, False, False, 100.0, 3.0),
                 (True, False, False, 100.0, 3.0),
                 (True, False, True, 100.0, 3.0)):
        line = sp.watchdog_record(*args)[0]
        line.encode('ascii')
        assert line.startswith('Breakdown watchdog: '), line


def test_setup_text_puts_the_line_under_i_out_and_none_adds_nothing():
    p = sp.SldeaProfile(start_kv=0, end_kv=1, step_kv=1)
    base = p.setup_text('R', 'iso', 1, 2, 3, False)
    line = sp.watchdog_record(False, False, False, 100.0, 3.0)[0]
    text = p.setup_text('R', 'iso', 1, 2, 3, False, watchdog=line)
    assert text.replace(line + "\n", "", 1) == base
    rows = text.splitlines()
    i = rows.index(line)
    assert rows[i - 1].startswith('I_Out: scope CH3'), rows[i - 1]
    assert rows[i + 1] == '' and rows[i + 2] == '--- Camera ---', rows


# --------------------------------------------------------------------------
# What a run does with it
# --------------------------------------------------------------------------

def test_energize_hv_names_the_watchdog_off_and_on():
    """Cancelled at "Energize HV?" each time, so nothing is driven. The
    title and the default (No, so Enter cancels) are what they were."""
    cases = (
        (False, True, OFF_DIALOG),
        (True, True, "Breakdown watchdog: ON. The run stops itself when "
                     "the current stays 75 µA or more away from the "
                     "baseline it learns at 0 kV, for 2 s of consecutive "
                     "reads."),
        (True, False, "Breakdown watchdog: OFF (no scope to read the "
                      "current). Nothing stops this run on a breakdown; "
                      "only ■ Abort or the end of the run does."),
    )
    for ticked, scope, words in cases:
        with tempfile.TemporaryDirectory() as tmp:
            mb = L._MB({'Energize HV?': False,
                        'No current monitoring': True})
            with L._patched(mb):
                app = L._App(tmp, dry=False, wd_on=ticked)
                app.sldea_vars['wd_ua'].set('75')
                app.sldea_vars['wd_s'].set('2')
                if not scope:
                    app.scope = None
                app.sldea_run()
            [hv] = [c for c in mb.calls if c[1] == 'Energize HV?']
            kind, _title, msg, kw = hv
            assert kind == 'askyesno' and kw == {'default': 'no'}, hv
            assert msg.startswith("LIVE run — this drives the Trek up to "
                                  "1 kV via SG CH1."), msg
            assert msg.endswith("\n\n" + words + "\n\nProceed?"), msg
            assert app.worker_args is None, "a cancelled run started"
            assert app.sg.writes == [], app.sg.writes
            assert not os.path.exists(_rundir(tmp))


def test_an_unticked_live_run_arms_nothing_and_records_off():
    """What unticking costs, shown in small: 120 uA, over the 100 uA trip,
    from the ramp on, and the run still goes to its end, because nothing
    watches. Its records now say so."""
    with tempfile.TemporaryDirectory() as tmp:
        app, _mb = _live_run(tmp, ticked=False, confirm_s='1',
                             current_v=0.6, landing_s=4.0)
        assert app.worker_args[11] is False, app.worker_args[11:14]
        assert any(ln.startswith('run complete') for ln in app.lines), \
            app.lines
        assert not app._sldea_bd_tripped
        assert not any('BREAKDOWN' in ln for ln in app.lines), app.lines
        assert '  [watchdog: OFF (box unticked)]' in _start_line(app)
        setup = _read(os.path.join(_rundir(tmp), 'setup.txt'))
        assert "\nBreakdown watchdog: OFF (box unticked)\n" in setup, setup
        # the readers of setup.txt still read it
        assert se.load_settings(_rundir(tmp))['diam_mm'] == 16.0
        health = se._health_setup(_rundir(tmp))
        assert health['planned'] and health['camera'].startswith(
            'exposure '), health


def test_a_ticked_live_run_arms_it_as_before_and_records_on():
    with tempfile.TemporaryDirectory() as tmp:
        app, _mb = _live_run(tmp, ticked=True, confirm_s='1',
                             current_v=0.6, landing_s=6.0)
        assert app.worker_args[11:14] == (True, 100.0, 1.0), \
            app.worker_args[11:14]
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('run BREAKDOWN-ABORT') for ln in
                   app.lines), app.lines
        assert ('  [watchdog: dev ≥100 µA for 1s, baseline learned at '
                '0 kV]') in _start_line(app)
        setup = _read(os.path.join(_rundir(tmp), 'setup.txt'))
        assert ("\nBreakdown watchdog: ON, trips when |I - baseline| >= "
                "100 uA for 1 s of consecutive reads (baseline learned at "
                "0 kV; absolute |I| if that baseline is refused)\n") in \
            setup, setup


def test_a_dry_run_records_off_whatever_the_box_says():
    for ticked in (True, False):
        with tempfile.TemporaryDirectory() as tmp:
            mb = L._MB({})
            with L._patched(mb):
                app = L._App(tmp, dry=True, real_worker=True, wd_on=ticked)
                app._sldea_build_profile = lambda: (L._short_profile(), None)
                app.sldea_run()
                assert app.worker_done.wait(60), app.lines
                assert app.worker_error is None, repr(app.worker_error)
                app.root.run_pending()
            assert mb.titles() == [], mb.calls
            assert app.worker_args[11] is False
            assert '  [watchdog: OFF (dry run, no HV)]' in _start_line(app)
            setup = _read(os.path.join(_rundir(tmp), 'setup.txt'))
            assert "\nBreakdown watchdog: OFF (dry run, no HV)\n" in setup


def _run():
    # Failures are collected, not fatal (`#280`); a case that cannot run
    # here (no display) is counted as skipped, not passed.
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed, skipped = [], []
    for fn in fns:
        try:
            fn()
        except _Skip as e:
            skipped.append((fn.__name__, str(e)))
            print(f"skip {fn.__name__}: {e}")
            continue
        except Exception:
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
        print(f"ok  {fn.__name__}")
    ran = len(fns) - len(skipped)
    if not failed:
        print(f"\n{ran} of {len(fns)} tests ran" if skipped
              else f"\n{len(fns)} tests passed")
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
