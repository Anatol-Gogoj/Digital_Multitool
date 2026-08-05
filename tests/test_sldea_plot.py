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


def _run():
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    for n in names:
        globals()[n]()
        print('ok ', n)
    print(f"{len(names)} tests passed")


if __name__ == '__main__':
    _run()
