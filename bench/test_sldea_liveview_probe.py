#!/usr/bin/env python3
"""Bench probe: what one SLDEA live-view tick costs, and how long the run
thread's root.after calls wait for it (#388).

The run thread's own root.after calls (_sldea_log, _sldea_set_status)
are marshaled to the Tk thread by _tkinter, so one made while a tick of
the live view runs waits for that tick to end. sldea_liveview's module
docstring gives the cost: with a fake 1080p stream, 9.4 to 9.5 ms median
and 13 to 16 ms max per tick with the Tk paste, in two runs of this
probe's measurement on the Windows development PC (2026-10-06 and 07).
Nobody has measured it on the Linux bench under X11, where runs happen.
This measures it there:

  A. poll() alone (the thumbnail and the exposure numbers), and poll()
     plus render() without the Tk paste, on the Tk thread;
  B. the whole tick, the paste included, while the loop runs;
  C. a worker thread calling root.after(0, f) every few ms: its wait
     when the call came in during a tick, between ticks, and with the
     view closed.

SAFETY
    No instrument and no camera: the stream is a fake recorder holding
    one random 1080p frame, and the only window is the live view's own.
    Run it with the SLDEA tab idle; it needs no high voltage and starts
    no run.

USAGE
    .venv/bin/python bench/test_sldea_liveview_probe.py
    .venv/bin/python bench/test_sldea_liveview_probe.py --seconds 20

    The loop ticks every 100 ms here (the view's own is 500 ms) to collect
    more ticks in the time; a tick's cost does not depend on its period.
    The run takes about twice --seconds.

OUTPUT
    Medians, 99th percentiles and maxima, in ms. If the bench's tick
    median or max differs much from the docstring's, put the bench's
    numbers, with the date and "Linux bench", into sldea_liveview's
    module docstring beside the Windows ones.
"""
# Runnable from anywhere: put the repo root (one level up) on sys.path.
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import argparse
import statistics
import threading
import time


def _stats(name, xs):
    xs = sorted(xs)
    if not xs:
        print(f"{name}: no samples")
        return
    p99 = xs[min(len(xs) - 1, int(round(0.99 * (len(xs) - 1))))]
    print(f"{name}: n={len(xs)}  median {statistics.median(xs) * 1e3:.2f}"
          f"  p99 {p99 * 1e3:.2f}  max {xs[-1] * 1e3:.2f} ms")


class _FakeRecorder:
    """VideoRecorder.latest() as the view sees it: a lock, one reference
    read, and a copy of the newest BGR frame, here always 0.05 s old."""

    def __init__(self, frame):
        self.frame = frame
        self.t0 = time.monotonic() - 30.0
        self._lock = threading.Lock()

    def latest(self, *a, **k):
        with self._lock:
            frame = self.frame
        return frame.copy(), time.monotonic() - 0.05 - self.t0

    def reader_alive(self):
        return True


class _App:
    """The run state the view reads, for a run that is going."""

    def __init__(self, root):
        self.root = root
        self._sldea_running = True
        self._sldea_stop = False
        self._sldea_elapsed = 1.0
        self._sldea_recorder = None
        self._sldea_live_still = None

    def _sldea_log(self, msg):
        pass


def _worker(root, secs, waits, spans):
    """root.after(0, f) every 3 ms, timing each call."""
    end = time.perf_counter() + secs
    while time.perf_counter() < end:
        t0 = time.perf_counter()
        root.after(0, lambda: None)
        t1 = time.perf_counter()
        waits.append(t1 - t0)
        spans.append((t0, t1))
        time.sleep(0.003)


def _phase(root, secs):
    """Run the real mainloop for `secs` while a worker thread calls
    root.after -> (waits, spans)."""
    waits, spans = [], []
    th = threading.Thread(target=_worker, args=(root, secs, waits, spans),
                          daemon=True)
    root.after(int((secs + 0.5) * 1000), root.quit)
    th.start()
    root.mainloop()
    th.join(5.0)
    return waits, spans


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--seconds', type=float, default=10.0,
                    help='length of each worker phase (default 10)')
    args = ap.parse_args(argv)

    import numpy as np
    import tkinter as tk
    import sldea_liveview as lv
    import sldea_profile

    frame = np.random.default_rng(1).integers(
        60, 200, size=(1080, 1920, 3), dtype=np.uint8)
    root = tk.Tk()
    root.geometry('300x100+40+40')
    app = _App(root)
    profile = sldea_profile.SldeaProfile(
        start_kv=0.0, end_kv=0.5, step_kv=0.25, ramp_s=10, landing_s=10,
        settle_s=1, snap_lead_s=1, baseline_warmup_s=1)
    view = lv.LiveView(app, period_ms=100)
    app._sldea_live_view = view
    view.begin_run(profile, True)
    app._sldea_recorder = _FakeRecorder(frame)   # this run's, not earlier
    view.open()
    root.update()

    polls, renders = [], []
    for _ in range(60):
        t0 = time.perf_counter()
        st = view.poll()
        t1 = time.perf_counter()
        lv.render(st['thumb'], st['kind'])
        polls.append(t1 - t0)
        renders.append(time.perf_counter() - t0)
    if st['kind'] != 'live':
        raise SystemExit(f"the view did not read the stream: {st['kind']}")
    print(f"Python {_sys.version.split()[0]}, Tk {tk.TkVersion}, "
          f"{_sys.platform}, frame {frame.shape[1]} x {frame.shape[0]}")
    _stats("A  poll() alone", polls)
    _stats("A  poll() + render(), no Tk paste", renders)

    ticks, tick_spans = [], []
    real_tick = view._tick

    def timed_tick():
        t0 = time.perf_counter()
        real_tick()
        t1 = time.perf_counter()
        ticks.append(t1 - t0)
        tick_spans.append((t0, t1))
    view._tick = timed_tick
    view._cancel()
    view._schedule()
    waits, spans = _phase(root, args.seconds)
    _stats("B  whole tick, Tk paste included", ticks)
    during, between = [], []
    for c0, c1 in spans:
        hit = any(t0 <= c0 < t1 for t0, t1 in tick_spans)
        (during if hit else between).append(c1 - c0)
    _stats("C  root.after, called during a tick", during)
    _stats("C  root.after, called between ticks", between)
    view.close()
    closed, _spans = _phase(root, args.seconds)
    _stats("C  root.after, view closed", closed)
    root.destroy()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
