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
import threading

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
        # armed, so neither record says otherwise
        assert 'NOT armed' not in setup, setup
        assert not any('NOT ARMED' in ln for ln in app.lines), app.lines


def test_a_scope_lost_before_the_arming_line_is_recorded_not_armed():
    """HV review 2026-10-08, finding 2; the owner chose to run on and say
    so. A LIVE Reconnect confirmed in the run's first seconds (#339): the
    scope is gone where the worker resolves the camera, before its arming
    line, and back 0.3 s later. The run goes on unwatched, as before, and
    at 120 uA over the 100 uA trip nothing stops it; now run.log carries
    the NOT ARMED warning and setup.txt an ASCII line, while the start
    records still say ON, as "Energize HV?" did."""
    with tempfile.TemporaryDirectory() as tmp:
        mb = L._MB(L.LIVE_OK)
        with L._patched(mb):
            app = L._App(tmp, dry=False, real_worker=True, wd_on=True)
            app.sldea_tel_on = L._Field(True)
            app.sldea_vars['wd_ua'].set('100')
            app.sldea_vars['wd_s'].set('1')
            app._sldea_build_profile = lambda: (
                L._short_profile(landing_s=6.0), None)
            scope = app.scope
            scope.volts = lambda ch: (0.6 if ch == 3 and L._ramping(app)
                                      else 0.0)

            def reconnect_now(idx):
                app.scope = None                 # what _reconnect does
                threading.Timer(
                    0.3, lambda: setattr(app, 'scope', scope)).start()
                return {'kind': 'cv2', 'index': int(idx)}
            gui.webcam.resolve_camera = reconnect_now   # _patched restores
            app.sldea_run()
            assert app.worker_done.wait(60), app.lines
            assert app.worker_error is None, repr(app.worker_error)
            app.root.run_pending()
        assert app.worker_args[11:14] == (True, 100.0, 1.0), \
            app.worker_args[11:14]
        assert any(ln.startswith('run complete') for ln in app.lines), \
            app.lines
        assert not app._sldea_bd_tripped
        [hv] = [c[2] for c in mb.calls if c[1] == 'Energize HV?']
        assert "\n\nBreakdown watchdog: ON. " in hv, hv
        assert ('  [watchdog: dev ≥100 µA for 1s, baseline learned at '
                '0 kV]') in _start_line(app)
        [warn] = [ln for ln in app.lines if 'NOT ARMED' in ln]
        assert warn.startswith("⚠⚠ BREAKDOWN WATCHDOG NOT ARMED — the scope "
                               "was gone when the run reached the arming "
                               "line"), warn
        assert "Nothing stops this run on a breakdown" in warn, warn
        setup = _read(os.path.join(_rundir(tmp), 'setup.txt'))
        assert "\nBreakdown watchdog: ON, trips when " in setup, setup
        assert "\nBreakdown watchdog (start): NOT armed (no scope)\n" in \
            setup, setup
        with open(os.path.join(_rundir(tmp), 'setup.txt'), 'rb') as f:
            f.read().decode('ascii')     # still ASCII, line and all
        assert se.load_settings(_rundir(tmp))['diam_mm'] == 16.0


class _MBThen(L._MB):
    """_MB, plus a callback run once a given question has been answered:
    where a scope Reconnect's done callback lands when it finishes inside
    that dialog's nested event loop."""

    def __init__(self, answers, then):
        super().__init__(answers)
        self.then = dict(then)

    def askyesno(self, title, message, **kw):
        answer = super().askyesno(title, message, **kw)
        fn = self.then.pop(title, None)
        if fn is not None:
            fn()
        return answer


def _assert_refused_at_the_commit_point(app, mb, tmp, change):
    """Refused after "Energize HV?" was answered Yes, with nothing sent to
    the SG and nothing left in a started state."""
    hv = [c for c in mb.calls if c[1] == 'Energize HV?']
    assert len(hv) == 1, mb.calls
    [(kind, title, msg, _kw)] = [c for c in mb.calls if c[0] != 'askyesno']
    assert (kind, title) == ('showerror', 'SLDEA — run blocked'), mb.calls
    assert msg.startswith("The breakdown watchdog's state changed since "
                          "Energize HV? (" + change + ")."), msg
    assert "Nothing was sent to the signal generator." in msg, msg
    assert any(ln.startswith("run refused — the breakdown watchdog's state "
                             "changed since Energize HV? (" + change + ")")
               for ln in app.lines), app.lines
    assert app.worker_args is None, "a refused run started its worker"
    assert app.sg.writes == [], app.sg.writes
    assert not os.path.exists(_rundir(tmp))
    assert not app._sldea_running and not app._sldea_starting
    assert app._sldea_live_ch is None and app._sldea_scope_chs is None
    assert app._sldea_prelog is None


def test_a_watchdog_state_that_changed_under_a_question_refuses_the_run():
    """HV review 2026-10-08, finding 1. sldea_run reads the watchdog's
    state before its questions, and a scope Reconnect whose done callback
    runs inside one of them changes it. Both ways are refused at the
    commit point, before any SG write, and Run works again afterwards:
    - the scope mid-Reconnect (None) when Run is pressed, back while "No
      current monitoring" is open: "Energize HV?" said OFF (no scope), and
      the run would have gone unarmed beside a connected scope at 120 uA
      (before the fix it ran to its end; main armed and tripped);
    - the scope there when Run is pressed, gone while "Energize HV?" is
      open: everything said ON for a run that could not arm.
    Then the same ticked run with nothing changing arms and trips at
    120 uA over the 100 uA trip, as on main."""
    def run(tmp, mb, scope_at_run, change_after):
        with L._patched(mb):
            app = L._App(tmp, dry=False, real_worker=True, wd_on=True)
            scope = app.scope
            app.sldea_vars['wd_ua'].set('100')
            app.sldea_vars['wd_s'].set('1')
            app._sldea_build_profile = lambda: (
                L._short_profile(landing_s=6.0), None)
            scope.volts = lambda ch: (0.6 if ch == 3 and L._ramping(app)
                                      else 0.0)
            mb.then = {change_after: (
                (lambda: setattr(app, 'scope', scope)) if not scope_at_run
                else (lambda: setattr(app, 'scope', None)))}
            if not scope_at_run:
                app.scope = None             # the Reconnect in flight
            app.sldea_run()
            app.root.run_pending()
        return app, scope

    # the scope comes back inside "No current monitoring"
    with tempfile.TemporaryDirectory() as tmp:
        mb = _MBThen({'No current monitoring': True, 'Energize HV?': True},
                     {})
        app, scope = run(tmp, mb, False, 'No current monitoring')
        assert mb.titles('askyesno') == ['No current monitoring',
                                         'Energize HV?'], mb.calls
        hv = [c[2] for c in mb.calls if c[1] == 'Energize HV?'][0]
        assert "Breakdown watchdog: OFF (no scope to read the current)" in \
            hv, hv
        assert app.scope is scope
        _assert_refused_at_the_commit_point(
            app, mb, tmp, "OFF (no scope to read the current) → ON")

        # ...and Run pressed again, nothing changing now: armed, and it
        # trips at 120 uA over the 100 uA trip, as main does
        mb2 = L._MB(L.LIVE_OK)
        with L._patched(mb2):
            app.sldea_run()
            assert app.worker_done.wait(60), app.lines
            assert app.worker_error is None, repr(app.worker_error)
            app.root.run_pending()
        assert app.worker_args[11:14] == (True, 100.0, 1.0), \
            app.worker_args[11:14]
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('run BREAKDOWN-ABORT') for ln in
                   app.lines), app.lines
        assert app.sg.writes[-2:] == [('set_offset', 1, 0.0),
                                      ('set_output', 1, False)], \
            app.sg.writes[-4:]

    # the scope goes inside "Energize HV?"
    with tempfile.TemporaryDirectory() as tmp:
        mb = _MBThen({'Energize HV?': True}, {})
        app, _scope = run(tmp, mb, True, 'Energize HV?')
        hv = [c[2] for c in mb.calls if c[1] == 'Energize HV?'][0]
        assert "Breakdown watchdog: ON." in hv, hv
        _assert_refused_at_the_commit_point(
            app, mb, tmp, "ON → OFF (no scope to read the current)")


def test_the_short_state_words_match_the_records():
    assert sp.watchdog_state(True, True, False) == 'ON'
    for ticked, armed, dry in ((False, False, False), (True, False, False),
                               (True, False, True), (False, False, True)):
        assert sp.watchdog_record(ticked, armed, dry, 100.0, 3.0)[0] == (
            'Breakdown watchdog: ' + sp.watchdog_state(ticked, armed, dry))


BAD_WATCHDOG_VALUES = ('nan', 'inf', '0', '-5', 'abc')


def test_the_watchdog_boxes_parse_to_positive_finite_numbers_only():
    for good, value in (('100', 100.0), (' 2.5 ', 2.5), ('1e2', 100.0)):
        assert sp.parse_watchdog_value(good) == value, good
    for bad in BAD_WATCHDOG_VALUES + ('', '  ', '-inf', 'NaN', None):
        try:
            sp.parse_watchdog_value(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} was accepted")


def test_a_ticked_live_run_refuses_a_trip_or_confirm_it_cannot_use():
    """HV review 2026-10-08: ticked on a LIVE run, a Trip or Confirm that
    is not a finite number above zero refuses Run before any question,
    with a message naming the box. The fault predates #406, but the
    records now quote these boxes as the rule: "abc" used to run as
    100 uA / 3 s unsaid, nan and inf never trip, a zero or negative trip
    fires on every read. Nothing is asked, driven or made."""
    for key, box, default in (('wd_ua', 'Trip (µA)', '100'),
                              ('wd_s', 'Confirm (s)', '3')):
        for bad in BAD_WATCHDOG_VALUES:
            with tempfile.TemporaryDirectory() as tmp:
                mb = L._MB({})          # any question fails the test
                with L._patched(mb):
                    app = L._App(tmp, dry=False, wd_on=True)
                    app.sldea_vars[key].set(bad)
                    app.sldea_run()
                assert [c[:2] for c in mb.calls] == \
                    [('showerror', 'SLDEA')], (box, bad, mb.calls)
                msg = mb.calls[0][2]
                assert msg.startswith(
                    f"Breakdown watchdog {box} must be a positive number — "
                    f"'{bad}' is not one."), msg
                assert f"(the default is {default})" in msg, msg
                assert any(ln.startswith(f"run refused — breakdown watchdog "
                                         f"{box} is '{bad}'")
                           for ln in app.lines), app.lines
                assert app.worker_args is None, (box, bad)
                assert app.sg.writes == [], app.sg.writes
                assert not os.path.exists(_rundir(tmp))
                assert app._sldea_prelog is None
                assert not getattr(app, '_sldea_starting', False)


def test_a_dry_or_unticked_run_is_not_refused_for_the_watchdog_boxes():
    """Neither arms anything from the boxes, so neither is refused for
    them: the unticked LIVE run reaches "Energize HV?" (answered No) and
    says OFF, and the ticked DRY run starts and records OFF. A good value
    on a ticked LIVE run reaches "Energize HV?" with that value."""
    for bad in BAD_WATCHDOG_VALUES:
        with tempfile.TemporaryDirectory() as tmp:
            mb = L._MB({'Energize HV?': False})
            with L._patched(mb):
                app = L._App(tmp, dry=False, wd_on=False)
                app.sldea_vars['wd_ua'].set(bad)
                app.sldea_vars['wd_s'].set(bad)
                app.sldea_run()
            assert mb.titles() == ['Energize HV?'], (bad, mb.calls)
            assert ("\n\n" + OFF_DIALOG + "\n\nProceed?") in mb.calls[0][2]
        with tempfile.TemporaryDirectory() as tmp:
            mb = L._MB({})
            with L._patched(mb):
                app = L._App(tmp, dry=True, wd_on=True)
                app.sldea_vars['wd_ua'].set(bad)
                app.sldea_vars['wd_s'].set(bad)
                app.sldea_run()
                assert app.worker_done.wait(10), app.lines
            assert mb.calls == [], (bad, mb.calls)
            assert app.worker_args[11] is False
            assert '  [watchdog: OFF (dry run, no HV)]' in _start_line(app)
    with tempfile.TemporaryDirectory() as tmp:
        mb = L._MB({'Energize HV?': False})
        with L._patched(mb):
            app = L._App(tmp, dry=False, wd_on=True)
            app.sldea_vars['wd_ua'].set(' 50 ')
            app.sldea_vars['wd_s'].set('2.5')
            app.sldea_run()
        assert mb.titles() == ['Energize HV?'], mb.calls
        assert ("stays 50 µA or more away from the baseline it learns at "
                "0 kV, for 2.5 s of consecutive reads.") in mb.calls[0][2]


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
