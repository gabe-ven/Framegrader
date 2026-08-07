"""Shared Anthropic client factory and image encoding for the AI layer.

Mirrors the proven integration in composition/subject_localization.py:
lazily construct the client, read the key from the environment, and never
raise on a missing key or unavailable SDK — callers degrade gracefully.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

# Matches a backslash not followed by a legal JSON escape character. Models
# sometimes escape an apostrophe as \' (valid in Python/JS string literals,
# illegal in JSON) — stripping these backslashes salvages the response
# instead of discarding it outright.
_INVALID_ESCAPE_RE = re.compile(r'\\(?!["\\/bfnrtu])')

# Default Claude model for the AI layer. Kept in sync with the VLM subject
# locator so the whole app uses one vision model.
DEFAULT_MODEL = "claude-sonnet-4-6"

# Long-edge cap for images sent to the model. 1024 px is plenty for scene/
# composition reasoning and keeps token cost and latency down.
VLM_MAX_EDGE = 1024


def get_anthropic_client() -> Any | None:
    """Return an Anthropic client, or None if it can't be constructed.

    Returns None (never raises) when ANTHROPIC_API_KEY is unset or the SDK
    isn't importable, so features built on this degrade gracefully.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set; AI analysis unavailable.")
        return None

    try:
        from anthropic import Anthropic
    except Exception as exc:  # noqa: BLE001 - any import failure -> unavailable
        logger.warning(
            "anthropic SDK unavailable (%s: %s); AI analysis unavailable.",
            type(exc).__name__,
            exc,
        )
        return None

    return Anthropic(api_key=api_key)


def encode_image(image: Image.Image) -> tuple[str, str]:
    """Resize to <= VLM_MAX_EDGE on the long edge and base64-encode as JPEG.

    Returns (base64_data, media_type) ready to drop into an Anthropic image
    content block.
    """
    width, height = image.size
    scale = VLM_MAX_EDGE / float(max(width, height)) if max(width, height) else 1.0
    if scale < 1.0:
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = image.resize(new_size, Image.LANCZOS)

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=85)
    return base64.standard_b64encode(buffer.getvalue()).decode("ascii"), "image/jpeg"


def extract_response_text(response: Any) -> str:
    """Concatenate the text blocks out of an Anthropic Messages API response."""
    blocks = getattr(response, "content", None) or []
    texts = [getattr(block, "text", None) for block in blocks]
    return "".join(t for t in texts if t)


def _loads_with_brace_repair(text: str) -> Any | None:
    """`json.loads`, with one targeted retry for a stray closing brace.

    Observed in the wild: the model occasionally over-closes a nested object
    one brace early, then keeps emitting sibling keys as if it were still
    open — e.g. ``..."composition_critique":{...},"overall":"x"},"next":...``
    where that `}` right after "x" terminates the whole object prematurely.
    json.loads reports this as "Extra data" at the position where the second
    (illegal) top-level value starts; the character just before it is the
    stray brace/bracket. Dropping it and reparsing recovers the rest of the
    payload instead of discarding it outright.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        if exc.msg != "Extra data" or exc.pos == 0 or text[exc.pos - 1] not in "}]":
            return None
        repaired = text[: exc.pos - 1] + text[exc.pos :]
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort parse of a JSON object out of a model's text response.

    Extracts the first ``{...}`` span (tolerating surrounding prose), then
    tries progressively more permissive repairs before giving up: parse as
    given, then retry with invalid backslash escapes stripped (models
    occasionally produce non-JSON escapes like ``\\'``), each also retried
    with a stray-closing-brace repair (see `_loads_with_brace_repair`).
    Returns None if no valid JSON object can be recovered.
    """
    if not text:
        return None
    match = _JSON_OBJECT_RE.search(text)
    candidate = match.group(0) if match else text

    for variant in (candidate, _INVALID_ESCAPE_RE.sub("", candidate)):
        parsed = _loads_with_brace_repair(variant)
        if isinstance(parsed, dict):
            return parsed
    return None
