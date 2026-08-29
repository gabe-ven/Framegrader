"""Tests for per-IP rate limiting on the endpoints that can spend money.

These are the only tests that run with the limiter armed (see the
`rate_limited` fixture in conftest.py). The AI service layer is stubbed
throughout so tripping the limit costs no network calls.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import get_settings
from app.main import app
from app.services.ai import color_grading, photo_critique

client = TestClient(app)


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (120, 120, 120)).save(buffer, format="PNG")
    return buffer.getvalue()


def _files() -> dict:
    return {"file": ("test.png", _png_bytes(), "image/png")}


@pytest.fixture
def _stub_ai(monkeypatch) -> None:
    """Make both AI endpoints return instantly without touching the network."""
    monkeypatch.setattr(
        photo_critique,
        "generate_critique",
        lambda image, context=None: {"available": False, "reason": "stub"},
    )
    monkeypatch.setattr(
        color_grading,
        "generate_color_grade",
        lambda image, context=None: {"available": False, "reason": "stub"},
    )


def _limit_count(rate: str) -> int:
    """"10/hour" -> 10."""
    return int(rate.split("/")[0])


# --- the limit actually engages -------------------------------------------


@pytest.mark.parametrize("endpoint", ["/api/ai-analysis", "/api/color-grade"])
def test_ai_endpoint_throttles_after_configured_limit(
    endpoint: str, rate_limited, _stub_ai
) -> None:
    allowed = _limit_count(get_settings().ai_rate_limit)

    for i in range(allowed):
        assert client.post(endpoint, files=_files()).status_code == 200, (
            f"request {i + 1} of {allowed} should have been allowed"
        )

    assert client.post(endpoint, files=_files()).status_code == 429


def test_analyze_has_its_own_looser_limit(rate_limited, _stub_ai) -> None:
    """/analyze is limited too (its VLM tier costs money), but far higher — and
    on its own bucket, so a user who exhausts the AI endpoints can still get
    measurements.

    Deliberately does NOT loop /analyze up to its own limit: each call runs the
    real CV pipeline including a YOLO-World load, which took ~37s for one test
    and dominated the whole suite. Exhausting the cheap (stubbed) AI bucket and
    then making a single /analyze call proves the same separation.
    """
    settings = get_settings()
    assert _limit_count(settings.analyze_rate_limit) > _limit_count(
        settings.ai_rate_limit
    )

    for _ in range(_limit_count(settings.ai_rate_limit)):
        client.post("/api/ai-analysis", files=_files())
    assert client.post("/api/ai-analysis", files=_files()).status_code == 429

    assert client.post("/api/analyze", files=_files()).status_code == 200


# --- the 429 is usable by the client --------------------------------------


def test_throttled_response_uses_the_detail_key_the_frontend_reads(
    rate_limited, _stub_ai
) -> None:
    """slowapi's default handler returns {"error": ...}; the frontend reads
    `detail`, so a default-handler regression would show the user a bare
    "Request failed (429)." instead of the reason."""
    for _ in range(_limit_count(get_settings().ai_rate_limit)):
        client.post("/api/color-grade", files=_files())

    response = client.post("/api/color-grade", files=_files())
    assert response.status_code == 429
    body = response.json()
    assert "detail" in body, f"expected a 'detail' key, got {sorted(body)}"
    assert "per IP address" in body["detail"]
    assert get_settings().ai_rate_limit.split("/")[0] in body["detail"]


def test_throttled_response_carries_retry_after(rate_limited, _stub_ai) -> None:
    for _ in range(_limit_count(get_settings().ai_rate_limit)):
        client.post("/api/color-grade", files=_files())

    response = client.post("/api/color-grade", files=_files())
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0
    assert response.headers["x-ratelimit-remaining"] == "0"


# --- scoping ---------------------------------------------------------------


def test_buckets_are_per_endpoint(rate_limited, _stub_ai) -> None:
    """Exhausting one AI endpoint must not spend the other's budget."""
    for _ in range(_limit_count(get_settings().ai_rate_limit)):
        client.post("/api/color-grade", files=_files())
    assert client.post("/api/color-grade", files=_files()).status_code == 429

    assert client.post("/api/ai-analysis", files=_files()).status_code == 200


def test_health_is_never_rate_limited(rate_limited) -> None:
    for _ in range(50):
        assert client.get("/health").status_code == 200


# --- the fixture itself ----------------------------------------------------


def test_limiter_is_disabled_by_default_in_tests(_stub_ai) -> None:
    """Guards the conftest autouse fixture: without it the rest of the suite
    would start failing once it crossed the limit."""
    limit = _limit_count(get_settings().ai_rate_limit)
    for _ in range(limit + 5):
        assert client.post("/api/color-grade", files=_files()).status_code == 200
