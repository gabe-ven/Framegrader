"""Color grading: a single Claude call suggesting slider-ready adjustments.

Mirrors photo_critique.py's shape exactly: the same shared client/encode/
extract helpers from ai_client.py, a system prompt that returns ONLY a JSON
object, and a service that never raises — any failure (no key, unavailable
SDK, API error, unparseable response) degrades to {"available": False,
"reason": ...} so the endpoint responds cleanly and the frontend can fall
back to zeroed sliders.
"""

from __future__ import annotations

import logging
from typing import Any

from PIL import Image

from app.services.ai.ai_client import (
    DEFAULT_MODEL,
    encode_image,
    extract_response_text,
    get_anthropic_client,
    parse_json_object,
)

logger = logging.getLogger(__name__)

_MAX_TOKENS = 500

_SYSTEM_PROMPT = (
    "You are an expert photo colorist suggesting a color grade for a "
    "photograph. You are given the image plus objective measurements already "
    "computed by a computer-vision pipeline (brightness, contrast, dynamic "
    "range, dominant colors, and EXIF camera settings indicating lighting "
    "conditions). Ground your suggested adjustments in those measurements.\n\n"
    "Respond with ONLY a single JSON object (no markdown fences, no prose) "
    "with exactly this shape:\n"
    "{\n"
    '  "adjustments": {\n'
    '    "exposure": number (-2.0 to 2.0, 0 = no change),\n'
    '    "contrast": number (-100 to 100, 0 = no change),\n'
    '    "highlights": number (-100 to 100, 0 = no change),\n'
    '    "shadows": number (-100 to 100, 0 = no change),\n'
    '    "whites": number (-100 to 100, 0 = no change),\n'
    '    "blacks": number (-100 to 100, 0 = no change),\n'
    '    "temperature": number (-100 to 100, 0 = no change),\n'
    '    "tint": number (-100 to 100, 0 = no change),\n'
    '    "saturation": number (-100 to 100, 0 = no change),\n'
    '    "vibrance": number (-100 to 100, 0 = no change),\n'
    '    "sharpness": number (0 to 100, 0 = no change)\n'
    "  },\n"
    '  "reasoning": "one or two sentences explaining the grade",\n'
    '  "style": "natural | cinematic | moody | airy | contrasty | warm | cool"\n'
    "}\n"
    "Suggest a tasteful, realistic grade appropriate to the scene and light — "
    "prefer restraint over dramatic values. Every adjustment field must be "
    "present even when the value is 0."
)


def _fmt(value: Any) -> str:
    return str(value) if value not in (None, "") else "unknown"


def build_context_summary(context: dict[str, Any] | None) -> str:
    """Render the subset of context relevant to grading into a text block.

    Tolerant of missing sections — an empty or partial context just yields a
    shorter summary rather than an error.
    """
    if not context:
        return "No pre-computed measurements were provided."

    lines: list[str] = []

    vision = context.get("vision") or {}
    if vision:
        colors = vision.get("dominant_colors") or []
        color_str = ", ".join(c.get("hex", "?") for c in colors[:5]) or "unknown"
        lines.append(
            "Vision metrics: "
            f"brightness={_fmt(vision.get('brightness'))}, "
            f"contrast={_fmt(vision.get('contrast'))}, "
            f"dominant_colors=[{color_str}]"
        )
        dr = vision.get("dynamic_range") or {}
        if dr:
            lines.append(
                f"Dynamic range: ~{_fmt(dr.get('stops'))} stops "
                f"(range {_fmt(dr.get('range'))})."
            )

    exif = context.get("exif") or {}
    if exif.get("has_exif"):
        lines.append(
            "EXIF (lighting conditions): "
            f"aperture={_fmt(exif.get('aperture'))}, "
            f"ISO={_fmt(exif.get('iso'))}, "
            f"shutter={_fmt(exif.get('shutter_speed'))}"
        )
    else:
        lines.append("EXIF: none present.")

    scene_summary = context.get("scene_summary")
    if scene_summary:
        lines.append(f"Scene: {scene_summary}")

    return "\n".join(lines)


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def generate_color_grade(
    image: Image.Image,
    context: dict[str, Any] | None = None,
    *,
    client: Any | None = None,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Produce suggested grading adjustments for ``image``.

    ``context`` is the prior /analyze response (optionally merged with the AI
    critique's scene summary under a "scene_summary" key) used to ground the
    model. Pass a fake ``client`` in tests to avoid a network call.

    Always returns a dict. On any failure it returns ``{"available": False,
    "reason": ...}`` rather than raising.
    """
    client = client or get_anthropic_client()
    if client is None:
        return _unavailable("Color grading is not configured (no API key).")

    try:
        image_b64, media_type = encode_image(image)
        context_summary = build_context_summary(context)
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Suggest color grading adjustments for this "
                                "photo. Pre-computed measurements:\n\n"
                                f"{context_summary}\n\n"
                                "Return the JSON object described in the "
                                "system prompt."
                            ),
                        },
                    ],
                }
            ],
        )
        text = extract_response_text(response)
        parsed = parse_json_object(text)
    except Exception as exc:  # noqa: BLE001 - never let an AI failure crash the endpoint
        logger.warning(
            "Color grading generation failed (%s: %s).",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return _unavailable("Color grading failed to generate a response.")

    if parsed is None:
        logger.warning("Color grading response was not parseable JSON: %r", text)
        return _unavailable("Color grading returned an unreadable response.")

    parsed["available"] = True
    return parsed
