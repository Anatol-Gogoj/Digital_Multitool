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
- beyond the driver's connect sequence, it only ever queries;
- the walk trusts a query only once the query has followed the front
  panel, and never calls the scope RESTORED when it is not.

Run: .venv/bin/python tests/test_bench_watchdog_probe.py
"""
import builtins
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
# Every reply the walk judges, in the state a LIVE run needs.
FULL = {'CH3:COUPLING?': 'DC', 'SELECT:CH3?': '1',
        'DISPLAY:GLOBAL:CH3:STATE?': '1', 'CH2:COUPLING?': 'DC',
        'SELECT:CH2?': '1', 'DISPLAY:GLOBAL:CH2:STATE?': '1',
        'ACQUIRE:STATE?': '1', 'ACQUIRE:STOPAFTER?': 'RUNSTOP'}
# What each walk step changes when every query follows the front panel.
TRACKING = {'i_ac': {'CH3:COUPLING?': 'AC'},
            'i_off': {'SELECT:CH3?': '0', 'DISPLAY:GLOBAL:CH3:STATE?': '0'},
            'stopped': {'ACQUIRE:STATE?': '0'}}


def _reads(*spec):
    """Read records from (reply, status) pairs."""
    return [{'reply': r, 'status': s, 'ms': 12.0,
             'value': probe.classify_value(r)[0]} for r, s in spec]


CHANGING = (('-8.1E-2', 'ok'), ('-7.9E-2', 'ok'))
FROZEN = (('-8.1E-2', 'ok'), ('-8.1E-2', 'ok'))


def _step(name, over=None, failed=(), reads=CHANGING):
    """A walk step: FULL's replies with `over` laid on top, `failed`
    queries timing out."""
    replies = dict(FULL, **(over or {}))
    return {'name': name, 'reads': _reads(*reads), 'after': {},
            'replies': _replies([(q, r) for q, r in replies.items()
                                 if q not in failed], failed)}


def _walk_steps(**over):
    """A walk in which every query followed the front panel. over[step]
    replaces that step's changes; None leaves the step out, as a walk
    stopped early would."""
    steps = [_step('normal', over.get('normal'))]
    for name in ('i_ac', 'i_off', 'stopped'):
        change = over.get(name, TRACKING[name])
        if change is not None:
            steps.append(_step(name, change, reads=(
                FROZEN if name == 'stopped' else CHANGING)))
    return steps


def _now(over=None, after=None, failed=(), reads=CHANGING):
    """A restore read: before the reads as _step, after them the same
    unless `after` says otherwise."""
    snap = _step('restored', over, failed, reads)
    watched = probe.watched_queries(ICH) + ['ACQUIRE:STOPAFTER?']
    snap['after'] = {q: snap['replies'][q] for q in watched}
    for q, r in (after or {}).items():
        snap['after'][q] = {'ok': True, 'reply': r}
    return snap


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
        self.timeout = None
        self.read_termination = self.write_termination = None

    def write(self, cmd):
        self.sent.append(cmd)

    def query(self, cmd):
        self.sent.append(cmd)
        if cmd not in self.replies:
            raise _VisaTimeout('VI_ERROR_TMO (-1073807339): timeout')
        return self.replies[cmd] + '\n'

    def clear(self):
        self.sent.append('<device clear>')

    def close(self):
        pass


class _RM:
    """A pyvisa ResourceManager stand-in that hands out one session."""

    def __init__(self, session):
        self.session = session

    def open_resource(self, resource):
        return self.session


def _driver(replies):
    """The real TekMSO24 on a recording session (its I/O lock is lazy, so
    skipping __init__ -- and the USB it would open -- is supported)."""
    from instruments import TekMSO24
    scope = TekMSO24.__new__(TekMSO24)
    scope.inst = _Session(replies)
    scope.idn = 'TEST,MSO24,0,0'
    return scope


class _Panel(probe._FakeScope):
    """The selftest's fake, with some replies overridden: a constant, a
    function of the panel, or an exception. This is how a query that
    ignores the front panel, or a Single button, gets played."""

    def __init__(self, **fixed):
        super().__init__()
        # SELECT_CH3Q -> 'SELECT:CH3?': a keyword argument cannot spell a
        # colon or a question mark, so the trailing Q stands for the '?'
        self.fixed = {q[:-1].replace('_', ':') + '?': v
                      for q, v in fixed.items()}
        self.stopafter = 'RUNSTOP'

    def ask(self, cmd):
        if cmd in self.fixed:
            v = self.fixed[cmd]
            if isinstance(v, Exception):
                raise v
            return v(self) if callable(v) else v
        return super().ask(cmd)


class _Bench:
    """A scripted operator on a probe._FakeScope. `actions` maps a walk
    step to what is done on the panel ('q' types q instead). The restore
    prompt can come round several times; `restores` is used in order, and
    q is typed once it runs out."""

    DEFAULT = {
        'normal': None,
        'i_ac': lambda f: f.set_coupling(ICH, 'AC'),
        'i_off': lambda f: (f.set_coupling(ICH, 'DC'), f.set_on(ICH, False)),
        'stopped': lambda f: (f.set_on(ICH, True), f.set_running(False)),
    }
    PUT_RIGHT = staticmethod(lambda f: (f.set_coupling(ICH, 'DC'),
                                        f.set_on(ICH, True),
                                        f.set_running(True)))

    def __init__(self, fake, actions=None, restores=None):
        self.fake = fake
        self.actions = dict(self.DEFAULT, **(actions or {}))
        self.restores = list([self.PUT_RIGHT] if restores is None
                             else restores)
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
    assert 'LINE, the mains, which triggers all the time' in v(
        mode='NORMAL', kind='EDGE', src='LINE')
    # a digital channel or AUX is NOT safe: nothing may be driving it
    for src in ('D0', 'AUX'):
        flat = v(mode='NORMAL', kind='EDGE', src=src)
        assert f'{src}, not an analog channel' in flat, flat
        assert 'if nothing drives it, every read freezes' in flat
        assert 'cannot' not in flat and 'no channel' not in flat
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
    off = dict(HEALTHY, **{'SELECT:CH2?': '0', 'ACQUIRE:STATE?': '0',
                           'ACQUIRE:STOPAFTER?': 'SEQ'})
    assert probe.blind_lines(_replies(off.items()), ICH, VCH)[0] == \
        ['CH2 (V_Out) reads off', 'the scope reads stopped',
         'the scope is set to stop after one acquisition (Single)']
    # SELECT? silent: DISPLAY:GLOBAL...:STATE? answers for on/off instead
    no_select = [(q, r) for q, r in HEALTHY if q != 'SELECT:CH3?']
    blind, unread = probe.blind_lines(
        _replies(no_select + [('DISPLAY:GLOBAL:CH3:STATE?', '0')],
                 failed=['SELECT:CH3?']), ICH, VCH)
    assert blind == ['CH3 (I_Out) reads off'] and unread == []
    # the two on/off queries disagree: one reading off is enough
    both = dict(HEALTHY, **{'DISPLAY:GLOBAL:CH3:STATE?': '0'})
    assert probe.blind_lines(_replies(both.items()), ICH, VCH)[0] == \
        ['CH3 (I_Out) reads off']
    # nothing readable: named as unread, never guessed as blind or fine
    blind, unread = probe.blind_lines(
        _replies([('CH3:COUPLING?', 'what')], failed=['ACQUIRE:STATE?']),
        ICH, VCH)
    assert blind == []
    assert unread == ['CH3 coupling', 'CH3 on/off', 'CH2 coupling',
                      'CH2 on/off', 'acquisition']


def test_reads_verdict():
    changing = _flat(probe.reads_verdict(_reads(*CHANGING)))
    assert '2 reads: 2 ok' in changing and '2 distinct of 2' in changing
    assert 'readable and changing' in changing
    assert 'median -16.00 uA' in changing
    frozen = _flat(probe.reads_verdict(_reads(*FROZEN)))
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


# ---------------------------------------------- which queries to trust
def test_moved_lines_judge_the_direction():
    normal = _step('normal')

    def lines(name, over, start=normal):
        return _flat(probe.moved_lines(_step(name, over), start, ICH))
    assert ("CH3:COUPLING?: 'DC' -> 'AC' -- moved, as this step should"
            in lines('i_ac', {'CH3:COUPLING?': 'AC'}))
    assert "CH3:COUPLING?: still 'DC' -- did NOT move" in lines('i_ac', {})
    assert "ACQUIRE:STATE?: '1' -> '0' -- moved" in lines(
        'stopped', {'ACQUIRE:STATE?': '0'})
    # moved, but to the reading a LIVE run needs: the start was AC
    back = lines('i_ac', {'CH3:COUPLING?': 'DC'},
                 start=_step('normal', {'CH3:COUPLING?': 'AC'}))
    assert "moved, but to the reading a LIVE run needs" in back
    silent = _flat(probe.moved_lines(
        _step('i_off', {}, failed=['SELECT:CH3?']), normal, ICH))
    assert "SELECT:CH3?: no reply now -- cannot tell" in silent


def test_proven_queries_trust_only_what_followed_the_panel():
    every = {'CH{ch}:COUPLING?', 'SELECT:CH{ch}?',
             'DISPLAY:GLOBAL:CH{ch}:STATE?', 'ACQUIRE:STATE?'}
    assert set(probe.proven_queries(_walk_steps(), ICH)) == every
    # did not move when its change was made
    assert 'CH{ch}:COUPLING?' not in probe.proven_queries(
        _walk_steps(i_ac={}), ICH)
    # moved, but to the good reading (the start was AC)
    assert 'CH{ch}:COUPLING?' not in probe.proven_queries(
        _walk_steps(normal={'CH3:COUPLING?': 'AC'},
                    i_ac={'CH3:COUPLING?': 'DC'}), ICH)
    # its step never reached
    assert 'ACQUIRE:STATE?' not in probe.proven_queries(
        _walk_steps(stopped=None), ICH)
    # no reply at its step
    steps = _walk_steps()
    steps[2] = _step('i_off', TRACKING['i_off'], failed=['SELECT:CH3?'])
    assert 'SELECT:CH{ch}?' not in probe.proven_queries(steps, ICH)
    # a reply it cannot interpret still proves the query, if it moved
    proven = probe.proven_queries(_walk_steps(
        normal={'SELECT:CH3?': 'X1'}, i_off={'SELECT:CH3?': 'X0'}), ICH)
    assert proven['SELECT:CH{ch}?'] == ('X1', 'X0')
    assert 'DISPLAY:GLOBAL:CH{ch}:STATE?' not in proven   # stayed '1'


def test_proof_lines_say_what_counts_and_why():
    steps = _walk_steps(i_ac={}, stopped=None)
    steps[2] = _step('i_off', {'SELECT:CH3?': '0'},
                     failed=['DISPLAY:GLOBAL:CH3:STATE?'])
    flat = _flat(probe.proof_lines(steps, ICH))
    assert ("CH3:COUPLING? did NOT follow the front panel: 'DC' in normal "
            "use and at step i_ac") in flat
    assert ("SELECT:CH3? FOLLOWS the front panel: '1' in normal use, '0' "
            "at step i_off") in flat
    assert ("DISPLAY:GLOBAL:CH3:STATE? no reply, so it cannot be judged"
            in flat)
    assert ("ACQUIRE:STATE? not tested: the walk stopped before step "
            "stopped") in flat


# ----------------------------------------------------- restore verdict
def test_restore_verdict_ready_only_when_all_of_it_is_confirmed():
    state, lines = probe.restore_verdict(_walk_steps(), _now(), ICH, VCH)
    assert state is True and 'RESTORED' in _flat(lines)
    stopped = probe.restore_verdict(_walk_steps(),
                                    _now({'ACQUIRE:STATE?': '0'}), ICH, VCH)
    assert stopped[0] is False
    assert 'NOT READY FOR A LIVE RUN' in _flat(stopped[1])
    assert "acquisition: ACQUIRE:STATE? reads '0'" in _flat(stopped[1])
    # V_Out is never touched by the walk, but a LIVE run needs it too
    v_off = probe.restore_verdict(_walk_steps(), _now({'SELECT:CH2?': '0'}),
                                  ICH, VCH)
    assert v_off[0] is False
    assert "CH2 (V_Out) on/off: SELECT:CH2? reads '0'" in _flat(v_off[1])


def test_restore_verdict_a_bad_reading_counts_from_any_query():
    # the two on/off queries disagree: the one reading off wins
    state, lines = probe.restore_verdict(
        _walk_steps(), _now({'DISPLAY:GLOBAL:CH3:STATE?': '0'}), ICH, VCH)
    assert state is False
    assert "DISPLAY:GLOBAL:CH3:STATE? reads '0'" in _flat(lines)
    # even from a query the walk did not prove
    state, _ = probe.restore_verdict(_walk_steps(i_ac={}),
                                     _now({'CH3:COUPLING?': 'AC'}), ICH, VCH)
    assert state is False


def test_restore_verdict_never_trusts_a_query_that_ignored_the_panel():
    # #337-review finding: SELECT? answered 1 whatever the panel did, so
    # its '1' at the end says nothing. DISPLAY followed the panel and
    # says off.
    steps = _walk_steps(i_off={'DISPLAY:GLOBAL:CH3:STATE?': '0'})
    state, lines = probe.restore_verdict(
        steps, _now({'DISPLAY:GLOBAL:CH3:STATE?': '0'}), ICH, VCH)
    assert state is False and "CH3 (I_Out) on/off" in _flat(lines)
    state, _ = probe.restore_verdict(steps, _now(), ICH, VCH)
    assert state is True
    # coupling never moved: its 'DC' at the end cannot be trusted
    state, lines = probe.restore_verdict(_walk_steps(i_ac={}), _now(),
                                         ICH, VCH)
    assert state is None and 'NOT CONFIRMED' in _flat(lines)
    assert ("CH3 (I_Out) coupling: no query this walk showed follows the "
            "front panel") in _flat(lines)
    assert 'RESTORED' not in _flat(lines)


def test_restore_verdict_a_blind_start_is_not_sent_back():
    # I_Out was AC before the walk, so the coupling query never showed it
    # follows the panel. DC at the end is unconfirmed -- never "put the
    # AC back" -- and AC at the end is NOT READY.
    steps = _walk_steps(normal={'CH3:COUPLING?': 'AC'})
    state, lines = probe.restore_verdict(steps, _now(), ICH, VCH)
    assert state is None and 'CH3 (I_Out) coupling' in _flat(lines)
    state, _ = probe.restore_verdict(steps, _now({'CH3:COUPLING?': 'AC'}),
                                     ICH, VCH)
    assert state is False


def test_restore_verdict_uninterpreted_replies_are_held_to_the_walk():
    no_disp = ('DISPLAY:GLOBAL:CH3:STATE?', 'DISPLAY:GLOBAL:CH2:STATE?')
    odd = {'SELECT:CH3?': 'X1', 'SELECT:CH2?': 'X1'}
    steps = [_step('normal', odd, no_disp),
             _step('i_ac', dict(odd, **TRACKING['i_ac']), no_disp),
             _step('i_off', {'SELECT:CH3?': 'X0', 'SELECT:CH2?': 'X1'},
                   no_disp),
             _step('stopped', dict(odd, **TRACKING['stopped']), no_disp,
                   FROZEN)]
    assert probe.restore_verdict(steps, _now(odd, failed=no_disp),
                                 ICH, VCH)[0] is True
    state, lines = probe.restore_verdict(
        steps, _now({'SELECT:CH3?': 'X0', 'SELECT:CH2?': 'X1'},
                    failed=no_disp), ICH, VCH)
    assert state is False and "SELECT:CH3? reads 'X0'" in _flat(lines)
    state, lines = probe.restore_verdict(
        steps, _now({'SELECT:CH3?': 'X9', 'SELECT:CH2?': 'X1'},
                    failed=no_disp), ICH, VCH)
    assert state is None
    assert "SELECT:CH3? gave 'X9', which the probe cannot judge" in \
        _flat(lines)


def test_restore_verdict_reads_after_the_reads_and_single():
    # stopped while the reads ran: the second read of the queries says so
    state, lines = probe.restore_verdict(
        _walk_steps(), _now(after={'ACQUIRE:STATE?': '0'}), ICH, VCH)
    assert state is False and "ACQUIRE:STATE? reads '0'" in _flat(lines)
    # Single armed: acquiring now, stopped after one record
    for view in ('before', 'after'):
        now = (_now({'ACQUIRE:STOPAFTER?': 'SEQ'}) if view == 'before'
               else _now(after={'ACQUIRE:STOPAFTER?': 'SEQUENCE'}))
        state, lines = probe.restore_verdict(_walk_steps(), now, ICH, VCH)
        assert state is False and 'Single' in _flat(lines), view


def test_restore_verdict_judges_the_watchdogs_own_read():
    state, lines = probe.restore_verdict(
        _walk_steps(), _now(reads=(('9.91E+37', 'offscreen'),) * 3),
        ICH, VCH)
    assert state is False
    assert "the watchdog's own read of CH3: 3 of 3 not a readable current" \
        in _flat(lines)
    # identical reads, and this walk showed identical means stopped here
    state, lines = probe.restore_verdict(_walk_steps(), _now(reads=FROZEN),
                                         ICH, VCH)
    assert state is None and 'as the reads did while the scope was stopped' \
        in _flat(lines)
    # ...but not when normal use repeated too: no evidence either way
    steps = _walk_steps()
    steps[0] = _step('normal', reads=FROZEN)
    assert probe.restore_verdict(steps, _now(reads=FROZEN),
                                 ICH, VCH)[0] is True


def test_restore_verdict_cannot_confirm_what_it_never_saw():
    # the walk stopped at the start: nothing proven, nothing confirmed
    state, lines = probe.restore_verdict(_walk_steps()[:1], _now(), ICH, VCH)
    assert state is None
    for prop in ('CH3 (I_Out) coupling', 'CH3 (I_Out) on/off',
                 'CH2 (V_Out) coupling', 'CH2 (V_Out) on/off',
                 'acquisition'):
        assert prop + ': no query' in _flat(lines), prop
    # a proven query that stopped answering
    state, lines = probe.restore_verdict(
        _walk_steps(), _now(failed=['SELECT:CH3?',
                                    'DISPLAY:GLOBAL:CH3:STATE?']), ICH, VCH)
    assert state is None and 'gave no reply' in _flat(lines)
    # ...even when the other proven on/off query reads on: every query the
    # walk proved must agree before the probe vouches for the property
    state, lines = probe.restore_verdict(
        _walk_steps(), _now(failed=['DISPLAY:GLOBAL:CH3:STATE?']), ICH, VCH)
    assert state is None
    assert ('CH3 (I_Out) on/off: DISPLAY:GLOBAL:CH3:STATE? gave no reply'
            in _flat(lines))


def test_reading_judges_an_uninterpreted_reply_only_with_proof():
    r = probe._reading
    on_off = (probe.parse_on_off, True)
    assert r('1', *on_off, None, '1', True) == 'good'      # face value
    assert r('0', *on_off, None, '1', True) == 'bad'
    assert r(None, *on_off, ('1', '0'), '1', True) is None
    # a reply it cannot interpret: nothing without proof...
    assert r('X1', *on_off, None, 'X1', True) is None
    # ...and with it, only the walk's own two replies mean anything
    proof = ('X1', 'X0')
    assert r('X1', *on_off, proof, 'X1', True) == 'good'
    assert r('X0', *on_off, proof, 'X1', True) == 'bad'
    assert r('X9', *on_off, proof, 'X1', True) is None
    # on V_Out's channel only its own normal-use reply counts
    assert r('X1', *on_off, proof, 'X1', False) == 'good'
    assert r('X0', *on_off, proof, 'X1', False) is None


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
    assert steps['i_ac']['moves'] == ['CH3:COUPLING?']
    assert report['restore']['restored'] is True
    assert len(report['restore']['attempts']) == 1
    assert fake.running and fake.on[ICH] and fake.coupling[ICH] == 'DC'
    summary = _flat(probe.walk_summary_lines(report))
    assert summary.count('FOLLOWS the front panel') == 3


def test_walk_flags_a_query_that_did_not_move():
    fake = probe._FakeScope()
    report = _walk(fake, _Bench(fake, actions={'i_ac': None}))
    normal, i_ac = report['steps'][0], report['steps'][1]
    flat = _flat(probe.step_lines(i_ac, normal, ICH, VCH))
    assert "CH3:COUPLING?: still 'DC' -- did NOT move" in flat
    # and so it can vouch for nothing at the end
    assert report['restore']['restored'] is None
    assert 'CH3 (I_Out) coupling: no query' in _flat(
        report['restore']['attempts'][-1]['verdict'])


def test_walk_flags_a_change_left_over_from_an_earlier_step():
    fake = probe._FakeScope()
    bench = _Bench(fake, actions={'i_off': lambda f: f.set_on(ICH, False)})
    report = _walk(fake, bench)
    normal, i_off = report['steps'][0], report['steps'][2]
    flat = _flat(probe.step_lines(i_off, normal, ICH, VCH))
    assert "CH3:COUPLING?: 'DC' -> 'AC' -- not this step's change" in flat
    assert report['restore']['restored'] is True


def test_walk_asks_again_until_the_scope_is_back():
    fake = probe._FakeScope()
    bench = _Bench(fake, restores=[None, _Bench.PUT_RIGHT])
    report = _walk(fake, bench)
    attempts = report['restore']['attempts']
    assert bench.asked.count('restored') == 2
    assert [a['state'] for a in attempts] == [False, True]
    assert "acquisition: ACQUIRE:STATE? reads '0'" in _flat(
        attempts[0]['verdict'])
    assert report['restore']['restored'] is True
    detail = _flat(probe.walk_detail_lines(report))
    assert 'restored (read 2):' in detail
    summary = probe.walk_summary_lines(report)
    assert 'RESTORED' in _flat(summary)
    assert 'put the scope back' not in _flat(summary)
    # the table's last column is the LAST read, the one the verdict is on
    row = [ln for ln in summary if ln.split()[:1] == ['ACQUIRE:STATE?']]
    assert row[0].split()[1:] == ['1', '1', '1', '0', '1']


def test_walk_left_unready_says_so_and_exits_nonzero():
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
    assert ('CH3 (I_Out) and CH2 (V_Out) DC-coupled and on, and the scope '
            'running continuously (Run/Stop, not Single)') in flat


def test_walk_not_confirmed_exits_nonzero_and_says_check_the_screen():
    fake = probe._FakeScope()
    bench = _Bench(fake, actions={'i_ac': None})
    with tempfile.TemporaryDirectory() as tmp:
        rc = _quiet(probe.run_walk, fake, _args(os.path.join(tmp, 'p')),
                    operator=bench, sleep=lambda s: None)
    assert rc == 1 and bench.asked.count('restored') == 1


def test_walk_stopped_before_the_check_is_not_called_restored():
    fake = probe._FakeScope()
    report = _walk(fake, _Bench(fake, restores=[]))     # q at restore
    assert report['restore'] == {'restored': None, 'attempts': []}
    summary = _flat(probe.walk_summary_lines(report))
    assert 'NOT CHECKED' in summary and 'put the scope back' in summary


def test_walk_quit_midway_cannot_confirm_what_it_never_tested():
    fake = probe._FakeScope()
    bench = _Bench(fake, actions={'stopped': 'q'})
    report = _walk(fake, bench)
    assert [s['name'] for s in report['steps']] == ['normal', 'i_ac', 'i_off']
    assert report['restore']['restored'] is None
    assert 'acquisition: no query' in _flat(
        report['restore']['attempts'][-1]['verdict'])
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
    assert 'NOT READY FOR A LIVE RUN' in summary      # the last read, kept


def test_walk_does_not_spin_on_a_query_the_scope_never_answers():
    fake = _Panel(SELECT_CH3Q=_VisaTimeout('timeout'),
                  SELECT_CH2Q=_VisaTimeout('timeout'))
    bench = _Bench(fake)
    report = _walk(fake, bench)
    assert bench.asked.count('restored') == 1
    assert report['restore']['restored'] is None
    normal, i_off = report['steps'][0], report['steps'][2]
    flat = _flat(probe.step_lines(i_off, normal, ICH, VCH))
    assert 'SELECT:CH3?: no reply at the start or now' in flat
    summary = _flat(probe.walk_summary_lines(report))
    assert 'NOT CONFIRMED' in summary and 'put the scope back' in summary
    assert 'CH3 (I_Out) on/off: no query this walk showed' in summary


def test_walk_never_trusts_a_query_that_ignored_the_panel():
    # the #337-review finding, end to end: SELECT? answers 1 whatever the
    # panel does, DISPLAY follows it, and the operator never turns CH3
    # back on. The walk must end NOT READY, exit 1 and say put it back.
    fake = _Panel(SELECT_CH3Q='1', SELECT_CH2Q='1',
                  DISPLAY_GLOBAL_CH3_STATEQ=lambda s: '1' if s.on[3] else '0',
                  DISPLAY_GLOBAL_CH2_STATEQ=lambda s: '1' if s.on[2] else '0')
    bench = _Bench(fake, actions={'stopped': lambda f: f.set_running(False)},
                   restores=[lambda f: f.set_running(True), 'q'])
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'p')
        rc = _quiet(probe.run_walk, fake, _args(out), operator=bench,
                    sleep=lambda s: None)
        text = _flat([_read(out + '_walk.txt')])
    assert rc == 1
    assert "SELECT:CH3? did NOT follow the front panel" in text
    assert "DISPLAY:GLOBAL:CH3:STATE? FOLLOWS the front panel" in text
    assert ("NOT READY FOR A LIVE RUN -- put these right on the front "
            "panel: CH3 (I_Out) on/off: DISPLAY:GLOBAL:CH3:STATE? reads "
            "'0'") in text
    assert 'put the scope back' in text


def test_walk_stuck_coupling_query_is_not_confirmed():
    # CH3:COUPLING? says DC whatever the panel does; the operator leaves
    # CH3 on AC. Nothing can vouch for the coupling: NOT CONFIRMED.
    fake = _Panel(CH3_COUPLINGQ='DC')
    bench = _Bench(fake, actions={'i_off': lambda f: f.set_on(ICH, False)},
                   restores=[lambda f: f.set_running(True)])
    report = _walk(fake, bench)
    assert fake.coupling[ICH] == 'AC'
    assert report['restore']['restored'] is None
    assert 'CH3 (I_Out) coupling: no query' in _flat(
        report['restore']['attempts'][-1]['verdict'])


def test_walk_catches_a_scope_that_stops_while_it_reads():
    class StopsMidRead(probe._FakeScope):
        """Stops acquiring on the second read after being armed."""
        armed, reads = False, 0

        def ask(self, cmd):
            if cmd == 'MEASUREMENT:IMMED:VALUE?' and self.armed:
                self.reads += 1
                if self.reads == 2:
                    self.set_running(False)
            return super().ask(cmd)
    fake = StopsMidRead()

    def put_right_then_stop(f):
        _Bench.PUT_RIGHT(f)
        f.armed = True
    report = _walk(fake, _Bench(fake, restores=[put_right_then_stop]))
    last = report['restore']['attempts'][-1]
    assert last['replies']['ACQUIRE:STATE?']['reply'] == '1'   # before
    assert last['after']['ACQUIRE:STATE?']['reply'] == '0'     # after
    assert report['restore']['restored'] is False
    assert "it changed while they ran" in _flat(
        probe.step_lines(last, report['steps'][0], ICH, VCH))


def test_walk_single_armed_is_not_ready():
    fake = _Panel(ACQUIRE_STOPAFTERQ=lambda s: s.stopafter)

    def press_single(f):
        _Bench.PUT_RIGHT(f)
        f.stopafter = 'SEQUENCE'
    report = _walk(fake, _Bench(fake, restores=[press_single]))
    assert report['restore']['restored'] is False
    assert 'Single' in _flat(report['restore']['attempts'][-1]['verdict'])


def test_walk_catches_single_pressed_while_it_reads():
    class SingleMidRead(_Panel):
        """Single pressed during the restore's reads: only the second read
        of ACQUIRE:STOPAFTER? can see it."""
        armed, reads = False, 0

        def ask(self, cmd):
            if cmd == 'MEASUREMENT:IMMED:VALUE?' and self.armed:
                self.reads += 1
                if self.reads == 2:
                    self.stopafter = 'SEQUENCE'
            return super().ask(cmd)
    fake = SingleMidRead(ACQUIRE_STOPAFTERQ=lambda s: s.stopafter)

    def put_right_then_single(f):
        _Bench.PUT_RIGHT(f)
        f.armed = True
    report = _walk(fake, _Bench(fake, restores=[put_right_then_single]))
    last = report['restore']['attempts'][-1]
    assert last['replies']['ACQUIRE:STOPAFTER?']['reply'] == 'RUNSTOP'
    assert last['after']['ACQUIRE:STOPAFTER?']['reply'] == 'SEQUENCE'
    assert report['restore']['restored'] is False
    assert 'Single' in _flat(last['verdict'])


def test_walk_notices_a_change_while_its_reads_run():
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
    assert ("SELECT:CH3?: '0' before the reads, '1' after -- it changed "
            "while they ran") in flat
    assert 'while they ran' not in _flat(
        probe.step_lines(report['steps'][1], normal, ICH, VCH))


def test_walk_warns_when_the_start_reads_blind():
    fake = probe._FakeScope()
    fake.set_coupling(ICH, 'AC')              # left AC before the walk
    report = _walk(fake, _Bench(fake))
    normal = report['steps'][0]
    flat = _flat(probe.step_lines(normal, normal, ICH, VCH))
    assert 'WARNING: the start reads blind for a LIVE run' in flat
    assert 'CH3 (I_Out) reads AC-coupled' in flat
    # the coupling query never showed it follows the panel, so the end is
    # NOT CONFIRMED -- and it is never told to put the AC back
    last = report['restore']['attempts'][-1]
    assert last['state'] is None and fake.coupling[ICH] == 'DC'
    assert 'CH3 (I_Out) coupling: no query' in _flat(last['verdict'])


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


def test_walk_table_reads_values_through_a_header():
    # HEADER ON: a cut-off raw reply would read ':CH3:COUP' in every cell
    cols = [{'name': n, 'reads': [], 'replies': _replies(
        [('CH3:COUPLING?', f':CH3:COUPLING {c}'), ('ACQUIRE:STATE?', '')])}
        for n, c in (('normal', 'DC'), ('i_ac', 'AC'))]
    rows = {ln.split()[0]: ln.split()[1:]
            for ln in probe.walk_table(cols, ICH)[1:]}
    assert rows['CH3:COUPLING?'] == ['DC', 'AC']
    assert rows['ACQUIRE:STATE?'] == ["''", "''"]


def test_console_operator_stops_on_a_closed_stdin():
    real = builtins.input

    def closed(prompt=''):
        raise EOFError
    builtins.input = closed
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            typed = probe._console_operator(
                'i_ac', 'Step 2 of 5 (i_ac): Set CH3 (I_Out) to AC coupling.')
            with tempfile.TemporaryDirectory() as tmp:
                rc = probe.run_walk(probe._FakeScope(),
                                    _args(os.path.join(tmp, 'p')),
                                    sleep=lambda s: None)
    finally:
        builtins.input = real
    assert typed == 'q' and '>>> Step 2 of 5 (i_ac)' in out.getvalue()
    assert rc == 1            # stopped at the first prompt, never looped


# ------------------------------------------------------ safety / audit
def test_probe_only_queries_on_the_real_driver():
    # SAFETY in the probe's docstring: after connecting, MEASUREMENT:IMMED
    # TYPE/SOURCE are its only writes. Held on the real driver, both
    # modes, every command.
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
    # nothing moved, so nothing is proven, so nothing is confirmed
    assert report['restore']['restored'] is None
    sent = scope.inst.sent
    for cmd in sent:
        assert cmd.endswith('?') or cmd.split(' ')[0] in (
            'MEASUREMENT:IMMED:TYPE', 'MEASUREMENT:IMMED:SOURCE'), cmd
    for q in ('CH3:COUPLING?', 'SELECT:CH3?', 'CH2:COUPLING?',
              'SELECT:CH2?', 'DISPLAY:GLOBAL:CH3:STATE?', 'ACQUIRE:STATE?',
              'TRIGGER:A:MODE?', 'TRIGGER:A:EDGE:SOURCE?'):
        assert q in sent, q


def test_main_sends_only_the_connect_sequence_and_queries():
    # The whole program, through the real TekMSO24 constructor: what the
    # docstring's SAFETY note says reaches the scope, and nothing else.
    import instruments
    replies = {'*IDN?': 'TEKTRONIX,MSO24,TEST,1.0',
               'MEASUREMENT:IMMED:VALUE?': '-8.1E-2', 'ACQUIRE:STATE?': '1',
               'CH3:COUPLING?': 'DC', 'CH2:COUPLING?': 'DC',
               'SELECT:CH3?': '1', 'SELECT:CH2?': '1'}
    real_rm, real_op = instruments.get_resource_manager, probe._console_operator
    real_tick = probe.WATCHDOG_TICK_S
    sessions = []

    def rm():
        sessions.append(_Session(replies))
        return _RM(sessions[-1])
    instruments.get_resource_manager = rm
    probe._console_operator = lambda step, text: (
        'q' if step == 'restored' else '')
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'p')
            base = ['--resource', 'USB0::0x0699::0x0105::TEST::INSTR',
                    '--out', out]
            assert _quiet(probe.main, base + ['--samples', '2',
                                              '--timing-samples', '2']) == 0
            # main() cannot be handed a sleep: without this the walk
            # paces its reads at the real 0.5 s and the suite waits 10 s
            probe.WATCHDOG_TICK_S = 0.0
            assert _quiet(probe.main, base + ['--walk']) == 1
    finally:
        instruments.get_resource_manager = real_rm
        probe._console_operator = real_op
        probe.WATCHDOG_TICK_S = real_tick
    assert len(sessions) == 2
    for s in sessions:
        assert s.sent[:4] == ['<device clear>', '*IDN?',
                              'DATA:ENCDG RIBINARY', 'DATA:WIDTH 2'], s.sent[:4]
        for cmd in s.sent[4:]:
            assert cmd.endswith('?') or cmd.split(' ')[0] in (
                'MEASUREMENT:IMMED:TYPE', 'MEASUREMENT:IMMED:SOURCE'), cmd
        assert 'CH3:COUPLING?' in s.sent


def test_the_same_channel_for_both_monitors_is_refused():
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            probe.main(['--selftest', '--ich', '3', '--vch', '3'])
        raise AssertionError("--ich 3 --vch 3 was accepted")
    except SystemExit as e:
        assert e.code == 2
    assert 'different channels' in err.getvalue()


def test_walk_outputs_are_gitignored():
    # Run data never enters the repo: the walk's and the selftest's files
    # must fall under the patterns that keep the probe's own report out.
    with open(os.path.join(ROOT, '.gitignore'), encoding='utf-8') as f:
        pats = [ln.strip() for ln in f
                if ln.strip() and not ln.startswith('#')]
    for stem in ('', '_walk', '_selftest', '_selftest_walk'):
        for ext in ('.txt', '.json'):
            name = probe.DEFAULT_OUT + stem + ext
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


def test_selftest_never_writes_over_a_real_report():
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            real = ('sldea_watchdog_probe.txt', 'sldea_watchdog_probe_walk.txt')
            for name in real:
                with open(name, 'w', encoding='utf-8') as f:
                    f.write('REAL')
            assert _quiet(probe.main, ['--selftest', '--walk']) == 0
            assert _quiet(probe.main, ['--selftest', '--samples', '2',
                                       '--timing-samples', '2']) == 0
            assert [_read(name) for name in real] == ['REAL', 'REAL']
            assert os.path.exists('sldea_watchdog_probe_selftest_walk.txt')
            assert os.path.exists('sldea_watchdog_probe_selftest.txt')
        finally:
            os.chdir(cwd)


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
