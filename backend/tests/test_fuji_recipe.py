"""Tests for real Fujifilm recipe extraction (mocked exiftool, no subprocess)."""

from __future__ import annotations

import io
import shutil

import pytest
from PIL import Image

from app.services.exif import fuji_recipe_service
from app.services.exif.fuji_recipe_service import extract_fuji_recipe


def _fake_runner(tags: dict | None):
    calls: list[bytes] = []

    def runner(image_bytes: bytes):
        calls.append(image_bytes)
        return tags

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def test_non_fuji_make_skips_runner_entirely() -> None:
    """A Canon/Nikon/etc. upload never even shells out to exiftool."""
    runner = _fake_runner({"FilmMode": "Classic Chrome"})

    result = extract_fuji_recipe(b"bytes", "Canon", runner=runner)

    assert result == {
        "applicable": False,
        "film_simulation": None,
        "settings": None,
    }
    assert runner.calls == []


def test_missing_make_is_not_applicable() -> None:
    runner = _fake_runner({"FilmMode": "Classic Chrome"})
    result = extract_fuji_recipe(b"bytes", None, runner=runner)
    assert result["applicable"] is False
    assert runner.calls == []


def test_fuji_camera_without_film_mode_is_not_applicable() -> None:
    """Older Fuji point-and-shoots have no film-simulation recipe data."""
    runner = _fake_runner({"WhiteBalance": "Auto", "Sharpness": "0 (normal)"})

    result = extract_fuji_recipe(b"bytes", "FUJIFILM", runner=runner)

    assert result["applicable"] is False
    assert result["settings"] is None


def test_runner_failure_is_not_applicable() -> None:
    runner = _fake_runner(None)
    result = extract_fuji_recipe(b"bytes", "FUJIFILM", runner=runner)
    assert result["applicable"] is False


def test_fuji_camera_with_full_recipe_maps_every_field() -> None:
    tags = {
        "FilmMode": "F1b/Studio Portrait Smooth Skin Tone (Astia)",
        "GrainEffectRoughness": "Weak",
        "GrainEffectSize": "Small",
        "ColorChromeEffect": "Strong",
        "WhiteBalance": "Daylight",
        "HighlightTone": "+2 (hard)",
        "ShadowTone": "-1 (medium soft)",
        "Saturation": "+1 (medium high)",
        "Sharpness": "0 (normal)",
        "NoiseReduction": "-2 (weak)",
    }
    runner = _fake_runner(tags)

    result = extract_fuji_recipe(b"bytes", "FUJIFILM", runner=runner)

    assert result["applicable"] is True
    # The "F1b/" internal code prefix is stripped for display.
    assert result["film_simulation"] == "Studio Portrait Smooth Skin Tone (Astia)"
    assert result["settings"] == {
        "grain": "Weak Small",
        "color_chrome_effect": "Strong",
        "white_balance": "Daylight",
        "highlights": "+2 (hard)",
        "shadows": "-1 (medium soft)",
        "color": "+1 (medium high)",
        "sharpness": "0 (normal)",
        "noise_reduction": "-2 (weak)",
    }
    assert runner.calls == [b"bytes"]


def test_film_mode_without_slash_is_used_as_is() -> None:
    runner = _fake_runner({"FilmMode": "Classic Chrome"})
    result = extract_fuji_recipe(b"bytes", "FUJIFILM", runner=runner)
    assert result["film_simulation"] == "Classic Chrome"


def test_grain_off_is_not_expanded_with_size() -> None:
    runner = _fake_runner({"FilmMode": "Provia", "GrainEffectRoughness": "Off"})
    result = extract_fuji_recipe(b"bytes", "FUJIFILM", runner=runner)
    assert result["settings"]["grain"] == "Off"


@pytest.mark.skipif(
    shutil.which("exiftool") is None, reason="exiftool not installed locally"
)
def test_real_exiftool_subprocess_does_not_crash_on_a_plain_jpeg() -> None:
    """Smoke test against the actual binary: a Fuji-free JPEG should just
    report no recipe data, without the subprocess plumbing raising."""
    image = Image.new("RGB", (32, 32), (10, 20, 30))
    buf = io.BytesIO()
    image.save(buf, format="JPEG")

    result = extract_fuji_recipe(
        buf.getvalue(), "FUJIFILM", runner=fuji_recipe_service._run_exiftool
    )

    assert result["applicable"] is False
