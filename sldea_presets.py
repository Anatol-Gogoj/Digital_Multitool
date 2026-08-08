#!/usr/bin/env python3
"""Named SLDEA run-configuration presets (pure logic -- no Tk, no hardware).

A preset is a widget-level snapshot of the SLDEA Test tab's run
configuration: the staircase, the output directory, the scope/SG channel
map, the device fields, and the watchdog/telemetry settings. It is the
same idea as the signal generator's named presets (siggen_presets.py) and
the whole-bench profiles (bench_profiles.py), so it REUSES their
conventions instead of inventing a second preset system:

  * one JSON file under the shared relative ``presets/`` directory, so a
    preset saved by one bench user is visible to the other;
  * every read and write goes through ``presets_path`` so a dead share
    degrades to a local copy instead of raising (the 2026-07-20 data-loss
    regression);
  * atomic writes (tmp + os.replace) so two users cannot tear the file;
  * entry values are stored as their RAW STRINGS, exactly as
    bench_profiles does, so Save never fails on a half-typed field.

TWO SETTINGS ARE DELIBERATELY NEVER STORED (`#265`):

  Run name   identifies ONE run, not a configuration. A preset carrying it
             would quietly push every load toward the same folder name.
  DRY / LIVE a preset must never re-arm the high voltage. Loading a preset
             leaves the tab in DRY and says so, so arming LIVE stays a
             separate, deliberate click by the operator. This is why the
             store refuses to write the key at all rather than merely
             ignoring it on load -- a preset file that CONTAINS
             ``dry_run: false`` is one careless reader away from being
             honoured.

Each preset records the app version that wrote it. Fields have been
moving (`#231`), so loading is tolerant in BOTH directions -- an unknown
key is skipped, a key this preset does not carry leaves its widget alone
-- and every skip is reported back to the caller so the GUI can say what
it did not apply. A load never silently half-applies.

Headless self-test: .venv/Scripts/python tests/test_sldea_presets.py
"""
import json
import os
from datetime import datetime, timezone

import presets_path
from version import __version__

SCHEMA_VERSION = 1

# Same relative directory as siggen_presets.py and bench_profiles.py: the
# launchers run with the working directory on the ShareDrive, so this is
# the shared bench library. presets/ is gitignored.
DEFAULT_PATH = os.path.join('presets', 'sldea_presets.json')

# Entry / combobox fields, stored as the raw strings the operator typed.
# Keys are the keys of GUI.sldea_vars plus 'outdir'.
TEXT_FIELDS = (
    # staircase
    'start_kv', 'end_kv', 'step_kv',
    'ramp_s', 'landing_s', 'settle_s', 'snap_lead_s', 'repeat',
    # where the runs land
    'outdir',
    # instrument channel map
    'vch', 'ich', 'sgch',
    # device under test. conc_ml is stored even when the electrode makes it
    # inapplicable: a preset is a snapshot of the BOXES, and whether the
    # box is greyed follows the electrode the preset loads (`#276`).
    'diam_mm', 'electrode', 'conc_ml',
    # breakdown watchdog
    'wd_ua', 'wd_s',
    # telemetry
    'tel_hz',
)

# Checkbutton fields, stored as bools.
BOOL_FIELDS = ('updown', 'trek_inv', 'wd_on', 'tel_on', 'autoproc')

ALL_FIELDS = TEXT_FIELDS + BOOL_FIELDS

# Refused on save and reported-as-ignored on load. The aliases are here so
# a hand-edited or foreign file naming the HV state in any obvious way is
# still reported as "deliberately ignored" rather than "unknown setting".
NEVER_STORED = ('run_name', 'runname', 'dry_run', 'dryrun', 'live')

# Readable names for the warning lines the GUI shows.
FIELD_LABELS = {
    'start_kv': 'Start (kV)', 'end_kv': 'End (kV)', 'step_kv': 'Step (kV)',
    'ramp_s': 'Ramp (s)', 'landing_s': 'Landing (s)',
    'settle_s': 'Settle (s)', 'snap_lead_s': 'Snap lead (s)',
    'repeat': 'Repeat', 'updown': 'Up/down (hysteresis)',
    'outdir': 'Output dir',
    'vch': 'V_Out scope CH', 'ich': 'I_Out scope CH', 'sgch': 'SG CH',
    'diam_mm': 'DEA diam (mm)', 'electrode': 'Electrode',
    'conc_ml': 'Concentration (mL)',
    'trek_inv': 'Trek inverts',
    'wd_on': 'Watchdog enabled', 'wd_ua': 'Watchdog trip (uA)',
    'wd_s': 'Watchdog confirm (s)',
    'tel_on': 'Telemetry enabled', 'tel_hz': 'Telemetry rate (Hz)',
    'autoproc': 'Auto-open Edge Review',
    'run_name': 'Run name', 'runname': 'Run name',
    'dry_run': 'DRY/LIVE state', 'dryrun': 'DRY/LIVE state',
    'live': 'DRY/LIVE state',
}


def field_label(key):
    """Human-readable name for a field key (falls back to the key)."""
    return FIELD_LABELS.get(key, key)


def normalise_for_save(fields):
    """Validate a complete {key: value} snapshot for storage.

    Text fields are coerced to str and bools to bool. Raises ValueError on
    an unknown key, on one of NEVER_STORED, or on an incomplete snapshot:
    the GUI builds its snapshot by iterating ALL_FIELDS, so any of those is
    a code bug rather than something an operator typed, and a preset that
    is silently missing half the tab is worse than a loud failure.
    """
    if not isinstance(fields, dict):
        raise ValueError("preset fields must be a dict, got "
                         f"{type(fields).__name__}")
    out = {}
    for key, value in fields.items():
        if key in NEVER_STORED:
            raise ValueError(
                f"{field_label(key)} ({key!r}) is never stored in an SLDEA "
                f"preset -- see the module docstring")
        if key in BOOL_FIELDS:
            out[key] = bool(value)
        elif key in TEXT_FIELDS:
            out[key] = '' if value is None else str(value)
        else:
            raise ValueError(f"unknown SLDEA preset field {key!r}")
    missing = sorted(k for k in ALL_FIELDS if k not in out)
    if missing:
        raise ValueError("snapshot is missing " + ', '.join(missing))
    return out


def normalise_for_load(stored, saved_app_version=None):
    """A stored field block -> (applicable_fields, warnings).

    `applicable_fields` holds only keys this build knows how to apply;
    `warnings` is a list of plain sentences naming everything that was NOT
    applied, so the caller can show them rather than half-applying in
    silence. Both directions of drift are tolerated (`#231`):

      * a key this build does not know  -> skipped, warned
      * a key this preset does not have -> the widget is left alone, warned

    The app version that wrote the preset is quoted only when something was
    actually skipped -- otherwise every load after a version bump would nag
    about a preset that applied perfectly.
    """
    if not isinstance(stored, dict):
        raise ValueError("preset has no settings block")
    fields, warnings = {}, []
    for key in sorted(stored):
        value = stored[key]
        if key in BOOL_FIELDS:
            fields[key] = bool(value)
        elif key in TEXT_FIELDS:
            fields[key] = '' if value is None else str(value)
        elif key in NEVER_STORED:
            warnings.append(
                f"ignored {field_label(key)}: an SLDEA preset never carries "
                f"it")
        else:
            warnings.append(f"skipped unknown setting {key!r}")
    for key in ALL_FIELDS:
        if key not in fields:
            warnings.append(
                f"{field_label(key)} is not in this preset -- left as it is")
    if warnings:
        warnings.append(
            f"(preset written by v{saved_app_version or '?'}; "
            f"this app is v{__version__})")
    return fields, warnings


class SldeaPresetStore:
    """JSON-backed store of named SLDEA run configurations.

    The file is re-read on every operation (bench_profiles.py's behaviour,
    not siggen_presets.py's cached one): the library is shared between two
    bench users over a network drive, so a cached copy would let one user's
    save drop the other's preset.
    """

    def __init__(self, path=DEFAULT_PATH):
        self.path = path or DEFAULT_PATH

    @property
    def _root(self):
        """Configured presets directory; the local fallback mirrors its
        layout underneath."""
        return os.path.dirname(self.path) or '.'

    # -- persistence -------------------------------------------------------
    def _read(self):
        """The whole store. A missing file reads as empty; a corrupt one is
        moved aside to ``<path>.corrupt`` and read as empty, so a torn file
        is preserved for inspection instead of being silently overwritten by
        the next save."""
        path = presets_path.readable_path(self.path, self._root)
        empty = {'version': SCHEMA_VERSION, 'presets': {}}
        if not os.path.exists(path):
            return empty
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict) \
                    or not isinstance(data.get('presets'), dict):
                raise ValueError("missing 'presets' object")
        except (json.JSONDecodeError, ValueError, OSError):
            try:
                os.replace(path, path + '.corrupt')
            except OSError:
                pass
            return empty
        return {'version': data.get('version', SCHEMA_VERSION),
                'presets': data['presets']}

    def _write(self, data):
        """Atomically persist: temp file then os.replace onto the path."""
        path = presets_path.writable_path(self.path, root=self._root)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, path)

    # -- queries -----------------------------------------------------------
    def names(self):
        """Sorted preset names (for a combobox)."""
        return sorted(self._read()['presets'])

    def get(self, name):
        """The full stored record. Raises KeyError if there is no such
        preset."""
        presets = self._read()['presets']
        if name not in presets:
            raise KeyError(f"No SLDEA preset named {name!r}")
        return presets[name]

    # -- mutations ---------------------------------------------------------
    def save(self, name, fields):
        """Create or overwrite a preset from a complete field snapshot.

        Overwrites without asking -- the GUI confirms first, same as the
        bench profiles. Returns the stored record.
        """
        name = str(name or '').strip()
        if not name:
            raise ValueError("Preset name must not be empty")
        record = {
            'name': name,
            'saved_utc': datetime.now(timezone.utc).strftime(
                '%Y-%m-%dT%H:%M:%SZ'),
            'app_version': __version__,
            'fields': normalise_for_save(fields),
        }
        data = self._read()
        data['presets'][name] = record
        data['version'] = SCHEMA_VERSION
        self._write(data)
        return record

    def load(self, name):
        """(fields, warnings) for a saved preset.

        `fields` is ready to push into the widgets; `warnings` names
        everything that could not be applied (see normalise_for_load).
        """
        record = self.get(name)
        if not isinstance(record, dict) or 'fields' not in record:
            raise ValueError(
                f"preset {name!r} has no settings block -- it may have been "
                f"written by a different tool")
        return normalise_for_load(record['fields'],
                                  record.get('app_version'))

    def delete(self, name):
        """Remove a preset. True if it existed, False otherwise."""
        data = self._read()
        if name not in data['presets']:
            return False
        del data['presets'][name]
        self._write(data)
        return True
