#!/usr/bin/env python3
"""Headless tests for the SLDEA video review window (sldea_video_review).

Builds a synthetic run with an FFV1 recording (test_sldea_video's
fixtures), runs the real video pass, writes accepted stills into data.csv
and their frame times into run.log, and drives the window. Needs a Tk
display and an OpenCV that writes FFV1; skips cleanly without either.

Run: .venv/bin/python tests/test_sldea_video_review.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import csv
import gc
import os
import shutil
import tempfile

import sldea_video as sv
import test_sldea_video as tv

_Skip = tv._Skip


def _root():
    import sldea_edge_gui  # noqa: F401  (applies tk_fontfix before Tk)
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    root.withdraw()
    return root


def _review_run(n=8):
    """A run whose video pass has run, with accepted stills: step 1 at
    frames 1 and 2 (their own detected areas, so those frames agree), step
    2 at frames 3 and 4 both recording 1.2 x frame 3's area (so the video
    frames there are 'off-stills'). Frame i is at t = 2 + i s. The
    synthetic disc outgrows the search window from frame 6, so frames 6
    and 7 have no edge, and the detector doubts frame 5."""
    tv._need_cv()
    d = tv._video_run(n)
    sv.detect_video(d, log=lambda m: None, plot=True)
    edges = sv.read_edges(d)
    area = {e['frame']: e['area_px'] for e in edges}
    for f in (1, 2, 3, 4):
        assert area[f], f"the synthetic disc was not found on frame {f}"
    cols = ['snapshot', 'step', 'tag', 'nominal_kV', 't_planned_s',
            'frame_file', 'active_area_px']
    rows = [{'snapshot': 1, 'step': 0, 'tag': 'baseline', 'nominal_kV': 0,
             't_planned_s': 0.0, 'frame_file': 'base.png',
             'active_area_px': ''}]
    log = []
    # (video frame, step, tag, frame whose area the still records, factor):
    # a landing's two stills read nearly the same area on the bench, so
    # both step-2 stills record frame 3's area (the synthetic disc grows
    # 30 % a frame, which no real landing does)
    for k, (f, step, tag, src, mult) in enumerate((
            (1, 1, 'post-ramp', 1, 1.0), (2, 1, 'pre-ramp', 2, 1.0),
            (3, 2, 'post-ramp', 3, 1.2), (4, 2, 'pre-ramp', 3, 1.2))):
        name = f"s{step}_{tag}.png"
        rows.append({'snapshot': k + 2, 'step': step, 'tag': tag,
                     'nominal_kV': 0.5 * f, 't_planned_s': 2.0 + f,
                     'frame_file': name,
                     'active_area_px': round(area[src] * mult, 1)})
        log.append(f"[00:00:{f:02d}] snap s{step} -> {name}  "
                   f"(frame t={2.0 + f:.2f}s)\n")
    with open(os.path.join(d, 'data.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(d, 'run.log'), 'w', encoding='utf-8') as fh:
        fh.writelines(log)
    return d


def _open(root, d):
    import sldea_video_review as vr
    return vr.VideoReviewWindow(root, d)


def test_the_window_opens_on_the_first_flagged_frame_and_walks_only_them():
    root = _root()
    d = None
    try:
        d = _review_run()
        w = _open(root, d)
        flagged = [i for i, f in enumerate(w.flags) if f['reasons']]
        by = {f['frame']: f['reasons'] for f in w.flags}
        assert by[3] == ['off-stills'] and by[4] == ['off-stills'], by
        assert by[1] == [] and by[2] == [], by
        assert 'detector' in by[5] and by[6] == ['no edge'], by
        assert w.cur == flagged[0], (w.cur, flagged)
        seen = [w.cur]
        for _ in range(len(flagged) + 2):
            w.step_flagged(+1)
            if w.cur != seen[-1]:
                seen.append(w.cur)
        assert seen == flagged, (seen, flagged)
        assert 'No undecided flagged frame after' in w.stat2.cget('text')
        w.step(-1)
        assert w.cur == flagged[-1] - 1
        assert w.stale is None, w.stale
        assert 'current' in w.head.cget('text')
        w.close()
    finally:
        root.destroy()
        if d:
            shutil.rmtree(d, ignore_errors=True)


def test_decisions_are_written_carry_their_area_and_survive_a_reopen():
    root = _root()
    d = None
    try:
        d = _review_run()
        w = _open(root, d)
        first = w.cur
        frame = w.edges[first]['frame']
        w.decide('accept')
        assert w.cur != first, "a decision moves on to the next flagged frame"
        rows = tv._read_csv(os.path.join(d, sv.VIDEO_REVIEW_FILENAME))
        assert [(int(r['frame']), r['decision']) for r in rows] == \
            [(frame, 'accept')], rows
        assert float(rows[0]['area_px']) == w.edges[first]['area_px']
        assert rows[0]['reasons'], "the decision records why it was asked"
        w.close()
        w = _open(root, d)
        assert w.decisions[frame]['decision'] == 'accept'
        assert w.dropped == 0
        assert w.cur != first, "a decided frame is not offered again"
        w.close()
        # the detector re-ran and now reads that frame differently: the
        # decision was about the old area, so it is dropped and said
        path = os.path.join(d, sv.VIDEO_EDGES_FILENAME)
        rows = tv._read_csv(path)
        for r in rows:
            if int(r['frame']) == frame:
                r['area_px'] = str(float(r['area_px']) + 50.0)
        with open(path, 'w', newline='', encoding='utf-8') as fh:
            wr = csv.DictWriter(fh, fieldnames=sv.EDGE_COLUMNS)
            wr.writeheader()
            wr.writerows(rows)
        w = _open(root, d)
        assert frame not in w.decisions and w.dropped == 1
        assert 'dropped' in w.head.cget('text')
        w.close()
    finally:
        root.destroy()
        if d:
            shutil.rmtree(d, ignore_errors=True)


def test_a_stretch_decision_covers_the_consecutive_flagged_frames():
    root = _root()
    d = None
    try:
        d = _review_run()
        w = _open(root, d)
        i3 = next(i for i, e in enumerate(w.edges) if e['frame'] == 3)
        w.show(i3)
        run = w.stretch(i3)
        assert [w.edges[i]['frame'] for i in run] == [3, 4, 5, 6, 7], run
        assert all(w.flags[i]['reasons'] for i in run)
        assert not (run[0] > 0 and w.flags[run[0] - 1]['reasons'])
        w.decide_stretch('reject')
        for i in run:
            assert w.decisions[w.edges[i]['frame']]['decision'] == 'reject'
        i1 = next(i for i, e in enumerate(w.edges) if e['frame'] == 1)
        w.show(i1)
        assert w.stretch(i1) == []
        n = len(w.decisions)
        w.decide_stretch('accept')
        assert len(w.decisions) == n
        assert 'not flagged' in w.stat2.cget('text')
        w.close()
    finally:
        root.destroy()
        if d:
            shutil.rmtree(d, ignore_errors=True)


def test_the_outline_is_detected_off_the_ui_thread_and_drawn():
    root = _root()
    d = None
    try:
        d = _review_run()
        w = _open(root, d)
        i2 = next(i for i, e in enumerate(w.edges) if e['frame'] == 2)
        w.show(i2)
        assert w.wait_outline(), "the outline never arrived"
        gen, contour, area, err = w.outline
        assert err is None and contour is not None and area, w.outline
        # the same detection the pass made, with its hysteresis: the area
        # re-detected is the file's
        assert abs(area - w.edges[i2]['area_px']) < 1.0, \
            (area, w.edges[i2]['area_px'])
        kinds = {w.cv.type(item) for item in w.cv.find_all()}
        assert {'image', 'polygon'} <= kinds, kinds
        # stepping before the worker answers: only the newest request is
        # drawn, never a stale outline over the next frame
        w.step(+1)
        w.step(+1)
        assert w.wait_outline()
        assert w.outline[0] == w.jobs.gen
        w.close()
    finally:
        root.destroy()
        if d:
            shutil.rmtree(d, ignore_errors=True)


def test_close_releases_the_video_redraws_the_figure_and_leaves_no_job():
    root = _root()
    d = None
    try:
        d = _review_run()
        png = os.path.join(d, sv.VIDEO_PLOT_FILENAME)
        before = os.path.getmtime(png)
        w = _open(root, d)
        w.decide('reject')
        os.utime(png, (before - 10, before - 10))
        w.close()
        assert w._cap is None
        assert os.path.getmtime(png) > before - 10, "the PNG was not redrawn"
        assert not root.tk.call('after', 'info'), \
            root.tk.call('after', 'info')
        w.close()                       # twice is harmless
    finally:
        root.destroy()
        if d:
            shutil.rmtree(d, ignore_errors=True)


def test_stale_edges_are_said_and_a_rerun_is_offered():
    import sldea_edge as se
    root = _root()
    d = None
    real = sv.launch_rerun
    started = []
    try:
        d = _review_run()
        s = se.load_settings(d)
        s['min_diff'] = float(s['min_diff']) + 1.0
        se.save_settings(d, s)
        w = _open(root, d)
        assert w.stale and 'min_diff' in w.stale, w.stale
        assert 'out of date' in w.head.cget('text')
        assert str(w.rerun_btn.cget('state')) != 'disabled'
        sv.launch_rerun = lambda rundir, popen=None: started.append(rundir)
        w.rerun()
        assert started == [d]
        assert str(w.rerun_btn.cget('state')) == 'disabled'
        assert 'background' in w.head.cget('text')
        w.close()
    finally:
        sv.launch_rerun = real
        root.destroy()
        if d:
            shutil.rmtree(d, ignore_errors=True)


def test_edges_whose_recording_is_not_in_the_folder_yet_say_so():
    """The post-run job writes video_edges.csv before it moves the
    recording into the run folder, and that copy is throttled to
    COPY_MAX_BPS (40 MB/s): about a minute per hour recorded at 1 fps
    (2.3 GB an hour, SLDEA_DECISIONS.md). A review opened in between, from
    the SLDEA tab's button or as the program, showed "this frame does not
    read" on every frame and said nothing about why (#395 review). It now
    says the recording is not in the folder yet and where its progress
    is, and a review opened once it is in reads the frames as before."""
    root = _root()
    d = held = None
    try:
        d = _review_run()
        held = tempfile.mkdtemp(prefix='sldea_video_staging_')
        for n in (sv.VIDEO_FILENAME, sv.VIDEO_INDEX_FILENAME):
            shutil.move(os.path.join(d, n), os.path.join(held, n))
        w = _open(root, d)
        head = w.head.cget('text')
        assert "not in this run's folder yet" in head and 'run.log' in head, \
            head
        said = [w.cv.itemcget(i, 'text') for i in w.cv.find_all()
                if w.cv.type(i) == 'text']
        assert said == [f"{sv.VIDEO_FILENAME} is not in the run folder yet"], \
            said
        assert str(w.rerun_btn.cget('state')) == 'disabled'
        w.close()
        for n in (sv.VIDEO_FILENAME, sv.VIDEO_INDEX_FILENAME):
            shutil.move(os.path.join(held, n), os.path.join(d, n))
        w = _open(root, d)
        assert 'not in this run' not in w.head.cget('text')
        assert w._img is not None, "a frame did not read with the recording in"
        w.close()
    finally:
        root.destroy()
        for folder in (d, held):
            if folder:
                shutil.rmtree(folder, ignore_errors=True)


def _run():
    # Failures are collected, not fatal (`#280`); skips are counted apart
    # and are not failures. gc after every case keeps Tk objects freed on
    # this thread (see test_sldea_edge_gui's _reap).
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    ran = skipped = 0
    failed = []
    for n in names:
        try:
            globals()[n]()
        except _Skip as why:
            skipped += 1
            print('skip', n, f'({why})')
            gc.collect()
            continue
        except Exception:
            ran += 1
            failed.append((n, traceback.format_exc()))
            print('FAIL', n)
            gc.collect()
            continue
        ran += 1
        print('ok ', n)
        gc.collect()
    tail = f"{ran} of {len(names)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped)"
    print(tail)
    if not failed:
        return 0
    head = f"{len(failed)} of {len(names)} tests failed"
    print(f"\n{head}")
    for name, tb in failed:
        print(f"===== FAIL {name} =====")
        print(tb.rstrip('\n'))
    print(f"===== end {head} =====")
    return 1


if __name__ == '__main__':
    raise SystemExit(_run())
