#!/usr/bin/env python3
"""Manual boundary tracing for SLDEA Edge Review -- the model half (#162).

Two jobs in one feature (issue #162, Anatol 2026-07-29):

1. RECOVERY: when every automated candidate is rejected, the operator
   finishes the measurement by tracing the outer edge of the active area
   by hand -- post-breakdown and event frames, exactly where the
   detector honestly gives up.
2. GROUND TRUTH: every trace is a label. The polygon is stored full-res
   alongside the machine's best candidate at trace time, so the
   conf-vs-IoU calibration curve is computable offline later without
   re-detection. That curve is what can turn conf from a review-ordering
   score into a bar that MEANS something (SLDEA_HANDOFF.md, Open #1).

Job 2 is not optional and not silent (2026-08-06): label_record REFUSES
to build a label whose machine pairing is missing unless the caller
names the reason (`unpaired=`, one of UNPAIRED_REASONS). A label with
machine:null yields None from label_iou forever -- it is invisible to
the calibration pass and worthless as ground truth, and four of them
were written unnoticed during the 2026-07/08 batch control round because
the runs were opened without --auto and no detection had ever run. The
GUI now detects the ONE frame on demand before the tracer opens, so the
pairing is created rather than reported; when the detector honestly has
nothing to offer (unreadable baseline, no-change frame) the operator is
told before tracing that the trace will be recovery-only. An on-demand
pairing follows a narrower conf convention than a run pass (see SCOPE_*),
so the CLI marks those points instead of pooling them silently.

No Tk in here: geometry, the undo/redo op stack, view<->image coordinate
mapping, the edge-snap magnet and the label sidecar are all headless and
unit-tested (tests/test_sldea_trace.py). sldea_edge_gui.TraceWindow is a
thin interaction layer over this module.

Labels live in edge_labels.json BESIDE data.csv -- append-only across
sessions, atomic tmp+replace (same pattern as save_settings). Tracing
never touches data.csv or setup.txt itself; the traced polygon flows
through the normal accept -> apply_results -> write_back path instead.

CLI: python sldea_trace.py <run-or-parent> [...] prints the pooled
conf-vs-IoU calibration summary from every edge_labels.json found.
"""
import getpass
import json
import os
import time

import numpy as np

LABELS_NAME = 'edge_labels.json'
# Still 1 after the 2026-08-06 pairing gate: 'unpaired' and
# machine.detect_scope are ADDITIVE (every reader reaches them through
# .get), no file was migrated, and a sidecar written today legitimately
# holds records from before the gate -- unpaired_labels() reports those
# as 'unrecorded'. Bumping it would claim a migration that did not happen.
LABELS_VERSION = 1

# Which detection pass the stored machine candidate came from. A single
# frame detected on demand cannot carry the ramp-order hysteresis bonus
# or the same-kV pair reconciliation (both move conf by up to 0.05), so
# the label says which convention its conf follows instead of letting the
# calibration curve mix two of them silently. And because the hysteresis
# bonus is applied BEFORE candidates() sorts, its absence can also change
# WHICH candidate wins: measured 3-9% best-area difference on synthetic
# diff-tier scenes where the disc fit refuses (2026-08-06). So an
# on-demand point is self-consistent (its conf and its contour are the
# same candidate's) but is NOT the point a full pass would have made --
# calibration_summary marks it, label_scope reads it.
SCOPE_RUN = 'run-pass'
SCOPE_FRAME = 'frame-on-demand'

# Why a label has no machine candidate to compare against. Each of these
# is a case the GUI must state to the operator BEFORE the trace is made:
# the trace still recovers the measurement, but it can never serve as
# ground truth. The sentences are printed by the CLI as well as shown in
# Tk, so they are ASCII-only -- the bench PC's console is cp1252 and a
# '...' or a warning glyph in here aborts the whole calibration report
# with a UnicodeEncodeError (measured 2026-08-06).
UNPAIRED_NO_BASELINE = 'no-baseline'
UNPAIRED_FRAME_UNREADABLE = 'frame-unreadable'
UNPAIRED_DETECT_FAILED = 'detect-failed'
UNPAIRED_NOT_DETECTED = 'not-detected'
UNPAIRED_NO_CANDIDATE = 'no-candidate'
UNPAIRED_NO_CONTOUR = 'no-contour'

UNPAIRED_REASONS = {
    UNPAIRED_NO_BASELINE:
        "The run's BASELINE frame is unreadable, so difference imaging "
        "is impossible and the detector cannot produce a candidate for "
        "any frame. Restore the baseline frame and re-run Detect if this "
        "frame is needed as ground truth.",
    UNPAIRED_FRAME_UNREADABLE:
        "This frame did not decode for detection (missing, 0-byte or "
        "truncated), so there is nothing for the detector to measure.",
    UNPAIRED_DETECT_FAILED:
        "Detection for this frame raised an error (see the console). The "
        "trace is still valid as a measurement; the pairing is not.",
    UNPAIRED_NOT_DETECTED:
        "Detection has never run for this frame, so there is no machine "
        "candidate in memory. Run Detect (or reopen the run with --auto) "
        "before tracing if this frame is needed as ground truth.",
    UNPAIRED_NO_CANDIDATE:
        "Detection ran and honestly found nothing on this frame (no "
        "change against the baseline above the gate). There is no "
        "machine outline to compare a trace against; lower min_diff in "
        "Advanced and re-detect if you disagree.",
    UNPAIRED_NO_CONTOUR:
        "The machine's best candidate for this frame carries no outline, "
        "only an area, so no IoU can be computed from it.",
}


# ---------------------------------------------------------------------------
# polygon geometry
# ---------------------------------------------------------------------------

def polygon_area(pts):
    """Shoelace area (px^2) of a closed polygon given as [(x, y), ...].
    The closing edge last->first is implied. Absolute value: winding
    direction is a mouse-path accident, not information."""
    p = np.asarray(pts, np.float64)
    if len(p) < 3:
        return 0.0
    x, y = p[:, 0], p[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
                 / 2.0)


def polygon_centroid(pts):
    """Area centroid; falls back to the vertex mean for degenerate
    (collinear / <3 point) input."""
    p = np.asarray(pts, np.float64)
    if len(p) < 3:
        return (float(p[:, 0].mean()), float(p[:, 1].mean())) if len(p) \
            else (0.0, 0.0)
    x, y = p[:, 0], p[:, 1]
    xn, yn = np.roll(x, -1), np.roll(y, -1)
    cross = x * yn - xn * y
    a = cross.sum() / 2.0
    if abs(a) < 1e-9:
        return float(x.mean()), float(y.mean())
    cx = float(((x + xn) * cross).sum() / (6.0 * a))
    cy = float(((y + yn) * cross).sum() / (6.0 * a))
    return cx, cy


def equivalent_diam(area_px):
    """Diameter of the circle with this area -- what active_diam_mm is
    derived from for a non-elliptical outline."""
    return float(2.0 * np.sqrt(max(area_px, 0.0) / np.pi))


def _segs_cross(a, b, c, d):
    """Proper intersection of open segments ab and cd (shared endpoints
    do not count -- adjacent polygon edges always share one)."""
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-12 else (1 if v > 0 else -1)
    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    return o1 != o2 and o3 != o4 and 0 not in (o1, o2, o3, o4)


def self_intersects(pts):
    """True when any two non-adjacent edges of the closed polygon cross.
    O(n^2) -- hand traces are tens of points, not thousands."""
    p = [tuple(map(float, q)) for q in pts]
    n = len(p)
    if n < 4:
        return False
    edges = [(p[i], p[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue                      # adjacent (or same) edges
            if _segs_cross(*edges[i], *edges[j]):
                return True
    return False


def polygon_mask(pts, shape):
    """Filled uint8 mask (0/1) of the polygon on an (h, w) canvas."""
    import cv2
    m = np.zeros(shape[:2], np.uint8)
    p = np.asarray(pts, np.float64)
    if len(p) >= 3:
        cv2.fillPoly(m, [np.round(p).astype(np.int32)], 1)
    return m


def iou(pts_a, pts_b, shape):
    """Intersection-over-union of two outlines rasterized on `shape`.
    -> float in [0, 1]; 0.0 when either is degenerate."""
    a, b = polygon_mask(pts_a, shape), polygon_mask(pts_b, shape)
    union = int((a | b).sum())
    if not union:
        return 0.0
    return float(int((a & b).sum()) / union)


# ---------------------------------------------------------------------------
# view <-> image coordinate mapping (zoom / pan)
# ---------------------------------------------------------------------------

class ViewTransform:
    """Zoom+pan mapping between full-res image px and view (canvas) px.

    view = (image - origin) * zoom. Kept as plain floats so the Tk layer
    cannot desynchronize click coordinates from image coordinates -- the
    polygon is ALWAYS stored full-res (#162 acceptance criterion)."""

    def __init__(self, zoom=1.0, ox=0.0, oy=0.0,
                 min_zoom=0.05, max_zoom=16.0):
        self.zoom = float(zoom)
        self.ox, self.oy = float(ox), float(oy)
        self.min_zoom, self.max_zoom = float(min_zoom), float(max_zoom)

    def to_view(self, ix, iy):
        return ((ix - self.ox) * self.zoom, (iy - self.oy) * self.zoom)

    def to_image(self, vx, vy):
        return (vx / self.zoom + self.ox, vy / self.zoom + self.oy)

    def zoom_at(self, vx, vy, factor):
        """Rescale about the cursor: the image point under (vx, vy)
        stays under (vx, vy). Factor is clamped to the zoom limits."""
        ix, iy = self.to_image(vx, vy)
        z = max(self.min_zoom, min(self.max_zoom, self.zoom * factor))
        self.zoom = z
        self.ox = ix - vx / z
        self.oy = iy - vy / z

    def pan_view(self, dvx, dvy):
        """Shift by a view-space drag delta (image follows the mouse)."""
        self.ox -= dvx / self.zoom
        self.oy -= dvy / self.zoom

    def fit(self, img_w, img_h, view_w, view_h):
        """Whole image centred in the viewport ('F')."""
        z = min(view_w / float(img_w), view_h / float(img_h))
        self.zoom = max(self.min_zoom, min(self.max_zoom, z))
        self.ox = (img_w - view_w / self.zoom) / 2.0
        self.oy = (img_h - view_h / self.zoom) / 2.0


# ---------------------------------------------------------------------------
# the undo/redo op stack
# ---------------------------------------------------------------------------

class TraceModel:
    """Polygon-in-progress with a single history of atomic ops.

    Ops: add / move / delete / restart. Restart is itself ONE undoable
    op (#162: the confirm dialog is not the only safety net). Any new op
    clears the redo stack. Points are full-res image px."""

    def __init__(self):
        self.points = []
        self._undo = []
        self._redo = []

    # -- edits ----------------------------------------------------------
    def add(self, x, y, index=None):
        i = len(self.points) if index is None else int(index)
        self.points.insert(i, (float(x), float(y)))
        self._push(('add', i, (float(x), float(y))))

    def move(self, index, x, y):
        old = self.points[index]
        new = (float(x), float(y))
        if new == old:
            return
        self.points[index] = new
        self._push(('move', index, old, new))

    def delete(self, index):
        old = self.points.pop(index)
        self._push(('delete', index, old))

    def restart(self):
        if not self.points:
            return
        self._push(('restart', list(self.points)))
        self.points = []

    def nearest(self, x, y, max_dist):
        """Index of the nearest point within max_dist, else None."""
        if not self.points:
            return None
        p = np.asarray(self.points, np.float64)
        d = np.hypot(p[:, 0] - x, p[:, 1] - y)
        i = int(np.argmin(d))
        return i if d[i] <= max_dist else None

    # -- history --------------------------------------------------------
    def _push(self, op):
        self._undo.append(op)
        self._redo.clear()

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            return False
        op = self._undo.pop()
        kind = op[0]
        if kind == 'add':
            self.points.pop(op[1])
        elif kind == 'move':
            self.points[op[1]] = op[2]
        elif kind == 'delete':
            self.points.insert(op[1], op[2])
        elif kind == 'restart':
            self.points = list(op[1])
        self._redo.append(op)
        return True

    def redo(self):
        if not self._redo:
            return False
        op = self._redo.pop()
        kind = op[0]
        if kind == 'add':
            self.points.insert(op[1], op[2])
        elif kind == 'move':
            self.points[op[1]] = op[3]
        elif kind == 'delete':
            self.points.pop(op[1])
        elif kind == 'restart':
            self.points = []
        self._undo.append(op)
        return True


# ---------------------------------------------------------------------------
# edge snap (optional magnet, OFF by default)
# ---------------------------------------------------------------------------

def edge_snap(gray, x, y, radius=5):
    """Snap (x, y) to the strongest local intensity step within `radius`
    px -- Sobel magnitude argmax, ties broken toward the click. Returns
    the input unchanged when the neighborhood is flat (no gradient above
    noise) or out of frame. Labels made with this ON are tagged
    'snapped' so calibration can weight them separately (#162)."""
    import cv2
    h, w = gray.shape[:2]
    xi, yi = int(round(x)), int(round(y))
    if not (0 <= xi < w and 0 <= yi < h):
        return float(x), float(y)
    r = int(radius)
    x0, x1 = max(0, xi - r - 2), min(w, xi + r + 3)
    y0, y1 = max(0, yi - r - 2), min(h, yi + r + 3)
    patch = np.asarray(gray[y0:y1, x0:x1], np.float32)
    gx = cv2.Sobel(patch, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(patch, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    dist = np.hypot(xx - x, yy - y)
    mag[dist > r] = -1.0
    if float(mag.max()) < 8.0:            # flat: nothing worth snapping to
        return float(x), float(y)
    # strongest step; among near-equal magnitudes prefer the closest
    good = mag >= 0.9 * float(mag.max())
    cand = np.argwhere(good)
    k = int(np.argmin(dist[good]))
    py, px = cand[k]
    return float(xx[py, px]), float(yy[py, px])


# ---------------------------------------------------------------------------
# the label sidecar (edge_labels.json)
# ---------------------------------------------------------------------------

def machine_summary(cand):
    """The machine's best candidate at trace time, JSON-clean -- enough
    to compute IoU offline without re-detection. None-safe."""
    if not cand:
        return None
    out = {'method': cand.get('method'),
           'conf': float(cand.get('conf', 0.0)),
           'area_px': float(cand.get('area_px', 0.0)),
           # which pass produced this conf (see SCOPE_*): written
           # explicitly, never inferred from a missing key
           'detect_scope': str(cand.get('detect_scope') or SCOPE_RUN)}
    for k in ('audit_nostep', 'audit_bias'):
        if cand.get(k) is not None:
            out[k] = float(cand[k])
    c = cand.get('contour')
    if c is not None and len(c):
        out['contour'] = [[float(x), float(y)] for x, y in np.asarray(c)]
    return out


def machine_pairing(cands, *, detected=True, baseline_ok=True):
    """Which candidate a trace of this frame pairs with, and why none
    does when none does (#162, 2026-08-06).

    `cands` is the frame's candidate list (best first, as
    sldea_edge.candidates returns it); `detected` says whether detection
    has actually run for this frame; `baseline_ok` whether the run's
    baseline frame reads at all. -> (candidate | None, reason | None),
    the reason a key of UNPAIRED_REASONS.

    A REJECTED candidate still pairs. #162's first job is recovery --
    tracing when every automated candidate has been thrown out -- and a
    rejected candidate is exactly the machine answer the operator's
    polygon is the ground truth against. Rejection lives in the review
    results, never in this list, so it cannot reach this function."""
    best = cands[0] if cands else None
    if best is not None:
        c = best.get('contour')
        if c is not None and len(c):
            return best, None
        return best, UNPAIRED_NO_CONTOUR
    if not baseline_ok:
        return None, UNPAIRED_NO_BASELINE
    if not detected:
        return None, UNPAIRED_NOT_DETECTED
    return None, UNPAIRED_NO_CANDIDATE


def unpaired_message(reason):
    """The operator-facing sentence for an UNPAIRED_* reason -- what is
    missing and what would fix it. Unknown reasons pass through rather
    than raising: a message is never worth losing a trace over."""
    if reason in UNPAIRED_REASONS:
        return UNPAIRED_REASONS[reason]
    return _REPORT_ONLY_REASONS.get(
        reason, f"No machine candidate for this frame ({reason}).")


# Classifications a REPORT can produce but a caller may never write:
# they describe labels that already exist on disk.
_REPORT_ONLY_REASONS = {
    'unrecorded':
        "Written before the 2026-08-06 pairing gate, with no reason "
        "recorded - most likely the run was opened without --auto, so "
        "detection had never run. Re-detect the run and re-trace these "
        "frames if they are needed as ground truth.",
    'degenerate-polygon':
        "The stored polygon has fewer than 3 points, so it encloses no "
        "area and cannot be compared with anything.",
}


def is_paired(rec):
    """True when this label record carries everything an offline IoU
    needs: a real polygon AND a machine contour to compare it with. The
    #162 ground-truth criterion, in one predicate."""
    m = rec.get('machine') or {}
    return bool(m.get('contour')) and len(rec.get('polygon') or []) >= 3


def label_scope(rec):
    """Which detection pass this label's conf came from (SCOPE_*).
    Missing tag -> SCOPE_RUN: on-demand detection did not exist before
    2026-08-06, so every earlier label is a run-pass one."""
    return (rec.get('machine') or {}).get('detect_scope') or SCOPE_RUN


def gui_frame_map(rundir):
    """{row_index: Edge Review frame number} for one run directory.

    Edge Review numbers frames 1..N over the rows that HAVE a frame
    file, not over every CSV row: sldea_edge_gui builds
    `frame_rows = [i for i, r in enumerate(rows) if r['frame_file']]`
    and its status bar prints `frame {pos+1}/{len(frame_rows)}`. So the
    frame number is NOT row_index+1 in general -- one CSV row without a
    frame shifts every later row by one, and an aborted run leaves
    exactly that (SLDEA_20260723_233426 in the 2026-07 corpus). Read
    from the same CSV the GUI reads rather than assumed: guessing an
    operator's frame number wrong is the whole of `#255`, and a fix that
    guesses it wrong a different way is not a fix.

    -> {} when the run cannot be read (a malformed CSV); label_where
    then falls back to the contiguous-run identity, which is what 17 of
    the corpus's 18 runs are."""
    try:
        import sldea_edge as se
        rows = se.load_run(rundir)['rows']
    except Exception:
        return {}
    frame_rows = [i for i, r in enumerate(rows)
                  if (r.get('frame_file') or '').strip()]
    return {i: n for n, i in enumerate(frame_rows, start=1)}


def gui_frame(rec):
    """The frame number Edge Review shows this label's row as, or None
    when row_index is not a number at all (a hand-edited sidecar can
    hold anything).

    Uses the exact mapping main() attached from the run CSV when there
    is one; otherwise row_index+1, the identity for a run where every
    row has a frame."""
    n = rec.get('_gui_frame')
    if isinstance(n, int):
        return n
    i = rec.get('row_index')
    return i + 1 if isinstance(i, int) else None


def label_where(rec):
    """Where to send an operator to re-trace this label, in BOTH
    vocabularies: 'row 28 (GUI frame 29)', or 'DOT_P3_1_20260729 row 28
    (GUI frame 29)' once main() has attached the run name (in memory
    only, never written back).

    Two separate mis-targetings paid for this one line. A pooled report
    of several runs printed two bare 'row 28's from different runs, and
    an operator cannot tell which run to re-detect from that (review
    2026-08-06). Then the bare row number itself sent one to the wrong
    frame: this report counts data.csv rows from 0, Edge Review's status
    bar counts frames from 1, and on 2026-08-07 an operator sent to
    'row 28' navigated to frame 28 and landed the label on row 27 -- a
    valid but unintended frame (`#255`). 'row' still means the data.csv
    row everywhere else in this file, so it keeps its meaning and the
    GUI's number is printed BESIDE it, never instead of it."""
    run = (rec.get('_run') or '').strip()
    where = f"{run} row {rec.get('row_index')}" if run \
        else f"row {rec.get('row_index')}"
    n = gui_frame(rec)
    return where if n is None else f"{where} (GUI frame {n})"


def label_record(row_index, row, polygon, frame_shape, *, machine=None,
                 unpaired=None, zoom=1.0, overlays=None, elapsed_s=None,
                 snapped=False, user=None, now=None):
    """One edge_labels.json entry. `row` is the run CSV row dict; the
    polygon is full-res [(x, y), ...]. Self-contained for offline IoU:
    carries the frame shape and the machine candidate it competes with.

    REFUSES (ValueError) to build a label with no usable machine pairing
    unless the caller names the reason in `unpaired` (a key of
    UNPAIRED_REASONS, obtained from machine_pairing). Such a label is
    invisible to conf_vs_iou forever, so it must never be written by
    omission: the caller has to have looked at why, which is the point
    where the operator gets told (#162, 2026-08-06)."""
    poly = [[float(x), float(y)] for x, y in polygon]
    area = polygon_area(poly)
    mach = machine_summary(machine)
    # the gate is about the PAIRING only; a degenerate polygon is the
    # tracer's own precondition (>= 3 points before Done) and would
    # produce a misleading 'no machine candidate' message here
    paired = bool(mach and mach.get('contour'))
    if not paired:
        if not unpaired:
            raise ValueError(
                "refusing to write a trace label with no machine pairing "
                "(#162): label_iou() can never return a value for it, so "
                "it is worthless as ground truth. Pass unpaired=<reason> "
                f"(one of {sorted(UNPAIRED_REASONS)}) from "
                "machine_pairing(), and tell the operator, or supply the "
                "machine candidate.")
        if unpaired not in UNPAIRED_REASONS:
            raise ValueError(
                f"unknown unpaired reason {unpaired!r}; expected one of "
                f"{sorted(UNPAIRED_REASONS)}")
    return {
        'row_index': int(row_index),
        'frame_file': (row.get('frame_file') or '').strip(),
        'nominal_kV': (row.get('nominal_kV') or '').strip(),
        'tag': (row.get('tag') or '').strip(),
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S',
                                   time.localtime(now)),
        'user': user or getpass.getuser(),
        'polygon': poly,
        'n_points': len(poly),
        'area_px': round(area, 1),
        'frame_shape': [int(frame_shape[0]), int(frame_shape[1])],
        'zoom': round(float(zoom), 3),
        'overlays': dict(overlays or {}),
        'elapsed_s': None if elapsed_s is None else round(float(elapsed_s),
                                                          1),
        'snapped': bool(snapped),
        'machine': mach,
        # null on a usable label; otherwise the named reason IoU can
        # never be computed, so the calibration pass can report the gap
        # instead of the label just not showing up (#162)
        'unpaired': None if paired else unpaired,
    }


def load_labels(rundir, path=None):
    """-> list of label records (possibly empty). Raises ValueError on a
    corrupt file rather than silently treating labels as absent -- the
    GUI must refuse to append to (and later clobber) a file it cannot
    read."""
    p = path or os.path.join(rundir, LABELS_NAME)
    try:
        with open(p) as f:
            d = json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as e:
        raise ValueError(f"{p} is not valid JSON ({e}); fix or move it "
                         f"before tracing") from e
    return list(d.get('labels', []))


def append_label(rundir, rec, path=None):
    """Append one record, atomically (tmp + os.replace -- the same
    pattern as save_settings; a mid-write failure must not destroy the
    accumulated ground truth). -> the sidecar path."""
    p = path or os.path.join(rundir, LABELS_NAME)
    labels = load_labels(rundir, path=p)
    labels.append(rec)
    tmp = p + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({'version': LABELS_VERSION, 'labels': labels}, f,
                  indent=1)
    os.replace(tmp, p)
    return p


# ---------------------------------------------------------------------------
# conf-vs-IoU calibration (consumes the labels once they exist)
# ---------------------------------------------------------------------------

def label_iou(rec):
    """IoU between a label's polygon and its stored machine candidate,
    or None when the machine had no contour to compare."""
    if not is_paired(rec):
        return None
    shape = tuple(rec.get('frame_shape') or (1080, 1920))
    return iou(rec['polygon'], rec['machine']['contour'], shape)


def unpaired_labels(labels):
    """-> {reason: [rec, ...]} for every label whose IoU is NOT
    computable, i.e. every trace that cannot serve as ground truth.

    Labels written before the 2026-08-06 pairing gate carry no reason at
    all -- they are reported as 'unrecorded' rather than dropped, because
    the four that exist are exactly the ones an operator has to go back
    and redo."""
    out = {}
    for rec in labels:
        if is_paired(rec):
            continue
        if rec.get('unpaired'):
            reason = rec['unpaired']
        elif len(rec.get('polygon') or []) < 3:
            reason = 'degenerate-polygon'
        else:
            reason = 'unrecorded'
        out.setdefault(reason, []).append(rec)
    return out


def unpaired_summary(labels):
    """ASCII report of the labels that can never yield an IoU -- printed
    next to the calibration curve so an unusable label is visible in the
    one place the curve is read, not just absent from it."""
    gaps = unpaired_labels(labels)
    n = sum(len(v) for v in gaps.values())
    if not labels:
        # ASCII, like every other line here: this is the FIRST-USE branch
        # (a not-yet-traced run, a typo'd path), so it is the one most
        # likely to be read on the bench console -- an em dash aborted the
        # whole report with a UnicodeEncodeError under cp437/cp850
        # (measured 2026-08-06, the fourth time this trap has fired)
        return ["no labels yet - trace frames in Edge Review first"]
    if not n:
        return [f"all {len(labels)} label(s) carry a machine candidate "
                f"- none wasted"]
    lines = [f"WARNING: {n} of {len(labels)} label(s) have NO comparable "
             f"machine candidate - recovery measurements only, invisible "
             f"to the calibration above:"]
    for reason, recs in sorted(gaps.items()):
        rows = ', '.join(label_where(r) for r in recs[:6])
        if len(recs) > 6:
            rows += f", +{len(recs) - 6} more"
        # no parens around the list: label_where now ends each entry with
        # its own '(GUI frame N)', and the old wrapper turned every line
        # into a '))' pile-up that is exactly what an operator skims
        lines.append(f"  {reason:<20} {len(recs):>3}  {rows}")
        lines.append(f"      {unpaired_message(reason)}")
    return lines


def conf_vs_iou(labels):
    """-> [(conf, iou, method, rec), ...] for every label with a
    comparable machine candidate."""
    out = []
    for rec in labels:
        v = label_iou(rec)
        if v is None:
            continue
        m = rec['machine']
        out.append((float(m.get('conf', 0.0)), v,
                    m.get('method') or '?', rec))
    return out


def calibration_summary(pairs, target_iou=0.8, bins=(0.0, 0.5, 0.75,
                                                     0.85, 0.95, 1.01)):
    """ASCII summary of P(IoU >= target | conf bin) -- the curve that
    decides what accept_conf may rise to (#162 / handoff Open #1).
    `pairs` is conf_vs_iou() output. Returns a list of lines."""
    lines = [f"conf-vs-IoU calibration  ({len(pairs)} labeled frames, "
             f"target IoU >= {target_iou:g})"]
    if not pairs:
        lines.append("  no labels with a comparable machine candidate yet"
                     " -- trace frames in Edge Review first")
        return lines
    arr = sorted(pairs, key=lambda t: t[0])
    lines.append(f"  {'conf bin':>12} {'n':>4} {'P(IoU>=t)':>10} "
                 f"{'median IoU':>11}")
    for lo, hi in zip(bins[:-1], bins[1:]):
        sel = [t for t in arr if lo <= t[0] < hi]
        if not sel:
            continue
        ious = [t[1] for t in sel]
        p = sum(1 for v in ious if v >= target_iou) / len(ious)
        n_od = sum(1 for t in sel if label_scope(t[3]) == SCOPE_FRAME)
        lines.append(f"  {f'{lo:.2f}-{min(hi, 1.0):.2f}':>12} "
                     f"{len(sel):>4} {p:>10.2f} "
                     f"{float(np.median(ious)):>11.2f}"
                     + (f"   * {n_od} on-demand" if n_od else ""))
    by_m = {}
    for conf, v, m, rec in arr:
        by_m.setdefault(m, []).append((v, rec))
    for m, vs in sorted(by_m.items()):
        n_od = sum(1 for _v, r in vs if label_scope(r) == SCOPE_FRAME)
        lines.append(f"  {m:<12} n={len(vs):<3} median IoU "
                     f"{float(np.median([v for v, _r in vs])):.2f}"
                     + (f"   * {n_od} on-demand" if n_od else ""))
    # The scope tag is only worth writing if the curve's READER sees it
    # (review 2026-08-06: it was recorded in the sidecar and read by
    # nothing, which is the silent mix it was added to prevent).
    od = [t for t in arr if label_scope(t[3]) == SCOPE_FRAME]
    if od:
        lines += [
            f"  * {len(od)} of {len(arr)} point(s) come from a "
            f"single-frame on-demand detect ({SCOPE_FRAME}), not the run",
            "      pass: no ramp-order hysteresis bonus and no same-kV "
            "pair reconciliation, so the",
            "      conf can read up to 0.05 low AND a different candidate "
            "can rank first (measured",
            "      3-9% area difference where the disc fit refuses). "
            "Re-detect the run and",
            "      re-trace those frames to put them on the run-pass "
            "convention:"]
        shown = ', '.join(label_where(t[3]) for t in od[:8])
        if len(od) > 8:
            shown += f", +{len(od) - 8} more"
        lines.append(f"      {shown}")
    return lines


def _iter_label_files(paths):
    """Run dirs or parents-of-runs -> (rundir, labels) pairs."""
    import sldea_edge as se
    for p in paths:
        cand = [p] + [os.path.join(p, n) for n in sorted(os.listdir(p))
                      if os.path.isdir(os.path.join(p, n))] \
            if os.path.isdir(p) else []
        for d in cand:
            if se.run_csv(d) and os.path.exists(
                    os.path.join(d, LABELS_NAME)):
                yield d, load_labels(d)


def main(argv):
    if not argv:
        print(__doc__.strip().split('\n\n')[-1])
        return 2
    pairs, all_labels, n_runs = [], [], 0
    for rundir, labels in _iter_label_files(argv):
        n_runs += 1
        # display-only provenance: the pooled report names the run each
        # row came from and the frame number Edge Review shows it as
        # (label_where), neither written back to the sidecar -- the
        # stored records stay exactly as they are on disk (`#255`).
        # (isinstance because a hand-edited sidecar can hold anything)
        frames = gui_frame_map(rundir)
        for rec in labels:
            if isinstance(rec, dict):
                rec['_run'] = os.path.basename(rundir.rstrip('\\/'))
                i = rec.get('row_index')
                if isinstance(i, int) and i in frames:
                    rec['_gui_frame'] = frames[i]
        all_labels.extend(labels)
        pairs.extend(conf_vs_iou(labels))
        gaps = sum(len(v) for v in unpaired_labels(labels).values())
        print(f"{os.path.basename(rundir)}: {len(labels)} label(s)"
              + (f"  ({gaps} UNPAIRED)" if gaps else ""))
    print(f"\n{len(all_labels)} labels across {n_runs} run(s)")
    for line in calibration_summary(pairs):
        print(line)
    print()
    for line in unpaired_summary(all_labels):
        print(line)
    return 0


if __name__ == '__main__':
    import sys
    raise SystemExit(main(sys.argv[1:]))
