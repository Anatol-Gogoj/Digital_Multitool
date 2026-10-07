#!/usr/bin/env python3
"""Cross-run plotting for SLDEA run data (issue #199).

Usage:
    python sldea_plot.py RUN [RUN2 ...] [--mode area|current|power]
                         [--vs-area] [--prepost] [--mean] [--no-bands]
                         [--no-breakdown] [--out DIR] [--stem NAME]
                         [--title TEXT] [--allow-suspect-scale]
                         [--allow-old-estimator]
                         [--logx] [--logy] [--no-marker-key]
                         [--title-first TEXT] [--title-second TEXT]
                         [--subplots both|first|second] [--cadence-guard]
                         [--aggregate] [--aggregate-exact]
                         [--group NAME=RUN[,RUN...]] [--aggregate-only]
                         [--strain-pct] [--x kv|time|field] [--merge-legs]
                         [--no-arrows] [--format png|svg] [--dpi N]
    python sldea_plot.py --from-spec FILE.figspec.json [flags to override]
    python sldea_plot.py --gui [RUN ...]        # window (see below)
    python sldea_plot.py --selftest [OUT.png]

Each RUN is a run directory, a parent full of runs (newest wins) or a bench
shortcut ('1'/'2'/'3') -- the same resolver as the tuner and diagnostic.
Writes the figure, the underlying tidy per-snapshot CSV and the figspec
sidecar (below), all named after --stem (default 'sldea_plot_<mode>'), into
--out (default the current directory). Custom --stem names written inside
the repo checkout are NOT gitignored -- keep the default 'sldea_plot'
prefix there, or point --out outside the checkout.

    --format  png (default) or svg. Only the IMAGE changes -- the tidy CSV
              and the figspec are written for both, off the same stem.
    --dpi     the raster resolution, 300 by default, 50-1200. Outside that
              it is REFUSED rather than clamped (a typed '30000' asks for
              a render that looks like a hang). Ignored for --format svg,
              which is a vector format pinned to 72 dpi by the backend --
              the window greys the field rather than pretending otherwise.
              Both are recorded in the figspec, so --from-spec re-renders
              the format and resolution it names.

Modes:
    area      (default) two panels: active area (mm^2) vs nominal kV, and
              the same curves normalized to expansion A/A0 (A0 = the run's
              baseline area), or to areal strain (A-A0)/A0*100 in percent
              with --strain-pct. Needs reviewed areas; raw runs are
              skipped with a warning.
    current   measured_uA vs nominal kV, one point per snapshot. Works on
              raw runs; the run-median current baseline is drawn dotted.
    power     |nominal_kV x (measured_uA - run median)| (mW) vs nominal
              kV -- offset-corrected, mirroring breakdown_flags' median
              baseline (audit 2026-08-05: the raw product was ~100%
              instrument zero x kV on the -16 uA-idle era and rank-
              inverted real dissipation). Runs with < 5 parseable uA
              rows keep the raw product, flagged in the caption.
    --vs-area swaps the x axis to active area (current/power modes only;
              needs reviewed areas like area mode).
    --x time  draws every mode against elapsed time since each run started
              (minutes; the scheduled t_planned_s, else the wall-clock
              timestamps) instead of nominal kV: one point per snapshot in
              the order taken, so an up/down or repeated run no longer
              folds back over itself. Refuses --prepost/--mean/--aggregate
              (they pool per kV level) and --vs-area.
    --x field draws every mode against the nominal electric field
              E = V / t0 in V/um (2026-10-06, `#398`): V is the nominal
              voltage the kV axis uses, t0 the film thickness the run's
              setup.txt records ('Film thickness: 50 um', measured with
              the film mounted and prestretched). Runs on films of
              different thickness then share an axis. A run with no usable
              thickness is left off, by name, with how to add the line to
              setup.txt by hand; this tool never writes setup.txt. Each
              run's t0 is fixed when the figure is made and stored in the
              figspec ('film_thickness'), so --from-spec draws the same
              figure after a setup.txt edit, and the tidy CSV carries t0
              and the field on every row. The X marks sit at the breakdown
              field. --aggregate pools runs on the field grid by
              interpolation; --aggregate-exact pools only runs that share
              one t0, since films of different thickness share no field
              levels. Refuses --vs-area.

Up/down and repeated runs:
    A run whose voltage also FELL (Up/down, or a Repeat that restarts
    below where it ended) is drawn leg by leg: one line per leg,
    triangle-up points rising and triangle-down falling, per LANDING
    rather than per kV level -- keyed by kV, the two legs used to average
    into one point and --prepost kept only the last leg. Small arrowheads
    follow the direction of travel. The aggregate takes such a run's
    first rising leg. --merge-legs restores the per-kV averaging and
    --no-arrows drops the arrowheads; a single sweep is unaffected by
    either.

Rendering:
    - Default lines are the per-level MEAN of the pre/post snapshot pair;
      --prepost draws post-ramp solid and pre-ramp dashed instead, and
      --mean adds the mean line back on top of those.
    - Uncertainty bands: +-2% on machine-measured stretches, +-1% on
      hand-traced ones (--no-bands hides them). A level mixing traced and
      machine snapshots keeps the machine +-2% band. Open markers = the
      level (with --prepost: the snapshot) includes a hand-traced boundary.
      The percentages are of the AREA. Under --strain-pct the band is built
      from A/A0 and then converted, so it is +-2 strain points at 0 % strain
      and +-2 x A/A0 points in general (+-2.8 at 40 % strain), not +-2% of
      the strain value.
    - The open/closed marker meaning is a KEY on the figure (`#267`): two
      proxy handles in their own compact legend, lower right of the area
      panel, so the run legend upper left keeps its corner and does not
      grow by two fixed rows on every plot. On by default;
      --no-marker-key hides it. Area mode only -- current/power draw one
      plain dot per snapshot with no open/closed meaning, and a key there
      would claim a distinction the figure does not make.
    - The caption under the panels is WRAPPED to the figure's width,
      measured from the font, so no sentence runs off the right edge, in
      the window at any size or in an export at any dpi (2026-10-06).
      Continuation rows are indented. A figure whose caption already fits
      keeps the layout it always had; one that wraps gets a caption strip
      tall enough to hold it.
    - --aggregate (area mode only) adds ONE mean curve across the selected
      runs, in black with square markers. Its band is the STANDARD ERROR
      OF THE MEAN, sigma/sqrt(n), per level -- and with a single run
      selected there is NO band at all, plus a caption saying the
      aggregate needs >= 2 runs. The calibrated +-1-2% budget band belongs
      to one run's pre/post average and is suppressed under the aggregate,
      exactly as --prepost suppresses it. The runs are put on a common
      grid by interpolation, never extrapolated past a run's own measured
      range and never interpolated across a breakdown. The caption states
      the aggregate's n; a level whose MEASURED support falls below that n
      prints its own count above the x axis ('a+b' = a measured + b
      interpolated), and no other level prints anything, so a family on one
      grid draws a clean figure and a thinly interpolated level still
      announces itself (`#312`). --aggregate-exact pools only exact levels
      instead. The aggregate stops at the first current-confirmed
      breakdown, past which the mean would mix intact and collapsed
      devices (`#268`, policy in SLDEA_HANDOFF.md 2026-08-09).
    - --group NAME=RUN[,RUN...] puts the named runs in a GROUP, and the
      aggregate then averages EACH GROUP SEPARATELY instead of averaging
      everything selected (`#313`). Repeat the flag for a second group:
      --group CB=SLCBvalidationTest --group P3=P3_1_2.5mL_20260728,...
      draws two mean curves on one panel, which is the carbon-black
      against P3 comparison the campaign is for. Every rule above still
      holds PER GROUP -- the SEM band, the no-band-and-a-caption refusal
      at n = 1, the no-extrapolation and no-interpolation-across-a-
      breakdown guardrails, and the first-breakdown cap, each computed
      from that group's own runs. A run may be in at most one group; runs
      in no group are drawn but contribute to no mean. A RUN is named by
      its directory (absolute is safest -- two runs in different parents
      can share a name) or by its bare folder name when that is
      unambiguous among the plotted runs.
    - Each group mean's LINE STYLE marks its electrode MATERIAL (`#373`):
      the groups whose runs all recorded one `Compliant electrode:` in
      setup.txt share that material's style and differ by color, and a
      group of no single material gets a style no other group has. No
      two group means on a figure share both color and style. The
      material is read when the group is FORMED: here, from each
      --group's runs at this invocation; in the window, by its "Group by
      material" seed or an Assign. It is stored in the figspec as
      `group_materials`, so --from-spec restyles nothing even if a
      setup.txt changed since.
    - --aggregate-only hides the contributing per-run curves so the panel
      carries the group means alone -- two lines and not fifteen, which
      is the state the comparison is actually read in. The runs are still
      loaded, still guarded and still written to the tidy CSV in full; it
      is the DRAWING that stops, and the caption says so.
    - Colors are the Paul Tol bright family (colorblind-safe, house
      convention), assigned to runs in argument order. Group means take
      the Paul Tol HIGH-CONTRAST palette instead (extended to seven from
      Tol's muted and medium-contrast schemes, `#373`), plus a line style,
      because a statistic must not look like one more measurement -- see
      GROUP_COLORS for what that separation measures.
    - Areas predating the 2026-07-28 scale fix (2.3-2.7x blob bug) are
      excluded from area axes unless the run's baseline matches the
      nominal disc; --allow-suspect-scale overrides. In current/power
      modes such runs still plot (currents are unaffected) but their area
      columns are blanked in the tidy CSV so eras cannot be mixed.
    - disc-fit areas saved by the OLD area method (the fitted ellipse,
      before 2026-10-02: no 'area_estimator: 2' line in the run's
      setup.txt) are excluded from area axes the same way; they read
      -0.4 to +7.4% off the common-ray ratio at rest, a different offset
      per run. Re-review the run in Edge Review, or --allow-old-estimator
      draws it anyway, named in the caption, with the estimator in the
      tidy CSV's area_estimator column. In current/power modes the run
      plots with its area columns blanked. Beside that column the tidy
      CSV carries the OpenCV and numpy versions the Save recorded
      (opencv_version, numpy_version; 2026-10-03) on every
      machine-measured row, and the boundary tracker's window limits
      the Save recorded (ray_win_hi, disc_fit_r_max; 2026-10-03) on
      every disc-fit row.

Panels (`#269` titles, `#270` selection):
    The panels a mode actually draws, in the order the flags name them:

        area            first  = active area vs nominal kV
                        second = the same curves as A/A0, or as areal
                                 strain in percent under --strain-pct
        current, power  first  = the single per-snapshot panel
                        (there is no second panel in these modes)

    --title-first / --title-second replace that panel's heading; blank or
    absent keeps the built-in default, so a figure only carries a hand
    written title where somebody wrote one. --title predates these and
    has always meant the FIRST panel, so it still does: --title-first
    wins over it, and both lose to nothing (the default). --title-second
    in current/power mode is accepted and does nothing -- there is no
    second panel to title.

    --subplots picks which of them render: 'both' (default), 'first' or
    'second'. A single chosen panel is created as the figure's ONLY axes
    so it fills the canvas -- not a two-column grid with one column
    blanked, which would squeeze the survivor into half a figure beside
    white space -- and it keeps the run legend and the marker key.
    'second' outside area mode is refused (there is no second panel to
    draw); 'first' there is a no-op naming the only panel. The tidy CSV
    does NOT shrink with the selection: it is the per-snapshot evidence
    for the numbers, not a description of the layout, and the two panels
    are two views of the same areas.

Cadence guard (`#264`, OPT-IN):
    --cadence-guard asks how often a run measured CURRENT and, where that
    is slower than 1 s, draws its breakdown X hollow and states the
    spacing in the caption. The mark stays on the figure: the event is
    just as current-confirmed, it is its ONSET that is an interval rather
    than a point, and suppressing a real event because the camera was
    slow would be the P3_5 mistake pointing the other way.

    Cadence comes from telemetry.csv beside data.csv (present = the ~2 Hz
    monitor log ran, so current was sampled continuously), else from the
    MEDIAN gap between snapshot timestamps. Threshold 1 s, because that is
    the telemetry logger's slowest guaranteed kV/uA period; an unmeasurable
    cadence is never treated as coarse.

    OFF by default, deliberately, and this is a decision for the bench to
    make rather than a plotting preference. No run in the 2026-08-04
    corpus carries telemetry.csv and every one of the thirteen samples
    current between 4.6 s and 32.5 s (median), so an automatic guard would
    restyle the breakdown marks on every figure the suite has ever made.
    That is a change to how a current-confirmed event is PRESENTED, which
    under CLAUDE.md is measurement-chain behaviour and belongs in a dated
    SLDEA_HANDOFF.md decision -- not in a rendering default. Turn it on
    per figure until that decision exists.

Figspec sidecar (`#273`):
    Every export writes a THIRD file beside the PNG and the CSV:
    <stem>.figspec.json, carrying the exact options, the run directories
    that were plotted (resolved and absolute -- a bench shortcut means a
    different run tomorrow) and two versions: the app's, and the spec
    FORMAT's. A PNG travels into slide decks and papers; the command line
    that made it does not, and six months later 'which runs is this?' has
    to be answerable from the file itself.

    --from-spec FILE re-renders from one. Precedence is one rule applied
    to every option: an explicitly given command-line flag beats the
    spec's value, which beats the built-in default. Positional RUN
    arguments REPLACE the spec's run list rather than adding to it (the
    common case is 'this figure, other runs'). --out is never taken from
    a spec -- a spec describes the figure, not the folder somebody filed
    it in -- and --stem comes from the spec unless you give one.

    The one asymmetry: boolean flags are one-way switches. --prepost can
    turn a spec's false ON, --no-bands can turn a spec's true OFF, but
    there is no --bands to turn a spec's false back on. Edit the spec; it
    is JSON, and that is half the point.

    A spec is validated, not trusted: it is a file a human can edit, so
    its options go back through make_opts and an illegal combination is
    refused with the same wording as on the command line. A spec_version
    from a newer build is refused rather than half-understood.

Log scales (`#263`):
    --logx / --logy put the x / y axis on a logarithmic scale. The axis
    kind is chosen from the DATA, per axis and per panel:

      all plotted values > 0      -> plain log10
      any value <= 0              -> symlog, linear inside +-linthresh
                                     and log outside, where linthresh is
                                     the smallest nonzero |value| rounded
                                     DOWN to a power of ten

    Symlog rather than clipping is deliberate. This suite's currents are
    NEGATIVE on the whole 07-29 era (the I_Out offset idles at ~-16 uA)
    and every run's x axis starts at the 0 kV baseline row, so a plain log
    scale would drop the entire current trace and the resting tier -- and
    dropping rows to make an axis work is the one thing this tool does not
    do (see the P3_5 lesson below). Symlog keeps every point, keeps the
    sign, and the caption names the scale and the linthresh so a reader
    cannot mistake the linear-near-zero region for log.

    An axis with no finite values, or one whose values are all exactly
    zero, is left LINEAR and says so in the caption rather than raising.

Breakdown marks (the P3_5 lesson, 2026-08-05 semantics):
    X marks come from RECOMPUTING the current-based detector
    (sldea_edge.breakdown_flags) on the saved CSV -- never from the saved
    *_BREAKDOWN renames / 'breakdown?' / 'post-breakdown' notes, which can
    predate the current semantics: the old area-jump heuristic once branded
    35 healthy frames of P3_5 while the current stayed flat. Saved brands
    the recompute does not explain (branded rows BEFORE the first confirmed
    row, or any brand when nothing confirms) get a stale-brand warning. A
    confirmed row without a reviewed area is anchored to its kV as a dashed
    vertical instead of being silently dropped. Rows are NEVER dropped or
    restyled because of breakdown annotations -- 'post-breakdown' rows plot
    exactly like any other row.

Window (`#223`):
    --gui opens the point-and-click front end (sldea_plot_gui.py, also
    launchable on its own and from the app's SLDEA tab). It is a FRONT END
    to the functions below, not a second implementation: it picks runs with
    prepare_runs, draws with draw() and writes with export(), so a figure
    made in the window and the same figure made here are the same figure.
    Any RUN arguments and flags given alongside --gui preselect the window.
    The headless paths are unchanged -- batch scripting and --selftest are
    real usage and stay first-class.
"""
import csv
import datetime
import io
import math
import os
import re
import sys

import sldea_edge as se
import sldea_profile as sprof

# Paul Tol bright (house palette for plots -- CLAUDE.md). Canonical order:
# adjacent pairs keep CVD deltaE >= 12 (validated 2026-08-05). Cyan/yellow/
# grey sit light on white surfaces, so marks carry a darker edge and every
# figure ships with its tidy CSV as the readable fallback.
TOL_BRIGHT = ['#4477AA', '#66CCEE', '#228833', '#CCBB44',
              '#EE6677', '#AA3377', '#BBBBBB']

MODES = ('area', 'current', 'power')

# What a figure's x axis can be (2026-09-23). 'kv' is nominal voltage, the
# only axis until now; 'time' is elapsed time since the run started, the
# axis on which an up/down or repeated run stops folding back over itself.
# --vs-area stays its own flag: it predates this, and it is a current/
# power-mode switch rather than a third general axis.
#
# 'field' (2026-10-06, `#398`) is the nominal electric field E = V / t0 in
# V/um, t0 being the film thickness the run's setup.txt records. It is
# the kV axis RESCALED PER RUN: one run's t0 is one number, so its field is
# its kV times a constant (prepare_runs puts that constant in
# run['x_scale']), and everything that pools or places points by kV level
# (pre/post, the mean line, the legs, the aggregate and its cap, the
# breakdown marks) works on it unchanged.
X_AXES = ('kv', 'time', 'field')

# The x axes that are an electric FIELD, and so need each run's t0. One
# today. The true field (`#398` item 4, deferred) would be the second:
# E_true = (V / t0) * (A / A0) if the film keeps its volume and thins
# evenly. It is NOT a constant per run, since A moves at every snapshot,
# so it cannot ride run['x_scale']: it would take a branch of its own in
# x_value and in the per-level drawing, beside the per-run t0 that
# prepare_runs already resolves for every axis named here.
FIELD_AXES = ('field',)

# Each axis' label and the unit the captions and warnings quote positions
# on it in. Read through x_label / x_unit, never typed at a call site.
X_LABELS = {'kv': 'Nominal voltage (kV)',
            'time': 'Elapsed time (min)',
            'field': 'Nominal field  V / t₀  (V/µm)'}
X_UNITS = {'kv': 'kV', 'time': 'min', 'field': 'V/µm'}

# which panel(s) a figure renders (`#270`). 'first'/'second' name the same
# panels --title-first/--title-second do, so one vocabulary covers both.
SUBPLOTS = ('both', 'first', 'second')

# Figure geometry lives here rather than at each call site: the CLI's PNG,
# the window's Export and the window's on-screen canvas all size from this
# one table, so an exported figure cannot silently differ in shape from the
# command-line one (`#223`).
FIGSIZE = {'area': (12.6, 5.4), 'current': (9, 5.4), 'power': (9, 5.4)}

# What an export may LAND AS (`#314`). PNG stays the default -- every figure
# in the handoff and the slide decks is one -- and SVG is the vector answer
# for a figure that will be enlarged or re-lettered by a publisher.
FORMATS = ('png', 'svg')
DEFAULT_FORMAT = 'png'

# The raster resolution, in dots per inch. 300 stays the default (it is what
# every figure written before `#314` used, and what a journal asks for), but
# it is now a number the operator sets rather than one hard-wired at the
# three savefig call sites.
DEFAULT_DPI = 300
# The range, with a refusal outside it. The floor is where the 7-point
# caption stops being readable. The ceiling is measured, 2026-08-10, on the
# two-run area figure: 1200 dpi is 15120 x 6480 px -- 98 Mpx, ~390 MB of RGBA
# buffer, 3.1 s and 1.3 MB on disk, which is already generous for a figure
# that is 12.6 inches wide. The next order of magnitude is not slow, it is a
# hang: a typed '30000' asks for 61 GIGApixels. Refused, never clamped -- a
# figure quietly written at a resolution nobody asked for is the same class
# of failure as a flag that silently does nothing.
DPI_MIN, DPI_MAX = 50, 1200

# matplotlib salts the internal element ids of an SVG with a FRESH uuid4 per
# render when svg.hashsalt is None, and stamps the file with its creation
# date -- so two renders of the same figure differ byte for byte. Both are
# pinned in _savefig, because a figspec that cannot prove it re-rendered the
# same file is the failure load_figspec exists to prevent (`#273`), and the
# suite's window-vs-CLI byte comparison would be untestable for SVG.
SVG_HASHSALT = 'sldea_plot'

MACHINE_BAND_PCT = 2.0   # auto-accepted (half-height) stretches
TRACED_BAND_PCT = 1.0    # hand-traced (outer-toe) stretches
SCALE_FIX_DATE = '2026-07-28'   # active_area_mm2 before this may carry the
                                # 2.3-2.7x blob-scale bug -- never mix eras

_NOTE_RE = re.compile(r'edge:([A-Za-z_-]+) conf ([0-9.]+)(\s*\(user\))?')


def _f(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _int(text):
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _median(vals):
    """Same even-count median as sldea_edge.breakdown_flags, so the drawn
    baseline matches the value printed in the detector's reason text."""
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def load_rows(rundir):
    """The run CSV as parsed per-snapshot dicts (nothing filtered out).

    Reads through se.run_csv so renamed data1.csv runs still resolve, but
    opens utf-8-sig itself: the bench writes UTF-8 and load_run's default
    decode mojibakes the notes glyphs on Windows consoles."""
    path = se.run_csv(rundir)
    if path is None:
        raise FileNotFoundError(f"no run CSV in {rundir}")
    with open(path, newline='', encoding='utf-8-sig', errors='replace') as f:
        raw = list(csv.DictReader(f))
    rows = []
    for i, r in enumerate(raw):
        notes = (r.get('notes') or '').strip()
        m = _NOTE_RE.search(notes)
        tag = (r.get('tag') or '').strip()
        # prefix match keeps the 07-23 era ('post'/'pre') alongside the
        # current tags ('post-ramp'/'pre-ramp'), same as Edge Review's plot
        phase = next((p for p in ('baseline', 'post', 'pre')
                      if tag.startswith(p)), '')
        rows.append({
            'index': i,
            'snapshot': (r.get('snapshot') or '').strip(),
            'tag': tag, 'phase': phase,
            'kv': _f(r.get('nominal_kV')),
            # the landing number and the scheduled time: read so an up/down
            # run's legs and an elapsed-time axis can be derived (see
            # sweep_legs / elapsed_times); blank on old runs and fixtures
            'step': _int(r.get('step')),
            't_planned': _f(r.get('t_planned_s')),
            'ua': _f(r.get('measured_uA')),
            'area_mm2': _f(r.get('active_area_mm2')),
            'area_px': _f(r.get('active_area_px')),
            'timestamp': (r.get('timestamp') or '').strip(),
            'frame_file': (r.get('frame_file') or '').strip(),
            'method': m.group(1) if m else '',
            'conf': float(m.group(2)) if m else None,
            'user': bool(m and m.group(3)),
            'traced': bool(m and m.group(1) == 'manual-trace'),
            'notes': notes,
            'raw': r,
        })
    return rows


# ---------------------------------------------------------------------------
# sweep direction (2026-09-23)
#
# An "Up/down (hysteresis)" run visits every level below the peak twice --
# once rising, once falling -- and Repeat visits the whole sweep again.
# Everything above keys snapshots by kV, which on such a run AVERAGES the
# two legs into one point per level: the loop the run was recorded to show
# disappears from the figure, and --prepost's per-kV dict let the falling
# leg overwrite the rising one outright. The data carries no direction
# field, but it does not need one: CSV order is time order, and the
# direction of every ramp is written in the nominal kV sequence.
# ---------------------------------------------------------------------------

def sweep_legs(rows):
    """Annotate `rows` IN PLACE with where each sits in the sweep:

      'landing'  0 for the 0 kV frames before the first ramp (warm-up,
                 baseline), then 1, 2, ... one per voltage landing -- a
                 landing's post-ramp and pre-ramp snapshots share one
      'leg'      'rise' or 'fall': the direction of the ramp INTO the
                 landing. A landing at the SAME kV as the one before --
                 the bottom level landed twice where two up/down cycles
                 meet -- takes the direction of the ramp OUT of it
      'cycle'    1, 2, ...: advances wherever a falling leg turns to rise

    Rows without a kV get landing None, leg '' and cycle None. Landing
    identity comes from the `step` column when the run has one; runs that
    predate it (and the test fixtures) split a landing where the kV
    changes or a post-ramp snapshot follows a pre-ramp one. A watchdog
    'breakdown' row is always a landing of its own: it records the kV at
    the moment of the trip, which may be partway up a ramp.

    A single sweep comes out all 'rise' in cycle 1 -- the property every
    caller relies on to leave single-sweep figures exactly as they were.
    Returns `rows`."""
    landing, key, last, kvs = -1, None, None, []
    for r in rows:
        r['landing'] = None
        r['leg'], r['cycle'] = '', None
        if r['kv'] is None:
            continue
        if r['phase'] == 'baseline' or r['tag'] == 'warmup' or (
                r['step'] == 0 and landing <= 0):
            r['landing'] = 0
            if landing < 0:
                landing = 0
                kvs.append(0.0)
            continue
        if r['tag'].startswith('breakdown'):
            new = True
        elif r['step'] is not None and last is not None \
                and last['step'] is not None:
            new = r['step'] != last['step']
        else:
            new = (last is None or key is None
                   or round(r['kv'], 6) != key
                   or (r['phase'] == 'post' and last['phase'] == 'pre'))
        if new or landing < 1:
            landing = max(landing, 0) + 1
            if len(kvs) == 0:
                kvs.append(0.0)          # the 0 kV start, even unrecorded
            kvs.append(r['kv'])
        r['landing'] = landing
        key = round(r['kv'], 6)
        last = r
    legs, cycles = ['rise'], [1]         # landing 0: the resting start
    for i in range(1, len(kvs)):
        d = kvs[i] - kvs[i - 1]
        if abs(d) < 1e-9 and i + 1 < len(kvs):
            d = kvs[i + 1] - kvs[i]
        leg = legs[-1] if abs(d) < 1e-9 else ('rise' if d > 0 else 'fall')
        cycle = cycles[-1] + (1 if leg == 'rise' and legs[-1] == 'fall'
                              else 0)
        legs.append(leg)
        cycles.append(cycle)
    for r in rows:
        if r['landing'] is not None:
            r['leg'] = legs[r['landing']]
            r['cycle'] = cycles[r['landing']]
    return rows


def multi_leg(run):
    """True when the run's voltage ever FELL between landings: an up/down
    run, or a repeat whose next cycle starts below where the last ended.
    Only such runs are drawn leg by leg -- a single sweep keeps exactly
    the figure it always had."""
    return any(r.get('leg') == 'fall' for r in run['rows'])


def elapsed_times(rows):
    """Annotate `rows` IN PLACE with 'elapsed_s', seconds since the run
    started, and return where it came from: 't_planned_s', 'timestamp' or
    None.

    The scheduled time is preferred: it is on the run's own monotonic
    clock (the one telemetry.csv uses), so it is exact to the schedule and
    immune to the grab latency folded into each wall-clock timestamp. It
    is used only when EVERY row with a kV carries one -- a run is never
    drawn half on one clock and half on the other. Otherwise the
    timestamps, zeroed at the first that parses; a row with neither gets
    None and is left off a time axis rather than guessed at."""
    rows_kv = [r for r in rows if r['kv'] is not None]
    if rows_kv and all(r['t_planned'] is not None for r in rows_kv):
        for r in rows:
            r['elapsed_s'] = r['t_planned']
        return 't_planned_s'
    stamps = []
    for r in rows:
        try:
            stamps.append(datetime.datetime.fromisoformat(r['timestamp']))
        except (TypeError, ValueError):
            stamps.append(None)
    t0 = next((s for s in stamps if s is not None), None)
    for r, s in zip(rows, stamps):
        r['elapsed_s'] = (None if s is None or t0 is None
                          else (s - t0).total_seconds())
    return 'timestamp' if t0 is not None else None


def x_value(r, opts):
    """Where row `r` sits on this figure's x axis, or None when it has no
    such coordinate. ONE function because the drawers, the breakdown
    marks and the window's click-through must all agree on it -- the
    lesson norm_y was written to learn."""
    if opts.get('x') == 'time':
        t = r.get('elapsed_s')
        return None if t is None else t / 60.0
    if opts.get('x') in FIELD_AXES:
        # the row's field, put there by prepare_runs from its run's t0;
        # None on a row with no kV, or one never prepared for this axis
        return r.get('field')
    if opts.get('vs_area'):
        return r['area_mm2']
    return r['kv']


def x_label(opts):
    if opts.get('x') in ('time',) + FIELD_AXES:
        return X_LABELS[opts['x']]
    return 'Active area (mm²)' if opts.get('vs_area') \
        else X_LABELS['kv']


def x_unit(opts):
    """The unit a position on this figure's x axis is quoted in, in the
    captions and the warnings: 'kV', or 'V/um' (micro sign) on the field
    axis (`#398`). The aggregate's cap and its thinnest level are such
    positions; on the field axis they are fields, not voltages."""
    return X_UNITS.get(opts.get('x') or 'kv', X_UNITS['kv'])


def nominal_field(kv, t0_um):
    """E = V / t0 in V/um, from a nominal kV and a film t0_um micrometres
    thick, or None when either is missing (`#398`). 1 kV across 1 um is
    1000 V/um: 6 kV across a 50 um film is 120 V/um.

    The same product prepare_runs puts on every row (kV times the run's
    x_scale, 1000 / t0), so a value computed here and a row's x agree to
    the last bit."""
    if kv is None or not t0_um:
        return None
    return kv * (1000.0 / t0_um)


def load_run(arg, warn):
    """-> run dict (name, rows, A0, flags, advisories, saved-brand rows) or
    None when the argument does not resolve. `warn` collects messages."""
    rundir = se.resolve_run(arg)
    if not rundir:
        warn(f"not a run directory: {arg}")
        return None
    rows = load_rows(rundir)
    sweep_legs(rows)
    t_src = elapsed_times(rows)
    settings = se.load_settings(rundir)

    # breakdown: ALWAYS recomputed from the saved current trace; areas go
    # in so the collapse-corroboration branch behaves exactly like a save.
    # ONE unit for the whole run: a per-row px-else-mm2 fallback can hand
    # the ratio-based collapse test a px value next to an mm2 value
    # (~1400x apart) and confirm a 100% "collapse" on a healthy device --
    # stale mm2-only rows exist in the wild from the pre-2026-07-25
    # rejected-row bug. The GUI caller passes pure px; matched here.
    area_key = ('area_px' if any(r['area_px'] for r in rows)
                else 'area_mm2')
    areas = {r['index']: r[area_key] for r in rows if r[area_key]}
    # the run folder goes in too (decision 17, 2026-10-03), so the plot
    # and Edge Review reach one verdict on the watchdog's trip row and
    # draw the same monitor-log advisories
    flags, advis = se.breakdown_flags([r['raw'] for r in rows],
                                      areas, settings, rundir=rundir)
    saved_brand = [r['index'] for r in rows
                   if '_BREAKDOWN' in r['frame_file']
                   or 'breakdown?' in r['notes']
                   or 'post-breakdown' in r['notes']]
    name = os.path.basename(os.path.abspath(rundir))
    # A save brands every row at/after the FIRST confirmed flag, so brands
    # from min(flags) on are explained; earlier ones -- or all of them when
    # nothing confirms -- are stale. Per-row, so a run carrying both a
    # stale brand AND a real later event still warns (review 2026-08-05).
    first = min(flags) if flags else None
    stale = [i for i in saved_brand if first is None or i < first]
    if stale:
        warn(f"{name}: saved breakdown branding on {len(stale)} of "
             f"{len(saved_brand)} branded row(s) is NOT current-confirmed "
             f"under the 2026-08-05 semantics -- stale brand, plotting "
             f"normally with no X mark")
    unbranded = sorted(set(flags) - set(saved_brand))
    if unbranded:
        warn(f"{name}: current-confirmed breakdown detected at row(s) "
             f"{unbranded} with no saved branding -- unreviewed")

    base_areas = [r['area_mm2'] for r in rows
                  if r['phase'] == 'baseline' and r['area_mm2']]
    a0 = _median(base_areas) if base_areas else None
    cadence_s, cadence_src = run_cadence(rundir, rows)
    stamp = se.load_stamp(rundir)
    return {'dir': rundir, 'name': name, 'rows': rows, 'a0': a0,
            # how often this run measured current (`#264`) -- what the
            # breakdown mark's position is actually resolved to
            'cadence_s': cadence_s, 'cadence_src': cadence_src,
            'settings': settings, 'flags': flags, 'advis': advis,
            # the px→mm anchor Edge Review recorded at Save (2026-08-05)
            # — cross-run absolute mm² inherits its provenance
            'anchor': se.load_scale_anchor(rundir),
            # which area estimator wrote the run's 'disc-fit' areas
            # (2026-10-02): the `area_estimator` stamp Edge Review's Save
            # puts in setup.txt; None = no stamp = the ellipse (version 1)
            'estimator': se.saved_area_estimator(rundir),
            # the OpenCV and numpy that wrote the run's machine areas
            # (2026-10-03): the library-version stamps beside it, '' for
            # a run saved before they were recorded
            'lib_versions': {k: str(stamp.get(k) or '')
                             for k in se.STAMP_TEXT_KEYS},
            # the tracker's window limits the run's 'disc-fit' rows were
            # measured under (2026-10-03, owner decision 6): the ink-step
            # search top and the ellipse gate in units of the resting
            # radius, None for a run saved before they were recorded
            'tracker_limits': {k: stamp.get(k)
                               for k in se.TRACKER_LIMIT_KEYS},
            'saved_brand': saved_brand,
            # which clock the elapsed-time axis reads (elapsed_times)
            't_src': t_src}


# How often the run measured CURRENT, above which a breakdown mark's
# position in voltage/time is an interval rather than a point (`#264`).
# 1 s because that is the telemetry logger's slowest guaranteed kV/uA
# period (sldea_profile.TELEMETRY_KV_MIN_PERIOD_S): at or under it the
# detector saw the event as it happened, above it the onset can be
# anywhere in the gap before the flagged snapshot.
CADENCE_COARSE_S = 1.0


def run_cadence(rundir, rows):
    """-> (seconds between current samples, where that came from).

    telemetry.csv beside data.csv means the ~2 Hz monitor log ran, so the
    current was sampled continuously; its presence is the answer and the
    file is not parsed (a truncated or aborted log still means the run was
    monitored). Otherwise the only current the run has is one reading per
    snapshot, and the cadence is the MEDIAN gap between snapshot
    timestamps -- median, not mean, because ramp settling makes the
    distribution lumpy (the P3 corpus runs 7 s to 57 s with a 32.5 s
    median).

    (None, 'unknown') when fewer than two timestamps parse: that is 'no
    answer', and no caller may read it as 'fine'."""
    tel = os.path.join(rundir, sprof.TELEMETRY_FILENAME)
    if os.path.exists(tel):
        return (1.0 / sprof.TELEMETRY_MAX_HZ, sprof.TELEMETRY_FILENAME)
    stamps = []
    for r in rows:
        text = r.get('timestamp') or ''
        try:
            stamps.append(datetime.datetime.fromisoformat(text))
        except (TypeError, ValueError):
            continue
    gaps = [(b - a).total_seconds()
            for a, b in zip(stamps, stamps[1:])
            if (b - a).total_seconds() > 0]
    if not gaps:
        return (None, 'unknown')
    return (_median(gaps), 'snapshot spacing')


def coarse_cadence(run, opts):
    """True when the guard is on AND this run sampled current more slowly
    than CADENCE_COARSE_S. An unknown cadence is NOT coarse: the guard
    annotates what it can measure and stays quiet about what it cannot."""
    if not opts.get('cadence_guard'):
        return False
    secs = run.get('cadence_s')
    return secs is not None and secs > CADENCE_COARSE_S


def _cadence_note(run):
    """'<run> every 6.1 s (snapshot spacing)' -- deliberately compact: it
    goes on ONE caption line, and the caption has a figure's width, not a
    console's. The console/window warning wraps this in the full
    sentence."""
    return (f"{run['name']} every {run['cadence_s']:.1f} s "
            f"({run.get('cadence_src', '?')})")


def suspect_old_scale(run):
    """True when the run's areas may carry the pre-2026-07-28 scale bug:
    old timestamps AND a baseline area far off the mask's nominal disc --
    or old timestamps with areas but NO baseline to verify against (fail
    closed: an unverifiable era must not mix in). 155425 is old but
    re-reviewed post-fix; its baseline is exactly pi*(16/2)^2, so it
    passes."""
    dates = [r['timestamp'][:10] for r in run['rows'] if r['timestamp']]
    if not dates or min(dates) >= SCALE_FIX_DATE:
        return False
    if run['a0'] is None:
        return any(r['area_mm2'] is not None for r in run['rows'])
    diam = float(run['settings'].get('diam_mm', 16.0) or 16.0)
    nominal = math.pi * (diam / 2.0) ** 2
    return abs(run['a0'] - nominal) / nominal > 0.05


def old_estimator_areas(run):
    """True when the run holds 'disc-fit' areas written by an OLDER area
    estimator than the current one (2026-10-02, se.AREA_ESTIMATOR_VERSION;
    the run's `area_estimator` stamp in setup.txt says which, and no
    stamp means the ellipse, version 1).

    Until 2026-10-02 a 'disc-fit' area was the fitted ellipse, which read
    -0.4 to +7.4 % against the same run's own A0 (a different offset per
    run); since then it is the common-ray ratio. Edge Review's Save
    keeps the two apart WITHIN a run (an unreviewed old row is emptied),
    and this guard keeps them apart ACROSS runs: without it an old run
    and a reprocessed one overlay on one axis, enter one group mean and
    land in one tidy CSV with nothing marking the boundary (review
    2026-10-02). The same shape as suspect_old_scale, and handled by
    prepare_runs the same way.

    Only 'disc-fit' rows changed meaning: a hand trace is the operator's
    polygon, the patch tiers did not change and a 'resting' row is A0
    under both versions, so a run holding only those passes, as does a
    run whose old rows a Save already emptied (no area, no method)."""
    ver = run.get('estimator')
    if ver is not None and ver >= se.AREA_ESTIMATOR_VERSION:
        return False
    return any(r['method'] == 'disc-fit'
               and (r['area_mm2'] is not None or r['area_px'] is not None)
               for r in run['rows'])


def _estimator_caption(runs):
    """The caption line naming the runs drawn with OLD-estimator areas
    (kept on --allow-old-estimator), or '' when there are none. A figure
    that mixes the two estimators has to say so ON the figure: the PNG
    travels without the command line that made it."""
    names = [r['name'] for r in runs if r.get('old_estimator_kept')]
    if not names:
        return ''
    return (f"\nOLD area method (ellipse, before 2026-10-02; kept on "
            f"--allow-old-estimator): {', '.join(names)}. Not comparable "
            f"with ray-ratio areas (offset -0.4 to +7.4% per run).")


# ---------------------------------------------------------------------------
# per-level aggregation (the pre/post pair collapses to one level entry)
# ---------------------------------------------------------------------------

def levels(run, value=lambda r: r['area_mm2'], by='kv', rows=None):
    """-> sorted [{kv, mean, post, pre, traced, all_traced, mixed,
    traced_post, traced_pre, confirmed}] over rows with a kV and a value.
    Baseline-tagged rows join their kV level like any snapshot (the
    resting tier). `traced` ORs the pair (drives the open marker on
    --prepost snapshots); `all_traced` ANDs it (drives the band width
    and, since 2026-08-05, the mean marker's fill).

    NEVER average across edge conventions (audit 2026-08-05): a
    hand-traced (outer-toe) and a machine (half-height) area differ by a
    documented +5.2-5.7% of DEFINITION, and the blended number belongs
    to neither — the old mean did it on 11 levels of the real batch and
    the caption labeled the result 'outer toe, ±1%'. A `mixed` level's
    mean now uses the machine member(s) only (the campaign's primary
    convention), plots FILLED, and keeps the machine band.

    `by='landing'` (2026-09-23) groups per LANDING instead of per kV, in
    time order, and each entry also carries its 'landing', 'leg' and
    'cycle' (see sweep_legs). That is the grouping an up/down run needs:
    keyed by kV, its rising and falling visits to one level were averaged
    into a single point, and --prepost's post/pre slots were simply
    overwritten by whichever leg came last. On a single sweep every kV
    has exactly one landing, so the two groupings hold the same numbers.
    `rows` restricts the rows considered (default: the whole run)."""
    by_kv = {}
    for r in (run['rows'] if rows is None else rows):
        v = value(r)
        if r['kv'] is None or v is None:
            continue
        if by == 'landing':
            if r.get('landing') is None:
                continue
            k = r['landing']
        else:
            k = round(r['kv'], 3)
        lv = by_kv.setdefault(k, {
            'kv': r['kv'], 'vals': [], 'vals_machine': [],
            'post': None, 'pre': None,
            'traced': False, 'all_traced': True, 'mixed': False,
            'traced_post': False, 'traced_pre': False,
            'confirmed': False})
        if by == 'landing' and 'leg' not in lv:
            lv.update(landing=k, leg=r['leg'], cycle=r['cycle'])
        lv['vals'].append(v)
        if not r['traced']:
            lv['vals_machine'].append(v)
        lv['traced'] = lv['traced'] or r['traced']
        lv['all_traced'] = lv['all_traced'] and r['traced']
        lv['confirmed'] = lv['confirmed'] or r['index'] in run['flags']
        if r['phase'] == 'post':
            lv['post'] = v
            lv['traced_post'] = r['traced']
        elif r['phase'] == 'pre':
            lv['pre'] = v
            lv['traced_pre'] = r['traced']
    out = []
    for k in sorted(by_kv):
        lv = by_kv[k]
        lv['mixed'] = lv['traced'] and not lv['all_traced']
        use = lv['vals_machine'] if lv['mixed'] else lv['vals']
        lv['mean'] = sum(use) / len(use)
        out.append(lv)
    return out


# ---------------------------------------------------------------------------
# the cross-run aggregate (`#268`)
#
# ONE mean curve across the selected runs, with a band -- and the band means
# a different thing at each n, which is the whole point of the feature
# (policy decided 2026-08-09, SLDEA_HANDOFF.md; measured on the five
# poolable P3-family runs):
#
#   n = 1 run   NO BAND, and the figure SAYS so. A refusal rather than a
#               silent fallback to the budget band, because "the mean of
#               one run +-2%" is a claim about the instrument dressed up
#               as a claim about the family.
#   n >= 2      the STANDARD ERROR OF THE MEAN, sigma/sqrt(n), per level.
#               The line drawn is the mean, so the band belongs to the
#               mean. Per-level spread across those five runs is SD median
#               4.94% / max 16.29%, SEM median 2.21% / max 7.28%; the SEM
#               exceeds the +-2% end of the calibrated budget at 23 of 40
#               levels, 22 above 4 kV and one exactly AT it -- above that
#               the instrument is no longer the limit and a budget band
#               would overstate confidence by ~3.5x.
#
#               Two corrections to the numbers the policy entry quotes,
#               both re-measured through these functions on 2026-08-10 and
#               neither changing the decision. The entry's MAXIMA (SD
#               15.63% at 7.5 kV, SEM 6.99%) predate the 2026-08-05
#               "never average across edge conventions" rule in levels():
#               with a mixed level's mean taken over the machine member(s)
#               only, 5.5 kV overtakes 7.5 kV and the maxima become the
#               ones above. The medians and the count of 23 are identical
#               either way. And "every one of them above 4 kV" is off by
#               one boundary level under BOTH rules.
#
# The calibrated +-1-2% budget band belongs to ONE run's pre/post average
# and is suppressed under the aggregate, exactly as --prepost suppresses it
# (draw_area's `budget_bands`).
#
# THE GRID. Eight corpus runs step 0.25 kV; one steps 0.2 and shares only
# eight levels with them. Pooling exact keys alone drops that run at 33 of
# 41 levels, so n alternates 4/5 level to level and the band steps
# discontinuously for a reason that is an artifact of grid choice and not
# of the devices. So runs are put on a common grid by INTERPOLATION by
# default, with exact-key pooling behind `aggregate_exact` for anyone who
# wants only real readings. Three guardrails make interpolation honest, and
# an implementation without them does not satisfy the decision:
#
#   1. NEVER EXTRAPOLATE past a run's own measured range. A run that stops
#      at 6 kV leaves the aggregate above 6 kV; it is not extended into it.
#      `_contribution` only ever interpolates STRICTLY BETWEEN two of the
#      run's own consecutive levels, so there is no code path that can.
#   2. NEVER INTERPOLATE ACROSS A BREAKDOWN. The curve is not smooth there
#      -- a device that collapses between two levels did not travel down
#      the straight line joining them. `_contribution` refuses any segment
#      with a current-confirmed level at either end.
#   3. RECORD MEASURED vs INTERPOLATED per level, and surface it. A level
#      carried by one measured run and four interpolated ones is not the
#      same evidence as five measured ones, and with a uniform n nothing
#      else on the figure would tell them apart. Hence `n_measured` /
#      `n_interpolated` -- stated as ONE n in the caption, and printed per
#      level only on the levels that fall short of it (`#312`; see
#      `aggregate_thin_levels`).
#
# Guardrail 2 is NOT made redundant by the first-breakdown cap below, which
# is the easy thing to assume: the cap drops grid levels at or above the
# first breakdown, but a level just BELOW it can still be reached by
# interpolating a segment whose UPPER end is the collapsed reading. That is
# exactly the case the corpus's 0.2 kV run creates against the 0.25 kV
# runs, and it is the case the test suite pins.
# ---------------------------------------------------------------------------

# The aggregate is not a run, so it does not take a run colour. Black sits
# outside the Tol bright family entirely -- the one curve on the figure
# that is a statistic rather than a measurement should not look like one
# more run.
AGGREGATE_COLOR = '#000000'

# ...and neither is a GROUP mean (`#313`), so the group palette starts at
# the same black: one group draws the figure the ungrouped aggregate
# already drew.
#
# Paul Tol HIGH-CONTRAST first, not bright: bright is the run palette,
# and the whole point is that these curves are statistics. `#313` chose
# the four and their order by worst-case CIEDE2000 under normal +
# deuteranopic + protanopic + tritanopic simulation (Machado 2009
# severity-1.0 matrices) against every TOL_BRIGHT entry. Its numbers,
# kept as recorded (they turned out to be the gamma-encoded variant, see
# THE STANDARD below):
#
#     groups   nearest OTHER GROUP     nearest RUN colour
#     2        29.23                    8.24  (#BB5566 vs #AA3377, tritan)
#     3        22.05                    3.98  (#004488 vs #AA3377, protan)
#     4        18.70                    2.22  (#DDAA33 vs #CCBB44, deutan)
#
# THE STANDARD (owner, 2026-10-06): the Machado matrices are applied to
# LINEAR RGB, after decoding sRGB, as tests/test_sldea_preview.py does.
# Source: the model builds its matrix by integrating the RGB primaries'
# spectral power distributions against the opponent-channel basis
# functions (Machado, Oliveira & Fernandes, IEEE TVCG 15(6):1291-1298,
# 2009, sec. 4.1, Eq. 8), which is linear in light, not in encoded
# values; and the reference implementations do exactly that:
# colorspacious, conversion.py, _CVD_forward, on the graph edge
# "sRGB1-linear+CVD" <-> "sRGB1-linear"; DaltonLens-Python, simulate.py,
# Simulator.simulate_cvd, which calls convert.linearRGB_from_sRGB before
# Simulator_Machado2009._simulate_cvd_linear_rgb. The `#313` script
# applied them to gamma-encoded sRGB, which reproduces its table above to
# the last digit and reads up to ~19 % differently per pair.
#
# GROWN TO SEVEN by `#373` (2026-10-06): the concentration split draws six
# means for one campaign (P3 at three volumes, Invisicon 3900 and 3500,
# carbon black), and four colors made two of them share one. The first
# four are untouched, in the same order, so every figure of four groups or
# fewer keeps its colors. The three added are the best extension a search
# found over Tol's other qualitative schemes (muted, vibrant, medium-
# contrast), held to two hard limits: no TOL_BRIGHT color (a statistic
# must not wear a run color), and at least 3:1 luminance contrast on the
# white panel (WCAG 2.1 SC 1.4.11's floor for graphical objects; a 2.2 pt
# line has to be seen before it can be told apart). #6699CC is Tol
# medium-contrast; #117733 and #882255 are Tol muted.
#
# MEASURED 2026-10-06 with the repo's own simulator
# (tests/test_sldea_preview.py: Machado applied in LINEAR RGB), worst pair
# over the first N colors, and the same in brackets with the matrices
# applied to gamma-encoded sRGB, which is the variant that reproduces the
# `#313` table above to the last digit:
#
#     N   floor           worst pair
#     2   31.54 (29.23)   #000000 / #BB5566   protan
#     3   26.02 (22.05)   #BB5566 / #004488   protan
#     4   21.22 (18.70)   #BB5566 / #DDAA33   tritan
#     5   21.22 (18.70)   (#6699CC is >= 21.22 from all four)
#     6   11.61 (12.44)   #BB5566 / #117733   deutan
#     7   11.36 ( 9.56)   #004488 / #882255   protan
#
# For scale: TOL_BRIGHT's own worst pair over all seven is 8.62 (#4477AA /
# #228833, tritan, linear), so seven group colors are still further
# apart than the run palette's members are. And past four groups color is
# no longer the cue that separates materials: assign_group_styles gives
# each material its own LINE STYLE, so the pairs that sit near 11 are, on
# a seeded figure, also two different dash patterns. Nearest run color
# for the three added (linear): #6699CC 11.78, #882255 8.39, #117733 5.77
# (vs #228833, tritan). The GROUP-VS-RUN point below stands unchanged.
#
# GROUP-VS-RUN cannot be solved by hue at all, and that is a finding
# rather than a compromise: TOL_BRIGHT already spans the wheel, so an
# exhaustive search over Tol's other qualitative schemes could not get a
# four-colour set past 10.67 even allowing olive/grey/brown. So the
# separation from the runs is carried by SHAPE -- square markers, 2.2 pt
# line, a line style per group -- and by --aggregate-only, which is the
# state this figure is normally read in and removes the question. The
# order above simply puts the two colours that do collide as far down the
# list as possible: at two groups (the campaign's CB-vs-P3 case) nothing
# is nearer a run colour than 8.24.
GROUP_COLORS = ('#000000', '#BB5566', '#004488', '#DDAA33',
                '#6699CC', '#117733', '#882255')

# The other half of the separation, and the half that survives greyscale
# printing and a palette wrap (`#373`): a line style per MATERIAL. Every
# group whose runs share one recorded electrode material draws its mean in
# that material's style, so the concentration subgroups of one material
# share a style and differ by color, while different materials differ by
# style, and on a material-only figure by color as well. A group with
# no single material takes a style of its own (assign_group_styles).
#
# The first four are matplotlib's named styles, exactly as before, so a
# figure of four hand-made groups draws what it always drew. The two added
# are dash tuples, in units of the line width like the named ones:
# dash-dot-dot (the owner's example) and a long dash, which the eye
# separates from '--' by length at 2.2 pt (17.6 pt on against 8.1 pt).
# Six rather than more: past six, dash patterns stop being something a
# reader tells apart at a glance, and color carries the rest.
GROUP_STYLES = ('-', '--', '-.', ':',
                (0, (6.4, 1.6, 1.0, 1.6, 1.0, 1.6)),
                (0, (8.0, 3.0)))
GROUP_STYLE_NAMES = ('solid', 'dashed', 'dash-dot', 'dotted',
                     'dash-dot-dot', 'long dash')

# The aggregate's mean line width. Named because the legend handle has to
# draw at the same width: matplotlib scales a dash pattern by the line
# width, so a handle at the default 1.5 pt shows a different pattern than
# the curve it stands for.
AGGREGATE_LW = 2.2

# How long the legend handles are on a GROUPED figure, in units of the
# legend's font size (8 pt). The default 2.0 is 16 pt, and the longest
# pattern above repeats every 13.2 x 2.2 = 29.0 pt (dash-dot-dot; the long
# dash is 24.2), so a default handle showed a dash and a gap and could not
# tell dash-dot from dash-dot-dot. 5.5 em = 44 pt holds one whole period
# of every style plus the first dash of the next (43.1 pt at worst, the
# dash-dot-dot). An ungrouped figure keeps the default, so it lays out as
# it always did.
GROUP_HANDLE_EM = 5.5

# A group name has to fit a legend entry beside 'mean of N runs (±SEM)'.
# 64 since `#373` (was 40): the seeded names are the recorded material,
# and 'Carbon Solutions P3-SWNT, (no concentration recorded)' is 55.
GROUP_NAME_MAX = 64

# The seeded group names for runs with no material (`#373`). Kept apart
# because they mean different things (`#268`, 2026-08-12): an absent line
# predates the field, a recorded '(not specified)' declined to answer.
NO_ELECTRODE_GROUP = '(no electrode recorded)'
NOT_SPECIFIED = '(not specified)'
NO_CONCENTRATION = '(no concentration recorded)'

# The two ways the window can seed groups from setup.txt (`#373`).
SEED_MODES = ('material', 'concentration')


def material_key(text):
    """The identity two recorded electrode strings are COMPARED on:
    case-insensitive, whitespace collapsed (`#373`). 'Carbon Solutions
    P3-SWNT' and 'carbon  solutions p3-swnt' are one material; 'Invisicon
    3900' and 'nano-c Invisicon 3900' are not. Merging spellings is the
    operator's call, made by moving runs between groups (`#374`)."""
    return ' '.join(str(text or '').split()).casefold()


def is_material(text):
    """Does this recorded electrode NAME a material? Not when the line is
    absent (None), blank, or '(not specified)'."""
    return (text is not None
            and material_key(text) not in ('', material_key(NOT_SPECIFIED)))


_ML_RE = re.compile(r'([0-9]*\.?[0-9]+)\s*(?:ml)?', re.IGNORECASE)


def concentration_label(text):
    """A recorded `Ink concentration:` value -> (sort key, group label).

    '2.5 mL', '2.5mL', '2.50 mL' and a bare '2.5' are one value and label
    as '2.5 mL'. The runner writes '<value> mL', so a bare number is the
    same field with the unit dropped. Anything else that is not a number
    in mL keeps its recorded text (whitespace collapsed) and compares
    case-insensitively, so free text is never guessed into a number.
    '(not specified)' sorts after every value, as its own group, and a
    blank value counts as '(not specified)', as a blank electrode does
    (is_material); labelled '' it named a group '<material>, '."""
    t = ' '.join(str(text or '').split())
    m = _ML_RE.fullmatch(t)
    if m:
        value = float(m.group(1))
        return (0, value, ''), f"{value:g} mL"
    if not t or material_key(t) == material_key(NOT_SPECIFIED):
        return (2, 0.0, ''), NOT_SPECIFIED
    return (1, 0.0, t.casefold()), t


def _fit_name(text, limit=GROUP_NAME_MAX):
    """`text` cut to fit a group name, with an ellipsis."""
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _spelling(counts):
    """Which recorded spelling names a material, from {spelling: runs}:
    the one most of its runs used; on a tie the app's own dropdown
    spelling (sldea_profile.ELECTRODE_CHOICES), then the first in sorted
    order. Never the accident of which run happened to be listed first,
    so the same runs always give the same name."""
    choices = set(sprof.ELECTRODE_CHOICES)
    return max(sorted(counts), key=lambda s: (counts[s], s in choices))


def seed_groups(rundirs, by='material'):
    """Groups for `rundirs` from what each run recorded in setup.txt
    (`#373`) -> [(group name, material or None, [rundir, ...])], sorted.

    A SEED, not a mode: the window turns this into ordinary groups the
    operator can edit, and the figspec stores those verbatim, so a later
    setup.txt edit cannot repaint an exported figure.

    by='material': one group per `Compliant electrode:` value, compared
    with material_key and named as recorded (_spelling picks which
    spelling when runs differ). by='concentration': each material splits
    further, one group per `Ink concentration:` value
    (concentration_label), named '<material>, 2.5 mL'. A material the
    runner omits that line for
    by design (sldea_profile.concentration_applies: carbon black, eGaIn,
    the sprayed Invisicon inks) stays one group; a material it applies to
    whose run has no line becomes '<material>, (no concentration
    recorded)'.

    Runs with no material are KEPT, in two separate groups and never
    split by concentration: NO_ELECTRODE_GROUP when the line is absent,
    NOT_SPECIFIED when the operator declined (a blank value counts as
    declining). Their 'material' is None, so their means take a line
    style of their own.

    Sorted by material (case-insensitive), then NOT_SPECIFIED, then
    NO_ELECTRODE_GROUP; within a material by concentration value, then
    free text, then '(not specified)', then the missing line. The order
    picks the colors, so it is fixed rather than left to the selection."""
    if by not in SEED_MODES:
        raise ValueError(f"seed_groups: by must be one of {SEED_MODES}")
    spelled = {}           # material key -> {recorded spelling: runs}
    found = {}             # group key -> [sort key, mat key, suffix, dirs]
    for d in rundirs:
        recorded = se.electrode_of(d)
        if recorded is None:
            gkey, sort, mkey, suffix = ('-',), (2,), None, NO_ELECTRODE_GROUP
        elif not is_material(recorded):
            gkey, sort, mkey, suffix = ('?',), (1,), None, NOT_SPECIFIED
        else:
            mkey = material_key(recorded)
            counts = spelled.setdefault(mkey, {})
            counts[recorded.strip()] = counts.get(recorded.strip(), 0) + 1
            gkey, sort, suffix = (mkey,), (0, mkey), None
            # asked of the COLLAPSED spelling, so two spellings of one
            # material cannot get two answers ('carbon  black' would miss
            # the 'carbon black' needle and split where the other did not)
            if by == 'concentration' and sprof.concentration_applies(
                    ' '.join(recorded.split())):
                conc = se.ink_concentration_of(d)
                if conc is None:
                    csort, clabel = (3, 0.0, ''), NO_CONCENTRATION
                else:
                    csort, clabel = concentration_label(conc)
                # free text can be any length; the tail never takes more
                # room than the longest fixed one, so a material name
                # always keeps 35 characters of the 64
                gkey, sort, suffix = ((mkey, clabel.casefold()),
                                      (0, mkey) + csort,
                                      _fit_name(clabel,
                                                len(NO_CONCENTRATION)))
        found.setdefault(gkey, [sort, mkey, suffix, []])[3].append(d)
    ordered = sorted(found.values(), key=lambda v: v[0])
    # ONE display form per material, cut to leave room for its longest
    # ', <concentration>' tail, so every subgroup of a long material reads
    # the same before the comma. Two materials cut to one prefix are
    # numbered rather than merged, and neither may take the name of a
    # no-material group.
    spelled = {mkey: _spelling(counts) for mkey, counts in spelled.items()}
    longest = {}
    for _sort, mkey, suffix, _dirs in ordered:
        if mkey is not None:
            tail = 0 if suffix is None else len(suffix) + 2
            longest[mkey] = max(longest.get(mkey, 0), tail)
    shown, used = {}, {NO_ELECTRODE_GROUP.casefold(), NOT_SPECIFIED.casefold()}
    for mkey in sorted(longest):
        n = 1
        while True:
            mark = '' if n == 1 else f" #{n}"
            disp = _fit_name(spelled[mkey], GROUP_NAME_MAX - longest[mkey]
                             - len(mark)) + mark
            if disp.casefold() not in used:
                break
            n += 1
        used.add(disp.casefold())
        shown[mkey] = disp
    out, taken = [], set()
    for _sort, mkey, suffix, dirs in ordered:
        if mkey is None:
            name, material = suffix, None
        else:
            material = spelled[mkey]
            name = shown[mkey] + ('' if suffix is None else f", {suffix}")
        # last resort: a material whose own name contains ', 2.5 mL' can
        # still meet another's subgroup; number it rather than merge them
        base, n = name, 2
        while name.casefold() in taken:
            sfx = f" #{n}"
            name = _fit_name(base, GROUP_NAME_MAX - len(sfx)) + sfx
            n += 1
        taken.add(name.casefold())
        out.append((name, material, list(dirs)))
    return out


def shared_material(rundirs):
    """The one material every run in `rundirs` recorded -> its spelling
    (chosen as seed_groups chooses it, _spelling), or None (`#373`).

    None as soon as a run records no material (absent, blank or
    '(not specified)') or a different one, and for an empty list: a group
    with no single material takes a line style of its own rather than
    borrowing one it cannot claim."""
    key, counts = None, {}
    for d in rundirs:
        recorded = se.electrode_of(d)
        if not is_material(recorded):
            return None
        k = material_key(recorded)
        if key is None:
            key = k
        elif k != key:
            return None
        counts[recorded.strip()] = counts.get(recorded.strip(), 0) + 1
    return _spelling(counts) if counts else None


def group_key(path):
    """The identity a group entry is MATCHED on: absolute and normcase'd,
    because Windows paths differ in case without differing.

    Comparison only -- what check_groups STORES is the path as the
    operator spelled it, merely made absolute. Storing the normcased form
    was the first draft and it is wrong twice over: on Windows every
    group in the figspec and in the warnings comes out lowercased, so
    'this group names P3_1_2.5mL_20260728' is reported as
    'p3_1_2.5ml_20260728', and the figspec -- which exists to be read by
    a human six months later -- stops matching the run folder's real
    name. Normalising at the comparison instead costs one normcase per
    lookup and keeps the file honest.

    Never raises: a group entry is a string out of a config file or a
    command line, and a path that cannot be resolved simply matches
    nothing rather than taking the figure down."""
    try:
        return os.path.normcase(os.path.abspath(path))
    except (OSError, ValueError):
        return os.path.normcase(str(path))


def check_groups(value):
    """-> (the canonical groups value, None) or (None, the CLI's error).

    Its own checker for the same reason check_dpi is: make_opts and the
    window's remembered-options cleaner must give a malformed value the
    identical answer, so a hand-edited config cannot smuggle past what
    the window itself would refuse.

    THE CANONICAL FORM is [[name, [run key, ...]], ...] -- LISTS, not the
    tuples every other structured value in this file uses, and that is
    the one place `#313` bent the house style on purpose. `groups` lives
    in opts, opts is what build_figspec stores verbatim, and the figspec
    is JSON: with tuples the value written to disk and the value in
    memory compare UNEQUAL after a round trip, which is exactly the
    'a re-render that is not' failure the spec exists to catch and would
    have turned every spec test into a special case. JSON has no tuples,
    so the canonical form does not either.

    IN THE OPERATOR'S ORDER, never sorted: that order picks the colours
    (assign_group_styles), so sorting here would quietly repaint a figure on
    reload.

    Empty groups are DROPPED, not refused: the window can hold a name
    with nothing in it while the operator is mid-edit, and an empty group
    draws nothing either way. Everything else is refused, because a
    duplicate name or a run in two groups has no defensible reading."""
    if value is None:
        return [], None
    if isinstance(value, (str, bytes)) or not hasattr(value, '__iter__'):
        return None, ('--group needs NAME=RUN[,RUN...] '
                      '(got a bare value)')
    out, seen_names, seen_runs = [], {}, {}
    for entry in value:
        if (isinstance(entry, (str, bytes))
                or not hasattr(entry, '__iter__')):
            return None, f"group entry {entry!r} is not a NAME=RUNS pair"
        pair = list(entry)
        if len(pair) != 2:
            return None, (f"group entry {entry!r} must be exactly "
                          f"(name, runs)")
        name, members = pair
        if not isinstance(name, str) or not name.strip():
            return None, f"group name {name!r} is empty"
        name = name.strip()
        if len(name) > GROUP_NAME_MAX:
            return None, (f"group name {name!r} is longer than "
                          f"{GROUP_NAME_MAX} characters")
        low = name.casefold()
        if low in seen_names:
            return None, (f"two groups are both named "
                          f"{seen_names[low]!r} -- names label the "
                          f"curves and must differ")
        seen_names[low] = name
        if isinstance(members, (str, bytes)) or not hasattr(members,
                                                            '__iter__'):
            return None, f"group {name!r} has no list of runs"
        keys, seen_here = [], set()
        for m in members:
            if not isinstance(m, str) or not m.strip():
                return None, f"group {name!r} names an empty run"
            stored = os.path.abspath(m.strip())
            key = group_key(stored)
            if key in seen_runs and seen_runs[key] != name:
                return None, (f"{os.path.basename(m.strip())} is in both "
                              f"{seen_runs[key]!r} and {name!r} -- a run "
                              f"belongs to at most one group")
            seen_runs[key] = name
            if key not in seen_here:
                seen_here.add(key)
                keys.append(stored)
        if keys:
            out.append([name, keys])
    return out, None


def check_group_materials(value):
    """-> (the canonical group_materials value, None) or (None, an error).

    `group_materials` (`#373`) records, per group, the ONE electrode
    material its runs shared when the group was formed: [[group name,
    material as recorded], ...]. Only groups that had one appear; a group
    with no single material is simply absent. It is what picks a group's
    LINE STYLE (assign_group_styles), and it lives in opts (and so in
    the figspec, verbatim) for the reason the grouping itself does: the
    style of an exported figure must not move because somebody edited a
    setup.txt afterwards. Nothing at draw time reads setup.txt.

    Lists, not tuples, and in the order given, for check_groups' JSON
    reason. The SHAPE is checked here; make_opts then keeps only the
    entries that name a group that exists, in the groups' order, so a
    stale entry is inert the way a stale group is."""
    if value is None:
        return [], None
    if isinstance(value, (str, bytes)) or not hasattr(value, '__iter__'):
        return None, ('group materials must be a list of '
                      '(group, material) pairs')
    out, seen = [], set()
    for entry in value:
        if (isinstance(entry, (str, bytes))
                or not hasattr(entry, '__iter__')):
            return None, (f"group material entry {entry!r} is not a "
                          f"(group, material) pair")
        pair = list(entry)
        if len(pair) != 2 or not all(isinstance(p, str) and p.strip()
                                     for p in pair):
            return None, (f"group material entry {entry!r} must be two "
                          f"non-empty strings")
        name, material = pair[0].strip(), pair[1].strip()
        if name.casefold() in seen:
            return None, (f"group {name!r} is given two materials")
        seen.add(name.casefold())
        out.append([name, material])
    return out, None


def check_film_thickness(value):
    """-> (the canonical film_thickness value, None) or (None, an error).

    `film_thickness` (`#398`) records, per run, the film thickness t0 in
    um that a FIELD-axis figure divided its voltages by: [[run directory,
    t0], ...]. Like group_materials it is DERIVED, never typed: export
    writes it from the runs it drew, and on the next render prepare_runs
    takes a run's t0 from here before it looks at setup.txt, so
    --from-spec redraws the same field axis after a setup.txt edit. A run
    it does not name is read from setup.txt as usual.

    Lists, not tuples, for check_groups' JSON reason, in the order given.
    Each t0 must be a positive finite number (a bool is not one). A run
    named twice, or an entry of any other shape, is refused rather than
    repaired: a spec is a file a human can edit."""
    if value is None:
        return [], None
    if isinstance(value, (str, bytes)) or not hasattr(value, '__iter__'):
        return None, ('film thickness must be a list of (run directory, '
                      'thickness in um) pairs')
    out, seen = [], set()
    for entry in value:
        if (isinstance(entry, (str, bytes))
                or not hasattr(entry, '__iter__')):
            return None, (f"film thickness entry {entry!r} is not a (run "
                          f"directory, thickness in um) pair")
        pair = list(entry)
        if (len(pair) != 2 or not isinstance(pair[0], str)
                or not pair[0].strip()):
            return None, (f"film thickness entry {entry!r} must be a run "
                          f"directory and a thickness in um")
        t0 = pair[1]
        if (isinstance(t0, bool) or not isinstance(t0, (int, float))
                or not math.isfinite(t0) or t0 <= 0):
            return None, (f"film thickness entry {entry!r}: the thickness "
                          f"must be a positive number of um")
        path = os.path.abspath(pair[0].strip())
        key = group_key(path)
        if key in seen:
            return None, (f"{os.path.basename(path)} is given two film "
                          f"thicknesses")
        seen.add(key)
        out.append([path, float(t0)])
    return out, None


def film_thickness_record(runs):
    """-> the film_thickness value for a figure drawn from `runs`
    (`#398`): [[run directory, t0], ...] in drawing order, for every run
    that carries a t0. What export stores in a field-axis figure's
    figspec, so it names exactly the runs on the figure."""
    return [[os.path.abspath(r['dir']), float(r['t0_um'])]
            for r in runs if r.get('t0_um')]


def derive_group_materials(groups, runs=()):
    """For a grouping made on the COMMAND LINE: -> group_materials, from
    what each group's runs recorded in setup.txt (`#373`).

    The window does the same thing at the moment a group is formed
    (sldea_plot_gui.PlotWindow.assign_group); a --group invocation is
    that moment for the CLI, so both front ends give one grouping one
    set of line styles. A member that is not a directory is matched to a
    plotted run by folder name, the way run_group matches it; a member
    that resolves to nothing is left out rather than read as a material."""
    by_name = {os.path.normcase(r.get('name') or ''): r['dir']
               for r in runs if r.get('dir')}
    out = []
    for name, members in (groups or ()):
        dirs = []
        for m in members:
            if os.path.isdir(m):
                dirs.append(m)
                continue
            d = by_name.get(os.path.normcase(os.path.basename(m)))
            if d:
                dirs.append(d)
        material = shared_material(dirs) if dirs else None
        if material:
            out.append([name, material])
    return out


def parse_group_flag(text):
    """'--group NAME=RUN[,RUN...]' -> ((name, [runs]), None) or
    (None, the CLI's error)."""
    if not isinstance(text, str) or '=' not in text:
        return None, (f"--group {text!r} needs the form "
                      f"NAME=RUN[,RUN...]")
    name, _, rest = text.partition('=')
    members = [m.strip() for m in rest.split(',') if m.strip()]
    if not name.strip():
        return None, f"--group {text!r} has no group name"
    if not members:
        return None, f"--group {text!r} names no runs"
    return (name.strip(), members), None


def run_group(run, groups):
    """Which group `run` belongs to, or None.

    Matched on the resolved directory first, and only then on the bare
    folder name -- `#323` put runs from several parents on one figure and
    two of them can share a name, so the path is the identity and the
    name is the convenience the command line needs."""
    if not groups:
        return None
    key = group_key(run.get('dir') or '')
    for name, members in groups:
        if any(group_key(m) == key for m in members):
            return name
    base = os.path.normcase(run.get('name') or '')
    if not base:
        return None
    for name, members in groups:
        if any(os.path.normcase(os.path.basename(m)) == base
               for m in members):
            return name
    return None


def group_sets(runs, groups):
    """-> [(group name, [its runs])] in the operator's group order, for
    the groups that actually have a run on this figure, plus the runs
    that landed in no group at all as a second return value.

    Empty of groups -> ([], runs): every caller then falls back to the
    single whole-selection aggregate, which is what `#268` shipped and
    what a figure with no groups must keep drawing."""
    if not groups:
        return [], list(runs)
    members = {name: [] for name, _ in groups}
    loose = []
    for run in runs:
        name = run_group(run, groups)
        if name is None:
            loose.append(run)
        else:
            members[name].append(run)
    return ([(name, members[name]) for name, _ in groups
             if members[name]], loose)


def assign_group_styles(keys):
    """-> ([(color, linestyle)] one per group, [notes]) for the groups
    drawn, in drawing order, given each one's material KEY (material_key)
    or None for a group with no single material (`#373`).

    THE RULES, in the owner's words turned into code:

      * every group of one material draws that material's line style, so
        the concentration subgroups of one material share a style and
        differ by color, and different materials differ by style;
      * a group with no single material (hand-made and mixed, or no
        electrode recorded) takes a style no other group on the figure
        has: it is not any material, so it must not look like one;
      * styles are handed out in drawing order, one per new material or
        material-less group; colors go one per group, the i'th group
        the i'th color. So a material-only figure separates materials by
        color AND style, and up to len(GROUP_COLORS) groups never share
        a color at all;
      * THE INVARIANT: no two groups on one figure share both color and
        style. Past the palette a color comes round again, and it is
        moved on to the next color that is still free on that style; if
        a material has more groups than there are colors, the extra
        ones step to the next free style, and a note says so.

    Deterministic in its input: the same keys in the same order give the
    same pairs, and both come from the figspec (groups, group_materials),
    so a re-render cannot restyle a figure. With no materials at all every
    group is its own style, and the first four come out (black solid, red
    dashed, blue dash-dot, yellow dotted): the `#313` figure, unchanged.
    One group is the black solid curve the ungrouped aggregate draws.

    `notes` are sentences for the console, empty on an ordinary figure."""
    nc, ns = len(GROUP_COLORS), len(GROUP_STYLES)
    slot_of, next_slot = {}, 0
    pairs, used, notes = [], set(), []
    stepped = []
    for i, key in enumerate(keys):
        if key is not None and key in slot_of:
            slot = slot_of[key]
        else:
            slot = next_slot
            next_slot += 1
            if key is not None:
                slot_of[key] = slot
        want = slot % ns
        pick = None
        for s in [want] + [(want + t) % ns for t in range(1, ns)]:
            for c in [(i + t) % nc for t in range(nc)]:
                if (c, s) not in used:
                    pick = (c, s)
                    break
            if pick is not None:
                break
        if pick is None:                  # more groups than pairs exist
            pick = (i % nc, want)
        elif pick[1] != want:
            stepped.append(i)
        used.add(pick)
        pairs.append((GROUP_COLORS[pick[0]], GROUP_STYLES[pick[1]]))
    n = len(keys)
    if n > nc:
        notes.append(f"{n} groups > {nc} group colors: a color comes "
                     f"round again, never on a line style it already has, "
                     f"so no two means look alike; the legend names each")
    if next_slot > ns:
        notes.append(f"{next_slot} line styles wanted (one per material, "
                     f"one per group with no single material) > {ns}: "
                     f"some materials share a style and differ by color "
                     f"alone")
    if stepped:
        notes.append(f"{len(stepped)} group(s) of a material with more "
                     f"than {nc} groups had to leave that material's line "
                     f"style; consider fewer groups per figure")
    if n > nc * ns:
        notes.append(f"{n} groups > {nc * ns} color/style pairs: some "
                     f"group means now look identical; draw fewer groups")
    return pairs, notes


def group_style(index):
    """-> (color, linestyle) for the index'th of `index + 1` groups with no
    recorded material: the hand-made case, and the whole story before
    `#373`. See assign_group_styles."""
    return assign_group_styles([None] * (index + 1))[0][index]


def group_style_name(ls):
    """'solid', 'dashed', ... for a GROUP_STYLES entry, for the caption."""
    for style, name in zip(GROUP_STYLES, GROUP_STYLE_NAMES):
        if style == ls:
            return name
    return str(ls)


def first_breakdown_kv(run):
    """The nominal kV of this run's FIRST current-confirmed breakdown --
    first in TIME, the earliest flagged row in CSV order -- or None when
    it has none.

    Reads run['flags'], which load_run ALWAYS recomputes from the saved
    current trace -- so this is deliberately independent of opts:
    where a device broke down is not a rendering preference, and
    --no-breakdown hides the X marks without making the collapse go away.

    Until 2026-09-23 this returned the LOWEST flagged kV. On a rising
    single sweep that is the same row, but an up/down run that breaks
    down on the way up keeps confirming on the way down, and the lowest
    flagged kV then named a level the device had passed intact. The
    pooled aggregate still stops at that lowest value, and has to -- see
    lowest_breakdown_kv; this is the cap for an aggregate that averages
    one leg per run."""
    hits = [(r['index'], r['kv']) for r in run['rows']
            if r['index'] in run['flags'] and r['kv'] is not None]
    return min(hits)[1] if hits else None


def lowest_breakdown_kv(run):
    """The LOWEST nominal kV among this run's current-confirmed breakdown
    rows, or None when it has none: the value the aggregate cap has
    always used, and on a rising single sweep the same row as
    first_breakdown_kv.

    run_level_curve pools every visit to a level into one mean, so the
    aggregate has to stop below EVERY flagged frame, not just the first.
    An up/down run that broke at 3.5 kV on the way up and stayed flagged
    down to 2.0 kV averages its collapsed frames into the 2.0-3.0 kV
    means, and capping at the first breakdown drew that mixture into the
    figure (review 2026-09-23)."""
    kvs = [r['kv'] for r in run['rows']
           if r['index'] in run['flags'] and r['kv'] is not None]
    return min(kvs) if kvs else None


def aggregate_cap_kv(runs):
    """Where the aggregate STOPS: the lowest breakdown kV across the runs
    (lowest_breakdown_kv of each), or None when nothing broke down.

    The LOWEST, not each run's own: past the first collapse the mean mixes
    intact and collapsed devices, which is not a physical quantity. On the
    corpus's five poolable runs the mean A/A0 climbs to 2.041 at 5.25 kV
    and then falls to ~1.18-1.27 for the rest of the staircase, and the
    spread spikes to ~15% through the transition before falling again as
    the runs re-agree on having collapsed -- the average of a mixture, not
    an average expansion."""
    # in the figure's x units (`#398`): each run's breakdown kV times its
    # x_scale, which is 1.0 on the kV axis and 1000 / t0 on the field
    # axis, where the lowest breakdown FIELD is what the mean must stop at
    kvs = [k * r.get('x_scale', 1.0)
           for r, k in ((r, lowest_breakdown_kv(r)) for r in runs)
           if k is not None]
    return min(kvs) if kvs else None


def norm_y(area, a0, pct=False):
    """The normalized panel's y for one absolute area.

    A / A0 by default. With `pct`, the SAME quantity as strain percent,
    (A - A0) / A0 * 100 -- which is what the lab quotes and what the
    SCORECARD's headline numbers are in.

    One function because seven drawing sites and the aggregate all did
    `y / run['a0']` inline; a units switch applied to six of the seven
    draws a figure that looks finished and is not.

    The map is AFFINE, so it commutes with the mean and scales the SEM by
    100 -- percent may be applied to each run's value before aggregation
    (which is what happens here) or to the aggregate afterwards, and the
    band is the same either way. That is why the aggregate needed no
    statistics rethink, only the same conversion in the same place."""
    r = area / a0
    return (r - 1.0) * 100.0 if pct else r


def first_rise_rows(run):
    """The rows of the run's FIRST rising leg (its resting 0 kV frames
    included) -- what an up/down run contributes to the aggregate when
    its legs are drawn apart. See run_level_curve."""
    return [r for r in run['rows']
            if r.get('leg') == 'rise' and r.get('cycle') == 1]


def run_level_curve(run, norm=False, pct=False, legs=False):
    """One run as [{key, kv, y, confirmed}], sorted by level.

    `y` is the level's mean area in mm2, or the normalized value when
    `norm` (A/A0, or strain percent when `pct`) -- the two area panels
    aggregate SEPARATELY because normalizing rescales each run by its own
    A0, and a spread in mm2 is not the same spread in A/A0. A run with
    no A0 contributes nothing to the normalized panel rather than being
    silently dropped into the absolute one.

    `legs` (2026-09-23): a run whose voltage also FELL contributes its
    first rising leg only. The aggregate pools one curve per run on a kV
    grid, and averaging a device's rising and falling visits to a level
    is the very blending the leg-split view exists to stop; the first
    rise is the leg every single-sweep run in the pool also has.

    `key` and `kv` are POSITIONS on the figure's x axis (`#398`): the
    level's kV times the run's x_scale, which prepare_runs sets to 1.0
    on the kV axis and to 1000 / t0 on the field axis. So the field
    aggregate pools runs on a grid of fields, and two runs on films of
    different thickness meet on it only by interpolation."""
    if norm and not run.get('a0'):
        return []
    out = []
    rows = first_rise_rows(run) if legs and multi_leg(run) else None
    scale = run.get('x_scale', 1.0)
    for lv in levels(run, rows=rows):
        y = norm_y(lv['mean'], run['a0'], pct) if norm else lv['mean']
        x = lv['kv'] * scale
        out.append({'key': round(x, 3), 'kv': x, 'y': y,
                    'confirmed': lv['confirmed']})
    return out


def _contribution(curve, key, exact=False):
    """One run's value at grid level `key` -> (y, measured?) or None.

    None means THIS RUN DOES NOT SPEAK HERE, and there are three ways to
    earn it -- all three of them guardrails, none of them a fallback:
    the level is outside the run's own measured range (guardrail 1, no
    extrapolation); the segment that would carry it has a current-confirmed
    breakdown at one end (guardrail 2, the curve is not smooth there); or
    `exact` was asked for and the run simply never measured this level."""
    for p in curve:
        if p['key'] == key:
            return (p['y'], True)
    if exact:
        return None
    for a, b in zip(curve, curve[1:]):
        if a['key'] < key < b['key']:
            if a['confirmed'] or b['confirmed']:
                return None                    # guardrail 2
            span = b['key'] - a['key']
            return (a['y'] + (key - a['key']) / span * (b['y'] - a['y']),
                    False)
    return None                                # guardrail 1


def aggregate_levels(runs, norm=False, exact=False, pct=False, legs=False):
    """-> sorted [{kv, n, mean, sd, sem, n_measured, n_interpolated}].

    The cross-run mean and its SEM band, per level, capped at the first
    current-confirmed breakdown. `sd` and `sem` are None wherever fewer
    than two runs contribute -- one value has no spread, and a level
    carried by a single run must not be handed a band borrowed from its
    neighbours.

    SD is the SAMPLE deviation (n-1): these runs are a sample of a family,
    not the family. Note what this function deliberately does NOT do --
    there is no minimum-n threshold beyond that. A thinly supported level
    is SHOWN, with its n, rather than quietly dropped; the corpus might
    argue for a floor later, and that is an argument to have in the open,
    not a constant to slip in here."""
    curves = [c for c in (run_level_curve(r, norm, pct, legs) for r in runs)
              if c]
    cap = aggregate_cap_kv(runs)
    keys = sorted({p['key'] for c in curves for p in c})
    if cap is not None:
        keys = [k for k in keys if k < round(cap, 3)]
    out = []
    for key in keys:
        vals, n_meas = [], 0
        for c in curves:
            hit = _contribution(c, key, exact)
            if hit is None:
                continue
            vals.append(hit[0])
            n_meas += 1 if hit[1] else 0
        if not vals:
            continue
        n = len(vals)
        mean = sum(vals) / n
        sd = sem = None
        if n >= 2:
            sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
            sem = sd / math.sqrt(n)
        out.append({'kv': key, 'n': n, 'mean': mean, 'sd': sd, 'sem': sem,
                    'n_measured': n_meas, 'n_interpolated': n - n_meas})
    return out


def aggregate_support(lv):
    """The per-level support label printed under an aggregate point: 'n',
    or 'a+b' where a were MEASURED at this level and b interpolated onto
    it (guardrail 3). The sum is always n, so the number a reader wants
    first is still readable at a glance."""
    return (str(lv['n']) if not lv['n_interpolated']
            else f"{lv['n_measured']}+{lv['n_interpolated']}")


def aggregate_full_n(ag):
    """The aggregate's headline n: the LARGEST per-level contribution
    count, which is the one the caption quotes. 0 for an empty
    aggregate."""
    return max((l['n'] for l in ag), default=0)


def aggregate_thin_levels(ag):
    """The levels whose MEASURED support falls below `aggregate_full_n`
    -> the only levels that still carry a printed count (`#312`).

    Every level used to print its own count, which put a row of identical
    numbers under the curve and straight through the marker key. The
    counts are not noise, though: guardrail 3 exists because a level
    carried by one measured run and four interpolated ones is not the
    evidence five measured runs are, and under the default interpolated
    grid `n` is uniform, so nothing else on the figure separates them.

    So the caption states the one n and this picks out the exceptions.
    The test is `n_measured < full`, on MEASURED support and not on `n`,
    and that choice is the whole point: comparing `n` alone would leave
    the 1-measured-of-5 level unmarked at exactly full n, which is the
    case the guardrail was written for. Since n_measured <= n <= full, a
    level passes the test iff it has the full complement of runs AND
    every one of them really measured this level -- so the marked set is
    exactly {thin support} u {interpolated support}, and on a clean
    single-grid family it is empty and the figure carries no counts at
    all."""
    full = aggregate_full_n(ag)
    return [l for l in ag if l['n_measured'] < full]


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------

# The caption strip is reserved in FIGURE FRACTIONS, so a resized figure
# keeps its proportions -- but the caption's own text does not scale, and
# neither do the tick labels tight_layout was measuring when it chose
# those fractions. That is the whole reason a resize needs anything from
# us at all; matplotlib's own resize handler has already redrawn the
# figure at the new size by then.
#
# So the rect is REMEMBERED rather than recomputed (`#316`). Re-deriving
# it means rebuilding the figure -- 298 ms of artist construction over 13
# runs, measured -- to arrive at a number that cannot have changed, since
# nothing but the window's shape did.
_RECT_ATTR = '_sldea_layout_rect'


def _tight(fig, rect):
    """fig.tight_layout(rect=...), remembering the rect for relayout."""
    setattr(fig, _RECT_ATTR, rect)
    fig.tight_layout(rect=rect)
    return rect


# ...with ONE exception, the caption (2026-10-06; the grouped caption
# since `#373`). It is wrapped to the figure's width, so a narrower window
# needs it re-wrapped and its strip re-measured, and only that. Held as
# (the caption's Text, the caption as composed, the strip it was composed
# for) so relayout can redo exactly that much; None on a figure draw() did
# not make. A grouped caption is held as a function of the width test
# rather than a string, with no strip of its own: it composes itself for
# the width it finds, and its strip is always measured.
_CAPTION_ATTR = '_sldea_caption'

# The gap kept between a wrapped caption's top and the figure's layout
# rect, in figure height. The x-axis label sits just above the rect.
CAPTION_PAD = 0.012


def _set_caption(fig, cap, bottom):
    """Write `cap` under the panels, wrapped to the figure's width, and lay
    the figure out above it -> the layout rect.

    `cap` is the caption as composed, or, on a grouped figure (`#373`), a
    function of _caption_fitter's width test that composes it. `bottom`
    is the caption strip the caller reserved for `cap` as composed, in
    figure height; _place_caption keeps it when every line fits and grows
    it when one does not. None, the grouped figure's, always measures."""
    text = fig.text(0.01, 0.005, '', fontsize=7, color='#555555')
    setattr(fig, _CAPTION_ATTR, (text, cap, bottom))
    return _tight(fig, (0, _place_caption(fig), 1, 1))


def _place_caption(fig):
    """(Re)write the figure's caption for the figure's CURRENT width and
    -> the layout rect's bottom that clears it.

    A line that fits is written exactly as composed. A caption whose every
    line fits keeps the strip it was composed for, so a figure that never
    ran off the edge lays out to the same pixels as before 2026-10-06.
    One that wraps takes the larger of the per-line allowance the
    multi-line captions already use (0.025 of the figure height a row,
    plus 0.025, capped at 0.30) and its own measured top plus
    CAPTION_PAD, measured because a wrapped caption can have more rows
    than the 0.30 cap allows for, and because in a short window a 7 pt
    row is a larger share of the height than the allowance assumes. A
    grouped one (`#373`) does the same with the allowance NOT capped, as
    that branch laid it out. Capped at 0.85 only so a pathological
    caption leaves the axes something."""
    text, cap, bottom = getattr(fig, _CAPTION_ATTR)
    fits = _caption_fitter(fig)
    if callable(cap):
        cap = cap(fits)
    rows = []
    for line in cap.split('\n'):
        rows += [line] if fits(line) else _wrap(line, fits)
    text.set_text('\n'.join(rows))
    if bottom is None:
        # grouped (`#373`): the per-row allowance is NOT capped. A row
        # takes about 0.022 of a 5.4 in figure, so the allowance keeps a
        # margin over the measured top that grows with the rows, and the
        # strip still clears the axes when it was measured at 300 dpi and
        # is drawn at 90, where hinting makes 7 pt rows about 12 % taller
        bottom = 0.025 + 0.025 * len(rows)
    elif len(rows) == cap.count('\n') + 1:
        return bottom
    else:
        bottom = max(bottom, min(0.025 + 0.025 * len(rows), 0.30))
    try:
        renderer = fig.canvas.get_renderer()
        top = text.get_window_extent(renderer=renderer).y1 / fig.bbox.height
        bottom = max(bottom, top + CAPTION_PAD)
    except (AttributeError, TypeError, ValueError):
        pass                    # no renderer yet: the allowance stands
    return min(bottom, 0.85)


_SUBPLOTPARS = ('left', 'right', 'bottom', 'top', 'wspace', 'hspace')


def relayout(fig):
    """Re-run the last draw's tight_layout at the figure's CURRENT size.

    FROM THE DEFAULT SUBPLOT PARAMS, NOT FROM THE LAST LAYOUT'S. That
    reset looks like a spare line and is not: tight_layout derives wspace
    from the axes width it FINDS, so run on its own output it does not
    land where it lands on a fresh figure. Measured in the plot window
    over the campaign corpus -- area mode's two panels came out 8-12%
    narrower at a 496x347 canvas, and by a different amount on each visit
    to the same size. Resetting first makes this exactly what a rebuild
    would have laid out, which is the only thing that makes it a shortcut
    rather than a second layout engine.

    -> True when there was a layout to re-run, False when this figure was
    never drawn by draw() (or was cleared since), which is the caller's
    signal that it needs a real draw and not a shortcut."""
    from matplotlib import rcParams

    rect = getattr(fig, _RECT_ATTR, None)
    if rect is None or not fig.axes:
        return False
    fig.subplots_adjust(**{k: rcParams['figure.subplot.' + k]
                           for k in _SUBPLOTPARS})
    held = getattr(fig, _CAPTION_ATTR, None)
    if held is not None and held[0] in fig.texts:
        # the one width-dependent thing on a figure, the caption, is
        # re-wrapped for the new width, and its strip with it
        rect = (rect[0], _place_caption(fig), rect[2], rect[3])
        setattr(fig, _RECT_ATTR, rect)
    fig.tight_layout(rect=rect)
    return True


def _style_axes(ax, xlabel, ylabel):
    ax.grid(alpha=0.3)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)


def log_scale_for(values):
    """-> ('log', None) | ('symlog', linthresh) | None, from the DATA.

    The `#263` policy in one function so both figures decide identically.
    None means 'leave this axis linear' -- nothing finite to scale, or an
    all-zero axis, neither of which a log scale can represent. See the
    module docstring for why nonpositive data becomes symlog rather than
    being clipped away."""
    vals = [v for v in values
            if v is not None and isinstance(v, (int, float))
            and math.isfinite(v)]
    if not vals:
        return None
    if all(v > 0 for v in vals):
        return ('log', None)
    nz = [abs(v) for v in vals if v != 0]
    if not nz:
        return None
    # floor to a decade so the linear window is a readable round number
    # and two runs of the same shape get the same axis
    return ('symlog', max(10.0 ** math.floor(math.log10(min(nz))), 1e-12))


def _apply_scales(ax, opts, xs, ys, notes):
    """Apply --logx/--logy to one axis, appending caption lines to `notes`.

    Values come from the CALLER's record of what it plotted, not from
    ax.get_lines(): axhline/axvline store one of their coordinate pairs in
    axes fractions (0..1), and letting those vote would pick a linthresh
    from a gridline rather than from the data."""
    for axis, on, vals, name in (('x', opts.get('logx'), xs, 'X'),
                                 ('y', opts.get('logy'), ys, 'Y')):
        if not on:
            continue
        pick = log_scale_for(vals)
        if pick is None:
            notes.append(f"{name} axis: log requested but the data has "
                         f"nothing a log scale can show -- left linear.")
            continue
        kind, lin = pick
        if kind == 'log':
            ax.set_xscale('log') if axis == 'x' else ax.set_yscale('log')
            notes.append(f"{name} axis: log10.")
        else:
            if axis == 'x':
                ax.set_xscale('symlog', linthresh=lin)
            else:
                ax.set_yscale('symlog', linthresh=lin)
            notes.append(f"{name} axis: symlog -- linear within ±{lin:g}, "
                         f"log outside (the data carries values ≤ 0; a "
                         f"plain log scale would drop them).")


def _panel_title(opts, which, default):
    """The heading for one panel: the panel's own option, else (first
    panel only) the legacy --title, else the built-in default.

    --title predates per-panel titles and has always meant 'the FIRST
    panel', so it keeps meaning that and --title-first is simply its
    precise name -- a script that says --title today keeps its figure.
    Blank is 'no override', never an empty heading (`#269`)."""
    text = (opts.get('title_' + which) or '').strip()
    if not text and which == 'first':
        text = (opts.get('title') or '').strip()
    return text or default


def default_panel_titles(opts, runs=()):
    """The BUILT-IN heading each panel carries when no option overrides
    it. -> {'first': str, 'second': str or None}; 'second' is None in the
    single-panel modes, which have no second panel to head.

    Written here rather than at the set_title calls so that the window can
    SHOW an operator the heading a blank box will produce (`#315`) without
    copying the wording -- a second copy of 'Active area vs voltage' would
    drift the first time one of them was reworded, and the drift would
    read as a correct label.

    The second panel's default names the baseline it normalizes by, so it
    depends on the RUNS and not only on the options -- which is precisely
    why the window may not treat it as a fixed string. `a0` is skipped
    where it is absent rather than indexed: draw_area only ever sees runs
    that have one (prepare_runs drops the others in area mode), but the
    window asks this question between a mode switch and the redraw that
    follows it, when the runs it holds were prepared for the mode before.
    """
    if opts['mode'] != 'area':
        return {'first': ('Power' if opts['mode'] == 'power' else 'Current')
                         + ' -- per snapshot',
                'second': None}
    a0s = sorted({round(r['a0'], 1) for r in runs if r.get('a0')})
    a0txt = f"A₀ = {a0s[0]:g} mm²" if len(a0s) == 1 else "per-run A₀"
    # The heading names the UNITS as well as the baseline: the two curves
    # are the same measurement, and a reader who sees 104 where they expect
    # 1.04 needs the panel itself to say which one this is.
    lead = ('Areal strain from baseline area' if opts.get('strain_pct')
            else 'Normalized to baseline area')
    return {'first': ('Active area vs time' if opts.get('x') == 'time'
                      else 'Active area vs field'
                      if opts.get('x') in FIELD_AXES
                      else 'Active area vs voltage'),
            'second': f"{lead} ({a0txt})"}


def panel_titles(opts, runs=()):
    """What each panel's heading ACTUALLY reads with these options and
    these runs -- the override where there is one, the built-in default
    where there is not. -> {'first': str, 'second': str or None}.

    THE answer to 'what will the figure say', for anything that has to
    agree with the figure without drawing it."""
    defaults = default_panel_titles(opts, runs)
    return {w: (None if defaults[w] is None
                else _panel_title(opts, w, defaults[w]))
            for w in ('first', 'second')}


def _dedupe(items):
    """Order-preserving unique -- the two area panels share an x axis, so
    the same caption line is generated twice."""
    out = []
    for i in items:
        if i not in out:
            out.append(i)
    return out


def _cadence_caption(notes):
    """The cadence-guard caption line, or '' when no run earned one.

    States the SPACING, not just 'coarse': a reader deciding whether an
    X at 6.4 kV means 'at 6.4 kV' needs the number to judge it, and 32 s
    of ramp is a very different claim from 5 s."""
    notes = _dedupe(notes)
    if not notes:
        return ''
    return (f"\nHollow X = confirmed, sampled slower than "
            f"{CADENCE_COARSE_S:g} s (onset lies before the mark).  "
            f"Sampling: " + '; '.join(notes) + '.')


def _time_axis_caption(runs):
    """The caption's x-axis sentence for the elapsed-time axis, naming the
    clock every run was read on (elapsed_times) -- the scheduled time and
    the wall-clock stamp differ by each grab's latency, and a figure that
    travels without its command line has to say which it is."""
    srcs = {r.get('t_src') for r in runs if r.get('t_src')}
    if srcs == {'t_planned_s'}:
        how = "the scheduled t_planned_s, on each run's own clock"
    elif srcs == {'timestamp'}:
        how = "wall-clock timestamps from each run's first snapshot"
    elif srcs:
        how = "scheduled times; wall-clock stamps where a run lacks them"
    else:
        how = "no run carried a usable time"
    return f"X axis: elapsed time since each run started ({how})."


# The caption's x-axis sentence on the kV axis, exactly as every area
# figure has carried it.
_KV_AXIS_CAPTION = ("X axis: nominal kV (measured_kV telemetry incomplete "
                    "on all runs).")


def _x_axis_caption(opts, runs=()):
    """The caption's x-axis sentence: the kV axis' unchanged, or on the
    field axis (`#398`) what the field is and what it is not. It is
    NOMINAL, V / t0 with V the nominal kV and t0 the thickness measured
    with the film mounted and prestretched, so it does not follow the
    film thinning as it expands. One t0 shared by every run is named;
    several are in the tidy CSV and the figspec, since a run's name and
    its t0 on one line each would outgrow the caption."""
    if opts.get('x') not in FIELD_AXES:
        return _KV_AXIS_CAPTION
    t0s = sorted({r['t0_um'] for r in runs if r.get('t0_um')})
    which = (f"{t0s[0]:g} µm on every run" if len(t0s) == 1
             else "per run in the tidy CSV and the figspec")
    return ("X axis: nominal field E = V / t₀ in V/µm, V the nominal kV "
            "(measured_kV telemetry incomplete on all runs) and t₀ the "
            "film thickness in each run's setup.txt, measured mounted and "
            f"prestretched ({which}). Nominal: it does not follow the film "
            "thinning as it expands.")


def _legs_caption(opts, point="one landing's post/pre mean"):
    """The caption line a leg-split figure earns, and no other figure."""
    return ("\nUp/down runs: one line per leg, triangle-up rising and "
            f"triangle-down falling, each point {point}"
            + ("; arrows follow the direction of travel"
               if opts.get('arrows', True) else "") + ".")


def _scale_caption(notes):
    """The log-scale caption line, or '' when both axes stayed linear.

    A figure whose axis is not what a reader assumes has to SAY so on the
    figure -- the PNG travels without the command line that made it."""
    notes = _dedupe(notes)
    return ('\n' + '  '.join(notes)) if notes else ''


# Where the support counts sit, and where the marker key has to start, both
# as POINTS above the axes floor -- never axes fractions (`#312`).
#
# The row used to be placed at axes y = 0.012 / 0.045 while the marker key
# sat at loc='lower right', i.e. one of the two in fractions and the other
# in font-sized padding. Those two agree at exactly one window size, and the
# window is resizable: on the campaign corpus the key landed on top of the
# counts and neither was readable. Points are the unit both are really made
# of -- text does not shrink with the axes -- so with the row's own height
# in the same unit the clearance below is arithmetic rather than a hope,
# and it holds at every window size the window permits.
#
# Two staggered baselines because where two grids interleave the levels can
# sit 0.05 kV apart, and a single row rendered n = 1, 5, 1 as "151" -- a
# support count that reads as a different support count is worse than none.
SUPPORT_FONT_PT = 6.0
SUPPORT_ROW_PT = (3.0, 12.0)
# COMPUTED from the row, not typed beside it: the top of the taller row
# plus 6 pt of daylight. Retyping it is how a clearance stops clearing
# anything the first time somebody nudges the font size.
MARKER_KEY_LIFT_PT = max(SUPPORT_ROW_PT) + SUPPORT_FONT_PT + 6.0


def _pt_above_axes(ax, pt, base=None):
    """`base` (default the axes transform) shifted UP by `pt` points.

    A lazy offset, evaluated at draw time: draw_area adds its artists
    before tight_layout and the window re-lays the figure on every
    resize, so anything measured in pixels here would be stale by the
    time it is drawn."""
    from matplotlib.transforms import offset_copy
    return offset_copy(ax.transAxes if base is None else base,
                       fig=ax.get_figure(), x=0, y=pt, units='points')


def _aggregate_series(ax, ag, band=True, labels=True,
                      color=AGGREGATE_COLOR, ls='-'):
    """The aggregate mean curve + its SEM band + a support count on the
    levels that earn one -> the (x, y) pairs it plotted, for the
    log-scale policy.

    SQUARE markers, not the round ones every run curve uses: the figure
    already spends open/closed circles on the hand-traced/machine
    convention (`#267`'s marker key), and a sixth round marker in a new
    colour would read as one more run rather than as the statistic.

    `band` is the n = 1 refusal arriving here as a flag; the band is also
    dropped level by level wherever fewer than two runs contributed, which
    is why fill_between gets a `where` mask rather than a whole-curve
    call -- a level with no SEM leaves a GAP in the band instead of being
    bridged by its neighbours' confidence.

    `color`/`ls` default to the ungrouped aggregate's black solid, so a
    figure without groups draws exactly what it drew before `#313`. A
    GROUP mean passes its own pair from assign_group_styles(). The
    colors are a different Tol palette on purpose (see GROUP_COLORS),
    and the style is what still separates the curves in grayscale and
    past a wrap. `ls` goes in as linestyle=, never as a format string: a
    GROUP_STYLES dash tuple is not one.

    THE BAND HAS NO EDGE, dashed or otherwise (`#373`, decided with the
    line styles). The dash pattern is carried by the 2.2 pt mean line on
    top, which is what a reader follows; edging each band in its group's
    pattern would put two more thin dashed curves beside every mean
    (twelve on the six-group concentration figure), and an edge at band
    width reads as a run curve, which is the confusion the square
    markers exist to prevent. Where bands overlap the means still say
    whose band is whose, and the band rule itself is untouched."""
    xs = [l['kv'] for l in ag]
    ys = [l['mean'] for l in ag]
    pts = list(zip(xs, ys))
    ax.plot(xs, ys, linestyle=ls, color=color, linewidth=AGGREGATE_LW,
            zorder=5)
    ax.plot(xs, ys, 's', markersize=4.0, linestyle='', zorder=6,
            color=color, markerfacecolor=color, markeredgecolor=color)
    if band and len(ag) > 1:
        have = [l['sem'] is not None for l in ag]
        lo = [l['mean'] - (l['sem'] or 0.0) for l in ag]
        hi = [l['mean'] + (l['sem'] or 0.0) for l in ag]
        ax.fill_between(xs, lo, hi, where=have, color=color,
                        alpha=0.18, linewidth=0, zorder=1)
        pts += list(zip(xs, lo)) + list(zip(xs, hi))
    if labels:
        # A FIXED ROW just above the x axis, not a tag trailing each point.
        # Hung off the curve the counts climb the staircase with it, land
        # on top of the run lines through the steep middle and pile up on
        # each other where the mean turns over -- measured on the five
        # poolable corpus runs, where the peak is exactly where the counts
        # matter most. get_xaxis_transform is x-in-data, y-in-axes, so the
        # row stays put whatever the y scale does (including --logy), and
        # _pt_above_axes puts its two heights in the same unit the marker
        # key clears them by.
        #
        # ONLY THE EXCEPTIONS (`#312`). A count per level printed the same
        # number forty times over and ran the row under the marker key;
        # the caption now states the one n and `aggregate_thin_levels`
        # picks out the levels that fall short of it. The stagger is
        # indexed by position in `ag`, not in the marked subset, so two
        # marked neighbours still alternate.
        thin = {id(l) for l in aggregate_thin_levels(ag)}
        for i, l in enumerate(ag):
            if id(l) not in thin:
                continue
            ax.text(l['kv'], 0.0, aggregate_support(l),
                    transform=_pt_above_axes(
                        ax, SUPPORT_ROW_PT[i % 2], ax.get_xaxis_transform()),
                    ha='center', va='bottom', fontsize=SUPPORT_FONT_PT,
                    color='#444444', zorder=7)
    return pts


def _aggregate_caption(runs, ag, opts, cap):
    """What the aggregate's band, grid and cap MEAN, as figure text.

    Every clause here is load-bearing and none of it can be left to the
    command line: the PNG travels, and a shaded band whose meaning a
    reader has to guess will be read as the +-1-2% budget band this
    figure spent four years teaching them to expect."""
    n = len(runs)
    if n < 2:
        head = (f"AGGREGATE: {n} run — NO BAND. The aggregate band is the "
                f"standard error of the mean and needs ≥ 2 runs; add runs "
                f"to earn one.")
    else:
        head = (f"AGGREGATE (black squares): mean of {n} runs, band = SEM "
                f"(σ/√n) per level — NOT the ±{TRACED_BAND_PCT:g}–"
                f"{MACHINE_BAND_PCT:g}% instrument budget, which is "
                f"suppressed under it.")
    grid = ('Grid: exact-key pooling — only levels a run really measured.'
            if opts.get('aggregate_exact') else
            'Grid: runs interpolated onto the common levels, never '
            'extrapolated past a run\'s own range and never across a '
            'breakdown.')
    stop = (f"Stops at {cap:g} {x_unit(opts)}, the first current-confirmed "
            f"breakdown."
            if cap is not None else
            "No current-confirmed breakdown among these runs, so the "
            "first-breakdown cap did not fire.")
    # n IN THE CAPTION, exceptions on the figure (`#312`). The row of
    # per-level counts printed the same number at every level and ran
    # under the marker key; one sentence carries it, and the levels that
    # fall short of it keep their own count where it means something.
    full = aggregate_full_n(ag)
    thin = aggregate_thin_levels(ag)
    support = (f"n = {full} at every level, all measured."
               if not thin else
               f"n = {full} at every level except the {len(thin)} marked "
               f"above the x axis, where 'a+b' = a measured + b "
               f"interpolated.")
    # THREE lines, not one, and each kept under ~215 characters: at 7 pt
    # on a 12.6 in figure anything longer runs off the right edge, which
    # is how the first draft of this lost the cap sentence entirely. The
    # existing caption's longest line is the width budget to match.
    # A caption a reader cannot finish is not a caption.
    return ('\n' + head
            + '\n' + grid
            + '\n' + support + '  ' + stop)


def _warn_aggregate(runs, ag, opts, cap, warn, what='aggregate',
                    labels=True):
    """Say on the CONSOLE what the figure can only say in six-point type.

    Two things, and both are the kind a reader should meet before quoting
    a number rather than after. Guardrail 3 first: how much of the
    aggregate is interpolation, and where the thinnest level is. Then the
    cap -- or its absence, which is the corpus's actual state and the
    quieter of the two failures. The cap keys on CURRENT-CONFIRMED
    breakdown (the only kind this tool has trusted since 2026-08-05), and
    the P3-family campaign carries none at all, so on those runs the
    aggregate runs the whole staircase THROUGH an area collapse that no
    current channel corroborated. Saying nothing there would let a figure
    imply the cap had been applied and found nothing to cut.

    `what` names the curve these lines are about -- 'aggregate' for the
    whole selection, "group 'CB'" for one group of `#313`. Every group
    gets its own full set, because n = 1 for one of them and n = 5 for
    the other is exactly the difference an operator must not have to
    infer. `labels` is false when the figure could not print the
    per-level counts (grouped figures cannot: see _group_caption), and
    the interpolation line then stops promising them."""
    n_runs = len(runs)
    if n_runs < 2:
        warn(f"{what}: {n_runs} run -- NO BAND drawn. The "
             f"aggregate band is the standard error of the mean and needs "
             f"at least 2 runs; the mean line is still the run itself")
    interp = [l for l in ag if l['n_interpolated']]
    if interp:
        worst = min(interp, key=lambda l: (l['n_measured'], l['kv']))
        where = ("every level short of the caption's n carries its own "
                 "'a+b' count on the figure, and " if labels else '')
        warn(f"{what}: {len(interp)} of {len(ag)} levels carry "
             f"interpolated contributions (thinnest measured support: "
             f"{worst['kv']:g} {x_unit(opts)}, {worst['n_measured']} "
             f"measured / "
             f"{worst['n_interpolated']} interpolated) -- {where}"
             f"--aggregate-exact pools only real readings")
    thin = [l for l in ag if l['n'] < n_runs]
    if thin:
        warn(f"{what}: {len(thin)} of {len(ag)} levels are supported by "
             f"fewer than all {n_runs} runs (a run is never extrapolated "
             f"past its own measured range); levels with n < 2 carry no "
             f"band at all")
    if cap is not None:
        warn(f"{what}: capped at {cap:g} {x_unit(opts)}, the first "
             f"current-confirmed breakdown -- past it the mean mixes intact "
             f"and collapsed devices, which is not a physical quantity")
    else:
        advis = [r['name'] for r in runs if r.get('advis')]
        extra = (f" {len(advis)} run(s) carry a breakdown ADVISORY "
                 f"({', '.join(advis)}), which confirms nothing and draws "
                 f"nothing -- read the top of the staircase by eye before "
                 f"quoting the mean there." if advis else '')
        warn(f"{what}: no run carries a current-confirmed breakdown, so "
             f"the first-breakdown cap did not fire and the mean runs to "
             f"the end of the staircase.{extra}")


# The caption's width budget, in characters, at 7 pt on a 12.6 in figure.
#
# The existing caption keeps its lines inside this by hand, and
# _aggregate_caption says so -- "each kept under ~215 characters... The
# existing caption's longest line is the width budget to match." That
# rule is right and the number in it was an estimate: the line it names
# (draw_area's "Points = per-level..." block, which every area figure has
# always carried and which renders inside the frame) is 248 characters.
# So the budget is measured off the line that demonstrably fits rather
# than guessed at, and 248 is it.
#
# A GROUPED caption cannot be kept inside it by hand, which is why this
# is a constant with a truncator behind it instead of a comment: its
# lines grow with the number of groups and with the length of the names
# an operator typed. Measured 2026-08-10 on the campaign's own CB-vs-P3
# figure, the first draft's support line reached ~256 and the figure cut
# it mid-word at "the console names eac|", losing the sentence that says
# where the per-level counts went.
#
# FOUND WHILE MEASURING THIS, and NOT fixed here: that same "Points ="
# line runs to 280 characters on a DEFAULT area figure, because
# ", bands ±2% machine / ±1% traced" is appended whenever the budget
# bands are drawn -- which is every figure that is not under an
# aggregate. Rendered on the corpus it clips to "…never averaged), banc"
# and loses the band widths entirely. That is a pre-existing defect on
# the most ordinary figure this tool draws, it predates `#313`, and
# fixing it moves the default figure's pixels -- which is a deliberate
# change with its own byte-identity guard to answer, not something to
# slip into a grouping PR. Dated entry in SLDEA_HANDOFF.md; the number
# is here so whoever takes it does not have to measure it again.
#
# FIXED 2026-10-06, and the anchor above corrected: 248 characters fit a
# 300 dpi export and not the window. Measured on main 0ffd1da, the
# 280-character line ends at 1.24 of the figure width at 90 dpi, 1.16 at
# 96 and 1.12 at 300; the 248-character one under the aggregate at 1.09,
# 1.02 and 0.98. Every caption line is now WRAPPED at its measured width
# (_place_caption) instead of trusting a character count, and the grouped
# lines are wrapped too (`#373`). This budget now cuts only a grouped line
# composed without a width test (_fit_or_wrap with no `fits`).
CAPTION_LINE_MAX = 248


def _fit(line, limit=CAPTION_LINE_MAX):
    """`line` truncated to the caption's width, with an ellipsis.

    A caption a reader cannot finish is not a caption -- but a caption
    that runs off the page is worse, because nothing on the figure says
    it did. Every line the group caption builds from operator-supplied
    text goes through here."""
    return line if len(line) <= limit else line[:limit - 1].rstrip() + '…'


# Continuation rows of a wrapped caption line start with this, so a
# reader can see where one caption line ends and the next begins.
CAPTION_WRAP_INDENT = '    '


def _wrap(line, fits, indent=CAPTION_WRAP_INDENT):
    """`line` broken at spaces into rows that each pass `fits` -> [rows].

    EVERY WORD IS KEPT (`#373`, 2026-10-06). Cutting a grouped caption
    line to fit dropped real content: on the six-group concentration split
    the 'AGGREGATE BY GROUP' and 'Support' lines ended in 'Carbon
    Solutions P3-S...' and lost the later groups. And the ungrouped
    caption's first line ran off the right edge of every default area
    figure and lost the band widths. A measurement figure must not drop
    caption text without saying so. Rows after the first carry `indent`.
    Only a single word wider than a whole row (a pasted path, say) is
    broken inside the word, because there is nowhere else to break it."""
    rows, cur = [], ''
    for word in line.split(' '):
        if not cur and not word:
            continue                   # the spaces at a break ARE the break
        lead = indent if rows else ''
        cand = f"{cur} {word}" if cur else word
        if fits(lead + cand):
            cur = cand
            continue
        if cur:
            rows.append(cur)
            cur = ''
            if not word:
                continue
            lead = indent
        # a single character that still does not fit is a row of its own:
        # it cannot be broken, and breaking it again would never end
        while len(word) > 1 and not fits(lead + word):
            k = len(word) - 1
            while k > 1 and not fits(lead + word[:k]):
                k -= 1
            rows.append(word[:k])
            word = word[k:]
            lead = indent
        cur = word
    if cur or not rows:
        rows.append(cur)
    return rows[:1] + [indent + r for r in rows[1:]]


def _fit_or_wrap(line, fits):
    """A caption line for the figure: wrapped to its measured width when
    `fits` is given (`#373`, grouped figures), else cut to the character
    budget exactly as before."""
    if fits is None:
        return _fit(line)
    return '\n'.join(_wrap(line, fits))


# The one grouped caption line that is still cut rather than wrapped in
# full: Members. It names every run, so it grows with the selection, and
# the tidy CSV's group column is its complete version. Three rows hold the
# six-group campaign figure's twelve runs with room to spare; past that it
# ends with a pointer to the CSV, as it did before `#373`.
MEMBERS_MAX_ROWS = 3


# How much of the figure width a caption row may reach, by the font's own
# metrics. Not 0.99: the raster is HINTED, and at a 7 pt size hinting
# rounds glyph advances to whole pixels, so the drawn row is wider than
# its metrics by an amount that depends on the dpi. Measured 2026-10-06
# (matplotlib 3.11.1) on the caption lines of the default, --prepost,
# strain, aggregate and power figures, every dpi from 50 to 159 and every
# 10th to 1200: drawn / measured = 0.989 at 300 dpi (the export default),
# 1.014 at 100 (the window), 1.025 at 96, 1.094 at 90, and at worst 1.121
# at 57 and 1.119 at 88. At the `#373` branch's 0.90, a row of real
# caption text ended at 1.002 of the width at 88 dpi. At 0.88, over every
# row those figures and two grouped ones wrap to at 12.6, 9 and 6 in wide,
# no row ends past 0.998 at any of those dpis, 0.978 from 72 dpi up and
# 0.959 from 90 up. A run name of one repeated letter is the worst text
# there is, since its rounding errors add instead of averaging; the
# suite's 'Rxxx...' fixture ends by 0.974.
CAPTION_FIT_FRAC = 0.88


def _caption_fitter(fig, fontsize=7, left=0.01, frac=CAPTION_FIT_FRAC):
    """-> fits(text): does `text` render, at the caption's size, inside
    `frac` of `fig`'s width from the caption's own left edge?

    Measured from the font itself (matplotlib's TextToPath, in points),
    not from a renderer, so the answer is the same on the window's Tk
    canvas, in a PNG and in an SVG, and needs nothing drawn first."""
    room = fig.get_figwidth() * 72.0 * (frac - left)

    def fits(text):
        return _caption_width(text, fontsize) <= room
    return fits


_WIDTHS = {}


def _caption_width(text, fontsize):
    """`text`'s width in points at `fontsize`, by the font's metrics.

    CACHED, because a window resize re-wraps the caption at every size a
    drag passes through, and _wrap measures each row word by word.
    Measured 2026-10-06 on an aggregate figure: uncached, the re-wrap
    took 87 ms of a 124 ms relayout at 6 in wide (11 rows), against 38 ms
    for the layout alone (`#316` is why that matters). Most strings recur
    from one size to the next, so with the cache a drag through 20
    distinct sizes from a cold start costs a median 59 ms a relayout,
    against 42 ms without the caption step. The width depends only on
    the string and the size: the caption's font is matplotlib's default,
    which nothing in this tool changes at run time. Cleared when it
    passes 20000 strings, so it cannot grow without bound."""
    key = (text, fontsize)
    width = _WIDTHS.get(key)
    if width is None:
        from matplotlib.font_manager import FontProperties
        from matplotlib.textpath import TextToPath
        if len(_WIDTHS) >= 20000:
            _WIDTHS.clear()
        width = _WIDTHS[key] = TextToPath().get_text_width_height_descent(
            text, FontProperties(size=fontsize), ismath=False)[0]
    return width


def _group_caption(drawn, opts, hidden, materials=False, fits=None):
    """What a GROUPED aggregate's curves, bands and caps mean (`#313`).

    `drawn` is [(name, runs, ag, cap, color, style)], one per group that
    reached the figure, in drawing order.

    Longer than the ungrouped caption because it has strictly more to
    say: the band policy is decided PER GROUP, and on this campaign the
    two groups land on opposite sides of it -- carbon black is a single
    run and gets no band, P3 is five and gets one. A caption that stated
    the policy once would be false about one of the two curves.

    THE PER-LEVEL SUPPORT COUNTS ARE NOT PRINTED on a grouped figure, and
    that is a decision rather than an omission. `#312` moved them to
    'exceptions only' precisely because one row of numbers above the x
    axis already collided with the marker key; G groups want G rows in
    the same strip, at the same x positions, in 6 pt type, and nothing on
    the figure would say which row belonged to which curve. So each
    group's support is stated here in words, and the console names the
    thinnest level of each.

    `materials` (`#373`): at least one group carries a recorded material,
    so its line style MEANS something (the material), and the caption
    says what, on a line of its own. Without it the styles are only
    there to tell the curves apart, as before, and nothing is added.

    `fits` (`#373`): _caption_fitter's width test. Every line is then
    WRAPPED to what really renders inside the frame, keeping every word
    (_wrap); without it the lines are cut to the character budget as
    before."""
    heads = []
    for name, runs, ag, _cap, _color, style in drawn:
        n = len(runs)
        heads.append(f"{name} ({group_style_name(style)}, {n} run"
                     f"{'' if n == 1 else 's'}"
                     f"{'' if n >= 2 else ' — NO BAND'})")
    head = ("AGGREGATE BY GROUP (squares): " + '; '.join(heads)
            + f". Bands are SEM (σ/√n), NOT the ±{TRACED_BAND_PCT:g}–"
              f"{MACHINE_BAND_PCT:g}% instrument budget.")
    lone = [name for name, runs, _a, _c, _col, _s in drawn if len(runs) < 2]
    if lone:
        head += (f" {', '.join(lone)} has one run: an aggregate needs ≥ 2 "
                 f"runs to earn a band.")
    styles = ''
    if materials:
        styles = '\n' + _fit_or_wrap(
            "Line style = the electrode material the group's runs recorded "
            "in setup.txt when the group was formed: groups of one "
            "material share it and differ by color; a group of no single "
            "material has a style of its own.", fits)
    grid = ('Grid: exact-key pooling — only levels a run really measured.'
            if opts.get('aggregate_exact') else
            'Grid: runs interpolated onto the common levels, never '
            'extrapolated past a run\'s own range and never across a '
            'breakdown.')
    if hidden:
        grid += '  Contributing runs hidden (--aggregate-only).'
    bits, capped = [], False
    for name, _runs, ag, cap, _color, _style in drawn:
        full = aggregate_full_n(ag)
        thin = len(aggregate_thin_levels(ag))
        capped = capped or cap is not None
        bits.append(f"{name}: n = {full} over {len(ag)} levels"
                    + (f", {thin} short or interpolated"
                       if thin else ", all measured")
                    + (f", capped at {cap:g} {x_unit(opts)}"
                       if cap is not None else ''))
    # the cap sentence ONCE, not per group: it is the same sentence every
    # time it does not fire, and repeating it is what pushed the first
    # draft of this line off the right edge of the figure
    support = ('Support — ' + '; '.join(bits) + '.'
               + ('  Caps are the first current-confirmed breakdown.'
                  if capped else '  No group carries a current-confirmed '
                                 'breakdown, so no cap fired.'))
    counts = ("Per-level support counts are not printed when groups share "
              "a panel; the console names each group's thinnest level.")
    return ('\n' + _fit_or_wrap(head, fits) + styles + '\n'
            + _fit_or_wrap(grid, fits) + '\n'
            + _fit_or_wrap(support, fits) + '\n' + _fit_or_wrap(counts, fits))


def _group_members_caption(drawn, limit=CAPTION_LINE_MAX, fits=None):
    """Which runs each group's mean is made of, as one caption line.

    Load-bearing under --aggregate-only above all: with the contributing
    curves hidden the legend no longer names them, and a mean whose
    members a reader cannot recover is not a citable figure. Truncated
    to `limit` characters with the count kept, because the tidy CSV's new
    'group' column is the complete answer and this line only has to be
    enough to recognize the figure.

    With `fits` (`#373`) the line is WRAPPED to its measured width and
    always ends by pointing at the CSV. It is the one grouped line still
    allowed to stop short, and only past MEMBERS_MAX_ROWS rows; then it
    says so and where the rest is, so nothing is dropped silently."""
    bits = [f"{name} = " + ', '.join(r['name'] for r in runs)
            for name, runs, _ag, _cap, _col, _st in drawn]
    line = 'Members: ' + '; '.join(bits) + '.'
    if fits is not None:
        whole = line + " (Also in the tidy CSV's group column.)"
        rows = _wrap(whole, fits)
        if len(rows) > MEMBERS_MAX_ROWS:
            tail = "… (full membership in the tidy CSV's group column)"

            def ok(k):
                cand = line[:k].rstrip(' ,;') + tail
                return len(_wrap(cand, fits)) <= MEMBERS_MAX_ROWS
            lo, hi = 0, len(line)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if ok(mid):
                    lo = mid
                else:
                    hi = mid - 1
            rows = _wrap(line[:lo].rstrip(' ,;') + tail, fits)
        return '\n' + '\n'.join(rows)
    if len(line) > limit:
        # the pointer to the full answer is part of the budget, not an
        # addition to it -- truncating to `limit` and THEN appending is
        # how a truncator produces a line longer than the one it cut
        tail = "… (full membership in the tidy CSV's group column)"
        line = line[:max(0, limit - len(tail))].rstrip(' ,;') + tail
    return '\n' + line


def _band_edges(y, p_pct, pct=False):
    """The budget band's (lo, hi) around one plotted `y`.

    The budget is +-p % of the AREA, so the band is built in RATIO space,
    A/A0 * (1 -/+ p), and only then mapped into the unit the panel shows.
    On the mm2 panel and the A/A0 panel that map is a plain scale, and
    this is y * (1 -/+ p). Under strain percent `y` is (A/A0 - 1) * 100,
    so scaling it by (1 -/+ p) would be +-p of the STRAIN: zero width at
    rest and 2.6 to 10.5 times too narrow on the campaign runs. Instead
    the ratio is recovered as r = 1 + y / 100 and mapped back through
    norm_y, which gives a half-width of p * 100 * A/A0 points: +-2
    points at rest, wider as the area grows."""
    f = p_pct / 100.0
    if not pct:
        return y * (1 - f), y * (1 + f)
    r = 1.0 + y / 100.0
    return norm_y(r * (1 - f), 1.0, True), norm_y(r * (1 + f), 1.0, True)


def _series(ax, xs, ys, traced, color, ls, bands, band_traced=None,
            pct=False, markers=None):
    """One curve: line + per-point open/closed markers + traced-aware band.
    `traced` drives the marker fill; `band_traced` (default: same) drives
    the band width -- the mean line passes the AND-aggregate there so a
    mixed pre/post level keeps the machine +-2% band. `pct` says `ys` are
    strain percent (the normalized panel under --strain-pct); every other
    caller leaves it False, so the mm2 panel and the A/A0 panel keep the
    band they always had.

    `markers` (2026-09-23) gives each point its own marker -- '^' on a
    rising leg, 'v' on a falling one -- and None skips a point: a leg's
    line starts at the turn, on a point its own leg already marked.
    Absent, every point is the 'o' it always was, drawn by the same
    calls in the same order."""
    if band_traced is None:
        band_traced = traced
    ax.plot(xs, ys, ls, color=color, linewidth=1.8, zorder=3)
    for i, (x, y, tr) in enumerate(zip(xs, ys, traced)):
        mk = 'o' if markers is None else markers[i]
        if mk is None:
            continue
        ax.plot([x], [y], mk, markersize=4.5 if mk == 'o' else 5.5,
                zorder=4, color=color,
                markerfacecolor='white' if tr else color,
                markeredgecolor=color, markeredgewidth=1.2)
    if bands and len(xs) > 1:
        edges = [_band_edges(y, TRACED_BAND_PCT if tr else MACHINE_BAND_PCT,
                             pct)
                 for y, tr in zip(ys, band_traced)]
        lo = [e[0] for e in edges]
        hi = [e[1] for e in edges]
        ax.fill_between(xs, lo, hi, color=color, alpha=0.14, linewidth=0,
                        zorder=2)


def _cross_marks(ax, pts, color, coarse=False):
    """X at each current-confirmed breakdown point. `pts` = [(x, y)].

    `coarse` draws the X hollow (`#264`): the event is just as confirmed,
    but the run sampled current slowly enough that its onset could be
    anywhere in the interval before this snapshot, so the mark is a
    neighbourhood rather than a point. It is still DRAWN -- suppressing a
    real current-confirmed event because the camera was slow would hide
    evidence, which is the P3_5 mistake pointing the other way."""
    for x, y in pts:
        ax.plot([x], [y], 'X', markersize=9, color=color, zorder=6,
                markerfacecolor='white' if coarse else color,
                markeredgecolor=color if coarse else 'black',
                markeredgewidth=1.4 if coarse else 0.6)


def _legend(ax, run_handles, style_rows, handlelength=None):
    """The run legend (+ the style rows this figure earned) -> the Legend.

    Returned rather than dropped: matplotlib keeps ONE ax.legend_, so the
    marker key has to re-add this one as a standalone artist before it
    creates its own or the run legend silently disappears (`#267`).

    `handlelength` (font-size units) is GROUP_HANDLE_EM on a grouped
    figure, so a dash pattern is long enough to read in the key (`#373`);
    None keeps matplotlib's default and every other figure's layout."""
    from matplotlib.lines import Line2D
    handles = list(run_handles)
    for label, kw in style_rows:
        handles.append(Line2D([], [], color='#666666', label=label, **kw))
    extra = {} if handlelength is None else {'handlelength': handlelength}
    return ax.legend(handles=handles, fontsize=8, loc='upper left',
                     framealpha=0.9, **extra)


# the two marker fills `_series` draws, as the figure's own key (`#267`).
# Area mode only: current/power draw one plain filled dot per snapshot with
# no open/closed meaning, and a key there would claim a distinction the
# figure does not make.
MARKER_KEY_ROWS = (('hand-traced (outer toe)', 'white'),
                   ('machine (half-height)', '#666666'))


def _marker_key(ax, main_legend, lift=False):
    """Draw the open/closed marker key as a SECOND compact legend.

    Its own legend in the opposite corner rather than two more rows in the
    run legend: the run list is what a reader scans to tell the curves
    apart, and a fixed key that grows it pushes the runs down the figure
    on every plot. Placed lower right because area curves rise to the
    right of the panel the run legend sits in.

    `lift` is the aggregate's support row asking for its own floor
    (`#312`): the two share the bottom-right corner, so the key starts
    MARKER_KEY_LIFT_PT above the axes floor rather than at it whenever
    that row is on this axis. Lifted by shifting the whole anchor box up
    -- the same corner, the same font padding, just a higher floor -- so
    a figure without the row lays out to the pixel it always did."""
    from matplotlib.lines import Line2D
    if main_legend is not None:
        ax.add_artist(main_legend)
    proxies = [Line2D([], [], linestyle='', marker='o', markersize=4.5,
                      color='#666666', markerfacecolor=fill,
                      markeredgecolor='#666666', markeredgewidth=1.2,
                      label=label)
               for label, fill in MARKER_KEY_ROWS]
    extra = ({} if not lift else
             {'bbox_to_anchor': (0.0, 0.0, 1.0, 1.0),
              'bbox_transform': _pt_above_axes(ax, MARKER_KEY_LIFT_PT)})
    return ax.legend(handles=proxies, fontsize=7, loc='lower right',
                     framealpha=0.9, title='marker fill',
                     title_fontsize=7, **extra)


# ---------------------------------------------------------------------------
# up/down legs and the elapsed-time axis (2026-09-23)
# ---------------------------------------------------------------------------

LEG_MARKERS = {'rise': '^', 'fall': 'v'}

# The legend rows the leg markers earn -- only on a figure that drew a run
# leg by leg, so a single-sweep figure keeps the legend it always had.
LEG_STYLE_ROWS = (('rising leg', {'linestyle': '', 'marker': '^'}),
                  ('falling leg', {'linestyle': '', 'marker': 'v'}))


def _leg_paths(ents, yf, trk, btrk, scale=1.0):
    """Time-ordered landing entries (levels(by='landing')) -> one
    (xs, ys, traced, band_traced, markers) per leg.

    Every leg after the first starts its LINE at the previous leg's last
    point, so the drawn path turns at the peak the way the voltage did --
    but not its MARKER there (None): that point belongs to the leg that
    reached it, and is already marked by it. `scale` is the run's
    x_scale: each x is the landing's kV times it (`#398`)."""
    out, prev, grp = [], None, []

    def flush():
        pts = ([prev] if prev is not None else []) + grp
        marks = ([None] if prev is not None else []) + [
            LEG_MARKERS.get(e['leg'], 'o') for e in grp]
        out.append(([e['kv'] * scale for e in pts], [yf(e) for e in pts],
                    [e[trk] for e in pts], [e[btrk] for e in pts], marks))

    for e in ents:
        if grp and (e['leg'], e['cycle']) != (grp[-1]['leg'],
                                              grp[-1]['cycle']):
            flush()
            prev, grp = grp[-1], []
        grp.append(e)
    if grp:
        flush()
    return out


def _draw_area_legs(axl, axr, run, lvs, opts, color, budget_bands, pct,
                    sinks, arrows, scale=1.0):
    """draw_area for a run whose voltage also FELL: the same curves the
    per-level view draws -- pre/post and/or the mean -- but per LANDING,
    one line per leg, triangle-up on a rising leg and triangle-down on a
    falling one. Keyed by kV these legs averaged into one point per level,
    and --prepost's post/pre slots kept only whichever leg came last.

    Travel paths go into `arrows` (panel -> [(xs, ys, color)]) for
    _direction_arrows, which runs once the scales are final: the mean
    line's when it is drawn, else the post-ramp line's -- one set per
    run, not one per series. `scale` is the run's x_scale (`#398`)."""
    xs_all, ysl_all, ysr_all = sinks
    a0 = run['a0']
    series = []
    if opts['prepost']:
        series += [(key, ls, 'traced_' + key, 'traced_' + key, budget_bands)
                   for key, ls in (('post', '-'), ('pre', '--'))]
    if opts['mean'] or not opts['prepost']:
        # the same fill rule as the per-level mean: all_traced, so a mixed
        # landing's machine-only mean plots filled (audit 2026-08-05)
        series.append(('mean', '-', 'all_traced', 'all_traced',
                       budget_bands and not opts['prepost']))
    arrow_key = series[-1][0] if series[-1][0] == 'mean' else 'post'
    for key, ls, trk, btrk, bands in series:
        ents = [e for e in lvs if e[key] is not None]
        if not ents:
            continue
        for panel, ax in ((0, axl), (1, axr)):
            if ax is None:
                continue
            if panel == 0:
                def yf(e):
                    return e[key]
            else:
                def yf(e):
                    return norm_y(e[key], a0, pct)
            for xs, ys, tr, btr, mks in _leg_paths(ents, yf, trk, btrk,
                                                   scale):
                _series(ax, xs, ys, tr, color, ls, bands, btr,
                        pct=(pct and panel == 1), markers=mks)
                if key == arrow_key:
                    arrows[panel].append((xs, ys, color))
        xs_all += [e['kv'] * scale for e in ents]
        ysl_all += [e[key] for e in ents]
        ysr_all += [norm_y(e[key], a0, pct) for e in ents]


def _draw_area_time(axl, axr, run, opts, color, budget_bands, pct, split,
                    sinks):
    """draw_area against ELAPSED TIME: one point per snapshot, joined in
    the order they were taken. No per-level pooling -- on this axis every
    snapshot already has a place of its own, which is the point of it. On
    a run whose voltage also fell, the points still carry their leg's
    triangle, so the time series says which stretch was the way down.
    -> True when anything was drawn."""
    xs_all, ysl_all, ysr_all = sinks
    pts = [(x_value(r, opts), r) for r in run['rows']
           if r['area_mm2'] is not None and x_value(r, opts) is not None]
    if not pts:
        return False
    xs = [x for x, _r in pts]
    ys = [r['area_mm2'] for _x, r in pts]
    tr = [r['traced'] for _x, r in pts]
    mks = ([LEG_MARKERS.get(r['leg'], 'o') for _x, r in pts] if split
           else None)
    yr = [norm_y(y, run['a0'], pct) for y in ys]
    if axl is not None:
        _series(axl, xs, ys, tr, color, '-', budget_bands, markers=mks)
    if axr is not None:
        _series(axr, xs, yr, tr, color, '-', budget_bands, pct=pct,
                markers=mks)
    xs_all += xs
    ysl_all += ys
    ysr_all += yr
    return True


def _direction_arrows(ax, paths):
    """Small arrowheads along each travelled path, pointing the way the
    voltage went: `paths` = [(xs, ys, color)], each a leg's line.

    Deliberately sparse -- a quarter, a half and three quarters of the way
    along a leg, or its middle segment when it is short -- and only on
    segments that move in x: a vertical step within one landing has no
    direction in voltage. Drawn AFTER the scales are final, and placed in
    the axis' own scaled space (log10 on a log axis), so a head sits ON
    the drawn line rather than beside it. Never on a line drawn sorted by
    kV: every arrow there would point right, claiming a direction the
    data never had -- which is why only the leg-split paths reach here.
    Kept out of the layout, so arrows cannot move a figure's margins."""
    import numpy as np
    if ax is None or not paths:
        return
    fx, fy = ax.xaxis.get_transform(), ax.yaxis.get_transform()
    ix, iy = fx.inverted(), fy.inverted()

    def fwd(tr, v):
        return float(tr.transform(np.array([[v]], float))[0][0])

    for xs, ys, color in paths:
        segs = [i for i in range(len(xs) - 1) if xs[i + 1] != xs[i]]
        if not segs:
            continue
        if len(segs) >= 4:
            picks = sorted({segs[int(len(segs) * f)]
                            for f in (0.25, 0.5, 0.75)})
        else:
            picks = [segs[len(segs) // 2]]
        for i in picks:
            try:
                sx0, sx1 = fwd(fx, xs[i]), fwd(fx, xs[i + 1])
                sy0, sy1 = fwd(fy, ys[i]), fwd(fy, ys[i + 1])
            except (ValueError, TypeError):
                continue
            if not all(map(math.isfinite, (sx0, sx1, sy0, sy1))):
                continue

            def at(f):
                return (fwd(ix, sx0 + f * (sx1 - sx0)),
                        fwd(iy, sy0 + f * (sy1 - sy0)))
            a = ax.annotate('', xy=at(0.56), xytext=at(0.44),
                            arrowprops=dict(arrowstyle='-|>', color=color,
                                            lw=0, alpha=0.85,
                                            mutation_scale=13,
                                            shrinkA=0, shrinkB=0),
                            zorder=3.5)
            a.set_in_layout(False)


def draw_area(fig, axl, axr, runs, opts, warn=lambda m: None):
    """Draw the two-panel area figure into ALREADY-CREATED axes.

    Split out of figure_area for `#223`: the window needs to draw into its
    live Tk canvas without saving a file, and a second drawing routine
    would be a second set of plotting rules to keep in step. Everything
    that decides what a figure LOOKS like lives here; the callers only
    decide where the pixels go.

    EITHER axis may be None (`#270`): the caller creates only the panels
    opts['subplots'] asked for, and the survivor gets the whole canvas."""
    from matplotlib.lines import Line2D

    panels = [ax for ax in (axl, axr) if ax is not None]
    legend_ax = axl if axl is not None else axr
    run_handles = []
    had_x = had_fallback = had_coarse = False
    cadence_notes = []
    # The normalized panel's units, read ONCE and passed to every site that
    # divides by A0. Reading opts at each site instead is how six of seven
    # get converted and the figure still looks finished.
    pct = bool(opts.get('strain_pct'))
    # what actually got plotted, per axis -- the log-scale policy reads
    # the DATA and axes-fraction gridlines must not vote (`#263`)
    xs_all, ysl_all, ysr_all = [], [], []
    # The calibrated ±1-2% band is ONE run's instrument budget. Under the
    # aggregate the figure's claim is the SEM of the family, and five
    # budget bands stacked under it would compete with exactly the band a
    # reader is meant to read -- the same argument that suppresses it under
    # --prepost, where the gap between the two lines is the information
    # (`#268`, policy 2026-08-09).
    # .get, like every option added after the hand-built opts dicts in the
    # test suite and the older callers: a missing key means "the behaviour
    # that existed before this option", never a KeyError mid-figure.
    budget_bands = opts['bands'] and not opts.get('aggregate')
    # `#313`: with the aggregate on, --aggregate-only draws the group (or
    # whole-selection) means ALONE. The runs are still loaded, still
    # guarded, still in the tidy CSV -- only this loop stops, which is
    # what turns fifteen curves plus two means into two means. Refused
    # any influence when the aggregate is off, because then it would be a
    # flag that emptied the figure.
    hide_runs = bool(opts.get('aggregate_only')) and bool(
        opts.get('aggregate'))
    # 2026-09-23: the elapsed-time axis, and up/down runs drawn leg by leg.
    # A single sweep takes neither branch below -- the else is the code
    # that always drew it, untouched -- so its figure cannot move.
    timeax = opts.get('x') == 'time'
    # `#398`: on the field axis a level sits at its kV times the run's
    # x_scale (1000 / t0); on the kV axis that factor is exactly 1.0, so
    # every position there is the kV it always was, to the bit
    fieldax = opts.get('x') in FIELD_AXES
    split_any = False
    arrow_paths = {0: [], 1: []}
    for run in ([] if hide_runs else runs):
        color = run['color']
        k = run.get('x_scale', 1.0)
        split = opts.get('split_legs', True) and multi_leg(run)
        if timeax:
            if not _draw_area_time(axl, axr, run, opts, color, budget_bands,
                                   pct, split, (xs_all, ysl_all, ysr_all)):
                continue
            split_any = split_any or split
            lvs = []
        elif split:
            lvs = levels(run, by='landing')
            if not lvs:
                continue
            split_any = True
            _draw_area_legs(axl, axr, run, lvs, opts, color, budget_bands,
                            pct, (xs_all, ysl_all, ysr_all), arrow_paths,
                            scale=k)
        else:
            lvs = levels(run)
            if not lvs:
                continue
        xs = [l['kv'] * k for l in lvs]
        if opts['prepost'] and not (timeax or split):
            for key, ls in (('post', '-'), ('pre', '--')):
                pts = [(l['kv'] * k, l[key], l['traced_' + key])
                       for l in lvs if l[key] is not None]
                if pts:
                    px, py, pt = zip(*pts)
                    if axl is not None:
                        _series(axl, px, py, pt, color, ls, budget_bands)
                    if axr is not None:
                        _series(axr, px, [norm_y(y, run['a0'], pct) for y in py], pt,
                                color, ls, budget_bands, pct=pct)
                    xs_all += list(px)
                    ysl_all += list(py)
                    ysr_all += [norm_y(y, run['a0'], pct) for y in py]
        if (opts['mean'] or not opts['prepost']) and not timeax:
            # marker fill follows the CONVENTION of the plotted value:
            # a mixed level's mean uses the machine member(s) only, so
            # it plots filled — the OR-aggregate used to open-mark a
            # blended number as 'outer toe ±1%' (audit 2026-08-05)
            tr = [l['all_traced'] for l in lvs]
            band_tr = [l['all_traced'] for l in lvs]
            ys = [l['mean'] for l in lvs]
            show_bands = budget_bands and not opts['prepost']
            if split:
                pass                     # drawn per leg by _draw_area_legs
            else:
                if axl is not None:
                    _series(axl, xs, ys, tr, color, '-', show_bands,
                            band_tr)
                if axr is not None:
                    _series(axr, xs, [norm_y(y, run['a0'], pct)
                                      for y in ys], tr, color,
                            '-', show_bands, band_tr, pct=pct)
                xs_all += list(xs)
                ysl_all += list(ys)
                ysr_all += [norm_y(y, run['a0'], pct) for y in ys]
            mixed = [l['kv'] for l in lvs if l['mixed']]
            if mixed:
                warn(f"{run['name']}: {len(mixed)} level(s) mix a "
                     f"hand-traced (outer-toe) and a machine "
                     f"(half-height) snapshot "
                     f"({', '.join(f'{k:g}' for k in mixed)} kV) — the "
                     f"mean plots the machine member(s) only; conventions "
                     f"differ +5.2-5.7% area and must not be averaged "
                     f"(see --prepost for both, and the tidy "
                     f"'convention' column)")
        if opts['breakdown']:
            coarse = coarse_cadence(run, opts)
            drawn, unanchored = [], []
            for r in run['rows']:
                # x_value is the row's kV on the kV axis, so this is the
                # same test and the same position as ever there -- and the
                # moment of the event on the elapsed-time axis
                bx = x_value(r, opts)
                if r['index'] not in run['flags'] or r['kv'] is None \
                        or bx is None:
                    continue
                if r['area_mm2'] is not None:
                    drawn.append((bx, r['area_mm2']))
                else:
                    # confirmed but no reviewed area (e.g. frame rejected
                    # in review): anchor the event to its kV rather than
                    # silently dropping it
                    for ax in panels:
                        ax.axvline(bx, color=color, linestyle='--',
                                   linewidth=0.9, alpha=0.55, zorder=1)
                    xs_all.append(bx)
                    unanchored.append(r['index'])
            if axl is not None:
                _cross_marks(axl, drawn, color, coarse)
            if axr is not None:
                _cross_marks(axr, [(x, norm_y(y, run['a0'], pct))
                               for x, y in drawn],
                             color, coarse)
            xs_all += [x for x, _ in drawn]
            ysl_all += [y for _, y in drawn]
            ysr_all += [norm_y(y, run['a0'], pct) for _, y in drawn]
            had_x = had_x or bool(drawn)
            had_coarse = had_coarse or (coarse and bool(drawn))
            had_fallback = had_fallback or bool(unanchored)
            if coarse and (drawn or unanchored):
                cadence_notes.append(_cadence_note(run))
                warn(f"{run['name']}: current sampled every "
                     f"{run['cadence_s']:.1f} s "
                     f"({run.get('cadence_src', '?')}), slower than "
                     f"{CADENCE_COARSE_S:g} s -- a breakdown's onset can "
                     f"be anywhere in the interval before the flagged "
                     f"snapshot, so its X is drawn hollow")
            if unanchored:
                warn(f"{run['name']}: confirmed breakdown row(s) "
                     f"{unanchored} have no reviewed area -- drawn as "
                     f"dashed verticals at their "
                     f"{'field' if fieldax else 'kV'} (see current mode)")
        run_handles.append(Line2D([], [], color=color, label=run['name']))

    agg_caption = ''
    # did the aggregate actually PRINT a count on the legend axis? Only
    # then does the marker key give up the bottom of its corner (`#312`) --
    # a figure with nothing to mark keeps the layout it always had.
    agg_support_row = False
    # the legend's handle length, and whether any drawn group mean stands
    # for a recorded material (`#373`). Both stay at their pre-`#373`
    # answers unless a GROUP mean is actually drawn
    handle_em = None
    materials_drawn = False
    # the grouped caption block, as a function of the figure's width
    # (`#373`); None on every other figure, which keeps its fixed caption
    group_caption = None
    if opts.get('aggregate'):
        # ONE mean, or one per operator-assigned group (`#313`). The two
        # paths are the same code with a different list of run sets: a
        # group is not a special kind of aggregate, it is an aggregate
        # over fewer runs, and every rule `#268` decided -- the SEM band,
        # the n = 1 refusal, the two guardrails, the first-breakdown cap
        # -- is therefore computed from THAT group's runs and no others.
        # With no groups the list is a single unnamed set, so a figure
        # that predates this draws exactly what it drew before.
        sets, loose = group_sets(runs, opts.get('groups') or ())
        grouped = bool(sets)
        if grouped and loose:
            # what happens to them depends on whether the runs are drawn
            # at all -- 'they are drawn but average into nothing' is a
            # false sentence under --aggregate-only, where they are on
            # the figure in no form whatsoever
            fate = ('they are not on the figure at all and average into '
                    'nothing' if hide_runs else
                    'they are drawn but average into nothing')
            warn(f"aggregate by group: {len(loose)} selected run(s) are in "
                 f"no group ({', '.join(r['name'] for r in loose)}) -- "
                 f"{fate}; assign them or deselect them")
        # A line style per MATERIAL (`#373`), from the material each group
        # recorded when it was formed: opts' group_materials, i.e. the
        # figspec, and never a setup.txt read at draw time, so a later
        # edit to a run cannot restyle an exported figure. A group with
        # no entry has no single material and gets a style of its own.
        mats = {n.casefold(): m
                for n, m in (opts.get('group_materials') or ())}
        keys = [material_key(mats[name.casefold()])
                if name.casefold() in mats else None
                for name, _subset in sets]
        styles, style_notes = assign_group_styles(keys)
        for note in style_notes:
            warn(f"aggregate by group: {note}")
        label_ax = axl if axl is not None else axr
        drawn_groups = []
        # pools exact-key pooling cannot draw on the field axis (`#398`)
        refused = []
        for i, (name, subset) in enumerate(
                sets if grouped else [(None, runs)]):
            color, ls = styles[i] if grouped else (AGGREGATE_COLOR, '-')
            t0s = (sorted({r.get('t0_um') or 0.0 for r in subset})
                   if fieldax else [])
            if opts.get('aggregate_exact') and len(t0s) > 1:
                # REFUSED, and said, rather than drawn: a run's field
                # levels are its kV levels over its own t0, so runs on
                # films of different thickness share no field level, and
                # exact-key pooling would draw each run's points as a
                # "mean" of one with no band. Interpolation onto the
                # field grid is the pooling that works across them. The
                # pool's color stays reserved, so the others keep theirs.
                what = f"group {name!r}" if grouped else 'aggregate'
                refused.append((what, t0s))
                warn(f"{what}: NOT drawn. Exact-level pooling on the "
                     f"field axis needs every run in it to share one film "
                     f"thickness, and these have "
                     f"{', '.join(f'{t:g}' for t in t0s)} µm, which share "
                     f"no field level. Untick exact pooling "
                     f"(--aggregate-exact) to interpolate them onto a "
                     f"common field grid.")
                continue
            cap_kv = aggregate_cap_kv(subset)
            # n = 1 is a REFUSAL, not a fallback (`#268`, decided
            # 2026-08-09): the band drops out entirely and the caption
            # says why. A single run's spread about itself is zero, and
            # quietly substituting the instrument budget would dress a
            # claim about the instrument up as a claim about the family.
            # PER GROUP, and on this campaign that is the common case and
            # not a corner: the carbon-black group is one run.
            band = len(subset) >= 2
            ag = None
            for ax, norm, sink in ((axl, False, ysl_all),
                                   (axr, True, ysr_all)):
                if ax is None:
                    continue
                ag = aggregate_levels(subset, norm=norm,
                                      exact=opts.get('aggregate_exact'),
                                      pct=pct,
                                      legs=opts.get('split_legs', True))
                if not ag:
                    continue
                # counts only on an UNGROUPED figure -- G groups would
                # want G rows of 6 pt numbers at the same x positions,
                # with nothing saying which row is whose (_group_caption)
                pts = _aggregate_series(
                    ax, ag, band=band, color=color, ls=ls,
                    labels=(not grouped) and ax is label_ax)
                if ax is label_ax and not grouped:
                    agg_support_row = bool(aggregate_thin_levels(ag))
                xs_all += [x for x, _ in pts]
                sink += [y for _, y in pts]
            if not ag:
                warn(f"{'group ' + repr(name) if grouped else 'aggregate'}: "
                     f"nothing to average -- no run contributed a level "
                     f"below the first-breakdown cap")
                continue
            drawn_groups.append((name, subset, ag, cap_kv, color, ls))
            n = len(subset)
            if grouped:
                label = (f"{name} — mean of {n} runs (±SEM)" if band
                         else f"{name} — mean of 1 run (no band)")
            else:
                label = (f"aggregate mean of {n} runs (±SEM)" if band
                         else 'aggregate mean (1 run — no band)')
            # a GROUP handle draws at the curve's own width, so its dash
            # pattern is the curve's (matplotlib scales dashes by the
            # width); the ungrouped handle keeps the default it always had
            run_handles.append(Line2D(
                [], [], color=color, linestyle=ls, marker='s',
                markersize=4.0, label=label,
                **({'linewidth': AGGREGATE_LW} if grouped else {})))
            if grouped:
                handle_em = GROUP_HANDLE_EM
                materials_drawn = materials_drawn or keys[i] is not None
            _warn_aggregate(subset, ag, opts, cap_kv, warn,
                            what=(f"group {name!r}" if grouped
                                  else 'aggregate'),
                            labels=not grouped)
        if drawn_groups and grouped:
            # WRAPPED to the width it really renders at (`#373`): seeded
            # group names are whole material names, and neither the
            # character budget nor a cut kept every group on the figure.
            # A function of the figure, not a string, because the width
            # it wraps to is the figure's: relayout re-runs it when the
            # window changes shape (_place_caption).
            def group_caption(fits, drawn=tuple(drawn_groups),
                              materials=materials_drawn):
                return (_group_caption(drawn, opts, hide_runs,
                                       materials=materials, fits=fits)
                        + _group_members_caption(drawn, fits=fits))
        elif drawn_groups:
            name, subset, ag, cap_kv, _c, _s = drawn_groups[0]
            agg_caption = _aggregate_caption(subset, ag, opts, cap_kv)
        # an up/down run pools its first rising leg only (run_level_curve)
        # -- which the figure has to SAY, since its own curve shows both
        updown = sorted({r['name'] for _n, subset, _a, _k, _c, _s
                         in drawn_groups for r in subset if multi_leg(r)})
        if updown and opts.get('split_legs', True):
            agg_caption += ("\nUp/down runs contribute their FIRST RISING "
                            "leg to the mean: " + ', '.join(updown) + ".")
            warn(f"aggregate: {', '.join(updown)} also ran DOWN in "
                 f"voltage -- only the first rising leg joins the mean, "
                 f"since averaging a device's rising and falling visits "
                 f"to a level is the blending the leg view exists to stop")
        if refused:
            # on the figure too: the PNG travels without the console, and
            # a requested mean that is simply absent reads as "none asked
            # for" (`#398`)
            agg_caption += (
                "\nNOT drawn: " + '; '.join(
                    f"{what} ({', '.join(f'{t:g}' for t in t0s)} µm)"
                    for what, t0s in refused)
                + ". Exact-level pooling on the field axis needs one film "
                  "thickness per pool; films of different thickness share "
                  "no field level.")

    scale_notes = []
    # the headings both panels will carry, resolved in ONE place so the
    # window can show the same answer without drawing (`#315`)
    heads = panel_titles(opts, runs)
    arrows = opts.get('arrows', True) and not timeax
    if axl is not None:
        _style_axes(axl, x_label(opts), 'Active area (mm²)')
        _apply_scales(axl, opts, xs_all, ysl_all, scale_notes)
        if arrows:
            _direction_arrows(axl, arrow_paths[0])
        axl.set_title(heads['first'],
                      loc='left', fontweight='bold', fontsize=11)
    if axr is not None:
        _style_axes(axr, x_label(opts),
                'Areal strain  (A − A₀)/A₀  (%)' if pct
                else 'Expansion  A / A₀')
        _apply_scales(axr, opts, xs_all, ysr_all, scale_notes)
        if arrows:
            _direction_arrows(axr, arrow_paths[1])
        axr.set_title(heads['second'],
                      loc='left', fontweight='bold', fontsize=11)
    style_rows = []
    if opts['prepost']:
        style_rows += [('post-ramp snapshot', {'linestyle': '-'}),
                       ('pre-ramp snapshot', {'linestyle': '--'})]
    if split_any:
        style_rows += list(LEG_STYLE_ROWS)
    if had_x:
        style_rows.append(('breakdown (current-confirmed)',
                           {'linestyle': '', 'marker': 'X'}))
    if had_coarse:
        style_rows.append(('breakdown, coarse current sampling',
                           {'linestyle': '', 'marker': 'X',
                            'markerfacecolor': 'white',
                            'markeredgewidth': 1.4}))
    if had_fallback:
        style_rows.append(('breakdown, no reviewed area',
                           {'linestyle': '--'}))
    main_legend = _legend(legend_ax, run_handles, style_rows,
                          handlelength=handle_em)
    # the open/closed key explains the RUN markers, and with the runs
    # hidden there are none on the figure to explain -- the same rule that
    # keeps it out of current/power mode (`#267`), reached from the other
    # direction. The window greys the box to say so rather than leaving a
    # tick that does nothing.
    if opts.get('marker_key', True) and not hide_runs:
        _marker_key(legend_ax, main_legend, lift=agg_support_row)

    if hide_runs:
        # The whole first block below describes per-run markers, bands and
        # breakdown X marks, none of which was drawn. Left standing it
        # would be a caption about a figure that is not there.
        cap = ("Per-run curves HIDDEN — this panel carries the aggregate "
               "means alone; every contributing run is still in the tidy "
               "CSV beside this figure, with its group.\n"
               + _x_axis_caption(opts, runs))
    elif timeax:
        cap = ("Points = one per snapshot, joined in the order taken"
               + (" (triangle-up on a rising leg, triangle-down on a "
                  "falling one)" if split_any else "") + ".  "
               "Open markers = hand-traced boundary (outer toe, ±1%); "
               "filled = machine half-height convention"
               + (", bands ±2% machine / ±1% traced" if budget_bands
                  else "") + ".\n"
               "X = current-confirmed breakdown (recomputed, 2026-08-05 "
               "semantics).  " + _time_axis_caption(runs))
    else:
        # The band is +-p of the AREA. Under strain percent the panel's
        # numbers are strain points, so "+-2%" there could be read as
        # "+-2 points everywhere", which is true only at rest. The note
        # rides on the caption's SECOND line, not the first: the first was
        # already wider than the figure (see CAPTION_LINE_MAX's comment)
        # and a clause appended to it was cut off. Every line is wrapped
        # to the figure's width since 2026-10-06, so this one wraps too
        # rather than running off the edge at screen dpi, where it ended
        # at 1.00 of the width. Only when the strain panel is really
        # drawn, with bands on.
        strain_note = ''
        if budget_bands and pct and axr is not None:
            strain_note = (
                f"  Strain bands = ±{MACHINE_BAND_PCT:g}% machine / "
                f"±{TRACED_BAND_PCT:g}% traced of the AREA: "
                f"±{MACHINE_BAND_PCT:g} / ±{TRACED_BAND_PCT:g} points at "
                f"0 % strain, wider as strain grows.")
        cap = ("Points = per-level pre/post snapshot pair"
               + (" (post solid, pre dashed)" if opts['prepost']
                  else " mean") + ".  "
               "Open markers = hand-traced boundary (outer toe, ±1%); "
               "filled = machine half-height convention; a level mixing "
               "the two plots its machine member(s) only (conventions "
               "differ +5.5% area, never averaged)"
               + (", bands ±2% machine / ±1% traced" if budget_bands
                  else "") + ".\n"
               "X = current-confirmed breakdown (recomputed, 2026-08-05 "
               "semantics).  " + _x_axis_caption(opts, runs) + strain_note)
        if split_any:
            cap += _legs_caption(opts)
    if group_caption is not None:
        # `#373`: a grouped figure's caption is composed for the width it
        # finds, and its strip is always measured (bottom None), so a
        # wrapped line never sits under the axes. _place_caption wraps the
        # head and tail lines like any other caption's.
        head = cap
        tail = (agg_caption
                + _estimator_caption(runs)
                + _cadence_caption(cadence_notes)
                + _scale_caption(scale_notes))
        _set_caption(fig, lambda fits: head + group_caption(fits) + tail,
                     None)
        return fig
    cap = (cap
           + agg_caption
           + _estimator_caption(runs)
           + _cadence_caption(cadence_notes)
           + _scale_caption(scale_notes))
    # The caption grew three lines under the aggregate and the fixed 5%
    # strip clipped the last of them. Reserved space follows the LINE
    # COUNT -- but only when the aggregate, the time axis or a leg-split
    # run adds lines, so every figure that existed before `#268` still
    # lays out to the same pixels (the window/CLI byte-identity test
    # would catch it if it did not). A line too wide for the figure is
    # wrapped, and the strip grows with it (_place_caption, 2026-10-06).
    bottom = 0.05
    if opts.get('aggregate') or timeax or split_any:
        bottom = min(0.025 + 0.025 * (cap.count('\n') + 1), 0.30)
    _set_caption(fig, cap, bottom)
    return fig


def area_axes(fig, opts):
    """-> (left, right) axes for the area figure; either is None when
    `#270` switched that panel off.

    A single chosen panel is created as the figure's ONLY axes, so it
    fills the canvas -- not a two-column grid with one column blanked,
    which would leave the survivor squeezed into half a figure next to
    white space. Every caller that makes area axes goes through here so
    the window, the CLI and the PNG cannot disagree about the layout."""
    which = opts.get('subplots', 'both')
    if which == 'first':
        return fig.subplots(), None
    if which == 'second':
        return None, fig.subplots()
    return tuple(fig.subplots(1, 2))


def _savefig(fig, path, opts):
    """THE savefig every write path goes through (`#314`) -> path.

    One call site for the format and the dpi, for the same reason FIGSIZE
    is one table: the CLI's figure, the window's Export and the direct
    figure_* helpers must not be able to disagree about what they wrote.

    DPI IS NOT PASSED FOR SVG, and that is not an oversight -- the SVG
    backend pins the figure to 72 dpi and scales in user units, so a dpi
    there could only ever be a number that did nothing. The window greys
    the field to say so; opts still CARRIES the value, so switching back
    to PNG (or overriding a spec with --format png) renders at the dpi
    that was chosen rather than at a silently restored default."""
    fmt = opts.get('fmt', DEFAULT_FORMAT)
    if fmt == 'svg':
        import matplotlib
        # both pins are reproducibility, not cosmetics -- see SVG_HASHSALT
        with matplotlib.rc_context({'svg.hashsalt': SVG_HASHSALT}):
            fig.savefig(path, format='svg', metadata={'Date': None})
        return path
    fig.savefig(path, format=fmt, dpi=opts.get('dpi', DEFAULT_DPI))
    return path


def figure_area(runs, opts, path, warn=lambda m: None):
    """The area figure at opts' format and dpi (kept for direct
    callers/tests). Same drawing as the window -- see draw_area."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=FIGSIZE['area'])
    axl, axr = area_axes(fig, opts)
    draw_area(fig, axl, axr, runs, opts, warn)
    _savefig(fig, path, opts)
    plt.close(fig)
    return path


def run_ua_median(run):
    """The run's median measured_uA — the same >=5-parseable-rows rule as
    breakdown_flags — or None. The per-era instrument zero this
    estimates is the ONLY current reference the suite trusts; absolute
    µA is documented untrustworthy (07-29 idles at −16 µA)."""
    uas = [r['ua'] for r in run['rows'] if r['ua'] is not None]
    return _median(uas) if len(uas) >= 5 else None


def power_mw(r, med):
    """|kV × (µA − run median)| in mW — the DEVICE's dissipation, not the
    instrument's. The raw |kV × µA| product multiplied the era's zero
    error by the voltage axis: on the P3 campaign it manufactured a
    near-perfect 155-160 mW line at 10 kV on runs whose true deviation
    never left ~5 µA of baseline, and it rank-INVERTED real dissipation
    (audit 2026-08-05). With no median (<5 parseable rows) the raw
    product is kept and the caller must say so."""
    if r['ua'] is None or r['kv'] is None:
        return None
    ua = r['ua'] - med if med is not None else r['ua']
    return abs(r['kv'] * ua)


def draw_signal(fig, ax, runs, opts, warn=lambda m: None):
    """current / power vs kV (or vs area with --vs-area), per snapshot,
    into an ALREADY-CREATED axis. Power is offset-corrected per run (see
    power_mw). The window and the CLI both draw through here (`#223`)."""
    from matplotlib.lines import Line2D

    power = opts['mode'] == 'power'

    def yval(r, med):
        if r['ua'] is None:
            return None
        if power:
            return power_mw(r, med)
        return r['ua']

    def xval(r):
        return x_value(r, opts)

    timeax = opts.get('x') == 'time'
    fieldax = opts.get('x') in FIELD_AXES        # `#398`
    split_any = False
    arrow_paths = []
    run_handles = []
    had_x = had_adv = had_coarse = False
    raw_power = []
    cadence_notes = []
    xs_all, ys_all = [], []          # what got plotted (`#263`)
    for run in runs:
        color = run['color']
        med = run_ua_median(run)
        if power and med is None:
            raw_power.append(run['name'])
            warn(f"{run['name']}: fewer than 5 parseable µA rows — no "
                 f"median baseline, power is the RAW |kV × µA| product "
                 f"(instrument offset included)")
        pts = [(xval(r), yval(r, med), r) for r in run['rows']
               if xval(r) is not None and yval(r, med) is not None]
        if not pts:
            warn(f"{run['name']}: no plottable points in this mode -- "
                 f"omitted from the figure")
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if opts.get('split_legs', True) and multi_leg(run):
            # 2026-09-23: already drawn in travel order, but on the kV
            # axis the way down retraced the way up in one colour with
            # nothing to tell them apart. One line per leg, turning at
            # the peak, each snapshot marked by its leg's triangle.
            split_any = True
            for lx, ly in _signal_legs(pts):
                ax.plot(lx, ly, '-', color=color, linewidth=1.4,
                        alpha=0.85, zorder=3)
                if not timeax:
                    arrow_paths.append((lx, ly, color))
            for leg in ('rise', 'fall', ''):
                sel = [(x, y) for x, y, r in pts if r['leg'] == leg]
                if sel:
                    ax.plot([s[0] for s in sel], [s[1] for s in sel],
                            LEG_MARKERS.get(leg, 'o'), color=color,
                            markersize=4.5 if leg else 3, zorder=4)
        else:
            ax.plot(xs, ys, '-', color=color, linewidth=1.4, alpha=0.85,
                    zorder=3)
            ax.plot(xs, ys, 'o', color=color, markersize=3, zorder=4)
        xs_all += xs
        ys_all += ys
        if not power and not opts['vs_area']:
            uas = [r['ua'] for r in run['rows'] if r['ua'] is not None]
            if len(uas) >= 5:
                med_line = _median(uas)
                ax.axhline(med_line, color=color, linestyle=':',
                           linewidth=0.9, alpha=0.6, zorder=2)
                ys_all.append(med_line)
        if opts['breakdown']:
            coarse = coarse_cadence(run, opts)
            xpts = [(x, y) for x, y, r in pts if r['index'] in run['flags']]
            _cross_marks(ax, xpts, color, coarse)
            had_x = had_x or bool(xpts)
            had_coarse = had_coarse or (coarse and bool(xpts))
            if coarse and xpts:
                cadence_notes.append(_cadence_note(run))
                warn(f"{run['name']}: current sampled every "
                     f"{run['cadence_s']:.1f} s "
                     f"({run.get('cadence_src', '?')}), slower than "
                     f"{CADENCE_COARSE_S:g} s -- a breakdown's onset can "
                     f"be anywhere in the interval before the flagged "
                     f"snapshot, so its X is drawn hollow")
            drawn_idx = {r['index'] for _, _, r in pts}
            missing = sorted(i for i in run['flags'] if i not in drawn_idx)
            if missing:
                warn(f"{run['name']}: confirmed breakdown row(s) "
                     f"{missing} lack a plottable coordinate in this mode "
                     f"-- X omitted (see the tidy CSV / current-vs-kV)")
            for x, y, r in pts:
                if r['index'] in run['advis']:
                    ax.plot([x], [y], 'D', markersize=6, color=color,
                            markerfacecolor='white', markeredgewidth=1.2,
                            zorder=5)
                    had_adv = True
        run_handles.append(Line2D([], [], color=color, label=run['name']))

    ylabel = ('|kV × (µA − run median)|  (mW)' if power
              else 'Measured current (µA)')
    _style_axes(ax, x_label(opts), ylabel)
    scale_notes = []
    _apply_scales(ax, opts, xs_all, ys_all, scale_notes)
    if opts.get('arrows', True):
        _direction_arrows(ax, arrow_paths)
    ax.set_title(panel_titles(opts, runs)['first'],
                 loc='left', fontweight='bold', fontsize=11)
    style_rows = []
    if split_any:
        style_rows += list(LEG_STYLE_ROWS)
    if had_x:
        style_rows.append(('breakdown (current-confirmed)',
                           {'linestyle': '', 'marker': 'X'}))
    if had_coarse:
        style_rows.append(('breakdown, coarse current sampling',
                           {'linestyle': '', 'marker': 'X',
                            'markerfacecolor': 'white',
                            'markeredgewidth': 1.4}))
    if had_adv:
        style_rows.append(('transient / advisory',
                           {'linestyle': '', 'marker': 'D',
                            'markerfacecolor': 'white'}))
    if not power and not opts['vs_area']:
        style_rows.append(('run-median baseline', {'linestyle': ':'}))
    _legend(ax, run_handles, style_rows)
    cap = ("One point per snapshot, CSV order.  X = current-confirmed "
           "breakdown, open diamond = advisory (both recomputed).\n"
           + ("Power uses the run-median-corrected current — the raw "
              "product was ~100% instrument zero × kV on the P3 era "
              "(−16 µA idle)."
              + (f"  RAW product (no median): "
                 f"{', '.join(raw_power)}." if raw_power else "")
              if power else
              "Currents carry each era's instrument offset "
              "(07-29 ≈ −16 µA idle).")
           # --vs-area puts areas on the x axis: a kept old-estimator
           # run is named here as it is on the area figure
           + (_estimator_caption(runs) if opts['vs_area'] else '')
           + (("\n" + _time_axis_caption(runs)) if timeax else "")
           + (("\n" + _x_axis_caption(opts, runs)) if fieldax else "")
           + (_legs_caption(opts, 'one snapshot') if split_any else "")
           + _cadence_caption(cadence_notes)
           + _scale_caption(scale_notes))
    # a fixed 5% strip, as ever, unless the time or field axis or a
    # leg-split run added caption lines, which would otherwise be clipped,
    # or a line had to be wrapped to the figure's width (_place_caption)
    bottom = 0.05
    if timeax or fieldax or split_any:
        bottom = min(0.025 + 0.025 * (cap.count('\n') + 1), 0.30)
    _set_caption(fig, cap, bottom)
    return fig


def _signal_legs(pts):
    """[(x, y, row)] in CSV order -> [(xs, ys)], one per leg (consecutive
    rows sharing a leg and cycle), each after the first starting at the
    previous leg's last point so the line turns where the voltage did."""
    out, prev, grp = [], None, []
    for p in pts:
        r = p[2]
        if grp and (r['leg'], r['cycle']) != (grp[-1][2]['leg'],
                                              grp[-1][2]['cycle']):
            seq = ([prev] if prev is not None else []) + grp
            out.append(([q[0] for q in seq], [q[1] for q in seq]))
            prev, grp = grp[-1], []
        grp.append(p)
    if grp:
        seq = ([prev] if prev is not None else []) + grp
        out.append(([q[0] for q in seq], [q[1] for q in seq]))
    return out


def figure_signal(runs, opts, path, warn=lambda m: None):
    """The current/power figure at opts' format and dpi (kept for direct
    callers/tests). Same drawing as the window -- see draw_signal."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=FIGSIZE[opts['mode']])
    draw_signal(fig, ax, runs, opts, warn)
    _savefig(fig, path, opts)
    plt.close(fig)
    return path


def draw(fig, runs, opts, warn=lambda m: None):
    """Draw the whole figure for opts['mode'] into a bare Figure, creating
    the axes it needs. THE entry point for anything that renders: the
    window's live canvas calls it on every toggle, and save_figure() calls
    it for the PNG, so what you see on screen is what lands in the file."""
    # a figure reused for a new draw must not keep the last one's caption;
    # draw_area / draw_signal hold this one's
    setattr(fig, _CAPTION_ATTR, None)
    if opts['mode'] == 'area':
        axl, axr = area_axes(fig, opts)
        return draw_area(fig, axl, axr, runs, opts, warn)
    return draw_signal(fig, fig.subplots(), runs, opts, warn)


def save_figure(runs, opts, path, warn=lambda m: None):
    """Write the figure at the canonical geometry, WITHOUT pyplot.

    figure_area/figure_signal force the Agg backend, which in a process
    that already owns a live Tk canvas means switching backends underneath
    it. This path never imports pyplot at all, so the window can export
    while its preview stays alive -- and headless callers get the same
    bytes, because it is the same Figure, the same draw() and the same
    _savefig (which is where the format and the dpi are decided, for both
    of them). An SVG path is fine on the Agg canvas: savefig swaps in the
    backend the FORMAT names, which is a different thing from
    matplotlib.use() replacing the process's."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=FIGSIZE[opts['mode']])
    FigureCanvasAgg(fig)
    draw(fig, runs, opts, warn)
    return _savefig(fig, path, opts)


# ---------------------------------------------------------------------------
# tidy CSV
# ---------------------------------------------------------------------------

TIDY_COLS = ['run', 'group', 'snapshot', 'nominal_kV', 'elapsed_s',
             'film_thickness_um', 'field_V_per_um',
             'phase', 'tag', 'leg', 'cycle',
             'area_mm2', 'convention', 'area_estimator', 'opencv_version',
             'numpy_version', 'ray_win_hi', 'disc_fit_r_max',
             'expansion_A_A0',
             'measured_uA', 'power_mW', 'traced', 'method', 'conf',
             'user_reviewed', 'breakdown_confirmed', 'breakdown_advisory',
             'saved_breakdown_brand', 'notes']


def write_tidy(runs, path, groups=()):
    """Per-snapshot tidy export. EVERY row of every run is written --
    including 'post-breakdown'-annotated ones (the P3_5 rule). Runs kept
    despite a suspect pre-scale-fix era ('suspect_kept', current/power
    modes) get their area columns blanked so bug-era areas cannot leak
    into downstream analysis; so do runs kept despite old-estimator
    areas ('old_estimator_hidden', the same two modes; 2026-10-02).

    'convention' names each area's edge definition ('half-height'
    machine / 'outer-toe' hand trace; +5.2-5.7% apart — never compare
    absolute mm² across them), and power_mW is the run-median-corrected
    product (see power_mw): both audit 2026-08-05.

    'area_estimator' (2026-10-02) says which area estimator wrote each
    'disc-fit' area: the run's `area_estimator` stamp from setup.txt,
    1 when the run has none (the ellipse), 2 the common-ray ratio; blank
    on every other row (a trace, a patch tier and a 'resting' row mean
    the same under both). It is the column a mixed figure drawn with
    --allow-old-estimator is separated by afterwards.

    'opencv_version' / 'numpy_version' (2026-10-03) are the library
    versions Edge Review's Save stamped beside the estimator (the
    process that wrote the run's machine areas; every corpus figure is
    OpenCV 4.13), on every machine-measured row ('half-height'
    convention) and blank on a hand trace, a row without an area, and
    a run saved before the versions were recorded. Columns rather than
    a header line, so the file stays a plain CSV for csv.DictReader and
    pandas without a comment option.

    'ray_win_hi' / 'disc_fit_r_max' (2026-10-03, owner decision 6) are
    the boundary tracker's window limits the Save stamped beside the
    estimator (se.TRACKER_LIMIT_KEYS): how far out along each ray the
    ink step was searched and the largest ellipse the fit believed, in
    units of the resting radius. The limits are constants that moved
    once under the same estimator version (1.38 -> 1.70 and 1.3 ->
    1.75 on 2026-10-03), so two 'disc-fit' rows can carry the same
    `area_estimator` and still have been measured under different
    windows; these columns say which window each RUN's last
    Detect-and-Save used. They are the run's stamp copied onto its
    rows, not a per-row record (owner decision 6): a review-queue row
    kept from an earlier pass keeps that pass's number under the later
    stamp (se.load_stamp). Filled exactly where 'area_estimator' is (a
    'disc-fit' row with an area), blank elsewhere and throughout a run
    saved before the limits were recorded (with `area_estimator` 2 that
    was the 1.38 / 1.3 window).

    'group' is the operator's grouping (`#313`), blank for a run in no
    group, and it sits SECOND -- beside 'run', because it is the other
    half of the same question. It is in the CSV for the reason the CSV
    exists at all: a figure whose two lines are the CB mean and the P3
    mean cannot be reproduced from a table that does not say which run
    was in which line. Written from the same opts the figure was drawn
    from, so it cannot describe a different grouping than the picture.

    'elapsed_s', 'leg' and 'cycle' (2026-09-23) are DATA columns, written
    for every figure whatever its options: the elapsed-time axis's x, and
    the grouping an up/down run is drawn by (see sweep_legs) -- a figure
    whose rising and falling curves cannot be told apart in its own CSV
    is not reproducible from it.

    'film_thickness_um' and 'field_V_per_um' (2026-10-06, `#398`) are the
    field axis' t0 and x: the thickness the run's fields were divided by,
    and nominal_kV x 1000 / t0 on each row, so a field figure can be
    redrawn from its CSV alone. Filled only when the figure IS a field
    figure, from the t0 it was drawn with (prepare_runs: the figspec, or
    setup.txt as read then), and blank on every other figure, which reads
    no thickness at all. A row with no kV has no field either."""
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(TIDY_COLS)
        for run in runs:
            hide_areas = (run.get('suspect_kept', False)
                          or run.get('old_estimator_hidden', False))
            group = run_group(run, groups) or ''
            med = run_ua_median(run)
            estimator = run.get('estimator') or 1
            libs = run.get('lib_versions') or {}
            limits = run.get('tracker_limits') or {}
            t0 = run.get('t0_um')
            for r in run['rows']:
                area = None if hide_areas else r['area_mm2']
                conv = ('' if area is None
                        else 'outer-toe' if r['traced']
                        else 'half-height' if r['method'] else '')
                est = (estimator if area is not None
                       and r['method'] == 'disc-fit' else '')
                machine = conv == 'half-height'
                cv_ver = libs.get('opencv_version', '') if machine else ''
                np_ver = libs.get('numpy_version', '') if machine else ''
                # the tracker's window limits ride exactly where the
                # estimator does: a 'disc-fit' row with an area
                win_hi, r_max = ('', '')
                if est != '':
                    win_hi, r_max = (
                        '' if limits.get(k) is None else f"{limits[k]:g}"
                        for k in se.TRACKER_LIMIT_KEYS)
                exp = (area / run['a0'] if area and run['a0'] else '')
                pw = power_mw(r, med)
                t = r.get('elapsed_s')
                e = r.get('field') if t0 else None
                w.writerow([
                    run['name'], group, r['snapshot'],
                    '' if r['kv'] is None else r['kv'],
                    '' if t is None else round(t, 3),
                    '' if not t0 else t0,
                    '' if e is None else round(e, 4),
                    r['phase'], r['tag'],
                    r.get('leg', ''),
                    '' if r.get('cycle') is None else r['cycle'],
                    '' if area is None else area,
                    conv, est, cv_ver, np_ver, win_hi, r_max,
                    f"{exp:.4f}" if exp != '' else '',
                    '' if r['ua'] is None else r['ua'],
                    f"{pw:.3f}" if pw is not None else '',
                    r['traced'], r['method'],
                    '' if r['conf'] is None else r['conf'],
                    r['user'],
                    run['flags'].get(r['index'], ''),
                    run['advis'].get(r['index'], ''),
                    r['index'] in run['saved_brand'],
                    r['notes'],
                ])
    return path


# ---------------------------------------------------------------------------
# the shared front-end surface: options, output paths, run preparation
#
# Everything below is what the CLI's main() and the window (`#223`) BOTH go
# through. Keeping it here rather than in the window is the whole point:
# a run the command line excludes is excluded in the window too, for the
# same reason and with the same warning text, and neither front end can
# grow its own idea of what a figure's options or filenames are.
#
# ---------------------------------------------------------------------------
# ADDING A NEW OPTION: NINE landing sites, and seven of them fail SILENTLY
#
# It was five until `#314`. Two more surfaced there, and neither was a
# special case -- each is the general form of a category the original five
# happened not to cover:
#
#   6. output_paths(). SILENT. Only matters for an option that changes an
#      ARTIFACT NAME rather than the figure's content; `fmt` was the first.
#      Miss it and the file is written with the wrong extension.
#   7. sldea_plot_gui.NUMERIC_OPTIONS. SILENT. The remembered-options
#      cleaner validated enums and flags only, because every remembered
#      option had been one or the other; `dpi` was the first NUMBER. Miss
#      it and a corrupt value in the options file survives a round trip
#      instead of being rejected.
#
# ...and two more surfaced in `#313`, whose `groups` is the first option
# that is neither a flag, a name nor a number but a STRUCTURE -- a list of
# (name, runs) pairs naming particular run directories:
#
#   8. _parse_argv()'s flag tables. SILENT for a REPEATABLE option. The
#      parser was written so that "later duplicate valued flags win"
#      (`--out a --out b` used to send 'b' run-hunting), which is right
#      for every option that names one value and silently wrong for
#      --group, where the second occurrence is a second GROUP. An option
#      that can be given more than once needs _REPEATED_FLAGS, or the
#      figure quietly loses every group but the last.
#   9. write_tidy()'s TIDY_COLS. SILENT. The tidy CSV is the figure's
#      evidence, so an option that changes WHICH ROWS BELONG TOGETHER --
#      as against how they are drawn -- has to appear in it, or the
#      figure cannot be reproduced from its own data. `groups` is the
#      first such option: without the column, a two-line CB-vs-P3 figure
#      exports a CSV that cannot say which run was in which line.
#      (`subplots` is the counter-example that proves the rule and is
#      deliberately NOT in the CSV: it changes the layout, not the
#      grouping of the numbers.)
#
# A structured option also lands on site 4 in a way a flag does not: the
# window's cleaner needs a checker of its own for it (STRUCTURED_OPTIONS,
# beside ENUM_OPTIONS and NUMERIC_OPTIONS), and the value must survive a
# JSON round trip through both the options file and the figspec -- which
# is why check_groups coerces lists back to tuples instead of refusing
# them. Nothing warns if it does not; the groups simply vanish on reload.
#
# The lesson generalises: the count is not the point. Before adding an
# option, ask which CATEGORY it belongs to -- flag, name, number, artifact
# name -- and whether that category has ever existed here before. A first
# of its kind will find a site this list does not have yet.
#
# Every option currently here is plumbed correctly, so nothing is broken --
# this is a map, written down because the next option through this seam
# (`#268`'s cross-run aggregate) would hit two of the silent ones on its
# first day. Miss a site and there is no error, just a control that does
# nothing -- or worse, a "re-render" of a different figure.
#
# `#268` has since been through: `aggregate` and `aggregate_exact` landed
# in all five, and the map held. Site 5 was the one that nearly bit --
# `aggregate` has to reach BOTH area panels and the caption, and
# `aggregate_exact` is read only by aggregate_levels, so a half-consumed
# version of either draws a figure that looks perfectly finished.
#
# `#313` has been through, and it is the first option that describes
# neither the drawing nor the file but the DATA's own structure:
# `groups` says which runs belong together, so it reaches sites 1-5 like
# any option, site 8 because it is repeatable on the command line, and
# site 9 because the tidy CSV has to carry it. `aggregate_only` travelled
# with it as an ordinary flag and hit only the familiar five -- a useful
# contrast, since the two shipped together and only one of them was new
# in kind.
#
# `#314` (`fmt` and `dpi`) has been through too, and it is the first
# option pair that does NOT describe the drawing -- it describes the file.
# That moves site 5: nothing in draw_area/draw_signal reads either one,
# and the code that does is _savefig plus output_paths' extension. Two
# extra sites came with that, both silent, both worth the next person's
# attention: output_paths (an SVG written to a .png name opens in
# nothing), and site 4's cleaner, which validated ENUM and BOOL values
# only -- `dpi` is the first NUMBER remembered, and an unvalidated one
# out of a hand-edited config would have reached make_opts.
#
# `strain_pct` has been through (2026-08-13), and it is the first option
# that changes the UNITS of a quantity the figure already drew rather than
# adding, removing or restyling anything. That put its weight in site 5
# and nowhere surprising: seven places divided by A0 inline, so the
# conversion went into one function (norm_y) that all of them and the
# aggregate call, because a units switch applied to six of seven draws a
# figure that looks perfectly finished. Two consequences worth keeping:
# the panel HEADING and the axis label both had to follow, since 40 and
# 1.4 are the same measurement and only the label says which; and the
# tidy CSV deliberately did NOT follow -- its expansion column stays A/A0
# so a saved CSV means one thing regardless of how the figure was drawn,
# which is the opposite of the `#313` decision to put groups in the CSV,
# and for the same underlying reason (the CSV records the DATA, not the
# drawing).
#
# `group_materials` (`#373`) has been through, and it is the first option
# that is DERIVED rather than chosen: nobody types it, it is what the runs
# of a group recorded in setup.txt at the moment the group was formed. So
# its weight is in WHEN it is computed, not where: at a grouping ACTION
# (the window's seed buttons and Assign, the CLI's --group in main()) and
# never in site 5's drawing code, or a setup.txt edit would restyle a
# figure on its next --from-spec. It rides site 2 without a flag of its
# own (_cli_opts inherits it from a spec with the groups and drops it
# when --group replaces them), reaches site 4 as a STRUCTURED option with
# its own checker, and stays out of the tidy CSV (site 9): the group
# column already says which run is in which line, and a line style is
# drawing, not data.
#
# `x='field'` and `film_thickness` (`#398`) have been through. The axis
# is a new NAME for an existing option, so it reached sites 2-4 by the
# enum it joined, and its weight is in site 5: the kV axis rescaled per
# run (run['x_scale']), at every place that turns a level's kV into a
# position, the aggregate's grid key and its cap included, and in the
# unit the captions and warnings quote positions in (x_unit). The
# thickness is DERIVED like group_materials, but WHEN differs: its moment
# is the figure being WRITTEN (export, from the runs prepare_runs
# resolved), since a t0 belongs to a run and not to a grouping action. It
# rides site 2 without a flag (_cli_opts inherits a spec's), is NOT
# remembered by the window (site 4: a stale t0 would be a wrong number,
# not an inert label, so the window keeps only a spec's, for the window
# opened from it, and reads every other run's setup.txt at each redraw),
# and DOES reach the tidy CSV (site 9), as the elapsed-time axis' x did:
# a field figure's x is not recoverable from its kV column alone.
#
#   1. make_opts() below -- the keyword, its default, any validation.
#      MISSING THIS IS LOUD: every other site raises TypeError.
#
#   2. _cli_opts()'s hand-written val()/on()/off() table. SILENT. The flag
#      does nothing. Worse, `--from-spec` then fails in a way that looks
#      like success: build_figspec() stores `dict(opts)` WHOLESALE, so the
#      spec records the new option faithfully, but _cli_opts() rebuilds the
#      dict from its own enumerated list and drops any key it does not know
#      -- returning err=None. Measured 2026-08-09:
#
#          spec_opts['sem_band'] = True
#          out, err = _cli_opts([], {}, spec_opts)
#          # err is None and 'sem_band' is not in out,
#          # while a known key ('logy') round-trips fine
#
#      That is precisely the failure load_figspec()'s docstring exists to
#      prevent ("a figure that claims to be a re-render and is not"), and
#      its validation cannot catch it -- the spec is perfectly well-formed.
#
#   3. The window: widget, Tk variable, and current_opts()
#      (sldea_plot_gui.py). SILENT -- the option ends up CLI-only. The
#      docstring there records the `--logy --gui` bug this already caused.
#
#   4. sldea_plot_gui.REMEMBERED, plus ENUM_OPTIONS if the value is a NAME
#      rather than a flag. SILENT: the option works, but is forgotten
#      between sessions, inconsistently with every other control.
#
#   5. The drawing code that reads opts[...]. Silent if the option is only
#      half-consumed -- read by one panel and not the other.
#
# A cheap guard for site 2, for whoever is next in here: assert that the
# keys make_opts() produces are exactly the keys _cli_opts() rebuilds, so
# the table cannot drift from the signature without a test failing.
# ---------------------------------------------------------------------------

def default_stem(mode):
    """The output stem when nobody chose one."""
    return f"sldea_plot_{mode}"


def check_dpi(dpi):
    """-> (the dpi as an int, None) or (None, the CLI's own error message).

    Its own function because two callers need the identical answer:
    make_opts (so the CLI and the window refuse a typo in the same words)
    and the window's remembered-options cleaner (so a hand-edited config
    cannot smuggle a 30000 past the range the window itself enforces).

    None means 'unset' and yields the default -- a caller that has nothing
    to say is not the same as one asking for a bad number."""
    if dpi is None or (isinstance(dpi, str) and not dpi.strip()):
        return DEFAULT_DPI, None
    if isinstance(dpi, bool):               # True is not a resolution
        return None, f"--dpi must be a whole number ({DPI_MIN}-{DPI_MAX})"
    try:
        n = int(str(dpi).strip())
    except (TypeError, ValueError):
        return None, (f"--dpi {dpi} is not a whole number "
                      f"({DPI_MIN}-{DPI_MAX})")
    if not DPI_MIN <= n <= DPI_MAX:
        return None, (f"--dpi {n} out of range ({DPI_MIN}-{DPI_MAX}); "
                      f"the default is {DEFAULT_DPI}")
    return n, None


def make_opts(mode='area', vs_area=False, prepost=False, mean=False,
              bands=True, breakdown=True, title=None,
              logx=False, logy=False, marker_key=True,
              title_first=None, title_second=None, subplots='both',
              cadence_guard=False, aggregate=False,
              aggregate_exact=False, groups=(), aggregate_only=False,
              fmt=DEFAULT_FORMAT, dpi=None, strain_pct=False,
              x='kv', split_legs=True, arrows=True, group_materials=(),
              film_thickness=()):
    """-> (opts dict, error message or None).

    The CLI builds this from its flags and the window from its tick boxes,
    so an illegal combination is refused identically in both. Error strings
    are the CLI's own wording -- main() prints them verbatim.

    Every key added after `#223` defaults to the behaviour that existed
    before it, so an options dict built with no arguments still describes
    the original figure -- with ONE deliberate exception, `marker_key`,
    which `#267` asked for on by default (--no-marker-key restores the
    older figure exactly, and the test suite proves that byte for byte).

    `fmt`/`dpi` (`#314`) are the two that describe the FILE rather than
    the drawing. They live here with the rest because the figspec records
    what make_opts produced, and a spec that did not say png-or-svg at
    what resolution would re-render something other than what it names.
    The key is `fmt` rather than `format` (the flag is --format): a
    parameter called `format` shadows the builtin in every signature it
    passes through.

    `groups` (`#313`) is the first option that is neither a flag, a name
    nor a number -- see check_groups for the canonical form and why it is
    ordered rather than sorted. It is NOT refused outside area mode the
    way `aggregate` is: an operator's grouping of their own runs is not
    made wrong by looking at a current plot, and it draws nothing there
    because nothing outside the aggregate reads it. `aggregate_only` is
    refused with the aggregate off, though, because there it would empty
    the figure rather than tidy it.

    `group_materials` (`#373`) travels with `groups`: the one material
    each group's runs recorded when it was formed, which picks its line
    style (check_group_materials, assign_group_styles). Entries naming no
    group are dropped and the rest are put in the groups' order, so the
    stored value is canonical and a JSON round trip compares equal.

    `x`, `split_legs` and `arrows` (2026-09-23): the x axis (X_AXES), and
    how a run whose voltage also FELL is drawn -- leg by leg with
    triangle-up/-down markers, and arrowheads in the direction of travel.
    The last two default ON, the second deliberate exception after
    `marker_key`: averaging a device's rising and falling visits to a
    level is not a figure anyone asked for, and a single sweep has one
    leg, so neither changes one byte of it (the test suite proves that
    against the pre-change engine, and that --merge-legs --no-arrows
    reproduces the old up/down figure too). --x time refuses the options
    that pool snapshots on the kV axis, and --vs-area, the other x switch.

    `x='field'` (`#398`) is the kV axis rescaled per run, so it keeps every
    kV option and refuses only --vs-area. `film_thickness` travels with it:
    the t0 each run's field was divided by when the figure was made
    (check_film_thickness), written by export and read back from a spec,
    never typed. Empty by default, which is a figure that reads every t0
    from setup.txt."""
    if fmt not in FORMATS:
        return None, f"unknown --format {fmt} ({' | '.join(FORMATS)})"
    dpi, dpi_err = check_dpi(dpi)
    if dpi_err:
        return None, dpi_err
    if mode not in MODES:
        return None, f"unknown --mode {mode} (area | current | power)"
    if vs_area and mode == 'area':
        return None, '--vs-area applies to current/power modes only'
    subplots = subplots or 'both'
    if subplots not in SUBPLOTS:
        return None, (f"unknown --subplots {subplots} "
                      f"(both | first | second)")
    if subplots == 'second' and mode != 'area':
        # 'first' in a single-panel mode is a harmless no-op (it names the
        # only panel), but 'second' would ask for a panel that does not
        # exist -- that is a mistake, not a preference
        return None, ('--subplots second applies to area mode only '
                      '(current/power draw a single panel)')
    if aggregate and mode != 'area':
        # REFUSED rather than ignored (`#268`). The aggregate averages
        # PER-LEVEL curves, and current/power plot one point per snapshot
        # with no level structure to pool -- a flag that quietly did
        # nothing here is the silent failure the landing-site map above
        # exists to prevent.
        return None, ('--aggregate applies to area mode only '
                      '(current/power draw one point per snapshot, '
                      'not one per level)')
    groups, groups_err = check_groups(groups)
    if groups_err:
        return None, groups_err
    group_materials, mats_err = check_group_materials(group_materials)
    if mats_err:
        return None, mats_err
    mats = {n.casefold(): m for n, m in group_materials}
    group_materials = [[n, mats[n.casefold()]] for n, _m in groups
                       if n.casefold() in mats]
    film_thickness, thick_err = check_film_thickness(film_thickness)
    if thick_err:
        return None, thick_err
    if aggregate_only and not aggregate:
        # REFUSED, not ignored, and this is the one combination where the
        # difference matters: "hide the runs" with nothing to replace
        # them is an EMPTY figure, which no operator ever wants and which
        # a silently-ignored flag would hand them anyway on the next
        # --from-spec.
        return None, ('--aggregate-only needs --aggregate (it hides the '
                      'per-run curves in favour of the aggregate; with no '
                      'aggregate there would be nothing left to draw)')
    x = x or 'kv'
    if x not in X_AXES:
        return None, f"unknown --x {x} ({' | '.join(X_AXES)})"
    if x != 'kv' and vs_area:
        # REFUSED, for the reason `#268` refused the aggregate outside
        # area mode: a flag that silently did nothing would re-render as
        # a different figure on the next --from-spec
        return None, (f'--x {x} and --vs-area both choose the x axis '
                      f'-- pick one')
    if x == 'time':
        # ...and so is everything that pools snapshots by kV level, which
        # the field axis keeps (it is the kV axis rescaled per run)
        if prepost or mean:
            return None, ('--prepost and --mean pool each level\'s '
                          'snapshots on the kV axis; with --x time every '
                          'snapshot is already its own point')
        if aggregate:
            return None, ('--aggregate pools runs on a common kV grid, '
                          'which has no meaning against --x time')
    return {'mode': mode, 'vs_area': bool(vs_area),
            'prepost': bool(prepost), 'mean': bool(mean),
            'bands': bool(bands), 'breakdown': bool(breakdown),
            'title': title or None,
            'logx': bool(logx), 'logy': bool(logy),
            'marker_key': bool(marker_key),
            'title_first': title_first or None,
            'title_second': title_second or None,
            'subplots': subplots,
            'cadence_guard': bool(cadence_guard),
            'aggregate': bool(aggregate),
            'aggregate_exact': bool(aggregate_exact),
            'groups': groups,
            'group_materials': group_materials,
            'film_thickness': film_thickness,
            'aggregate_only': bool(aggregate_only),
            'strain_pct': bool(strain_pct),
            'x': x, 'split_legs': bool(split_legs), 'arrows': bool(arrows),
            'fmt': fmt, 'dpi': dpi}, None


def needs_areas(opts):
    """True when this figure reads reviewed areas -- area mode, or an area
    x axis. Current/power vs kV work on RAW runs, which is the distinction
    the window has to surface (`#223`: it was buried in --help)."""
    return opts['mode'] == 'area' or opts['vs_area']


def output_paths(out_dir, stem, mode, fmt=DEFAULT_FORMAT):
    """-> (image_path, csv_path).

    The tidy CSV is derived from the image's stem and written beside it,
    and that is not a convenience: the per-snapshot CSV is the figure's
    evidence, and a figure that cannot be traced back to its numbers is not
    citable (`#223`). Derived in ONE place so no caller can drift.

    `fmt` only ever moves the IMAGE's extension (`#314`) -- the CSV and the
    figspec are named off the same stem whichever format was picked, so a
    figure's three files stay a set and an operator who exported both an
    SVG and a PNG of one figure does not end up with two rival CSVs."""
    stem = (stem or '').strip() or default_stem(mode)
    return (os.path.join(out_dir, f"{stem}.{fmt}"),
            os.path.join(out_dir, stem + '.csv'))


# ---------------------------------------------------------------------------
# the figspec sidecar (`#273`)
#
# A PNG travels; the command line that made it does not. The figspec is the
# third file every export writes: the exact options, the run directories
# that were actually plotted, and the versions that plotted them -- enough
# to re-render the figure, and enough to say what a figure in a slide deck
# came from six months later. JSON beside the PNG rather than PNG metadata
# so it is greppable, diffable and survives a crop.
# ---------------------------------------------------------------------------

SPEC_VERSION = 1        # the figspec FORMAT version, not the app's


def figspec_path(img_path):
    """The spec that belongs to an exported figure, PNG or SVG. Derived
    from the image in ONE place so no caller can invent a different
    neighbour."""
    return os.path.splitext(img_path)[0] + '.figspec.json'


def _app_version():
    """v<semver>[+<short hash>], or 'unknown' off a checkout. Best effort
    on purpose: provenance is worth recording, but not worth failing an
    export over."""
    try:
        import version
        return version.version_string()
    except Exception:
        return 'unknown'


def build_figspec(runs, opts, stem):
    """-> the spec dict for this figure.

    Runs are stored RESOLVED and absolute, not as the arguments that were
    typed: a bench shortcut ('1') or a parent-of-runs path means something
    different on another machine or on another day, and a spec that
    re-renders a different run is worse than no spec at all."""
    return {
        'spec_version': SPEC_VERSION,
        'tool': 'sldea_plot',
        'app_version': _app_version(),
        'stem': stem,
        'runs': [os.path.abspath(r['dir']) for r in runs],
        'opts': dict(opts),
    }


def write_figspec(runs, opts, path, stem):
    import json
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(build_figspec(runs, opts, stem), f, indent=2,
                  sort_keys=True)
        f.write('\n')
    return path


def load_figspec(path):
    """-> (spec dict, None) or (None, error message the CLI prints).

    Validated rather than trusted: a spec is a file a human can edit, and
    the failure mode of a silently half-understood spec is a figure that
    claims to be a re-render and is not."""
    import json
    try:
        with open(path, encoding='utf-8') as f:
            spec = json.load(f)
    except OSError as e:
        return None, f"cannot read --from-spec {path}: {e}"
    except ValueError as e:
        return None, f"--from-spec {path} is not valid JSON: {e}"
    if not isinstance(spec, dict):
        return None, f"--from-spec {path}: expected a JSON object"
    ver = spec.get('spec_version')
    if isinstance(ver, bool) or not isinstance(ver, int) or ver < 1:
        return None, (f"--from-spec {path}: 'spec_version' must be a "
                      f"positive integer")
    if ver > SPEC_VERSION:
        return None, (f"--from-spec {path}: spec_version {ver} was written "
                      f"by a newer build (this one reads up to "
                      f"{SPEC_VERSION})")
    if not isinstance(spec.get('opts'), dict):
        return None, f"--from-spec {path}: no 'opts' object"
    runs = spec.get('runs')
    if not isinstance(runs, list) or not all(isinstance(r, str)
                                             for r in runs):
        return None, (f"--from-spec {path}: 'runs' must be a list of "
                      f"run directories")
    return spec, None


def export(runs, opts, out_dir, stem, warn=lambda m: None):
    """Render the figure, write its tidy CSV AND its figspec -> (img, csv).

    The single write path for both front ends. There is deliberately no
    way to ask for the IMAGE alone: on-screen preview is free, but
    anything that lands on disk lands with its numbers and with the spec
    that says where they came from.

    What that sentence used to say (and what the flags used to allow) is
    that there was no way to ask for a DIFFERENT image either -- one 300
    dpi PNG, no choice offered. `#314` replaced the hard-wiring with
    opts['fmt'] (png | svg) and opts['dpi'], BOTH recorded in the figspec,
    and left the pairing rule exactly where it was: the format is the
    operator's, the three-files-or-nothing is not. The return stays
    (image, csv) -- the spec's path is figspec_path(image), so existing
    callers keep working unchanged."""
    os.makedirs(out_dir, exist_ok=True)
    img, tidy = output_paths(out_dir, stem, opts['mode'],
                             opts.get('fmt', DEFAULT_FORMAT))
    if opts.get('x') in FIELD_AXES:
        # `#398`: the t0 each drawn run's field was divided by, fixed in
        # the figspec at the moment the figure is written, from the runs
        # themselves (prepare_runs resolved them), so the spec names
        # exactly the runs on the figure and --from-spec redraws this
        # field axis whatever setup.txt says by then
        opts = dict(opts, film_thickness=film_thickness_record(runs))
    save_figure(runs, opts, img, warn)
    # the grouping the FIGURE was drawn from, never a second opinion
    # (`#313`, landing site 9): the CSV is the figure's evidence, and
    # evidence that disagrees with the picture is worse than none
    write_tidy(runs, tidy, opts.get('groups') or ())
    # the EFFECTIVE stem (output_paths defaults a blank one), so a
    # re-render from this spec lands on the same filenames
    write_figspec(runs, opts, figspec_path(img),
                  os.path.splitext(os.path.basename(img))[0])
    return img, tidy


def describe_output(img_path, opts):
    """'PNG, 300 dpi, 1.2 MB' / 'SVG (vector), 4.8 MB' -> one phrase both
    front ends report after writing (`#314`).

    The SIZE is in it on purpose. An SVG's size follows the number of
    drawn ELEMENTS, not the pixel count, so it is the one thing about an
    export that cannot be predicted from the settings -- `#314` expected
    a many-run SVG to dwarf its PNG, and MEASURED (2026-08-10, seven runs
    with --prepost --mean) it is 322 kB against the PNG's 310 kB at 300
    dpi. Comparable on this campaign's figures, then; the point of
    printing it is that the next figure's answer may differ, and reading
    it here beats discovering it when a slide deck will not take the
    file. The dpi is named only where it MEANS something, for the same
    reason the window greys the field."""
    try:
        size = os.path.getsize(img_path)
    except OSError:                       # nothing worth failing over
        size = None
    fmt = opts.get('fmt', DEFAULT_FORMAT)
    what = ('SVG (vector)' if fmt == 'svg'
            else f"PNG, {opts.get('dpi', DEFAULT_DPI)} dpi")
    if size is None:
        return what
    for unit, scale in (('MB', 1024 * 1024), ('kB', 1024)):
        if size >= scale:
            return f"{what}, {size / scale:.1f} {unit}"
    return f"{what}, {size} bytes"


def _film_thickness(run, stored, warn):
    """-> (t0 in um, where it came from, why there is none) for one run on
    a field axis (`#398`).

    `stored` is opts' film_thickness as {group_key(run dir): t0}. A run it
    names keeps that t0 whatever its setup.txt says now, because the
    figure being re-made was made with it, and a warning says so when the
    two differ. Any other run's t0 is read from setup.txt now, through the
    one reader (se.film_thickness_of) and sldea_profile.film_thickness_um.
    (None, None, why) when there is none to use, `why` naming which of
    the three reasons it is."""
    recorded = se.film_thickness_of(run['dir'])
    now = sprof.film_thickness_um(recorded)
    key = group_key(run['dir'])
    if key in stored:
        t0 = stored[key]
        if now != t0:
            warn(f"{run['name']}: drawn at the film thickness this figure "
                 f"was made with, {t0:g} µm (its figspec); its setup.txt "
                 f"now records "
                 + (repr(recorded) if recorded is not None
                    else "no 'Film thickness:' line"))
        return t0, 'figspec', ''
    if now is not None:
        return now, 'setup.txt', ''
    if recorded is None:
        return None, None, "no 'Film thickness:' line in its setup.txt"
    if material_key(recorded) == material_key(NOT_SPECIFIED):
        return None, None, "its setup.txt records it as (not specified)"
    return None, None, (f"its setup.txt records {recorded!r}, which is not "
                        f"a thickness in µm")


def prepare_runs(args, opts, warn=lambda m: None, allow_suspect=False,
                 load=None, allow_old_estimator=False):
    """Resolve, load, era-guard, filter and colour the runs -> list.

    Returns [] when nothing is plottable (the caller reports the collected
    warnings). Every guard the CLI grew lives here, so the window inherits
    them instead of reimplementing them: the pre-2026-07-28 scale-bug era,
    the pre-2026-10-02 area-estimator era (old_estimator_areas), the
    reviewed-areas requirement, the missing-baseline case, the palette
    wrap and the cross-run anchor-provenance advisory.

    `load` overrides load_run. The window redraws on every tick box and
    re-reading each run's CSV (and recomputing its breakdown flags) that
    often made it feel broken, so it passes a cache -- the guards below
    still run every time, because which runs are plottable depends on the
    mode.

    On a FIELD axis (`#398`) every run also needs its film thickness t0:
    opts' film_thickness when it names the run (a figspec, so the figure
    is the one that was made), else the run's setup.txt, read here at
    every render. A run with none is left off, and one warning names
    each such run and says how to add the line by hand. The t0 lands on
    run['t0_um'] (with run['t0_src']), the factor from kV to the axis on
    run['x_scale'], and each row's field on row['field'], which x_value
    reads; on every other axis t0 is None and the factor 1.0."""
    load = load or load_run
    uses_areas = needs_areas(opts)
    field = opts.get('x') in FIELD_AXES
    stored = {group_key(d): t0
              for d, t0 in (opts.get('film_thickness') or ())}
    no_t0 = []
    runs = []
    for a in args:
        run = load(a, warn)
        if run is None:
            continue
        # explicit rather than defaulted: a run dict reused across two
        # renders (the window redraws on every toggle) must not carry a
        # previous mode's blanking decision into this one
        run['suspect_kept'] = False
        run['old_estimator_kept'] = False
        run['old_estimator_hidden'] = False
        # ...nor a field axis' t0 into a kV figure (`#398`)
        run['t0_um'] = run['t0_src'] = None
        run['x_scale'] = 1.0
        if suspect_old_scale(run):
            if allow_suspect:
                warn(f"{run['name']}: pre-{SCALE_FIX_DATE} areas "
                     f"KEPT on --allow-suspect-scale")
            elif uses_areas:
                warn(f"{run['name']}: EXCLUDED -- areas predate the "
                     f"{SCALE_FIX_DATE} scale fix and cannot be verified "
                     f"against the nominal disc (2.3-2.7x bug era). "
                     f"Reprocess, or override with --allow-suspect-scale")
                continue
            else:
                # currents are unaffected by the blob-scale bug -- keep
                # the run, but keep its bug-era areas out of the export
                run['suspect_kept'] = True
                warn(f"{run['name']}: areas predate the "
                     f"{SCALE_FIX_DATE} scale fix -- run kept for "
                     f"{opts['mode']} mode (currents unaffected); area "
                     f"columns blanked in the tidy CSV")
        # the area-estimator era (2026-10-02), the same way: old 'disc-fit'
        # areas are the ellipse, new ones the common-ray ratio, and the
        # two must not meet on one axis, in one mean or in one CSV
        if old_estimator_areas(run):
            if allow_old_estimator:
                # drawn, but SAID: in the caption and in the tidy CSV's
                # area_estimator column
                run['old_estimator_kept'] = True
                warn(f"{run['name']}: disc-fit areas from the OLD area "
                     f"method (ellipse; no 'area_estimator: "
                     f"{se.AREA_ESTIMATOR_VERSION}' stamp in setup.txt) "
                     f"KEPT on --allow-old-estimator -- not comparable "
                     f"with ray-ratio areas; named in the caption and the "
                     f"tidy CSV")
            elif uses_areas:
                warn(f"{run['name']}: EXCLUDED -- its disc-fit areas were "
                     f"written by the OLD area method (the fitted ellipse, "
                     f"before 2026-10-02; setup.txt has no 'area_estimator: "
                     f"{se.AREA_ESTIMATOR_VERSION}' line), which read -0.4 "
                     f"to +7.4% off the ray ratio at rest. Re-review the "
                     f"run in Edge Review (Detect, review, Save), or "
                     f"override with --allow-old-estimator")
                continue
            else:
                run['old_estimator_hidden'] = True
                warn(f"{run['name']}: disc-fit areas from the OLD area "
                     f"method (before 2026-10-02) -- run kept for "
                     f"{opts['mode']} mode (currents unaffected); area "
                     f"columns blanked in the tidy CSV")
        if field:
            t0, src, why = _film_thickness(run, stored, warn)
            if t0 is None:
                no_t0.append((run['name'], why))
                continue
            run['t0_um'], run['t0_src'] = t0, src
            run['x_scale'] = 1000.0 / t0
            for r in run['rows']:
                r['field'] = (None if r['kv'] is None
                              else r['kv'] * run['x_scale'])
        runs.append(run)
    if no_t0:
        # ONE warning naming every run, with the fix: the window shows it
        # where the figure's other exclusions are shown, and the plot
        # tools never write setup.txt themselves (`#398`)
        warn(f"field axis: {len(no_t0)} run(s) left off, with no usable "
             f"film thickness: "
             + '; '.join(f"{name} ({why})" for name, why in no_t0)
             + ". To plot a run against the field, add a line like "
               "'Film thickness: 50 µm' (its film's thickness, measured "
               "mounted and prestretched) to that run's setup.txt by "
               "hand, then plot again. This tool never writes setup.txt.")
    if uses_areas:
        kept = []
        for run in runs:
            has_areas = any(r['area_mm2'] is not None for r in run['rows'])
            if has_areas and (opts['mode'] != 'area' or run['a0']):
                kept.append(run)
            elif not has_areas:
                warn(f"{run['name']}: no reviewed areas -- skipped "
                     f"({'area mode' if opts['mode'] == 'area' else '--vs-area'} "
                     f"needs them; current/power vs kV work on raw "
                     f"runs)")
            else:
                warn(f"{run['name']}: areas present but no "
                     f"baseline A0 -- cannot normalize, skipped in "
                     f"area mode")
        runs = kept
    if not runs:
        return runs
    if len(runs) > len(TOL_BRIGHT):
        warn(f"{len(runs)} runs > {len(TOL_BRIGHT)} palette "
             f"colors -- colors repeat; consider fewer runs per "
             f"figure")
    if uses_areas and len(runs) > 1:
        # cross-run absolute mm² inherits each run's anchor provenance
        # (audit 2026-08-05): a recorded manual 📏 anchor and a pre-gate
        # automatic one are different instruments
        with_anchor = [r['name'] for r in runs if r.get('anchor')]
        without = [r['name'] for r in runs if not r.get('anchor')]
        if with_anchor and without:
            warn(f"absolute-scale provenance differs across runs: "
                 f"{len(with_anchor)} carry a recorded manual anchor "
                 f"({', '.join(with_anchor)}), {len(without)} predate it "
                 f"({', '.join(without)}) — cross-run absolute mm² "
                 f"comparisons inherit that difference (A/A0 is safe)")
    for i, run in enumerate(runs):
        run['color'] = TOL_BRIGHT[i % len(TOL_BRIGHT)]
    # A group entry that matches nothing on this figure is the `#313`
    # typo, and it is silent by construction: the group simply averages
    # fewer runs and still draws a perfectly convincing curve. Reported
    # here rather than in draw_area because this is where the plottable
    # set is finally known -- a run excluded by the scale-era guard is a
    # legitimate reason for a group to shrink, and the warning that
    # explains it has already been given above.
    dirs = {group_key(r['dir']) for r in runs}
    names = {os.path.normcase(r['name']) for r in runs}
    for name, members in (opts.get('groups') or ()):
        missing = [os.path.basename(m) for m in members
                   if group_key(m) not in dirs
                   and os.path.normcase(os.path.basename(m)) not in names]
        if missing:
            warn(f"group {name!r}: {len(missing)} named run(s) are not on "
                 f"this figure ({', '.join(missing)}) -- the group's mean "
                 f"is over the {len(members) - len(missing)} that are")
    return runs


# ---------------------------------------------------------------------------
# selftest (synthetic runs, no bench data -- run data never enters the repo)
# ---------------------------------------------------------------------------

def _selftest(out_png):
    import tempfile
    tmp = tempfile.mkdtemp(prefix='sldea_plot_selftest_')
    healthy = os.path.join(tmp, 'HEALTHY_20260805')
    broken = os.path.join(tmp, 'BREAKDOWN_20260805')
    for d in (healthy, broken):
        os.makedirs(os.path.join(d, 'frames'), exist_ok=True)
    cols = ['snapshot', 'step', 'tag', 'nominal_kV', 'control_V',
            'measured_kV', 'measured_uA', 't_planned_s', 'timestamp',
            'frame_file', 'active_area_px', 'active_area_mm2',
            'active_diam_mm', 'wrinkle_idx', 'notes']

    def write(d, rows):
        with open(os.path.join(d, 'data.csv'), 'w', newline='',
                  encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({**{c: '' for c in cols}, **r})

    def rows_for(peak_kv, ua_events):
        rows = [{'snapshot': 1, 'tag': 'baseline', 'nominal_kV': 0,
                 'measured_uA': -16.0, 'active_area_mm2': 201.062,
                 'timestamp': '2026-08-05T10:00:00',
                 'notes': 'edge:resting conf 0.95'}]
        n = 2
        for step in range(1, 17):
            kv = step * 0.5
            bulge = math.exp(-((kv - peak_kv) / 2.2) ** 2)
            for phase in ('pre-ramp', 'post-ramp'):
                area = 201.062 * (1 + 1.4 * bulge)
                traced = 4.0 <= kv <= 5.5
                rows.append({
                    'snapshot': n, 'tag': phase, 'nominal_kV': kv,
                    'measured_uA': ua_events.get(n, -16.0),
                    'active_area_mm2': round(area, 3),
                    'timestamp': '2026-08-05T10:%02d:00' % n,
                    'notes': ('edge:manual-trace conf 1.00 (user)'
                              if traced else 'edge:disc-fit conf 0.93'),
                })
                n += 1
        return rows

    write(healthy, rows_for(5.0, {}))
    write(broken, rows_for(5.5, {29: -80.0, 30: -140.0, 31: -205.0,
                                 32: -210.0, 33: -190.0}))
    warns = []
    runs = [load_run(healthy, warns.append), load_run(broken, warns.append)]
    for i, run in enumerate(runs):
        run['color'] = TOL_BRIGHT[i]
    assert runs[0]['flags'] == {}, runs[0]['flags']
    assert runs[1]['flags'], 'synthetic breakdown not confirmed'
    opts, _ = make_opts(mode='area', mean=True, title='selftest')
    figure_area(runs, opts, out_png, warns.append)
    write_tidy(runs, os.path.splitext(out_png)[0] + '.csv')
    print(f"selftest ok -- wrote {out_png}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

# Every flag _cli_opts reads must be registered here or in _VALUED_FLAGS:
# the parser rejects anything else as "unknown flag" before _cli_opts runs
# (pinned by a source-scan test in tests/test_sldea_plot.py).
_BOOL_FLAGS = ('--vs-area', '--prepost', '--mean', '--no-bands',
               '--no-breakdown', '--allow-suspect-scale',
               '--allow-old-estimator', '--selftest',
               '--gui', '--logx', '--logy', '--no-marker-key',
               '--cadence-guard', '--aggregate', '--aggregate-exact',
               '--aggregate-only', '--strain-pct', '--merge-legs',
               '--no-arrows')
_VALUED_FLAGS = ('--mode', '--out', '--stem', '--title',
                 '--title-first', '--title-second', '--subplots',
                 '--from-spec', '--format', '--dpi', '--group', '--x')

# Valued flags whose SECOND occurrence is a second value, not a correction
# (`#313`, landing site 8). Every other valued flag names one thing and
# "later wins" is right for it -- `--out a --out b` used to send 'b' run
# hunting, which is the review this parser was tightened by. --group is
# the first where that rule is backwards: two --group flags are two
# GROUPS, and last-wins would draw one curve where the operator asked for
# two, with no error anywhere.
_REPEATED_FLAGS = ('--group',)

_orig_stdout = None     # keeps the replaced wrapper alive: a GC'd
                        # TextIOWrapper closes the buffer it shares with
                        # the replacement (found by the test suite)


def _utf8_stdout():
    """Windows cp1252 consoles choke on the micro sign in run notes."""
    global _orig_stdout
    out = sys.stdout
    if (out is None or not hasattr(out, 'buffer')
            or (out.encoding or '').lower().replace('-', '') == 'utf8'):
        return
    _orig_stdout = out
    sys.stdout = io.TextIOWrapper(out.buffer, encoding='utf-8',
                                  errors='replace', line_buffering=True)


def _usage():
    print(__doc__.strip().split('\n\n')[1])


def _parse_argv(argv):
    """-> (positionals, bool_flag_set, valued_flag_dict) or None on a bad
    invocation (message already printed). One consuming left-to-right pass:
    later duplicate valued flags win, a valued flag missing its value or a
    misspelled --flag errors out instead of leaking into positionals
    (review 2026-08-05: `--out a --out b` used to send 'b' run-hunting).

    A flag in _REPEATED_FLAGS ACCUMULATES instead, arriving as a list --
    the exception `#313` needed and the reason that tuple exists rather
    than a special case here."""
    args, flags, vals = [], set(), {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in _BOOL_FLAGS:
            flags.add(a)
        elif a in _VALUED_FLAGS:
            if i + 1 >= len(argv) or argv[i + 1].startswith('--'):
                print(f"{a} requires a value")
                _usage()
                return None
            if a in _REPEATED_FLAGS:
                vals.setdefault(a, []).append(argv[i + 1])
            else:
                vals[a] = argv[i + 1]
            i += 1
        elif a.startswith('--'):
            print(f"unknown flag: {a}")
            _usage()
            return None
        else:
            args.append(a)
        i += 1
    return args, flags, vals


def _cli_opts(flags, vals, base=None):
    """Build the options dict from the parsed command line, over an
    optional `base` (a figspec's opts) -> (opts, error).

    ONE precedence rule, applied to every option: an explicitly given
    command-line flag wins, else the spec's value, else the built-in
    default. With no base this is exactly what the CLI did before
    --from-spec existed.

    Boolean flags are one-way switches, which is the one asymmetry worth
    knowing: --prepost can turn prepost ON over a spec that says false,
    and --no-bands can turn bands OFF over a spec that says true, but
    there is no --bands to turn a spec's `false` back on. To flip a spec
    value the other way, edit the spec -- it is a JSON file, and that is
    half the point of it being one."""
    base = base or {}

    def val(flag, key, default):
        return vals[flag] if flag in vals else base.get(key, default)

    def on(flag, key):
        """a plain --flag: present turns it on, absent inherits"""
        return True if flag in flags else bool(base.get(key, False))

    def off(flag, key):
        """a --no-... flag: present turns it off, absent inherits"""
        return False if flag in flags else bool(base.get(key, True))

    # `#313`. The same precedence as everything else -- any --group at
    # all REPLACES the spec's grouping wholesale rather than merging into
    # it, because a half-merged grouping is a figure nobody described.
    # With no --group the base's own value is inherited, which is the
    # part that keeps --from-spec honest: build_figspec stores dict(opts)
    # and this table is what rebuilds it, so a key missing HERE is a
    # re-render that silently draws a different figure (site 2).
    groups = base.get('groups', ())
    # `#373`: the materials TRAVEL WITH the grouping they describe. A
    # spec's are inherited verbatim alongside its groups, which is what
    # keeps a re-render's line styles from moving, and a --group that
    # replaces the grouping drops them, because they described groups
    # that no longer exist. main() then reads the new groups' materials
    # (derive_group_materials), the CLI's moment of forming a group.
    group_materials = base.get('group_materials', ())
    if '--group' in vals:
        groups = []
        group_materials = ()
        for text in vals['--group']:
            pair, err = parse_group_flag(text)
            if err:
                return None, err
            groups.append(pair)
    # `#398`: a spec's film thicknesses are inherited verbatim, and there
    # is no flag for them. prepare_runs reads only the runs they do not
    # name from setup.txt, which is what lets --from-spec redraw the same
    # field axis after a setup.txt edit, and what reads the new runs when
    # positional RUNs replace the spec's.
    film_thickness = base.get('film_thickness', ())

    return make_opts(mode=val('--mode', 'mode', 'area'),
                     vs_area=on('--vs-area', 'vs_area'),
                     prepost=on('--prepost', 'prepost'),
                     mean=on('--mean', 'mean'),
                     bands=off('--no-bands', 'bands'),
                     breakdown=off('--no-breakdown', 'breakdown'),
                     title=val('--title', 'title', None),
                     logx=on('--logx', 'logx'),
                     logy=on('--logy', 'logy'),
                     marker_key=off('--no-marker-key', 'marker_key'),
                     title_first=val('--title-first', 'title_first', None),
                     title_second=val('--title-second', 'title_second',
                                      None),
                     subplots=val('--subplots', 'subplots', 'both'),
                     cadence_guard=on('--cadence-guard', 'cadence_guard'),
                     aggregate=on('--aggregate', 'aggregate'),
                     aggregate_exact=on('--aggregate-exact',
                                        'aggregate_exact'),
                     groups=groups,
                     group_materials=group_materials,
                     film_thickness=film_thickness,
                     aggregate_only=on('--aggregate-only',
                                       'aggregate_only'),
                     # `#314`. Both go through val() like any other named
                     # option, so `--from-spec spec.json --format png`
                     # re-renders a spec'd SVG as a PNG at the spec's own
                     # dpi -- and a spec that names neither still gets the
                     # 300 dpi PNG every pre-`#314` spec was written from.
                     strain_pct=on('--strain-pct', 'strain_pct'),
                     # 2026-09-23. The two leg options default ON, so they
                     # are "--no-..." style switches like --no-bands: a
                     # spec that says true re-renders true unless told off
                     x=val('--x', 'x', 'kv'),
                     split_legs=off('--merge-legs', 'split_legs'),
                     arrows=off('--no-arrows', 'arrows'),
                     fmt=val('--format', 'fmt', DEFAULT_FORMAT),
                     dpi=val('--dpi', 'dpi', DEFAULT_DPI))


def _field_note(run):
    """The tail of a run's console line on a field-axis figure (`#398`):
    its t0 and where that came from, and the nominal field of its first
    current-confirmed breakdown, E_b = V_b / t0 (first_breakdown_kv, the
    first in time). '' for a run with no t0, which is every run on any
    other axis. ASCII ('um'), as console report text stays."""
    t0 = run.get('t0_um')
    if not t0:
        return ''
    note = f", t0 {t0:g} um ({run.get('t0_src') or '?'})"
    kv_b = first_breakdown_kv(run)
    if kv_b is not None:
        note += (f", first breakdown at {kv_b:g} kV = "
                 f"{nominal_field(kv_b, t0):.4g} V/um")
    return note


def main(argv):
    _utf8_stdout()
    parsed = _parse_argv(argv)
    if parsed is None:
        return 2
    args, flags, vals = parsed
    if '--selftest' in flags:
        return _selftest(args[0] if args else 'sldea_plot_selftest.png')

    spec = None
    if '--from-spec' in vals:
        spec, spec_err = load_figspec(vals['--from-spec'])
        if spec is None:
            print(spec_err)
            return 2
    # a spec's options are re-validated through make_opts rather than
    # trusted: it is an editable file, and an illegal combination must be
    # refused with the same wording wherever it came from
    opts, err = _cli_opts(flags, vals, spec['opts'] if spec else None)
    run_args = args or (list(spec['runs']) if spec else [])
    if '--gui' in flags:
        # the window is a front end to everything below, and it does its own
        # run picking -- so unlike the headless paths it does NOT require
        # run arguments; any given preselect it (`#223`)
        if err:
            print(err)
            return 2
        if '--group' in vals:
            # `#373`: a group formed on this command line gets its
            # material now, the way the window's Assign gives one. A
            # member named by bare folder name is matched against the
            # run arguments, as the headless path matches it against the
            # prepared runs, so both give one command one set of styles.
            named = []
            for a in run_args:
                d = se.resolve_run(a)
                if d:
                    named.append({'dir': d, 'name': os.path.basename(
                        os.path.abspath(d))})
            opts = dict(opts, group_materials=derive_group_materials(
                opts['groups'], named))
        import sldea_plot_gui
        return sldea_plot_gui.launch(
            run_args, opts=opts, out_dir=vals.get('--out'),
            stem=vals.get('--stem') or (spec['stem'] if spec else None))
    # order preserved from before the `#223` refactor: a bare invocation
    # prints usage, and only an invocation that HAS runs gets told its mode
    # or --vs-area is wrong
    if not run_args:
        _usage()
        return 2
    if err:
        print(err)
        return 2

    out_dir = vals.get('--out', '.')
    os.makedirs(out_dir, exist_ok=True)
    # --out is deliberately NOT carried in a spec: a spec describes the
    # figure, not the folder somebody filed it in
    stem = vals.get('--stem') or (spec['stem'] if spec else None) \
        or default_stem(opts['mode'])

    warns = []
    runs = prepare_runs(run_args, opts, warns.append,
                        allow_suspect='--allow-suspect-scale' in flags,
                        allow_old_estimator='--allow-old-estimator'
                        in flags)
    if not runs:
        for w in warns:
            print('warning:', w)
        print('nothing to plot')
        return 2
    if '--group' in vals:
        # `#373`: the groups were formed by THIS invocation, so their
        # materials are read now (after prepare_runs, so a member named
        # by bare folder name resolves to the run it means) and stored
        # in the figspec export writes. Without --group the grouping (and
        # its materials) came from a spec and is used verbatim.
        opts = dict(opts, group_materials=derive_group_materials(
            opts['groups'], runs))

    img, tidy = export(runs, opts, out_dir, stem, warns.append)

    for run in runs:
        n_traced = sum(1 for r in run['rows'] if r['traced'])
        bd = (f"breakdown row(s) {sorted(run['flags'])}" if run['flags']
              else 'no confirmed breakdown')
        print(f"{run['name']}: {len(run['rows'])} rows, "
              f"{n_traced} traced, {bd}" + _field_note(run))
    if opts['mode'] == 'area' and len(runs) > 1:
        print('note: cross-run ABSOLUTE mm2 comparability needs the batch '
              'control round; the A/A0 panel is the safe comparison '
              '(SLDEA_MEASUREMENT.md)')
    for w in warns:
        print('warning:', w)
    print(f"wrote {img} ({describe_output(img, opts)}) + {tidy} + "
          f"{figspec_path(img)}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
