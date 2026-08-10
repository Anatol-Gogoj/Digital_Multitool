#!/usr/bin/env python3
"""Headless tests for sldea_trace -- the manual-trace model (#162).

The Tk layer (sldea_edge_gui.TraceWindow) is a thin shell over this
module; everything that can be wrong in a way that matters -- geometry,
the undo stack, view<->image mapping, the label sidecar -- is exercised
here without a display.

Run: .venv/bin/python tests/test_sldea_trace.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(
    _os.path.abspath(__file__))))
import json
import os
import shutil
import tempfile

import numpy as np

import sldea_trace as st


def test_polygon_area_shoelace():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert st.polygon_area(sq) == 100.0
    # winding direction is a mouse-path accident, not information
    assert st.polygon_area(sq[::-1]) == 100.0
    assert st.polygon_area([(0, 0), (4, 0), (0, 3)]) == 6.0
    assert st.polygon_area([(0, 0), (5, 5)]) == 0.0
    d = st.equivalent_diam(st.polygon_area(sq))
    assert abs(d - 2 * np.sqrt(100 / np.pi)) < 1e-9


def test_polygon_centroid_and_degenerate_fallback():
    cx, cy = st.polygon_centroid([(0, 0), (10, 0), (10, 10), (0, 10)])
    assert abs(cx - 5.0) < 1e-9 and abs(cy - 5.0) < 1e-9
    cx, cy = st.polygon_centroid([(1, 1), (3, 3), (5, 5)])   # collinear
    assert abs(cx - 3.0) < 1e-9 and abs(cy - 3.0) < 1e-9


def test_self_intersection_bowtie_yes_square_no():
    assert not st.self_intersects([(0, 0), (10, 0), (10, 10), (0, 10)])
    # the classic bowtie: edges 0-1 and 2-3 cross
    assert st.self_intersects([(0, 0), (10, 10), (10, 0), (0, 10)])
    # sharing an endpoint (adjacent edges) is not an intersection
    assert not st.self_intersects([(0, 0), (5, 8), (10, 0), (5, 3)])


def test_mask_and_iou():
    a = [(2, 2), (12, 2), (12, 12), (2, 12)]
    m = st.polygon_mask(a, (20, 20))
    assert m.dtype == np.uint8 and m[7, 7] == 1 and m[0, 0] == 0
    assert st.iou(a, a, (20, 20)) == 1.0
    b = [(x + 100, y) for x, y in a]
    assert st.iou(a, b, (20, 200)) == 0.0
    # half-overlap square: IoU = 5x10 / (2*10x10 - 5x10) = 1/3
    c = [(7, 2), (17, 2), (17, 12), (7, 12)]
    v = st.iou(a, c, (20, 30))
    assert 0.25 < v < 0.42, v
    assert st.iou([(0, 0)], a, (20, 20)) == 0.0


def test_view_transform_roundtrip_and_cursor_anchored_zoom():
    """Zoom/pan must never desynchronize click coordinates from full-res
    image coordinates (#162 acceptance criterion)."""
    t = st.ViewTransform()
    t.fit(1920, 1080, 780, 560)
    for ix, iy in ((0, 0), (1919, 1079), (480.25, 270.75)):
        vx, vy = t.to_view(ix, iy)
        rx, ry = t.to_image(vx, vy)
        assert abs(rx - ix) < 1e-9 and abs(ry - iy) < 1e-9
    # the image point under the cursor stays under the cursor
    t2 = st.ViewTransform(zoom=1.0)
    anchor_img = t2.to_image(300, 200)
    t2.zoom_at(300, 200, 1.5)
    after = t2.to_image(300, 200)
    assert abs(after[0] - anchor_img[0]) < 1e-9
    assert abs(after[1] - anchor_img[1]) < 1e-9
    assert abs(t2.zoom - 1.5) < 1e-9
    # clamped at the limits, still anchored
    t2.zoom_at(300, 200, 1e9)
    assert t2.zoom == t2.max_zoom
    # panning by a view delta moves the origin against it
    t3 = st.ViewTransform(zoom=2.0, ox=10, oy=20)
    t3.pan_view(30, -10)
    assert abs(t3.ox - (10 - 15)) < 1e-9 and abs(t3.oy - 25) < 1e-9


def test_trace_model_undo_redo_walks_every_op_including_restart():
    m = st.TraceModel()
    m.add(0, 0)
    m.add(10, 0)
    m.add(10, 10)
    m.move(1, 12, 1)
    m.delete(0)
    assert m.points == [(12.0, 1.0), (10.0, 10.0)]
    m.restart()
    assert m.points == []
    # undo all five ops in reverse
    assert m.undo() and m.points == [(12.0, 1.0), (10.0, 10.0)]  # restart
    assert m.undo() and m.points[0] == (0.0, 0.0)                # delete
    assert m.undo() and m.points[1] == (10.0, 0.0)               # move
    assert m.undo() and len(m.points) == 2                       # add
    assert m.undo() and m.undo() and m.points == []
    assert not m.undo()
    # redo all the way back to the restarted-empty state
    while m.redo():
        pass
    assert m.points == [] and not m.can_redo() and m.can_undo()
    # a new op clears the redo stack
    m.undo()
    m.add(5, 5)
    assert not m.can_redo()
    # nearest respects the threshold
    assert m.nearest(12.5, 1.2, max_dist=2.0) == 0
    assert m.nearest(50, 50, max_dist=2.0) is None


def test_edge_snap_magnet_and_flat_no_op():
    img = np.full((40, 40), 100.0, np.float32)
    img[:, 20:] = 180.0                       # vertical step at x=20
    x, y = st.edge_snap(img, 16.0, 10.0, radius=6)
    assert abs(x - 19.5) <= 1.5 and abs(y - 10.0) <= 1.0, (x, y)
    # flat neighborhoods leave the click alone
    x, y = st.edge_snap(img, 5.0, 30.0, radius=5)
    assert (x, y) == (5.0, 30.0)
    # out of frame: unchanged rather than a crash
    assert st.edge_snap(img, -10, -10) == (-10.0, -10.0)


def test_label_sidecar_appends_atomically_and_refuses_corrupt():
    d = tempfile.mkdtemp(prefix='trace_labels_')
    try:
        row = {'frame_file': 'SLDEA_s01_00.25kV_pre-ramp.png',
               'nominal_kV': '0.25', 'tag': 'pre-ramp'}
        poly = [(10, 10), (110, 12), (108, 90), (12, 88)]
        mach = {'method': 'disc-fit', 'conf': 0.91, 'area_px': 7500.0,
                'audit_nostep': 22.0,
                'contour': np.array([[10, 10], [110, 10],
                                     [110, 90], [10, 90]], float)}
        rec = st.label_record(3, row, poly, (540, 960), machine=mach,
                              zoom=2.5, overlays={'resting': True},
                              elapsed_s=41.2, snapped=False, user='op',
                              now=1753795000)
        p = st.append_label(d, rec)
        assert os.path.basename(p) == st.LABELS_NAME
        assert not os.path.exists(p + '.tmp')
        rec2 = st.label_record(5, row, poly, (540, 960), machine=None,
                               unpaired=st.UNPAIRED_NO_CANDIDATE,
                               user='op')
        st.append_label(d, rec2)
        labels = st.load_labels(d)
        assert len(labels) == 2
        assert labels[0]['machine']['method'] == 'disc-fit'
        assert labels[0]['machine']['audit_nostep'] == 22.0
        assert labels[0]['frame_shape'] == [540, 960]
        assert labels[0]['user'] == 'op' and labels[0]['n_points'] == 4
        assert labels[1]['machine'] is None
        # a label made WITH a candidate keeps it, all the way through the
        # JSON round trip, and says nothing is missing (#162)
        assert st.is_paired(labels[0]) and labels[0]['unpaired'] is None
        assert labels[0]['machine']['detect_scope'] == st.SCOPE_RUN
        # ...and the unpaired one carries the named reason it can never
        # be ground truth, instead of an unexplained null
        assert labels[1]['unpaired'] == st.UNPAIRED_NO_CANDIDATE
        assert not st.is_paired(labels[1])
        # every entry is sufficient to compute IoU offline (#162)
        v = st.label_iou(labels[0])
        assert v is not None and 0.85 < v <= 1.0, v
        assert st.label_iou(labels[1]) is None
        # a corrupt sidecar must refuse, never silently clobber the
        # accumulated ground truth
        with open(os.path.join(d, st.LABELS_NAME), 'w') as f:
            f.write('{not json')
        try:
            st.append_label(d, rec2)
        except ValueError as e:
            assert st.LABELS_NAME in str(e)
        else:
            raise AssertionError("append_label clobbered a corrupt sidecar")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_manual_trace_result_flows_through_apply_results():
    """#162 acceptance criterion: a traced frame's CSV row carries the
    manual area and an 'edge:manual-trace ... (user)' note, through the
    SAME apply_results path every accepted candidate takes."""
    import sldea_edge as se
    poly = [(100, 100), (300, 100), (300, 260), (100, 260)]
    area = st.polygon_area(poly)
    res = {'method': 'manual-trace', 'conf': 1.0, 'chosen_by': 'user',
           'area_px': float(area), 'diam_px': st.equivalent_diam(area),
           'cx': 200.0, 'cy': 180.0,
           'contour': np.asarray(poly, np.int32), 'wrinkle': 1.7}
    rows = [{'nominal_kV': '5', 'notes': ''}]
    se.apply_results(rows, {0: res}, 0.02, {}, {})
    assert rows[0]['active_area_px'] == f"{area:.0f}"
    assert rows[0]['active_area_mm2'] == f"{area * 0.02 * 0.02:.3f}"
    assert rows[0]['notes'] == 'edge:manual-trace conf 1.00 (user)'
    assert rows[0]['wrinkle_idx'] == '1.70'


def test_calibration_summary_bins_conf_against_iou():
    sq = [[10, 10], [110, 10], [110, 90], [10, 90]]
    def rec(conf, shift):
        return {'polygon': [[x + shift, y] for x, y in sq],
                'frame_shape': [200, 400],
                'machine': {'method': 'disc-fit', 'conf': conf,
                            'contour': sq}}
    labels = [rec(0.95, 0), rec(0.9, 2), rec(0.6, 60), rec(0.55, 70)]
    pairs = st.conf_vs_iou(labels)
    assert len(pairs) == 4
    hi = [p for p in pairs if p[0] >= 0.85]
    lo = [p for p in pairs if p[0] < 0.85]
    assert min(p[1] for p in hi) > 0.8 and max(p[1] for p in lo) < 0.5
    lines = st.calibration_summary(pairs)
    text = '\n'.join(lines)
    assert 'conf-vs-IoU' in text and 'disc-fit' in text
    assert st.calibration_summary([])[-1].startswith('  no labels')


def test_append_label_is_atomic_under_replace_failure():
    """audit 2026-08-05 (mutation finding): swapping the tmp+os.replace
    for an in-place write survived the suite. append_label rewrites the
    WHOLE sidecar each call, so a mid-write failure would destroy every
    accumulated label, not just the new one — pin that the destination
    never changes when os.replace fails."""
    import os
    d = tempfile.mkdtemp(prefix='trace_atomic_')
    try:
        row = {'frame_file': 'f.png', 'nominal_kV': '1', 'tag': 'pre'}
        poly = [(10, 10), (110, 12), (108, 90)]
        st.append_label(d, st.label_record(
            1, row, poly, (240, 320),
            unpaired=st.UNPAIRED_NO_CANDIDATE))
        p = os.path.join(d, st.LABELS_NAME)
        before = open(p, 'rb').read()

        real_replace = st.os.replace

        def boom(src, dst):
            raise OSError(28, 'No space left on device')

        st.os.replace = boom
        try:
            st.append_label(d, st.label_record(
                2, row, poly, (240, 320),
                unpaired=st.UNPAIRED_NO_CANDIDATE))
        except OSError:
            pass
        else:
            raise AssertionError("append_label swallowed the failure")
        finally:
            st.os.replace = real_replace
        assert open(p, 'rb').read() == before
        assert len(st.load_labels(d)) == 1
        assert os.path.exists(p + '.tmp')
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _disc_scene(r=40, size=240):
    """Flat baseline + a disc `r` px brighter -- the same synthetic scene
    tests/test_sldea_edge.py detects on."""
    base = np.full((size, size), 100.0, np.float32)
    img = base.copy()
    yy, xx = np.mgrid[0:size, 0:size]
    img[(xx - size / 2) ** 2 + (yy - size / 2) ** 2 <= r * r] += 40.0
    return base, img


def _ngon(cx, cy, r, n=24):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return [(float(cx + r * np.cos(t)), float(cy + r * np.sin(t)))
            for t in a]


def test_machine_pairing_keeps_rejected_candidates_pairable():
    """#162's TWO jobs, told apart.

    Job 1 (recovery) is tracing when every automated candidate has been
    REJECTED -- rejection lives in the review results, never in the
    candidate list, so such a frame still has a candidate to pair with
    and its label is full ground truth. The 2026-08-06 bug was the other
    case: a frame whose candidate list is EMPTY because detection never
    ran. Both used to end up as machine:null; only the second one may."""
    rejected = [{'method': 'disc-fit', 'conf': 0.62, 'area_px': 5000.0,
                 'contour': np.array([[10, 10], [110, 10], [110, 90],
                                      [10, 90]], float)},
                {'method': 'diff-hi', 'conf': 0.41, 'area_px': 3000.0,
                 'contour': np.array([[20, 20], [90, 20], [90, 80]],
                                     float)}]
    mach, why = st.machine_pairing(rejected)
    assert why is None and mach is rejected[0], (mach, why)
    # the empty-list cases each name themselves
    assert st.machine_pairing([])[1] == st.UNPAIRED_NO_CANDIDATE
    assert st.machine_pairing([], detected=False)[1] == \
        st.UNPAIRED_NOT_DETECTED
    assert st.machine_pairing([], baseline_ok=False)[1] == \
        st.UNPAIRED_NO_BASELINE
    # a candidate with an area but no outline is not a pairing either --
    # label_iou needs a contour -- yet it is still worth recording
    no_c = [{'method': 'resting', 'conf': 0.8, 'area_px': 700.0}]
    mach, why = st.machine_pairing(no_c)
    assert why == st.UNPAIRED_NO_CONTOUR and mach is no_c[0]
    # every reason the model can produce has an operator sentence
    for r in (st.UNPAIRED_NO_CANDIDATE, st.UNPAIRED_NOT_DETECTED,
              st.UNPAIRED_NO_BASELINE, st.UNPAIRED_NO_CONTOUR,
              st.UNPAIRED_FRAME_UNREADABLE, st.UNPAIRED_DETECT_FAILED):
        assert len(st.unpaired_message(r)) > 40, r


def test_label_record_refuses_an_unexplained_missing_pairing():
    """The 2026-08-06 gate: a label with machine:null returns None from
    label_iou forever, so it can never be ground truth. Writing one is
    allowed only when the caller NAMES the reason -- which is the point
    where the GUI has to tell the operator."""
    row = {'frame_file': 'f.png', 'nominal_kV': '3', 'tag': 'post-ramp'}
    poly = [(10, 10), (110, 12), (108, 90), (12, 88)]
    for bad in ({}, {'machine': None},
                {'machine': {'method': 'resting', 'conf': 0.8}},
                {'machine': {'method': 'x', 'conf': 0.1, 'contour': []}}):
        try:
            st.label_record(28, row, poly, (240, 320), **bad)
        except ValueError as e:
            assert '#162' in str(e), str(e)
        else:
            raise AssertionError(f"machine:null slipped through: {bad}")
    # a reason outside the vocabulary is refused too (a typo must not
    # become a silent free-text excuse)
    try:
        st.label_record(28, row, poly, (240, 320), unpaired='dunno')
    except ValueError as e:
        assert 'unknown unpaired reason' in str(e)
    else:
        raise AssertionError("an unknown reason was accepted")
    # named -> written, and the record says so out loud
    rec = st.label_record(28, row, poly, (240, 320),
                          unpaired=st.UNPAIRED_NOT_DETECTED)
    assert rec['machine'] is None
    assert rec['unpaired'] == st.UNPAIRED_NOT_DETECTED
    assert not st.is_paired(rec) and st.label_iou(rec) is None
    # a real pairing wins over any reason the caller happened to pass
    mach = {'method': 'disc-fit', 'conf': 0.9, 'area_px': 9000.0,
            'contour': np.array([[10, 10], [110, 10], [110, 90],
                                 [10, 90]], float)}
    rec = st.label_record(28, row, poly, (240, 320), machine=mach,
                          unpaired=st.UNPAIRED_NOT_DETECTED)
    assert rec['unpaired'] is None and st.is_paired(rec)
    assert st.label_iou(rec) > 0.8


def test_on_demand_single_frame_detection_supplies_the_pairing():
    """The fix's (a) half, headlessly: the tracer no longer needs a whole
    detection pass to have a machine candidate. Detecting the ONE frame
    the operator is about to trace yields a pairing, and the label marks
    the conf as coming from that narrower pass (no ramp hysteresis, no
    same-kV pair reconciliation -- both worth up to 0.05 of conf).

    It also pins the honest LIMIT: with an unreadable baseline the
    detector refuses by design, so no on-demand detection can rescue
    that frame and the reason must be reported instead."""
    import sldea_edge as se
    base, img = _disc_scene(r=40)
    cands = se.candidates(base, img, dict(se.DEFAULT_SETTINGS))
    assert cands, "no candidate on a clean synthetic disc"
    for c in cands:                       # what the GUI tags them with
        c['detect_scope'] = st.SCOPE_FRAME
    mach, why = st.machine_pairing(cands)
    assert why is None
    row = {'frame_file': 'f.png', 'nominal_kV': '3', 'tag': 'post-ramp'}
    rec = st.label_record(28, row, _ngon(120, 120, 40), (240, 240),
                          machine=mach, unpaired=why)
    assert rec['machine']['detect_scope'] == st.SCOPE_FRAME
    v = st.label_iou(rec)
    assert v is not None and v > 0.8, v
    # no baseline -> the detector refuses (audit 2026-08-05), so the
    # pairing genuinely cannot be created; it must be NAMED
    assert se.candidates(None, img, dict(se.DEFAULT_SETTINGS)) == []
    assert st.machine_pairing([], baseline_ok=False)[1] == \
        st.UNPAIRED_NO_BASELINE


def test_unpaired_summary_names_the_dead_labels_including_legacy():
    """The calibration pass must REPORT unusable labels, not just fail to
    see them -- the 2026-07/08 control round lost four traces to
    machine:null and nothing said so. Pre-gate labels carry no reason, so
    they are reported as 'unrecorded' rather than dropped."""
    sq = [[10, 10], [110, 10], [110, 90], [10, 90]]
    good = {'row_index': 5, 'polygon': sq, 'frame_shape': [200, 400],
            'machine': {'method': 'disc-fit', 'conf': 0.9,
                        'contour': sq}}
    named = {'row_index': 65, 'polygon': sq, 'frame_shape': [200, 400],
             'machine': None, 'unpaired': st.UNPAIRED_NO_CANDIDATE}
    legacy = {'row_index': 28, 'polygon': sq, 'frame_shape': [200, 400],
              'machine': None}            # written before the gate
    gaps = st.unpaired_labels([good, named, legacy])
    assert set(gaps) == {st.UNPAIRED_NO_CANDIDATE, 'unrecorded'}
    assert gaps['unrecorded'][0]['row_index'] == 28
    # the curve itself still only counts comparable labels
    assert len(st.conf_vs_iou([good, named, legacy])) == 1
    text = '\n'.join(st.unpaired_summary([good, named, legacy]))
    assert '2 of 3' in text
    # both vocabularies, every time (`#255`) -- the bare row number sent
    # an operator to the wrong frame on 2026-08-07
    assert 'row 28 (GUI frame 29)' in text, text
    assert 'row 65 (GUI frame 66)' in text, text
    assert '--auto' in text, "the actual cause must be named"
    assert st.unpaired_summary([good])[0].startswith('all 1 label')
    assert 'no labels yet' in st.unpaired_summary([])[0]
    # a pooled report of several runs must not print two bare 'row 28's:
    # main() attaches the run name, label_where prints it (review
    # 2026-08-06)
    two_runs = [dict(legacy, _run='DOT_P3_1_20260729'),
                dict(legacy, _run='P3_3_2.5mL_20260728')]
    both = '\n'.join(st.unpaired_summary(two_runs))
    assert 'DOT_P3_1_20260729 row 28 (GUI frame 29)' in both, both
    assert 'P3_3_2.5mL_20260728 row 28 (GUI frame 29)' in both, both
    # measured 2026-08-06: the bench PC's console is cp1252, and one '⚠'
    # in this report aborted the whole CLI with a UnicodeEncodeError.
    # Every line the CLI can print stays ASCII (Tk dialogs may not) --
    # INCLUDING the no-labels branch, which is the first-use path and was
    # the one line left out of this check when it was written (an em dash
    # sat in it, crashing under cp437/cp850).
    printable = text + both + '\n'.join(
        [st.unpaired_message(r) for r in st.UNPAIRED_REASONS]
        + [st.unpaired_message('unrecorded'),
           st.unpaired_message('degenerate-polygon')]
        + st.unpaired_summary([])
        + st.unpaired_summary([good])
        + st.calibration_summary(st.conf_vs_iou([good]))
        + st.calibration_summary([]))
    printable.encode('ascii')          # raises if a glyph creeps back in
    for enc in ('cp437', 'cp850', 'cp1252'):
        printable.encode(enc)          # the consoles this actually runs on


def test_calibration_report_marks_on_demand_points():
    """A single-frame on-demand pairing follows a NARROWER conf
    convention than a run pass (no ramp hysteresis, no same-kV
    reconciliation), and because the hysteresis bonus lands before
    candidates() sorts, a full pass could also have picked a different
    candidate. The tag existed but nothing read it (review 2026-08-06):
    an operator setting accept_conf off this curve could not see that a
    bin was part on-demand. Now the curve itself says so."""
    sq = [[10, 10], [110, 10], [110, 90], [10, 90]]

    def rec(conf, shift, scope, row):
        return {'row_index': row, '_run': 'P3_5_2.5mL_0729',
                'polygon': [[x + shift, y] for x, y in sq],
                'frame_shape': [200, 400],
                'machine': {'method': 'disc-fit', 'conf': conf,
                            'contour': sq, 'detect_scope': scope}}
    run_pass = rec(0.90, 2, st.SCOPE_RUN, 5)
    on_demand = rec(0.79, 3, st.SCOPE_FRAME, 25)
    legacy = {'row_index': 9, 'polygon': sq, 'frame_shape': [200, 400],
              'machine': {'method': 'disc-fit', 'conf': 0.95,
                          'contour': sq}}          # no tag == run pass
    assert st.label_scope(on_demand) == st.SCOPE_FRAME
    assert st.label_scope(run_pass) == st.SCOPE_RUN
    assert st.label_scope(legacy) == st.SCOPE_RUN
    text = '\n'.join(st.calibration_summary(
        st.conf_vs_iou([run_pass, on_demand, legacy])))
    assert st.SCOPE_FRAME in text, text
    assert '1 of 3' in text, text
    # the re-trace list is an instruction to an operator, so it speaks
    # the GUI's frame numbers too (`#255`)
    assert 'P3_5_2.5mL_0729 row 25 (GUI frame 26)' in text, text
    # the marker lands on the affected bin and method line, not only in
    # the footnote -- the bin is what sets accept_conf
    marked = [ln for ln in text.split('\n') if 'on-demand' in ln]
    assert len(marked) >= 3, marked
    assert any(ln.strip().startswith('0.75') for ln in marked), marked
    assert any('disc-fit' in ln for ln in marked), marked
    # a curve made only of run-pass points says nothing about scope
    clean = '\n'.join(st.calibration_summary(
        st.conf_vs_iou([run_pass, legacy])))
    assert 'on-demand' not in clean and st.SCOPE_FRAME not in clean


def test_report_names_rows_in_the_gui_frame_vocabulary():
    """`#255`: every row this report names to an operator carries the
    number Edge Review's status bar shows for that row.

    The report counts data.csv rows from 0; the GUI prints
    `frame {pos+1}/{len(frame_rows)}`. On 2026-08-07 an operator sent to
    'row 28' navigated to GUI frame 28 and landed the label on row 27 --
    a valid but unintended frame. 'row' still means the data.csv row (it
    is the sidecar's own key, read by everything else), so the GUI's
    number is printed BESIDE it, never instead of it.

    And the frame number is MAPPED from the run CSV, never assumed to be
    row+1: the GUI numbers only the rows that HAVE a frame file, so one
    frameless row shifts every later one -- the 2026-07 corpus already
    holds such a run (SLDEA_20260723_233426, an aborted capture)."""
    import io
    import re
    from contextlib import redirect_stdout

    # the formatting helper, in every state it can be called in
    assert st.label_where({'row_index': 28}) == 'row 28 (GUI frame 29)'
    assert st.label_where({'row_index': 28, '_run': 'DOT_P3_1_20260729'}) \
        == 'DOT_P3_1_20260729 row 28 (GUI frame 29)'
    # a mapping attached by main() WINS over the row+1 fallback
    assert st.label_where({'row_index': 28, '_gui_frame': 25}) == \
        'row 28 (GUI frame 25)'
    # a hand-edited sidecar can hold anything; still no crash, and no
    # invented frame number
    assert st.label_where({'row_index': None}) == 'row None'
    assert st.gui_frame({'row_index': 'x'}) is None

    d = tempfile.mkdtemp(prefix='trace_frames_')
    try:
        # a run whose row 2 lost its frame: from there on the GUI's frame
        # number is NOT row+1
        with open(os.path.join(d, 'data.csv'), 'w', newline='') as f:
            f.write('frame_file,nominal_kV,tag\n')
            for i in range(5):
                name = '' if i == 2 else f'f{i}.png'
                f.write(f'{name},{i},pre-ramp\n')
        assert st.gui_frame_map(d) == {0: 1, 1: 2, 3: 3, 4: 4}
        # an unreadable run degrades to the row+1 fallback, never raises
        assert st.gui_frame_map(os.path.join(d, 'nope')) == {}

        sq = [[10, 10], [110, 10], [110, 90], [10, 90]]
        legacy = {'row_index': 3, 'polygon': sq, 'frame_shape': [200, 400],
                  'machine': None}              # pre-gate -> 'unrecorded'
        on_demand = {'row_index': 4, 'polygon': sq,
                     'frame_shape': [200, 400],
                     'machine': {'method': 'disc-fit', 'conf': 0.9,
                                 'contour': sq,
                                 'detect_scope': st.SCOPE_FRAME}}
        sidecar = os.path.join(d, st.LABELS_NAME)
        with open(sidecar, 'w') as f:
            json.dump({'version': st.LABELS_VERSION,
                       'labels': [legacy, on_demand]}, f, indent=1)
        before = open(sidecar, 'rb').read()

        buf = io.StringIO()
        with redirect_stdout(buf):
            assert st.main([d]) == 0
        out = buf.getvalue()
        # the payoff. Row 3 is the GUI's frame 3 because row 2 carries no
        # frame -- a row+1 guess would have said 4 and sent the operator
        # one frame PAST the one that needs re-tracing, which is `#255`
        # committed a second time.
        assert 'row 3 (GUI frame 3)' in out, out
        assert 'row 3 (GUI frame 4)' not in out, out
        assert 'row 4 (GUI frame 4)' in out, out
        # no row is named bare anywhere in the report -- a hand-built
        # f-string left behind must fail HERE, not in an operator's hands
        bare = re.findall(r'row \d+\b(?! \(GUI frame \d)', out)
        assert not bare, (bare, out)

        # the report is read-only: the display-only _run / _gui_frame keys
        # annotate records in memory and never reach the sidecar. This is
        # a REPORT-vocabulary fix; the machine-readable records do not
        # move (`#255`).
        assert open(sidecar, 'rb').read() == before
        assert '_gui_frame' not in before.decode()
        rec = st.label_record(3, {'frame_file': 'f3.png', 'nominal_kV': '1',
                                  'tag': 'pre'}, sq, (200, 400),
                              unpaired=st.UNPAIRED_NOT_DETECTED)
        assert '_gui_frame' not in rec and '_run' not in rec

        # measured 2026-08-06, four times over: the bench PC's console is
        # cp1252/cp437/cp850 and one non-ASCII glyph aborts the whole
        # report with a UnicodeEncodeError. The new wording is ASCII...
        out.encode('ascii')
        for enc in ('cp437', 'cp850', 'cp1252'):
            out.encode(enc)
        # ...and survives an actual redirect onto a legacy code page,
        # which is how the bench reads it: `sldea_trace.py ... > out.txt`
        p = os.path.join(d, 'report.txt')
        with open(p, 'w', encoding='cp437') as f, redirect_stdout(f):
            st.main([d])
        assert 'row 3 (GUI frame 3)' in open(p, encoding='cp437').read()
    finally:
        shutil.rmtree(d, ignore_errors=True)


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
