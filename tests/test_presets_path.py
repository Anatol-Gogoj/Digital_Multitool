#!/usr/bin/env python3
"""Headless tests for the presets fallback (share-down resilience).

Regression target: on 2026-07-20 the shared drive dropped mid-session and
"Save to Library" raised OSError [Errno 112] Host is down: 'presets',
losing the user's waveform. An unwritable presets directory must now
degrade to a local copy instead of raising.

Run: .venv/bin/python tests/test_presets_path.py
"""
# Runnable from anywhere: put the repo root (one level up) on sys.path
# so the app modules import when this file is executed directly.
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import os
import shutil
import tempfile

import presets_path


def kill_dir(path):
    """Make every write under `path` fail, on every platform.

    `os.chmod(path, 0o555)` was the old way to fake a dead share, and
    Windows ignores chmod on DIRECTORIES entirely -- the "unreachable"
    share stayed perfectly writable, so five cases in this file and one in
    test_camera_controls.py failed for that single reason and were filed as
    environmental (2026-08-09).

    Replacing the directory with a regular FILE of the same name fails
    everywhere instead. `writable_path` probes with
    `os.makedirs(target, exist_ok=True)` followed by an `open()`
    (presets_path.py:73-76), and against a file that raises an OSError
    subclass on both platforms -- FileExistsError when the probe target IS
    the file, NotADirectoryError when it is underneath one -- which is
    exactly what presets_path.py:78 already catches.
    """
    shutil.rmtree(path)
    open(path, 'wb').close()


def revive_dir(path):
    """Undo `kill_dir`: the share comes back, empty."""
    if os.path.isfile(path):
        os.remove(path)
    os.makedirs(path, exist_ok=True)


def _sandbox():
    """(root, share_dir, restore_fn) with LOCAL_FALLBACK pointed at tmp."""
    root = tempfile.mkdtemp(prefix='presets_path_')
    share = os.path.join(root, 'share', 'presets')
    os.makedirs(share)
    original = presets_path.LOCAL_FALLBACK
    presets_path.LOCAL_FALLBACK = os.path.join(root, 'local', 'presets')
    presets_path.clear_note()

    def restore():
        presets_path.LOCAL_FALLBACK = original
        presets_path.clear_note()
        for dirpath, dirnames, _files in os.walk(root):
            for d in [dirpath] + [os.path.join(dirpath, x) for x in dirnames]:
                try:
                    os.chmod(d, 0o755)
                except OSError:
                    pass
        shutil.rmtree(root, ignore_errors=True)
    return root, share, restore


def test_writable_path_passes_through_when_healthy():
    _root, share, restore = _sandbox()
    try:
        target = os.path.join(share, 'siggen_presets.json')
        assert presets_path.writable_path(target) == target
        assert presets_path.fallback_note() is None, "healthy write = no note"
        # the probe file must not be left behind
        assert os.listdir(share) == []
    finally:
        restore()


def test_writable_path_falls_back_when_share_is_dead():
    _root, share, restore = _sandbox()
    try:
        kill_dir(share)                             # simulate unwritable share
        target = os.path.join(share, 'siggen_presets.json')
        got = presets_path.writable_path(target)
        assert got != target, "must not hand back the unwritable path"
        assert got.startswith(presets_path.LOCAL_FALLBACK), got
        assert os.path.basename(got) == 'siggen_presets.json'
        note = presets_path.fallback_note()
        assert note and 'local copy' in note, note
    finally:
        restore()


def test_writable_path_dir_mode():
    _root, share, restore = _sandbox()
    try:
        arb = os.path.join(share, 'arb')
        assert presets_path.writable_path(arb, is_dir=True) == arb
        shutil.rmtree(arb)
        kill_dir(share)                             # creation must now fail
        got = presets_path.writable_path(arb, is_dir=True)
        assert got == os.path.join(presets_path.LOCAL_FALLBACK, 'arb'), got
        assert os.path.isdir(got), "fallback dir must be created"
    finally:
        restore()


def test_readable_path_prefers_share_then_mirror():
    _root, share, restore = _sandbox()
    try:
        primary = os.path.join(share, 'bench_profiles.json')
        # neither exists -> unchanged, so callers keep normal missing-file paths
        assert presets_path.readable_path(primary) == primary
        # only the local mirror exists -> use it
        os.makedirs(presets_path.LOCAL_FALLBACK, exist_ok=True)
        mirror = os.path.join(presets_path.LOCAL_FALLBACK,
                              'bench_profiles.json')
        open(mirror, 'w').close()
        assert presets_path.readable_path(primary) == mirror
        # share copy exists too -> the share wins
        open(primary, 'w').close()
        assert presets_path.readable_path(primary) == primary
    finally:
        restore()


def test_listable_dir():
    _root, share, restore = _sandbox()
    try:
        arb = os.path.join(share, 'arb')
        os.makedirs(arb)
        assert presets_path.listable_dir(arb) == arb
        shutil.rmtree(arb)
        mirror = os.path.join(presets_path.LOCAL_FALLBACK, 'arb')
        os.makedirs(mirror)
        assert presets_path.listable_dir(arb) == mirror
    finally:
        restore()


def test_arb_save_survives_dead_share():
    """The actual 2026-07-20 regression, end to end."""
    from siggen_presets import SignalGenPresetStore
    _root, share, restore = _sandbox()
    try:
        store = SignalGenPresetStore(
            path=os.path.join(share, 'siggen_presets.json'))
        store.arb_dir = os.path.join(share, 'arb')
        store.save_arb('healthy', [0.0, 1.0, 0.0, -1.0])
        assert store.arb_names() == ['healthy']

        # The NAS goes away. Killing the share itself takes its `arb`
        # subdirectory with it, which is the same end state the old version
        # reached by chmod-ing both and then removing the share copy by hand.
        kill_dir(share)
        clean = store.save_arb('rescued', [0.0, 0.5, 1.0])   # must NOT raise
        assert clean == 'rescued'
        note = presets_path.fallback_note()
        assert note and 'local copy' in note, note
        assert os.path.exists(os.path.join(presets_path.LOCAL_FALLBACK,
                                           'arb', 'rescued.csv'))
        # and it is loadable again from the mirror, with the share back but
        # empty -- no share copy of 'rescued' has ever existed
        revive_dir(share)
        assert not os.path.exists(os.path.join(share, 'arb'))
        assert 'rescued' in store.arb_names()
        assert store.load_arb('rescued') == [0.0, 0.5, 1.0]
    finally:
        restore()


def test_bench_profile_save_survives_dead_share():
    from bench_profiles import BenchProfileStore
    _root, share, restore = _sandbox()
    try:
        store = BenchProfileStore(os.path.join(share, 'bench_profiles.json'))
        store.save('before', {'lcr': {'mode': 'CPD'}})
        kill_dir(share)
        store.save('during-outage', {'lcr': {'mode': 'CSRS'}})  # must not raise
        assert os.path.exists(os.path.join(presets_path.LOCAL_FALLBACK,
                                           'bench_profiles.json'))
    finally:
        restore()


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


def test_fallback_chain_skips_rootowned_primary():
    # The primary local fallback can itself be unwritable (root-owned
    # installer artefact, audit 2026-07-25): writable_path must land in the
    # SECOND fallback instead of raising.
    #
    # NOTE what this does and does not reproduce. The fallback CHAIN
    # (presets_path.py:83-94) is exercised exactly as before. The specific
    # cause -- a root-owned directory -- is not: since 2026-08-09 this makes
    # the primary unwritable by not being a directory, because chmod cannot
    # do it on Windows. The original root-owned case stays POSIX-only and
    # has never been reproducible in this suite on Windows at all.
    share = tempfile.mkdtemp(prefix='pp_share_')
    ro = tempfile.mkdtemp(prefix='pp_ro_')
    ok2 = tempfile.mkdtemp(prefix='pp_cache_')
    kill_dir(share)                             # share "unreachable"
    kill_dir(ro)                                # primary fallback unusable
    p1, p2 = presets_path.LOCAL_FALLBACK, presets_path.LOCAL_FALLBACK2
    presets_path.LOCAL_FALLBACK = os.path.join(ro, 'presets')
    presets_path.LOCAL_FALLBACK2 = os.path.join(ok2, 'presets')
    try:
        out = presets_path.writable_path(os.path.join(share, 'x.json'))
        assert out.startswith(presets_path.LOCAL_FALLBACK2), out
        assert presets_path.fallback_note()
    finally:
        presets_path.LOCAL_FALLBACK, presets_path.LOCAL_FALLBACK2 = p1, p2
        for d in (share, ro):
            revive_dir(d)
        for d in (share, ro, ok2):
            shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    _run()
