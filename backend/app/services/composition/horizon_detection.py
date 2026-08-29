"""Horizon detection via vertical-gradient row projection.

A horizon is a strong, sustained horizontal edge that divides a calmer
sky-like region above from a textured ground/water region below.

Algorithm:
1. Build a row-energy profile from the vertical Sobel gradient.
2. Collect all candidate rows whose energy exceeds a minimum threshold.
3. For each candidate (highest energy first), verify three properties:

   Sky-calm check: the local window of rows directly above the candidate
   must be calmer than the candidate row itself (relative threshold) AND
   calmer than the frame average (absolute threshold).

   Ground-noisier check: the window of rows directly BELOW the candidate
   must be at least as textured as the window above.  Real water/ground is
   always noisier than sky; a structural edge above a dark silhouette
   building or a plain studio background fails this gate.

   Width-coverage check: the edge must be present across all three
   horizontal thirds of the frame.

4. If the strict pass finds no result, retry with relaxed thresholds but
   require a stronger ground-vs-sky noisiness contrast.

This multi-candidate, multi-pass approach handles:
- Photos where the waterline is weaker than a nearby structural edge
- Urban waterfronts where the "sky" above is slightly noisy (city haze)
- Silhouette buildings whose top edge would otherwise look like a horizon

Tilt is measured separately, and only from the detected horizon itself:
sample one sub-pixel edge row per column band inside a narrow strip around
the detected row, fit a line through those samples with a Theil-Sen (median
pairwise slope) estimator, and accept the result only if enough bands across
enough of the frame width agree with it.  When they do not, `tilt_reliable`
is False and `tilt_angle` is 0.0 — consumers must not display a tilt then.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from app.services.composition._utils import to_gray_u8

# --- Pass-1 (strict) parameters ---
_THRESH_STRICT = 2.5           # ×mean row energy
_SKY_ABS_STRICT = 0.80         # sky_window_pp < X × global_mean_pp
_SKY_REL_STRICT = 0.85         # sky_window_pp < X × candidate_pp
_GROUND_MIN_RATIO_STRICT = 0.90  # ground_window_pp > X × sky_window_pp

# --- Pass-2 (relaxed) parameters ---
# Lowered energy threshold to find subtle waterlines; compensated by
# requiring significantly noisier ground below than sky above.
_THRESH_RELAXED = 1.60
_SKY_ABS_RELAXED = 1.40        # sky may be moderately noisy (urban haze)
_SKY_REL_RELAXED = 0.80
_GROUND_MIN_RATIO_RELAXED = 1.20  # ground must be 20% noisier than sky above
# Tighter vertical position range for the relaxed pass to avoid picking up
# overhead architectural edges (< 20% height) or ground-level edges (> 84%).
_Y_MIN_RELAXED = 0.20
_Y_MAX_RELAXED = 0.84

# Fraction of frame height to sample for sky/ground windows.
_WIN_FRAC = 0.08
# Y margins — horizons rarely sit at the very top or bottom.
_Y_MARGIN_FRAC = 0.08
_LEVEL_TOLERANCE_DEG = 3.0

# --- Tilt estimation parameters ---
# Only rows within this fraction of the frame height of the detected horizon
# are searched. Anything further away is a different feature, not the horizon.
_TILT_STRIP_FRAC = 0.15
# Column bands sampled across the width; each yields at most one observation.
# Summing within a band suppresses per-pixel noise before taking the argmax.
_TILT_BANDS = 48
# A band's peak must clear this multiple of the frame-mean gradient (an edge is
# actually there) and this multiple of the band's own mean inside the strip
# (the profile has a real peak rather than a flat, argmax-is-noise ramp).
_TILT_BAND_ABS = 1.0
_TILT_BAND_REL = 1.5
# Fit acceptance. A tilt is only reported when this many bands survive, that
# share of them sits within the residual tolerance, and those agreeing bands
# span this fraction of the frame width.
_TILT_MIN_BANDS = 8
_TILT_INLIER_TOL_FRAC = 0.02   # × height, floored at 2 px
_TILT_MIN_INLIER_RATIO = 0.60
_TILT_MIN_SPAN_FRAC = 0.50
# Past this angle the fitted line is some other structure, not a horizon.
_TILT_MAX_DEG = 30.0


def _check_candidate(
    peak: int,
    sobel_y: np.ndarray,
    row_energy: np.ndarray,
    height: int,
    width: int,
    global_mean_pp: float,
    sky_abs: float,
    sky_rel: float,
    ground_min_ratio: float,
) -> bool:
    """Return True if *peak* passes sky-calm, ground-noisier, and thirds checks."""
    sky_win = max(5, int(_WIN_FRAC * height))

    # --- sky-calm check ---
    window_start = max(0, peak - sky_win)
    if peak - window_start < 3:
        return False
    sky_win_pp = float(sobel_y[window_start:peak, :].mean())
    cand_pp = row_energy[peak] / width
    if cand_pp <= 0:
        return False
    if sky_win_pp > sky_abs * global_mean_pp:
        return False  # sky too noisy relative to the frame average
    if sky_win_pp > sky_rel * cand_pp:
        return False  # sky too noisy relative to the edge itself

    # --- ground-noisier check ---
    ground_end = min(height, peak + 1 + sky_win)
    if ground_end > peak + 1:
        ground_win_pp = float(sobel_y[peak + 1 : ground_end, :].mean())
        if ground_win_pp < ground_min_ratio * sky_win_pp:
            return False  # ground below is not noisier than sky above

    # --- width-coverage check ---
    third = max(1, width // 3)
    return (
        float(sobel_y[peak, :third].mean()) > global_mean_pp
        and float(sobel_y[peak, third : 2 * third].mean()) > global_mean_pp
        and float(sobel_y[peak, 2 * third :].mean()) > global_mean_pp
    )


def _subpixel_peak(profile: np.ndarray, idx: int) -> float:
    """Refine an integer argmax to sub-row precision by parabolic interpolation.

    Band argmaxes are whole rows, and that quantisation is the dominant error
    in the slope fit for shallow tilts — a 1 px step across the frame is
    already ~0.2°. Fitting a parabola through the peak and its two neighbours
    recovers the fractional row.
    """
    if idx <= 0 or idx >= len(profile) - 1:
        return float(idx)
    a, b, c = float(profile[idx - 1]), float(profile[idx]), float(profile[idx + 1])
    denom = a - 2.0 * b + c
    if denom == 0.0:
        return float(idx)
    offset = 0.5 * (a - c) / denom
    return float(idx) + max(-1.0, min(1.0, offset))


def _sample_edge_rows(
    sobel_y: np.ndarray,
    peak: int,
    height: int,
    width: int,
    global_mean_pp: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Locate the horizon edge once per column band within a strip around *peak*.

    Returns (xs, ys): band centre columns and their sub-pixel edge rows. Bands
    with no convincing edge are dropped rather than contributing a guess.
    """
    half_strip = max(3, int(_TILT_STRIP_FRAC * height))
    r0 = max(0, peak - half_strip)
    r1 = min(height, peak + half_strip + 1)
    if r1 - r0 < 3:
        return np.empty(0), np.empty(0)

    n_bands = min(_TILT_BANDS, width)
    edges = np.linspace(0, width, n_bands + 1).astype(int)

    xs: list[float] = []
    ys: list[float] = []
    for i in range(n_bands):
        c0, c1 = int(edges[i]), int(edges[i + 1])
        if c1 <= c0:
            continue
        profile = sobel_y[r0:r1, c0:c1].mean(axis=1)
        idx = int(np.argmax(profile))
        # An argmax pinned to the strip boundary means the true maximum lies
        # outside the window — that band is looking at something else.
        if idx == 0 or idx == len(profile) - 1:
            continue
        band_peak = float(profile[idx])
        if band_peak < _TILT_BAND_ABS * global_mean_pp:
            continue  # no edge worth calling an edge in this band
        if band_peak < _TILT_BAND_REL * float(profile.mean()):
            continue  # profile too flat — the argmax is noise, not a peak
        xs.append((c0 + c1 - 1) / 2.0)
        ys.append(r0 + _subpixel_peak(profile, idx))

    return np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)


def _theil_sen(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float] | None:
    """Median of all pairwise slopes, plus the median intercept.

    Chosen over least squares because a minority of bands can still sit on an
    unrelated edge (a roofline clipping the strip); the median ignores them,
    where a squared-error fit would be dragged toward them.
    """
    i, j = np.triu_indices(len(xs), k=1)
    dx = xs[j] - xs[i]
    ok = dx != 0
    if not np.any(ok):
        return None
    slope = float(np.median((ys[j][ok] - ys[i][ok]) / dx[ok]))
    intercept = float(np.median(ys - slope * xs))
    return slope, intercept


def _estimate_tilt(
    sobel_y: np.ndarray,
    peak: int,
    height: int,
    width: int,
    global_mean_pp: float,
) -> tuple[float, bool]:
    """Return (tilt_degrees, reliable) for the horizon detected at row *peak*.

    Positive tilt means the right-hand side of the horizon sits lower in the
    frame. Returns (0.0, False) whenever the evidence does not support an
    angle, so callers never have to distinguish "level" from "unknown".
    """
    xs, ys = _sample_edge_rows(sobel_y, peak, height, width, global_mean_pp)
    if len(xs) < _TILT_MIN_BANDS:
        return 0.0, False

    fit = _theil_sen(xs, ys)
    if fit is None:
        return 0.0, False
    slope, intercept = fit

    tol = max(2.0, _TILT_INLIER_TOL_FRAC * height)
    inliers = np.abs(ys - (slope * xs + intercept)) <= tol
    n_inliers = int(inliers.sum())
    if n_inliers < _TILT_MIN_BANDS or n_inliers < _TILT_MIN_INLIER_RATIO * len(xs):
        return 0.0, False  # the bands disagree; no single line explains them

    # The agreeing bands must also be spread out. A tight cluster of inliers
    # pins down a point, not a slope.
    span = float(xs[inliers].max() - xs[inliers].min())
    if span < _TILT_MIN_SPAN_FRAC * width:
        return 0.0, False

    # Theil-Sen finds the consensus; least squares on the inliers alone then
    # sharpens it now that the outliers are gone.
    slope = float(np.polyfit(xs[inliers], ys[inliers], 1)[0])
    tilt = math.degrees(math.atan(slope))
    if abs(tilt) > _TILT_MAX_DEG:
        return 0.0, False
    return tilt, True


def detect_horizon(image: np.ndarray) -> dict:
    gray = to_gray_u8(image).astype(np.float64)
    height, width = gray.shape

    not_found = {
        "horizon_detected": False,
        "horizon_y": None,
        "is_level": False,
        "tilt_angle": None,
        "tilt_reliable": False,
    }
    if height < 10 or width < 10:
        return not_found

    sobel_y = np.abs(cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3))
    row_energy = sobel_y.sum(axis=1)
    mean_energy = float(row_energy.mean())
    if mean_energy <= 0:
        return not_found

    global_mean_pp = mean_energy / width

    def _find(
        thresh_factor: float,
        sky_abs: float,
        sky_rel: float,
        ground_ratio: float,
        y_min: float = _Y_MARGIN_FRAC,
        y_max: float = 1.0 - _Y_MARGIN_FRAC,
    ):
        r_min = int(y_min * height)
        r_max = int(y_max * height)
        threshold = thresh_factor * mean_energy
        cands = sorted(
            [r for r in range(r_min, r_max + 1) if row_energy[r] >= threshold],
            key=lambda r: row_energy[r],
            reverse=True,
        )
        for peak in cands:
            if _check_candidate(
                peak, sobel_y, row_energy, height, width, global_mean_pp,
                sky_abs, sky_rel, ground_ratio,
            ):
                return peak
        return None

    # Pass 1: strict — avoids false positives on photos with no real horizon.
    peak = _find(_THRESH_STRICT, _SKY_ABS_STRICT, _SKY_REL_STRICT, _GROUND_MIN_RATIO_STRICT)

    # Pass 2: relaxed — picks up subtle waterlines in complex outdoor scenes
    # where the mean row energy is high and the waterline is relatively weak.
    # Tighter vertical position range avoids architectural/ground false positives.
    if peak is None:
        peak = _find(
            _THRESH_RELAXED, _SKY_ABS_RELAXED, _SKY_REL_RELAXED, _GROUND_MIN_RATIO_RELAXED,
            y_min=_Y_MIN_RELAXED, y_max=_Y_MAX_RELAXED,
        )

    if peak is None:
        return not_found

    # Tilt is fitted to the edge at `peak` itself. The previous version instead
    # compared the vertical-gradient argmax of the left half against that of the
    # right half — two independent maxima over the whole frame that need not lie
    # on the horizon at all, which reported 9-17 degrees on level photos.
    tilt, tilt_reliable = _estimate_tilt(sobel_y, peak, height, width, global_mean_pp)

    return {
        "horizon_detected": True,
        "horizon_y": round(peak / max(height - 1, 1), 3),
        "is_level": bool(abs(tilt) <= _LEVEL_TOLERANCE_DEG),
        "tilt_angle": round(tilt, 2),
        "tilt_reliable": tilt_reliable,
    }
