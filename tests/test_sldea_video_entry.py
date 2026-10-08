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
  and the window starts one review per run;
* the SLDEA tab's button sits in the run row next to Live view... and
  gives way first when the row is short, steps out of the row while a run
  is going, follows the run that just ended (live when that run recorded
  video), and launches exactly like Edge Review... and Plot runs..., one
  review per run, without looking in the run folder;
* Edge Review's button acts on the run in the Run box whether or not it
  loaded, and looks at the folder again when the pointer comes onto it;
  a review that cannot read the run says why and leaves no window behind,
  in Edge Review's process and as the program alike.

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


def test_a_run_the_review_cannot_read_is_said_over_its_own_root():
    """The case above with the real window: the run's data.csv cannot be
    read. A window that fails part way now cleans up after itself (see the
    Edge Review case below), but the program's window IS its root, and the
    box that says why needs that root: it is left to open_standalone,
    which destroys it only after the box."""
    import sldea_edge as se
    import sldea_video_review as vr
    p = _tmp()
    real_load = se.load_run

    def unreadable(rundir):
        raise OSError("data.csv is locked")
    try:
        run = _run(p, 'SLDEA_20261006_113000', video=True, edges=True)
        se.load_run = unreadable
        with _program_roots() as made, _review_boxes() as boxes:
            assert vr.main([run]) == 1
            [root] = made
            assert not root.looped, "a main loop ran for a failed window"
            assert len(boxes.errors) == 1 and not boxes.infos, \
                (boxes.errors, boxes.infos)
            title, text, parent = boxes.errors[0]
            assert title == 'Video review'
            assert 'data.csv is locked' in text, text
            assert parent is root
            import tkinter
            try:
                alive = bool(root.winfo_exists())
            except tkinter.TclError:
                alive = False
            assert not alive, "the failed window's root was left alive"
    finally:
        se.load_run = real_load
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


# ---------------------------------------------------------------------------
# the SLDEA tab
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _gui():
    """(root, app): the real main window, with no instrument hunt and no
    camera preview (test_gui_tabs' recipe)."""
    root = _tk_root()
    import gui
    saved = (gui.InstrumentControlGUI.auto_connect, gui.CAM_AUTOSTART_ON_TAB)
    gui.InstrumentControlGUI.auto_connect = lambda self: None
    gui.CAM_AUTOSTART_ON_TAB = False
    try:
        app = gui.InstrumentControlGUI(root)
        root.withdraw()
        yield root, app
    finally:
        (gui.InstrumentControlGUI.auto_connect,
         gui.CAM_AUTOSTART_ON_TAB) = saved
        _destroy(root)


class _Rec:
    """A recorder as the run leaves it: `written` frames."""

    def __init__(self, written):
        self.written = written


def _end_run(app, rundir, rec):
    """What the run's worker leaves for _sldea_finished: its run.log (None
    for a run that never got a folder) and its recorder, then the Tk-side
    end of the run itself."""
    app._sldea_running = True
    app._sldea_runlog = os.path.join(rundir, 'run.log') if rundir else None
    app._sldea_recorder = rec
    app._sldea_finished()


def test_the_sldea_tab_has_the_button_next_to_live_view_giving_way_first():
    """In the run row, at the right next to Live view..., and packed AFTER
    it: a row too short for everything takes its room from this button
    first, never from the status line or Live view.... Grey until a run
    with video has ended in this session."""
    with _gui() as (_root, app):
        btn = app.sldea_video_btn
        slaves = btn.master.pack_slaves()
        texts = [str(w.cget('text')) for w in slaves]
        assert slaves[-1] is btn, texts
        assert texts[-2] == 'Live view…', texts
        assert slaves.index(app.sldea_status) < len(slaves) - 2, texts
        assert all(w.pack_info()['side'] == 'right' for w in slaves[-2:])
        assert str(btn.cget('state')) == 'disabled'
        assert app._sldea_video_run is None


# The widest status line a running run writes (the worker's one-second
# tick), and the longest alarm the run's end leaves on it: 235 and 254 px
# at 96 dpi, and main fits each beside a whole Live view... in the default
# 1320x800 window.
LIVE_STATUS = "LIVE  t=1234/3600s  ~10.25 kV  frames 12/34"
ALARM_STATUS = "⚡ NOT ZEROED — turn off SG/Trek manually!"


def _until(root, cond, timeout=3.0):
    """Pump Tk until cond() holds or `timeout` s pass -> cond(). A child's
    <Configure> lands 120 to 320 ms after a geometry change on this PC."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_a_run_gives_the_row_back_to_the_status_line_and_live_view():
    """Review finding (2026-10-06): beside Plot runs..., Video review...
    took 109 px of the run row, and in the default 1320x800 window it left
    Live view... 6 px of its 76 beside a running run's status line and
    pushed it off the row after a run that ended on "NOT ZEROED". Behind a
    maximized main window the live view is reached only through that
    button.

    The start path now takes Video review... out of the row once the
    worker has started, and _sldea_finished puts it back as the row's last
    slave, after Live view.... During the run the row holds the widgets it
    held before #395, in the same order, so every width in it is main's at
    any window size; at 1320x800, beside the widest running status line,
    Abort, the status line and Live view... each get the full width they
    ask for (where main's row has the room). After the run, beside the
    longest alarm, the status line and Live view... get what they get in
    main's row, the row without the button: the button gives way first."""
    import inspect
    import gui
    with _gui() as (root, app):
        root.geometry('1320x800+0+0')
        root.deiconify()
        assert app.select_manual_tab('sldea'), "cannot find the SLDEA tab"
        btn = app.sldea_video_btn
        row = btn.master
        live = [w for w in row.pack_slaves()
                if str(w.cget('text')) == 'Live view…'][0]
        assert _until(root, lambda: live.winfo_ismapped())
        idle = row.pack_slaves()
        assert btn in idle
        full = (app.sldea_abort_btn, app.sldea_status, live)

        def widths():
            return [(w.winfo_ismapped(), w.winfo_width()) for w in full]

        # what sldea_run does once the worker is on its way, then what the
        # worker writes on the status line every second
        app._sldea_running = True
        app.sldea_run_btn.config(state='disabled')
        app.sldea_abort_btn.config(state='normal')
        gui.sldea_video_btn_sync(app)
        app.sldea_status.config(text=LIVE_STATUS)
        _until(root, lambda: all(w.winfo_width() == w.winfo_reqwidth()
                                 for w in full))
        # what main's row asks for: this row less the button, if it stayed
        # (its request plus its 8 px of padding)
        main_req = row.winfo_reqwidth() - (
            btn.winfo_reqwidth() + 8 if btn.winfo_manager() else 0)
        if main_req <= row.winfo_width():
            # main's row has the room for all of it here (this PC, 96 dpi)
            for w in full:
                assert w.winfo_ismapped(), w.cget('text')
                assert w.winfo_width() == w.winfo_reqwidth(), (
                    f"{w.cget('text')!r} is {w.winfo_width()} px wide "
                    f"during a run, of the {w.winfo_reqwidth()} it asks for")
        else:
            print(f"   (main's row would ask {main_req} px of "
                  f"{row.winfo_width()} on this PC; widths not compared)")
        assert not btn.winfo_manager(), "Video review... stayed in the row"
        assert row.pack_slaves() == [w for w in idle if w is not btn]
        # the run ends: the button is back after Live view..., the row is
        # as it was, and beside the longest alarm the button gives way,
        # never the status line or Live view...
        app._sldea_runlog = None
        app._sldea_finished()
        assert row.pack_slaves() == idle, row.pack_slaves()
        assert str(btn.cget('state')) == 'disabled'
        app.sldea_status.config(text=ALARM_STATUS)
        btn.pack_forget()                    # main's row, for the reference
        _pump(root, 0.6)
        on_main = widths()
        gui.sldea_video_btn_sync(app)        # back, as the run's end puts it
        _pump(root, 0.6)
        assert row.pack_slaves() == idle, row.pack_slaves()
        assert widths() == on_main, (
            f"beside {ALARM_STATUS!r}: (mapped, width) of Abort, the status "
            f"line and Live view... are {widths()}, and {on_main} without "
            f"the button")
    # ...and it is the real start path that steps it aside: last, once the
    # worker has started and the live view has opened
    src = inspect.getsource(gui.InstrumentControlGUI.sldea_run)
    assert 'sldea_video_btn_sync(self)' in src, \
        "sldea_run never takes Video review... out of the row"
    started = src.index('daemon=True).start()')
    opened = src.index("sldea_liveview.notify(self, 'open_with_run')")
    stepped = src.index('sldea_video_btn_sync(self)')
    assert started < opened < stepped, (started, opened, stepped)


def test_the_sldea_tab_button_follows_the_run_that_just_ended():
    """It opens the video of the last run this tab finished, so each run's
    end moves it on: live after a run whose own recorder wrote frames;
    grey after a run without video (the recorder attribute still holds the
    previous run's), after a recorder that wrote nothing, and after a run
    that never got a folder. Its bookkeeping never raises: the live view
    is told of the end after it whatever it met."""
    import gui
    p = _tmp()
    try:
        runs = [_run(p, f'RUN{k}', video=True) for k in range(5)]
        with _gui() as (_root, app):
            btn = app.sldea_video_btn
            rec = _Rec(12)
            _end_run(app, runs[0], rec)
            assert _same(app._sldea_video_run, runs[0])
            assert str(btn.cget('state')) == 'normal'
            # the next run recorded nothing: _sldea_recorder still holds
            # the first run's recorder, which is not this run's
            _end_run(app, runs[1], rec)
            assert app._sldea_video_run is None
            assert str(btn.cget('state')) == 'disabled'
            # a recorder of its own that wrote nothing (no stream, or the
            # codec check stopped the run)
            _end_run(app, runs[2], _Rec(0))
            assert app._sldea_video_run is None
            # a run that never got a folder
            _end_run(app, None, _Rec(5))
            assert app._sldea_video_run is None
            # a video run again
            _end_run(app, runs[3], _Rec(3))
            assert _same(app._sldea_video_run, runs[3])
            assert str(btn.cget('state')) == 'normal'

            class _Broken:
                @property
                def written(self):
                    raise RuntimeError("recorder state unreadable")
            told = []
            real_notify = gui.sldea_liveview.notify
            gui.sldea_liveview.notify = \
                lambda app_, action, *a: told.append(action) or True
            try:
                _end_run(app, runs[4], _Broken())
            finally:
                gui.sldea_liveview.notify = real_notify
            assert told == ['end_run'], told
            assert app._sldea_video_run is None, "left on the previous run"
            assert str(btn.cget('state')) == 'disabled'
            assert str(app.sldea_run_btn.cget('state')) == 'normal'
    finally:
        shutil.rmtree(p, ignore_errors=True)


def test_the_sldea_tab_launches_the_review_like_its_neighbours():
    """The same interpreter, inherited working directory and detach flag
    as Edge Review... and Plot runs..., and one review per run from this
    button. The press never looks in the run folder, which is usually on
    the share: it runs on the Tk thread of the app that drives the HV, and
    the run worker's own Tk calls wait on that thread. A recording that
    is not in the folder yet is the review program's to report.

    Since #429 all three send their output to a log file of their own
    (launch_check), and the status line says "starting" until the program
    has stayed up for launch_check.CHECK_MS, then "opened"."""
    import gui
    import launch_check
    import subprocess
    p = _tmp()
    spy, boxes = _Spawn(), _Boxes()
    looked = []
    real_sp, real_mb = gui.subprocess, gui.messagebox
    real_has = gui.sldea_video.has_video
    real_logs = launch_check.LOG_DIR
    logs = launch_check.LOG_DIR = os.path.join(p, 'launch_logs')

    def has_video(rundir):
        looked.append(rundir)
        return real_has(rundir)
    try:
        run = _run(p, 'SLDEA_20261006_120000', video=True)
        later = _run(p, 'SLDEA_20261006_130000')
        with _gui() as (root, app):
            gui.subprocess, gui.messagebox = spy, boxes
            gui.sldea_video.has_video = has_video
            app._sldea_open_plot(run)
            app._sldea_open_edge_review(run)
            (plot_argv, plot_kw), (edge_argv, edge_kw) = spy.calls
            del spy.calls[:]
            _end_run(app, run, _Rec(40))
            app.sldea_video_btn.invoke()
            assert len(spy.calls) == 1, spy.calls
            argv, kw = spy.calls[0]
            assert argv[0] == plot_argv[0] == edge_argv[0] == sys.executable
            assert os.path.basename(argv[1]) == 'sldea_video_review.py'
            assert os.path.dirname(argv[1]) == os.path.dirname(plot_argv[1])
            assert os.path.exists(argv[1])
            assert argv[2:] == [run], argv
            # detached as before, no working folder of its own, the app's
            # environment with PYTHONUNBUFFERED=1, and its stdout and
            # stderr in one log file per start
            for k in (kw, plot_kw, edge_kw):
                assert set(k) == {'start_new_session', 'stdout', 'stderr',
                                  'env'}, k
                assert k['start_new_session'] is True
                assert k['stderr'] == subprocess.STDOUT
                assert k['env'] == dict(os.environ, PYTHONUNBUFFERED='1')
                assert k['stdout'].closed, "the app kept the log open"
            assert len({id(k['stdout']) for k in (kw, plot_kw, edge_kw)}) == 3
            assert len([n for n in os.listdir(logs) if n.endswith('.log')]) \
                == 3, os.listdir(logs)
            said = app.status_bar.cget('text')
            assert said == 'Video review starting on SLDEA_20261006_120000…', \
                said
            assert _until(root, lambda: app.status_bar.cget('text') ==
                          'Video review opened on SLDEA_20261006_120000',
                          timeout=launch_check.CHECK_MS / 1000.0 + 3.0), \
                app.status_bar.cget('text')
            # while it runs, a second press starts nothing and says so
            app.sldea_video_btn.invoke()
            assert len(spy.calls) == 1
            said = app.status_bar.cget('text')
            assert 'already open' in said and 'SLDEA_20261006_120000' in said
            # once it has closed, the press opens it again
            next(iter(app._sldea_video_reviews.values())).rc = 0
            app.sldea_video_btn.invoke()
            assert len(spy.calls) == 2
            # a video run whose recording is still on its way in: the
            # program is started all the same, and says so itself
            _end_run(app, later, _Rec(40))
            assert str(app.sldea_video_btn.cget('state')) == 'normal'
            app.sldea_video_btn.invoke()
            assert len(spy.calls) == 3 and spy.calls[2][0][2:] == [later]
            assert not (boxes.infos or boxes.errors), boxes.infos
            assert looked == [], f"the main app looked in {looked}"
    finally:
        gui.subprocess, gui.messagebox = real_sp, real_mb
        gui.sldea_video.has_video = real_has
        launch_check.LOG_DIR = real_logs
        shutil.rmtree(p, ignore_errors=True)


# ---------------------------------------------------------------------------
# Edge Review
# ---------------------------------------------------------------------------

def test_edge_review_reviews_the_run_in_the_box_even_when_it_did_not_load():
    """The review needs the run's folder, never Edge Review's own load or
    detection: a run that could not be loaded, but whose recording is in
    its folder, still has its video reviewed from the button."""
    import sldea_edge_gui as eg
    import sldea_video_review as vr
    root = _tk_root()
    p = _tmp()
    real_load, real_mb, real_win = eg.se.load_run, eg.messagebox, \
        vr.VideoReviewWindow
    opened = []

    class _Win:
        def __init__(self, master, rundir, on_close=None):
            self.rundir, self.on_close = rundir, on_close
            self._closed = False
            self.win = self
            opened.append(self)

        def lift(self):
            pass

        def close(self):
            self._closed = True
    try:
        run = _run(p, 'SLDEA_20261006_140000', video=True)

        def unreadable(rundir):
            raise OSError("data.csv is locked")
        eg.se.load_run = unreadable
        eg.messagebox = _Boxes()
        app = eg.EdgeReviewApp(root, path=run)
        assert app.run is None, "the fixture loaded after all"
        assert eg.messagebox.errors, "the failed load said nothing"
        assert app.run_box.get().split('  ')[0] == 'SLDEA_20261006_140000'
        assert str(app.video_btn.cget('state')) == 'normal'
        assert app._tips['video_btn'].text == eg.TIPS['video_btn']
        vr.VideoReviewWindow = _Win
        app._open_video_review()
        assert len(opened) == 1 and _same(opened[0].rundir, run)
    finally:
        eg.se.load_run = real_load
        eg.messagebox = real_mb
        vr.VideoReviewWindow = real_win
        _destroy(root)
        shutil.rmtree(p, ignore_errors=True)


def test_edge_review_leaves_no_window_when_the_review_cannot_read_the_run():
    """The real review window, on a run whose data.csv neither Edge Review
    nor the review can read. The review made its window before reading the
    run, so every press of the button left one more empty "Video review"
    window on screen, outside the one-at-a-time rule (#395 review). Now
    each press says why in a box and leaves no window behind."""
    import sldea_edge_gui as eg
    tk = _tk()
    root = _tk_root()
    p = _tmp()
    real_load, real_mb = eg.se.load_run, eg.messagebox

    def unreadable(rundir):
        raise OSError("data.csv is locked")

    def reviews():
        return [w.title() for w in root.winfo_children()
                if isinstance(w, tk.Toplevel)
                and w.title().startswith('Video review')]
    try:
        run = _run(p, 'SLDEA_20261006_143000', video=True)
        eg.se.load_run = unreadable
        eg.messagebox = _Boxes()
        app = eg.EdgeReviewApp(root, path=run)
        assert app.run is None, "the fixture loaded after all"
        assert str(app.video_btn.cget('state')) == 'normal'
        before = len(eg.messagebox.errors)
        for _ in range(2):
            app._open_video_review()
            root.update()
        assert reviews() == [], f"windows left behind: {reviews()}"
        said = eg.messagebox.errors[before:]
        assert len(said) == 2, said
        assert all('data.csv is locked' in text for _t, text, _p in said), \
            said
        assert app._video_win is None
    finally:
        eg.se.load_run = real_load
        eg.messagebox = real_mb
        _destroy(root)
        shutil.rmtree(p, ignore_errors=True)


def test_edge_review_looks_at_the_folder_again_when_the_pointer_arrives():
    """The SLDEA tab's auto-open picks a run the moment it ends, and its
    recording reaches the folder a while later. The button used to stay
    grey until the run was picked again, which throws its review pass
    away. Now the pointer coming onto the button looks again, and the
    loaded run is left as it was."""
    import sldea_edge_gui as eg
    root = _tk_root()
    p = _tmp()
    real_mb = eg.messagebox
    try:
        eg.messagebox = _Boxes()
        run = _run(p, 'SLDEA_20261006_150000')
        app = eg.EdgeReviewApp(root, path=run)
        loaded = app.run
        assert loaded is not None, "the fixture did not load"
        root.deiconify()
        _pump(root, 0.2)
        assert str(app.video_btn.cget('state')) == 'disabled'
        _add_video(run)
        assert str(app.video_btn.cget('state')) == 'disabled', \
            "something looked before the pointer arrived"
        # processed before event_generate returns: no -when given
        app.video_btn.event_generate('<Enter>', x=2, y=2)
        assert str(app.video_btn.cget('state')) == 'normal'
        assert app._tips['video_btn'].text == eg.TIPS['video_btn']
        assert app.run is loaded, "the run was loaded again"
    finally:
        eg.messagebox = real_mb
        _destroy(root)
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
