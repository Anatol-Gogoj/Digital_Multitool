#!/usr/bin/env python3
"""Headless tests for bench/test_sldea_watchdog_probe.py (no hardware).

The probe is the bench-side half of closing the monitor check's blind
spots (SLDEA_HANDOFF.md, 2026-09-24): it asks the scope for each monitor
channel's coupling and on/off state and for the acquisition state, and
its --walk takes the operator through the states the check cannot see
yet. Nothing here says what an MSO24 answers -- only a bench session can.
These pin the probe's own logic:

- it reads a reply the same way whether the scope sends a header or a
  short keyword, and never guesses at one it does not know;
- it classifies a measurement exactly as the driver does;
- it only ever queries;
- the walk does not call the scope restored when it is not.

Run: .venv/bin/python tests/test_bench_watchdog_probe.py
"""
import contextlib
import fnmatch
import importlib.util
import io
import json
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _load_probe():
    """The bench script, imported by path (bench/ is not a package)."""
    path = os.path.join(ROOT, 'bench', 'test_sldea_watchdog_probe.py')
    spec = importlib.util.spec_from_file_location('sldea_watchdog_probe',
                                                  path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


probe = _load_probe()
ICH, VCH = 3, 2


def _flat(lines):
    """Report lines as one whitespace-normalised string, so a phrase can
    be looked for across the report's line wrapping."""
    return ' '.join('\n'.join(lines).split())


def _read(path, as_json=False):
    """A file's text (or JSON), closed before the temp dir goes away."""
    with open(path, encoding='utf-8') as f:
        return json.load(f) if as_json else f.read()


def _replies(pairs, failed=()):
    """{query: reply record} from (query, reply) pairs, plus failures."""
    out = {q: {'ok': True, 'reply': r} for q, r in pairs}
    for q in failed:
        out[q] = {'ok': False, 'reply': 'VisaIOError: timeout'}
    return out


HEALTHY = (('CH3:COUPLING?', 'DC'), ('SELECT:CH3?', '1'),
           ('CH2:COUPLING?', 'DC'), ('SELECT:CH2?', '1'),
           ('ACQUIRE:STATE?', '1'))


def _snap(pairs, failed=()):
    return {'replies': _replies(pairs, failed), 'reads': [], 'after': {}}


class _VisaTimeout(Exception):
    """Stands in for pyvisa's VisaIOError, which is NOT an OSError: a probe
    that only caught IOError would die on the first real timeout."""


class _Session:
    """A pyvisa-style session: records every command sent, answers the
    queries it knows (with a trailing newline, as the wire does) and
    raises, as a timeout would, on the rest."""

    def __init__(self, replies):
        self.replies = replies
        self.sent = []

    def write(self, cmd):
        self.sent.append(cmd)

    def query(self, cmd):
        self.sent.append(cmd)
        if cmd not in self.replies:
            raise _VisaTimeout('VI_ERROR_TMO (-1073807339): timeout')
        return self.replies[cmd] + '\n'

    def close(self):
        pass


def _driver(replies):
    """The real TekMSO24 on a recording session (its I/O lock is lazy, so
    skipping __init__ -- and the USB it would open -- is supported)."""
    from instruments import TekMSO24
    scope = TekMSO24.__new__(TekMSO24)
    scope.inst = _Session(replies)
    scope.idn = 'TEST,MSO24,0,0'
    return scope


class _Bench:
    """A scripted operator on a probe._FakeScope. `actions` maps a walk
    step to what is done on the panel ('q' types q instead). The restore
    prompt can come round several times; `restores` is used in order and
    types q once it runs out."""

    DEFAULT = {
        'normal': None,
        'i_ac': lambda f: f.set_coupling(ICH, 'AC'),
        'i_off': lambda f: (f.set_coupling(ICH, 'DC'), f.set_on(ICH, False)),
        'stopped': lambda f: (f.set_on(ICH, True), f.set_running(False)),
    }

    def __init__(self, fake, actions=None, restores=None):
        self.fake = fake
        self.actions = dict(self.DEFAULT, **(actions or {}))
        self.restores = list([lambda f: f.set_running(True)]
                             if restores is None else restores)
        self.asked = []

    def __call__(self, step, text):
        self.asked.append(step)
        if step == 'restored':
            act = self.restores.pop(0) if self.restores else 'q'
        else:
            act = self.actions[step]
        if act == 'q':
            return 'q'
        if act is not None:
            act(self.fake)
        return ''


def _walk(fake, bench, reads=3):
    return probe.walk(fake, ICH, VCH, bench, reads=reads,
                      sleep=lambda s: None, echo=lambda s: None)


def _args(out, **kw):
    base = dict(ich=ICH, vch=VCH, samples=3, timing_samples=2, out=out,
                walk=False, selftest=False, resource=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _quiet(fn, *a, **kw):
    """fn(*a, **kw) with its console output swallowed."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


# ------------------------------------------------------------- parsing
def test_reply_token_strips_header_quotes_and_case():
    assert probe.reply_token('DC') == 'DC'
    assert probe.reply_token(' dc\n') == 'DC'
    assert probe.reply_token(':CH3:COUPLING DC') == 'DC'
    assert probe.reply_token(':ACQUIRE:STATE 1') == '1'
    assert probe.reply_token('"CH1"') == 'CH1'
    assert probe.reply_token(':SELECT:CH3') == ''      # header, no value
    assert probe.reply_token('') == ''


def test_parse_coupling_long_short_and_header_forms():
    for reply, want in (('DC', 'DC'), ('AC', 'AC'), ('ac', 'AC'),
                        (':CH3:COUPLING AC', 'AC'), (':CH3:COUP DC', 'DC'),
                        ('DCREJ', 'DCREJECT'), ('DCREJECT', 'DCREJECT'),
                        ('DCREJE', 'DCREJECT'), ('GND', 'GND')):
        assert probe.parse_coupling(reply) == want, reply


def test_parse_coupling_refuses_what_it_does_not_know():
    # 'D' and 'DCR' are shorter than any keyword they start; 'DCX' and
    # '1' are no keyword at all. None, never a guess.
    for reply in ('D', 'DCR', 'DCX', 'ACDC', '1', '', 'XYZ'):
        assert probe.parse_coupling(reply) is None, reply


def test_parse_on_off():
    for reply, want in (('1', True), ('ON', True), ('on', True),
                        (':SELECT:CH3 1', True), ('0', False),
                        ('OFF', False), (':DISPLAY:GLOBAL:CH3:STATE 0', False)):
        assert probe.parse_on_off(reply) is want, reply
    for reply in ('2', '', 'RUN', 'TRUE'):
        assert probe.parse_on_off(reply) is None, reply


def test_parse_acquiring_takes_run_and_stop_words():
    for reply, want in (('1', True), ('RUN', True), ('ON', True),
                        (':ACQUIRE:STATE 1', True), ('0', False),
                        ('STOP', False), ('OFF', False)):
        assert probe.parse_acquiring(reply) is want, reply
    for reply in ('', 'RUNSTOP', 'SAVE', '2'):
        assert probe.parse_acquiring(reply) is None, reply


def test_parse_trigger_mode_and_stopafter():
    for reply, want in (('AUTO', 'AUTO'), ('NORMAL', 'NORMAL'),
                        ('NORM', 'NORMAL'), ('norm', 'NORMAL'),
                        (':TRIGGER:A:MODE NORM', 'NORMAL')):
        assert probe.parse_trigger_mode(reply) == want, reply
    for reply in ('NOR', 'AUT', '', 'SINGLE'):
        assert probe.parse_trigger_mode(reply) is None, reply
    for reply, want in (('RUNSTOP', 'RUNSTOP'), ('RUNST', 'RUNSTOP'),
                        ('SEQUENCE', 'SEQUENCE'), ('SEQ', 'SEQUENCE'),
                        (':ACQUIRE:STOPAFTER SEQ', 'SEQUENCE')):
        assert probe.parse_stopafter(reply) == want, reply
    for reply in ('RUN', 'SE', ''):
        assert probe.parse_stopafter(reply) is None, reply


def test_parse_channel():
    assert probe.parse_channel('CH1') == 1
    assert probe.parse_channel(':TRIGGER:A:EDGE:SOURCE CH3') == 3
    assert probe.parse_channel('ch4') == 4
    assert probe.parse_channel('CH12') == 12
    for reply in ('LINE', 'AUX', 'CH', 'CH1_D0', ''):
        assert probe.parse_channel(reply) is None, reply


def test_classify_value_matches_the_driver():
    # The walk says what the watchdog would have made of each reply, so
    # its classification must be the driver's: same replies, same answer,
    # header-prefixed ones included (the driver cannot read those either).
    for reply in ('-8.1000E-02', '1.5E-3', '0', '9.91E+37', '9.9E37',
                  '-9.91E+37', '1E30', '1.0000001E30', 'inf', '', 'garbage',
                  ':MEASUREMENT:IMMED:VALUE -8.1E-2'):
        scope = _driver({'MEASUREMENT:IMMED:VALUE?': reply})
        assert probe.classify_value(reply) == scope.measure_raw('MEAN', 3), \
            reply


def test_read_values_sends_the_drivers_triple():
    replies = {'MEASUREMENT:IMMED:VALUE?': '-8.1E-2'}
    mine, theirs = _driver(replies), _driver(replies)
    probe.read_values(mine, ICH, 1, sleep=lambda s: None)
    theirs.measure_raw('MEAN', ICH)
    assert mine.inst.sent == theirs.inst.sent == [
        'MEASUREMENT:IMMED:TYPE MEAN', 'MEASUREMENT:IMMED:SOURCE CH3',
        'MEASUREMENT:IMMED:VALUE?']


def test_read_values_keeps_raw_replies_and_failures():
    fake = probe._FakeScope()
    fake.set_on(ICH, False)
    reads = probe.read_values(fake, ICH, 2, sleep=lambda s: None)
    assert [r['reply'] for r in reads] == ['9.91E+37', '9.91E+37']
    assert {r['status'] for r in reads} == {'offscreen'}
    broken = _driver({})                      # every query times out
    reads = probe.read_values(broken, ICH, 2, sleep=lambda s: None)
    assert [r['status'] for r in reads] == ['error', 'error']
    assert reads[0]['reply'].startswith('_VisaTimeout: VI_ERROR_TMO')
    assert reads[0]['value'] is None
    replies = probe._ask_all(broken, ['CH3:COUPLING?'])
    assert replies['CH3:COUPLING?']['ok'] is False
    assert 'VI_ERROR_TMO' in replies['CH3:COUPLING?']['reply']


def test_read_values_paced_at_the_watchdog_tick():
    t = [0.0]

    def clock():                               # every call costs 5 ms
        t[0] += 0.005
        return t[0]
    slept = []
    probe.read_values(probe._FakeScope(), ICH, 4, sleep=slept.append,
                      clock=clock)
    assert len(slept) == 3                     # none after the last read
    assert all(abs(s - 0.495) < 1e-9 for s in slept), slept


def test_describe_words():
    d = lambda q, r: probe.describe(q, r, ICH, VCH)
    assert d('CH3:COUPLING?', 'DC') == 'DC-coupled'
    assert d('CH3:COUPLING?', 'AC') == 'AC-coupled -- NOT DC'
    assert d('CH3:COUPLING?', 'DCREJ') == 'DCREJECT-coupled -- NOT DC'
    assert d('CH2:COUPLING?', 'what') == probe.UNREAD
    assert d('SELECT:CH3?', '1') == 'on'
    assert d('DISPLAY:GLOBAL:CH3:STATE?', '0') == 'OFF'
    assert d('SELECT:CH3?', 'maybe') == probe.UNREAD
    assert d('ACQUIRE:STATE?', '0') == 'STOPPED'
    assert d('ACQUIRE:STATE?', '1') == 'acquiring'
    assert d('ACQUIRE:STOPAFTER?', 'SEQ') == 'single sequence'
    assert d('TRIGGER:A:MODE?', 'NORM') == 'waits for a trigger'
    assert d('TRIGGER:A:MODE?', 'AUTO') == 'runs without a trigger too'
    assert d('TRIGGER:A:EDGE:SOURCE?', 'CH1') == \
        'a channel the run does not read'
    assert d('TRIGGER:A:EDGE:SOURCE?', 'CH3') == '= I_Out, which the run reads'
    assert d('TRIGGER:A:EDGE:SOURCE?', 'CH2') == '= V_Out, which the run reads'
    assert d('TRIGGER:A:EDGE:SOURCE?', 'LINE') == 'not an analog channel'
    assert d('TRIGGER:A:EDGE:SOURCE?', '') == probe.UNREAD
    assert d('TRIGGER:STATE?', 'READY') == ''
    assert d('HORIZONTAL:SCALE?', '1E-3') == ''


def test_reply_lines_say_fail_and_name_the_role():
    lines = probe.reply_lines(
        {'CH3:COUPLING?': {'ok': True, 'reply': 'AC', 'role': 'I_Out'},
         'SELECT:CH3?': {'ok': False, 'reply': 'VisaIOError: timeout',
                         'role': 'I_Out'},
         'TRIGGER:STATE?': {'ok': True, 'reply': 'READY'}}, ICH, VCH)
    assert 'CH3:COUPLING? [I_Out]' in lines[0]
    assert lines[0].split()[2:] == ['OK', 'AC', 'AC-coupled', '--', 'NOT',
                                    'DC']
    # a failure is shown as it came, never interpreted as a reply
    assert lines[1].split()[2:] == ['FAIL', 'VisaIOError:', 'timeout']
    assert lines[2].split() == ['TRIGGER:STATE?', 'OK', 'READY']


def test_channel_queries_both_roles_and_no_repeats():
    assert probe.channel_queries(3, 2) == [
        ('CH3:COUPLING?', 'I_Out'), ('SELECT:CH3?', 'I_Out'),
        ('DISPLAY:GLOBAL:CH3:STATE?', 'I_Out'),
        ('CH2:COUPLING?', 'V_Out'), ('SELECT:CH2?', 'V_Out'),
        ('DISPLAY:GLOBAL:CH2:STATE?', 'V_Out')]
    same = probe.channel_queries(3, 3)
    assert [q for q, _ in same] == ['CH3:COUPLING?', 'SELECT:CH3?',
                                    'DISPLAY:GLOBAL:CH3:STATE?']


def test_trigger_verdict():
    v = lambda **kw: _flat(probe.trigger_verdict(
        _replies([(q, r) for q, r in (
            ('TRIGGER:A:MODE?', kw.get('mode')),
            ('TRIGGER:A:TYPE?', kw.get('kind')),
            ('TRIGGER:A:EDGE:SOURCE?', kw.get('src'))) if r is not None]),
        ICH, VCH))
    assert 'Trigger mode AUTO' in v(mode='AUTO', src='CH1')
    assert 'no channel\'s settings can stall' in v(mode='AUTO', src='CH1')
    free = v(mode='NORM', kind='EDGE', src='CH1')
    assert 'NORMAL' in free and 'CH1, a channel the run does not read' in free
    assert 'freezes every read' in free
    # VERBOSE OFF answers EDGe as 'EDG': still an edge trigger
    assert v(mode='NORM', kind='EDG', src='CH1') == free
    own = v(mode='NORMAL', kind='EDGE', src='CH3')
    assert 'CH3 = I_Out, which the run reads' in own
    assert 'a quiet I_Out' in own
    assert 'CH2 = V_Out' in v(mode='NORMAL', src='CH2')
    assert 'LINE, not a channel' in v(mode='NORMAL', kind='EDGE', src='LINE')
    assert 'did not read back' in v(mode='NORMAL', kind='EDGE')
    assert 'type is PULSEWIDTH, not EDGE' in v(mode='NORMAL',
                                               kind='PULSEWIDTH', src='CH1')
    assert 'Read the mode off the screen' in v()
    assert 'Read the mode off the screen' in v(mode='FREE', src='CH1')


def test_blind_lines():
    assert probe.blind_lines(_replies(HEALTHY), ICH, VCH) == ([], [])
    ac = dict(HEALTHY, **{'CH3:COUPLING?': 'AC'})
    assert probe.blind_lines(_replies(ac.items()), ICH, VCH)[0] == \
        ['CH3 (I_Out) reads AC-coupled']
    # anything but DC strips the level the watchdog reads, not only AC
    rej = dict(HEALTHY, **{'CH3:COUPLING?': 'DCREJ', 'CH2:COUPLING?': 'GND'})
    assert probe.blind_lines(_replies(rej.items()), ICH, VCH)[0] == \
        ['CH3 (I_Out) reads DCREJECT-coupled', 'CH2 (V_Out) reads GND-coupled']
    off = dict(HEALTHY, **{'SELECT:CH2?': '0', 'ACQUIRE:STATE?': '0'})
    assert probe.blind_lines(_replies(off.items()), ICH, VCH)[0] == \
        ['CH2 (V_Out) reads off', 'the scope reads stopped']
    # SELECT? silent: DISPLAY:GLOBAL...:STATE? answers for on/off instead
    no_select = [(q, r) for q, r in HEALTHY if q != 'SELECT:CH3?']
    blind, unread = probe.blind_lines(
        _replies(no_select + [('DISPLAY:GLOBAL:CH3:STATE?', '0')],
                 failed=['SELECT:CH3?']), ICH, VCH)
    assert blind == ['CH3 (I_Out) reads off'] and unread == []
    # nothing readable: named as unread, never guessed as blind or fine
    blind, unread = probe.blind_lines(
        _replies([('CH3:COUPLING?', 'what')], failed=['ACQUIRE:STATE?']),
        ICH, VCH)
    assert blind == []
    assert unread == ['CH3 coupling', 'CH3 on/off', 'CH2 coupling',
                      'CH2 on/off', 'acquisition']


def _reads(*spec):
    """Read records from (reply, status) pairs."""
    return [{'reply': r, 'status': s, 'ms': 12.0,
             'value': probe.classify_value(r)[0]} for r, s in spec]


def test_reads_verdict():
    changing = _flat(probe.reads_verdict(_reads(('-8.1E-2', 'ok'),
                                                ('-7.9E-2', 'ok'))))
    assert '2 reads: 2 ok' in changing and '2 distinct of 2' in changing
    assert 'readable and changing' in changing
    assert 'median -16.00 uA' in changing
    frozen = _flat(probe.reads_verdict(_reads(('-8.1E-2', 'ok'),
                                              ('-8.1E-2', 'ok'))))
    assert 'every read returned the same value' in frozen
    sentinel = _flat(probe.reads_verdict(_reads(('9.91E+37', 'offscreen'),) * 3))
    assert '3 offscreen' in sentinel and 'over-trip' in sentinel
    assert 'BREAKDOWN-ABORT' in sentinel and 'readable' not in sentinel
    lost = _flat(probe.reads_verdict(_reads(('x', 'invalid'),
                                            ('IOError: t', 'error'))))
    assert '1 invalid, 1 error' in lost and 'MONITORING LOST' in lost
    # a read that raised (a timeout) is as unreadable as a garbled reply
    timed_out = _flat(probe.reads_verdict(_reads(('IOError: t', 'error'),)))
    assert '1 error' in timed_out and 'MONITORING LOST' in timed_out
    mixed = _flat(probe.reads_verdict(_reads(('-8.1E-2', 'ok'),
                                             ('9.91E+37', 'offscreen'))))
    assert 'over-trip' in mixed and 'changing' not in mixed
    # one read can neither repeat nor change: no claim either way
    one = _flat(probe.reads_verdict(_reads(('-8.1E-2', 'ok'))))
    assert 'same value' not in one and 'changing' not in one
    assert probe.reads_verdict([]) == ["  no reads taken"]


def test_reads_cell():
    assert probe._reads_cell(_reads(('1E-3', 'ok'), ('2E-3', 'ok'))) == \
        'ok x2'
    assert probe._reads_cell(_reads(('1E-3', 'ok'), ('1E-3', 'ok'))) == \
        'ok x2 ='
    assert probe._reads_cell(_reads(('9.91E+37', 'offscreen'),) * 6) == \
        'offscr x6'
    assert probe._reads_cell(_reads(('1E-3', 'ok'), ('e', 'error'),
                                    ('e', 'error'))) == 'ok1/err2'


def test_restore_verdict():
    start = _snap(HEALTHY)
    state, lines = probe.restore_verdict(start, _snap(HEALTHY), ICH, VCH)
    assert state is True and 'RESTORED' in _flat(lines)
    stopped = dict(HEALTHY, **{'ACQUIRE:STATE?': '0'})
    state, lines = probe.restore_verdict(start, _snap(stopped.items()),
                                         ICH, VCH)
    flat = _flat(lines)
    assert state is False and 'NOT READY FOR A LIVE RUN' in flat
    assert 'the scope reads stopped' in flat and 'NOT RESTORED' not in flat
    # V_Out is never touched by the walk, but a LIVE run needs it too
    v_off = dict(HEALTHY, **{'SELECT:CH2?': '0'})
    state, lines = probe.restore_verdict(start, _snap(v_off.items()),
                                         ICH, VCH)
    assert state is False and 'CH2 (V_Out) reads off' in _flat(lines)
    # started blind, came back to the start: still not fit for a LIVE run
    ac = dict(HEALTHY, **{'CH3:COUPLING?': 'AC'}).items()
    state, lines = probe.restore_verdict(_snap(ac), _snap(ac), ICH, VCH)
    assert state is False
    assert 'CH3 (I_Out) reads AC-coupled' in _flat(lines)
    # started blind, ends DC: ready. Never sent back to the blind start.
    state, _ = probe.restore_verdict(_snap(ac), _snap(HEALTHY), ICH, VCH)
    assert state is True
    # a reply the probe cannot interpret is held to the start instead
    odd = dict(HEALTHY, **{'SELECT:CH3?': 'X1'})
    moved = dict(HEALTHY, **{'SELECT:CH3?': 'X0'})
    state, lines = probe.restore_verdict(_snap(odd.items()),
                                         _snap(moved.items()), ICH, VCH)
    assert state is False and 'NOT RESTORED' in _flat(lines)
    assert "SELECT:CH3? reads 'X0'; it read 'X1' at the start" in \
        _flat(lines)
    state, _ = probe.restore_verdict(_snap(odd.items()), _snap(odd.items()),
                                     ICH, VCH)
    assert state is True
    # one on/off query reading a known state settles it, whatever an
    # uninterpreted second one does
    both = dict(HEALTHY, **{'DISPLAY:GLOBAL:CH3:STATE?': 'X1'})
    both_moved = dict(HEALTHY, **{'DISPLAY:GLOBAL:CH3:STATE?': 'X0'})
    state, _ = probe.restore_verdict(_snap(both.items()),
                                     _snap(both_moved.items()), ICH, VCH)
    assert state is True
    # on/off never answered: nothing to compare, so NOT CONFIRMED -- not a
    # pass, and not a loop the operator cannot leave either
    silent = [(q, r) for q, r in HEALTHY if q != 'SELECT:CH3?']
    state, lines = probe.restore_verdict(
        _snap(silent, failed=['SELECT:CH3?']),
        _snap(silent, failed=['SELECT:CH3?']), ICH, VCH)
    assert state is None and 'NOT CONFIRMED' in _flat(lines)
    assert 'CH3 on/off' in _flat(lines)
    # answered at the start, silent now: cannot be called back either
    state, _ = probe.restore_verdict(
        start, _snap(silent, failed=['SELECT:CH3?']), ICH, VCH)
    assert state is None
    # the second on/off query covers for a silent SELECT?
    alt = silent + [('DISPLAY:GLOBAL:CH3:STATE?', '1')]
    state, _ = probe.restore_verdict(_snap(alt, failed=['SELECT:CH3?']),
                                     _snap(alt, failed=['SELECT:CH3?']),
                                     ICH, VCH)
    assert state is True


def test_repeat_verdict():
    def steps(normal, stopped):
        return [{'name': 'normal', 'reads': _reads(*normal)},
                {'name': 'stopped', 'reads': _reads(*stopped)}]
    two = (('1E-3', 'ok'), ('2E-3', 'ok'))
    same = (('1E-3', 'ok'), ('1E-3', 'ok'))
    assert 'do mark a stopped scope' in _flat(probe.repeat_verdict(
        steps(two, same)))
    assert 'only ACQUIRE:STATE? can' in _flat(probe.repeat_verdict(
        steps(same, same)))
    assert 'did not return one frozen value' in _flat(probe.repeat_verdict(
        steps(two, two)))
    assert 'too few readable reads' in _flat(probe.repeat_verdict(
        steps(two, (('9.91E+37', 'offscreen'),) * 2)))
    assert probe.repeat_verdict(steps(two, two)[:1]) == []


def test_wrap_keeps_words_whole():
    lines = probe._wrap("x " * 30 + "BREAKDOWN-ABORT " + "y" * 90 + " z")
    assert len(lines) == 4, lines
    assert lines[0] == '  ' + ' '.join('x' * 30)       # 61 columns
    assert lines[1] == '     BREAKDOWN-ABORT'          # not split at '-'
    assert lines[2] == '     ' + 'y' * 90              # never split
    assert lines[3] == '     z'


# ---------------------------------------------------------------- walk
def test_walk_every_step_moves_and_it_ends_restored():
    fake = probe._FakeScope()
    bench = _Bench(fake)
    report = _walk(fake, bench)
    assert bench.asked == ['normal', 'i_ac', 'i_off', 'stopped', 'restored']
    steps = {s['name']: s for s in report['steps']}
    assert list(steps) == ['normal', 'i_ac', 'i_off', 'stopped']
    lines = lambda s: _flat(probe.step_lines(steps[s], steps['normal'],
                                             ICH, VCH))
    assert "CH3:COUPLING?: 'DC' -> 'AC' -- moved" in lines('i_ac')
    assert "SELECT:CH3?: '1' -> '0' -- moved" in lines('i_off')
    assert "ACQUIRE:STATE?: '1' -> '0' -- moved" in lines('stopped')
    assert 'did NOT move' not in lines('i_ac') + lines('stopped')
    assert 'left over' not in lines('i_off') + lines('stopped')
    assert {r['status'] for r in steps['i_off']['reads']} == {'offscreen'}
    assert len({r['reply'] for r in steps['stopped']['reads']}) == 1
    assert report['restore']['restored'] is True
    assert len(report['restore']['attempts']) == 1
    assert fake.running and fake.on[ICH] and fake.coupling[ICH] == 'DC'


def test_walk_flags_a_query_that_did_not_move():
    fake = probe._FakeScope()
    report = _walk(fake, _Bench(fake, actions={'i_ac': None}))
    normal, i_ac = report['steps'][0], report['steps'][1]
    flat = _flat(probe.step_lines(i_ac, normal, ICH, VCH))
    assert "CH3:COUPLING?: still 'DC' -- did NOT move" in flat


def test_walk_flags_a_change_left_over_from_an_earlier_step():
    fake = probe._FakeScope()
    bench = _Bench(fake,
                   actions={'i_off': lambda f: f.set_on(ICH, False)},
                   restores=[lambda f: (f.set_coupling(ICH, 'DC'),
                                        f.set_running(True))])
    report = _walk(fake, bench)
    normal, i_off = report['steps'][0], report['steps'][2]
    flat = _flat(probe.step_lines(i_off, normal, ICH, VCH))
    assert "CH3:COUPLING?: 'DC' -> 'AC' -- not this step's change" in flat
    assert report['restore']['restored'] is True


def test_walk_asks_again_until_the_scope_is_back():
    fake = probe._FakeScope()
    bench = _Bench(fake, restores=[None, lambda f: f.set_running(True)])
    report = _walk(fake, bench)
    attempts = report['restore']['attempts']
    assert bench.asked.count('restored') == 2
    assert [a['state'] for a in attempts] == [False, True]
    assert 'the scope reads stopped' in _flat(attempts[0]['verdict'])
    assert report['restore']['restored'] is True
    detail = _flat(probe.walk_detail_lines(report))
    assert 'restored (read 2):' in detail
    summary = probe.walk_summary_lines(report)
    assert 'RESTORED' in _flat(summary)
    assert 'put the scope back' not in _flat(summary)
    # the table's last column is the LAST read, the one the verdict is on
    row = [ln for ln in summary if ln.split()[:1] == ['ACQUIRE:STATE?']]
    assert row[0].split()[1:] == ['1', '1', '1', '0', '1']


def test_walk_left_unrestored_says_so_and_exits_nonzero():
    fake = probe._FakeScope()
    bench = _Bench(fake, restores=[None, 'q'])
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'p')
        rc = _quiet(probe.run_walk, fake, _args(out), operator=bench,
                    sleep=lambda s: None)
        text = _read(out + '_walk.txt')
        saved = _read(out + '_walk.json', as_json=True)
    assert rc == 1
    assert saved['restore']['restored'] is False
    flat = _flat([text])
    assert 'NOT READY FOR A LIVE RUN' in flat and 'put the scope back' in flat
    assert 'CH3 DC-coupled and on, and Run/Stop pressed' in flat


def test_walk_stopped_before_the_check_is_not_called_restored():
    fake = probe._FakeScope()
    report = _walk(fake, _Bench(fake, restores=[]))     # q at restore
    assert report['restore'] == {'restored': None, 'attempts': []}
    summary = _flat(probe.walk_summary_lines(report))
    assert 'NOT CHECKED' in summary and 'put the scope back' in summary


def test_walk_quit_midway_still_checks_the_restore():
    fake = probe._FakeScope()
    bench = _Bench(fake, actions={'stopped': 'q'},
                   restores=[lambda f: f.set_on(ICH, True)])
    report = _walk(fake, bench)
    assert [s['name'] for s in report['steps']] == ['normal', 'i_ac', 'i_off']
    assert report['restore']['restored'] is True
    assert probe.repeat_verdict(report['steps']) == []    # never stopped


def test_walk_quit_at_the_start_records_nothing():
    fake = probe._FakeScope()
    bench = _Bench(fake, actions={'normal': 'q'})
    with tempfile.TemporaryDirectory() as tmp:
        rc = _quiet(probe.run_walk, fake, _args(os.path.join(tmp, 'p')),
                    operator=bench, sleep=lambda s: None)
    assert rc == 1 and bench.asked == ['normal']


def test_walk_ctrl_c_keeps_what_it_read_and_says_put_back():
    fake = probe._FakeScope()
    bench = _Bench(fake, restores=[None])

    def operator(step, text):
        if step == 'restored' and bench.asked.count('restored') == 1:
            raise KeyboardInterrupt
        return bench(step, text)
    try:
        report = _walk(fake, operator)
    except KeyboardInterrupt:
        raise AssertionError("Ctrl-C escaped the walk: no file written and "
                             "no put-back reminder printed")
    assert report['interrupted'] is True
    assert len(report['restore']['attempts']) == 1       # kept
    assert report['restore']['restored'] is False
    summary = _flat(probe.walk_summary_lines(report))
    assert 'INTERRUPTED' in summary and 'put the scope back' in summary


def test_walk_does_not_spin_on_a_query_the_scope_never_answers():
    class NoOnOff(probe._FakeScope):
        def ask(self, cmd):
            if cmd.startswith('SELECT:'):
                raise IOError('VI_ERROR_TMO: timeout')
            return super().ask(cmd)
    fake = NoOnOff()
    bench = _Bench(fake)
    report = _walk(fake, bench)
    assert bench.asked.count('restored') == 1
    assert report['restore']['restored'] is None
    normal, i_off = report['steps'][0], report['steps'][2]
    flat = _flat(probe.step_lines(i_off, normal, ICH, VCH))
    assert 'SELECT:CH3?: no reply at the start or now' in flat
    summary = _flat(probe.walk_summary_lines(report))
    assert 'NOT CONFIRMED' in summary and 'CH3 on/off' in summary
    assert 'put the scope back' in summary


def test_walk_notices_when_its_own_reads_change_the_state():
    class SelfEnabling(probe._FakeScope):
        """Measuring an off channel switches it back on: the kind of side
        effect the second read of the watched queries exists to catch."""
        def write(self, cmd):
            super().write(cmd)
            if cmd.startswith('MEASUREMENT:IMMED:SOURCE'):
                self.on[self._source] = True
    fake = SelfEnabling()
    report = _walk(fake, _Bench(fake))
    normal, i_off = report['steps'][0], report['steps'][2]
    flat = _flat(probe.step_lines(i_off, normal, ICH, VCH))
    assert ("SELECT:CH3?: '0' before the reads, '1' after -- the reads "
            "themselves changed it") in flat
    assert 'reads themselves' not in _flat(
        probe.step_lines(report['steps'][1], normal, ICH, VCH))


def test_walk_warns_when_the_start_reads_blind():
    fake = probe._FakeScope()
    fake.set_coupling(ICH, 'AC')              # left AC before the walk
    report = _walk(fake, _Bench(fake))
    normal = report['steps'][0]
    flat = _flat(probe.step_lines(normal, normal, ICH, VCH))
    assert 'WARNING: the start reads blind for a LIVE run' in flat
    assert 'CH3 (I_Out) reads AC-coupled' in flat
    # the i_off step set DC on the way: the walk ends ready, and is not
    # told to put the AC it started with back
    last = report['restore']['attempts'][-1]
    assert last['state'] is True and fake.coupling[ICH] == 'DC'


def test_walk_table_one_column_per_step():
    fake = probe._FakeScope()
    report = _walk(fake, _Bench(fake))
    cols = report['steps'] + report['restore']['attempts'][-1:]
    table = probe.walk_table(cols, ICH)
    rows = {ln.split()[0]: ln.split()[1:] for ln in table[1:]}
    assert table[0].split() == [
        'normal', 'i_ac', 'i_off', 'stopped', 'restored']
    assert all(ln == ln.rstrip() for ln in table)     # pasteable as is
    assert rows['CH3:COUPLING?'] == ['DC', 'AC', 'DC', 'DC', 'DC']
    assert rows['SELECT:CH3?'] == ['1', '1', '0', '1', '1']
    assert rows['ACQUIRE:STATE?'] == ['1', '1', '1', '0', '1']
    assert rows['DISPLAY:GLOBAL:CH3:STATE?'] == ['FAIL'] * 5
    assert rows['MEAN'][3:] == ['ok', 'x3', 'ok', 'x3', 'offscr', 'x3',
                                'ok', 'x3', '=', 'ok', 'x3']


# ------------------------------------------------------ safety / audit
def test_probe_only_queries_on_the_real_driver():
    # SAFETY in the probe's docstring: MEASUREMENT:IMMED TYPE/SOURCE are
    # its only writes. Held on the real driver, both modes, every command.
    replies = {'MEASUREMENT:IMMED:VALUE?': '-8.1E-2', 'ACQUIRE:STATE?': '1',
               'CH3:COUPLING?': 'DC', 'CH2:COUPLING?': 'DC',
               'SELECT:CH3?': '1', 'SELECT:CH2?': '1',
               'TRIGGER:A:MODE?': 'AUTO'}
    scope = _driver(replies)
    prompts = []

    def operator(step, text):     # changes nothing; types q rather than
        prompts.append(step)      # hang the suite if restore never passes
        return 'q' if prompts.count('restored') > 2 else ''
    with tempfile.TemporaryDirectory() as tmp:
        _quiet(probe.run, scope, _args(os.path.join(tmp, 'p')))
        report = _quiet(probe.walk, scope, ICH, VCH, operator, reads=2,
                        sleep=lambda s: None)
    assert report['restore']['restored'] is True
    sent = scope.inst.sent
    for cmd in sent:
        assert cmd.endswith('?') or cmd.split(' ')[0] in (
            'MEASUREMENT:IMMED:TYPE', 'MEASUREMENT:IMMED:SOURCE'), cmd
    for q in ('CH3:COUPLING?', 'SELECT:CH3?', 'CH2:COUPLING?',
              'SELECT:CH2?', 'DISPLAY:GLOBAL:CH3:STATE?', 'ACQUIRE:STATE?',
              'TRIGGER:A:MODE?', 'TRIGGER:A:EDGE:SOURCE?'):
        assert q in sent, q


def test_walk_outputs_are_gitignored():
    # Run data never enters the repo: the walk's files must fall under the
    # patterns that already keep the probe's own report out.
    with open(os.path.join(ROOT, '.gitignore'), encoding='utf-8') as f:
        pats = [ln.strip() for ln in f
                if ln.strip() and not ln.startswith('#')]
    for name in (probe.DEFAULT_OUT + '.txt', probe.DEFAULT_OUT + '.json',
                 probe.DEFAULT_OUT + '_walk.txt',
                 probe.DEFAULT_OUT + '_walk.json'):
        assert any(fnmatch.fnmatch(name, p) for p in pats), name


def test_default_report_carries_the_channel_queries():
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'p')
        _quiet(probe.run, probe._FakeScope(), _args(out))
        saved = _read(out + '.json', as_json=True)
        text = _read(out + '.txt')
    ch = saved['channel_queries']
    assert ch['CH3:COUPLING?'] == {'ok': True, 'reply': 'DC', 'role': 'I_Out'}
    assert ch['SELECT:CH2?'] == {'ok': True, 'reply': '1', 'role': 'V_Out'}
    assert ch['DISPLAY:GLOBAL:CH3:STATE?']['ok'] is False
    for q in probe.STATE_QUERIES:
        assert q in saved['state_queries'], q
    flat = _flat([text])
    assert 'CH3:COUPLING? [I_Out] OK DC DC-coupled' in flat
    assert 'Trigger mode AUTO' in flat


def test_selftest_runs_both_modes():
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'p')
        assert _quiet(probe.main, ['--selftest', '--samples', '3',
                                   '--timing-samples', '2', '--out', out]) == 0
        assert _quiet(probe.main, ['--selftest', '--walk', '--out', out]) == 0
        walked = _read(out + '_walk.json', as_json=True)
        assert os.path.exists(out + '.txt')
    assert [s['name'] for s in walked['steps']] == ['normal', 'i_ac',
                                                    'i_off', 'stopped']
    assert walked['restore']['restored'] is True


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
