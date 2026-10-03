#!/usr/bin/env python3
"""Headless tests for sldea_diag -- the run diagnostic's measurements.

The diagnostic exists to tell us which failure mode a run actually has, so
a measurement that lies is worse than no measurement: it would send the
next round of detector work in the wrong direction. These pin the four
numbers the verdicts are built on.

Run: .venv/bin/python tests/test_sldea_diag.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import tempfile

import numpy as np

import sldea_diag as sd


def _scene(shift=0.0, wrinkle=False, bright=0.0, seed=3):
    """A frame pair: baseline, then the same scene with one thing changed."""
    import cv2
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:240, 0:320]
    base = np.full((240, 320), 90.0, np.float32)
    base[np.abs(xx - 20) < 6] = 230.0            # structure on both axes,
    base[np.abs(yy - 18) < 5] = 215.0            # so a shift is well posed
    base += rng.normal(0, 1.5, base.shape)
    img = base.copy()
    disc = (xx - 160) ** 2 + (yy - 120) ** 2 <= 60 * 60
    if wrinkle:
        img[disc] += 26 * np.sin((xx[disc] + yy[disc]) / 2.2)
    if bright:
        img[disc] += bright
    if shift:
        m = np.float32([[1, 0, shift], [0, 1, shift * 0.5]])
        img = cv2.warpAffine(img, m, (320, 240),
                             borderMode=cv2.BORDER_REPLICATE)
    return (np.clip(base, 0, 255).astype(np.float32),
            np.clip(img, 0, 255).astype(np.float32), disc)


def test_separability_splits_bimodal_not_noise():
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 1, 20000)
    two = np.concatenate([rng.normal(0, 1, 10000), rng.normal(12, 1, 10000)])
    # a single Gaussian is the zero point, not a low score: raw Otsu eta
    # would call it 0.64 and every map would look separable
    assert sd.separability(noise) < 0.05, sd.separability(noise)
    assert sd.separability(two) > 0.85, sd.separability(two)
    # a constant map cannot be split at all, and must not divide by zero
    assert sd.separability(np.full(500, 7.0)) == 0.0


def test_texture_map_sees_wrinkles_and_ignores_brightness():
    """The bench case: the DEA sometimes wrinkles WITHOUT expanding, so a
    brightness step and a texture change must not read the same."""
    base, wrinkled, disc = _scene(wrinkle=True)
    _b2, brighter, _d = _scene(bright=34.0)
    tb = sd.texture_map(base)
    r_wrinkle = float(np.median(sd.texture_map(wrinkled)[disc] / tb[disc]))
    r_bright = float(np.median(sd.texture_map(brighter)[disc] / tb[disc]))
    assert r_wrinkle > 5.0, r_wrinkle
    assert 0.5 < r_bright < 2.0, r_bright      # a flat step adds no texture


def test_drift_measures_a_known_shift():
    base, moved, _d = _scene(shift=3.0)
    dx, dy, resp, _al = sd.drift(base, moved)
    assert abs(np.hypot(dx, dy) - np.hypot(3.0, 1.5)) < 1.0, (dx, dy)
    assert resp > 0.05, resp


def test_drift_does_not_modify_its_inputs():
    """Regression: cv2.phaseCorrelate given a window multiplies it INTO its
    inputs when the frame needs no DFT padding. Handing it the caller's
    arrays left a Hanning-darkened baseline behind, and every later
    measurement in the module silently read a corrupted reference."""
    base, moved, _d = _scene(shift=2.0)
    b0, m0 = base.copy(), moved.copy()
    sd.drift(base, moved)
    assert np.array_equal(base, b0), "baseline was modified by drift()"
    assert np.array_equal(moved, m0), "frame was modified by drift()"


def test_registration_reduces_the_difference_energy():
    import cv2
    base, moved, _d = _scene(shift=3.0)
    _dx, _dy, _r, aligned = sd.drift(base, moved)
    raw = float(cv2.absdiff(moved, base).mean())
    reg = float(cv2.absdiff(aligned, base).mean())
    assert reg < 0.75 * raw, (raw, reg)


def test_noise_sigma_prefers_a_zero_kv_pair():
    rng = np.random.default_rng(11)
    base = np.full((240, 320), 90.0, np.float32) + rng.normal(0, 3.0,
                                                              (240, 320))
    other = np.full((240, 320), 90.0, np.float32) + rng.normal(0, 3.0,
                                                               (240, 320))
    sigma, src = sd.noise_sigma(base, [{'kv': 0.0, 'gray': other}], 0.85)
    assert src == 'baseline pair'
    assert 2.0 < sigma < 4.0, sigma           # recovers the injected 3.0


def test_analyze_reports_the_dominant_failure_of_each_synthetic_run():
    root = tempfile.mkdtemp(prefix='diag_tests_')

    exp = sd.analyze(sd._synth_run(_os.path.join(root, 'SLDEA_e'), 'expand'))
    assert exp['frames_analyzed'] == 3
    assert np.median([p['sep_intensity'] for p in exp['frames']]) > 0.3
    assert np.median([p['shift_px'] for p in exp['frames']]) < 1.0

    wr = sd.analyze(sd._synth_run(_os.path.join(root, 'SLDEA_w'), 'wrinkle'))
    # the disc never changes size here, so texture must carry the signal
    assert np.median([p['texture_ratio'] for p in wr['frames']]) > 1.3

    dr = sd.analyze(sd._synth_run(_os.path.join(root, 'SLDEA_d'), 'expand',
                                  shift=3.0))
    assert np.median([p['shift_px'] for p in dr['frames']]) > 1.5
    heads = [h for _sev, h, _detail in sd.verdicts(dr)]
    assert any('drift' in h.lower() for h in heads), heads
    # and the run without drift must NOT be accused of it
    ok_heads = [h for _s, h, _d in sd.verdicts(exp)]
    assert any('stable' in h.lower() for h in ok_heads), ok_heads


def test_photometric_fit_recovers_gain_and_offset():
    """Bench runs P3_* 2026-07-28: every frame, including 0.25 kV where
    nothing has activated, differed from the baseline by 10-17 sigma. A
    gain+offset model has to be able to take that back out, or the
    diagnostic cannot tell photometry from the device."""
    # an intensity RAMP, not _scene(): its rig bars sit at 230 and would
    # saturate under a 1.22 gain, and clipped highlights bias the slope
    # down -- the same trap real frames set when electrodes blow out
    rng = np.random.default_rng(5)
    base = np.tile(np.linspace(20, 180, 320, dtype=np.float32), (240, 1))
    base += rng.normal(0, 1.5, base.shape).astype(np.float32)
    frame = np.clip(base * 1.22 + 4.0, 0, 255).astype(np.float32)
    roi = sd._roi(base.shape, 0.85)
    a, b = sd.photometric_fit(base, frame, roi)
    assert abs(a - 1.22) < 0.05, a
    assert abs(b - 4.0) < 3.0, b
    raw = float(np.abs(frame[roi] - base[roi]).mean())
    corrected = float(np.abs((a * base[roi] + b) - frame[roi]).mean())
    assert raw > 15, raw
    assert corrected < 0.15 * raw, (raw, corrected)


def test_photometry_verdict_fires_on_an_exposure_mismatch():
    root = tempfile.mkdtemp(prefix='diag_photo_')
    d = sd.analyze(sd._synth_run(_os.path.join(root, 'SLDEA_p'), 'expand',
                                 gain=1.22, offset=4.0))
    heads = [h for _s, h, _det in sd.verdicts(d)]
    assert any('photometry' in h.lower() for h in heads), heads
    for p in d['frames']:
        assert p['diff_mean_photofit'] < p['diff_mean'], p['kv']


def test_same_voltage_pairs_expose_an_instrument_floor():
    """The run carries its own control: two snapshots at one voltage hold
    the same scene in the same state. If they differ, that is the camera,
    and it bounds every other number in the report. Modelled here as a
    per-snapshot gain, the behaviour a camera reopened for every grab
    would show."""
    root = tempfile.mkdtemp(prefix='diag_rep_')
    d = sd.analyze(sd._synth_run(_os.path.join(root, 'SLDEA_j'), 'expand',
                                 jitter=0.2))
    rep = d['repeats']
    assert rep['kind'] == 'same voltage', rep['kind']
    assert len(rep['pairs']) >= 3, rep['pairs']
    # a gain+offset fit between the pair members takes the difference back
    # out: nothing moved, only the exposure did
    for p in rep['pairs']:
        assert p['diff_mean_photofit'] < p['diff_mean'], p
    heads = [h.lower() for _s, h, _det in sd.verdicts(d)]
    assert any('should be identical' in h for h in heads), heads


def test_a_steady_camera_is_not_accused_of_a_floor():
    root = tempfile.mkdtemp(prefix='diag_steady_')
    d = sd.analyze(sd._synth_run(_os.path.join(root, 'SLDEA_s'), 'expand'))
    heads = [h.lower() for _s, h, _det in sd.verdicts(d)]
    assert not any('should be identical' in h for h in heads), heads


def test_ab_compares_the_two_normalizations_on_the_same_frames():
    """Residuals are the means; detections are the end. The report has to
    say whether switching normalization changed what candidates() actually
    found, on the same frames, in one run."""
    root = tempfile.mkdtemp(prefix='diag_ab_')
    d = sd.analyze(sd._synth_run(_os.path.join(root, 'SLDEA_ab'), 'expand',
                                 gain=0.78, offset=12.0))
    for p in d['frames']:
        assert p['alt_norm_bg'] == 1, p       # default is 2, so alt is 1
        for k in ('alt_area_px', 'alt_conf', 'alt_needs_review'):
            assert k in p, k
    heads = [h for _s, h, _det in sd.verdicts(d)]
    assert any('vs' in h and 'gain+offset' in h for h in heads), heads


def test_gate_is_read_off_the_map_the_detector_thresholds():
    """The gate and Otsu columns describe detector behaviour, so they must
    come from the normalized map candidates() cuts -- not a raw difference
    it never sees. Under a photometric mismatch those differ hugely."""
    base, _img, _d = _scene()
    frame = np.clip(base * 0.78 + 12.0, 0, 255).astype(np.float32)
    s = dict(sd.se.DEFAULT_SETTINGS)
    raw = float(np.percentile(np.abs(frame - base), 99))
    det = float(np.percentile(sd._detector_diff(base, frame, s), 99))
    assert raw > 20, raw            # the uncorrected mismatch is large...
    assert det < 0.5 * raw, (det, raw)   # ...the detector does not see it


def _fake_d(**frame_overrides):
    """A verdicts() input with everything neutral, for testing one rule."""
    frame = {'idx': 1, 'kv': 5.0, 'file': 'f.png', 'shift_px': 0.1,
             'dx': 0.1, 'dy': 0.0, 'pc_response': 0.5, 'diff_mean': 4.0,
             'diff_mean_registered': 4.0, 'diff_mean_normbg': 4.0,
             'diff_mean_photofit': 4.0, 'gain': 1.0, 'offset': 0.0,
             'diff_p99': 8.0, 'diff_p99_sigma': 4.0, 'gated': False,
             'otsu': 20.0, 'texture_ratio': 1.0, 'sep_intensity': 0.4,
             'sep_registered': 0.4, 'sep_photofit': 0.4, 'sep_texture': 0.4,
             'area_px': 1000.0, 'solidity': 0.7, 'conf': 0.8,
             'needs_review': False}
    frame.update(frame_overrides)
    return {'rundir': '/x', 'frames_analyzed': 3, 'baseline_row': 0,
            'frame_shape': [240, 320], 'sigma': 2.0,
            'sigma_source': 'test', 'settings': dict(se_defaults()),
            'sweep_thresholds': [3, 5], 'sweeps': [], 'repeats': {},
            'frames': [dict(frame), dict(frame), dict(frame)]}


def se_defaults():
    import sldea_edge as se
    return se.DEFAULT_SETTINGS


def test_a_large_shift_registration_cannot_cash_in_is_not_called_drift():
    """Bench runs P3_*: phase correlation reported 5-27 px, but undoing it
    changed the diff energy by ~1% -- the horizontal electrode strips leave
    translation along their own axis unobservable. Calling that drift would
    aim the next fix at registration, which the data says will not help."""
    d = _fake_d(shift_px=14.0, diff_mean=30.0, diff_mean_registered=29.7)
    verdicts = sd.verdicts(d)
    heads = [h.lower() for _s, h, _det in verdicts]
    assert any('not a real translation' in h for h in heads), heads
    assert not any('drift is polluting' in h for h in heads), heads
    # and when registration DOES pay off, it is still called drift
    d2 = _fake_d(shift_px=14.0, diff_mean=30.0, diff_mean_registered=15.0)
    heads2 = [h.lower() for _s, h, _det in sd.verdicts(d2)]
    assert any('drift' in h and 'polluting' in h for h in heads2), heads2


def test_report_renders_for_every_synthetic_run():
    root = tempfile.mkdtemp(prefix='diag_report_')
    d = sd.analyze(sd._synth_run(_os.path.join(root, 'SLDEA_r'), 'wrinkle'))
    text = sd.report(d)
    for want in ('VERDICTS', 'PER FRAME', 'sensor sigma', 'sep-T', 'foil%',
                 'resting disc'):
        assert want in text, want


def test_report_does_not_call_the_spread_a_confidence_interval():
    """2026-10-02: the ci% column is the block-bootstrap spread of the
    common-ray ratio. The legend used to call it 'the disc-fit's own 85%
    confidence interval', a name the old edge-scatter formula never
    earned (measured coverage 21-49 %) and the new number does not claim.
    The key says what it is, and what it leaves out."""
    root = tempfile.mkdtemp(prefix='diag_ci_')
    d = sd.analyze(sd._synth_run(_os.path.join(root, 'SLDEA_r'), 'wrinkle'))
    text = sd.report(d)
    assert "85% confidence interval" not in text
    assert 'NOT a calibrated confidence' in text
    assert 'block bootstrap' in text and 'behind the leads' in text


def _ink_run(dirpath):
    """A run the boundary tracker can work on: a dark ink disc (r=70) on
    paper, photographed at rest three times (baseline, 0.25 kV post and
    pre) and twice at 3 kV, grown to r=76 with a rippled interior."""
    import csv
    import cv2
    frames = _os.path.join(dirpath, 'frames')
    _os.makedirs(frames, exist_ok=True)
    yy, xx = np.mgrid[0:360, 0:640]
    rows = []
    specs = (('baseline', 0.0, 70, False), ('post-ramp', 0.25, 70, False),
             ('pre-ramp', 0.25, 70, False), ('post-ramp', 3.0, 76, True),
             ('pre-ramp', 3.0, 76, True))
    for k, (tag, kv, r, ripple) in enumerate(specs):
        img = np.full((360, 640), 190.0, np.float32)
        disc = (xx - 320) ** 2 + (yy - 180) ** 2 <= r * r
        img[disc] = 172.0
        if ripple:
            img[disc] += 6.0 * np.sin((xx[disc] + yy[disc]) / 2.5)
        img += np.random.default_rng(40 + k).normal(0, 1.5, img.shape)
        fn = f'SLDEA_s{k:02d}_{kv:05.2f}kV_{tag}.png'
        cv2.imwrite(_os.path.join(frames, fn),
                    np.clip(img, 0, 255).astype(np.uint8))
        rows.append({'step': (k + 1) // 2, 'tag': tag, 'nominal_kV': kv,
                     'frame_file': fn})
    with open(_os.path.join(dirpath, 'data.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['step', 'tag', 'nominal_kV',
                                          'frame_file'])
        w.writeheader()
        w.writerows(rows)
    with open(_os.path.join(dirpath, 'setup.txt'), 'w') as f:
        f.write("SLDEA Test -- synthetic\nDEA nominal diameter: 16 mm\n")
    return dirpath


def test_report_states_what_the_tracker_reads_at_rest():
    """2026-10-02: every disc-fit area is a ratio to the rays the tracker
    measures on the baseline frame. The report has one 'tracker at
    rest' line with the facts a Save stamps into setup.txt: how many
    rays found the edge, the hidden share, their one-sidedness, and the
    ellipse/circle offset the old estimator read on the resting disc.
    A run with no resting disc claims nothing."""
    import sldea_edge as se
    root = tempfile.mkdtemp(prefix='diag_rest_')
    d = sd.analyze(_ink_run(_os.path.join(root, 'SLDEA_k')))
    rest = d['tracker_rest']
    assert rest and tuple(rest) == se.STAMP_KEYS[1:], rest
    assert rest['base_rays'] >= 300, rest           # no leads: all round
    assert rest['base_hidden_pct'] < 20.0, rest
    assert rest['base_one_sided'] < 0.2, rest
    assert abs(rest['base_ellipse_over_circle'] - 1.0) < 0.02, rest
    a0 = d['baseline_disc']['area_px']
    by_kv = {}
    for p in d['frames']:
        by_kv.setdefault(p['kv'], []).append(p)
    assert all(p['method'] == 'disc-fit' for p in by_kv[0.25] + by_kv[3.0])
    for p in by_kv[0.25]:
        assert abs(p['area_px'] / a0 - 1.0) < 0.01, p['area_px'] / a0
    for p in by_kv[3.0]:
        assert abs(p['area_px'] / a0 - (76 / 70) ** 2) < 0.03, \
            p['area_px'] / a0
    text = sd.report(d)
    line = [ln for ln in text.splitlines() if ln.startswith('tracker at rest')]
    assert len(line) == 1, line
    assert f"{rest['base_rays']} of 360 rays find the ink edge" in line[0]
    # the share is 1 - base_rays/360: leads, foil AND faint-ink rays, so
    # the line must not call all of it 'hidden' (review 2026-10-02)
    assert '% of the perimeter not usable' in line[0], line
    assert 'no ink step' in line[0], line
    assert 'perimeter hidden' not in line[0], line
    assert 'one-sidedness' in line[0] and 'ellipse/circle' in line[0], line
    assert 'old area method' in line[0], line
    text.encode('ascii')
    # no resting disc, no line: nothing is claimed about a tracker
    # that never ran
    bare = sd.report(sd.analyze(sd._synth_run(
        _os.path.join(root, 'SLDEA_w'), 'wrinkle')))
    assert 'tracker at rest' not in bare
    # a resting disc the tracker cannot measure says so
    d['tracker_rest'] = None
    assert 'tracker at rest : NO READING' in sd.report(d)


def test_report_is_ascii_so_a_cp1252_console_cannot_kill_it():
    """The bench and analysis consoles are cp1252, and report() goes both
    to stdout and to sldea_diag.txt written with the locale codec — so
    one non-ASCII character in one verdict takes the whole diagnostic
    down. It happened once with an arrow; the 2026-08-05 scale-gate
    wording brought it back with a ruler emoji in three verdicts, and
    `sldea_diag.py --selftest` crashed on this Windows box while the
    v1.1.0 manual was being built."""
    root = tempfile.mkdtemp(prefix='diag_ascii_')
    d = sd.analyze(sd._synth_run(_os.path.join(root, 'SLDEA_r'), 'wrinkle'))
    text = sd.report(d)
    text.encode('ascii')                      # raises if anything leaked
    # the substitutions stay readable rather than turning into '?'
    assert sd._ascii('a — b') == 'a -- b'
    assert sd._ascii('5 µA → ok') == '5 uA -> ok'
    assert sd._ascii('the \U0001f4cf anchor') == 'the ruler anchor'
    assert sd._ascii('area mm²') == 'area mm2'
    # anything unmapped still degrades instead of raising
    sd._ascii('☃').encode('ascii')


def test_analyze_reports_localization_and_scale_context():
    """Statistics said nothing while 83-100% of every detection sat on the
    electrodes and the px->mm scale was 1.5x off at conf 0.93 (bench
    2026-07-28). The report must carry both context numbers -- where the
    detection LANDED and what anchors the scale -- and say so plainly
    when the anchors are missing."""
    root = tempfile.mkdtemp(prefix='diag_loc_')
    d = sd.analyze(sd._synth_run(_os.path.join(root, 'SLDEA_l'), 'expand'))
    assert 'foil_pct' in d and 'baseline_disc' in d
    for p in d['frames']:
        assert 'foil_frac' in p and 'gain_paper' in p and 'method' in p
    # no foil in the synthetic scene: every detection is off-foil
    assert all((p['foil_frac'] or 0.0) == 0.0 for p in d['frames'])
    heads = [h.lower() for _s, h, _det in sd.verdicts(d)]
    assert any('off the electrodes' in h for h in heads), heads
    # the synthetic baseline holds no resting disc AND no manual anchor
    # is recorded -> the refusal must be reported, not papered over —
    # and worded for the scale-gate era: saved mm² comes from the manual
    # 📏 anchor, so 'no scale reference' is the honest verdict, not
    # 'falls back to the first accepted frame' (audit 2026-08-05)
    assert d['baseline_disc'] is None
    assert d.get('scale_anchor') is None
    assert any('no scale reference' in h for h in heads), heads
    # and the contact sheet leads with the baseline panel
    png = _os.path.join(root, 'cs.png')
    sd.contact_sheet(_os.path.join(root, 'SLDEA_l'), png, count=4)
    assert _os.path.exists(png)


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
