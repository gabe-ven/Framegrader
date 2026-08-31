"""Per-channel RGB histogram."""

from __future__ import annotations

import numpy as np

from app.services.vision._utils import to_grayscale, to_rgb


def compute_histogram(image: np.ndarray, bins: int = 256) -> dict:
    """Return bin counts for each channel plus true luminance:
    {"bins", "r", "g", "b", "luminance"}.

    Luminance is histogrammed from each pixel's own weighted value (same
    Rec. 601 weights `to_grayscale` uses elsewhere in this pipeline), not
    recombined from the three per-channel histograms after the fact — R, G,
    and B are correlated per pixel, so summing independent marginal
    distributions would drift from the real luminance distribution.
    """
    rgb = to_rgb(image)
    out: dict = {"bins": bins}
    for index, channel in enumerate(("r", "g", "b")):
        counts, _ = np.histogram(rgb[:, :, index], bins=bins, range=(0, 255))
        out[channel] = counts.astype(int).tolist()
    luminance_counts, _ = np.histogram(to_grayscale(rgb), bins=bins, range=(0, 255))
    out["luminance"] = luminance_counts.astype(int).tolist()
    return out
