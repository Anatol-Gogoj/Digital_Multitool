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
* Run refuses a folder that holds a run, a name that cannot be a folder
  name, a folder whose check failed or did not answer, and a folder on
  the share while the share is not mounted, right after the start gate:
  before any HV question, before the video and camera pre-flights and
  before anything drives the HV, with nothing started and the earlier
  run's files untouched. It reads the boxes once, there, and the worker
  gets exactly those values.
* A run that appears in the folder after the check makes the worker fail
  at its first write, before the camera and the SG (mode 'x').
* The line follows the boxes, warns in words and in Tol's muted wine, and
  checks the folder on a thread, so a share that hangs never freezes the
  window. It is two lines high whatever it says, so nothing below it
  moves; it describes the folder the boxes name now, or, during a run,
  the run's own. A finished run turns it to a warning.

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
import errno  # noqa: E402
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
        assert sprof.run_folder_look_within(tmp, 'RUN', None, 5.0) == \
            ['setup.txt', 'data.csv']
        # a file where a folder of the path should be is "absent" too
        assert sprof.holds_run(os.path.join(run, 'setup.txt', 'x')) == []


@contextlib.contextmanager
def _stat_fails(under, err=errno.EIO):
    """os.stat raises OSError(`err`) for any path under `under`, as on a
    share that dropped mid-session (EIO, ESTALE) or a folder this user
    may not read (EACCES)."""
    real = os.stat
    top = os.path.normcase(os.path.abspath(under))

    def stat(path, *a, **k):
        if os.path.normcase(os.path.abspath(path)).startswith(top):
            raise OSError(err, os.strerror(err), path)
        return real(path, *a, **k)
    os.stat = stat
    try:
        yield
    finally:
        os.stat = real


def test_a_stat_that_fails_is_not_read_as_no_run():
    """#402 review, finding 2: os.path.exists read EIO, ESTALE or EACCES as
    "absent", so a folder on a share that had just dropped passed the
    check. Only FileNotFoundError and NotADirectoryError mean absent; any
    other failure means a run there cannot be ruled out, and Run refuses,
    saying the folder could not be checked."""
    for err in (errno.EIO, errno.EACCES, getattr(errno, 'ESTALE', 116)):
        with tempfile.TemporaryDirectory() as tmp, \
                _stat_fails(os.path.join(tmp, 'RUN'), err):
            assert sprof.holds_run(os.path.join(tmp, 'RUN')) is None, err
            assert sprof.run_folder_look(tmp, 'RUN') == \
                sprof.FOLDER_NOT_CHECKED
            why = sprof.run_folder_refusal(tmp, 'RUN')
            assert why and 'Could not check the run folder' in why, why
            assert 'cannot be ruled out' in why, why
            assert sprof.run_folder_refusal(tmp, 'OTHER') is None
            text, warn, full = sprof.run_folder_line(
                tmp, 'RUN', sprof.FOLDER_NOT_CHECKED)
            second = _lines(text)[1]
            assert warn and 'Could not check' in second, text
            assert 'refuse' in second, text
            assert 'cannot be ruled out' in full, full


def test_a_stat_that_fails_refuses_the_run_before_any_question():
    mb = T._MB(T.LIVE_OK)
    with tempfile.TemporaryDirectory() as tmp, T._patched(mb), \
            _stat_fails(os.path.join(tmp, 'RUN')):
        app = _app(tmp, 'RUN', dry=False)
        app.sldea_run()
        assert mb.titles() == [REFUSED], mb.calls
        assert 'Could not check' in mb.message(REFUSED), mb.calls
        _not_started(app)


@contextlib.contextmanager
def _share_at(mount):
    """Aim the app's share mount point at `mount`, a plain folder: a share
    that is not mounted."""
    real = gui.sldea_share_mount
    gui.sldea_share_mount = lambda: mount
    try:
        yield mount
    finally:
        gui.sldea_share_mount = real


def test_an_unmounted_share_is_refused_and_a_folder_elsewhere_is_not():
    """#402 review, finding 1: unmounted, a stat under the mount point
    finds nothing at once, so the line said a plain "Saves to:" and Run
    went on, to fail at makedirs after "Energize HV?" or to write to this
    PC's own disk. New folder's check (#394) now refuses it, named or
    blank. An Output dir off the share is not touched by it: not one
    os.path.ismount call."""
    with tempfile.TemporaryDirectory() as tmp:
        mnt = os.path.join(tmp, 'mnt')          # a plain folder: unmounted
        share = os.path.join(mnt, 'robot_incubator', 'SLDEA_data')
        os.makedirs(share)
        for name in ('RUN', ''):
            assert sprof.run_folder_look(share, name, mnt) == \
                sprof.FOLDER_NOT_MOUNTED, name
            why = sprof.run_folder_refusal(share, name, mount=mnt)
            assert why and f'not mounted at {mnt}' in why, (name, why)
            assert "this PC's own disk" in why, why
            text, warn, full = sprof.run_folder_line(
                share, name, sprof.FOLDER_NOT_MOUNTED, mount=mnt)
            second = _lines(text)[1]
            assert warn and 'not mounted' in second, text
            assert 'refuse' in second and mnt in full, (text, full)
        # off the share: nothing refused, and the mount never looked at
        local = os.path.join(tmp, 'local')
        os.mkdir(local)
        calls = []
        real = os.path.ismount
        os.path.ismount = lambda p: calls.append(p) or real(p)
        try:
            for name in ('RUN', ''):
                assert sprof.run_folder_look(local, name, mnt) == [], name
                assert sprof.run_folder_refusal(local, name,
                                                mount=mnt) is None
        finally:
            os.path.ismount = real
        assert calls == [], calls
        # a share that IS mounted (the root of this disk is a mount point)
        root = os.path.abspath(os.sep)
        assert os.path.ismount(root)
        for name in ('RUN', ''):
            assert sprof.run_folder_refusal(share, name, mount=root) is None


def test_an_unmounted_share_refuses_the_run_before_any_question():
    """DRY and LIVE, named and blank: the refusal is the only dialog,
    nothing starts, and nothing is written under the bare mount point."""
    for dry in (True, False):
        for name in ('RUN', ''):
            mb = T._MB(T.LIVE_OK)
            with tempfile.TemporaryDirectory() as tmp, T._patched(mb), \
                    _share_at(os.path.join(tmp, 'mnt')) as mnt:
                share = os.path.join(mnt, 'SLDEA_data')
                os.makedirs(share)
                app = _app(share, name, dry=dry)
                app.sldea_run()
                assert mb.titles() == [REFUSED], (dry, name, mb.calls)
                assert 'not mounted' in mb.message(REFUSED), mb.calls
                _not_started(app)
                assert os.listdir(share) == [], os.listdir(share)


def test_a_share_that_hangs_is_given_up_on_within_the_bound():
    with _hanging_share():
        t0 = time.monotonic()
        assert sprof.run_folder_look_within('/nowhere', 'RUN', None,
                                            0.3) is None
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


def _lines(text):
    """The line's text as its lines: at most two, folder then warning."""
    lines = text.split('\n')
    assert 1 <= len(lines) <= 2, text
    return lines


def test_the_line_says_where_and_warns_in_words():
    """Line 1 says where, line 2 warns in words or is absent; the tooltip
    has the whole path and below it the whole reason."""
    with tempfile.TemporaryDirectory() as tmp:
        text, warn, full = sprof.run_folder_line(tmp, '')
        [first] = _lines(text)
        assert first.startswith('Saves to: ') and not warn, text
        assert sprof.AUTO_RUN_DIRNAME in first, text
        assert first.endswith('  (stamped at start)'), text
        text, warn, full = sprof.run_folder_line(tmp, 'NEW', found=[])
        assert full == os.path.abspath(os.path.join(tmp, 'NEW')), full
        assert text == sprof.fit_path('Saves to: ', full), text
        assert not warn
        text, warn, full = sprof.run_folder_line(tmp, 'RUN',
                                                 found=['setup.txt'])
        first, second = _lines(text)
        assert first == sprof.fit_path(
            'Saves to: ', os.path.abspath(os.path.join(tmp, 'RUN'))), text
        assert warn and second.startswith('\u26a0'), text
        assert 'already holds a run' in second.lower(), text
        assert 'refuse' in second, text
        assert 'setup.txt' in full and 'write over' in full, full
        text, warn, full = sprof.run_folder_line(tmp, 'a:b')
        _first, second = _lines(text)
        assert warn and 'cannot contain :' in second, text
        assert 'refuse' in second, text
        assert 'Windows' in full, full          # the whole reason, hovered
        # not plain ASCII: the line also says New folder's way round it,
        # in its words, before Run is pressed (owner decision 2026-10-08)
        import output_folder
        text, warn, full = sprof.run_folder_line(tmp, 'P3_7_2.5\u00b5L')
        _first, second = _lines(text)
        assert warn and 'Plain ASCII' in second, text
        assert 'u for \u00b5, as in 2.5uL' in second, text
        assert 'refuse' in second, text
        assert output_folder.ASCII_HINT in full, full
        text, _warn, _full = sprof.run_folder_line(tmp, 'a:b')
        assert 'u for' not in text, text
        text, warn, _full = sprof.run_folder_line(tmp, 'NEW', None, slow=True)
        assert warn and 'not answering' in _lines(text)[1], text
        # a reason too long for the line gives way to a short one; the
        # tooltip keeps the whole reason
        text, warn, full = sprof.run_folder_line(tmp, 'CON')
        _first, second = _lines(text)
        assert second == ('\u26a0 Not a folder name: \u25b6 Run will refuse '
                          'it.'), text
        assert 'device name' in full, full
    deep = ('/mnt/shareDrive/robot_incubator/SLDEA_data/Upload 20260804/'
            + 'deeper/' * 8)
    text, _warn, _full = sprof.run_folder_line(deep, 'P3_6_2.5mL_20260729',
                                               found=[])
    assert text.endswith('P3_6_2.5mL_20260729'), text      # the name, whole
    assert '\u2026' in text, text                          # the head, cut
    assert len(text) <= sprof.RUN_FOLDER_LINE_CHARS, text


def test_each_line_is_fitted_to_the_width_from_the_left():
    """With a measured width (here: characters), line 1 keeps the run
    folder's name and cuts the path's head, character by character once
    the name alone is too long; line 2 is cut at its end only as a safety
    net. Neither ever passes the width."""
    for room in (20, 30, 45, 80):
        def fits(text, room=room):
            return len(text) <= room
        for outdir, name in (('/mnt/shareDrive/a/b/c/d/e', 'P3_6_2.5mL'),
                             ('C:\\data\\x\\y', 'A_VERY_LONG_RUN_NAME_x'),
                             ('/x', 'RUN'), ('/x', '')):
            for found, slow in (([], False), (['setup.txt'], False),
                                (None, True)):
                text, _warn, _full = sprof.run_folder_line(
                    outdir, name, found, slow, fits=fits)
                for line in _lines(text):
                    assert fits(line), (room, line)
                first = _lines(text)[0]
                path = os.path.abspath(sprof.run_folder(outdir, name))
                tail = path[-3:] + ('' if name else '  (stamped at start)')
                if fits('Saves to: \u2026' + tail):
                    assert first.endswith(tail), (room, first)
    assert sprof.fit_end('abcdef', lambda t: len(t) <= 4) == 'abc\u2026'
    assert sprof.fit_path('S: ', '/a/b/NAME', '',
                          lambda t: len(t) <= 9) == 'S: \u2026/NAME'
    assert sprof.fit_path('S: ', '/a/b/NAME', '',
                          lambda t: len(t) <= 7) == 'S: \u2026AME'


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


def test_a_name_that_is_not_plain_ascii_is_refused_with_the_u_hint():
    """Owner decision 2026-10-08: a µ in the run name is refused like any
    name that cannot be a folder name, and the box carries New folder's
    own way round it (output_folder.ASCII_HINT), not a second wording."""
    import output_folder
    mb = T._MB(T.LIVE_OK)
    with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
        app = _app(tmp, 'P3_7_2.5µL', dry=False)
        app.sldea_run()
        assert mb.titles() == [REFUSED], mb.calls
        msg = mb.message(REFUSED)
        assert 'plain ASCII' in msg and output_folder.ASCII_HINT in msg, msg
        assert 'u for µ, as in 2.5uL' in msg, msg
        _not_started(app)
        assert os.listdir(tmp) == [], os.listdir(tmp)


def test_a_share_that_does_not_answer_refuses_the_run():
    """Owner decision 2026-10-08: no answer from the Output dir within the
    bound refuses the run, before any question, with nothing started. The
    bound is read at the call, so this test shortens it."""
    mb = T._MB(T.LIVE_OK)
    real_bound = sprof.RUN_FOLDER_CHECK_S
    with tempfile.TemporaryDirectory() as tmp, T._patched(mb), \
            _hanging_share():
        sprof.RUN_FOLDER_CHECK_S = 0.3
        try:
            app = _app(tmp, 'RUN', dry=False)
            t0 = time.monotonic()
            app.sldea_run()
            took = time.monotonic() - t0
        finally:
            sprof.RUN_FOLDER_CHECK_S = real_bound
        assert mb.titles() == [REFUSED], mb.calls
        msg = mb.message(REFUSED)
        assert 'did not answer within 0.3 s' in msg, msg
        assert 'mounted' in msg, msg
        assert took < 3.0, took
        _not_started(app)


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


def _bytes_of(path):
    with open(path, 'rb') as f:
        return f.read()


def test_a_run_that_appears_after_the_check_makes_this_run_fail():
    """#402 review, finding 3: Run checks the folder, then every dialog
    takes as long as the operator does, and another run (another PC on the
    share) can start there meanwhile. The worker opens setup.txt with mode
    'x' for a typed name, so this run fails at that first write, before
    the camera and the SG, and the earlier run's setup.txt stays as it
    was. LIVE, through the REAL worker: the SG gets nothing but the
    finally's zeroing, 0 V and output off."""
    mb = T._MB(T.LIVE_OK)
    with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
        run = os.path.join(tmp, 'RUN')
        before = {}

        def meanwhile():                 # after the check, before the worker
            _a_run_in(run)
            before['setup'] = _bytes_of(os.path.join(run, 'setup.txt'))
        app = _app(tmp, 'RUN', dry=False, real_worker=True)
        app.on_preflight = meanwhile
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        app.root.run_pending()
        assert mb.titles() == list(T.LIVE_OK), mb.calls   # the check passed
        assert 'setup' in before, 'the pre-flight never ran'
        errors = [l for l in app.lines if l.startswith('ERROR')]
        assert len(errors) == 1, app.lines
        assert 'setup.txt appeared in the run folder' in errors[0], errors
        assert 'before any HV' in errors[0], errors
        assert not any(l.startswith('run complete') for l in app.lines)
        assert _bytes_of(os.path.join(run, 'setup.txt')) == before['setup']
        assert sorted(os.listdir(run)) == ['frames', 'setup.txt'], \
            os.listdir(run)
        writes = [w[1:] for w in app.sg.writes]
        assert writes == [('set_offset', 1, (0.0,)),
                          ('set_output', 1, (False,))], writes
        assert not app._sldea_running


def test_a_data_csv_that_appears_after_the_check_is_not_overwritten():
    """The same for a folder that got only a data.csv meanwhile: data.csv
    is opened with mode 'x' too, still before the camera and the SG, so it
    stays as it was and the SG is only zeroed."""
    mb = T._MB(T.LIVE_OK)
    with tempfile.TemporaryDirectory() as tmp, T._patched(mb):
        run = os.path.join(tmp, 'RUN')
        data = os.path.join(run, 'data.csv')
        before = {}

        def meanwhile():
            os.makedirs(run)
            with open(data, 'w', newline='') as f:
                f.write('frame,kv\r\n1,0.5\r\n')
            before['data'] = _bytes_of(data)
        app = _app(tmp, 'RUN', dry=False, real_worker=True)
        app.on_preflight = meanwhile
        app.sldea_run()
        assert app.worker_done.wait(30), app.lines
        app.root.run_pending()
        errors = [l for l in app.lines if l.startswith('ERROR')]
        assert len(errors) == 1, app.lines
        assert 'data.csv appeared in the run folder' in errors[0], errors
        assert _bytes_of(data) == before['data']
        writes = [w[1:] for w in app.sg.writes]
        assert writes == [('set_offset', 1, (0.0,)),
                          ('set_output', 1, (False,))], writes


def test_a_blank_name_keeps_writing_its_files_with_w():
    """A blank name's folder is new by its time stamp: the worker keeps
    mode 'w' for it, and a typed name gets 'x', for both files."""
    import builtins
    with tempfile.TemporaryDirectory() as tmp:
        modes = []
        real = builtins.open
        try:
            sprof.open = lambda path, mode, **kw: (
                modes.append((os.path.basename(path), mode))
                or real(path, mode, **kw))
            for name, folder in (('', 'a'), ('RUN', 'b')):
                os.mkdir(os.path.join(tmp, folder))
                for fn in ('setup.txt', 'data.csv'):
                    sprof.open_run_file(os.path.join(tmp, folder), fn,
                                        name).close()
        finally:
            del sprof.open
        assert modes == [('setup.txt', 'w'), ('data.csv', 'w'),
                         ('setup.txt', 'x'), ('data.csv', 'x')], modes
        try:
            sprof.open_run_file(os.path.join(tmp, 'b'), 'setup.txt', 'RUN')
        except FileExistsError as e:
            assert 'setup.txt appeared in the run folder' in str(e), e
        else:
            raise AssertionError('a second open with a typed name passed')


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


def _saves_to(app, folder):
    """Line 1 for `folder`, fitted to the line's width as the app fits it."""
    return sprof.fit_path('Saves to: ', os.path.abspath(folder), '',
                          app._sldea_folder_fits())


def _holds_run(text):
    return 'already holds a run' in text.lower()


def _select_sldea(root, app):
    """Show the SLDEA tab, so its widgets are laid out for real."""
    nb = app.notebook
    for i in range(nb.index('end')):
        if 'SLDEA' in nb.tab(i, 'text'):
            nb.select(i)
            break
    else:
        raise AssertionError('no SLDEA tab')
    root.update()


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
                       _saves_to(app, os.path.join(tmp, 'NEW'))), \
            line.cget('text')
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
        assert _settle(root, lambda: _holds_run(line.cget('text'))), \
            line.cget('text')
        assert line.cget('text').split('\n')[1].startswith('⚠')
        assert line.cget('fg') == WINE
        note()
        # a name that cannot be a folder name: warned at once
        app.sldea_runname_var.set('a:b')
        root.update()
        assert 'cannot contain :' in line.cget('text'), line.cget('text')
        assert line.cget('fg') == WINE
        note()
        # a µ in the name: warned at once, with New folder's way round it
        app.sldea_runname_var.set('P3_7_2.5µL')
        root.update()
        assert 'u for µ, as in 2.5uL' in line.cget('text'), \
            line.cget('text')
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
                       _saves_to(app, os.path.join(other, 'RUN'))), \
            line.cget('text')
        assert line.cget('fg') == app.SLDEA_FOLDER_COLORS['ok']


def test_the_line_never_moves_the_rows_below_it():
    """#402 review: a warning took the line to two lines and the µ hint to
    three, so every row below it, ▶ Run included, jumped after each typing
    pause. The line is two lines high whatever it says, each line fitted
    to its width: the Run button and the row under the line stay put
    through a blank name, a long name in a long Output dir, a name whose
    folder holds a run, and a µ, and the run folder's name always shows."""
    with tempfile.TemporaryDirectory() as tmp, _real_app() as (root, app):
        _select_sldea(root, app)
        line = app.sldea_folder_line
        below = app.sldea_vars['diam_mm']          # the row under the line
        deep = os.path.join(tmp, *(['a_long_folder_name_for_a_test'] * 6))
        os.makedirs(deep)
        long_name = 'P3_6_2.5mL_Triazole_20261008_and_then_some_more'
        _a_run_in(os.path.join(tmp, 'RUN'))
        spots, texts = {}, {}

        def note(state):
            root.update()
            spots[state] = (app.sldea_run_btn.winfo_rooty()
                            - root.winfo_rooty(), below.winfo_y(),
                            line.winfo_height())
            texts[state] = line.cget('text')
        app.sldea_outdir.set(tmp)
        app.sldea_runname_var.set('')
        _settle(root, lambda: False, timeout=0.5)
        note('blank')
        app.sldea_outdir.set(deep)
        app.sldea_runname_var.set(long_name)
        _settle(root, lambda: False, timeout=0.5)
        note('long')
        app.sldea_outdir.set(tmp)
        app.sldea_runname_var.set('RUN')
        assert _settle(root, lambda: _holds_run(line.cget('text'))), \
            line.cget('text')
        note('used')
        app.sldea_runname_var.set('P3_7_2.5µL')
        root.update()
        note('micro')
        assert len(set(spots.values())) == 1, spots
        fits = app._sldea_folder_fits()
        assert fits is not None, 'the line was never laid out'
        for state, text in texts.items():
            for part in _lines(text):
                assert fits(part), (state, part)
        assert texts['long'].endswith(long_name), texts['long']
        assert texts['long'].startswith('Saves to: …'), texts['long']
        assert len(_lines(texts['used'])) == 2, texts['used']
        assert len(_lines(texts['micro'])) == 2, texts['micro']


def test_the_line_warns_while_the_share_is_not_mounted():
    """#402 review, finding 1, on the real tab: an Output dir under the
    share's mount point while nothing is mounted there gets a warning, for
    a typed name and a blank one; an Output dir off the share gets none."""
    with tempfile.TemporaryDirectory() as tmp, _real_app() as (root, app), \
            _share_at(os.path.join(tmp, 'mnt')) as mnt:
        share = os.path.join(mnt, 'SLDEA_data')
        os.makedirs(share)
        line = app.sldea_folder_line
        app.sldea_outdir.set(share)
        for name in ('RUN', ''):
            app.sldea_runname_var.set(name)
            assert _settle(root, lambda: 'not mounted' in line.cget('text')), \
                (name, line.cget('text'))
            assert line.cget('fg') == WINE
            assert mnt in app._sldea_folder_tip.text
        local = os.path.join(tmp, 'local')
        os.mkdir(local)
        app.sldea_outdir.set(local)
        app.sldea_runname_var.set('RUN')
        assert _settle(root, lambda: line.cget('text') ==
                       _saves_to(app, os.path.join(local, 'RUN'))), \
            line.cget('text')
        assert line.cget('fg') == app.SLDEA_FOLDER_COLORS['ok']


def _line_threads():
    return [t for t in threading.enumerate() if t.name == LINE_THREAD]


def test_a_share_that_hangs_never_freezes_the_window():
    """Every keystroke redraws at once while the check hangs; the line
    says the Output dir is not answering; a burst of typing sends one
    check, and a burst while that one is stuck one more; the answer shows
    once it comes."""
    with tempfile.TemporaryDirectory() as tmp, _real_app() as (root, app), \
            _hanging_share() as gate:
        line = app.sldea_folder_line
        app.SLDEA_FOLDER_SLOW_S = 0.3
        app.sldea_outdir.set(tmp)
        worst = 0.0
        out = []
        for burst in (('A', 'AB', 'ABC'), ('ABCD', 'ABCDE')):
            for name in burst:
                # The trace runs the redraw inside set(): a stat made there
                # would hold it for the share's 30 s. Painting is timed
                # apart. Keys come faster than the pause before a check.
                t0 = time.monotonic()
                app.sldea_runname_var.set(name)
                worst = max(worst, time.monotonic() - t0)
                root.update()
                first = line.cget('text').split('\n')[0]
                assert first == _saves_to(app, os.path.join(tmp, name)), \
                    first
                _settle(root, lambda: False, timeout=0.1)
            # the last key of the burst: a check goes out, and hangs
            assert _settle(root, lambda: 'not answering' in
                           line.cget('text')), line.cget('text')
            assert line.cget('text').startswith(
                _saves_to(app, os.path.join(tmp, burst[-1]))), \
                line.cget('text')
            assert line.cget('fg') == WINE
            out.append(len(_line_threads()))
        assert worst < 0.5, worst
        assert out == [1, 2], out
        gate.set()
        assert _settle(root, lambda: line.cget('text') ==
                       _saves_to(app, os.path.join(tmp, 'ABCDE'))), \
            line.cget('text')


@contextlib.contextmanager
def _hanging_under(top):
    """sldea_profile.holds_run blocks until the yielded event is set for a
    folder under `top`, as on a share that has gone away, and is the real
    one anywhere else."""
    gate = threading.Event()
    real = sprof.holds_run
    hung = os.path.normcase(os.path.abspath(top))

    def maybe(folder):
        if os.path.normcase(os.path.abspath(folder)).startswith(hung):
            gate.wait(30)
            return []
        return real(folder)
    sprof.holds_run = maybe
    try:
        yield gate
    finally:
        gate.set()
        sprof.holds_run = real


def test_a_stuck_check_of_another_folder_never_claims_the_line():
    """#402 review, finding 5: a check stuck on a share made the line say
    "not answering" for whatever folder the boxes named, a local one
    included, until the stat returned, which on a hard mount may be never.
    The line now describes the folder the boxes name: switching the Output
    dir to a local folder, or the name to another one, drops the stuck
    check's claim at once, and the folder named now gets its own check."""
    with tempfile.TemporaryDirectory() as tmp, _real_app() as (root, app):
        hung, local = os.path.join(tmp, 'hung'), os.path.join(tmp, 'local')
        os.mkdir(hung)
        os.mkdir(local)
        _a_run_in(os.path.join(local, 'RUN'))
        line = app.sldea_folder_line
        app.SLDEA_FOLDER_SLOW_S = 0.3
        with _hanging_under(hung) as gate:
            app.sldea_outdir.set(hung)
            app.sldea_runname_var.set('RUN')
            assert _settle(root, lambda: 'not answering' in
                           line.cget('text')), line.cget('text')
            # the Output dir moves to a local folder: no claim, and checked
            app.sldea_outdir.set(local)
            root.update()
            assert 'not answering' not in line.cget('text'), \
                line.cget('text')
            assert line.cget('text') == _saves_to(
                app, os.path.join(local, 'RUN')), line.cget('text')
            assert _settle(root, lambda: _holds_run(line.cget('text'))), \
                line.cget('text')
            # the name changes while the check of another name is stuck
            app.sldea_outdir.set(hung)
            app.sldea_runname_var.set('A')
            assert _settle(root, lambda: 'not answering' in
                           line.cget('text')), line.cget('text')
            app.sldea_runname_var.set('B')
            root.update()
            assert line.cget('text') == _saves_to(
                app, os.path.join(hung, 'B')), line.cget('text')
            # B's own check hangs too, and the line says so for B
            assert _settle(root, lambda: 'not answering' in
                           line.cget('text')), line.cget('text')
            assert line.cget('text').startswith(
                _saves_to(app, os.path.join(hung, 'B')))
            gate.set()
            assert _settle(root, lambda: line.cget('text') ==
                           _saves_to(app, os.path.join(hung, 'B'))), \
                line.cget('text')


def test_the_line_names_the_running_runs_folder():
    """#402 review, finding 5: while a run was on, the line judged the
    boxes, and after a tab change it warned that the run's own folder
    "already holds a run". It now says "Writing to:" and the folder that
    run writes to, whatever the boxes say, until the run ends, and checks
    nothing meanwhile; then it judges the boxes again."""
    with tempfile.TemporaryDirectory() as tmp, _real_app() as (root, app):
        line = app.sldea_folder_line
        run = os.path.join(tmp, 'RUN')
        app.sldea_outdir.set(tmp)
        app.sldea_runname_var.set('RUN')
        assert _settle(root, lambda: line.cget('text') ==
                       _saves_to(app, run)), line.cget('text')
        # what sldea_run does once the worker is on its way, and what the
        # worker then writes
        app._sldea_running = True
        app._sldea_folder_run = (tmp, 'RUN')
        _a_run_in(run)
        app._sldea_folder_refresh()
        assert line.cget('text').startswith('Writing to: '), \
            line.cget('text')
        writing = sprof.fit_path('Writing to: ', os.path.abspath(run), '',
                                 app._sldea_folder_fits())
        assert line.cget('text') == writing, line.cget('text')
        # a tab change and retyped boxes leave it alone, and check nothing
        app.notebook.event_generate('<<NotebookTabChanged>>')
        app.sldea_runname_var.set('OTHER')
        app.sldea_outdir.set(os.path.join(tmp, 'elsewhere'))
        _settle(root, lambda: False, timeout=0.6)
        assert line.cget('text') == writing, line.cget('text')
        assert line.cget('fg') == app.SLDEA_FOLDER_COLORS['ok']
        assert app._sldea_folder_job is None
        # a blank name: the worker's stamped folder, once its run.log is
        # live
        app._sldea_folder_run = (tmp, '')
        app._sldea_folder_refresh()
        assert sprof.AUTO_RUN_DIRNAME in line.cget('text'), line.cget('text')
        stamped = os.path.join(tmp, 'SLDEA_20261008_131500')
        app._sldea_runlog = os.path.join(stamped, 'run.log')
        assert _settle(root, lambda: line.cget('text').endswith(
            'SLDEA_20261008_131500')), line.cget('text')
        # the run ends: the boxes are judged again
        app.sldea_outdir.set(tmp)
        app.sldea_runname_var.set('RUN')
        app._sldea_finished()
        assert _settle(root, lambda: _holds_run(line.cget('text'))), \
            line.cget('text')


def test_a_run_finished_while_its_folder_is_checked_is_seen():
    """#402 review, finding 6: _sldea_finished asks for a look while a
    check of the same folder is still out, one that looked before the run
    wrote. That check is asked to go again once it is back, so the line
    ends up warning; without that, its stale "no run" stood."""
    with tempfile.TemporaryDirectory() as tmp, _real_app() as (root, app):
        line = app.sldea_folder_line
        run = os.path.join(tmp, 'RUN')
        gate = threading.Event()
        calls = []
        real = sprof.holds_run

        def first_is_stale(folder):
            calls.append(folder)
            if len(calls) == 1:
                gate.wait(30)
                return []             # what it saw before the run wrote
            return real(folder)
        sprof.holds_run = first_is_stale
        try:
            app.sldea_outdir.set(tmp)
            app.sldea_runname_var.set('RUN')
            assert _settle(root, lambda: len(calls) == 1), calls
            _a_run_in(run)                       # the run writes...
            app._sldea_finished()                # ...and ends
            _settle(root, lambda: False, timeout=0.6)   # past the pause
            assert len(calls) == 1, calls        # one check out at a time
            gate.set()
            assert _settle(root, lambda: _holds_run(line.cget('text'))), \
                line.cget('text')
            assert len(calls) == 2, calls
        finally:
            gate.set()
            sprof.holds_run = real


def test_a_finished_run_turns_the_line_to_a_warning():
    """_sldea_finished asks the line to look again, so it warns about the
    folder the run just made before the next Run is refused for it."""
    with tempfile.TemporaryDirectory() as tmp, _real_app() as (root, app):
        line = app.sldea_folder_line
        app.sldea_outdir.set(tmp)
        app.sldea_runname_var.set('RUN')
        assert _settle(root, lambda: line.cget('text') ==
                       _saves_to(app, os.path.join(tmp, 'RUN'))), \
            line.cget('text')
        _a_run_in(os.path.join(tmp, 'RUN'))      # what the worker wrote
        app._sldea_finished()
        assert _settle(root, lambda: _holds_run(line.cget('text'))), \
            line.cget('text')


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
