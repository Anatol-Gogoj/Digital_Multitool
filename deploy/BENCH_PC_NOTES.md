# Bench PC operational notes (RHEL 9 box `hc18kx2`)

Notes for whoever maintains the lab machine. Application code is documented
in the top-level README; this file covers the **desktop/OS side**: how the
app gets launched, why start-up takes as long as it does, and the shared
kiosk-account behaviour.

## Launch chain

Desktop icon / app-grid entry → `/usr/local/bin/scpi-launch.sh` (installed by
`~/install_lab_launchers.sh`) which tries, in order:

1. **The share** — `/mnt/shareDrive/_software/launch_gui.sh`. Probed by
   *reading a byte* (`head -c 1`), not `test -r`: on 2026-07-20 `test -r`
   succeeded against a dead NAS and the launch then died with "Host is down"
   without ever reaching a fallback.
2. **GitHub** — if the share is down but the internet is up, pull the latest
   code and run it locally (`/usr/local/bin/scpi-from-github.sh`; canonical
   copy `deploy/scpi_from_github.sh`). Gated on a quick `git ls-remote` so a
   full internet outage falls through fast. This is the share-outage backup:
   GitHub is over the internet, not the LAN share host, so it works when the
   Win11 share box is down. Clones to `~/.cache/scpi_control_git` (local
   disk — git corrupts packfiles on CIFS), reuses the existing
   `~/.cache/scpi_control/pylibs` for deps (or builds a local venv if there
   is none), and runs with cwd on the local presets root so presets persist.
   Anyone can run it by hand any time: `bash ~/scpi_from_github.sh`.
3. **This user's local cache** — `~/.cache/scpi_control`, kept up to date by
   the share launcher (can be stale — hence GitHub is tried first). Run with
   the working directory at `~/.local/share/scpi_control`, so `presets/`
   resolves to the same folder the app itself falls back to (see
   `presets_path.py`) and work done during an outage is not lost.
4. **A developer clone** at `~/projects/SCPI_Control`, if one exists.
5. Otherwise a visible zenity/notify error — never a silent nothing.

`launch_gui.sh` itself (share-only file; reference copy: `launch_gui.sh.reference`)
mirrors the app to the local cache **only when `version.py`'s stamp changed**,
then runs Python from local disk while keeping the working directory on the
share so presets stay shared between users.

**Restart now goes back through the launcher (2026-09-24).** `Tools → Update
Software…` deploys to the share, not to anyone's cache, and only `launch_gui.sh`
refreshes the cache. Restart now used to re-exec the app's own command line,
which is the *cached* `gui.py` with the cached `PYTHONPATH`, so it came back as
the version that was already running. This was reproduced against the reference
copy on 2026-09-24. The bench check is pending: see `PROJECT_HANDOFF.md`.

Now, when the app runs from `${SCPI_CACHE:-$HOME/.cache/scpi_control}/SCPI_Control`,
Restart runs what a click on the icon runs, `bash /usr/local/bin/scpi-launch.sh`
(`relaunch.py`). It is on local disk and probes the share with a timed read. On a
working share it runs `launch_gui.sh`, which re-syncs the cache (about 25 s, under
the launcher's update window) and starts the new version. On a dead share it falls
back as the icon does and says so. A PC without that desktop launcher runs
`bash /mnt/shareDrive/_software/launch_gui.sh` directly, but only if a byte of it
can be read. The Tk thread never touches the share when the desktop launcher is
there.

This also covers the desktop launcher's own share-down session (step 3 above:
the cache run with `~/.local/share/scpi_control` as the working directory). The
update in that session needed the share, so the restart finds the share up again
and goes back to the normal path, with presets shared again. If the share has
died again, the fallbacks show a note and bring back the cached copy.

A launcher can name itself for Restart by exporting `SCPI_LAUNCHER=<its own
path>`. None does yet. The GitHub fallback could do it in the installer's
heredoc.

Everywhere else, Restart re-execs as before:
- a dev clone;
- the GitHub fallback's `~/.cache/scpi_control_git`;
- the share copy, when the launcher's sync failed.

For the two clones, that reloads code the update did not touch, so start the app
again from the icon instead.

What to know about the restart:
- **The app is gone for about half a minute after an update** (before, about
  3 s). Outputs stay as they are, as the owner decided for Restart. If the new
  version then fails to start, the app does not come back until someone starts
  it. Switch outputs off first if they must not be left unattended.
- **Close Edge Review, the tuner and plot windows before restarting.** They run
  from the cache, which the re-sync rewrites under them (`rsync --delete`), so a
  later lazy import could load files from the other version. Any start from the
  icon after a deploy does the same.
- **The new launcher runs inside the old one**, which is still waiting on the
  same process, and each restart adds one more level. If the restarted app then
  exits with an error, the "failed to start" dialog appears once per level:
  twice after one restart. `launch.log.prev` holds the session before the
  restart, followed by a copy of the restarted one. `PYTHONPATH` repeats the
  cache pylibs once per level, which is harmless.
- **The re-sync has no lock.** A second click on the icon during it starts a
  second copy, as it always could after a deploy.

`tests/test_relaunch.py` pins the desktop launcher, the cache path and the share
path against the repo copies of the launch chain. On POSIX it also runs the
reference launchers end to end, including a share that dies between the update
and the restart. The live copies can still drift from the repo copies.

**Line endings trap (found 2026-09-24).** A Windows checkout (`core.autocrlf`)
has CRLF endings in `deploy/*.sh` and `*.reference`, and bash rejects those
files (`set: pipefail\r: invalid option name`). The share is hosted on a Windows
PC, so never copy a launcher onto it from a Windows checkout without converting
the endings to LF.

**How the launchers actually reach `/usr/local/bin` (corrected 2026-08-05).**
Both `scpi-launch.sh` and `scpi-from-github.sh` are *generated* by
`install_lab_launchers.sh` (repo copy: `deploy/install_lab_launchers.sh`),
which writes each from an inline heredoc — so `deploy/scpi_from_github.sh` is
**not** what lands on disk, despite what step 2 above says, and the live file
has drifted from it (condensed formatting, different `say` strings). Edit the
installer, not the repo copy: re-running the installer to provision a PC or
repair desktop icons silently overwrites both launchers and reverts any hand
edit. Reconciling the two copies is tracked in issue #206. Related trap: the
GitHub fallback's runtime clone `~/.cache/scpi_control_git` stores its **own**
`origin`, and `REPO` is only consulted on the *first* clone — so changing the
URL in the scripts does nothing on a machine that already has that cache.
Repoint it (`git -C ~/.cache/scpi_control_git remote set-url origin <url>`) or
delete the directory and let it re-clone.

## Start-up time — where it actually goes

Measured on the bench PC:

| Phase | Cold | Warm |
|---|---|---|
| Python imports | 0.02 s | 0.02 s |
| Building the six tabs | 2.6 s | 0.8 s |
| Cache re-sync (only after a deploy) | ~25 s | – |
| Instrument auto-connect | background, non-blocking | – |

So: a normal launch is a couple of seconds; the *first* launch after a deploy
pays the sync. Both now report themselves — the app shows a splash with a live
phase line, and the launcher raises a desktop notification before a re-sync.

Historical note: before the local-cache design, a cold launch straight off the
CIFS share took **72 s**, nearly all of it `pyvisa` import I/O over SMB.

## Shared "kiosk" account (`robotincubator`)

**Auto-login at boot** is configured in `/etc/gdm/custom.conf`:

```
[daemon]
AutomaticLoginEnable=True
AutomaticLogin=robotincubator
```

**Known behaviour:** this applies *only at boot*. Every logout, "Switch User",
or screen-lock returns to the GDM greeter, which prompts for a password
normally. That is GDM working as designed, not a broken configuration — so
"I have to type the password again every time I switch users" is expected
unless the greeter itself is told otherwise.

### Making the switch password-free (operator decision)

If the lab wants that account selectable from the greeter without a password,
the mechanism is a PAM rule in the **graphical login stack only**
(`/etc/pam.d/gdm-password`) that succeeds immediately for that one username,
placed directly after the existing `pam_selinux_permit.so` line so it is
evaluated before the password substack:

```
auth     [success=done ignore=ignore default=bad] pam_succeed_if.so user = robotincubator quiet_success
```

Understand the trade-off before doing it:

- It covers the GDM greeter **and the GNOME unlock screen** for that account.
- It does **not** touch `ssh`, `sudo`, `su`, or `xrdp`, and no other account
  is affected.
- It does mean anyone at the keyboard can enter that account freely. On a
  machine that already auto-logs into it at boot the practical change is
  small, but it is a real one: do not use it for an account that owns
  anything sensitive.

Practical safety when editing PAM: **keep a root shell open on another VT**,
back the file up first, verify the file still contains its
`substack password-auth` line afterwards, and test "Switch User" *before*
logging out of everything. A broken `gdm-password` locks every account out of
the desktop; recovery is restoring the backup from a text console.

## Desktop icons and the "plugin to the panel" error

An **untrusted** `.desktop` file is *opened* rather than executed. The only
handler registered for `application/x-desktop` here was xfce4-panel's
`panel-desktop-handler.desktop` (`Exec=xfce4-panel --add=launcher %u`), which
fails in a GNOME session with

```
Failed to add a plugin to the panel
GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: The name is not activatable
```

Two mitigations, both installed by `~/install_lab_launchers.sh`:

1. The login helper keeps each user's desktop icon marked
   `metadata::trusted true`, and now only re-copies the file when its content
   differs — a plain `cp -f` every login silently dropped that flag.
2. `/etc/xdg/mimeapps.list` removes the association. It **must** be the
   generic file: GIO warns and ignores `[Removed Associations]` in
   `gnome-mimeapps.list` ("only the non-desktop-specific mimeapps.list file
   may add or remove associations"), so the change cannot be scoped per
   desktop.

Escape hatch that never needs trust: **Activities → type "SCPI" → Enter.**

## Verifying GUI changes without a seat

`xorg-x11-server-Xvfb` is installed. For screenshots or timing runs when no
desktop session is reachable:

```
Xvfb :99 -screen 0 1400x900x24 &
DISPLAY=:99 .venv/bin/python gui.py
```
