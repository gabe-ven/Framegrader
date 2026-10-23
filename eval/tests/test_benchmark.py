"""Offline tests for the benchmark machinery — no network, no datasets."""

from __future__ import annotations

import io
import json
import math
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark import calibrate, fetch, metrics, tasks  # noqa: E402
from benchmark.remote_zip import RemoteZip  # noqa: E402


def test_box_iou() -> None:
    assert metrics.box_iou((0, 0, 1, 1), (0, 0, 1, 1)) == 1.0
    assert metrics.box_iou((0, 0, 0.5, 1), (0.5, 0, 1, 1)) == 0.0
    assert metrics.box_iou((0, 0, 1, 1), (0, 0, 0.5, 0.5)) == pytest.approx(0.25)
    assert metrics.box_iou(None, (0, 0, 1, 1)) == 0.0


def test_correlation_reports_ci_that_brackets_the_estimate() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=300)
    y = x + rng.normal(scale=1.0, size=300)
    r = metrics.correlation(x, y)
    assert 0.5 < r["spearman"] < 0.85
    lo, hi = r["spearman_ci95"]
    assert lo < r["spearman"] < hi


def test_constant_predictions_are_nan_not_a_crash() -> None:
    assert math.isnan(metrics.correlation([1, 1, 1, 1], [1, 2, 3, 4])["spearman"])


def test_precision_recall() -> None:
    pr = metrics.precision_recall(tp=8, fp=2, fn=8)
    assert pr["precision"] == 0.8 and pr["recall"] == 0.5


def test_ridge_recovers_a_linear_relationship_and_cv_picks_an_alpha() -> None:
    rng = np.random.default_rng(1)
    rows = [{"a": float(a), "b": float(b)} for a, b in rng.normal(size=(400, 2))]
    y = np.array([3 + 0.5 * r["a"] - 0.2 * r["b"] for r in rows]) + rng.normal(scale=0.05, size=400)
    model = calibrate.fit_model("t", rows, y, ["a", "b"])
    assert model["alpha"] in calibrate.ALPHAS
    pred = calibrate.predict(model, rows)
    assert np.corrcoef(pred, y)[0, 1] > 0.99


def test_sampling_is_deterministic_and_order_independent() -> None:
    ids = [f"img{i}" for i in range(1000)]
    a = fetch._sample(ids, 50, "x:test")
    b = fetch._sample(list(reversed(ids)), 50, "x:test")
    assert a == b and len(a) == 50
    assert fetch._sample(ids, 50, "y:test") != a  # salted per dataset/split


def test_manifest_reuses_ids_and_rejects_changed_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(fetch, "MANIFEST_DIR", tmp_path)
    m = fetch.Manifest("demo")
    ids = m.ids("test", ["a", "b", "c", "d"], 2)
    m.record("images/a.jpg", b"one")
    m.data["splits"]["test"] = ids
    m.save()

    again = fetch.Manifest("demo")
    assert again.ids("test", ["d", "c", "b", "a", "e"], 2) == ids  # not resampled
    again.record("images/a.jpg", b"one")  # unchanged: fine
    with pytest.raises(fetch.FetchError, match="upstream changed"):
        again.record("images/a.jpg", b"two")


def test_remote_zip_single_request_reader_matches_zipfile() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("stored.txt", b"hello" * 100, compress_type=zipfile.ZIP_STORED)
        zf.writestr("deflated.bin", bytes(range(256)) * 300, compress_type=zipfile.ZIP_DEFLATED)
    data = buf.getvalue()

    class FakeRemote:
        def fetch(self, start: int, length: int) -> bytes:
            return data[start : start + length]

    zf = RemoteZip(io.BytesIO(data))
    zf.remote = FakeRemote()  # type: ignore[assignment]
    assert zf.read("stored.txt") == b"hello" * 100
    assert zf.read("deflated.bin") == bytes(range(256)) * 300


def test_hlw_ground_truth_conversion() -> None:
    # A level horizon 50px above the centre of a 400x300 image (centre, y up).
    row = {"left_x": "-200", "left_y": "50", "right_x": "200", "right_y": "50"}
    assert tasks._hlw_gt(row, 400, 300, "center-up") == (100.0, 100.0)
    assert tasks._hlw_gt(row, 400, 300, "center-down") == (200.0, 200.0)
    tilted = {"left_x": "0", "left_y": "100", "right_x": "400", "right_y": "140"}
    left, right = tasks._hlw_gt(tilted, 400, 300, "topleft")
    assert (left, right) == (100.0, 140.0)


def test_results_markdown_renders_with_partial_results(tmp_path, monkeypatch) -> None:
    from benchmark import run

    monkeypatch.setattr(run, "RESULTS_DIR", tmp_path)
    run.write_markdown({"env": {}, "horizon": {"status": "skipped"}})
    text = (tmp_path / "RESULTS.md").read_text(encoding="utf-8")
    assert "Not run" in text and "HLW" in text
    json.dumps(text)
