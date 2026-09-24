#!/usr/bin/env python3
"""Headless tests for the scope's Reconnect during a LIVE SLDEA run (no
hardware, no Tk).

The gap (found 2026-09-24 by the adversarial review of PR #336): the LIVE
lock refuses only the signal generator's Reconnect. A LIVE run's worker
reads `self.scope` on every monitor tick -- the breakdown watchdog, the
telemetry row, each snapshot's kV/uA -- and a scope Reconnect sets that
handle to None, then closes the session and opens a new one on a worker
thread. Until the new session is up the watchdog cannot trip; if the
connect fails it stays blind until a later Reconnect succeeds. The run
logs "CURRENT MONITORING LOST" after 10 s and carries on (policy
2026-07-25).

Reconnect is also how monitoring comes back after a link drop, so the
owner's decision of 2026-09-24 is to ASK, default No, rather than refuse
as the SG does. What is pinned here:

* during a LIVE run with a scope connected, the scope's Reconnect asks
  first, before the handle, its session or the label is touched; No
  leaves everything as it was, and the question names what goes blind;
* Yes goes ahead exactly as a Reconnect always has, and says so in the
  run log;
* the question runs the event loop, so a connect that started meanwhile
  still refuses with `_run_bg`'s own note, and the handle stays; a run
  that ended meanwhile gets no log line;
* the existing checks answer first: the Linux gate, and a connect already
  in flight (PR #336's guard);
* no question when nothing can be lost: no run, a DRY run, no scope
  connected (so the retry after a failed connect goes straight through),
  or another tab's Reconnect.

Everything drives the REAL `_reconnect` and `_run_bg` on a Tk-free stub
app, as tests/test_reconnect_busy.py does. `_run_bg` runs its worker on a
real thread; the stub root queues the completion, and the test runs it,
standing in for the Tk main loop.

Run: .venv/bin/python tests/test_scope_reconnect_live.py
"""
import contextlib as _contextlib
import os as _os
import queue as _queue
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import gui  # noqa: E402

G = gui.InstrumentControlGUI
KEYS = ('lcr', 'scope', 'sg', 'psu', 'dmm')
ASK = 'Scope in use — LIVE HV run'
BUSY_NOTE = 'Still working on the previous connect operation...'
CONNECTING = ('Connecting...', '#b36b00')
CONNECTED = ('Connected (USB): OLD scope', 'green')


class _Label:
    """tk.Label stand-in: config() records the text and the colour."""

    def __init__(self, text=None, fg=None):
        self.text, self.fg = text, fg

    def config(self, text=None, fg=None, **_kw):
        if text is not None:
            self.text = text
        if fg is not None:
            self.fg = fg

    def state(self):
        return self.text, self.fg


class _FakeInst:
    """An instrument handle: an identity, and a session that can close."""
    resource = 'USB0::0x0699::0x0105::FAKE::INSTR'

    def __init__(self, idn):
        self.idn = idn
        self.closed = False

    def close(self):
        self.closed = True


class _Root:
    """Tk root stand-in. A worker's root.after(0, finish) lands in a queue;
    pump() runs the next one on the calling thread, as the Tk main loop
    would."""

    def __init__(self):
        self.pending = _queue.Queue()

    def after(self, _ms, fn):
        self.pending.put(fn)

    def pump(self):
        self.pending.get(timeout=5)()


class _MB:
    """tkinter.messagebox stand-in: records every dialog as (kind, title,
    message, kw). askyesno gives the scripted answer; `during`, if set,
    runs while the question is up -- the event loop a real dialog runs."""

    def __init__(self, answer=None, during=None):
        self.answer, self.during = answer, during
        self.calls = []

    def askyesno(self, title, message, **kw):
        self.calls.append(('askyesno', title, message, kw))
        if self.answer is None:
            raise AssertionError(f"unexpected question: {title!r}")
        if self.during is not None:
            self.during()
        return self.answer

    def __getattr__(self, name):
        if not name.startswith('show'):
            raise AttributeError(name)
        return lambda title, message, **kw: self.calls.append(
            (name, title, message, kw))


class _App:
    """Just enough app for Reconnect: the real _reconnect, _run_bg and SG
    lock, with every instrument connected and every tab's label saying so.
    `live` is the SG channel a LIVE run drives (None: no run, or a DRY
    one). `started` records each _run_bg call as (busy key, did a job
    start?); `log` is the SLDEA run log."""
    _reconnect = G._reconnect
    _sg_live_locked = G._sg_live_locked
    _transport = staticmethod(G._transport)

    def __init__(self, live=None, running=None):
        self.root = _Root()
        self.status_bar = _Label()
        self._bg_busy = set()
        self._sldea_live_ch = live
        self._sldea_running = live is not None if running is None \
            else running
        self.started, self.log = [], []
        for key in KEYS:
            setattr(self, key, _FakeInst(f'OLD {key}'))
            setattr(self, f'{key}_status',
                    _Label(f'Connected (USB): OLD {key}', 'green'))

    def _run_bg(self, work, done, busy=None, quiet=False):
        started = G._run_bg(self, work, done, busy=busy, quiet=quiet)
        self.started.append((busy, started))
        return started

    def _sldea_log(self, msg):
        self.log.append(msg)

    def jobs_started(self):
        return sum(1 for _, started in self.started if started)

    def reconnect_scope(self, factory):
        """The Oscilloscope tab's Reconnect, with a stand-in for TekMSO24."""
        self._reconnect('scope', factory, self.scope_status)


@_contextlib.contextmanager
def _patched(mb, supported=True):
    """The messagebox stand-in, and the Linux gate opened so Reconnect runs
    on any OS."""
    saved = gui.messagebox, gui.INSTRUMENTS_SUPPORTED
    gui.messagebox, gui.INSTRUMENTS_SUPPORTED = mb, supported
    try:
        yield mb
    finally:
        gui.messagebox, gui.INSTRUMENTS_SUPPORTED = saved


def _questions(mb):
    return [c for c in mb.calls if c[0] == 'askyesno']


def _assert_untouched(app, scope):
    """The scope handle, its session and its label as they were, and no
    job started."""
    assert app.scope is scope, "the handle was dropped"
    assert not scope.closed, "its session was closed"
    assert app.scope_status.state() == CONNECTED, app.scope_status.state()
    assert app.jobs_started() == 0, app.started
    assert app.root.pending.empty()


# --------------------------------------------------------------------------
# A LIVE run, a scope connected: the question
# --------------------------------------------------------------------------

def test_no_leaves_the_scope_as_it_was():
    """The default answer. Nothing is touched: the handle and its session,
    the label, the busy set, the status bar, the run log."""
    with _patched(_MB(answer=False)) as mb:
        app = _App(live=1)
        scope, opened = app.scope, []
        app.reconnect_scope(lambda: opened.append(1))
        _assert_untouched(app, scope)
        assert opened == [] and app._bg_busy == set()
        assert app.status_bar.text is None and app.log == []
        [(kind, title, _msg, kw)] = mb.calls
        assert (kind, title) == ('askyesno', ASK), mb.calls
        assert kw == {'default': 'no'}, kw


def test_the_question_comes_before_anything_is_touched():
    """While the question is up, the run still has its scope: the handle,
    the session and the label are the old ones."""
    seen = []
    app = _App(live=1)
    scope = app.scope

    def during():
        seen.append((app.scope is scope, scope.closed,
                     app.scope_status.state(), app.jobs_started()))

    with _patched(_MB(answer=False, during=during)):
        app.reconnect_scope(lambda: _FakeInst('NEW scope'))
    assert seen == [(True, False, CONNECTED, 0)], seen


def test_the_question_says_what_goes_blind():
    """The operator decides on what the question says, so it has to say it:
    the watchdog cannot trip, a failed connect lasts, the run keeps going,
    and the safe alternative."""
    with _patched(_MB(answer=False)) as mb:
        _App(live=2).reconnect_scope(lambda: _FakeInst('NEW scope'))
    [(_kind, _title, msg, _kw)] = mb.calls
    for phrase in ('LIVE SLDEA run is reading this scope',
                   'breakdown watchdog', 'watchdog cannot trip',
                   'If the connect fails', 'until a Reconnect succeeds',
                   'The run keeps going either way', 'stopped answering',
                   'abort the run on the SLDEA tab first',
                   'Reconnect the scope now?'):
        assert phrase in msg, (phrase, msg)


def test_yes_reconnects_as_before_and_says_so_in_the_run_log():
    """Once confirmed, the path is the one every Reconnect takes: the
    handle is None before the worker runs, the old session closes before
    the new one opens, then the new handle, a Connected label, and the busy
    key freed. The run log records why the monitor readings have a gap."""
    with _patched(_MB(answer=True)) as mb:
        app = _App(live=1)
        old, seen = app.scope, []

        def factory():                   # runs on the worker thread
            seen.append((app.scope, old.closed))
            return _FakeInst('NEW scope')

        app.reconnect_scope(factory)
        assert app.started == [('connect', True)], app.started
        assert app.scope is None and app.scope_status.state() == CONNECTING
        assert len(app.log) == 1, app.log
        assert app.log[0].startswith('⚠ scope Reconnect during the LIVE run '
                                     '(confirmed)'), app.log
        app.root.pump()                  # the worker's completion
        assert seen == [(None, True)], seen
        assert app.scope.idn == 'NEW scope' and old.closed
        assert app.scope_status.state() == (
            'Connected (USB): NEW scope', 'green')
        assert app._bg_busy == set() and app.status_bar.text is None
        assert [c[:2] for c in mb.calls] == [('askyesno', ASK)], mb.calls


def test_a_connect_started_during_the_question_still_refuses():
    """The dialog runs the event loop, so the busy check before it is stale
    by the time the answer comes. A connect that started meanwhile must
    still refuse, with _run_bg's own note -- dropping the handle behind it
    is the bug PR #336 fixed."""
    app = _App(live=1)
    scope = app.scope
    with _patched(_MB(answer=True,
                      during=lambda: app._bg_busy.add('connect'))) as mb:
        app.reconnect_scope(lambda: _FakeInst('NEW scope'))
    _assert_untouched(app, scope)
    assert app.status_bar.text == BUSY_NOTE, app.status_bar.text
    assert app._bg_busy == {'connect'} and app.log == [], app.log
    assert [c[0] for c in mb.calls] == ['askyesno'], mb.calls


def test_a_run_that_ends_during_the_question_logs_nothing():
    """The run finished while the question was up (_sldea_finished ran in
    the dialog's event loop). Yes still reconnects -- the operator asked for
    it -- but there is no run left to write "during the LIVE run" into."""
    app = _App(live=1)

    def run_ends():
        app._sldea_live_ch, app._sldea_running = None, False

    with _patched(_MB(answer=True, during=run_ends)):
        old = app.scope
        app.reconnect_scope(lambda: _FakeInst('NEW scope'))
        app.root.pump()
    assert old.closed and app.scope.idn == 'NEW scope', app.scope
    assert app.log == [], app.log


def test_the_second_busy_note_is_the_one_run_bg_gives():
    """Word for word, as PR #336 pins for the first one."""
    app = _App()
    app._bg_busy.add('connect')
    assert G._run_bg(app, lambda: None, lambda _r, _e: None,
                     busy='connect') is False
    assert app.status_bar.text == BUSY_NOTE, app.status_bar.text


def test_a_failed_connect_after_yes_leaves_the_retry_unasked():
    """Yes, then the connect fails: no handle, the error in red with its
    dialog -- the run is blind now, which the question said. A retry has
    nothing left to lose, so it goes straight through, and monitoring is
    back once it lands."""
    with _patched(_MB(answer=True)) as mb:
        app = _App(live=1)
        old = app.scope

        def unreachable():
            raise RuntimeError('TekMSO24: no device found')

        app.reconnect_scope(unreachable)
        app.root.pump()
        assert old.closed and app.scope is None
        assert app.scope_status.state() == (
            'Error: TekMSO24: no device found', 'red')
        assert [c[:2] for c in mb.calls] == [
            ('askyesno', ASK), ('showerror', 'Connection Error')], mb.calls
        assert app._bg_busy == set() and len(app.log) == 1, app.log

        app.reconnect_scope(lambda: _FakeInst('NEW scope'))
        app.root.pump()
        assert app.scope.idn == 'NEW scope', app.scope
        assert len(_questions(mb)) == 1, mb.calls   # the retry never asked
        assert len(app.log) == 1, app.log
        assert app.jobs_started() == 2, app.started


# --------------------------------------------------------------------------
# The existing checks answer first
# --------------------------------------------------------------------------

def test_a_connect_in_flight_answers_before_the_question():
    """PR #336's guard comes first: with a connect already running, the
    busy note, no question, and the scope left alone."""
    with _patched(_MB()) as mb:           # a question would fail the test
        app = _App(live=1)
        app._bg_busy.add('connect')
        scope = app.scope
        app.reconnect_scope(lambda: _FakeInst('NEW scope'))
        _assert_untouched(app, scope)
        assert app.status_bar.text == BUSY_NOTE and mb.calls == [], mb.calls
        assert app.log == [], app.log


def test_the_linux_gate_answers_before_the_question():
    """Off the bench (Windows) Reconnect only says it is Linux-only."""
    with _patched(_MB(), supported=False) as mb:
        app = _App(live=1)
        scope = app.scope
        app.reconnect_scope(lambda: _FakeInst('NEW scope'))
        _assert_untouched(app, scope)
        assert [c[:2] for c in mb.calls] == [('showinfo', 'Linux only')]


def test_the_sg_is_still_refused_not_asked():
    """The SG's Reconnect keeps its outright refusal: the run drives the
    Trek through that session (audit 2026-07-25, C1)."""
    with _patched(_MB()) as mb:
        app = _App(live=2)
        sg = app.sg
        app._reconnect('sg', lambda: _FakeInst('NEW sg'), app.sg_status)
        assert app.sg is sg and not sg.closed and app.started == []
        assert [c[:2] for c in mb.calls] == [
            ('showwarning', 'Channel in use — LIVE HV run')], mb.calls


# --------------------------------------------------------------------------
# Nothing to lose: no question
# --------------------------------------------------------------------------

def _goes_straight_through(app, key='scope'):
    """Reconnect `key` with no dialog at all, and land it."""
    with _patched(_MB()) as mb:           # a question would fail the test
        old = getattr(app, key)
        app._reconnect(key, lambda: _FakeInst(f'NEW {key}'),
                       getattr(app, f'{key}_status'))
        assert app.started == [('connect', True)], (key, app.started)
        app.root.pump()
        assert getattr(app, key).idn == f'NEW {key}', key
        if old is not None:
            assert old.closed, key
        assert mb.calls == [] and app.log == [], (key, mb.calls, app.log)


def test_no_run_no_question():
    _goes_straight_through(_App())


def test_a_dry_run_no_question():
    """A DRY run claims no channel (_sldea_live_ch stays None): it is the
    rig check, with no HV and no watchdog, as the SG lock decided."""
    _goes_straight_through(_App(live=None, running=True))


def test_no_scope_connected_no_question():
    """A LIVE run that started without a scope, or whose scope Reconnect
    failed: there is no session to close and no reading to lose."""
    app = _App(live=1)
    app.scope = None
    _goes_straight_through(app)


def test_the_other_tabs_reconnect_unasked_during_a_live_run():
    """The question is the scope's alone: the LCR, the DC supply and the
    DMM reconnect during a LIVE run as they always have."""
    for key in ('lcr', 'psu', 'dmm'):
        _goes_straight_through(_App(live=1), key)


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = []
    for fn in fns:
        try:
            fn()
        except Exception:
            failed.append((fn.__name__, traceback.format_exc()))
            print(f"FAIL {fn.__name__}")
            continue
        print(f"ok  {fn.__name__}")
    if not failed:
        print(f"\n{len(fns)} tests passed")
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
