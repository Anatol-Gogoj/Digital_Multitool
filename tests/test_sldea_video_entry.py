#!/usr/bin/env python3
"""The ways into the video review window (#395).

Edge Review's button opened it only on the run loaded there. #395 opens it
from the plot window's run menu and from the SLDEA tab as well, each as a
process of its own (`python sldea_video_review.py RUN`, owner decision
2026-10-06), launched the way those windows already launch their sibling
tools. Pinned here:

* the program opens on a run whose recording is in its folder even before
  video_edges.csv exists, so the window itself says what is missing; a
  folder with no video, and a window that cannot open, are said in a box
  as well as on the console;
* the plot window's right-click menu offers Video review... for the run
  that was clicked, live only when that run's folder holds a recording,
  and the window starts one review per run.

Nothing here starts a process or opens a camera: every launch is a stub.
The window cases need a Tk display and skip cleanly without one.

Run: .venv/bin/python tests/test_sldea_video_entry.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import contextlib
import csv
import gc
import os
import shutil
import sys
import tempfile
import time

import sldea_video as sv

COLS = ['snapshot', 'step', 'tag', 'nominal_kV', 'control_V',
        'measured_kV', 'measured_uA', 't_planned_s', 'timestamp',
        'frame_file', 'active_area_px', 'active_area_mm2',
        'active_diam_mm', 'wrinkle_idx', 'notes']


class _Skip(Exception):
    """Raised by a case this PC cannot host: no Tk, or no display for it."""


def _tmp():
    return tempfile.mkdtemp(prefix='sldea_video_entry_')


def _run(parent, name, video=False, edges=False):
    """A run folder: data.csv (a baseline and one landing, no frame
    files) and setup.txt; with `video` the recording and its index, empty,
    since sldea_video.has_video asks only that both exist; with `edges` a
    video_edges.csv that holds its header only."""
    d = os.path.join(parent, name)
    os.makedirs(os.path.join(d, 'frames'), exist_ok=True)
    rows = [{'snapshot': 1, 'step': 0, 'tag': 'baseline', 'nominal_kV': 0,
             't_planned_s': 0.0, 'timestamp': '2026-10-06T10:00:00'},
            {'snapshot': 2, 'step': 1, 'tag': 'post-ramp',
             'nominal_kV': 1.0, 't_planned_s': 5.0,
             'timestamp': '2026-10-06T10:00:05'}]
    with open(os.path.join(d, 'data.csv'), 'w', newline='',
              encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({**{c: '' for c in COLS}, **r})
    with open(os.path.join(d, 'setup.txt'), 'w', encoding='utf-8') as f:
        f.write("SLDEA Test -- synthetic\nDEA nominal diameter: 16 mm\n")
    if video:
        _add_video(d)
    if edges:
        with open(os.path.join(d, sv.VIDEO_EDGES_FILENAME), 'w',
                  newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(sv.EDGE_COLUMNS)
    return d


def _add_video(d):
    for n in (sv.VIDEO_FILENAME, sv.VIDEO_INDEX_FILENAME):
        open(os.path.join(d, n), 'w').close()


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == \
        os.path.normcase(os.path.abspath(b))


def _tk():
    """The tkinter module, after tk_fontfix has been applied (the Edge
    Review import applies it); a Python built without Tk skips."""
    try:
        import tkinter
    except ImportError as e:
        raise _Skip(f"no tkinter in this Python: {e}")
    import sldea_edge_gui  # noqa: F401  (applies tk_fontfix before Tk)
    return tkinter


def _tk_root():
    tk = _tk()
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    root.withdraw()
    return root


def _pump(root, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        root.update()
        time.sleep(0.02)


def _destroy(root):
    """Destroy a test root without leaving its pending callbacks behind
    (a debounced redraw firing into a dead interpreter prints noise)."""
    try:
        for job in root.tk.splitlist(root.tk.call('after', 'info')):
            try:
                root.after_cancel(job)
            except Exception:
                pass
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass
    import tkinter as tk
    if getattr(tk, '_default_root', None) is root:
        tk._default_root = None


class _Proc:
    """A launched program as the launchers see it: poll() is None while
    it runs."""

    def __init__(self):
        self.rc = None

    def poll(self):
        return self.rc


class _Spawn:
    """Stands in for the subprocess module: records each Popen."""

    def __init__(self):
        self.calls = []

    def Popen(self, cmd, **kw):
        self.calls.append((list(cmd), dict(kw)))
        return _Proc()


class _Boxes:
    """messagebox stand-in: records every box as (title, text, parent)."""

    def __init__(self):
        self.infos, self.errors = [], []

    def showinfo(self, title=None, message=None, **k):
        self.infos.append((title, message, k.get('parent')))

    def showerror(self, title=None, message=None, **k):
        self.errors.append((title, message, k.get('parent')))


# ---------------------------------------------------------------------------
# the program: python sldea_video_review.py RUN
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _program_roots():
    """Every Tk root sldea_video_review.main makes, withdrawn and with
    mainloop stubbed, since a real one would hold the suite. -> the list
    of roots made."""
    tkinter = _tk()
    real = tkinter.Tk
    made = []

    class _Root(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.withdraw()
            self.looped = False
            made.append(self)

        def mainloop(self, n=0):
            self.looped = True

    try:
        probe = real()
    except tkinter.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    _destroy(probe)
    tkinter.Tk = _Root
    try:
        yield made
    finally:
        tkinter.Tk = real
        for r in made:
            _destroy(r)


@contextlib.contextmanager
def _review_boxes():
    """sldea_video_review's message boxes, recorded instead of shown (a
    real one is modal and would hold the suite). -> the _Boxes."""
    import sldea_video_review as vr
    had = hasattr(vr, 'messagebox')
    real = getattr(vr, 'messagebox', None)
    boxes = _Boxes()
    vr.messagebox = boxes
    try:
        yield boxes
    finally:
        if had:
            vr.messagebox = real
        else:
            del vr.messagebox


def test_the_program_opens_on_a_recording_whose_edges_are_not_made_yet():
    """The SLDEA tab and the plot window start the program on a run whose
    recording is in its folder. For a while after every video run, and
    for good on one recorded without "edges after", that folder has no
    video_edges.csv. The program refused such a run with one printed
    line, which a program started from a button prints where nobody reads
    it. It opens now, and the window says the edges are missing and
    offers Re-run. A folder with no video at all is still refused before
    any review window, now in a box as well as on the console: the SLDEA
    tab starts the program without looking in the folder first."""
    import sldea_video_review as vr
    p = _tmp()
    real_win = vr.VideoReviewWindow
    built = []

    class _Win(real_win):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            built.append(self)
    try:
        run = _run(p, 'SLDEA_20261006_100000', video=True)
        vr.VideoReviewWindow = _Win
        with _program_roots() as made, _review_boxes() as boxes:
            assert vr.main([run]) == 0
            assert len(made) == 1 and made[0].looped, made
            [w] = built
            assert w.win is made[0], "not opened as its own window"
            assert _same(w.rundir, run) and w.edges == []
            head = w.head.cget('text')
            assert 'out of date' in head and \
                'there are no video edges yet' in head, head
            assert 'has no rows' in w.stat1.cget('text'), \
                w.stat1.cget('text')
            assert str(w.rerun_btn.cget('state')) != 'disabled', \
                "Re-run is not offered"
            assert not (boxes.infos or boxes.errors), boxes.errors
            w.close()
            # a folder with no video at all: refused before any review
            # window, and in words on screen as well as on the console
            plain = _run(p, 'SLDEA_20261006_100500')
            assert vr.main([plain]) == 2
            assert len(built) == 1, "a review window for a run with no video"
            assert not any(r.looped for r in made[1:]), made
            assert len(boxes.infos) == 1 and not boxes.errors, boxes.infos
            title, text, _parent = boxes.infos[0]
            assert title == 'Video review'
            assert 'There is no video of SLDEA_20261006_100500' in text, text
            assert 'run.log' in text, text
            # edges without the recording in the folder still open, as
            # before (the post-run job writes them before it moves the
            # recording in)
            early = _run(p, 'SLDEA_20261006_101000', edges=True)
            assert vr.main([early]) == 0 and len(built) == 2
            built[-1].close()
    finally:
        vr.VideoReviewWindow = real_win
        shutil.rmtree(p, ignore_errors=True)


def test_a_review_that_cannot_open_says_why_on_screen():
    """Started from a button, the program has no console anyone reads. A
    window that fails to open (a share gone, an unreadable file) used to
    end in a traceback there and nothing on screen. It now says why in a
    box over its own root, then exits 1 without a main loop."""
    import sldea_video_review as vr
    p = _tmp()
    real_win = vr.VideoReviewWindow

    def broken(*a, **k):
        raise OSError("the share went away")
    try:
        run = _run(p, 'SLDEA_20261006_110000', video=True, edges=True)
        vr.VideoReviewWindow = broken
        with _program_roots() as made, _review_boxes() as boxes:
            assert vr.main([run]) == 1
            [root] = made
            assert not root.looped, "a main loop ran for a failed window"
            assert len(boxes.errors) == 1 and not boxes.infos, boxes.errors
            title, text, parent = boxes.errors[0]
            assert title == 'Video review'
            assert 'the share went away' in text, text
            assert 'SLDEA_20261006_110000' in text, text
            assert parent is root
            import tkinter
            try:
                alive = bool(root.winfo_exists())
            except tkinter.TclError:
                alive = False
            assert not alive, "the failed window's root was left alive"
    finally:
        vr.VideoReviewWindow = real_win
        shutil.rmtree(p, ignore_errors=True)


# ---------------------------------------------------------------------------
# the plot window's run menu
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _plot(parent):
    """A PlotWindow on `parent`, remembering nothing, whose right-click
    menu is never posted (a real tk_popup is modal on Windows)."""
    import sldea_plot_gui as g
    root = _tk_root()
    try:
        win = g.PlotWindow(root, parent, remember=False)
        real_gm = win.group_menu

        def gm():
            m = real_gm()
            m.tk_popup = lambda x, y: None
            return m
        win.group_menu = gm
        yield win
    finally:
        _destroy(root)


def _right_click(win, iid):
    """Right-click picker row `iid` ('' = below the rows) -> (the menu,
    the index of its last entry). The row is named directly: a withdrawn
    window lays nothing out to aim at."""
    win.run_box.identify_row = lambda y: iid

    class _E:
        x, y, x_root, y_root = 5, 5, 300, 200
    win._run_menu(_E())
    m = win._menu
    return m, m.index('end')


def _iids(win):
    return {os.path.basename(d): win._iid(i)
            for i, (d, _l) in enumerate(win.runs)}


def test_the_run_menu_offers_the_clicked_runs_video_review():
    """The `#383` menu gains Video review... for the run that was
    right-clicked: live when that run's folder holds a recording, grey
    with the reason in its label otherwise, and grey when the click
    named no run. Inside a multi-selection the selection stays and the
    clicked run is the one reviewed. The group cascade stays first."""
    import sldea_plot_gui as g
    p = _tmp()
    try:
        a = _run(p, 'A_video', video=True)
        b = _run(p, 'B_plain')
        with _plot(p) as win:
            rows = _iids(win)
            m, last = _right_click(win, rows['A_video'])
            assert m.type(0) == 'cascade', "the group cascade moved"
            assert m.type(last) == 'command' and \
                m.type(last - 1) == 'separator', (m.type(last - 1),
                                                   m.type(last))
            assert m.entrycget(last, 'label') == g.VIDEO_ITEM
            assert str(m.entrycget(last, 'state')) == 'normal'
            assert [_same(d, a) for d in win.selected_dirs()] == [True]
            spy = _Spawn()
            real = g.subprocess
            g.subprocess = spy
            try:
                m.invoke(last)
            finally:
                g.subprocess = real
            assert len(spy.calls) == 1 and _same(spy.calls[0][0][2], a), \
                spy.calls
            # a run with no video in its folder: grey, and it says why
            m, last = _right_click(win, rows['B_plain'])
            assert m.entrycget(last, 'label') == g.VIDEO_ITEM_NO_VIDEO
            assert str(m.entrycget(last, 'state')) == 'disabled'
            # inside a multi-selection: the selection stays, and the
            # clicked run is the one the entry is for
            win.set_selected_dirs([a, b])
            m, last = _right_click(win, rows['A_video'])
            assert len(win.selected_dirs()) == 2, win.selected_dirs()
            assert m.entrycget(last, 'label') == g.VIDEO_ITEM
            # a right-click below the rows, with runs selected: no run
            m, last = _right_click(win, '')
            assert m.entrycget(last, 'label') == g.VIDEO_ITEM_NO_RUN
            assert str(m.entrycget(last, 'state')) == 'disabled'
            assert m.type(0) == 'cascade'
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_the_plot_window_starts_one_review_per_run_as_its_own_process():
    """Owner decision 2026-10-06: a process of its own, launched as the
    plot window launches Edge Review from a double-click, so a decoder
    stall or crash cannot take the plot window down and the review
    outlives it. One live review per run from this window: a second
    request while it runs starts nothing and says so; another run is not
    held up; a closed review can be opened again."""
    import sldea_plot as sp
    import sldea_plot_gui as g
    p = _tmp()
    try:
        a = _run(p, 'A_video', video=True)
        c = _run(p, 'C_video', video=True)
        _run(p, 'B_plain')
        with _plot(p) as win:
            spy = _Spawn()
            real = g.subprocess
            g.subprocess = spy
            try:
                cmd = win.open_video_review(a)
                assert cmd is not None and len(spy.calls) == 1
                argv, kw = spy.calls[0]
                assert argv == cmd
                assert argv[0] == sys.executable
                assert os.path.basename(argv[1]) == 'sldea_video_review.py'
                assert os.path.isabs(argv[1]) and os.path.exists(argv[1])
                assert argv[2:] == [a], argv
                said = win.lbl_click.cget('text')
                assert 'Video review opening on A_video' in said, said
                # exactly the launch the double-click uses for Edge Review
                win.open_in_edge_review({'dir': a, 'name': 'A_video'},
                                        {'index': 0, 'snapshot': 1})
                assert kw == spy.calls[1][1] == {'start_new_session': True}
                assert spy.calls[1][0][0] == argv[0]
                # while that review runs, its run is not opened twice
                assert win.open_video_review(a) is None
                assert len(spy.calls) == 2
                said = win.lbl_click.cget('text')
                assert 'A_video' in said and 'still open' in said, said
                # another run is not held up by it
                assert win.open_video_review(c) is not None
                assert len(spy.calls) == 3
                # once the first review has closed, its run opens again
                win._video_reviews[sp.group_key(a)].rc = 0
                assert win.open_video_review(a) is not None
                assert len(spy.calls) == 4
                # a run with no video starts nothing, and says why
                assert win.open_video_review(
                    os.path.join(p, 'B_plain')) is None
                assert len(spy.calls) == 4
                assert 'no video in its folder' in win.lbl_click.cget('text')
            finally:
                g.subprocess = real
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_the_plot_windows_answer_survives_the_redraw_a_right_click_asks():
    """A right-click on a row outside the selection selects it, and the
    selection change queues a redraw, which puts the click-through hint
    back on the line the answer is written to. The redraw already asked
    for lands first, so the answer stays on screen."""
    import sldea_plot_gui as g
    p = _tmp()
    try:
        a = _run(p, 'A_video', video=True)
        with _plot(p) as win:
            _pump(win.root, 0.5)             # the window's own first redraw
            spy = _Spawn()
            real = g.subprocess
            g.subprocess = spy
            try:
                win.schedule()               # what the selection change does
                assert win._redraw_after is not None
                assert win.open_video_review(a) is not None
                assert win._redraw_after is None, "a redraw is still due"
                _pump(win.root, 0.4)
                said = win.lbl_click.cget('text')
                assert 'Video review opening on A_video' in said, said
            finally:
                g.subprocess = real
    finally:
        shutil.rmtree(p, ignore_errors=True)


def _run_all():
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
        print('ok  ', n)
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
    raise SystemExit(_run_all())
