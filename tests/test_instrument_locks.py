#!/usr/bin/env python3
"""Cross-thread instrument-lock tests (fake transports, no hardware).

Run: .venv/bin/python tests/test_instrument_locks.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import threading
import time

import instruments
from instruments import TekMSO24, _io_lock


class FakeScopeTransport:
    """Write-then-read fake that DETECTS interleaving: VALUE? returns the
    channel most recently programmed by ANY thread."""
    def __init__(self):
        self.ch = None
        self.typ = None

    def write(self, cmd):
        time.sleep(0.001)              # widen the race window
        if cmd.startswith('MEASUREMENT:IMMED:SOURCE CH'):
            self.ch = int(cmd.rsplit('CH', 1)[1])
        elif cmd.startswith('MEASUREMENT:IMMED:TYPE'):
            self.typ = cmd.split()[-1]

    def query(self, cmd):
        time.sleep(0.001)
        assert cmd == 'MEASUREMENT:IMMED:VALUE?'
        return f"{self.ch}.0"          # the value IS the channel it reads


class FakeScope(TekMSO24):
    def __init__(self):                 # no VISA open
        self.inst = None
        self._t = FakeScopeTransport()

    def write(self, command):
        with _io_lock(self):
            self._t.write(command)

    def ask(self, command):
        with _io_lock(self):
            return self._t.query(command)


def test_measure_transactions_never_interleave():
    sc = FakeScope()
    errors = []

    def hammer(ch, n=60):
        for _ in range(n):
            v = sc.measure('MEAN', ch)
            if v != float(ch):
                errors.append((ch, v))

    ts = [threading.Thread(target=hammer, args=(ch,)) for ch in (1, 2, 3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors, f"crossed transactions: {errors[:5]}"


def test_lock_is_reentrant_and_lazy():
    sc = FakeScope()                    # __init__ never made a lock
    lk = _io_lock(sc)
    assert lk is _io_lock(sc)           # stable identity
    with lk:
        with lk:                        # reentrant
            assert sc.measure('MEAN', 2) == 2.0


def _run():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == '__main__':
    _run()
