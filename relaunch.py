#!/usr/bin/env python3
"""What Tools → Update Software → Restart now runs, so that the restarted
app is the version the update just deployed.

Update Software deploys to the SHARE (update_software.sh). The bench app
does not run from the share: launch_gui.sh (reference copy:
deploy/launch_gui.sh.reference) keeps a per-user local cache,
${SCPI_CACHE:-$HOME/.cache/scpi_control}, refreshes it from the share only
when the share's version.py stamp differs from the cache's, and runs
gui.py from the cache. Restart used to re-exec its own command line -- the
cached gui.py, with the cached PYTHONPATH -- so it never passed through
the launcher, the cache was never refreshed, and the restarted app was the
version that was already running. Reproduced 2026-09-24 against the
reference launcher (fake share and cache, the real _restart_app body); not
yet checked on the bench.

restart_command() runs a launcher again instead. The launcher is:

1. $SCPI_LAUNCHER, when a launcher exports it and it names a file;
2. when the app runs from the share launcher's cache:
   a. the desktop launcher, /usr/local/bin/scpi-launch.sh -- exactly what
      a click on the icon runs. It is on local disk; it reads a byte of
      the share launcher with a 5 s timeout and runs it when the share is
      up, and otherwise falls back to GitHub, this cache or a dev clone,
      or shows an error -- never a silent nothing;
   b. without it, the share launcher itself, when a byte of it can be
      read. (A stat is not enough: on 2026-07-20 `test -r` succeeded
      against a dead NAS.)
3. otherwise none, and the app re-execs its own command line as before.
   That is right when it runs from the share itself (the launcher's cache
   sync failed, so it ran the share copy). For a developer clone or the
   GitHub fallback's clone it reloads that clone, which the update did
   not change -- the behaviour before this module, kept on purpose.

Only case 2b touches the share (and case 1, if SCPI_LAUNCHER named a file
there), so on a PC with the desktop launcher the Tk thread never waits on
a dead NAS.

Tk-free, so tests/test_relaunch.py runs anywhere, including the run of the
reference launchers end to end.
"""
import os
import shutil

# What the desktop icon runs (install_lab_launchers.sh: WRAPPER=). Local
# disk. Module-level, like the next two, so tests can point it elsewhere.
DESKTOP_LAUNCHER = '/usr/local/bin/scpi-launch.sh'

# The share launcher. update_software.sh deploys beside it, and the
# desktop launcher runs it from here.
SHARE_LAUNCHER = '/mnt/shareDrive/_software/launch_gui.sh'

# A launcher that exports this variable, naming its own path, is the one
# Restart now runs again (see find_launcher).
LAUNCHER_ENV = 'SCPI_LAUNCHER'


def launcher_cache_app(env):
    """The app folder inside launch_gui.sh's cache, found the way the
    launcher finds it: CACHE="${SCPI_CACHE:-$HOME/.cache/scpi_control}",
    RUN_APP="$CACHE/SCPI_Control". An empty SCPI_CACHE counts as unset,
    as it does for bash's `:-`."""
    home = env.get('HOME') or os.path.expanduser('~')
    cache = env.get('SCPI_CACHE') or os.path.join(home, '.cache',
                                                  'scpi_control')
    return os.path.join(cache, 'SCPI_Control')


def _same_dir(a, b):
    def norm(p):
        return os.path.normcase(os.path.realpath(p))
    return norm(a) == norm(b)


def _readable(path):
    """True when a byte of `path` can be read, as the desktop launcher
    probes the share."""
    try:
        with open(path, 'rb') as f:
            f.read(1)
        return True
    except OSError:
        return False


def find_launcher(app_dir, env):
    """The launcher Restart now must run again, or None (module doc).

    `app_dir` is the folder the running gui.py lives in, `env` the app's
    environment."""
    named = env.get(LAUNCHER_ENV, '')
    if os.path.isabs(named) and os.path.isfile(named):
        return named
    if not _same_dir(app_dir, launcher_cache_app(env)):
        return None
    if os.path.isfile(DESKTOP_LAUNCHER):
        return DESKTOP_LAUNCHER
    if _readable(SHARE_LAUNCHER):
        return SHARE_LAUNCHER
    return None


def restart_command(app_dir, env, argv, python, which=shutil.which):
    """(program, argv) for os.execv.

    With a launcher and bash on PATH: `bash <launcher>` plus the app's own
    arguments (launch_gui.sh passes "$@" on to gui.py; the desktop
    launcher passes none, and gui.py takes none). Otherwise the app's own
    command line, `python` + `argv`, as before."""
    launcher = find_launcher(app_dir, env)
    bash = which('bash', path=env.get('PATH')) if launcher else None
    if bash:
        return bash, ['bash', launcher] + list(argv[1:])
    return python, [python] + list(argv)
