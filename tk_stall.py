#!/usr/bin/env python3
"""Log each time a window stops responding, with the code it was stuck in.

The windows freeze, and not only after runs (operator report 2026-10-06,
`#397`). Reading the code turns up suspects: instrument queries with
multi-second timeouts at run start, run.log appends to the share, the
webcam preview's frame reads, Edge Review's run listing. Which of them
freezes which window, for how long and how often was never measured. A
window that calls `watch` measures it:

    import tk_stall
    tk_stall.watch(root, 'Edge Review')    # right after its root exists

How it works. A heartbeat on the window's Tk thread stamps the time every
HEARTBEAT_MS, and a daemon watchdog thread reads the stamp. A stamp more
than THRESHOLD_S old means the Tk thread has not been back to its event
loop, so the window can neither repaint nor take a click: a stall. While
it lasts the watchdog takes the Tk thread's stack (sys._current_frames):
at THRESHOLD_S, then 1, 2, 4 ... s in, never more than SAMPLE_MAX_GAP_S
apart. When the heartbeat comes back it writes ONE record: the whole gap,
the stacks, and the CPU time the Tk thread used over the gap.

Reading a record. The CPU time says what kind of stall it was:
  - Tk-thread CPU close to the gap: the window's own code was computing.
  - Tk-thread CPU close to zero: it waited, on a file, an instrument or a
    lock, or the PC gave it no CPU. The stack names the call it waited
    in. On Linux the load average shows whether the PC was busy. A
    whole-process CPU well above the Tk thread's means other threads of
    the same program ran meanwhile, and the Tk thread may have waited
    for one of them.
The gap is measured between heartbeats, so it includes up to one
HEARTBEAT_MS of ordinary idle time before the freeze began.

A stall that is still going after HANG_S also gets an early STALLING
record, so that a window that never recovers still leaves its stack
behind: GNOME and Windows both offer to kill a window that has not
answered for 5 s (mutter's check-alive-timeout default; the timeout in
the Win32 IsHungAppWindow documentation), and a killed process writes
nothing more. If the window does recover, the STALL record with the same
stall number follows and supersedes it.

The log is LOCAL and per user, never the share, because a share stall is
one of the suspects. It goes where sldea_video.staging_root() puts local
files: ~/.cache/scpi_control/tk_stall.log on Linux, beside the launcher's
launch.log, and %LOCALAPPDATA%\\scpi_control\\tk_stall.log on Windows,
beside the Windows launcher's setup.log. Over MAX_BYTES it is rotated
once, to tk_stall.log.1, so the two files stay near 2 x MAX_BYTES. All
windows append to the same file, each record in one write() to a file
opened for appending; Linux keeps such writes whole when several windows
write at once, while on Windows two records written in the same instant
could interleave.

ON BY DEFAULT: the freezes this exists to find are the ones that happen
when nobody planned to measure. SCPI_STALL_LOG=0 (or off, no, false)
switches it off, and SCPI_STALL_LOG=<file> writes to that file instead.
While nothing stalls it costs one Tk timer callback every HEARTBEAT_MS
(41-47 us each, of which a bare after(50) is 38-39 us: under 0.1 % of one
core) and about four watchdog wake-ups a second (measured 2026-10-06 on
Windows 11).

It never raises into the window. A failure is caught, reported on stderr
(and in the log, when the log can be written), and ends only the logging.

Headless self-test: .venv/bin/python tests/test_tk_stall.py
"""
import collections
import gc
import os
import sys
import threading
import time

# ---- settings (`#397`) ------------------------------------------------------
HEARTBEAT_MS = 50          # the Tk thread stamps the time this often
THRESHOLD_S = 0.30         # a stamp older than this is a stall
HANG_S = 4.0               # still frozen this long: write STALLING at once
SAMPLE_MAX_GAP_S = 30.0    # stacks at 1, 2, 4 ... s into a stall, capped
MAX_SAMPLES = 12           # stacks kept per stall: the first 11 + the latest
MAX_FRAMES = 60            # innermost frames kept per stack
STALL_POLL_S = 0.1         # how often the watchdog looks while a stall lasts
MAX_BYTES = 1000000        # the log rotates to <log>.1 above this size
LOG_NAME = 'tk_stall.log'
ENV = 'SCPI_STALL_LOG'     # 0/off/no/false: off; anything else: the log file
OFF_WORDS = ('0', 'off', 'no', 'false')

APP_DIR = os.path.dirname(os.path.abspath(__file__))
THREAD_QUERY_LIMITED_INFORMATION = 0x0800          # winnt.h


# ---------------------------------------------------------------------------
# where the log goes
# ---------------------------------------------------------------------------

def default_log_path(env=None):
    """The house place for a local per-user file, as sldea_video's
    staging_root() uses it: %LOCALAPPDATA%\\scpi_control on Windows,
    ~/.cache/scpi_control elsewhere. The Linux launcher creates
    ~/.cache/scpi_control at every start, so it is writable."""
    env = os.environ if env is None else env
    if os.name == 'nt':
        base = env.get('LOCALAPPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'scpi_control', LOG_NAME)
    return os.path.join(os.path.expanduser('~'), '.cache', 'scpi_control',
                        LOG_NAME)


def log_path(env=None):
    """Where stall records go, or None when SCPI_STALL_LOG switches the
    logger off."""
    env = os.environ if env is None else env
    value = (env.get(ENV) or '').strip()
    if value.lower() in OFF_WORDS:
        return None
    if value:
        return os.path.expanduser(value)
    return default_log_path(env)


# ---------------------------------------------------------------------------
# the decisions, with no clock, thread, Tk or file of their own
# ---------------------------------------------------------------------------

# A heartbeat stamp is (monotonic s, Tk-thread CPU s, process CPU s); either
# CPU value is None where it could not be read.

Look = collections.namedtuple('Look', 'cpu pcpu load stack threads note')
Look.__doc__ = """What the watchdog saw at one moment of a stall: absolute
CPU readings (Tk thread, whole process), /proc/loadavg, the Tk thread's
stack as (file, line, function) outermost first, the other threads'
innermost frames as (name, (file, line, function)), and a note when part
of it could not be read."""

Sample = collections.namedtuple('Sample',
                                'at cpu pcpu load stack threads note')
Sample.__doc__ = """A Look placed in its stall: `at` is seconds into the
stall, and the CPU values are deltas since the stall began."""

Record = collections.namedtuple('Record',
                                'kind number start end at samples startup')
Record.__doc__ = """One entry for the log. `kind` is 'STALL' (the
heartbeat came back at `end`) or 'STALLING' (still frozen at `at`).
`start` and `end` are heartbeat stamps; `startup` is True when the stall
began before any heartbeat had run."""


def _delta(now, then):
    return None if now is None or then is None else now - then


class _Stall:
    """The stall the watchdog is looking at."""

    def __init__(self, start, number):
        self.start = start          # the last heartbeat before it
        self.number = number
        self.samples = []
        self.plan = 0.0             # seconds in at which to look next
        self.hang_written = False

    def add(self, sample, cap):
        if len(self.samples) < cap:
            self.samples.append(sample)
        else:
            self.samples[-1] = sample           # keep the latest look


class StallTracker:
    """When a stall begins and ends, when to look at the Tk thread, and
    what to write. It is handed the times, so a test can drive it with
    made-up ones.

    `beat` is the heartbeat and runs on the Tk thread. `poll` is the
    watchdog and runs on its own thread. They share `last` (one tuple,
    replaced whole) and `gaps` (a deque); both are safe to hand between
    threads in CPython.
    """

    def __init__(self, stamp, threshold=THRESHOLD_S, hang_s=HANG_S,
                 max_gap_s=SAMPLE_MAX_GAP_S, max_samples=MAX_SAMPLES):
        self.threshold = threshold
        self.hang_s = hang_s
        self.max_gap_s = max_gap_s
        self.max_samples = max_samples
        self.first = self.last = tuple(stamp)
        self.gaps = collections.deque(maxlen=256)
        self.stall = None
        self.count = 0              # stalls seen, numbered from 1
        self.longest = 0.0

    def beat(self, stamp):
        """The heartbeat. A gap over the threshold is queued BEFORE `last`
        moves on, so a watchdog that sees the new stamp always finds the
        gap it closed."""
        stamp = tuple(stamp)
        prev = self.last
        if stamp[0] - prev[0] > self.threshold:
            self.gaps.append((prev, stamp))
        self.last = stamp

    def drain(self):
        """A STALL record for every gap the heartbeat has closed, oldest
        first, carrying the stacks taken while it lasted."""
        out = []
        while self.gaps:
            start, end = self.gaps.popleft()
            st = self.stall
            if st is not None and st.start is start:
                self.stall = None
                number, samples = st.number, tuple(st.samples)
            else:                   # over before the watchdog looked
                self.count += 1
                number, samples = self.count, ()
            self.longest = max(self.longest, end[0] - start[0])
            out.append(Record('STALL', number, start, end, end[0], samples,
                              start is self.first))
        return out

    def poll(self, t, look):
        """The watchdog at monotonic time `t`; `look()` returns a Look at
        the Tk thread now. Returns (records to write, when to poll next)."""
        out = self.drain()
        last = self.last
        if t - last[0] <= self.threshold:
            return out, last[0] + self.threshold
        st = self.stall
        if st is None or st.start is not last:
            self.count += 1
            st = self.stall = _Stall(last, self.count)
        into = t - last[0]
        if into >= st.plan:
            got = look()
            if self.last is last:   # still frozen, so the look is this stall's
                st.add(Sample(into, _delta(got.cpu, last[1]),
                              _delta(got.pcpu, last[2]), got.load, got.stack,
                              got.threads, got.note), self.max_samples)
            while st.plan <= into:
                st.plan = max(1.0, min(st.plan * 2,
                                       st.plan + self.max_gap_s))
        if not st.hang_written and into >= self.hang_s \
                and self.last is last:
            st.hang_written = True
            out.append(Record('STALLING', st.number, last, None, t,
                              tuple(st.samples), last is self.first))
        return out, min(last[0] + st.plan, t + STALL_POLL_S)


# ---------------------------------------------------------------------------
# the record as text
# ---------------------------------------------------------------------------

def _plus(seconds):
    return 'n/a' if seconds is None else f"+{seconds:.2f} s"


def _clock_text(epoch):
    """Local time with milliseconds; run.log uses the same local clock."""
    ms = min(999, int((epoch % 1) * 1000))
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(epoch)) \
        + f".{ms:03d}"


def _span(seconds):
    if seconds >= 3600:
        return f"{seconds / 3600:.2f} h"
    if seconds >= 60:
        return f"{seconds / 60:.1f} min"
    return f"{seconds:.1f} s"


def _short(filename):
    """An app module by its bare name; anything else in full."""
    try:
        if os.path.dirname(os.path.abspath(filename)) == APP_DIR:
            return os.path.basename(filename)
    except Exception:
        pass
    return str(filename)


_SOURCES = {}              # file -> its lines, each file read once, whole


def _source(filename, lineno):
    """Line `lineno` of `filename`, stripped, or ''.

    Not linecache: it reads a file in 8 KB pieces, and every read releases
    the GIL. While the Tk thread computes, the watchdog then waits at least
    a switch interval (5 ms) to get the GIL back, each time. The first
    lines of gui.py and tkinter took 1.1-1.4 s through linecache that way,
    and 0.12-0.18 s with one read per file (measured 2026-10-06, Windows
    11, Python 3.13, against a thread spinning in Python). A record that
    is slow to write makes the watchdog late for the next stall."""
    lines = _SOURCES.get(filename)
    if lines is None:
        try:
            with open(filename, 'rb') as fh:
                lines = fh.read().decode('utf-8', 'replace').splitlines()
        except Exception:
            lines = []
        _SOURCES[filename] = lines
    if isinstance(lineno, int) and 0 < lineno <= len(lines):
        return lines[lineno - 1].strip()[:160]
    return ''


def _frame_lines(stack):
    out = []
    for filename, lineno, func in stack:
        if filename is None:
            out.append(f"    ({func})")
            continue
        out.append(f"    {_short(filename)}:{lineno} in {func}")
        src = _source(filename, lineno)
        if src:
            out.append(f"      {src}")
    return out


def format_record(rec, window, pid, tk_name, opened_t, wall,
                  load_after=None):
    """The text of one Record. `opened_t` is the monotonic time watching
    began and `wall(t)` turns a monotonic time into epoch seconds. The
    first line starts with the local time the stall BEGAN."""
    when = _clock_text(wall(rec.start[0]))
    if rec.kind == 'STALL':
        gap = rec.end[0] - rec.start[0]
        lines = [f"{when} STALL {gap:.2f} s in {window} "
                 f"(pid {pid}, stall {rec.number})"]
    else:
        gap = rec.at - rec.start[0]
        lines = [f"{when} STALLING {gap:.1f} s so far in {window} "
                 f"(pid {pid}, stall {rec.number}): still frozen; a STALL "
                 f"record with the whole duration follows if it recovers"]
    began = f"  began {rec.start[0] - opened_t:.1f} s after the window opened"
    if rec.startup:
        began += " (no heartbeat had run yet: the window was being built)"
    lines.append(began)
    if rec.kind == 'STALL':
        cpu = _delta(rec.end[1], rec.start[1])
        share = (f" = {100.0 * cpu / gap:.0f} % of the gap"
                 if cpu is not None and gap > 0 else "")
        lines.append(f"  Tk thread ({tk_name}) cpu {_plus(cpu)}{share}; "
                     f"whole process cpu "
                     f"{_plus(_delta(rec.end[2], rec.start[2]))}")
        if load_after:
            lines.append(f"  load after: {load_after}")
    if not rec.samples:
        lines.append("  no stack: the window recovered before the watchdog "
                     "looked" if rec.kind == 'STALL'
                     else "  no stack taken yet")
    shown = None
    for s in rec.samples:
        bits = [f"Tk thread cpu {_plus(s.cpu)}", f"process {_plus(s.pcpu)}"]
        if s.load:
            bits.append(f"load {s.load}")
        head = f"  stack at +{s.at:.2f} s ({', '.join(bits)})"
        if not s.stack:
            lines.append(f"{head}: {s.note or 'no stack'}")
            continue
        if s.stack == shown:
            lines.append(f"{head}: unchanged")
        else:
            lines.append(f"{head}, most recent call last:")
            lines.extend(_frame_lines(s.stack))
            shown = s.stack
        if s.note:
            lines.append(f"    ({s.note})")
    first = next((s for s in rec.samples if s.threads), None)
    if first is not None:
        lines.append(f"  other threads at +{first.at:.2f} s:")
        for name, (filename, lineno, func) in first.threads:
            lines.append(f"    {name}: {_short(filename)}:{lineno} in {func}")
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# reading the Tk thread from the watchdog thread
# ---------------------------------------------------------------------------

def _now():
    """A heartbeat stamp. Taken ON the Tk thread, so that thread_time() is
    the Tk thread's own CPU time."""
    try:
        cpu = time.thread_time()
    except Exception:
        cpu = None
    try:
        pcpu = time.process_time()
    except Exception:
        pcpu = None
    return (time.monotonic(), cpu, pcpu)


def _wall(t):
    """Epoch seconds at monotonic time `t`."""
    return time.time() - (time.monotonic() - t)


def _current_frames():
    """sys._current_frames() with the cyclic collector off, as CPython does
    itself from 3.11.12 on.

    Before that the call could hang the whole process: it holds the
    runtime's thread-list lock while it allocates frame objects, an
    allocation can start a collection, the collection can run Python code
    that lets go of the GIL, and a thread that starts or ends then takes
    the GIL and waits for the lock (gh-106883; Python 3.11.12 changelog,
    C API: "Disable GC during the _PyThread_CurrentFrames() and
    _PyThread_CurrentExceptions() calls to avoid the interpreter to
    deadlock"). The bench runs /usr/bin/python3.11 at a patch level not
    recorded yet, and the app starts and ends a thread for every
    background job (gui.py _run_bg). On a fixed Python this costs two
    cheap calls."""
    was_on = gc.isenabled()
    gc.disable()
    try:
        return sys._current_frames()
    finally:
        if was_on:
            gc.enable()


def _stack(frame, limit=MAX_FRAMES):
    """`frame` and its callers as (file, line, function), outermost first.
    Only the innermost `limit` are kept, behind a marker when any were
    cut. Copied out at once, so no frame is kept alive."""
    out = []
    while frame is not None and len(out) < limit:
        code = frame.f_code
        out.append((code.co_filename, frame.f_lineno,
                    getattr(code, 'co_qualname', code.co_name)))
        frame = frame.f_back
    if frame is not None:
        out.append((None, None, 'outer frames cut'))
    out.reverse()
    return out


def _where(frame):
    code = frame.f_code
    return (code.co_filename, frame.f_lineno,
            getattr(code, 'co_qualname', code.co_name))


def _loadavg():
    """/proc/loadavg as one line on Linux, else None."""
    if not sys.platform.startswith('linux'):
        return None
    try:
        with open('/proc/loadavg') as fh:
            return fh.read().strip()
    except OSError:
        return None


class _CpuClock:
    """One thread's CPU time in seconds, readable from any thread."""

    def __init__(self, read, close=None):
        self.read = read
        self._close = close

    def close(self):
        close, self._close = self._close, None
        if close is not None:
            try:
                close()
            except Exception:
                pass


def _windows_thread_clock():
    """GetThreadTimes on the calling thread, through a real handle: the
    GetCurrentThread() pseudo-handle would mean whichever thread asks."""
    import ctypes
    from ctypes import wintypes
    # A private WinDLL, so these prototypes cannot clash with anyone
    # else's use of ctypes.windll.kernel32.
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    u64p = ctypes.POINTER(ctypes.c_ulonglong)
    k32.OpenThread.restype = wintypes.HANDLE
    k32.OpenThread.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.GetThreadTimes.restype = wintypes.BOOL
    k32.GetThreadTimes.argtypes = (wintypes.HANDLE, u64p, u64p, u64p, u64p)
    k32.CloseHandle.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k32.OpenThread(THREAD_QUERY_LIMITED_INFORMATION, False,
                            threading.get_native_id())
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    def read():
        # creation, exit, kernel, user: FILETIMEs, in 100 ns units
        t = [ctypes.c_ulonglong() for _ in range(4)]
        if not k32.GetThreadTimes(handle, *[ctypes.byref(x) for x in t]):
            raise ctypes.WinError(ctypes.get_last_error())
        return (t[2].value + t[3].value) * 1e-7

    return _CpuClock(read, lambda: k32.CloseHandle(handle))


def _cpu_clock():
    """(clock, how): the CALLING thread's CPU time, readable from other
    threads, for the watchdog's looks while a stall lasts. `clock` is None
    where there is no such clock, and `how` then says why. A STALL
    record's CPU over the whole gap does not depend on it: the heartbeat
    reads time.thread_time() on the Tk thread itself, which is the same
    clock on Linux and Windows."""
    try:
        if hasattr(time, 'pthread_getcpuclockid'):
            # It takes the pthread_t, which threading.get_ident() returns
            # on POSIX. NOT the kernel thread id from get_native_id(): glibc
            # follows the argument as a pointer, and that call ended Python
            # with a segmentation fault (Debian under WSL, 2026-10-06).
            clk = time.pthread_getcpuclockid(threading.get_ident())
            time.clock_gettime(clk)                 # works here, or raises
            return (_CpuClock(lambda: time.clock_gettime(clk)),
                    'pthread_getcpuclockid')
        if os.name == 'nt':
            return (_windows_thread_clock(),
                    'GetThreadTimes, about 16 ms resolution')
        return None, f'n/a, no per-thread CPU clock on {sys.platform}'
    except Exception as e:
        return None, f'n/a ({type(e).__name__}: {e})'


# ---------------------------------------------------------------------------
# the log file
# ---------------------------------------------------------------------------

def _open_log(path):
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_BINARY',
                                                               0)
    try:
        return os.open(path, flags, 0o644)
    except FileNotFoundError:
        folder = os.path.dirname(path)
        if not folder:
            raise
        os.makedirs(folder, exist_ok=True)
        return os.open(path, flags, 0o644)


def append_record(path, text, max_bytes=MAX_BYTES):
    """Append `text` to the log at `path` in one write() on a file opened
    for appending, after rotating the log to <path>.1 when it is over
    `max_bytes`. Raises OSError when it cannot write.

    Four system calls when nothing needs doing: like a file read (see
    _source), each one costs the watchdog a GIL switch interval while the
    Tk thread computes. Measured the same way: 41-50 ms, against 71-78 ms
    for makedirs + getsize + open + write + close."""
    data = memoryview(text.encode('utf-8', 'replace'))
    fd = _open_log(path)
    try:
        if os.fstat(fd).st_size > max_bytes:
            os.close(fd)
            fd = None
            try:
                os.replace(path, path + '.1')
            except OSError:
                pass        # another window has it open: rotate next time
            fd = _open_log(path)
        while data:
            n = os.write(fd, data)
            if n <= 0:
                break
            data = data[n:]
    finally:
        if fd is not None:
            os.close(fd)


def _complain(msg):
    """stderr, best effort: the launchers send it to launch.log, and a
    pythonw process has no stderr at all."""
    try:
        if sys.stderr is not None:
            sys.stderr.write(msg if msg.endswith('\n') else msg + '\n')
            sys.stderr.flush()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# one window
# ---------------------------------------------------------------------------

class StallLogger:
    """A StallTracker wired to one window: the heartbeat on its Tk thread,
    the watchdog thread, and the log file. Made by `watch`."""

    def __init__(self, root, window, path):
        self.root = root
        self.window = str(window)
        self.path = path
        self.pid = os.getpid()
        here = threading.current_thread()
        self.tk_ident = here.ident
        self.tk_name = here.name
        self.clock, self.clock_how = _cpu_clock()
        self.tracker = StallTracker(_now())
        self.failed = None          # why the heartbeat stopped, if it did
        self.stopped = False
        self._job = None            # the pending heartbeat's after id
        self._done = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True,
                                       name=f"tk_stall {self.window}")

    def start(self):
        # add='+': the windows bind <Destroy> on their root themselves
        # (Edge Review cancels its pending work there). Never unbound:
        # before Python 3.13, unbind(sequence, funcid) dropped EVERY
        # binding on the sequence, the window's own included. After stop()
        # the handler does nothing.
        self.root.bind('<Destroy>', self._on_destroy, add='+')
        self._job = self.root.after(HEARTBEAT_MS, self._beat)
        self.thread.start()

    def _beat(self):
        """The heartbeat, on the Tk thread: stamp, then come back."""
        self._job = None
        if self.stopped:
            return
        try:
            self.tracker.beat(_now())
            self._job = self.root.after(HEARTBEAT_MS, self._beat)
        except Exception as e:
            # The root is going or gone. Stop watching rather than report
            # the missing heartbeat as a stall that never ends.
            self.failed = f"heartbeat stopped ({type(e).__name__}: {e})"
            self._done.set()

    def _on_destroy(self, ev=None):
        """<Destroy> on the root fires for every child too: act only on
        the root's own."""
        try:
            if ev is not None and ev.widget is not self.root:
                return
            self.stop()
        except Exception:
            pass                    # never into the window's own teardown

    def stop(self, wait_s=1.0):
        """Stop watching; safe to call twice. On the Tk thread it beats
        once more first, so a stall that ends with the window closing (a
        close that waits for a worker freezes the window meanwhile) is
        recorded. Then it waits up to `wait_s` for the watchdog to write
        its last record and the STOP line."""
        if self.stopped:
            return
        self.stopped = True
        _forget(self)
        try:
            if self._job is not None:
                self.root.after_cancel(self._job)
        except Exception:
            pass
        self._job = None
        if threading.get_ident() == self.tk_ident:
            try:
                self.tracker.beat(_now())
            except Exception:
                pass
        self._done.set()
        if self.thread.ident is None:               # never started
            self._close_clock()
        elif self.thread.is_alive() \
                and threading.current_thread() is not self.thread:
            self.thread.join(wait_s)

    def _watch(self):
        """The watchdog thread."""
        try:
            self._write(self._start_line())
            while not self._done.is_set():
                records, wake = self.tracker.poll(time.monotonic(),
                                                  self._look)
                for rec in records:
                    self._write(self._format(rec))
                self._done.wait(max(0.01, wake - time.monotonic() + 0.005))
            for rec in self.tracker.drain():
                self._write(self._format(rec))
            self._write(self._stop_line())
        except Exception as e:
            msg = (f"{_clock_text(time.time())} ERROR {self.window} "
                   f"(pid {self.pid}): the stall logger stopped "
                   f"({type(e).__name__}: {e})\n")
            _complain(msg)
            try:
                append_record(self.path, msg)
            except Exception:
                pass
        finally:
            self._close_clock()

    def _look(self):
        """A Look at the Tk thread, taken on the watchdog thread."""
        stack = threads = cpu = note = None
        frames = top = None
        try:
            frames = _current_frames()
            names = {t.ident: t.name for t in threading.enumerate()}
            mine = threading.get_ident()
            top = frames.get(self.tk_ident)
            if top is None:
                note = "no stack: the Tk thread runs no Python code"
            else:
                stack = _stack(top)
            threads = sorted(((names.get(i, f"thread {i}"), _where(f))
                              for i, f in frames.items()
                              if i not in (self.tk_ident, mine)),
                             key=lambda item: item[0])
        except Exception as e:
            note = f"no stack ({type(e).__name__}: {e})"
        finally:
            frames = top = None
        clock = self.clock
        if clock is not None:
            try:
                cpu = clock.read()
            except Exception as e:
                note = f"Tk-thread cpu unreadable ({type(e).__name__}: {e})"
        try:
            pcpu = time.process_time()
        except Exception:
            pcpu = None
        return Look(cpu, pcpu, _loadavg(), stack, threads, note)

    def _format(self, rec):
        return format_record(rec, self.window, self.pid, self.tk_name,
                             self.tracker.first[0], _wall,
                             _loadavg() if rec.kind == 'STALL' else None)

    def _start_line(self):
        try:
            import version
            ver = 'v' + version.__version__
        except Exception:
            ver = 'version unknown'
        when = _clock_text(_wall(self.tracker.first[0]))
        return (f"{when} START {self.window} (pid {self.pid}): {ver}, "
                f"Python {sys.version.split()[0]} on {sys.platform}; logs "
                f"gaps over {THRESHOLD_S:.2f} s between the {HEARTBEAT_MS} "
                f"ms heartbeats of its Tk thread ({self.tk_name}); "
                f"cpu clock: {self.clock_how}\n")

    def _stop_line(self):
        n = self.tracker.count
        stalls = f"{n} stall{'' if n == 1 else 's'}"
        if self.tracker.longest:
            stalls += f", longest {self.tracker.longest:.2f} s"
        why = f"; {self.failed}" if self.failed else ""
        up = time.monotonic() - self.tracker.first[0]
        return (f"{_clock_text(time.time())} STOP {self.window} "
                f"(pid {self.pid}): watched {_span(up)}; {stalls}{why}\n")

    def _write(self, text):
        try:
            append_record(self.path, text)
        except Exception as e:
            _complain(f"tk_stall: cannot write {self.path} "
                      f"({type(e).__name__}: {e}); the record was:\n{text}")

    def _close_clock(self):
        clock, self.clock = self.clock, None
        if clock is not None:
            clock.close()


# ---------------------------------------------------------------------------
# the entry point
# ---------------------------------------------------------------------------

_ACTIVE = {}                        # id(root) -> the StallLogger watching it
_ACTIVE_LOCK = threading.Lock()


def watching(root):
    """The logger watching `root`, or None."""
    with _ACTIVE_LOCK:
        logger = _ACTIVE.get(id(root))
    return logger if logger is not None and logger.root is root else None


def _forget(logger):
    with _ACTIVE_LOCK:
        if _ACTIVE.get(id(logger.root)) is logger:
            del _ACTIVE[id(logger.root)]


def watch(root, window, path=None):
    """Log the stalls of the window whose Tk root is `root`.

    Call it on the thread that runs that root's mainloop, right after the
    root is made, so that a slow start is caught too. `window` names the
    window in the log; `path`, when given, overrides where the log goes.
    Returns the StallLogger, or None when SCPI_STALL_LOG switches logging
    off or it could not start. One logger per root: asked again, it
    returns the one already watching. It stops by itself when the root is
    destroyed. Never raises.
    """
    try:
        where = log_path()
        if where is None:
            return None
        with _ACTIVE_LOCK:
            have = _ACTIVE.get(id(root))
            if have is not None and have.root is root:
                return have
            logger = StallLogger(root, window, path or where)
            _ACTIVE[id(root)] = logger
        try:
            logger.start()
        except Exception:
            logger.stop(wait_s=0)
            raise
        return logger
    except Exception as e:
        _complain(f"tk_stall: not watching {window!r} "
                  f"({type(e).__name__}: {e})")
        return None
