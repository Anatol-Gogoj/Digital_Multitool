#!/usr/bin/env python3
"""Pure helpers for the folder pickers that choose where output goes (no Tk).

Issue #394. On the Linux bench Tk draws its own folder dialog
(tk_chooseDirectory, Tk 8.6 choosedir.tcl), and it has no New Folder
button, so an operator who wanted a fresh folder for a session had to make
it in the system file manager and come back. The SLDEA tab's Browse also
opened at the process's working directory instead of at the folder already
in the box.

This module is the deciding half of the fix, kept out of Tk so it can be
tested anywhere, Linux without tkinter included:

  * browse_start -- where a Browse dialog opens: the folder in the box, or
    the nearest folder above it that still exists.
  * parent_problem / name_problem -- what New folder... refuses, worded as
    the message to show.
  * new_path / make -- where the new folder goes, and making it.
  * failed_text -- the message for a folder the system would not make (a
    read-only or missing share), so that case is never a traceback.

ui_widgets.browse_folder / new_folder put these behind the dialogs; the
SLDEA, Webcam and Continuous Logging tabs share them.

Headless self-test: .venv/bin/python tests/test_output_folder.py
"""
import os

# The button's label on every tab that has one. A Unicode ellipsis, like
# the plot window's "New group..." menu item.
NEW_FOLDER_LABEL = "New folder\u2026"

# Names Windows does not allow for a file or folder, from Microsoft's
# "Naming Files, Paths, and Namespaces": these characters, codes 0-31, a
# trailing dot or space, and the device names below. Linux makes most of
# them without complaint, but the share is also read from the lab's
# Windows PCs. ':' matters on Windows itself too: os.path.join('C:\\data',
# 'D:x') is 'D:x', a folder outside the box. The device names are the set
# CPython 3.13's ntpath.isreserved checks; the bench's Python 3.11 has no
# isreserved, hence a copy.
_WINDOWS_FORBIDDEN = '<>:"|?*'
_WINDOWS_DEVICES = frozenset(
    ['CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$']
    + [f'COM{d}' for d in '123456789\u00b9\u00b2\u00b3']
    + [f'LPT{d}' for d in '123456789\u00b9\u00b2\u00b3'])


def browse_start(box):
    """The folder a Browse dialog opens at, for a box holding `box`.

    The folder in the box when it exists. When it does not (a run folder
    deleted since, a share that is not mounted), the nearest folder above
    it that does, which also shows where the path stops. An empty box means
    the working directory, which is where an empty box sends an SLDEA run
    and the Webcam's images.
    """
    path = os.path.abspath((box or '').strip() or os.curdir)
    while not os.path.isdir(path):
        up = os.path.dirname(path)
        if up == path:              # walked off the top: nothing exists
            return os.getcwd()
        path = up
    return path


def parent_problem(where, box):
    """Why New folder... cannot make a folder inside `where` (the text in
    the `box` box), as the message to show, or None when it can.

    It never picks a parent of its own: a folder made somewhere the
    operator did not choose is worse than being asked to choose one.
    """
    where = (where or '').strip()
    again = f"then press {NEW_FOLDER_LABEL} again."
    if not where:
        return (f"The {box} box is empty, so there is no folder to make the "
                f"new one in.\n\nFill the box first (type a folder or use "
                f"Browse), {again}")
    if os.path.isdir(where):
        return None
    if os.path.exists(where):
        return (f"The {box} box names a file, not a folder:\n{where}\n\n"
                f"Fill the box with a folder (type it or use Browse), "
                f"{again}")
    return (f"The folder in the {box} box does not exist:\n{where}\n\n"
            f"If it is on the share, check that the share is mounted. "
            f"Otherwise fill the box with a folder that exists (type it or "
            f"use Browse), {again}")


def name_problem(name):
    """Why `name` cannot be the new folder's name, as the message to show,
    or None when it can.

    Spaces around the name do not count: make() strips them, so the folder
    made is exactly the name that ends up in the box.
    """
    text = (name or '').strip()
    if not text:
        return "Type a name for the new folder."
    if text in ('.', '..'):
        return (f"'{text}' is not a folder name. Type a name for the new "
                f"folder.")
    if '/' in text or '\\' in text:
        return ("A folder name cannot contain / or \\. This makes one "
                "folder, inside the folder in the box.")
    bad = sorted(set(c for c in text if c in _WINDOWS_FORBIDDEN))
    if bad:
        return (f"A folder name cannot contain {' '.join(bad)}. Windows "
                f"does not allow {'it' if len(bad) == 1 else 'them'} in a "
                f"name, and the share is also read from the lab's Windows "
                f"PCs.")
    if any(ord(c) < 32 for c in text):
        return "A folder name cannot contain a control character, like a tab."
    if text.endswith('.'):
        return ("A folder name cannot end with a dot. Windows drops it, so "
                "the folder would not keep the name you typed.")
    if text.partition('.')[0].rstrip(' ').upper() in _WINDOWS_DEVICES:
        return (f"'{text}' is a device name on Windows (like CON, NUL, COM1 "
                f"or LPT1), so it cannot be a folder name there.")
    return None


def new_path(where, name):
    """Where folder `name` goes inside `where`.

    os.path.join, keeping the box's own separator: Browse fills the box
    with forward slashes on Windows too (C:/data), and a mixed
    C:/data\\run1 in the box looks wrong even though it works. `name` never
    holds a separator by the time it gets here (name_problem refuses one).
    """
    path = os.path.join(where, name)
    if os.sep == '\\' and '/' in where and '\\' not in where:
        path = path.replace('\\', '/')
    return path


def make(where, name):
    """Make folder `name` inside `where` -> the new folder's path.

    Raises ValueError, carrying the message to show, when the name is
    refused or already taken; raises OSError when the system will not make
    it (failed_text words that message). `where` is the caller's to check
    first, with parent_problem.

    os.mkdir rather than os.makedirs: it makes this one folder and never a
    folder above it. If the share drops between the check on `where` and
    this call, makedirs could rebuild the missing path under the bare mount
    point, on the local disk; mkdir fails instead, and the operator is told.
    """
    problem = name_problem(name)
    if problem:
        raise ValueError(problem)
    name = name.strip()
    path = new_path(where, name)
    try:
        os.mkdir(path)
    except FileExistsError:
        is_dir = os.path.isdir(path)
        raise ValueError(
            f"There is already a {'folder' if is_dir else 'file'} called "
            f"'{name}' in\n{where}\n\nType another name"
            + (", or use Browse to choose that folder." if is_dir else ".")
        ) from None
    return path


def failed_text(where, name, err):
    """The message for a folder the system would not make: which folder,
    the system's reason, and the usual cause on the bench."""
    path = new_path(where, (name or '').strip())
    reason = (getattr(err, 'strerror', None) or str(err)
              or type(err).__name__)
    return (f"Could not make the folder\n{path}\n\n{reason.rstrip('.')}.\n\n"
            f"If it is on the share, check that the share is mounted and "
            f"that you can write to it.")
