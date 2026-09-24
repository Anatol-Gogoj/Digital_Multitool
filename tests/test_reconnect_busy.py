#!/usr/bin/env python3
"""Headless tests for Reconnect while another connect is in flight (no
hardware, no Tk).

The gap (found 2026-09-24 by the adversarial review of PR #335, verified
on 78315cc): `_reconnect` nulled the instrument handle and set its tab's
label to "Connecting..." BEFORE `_run_bg` looked at the 'connect' busy
key. With another tab's Reconnect still in flight, `_run_bg` refused and
the job never ran. Nothing closed the old session or opened a new one, the
handle stayed None and the label stayed at "Connecting...". Until a later
Reconnect succeeded, the app treated the instrument as gone: with the
signal generator, Output refused and window close skipped the outputs-OFF
shutdown, and a LIVE run refused to start. (During the start-up
auto-connect the same refusal did no lasting harm: the handle was still
None, and auto-connect's result overwrote both.) What is pinned here:

* a refused Reconnect leaves the handle, its session and the tab's label
  as they were, opens nothing, and says why in the status bar with the
  note `_run_bg` itself gives -- on every tab;
* the LIVE-run lock still answers an SG Reconnect first;
* a Reconnect with nothing else in flight is unchanged: the handle is None
  before the worker runs, the old session closes before the new one opens,
  and the handle, the label and the sync follow the result;
* once the other connect lands, the refused Reconnect works on a retry.

Everything drives the REAL `_reconnect` and `_run_bg` on a Tk-free stub
app. `_run_bg` runs its worker on a real thread; the stub root queues the
completion, and the test runs it, standing in for the Tk main loop.

Run: .venv/bin/python tests/test_reconnect_busy.py
"""
import contextlib as _contextlib
import os as _os
import queue as _queue
import sys as _sys
import threading as _threading
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import gui  # noqa: E402

G = gui.InstrumentControlGUI
KEYS = ('lcr', 'scope', 'sg', 'psu', 'dmm')
LOCK = 'Channel in use — LIVE HV run'
BUSY_NOTE = 'Still working on the previous connect operation...'
CONNECTING = ('Connecting...', '#b36b00')


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
    resource = 'USB0::0xF4EC::0x1101::FAKE::INSTR'

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
    message)."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if not name.startswith('show'):
            raise AttributeError(name)
        return lambda title, message, **_kw: self.calls.append(
            (name, title, message))


class _App:
    """Just enough app for Reconnect: the real _reconnect, _run_bg and LIVE
    lock, with every instrument connected and every tab's label saying so.
    `started` records each _run_bg call as (busy key, did a job start?)."""
    _reconnect = G._reconnect
    _sg_live_locked = G._sg_live_locked
    _transport = staticmethod(G._transport)

    def __init__(self, live=None):
        self.root = _Root()
        self.status_bar = _Label()
        self._bg_busy = set()
        self._sldea_live_ch = live       # None = no run, or a DRY run
        self.started = []
        for key in KEYS:
            setattr(self, key, _FakeInst(f'OLD {key}'))
            setattr(self, f'{key}_status',
                    _Label(f'Connected (USB): OLD {key}', 'green'))

    def _run_bg(self, work, done, busy=None, quiet=False):
        started = G._run_bg(self, work, done, busy=busy, quiet=quiet)
        self.started.append((busy, started))
        return started

    def jobs_started(self):
        return sum(1 for _, started in self.started if started)


@_contextlib.contextmanager
def _patched():
    """A recording messagebox, and the Linux gate opened so Reconnect runs
    on any OS."""
    mb = _MB()
    saved = gui.messagebox, gui.INSTRUMENTS_SUPPORTED
    gui.messagebox, gui.INSTRUMENTS_SUPPORTED = mb, True
    try:
        yield mb
    finally:
        gui.messagebox, gui.INSTRUMENTS_SUPPORTED = saved


# --------------------------------------------------------------------------
# Refused: another connect is in flight
# --------------------------------------------------------------------------

def test_a_refused_reconnect_leaves_the_instrument_as_it_was():
    """Every tab: with a connect already in flight (the start-up
    auto-connect, or another tab's Reconnect), Reconnect keeps the handle
    it had with its session open, keeps its label, and opens nothing. The
    status bar says why; there is no dialog."""
    for key in KEYS:
        with _patched() as mb:
            app = _App()
            app._bg_busy.add('connect')
            inst, label = getattr(app, key), getattr(app, f'{key}_status')
            before = label.state()
            opened = []
            app._reconnect(key, lambda: opened.append(key), label)
            assert getattr(app, key) is inst, f"{key}: the handle was dropped"
            assert not inst.closed, f"{key}: its session was closed"
            assert label.state() == before, (key, label.state())
            assert app.status_bar.text == BUSY_NOTE, app.status_bar.text
            assert app.jobs_started() == 0, app.started
            assert opened == [] and app.root.pending.empty()
            assert app._bg_busy == {'connect'}, app._bg_busy
            assert mb.calls == [], mb.calls


def test_the_refusal_note_is_the_one_run_bg_gives():
    """Word for word: one refusal, one wording, whichever check says it."""
    app = _App()
    app._bg_busy.add('connect')
    assert G._run_bg(app, lambda: None, lambda _r, _e: None,
                     busy='connect') is False
    assert app.status_bar.text == BUSY_NOTE, app.status_bar.text


def test_a_reconnect_refused_behind_another_tab_works_once_that_lands():
    """The case that did the damage: the scope's Reconnect is still opening
    its session when the SG's Reconnect is pressed. The SG keeps its working
    handle, and once the scope has landed the SG's Reconnect goes through."""
    with _patched() as mb:
        app = _App()
        release = _threading.Event()

        def slow_scope():
            assert release.wait(5), "the test never released the scope"
            return _FakeInst('NEW scope')

        app._reconnect('scope', slow_scope, app.scope_status)
        assert app.scope is None and app.scope_status.state() == CONNECTING
        sg, before = app.sg, app.sg_status.state()
        app._reconnect('sg', lambda: _FakeInst('NEW sg'), app.sg_status)
        assert app.sg is sg and not sg.closed, "the SG handle was dropped"
        assert app.sg_status.state() == before, app.sg_status.state()
        assert app.status_bar.text == BUSY_NOTE, app.status_bar.text

        release.set()
        app.root.pump()                  # the scope's connect lands
        assert app.scope.idn == 'NEW scope' and app._bg_busy == set()
        assert app.sg is sg, "the scope's result touched the SG"

        app._reconnect('sg', lambda: _FakeInst('NEW sg'), app.sg_status)
        app.root.pump()
        assert sg.closed and app.sg.idn == 'NEW sg'
        assert app.sg_status.state() == ('Connected (USB): NEW sg', 'green')
        assert app.jobs_started() == 2 and mb.calls == [], mb.calls


def test_a_second_press_on_the_same_tab_leaves_the_first_to_land():
    """Reconnect pressed twice: the second press changes nothing, and the
    first one still lands."""
    with _patched() as mb:
        app = _App()
        release = _threading.Event()
        opened = []

        def factory():
            assert release.wait(5), "the test never released the LCR"
            opened.append('lcr')
            return _FakeInst('NEW lcr')

        old = app.lcr
        app._reconnect('lcr', factory, app.lcr_status)
        app._reconnect('lcr', factory, app.lcr_status)
        assert app.lcr is None and app.lcr_status.state() == CONNECTING
        assert app.status_bar.text == BUSY_NOTE, app.status_bar.text
        assert app.jobs_started() == 1, app.started

        release.set()
        app.root.pump()
        assert opened == ['lcr'] and old.closed and app.lcr.idn == 'NEW lcr'
        assert app.lcr_status.state() == ('Connected (USB): NEW lcr', 'green')
        assert app.root.pending.empty() and mb.calls == [], mb.calls


# --------------------------------------------------------------------------
# The LIVE-run lock answers first
# --------------------------------------------------------------------------

def test_the_live_lock_still_answers_an_sg_reconnect_first():
    """During a LIVE run an SG Reconnect gets the lock's warning, with or
    without a connect in flight, and never the busy note: the lock is the
    reason that matters (audit 2026-07-25, C1)."""
    for busy in (set(), {'connect'}):
        with _patched() as mb:
            app = _App(live=2)
            app._bg_busy.update(busy)
            sg, before = app.sg, app.sg_status.state()
            app._reconnect('sg', lambda: _FakeInst('NEW sg'), app.sg_status)
            assert app.sg is sg and not sg.closed
            assert app.sg_status.state() == before, app.sg_status.state()
            assert app.started == [] and app.status_bar.text is None
            [(kind, title, msg)] = mb.calls
            assert (kind, title) == ('showwarning', LOCK), mb.calls
            assert 'SG CH2 is driving the Trek' in msg, msg


# --------------------------------------------------------------------------
# Nothing in flight: unchanged
# --------------------------------------------------------------------------

def test_a_reconnect_with_nothing_in_flight_goes_ahead_as_before():
    """The handle is None before the worker runs ("nothing may use the
    handle meanwhile"), and the old session is closed before the new one
    opens. Then come the new handle, a Connected label and the sync, and
    the busy key is freed."""
    with _patched() as mb:
        app = _App()
        old, seen, synced = app.psu, [], []

        def factory():                   # runs on the worker thread
            seen.append((app.psu, old.closed))
            return _FakeInst('NEW psu')

        app._reconnect('psu', factory, app.psu_status,
                       sync=lambda: synced.append(app.psu.idn))
        assert app.started == [('connect', True)], app.started
        assert app.psu is None and app.psu_status.state() == CONNECTING
        app.root.pump()                  # the worker's completion
        assert seen == [(None, True)], seen
        assert app.psu.idn == 'NEW psu' and old.closed
        assert app.psu_status.state() == ('Connected (USB): NEW psu', 'green')
        assert synced == ['NEW psu'] and app._bg_busy == set()
        assert mb.calls == [] and app.status_bar.text is None


def test_a_failed_reconnect_still_reports_the_error():
    """A Reconnect that RAN and failed leaves no handle, and says so in red
    with a dialog. A refused one never ran, so it leaves things as they
    were."""
    with _patched() as mb:
        app = _App()
        old = app.dmm

        def factory():
            raise RuntimeError('DMM not reachable at 10.0.0.9:45454')

        app._reconnect('dmm', factory, app.dmm_status)
        app.root.pump()
        assert old.closed and app.dmm is None
        assert app.dmm_status.state() == (
            'Error: DMM not reachable at 10.0.0.9:45454', 'red')
        assert mb.calls == [('showerror', 'Connection Error',
                             'DMM not reachable at 10.0.0.9:45454')], mb.calls
        assert app._bg_busy == set()


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
