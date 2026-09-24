#!/usr/bin/env python3
"""Headless tests for relaunch.py: what Tools → Update Software → Restart
now runs (no hardware, no Tk).

Update Software deploys to the SHARE, but the bench app runs from the
share launcher's per-user local cache, and only the launcher refreshes
that cache. Restart used to re-exec its own command line -- the cached
gui.py -- so it reloaded the version that was already running (reproduced
2026-09-24 against deploy/launch_gui.sh.reference; bench check pending).
What is pinned here:

* running from the share launcher's cache, Restart runs `bash <share
  launcher>` with the app's own arguments;
* the cache is found the way the launcher finds it: SCPI_CACHE, else
  $HOME/.cache/scpi_control, an empty SCPI_CACHE counting as unset;
* a launcher that exports SCPI_LAUNCHER is run again, from anywhere; a
  relative, missing or folder SCPI_LAUNCHER is ignored;
* anywhere else -- a developer clone, the share itself, the GitHub
  fallback's clone -- and with no share launcher or no bash, Restart
  re-execs its own command line exactly as before;
* the guess agrees with the repo's copies of the launch chain
  (launch_gui.sh.reference, update_software.sh.reference,
  install_lab_launchers.sh, gui._find_update_script). The LIVE share
  launcher can drift from its reference copy; that is the bench check;
* end to end, on POSIX with bash and rsync: the REFERENCE launcher runs a
  stand-in app from a fake share into a fake cache, a fake update lands on
  the share, and the restart the stand-in performs through relaunch loads
  the new stamp, code and pylibs. The control -- the old restart, the app's
  own command line -- reloads the old ones, so the case can fail. The only
  real exec in this suite happens there, in a child of the fake launcher,
  never in this process.

Run: .venv/bin/python tests/test_relaunch.py
"""
import contextlib as _contextlib
import os as _os
import posixpath as _posixpath
import re as _re
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


@_contextlib.contextmanager
def _chain():
    """A fake bench under a temp dir: a home whose default launcher cache
    holds the app, a share launcher, a developer clone, the GitHub
    fallback's clone -- and relaunch.SHARE_LAUNCHER pointing at the fake
    launcher for the duration."""
    saved = relaunch.SHARE_LAUNCHER
    with _tempfile.TemporaryDirectory() as tmp:
        c = _types.SimpleNamespace()
        c.home = _os.path.join(tmp, 'home')
        c.cache_app = _os.path.join(c.home, '.cache', 'scpi_control',
                                    'SCPI_Control')
        c.share = _os.path.join(tmp, 'mnt', 'shareDrive', '_software')
        c.share_app = _os.path.join(c.share, 'SCPI_Control')
        c.launcher = _os.path.join(c.share, 'launch_gui.sh')
        c.clone = _os.path.join(c.home, 'projects', 'SCPI_Control')
        c.github = _os.path.join(c.home, '.cache', 'scpi_control_git')
        for d in (c.cache_app, c.share_app, c.clone, c.github):
            _os.makedirs(d)
        _write(c.launcher, '#!/usr/bin/env bash\n')
        c.env = {'HOME': c.home, 'PATH': _os.pathsep.join(['/x', '/y'])}
        relaunch.SHARE_LAUNCHER = c.launcher
        try:
            yield c
        finally:
            relaunch.SHARE_LAUNCHER = saved


def _cmd(app_dir, env, which=_which):
    return relaunch.restart_command(app_dir, env, ARGV, PY, which=which)


# --------------------------------------------------------------------------
# The guess
# --------------------------------------------------------------------------

def test_running_from_the_launcher_cache_reruns_the_share_launcher():
    """The bench's case: the launcher refreshes its cache only when it
    starts, so Restart must start it -- with the app's arguments, and bash
    looked up on the app's own PATH."""
    seen = []

    def which(name, path=None):
        seen.append((name, path))
        return BASH

    with _chain() as c:
        got = _cmd(c.cache_app, c.env, which=which)
        assert got == (BASH, ['bash', c.launcher, '--an-arg']), got
        assert seen == [('bash', c.env['PATH'])], seen


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
        relaunched = (BASH, ['bash', c.launcher, '--an-arg'])
        assert _cmd(custom_app, moved) == relaunched
        assert _cmd(c.cache_app, moved) == UNCHANGED, \
            "the default folder is not the cache when SCPI_CACHE moves it"


def test_a_launcher_that_names_itself_is_run_again():
    """SCPI_LAUNCHER, when it names a file, wins from anywhere -- also over
    the share launcher when running from its cache."""
    with _chain() as c:
        named = _os.path.join(c.home, 'bin', 'scpi-from-github.sh')
        _write(named, '#!/usr/bin/env bash\n')
        env = dict(c.env, SCPI_LAUNCHER=named)
        for app_dir in (c.github, c.clone, c.cache_app):
            got = _cmd(app_dir, env)
            assert got == (BASH, ['bash', named, '--an-arg']), (app_dir, got)


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
                assert got == (BASH, ['bash', c.launcher, '--an-arg']), \
                    (bad, got)
                assert _cmd(c.clone, env) == UNCHANGED, bad
        finally:
            _os.chdir(cwd)


def test_anywhere_else_the_restart_is_unchanged():
    """A developer clone, the share itself (the launcher's sync failed, so
    it ran the share copy -- which the update DID refresh), the GitHub
    fallback's clone, the cache's parent: the app's own command line, as
    before."""
    with _chain() as c:
        for app_dir in (c.clone, c.share_app, c.github,
                        _os.path.dirname(c.cache_app)):
            assert _cmd(app_dir, c.env) == UNCHANGED, app_dir


def test_no_share_launcher_or_no_bash_leaves_the_restart_unchanged():
    """From the cache, but the share launcher is missing (share down), or
    bash is not on PATH: the old restart, never a command that cannot
    start."""
    with _chain() as c:
        assert _cmd(c.cache_app, c.env, which=_no_bash) == UNCHANGED
        _os.remove(c.launcher)
        assert _cmd(c.cache_app, c.env) == UNCHANGED
        named = _os.path.join(c.home, 'launcher.sh')
        _write(named, '#!/usr/bin/env bash\n')
        assert _cmd(c.clone, dict(c.env, SCPI_LAUNCHER=named),
                    which=_no_bash) == UNCHANGED


def test_the_guess_matches_the_repo_copies_of_the_launch_chain():
    """relaunch's share launcher and cache must be the ones the launch
    chain uses. Read from the repo copies; a change there fails here until
    relaunch is checked against it. The LIVE share launcher is checked on
    the bench (it can drift from its reference copy)."""
    def read(*parts):
        with open(_os.path.join(_ROOT, *parts), encoding='utf-8') as f:
            return f.read()

    def one(pattern, text, what):
        found = _re.findall(pattern, text, _re.M)
        assert len(found) == 1, f"{what}: {found}"
        return found[0]

    launch = read('deploy', 'launch_gui.sh.reference')
    one(r'^CACHE="\$\{SCPI_CACHE:-\$HOME/\.cache/scpi_control\}"$', launch,
        'launch_gui.sh cache default')
    one(r'^RUN_APP="\$CACHE/SCPI_Control"$', launch,
        'launch_gui.sh runs the app from the cache')
    one(r'^\s*! rsync -a --delete --exclude presets/ "\$APP/" "\$RUN_APP/"',
        launch, 'launch_gui.sh refreshes the cache from the share app')
    one(r'"\$PY" "\$RUN_APP/gui\.py" "\$@"', launch,
        'launch_gui.sh runs gui.py from RUN_APP with the arguments')

    installer = read('deploy', 'install_lab_launchers.sh')
    share = one(r'^SHARE=(\S+)$', installer, 'the desktop wrapper share')
    one(r'^\s*exec bash "\$SHARE/launch_gui\.sh"$', installer,
        'the desktop wrapper runs the share launcher')
    assert _posixpath.join(share, 'launch_gui.sh') == relaunch.SHARE_LAUNCHER

    update = read('deploy', 'update_software.sh.reference')
    dest = one(r'^DEST="([^"]+)"$', update, 'update_software.sh DEST')
    one(r'^APP="\$DEST/SCPI_Control"$', update, 'the update deploys here')
    assert _posixpath.dirname(relaunch.SHARE_LAUNCHER) == dest, dest

    gui_src = read('gui.py')
    [script] = _re.findall(r"'(/[^']*/update_software\.sh)'", gui_src)
    assert _posixpath.dirname(script) == dest, script


# --------------------------------------------------------------------------
# End to end: the reference launcher, a fake share, a fake update
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
    with open(STATE, 'w') as f:
        f.write('restarted')
    if os.environ.get('T_OLD_RESTART'):
        prog, argv = sys.executable, [sys.executable] + sys.argv
    else:
        relaunch.SHARE_LAUNCHER = os.environ['T_SHARE_LAUNCHER']
        prog, argv = relaunch.restart_command(
            os.path.dirname(os.path.abspath(__file__)), os.environ,
            sys.argv, sys.executable)
    os.execv(prog, argv)
'''


def _stamp(path):
    with open(path, encoding='utf-8') as f:
        return _re.search(r'^__version__ = "([^"]*)"', f.read(), _re.M)[1]


def _through_the_reference_launcher(old_restart):
    """Run deploy/launch_gui.sh.reference, unmodified, on a fake share
    and a fake home -> (report lines, share stamp, cache stamp)."""
    if _os.name != 'posix':
        raise _Skip("POSIX only: the launcher is bash, rsync'ing a cache")
    for tool in ('bash', 'rsync'):
        if not _shutil.which(tool):
            raise _Skip(f"needs {tool} on PATH")
    with _tempfile.TemporaryDirectory() as tmp:
        share = _os.path.join(tmp, 'mnt', 'shareDrive', '_software')
        share_app = _os.path.join(share, 'SCPI_Control')
        share_libs = _os.path.join(share, 'pylibs')
        launcher = _os.path.join(share, 'launch_gui.sh')
        home = _os.path.join(tmp, 'home')
        _os.makedirs(home)

        def release(name, version, code, lib):
            where = _os.path.join(tmp, name)
            app = _os.path.join(where, 'app')
            _os.makedirs(app)
            _shutil.copy(_os.path.join(_ROOT, 'relaunch.py'), app)
            with open(_os.path.join(_ROOT, 'version.py'),
                      encoding='utf-8') as f:
                text = f.read()
            _write(_os.path.join(app, 'version.py'),
                   _re.sub(r'^__version__ = "[^"]*"',
                           f'__version__ = "{version}"', text, count=1,
                           flags=_re.M))
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
        # With LF endings, as on the share: a Windows checkout (autocrlf)
        # has CRLF, which bash rejects ("set: pipefail\r").
        with open(_os.path.join(_ROOT, 'deploy', 'launch_gui.sh.reference'),
                  encoding='utf-8') as f:
            _write(launcher, f.read())
        vpath = _os.path.join(share_app, 'version.py')
        with open(vpath, encoding='utf-8') as f:
            text = f.read()
        _write(vpath, text.replace('__version__ = "1.0.0"',
                                   '__version__ = "1.0.0+aaaaaaa"', 1))
        hour_ago = _time.time() - 3600
        for base, _dirs, files in _os.walk(share):
            for name in files:
                _os.utime(_os.path.join(base, name), (hour_ago, hour_ago))

        env = {k: v for k, v in _os.environ.items()
               if k not in ('SCPI_CACHE', 'SCPI_LAUNCHER', 'PYTHONPATH',
                            'DISPLAY', 'WAYLAND_DISPLAY')}
        report = _os.path.join(tmp, 'report.txt')
        env.update(HOME=home, SCPI_PYTHON=_sys.executable,
                   PYTHONDONTWRITEBYTECODE='1',
                   T_STATE=_os.path.join(tmp, 'state'), T_REPORT=report,
                   T_NEW_RELEASE=new, T_SHARE_APP=share_app,
                   T_SHARE_LIBS=share_libs, T_SHARE_LAUNCHER=launcher)
        if old_restart:
            env['T_OLD_RESTART'] = '1'
        proc = _subprocess.run(['bash', launcher], env=env,
                               capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, (proc.returncode, proc.stdout,
                                      proc.stderr)
        with open(report, encoding='utf-8') as f:
            lines = [ln.split() for ln in f.read().splitlines()]
        cache_app = _os.path.join(home, '.cache', 'scpi_control',
                                  'SCPI_Control')
        return (lines, _stamp(vpath),
                _stamp(_os.path.join(cache_app, 'version.py')), proc)


def test_restart_through_the_reference_launcher_loads_the_new_version():
    lines, share, cache, proc = _through_the_reference_launcher(
        old_restart=False)
    assert [ln[0] for ln in lines] == ['first', 'restarted'], (lines, proc)
    (_, pid1, footer1, code1, lib1), (_, pid2, footer2, code2, lib2) = lines
    assert (footer1, code1, lib1) == ('v1.0.0+aaaaaaa', 'OLD', 'old'), lines
    assert (footer2, code2, lib2) == ('v1.0.1+bbbbbbb', 'NEW', 'new'), lines
    assert pid2 != pid1, "the new app is the re-run launcher's child"
    assert share == cache == '1.0.1+bbbbbbb', (share, cache)


def test_the_old_restart_reloaded_the_cached_version():
    """The control: the old restart -- the app's own command line --
    comes back as the same process running the old stamp, code and
    pylibs, while the share holds the new ones. If this ever stops
    failing that way, the case above no longer proves anything."""
    lines, share, cache, proc = _through_the_reference_launcher(
        old_restart=True)
    assert [ln[0] for ln in lines] == ['first', 'restarted'], (lines, proc)
    (_, pid1, *first), (_, pid2, *again) = lines
    assert first == again == ['v1.0.0+aaaaaaa', 'OLD', 'old'], lines
    assert pid2 == pid1, "os.execv keeps the pid"
    assert (share, cache) == ('1.0.1+bbbbbbb', '1.0.0+aaaaaaa'), (share,
                                                                 cache)


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
        tail += f" ({skipped} skipped, POSIX with bash and rsync only)"
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
