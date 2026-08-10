#!/usr/bin/env python3
"""Headless tests for sldea_plot (synthetic runs, no bench data).

Run: .venv/bin/python tests/test_sldea_plot.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import csv
import os
import shutil
import tempfile

import sldea_plot as sp

COLS_15 = ['snapshot', 'step', 'tag', 'nominal_kV', 'control_V',
           'measured_kV', 'measured_uA', 't_planned_s', 'timestamp',
           'frame_file', 'active_area_px', 'active_area_mm2',
           'active_diam_mm', 'wrinkle_idx', 'notes']
COLS_14 = [c for c in COLS_15 if c != 'wrinkle_idx']   # 07-23 era


def _fake_run(d, rows, cols=COLS_15):
    os.makedirs(os.path.join(d, 'frames'), exist_ok=True)
    with open(os.path.join(d, 'data.csv'), 'w', newline='',
              encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({**{c: '' for c in cols}, **r})


def _healthy_rows(n_levels=8, ts='2026-08-05T10:00:00', tags=('pre-ramp',
                                                             'post-ramp')):
    rows = [{'snapshot': 1, 'tag': 'baseline', 'nominal_kV': 0,
             'measured_uA': -16.0, 'active_area_px': 288555,
             'active_area_mm2': 201.062, 'timestamp': ts,
             'notes': 'edge:resting conf 0.95'}]
    n = 2
    for step in range(1, n_levels + 1):
        kv = step * 0.5
        for tag in tags:
            traced = kv >= 3.0
            # post differs from pre so pair aggregation is actually tested
            # (a symmetric fixture made the mean assertion tautological)
            area = round(201.062 * (1 + 0.05 * step), 3)
            if tag.startswith('post'):
                area = round(area + 2.0, 3)
            rows.append({
                'snapshot': n, 'tag': tag, 'nominal_kV': kv,
                'measured_uA': -16.0 + 0.1 * step,
                'active_area_px': 288555 + 9000 * step,
                'active_area_mm2': area,
                'timestamp': ts,
                'notes': ('edge:manual-trace conf 1.00 (user)' if traced
                          else 'edge:disc-fit conf 0.93'),
            })
            n += 1
    return rows


def _mktmp():
    return tempfile.mkdtemp(prefix='sldea_plot_test_')


def _has_mpl():
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        print('  (skipped: no matplotlib)')
        return False


def _drawn(runs, opts, warn=lambda m: None):
    """-> the Figure sp.draw() produced, WITHOUT pyplot (the same path
    save_figure uses), so a test can interrogate the real axes."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    fig = Figure(figsize=sp.FIGSIZE[opts['mode']])
    FigureCanvasAgg(fig)
    sp.draw(fig, runs, opts, warn)
    return fig


def _caption(fig):
    """The figure-level caption text every figure carries."""
    return '\n'.join(t.get_text() for t in fig.texts)


def _band_count(fig):
    """How many SHADED bands the figure actually drew, over all panels.

    fill_between is the only thing in this module that makes a filled
    collection, so counting them is counting bands -- and counting the
    drawn artists rather than reading the opts dict is the point: an
    option that is half-consumed by the drawing code produces a figure
    that looks finished and is not."""
    from matplotlib.collections import PolyCollection
    return sum(1 for ax in fig.axes for c in ax.collections
               if isinstance(c, PolyCollection))


def test_load_rows_parses_notes_phases_and_eras():
    d = _mktmp()
    try:
        _fake_run(d, [
            {'snapshot': 1, 'tag': 'baseline', 'nominal_kV': 0,
             'active_area_mm2': 201.062, 'notes': 'edge:resting conf 0.95'},
            {'snapshot': 2, 'tag': 'pre', 'nominal_kV': 1.0,
             'active_area_mm2': 210.0,
             'notes': 'edge:disc-fit conf 0.74 (user); '
                      'pair mismatch 40% at 5.75 kV'},
            {'snapshot': 3, 'tag': 'post', 'nominal_kV': 1.0,
             'active_area_mm2': 212.0,
             'notes': 'edge:manual-trace conf 1.00 (user)'},
        ], cols=COLS_14)
        rows = sp.load_rows(d)
        assert [r['phase'] for r in rows] == ['baseline', 'pre', 'post']
        assert rows[1]['method'] == 'disc-fit' and rows[1]['user']
        assert rows[1]['conf'] == 0.74 and not rows[1]['traced']
        assert rows[2]['traced'] and rows[2]['user']
        assert rows[0]['method'] == 'resting' and not rows[0]['user']
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_stale_breakdown_brand_is_not_confirmed_and_drops_nothing():
    # The P3_5 case: old area-jump heuristic branded frames *_BREAKDOWN and
    # wrote 'post-breakdown' notes while the current stayed flat. The tool
    # must not confirm it, must warn, and must keep every row.
    d = _mktmp()
    try:
        rows = _healthy_rows(8)
        rows[9]['notes'] += '; breakdown? area collapsed 36%'
        for r in rows[10:]:
            r['frame_file'] = f"SLDEA_s{r['snapshot']}_BREAKDOWN.png"
            r['notes'] += '; post-breakdown'
        _fake_run(d, rows)
        warns = []
        run = sp.load_run(d, warns.append)
        assert run['flags'] == {}, run['flags']
        assert run['saved_brand'], 'brand rows not detected'
        assert any('stale brand' in w for w in warns), warns
        out = _mktmp()
        try:
            sp.write_tidy([dict(run, color='#4477AA')],
                          os.path.join(out, 't.csv'))
            with open(os.path.join(out, 't.csv'), encoding='utf-8') as f:
                tidy = list(csv.DictReader(f))
            assert len(tidy) == len(rows), 'rows were dropped'
            assert all(t['breakdown_confirmed'] == '' for t in tidy)
            assert sum(t['saved_breakdown_brand'] == 'True'
                       for t in tidy) == len(rows) - 9
        finally:
            shutil.rmtree(out, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_stale_brand_still_warns_next_to_a_real_event():
    # Review 2026-08-05: the warning used to be per-run ('brand and no
    # flags'), so stale brands went silent whenever the run ALSO had a real
    # confirmed event. Brands before the first confirmed row must warn.
    d = _mktmp()
    try:
        rows = _healthy_rows(8)
        for r in rows[2:5]:                      # stale brands, healthy rows
            r['frame_file'] = f"SLDEA_s{r['snapshot']}_BREAKDOWN.png"
            r['notes'] += '; post-breakdown'
        for snap, ua in ((14, -80.0), (15, -140.0), (16, -205.0)):
            rows[snap - 1]['measured_uA'] = ua    # real adjacent staircase
        _fake_run(d, rows)
        warns = []
        run = sp.load_run(d, warns.append)
        assert run['flags'], 'real staircase not confirmed'
        assert any('stale brand' in w for w in warns), warns
        assert any('no saved branding' in w for w in warns), warns
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_unit_mixing_cannot_fabricate_breakdown():
    # Review 2026-08-05 (high): a per-row px-else-mm2 fallback fed mixed
    # units to the ratio-based collapse test; a stale mm2-only row (the
    # pre-2026-07-25 rejected-row shape) next to px rows read as a 100%
    # collapse. One unit per run: no flags, no advisories.
    for sparse in (False, True):
        d = _mktmp()
        try:
            rows = _healthy_rows(8)
            rows[4]['active_area_px'] = ''       # stale mm2-only row
            if sparse:
                # <5 parseable uA rows -> legacy fallback where collapse
                # alone used to confirm
                for r in rows[3:]:
                    r['measured_uA'] = ''
            _fake_run(d, rows)
            run = sp.load_run(d, lambda m: None)
            assert run['flags'] == {}, (sparse, run['flags'])
            assert run['advis'] == {}, (sparse, run['advis'])
        finally:
            shutil.rmtree(d, ignore_errors=True)


def test_real_breakdown_staircase_is_confirmed():
    d = _mktmp()
    try:
        rows = _healthy_rows(8)
        # adjacent sustained deviation from the -16 uA median (233451 shape)
        for snap, ua in ((14, -80.0), (15, -140.0), (16, -205.0)):
            rows[snap - 1]['measured_uA'] = ua
        _fake_run(d, rows)
        warns = []
        run = sp.load_run(d, warns.append)
        assert run['flags'], 'staircase not confirmed'
        assert min(run['flags']) == 13, run['flags']
        assert any('current-confirmed breakdown detected' in w
                   for w in warns), warns
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_single_recovered_event_is_advisory_only():
    d = _mktmp()
    try:
        rows = _healthy_rows(8)
        rows[7]['measured_uA'] = -153.0        # 104531: one spike, recovers
        _fake_run(d, rows)
        run = sp.load_run(d, lambda m: None)
        assert run['flags'] == {}, run['flags']
        assert 7 in run['advis'], run['advis']
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_levels_pairs_and_traced_aggregation():
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        run = sp.load_run(d, lambda m: None)
        lvs = sp.levels(run)
        assert lvs[0]['kv'] == 0 and lvs[0]['mean'] == 201.062
        one = next(l for l in lvs if l['kv'] == 1.0)   # step 2
        pre_v = round(201.062 * 1.1, 3)
        post_v = round(pre_v + 2.0, 3)
        assert one['pre'] == pre_v and one['post'] == post_v, one
        assert one['mean'] == (pre_v + post_v) / 2, one
        assert not one['traced'] and not one['all_traced']
        both = next(l for l in lvs if l['kv'] == 3.0)  # fully traced level
        assert both['traced'] and both['all_traced']
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_mixed_level_keeps_machine_band():
    # Review 2026-08-05: a level with one traced and one machine snapshot
    # must NOT get the tight +-1% band around its mean (the machine
    # snapshot carries +-2% and a convention offset). Marker stays open.
    d = _mktmp()
    try:
        rows = _healthy_rows(8)
        mixed = next(r for r in rows
                     if r['nominal_kV'] == 3.0 and r['tag'] == 'pre-ramp')
        mixed['notes'] = 'edge:disc-fit conf 0.90'     # un-trace the pre
        _fake_run(d, rows)
        run = sp.load_run(d, lambda m: None)
        lv = next(l for l in sp.levels(run) if l['kv'] == 3.0)
        assert lv['traced'] and not lv['all_traced'], lv
        # audit 2026-08-05: NEVER average across edge conventions — the
        # mixed level's mean is the MACHINE member alone (the traced
        # member is +5.2-5.7% by definition, and the blend belonged to
        # neither convention while the caption claimed 'outer toe ±1%')
        assert lv['mixed'], lv
        assert lv['mean'] == lv['pre'], lv     # the machine member
        pure = next(l for l in sp.levels(run) if l['kv'] == 3.5)
        assert pure['all_traced'] and not pure['mixed']
        assert pure['mean'] == (pure['pre'] + pure['post']) / 2
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_main_area_mode_end_to_end():
    if not _has_mpl():
        return
    d1, d2, out = _mktmp(), _mktmp(), _mktmp()
    try:
        _fake_run(d1, _healthy_rows(8))
        rows = _healthy_rows(8)
        for snap, ua in ((14, -80.0), (15, -140.0), (16, -205.0)):
            rows[snap - 1]['measured_uA'] = ua
        _fake_run(d2, rows)
        rc = sp.main([d1, d2, '--out', out, '--stem', 'tt', '--prepost',
                      '--mean'])
        assert rc == 0
        assert os.path.exists(os.path.join(out, 'tt.png'))
        with open(os.path.join(out, 'tt.csv'), encoding='utf-8') as f:
            tidy = list(csv.DictReader(f))
        assert len(tidy) == 34, len(tidy)
        assert any(t['breakdown_confirmed'] for t in tidy)
        assert tidy[0].keys() == dict.fromkeys(sp.TIDY_COLS).keys()
    finally:
        for d in (d1, d2, out):
            shutil.rmtree(d, ignore_errors=True)


def test_confirmed_row_without_area_gets_fallback_not_silence():
    # Review 2026-08-05 (high): a confirmed breakdown row whose frame was
    # rejected in review (no area) used to lose its X mark silently in
    # area mode. It must surface as a dashed vertical + warning.
    if not _has_mpl():
        return
    d, out = _mktmp(), _mktmp()
    try:
        rows = _healthy_rows(8)
        for snap, ua in ((16, -150.0), (17, -200.0)):   # terminal adjacent
            rows[snap - 1]['measured_uA'] = ua
            rows[snap - 1]['active_area_mm2'] = ''      # rejected frames
            rows[snap - 1]['active_area_px'] = ''
            rows[snap - 1]['notes'] = 'rejected (no reliable edge)'
        _fake_run(d, rows)
        warns = []
        run = sp.load_run(d, warns.append)
        assert run['flags'], 'terminal event not confirmed'
        run['color'] = '#4477AA'
        opts = {'mode': 'area', 'prepost': False, 'mean': True,
                'bands': True, 'breakdown': True, 'vs_area': False,
                'title': None}
        png = os.path.join(out, 'fb.png')
        sp.figure_area([run], opts, png, warns.append)
        assert os.path.exists(png)
        assert any('no reviewed area' in w for w in warns), warns
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


def test_raw_run_skips_area_mode_but_plots_current():
    if not _has_mpl():
        return
    d, out = _mktmp(), _mktmp()
    try:
        rows = _healthy_rows(6)
        for r in rows:                      # raw: no review columns filled
            r['active_area_mm2'] = ''
            r['active_area_px'] = ''
            r['notes'] = ''
        _fake_run(d, rows)
        assert sp.main([d, '--out', out]) == 2          # nothing in area mode
        assert sp.main([d, '--out', out, '--mode', 'current']) == 0
        assert os.path.exists(os.path.join(out, 'sldea_plot_current.png'))
        # --vs-area needs areas too: raw run -> nothing to plot, not a
        # blank exit-0 figure (review 2026-08-05)
        assert sp.main([d, '--out', out, '--mode', 'current',
                        '--vs-area']) == 2
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


def test_cli_rejects_bad_flags_cleanly():
    # Review 2026-08-05: missing values crashed with IndexError; misspelled
    # flags vanished silently. Both must exit 2 with the usage message.
    assert sp.main(['x', '--title']) == 2
    assert sp.main(['x', '--mode']) == 2
    assert sp.main(['x', '--out', '--prepost']) == 2   # value can't be a flag
    assert sp.main(['x', '--bogus-flag']) == 2


def test_duplicate_out_flag_last_wins():
    if not _has_mpl():
        return
    d, a, b = _mktmp(), _mktmp(), _mktmp()
    try:
        _fake_run(d, _healthy_rows(6))
        rc = sp.main([d, '--mode', 'current', '--out', a, '--out', b])
        assert rc == 0
        assert os.path.exists(os.path.join(b, 'sldea_plot_current.png'))
        assert not os.path.exists(os.path.join(a, 'sldea_plot_current.png'))
    finally:
        for p in (d, a, b):
            shutil.rmtree(p, ignore_errors=True)


def test_old_scale_bug_guard():
    d = _mktmp()
    try:
        rows = _healthy_rows(4, ts='2026-07-20T10:00:00')
        for r in rows:                      # 2.5x-style inflated areas
            if r.get('active_area_mm2'):
                r['active_area_mm2'] = round(r['active_area_mm2'] * 2.5, 3)
        _fake_run(d, rows)
        run = sp.load_run(d, lambda m: None)
        assert sp.suspect_old_scale(run)
        # post-fix data on the same date is fine (155425: baseline exact)
        rows2 = _healthy_rows(4, ts='2026-07-20T10:00:00')
        d2 = _mktmp()
        try:
            _fake_run(d2, rows2)
            run2 = sp.load_run(d2, lambda m: None)
            assert not sp.suspect_old_scale(run2)
        finally:
            shutil.rmtree(d2, ignore_errors=True)
        # fail CLOSED: old-era areas with NO baseline to verify against are
        # suspect too (review 2026-08-05)
        rows3 = _healthy_rows(4, ts='2026-07-20T10:00:00')
        rows3[0]['active_area_mm2'] = ''
        rows3[0]['active_area_px'] = ''
        d3 = _mktmp()
        try:
            _fake_run(d3, rows3)
            run3 = sp.load_run(d3, lambda m: None)
            assert sp.suspect_old_scale(run3)
        finally:
            shutil.rmtree(d3, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_scale_guard_scoping_by_mode():
    # Review 2026-08-05: the guard used to exclude suspect runs from
    # current/power modes that never read areas. Now: excluded from area
    # axes, kept for current (with area columns blanked in the tidy CSV),
    # and --allow-suspect-scale overrides everywhere.
    if not _has_mpl():
        return
    d, out = _mktmp(), _mktmp()
    try:
        rows = _healthy_rows(6, ts='2026-07-20T10:00:00')
        for r in rows:
            if r.get('active_area_mm2'):
                r['active_area_mm2'] = round(r['active_area_mm2'] * 2.5, 3)
        _fake_run(d, rows)
        assert sp.main([d, '--out', out]) == 2                    # excluded
        assert sp.main([d, '--out', out,
                        '--allow-suspect-scale']) == 0            # override
        assert sp.main([d, '--out', out, '--mode', 'current',
                        '--stem', 'cur']) == 0                    # kept
        with open(os.path.join(out, 'cur.csv'), encoding='utf-8') as f:
            tidy = list(csv.DictReader(f))
        assert tidy and all(t['area_mm2'] == '' for t in tidy), \
            'bug-era areas leaked into the tidy CSV'
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


def test_selftest_renders():
    if not _has_mpl():
        return
    out = _mktmp()
    try:
        png = os.path.join(out, 'st.png')
        assert sp._selftest(png) == 0
        assert os.path.exists(png)
        assert os.path.exists(os.path.join(out, 'st.csv'))
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_power_is_offset_corrected_by_the_run_median():
    """audit 2026-08-05: power_mW was |kV × raw µA| — on the −16 µA-idle
    era that is ~100% instrument zero × the voltage axis (158.7 'mW' at
    10 kV for a device dissipating ~0.3), and it rank-inverted real
    dissipation. Power now mirrors breakdown_flags' median baseline."""
    d = _mktmp()
    try:
        rows = [{'snapshot': 1, 'tag': 'baseline', 'nominal_kV': 0,
                 'measured_uA': -16.0, 'timestamp': '2026-08-05T10:00:00'}]
        for n, (kv, ua) in enumerate(((1.0, -16.0), (2.0, -15.9),
                                      (5.0, -15.9), (10.0, -15.87),
                                      (10.0, -10.5)), start=2):
            rows.append({'snapshot': n, 'tag': 'pre-ramp',
                         'nominal_kV': kv, 'measured_uA': ua,
                         'timestamp': '2026-08-05T10:00:00'})
        _fake_run(d, rows)
        run = sp.load_run(d, lambda m: None)
        med = sp.run_ua_median(run)
        assert med is not None and abs(med - (-15.9)) < 1e-9, med
        r_idle = run['rows'][4]        # 10 kV at essentially the idle
        r_real = run['rows'][5]        # 10 kV, 5.4 µA off baseline
        p_idle = sp.power_mw(r_idle, med)
        p_real = sp.power_mw(r_real, med)
        # the idle row's power is ~0, not 158.7; the genuinely
        # dissipating row now ranks ABOVE it (the raw product inverted)
        assert p_idle < 1.0, p_idle
        assert abs(p_real - 54.0) < 1e-6, p_real
        assert p_real > p_idle
        # no median (<5 parseable rows): the raw product is kept
        assert sp.power_mw({'kv': 10.0, 'ua': -15.87}, None) == 158.7
        # and the tidy export carries the corrected value
        out = _mktmp()
        try:
            path = sp.write_tidy([dict(run, color='#4477AA')],
                                 os.path.join(out, 't.csv'))
            with open(path, newline='', encoding='utf-8') as f:
                tidy = list(csv.DictReader(f))
            ten = [t for t in tidy if t['nominal_kV'] == '10.0']
            assert any(abs(float(t['power_mW']) - 54.0) < 1e-6
                       for t in ten), ten
            assert not any(float(t['power_mW']) > 100 for t in ten
                           if t['power_mW']), ten
        finally:
            shutil.rmtree(out, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_tidy_names_each_areas_edge_convention():
    """audit 2026-08-05: the tidy CSV had no way to tell an outer-toe
    hand trace from a half-height machine area — the +5.2-5.7%
    definitional gap was invisible downstream."""
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))     # traced rows start at 3.0 kV
        run = sp.load_run(d, lambda m: None)
        out = _mktmp()
        try:
            path = sp.write_tidy([dict(run, color='#4477AA')],
                                 os.path.join(out, 't.csv'))
            with open(path, newline='', encoding='utf-8') as f:
                tidy = list(csv.DictReader(f))
            assert 'convention' in tidy[0]
            by_traced = {t['traced']: t['convention'] for t in tidy
                         if t['area_mm2']}
            assert by_traced.get('True') == 'outer-toe'
            assert by_traced.get('False') == 'half-height'
        finally:
            shutil.rmtree(out, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------
# the shared front-end surface (`#223`): the window is a front end to these,
# so anything that lets the two drift apart is the bug these tests hunt
# --------------------------------------------------------------------------

def test_make_opts_maps_choices_and_refuses_bad_combinations():
    o, err = sp.make_opts()
    assert err is None
    # the defaults are the CLI's: bands and breakdown marks ON, the rest
    # off. Strict equality on purpose -- a key added without a default
    # that reproduces the pre-change figure has to fail here.
    assert o == {'mode': 'area', 'vs_area': False, 'prepost': False,
                 'mean': False, 'bands': True, 'breakdown': True,
                 'title': None, 'logx': False, 'logy': False,
                 'marker_key': True, 'title_first': None,
                 'title_second': None, 'subplots': 'both',
                 'cadence_guard': False, 'aggregate': False,
                 'aggregate_exact': False,
                 # `#313`: no groups is 'average everything selected',
                 # which is the aggregate that already shipped, and the
                 # contributing runs are drawn -- both defaults reproduce
                 # the figure that existed before the option
                 'groups': [], 'aggregate_only': False,
                 # `#314`: the file, not the drawing -- and the defaults
                 # are the file every export wrote before it existed
                 'fmt': 'png', 'dpi': 300}
    o, err = sp.make_opts(mode='current', vs_area=True, prepost=True,
                          mean=True, bands=False, breakdown=False,
                          title='x')
    assert err is None and o['vs_area'] and not o['bands']
    assert o['title'] == 'x'
    # an empty title is no title, not an empty heading
    assert sp.make_opts(title='')[0]['title'] is None
    # the two illegal states, refused with the CLI's own wording
    assert sp.make_opts(mode='bogus')[0] is None
    assert '--mode' in sp.make_opts(mode='bogus')[1]
    assert sp.make_opts(mode='area', vs_area=True)[0] is None
    assert '--vs-area' in sp.make_opts(mode='area', vs_area=True)[1]


def test_cli_flags_land_on_the_shared_options_dict():
    # The mapping the window has to match. Captured off the REAL CLI path
    # rather than re-derived, so a flag that stops reaching the renderer
    # fails here.
    seen = {}
    real = sp.export
    sp.export = lambda runs, opts, out, stem, warn=None: (
        seen.update(opts=opts, out=out, stem=stem), ('p.png', 'p.csv'))[1]
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(6))
        assert sp.main([d, '--out', d]) == 0
        assert seen['opts'] == sp.make_opts()[0]
        assert seen['stem'] == 'sldea_plot_area'
        assert sp.main([d, '--mode', 'current', '--vs-area', '--prepost',
                        '--mean', '--no-bands', '--no-breakdown',
                        '--title', 'T', '--stem', 's', '--out', d]) == 0
        assert seen['opts'] == sp.make_opts(
            mode='current', vs_area=True, prepost=True, mean=True,
            bands=False, breakdown=False, title='T')[0]
        assert seen['stem'] == 's'
    finally:
        sp.export = real
        shutil.rmtree(d, ignore_errors=True)


def test_output_paths_keep_the_csv_beside_the_png():
    png, tidy = sp.output_paths('/tmp/o', 'fig', 'area')
    assert os.path.basename(png) == 'fig.png'
    assert os.path.basename(tidy) == 'fig.csv'
    assert os.path.dirname(png) == os.path.dirname(tidy)
    # no stem -> the mode's default, so the two modes cannot overwrite
    # each other's figure by accident
    assert sp.output_paths('o', '', 'current')[0].endswith(
        'sldea_plot_current.png')
    assert sp.output_paths('o', None, 'power')[1].endswith(
        'sldea_plot_power.csv')
    assert sp.output_paths('o', '  ', 'area')[0].endswith(
        'sldea_plot_area.png')


def test_export_never_writes_a_png_without_its_csv():
    """`#223`: the tidy CSV is the figure's evidence. A front end that
    could draw to disk without it would break the provenance that makes a
    figure citable -- so export() is the only write path and it writes
    both."""
    if not _has_mpl():
        return
    d, out = _mktmp(), _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        runs = sp.prepare_runs([d], sp.make_opts()[0])
        assert runs
        sub = os.path.join(out, 'made', 'up')      # created on demand
        png, tidy = sp.export(runs, sp.make_opts()[0], sub, 'fig')
        assert os.path.exists(png) and os.path.exists(tidy)
        with open(tidy, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 17 and rows[0].keys() == \
            dict.fromkeys(sp.TIDY_COLS).keys()
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


def test_window_export_is_byte_identical_to_the_cli():
    """The window must not be a fork. save_figure() skips pyplot (it runs
    in a process that owns a live Tk canvas, and matplotlib.use('Agg')
    would switch the backend underneath it) -- but it has to land on the
    same bytes as the command line, or 'the same figure' is a story.

    Every FORMAT and a non-default dpi (`#314`), because the two paths
    now decide more than they used to: an SVG written through the Agg
    canvas has to be the SVG pyplot writes, and a dpi that reached only
    one of them would be exactly this bug wearing a new hat."""
    if not _has_mpl():
        return
    d, out = _mktmp(), _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        for mode in sp.MODES:
            for fmt, dpi in (('png', 300), ('png', 120), ('svg', 300)):
                opts = sp.make_opts(mode=mode, fmt=fmt, dpi=dpi)[0]
                runs = sp.prepare_runs([d], opts)
                tag = f"{mode}_{fmt}{dpi}"
                cli = os.path.join(out, f"{tag}_cli.{fmt}")
                if mode == 'area':
                    sp.figure_area(runs, opts, cli)
                else:
                    sp.figure_signal(runs, opts, cli)
                gui = sp.save_figure(runs, opts,
                                     os.path.join(out, f"{tag}_g.{fmt}"))
                with open(cli, 'rb') as a, open(gui, 'rb') as b:
                    assert a.read() == b.read(), tag
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


def test_prepare_runs_is_the_gate_both_front_ends_pass_through():
    # A raw run: area mode drops it with a reason, current keeps it. The
    # window shows exactly these warnings, so the wording is the contract.
    d = _mktmp()
    try:
        rows = _healthy_rows(6)
        for r in rows:
            r['active_area_mm2'] = ''
            r['active_area_px'] = ''
            r['notes'] = ''
        _fake_run(d, rows)
        warns = []
        assert sp.prepare_runs([d], sp.make_opts()[0], warns.append) == []
        assert any('no reviewed areas' in w for w in warns), warns
        warns = []
        runs = sp.prepare_runs([d], sp.make_opts(mode='current')[0],
                               warns.append)
        assert len(runs) == 1 and runs[0]['color'] == sp.TOL_BRIGHT[0]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_prepare_runs_clears_a_previous_modes_area_blanking():
    """The window reuses loaded run dicts across redraws. 'suspect_kept'
    is set per mode, so leaving a stale True behind would blank the area
    columns of a perfectly good area-mode CSV."""
    d = _mktmp()
    try:
        rows = _healthy_rows(6, ts='2026-07-20T10:00:00')
        for r in rows:
            if r.get('active_area_mm2'):
                r['active_area_mm2'] = round(r['active_area_mm2'] * 2.5, 3)
        _fake_run(d, rows)
        cache = {}

        def load(a, warn):
            if a not in cache:
                cache[a] = sp.load_run(a, warn)
            return cache[a]

        runs = sp.prepare_runs([d], sp.make_opts(mode='current')[0],
                               load=load)
        assert runs and runs[0]['suspect_kept'] is True
        # same dict, now with the era override on: areas are legitimate
        runs = sp.prepare_runs([d], sp.make_opts(mode='current')[0],
                               allow_suspect=True, load=load)
        assert runs and runs[0]['suspect_kept'] is False
        assert runs[0] is cache[d], 'the cached dict was not reused'
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_gui_flag_opens_the_window_without_run_arguments():
    """`--gui` is the one path that does not need runs on the command
    line -- the window has its own picker. Flags given alongside it
    preselect."""
    import sldea_plot_gui
    seen = {}
    real = sldea_plot_gui.launch
    sldea_plot_gui.launch = lambda args, **kw: (
        seen.update(args=list(args), **kw), 0)[1]
    try:
        assert sp.main(['--gui']) == 0
        assert seen['args'] == [] and seen['opts']['mode'] == 'area'
        assert seen['out_dir'] is None and seen['stem'] is None
        assert sp.main(['--gui', 'RUNA', 'RUNB', '--mode', 'power',
                        '--no-bands', '--out', 'O', '--stem', 'S']) == 0
        assert seen['args'] == ['RUNA', 'RUNB']
        assert seen['opts']['mode'] == 'power'
        assert seen['opts']['bands'] is False
        assert seen['out_dir'] == 'O' and seen['stem'] == 'S'
        # a bad combination is still refused before any window opens
        assert sp.main(['--gui', '--mode', 'nope']) == 2
    finally:
        sldea_plot_gui.launch = real


# --------------------------------------------------------------------------
# the compatibility invariant: adding options must not move a pixel of the
# figure nobody asked to change. The `#223` refactor proved 'the window is
# not a fork' by comparing bytes; this proves 'the new options are not a
# rewrite' the same way -- against the REAL pre-change engine, read out of
# git, so both halves run on the same matplotlib and the comparison means
# something on any machine.
# --------------------------------------------------------------------------

# the commit this branch was cut from (the `#223` plot-window merge). Kept
# as a SHA rather than a stored PNG because PNG bytes carry the matplotlib
# version -- a golden file would rot on the next upgrade, this cannot.
_BASE_SHA = 'd11b01ad0b9e3e28786d482fabb4fe6027a4438e'


def _pre_change_module():
    """sldea_plot as of _BASE_SHA, as an importable module, or None.

    None when the object is not reachable (no git, a shallow clone, an
    exported tarball) -- the caller then SKIPS and says so, because a
    compatibility test that quietly passes when it cannot compare is
    worse than no test."""
    import importlib.util
    import subprocess
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    try:
        got = subprocess.run(['git', 'show', _BASE_SHA + ':sldea_plot.py'],
                             cwd=root, capture_output=True, timeout=30)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if got.returncode != 0 or not got.stdout:
        return None
    spec = importlib.util.spec_from_loader('sldea_plot_pre_change',
                                           loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = os.path.join(root, 'sldea_plot.py')
    exec(compile(got.stdout.decode('utf-8'), '<sldea_plot@base>', 'exec'),
         mod.__dict__)
    return mod


def _default_opts_pair(old, mode):
    """(new opts, old opts) for `mode` with every new option at the value
    that reproduces the pre-change figure. Extended once per new option,
    which is the point: an option that CANNOT be turned back off shows up
    here as a test that no longer compiles."""
    return (sp.make_opts(mode=mode, marker_key=False)[0],
            old.make_opts(mode=mode)[0])


def test_default_output_is_byte_identical_to_the_pre_change_engine():
    if not _has_mpl():
        return
    old = _pre_change_module()
    if old is None:
        print('  (skipped: pre-change sldea_plot not reachable via git)')
        return
    d, out = _mktmp(), _mktmp()
    try:
        rows = _healthy_rows(8)
        for snap, ua in ((14, -80.0), (15, -140.0), (16, -205.0)):
            rows[snap - 1]['measured_uA'] = ua      # exercise the X marks
        _fake_run(d, rows)
        for mode in sp.MODES:
            new_opts, old_opts = _default_opts_pair(old, mode)
            new_png = sp.save_figure(
                sp.prepare_runs([d], new_opts), new_opts,
                os.path.join(out, mode + '_new.png'))
            old_png = old.save_figure(
                old.prepare_runs([d], old_opts), old_opts,
                os.path.join(out, mode + '_old.png'))
            with open(new_png, 'rb') as a, open(old_png, 'rb') as b:
                assert a.read() == b.read(), f"{mode} PNG moved"
            new_csv = sp.write_tidy(sp.prepare_runs([d], new_opts),
                                    os.path.join(out, mode + '_new.csv'))
            old_csv = old.write_tidy(old.prepare_runs([d], old_opts),
                                     os.path.join(out, mode + '_old.csv'))
            # THE ONE DELIBERATE MOVE (`#313`): the tidy CSV gained a
            # 'group' column, because a figure whose two lines are the CB
            # mean and the P3 mean cannot be reproduced from a table that
            # does not say which run was in which line. So the claim
            # sharpens rather than lapses -- drop the new column and
            # every other byte, in every row, must still be identical.
            # Ungrouped, that column is empty at every row, which is
            # asserted here too: adding the option must not have changed
            # what an ungrouped export SAYS, only what it can say.
            assert sp.TIDY_COLS[1] == 'group', sp.TIDY_COLS
            assert 'group' not in old.TIDY_COLS, 'base already had it'
            with open(new_csv, newline='', encoding='utf-8') as a, \
                    open(old_csv, newline='', encoding='utf-8') as b:
                new_rows = list(csv.reader(a))
                old_rows = list(csv.reader(b))
            assert {r[1] for r in new_rows[1:]} <= {''}, \
                'an ungrouped export wrote a group'
            assert [r[:1] + r[2:] for r in new_rows] == old_rows, \
                f"{mode} CSV moved beyond the new column"
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


# --------------------------------------------------------------------------
# log scales (`#263`)
# --------------------------------------------------------------------------

def test_log_scale_kind_is_chosen_from_the_data():
    """The `#263` policy: positive data -> log10; anything <= 0 -> symlog
    with a decade-floored linthresh, so no point is clipped away."""
    assert sp.log_scale_for([1.0, 2.0, 300.0]) == ('log', None)
    kind, lin = sp.log_scale_for([-16.0, -15.9, -10.5])
    assert kind == 'symlog' and lin == 10.0, lin      # min |v| 10.5 -> 10
    kind, lin = sp.log_scale_for([0.0, 0.5, 8.0])     # the 0 kV baseline
    assert kind == 'symlog' and lin == 0.1, lin
    # nothing a log scale can show -> leave the axis linear, never raise
    assert sp.log_scale_for([]) is None
    assert sp.log_scale_for([0.0, 0.0]) is None
    assert sp.log_scale_for([None, float('nan'), float('inf')]) is None


def test_log_flags_reach_the_axes_on_the_happy_and_nonpositive_paths():
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        # areas are strictly positive -> plain log10 on both panels
        opts = sp.make_opts(logy=True)[0]
        runs = sp.prepare_runs([d], opts)
        fig = _drawn(runs, opts)
        assert [a.get_yscale() for a in fig.axes] == ['log', 'log']
        assert [a.get_xscale() for a in fig.axes] == ['linear', 'linear']
        assert 'Y axis: log10.' in _caption(fig)
        # the x axis starts at the 0 kV baseline row -> symlog, and the
        # baseline level is still drawn (nothing clipped)
        opts = sp.make_opts(logx=True)[0]
        fig = _drawn(sp.prepare_runs([d], opts), opts)
        assert [a.get_xscale() for a in fig.axes] == ['symlog', 'symlog']
        assert 'symlog' in _caption(fig) and '≤ 0' in _caption(fig)
        assert min(min(l.get_xdata()) for l in fig.axes[0].get_lines()) == 0
        # currents are NEGATIVE on the -16 uA era: symlog keeps the whole
        # trace where a plain log would have dropped every point
        opts = sp.make_opts(mode='current', logy=True)[0]
        fig = _drawn(sp.prepare_runs([d], opts), opts)
        assert fig.axes[0].get_yscale() == 'symlog'
        ys = [y for l in fig.axes[0].get_lines() for y in l.get_ydata()]
        assert any(y < 0 for y in ys), 'negative currents were dropped'
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_log_axis_with_nothing_to_scale_stays_linear_and_says_so():
    """A power figure whose every point is exactly 0 (a run sitting on its
    own median) has no log axis to draw. It must caption that, not raise
    and not silently pretend the axis is logarithmic."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        rows = [{'snapshot': 1, 'tag': 'baseline', 'nominal_kV': 0,
                 'measured_uA': -16.0, 'timestamp': '2026-08-05T10:00:00'}]
        for n in range(2, 8):        # flat current -> power is 0 everywhere
            rows.append({'snapshot': n, 'tag': 'pre-ramp', 'nominal_kV': n,
                         'measured_uA': -16.0,
                         'timestamp': '2026-08-05T10:00:00'})
        _fake_run(d, rows)
        opts = sp.make_opts(mode='power', logy=True)[0]
        fig = _drawn(sp.prepare_runs([d], opts), opts)
        assert fig.axes[0].get_yscale() == 'linear'
        assert 'left linear' in _caption(fig)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_log_flags_survive_the_cli_and_land_on_the_options_dict():
    seen = {}
    real = sp.export
    sp.export = lambda runs, opts, out, stem, warn=None: (
        seen.update(opts=opts), ('p.png', 'p.csv'))[1]
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(6))
        assert sp.main([d, '--out', d, '--logx', '--logy']) == 0
        assert seen['opts']['logx'] and seen['opts']['logy']
        assert sp.main([d, '--out', d]) == 0
        assert not seen['opts']['logx'] and not seen['opts']['logy']
    finally:
        sp.export = real
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------
# the marker key (`#267`)
# --------------------------------------------------------------------------

def _legend_texts(ax):
    """Every legend on `ax` -> {title: [row labels]}. A second legend only
    survives when the first was re-added as an artist, so reading them all
    back is also the collision test."""
    from matplotlib.legend import Legend
    out = {}
    for art in ax.get_children():
        if isinstance(art, Legend):
            title = art.get_title().get_text()
            out[title] = [t.get_text() for t in art.get_texts()]
    return out


def test_marker_key_is_on_by_default_and_does_not_eat_the_run_legend():
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        opts = sp.make_opts()[0]
        fig = _drawn(sp.prepare_runs([d], opts), opts)
        legends = _legend_texts(fig.axes[0])
        assert len(legends) == 2, legends           # both survived
        key = legends.get('marker fill')
        assert key == ['hand-traced (outer toe)',
                       'machine (half-height)'], legends
        # the run legend still carries the run, in its own corner
        runs_leg = [v for k, v in legends.items() if k != 'marker fill'][0]
        assert any('sldea_plot_test' in t for t in runs_leg), runs_leg
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_no_marker_key_hides_it_and_current_power_never_show_one():
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        opts = sp.make_opts(marker_key=False)[0]
        fig = _drawn(sp.prepare_runs([d], opts), opts)
        assert 'marker fill' not in _legend_texts(fig.axes[0])
        assert len(_legend_texts(fig.axes[0])) == 1
        # current/power draw one plain dot per snapshot -- there is no
        # open/closed meaning there, so the key must not appear even ON
        for mode in ('current', 'power'):
            opts = sp.make_opts(mode=mode)[0]
            assert opts['marker_key'] is True
            fig = _drawn(sp.prepare_runs([d], opts), opts)
            assert 'marker fill' not in _legend_texts(fig.axes[0]), mode
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_no_marker_key_flag_reaches_the_options_dict():
    seen = {}
    real = sp.export
    sp.export = lambda runs, opts, out, stem, warn=None: (
        seen.update(opts=opts), ('p.png', 'p.csv'))[1]
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(6))
        assert sp.main([d, '--out', d]) == 0
        assert seen['opts']['marker_key'] is True
        assert sp.main([d, '--out', d, '--no-marker-key']) == 0
        assert seen['opts']['marker_key'] is False
    finally:
        sp.export = real
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------
# per-panel titles (`#269`)
# --------------------------------------------------------------------------

def _titles(fig):
    """Panel headings, in axes order. loc='left' on purpose -- that is
    where the figures put them, and the default get_title() reads the
    (always empty) centre slot."""
    return [a.get_title(loc='left') for a in fig.axes]


def test_panel_titles_default_then_take_the_per_panel_override():
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        opts = sp.make_opts()[0]
        assert _titles(_drawn(sp.prepare_runs([d], opts), opts)) == [
            'Active area vs voltage',
            'Normalized to baseline area (A₀ = 201.1 mm²)']
        opts = sp.make_opts(title_first='Absolute', title_second='Norm')[0]
        assert _titles(_drawn(sp.prepare_runs([d], opts), opts)) == \
            ['Absolute', 'Norm']
        # one override leaves the other panel's default alone
        opts = sp.make_opts(title_second='Only the right one')[0]
        got = _titles(_drawn(sp.prepare_runs([d], opts), opts))
        assert got == ['Active area vs voltage', 'Only the right one'], got
        # single-panel modes: 'first' is the panel, 'second' does nothing
        for mode, default in (('current', 'Current -- per snapshot'),
                              ('power', 'Power -- per snapshot')):
            opts = sp.make_opts(mode=mode, title_second='ignored')[0]
            assert _titles(_drawn(sp.prepare_runs([d], opts), opts)) == \
                [default], mode
            opts = sp.make_opts(mode=mode, title_first='Mine')[0]
            assert _titles(_drawn(sp.prepare_runs([d], opts), opts)) == \
                ['Mine'], mode
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_legacy_title_still_means_the_first_panel_and_loses_to_it():
    """--title shipped before per-panel titles and has always set the
    first panel's heading. A script that says --title must keep its
    figure; --title-first is the precise name for the same slot."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        opts = sp.make_opts(title='Legacy')[0]
        got = _titles(_drawn(sp.prepare_runs([d], opts), opts))
        assert got[0] == 'Legacy'
        assert got[1] == 'Normalized to baseline area (A₀ = 201.1 mm²)'
        opts = sp.make_opts(title='Legacy', title_first='Precise')[0]
        assert _titles(_drawn(sp.prepare_runs([d], opts), opts))[0] == \
            'Precise'
        # blank is 'no override', not an empty heading, on every route in
        assert sp.make_opts(title_first='', title_second='  ')[0][
            'title_first'] is None
        opts = sp.make_opts(title_first='   ')[0]
        assert _titles(_drawn(sp.prepare_runs([d], opts), opts))[0] == \
            'Active area vs voltage'
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_title_flags_reach_the_options_dict():
    seen = {}
    real = sp.export
    sp.export = lambda runs, opts, out, stem, warn=None: (
        seen.update(opts=opts), ('p.png', 'p.csv'))[1]
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(6))
        assert sp.main([d, '--out', d, '--title-first', 'A',
                        '--title-second', 'B']) == 0
        assert seen['opts']['title_first'] == 'A'
        assert seen['opts']['title_second'] == 'B'
        assert seen['opts']['title'] is None
        # still a valued flag: a missing value is refused, not swallowed
        assert sp.main([d, '--title-first']) == 2
    finally:
        sp.export = real
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------
# panel selection (`#270`)
# --------------------------------------------------------------------------

def test_a_single_chosen_panel_is_the_only_axes_on_the_figure():
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        opts = sp.make_opts()[0]
        assert len(_drawn(sp.prepare_runs([d], opts), opts).axes) == 2
        # first: the absolute-area panel, alone, filling the canvas
        opts = sp.make_opts(subplots='first')[0]
        fig = _drawn(sp.prepare_runs([d], opts), opts)
        assert len(fig.axes) == 1, 'an empty axes was left behind'
        assert _titles(fig) == ['Active area vs voltage']
        assert fig.axes[0].get_ylabel() == 'Active area (mm²)'
        box = fig.axes[0].get_position()
        assert box.width > 0.7, box          # the whole canvas, not half
        # second: the normalized panel, alone, and it inherits the legend
        # and the marker key that used to live on the left one
        opts = sp.make_opts(subplots='second')[0]
        fig = _drawn(sp.prepare_runs([d], opts), opts)
        assert len(fig.axes) == 1
        assert fig.axes[0].get_ylabel() == 'Expansion  A / A₀'
        assert 'Normalized' in _titles(fig)[0]
        assert 'marker fill' in _legend_texts(fig.axes[0])
        assert len(_legend_texts(fig.axes[0])) == 2
        assert fig.axes[0].get_position().width > 0.7
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_panel_selection_refuses_only_the_panel_that_does_not_exist():
    assert sp.make_opts(subplots='bogus')[0] is None
    assert '--subplots' in sp.make_opts(subplots='bogus')[1]
    # single-panel modes: 'first' names the only panel (no-op), 'second'
    # asks for one that is not drawn
    for mode in ('current', 'power'):
        assert sp.make_opts(mode=mode, subplots='first')[0]['subplots'] \
            == 'first'
        o, err = sp.make_opts(mode=mode, subplots='second')
        assert o is None and '--subplots second' in err, err
    assert sp.make_opts(mode='area', subplots='second')[1] is None


def test_panel_selection_reaches_export_and_the_csv_stays_whole():
    """`#270`: the PNG follows the selection, the tidy CSV does not. The
    CSV is the evidence for the numbers, and both panels are two views of
    the same areas -- dropping rows to match a layout choice would make
    the figure's own evidence depend on how it was framed."""
    if not _has_mpl():
        return
    d, out = _mktmp(), _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        assert sp.main([d, '--out', out, '--stem', 'both']) == 0
        assert sp.main([d, '--out', out, '--stem', 'one',
                        '--subplots', 'second']) == 0
        with open(os.path.join(out, 'both.csv'), 'rb') as a, \
                open(os.path.join(out, 'one.csv'), 'rb') as b:
            assert a.read() == b.read(), 'the tidy CSV followed the layout'
        with open(os.path.join(out, 'both.png'), 'rb') as a, \
                open(os.path.join(out, 'one.png'), 'rb') as b:
            assert a.read() != b.read(), 'the PNG ignored --subplots'
        # a bad value is refused before anything is written
        assert sp.main([d, '--out', out, '--subplots', 'sideways']) == 2
        assert sp.main([d, '--out', out, '--mode', 'current',
                        '--subplots', 'second']) == 2
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


# --------------------------------------------------------------------------
# the figspec sidecar (`#273`)
# --------------------------------------------------------------------------

def _read_json(path):
    import json
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def test_export_writes_the_figspec_beside_the_png_and_csv():
    if not _has_mpl():
        return
    d, out = _mktmp(), _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        opts = sp.make_opts(prepost=True, logy=True, title_first='T')[0]
        runs = sp.prepare_runs([d], opts)
        png, tidy = sp.export(runs, opts, out, 'fig')
        spec_path = sp.figspec_path(png)
        assert os.path.exists(spec_path)
        assert os.path.dirname(spec_path) == os.path.dirname(png)
        spec = _read_json(spec_path)
        assert spec['spec_version'] == sp.SPEC_VERSION
        assert spec['opts'] == opts, spec['opts']
        assert spec['stem'] == 'fig'
        assert spec['app_version'] and isinstance(spec['app_version'], str)
        # runs are stored RESOLVED and absolute -- a bench shortcut or a
        # parent-of-runs argument means a different run tomorrow
        assert spec['runs'] == [os.path.abspath(d)], spec['runs']
        # a blank stem records the EFFECTIVE one, so a re-render lands on
        # the same filenames instead of on 'None.png'
        png2, _ = sp.export(runs, opts, out, '')
        assert _read_json(sp.figspec_path(png2))['stem'] == \
            'sldea_plot_area'
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


def test_figspec_round_trip_re_renders_a_byte_identical_png():
    """The whole promise of `#273`: the sidecar is enough to make the
    figure again. Non-default options on purpose -- a round trip that
    only exercises the defaults proves nothing."""
    if not _has_mpl():
        return
    d, out, again = _mktmp(), _mktmp(), _mktmp()
    try:
        rows = _healthy_rows(8)
        for snap, ua in ((14, -80.0), (15, -140.0), (16, -205.0)):
            rows[snap - 1]['measured_uA'] = ua
        _fake_run(d, rows)
        assert sp.main([d, '--out', out, '--stem', 'rt', '--prepost',
                        '--mean', '--no-bands', '--logy',
                        '--title-first', 'One', '--title-second', 'Two',
                        '--subplots', 'second']) == 0
        spec = os.path.join(out, 'rt.figspec.json')
        assert os.path.exists(spec)
        assert sp.main(['--from-spec', spec, '--out', again]) == 0
        with open(os.path.join(out, 'rt.png'), 'rb') as a, \
                open(os.path.join(again, 'rt.png'), 'rb') as b:
            assert a.read() == b.read(), 're-render is not the same figure'
        with open(os.path.join(out, 'rt.csv'), 'rb') as a, \
                open(os.path.join(again, 'rt.csv'), 'rb') as b:
            assert a.read() == b.read()
        # and the spec the re-render wrote says the same thing
        assert _read_json(os.path.join(again, 'rt.figspec.json'))['opts'] \
            == _read_json(spec)['opts']
    finally:
        for p in (d, out, again):
            shutil.rmtree(p, ignore_errors=True)


def test_explicit_flags_override_the_spec_and_runs_replace_it():
    if not _has_mpl():
        return
    d, d2, out = _mktmp(), _mktmp(), _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        _fake_run(d2, _healthy_rows(6))
        assert sp.main([d, '--out', out, '--stem', 'base', '--logy',
                        '--subplots', 'first', '--title', 'Spec title',
                        '--no-marker-key']) == 0
        spec = os.path.join(out, 'base.figspec.json')
        seen = {}
        real = sp.export
        sp.export = lambda runs, opts, o, stem, warn=None: (
            seen.update(opts=opts, out=o, stem=stem,
                        runs=[r['dir'] for r in runs]),
            ('p.png', 'p.csv'))[1]
        try:
            # nothing explicit -> everything comes from the spec
            assert sp.main(['--from-spec', spec, '--out', out]) == 0
            assert seen['opts'] == _read_json(spec)['opts']
            assert seen['stem'] == 'base'
            assert seen['runs'] == [os.path.abspath(d)]
            # explicit flags win, per option, and a RUN replaces the list
            assert sp.main([d2, '--from-spec', spec, '--out', out,
                            '--mode', 'current', '--stem', 'over']) == 0
            assert seen['opts']['mode'] == 'current'
            assert seen['opts']['logy'] is True        # kept from the spec
            assert seen['opts']['title'] == 'Spec title'
            assert seen['opts']['marker_key'] is False
            assert seen['stem'] == 'over'
            assert seen['runs'] == [d2], seen['runs']
            # a --no-... flag can still switch a spec's true off
            assert sp.main(['--from-spec', spec, '--out', out,
                            '--no-breakdown']) == 0
            assert seen['opts']['breakdown'] is False
        finally:
            sp.export = real
    finally:
        for p in (d, d2, out):
            shutil.rmtree(p, ignore_errors=True)


def test_a_bad_spec_is_refused_rather_than_half_understood():
    import json
    out = _mktmp()
    try:
        def spec_file(name, payload):
            p = os.path.join(out, name)
            with open(p, 'w', encoding='utf-8') as f:
                if isinstance(payload, str):
                    f.write(payload)
                else:
                    json.dump(payload, f)
            return p
        good = {'spec_version': sp.SPEC_VERSION, 'opts':
                sp.make_opts()[0], 'runs': ['x'], 'stem': 's'}
        assert sp.load_figspec(spec_file('ok.json', good))[0] is not None
        assert sp.main(['--from-spec',
                        os.path.join(out, 'nope.json')]) == 2
        assert sp.main(['--from-spec',
                        spec_file('bad.json', '{not json')]) == 2
        assert sp.main(['--from-spec', spec_file('list.json', [1, 2])]) == 2
        newer = dict(good, spec_version=sp.SPEC_VERSION + 1)
        _, err = sp.load_figspec(spec_file('new.json', newer))
        assert 'newer build' in err, err
        for broken, needle in (
                (dict(good, spec_version='1'), 'positive integer'),
                (dict(good, opts=None), "no 'opts'"),
                (dict(good, runs='not-a-list'), 'list of'),
                (dict(good, runs=[1, 2]), 'list of')):
            spec, err = sp.load_figspec(spec_file('b.json', broken))
            assert spec is None and needle in err, (err, needle)
        # an ILLEGAL combination inside an otherwise valid spec is refused
        # with the CLI's own wording, not silently rendered
        bad_combo = dict(good, opts=dict(sp.make_opts()[0], vs_area=True))
        assert sp.main(['--from-spec',
                        spec_file('combo.json', bad_combo)]) == 2
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_from_spec_preselects_the_window_too():
    import json
    import sldea_plot_gui
    out = _mktmp()
    seen = {}
    real = sldea_plot_gui.launch
    sldea_plot_gui.launch = lambda args, **kw: (
        seen.update(args=list(args), **kw), 0)[1]
    try:
        p = os.path.join(out, 'w.figspec.json')
        with open(p, 'w', encoding='utf-8') as f:
            json.dump({'spec_version': sp.SPEC_VERSION, 'stem': 'st',
                       'runs': ['RUNA', 'RUNB'],
                       'opts': sp.make_opts(mode='power')[0]}, f)
        assert sp.main(['--gui', '--from-spec', p]) == 0
        assert seen['args'] == ['RUNA', 'RUNB']
        assert seen['opts']['mode'] == 'power'
        assert seen['stem'] == 'st'
    finally:
        sldea_plot_gui.launch = real
        shutil.rmtree(out, ignore_errors=True)


# --------------------------------------------------------------------------
# the cadence guard (`#264`)
# --------------------------------------------------------------------------

def _spaced_rows(seconds, n_levels=8):
    """_healthy_rows with the snapshots `seconds` apart instead of all
    sharing one timestamp."""
    import datetime
    rows = _healthy_rows(n_levels)
    t0 = datetime.datetime(2026, 8, 5, 10, 0, 0)
    for i, r in enumerate(rows):
        r['timestamp'] = (t0 + datetime.timedelta(
            seconds=i * seconds)).isoformat()
    for snap, ua in ((14, -80.0), (15, -140.0), (16, -205.0)):
        rows[snap - 1]['measured_uA'] = ua
    return rows


def test_cadence_comes_from_telemetry_then_from_snapshot_spacing():
    d = _mktmp()
    try:
        _fake_run(d, _spaced_rows(30))
        secs, src = sp.run_cadence(d, sp.load_rows(d))
        assert abs(secs - 30.0) < 1e-6 and src == 'snapshot spacing'
        # telemetry.csv beside data.csv answers on PRESENCE -- a truncated
        # or aborted log still means the run was monitored
        with open(os.path.join(d, 'telemetry.csv'), 'w',
                  encoding='utf-8') as f:
            f.write('t_s,timestamp\n')
        secs, src = sp.run_cadence(d, sp.load_rows(d))
        assert secs <= sp.CADENCE_COARSE_S and src == 'telemetry.csv'
        assert sp.load_run(d, lambda m: None)['cadence_src'] == \
            'telemetry.csv'
    finally:
        shutil.rmtree(d, ignore_errors=True)
    # no parseable timestamps -> no answer, and 'unknown' is never 'fine'
    d2 = _mktmp()
    try:
        _fake_run(d2, _healthy_rows(4, ts=''))
        assert sp.run_cadence(d2, sp.load_rows(d2)) == (None, 'unknown')
        run = sp.load_run(d2, lambda m: None)
        assert not sp.coarse_cadence(run, sp.make_opts(
            cadence_guard=True)[0])
    finally:
        shutil.rmtree(d2, ignore_errors=True)


def test_coarse_cadence_marks_stay_on_the_figure_and_say_the_spacing():
    """The guard annotates, it does not hide: a current-confirmed event
    drawn hollow is still drawn. Suppressing it because the camera was
    slow would be the P3_5 mistake pointing the other way."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        _fake_run(d, _spaced_rows(32.5))
        for mode in ('area', 'current'):
            plain = sp.make_opts(mode=mode)[0]
            guard = sp.make_opts(mode=mode, cadence_guard=True)[0]
            warns = []
            fig = _drawn(sp.prepare_runs([d], plain, warns.append), plain)
            assert not any('sampled every' in w for w in warns), warns
            marks = _cross_faces(fig)
            assert marks and all(f != (1.0, 1.0, 1.0, 1.0)
                                 for f in marks), mode
            warns = []
            runs = sp.prepare_runs([d], guard, warns.append)
            fig = _drawn(runs, guard, warns.append)
            guarded = _cross_faces(fig)
            # same number of X marks, now hollow
            assert len(guarded) == len(marks), mode
            assert all(f == (1.0, 1.0, 1.0, 1.0) for f in guarded), mode
            cap = _caption(fig)
            assert 'Hollow X' in cap and '32.5 s' in cap, cap
            assert 'snapshot spacing' in cap, cap
            assert any('sampled every 32.5 s' in w for w in warns), warns
            # ONE line, and short enough to stay on the narrowest canvas
            # (9 in fits ~170 characters at 7 pt) -- a caption that runs
            # off the figure says nothing
            hollow = [l for l in cap.split('\n') if l.startswith('Hollow')]
            assert len(hollow) == 1, cap
            assert len(hollow[0]) < 170, (len(hollow[0]), hollow[0])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _cross_faces(fig):
    """The face colour of every 'X' breakdown marker on the first axes,
    as RGBA. White = hollow = the cadence guard annotated it."""
    from matplotlib.colors import to_rgba
    return [to_rgba(l.get_markerfacecolor())
            for l in fig.axes[0].get_lines() if l.get_marker() == 'X']


def test_a_fast_run_is_not_annotated_even_with_the_guard_on():
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        _fake_run(d, _spaced_rows(0.5))       # telemetry-grade cadence
        opts = sp.make_opts(cadence_guard=True)[0]
        warns = []
        runs = sp.prepare_runs([d], opts, warns.append)
        assert runs[0]['cadence_s'] <= sp.CADENCE_COARSE_S
        fig = _drawn(runs, opts)
        assert 'Hollow X' not in _caption(fig)
        assert all(f != (1.0, 1.0, 1.0, 1.0) for f in _cross_faces(fig))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_cadence_guard_is_opt_in_and_no_breakdown_is_unchanged():
    """OFF by default on purpose: no run in the corpus carries
    telemetry.csv and every one samples current far slower than 1 s, so
    an automatic guard would restyle every figure the suite has made.
    That is a measurement-chain decision, not a rendering default."""
    if not _has_mpl():
        return
    assert sp.make_opts()[0]['cadence_guard'] is False
    seen = {}
    real = sp.export
    sp.export = lambda runs, opts, out, stem, warn=None: (
        seen.update(opts=opts), ('p.png', 'p.csv'))[1]
    d = _mktmp()
    try:
        _fake_run(d, _spaced_rows(32.5))
        assert sp.main([d, '--out', d]) == 0
        assert seen['opts']['cadence_guard'] is False
        assert sp.main([d, '--out', d, '--cadence-guard']) == 0
        assert seen['opts']['cadence_guard'] is True
    finally:
        sp.export = real
        shutil.rmtree(d, ignore_errors=True)
    # --no-breakdown still means no marks at all, guard or no guard
    d = _mktmp()
    try:
        _fake_run(d, _spaced_rows(32.5))
        opts = sp.make_opts(breakdown=False, cadence_guard=True)[0]
        fig = _drawn(sp.prepare_runs([d], opts), opts)
        assert _cross_faces(fig) == []
        assert 'Hollow X' not in _caption(fig)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# the cross-run aggregate (`#268`, policy SLDEA_HANDOFF.md 2026-08-09)
# ---------------------------------------------------------------------------

def _agg_run(d, name, kvs, area_at, ts='2026-08-05T10:00:00', ua=None):
    """A run whose levels are exactly `kvs` with area `area_at(kv)`.

    One snapshot per level (no pre/post pair) so a level's mean IS the
    number written here -- the aggregate arithmetic is then hand-checkable
    without going through the pair aggregation as well. `ua` overrides the
    current per level, which is how a breakdown gets confirmed."""
    rows = [{'snapshot': 1, 'tag': 'baseline', 'nominal_kV': 0,
             'measured_uA': -16.0, 'active_area_px': 100000,
             'active_area_mm2': 100.0, 'timestamp': ts,
             'notes': 'edge:resting conf 0.95'}]
    for i, kv in enumerate(kvs, start=2):
        rows.append({'snapshot': i, 'tag': 'post-ramp', 'nominal_kV': kv,
                     'measured_uA': (ua(kv) if ua else -16.0),
                     'active_area_px': 100000 + 1000 * i,
                     'active_area_mm2': area_at(kv), 'timestamp': ts,
                     'notes': 'edge:disc-fit conf 0.93'})
    sub = os.path.join(d, name)
    _fake_run(sub, rows)
    run = sp.load_run(sub, lambda m: None)
    run['color'] = '#4477AA'
    return run


def test_aggregate_of_one_run_refuses_the_band_and_says_so():
    """The n = 1 rule, decided by the owner 2026-08-09: NO BAND, plus a
    caption saying the aggregate needs >= 2 runs.

    A refusal that can actually fail, which is why it is a refusal and not
    a silent fallback -- the tempting alternative is to quietly draw the
    calibrated +-1-2% budget band instead, which would dress a claim about
    the INSTRUMENT up as a claim about the family."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        one = _agg_run(d, 'R1', [1.0, 2.0, 3.0], lambda kv: 100.0 + 10 * kv)
        ag = sp.aggregate_levels([one], norm=True)
        assert [l['n'] for l in ag] == [1, 1, 1, 1], ag
        assert all(l['sd'] is None and l['sem'] is None for l in ag), ag
        opts = sp.make_opts(aggregate=True)[0]
        warns = []
        fig = _drawn([one], opts, warns.append)
        cap = _caption(fig)
        assert 'NO BAND' in cap, cap
        assert '≥ 2 runs' in cap, cap
        assert any('NO BAND' in w for w in warns), warns
        # and the refusal is REAL: nothing shaded was drawn on either panel
        assert _band_count(fig) == 0, 'a band survived the n = 1 refusal'
        # two runs earn one
        two = _agg_run(d, 'R2', [1.0, 2.0, 3.0], lambda kv: 102.0 + 10 * kv)
        fig2 = _drawn([one, two], sp.make_opts(aggregate=True)[0])
        assert 'NO BAND' not in _caption(fig2)
        assert 'σ/√n' in _caption(fig2), _caption(fig2)
        assert _band_count(fig2) > 0, 'n = 2 earned no band'
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_aggregate_band_is_the_standard_error_of_the_mean():
    """SEM = sigma/sqrt(n) with the SAMPLE (n-1) deviation, hand-checked.

    Four runs, one level, areas 100/110/120/130 mm2 against A0 = 100:
    mean 115, deviations -15/-5/+5/+15, sum of squares 500, sample
    variance 500/3 = 166.667, sigma = 12.90994, SEM = sigma/2 = 6.45497.
    The n-1 denominator is the decision being pinned: these runs are a
    SAMPLE of a family, not the family."""
    d = _mktmp()
    try:
        runs = [_agg_run(d, f"R{i}", [1.0], lambda kv, a=a: a)
                for i, a in enumerate((100.0, 110.0, 120.0, 130.0))]
        lv = next(l for l in sp.aggregate_levels(runs) if l['kv'] == 1.0)
        assert lv['n'] == 4, lv
        assert abs(lv['mean'] - 115.0) < 1e-9, lv
        assert abs(lv['sd'] - 12.909944487358056) < 1e-9, lv
        assert abs(lv['sem'] - 6.454972243679028) < 1e-9, lv
        # ddof=0 would give sigma 11.18034 / SEM 5.59017 -- pinned so a
        # "simpler" population formula cannot slip in unnoticed
        assert abs(lv['sd'] - 11.180339887498949) > 1e-6, 'ddof=0 crept in'
        # and A/A0 rescales by each run's own A0 (all 100 here), so the
        # normalized band is the same numbers over 100
        lvn = next(l for l in sp.aggregate_levels(runs, norm=True)
                   if l['kv'] == 1.0)
        assert abs(lvn['mean'] - 1.15) < 1e-9, lvn
        assert abs(lvn['sem'] - 0.06454972243679028) < 1e-9, lvn
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_aggregate_never_extrapolates_past_a_runs_own_range():
    """Guardrail 1. A run that stops at 3 kV LEAVES the aggregate above
    3 kV; it is not extended into it on the strength of its last point."""
    d = _mktmp()
    try:
        short = _agg_run(d, 'SHORT', [1.0, 2.0, 3.0],
                         lambda kv: 100.0 + 10 * kv)
        long_ = _agg_run(d, 'LONG', [1.0, 2.0, 3.0, 4.0, 5.0],
                         lambda kv: 100.0 + 12 * kv)
        ag = {l['kv']: l for l in sp.aggregate_levels([short, long_])}
        assert ag[3.0]['n'] == 2, ag[3.0]
        # above the short run's last level it contributes NOTHING -- not a
        # held-flat value, not a linear continuation
        for kv in (4.0, 5.0):
            assert ag[kv]['n'] == 1, (kv, ag[kv])
            assert ag[kv]['n_interpolated'] == 0, ag[kv]
            assert abs(ag[kv]['mean'] - (100.0 + 12 * kv)) < 1e-9, ag[kv]
            # n = 1 -> no band at that level either; a lone run's mean must
            # not inherit its neighbours' confidence
            assert ag[kv]['sem'] is None, ag[kv]
        # the guard is in _contribution, so it holds off-figure too
        curve = sp.run_level_curve(short)
        assert sp._contribution(curve, 4.0) is None
        assert sp._contribution(curve, 0.5) is not None      # inside: fine
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_aggregate_never_interpolates_across_a_breakdown():
    """Guardrail 2, and the reason it is NOT made redundant by the cap.

    The cap drops levels at or above the first breakdown, but a level just
    BELOW it can still be reached by interpolating a segment whose upper
    end is the collapsed reading -- and a device that collapses between
    two levels did not travel down the straight line joining them.

    Reproduced on the real corpus 2026-08-09: SLDEA_20260723_233451 steps
    0.2 kV and breaks down at 5.6 kV, so at the 0.25 kV grid's 5.5 kV
    level it would otherwise be interpolated 5.4 -> 5.6, straight through
    the event. It declines, and n drops 6 -> 5 at exactly that level."""
    d = _mktmp()
    try:
        # a 0.2 kV stepper that collapses at 1.6 kV, against a 0.25 stepper
        def ua(kv):
            return -200.0 if kv >= 1.6 else -16.0

        def area(kv):
            return 40.0 if kv >= 1.6 else 100.0 + 10 * kv
        fine = _agg_run(d, 'FINE', [0.2 * i for i in range(1, 11)],
                        area, ua=ua)
        assert sp.first_breakdown_kv(fine) == 1.6, sp.first_breakdown_kv(fine)
        curve = sp.run_level_curve(fine)
        # 1.5 sits between the run's 1.4 and its CONFIRMED 1.6 -- refused
        assert sp._contribution(curve, 1.5) is None
        # 1.3 sits between two clean levels -- interpolated, as normal
        got = sp._contribution(curve, 1.3)
        assert got is not None and got[1] is False, got
        assert abs(got[0] - 113.0) < 1e-9, got
        coarse = _agg_run(d, 'COARSE', [0.25 * i for i in range(1, 9)],
                          lambda kv: 100.0 + 11 * kv)
        ag = {l['kv']: l for l in sp.aggregate_levels([fine, coarse])}
        assert sp.aggregate_cap_kv([fine, coarse]) == 1.6
        assert max(ag) < 1.6, max(ag)                 # the cap
        assert 1.5 in ag, sorted(ag)                  # below it, so kept
        assert ag[1.5]['n'] == 1, ag[1.5]             # ...but FINE declined
        assert ag[1.5]['n_interpolated'] == 0, ag[1.5]
        assert ag[1.25]['n'] == 2, ag[1.25]           # a clean segment
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_aggregate_records_measured_versus_interpolated_per_level():
    """Guardrail 3. A level carried by one measured run and two
    interpolated ones is not the same evidence as three measured ones, and
    with a uniform n nothing else on the figure would tell them apart."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        fine = _agg_run(d, 'FINE', [0.2, 0.4, 0.6, 0.8, 1.0],
                        lambda kv: 100.0 + 10 * kv)
        c1 = _agg_run(d, 'C1', [0.25, 0.5, 0.75, 1.0],
                      lambda kv: 100.0 + 11 * kv)
        c2 = _agg_run(d, 'C2', [0.25, 0.5, 0.75, 1.0],
                      lambda kv: 100.0 + 12 * kv)
        ag = {l['kv']: l for l in sp.aggregate_levels([fine, c1, c2])}
        # a 0.25 grid level: measured by the two coarse runs, interpolated
        # for the fine one
        assert (ag[0.5]['n'], ag[0.5]['n_measured'],
                ag[0.5]['n_interpolated']) == (3, 2, 1), ag[0.5]
        assert sp.aggregate_support(ag[0.5]) == '2+1'
        # a 0.2 grid level: the other way round
        assert (ag[0.4]['n'], ag[0.4]['n_measured'],
                ag[0.4]['n_interpolated']) == (3, 1, 2), ag[0.4]
        assert sp.aggregate_support(ag[0.4]) == '1+2'
        # a level every run really measured prints the bare n
        assert ag[1.0]['n_interpolated'] == 0 and ag[1.0]['n'] == 3
        assert sp.aggregate_support(ag[1.0]) == '3'
        # measured + interpolated is ALWAYS n -- the label cannot lie by
        # losing a contribution somewhere
        for l in ag.values():
            assert l['n_measured'] + l['n_interpolated'] == l['n'], l
        # and it is SURFACED, on the figure and on the console -- on the
        # EXCEPTIONS only since `#312`: the thin levels keep their count,
        # the level all three runs really measured carries none, and the
        # caption states the n it falls short of
        opts = sp.make_opts(aggregate=True)[0]
        warns = []
        fig = _drawn([fine, c1, c2], opts, warns.append)
        labels = {t.get_text() for a in fig.axes for t in a.texts}
        assert '2+1' in labels and '1+2' in labels, labels
        assert '3' not in labels, 'a full-support level still printed its n'
        assert any('measured' in w and 'interpolated' in w for w in warns), \
            warns
        assert 'measured + ' in _caption(fig), _caption(fig)
        assert 'n = 3 at every level except' in _caption(fig), _caption(fig)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _marker_key_legend(ax):
    """The 'marker fill' legend on `ax`, or None -- it is a second Legend
    beside the run legend, so it has to be picked out by its title."""
    for a in ax.get_children():
        if (a.__class__.__name__ == 'Legend'
                and a.get_title().get_text() == 'marker fill'):
            return a
    return None


def test_only_the_levels_short_of_the_captions_n_still_print_a_count():
    """`#312`. Every level used to print its own support count, which
    under the default interpolated grid is the SAME NUMBER at every level
    -- a row of identical digits, and it ran straight through the marker
    key. The counts still have to survive where they mean something, so
    the caption states the one n and only the exceptions are marked.

    The exception test is on MEASURED support, not on n, and that is the
    whole of it: a level carried by one measured run and four
    interpolated ones sits at exactly full n, so comparing n alone would
    leave unmarked the very case guardrail 3 exists for."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        fine = _agg_run(d, 'FINE', [0.2, 0.4, 0.6, 0.8, 1.0],
                        lambda kv: 100.0 + 10 * kv)
        c1 = _agg_run(d, 'C1', [0.25, 0.5, 0.75, 1.0],
                      lambda kv: 100.0 + 11 * kv)
        c2 = _agg_run(d, 'C2', [0.25, 0.5, 0.75, 1.0],
                      lambda kv: 100.0 + 12 * kv)
        ag = sp.aggregate_levels([fine, c1, c2])
        by_kv = {l['kv']: l for l in ag}
        assert sp.aggregate_full_n(ag) == 3
        thin = {l['kv'] for l in sp.aggregate_thin_levels(ag)}
        # 1.0 kV: every run measured it -> not an exception
        assert by_kv[1.0]['n'] == 3 and by_kv[1.0]['n_interpolated'] == 0
        assert 1.0 not in thin, 'a fully measured level was marked'
        # 0.4 kV: full n, but ONE measured value and two interpolated --
        # the case a plain `n < max` rule would miss
        assert by_kv[0.4]['n'] == sp.aggregate_full_n(ag)
        assert by_kv[0.4]['n_measured'] == 1
        assert 0.4 in thin, 'a thinly interpolated level went unmarked'
        assert 0.5 in thin, thin                       # 2 measured of 3
        # and it is exactly {short of n} u {any interpolation}
        assert thin == {l['kv'] for l in ag
                        if l['n'] < 3 or l['n_interpolated']}, thin
        # an empty aggregate has no maximum to fall short of
        assert sp.aggregate_full_n([]) == 0
        assert sp.aggregate_thin_levels([]) == []
        # ONE run on ONE grid: nothing is interpolated, so nothing is
        # marked and the caption carries the whole story
        opts = sp.make_opts(aggregate=True)[0]
        fig = _drawn([c1, c2], opts)
        assert not [t for a in fig.axes for t in a.texts], \
            'a single-grid family still printed per-level counts'
        assert 'n = 2 at every level, all measured.' in _caption(fig), \
            _caption(fig)
        # ...and neither wording outgrew the width the aggregate caption
        # is written to (7 pt on a 12.6 in figure runs off the right edge
        # past ~215 characters, which is how an early draft lost the cap
        # sentence entirely)
        for pool in ([c1, c2], [fine, c1, c2]):
            text = sp._aggregate_caption(pool, sp.aggregate_levels(pool),
                                         opts, None)
            for line in text.split('\n'):
                assert len(line) <= 215, (len(line), line)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_support_row_clears_the_marker_key_at_every_figure_size():
    """`#312`'s acceptance, measured rather than eyeballed.

    The row of counts was placed in AXES FRACTIONS and the marker key in
    font-sized padding from the corner. Two units, one shared corner: they
    agree at no size at all -- on the campaign corpus the key sat on the
    counts and neither was readable. Both are now measured in POINTS from
    the axes floor, so the clearance is arithmetic and, being points, it
    is the SAME at every size the window can be dragged to.

    Sizes span 3.2x2.0 in (below anything the window permits) to 20x9,
    including a wide-and-short one, because a fraction-based row would
    fail first exactly where the axes are shortest."""
    if not _has_mpl():
        return
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    d = _mktmp()
    try:
        kv25 = [round(0.25 * i, 3) for i in range(1, 41)]     # to 10 kV
        kv20 = [round(0.20 * i, 3) for i in range(1, 51)]     # ...and 0.2
        runs = [_agg_run(d, 'FINE', kv20, lambda kv: 100.0 + 10 * kv),
                _agg_run(d, 'C1', kv25, lambda kv: 100.0 + 11 * kv),
                _agg_run(d, 'C2', kv25, lambda kv: 100.0 + 12 * kv)]
        opts = sp.make_opts(aggregate=True)[0]
        # the labels have to reach the key's own corner, or the test
        # would pass on a figure that never put them near each other
        ag = sp.aggregate_levels(runs)
        assert max(l['kv'] for l in sp.aggregate_thin_levels(ag)) >= 9.0
        tightest = set()
        for size in ((12.6, 5.4), (20.0, 9.0), (6.0, 3.0), (4.0, 2.2),
                     (14.0, 2.6), (3.2, 2.0)):
            fig = Figure(figsize=size)
            FigureCanvasAgg(fig)
            sp.draw(fig, runs, opts, lambda m: None)
            fig.canvas.draw()
            rend = fig.canvas.get_renderer()
            for ax in fig.axes:
                key = _marker_key_legend(ax)
                if key is None:
                    continue
                kb = key.get_window_extent(rend)
                assert ax.texts, 'no support row on the key\'s own axis'
                gaps = []
                for t in ax.texts:
                    tb = t.get_window_extent(rend)
                    assert not tb.overlaps(kb), \
                        (size, t.get_text(), 'under the marker key')
                    gaps.append(kb.y0 - tb.y1)
                # the taller of the two staggered rows is the one that
                # decides whether the key clears anything
                tightest.add(round(min(gaps), 1))
        # points, not fractions: ONE clearance across every size above
        assert len(tightest) == 1, \
            f"clearance varies with figure size: {tightest}"
        assert tightest.pop() > 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_figure_with_nothing_to_mark_leaves_the_marker_key_alone():
    """The lift is the support row asking for a floor, so a figure
    without one keeps the corner it always had -- the aggregate is not
    allowed to restyle every other figure in the suite on its way past.

    Read off the legend's ANCHOR BOX against the axes it sits in, which
    is what 'lower right' is measured from: unlifted the two are the same
    rectangle, lifted the anchor floor is MARKER_KEY_LIFT_PT above the
    axes floor -- in points, so the same at any size."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        c1 = _agg_run(d, 'C1', [0.25, 0.5, 0.75, 1.0],
                      lambda kv: 100.0 + 11 * kv)
        c2 = _agg_run(d, 'C2', [0.25, 0.5, 0.75, 1.0],
                      lambda kv: 100.0 + 12 * kv)
        fine = _agg_run(d, 'FINE', [0.2, 0.4, 0.6, 0.8, 1.0],
                        lambda kv: 100.0 + 10 * kv)

        def floors(runs, opts):
            fig = _drawn(runs, opts)
            fig.canvas.draw()
            out = []
            for ax in fig.axes:
                key = _marker_key_legend(ax)
                if key is not None:
                    out.append((key.get_bbox_to_anchor().y0, ax.bbox.y0,
                                fig.dpi))
            assert out, 'no marker key drawn'
            return out

        for opts in (sp.make_opts()[0], sp.make_opts(aggregate=True)[0]):
            for anchor_y0, axes_y0, _dpi in floors([c1, c2], opts):
                assert anchor_y0 == axes_y0, \
                    'the key left its corner with nothing to clear'
        # ...and the mixed grid, which DOES mark levels, lifts it by
        # exactly the declared number of points
        for anchor_y0, axes_y0, dpi in floors(
                [fine, c1, c2], sp.make_opts(aggregate=True)[0]):
            lift_px = sp.MARKER_KEY_LIFT_PT * dpi / 72.0
            assert abs((anchor_y0 - axes_y0) - lift_px) < 0.5, \
                (anchor_y0 - axes_y0, lift_px)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_aggregate_suppresses_the_calibrated_budget_band():
    """The +-1-2% budget is ONE run's instrument error and must not sit
    under a cross-run mean -- the same argument that suppresses it under
    --prepost, where the gap between the two lines is the information.

    Counted off the drawn figure rather than the opts dict, because a
    dict that says 'aggregate' and a figure with five budget bands under
    it is exactly the half-consumed-option failure the landing-site map
    warns about."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        r1 = _agg_run(d, 'R1', [1.0, 2.0, 3.0], lambda kv: 100.0 + 10 * kv)
        r2 = _agg_run(d, 'R2', [1.0, 2.0, 3.0], lambda kv: 102.0 + 10 * kv)
        plain = _drawn([r1, r2], sp.make_opts()[0])
        n_budget = _band_count(plain)
        assert n_budget >= 2, 'the budget band is not being drawn at all'
        agg = _drawn([r1, r2], sp.make_opts(aggregate=True)[0])
        # exactly the aggregate's OWN band survives, per panel
        assert _band_count(agg) == 2, _band_count(agg)
        assert 'bands ±2% machine' not in _caption(agg), _caption(agg)
        assert 'suppressed under it' in _caption(agg), _caption(agg)
        # --no-bands under the aggregate still leaves the SEM band: the
        # tick box names the BUDGET band, and the aggregate's band is the
        # figure's whole claim
        both = _drawn([r1, r2], sp.make_opts(aggregate=True, bands=False)[0])
        assert _band_count(both) == 2, _band_count(both)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_exact_key_toggle_really_changes_the_pooling():
    """Interpolation is the DEFAULT and exact-key pooling the toggle.

    Measured on the corpus 2026-08-09: eight runs step 0.25 kV and one
    steps 0.2, sharing only 8 of 41 levels, so exact pooling drops it at
    33 of 41 and n alternates 4/5 level to level -- a band that steps for
    a reason that is an artifact of grid choice, not of the devices."""
    d = _mktmp()
    try:
        fine = _agg_run(d, 'FINE', [0.2, 0.4, 0.6, 0.8, 1.0],
                        lambda kv: 100.0 + 10 * kv)
        coarse = _agg_run(d, 'COARSE', [0.25, 0.5, 0.75, 1.0],
                          lambda kv: 100.0 + 20 * kv)
        assert sp.make_opts()[0]['aggregate_exact'] is False, 'wrong default'
        soft = sp.aggregate_levels([fine, coarse], exact=False)
        hard = sp.aggregate_levels([fine, coarse], exact=True)
        # interpolation gives a UNIFORM n; exact pooling alternates
        assert {l['n'] for l in soft} == {2}, [(l['kv'], l['n'])
                                               for l in soft]
        assert {l['n'] for l in hard} == {1, 2}, [(l['kv'], l['n'])
                                                  for l in hard]
        # ...and where n = 1 there is no band at all under exact pooling
        assert [l['kv'] for l in hard if l['sem'] is None] == \
            [0.2, 0.25, 0.4, 0.5, 0.6, 0.75, 0.8], hard
        # exact pooling never invents a value: every contribution measured
        assert all(l['n_interpolated'] == 0 for l in hard), hard
        assert any(l['n_interpolated'] for l in soft), soft
        # the two agree exactly where both runs really measured
        assert soft[-1]['mean'] == hard[-1]['mean']
        # and the toggle reaches the figure through the CLI
        o, err = sp._cli_opts({'--aggregate', '--aggregate-exact'}, {})
        assert not err and o['aggregate'] and o['aggregate_exact']
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_aggregate_stops_at_the_first_breakdown_across_the_runs():
    """The cap is the LOWEST first-breakdown kV, not each run's own: past
    the first collapse the mean mixes intact and collapsed devices, which
    is not a physical quantity.

    It keys on CURRENT-CONFIRMED breakdown, the only kind this tool has
    trusted since 2026-08-05 -- so it is deliberately independent of
    --no-breakdown, which hides X marks without un-collapsing a device."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        # the event sits near the TOP of the staircase on purpose:
        # breakdown_flags measures deviation against the run's own MEDIAN
        # current, so a run that is mostly collapsed drags the baseline
        # onto the collapsed value and confirms every row including the
        # resting one (measured while writing this test)
        def ua(kv):
            return -300.0 if kv >= 4.5 else -16.0

        def area(kv):
            return 30.0 if kv >= 4.5 else 100.0 + 10 * kv
        kvs = [1.0 + 0.5 * i for i in range(9)]        # 1.0 .. 5.0
        broke = _agg_run(d, 'BROKE', kvs, area, ua=ua)
        fine_ = _agg_run(d, 'FINE', kvs, lambda kv: 100.0 + 11 * kv)
        assert sp.first_breakdown_kv(broke) == 4.5
        assert sp.first_breakdown_kv(fine_) is None
        assert sp.aggregate_cap_kv([broke, fine_]) == 4.5
        ag = sp.aggregate_levels([broke, fine_])
        assert max(l['kv'] for l in ag) == 4.0, [l['kv'] for l in ag]
        # the healthy run reaches 5.0 on its own -- it is the OTHER run's
        # collapse that ends the average, because past it the mean mixes
        # intact and collapsed devices
        assert max(p['key'] for p in sp.run_level_curve(fine_)) == 5.0
        assert 'Stops at 4.5 kV' in _caption(
            _drawn([broke, fine_], sp.make_opts(aggregate=True)[0]))
        # --no-breakdown hides the X marks; the cap is untouched
        no_x = sp.make_opts(aggregate=True, breakdown=False)[0]
        assert 'Stops at 4.5 kV' in _caption(_drawn([broke, fine_], no_x))
        # nothing broke down -> no cap, and the figure SAYS the cap did not
        # fire rather than implying it looked and found nothing (the P3
        # campaign's real state: zero current-confirmed breakdowns)
        warns = []
        fig = _drawn([fine_], sp.make_opts(aggregate=True)[0], warns.append)
        assert 'cap did not fire' in _caption(fig), _caption(fig)
        assert any('cap did not fire' in w for w in warns), warns
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_aggregate_is_refused_outside_area_mode_in_both_front_ends():
    """current/power plot one point per SNAPSHOT, with no level structure
    to pool. Refused loudly rather than ignored: a flag that quietly does
    nothing is landing-site 2's silent failure wearing a different hat."""
    assert sp.make_opts(aggregate=True)[1] is None
    for mode in ('current', 'power'):
        opts, err = sp.make_opts(mode=mode, aggregate=True)
        assert opts is None and 'area mode only' in err, (mode, err)
    # the CLI refuses it with the same wording, and main() prints it
    opts, err = sp._cli_opts({'--aggregate'}, {'--mode': 'current'})
    assert opts is None and 'area mode only' in err, err
    # aggregate_exact alone is a harmless no-op, exactly like --mean
    # without --prepost -- it is a CHILD of --aggregate, not a mode
    o, err = sp._cli_opts({'--aggregate-exact'}, {'--mode': 'current'})
    assert err is None and o['aggregate_exact'] and not o['aggregate']


# ---------------------------------------------------------------------------
# aggregating BY GROUP (`#313`) -- CB against P3 as two mean lines
#
# The comparison the campaign exists for. Everything below is measured off
# the drawn Figure or the written CSV rather than off the opts dict: an
# option half-consumed by the drawing code produces a figure that looks
# perfectly finished, which is landing site 5 and is how `#268` nearly
# shipped a caption describing a band it had not drawn.
# ---------------------------------------------------------------------------

def _agg_lines(fig, panel=0):
    """-> {label: handle} for the RUN legend of `fig`'s panel.

    Not ax.get_legend(): matplotlib keeps one ax.legend_ and `#267`'s
    marker key is created second, so get_legend() answers with the key
    and the run legend is the artist _marker_key re-added by hand. The
    one WITHOUT the 'marker fill' title is the one this asks about."""
    from matplotlib.legend import Legend
    legs = [c for c in fig.axes[panel].get_children()
            if isinstance(c, Legend)
            and c.get_title().get_text() != 'marker fill']
    assert legs, 'no run legend on this panel'
    return {t.get_text(): h
            for t, h in zip(legs[0].get_texts(), legs[0].legend_handles)}


def _thick(fig, panel=0):
    """The aggregate curves actually drawn on a panel: linewidth 2.2 is
    _aggregate_series' own, and no run curve uses it (runs are 1.8)."""
    return [ln for ln in fig.axes[panel].get_lines()
            if abs(ln.get_linewidth() - 2.2) < 1e-6]


def test_two_groups_draw_two_means_and_each_gets_its_own_band_rule():
    """THE `#313` FIGURE, and the n = 1 rule holding PER GROUP.

    On the real campaign the carbon-black group is a single run and the
    P3 group is five, so 'no band at n = 1' is not a corner case here --
    it is one of the two curves. A single band policy applied to the
    whole figure would be wrong about one of them whichever way it went.
    """
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        cb = _agg_run(d, 'CB1', [1.0, 2.0, 3.0], lambda kv: 100.0 + 5 * kv)
        p1 = _agg_run(d, 'P3_1', [1.0, 2.0, 3.0], lambda kv: 110.0 + 10 * kv)
        p2 = _agg_run(d, 'P3_2', [1.0, 2.0, 3.0], lambda kv: 120.0 + 10 * kv)
        groups = [['CB', [cb['dir']]], ['P3', [p1['dir'], p2['dir']]]]
        opts, err = sp.make_opts(aggregate=True, groups=groups)
        assert err is None, err
        warns = []
        fig = _drawn([cb, p1, p2], opts, warns.append)
        # TWO aggregate curves, not one, on BOTH panels (site 5: the
        # option has to reach the mm² panel and the A/A0 panel alike)
        assert len(_thick(fig, 0)) == 2, _thick(fig, 0)
        assert len(_thick(fig, 1)) == 2, _thick(fig, 1)
        # ...distinguishable from each other, by colour AND by style
        colors = {ln.get_color() for ln in _thick(fig, 0)}
        styles = {ln.get_linestyle() for ln in _thick(fig, 0)}
        assert len(colors) == 2, colors
        assert len(styles) == 2, styles
        assert colors <= set(sp.GROUP_COLORS), colors
        # ...and neither wears a RUN's colour
        assert not (colors & {r['color'] for r in (cb, p1, p2)}), colors
        # the legend names both groups and states each one's band
        labels = _agg_lines(fig)
        assert 'CB — mean of 1 run (no band)' in labels, labels
        assert 'P3 — mean of 2 runs (±SEM)' in labels, labels
        # THE BAND RULE, per group: exactly one shaded band on each panel
        # -- P3's. The n = 1 group's absence is the refusal, and the
        # caption has to say so rather than leaving it to be noticed.
        assert _band_count(fig) == 2, 'one SEM band per panel, P3 only'
        cap = _caption(fig)
        assert 'CB (solid, 1 run — NO BAND)' in cap, cap
        assert '≥ 2 runs' in cap, cap
        # the mean is the group's own, hand-checked: P3 at 3.0 kV is the
        # mean of 140 and 150 in mm², and CB's is its single run's 115
        p3_line = [ln for ln in _thick(fig, 0)
                   if ln.get_color() == sp.GROUP_COLORS[1]][0]
        cb_line = [ln for ln in _thick(fig, 0)
                   if ln.get_color() == sp.GROUP_COLORS[0]][0]
        assert list(p3_line.get_ydata())[-1] == 145.0, p3_line.get_ydata()
        assert list(cb_line.get_ydata())[-1] == 115.0, cb_line.get_ydata()
        # and the console says it PER GROUP, naming which
        assert any("group 'CB'" in w and 'NO BAND' in w for w in warns), \
            warns
        assert not any("group 'P3'" in w and 'NO BAND' in w for w in warns)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_group_caps_and_pools_on_its_own_runs_only():
    """Every `#268` rule is computed from THAT GROUP's runs. The tempting
    shortcut -- one cap, one grid, one n for the figure -- would let a
    breakdown in the CB run truncate the P3 mean, which is a claim about
    P3 that no P3 device made."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        # A breaks down near the top of its staircase; B and C never do.
        # The event sits high on purpose, for the reason the cap test
        # above records: breakdown_flags measures deviation against the
        # run's OWN median current, so a mostly-collapsed run drags the
        # baseline onto the collapsed value and confirms every row.
        kvs = [1.0 + 0.5 * i for i in range(9)]           # 1.0 .. 5.0
        a = _agg_run(d, 'A', kvs,
                     lambda kv: 30.0 if kv >= 4.5 else 100.0 + 5 * kv,
                     ua=lambda kv: -300.0 if kv >= 4.5 else -16.0)
        b = _agg_run(d, 'B', kvs, lambda kv: 110.0 + 10 * kv)
        c = _agg_run(d, 'C', kvs, lambda kv: 120.0 + 10 * kv)
        assert sp.first_breakdown_kv(a) == 4.5, a['flags']
        assert sp.first_breakdown_kv(b) is None
        groups = [['broken', [a['dir']]], ['whole', [b['dir'], c['dir']]]]
        opts = sp.make_opts(aggregate=True, groups=groups)[0]
        fig = _drawn([a, b, c], opts)
        by_color = {ln.get_color(): ln for ln in _thick(fig, 0)}
        broken = by_color[sp.GROUP_COLORS[0]]
        whole = by_color[sp.GROUP_COLORS[1]]
        # the capped group stops; the other runs the whole staircase, and
        # an ungrouped aggregate over all three would have stopped both
        assert max(broken.get_xdata()) < 4.5, broken.get_xdata()
        assert max(whole.get_xdata()) == 5.0, whole.get_xdata()
        assert max(l['kv'] for l in sp.aggregate_levels([a, b, c])) < 4.5, \
            'fixture: the shared cap would not have been visible'
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_hiding_the_contributing_runs_leaves_the_means_and_says_so():
    """'so the panel is two lines and not fifteen' -- the operator's own
    words. Counted off the Figure, because a caption claiming the runs
    are hidden over a panel still carrying them is the exact failure this
    is measured to prevent."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        runs = [_agg_run(d, f"R{i}", [1.0, 2.0, 3.0],
                         lambda kv, i=i: 100.0 + i + 10 * kv)
                for i in range(4)]
        groups = [['X', [r['dir'] for r in runs[:2]]],
                  ['Y', [r['dir'] for r in runs[2:]]]]
        shown = sp.make_opts(aggregate=True, groups=groups)[0]
        hidden = sp.make_opts(aggregate=True, groups=groups,
                              aggregate_only=True)[0]
        n_shown = len(_drawn(runs, shown).axes[0].get_lines())
        fig = _drawn(runs, hidden)
        assert len(_thick(fig, 0)) == 2, 'the group means went too'
        # every line left on the panel IS an aggregate -- no run curve and
        # no per-point run marker. _aggregate_series draws two Line2D per
        # group (the curve, then its square markers), so two groups is
        # four and anything above that is a run that survived.
        assert len(fig.axes[0].get_lines()) == 4, fig.axes[0].get_lines()
        assert all(ln.get_color() in sp.GROUP_COLORS
                   for ln in fig.axes[0].get_lines())
        assert n_shown > 6, 'fixture drew too few run artists to matter'
        cap = _caption(fig)
        assert 'Per-run curves HIDDEN' in cap, cap
        # the caption that describes per-run markers and X marks is gone
        # with them -- it would be describing a figure that is not there
        assert 'Open markers' not in cap, cap
        # ...and the members are named, because the legend no longer can
        assert 'Members: X = R0, R1; Y = R2, R3.' in cap, cap
        # the marker key explains RUN markers and goes with them
        assert fig.axes[0].get_legend().get_title().get_text() != \
            'marker fill'
        # refused without the aggregate: on its own it empties the figure
        bad, err = sp.make_opts(aggregate_only=True)
        assert bad is None and '--aggregate-only needs --aggregate' in err
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_tidy_csv_carries_the_grouping_the_figure_was_drawn_from():
    """Landing site 9. `#313` asked for this in as many words: 'the tidy
    CSV export should gain a group column, or the figure cannot be
    reproduced from its own data'. A two-line CB-vs-P3 figure whose CSV
    cannot say which run was in which line is not evidence for it."""
    if not _has_mpl():
        return
    d, out = _mktmp(), _mktmp()
    try:
        cb = _agg_run(d, 'CB1', [1.0, 2.0], lambda kv: 100.0 + 5 * kv)
        p1 = _agg_run(d, 'P3_1', [1.0, 2.0], lambda kv: 110.0 + 10 * kv)
        loose = _agg_run(d, 'LOOSE', [1.0, 2.0], lambda kv: 90.0 + kv)
        groups = [['CB', [cb['dir']]], ['P3', [p1['dir']]]]
        opts = sp.make_opts(aggregate=True, groups=groups)[0]
        img, tidy = sp.export([cb, p1, loose], opts, out, 'g')
        with open(tidy, newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        got = {r['run']: r['group'] for r in rows}
        assert got == {'CB1': 'CB', 'P3_1': 'P3', 'LOOSE': ''}, got
        # EVERY row of a grouped run carries it, not just the first
        assert all(r['group'] == 'CB' for r in rows if r['run'] == 'CB1')
        # ...and the figspec records the grouping too, so --from-spec
        # re-renders the same two lines rather than one
        spec, err = sp.load_figspec(sp.figspec_path(img))
        assert err is None, err
        assert spec['opts']['groups'] == groups, spec['opts']['groups']
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


def test_a_grouping_survives_the_command_line_and_a_spec_round_trip():
    """Landing sites 2 and 8 together. --group is REPEATABLE, which every
    other valued flag is not ('later wins' would silently draw one curve
    where two were asked for), and it has to survive build_figspec ->
    load_figspec -> _cli_opts, which is the round trip that drops any key
    the CLI's hand-written table does not name."""
    o, err = sp._cli_opts(set(), {'--group': ['CB=r1', 'P3=r2,r3']})
    assert err is None, err
    assert [n for n, _m in o['groups']] == ['CB', 'P3'], o['groups']
    assert len(o['groups'][1][1]) == 2, o['groups']
    # ORDER IS THE OPERATOR'S, and it is what picks the colours -- so it
    # is preserved rather than sorted
    o2, _e = sp._cli_opts(set(), {'--group': ['P3=r2', 'CB=r1']})
    assert [n for n, _m in o2['groups']] == ['P3', 'CB']
    # the spec round trip: a spec's grouping is inherited when no --group
    # is given, and REPLACED wholesale when one is
    back, err = sp._cli_opts(set(), {}, dict(o))
    assert err is None and back['groups'] == o['groups'], back['groups']
    over, _e = sp._cli_opts(set(), {'--group': ['ALL=r1,r2,r3']}, dict(o))
    assert [n for n, _m in over['groups']] == ['ALL']
    # the parser really accumulates rather than overwriting
    args, flags, vals = sp._parse_argv(['x', '--group', 'A=1',
                                        '--group', 'B=2'])
    assert vals['--group'] == ['A=1', 'B=2'], vals
    assert args == ['x'] and not flags
    # a malformed one is refused in the CLI's own words, never half-read
    for bad in ('nonsense', '=r1', 'CB='):
        assert sp._cli_opts(set(), {'--group': [bad]})[1], bad


def test_a_grouping_that_cannot_be_read_is_refused_not_repaired():
    """check_groups is the one gate, so the window and a hand-edited
    config get the identical answer. Each refusal below is a grouping
    with no defensible reading -- unlike an EMPTY group, which is simply
    dropped because the window holds one while a name is being typed."""
    ok, err = sp.check_groups([['CB', ['a']], ['P3', ['b', 'c']]])
    assert err is None and len(ok) == 2, (ok, err)
    # JSON has no tuples: the value that comes back out of a figspec or
    # the options file is lists, and it must read as what went in
    assert sp.check_groups(tuple(tuple(g) for g in ok))[0] == ok
    # a run in two groups: which curve does it belong to?
    assert 'at most one group' in sp.check_groups(
        [['CB', ['a']], ['P3', ['a']]])[1]
    # two groups with one name: which legend entry is which?
    assert sp.check_groups([['CB', ['a']], ['cb', ['b']]])[1]
    for bad in ('a string', [['CB']], [['', ['a']]], [['CB', 'a']],
                [['CB', ['']]], [['x' * 99, ['a']]]):
        assert sp.check_groups(bad)[1], bad
    # an empty group is DROPPED, and the rest survive it
    kept, err = sp.check_groups([['CB', []], ['P3', ['b']]])
    assert err is None and kept == [['P3', [os.path.abspath('b')]]], kept
    # STORED AS SPELLED, matched case-insensitively. The first draft
    # stored the normcased key and every group in the figspec and in the
    # warnings came out lowercased on Windows -- 'P3_1_2.5mL_20260728'
    # reported as 'p3_1_2.5ml_20260728', against a run folder of the
    # other name.
    mixed, err = sp.check_groups([['P3', ['MiXeD_Case_Run']]])
    assert err is None
    assert os.path.basename(mixed[0][1][0]) == 'MiXeD_Case_Run', mixed
    assert sp.run_group({'dir': os.path.abspath('mixed_case_run'),
                         'name': 'mixed_case_run'}, mixed) == 'P3' or \
        os.path.normcase('A') == 'A'


def test_a_group_that_names_a_run_nobody_plotted_says_so():
    """The silent failure this option was always going to have: a typo in
    a run name makes the group average fewer runs and still draw a
    perfectly convincing curve."""
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(6))
        opts = sp.make_opts(aggregate=True, groups=[
            ['P3', [d, os.path.join(os.path.dirname(d), 'NOT_A_RUN')]]])[0]
        warns = []
        runs = sp.prepare_runs([d], opts, warns.append)
        assert len(runs) == 1
        assert any('NOT_A_RUN' in w and "group 'P3'" in w for w in warns), \
            warns
        # ...and no warning when every named run is there
        warns2 = []
        sp.prepare_runs([d], sp.make_opts(
            aggregate=True, groups=[['P3', [d]]])[0], warns2.append)
        assert not any('not on this figure' in w for w in warns2), warns2
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_group_palette_is_separable_and_never_wears_a_run_colour():
    """The `#313` colour question, answered as a property rather than as
    a list of hexes: no group colour may BE a run colour, no two groups
    may share a (colour, style) pair inside one wrap, and the first group
    must still be the black solid curve the ungrouped aggregate draws --
    so turning one group on does not restyle a figure that had none.

    The perceptual measurement behind the CHOICE of palette lives in the
    GROUP_COLORS comment; what a test can hold is the invariant."""
    assert not set(sp.GROUP_COLORS) & set(sp.TOL_BRIGHT)
    assert sp.group_style(0) == (sp.AGGREGATE_COLOR, '-')
    n = len(sp.GROUP_COLORS) * len(sp.GROUP_STYLES)
    pairs = [sp.group_style(i) for i in range(n)]
    assert len(set(pairs)) == n, 'a (colour, style) pair repeats early'
    # inside one palette-width, the COLOURS alone already differ -- the
    # style is the second axis, not a substitute for the first
    assert len({c for c, _s in pairs[:len(sp.GROUP_COLORS)]}) == \
        len(sp.GROUP_COLORS)
    assert len({s for _c, s in pairs[:len(sp.GROUP_STYLES)]}) == \
        len(sp.GROUP_STYLES)


def test_grouping_changes_nothing_when_nobody_asked_for_it():
    """The compatibility half. An option that cannot be turned back off
    is a rewrite; this proves the ungrouped aggregate is untouched, down
    to the bytes."""
    if not _has_mpl():
        return
    d, out = _mktmp(), _mktmp()
    try:
        a = _agg_run(d, 'A', [1.0, 2.0, 3.0], lambda kv: 100.0 + 5 * kv)
        b = _agg_run(d, 'B', [1.0, 2.0, 3.0], lambda kv: 110.0 + 10 * kv)
        opts = sp.make_opts(aggregate=True)[0]
        assert opts['groups'] == [] and opts['aggregate_only'] is False
        one = sp.save_figure([a, b], opts, os.path.join(out, 'plain.png'))
        # a grouping naming runs that are NOT on this figure is inert
        far = sp.make_opts(aggregate=True,
                           groups=[['ELSEWHERE', ['/nowhere/at/all']]])[0]
        two = sp.save_figure([a, b], far, os.path.join(out, 'inert.png'))
        with open(one, 'rb') as f1, open(two, 'rb') as f2:
            assert f1.read() == f2.read(), \
                'a group matching no plotted run changed the figure'
        # ...and the single ungrouped mean is still black, solid, one line
        fig = _drawn([a, b], opts)
        assert len(_thick(fig, 0)) == 1
        assert _thick(fig, 0)[0].get_color() == sp.AGGREGATE_COLOR
        assert 'AGGREGATE BY GROUP' not in _caption(fig)
        assert 'aggregate mean of 2 runs (±SEM)' in _agg_lines(fig)
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


def test_no_caption_line_runs_off_the_right_edge_of_the_figure():
    """MEASURED, 2026-08-10: the first grouped caption's support line ran
    to ~250 characters and the figure cut it mid-word at 'the console
    names eac|', losing the sentence that says where the per-level counts
    went. Group names and run names are operator text, so no amount of
    care in the wording bounds this -- only the fit does."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        runs = [_agg_run(d, 'R' + 'x' * 30 + str(i), [1.0, 2.0],
                         lambda kv, i=i: 100.0 + i + 10 * kv)
                for i in range(6)]
        groups = [[f"group number {i} with a long name", [r['dir']]]
                  for i, r in enumerate(runs)]
        opts = sp.make_opts(aggregate=True, groups=groups)[0]
        cap = _caption(_drawn(runs, opts))
        for line in cap.split('\n'):
            assert len(line) <= sp.CAPTION_LINE_MAX, (len(line), line)
        assert '…' in cap, 'nothing was truncated; fixture too tame'
        # THE BUDGET IS AN ANCHOR, not a guess: 248 is the "Points ="
        # line as it renders under an aggregate, which every figure in
        # the handoff carries and which sits inside the frame.
        under_agg = _caption(_drawn(runs[:1], sp.make_opts(
            aggregate=True)[0])).split('\n')
        assert max(len(l) for l in under_agg[:2]) == sp.CAPTION_LINE_MAX
        # ...and the same line WITHOUT the aggregate is 280, because the
        # band widths are appended whenever the budget bands are drawn.
        # It clips on a default figure -- measured on the corpus, it ends
        # "never averaged), banc". Recorded rather than fixed: that is a
        # pre-existing defect on the most ordinary figure this tool
        # draws, it predates `#313`, and repairing it moves the default
        # figure's pixels, which the byte-identity guard above exists to
        # make a deliberate decision rather than a side effect. The
        # number is asserted so the next change here cannot make it
        # quietly worse.
        plain = _caption(_drawn(runs[:1], sp.make_opts()[0])).split('\n')
        assert max(len(l) for l in plain) == 280, [len(l) for l in plain]
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------
# the export format and the dpi (`#314`) -- the first options that describe
# the FILE rather than the drawing
# --------------------------------------------------------------------------

def _png_size(path):
    """(width, height) in pixels, read straight out of the PNG's IHDR.

    No Pillow: the suite has no image dependency, and thirteen bytes of
    header is a smaller thing to trust than a decoder."""
    with open(path, 'rb') as f:
        head = f.read(24)
    assert head[:8] == b'\x89PNG\r\n\x1a\n', path
    return (int.from_bytes(head[16:20], 'big'),
            int.from_bytes(head[20:24], 'big'))


def test_svg_export_writes_a_real_svg_beside_its_csv_and_figspec():
    """`#314`: the vector option. The three-files-or-nothing rule is
    format-INDEPENDENT -- the tidy CSV is the figure's evidence whatever
    the picture is written as -- so the assertion is not just 'an .svg
    appeared' but 'the whole set did, off one stem'."""
    if not _has_mpl():
        return
    d, out = _mktmp(), _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        opts = sp.make_opts(fmt='svg')[0]
        runs = sp.prepare_runs([d], opts)
        img, tidy = sp.export(runs, opts, out, 'vec')
        assert img == os.path.join(out, 'vec.svg'), img
        # a real SVG, not an empty file with a hopeful name
        with open(img, encoding='utf-8') as f:
            text = f.read()
        assert os.path.getsize(img) > 10000, os.path.getsize(img)
        assert text.lstrip().startswith('<?xml'), text[:80]
        assert '<svg' in text and '</svg>' in text
        # ...and it really is vector: the area figure's own axis label is
        # in there as text/paths, and no raster payload is embedded
        assert 'image/png' not in text, 'the SVG embedded a bitmap'
        # the set, off ONE stem
        assert tidy == os.path.join(out, 'vec.csv')
        spec = sp.figspec_path(img)
        assert spec == os.path.join(out, 'vec.figspec.json')
        for p in (tidy, spec):
            assert os.path.exists(p) and os.path.getsize(p) > 0, p
        # the CSV is the same evidence the PNG would have been given
        raster = sp.make_opts()[0]
        png_img, png_tidy = sp.export(sp.prepare_runs([d], raster), raster,
                                      out, 'ras')
        assert png_img == os.path.join(out, 'ras.png'), png_img
        with open(tidy, 'rb') as a, open(png_tidy, 'rb') as b:
            assert a.read() == b.read(), 'the tidy CSV followed the format'
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


def test_the_dpi_reaches_the_raster_and_cannot_reach_the_vector():
    """Two claims in one, and the second is the point of greying the
    field: a PNG really is written at the dpi that was asked for, and an
    SVG is byte-for-byte the same file at 50 dpi as at 1200 -- so a dpi
    under SVG is INERT, which is what the window's greyed box says, and
    not silently applied behind it."""
    if not _has_mpl():
        return
    d, out = _mktmp(), _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        wide, tall = sp.FIGSIZE['area']
        for dpi in (100, 300, 600):
            opts = sp.make_opts(dpi=dpi)[0]
            png = sp.save_figure(sp.prepare_runs([d], opts), opts,
                                 os.path.join(out, f"r{dpi}.png"))
            # matplotlib rounds the inch x dpi product; 1 px of slack
            w, h = _png_size(png)
            assert abs(w - wide * dpi) <= 1 and abs(h - tall * dpi) <= 1, \
                (dpi, w, h)
        # the default is still 300, i.e. the pre-`#314` file exactly
        assert _png_size(os.path.join(out, 'r300.png')) == _png_size(
            sp.save_figure(sp.prepare_runs([d], sp.make_opts()[0]),
                           sp.make_opts()[0], os.path.join(out, 'def.png')))
        svgs = []
        for dpi in (sp.DPI_MIN, sp.DPI_MAX):
            opts = sp.make_opts(fmt='svg', dpi=dpi)[0]
            assert opts['dpi'] == dpi, 'the value was not even carried'
            path = sp.save_figure(sp.prepare_runs([d], opts), opts,
                                  os.path.join(out, f"v{dpi}.svg"))
            with open(path, 'rb') as f:
                svgs.append(f.read())
        assert svgs[0] == svgs[1], 'a dpi changed a vector file'
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


def test_a_dpi_or_format_outside_the_sane_range_is_refused():
    """REFUSED, not clamped and not ignored (`#314`). A typed '30000' asks
    for a render that looks exactly like a hang, and a clamp would answer
    it with a figure nobody asked for -- the same silent-success failure
    the landing-site map exists to prevent."""
    for bad in (30000, 0, -300, 49, 1201, 'abc', '', True, 12.5):
        opts, err = sp.make_opts(dpi=bad)
        if bad == '':                 # a blank box is the ABSENCE of a
            assert err is None and opts['dpi'] == sp.DEFAULT_DPI   # request
            continue
        assert opts is None, bad
        assert '--dpi' in err, (bad, err)
    # the boundaries themselves are IN
    for good in (sp.DPI_MIN, sp.DPI_MAX, '600'):
        opts, err = sp.make_opts(dpi=good)
        assert err is None and opts['dpi'] == int(good), (good, err)
    # None means unset, which is how every caller that says nothing about
    # the dpi still gets the 300 every pre-`#314` export used
    assert sp.make_opts(dpi=None)[0]['dpi'] == sp.DEFAULT_DPI
    # an unknown format is refused in the CLI's own vocabulary
    for bad in ('tiff', 'PNG', 'pdf', ''):
        opts, err = sp.make_opts(fmt=bad)
        assert opts is None and '--format' in err, (bad, err)
    # ...and the CLI refuses before it writes anything
    d, out = _mktmp(), _mktmp()
    try:
        _fake_run(d, _healthy_rows(6))
        assert sp.main([d, '--out', out, '--dpi', '30000']) == 2
        assert sp.main([d, '--out', out, '--dpi', 'lots']) == 2
        assert sp.main([d, '--out', out, '--format', 'tiff']) == 2
        assert os.listdir(out) == [], os.listdir(out)
        # and a good one still writes the three files
        assert sp.main([d, '--out', out, '--stem', 'ok', '--format', 'svg',
                        '--dpi', '600']) == 0
        assert sorted(os.listdir(out)) == ['ok.csv', 'ok.figspec.json',
                                           'ok.svg']
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


def test_the_figspec_records_the_format_and_the_dpi():
    """Without both, `--from-spec` re-renders something other than the
    file it names -- a 300 dpi PNG standing in for the 600 dpi SVG the
    spec was written beside. The round trip is checked on the BYTES, and
    then a flag is used to override the spec's format, which is the whole
    reason the two live in opts rather than beside them."""
    if not _has_mpl():
        return
    d, out, again = _mktmp(), _mktmp(), _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        assert sp.main([d, '--out', out, '--stem', 'rt', '--format', 'svg',
                        '--dpi', '600', '--prepost']) == 0
        spec = os.path.join(out, 'rt.figspec.json')
        recorded = _read_json(spec)['opts']
        assert recorded['fmt'] == 'svg' and recorded['dpi'] == 600, recorded
        # the re-render lands on an SVG again, byte for byte
        assert sp.main(['--from-spec', spec, '--out', again]) == 0
        assert os.path.exists(os.path.join(again, 'rt.svg'))
        with open(os.path.join(out, 'rt.svg'), 'rb') as a, \
                open(os.path.join(again, 'rt.svg'), 'rb') as b:
            assert a.read() == b.read(), 're-render is not the same file'
        # an explicit flag still beats the spec, and the dpi the spec
        # carried is what the PNG is then rendered at -- which is why the
        # window keeps the typed value under SVG instead of neutralising it
        third = _mktmp()
        try:
            assert sp.main(['--from-spec', spec, '--out', third,
                            '--format', 'png']) == 0
            png = os.path.join(third, 'rt.png')
            assert os.path.exists(png) and not os.path.exists(
                os.path.join(third, 'rt.svg'))
            w, _h = _png_size(png)
            assert abs(w - sp.FIGSIZE['area'][0] * 600) <= 1, w
        finally:
            shutil.rmtree(third, ignore_errors=True)
        # a spec written before `#314` has neither key: it must still
        # re-render, as the 300 dpi PNG it was
        old = os.path.join(out, 'old.figspec.json')
        blob = _read_json(spec)
        blob['opts'].pop('fmt')
        blob['opts'].pop('dpi')
        blob['stem'] = 'old'
        import json
        with open(old, 'w', encoding='utf-8') as f:
            json.dump(blob, f)
        assert sp.main(['--from-spec', old, '--out', again]) == 0
        assert os.path.exists(os.path.join(again, 'old.png'))
        assert abs(_png_size(os.path.join(again, 'old.png'))[0]
                   - sp.FIGSIZE['area'][0] * sp.DEFAULT_DPI) <= 1
    finally:
        for p in (d, out, again):
            shutil.rmtree(p, ignore_errors=True)


def test_the_written_file_is_described_with_its_size():
    """An SVG's size follows the number of drawn elements rather than the
    pixel count, so it is the one thing about an export that cannot be
    read off the settings -- hence naming it in the line that says the
    file was written. The dpi is named only where it means something."""
    if not _has_mpl():
        return
    d, out = _mktmp(), _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        for fmt in sp.FORMATS:
            opts = sp.make_opts(fmt=fmt, dpi=150)[0]
            img, _csv = sp.export(sp.prepare_runs([d], opts), opts, out, fmt)
            said = sp.describe_output(img, opts)
            assert fmt.upper() in said, said
            assert ('150 dpi' in said) is (fmt == 'png'), said
            assert 'kB' in said or 'MB' in said, said
        # never a reason to fail an export: a file that is not there yet
        # still gets a description
        assert 'PNG' in sp.describe_output(os.path.join(out, 'nope.png'),
                                           sp.make_opts()[0])
    finally:
        for p in (d, out):
            shutil.rmtree(p, ignore_errors=True)


def test_the_cli_option_table_cannot_drift_from_make_opts():
    """A figspec must never silently re-render a DIFFERENT figure.

    `build_figspec` stores `dict(opts)` wholesale, so a new option lands in
    the spec faithfully. But `_cli_opts` rebuilds the dict from a
    hand-written val()/on()/off() table and drops every key that table does
    not name -- returning err=None, so nothing anywhere reports it. The
    result is a `--from-spec` render that claims to reproduce a figure and
    does not: exactly the failure `load_figspec`'s validation exists to
    prevent, and cannot catch, because such a spec is well-formed.

    Measured 2026-08-09 with a fake `sem_band` key -- present in the spec,
    absent after the round trip, err None -- while `logy` round-tripped
    fine. This is the guard so the next option through the seam (`#268`)
    cannot repeat it.
    """
    base, err = sp.make_opts()
    assert err is None, err
    out, err = sp._cli_opts([], {}, dict(base))
    assert err is None, err
    dropped = sorted(set(base) - set(out))
    assert not dropped, (
        f"_cli_opts drops {dropped}: add them to its val()/on()/off() table, "
        "or --from-spec will silently render a different figure")
    invented = sorted(set(out) - set(base))
    assert not invented, \
        f"_cli_opts invents keys make_opts never made: {invented}"


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    failed = []
    for n in names:
        try:
            globals()[n]()
        except Exception:
            failed.append((n, traceback.format_exc()))
            print('FAIL', n)
            continue
        print('ok ', n)
    if not failed:
        print(f"{len(names)} tests passed")
        return 0
    head = f"{len(failed)} of {len(names)} tests failed"
    print(f"\n{head}")
    for name, tb in failed:
        print(f"===== FAIL {name} =====")
        print(tb.rstrip('\n'))
    print(f"===== end {head} =====")
    return 1


if __name__ == '__main__':
    raise SystemExit(_run())
