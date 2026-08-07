"""Tests for the Phase 3 AI analysis layer (mocked client, no network)."""

from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services.ai import photo_critique
from app.services.ai.photo_critique import build_context_summary, generate_critique

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
        "scene": {"summary": "A calm seascape at dusk.", "setting": "outdoor coastal", "tags": ["seascape", "dusk"]},
        "subject": {"primary": "lone pier", "description": "A pier leading to the horizon."},
        "lighting": {"summary": "Soft warm light.", "direction": "side", "quality": "soft", "time_of_day": "golden hour"},
        "camera_settings": {"aperture": "f/11", "shutter_speed": "1/125", "iso": "200", "focal_length": "24mm", "from_exif": True, "reasoning": "Deep DOF landscape."},
        "composition_critique": {"strengths": ["Strong leading line"], "improvements": ["Level the horizon"], "overall": "A solid minimalist seascape."},
        "recreation_guide": ["Shoot at golden hour", "Use a tripod", "Stop down to f/11"],
    }
)


# --- generate_critique -----------------------------------------------------


def test_generate_critique_parses_valid_json() -> None:
    result = generate_critique(_image(), client=_FakeClient(_VALID_JSON))
    assert result["available"] is True
    assert result["scene"]["setting"] == "outdoor coastal"
    assert result["camera_settings"]["from_exif"] is True
    assert len(result["recreation_guide"]) == 3


def test_generate_critique_extracts_json_from_surrounding_prose() -> None:
    noisy = "Here is your analysis:\n" + _VALID_JSON + "\nHope that helps!"
    result = generate_critique(_image(), client=_FakeClient(noisy))
    assert result["available"] is True
    assert result["subject"]["primary"] == "lone pier"


def test_generate_critique_handles_unparseable_response() -> None:
    result = generate_critique(_image(), client=_FakeClient("not json at all"))
    assert result["available"] is False
    assert "unreadable" in result["reason"].lower()


def test_generate_critique_recovers_from_invalid_backslash_escape() -> None:
    # \' is valid in Python/JS string literals but illegal JSON and trips
    # json.loads — guard against a model emitting it for an apostrophe.
    broken = _VALID_JSON.replace("A solid minimalist seascape.", "A photographer\\'s dream shot.")
    result = generate_critique(_image(), client=_FakeClient(broken))
    assert result["available"] is True
    assert result["composition_critique"]["overall"] == "A photographer's dream shot."


def test_generate_critique_recovers_from_misnested_overall() -> None:
    # Observed in production: the model closed composition_critique's `{`
    # one brace early, then emitted "overall" as a stray top-level sibling
    # followed by an extra `}` that terminated the whole object prematurely
    # — e.g. ...,"improvements":[...]},"overall":"x"},"recreation_guide":...
    # json.loads reports "Extra data" right after that stray brace. The fix
    # drops it, then reattaches "overall" into composition_critique so the
    # verdict still renders instead of the whole critique going unavailable.
    broken = (
        '{"scene":{"summary":"s","setting":"t","tags":[]},'
        '"subject":{"primary":"p","description":"d"},'
        '"lighting":{"summary":"l","direction":"side","quality":"soft","time_of_day":"day"},'
        '"camera_settings":{"aperture":"f/8","shutter_speed":"1/100","iso":"100","focal_length":"35mm","from_exif":true,"reasoning":"r"},'
        '"composition_critique":{"strengths":["s1"],"improvements":["i1"]},'
        '"overall":"A solid minimalist seascape."},'
        '"recreation_guide":["step1","step2"]}'
    )
    result = generate_critique(_image(), client=_FakeClient(broken))
    assert result["available"] is True
    assert result["composition_critique"]["overall"] == "A solid minimalist seascape."
    assert result["recreation_guide"] == ["step1", "step2"]
    assert "overall" not in result


def test_generate_critique_handles_api_failure() -> None:
    result = generate_critique(_image(), client=_RaisingClient())
    assert result["available"] is False


def test_generate_critique_unavailable_without_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = generate_critique(_image())  # no client, no key
    assert result["available"] is False
    assert "not configured" in result["reason"].lower()


# --- build_context_summary -------------------------------------------------


def test_context_summary_includes_exif_when_present() -> None:
    context = {
        "exif": {"has_exif": True, "make": "FUJIFILM", "model": "X-T5", "iso": 200,
                  "aperture": "f/8", "shutter_speed": "1/500", "focal_length": "35mm"},
    }
    summary = build_context_summary(context)
    assert "FUJIFILM" in summary and "X-T5" in summary
    assert "ISO=200" in summary


def test_context_summary_notes_missing_exif() -> None:
    summary = build_context_summary({"exif": {"has_exif": False}})
    assert "none present" in summary.lower()


def test_context_summary_handles_empty_context() -> None:
    assert "no pre-computed" in build_context_summary(None).lower()


def test_context_summary_includes_composition_geometry() -> None:
    context = {
        "composition": {
            "leading_lines": {"has_leading_lines": True, "dominant_angle": 30.0},
            "horizon": {"horizon_detected": True, "is_level": False, "tilt_angle": 3.2},
        }
    }
    summary = build_context_summary(context)
    assert "leading_lines" in summary
    assert "horizon detected" in summary


# --- endpoint --------------------------------------------------------------


def _png_bytes(size: tuple[int, int] = (200, 150)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 120, 120)).save(buf, format="PNG")
    return buf.getvalue()


def test_ai_endpoint_returns_unavailable_without_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    files = {"file": ("test.png", _png_bytes(), "image/png")}
    response = client.post("/api/ai-analysis", files=files)
    assert response.status_code == 200
    ai = response.json()["ai"]
    assert ai["available"] is False


def test_ai_endpoint_uses_mocked_critique(monkeypatch) -> None:
    monkeypatch.setattr(
        photo_critique,
        "generate_critique",
        lambda image, context=None: {**json.loads(_VALID_JSON), "available": True},
    )
    files = {"file": ("test.png", _png_bytes(), "image/png")}
    response = client.post("/api/ai-analysis", files=files, data={"context": "{}"})
    assert response.status_code == 200
    ai = response.json()["ai"]
    assert ai["available"] is True
    assert ai["scene"]["summary"].startswith("A calm seascape")


def test_ai_endpoint_rejects_non_image() -> None:
    files = {"file": ("notes.txt", b"hello world", "text/plain")}
    response = client.post("/api/ai-analysis", files=files)
    assert response.status_code == 422


def test_ai_endpoint_tolerates_malformed_context(monkeypatch) -> None:
    captured: dict = {}

    def _fake(image, context=None):
        captured["context"] = context
        return {"available": False, "reason": "stub"}

    monkeypatch.setattr(photo_critique, "generate_critique", _fake)
    files = {"file": ("test.png", _png_bytes(), "image/png")}
    response = client.post(
        "/api/ai-analysis", files=files, data={"context": "{not valid json"}
    )
    assert response.status_code == 200
    assert captured["context"] is None
