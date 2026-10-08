#!/usr/bin/env python3
"""Tests for the camera pre-flight image gate (2026-10-02): no camera, no
instruments, fakes throughout.

The run this is built against is SLDEA_20261001_151016: the camera at
exposure 3, every frame a flat dark gray spanning 2 gray levels, 209 s of
high voltage up to 3 kV, and 25 of 26 frames rejected. The pre-flight
could not have stopped it: such a frame reads "exposure OK" because the
dark tier (mean < 40) sits below this camera's black pedestal of about
64, the default button says "Looks good" and Return presses it, and no
pre-flight ever reached run.log.

What is pinned here:

* sldea_edge.image_content, the pedestal-free contrast every check uses.
* The verdict tiers: 'flat' fires where 'dark' cannot, 'clipped' still
  wins on a white frame, and the older tiers answer as before. Real
  corpus baselines are judged too when SLDEA_CORPUS_DIR names a folder of
  run folders (each with frames/SLDEA_s00_00.00kV_baseline.png); without
  it that one test is skipped and the synthetic frames carry the tiers.
* The dialog's default-button rule, as a table and on the REAL dialog:
  on anything but a clean verdict the start button is not focused and
  Return is not bound. A flat frame needs a second Yes, like a clipped
  one, and the override is logged. Every pre-flight is logged.
* The preview-versus-run camera settings warning, and the SLDEA tab's
  "Camera for this run" line.
* The runner: a flat baseline ends a DRY and a LIVE run right after the
  baseline frame through the stop flag Abort uses, with the same zeroing
  writes, and run.log says what the drive had been commanded to; a
  normal baseline changes nothing; a check that raises is logged and the
  run completes; a log call that raises at the stop still zeroes.
* Owner decisions 12, 13 and 14 (2026-10-03): a deliberate "Start anyway
  (no picture)" at the pre-flight is an override that the start path
  hands to the worker, DRY or LIVE. With it a flat baseline is still
  checked and logged but does not stop the run, and setup.txt and
  run.log record the override. Without it, a baseline the camera gave
  no frame for ends the run the way a flat one does, when the pre-flight
  had a camera; a run started past "No camera frame available" goes on
  as it always did. The no-frame stop zeroes exactly as Abort does.

The dialog cases open one small window each and are skipped without a
display.

Run: .venv/bin/python tests/test_sldea_preflight.py
"""
import contextlib as _contextlib
import csv as _csv
import inspect as _inspect
import os as _os
import sys as _sys
import tempfile as _tempfile
import threading as _threading
import types as _types
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import numpy as _np  # noqa: E402

import gui  # noqa: E402
import sldea_edge  # noqa: E402
import sldea_profile  # noqa: E402
import webcam  # noqa: E402
from sldea_profile import (  # noqa: E402
    PREFLIGHT_OVERRIDE_NO_PICTURE, SldeaProfile, baseline_picture_check,
    baseline_stop_reason, baseline_stop_words, camera_line,
    camera_lock_mismatch, exposure_verdict, flat_stop_words,
    no_baseline_frame_line, preflight_override_record, preflight_report,
    preflight_start_button)

G = gui.InstrumentControlGUI
FLAT_Q = 'No picture in this frame'
CLIP_Q = 'Baseline is blown out'
STOP_BOX = 'Run stopped: no picture'
NOFRAME_BOX = 'Run stopped: no baseline frame'
OVERRIDE = PREFLIGHT_OVERRIDE_NO_PICTURE
# what the pre-flight leaves for the start path, by outcome
SEEN_NONE = {'frame': False, 'override': ''}
SEEN_FRAME = {'frame': True, 'override': ''}
SEEN_OVERRIDE = {'frame': True, 'override': OVERRIDE}


class _Skip(Exception):
    """Raised by a test that cannot run here (no display, no corpus)."""


# --------------------------------------------------------------------------
# Synthetic frames
# --------------------------------------------------------------------------

def _rgb(gray):
    g = _np.clip(gray, 0, 255).astype(_np.uint8)
    return _np.stack([g, g, g], axis=2)


def _flat_frame(level=66, h=240, w=320, seed=1):
    """The 2026-10-01 picture: one gray level plus or minus one."""
    rng = _np.random.default_rng(seed)
    return _rgb(level + rng.integers(-1, 2, size=(h, w)))


def _disc_frame(paper=170, disc=110, h=480, w=640, r=120, seed=2):
    """A dark resting disc on lighter paper, with a little sensor noise."""
    rng = _np.random.default_rng(seed)
    yy, xx = _np.mgrid[0:h, 0:w]
    g = _np.full((h, w), float(paper))
    g[(xx - w / 2) ** 2 + (yy - h / 2) ** 2 <= r * r] = disc
    return _rgb(g + rng.normal(0, 2.0, size=(h, w)))


def _halves(lo, hi, h=240, w=320):
    """Left half `lo`, right half `hi`: content without a disc."""
    g = _np.full((h, w), float(lo))
    g[:, w // 2:] = hi
    return _rgb(g)


def _stats(frame):
    gray = frame.mean(axis=2)
    return float(gray.mean()), float((gray >= 250).mean() * 100)


# --------------------------------------------------------------------------
# sldea_edge.image_content
# --------------------------------------------------------------------------

def test_image_content_reads_the_incident_as_flat_and_a_disc_as_a_picture():
    c = sldea_edge.image_content(_flat_frame())
    assert c['flat'] and c['contrast'] == 2.0, c
    assert (c['p5'], c['p95']) == (65.0, 67.0), c
    d = sldea_edge.image_content(_disc_frame())
    assert not d['flat'] and d['contrast'] >= 55.0, d
    # a 2-D float gray (what load_gray returns) and the RGB frame agree
    g = _disc_frame()[:, :, 0].astype(_np.float32)
    assert sldea_edge.image_content(g) == d
    # the threshold is the documented one, and it is strict
    assert sldea_edge.FLAT_CONTRAST_GRAY == 20.0
    assert sldea_edge.image_content(_halves(100, 119.9))['flat']
    assert not sldea_edge.image_content(_halves(100, 120))['flat']


def test_image_content_does_not_care_where_the_black_level_sits():
    """Pedestal-free: the same picture lifted by 64 gray reads the same
    contrast, which is the whole reason the mean-based dark tier failed."""
    low = sldea_edge.image_content(_halves(10, 60))
    lifted = sldea_edge.image_content(_halves(74, 124))
    assert low['contrast'] == lifted['contrast'] == 50.0, (low, lifted)


def test_image_content_judges_the_search_window_not_the_border():
    g = _np.full((200, 300), 66.0)
    g[:10, :] = 250                 # a bright strip outside the 85% window
    g[:, :15] = 0
    c = sldea_edge.image_content(g)
    assert c['flat'] and c['contrast'] == 0.0 and c['sat_pct'] == 0.0, c
    whole = sldea_edge.image_content(g, roi_frac=1.0)
    assert whole['sat_pct'] > 0.0, whole


def test_image_content_has_no_answer_for_no_frame():
    assert sldea_edge.image_content(None) is None
    assert sldea_edge.image_content(_np.zeros((0, 0))) is None


# --------------------------------------------------------------------------
# The verdict tiers
# --------------------------------------------------------------------------

def test_the_flat_tier_fires_where_the_dark_tier_cannot():
    # the incident's own numbers: mean 67.16, nothing saturated
    assert exposure_verdict(67.16, 0.0) == ('ok', 'exposure OK'), \
        "the two-argument call must answer as it always did"
    content = sldea_edge.image_content(_flat_frame())
    level, msg = exposure_verdict(67.16, 0.0, content)
    assert level == 'flat', (level, msg)
    assert msg == ("NO PICTURE: the frame is flat (contrast 2 gray "
                   "levels). The disc is not visible. Raise the exposure "
                   "or the light on the Webcam tab."), msg


def test_the_older_tiers_answer_as_before_on_a_frame_with_a_picture():
    content = sldea_edge.image_content(_disc_frame())
    for mean, sat, want in ((160.0, 0.5, 'ok'), (20.0, 0.0, 'dark'),
                            (220.0, 1.0, 'bright'), (200.0, 12.0, 'bright'),
                            (235.3, 73.74, 'clipped')):
        assert exposure_verdict(mean, sat)[0] == want
        assert exposure_verdict(mean, sat, content)[0] == want, (mean, sat)
    # no content dict at all (the check could not run) is not 'flat'
    assert exposure_verdict(67.16, 0.0, None)[0] == 'ok'


def test_clipped_beats_flat_because_its_advice_is_the_right_one():
    white = _rgb(_np.full((240, 320), 255.0))
    content = sldea_edge.image_content(white)
    assert content['flat'], content
    level, msg = exposure_verdict(*_stats(white), content)
    assert level == 'clipped' and 'Lower the exposure' in msg, (level, msg)


def test_flat_advice_follows_the_frame_level():
    flat = {'flat': True, 'contrast': 3.0}
    assert 'Raise the exposure' in exposure_verdict(67.0, 0.0, flat)[1]
    assert 'Lower the exposure' in exposure_verdict(220.0, 0.0, flat)[1]
    mid = exposure_verdict(150.0, 0.0, flat)[1]
    assert mid.endswith(
        "The disc is not visible. Check that the device is under the "
        "camera and that the disc is at least a third of the picture's "
        "height across, then the exposure and the light on the Webcam "
        "tab."), mid
    for mean in (67.0, 150.0, 220.0):
        level, msg = exposure_verdict(mean, 0.0, flat)
        assert level == 'flat' and msg.startswith('NO PICTURE:'), msg
        assert 'The disc is not visible.' in msg, msg


def test_flat_is_judged_before_dark_on_a_low_black_level():
    """A black frame on a camera whose black level is low (the 07-23
    setup, 35 gray or less) sits under the dark tier's mean AND is flat.
    It has to meet the gate and its default-No question, not the
    one-click 'dark' warning, so the flat tier is judged first."""
    assert exposure_verdict(20.0, 0.0)[0] == 'dark'
    level, msg = exposure_verdict(20.0, 0.0,
                                  {'flat': True, 'contrast': 1.0})
    assert level == 'flat' and 'Raise the exposure' in msg, (level, msg)
    black = _flat_frame(level=20)
    rep = preflight_report(black, 3, 0, {}, 0.2)
    assert rep['mean'] < sldea_profile.BASELINE_DARK_MEAN, rep['mean']
    assert rep['level'] == 'flat' and rep['gate'] is True, rep
    assert rep['start_default'] is False
    assert 'no picture' in rep['start_label'], rep['start_label']
    assert rep['log_lines'][0].endswith('verdict FLAT'), rep['log_lines']
    # the runner's check is the same rule: it stops on that frame too
    assert baseline_picture_check(black)[0] is True


def test_a_small_disc_on_even_paper_reads_flat_and_the_advice_says_so():
    """A KNOWN LIMIT, pinned so it is not a surprise at the bench. p5
    and p95 do not see a dark disc that covers under 5 % of the central
    window: on an even background such a frame reads flat although the
    disc is in the picture, and the runner's stop has no override.

    Measured 2026-10-02, paper 170, disc 110, noise sigma 2: at
    1920x1080 a 308 px disc reads contrast 10 and a 310 px one 63; at
    640x480 the same edge is between 118 and 120 px. No bench run has
    come near it: the smallest fitted disc in the corpus is 361 px of
    1080 (6.8 % of the window), and every corpus background spans 37.7
    gray levels or more by itself. The way through is tighter framing,
    which is what the mid-level advice asks for."""
    third = "at least a third of the picture's height across"
    for h, w, r_flat, r_seen in ((480, 640, 59, 60), (1080, 1920, 154, 155)):
        small = _disc_frame(h=h, w=w, r=r_flat)
        seen = _disc_frame(h=h, w=w, r=r_seen)
        c = sldea_edge.image_content(small)
        assert c['flat'] and c['contrast'] <= 12.0, (h, w, c)
        d = sldea_edge.image_content(seen)
        assert not d['flat'] and d['contrast'] >= 55.0, (h, w, d)
        # the runner's check is the same rule, and it names the fix
        flat, line = baseline_picture_check(small)
        assert flat and third in line, line
        assert baseline_picture_check(seen)[0] is False
    small, seen = _disc_frame(r=59), _disc_frame(r=60)
    rep = preflight_report(small, 23, 0, {}, 10.0)
    assert rep['level'] == 'flat' and rep['gate'], rep
    assert not rep['start_default'] and third in rep['hint'], rep['hint']
    assert preflight_report(seen, 23, 0, {}, 10.0)['level'] == 'ok'
    # a disc a third of the picture's height across is clear of the limit
    assert not sldea_edge.image_content(_disc_frame(r=80))['flat']
    # the limit needs an EVEN background: the same small disc on paper
    # that spans 40 gray levels by itself is a picture
    uneven = small.astype(_np.int16)
    uneven[:, uneven.shape[1] // 2:] += 40
    uneven = _np.clip(uneven, 0, 255).astype(_np.uint8)
    assert not sldea_edge.image_content(uneven)['flat']
    assert baseline_picture_check(uneven)[0] is False


# What each corpus baseline measured on 2026-10-02 (contrast is p95 - p5 of
# the central window; the incident reads 2, every other baseline 30+).
CORPUS_VERDICTS = {
    'Assctuator': 'ok', 'Assctuator2': 'ok', 'DOT_P3_1_20260729': 'ok',
    'P3_2_2.5mL_20260728': 'ok', 'P3_3_2.5mL_20260728': 'ok',
    'P3_5_2.5mL_0729': 'ok', 'P3_6_2.5mL_20260729': 'ok',
    'P3_7_2.3mL_20260729': 'ok', 'SLDEA_20260723_152205': 'ok',
    'SLDEA_20260723_233451': 'ok', 'SLDEA_20260729_104531': 'ok',
    'SLDEA_20260805_102417': 'clipped', 'SLDEA_20260805_103546': 'clipped',
    'SLDEA_20260806_151857': 'ok', 'SLDEA_20261001_151016': 'flat',
    'SquareStack-1': 'ok',
}


def test_real_corpus_baselines_get_the_verdicts_measured_for_them():
    root = _os.environ.get('SLDEA_CORPUS_DIR', '')
    if not root or not _os.path.isdir(root):
        raise _Skip("no corpus: set SLDEA_CORPUS_DIR to a folder of runs")
    try:
        import cv2
    except ImportError:
        raise _Skip("no OpenCV to read the corpus frames with")
    judged = {}
    for run in sorted(_os.listdir(root)):
        path = _os.path.join(root, run, 'frames',
                             'SLDEA_s00_00.00kV_baseline.png')
        bgr = cv2.imread(path, cv2.IMREAD_COLOR) \
            if _os.path.exists(path) else None
        if bgr is None:
            continue
        frame = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        rep = preflight_report(frame, 3, 0, {}, None)
        judged[run] = rep
        # the gate and the runner's check are one rule, not two
        assert baseline_picture_check(frame)[0] == (rep['level'] == 'flat')
        assert rep['start_default'] == (rep['level'] == 'ok'), run
        assert rep['log_lines'][0].endswith(
            f"verdict {rep['level'].upper()}"), rep['log_lines']
    known = {r: rep for r, rep in judged.items() if r in CORPUS_VERDICTS}
    if not known:
        raise _Skip(f"no known run under {root}")
    for run, rep in known.items():
        assert rep['level'] == CORPUS_VERDICTS[run], (
            run, rep['level'], rep['stats_line'])
        if rep['level'] != 'flat':
            assert rep['content']['contrast'] >= 30.0, (run, rep['content'])
    if 'SLDEA_20261001_151016' in known:
        rep = known['SLDEA_20261001_151016']
        assert rep['content']['contrast'] <= 3.0, rep['content']
        assert rep['gate'] and not rep['start_default']
        # the hole this closes: the old two-argument verdict passed it
        assert exposure_verdict(rep['mean'], rep['sat_pct'])[0] == 'ok'
        assert rep['disc_line'].startswith('Disc not found:'), rep


# --------------------------------------------------------------------------
# The default-button rule and the report (Tk-free)
# --------------------------------------------------------------------------

def test_only_a_clean_preflight_may_have_start_as_its_default_button():
    for level in ('ok', 'dark', 'bright', 'clipped', 'flat', 'unheard-of'):
        for mismatch in (False, True):
            for checked in (True, False):
                label, default = preflight_start_button(level, mismatch,
                                                        checked)
                clean = level == 'ok' and not mismatch and checked
                assert default == clean, (level, mismatch, checked, label)
                # the label never says "Looks good" on an unclean one
                assert ('Looks good' in label) == clean, label
                assert ('Start anyway' in label) == (not clean), label
    assert 'no picture' in preflight_start_button('flat')[0]
    assert 'blown out' in preflight_start_button('clipped')[0]


def test_a_builtin_camera_value_or_a_differing_tab_lock_costs_the_default():
    """2026-10-06 (the #348/#361 merge review). A camera value that is a
    built-in default, and the Webcam tab's lock disagreeing with the run
    (#361), are warnings the dialog shows with a warning sign: each costs
    the start button its default, and the report hands both through."""
    for fallback in (False, True):
        for tab in (False, True):
            label, default = preflight_start_button(
                'ok', False, True, fallback=fallback, tab_mismatch=tab)
            assert default == (not fallback and not tab), (fallback, tab)
            assert ('Looks good' in label) == default, label
    assert 'built-in camera values' in preflight_start_button(
        'ok', fallback=True)[0]
    assert preflight_start_button('ok', tab_mismatch=True)[0] == \
        sldea_profile.PREFLIGHT_START_LOCK_DIFFERS
    # a gate still names the gate, whatever else is also wrong
    assert 'no picture' in preflight_start_button(
        'flat', fallback=True, tab_mismatch=True)[0]
    rep = preflight_report(_disc_frame(), 6, 60, {}, 1.0,
                           defaults=('exposure', 'gain'))
    assert not rep['start_default'], rep['start_label']
    rep = preflight_report(_disc_frame(), 6, 60, {}, 1.0, tab_mismatch=True)
    assert not rep['start_default'] and \
        rep['start_label'] == sldea_profile.PREFLIGHT_START_LOCK_DIFFERS
    assert preflight_report(_disc_frame(), 6, 60, {}, 1.0)['start_default']


def test_a_video_runs_missing_baseline_is_not_blamed_on_the_preview():
    """A video run holds the camera, so the Webcam preview cannot be why
    its baseline frame never came: the stream stalled (2026-10-06)."""
    for override in ('', sldea_profile.PREFLIGHT_OVERRIDE_NO_PICTURE):
        still = sldea_profile.no_baseline_frame_line(override)
        video = sldea_profile.no_baseline_frame_line(override, video=True)
        assert 'Webcam preview' in still and 'Webcam preview' not in video
        assert 'video stream' in video, video
    box = sldea_profile.baseline_stop_words('no frame', False, 0.2,
                                            video=True)['box']
    assert 'Webcam preview' not in box and 'cable' in box, box
    assert 'Webcam preview' in sldea_profile.baseline_stop_words(
        'no frame', False, 0.2)['box']


def test_the_report_gates_a_flat_frame_and_logs_it():
    rep = preflight_report(_flat_frame(), 3, 0, {}, 0.19)
    assert rep['level'] == 'flat' and rep['gate'], rep
    assert not rep['start_default']
    assert 'no picture' in rep['start_label']
    assert rep['hint'].startswith('NO PICTURE: the frame is flat')
    assert rep['stats_line'] == ("focus 0   mean 66   saturated 0.0%   "
                                 "contrast 2 gray levels"), rep['stats_line']
    # mean, saturated percent, contrast, focus score and verdict, in one
    # line, plus the loud line a gate has always had
    assert rep['log_lines'][0] == (
        "camera pre-flight: mean 66, saturated 0.0%, contrast 2 gray "
        "levels, focus 0.19, verdict FLAT"), rep['log_lines']
    assert any('NO PICTURE' in ln for ln in rep['log_lines'][1:])
    assert rep['camera_line'] == ("Camera for this run: exposure 3, gain 0, "
                                  "set on the Webcam tab")


def test_the_report_passes_a_normal_frame_and_still_logs_it():
    rep = preflight_report(_disc_frame(), 23, 0, {}, 12.3)
    assert rep['level'] == 'ok' and not rep['gate'], rep
    assert rep['start_default'] and 'Looks good' in rep['start_label']
    assert rep['mismatch'] == [] and rep['mismatch_line'] == ''
    first = rep['log_lines'][0]
    assert first.startswith('camera pre-flight: mean 16') \
        and first.endswith('focus 12.30, verdict OK'), first
    assert 'contrast 6' in first and 'saturated 0.0%' in first, first
    assert rep['log_lines'][-1] == (
        "camera pre-flight: run camera exposure 23, gain 0; this camera "
        "has no device path, so neither the pre-flight nor the run stamps "
        "them on it"), rep['log_lines']
    # an unscored focus is said, not printed as a number
    assert 'focus not scored' in preflight_report(
        _disc_frame(), 23, 0, {}, None)['log_lines'][0]


def test_dark_bright_and_clipped_are_logged_and_lose_the_default_button():
    for frame, want, gate in ((_halves(10, 50), 'dark', False),
                              (_halves(205, 235), 'bright', False),
                              (_rgb(_np.full((240, 320), 255.0)),
                               'clipped', True)):
        rep = preflight_report(frame, 3, 0, {}, 1.0)
        assert rep['level'] == want and rep['gate'] is gate, (want, rep)
        assert not rep['start_default'], want
        assert 'Start anyway' in rep['start_label'], rep['start_label']
        assert rep['log_lines'][0].endswith(f"verdict {want.upper()}")


def test_the_lock_mismatch_is_what_the_preview_was_exposed_with():
    # the pre-flight frame is exposed with the LOCK wherever the lock
    # holds one of the run's four controls
    assert camera_lock_mismatch(3, 0, {}) == []
    assert camera_lock_mismatch(3, 0, None) == []
    assert camera_lock_mismatch(3, 0, {'brightness': 240}) == []
    assert camera_lock_mismatch(3, 0, {'exposure_time_absolute': 3,
                                       'gain': 0, 'auto_exposure': 1,
                                       'white_balance_automatic': 0}) == []
    assert camera_lock_mismatch(3, 0, {'exposure_time_absolute': 30,
                                       'gain': 0}) == [
        ('exposure_time_absolute', 3, 30)]
    both = camera_lock_mismatch(3, 0, {'gain': 16, 'auto_exposure': 3,
                                       'exposure_time_absolute': 3})
    assert [m[0] for m in both] == ['auto_exposure', 'gain'], both
    # a lock value nobody can read as a number counts as a difference
    assert camera_lock_mismatch(3, 0, {'gain': 'x'}) == [('gain', 0, 'x')]


def test_a_preview_taken_with_other_settings_is_said_in_plain_words():
    lock = {'exposure_time_absolute': 30, 'gain': 0, 'brightness': 240}
    rep = preflight_report(_disc_frame(), 3, 0, lock, 12.0)
    assert rep['level'] == 'ok', rep           # the PICTURE is fine...
    assert not rep['start_default']            # ...but it is not the run's
    assert 'preview does not match the run' in rep['start_label']
    assert sldea_profile.PREVIEW_MISMATCH_HEADLINE == (
        "This preview was NOT taken with the run's settings")
    assert 'The preview used exposure 30' in rep['mismatch_line']
    assert 'The run will use exposure 3 (what the boxes on the Webcam ' \
        'tab say).' in rep['mismatch_line'], rep['mismatch_line']
    # the advice is to CHECK the boxes first: Apply & Lock alone would
    # lock whatever the boxes hold, the wrong number included
    assert 'make the boxes say what you want, press Apply & Lock' \
        in rep['mismatch_line'], rep['mismatch_line']
    assert any('NOT taken' in ln and 'exposure 30' in ln
               for ln in rep['log_lines']), rep['log_lines']
    # automatic exposure left on in the lock is a mismatch too, in words
    auto = preflight_report(_disc_frame(), 3, 0, {'auto_exposure': 3}, 1.0)
    assert 'automatic exposure ON' in auto['mismatch_line'], auto
    assert 'automatic exposure off' in auto['mismatch_line'], auto
    # agreement, or a lock that holds none of the four: no warning
    for ok_lock in ({}, {'brightness': 240},
                    {'exposure_time_absolute': 3, 'gain': 0}):
        rep = preflight_report(_disc_frame(), 3, 0, ok_lock, 12.0)
        assert rep['start_default'] and not rep['mismatch'], ok_lock


def test_the_disc_line_is_advice_and_never_changes_the_verdict():
    try:
        import cv2  # noqa: F401
    except ImportError:
        raise _Skip("no OpenCV: the disc line is silent by design")
    found = preflight_report(_disc_frame(), 3, 0, {}, 1.0)
    assert found['disc_line'].startswith('Disc found: '), found['disc_line']
    px = float(found['disc_line'].split('Disc found: ')[1].split(' px')[0])
    assert abs(px - 240.0) <= 0.06 * 240.0, found['disc_line']
    assert 'fit quality 0.' in found['disc_line']
    # a frame with a picture but no disc: the fit refuses, the verdict
    # stays OK and start stays the default (non-disc devices exist)
    nodisc = preflight_report(_halves(120, 180), 3, 0, {}, 1.0)
    assert nodisc['level'] == 'ok' and nodisc['start_default'], nodisc
    assert nodisc['disc_line'].startswith('Disc not found: ')
    assert nodisc['disc_line'].endswith(
        'Edge Review will not be able to measure this run automatically.')
    # ...and if the fit itself blows up, the line is simply absent
    real = sldea_edge.baseline_disc
    try:
        def boom(*a, **k):
            raise RuntimeError('fit blew up')
        sldea_edge.baseline_disc = boom
        rep = preflight_report(_disc_frame(), 3, 0, {}, 1.0)
    finally:
        sldea_edge.baseline_disc = real
    assert rep['disc_line'] is None
    assert rep['level'] == 'ok' and rep['start_default']
    assert not any('Disc' in ln for ln in rep['log_lines'])


def test_a_picture_check_that_cannot_run_never_passes_for_ok():
    real = sldea_edge.image_content
    try:
        def boom(*a, **k):
            raise RuntimeError('no percentile today')
        sldea_edge.image_content = boom
        rep = preflight_report(_flat_frame(), 3, 0, {}, 0.19)
    finally:
        sldea_edge.image_content = real
    # the old tiers still answer (and are still fooled by the pedestal)...
    assert rep['level'] == 'ok' and rep['content'] is None, rep
    # ...but an unchecked picture may not sit behind a default button
    assert not rep['start_default']
    assert 'picture not checked' in rep['start_label']
    assert 'contrast not checked' in rep['stats_line']
    assert any('could not run (no percentile today)' in ln
               for ln in rep['log_lines']), rep['log_lines']


# --------------------------------------------------------------------------
# The "Camera for this run" line
# --------------------------------------------------------------------------

def test_the_camera_line_names_the_run_values_and_the_lock():
    text, warn = camera_line(3, 0, {})
    assert (text, warn) == ("Camera for this run: exposure 3, gain 0, set "
                            "on the Webcam tab", False)
    text, warn = camera_line(3, 0, {'exposure_time_absolute': 30, 'gain': 0})
    assert warn and text.startswith(
        "Camera for this run: exposure 3, gain 0, set on the Webcam tab")
    assert 'LOCKED exposure 30' in text and 'Apply & Lock' in text, text
    text, warn = camera_line(6, 60, {}, defaults=('exposure', 'gain'))
    assert warn and 'Read camera' in text and 'exposure 6, gain 60' in text
    assert 'The exposure and gain are built-in defaults' in text, text
    text, warn = camera_line(6, 0, {}, defaults=('exposure',))
    assert warn and 'The exposure is a built-in default' in text, text
    assert 'exposure 6, gain 0' in text


def test_the_dialog_line_does_not_call_a_fallback_set_on_the_webcam_tab():
    """With no readable box on the Webcam tab the run uses 6 and 60, and
    the pre-flight frame is shot with them too. The dialog's camera line
    has to say that, in the words the SLDEA tab uses."""
    rep = preflight_report(_disc_frame(), 6, 60, {}, 1.0,
                           defaults=('exposure', 'gain'))
    assert rep['camera_line'] == camera_line(
        6, 60, {}, defaults=('exposure', 'gain'))[0], rep['camera_line']
    assert 'built-in defaults' in rep['camera_line']
    assert 'set on the Webcam tab' not in rep['camera_line']
    # no defaults named: the line is the plain one, as before
    assert preflight_report(_disc_frame(), 6, 60, {}, 1.0)['camera_line'] \
        == "Camera for this run: exposure 6, gain 60, set on the Webcam tab"


def _var(value):
    return _types.SimpleNamespace(get=lambda: value)


class _Label:
    def __init__(self, broken=False):
        self.broken, self.shown = broken, []

    def config(self, **kw):
        if self.broken:
            raise RuntimeError('widget is gone')
        self.shown.append(kw)


class _LineApp:
    """Just enough app for the SLDEA tab's camera line."""
    _sldea_cam_value = G._sldea_cam_value
    _sldea_cam_defaults = G._sldea_cam_defaults
    _sldea_cam_line_refresh = G._sldea_cam_line_refresh

    def __init__(self, exp=None, gain=None, broken=False):
        if exp is not None:
            self.cam_exposure = _var(exp)
        if gain is not None:
            self.cam_gain = _var(gain)
        self.sldea_cam_line = _Label(broken)


@_contextlib.contextmanager
def _lock(controls):
    saved = dict(webcam.LOCKED_CONTROLS)
    webcam.set_locked(controls)
    try:
        yield
    finally:
        webcam.set_locked(saved)


def test_the_sldea_tab_line_reads_the_webcam_entries_and_the_lock():
    with _lock({}):
        app = _LineApp('3', '0')
        app._sldea_cam_line_refresh()
        [kw] = app.sldea_cam_line.shown
        assert kw == {'text': "Camera for this run: exposure 3, gain 0, set "
                              "on the Webcam tab", 'fg': '#555'}, kw
    with _lock({'exposure_time_absolute': 30, 'gain': 0}):
        app = _LineApp('3', '0')
        app._sldea_cam_line_refresh()
        [kw] = app.sldea_cam_line.shown
        # the warning is words AND colour, never colour alone
        assert kw['fg'] == '#8a5a00' and 'LOCKED exposure 30' in kw['text']
        assert 'NOT' in kw['text'], kw
    with _lock({}):
        # no Webcam-tab boxes (camera never read), or an unreadable one
        for app, said in (
                (_LineApp(), 'The exposure and gain are built-in defaults'),
                (_LineApp('3', None), 'The gain is a built-in default'),
                (_LineApp('', '0'), 'The exposure is a built-in default')):
            app._sldea_cam_line_refresh()
            [kw] = app.sldea_cam_line.shown
            assert said in kw['text'], kw
            assert kw['fg'] == '#8a5a00'
        # a dead label is not an exception: it is a label
        _LineApp('3', '0', broken=True)._sldea_cam_line_refresh()


def test_the_tab_line_shows_the_fallbacks_the_run_really_uses():
    """The line prints 6 and 60 when a box is missing; sldea_run must
    still fall back on exactly those, or the line would lie."""
    src = _inspect.getsource(G.sldea_run)
    assert "self._sldea_cam_value('cam_exposure', 6)" in src
    assert "self._sldea_cam_value('cam_gain', 60)" in src
    with _lock({}):
        app = _LineApp()
        app._sldea_cam_line_refresh()
        assert 'exposure 6, gain 60' in app.sldea_cam_line.shown[0]['text']


# --------------------------------------------------------------------------
# The runner: fakes for the camera, the signal generator and Tk
# --------------------------------------------------------------------------

class _Root:
    """Tk root stand-in: after() queues, run_pending() plays the queue."""

    def __init__(self):
        self.pending = []
        self._lock = _threading.Lock()

    def after(self, _ms, fn=None, *args):
        if fn is not None:
            with self._lock:
                self.pending.append((fn, args))
        return 'after#'

    def run_pending(self):
        while True:
            with self._lock:
                if not self.pending:
                    return
                fn, args = self.pending.pop(0)
            fn(*args)


class _FakeSG:
    """BK4055B stand-in: records every write as (call, channel, args)."""

    def __init__(self):
        self.writes = []

    def set_basic_wave(self, channel, **params):
        self.writes.append(('set_basic_wave', channel, params))

    def set_offset(self, channel, offset_v):
        self.writes.append(('set_offset', channel, offset_v))

    def set_output(self, channel, on):
        self.writes.append(('set_output', channel, on))

    def set_load_polarity(self, channel, load=None, polarity=None):
        self.writes.append(('set_load_polarity', channel, (load, polarity)))

    def offsets(self):
        return [w[2] for w in self.writes if w[0] == 'set_offset']


class _MB:
    """tkinter.messagebox stand-in: records every box, answers questions
    by title (a list is used up one answer at a time). A question with no
    answer fails the test."""

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.calls = []

    def askyesno(self, title, message, **kw):
        self.calls.append(('askyesno', title, message, kw))
        if title not in self.answers:
            raise AssertionError(f"unexpected question: {title!r}")
        ans = self.answers[title]
        return ans.pop(0) if isinstance(ans, list) else ans

    def __getattr__(self, name):
        if name.startswith('show'):
            def show(title, message, **kw):
                self.calls.append((name, title, message, kw))
            return show
        raise AttributeError(name)

    def titles(self, kind=None):
        return [c[1] for c in self.calls if kind in (None, c[0])]


# No test here may ever open a real message box: a modal one would sit on
# the screen and block the suite. Each test swaps in its own stub over this.
gui.messagebox = _MB()


class _RunApp:
    """Just enough app for the REAL _sldea_worker and _sldea_capture."""
    SLDEA_POLL_S = G.SLDEA_POLL_S
    _sldea_worker = G._sldea_worker
    _sldea_capture = G._sldea_capture
    sldea_abort = G.sldea_abort

    def __init__(self, sg=None):
        self.scope, self.sg = None, sg
        self._sldea_stop = False
        self._sldea_bd_tripped = False
        self._sldea_elapsed = 0.0
        self._sldea_prelog, self._sldea_runlog = [], None
        self._sldea_loglock = _threading.Lock()
        self.lines, self.status, self.finished = [], [], False
        self.root = _Root()

    def _sldea_log(self, msg):
        self.lines.append(str(msg))

    def _sldea_set_status(self, text, fg='#555'):
        self.status.append((text, fg))

    def _sldea_finished(self):
        self.finished = True


@_contextlib.contextmanager
def _camera(frames, device=None):
    """A camera that hands out `frames(n)` on its n-th grab (1-based).
    With `device` the spec carries a device path, so the run's control
    writes happen and are recorded instead of reaching v4l2-ctl."""
    saved = (webcam.resolve_camera, webcam.oneshot_rgb, webcam.set_control)
    lock = dict(webcam.LOCKED_CONTROLS)
    seen = {'grabs': 0, 'controls': [], 'on_grab': None}
    spec = {'kind': 'cv2', 'index': 0}
    if device:
        spec['device'] = device

    def grab(_spec, count=2):
        seen['grabs'] += 1
        if seen['on_grab'] is not None:
            seen['on_grab'](seen['grabs'])
        return frames(seen['grabs'])

    def set_control(_dev, name, value):
        seen['controls'].append((name, int(value)))
        return True

    webcam.resolve_camera = lambda idx: dict(spec)
    webcam.oneshot_rgb = grab
    webcam.set_control = set_control
    try:
        yield seen
    finally:
        (webcam.resolve_camera, webcam.oneshot_rgb,
         webcam.set_control) = saved
        webcam.set_locked(lock)


@_contextlib.contextmanager
def _messagebox(mb):
    saved = gui.messagebox
    gui.messagebox = mb
    try:
        yield mb
    finally:
        gui.messagebox = saved


def _profile(**kw):
    """Two landings, 2.1 s end to end, baseline 0.3 s after the warm-up."""
    opts = dict(start_kv=0.0, end_kv=0.5, step_kv=0.25, ramp_s=0.4,
                landing_s=0.5, settle_s=0.1, snap_lead_s=0.1,
                baseline_warmup_s=0.3)
    opts.update(kw)
    return SldeaProfile(**opts)


def _run_worker(app, p, tmp, dry=True, timeout=60, **kw):
    """The REAL worker on `app`, as the start path starts it. `kw` is
    what the start path adds from the pre-flight (cam_expected,
    picture_override); left out, the worker's defaults apply."""
    t = _threading.Thread(
        target=app._sldea_worker, args=(p, tmp, 'RUN', 1, 2, 3, dry),
        kwargs=dict(cam_exp=3, cam_gain=0, **kw), daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), ("the worker stalled", app.lines)
    assert not any(ln.startswith('ERROR') for ln in app.lines), app.lines
    return _os.path.join(tmp, 'RUN')


def _rows(rundir):
    with open(_os.path.join(rundir, 'data.csv'), newline='') as f:
        return list(_csv.DictReader(f))


def _setup_lines(rundir):
    with open(_os.path.join(rundir, 'setup.txt'), encoding='utf-8') as f:
        return f.read().splitlines()


FLAT, GOOD = _flat_frame(), _disc_frame(h=240, w=320, r=60)
ZEROING = [('set_offset', 1, 0.0), ('set_output', 1, False)]
SETUP = ['set_load_polarity', 'set_basic_wave', 'set_output']


def test_capture_hands_the_frame_back_to_the_runner():
    src = _inspect.getsource(G._sldea_capture)
    assert src.rstrip().endswith('return frame'), src[-200:]


def test_the_stop_says_what_the_drive_had_been_commanded_to():
    """The baseline is shot in the loop tick in which the first ramp
    begins, so "at 0 kV" would not be true of a LIVE stop. The line
    prints the number instead, and never raises."""
    assert flat_stop_words(True, 0.25) == \
        "This was a DRY run: no voltage was driven."
    live = flat_stop_words(False, 0.012)
    assert live == ("The first voltage ramp had only just begun: the drive "
                    "had been commanded to 0.012 kV when the run stopped.")
    assert '0.250 kV' in flat_stop_words(False, 0.25)
    for junk in (None, 'x', object()):
        assert 'not known' in flat_stop_words(False, junk), junk


def test_a_flat_baseline_stops_a_dry_run_right_after_the_baseline_frame():
    p = _profile()
    mb = _MB()
    with _tempfile.TemporaryDirectory() as tmp, \
            _camera(lambda n: FLAT) as cam, _messagebox(mb):
        app = _RunApp()
        rundir = _run_worker(app, p, tmp, dry=True)
        rows = _rows(rundir)
        frames = sorted(_os.listdir(_os.path.join(rundir, 'frames')))
        # the box is queued for the Tk thread, never shown from the worker
        assert mb.calls == [], mb.calls
        app.root.run_pending()
    # the warm-up and the baseline, and nothing after them
    assert [r['tag'] for r in rows] == ['warmup', 'baseline'], rows
    assert frames == ['SLDEA_s00_00.00kV_baseline.png',
                      'SLDEA_s00_00.00kV_warmup.png'], frames
    assert cam['grabs'] == 2, cam
    loud = [ln for ln in app.lines if 'NO PICTURE' in ln]
    assert len(loud) == 1 and loud[0].endswith('STOPPING NOW.'), app.lines
    assert 'contrast 2 gray levels' in loud[0], loud
    # the next line is the record of where the drive stood: nowhere, DRY
    at = app.lines.index(loud[0])
    assert app.lines[at + 1] == ("run stopped at the baseline frame. This "
                                 "was a DRY run: no voltage was driven."), \
        app.lines
    assert f"run aborted: 2/{len(p.snapshots)} frames" in app.lines
    assert not any('post-ramp' in ln for ln in app.lines), app.lines
    # the operator is told why, in words, where they look
    text, fg = app.status[-1]
    assert text.startswith('STOPPED: NO PICTURE in the baseline frame'), text
    assert fg == '#c62828'
    assert mb.titles('showwarning') == [STOP_BOX], mb.calls
    box = mb.calls[0][2]
    assert box.startswith('The run stopped itself right after its baseline '
                          'picture.'), box
    assert 'This was a DRY run: no voltage was driven.' in box, box
    assert 'Apply & Lock' in box, box
    assert app.finished


def test_a_flat_baseline_zeroes_a_live_run_exactly_as_abort_does():
    """The stop is the Abort flag, so the shutdown must be the Abort
    shutdown: same zeroing writes, nothing after the baseline but them,
    and the Webcam-tab lock handed back. Slow ramp (0.05 kV/s, the tab's
    default) so the drive reached before the stop is the realistic one."""
    p = _profile(ramp_s=5.0)
    lock = {'exposure_time_absolute': 30, 'gain': 0, 'brightness': 240}
    out = {}
    for case in ('flat baseline', 'operator abort'):
        sg = _FakeSG()
        app = _RunApp(sg)
        mark = {}

        def on_grab(n, app=app, sg=sg, mark=mark, case=case):
            if n == 2:                       # the baseline grab
                mark['writes'] = len(sg.writes)
                if case == 'operator abort':
                    app.sldea_abort()        # the real Abort button path

        frame = FLAT if case == 'flat baseline' else GOOD
        with _tempfile.TemporaryDirectory() as tmp, _lock(lock), \
                _camera(lambda n: frame, device='/dev/video0') as cam, \
                _messagebox(_MB()):
            cam['on_grab'] = on_grab
            rundir = _run_worker(app, p, tmp, dry=False)
            rows = _rows(rundir)
            lock_after = dict(webcam.LOCKED_CONTROLS)
            app.root.run_pending()
        out[case] = (sg, app, mark, rows, lock_after, list(cam['controls']))

    for case, (sg, app, mark, rows, lock_after, controls) in out.items():
        assert [w[0] for w in sg.writes[:3]] == SETUP, (case, sg.writes)
        # after the baseline grab the ONLY writes are the zeroing pair
        assert sg.writes[mark['writes']:] == ZEROING, (case, sg.writes)
        assert sg.writes[-2:] == ZEROING, (case, sg.writes)
        assert [r['tag'] for r in rows] == ['warmup', 'baseline'], case
        assert f"run aborted: 2/{len(p.snapshots)} frames" in app.lines, case
        # the first ramp had begun by one loop tick at most: under 1 s of
        # a 0.05 kV/s ramp, and never a second write of it
        up = [v for v in sg.offsets() if v > 0]
        assert len(up) <= 1 and all(v < 0.05 for v in up), (case, up)
        assert not any('FAILED TO ZERO' in ln for ln in app.lines), case
        # the run's camera lock is undone: the operator's lock is back
        assert lock_after == lock, (case, lock_after)
        assert controls == [('auto_exposure', 1),
                            ('white_balance_automatic', 0),
                            ('exposure_time_absolute', 3), ('gain', 0)], \
            (case, controls)
    flat_sg, abort_sg = out['flat baseline'][0], out['operator abort'][0]
    assert [w[:2] for w in flat_sg.writes if w[0] != 'set_offset'] == \
        [w[:2] for w in abort_sg.writes if w[0] != 'set_offset']
    assert any('NO PICTURE' in ln for ln in out['flat baseline'][1].lines)
    assert not any('NO PICTURE' in ln
                   for ln in out['operator abort'][1].lines)
    # run.log carries what the drive had been commanded to at the stop:
    # the last offset written before the zeroing pair, not an assumed 0
    said = [ln for ln in out['flat baseline'][1].lines
            if ln.startswith('run stopped at the baseline frame.')]
    last = [v for v in flat_sg.offsets()[:-1]][-1]
    assert len(said) == 1 and f"commanded to {last:.3f} kV" in said[0], \
        (said, flat_sg.offsets())
    assert not any(ln.startswith('run stopped at the baseline frame.')
                   for ln in out['operator abort'][1].lines)


def test_a_zero_second_ramp_is_reported_as_it_is_not_as_zero_volts():
    """With ramp time 0 the profile commands the whole first level in the
    tick the baseline is shot (it always has). The stop cannot undo that
    tick; what it must do is zero the drive at once and write the number
    down instead of claiming the staircase never left 0 kV."""
    p = _profile(ramp_s=0.0)
    sg = _FakeSG()
    app = _RunApp(sg)
    mb = _MB()
    with _tempfile.TemporaryDirectory() as tmp, \
            _camera(lambda n: FLAT), _messagebox(mb):
        rundir = _run_worker(app, p, tmp, dry=False)
        rows = _rows(rundir)
        app.root.run_pending()
    assert [r['tag'] for r in rows] == ['warmup', 'baseline'], rows
    assert sg.writes[-2:] == ZEROING, sg.writes
    assert [v for v in sg.offsets() if v > 0] == [0.25], sg.offsets()
    said = [ln for ln in app.lines
            if ln.startswith('run stopped at the baseline frame.')]
    assert len(said) == 1 and 'commanded to 0.250 kV' in said[0], app.lines
    assert 'commanded to 0.250 kV' in mb.calls[0][2], mb.calls


def test_a_log_call_that_raises_at_the_stop_still_zeroes_the_drive():
    """The stop flag is set before the loud line is logged, and the whole
    block sits inside the worker's try: if logging itself fails (the Tk
    loop is gone), the run still ends and the finally block still writes
    the zeroing pair. Nothing after the baseline but those two writes.
    Both stops: a flat baseline, and no baseline frame at all."""
    for loud, frames, kw in (
            ('NO PICTURE', lambda n: FLAT, {}),
            ('NO BASELINE FRAME', lambda n: GOOD if n == 1 else None,
             dict(cam_expected=True))):
        class _DeafApp(_RunApp):
            def _sldea_log(self, msg):
                if loud in str(msg):
                    raise RuntimeError('main thread is not in main loop')
                self.lines.append(str(msg))

        p = _profile(ramp_s=5.0)
        sg = _FakeSG()
        app = _DeafApp(sg)
        mark = {}
        with _tempfile.TemporaryDirectory() as tmp, \
                _camera(frames) as cam, _messagebox(_MB()):
            cam['on_grab'] = lambda n: mark.__setitem__(n, len(sg.writes))
            t = _threading.Thread(
                target=app._sldea_worker,
                args=(p, tmp, 'RUN', 1, 2, 3, False),
                kwargs=dict(cam_exp=3, cam_gain=0, **kw), daemon=True)
            t.start()
            t.join(60)
            assert not t.is_alive(), ("the worker stalled", app.lines)
            rows = _rows(_os.path.join(tmp, 'RUN'))
            app.root.run_pending()
        assert app._sldea_stop is True, loud
        assert [r['tag'] for r in rows] == ['warmup', 'baseline'], rows
        assert sg.writes[mark[2]:] == ZEROING, (loud, sg.writes)
        assert any(ln.startswith('ERROR: main thread') for ln in app.lines)
        assert not any('FAILED TO ZERO' in ln for ln in app.lines), \
            app.lines
        assert app.finished, loud


def _complete_run(frames, dry=False, patch=None, **kw):
    """One whole run on `frames`; -> (app, sg, rows, profile). The run
    folder's setup.txt lines are kept on the app as app.setup, read
    before the folder goes away, and every box shown as app.boxes."""
    p = _profile()
    sg = None if dry else _FakeSG()
    app = _RunApp(sg)
    mb = _MB()
    with _tempfile.TemporaryDirectory() as tmp, _camera(frames), \
            _messagebox(mb):
        undo = patch() if patch is not None else None
        try:
            rundir = _run_worker(app, p, tmp, dry=dry, **kw)
        finally:
            if undo is not None:
                undo()
        rows = _rows(rundir)
        app.setup = _setup_lines(rundir)
        app.root.run_pending()      # inside the stub: no real box, ever
    app.boxes = mb.calls
    return app, sg, rows, p


def _assert_ran_to_the_end(app, sg, rows, p):
    assert f"run complete: {len(p.snapshots)}/{len(p.snapshots)} frames" \
        in app.lines, app.lines
    assert len(rows) == len(p.snapshots), rows
    assert not any('NO PICTURE' in ln for ln in app.lines), app.lines
    assert app.status[-1][0].startswith('complete'), app.status[-1]
    if sg is not None:
        assert [w[0] for w in sg.writes[:3]] == SETUP, sg.writes
        assert sg.writes[-2:] == ZEROING, sg.writes
        # the staircase reached its top landing (0.5 kV, within the
        # 1e-4 step below which the loop does not re-send an offset)
        assert max(sg.offsets()) > 0.499, sg.offsets()
    assert app.finished


def test_a_normal_baseline_lets_the_run_complete():
    for dry in (True, False):
        app, sg, rows, p = _complete_run(lambda n: GOOD, dry=dry)
        _assert_ran_to_the_end(app, sg, rows, p)
        ok = [ln for ln in app.lines
              if ln.startswith('baseline picture check: contrast')]
        assert len(ok) == 1 and ok[0].endswith('- OK'), app.lines
        assert all(r['frame_file'] for r in rows), rows


def test_an_exception_in_the_check_does_not_stop_the_run():
    def boom(*a, **k):
        raise RuntimeError('boom')

    def patch_check():
        real = sldea_profile.baseline_picture_check
        sldea_profile.baseline_picture_check = boom
        return lambda: setattr(sldea_profile, 'baseline_picture_check', real)

    def patch_content():
        real = sldea_edge.image_content
        sldea_edge.image_content = boom
        return lambda: setattr(sldea_edge, 'image_content', real)

    def patch_empty():
        real = sldea_edge.image_content
        sldea_edge.image_content = lambda *a, **k: None
        return lambda: setattr(sldea_edge, 'image_content', real)

    # even on a FLAT baseline: a check that cannot run decides nothing
    for patch, why in ((patch_check, 'boom'), (patch_content, 'boom'),
                       (patch_empty, 'the baseline frame is empty')):
        app, sg, rows, p = _complete_run(lambda n: FLAT, patch=patch)
        _assert_ran_to_the_end(app, sg, rows, p)
        said = [ln for ln in app.lines
                if 'baseline picture check could not run' in ln]
        assert len(said) == 1 and why in said[0], app.lines
        assert 'the run continues unchanged' in said[0], said


def test_a_flat_warm_up_frame_alone_stops_nothing():
    """Only the baseline is judged: the warm-up frame is the one the
    camera is most likely to mis-expose, which is why it is thrown away."""
    app, sg, rows, p = _complete_run(lambda n: FLAT if n == 1 else GOOD)
    _assert_ran_to_the_end(app, sg, rows, p)


def test_no_baseline_frame_means_no_check_and_no_change():
    """The "No camera frame available, continue anyway?" case: the
    pre-flight had no camera (cam_expected stays False), so a run with
    no frames goes on exactly as it always did (decision 13 keeps it)."""
    app, sg, rows, p = _complete_run(lambda n: None)
    _assert_ran_to_the_end(app, sg, rows, p)
    assert not any('baseline picture check' in ln for ln in app.lines)
    assert not any('BASELINE FRAME' in ln for ln in app.lines), app.lines
    assert all(r['frame_file'] == '' for r in rows), rows
    assert not any(ln.startswith('Pre-flight override') for ln in app.setup)


# --------------------------------------------------------------------------
# Decisions 12, 13 and 14 (2026-10-03): the pre-flight override carries
# into the run; no baseline frame at all stops the run
# --------------------------------------------------------------------------

def test_the_baseline_stop_rule_as_a_table():
    """(frame taken, flat, camera at the pre-flight, override) -> why."""
    table = [
        ((True, False, True, ''), ''),           # a normal baseline
        ((True, True, True, ''), 'flat'),        # the 2026-10-01 picture
        ((True, True, False, ''), 'flat'),       # flat is flat regardless
        ((False, False, True, ''), 'no frame'),  # camera gave nothing
        ((False, False, False, ''), ''),         # no camera to expect it
        ((True, True, True, OVERRIDE), ''),      # the override: carry on
        ((False, False, True, OVERRIDE), ''),    # ...also with no frame
        ((True, False, True, OVERRIDE), ''),
    ]
    for args, why in table:
        assert baseline_stop_reason(*args) == why, (args, why)


def test_the_override_record_is_a_plain_key_value_line_and_a_log_line():
    assert preflight_override_record('') == (None, None)
    setup, log = preflight_override_record(OVERRIDE)
    assert setup.startswith('Pre-flight override: no picture ('), setup
    assert setup.isascii() and '\n' not in setup, setup
    assert 'baseline picture stop is off for this run' in setup, setup
    assert log.startswith('⚠⚠ pre-flight override: no picture.')
    assert 'will NOT stop this run' in log, log
    # the setup.txt reader is unmoved by the new line (it reads only its
    # own section and the diameter line)
    with _tempfile.TemporaryDirectory() as tmp:
        with open(_os.path.join(tmp, 'setup.txt'), 'w') as f:
            f.write("SLDEA Test  --  RUN\nDEA nominal diameter: 16 mm\n"
                    + setup + "\n")
        s = sldea_edge.load_settings(tmp)
    assert s == dict(sldea_edge.DEFAULT_SETTINGS, diam_mm=16.0), s


def test_the_check_names_the_override_instead_of_stopping():
    """The verdict is the same; only the words after it change."""
    flat, plain = baseline_picture_check(FLAT)
    flat2, said = baseline_picture_check(FLAT, OVERRIDE)
    assert flat and flat2
    assert plain.endswith('STOPPING NOW.'), plain
    assert said.endswith('so the run CARRIES ON. Review this run by hand.')
    assert 'started anyway at the pre-flight (no picture)' in said, said
    assert 'STOPPING' not in said, said
    assert plain.split(' This is the run')[0] == \
        said.split(' This is the run')[0]
    assert 'contrast 2 gray levels' in said, said
    ok, line = baseline_picture_check(GOOD, OVERRIDE)
    assert not ok and line == baseline_picture_check(GOOD)[1]


def test_the_no_frame_words_say_what_happened_and_what_to_do():
    stop = no_baseline_frame_line()
    assert stop.startswith('⚠⚠ NO BASELINE FRAME: the camera gave '
                           'the pre-flight a picture'), stop
    assert stop.endswith('STOPPING NOW.') and 'Webcam preview' in stop
    on = no_baseline_frame_line(OVERRIDE)
    assert on.endswith('so the run CARRIES ON. Review this run by hand.')
    assert 'STOPPING' not in on and '(no picture)' in on, on
    for reason in ('flat', 'no frame'):
        w = baseline_stop_words(reason, True, None)
        assert set(w) == {'stopped', 'status', 'title', 'box'}, w
        assert w['stopped'] == ("run stopped at the baseline frame. This "
                                "was a DRY run: no voltage was driven.")
        assert w['status'].startswith('STOPPED: ') and \
            w['status'].endswith('(see Run log)'), w
        assert 'no voltage was driven' in w['box'], w
        assert 'press Run again' in w['box'], w
        live = baseline_stop_words(reason, False, 0.012)
        assert 'commanded to 0.012 kV' in live['box'], live
    assert baseline_stop_words('flat', True, None)['title'] == STOP_BOX
    assert baseline_stop_words('no frame', True, None)['title'] == \
        NOFRAME_BOX
    assert 'NO BASELINE FRAME' in \
        baseline_stop_words('no frame', True, None)['status']
    assert 'NO PICTURE' in baseline_stop_words('flat', True, None)['status']


def test_a_flat_baseline_with_the_override_runs_to_the_end():
    """Decisions 12 and 14: the override carries into DRY and LIVE. The
    check still runs and logs its verdict, setup.txt and run.log record
    the override, nothing stops, and the LIVE run ends with the same
    zeroing pair every complete run ends with."""
    for dry in (True, False):
        app, sg, rows, p = _complete_run(
            lambda n: FLAT, dry=dry, cam_expected=True,
            picture_override=OVERRIDE)
        # _assert_ran_to_the_end forbids a NO PICTURE line, which this
        # run must have, so its checks are spelled out here
        assert f"run complete: {len(p.snapshots)}/{len(p.snapshots)} " \
               f"frames" in app.lines, (dry, app.lines)
        assert len(rows) == len(p.snapshots), rows
        assert app.status[-1][0].startswith('complete'), app.status[-1]
        assert app.boxes == [], app.boxes
        assert app.finished
        if sg is not None:
            assert [w[0] for w in sg.writes[:3]] == SETUP, sg.writes
            assert sg.writes[-2:] == ZEROING, sg.writes
            assert max(sg.offsets()) > 0.499, sg.offsets()
        # the verdict is logged, and it says the run goes on
        loud = [ln for ln in app.lines if 'NO PICTURE' in ln]
        assert len(loud) == 1, (dry, app.lines)
        assert 'contrast 2 gray levels' in loud[0], loud
        assert loud[0].endswith('so the run CARRIES ON. Review this run '
                                'by hand.'), loud
        assert not any('STOPPING' in ln or 'run stopped' in ln
                       for ln in app.lines), app.lines
        # the record: one plain Key: value line in setup.txt, and the
        # override in run.log before the first frame
        [key] = [ln for ln in app.setup if ln.startswith('Pre-flight ')]
        assert key == preflight_override_record(OVERRIDE)[0], key
        # on its own, after the Snapshots block the profile text ends with
        at = app.setup.index(key)
        assert at > app.setup.index('--- Snapshots ---'), app.setup
        assert app.setup[at - 1] == '', app.setup[at - 2:at + 1]
        over = [i for i, ln in enumerate(app.lines)
                if 'pre-flight override: no picture' in ln]
        first_snap = [i for i, ln in enumerate(app.lines)
                      if 'snap s00' in ln]
        assert len(over) == 1 and over[0] < first_snap[0], app.lines
        assert 'will NOT stop this run' in app.lines[over[0]], app.lines


def test_no_baseline_frame_stops_a_run_whose_preflight_had_a_camera():
    """Decision 13: the pre-flight got a frame, the baseline grab gives
    none. The run ends through the abort path, with the zeroing pair as
    the only writes after the baseline grab, as the flat stop does."""
    p = _profile(ramp_s=5.0)
    frames = lambda n: GOOD if n == 1 else None     # noqa: E731
    for dry in (True, False):
        sg = None if dry else _FakeSG()
        app = _RunApp(sg)
        mb = _MB()
        mark = {}
        with _tempfile.TemporaryDirectory() as tmp, \
                _camera(frames) as cam, _messagebox(mb):
            cam['on_grab'] = lambda n: mark.setdefault(
                n, len(sg.writes) if sg else 0)
            rundir = _run_worker(app, p, tmp, dry=dry, cam_expected=True)
            rows = _rows(rundir)
            frame_files = sorted(_os.listdir(
                _os.path.join(rundir, 'frames')))
            setup = _setup_lines(rundir)
            assert mb.calls == [], mb.calls
            app.root.run_pending()
        assert [r['tag'] for r in rows] == ['warmup', 'baseline'], rows
        assert rows[1]['frame_file'] == '', rows
        assert frame_files == ['SLDEA_s00_00.00kV_warmup.png'], frame_files
        # the baseline grab and its one retry, then nothing
        assert cam['grabs'] == 3, cam
        loud = [ln for ln in app.lines if 'NO BASELINE FRAME' in ln]
        assert len(loud) == 1 and loud[0].endswith('STOPPING NOW.'), \
            app.lines
        at = app.lines.index(loud[0])
        assert app.lines[at + 1].startswith(
            'run stopped at the baseline frame. '), app.lines
        assert f"run aborted: 2/{len(p.snapshots)} frames" in app.lines
        assert not any('NO PICTURE' in ln for ln in app.lines), app.lines
        text, fg = app.status[-1]
        assert text.startswith('STOPPED: NO BASELINE FRAME'), text
        assert fg == '#c62828'
        assert mb.titles('showwarning') == [NOFRAME_BOX], mb.calls
        assert 'gave the pre-flight one' in mb.calls[0][2], mb.calls
        assert not any(ln.startswith('Pre-flight') for ln in setup)
        assert app.finished
        if dry:
            assert 'This was a DRY run' in app.lines[at + 1]
            assert 'This was a DRY run' in mb.calls[0][2]
        else:
            assert sg.writes[mark[2]:] == ZEROING, sg.writes
            assert sg.writes[-2:] == ZEROING, sg.writes
            up = [v for v in sg.offsets() if v > 0]
            assert len(up) <= 1 and all(v < 0.05 for v in up), up
            assert not any('FAILED TO ZERO' in ln for ln in app.lines)
            last = [v for v in sg.offsets()[:-1]][-1]
            assert f"commanded to {last:.3f} kV" in app.lines[at + 1]


def test_no_baseline_frame_with_the_override_carries_on():
    """One mechanism: the override also covers a camera that gives the
    run no baseline frame. Logged, and the run goes on."""
    app, sg, rows, p = _complete_run(
        lambda n: GOOD if n == 1 else None, cam_expected=True,
        picture_override=OVERRIDE)
    _assert_ran_to_the_end(app, sg, rows, p)
    [said] = [ln for ln in app.lines if 'NO BASELINE FRAME' in ln]
    assert said.endswith('so the run CARRIES ON. Review this run by hand.')
    assert not any('run stopped' in ln for ln in app.lines), app.lines
    assert app.boxes == [], app.boxes
    assert any(ln.startswith('Pre-flight override: no picture')
               for ln in app.setup), app.setup


def test_a_good_baseline_with_the_override_is_only_a_recorded_run():
    """The override changes nothing about a baseline that is fine: the
    check passes as before, and only the record carries the override."""
    app, sg, rows, p = _complete_run(
        lambda n: GOOD, cam_expected=True, picture_override=OVERRIDE)
    _assert_ran_to_the_end(app, sg, rows, p)
    ok = [ln for ln in app.lines
          if ln.startswith('baseline picture check: contrast')]
    assert len(ok) == 1 and ok[0].endswith('- OK'), app.lines
    assert any(ln.startswith('Pre-flight override: no picture')
               for ln in app.setup), app.setup
    assert any('pre-flight override: no picture' in ln
               for ln in app.lines), app.lines


# --------------------------------------------------------------------------
# The pre-flight method itself: the two paths that need no window
# --------------------------------------------------------------------------

class _FlightApp:
    """Just enough app for the REAL _sldea_preflight. `boxes` are the
    Webcam tab's exposure and gain entries (None: the tab has none)."""
    _sldea_preflight = G._sldea_preflight
    _sldea_cam_value = G._sldea_cam_value
    _sldea_cam_defaults = G._sldea_cam_defaults

    def __init__(self, root=None, boxes=('3', '0')):
        self.root = root
        self.lines, self.tabs = [], []
        if boxes is not None:
            self.cam_exposure, self.cam_gain = _var(boxes[0]), _var(boxes[1])

    def _sldea_log(self, msg):
        self.lines.append(str(msg))

    def select_manual_tab(self, slug):
        self.tabs.append(slug)
        return True


def test_a_preflight_with_no_frame_logs_the_question_and_the_answer():
    for answer in (False, True):
        mb = _MB({'Camera pre-flight': answer})
        app = _FlightApp()
        app._sldea_preflight_seen = SEEN_OVERRIDE      # stale, from before
        with _camera(lambda n: None), _messagebox(mb):
            assert app._sldea_preflight(3, 0) is answer
        [(kind, _title, _msg, kw)] = mb.calls
        assert kind == 'askyesno' and kw == {'default': 'no'}, mb.calls
        assert app.lines[0] == 'camera pre-flight: NO FRAME from the camera'
        assert ('ANYWAY with no camera frame' in app.lines[-1]) is answer, \
            app.lines
        # no camera at the pre-flight: not an override, and the run is
        # not told to expect a baseline frame (decision 13 keeps this
        # question's behaviour)
        assert app._sldea_preflight_seen == SEEN_NONE, \
            app._sldea_preflight_seen


def test_a_report_that_raises_asks_default_no_and_never_starts_silently():
    real = sldea_profile.preflight_report

    def boom(*a, **k):
        raise RuntimeError('report blew up')

    for answer in (False, True):
        mb = _MB({'Camera pre-flight': answer})
        app = _FlightApp()
        sldea_profile.preflight_report = boom
        try:
            with _camera(lambda n: GOOD), _messagebox(mb):
                assert app._sldea_preflight(3, 0) is answer
        finally:
            sldea_profile.preflight_report = real
        [(kind, _title, msg, kw)] = mb.calls
        assert kind == 'askyesno' and kw == {'default': 'no'}, mb.calls
        assert 'report blew up' in msg and 'Start the run anyway?' in msg
        assert 'the picture check failed (report blew up)' in app.lines[0]
        assert ('picture unchecked' in app.lines[-1]) is answer, app.lines
        # the camera gave a frame, so the run expects a baseline frame;
        # an unchecked start is not the flat override
        assert app._sldea_preflight_seen == SEEN_FRAME, \
            app._sldea_preflight_seen


# --------------------------------------------------------------------------
# The REAL dialog (one small window each; skipped without a display)
# --------------------------------------------------------------------------

class _Dlg:
    """What a test may ask of the open pre-flight window."""

    def __init__(self, win):
        import tkinter as tk
        from tkinter import ttk
        self.win = win
        self.labels = [w for w in win.winfo_children()
                       if isinstance(w, tk.Label) and w.cget('text')]
        self.buttons = [b for f in win.winfo_children()
                        if isinstance(f, ttk.Frame)
                        for b in f.winfo_children()
                        if isinstance(b, ttk.Button)]
        assert len(self.buttons) == 3, self.buttons
        self.start, self.adjust, self.cancel = self.buttons

    def texts(self):
        return [w.cget('text') for w in self.labels]

    def label(self, fragment):
        [w] = [w for w in self.labels if fragment in w.cget('text')]
        return w

    def is_bold(self, fragment):
        return 'bold' in str(self.label(fragment).cget('font'))

    def return_starts(self):
        return bool(self.win.bind('<Return>'))

    def focused(self):
        return self.win.focus_lastfor()

    def press_return(self):
        """Send Return to the window and to the focused widget; nothing
        may come of it unless the dialog bound it."""
        for w in (self.win, self.focused()):
            w.event_generate('<Return>')
        self.win.update()

    def alive(self):
        return bool(self.win.winfo_exists())


def _dialog(frame, lock, probe, answers=None, cam=(3, 0),
            device='/dev/video0', boxes=('3', '0')):
    """Open the REAL pre-flight on `frame` with `lock` as the Webcam-tab
    lock, hand the window to `probe(dlg, app, mb)`, close whatever it
    left open, and return (what the pre-flight returned, app, mb, camera
    record, the lock afterwards)."""
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    root.geometry('240x60+30+30')
    app = _FlightApp(root, boxes)
    mb = _MB(answers)
    seen = {'tries': 0}

    def run_probe():
        wins = [w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel)]
        if not wins or not wins[0].winfo_ismapped():
            seen['tries'] += 1
            if seen['tries'] < 60:
                root.after(100, run_probe)
                return
            # a display that never maps the window cannot show its focus
            seen['error'] = _Skip("the pre-flight window never mapped here")
            for w in wins:
                w.destroy()
            return
        try:
            assert len(wins) == 1, wins
            wins[0].update()
            seen['probed'] = True
            probe(_Dlg(wins[0]), app, mb)
        except BaseException as e:           # a callback's traceback is lost
            seen['error'] = e
        finally:
            for w in wins:
                if w.winfo_exists():
                    w.destroy()

    try:
        with _lock(lock), _messagebox(mb), \
                _camera(lambda n: frame, device=device) as camrec:
            root.after(300, run_probe)
            seen['go'] = app._sldea_preflight(*cam)
            lock_after = dict(webcam.LOCKED_CONTROLS)
    finally:
        root.destroy()
    if 'error' in seen:
        raise seen['error']
    assert seen.get('probed'), "the dialog closed before it was looked at"
    return seen['go'], app, mb, camrec, lock_after


RUN_CONTROLS = [('auto_exposure', 1), ('white_balance_automatic', 0),
                ('exposure_time_absolute', 3), ('gain', 0)]


def test_dialog_a_flat_frame_cannot_be_started_by_return_or_by_one_click():
    def probe(dlg, app, mb):
        assert dlg.start.cget('text').endswith('Start anyway (no picture)')
        assert not dlg.return_starts(), "Return is bound on a flat frame"
        assert dlg.focused() == dlg.adjust, dlg.focused()
        # ttk buttons take Space, not Return: nothing else can start it
        assert not dlg.win.bind_class('TButton', '<Return>')
        assert not dlg.win.bind_class('TButton', '<Key-Return>')
        assert dlg.is_bold('NO PICTURE: the frame is flat')
        assert 'contrast 2 gray levels' in ' '.join(dlg.texts())
        assert any(t.startswith('Camera for this run: exposure 3, gain 0')
                   for t in dlg.texts()), dlg.texts()
        dlg.press_return()
        assert dlg.alive() and mb.calls == [], mb.calls
        dlg.start.invoke()                   # first click: asked, says No
        assert dlg.alive(), "one click started a run on a flat frame"
        [(kind, title, msg, kw)] = mb.calls
        assert (kind, title) == ('askyesno', FLAT_Q), mb.calls
        assert kw.get('default') == 'no', kw
        assert 'NO PICTURE' in msg and 'Start the run anyway?' in msg
        # the question says what Yes does since 2026-10-03: the run
        # will not stop itself on a flat baseline
        assert 'the run will NOT stop itself on a flat baseline' in msg
        assert 'setup.txt records that you started anyway' in msg, msg
        assert 'stops itself' not in msg, msg
        assert not any('ANYWAY' in ln for ln in app.lines), app.lines
        assert app._sldea_preflight_seen == SEEN_FRAME, "No is no override"
        dlg.start.invoke()                   # second click: says Yes
        assert not dlg.alive()

    go, app, mb, cam, lock_after = _dialog(
        FLAT, {}, probe, answers={FLAT_Q: [False, True]})
    assert go is True
    assert app.lines[0].endswith('verdict FLAT'), app.lines
    assert 'mean 66, saturated 0.0%, contrast 2 gray levels' in app.lines[0]
    assert app.lines[-1].endswith(
        'operator started the run ANYWAY on a flat pre-flight frame '
        '(no picture): the baseline picture stop is OFF for this run'), \
        app.lines
    # Yes IS the override, and it is left for the start path to pass on
    assert app._sldea_preflight_seen == SEEN_OVERRIDE, \
        app._sldea_preflight_seen
    # the camera was asked exactly what it always was, in the same order
    assert cam['controls'] == RUN_CONTROLS and cam['grabs'] == 1, cam


def test_dialog_a_normal_frame_keeps_start_as_the_default():
    def probe(dlg, app, mb):
        assert 'Looks good' in dlg.start.cget('text')
        assert dlg.return_starts()
        assert dlg.focused() == dlg.start, dlg.focused()
        assert not dlg.is_bold('exposure OK')
        assert not any('NOT taken' in t for t in dlg.texts()), dlg.texts()
        dlg.start.invoke()
        assert not dlg.alive()

    go, app, mb, cam, lock_after = _dialog(GOOD, {}, probe)
    assert go is True and mb.calls == [], mb.calls
    assert app.lines[0].endswith('verdict OK'), app.lines
    assert not any('ANYWAY' in ln for ln in app.lines), app.lines
    assert not any('operator pressed' in ln for ln in app.lines), app.lines
    assert app._sldea_preflight_seen == SEEN_FRAME, app._sldea_preflight_seen


def test_the_preflight_keeps_the_camera_it_found_for_setup_txt():
    """#400: setup.txt records the camera a run used. The pre-flight
    already resolves the camera and takes a picture, so it keeps the spec
    and the picture's size for the run's camera block
    (_sldea_preflight_camera), with no camera I/O of its own; what it
    leaves for the start path is unchanged."""
    mb = _MB({'Camera pre-flight': False})
    app = _FlightApp()
    with _camera(lambda n: None, device='/dev/video0'), _messagebox(mb):
        assert app._sldea_preflight(3, 0) is False
    # no picture: the camera is named, without a size
    assert app._sldea_preflight_camera == {
        'kind': 'cv2', 'index': 0, 'device': '/dev/video0'}, \
        app._sldea_preflight_camera
    assert app._sldea_preflight_seen == SEEN_NONE

    def probe(dlg, app, mb):
        dlg.start.invoke()

    go, app, mb, cam, _lock_after = _dialog(GOOD, {}, probe)
    assert go is True and cam['grabs'] == 1, (go, cam)
    assert app._sldea_preflight_camera == {
        'kind': 'cv2', 'index': 0, 'device': '/dev/video0',
        'frame': (GOOD.shape[1], GOOD.shape[0])}, \
        app._sldea_preflight_camera
    assert app._sldea_preflight_seen == SEEN_FRAME


def test_dialog_starting_past_a_warning_is_one_click_and_one_log_line():
    """dark, bright and a preview mismatch are warnings, not gates: no
    second question. They still cost the default button, and the click
    that starts the run is written down."""
    def probe(dlg, app, mb):
        assert dlg.start.cget('text').endswith(
            'Start anyway (exposure warning)'), dlg.start.cget('text')
        assert not dlg.return_starts()
        assert dlg.focused() == dlg.adjust, dlg.focused()
        dlg.press_return()
        assert dlg.alive()
        dlg.start.invoke()
        assert not dlg.alive()

    go, app, mb, cam, lock_after = _dialog(_halves(10, 50), {}, probe)
    assert go is True and mb.calls == [], mb.calls
    assert app.lines[0].endswith('verdict DARK'), app.lines
    assert app.lines[-1].endswith(
        'operator pressed: \u26a0 Start anyway (exposure warning)'), app.lines


def test_dialog_a_webcam_lock_that_is_not_the_runs_is_said_in_bold():
    """Merged with #361 (2026-10-06). The pre-flight frame is now taken
    under the run's own lock, so it IS the run's picture: #348's bold
    'This preview was NOT taken with the run's settings' stays away. What
    differs is the Webcam tab's LIVE preview, which runs on its lock:
    #361's sentence says so in bold, and as a warning it costs the start
    button its default, so Return cannot start the run (#348's rule)."""
    lock = {'exposure_time_absolute': 30, 'gain': 0, 'brightness': 240}

    def probe(dlg, app, mb):
        assert not any('NOT taken' in t for t in dlg.texts()), dlg.texts()
        assert dlg.is_bold("The Webcam tab's fields differ from its lock")
        sentence = dlg.label("fields differ from its lock").cget('text')
        assert 'exposure 3 (locked: 30)' in sentence, sentence
        assert dlg.start.cget('text') == \
            sldea_profile.PREFLIGHT_START_LOCK_DIFFERS, dlg.start.cget('text')
        assert not dlg.return_starts()
        assert dlg.focused() == dlg.adjust, dlg.focused()
        dlg.press_return()
        assert dlg.alive()
        dlg.cancel.invoke()
        assert not dlg.alive()

    go, app, mb, cam, lock_after = _dialog(GOOD, lock, probe)
    assert go is False and mb.calls == [] and app.tabs == []
    assert any('fields differ from its lock' in ln for ln in app.lines), \
        app.lines
    assert not any('NOT taken' in ln for ln in app.lines), app.lines
    # the frame the check judged was taken under the run's lock
    assert any('the lock this frame was taken under agrees' in ln
               for ln in app.lines), app.lines
    # Cancel leaves the camera as the pre-flight always left it: the same
    # four writes, one grab, and the Webcam-tab lock put back as it was
    assert cam['controls'] == RUN_CONTROLS and cam['grabs'] == 1, cam
    assert lock_after == lock, lock_after


def test_dialog_a_clean_picture_with_a_differing_lock_starts_by_click():
    """The same differing lock on a clean picture: one click starts the
    run (a warning, not a gate), and run.log says which button it was."""
    lock = {'exposure_time_absolute': 30, 'gain': 0}

    def probe(dlg, app, mb):
        dlg.start.invoke()
        assert not dlg.alive()

    go, app, mb, cam, lock_after = _dialog(GOOD, lock, probe)
    assert go is True and mb.calls == [], mb.calls
    assert app.lines[-1].endswith(
        'operator pressed: ' + sldea_profile.PREFLIGHT_START_LOCK_DIFFERS), \
        app.lines
    assert lock_after == lock, lock_after


def test_dialog_a_camera_with_no_device_path_has_no_lock_to_disagree_with():
    """A camera with no device path is stamped by neither the pre-flight
    nor the run (both gate their control writes on it), so preview and
    run are the same picture whatever the lock dict holds. The warning
    would be untrue there, and it would take the default button away
    from every run on such a camera."""
    lock = {'exposure_time_absolute': 30, 'gain': 0}

    def probe(dlg, app, mb):
        assert not any('NOT taken' in t for t in dlg.texts()), dlg.texts()
        assert 'Looks good' in dlg.start.cget('text')
        assert dlg.return_starts() and dlg.focused() == dlg.start
        dlg.cancel.invoke()

    go, app, mb, cam, lock_after = _dialog(GOOD, lock, probe, device=None)
    assert go is False and cam['controls'] == [] and cam['grabs'] == 1, cam
    assert not any('NOT taken' in ln for ln in app.lines), app.lines
    assert lock_after == lock, lock_after


def test_dialog_fallback_camera_values_are_called_built_in_defaults():
    def probe(dlg, app, mb):
        line = dlg.label('Camera for this run').cget('text')
        assert 'exposure 6, gain 60' in line, line
        assert 'The exposure and gain are built-in defaults' in line, line
        assert 'set on the Webcam tab' not in line, line
        dlg.cancel.invoke()

    go, app, mb, cam, lock_after = _dialog(GOOD, {}, probe, cam=(6, 60),
                                          boxes=None)
    assert go is False
    assert cam['controls'] == [('auto_exposure', 1),
                               ('white_balance_automatic', 0),
                               ('exposure_time_absolute', 6),
                               ('gain', 60)], cam


def test_dialog_adjust_cancels_the_run_and_opens_the_webcam_tab():
    def probe(dlg, app, mb):
        dlg.adjust.invoke()
        assert not dlg.alive()

    go, app, mb, cam, lock_after = _dialog(FLAT, {}, probe)
    assert go is False and app.tabs == ['webcam'] and mb.calls == []
    assert not any('ANYWAY' in ln for ln in app.lines), app.lines


def test_dialog_a_clipped_frame_still_asks_its_own_question():
    white = _rgb(_np.full((240, 320), 255.0))

    def probe(dlg, app, mb):
        assert 'blown out' in dlg.start.cget('text')
        assert not dlg.return_starts()
        assert dlg.focused() == dlg.adjust
        assert dlg.is_bold('BASELINE IS CLIPPED')
        dlg.start.invoke()
        assert not dlg.alive()

    go, app, mb, cam, lock_after = _dialog(white, {}, probe,
                                          answers={CLIP_Q: True})
    assert go is True and mb.titles('askyesno') == [CLIP_Q], mb.calls
    assert app.lines[0].endswith('verdict CLIPPED'), app.lines
    assert app.lines[-1].endswith('ANYWAY on a blown-out baseline')
    # a clipped start is not the flat override: the run still stops
    # itself if its own baseline turns out flat
    assert app._sldea_preflight_seen == SEEN_FRAME, app._sldea_preflight_seen


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block (run_tests.py explains why).
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    ran = skipped = 0
    failed = []
    for fn in fns:
        try:
            fn()
        except _Skip as why:
            skipped += 1
            print(f"skip {fn.__name__}  ({why})")
            continue
        except Exception:
            # A test that blew up still RAN: only a skip is "did not run".
            ran += 1
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
        ran += 1
        print(f"ok  {fn.__name__}")
    tail = f"{ran} of {len(fns)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped)"
    print(f"\n{tail}")
    if not failed:
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
