#!/usr/bin/env python3
"""The background video jobs say how far they have got, and run low
(#396, 2026-10-06).

After an SLDEA run with video, a separate program moves the recording
into the run folder (detecting edges on every frame first, when asked),
and Edge Review's Save may start another to re-run that detection. Both
reported only to run.log, ran on every core, and on Windows at normal
priority. What these pin down:

  * a job's progress record is replaced whole: at most once a second
    while busy, at once on a phase change and for its last word; it
    never raises;
  * progress_text says in words what the job is doing, how far it is,
    when it has gone quiet, and how it ended;
  * detect_video and the copy into the run folder report their progress
    and write exactly what they wrote before; run.log is unchanged;
  * the launchers announce a job in its record before it exists and
    start it detached and low (BELOW_NORMAL on Windows, a session of its
    own elsewhere); a job nobody launched writes no record;
  * on Linux a job lowers its own autogroup, and only when it leads its
    session;
  * OpenCV is held to half the cores while a job detects, which changes
    no byte of video_edges.csv;
  * the SLDEA tab's job line follows a run's jobs from a stat and a small
    read, reports a re-run after Save, says when a job ended without its
    last word or went quiet, and stops polling once nothing is left.

The job-line tests need tkinter (gui.py), the detection tests OpenCV with
FFV1; the rest is stdlib and also runs on Linux (WSL).

Run: .venv/bin/python tests/test_sldea_video_jobs.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import sldea_video as sv

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Skip(Exception):
    """Could not run here -- reported, never counted as a pass."""


class _Env:
    """Points the staging root at a temporary folder (and clears the job
    record variable) for the length of a test; restores both."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix='sldea_jobs_')
        self.saved = {k: os.environ.get(k) for k in
                      ('SCPI_SLDEA_VIDEO_STAGING', sv.JOB_PROGRESS_ENV)}
        os.environ['SCPI_SLDEA_VIDEO_STAGING'] = os.path.join(self.tmp,
                                                              'staging')
        os.environ.pop(sv.JOB_PROGRESS_ENV, None)
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def _record(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


# ------------------------------------------------------- the record itself

def test_the_record_is_written_whole_once_a_second_and_never_raises():
    with _Env() as env:
        clock = _Clock()
        path = os.path.join(env.tmp, 'p', 'RUN_x.json')
        p = sv.JobProgress(os.path.join(env.tmp, 'RUN'), 'finalize',
                           path=path, clock=clock)
        p.update('detect', 1, 10)          # the first word is written
        assert _record(path)['done'] == 1
        clock.t += 0.5
        p.update('detect', 2, 10)          # too soon: kept, not written
        assert _record(path)['done'] == 1 and p.rec['done'] == 2
        clock.t += 0.5
        p.update('detect', 3, 10)          # a second on: written
        rec = _record(path)
        assert (rec['done'], rec['total'], rec['t']) == (3, 10, clock.t)
        clock.t += 0.1
        p.update('copy', 100, 1000, what=sv.VIDEO_FILENAME)  # new phase
        rec = _record(path)
        assert rec['phase'] == 'copy' and rec['phase_started'] == clock.t
        assert (rec['done'], rec['total'], rec['what']) == (
            100, 1000, sv.VIDEO_FILENAME), rec
        clock.t += 0.1
        assert p.finish(True, 'ready in the run folder')
        rec = _record(path)
        assert rec['phase'] == 'done' and rec['text'] == \
            'ready in the run folder' and rec['warn'] is False, rec
        assert 'done' not in rec and 'what' not in rec, rec
        assert rec['job'] == 'finalize' and rec['run'] == 'RUN', rec
        assert not [n for n in os.listdir(os.path.dirname(path))
                    if n.endswith('.part')]
        # a record that cannot be written costs nothing but itself
        blocker = os.path.join(env.tmp, 'a_file')
        open(blocker, 'w').close()
        bad = sv.JobProgress(env.tmp, 'rerun',
                             path=os.path.join(blocker, 'x.json'),
                             clock=clock)
        bad.update('detect', 1, 2)
        bad.update('copy', 1, 2)
        assert bad.write() is False
        assert bad.finish(False, 'x') is False


def test_the_job_line_says_what_how_far_and_how_it_ended():
    base = {'run': 'R', 't': 1000.0, 'phase_started': 990.0}

    def say(now=1000.0, **rec):
        return sv.progress_text(dict(base, **rec), now=now)
    assert say(job='finalize', phase='starting') == (
        "video of R: starting the post-run job", 'busy')
    assert say(job='rerun', phase='starting') == (
        "video of R: starting the edge re-run after Save", 'busy')
    # the rate is quoted once the phase has run 5 s: 100 frames in 10 s,
    # so 300 frames to go take 30 s
    assert say(job='finalize', phase='detect', done=100, total=400) == (
        "video of R: detecting edges 100/400, about 30 s left", 'busy')
    assert say(job='finalize', phase='detect', done=1, total=438,
               phase_started=998.0) == (
        "video of R: detecting edges 1/438", 'busy')
    assert say(job='rerun', phase='detect', done=3, total=10)[0] == (
        "video of R: re-running edge detection after Save 3/10, about 23 "
        "s left")
    assert say(job='finalize', phase='detect', done=10, total=610)[0] == (
        "video of R: detecting edges 10/610, about 10 min left")
    assert say(job='finalize', phase='copy', done=int(1.2e9),
               total=int(2.3e9), what='video.mkv')[0].startswith(
        "video of R: copying video.mkv into the run folder, 1.2 GB of "
        "2.3 GB, about 9 s left")
    assert say(job='finalize', phase='done', text='ready') == (
        "video of R: ready", 'done')
    assert say(job='finalize', phase='done', text='ready, but x',
               warn=True) == ("⚠ video of R: ready, but x", 'warn')
    assert say(job='rerun', phase='failed', text='it broke') == (
        "⚠ video of R: it broke; see run.log", 'warn')
    # a busy record that stopped changing: said, with what it last said
    text, level = say(now=1000.0 + sv.PROGRESS_STALE_S + 60.0,
                      job='finalize', phase='detect', done=5, total=10)
    assert level == 'warn' and text.startswith(
        "⚠ video of R: no word from the job for 3 min (it last said: "
        "detecting edges 5/10"), text
    assert text.endswith("; see run.log"), text
    # a damaged record is still a line, never a traceback
    assert sv.progress_text({'phase': 'detect', 'done': 'x', 'total': None,
                             't': 'y'}, now=5.0)[1] == 'busy'
    assert sv.progress_text({}, now=1.0) == (
        "video of the run: starting the post-run job", 'busy')


def test_the_record_is_local_one_per_run_and_named_for_people():
    with _Env() as env:
        a = os.path.join(env.tmp, 'share1', 'SLDEA_20261006_101500')
        b = os.path.join(env.tmp, 'share2', 'SLDEA_20261006_101500')
        pa = sv.progress_path(a)
        assert os.path.dirname(pa) == os.path.join(
            sv.staging_root(), sv.PROGRESS_DIRNAME)
        assert os.path.basename(pa).startswith('SLDEA_20261006_101500_')
        assert pa != sv.progress_path(b), "two runs share a record"
        assert pa == sv.progress_path(a + os.sep)
        assert pa == sv.progress_path(os.path.join(a, '.'))


def test_old_records_are_cleared_when_a_job_starts():
    with _Env() as env:
        folder = os.path.join(env.tmp, 'progress')
        os.makedirs(folder)
        old, new, other = (os.path.join(folder, n) for n in
                           ('old.json', 'new.json', 'notes.txt'))
        for p in (old, new, other):
            open(p, 'w').close()
        past = time.time() - sv.PROGRESS_KEEP_S - 60
        os.utime(old, (past, past))
        os.utime(other, (past, past))
        os.environ[sv.JOB_PROGRESS_ENV] = os.path.join(folder, 'mine.json')
        prog = sv.job_progress(os.path.join(env.tmp, 'RUN'), 'finalize')
        assert sorted(os.listdir(folder)) == ['mine.json', 'new.json',
                                              'notes.txt']
        rec = _record(prog.path)
        assert rec['phase'] == 'starting' and rec['pid'] == os.getpid()


# ------------------------------------------------- launching a job

class _Popen:
    """Records what a launcher asked for, and the record as it stood at
    that moment."""

    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, cmd, **kw):
        path = kw['env'].get(sv.JOB_PROGRESS_ENV)
        self.calls.append((cmd, kw, sv.read_progress(path)
                           if path else None))
        if self.fail:
            raise self.fail
        return 'proc'


def test_the_launchers_announce_the_job_and_start_it_detached_and_low():
    with _Env() as env:
        run = os.path.join(env.tmp, 'SLDEA_20261006_101500')
        stage = os.path.join(env.tmp, 'staging', 'SLDEA_x_stage')
        # a variable the GUI itself inherited never reaches the job
        os.environ[sv.JOB_PROGRESS_ENV] = 'inherited.json'
        popen = _Popen()
        assert sv.launch_finalize(stage, run, True, popen=popen) == 'proc'
        assert sv.launch_rerun(run, popen=popen) == 'proc'
        (c1, kw1, rec1), (c2, kw2, rec2) = popen.calls
        assert c1[1].endswith('sldea_video.py'), c1
        assert c1[2:] == ['--finalize', stage, run, '--detect'], c1
        assert c2[2:] == [run, '--after-save'], c2
        for kw, job, rec in ((kw1, 'finalize', rec1), (kw2, 'rerun', rec2)):
            assert kw['env'][sv.JOB_PROGRESS_ENV] == sv.progress_path(run)
            assert kw['env']['PYTHONIOENCODING'] == 'utf-8'
            for k in ('stdin', 'stdout', 'stderr'):
                assert kw[k] == subprocess.DEVNULL, (k, kw)
            if os.name == 'nt':
                flags = kw['creationflags']
                for name in ('BELOW_NORMAL_PRIORITY_CLASS',
                             'DETACHED_PROCESS', 'CREATE_NEW_PROCESS_GROUP'):
                    assert flags & getattr(subprocess, name), (name, flags)
                assert 'start_new_session' not in kw
            else:
                assert kw['start_new_session'] is True, kw
            # announced BEFORE the program existed
            assert rec and rec['phase'] == 'starting' and \
                rec['job'] == job, rec
        assert sv.launch_finalize(stage, run, False,
                                  popen=_Popen()) == 'proc'
        # a launch that fails says so in the record, and still raises
        try:
            sv.launch_rerun(run, popen=_Popen(fail=OSError('no fork')))
        except OSError:
            pass
        else:
            raise AssertionError("the failed launch did not raise")
        rec = sv.read_progress(sv.progress_path(run))
        assert rec['phase'] == 'failed' and rec['text'] == (
            'the edge re-run after Save could not start (no fork)'), rec


def _staged(folder, size=3 << 20):
    """A staging folder holding a stand-in recording (bytes, not video)
    and its index: enough for a move with no detection."""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, sv.VIDEO_FILENAME), 'wb') as f:
        f.write(os.urandom(size))
    with open(os.path.join(folder, sv.VIDEO_INDEX_FILENAME), 'w',
              newline='') as f:
        csv.writer(f).writerow(sv.INDEX_COLUMNS)
    return folder


def _log_body(path):
    """run.log without the [HH:MM:SS] stamps."""
    with open(path, encoding='utf-8') as f:
        return [line.split('] ', 1)[1] for line in f.read().splitlines()]


def test_a_job_reports_its_copy_and_says_nothing_new_in_run_log():
    """The post-run job across volumes (a forced copy): with a launcher's
    record it reports the copy in bytes and ends "ready in the run
    folder"; without one it writes no record at all. run.log reads the
    same either way."""
    with _Env() as env:
        logs = []
        writes = []
        real_replace, real_write = sv.os.replace, sv.JobProgress.write

        def spy_write(self, now=None):
            writes.append(dict(self.rec))
            return real_write(self, now)
        try:
            sv.JobProgress.write = spy_write
            for watched in (False, True):
                stage = _staged(os.path.join(env.tmp, f'stage{watched}'))
                run = os.path.join(env.tmp, f'run{watched}')
                os.makedirs(run)

                def cross_device(src, dst, _stage=stage):
                    if os.path.dirname(os.path.abspath(src)) == \
                            os.path.abspath(_stage):
                        raise OSError(18, 'Invalid cross-device link')
                    return real_replace(src, dst)
                sv.os.replace = cross_device
                if watched:
                    os.environ[sv.JOB_PROGRESS_ENV] = sv.progress_path(run)
                else:
                    os.environ.pop(sv.JOB_PROGRESS_ENV, None)
                assert sv.main(['--finalize', stage, run]) == 0
                sv.os.replace = real_replace
                logs.append(_log_body(os.path.join(run, 'run.log')))
                if not watched:
                    assert not os.path.exists(os.path.join(
                        sv.staging_root(), sv.PROGRESS_DIRNAME)), \
                        "a job nobody launched wrote a record"
                    assert not writes, writes
            rec = sv.read_progress(sv.progress_path(run))
            assert rec['phase'] == 'done' and rec['job'] == 'finalize', rec
            assert rec['text'] == 'ready in the run folder', rec
            copies = [w for w in writes if w['phase'] == 'copy']
            assert copies and copies[0]['what'] == sv.VIDEO_FILENAME, writes
            assert copies[0]['total'] == 3 << 20, copies[0]
            assert logs[0] == logs[1], logs
            assert logs[0] == [f"video: {sv.VIDEO_FILENAME} is in the run "
                               f"folder", f"video: {sv.VIDEO_INDEX_FILENAME}"
                               f" is in the run folder"], logs
        finally:
            sv.os.replace, sv.JobProgress.write = real_replace, real_write


def test_a_copy_reports_bytes_and_a_stand_in_with_the_old_signature_runs():
    """_copy_throttled reports each chunk; finalize passes the file's name
    with it, and calls a copy that takes no `progress` exactly as before
    when nobody listens (the existing move tests replace it with one)."""
    with _Env() as env:
        src = os.path.join(env.tmp, 'src.bin')
        with open(src, 'wb') as f:
            f.write(b'x' * 2500)
        seen = []
        sv._copy_throttled(src, src + '.copy', max_bps=None, chunk=1000,
                           progress=lambda n, t: seen.append((n, t)))
        assert seen == [(1000, 2500), (2000, 2500), (2500, 2500)], seen
        real_replace, real_copy = sv.os.replace, sv._copy_throttled
        stage = _staged(os.path.join(env.tmp, 'stage'), size=10)
        run = os.path.join(env.tmp, 'run')
        os.makedirs(run)
        old_style = []

        def copy(src, dst, max_bps=None, chunk=0):
            old_style.append(os.path.basename(src))
            return real_copy(src, dst, max_bps)

        def cross_device(s, d):
            if os.path.dirname(os.path.abspath(s)) == os.path.abspath(stage):
                raise OSError(18, 'Invalid cross-device link')
            return real_replace(s, d)
        try:
            sv.os.replace, sv._copy_throttled = cross_device, copy
            moved = sv.finalize(stage, run, log=lambda m: None)
            assert all(moved.values()), moved
            assert old_style == [sv.VIDEO_FILENAME, sv.VIDEO_INDEX_FILENAME]
        finally:
            sv.os.replace, sv._copy_throttled = real_replace, real_copy


def test_lower_job_priority_never_raises_on_this_platform():
    """In a fresh process (it would lower this one for good): whatever the
    platform, the job's own priority step runs through without an
    exception. On Windows it has nothing to do; the launcher set the
    priority class."""
    out = subprocess.run(
        [sys.executable, '-c', 'import sys; sys.path.insert(0, sys.argv[1]);'
         ' import sldea_video as sv; sv.lower_job_priority(); print("ok")',
         REPO], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip() == 'ok', (
        out.returncode, out.stdout, out.stderr)


_PRIORITY_PROBE = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
import sldea_video as sv
def autogroup():
    try:
        with open('/proc/self/autogroup') as f:
            return f.read().strip()
    except OSError:
        return None
before = autogroup()
sv.lower_job_priority()
print(repr((os.nice(0), before, autogroup(), os.getsid(0) == os.getpid())))
'''


def test_on_linux_the_job_lowers_its_autogroup_only_as_session_leader():
    """A job started the way the launchers start it (a session of its
    own) ends at nice JOB_NICE with its autogroup at JOB_NICE as well. A
    job run inside someone else's session (a terminal) lowers its own
    nice only, and leaves that session's autogroup alone. Linux only."""
    if not sys.platform.startswith('linux'):
        raise _Skip("autogroups are Linux's")
    cmd = [sys.executable, '-c', _PRIORITY_PROBE, REPO]
    lead = eval(subprocess.run(cmd, capture_output=True, text=True,
                               start_new_session=True,
                               check=True).stdout.strip())
    inside = eval(subprocess.run(cmd, capture_output=True, text=True,
                                 check=True).stdout.strip())
    base = os.nice(0)
    assert lead[3] is True and inside[3] is False, (lead, inside)
    assert lead[0] == min(19, base + sv.JOB_NICE), lead
    assert inside[0] == min(19, base + sv.JOB_NICE), inside
    if lead[1] is None:
        raise _Skip("this kernel has no /proc/self/autogroup")
    assert lead[2].endswith(f"nice {sv.JOB_NICE}"), lead
    assert inside[2] == inside[1], "a job lowered a session it does not own"


# ------------------------------------------------ detection (OpenCV)

def _need_cv():
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as e:
        raise _Skip(f"no OpenCV/numpy: {e}")
    ok, why = sv.codec_available()
    if not ok:
        raise _Skip(f"this OpenCV cannot write {sv.VIDEO_FOURCC}: {why}")


def _scene(r, rng, size=(240, 320)):
    """test_sldea_video's synthetic rig: a brighter disc that grows with
    voltage, structure on both axes, sensor noise."""
    import numpy as np
    h, w = size
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.full((h, w), 90.0, np.float32)
    img[np.abs(xx - 20) < 6] = 230.0
    img[np.abs(yy - 18) < 5] = 215.0
    if r:
        img[(xx - 160) ** 2 + (yy - 120) ** 2 <= r * r] += 34
    img += rng.normal(0, 1.6, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def _video_run(n, parent):
    """A run folder with a baseline still, data.csv, setup.txt and an FFV1
    recording of a disc growing over `n` frames."""
    import cv2
    import numpy as np
    rng = np.random.default_rng(7)
    d = os.path.join(parent, 'SLDEA_20261006_101500')
    os.makedirs(os.path.join(d, 'frames'))
    cv2.imwrite(os.path.join(d, 'frames', 'base.png'), _scene(0, rng))
    with open(os.path.join(d, 'data.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['snapshot', 'step', 'tag',
                                          'nominal_kV', 'frame_file'])
        w.writeheader()
        w.writerow({'snapshot': 1, 'step': 0, 'tag': 'baseline',
                    'nominal_kV': 0, 'frame_file': 'base.png'})
    with open(os.path.join(d, 'setup.txt'), 'w') as f:
        f.write('DEA nominal diameter: 16 mm\n')
    vw = cv2.VideoWriter(os.path.join(d, sv.VIDEO_FILENAME),
                         cv2.VideoWriter_fourcc(*sv.VIDEO_FOURCC), 1.0,
                         (320, 240), isColor=False)
    with open(os.path.join(d, sv.VIDEO_INDEX_FILENAME), 'w',
              newline='') as f:
        w = csv.writer(f)
        w.writerow(sv.INDEX_COLUMNS)
        buf = None
        try:
            for i in range(n):
                safe, buf = sv.ffmpeg_safe(_scene(30 + 6 * i, rng), buf)
                vw.write(safe)
                w.writerow([i, 2.0 + i, 0.5 * i, '', i + 1])
        except cv2.error as e:
            vw.release()
            raise _Skip(f"this OpenCV's {sv.VIDEO_FOURCC} writer failed "
                        f"mid-file: {e}")
    vw.release()
    return d


def _edges_bytes(d):
    with open(os.path.join(d, sv.VIDEO_EDGES_FILENAME), 'rb') as f:
        return f.read()


def test_detection_reports_every_frame_and_writes_what_it_wrote():
    _need_cv()
    with _Env() as env:
        d = _video_run(8, env.tmp)
        sv.detect_video(d, log=lambda m: None, plot=False)
        plain = _edges_bytes(d)
        seen = []
        sv.detect_video(d, log=lambda m: None, plot=False,
                        progress=lambda n, t: seen.append((n, t)))
        assert _edges_bytes(d) == plain, "progress changed the CSV"
        assert seen == [(n, 8) for n in range(1, 9)], seen
        seen.clear()
        sv.detect_video(d, stride=3, log=lambda m: None, plot=False,
                        progress=lambda n, t: seen.append((n, t)))
        assert seen == [(1, 3), (2, 3), (3, 3)], seen
        seen.clear()
        sv.detect_video(d, limit=2, log=lambda m: None, plot=False,
                        progress=lambda n, t: seen.append((n, t)))
        assert seen == [(1, 2), (2, 2)], seen


def test_half_the_cores_changes_no_byte_of_the_video_edges():
    """The jobs hold OpenCV to half the cores while they detect; the same
    recording measured at every core, at half and at one thread gives
    the same video_edges.csv, byte for byte. The count is put back."""
    _need_cv()
    import cv2
    with _Env() as env:
        d = _video_run(12, env.tmp)
        before = cv2.getNumThreads()
        sv.detect_video(d, log=lambda m: None, plot=False)
        full = _edges_bytes(d)
        old = sv._cap_cv_threads()
        try:
            assert old == before
            assert cv2.getNumThreads() == max(1, (os.cpu_count() or 2) // 2)
            sv.detect_video(d, log=lambda m: None, plot=False)
            half = _edges_bytes(d)
            cv2.setNumThreads(1)
            sv.detect_video(d, log=lambda m: None, plot=False)
            one = _edges_bytes(d)
        finally:
            sv._restore_cv_threads(old)
        assert cv2.getNumThreads() == before
        assert full == half == one, "the thread count changed the edges"


def test_the_finalize_job_reports_frames_then_its_last_word():
    _need_cv()
    with _Env() as env:
        run = _video_run(5, env.tmp)
        stage = os.path.join(env.tmp, 'staging', 'stage1')
        os.makedirs(stage)
        for n in (sv.VIDEO_FILENAME, sv.VIDEO_INDEX_FILENAME):
            shutil.move(os.path.join(run, n), os.path.join(stage, n))
        writes = []
        real_write = sv.JobProgress.write

        def spy(self, now=None):
            writes.append(dict(self.rec))
            return real_write(self, now)
        os.environ[sv.JOB_PROGRESS_ENV] = sv.progress_path(run)
        try:
            sv.JobProgress.write = spy
            assert sv.main(['--finalize', stage, run, '--detect']) == 0
        finally:
            sv.JobProgress.write = real_write
        phases = [w['phase'] for w in writes]
        assert phases[0] == 'starting' and phases[-1] == 'done', phases
        detect = [w for w in writes if w['phase'] == 'detect']
        assert detect and detect[0]['total'] == 5, detect
        rec = sv.read_progress(sv.progress_path(run))
        assert rec['text'].startswith("ready in the run folder, edges of 5 "
                                      "frames ("), rec
        assert rec['warn'] is False, rec


def test_the_rerun_job_reports_and_ends_with_its_word():
    _need_cv()
    with _Env() as env:
        d = _video_run(3, env.tmp)
        os.environ[sv.JOB_PROGRESS_ENV] = sv.progress_path(d)
        assert sv.main([d, '--after-save', '--no-plot']) == 0
        rec = sv.read_progress(sv.progress_path(d))
        assert rec['job'] == 'rerun' and rec['phase'] == 'done', rec
        assert rec['text'].startswith("edges re-run after Save, 3 frames ("),\
            rec
        real = sv.detect_video

        def broken(*a, **k):
            raise RuntimeError('decoder gone')
        try:
            sv.detect_video = broken
            assert sv.main([d, '--after-save', '--no-plot']) == 1
        finally:
            sv.detect_video = real
        rec = sv.read_progress(sv.progress_path(d))
        assert rec['phase'] == 'failed' and rec['text'] == (
            'the edge re-run after Save failed (decoder gone)'), rec
        os.remove(os.path.join(d, sv.VIDEO_FILENAME))
        assert sv.main([d, '--after-save']) == 2
        rec = sv.read_progress(sv.progress_path(d))
        assert rec['phase'] == 'failed' and rec['text'] == (
            f"no {sv.VIDEO_FILENAME} in the run folder"), rec


# ------------------------------------------------ the SLDEA tab's line

class _Root:
    """Records `after` calls instead of running them."""

    def __init__(self):
        self.jobs, self.cancelled, self.n = [], [], 0

    def after(self, ms, fn=None, *a):
        self.n += 1
        self.jobs.append((ms, fn, self.n))
        return self.n

    def after_cancel(self, jid):
        self.cancelled.append(jid)

    def pending(self):
        """The (ms, fn) of the newest job not cancelled, or None."""
        live = [j for j in self.jobs if j[2] not in self.cancelled]
        return live[-1][:2] if live else None


class _Label:
    def __init__(self):
        self.opts, self.packed = {'text': '', 'fg': '#555'}, None

    def cget(self, k):
        return self.opts[k]

    def config(self, **kw):
        self.opts.update(kw)

    def winfo_manager(self):
        return 'pack' if self.packed is not None else ''

    def pack(self, **kw):
        self.packed = kw


class _Proc:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


def _gui():
    try:
        import gui
    except ImportError as e:            # no tkinter (WSL)
        raise _Skip(f"gui.py needs tkinter: {e}")
    return gui


def _line_app():
    """Just enough app for the job line's methods."""
    G = _gui().InstrumentControlGUI

    class App:
        SLDEA_JOB_POLL_MS = G.SLDEA_JOB_POLL_MS
        SLDEA_JOB_IDLE_MS = G.SLDEA_JOB_IDLE_MS
        _sldea_job_watch = G._sldea_job_watch
        _sldea_job_resume = G._sldea_job_resume
        _sldea_job_tick = G._sldea_job_tick
        _sldea_job_show = G._sldea_job_show

        def __init__(self):
            self._sldea_job = None
            self._sldea_edge_procs = []
            self.root = _Root()
            self.sldea_job_line = _Label()

        def text(self):
            return self.sldea_job_line.cget('text')

        def tick(self):
            """Run the pending tick, as Tk would; -> its delay."""
            ms, fn = self.root.pending()
            self.root.jobs.clear()
            fn()
            return ms
    return App()


def _handed(root):
    """The callbacks `root` was asked to run that start the job line."""
    return [fn for _ms, fn, _n in root.jobs
            if '_sldea_job_watch' in getattr(getattr(fn, '__code__', None),
                                             'co_names', ())]


def _say(run, job, phase, **kw):
    p = sv.JobProgress(run, job)
    p.rec.update(phase=phase, **kw)
    if phase in sv.PROGRESS_FINAL:
        assert p.finish(phase == 'done', kw.get('text', ''),
                        kw.get('warn', False))
    else:
        assert p.write()
    return p


def test_the_job_line_follows_the_post_run_job_and_then_stops():
    with _Env() as env:
        app = _line_app()
        run = os.path.join(env.tmp, 'SLDEA_20261006_101500')
        proc = _Proc()
        _say(run, 'finalize', 'starting')
        app._sldea_job_watch(run, proc)
        assert app.text() == ("video of SLDEA_20261006_101500: starting "
                              "the post-run job"), app.text()
        assert app.sldea_job_line.packed is not None
        assert app.root.pending()[0] == app.SLDEA_JOB_POLL_MS
        _say(run, 'finalize', 'detect', done=120, total=438)
        app.tick()
        assert app.text().endswith('detecting edges 120/438'), app.text()
        assert app.sldea_job_line.cget('fg') == '#555'
        _say(run, 'finalize', 'done', text='ready in the run folder')
        proc.code = 0
        app.tick()
        assert app.text().endswith(': ready in the run folder'), app.text()
        assert app.sldea_job_line.cget('fg') == '#2e7d32'
        assert app.root.pending() is None, "the poll outlived the job"


def test_the_job_line_reads_the_record_only_when_it_changed():
    """A stat each tick; the read (and parse) only when the stat says the
    record is another one."""
    with _Env() as env:
        app = _line_app()
        run = os.path.join(env.tmp, 'R')
        reads = []
        real = sv.read_progress
        sv.read_progress = lambda path: (reads.append(path), real(path))[1]
        try:
            _say(run, 'finalize', 'detect', done=1, total=9)
            app._sldea_job_watch(run, _Proc())
            for _ in range(3):
                app.tick()
            assert len(reads) == 1, reads
            time.sleep(0.05)            # a different mtime, whatever the FS
            _say(run, 'finalize', 'detect', done=2, total=9)
            app.tick()
            assert len(reads) == 2 and app.text().endswith('2/9'), reads
        finally:
            sv.read_progress = real


def test_the_job_line_reports_a_rerun_after_save():
    """With an Edge Review window opened from the tab still open, the line
    keeps looking (half as often) after the post-run job ended. A Save
    there announces a re-run; the window closes (a clean --auto Save);
    the line follows the re-run to its last word, then stops."""
    with _Env() as env:
        app = _line_app()
        run = os.path.join(env.tmp, 'SLDEA_20261006_101500')
        edge = _Proc()
        app._sldea_edge_procs = [edge]
        _say(run, 'finalize', 'done', text='ready in the run folder')
        app._sldea_job_watch(run, _Proc(0))
        assert app.root.pending()[0] == app.SLDEA_JOB_IDLE_MS
        time.sleep(0.05)
        sv.launch_rerun(run, popen=lambda cmd, **kw: 'proc')
        edge.code = 0
        app.tick()
        assert app.text().endswith('starting the edge re-run after Save'), \
            app.text()
        assert app.root.pending()[0] == app.SLDEA_JOB_POLL_MS
        time.sleep(0.05)
        _say(run, 'rerun', 'detect', done=3, total=10)
        app.tick()
        assert app.text().endswith('re-running edge detection after Save '
                                   '3/10'), app.text()
        time.sleep(0.05)
        _say(run, 'rerun', 'done', text='edges re-run after Save, 10 frames')
        app.tick()
        assert app.text().endswith('edges re-run after Save, 10 frames')
        assert app.root.pending() is None


def test_the_job_line_says_when_a_job_ended_or_went_quiet_without_a_word():
    with _Env() as env:
        app = _line_app()
        run = os.path.join(env.tmp, 'R')
        _say(run, 'finalize', 'copy', done=5, total=10, what='video.mkv')
        app._sldea_job_watch(run, _Proc(1))
        assert app.text() == ("⚠ video of R: the post-run job ended (exit "
                              "code 1) without its last word; see run.log"), \
            app.text()
        assert app.sldea_job_line.cget('fg') == '#8a5a00'
        assert app.root.pending() is None
        # a re-run nobody here holds the process of: quiet too long
        p = _say(run, 'rerun', 'detect', done=5, total=10)
        p.rec['t'] = time.time() - sv.PROGRESS_STALE_S - 30
        assert p.write(now=p.rec['t'])
        app2 = _line_app()
        app2._sldea_job_watch(run)
        assert app2.text().startswith("⚠ video of R: no word from the job"), \
            app2.text()
        assert app2.root.pending() is None


def test_the_post_run_thread_starts_the_job_and_hands_it_to_the_line():
    """_sldea_video_postrun starts the job through launch_finalize, logs
    the same run.log line as before, and hands the job to the line on the
    Tk thread; a launch that fails is logged as before and handed too
    (its record says it failed)."""
    gui = _gui()
    G = gui.InstrumentControlGUI
    with _Env() as env:
        run = os.path.join(env.tmp, 'SLDEA_20261006_101500')
        os.makedirs(run)
        stage = os.path.join(env.tmp, 'staging', 'stage1')

        class Rec:
            written = 5

            def wait_finished(self, t):
                return True

        class App:
            _sldea_run_logger = G._sldea_run_logger
            _sldea_video_postrun = G._sldea_video_postrun

            def __init__(self):
                self._sldea_video_jobs = []
                self.root = _Root()
                self.watched = []

            def _sldea_job_watch(self, rundir, proc=None):
                self.watched.append((rundir, proc))

        calls = []
        real = gui.sldea_video.launch_finalize
        try:
            gui.sldea_video.launch_finalize = (
                lambda s, r, detect=False: calls.append((s, r, detect))
                or 'proc')
            app = App()
            app._sldea_video_postrun(Rec(), stage, run, True)
            assert calls == [(stage, run, True)], calls
            assert app._sldea_video_jobs == ['proc']
            handed = _handed(app.root)
            assert len(handed) == 1, app.root.jobs
            assert not app.watched, "the line was started off the Tk thread"
            handed[0]()
            assert app.watched == [(run, 'proc')], app.watched

            def fail(s, r, detect=False):
                raise OSError('no fork')
            gui.sldea_video.launch_finalize = fail
            app = App()
            app._sldea_video_postrun(Rec(), stage, run, False)
            assert app._sldea_video_jobs == []
            [fn] = _handed(app.root)
            fn()
            assert app.watched == [(run, None)], app.watched
        finally:
            gui.sldea_video.launch_finalize = real
        lines = _log_body(os.path.join(run, 'run.log'))
        assert lines == [
            "video: moving the recording into the run folder, after edge "
            "detection on every frame — in a separate program that survives "
            "closing this app; its progress is in this run's run.log",
            f"⚠ video: could not start the move (no fork) — the recording "
            f"is in {stage}; run `python sldea_video.py --finalize "
            f"\"{stage}\" \"{run}\"` by hand"], lines


def test_an_edge_review_opened_from_the_tab_keeps_the_line_looking():
    gui = _gui()
    G = gui.InstrumentControlGUI
    with _Env() as env:
        app = _line_app()
        app._sldea_open_edge_review = G._sldea_open_edge_review.__get__(app)

        class Out:
            def get(self):
                return env.tmp
        app.sldea_outdir = Out()
        app.status_bar = _Label()
        started = []
        real = gui.subprocess.Popen
        try:
            gui.subprocess.Popen = lambda cmd, **kw: (started.append(cmd)
                                                      or _Proc())
            run = os.path.join(env.tmp, 'R')
            _say(run, 'finalize', 'done', text='ready')
            app._sldea_job_watch(run, _Proc(0))
            assert app.root.pending() is None       # nothing left
            gone = _Proc(0)
            app._sldea_edge_procs = [gone]
            app._sldea_open_edge_review(run, auto=True)
            assert started and started[0][-1] == '--auto', started
            assert len(app._sldea_edge_procs) == 1 and \
                app._sldea_edge_procs[0] is not gone
            assert app.root.pending()[0] == app.SLDEA_JOB_IDLE_MS
        finally:
            gui.subprocess.Popen = real


def test_the_job_line_sits_under_the_run_row_once_a_job_reports():
    """In the real tab: not packed while no job has reported, then just
    above the camera line, under the run row and its status."""
    gui = _gui()
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as e:
        raise _Skip(f"no display for Tk: {e}")
    # no instrument hunt and no camera, as test_gui_tabs builds the app
    real = (gui.InstrumentControlGUI.auto_connect, gui.CAM_AUTOSTART_ON_TAB)
    gui.InstrumentControlGUI.auto_connect = lambda self: None
    gui.CAM_AUTOSTART_ON_TAB = False
    with _Env() as env:
        try:
            root.withdraw()
            app = gui.InstrumentControlGUI(root)
            line = app.sldea_job_line
            assert line.winfo_manager() == '', "packed before any job"
            run = os.path.join(env.tmp, 'SLDEA_20261006_101500')
            _say(run, 'finalize', 'detect', done=4, total=40)
            app._sldea_job_watch(run, _Proc())
            assert line.winfo_manager() == 'pack'
            slaves = line.master.pack_slaves()
            i = slaves.index(line)
            assert slaves[i + 1] is app.sldea_cam_line, slaves
            assert app.sldea_status.master in slaves[:i], slaves
            assert line.cget('text').endswith('detecting edges 4/40')
            job = app._sldea_job
            root.after_cancel(job['after'])
            job['after'] = None
        finally:
            (gui.InstrumentControlGUI.auto_connect,
             gui.CAM_AUTOSTART_ON_TAB) = real
            root.destroy()


def _run():
    # Failures are collected, not fatal (`#280`): failing fast reported one
    # broken test in suites that had five. Tracebacks land after the count
    # line, in name order, in one bounded block -- run_tests.py explains why.
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    ran = skipped = 0
    failed = []
    for n in names:
        try:
            globals()[n]()
        except _Skip as why:
            skipped += 1
            print('skip', n, f'({why})')
            continue
        except Exception:
            ran += 1
            failed.append((n, traceback.format_exc()))
            print('FAIL', n)
            continue
        ran += 1
        print('ok ', n)
    tail = f"{ran} of {len(names)} tests ran"
    if skipped:
        tail += f" ({skipped} skipped)"
    print(tail)
    if not failed:
        return 0
    head = f"{len(failed)} of {len(names)} tests failed"
    print(f"\n{head}")
    for name, tb in failed:
        print(f"===== FAIL {name} =====")
        print(tb.rstrip('\n'))
    print(f"===== end {head} =====")
    return 1


if __name__ == '__main__':
    raise SystemExit(_run())
