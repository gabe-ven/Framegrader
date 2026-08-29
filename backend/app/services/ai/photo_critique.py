"""Photo critique: the Phase 3 AI analysis.

A single vision-language call that interprets a photo the way a photographer
would and returns a structured critique. The already-computed CV/EXIF/vision
context is folded into the prompt so the model reasons from measured facts
(actual EXIF settings, detected composition) rather than guessing blindly.

The service never raises: on a missing key, unavailable SDK, API failure, or
unparseable response it returns an ``available=False`` result so the endpoint
can respond cleanly and the frontend can show a graceful "unavailable" state.
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

_MAX_TOKENS = 2200

_SYSTEM_PROMPT = (
    "You are an expert photography instructor analyzing a photo for a "
    "photographer who wants to understand and recreate it. You are given the "
    "image plus objective measurements already computed by a computer-vision "
    "pipeline (EXIF camera settings, brightness/contrast, dominant colors, and "
    "composition geometry). Ground your analysis in those measurements: when "
    "EXIF camera settings are provided, EXPLAIN them rather than guessing; when "
    "they are absent, ESTIMATE plausible settings from the image and say so.\n\n"
    "This renders as a scannable card, not an essay. Favor short phrases over "
    "full sentences, cut filler words and hedging, and stay within every word "
    "limit below — they are hard caps, not targets to approach.\n\n"
    "Be extremely concise. These per-field limits are HARD caps:\n"
    "- scene.summary: maximum 20 words, one sentence only\n"
    "- subject.primary: 3-5 words\n"
    "- subject.description: maximum 15 words\n"
    "- lighting.summary: maximum 20 words\n"
    "- camera_settings.reasoning: maximum 30 words\n"
    "- composition_critique.strengths: exactly 3 items, maximum 12 words each\n"
    "- composition_critique.improvements: exactly 3 items, maximum 12 words each\n"
    "- composition_critique.overall: maximum 25 words, one sentence\n"
    "- recreation_guide: exactly 4 steps, maximum 15 words each\n\n"
    "Respond with ONLY a single JSON object (no markdown fences, no prose) with "
    "exactly this shape:\n"
    "{\n"
    '  "scene": {\n'
    '    "summary": "a punchy one-sentence description of the photo, max 20 words",\n'
    '    "setting": "e.g. outdoor coastal / indoor studio / urban street",\n'
    '    "tags": ["3-5 short descriptive tags"]\n'
    "  },\n"
    '  "subject": {\n'
    '    "primary": "the main subject, 3-5 words",\n'
    '    "description": "how it is framed, max 15 words"\n'
    "  },\n"
    '  "lighting": {\n'
    '    "summary": "the light in a phrase, max 20 words",\n'
    '    "direction": "front | back | side | top | diffuse | mixed | unknown",\n'
    '    "quality": "hard | soft | diffuse | mixed | unknown",\n'
    '    "time_of_day": "golden hour | blue hour | midday | overcast | night | indoor | unknown"\n'
    "  },\n"
    '  "camera_settings": {\n'
    '    "aperture": "e.g. f/8 or null",\n'
    '    "shutter_speed": "e.g. 1/250 or null",\n'
    '    "iso": "e.g. 100 or null",\n'
    '    "focal_length": "e.g. 35mm or null",\n'
    '    "from_exif": true/false (true if taken from provided EXIF, false if estimated),\n'
    '    "reasoning": "one sentence explaining the settings, max 30 words"\n'
    "  },\n"
    '  "composition_critique": {\n'
    '    "strengths": ["exactly 3 specific things that work, max 12 words each"],\n'
    '    "improvements": ["exactly 3 concrete, actionable suggestions, max 12 words each"],\n'
    '    "overall": "one-sentence overall assessment, max 25 words"\n'
    "  },\n"
    '  "recreation_guide": ["exactly 4 ordered, practical steps, max 15 words each"],\n'
    '  "semantic_composition": {\n'
    '    "leading_lines": {\n'
    '      "present": true/false,\n'
    '      "strength": 0-100 (0 when none are present),\n'
    '      "description": "what lines and where they lead, under 10 words"\n'
    "    },\n"
    '    "rule_of_thirds": { "score": 0-100, "reasoning": "under 10 words" },\n'
    '    "negative_space": { "score": 0-100, "reasoning": "under 10 words" }\n'
    "  },\n"
    '  "fujifilm_recipe": {\n'
    '    "applicable": true/false (false when the EXIF camera make is not Fujifilm, or EXIF is absent),\n'
    '    "film_simulation": "e.g. Classic Chrome, Eterna, Velvia, Provia, Astia, Acros, Nostalgic Neg",\n'
    '    "settings": {\n'
    '      "grain": "e.g. Weak Small / Strong Large / Off",\n'
    '      "color_chrome_effect": "Off | Weak | Strong",\n'
    '      "white_balance": "e.g. Auto / Daylight / 5500K, R+1 B-1",\n'
    '      "highlights": number (Fujifilm tone, typically -2 to +4),\n'
    '      "shadows": number (typically -2 to +4),\n'
    '      "color": number (typically -4 to +4),\n'
    '      "sharpness": number (typically -4 to +4),\n'
    '      "noise_reduction": number (typically -4 to +4)\n'
    "    },\n"
    '    "reasoning": "why this recipe fits, under 12 words"\n'
    "  }\n"
    "}\n"
    "Judge semantic_composition from the image itself — this is your independent, "
    "meaning-aware read, and it intentionally REPLACES the geometric CV scores for "
    "leading lines, rule of thirds, and negative space. "
    "For fujifilm_recipe, recommend a film simulation and in-camera settings that suit "
    "the scene and light; set applicable to false when the EXIF camera make is not a "
    "Fujifilm body (including when no EXIF is present), but still provide a usable recipe. "
    "Be specific and practical. Prefer concrete photographic advice over generic praise, "
    "and prefer a terse phrase over a complete sentence wherever the shape above allows it."
)


def _fmt(value: Any) -> str:
    return str(value) if value not in (None, "") else "unknown"


def build_context_summary(context: dict[str, Any] | None) -> str:
    """Render the CV/EXIF/vision context into a compact text block for the prompt.

    Tolerant of missing sections — an empty or partial context just yields a
    shorter summary rather than an error.
    """
    if not context:
        return "No pre-computed measurements were provided."

    lines: list[str] = []

    exif = context.get("exif") or {}
    if exif.get("has_exif"):
        lines.append(
            "EXIF (actual camera settings): "
            f"camera={_fmt(exif.get('make'))} {_fmt(exif.get('model'))}, "
            f"lens={_fmt(exif.get('lens'))}, "
            f"ISO={_fmt(exif.get('iso'))}, "
            f"aperture={_fmt(exif.get('aperture'))}, "
            f"shutter={_fmt(exif.get('shutter_speed'))}, "
            f"focal_length={_fmt(exif.get('focal_length'))}"
        )
    else:
        lines.append("EXIF: none present (estimate camera settings from the image).")

    vision = context.get("vision") or {}
    if vision:
        colors = vision.get("dominant_colors") or []
        color_str = ", ".join(c.get("hex", "?") for c in colors[:5]) or "unknown"
        lines.append(
            "Vision metrics: "
            f"brightness={_fmt(vision.get('brightness'))}, "
            f"contrast={_fmt(vision.get('contrast'))}, "
            f"sharpness={_fmt(vision.get('sharpness'))}, "
            f"orientation={_fmt(vision.get('orientation'))}, "
            f"dominant_colors=[{color_str}]"
        )
        dr = vision.get("dynamic_range") or {}
        if dr:
            lines.append(f"Dynamic range: ~{_fmt(dr.get('stops'))} stops.")

    comp = context.get("composition") or {}
    if comp:
        parts: list[str] = []
        rot = comp.get("rule_of_thirds") or {}
        if rot:
            parts.append(
                f"rule_of_thirds={'follows' if rot.get('follows_rule') else 'centered/other'}"
            )
        ll = comp.get("leading_lines") or {}
        if ll.get("has_leading_lines"):
            parts.append(f"leading_lines at ~{_fmt(ll.get('dominant_angle'))}°")
        hz = comp.get("horizon") or {}
        if hz.get("horizon_detected"):
            if hz.get("tilt_reliable"):
                level = "level" if hz.get("is_level") else f"tilted {_fmt(hz.get('tilt_angle'))}°"
                parts.append(f"horizon detected ({level})")
            else:
                # Tilt estimate is disabled — omit it rather than feed the model
                # an angle we know is wrong.
                parts.append("horizon detected")
        sym = comp.get("symmetry") or {}
        if sym.get("is_symmetric"):
            parts.append(f"{_fmt(sym.get('dominant_axis'))} symmetry")
        sp = comp.get("subject_position") or {}
        if sp:
            label = sp.get("label")
            region = _fmt(sp.get("region"))
            parts.append(
                f"subject '{label}' in {region}" if label else f"subject in {region}"
            )
        ns = comp.get("negative_space") or {}
        if ns.get("has_significant_negative_space"):
            parts.append("significant negative space")
        if parts:
            lines.append("Composition geometry: " + "; ".join(parts) + ".")

    return "\n".join(lines)


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def generate_critique(
    image: Image.Image,
    context: dict[str, Any] | None = None,
    *,
    client: Any | None = None,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Produce a structured AI critique of ``image``.

    ``context`` is the prior /analyze response (exif/vision/composition) used
    to ground the model. Pass a fake ``client`` (anything exposing
    ``.messages.create(...)``) in tests to avoid a network call.

    Always returns a dict. On any failure it returns ``{"available": False,
    "reason": ...}`` rather than raising.
    """
    client = client or get_anthropic_client()
    if client is None:
        return _unavailable("AI analysis is not configured (no API key).")

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
                                "Analyze this photo. Pre-computed measurements:\n\n"
                                f"{context_summary}\n\n"
                                "Return the JSON object described in the system prompt."
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
            "AI critique generation failed (%s: %s).",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return _unavailable("AI analysis failed to generate a response.")

    if parsed is None:
        logger.warning("AI critique response was not parseable JSON: %r", text)
        return _unavailable("AI analysis returned an unreadable response.")

    _reattach_misnested_overall(parsed)
    parsed["available"] = True
    return parsed


def _reattach_misnested_overall(parsed: dict[str, Any]) -> None:
    """Recover ``overall`` when the model emits it as a stray top-level key.

    Observed in the wild: a brace-repaired response can leave "overall" as a
    sibling of "composition_critique" instead of nested inside it (the model
    closed that object one brace early). Move it back in place so the
    verdict still renders instead of silently vanishing.
    """
    stray_overall = parsed.pop("overall", None)
    if not stray_overall:
        return
    crit = parsed.get("composition_critique")
    if isinstance(crit, dict) and not crit.get("overall"):
        crit["overall"] = stray_overall
