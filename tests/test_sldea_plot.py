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


def _fake_run(d, rows, cols=COLS_15, estimator='current'):
    """A run folder with these CSV rows. `estimator`: which area
    estimator its setup.txt says wrote the 'disc-fit' areas -- 'current'
    stamps se.AREA_ESTIMATOR_VERSION (what every Save writes since
    2026-10-02, so the fixtures stand for reviewed runs), an int stamps
    that version, None writes no stamp (a run last saved by the ellipse
    estimator, which prepare_runs refuses in area mode)."""
    import sldea_edge as se
    os.makedirs(os.path.join(d, 'frames'), exist_ok=True)
    with open(os.path.join(d, 'data.csv'), 'w', newline='',
              encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({**{c: '' for c in cols}, **r})
    if estimator is not None:
        ver = (se.AREA_ESTIMATOR_VERSION if estimator == 'current'
               else int(estimator))
        se.save_settings(d, None, stamp=se.estimator_stamp(None, ver))


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
    """The figure-level caption text every figure carries, AS COMPOSED:
    every line whole, before it is wrapped to the figure's width
    (2026-10-06). A phrase a test looks for cannot then be split by where
    a row happens to break; that the drawn rows are these lines and keep
    every word is test_the_caption_is_wrapped_inside_the_frame's job, and
    _caption_rows is what is drawn."""
    held = getattr(fig, sp._CAPTION_ATTR, None)
    return '\n'.join(held[1] if held is not None and t is held[0]
                     else t.get_text() for t in fig.texts)


def _caption_rows(fig):
    """The caption's rows as DRAWN, after the wrap -> [rows]."""
    return getattr(fig, sp._CAPTION_ATTR)[0].get_text().split('\n')


def _words(text):
    """`text`'s words in order: what a wrap must keep, wherever it breaks
    the rows and however much space it leaves at a break."""
    return text.split()


def _caption_right_edges(fig, rows=None):
    """-> [right edge of each drawn caption row, as a fraction of the
    figure width], measured in pixels at the figure's own dpi: what a
    reader meets, where a character count is only a proxy."""
    text = getattr(fig, sp._CAPTION_ATTR)[0]
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    out = []
    for row in (rows if rows is not None else _caption_rows(fig)):
        probe = fig.text(text.get_position()[0], 0.5, row,
                         fontproperties=text.get_fontproperties())
        out.append(probe.get_window_extent(rend).x1 / fig.bbox.width)
        probe.remove()
    return out


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


def test_a_row_emptied_by_the_estimator_change_never_reaches_an_axis():
    """2026-10-02 (R5): a `disc-fit` area saved by the old ellipse
    estimator is a few percent off the common-ray areas a later Save
    writes. Edge Review empties such a row and replaces its note, so
    here it must read as no area and no method, and the level it sat
    on is drawn from the measured rows only."""
    import sldea_edge as se
    d = _mktmp()
    try:
        _fake_run(d, [
            {'snapshot': 1, 'tag': 'baseline', 'nominal_kV': 0,
             'active_area_px': 217438, 'active_area_mm2': 201.062,
             'notes': 'edge:resting conf 0.95'},
            {'snapshot': 2, 'tag': 'post-ramp', 'nominal_kV': 2.0,
             'active_area_px': 221000, 'active_area_mm2': 204.356,
             'notes': 'edge:disc-fit conf 0.97'},
            {'snapshot': 3, 'tag': 'pre-ramp', 'nominal_kV': 2.0,
             'notes': se.AREA_ESTIMATOR_STALE_NOTE},
            {'snapshot': 4, 'tag': 'post-ramp', 'nominal_kV': 3.0,
             'notes': se.AREA_ESTIMATOR_STALE_NOTE + '; wrinkle-mode'},
        ])
        rows = sp.load_rows(d)
        assert rows[2]['area_px'] is None and rows[2]['area_mm2'] is None
        assert rows[2]['method'] == '' and rows[2]['conf'] is None
        assert rows[3]['method'] == '' and rows[3]['area_mm2'] is None
        run = sp.load_run(d, warn=lambda m: None)
        lv = sp.levels(run)
        assert [l['kv'] for l in lv] == [0.0, 2.0], lv
        assert lv[1]['mean'] == 204.356 and lv[1]['pre'] is None
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


def test_old_estimator_areas_are_refused_across_runs_like_the_scale_era():
    """2026-10-02 (R5, across runs): a run whose 'disc-fit' areas were
    saved by the old area method (the ellipse; no `area_estimator: 2`
    stamp in setup.txt) reads -0.4 to +7.4 % off the common-ray areas
    of a reprocessed run. Edge Review keeps the two apart within a run;
    sldea_plot must keep them apart ACROSS runs the way it keeps the
    2026-07-28 scale era out: refused from area axes with a message that
    says to re-review, kept only on an explicit --allow-old-estimator
    and then NAMED in the caption and in the tidy CSV's area_estimator
    column, and in current mode kept with its area columns blanked.
    Runs holding only rows that mean the same under both estimators
    (resting, hand traces, emptied old rows) pass without a stamp."""
    import sldea_edge as se
    if not _has_mpl():
        return
    d_old, d_new, d_same, d_v1, out = (_mktmp(), _mktmp(), _mktmp(),
                                       _mktmp(), _mktmp())
    try:
        _fake_run(d_old, _healthy_rows(6), estimator=None)
        _fake_run(d_new, _healthy_rows(6))              # stamped current
        # no stamp, but nothing the estimator change touched: the
        # baseline, hand traces, and an old row a Save already emptied
        rows = [r for r in _healthy_rows(6)
                if 'disc-fit' not in r['notes']]
        rows.append({'snapshot': 99, 'tag': 'post-ramp', 'nominal_kV': 1.0,
                     'timestamp': '2026-08-05T10:00:00',
                     'notes': se.AREA_ESTIMATOR_STALE_NOTE})
        _fake_run(d_same, rows, estimator=None)
        old = sp.load_run(d_old, lambda m: None)
        assert old['estimator'] is None and sp.old_estimator_areas(old)
        new = sp.load_run(d_new, lambda m: None)
        assert new['estimator'] == se.AREA_ESTIMATOR_VERSION
        assert not sp.old_estimator_areas(new)
        assert not sp.old_estimator_areas(sp.load_run(d_same,
                                                      lambda m: None))
        # a stamp OLDER than the current version is old too
        _fake_run(d_v1, _healthy_rows(4), estimator=1)
        assert sp.old_estimator_areas(sp.load_run(d_v1, lambda m: None))

        # area mode: the old run is refused, and the message says why and
        # what to do; the stamped and the same-under-both runs draw
        warns = []
        opts, _ = sp.make_opts(mode='area')
        runs = sp.prepare_runs([d_old, d_new, d_same], opts, warns.append)
        assert [r['dir'] for r in runs] == [d_new, d_same], \
            [r['name'] for r in runs]
        said = [w for w in warns if 'OLD area method' in w]
        assert len(said) == 1 and 'EXCLUDED' in said[0], warns
        assert 'Re-review' in said[0] and '--allow-old-estimator' in said[0]
        assert sp.main([d_old, '--out', out]) == 2                # alone
        # the override: drawn, SAID in the caption, marked in the CSV
        assert sp.main([d_old, d_new, '--out', out, '--stem', 'mix',
                        '--allow-old-estimator']) == 0
        runs = sp.prepare_runs([d_old, d_new], opts, warns.append,
                               allow_old_estimator=True)
        assert [r['old_estimator_kept'] for r in runs] == [True, False]
        cap = _caption(_drawn(runs, opts))
        assert 'OLD area method' in cap, cap
        assert os.path.basename(d_old) in cap, cap
        assert os.path.basename(d_new) not in cap.split('OLD area')[1], cap
        assert '--allow-old-estimator' in cap, cap
        with open(os.path.join(out, 'mix.csv'), encoding='utf-8') as f:
            tidy = list(csv.DictReader(f))
        by_run = {}
        for t in tidy:
            by_run.setdefault(t['run'], []).append(t)
        for name, want in ((os.path.basename(d_old), '1'),
                           (os.path.basename(d_new),
                            str(se.AREA_ESTIMATOR_VERSION))):
            disc = [t for t in by_run[name] if t['method'] == 'disc-fit']
            assert disc and all(t['area_estimator'] == want for t in disc), \
                (name, [t['area_estimator'] for t in disc])
            other = [t for t in by_run[name] if t['method'] != 'disc-fit']
            assert other and all(t['area_estimator'] == '' for t in other)
        # a figure with no old run carries no such caption line and no
        # mark: the ordinary figure is byte-for-byte what it was
        cap = _caption(_drawn(sp.prepare_runs([d_new], opts), opts))
        assert 'OLD area method' not in cap
        # current mode: the old run is kept (currents are unaffected)
        # with its area columns blanked, as the scale era is
        assert sp.main([d_old, '--out', out, '--mode', 'current',
                        '--stem', 'cur']) == 0
        with open(os.path.join(out, 'cur.csv'), encoding='utf-8') as f:
            tidy = list(csv.DictReader(f))
        assert tidy and all(t['area_mm2'] == '' and t['area_estimator'] == ''
                            for t in tidy), 'old-estimator areas leaked'
        # ...but --vs-area puts areas on an axis, so it is refused there
        assert sp.main([d_old, '--out', out, '--mode', 'current',
                        '--vs-area', '--stem', 'va']) == 2
    finally:
        for p in (d_old, d_new, d_same, d_v1, out):
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


def test_tidy_carries_the_library_versions_the_save_recorded():
    """Owner decision 29 (2026-10-03): the tidy CSV says which OpenCV
    and numpy wrote each machine area, from the stamp Edge Review's
    Save put in setup.txt beside `area_estimator`. Two columns after
    that one (not a header line, so the file stays a plain CSV): filled
    on every machine-measured row ('half-height'), blank on a hand
    trace, on a row without an area, and throughout a run saved before
    the versions were recorded; blanked with the areas when an old run
    is kept in current mode."""
    import sldea_edge as se
    d = _mktmp()
    d_old = _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))          # stamped by this process
        # a run stamped before the versions existed: the estimator alone
        _fake_run(d_old, _healthy_rows(4), estimator=None)
        se.save_settings(d_old, None,
                         stamp=se.estimator_stamp(None, libs={}))
        libs = se.library_versions()
        assert se.load_stamp(d)['opencv_version'] == libs['opencv_version']
        assert 'opencv_version' not in se.load_stamp(d_old)
        run = sp.load_run(d, lambda m: None)
        old = sp.load_run(d_old, lambda m: None)
        assert run['lib_versions'] == libs
        assert old['lib_versions'] == {'opencv_version': '',
                                       'numpy_version': ''}
        out = _mktmp()
        try:
            path = sp.write_tidy([dict(run, color='#4477AA'),
                                  dict(old, color='#EE6677')],
                                 os.path.join(out, 't.csv'))
            with open(path, newline='', encoding='utf-8') as f:
                rd = csv.DictReader(f)
                cols = rd.fieldnames
                tidy = list(rd)
            assert cols == sp.TIDY_COLS
            i = cols.index('area_estimator')
            assert cols[i + 1:i + 3] == ['opencv_version', 'numpy_version']
            mine = [t for t in tidy if t['run'] == run['name']]
            theirs = [t for t in tidy if t['run'] == old['name']]
            assert mine and theirs
            for t in mine:
                want = libs if t['convention'] == 'half-height' else None
                assert t['opencv_version'] == (want or {}).get(
                    'opencv_version', ''), t
                assert t['numpy_version'] == (want or {}).get(
                    'numpy_version', ''), t
            assert any(t['convention'] == 'half-height' for t in mine)
            assert any(t['convention'] == 'outer-toe' for t in mine)
            assert all(t['opencv_version'] == '' and t['numpy_version'] == ''
                       for t in theirs)
            # the resting baseline row is a machine row too
            base = next(t for t in mine if t['phase'] == 'baseline')
            assert base['method'] == 'resting'
            assert base['opencv_version'] == libs['opencv_version']
            # current mode keeps an old-estimator run with its areas
            # blanked, and the version columns go with them
            d_v1 = _mktmp()
            try:
                _fake_run(d_v1, _healthy_rows(4), estimator=1)
                assert sp.main([d_v1, '--out', out, '--mode', 'current',
                                '--stem', 'cur']) == 0
                with open(os.path.join(out, 'cur.csv'),
                          encoding='utf-8') as f:
                    cur = list(csv.DictReader(f))
                assert cur and all(t['area_mm2'] == ''
                                   and t['opencv_version'] == ''
                                   and t['numpy_version'] == ''
                                   for t in cur), cur[0]
            finally:
                shutil.rmtree(d_v1, ignore_errors=True)
        finally:
            shutil.rmtree(out, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(d_old, ignore_errors=True)


def test_tidy_carries_the_tracker_limits_the_save_recorded():
    """Owner decision 6 (2026-10-03): the tidy CSV says which tracker
    window each 'disc-fit' area was measured under, from the two limit
    stamps Edge Review's Save puts in setup.txt beside the versions
    (ray_win_hi, the ink-step search top; disc_fit_r_max, the ellipse
    gate; units of the resting radius). They are constants that moved
    once under the same `area_estimator` (1.38 -> 1.70, 1.3 -> 1.75),
    so two rows with the same estimator can differ by the window, and
    the columns tell them apart. Filled exactly where area_estimator
    is (a 'disc-fit' row with an area), blank on a hand trace, on a
    'resting' row, and throughout a run saved before the limits were
    recorded; blanked with the areas when an old run is kept in
    current mode."""
    import sldea_edge as se
    d = _mktmp()
    d_old = _mktmp()
    d_win = _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))          # stamped by this code
        # a run stamped before the limits existed
        _fake_run(d_old, _healthy_rows(4), estimator=None)
        se.save_settings(d_old, None,
                         stamp=se.estimator_stamp(None, limits={}))
        # a run measured under the 2026-10-02 window
        _fake_run(d_win, _healthy_rows(4), estimator=None)
        se.save_settings(d_win, None, stamp=se.estimator_stamp(
            None, limits={'ray_win_hi': 1.38, 'disc_fit_r_max': 1.3}))
        lims = se.tracker_limits()
        assert se.load_stamp(d)['ray_win_hi'] == lims['ray_win_hi']
        assert 'ray_win_hi' not in se.load_stamp(d_old)
        assert se.load_stamp(d_win)['disc_fit_r_max'] == 1.3
        run = sp.load_run(d, lambda m: None)
        old = sp.load_run(d_old, lambda m: None)
        win = sp.load_run(d_win, lambda m: None)
        assert run['tracker_limits'] == lims
        assert old['tracker_limits'] == {'ray_win_hi': None,
                                         'disc_fit_r_max': None}
        assert win['tracker_limits'] == {'ray_win_hi': 1.38,
                                         'disc_fit_r_max': 1.3}
        assert run['estimator'] == old['estimator'] == win['estimator'] \
            == se.AREA_ESTIMATOR_VERSION
        out = _mktmp()
        try:
            path = sp.write_tidy([dict(run, color='#4477AA'),
                                  dict(old, color='#EE6677'),
                                  dict(win, color='#228833')],
                                 os.path.join(out, 't.csv'))
            with open(path, newline='', encoding='utf-8') as f:
                rd = csv.DictReader(f)
                cols = rd.fieldnames
                tidy = list(rd)
            assert cols == sp.TIDY_COLS
            i = cols.index('area_estimator')
            assert cols[i + 1:i + 5] == ['opencv_version', 'numpy_version',
                                         'ray_win_hi', 'disc_fit_r_max']
            mine = [t for t in tidy if t['run'] == run['name']]
            theirs = [t for t in tidy if t['run'] == old['name']]
            older = [t for t in tidy if t['run'] == win['name']]
            assert mine and theirs and older
            for t in mine:
                if t['area_estimator'] != '':
                    assert t['method'] == 'disc-fit', t
                    assert t['ray_win_hi'] == f"{lims['ray_win_hi']:g}", t
                    assert t['disc_fit_r_max'] \
                        == f"{lims['disc_fit_r_max']:g}", t
                else:
                    assert t['ray_win_hi'] == '' and t['disc_fit_r_max'] == '', t
            assert any(t['area_estimator'] != '' for t in mine)
            assert any(t['convention'] == 'outer-toe' for t in mine)
            # the resting baseline row carries the versions but no
            # window: A0 is not a tracker reading
            base = next(t for t in mine if t['phase'] == 'baseline')
            assert base['method'] == 'resting'
            assert base['opencv_version'] != '' and base['ray_win_hi'] == ''
            assert all(t['ray_win_hi'] == '' and t['disc_fit_r_max'] == ''
                       for t in theirs)
            for t in older:
                want = ('1.38', '1.3') if t['area_estimator'] != '' \
                    else ('', '')
                assert (t['ray_win_hi'], t['disc_fit_r_max']) == want, t
            # current mode keeps an old-estimator run with its areas
            # blanked, and the window columns go with them
            d_v1 = _mktmp()
            try:
                _fake_run(d_v1, _healthy_rows(4), estimator=1)
                assert se.load_stamp(d_v1)['ray_win_hi'] == lims['ray_win_hi']
                assert sp.main([d_v1, '--out', out, '--mode', 'current',
                                '--stem', 'cur']) == 0
                with open(os.path.join(out, 'cur.csv'),
                          encoding='utf-8') as f:
                    cur = list(csv.DictReader(f))
                assert cur and all(t['area_mm2'] == ''
                                   and t['ray_win_hi'] == ''
                                   and t['disc_fit_r_max'] == ''
                                   for t in cur), cur[0]
            finally:
                shutil.rmtree(d_v1, ignore_errors=True)
        finally:
            shutil.rmtree(out, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(d_old, ignore_errors=True)
        shutil.rmtree(d_win, ignore_errors=True)


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
                 # the normalized panel's UNITS. Defaults to the ratio,
                 # so an options dict built with no arguments still
                 # describes the figure that existed before the option
                 'strain_pct': False,
                 # 2026-09-23: kV stays the x axis, and the leg split and
                 # its arrows default ON -- they only ever act on a run
                 # whose voltage also fell, so a single sweep is
                 # untouched (the byte-identity test below proves it
                 # against the pre-change engine)
                 'x': 'kv', 'split_legs': True, 'arrows': True,
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
        # the estimator-era flags (2026-10-02) are reset the same way: an
        # old-estimator run is hidden in current mode, kept on the
        # override, and neither decision survives into the next render
        d2 = _mktmp()
        try:
            _fake_run(d2, _healthy_rows(6), estimator=None)
            cur = sp.make_opts(mode='current')[0]
            runs = sp.prepare_runs([d2], cur, load=load)
            assert runs[0]['old_estimator_hidden'] is True
            assert runs[0]['old_estimator_kept'] is False
            runs = sp.prepare_runs([d2], cur, load=load,
                                   allow_old_estimator=True)
            assert runs[0]['old_estimator_hidden'] is False
            assert runs[0]['old_estimator_kept'] is True
            assert runs[0] is cache[d2]
            runs = sp.prepare_runs([d2], cur, load=load)
            assert runs[0]['old_estimator_kept'] is False
        finally:
            shutil.rmtree(d2, ignore_errors=True)
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


def _pre_change_module(sha=None):
    """sldea_plot as of `sha` (default _BASE_SHA), as an importable module,
    or None.

    None when the object is not reachable (no git, a shallow clone, an
    exported tarball) -- the caller then SKIPS and says so, because a
    compatibility test that quietly passes when it cannot compare is
    worse than no test."""
    import importlib.util
    import subprocess
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    try:
        got = subprocess.run(['git', 'show',
                              (sha or _BASE_SHA) + ':sldea_plot.py'],
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


def _old_figure_rewrapped(old, dirs, old_opts, new_opts, path):
    """The OLD engine's figure with ONLY the 2026-10-06 change applied to
    it -> the PNG path, written as the new engine writes.

    That change wraps a caption line too wide for the figure and grows the
    strip to hold it, which moves every axis of the default area figure.
    So the byte claim on that figure is restated rather than dropped: take
    the old engine's figure, put the new engine's wrapped rows in its
    caption, lay it out above the new engine's strip (from the default
    subplot params, as relayout does), and every byte must match. The old
    caption must be the new one's composed text exactly, so the words did
    not change, only where the rows break."""
    from matplotlib import rcParams
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    new = _drawn(sp.prepare_runs(dirs, new_opts), new_opts)
    text, composed, _strip = getattr(new, sp._CAPTION_ATTR)
    assert text.get_text() != composed, 'nothing wrapped; this one did not move'
    fig = Figure(figsize=old.FIGSIZE[old_opts['mode']])
    FigureCanvasAgg(fig)
    old.draw(fig, old.prepare_runs(dirs, old_opts), old_opts)
    caps = [t for t in fig.texts if t.get_text() == composed]
    assert len(caps) == 1, "the caption's words changed, not only its rows"
    caps[0].set_text(text.get_text())
    fig.subplots_adjust(**{k: rcParams['figure.subplot.' + k]
                           for k in sp._SUBPLOTPARS})
    fig.tight_layout(rect=getattr(new, sp._RECT_ATTR))
    return sp._savefig(fig, path, new_opts)


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
            if mode == 'area':
                # THE DELIBERATE MOVE of 2026-10-06: the default area
                # figure's first caption line (280 characters) ran off the
                # right edge and is wrapped now, so this figure is the old
                # one with its caption re-wrapped and its strip re-laid,
                # and nothing else (_old_figure_rewrapped). Current and
                # power captions fit, and stay byte-identical outright.
                old_png = _old_figure_rewrapped(
                    old, [d], old_opts, new_opts,
                    os.path.join(out, mode + '_old.png'))
            else:
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
            # ...and 2026-09-23 added three DATA columns the same way:
            # 'elapsed_s' (the time axis's x) and 'leg'/'cycle' (the
            # grouping an up/down run is drawn by). Dropped BY NAME below,
            # so the claim stays exactly as sharp: every other byte, in
            # every row, identical. On this single sweep they must also say
            # the obvious -- one rising leg, one cycle, the 0 kV rows in it.
            # ...and the provenance stamps of 2026-10-02/03 (the area
            # estimator, the OpenCV/numpy versions and the tracker's window
            # limits) were added to TIDY_COLS without being listed here, so
            # this case failed on main at the CSV step on every clone while
            # the PNGs stayed byte-identical (found 2026-10-05 during the
            # leg-branch rebase). They are stamps, not data the base engine
            # could have written, so they are dropped by name too.
            added = ('group', 'elapsed_s', 'leg', 'cycle',
                     'area_estimator', 'opencv_version', 'numpy_version',
                     'ray_win_hi', 'disc_fit_r_max')
            assert sp.TIDY_COLS[1] == 'group', sp.TIDY_COLS
            for col in added:
                assert col in sp.TIDY_COLS, col
                assert col not in old.TIDY_COLS, f"base already had {col}"
            keep = [i for i, c in enumerate(sp.TIDY_COLS) if c not in added]
            with open(new_csv, newline='', encoding='utf-8') as a, \
                    open(old_csv, newline='', encoding='utf-8') as b:
                new_rows = list(csv.reader(a))
                old_rows = list(csv.reader(b))
            assert {r[1] for r in new_rows[1:]} <= {''}, \
                'an ungrouped export wrote a group'
            legs = {r[sp.TIDY_COLS.index('leg')] for r in new_rows[1:]}
            cycles = {r[sp.TIDY_COLS.index('cycle')] for r in new_rows[1:]}
            assert legs == {'rise'} and cycles == {'1'}, (legs, cycles)
            assert [[r[i] for i in keep] for r in new_rows] == old_rows, \
                f"{mode} CSV moved beyond the new columns"
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


def test_strain_percent_is_the_same_measurement_as_the_ratio():
    """`--strain-pct` renders the normalized panel as (A-A0)/A0*100.

    The identity is what makes this a UNITS switch and not a second
    analysis: strain is exactly (A/A0 - 1) * 100, so any figure drawn one
    way can be read the other. Pinned on an expansion, no change, and a
    contraction -- the last because a shrinking device gives a NEGATIVE
    strain where the ratio stays positive, and a reader who only ever saw
    expansion would not notice a sign convention quietly chosen for them.
    """
    for a, a0 in ((281.5, 201.1), (201.1, 201.1), (150.0, 201.1)):
        ratio = sp.norm_y(a, a0)
        pct = sp.norm_y(a, a0, pct=True)
        assert abs((ratio - 1.0) * 100.0 - pct) < 1e-9, (a, a0)
    assert abs(sp.norm_y(201.1, 201.1, pct=True)) < 1e-12, 'A0 must be 0 %'
    assert sp.norm_y(150.0, 201.1, pct=True) < 0, 'a contraction is negative'
    # the SCORECARD's headline: A/A0 1.40 is quoted as 40 % strain
    assert abs(sp.norm_y(281.54, 201.1, pct=True) - 40.0) < 0.1


def test_the_strain_aggregate_is_the_ratio_aggregate_rescaled():
    """The affine claim in norm_y's docstring, checked rather than argued.

    (r-1)*100 commutes with the mean and multiplies the SEM by 100, so the
    percent aggregate must be the ratio aggregate rescaled EXACTLY -- no
    statistics were rethought for the units switch. If someone later moves
    the conversion to after the aggregation, or applies it to the mean but
    not the band, this is what fails."""
    d = _mktmp()
    try:
        runs = [_agg_run(d, f"R{i}", [1.0], lambda kv, a=a: a)
                for i, a in enumerate((100.0, 110.0, 120.0, 130.0))]
        r = next(l for l in sp.aggregate_levels(runs, norm=True)
                 if l['kv'] == 1.0)
        p = next(l for l in sp.aggregate_levels(runs, norm=True, pct=True)
                 if l['kv'] == 1.0)
        assert p['n'] == r['n'] == 4
        assert abs(p['mean'] - (r['mean'] - 1.0) * 100.0) < 1e-9, (r, p)
        assert abs(p['sem'] - r['sem'] * 100.0) < 1e-9, (r, p)
        assert abs(p['sd'] - r['sd'] * 100.0) < 1e-9, (r, p)
        # ...and against the hand numbers from the test above: mean 1.15
        # becomes 15 % with a SEM of 6.4549...
        assert abs(p['mean'] - 15.0) < 1e-9, p
        assert abs(p['sem'] - 6.454972243679028) < 1e-9, p
        # the absolute panel is untouched -- percent describes the
        # NORMALIZED panel only, and an mm2 axis relabelled as a
        # percentage would be a lie about the same numbers
        abs_ratio = next(l for l in sp.aggregate_levels(runs)
                         if l['kv'] == 1.0)
        abs_pct = next(l for l in sp.aggregate_levels(runs, pct=True)
                       if l['kv'] == 1.0)
        assert abs_pct == abs_ratio, 'percent leaked into the mm² panel'
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------
# the budget band under --strain-pct (2026-10-02 plot review)
#
# The band is +-p of the AREA. In strain mode it was drawn as +-p of the
# STRAIN VALUE: zero width at rest, 2.6 to 10.5 times too narrow on the
# campaign runs. These tests read the band back off the axes, the way a
# reader sees it, rather than trusting the function that drew it.
# --------------------------------------------------------------------------

def _band_polys(ax):
    """The budget bands drawn on `ax`: one {x: (lo, hi)} per band.

    Read from the PolyCollection vertices, so the numbers are what the
    figure shows. fill_between writes a lo and a hi vertex at every x, so
    the min and max of the y values at each x are the band's two edges."""
    from matplotlib.collections import PolyCollection
    out = []
    for coll in ax.collections:
        if not isinstance(coll, PolyCollection):
            continue
        for path in coll.get_paths():
            by_x = {}
            for x, y in path.vertices:
                by_x.setdefault(round(float(x), 6), []).append(float(y))
            out.append({x: (min(v), max(v)) for x, v in by_x.items()})
    return out


def _band_fixture(d, **kw):
    """-> (run, Figure) for the standard synthetic run, drawn with `kw`.

    The fixture has a 0 kV baseline level (A/A0 exactly 1), machine
    levels, and hand-traced levels from 3.0 kV up, so one run covers the
    rest level, the 2 % band and the 1 % band."""
    _fake_run(d, _healthy_rows(8))
    opts = sp.make_opts(**kw)[0]
    runs = sp.prepare_runs([d], opts)
    return runs[0], _drawn(runs, opts)


def test_band_edges_map_the_area_band_into_the_displayed_unit():
    """Hand-checked. A/A0 = 1.4 is 40 % strain; +-2 % of the AREA there is
    A/A0 1.372 to 1.428, which is strain 37.2 to 42.8: +-2.8 points, not
    the +-0.8 points that +-2 % of the number 40 gives."""
    lo, hi = sp._band_edges(40.0, 2.0, pct=True)
    assert abs(lo - 37.2) < 1e-9 and abs(hi - 42.8) < 1e-9, (lo, hi)
    # at rest the band is +-2 points; the old rule gave zero
    lo, hi = sp._band_edges(0.0, 2.0, pct=True)
    assert abs(lo + 2.0) < 1e-9 and abs(hi - 2.0) < 1e-9, (lo, hi)
    # the traced level is +-1 %
    lo, hi = sp._band_edges(0.0, 1.0, pct=True)
    assert abs(lo + 1.0) < 1e-9 and abs(hi - 1.0) < 1e-9, (lo, hi)
    # a contraction (A/A0 0.8 is -20 % strain): the band is +-1.6 points
    # and lo stays below hi. Scaling the strain value by (1 -/+ p) put lo
    # ABOVE hi here, and only fill_between's tolerance hid it.
    lo, hi = sp._band_edges(-20.0, 2.0, pct=True)
    assert lo < hi, (lo, hi)
    assert abs(lo + 21.6) < 1e-9 and abs(hi + 18.4) < 1e-9, (lo, hi)
    # half-width = p * 100 * A/A0 at every ratio, whatever the sign
    for r in (0.5, 0.8, 1.0, 1.4, 2.3):
        lo, hi = sp._band_edges((r - 1.0) * 100.0, 2.0, pct=True)
        assert abs((hi - lo) / 2.0 - 2.0 * r) < 1e-9, (r, lo, hi)
    # the mm2 and A/A0 panels keep the plain scaling: +-p of the number
    lo, hi = sp._band_edges(250.0, 2.0)
    assert abs(lo - 245.0) < 1e-9 and abs(hi - 255.0) < 1e-9, (lo, hi)
    lo, hi = sp._band_edges(1.4, 1.0)
    assert abs(lo - 1.386) < 1e-9 and abs(hi - 1.414) < 1e-9, (lo, hi)


def test_the_strain_band_is_the_ratio_band_in_strain_points():
    """Reads the drawn band in both units and compares them.

    Ratio mode: half-width p * A/A0. Strain mode: p * 100 * A/A0 points,
    which is p * 100 at 0 kV where the old rule drew nothing. Both are the
    SAME band: every strain edge is (ratio edge - 1) * 100. The mm2 panel
    is not touched by the units switch."""
    if not _has_mpl():
        return
    d, d2 = _mktmp(), _mktmp()
    try:
        run, rfig = _band_fixture(d)
        _run2, sfig = _band_fixture(d2, strain_pct=True)
        lvs = sp.levels(run)
        assert any(l['all_traced'] for l in lvs), 'fixture has no traced level'
        assert any(not l['all_traced'] for l in lvs), 'no machine level'
        rband = _band_polys(rfig.axes[1])
        sband = _band_polys(sfig.axes[1])
        assert len(rband) == len(sband) == 1, (len(rband), len(sband))
        rband, sband = rband[0], sband[0]
        assert len(rband) == len(sband) == len(lvs)
        saw_rest = False
        for lv in lvs:
            x = round(float(lv['kv']), 6)
            p = (sp.TRACED_BAND_PCT if lv['all_traced']
                 else sp.MACHINE_BAND_PCT) / 100.0
            r = lv['mean'] / run['a0']
            rlo, rhi = rband[x]
            slo, shi = sband[x]
            assert abs((rhi - rlo) / 2.0 - p * r) < 1e-9, (x, rlo, rhi)
            assert abs((shi - slo) / 2.0 - 100.0 * p * r) < 1e-9, \
                (x, slo, shi)
            # centred on the plotted strain, so the band belongs to the line
            assert abs((shi + slo) / 2.0
                       - sp.norm_y(lv['mean'], run['a0'], True)) < 1e-9, x
            # the same band in two units
            assert abs(slo - (rlo - 1.0) * 100.0) < 1e-9, (x, slo, rlo)
            assert abs(shi - (rhi - 1.0) * 100.0) < 1e-9, (x, shi, rhi)
            if lv['kv'] == 0:
                saw_rest = True
                # the 0 kV level: p * 100 points, NOT zero
                assert abs((shi - slo) / 2.0
                           - 100.0 * sp.MACHINE_BAND_PCT / 100.0) < 1e-9
                assert shi - slo > 3.9, 'zero-width band at rest'
        assert saw_rest, 'fixture has no 0 kV level'
        # percent describes the normalized panel only: the mm2 band is the
        # same drawing in both figures
        assert _band_polys(rfig.axes[0]) == _band_polys(sfig.axes[0])
    finally:
        for p in (d, d2):
            shutil.rmtree(p, ignore_errors=True)


def test_the_strain_band_holds_under_prepost_and_never_inverts():
    """Under --prepost each line carries its own band (an old behaviour, see
    the open question in SLDEA_HANDOFF.md); whichever of them are drawn,
    each must be p * A/A0 points wide in strain mode. The test does not
    say whether prepost SHOULD draw bands; that is the owner's call."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        _run, fig = _band_fixture(d, strain_pct=True, prepost=True,
                                  mean=True)
        for poly in _band_polys(fig.axes[1]):
            for x, (lo, hi) in poly.items():
                assert lo < hi, (x, lo, hi)
                mid = (lo + hi) / 2.0
                # half-width / (100 + strain) is p, whatever the strain
                p = (hi - lo) / 2.0 / (100.0 + mid)
                assert min(abs(p - 0.02), abs(p - 0.01)) < 1e-9, (x, p)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_strain_caption_states_the_band_that_is_drawn():
    """The caption's strain-points sentence is read back and compared with
    the polygon: its numbers are the drawn half-widths at 0 % strain."""
    if not _has_mpl():
        return
    import re
    d, d2, d3, d4, d5 = (_mktmp() for _ in range(5))
    try:
        run, sfig = _band_fixture(d, strain_pct=True)
        cap = _caption(sfig)
        m = re.search(r"±([\d.]+) / ±([\d.]+) points at 0 % "
                      r"strain, wider as strain grows", cap)
        assert m, cap
        machine_pts, traced_pts = float(m.group(1)), float(m.group(2))
        assert machine_pts == sp.MACHINE_BAND_PCT
        assert traced_pts == sp.TRACED_BAND_PCT
        assert 'of the AREA' in cap, cap
        band = _band_polys(sfig.axes[1])[0]
        for lv in sp.levels(run):
            x = round(float(lv['kv']), 6)
            half = (band[x][1] - band[x][0]) / 2.0
            r = lv['mean'] / run['a0']
            stated = traced_pts if lv['all_traced'] else machine_pts
            # the sentence says "at 0 % strain"; the band then grows as
            # A/A0, so the drawn half-width is the stated points times r
            assert abs(half - stated * r) < 1e-9, (x, half, stated, r)
        # the sentence has to be ON the figure, not cut off at its edge.
        # It rides on the caption's second line, which this test once held
        # to 0.99 of the frame in one piece -- and which ended at 0.991 at
        # this figure's 100 dpi and 1.002 at 96, so the test failed on
        # main (measured 2026-10-06). Every line is wrapped to the
        # figure's width since then, so the claim is now that every drawn
        # row ends inside the frame with a little room, and that the rows
        # still carry every word of the sentence.
        assert m.group(0) in cap.split('\n')[1], cap
        rows = _caption_rows(sfig)
        assert _words('\n'.join(rows)) == _words(cap), rows
        right = max(_caption_right_edges(sfig, rows))
        assert right <= 0.99, 'a caption row ends at %.3f' % right
        # ratio mode, no bands, a single mm2 panel and the aggregate each
        # draw no strain band, so none of them may claim one
        _r, rfig = _band_fixture(d2)
        assert 'Strain bands' not in _caption(rfig)
        _r, nofig = _band_fixture(d3, strain_pct=True, bands=False)
        assert 'Strain bands' not in _caption(nofig)
        assert _band_count(nofig) == 0
        _r, firstfig = _band_fixture(d4, strain_pct=True, subplots='first')
        assert 'Strain bands' not in _caption(firstfig)
        _fake_run(d5, _healthy_rows(8))
        aopts = sp.make_opts(strain_pct=True, aggregate=True)[0]
        aggfig = _drawn(sp.prepare_runs([d5], aopts), aopts)
        assert 'Strain bands' not in _caption(aggfig)
    finally:
        for p in (d, d2, d3, d4, d5):
            shutil.rmtree(p, ignore_errors=True)


def test_the_strain_pct_flag_is_accepted_by_the_command_line():
    """`--strain-pct` was documented in the module text and refused by the
    parser ('unknown flag'), so it worked from the window and from a
    spec but not from the command line."""
    parsed = sp._parse_argv(['RUN', '--strain-pct'])
    assert parsed is not None, 'the parser rejected --strain-pct'
    args, flags, vals = parsed
    assert args == ['RUN'] and '--strain-pct' in flags and not vals
    opts, err = sp._cli_opts(flags, vals)
    assert err is None and opts['strain_pct'] is True, (opts, err)
    # absent: off, as before; and a spec that says true is inherited
    opts, err = sp._cli_opts(set(), {})
    assert err is None and opts['strain_pct'] is False
    opts, err = sp._cli_opts(set(), {}, {'strain_pct': True})
    assert err is None and opts['strain_pct'] is True


def test_every_flag_the_parser_takes_is_in_the_usage_block_and_back():
    """The omission this suite missed: the usage text and the parser's two
    flag tuples are typed by hand in two places. They must name the same
    flags, so a flag added to one and not the other fails here."""
    import contextlib
    import io
    import re
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sp._usage()
    shown = set(re.findall(r'--[a-z][a-z-]*', buf.getvalue()))
    taken = set(sp._BOOL_FLAGS) | set(sp._VALUED_FLAGS)
    assert '--strain-pct' in shown, 'usage block does not name --strain-pct'
    assert shown == taken, (sorted(shown - taken), sorted(taken - shown))


def test_strain_pct_from_the_command_line_draws_the_strain_figure():
    """End to end through main(): the flag reaches the figure, is recorded
    in the figspec, and --from-spec re-renders the same bytes."""
    if not _has_mpl():
        return
    d, out, again, plain = _mktmp(), _mktmp(), _mktmp(), _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        assert sp.main([d, '--strain-pct', '--out', out,
                        '--stem', 'sp']) == 0
        spec = os.path.join(out, 'sp.figspec.json')
        assert _read_json(spec)['opts']['strain_pct'] is True
        assert sp.main(['--from-spec', spec, '--out', again]) == 0
        assert sp.main([d, '--out', plain, '--stem', 'sp']) == 0

        def read(folder):
            with open(os.path.join(folder, 'sp.png'), 'rb') as f:
                return f.read()
        assert read(out) == read(again), 're-render is not the same figure'
        assert read(out) != read(plain), '--strain-pct changed nothing'
    finally:
        for p in (d, out, again, plain):
            shutil.rmtree(p, ignore_errors=True)


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


def _staircase_run(d, name, profile, broke):
    """`profile`'s rows as the runner writes them, breaking down at the
    steps in `broke`: current off baseline and the area collapsed."""
    rows = [{'snapshot': n, 'step': s['step'], 'tag': s['tag'],
             'nominal_kV': round(s['nominal_kv'], 3),
             'measured_uA': -300.0 if s['step'] in broke else -16.0,
             'active_area_mm2': (40.0 if s['step'] in broke
                                 else 100.0 + 10 * s['nominal_kv']),
             'timestamp': '2026-09-23T10:00:00',
             'notes': 'edge:disc-fit conf 0.93'}
            for n, s in enumerate(profile.snapshots, start=1)]
    _fake_run(os.path.join(d, name), rows)
    return sp.load_run(os.path.join(d, name), lambda m: None)


def test_first_breakdown_is_the_first_event_in_time():
    """An up/down run that breaks down at 3.5 kV on the way UP keeps
    confirming on the way down, to 2 kV. Its FIRST breakdown is 3.5 kV;
    until 2026-09-23 first_breakdown_kv returned the lowest flagged kV,
    2.0, a level the device passed intact going up.

    The pooled aggregate must still stop at 2.0. Its per-level curve
    averages every visit to a level, so this run's 2.0-3.0 kV means hold
    its collapsed frames from the way down, and capping at the first
    breakdown drew that mixture into the figure (review 2026-09-23). A
    falling single sweep keeps its old cap the same way."""
    import sldea_profile
    d = _mktmp()
    try:
        updown = _staircase_run(d, 'UPDOWN', sldea_profile.SldeaProfile(
            start_kv=0, end_kv=4, step_kv=0.5, updown=True),
            broke=range(7, 13))     # 3.5 kV up, 4.0, then 3.5 .. 2.0 down
        kvs = [updown['rows'][i]['kv'] for i in sorted(updown['flags'])]
        assert kvs == [3.5, 3.5, 4.0, 4.0, 3.5, 3.5, 3.0, 3.0,
                       2.5, 2.5, 2.0, 2.0], kvs
        assert sp.first_breakdown_kv(updown) == 3.5
        assert sp.lowest_breakdown_kv(updown) == 2.0
        fine = _agg_run(d, 'FINE', [0.5 * i for i in range(1, 9)],
                        lambda kv: 100.0 + 11 * kv)
        assert sp.aggregate_cap_kv([updown, fine]) == 2.0
        ag = sp.aggregate_levels([updown, fine])
        mixed = {p['key'] for p in sp.run_level_curve(updown)
                 if p['confirmed']}
        assert mixed and not mixed & {lv['kv'] for lv in ag}, ag
        assert max(lv['kv'] for lv in ag) == 1.5
        # a falling single sweep, 6 -> 1 kV, broken from 3.0 kV on: the
        # first breakdown is its HIGHEST flagged kV, the cap its lowest
        falling = _staircase_run(d, 'FALLING', sldea_profile.SldeaProfile(
            start_kv=6, end_kv=1, step_kv=0.5), broke=range(7, 12))
        assert sp.first_breakdown_kv(falling) == 3.0
        assert sp.aggregate_cap_kv([falling]) \
            == sp.lowest_breakdown_kv(falling) == 1.0
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
        # THE BUDGET'S ANCHOR: 248 is the "Points =" line as COMPOSED
        # under an aggregate...
        under_agg = _caption(_drawn(runs[:1], sp.make_opts(
            aggregate=True)[0])).split('\n')
        assert max(len(l) for l in under_agg[:2]) == sp.CAPTION_LINE_MAX
        # ...and the same line WITHOUT the aggregate is 280, because the
        # band widths are appended whenever the budget bands are drawn.
        # Until 2026-10-06 the 280 ran off a default figure ("never
        # averaged), banc") and the 248 did too at screen dpi (1.02 of the
        # width at 96, 1.09 at 90). Both are WRAPPED now: the composed
        # lengths stay what CAPTION_LINE_MAX's comment records, and
        # test_the_caption_is_wrapped_inside_the_frame holds the drawn
        # rows inside the frame.
        plain = _caption(_drawn(runs[:1], sp.make_opts()[0])).split('\n')
        assert max(len(l) for l in plain) == 280, [len(l) for l in plain]
    finally:
        shutil.rmtree(d, ignore_errors=True)


# the dpis the drawn caption rows are held inside the frame at: the
# window's canvas (100, and 96 / 110 / 150 / 200 under display scaling),
# the export default (300), and the low end where hinting widens a row
# most -- 88 and 90 are the worst above the readable floor, measured
# 2026-10-06 (see CAPTION_FIT_FRAC)
CAPTION_DPIS = (72, 88, 90, 96, 100, 110, 150, 200, 300)


def test_the_caption_is_wrapped_inside_the_frame():
    """MEASURED on main 0ffd1da, 2026-10-06: the default area figure's
    first caption line, 280 characters, ran to 1.24 of the figure width
    at 90 dpi, 1.16 at 96 and 1.12 at 300, losing part of the sentence
    about the two area conventions from every exported PNG; under the
    aggregate its 248 characters reached 1.09, 1.02 and 0.98. Every
    caption line is now wrapped at its measured width. Each drawn row must
    end inside 0.99 of the frame at every dpi above, and the rows must
    carry every word of the caption as composed, in order."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        one = os.path.join(d, 'one')
        _fake_run(one, _healthy_rows(8))
        two = os.path.join(d, 'two')
        _fake_run(two, _healthy_rows(8))
        named = [_agg_run(d, n, [1.0, 2.0],
                          lambda kv, i=i: 100.0 + i + 10 * kv)
                 for i, n in enumerate(('P3_1_2.5mL_20260728',
                                        'DOT_P3_1_20260729',
                                        'SLCBvalidationTest'))]
        groups = [['Carbon Solutions P3-SWNT 2.5 mL',
                   [named[0]['dir'], named[1]['dir']]],
                  ['Carbon black', [named[2]['dir']]]]
        cases = [(kw, sp.prepare_runs(dirs, sp.make_opts(**kw)[0]))
                 for kw, dirs in ((dict(), [one]),
                                  (dict(prepost=True), [one]),
                                  (dict(bands=False), [one]),
                                  (dict(strain_pct=True), [one]),
                                  (dict(aggregate=True), [one, two]),
                                  (dict(x='time'), [one]),
                                  (dict(mode='power'), [one]))]
        cases.append((dict(aggregate=True, groups=groups), named))
        wrapped = 0
        for kw, runs in cases:
            opts = sp.make_opts(**kw)[0]
            for width in (sp.FIGSIZE[opts['mode']][0], 6.0):
                from matplotlib.backends.backend_agg import FigureCanvasAgg
                from matplotlib.figure import Figure
                fig = Figure(figsize=(width, sp.FIGSIZE[opts['mode']][1]))
                FigureCanvasAgg(fig)
                sp.draw(fig, runs, opts)
                cap, rows = _caption(fig), _caption_rows(fig)
                assert _words('\n'.join(rows)) == _words(cap), (kw, rows)
                wrapped += len(rows) > cap.count('\n') + 1
                for dpi in CAPTION_DPIS:
                    fig.set_dpi(dpi)
                    right = max(_caption_right_edges(fig, rows))
                    assert right <= 0.99, (kw, width, dpi, right)
                # the strip holds the rows: the caption's top stays below
                # every axes' lowest artist (its x label, its ticks)
                fig.set_dpi(100)
                fig.canvas.draw()
                rend = fig.canvas.get_renderer()
                top = getattr(fig, sp._CAPTION_ATTR)[0] \
                    .get_window_extent(rend).y1
                low = min(ax.get_tightbbox(rend).y0 for ax in fig.axes)
                assert top < low, (kw, width, top, low)
        # the default figure is the reason for all this: it wraps at its
        # own size, and so do --prepost, --no-bands, strain and aggregate
        assert wrapped >= 10, wrapped
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_caption_that_fits_is_left_exactly_as_it_was():
    """The wrap only touches a line too wide for the figure. Current and
    power captions fit at their size, so they are drawn as composed and
    keep the 5% strip they always had, which is why those figures are
    still byte-identical to the pre-change engine above."""
    if not _has_mpl():
        return
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        for mode in ('current', 'power'):
            opts = sp.make_opts(mode=mode)[0]
            fig = _drawn(sp.prepare_runs([d], opts), opts)
            assert '\n'.join(_caption_rows(fig)) == _caption(fig)
            assert getattr(fig, sp._RECT_ATTR) == (0, 0.05, 1, 1)
        # ...and the area figure, which does wrap, takes the per-row
        # allowance the multi-line captions already use (3 rows: 0.10)
        opts = sp.make_opts()[0]
        fig = _drawn(sp.prepare_runs([d], opts), opts)
        assert len(_caption_rows(fig)) == 3, _caption_rows(fig)
        assert getattr(fig, sp._RECT_ATTR)[1] == 0.025 + 0.025 * 3
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_a_resize_re_wraps_the_caption_as_a_rebuild_would():
    """The window resizes through relayout, which does not rebuild the
    figure (`#316`). The caption is the one thing on it that depends on
    the width, so relayout re-wraps it and re-measures its strip, and must
    land exactly where a draw at the new size lands: same rows, same rect,
    same axes, to the last bit. Then back out to the old size."""
    if not _has_mpl():
        return
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    d = _mktmp()
    try:
        _fake_run(d, _healthy_rows(8))
        opts = sp.make_opts(aggregate=True)[0]
        runs = sp.prepare_runs([d], opts)

        def fresh(w, h):
            fig = Figure(figsize=(w, h))
            FigureCanvasAgg(fig)
            sp.draw(fig, runs, opts)
            return fig

        def state(fig):
            return (_caption_rows(fig), getattr(fig, sp._RECT_ATTR),
                    [tuple(ax.get_position().bounds) for ax in fig.axes])

        fig = fresh(*sp.FIGSIZE['area'])
        wide = state(fig)
        for w, h in ((6.0, 4.0), (9.0, 5.4), sp.FIGSIZE['area']):
            fig.set_size_inches(w, h)
            assert sp.relayout(fig)
            assert state(fig) == state(fresh(w, h)), (w, h)
        assert state(fig) == wide
        assert len(state(fresh(6.0, 4.0))[0]) > len(wide[0]), \
            'a narrower figure wrapped no further; fixture too tame'
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_wrap_keeps_every_word_and_indents_the_continuations():
    """_wrap on its own, with a character-count fit so it is hand-checked:
    rows break at spaces, continuation rows carry the indent and still
    fit with it, every word survives, and only a word wider than a whole
    row is broken inside the word."""
    def fits(s):
        return len(s) <= 20
    ind = sp.CAPTION_WRAP_INDENT
    rows = sp._wrap('the quick brown fox jumps over the lazy dog', fits)
    assert rows == ['the quick brown fox', ind + 'jumps over the', ind
                    + 'lazy dog'], rows
    assert all(fits(r) for r in rows)
    # the double space between sentences stays inside a row
    rows = sp._wrap('a.  Two spaces stay between sentences.', fits)
    assert rows == ['a.  Two spaces stay', ind + 'between',
                    ind + 'sentences.'], rows
    # a word wider than a row is the only thing broken inside a word, and
    # its pieces after the first still fit WITH the indent
    rows = sp._wrap('C:/a/very/long/pasted/path/with/no/spaces x', fits)
    assert rows == ['C:/a/very/long/paste', ind + 'd/path/with/no/s',
                    ind + 'paces x'], rows
    assert all(fits(r) for r in rows), rows


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


# --------------------------------------------------------------------------
# up/down legs and the elapsed-time axis (2026-09-23)
#
# An "Up/down (hysteresis)" run visits every level below the peak twice.
# Keyed by kV the plotter averaged the two visits into one point -- the loop
# the run was recorded to show vanished -- and --prepost's per-kV slots kept
# only the falling leg. These pin the leg-by-leg view, its arrows, the
# elapsed-time axis, and that none of it moves a single-sweep figure.
# --------------------------------------------------------------------------

# the commit this work was cut from: an ANCESTOR of main, so -- unlike
# _BASE_SHA, which main's history does not contain -- it is reachable in
# every clone, and the comparisons below run everywhere rather than skip
_LEGS_BASE_SHA = '78315cc27c9d2b001d99f8d198aa5a4e5bb1e1d5'

FALL_OFFSET = 8.0       # mm2: the falling leg sits this much HIGHER


def _updown_rows(end_kv=1.5, step_kv=0.5, updown=True, repeat=1):
    """Rows exactly as the bench writes them -- the REAL SldeaProfile
    schedule (warm-up and baseline frames, post-ramp before pre-ramp, step
    numbers, planned times) -- with a falling leg FALL_OFFSET above the
    rising one at every level: the viscoelastic lag the mode exists to
    record. Timestamps trail the plan by 0.3 s, as grab latency does."""
    import datetime
    import sldea_profile as sprof
    p = sprof.SldeaProfile(end_kv=end_kv, step_kv=step_kv, updown=updown,
                           repeat=repeat)
    seq = p.sequence()
    t0 = datetime.datetime(2026, 9, 23, 10, 0, 0)
    rows = []
    for n, s in enumerate(sorted(p.snapshots, key=lambda s: s['t']), 1):
        kv, st = s['nominal_kv'], s['step']
        falling = st >= 2 and seq[st - 1] < seq[st - 2]
        area = (None if s['tag'] == 'warmup' else
                round(201.062 * (1 + 0.1 * kv)
                      + (FALL_OFFSET if falling else 0.0), 3))
        rows.append({
            'snapshot': n, 'step': st, 'tag': s['tag'], 'nominal_kV': kv,
            'measured_uA': round(-16.0 + (1.0 if falling else 2.0) * kv, 2),
            't_planned_s': round(s['t'], 2),
            'timestamp': (t0 + datetime.timedelta(seconds=s['t'] + 0.3)
                          ).isoformat(timespec='milliseconds'),
            'active_area_px': '' if area is None else round(area * 1435),
            'active_area_mm2': '' if area is None else area,
            'notes': '' if area is None else 'edge:disc-fit conf 0.93'})
    return rows


def _rise_area(kv):
    return round(201.062 * (1 + 0.1 * kv), 3)


def _loaded(rows, name='UD_run'):
    """(tmpdir, run) -- the rows written as a run and loaded through the
    real load_run, colour assigned the way prepare_runs does."""
    d = _mktmp()
    rd = os.path.join(d, name)
    _fake_run(rd, rows)
    run = sp.load_run(rd, lambda m: None)
    run['color'] = sp.TOL_BRIGHT[0]
    return d, run


def _legs_of(run):
    """[(kv, leg, cycle)] per LANDING, in time order."""
    out, seen = [], set()
    for r in run['rows']:
        if r['landing'] is not None and r['landing'] not in seen:
            seen.add(r['landing'])
            out.append((r['kv'], r['leg'], r['cycle']))
    return out


def test_sweep_legs_reads_the_direction_from_the_kv_sequence():
    cases = [
        # a single sweep is all one rising leg -- the property that keeps
        # its figure untouched
        (dict(updown=False),
         [(0.0, 'rise', 1), (0.5, 'rise', 1), (1.0, 'rise', 1),
          (1.5, 'rise', 1)]),
        # up/down: the peak ends the rising leg, then it falls
        (dict(updown=True),
         [(0.0, 'rise', 1), (0.5, 'rise', 1), (1.0, 'rise', 1),
          (1.5, 'rise', 1), (1.0, 'fall', 1), (0.5, 'fall', 1)]),
        # up/down x2: the bottom level is landed TWICE where the cycles
        # meet; the second visit takes the direction of the ramp OUT of it
        (dict(updown=True, repeat=2),
         [(0.0, 'rise', 1), (0.5, 'rise', 1), (1.0, 'rise', 1),
          (1.5, 'rise', 1), (1.0, 'fall', 1), (0.5, 'fall', 1),
          (0.5, 'rise', 2), (1.0, 'rise', 2), (1.5, 'rise', 2),
          (1.0, 'fall', 2), (0.5, 'fall', 2)]),
        # a plain repeat drops straight from the peak back to the bottom:
        # a one-landing fall, and cycle 2 rises from there
        (dict(updown=False, repeat=2),
         [(0.0, 'rise', 1), (0.5, 'rise', 1), (1.0, 'rise', 1),
          (1.5, 'rise', 1), (0.5, 'fall', 1), (1.0, 'rise', 2),
          (1.5, 'rise', 2)]),
    ]
    for kw, want in cases:
        d, run = _loaded(_updown_rows(**kw))
        try:
            assert _legs_of(run) == want, (kw, _legs_of(run))
            assert sp.multi_leg(run) == any(l == 'fall' for _k, l, _c in want)
            # both snapshots of a landing share it: two rows per landing
            # after the 0 kV frames, post-ramp first
            by = {}
            for r in run['rows']:
                if r['landing']:
                    by.setdefault(r['landing'], []).append(r['tag'])
            assert all(v == ['post-ramp', 'pre-ramp'] for v in by.values()), by
        finally:
            shutil.rmtree(d, ignore_errors=True)


def test_sweep_legs_copes_without_step_numbers_and_with_a_trip():
    # the fixtures (and pre-`step` data) carry no landing numbers: every
    # level is still ONE rising leg, even written pre-ramp first
    d, run = _loaded(_healthy_rows(4))
    try:
        assert {r['leg'] for r in run['rows']} == {'rise'}
        assert {r['cycle'] for r in run['rows']} == {1}
        assert not sp.multi_leg(run)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    # a watchdog row records the kV at the trip -- partway up a ramp -- and
    # is a landing of its own, still on the rising leg
    rows = _updown_rows(updown=False)
    rows.append({'snapshot': len(rows) + 1, 'step': 99, 'tag': 'breakdown',
                 'nominal_kV': 1.37, 'measured_uA': 150.0,
                 't_planned_s': 999.0, 'timestamp': rows[-1]['timestamp']})
    d, run = _loaded(rows)
    try:
        bd = [r for r in run['rows'] if r['tag'] == 'breakdown'][0]
        others = {r['landing'] for r in run['rows'] if r is not bd}
        assert bd['landing'] not in others and bd['leg'] == 'fall', \
            "1.37 kV after the 1.5 kV landing is a way down"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_levels_by_landing_keeps_the_two_legs_apart():
    d, run = _loaded(_updown_rows())
    try:
        # keyed by kV (the old view): the 1 kV level BLENDS both visits
        by_kv = {round(l['kv'], 3): l for l in sp.levels(run)}
        assert abs(by_kv[1.0]['mean']
                   - (_rise_area(1.0) + FALL_OFFSET / 2)) < 1e-6
        # keyed by landing: two entries at 1 kV, one per leg, unblended
        at1 = [l for l in sp.levels(run, by='landing') if l['kv'] == 1.0]
        assert [(l['leg'], round(l['mean'], 3)) for l in at1] == [
            ('rise', _rise_area(1.0)),
            ('fall', round(_rise_area(1.0) + FALL_OFFSET, 3))], at1
    finally:
        shutil.rmtree(d, ignore_errors=True)
    # ...and on a single sweep the two groupings hold the same numbers
    d, run = _loaded(_updown_rows(updown=False))
    try:
        assert [(l['kv'], l['mean']) for l in sp.levels(run)] == [
            (l['kv'], l['mean']) for l in sp.levels(run, by='landing')]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _arrows(ax):
    """[(tail_x, tail_y, head_x, head_y)] for every direction arrow."""
    return [(a.xyann[0], a.xyann[1], a.xy[0], a.xy[1])
            for a in ax.texts if getattr(a, 'arrow_patch', None)]


def _marked(ax, marker):
    """[(x, y)] of every point drawn with `marker` on `ax`."""
    out = []
    for ln in ax.get_lines():
        if ln.get_marker() == marker:
            out += list(zip(ln.get_xdata(), ln.get_ydata()))
    return out


def test_updown_legs_and_the_time_axis_draw_the_strain_band_in_strain_points():
    """The leg and time-axis paths (2026-09-23) were written before the
    strain-band fix (2026-10-02) and met it at the 2026-10-05 rebase. Both
    must pass the panel's units to the band: under --strain-pct a machine
    point at A/A0 = r gets a half-width of 2 * r points, never 2 % of the
    strain value (which is zero at rest). Read off the drawn bands."""
    if not _has_mpl():
        return
    d, run = _loaded(_updown_rows())
    try:
        for kw in (dict(strain_pct=True), dict(strain_pct=True, x='time')):
            fig = _drawn([run], sp.make_opts(**kw)[0])
            bands = _band_polys(fig.axes[1])
            assert bands, (kw, 'no band on the strain panel')
            n = 0
            for band in bands:
                for x, (lo, hi) in band.items():
                    r = 1.0 + (lo + hi) / 200.0
                    half = (hi - lo) / 2.0
                    assert abs(half - sp.MACHINE_BAND_PCT * r) < 1e-6, \
                        (kw, x, lo, hi)
                    n += 1
            assert n >= 4, (kw, n)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_an_updown_run_draws_both_legs_with_their_arrows():
    if not _has_mpl():
        return
    d, run = _loaded(_updown_rows())
    try:
        opts = sp.make_opts()[0]
        fig = _drawn([run], opts)
        ax = fig.axes[0]
        up, down = _marked(ax, '^'), _marked(ax, 'v')
        assert sorted(x for x, _y in up) == [0.0, 0.5, 1.0, 1.5], up
        assert sorted(x for x, _y in down) == [0.5, 1.0], down
        # the falling points carry the falling leg's OWN areas
        for x, y in down:
            assert abs(y - (_rise_area(x) + FALL_OFFSET)) < 1e-6, (x, y)
        assert not _marked(ax, 'o'), "a leg-split run keeps no round dots"
        arrows = _arrows(ax)
        assert arrows, "no direction arrows on an up/down run"
        for tx, ty, hx, hy in arrows:
            rising = abs(ty - _rise_area(tx)) < 3.0
            assert (hx > tx) == rising, (tx, ty, hx, hy)
        cap = _caption(fig)
        assert 'Up/down runs' in cap and 'direction of travel' in cap
        # --no-arrows drops only the arrows; --merge-legs is the old view
        fig = _drawn([run], sp.make_opts(arrows=False)[0])
        assert not _arrows(fig.axes[0]) and _marked(fig.axes[0], 'v')
        fig = _drawn([run], sp.make_opts(split_legs=False)[0])
        assert not _marked(fig.axes[0], 'v') and _marked(fig.axes[0], 'o')
        assert not _arrows(fig.axes[0])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_prepost_keeps_the_rising_leg_of_an_updown_run():
    if not _has_mpl():
        return
    d, run = _loaded(_updown_rows())
    try:
        # the old per-kV dict overwrote post/pre with the LAST visit, so
        # the rising leg never reached the figure at all
        fig = _drawn([run], sp.make_opts(prepost=True)[0])
        ys_at_1kv = {round(y, 3) for x, y in _marked(fig.axes[0], '^')
                     + _marked(fig.axes[0], 'v') if x == 1.0}
        assert _rise_area(1.0) in ys_at_1kv, ys_at_1kv
        assert round(_rise_area(1.0) + FALL_OFFSET, 3) in ys_at_1kv
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_current_mode_marks_the_legs_and_their_direction():
    if not _has_mpl():
        return
    d, run = _loaded(_updown_rows())
    try:
        fig = _drawn([run], sp.make_opts(mode='current')[0])
        ax = fig.axes[0]
        assert _marked(ax, '^') and _marked(ax, 'v')
        for tx, ty, hx, hy in _arrows(ax):
            # rising samples sit on -16 + 2 kV, falling on -16 + 1 kV
            rising = abs(ty - (-16.0 + 2.0 * tx)) < 0.3
            assert (hx > tx) == rising, (tx, ty, hx, hy)
        assert _arrows(ax)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_legs_and_arrows_leave_single_sweeps_and_merge_restores_updown():
    """Byte for byte, against the engine this work was cut from: every
    mode's DEFAULT figure of a single sweep, and --merge-legs --no-arrows
    on an up/down run -- the escape hatch has to be exactly the old
    figure, not a lookalike. Area figures since 2026-10-06: the old figure
    with its caption re-wrapped and its strip re-laid, nothing else
    (_old_figure_rewrapped)."""
    if not _has_mpl():
        return
    old = _pre_change_module(_LEGS_BASE_SHA)
    if old is None:
        print('  (skipped: base sldea_plot not reachable via git)')
        return
    out = _mktmp()
    try:
        for label, rows, extra in (
                ('single', _updown_rows(updown=False), {}),
                ('updown', _updown_rows(), dict(split_legs=False,
                                               arrows=False))):
            d = os.path.join(out, label)
            _fake_run(d, rows)
            for mode in sp.MODES:
                new_opts = sp.make_opts(mode=mode, **extra)[0]
                old_opts = old.make_opts(mode=mode)[0]
                new_png = sp.save_figure(
                    sp.prepare_runs([d], new_opts), new_opts,
                    os.path.join(out, f"{label}_{mode}_new.png"))
                if mode == 'area':
                    old_png = _old_figure_rewrapped(
                        old, [d], old_opts, new_opts,
                        os.path.join(out, f"{label}_{mode}_old.png"))
                else:
                    old_png = old.save_figure(
                        old.prepare_runs([d], old_opts), old_opts,
                        os.path.join(out, f"{label}_{mode}_old.png"))
                with open(new_png, 'rb') as a, open(old_png, 'rb') as b:
                    assert a.read() == b.read(), f"{label} {mode} PNG moved"
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_the_time_axis_plots_every_snapshot_in_the_order_taken():
    if not _has_mpl():
        return
    d, run = _loaded(_updown_rows())
    try:
        assert run['t_src'] == 't_planned_s'
        opts = sp.make_opts(x='time')[0]
        fig = _drawn([run], opts)
        ax = fig.axes[0]
        line = max(ax.get_lines(), key=lambda ln: len(ln.get_xdata()))
        want = [r['t_planned'] / 60.0 for r in run['rows']
                if r['area_mm2'] is not None]
        assert list(line.get_xdata()) == want, "not one point per snapshot"
        assert want == sorted(want), "not in the order taken"
        assert ax.get_xlabel() == 'Elapsed time (min)'
        assert ax.get_title(loc='left') == 'Active area vs time'
        cap = _caption(fig)
        assert 'elapsed time' in cap and 't_planned_s' in cap, cap
        assert not _arrows(ax), "time already runs one way; no arrows"
        # the legs still say which stretch was the way down
        assert _marked(ax, 'v') and _marked(ax, '^')
        # current mode follows the same axis
        fig = _drawn([run], sp.make_opts(mode='current', x='time')[0])
        assert fig.axes[0].get_xlabel() == 'Elapsed time (min)'
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_time_axis_falls_back_to_timestamps_whole_runs_at_a_time():
    rows = _updown_rows(updown=False)
    for r in rows[3:]:
        r['t_planned_s'] = ''             # a run half on the schedule...
    d, run = _loaded(rows)
    try:
        # ...is read wholly off the wall clock, never on two clocks at once
        assert run['t_src'] == 'timestamp'
        first = next(r for r in run['rows'] if r['elapsed_s'] is not None)
        assert first['elapsed_s'] == 0.0
        assert all(r['elapsed_s'] is not None for r in run['rows'])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_time_axis_refuses_what_it_cannot_mean():
    assert sp.make_opts(x='time')[1] is None
    assert '--x' in sp.make_opts(x='sideways')[1]
    for kw in (dict(prepost=True), dict(mean=True), dict(aggregate=True),
               dict(mode='current', vs_area=True)):
        opts, err = sp.make_opts(x='time', **kw)
        assert opts is None and err, kw


def test_cli_takes_the_axis_and_the_leg_switches():
    parsed = sp._parse_argv(['r', '--x', 'time', '--merge-legs',
                             '--no-arrows'])
    assert parsed is not None
    _args, flags, vals = parsed
    opts, err = sp._cli_opts(flags, vals)
    assert err is None, err
    assert (opts['x'], opts['split_legs'], opts['arrows']) == (
        'time', False, False)
    # a figspec re-renders them as recorded, and a flag still wins over it
    spec = sp.build_figspec([], opts, 'sldea_plot_area')
    back, err = sp._cli_opts(set(), {}, spec['opts'])
    assert err is None and (back['x'], back['split_legs'],
                            back['arrows']) == ('time', False, False)
    back, err = sp._cli_opts(set(), {'--x': 'kv'}, spec['opts'])
    assert err is None and back['x'] == 'kv'


def test_tidy_csv_says_which_leg_and_when():
    d, run = _loaded(_updown_rows())
    try:
        path = sp.write_tidy([run], os.path.join(d, 't.csv'))
        with open(path, newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        got = [(r['tag'], r['nominal_kV'], r['leg'], r['cycle'])
               for r in rows if r['tag'] == 'post-ramp']
        assert got == [('post-ramp', '0.5', 'rise', '1'),
                       ('post-ramp', '1.0', 'rise', '1'),
                       ('post-ramp', '1.5', 'rise', '1'),
                       ('post-ramp', '1.0', 'fall', '1'),
                       ('post-ramp', '0.5', 'fall', '1')], got
        assert [float(r['elapsed_s']) for r in rows] == [
            r['t_planned'] for r in run['rows']]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_the_aggregate_takes_an_updown_runs_first_rising_leg():
    d1, ud = _loaded(_updown_rows(), 'UD')
    d2, ss = _loaded(_updown_rows(updown=False), 'SS')
    try:
        at = {round(l['kv'], 3): l['mean']
              for l in sp.aggregate_levels([ud, ss], legs=True)}
        # both runs rise identically, so the rising-leg mean IS that curve
        assert abs(at[1.0] - _rise_area(1.0)) < 1e-6, at
        blended = {round(l['kv'], 3): l['mean']
                   for l in sp.aggregate_levels([ud, ss], legs=False)}
        assert blended[1.0] > at[1.0], "--merge-legs keeps the old pooling"
        if _has_mpl():
            warns = []
            fig = _drawn([ud, ss], sp.make_opts(aggregate=True)[0],
                         warns.append)
            assert 'FIRST RISING' in _caption(fig)
            assert any('first rising leg' in w for w in warns), warns
    finally:
        shutil.rmtree(d1, ignore_errors=True)
        shutil.rmtree(d2, ignore_errors=True)


def test_every_flag_the_cli_reads_is_one_the_parser_accepts():
    """The OTHER side of the seam the test above guards.

    --strain-pct was wired through _cli_opts but never registered in
    _BOOL_FLAGS, so `sldea_plot.py RUN --strain-pct` died in _parse_argv
    with "unknown flag" -- the flag the docstring advertised could not be
    typed (found 2026-09-23). The drift test compares _cli_opts with
    make_opts and could not see it; this compares _cli_opts with the
    parser, by reading the flags straight out of its source."""
    import inspect
    import re
    read = set(re.findall(r"'(--[a-z][a-z-]*)'",
                          inspect.getsource(sp._cli_opts)))
    assert len(read) > 10, f"the scan found too few flags: {sorted(read)}"
    missing = sorted(read - set(sp._BOOL_FLAGS) - set(sp._VALUED_FLAGS))
    assert not missing, (
        f"_cli_opts reads {missing}, which _parse_argv rejects as unknown "
        f"-- register them in _BOOL_FLAGS or _VALUED_FLAGS")
    # ...and the one that was broken, end to end
    parsed = sp._parse_argv(['somerun', '--strain-pct'])
    assert parsed is not None, "--strain-pct is rejected by the parser"
    _args, flags, vals = parsed
    opts, err = sp._cli_opts(flags, vals)
    assert err is None and opts['strain_pct'] is True, (opts, err)


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
