#!/usr/bin/env python3
"""HIL probe: the numbers #189's remaining increments need, and the scope
replies the SLDEA monitor check's blind spots need.

Everything left in the live-breakdown-detection thread is blocked on
facts nobody has measured. This gets them at 0 kV, with NO high voltage
anywhere:

  A. What do MEAN / MAXIMUM / MINIMUM / PK2PK actually read on a quiet
     I_Out, and how far do they wander? That spread is the whole design
     input for #189 increment (1): the peak tokens see sub-sample spikes
     (which is the point) but they are noisier, so the trip level and
     the confirm streak have to be re-tuned around whatever this
     measures. Guessing it at a desk is not possible.

  B. How fast can the MEASUREMENT:IMMED triple really go? #157 asked for
     the telemetry rate to be capped at what the hardware sustains. It
     shipped capped at 2 Hz on the reasoning that those samples already
     exist for the watchdog -- true, but never timed. This says whether
     2 Hz has headroom, and what the kV sub-sample really costs.

  C. Do TRIGGER:STATE? and ACQUIRE:STATE? work on this scope, and what
     do they return? Increment (3) needs a trigger-state query added to
     the driver, and detecting a scope parked in STOP -- which would let
     telemetry record a plausible flat trace for a whole run -- needs
     the acquire one. Both are pure discovery; cheap here, expensive to
     find out mid-session.

     Since 2026-09-24 C also asks each monitor channel's CH<n>:COUPLING?
     and SELECT:CH<n>?. The SLDEA tab's Run button checks scale,
     attenuation, position and offset, and nothing else, so an I_Out
     left AC-coupled or switched off, or a scope left stopped, passes
     it, and the watchdog would then read ~0 or one frozen record from
     the first second (#337's review). The check cannot learn to see
     those until these replies are known. The trigger's type and source
     are asked too: in NORMAL trigger mode, a source channel that stops
     crossing its level stalls acquisition, and a LIVE run reads only
     two of the scope's channels.

  D. --walk: what C's replies, and the watchdog's own read, come back as
     in each of those blind states. You set each state by hand on the
     front panel (I_Out AC-coupled, I_Out off, the scope stopped); the
     probe reads after each one, works out which queries follow the
     front panel, and ends by checking the scope is ready for a LIVE run
     again. BENCH_TEST.md section N2 walks you through it.

SAFETY
    This opens the SCOPE ONLY. It never touches the signal generator, so
    nothing here can put a control voltage into the Trek. Leave the HV
    OFF: a quiet 0 kV rig is exactly the condition being measured, and a
    live one would corrupt probe A.

    It does not change acquisition state. Opening the scope sends the
    driver's connect sequence -- a VISA device clear, *IDN?, and the
    waveform-transfer format (DATA:ENCDG, DATA:WIDTH), which the app
    sends on every connect too. After that the probe programs
    MEASUREMENT:IMMED TYPE/SOURCE (which every measurement the app takes
    already does) and otherwise only queries.

    The --walk has YOU put I_Out into the states a LIVE run must never
    start in; the probe itself still only queries. It ends by reading the
    scope again, and prints RESTORED only when both monitor channels read
    DC-coupled and on and the scope acquiring -- through queries the walk
    showed follow the front panel -- and the watchdog's own read is a
    readable current. Whatever it cannot confirm it names, for you to
    check on the screen. Put the scope right before anyone starts a LIVE
    run: the SLDEA tab's Run button cannot check any of this yet.

USAGE
    .venv/bin/python bench/test_sldea_watchdog_probe.py --ich 3 --vch 2
    .venv/bin/python bench/test_sldea_watchdog_probe.py --ich 3 --vch 2 --walk

    Add --resource TCPIP0::...::INSTR for LAN. --samples/--timing-samples
    trade run time for confidence; the defaults take about a minute. The
    walk takes as long as you do, about five minutes.

    Desk check (no instruments, exercises every code path against a
    synthetic scope):
        .venv/bin/python bench/test_sldea_watchdog_probe.py --selftest
        .venv/bin/python bench/test_sldea_watchdog_probe.py --selftest --walk

OUTPUT
    Prints a summary and writes <--out>.txt and <--out>.json (default
    sldea_watchdog_probe.*) so the numbers can be pasted into #189
    without re-typing them. --walk writes <--out>_walk.txt/.json
    instead, so it never overwrites them, and --selftest defaults to
    sldea_watchdog_probe_selftest*, so it never lands on a real report.
"""
# Runnable from anywhere: put the repo root (one level up) on sys.path.
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import argparse
import json
import re
import statistics
import textwrap
import time

from sldea_profile import IMON_UA_PER_V, VMON_KV_PER_V   # noqa: E402

# Tokens to characterise on the current monitor. MEAN is what the
# watchdog uses today; MAXIMUM/PK2PK are increment (1)'s candidates;
# MINIMUM is here because every ground-truthed breakdown swings NEGATIVE
# (-27..-208 uA on the 2026-08-04 batch), so a peak-based trip may well
# want the minimum rather than the maximum.
I_TOKENS = ('MEAN', 'MAXIMUM', 'MINIMUM', 'PK2PK')
# Queries increments (3)/(4) and the STOP-detection follow-up depend on.
# TYPE and EDGE:SOURCE (2026-09-24) name the trigger source: in NORMAL
# mode a source that stops crossing its level stalls acquisition as Stop
# does, and a LIVE run reads only two channels (#337's lock leaves the
# others free). HORIZONTAL:SCALE is how long a record MEAN averages over,
# which is what separates a stopped scope from a slow one when reads
# repeat.
STATE_QUERIES = ('TRIGGER:STATE?', 'ACQUIRE:STATE?', 'ACQUIRE:STOPAFTER?',
                 'TRIGGER:A:MODE?', 'ACQUIRE:MODE?', 'TRIGGER:A:TYPE?',
                 'TRIGGER:A:EDGE:SOURCE?', 'HORIZONTAL:SCALE?')
# Asked on both monitor channels (2026-09-24), for the start check #337's
# review asked for: is the channel DC-coupled, and is it on?
# DISPLAY:GLOBAL:CH<n>:STATE? is a second on/off candidate, asked so one
# bench visit settles which of the two this scope answers.
CHANNEL_QUERIES = ('CH{ch}:COUPLING?', 'SELECT:CH{ch}?',
                   'DISPLAY:GLOBAL:CH{ch}:STATE?')
WATCHDOG_TICK_S = 0.5          # the live run loop's monitor cadence
TELEMETRY_CAP_HZ = 2.0         # what shipped in #218
WALK_READS = 6                 # watchdog-style MEAN reads per walk step
UNREAD = '(reply not recognised)'
# .gitignore's sldea_watchdog_probe*.txt/.json keep both reports, and the
# walk's <out>_walk.* beside them, out of the repo.
DEFAULT_OUT = 'sldea_watchdog_probe'


def _wrap(text, indent='  ', hang=None):
    """A sentence as report lines, wrapped at 76 columns. The report is
    pasted into issues, where a code block never wraps a long line."""
    return textwrap.wrap(text, width=76, initial_indent=indent,
                         subsequent_indent=indent + '   ' if hang is None
                         else hang,
                         break_long_words=False, break_on_hyphens=False)


def _stats(values):
    """min/median/max/spread/stdev for a list of floats ({} if empty)."""
    if not values:
        return {}
    out = {'n': len(values), 'min': min(values), 'max': max(values),
           'median': statistics.median(values),
           'spread': max(values) - min(values)}
    out['stdev'] = statistics.stdev(values) if len(values) > 1 else 0.0
    return out


# --------------------------------------------------------------- replies
# Tek scopes put the header in front of a reply when HEADER is ON
# (':CH3:COUPLING DC') and answer the short keyword when VERBOSE is OFF
# ('NORM' for NORMAL). HEADER is off in practice -- every bench run has
# logged measured_kV/measured_uA, and the driver's plain float() of a
# MEASUREMENT:IMMED:VALUE? reply could not read a headed one -- but
# nobody has seen what these queries answer, so reading a reply must not
# depend on either setting. The raw reply is always what gets recorded;
# these parsers only feed the words printed beside it.

_COUPLINGS = (('DC', 'DC'), ('AC', 'AC'), ('DCREJECT', 'DCREJ'),
              ('GND', 'GND'))
_TRIGGER_MODES = (('AUTO', 'AUTO'), ('NORMAL', 'NORM'))
_STOPAFTER = (('RUNSTOP', 'RUNST'), ('SEQUENCE', 'SEQ'))


def reply_token(reply):
    """A reply reduced to its value: header, quotes and case removed."""
    s = str(reply).strip()
    if s.startswith(':'):                  # HEADER ON: ':CH3:COUPLING DC'
        s = s.partition(' ')[2]
    return s.strip().strip('"').strip().upper()


def _keyword(token, choices):
    """The long form in `choices` ((long, short) pairs) that `token`
    spells, or None. Tek accepts any spelling from the short form up to
    the long one, so 'NORM', 'NORMA' and 'NORMAL' are all NORMAL."""
    for long_form, short_form in choices:
        if len(token) >= len(short_form) and long_form.startswith(token):
            return long_form
    return None


def parse_coupling(reply):
    """CH<n>:COUPLING? -> 'DC' / 'AC' / 'DCREJECT' / 'GND', or None."""
    return _keyword(reply_token(reply), _COUPLINGS)


def parse_on_off(reply):
    """SELECT:CH<n>? or DISPLAY:GLOBAL:CH<n>:STATE? -> True (on),
    False (off), or None."""
    return {'1': True, 'ON': True,
            '0': False, 'OFF': False}.get(reply_token(reply))


def parse_acquiring(reply):
    """ACQUIRE:STATE? -> True (acquiring), False (stopped), or None.
    Takes the command's own RUN/STOP words as well as 1/0 and ON/OFF."""
    return {'1': True, 'ON': True, 'RUN': True,
            '0': False, 'OFF': False, 'STOP': False}.get(reply_token(reply))


def parse_trigger_mode(reply):
    """TRIGGER:A:MODE? -> 'AUTO' / 'NORMAL', or None."""
    return _keyword(reply_token(reply), _TRIGGER_MODES)


def parse_stopafter(reply):
    """ACQUIRE:STOPAFTER? -> 'RUNSTOP' / 'SEQUENCE', or None."""
    return _keyword(reply_token(reply), _STOPAFTER)


def parse_channel(reply):
    """'CH3' -> 3. Anything that is not an analog channel -> None."""
    m = re.fullmatch(r'CH(\d+)', reply_token(reply))
    return int(m.group(1)) if m else None


def classify_value(reply):
    """(value, status) for a MEASUREMENT:IMMED:VALUE? reply, classified
    exactly as TekMSO24.measure_raw classifies it, so a step says what the
    watchdog would have made of the same reply. Deliberately NOT header-
    tolerant: the driver is not either."""
    try:
        val = float(reply)
    except (TypeError, ValueError):
        return None, 'invalid'
    if abs(val) > 1e30:
        return None, 'offscreen'
    return val, 'ok'


def describe(query, reply, ich, vch):
    """What a reply means for a LIVE run, in words; '' where there is
    nothing to add. A reply in a form this probe does not know says so:
    that is a finding in itself, and the raw text is then the evidence."""
    q = query.upper()
    if q.endswith(':COUPLING?'):
        c = parse_coupling(reply)
        if c is None:
            return UNREAD
        return 'DC-coupled' if c == 'DC' else c + '-coupled -- NOT DC'
    if q.startswith(('SELECT:CH', 'DISPLAY:GLOBAL:CH')):
        return {True: 'on', False: 'OFF', None: UNREAD}[parse_on_off(reply)]
    if q == 'ACQUIRE:STATE?':
        return {True: 'acquiring', False: 'STOPPED',
                None: UNREAD}[parse_acquiring(reply)]
    if q == 'ACQUIRE:STOPAFTER?':
        return {'RUNSTOP': 'continuous (Run/Stop)',
                'SEQUENCE': 'single sequence',
                None: UNREAD}[parse_stopafter(reply)]
    if q == 'TRIGGER:A:MODE?':
        return {'AUTO': 'runs without a trigger too',
                'NORMAL': 'waits for a trigger',
                None: UNREAD}[parse_trigger_mode(reply)]
    if q == 'TRIGGER:A:EDGE:SOURCE?':
        ch = parse_channel(reply)
        if ch is None:
            return 'not an analog channel' if reply_token(reply) else UNREAD
        roles = {ich: 'I_Out', vch: 'V_Out'}
        if ch in roles:
            return f"= {roles[ch]}, which the run reads"
        return 'a channel the run does not read'
    return ''


# ------------------------------------------------------------ A. tokens
def probe_tokens(scope, ich, samples):
    """Read every token on the current channel; -> {token: {...}}.

    Values are converted to uA with the same scale factor the app uses,
    so the numbers are directly comparable to a trip level typed into
    the SLDEA tab."""
    out = {}
    for token in I_TOKENS:
        ua, offscreen, invalid = [], 0, 0
        for _ in range(samples):
            try:
                val, status = scope.measure_raw(token, ich)
            except Exception:
                val, status = None, 'error'
            if status == 'offscreen':
                offscreen += 1
            elif val is None:
                invalid += 1
            else:
                ua.append(val * IMON_UA_PER_V)
        out[token] = dict(_stats(ua), offscreen=offscreen, invalid=invalid,
                          requested=samples)
    return out


def token_verdict(tokens):
    """Readable lines: what a peak-based trip would have to clear.

    The quiet-rig spread of a token is the floor under any trip level
    built on it -- a threshold inside that spread false-trips on nothing
    at all."""
    lines = []
    base = tokens.get('MEAN', {})
    for token in I_TOKENS:
        t = tokens.get(token, {})
        if not t.get('n'):
            lines.append(f"  {token:8s} NO READABLE SAMPLES "
                         f"({t.get('offscreen', 0)} off-screen, "
                         f"{t.get('invalid', 0)} invalid) -- check the "
                         f"vertical window before trusting anything else")
            continue
        lines.append(
            f"  {token:8s} median {t['median']:+8.2f} uA   "
            f"range {t['min']:+8.2f} ... {t['max']:+8.2f}   "
            f"spread {t['spread']:6.2f}   sd {t['stdev']:5.2f}"
            + (f"   ({t['offscreen']} off-screen)" if t['offscreen'] else ""))
    if base.get('spread') is not None:
        lines.append("")
        lines.append(f"  A trip built on MEAN clears {base['spread']:.1f} uA "
                     f"of quiet-rig noise today.")
        for token in ('MAXIMUM', 'MINIMUM', 'PK2PK'):
            t = tokens.get(token, {})
            if t.get('spread') is None:
                continue
            ratio = (t['spread'] / base['spread']) if base['spread'] else 0.0
            lines.append(
                f"  Switching to {token} would have to clear "
                f"{t['spread']:.1f} uA"
                + (f" ({ratio:.1f}x MEAN)" if ratio else ""))
    return lines


# ------------------------------------------------------------- B. rates
def probe_rates(scope, ich, vch, n):
    """Time the measurement round-trip, I alone and I+V paired."""
    def _time(fn, count):
        ms = []
        for _ in range(count):
            t0 = time.monotonic()
            try:
                fn()
            except Exception:
                pass
            ms.append((time.monotonic() - t0) * 1000.0)
        return ms

    i_only = _time(lambda: scope.measure_raw('MEAN', ich), n)

    def _pair():
        scope.measure_raw('MEAN', ich)
        scope.measure_raw('MEAN', vch)
    paired = _time(_pair, n)
    return {'i_only_ms': _stats(i_only), 'i_plus_v_ms': _stats(paired)}


def rate_verdict(rates):
    """Does the shipped 2 Hz cap have headroom, and what does kV cost?"""
    lines = []
    for key, label in (('i_only_ms', 'I_Out alone      '),
                       ('i_plus_v_ms', 'I_Out + V_Out    ')):
        s = rates.get(key) or {}
        if not s:
            continue
        hz = 1000.0 / s['median'] if s['median'] else 0.0
        lines.append(f"  {label} median {s['median']:7.1f} ms  "
                     f"worst {s['max']:7.1f} ms  -> {hz:6.1f} reads/s "
                     f"sustained")
    i = (rates.get('i_only_ms') or {}).get('max')
    p = (rates.get('i_plus_v_ms') or {}).get('max')
    if i:
        lines.append("")
        budget = WATCHDOG_TICK_S * 1000.0
        lines.append(
            f"  The monitor tick is {WATCHDOG_TICK_S:g} s. A worst-case "
            f"I_Out read is {i:.0f} ms = {100.0 * i / budget:.1f}% of it."
            + ("  HEADROOM IS THIN -- say so on the issue."
               if i > 0.25 * budget else "  Comfortable."))
    if p and i:
        lines.append(
            f"  The kV sub-sample adds {p - i:.0f} ms to the ticks that "
            f"take it. Telemetry shipped capped at {TELEMETRY_CAP_HZ:g} Hz; "
            + ("that cap looks right." if p < 0.5 * WATCHDOG_TICK_S * 1000.0
               else "revisit the cap -- the pair is a large slice of a tick."))
    return lines


# ------------------------------------------------------------ C. states
def _ask_all(scope, queries):
    """{query: {'ok', 'reply'}}. A failure is recorded, never raised."""
    out = {}
    for q in queries:
        try:
            out[q] = {'ok': True, 'reply': str(scope.ask(q)).strip()}
        except Exception as e:
            out[q] = {'ok': False, 'reply': f"{type(e).__name__}: {e}"}
    return out


def probe_state_queries(scope):
    """Which state queries this scope answers, and with what."""
    return _ask_all(scope, STATE_QUERIES)


def channel_queries(ich, vch):
    """[(query, role)] for both monitor channels, I_Out first. A channel
    given for both roles is asked once."""
    out = []
    for role, ch in (('I_Out', ich), ('V_Out', vch)):
        for q in CHANNEL_QUERIES:
            q = q.format(ch=ch)
            if q not in [seen for seen, _ in out]:
                out.append((q, role))
    return out


def probe_channel_queries(scope, ich, vch):
    """CHANNEL_QUERIES on both monitor channels, each tagged with its
    role."""
    pairs = channel_queries(ich, vch)
    out = _ask_all(scope, [q for q, _ in pairs])
    for q, role in pairs:
        out[q]['role'] = role
    return out


def reply_lines(replies, ich, vch):
    """One line per query: OK/FAIL, the raw reply, and what it means."""
    lines = []
    for q, r in replies.items():
        label = f"{q} [{r['role']}]" if r.get('role') else q
        words = describe(q, r['reply'], ich, vch) if r['ok'] else ''
        lines.append(f"  {label:34s} {'OK' if r['ok'] else 'FAIL':4s}  "
                     + (f"{r['reply']:10s}  {words}" if words
                        else r['reply']))
    return lines


def _reply(replies, q):
    """The reply to `q` if it answered, else None."""
    r = replies.get(q) or {}
    return r['reply'] if r.get('ok') else None


def trigger_verdict(replies, ich, vch):
    """Can a channel the run does not read stall the run's reads? Read
    off the trigger mode, type and edge source."""
    mode = parse_trigger_mode(_reply(replies, 'TRIGGER:A:MODE?') or '')
    if mode is None:
        return _wrap("Trigger mode: no reply this probe can read. Read the "
                     "mode off the screen and write it down -- it decides "
                     "whether a channel the run does not read can stall "
                     "the run's reads.")
    if mode == 'AUTO':
        return _wrap("Trigger mode AUTO: the scope acquires with or without "
                     "a trigger, so no channel's settings can stall a LIVE "
                     "run's reads.")
    head = "Trigger mode NORMAL: acquisition waits for a trigger."
    kind = reply_token(_reply(replies, 'TRIGGER:A:TYPE?') or '')
    source = _reply(replies, 'TRIGGER:A:EDGE:SOURCE?') or ''
    ch = parse_channel(source)
    look = (f"Read the source off the screen: if it is a channel other "
            f"than CH{ich}/CH{vch}, that channel can stall a LIVE run's "
            f"reads.")
    if kind and _keyword(kind, (('EDGE', 'EDG'),)) is None:
        why = (f"The trigger type is {kind}, not EDGE, and this probe "
               f"reads only the edge source. " + look)
    elif ch is None and reply_token(source) == 'LINE':
        why = ("Its source is LINE, the mains, which triggers all the "
               "time: no channel's settings can stall it.")
    elif ch is None and reply_token(source):
        why = (f"Its source is {reply_token(source)}, not an analog "
               f"channel: acquisition waits for it to trigger, and if "
               f"nothing drives it, every read freezes. Write down what "
               f"it is.")
    elif ch is None:
        why = "The source did not read back. " + look
    elif ch in (ich, vch):
        role = 'I_Out' if ch == ich else 'V_Out'
        why = (f"Its source is CH{ch} = {role}, which the run reads: "
               f"acquisition moves only when {role} crosses the trigger "
               f"level, so a quiet {role} that never crosses it freezes "
               f"every read with nothing touched.")
    else:
        why = (f"Its source is CH{ch}, a channel the run does not read, "
               f"and nothing locks or checks it: re-coupling CH{ch}, "
               f"moving it or turning it off so it never crosses the level "
               f"freezes every read of the run, as Stop does.")
    return _wrap(head + " " + why)


def render(report):
    """The whole report as text (also what gets written to disk)."""
    ich, vch = report['ich'], report['vch']
    L = ["SLDEA watchdog probe -- #189 increments (1)/(3), #157 rate cap",
         "=" * 66,
         f"scope   : {report['idn']}",
         f"channels: I_Out CH{ich}  V_Out CH{vch}"
         f"   ({IMON_UA_PER_V:g} uA and {VMON_KV_PER_V:g} kV per scope-volt)",
         f"when    : {report['when']}",
         "",
         "A. Quiet-rig readings per measurement token  (HV must be OFF)",
         "-" * 66]
    L += token_verdict(report['tokens'])
    L += ["",
          "B. Measurement round-trip cost",
          "-" * 66]
    L += rate_verdict(report['rates'])
    L += ["",
          "C. State queries increments (3)/(4) and the monitor check need",
          "-" * 66]
    L += reply_lines(report['state_queries'], ich, vch)
    L += reply_lines(report.get('channel_queries', {}), ich, vch)
    L += [""] + trigger_verdict(report['state_queries'], ich, vch)
    L += ["",
          "Paste this into issue #189. Section A decides the peak-token",
          "trip level; C decides whether increment (3) needs new driver",
          "work or just a wrapper. C's per-channel lines, and the --walk",
          "file (BENCH_TEST.md N2), are what the monitor check needs",
          "before it can refuse an AC-coupled, switched-off or stopped",
          "monitor.", ""]
    return "\n".join(L)


# -------------------------------------------------------------- D. walk
# The states the monitor check has to learn to see, each set by hand on
# the front panel so every reply is checked against a state someone can
# see on the screen. Only I_Out changes -- it is what the watchdog reads --
# and V_Out rides along untouched.
WALK_STEPS = (
    ('normal',
     "Set the scope up as a LIVE run uses it: CH{ich} (I_Out) and CH{vch} "
     "(V_Out) DC-coupled and on, and the scope acquiring (Run). If it "
     "already is, change nothing."),
    ('i_ac', "Set CH{ich} (I_Out) to AC coupling."),
    ('i_off', "Set CH{ich} back to DC coupling, then turn CH{ich} OFF."),
    ('stopped', "Turn CH{ich} back ON, then press Run/Stop so the scope "
                "stops."),
)
RESTORE_TEXT = ("Put the scope back the way a LIVE run needs it: CH{ich} "
                "(I_Out) and CH{vch} (V_Out) DC-coupled and on, and the "
                "scope running continuously -- if it shows Stopped, press "
                "Run/Stop.")
# What a LIVE run's monitoring needs, one property per entry: (label, the
# queries that read it, their parser, the reading a LIVE run needs, the
# walk step that changes it). A '{ch}' property holds for both monitor
# channels, and the walk changes it on I_Out's. On/off has two candidate
# queries.
WALK_PROPERTIES = (
    ('coupling', ('CH{ch}:COUPLING?',), parse_coupling, 'DC', 'i_ac'),
    ('on/off', ('SELECT:CH{ch}?', 'DISPLAY:GLOBAL:CH{ch}:STATE?'),
     parse_on_off, True, 'i_off'),
    ('acquisition', ('ACQUIRE:STATE?',), parse_acquiring, True, 'stopped'),
)


def _walk_queries(ich):
    """{query on I_Out's channel: (form, parser, needed reading, step)},
    in step order."""
    return {form.format(ch=ich): (form, parse, good, step)
            for _, forms, parse, good, step in WALK_PROPERTIES
            for form in forms}


def watched_queries(ich):
    """Every query the walk's steps move, in step order."""
    return list(_walk_queries(ich))


def step_moves(name, ich):
    """The queries walk step `name` should move away from normal use."""
    return [q for q, (_, _, _, step) in _walk_queries(ich).items()
            if step == name]


def read_values(scope, ich, n, sleep=time.sleep, clock=time.monotonic):
    """n MEAN reads of I_Out, one per watchdog tick, keeping the RAW reply.

    The same TYPE/SOURCE/VALUE? triple TekMSO24.measure_raw sends, and in
    the same order. The raw text is kept because what this scope answers
    for a switched-off channel or a stopped acquisition is exactly what
    nobody knows yet."""
    out = []
    for k in range(n):
        t0 = clock()
        try:
            scope.write('MEASUREMENT:IMMED:TYPE MEAN')
            scope.write(f'MEASUREMENT:IMMED:SOURCE CH{ich}')
            reply = str(scope.ask('MEASUREMENT:IMMED:VALUE?')).strip()
            value, status = classify_value(reply)
        except Exception as e:
            reply, value, status = f"{type(e).__name__}: {e}", None, 'error'
        ms = (clock() - t0) * 1000.0
        out.append({'reply': reply, 'value': value, 'status': status,
                    'ms': round(ms, 1)})
        if k < n - 1:
            sleep(max(0.0, WATCHDOG_TICK_S - ms / 1000.0))
    return out


def snapshot(scope, ich, vch, reads=WALK_READS, sleep=time.sleep,
             clock=time.monotonic):
    """Everything one walk step records: every C query, then the
    watchdog's own read of I_Out at its cadence, then the watched queries
    and ACQUIRE:STOPAFTER? once more. A read that switched the channel
    back on, or an acquisition that stopped meanwhile, shows up as a
    difference between the two."""
    replies = probe_state_queries(scope)
    replies.update(probe_channel_queries(scope, ich, vch))
    values = read_values(scope, ich, reads, sleep, clock)
    return {'replies': replies, 'reads': values,
            'after': _ask_all(scope, watched_queries(ich)
                              + ['ACQUIRE:STOPAFTER?'])}


def blind_lines(replies, ich, vch):
    """(blind, unread) for `replies`, taken at face value: what reads as a
    state a LIVE run must not start in -- a monitor channel not DC-coupled
    or off, the scope stopped or set to Single -- and what could not be
    read at all. One on/off query reading off is enough, and an unreadable
    reply is never guessed at."""
    blind, unread = [], []
    for role, ch in (('I_Out', ich), ('V_Out', vch)):
        c = parse_coupling(_reply(replies, f'CH{ch}:COUPLING?') or '')
        if c is None:
            unread.append(f"CH{ch} coupling")
        elif c != 'DC':
            blind.append(f"CH{ch} ({role}) reads {c}-coupled")
        ons = [parse_on_off(_reply(replies, q) or '') for q in
               (f'SELECT:CH{ch}?', f'DISPLAY:GLOBAL:CH{ch}:STATE?')]
        if False in ons:
            blind.append(f"CH{ch} ({role}) reads off")
        elif True not in ons:
            unread.append(f"CH{ch} on/off")
    acq = parse_acquiring(_reply(replies, 'ACQUIRE:STATE?') or '')
    if acq is None:
        unread.append("acquisition")
    elif not acq:
        blind.append("the scope reads stopped")
    if parse_stopafter(_reply(replies, 'ACQUIRE:STOPAFTER?')
                       or '') == 'SEQUENCE':
        blind.append("the scope is set to stop after one acquisition "
                     "(Single)")
    return blind, unread


def reads_verdict(reads):
    """What the watchdog would make of one step's reads, as lines."""
    if not reads:
        return ["  no reads taken"]
    counts = {}
    for r in reads:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    ok = [r for r in reads if r['status'] == 'ok']
    ms = [r['ms'] for r in reads]
    lines = [f"  {len(reads)} reads: "
             + ", ".join(f"{counts[s]} {s}" for s in
                         ('ok', 'offscreen', 'invalid', 'error')
                         if s in counts)
             + f"   ({min(ms):.0f}..{max(ms):.0f} ms each)"]
    if ok:
        distinct = len({r['reply'] for r in ok})
        median_ua = statistics.median(r['value'] for r in ok) * IMON_UA_PER_V
        lines.append(f"  readable ones: median {median_ua:+.2f} uA, "
                     f"{distinct} distinct of {len(ok)}")
    if counts.get('offscreen'):
        lines += _wrap("-> the 9.9E37 sentinel: the watchdog counts each as "
                       "an over-trip sample, so a LIVE run would "
                       "BREAKDOWN-ABORT once the confirm time ran out")
    if counts.get('invalid') or counts.get('error'):
        lines += _wrap("-> unreadable: after 10 s of these a LIVE run logs "
                       "CURRENT MONITORING LOST and carries on with the "
                       "watchdog blind")
    if len(ok) == len(reads) > 1:
        if len({r['reply'] for r in ok}) == 1:
            lines += _wrap("-> readable, but every read returned the same "
                           "value: a frozen record passes as healthy, and "
                           "no alarm fires")
        else:
            lines += _wrap("-> readable and changing: the watchdog takes "
                           "these as the real current")
    return lines


def moved_lines(step, normal, ich):
    """Did the queries this step targets move away from their 'normal'
    replies -- to a bad reading, not a good one -- and are the other
    watched ones still where they started?"""
    lines = []
    for q, (_, parse, good, target) in _walk_queries(ich).items():
        a = _reply(normal['replies'], q)
        b = _reply(step['replies'], q)
        if target == step['name']:
            if a is None or b is None:
                when = ('at the start or now' if a is None and b is None
                        else 'at the start' if a is None else 'now')
                lines += _wrap(f"{q}: no reply {when} -- cannot tell "
                               f"whether it moved")
            elif a == b:
                lines += _wrap(f"{q}: still {b!r} -- did NOT move. If the "
                               f"screen shows the change, this query does "
                               f"not see it: note that")
            elif parse(b) == good:
                lines += _wrap(f"{q}: {a!r} -> {b!r} -- moved, but to the "
                               f"reading a LIVE run needs, the opposite of "
                               f"this step's change: note what the screen "
                               f"shows")
            else:
                lines += _wrap(f"{q}: {a!r} -> {b!r} -- moved, as this "
                               f"step should")
        elif a is not None and b is not None and a != b:
            lines += _wrap(f"{q}: {a!r} -> {b!r} -- not this step's "
                           f"change; left over from an earlier step?")
    return lines


def after_lines(step):
    """Watched replies that changed while the step's reads ran."""
    lines = []
    for q in step['after']:
        before, after = _reply(step['replies'], q), _reply(step['after'], q)
        if before is not None and after is not None and before != after:
            lines += _wrap(f"{q}: {before!r} before the reads, {after!r} "
                           f"after -- it changed while they ran")
    return lines


def proven_queries(steps, ich):
    """The watched queries this walk showed follow the front panel. One
    counts only if, at the step that changed what it reads, its reply
    moved away from its reply in normal use -- and not to the reading a
    LIVE run needs. -> {query form: (reply in normal use, reply at that
    step)}. A form proven on I_Out's channel is taken to behave the same
    on V_Out's: it is the same command."""
    by = {s['name']: s for s in steps}
    out = {}
    for q, (form, parse, good, step) in _walk_queries(ich).items():
        if 'normal' not in by or step not in by:
            continue
        a = _reply(by['normal']['replies'], q)
        b = _reply(by[step]['replies'], q)
        if a is not None and b is not None and a != b and parse(b) != good:
            out[form] = (a, b)
    return out


def proof_lines(steps, ich):
    """Which watched queries followed the front panel, and why the others
    do not count: the walk's headline result for the monitor check."""
    by = {s['name']: s for s in steps}
    proven = proven_queries(steps, ich)
    lines = []
    for q, (form, _, _, step) in _walk_queries(ich).items():
        if form in proven:
            a, b = proven[form]
            why = (f"FOLLOWS the front panel: {a!r} in normal use, {b!r} "
                   f"at step {step}")
        elif 'normal' not in by or step not in by:
            why = f"not tested: the walk stopped before step {step}"
        else:
            a = _reply(by['normal']['replies'], q)
            b = _reply(by[step]['replies'], q)
            if a is None or b is None:
                why = "no reply, so it cannot be judged"
            elif a == b:
                why = (f"did NOT follow the front panel: {b!r} in normal "
                       f"use and at step {step}")
            else:
                why = (f"moved to {b!r} at step {step} -- the reading a "
                       f"LIVE run needs, the opposite of that step")
        lines += _wrap(f"{q} {why}")
    return lines


def _distinct_ok(step):
    """(distinct readable replies, readable replies) in a step's reads."""
    vals = [r['reply'] for r in step['reads'] if r['status'] == 'ok']
    return len(set(vals)), len(vals)


def _repeats_mark_stopped(steps):
    """True when this walk showed that on this rig identical reads mean a
    stopped scope: varied in normal use, one value while stopped."""
    by = {s['name']: s for s in steps}
    if 'normal' not in by or 'stopped' not in by:
        return False
    dn, nn = _distinct_ok(by['normal'])
    ds, ns = _distinct_ok(by['stopped'])
    return nn > 1 and ns > 1 and dn > 1 and ds == 1


def _reading(reply, parse, good, proof, normal_reply, on_ich):
    """'good', 'bad' or None (cannot judge) for one reply of a property.

    A reply the parser knows is read at face value. One it does not know
    is judged only for a proven query, against that query's own replies in
    the walk: as in normal use (which the operator set up) is good; as at
    the step that changed it, on I_Out's channel, is bad."""
    if reply is None:
        return None
    p = parse(reply)
    if p is not None:
        return 'good' if p == good else 'bad'
    if proof is None:
        return None
    if on_ich and reply == proof[1]:
        return 'bad'
    return 'good' if reply == normal_reply else None


def restore_verdict(steps, now, ich, vch):
    """(state, lines) for the scope after the walk.

    Everything a LIVE run's monitoring needs is judged on `now`: both
    monitor channels DC-coupled and on, the scope acquiring and not set to
    Single, and the watchdog's own read of I_Out a readable current. The
    replies from before AND after its reads both count, so a change while
    they ran is caught.

    A bad reading counts whichever query gave it. A good one counts only
    from a query this walk proved follows the front panel
    (proven_queries): a query that did not move when the operator changed
    what it reads says nothing about the panel. A walk that started blind
    is judged on what a LIVE run needs, never sent back to how it started.

    state False (NOT READY FOR A LIVE RUN): something reads bad. None (NOT
    CONFIRMED): nothing reads bad, but something could not be confirmed and
    the operator has to check it on the screen. True (RESTORED): all of it
    confirmed good."""
    proven = proven_queries(steps, ich)
    by = {s['name']: s for s in steps}
    normal = by.get('normal', {'replies': {}})
    views = (now['replies'], now.get('after') or {})
    bad, unsure = [], []
    for label, forms, parse, good, _step in WALK_PROPERTIES:
        chans = ([(ich, 'I_Out'), (vch, 'V_Out')] if '{ch}' in forms[0]
                 else [(ich, None)])
        for ch, role in chans:
            name = f"CH{ch} ({role}) {label}" if role else label
            found = []                  # (query, reply, reading, proven)
            for form in forms:
                q = form.format(ch=ch)
                for view in views:
                    if q in view:
                        r = _reply(view, q)
                        found.append((q, r, _reading(
                            r, parse, good, proven.get(form),
                            _reply(normal['replies'], q), ch == ich),
                            form in proven))
            worst = [f for f in found if f[2] == 'bad']
            vouched = [f for f in found if f[3]]
            doubt = [f for f in vouched if f[2] != 'good']
            if worst:
                bad.append(f"{name}: {worst[0][0]} reads {worst[0][1]!r}")
            elif not vouched:
                unsure.append(f"{name}: no query this walk showed follows "
                              f"the front panel")
            elif doubt:
                q, r = doubt[0][:2]
                unsure.append(f"{name}: {q} gave "
                              + ('no reply' if r is None else repr(r))
                              + ", which the probe cannot judge")
    for view in views:
        if parse_stopafter(_reply(view, 'ACQUIRE:STOPAFTER?')
                           or '') == 'SEQUENCE':
            bad.append("acquisition: ACQUIRE:STOPAFTER? reads Single "
                       "(SEQUENCE) -- it stops after one acquisition")
            break
    reads = now.get('reads') or []
    poor = [r for r in reads if r['status'] != 'ok']
    if poor:
        bad.append(f"the watchdog's own read of CH{ich}: {len(poor)} of "
                   f"{len(reads)} not a readable current, e.g. "
                   f"{poor[0]['reply']!r}")
    elif (len(reads) > 1 and len({r['reply'] for r in reads}) == 1
          and _repeats_mark_stopped(steps)):
        unsure.append(f"the watchdog's own read of CH{ich}: all "
                      f"{len(reads)} returned {reads[0]['reply']!r}, as "
                      f"the reads did while the scope was stopped")
    lines = []
    if bad:
        lines.append("  NOT READY FOR A LIVE RUN -- put these right on the "
                     "front panel:")
        for x in bad:
            lines += _wrap(x, indent='    ')
    if unsure:
        lines.append("  It also cannot confirm these -- check them on the "
                     "screen:" if bad else
                     "  NOT CONFIRMED -- check these on the screen "
                     "yourself:")
        for x in unsure:
            lines += _wrap(x, indent='    ')
    if bad:
        return False, lines
    if unsure:
        return None, lines
    return True, _wrap("RESTORED -- both monitor channels read DC-coupled "
                       "and on, and the scope acquiring, through queries "
                       "this walk showed follow the front panel, and the "
                       "watchdog's own read is a readable current. Still "
                       "glance at the screen before a LIVE run.")


def put_back_lines(ich, vch):
    """The reminder for any walk that did not end RESTORED."""
    return _wrap(f"Before anyone starts a LIVE run, put the scope back the "
                 f"way it needs it: CH{ich} (I_Out) and CH{vch} (V_Out) "
                 f"DC-coupled and on, and the scope running continuously "
                 f"(Run/Stop, not Single). The SLDEA tab's Run button "
                 f"cannot check any of this yet -- that is what this walk "
                 f"is for.")


def step_lines(step, normal, ich, vch):
    """One step's section: replies, reads, and what moved."""
    name = step['name']
    if step.get('attempt', 1) > 1:
        name += f" (read {step['attempt']})"
    L = [""] + _wrap(f"{name}: {step['did']}", indent='', hang='  ')
    L += ["-" * 70]
    L += reply_lines(step['replies'], ich, vch)
    L.append(f"  MEAN reads of CH{ich}, {WATCHDOG_TICK_S:g} s apart "
             f"(raw reply, status, time):")
    L += [f"    {r['reply']:16s} {r['status']:9s} {r['ms']:7.1f} ms"
          for r in step['reads']]
    L += reads_verdict(step['reads'])
    if step['name'] == 'normal':
        blind, _ = blind_lines(step['replies'], ich, vch)
        if blind:
            L += _wrap("WARNING: the start reads blind for a LIVE run ("
                       + "; ".join(blind) + "). Every step is compared with "
                       "this start. If the screen agrees, set the scope up "
                       "as a LIVE run uses it and walk again. If the screen "
                       "disagrees, carry on and note it: that query reads "
                       "the setting wrongly.")
    elif step['name'] != 'restored':
        L += moved_lines(step, normal, ich)
    L += after_lines(step)
    L += step.get('verdict', [])
    return L


def _reads_cell(reads):
    """A step's reads in one table cell: 'ok x6', 'ok x6 =' when every
    read was identical, 'offscr x6', or a mix such as 'ok4/err2'."""
    abbr = {'ok': 'ok', 'offscreen': 'offscr', 'invalid': 'inval',
            'error': 'err'}
    counts = {}
    for r in reads:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    if len(counts) == 1:
        status, n = next(iter(counts.items()))
        same = (status == 'ok' and n > 1
                and len({r['reply'] for r in reads}) == 1)
        return f"{abbr[status]} x{n}" + (" =" if same else "")
    return "/".join(f"{abbr[s]}{counts[s]}" for s in abbr if s in counts)


def walk_table(cols, ich):
    """One row per query, one column per step: the part to read first. A
    cell holds the reply's value -- header stripped, cut to 9 characters
    -- or FAIL; the step sections below carry every reply raw and in
    full."""
    w = 10
    rows = [f"  {'':27s}" + "".join(f"{s['name']:{w}s}" for s in cols)]
    for q in cols[0]['replies']:
        cells = []
        for s in cols:
            r = s['replies'].get(q) or {}
            cell = (reply_token(r['reply']) or "''") if r.get('ok') else 'FAIL'
            cells.append(cell[:w - 1])
        rows.append(f"  {q:27s}" + "".join(f"{c:{w}s}" for c in cells))
    rows.append(f"  {'MEAN reads of CH%d' % ich:27s}"
                + "".join(f"{_reads_cell(s['reads']):{w}s}" for s in cols))
    return [r.rstrip() for r in rows]


def repeat_verdict(steps):
    """Do repeated reads mark a stopped scope on this rig? Compares how
    many distinct values normal use gave with what the stopped step
    gave."""
    by = {s['name']: s for s in steps}
    if 'normal' not in by or 'stopped' not in by:
        return []
    dn, nn = _distinct_ok(by['normal'])
    ds, ns = _distinct_ok(by['stopped'])
    if nn < 2 or ns < 2:
        return _wrap("Repeated reads: too few readable reads to compare "
                     "normal use with a stopped scope.")
    if ds == 1 and dn > 1:
        return _wrap(f"Repeated reads: {dn} distinct of {nn} in normal use, "
                     f"1 of {ns} stopped -- at this timebase, identical "
                     f"reads do mark a stopped scope on this rig.")
    if ds == 1:
        return _wrap(f"Repeated reads: identical in normal use too ({nn} "
                     f"reads) -- repeats cannot tell a stopped scope from a "
                     f"quiet or slow one here; only ACQUIRE:STATE? can.")
    return _wrap(f"Repeated reads: {ds} distinct of {ns} while stopped -- a "
                 f"stopped scope did not return one frozen value here. Note "
                 f"the timebase.")


def walk_summary_lines(report):
    """The walk's front page: the table, then what it means."""
    ich, vch = report['ich'], report['vch']
    steps = report['steps']
    rest = report.get('restore') or {}
    L = ["SLDEA monitor-state walk -- what the scope answers when I_Out is "
         "blind",
         "=" * 70,
         f"scope   : {report['idn']}",
         f"channels: I_Out CH{ich}  V_Out CH{vch}   ({IMON_UA_PER_V:g} uA "
         f"and {VMON_KV_PER_V:g} kV per scope-volt)",
         f"when    : {report['when']}"]
    if not steps:
        return L + ["", "The walk stopped before its first read: nothing "
                        "recorded."]
    cols = steps + rest.get('attempts', [])[-1:]
    L += ["", "Every step at a glance (full replies in the step sections "
              "below):", ""]
    L += walk_table(cols, ich)
    L += ["", "Which queries follow the front panel -- the monitor check "
              "can use only these:"]
    L += proof_lines(steps, ich)
    L += ["", "What it means for a LIVE run", "-" * 70]
    L += trigger_verdict(steps[0]['replies'], ich, vch)
    L += repeat_verdict(steps)
    L.append("")
    if report.get('interrupted'):
        L.append("  INTERRUPTED -- the walk was stopped with Ctrl-C.")
    if rest.get('attempts'):
        L += rest['attempts'][-1]['verdict']
    elif not report.get('interrupted'):
        L.append("  NOT CHECKED -- the walk stopped before the scope was put "
                 "back and re-read.")
    if rest.get('restored') is not True:
        L += put_back_lines(ich, vch)
    return L


def walk_detail_lines(report):
    """Every step's full section, restore attempts included."""
    ich, vch = report['ich'], report['vch']
    steps = report['steps']
    rest = report.get('restore') or {}
    L = []
    for s in steps + rest.get('attempts', []):
        L += step_lines(s, steps[0], ich, vch)
    return L


def _console_operator(step, text):
    """The bench operator: show what to do, wait for Enter. 'q' stops, and
    so does a closed stdin -- a walk never loops without a person."""
    print("")
    print("\n".join(_wrap(text, indent='>>> ', hang='    ')))
    try:
        return input("    Enter when done, q to stop: ")
    except EOFError:
        return 'q'


def restore(scope, ich, vch, operator, steps, total, out, reads=WALK_READS,
            sleep=time.sleep, clock=time.monotonic, echo=print):
    """Ask for the scope back the way a LIVE run needs it, read it, and ask
    again for as long as something reads NOT READY and the operator does
    not stop. NOT CONFIRMED ends it: reading again cannot confirm what the
    probe cannot see. Fills `out` as it goes -- {'restored', 'attempts'},
    'restored' being the last read's state, None before any read -- so a
    Ctrl-C mid-way keeps the reads already taken."""
    did = RESTORE_TEXT.format(ich=ich, vch=vch)
    text = f"Step {total} of {total} (restored): {did}"
    while operator('restored', text).strip().lower() != 'q':
        snap = snapshot(scope, ich, vch, reads, sleep, clock)
        state, verdict = restore_verdict(steps, snap, ich, vch)
        snap.update(name='restored', did=did, moves=[], state=state,
                    verdict=verdict, attempt=len(out['attempts']) + 1)
        out['attempts'].append(snap)
        out['restored'] = state
        for ln in step_lines(snap, steps[0], ich, vch):
            echo(ln)
        if state is not False:
            break
        text = ("Still not ready for a LIVE run (listed above). Put it "
                "right on the front panel, then press Enter to read it "
                "again.")
    return out


def walk(scope, ich, vch, operator, reads=WALK_READS, sleep=time.sleep,
         clock=time.monotonic, echo=print):
    """Section D: each WALK_STEPS state, set by the operator and read by
    the probe, then the restore check. `operator(step, text)` does or asks
    for the step and returns what was typed ('q' stops). -> the report."""
    report = {'idn': getattr(scope, 'idn', '?'), 'ich': ich, 'vch': vch,
              'when': time.strftime('%Y-%m-%dT%H:%M:%S'), 'steps': [],
              'restore': None, 'interrupted': False}
    total = len(WALK_STEPS) + 1
    try:
        for i, (name, text) in enumerate(WALK_STEPS, 1):
            did = text.format(ich=ich, vch=vch)
            typed = operator(name, f"Step {i} of {total} ({name}): {did}")
            if typed.strip().lower() == 'q':
                break
            snap = snapshot(scope, ich, vch, reads, sleep, clock)
            snap.update(name=name, did=did, moves=step_moves(name, ich))
            report['steps'].append(snap)
            for ln in step_lines(snap, report['steps'][0], ich, vch):
                echo(ln)
        if report['steps']:
            report['restore'] = {'restored': None, 'attempts': []}
            restore(scope, ich, vch, operator, report['steps'], total,
                    report['restore'], reads, sleep, clock, echo)
    except KeyboardInterrupt:
        report['interrupted'] = True
    return report


# ------------------------------------------------------------ selftest
class _FakeScope:
    """Synthetic MSO24 for --selftest: quiet rig, plausible noise.

    It has a front panel -- coupling and on/off per channel, and Run/Stop
    -- so the walk runs every path too; `_scripted_operator` works it. Its
    replies are invented to exercise the code, NOT a claim about what an
    MSO24 answers: finding that out is what the bench run is for."""

    idn = 'FAKE,MSO24,SELFTEST,0'
    _BASE = {'MEAN': -0.08, 'MAXIMUM': -0.02, 'MINIMUM': -0.14,
             'PK2PK': 0.12}

    def __init__(self):
        self._k = 0
        self._type, self._source = 'MEAN', 1
        self.coupling = {ch: 'DC' for ch in range(1, 9)}
        self.on = {ch: True for ch in range(1, 9)}
        self.running = True
        self._frozen = {}

    # the front panel
    def set_coupling(self, ch, coupling):
        self.coupling[ch] = coupling

    def set_on(self, ch, on):
        self.on[ch] = on

    def set_running(self, running):
        self.running = running
        if running:
            self._frozen.clear()

    # SCPI
    def write(self, cmd):
        head, _, arg = cmd.partition(' ')
        if head == 'MEASUREMENT:IMMED:TYPE':
            self._type = arg
        elif head == 'MEASUREMENT:IMMED:SOURCE':
            self._source = int(arg[2:])
        else:
            raise IOError('command not supported by this fake')

    def measure_raw(self, meas_type, channel):
        self.write(f'MEASUREMENT:IMMED:TYPE {meas_type}')
        self.write(f'MEASUREMENT:IMMED:SOURCE CH{channel}')
        return classify_value(self.ask('MEASUREMENT:IMMED:VALUE?'))

    def _live_value(self, ch):
        if self._type not in self._BASE:
            return ''
        self._k += 1
        # deterministic wobble -- no Math.random, so runs are comparable
        wobble = ((self._k * 37) % 11 - 5) / 1000.0
        dc = self._BASE[self._type] if self.coupling[ch] == 'DC' else 0.0
        return f'{dc + wobble:.4E}'

    def _value(self):
        ch = self._source
        if not self.on[ch]:
            return '9.91E+37'
        if not self.running:
            key = (self._type, ch)
            if key not in self._frozen:
                self._frozen[key] = self._live_value(ch)
            return self._frozen[key]
        return self._live_value(ch)

    def ask(self, cmd):
        fixed = {'TRIGGER:STATE?': 'READY' if self.running else 'SAVE',
                 'ACQUIRE:STATE?': '1' if self.running else '0',
                 'ACQUIRE:STOPAFTER?': 'RUNSTOP',
                 'TRIGGER:A:MODE?': 'AUTO',
                 'TRIGGER:A:TYPE?': 'EDGE',
                 'TRIGGER:A:EDGE:SOURCE?': 'CH1',
                 'HORIZONTAL:SCALE?': '1.0E-3'}
        if cmd in fixed:
            return fixed[cmd]
        m = re.fullmatch(r'CH(\d+):COUPLING\?', cmd)
        if m:
            return self.coupling[int(m.group(1))]
        m = re.fullmatch(r'SELECT:CH(\d+)\?', cmd)
        if m:
            return '1' if self.on[int(m.group(1))] else '0'
        if cmd == 'MEASUREMENT:IMMED:VALUE?':
            return self._value()
        raise IOError('query not supported by this fake')

    def close(self):
        pass


def _scripted_operator(fake, ich):
    """--selftest's operator: does each walk step on the fake's panel.
    It types q at a third restore prompt, so a restore check that never
    passes fails the selftest instead of hanging it."""
    actions = {
        'normal': lambda: None,
        'i_ac': lambda: fake.set_coupling(ich, 'AC'),
        'i_off': lambda: (fake.set_coupling(ich, 'DC'),
                          fake.set_on(ich, False)),
        'stopped': lambda: (fake.set_on(ich, True),
                            fake.set_running(False)),
        'restored': lambda: (fake.set_coupling(ich, 'DC'),
                             fake.set_on(ich, True),
                             fake.set_running(True)),
    }
    asked = []

    def operator(step, text):
        asked.append(step)
        print("")
        print("\n".join(_wrap(text, indent='>>> ', hang='    ')))
        if asked.count('restored') > 2:
            print("    (selftest: restore never passed -- giving up)")
            return 'q'
        print("    (selftest: done on the fake's panel)")
        actions[step]()
        return ''
    return operator


def run(scope, args):
    report = {
        'idn': getattr(scope, 'idn', '?'), 'ich': args.ich, 'vch': args.vch,
        'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'tokens': probe_tokens(scope, args.ich, args.samples),
        'rates': probe_rates(scope, args.ich, args.vch, args.timing_samples),
        'state_queries': probe_state_queries(scope),
        'channel_queries': probe_channel_queries(scope, args.ich, args.vch),
    }
    text = render(report)
    print(text)
    with open(args.out + '.txt', 'w', encoding='utf-8') as f:
        f.write(text)
    with open(args.out + '.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1)
    print(f"written: {args.out}.txt  {args.out}.json")
    return report


def run_walk(scope, args, operator=None, sleep=time.sleep,
             clock=time.monotonic):
    """Section D end to end: walk, print the summary, write <out>_walk.*.
    Returns 0 only when the walk ended RESTORED."""
    report = walk(scope, args.ich, args.vch, operator or _console_operator,
                  sleep=sleep, clock=clock)
    summary = walk_summary_lines(report)
    text = "\n".join(summary + walk_detail_lines(report)) + "\n"
    print("\n" + "\n".join(summary))
    base = args.out + '_walk'
    with open(base + '.txt', 'w', encoding='utf-8') as f:
        f.write(text)
    with open(base + '.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1)
    print(f"\nwritten: {base}.txt  {base}.json")
    return 0 if (report['restore'] or {}).get('restored') is True else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--resource', default=None,
                    help='VISA resource (default: autodiscover over USB)')
    ap.add_argument('--ich', type=int, default=3, help='I_Out channel')
    ap.add_argument('--vch', type=int, default=2, help='V_Out channel')
    ap.add_argument('--samples', type=int, default=40,
                    help='readings per token for the noise floor')
    ap.add_argument('--timing-samples', type=int, default=30,
                    help='readings per timing measurement')
    ap.add_argument('--out', default=DEFAULT_OUT,
                    help='output basename (.txt and .json are appended)')
    ap.add_argument('--walk', action='store_true',
                    help='section D (BENCH_TEST.md N2): you set I_Out '
                         'AC-coupled, then off, then stop the scope, by '
                         'hand; the probe reads after each. Writes '
                         '<out>_walk.txt/.json')
    ap.add_argument('--selftest', action='store_true',
                    help='run against a synthetic scope; no hardware')
    args = ap.parse_args(argv)
    if args.ich == args.vch:
        ap.error("--ich and --vch must be different channels: I_Out and "
                 "V_Out are two monitors")

    if args.selftest:
        print("--selftest: synthetic scope, no instruments touched\n")
        if args.out == DEFAULT_OUT:          # never over a real report
            args.out = DEFAULT_OUT + '_selftest'
        fake = _FakeScope()
        if args.walk:
            rc = run_walk(fake, args, _scripted_operator(fake, args.ich),
                          sleep=lambda s: None)
        else:
            run(fake, args)
            rc = 0
        if rc == 0:
            print("\nselftest OK -- every probe path executed")
        return rc

    from instruments import TekMSO24
    scope = TekMSO24(args.resource) if args.resource else TekMSO24()
    try:
        if args.walk:
            return run_walk(scope, args)
        run(scope, args)
    finally:
        scope.close()
    return 0


if __name__ == '__main__':
    _sys.exit(main())
