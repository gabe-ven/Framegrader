"""Real Fujifilm film-simulation recipe extraction.

Fujifilm bodies bake the in-camera recipe (film simulation, grain, color
chrome, tone curves, ...) into proprietary MakerNote tags that Pillow's
`getexif()` never decodes — it only understands the standard EXIF IFDs. There
is no AI involved here: this reads the settings the camera actually applied,
via `exiftool` (the community-maintained, battle-tested parser for these
tags — hand-rolling the binary MakerNote format from scratch risks silently
wrong values, which is worse than showing nothing).

Never raises: a missing `exiftool` binary, a non-Fujifilm camera, or any
parse failure all just yield "not applicable" so the caller can render
"no recipe" rather than break the request.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any, Callable

logger = logging.getLogger(__name__)

_EXIFTOOL_BIN = shutil.which("exiftool")
if _EXIFTOOL_BIN is None:
    logger.warning(
        "exiftool not found on PATH — Fujifilm recipe extraction is disabled."
    )

# Exact tag names exiftool understands for Fuji's recipe MakerNotes. Passed
# with `-j` (JSON output), which returns exiftool's already human-readable
# PrintConv strings (e.g. "Classic Chrome", "+2 (hard)") rather than raw
# camera-internal codes — no manual enum tables to get wrong.
_FUJI_TAGS = (
    "FilmMode",
    "GrainEffectRoughness",
    "GrainEffectSize",
    "ColorChromeEffect",
    "WhiteBalance",
    "HighlightTone",
    "ShadowTone",
    "Saturation",
    "Sharpness",
    "NoiseReduction",
)

_NOT_APPLICABLE: dict[str, Any] = {
    "applicable": False,
    "film_simulation": None,
    "settings": None,
}


def _run_exiftool(image_bytes: bytes) -> dict[str, Any] | None:
    """Run exiftool over the raw file bytes (via stdin) and return its tag
    dict, or None on any failure. Reading from stdin avoids writing a temp
    file — exiftool identifies the format from the file's own signature, not
    its (absent) name."""
    if _EXIFTOOL_BIN is None:
        return None
    args = [_EXIFTOOL_BIN, "-j", *(f"-{tag}" for tag in _FUJI_TAGS), "-"]
    try:
        proc = subprocess.run(
            args, input=image_bytes, capture_output=True, timeout=10
        )
        if proc.returncode != 0:
            return None
        parsed = json.loads(proc.stdout)
        return parsed[0] if parsed else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, IndexError):
        logger.debug("exiftool run failed while reading Fuji recipe.", exc_info=True)
        return None


def _clean_film_mode(value: str | None) -> str | None:
    """exiftool's FilmMode label carries an internal code prefix on some
    entries, e.g. "F1b/Studio Portrait Smooth Skin Tone (Astia)" — the part
    after the slash is the actual simulation name."""
    if not value:
        return None
    return value.rsplit("/", 1)[-1].strip()


def _clean_grain(roughness: str | None, size: str | None) -> str | None:
    if not roughness:
        return None
    if roughness.lower() == "off" or not size or size.lower() == "off":
        return roughness
    return f"{roughness} {size}"


def extract_fuji_recipe(
    image_bytes: bytes,
    make: str | None,
    *,
    runner: Callable[[bytes], dict[str, Any] | None] = _run_exiftool,
) -> dict[str, Any]:
    """Read the real in-camera recipe from a Fujifilm photo's MakerNotes.

    ``make`` is the already-parsed standard EXIF make (from `exif_service`) —
    checked first so non-Fuji uploads (the common case) skip the subprocess
    call entirely. Returns ``applicable: False`` whenever the camera isn't a
    Fuji body or the file has no recipe data (e.g. an older model without
    film-simulation recipes, or a non-JPEG that stripped MakerNotes).
    """
    if not make or "fujifilm" not in make.lower():
        return _NOT_APPLICABLE

    tags = runner(image_bytes)
    film_mode = tags.get("FilmMode") if tags else None
    if not tags or not film_mode:
        return _NOT_APPLICABLE

    return {
        "applicable": True,
        "film_simulation": _clean_film_mode(film_mode),
        "settings": {
            "grain": _clean_grain(
                tags.get("GrainEffectRoughness"), tags.get("GrainEffectSize")
            ),
            "color_chrome_effect": tags.get("ColorChromeEffect"),
            "white_balance": tags.get("WhiteBalance"),
            "highlights": tags.get("HighlightTone"),
            "shadows": tags.get("ShadowTone"),
            "color": tags.get("Saturation"),
            "sharpness": tags.get("Sharpness"),
            "noise_reduction": tags.get("NoiseReduction"),
        },
    }
