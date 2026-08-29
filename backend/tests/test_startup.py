"""Tests for startup wiring: threadpool sizing and model warm-up.

Both exist to keep the event loop free, so the regressions they guard against
are performance/concurrency ones that no other test would catch.
"""

from __future__ import annotations

import inspect
import os

import pytest

from app.main import _MAX_AUTO_CONCURRENCY, _resolve_analysis_concurrency, app
from app.services.composition.subject_localization import YOLOWorldSubjectLocator


# --- threadpool sizing -----------------------------------------------------


def test_explicit_concurrency_is_honoured() -> None:
    assert _resolve_analysis_concurrency(3) == 3
    assert _resolve_analysis_concurrency(32) == 32


def test_auto_concurrency_tracks_cpu_count_within_bounds() -> None:
    resolved = _resolve_analysis_concurrency(0)
    assert 2 <= resolved <= _MAX_AUTO_CONCURRENCY
    assert resolved == max(2, min(_MAX_AUTO_CONCURRENCY, os.cpu_count() or 4))


def test_auto_concurrency_never_drops_below_two() -> None:
    """A single-core box must still be able to overlap two requests, or one
    slow analysis serialises the whole service again."""
    assert _resolve_analysis_concurrency(0) >= 2


def test_health_endpoint_is_async() -> None:
    """/health must stay on the event loop.

    As a sync handler it would need a thread from the capped analysis pool and
    could queue behind in-flight analyses — the exact stall the sync-handler
    conversion was meant to remove, and the worst place to reintroduce it.
    """
    routes = [r for r in app.routes if getattr(r, "path", None) == "/health"]
    assert routes, "no /health route registered"
    assert inspect.iscoroutinefunction(routes[0].endpoint)


# --- predictor warm-up -----------------------------------------------------


class _FakeModel:
    """Stands in for a YOLO model; records how often predict() was called."""

    def __init__(self) -> None:
        self.calls = 0

    def predict(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.calls += 1
        return []


@pytest.fixture
def _reset_predictor_state():
    """_predictor_ready is class-level and process-wide — restore it."""
    previous = YOLOWorldSubjectLocator._predictor_ready
    YOLOWorldSubjectLocator._predictor_ready = False
    yield
    YOLOWorldSubjectLocator._predictor_ready = previous


def test_ensure_predictor_builds_once_then_short_circuits(
    _reset_predictor_state,
) -> None:
    model = _FakeModel()
    for _ in range(5):
        YOLOWorldSubjectLocator._ensure_predictor(model)
    assert model.calls == 1
    assert YOLOWorldSubjectLocator._predictor_ready is True


def test_ensure_predictor_survives_a_failing_model(_reset_predictor_state) -> None:
    """A warm-up that cannot run must not take the detector tier down; the
    real inference right after will surface any genuine problem."""

    class _Exploding:
        def predict(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("boom")

    YOLOWorldSubjectLocator._ensure_predictor(_Exploding())
    assert YOLOWorldSubjectLocator._predictor_ready is True


def test_warm_up_is_a_noop_when_the_model_cannot_load(monkeypatch) -> None:
    monkeypatch.setattr(YOLOWorldSubjectLocator, "_get_model", classmethod(lambda cls: None))
    YOLOWorldSubjectLocator.warm_up()  # must not raise
