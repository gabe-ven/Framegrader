"""API contract for the analysis endpoint.

`AnalysisResponse` is intentionally small right now. Each feature we add
(EXIF, composition, lighting, AI critique...) appends a new optional field
here, so the contract grows without breaking existing clients.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ImageInfo(BaseModel):
    filename: str
    format: str
    mode: str
    width: int
    height: int
    megapixels: float
    aspect_ratio: float
    size_bytes: int


class GpsCoordinates(BaseModel):
    latitude: float
    longitude: float


class ExifInfo(BaseModel):
    """Camera metadata read from the file. Every field is optional because
    many images (screenshots, exports, stripped photos) carry no EXIF."""

    has_exif: bool = Field(..., description="True if any EXIF field was found.")
    make: str | None = None
    model: str | None = None
    lens: str | None = None
    iso: int | None = None
    aperture: str | None = None
    shutter_speed: str | None = None
    focal_length: str | None = None
    date_taken: str | None = None
    gps: GpsCoordinates | None = None


class ColorSwatch(BaseModel):
    hex: str
    rgb: list[int]
    proportion: float


class Dimensions(BaseModel):
    width: int
    height: int
    aspect_ratio: float


class Histogram(BaseModel):
    bins: int
    r: list[int]
    g: list[int]
    b: list[int]


class DynamicRange(BaseModel):
    low: float
    high: float
    range: float
    stops: float


class VisionInfo(BaseModel):
    """Objective image-quality metrics from the OpenCV pipeline (no AI)."""

    brightness: float
    contrast: float
    sharpness: float
    dominant_colors: list[ColorSwatch]
    color_samples: list[list[int]] = Field(
        default_factory=list,
        description="Raw [r, g, b] pixel scatter for the 3D color-space point cloud.",
    )
    histogram: Histogram
    dynamic_range: DynamicRange
    dimensions: Dimensions
    orientation: str


class Point(BaseModel):
    x: float
    y: float


class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class RuleOfThirds(BaseModel):
    score: float
    follows_rule: bool
    centroid: Point
    nearest_power_point: Point
    distance_to_power_point: float
    source: str = "saliency"


class LineSegment(BaseModel):
    """A detected leading line. Endpoints are normalized to ``[0, 1]`` with a
    top-left origin, like every other spatial field here, so a client can scale
    them to whatever size it is actually displaying the photo at."""

    x1: float
    y1: float
    x2: float
    y2: float
    angle: float


class LeadingLines(BaseModel):
    has_leading_lines: bool
    line_count: int
    dominant_angle: float | None
    lines: list[LineSegment]


class Horizon(BaseModel):
    horizon_detected: bool
    horizon_y: float | None
    is_level: bool
    tilt_angle: float | None
    # False while the tilt estimator is disabled — consumers must not display
    # or reason about tilt_angle when this is False.
    tilt_reliable: bool = False


class Symmetry(BaseModel):
    vertical: float
    horizontal: float
    is_symmetric: bool
    dominant_axis: str


class SubjectPosition(BaseModel):
    centroid: Point
    region: str
    offset_from_center: float
    bbox: BoundingBox | None = None
    label: str | None = None
    confidence: float = 0.0
    has_mask: bool = False
    source: str = "saliency"


class EdgeRegions(BaseModel):
    top: float
    bottom: float
    left: float
    right: float
    center: float


class EdgeDensity(BaseModel):
    edge_density: float
    busyness: str
    regions: EdgeRegions


class NegativeSpace(BaseModel):
    negative_space_ratio: float
    subject_excluded_ratio: float
    has_significant_negative_space: bool


class CompositionInfo(BaseModel):
    """Geometric/structural composition metrics from OpenCV (no AI)."""

    rule_of_thirds: RuleOfThirds
    leading_lines: LeadingLines
    horizon: Horizon
    symmetry: Symmetry
    subject_position: SubjectPosition
    edge_density: EdgeDensity
    negative_space: NegativeSpace


class AnalysisResponse(BaseModel):
    image: ImageInfo = Field(..., description="Basic metadata about the upload.")
    exif: ExifInfo = Field(..., description="Camera metadata extracted from EXIF.")
    vision: VisionInfo = Field(..., description="Objective CV image-quality metrics.")
    composition: CompositionInfo = Field(
        ..., description="Geometric composition metrics."
    )


# --- Phase 3: AI analysis --------------------------------------------------
# Every field on the sub-models is optional: the response is produced by a
# vision-language model, so a partial/omitted field must degrade gracefully
# rather than fail validation.


class SceneInfo(BaseModel):
    summary: str | None = None
    setting: str | None = None
    tags: list[str] = Field(default_factory=list)


class SubjectInsight(BaseModel):
    primary: str | None = None
    description: str | None = None


class LightingInfo(BaseModel):
    summary: str | None = None
    direction: str | None = None
    quality: str | None = None
    time_of_day: str | None = None


class CameraSettings(BaseModel):
    aperture: str | None = None
    shutter_speed: str | None = None
    iso: str | None = None
    focal_length: str | None = None
    from_exif: bool = False
    reasoning: str | None = None


class CompositionCritique(BaseModel):
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    overall: str | None = None


class SemanticLeadingLines(BaseModel):
    present: bool | None = None
    strength: float | None = None
    description: str | None = None


class SemanticScore(BaseModel):
    score: float | None = None
    reasoning: str | None = None


class SemanticComposition(BaseModel):
    """The AI's meaning-aware read of composition. Intentionally replaces the
    geometric CV scores for these three dimensions."""

    leading_lines: SemanticLeadingLines | None = None
    rule_of_thirds: SemanticScore | None = None
    negative_space: SemanticScore | None = None


class FujifilmRecipeSettings(BaseModel):
    grain: str | None = None
    color_chrome_effect: str | None = None
    white_balance: str | None = None
    highlights: float | None = None
    shadows: float | None = None
    color: float | None = None
    sharpness: float | None = None
    noise_reduction: float | None = None


class FujifilmRecipe(BaseModel):
    """A Fujifilm film-simulation recipe recommendation (Phase 4).

    ``applicable`` is False when the shot was not taken on a Fujifilm body."""

    applicable: bool | None = None
    film_simulation: str | None = None
    settings: FujifilmRecipeSettings | None = None
    reasoning: str | None = None


class AIAnalysis(BaseModel):
    """Vision-language interpretation of the photo (Phase 3).

    ``available`` is False when AI analysis is unconfigured or failed; in that
    case ``reason`` explains why and the content fields are omitted.
    """

    available: bool
    reason: str | None = None
    scene: SceneInfo | None = None
    subject: SubjectInsight | None = None
    lighting: LightingInfo | None = None
    camera_settings: CameraSettings | None = None
    composition_critique: CompositionCritique | None = None
    recreation_guide: list[str] = Field(default_factory=list)
    semantic_composition: SemanticComposition | None = None
    fujifilm_recipe: FujifilmRecipe | None = None


class AIAnalysisResponse(BaseModel):
    ai: AIAnalysis = Field(..., description="AI interpretation of the photo.")


# --- Color grading -----------------------------------------------------
# A single Claude call suggesting slider-ready adjustments. Mirrors
# AIAnalysis: every field degrades gracefully, and `available=False` on
# any failure rather than raising.


class GradingAdjustments(BaseModel):
    exposure: float = 0.0
    contrast: float = 0.0
    highlights: float = 0.0
    shadows: float = 0.0
    whites: float = 0.0
    blacks: float = 0.0
    temperature: float = 0.0
    tint: float = 0.0
    saturation: float = 0.0
    vibrance: float = 0.0
    sharpness: float = 0.0


class ColorGradeResponse(BaseModel):
    available: bool
    adjustments: GradingAdjustments = Field(default_factory=GradingAdjustments)
    reasoning: str | None = None
    style: str | None = None
    reason: str | None = None
