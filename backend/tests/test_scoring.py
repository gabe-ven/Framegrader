"""Composition score (heuristic + calibrated) and the optional aesthetic model."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from app.services.scoring import aesthetic, composition_score as cs


def _composition(**overrides) -> dict:
    # Same fixture as frontend/src/components/composition/compositionProfile.test.ts,
    # so the Python port and the TypeScript original are checked against the
    # same expected numbers.
    base = {
        "rule_of_thirds": {"score": 0.8},
        "leading_lines": {"has_leading_lines": False, "line_count": 0},
        "horizon": {"horizon_detected": True, "tilt_angle": 2, "tilt_reliable": True},
        "symmetry": {"vertical": 0.4, "horizontal": 0.3},
        "subject_position": {"offset_from_center": 0.25, "bbox": None},
        "edge_density": {
            "edge_density": 0.1,
            "regions": {"top": 0.1, "bottom": 0.1, "left": 0.1, "right": 0.1, "center": 0.1},
        },
        "negative_space": {"negative_space_ratio": 0.5, "subject_excluded_ratio": 0.4},
    }
    base.update(overrides)
    return base


def test_profile_matches_the_frontend_port() -> None:
    p = cs.profile(_composition())
    assert p["rule_of_thirds"] == (80.0, True)
    assert p["negative_space"] == (40.0, True)
    assert p["symmetry"] == (40.0, True)
    assert p["horizon"] == pytest.approx((80.0, True))
    assert p["subject_placement"] == (100.0, True)
    assert p["edge_balance"] == (100.0, True)
    assert p["leading_lines"][1] is False


def test_unreliable_tilt_is_not_a_free_100() -> None:
    c = _composition(horizon={"horizon_detected": True, "tilt_angle": 0, "tilt_reliable": False})
    assert cs.profile(c)["horizon"] == (0.0, False)


def test_heuristic_score_is_the_mean_of_applicable_axes() -> None:
    # (80 + 40 + 40 + 80 + 100 + 100) / 6
    assert cs.heuristic_score(_composition()) == 73


def _calibration(with_aesthetic: bool) -> dict:
    geo_names = sorted(cs.features(_composition(), None))
    geo = {
        "name": "geo",
        "features": geo_names,
        "coef": [0.0] * len(geo_names),
        "mean": [0.0] * len(geo_names),
        "scale": [1.0] * len(geo_names),
        "intercept": 3.0,  # mid-scale rating -> 50
        "target_range": [1.0, 5.0],
    }
    models = [geo]
    if with_aesthetic:
        names = sorted(cs.features(_composition(), 50.0))
        coef = [1.0 if n == "aesthetic" else 0.0 for n in names]
        models.insert(0, {**geo, "name": "geo+aes", "features": names, "coef": coef,
                          "mean": [0.0] * len(names), "scale": [1.0] * len(names)})
    return {"models": models}


def test_calibrated_score_maps_the_rating_scale_onto_0_100() -> None:
    assert cs.calibrated_score(_composition(), None, _calibration(False)) == (50.0, "geo")


def test_calibrated_score_prefers_the_aesthetic_model_and_falls_back_without_it() -> None:
    cal = _calibration(True)
    score, method = cs.calibrated_score(_composition(), 100.0, cal)
    assert method == "geo+aes" and score == pytest.approx(75.0)  # 3 + 1.0 -> rating 4
    assert cs.calibrated_score(_composition(), None, cal) == (50.0, "geo")


def test_composition_score_uses_heuristic_without_any_calibration(monkeypatch) -> None:
    monkeypatch.setattr(cs, "load_calibration", lambda path=None: None)
    out = cs.composition_score(_composition(), None)
    assert out == {"score": 73, "method": "heuristic-mean", "heuristic": 73}


def test_shipped_calibration_is_well_formed_if_present() -> None:
    cal = cs.load_calibration()
    if cal is None:
        pytest.skip("no calibration.json shipped")
    for model in cal["models"]:
        n = len(model["features"])
        assert len(model["coef"]) == len(model["mean"]) == len(model["scale"]) == n
        assert all(s > 0 for s in model["scale"])
    # The geometry-only model must exist, so scoring never depends on the
    # optional aesthetic model being installed.
    assert any("aesthetic" not in m["features"] for m in cal["models"])
    score = cs.composition_score(_composition(), None)["score"]
    assert 0 <= score <= 100


def test_aesthetic_scorer_is_off_when_the_model_file_is_missing(monkeypatch, tmp_path) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("AESTHETIC_MODEL_PATH", str(tmp_path / "nope.onnx"))
    get_settings.cache_clear()
    aesthetic.reset_for_tests()
    assert aesthetic.score_image(Image.new("RGB", (64, 64))) is None
    aesthetic.reset_for_tests()


def test_aesthetic_output_readers() -> None:
    import numpy as np

    dist = {"output": "distribution", "raw_range": [1.0, 10.0]}
    probs = np.zeros(10)
    probs[9] = 1.0  # all mass on bin 10
    assert aesthetic._raw_score(probs, dist) == 10.0
    assert aesthetic.to_100(10.0, dist) == 100.0
    assert aesthetic.to_100(5.5, dist) == 50.0
    scalar = {"output": "scalar", "raw_range": [0.0, 1.0]}
    assert aesthetic._raw_score(np.array([[0.25]]), scalar) == 0.25
    assert aesthetic.to_100(2.0, scalar) == 100.0  # clamped


def test_api_reports_scores_and_their_method() -> None:
    import io

    from fastapi.testclient import TestClient

    from app.main import app

    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (120, 130, 140)).save(buf, format="PNG")
    res = TestClient(app).post("/api/analyze", files={"file": ("t.png", buf.getvalue(), "image/png")})
    scores = res.json()["scores"]
    assert 0 <= scores["composition"]["score"] <= 100
    assert scores["composition"]["method"]
    assert scores["composition"]["heuristic"] is not None
    json.dumps(scores)
