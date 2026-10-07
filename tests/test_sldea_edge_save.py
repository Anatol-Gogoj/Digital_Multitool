#!/usr/bin/env python3
"""Edge Review's Save writes on a worker thread (#396, 2026-10-06).

Save used to do all of its file work on the window's Tk thread, with no
busy cursor: data.csv, the frame renames, setup.txt, the plot and an
overlay rewritten for every accepted frame. The window stopped repainting
for seconds. What these pin down:

  * the same Save, run on its worker thread and run synchronously, writes
    the same files byte for byte, and both write them in the order Save
    used before #396 (data.csv, renames, anchor, stamp, video hook, plot,
    overlays);
  * the file work runs on the worker; the matplotlib plot, the dialogs
    and the status strip run on the Tk thread;
  * a "Saving n/N" box counts every step, with the busy cursor, and both
    are gone afterwards;
  * while a Save writes, a second Save, the close box, the review keys
    and a card redraw are refused (the redraw is only put off);
  * an error inside the writing reaches the caller on the Tk thread, as
    it always did, and leaves nothing busy behind;
  * a window torn down mid-Save lets the worker finish the file in hand
    and stop, without hanging.

The tests drive a real EdgeReviewApp on a synthetic run and skip cleanly
when Tk cannot open a display.

Run: .venv/bin/python tests/test_sldea_edge_save.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import csv
import os
import shutil
import tempfile
import threading
import time

import numpy as np


class _Skip(Exception):
    """Could not run here -- reported, never counted as a pass."""


def _root():
    """A withdrawn Tk root, or _Skip without a display."""
    import sldea_edge_gui  # noqa: F401  (applies tk_fontfix before Tk)
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    root.withdraw()
    return root


def _gone(root):
    import tkinter as tk
    try:
        root.winfo_exists()
    except tk.TclError:
        return True
    return False


def _fire_binding(widget, sequence):
    """Run the Python callback bound to `sequence` on `widget` the way Tk
    runs it, with a stand-in event. A generated key never reaches a
    withdrawn window (it has no keyboard focus), and these tests keep
    their windows withdrawn so they take no focus from anything else on
    the desktop."""
    import re
    m = re.search(r'\[(\S+) ', widget.bind(sequence))
    assert m, f"nothing bound to {sequence}"
    args = ['0'] * 19            # tkinter's %-substitutions, in its order
    args[14] = str(widget)       # %W
    return widget.tk.call(m.group(1), *args)


def _fake_run(dirpath, n_act=10):
    """A baseline and `n_act` activated frames whose disc grows: the scene
    test_sldea_edge_gui's _fake_run draws, with more frames, so a Save
    has renames, a reject and an unreviewed row to write."""
    import cv2
    frames = os.path.join(dirpath, 'frames')
    os.makedirs(frames, exist_ok=True)
    cols = ['snapshot', 'step', 'tag', 'nominal_kV', 'control_V',
            'measured_kV', 'measured_uA', 't_planned_s', 'timestamp',
            'frame_file', 'active_area_px', 'active_area_mm2',
            'active_diam_mm', 'wrinkle_idx', 'notes']
    rows = []
    yy, xx = np.mgrid[0:240, 0:320]
    specs = [('baseline', 0.0, 0)] + [
        ('post-ramp' if k % 2 else 'pre-ramp', 0.5 * (k + 1), 30 + 4 * k)
        for k in range(n_act)]
    for k, (tag, kv, r) in enumerate(specs):
        img = np.full((240, 320), 190.0, np.float32)
        img[(xx - 160) ** 2 + (yy - 120) ** 2 <= 80 * 80] = 165.0
        if r:
            img[(xx - 160) ** 2 + (yy - 120) ** 2 <= r * r] += 35
        fn = f'SLDEA_s{k:02d}_{kv:05.2f}kV_{tag}.png'
        cv2.imwrite(os.path.join(frames, fn),
                    np.clip(img, 0, 255).astype(np.uint8))
        rows.append({**{c: '' for c in cols}, 'tag': tag, 'nominal_kV': kv,
                     'frame_file': fn, 'step': k, 'snapshot': k + 1,
                     'measured_uA': f"{1.0 + 0.1 * k:.2f}"})
    with open(os.path.join(dirpath, 'data.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(dirpath, 'setup.txt'), 'w') as f:
        f.write("SLDEA Test -- synthetic\nDEA nominal diameter: 16 mm\n")
    return dirpath


def _snapshot(folder):
    """{relative path: bytes} for every file under `folder`."""
    out = {}
    for base, _dirs, files in os.walk(folder):
        for n in files:
            p = os.path.join(base, n)
            with open(p, 'rb') as f:
                out[os.path.relpath(p, folder)] = f.read()
    return out


class _MB:
    """messagebox stand-in: records (name, title, on the main thread?) and
    answers yes."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def answer(*a, **k):
            self.calls.append((name, a[0] if a else '',
                               threading.current_thread()
                               is threading.main_thread()))
            return True
        return answer


class _Spies:
    """Wraps the functions Save writes through, recording (label, on the
    main thread?) in call order, and puts them back on exit."""

    def __init__(self, gui, app, order):
        import cv2
        self.order = order
        self.saved = []
        self.targets = [(gui.se, n, n) for n in
                        ('write_back', 'apply_rename_plan',
                         'save_scale_anchor', 'stamp_area_estimator')]
        self.targets += [(cv2, 'imwrite', 'imwrite'),
                         (app, '_video_after_save', 'after_save'),
                         (app, '_save_plot', 'save_plot')]

    def __enter__(self):
        for owner, name, label in self.targets:
            real = getattr(owner, name)
            self.saved.append((owner, name, real,
                               name in vars(owner) if not isinstance(
                                   owner, type(os)) else True))

            def wrapper(*a, _real=real, _label=label, **k):
                self.order.append((_label, threading.current_thread()
                                   is threading.main_thread()))
                return _real(*a, **k)
            setattr(owner, name, wrapper)
        return self

    def __exit__(self, *exc):
        for owner, name, real, had in reversed(self.saved):
            if had:
                setattr(owner, name, real)
            else:
                delattr(owner, name)
        return False


# Save's order before #396, as f69eade's synchronous save() made the
# calls (checked once against that code on this suite's scene, 24 files
# byte-identical): then one overlay per accepted frame.
ORDER_BEFORE_396 = ['write_back', 'apply_rename_plan', 'save_scale_anchor',
                    'stamp_area_estimator', 'after_save', 'save_plot']


class _DirectJob:
    """A SaveJob that runs everything on the calling thread: the Save
    exactly as it ran before #396, for the byte-for-byte comparison."""

    def step(self, what):
        pass

    def call(self, fn, *a, **kw):
        return fn(*a, **kw)


def _prepared_app(gui, root, run):
    """An app on `run` with a manual anchor, a detection pass, a reviewed
    reject, an unreviewed frame and a confirmed breakdown flag (so the
    Save renames three frames)."""
    app = gui.EdgeReviewApp(root, path=run)
    assert app.run is not None, "synthetic run failed to load"
    fit = app._auto_disc()
    assert fit and fit.get('diam_px'), "fixture has no automatic fit"
    app.manual_ref = {'method': gui.se.ANCHOR_METHOD_MANUAL,
                      'diam_px': float(fit['diam_px']),
                      'cal_mode': 'twopoint', 'n_rounds': 5,
                      'spread_pct': 0.5, 'se_pct': 0.1}
    app.detect_all_sync()
    rows = app.frame_rows
    app.results[rows[3]] = None
    app.results.pop(rows[5], None)
    app.flags = {rows[8]: 'breakdown? (synthetic)'}
    return app


def test_the_threaded_save_writes_what_the_synchronous_one_did():
    """Two identical runs (same run name, two parents). One is saved with
    the writing run synchronously on the Tk thread, as before #396; the
    other with it on the worker thread. Every file under both run folders
    is compared byte for byte, the order of the writing calls is the
    order before #396, and in the threaded Save only the plot ran on the
    main thread. The anchor's `saved:` time is pinned for both."""
    import sldea_edge_gui as gui
    root = _root()
    real_mb, real_strftime = gui.messagebox, time.strftime
    d = tempfile.mkdtemp(prefix='edge_save_bytes_')
    try:
        time.strftime = lambda fmt, *a: '2026-10-06T12:00:00'
        name = 'SLDEA_20261006_120000'
        a = _fake_run(os.path.join(d, 'sync', name))
        b = _fake_run(os.path.join(d, 'thread', name))
        assert _snapshot(a) == _snapshot(b), "the runs differ before Save"
        orders, dialogs = {}, {}
        for label, run in (('sync', a), ('thread', b)):
            mb = gui.messagebox = _MB()
            app = _prepared_app(gui, root, run)
            if label == 'sync':
                app._save_in_background = (
                    lambda work, total: work(_DirectJob()))
            order = orders[label] = []
            with _Spies(gui, app, order):
                app.save()
            dialogs[label] = [c[:2] for c in mb.calls]
            assert app.status.cget('text').startswith('saved in '), \
                app.status.cget('text')
        sa, sb = _snapshot(a), _snapshot(b)
        assert sorted(sa) == sorted(sb), sorted(set(sa) ^ set(sb))
        differ = [rel for rel in sa if sa[rel] != sb[rel]]
        assert not differ, f"not byte-identical: {differ}"
        # what this Save writes, so a fixture change cannot hollow it out
        assert 'data.csv.bak' in sa and 'area_vs_voltage.png' in sa
        overlays = [r for r in sa if r.startswith('overlays')]
        renamed = [r for r in sa if r.startswith('frames')
                   and '_BREAKDOWN' in r]
        assert len(overlays) == 9 and len(renamed) == 3, (overlays, renamed)
        expect = ORDER_BEFORE_396 + ['imwrite'] * len(overlays)
        for label in ('sync', 'thread'):
            assert [o[0] for o in orders[label]] == expect, (
                label, orders[label])
        on_main = {lab for lab, main in orders['thread'] if main}
        assert on_main == {'save_plot'}, orders['thread']
        assert dialogs['sync'] == dialogs['thread'] == [
            ('askyesno', 'Save results')], dialogs
    finally:
        time.strftime = real_strftime
        gui.messagebox = real_mb
        if not _gone(root):
            root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_the_saving_box_counts_every_step_with_the_busy_cursor():
    """The box says "Saving n/N" for every step, N being the six fixed
    steps plus one per accepted frame, and names what is being written.
    While the plot is drawn (on the Tk thread, mid-Save) the box is on
    screen holding the grab, the window shows the busy cursor and a Save
    is marked as running; afterwards none of that is left. This one test
    shows its window: the box is only shown over a window on screen."""
    import tkinter as tk
    import sldea_edge_gui as gui
    root = _root()
    real_mb = gui.messagebox
    d = tempfile.mkdtemp(prefix='edge_save_box_')
    try:
        gui.messagebox = _MB()
        run = _fake_run(os.path.join(d, 'SLDEA_20261006_120000'))
        app = _prepared_app(gui, root, run)
        root.deiconify()
        root.update()
        accepted = sum(1 for r in app.results.values() if r)
        real_dialog, real_plot = app._save_dialog, app._save_plot
        shown, seen = [], {}

        def dialog(total):
            dlg, show = real_dialog(total)
            seen['total'], seen['dlg'] = total, dlg

            def spy(n, what):
                shown.append((n, what))
                show(n, what)
            return dlg, spy

        def plot(scale):
            dlg = seen['dlg']
            seen['cursor'] = root.cget('cursor')
            seen['busy'] = app._save_busy
            seen['up'] = bool(dlg.winfo_viewable())
            seen['grab'] = str(root.grab_current()) == str(dlg)
            seen['title'] = dlg.title()
            return real_plot(scale)
        app._save_dialog, app._save_plot = dialog, plot
        app.save()
        total = gui.SAVE_FIXED_STEPS + accepted
        assert seen['total'] == total, (seen['total'], total)
        # (step 0, "starting", is drawn before this spy is in place)
        assert [n for n, _w in shown] == list(range(1, total + 1)), shown
        whats = [None] + [w for _n, w in shown]
        assert whats[1].startswith('data.csv'), whats
        assert whats[2] == 'frame file renames (3)', whats
        assert whats[3:7] == ['setup.txt: the scale anchor',
                              'setup.txt: the area-method stamp',
                              'video edges: checking whether they need a '
                              're-run', 'area_vs_voltage.png'], whats
        assert whats[-1].startswith('overlays: ') and \
            whats[-1].endswith(f'({accepted}/{accepted})'), whats
        assert seen['cursor'] == 'watch' and seen['busy'] is True, seen
        assert seen['up'] and seen['grab'], seen
        assert seen['title'] == 'Saving…', seen
        # and nothing of it is left
        assert not app._save_busy
        assert root.cget('cursor') == '' and root.grab_current() is None
        assert not [w for w in root.winfo_children()
                    if isinstance(w, tk.Toplevel)]
        assert app.status.cget('text').startswith('saved in ')
    finally:
        gui.messagebox = real_mb
        if not _gone(root):
            root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_a_second_save_a_close_a_key_and_a_redraw_wait_for_the_save():
    """With the worker held inside data.csv's write, the Tk thread keeps
    running (it is what serves this test's callbacks) and refuses: a
    second Save (no second question, no second write), the close box
    (the window stays), the R key (no frame is rejected) and a card
    redraw (put off until the Save is over, then done once)."""
    import sldea_edge_gui as gui
    root = _root()
    real_mb = gui.messagebox
    real_write = gui.se.write_back
    d = tempfile.mkdtemp(prefix='edge_save_refuse_')
    gate = threading.Event()
    writes, saw = [], {}
    try:
        mb = gui.messagebox = _MB()
        run = _fake_run(os.path.join(d, 'SLDEA_20261006_120000'))
        app = _prepared_app(gui, root, run)
        before = dict(app.results)
        app.pos = app.frame_rows.index(app.frame_rows[1])
        drawn = []
        real_draw = app._draw
        app._draw = lambda *a, **k: (drawn.append(a), real_draw(*a, **k))

        def held_write(*a, **k):
            writes.append(threading.current_thread()
                          is threading.main_thread())
            assert gate.wait(30), "the test never released the write"
            return real_write(*a, **k)
        gui.se.write_back = held_write

        class _Ev:
            width, height = 640, 480       # a resize, as <Configure> says

        def meanwhile():
            if not writes:                 # the worker is not there yet
                root.after(20, meanwhile)
                return
            asked = len(mb.calls)
            app.save()
            saw['second_asked'] = len(mb.calls) - asked
            app._close_request()
            saw['open_after_close'] = not _gone(root)
            _fire_binding(root, '<Key-r>')
            saw['results_after_key'] = dict(app.results)
            # its redraw comes due 120 ms later, with the Save still held
            app._canvas_resized(_Ev())
            root.after(400, release)

        def release():
            saw['drawn_during'] = len(drawn)
            gate.set()
        root.after(20, meanwhile)
        app.save()
        assert writes == [False], writes   # one write, on the worker
        assert saw['second_asked'] == 0, saw
        assert saw['open_after_close'], saw
        assert saw['results_after_key'] == before, "R rejected a frame"
        assert saw['drawn_during'] == 0, saw
        # the put-off redraw happens once the Save is over
        end = time.monotonic() + 3.0
        while not drawn and time.monotonic() < end:
            root.update()
            time.sleep(0.02)
        assert len(drawn) == 1, len(drawn)
        assert app.status.cget('text').startswith('saved in ')
        assert [c[0] for c in mb.calls] == ['askyesno'], mb.calls
        # and with no Save running, the close box closes as before
        app._close_request()
        assert _gone(root)
    finally:
        gate.set()
        gui.se.write_back = real_write
        gui.messagebox = real_mb
        if not _gone(root):
            root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_the_dialogs_and_the_strip_stay_on_the_tk_thread():
    """A failed data.csv write still shows "Save FAILED" and renames
    nothing; failed renames and a failed stamp still show their boxes;
    every one of them is shown on the Tk thread, and so is the strip."""
    import sldea_edge_gui as gui
    root = _root()
    se = gui.se
    real = (gui.messagebox, se.write_back, se.apply_rename_plan,
            se.stamp_area_estimator)
    d = tempfile.mkdtemp(prefix='edge_save_dialogs_')
    try:
        run = _fake_run(os.path.join(d, 'SLDEA_20261006_120000'))
        app = _prepared_app(gui, root, run)
        strips = []
        real_config = app.status.config

        def config(*a, **k):
            if 'text' in k:
                strips.append(threading.current_thread()
                              is threading.main_thread())
            return real_config(*a, **k)
        app.status.config = config

        def no_disk(*_a, **_k):
            raise OSError(28, 'No space left on device')
        renames = []
        se.apply_rename_plan = lambda plan: (renames.append(plan) or
                                             (0, []))
        mb = gui.messagebox = _MB()
        se.write_back = no_disk
        app.save()
        assert [c[:2] for c in mb.calls] == [('askyesno', 'Save results'),
                                            ('showerror', 'Save FAILED')]
        assert not renames, "a frame rename ran after data.csv failed"
        se.write_back = real[1]
        se.apply_rename_plan = lambda plan: (0, ['x.png: access denied'])
        se.stamp_area_estimator = no_disk
        mb = gui.messagebox = _MB()
        app.save()
        assert [c[:2] for c in mb.calls] == [
            ('askyesno', 'Save results'),
            ('showwarning', 'Save: renames incomplete'),
            ('showwarning', 'Save: area-method stamp not written')], mb.calls
        assert all(c[2] for c in mb.calls), mb.calls
        assert strips and all(strips), strips
    finally:
        (gui.messagebox, se.write_back, se.apply_rename_plan,
         se.stamp_area_estimator) = real
        if not _gone(root):
            root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_an_error_inside_the_writing_reaches_the_caller():
    """An exception nobody handles inside the writing is raised by save()
    on the Tk thread, where it always surfaced, and leaves no Save
    running, no busy cursor and no box behind."""
    import tkinter as tk
    import sldea_edge_gui as gui
    root = _root()
    real_mb, real_onset = gui.messagebox, gui.se.wrinkle_onset
    d = tempfile.mkdtemp(prefix='edge_save_raise_')
    try:
        gui.messagebox = _MB()
        run = _fake_run(os.path.join(d, 'SLDEA_20261006_120000'))
        app = _prepared_app(gui, root, run)

        def boom(*a, **k):
            raise RuntimeError('a bug in the writing')
        gui.se.wrinkle_onset = boom
        try:
            app.save()
        except RuntimeError as e:
            assert str(e) == 'a bug in the writing', e
        else:
            raise AssertionError("the error did not reach save()'s caller")
        assert not app._save_busy and root.cget('cursor') == ''
        assert not [w for w in root.winfo_children()
                    if isinstance(w, tk.Toplevel)]
    finally:
        gui.se.wrinkle_onset = real_onset
        gui.messagebox = real_mb
        if not _gone(root):
            root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_a_window_torn_down_mid_save_lets_the_worker_stop_cleanly():
    """The close box is refused during a Save, but a teardown from
    outside is not. Then save() returns at once, the worker finishes
    the file in hand (data.csv), stops at its next call into the gone
    window instead of waiting for it for ever, and its thread ends."""
    import sldea_edge_gui as gui
    root = _root()
    real_mb = gui.messagebox
    real_write = gui.se.write_back
    d = tempfile.mkdtemp(prefix='edge_save_teardown_')
    gate = threading.Event()
    reached = threading.Event()
    try:
        gui.messagebox = _MB()
        run = _fake_run(os.path.join(d, 'SLDEA_20261006_120000'))
        app = _prepared_app(gui, root, run)

        def held_write(*a, **k):
            reached.set()
            assert gate.wait(30)
            return real_write(*a, **k)
        gui.se.write_back = held_write

        def teardown():
            if not reached.is_set():
                root.after(20, teardown)
                return
            root.destroy()
            gate.set()
        root.after(20, teardown)
        assert app.save() is None
        assert _gone(root)
        workers = [t for t in threading.enumerate()
                   if t.name == 'edge-review-save']
        for t in workers:
            t.join(15)
        assert not any(t.is_alive() for t in workers), "the worker hung"
        with open(os.path.join(run, 'data.csv'), newline='',
                  encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        assert any((r.get('active_area_px') or '').strip() for r in rows), \
            "the data.csv write in hand did not finish"
        assert not os.path.exists(os.path.join(run, 'area_vs_voltage.png'))
    finally:
        gate.set()
        gui.se.write_back = real_write
        gui.messagebox = real_mb
        if not _gone(root):
            root.destroy()
        shutil.rmtree(d, ignore_errors=True)


def test_a_save_job_that_lost_its_window_raises_instead_of_waiting():
    """SaveJob.call waits for the Tk thread's answer, and gives up with a
    TclError once the window is gone. Pure: no display needed."""
    import tkinter as tk
    import sldea_edge_gui as gui
    job = gui.SaveJob(3)
    job.step('one')
    assert job.q.get_nowait() == ('step', 1, 'one')
    out = {}

    def worker():
        try:
            job.call(lambda: 1)
        except tk.TclError as e:
            out['err'] = str(e)
    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.15)
    assert t.is_alive(), "call() did not wait for its answer"
    job.abandoned = True
    t.join(2)
    assert not t.is_alive() and 'closed during Save' in out.get('err', '')
    # and an answer that comes is handed back, error or value
    job2 = gui.SaveJob(1)
    res = {}

    def worker2():
        res['v'] = job2.call(lambda x: x * 2, 21)
        try:
            job2.call(lambda: 1 / 0)
        except ZeroDivisionError:
            res['raised'] = True
    t2 = threading.Thread(target=worker2)
    t2.start()
    for _ in range(2):
        kind, fn, a, kw, done, box = job2.q.get(timeout=2)
        try:
            box['value'] = fn(*a, **kw)
        except BaseException as e:
            box['error'] = e
        done.set()
    t2.join(2)
    assert res == {'v': 42, 'raised': True}, res


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
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
            continue
        except Exception:
            ran += 1
            failed.append((n, traceback.format_exc()))
            print('FAIL', n)
            continue
        ran += 1
        print('ok ', n)
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
