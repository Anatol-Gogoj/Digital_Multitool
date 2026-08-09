#!/usr/bin/env python3
"""Headless tests for the 4055B flash-drive .bin export (no instrument).

Ground truth is arb_bin_reference_9step.bin -- a known-good lab file the
4055B reads from a flash drive (9-step staircase, EasyWaveX-generated).
Run: .venv/bin/python tests/test_arb_bin.py
"""
# Runnable from anywhere: put the repo root (one level up) on sys.path
# so the app modules import when this file is executed directly.
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import os
import shutil
import struct
import tempfile

import arb_bin
from arb_bin import (BIN_POINTS, FULL_SCALE, build_arb_bin, find_flash_drives,
                     parse_arb_bin, write_arb_bin)

_REFERENCE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'arb_bin_reference_9step.bin')


class _OsWithUnwritable:
    """The `os` module with exactly one directory reported unwritable.

    `os.chmod(dir, 0o555)` was the old way to fake a read-only stick, and
    Windows ignores chmod on DIRECTORIES entirely -- the "read-only" stick
    stayed writable and `find_flash_drives` correctly returned both, which
    is one of the four failures long filed as environmental (2026-08-09).

    Swapping the directory for a file would turn the suite green for the
    wrong reason: `arb_bin.py:84` is `if not os.path.isdir(path) or not
    os.access(path, os.W_OK)`, so a file trips the isdir half and the
    writability half -- the thing under test -- never runs. Faking the
    probe itself keeps the real branch exercised on every platform.

    `arb_bin` does a plain module-level `import os`, so `arb_bin.os` is a
    rebindable name. The real `os` module is never mutated.
    """

    def __init__(self, blocked):
        self._blocked = os.path.abspath(blocked)

    def __getattr__(self, name):        # everything else is the real thing
        return getattr(os, name)

    def access(self, path, mode):
        if mode & os.W_OK and os.path.abspath(path) == self._blocked:
            return False
        return os.access(path, mode)


def test_build_size_and_encoding():
    blob = build_arb_bin([0.0, 1.0, -1.0, 0.0])
    assert len(blob) == BIN_POINTS * 2 == 32768, len(blob)
    vals = struct.unpack(f'<{BIN_POINTS}h', blob)
    assert max(vals) == FULL_SCALE and min(vals) == -FULL_SCALE
    # first sample exact, endpoints preserved by the resampler
    assert vals[0] == 0 and vals[-1] == 0


def test_build_normalizes_overscale():
    blob = build_arb_bin([2.0, -2.0, 1.0], points=3)
    assert struct.unpack('<3h', blob) == (32767, -32767, 16384)


def test_parse_roundtrip_values():
    blob = struct.pack('<4h', 0, 32767, -32767, 16384)
    vals = parse_arb_bin(blob)
    assert vals[0] == 0.0 and vals[1] == 1.0 and vals[2] == -1.0
    assert abs(vals[3] - 0.5) < 1e-4


def test_parse_rejects_bad_input():
    for bad in (b'', b'\x00'):
        try:
            parse_arb_bin(bad)
            assert False, f"must raise on {bad!r}"
        except ValueError:
            pass


def test_reference_file_structure():
    # The lab file: headerless, 16384 samples, a 9-plateau staircase from
    # -FS to +FS in FS/4 steps.
    with open(_REFERENCE, 'rb') as f:
        blob = f.read()
    assert len(blob) == 32768
    vals = struct.unpack(f'<{BIN_POINTS}h', blob)
    plateaus = [vals[0]]
    for a, b in zip(vals, vals[1:]):
        if b != a:
            plateaus.append(b)
    assert len(plateaus) == 9, plateaus
    assert plateaus[0] == -FULL_SCALE and plateaus[-1] == FULL_SCALE
    assert plateaus[4] == 0
    # monotone rising staircase
    assert all(b > a for a, b in zip(plateaus, plateaus[1:]))


def test_reference_roundtrip_byte_identical():
    # parse -> rebuild must reproduce the lab file byte-for-byte
    with open(_REFERENCE, 'rb') as f:
        original = f.read()
    rebuilt = build_arb_bin(parse_arb_bin(original))
    assert rebuilt == original, "rebuild must be byte-identical"


def test_write_arb_bin():
    # tempfile, not a '/tmp/...' literal: on Windows that abspaths to
    # C:\tmp and the test depends on a directory nobody created.
    fd, tmp = tempfile.mkstemp(prefix='arb_bin_', suffix='.bin')
    os.close(fd)
    try:
        n = write_arb_bin(tmp, [0.0, 1.0, 0.0, -1.0])
        with open(tmp, 'rb') as f:
            blob = f.read()
        assert n == len(blob) == BIN_POINTS * 2
    finally:
        os.unlink(tmp)


def test_find_flash_drives():
    root = tempfile.mkdtemp(prefix='arb_bin_media_')
    ro = os.path.join(root, 'RO_STICK')
    os.makedirs(os.path.join(root, 'STICK'), exist_ok=True)
    os.makedirs(ro, exist_ok=True)
    real_os = arb_bin.os
    arb_bin.os = _OsWithUnwritable(ro)   # see the class docstring
    try:
        found = find_flash_drives(roots=[root], require_mount=False)
        assert found == [os.path.join(root, 'STICK')], found
        # missing roots are silently skipped
        assert find_flash_drives(roots=['/nonexistent_xyz']) == []
    finally:
        arb_bin.os = real_os
        shutil.rmtree(root, ignore_errors=True)


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
