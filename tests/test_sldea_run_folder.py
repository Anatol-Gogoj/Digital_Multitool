#!/usr/bin/env python3
"""The SLDEA run folder (`#402`): the line under Run name that says where a
run will write, and Run's refusal of a folder that already holds a run.

A run name used before made the worker write over that run: it makes the
folder with exist_ok=True and opens setup.txt and data.csv with mode 'w'.
What is pinned here:

* sldea_profile.run_folder is the one join of Output dir and Run name, the
  worker's old expression to the byte, and the REAL worker makes its
  folder through it, so the line cannot show one folder while the run
  writes another.
* Run refuses a folder that holds a run, and a name that cannot be a
  folder name, right after the start gate: before any question, before
  the video and camera pre-flights and before anything drives the HV,
  with nothing started and the earlier run's files untouched. It reads
  the boxes once, there, and the worker gets exactly those values.
* The line follows the boxes, warns in words and in Tol's muted wine, and
  checks the folder on a thread, one check at a time, so a share that
  hangs never freezes the window. A finished run turns it to a warning.

The run-start cases drive the real sldea_run on test_sldea_interlock's
stub app, whose messagebox stand-in fails on any question it was not told
to expect. The line's cases build the real app and skip with no display.

Run: .venv/bin/python tests/test_sldea_run_folder.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import contextlib  # noqa: E402
import datetime  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import gui  # noqa: E402
import sldea_profile as sprof  # noqa: E402
import test_sldea_interlock as T  # noqa: E402

REFUSED = 'SLDEA run folder'
WINE = '#882255'
EARLIER = 'an earlier run\n'
LINE_THREAD = 'sldea-run-folder-line'


class _Skip(Exception):
    pass


class _Box:
    """A box the test can retype mid-run (the interlock stub's are fixed)."""

    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def _app(tmp, name='RUN', dry=True, real_worker=False):
    """The interlock suite's stub app, aimed at `tmp` with run name `name`."""
    app = T._App(tmp, dry=dry, sgch=1, real_worker=real_worker)
    app.sldea_outdir, app.sldea_runname = _Box(tmp), _Box(name)
    return app


def _a_run_in(folder):
    """What an earlier run left: its folder with a setup.txt in it."""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'setup.txt'), 'w') as f:
        f.write(EARLIER)


def _setup_of(folder):
    with open(os.path.join(folder, 'setup.txt')) as f:
        return f.read()


def _not_started(app):
    """Nothing the run does happened: no claim, no worker, no camera
    pre-flight, no start flag, the run.log buffer disarmed, and not one
    write to the signal generator."""
    assert not app._sldea_running
    assert getattr(app, '_sldea_live_ch', None) is None
    assert not getattr(app, '_sldea_starting', False)
    assert not app.worker_done.is_set()
    assert app._sldea_prelog is None
    assert 'preflight' not in app.events, app.events
    assert app.sg.writes == [], app.sg.writes


@contextlib.contextmanager
def _hanging_share():
    """sldea_profile.holds_run blocks until the yielded event is set, as a
    stat on a share that has gone away does."""
    gate = threading.Event()
    real = sprof.holds_run

    def hang(folder):
        gate.wait(30)
        return []
    sprof.holds_run = hang
    try:
        yield gate
    finally:
        gate.set()
        sprof.holds_run = real


# --------------------------------------------------------------------------
# sldea_profile: the folder, the check, the refusal, the line
# --------------------------------------------------------------------------

def test_run_folder_is_the_workers_old_join_to_the_byte():
    started = datetime.datetime(2026, 10, 7, 23, 1, 2)
    for outdir in ('/mnt/shareDrive/robot_incubator/SLDEA_data', 'C:/data',
                   'C:\\data\\', 'relative', ''):
        for name in ('RUN', 'P3_6_2.5mL_20260729', ''):
            old = os.path.join(
                outdir, name or sprof.SldeaProfile.run_dirname(started))
            assert sprof.run_folder(outdir, name, started) == old, (outdir,
                                                                    name)
    assert sprof.run_folder('/x', '') == os.path.join(
        '/x', sprof.AUTO_RUN_DIRNAME)


def test_holds_run_names_the_run_files_it_finds():
    with tempfile.TemporaryDirectory() as tmp:
        run = os.path.join(tmp, 'RUN')
        assert sprof.holds_run(run) == []                 # no folder
        os.mkdir(run)
        assert sprof.holds_run(run) == []                 # empty: no run
        open(os.path.join(run, 'data.csv'), 'w').close()
        assert sprof.holds_run(run) == ['data.csv']
        open(os.path.join(run, 'setup.txt'), 'w').close()
        assert sprof.holds_run(run) == ['setup.txt', 'data.csv']
        assert sprof.holds_run_within(run, 5.0) == ['setup.txt', 'data.csv']


def test_a_share_that_hangs_is_given_up_on_within_the_bound():
    with _hanging_share():
        t0 = time.monotonic()
        assert sprof.holds_run_within('/nowhere/RUN', 0.3) is None
        took = time.monotonic() - t0
        assert 0.25 <= took < 1.5, took
        why = sprof.run_folder_refusal('/nowhere', 'RUN', timeout_s=0.3)
        assert 'did not answer within 0.3 s' in why, why
        assert 'mounted' in why, why


def test_the_refusal_names_the_folder_and_spares_new_and_blank_names():
    with tempfile.TemporaryDirectory() as tmp:
        assert sprof.run_folder_refusal(tmp, '') is None
        assert sprof.run_folder_refusal(tmp, '   ') is None
        assert sprof.run_folder_refusal(tmp, 'NEW') is None
        # a folder made with New folder... holds no run: not refused
        os.mkdir(os.path.join(tmp, 'EMPTY'))
        assert sprof.run_folder_refusal(tmp, 'EMPTY') is None
        run = os.path.join(tmp, 'RUN')
        _a_run_in(run)
        why = sprof.run_folder_refusal(tmp, 'RUN')
        assert run in why and 'setup.txt' in why, why
        assert 'write over' in why and 'start anyway' not in why, why
        assert sprof.run_folder_refusal(tmp, ' RUN ') == why
        for bad, word in (('P3/x', '/'), ('a\\b', '\\'), ('a:b', ':'),
                          ('..', '..'), ('CON', 'device'),
                          ('end.', 'dot'), ('2.5\u00b5L', 'ASCII')):
            why = sprof.run_folder_refusal(tmp, bad)
            assert why and 'cannot name the run' in why, (bad, why)
            assert word in why, (bad, why)


def test_the_line_says_where_and_warns_in_words():
    with tempfile.TemporaryDirectory() as tmp:
        text, warn, full = sprof.run_folder_line(tmp, '')
        assert text.startswith('Saves to: ') and not warn, text
        assert sprof.AUTO_RUN_DIRNAME in text, text
        assert 'stamped at start' in text, text
        text, warn, full = sprof.run_folder_line(tmp, 'NEW', found=[])
        assert full == os.path.abspath(os.path.join(tmp, 'NEW')), full
        assert text == 'Saves to: ' + sprof._short_path(full), text
        assert not warn
        text, warn, _full = sprof.run_folder_line(tmp, 'RUN',
                                                  found=['setup.txt'])
        assert warn and text.startswith('\u26a0'), text
        assert 'already holds a run (setup.txt)' in text, text
        assert 'refuse' in text, text
        text, warn, full = sprof.run_folder_line(tmp, 'a:b')
        assert warn and 'Run name' in text and 'refuse' in text, text
        assert 'Windows' in full, full          # the whole reason, hovered
        text, warn, _full = sprof.run_folder_line(tmp, 'NEW', None, slow=True)
        assert warn and 'not answering' in text, text
    deep = ('/mnt/shareDrive/robot_incubator/SLDEA_data/Upload 20260804/'
            + 'deeper/' * 8)
    text, _warn, _full = sprof.run_folder_line(deep, 'P3_6_2.5mL_20260729',
                                               found=[])
    assert text.endswith('P3_6_2.5mL_20260729'), text      # the name, whole
    assert '\u2026' in text, text                          # the head, cut
    assert len(text) <= len('Saves to: ') + sprof.RUN_FOLDER_LINE_CHARS + 1


# --------------------------------------------------------------------------
# sldea_run: the refusal, on the interlock suite's stub app
# --------------------------------------------------------------------------

def test_a_folder_holding_a_run_is_refused_before_any_question():
    """LIVE asks two HV questions and DRY none: the refusal comes before
    either, before the video pre-flight and before the camera pre-flight,
    and the earlier run's setup.txt is untouched."""
    for dry in (True, False):
        mb = T._MB(T.LIVE_OK)
        with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
            run = os.path.join(tmp, 'RUN')
            _a_run_in(run)
            app = _app(tmp, 'RUN', dry=dry)
            video = []
            app._sldea_video_preflight = (
                lambda p: (video.append(p), (False, None))[1])
            app.sldea_run()
            assert mb.titles() == [REFUSED], (dry, mb.calls)
            assert mb.calls[0][0] == 'showerror', mb.calls
            msg = mb.message(REFUSED)
            assert run in msg and 'setup.txt' in msg, msg
            assert video == [], 'the video pre-flight ran first'
            _not_started(app)
            assert _setup_of(run) == EARLIER
            assert any(l.startswith('run refused:') for l in app.lines), \
                app.lines


def test_a_name_that_cannot_be_a_folder_is_refused_the_same_way():
    mb = T._MB(T.LIVE_OK)
    with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
        app = _app(tmp, 'P3/x', dry=False)
        app.sldea_run()
        assert mb.titles() == [REFUSED], mb.calls
        assert 'cannot name the run' in mb.message(REFUSED)
        _not_started(app)
        assert os.listdir(tmp) == [], os.listdir(tmp)


def test_a_new_name_runs_and_the_same_name_is_then_refused():
    """End to end through the REAL worker: a fresh name runs as before, and
    pressing Run again with that name is refused with the first run's
    data.csv as it was."""
    mb = T._MB({})
    with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
        app = _app(tmp, 'RUN', real_worker=True)
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        T._assert_clean_run(app)
        app.root.run_pending()
        assert mb.calls == [], mb.calls
        assert app.worker_args[1:3] == (tmp, 'RUN'), app.worker_args[1:3]
        run = os.path.join(tmp, 'RUN')
        assert sprof.holds_run(run) == ['setup.txt', 'data.csv']
        with open(os.path.join(run, 'data.csv'), 'rb') as f:
            data = f.read()
        setup = _setup_of(run)
        again = _app(tmp, 'RUN', real_worker=True)
        again.sldea_run()
        assert mb.titles() == [REFUSED], mb.calls
        _not_started(again)
        with open(os.path.join(run, 'data.csv'), 'rb') as f:
            assert f.read() == data
        assert _setup_of(run) == setup


def test_the_worker_writes_where_run_folder_says():
    """The worker's folder comes from sldea_profile.run_folder, named or
    blank, so the line and the run cannot drift."""
    calls = []
    real = sprof.run_folder

    def spy(outdir, run_name, started=None):
        out = real(outdir, run_name, started)
        calls.append((outdir, run_name, started, out))
        return out
    mb = T._MB({})
    with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
        sprof.run_folder = spy
        try:
            for name in ('RUN', ''):
                del calls[:]
                app = _app(tmp, name, real_worker=True)
                app.sldea_run()
                assert app.worker_done.wait(30), app.lines
                T._assert_clean_run(app)
                app.root.run_pending()
                worker = [c for c in calls
                          if isinstance(c[2], datetime.datetime)]
                assert len(worker) == 1, calls
                [(outdir, run_name, started, folder)] = worker
                assert (outdir, run_name) == (tmp, name)
                assert os.path.isfile(os.path.join(folder, 'setup.txt'))
                if not name:
                    assert os.path.basename(folder) == \
                        sprof.SldeaProfile.run_dirname(started)
        finally:
            sprof.run_folder = real


def test_the_boxes_are_read_once_at_the_check():
    """Retyping the boxes while the pre-flight is up cannot slip a checked
    folder past the check: the worker gets what was checked."""
    mb = T._MB({})
    with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
        taken = os.path.join(tmp, 'TAKEN')
        _a_run_in(taken)
        app = _app(tmp, 'RUN', real_worker=True)

        def retype():
            app.sldea_runname.set('TAKEN')
            app.sldea_outdir.set(os.path.join(tmp, 'elsewhere'))
        app.on_preflight = retype
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        T._assert_clean_run(app)
        app.root.run_pending()
        assert app.worker_args[1:3] == (tmp, 'RUN'), app.worker_args[1:3]
        assert _setup_of(taken) == EARLIER
        assert not os.path.exists(os.path.join(tmp, 'elsewhere'))


# --------------------------------------------------------------------------
# The line on the real SLDEA tab
# --------------------------------------------------------------------------

@contextlib.contextmanager
def _real_app():
    """(root, app) with every tab built, no instrument hunt and no camera,
    or _Skip. Restores what it patched and destroys the root."""
    try:
        import tkinter as tk
    except ImportError as e:
        raise _Skip(f"no tkinter: {e}")
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    real_connect = gui.InstrumentControlGUI.auto_connect
    real_autostart = gui.CAM_AUTOSTART_ON_TAB
    gui.InstrumentControlGUI.auto_connect = lambda self: None
    gui.CAM_AUTOSTART_ON_TAB = False
    try:
        app = gui.InstrumentControlGUI(root)
        root.update_idletasks()
        yield root, app
    finally:
        gui.InstrumentControlGUI.auto_connect = real_connect
        gui.CAM_AUTOSTART_ON_TAB = real_autostart
        root.destroy()


def _settle(root, pred, timeout=3.0):
    """Pump Tk until `pred()` holds; the result of the last look."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if pred():
            return True
        time.sleep(0.01)
    root.update()
    return pred()


def _saves_to(folder):
    return 'Saves to: ' + sprof._short_path(os.path.abspath(folder))


def test_the_line_sits_under_run_name_follows_the_boxes_and_warns():
    with tempfile.TemporaryDirectory() as tmp, _real_app() as (root, app):
        line = app.sldea_folder_line
        info, name_info = line.grid_info(), app.sldea_runname.grid_info()
        assert int(info['row']) == int(name_info['row']) + 1, (info,
                                                               name_info)
        assert int(info['column']) == int(name_info['column'])
        app.sldea_outdir.set(tmp)
        root.update()
        assert sprof.AUTO_RUN_DIRNAME in line.cget('text'), line.cget('text')
        # typed key by key into the real box: the line follows each key
        app.sldea_runname.delete(0, 'end')
        for i, ch in enumerate('NEW'):
            app.sldea_runname.insert('end', ch)
            root.update()
            typed = 'NEW'[:i + 1]
            assert line.cget('text').endswith(typed), line.cget('text')
        assert _settle(root, lambda: line.cget('text') ==
                       _saves_to(os.path.join(tmp, 'NEW'))), line.cget('text')
        assert line.cget('fg') == app.SLDEA_FOLDER_COLORS['ok']
        assert app._sldea_folder_tip.text == os.path.abspath(
            os.path.join(tmp, 'NEW'))
        # Where the boxes beside the line sit, in every state below: its
        # text changes at every keystroke and must never move them.
        beside = (app.sldea_vars['vch'], app.sldea_browse_btn)
        spots = set()

        def note():
            root.update_idletasks()
            spots.add(tuple(w.winfo_x() for w in beside))
        note()
        # a folder that holds a run: warned once its check is back
        _a_run_in(os.path.join(tmp, 'RUN'))
        app.sldea_runname_var.set('RUN')
        assert _settle(root, lambda: 'already holds a run' in
                       line.cget('text')), line.cget('text')
        assert line.cget('text').startswith('\u26a0')
        assert line.cget('fg') == WINE
        note()
        # a name that cannot be a folder name: warned at once
        app.sldea_runname_var.set('a:b')
        root.update()
        assert 'Run name' in line.cget('text'), line.cget('text')
        assert line.cget('fg') == WINE
        note()
        app.sldea_runname_var.set('')
        root.update()
        note()
        assert len(spots) == 1, spots
        # Browse and New folder... set the Output dir box: followed too
        other = os.path.join(tmp, 'other')
        os.mkdir(other)
        app.sldea_runname_var.set('RUN')
        app.sldea_outdir.set(other)
        assert _settle(root, lambda: line.cget('text') ==
                       _saves_to(os.path.join(other, 'RUN'))), \
            line.cget('text')
        assert line.cget('fg') == app.SLDEA_FOLDER_COLORS['ok']


def test_a_share_that_hangs_never_freezes_the_window():
    """Every keystroke redraws at once while the check hangs; the line
    says the Output dir is not answering; only one check is ever out; the
    answer shows once it comes."""
    with tempfile.TemporaryDirectory() as tmp, _real_app() as (root, app), \
            _hanging_share() as gate:
        line = app.sldea_folder_line
        app.SLDEA_FOLDER_SLOW_S = 0.3
        app.sldea_outdir.set(tmp)
        worst = 0.0
        for name in ('A', 'AB', 'ABC', 'ABCD', 'ABCDE'):
            # The trace runs the redraw inside set(): a stat made there
            # would hold it for the share's 30 s. Painting is timed apart.
            t0 = time.monotonic()
            app.sldea_runname_var.set(name)
            worst = max(worst, time.monotonic() - t0)
            root.update()
            # the path for THIS keystroke, with or without the slow note
            want = sprof._short_path(os.path.abspath(os.path.join(tmp, name)))
            text = line.cget('text')
            assert text.endswith(want) or want + '  (' in text, text
            _settle(root, lambda: False, timeout=0.4)
        assert worst < 0.5, worst
        assert _settle(root, lambda: 'not answering' in line.cget('text')), \
            line.cget('text')
        assert line.cget('fg') == WINE
        out = [t for t in threading.enumerate() if t.name == LINE_THREAD]
        assert len(out) == 1, out
        gate.set()
        assert _settle(root, lambda: line.cget('text') ==
                       _saves_to(os.path.join(tmp, 'ABCDE'))), \
            line.cget('text')


def test_a_finished_run_turns_the_line_to_a_warning():
    """_sldea_finished asks the line to look again, so it warns about the
    folder the run just made before the next Run is refused for it."""
    with tempfile.TemporaryDirectory() as tmp, _real_app() as (root, app):
        line = app.sldea_folder_line
        app.sldea_outdir.set(tmp)
        app.sldea_runname_var.set('RUN')
        assert _settle(root, lambda: line.cget('text') ==
                       _saves_to(os.path.join(tmp, 'RUN'))), line.cget('text')
        _a_run_in(os.path.join(tmp, 'RUN'))      # what the worker wrote
        app._sldea_finished()
        assert _settle(root, lambda: 'already holds a run' in
                       line.cget('text')), line.cget('text')


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    try:
        _sys.stdout.reconfigure(errors='backslashreplace')
    except AttributeError:          # not a TextIOWrapper: leave it be
        pass
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    ran = skipped = 0
    failed = []
    for fn in fns:
        try:
            fn()
        except _Skip as why:
            skipped += 1
            print(f"skip {fn.__name__} ({why})")
            continue
        except Exception:
            ran += 1
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
        ran += 1
        print(f"ok  {fn.__name__}")
    tail = f"{ran} of {len(fns)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped, see above)"
    if not failed:
        print(f"\n{tail}")
        return 0
    head = f"{len(failed)} of {len(fns)} tests failed"
    print(f"\n{head}")
    for name, tb in failed:
        print(f"===== FAIL {name} =====")
        print(tb.rstrip('\n'))
    print(f"===== end {head} =====")
    return 1


if __name__ == '__main__':
    raise SystemExit(_run())
