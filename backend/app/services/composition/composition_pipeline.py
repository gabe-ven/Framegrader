"""Composition analysis orchestrator.

Converts the image to a grayscale array once, then runs each independent
analyzer over it. No AI — purely geometric/structural measurements.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from app.services.composition.edge_density import compute_edge_density
from app.services.composition.horizon_detection import detect_horizon
from app.services.composition.leading_lines import detect_leading_lines
from app.services.composition.negative_space import estimate_negative_space
from app.services.composition.rule_of_thirds import analyze_rule_of_thirds
from app.services.composition.subject_localization import locate_subject
from app.services.composition.subject_position import estimate_subject_position
from app.services.composition.symmetry import analyze_symmetry

# All composition metrics work on normalized coordinates, so pixel resolution
# doesn't affect accuracy. Cap at this edge length to keep CV operations fast
# on high-resolution camera files (e.g. 26 MP gives ~4× speedup vs full-res).
_ANALYSIS_MAX_EDGE = 1920


def run_composition_analysis(image: Image.Image) -> dict:
    # Downsample to analysis resolution if needed. Track original dimensions
    # so pixel-space outputs (leading lines) can be scaled back before returning.
    orig_w, orig_h = image.size
    if max(orig_w, orig_h) > _ANALYSIS_MAX_EDGE:
        scale = _ANALYSIS_MAX_EDGE / max(orig_w, orig_h)
        image = image.resize(
            (max(1, int(orig_w * scale)), max(1, int(orig_h * scale))),
            Image.LANCZOS,
        )

    rgb = np.asarray(image.convert("RGB"))
    gray = np.asarray(image.convert("L"))
    analysis_h, analysis_w = gray.shape[:2]

    # Locate the subject once and share it across the metrics that depend on
    # "where the subject is" (rule of thirds, subject position, negative space).
    subject = locate_subject(rgb)

    result = {
        "rule_of_thirds": analyze_rule_of_thirds(gray, subject),
        "leading_lines": detect_leading_lines(gray, subject),
        "horizon": detect_horizon(gray),
        "symmetry": analyze_symmetry(gray),
        "subject_position": estimate_subject_position(gray, subject),
        "edge_density": compute_edge_density(gray),
        "negative_space": estimate_negative_space(gray, subject),
    }

    # Leading-line coordinates come out in analysis-resolution pixel space.
    # Normalize them to 0-1, matching every other spatial field in this API
    # (centroid, bbox, horizon_y) and making them independent of whatever
    # resolution the analysis or the client's preview happens to run at.
    #
    # They used to be scaled to the ORIGINAL image size instead, on the
    # assumption the frontend SVG viewBox matched. It doesn't: the client
    # renders a preview capped at 1600px, so a 4160px-wide photo produced
    # coordinates roughly 2.6x outside the viewBox and the overlay drew off
    # canvas. That went unnoticed only because the detector never fired.
    if analysis_w > 0 and analysis_h > 0:
        for line in result["leading_lines"]["lines"]:
            line["x1"] = round(line["x1"] / analysis_w, 4)
            line["x2"] = round(line["x2"] / analysis_w, 4)
            line["y1"] = round(line["y1"] / analysis_h, 4)
            line["y2"] = round(line["y2"] / analysis_h, 4)

    return result
