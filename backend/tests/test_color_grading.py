"""Tests for the color grading AI layer (mocked client, no network)."""

from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services.ai import color_grading
from app.services.ai.color_grading import build_context_summary, generate_color_grade

client = TestClient(app)


# --- Fakes mirroring the anthropic SDK surface ----------------------------


class _FakeMessages:
    def __init__(self, text: str) -> None:
        self._text = text
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):  # noqa: ANN003 - mirrors anthropic SDK signature
        self.last_kwargs = kwargs

        class _Block:
            def __init__(self, text: str) -> None:
                self.text = text

        class _Response:
            def __init__(self, text: str) -> None:
                self.content = [_Block(text)]

        return _Response(self._text)


class _FakeClient:
    def __init__(self, text: str) -> None:
        self.messages = _FakeMessages(text)


class _RaisingClient:
    class _Messages:
        def create(self, **kwargs):  # noqa: ANN003
            raise RuntimeError("simulated API failure")

    def __init__(self) -> None:
        self.messages = self._Messages()


def _image() -> Image.Image:
    return Image.new("RGB", (64, 48), (100, 120, 140))


_VALID_JSON = json.dumps(
    {
        "adjustments": {
            "exposure": 0.3,
            "contrast": 10,
            "highlights": -20,
            "shadows": 15,
            "whites": 0,
            "blacks": -5,
            "temperature": 8,
            "tint": 0,
            "saturation": 5,
            "vibrance": 10,
            "sharpness": 20,
        },
        "reasoning": "Lifts the shadows and warms the highlights for a filmic look.",
        "style": "cinematic",
    }
)


# --- generate_color_grade ---------------------------------------------------


def test_generate_color_grade_parses_valid_json() -> None:
    result = generate_color_grade(_image(), client=_FakeClient(_VALID_JSON))
    assert result["available"] is True
    assert result["adjustments"]["exposure"] == 0.3
    assert result["style"] == "cinematic"


def test_generate_color_grade_extracts_json_from_surrounding_prose() -> None:
    noisy = "Here is your grade:\n" + _VALID_JSON + "\nEnjoy!"
    result = generate_color_grade(_image(), client=_FakeClient(noisy))
    assert result["available"] is True
    assert result["adjustments"]["sharpness"] == 20


def test_generate_color_grade_handles_unparseable_response() -> None:
    result = generate_color_grade(_image(), client=_FakeClient("not json at all"))
    assert result["available"] is False
    assert "unreadable" in result["reason"].lower()


def test_generate_color_grade_recovers_from_invalid_backslash_escape() -> None:
    # Real responses have escaped an apostrophe as \', which is valid in
    # Python/JS string literals but not legal JSON and trips json.loads.
    broken = _VALID_JSON.replace(
        "Lifts the shadows and warms the highlights for a filmic look.",
        "Lifts the shadows for a photographer\\'s filmic look.",
    )
    result = generate_color_grade(_image(), client=_FakeClient(broken))
    assert result["available"] is True
    assert result["reasoning"] == "Lifts the shadows for a photographer's filmic look."


def test_generate_color_grade_handles_api_failure() -> None:
    result = generate_color_grade(_image(), client=_RaisingClient())
    assert result["available"] is False


def test_generate_color_grade_unavailable_without_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = generate_color_grade(_image())  # no client, no key
    assert result["available"] is False
    assert "not configured" in result["reason"].lower()


# --- build_context_summary -------------------------------------------------


def test_context_summary_includes_vision_and_exif_when_present() -> None:
    context = {
        "vision": {
            "brightness": 120.0,
            "contrast": 40.0,
            "dominant_colors": [{"hex": "#112233"}],
            "dynamic_range": {"stops": 6.5, "range": 200},
        },
        "exif": {"has_exif": True, "aperture": "f/8", "iso": 200, "shutter_speed": "1/500"},
    }
    summary = build_context_summary(context)
    assert "brightness=120.0" in summary
    assert "#112233" in summary
    assert "aperture=f/8" in summary
    assert "ISO=200" in summary


def test_context_summary_includes_scene_summary_when_present() -> None:
    summary = build_context_summary({"scene_summary": "A quiet mountain lake at dawn."})
    assert "A quiet mountain lake at dawn." in summary


def test_context_summary_notes_missing_exif() -> None:
    summary = build_context_summary({"exif": {"has_exif": False}})
    assert "none present" in summary.lower()


def test_context_summary_handles_empty_context() -> None:
    assert "no pre-computed" in build_context_summary(None).lower()


# --- endpoint --------------------------------------------------------------


def _png_bytes(size: tuple[int, int] = (200, 150)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 120, 120)).save(buf, format="PNG")
    return buf.getvalue()


def test_color_grade_endpoint_returns_unavailable_without_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    files = {"file": ("test.png", _png_bytes(), "image/png")}
    response = client.post("/api/color-grade", files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["adjustments"]["exposure"] == 0.0


def test_color_grade_endpoint_uses_mocked_service(monkeypatch) -> None:
    monkeypatch.setattr(
        color_grading,
        "generate_color_grade",
        lambda image, context=None: {**json.loads(_VALID_JSON), "available": True},
    )
    files = {"file": ("test.png", _png_bytes(), "image/png")}
    response = client.post("/api/color-grade", files=files, data={"context": "{}"})
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["style"] == "cinematic"
    assert body["adjustments"]["shadows"] == 15


def test_color_grade_endpoint_rejects_non_image() -> None:
    files = {"file": ("notes.txt", b"hello world", "text/plain")}
    response = client.post("/api/color-grade", files=files)
    assert response.status_code == 422


def test_color_grade_endpoint_tolerates_malformed_context(monkeypatch) -> None:
    captured: dict = {}

    def _fake(image, context=None):
        captured["context"] = context
        return {"available": False, "reason": "stub"}

    monkeypatch.setattr(color_grading, "generate_color_grade", _fake)
    files = {"file": ("test.png", _png_bytes(), "image/png")}
    response = client.post(
        "/api/color-grade", files=files, data={"context": "{not valid json"}
    )
    assert response.status_code == 200
    assert captured["context"] is None
