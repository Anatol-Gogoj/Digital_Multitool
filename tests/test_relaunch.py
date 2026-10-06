#!/usr/bin/env python3
"""Headless tests for relaunch.py: what Tools → Update Software → Restart
now runs (no hardware, no Tk).

Update Software deploys to the SHARE, but the bench app runs from the
share launcher's per-user local cache, and only the launcher refreshes
that cache. Restart used to re-exec its own command line -- the cached
gui.py -- so it reloaded the version that was already running (reproduced
2026-09-24 against deploy/launch_gui.sh.reference; bench check pending).
What is pinned here:

* running from the share launcher's cache, Restart runs `bash <desktop
  launcher>` -- what a click on the icon runs -- with the app's own
  arguments, and without the desktop launcher `bash <share launcher>`, if
  a byte of it can be read;
* the cache is found the way the launcher finds it: SCPI_CACHE, else
  $HOME/.cache/scpi_control, an empty SCPI_CACHE counting as unset; a
  folder beside it, inside it or above it is not it; a symlinked home
  still finds it;
* a launcher that exports SCPI_LAUNCHER is run again, from anywhere; a
  relative, missing or folder SCPI_LAUNCHER is ignored;
* anywhere else -- a developer clone, the share itself, the GitHub
  fallback's clone -- and with no launcher to run or no bash, Restart
  re-execs its own command line exactly as before;
* the guess agrees with the repo's copies of the launch chain
  (launch_gui.sh.reference, update_software.sh.reference,
  install_lab_launchers.sh, gui._find_update_script). The LIVE launchers
  can drift from these copies; that is the bench check;
* end to end, on POSIX with bash, rsync and timeout: the REFERENCE
  launchers -- the share launcher, and the desktop launcher taken from the
  installer -- start a stand-in app from a fake share into a fake cache, a
  fake update lands on the share, and the restart the stand-in performs
  through relaunch loads the new stamp, code and pylibs, with no error
  dialog. With the share gone by the time Restart is pressed, the desktop
  launcher says so and runs the cached copy -- never a silent nothing.
  The control -- the old restart, the app's own command line --
  reloads the old ones, so the case can fail. notify-send and zenity are
  stubbed: run on the bench, nothing pops up on the desktop. The only real
  exec in this suite happens there, in a child of the fake launcher, never
  in this process.

Run: .venv/bin/python tests/test_relaunch.py
"""
import contextlib as _contextlib
import os as _os
import posixpath as _posixpath
import re as _re
import shlex as _shlex
import shutil as _shutil
import subprocess as _subprocess
import sys as _sys
import tempfile as _tempfile
import time as _time
import types as _types
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _ROOT)

import relaunch  # noqa: E402

PY = '/usr/bin/python3.11'           # stands in for the app's sys.executable
BASH = '/usr/bin/bash'               # what the fake `which` finds
# The app's command line: launch_gui.sh runs "$RUN_APP/gui.py" "$@".
ARGV = ['/home/lab/.cache/scpi_control/SCPI_Control/gui.py', '--an-arg']
UNCHANGED = (PY, [PY] + ARGV)


class _Skip(Exception):
    """Raised by a case that cannot run here. Counted, never silent."""


def _which(name, path=None):
    assert name == 'bash', name
    return BASH


def _no_bash(name, path=None):
    return None


def _write(path, text):
    _os.makedirs(_os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def _read(*parts):
    with open(_os.path.join(_ROOT, *parts), encoding='utf-8') as f:
        return f.read()


@_contextlib.contextmanager
def _chain(desktop=True):
    """A fake bench under a temp dir: a home whose default launcher cache
    holds the app, a share launcher, a developer clone, the GitHub
    fallback's clone and -- with `desktop` -- the desktop launcher.
    relaunch's two launcher paths point at the fakes for the duration."""
    saved = relaunch.DESKTOP_LAUNCHER, relaunch.SHARE_LAUNCHER
    with _tempfile.TemporaryDirectory() as tmp:
        c = _types.SimpleNamespace()
        c.home = _os.path.join(tmp, 'home')
        c.cache = _os.path.join(c.home, '.cache', 'scpi_control')
        c.cache_app = _os.path.join(c.cache, 'SCPI_Control')
        c.share = _os.path.join(tmp, 'mnt', 'shareDrive', '_software')
        c.share_app = _os.path.join(c.share, 'SCPI_Control')
        c.launcher = _os.path.join(c.share, 'launch_gui.sh')
        c.desktop = _os.path.join(tmp, 'usr', 'local', 'bin',
                                  'scpi-launch.sh')
        c.clone = _os.path.join(c.home, 'projects', 'SCPI_Control')
        c.github = _os.path.join(c.home, '.cache', 'scpi_control_git')
        for d in (c.cache_app, _os.path.join(c.cache, 'pylibs'),
                  _os.path.join(c.cache_app, 'tests'), c.share_app,
                  c.clone, c.github):
            _os.makedirs(d)
        _write(c.launcher, '#!/usr/bin/env bash\n')
        if desktop:
            _write(c.desktop, '#!/bin/bash\n')
        c.env = {'HOME': c.home, 'PATH': _os.pathsep.join(['/x', '/y'])}
        relaunch.DESKTOP_LAUNCHER, relaunch.SHARE_LAUNCHER = (c.desktop,
                                                              c.launcher)
        try:
            yield c
        finally:
            relaunch.DESKTOP_LAUNCHER, relaunch.SHARE_LAUNCHER = saved


def _cmd(app_dir, env, which=_which):
    return relaunch.restart_command(app_dir, env, ARGV, PY, which=which)


def _runs(launcher):
    return (BASH, ['bash', launcher, '--an-arg'])


# --------------------------------------------------------------------------
# The guess
# --------------------------------------------------------------------------

def test_running_from_the_launcher_cache_runs_the_desktop_launcher():
    """The bench's case: the launcher refreshes its cache only when it
    starts, so Restart must start the chain again -- as the icon does, with
    the app's arguments, and bash looked up on the app's own PATH."""
    seen = []

    def which(name, path=None):
        seen.append((name, path))
        return BASH

    with _chain() as c:
        got = _cmd(c.cache_app, c.env, which=which)
        assert got == _runs(c.desktop), got
        assert seen == [('bash', c.env['PATH'])], seen


def test_the_desktop_launcher_does_not_need_the_share():
    """It is what copes with a dead share (a timed read, then GitHub, the
    cache, an error), so a missing or unreadable share launcher does not
    stop it being run."""
    with _chain() as c:
        _os.remove(c.launcher)
        assert _cmd(c.cache_app, c.env) == _runs(c.desktop)
        _os.makedirs(c.launcher)           # there, but no byte to read
        assert _cmd(c.cache_app, c.env) == _runs(c.desktop)


def test_without_the_desktop_launcher_a_readable_share_launcher_is_run():
    """A PC the lab installer never ran on: the share launcher itself --
    but only when a byte of it can be read. A folder in its place (open
    fails, as a dead NAS's read does, even though a stat succeeds) or no
    file leaves the restart as before."""
    with _chain(desktop=False) as c:
        assert _cmd(c.cache_app, c.env) == _runs(c.launcher)
        _os.remove(c.launcher)
        assert _cmd(c.cache_app, c.env) == UNCHANGED
        _os.makedirs(c.launcher)
        assert _os.path.exists(c.launcher)
        assert _cmd(c.cache_app, c.env) == UNCHANGED


def test_a_share_launcher_that_stats_but_cannot_be_read_is_not_run():
    """The 2026-07-20 dead NAS: `test -r` said yes, the read said "Host is
    down". A file whose stat succeeds but whose read fails (mode 000 here)
    must not be run -- the old restart at least brings an app back."""
    if _os.name != 'posix':
        raise _Skip("POSIX only: needs a file that stats but cannot be read")
    if _os.geteuid() == 0:
        raise _Skip("root reads a mode-000 file")
    with _chain(desktop=False) as c:
        _os.chmod(c.launcher, 0)
        try:
            assert _os.path.isfile(c.launcher)
            assert _cmd(c.cache_app, c.env) == UNCHANGED
        finally:
            _os.chmod(c.launcher, 0o644)


def test_the_cache_is_found_the_way_the_launcher_finds_it():
    """CACHE="${SCPI_CACHE:-$HOME/.cache/scpi_control}": SCPI_CACHE wins,
    an empty one counts as unset, and when SCPI_CACHE points elsewhere the
    default folder is NOT the launcher's cache any more."""
    with _chain() as c:
        custom = _os.path.join(c.home, 'elsewhere')
        custom_app = _os.path.join(custom, 'SCPI_Control')
        _os.makedirs(custom_app)
        default = relaunch.launcher_cache_app(c.env)
        assert default == c.cache_app, (default, c.cache_app)
        assert relaunch.launcher_cache_app(
            dict(c.env, SCPI_CACHE='')) == c.cache_app
        assert relaunch.launcher_cache_app(
            dict(c.env, SCPI_CACHE=custom)) == custom_app
        moved = dict(c.env, SCPI_CACHE=custom)
        assert _cmd(custom_app, moved) == _runs(c.desktop)
        assert _cmd(c.cache_app, moved) == UNCHANGED, \
            "the default folder is not the cache when SCPI_CACHE moves it"


def test_a_folder_beside_inside_or_above_the_cache_is_not_it():
    """Only the cache's own app folder counts: not its pylibs beside it,
    not a folder inside it, not the cache above it."""
    with _chain() as c:
        for app_dir in (_os.path.join(c.cache, 'pylibs'),
                        _os.path.join(c.cache_app, 'tests'), c.cache):
            assert _cmd(app_dir, c.env) == UNCHANGED, app_dir


def test_a_symlinked_home_still_finds_the_cache():
    """The launcher builds the cache path from $HOME as it is; the app may
    see the same folder through a symlink. Same folder, same cache."""
    with _chain() as c:
        link = _os.path.join(_os.path.dirname(c.home), 'home-link')
        try:
            _os.symlink(c.home, link, target_is_directory=True)
        except (OSError, NotImplementedError) as e:
            raise _Skip(f"cannot make a symlink here: {e}")
        linked = dict(c.env, HOME=link)
        assert _cmd(c.cache_app, linked) == _runs(c.desktop)
        via_link = _os.path.join(link, '.cache', 'scpi_control',
                                 'SCPI_Control')
        assert _cmd(via_link, c.env) == _runs(c.desktop)


def test_a_launcher_that_names_itself_is_run_again():
    """SCPI_LAUNCHER, when it names a file, wins from anywhere -- also over
    the desktop and share launchers when running from the cache."""
    with _chain() as c:
        named = _os.path.join(c.home, 'bin', 'scpi-from-github.sh')
        _write(named, '#!/usr/bin/env bash\n')
        env = dict(c.env, SCPI_LAUNCHER=named)
        for app_dir in (c.github, c.clone, c.cache_app):
            assert _cmd(app_dir, env) == _runs(named), app_dir


def test_a_named_launcher_that_is_not_a_file_is_ignored():
    """A relative path -- even one that names a file in the working
    directory -- a missing file or a folder in SCPI_LAUNCHER is ignored:
    the guess and the old restart carry on as if it were unset."""
    with _chain() as c:
        cwd = _os.getcwd()
        _os.chdir(c.share)             # 'launch_gui.sh' is a file here
        try:
            for bad in ('launch_gui.sh', _os.path.join(c.home, 'gone.sh'),
                        c.home, ''):
                env = dict(c.env, SCPI_LAUNCHER=bad)
                got = _cmd(c.cache_app, env)
                assert got == _runs(c.desktop), (bad, got)
                assert _cmd(c.clone, env) == UNCHANGED, bad
        finally:
            _os.chdir(cwd)


def test_anywhere_else_the_restart_is_unchanged():
    """A developer clone, the share itself (the launcher's sync failed, so
    it ran the share copy -- which the update DID refresh), the GitHub
    fallback's clone: the app's own command line, as before, with both
    launchers present."""
    with _chain() as c:
        for app_dir in (c.clone, c.share_app, c.github):
            assert _cmd(app_dir, c.env) == UNCHANGED, app_dir


def test_no_bash_leaves_the_restart_unchanged():
    """A launcher to run, but no bash on PATH: the old restart, never a
    command that cannot start."""
    with _chain() as c:
        assert _cmd(c.cache_app, c.env, which=_no_bash) == UNCHANGED
        named = _os.path.join(c.home, 'launcher.sh')
        _write(named, '#!/usr/bin/env bash\n')
        assert _cmd(c.clone, dict(c.env, SCPI_LAUNCHER=named),
                    which=_no_bash) == UNCHANGED


def test_the_guess_matches_the_repo_copies_of_the_launch_chain():
    """relaunch's launchers and cache must be the ones the launch chain
    uses. Read from the repo copies; a change there fails here until
    relaunch is checked against it. The LIVE launchers are checked on the
    bench (they can drift from these copies)."""
    def one(pattern, text, what):
        found = _re.findall(pattern, text, _re.M)
        assert len(found) == 1, f"{what}: {found}"
        return found[0]

    cache_line = r'^CACHE="\$\{SCPI_CACHE:-\$HOME/\.cache/scpi_control\}"$'
    launch = _read('deploy', 'launch_gui.sh.reference')
    one(cache_line, launch, 'launch_gui.sh cache default')
    one(r'^RUN_APP="\$CACHE/SCPI_Control"$', launch,
        'launch_gui.sh runs the app from the cache')
    one(r'^\s*! rsync -a --delete --exclude presets/ "\$APP/" "\$RUN_APP/"',
        launch, 'launch_gui.sh refreshes the cache from the share app')
    one(r'"\$PY" "\$RUN_APP/gui\.py" "\$@"', launch,
        'launch_gui.sh runs gui.py from RUN_APP with the arguments')

    installer = _read('deploy', 'install_lab_launchers.sh')
    wrapper = one(r'^WRAPPER=(\S+)$', installer, 'the desktop launcher')
    assert wrapper == relaunch.DESKTOP_LAUNCHER, wrapper
    assert one(r'^Exec=bash (\S+)$', installer,
               'what the icon runs') == wrapper
    desktop = _desktop_launcher_source()
    one(cache_line, desktop, "the desktop launcher's cache")
    share = one(r'^SHARE=(\S+)$', desktop, 'the desktop launcher share')
    one(r'^\s*exec bash "\$SHARE/launch_gui\.sh"$', desktop,
        'the desktop launcher runs the share launcher')
    assert _posixpath.join(share, 'launch_gui.sh') == relaunch.SHARE_LAUNCHER

    update = _read('deploy', 'update_software.sh.reference')
    dest = one(r'^DEST="([^"]+)"$', update, 'update_software.sh DEST')
    one(r'^APP="\$DEST/SCPI_Control"$', update, 'the update deploys here')
    assert _posixpath.dirname(relaunch.SHARE_LAUNCHER) == dest, dest

    [script] = _re.findall(r"'(/[^']*/update_software\.sh)'", _read('gui.py'))
    assert _posixpath.dirname(script) == dest, script


def _desktop_launcher_source():
    """The desktop launcher as install_lab_launchers.sh writes it."""
    found = _re.findall(r"^cat > \"\$WRAPPER\" <<'WRAP'\n(.*?)^WRAP$",
                        _read('deploy', 'install_lab_launchers.sh'),
                        _re.M | _re.S)
    assert len(found) == 1, found
    return found[0]


# --------------------------------------------------------------------------
# End to end: the reference launchers, a fake share, a fake update
# --------------------------------------------------------------------------

# Runs as gui.py in the fake cache. Reports its state, footer, code and
# pylibs; on its first run it plays Update Software (the new release onto
# the SHARE, version.py stamped last, as update_software.sh does) and then
# Restart now -- through relaunch, or with T_OLD_RESTART the old way.
_STANDIN = '''\
import os
import re
import shutil
import sys

import fakelib
import relaunch
from version import version_string

CODE = '@CODE@'
STATE = os.environ['T_STATE']


def report(state):
    with open(os.environ['T_REPORT'], 'a') as f:
        f.write(f"{state} {os.getpid()} {version_string()} {CODE} "
                f"{fakelib.VERSION}\\n")


def update_the_share():
    new = os.environ['T_NEW_RELEASE']
    shutil.copytree(os.path.join(new, 'app'), os.environ['T_SHARE_APP'],
                    dirs_exist_ok=True)
    shutil.copytree(os.path.join(new, 'pylibs'), os.environ['T_SHARE_LIBS'],
                    dirs_exist_ok=True)
    path = os.path.join(os.environ['T_SHARE_APP'], 'version.py')
    with open(path) as f:
        text = f.read()
    with open(path, 'w') as f:
        f.write(re.sub(r'^(__version__ = ")([^"]*)(")', r'\\g<1>\\g<2>+bbbbbbb\\g<3>',
                       text, count=1, flags=re.M))


state = 'first'
if os.path.exists(STATE):
    with open(STATE) as f:
        state = f.read()
report(state)
if state == 'first':
    update_the_share()
    if os.environ.get('T_KILL_SHARE'):
        # the share dies after the update: no byte of the launcher reads
        os.remove(os.environ['T_SHARE_LAUNCHER'])
        os.mkdir(os.environ['T_SHARE_LAUNCHER'])
    with open(STATE, 'w') as f:
        f.write('restarted')
    if os.environ.get('T_OLD_RESTART'):
        prog, argv = sys.executable, [sys.executable] + sys.argv
    else:
        relaunch.DESKTOP_LAUNCHER = os.environ['T_DESKTOP_LAUNCHER']
        relaunch.SHARE_LAUNCHER = os.environ['T_SHARE_LAUNCHER']
        prog, argv = relaunch.restart_command(
            os.path.dirname(os.path.abspath(__file__)), os.environ,
            sys.argv, sys.executable)
    os.execv(prog, argv)
'''

# notify-send and zenity for the fake launchers: they only log the call.
_STUB = '#!/bin/sh\necho "$(basename "$0") $*" >> "$T_POPUPS"\n'


def _stamp(path):
    with open(path, encoding='utf-8') as f:
        return _re.search(r'^__version__ = "([^"]*)"', f.read(), _re.M)[1]


def _through_the_reference_launchers(mode):
    """One Update + Restart now on a fake bench, driven by the reference
    launchers (with LF endings, as on the share and in /usr/local/bin: a
    Windows checkout's CRLF would stop bash at `set -o pipefail`).

    mode 'desktop': started by the desktop launcher, which relaunch finds;
         'share':   no desktop launcher; started by the share launcher;
         'old':     started by the desktop launcher, restarted the old way;
         'share-gone': as 'desktop', but the share launcher cannot be read
                    any more when Restart is pressed.
    The desktop launcher is the installer's, pointed at the fake share, at
    this interpreter instead of /usr/bin/python3.11, and at no GitHub
    launcher -- run on the bench, a dead-share path must not start the
    real app from GitHub.
    -> (report lines, share stamp, cache stamp, popups, the process)."""
    if _os.name != 'posix':
        raise _Skip("POSIX only: the launchers are bash, rsync'ing a cache")
    for tool in ('bash', 'rsync', 'timeout'):
        if not _shutil.which(tool):
            raise _Skip(f"needs {tool} on PATH")
    with _tempfile.TemporaryDirectory() as tmp:
        share = _os.path.join(tmp, 'mnt', 'shareDrive', '_software')
        share_app = _os.path.join(share, 'SCPI_Control')
        share_libs = _os.path.join(share, 'pylibs')
        launcher = _os.path.join(share, 'launch_gui.sh')
        desktop = _os.path.join(tmp, 'usr', 'local', 'bin', 'scpi-launch.sh')
        home = _os.path.join(tmp, 'home')
        stubs = _os.path.join(tmp, 'stubs')
        _os.makedirs(home)
        for name in ('notify-send', 'zenity'):
            _write(_os.path.join(stubs, name), _STUB)
            _os.chmod(_os.path.join(stubs, name), 0o755)

        def release(name, version, code, lib):
            where = _os.path.join(tmp, name)
            app = _os.path.join(where, 'app')
            _os.makedirs(app)
            _shutil.copy(_os.path.join(_ROOT, 'relaunch.py'), app)
            _write(_os.path.join(app, 'version.py'),
                   _re.sub(r'^__version__ = "[^"]*"',
                           f'__version__ = "{version}"', _read('version.py'),
                           count=1, flags=_re.M))
            _write(_os.path.join(app, 'gui.py'),
                   _STANDIN.replace('@CODE@', code))
            _write(_os.path.join(where, 'pylibs', 'fakelib.py'),
                   f"VERSION = {lib!r}\n")
            return where

        old = release('release_old', '1.0.0', 'OLD', 'old')
        new = release('release_new', '1.0.1', 'NEW', 'new')
        # What the PC runs now: the old release, deployed an hour ago and
        # stamped. (An hour: equal-size files written in the same second
        # would look unchanged to rsync's quick check. Real deploys are
        # never a second apart.)
        _shutil.copytree(_os.path.join(old, 'app'), share_app)
        _shutil.copytree(_os.path.join(old, 'pylibs'), share_libs)
        _write(launcher, _read('deploy', 'launch_gui.sh.reference'))
        vpath = _os.path.join(share_app, 'version.py')
        with open(vpath, encoding='utf-8') as f:
            text = f.read()
        _write(vpath, text.replace('__version__ = "1.0.0"',
                                   '__version__ = "1.0.0+aaaaaaa"', 1))
        hour_ago = _time.time() - 3600
        for base, _dirs, files in _os.walk(share):
            for name in files:
                _os.utime(_os.path.join(base, name), (hour_ago, hour_ago))
        if mode != 'share':
            src = _desktop_launcher_source()
            for was, now in (
                    ('\nSHARE=/mnt/shareDrive/_software\n', f'\nSHARE={share}\n'),
                    ('\nGHSCRIPT=/usr/local/bin/scpi-from-github.sh\n',
                     f"\nGHSCRIPT={_os.path.join(tmp, 'no-github-launcher')}\n"),
                    (' /usr/bin/python3.11 ', f' {_shlex.quote(_sys.executable)} ')):
                assert src.count(was) == 1, was
                src = src.replace(was, now)
            _write(desktop, src)

        env = {k: v for k, v in _os.environ.items()
               if k not in ('SCPI_CACHE', 'SCPI_LAUNCHER', 'PYTHONPATH',
                            'DISPLAY', 'WAYLAND_DISPLAY',
                            'DBUS_SESSION_BUS_ADDRESS')}
        report = _os.path.join(tmp, 'report.txt')
        popups = _os.path.join(tmp, 'popups.txt')
        env.update(HOME=home, SCPI_PYTHON=_sys.executable,
                   PYTHONDONTWRITEBYTECODE='1',
                   PATH=_os.pathsep.join([stubs, env.get('PATH', '')]),
                   T_POPUPS=popups, T_STATE=_os.path.join(tmp, 'state'),
                   T_REPORT=report, T_NEW_RELEASE=new, T_SHARE_APP=share_app,
                   T_SHARE_LIBS=share_libs, T_SHARE_LAUNCHER=launcher,
                   T_DESKTOP_LAUNCHER=desktop)
        if mode == 'old':
            env['T_OLD_RESTART'] = '1'
        if mode == 'share-gone':
            env['T_KILL_SHARE'] = '1'
        first = launcher if mode == 'share' else desktop
        proc = _subprocess.run(['bash', first], env=env,
                               capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, (proc.returncode, proc.stdout,
                                      proc.stderr)
        with open(report, encoding='utf-8') as f:
            lines = [ln.split() for ln in f.read().splitlines()]
        seen = []
        if _os.path.exists(popups):
            with open(popups, encoding='utf-8') as f:
                seen = f.read().splitlines()
        cache_app = _os.path.join(home, '.cache', 'scpi_control',
                                  'SCPI_Control')
        return (lines, _stamp(vpath),
                _stamp(_os.path.join(cache_app, 'version.py')), seen, proc)


def _loads_the_new_version(mode):
    lines, share, cache, popups, proc = _through_the_reference_launchers(mode)
    assert [ln[0] for ln in lines] == ['first', 'restarted'], (lines, proc)
    (_, pid1, footer1, code1, lib1), (_, pid2, footer2, code2, lib2) = lines
    assert (footer1, code1, lib1) == ('v1.0.0+aaaaaaa', 'OLD', 'old'), lines
    assert (footer2, code2, lib2) == ('v1.0.1+bbbbbbb', 'NEW', 'new'), lines
    assert pid2 != pid1, "the new app is the re-run launcher's child"
    assert share == cache == '1.0.1+bbbbbbb', (share, cache)
    assert not [p for p in popups if p.startswith('zenity')], popups


def test_restart_through_the_desktop_launcher_loads_the_new_version():
    """The bench: started from the icon's launcher, restarted through it."""
    _loads_the_new_version('desktop')


def test_restart_through_the_share_launcher_loads_the_new_version():
    """A PC without the desktop launcher: the share launcher directly."""
    _loads_the_new_version('share')


def test_restart_with_the_share_gone_says_so_and_runs_the_cached_copy():
    """The share dies between the update and Restart now (adversarial
    review, 2026-09-24). Run straight, the share launcher would fail with
    no app to come back to; through the desktop launcher the app comes
    back -- the cached, old version -- with the desktop launcher's note
    on the screen. Never a silent nothing."""
    lines, share, cache, popups, proc = _through_the_reference_launchers(
        'share-gone')
    assert [ln[0] for ln in lines] == ['first', 'restarted'], (lines, proc)
    (_, _, *first), (_, _, *again) = lines
    assert first == again == ['v1.0.0+aaaaaaa', 'OLD', 'old'], lines
    assert (share, cache) == ('1.0.1+bbbbbbb', '1.0.0+aaaaaaa'), (share,
                                                                 cache)
    assert [p for p in popups if p.startswith('notify-send')
            and 'Shared drive unreachable' in p], popups
    assert not [p for p in popups if p.startswith('zenity')], popups


def test_the_old_restart_reloaded_the_cached_version():
    """The control: the old restart -- the app's own command line --
    comes back as the same process running the old stamp, code and
    pylibs, while the share holds the new ones. If this ever stops
    failing that way, the cases above no longer prove anything."""
    lines, share, cache, popups, proc = _through_the_reference_launchers(
        'old')
    assert [ln[0] for ln in lines] == ['first', 'restarted'], (lines, proc)
    (_, pid1, *first), (_, pid2, *again) = lines
    assert first == again == ['v1.0.0+aaaaaaa', 'OLD', 'old'], lines
    assert pid2 == pid1, "os.execv keeps the pid"
    assert (share, cache) == ('1.0.1+bbbbbbb', '1.0.0+aaaaaaa'), (share,
                                                                 cache)
    assert not [p for p in popups if p.startswith('zenity')], popups


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    ran = skipped = 0
    failed = []
    for fn in fns:
        try:
            fn()
        except _Skip as why:
            skipped += 1
            print(f"skip {fn.__name__}  ({why})")
            continue
        except Exception:
            # A test that blew up still RAN -- only a skip is "did not run".
            ran += 1
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
        ran += 1
        print(f"ok  {fn.__name__}")
    tail = f"{ran} of {len(fns)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped: POSIX-only cases, reasons above)"
    print(f"\n{tail}")
    if not failed:
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
