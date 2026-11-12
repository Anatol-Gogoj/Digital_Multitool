#!/usr/bin/env python3
"""Bench probe: where the time goes in one BK 894 LCR reading (#505).

Two questions need numbers that only the meter can give:

  1. How long is one query round trip on this transport, with no
     measurement in it? (:FUNC:IMP?, :FREQ?, :VOLT?, :APER?)  This is the
     part a different transport (LAN instead of USB) could change.
  2. How long does :FETC? take at each aperture (FAST, MED, SLOW, all with
     averaging 1), and does back-to-back polling get a NEW reading every
     time or repeat the last one?  The datasheet's "Typical measurement
     time (>=10 kHz) (excluding display refresh time)" is FAST 13 ms,
     MED 67 ms, SLOW 187 ms per measurement; this checks that on our unit
     and, with --freqs, below 10 kHz, where the sheet gives no figure.

A :FETC? whose median time is close to the datasheet figure and whose
readings are all fresh suggests the query waits for a new measurement. A
:FETC? much faster than the datasheet figure with many repeats suggests it
returns the last finished reading, so polling faster than the meter
measures only logs duplicates. A call near the I/O timeout is a timeout,
which is #505's leading suspect for the 2.2 s logging floor.

    python bench/lcr_speed_probe.py
    python bench/lcr_speed_probe.py --n 100 --freqs 1000,10000
    python bench/lcr_speed_probe.py --resource "TCPIP::<meter-ip>::<port>::SOCKET"

--resource takes any VISA resource string, so the same probe compares USB
with LAN once the 894's LAN port number is known (from its manual or its
front-panel LAN settings page; it is not known here).

SAFETY AND STATE
    The 894's AC test level is at most 2 Vrms; there is no high voltage
    here. The probe never writes the test level, the DC bias, the bias
    state, the range or the correction. It writes only :APER (to step
    through the speeds) and, with --freqs, :FREQ. Both are put back to
    what the meter had at the start, in a finally block, and read back;
    the report says RESTORED or NOT RESTORED.

    A repeated reading is only a repeat if the reading normally changes in
    its last digits. Measure a real part (the DUT or a capacitor in the
    fixture), not a range where the display sits still.

    Close the Digital Multitool first: only one process can hold the
    894's USB interface.

Writes a CSV of every call and a text summary next to it, by default under
~/lcr_speed_probe/ (never inside the repo: run data stays out of git).
"""
import argparse
import csv
import os
import statistics
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from instruments import BK894          # noqa: E402

# B&K 894/895 datasheet, "Typical measurement time (>=10 kHz) (excluding
# display refresh time)", ms per measurement.
DATASHEET_MS = {'FAST': 13.0, 'MED': 67.0, 'SLOW': 187.0}
CONFIG_QUERIES = (':FUNC:IMP?', ':FREQ?', ':VOLT?', ':APER?')
SPEEDS = ('FAST', 'MED', 'SLOW')
MAX_ERRORS_PER_BLOCK = 3
TIMEOUT_FRACTION = 0.9      # a call this close to the timeout is one


def default_out_dir():
    return os.path.join(os.path.expanduser('~'), 'lcr_speed_probe')


def timed_call(fn, clock=time.perf_counter):
    """Run fn() -> (reply, error_text, start_s, duration_s). Never raises
    except KeyboardInterrupt."""
    t0 = clock()
    try:
        reply = fn()
        err = None
    except KeyboardInterrupt:
        raise
    except Exception as e:          # transport errors are data here
        reply = None
        err = f"{type(e).__name__}: {e}"
    return reply, err, t0, clock() - t0


def run_block(lcr, block, query, n, clock=time.perf_counter):
    """Ask `query` n times back to back. Returns a list of row dicts.

    On an error the input buffer is drained so the next reply is the
    meter's answer to the next query, and the block stops after
    MAX_ERRORS_PER_BLOCK errors rather than paying a timeout per call."""
    rows = []
    errors = 0
    for i in range(n):
        reply, err, t0, dt = timed_call(lambda: lcr.ask(query), clock)
        rows.append({'block': block, 'query': query, 'index': i,
                     't_start_s': t0, 'duration_ms': dt * 1000.0,
                     'reply': reply if reply is not None else '',
                     'error': err or ''})
        if err:
            errors += 1
            try:
                lcr._drain()
            except Exception:
                pass
            if errors >= MAX_ERRORS_PER_BLOCK:
                break
    return rows


def summarize(rows, timeout_ms, fetch=False):
    """Statistics for one block of rows (all the same query).

    For a :FETC? block, `fresh` counts readings whose (primary, secondary)
    differs from the previous good reading; the first good reading counts
    as fresh. `fresh_per_s` is fresh readings over the block's wall time,
    which is the rate of NEW data a logger could actually get."""
    ok = [r for r in rows if not r['error']]
    durations = [r['duration_ms'] for r in ok]
    out = {'n': len(rows), 'n_ok': len(ok), 'n_err': len(rows) - len(ok),
           'n_near_timeout': sum(1 for r in rows
                                 if r['duration_ms']
                                 >= TIMEOUT_FRACTION * timeout_ms),
           'median_ms': None, 'p95_ms': None, 'max_ms': None,
           'calls_per_s': None, 'fresh': None, 'bad_format': None,
           'fresh_per_s': None}
    if durations:
        s = sorted(durations)
        out['median_ms'] = statistics.median(s)
        out['p95_ms'] = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
        out['max_ms'] = s[-1]
    if rows:
        wall_s = (rows[-1]['t_start_s'] + rows[-1]['duration_ms'] / 1000.0
                  - rows[0]['t_start_s'])
        if wall_s > 0:
            out['calls_per_s'] = len(ok) / wall_s
    if fetch:
        fresh = bad = 0
        prev = None
        for r in ok:
            parsed = BK894.parse_fetch(r['reply'])
            if parsed is None:
                bad += 1
                continue
            value = parsed[:2]
            if value != prev:
                fresh += 1
            prev = value
        out['fresh'] = fresh
        out['bad_format'] = bad
        if rows and wall_s > 0:
            out['fresh_per_s'] = fresh / wall_s
    return out


def verdict(speed, stats):
    """One plain line on what a :FETC? block suggests. Hedged on purpose:
    it reads two numbers, it does not know the firmware."""
    if stats['n_near_timeout']:
        return (f"{stats['n_near_timeout']} call(s) near the I/O timeout: "
                "a query is timing out (the #505 suspect)")
    if not stats['n_ok']:
        return "no good readings; see the errors in the CSV"
    ref = DATASHEET_MS.get(speed)
    good = stats['n_ok'] - (stats['bad_format'] or 0)
    fresh_frac = (stats['fresh'] / good) if good else 0.0
    if ref and stats['median_ms'] < 0.5 * ref and fresh_frac < 0.9:
        return (f"returns faster than one {speed} measurement and "
                f"{100 * (1 - fresh_frac):.0f}% of readings repeat: :FETC? "
                "probably hands back the last finished reading")
    if fresh_frac >= 0.9:
        return ("almost every reading is new: polling at this rate gets "
                "fresh data")
    return (f"{100 * (1 - fresh_frac):.0f}% of readings repeat; check that "
            "the part's reading normally moves in its last digits")


def fmt(v, spec='.1f'):
    return '-' if v is None else format(v, spec)


def write_csv(path, rows):
    fields = ['block', 'query', 'index', 't_start_s', 'duration_ms',
              'reply', 'error']
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def restore(lcr, orig_aperture, orig_freq, changed_freq):
    """Put the aperture (and frequency, if the probe changed it) back and
    read them back. Returns report lines; never raises."""
    lines = []
    try:
        lcr._drain()
    except Exception:
        pass
    if orig_aperture is not None:
        try:
            lcr.set_aperture(*orig_aperture)
            now = lcr.get_aperture()
            ok = now == orig_aperture
            lines.append(f"Aperture {orig_aperture[0]},{orig_aperture[1]}: "
                         f"{'RESTORED' if ok else 'NOT RESTORED, reads ' + repr(now)}")
        except Exception as e:
            lines.append(f"Aperture: NOT RESTORED ({type(e).__name__}: {e}); "
                         f"set it to {orig_aperture[0]},{orig_aperture[1]} "
                         "on the front panel")
    if changed_freq and orig_freq is not None:
        try:
            lcr.set_frequency(orig_freq)
            now = lcr.get_config().get('frequency')
            ok = now is not None and abs(now - orig_freq) <= 1e-6 * orig_freq
            lines.append(f"Frequency {orig_freq:g} Hz: "
                         f"{'RESTORED' if ok else 'NOT RESTORED, reads ' + repr(now)}")
        except Exception as e:
            lines.append(f"Frequency: NOT RESTORED ({type(e).__name__}: {e}); "
                         f"set it to {orig_freq:g} Hz on the front panel")
    return lines


def run_probe(lcr, n, freqs, settle_s, clock=time.perf_counter,
              sleep=time.sleep):
    """Run every block against an open BK894. Returns (rows, report_lines).
    Never raises: Ctrl-C or an error ends the probe early with a line in
    the report, and the meter's aperture and frequency are restored
    whatever happens."""
    timeout_ms = float(getattr(getattr(lcr, 'inst', None), 'timeout', None)
                       or BK894.TIMEOUT_MS)
    rows = []
    lines = []
    orig_aperture = orig_freq = None
    changed_freq = False
    try:
        lcr._drain()
        orig_aperture = lcr.get_aperture()
        config = lcr.get_config()
        orig_freq = config.get('frequency')
        lines.append(f"Meter: {getattr(lcr, 'idn', '?')}")
        lines.append(f"Resource: {getattr(lcr, 'resource', '?')}")
        lines.append(f"Start state: mode {config.get('mode')}, "
                     f"{fmt(orig_freq, 'g')} Hz, {fmt(config.get('voltage'), 'g')} V, "
                     f"aperture {orig_aperture[0]},{orig_aperture[1]}")
        lines.append(f"I/O timeout {timeout_ms:.0f} ms; {n} calls per block")
        lines.append("")

        lines.append("A. Round trip, no measurement")
        lines.append(f"   {'query':<12}{'ok/n':>8}{'median':>9}{'p95':>9}"
                     f"{'max':>9}  ms")
        for q in CONFIG_QUERIES:
            block = f"rt {q}"
            b = run_block(lcr, block, q, n, clock)
            rows += b
            s = summarize(b, timeout_ms)
            lines.append(f"   {q:<12}{s['n_ok']:>4}/{s['n']:<3}"
                         f"{fmt(s['median_ms']):>9}{fmt(s['p95_ms']):>9}"
                         f"{fmt(s['max_ms']):>9}"
                         + (f"  {s['n_near_timeout']} near timeout"
                            if s['n_near_timeout'] else ''))
        lines.append("")

        lines.append("B. :FETC? back to back, averaging 1")
        lines.append(f"   {'freq Hz':>9} {'speed':<5}{'sheet':>7}{'median':>8}"
                     f"{'p95':>8}{'max':>8}{'calls/s':>9}{'fresh':>8}"
                     f"{'new/s':>9}")
        if freqs and orig_freq is None:
            lines.append("   start frequency unreadable, so --freqs is "
                         "skipped: the probe could not put it back")
            freqs = []
        for f_hz in (freqs or [orig_freq]):
            if f_hz is not None and orig_freq is not None and f_hz != orig_freq:
                lcr.set_frequency(f_hz)
                changed_freq = True
            for speed in SPEEDS:
                lcr.set_aperture(speed, 1)
                lcr.get_aperture()          # the meter has taken the change
                sleep(settle_s)
                lcr._drain()
                block = f"fetch {fmt(f_hz, 'g')}Hz {speed}"
                b = run_block(lcr, block, ':FETC?', n, clock)
                rows += b
                s = summarize(b, timeout_ms, fetch=True)
                good = s['n_ok'] - (s['bad_format'] or 0)
                lines.append(
                    f"   {fmt(f_hz, 'g'):>9} {speed:<5}"
                    f"{DATASHEET_MS[speed]:>7.0f}{fmt(s['median_ms']):>8}"
                    f"{fmt(s['p95_ms']):>8}{fmt(s['max_ms']):>8}"
                    f"{fmt(s['calls_per_s']):>9}"
                    f"{(str(s['fresh']) + '/' + str(good)):>8}"
                    f"{fmt(s['fresh_per_s']):>9}")
                lines.append(f"      {verdict(speed, s)}")
                if s['n_err']:
                    lines.append(f"      {s['n_err']} error(s), first: "
                                 + next(r['error'] for r in b if r['error']))
        lines.append("")
        lines.append("'sheet' is the datasheet's typical ms per measurement, "
                     "given only for >=10 kHz. 'fresh' counts readings that "
                     "differ from the one before; 'new/s' is fresh readings "
                     "per second of wall time, the rate a logger can reach.")
    except KeyboardInterrupt:
        lines.append("")
        lines.append("Stopped by user.")
    except Exception as e:          # report what was measured, then restore
        lines.append("")
        lines.append(f"Probe stopped early: {type(e).__name__}: {e}")
    finally:
        lines.append("")
        lines.append("Restore")
        lines += ["   " + x for x in restore(lcr, orig_aperture, orig_freq,
                                             changed_freq)]
    return rows, lines


def parse_freqs(text):
    if not text:
        return []
    out = []
    for part in text.split(','):
        part = part.strip()
        if part:
            f_hz = float(part)
            if not 20 <= f_hz <= 500000:
                raise ValueError(f"{part}: the 894 runs 20 Hz to 500 kHz")
            out.append(f_hz)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--resource', default=None,
                    help='VISA resource string (default: find the 894 on USB)')
    ap.add_argument('--n', type=int, default=50,
                    help='calls per block (default 50)')
    ap.add_argument('--freqs', default='',
                    help='comma list of test frequencies in Hz (default: the '
                         "meter's current one only)")
    ap.add_argument('--settle', type=float, default=0.5,
                    help='seconds to wait after each aperture change '
                         '(default 0.5)')
    ap.add_argument('--out-dir', default=default_out_dir(),
                    help='where the CSV and summary go (default '
                         '~/lcr_speed_probe)')
    args = ap.parse_args(argv)
    if args.n < 2:
        ap.error('--n must be at least 2')
    try:
        freqs = parse_freqs(args.freqs)
    except ValueError as e:
        ap.error(str(e))

    os.makedirs(args.out_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_path = os.path.join(args.out_dir, f'lcr_speed_{stamp}.csv')
    txt_path = os.path.join(args.out_dir, f'lcr_speed_{stamp}.txt')

    lcr = BK894(resource=args.resource)
    try:
        rows, lines = run_probe(lcr, args.n, freqs, args.settle)
    finally:
        try:
            lcr.go_local()
        finally:
            lcr.close()

    header = [f"BK 894 speed probe {datetime.now().isoformat(timespec='seconds')}"]
    try:
        import version
        header.append(f"App version {version.version_string()}")
    except Exception:
        pass
    report = '\n'.join(header + [''] + lines) + '\n'
    write_csv(csv_path, rows)
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(report)
    print(f"CSV:     {csv_path}")
    print(f"Summary: {txt_path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
