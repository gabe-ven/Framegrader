"""Vision analysis orchestrator.

Converts a PIL image to a single RGB array once, then runs each independent
metric over it and assembles one structured result. No AI, no composition
detection — just objective, reproducible measurements.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from app.services.vision.brightness import compute_brightness
from app.services.vision.colors import color_samples, dominant_colors
from app.services.vision.contrast import compute_contrast
from app.services.vision.dynamic_range import compute_dynamic_range
from app.services.vision.histogram import compute_histogram
from app.services.vision.sharpness import compute_sharpness


# Cap the long edge for all pixel-level metrics. All outputs are normalized
# or scale-independent (histograms, brightness, sharpness, k-means colors),
# so full resolution adds no accuracy — only runtime cost on large camera files.
_VISION_MAX_EDGE = 1920


def run_vision_analysis(
    image: Image.Image, reported_dimensions: tuple[int, int] | None = None
) -> dict:
    """Run the objective image-quality metrics.

    ``reported_dimensions`` overrides what the ``dimensions``/``orientation``
    fields describe. The caller may hand us an already-downscaled image to cap
    memory (see image_io.downscale_to_megapixels), and those fields are supposed
    to describe the photograph the user uploaded, not our working copy.
    """
    # Preserve original dimensions for the reported metadata, then downsample.
    orig_w, orig_h = reported_dimensions or image.size
    work_w, work_h = image.size
    if max(work_w, work_h) > _VISION_MAX_EDGE:
        scale = _VISION_MAX_EDGE / max(work_w, work_h)
        image = image.resize(
            (max(1, int(work_w * scale)), max(1, int(work_h * scale))),
            Image.LANCZOS,
        )

    rgb = np.asarray(image.convert("RGB"))

    return {
        "brightness": compute_brightness(rgb),
        "contrast": compute_contrast(rgb),
        "sharpness": compute_sharpness(rgb),
        "dominant_colors": dominant_colors(rgb),
        "color_samples": color_samples(rgb),
        "histogram": compute_histogram(rgb),
        "dynamic_range": compute_dynamic_range(rgb),
        "dimensions": {
            "width": orig_w,
            "height": orig_h,
            "aspect_ratio": round(orig_w / orig_h, 2) if orig_h else 0.0,
        },
        "orientation": _orientation(orig_w, orig_h),
    }


def _orientation(width: int, height: int) -> str:
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"
