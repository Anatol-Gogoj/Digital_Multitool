#!/usr/bin/env python3
"""Why won't this run tune? -- measurements on a real SLDEA run.

Point it at a run directory and it reports, in numbers, which of the known
failure modes is actually present. The tuner shows you what the detector
decided; this shows you WHY, and whether the detector is even looking at
the right signal.

    python sldea_diag.py RUNDIR [--out DIR] [--max-frames N] [--no-contact]
    python sldea_diag.py 1                      # bench shortcut
    python sldea_diag.py --selftest OUT.png     # synthetic, no run needed

Writes sldea_diag.txt / .json / .png / _contact.png next to the run (or
into --out) and prints the report. The JSON is data only -- small enough to
send. The contact sheet draws the detected outline on real frames across
the ramp: the numbers say whether a threshold CAN separate the active
area, that says whether the outline landed in the right place.

What it measures, and the failure each one pins down:

  REPEAT     the run's own control experiment. Two snapshots at the same
             nominal kV, seconds apart, hold the same scene in the same
             state -- whatever separates them is the instrument, not the
             device. If that floor is as large as the difference against
             the baseline, no threshold anywhere can work, and the fix is
             at capture time rather than in the detector.

  PHOTOMETRY the mean ROI difference as it stands, after the scalar
             norm_bg gain the detector applies, and after a gain+offset
             fit on matched quantiles. When the last is far below the
             first, the difference was mostly an exposure mismatch and
             never measured the device: thresholds then sit on a pedestal
             many sigma tall, and no setting can work. The lowest-voltage
             frame is the control -- nothing has activated there, so
             whatever it differs by is the artifact.

  DRIFT      phase correlation baseline->frame, and how much of the diff
             energy disappears once that shift is undone. candidates() has
             photometric normalization but NO geometric registration, so
             drift makes every hard edge in the scene ring in the absdiff
             -- outlines that hug the rig, "Rorschach" speckle. A large
             shift that registration cannot cash in is reported as what it
             is: an unconstrained estimate, not drift.

  FEATURE    separability (Otsu's between-class variance ratio, rescaled
             so one noise population reads 0) of three maps over the same
             ROI: raw absdiff, registered absdiff, and the dense wrinkle
             map (local Laplacian energy, frame vs baseline). Whichever
             separates best is what the detector SHOULD be segmenting.
             This is the decisive number when the DEA wrinkles without
             expanding: intensity differencing then has nothing to find,
             while texture does.

  TRANSFER   per-frame Otsu threshold across the run, and the area a
             single fixed threshold produces on every frame. The three
             "candidates" in candidates() are all multiples of one Otsu
             value, so when that value swings, one slider setting cannot
             serve baseline, mid and late frames of the same run.

  STEP       area vs threshold, swept. The 21x21 merge close bridges
             nearby patches and the largest contour then jumps, so area
             moves in steps -- the reason dragging a slider feels chaotic
             rather than gradual.

  GATE       ROI diff p99 vs min_diff per frame: which frames the honest
             no-change gate drops, and at what voltage.

  NOISE      the sensor's own sigma, from a 0 kV frame pair when the run
             has one, else from the static border band. Every threshold
             here is also printed in sigma, because a gray-level constant
             does not transfer between runs, cameras or exposures.

  Since 2026-07-29 the report also carries LOCALIZATION (foil% of each
  detection -- statistics looked fine while every outline sat on the
  electrodes), the BASELINE anchor (resting-disc trace and the mm/px it
  implies, with its own gates), per-frame ci% (the disc-fit's 85% CI on
  area -- a statistical statement, unlike conf, which is a
  review-ordering score), and CONSISTENCY (same-kV pair agreement and
  monotonicity, with pair reconciliation applied exactly as the GUI
  applies it before auto-accept).

Nothing is modified: the run's setup.txt is read, never written.
"""
import json
import os
import sys

import numpy as np

import sldea_edge as se

# Frame-level work is cheap, but the threshold sweep repeats the detector's
# morphology ~20x per frame, so it runs at the detector's own scale.
SWEEP_T = list(range(3, 46, 2))
# kV parsed locally rather than imported from sldea_tuner: that module
# applies the Tk font workaround on import, and this one never opens a
# window.


def _fkv(row):
    try:
        return float(row.get('nominal_kV') or row.get('nominal_kv') or 'nan')
    except (TypeError, ValueError):
        return float('nan')


def _roi(shape, roi_frac):
    """The detector's central search window, as slices."""
    h, w = shape
    rf = min(1.0, max(0.2, float(roi_frac)))
    y0, x0 = int(h * (1 - rf) / 2), int(w * (1 - rf) / 2)
    return (slice(y0, h - y0 if y0 else h),
            slice(x0, w - x0 if x0 else w))


# Otsu's eta for a SINGLE Gaussian is exactly 2/pi: split at the mean, the
# two halves sit +-0.7979 sigma apart, so between-class variance is 0.6366
# of the total. Pure noise therefore scores 0.64, not 0, and raw eta values
# are almost all floor. Everything here is reported above that floor.
ETA_FLOOR = 2.0 / np.pi


def separability(vals):
    """How cleanly does this map split into two populations? 0..1.

    Otsu's eta (between-class / total variance) rescaled so that a single
    noise population reads 0 and two clean populations approach 1. It is
    exactly what a threshold-and-contour detector needs and cannot
    manufacture: near 0, no threshold separates active from inactive and
    every slider setting is a different arbitrary cut through one blob."""
    v = np.asarray(vals, np.float64).ravel()
    v = v[np.isfinite(v)]
    if v.size < 64 or v.max() <= v.min():
        return 0.0
    hist, edges = np.histogram(v, bins=128)
    p = hist / float(hist.sum())
    centers = 0.5 * (edges[1:] + edges[:-1])
    omega = np.cumsum(p)
    mu = np.cumsum(p * centers)
    mu_t = mu[-1]
    with np.errstate(divide='ignore', invalid='ignore'):
        sb = (mu_t * omega - mu) ** 2 / (omega * (1.0 - omega))
    total = float((((centers - mu_t) ** 2) * p).sum())
    if total <= 0:
        return 0.0
    eta = float(np.nan_to_num(sb).max() / total)
    return max(0.0, (eta - ETA_FLOOR) / (1.0 - ETA_FLOOR))


# One definition, in the module the detector itself uses -- since
# 2026-07-28 candidates() SEGMENTS this map (the tex-ratio channel), so
# the diagnostic must measure exactly the energy the detector cuts.
texture_map = se.texture_energy


# One definition, in the module the detector itself uses -- the diagnostic
# must measure exactly the correction candidates() applies.
photometric_fit = se.photometric_fit


def norm_bg_scale(base, img, roi_frac):
    """The scalar gain candidates() actually applies (sldea_edge, norm_bg):
    border-band median ratio, clamped. Reproduced here so the report can
    say what the shipping correction leaves behind."""
    h, w = base.shape
    rf = min(1.0, max(0.2, float(roi_frac)))
    by, bx = int(h * (1 - rf) / 2), int(w * (1 - rf) / 2)
    if not (by and bx):
        return 1.0
    band = np.ones(base.shape, bool)
    band[by:h - by, bx:w - bx] = False
    med_i = float(np.median(img[band])) or 1.0
    med_b = float(np.median(base[band]))
    return min(1.4, max(0.7, med_b / med_i))


def _detector_diff(base, img, settings):
    """The exact map candidates() thresholds, ROI-cropped and normalized.
    Via sldea_edge so the two can never drift apart."""
    return se.prepared_diff(base, img, settings)['sub']


def _foil_fraction(cand, foil):
    """Fraction of a candidate's filled outline lying on the foil strips.

    THE localization number: statistics on the diff said nothing while
    83-100% of every detection sat on the electrodes (bench 2026-07-28).
    None when there is no detection to locate; 0.0 when the scene has no
    foil."""
    import cv2
    if cand is None:
        return None
    if foil is None or not foil.any():
        return 0.0
    m = np.zeros(foil.shape, np.uint8)
    cv2.drawContours(m, [np.asarray(cand['contour'], np.int32)], -1, 1, -1)
    denom = int((m > 0).sum())
    if not denom:
        return None
    return float((foil & (m > 0)).sum()) / denom


def drift(base, img):
    """Phase-correlate baseline->frame. Returns (dx, dy, response, aligned).

    Sub-pixel and global, so it measures rig/camera movement rather than
    the membrane deformation we are trying to detect."""
    import cv2
    # COPIES, not views: given a window, phaseCorrelate multiplies it into
    # its inputs IN PLACE whenever the frame needs no DFT padding (OpenCV
    # aliases padded1 to src1). Passing the caller's arrays leaves a
    # Hanning-darkened baseline behind, and every later measurement in this
    # module then reads a corrupted reference.
    b = np.array(base, np.float32)
    f = np.array(img, np.float32)
    win = cv2.createHanningWindow((b.shape[1], b.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(b, f, win)
    # ...and warp the ORIGINAL frame, never `f`: the call above just left
    # the Hanning window baked into it, and aligning that against an
    # untouched baseline reports a residual many times the raw one.
    m = np.float32([[1, 0, -dx], [0, 1, -dy]])
    aligned = cv2.warpAffine(np.array(img, np.float32), m,
                             (b.shape[1], b.shape[0]),
                             flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE)
    return float(dx), float(dy), float(resp), aligned


def noise_sigma(base, frames, roi_frac):
    """Sensor sigma in gray levels, best estimate available.

    A 0 kV frame pair sees only sensor noise, so it is the honest estimate
    (the pair difference carries 2*sigma^2, hence the sqrt(2)). Failing
    that, the border band outside the ROI is static holder -- an upper
    bound, since drift and lighting land in it too."""
    def mad_sigma(d):
        return float(1.4826 * np.median(np.abs(d - np.median(d)))
                     / np.sqrt(2.0))

    zeros = [f for f in frames if not np.isnan(f['kv']) and f['kv'] <= 0.01]
    if zeros:
        return mad_sigma(zeros[0]['gray'] - base), 'baseline pair'
    h, w = base.shape
    rf = min(1.0, max(0.2, float(roi_frac)))
    by, bx = int(h * (1 - rf) / 2), int(w * (1 - rf) / 2)
    if not (by and bx) or not frames:
        return 1.0, 'assumed (no pair, no border band)'
    band = np.ones(base.shape, bool)
    band[by:h - by, bx:w - bx] = False
    d = frames[0]['gray'][band] - base[band]
    return mad_sigma(d), 'border band (upper bound)'


def _sweep_area(base, img, settings):
    """Area of the detector's merged largest region vs threshold, at the
    detector's own scale and with its own morphology."""
    import cv2
    h0, w0 = img.shape
    f = min(1.0, se.DETECT_MAX_W / float(w0))
    if f < 1.0:
        size = (se.DETECT_MAX_W, max(1, int(round(h0 * f))))
        img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
        base = cv2.resize(base, size, interpolation=cv2.INTER_AREA)
    k = int(settings.get('blur_px', 5)) | 1
    diff = cv2.GaussianBlur(cv2.absdiff(img, base).astype(np.uint8), (k, k), 0)
    ys, xs = _roi(diff.shape, settings.get('roi_frac', 0.85))
    sub = diff[ys, xs]
    out = []
    for t in SWEEP_T:
        _t, m = cv2.threshold(sub, float(t), 255, cv2.THRESH_BINARY)
        c = se._region_candidate(m, 'sweep')
        out.append(0.0 if c is None else float(c['area_px']) / (f * f))
    return out


def _seconds_between(row_a, row_b):
    """Wall-clock gap from the CSV timestamps, or None."""
    import datetime as _dt
    try:
        ta = _dt.datetime.fromisoformat((row_a.get('timestamp') or '').strip())
        tb = _dt.datetime.fromisoformat((row_b.get('timestamp') or '').strip())
        return round(abs((tb - ta).total_seconds()), 2)
    except (TypeError, ValueError):
        return None


def repeat_pairs(run, base_shape, roi_frac, limit=40):
    """Frames that should look ALIKE, and how much they actually differ.

    The run itself carries the control experiment: two snapshots at the
    same nominal kV, seconds apart, contain the same scene in the same
    state. Whatever separates them is instrumentation -- exposure, gain,
    white balance, focus -- and not the device. Compare that floor against
    how far each frame sits from the baseline and you know immediately
    whether the baseline difference carries any device signal at all.

    Same-voltage pairs are used when the run has them (the pre-ramp /
    post-ramp snapshots of one step); otherwise adjacent frames, where the
    voltage moved by one small step and the device cannot account for much.
    Streams two frames at a time, so a 1080p run costs no memory."""
    rows = run['rows']
    have = [i for i, r in enumerate(rows)
            if (r.get('frame_file') or '').strip()]
    same, adjacent = [], []
    for k in range(1, len(have)):
        i, j = have[k - 1], have[k]
        a, b = _fkv(rows[i]), _fkv(rows[j])
        if not np.isnan(a) and not np.isnan(b) and abs(a - b) < 1e-6:
            same.append((i, j))
        else:
            adjacent.append((i, j))
    pairs = same or adjacent
    kind = 'same voltage' if same else 'adjacent step'
    dropped = max(0, len(pairs) - limit)
    pairs = pairs[:limit]

    ys, xs = _roi(base_shape, roi_frac)
    out, prev_idx, prev = [], None, None
    for i, j in pairs:
        if prev_idx != i:
            prev = se.load_gray(se.frame_path(run, rows[i]) or '')
            prev_idx = i
        cur = se.load_gray(se.frame_path(run, rows[j]) or '')
        if prev is None or cur is None or prev.shape != base_shape \
                or cur.shape != base_shape:
            continue
        a, b = photometric_fit(prev, cur, (ys, xs))
        out.append({
            'row_a': i, 'row_b': j,
            'kv_a': _fkv(rows[i]), 'kv_b': _fkv(rows[j]),
            'seconds': _seconds_between(rows[i], rows[j]),
            'diff_mean': round(float(np.abs(cur[ys, xs]
                                            - prev[ys, xs]).mean()), 2),
            'diff_mean_photofit': round(float(np.abs(
                (a * prev[ys, xs] + b) - cur[ys, xs]).mean()), 2),
            'gain': round(a, 3),
        })
        prev, prev_idx = cur, j
    return {'kind': kind, 'dropped': dropped, 'pairs': out}


def analyze(rundir, max_frames=24):
    """Every measurement, as plain data (JSON-serializable)."""
    import cv2
    run = se.load_run(rundir)
    settings = se.load_settings(rundir)
    rows = run['rows']
    base_i = next((i for i, r in enumerate(rows)
                   if (r.get('tag') or '') == 'baseline'), 0)
    base = se.load_gray(se.frame_path(run, rows[base_i]) or '')
    if base is None:
        raise SystemExit(f"baseline frame not loadable in {rundir} -- the "
                         f"tuner would silently use another frame as the "
                         f"difference reference, and every outline would "
                         f"be wrong")

    idx = [i for i, r in enumerate(rows)
           if i != base_i and (r.get('frame_file') or '').strip()]
    if len(idx) > max_frames:                      # even coverage of the ramp
        picked = [idx[round(j * (len(idx) - 1) / (max_frames - 1.0))]
                  for j in range(max_frames)]
        # ...plus each pick's same-kV partner: the pre/post pair is the
        # run's own control, and ramp consistency cannot be judged on one
        # member of it
        by_kv = {}
        for i in idx:
            kv = _fkv(rows[i])
            if not np.isnan(kv):
                by_kv.setdefault(kv, []).append(i)
        for i in list(picked):
            kv = _fkv(rows[i])
            if not np.isnan(kv):
                picked.extend(by_kv.get(kv, []))
        idx = sorted(set(picked))

    frames = []
    for i in idx:
        gray = se.load_gray(se.frame_path(run, rows[i]) or '')
        if gray is None or gray.shape != base.shape:
            continue
        frames.append({'idx': i, 'kv': _fkv(rows[i]), 'gray': gray,
                       'file': (rows[i].get('frame_file') or '').strip()})
    if not frames:
        raise SystemExit(f"no frames the same size as the baseline in "
                         f"{rundir}")

    roi_frac = settings.get('roi_frac', 0.85)
    sigma, sigma_src = noise_sigma(base, frames, roi_frac)
    sigma = max(sigma, 0.05)
    ys, xs = _roi(base.shape, roi_frac)
    tex_base = texture_map(base)
    # where the electrodes are, where the resting disc is, and the paper
    # left between them -- the localization context every per-frame
    # number below is judged against
    foil = se.foil_mask(base)
    disc_ref = se.baseline_disc(base, settings)
    paper = se._paper_mask(base, base.shape, settings)
    k = int(settings.get('blur_px', 5)) | 1
    per = []
    cands_store = {}
    prev_m = None
    for fr in frames:
        dx, dy, resp, aligned = drift(base, fr['gray'])
        raw = cv2.absdiff(fr['gray'], base)
        reg = cv2.absdiff(aligned, base)
        blurred = cv2.GaussianBlur(raw.astype(np.uint8), (k, k), 0)
        tex = texture_map(fr['gray']) / np.maximum(tex_base, 1e-3)
        r_roi, g_roi, t_roi = raw[ys, xs], reg[ys, xs], tex[ys, xs]
        a, b = photometric_fit(base, fr['gray'], (ys, xs))
        ap, _bp = photometric_fit(base, fr['gray'], (ys, xs), mask=paper)
        aff = np.abs((a * base[ys, xs] + b) - fr['gray'][ys, xs])
        nb = norm_bg_scale(base, fr['gray'], roi_frac)
        nbr = np.abs(np.clip(fr['gray'][ys, xs] * nb, 0, 255) - base[ys, xs])
        cands = se.candidates(base, fr['gray'], settings,
                              prev_method=prev_m)
        best = cands[0] if cands else None
        if best:
            prev_m = best['method']
        cands_store[fr['idx']] = cands
        # A/B the normalization the detector applies: the run's own setting
        # against the legacy scalar. One command then answers "did the
        # gain+offset fit actually change what gets detected", instead of
        # it being an argument about residuals.
        alt = dict(settings)
        alt['norm_bg'] = 1 if int(settings.get('norm_bg', 2) or 0) >= 2 else 2
        alt_cands = se.candidates(base, fr['gray'], alt)
        alt_best = alt_cands[0] if alt_cands else None
        # the gate and Otsu describe DETECTOR behaviour, so they are read
        # off the diff the detector actually thresholds -- normalized --
        # rather than the raw one
        norm = _detector_diff(base, fr['gray'], settings)
        gate_p99 = float(np.percentile(norm, 99))
        ff = _foil_fraction(best, foil)
        aud = se.audit_boundary(se.prepared_diff(base, fr['gray'],
                                                 settings), best, settings)
        per.append({
            'audit': aud,
            'gain': round(a, 3), 'offset': round(b, 2),
            'gain_paper': round(ap, 3),
            'foil_frac': None if ff is None else round(ff, 3),
            'method': best['method'] if best else '',
            'ci85_pct': (float(best['ci85_pct'])
                         if best and best.get('ci85_pct') is not None
                         else None),
            'alt_norm_bg': alt['norm_bg'],
            'alt_area_px': round(float(alt_best['area_px']), 0)
            if alt_best else 0.0,
            'alt_conf': float(alt_best['conf']) if alt_best else 0.0,
            'alt_needs_review': bool(se.needs_review(alt_cands, alt)),
            'diff_mean_photofit': round(float(aff.mean()), 2),
            'diff_mean_normbg': round(float(nbr.mean()), 2),
            'sep_photofit': round(separability(aff), 3),
            'idx': fr['idx'], 'kv': fr['kv'], 'file': fr['file'],
            'shift_px': round(float(np.hypot(dx, dy)), 2),
            'dx': round(dx, 2), 'dy': round(dy, 2),
            'pc_response': round(resp, 3),
            'diff_mean': round(float(r_roi.mean()), 2),
            'diff_mean_registered': round(float(g_roi.mean()), 2),
            'diff_p99': round(gate_p99, 2),
            'diff_p99_sigma': round(gate_p99 / sigma, 1),
            'gated': bool(gate_p99 < float(settings.get('min_diff', 10))),
            'otsu': round(float(cv2.threshold(
                norm, 0, 255,
                cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0]), 1),
            # p90, not median: the active region is a MINORITY of the ROI,
            # so a median reports the untouched surround and reads ~1.0 even
            # when the disc is visibly wrinkled
            'texture_ratio': round(float(np.percentile(t_roi, 90)), 3),
            'sep_intensity': round(separability(r_roi), 3),
            'sep_registered': round(separability(g_roi), 3),
            'sep_texture': round(separability(t_roi), 3),
            'area_px': round(float(best['area_px']), 0) if best else 0.0,
            'solidity': round(float(best['solidity']), 3) if best else 0.0,
            'conf': float(best['conf']) if best else 0.0,
            'needs_review': bool(se.needs_review(cands, settings)),
        })

    # the threshold sweep on the three highest-voltage frames: the ones a
    # human tunes on, and where a fixed threshold has to hold
    hot = sorted([p for p in per if not np.isnan(p['kv'])],
                 key=lambda p: p['kv'])[-3:] or per[-3:]
    by_idx = {fr['idx']: fr for fr in frames}
    sweeps = [{'idx': p['idx'], 'kv': p['kv'],
               'area': _sweep_area(base, by_idx[p['idx']]['gray'], settings)}
              for p in hot if p['idx'] in by_idx]

    repeats = repeat_pairs(run, base.shape, roi_frac)
    # pair reconciliation happens exactly where the GUI does it: after
    # detection, before the accept decision the report quotes
    recon = se.reconcile_pairs(rows, cands_store, settings)
    for p in per:
        cl = cands_store.get(p['idx'])
        if cl:
            p['conf'] = float(cl[0]['conf'])
            p['needs_review'] = bool(se.needs_review(cl, settings))
    res_best = {p['idx']: {'area_px': p['area_px']}
                for p in per if p['area_px']}
    cons_annos = se.ramp_consistency(rows, res_best)
    consistency = {
        'checked': len(res_best),
        'pairs_confirmed': recon['confirmed'],
        'pairs_capped': recon['capped'],
        'pair_mismatches': sum(1 for n in cons_annos.values()
                               if 'pair mismatch' in n),
        'dips': sum(1 for n in cons_annos.values() if 'area dip' in n),
        'annos': {str(k): v for k, v in sorted(cons_annos.items())},
    }
    ref_out = None
    if disc_ref is not None:
        ref_out = {kk: vv for kk, vv in disc_ref.items() if kk != 'contour'}
        ref_out['mm_per_px'] = round(float(settings['diam_mm'])
                                     / float(disc_ref['diam_px']), 5)
    return {'rundir': os.path.abspath(rundir),
            'repeats': repeats,
            'frames_analyzed': len(per), 'baseline_row': base_i,
            'frame_shape': list(base.shape), 'sigma': round(sigma, 2),
            'sigma_source': sigma_src, 'settings': dict(settings),
            'foil_pct': round(100.0 * float(foil.mean()), 1)
            if foil is not None else 0.0,
            'baseline_disc': ref_out, 'consistency': consistency,
            'sweep_thresholds': SWEEP_T, 'sweeps': sweeps, 'frames': per}


# ---------------------------------------------------------------------------
# verdicts
# ---------------------------------------------------------------------------

def _step_ratio(sweep):
    """Largest area jump between adjacent thresholds (x). >2 means the
    merge close is bridging, and the area is a step function of a slider."""
    a = [v for v in sweep if v > 0]
    return max((a[i] / max(a[i + 1], 1.0) for i in range(len(a) - 1)),
               default=1.0)


def verdicts(d):
    """[(severity, headline, detail)] -- the report's conclusions."""
    out = []
    per = d['frames']
    sigma = d['sigma']
    shifts = [p['shift_px'] for p in per]
    med_shift = float(np.median(shifts)) if shifts else 0.0
    drops = [1.0 - p['diff_mean_registered'] / max(p['diff_mean'], 1e-6)
             for p in per]
    med_drop = float(np.median(drops)) if drops else 0.0
    resp = [p['pc_response'] for p in per]
    med_resp = float(np.median(resp)) if resp else 0.0
    if med_resp < 0.05:
        out.append(('MED', 'The shift estimate itself is weak',
                    f"median phase-correlation response {med_resp:.3f}. "
                    f"These frames may be too featureless, or too unlike "
                    f"the baseline, for a global shift to be well "
                    f"determined -- read the drift line below as indicative "
                    f"and trust the registered-vs-raw diff energy instead."))
    if med_drop >= 0.15:
        out.append(('HIGH', 'Geometric drift is polluting the difference',
                    f"median shift {med_shift:.2f} px (max "
                    f"{max(shifts):.2f}); undoing it removes "
                    f"{100 * med_drop:.0f}% of the mean ROI diff energy. "
                    f"candidates() never registers, so that energy is being "
                    f"thresholded as if it were membrane change."))
    elif med_shift >= 1.0:
        # a large shift that registration cannot cash in is not a shift:
        # an elongated feature (electrode strips) leaves translation along
        # its own axis unobservable, and phase correlation returns noise
        # there. Reporting drift here would send the fix in a direction the
        # data does not support (bench runs P3_*, 2026-07-28).
        out.append(('MED', 'The measured shift is not a real translation',
                    f"median shift {med_shift:.2f} px, yet undoing it "
                    f"changes the diff energy by only "
                    f"{100 * med_drop:.0f}%. A true shift of that size "
                    f"would remove far more. Expect an elongated feature "
                    f"in frame whose long axis is unconstrained; registering"
                    f" on this estimate would not help."))
    else:
        out.append(('OK', 'Frames are geometrically stable',
                    f"median shift {med_shift:.2f} px, registration would "
                    f"remove only {100 * med_drop:.0f}% of the diff energy."))

    # the run's own control: frames that should look alike, and do not
    reps = (d.get('repeats') or {}).get('pairs') or []
    floor = float(np.median([r['diff_mean'] for r in reps])) if reps else None
    kind = (d.get('repeats') or {}).get('kind', '')
    if floor is not None and floor > 4 * sigma:
        secs = [r['seconds'] for r in reps if r['seconds'] is not None]
        when = f" {np.median(secs):.0f} s apart" if secs else ""
        fl_aff = float(np.median([r['diff_mean_photofit'] for r in reps]))
        out.append(('HIGH', 'Frames that should be identical are not',
                    f"{len(reps)} pairs at the {kind}{when} differ by "
                    f"{floor:.1f} gray levels ({floor / sigma:.0f} sigma) -- "
                    f"a gain+offset fit between the two takes that to "
                    f"{fl_aff:.1f}. The device cannot have changed between "
                    f"them, so this is the instrument, and no baseline "
                    f"difference smaller than it can be trusted."))

    # photometry: is the difference even measuring the device?
    raw = float(np.median([p['diff_mean'] for p in per]))
    aff = float(np.median([p['diff_mean_photofit'] for p in per]))
    nbg = float(np.median([p['diff_mean_normbg'] for p in per]))
    cold = min(per, key=lambda p: (1e9 if np.isnan(p['kv']) else p['kv']))
    if floor is not None and raw > 4 * sigma and floor > 0.7 * raw:
        out.append(('HIGH', 'The baseline difference carries no more signal '
                    'than two frames of the same thing',
                    f"median difference vs the baseline {raw:.1f} gray "
                    f"levels, against {floor:.1f} between frames that should "
                    f"be identical. Whatever the ramp does to the picture is "
                    f"smaller than the noise the camera adds between two "
                    f"snapshots -- tuning thresholds on this cannot work, "
                    f"and no amount of it will."))
    if raw > 4 * sigma and aff < 0.6 * raw:
        out.append(('HIGH', 'The difference is dominated by photometry, not '
                    'by the device',
                    f"median ROI difference {raw:.1f} gray levels "
                    f"({raw / sigma:.0f} sigma); a gain+offset fit leaves "
                    f"{aff:.1f}, while the scalar norm_bg correction the "
                    f"detector applies leaves {nbg:.1f}. At "
                    f"{cold['kv']:g} kV, where nothing has activated yet, "
                    f"the frames already differ by "
                    f"{cold['diff_mean'] / sigma:.0f} sigma. Every "
                    f"threshold is being set on that pedestal."))
    elif raw > 4 * sigma and cold['diff_mean'] > 4 * sigma:
        out.append(('HIGH', 'Something other than the device is changing',
                    f"at {cold['kv']:g} kV the ROI already differs by "
                    f"{cold['diff_mean'] / sigma:.0f} sigma, and a "
                    f"gain+offset fit does not explain it (leaves "
                    f"{aff:.1f} of {raw:.1f}). The scene itself is moving "
                    f"or changing between the baseline and the run."))

    # localization: every statistic above can look fine while the outline
    # sits on the wrong OBJECT -- which is what the frames exposed on the
    # P3 runs (83-100% of detected area on the strips, sep 0.000)
    ffs = [p.get('foil_frac') for p in per]
    ffs = [v for v in ffs if v is not None]
    if ffs:
        med_ff = float(np.median(ffs))
        n_hi = sum(1 for v in ffs if v > 0.5)
        if med_ff > 0.5:
            out.append(('HIGH', 'Detections sit on the electrodes, not the '
                        'device',
                        f"median {100 * med_ff:.0f}% of the detected area "
                        f"lies on the foil strips ({n_hi}/{len(ffs)} frames "
                        f"mostly foil). Whatever the residuals say, the "
                        f"detector is outlining the wrong object, and no "
                        f"threshold tuning fixes that."))
        elif n_hi:
            out.append(('MED', 'Some detections sit on the electrodes',
                        f"{n_hi}/{len(ffs)} detections are mostly foil "
                        f"(median {100 * med_ff:.0f}%). Check those frames "
                        f"on the contact sheet."))
        else:
            out.append(('OK', 'Detections stay off the electrodes',
                        f"median {100 * med_ff:.0f}% of detected area on "
                        f"foil across {len(ffs)} frames with a detection."))

    if 'baseline_disc' in d:
        ref = d.get('baseline_disc')
        if ref:
            out.append(('OK', 'px->mm is anchored on the resting disc',
                        f"baseline-disc diam {ref['diam_px']:.0f} px "
                        f"(circ {ref.get('circ', 0):.2f}, fill "
                        f"{ref.get('solidity', 0):.2f}, arc "
                        f"{ref.get('arc_cov', 0):.2f}, conf "
                        f"{ref.get('conf', 0):.2f}) -> "
                        f"{ref.get('mm_per_px', 0):.5f} mm/px. The blob "
                        f"trace this replaces read 896-951 px on these "
                        f"runs -- a 1.5-1.6x diameter error at conf 0.93."))
        else:
            out.append(('MED', 'No trustworthy resting-disc trace',
                        f"baseline_disc refused this baseline, so mm "
                        f"figures fall back to the first accepted frame "
                        f"-- an ACTIVATED region. Treat active_area_mm2 "
                        f"as uncalibrated until the baseline is fixed."))

    auds = [p.get('audit') for p in per]
    auds = [a for a in auds if a and a.get('bias_px') is not None]
    if auds:
        bias = float(np.median([a['bias_px'] for a in auds]))
        p95 = float(np.percentile([abs(a['bias_px']) for a in auds], 95))
        ns = float(np.median([a['nostep_pct'] for a in auds]))
        detail = (f"median signed offset fit-vs-step {bias:+.1f} px "
                  f"(p95 |offset| {p95:.1f}), median no-step arc "
                  f"{ns:.0f}% over {len(auds)} audited boundaries. ")
        if abs(bias) <= 2.0 and ns <= 10.0:
            out.append(('OK', 'Accepted boundaries sit on a real ink step',
                        detail + "Within the 2 px / 10% trust rule: not "
                        "noise, and no systematic feature bias."))
        else:
            out.append(('HIGH', 'Accepted boundaries fail the self-audit',
                        detail + "Past the 2 px / 10% rule -- a large "
                        "no-step arc means circled noise; a clean bias "
                        "means the wrong feature. Fix before labeling."))

    cons = d.get('consistency')
    if cons and cons.get('checked', 0) >= 4:
        nmm, nd = cons['pair_mismatches'], cons['dips']
        if nmm or nd:
            worst = next(iter(cons.get('annos', {}).values()), '')
            out.append(('MED', 'The ramp is not self-consistent',
                        f"{nmm} frames in mismatching same-kV pairs, {nd} "
                        f"area dips while the voltage rose (e.g. {worst}). "
                        f"The two snapshots of one step photograph the "
                        f"same state -- when their areas differ, the "
                        f"detection, not the device, changed."))
        else:
            out.append(('OK', 'The ramp is self-consistent',
                        f"same-kV pairs agree and the area never dips "
                        f"against a rising voltage across "
                        f"{cons['checked']} detected frames "
                        f"({cons.get('pairs_confirmed', 0)} pair-confirmed, "
                        f"{cons.get('pairs_capped', 0)} capped to review)."))

    si = float(np.median([p['sep_intensity'] for p in per]))
    sr = float(np.median([p['sep_registered'] for p in per]))
    st = float(np.median([p['sep_texture'] for p in per]))
    best = max((si, 'raw absdiff'), (sr, 'registered absdiff'),
               (st, 'wrinkle map'))
    if best[0] < 0.25:
        out.append(('HIGH', 'No map here separates at all',
                    f"best separability {best[0]:.2f} ({best[1]}), where 0 "
                    f"is indistinguishable from one noise population. No "
                    f"threshold can split active from inactive on these "
                    f"frames -- every slider setting is a different "
                    f"arbitrary cut, which is the Rorschach result."))
    elif st > max(si, sr) * 1.25:
        out.append(('HIGH', 'Texture separates; intensity difference does '
                    'not',
                    f"separability -- wrinkle map {st:.2f} vs absdiff "
                    f"{si:.2f} (registered {sr:.2f}). The active area is "
                    f"visible as a texture change and barely as a "
                    f"displacement, which is why no threshold on the diff "
                    f"works. The detector is segmenting the wrong map."))
    else:
        out.append(('OK', f'Best feature is the {best[1]}',
                    f"separability {best[0]:.2f} (absdiff {si:.2f}, "
                    f"registered {sr:.2f}, wrinkle {st:.2f})."))

    ot = [p['otsu'] for p in per if p['otsu'] > 0]
    if ot and max(ot) / max(min(ot), 1e-6) >= 2.0:
        lo_s, hi_s = min(ot) / sigma, max(ot) / sigma
        out.append(('HIGH', 'One threshold cannot serve this run',
                    f"per-frame Otsu ranges {min(ot):.0f}..{max(ot):.0f} "
                    f"gray levels ({lo_s:.1f}..{hi_s:.1f} sigma). Every "
                    f"candidate tier is a multiple of that one number, so a "
                    f"setting tuned on one frame is a different cut on the "
                    f"next."))
    elif ot:
        out.append(('OK', 'Per-frame Otsu is stable',
                    f"{min(ot):.0f}..{max(ot):.0f} gray levels."))

    steps = [_step_ratio(s['area']) for s in d['sweeps']]
    if steps and max(steps) >= 2.0:
        out.append(('MED', 'Area is a step function of the threshold',
                    f"largest jump between adjacent sweep thresholds is "
                    f"{max(steps):.1f}x. The 21x21 merge close bridges "
                    f"patches and the largest contour jumps -- why dragging "
                    f"a slider feels chaotic instead of gradual."))

    gated = [p for p in per if p['gated']]
    hot_gated = [p for p in gated if not np.isnan(p['kv']) and p['kv'] > 0]
    if hot_gated:
        kvs = ', '.join(f"{p['kv']:g}" for p in hot_gated[:6])
        md = float(d['settings'].get('min_diff', 0))
        out.append(('MED', 'The no-change gate is dropping energised frames',
                    f"{len(gated)}/{len(per)} frames gated, including "
                    f"{kvs} kV. min_diff is {md:g} gray levels = "
                    f"{md / sigma:.1f} sigma."))

    # A/B: did switching the normalization change what gets DETECTED?
    alt_mode = per[0].get('alt_norm_bg')
    if alt_mode is not None:
        now = int(d['settings'].get('norm_bg', 2) or 0)
        rev_now = sum(1 for p in per if p['needs_review'])
        rev_alt = sum(1 for p in per if p['alt_needs_review'])
        names = {0: 'no normalization', 1: 'the legacy scalar',
                 2: 'the gain+offset fit'}
        conf_now = float(np.median([p['conf'] for p in per]))
        conf_alt = float(np.median([p['alt_conf'] for p in per]))
        sev = 'OK' if rev_now < rev_alt or conf_now > conf_alt else 'MED'
        out.append((sev, f'Detector under {names.get(now, now)} vs '
                    f'{names.get(alt_mode, alt_mode)}',
                    f"frames needing review {rev_now}/{len(per)} against "
                    f"{rev_alt}/{len(per)}; median confidence "
                    f"{conf_now:.2f} against {conf_alt:.2f}. This is the "
                    f"only comparison that matters -- residuals are the "
                    f"means, detections are the end."))

    kv = np.array([p['kv'] for p in per], float)
    ar = np.array([p['area_px'] for p in per], float)
    ok = ~np.isnan(kv) & (ar > 0)
    if ok.sum() >= 3:
        order = np.argsort(kv[ok])
        a = ar[ok][order]
        back = float(np.sum(np.diff(a) < 0)) / max(len(a) - 1, 1)
        if back > 0.3:
            out.append(('MED', 'Detected area does not grow with voltage',
                        f"{100 * back:.0f}% of steps up the ramp go "
                        f"backwards. Each frame is detected independently, "
                        f"so nothing enforces the monotonicity the physics "
                        f"has."))
    return out


def report(d):
    """The human-readable report."""
    L = []
    A = L.append
    A("=" * 74)
    A(f"SLDEA run diagnostic -- {os.path.basename(d['rundir'])}")
    A("=" * 74)
    A(f"frames analyzed : {d['frames_analyzed']}  "
      f"({d['frame_shape'][1]}x{d['frame_shape'][0]} px)")
    A(f"sensor sigma    : {d['sigma']:.2f} gray levels  [{d['sigma_source']}]")
    s = d['settings']
    A(f"run settings    : min_diff {s.get('min_diff')}  "
      f"diff_thresh {s.get('diff_thresh')}  blur_px {s.get('blur_px')}  "
      f"min_solidity {s.get('min_solidity')}  roi_frac {s.get('roi_frac')}  "
      f"tex_seg {s.get('tex_seg')}")
    if 'foil_pct' in d:
        A(f"electrodes      : texture footprint covers {d['foil_pct']:.1f}% "
          f"of the frame")
    if 'baseline_disc' in d:
        ref = d.get('baseline_disc')
        if ref:
            A(f"resting disc    : diam {ref['diam_px']:.0f} px  centre "
              f"({ref['cx']:.0f},{ref['cy']:.0f})  circ "
              f"{ref.get('circ', 0):.2f}  fill {ref.get('solidity', 0):.2f}"
              f"  conf {ref.get('conf', 0):.2f}  ->  "
              f"{ref.get('mm_per_px', 0):.5f} mm/px")
        else:
            A("resting disc    : NOT FOUND (baseline_disc refused -- mm "
              "figures fall back to an activated frame)")
    A("")
    A("VERDICTS")
    A("-" * 74)
    for sev, head, detail in verdicts(d):
        A(f"[{sev:4}] {head}")
        for line in _wrap(detail, 66):
            A(f"        {line}")
    reps = (d.get('repeats') or {}).get('pairs') or []
    if reps:
        kind = d['repeats'].get('kind', '')
        A("")
        A(f"REPEATABILITY  ({len(reps)} pairs at the {kind} -- the run's "
          f"own control)")
        A("-" * 74)
        fl = float(np.median([r['diff_mean'] for r in reps]))
        fa = float(np.median([r['diff_mean_photofit'] for r in reps]))
        secs = [r['seconds'] for r in reps if r['seconds'] is not None]
        A(f"  median difference between frames that should look alike: "
          f"{fl:.2f} gray levels ({fl / d['sigma']:.0f} sigma)")
        A(f"  after a gain+offset fit between the two:                  "
          f"{fa:.2f}")
        if secs:
            A(f"  typical gap between them: {np.median(secs):.1f} s")
        A(f"  worst pair: {max(r['diff_mean'] for r in reps):.2f}   "
          f"best pair: {min(r['diff_mean'] for r in reps):.2f}   "
          f"fitted gain spread: "
          f"{min(r['gain'] for r in reps):.3f}.."
          f"{max(r['gain'] for r in reps):.3f}")
        A("  The device cannot change between these, so this is the floor")
        A("  under every number below it.")
        if d['repeats'].get('dropped'):
            A(f"  ({d['repeats']['dropped']} further pairs not measured)")
    A("")
    A("PER FRAME")
    A("-" * 74)
    A(f"{'kV':>6} {'shift':>6} {'pcr':>5} {'diff':>6} {'d-nbg':>6} "
      f"{'d-aff':>6} {'gain':>5} {'g-pap':>6} {'otsu':>5} {'sep-I':>6} "
      f"{'sep-A':>6} {'sep-T':>6} {'tex':>5} {'foil%':>6} {'ci%':>5} "
      f"{'area':>8} {'rev':>4}  method")
    for p in d['frames']:
        kv = '?' if np.isnan(p['kv']) else f"{p['kv']:.2f}"
        ff = ('     -' if p.get('foil_frac') is None
              else f"{100 * p['foil_frac']:>6.0f}")
        ci = ('    -' if p.get('ci85_pct') is None
              else f"{p['ci85_pct']:>5.2f}")
        A(f"{kv:>6} {p['shift_px']:>6.2f} {p['pc_response']:>5.2f} "
          f"{p['diff_mean']:>6.2f} {p['diff_mean_normbg']:>6.2f} "
          f"{p['diff_mean_photofit']:>6.2f} {p['gain']:>5.2f} "
          f"{p.get('gain_paper', float('nan')):>6.2f} "
          f"{p['otsu']:>5.0f} {p['sep_intensity']:>6.2f} "
          f"{p['sep_photofit']:>6.2f} {p['sep_texture']:>6.2f} "
          f"{p['texture_ratio']:>5.2f} {ff} {ci} "
          f"{p['area_px']:>8.0f} {'yes' if p['needs_review'] else 'no':>4}"
          f"  {p.get('method', '')}"
          + ('  GATED' if p['gated'] else ''))
    A("")
    A("  shift  px of rig/camera movement vs the baseline (phase corr.);")
    A("         pcr is that estimate's response -- below ~0.05, distrust it")
    A("  diff   mean ROI |frame-baseline|; d-nbg after the scalar norm_bg")
    A("         correction the detector applies; d-aff after a gain+offset")
    A("         fit. If d-aff is far below diff, the difference was mostly")
    A("         photometry -- not the device. gain is that fit's slope;")
    A("         g-pap is the same fit restricted to the paper background")
    A("         (what norm_bg 2 actually applies since 2026-07-28).")
    A("  sep-I/A/T  separability of the raw / photometry-corrected absdiff")
    A("             and the wrinkle map: 0 = one noise population (no")
    A("             threshold splits it), 1 = two clean ones. Highest wins.")
    A("  tex    wrinkle-energy ratio at the ROI p90 (1.0 = no texture "
      "change)")
    A("  foil%  fraction of the detected area lying on the electrode")
    A("         strips -- the localization number; method is the winning")
    A("         candidate tier ('disc-fit' = the ink-edge boundary")
    A("         tracker, 'tex-ratio' = the texture channel, 'resting' =")
    A("         gated frame stated at the known resting area)")
    A("  ci%    the disc-fit's own 85% confidence interval on area, from")
    A("         the edge-point scatter -- a statistical statement, unlike")
    A("         conf, which is a quality score")
    A("  area   what candidates() detects with the run's own settings;")
    A("         the A/B verdict above compares that against the other")
    A("         normalization mode, on the same frames")
    return "\n".join(L)


def _wrap(text, width):
    words, line, out = text.split(), '', []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out


def figure(d, png, rundir=None):
    """Six panels: the three maps of the hottest frame, then drift,
    thresholds and the area sweep."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import cv2

    fig, axs = plt.subplots(2, 3, figsize=(16, 9))
    per = d['frames']
    kv = [p['kv'] for p in per]

    hot = max(per, key=lambda p: (-1e9 if np.isnan(p['kv']) else p['kv']))
    drawn = False
    if rundir:
        run = se.load_run(rundir)
        rows = run['rows']
        base = se.load_gray(se.frame_path(run, rows[d['baseline_row']]) or '')
        img = se.load_gray(os.path.join(run['frames_dir'], hot['file']))
        if base is not None and img is not None and base.shape == img.shape:
            ys, xs = _roi(base.shape, d['settings'].get('roi_frac', 0.85))
            a, b = photometric_fit(base, img, (ys, xs))
            tex = texture_map(img) / np.maximum(texture_map(base), 1e-3)
            for ax, (m, t) in zip(axs[0], [
                    (cv2.absdiff(img, base), 'raw absdiff'),
                    (np.abs((a * base + b) - img),
                     'absdiff after gain+offset fit'),
                    (np.clip(tex, 0, 3), 'wrinkle map (texture ratio)')]):
                ax.imshow(m, cmap='magma')
                ax.set_title(f"{t}\n{hot['kv']:g} kV", fontsize=9)
                ax.set_xticks([])
                ax.set_yticks([])
            drawn = True
    if not drawn:
        for ax in axs[0]:
            ax.axis('off')

    ax = axs[1][0]
    ax.plot(kv, [p['diff_mean'] for p in per], 'o-', label='raw')
    ax.plot(kv, [p['diff_mean_normbg'] for p in per], 's-', label='norm_bg')
    ax.plot(kv, [p['diff_mean_photofit'] for p in per], '^-',
            label='gain+offset')
    ax.axhline(d['sigma'], ls=':', color='#444', lw=1)
    ax.annotate('1 sigma', (kv[0], d['sigma']), fontsize=7, va='bottom')
    reps = (d.get('repeats') or {}).get('pairs') or []
    if reps:
        fl = float(np.median([r['diff_mean'] for r in reps]))
        ax.axhline(fl, ls='--', color='#d81b60', lw=1.2)
        ax.annotate('identical-frame floor', (kv[0], fl), fontsize=7,
                    va='bottom', color='#d81b60')
    ax.set_title('difference energy -- what is left after correction',
                 fontsize=9)
    ax.set_xlabel('nominal kV')
    ax.set_ylabel('mean |diff| (gray levels)')
    ax.legend(fontsize=7, loc='upper left')
    tw = ax.twinx()
    tw.plot(kv, [p['shift_px'] for p in per], color='#bbb', lw=1, zorder=0)
    tw.set_ylabel('shift (px)', color='#999', fontsize=8)
    tw.tick_params(axis='y', colors='#999', labelsize=7)

    ax = axs[1][1]
    ax.plot(kv, [p['sep_intensity'] for p in per], 'o-', label='absdiff')
    ax.plot(kv, [p['sep_registered'] for p in per], 's-', label='registered')
    ax.plot(kv, [p['sep_photofit'] for p in per], 'd-', label='gain+offset')
    ax.plot(kv, [p['sep_texture'] for p in per], '^-', label='wrinkle')
    ax.set_title('Otsu separability -- which map can be thresholded',
                 fontsize=9)
    ax.set_xlabel('nominal kV')
    ax.set_ylabel('eta')
    ax.legend(fontsize=7)

    ax = axs[1][2]
    for s in d['sweeps']:
        ax.plot(d['sweep_thresholds'], s['area'], 'o-',
                label=f"{s['kv']:g} kV" if not np.isnan(s['kv']) else '?')
    ax.set_yscale('symlog')
    ax.set_title('detected area vs threshold (steps = merge close)',
                 fontsize=9)
    ax.set_xlabel('diff threshold (gray levels)')
    ax.set_ylabel('area (px^2)')
    ax.legend(fontsize=7)

    for ax in axs[1]:
        ax.grid(alpha=0.25)
    fig.suptitle(f"SLDEA diagnostic -- {os.path.basename(d['rundir'])}",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(png, dpi=95)
    plt.close(fig)


# ---------------------------------------------------------------------------
# selftest: a run that expands, and a run that only wrinkles
# ---------------------------------------------------------------------------

def _synth_run(dirpath, mode, shift=0.0, gain=1.0, offset=0.0,
               jitter=0.0):
    """Synthesise a run. mode 'expand' grows a brighter disc (the case
    difference-imaging was designed for); mode 'wrinkle' keeps the disc the
    same mean brightness and adds ridges instead -- the case the bench
    reports, where the DEA barely expands."""
    import csv
    import cv2
    frames = os.path.join(dirpath, 'frames')
    os.makedirs(frames, exist_ok=True)
    cols = ['step', 'tag', 'nominal_kV', 'frame_file']
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0:240, 0:320]

    def make(r, kv, wrinkle):
        img = np.full((240, 320), 90.0, np.float32)
        # the rig: structure on BOTH axes, or phase correlation has nothing
        # to constrain the shift along the missing one and returns noise
        img[np.abs(xx - 20) < 6] = 230.0
        img[np.abs(yy - 18) < 5] = 215.0
        m = (xx - 160) ** 2 + (yy - 120) ** 2 <= r * r
        if wrinkle:
            img[m] += 26 * np.sin((xx[m] + yy[m]) / 2.2)
        else:
            img[m] += 34
        img += rng.normal(0, 1.6, img.shape)
        if kv > 0 and (gain != 1.0 or offset):
            img = img * gain + offset
        if kv > 0 and shift:
            m2 = np.float32([[1, 0, shift], [0, 1, shift * 0.5]])
            img = cv2.warpAffine(img, m2, (320, 240),
                                 borderMode=cv2.BORDER_REPLICATE)
        return np.clip(img, 0, 255).astype(np.uint8)

    rows = []
    step = 0
    for k, kv in enumerate([0.0, 2.0, 4.0, 6.0]):
        # with jitter, every voltage is snapshotted TWICE (pre-ramp and
        # post-ramp, as the real tab does) and each snapshot gets its own
        # gain -- the hypothesis that the camera re-converges its exposure
        # on every grab, which makes two pictures of one unchanged scene
        # differ. Those pairs are the run's own control.
        reps = 2 if (jitter and k) else 1
        for r in range(reps):
            if k == 0:
                im = make(0, 0.0, False)
            elif mode == 'expand':
                im = make(25 + 9 * k, kv, False)
            else:
                im = make(60, kv, True)      # same size every step
            if jitter and k:
                g = 1.0 + float(rng.normal(0, jitter))
                im = np.clip(im.astype(np.float32) * g, 0,
                             255).astype(np.uint8)
            tag = ('baseline' if k == 0 else
                   ('pre-ramp' if r == 0 else 'post-ramp'))
            fn = f'SLDEA_s{step:02d}_{kv:05.2f}kV_{tag}.png'
            cv2.imwrite(os.path.join(frames, fn), im)
            rows.append({'step': step, 'tag': tag, 'nominal_kV': kv,
                         'frame_file': fn})
            step += 1
    with open(os.path.join(dirpath, 'data.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return dirpath


def _selftest(out_png):
    import tempfile
    root = tempfile.mkdtemp(prefix='sldea_diag_selftest_')

    exp = _synth_run(os.path.join(root, 'SLDEA_expand'), 'expand')
    d1 = analyze(exp)
    assert d1['frames_analyzed'] == 3, d1['frames_analyzed']
    si = np.median([p['sep_intensity'] for p in d1['frames']])
    assert si > 0.3, f"expanding disc should separate on absdiff, got {si}"

    wr = _synth_run(os.path.join(root, 'SLDEA_wrinkle'), 'wrinkle')
    d2 = analyze(wr)
    tex = np.median([p['texture_ratio'] for p in d2['frames']])
    assert tex > 1.3, f"wrinkled disc should raise texture ratio, got {tex}"

    dr = _synth_run(os.path.join(root, 'SLDEA_drift'), 'expand', shift=3.0)
    d3 = analyze(dr)
    shifts = [p['shift_px'] for p in d3['frames']]
    assert min(shifts) > 1.5, f"3 px shift should be detected, got {shifts}"
    heads = [h for _s, h, _d in verdicts(d3)]
    assert any('drift' in h.lower() for h in heads), heads
    dropped = np.median([1 - p['diff_mean_registered'] / p['diff_mean']
                         for p in d3['frames']])
    assert dropped > 0.1, f"registration should cut diff energy, {dropped}"

    figure(d1, out_png, rundir=exp)
    print(report(d3))
    print(f"\nselftest OK -> {out_png}  (absdiff sep {si:.2f} on the "
          f"expanding run, texture ratio {tex:.2f} on the wrinkle-only run, "
          f"drift {min(shifts):.1f}-{max(shifts):.1f} px detected)")


def contact_sheet(rundir, png, count=8, max_frames=24):
    """A grid of real frames with the detected outline drawn on each.

    The numbers say whether a threshold CAN separate the active area; this
    says whether the outline is in the right place. An agent working on
    this can read the PNG directly, which is the check that no residual
    substitutes for."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    run = se.load_run(rundir)
    settings = se.load_settings(rundir)
    rows = run['rows']
    base_i = next((i for i, r in enumerate(rows)
                   if (r.get('tag') or '') == 'baseline'), 0)
    base = se.load_gray(se.frame_path(run, rows[base_i]) or '')
    if base is None:
        raise SystemExit(f"baseline frame not loadable in {rundir}")
    idx = [i for i, r in enumerate(rows)
           if i != base_i and (r.get('frame_file') or '').strip()]
    if not idx:
        raise SystemExit(f"no frames in {rundir}")
    if len(idx) > count:                      # even coverage of the ramp
        idx = sorted({idx[round(j * (len(idx) - 1) / (count - 1.0))]
                      for j in range(count)})

    panels = 1 + len(idx)                    # baseline panel leads
    cols = min(4, panels)
    rowsn = int(np.ceil(panels / cols))
    fig, axs = plt.subplots(rowsn, cols,
                            figsize=(4.2 * cols, 2.9 * rowsn), squeeze=False)
    for ax in axs.ravel():
        ax.axis('off')

    # Panel 0: the baseline with the resting-disc trace and the foil
    # footprint -- the two anchors (px→mm scale, electrode suppression)
    # every other panel's detection depends on. Drawing them is the check
    # that caught the 1.5x scale error no residual could see.
    import cv2 as _cv2
    ax0 = axs[0][0]
    ax0.imshow(base, cmap='gray', vmin=0, vmax=255)
    ax0.axis('off')
    foil = se.foil_mask(base)
    if foil is not None and foil.any():
        fc, _h = _cv2.findContours(foil.astype(np.uint8),
                                   _cv2.RETR_EXTERNAL,
                                   _cv2.CHAIN_APPROX_SIMPLE)
        for c in fc:
            pts = c.reshape(-1, 2)
            ax0.plot(np.append(pts[:, 0], pts[0, 0]),
                     np.append(pts[:, 1], pts[0, 1]),
                     lw=0.9, color='#ff9100')
    ref = se.baseline_disc(base, settings)
    head0 = "baseline"
    if ref is not None:
        pts = np.asarray(ref['contour'], float)
        ax0.plot(np.append(pts[:, 0], pts[0, 0]),
                 np.append(pts[:, 1], pts[0, 1]), lw=2.0, color='#00e676')
        head0 += (f"  disc {ref['diam_px']:.0f} px  circ "
                  f"{ref.get('circ', 0):.2f}  conf {ref.get('conf', 0):.2f}")
    else:
        head0 += "  disc NOT FOUND"
    if foil is not None:
        head0 += f"  foil {100 * float(foil.mean()):.0f}%"
    ax0.set_title(head0, fontsize=8, loc='left')

    prev_m = None
    for k, i in enumerate(idx):
        gray = se.load_gray(se.frame_path(run, rows[i]) or '')
        ax = axs[(k + 1) // cols][(k + 1) % cols]
        if gray is None or gray.shape != base.shape:
            continue
        cands = se.candidates(base, gray, settings, prev_method=prev_m)
        if cands:
            prev_m = cands[0]['method']
        ax.imshow(gray, cmap='gray', vmin=0, vmax=255)
        ax.axis('off')
        for j, c in enumerate(cands[:3]):
            pts = np.asarray(c['contour'], float)
            if len(pts) < 3:
                continue
            xs = np.append(pts[:, 0], pts[0, 0])
            ys = np.append(pts[:, 1], pts[0, 1])
            ax.plot(xs, ys, lw=2.0 if j == 0 else 0.9,
                    color=['#00e676', '#40c4ff', '#ff9100'][j])
        kv = _fkv(rows[i])
        best = cands[0] if cands else None
        head = f"{kv:g} kV" if not np.isnan(kv) else "? kV"
        if best:
            rev = 'REVIEW' if se.needs_review(cands, settings) else 'ok'
            head += (f"  {best['method']}  {best['area_px']:.0f} px2  "
                     f"conf {best['conf']:.2f}  {rev}")
        else:
            head += "  no candidates (gated)"
        ax.set_title(head, fontsize=8, loc='left')
    fig.suptitle(f"detections -- {os.path.basename(os.path.abspath(rundir))} "
                 f"(norm_bg={settings.get('norm_bg')})", fontsize=11)
    fig.tight_layout()
    fig.savefig(png, dpi=90)
    plt.close(fig)
    return png


def main(argv):
    args = [a for a in argv if not a.startswith('--')]
    if '--selftest' in argv:
        _selftest(args[0] if args else 'sldea_diag_selftest.png')
        return 0
    if not args:
        print(__doc__.strip().split('\n\n')[1])
        return 2
    # same resolver as the tuner: a run directory, a parent full of runs,
    # or a bench shortcut like `1`
    rundir = se.resolve_run(args[0])
    if not rundir:
        print(f"not a run directory (no data.csv, and no renamed "
              f"data1.csv / data2.csv ...): {args[0]}")
        return 2
    out = rundir
    if '--out' in argv:
        out = argv[argv.index('--out') + 1]
        os.makedirs(out, exist_ok=True)
    mx = 24
    if '--max-frames' in argv:
        mx = int(argv[argv.index('--max-frames') + 1])

    d = analyze(rundir, max_frames=mx)
    text = report(d)
    print(text)
    stem = os.path.join(out, 'sldea_diag')
    with open(stem + '.txt', 'w') as f:
        f.write(text + '\n')
    with open(stem + '.json', 'w') as f:
        json.dump(d, f, indent=1)
    figure(d, stem + '.png', rundir=rundir)
    made = '.txt / .json / .png'
    if '--no-contact' not in argv:
        # the outline drawn on the real frame: the check no residual can
        # stand in for, and readable by an agent working without a bench
        contact_sheet(rundir, stem + '_contact.png')
        made += ' / _contact.png'
    print(f"\nwrote {stem}{made}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
