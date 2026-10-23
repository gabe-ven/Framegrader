"""Metrics, each with a bootstrap 95% confidence interval.

At n=500 a correlation of 0.40 could plausibly be anywhere from ~0.32 to
~0.47; reporting the interval keeps a 0.02 difference between two models from
being read as a ranking.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np
from scipy import stats

_BOOTSTRAP = 1000
_RNG_SEED = 7


def _bootstrap(values: Sequence[Sequence[float]], fn: Callable[..., float]) -> tuple[float, float]:
    arrays = [np.asarray(v, dtype=float) for v in values]
    n = len(arrays[0])
    if n < 3:
        return (math.nan, math.nan)
    rng = np.random.default_rng(_RNG_SEED)
    samples = []
    for _ in range(_BOOTSTRAP):
        idx = rng.integers(0, n, n)
        value = fn(*(a[idx] for a in arrays))
        if not math.isnan(value):
            samples.append(value)
    if not samples:
        return (math.nan, math.nan)
    lo, hi = np.percentile(samples, [2.5, 97.5])
    return (round(float(lo), 4), round(float(hi), 4))


def _r(value: float) -> float:
    return round(float(value), 4)


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    if np.ptp(a) == 0 or np.ptp(b) == 0:
        return math.nan
    return float(stats.spearmanr(a, b).statistic)


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    if np.ptp(a) == 0 or np.ptp(b) == 0:
        return math.nan
    return float(stats.pearsonr(a, b).statistic)


def correlation(pred: Sequence[float], truth: Sequence[float]) -> dict:
    """SRCC and PLCC with CIs. PLCC is on raw scores (no logistic fit), which
    is stricter than the IQA-literature convention and says so."""
    p, t = np.asarray(pred, float), np.asarray(truth, float)
    return {
        "n": int(len(p)),
        "spearman": _r(_spearman(p, t)),
        "spearman_ci95": _bootstrap([p, t], _spearman),
        "pearson": _r(_pearson(p, t)),
        "pearson_ci95": _bootstrap([p, t], _pearson),
    }


def mean_ci(values: Sequence[float]) -> dict:
    v = np.asarray(values, float)
    if len(v) == 0:
        return {"n": 0, "mean": None, "ci95": None}
    return {
        "n": int(len(v)),
        "mean": _r(v.mean()),
        "ci95": _bootstrap([v], lambda x: float(x.mean())),
    }


def precision_recall(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else math.nan
    recall = tp / (tp + fn) if tp + fn else math.nan
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else math.nan
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": _r(precision), "recall": _r(recall), "f1": _r(f1),
    }


def box_iou(a: Sequence[float] | None, b: Sequence[float] | None) -> float:
    """IoU of two normalized (x0, y0, x1, y1) boxes; 0 when either is missing."""
    if a is None or b is None:
        return 0.0
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0
