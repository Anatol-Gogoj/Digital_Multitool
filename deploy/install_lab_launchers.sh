#!/usr/bin/env bash
# ============================================================================
#  Make the SCPI Control + Share Drive launchers work for EVERY user on this
#  shared bench (current and future), with no per-user "Allow Launching" step.
#
#    1) System-wide app launchers in /usr/share/applications  -> appear in the
#       Activities / app grid for all users immediately (no trust needed).
#    2) A login autostart helper that drops the same launchers onto each user's
#       Desktop and marks them trusted IN THAT user's session, so the desktop
#       icons launch on double-click automatically.
#
#  Run as root:  sudo bash ~/install_lab_launchers.sh
# ============================================================================
set -euo pipefail

APPDIR=/usr/share/applications
HELPER=/usr/local/bin/scpi-lab-desktop-icons.sh
AUTOSTART=/etc/xdg/autostart/scpi-lab-desktop-icons.desktop
WRAPPER=/usr/local/bin/scpi-launch.sh
GHSCRIPT=/usr/local/bin/scpi-from-github.sh

# --- 0) Resilient launch wrapper ---------------------------------------------
# The share lives on the NAS (192.168.68.55) behind autofs; when the NAS is
# down, Exec'ing launch_gui.sh directly dies SILENTLY (Terminal=false). The
# wrapper tries the share (with a timeout so a dead autofs can't hang), falls
# back to a local clone if the user has one, and reports failures visibly.
cat > "$WRAPPER" <<'WRAP'
#!/bin/bash
# SCPI Control launcher: shared drive first, then this user's local cache,
# then a dev clone; loud errors instead of a silent nothing.
SHARE=/mnt/shareDrive/_software
CACHE="${SCPI_CACHE:-$HOME/.cache/scpi_control}"
LOCALROOT="$HOME/.local/share/scpi_control"
LOCAL="$HOME/projects/SCPI_Control"
GHSCRIPT=/usr/local/bin/scpi-from-github.sh
REPO=https://github.com/Anatol-Gogoj/Digital_Multitool

err() {
    zenity --error --title "SCPI Control" --text "$1" 2>/dev/null \
        || notify-send -u critical "SCPI Control" "$1" 2>/dev/null
}

# Probe by actually READING a byte. On 2026-07-20 `test -r` succeeded
# against a dead NAS and the exec that followed died with "Host is down",
# so the fallbacks below never ran.
if timeout 5 head -c 1 "$SHARE/launch_gui.sh" >/dev/null 2>&1; then
    exec bash "$SHARE/launch_gui.sh"
fi

# Share is down -> if GitHub is reachable, pull the LATEST and run from it
# (this is the backup for a share outage; the local cache can be stale).
# The quick ls-remote gate means a full internet outage falls through fast.
if [ -x "$GHSCRIPT" ] \
   && timeout 8 git ls-remote --heads "$REPO" main >/dev/null 2>&1; then
    exec bash "$GHSCRIPT"
fi

# No internet either -> run the cache the share launcher keeps up to date.
# cwd is the local presets root, so presets/ resolves to the same place
# the app falls back to (presets_path.LOCAL_FALLBACK) and work is kept.
if [ -f "$CACHE/SCPI_Control/gui.py" ]; then
    notify-send "SCPI Control" \
        "Shared drive unreachable (NAS down?) -- running the local cached copy. Presets are saved locally until the drive is back." 2>/dev/null
    mkdir -p "$LOCALROOT"
    cd "$LOCALROOT" || exit 1
    exec env PYTHONPATH="$CACHE/pylibs" /usr/bin/python3.11 \
        "$CACHE/SCPI_Control/gui.py"
fi

if [ -x "$LOCAL/.venv/bin/python" ] && [ -f "$LOCAL/gui.py" ]; then
    notify-send "SCPI Control" \
        "Shared drive unreachable (NAS down?) -- launching the LOCAL copy from $LOCAL instead." 2>/dev/null
    cd "$LOCAL" && exec "$LOCAL/.venv/bin/python" gui.py
fi

err "Cannot launch SCPI Control: the shared drive is unreachable (is the NAS at 192.168.68.55 powered on?) and this account has no local cached copy yet. Launch once while the drive is up, and the cache will cover later outages."
exit 1
WRAP
chmod 0755 "$WRAPPER"
echo "0) installed launch wrapper $WRAPPER"

# --- 0b) GitHub backup launcher ----------------------------------------------
# Runs the app straight from GitHub onto local disk, for when the ShareDrive
# is unreachable (e.g. the Win11 host is down). GitHub is over the internet,
# not the LAN share, so it works during a share outage. Canonical copy lives
# in the repo at deploy/scpi_from_github.sh.
cat > "$GHSCRIPT" <<'GHEOF'
#!/usr/bin/env bash
# Digital Multitool -- GitHub backup launcher (share-down fallback).
set -uo pipefail
REPO="${SCPI_GITHUB_REPO:-https://github.com/Anatol-Gogoj/Digital_Multitool}"
GHDIR="${SCPI_GITHUB_DIR:-$HOME/.cache/scpi_control_git}"
CACHE_LIBS="$HOME/.cache/scpi_control/pylibs"
PRESETS_ROOT="$HOME/.local/share/scpi_control"
PY="${SCPI_PYTHON:-/usr/bin/python3.11}"
command -v "$PY" >/dev/null 2>&1 || PY=python3.11
say()  { echo "Digital Multitool: $*"; notify-send "Digital Multitool" "$*" 2>/dev/null || true; }
fail() { zenity --error --title "Digital Multitool" --text "$1" 2>/dev/null \
           || notify-send -u critical "Digital Multitool" "$1" 2>/dev/null; echo "ERROR: $1" >&2; exit 1; }
command -v git >/dev/null 2>&1 || fail "git is not installed -- cannot pull from GitHub."
if [ -d "$GHDIR/.git" ]; then
    say "updating from GitHub..."
    if timeout 120 git -C "$GHDIR" fetch --depth 1 origin main 2>/dev/null; then
        git -C "$GHDIR" reset --hard FETCH_HEAD >/dev/null 2>&1 || true
    else say "GitHub update failed -- using the last-downloaded copy."; fi
else
    say "downloading from GitHub (first time)..."
    rm -rf "$GHDIR"
    timeout 180 git clone --depth 1 "$REPO" "$GHDIR" 2>/dev/null \
        || fail "Could not download from GitHub. Check the internet connection and try again."
fi
[ -f "$GHDIR/gui.py" ] || fail "GitHub copy is incomplete (no gui.py) -- try again."
ver="$(grep -m1 '^__version__' "$GHDIR/version.py" 2>/dev/null | cut -d'"' -f2)"
mkdir -p "$PRESETS_ROOT"; cd "$PRESETS_ROOT"
if [ -d "$CACHE_LIBS" ]; then
    say "running ${ver:-latest} from GitHub (local copy; presets saved locally)."
    exec env PYTHONPATH="$CACHE_LIBS" "$PY" "$GHDIR/gui.py" "$@"
fi
if [ ! -x "$GHDIR/.venv/bin/python" ]; then
    say "first-time setup: installing Python packages (a few minutes, needs internet)..."
    "$PY" -m venv "$GHDIR/.venv" || fail "Could not create a Python environment."
    "$GHDIR/.venv/bin/python" -m pip install --quiet --upgrade pip setuptools wheel
    "$GHDIR/.venv/bin/python" -m pip install --quiet -r "$GHDIR/requirements.txt" \
        || fail "Package install failed (no internet?). Try again once online."
fi
say "running ${ver:-latest} from GitHub (local copy; presets saved locally)."
exec "$GHDIR/.venv/bin/python" "$GHDIR/gui.py" "$@"
GHEOF
chmod 0755 "$GHSCRIPT"
echo "0b) installed GitHub backup launcher $GHSCRIPT"

# --- 1) System-wide application launchers -----------------------------------
cat > "$APPDIR/scpi-control.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=SCPI Control
GenericName=Lab instrument GUI
Comment=Launch the SCPI_Control instrument GUI (shared drive, local fallback)
Exec=bash /usr/local/bin/scpi-launch.sh
Icon=applications-science
Terminal=false
Categories=Science;Utility;
Keywords=scpi;instrument;signal;oscilloscope;lcr;lab;
DESK

cat > "$APPDIR/sharedrive.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=Share Drive
GenericName=Lab network drive
Comment=Open the shareDrive SMB network drive (//192.168.68.55/shareDrive)
Exec=xdg-open /mnt/shareDrive
Icon=folder-remote
Terminal=false
Categories=System;Network;Utility;
Keywords=smb;cifs;network;share;drive;nas;
DESK
chmod 0644 "$APPDIR/scpi-control.desktop" "$APPDIR/sharedrive.desktop"
update-desktop-database "$APPDIR" 2>/dev/null || true
echo "1) installed system launchers in $APPDIR"

# --- 2) Per-user helper: trusted desktop icons for whoever logs in ----------
cat > "$HELPER" <<'HELP'
#!/usr/bin/env bash
# Runs at every login (via /etc/xdg/autostart). Keeps the lab launchers on
# ~/Desktop AND marked trusted in THIS user's session.
#
# Trust is not cosmetic: an untrusted .desktop is OPENED rather than
# executed, and the only registered handler for application/x-desktop on
# this box is XFCE's panel-desktop-handler, so a double-click produces
#   "Failed to add a plugin to the panel ... The name is not activatable"
# instead of starting the app (seen by robotincubator, 2026-07-20).
set -u
DESK="$HOME/Desktop"
mkdir -p "$DESK" 2>/dev/null || exit 0
for f in scpi-control.desktop sharedrive.desktop; do
  src="/usr/share/applications/$f"; dst="$DESK/$f"
  [ -f "$src" ] || continue
  # Copy ONLY when the content differs -- replacing the file drops the
  # gvfs "trusted" metadata we are trying to preserve.
  if ! cmp -s "$src" "$dst" 2>/dev/null; then
    cp -f "$src" "$dst" 2>/dev/null || continue
  fi
  chmod 0755 "$dst" 2>/dev/null || true
  # The gvfs metadata daemon can still be starting right after login, so
  # set-and-verify a few times instead of firing once and hoping.
  for _try in 1 2 3; do
    if gio info -a metadata::trusted "$dst" 2>/dev/null \
         | grep -q "trusted: true"; then
      break
    fi
    gio set "$dst" metadata::trusted true 2>/dev/null || true
    sleep 1
  done
done
exit 0
HELP
chmod 0755 "$HELPER"
echo "2) installed per-user helper $HELPER"

# --- 2b) Stop XFCE's panel handler from hijacking .desktop double-clicks ----
# xfce4-panel ships panel-desktop-handler.desktop, the ONLY registered
# handler for application/x-desktop here. If an icon ever loses its trusted
# flag, the double-click is handed to it and the user gets the confusing
# "Failed to add a plugin to the panel ... not activatable" dialog, because
# xfce4-panel is not running in a GNOME session.
#
# NOTE (verified 2026-07-20): [Removed Associations] is honoured ONLY in the
# non-desktop-specific mimeapps.list. GIO warns and IGNORES it in
# gnome-mimeapps.list -- "Only the non-desktop-specific mimeapps.list file
# may add or remove associations" -- so it has to go in the generic file
# even though that also covers a real XFCE session. Nobody here uses XFCE
# and the handler is broken outside a running xfce4-panel anyway.
MIMEAPPS=/etc/xdg/mimeapps.list
GNOMEMIME=/etc/xdg/gnome-mimeapps.list
ASSOC="application/x-desktop=panel-desktop-handler.desktop;"

# Remove the earlier, ignored attempt -- but only if it is exactly the file
# this script wrote, never someone else's config.
if [ -f "$GNOMEMIME" ] && grep -q "panel-desktop-handler" "$GNOMEMIME" \
   && [ "$(grep -cve '^[[:space:]]*$' "$GNOMEMIME")" -le 2 ]; then
  rm -f "$GNOMEMIME"
  echo "2b) removed the ignored $GNOMEMIME"
fi

if [ -f "$MIMEAPPS" ]; then
  cp -a "$MIMEAPPS" "$MIMEAPPS.bak-$(date +%Y%m%d%H%M)"
  if ! grep -q "panel-desktop-handler" "$MIMEAPPS"; then
    if grep -q "^\[Removed Associations\]" "$MIMEAPPS"; then
      sed -i "/^\[Removed Associations\]/a $ASSOC" "$MIMEAPPS"
    else
      printf '\n[Removed Associations]\n%s\n' "$ASSOC" >> "$MIMEAPPS"
    fi
  fi
else
  printf '[Removed Associations]\n%s\n' "$ASSOC" > "$MIMEAPPS"
fi
chmod 0644 "$MIMEAPPS"
echo "2b) GNOME will no longer hand .desktop files to xfce4-panel"

# --- 3) Autostart entry that runs the helper at every user's login ----------
cat > "$AUTOSTART" <<DESK
[Desktop Entry]
Type=Application
Name=SCPI lab desktop icons
Comment=Install trusted lab launchers on the desktop
Exec=$HELPER
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
DESK
chmod 0644 "$AUTOSTART"
echo "3) installed login autostart $AUTOSTART"

# --- 4) Apply now to any already-logged-in graphical user -------------------
echo "4) applying to currently logged-in users:"
while read -r _sid uid user _seat _tty _state _rest; do
  bus="/run/user/$uid/bus"
  home="$(getent passwd "$uid" | cut -d: -f6)"
  [ -S "$bus" ] && [ -n "$home" ] || continue
  sudo -u "$user" env XDG_RUNTIME_DIR="/run/user/$uid" \
       DBUS_SESSION_BUS_ADDRESS="unix:path=$bus" HOME="$home" \
       bash "$HELPER" 2>/dev/null \
    && echo "   applied for $user" || echo "   (skipped $user)"
done < <(loginctl list-sessions --no-legend)

echo
echo "Done. Every user now gets: app-grid entries (Super -> type 'SCPI') and"
echo "trusted desktop icons at login. Already-logged-in users were updated now"
echo "(may need to toggle the desktop / re-login to see refreshed icons)."
