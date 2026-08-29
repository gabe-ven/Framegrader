"""Leading lines via the Line Segment Detector (LSD).

LSD (cv2.createLineSegmentDetector) yields cleaner, longer, less noisy
segments than the probabilistic Hough transform, which fragments a single
physical edge into many short near-duplicates across textured regions. If LSD
is unavailable in the installed OpenCV build (it has been patent-gated in some
releases) or construction fails, we silently fall back to HoughLinesP.

A detected segment counts as a leading line only if it survives three filters:

1. Length — at least 20% of the frame diagonal (kills texture noise).
2. Angle  — more than 15 degrees from horizontal (near-horizontal edges are
   horizon candidates, handled by horizon_detection; not leading lines).
3. Edge   — it enters the frame from a border: an endpoint sits within 10% of
   a frame edge, or the segment's infinite extension crosses a frame edge.

Among the survivors we measure convergence toward the subject: a line "leads to
the subject" when its infinite extension passes within 15% of the frame
diagonal of the subject centroid (subject.centroid when available, else the
frame center (0.5, 0.5)). The photo has leading lines when at least one
survivor converges; the convergence fraction (passing / surviving) is the
internal strength signal that drives has_leading_lines.
"""

from __future__ import annotations

import math
from collections import defaultdict

import cv2
import numpy as np

from app.services.composition._utils import canny_edges_structural, to_gray_u8
from app.services.composition.subject import Subject

# Cap on how many segments we hand back to the overlay renderer.
_MAX_LINES = 20

# --- Filter thresholds -----------------------------------------------------
# Minimum segment length as a fraction of the frame diagonal.
_MIN_LENGTH_FRACTION = 0.20
# Minimum angle from horizontal (degrees). At/below this a line is a horizon
# candidate, not a leading line.
_MIN_ANGLE_FROM_HORIZONTAL = 15.0
# An endpoint within this fraction of any edge (per axis) counts as touching it.
_EDGE_MARGIN_FRACTION = 0.10
# A line's extension within this fraction of the frame diagonal of the subject
# centroid counts as "leading to the subject".
_CONVERGENCE_FRACTION = 0.15

# --- Fragment merging ------------------------------------------------------
# LSD reports one long physical edge as many short collinear pieces, split at
# every occlusion, intersection and texture change. Measured on real photos:
# of 1,000-4,000 raw segments per frame, zero to one ever cleared the 20%
# length gate above, so the detector returned False on every photograph in the
# eval set. Fusing fragments back into whole lines before the length gate is
# what makes that gate satisfiable.
_MERGE_ANGLE_TOLERANCE = 4.0      # degrees between two fragments' directions
_MERGE_OFFSET_FRACTION = 0.006    # perpendicular offset, as a frame-diagonal fraction
# Floor for the offset tolerance. LSD reports a stroke of any thickness as its
# two boundary edges, a few pixels apart; below this floor those two halves of
# one line stay separate and get counted (and voted on) twice.
_MERGE_MIN_OFFSET_PX = 5.0
# Collinear fragments this far apart along the line are treated as separate
# edges rather than one occluded line, so we don't invent a line spanning the
# frame out of two unrelated pieces.
_MERGE_MAX_GAP_FRACTION = 0.25
# Fragments below this length can't meaningfully extend a line and dominate the
# pairwise merge cost, so they're dropped before merging.
_MERGE_MIN_FRAGMENT_FRACTION = 0.02

# --- Structure gates -------------------------------------------------------
# Surviving lines must span a meaningful part of the frame; a dense cluster of
# long-ish segments inside one small region is texture (bark, foliage, grating),
# not composition. A line that leads the eye has to travel, so the gate is
# "collectively cover at least half the frame diagonal".
#
# On the eval set this is the single most discriminating signal: photos with
# real leading lines spanned 0.63-0.96, those without spanned 0.33-0.69. Eleven
# photos is far too few to fit a threshold to, so this is set to the round,
# defensible half rather than the 0.63 the data would suggest.
_MIN_SPREAD_FRACTION = 0.50
# Vanishing-point coherence. Real leading lines converge somewhere; a facade of
# columns and window rows spans the frame without ever converging. Below this
# many lines a vanishing point isn't defined (any two non-parallel lines meet
# somewhere), so the check is skipped rather than applied vacuously.
_VP_MIN_LINES = 3
_VP_PARALLEL_EPS_DEG = 2.0      # closer than this in angle -> treated as parallel
_VP_CLUSTER_FRACTION = 0.25     # lines passing this close to a point share it
# A vanishing point is, by definition, where three or more lines meet. On
# busier frames require proportionally more agreement, so a handful of chance
# crossings among many lines doesn't read as perspective.
_VP_MIN_CONVERGING = 3
_VP_CONVERGING_FRACTION = 0.25

_NOT_FOUND = {
    "has_leading_lines": False,
    "line_count": 0,
    "dominant_angle": None,
    "lines": [],
}


def detect_leading_lines(image: np.ndarray, subject: Subject | None = None) -> dict:
    gray = to_gray_u8(image)
    height, width = gray.shape
    frame_diagonal = math.hypot(width, height)
    if frame_diagonal == 0:
        return dict(_NOT_FOUND)

    # 1. Detect segments — LSD first, Hough as a silent fallback.
    raw = _detect_lsd(gray)
    if raw is None:
        raw = _detect_hough(gray, height, width)
    if not raw:
        return dict(_NOT_FOUND)

    segments = [_segment(x1, y1, x2, y2) for (x1, y1, x2, y2) in raw]

    # 2. Fuse collinear fragments back into whole lines. Must happen BEFORE the
    #    length gate — LSD's pieces are individually far too short to clear it.
    segments = _merge_segments(segments, frame_diagonal)

    # 3. Geometry filters: length, angle-from-horizontal, edge entry.
    survivors = [
        s for s in segments if _passes_filters(s, width, height, frame_diagonal)
    ]
    if not survivors:
        return dict(_NOT_FOUND)
    survivors.sort(key=lambda s: s["length"], reverse=True)

    # 4. Structure gates: the lines must span the frame and share a vanishing
    #    point. Together these reject texture clusters and grid-like facades
    #    that clear the per-line geometry but aren't leading lines.
    if not _spans_frame(survivors, frame_diagonal):
        return dict(_NOT_FOUND)
    if not _has_vanishing_point(survivors, frame_diagonal):
        return dict(_NOT_FOUND)

    # 5. Convergence toward the subject centroid (normalized -> pixels).
    cx, cy = subject.centroid if subject is not None else (0.5, 0.5)
    centroid_x, centroid_y = cx * width, cy * height
    converge_threshold = _CONVERGENCE_FRACTION * frame_diagonal
    converging = [
        s
        for s in survivors
        if _point_to_line_distance(
            centroid_x, centroid_y, s["x1"], s["y1"], s["x2"], s["y2"]
        )
        <= converge_threshold
    ]

    # A photo "has leading lines" only when at least one surviving line actually
    # leads toward the subject. Lines that clear the geometry filters but ignore
    # the subject are structure, not composition.
    if not converging:
        return dict(_NOT_FOUND)

    return {
        "has_leading_lines": True,
        "line_count": len(survivors),
        # Reported over the converging lines, not every survivor. Length-weighting
        # across all structure lets whatever is tallest in frame win — on three
        # eval photos that returned 90° (building edges, a bridge tower) for
        # shots whose actual leading line runs at 25-40°. The converging subset
        # is what "leading line" means here, so it is what the angle describes.
        "dominant_angle": _dominant_angle(converging),
        "lines": survivors[:_MAX_LINES],
    }


# ---------------------------------------------------------------------------
# Detection backends
# ---------------------------------------------------------------------------


def _detect_lsd(gray: np.ndarray) -> list[tuple[float, float, float, float]] | None:
    """Detect line segments with LSD. Returns None if LSD is unavailable."""
    try:
        lsd = cv2.createLineSegmentDetector()
        detected = lsd.detect(gray)
    except Exception:  # noqa: BLE001 - any LSD failure -> fall back to Hough
        return None

    # detect() returns (lines, width, prec, nfa), or bare lines on some builds.
    lines = detected[0] if isinstance(detected, tuple) else detected
    if lines is None or len(lines) == 0:
        return None

    # Shape differs across major OpenCV versions: 4.x returns (N, 1, 4), 5.0
    # dropped the middle axis and returns (N, 4). Indexing the old layout
    # directly raised "'numpy.float32' object is not iterable" the moment CI
    # resolved OpenCV 5. Flattening accepts either, so the next bump can't
    # reintroduce it.
    coords = np.asarray(lines, dtype=float).reshape(-1, 4)
    return [(float(a), float(b), float(c), float(d)) for a, b, c, d in coords]


def _detect_hough(
    gray: np.ndarray, height: int, width: int
) -> list[tuple[float, float, float, float]] | None:
    """Silent fallback: probabilistic Hough transform over structural edges."""
    edges = canny_edges_structural(gray)
    min_length = max(10.0, 0.15 * min(height, width))
    raw = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=25,
        minLineLength=min_length,
        maxLineGap=20,
    )
    if raw is None:
        return None
    return [tuple(float(v) for v in seg) for seg in raw[:, 0, :]]


# ---------------------------------------------------------------------------
# Fragment merging
# ---------------------------------------------------------------------------


def _merge_segments(segments: list[dict], frame_diagonal: float) -> list[dict]:
    """Fuse collinear fragments of the same physical edge into single segments.

    Greedy, longest-first: each unclaimed segment seeds a group, absorbs every
    remaining fragment that lies along the same infinite line, and the group is
    replaced by the segment spanning its extreme projections. Seeding from the
    longest fragment means the group's direction comes from the most reliable
    piece rather than an arbitrary one.
    """
    if not segments:
        return []

    offset_tol = max(_MERGE_MIN_OFFSET_PX, _MERGE_OFFSET_FRACTION * frame_diagonal)
    gap_tol = _MERGE_MAX_GAP_FRACTION * frame_diagonal
    min_fragment = _MERGE_MIN_FRAGMENT_FRACTION * frame_diagonal

    candidates = sorted(
        (s for s in segments if s["length"] >= min_fragment),
        key=lambda s: s["length"],
        reverse=True,
    )
    if not candidates:
        return []

    claimed = [False] * len(candidates)
    merged: list[dict] = []

    for i, base in enumerate(candidates):
        if claimed[i]:
            continue
        claimed[i] = True
        group = [base]
        for j in range(i + 1, len(candidates)):
            if claimed[j]:
                continue
            if _is_collinear(base, candidates[j], offset_tol, gap_tol):
                claimed[j] = True
                group.append(candidates[j])
        merged.append(_fuse(group) if len(group) > 1 else base)

    return merged


def _is_collinear(base: dict, other: dict, offset_tol: float, gap_tol: float) -> bool:
    """True if ``other`` lies along the same infinite line as ``base``."""
    if _angle_difference(base["angle"], other["angle"]) > _MERGE_ANGLE_TOLERANCE:
        return False

    # Both endpoints must sit near base's line, not just the midpoint — a
    # fragment crossing the line at a shallow angle would otherwise qualify.
    for px, py in ((other["x1"], other["y1"]), (other["x2"], other["y2"])):
        if (
            _point_to_line_distance(
                px, py, base["x1"], base["y1"], base["x2"], base["y2"]
            )
            > offset_tol
        ):
            return False

    return _projection_gap(base, other) <= gap_tol


def _angle_difference(a: float, b: float) -> float:
    """Smallest angle between two undirected line directions, in [0, 90]."""
    diff = abs(a - b) % 180
    return min(diff, 180 - diff)


def _unit_vector(seg: dict) -> tuple[float, float, float]:
    """Direction unit vector of ``seg`` plus its length."""
    dx = seg["x2"] - seg["x1"]
    dy = seg["y2"] - seg["y1"]
    norm = math.hypot(dx, dy)
    if norm == 0:
        return 0.0, 0.0, 0.0
    return dx / norm, dy / norm, norm


def _projection_gap(base: dict, other: dict) -> float:
    """Gap between the two segments' extents along base's direction.

    Zero when they overlap. Used to keep two unrelated collinear edges at
    opposite ends of the frame from fusing into one invented line.
    """
    ux, uy, norm = _unit_vector(base)
    if norm == 0:
        return float("inf")

    def project(px: float, py: float) -> float:
        return (px - base["x1"]) * ux + (py - base["y1"]) * uy

    base_lo, base_hi = 0.0, norm
    o1 = project(other["x1"], other["y1"])
    o2 = project(other["x2"], other["y2"])
    other_lo, other_hi = min(o1, o2), max(o1, o2)

    if other_hi < base_lo:
        return base_lo - other_hi
    if other_lo > base_hi:
        return other_lo - base_hi
    return 0.0  # overlapping


def _fuse(group: list[dict]) -> dict:
    """Collapse a collinear group into the segment spanning its full extent."""
    base = group[0]
    ux, uy, norm = _unit_vector(base)
    if norm == 0:
        return base

    projections = [
        (px - base["x1"]) * ux + (py - base["y1"]) * uy
        for seg in group
        for px, py in ((seg["x1"], seg["y1"]), (seg["x2"], seg["y2"]))
    ]
    lo, hi = min(projections), max(projections)
    return _segment(
        base["x1"] + ux * lo,
        base["y1"] + uy * lo,
        base["x1"] + ux * hi,
        base["y1"] + uy * hi,
    )


# ---------------------------------------------------------------------------
# Structure gates
# ---------------------------------------------------------------------------


def _spans_frame(lines: list[dict], frame_diagonal: float) -> bool:
    """True if the lines collectively cover a meaningful part of the frame.

    A tight cluster of segments — bark, foliage, a grating — can clear every
    per-line filter while occupying one small region. Real leading lines lead
    somewhere, which means they span.
    """
    xs = [v for ln in lines for v in (ln["x1"], ln["x2"])]
    ys = [v for ln in lines for v in (ln["y1"], ln["y2"])]
    spread = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    return spread >= _MIN_SPREAD_FRACTION * frame_diagonal


def _has_vanishing_point(lines: list[dict], frame_diagonal: float) -> bool:
    """True if enough of the lines' pairwise intersections agree on one point.

    Skipped below ``_VP_MIN_LINES``: two non-parallel lines always meet
    somewhere, so the test would pass vacuously and tell us nothing.

    Parallel pairs contribute no intersection, so a set of purely parallel
    lines — a facade of columns, a grid — finds no vanishing point and is
    rejected, which is the intent.
    """
    if len(lines) < _VP_MIN_LINES:
        return True

    intersections: list[tuple[float, float]] = []
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            point = _line_intersection(lines[i], lines[j])
            if point is not None:
                intersections.append(point)

    if not intersections:
        return False

    # Score a candidate point by how many *lines* pass near it, not by what
    # fraction of pairwise intersections land there. With n lines there are
    # n(n-1)/2 pairs, so on a busy frame the incidental crossings swamp the
    # real vanishing point and a fraction-based test rejects genuine
    # perspective — it threw out two photographs that plainly have it.
    radius = _VP_CLUSTER_FRACTION * frame_diagonal
    required = max(_VP_MIN_CONVERGING, math.ceil(_VP_CONVERGING_FRACTION * len(lines)))

    best = 0
    for point in intersections:
        through = sum(
            1
            for ln in lines
            if _point_to_line_distance(
                point[0], point[1], ln["x1"], ln["y1"], ln["x2"], ln["y2"]
            )
            <= radius
        )
        best = max(best, through)

    return best >= required


def _line_intersection(a: dict, b: dict) -> tuple[float, float] | None:
    """Intersection of two infinite lines, or None when near-parallel."""
    if _angle_difference(a["angle"], b["angle"]) < _VP_PARALLEL_EPS_DEG:
        return None

    x1, y1 = a["x1"], a["y1"]
    x2, y2 = a["x2"], a["y2"]
    x3, y3 = b["x1"], b["y1"]
    x4, y4 = b["x2"], b["y2"]

    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if denominator == 0:
        return None

    det_a = x1 * y2 - y1 * x2
    det_b = x3 * y4 - y3 * x4
    px = (det_a * (x3 - x4) - (x1 - x2) * det_b) / denominator
    py = (det_a * (y3 - y4) - (y1 - y2) * det_b) / denominator
    return px, py


# ---------------------------------------------------------------------------
# Segment construction + filters
# ---------------------------------------------------------------------------


def _segment(x1: float, y1: float, x2: float, y2: float) -> dict:
    ix1, iy1, ix2, iy2 = (int(round(v)) for v in (x1, y1, x2, y2))
    angle = math.degrees(math.atan2(iy2 - iy1, ix2 - ix1)) % 180
    length = math.hypot(ix2 - ix1, iy2 - iy1)
    return {
        "x1": ix1,
        "y1": iy1,
        "x2": ix2,
        "y2": iy2,
        "angle": round(angle, 1),
        "length": round(length, 1),
    }


def _passes_filters(
    seg: dict, width: int, height: int, frame_diagonal: float
) -> bool:
    if seg["length"] < _MIN_LENGTH_FRACTION * frame_diagonal:
        return False
    if _angle_from_horizontal(seg["angle"]) <= _MIN_ANGLE_FROM_HORIZONTAL:
        return False
    return _enters_from_edge(seg, width, height)


def _angle_from_horizontal(angle: float) -> float:
    """Angle to the nearest horizontal, in [0, 90] degrees."""
    a = angle % 180
    return min(a, 180 - a)


def _enters_from_edge(seg: dict, width: int, height: int) -> bool:
    """True if an endpoint is within the edge margin, or the infinite line
    extension crosses the frame border."""
    margin_x = _EDGE_MARGIN_FRACTION * width
    margin_y = _EDGE_MARGIN_FRACTION * height
    for px, py in ((seg["x1"], seg["y1"]), (seg["x2"], seg["y2"])):
        if (
            px <= margin_x
            or px >= width - margin_x
            or py <= margin_y
            or py >= height - margin_y
        ):
            return True
    return _line_crosses_frame_border(seg, width, height)


def _line_crosses_frame_border(seg: dict, width: int, height: int) -> bool:
    """True if the infinite line through the segment intersects the frame
    rectangle boundary [0, width] x [0, height]."""
    x1, y1, x2, y2 = seg["x1"], seg["y1"], seg["x2"], seg["y2"]
    dx, dy = x2 - x1, y2 - y1
    eps = 1e-9
    if dx != 0:
        for xb in (0.0, float(width)):
            t = (xb - x1) / dx
            y = y1 + t * dy
            if -eps <= y <= height + eps:
                return True
    if dy != 0:
        for yb in (0.0, float(height)):
            t = (yb - y1) / dy
            x = x1 + t * dx
            if -eps <= x <= width + eps:
                return True
    return False


def _point_to_line_distance(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    """Perpendicular distance from a point to the infinite line through two points."""
    dx = x2 - x1
    dy = y2 - y1
    norm = math.hypot(dx, dy)
    if norm == 0:
        return math.hypot(px - x1, py - y1)
    return abs(dy * (px - x1) - dx * (py - y1)) / norm


def _dominant_angle(lines: list[dict]) -> float:
    """Length-weighted dominant angle, binned to 10 degrees (in [0, 180))."""
    weight: dict[int, float] = defaultdict(float)
    for ln in lines:
        bin_ = int(round(ln["angle"] / 10.0) * 10) % 180
        weight[bin_] += ln["length"]
    return float(max(weight, key=weight.__getitem__))
