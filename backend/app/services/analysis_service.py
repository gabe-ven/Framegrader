"""The measurement pipeline, independent of how it is invoked.

Both the synchronous ``POST /api/analyze`` route and the background ``analyze``
job run exactly this code, so the two paths cannot drift: same decode, same
EXIF handling, same metrics, same response shape.

Every step runs inside an ``observability.stage`` so its duration lands in the
request's Server-Timing header or the job's stored timings, and ``on_stage``
lets the job worker turn the same boundaries into user-visible progress.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PIL import Image
from pydantic import ValidationError

from app.core.config import Settings
from app.core.observability import stage
from app.schemas.analysis import (
    AIAnalysis,
    AnalysisResponse,
    ColorGradeResponse,
)
from app.services import image_io
from app.services.composition import composition_pipeline
from app.services.exif import exif_service, fuji_recipe_service
from app.services.scoring import aesthetic, composition_score
from app.services.vision import analysis_pipeline

logger = logging.getLogger(__name__)

OnStage = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def measure(
    data: bytes,
    *,
    filename: str,
    content_type: str | None,
    settings: Settings,
    on_stage: OnStage | None = None,
) -> tuple[AnalysisResponse, Image.Image]:
    """Validate, decode and measure one upload.

    Returns the response model plus the decoded working image (already capped
    to ``max_analysis_megapixels``), which callers reuse for the AI calls and
    the stored copy instead of decoding the bytes a second time.

    Raises ``image_io.ImageValidationError`` for anything that is not a usable
    image.
    """
    report = on_stage or _noop

    report("decode")
    with stage("decode"):
        image_io.validate_upload(data, content_type, max_bytes=settings.max_upload_bytes)
        image = image_io.open_image(data, decode_max_edge=settings.decode_max_edge)
        # Read from the header rather than the decoded image: the decode above
        # may be scaled down, but this metadata describes the uploaded photo.
        original_size = image_io.read_display_dimensions(data)

    report("metadata")
    with stage("metadata"):
        info = image_io.describe_image(
            image, filename=filename, size_bytes=len(data), dimensions=original_size
        )
        exif = exif_service.extract_exif(image)
        # Reads real MakerNote data (via exiftool) straight from the uploaded
        # bytes — must happen before downscaling/re-encoding below, which
        # would strip it.
        recipe = fuji_recipe_service.extract_fuji_recipe(data, exif.get("make"))

    # Cap working resolution before the pixel pipelines run. describe_image
    # and the EXIF read above already captured everything that must reflect
    # the original file, so the reported dimensions stay true while peak
    # memory stops scaling with whatever the camera produced.
    image = image_io.downscale_to_megapixels(image, settings.max_analysis_megapixels)

    report("vision")
    with stage("vision"):
        vision = analysis_pipeline.run_vision_analysis(image, reported_dimensions=original_size)

    # "subject" and "composition" are reported from inside the pipeline.
    composition = composition_pipeline.run_composition_analysis(image, on_stage=report)

    report("scoring")
    with stage("scoring"):
        scores = score(image, composition)

    response = AnalysisResponse.model_validate(
        {
            "image": info,
            "exif": exif,
            "vision": vision,
            "composition": composition,
            "recipe": recipe,
            "scores": scores,
        }
    )
    return response, image


def score(image: Image.Image, composition: dict[str, Any]) -> dict[str, Any]:
    """The learned aesthetic score, and the composition score calibrated
    against human ratings (using the aesthetic score as a feature when the
    model is available)."""
    aes = aesthetic.score_image(image)
    comp = composition_score.composition_score(composition, aes["score"] if aes else None)
    return {
        "composition": {
            "score": comp["score"],
            "method": comp["method"],
            "model": aes["model"] if aes and "+" in comp["method"] else None,
            "heuristic": comp["heuristic"],
        },
        "aesthetic": (
            {"score": aes["score"], "method": "onnx", "model": aes["model"]} if aes else None
        ),
    }


def coerce_ai(critique: dict[str, Any]) -> AIAnalysis:
    """Validate a critique dict, degrading to ``available=False`` on bad shape.

    ``photo_critique.generate_critique`` never raises, but a well-formed JSON
    response can still violate the schema (a list where a string was expected,
    an object for a recipe field). Validation used to happen bare in the route,
    turning exactly those responses into HTTP 500s.
    """
    try:
        return AIAnalysis.model_validate(critique)
    except ValidationError as exc:
        logger.warning(
            "AI critique failed schema validation",
            extra={"errors": exc.errors(include_url=False, include_input=False)},
        )
        return AIAnalysis(
            available=False, reason="AI analysis returned an unexpected response shape."
        )


def coerce_color_grade(result: dict[str, Any]) -> ColorGradeResponse:
    """Same contract as ``coerce_ai``, for the color-grade response."""
    try:
        return ColorGradeResponse.model_validate(result)
    except ValidationError as exc:
        logger.warning(
            "Color grade failed schema validation",
            extra={"errors": exc.errors(include_url=False, include_input=False)},
        )
        return ColorGradeResponse(
            available=False, reason="Color grading returned an unexpected response shape."
        )
