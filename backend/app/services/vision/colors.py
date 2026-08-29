"""Dominant colors via k-means clustering of the pixels."""

from __future__ import annotations

import cv2
import numpy as np

# k-means accuracy doesn't require every pixel — sample this many at most.
# 4096 gives stable cluster results while being orders of magnitude faster
# than running k-means on a full 26 MP image.
_MAX_PIXELS_FOR_KMEANS = 4096

# Raw pixel scatter for the 3D color-space point cloud. Much smaller than the
# k-means sample — this renders as individual WebGL points on the frontend,
# so it's sized for visual density rather than statistical accuracy.
_MAX_COLOR_SAMPLES = 500

# Fixed seed for OpenCV's (thread-local) RNG so k-means clustering is
# reproducible; matches the seed used for GrabCut in subject_localization.
_CV_RNG_SEED = 42


def dominant_colors(image: np.ndarray, k: int = 5) -> list[dict]:
    """Return up to `k` dominant colors, sorted by coverage (most first).

    Each entry: {"hex": "#rrggbb", "rgb": [r, g, b], "proportion": 0–1}.
    `k` is clamped to the number of distinct colors so tiny/flat images work.
    """
    from app.services.vision._utils import to_rgb

    rgb = to_rgb(image)
    pixels = rgb.reshape(-1, 3)
    if pixels.size == 0:
        return []

    # Subsample for large images before running k-means.
    if len(pixels) > _MAX_PIXELS_FOR_KMEANS:
        rng = np.random.default_rng(seed=42)
        idx = rng.choice(len(pixels), size=_MAX_PIXELS_FOR_KMEANS, replace=False)
        pixels = pixels[idx]

    distinct, distinct_counts = np.unique(pixels, axis=0, return_counts=True)

    # When there are at most `k` distinct colors (flat or tiny images), report
    # them exactly. kmeans is only well-posed — and only needed — when the
    # palette is larger than the cluster count.
    if len(distinct) <= k:
        centers = distinct.astype(np.float32)
        counts = distinct_counts
    else:
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        # KMEANS_PP_CENTERS draws its initial centers from OpenCV's RNG, so the
        # same photo produced a different palette on every call. The pixel
        # subsample above is already seeded; seeding here makes the clustering
        # reproducible too. cv2's RNG is thread-local, so this stays confined to
        # the calling thread.
        cv2.setRNGSeed(_CV_RNG_SEED)
        _, labels, centers = cv2.kmeans(
            pixels.astype(np.float32), k, None, criteria, 3, cv2.KMEANS_PP_CENTERS
        )
        counts = np.bincount(labels.flatten(), minlength=k)

    total = int(counts.sum())
    result: list[dict] = []
    for idx in np.argsort(counts)[::-1]:
        r, g, b = (int(np.clip(round(float(c)), 0, 255)) for c in centers[idx])
        result.append(
            {
                "hex": f"#{r:02x}{g:02x}{b:02x}",
                "rgb": [r, g, b],
                "proportion": round(float(counts[idx] / total), 4),
            }
        )
    return result


def color_samples(image: np.ndarray, n: int = _MAX_COLOR_SAMPLES) -> list[list[int]]:
    """Return up to `n` raw pixel RGB triples, randomly sampled without replacement.

    Unlike `dominant_colors` (which reduces the image to a handful of cluster
    centers), this preserves the actual scatter of individual pixel colors —
    used to plot a 3D RGB color-space point cloud on the frontend.
    """
    from app.services.vision._utils import to_rgb

    rgb = to_rgb(image)
    pixels = rgb.reshape(-1, 3)
    if pixels.size == 0:
        return []

    if len(pixels) > n:
        rng = np.random.default_rng(seed=42)
        idx = rng.choice(len(pixels), size=n, replace=False)
        pixels = pixels[idx]

    return pixels.astype(int).tolist()
