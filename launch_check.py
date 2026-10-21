#!/usr/bin/env python3
"""Start a helper program as a process of its own, and tell whether it
stayed up (#429).

The SLDEA tab starts Edge Review, the Edge tuner, the plot window and the
video review as programs of their own, so they outlive the bench app. Each
launcher used to say "<program> opened on <run>" as soon as Popen
returned. A program that died at once (an import error, a run it could not
take, no display) still read as opened, and what it printed went to the
bench app's own output: on the lab PCs a pipe into the launcher's tee and
launch.log, where nobody looks while working.

start() opens a log file for the program and starts it with its stdout and
stderr in that file. watch() then looks at the process from the Tk thread,
with after() polls of proc.poll() every POLL_MS over CHECK_MS, and calls
`down(code)` if it exited by then or `up()` if it is still running. Nothing
here waits: poll() is a non-blocking waitpid, and the only reads are of
the local log, once, after the process has exited.

Why the look goes on after up() (#473). On some Windows PCs about 1 in 30
Python starts is held about 5 s before Python runs: 36 of 1080 starts of
the venv's python lived 5.08 to 5.21 s with under 0.1 s of CPU (Gogojster,
2026-10-19, #458). So a program can still be starting at CHECK_MS, read as
up, and then die on an import or a run it cannot take. watch() therefore
keeps looking, every LATE_POLL_MS, until WATCH_MS after the start, and
calls `late(code, secs)` if the program exits in that time. WATCH_MS is a
bound, not a measurement: about six times that hold, plus the 0.2 to
0.33 s these programs take to import on ClaudeBox (#429). A program that
dies later than that is still not said. At its end the watch lets go of
the process, and the caller's window can end it at once (Watch.cancel).

Why a file and not a pipe. The program outlives the app, so nothing would
drain a pipe once the app has gone, and a full pipe stops the program at
its next print. A file needs no reader. Both streams go to the one file.
That also takes the program off the bench app's own output: before #429 an
open Edge Review held the write end of the launcher's tee pipe, which by
launch_gui.sh.reference keeps the launcher script waiting after the app
has closed (read, not measured).

Unbuffered. A Python program writing to a file buffers its stdout and
writes it at exit, AFTER the traceback on its stderr, so the lines it
printed last could push the traceback out of the tail: 20 printed lines
and then a RuntimeError left a 12-line tail of printed lines only (#429
review, measured 2026-10-08). The program therefore runs with
PYTHONUNBUFFERED=1, and both streams reach the file in the order they were
written. That one variable is the only change to its environment.

Where the logs go. LOCAL and per user, never the run folder: the run
folder is usually on the share, which stalls (#397), and on the analysis
VM it is mounted read-only. The folder is LOG_SUBDIR in the per-user
folder that tk_stall.log and the launchers' own logs share
(tk_stall.default_log_path: $SCPI_CACHE or ~/.cache/scpi_control on
Linux, %LOCALAPPDATA%\\scpi_control on Windows). One file per start, made
by tempfile.mkstemp (a new name each time, readable by its owner only).
Each start first removes logs in that folder older than KEEP_S, so the
folder holds about a week of starts; a log that is still open in a
running program on Windows cannot be removed and is left for a later
start.

When the log cannot be made, the program is started exactly as before,
with the app's own output, and a failure report says its output was not
kept and why: a log is never a reason not to open the program.

Tk-free: watch() takes anything with after(ms, fn), so the cases run
anywhere. Self-test: .venv/bin/python tests/test_launch_check.py
"""
import locale
import math
import os
import shlex
import subprocess
import tempfile
import time

import tk_stall

CHECK_MS = 2000      # a program still running this long after start is up
POLL_MS = 200        # how often watch() looks before then
WATCH_MS = 30000     # a death up to this long after start is still said
LATE_POLL_MS = 500   # how often watch() looks between CHECK_MS and that
TAIL_LINES = 12      # lines of a stopped program's output shown in its box
TAIL_BYTES = 8192    # read at most this much of the log's end for them
LINE_CHARS = 200     # a longer output line is cut to this in the box
KEEP_S = 7 * 24 * 3600   # logs older than this go at the next start
LOG_SUBDIR = 'launch_logs'
LOG_SUFFIX = '.log'
# added to the program's environment when its output goes to a log (see
# the module docstring: a traceback must not fall out of the tail)
UNBUFFERED_ENV = {'PYTHONUNBUFFERED': '1'}

# Tests aim this at a folder of their own; None is the per-user default.
LOG_DIR = None


class Launch:
    """One start: the process, and where its output is.

    `path` is the log file, or None when none could be made (`why` then
    says why). `start` is the log's byte offset where the program's own
    output begins, after the header start() wrote."""

    def __init__(self, proc, program, path, start=0, why=''):
        self.proc = proc
        self.program = program
        self.path = path
        self.start = start
        self.why = why


def log_dir():
    """The folder the logs go in (see the module docstring)."""
    if LOG_DIR:
        return LOG_DIR
    return os.path.join(os.path.dirname(tk_stall.default_log_path()),
                        LOG_SUBDIR)


def _slug(program):
    """'Edge Review' -> 'edge_review', for the log's name."""
    out = ''.join(c.lower() if c.isalnum() else '_' for c in program)
    return out.strip('_') or 'program'


def sweep(folder, now=None, keep_s=None):
    """Remove the logs in `folder` older than `keep_s` (KEEP_S) by their
    last write. Only files this module names (*.log) are touched, and
    nothing here raises: a log still open in a running program on Windows
    is left for a later start. -> how many were removed."""
    keep_s = KEEP_S if keep_s is None else keep_s
    now = time.time() if now is None else now
    gone = 0
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return 0
    for e in entries:
        try:
            if not (e.name.endswith(LOG_SUFFIX) and e.is_file(
                    follow_symlinks=False)):
                continue
            if now - e.stat(follow_symlinks=False).st_mtime > keep_s:
                os.remove(e.path)
                gone += 1
        except OSError:
            pass
    return gone


def _open_log(program, cmd):
    """-> (file, path, start): a new log for one start of `program`, with
    a two-line header saying what was started and when, flushed so the
    program's output follows it. Raises OSError when it cannot be made."""
    folder = log_dir()
    os.makedirs(folder, exist_ok=True)
    sweep(folder)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    fd, path = tempfile.mkstemp(prefix=f"{_slug(program)}_{stamp}_",
                                suffix=LOG_SUFFIX, dir=folder)
    f = os.fdopen(fd, 'wb')
    try:
        head = (f"# {program}, started {time.strftime('%Y-%m-%d %H:%M:%S')}"
                f"\n# {' '.join(shlex.quote(str(a)) for a in cmd)}\n")
        f.write(head.encode('utf-8', 'backslashreplace'))
        f.flush()
        return f, path, f.tell()
    except BaseException:
        f.close()
        try:
            os.remove(path)
        except OSError:
            pass
        raise


def start(cmd, program, popen=subprocess.Popen):
    """Start `cmd` as a process of its own (start_new_session, as the
    launchers always have) with its stdout and stderr in a new log file.
    -> a Launch. Its arguments and working folder are the caller's,
    unchanged, and so is its environment but for PYTHONUNBUFFERED=1 (see
    the module docstring). `popen` is the caller's subprocess.Popen, so a
    test that stands in for the caller's subprocess module catches this
    start too.

    Raises what `popen` raises, as before #429. A log that cannot be made
    costs only the log: the program is started on the app's own output."""
    try:
        f, path, head = _open_log(program, cmd)
    except OSError as e:
        proc = popen(cmd, start_new_session=True)
        return Launch(proc, program, None, why=str(e))
    try:
        proc = popen(cmd, start_new_session=True, stdout=f,
                     stderr=subprocess.STDOUT,
                     env=dict(os.environ, **UNBUFFERED_ENV))
    except BaseException:
        f.close()
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    # the program has its own handle on the file now; this one is ours
    f.close()
    return Launch(proc, program, path, start=head)


def _decode(raw):
    """Log bytes -> text, never raising. A program writing to a file uses
    the locale's encoding, which is not UTF-8 on every Windows PC."""
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode(locale.getpreferredencoding(False),
                          errors='replace')


def tail(path, start=0, lines=None, max_bytes=None):
    """The last `lines` (TAIL_LINES) lines a program wrote to its log
    `path`, read from at most its last `max_bytes` (TAIL_BYTES) bytes and
    never from before `start` (the header). Each line is cut to
    LINE_CHARS. -> the text ('' when it wrote nothing), or None when the
    log cannot be read."""
    lines = TAIL_LINES if lines is None else lines
    max_bytes = TAIL_BYTES if max_bytes is None else max_bytes
    try:
        with open(path, 'rb') as f:
            end = f.seek(0, os.SEEK_END)
            begin = max(start, end - max_bytes)
            f.seek(begin)
            raw = f.read(end - begin)
    except OSError:
        return None
    if begin > start:
        # read from the middle of a line: drop its partial start
        cut = raw.find(b'\n')
        if cut >= 0:
            raw = raw[cut + 1:]
    out = [ln.rstrip() for ln in _decode(raw).splitlines()]
    while out and not out[-1]:
        out.pop()
    out = out[-lines:] if lines > 0 else []
    return '\n'.join(ln if len(ln) <= LINE_CHARS
                     else ln[:LINE_CHARS - 3] + '...' for ln in out)


def exit_words(code):
    """'exit code 3', or on POSIX, for a program a signal ended (Popen's
    negative return code), 'ended by signal 11'."""
    if code is not None and code < 0:
        return f"ended by signal {-code}"
    return f"exit code {code}"


def when_words(secs=None):
    """When a program stopped, for its status line and box: 'before it
    opened' for one that stopped within CHECK_MS (`secs` None), or, for
    one watch() saw stop later (#473), 'within 7 s of starting', from
    the time of the look that found it gone: the exit came before that
    look, so the number is an upper bound."""
    if secs is None:
        return "before it opened"
    return f"within {max(1, math.ceil(secs))} s of starting"


def report(launch, code, secs=None):
    """The text of the box for a program that stopped as it started (or,
    with `secs`, soon after it read as opened, #473): its exit code, the
    last lines it printed, and where all of them are."""
    head = (f"{launch.program} stopped {when_words(secs)} "
            f"({exit_words(code)}).")
    if launch.path is None:
        return (f"{head}\n\nIts output was not kept: no log file could be "
                f"made ({launch.why}). It went to this app's own output.")
    text = tail(launch.path, launch.start)
    if text is None:
        said = "Its log could not be read."
    elif not text:
        said = "It printed nothing."
    else:
        said = f"The last lines it printed:\n\n{text}"
    return f"{head}\n\n{said}\n\nAll of its output:\n{launch.path}"


class Watch:
    """One watch() of a started program (#473). `done` once it has ended:
    it called down() or late(), its time ran out, a callback raised, the
    window refused its next after(), or cancel() ended it. At its end it
    lets go of the process and of the callbacks (which hold the Launch),
    so a program nobody watches any more is not held here. `job` is its
    pending after() id, or None."""

    def __init__(self, root, proc, up, down, late):
        self.root, self.proc = root, proc
        self.up, self.down, self.late = up, down, late
        self.job = None
        self.done = False

    def _end(self):
        self.done = True
        self.proc = self.up = self.down = self.late = None

    def cancel(self):
        """End the watch now, telling nobody: for the caller's window as
        it closes, so no look fires into a window that is gone. Never
        raises; a watch already ended is left as it is."""
        job, self.job = self.job, None
        self._end()
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass


def watch(root, proc, up, down, late=None, check_ms=None, poll_ms=None,
          watch_ms=None, late_poll_ms=None, clock=time.monotonic):
    """Look at `proc` from the Tk thread of `root`: every `poll_ms`
    (POLL_MS) until `check_ms` (CHECK_MS) after this call. The first look
    that finds it exited calls `down(code)`; a look at or after `check_ms`
    that finds it running calls `up()`. Exactly one of them is called,
    unless the window goes first.

    After up(), with a `late`, the look goes on every `late_poll_ms`
    (LATE_POLL_MS) until `watch_ms` (WATCH_MS) after this call (#473): a
    look that finds the program exited calls `late(code, secs)`, `secs`
    being the time of that look since this call, and the first look at or
    after `watch_ms` that finds it running ends the watch. Exit code 0
    included; what it means is the caller's to say. With no `late`, up()
    ends the watch, as before #473. At most one of down() and late() is
    ever called, and the watch has ended before it is.

    Each look is one proc.poll() and a clock read, and the exit is looked
    for before the time, so a Tk thread held up past either time still
    reports an exit it missed. Never raises into Tk: a poll that raises
    counts as running, and a callback that raises ends the watch.
    -> the Watch, whose cancel() ends it."""
    check_ms = CHECK_MS if check_ms is None else check_ms
    poll_ms = POLL_MS if poll_ms is None else poll_ms
    watch_ms = WATCH_MS if watch_ms is None else watch_ms
    late_poll_ms = LATE_POLL_MS if late_poll_ms is None else late_poll_ms
    w = Watch(root, proc, up, down, late)
    t0 = clock()
    opened = False

    def look():
        nonlocal opened
        w.job = None
        if w.done:
            return
        try:
            code = w.proc.poll()
        except Exception:
            code = None
        up, down, late = w.up, w.down, w.late
        try:
            if code is not None:
                w._end()            # first: one report for one exit
                if not opened:
                    down(code)
                else:
                    late(code, clock() - t0)
                return
            ms = (clock() - t0) * 1000.0
            if not opened and ms >= check_ms:
                opened = True
                up()
                if late is None:
                    w._end()
                    return
            if opened and ms >= watch_ms:
                w._end()
                return
        except Exception:
            w._end()
            return
        nxt(late_poll_ms if opened else poll_ms)

    def nxt(ms):
        try:
            w.job = root.after(ms, look)
        except Exception:
            w._end()            # the window is gone: nobody left to tell

    nxt(poll_ms)
    return w
