#!/usr/bin/env python3
"""The #219 N-sigma breakdown rule, run in SHADOW on every LIVE run.

Owner decision 2026-10-08: build the N-sigma rule now and run it in shadow:
it reads the very current the monitor tick already reads, records what it
would have done (one telemetry event row, one run.log line and one
setup.txt line after the SG is zeroed), and acts on nothing. Every away
read, a lone one included, is listed too, in one run.log entry after the
SG is zeroed, so the owner can decide later whether a single away read is
a breakdown. BreakdownWatchdog (100 uA for 3 s) still stops runs. No
single-read spike tier. Defaults N 5, floor 20 uA, 2 reads in a row,
window 40, chosen on the 18 single-layer runs replayed on 2026-10-08
(SLDEA_DECISIONS.md).

The first half pins the rule itself, on made-up reads and on short traces
copied from real runs (numbers only). The second half runs the real
sldea_run and worker on the scope-lock suite's fakes
(tests/test_scope_live_lock.py) and checks that the shadow never changes
a run.
"""
import csv
import os
import random
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import gui  # noqa: E402
import sldea_edge as se  # noqa: E402
import sldea_profile as sp  # noqa: E402
import test_scope_live_lock as L  # noqa: E402


class _Skip(Exception):
    pass


def _feed(wd, reads, t0=0.0, dt=0.5):
    """Feed (kv, ua) or (kv, ua, offscreen) reads 0.5 s apart; -> the time
    of the first would-trip, or None."""
    t = t0
    for r in reads:
        kv, ua = r[0], r[1]
        off = r[2] if len(r) > 2 else False
        if wd.update(t, kv, ua, offscreen=off):
            return t
        t += dt
    return None


def _landing(kv, values):
    return [(kv, v) for v in values]


def _settled(kv, ua, n):
    """n reads at one landing: the first two fall in its settle second."""
    return [(kv, ua)] * n


# --------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------

def test_the_defaults_are_the_ones_the_replay_chose():
    d = sp.NSIGMA_DEFAULTS
    assert (d['n_sigma'], d['dev_min'], d['k_consec'], d['window']) == \
        (5.0, 20.0, 2, 40), d
    wd = sp.NSigmaWatchdog()
    assert (wd.n_sigma, wd.dev_min, wd.k_consec, wd.window, wd.guard,
            wd.w_min, wd.settle_s, wd.ramp_factor, wd.sigma_floor) == \
        (5.0, 20.0, 2, 40, 2, 10, 1.0, 2.0, 0.5)
    # and the 20 uA floor is the after-the-fact detector's own number, so
    # the live and post-hoc verdicts draw the same line
    assert float(se.DEFAULT_SETTINGS['breakdown_dev_ua']) == d['dev_min']


def test_quiet_noise_across_a_staircase_never_trips():
    """13_backlight's kind of run: about +-3 uA of read noise around 0,
    a staircase of landings with ramps between."""
    rnd = random.Random(7)
    wd = sp.NSigmaWatchdog(base_loc=0.0, base_sigma=1.0)
    reads = []
    for step in range(12):
        kv0, kv1 = 0.25 * step, 0.25 * (step + 1)
        reads += [(kv0 + (kv1 - kv0) * f, rnd.gauss(0, 1.2))
                  for f in (0.25, 0.5, 0.75)]           # the ramp
        reads += [(kv1, max(-3.5, min(3.5, rnd.gauss(0, 1.2))))
                  for _ in range(60)]                   # a 30 s landing
    assert _feed(wd, reads) is None, wd.outcome_text()
    assert wd.n_reads == len(reads)
    assert wd.outcome_text().startswith(f"no trip in {len(reads)} reads"), \
        wd.outcome_text()


def test_a_held_step_trips_on_the_second_away_read():
    """152205's size of event: 26.5 uA off a quiet location, held."""
    wd = sp.NSigmaWatchdog(base_loc=1.0, base_sigma=0.3)
    reads = _settled(5.5, 1.0, 30) + _settled(5.5, -25.5, 5)
    t = _feed(wd, reads)
    assert t == 0.5 * 31, t                  # the second away read
    assert wd.how == 'away, 2 reads in a row', wd.how
    text = wd.outcome_text()
    assert text.startswith('would trip at 15.5 s (5.50 kV): I -25.5 uA, '
                           '26.5 uA from location 1.0 uA (bar 20.0 uA'), text
    text.encode('ascii')


def test_one_away_read_never_trips():
    """104531, P3_7 and an operator run: one read far off, then back."""
    for spike in (-153.4, -64.0, -24.4):
        wd = sp.NSigmaWatchdog(base_loc=-16.0, base_sigma=0.3)
        reads = (_settled(6.75, -16.0, 30) + [(6.75, spike)]
                 + _settled(6.75, -16.0, 30))
        assert _feed(wd, reads) is None, (spike, wd.outcome_text())
        assert wd.peak['dev'] >= abs(spike + 16.0) - 1e-9


def test_off_screen_counts_as_away_but_one_read_alone_does_not_trip():
    wd = sp.NSigmaWatchdog(base_loc=-16.0, base_sigma=0.3)
    reads = (_settled(1.0, -16.0, 20) + [(1.0, None, True)]
             + _settled(1.0, -16.0, 5))
    assert _feed(wd, reads) is None, wd.outcome_text()
    wd = sp.NSigmaWatchdog(base_loc=-16.0, base_sigma=0.3)
    reads = _settled(1.0, -16.0, 20) + [(1.0, None, True)] * 2
    assert _feed(wd, reads) == 0.5 * 21
    assert wd.how == 'off-screen, 2 reads in a row'
    assert "the current was off the scope's screen" in wd.outcome_text()


# --------------------------------------------------------------------------
# Every away read is kept (owner, 2026-10-08: log every single away read in
# shadow, then decide whether a single-read excursion is a breakdown)
# --------------------------------------------------------------------------

def test_a_lone_away_read_is_listed_though_it_never_trips():
    """One read 30 uA off at a settled landing, then back: no would-trip,
    and one away line with the time, kV, reading, location, deviation and
    bar."""
    wd = sp.NSigmaWatchdog(base_loc=-16.0, base_sigma=0.3)
    reads = (_settled(6.75, -16.0, 30) + [(6.75, -46.0)]
             + _settled(6.75, -16.0, 10))
    assert _feed(wd, reads) is None, wd.outcome_text()
    assert wd.n_away == 1 and len(wd.away) == 1, wd.away
    lines = wd.away_lines()
    assert lines == [
        "1 away read in 41 reads",
        "away at 15.0 s (6.75 kV, landing): I -46.0 uA, 30.0 uA from "
        "location -16.0 uA (bar 20.0 uA, sigma 0.50 uA); 1 in a row"], lines
    for line in lines:
        line.encode('ascii')


def test_an_off_screen_read_is_listed_as_off_screen():
    wd = sp.NSigmaWatchdog(base_loc=-16.0, base_sigma=0.3)
    reads = (_settled(1.0, -16.0, 20) + [(1.0, None, True)]
             + _settled(1.0, -16.0, 5))
    assert _feed(wd, reads) is None, wd.outcome_text()
    assert wd.away_lines() == [
        "1 away read in 26 reads",
        "away at 10.0 s (1.00 kV, landing): off the scope's screen "
        "(location -16.0 uA); 1 in a row"], wd.away_lines()


def test_k_away_reads_in_a_row_are_each_listed_and_trip_once():
    """152205's size of step, held: both away reads are listed, the second
    marked, and the rule trips once, at the second, as before."""
    wd = sp.NSigmaWatchdog(base_loc=1.0, base_sigma=0.3)
    reads = _settled(5.5, 1.0, 30) + _settled(5.5, -25.5, 5)
    assert _feed(wd, reads) == 0.5 * 31, wd.outcome_text()
    # nothing is judged after the would-trip: no second trip, no more lines
    for k in range(4):
        assert wd.update(16.0 + 0.5 * k, 5.5, -25.5) is True
    assert wd.trip['t'] == 15.5, wd.trip
    assert wd.n_away == 2, wd.away
    lines = wd.away_lines()
    assert len(lines) == 3, lines
    assert lines[0] == "2 away reads in 32 reads", lines
    assert lines[1] == ("away at 15.0 s (5.50 kV, landing): I -25.5 uA, "
                        "26.5 uA from location 1.0 uA (bar 20.0 uA, sigma "
                        "0.50 uA); 1 in a row"), lines
    assert lines[2].startswith("away at 15.5 s (5.50 kV, landing): "), lines
    assert lines[2].endswith("; 2 in a row, would trip"), lines


def test_quiet_noise_lists_no_away_read():
    """The quiet staircase above: no away read, so nothing to list."""
    rnd = random.Random(7)
    wd = sp.NSigmaWatchdog(base_loc=0.0, base_sigma=1.0)
    reads = []
    for step in range(12):
        kv0, kv1 = 0.25 * step, 0.25 * (step + 1)
        reads += [(kv0 + (kv1 - kv0) * f, rnd.gauss(0, 1.2))
                  for f in (0.25, 0.5, 0.75)]
        reads += [(kv1, max(-3.5, min(3.5, rnd.gauss(0, 1.2))))
                  for _ in range(60)]
    assert _feed(wd, reads) is None, wd.outcome_text()
    assert wd.n_reads == len(reads)
    assert (wd.n_away, wd.away, wd.away_lines()) == (0, [], []), wd.away


def test_the_away_list_is_capped_and_says_how_many_it_left_out():
    assert sp.NSIGMA_AWAY_LOG_MAX == 100
    # lone away reads, each followed by a quiet one: none trips the rule
    wobble = [(2.0, 30.0), (2.0, 0.0)] * 150
    wd = sp.NSigmaWatchdog(base_loc=0.0, base_sigma=0.3)
    assert wd.away_max == 100
    assert _feed(wd, _settled(2.0, 0.0, 20) + wobble) is None, \
        wd.outcome_text()
    assert (wd.n_away, len(wd.away)) == (150, 100), (wd.n_away,
                                                     len(wd.away))
    lines = wd.away_lines()
    assert lines[0] == ("150 away reads in 320 reads; the first 100 "
                        "listed, 50 more not"), lines[0]
    assert len(lines) == 101, len(lines)
    # and a smaller cap holds the same way
    wd = sp.NSigmaWatchdog(base_loc=0.0, base_sigma=0.3, away_max=3)
    _feed(wd, _settled(2.0, 0.0, 20) + wobble[:10])
    assert wd.away_lines()[0] == ("5 away reads in 30 reads; the first 3 "
                                  "listed, 2 more not"), wd.away_lines()


def test_an_unreadable_read_neither_extends_nor_breaks_the_streak():
    wd = sp.NSigmaWatchdog(base_loc=0.0, base_sigma=0.3)
    reads = _settled(2.0, 0.0, 20) + [(2.0, 30.0), (2.0, None), (2.0, 30.0)]
    assert _feed(wd, reads) == 0.5 * 22, wd.outcome_text()
    assert wd.n_reads == 22                  # the unreadable read not counted


def test_ramps_and_settling_landings_double_the_bar():
    """A 30 uA departure: away at a settled landing (bar 20 uA), not on a
    ramp or in a landing's first second (bar 40 uA)."""
    wd = sp.NSigmaWatchdog(base_loc=0.0, base_sigma=0.3)
    ramp = [(1.0 + 0.1 * i, 30.0) for i in range(1, 6)]
    assert _feed(wd, _settled(1.0, 0.0, 20) + ramp) is None, \
        wd.outcome_text()
    # the new landing's first second still settles: two reads in it at
    # 30 uA (at 11.0 s and 11.5 s; the landing begins at 11.0 s) are not
    # away against the doubled bar
    wd = sp.NSigmaWatchdog(base_loc=0.0, base_sigma=0.3)
    reads = _settled(1.0, 0.0, 20) + [(1.5, 0.0)] + [(2.0, 30.0)] * 3
    assert _feed(wd, reads) is None, wd.outcome_text()
    # settled, the same departure is away
    wd = sp.NSigmaWatchdog(base_loc=0.0, base_sigma=0.3)
    reads = _settled(1.0, 0.0, 20) + [(2.0, 0.0)] * 4 + [(2.0, 30.0)] * 2
    assert _feed(wd, reads) is not None, wd.outcome_text()


def test_the_window_follows_slow_drift_and_away_reads_never_enter_it():
    wd = sp.NSigmaWatchdog(base_loc=0.0, base_sigma=0.3)
    # leakage creeping by 0.05 uA a read for 400 reads: 20 uA in all, but
    # followed, so never away
    assert _feed(wd, [(3.0, -0.05 * i) for i in range(400)]) is None, \
        wd.outcome_text()
    loc, _sig = wd.stats()
    assert -20.0 < loc < -17.0, loc
    # an excursion is not learned: with K raised so nothing trips, the
    # location does not move while it lasts
    wd = sp.NSigmaWatchdog(base_loc=0.0, base_sigma=0.3, k_consec=1000)
    _feed(wd, _settled(3.0, 0.0, 30))
    before = wd.stats()
    _feed(wd, _settled(3.0, -40.0, 50), t0=15.0)
    assert wd.stats() == before, (before, wd.stats())


def test_with_no_baseline_settled_reads_seed_the_window_first():
    """No 0 kV baseline (the watchdog unticked, telemetry on): nothing is
    judged until w_min + guard settled landing reads have seeded the
    window, and then a step trips. The desk prototype judged reads before
    it had a location, so its window never filled and it could not trip."""
    wd = sp.NSigmaWatchdog()
    assert wd.stats() == (None, None)
    reads = [(1.0, 10.0)] * 2 + _settled(1.0, 10.0, 12)
    assert _feed(wd, reads) is None
    loc, sig = wd.stats()
    assert loc == 10.0 and sig == 0.5, (loc, sig)
    assert _feed(wd, _settled(1.0, 40.0, 2), t0=7.0) == 7.5, \
        wd.outcome_text()


def test_a_baseline_stands_in_before_the_window_has_reads():
    wd = sp.NSigmaWatchdog(base_loc=-16.0, base_sigma=0.4)
    reads = [(0.5, -16.0)] * 3 + [(0.5, -45.0)] * 2
    assert _feed(wd, reads) == 2.0, wd.outcome_text()


def test_real_traces_land_where_the_replay_said():
    """Numbers copied from real runs (folder names in the comments)."""
    # SLDEA_20260806_151857 at 5 kV: two reads 14.5 uA off its -16 uA
    # level, then a noisy stretch. The 20 uA floor keeps it; a 12.5 uA one
    # would not (the replay's choice between the two).
    dip = [-16.0, -16.0, -15.94, -16.0, -15.89, -15.87, -16.0, -16.19,
           -30.27, -30.53, -18.82, -19.43, -22.19, -21.6, -19.9, -22.67,
           -16.1, -16.22, -16.26, -16.26, -18.89, -17.15, -16.35, -27.19,
           -18.89, -16.48, -15.9, -16.95]
    for floor, trips in ((None, False), (12.5, True)):   # None: shipped
        wd = sp.NSigmaWatchdog(dev_min=floor)
        t = _feed(wd, _settled(5.0, -16.0, 44) + _landing(5.0, dip))
        assert (t is not None) == trips, (floor, wd.outcome_text())
    # an operator run at 4.4 to 4.6 kV: one -24.4 uA read on a ramp
    ramp = [(4.4, 0.1), (4.401, 1.44), (4.424, 0.11), (4.445, -2.37),
            (4.467, 0.16), (4.489, 0.48), (4.51, -24.36), (4.533, -0.12),
            (4.553, -1.72), (4.576, -0.06), (4.6, -0.54), (4.6, 0.24)]
    wd = sp.NSigmaWatchdog()
    assert _feed(wd, _settled(4.4, 0.0, 44) + ramp) is None, \
        wd.outcome_text()
    # SLDEA_20260723_152205's snapshots from 5 kV, two per landing: caught
    # on the second -25.58 uA read
    snaps = [(5.0, 0.15), (5.0, -0.62), (5.25, -0.62), (5.25, -0.62),
             (5.5, -3.28), (5.5, -3.28), (5.75, -25.58), (5.75, -25.58),
             (6.0, -25.58), (6.0, -78.29)]
    wd = sp.NSigmaWatchdog(base_loc=1.05, base_sigma=0.1)
    hit = None
    for i, (kv, ua) in enumerate(snaps):
        t = 10.0 * i
        # a snapshot is taken on a settled landing: two unreadable reads
        # at its kV mark the landing as begun 1.5 s before it
        wd.update(t - 2.0, kv, None)
        wd.update(t - 1.5, kv, None)
        if wd.update(t, kv, ua):
            hit = (kv, ua)
            break
    assert hit == (5.75, -25.58), (hit, wd.outcome_text())


def test_a_read_costs_a_few_microseconds():
    rnd = random.Random(3)
    feed = [(0.5 * i, 2.0, rnd.gauss(0.0, 1.0)) for i in range(4000)]
    best = None
    for _ in range(3):
        wd = sp.NSigmaWatchdog(base_loc=0.0, base_sigma=1.0)
        t0 = time.perf_counter()
        for t, kv, ua in feed:
            wd.update(t, kv, ua)
        per = (time.perf_counter() - t0) / len(feed)
        best = per if best is None else min(best, per)
    # measured 3 to 4 us on the dev VM; the bound only catches a rewrite
    # that sorts far more than the window per read
    assert best < 100e-6, best


# --------------------------------------------------------------------------
# The words
# --------------------------------------------------------------------------

def test_one_function_words_the_start_line():
    on = sp.shadow_record(True, True)
    assert on == (
        "Watchdog shadow: N-sigma rule, logs only and never acts: "
        "|I - location| >= max(5 sigma, 20 uA) for 2 reads in a row; "
        "location and sigma = median and 1.4826 MAD of the last 40 quiet "
        "landing reads; bar x2 on ramps and the first 1 s of a landing; "
        "off-screen counts as away"), on
    assert sp.shadow_record(False, True) == \
        "Watchdog shadow: OFF (dry run, no HV)"
    assert sp.shadow_record(False, False) == \
        "Watchdog shadow: OFF (dry run, no HV)"
    assert sp.shadow_record(True, False) == (
        "Watchdog shadow: OFF (no current reads: watchdog and telemetry "
        "both off)")
    for args in ((True, True), (True, False), (False, True)):
        sp.shadow_record(*args).encode('ascii')


def test_setup_text_puts_the_shadow_line_under_the_watchdog_line():
    p = sp.SldeaProfile(start_kv=0, end_kv=1, step_kv=1)
    wd_line = sp.watchdog_record(True, True, False, 100.0, 3.0)[0]
    sh_line = sp.shadow_record(True, True)
    base = p.setup_text('R', 'iso', 1, 2, 3, False, watchdog=wd_line)
    text = p.setup_text('R', 'iso', 1, 2, 3, False, watchdog=wd_line,
                        watchdog_shadow=sh_line)
    assert text.replace(sh_line + "\n", "", 1) == base
    rows = text.splitlines()
    assert rows[rows.index(sh_line) - 1] == wd_line, rows


# --------------------------------------------------------------------------
# What a run does with it
# --------------------------------------------------------------------------

def _rundir(tmp):
    return os.path.join(tmp, 'RUN')


def _read(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()


def _step_volts(app, after_s, base_v, step_v):
    """I_Out monitor volts: `base_v` until `after_s` seconds after the
    ramp's first SG write, `step_v` from then on (0.05 V = 10 uA)."""
    t_ramp = []

    def volts(ch):
        if ch != 3:
            return 0.0
        if L._ramping(app):
            if not t_ramp:
                t_ramp.append(time.monotonic())
            if time.monotonic() - t_ramp[0] >= after_s:
                return step_v
        return base_v
    return volts


def _one_spike(after_s, base_v, spike_v):
    """A `volts` factory for _run: I_Out reads `base_v`, except ONE read
    taken by the run loop itself (not a snapshot's) at least `after_s`
    seconds after the ramp's first SG write, which reads `spike_v`."""
    def factory(app):
        state = {'t_ramp': None, 'done': False, 'caller': None}

        def on_read(ch, caller):
            state['caller'] = caller
        app.scope.on_read = on_read

        def volts(ch):
            if ch != 3:
                return 0.0
            if L._ramping(app):
                if state['t_ramp'] is None:
                    state['t_ramp'] = time.monotonic()
                if (not state['done'] and state['caller'] == '_sldea_worker'
                        and time.monotonic() - state['t_ramp'] >= after_s):
                    state['done'] = True
                    return spike_v
            return base_v
        return volts
    return factory


def _log_spy(seen):
    """A `hook` for _run: every run.log message, with the SG's writes as
    they stood when it was logged."""
    def hook(app):
        log = app._sldea_log

        def spy(msg):
            seen.append((str(msg), list(app.sg.writes)))
            log(msg)
        app._sldea_log = spy
    return hook


def _run(tmp, dry=False, ticked=False, tel=True, volts=None, trip_ua='100',
         confirm_s='3', landing_s=12.0, answers=None, scope=True, hook=None):
    """The real sldea_run and worker to the run's end; -> app. `hook(app)`
    runs just before sldea_run."""
    mb = L._MB(answers if answers is not None else
               ({} if dry else L.LIVE_OK))
    with L._patched(mb):
        app = L._App(tmp, dry=dry, real_worker=True, wd_on=ticked)
        app.sldea_tel_on = L._Field(tel)
        app.sldea_vars['wd_ua'].set(trip_ua)
        app.sldea_vars['wd_s'].set(confirm_s)
        app._sldea_build_profile = lambda: (
            L._short_profile(landing_s=landing_s), None)
        if not scope:
            app.scope = None
        elif volts is not None:
            app.scope.volts = volts(app)
        if hook is not None:
            hook(app)
        app.sldea_run()
        assert app.worker_done.wait(90), app.lines
        assert app.worker_error is None, repr(app.worker_error)
        app.root.run_pending()
    return app


def _telemetry_events(tmp):
    with open(os.path.join(_rundir(tmp), 'telemetry.csv'), newline='',
              encoding='utf-8') as f:
        return [r for r in csv.DictReader(f) if r['event']]


def _shadow_lines(app):
    return [ln for ln in app.lines if ln.startswith('SHADOW N-sigma')]


def test_a_would_trip_never_stops_a_live_run():
    """The watchdog unticked, telemetry on: only the shadow watches. The
    current steps 30 uA 8 s into the 1 kV landing; the shadow would trip,
    and the run still goes to its end and ramps down as every run does."""
    with tempfile.TemporaryDirectory() as tmp:
        app = _run(tmp, ticked=False, tel=True,
                   volts=lambda a: _step_volts(a, 8.0, 0.05, 0.2))
        assert any(ln.startswith('run complete') for ln in app.lines), \
            app.lines
        assert not app._sldea_bd_tripped
        assert not any('BREAKDOWN' in ln for ln in app.lines), app.lines
        # the SG was driven to 1 kV and back to 0, then switched off
        assert app.sg.writes[-2:] == [('set_offset', 1, 0.0),
                                      ('set_output', 1, False)], \
            app.sg.writes[-4:]
        [line] = _shadow_lines(app)
        assert line.startswith('SHADOW N-sigma (acts on nothing): would trip '
                               'at '), line
        assert '(1.00 kV): I 40.0 uA, 30.0 uA from location 10.0 uA' in \
            line, line
        setup = _read(os.path.join(_rundir(tmp), 'setup.txt'))
        assert "\n" + sp.shadow_record(True, True) + "\n" in setup, setup
        assert "\nWatchdog shadow (end): would trip at " in setup, setup
        # one telemetry event row, carrying no current of its own, so no
        # reader counts that read twice
        [ev] = [r for r in _telemetry_events(tmp)
                if r['event'].startswith('SHADOW')]
        assert ev['event'].startswith('SHADOW N-sigma would trip at '), ev
        assert ev['measured_uA'] == '' and ev['i_status'] == 'skipped', ev
        # the readers of setup.txt still read it
        assert se.load_settings(_rundir(tmp))['diam_mm'] == 16.0


def test_beside_an_armed_watchdog_the_shadow_changes_nothing():
    """Watchdog ticked with a trip it never reaches (1000 uA): the shadow
    has the 0 kV baseline from the start, would trip on the same step, and
    the run still completes."""
    with tempfile.TemporaryDirectory() as tmp:
        app = _run(tmp, ticked=True, tel=True, trip_ua='1000',
                   volts=lambda a: _step_volts(a, 8.0, 0.05, 0.2))
        assert app.worker_args[11:13] == (True, 1000.0), \
            app.worker_args[11:13]
        assert any(ln.startswith('run complete') for ln in app.lines), \
            app.lines
        assert not app._sldea_bd_tripped
        [line] = _shadow_lines(app)
        assert 'would trip at ' in line, line


def test_the_watchdog_still_stops_a_run_as_before():
    """120 uA from the ramp on, the watchdog ticked with a 1 s confirm:
    the shadow would trip first, and the watchdog stops the run as it did
    before the shadow existed."""
    with tempfile.TemporaryDirectory() as tmp:
        app = _run(tmp, ticked=True, tel=True, confirm_s='1', landing_s=6.0,
                   volts=lambda a: (lambda ch: 0.6 if ch == 3
                                    and L._ramping(a) else 0.0))
        assert app._sldea_bd_tripped, app.lines
        assert any(ln.startswith('run BREAKDOWN-ABORT') for ln in
                   app.lines), app.lines
        [line] = _shadow_lines(app)
        assert 'would trip at ' in line, line
        events = [r['event'] for r in _telemetry_events(tmp)]
        assert any(e.startswith('SHADOW') for e in events), events
        assert 'BREAKDOWN CONFIRMED' in events, events


def test_a_refused_baseline_arms_no_shadow():
    """40 uA already at 0 kV is a standing fault current: the watchdog
    refuses it as a baseline (credible_baseline_ua) and keeps its absolute
    rule, and the shadow is not armed, because a deviation rule anchored
    there would take the fault as normal."""
    with tempfile.TemporaryDirectory() as tmp:
        app = _run(tmp, ticked=True, tel=True, landing_s=1.2,
                   volts=lambda a: (lambda ch: 0.2 if ch == 3 else 0.0))
        assert any('is not a credible 0 kV rest level' in ln
                   for ln in app.lines), app.lines
        assert any(ln.startswith('run complete') for ln in app.lines)
        [line] = _shadow_lines(app)
        assert line == ('SHADOW N-sigma (acts on nothing): not armed: the '
                        '0 kV baseline 40.0 uA was refused (a standing '
                        'fault current)'), line
        setup = _read(os.path.join(_rundir(tmp), 'setup.txt'))
        assert ("\nWatchdog shadow (end): not armed: the 0 kV baseline "
                "40.0 uA was refused (a standing fault current)\n") in \
            setup, setup


def test_an_error_in_the_rule_stops_only_the_shadow():
    saved = sp.NSigmaWatchdog.update

    def broken(self, *a, **k):
        raise RuntimeError('made up')
    sp.NSigmaWatchdog.update = broken
    try:
        with tempfile.TemporaryDirectory() as tmp:
            app = _run(tmp, ticked=False, tel=True, landing_s=4.0)
            assert any(ln.startswith('run complete') for ln in app.lines), \
                app.lines
            [line] = _shadow_lines(app)
            assert line.startswith('SHADOW N-sigma (acts on nothing): '
                                   'stopped by an error at '), line
            assert line.endswith('RuntimeError: made up'), line
            setup = _read(os.path.join(_rundir(tmp), 'setup.txt'))
            assert "\nWatchdog shadow (end): stopped by an error at " in \
                setup, setup
    finally:
        sp.NSigmaWatchdog.update = saved


def test_dry_runs_and_runs_without_reads_are_as_before():
    # a DRY run, with telemetry: no shadow, and setup.txt says why
    with tempfile.TemporaryDirectory() as tmp:
        app = _run(tmp, dry=True, ticked=True, tel=True, landing_s=1.2)
        assert _shadow_lines(app) == [], app.lines
        setup = _read(os.path.join(_rundir(tmp), 'setup.txt'))
        assert "\nWatchdog shadow: OFF (dry run, no HV)\n" in setup, setup
        assert "Watchdog shadow (end)" not in setup, setup
        assert not any(r['event'].startswith('SHADOW')
                       for r in _telemetry_events(tmp))
    # LIVE, the watchdog unticked and telemetry off: nothing reads the
    # current, so there is nothing for a shadow to read either
    with tempfile.TemporaryDirectory() as tmp:
        app = _run(tmp, ticked=False, tel=False, landing_s=1.2)
        assert any(ln.startswith('run complete') for ln in app.lines)
        assert _shadow_lines(app) == [], app.lines
        setup = _read(os.path.join(_rundir(tmp), 'setup.txt'))
        assert ("\nWatchdog shadow: OFF (no current reads: watchdog and "
                "telemetry both off)\n") in setup, setup
        assert "Watchdog shadow (end)" not in setup, setup
        assert not any(r[2] == '_sldea_worker' for r in app.scope.reads
                       if r[0] == 'MEAN'), app.scope.reads
    # LIVE with no scope at all: the same, after the existing question
    with tempfile.TemporaryDirectory() as tmp:
        app = _run(tmp, ticked=True, tel=True, landing_s=1.2, scope=False,
                   answers={'Energize HV?': True,
                            'No current monitoring': True})
        assert any(ln.startswith('run complete') for ln in app.lines)
        assert _shadow_lines(app) == [], app.lines
        setup = _read(os.path.join(_rundir(tmp), 'setup.txt'))
        assert ("\nWatchdog shadow: OFF (no current reads: watchdog and "
                "telemetry both off)\n") in setup, setup


def _away_entries(app):
    return [ln for ln in app.lines if ln.startswith('SHADOW away reads')]


def test_a_lone_away_read_on_a_live_run_is_listed_after_the_sg_is_zeroed():
    """The watchdog unticked, telemetry on: ONE read at 40 uA, 9 s into
    the ramp, against the run's 10 uA. The shadow does not trip, and the
    run lists that read in run.log once, in one entry, and only after the
    SG is at 0 V and off: nothing about it is logged from the run loop."""
    seen = []
    with tempfile.TemporaryDirectory() as tmp:
        app = _run(tmp, ticked=False, tel=True,
                   volts=_one_spike(9.0, 0.05, 0.2), hook=_log_spy(seen))
        assert any(ln.startswith('run complete') for ln in app.lines), \
            app.lines
        assert not app._sldea_bd_tripped
        [line] = _shadow_lines(app)
        assert line.startswith('SHADOW N-sigma (acts on nothing): no trip '
                               'in '), line
        [entry] = _away_entries(app)
        rows = entry.split('\n  ')
        assert len(rows) == 2, rows
        assert rows[0].startswith('SHADOW away reads (N-sigma, acts on '
                                  'nothing): 1 away read in '), rows[0]
        assert rows[1].startswith('away at '), rows[1]
        assert ('(1.00 kV, landing): I 40.0 uA, 30.0 uA from location '
                '10.0 uA (bar 20.0 uA, sigma 0.50 uA); 1 in a row') in \
            rows[1], rows[1]
        # no would-trip, so no telemetry event row for the shadow
        assert not any(r['event'].startswith('SHADOW')
                       for r in _telemetry_events(tmp))
    # when it was logged: the SG was already zeroed and switched off, and
    # no other message mentions the read
    [(msg, sg_then)] = [(m, w) for m, w in seen if 'away at ' in m]
    assert msg == entry
    assert sg_then[-2:] == [('set_offset', 1, 0.0),
                            ('set_output', 1, False)], sg_then[-4:]


def test_a_would_trip_lists_both_reads_and_is_still_one_would_trip():
    """The held 30 uA step of the first run test: both away reads are
    listed, the second marked, and there is still exactly one would-trip:
    one telemetry event row and one end line."""
    with tempfile.TemporaryDirectory() as tmp:
        app = _run(tmp, ticked=False, tel=True,
                   volts=lambda a: _step_volts(a, 8.0, 0.05, 0.2))
        assert any(ln.startswith('run complete') for ln in app.lines), \
            app.lines
        [line] = _shadow_lines(app)
        assert 'would trip at ' in line, line
        shadow_events = [r for r in _telemetry_events(tmp)
                         if r['event'].startswith('SHADOW')]
        assert len(shadow_events) == 1, shadow_events
        [entry] = _away_entries(app)
        rows = entry.split('\n  ')
        assert len(rows) == 3, rows
        assert rows[0].startswith('SHADOW away reads (N-sigma, acts on '
                                  'nothing): 2 away reads in '), rows[0]
        assert rows[1].endswith('; 1 in a row'), rows[1]
        assert rows[2].endswith('; 2 in a row, would trip'), rows[2]


def test_a_quiet_live_run_lists_no_away_read():
    """The watchdog ticked (so the shadow has the 0 kV baseline), the
    current a steady 10 uA: no away read, so no entry at all."""
    with tempfile.TemporaryDirectory() as tmp:
        app = _run(tmp, ticked=True, tel=True, landing_s=4.0)
        assert any(ln.startswith('run complete') for ln in app.lines), \
            app.lines
        [line] = _shadow_lines(app)
        assert line.startswith('SHADOW N-sigma (acts on nothing): no trip '
                               'in '), line
        assert _away_entries(app) == [], app.lines


def _levels_volts(app, steps, base_v):
    """I_Out monitor volts: `base_v`, then each (after_s, volts) of
    `steps` from `after_s` seconds after the ramp's first SG write."""
    t_ramp = []

    def volts(ch):
        if ch != 3:
            return 0.0
        v = base_v
        if L._ramping(app):
            if not t_ramp:
                t_ramp.append(time.monotonic())
            dt = time.monotonic() - t_ramp[0]
            for after_s, step_v in steps:
                if dt >= after_s:
                    v = step_v
        return v
    return volts


def _spied_run(tmp):
    """A ticked LIVE run, telemetry at 2 Hz: 10 uA at rest, 40 uA from 3 s
    after the ramp starts (the shadow would trip; under the 100 uA trip),
    160 uA from 5 s (the watchdog trips, confirm 1 s). -> (app, calls):
    in the order the worker made them, every BreakdownWatchdog.update and
    NSigmaWatchdog.update (called, then decided), every telemetry event
    and periodic row (with hold_flush as it stood), and every flush of
    the telemetry file."""
    calls = []
    saved = (sp.BreakdownWatchdog.update, sp.NSigmaWatchdog.update,
             sp.TelemetryLog.event, sp.TelemetryLog.sample,
             sp.TelemetryLog.__init__)

    def watchdog(self, t_s, ua, offscreen=False):
        calls.append(('watchdog', t_s))
        tripped = saved[0](self, t_s, ua, offscreen=offscreen)
        calls.append(('watchdog decided', t_s, tripped))
        return tripped

    def shadow(self, t_s, kv, ua, offscreen=False):
        calls.append(('shadow', t_s))
        tripped = saved[1](self, t_s, kv, ua, offscreen=offscreen)
        calls.append(('shadow decided', t_s, tripped))
        return tripped

    def event(self, t_s, timestamp, nominal_kv, event, **kw):
        calls.append(('event', t_s, str(event), self.hold_flush))
        return saved[2](self, t_s, timestamp, nominal_kv, event, **kw)

    def sample(self, t_s, timestamp, nominal_kv, **kw):
        calls.append(('sample', t_s, self.hold_flush))
        return saved[3](self, t_s, timestamp, nominal_kv, **kw)

    class _Flushes:
        def __init__(self, f):
            self._f = f

        def __getattr__(self, name):
            return getattr(self._f, name)

        def flush(self):
            calls.append(('flush',))
            return self._f.flush()

    def init(self, *a, **k):
        saved[4](self, *a, **k)
        self._f = _Flushes(self._f)

    (sp.BreakdownWatchdog.update, sp.NSigmaWatchdog.update,
     sp.TelemetryLog.event, sp.TelemetryLog.sample,
     sp.TelemetryLog.__init__) = (watchdog, shadow, event, sample, init)
    try:
        app = _run(tmp, ticked=True, tel=True, confirm_s='1', landing_s=8.0,
                   volts=lambda a: _levels_volts(
                       a, ((3.0, 0.2), (5.0, 0.8)), 0.05))
    finally:
        (sp.BreakdownWatchdog.update, sp.NSigmaWatchdog.update,
         sp.TelemetryLog.event, sp.TelemetryLog.sample,
         sp.TelemetryLog.__init__) = saved
    return app, calls


def _shadow_event(calls):
    [(i, ev)] = [(i, c) for i, c in enumerate(calls)
                 if c[0] == 'event' and c[2].startswith('SHADOW')]
    return i, ev


def test_in_every_tick_the_watchdog_decides_before_the_shadow():
    """HV review 2026-10-08, finding 3: nothing pinned WHEN the shadow
    runs. With its block moved above the watchdog's trip branch, and a
    would-trip made to cost 2 s, every suite still passed. Here, in a real
    worker run whose shadow would trip at 40 uA before the watchdog trips
    at 160 uA: on every read the shadow is fed, the call just before it is
    the watchdog's decision on that same read (not a trip), and the
    would-trip's telemetry row comes after both decisions of its tick."""
    with tempfile.TemporaryDirectory() as tmp:
        app, calls = _spied_run(tmp)
    assert app._sldea_bd_tripped, app.lines
    shadow_ticks = [c[1] for c in calls if c[0] == 'shadow']
    assert len(shadow_ticks) >= 5, calls
    for t in shadow_ticks:
        i = calls.index(('shadow', t))
        assert calls[i - 2:i] == [('watchdog', t),
                                  ('watchdog decided', t, False)], \
            calls[max(0, i - 4):i + 1]
    i_ev, ev = _shadow_event(calls)
    t_ev = ev[1]
    assert calls[i_ev - 4:i_ev] == [
        ('watchdog', t_ev), ('watchdog decided', t_ev, False),
        ('shadow', t_ev), ('shadow decided', t_ev, True)], \
        calls[max(0, i_ev - 5):i_ev + 1]
    # the watchdog went on reading after the would-trip, and tripped later
    [t_trip] = [c[1] for c in calls if c[0] == 'watchdog decided' and c[2]]
    assert t_trip > t_ev, (t_trip, t_ev)
    assert calls.index(('watchdog decided', t_trip, True)) > i_ev


def test_the_would_trip_row_is_written_without_a_flush_and_kept():
    """HV review 2026-10-08, the note on the would-trip row: it is the one
    file write the shadow adds to the HV loop, and in the review's model a
    3 s stall on it delayed the watchdog's trip that followed (3.06 s to
    SG zero became 5.65 s). It is now written with hold_flush set, so it
    issues no flush of its own: the periodic row after it flushes it, the
    hold is put back for that row, and the row is in telemetry.csv after
    the run."""
    with tempfile.TemporaryDirectory() as tmp:
        app, calls = _spied_run(tmp)
        rows = [r for r in _telemetry_events(tmp)
                if r['event'].startswith('SHADOW')]
    assert app._sldea_bd_tripped, app.lines
    i_ev, ev = _shadow_event(calls)
    assert ev[3] is True, ev                       # held while written
    after = calls[i_ev + 1:]
    first_flush = after.index(('flush',))
    samples = [c for c in after[:first_flush] if c[0] == 'sample']
    assert samples, after[:first_flush + 1]        # a periodic row flushed
    assert samples[0][2] is False, samples[0]      # ...the hold put back
    assert len(rows) == 1 and rows[0]['event'] == ev[2], (rows, ev)


def _run_all():
    # Failures are collected, not fatal (`#280`); a case that cannot run
    # here is counted as skipped, not passed.
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
    raise SystemExit(_run_all())
