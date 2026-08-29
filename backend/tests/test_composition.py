import cv2
import numpy as np
from PIL import Image

from app.services.composition.composition_pipeline import run_composition_analysis
from app.services.composition.edge_density import compute_edge_density
from app.services.composition.horizon_detection import detect_horizon
from app.services.composition.leading_lines import detect_leading_lines
from app.services.composition.negative_space import estimate_negative_space
from app.services.composition.rule_of_thirds import analyze_rule_of_thirds
from app.services.composition.subject import Subject
from app.services.composition.subject_localization import (
    CompositeSubjectLocator,
    LocatorResult,
    VLMSubjectLocator,
    locate_subject,
)
from app.services.composition.subject_position import estimate_subject_position
from app.services.composition.symmetry import analyze_symmetry


def _blank(size: int = 100) -> np.ndarray:
    return np.zeros((size, size), dtype=np.uint8)


def _with_square(top: int, left: int, side: int = 26, size: int = 100) -> np.ndarray:
    img = _blank(size)
    img[top : top + side, left : left + side] = 255
    return img


def _checkerboard(size: int = 100, cell: int = 5) -> np.ndarray:
    ys, xs = np.indices((size, size))
    return (((xs // cell + ys // cell) % 2) * 255).astype(np.uint8)


# --- rule of thirds -------------------------------------------------------


def test_rule_of_thirds_subject_on_power_point() -> None:
    img = _with_square(top=20, left=20)  # centered near (0.33, 0.33)
    result = analyze_rule_of_thirds(img)
    assert result["follows_rule"] is True
    assert result["score"] > 0.6


def test_rule_of_thirds_centered_subject_fails() -> None:
    img = _with_square(top=37, left=37)  # dead center
    result = analyze_rule_of_thirds(img)
    assert result["follows_rule"] is False
    assert result["score"] < 0.3


def test_rule_of_thirds_subject_exactly_on_power_point_scores_full() -> None:
    """A centroid placed exactly on a power point is distance 0 -> score ~1."""
    subject = Subject.from_saliency((1 / 3, 1 / 3))
    result = analyze_rule_of_thirds(_blank(), subject)
    assert result["score"] > 0.99
    assert result["follows_rule"] is True
    assert result["distance_to_power_point"] < 0.001


def test_rule_of_thirds_subject_exactly_centered_scores_zero() -> None:
    """Dead center is exactly _CENTER_DISTANCE from every power point -> ~0."""
    subject = Subject.from_saliency((0.5, 0.5))
    result = analyze_rule_of_thirds(_blank(), subject)
    assert result["score"] < 0.01
    assert result["follows_rule"] is False


def test_rule_of_thirds_subject_at_corner_clamps_low() -> None:
    """A frame corner is farther from a power point than the center is; the
    raw formula goes negative there and must clamp to 0, not crash or return
    a negative score."""
    subject = Subject.from_saliency((0.0, 0.0))
    result = analyze_rule_of_thirds(_blank(), subject)
    assert result["score"] == 0.0
    assert 0.0 <= result["score"] <= 1.0
    assert result["follows_rule"] is False


# --- leading lines --------------------------------------------------------


def test_leading_lines_blank_has_none() -> None:
    result = detect_leading_lines(_blank())
    assert result["has_leading_lines"] is False
    assert result["line_count"] == 0


def test_leading_lines_detects_diagonal() -> None:
    # _MIN_LINE_COUNT requires at least 2 distinct merged lines.  Use a 200x200
    # image with two parallel diagonals separated by >15px perpendicular offset
    # so they are NOT collapsed by _merge_segments.
    img = _blank(200)
    cv2.line(img, (10, 10), (190, 190), 255, 2)   # main diagonal
    cv2.line(img, (40, 10), (190, 160), 255, 2)   # parallel, ~21px offset
    result = detect_leading_lines(img)
    assert result["has_leading_lines"] is True
    assert result["line_count"] >= 1
    assert abs(result["dominant_angle"] - 45) <= 15


# --- horizon --------------------------------------------------------------


def test_horizon_detects_horizontal_edge() -> None:
    img = _blank()
    img[50:, :] = 255  # hard horizontal edge at the middle
    result = detect_horizon(img)
    assert result["horizon_detected"] is True
    assert abs(result["horizon_y"] - 0.5) < 0.1
    assert result["is_level"] is True


def test_horizon_blank_not_detected() -> None:
    assert detect_horizon(_blank())["horizon_detected"] is False


def test_horizon_detects_boundary_partway_down() -> None:
    """A sharp horizontal boundary at 70% height must be detected near there."""
    img = _blank()
    img[70:, :] = 255
    result = detect_horizon(img)
    assert result["horizon_detected"] is True
    assert abs(result["horizon_y"] - 0.7) < 0.05
    assert result["is_level"] is True


def test_horizon_uniform_noisy_image_no_false_positive() -> None:
    """A uniform-tone image with mild sensor-like noise has no horizon; the
    row-energy peak must not clear the strength threshold on noise alone."""
    rng = np.random.default_rng(3)
    img = rng.integers(118, 138, size=(100, 100), dtype=np.uint8)
    result = detect_horizon(img)
    assert result["horizon_detected"] is False


def test_horizon_sky_above_water_below_detected() -> None:
    """Simulate a waterline photo: smooth gradient sky occupies the top half,
    a sharp horizontal edge separates it from textured 'water' below.
    The horizon must be detected even when stronger structural edges exist
    elsewhere in the frame."""
    rng = np.random.default_rng(42)
    img = np.zeros((200, 200), dtype=np.uint8)
    # Top 45%: uniform sky (value 180, low gradient)
    img[:90, :] = 180
    # Rows 90–94: horizon transition band
    for i, v in enumerate(range(180, 50, -26)):
        img[90 + i, :] = max(0, v)
    # Bottom 52%: textured water/ground (noisy, high gradient)
    img[95:, :] = rng.integers(30, 100, size=(105, 200), dtype=np.uint8)
    result = detect_horizon(img)
    assert result["horizon_detected"] is True, (
        "Horizon should be detected when smooth sky is above a sharp waterline"
    )
    assert result["horizon_y"] < 0.60, (
        f"Detected horizon at {result['horizon_y']:.2f} should be in the upper "
        f"portion (sky/water boundary ~0.45), not deep in the textured region"
    )


def test_horizon_structural_edge_no_sky_above_rejected() -> None:
    """A strong horizontal edge with consistently textured content ABOVE it
    (like a bridge deck or pier railing) must NOT be detected as a horizon.
    Uses a deterministic every-2-row alternating pattern to ensure the sky
    window is reliably noisy (not accidentally smooth due to random seed)."""
    img = np.zeros((200, 200), dtype=np.uint8)
    # Deterministic alternating-brightness rows (every 2 rows) → consistent
    # high Sobel_Y throughout; no accidentally smooth patches.
    for r in range(200):
        img[r, :] = 200 if (r // 2) % 2 == 0 else 50
    # Bright structural bar at 50%: surrounded by the same alternating texture.
    img[100, :] = 255
    result = detect_horizon(img)
    assert result["horizon_detected"] is False, (
        "A strong edge with consistently textured/busy content above it "
        "is NOT a horizon"
    )


# --- horizon tilt ---------------------------------------------------------


def _horizon_scene(
    tilt_deg: float = 0.0,
    height: int = 300,
    width: int = 400,
    y_frac: float = 0.45,
    seed: int = 42,
    bars: tuple[tuple[int, int, int, int], ...] = (),
) -> np.ndarray:
    """Uniform sky above a straight boundary tilted by *tilt_deg*, noisy ground
    below. Positive tilt drops the right-hand side. Each bar is
    (row, col_start, col_end, value) — an off-horizon edge such as a roofline.
    """
    rng = np.random.default_rng(seed)
    img = np.full((height, width), 180, dtype=np.uint8)
    ground = rng.integers(30, 100, size=(height, width), dtype=np.uint8)
    cols = np.arange(width)
    boundary = y_frac * height + np.tan(np.radians(tilt_deg)) * (cols - width / 2.0)
    mask = np.arange(height)[:, None] >= boundary[None, :]
    img[mask] = ground[mask]
    for row, c0, c1, value in bars:
        img[row : row + 3, c0:c1] = value
    return img


def test_horizon_tilt_recovers_known_angles() -> None:
    """A boundary drawn at a known angle must be measured back within 0.5°."""
    for expected in (-12.0, -5.0, -1.5, 1.5, 5.0, 8.0):
        result = detect_horizon(_horizon_scene(tilt_deg=expected))
        assert result["horizon_detected"] is True, f"{expected}° horizon not detected"
        assert result["tilt_reliable"] is True, (
            f"tilt of a clean {expected}° horizon should be reliable"
        )
        assert abs(result["tilt_angle"] - expected) < 0.5, (
            f"Expected ~{expected}°, measured {result['tilt_angle']}°"
        )


def test_horizon_level_edge_measures_zero_tilt() -> None:
    result = detect_horizon(_horizon_scene(tilt_deg=0.0))
    assert result["tilt_reliable"] is True
    assert abs(result["tilt_angle"]) < 0.5
    assert result["is_level"] is True


def test_horizon_tilt_ignores_off_horizon_edge() -> None:
    """REGRESSION: a level horizon with a dark silhouette high in one corner.

    The previous estimator compared the vertical-gradient argmax of the left
    half against the right half. Those are global maxima, so the silhouette
    captured one of them while the horizon captured the other, and the row gap
    between two unrelated features was reported as a ~22° tilt on a level
    photo. The fit must only consider edges near the detected horizon row.
    """
    for bar in ((55, 0, 200, 0), (55, 200, 400, 0)):  # left corner, then right
        result = detect_horizon(_horizon_scene(tilt_deg=0.0, bars=(bar,)))
        assert result["horizon_detected"] is True
        assert abs(result["tilt_angle"]) < 1.0, (
            f"A silhouette at row {bar[0]} must not tilt a level horizon; "
            f"got {result['tilt_angle']}°"
        )


def test_horizon_tilt_survives_off_horizon_edge_when_genuinely_tilted() -> None:
    """The same distractor must not corrupt a real 5° tilt either."""
    result = detect_horizon(_horizon_scene(tilt_deg=5.0, bars=((55, 0, 200, 0),)))
    assert result["tilt_reliable"] is True
    assert abs(result["tilt_angle"] - 5.0) < 0.5, (
        f"Expected ~5°, measured {result['tilt_angle']}°"
    )


def test_horizon_tilt_unreliable_when_bands_disagree() -> None:
    """Two competing edges at different rows on either side: no single line
    explains the strip, so the estimator must decline rather than guess."""
    result = detect_horizon(
        _horizon_scene(tilt_deg=0.0, bars=((50, 0, 200, 0), (95, 200, 400, 0)))
    )
    assert result["tilt_reliable"] is False
    assert result["tilt_angle"] == 0.0, (
        "A declined tilt must report 0.0, never a partial estimate"
    )


def test_horizon_undetected_reports_unreliable_tilt() -> None:
    result = detect_horizon(_blank())
    assert result["horizon_detected"] is False
    assert result["tilt_reliable"] is False
    assert result["tilt_angle"] is None


# --- symmetry -------------------------------------------------------------


def test_symmetry_mirrored_is_high() -> None:
    rng = np.random.default_rng(0)
    half = rng.integers(0, 256, (50, 50), dtype=np.uint8)
    img = np.hstack([half, np.fliplr(half)])
    result = analyze_symmetry(img)
    assert result["vertical"] > 0.95
    assert result["dominant_axis"] == "vertical"


def test_symmetry_asymmetric_is_low() -> None:
    img = np.zeros((50, 100), dtype=np.uint8)
    img[:, 50:] = 255
    result = analyze_symmetry(img)
    assert result["vertical"] < 0.1


def test_symmetry_solid_is_symmetric() -> None:
    img = np.full((50, 50), 128, dtype=np.uint8)
    result = analyze_symmetry(img)
    assert result["is_symmetric"] is True


# --- subject position -----------------------------------------------------


def test_subject_position_top_left() -> None:
    img = _with_square(top=15, left=15)
    assert estimate_subject_position(img)["region"] == "top-left"


def test_subject_position_center() -> None:
    img = _with_square(top=37, left=37)
    result = estimate_subject_position(img)
    assert result["region"] == "center"
    assert result["offset_from_center"] < 0.1


def test_subject_position_all_nine_regions() -> None:
    """Exact centroids in each cell of the 3x3 grid must map to the right
    region label. Uses Subject.from_saliency so the centroid is exact,
    not derived from image content."""
    cases = [
        ((0.15, 0.15), "top-left"),
        ((0.50, 0.15), "top-center"),
        ((0.85, 0.15), "top-right"),
        ((0.15, 0.50), "middle-left"),
        ((0.50, 0.50), "center"),
        ((0.85, 0.50), "middle-right"),
        ((0.15, 0.85), "bottom-left"),
        ((0.50, 0.85), "bottom-center"),
        ((0.85, 0.85), "bottom-right"),
    ]
    for centroid, expected in cases:
        subject = Subject.from_saliency(centroid)
        result = estimate_subject_position(_blank(), subject)
        assert result["region"] == expected, (
            f"centroid {centroid}: expected {expected!r}, got {result['region']!r}"
        )


# --- edge density ---------------------------------------------------------


def test_edge_density_blank_is_minimal() -> None:
    result = compute_edge_density(_blank())
    assert result["edge_density"] == 0.0
    assert result["busyness"] == "minimal"


def test_edge_density_checkerboard_is_busy() -> None:
    result = compute_edge_density(_checkerboard())
    assert result["edge_density"] > 0.1


def test_edge_density_regions_keys_and_range() -> None:
    result = compute_edge_density(_checkerboard())
    regions = result["regions"]
    assert set(regions) == {"top", "bottom", "left", "right", "center"}
    for value in regions.values():
        assert 0.0 <= value <= 1.0


def test_edge_density_regions_top_heavy() -> None:
    # All edges concentrated in the top half -> top region denser than bottom.
    img = _blank(size=100)
    img[:50, :] = _checkerboard(size=100, cell=5)[:50, :]
    regions = compute_edge_density(img)["regions"]
    assert regions["top"] > regions["bottom"]


def test_edge_density_regions_tiny_image_no_crash() -> None:
    tiny = np.array([[10, 200], [50, 90]], dtype=np.uint8)
    regions = compute_edge_density(tiny)["regions"]
    assert set(regions) == {"top", "bottom", "left", "right", "center"}
    for value in regions.values():
        assert 0.0 <= value <= 1.0


def test_edge_density_flat_image_zero_everywhere() -> None:
    """A fully flat (non-zero tone) image has no edges anywhere: overall
    density and every region must be exactly 0."""
    flat = np.full((90, 90), 128, dtype=np.uint8)
    result = compute_edge_density(flat)
    assert result["edge_density"] == 0.0
    for name, value in result["regions"].items():
        assert value == 0.0, f"region {name} expected 0.0, got {value}"


def test_edge_density_patch_confined_to_bottom_right() -> None:
    """Texture confined to the bottom-right corner must show up in the bottom
    and right regions only — top and left stay at exactly 0."""
    img = _blank(size=90)
    img[60:, 60:] = _checkerboard(size=30, cell=3)
    regions = compute_edge_density(img)["regions"]
    assert regions["top"] == 0.0
    assert regions["left"] == 0.0
    assert regions["bottom"] > 0.05
    assert regions["right"] > 0.05
    assert regions["bottom"] > regions["top"]
    assert regions["right"] > regions["left"]


# --- negative space -------------------------------------------------------


def test_negative_space_blank_is_full() -> None:
    result = estimate_negative_space(_blank())
    assert result["negative_space_ratio"] > 0.95
    assert result["has_significant_negative_space"] is True


def test_negative_space_busy_is_low() -> None:
    result = estimate_negative_space(_checkerboard())
    assert result["negative_space_ratio"] < 0.5


# --- small images & pipeline ---------------------------------------------


def test_modules_handle_tiny_image() -> None:
    tiny = np.array([[10, 200], [50, 90]], dtype=np.uint8)
    assert detect_horizon(tiny)["horizon_detected"] is False
    assert detect_leading_lines(tiny)["line_count"] == 0
    assert 0.0 <= analyze_symmetry(tiny)["vertical"] <= 1.0


def test_pipeline_structure() -> None:
    image = Image.fromarray(_with_square(top=20, left=20)).convert("RGB")
    result = run_composition_analysis(image)
    assert set(result) == {
        "rule_of_thirds",
        "leading_lines",
        "horizon",
        "symmetry",
        "subject_position",
        "edge_density",
        "negative_space",
    }


# --- Subject value object -------------------------------------------------


def test_subject_from_saliency_is_centroid_only() -> None:
    subject = Subject.from_saliency((0.3, 0.7))
    assert subject.centroid == (0.3, 0.7)
    assert subject.bbox is None
    assert subject.mask is None
    assert subject.has_mask is False
    assert subject.source == "saliency"


def test_subject_centroid_from_bbox_when_no_mask() -> None:
    subject = Subject.from_detection(
        (0.2, 0.4, 0.6, 0.8), confidence=0.9, label="person"
    )
    cx, cy = subject.centroid  # bbox center
    assert abs(cx - 0.4) < 1e-9
    assert abs(cy - 0.6) < 1e-9
    assert subject.source == "detector"
    assert subject.has_mask is False


def test_subject_centroid_from_mask_center_of_mass() -> None:
    mask = np.zeros((100, 100), dtype=bool)
    mask[60:81, 60:81] = True  # block centered near (0.7, 0.7)
    subject = Subject.from_detection(
        (0.0, 0.0, 1.0, 1.0), confidence=0.8, label="cat", mask=mask
    )
    cx, cy = subject.centroid
    assert abs(cx - 0.70) < 0.02
    assert abs(cy - 0.70) < 0.02
    assert subject.has_mask is True


# --- rule of thirds with subject -----------------------------------------


def test_rule_of_thirds_uses_subject_centroid() -> None:
    subject = Subject.from_saliency((1 / 3, 1 / 3))
    result = analyze_rule_of_thirds(_blank(), subject)
    assert result["follows_rule"] is True
    assert result["score"] > 0.6
    assert result["source"] == "saliency"


def test_rule_of_thirds_centered_subject_fails_with_subject() -> None:
    subject = Subject.from_detection(
        (0.4, 0.4, 0.6, 0.6), confidence=0.9, label="person"
    )
    result = analyze_rule_of_thirds(_blank(), subject)
    assert result["follows_rule"] is False
    assert result["score"] < 0.3
    assert result["source"] == "detector"


# --- subject position with subject ---------------------------------------


def test_subject_position_reports_detector_fields() -> None:
    subject = Subject.from_detection(
        (0.0, 0.0, 0.3, 0.3), confidence=0.77, label="bird"
    )
    result = estimate_subject_position(_blank(), subject)
    assert result["region"] == "top-left"
    assert result["label"] == "bird"
    assert result["confidence"] == 0.77
    assert result["has_mask"] is False
    assert result["source"] == "detector"
    assert result["bbox"] == {"x0": 0.0, "y0": 0.0, "x1": 0.3, "y1": 0.3}


def test_subject_position_fallback_has_no_bbox() -> None:
    result = estimate_subject_position(_with_square(top=15, left=15))
    assert result["source"] == "saliency"
    assert result["bbox"] is None
    assert result["label"] is None


# --- negative space subject exclusion ------------------------------------


def test_negative_space_excludes_subject_mask() -> None:
    blank = _blank(100)  # entirely flat -> raw ratio ~1.0
    mask = np.zeros((100, 100), dtype=bool)
    mask[:50, :50] = True  # subject covers a quarter of the frame
    subject = Subject.from_detection(
        (0.0, 0.0, 0.5, 0.5), confidence=0.9, label="person", mask=mask
    )
    result = estimate_negative_space(blank, subject)
    assert result["negative_space_ratio"] > 0.95
    assert abs(result["subject_excluded_ratio"] - 0.75) < 0.02
    assert result["subject_excluded_ratio"] < result["negative_space_ratio"]


def test_negative_space_falls_back_to_bbox_without_mask() -> None:
    blank = _blank(100)
    subject = Subject.from_detection(
        (0.0, 0.0, 0.5, 0.5), confidence=0.9, label="person"
    )
    result = estimate_negative_space(blank, subject)
    assert abs(result["subject_excluded_ratio"] - 0.75) < 0.03
    assert result["subject_excluded_ratio"] < result["negative_space_ratio"]


def test_negative_space_unchanged_without_subject() -> None:
    blank = _blank(100)
    result = estimate_negative_space(blank)
    assert result["subject_excluded_ratio"] == result["negative_space_ratio"]


def test_negative_space_unchanged_for_saliency_only_subject() -> None:
    blank = _blank(100)
    subject = Subject.from_saliency((0.4, 0.4))  # no footprint
    result = estimate_negative_space(blank, subject)
    assert result["subject_excluded_ratio"] == result["negative_space_ratio"]


# --- subject localization (fallback path) --------------------------------


def test_locate_subject_returns_valid_subject() -> None:
    # In test/CI the detector weights are typically unavailable, so this
    # exercises the saliency fallback. Either way we must get a usable Subject.
    rgb = np.dstack([_with_square(top=20, left=20)] * 3)
    subject = locate_subject(rgb)
    assert isinstance(subject, Subject)
    cx, cy = subject.centroid
    assert 0.0 <= cx <= 1.0
    assert 0.0 <= cy <= 1.0
    assert subject.source in {"detector", "vlm", "saliency"}


# --- VLMSubjectLocator (mocked API, no network) ---------------------------


class _FakeMessages:
    def __init__(self, text: str) -> None:
        self._text = text

    def create(self, **kwargs):  # noqa: ANN003 - mirrors anthropic SDK signature
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


def _rgb_image(size: int = 40) -> np.ndarray:
    return np.zeros((size, size, 3), dtype=np.uint8)


def test_vlm_locator_parses_valid_json() -> None:
    text = '{"label": "dog", "bbox": [0.1, 0.2, 0.6, 0.8], "confidence": 0.87}'
    locator = VLMSubjectLocator(client=_FakeClient(text))
    result = locator.locate(_rgb_image())
    assert result is not None
    assert result.subject.source == "vlm"
    assert result.subject.label == "dog"
    assert result.subject.confidence == 0.87
    assert result.subject.bbox == (0.1, 0.2, 0.6, 0.8)
    assert result.diagnostics["vlm_confidence"] == 0.87


def test_vlm_locator_tolerates_single_quoted_json() -> None:
    text = "Sure, here you go: {'label': 'tree', 'bbox': [0.0, 0.0, 1.0, 1.0], 'confidence': 0.3}"
    locator = VLMSubjectLocator(client=_FakeClient(text))
    result = locator.locate(_rgb_image())
    assert result is not None
    assert result.subject.label == "tree"


def test_vlm_locator_rejects_invalid_bbox() -> None:
    text = '{"label": "dog", "bbox": [0.9, 0.2, 0.1, 0.8], "confidence": 0.9}'
    locator = VLMSubjectLocator(client=_FakeClient(text))
    assert locator.locate(_rgb_image()) is None


def test_vlm_locator_rejects_unparseable_response() -> None:
    locator = VLMSubjectLocator(client=_FakeClient("not json at all"))
    assert locator.locate(_rgb_image()) is None


def test_vlm_locator_returns_none_on_api_exception() -> None:
    locator = VLMSubjectLocator(client=_RaisingClient())
    assert locator.locate(_rgb_image()) is None


def test_vlm_locator_returns_none_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    locator = VLMSubjectLocator()
    assert locator.locate(_rgb_image()) is None


# --- CompositeSubjectLocator tier selection --------------------------------


class _StubLocator:
    def __init__(self, result: LocatorResult | None) -> None:
        self._result = result

    def locate(self, rgb: np.ndarray) -> LocatorResult | None:
        return self._result


def _detector_result(confidence: float, second: float) -> LocatorResult:
    subject = Subject.from_detection(
        (0.1, 0.1, 0.5, 0.5), confidence=confidence, label="dog"
    )
    return LocatorResult(
        subject=subject,
        diagnostics={"top_confidence": confidence, "second_confidence": second},
    )


def _vlm_result(confidence: float) -> LocatorResult:
    subject = Subject.from_detection(
        (0.2, 0.2, 0.6, 0.6), confidence=confidence, label="cat", source="vlm"
    )
    return LocatorResult(subject=subject, diagnostics={"vlm_confidence": confidence})


def test_composite_uses_detector_when_gate_passes() -> None:
    # top=0.5 beats 2nd=0.1 by 5x (> 3x) and clears the 0.10 floor.
    yolo = _StubLocator(_detector_result(confidence=0.5, second=0.1))
    vlm = _StubLocator(_vlm_result(confidence=0.9))
    saliency = _StubLocator(LocatorResult(subject=Subject.from_saliency((0.5, 0.5))))
    composite = CompositeSubjectLocator(yolo=yolo, vlm=vlm, saliency=saliency)

    result = composite.locate(_rgb_image())
    assert result.subject.source == "detector"
    assert composite.last_decision["tier"] == "detector"


def test_composite_escalates_to_vlm_when_ratio_gate_fails() -> None:
    # top=0.12 vs 2nd=0.10 -> ratio ~1.2x, well below the 3x gate.
    yolo = _StubLocator(_detector_result(confidence=0.12, second=0.10))
    vlm = _StubLocator(_vlm_result(confidence=0.9))
    saliency = _StubLocator(LocatorResult(subject=Subject.from_saliency((0.5, 0.5))))
    composite = CompositeSubjectLocator(yolo=yolo, vlm=vlm, saliency=saliency)

    result = composite.locate(_rgb_image())
    assert result.subject.source == "vlm"
    assert composite.last_decision["tier"] == "vlm"
    assert "escalated to VLM" in composite.last_decision["reason"]


def test_composite_escalates_to_vlm_when_absolute_floor_fails() -> None:
    # top=0.09 never clears the 0.10 absolute floor, even with no competitor.
    yolo = _StubLocator(_detector_result(confidence=0.09, second=0.0))
    vlm = _StubLocator(_vlm_result(confidence=0.9))
    saliency = _StubLocator(LocatorResult(subject=Subject.from_saliency((0.5, 0.5))))
    composite = CompositeSubjectLocator(yolo=yolo, vlm=vlm, saliency=saliency)

    result = composite.locate(_rgb_image())
    assert result.subject.source == "vlm"


def test_composite_falls_to_saliency_when_vlm_confidence_too_low() -> None:
    yolo = _StubLocator(None)  # no detection at all
    vlm = _StubLocator(_vlm_result(confidence=0.25))  # below the 0.4 floor
    saliency = _StubLocator(LocatorResult(subject=Subject.from_saliency((0.5, 0.5))))
    composite = CompositeSubjectLocator(yolo=yolo, vlm=vlm, saliency=saliency)

    result = composite.locate(_rgb_image())
    assert result.subject.source == "saliency"
    assert composite.last_decision["tier"] == "saliency"


def test_composite_falls_to_saliency_when_vlm_returns_none() -> None:
    yolo = _StubLocator(None)
    vlm = _StubLocator(None)
    saliency = _StubLocator(LocatorResult(subject=Subject.from_saliency((0.5, 0.5))))
    composite = CompositeSubjectLocator(yolo=yolo, vlm=vlm, saliency=saliency)

    result = composite.locate(_rgb_image())
    assert result.subject.source == "saliency"


def test_composite_survives_locator_exceptions() -> None:
    class _ExplodingLocator:
        def locate(self, rgb: np.ndarray) -> LocatorResult | None:
            raise RuntimeError("boom")

    saliency = _StubLocator(LocatorResult(subject=Subject.from_saliency((0.5, 0.5))))
    composite = CompositeSubjectLocator(
        yolo=_ExplodingLocator(), vlm=_ExplodingLocator(), saliency=saliency
    )

    result = composite.locate(_rgb_image())
    assert result.subject.source == "saliency"


# --- negative space: noise regression (issue #1) ----------------------------


def test_negative_space_flat_noisy_image_is_high() -> None:
    """Regression for the JPEG-noise bug.

    A flat image with realistic per-pixel noise (simulates JPEG-compressed sky)
    must report a high negative_space_ratio. Before the GaussianBlur fix, the
    Sobel on raw noise inflated gradient magnitudes above _FLAT_THRESHOLD and
    the ratio came back as low as 0.18 on what was visually ~80% empty sky.
    """
    rng = np.random.default_rng(42)
    noisy = rng.integers(120, 137, size=(100, 100), dtype=np.uint8)
    result = estimate_negative_space(noisy)
    assert result["negative_space_ratio"] >= 0.80, (
        f"Flat noisy image should be mostly negative space, "
        f"got {result['negative_space_ratio']:.3f}"
    )


def test_negative_space_checkerboard_is_dense() -> None:
    """High-frequency texture should have low negative space even after blur."""
    checker = _checkerboard(size=100, cell=3)
    result = estimate_negative_space(checker)
    assert result["negative_space_ratio"] <= 0.30, (
        f"Checkerboard should read as dense, got {result['negative_space_ratio']:.3f}"
    )


def test_negative_space_large_flat_region_scores_high() -> None:
    """An image that is mostly flat (open sky) with one textured region (subject)
    must read as significant negative space — the photographic expectation."""
    img = np.full((100, 100), 180, dtype=np.uint8)  # flat sky
    img[40:70, 40:70] = _checkerboard(size=30, cell=3)  # small textured subject
    result = estimate_negative_space(img)
    assert result["negative_space_ratio"] >= 0.75, (
        f"Mostly-flat image should have high negative space, "
        f"got {result['negative_space_ratio']:.3f}"
    )


# --- leading lines: architectural / near-vertical (issue #4 verification) ----


def test_leading_lines_detects_near_vertical() -> None:
    """Near-vertical converging lines (tower edges, architectural shots from below)
    must be detected. This is the key architectural case that was failing."""
    img = np.zeros((200, 100), dtype=np.uint8)
    # Two converging edges: bottom-left to top-center, bottom-right to top-center
    cv2.line(img, (10, 199), (50, 0), 255, 2)
    cv2.line(img, (90, 199), (50, 0), 255, 2)
    result = detect_leading_lines(img)
    assert result["has_leading_lines"] is True, (
        "Near-vertical converging lines were not detected — "
        "check threshold and maxLineGap in HoughLinesP"
    )
    assert result["line_count"] >= 2


def test_leading_lines_converge_to_subject_centroid() -> None:
    """NEW APPROACH: diagonals count as leading lines only when they converge
    toward the subject. Two diagonals meeting at the top-center vanishing point
    (100, 0) are detected when a Subject sits there, because their extensions
    pass within 15% of the frame diagonal of the subject centroid."""
    img = np.zeros((200, 200), dtype=np.uint8)
    cv2.line(img, (0, 199), (100, 0), 255, 2)   # left edge converging up
    cv2.line(img, (199, 199), (100, 0), 255, 2)  # right edge converging up
    # Subject at the vanishing point (normalized (0.5, 0.0)).
    subject = Subject.from_saliency((0.5, 0.0))
    result = detect_leading_lines(img, subject)
    assert result["has_leading_lines"] is True
    assert result["line_count"] >= 2


def test_leading_lines_reject_when_not_converging_to_subject() -> None:
    """NEW APPROACH: the same two diagonals converging at top-center do NOT
    count when the subject is bottom-center — the lines lead away from the
    subject, so the convergence test (and thus has_leading_lines) fails."""
    img = np.zeros((200, 200), dtype=np.uint8)
    cv2.line(img, (0, 199), (100, 0), 255, 2)
    cv2.line(img, (199, 199), (100, 0), 255, 2)
    subject = Subject.from_saliency((0.5, 0.95))  # bottom-center, away from VP
    result = detect_leading_lines(img, subject)
    assert result["has_leading_lines"] is False


def test_leading_lines_longest_first() -> None:
    """Lines must be sorted longest-first so the overlay always shows the most
    significant lines when line_count exceeds the 20-line display cap.

    NEW APPROACH: all test lines must clear the filter chain (>15° from
    horizontal, >=20% of the frame diagonal) and pass through the frame center
    (the (0.5, 0.5) fallback used when no Subject is supplied), so they qualify
    as converging leading lines."""
    img = np.zeros((200, 200), dtype=np.uint8)
    cv2.line(img, (0, 0), (199, 199), 255, 2)    # diagonal through center (~281px)
    cv2.line(img, (50, 199), (150, 0), 255, 2)   # steep diagonal through center (~222px)
    cv2.line(img, (100, 0), (100, 199), 255, 2)  # vertical through center (~199px)
    result = detect_leading_lines(img)
    assert result["has_leading_lines"] is True
    lines = result["lines"]
    for i in range(len(lines) - 1):
        assert lines[i]["length"] >= lines[i + 1]["length"], (
            f"Lines not sorted by length: index {i} ({lines[i]['length']:.0f}) "
            f"< index {i+1} ({lines[i+1]['length']:.0f})"
        )


def test_leading_lines_filters_short_and_horizontal() -> None:
    """NEW APPROACH: the LSD filter chain rejects texture noise and horizon
    candidates. Short fragments (below 20% of the frame diagonal) and the
    near-horizontal edge are both filtered out, leaving only the long diagonal
    that runs through the frame center — so the result reports a leading line
    in the diagonal direction and never a horizontal one.
    """
    img = np.zeros((200, 200), dtype=np.uint8)
    # Near-horizontal edge — a horizon candidate, must be filtered by the angle gate.
    cv2.line(img, (20, 100), (180, 100), 255, 2)
    # Short fragments (~35px << 20% of the ~283px diagonal) — texture noise.
    cv2.line(img, (30, 108), (65, 108), 255, 2)
    cv2.line(img, (80, 108), (115, 108), 255, 2)
    cv2.line(img, (130, 108), (165, 108), 255, 2)
    # Long diagonal through the center — the only genuine leading line.
    cv2.line(img, (10, 10), (190, 190), 255, 2)
    result = detect_leading_lines(img)
    assert result["has_leading_lines"] is True
    assert abs(result["dominant_angle"] - 45) <= 15
    # No surviving line may be near-horizontal (the horizon edge was filtered).
    for ln in result["lines"]:
        angle_from_h = min(ln["angle"] % 180, 180 - (ln["angle"] % 180))
        assert angle_from_h > 15, (
            f"A near-horizontal line ({ln['angle']}°) leaked past the angle filter"
        )


def test_leading_lines_rejects_small_region_cluster() -> None:
    """A dense cluster of segments confined to one small region (texture,
    bark, leaves) must NOT count as leading lines — real leading lines span
    a meaningful portion of the frame."""
    img = np.zeros((400, 400), dtype=np.uint8)
    # Four segments at spread angles, all inside an ~80x80 region near the
    # center. Region bbox diagonal ≈ 99px < 20% of frame diagonal (113px).
    cv2.line(img, (165, 180), (235, 180), 255, 2)  # horizontal
    cv2.line(img, (200, 165), (200, 235), 255, 2)  # vertical
    cv2.line(img, (165, 165), (235, 235), 255, 2)  # diagonal
    cv2.line(img, (165, 235), (235, 165), 255, 2)  # anti-diagonal
    result = detect_leading_lines(img)
    assert result["has_leading_lines"] is False, (
        f"Small-region cluster should be rejected as texture, but got "
        f"{result['line_count']} lines"
    )
    assert result["line_count"] == 0


def test_leading_lines_vp_coherence_converging_pass() -> None:
    """Lines converging toward a common vanishing point should pass the VP
    coherence check — this is the prototype of a 'real' leading-line photo."""
    # Four lines radiating from the right edge (vanishing point at ~(390, 200)).
    img = _blank(400)
    cv2.line(img, (10, 50),  (390, 200), 255, 2)   # from top-left → VP
    cv2.line(img, (10, 150), (390, 200), 255, 2)   # from mid-left  → VP
    cv2.line(img, (10, 250), (390, 200), 255, 2)   # from mid-left  → VP
    cv2.line(img, (10, 350), (390, 200), 255, 2)   # from bot-left  → VP
    result = detect_leading_lines(img)
    assert result["has_leading_lines"] is True, (
        "Converging lines sharing a vanishing point must be detected as leading lines"
    )


def test_leading_lines_vp_coherence_chaotic_reject() -> None:
    """Lines spanning the frame but at scattered, non-converging angles
    (like a building facade with columns + windows) must be rejected by the
    VP coherence check even though they pass the spread gate."""
    # Simulate a building facade: horizontal window lines + vertical columns
    # spanning the full frame — intersections will be scattered uniformly.
    img = np.zeros((400, 600), dtype=np.uint8)
    # Horizontal window rows
    for y in (60, 130, 200, 270, 340):
        cv2.line(img, (10, y), (590, y), 255, 2)
    # Vertical columns
    for x in (80, 200, 320, 440, 560):
        cv2.line(img, (x, 10), (x, 390), 255, 2)
    result = detect_leading_lines(img)
    assert result["has_leading_lines"] is False, (
        "Grid-like architectural pattern must be rejected by VP coherence check"
    )


# --- symmetry: axis labeling verification (issue #5) -------------------------


def test_symmetry_vertical_axis_means_left_right_mirror() -> None:
    """'vertical' in the API means the axis of symmetry is vertical, i.e.
    left-right mirror symmetry. A left-bright / right-dark image must have
    LOW vertical score and HIGH horizontal score."""
    img = np.zeros((100, 100), dtype=np.uint8)
    img[:, :50] = 200  # left half bright, right half dark
    result = analyze_symmetry(img)
    assert result["vertical"] < 0.25, (
        f"Left/right-split image should have low vertical (L-R) symmetry, "
        f"got {result['vertical']:.3f}"
    )
    assert result["horizontal"] > 0.95, (
        f"Left/right-split image should have high horizontal (T-B) symmetry, "
        f"got {result['horizontal']:.3f}"
    )
    assert result["dominant_axis"] == "horizontal"


def test_symmetry_horizontal_axis_means_top_bottom_mirror() -> None:
    """'horizontal' means the axis runs horizontally, i.e. top-bottom mirror.
    A top-bright / bottom-dark image must have LOW horizontal score."""
    img = np.zeros((100, 100), dtype=np.uint8)
    img[:50, :] = 200  # top half bright, bottom half dark
    result = analyze_symmetry(img)
    assert result["horizontal"] < 0.25, (
        f"Top/bottom-split image should have low horizontal (T-B) symmetry, "
        f"got {result['horizontal']:.3f}"
    )
    assert result["vertical"] > 0.95, (
        f"Top/bottom-split image should have high vertical (L-R) symmetry, "
        f"got {result['vertical']:.3f}"
    )
    assert result["dominant_axis"] == "vertical"


def test_symmetry_similar_tone_different_structure_is_not_symmetric() -> None:
    """Regression: two halves with similar AVERAGE brightness but totally
    different structure (e.g. flat sky vs textured stairs) must NOT score
    as symmetric. The old mean-brightness-diff metric couldn't tell "same
    average tone" from "actually mirrors" and scored this ~0.9 (falsely
    'STRONG'); SSIM must score it low."""
    rng = np.random.default_rng(1)
    img = np.zeros((120, 120), dtype=np.uint8)
    img[:60, :] = 150  # flat top half (sky-like)
    img[60:, :] = rng.integers(100, 200, size=(60, 120), dtype=np.uint8)  # textured bottom, similar avg tone
    result = analyze_symmetry(img)
    assert result["horizontal"] < 0.3, (
        f"Similar-tone/different-structure halves should score LOW on "
        f"symmetry, got {result['horizontal']:.3f}"
    )


def test_symmetry_reports_both_scores() -> None:
    """Both vertical and horizontal scores must always be present in the output,
    even when one is clearly dominant — they're both used in the frontend."""
    result = analyze_symmetry(_blank())
    assert "vertical" in result
    assert "horizontal" in result
    assert "dominant_axis" in result
    assert result["dominant_axis"] in {"vertical", "horizontal"}
