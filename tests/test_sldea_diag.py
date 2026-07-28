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


def test_report_renders_for_every_synthetic_run():
    root = tempfile.mkdtemp(prefix='diag_report_')
    d = sd.analyze(sd._synth_run(_os.path.join(root, 'SLDEA_r'), 'wrinkle'))
    text = sd.report(d)
    for want in ('VERDICTS', 'PER FRAME', 'sensor sigma', 'sep-T'):
        assert want in text, want


def _run():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
