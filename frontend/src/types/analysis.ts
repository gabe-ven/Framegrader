// Mirrors the backend Pydantic schemas in app/schemas/analysis.py.
// Grows alongside the API contract as features are added.

export interface ImageInfo {
  filename: string;
  format: string;
  mode: string;
  width: number;
  height: number;
  megapixels: number;
  aspect_ratio: number;
  size_bytes: number;
}

export interface GpsCoordinates {
  latitude: number;
  longitude: number;
}

export interface ExifInfo {
  has_exif: boolean;
  make: string | null;
  model: string | null;
  lens: string | null;
  iso: number | null;
  aperture: string | null;
  shutter_speed: string | null;
  focal_length: string | null;
  date_taken: string | null;
  gps: GpsCoordinates | null;
}

export interface ColorSwatch {
  hex: string;
  rgb: number[];
  proportion: number;
}

export interface Dimensions {
  width: number;
  height: number;
  aspect_ratio: number;
}

export interface Histogram {
  bins: number;
  r: number[];
  g: number[];
  b: number[];
}

export interface DynamicRange {
  low: number;
  high: number;
  range: number;
  stops: number;
}

export type Orientation = "portrait" | "landscape" | "square";

export interface VisionInfo {
  brightness: number;
  contrast: number;
  sharpness: number;
  dominant_colors: ColorSwatch[];
  color_samples: number[][];
  histogram: Histogram;
  dynamic_range: DynamicRange;
  dimensions: Dimensions;
  orientation: Orientation;
}

export interface Point {
  x: number;
  y: number;
}

export interface BoundingBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export type SubjectSource = "detector" | "saliency" | "vlm";

/**
 * Maps a SubjectSource to a human-readable display label.
 *
 * The never check in the default branch makes TypeScript flag this function
 * as a compile error whenever a new SubjectSource variant is added without
 * a corresponding case — use this (or the same pattern) in any component
 * that switches on source, so regressions are caught at build time.
 */
export function subjectSourceLabel(source: SubjectSource): string {
  switch (source) {
    case "detector":
      return "Object Detector";
    case "saliency":
      return "Saliency Fallback";
    case "vlm":
      return "VLM";
    default: {
      const _exhaustive: never = source;
      return _exhaustive;
    }
  }
}

export interface RuleOfThirds {
  score: number;
  follows_rule: boolean;
  centroid: Point;
  nearest_power_point: Point;
  distance_to_power_point: number;
  source: SubjectSource;
}

export interface LineSegment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  angle: number;
}

export interface LeadingLines {
  has_leading_lines: boolean;
  line_count: number;
  dominant_angle: number | null;
  lines: LineSegment[];
}

export interface Horizon {
  horizon_detected: boolean;
  horizon_y: number | null;
  is_level: boolean;
  tilt_angle: number | null;
  /** False while the backend tilt estimator is disabled. When false, never
   *  display tilt_angle — treat the horizon as level of unknown accuracy. */
  tilt_reliable: boolean;
}

export interface Symmetry {
  vertical: number;
  horizontal: number;
  is_symmetric: boolean;
  dominant_axis: "vertical" | "horizontal";
}

export interface SubjectPosition {
  centroid: Point;
  region: string;
  offset_from_center: number;
  bbox: BoundingBox | null;
  label: string | null;
  confidence: number;
  has_mask: boolean;
  source: SubjectSource;
}

export interface EdgeRegions {
  top: number;
  bottom: number;
  left: number;
  right: number;
  center: number;
}

export interface EdgeDensity {
  edge_density: number;
  busyness: "minimal" | "moderate" | "busy";
  regions: EdgeRegions;
}

export interface NegativeSpace {
  negative_space_ratio: number;
  subject_excluded_ratio: number;
  has_significant_negative_space: boolean;
}

export interface CompositionInfo {
  rule_of_thirds: RuleOfThirds;
  leading_lines: LeadingLines;
  horizon: Horizon;
  symmetry: Symmetry;
  subject_position: SubjectPosition;
  edge_density: EdgeDensity;
  negative_space: NegativeSpace;
}

export interface AnalysisResponse {
  image: ImageInfo;
  exif: ExifInfo;
  vision: VisionInfo;
  composition: CompositionInfo;
}

// --- Phase 3: AI analysis --------------------------------------------------
// All content fields are optional: they come from a vision-language model and
// may be partially omitted, so the UI must render whatever is present.

export interface SceneInfo {
  summary: string | null;
  setting: string | null;
  tags: string[];
}

export interface SubjectInsight {
  primary: string | null;
  description: string | null;
}

export interface LightingInfo {
  summary: string | null;
  direction: string | null;
  quality: string | null;
  time_of_day: string | null;
}

export interface CameraSettings {
  aperture: string | null;
  shutter_speed: string | null;
  iso: string | null;
  focal_length: string | null;
  from_exif: boolean;
  reasoning: string | null;
}

export interface CompositionCritique {
  strengths: string[];
  improvements: string[];
  overall: string | null;
}

export interface SemanticLeadingLines {
  present: boolean | null;
  strength: number | null;
  description: string | null;
}

export interface SemanticScore {
  score: number | null;
  reasoning: string | null;
}

export interface SemanticComposition {
  leading_lines: SemanticLeadingLines | null;
  rule_of_thirds: SemanticScore | null;
  negative_space: SemanticScore | null;
}

export interface FujifilmRecipeSettings {
  grain: string | null;
  color_chrome_effect: string | null;
  white_balance: string | null;
  highlights: number | null;
  shadows: number | null;
  color: number | null;
  sharpness: number | null;
  noise_reduction: number | null;
}

export interface FujifilmRecipe {
  applicable: boolean | null;
  film_simulation: string | null;
  settings: FujifilmRecipeSettings | null;
  reasoning: string | null;
}

export interface AIAnalysis {
  available: boolean;
  reason: string | null;
  scene: SceneInfo | null;
  subject: SubjectInsight | null;
  lighting: LightingInfo | null;
  camera_settings: CameraSettings | null;
  composition_critique: CompositionCritique | null;
  recreation_guide: string[];
  semantic_composition: SemanticComposition | null;
  fujifilm_recipe: FujifilmRecipe | null;
}

export interface AIAnalysisResponse {
  ai: AIAnalysis;
}

// --- Color grading -----------------------------------------------------

export interface GradingAdjustments {
  exposure: number;
  contrast: number;
  highlights: number;
  shadows: number;
  whites: number;
  blacks: number;
  temperature: number;
  tint: number;
  saturation: number;
  vibrance: number;
  sharpness: number;
}

export type ColorGradeStyle =
  | "natural"
  | "cinematic"
  | "moody"
  | "airy"
  | "contrasty"
  | "warm"
  | "cool";

export interface ColorGradeResponse {
  available: boolean;
  adjustments: GradingAdjustments;
  reasoning: string | null;
  style: ColorGradeStyle | null;
  reason: string | null;
}
