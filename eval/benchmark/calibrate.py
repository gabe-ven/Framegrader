"""Fit the overall composition score to human ratings (CADB).

Replaces the hand-weighted average with a ridge regression from the same
composition features (plus, optionally, the learned aesthetic score) onto
CADB's mean composition rating:

- fitted on CADB's *train* split only; the regularisation strength is chosen
  by 5-fold cross-validation on that same train split;
- evaluated exactly once on CADB's held-out *test* split;
- written to backend/app/services/scoring/calibration.json, which is what the
  app loads. Every number reported for it comes from the test split.

Ridge rather than anything fancier on purpose: ~15 features and 1,000 labels
is small data, the coefficients stay inspectable (they say which composition
cues human raters actually reward), and inference is a dot product with no new
runtime dependency.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.services.scoring.composition_score import features as score_features  # noqa: E402

CALIBRATION_OUT = REPO / "backend" / "app" / "services" / "scoring" / "calibration.json"
ALPHAS = (0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0)
FOLDS = 5


def _matrix(rows: list[dict[str, float]], names: list[str]) -> np.ndarray:
    return np.array([[r[n] for n in names] for r in rows], dtype=float)


def _fit(X: np.ndarray, y: np.ndarray, alpha: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    mean, scale = X.mean(0), X.std(0)
    scale[scale == 0] = 1.0
    Z = (X - mean) / scale
    intercept = float(y.mean())
    coef = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - intercept))
    return coef, mean, scale, intercept


def _predict(X: np.ndarray, coef: np.ndarray, mean: np.ndarray, scale: np.ndarray, intercept: float) -> np.ndarray:
    return intercept + ((X - mean) / scale) @ coef


def _cv_alpha(X: np.ndarray, y: np.ndarray) -> tuple[float, dict[str, float]]:
    rng = np.random.default_rng(0)
    folds = np.array_split(rng.permutation(len(y)), FOLDS)
    scores = {}
    for alpha in ALPHAS:
        preds = np.empty_like(y)
        for k in range(FOLDS):
            test = folds[k]
            train = np.concatenate([folds[j] for j in range(FOLDS) if j != k])
            preds[test] = _predict(X[test], *_fit(X[train], y[train], alpha))
        scores[str(alpha)] = round(float(stats.spearmanr(preds, y).statistic), 4)
    best = max(ALPHAS, key=lambda a: scores[str(a)])
    return best, scores


def fit_model(
    name: str,
    train_rows: list[dict[str, float]],
    y_train: np.ndarray,
    feature_names: list[str],
) -> dict[str, Any]:
    X = _matrix(train_rows, feature_names)
    alpha, cv = _cv_alpha(X, y_train)
    coef, mean, scale, intercept = _fit(X, y_train, alpha)
    return {
        "name": name,
        "features": feature_names,
        "coef": [round(float(c), 6) for c in coef],
        "mean": [round(float(m), 6) for m in mean],
        "scale": [round(float(s), 6) for s in scale],
        "intercept": round(intercept, 6),
        "alpha": alpha,
        "cv_spearman_by_alpha": cv,
        "target_range": [1.0, 5.0],
    }


def predict(model: dict[str, Any], rows: list[dict[str, float]]) -> np.ndarray:
    X = _matrix(rows, model["features"])
    return _predict(X, np.array(model["coef"]), np.array(model["mean"]), np.array(model["scale"]), model["intercept"])


def build_rows(
    comp: dict[str, dict[str, Any]], aesthetic: dict[str, float] | None
) -> list[dict[str, float]]:
    return [
        score_features(comp[i], aesthetic[i] if aesthetic is not None else None)
        for i in comp
    ]


def write_calibration(models: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    payload = {
        "version": 1,
        "fitted": date.today().isoformat(),
        "fitted_on": "CADB train split (eval/benchmark/manifests/cadb.json)",
        **meta,
        # Ordered by preference: composition_score tries each in turn and uses
        # the first whose features are all available.
        "models": models,
    }
    CALIBRATION_OUT.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
