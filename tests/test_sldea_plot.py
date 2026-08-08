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


def _drawn(runs, opts):
    """-> the Figure sp.draw() produced, WITHOUT pyplot (the same path
    save_figure uses), so a test can interrogate the real axes."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    fig = Figure(figsize=sp.FIGSIZE[opts['mode']])
    FigureCanvasAgg(fig)
    sp.draw(fig, runs, opts)
    return fig


def _caption(fig):
    """The figure-level caption text every figure carries."""
    return '\n'.join(t.get_text() for t in fig.texts)


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
                 'title_second': None, 'subplots': 'both'}
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
    same bytes as the command line, or 'the same figure' is a story."""
    if not _has_mpl():
        return
    d, out = _mktmp(), _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        for mode in sp.MODES:
            opts = sp.make_opts(mode=mode)[0]
            runs = sp.prepare_runs([d], opts)
            cli = os.path.join(out, mode + '_cli.png')
            if mode == 'area':
                sp.figure_area(runs, opts, cli)
            else:
                sp.figure_signal(runs, opts, cli)
            gui = sp.save_figure(runs, opts, os.path.join(out, mode + '_g.png'))
            with open(cli, 'rb') as a, open(gui, 'rb') as b:
                assert a.read() == b.read(), mode
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
            with open(new_csv, 'rb') as a, open(old_csv, 'rb') as b:
                assert a.read() == b.read(), f"{mode} CSV moved"
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


def _run():
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    for n in names:
        globals()[n]()
        print('ok ', n)
    print(f"{len(names)} tests passed")


if __name__ == '__main__':
    _run()
