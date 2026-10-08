#!/usr/bin/env python3
"""Single-Layer DEA (SLDEA) test profile: staircase drive, snapshot schedule,
and run layout. Pure logic -- no hardware, no Tk -- so it is unit-testable and
drives both the GUI preview and the run executor.

Drive chain: the signal generator outputs a DC *control* voltage into a Trek
HV amplifier. Gain is 1 V(control) = 1 kV(Trek); the Trek maxes at 10 kV, so
the control voltage is clamped to 10 V. There is no DMM here -- the Trek's own
monitor BNCs are read on the oscilloscope:
    V_Out : 10 V on the scope = 10 kV on the Trek   -> 1 kV per scope-volt
    I_Out : 10 V on the scope = 2000 uA on the Trek -> 200 uA per scope-volt

A run captures a webcam frame near the end of the ramp (settled) and again
just before the next step, at every landing, plus a 0 kV baseline -- for the
later edge-detection pass that traces the active DEA area vs voltage.

Headless self-test: .venv/bin/python tests/test_sldea_profile.py
"""

HV_GAIN_KV_PER_V = 1.0      # 1 V control -> 1 kV Trek output
TREK_MAX_KV = 10.0          # Trek amplifier ceiling
VMON_KV_PER_V = 1.0         # scope V_Out: 1 scope-volt -> 1 kV
IMON_UA_PER_V = 200.0       # scope I_Out: 1 scope-volt -> 200 uA (10 V = 2000 uA)


def control_v_for_kv(kv):
    """SG control voltage for a desired Trek output (kV)."""
    return kv / HV_GAIN_KV_PER_V


def measured_kv(vmon_scope_v):
    """Trek output (kV) from the scope's V_Out reading (volts)."""
    return vmon_scope_v * VMON_KV_PER_V


def measured_ua(imon_scope_v):
    """Trek current (uA) from the scope's I_Out reading (volts)."""
    return imon_scope_v * IMON_UA_PER_V


# The study compares COMPLIANT ELECTRODE MATERIALS: CNT so far, carbon
# black since 2026-08-05, liquid metal expected. Recorded per run so the
# campaign's device class lives in the data instead of in folder names,
# and so per-family detection defaults have something to key on later
# (#229). Free text is allowed -- the list is a convenience, not a
# constraint; an unrecognised entry is kept verbatim and families out to
# 'other'.
#
# The CNT inks are listed by BRAND (`#272`), not by the in-lab shorthand
# ("P2 ink", "P3 ink"): the brand is what can be re-ordered, cited, and
# matched against a datasheet, and the shorthand already lives in the run
# folder names. Generic 'CNT' stays because it is the vocabulary every
# run recorded before this list existed, and dropping it would strand
# that value.
#
# There is deliberately NO literal 'other' entry (`#272`). It is a
# non-answer that looks like an answer: a run recorded as "other" says
# only that the material is not on a list that has since changed. Typing
# the real material is now advertised on the box and costs the same
# click, and a genuinely unknown sample is BLANK -- which the run-start
# prompt already treats as a deliberate choice. 'other' remains a FAMILY
# below, so runs that recorded the literal string still canonicalise
# exactly as they always did.
ELECTRODE_CHOICES = ('', 'CNT',
                     'Carbon Solutions P3-SWNT', 'Carbon Solutions P2-SWNT',
                     # The Invisicon pair is the WHOLE nano-c offering here.
                     # A '<n> Spray' pair was added alongside them
                     # 2026-08-12 and removed 2026-08-13: they name the same
                     # two products, and two dropdown entries for one
                     # material is how a corpus ends up with a family split
                     # across spellings that no analysis can rejoin.
                     'nano-c Invisicon 3900', 'nano-c Invisicon 3500',
                     'carbon black', 'eGaIn')
# Substring needles, matched against the lowercased value padded with
# spaces. None of the six brand names contains "cnt", so the CNT family
# also keys on what the products ARE: 'swnt'/'mwnt' (Carbon Solutions
# sells single-wall nanotube ink) and the 'invisicon' brand (nano-c's
# transparent CNT ink). Order matters -- the first family that matches
# wins.
#
# 'nanoc ' carries a TRAILING SPACE on purpose. The spray entries added
# 2026-08-12 were first proposed as "NanoC 3500 Spray", which matched no
# needle at all and canonicalised to 'other' -- a silent
# mis-classification, since nothing downstream can tell a deliberate
# 'other' from a brand nobody taught the matcher. The hyphenless
# spelling is what an operator types, so it is accepted here rather than
# only in the dropdown. The space is what keeps it from also swallowing
# 'nanocomposite', 'nanoclay' and 'nanocellulose', which are plausible
# electrode materials and are NOT nanotube ink -- the same guard the
# 'cb ' / ' cb' needles below already use.
_ELECTRODE_FAMILIES = (
    ('cnt', ('cnt', 'carbon nanotube', 'nanotube', 'swnt', 'mwnt',
             'invisicon', 'nano-c', 'nanoc ')),
    ('carbon_black', ('carbon black', 'carbonblack', 'cb ', ' cb', 'c-black')),
    ('liquid_metal', ('egain', 'e-gain', 'galinstan', 'liquid metal',
                      'liquidmetal')),
)


def electrode_family(text):
    """Free-text electrode -> a canonical family, or None when blank.

    'CNT' / 'carbon black' / 'eGaIn', the branded CNT inks in
    ELECTRODE_CHOICES, and their obvious spellings map to 'cnt' /
    'carbon_black' / 'liquid_metal'; anything else non-blank is 'other'.
    Nothing keys off this yet -- it exists so that when the detector needs
    per-family behaviour (#229: a mirror-bright electrode inverts the
    dark-disc assumption) there is one place that decides what family a
    run belongs to.

    Matching is case-insensitive, ignores surrounding whitespace, and is
    on substrings, so a hand-typed 'p3-swnt', 'SWNT ink' or
    'Invisicon 3900' still lands in 'cnt'. It does NOT guess from the
    campaign's device tokens alone: a bare 'P2' or 'P3' names a device,
    not a material, and is 'other'."""
    t = (text or '').strip().lower()
    if not t:
        return None
    padded = f' {t} '
    for family, needles in _ELECTRODE_FAMILIES:
        if any(nd in padded for nd in needles):
            return family
    return 'other'


# NOT DISPENSED AS A MEASURED VOLUME. A second axis, deliberately separate
# from _ELECTRODE_FAMILIES: folding "no concentration" into the family
# would force these into their own family or into 'other', and either one
# splits the CNT group that `#268`'s aggregate exists to draw. A
# spray-applied CNT is still `cnt` and still averages with every other CNT
# run; it just has no millilitres to record.
#
# Two kinds of needle, and the distinction is worth keeping straight:
#
#   'spray'      -- an application METHOD, for the free-text case where an
#                   operator types how the electrode went on.
#   'invisicon'  -- a PRODUCT that is only ever sprayed. nano-c's Invisicon
#                   pair is the lab's spray (Anatol, 2026-08-13, when the
#                   duplicate '<n> Spray' dropdown entries were dropped as
#                   the same two products). Keyed on the brand rather than
#                   on the two full entry strings so a hand-typed
#                   'Invisicon 3900' answers the same way the dropdown does.
_NO_CONCENTRATION_NEEDLES = ('spray', 'invisicon')


def concentration_applies(electrode):
    """Is an ink concentration a meaningful thing to record here? (`#276`)

    The Concentration (mL) field records the CNT INK VOLUME -- the '2.5mL'
    in a folder name like P3_2.5mL_Triazole, which is how the campaign has
    been carrying it. Carbon black and liquid metal are not inks dispensed
    by volume, so for those it is meaningless: the field is greyed, the run
    never asks about it, and setup.txt does not carry the key at all. A CB
    run should not look like a CNT run that forgot to fill something in.

    SPRAYED electrodes are excluded for the same reason but on a different
    axis (2026-08-12): a spray goes on as coats, not as a measured
    millilitre, so the number would be a fiction. That covers the
    nano-c Invisicon pair, which is this lab's spray (2026-08-13). The
    material is unchanged either way -- Invisicon is still family `cnt`
    and still averages with every other CNT run.

    Everything else may have one and is offered it: the CNT family, and any
    custom material the operator typed (we do not know that a material we
    have never heard of is not an ink).

    BLANK counts as applicable. "No electrode chosen yet" is not the same
    fact as "this electrode has no concentration", and greying the box
    before the operator has said what the device is would just look broken.
    """
    padded = f" {(electrode or '').strip().lower()} "
    if any(nd in padded for nd in _NO_CONCENTRATION_NEEDLES):
        return False
    return electrode_family(electrode) not in ('carbon_black', 'liquid_metal')


def parse_concentration_ml(text):
    """Concentration text -> a positive float, or ValueError (`#276`).

    Junk, zero, negatives, nan and inf are all refused: this number goes
    into setup.txt as a fact about the device, and "0 mL of ink" is not a
    measurement anyone meant to record. A BLANK string is refused here
    too -- "nothing entered" is a question to put to the operator, not a
    parse result, and the run asks it separately.
    """
    import math
    s = str(text or '').strip()
    value = float(s)                       # ValueError on blank or junk
    if not math.isfinite(value) or value <= 0:
        raise ValueError(
            f"concentration must be a positive number of mL, got {s!r}")
    return value


# The FILM THICKNESS (`#398`): t0, in micrometres, measured with the film
# MOUNTED AND PRESTRETCHED (owner decision 2026-10-06), so the number the
# operator types is the thickness the plot's nominal field E = V / t0
# divides by, with no prestretch correction anywhere. One value per run and
# no +/- field, by the same decision. setup.txt carries it beside the
# electrode as 'Film thickness: 50 um'.
#
# 'um', in ASCII, and not the micro sign the issue's text and the SLDEA
# tab's label use (owner decision 2026-10-07). The runner writes setup.txt
# with the LOCALE codec, which the runner's own comments say to keep ASCII
# so the open cannot refuse a line: on a cp932, cp936 or cp949 Windows PC
# the micro sign raises UnicodeEncodeError on the first write, and on a
# cp1252 one it lands as byte 0xB5, which every reader here decodes as
# U+FFFD. The file already says 'uA' rather than the micro-amp sign.
FILM_THICKNESS_UNIT = 'um'

# A recorded value's unit, as film_thickness_um reads it: the 'um' the
# runner writes, and for a hand-edited line the micro sign, the Greek small
# mu and U+FFFD. The last is a micro sign written in cp1252 and read back
# as UTF-8 with errors='replace', which is how every reader of setup.txt
# opens it, and how Edge Review's Save then rewrites the file.
_THICKNESS_UNIT_RE = r'(?:[\u00b5\u03bcu\ufffd]m)?'


# The NUMBER a thickness is written as, for the box and for the recorded
# line alike: ASCII digits, an optional point and exponent. ONE pattern,
# because the box used to take whatever float() takes, which is more than
# the reader read back: '1_000', fullwidth and Arabic-Indic digits, and
# '50.' (the old reader wanted a digit after the point). Such a value
# passed at Run and was then left off the field axis as unreadable
# (adversarial review 2026-10-07). Now the box refuses at Run whatever the
# reader cannot read.
_THICKNESS_NUMBER_RE = (r'[-+]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)'
                        r'(?:[eE][-+]?[0-9]+)?')

# The range a film thickness is expected in, in um, outside which the run
# asks before it starts (`#398`, review 2026-10-07). Prestretched elastomer
# films are tens to hundreds of um thick, which sits inside with room at
# both ends. And the range spans a factor of 400, less than 1000, so any
# thickness inside it typed in the wrong unit lands outside it: in mm
# (0.05 for 50 um) below 5, in nm above 2000. A question, never a refusal:
# an unusual film is still the operator's to run.
FILM_THICKNESS_PLAUSIBLE_UM = (5.0, 2000.0)


def parse_film_thickness_um(text):
    """Film thickness text -> a positive float in um, or ValueError
    (`#398`).

    parse_concentration_ml's rule, for its reason: the number goes into
    setup.txt as a fact about the device, so junk, zero, negatives, nan
    and inf are refused, and so is a blank, which is a question the run
    asks separately. A bare number only, in _THICKNESS_NUMBER_RE, the
    pattern film_thickness_um reads the recorded line with, so nothing
    the box accepts can come back unreadable. The box is labelled in um,
    and a unit typed into it is refused, as '2.5 mL' is in the
    concentration box, rather than guessed at."""
    import math
    import re
    s = str(text or '').strip()
    if re.fullmatch(_THICKNESS_NUMBER_RE, s) is None:
        raise ValueError(
            f"film thickness must be a number in um, got {s!r}")
    value = float(s)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(
            f"film thickness must be a positive number of um, got {s!r}")
    return value


def film_thickness_plausible(t0_um):
    """Is `t0_um` inside FILM_THICKNESS_PLAUSIBLE_UM? (`#398`) The run
    asks before it starts on one that is not."""
    lo, hi = FILM_THICKNESS_PLAUSIBLE_UM
    return lo <= t0_um <= hi


def film_thickness_um(recorded):
    """A recorded `Film thickness:` value -> t0 in um, or None when there
    is none to use (`#398`).

    `recorded` is what sldea_edge.film_thickness_of returns: None when the
    line is absent, '(not specified)' when the operator declined, else the
    value as written. The first two are None here, and so is a value that
    is not a positive number in um; a caller that has to say WHY tells
    them apart from the recorded text.

    The value the runner writes ('50 um'), the same with no space, with
    the micro sign or the Greek mu, with the U+FFFD a cp1252 write of a
    micro sign leaves (_THICKNESS_UNIT_RE), and a bare number all read as
    that number: the first is what the runner writes and the others are
    what a hand edit or an older Windows run produce. The number is
    _THICKNESS_NUMBER_RE, the box's own pattern. Any other unit
    ('0.05 mm') is None rather than a guess."""
    import re
    m = re.fullmatch(r'\s*(' + _THICKNESS_NUMBER_RE + r')\s*'
                     + _THICKNESS_UNIT_RE + r'\s*', str(recorded or ''),
                     re.IGNORECASE)
    if m is None:
        return None
    try:
        return parse_film_thickness_um(m.group(1))
    except ValueError:
        return None


def compute_levels(start_kv, end_kv, step_kv=None, n_steps=None):
    """Ordered list of landing voltages (kV).

    With step_kv: exact `step_kv` increments from start, last <= end.
    With n_steps: linspace with exact endpoints (start..end, n_steps levels).
    """
    if step_kv is not None and step_kv > 0:
        span = abs(end_kv - start_kv)
        n = int(span / step_kv + 1e-9) + 1
        sgn = 1.0 if end_kv >= start_kv else -1.0
        return [round(start_kv + sgn * i * step_kv, 6) for i in range(n)]
    if n_steps is not None and int(n_steps) >= 1:
        n = int(n_steps)
        if n == 1:
            return [end_kv]
        return [round(start_kv + (end_kv - start_kv) * i / (n - 1), 6)
                for i in range(n)]
    raise ValueError("give a positive step_kv or n_steps >= 1")


def fmt_duration(seconds):
    s = int(round(seconds))
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


# Seconds between the throw-away 0 kV frame and the real baseline. The
# camera's firmware re-decides exposure on every open and walks written
# values back within ~0.5 s (webcam.apply_locked), so the FIRST frame of
# a session is the one most likely to be mis-exposed -- measured on the
# 2026-08-05 CB run, whose baseline was 73.7% saturated while its own
# ramp frames were 0.27%. Two seconds costs nothing and the staircase
# does not start until after it.
BASELINE_WARMUP_S = 2.0

SCOPE_DIVISIONS = 8          # MSO24 vertical divisions
BNC_ATTEN = 1.0              # bench convention: monitors are direct BNC


def suggested_scale(volts_needed, divisions=SCOPE_DIVISIONS):
    """A sane V/div that puts `volts_needed` on screen with headroom."""
    from math import ceil
    if volts_needed <= 0:
        return 1.0
    raw = (volts_needed * 1.3) / divisions        # 30% headroom
    for step in (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0):
        if step >= raw:
            return step
    return 10.0


def monitor_problems(max_kv, v_scale=None, v_atten=None, i_scale=None,
                     i_atten=None, breakdown_ua=100.0,
                     divisions=SCOPE_DIVISIONS,
                     v_position=None, v_offset=None,
                     i_position=None, i_offset=None, v_sign=1.0):
    """Problems with the scope's Trek-monitor channel setup, as readable
    strings (empty list = ready to run).

    Bench 2026-07-25: CH2 sat at 2.6 mV/div while V_Out swings 0-10 V, so
    the MSO24 returned its invalid sentinel for nearly every reading and
    FIVE runs recorded no usable measured_kV at all; CH3 additionally
    carried a 10x attenuation factor with a plain BNC cable, inflating
    every logged current tenfold. Both are invisible from the GUI, so a
    live run now checks them up front.

    Bench 2026-07-29: the raw-span check is not enough — all three runs
    that day clipped from 4.25 kV with the check passing, because CH2 sat
    at 1 V/div with POSITION 0 (visible window ±4 V) for a 6 kV run: span
    8 V >= 6 V, but the top of screen was 4 V. When position and offset
    are known, the ACTUAL visible window (centre = offset, shifted down
    by position divisions) is checked instead of the span. Unknown values
    (query failed) are still never guessed at — the caller is expected to
    say which channels went unverified.

    `v_sign` (+1/-1) is the Trek monitor polarity: with the 'Trek
    inverts' option the amplifier is driven negative and V_Out swings
    0..-need, so the V window must contain 0 and v_sign*need — a window
    framed for a positive-going monitor would clip every reading of an
    inverted run while this check passed (review 2026-08-04).

    The I window must contain ±i_need regardless of drive polarity:
    every real breakdown in the 2026-08-04 ground-truth batch swings
    NEGATIVE (-27..-208 uA) while the old check only demanded that 0 V
    be on screen — a window 0..top would clip the one excursion the
    watchdog exists to see."""
    out = []
    v_need = float(max_kv) / VMON_KV_PER_V
    i_need = max(1.0, 2.0 * float(breakdown_ua) / IMON_UA_PER_V)
    v_lo, v_hi = (0.0, v_need) if v_sign >= 0 else (-v_need, 0.0)
    for label, scale, atten, span_need, lo, hi, pos, off in (
            ('V_Out', v_scale, v_atten, v_need, v_lo, v_hi,
             v_position, v_offset),
            ('I_Out', i_scale, i_atten, 2.0 * i_need, -i_need, i_need,
             i_position, i_offset)):
        if atten is not None and abs(float(atten) - BNC_ATTEN) > 1e-6:
            out.append(
                f"{label}: scope thinks a {float(atten):g}x probe is fitted, "
                f"but the monitors use direct BNC — readings would be "
                f"{float(atten):g}x off.")
        if scale is not None:
            span = float(scale) * divisions
            if span < span_need:
                out.append(
                    f"{label}: {float(scale):g} V/div shows only ±"
                    f"{span / 2:.3g} V, but this run needs {span_need:.3g} V "
                    f"({'up to %g kV' % max_kv if label == 'V_Out' else 'bipolar breakdown headroom'})"
                    f" — readings will go off-screen and log as blank.")
            elif pos is not None and off is not None:
                top = float(off) + (divisions / 2.0 - float(pos)) * float(scale)
                bot = float(off) - (divisions / 2.0 + float(pos)) * float(scale)
                if label == 'V_Out' and (top < hi or bot > lo):
                    out.append(
                        f"V_Out: visible window {bot:g}..{top:g} V "
                        f"({float(scale):g} V/div, position {float(pos):g} "
                        f"div, offset {float(off):g} V) cannot show "
                        f"{lo:g}..{hi:g} V"
                        f"{' (Trek inverted)' if v_sign < 0 else ''} — "
                        f"readings past the screen edge log as blank.")
                elif label == 'I_Out' and (top < hi or bot > lo):
                    out.append(
                        f"I_Out: visible window {bot:g}..{top:g} V cannot "
                        f"show ±{hi:g} V — real breakdowns swing negative "
                        f"(-27..-208 uA on the 08-04 batch); the excursion "
                        f"would clip off-screen and log as blank.")
    return out


def monitor_fix_plan(max_kv, breakdown_ua=100.0, divisions=SCOPE_DIVISIONS,
                     v_sign=1.0):
    """{'v_scale','i_scale','atten','v_position','i_position'} that would
    satisfy monitor_problems() for this run.

    V_Out gets position -3 (or +3 when the Trek is inverted, v_sign=-1)
    so the unipolar 0..±need swing uses the screen asymmetrically;
    I_Out gets position 0 with a scale sized for the full ±i_need swing
    — the current excursion is bipolar-negative and a -3 position left
    only one division below 0 V (review 2026-08-04)."""
    v_need = float(max_kv) / VMON_KV_PER_V
    i_need = max(1.0, 2.0 * float(breakdown_ua) / IMON_UA_PER_V)
    return {'v_scale': suggested_scale(v_need, divisions),
            'i_scale': suggested_scale(2.0 * i_need, divisions),
            'atten': BNC_ATTEN,
            'v_position': 3.0 if v_sign < 0 else -3.0,
            'i_position': 0.0}


# Baseline exposure gates, calibrated on the real corpus rather than
# guessed. Measured over all 14 baselines held on 2026-08-05: every
# healthy run sits at mean 128-190 with 0.12-3.62% of pixels at/above
# 250. The carbon-black validation run sits at mean 235, MEDIAN 255,
# 73.7% saturated -- twenty times the worst healthy run. The warn tier
# was already well placed (it fires on that run and on nothing else);
# what was missing is a tier that actually stops you.
BASELINE_DARK_MEAN = 40.0
BASELINE_BRIGHT_MEAN = 215.0
BASELINE_BRIGHT_SAT_PCT = 8.0
# The gate sits 5.5x above the worst healthy baseline and 3.7x below the
# blown-out one, so it separates the two populations with room to spare.
BASELINE_CLIP_MEAN = 225.0
BASELINE_CLIP_SAT_PCT = 20.0


# Which way to send the operator when a frame is flat. Below this mean
# the frame is darker than any usable baseline in the corpus (the lowest
# of the 15 usable baselines reads mean 116, the flat 2026-10-01 run 67;
# measured 2026-10-02), so more exposure or light is the fix.
FLAT_DARK_MEAN = 100.0


def flat_message(contrast, mean):
    """Operator wording for a frame that holds no picture."""
    m = float(mean)
    if m > BASELINE_BRIGHT_MEAN:
        advice = "Lower the exposure or the light on the Webcam tab."
    elif m < FLAT_DARK_MEAN:
        advice = "Raise the exposure or the light on the Webcam tab."
    else:
        # A dark disc that covers under 5 % of the central window does
        # not move p5, so on an even background it reads flat although
        # it is in the picture (measured 2026-10-02 at 1920x1080: a
        # 308 px disc reads contrast 10, a 310 px one 63). A third of
        # the picture's height clears that limit with room; the
        # smallest fitted disc in the corpus is 361 px of 1080.
        advice = ("Check that the device is under the camera and that "
                  "the disc is at least a third of the picture's height "
                  "across, then the exposure and the light on the Webcam "
                  "tab.")
    return (f"NO PICTURE: the frame is flat (contrast {float(contrast):.0f} "
            f"gray levels). The disc is not visible. {advice}")


def exposure_verdict(mean, sat_pct, content=None):
    """Baseline exposure -> ('ok'|'dark'|'bright'|'clipped'|'flat', message).

    'clipped' is a GATE, but be precise about WHY, because the obvious
    reason turned out to be wrong when it was measured (2026-08-05, the
    CB run): a clipped BACKGROUND does not stop the detector. That run's
    baseline was 73.7% saturated and it still traced every level at conf
    0.98-0.99 with a monotonic area curve -- the electrode disc itself
    sat at median 89, nowhere near clipping, so the boundary was a
    ~165-level step and if anything easier to find than usual.

    What is actually wrong with a clipped baseline:
      * clipped pixels carry no information the gain/offset
        normalisation can recover -- `photometric_fit` can only scale
        what still varies;
      * and it is evidence the exposure was not pinned. On that same
        run the baseline was 73.7% saturated while its own ramp frames
        were 0.27%, so the reference frame was shot at a different
        exposure from everything it is differenced against.
    Both are reasons to fix the exposure. Neither is a reason to claim
    the measurement is worthless, so this no longer says that.

    'flat' is the second GATE (2026-10-02). `content` is
    sldea_edge.image_content's dict for the same frame; without it the
    older tiers answer exactly as before. The 'dark' tier cannot do
    this job on the bench camera: its black pedestal sits near 64 gray,
    so the 2026-10-01 run (exposure 3, every frame a flat dark gray, 25
    of 26 frames rejected) read mean 67 and came out 'exposure OK'.
    Contrast is pedestal-free: that run spans 2 gray levels, every
    other frame in the corpus 30 or more. Judged after 'clipped'
    because a fully white frame is flat too, and "lower the exposure"
    is the advice that fixes that one. Judged BEFORE 'dark' because a
    black frame on a camera with a low black level (the 07-23 setup,
    35 gray or less) is flat as well, and it has to meet this gate and
    its default-No question, not the one-click 'dark' warning.

    Kept here, clock-free and Tk-free, so the thresholds can be tested
    against the measured corpus instead of eyeballed in a dialog."""
    m, s = float(mean), float(sat_pct)
    if s >= BASELINE_CLIP_SAT_PCT or m >= BASELINE_CLIP_MEAN:
        return ('clipped',
                f"BASELINE IS CLIPPED - {s:.0f}% of pixels are at or "
                f"above 250 (mean {m:.0f}). Clipped pixels carry nothing "
                f"the gain/offset normalisation can recover, and a "
                f"baseline exposed differently from the ramp frames is "
                f"not a comparable reference. Lower the exposure.")
    if content and content.get('flat'):
        return ('flat', flat_message(content.get('contrast', 0.0), m))
    if m < BASELINE_DARK_MEAN:
        return ('dark', "⚠ looks DARK - raise exposure/lighting")
    if m > BASELINE_BRIGHT_MEAN or s > BASELINE_BRIGHT_SAT_PCT:
        return ('bright', "⚠ looks BRIGHT/clipped - lower exposure")
    return ('ok', "exposure OK")


# ---- camera settings of a run, and the pre-flight report ----------------
# Tk-free and camera-free on purpose: the HV start path reads these, so
# every rule in them has to be testable without a bench.

PREVIEW_MISMATCH_HEADLINE = ("This preview was NOT taken with the run's "
                             "settings")


def run_camera_controls(cam_exp, cam_gain):
    """The four controls a run stamps on the camera before every grab
    (gui._sldea_worker), in the order it writes them."""
    return (('auto_exposure', 1), ('white_balance_automatic', 0),
            ('exposure_time_absolute', cam_exp), ('gain', cam_gain))


def camera_lock_mismatch(cam_exp, cam_gain, locked):
    """Where the Webcam-tab lock disagrees with what a run will use.

    -> [(control, run_value, locked_value), ...]; empty when the lock
    holds none of the run's four controls or agrees on all it holds.

    Why it matters (2026-10-02): the pre-flight frame is grabbed by
    webcam.oneshot_rgb, which re-stamps webcam.LOCKED_CONTROLS just
    before the shutter, while the run overlays the Webcam-tab exposure
    and gain ENTRY values on that lock. Whenever the two disagree, the
    picture the operator approves is not the picture the run takes.

    Since #361 (merged with this 2026-10-06) the pre-flight sets the
    run's own lock (gui.sldea_run_lock) for its grab, and the dialog
    hands THAT lock here. It is built from the run's own values, so from
    the dialog this can no longer find a mismatch; it stays for a caller
    that hands it another lock. The SLDEA tab's camera line
    (camera_line) still compares the Webcam tab's lock: its live
    preview runs on it, and the dialog says so through `tab_mismatch`."""
    held = locked or {}
    out = []
    for name, want in run_camera_controls(cam_exp, cam_gain):
        if name not in held:
            continue
        try:
            same = int(float(held[name])) == int(float(want))
        except (TypeError, ValueError):
            same = False
        if not same:
            out.append((name, want, held[name]))
    return out


def _camera_words(name, value):
    """One camera control as an operator would say it."""
    if name == 'exposure_time_absolute':
        return f"exposure {value}"
    if name == 'gain':
        return f"gain {value}"
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        v = None
    if name == 'auto_exposure':            # UVC menu: 1 = manual
        return "automatic exposure " + ("off" if v == 1 else "ON")
    if name == 'white_balance_automatic':
        return "automatic white balance " + ("off" if v == 0 else "ON")
    return f"{name} {value}"


def camera_mismatch_words(mismatch):
    """-> (what the preview used, what the run will use), plain words."""
    preview = ", ".join(_camera_words(n, lock) for n, _run, lock in mismatch)
    run = ", ".join(_camera_words(n, want) for n, want, _lock in mismatch)
    return preview, run


def camera_for_run(cam_exp, cam_gain, defaults=()):
    """'Camera for this run: ...' -> (text, any value is a fallback).

    `defaults` names the values ('exposure', 'gain') the Webcam tab had
    no readable box for, where the run falls back on a built-in number.
    The line then says so instead of "set on the Webcam tab"."""
    names = tuple(defaults or ())
    if not names:
        return (f"Camera for this run: exposure {cam_exp}, gain {cam_gain}, "
                f"set on the Webcam tab", False)
    what = (f"The {names[0]} is a built-in default, because the Webcam "
            f"tab has no readable box for it." if len(names) == 1 else
            f"The {' and '.join(names)} are built-in defaults, because "
            f"the Webcam tab has no readable boxes for them.")
    return (f"⚠ Camera for this run: exposure {cam_exp}, gain "
            f"{cam_gain}. {what} Open the Webcam tab and press Read "
            f"camera.", True)


def camera_line(cam_exp, cam_gain, locked=None, defaults=()):
    """The SLDEA tab's 'Camera for this run' line -> (text, warn).

    `warn` asks the caller for its warning colour; the text carries the
    same fact in words, so colour is never the only cue."""
    text, fallback = camera_for_run(cam_exp, cam_gain, defaults)
    if fallback:
        return text, True
    mismatch = camera_lock_mismatch(cam_exp, cam_gain, locked)
    if not mismatch:
        return text, False
    preview, _run = camera_mismatch_words(mismatch)
    return (f"{text}\n⚠ The Webcam tab has LOCKED {preview} instead, so "
            f"its live preview will NOT show what the run records (the "
            f"pre-flight does). Check the boxes on the Webcam tab, then "
            f"press Apply & Lock there, or Auto-set camera.",
            True)


CAMERA_NOT_KNOWN = "(not known: the camera pre-flight did not run)"


def camera_record(cam_exp, cam_gain, run_lock=None, camera=None,
                  defaults=()):
    """setup.txt's camera block, under '--- Camera ---' (#400): one
    summary line, then `Key: value` lines with everything the app knows
    about the camera when the run starts, so a run records the camera
    state its pictures were shot under.

    `run_lock` is the lock the run stamps before every grab
    (gui.sldea_run_lock: the Webcam tab's lock, with manual exposure, white
    balance auto off, and the run's exposure and gain on top), or None from
    a caller that does not know it. `camera` is what the camera pre-flight
    found: webcam.resolve_camera's spec ('kind', 'device', 'fourcc', 'w',
    'h') and 'frame', the (width, height) of the picture it took; None when
    the pre-flight did not run. `defaults` names the run's values that are
    built-in fallbacks (gui._sldea_cam_defaults), as camera_for_run does.

    The summary stays the first line: Edge Review's run health quotes the
    line under the header (sldea_edge._health_setup). ASCII only, because
    the runner writes setup.txt in the locale's encoding."""
    lock = dict(run_lock or {})
    cam = dict(camera or {})
    if run_lock is None:
        white = "white balance manual (balance not recorded)"
    elif 'red_balance' in lock and 'blue_balance' in lock:
        white = (f"white balance manual, red {int(lock['red_balance'])}, "
                 f"blue {int(lock['blue_balance'])}")
    else:
        white = "white balance manual (red and blue not locked)"
    stamped = bool(cam.get('device')) if camera is not None else True
    if stamped:
        summary = f"exposure {cam_exp}, gain {cam_gain}, {white}"
    else:
        summary = (f"exposure {cam_exp} and gain {cam_gain} asked for, but "
                   f"this camera has no V4L2 controls, so none was set")
    names = tuple(defaults or ())
    if names:
        summary += (f" ({names[0]} is a built-in default"
                    if len(names) == 1 else
                    f" ({' and '.join(names)} are built-in defaults")
        summary += ": no readable box on the Webcam tab)"
    lines = [summary]
    if camera is None:
        lines += [f"Camera device: {CAMERA_NOT_KNOWN}",
                  f"Camera pixel format: {CAMERA_NOT_KNOWN}",
                  f"Camera frame size: {CAMERA_NOT_KNOWN}"]
    else:
        index = cam.get('index')
        lines.append("Camera device: " + (
            str(cam['device']) if cam.get('device')
            else f"OpenCV camera {index}" if index is not None
            else "(not known)"))
        if cam.get('kind') == 'bayer' and cam.get('fourcc'):
            lines.append(f"Camera pixel format: {cam['fourcc']} (raw Bayer)")
        else:
            lines.append("Camera pixel format: (chosen by OpenCV)")
        size = cam.get('frame') or (
            (cam.get('w'), cam.get('h')) if cam.get('w') and cam.get('h')
            else None)
        lines.append(f"Camera frame size: {int(size[0])} x {int(size[1])}"
                     if size else
                     "Camera frame size: (not known: the pre-flight took "
                     "no picture)")
    if run_lock is None:
        lines.append("Camera controls: (not recorded)")
    elif not stamped:
        lines.append("Camera controls: (none set: no V4L2 controls)")
    elif not lock:
        lines.append("Camera controls: (none locked)")
    else:
        lines.append("Camera controls: " + ", ".join(
            f"{name}={int(lock[name])}" for name in sorted(lock)))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The run folder (`#402`)
# ---------------------------------------------------------------------------
# The worker makes the run folder with exist_ok=True and opens setup.txt and
# data.csv in it with mode 'w', so a run name used before overwrote that
# run without a word. The SLDEA tab now shows the folder a run will write
# to, warns while the operator types, and Run refuses a folder that already
# holds a run.

# The files that make a folder a run. The worker writes setup.txt right
# after making the folder and data.csv next, so a run that wrote anything
# left setup.txt. Looked for by name (two stats), never by listing the
# folder: a run folder holds thousands of frames, and the share can be slow.
RUN_FILES = ('setup.txt', 'data.csv')
# The line's stand-in for a blank Run name, whose folder is only named
# (SldeaProfile.run_dirname) when the run starts.
AUTO_RUN_DIRNAME = 'SLDEA_<date>_<time>'
# How long Run waits for those two stats before it refuses. They run on a
# thread because sldea_run is on the Tk thread, and a stat on a share that
# has gone away can block for minutes.
RUN_FOLDER_CHECK_S = 3.0
# The line is two lines of text in a box of fixed height (#402 review): the
# folder, then a warning or nothing, so its text never moves the rows
# below it. Each line is shortened to the width the tab gives it, measured
# in its font by the caller (run_folder_line's `fits`). Without a measured
# width (the tab before Tk has laid it out) a line holds this many
# characters.
RUN_FOLDER_LINE_CHARS = 64


def run_folder(outdir, run_name, started=None):
    """The folder a run writes to: <outdir>/<run_name>, or with the name
    blank, <outdir>/SLDEA_YYYYmmdd_HHMMSS from `started`, the run's start
    time. With `started` None (the SLDEA tab's line, before any run) a
    blank name shows as AUTO_RUN_DIRNAME. The worker makes its folder from
    this and the tab's line shows what it returns, so they cannot drift."""
    import os
    if not run_name:
        run_name = (SldeaProfile.run_dirname(started) if started is not None
                    else AUTO_RUN_DIRNAME)
    return os.path.join(outdir, run_name)


def run_name_problem(run_name):
    """Why `run_name` cannot name a run folder, as the message to show, or
    None when it can. A blank name always can: the run names its folder
    from its start time. A typed one follows New folder...'s rules
    (output_folder.name_problem): one folder inside the Output dir, with a
    name Windows and the share accept, in plain ASCII, because OpenCV on
    the lab's Windows PCs cannot open frames in a folder named otherwise."""
    if not (run_name or '').strip():
        return None
    import output_folder
    return output_folder.name_problem(run_name)


def holds_run(folder):
    """The RUN_FILES already in `folder`, in that order: empty when no run
    is there, the folder itself missing included. Two stats. None when a
    stat failed for any other reason than the file or a folder above it
    being absent (a permission, an I/O error, a stale handle on the share):
    a run there cannot be ruled out then (#402 review). os.path.exists,
    used here before, reads every failure as absent."""
    import os
    found = []
    for name in RUN_FILES:
        try:
            os.stat(os.path.join(folder, name))
        except (FileNotFoundError, NotADirectoryError):
            continue
        except (OSError, ValueError):
            return None
        found.append(name)
    return found


# What a check of the run folder can find besides holds_run's list (#402
# review): the folder is on the lab share while nothing is mounted at its
# mount point, so it would be on this PC's own disk; or a stat failed in a
# way that does not mean "absent". Either refuses the run.
FOLDER_NOT_MOUNTED = 'share not mounted'
FOLDER_NOT_CHECKED = 'could not be checked'


def run_folder_look(outdir, run_name, mount=None):
    """The check behind the line and the refusal, run on a thread: what the
    run folder holds -> holds_run's list, FOLDER_NOT_MOUNTED, or
    FOLDER_NOT_CHECKED.

    `mount` is the lab share's mount point (output_folder.share_mount).
    A folder under it while nothing is mounted there is refused, as New
    folder... refuses such a parent (#394): unmounted, a stat there finds
    nothing at once, and the run would write to this PC's own disk or fail
    after "Energize HV?". A folder off the share costs no stat for this.
    A blank name's folder is new by its time stamp, so it is only checked
    for the mount, and off the share it costs nothing at all."""
    import output_folder
    folder = run_folder(outdir, run_name)
    if output_folder.share_unmounted(folder, mount):
        return FOLDER_NOT_MOUNTED
    if not (run_name or '').strip():
        return []
    found = holds_run(folder)
    return FOLDER_NOT_CHECKED if found is None else found


def run_folder_look_within(outdir, run_name, mount=None,
                           timeout_s=RUN_FOLDER_CHECK_S):
    """run_folder_look, waited for at most `timeout_s` -> what it found, or
    None when its stats have not returned by then (a share that hangs).
    They run on a daemon thread left to finish on its own, which holds the
    two boxes' text and a list and nothing of the caller's."""
    import threading
    out = []
    worker = threading.Thread(
        target=lambda: out.append(run_folder_look(outdir, run_name, mount)),
        name='sldea-run-folder-check', daemon=True)
    worker.start()
    worker.join(timeout_s)
    return out[0] if out else None


def run_folder_refusal(outdir, run_name, timeout_s=None, mount=None):
    """Why Run must not start into this run's folder, as the message to
    show, or None when it may.

    Refused: a typed name that cannot be a folder name, a folder that
    already holds a run, a folder whose check failed or has not answered
    within `timeout_s`, because a run already there cannot be ruled out and
    writing over the only copy of a run cannot be undone, and a folder on
    the lab share while the share is not mounted at `mount` (#402 review).
    There is no "start anyway", for the folder that does not answer either
    (owner decision 2026-10-08). A blank name's folder is named from the
    start time, so it is refused only for the share: not mounted, or, under
    the mount point, not answering. `timeout_s` None means
    RUN_FOLDER_CHECK_S, read at the call."""
    import output_folder
    if timeout_s is None:
        timeout_s = RUN_FOLDER_CHECK_S
    name = (run_name or '').strip()
    problem = run_name_problem(name)
    if problem:
        return (f"The run name '{name}' cannot name the run's folder.\n\n"
                f"{problem}\n\nType another name, or clear the box and the "
                f"run names its folder from its start time "
                f"({AUTO_RUN_DIRNAME}).")
    folder = run_folder(outdir, name)
    if not name and not output_folder.on_share(folder, mount):
        return None
    found = run_folder_look_within(outdir, name, mount, timeout_s)
    if found is None:
        what = ("a run already there cannot be ruled out" if name else
                "whether the share is mounted cannot be told")
        return (f"Could not check the run folder\n{folder}\n\nThe Output dir "
                f"did not answer within {timeout_s:g} s, so {what}. If it is "
                f"on the share, check that the share is mounted, then press "
                f"▶ Run again.")
    if found == FOLDER_NOT_MOUNTED:
        return (f"The share is not mounted at {mount}, so the run folder\n"
                f"{folder}\nwould be on this PC's own disk instead of on the "
                f"share.\n\nCheck that the share is mounted, then press ▶ Run "
                f"again.")
    if found == FOLDER_NOT_CHECKED:
        return (f"Could not check the run folder\n{folder}\n\nLooking for "
                f"{' and '.join(RUN_FILES)} there failed for another reason "
                f"than the files being absent (a permission, or the share), "
                f"so a run already there cannot be ruled out. Check that the "
                f"Output dir can be read, then press ▶ Run again.")
    if found:
        return (f"The run folder\n{folder}\nalready holds a run: "
                f"{' and '.join(found)}. A run started there would write "
                f"over that run's files.\n\nType another run name, or clear "
                f"the box and the run names its folder from its start time "
                f"({AUTO_RUN_DIRNAME}).")
    return None


def open_run_file(rundir, name, run_name, **kw):
    """open(<rundir>/<name>) for the worker to write a run's own file
    (setup.txt, data.csv) -> the file object.

    With a typed `run_name` the mode is 'x', so a run that started in that
    folder after Run checked it (another PC on the share, in the minutes
    the dialogs took) makes this one fail instead of writing over it
    (#402 review). The FileExistsError then says so in words, for the run
    log, with what this run had already left there: the worker opens
    setup.txt first, then appends to run.log, then opens data.csv, so a
    data.csv that fails finds this run's setup.txt and log lines already
    in that folder (final HV review 2026-10-08, finding 3). A blank name's
    folder is new by its time stamp and keeps 'w'."""
    import os
    path = os.path.join(rundir, name)
    try:
        return open(path, 'x' if (run_name or '').strip() else 'w', **kw)
    except FileExistsError:
        if name == 'setup.txt':
            left = ("This run stopped before any HV and left that run's "
                    "files as they were.")
        else:
            left = ("This run stopped before any HV, but it had already "
                    "written its setup.txt in that folder and added its log "
                    "lines to the run.log there; it overwrote none of the "
                    "other run's files.")
        raise FileExistsError(
            f"{name} appeared in the run folder {rundir} after ▶ Run "
            f"checked it: another run is writing there. {left} Type "
            f"another run name and press ▶ Run again.") from None


def _fits_chars(text):
    """run_folder_line's `fits` when the caller has no measured width."""
    return len(text) <= RUN_FOLDER_LINE_CHARS


def fit_path(head, path, tail='', fits=None):
    """One line of text, head + path + tail, with `path` cut from the left
    behind an ellipsis until fits(line) holds: first at a separator, then,
    when even the last part does not fit, character by character. So the
    run folder's name, at the end, is what shows when anything does. A
    width too narrow for `tail` as well loses the tail. `fits` None counts
    characters (_fits_chars)."""
    fits = fits or _fits_chars
    line = head + path + tail
    if fits(line):
        return line
    last = max(path.rfind('/'), path.rfind('\\'))
    cuts = [i for i, c in enumerate(path) if c in '/\\' and i > 0]
    cuts += range(last + 1, len(path))
    for i in cuts:
        line = head + '…' + path[i:] + tail
        if fits(line):
            return line
    if tail:                       # a width too narrow for the tail too
        return fit_path(head, path, '', fits)
    return fit_end(head + '…' + path[-1:], fits)


def fit_end(text, fits=None):
    """`text` cut at its end behind an ellipsis until fits(text) holds. A
    safety net for a warning that does not fit the line, as on a wider
    font: the words are written to fit, and the tooltip has them whole."""
    fits = fits or _fits_chars
    if fits(text):
        return text
    for n in range(len(text) - 1, 0, -1):
        cut = text[:n].rstrip() + '…'
        if fits(cut):
            return cut
    return '…'


def run_folder_line(outdir, run_name, found=None, slow=False, fits=None,
                    mount=None):
    """The SLDEA tab's line under Run name -> (text, warn, full).

    `text` is at most two lines, each fitting the line's width (`fits`,
    a test of one line of text; None counts characters): "Saves to:" and
    the folder, cut from the left so the run folder's name shows, then a
    warning or nothing. The label keeps two lines of height whatever this
    says, so the rows below never move (#402 review).

    `found` is what the last check of this folder saw (run_folder_look's
    answer), None while that is not known. `slow` says the check out now
    for this folder has not answered for a while. `mount`, the share's
    mount point, is only named in the tooltip. `full`, for the tooltip, is
    the whole path, and below it the whole reason for a warning. `warn`
    asks the caller for its warning colour; the words say the same, so
    colour is never the only cue. A relative Output dir is shown from the
    working folder, where the run would really write; that costs no file
    system call."""
    import os
    import output_folder
    fits = fits or _fits_chars
    name = (run_name or '').strip()
    problem = run_name_problem(name)
    folder = os.path.abspath(run_folder(outdir, name))
    first = fit_path('Saves to: ', folder,
                     '' if name else '  (stamped at start)', fits)
    warning = detail = ''
    if problem:
        # a name that is not plain ASCII gets New folder's way round it,
        # in its own words (owner decision 2026-10-08)
        if output_folder.ASCII_HINT in problem:
            warning = ("⚠ Plain ASCII only: u for µ, as in 2.5uL. "
                       "▶ Run will refuse it.")
        else:
            reason = problem.split('. ')[0].rstrip('.') + '.'
            warning = f"⚠ {reason} ▶ Run will refuse it."
            if not fits(warning):
                warning = "⚠ Not a folder name: ▶ Run will refuse it."
        detail = problem
    elif found == FOLDER_NOT_MOUNTED:
        warning = "⚠ The share is not mounted: ▶ Run will refuse."
        where = f" at {mount}" if mount else ""
        detail = (f"The share is not mounted{where}, so this folder would "
                  f"be on this PC's own disk instead of on the share.")
    elif found == FOLDER_NOT_CHECKED:
        warning = "⚠ Could not check this folder: ▶ Run will refuse."
        detail = (f"Looking for {' and '.join(RUN_FILES)} here failed for "
                  f"another reason than the files being absent (a "
                  f"permission, or the share), so a run already here cannot "
                  f"be ruled out.")
    elif found:
        warning = "⚠ Already holds a run: ▶ Run will refuse this name."
        detail = (f"It already holds {' and '.join(found)}. A run started "
                  f"there would write over that run's files.")
    elif slow and found is None:
        warning = ("⚠ The Output dir is not answering: ▶ Run would "
                   "refuse.")
        detail = ("The check of this folder has not answered yet, so a run "
                  "already there cannot be ruled out. If it is on the share, "
                  "check that the share is mounted.")
    full = folder + (f"\n\n{detail}" if detail else '')
    if not warning:
        return first, False, full
    return f"{first}\n{fit_end(warning, fits)}", True, full


def run_folder_writing_line(folder, fits=None):
    """The line while a run is on -> (text, warn, full): "Writing to:" and
    the folder that run writes to, cut as run_folder_line cuts it. The
    boxes stay editable during a run, and judging them then once warned
    that the run's own folder "already holds a run" (#402 review)."""
    import os
    folder = os.path.abspath(folder)
    return fit_path('Writing to: ', folder, '', fits), False, folder


def preflight_start_button(level, mismatch=False, checked=True,
                           fallback=False, tab_mismatch=False):
    """The pre-flight's start button -> (label, is_default).

    The default button is the one that holds the focus and that Return
    presses. It may be the start button only when the verdict is 'ok',
    the picture check really ran, and the preview was taken with the
    run's own camera settings. The 2026-10-01 run recorded a flat
    picture for 209 s of HV; its pre-flight was confirmed within 4 s,
    and whatever that preview showed, "Looks good" was one Return away.

    Two more warnings cost the default (2026-10-06, the #348/#361 merge
    review): `fallback`, a camera value that is a built-in default because
    the Webcam tab has no readable box for it (the dialog already said so
    with a warning sign, but Return still started the run), and
    `tab_mismatch`, the Webcam tab's lock disagreeing with the run's
    fields, so its live preview is not what the run records (#361)."""
    if level == 'clipped':
        return "⚠ Start anyway (baseline blown out)", False
    if level == 'flat':
        return "⚠ Start anyway (no picture)", False
    if not checked:
        return "⚠ Start anyway (picture not checked)", False
    if level != 'ok':
        return "⚠ Start anyway (exposure warning)", False
    if mismatch:
        return "⚠ Start anyway (preview does not match the run)", False
    if fallback:
        return "⚠ Start anyway (built-in camera values)", False
    if tab_mismatch:
        return PREFLIGHT_START_LOCK_DIFFERS, False
    return "✔ Looks good — start run", True


def preflight_disc_line(frame):
    """Advice: can Edge Review's resting-disc fit see a disc in this frame?

    Runs sldea_edge.baseline_disc (about 0.06 s) on the grayscale Edge
    Review itself would load from the saved PNG. This is ADVICE, never a
    gate: a non-disc device refuses by design, and a dark-disc run has
    been reviewed by hand after a refusal. None when the fit cannot be
    run at all (OpenCV missing, or the fit raised)."""
    try:
        import cv2
        import numpy as np
        import sldea_edge
        g = np.asarray(frame)
        if g.ndim == 3:
            g = cv2.cvtColor(np.ascontiguousarray(g, dtype=np.uint8),
                             cv2.COLOR_RGB2GRAY)
        g = g.astype(np.float32)
        settings = dict(sldea_edge.DEFAULT_SETTINGS)
        ref = sldea_edge.baseline_disc(g, settings)
        if ref is not None:
            return (f"Disc found: {ref['diam_px']:.0f} px across, fit "
                    f"quality {ref['conf']:.2f} (0 to 1, higher is better)")
        why = sldea_edge.baseline_disc_refusal(g, settings)
        if not why:
            return None
        return (f"Disc not found: {why}. Edge Review will not be able to "
                f"measure this run automatically.")
    except Exception:
        return None


def preflight_report(frame, cam_exp, cam_gain, locked=None, focus=None,
                     defaults=(), tab_mismatch=False):
    """Everything the camera pre-flight says about one frame.

    `frame` is the RGB pre-flight frame, `locked` a copy of
    webcam.LOCKED_CONTROLS as it stood for the grab (empty when the
    camera has no device path to stamp it on), `focus` the focus score
    or None, `defaults` as in camera_for_run. Returns a dict:

      mean, sat_pct   whole-frame statistics (as before 2026-10-02)
      content         sldea_edge.image_content's dict, or None when that
                      check could not run (content_error says why)
      level, hint     exposure_verdict's answer, 'flat' tier included
      gate            True for 'clipped' and 'flat': a second, default-No
                      confirmation stands between them and a run
      disc_line       preflight_disc_line's advice, or None
      camera_line     'Camera for this run: ...'
      mismatch        camera_lock_mismatch's list
      mismatch_line   the plain-words detail under the bold headline
      start_label, start_default   preflight_start_button's answer
      stats_line      the one-line numbers shown under the picture
      log_lines       what run.log gets, for EVERY pre-flight, where
                      it used to be clipped ones only"""
    import numpy as np
    arr = np.asarray(frame)
    gray = arr.mean(axis=2) if arr.ndim == 3 else arr.astype(np.float64)
    mean = float(gray.mean())
    sat = float((gray >= 250).mean() * 100)
    content, content_error = None, None
    try:
        import sldea_edge
        content = sldea_edge.image_content(gray)
        if content is None:
            content_error = "the frame is empty"
    except Exception as e:
        content, content_error = None, str(e) or type(e).__name__
    level, hint = exposure_verdict(mean, sat, content)
    mismatch = camera_lock_mismatch(cam_exp, cam_gain, locked)
    cam_text, cam_fallback = camera_for_run(cam_exp, cam_gain, defaults)
    label, is_default = preflight_start_button(
        level, bool(mismatch), content is not None, fallback=cam_fallback,
        tab_mismatch=tab_mismatch)
    disc = preflight_disc_line(frame)
    mismatch_line = ''
    if mismatch:
        preview, run = camera_mismatch_words(mismatch)
        mismatch_line = (f"The preview used {preview} (what the Webcam tab "
                         f"has locked). The run will use {run} (what the "
                         f"boxes on the Webcam tab say). Press Adjust, make "
                         f"the boxes say what you want, press Apply & Lock, "
                         f"and run again.")
    ctxt = (f"contrast {content['contrast']:.0f} gray levels" if content
            else "contrast not checked")
    stats = ((f"focus {focus:.0f}   " if focus is not None else "")
             + f"mean {mean:.0f}   saturated {sat:.1f}%   {ctxt}")
    log = [f"camera pre-flight: mean {mean:.0f}, saturated {sat:.1f}%, "
           + ctxt
           + (f", focus {focus:.2f}" if focus is not None
              else ", focus not scored")
           + f", verdict {level.upper()}"]
    if content_error:
        log.append(f"⚠ camera pre-flight: the picture check could not "
                   f"run ({content_error})")
    if level in ('clipped', 'flat'):
        log.append(f"⚠⚠ camera pre-flight: {hint}")
    if disc:
        log.append(f"camera pre-flight: {disc}")
    if mismatch:
        log.append(f"⚠ camera pre-flight: run camera exposure {cam_exp}, "
                   f"gain {cam_gain}, but the preview was NOT taken with "
                   f"them (it used {preview})")
    elif locked:
        log.append(f"camera pre-flight: run camera exposure {cam_exp}, gain "
                   f"{cam_gain}; the lock this frame was taken under "
                   f"agrees with them")
    else:
        log.append(f"camera pre-flight: run camera exposure {cam_exp}, gain "
                   f"{cam_gain}; this camera has no device path, so neither "
                   f"the pre-flight nor the run stamps them on it")
    return {'mean': mean, 'sat_pct': sat, 'focus': focus,
            'content': content, 'content_error': content_error,
            'level': level, 'hint': hint,
            'gate': level in ('clipped', 'flat'),
            'disc_line': disc, 'camera_line': cam_text,
            'mismatch': mismatch, 'mismatch_line': mismatch_line,
            'start_label': label, 'start_default': is_default,
            'stats_line': stats, 'log_lines': log}


def baseline_picture_check(frame, override=''):
    """Does the run's own 0 kV baseline frame hold a picture?

    -> (flat, run.log line). The warm-up and baseline frames are the
    only ones shot with the run's real camera settings before the
    staircase, so this is the last place a run on a flat picture can be
    stopped (the 2026-10-01 run went on to 3 kV for 209 s). Raises when
    the frame cannot be judged; the runner logs that and carries on
    unchanged, because a check that cannot run must not end a run.

    `override` is the pre-flight override the run was started with
    ('' for none, see preflight_override_record). The verdict is the
    same either way; only the words after it change, because with the
    override the runner does not stop (decisions 12 and 14,
    2026-10-03), and the line must not say that it does."""
    import sldea_edge
    c = sldea_edge.image_content(frame)
    if c is None:
        raise ValueError("the baseline frame is empty")
    if c['flat']:
        if override:
            tail = (f" This is the run's own baseline frame. The operator "
                    f"started anyway at the pre-flight ({override}), so "
                    f"the run CARRIES ON. Review this run by hand.")
        else:
            tail = (" This is the run's own baseline frame, so nothing in "
                    "this run could be measured. STOPPING NOW.")
        return True, (
            "⚠⚠ "
            + flat_message(c['contrast'], 0.5 * (c['p5'] + c['p95']))
            + f" (A usable picture spans {sldea_edge.FLAT_CONTRAST_GRAY:.0f}"
            f" gray levels or more.)" + tail)
    return False, (f"baseline picture check: contrast {c['contrast']:.0f} "
                   f"gray levels, saturated {c['sat_pct']:.1f}% - OK")


def flat_stop_words(dry, drive_kv):
    """Where the drive stood when a flat baseline ended the run: one
    plain sentence, for run.log and for the operator's box.

    `drive_kv` is the last voltage the runner commanded. It is printed
    so that nobody has to assume it was zero: the baseline is shot in
    the loop tick in which the first ramp begins, so the drive stands a
    few volts up on an ordinary profile, and at the whole first level
    when the ramp time is 0. Never raises."""
    if dry:
        return "This was a DRY run: no voltage was driven."
    try:
        kv = float(drive_kv)
    except (TypeError, ValueError):
        return ("The first voltage ramp had only just begun (the drive "
                "voltage at the stop is not known).")
    return (f"The first voltage ramp had only just begun: the drive had "
            f"been commanded to {kv:.3f} kV when the run stopped.")


# ---- the pre-flight override, and what ends a run at its baseline -------
# Owner decisions 12, 13 and 14 (2026-10-03), one mechanism. A deliberate
# "Start anyway (no picture)" at the camera pre-flight, after its
# default-No question, carries into the run, DRY or LIVE: the baseline
# picture check still runs and logs its verdict, but it does not stop
# that run. The override is written to run.log and to setup.txt, so the
# record shows the baseline was flat and the operator chose to go on (a
# faint device that will be reviewed by hand is what it exists for).
# Without the override, a baseline with no frame at all ends the run the
# way a flat one does, when the pre-flight had a camera to expect one
# from. Tk-free, so the HV start path's rules are tested without a bench.

PREFLIGHT_OVERRIDE_NO_PICTURE = 'no picture'

# The start button's label when the only thing wrong is that the Webcam
# tab's lock disagrees with the run's fields (#361's sentence): its live
# preview is not what the run records. A warning, so not the default
# button, as every warning in preflight_start_button (merged 2026-10-06).
PREFLIGHT_START_LOCK_DIFFERS = ("\u26a0 Start anyway (the Webcam preview "
                                "differs from the run)")
PREFLIGHT_OVERRIDE_KEY = 'Pre-flight override'


def preflight_override_record(override):
    """What a run writes down about its pre-flight override.

    -> (setup.txt line, run.log line), or (None, None) for no override.
    The setup.txt line is plain `Key: value` text like every other line
    in that file (decision 2026-08-08); nothing reads it back by machine
    yet, it is there for the person reading the run folder."""
    if not override:
        return None, None
    return (f"{PREFLIGHT_OVERRIDE_KEY}: {override} (the operator started "
            f"anyway at the camera pre-flight; the baseline picture stop "
            f"is off for this run)",
            f"⚠⚠ pre-flight override: {override}. The baseline picture "
            f"check still runs and its verdict goes to this log, but it "
            f"will NOT stop this run. Review this run by hand.")


def baseline_stop_reason(frame_taken, flat, cam_expected, override):
    """Why the runner ends a run at its baseline frame, or '' to go on.

    'flat'      the baseline holds no picture (2026-10-02).
    'no frame'  the camera gave the pre-flight a frame but gave the run
                none for its baseline (decision 13). A run started past
                the "No camera frame available" question had no camera
                to expect one from, and goes on as it always did.
    The pre-flight override switches both off."""
    if override:
        return ''
    if not frame_taken:
        return 'no frame' if cam_expected else ''
    return 'flat' if flat else ''


def _no_frame_cause(video):
    return ("the video stream gave no frame in time: check the camera and "
            "its cable" if video else
            "camera busy? close the Webcam preview")


def no_baseline_frame_line(override='', video=False):
    """The run.log line for a baseline the camera gave no frame for, in
    a run whose pre-flight did get one. `video`: the run takes its stills
    off the recorder's stream (2026-10-06), where the Webcam tab cannot be
    the reason, since a video run holds the camera."""
    cause = _no_frame_cause(video)
    if override:
        return (f"⚠⚠ NO BASELINE FRAME: the camera gave the pre-flight a "
                f"picture but gave this run none for its baseline ({cause}). "
                f"The operator started anyway at the pre-flight "
                f"({override}), so the run CARRIES ON. Review this run by "
                f"hand.")
    return (f"⚠⚠ NO BASELINE FRAME: the camera gave the pre-flight a "
            f"picture but gave this run none for its baseline ({cause}). "
            f"Nothing in this run could be measured. STOPPING NOW.")


def baseline_stop_words(reason, dry, drive_kv, video=False):
    """The words for a run that ends at its baseline frame.

    -> dict(stopped, status, title, box): the run.log line after the
    check's own line, the red status line, and the operator's box. The
    drive sentence is flat_stop_words'. Never raises."""
    drive = flat_stop_words(dry, drive_kv)
    tail = "\n\nThe Run log has the numbers."
    if reason == 'no frame':
        return {
            'stopped': f"run stopped at the baseline frame. {drive}",
            'status': ("STOPPED: NO BASELINE FRAME from the camera, "
                       "nothing was measured (see Run log)"),
            'title': "Run stopped: no baseline frame",
            'box': ("The run stopped itself at its baseline picture.\n\n"
                    "The camera gave no frame for it, although it gave "
                    "the pre-flight one, so nothing in this run could "
                    "have been measured.\n\n" + drive
                    + ("\n\nCheck the camera and its cable, then press "
                       "Run again." if video else
                       "\n\nClose the Webcam preview if it is running, "
                       "check the camera, then press Run again.") + tail)}
    return {
        'stopped': f"run stopped at the baseline frame. {drive}",
        'status': ("STOPPED: NO PICTURE in the baseline frame, nothing "
                   "was measured (see Run log)"),
        'title': "Run stopped: no picture",
        'box': ("The run stopped itself right after its baseline "
                "picture.\n\nThat picture is flat: the disc is not "
                "visible, so nothing in this run could have been "
                "measured.\n\n" + drive
                + "\n\nOpen the Webcam tab, press Auto-set camera (or "
                "change the exposure or the light by hand and press Apply & "
                "Lock) until you can see the disc, then "
                "press Run again." + tail)}


def credible_baseline_ua(baseline_ua, trip_ua):
    """True when a learned 0 kV rest level may anchor the deviation trip.

    The bound is min(30, trip/2) uA: the worst honest instrument offset
    observed is the 07-29 campaign's stiff -16 uA, so 30 covers it with
    margin, while anything larger at 0 kV is indistinguishable from a
    standing fault current (a damaged sample leaking before the ramp).
    Anchoring |I - baseline| to a fault current would normalize the very
    signal the watchdog exists for; refusing the baseline leaves the
    absolute |I| >= trip rule, which then trips on the fault — the
    correct outcome (review 2026-08-04). Never more than trip/2 so a
    small trip level cannot be half-eaten by its own baseline."""
    if baseline_ua is None:
        return False
    return abs(float(baseline_ua)) <= min(30.0, 0.5 * float(trip_ua))


def fmt_meas(mkv, mua):
    """Status-line fragment for one snapshot's scope readings.

    Either value may be None INDEPENDENTLY — an off-screen I_Out with a
    fine V_Out is expected-by-design once a window clips — so each is
    formatted on its own ('?' for unreadable). The old single-guard
    f-string raised TypeError on (mkv ok, mua None) and killed the LIVE
    run's snapshot loop (review 2026-08-04)."""
    if mkv is None and mua is None:
        return ""
    fk = '?' if mkv is None else f"{mkv:.2f}"
    fi = '?' if mua is None else f"{mua:.0f}"
    return f"  meas {fk} kV / {fi} µA"


class BreakdownWatchdog:
    """Deliberately SLOW-to-trip breakdown detector for live runs.

    Watches the Trek current (via the scope's I_Out monitor) and only
    declares breakdown after the current has stayed at/above the trip
    level for `confirm_s` seconds of CONSECUTIVE samples -- any single
    reading below the threshold resets the streak, and unreadable samples
    (None) are ignored without resetting. The point is to be essentially
    certain before aborting a long run: a transient spike or one glitchy
    scope read never trips it.

    With `baseline_ua` (learned by the runner at 0 kV before the ramp)
    the trip is on |ua - baseline| instead of |ua|: the whole 07-29
    campaign sits on a stiff -16 uA I_Out offset, which silently made an
    absolute threshold polarity-asymmetric (34 uA of real headroom one
    way, 66 the other). Without a baseline the absolute behaviour is
    unchanged, so dry runs and scope-less tests behave exactly as before.
    """

    def __init__(self, trip_ua=100.0, confirm_s=3.0, baseline_ua=None):
        self.trip_ua = float(trip_ua)
        self.confirm_s = float(confirm_s)
        self.baseline_ua = None if baseline_ua is None else float(baseline_ua)
        self._over_since = None
        self.tripped = False
        self.last_ua = None
        # nature of the LAST evidence-bearing sample: True when it was the
        # off-screen sentinel. The trip message must not print a stale
        # below-trip last_ua when the streak that tripped was a clipping
        # current after an earlier readable sample (review 2026-08-04).
        self.last_offscreen = False

    def update(self, t_s, ua, offscreen=False):
        """Feed one sample (time in s, current in uA; ua may be None).
        Returns True the moment breakdown is CONFIRMED.

        offscreen=True marks a read where the scope reported its 9.9E37
        off-screen sentinel on the CURRENT channel: a clipping current is
        far beyond any sane trip level, so it counts as an over-trip
        sample rather than as an unreadable one."""
        if self.tripped:
            return True
        if ua is None and not offscreen:
            return False                 # unreadable: no evidence either way
        if ua is not None:
            self.last_ua = ua
        self.last_offscreen = bool(offscreen)
        if offscreen:
            over = True
        elif self.baseline_ua is not None:
            over = abs(ua - self.baseline_ua) >= self.trip_ua
        else:
            over = abs(ua) >= self.trip_ua
        if over:
            if self._over_since is None:
                self._over_since = t_s
            elif t_s - self._over_since >= self.confirm_s:
                self.tripped = True
                return True
        else:
            self._over_since = None      # dipped below: start over
        return False


def parse_watchdog_value(text):
    """The watchdog's Trip (uA) or Confirm (s) box -> a positive float, or
    ValueError (HV review 2026-10-08, #406).

    Junk, blank, zero, negatives, nan and inf are all refused. A ticked
    LIVE run quotes these numbers as its rule in "Energize HV?", run.log
    and setup.txt, and with any of them the rule is not the one quoted:
    nan or inf never trips, and a zero or negative trip trips on every
    read."""
    import math
    s = str(text or '').strip()
    value = float(s)                       # ValueError on blank or junk
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"must be a positive number, got {s!r}")
    return value


def watchdog_off_reason(ticked, dry):
    """Why a run's breakdown watchdog is not armed, in the words
    watchdog_record uses: a DRY run, the box unticked, or, ticked on a
    LIVE run, no scope to read the current."""
    if dry:
        return "dry run, no HV"
    if not ticked:
        return "box unticked"
    return "no scope to read the current"


def watchdog_state(ticked, armed, dry):
    """'ON' or 'OFF (<reason>)': watchdog_record's state in short, for
    sldea_run's refusal when it changed between "Energize HV?" and the
    commit point (HV review 2026-10-08, #406)."""
    return "ON" if armed else f"OFF ({watchdog_off_reason(ticked, dry)})"


def watchdog_record(ticked, armed, dry, trip_ua, confirm_s):
    """(setup_line, log_tag, dialog_text): the breakdown watchdog a run
    starts with, worded for setup.txt, run.log and "Energize HV?" (#406).

    `armed` is what sldea_run hands the worker (the box ticked, a LIVE
    run, a scope to read the current from), and all three texts are built
    from it, so none of them can claim something the run does not do. The
    box starts ticked, but an operator can untick it, and a preset saved
    unticked loads unticked. Before #406 no line anywhere said that
    nothing watched such a run, so OFF is said as plainly as ON.
    setup_line is an ASCII `Key: value` line, because the worker writes
    setup.txt in the locale encoding. The armed log tag is the run.log
    wording runs have carried since 2026-08-04, unchanged, so old and new
    logs read alike."""
    if armed:
        return (f"Breakdown watchdog: ON, trips when |I - baseline| >= "
                f"{trip_ua:g} uA for {confirm_s:g} s of consecutive reads "
                f"(baseline learned at 0 kV; absolute |I| if that baseline "
                f"is refused)",
                f"watchdog: dev ≥{trip_ua:g} µA for {confirm_s:g}s, "
                f"baseline learned at 0 kV",
                f"Breakdown watchdog: ON. The run stops itself when the "
                f"current stays {trip_ua:g} µA or more away from the "
                f"baseline it learns at 0 kV, for {confirm_s:g} s of "
                f"consecutive reads.")
    why = watchdog_off_reason(ticked, dry)
    return (f"Breakdown watchdog: OFF ({why})",
            f"watchdog: OFF ({why})",
            "Breakdown watchdog: OFF"
            + ("" if why == "box unticked" else f" ({why})")
            + ". Nothing stops this run on a breakdown; only ■ Abort or "
              "the end of the run does.")


# The #219 N-sigma rule's defaults, chosen on the 18 single-layer runs
# replayed on 2026-10-08 (SLDEA_DECISIONS.md, "The N-sigma breakdown rule
# runs in shadow"): no false trip on any healthy run and none on the three
# self-clearing transients. Of the three breakdowns, all snapshot-only,
# two were caught; the third sits on its run's last snapshot.
NSIGMA_DEFAULTS = {
    'n_sigma': 5.0,         # the bar is n_sigma x sigma ...
    'dev_min': 20.0,        # ... or this many uA, whichever is larger
    'window': 40,           # quiet reads behind location and sigma (20 s)
    'k_consec': 2,          # away reads in a row that would trip it
    'sigma_floor': 0.5,     # uA; sigma is never taken below this
    'guard': 2,             # newest quiet reads left out of the window
    'w_min': 10,            # quiet reads before the window is trusted
    'settle_s': 1.0,        # a landing's first second is judged as a ramp
    'ramp_factor': 2.0,     # the bar on ramps and while a landing settles
}

# Away reads the shadow lists in run.log, per run (#219). Every away read is
# counted; the first this many are listed, one line each, written once after
# the SG is zeroed. A cap, so a run that wobbles across the bar from start
# to end cannot grow the list, or that one write, without bound: 100 lines
# are about 13 KB.
NSIGMA_AWAY_LOG_MAX = 100


class NSigmaWatchdog:
    """The #219 breakdown rule: away when the current sits N sigmas from
    where THIS run's current has been. Pure, like BreakdownWatchdog: feed
    reads, read the state; no clock, thread, instrument or file.

    It runs in SHADOW (owner, 2026-10-08): the LIVE worker feeds it the
    very reads the monitor tick already takes and records what it would
    have done, and it acts on nothing; BreakdownWatchdog still stops runs.
    It also keeps every away read, a lone one included (`away`, `n_away`,
    `away_lines`), so the owner can decide later whether a single away
    read is a breakdown (2026-10-08).

    Location and sigma are the median and 1.4826 x the median absolute
    deviation of the last `window` QUIET reads, the newest `guard` of them
    left out so an excursion that is just starting cannot pull its own
    reference. A quiet read is readable, taken at a landing (nominal kV
    unchanged since the read before) at least `settle_s` after the landing
    began, and not itself away: an excursion never becomes the new normal,
    while slow leakage drift is followed. Median and MAD, not mean and
    standard deviation, so the event's own reads cannot drag the location
    or widen sigma.

    A read is AWAY when it is the scope's off-screen sentinel, or when
    |I - location| >= max(n_sigma x sigma, dev_min) at a settled landing,
    or that bar times `ramp_factor` on a ramp or while a landing settles
    (charging current and leakage settling). `k_consec` away reads in a
    row would trip it; an unreadable read neither extends nor breaks the
    streak, as in BreakdownWatchdog. sigma is never below `sigma_floor`.
    There is no single-read spike tier (owner, 2026-10-08): on MEAN reads
    a lone excursion has been the self-clearing kind (104531, P3_7).

    Before `w_min` quiet reads exist the 0 kV baseline (`base_loc`,
    `base_sigma`: the runner's reads before the ramp) stands in. With no
    baseline, settled landing reads seed the window unjudged until it
    holds `w_min` of them; a fault present from the first landing is then
    taken as normal. The fixed rule catches that only on a run where it is
    armed (its absolute |I| rule, when its baseline read failed). On a run
    whose watchdog is not armed (the box unticked, or no scope at its
    arming line) nothing does, so such a run's "no trip" is no evidence;
    only its would-trips are (HV review 2026-10-08). (The desk
    prototype of 2026-10-08 judged reads before it had anything to judge
    them by, so without a baseline its window never filled.)"""

    def __init__(self, n_sigma=None, window=None, k_consec=None,
                 dev_min=None, sigma_floor=None, guard=None, w_min=None,
                 settle_s=None, ramp_factor=None, base_loc=None,
                 base_sigma=None, away_max=None):
        d = NSIGMA_DEFAULTS
        self.n_sigma = float(d['n_sigma'] if n_sigma is None else n_sigma)
        self.window = int(d['window'] if window is None else window)
        self.k_consec = int(d['k_consec'] if k_consec is None else k_consec)
        self.dev_min = float(d['dev_min'] if dev_min is None else dev_min)
        self.sigma_floor = float(d['sigma_floor'] if sigma_floor is None
                                 else sigma_floor)
        self.guard = int(d['guard'] if guard is None else guard)
        self.w_min = int(d['w_min'] if w_min is None else w_min)
        self.settle_s = float(d['settle_s'] if settle_s is None else settle_s)
        self.ramp_factor = float(d['ramp_factor'] if ramp_factor is None
                                 else ramp_factor)
        self.base_loc = None if base_loc is None else float(base_loc)
        self.base_sigma = None if base_sigma is None else float(base_sigma)
        self._quiet = []              # newest last, at most window + guard
        self._stats_cache = None      # (location, sigma) of _quiet, or None
        self._prev_kv = None
        self._landing_t = None
        self._streak = 0
        self.n_reads = 0              # reads with a value or the sentinel
        self.tripped = False
        self.how = ''
        self.trip = None              # dict: t, kv, ua, dev, bar, loc, sigma
        self.peak = None              # largest judged departure, same keys
        # The first away_max away reads (the trip's keys plus phase, streak
        # and offscreen), and the count of every away read, listed or not.
        self.away_max = int(NSIGMA_AWAY_LOG_MAX if away_max is None
                            else away_max)
        self.away = []
        self.n_away = 0

    def stats(self):
        """(location, sigma) the next read is judged by, or (None, None)
        when there is nothing to judge it by yet."""
        q = self._quiet[:-self.guard] if self.guard else self._quiet
        if len(q) >= self.w_min:
            if self._stats_cache is None:
                s = sorted(q)
                n = len(s)
                med = s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])
                a = sorted(abs(v - med) for v in s)
                mad = (a[n // 2] if n % 2
                       else 0.5 * (a[n // 2 - 1] + a[n // 2]))
                self._stats_cache = (med, max(self.sigma_floor,
                                              1.4826 * mad))
            return self._stats_cache
        if self.base_loc is not None:
            return (self.base_loc, max(self.sigma_floor,
                                       self.base_sigma or 0.0))
        return None, None

    def _keep(self, ua):
        self._quiet.append(ua)
        if len(self._quiet) > self.window + self.guard:
            del self._quiet[0]
        self._stats_cache = None

    def update(self, t_s, kv, ua, offscreen=False):
        """Feed one read: elapsed time (s), nominal kV, current (uA, or
        None when unreadable). Returns True once the rule would trip."""
        if self.tripped:
            return True
        kv = float(kv)
        ramping = (self._prev_kv is not None
                   and abs(kv - self._prev_kv) > 1e-6)
        if ramping:
            self._landing_t = None
        elif self._landing_t is None:
            self._landing_t = t_s
        self._prev_kv = kv
        settling = (self._landing_t is None
                    or t_s - self._landing_t < self.settle_s)
        if ua is None and not offscreen:
            return False                  # unreadable: no evidence either way
        self.n_reads += 1
        loc, sig = self.stats()
        if offscreen:
            away, dev, bar = True, None, None
        elif loc is None:
            if not ramping and not settling:
                self._keep(ua)            # bootstrap: seed, cannot judge yet
            self._streak = 0
            return False
        else:
            dev = abs(ua - loc)
            bar = max(self.n_sigma * sig, self.dev_min)
            if ramping or settling:
                bar *= self.ramp_factor
            away = dev >= bar
            if self.peak is None or dev > self.peak['dev']:
                self.peak = {'t': t_s, 'kv': kv, 'ua': ua, 'dev': dev,
                             'bar': bar, 'loc': loc, 'sigma': sig}
            if not away and not ramping and not settling:
                self._keep(ua)
        self._streak = self._streak + 1 if away else 0
        if away:
            # Every away read, for the owner's call on single-read
            # excursions (#219): always counted, listed up to away_max.
            # Memory only: the worker writes the list once, after the SG
            # is zeroed, so nothing here waits on a file or on Tk.
            self.n_away += 1
            if len(self.away) < self.away_max:
                self.away.append({
                    't': t_s, 'kv': kv, 'ua': ua, 'dev': dev, 'bar': bar,
                    'loc': loc, 'sigma': sig, 'offscreen': bool(offscreen),
                    'phase': ('ramp' if ramping else
                              'settling' if settling else 'landing'),
                    'streak': self._streak})
        if self._streak >= self.k_consec:
            self.tripped = True
            self.how = ('off-screen' if offscreen else 'away') + \
                f", {self.k_consec} reads in a row"
            self.trip = {'t': t_s, 'kv': kv, 'ua': ua, 'dev': dev,
                         'bar': bar, 'loc': loc, 'sigma': sig}
        return self.tripped

    def rule_text(self):
        """The rule and its parameters, ASCII, for setup.txt."""
        return (f"|I - location| >= max({self.n_sigma:g} sigma, "
                f"{self.dev_min:g} uA) for {self.k_consec} reads in a row; "
                f"location and sigma = median and 1.4826 MAD of the last "
                f"{self.window} quiet landing reads; bar x"
                f"{self.ramp_factor:g} on ramps and the first "
                f"{self.settle_s:g} s of a landing; off-screen counts as away")

    def outcome_text(self):
        """What it would have done, ASCII, for run.log and setup.txt."""
        if self.tripped:
            tr = self.trip
            if tr['ua'] is None:
                what = "the current was off the scope's screen"
            else:
                what = (f"I {tr['ua']:.1f} uA, {tr['dev']:.1f} uA from "
                        f"location {tr['loc']:.1f} uA (bar {tr['bar']:.1f} "
                        f"uA, sigma {tr['sigma']:.2f} uA)")
            return (f"would trip at {tr['t']:.1f} s ({tr['kv']:.2f} kV): "
                    f"{what}; {self.how}")
        if self.peak is None:
            return f"no trip in {self.n_reads} reads (nothing to judge by)"
        pk = self.peak
        return (f"no trip in {self.n_reads} reads; largest departure "
                f"{pk['dev']:.1f} uA (bar {pk['bar']:.1f} uA) at "
                f"{pk['t']:.1f} s ({pk['kv']:.2f} kV)")

    def away_lines(self):
        """Every away read it saw, ASCII, for run.log (#219): a count line,
        then one line per listed read with its time, kV, reading, the
        location it was judged against, the deviation and the bar. [] with
        no away read, so a quiet run logs nothing. The owner reads these to
        decide whether a single away read is a breakdown."""
        if not self.n_away:
            return []
        n = len(self.away)
        head = (f"{self.n_away} away read{'' if self.n_away == 1 else 's'} "
                f"in {self.n_reads} reads")
        if self.n_away > n:
            head += f"; the first {n} listed, {self.n_away - n} more not"
        out = [head]
        for a in self.away:
            if a['offscreen']:
                what = "off the scope's screen"
                if a['loc'] is not None:
                    what += f" (location {a['loc']:.1f} uA)"
            else:
                what = (f"I {a['ua']:.1f} uA, {a['dev']:.1f} uA from "
                        f"location {a['loc']:.1f} uA (bar {a['bar']:.1f} "
                        f"uA, sigma {a['sigma']:.2f} uA)")
            run = f"{a['streak']} in a row"
            if a['streak'] >= self.k_consec:
                run += ", would trip"
            out.append(f"away at {a['t']:.1f} s ({a['kv']:.2f} kV, "
                       f"{a['phase']}): {what}; {run}")
        return out


def shadow_record(live, monitored):
    """setup.txt's `Watchdog shadow:` line for a run start (#219).

    The N-sigma rule runs in shadow on every LIVE run whose monitor reads
    run (the breakdown watchdog armed, or telemetry on), and acts on
    nothing. ASCII, because the worker writes setup.txt in the locale
    encoding."""
    if not live:
        return "Watchdog shadow: OFF (dry run, no HV)"
    if not monitored:
        return ("Watchdog shadow: OFF (no current reads: watchdog and "
                "telemetry both off)")
    return ("Watchdog shadow: N-sigma rule, logs only and never acts: "
            + NSigmaWatchdog().rule_text())


TELEMETRY_FILENAME = 'telemetry.csv'
TELEMETRY_COLUMNS = ['t_s', 'timestamp', 'nominal_kV', 'measured_kV',
                     'measured_uA', 'v_status', 'i_status', 'event']
# The run loop ticks at 10 Hz and the watchdog already samples I_Out at
# 2 Hz, so 2 Hz costs nothing extra; anything faster is a NEW instrument
# duty cycle and stays bench-unverified until someone times it (#157).
TELEMETRY_MAX_HZ = 2.0
TELEMETRY_MIN_HZ = 0.1
# V_Out is sampled at most this often even when current is sampled faster:
# a kV read is a second MEASUREMENT:IMMED triple under the instrument lock,
# and nominal_kV already gives the exact commanded voltage on every row.
TELEMETRY_KV_MIN_PERIOD_S = 1.0
# A single row write+flush slower than this means the output directory is
# not behaving like local disk (the bench default lives on a network
# share). Past it the log stops flushing every row -- see TelemetryLog.
TELEMETRY_SLOW_WRITE_S = 0.25
TELEMETRY_SLOW_FLUSH_PERIOD_S = 1.0
# ...and the flush window has to CLEAR the worst write it is throttling.
# A fixed 1 s window is already expired on arrival once a single write
# costs 1 s+, so every row flushed again and the monitor tick tracked the
# share 1:1 — the throttle was inert in exactly the regime it exists for
# (review 2026-08-05, measured).
TELEMETRY_SLOW_FLUSH_MARGIN = 4.0
# The achieved rate always lands a little under target: the run loop polls
# at 10 Hz, so a 0.5 s gate actually fires at 0.5-0.6 s, and every snapshot
# steals a tick for its camera grab. Only a real inability to keep up
# should raise a warning, so the bar is 70% of target, not 80%.
TELEMETRY_SHORTFALL_FRAC = 0.7


def _telemetry_num(value, places):
    """Number for a telemetry cell, or '' when it is not one.

    Blank, never an exception and never a bogus number: a caller that
    hands over None, a NaN measurement or a stray string costs that one
    cell, not the whole record of the run."""
    if value is None:
        return ''
    try:
        val = float(value)
    except (TypeError, ValueError):
        return ''
    if val != val or val in (float('inf'), float('-inf')):
        return ''
    return round(val, places)


def clamp_telemetry_hz(hz):
    """Requested telemetry rate -> the rate actually offered (Hz).

    Capped at TELEMETRY_MAX_HZ: the samples above that rate do not exist
    yet — they would be new scope round-trips inside the live run loop,
    which is bench-verified territory, not a desk decision."""
    try:
        val = float(hz)
    except (TypeError, ValueError):
        return TELEMETRY_MAX_HZ
    if val != val:                       # NaN
        return TELEMETRY_MAX_HZ
    return min(TELEMETRY_MAX_HZ, max(TELEMETRY_MIN_HZ, val))


class TelemetryLog:
    """Sidecar CSV of the live monitor samples, beside data.csv.

    The watchdog already reads I_Out at ~2 Hz on every live run and throws
    every sample away; nothing electrical is recorded between snapshots, so
    a breakdown cannot even be DATED after the fact (#157/#189). This
    writes those samples to their own file: `data.csv` keeps its one-row-
    per-frame schema and every downstream reader (`sldea_edge.load_run`,
    Edge Review, the tuner, `sldea_diag`) is untouched.

    Clock-free like `psu_logger` -- the caller passes elapsed seconds and
    the ISO timestamp -- so the whole thing is unit-testable with no Tk, no
    hardware and no sleeping.

    Statuses are recorded, not just values: a blank `measured_kV` with
    `v_status=offscreen` (the Tek 9.9E37 sentinel, i.e. clipped off the
    visible window) is a different fact from `invalid` (unparseable) and
    from `skipped` (not sampled on this row), and the 07-29 dropout
    investigation was ambiguous precisely because that distinction was
    never written down (#159).

    NOTHING here may raise into the live run loop: a full disk or a
    yanked USB stick must cost the record, never the HV shutdown path.
    Write failures set `.failed` and are reported once by the caller.

    For the same reason the per-row flush is not unconditional. Flushing
    every row is what makes an aborted run's file complete, but the run
    loop is also the thread that services ■ Abort, and the bench's
    default output directory is a network share -- one stalled flush is
    the ramp-down waiting on the file system. So each write is TIMED, and
    a directory that behaves like a slow share flushes only periodically
    (`.slow`), on a window sized to CLEAR the worst write seen so far --
    a fixed window shorter than the write is no throttle at all. The
    window in force is said out loud in `summary()`.

    `hold_flush` is the harder version of the same idea, for the seconds
    between a confirmed breakdown and the SG reaching 0 V: rows are still
    written (they are the record of the event) but nothing is flushed
    until `close()`, which the runner calls after the HV is down.

    This bounds the flush DUTY CYCLE, not the worst single stall: one
    unlucky flush still parks the run thread for its full duration.
    Taking that out needs the write off this thread entirely -- a queue
    drained after the SG is zeroed -- which is a follow-up, not this
    change. `max_write_s` is deliberately monotonic (the window never
    re-tightens), so one pathological write keeps the file lazily
    flushed for the rest of the run; `close()` still commits everything
    on any ordinary end, abort or exception.
    """

    def __init__(self, path, target_hz=TELEMETRY_MAX_HZ,
                 kv_min_period_s=TELEMETRY_KV_MIN_PERIOD_S,
                 slow_write_s=TELEMETRY_SLOW_WRITE_S, clock=None):
        import csv as _csv
        import time as _time
        self.path = path
        self._clock = clock or _time.monotonic
        self.slow_write_s = float(slow_write_s)
        self.slow = False              # degraded to periodic flushing
        self.hold_flush = False        # HV-shutdown path: buffer only
        self.max_write_s = 0.0
        self._last_flush_t = None
        self.target_hz = clamp_telemetry_hz(target_hz)
        self.period_s = 1.0 / self.target_hz
        # never ask for kV faster than the samples themselves
        self.kv_period_s = max(float(kv_min_period_s), self.period_s)
        self.rows = 0                    # every row, event rows included
        self.samples = 0                 # periodic samples only (rate math)
        self.kv_rows = 0
        self.unreadable = 0              # i_status invalid/error
        self.offscreen = 0               # i_status offscreen
        self.failed = False
        self.last_error = None
        self.max_gap_s = 0.0
        self._first_t = None
        self._last_t = None
        self._next_due = 0.0
        self._next_kv_due = 0.0
        # utf-8 explicitly (not the platform codec): the bench writes on
        # Linux and the analysis PC reads on Windows, and the same file
        # must decode identically on both (audit 2026-08-05, data.csv).
        # `event` is ASCII-clamped on the way in, so the file stays plain
        # ASCII in practice and Excel is happy either way.
        self._f = open(path, 'w', newline='', encoding='utf-8')
        self._w = _csv.DictWriter(self._f, fieldnames=TELEMETRY_COLUMNS)
        self._w.writeheader()
        self._f.flush()

    # ---- schedule -------------------------------------------------------
    def due(self, t_s):
        """Is a periodic sample due at elapsed time `t_s`?"""
        return not self.failed and float(t_s) >= self._next_due

    def kv_due(self, t_s):
        """Should this sample also spend a round-trip on V_Out?

        Asked BEFORE the read so a skipped kV costs nothing at all."""
        return not self.failed and float(t_s) >= self._next_kv_due

    # ---- writing --------------------------------------------------------
    def sample(self, t_s, timestamp, nominal_kv, ua=None, i_status='',
               kv=None, v_status='', event=''):
        """Write one periodic sample and advance the schedule.

        Unreadable samples are written too -- a gap in the record is the
        evidence that monitoring was lost, and blanking it silently is the
        bug #159 was filed about. Returns True when the row was written."""
        t = float(t_s)
        if self._last_t is not None:
            self.max_gap_s = max(self.max_gap_s, t - self._last_t)
        # schedule from the ACTUAL sample time, like the watchdog's own
        # gate: a stalled scope must not leave a burst of catch-up rows.
        self._next_due = t + self.period_s
        if v_status and v_status != 'skipped':
            self._next_kv_due = t + self.kv_period_s
        ok = self._write(t, timestamp, nominal_kv, ua, i_status, kv,
                         v_status or 'skipped', event)
        if ok:
            self.samples += 1
            self._first_t = t if self._first_t is None else self._first_t
            self._last_t = t
            if v_status and v_status != 'skipped':
                self.kv_rows += 1
            if i_status == 'offscreen':
                self.offscreen += 1
            elif i_status in ('invalid', 'error'):
                self.unreadable += 1
        return ok

    def event(self, t_s, timestamp, nominal_kv, event, ua=None, i_status='',
              kv=None, v_status=''):
        """Write a row that marks something (a snapshot, the breakdown
        trip) without disturbing the periodic schedule or the rate math --
        it reuses readings that were taken for another purpose."""
        return self._write(float(t_s), timestamp, nominal_kv, ua,
                           i_status or 'skipped', kv, v_status or 'skipped',
                           event)

    def _write(self, t_s, timestamp, nominal_kv, ua, i_status, kv, v_status,
               event):
        if self.failed:
            return False
        # Flush every row while the file system is keeping up (an aborted
        # run then has a complete file); once it is not, only once per
        # flush window, so the run loop is not the thing waiting on the
        # share. On the HV-shutdown path, not at all until close().
        do_flush = (not self.hold_flush
                    and (not self.slow or self._last_flush_t is None
                         or t_s - self._last_flush_t
                         >= self.flush_period_s()))
        started = self._clock()
        try:
            self._w.writerow({
                't_s': round(t_s, 3),
                'timestamp': timestamp,
                'nominal_kV': _telemetry_num(nominal_kv, 4),
                'measured_kV': _telemetry_num(kv, 4),
                'measured_uA': _telemetry_num(ua, 2),
                'v_status': v_status,
                'i_status': i_status or 'skipped',
                # ASCII-clamped so the file cannot depend on the caller's
                # vocabulary staying ASCII (the run log's own is not: ⚡, µA)
                'event': str(event).encode('ascii', 'replace').decode(),
            })
            if do_flush:
                self._f.flush()
                self._last_flush_t = t_s
        except Exception as e:       # disk full, device gone, encoding...
            self.failed = True
            self.last_error = e
            return False
        took = self._clock() - started
        if took > self.max_write_s:
            self.max_write_s = took
        if took >= self.slow_write_s:
            self.slow = True
        self.rows += 1
        return True

    # ---- reporting ------------------------------------------------------
    def flush_period_s(self):
        """Seconds between flushes while degraded.

        Sized to clear the worst write seen: a window shorter than a
        single write has always already expired by the next row, which
        made the throttle a no-op on a badly stalled share (measured,
        review 2026-08-05). `summary()` reports THIS number rather than
        the constant, so the run log cannot claim a throttle that is not
        in force."""
        return max(TELEMETRY_SLOW_FLUSH_PERIOD_S,
                   TELEMETRY_SLOW_FLUSH_MARGIN * self.max_write_s)

    def achieved_hz(self):
        """Mean sample rate actually achieved, or None with < 2 samples."""
        if self.samples < 2 or self._first_t is None:
            return None
        span = self._last_t - self._first_t
        return (self.samples - 1) / span if span > 0 else None

    def summary(self):
        """One log line: what was recorded and whether the rate held.

        #157's acceptance asks for the ACHIEVED rate to be visible, so a
        run where the hardware could not keep up says so in run.log
        instead of quietly producing a sparse file."""
        if self.failed and self.rows == 0:
            return (f"telemetry: FAILED before any row was written "
                    f"({self.last_error})")
        hz = self.achieved_hz()
        parts = [f"telemetry: {self.samples} samples"]
        if hz is not None:
            parts.append(f"{hz:.2f} Hz achieved (target {self.target_hz:g})")
        parts.append(f"max gap {self.max_gap_s:.1f} s")
        parts.append(f"{self.kv_rows} with kV")
        if self.offscreen:
            parts.append(f"{self.offscreen} off-screen")
        if self.unreadable:
            parts.append(f"{self.unreadable} unreadable")
        if self.slow:
            parts.append(f"SLOW DISK ({self.max_write_s:.2f} s worst write) "
                         f"— flushed every {self.flush_period_s():.1f} s, "
                         f"not per row")
        if self.failed:
            parts.append(f"STOPPED EARLY ({self.last_error})")
        return ", ".join(parts) + f" -> {TELEMETRY_FILENAME}"

    def rate_shortfall(self):
        """True when the achieved rate missed the target badly enough to
        mention -- the loop or the scope could not keep up. See
        TELEMETRY_SHORTFALL_FRAC for why the bar is not tighter."""
        hz = self.achieved_hz()
        return (hz is not None
                and hz < TELEMETRY_SHORTFALL_FRAC * self.target_hz)

    def close(self):
        try:
            self._f.close()
        except Exception:
            pass


class SldeaProfile:
    """A full staircase test built from the tab's input fields."""

    CSV_COLUMNS = [
        'snapshot', 'step', 'tag', 'nominal_kV', 'control_V',
        'measured_kV', 'measured_uA', 't_planned_s', 'timestamp', 'frame_file',
        # left empty at capture time; filled by the edge-detection pass later
        # (wrinkle_idx = high-freq texture vs baseline; wrinkled = active):
        'active_area_px', 'active_area_mm2', 'active_diam_mm', 'wrinkle_idx',
        'notes',
    ]

    def __init__(self, start_kv=0.0, end_kv=10.0, step_kv=0.25, n_steps=None,
                 ramp_s=5.0, landing_s=60.0, settle_s=2.0, snap_lead_s=1.0,
                 repeat=1, updown=False, baseline=True,
                 snap_post=True, snap_pre=True,
                 baseline_warmup_s=BASELINE_WARMUP_S):
        for name, val in (('start_kv', start_kv), ('end_kv', end_kv)):
            if not 0.0 <= val <= TREK_MAX_KV:
                raise ValueError(f"{name}={val} kV out of range 0..{TREK_MAX_KV}")
        if ramp_s < 0:
            raise ValueError("ramp_s must be >= 0")
        if landing_s <= 0:
            raise ValueError("landing_s must be > 0")
        if settle_s < 0 or snap_lead_s < 0:
            raise ValueError("settle_s and snap_lead_s must be >= 0")
        if not (snap_post or snap_pre or baseline):
            raise ValueError("no snapshots requested")
        if snap_post and settle_s >= landing_s:
            raise ValueError("settle_s must be < landing_s")
        if snap_pre and snap_lead_s >= landing_s:
            raise ValueError("snap_lead_s must be < landing_s")
        if snap_post and snap_pre and settle_s + snap_lead_s >= landing_s:
            raise ValueError("settle_s + snap_lead_s must be < landing_s")

        self.levels = compute_levels(start_kv, end_kv, step_kv, n_steps)
        # 0 kV is captured as the baseline, not held as a landing -- a 0 kV
        # hold does nothing to a DEA, so drop a leading zero level.
        if self.levels and abs(self.levels[0]) < 1e-9:
            self.levels = self.levels[1:]
        if not self.levels:
            raise ValueError("no non-zero landing levels to run")
        if max(self.levels) > TREK_MAX_KV + 1e-9:
            raise ValueError(f"a level exceeds the Trek max {TREK_MAX_KV} kV")

        self.start_kv, self.end_kv = start_kv, end_kv
        self.step_kv, self.n_steps_req = step_kv, n_steps
        self.ramp_s, self.landing_s = float(ramp_s), float(landing_s)
        self.settle_s, self.snap_lead_s = float(settle_s), float(snap_lead_s)
        self.repeat = max(1, int(repeat))
        self.updown, self.baseline = bool(updown), bool(baseline)
        self.snap_post, self.snap_pre = bool(snap_post), bool(snap_pre)
        self.baseline_warmup_s = max(0.0, float(baseline_warmup_s))
        self._build()

    def sequence(self):
        """The full ordered list of landing voltages (with up/down + repeat)."""
        seq = list(self.levels)
        if self.updown and len(self.levels) > 1:
            seq = seq + list(reversed(self.levels[:-1]))
        return seq * self.repeat

    def _build(self):
        self.segments = []    # (kind, t0, t1, from_kv, to_kv), kind ramp|hold
        self.snapshots = []   # {t, step, nominal_kv, tag}
        t = 0.0
        if self.baseline:
            # TWO frames at 0 kV when a warm-up is configured. The first
            # is thrown at the camera to make it settle; the SECOND is
            # the reference every area in the run is differenced against.
            # The 2026-08-05 CB run is why: its baseline came out 73.7%
            # saturated while its own ramp frames were 0.27%, i.e. the
            # reference was exposed differently from everything compared
            # against it. Tagged 'warmup', NOT 'baseline-warmup' --
            # sldea_plot phases rows with tag.startswith('baseline'), so
            # a baseline-prefixed tag would be averaged into A0.
            if self.baseline_warmup_s > 0:
                self.snapshots.append(
                    {'t': 0.0, 'step': 0, 'nominal_kv': 0.0,
                     'tag': 'warmup'})
                t = self.baseline_warmup_s
            self.snapshots.append(
                {'t': t, 'step': 0, 'nominal_kv': 0.0, 'tag': 'baseline'})
        prev = 0.0
        for step, lvl in enumerate(self.sequence(), start=1):
            self.segments.append(('ramp', t, t + self.ramp_s, prev, lvl))
            t_ramp_end = t + self.ramp_s
            t_hold_end = t_ramp_end + self.landing_s
            self.segments.append(('hold', t_ramp_end, t_hold_end, lvl, lvl))
            if self.snap_post:
                self.snapshots.append(
                    {'t': t_ramp_end + self.settle_s, 'step': step,
                     'nominal_kv': lvl, 'tag': 'post-ramp'})
            if self.snap_pre:
                self.snapshots.append(
                    {'t': t_hold_end - self.snap_lead_s, 'step': step,
                     'nominal_kv': lvl, 'tag': 'pre-ramp'})
            prev = lvl
            t = t_hold_end
        self.total_duration_s = t
        self.n_levels = len(self.sequence())
        self.n_frames = len(self.snapshots)

    def kv_at(self, t):
        """Target Trek voltage (kV) at time t -- for the runner's ramp and the
        preview curve.

        SAFETY: t before the first segment returns 0.0. With a warm-up
        baseline the staircase no longer starts at t=0, and the
        fall-through below returns the FINAL level -- which would have
        commanded the SG to full scale for the whole warm-up window."""
        if t <= 0:
            return 0.0
        if self.segments and t < self.segments[0][1]:
            return 0.0
        for kind, t0, t1, a, b in self.segments:
            if t0 <= t <= t1:
                if kind == 'hold' or t1 == t0:
                    return b
                return a + (b - a) * (t - t0) / (t1 - t0)
        return self.segments[-1][4] if self.segments else 0.0

    # ---- run layout / naming -------------------------------------------
    @staticmethod
    def run_dirname(dt):
        """Auto directory name from the run start datetime."""
        return dt.strftime("SLDEA_%Y%m%d_%H%M%S")

    @staticmethod
    def frame_filename(step, nominal_kv, tag):
        return f"SLDEA_s{int(step):02d}_{float(nominal_kv):05.2f}kV_{tag}.png"

    def summary(self):
        return (f"{len(self.levels)} levels "
                f"{self.start_kv:g}->{self.end_kv:g} kV"
                f"{' (up/down)' if self.updown else ''}"
                f"{f' x{self.repeat}' if self.repeat > 1 else ''}: "
                f"{self.n_levels} landings, {self.n_frames} frames, "
                f"total {fmt_duration(self.total_duration_s)}")

    def setup_text(self, run_name, started_iso, sg_ch, vmon_ch, imon_ch,
                   dry_run, cam_info='', dea_diam_mm=None, electrode=None,
                   concentration_ml=None, film_thickness_um=None,
                   watchdog=None, watchdog_shadow=None):
        """`watchdog` is watchdog_record's setup line (#406), written under
        the I_Out line it watches; None (a caller that predates it) writes
        no line, so an older run and an OFF run stay apart.
        `watchdog_shadow` is shadow_record's line (#219), written right
        under it on the same terms."""
        step_desc = (f"{self.step_kv:g} kV/step" if self.step_kv
                     else f"{self.n_steps_req} steps")
        return "\n".join([
            f"SLDEA Test  --  {run_name}",
            f"Started: {started_iso}",
            "MODE: *** DRY RUN (HV output OFF) ***" if dry_run
            else "MODE: LIVE (HV energized)",
            "",
            "--- Drive ---",
            f"HV gain: {HV_GAIN_KV_PER_V:g} V(control) = "
            f"{HV_GAIN_KV_PER_V:g} kV(Trek);  Trek max {TREK_MAX_KV:g} kV",
            f"SG: CH{sg_ch} DC control voltage (High-Z)",
            f"Sweep: {self.start_kv:g} -> {self.end_kv:g} kV, {step_desc}, "
            f"{len(self.levels)} levels"
            f"{', up/down' if self.updown else ''}"
            f"{f', repeat x{self.repeat}' if self.repeat > 1 else ''}",
            f"Ramp {self.ramp_s:g}s | Landing {self.landing_s:g}s | "
            f"Settle {self.settle_s:g}s | Snap-lead {self.snap_lead_s:g}s",
            f"Total: {fmt_duration(self.total_duration_s)}  "
            f"({self.n_levels} landings, {self.n_frames} frames)",
            "",
            "--- Measurement (Trek monitors on scope) ---",
            f"V_Out: scope CH{vmon_ch}  ({VMON_KV_PER_V:g} kV per scope-volt)",
            f"I_Out: scope CH{imon_ch}  ({IMON_UA_PER_V:g} uA per scope-volt; "
            f"10 V = 2000 uA)"] + ([] if watchdog is None else [watchdog])
            + ([] if watchdog_shadow is None else [watchdog_shadow]) + [
            "",
            "--- Camera ---",
            cam_info or "(settings not recorded)",
            ""] + ([f"DEA nominal diameter: {dea_diam_mm:g} mm", ""]
                   if dea_diam_mm else []) + (
            [f"Compliant electrode: {str(electrode).strip()}",
             f"Electrode family: {electrode_family(electrode)}"]
            if str(electrode or '').strip()
            else ["Compliant electrode: (not specified)"]) + (
            # Ink concentration (`#276`), beside the electrode it belongs
            # to. OMITTED ENTIRELY when the electrode is not an ink: a
            # carbon-black run must not carry a CNT-ink key at all, empty
            # or otherwise. When it DOES apply, a blank answer is written
            # as "(not specified)" rather than dropped -- the same rule the
            # electrode line follows, so a run that declined to answer and
            # a run that predates the field stay distinguishable.
            [f"Ink concentration: {str(concentration_ml).strip()} mL"
             if str(concentration_ml or '').strip()
             else "Ink concentration: (not specified)"]
            if concentration_applies(electrode) else []) + (
            # Film thickness (`#398`), t0 for the plot's field axis, in the
            # same device block. The concentration's three states: the
            # value as typed with its unit, "(not specified)" when the
            # operator was asked and declined (''), and NO line from a
            # caller that predates the field (None), so a run that
            # declined and a run that never had the box stay apart.
            [] if film_thickness_um is None
            else [f"Film thickness: {str(film_thickness_um).strip()} "
                  f"{FILM_THICKNESS_UNIT}"
                  if str(film_thickness_um).strip()
                  else "Film thickness: (not specified)"]) + ["",
            "--- Snapshots ---",
            ("baseline @ 0 kV"
             + (f" (after a {self.baseline_warmup_s:g}s camera warm-up "
                f"frame tagged 'warmup'; the staircase starts at "
                f"{self.baseline_warmup_s:g}s)"
                if self.baseline_warmup_s > 0 else ""))
            if self.baseline else "(no baseline)",
            "per landing: "
            + ", ".join(([f"post-ramp (ramp-end + {self.settle_s:g}s)"]
                         if self.snap_post else [])
                        + ([f"pre-ramp (landing-end - {self.snap_lead_s:g}s, "
                            f"just before the next ramp)"]
                           if self.snap_pre else [])),
        ]) + "\n"
