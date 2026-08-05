#!/usr/bin/env python3
"""HIL probe: the three numbers #189's remaining increments need.

Everything left in the live-breakdown-detection thread is blocked on
facts nobody has measured. This gets all three in one pass, at 0 kV,
with NO high voltage anywhere:

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

SAFETY
    This opens the SCOPE ONLY. It never touches the signal generator, so
    nothing here can put a control voltage into the Trek. Leave the HV
    OFF: a quiet 0 kV rig is exactly the condition being measured, and a
    live one would corrupt probe A.

    It does not change acquisition state. It programs MEASUREMENT:IMMED
    TYPE/SOURCE (which every measurement the app takes already does) and
    otherwise only queries.

USAGE
    .venv/bin/python bench/test_sldea_watchdog_probe.py --ich 3 --vch 2

    Add --resource TCPIP0::...::INSTR for LAN. --samples/--timing-samples
    trade run time for confidence; the defaults take about a minute.

    Desk check (no instruments, exercises every code path against a
    synthetic scope):
        .venv/bin/python bench/test_sldea_watchdog_probe.py --selftest

OUTPUT
    Prints a summary and writes <--out>.txt and <--out>.json (default
    sldea_watchdog_probe.*) so the numbers can be pasted into #189
    without re-typing them.
"""
# Runnable from anywhere: put the repo root (one level up) on sys.path.
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import argparse
import json
import statistics
import time

from sldea_profile import IMON_UA_PER_V, VMON_KV_PER_V   # noqa: E402

# Tokens to characterise on the current monitor. MEAN is what the
# watchdog uses today; MAXIMUM/PK2PK are increment (1)'s candidates;
# MINIMUM is here because every ground-truthed breakdown swings NEGATIVE
# (-27..-208 uA on the 2026-08-04 batch), so a peak-based trip may well
# want the minimum rather than the maximum.
I_TOKENS = ('MEAN', 'MAXIMUM', 'MINIMUM', 'PK2PK')
# Queries increments (3)/(4) and the STOP-detection follow-up depend on.
STATE_QUERIES = ('TRIGGER:STATE?', 'ACQUIRE:STATE?', 'ACQUIRE:STOPAFTER?',
                 'TRIGGER:A:MODE?', 'ACQUIRE:MODE?')
WATCHDOG_TICK_S = 0.5          # the live run loop's monitor cadence
TELEMETRY_CAP_HZ = 2.0         # what shipped in #218


def _stats(values):
    """min/median/max/spread/stdev for a list of floats ({} if empty)."""
    if not values:
        return {}
    out = {'n': len(values), 'min': min(values), 'max': max(values),
           'median': statistics.median(values),
           'spread': max(values) - min(values)}
    out['stdev'] = statistics.stdev(values) if len(values) > 1 else 0.0
    return out


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


def probe_state_queries(scope):
    """Which state queries this scope answers, and with what."""
    out = {}
    for q in STATE_QUERIES:
        try:
            out[q] = {'ok': True, 'reply': str(scope.ask(q)).strip()}
        except Exception as e:
            out[q] = {'ok': False, 'reply': f"{type(e).__name__}: {e}"}
    return out


def render(report):
    """The whole report as text (also what gets written to disk)."""
    L = ["SLDEA watchdog probe -- #189 increments (1)/(3), #157 rate cap",
         "=" * 66,
         f"scope   : {report['idn']}",
         f"channels: I_Out CH{report['ich']}  V_Out CH{report['vch']}"
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
          "C. State queries increments (3)/(4) need",
          "-" * 66]
    for q, r in report['state_queries'].items():
        L.append(f"  {q:22s} {'OK ' if r['ok'] else 'FAIL'}  {r['reply']}")
    L += ["",
          "Paste this into issue #189. Section A decides the peak-token",
          "trip level; C decides whether increment (3) needs new driver",
          "work or just a wrapper.", ""]
    return "\n".join(L)


class _FakeScope:
    """Synthetic MSO24 for --selftest: quiet rig, plausible noise."""

    idn = 'FAKE,MSO24,SELFTEST,0'
    _BASE = {'MEAN': -0.08, 'MAXIMUM': -0.02, 'MINIMUM': -0.14,
             'PK2PK': 0.12}

    def __init__(self):
        self._k = 0

    def measure_raw(self, meas_type, channel):
        self._k += 1
        if meas_type not in self._BASE:
            return None, 'invalid'
        # deterministic wobble -- no Math.random, so runs are comparable
        wobble = ((self._k * 37) % 11 - 5) / 1000.0
        return self._BASE[meas_type] + wobble, 'ok'

    def ask(self, cmd):
        if cmd == 'TRIGGER:STATE?':
            return 'READY'
        if cmd == 'ACQUIRE:STATE?':
            return '1'
        if cmd == 'ACQUIRE:STOPAFTER?':
            return 'RUNSTOP'
        raise IOError('query not supported by this fake')

    def close(self):
        pass


def run(scope, args):
    report = {
        'idn': getattr(scope, 'idn', '?'), 'ich': args.ich, 'vch': args.vch,
        'when': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'tokens': probe_tokens(scope, args.ich, args.samples),
        'rates': probe_rates(scope, args.ich, args.vch, args.timing_samples),
        'state_queries': probe_state_queries(scope),
    }
    text = render(report)
    print(text)
    with open(args.out + '.txt', 'w', encoding='utf-8') as f:
        f.write(text)
    with open(args.out + '.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1)
    print(f"written: {args.out}.txt  {args.out}.json")
    return report


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
    ap.add_argument('--out', default='sldea_watchdog_probe',
                    help='output basename (.txt and .json are appended)')
    ap.add_argument('--selftest', action='store_true',
                    help='run against a synthetic scope; no hardware')
    args = ap.parse_args(argv)

    if args.selftest:
        print("--selftest: synthetic scope, no instruments touched\n")
        run(_FakeScope(), args)
        print("\nselftest OK -- every probe path executed")
        return 0

    from instruments import TekMSO24
    scope = TekMSO24(args.resource) if args.resource else TekMSO24()
    try:
        run(scope, args)
    finally:
        scope.close()
    return 0


if __name__ == '__main__':
    _sys.exit(main())
