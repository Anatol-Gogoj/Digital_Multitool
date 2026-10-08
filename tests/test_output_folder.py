#!/usr/bin/env python3
"""Browse and New folder... on the output-folder pickers (#394).

The bench's Tk folder dialog (tk_chooseDirectory) has no New Folder button,
and the SLDEA tab's Browse opened at the working directory instead of at
the folder in the box. Three layers, cheapest first:

  * output_folder on its own (stdlib only, so it also runs on Linux without
    tkinter): what a new folder's name may not be, what an empty or missing
    box says, that exactly one folder is made and never a parent, the
    message for an unwritable parent (a real one on POSIX), and where
    Browse opens.
  * ui_widgets.new_folder / browse_folder behind fake dialogs: the
    refusals, the re-ask, Cancel, the box update, and that a refusal from
    the system is a message, not a traceback. Needs tkinter importable,
    not a display.
  * the real app (needs a display): the button beside Browse on the SLDEA,
    Webcam and Continuous Logging tabs, each wired to its own box and to
    the share's mount point; Browse opening at the box's folder; the SLDEA
    tab's two pickers refusing with a note while a run is on (LIVE or DRY)
    while the Logging and Webcam ones stay open, also while logging runs;
    and, on their source, the run workers never reading the box.

Run: .venv/bin/python tests/test_output_folder.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import contextlib
import errno
import os
import shutil
import string
import tempfile
import threading

import output_folder as of


class _Skip(Exception):
    """The test could not run here -- reported, not passed."""


@contextlib.contextmanager
def _tmpdir():
    path = tempfile.mkdtemp(prefix='newfolder_')
    try:
        yield path
    finally:
        # a POSIX case leaves a folder read-only; give it back first
        for top, dirs, _files in os.walk(path):
            for name in dirs:
                try:
                    os.chmod(os.path.join(top, name), 0o755)
                except OSError:
                    pass
        shutil.rmtree(path, ignore_errors=True)


def _touch(path):
    with open(path, 'w'):
        pass
    return path


def _refusal(where, name):
    """make() must refuse: -> its message."""
    try:
        of.make(where, name)
    except ValueError as e:
        return str(e)
    raise AssertionError(f"{name!r} was not refused")


# --------------------------------------------------------------------------
# output_folder on its own (stdlib only)
# --------------------------------------------------------------------------

def test_an_empty_name_or_a_bare_dot_is_refused():
    for name in ('', '   ', None):
        assert of.name_problem(name) == "Type a name for the new folder.", name
    for name in ('.', '..', ' .. '):
        msg = of.name_problem(name)
        assert msg and 'is not a folder name' in msg, (name, msg)


def test_either_separator_is_refused_on_every_os():
    """This makes ONE folder. On Linux a backslash is an ordinary character
    and would quietly become part of the name, so it is refused there too,
    with the same message."""
    for name in ('a/b', 'a\\b', '/abs', '\\\\server\\share', 'runs/',
                 '..\\x', 'C:\\x'):
        msg = of.name_problem(name)
        assert msg and '/ or \\' in msg, (name, msg)


def test_a_name_windows_cannot_hold_is_refused():
    """The share is also read from the lab's Windows PCs. ':' matters on
    Windows itself as well: os.path.join('C:\\data', 'D:x') is 'D:x', a
    folder outside the box."""
    for ch in '<>:"|?*':
        msg = of.name_problem(f'run{ch}1')
        assert msg and f'contain {ch}.' in msg and 'Windows' in msg, (ch, msg)
    msg = of.name_problem('P3: 2.5mL?')
    assert 'contain : ?.' in msg and 'them' in msg, msg
    # inside the name: str.strip() takes tabs and \x1c-\x1f off the ENDS,
    # as it does spaces, so 'x\x1f' is the name 'x'
    for name in ('run\t1', 'a\x00b', 'x\x1fy'):
        assert 'control character' in (of.name_problem(name) or ''), \
            repr(name)
    assert of.name_problem('x\x1f') is None
    for name in ('run.', 'run. ', 'v2..'):
        assert 'end with a dot' in of.name_problem(name), name
    for name in ('CON', 'con', 'Nul', 'aux.txt', 'COM1', 'lpt9.log',
                 'con .x'):
        assert 'device name on Windows' in of.name_problem(name), name


def test_the_device_names_match_cpythons_own_list():
    """output_folder copies CPython 3.13's ntpath.isreserved device set
    (the bench runs 3.11, which has none). Where isreserved exists, the
    two must agree on every name that only the device rule decides."""
    import ntpath
    if not hasattr(ntpath, 'isreserved'):
        raise _Skip("ntpath.isreserved needs Python 3.13")
    stems = (['CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$', 'CONSOLE',
              'NULL', 'LPT', 'COM', 'AUXILIARY', 'CONTROL']
             + [f'{p}{d}' for p in ('COM', 'LPT')
                for d in '0123456789\u00b9\u00b2\u00b3']
             + ['COM10', 'LPT10'])
    checked = 0
    for stem in stems:
        for name in (stem, stem.lower(), stem.title(), f'{stem}.txt',
                     f'{stem} .log', f'{stem}x'):
            ours = 'device name' in (of.name_problem(name) or '')
            assert ours == ntpath.isreserved(name), (name, ours)
            checked += 1
    assert checked > 150, checked


def test_ordinary_names_pass():
    for name in ('P3_2.5mL_Triazole', '2026-10-06 session 2', 'run (2)',
                 'Probe #4', 'CNT+CB mix', 'P3 2.5uL', '  padded  ',
                 'CONSOLE', 'con test', 'COM10', 'my.folder', '.hidden'):
        assert of.name_problem(name) is None, (name, of.name_problem(name))


def test_a_name_that_is_not_plain_ascii_is_refused():
    """cv2 4.13 on Windows (the pinned build) cannot write or read an image
    under a folder whose path holds any of these (measured 2026-10-07), so
    the Webcam's saves and Edge Review would fail in such a folder. The
    message says which characters, and offers u for the micro sign."""
    for name, odd in (('P3 2.5\u00b5L', '\u00b5'),          # micro sign
                      ('P3 2.5\u03bcL', '\u03bc'),          # Greek mu
                      ('r\u00e9sum\u00e9', '\u00e9'),
                      ('na\u00efve caf\u00e9', '\u00e9 \u00ef'),
                      ('run \U0001F600', '\U0001F600'),
                      ('\u00a0nbsp inside\u00a0x', '\u00a0')):
        msg = of.name_problem(name)
        assert msg and 'plain ASCII' in msg, (name, msg)
        assert f"and {odd} " in msg, (name, msg)
        assert 'u for \u00b5, as in 2.5uL' in msg, msg
    assert 'are not' in of.name_problem('na\u00efve caf\u00e9')
    assert 'is not' in of.name_problem('r\u00e9sum\u00e9')


def test_make_makes_exactly_one_folder_and_returns_its_path():
    with _tmpdir() as tmp:
        path = of.make(tmp, '  day 1  ')
        assert path == os.path.join(tmp, 'day 1'), path
        assert os.path.isdir(path)
        assert os.listdir(tmp) == ['day 1'], os.listdir(tmp)
        assert os.listdir(path) == []


def test_make_refuses_a_name_already_taken_and_changes_nothing():
    with _tmpdir() as tmp:
        os.mkdir(os.path.join(tmp, 'taken'))
        _touch(os.path.join(tmp, 'notes'))
        msg = _refusal(tmp, 'taken')
        assert msg.startswith(f"There is already a folder called 'taken' "
                              f"in\n{tmp}\n"), msg
        assert 'use Browse to choose that folder' in msg, msg
        msg = _refusal(tmp, ' notes ')
        assert msg.startswith(f"There is already a file called 'notes' "
                              f"in\n{tmp}\n"), msg
        assert 'Browse' not in msg, msg
        assert sorted(os.listdir(tmp)) == ['notes', 'taken']
        assert os.listdir(os.path.join(tmp, 'taken')) == []


def test_make_refuses_every_bad_name_before_touching_the_disk():
    with _tmpdir() as tmp:
        for name in ('', ' ', '.', '..', 'a/b', 'a\\b', 'D:x', 'C:x', 'x?',
                     'run.', 'CON', 'tab\there', 'r\u00e9sum\u00e9',
                     'P3 2.5\u00b5L'):
            _refusal(tmp, name)
        assert os.listdir(tmp) == [], os.listdir(tmp)


def test_make_never_makes_a_missing_parent():
    """os.mkdir, not os.makedirs: a box whose folder vanished after the
    check (a share dropping) must fail, not be rebuilt under the bare
    mount point on the local disk."""
    with _tmpdir() as tmp:
        gone = os.path.join(tmp, 'share', 'SLDEA_data')
        try:
            of.make(gone, 'today')
        except FileNotFoundError as e:
            msg = of.failed_text(gone, 'today', e)
        else:
            raise AssertionError("made a folder under a missing parent")
        assert os.listdir(tmp) == [], os.listdir(tmp)
        assert msg.startswith("Could not make the folder\n"
                              + os.path.join(gone, 'today')), msg


def test_an_unwritable_parent_is_refused_by_the_system_for_real():
    """A real read-only folder, where the OS honors one (POSIX, not root).
    Windows ignores chmod on folders (tests/test_presets_path.py), so there
    the helper layer below fakes the refusal instead."""
    if os.name != 'posix':
        raise _Skip("Windows ignores chmod on folders")
    if os.geteuid() == 0:
        raise _Skip("root writes into read-only folders")
    with _tmpdir() as tmp:
        ro = os.path.join(tmp, 'ro')
        os.mkdir(ro)
        os.chmod(ro, 0o555)
        try:
            of.make(ro, 'new')
        except PermissionError as e:
            msg = of.failed_text(ro, 'new', e)
        else:
            raise AssertionError("made a folder in a read-only parent")
        finally:
            os.chmod(ro, 0o755)
        assert os.listdir(ro) == []
        assert msg == (f"Could not make the folder\n{ro}/new\n\nPermission "
                       f"denied.\n\nIf it is on the share, check that the "
                       f"share is mounted and that you can write to it."), msg


def test_the_failure_message_names_the_folder_the_reason_and_the_share():
    where = os.path.join('mnt', 'share')
    for err, reason in (
            (PermissionError(errno.EACCES, 'Permission denied'),
             'Permission denied.'),
            (OSError(30, 'Read-only file system'),          # EROFS
             'Read-only file system.'),
            (OSError(112, 'Host is down'), 'Host is down.'),  # 2026-07-20
            (OSError('a reason with no errno.'),
             'a reason with no errno.'),
            (OSError(), 'OSError.')):
        msg = of.failed_text(where, ' new ', err)
        assert msg.startswith(
            f"Could not make the folder\n{os.path.join(where, 'new')}\n\n"
            f"{reason}\n\n"), (err, msg)
        assert msg.endswith("check that the share is mounted and that you "
                            "can write to it."), msg


def test_an_empty_missing_or_file_box_is_explained_and_no_parent_guessed():
    with _tmpdir() as tmp:
        a_file = _touch(os.path.join(tmp, 'a_file'))
        gone = os.path.join(tmp, 'gone')
        assert of.parent_problem(tmp, 'Output dir') is None
        assert of.parent_problem(f'  {tmp}  ', 'Output dir') is None
        for where in ('', '   ', None):
            msg = of.parent_problem(where, 'Output dir')
            assert msg.startswith('The Output dir box is empty, so there is '
                                  'no folder to make the new one in.'), msg
            assert 'use Browse' in msg and of.NEW_FOLDER_LABEL in msg, msg
        msg = of.parent_problem(gone, 'Save to')
        assert msg.startswith(f"The folder in the Save to box does not "
                              f"exist:\n{gone}\n"), msg
        assert 'check that the share is mounted' in msg, msg
        msg = of.parent_problem(a_file, 'Log Directory')
        assert msg.startswith(f"The Log Directory box names a file, not a "
                              f"folder:\n{a_file}\n"), msg
        assert os.listdir(tmp) == ['a_file'], os.listdir(tmp)


def test_the_share_mount_point_is_read_off_a_share_path():
    """Its first two levels: /mnt/shareDrive for the SLDEA tab's built-in
    Output dir. Nothing that is not an absolute Linux path that deep."""
    share = '/mnt/shareDrive/robot_incubator/SLDEA_data'
    assert of.share_mount(share) == '/mnt/shareDrive'
    assert of.share_mount('/mnt//shareDrive/x/') == '/mnt/shareDrive'
    assert of.share_mount('/mnt/shareDrive') == '/mnt/shareDrive'
    for other in ('', None, '/', '/mnt', 'mnt/shareDrive/x', 'C:\\SLDEA',
                  'C:/SLDEA/runs', 'Z:\\Anatol Gogoj\\runs'):
        assert of.share_mount(other) is None, other


def _fake_ismount(mount, mounted):
    """os.path.ismount, except that `mount` is or is not one as told: a
    test cannot mount or unmount anything."""
    def ismount(path):
        if os.path.normcase(os.path.abspath(path)) == \
                os.path.normcase(os.path.abspath(mount)):
            return mounted
        return os.path.ismount(path)
    return ismount


def test_a_folder_on_an_unmounted_share_is_refused():
    """With the share not mounted, its mount point is a plain folder on the
    PC's own disk, and so is anything left under it: a folder made there
    would stay on the PC. Mounted, the same folders are fine, and so is a
    folder that only starts with the mount point's name."""
    with _tmpdir() as tmp:
        mount = os.path.join(tmp, 'mnt', 'shareDrive')
        data = os.path.join(mount, 'robot_incubator', 'SLDEA_data')
        os.makedirs(data)
        twin = os.path.join(tmp, 'mnt', 'shareDrive2')
        local = os.path.join(tmp, 'local')
        os.mkdir(twin)
        os.mkdir(local)
        for mounted in (False, True):
            fake = _OsProxy(os.path, {'ismount': _fake_ismount(mount,
                                                               mounted)})
            with _os_patched(of, path=fake):
                for where in (mount, data, data + os.sep, f'  {data}  '):
                    msg = of.parent_problem(where, 'Output dir', mount=mount)
                    if mounted:
                        assert msg is None, (where, msg)
                        continue
                    assert msg and msg.startswith(
                        f"The share is not mounted at {mount}, so the folder "
                        f"in the Output dir box is on this PC's own disk:\n"
                        f"{where.strip()}\n"), (where, msg)
                    assert 'would stay on this PC' in msg, msg
                    assert of.NEW_FOLDER_LABEL in msg, msg
                for where in (twin, local):
                    assert of.parent_problem(where, 'Output dir',
                                             mount=mount) is None, where
                # no mount point known, no check
                assert of.parent_problem(data, 'Output dir') is None
        assert sorted(os.listdir(os.path.join(tmp, 'mnt'))) == [
            'shareDrive', 'shareDrive2']


def test_the_mount_check_with_the_real_ismount_on_linux():
    """No fake here: a plain folder standing in for the mount point is
    refused, which is exactly what an unmounted share's mount point is,
    and a real mount point (/proc) is not."""
    if os.name != 'posix':
        raise _Skip("needs a POSIX mount table")
    if not os.path.ismount('/proc'):
        raise _Skip("/proc is not a mount point here")
    with _tmpdir() as tmp:
        bare = os.path.join(tmp, 'shareDrive')
        os.mkdir(bare)
        msg = of.parent_problem(bare, 'Output dir', mount=bare)
        assert msg and 'share is not mounted' in msg, msg
    assert of.parent_problem('/proc', 'Output dir', mount='/proc') is None


def test_browse_opens_at_the_folder_in_the_box():
    with _tmpdir() as tmp:
        runs = os.path.join(tmp, 'runs')
        os.mkdir(runs)
        assert of.browse_start(runs) == os.path.abspath(runs)
        assert of.browse_start(f'  {runs}  ') == os.path.abspath(runs)


def test_browse_falls_back_to_the_nearest_folder_that_exists():
    with _tmpdir() as tmp:
        gone = os.path.join(tmp, 'runs', 'deleted', 'deeper')
        assert of.browse_start(gone) == os.path.abspath(tmp)
        runs = os.path.join(tmp, 'runs')
        os.mkdir(runs)
        assert of.browse_start(gone) == os.path.abspath(runs)
        data = _touch(os.path.join(runs, 'data.csv'))     # a file in the box
        assert of.browse_start(data) == os.path.abspath(runs)


def test_browse_with_an_empty_box_opens_at_the_working_directory():
    """Where an empty box sends an SLDEA run (os.path.join('', name)) and
    the Webcam's images (`or '.'`); the Webcam's Browse opened there too.
    A relative box resolves against the same directory, as the run does."""
    for box in ('', '   ', None):
        assert of.browse_start(box) == os.getcwd(), box
    here = os.getcwd()
    with _tmpdir() as tmp:
        os.chdir(tmp)
        try:
            os.mkdir('logs')
            logs = os.path.join(os.getcwd(), 'logs')
            assert of.browse_start('./logs') == logs
            assert of.browse_start('logs/not yet') == logs
        finally:
            os.chdir(here)


def test_browse_with_nothing_on_the_path_opens_at_the_working_directory():
    """A box on a drive letter that is not there at all."""
    if os.name != 'nt':
        raise _Skip("POSIX always has /, so some folder on a path exists")
    import ctypes
    # GetLogicalDrives, not os.path.exists: probing a mapped drive that is
    # offline can stall for seconds
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    free = [c for i, c in enumerate(string.ascii_uppercase)
            if i >= 3 and not mask & (1 << i)]
    if not free:
        raise _Skip("every drive letter is in use")
    assert of.browse_start(f'{free[0]}:\\Anatol Gogoj\\runs') == os.getcwd()


def test_the_new_path_keeps_the_box_separator():
    if os.sep == '\\':
        assert of.new_path('C:/data', 'run1') == 'C:/data/run1'
        assert of.new_path('C:/data/', 'run1') == 'C:/data/run1'
        assert of.new_path('C:\\data', 'run1') == 'C:\\data\\run1'
        assert of.new_path('C:/a\\b', 'run1') == 'C:/a\\b\\run1'
    else:
        assert of.new_path('/mnt/data', 'run1') == '/mnt/data/run1'
        assert of.new_path('/mnt/data/', 'run1') == '/mnt/data/run1'
        # on Linux a backslash is part of a name, never a separator
        assert of.new_path('/mnt/a\\b', 'run1') == '/mnt/a\\b/run1'


# --------------------------------------------------------------------------
# ui_widgets.new_folder / browse_folder behind fake dialogs (no display)
# --------------------------------------------------------------------------

def _ui():
    try:
        import ui_widgets
    except ImportError as e:              # Linux without tkinter
        raise _Skip(f"no tkinter: {e}")
    return ui_widgets


class _Var:
    """A tk.StringVar stand-in: no Tk interpreter needed."""

    def __init__(self, value=''):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Dialogs:
    """Stands in for filedialog, simpledialog and messagebox at once.

    Records every call as (kind, title, text, kwargs). askstring answers
    from `names` and then Cancels; askdirectory answers `folder`. Any other
    dialog fails the test: an unexpected dialog is a finding."""

    def __init__(self, names=(), folder=''):
        self.names = list(names)
        self.folder = folder
        self.calls = []

    def askstring(self, title, prompt, **kw):
        self.calls.append(('askstring', title, prompt, kw))
        return self.names.pop(0) if self.names else None

    def askdirectory(self, **kw):
        self.calls.append(('askdirectory', None, None, kw))
        return self.folder

    def showerror(self, title, message, **kw):
        self.calls.append(('showerror', title, message, kw))

    def showinfo(self, title, message, **kw):
        self.calls.append(('showinfo', title, message, kw))

    def __getattr__(self, name):
        raise AssertionError(f"unexpected dialog: {name}")

    def kinds(self):
        return [c[0] for c in self.calls]

    def texts(self, kind):
        return [c[2] for c in self.calls if c[0] == kind]


@contextlib.contextmanager
def _fake_dialogs(*modules, **answers):
    """Install one _Dialogs as each module's filedialog, simpledialog and
    messagebox, and put the real ones back after."""
    d = _Dialogs(**answers)
    names = ('filedialog', 'simpledialog', 'messagebox')
    saved = [(m, n, getattr(m, n)) for m in modules for n in names
             if hasattr(m, n)]
    for m, n, _real in saved:
        setattr(m, n, d)
    try:
        yield d
    finally:
        for m, n, real in saved:
            setattr(m, n, real)


class _OsProxy:
    """`os`, with some of its functions replaced (see _os_patched)."""

    def __init__(self, real, over):
        self._real, self._over = real, over

    def __getattr__(self, name):
        if name in self._over:
            return self._over[name]
        return getattr(self._real, name)


@contextlib.contextmanager
def _os_patched(module, **over):
    """Replace functions of `os` as `module` sees them, and only there."""
    saved = module.os
    module.os = _OsProxy(saved, over)
    try:
        yield
    finally:
        module.os = saved


def test_new_folder_makes_it_inside_the_box_and_fills_the_box():
    ui = _ui()
    with _tmpdir() as tmp, _fake_dialogs(ui, names=['  day 1 ']) as d:
        var = _Var(tmp)
        got = ui.new_folder(var, 'Output dir')
        want = os.path.join(tmp, 'day 1')
        assert got == want and var.get() == want, (got, var.get())
        assert os.path.isdir(want) and os.listdir(tmp) == ['day 1']
        assert d.kinds() == ['askstring'], d.calls
        _kind, title, prompt, kw = d.calls[0]
        assert title == 'New folder' and tmp in prompt, d.calls
        assert kw == {'initialvalue': ''}, kw


def test_a_refused_name_is_explained_and_asked_again_holding_it():
    ui = _ui()
    answers = ['', '.', '..', 'a/b', 'a\\b', 'taken', 'P3: 2.5 mL',
               'P3 2.5\u00b5L', 'P3 2.5uL']
    expect = ['Type a name', 'is not a folder name', 'is not a folder name',
              '/ or \\', '/ or \\', "already a folder called 'taken'",
              'cannot contain :.', 'u for \u00b5']
    with _tmpdir() as tmp:
        os.mkdir(os.path.join(tmp, 'taken'))
        with _fake_dialogs(ui, names=answers) as d:
            var = _Var(tmp)
            got = ui.new_folder(var, 'Output dir', parent='PARENT')
        want = os.path.join(tmp, 'P3 2.5uL')
        assert got == want == var.get(), (got, var.get())
        errors = d.texts('showerror')
        assert len(errors) == len(expect), errors
        for msg, text in zip(errors, expect):
            assert text in msg, (text, msg)
        asks = [c for c in d.calls if c[0] == 'askstring']
        # each re-ask holds what was typed, to be fixed rather than retyped
        assert [a[3]['initialvalue'] for a in asks] == [''] + answers[:-1]
        assert all(c[3]['parent'] == 'PARENT' for c in d.calls), d.calls
        assert sorted(os.listdir(tmp)) == ['P3 2.5uL', 'taken']


def test_cancel_makes_nothing_and_leaves_the_box():
    ui = _ui()
    with _tmpdir() as tmp:
        for names in ([], ['a/b']):            # at once, or after a refusal
            with _fake_dialogs(ui, names=names) as d:
                var = _Var(tmp)
                assert ui.new_folder(var, 'Output dir') is None
            assert var.get() == tmp
            assert d.kinds() == ['askstring', 'showerror'] * len(names) + [
                'askstring'], d.calls
        assert os.listdir(tmp) == []


def test_an_empty_or_missing_box_is_explained_and_nothing_is_asked():
    ui = _ui()
    with _tmpdir() as tmp:
        gone = os.path.join(tmp, 'share', 'SLDEA_data')
        a_file = _touch(os.path.join(tmp, 'file.txt'))
        for box in ('', '   ', gone, a_file):
            with _fake_dialogs(ui, names=['never asked']) as d:
                var = _Var(box)
                assert ui.new_folder(var, 'Output dir') is None
            assert d.kinds() == ['showerror'], (box, d.calls)
            assert 'Output dir box' in d.calls[0][2], d.calls
            assert var.get() == box
        assert os.listdir(tmp) == ['file.txt'], os.listdir(tmp)


def test_an_unwritable_parent_is_a_message_not_a_traceback():
    """A read-only or missing share, faked at output_folder's os.mkdir
    (Windows ignores chmod on folders; the real POSIX refusal is pinned in
    the first layer). One message, no re-ask, the box untouched."""
    ui = _ui()
    with _tmpdir() as tmp:
        for exc, num, text in (
                (PermissionError, errno.EACCES, 'Permission denied'),
                (OSError, 30, 'Read-only file system'),           # EROFS
                (FileNotFoundError, errno.ENOENT,
                 'No such file or directory')):    # the share dropped

            def refuse(path, *_a, exc=exc, num=num, text=text, **_k):
                raise exc(num, text, path)

            with _fake_dialogs(ui, names=['day 1', 'never asked']) as d, \
                    _os_patched(of, mkdir=refuse):
                var = _Var(tmp)
                assert ui.new_folder(var, 'Output dir') is None
            assert d.kinds() == ['askstring', 'showerror'], d.calls
            msg = d.calls[1][2]
            assert msg.startswith(f"Could not make the folder\n"
                                  f"{os.path.join(tmp, 'day 1')}\n\n"
                                  f"{text}.\n"), msg
            assert 'share is mounted' in msg, msg
            assert var.get() == tmp
        assert os.listdir(tmp) == []


def test_new_folder_on_an_unmounted_share_asks_nothing():
    """new_folder reads the mount point off `share` and refuses before the
    prompt, so nothing is asked and nothing is made on the bare mount
    point. share_mount is pointed at a temp folder: the real one is Linux's
    /mnt/shareDrive."""
    ui = _ui()
    share = '/mnt/shareDrive/robot_incubator/SLDEA_data'
    with _tmpdir() as tmp:
        mount = os.path.join(tmp, 'mnt', 'shareDrive')
        os.makedirs(mount)
        saved = of.share_mount
        of.share_mount = lambda s: mount if s == share else None
        try:
            fake = _OsProxy(os.path, {'ismount': _fake_ismount(mount, False)})
            with _fake_dialogs(ui, names=['never asked']) as d, \
                    _os_patched(of, path=fake):
                var = _Var(mount)
                assert ui.new_folder(var, 'Save to', share=share) is None
                assert d.kinds() == ['showerror'], d.calls
                assert 'share is not mounted' in d.calls[0][2], d.calls
                assert var.get() == mount and os.listdir(mount) == []
                # without the share's path nothing knows the mount point
                with _fake_dialogs(ui, names=['day 1']) as d2:
                    assert ui.new_folder(var, 'Save to') == os.path.join(
                        mount, 'day 1')
                assert d2.kinds() == ['askstring'], d2.calls
        finally:
            of.share_mount = saved
        assert os.listdir(mount) == ['day 1']


def test_browse_opens_at_the_box_and_cancel_changes_nothing():
    ui = _ui()
    with _tmpdir() as tmp:
        runs = os.path.join(tmp, 'runs')
        os.mkdir(runs)
        gone = os.path.join(runs, 'deleted')
        for box, start in ((runs, runs), (gone, runs), ('', os.getcwd())):
            with _fake_dialogs(ui, folder='') as d:
                var = _Var(box)
                assert ui.browse_folder(var) is None
            assert d.kinds() == ['askdirectory'], d.calls
            assert d.calls[0][3] == {'initialdir': os.path.abspath(start)}, \
                (box, d.calls)
            assert var.get() == box
        with _fake_dialogs(ui, folder=tmp) as d:
            var = _Var(runs)
            assert ui.browse_folder(var, parent='PARENT') == tmp
        assert var.get() == tmp
        assert d.calls[0][3] == {'initialdir': os.path.abspath(runs),
                                 'parent': 'PARENT'}, d.calls


# --------------------------------------------------------------------------
# The real app (needs a display)
# --------------------------------------------------------------------------

# (button prefix, the box's variable, the box's name in messages)
TABS = (('sldea', 'sldea_outdir', 'Output dir'),
        ('cam', 'cam_dir_var', 'Save to'),
        ('log', 'log_dir', 'Log Directory'))


def _app():
    """(root, app) with every tab built, or raise _Skip."""
    try:
        import tkinter as tk
    except ImportError as e:
        raise _Skip(f"no tkinter: {e}")
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    import gui
    # No instrument hunt: irrelevant here, and it starts threads.
    gui.InstrumentControlGUI.auto_connect = lambda self: None
    app = gui.InstrumentControlGUI(root)
    root.update_idletasks()
    return root, app


def _app_dialogs(**answers):
    """Fake dialogs for the app: ui_widgets' (the helpers) and gui's own,
    so a picker that still called the real dialog could not block."""
    import gui
    import ui_widgets
    return _fake_dialogs(ui_widgets, gui, **answers)


class _MB:
    """gui.messagebox stand-in for the run starts: answers questions by
    title; a question it has no answer for fails the test."""

    def __init__(self, answers):
        self.answers = dict(answers)
        self.calls = []

    def askyesno(self, title, message, **kw):
        self.calls.append(('askyesno', title, message))
        if title not in self.answers:
            raise AssertionError(f"unexpected question: {title!r}")
        return self.answers[title]

    def __getattr__(self, name):
        if name.startswith('show'):
            def note(title, message, **kw):
                self.calls.append((name, title, message))
            return note
        raise AttributeError(name)


def _enabled(btn):
    return btn.instate(['!disabled'])


def test_each_tab_has_new_folder_right_beside_browse():
    root, app = _app()
    try:
        for prefix, _var_name, _box in TABS:
            browse = getattr(app, f'{prefix}_browse_btn')
            new = getattr(app, f'{prefix}_newdir_btn')
            assert browse.cget('text') == 'Browse', prefix
            assert new.cget('text') == of.NEW_FOLDER_LABEL, prefix
            assert browse.master is new.master, prefix
            assert browse.master.pack_slaves() == [browse, new], prefix
            assert _enabled(browse) and _enabled(new), prefix
        # each pair stands where Browse alone stood
        for prefix in ('sldea', 'log'):
            info = getattr(app, f'{prefix}_browse_btn').master.grid_info()
            assert (int(info['row']), int(info['column'])) == (0, 2), info
        row = app.cam_browse_btn.master.master.pack_slaves()
        here = row.index(app.cam_browse_btn.master)
        assert row[here - 1].winfo_class() == 'TEntry', row
        assert str(row[here - 1].cget('textvariable')) == str(app.cam_dir_var)
    finally:
        root.destroy()


def test_each_tabs_buttons_work_on_its_own_box():
    root, app = _app()
    try:
        with _tmpdir() as tmp:
            for prefix, var_name, box in TABS:
                var = getattr(app, var_name)
                others = {n: getattr(app, n).get()
                          for _p, n, _b in TABS if n != var_name}
                var.set(tmp)
                with _app_dialogs(names=[f'{prefix} day']) as d:
                    getattr(app, f'{prefix}_newdir_btn').invoke()
                want = of.new_path(tmp, f'{prefix} day')
                assert var.get() == want and os.path.isdir(want), \
                    (prefix, var.get(), d.calls)
                assert d.kinds() == ['askstring'], (prefix, d.calls)
                assert d.calls[0][3]['parent'] is app.root
                assert {n: getattr(app, n).get() for n in others} == others
                assert app.status_bar.cget('text') == \
                    f"New folder made: {want}", app.status_bar.cget('text')
                # Browse opens at the folder now in the box
                with _app_dialogs(folder='') as d:
                    getattr(app, f'{prefix}_browse_btn').invoke()
                assert d.kinds() == ['askdirectory'], (prefix, d.calls)
                assert d.calls[0][3] == {'initialdir': os.path.abspath(want),
                                         'parent': app.root}, d.calls
                assert var.get() == want
                # an empty box is explained, and nothing is asked
                var.set('')
                with _app_dialogs(names=['never asked']) as d:
                    getattr(app, f'{prefix}_newdir_btn').invoke()
                assert d.kinds() == ['showerror'], (prefix, d.calls)
                assert d.calls[0][2].startswith(f"The {box} box is empty"), \
                    d.calls
            assert sorted(os.listdir(tmp)) == ['cam day', 'log day',
                                               'sldea day']
    finally:
        root.destroy()


def test_every_tab_checks_the_share_mount_point():
    """Each tab's New folder... hands new_folder the SLDEA tab's built-in
    share path, the one place the app knows where the share lives, so the
    bare-mount-point check covers the Webcam and Logging boxes too."""
    root, app = _app()
    import gui
    saved = gui.new_folder
    seen = []
    gui.new_folder = lambda var, box, parent=None, share=None: \
        seen.append((box, share))
    try:
        for prefix, _var_name, _box in TABS:
            getattr(app, f'{prefix}_newdir_btn').invoke()
        share = gui.InstrumentControlGUI.SLDEA_SHARE_DIR
        assert share == '/mnt/shareDrive/robot_incubator/SLDEA_data'
        assert seen == [(box, share) for _p, _v, box in TABS], seen
        assert of.share_mount(share) == '/mnt/shareDrive'
    finally:
        gui.new_folder = saved
        root.destroy()


def test_during_an_sldea_run_both_pickers_refuse_with_a_note():
    """The real sldea_run, LIVE and then DRY, up to the worker (a stand-in
    that only records its arguments). While it runs, Output dir's Browse
    and New folder... both refuse with a note and change nothing: the run
    keeps the folder it started in, and the box also aims Edge Review, the
    tuner and the plot window. The two buttons stay in one state, the
    Logging and Webcam pickers are not locked, and once the run has ended
    both SLDEA pickers work again. That the running run keeps its own
    folder is pinned on the worker's source, in
    test_the_workers_never_read_the_box_themselves."""
    root, app = _app()
    import gui
    saved = (gui.messagebox, gui.INSTRUMENTS_SUPPORTED)
    try:
        with _tmpdir() as tmp:
            # every question a run start with blank device fields asks;
            # #398 adds the film thickness one (harmless before it lands)
            gui.messagebox = _MB({
                'No current monitoring': True, 'Energize HV?': True,
                'No electrode specified': True,
                'No concentration specified': True,
                'No film thickness specified': True})
            gui.INSTRUMENTS_SUPPORTED = True    # the LIVE path on any OS
            app.sg = object()     # "connected"; the stand-in never drives it
            app.scope = None
            app._sldea_skip_preflight = True
            app._sldea_live_view = None     # no live-view window in a test
            for dry in (False, True):
                started = threading.Event()
                seen = {}

                def worker(*args, _seen=seen, _started=started, **_kw):
                    _seen['args'] = args
                    _started.set()

                app._sldea_worker = worker
                app.sldea_outdir.set(tmp)
                app.sldea_dryrun.set(dry)
                app._sldea_dry_toggle()
                app.sldea_run()
                assert started.wait(5), (dry, gui.messagebox.calls)
                # the run really is on, LIVE the first time, DRY the second
                assert app._sldea_running, dry
                assert (app._sldea_live_ch is None) == dry
                assert str(app.sldea_run_btn.cget('state')) == 'disabled'
                assert seen['args'][1] == tmp and seen['args'][6] is dry
                # the two buttons stay in one state...
                assert _enabled(app.sldea_newdir_btn) == \
                    _enabled(app.sldea_browse_btn) is True
                # ...and both refuse, asking nothing and changing nothing
                before = sorted(os.listdir(tmp))
                for btn in (app.sldea_browse_btn, app.sldea_newdir_btn):
                    with _app_dialogs(names=['not now'], folder=tmp) as d:
                        btn.invoke()
                    assert d.kinds() == ['showinfo'], (dry, d.calls)
                    title, text = d.calls[0][1], d.calls[0][2]
                    assert title == 'SLDEA Output dir', title
                    assert text.startswith('A run is in progress.'), text
                    assert 'Abort first' in text, text
                    assert app.sldea_outdir.get() == tmp
                assert sorted(os.listdir(tmp)) == before
                # an SLDEA run locks only the SLDEA tab's pickers
                for prefix, var_name in (('log', 'log_dir'),
                                         ('cam', 'cam_dir_var')):
                    getattr(app, var_name).set(tmp)
                    name = f'{prefix} during {"dry" if dry else "live"}'
                    with _app_dialogs(names=[name]) as d:
                        getattr(app, f'{prefix}_newdir_btn').invoke()
                    assert d.kinds() == ['askstring'], (prefix, d.calls)
                    assert getattr(app, var_name).get() == \
                        of.new_path(tmp, name)
                app._sldea_finished()
                assert not app._sldea_running
                assert _enabled(app.sldea_newdir_btn) == \
                    _enabled(app.sldea_browse_btn) is True
                # after the run, both work again
                name = f'after {"dry" if dry else "live"}'
                with _app_dialogs(names=[name]) as d:
                    app.sldea_newdir_btn.invoke()
                assert d.kinds() == ['askstring'], d.calls
                assert app.sldea_outdir.get() == of.new_path(tmp, name)
                with _app_dialogs(folder='') as d:
                    app.sldea_browse_btn.invoke()
                assert d.kinds() == ['askdirectory'], d.calls
            assert sorted(os.listdir(tmp)) == [
                'after dry', 'after live', 'cam during dry',
                'cam during live', 'log during dry', 'log during live']
    finally:
        gui.messagebox, gui.INSTRUMENTS_SUPPORTED = saved
        root.destroy()


def test_while_logging_runs_new_folder_stays_as_browse_does():
    """The real start_logging with a stand-in worker, as in
    tests/test_continuous_log.py. Neither button is locked while logging
    runs; that the running log keeps its own folder is pinned on the
    worker's source, in test_the_workers_never_read_the_box_themselves."""
    root, app = _app()
    import gui
    saved = gui.messagebox
    runs = []
    try:
        with _tmpdir() as tmp:
            gui.messagebox = _MB({})
            app._logging_worker = lambda interval, cfg, tok: runs.append(cfg)
            app.psu = object()            # "connected"; never called
            app.log_lcr.set(False)
            for ch in range(1, 5):
                app.log_scope_channels[ch].set(False)
            app.log_psu_channels[1].set(True)
            app.log_dir.set(tmp)
            app.start_logging()
            app.record_thread.join(5)
            assert app.recording and runs and runs[0]['dir'] == tmp, \
                gui.messagebox.calls
            assert str(app.log_start_btn.cget('state')) == 'disabled'
            assert _enabled(app.log_newdir_btn) == \
                _enabled(app.log_browse_btn) is True
            with _app_dialogs(names=['next run']) as d:
                app.log_newdir_btn.invoke()
            want = of.new_path(tmp, 'next run')
            assert app.log_dir.get() == want and os.path.isdir(want), d.calls
            app.stop_logging()
            assert _enabled(app.log_newdir_btn) == \
                _enabled(app.log_browse_btn) is True
    finally:
        gui.messagebox = saved
        root.destroy()


def test_the_workers_never_read_the_box_themselves():
    """Why a change to the box cannot move a running SLDEA run or log:
    sldea_run hands _sldea_worker the box's folder as an argument, and
    start_logging hands logging_loop cfg['dir']; neither worker reads the
    box. Pinned on the source, because a stand-in worker cannot show what
    the real one reads."""
    import inspect
    try:
        import gui
    except ImportError as e:              # gui.py needs tkinter
        raise _Skip(f"no tkinter: {e}")
    G = gui.InstrumentControlGUI
    for name, box in (('_sldea_worker', 'self.sldea_outdir'),
                      ('_logging_worker', 'self.log_dir'),
                      ('logging_loop', 'self.log_dir')):
        assert box not in inspect.getsource(getattr(G, name)), \
            f"{name} reads {box}"
    # ...and Start is where each one gets the folder from the box
    assert 'self.sldea_outdir.get()' in inspect.getsource(G.sldea_run)
    assert 'self.log_dir.get()' in inspect.getsource(G.start_logging)


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    # A failure message can carry the app's glyphs (the run-lock note's
    # Abort square, a refused micro sign or emoji). Printed to a cp1252
    # pipe they raised UnicodeEncodeError and cut the report off before the
    # traceback (seen 2026-10-07); escape what the stream cannot encode.
    try:
        _sys.stdout.reconfigure(errors='backslashreplace')
    except AttributeError:          # not a TextIOWrapper: leave it be
        pass
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
            # A test that blew up still RAN -- only a skip is "did not run".
            ran += 1
            failed.append((n, traceback.format_exc()))
            print('FAIL', n)
            continue
        ran += 1
        print('ok ', n)
    tail = f"{ran} of {len(names)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped, see above)"
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
