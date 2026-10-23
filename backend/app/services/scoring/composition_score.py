"""The overall composition score: heuristic baseline and calibrated model.

Two scorers, deliberately side by side:

- ``heuristic_score`` is the original hand-weighted average — a line-for-line
  port of buildCompositionProfile + overallScore from
  frontend/src/components/composition/compositionProfile.ts. It stays as the
  fallback and as the baseline the benchmark compares against.
- ``calibrated_score`` is a ridge regression from composition features (plus
  the learned aesthetic score, when available) onto human composition ratings.
  It is fitted by eval/benchmark on CADB's train split and evaluated on CADB's
  held-out test split; the fitted coefficients ship as calibration.json next to
  this file. The weights are learned, not chosen.

Both return 0-100. The calibrated model predicts CADB's 1-5 mean rating, which
is mapped linearly onto 0-100 so it reads on the same scale as everything else.
"""

from __future__ import annotations

import json
import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CALIBRATION_PATH = Path(__file__).with_name("calibration.json")

AXES = (
    "rule_of_thirds",
    "leading_lines",
    "symmetry",
    "negative_space",
    "horizon",
    "subject_placement",
    "edge_balance",
)


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def edge_balance(regions: dict[str, float]) -> float:
    values = [regions[k] for k in ("top", "bottom", "left", "right", "center")]
    mean = sum(values) / len(values)
    if mean <= 0:
        return 0.0
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    return _clamp01(1 - std / mean)


def profile(c: dict[str, Any]) -> dict[str, tuple[float, bool]]:
    """axis -> (value 0-100, applicable). Mirrors buildCompositionProfile."""
    rot, ll, sym = c["rule_of_thirds"], c["leading_lines"], c["symmetry"]
    ns, hz, sp = c["negative_space"], c["horizon"], c["subject_position"]
    horizon_measurable = bool(hz["horizon_detected"] and hz.get("tilt_reliable"))
    horizon = (
        max(0.0, 1 - min(abs(hz.get("tilt_angle") or 0.0) / 10, 1)) * 100
        if horizon_measurable
        else 0.0
    )
    return {
        "rule_of_thirds": (rot["score"] * 100, True),
        "leading_lines": (min(ll["line_count"] / 8, 1) * 100, bool(ll["has_leading_lines"])),
        "symmetry": (max(sym["vertical"], sym["horizontal"]) * 100, True),
        "negative_space": (ns["subject_excluded_ratio"] * 100, True),
        "horizon": (horizon, horizon_measurable),
        "subject_placement": (min(sp["offset_from_center"] / 0.25, 1) * 100, True),
        "edge_balance": (edge_balance(c["edge_density"]["regions"]) * 100, True),
    }


def heuristic_score(c: dict[str, Any]) -> float:
    """Mean of applicable axes — the original overallScore()."""
    axes = [v for v, applicable in profile(c).values() if applicable]
    return round(sum(axes) / len(axes)) if axes else 0.0


def features(c: dict[str, Any], aesthetic: float | None) -> dict[str, float]:
    """Named feature vector for the calibrated model.

    Non-applicable axes contribute 0 plus an indicator, so the model can learn
    that "no horizon" is not the same as "a badly tilted horizon".
    """
    out: dict[str, float] = {}
    for axis, (value, applicable) in profile(c).items():
        out[axis] = value / 100 if applicable else 0.0
        if axis in ("leading_lines", "horizon"):
            out[f"has_{axis}"] = 1.0 if applicable else 0.0
    out["edge_density"] = float(c["edge_density"]["edge_density"])
    out["negative_space_raw"] = float(c["negative_space"]["negative_space_ratio"])
    out["subject_has_box"] = 1.0 if c["subject_position"].get("bbox") else 0.0
    if aesthetic is not None:
        out["aesthetic"] = aesthetic / 100
    return out


@lru_cache
def load_calibration(path: str | None = None) -> dict[str, Any] | None:
    p = Path(path) if path else CALIBRATION_PATH
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("Composition calibration unreadable; using heuristic", exc_info=True)
        return None


def _predict(model: dict[str, Any], feats: dict[str, float]) -> float | None:
    names = model["features"]
    if any(name not in feats for name in names):
        return None
    z = [(feats[n] - m) / s for n, m, s in zip(names, model["mean"], model["scale"])]
    rating = model["intercept"] + sum(w * x for w, x in zip(model["coef"], z))
    lo, hi = model.get("target_range", [1.0, 5.0])
    return round(_clamp01((rating - lo) / (hi - lo)) * 100, 1)


def calibrated_score(
    c: dict[str, Any], aesthetic: float | None, calibration: dict[str, Any] | None = None
) -> tuple[float, str] | None:
    """(score, method) from the best calibrated model the inputs allow.

    Prefers the model that uses the aesthetic score; falls back to the
    geometry-only model when no aesthetic score is available (lite build
    without the model file). None when there is no calibration at all.
    """
    calibration = calibration or load_calibration()
    if not calibration:
        return None
    feats = features(c, aesthetic)
    for model in calibration["models"]:
        score = _predict(model, feats)
        if score is not None:
            return score, model["name"]
    return None


def composition_score(c: dict[str, Any], aesthetic: float | None) -> dict[str, Any]:
    """The score the API reports: calibrated when possible, heuristic otherwise."""
    calibrated = calibrated_score(c, aesthetic)
    if calibrated is not None:
        score, method = calibrated
        return {"score": score, "method": method, "heuristic": heuristic_score(c)}
    return {"score": heuristic_score(c), "method": "heuristic-mean", "heuristic": heuristic_score(c)}
