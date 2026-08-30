"""Analysis routes.

Thin HTTP layer: read the upload, hand bytes to the image service, return a
schema. As features land, this handler calls more services and the response
schema grows — the route logic stays simple.

These handlers are deliberately `def`, not `async def`. Every one of them is
dominated by synchronous CPU-bound work (OpenCV, PIL, YOLO, SSIM) plus a
blocking Anthropic call. Declared `async`, that work runs *on* the event loop
and stalls every other request — /health measured 6.2s during one analysis.
Starlette runs sync handlers in a threadpool instead, so the loop stays free.
Do not "modernise" these back to async without moving the work off-thread.
"""

# NOTE: deliberately no `from __future__ import annotations` here.
# slowapi's @limiter.limit wraps the endpoint with functools.wraps, which keeps
# slowapi's module globals on the wrapper. With postponed evaluation every
# annotation is a string, so FastAPI then tries to resolve ForwardRef
# ('UploadFile') against those globals and fails at import with "Invalid args
# for response field". The `X | None` syntax below is native from 3.10 on, so
# nothing in this module needs the future import anyway.

import json

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

from app.core.config import Settings, get_settings
from app.core.rate_limit import limiter
from app.schemas.analysis import (
    AIAnalysis,
    AIAnalysisResponse,
    AnalysisResponse,
    ColorGradeResponse,
    CompositionInfo,
    ExifInfo,
    FujifilmRecipe,
    ImageInfo,
    VisionInfo,
)
from app.services import image_io
from app.services.ai import color_grading, photo_critique
from app.services.composition import composition_pipeline
from app.services.exif import exif_service, fuji_recipe_service
from app.services.vision import analysis_pipeline

router = APIRouter(tags=["analysis"])

# Read once at import: these are deployment configuration, not per-request
# state. The AI endpoints get the tight limit; /analyze gets a looser one
# because its VLM escalation tier can also spend money (see config.py).
_AI_RATE_LIMIT = get_settings().ai_rate_limit
_ANALYZE_RATE_LIMIT = get_settings().analyze_rate_limit


@router.post("/analyze", response_model=AnalysisResponse)
@limiter.limit(_ANALYZE_RATE_LIMIT)
def analyze(
    # See ai_analysis below — slowapi requires both of these.
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
) -> AnalysisResponse:
    # .file is the underlying SpooledTemporaryFile; UploadFile.read() is async
    # and unusable here. Starlette has already seeked it back to 0.
    data = file.file.read()

    try:
        image_io.validate_upload(
            data, file.content_type, max_bytes=settings.max_upload_bytes
        )
        image = image_io.open_image(
            data, decode_max_edge=settings.decode_max_edge
        )
    except image_io.ImageValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # Read from the header rather than the decoded image: the decode above may
    # be scaled down, but this metadata describes the uploaded photograph.
    original_size = image_io.read_display_dimensions(data)
    info = image_io.describe_image(
        image,
        filename=file.filename or "upload",
        size_bytes=len(data),
        dimensions=original_size,
    )
    exif = exif_service.extract_exif(image)
    # Reads real MakerNote data (via exiftool) straight from the uploaded
    # bytes — must happen before downscaling/re-encoding below, which would
    # strip it.
    recipe = fuji_recipe_service.extract_fuji_recipe(data, exif.get("make"))

    # Cap working resolution before the pixel pipelines run. describe_image and
    # the EXIF read above already captured everything that must reflect the
    # original file, so the reported dimensions stay true while peak memory
    # stops scaling with whatever the camera produced.
    image = image_io.downscale_to_megapixels(
        image, settings.max_analysis_megapixels
    )

    vision = analysis_pipeline.run_vision_analysis(
        image, reported_dimensions=original_size
    )
    composition = composition_pipeline.run_composition_analysis(image)

    return AnalysisResponse(
        image=ImageInfo(**info),
        exif=ExifInfo(**exif),
        vision=VisionInfo(**vision),
        composition=CompositionInfo(**composition),
        recipe=FujifilmRecipe(**recipe),
    )


@router.post("/ai-analysis", response_model=AIAnalysisResponse)
@limiter.limit(_AI_RATE_LIMIT)
def ai_analysis(
    # Both are required by slowapi and unused in the body: `request` carries the
    # client address it keys the limit on, and `response` is where it writes the
    # X-RateLimit-* headers (the handler returns a model, not a Response, so it
    # needs FastAPI's injected one). Neither has a default, so both must precede
    # the parameters that do.
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    context: str | None = Form(
        default=None,
        description="Optional JSON string of the prior /analyze response, used "
        "to ground the AI in the already-computed CV/EXIF/vision measurements.",
    ),
    settings: Settings = Depends(get_settings),
) -> AIAnalysisResponse:
    """Generate an AI critique of the uploaded photo.

    Separate from /analyze so the fast CV metrics can render immediately while
    this slower vision-language call runs. Accepts the prior /analyze response
    as ``context`` so the model reasons from measured facts.
    """
    data = file.file.read()

    try:
        image_io.validate_upload(
            data, file.content_type, max_bytes=settings.max_upload_bytes
        )
        image = image_io.open_image(
            data, decode_max_edge=settings.decode_max_edge
        )
    except image_io.ImageValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # Paused: return the placeholder without building a prompt or calling
    # Claude. Kept after upload validation so a bad file still gets its 422 —
    # the endpoint's contract shouldn't change just because the model is off.
    if settings.ai_analysis_paused:
        return AIAnalysisResponse(ai=AIAnalysis(**photo_critique.placeholder_critique()))

    parsed_context: dict | None = None
    if context:
        try:
            loaded = json.loads(context)
            if isinstance(loaded, dict):
                parsed_context = loaded
        except json.JSONDecodeError:
            # A malformed context is non-fatal: fall back to image-only analysis.
            parsed_context = None

    critique = photo_critique.generate_critique(image, parsed_context)
    return AIAnalysisResponse(ai=AIAnalysis(**critique))


@router.post("/color-grade", response_model=ColorGradeResponse)
@limiter.limit(_AI_RATE_LIMIT)
def color_grade(
    # See ai_analysis above — slowapi requires both of these.
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    context: str | None = Form(
        default=None,
        description="Optional JSON string of context — the prior /analyze "
        "response, optionally merged with the AI critique's scene summary — "
        "used to ground the suggested grade in measured facts.",
    ),
    settings: Settings = Depends(get_settings),
) -> ColorGradeResponse:
    """Suggest color grading adjustments for the uploaded photo.

    Same request contract as /ai-analysis: file + optional JSON context.
    """
    data = file.file.read()

    try:
        image_io.validate_upload(
            data, file.content_type, max_bytes=settings.max_upload_bytes
        )
        image = image_io.open_image(
            data, decode_max_edge=settings.decode_max_edge
        )
    except image_io.ImageValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    parsed_context: dict | None = None
    if context:
        try:
            loaded = json.loads(context)
            if isinstance(loaded, dict):
                parsed_context = loaded
        except json.JSONDecodeError:
            parsed_context = None

    result = color_grading.generate_color_grade(image, parsed_context)
    return ColorGradeResponse(**result)
