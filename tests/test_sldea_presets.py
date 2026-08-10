#!/usr/bin/env python3
"""Headless tests for named SLDEA run-configuration presets (`#265`).

What these pin down:
  * a saved configuration round-trips field for field;
  * the run name and the DRY/LIVE state are NEVER stored -- a preset must
    not re-arm the high voltage or reuse a run folder name;
  * drift in both directions is survivable and LOUD (`#231`): an unknown
    key is skipped with a warning, an absent key leaves its widget alone
    with a warning, and nothing is applied in silence;
  * the field list still covers every control on the tab.

These tests are deliberately NOT added to tests/test_presets_path.py:
that suite simulates a dead share with os.chmod(dir, 0o555), which
Windows ignores for directories, so it fails on the Windows bench box for
environmental reasons. Nothing here depends on making a directory
unwritable.

Run: .venv/Scripts/python tests/test_sldea_presets.py
"""
# Runnable from anywhere: put the repo root (one level up) on sys.path
# so the app modules import when this file is executed directly.
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import json
import os
import re
import shutil
import tempfile

import presets_path
import sldea_presets
from sldea_presets import SldeaPresetStore
from version import __version__

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A complete, plausible snapshot of the tab.
SAMPLE = {
    'start_kv': '0', 'end_kv': '6', 'step_kv': '0.25',
    'ramp_s': '5', 'landing_s': '60', 'settle_s': '2', 'snap_lead_s': '1',
    'repeat': '2', 'updown': True,
    'outdir': '/mnt/shareDrive/robot_incubator/SLDEA_data',
    'vch': '2', 'ich': '3', 'sgch': '1',
    'diam_mm': '16', 'electrode': 'carbon black', 'conc_ml': '2.5',
    'trek_inv': True,
    'wd_on': True, 'wd_ua': '100', 'wd_s': '3',
    'tel_on': False, 'tel_hz': '2',
    'autoproc': True,
}


def _sandbox():
    """(store, root, restore) with storage AND both presets_path fallbacks
    pointed at a throwaway directory inside the worktree.

    presets/ is gitignored, so nothing written here can reach the real
    shared library or a commit. The fallbacks are redirected too, because
    presets_path degrades an unwritable target into the USER PROFILE
    (~/.local/share/scpi_control, ~/.cache/scpi_control) and a test must
    never land there.
    """
    base = os.path.join(REPO, 'presets')
    os.makedirs(base, exist_ok=True)
    root = tempfile.mkdtemp(prefix='tmp_test_sldea_presets_', dir=base)
    saved = (presets_path.LOCAL_FALLBACK, presets_path.LOCAL_FALLBACK2)
    presets_path.LOCAL_FALLBACK = os.path.join(root, 'local')
    presets_path.LOCAL_FALLBACK2 = os.path.join(root, 'cache')
    presets_path.clear_note()
    store = SldeaPresetStore(os.path.join(root, 'sldea_presets.json'))

    def restore():
        presets_path.LOCAL_FALLBACK, presets_path.LOCAL_FALLBACK2 = saved
        presets_path.clear_note()
        shutil.rmtree(root, ignore_errors=True)
    return store, root, restore


# -- the round trip --------------------------------------------------------

def test_a_saved_configuration_round_trips_field_for_field():
    store, _root, restore = _sandbox()
    try:
        store.save('6 kV CB sweep', SAMPLE)
        fields, warnings = store.load('6 kV CB sweep')
        assert warnings == [], warnings
        assert fields == SAMPLE, fields
    finally:
        restore()


def test_every_field_survives_being_changed_and_reloaded():
    """The GUI's round-trip, one field at a time: change it, reload, and the
    stored value must come back -- not the changed one."""
    store, _root, restore = _sandbox()
    try:
        store.save('base', SAMPLE)
        for key in sldea_presets.ALL_FIELDS:
            changed = dict(SAMPLE)
            changed[key] = (not SAMPLE[key]) if key in \
                sldea_presets.BOOL_FIELDS else 'CHANGED'
            assert changed != SAMPLE
            fields, _w = store.load('base')
            assert fields[key] == SAMPLE[key], key
    finally:
        restore()


def test_entry_values_are_kept_as_raw_strings():
    """bench_profiles' rule: a half-typed field must still save. '0.2.' is
    not a float and must survive as text rather than raising."""
    store, _root, restore = _sandbox()
    try:
        halftyped = dict(SAMPLE, step_kv='0.2.', end_kv='')
        store.save('mid-edit', halftyped)
        fields, warnings = store.load('mid-edit')
        assert warnings == [], warnings
        assert fields['step_kv'] == '0.2.'
        assert fields['end_kv'] == ''
    finally:
        restore()


def test_numbers_and_none_coerce_to_text():
    store, _root, restore = _sandbox()
    try:
        store.save('typed', dict(SAMPLE, end_kv=6.5, repeat=2,
                                 electrode=None))
        fields, _w = store.load('typed')
        assert fields['end_kv'] == '6.5'
        assert fields['repeat'] == '2'
        assert fields['electrode'] == ''
    finally:
        restore()


# -- what is deliberately not stored ---------------------------------------

def test_the_run_name_is_refused_on_save():
    store, _root, restore = _sandbox()
    try:
        for key in ('run_name', 'runname'):
            try:
                store.save('nope', dict(SAMPLE, **{key: 'SLDEA_20260807'}))
            except ValueError as e:
                assert 'Run name' in str(e), e
            else:
                raise AssertionError(f"{key} was accepted")
        assert store.names() == []
    finally:
        restore()


def test_the_dry_live_state_is_refused_on_save():
    """A preset that stores DRY/LIVE is one careless reader away from
    re-arming the HV, so the store will not write the key at all."""
    store, _root, restore = _sandbox()
    try:
        for key in ('dry_run', 'dryrun', 'live'):
            try:
                store.save('nope', dict(SAMPLE, **{key: False}))
            except ValueError as e:
                assert 'DRY/LIVE' in str(e), e
            else:
                raise AssertionError(f"{key} was accepted")
        assert store.names() == []
    finally:
        restore()


def test_a_hand_edited_file_carrying_the_hv_state_is_ignored_and_says_so():
    """Defence in depth: the store refuses to WRITE the key, and a file
    that has one anyway (hand-edited, or written by another tool) is
    reported as ignored rather than applied."""
    store, root, restore = _sandbox()
    try:
        store.save('smuggled', SAMPLE)
        path = os.path.join(root, 'sldea_presets.json')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        data['presets']['smuggled']['fields']['dry_run'] = False
        data['presets']['smuggled']['fields']['run_name'] = 'SLDEA_x'
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)

        fields, warnings = store.load('smuggled')
        assert 'dry_run' not in fields and 'run_name' not in fields
        assert 'live' not in fields
        text = ' | '.join(warnings)
        assert 'DRY/LIVE state' in text and 'ignored' in text, text
        assert 'Run name' in text, text
    finally:
        restore()


def test_no_field_key_is_both_stored_and_forbidden():
    overlap = set(sldea_presets.ALL_FIELDS) & set(sldea_presets.NEVER_STORED)
    assert not overlap, overlap
    assert len(set(sldea_presets.ALL_FIELDS)) == \
        len(sldea_presets.ALL_FIELDS), "duplicate field key"


# -- drift in both directions (`#231`) -------------------------------------

def test_an_unknown_setting_is_skipped_loudly_and_the_rest_applies():
    store, root, restore = _sandbox()
    try:
        store.save('future', SAMPLE)
        path = os.path.join(root, 'sldea_presets.json')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        data['presets']['future']['fields']['plasma_mode'] = 'on'
        data['presets']['future']['app_version'] = '9.9.9'
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)

        fields, warnings = store.load('future')
        assert 'plasma_mode' not in fields
        assert fields == SAMPLE, "everything else must still apply"
        text = ' | '.join(warnings)
        assert "skipped unknown setting 'plasma_mode'" in text, text
        assert 'v9.9.9' in text and f'v{__version__}' in text, text
    finally:
        restore()


def test_a_missing_setting_leaves_its_widget_alone_and_says_so():
    store, root, restore = _sandbox()
    try:
        store.save('old', SAMPLE)
        path = os.path.join(root, 'sldea_presets.json')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        del data['presets']['old']['fields']['electrode']
        del data['presets']['old']['fields']['tel_hz']
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)

        fields, warnings = store.load('old')
        assert 'electrode' not in fields and 'tel_hz' not in fields
        assert len(fields) == len(sldea_presets.ALL_FIELDS) - 2
        text = ' | '.join(warnings)
        assert 'Electrode is not in this preset' in text, text
        assert 'Telemetry rate (Hz) is not in this preset' in text, text
        assert 'left as it is' in text, text
    finally:
        restore()


def test_a_clean_load_does_not_quote_the_version():
    """The writing version is quoted to EXPLAIN a skip. With nothing
    skipped it would just be noise on every load after a bump."""
    store, root, restore = _sandbox()
    try:
        store.save('clean', SAMPLE)
        path = os.path.join(root, 'sldea_presets.json')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        data['presets']['clean']['app_version'] = '0.0.1'
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        _fields, warnings = store.load('clean')
        assert warnings == [], warnings
    finally:
        restore()


def test_an_incomplete_snapshot_is_a_loud_save_failure():
    """The GUI builds its snapshot from ALL_FIELDS, so a gap is a code bug.
    Half a preset is worse than no preset."""
    store, _root, restore = _sandbox()
    try:
        partial = dict(SAMPLE)
        del partial['wd_ua']
        del partial['autoproc']
        try:
            store.save('half', partial)
        except ValueError as e:
            assert 'autoproc' in str(e) and 'wd_ua' in str(e), e
        else:
            raise AssertionError("an incomplete snapshot was accepted")
        assert store.names() == []
    finally:
        restore()


def test_a_preset_with_no_settings_block_fails_clearly():
    store, root, restore = _sandbox()
    try:
        store.save('x', SAMPLE)
        path = os.path.join(root, 'sldea_presets.json')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        del data['presets']['x']['fields']
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        try:
            store.load('x')
        except ValueError as e:
            assert 'settings block' in str(e), e
        else:
            raise AssertionError("a preset with no fields loaded")
    finally:
        restore()


# -- the store itself ------------------------------------------------------

def test_names_save_overwrite_and_delete():
    store, _root, restore = _sandbox()
    try:
        assert store.names() == []
        store.save('b sweep', SAMPLE)
        store.save('a sweep', dict(SAMPLE, end_kv='4'))
        assert store.names() == ['a sweep', 'b sweep']

        store.save('a sweep', dict(SAMPLE, end_kv='8'))     # edit in place
        fields, _w = store.load('a sweep')
        assert fields['end_kv'] == '8'
        assert store.names() == ['a sweep', 'b sweep'], "no duplicate"

        assert store.delete('a sweep') is True
        assert store.delete('a sweep') is False
        assert store.names() == ['b sweep']
    finally:
        restore()


def test_a_blank_name_is_refused():
    store, _root, restore = _sandbox()
    try:
        for name in ('', '   ', None):
            try:
                store.save(name, SAMPLE)
            except ValueError as e:
                assert 'must not be empty' in str(e), e
            else:
                raise AssertionError(f"name {name!r} was accepted")
    finally:
        restore()


def test_a_saved_preset_records_the_writing_app_version():
    store, _root, restore = _sandbox()
    try:
        record = store.save('stamped', SAMPLE)
        assert record['app_version'] == __version__
        assert store.get('stamped')['app_version'] == __version__
        assert record['name'] == 'stamped'
        assert record['saved_utc'].endswith('Z')
    finally:
        restore()


def test_a_missing_preset_raises_keyerror():
    store, _root, restore = _sandbox()
    try:
        try:
            store.load('never saved')
        except KeyError as e:
            assert 'never saved' in str(e), e
        else:
            raise AssertionError("a missing preset loaded")
    finally:
        restore()


def test_a_missing_file_reads_as_an_empty_library():
    store, _root, restore = _sandbox()
    try:
        assert store.names() == []
        assert not os.path.exists(store.path), "reading must not create it"
    finally:
        restore()


def test_a_corrupt_file_is_moved_aside_not_silently_overwritten():
    store, root, restore = _sandbox()
    try:
        store.save('good', SAMPLE)
        path = os.path.join(root, 'sldea_presets.json')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{not json at all')
        assert store.names() == []                  # reads as empty
        assert os.path.exists(path + '.corrupt'), "the torn file is kept"
        store.save('recovered', SAMPLE)             # and the store works on
        assert store.names() == ['recovered']
    finally:
        restore()


def test_the_write_is_atomic_and_leaves_no_temp_file():
    store, root, restore = _sandbox()
    try:
        store.save('one', SAMPLE)
        leftovers = [f for f in os.listdir(root) if f.endswith('.tmp')]
        assert leftovers == [], leftovers
    finally:
        restore()


def test_a_second_store_object_sees_the_first_one_s_saves():
    """The library is shared between two bench users over a network drive,
    so the file is re-read on every operation rather than cached."""
    store, root, restore = _sandbox()
    try:
        other = SldeaPresetStore(os.path.join(root, 'sldea_presets.json'))
        store.save('mine', SAMPLE)
        assert other.names() == ['mine']
        other.save('theirs', SAMPLE)
        assert store.names() == ['mine', 'theirs'], "a save must not drop"
    finally:
        restore()


def test_the_default_path_is_the_shared_presets_directory():
    """Same relative presets/ dir as siggen_presets and bench_profiles, so
    the launchers' ShareDrive working directory shares it between users."""
    assert sldea_presets.DEFAULT_PATH == os.path.join(
        'presets', 'sldea_presets.json')
    assert SldeaPresetStore().path == sldea_presets.DEFAULT_PATH


# -- the field list still matches the tab ----------------------------------

def _gui_source():
    with open(os.path.join(REPO, 'gui.py'), encoding='utf-8') as f:
        return f.read()


def test_every_sldea_var_on_the_tab_is_covered_by_a_preset_field():
    """Source scan, so a new control on the SLDEA tab that nobody added to
    the preset cannot ship silently. `#265` exists because the tab's run
    configuration had to be retyped every session -- a field that quietly
    stops being covered puts one back."""
    keys = set(re.findall(r"self\.sldea_vars\[['\"]([a-z_0-9]+)['\"]\]",
                          _gui_source()))
    assert keys, "the scan found no sldea_vars keys -- has gui.py moved?"
    uncovered = sorted(keys - set(sldea_presets.ALL_FIELDS))
    assert not uncovered, (
        f"SLDEA tab fields not covered by a preset: {uncovered} -- add them "
        f"to sldea_presets.TEXT_FIELDS/BOOL_FIELDS and FIELD_LABELS")


def test_the_concentration_is_stored_and_round_trips():
    """`#276`. A preset is a snapshot of the BOXES, so the concentration is
    stored whatever the electrode -- including one that greys it. Whether
    the box ends up greyed is decided from the electrode the preset loads,
    not from anything stored alongside it."""
    import sldea_profile
    store, _root, restore = _sandbox()
    try:
        assert 'conc_ml' in sldea_presets.ALL_FIELDS
        # an ink preset: applicable, and the value comes back
        store.save('ink', dict(SAMPLE, electrode='Carbon Solutions P3-SWNT',
                               conc_ml='1.5'))
        fields, warnings = store.load('ink')
        assert warnings == [], warnings
        assert fields['conc_ml'] == '1.5'
        assert sldea_profile.concentration_applies(
            fields['electrode']) is True

        # a carbon-black preset: the value is still stored (the operator
        # typed it), but loading it greys the box
        store.save('cb', dict(SAMPLE, electrode='carbon black',
                              conc_ml='2.5'))
        fields, _w = store.load('cb')
        assert fields['conc_ml'] == '2.5'
        assert sldea_profile.concentration_applies(
            fields['electrode']) is False
    finally:
        restore()


def test_every_preset_field_has_a_readable_label():
    missing = sorted(k for k in sldea_presets.ALL_FIELDS
                     if k not in sldea_presets.FIELD_LABELS)
    assert not missing, missing
    missing = sorted(k for k in sldea_presets.NEVER_STORED
                     if k not in sldea_presets.FIELD_LABELS)
    assert not missing, missing


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
