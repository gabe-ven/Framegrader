import numpy as np
from PIL import Image

from app.services.vision.analysis_pipeline import run_vision_analysis
from app.services.vision.brightness import compute_brightness
from app.services.vision.colors import color_samples, dominant_colors
from app.services.vision.contrast import compute_contrast
from app.services.vision.dynamic_range import compute_dynamic_range
from app.services.vision.histogram import compute_histogram
from app.services.vision.sharpness import compute_sharpness


# --- brightness -----------------------------------------------------------


def test_brightness_solid_color() -> None:
    white = np.full((10, 10, 3), 255, dtype=np.uint8)
    black = np.zeros((10, 10, 3), dtype=np.uint8)
    assert compute_brightness(white) == 255.0
    assert compute_brightness(black) == 0.0


def test_brightness_handles_grayscale_2d() -> None:
    gray = np.full((8, 8), 128, dtype=np.uint8)
    assert compute_brightness(gray) == 128.0


# --- contrast -------------------------------------------------------------


def test_contrast_uniform_is_zero() -> None:
    uniform = np.full((10, 10, 3), 100, dtype=np.uint8)
    assert compute_contrast(uniform) == 0.0


def test_contrast_high_for_split_image() -> None:
    img = np.zeros((10, 10), dtype=np.uint8)
    img[:, 5:] = 255
    assert compute_contrast(img) > 100.0


# --- sharpness ------------------------------------------------------------


def test_sharpness_uniform_is_zero() -> None:
    uniform = np.full((10, 10, 3), 100, dtype=np.uint8)
    assert compute_sharpness(uniform) == 0.0


def test_sharpness_edges_higher_than_blur() -> None:
    sharp = np.zeros((20, 20), dtype=np.uint8)
    sharp[:, 10:] = 255  # hard edge
    blurry = np.tile(np.linspace(0, 255, 20, dtype=np.uint8), (20, 1))  # gradient
    assert compute_sharpness(sharp) > compute_sharpness(blurry)


# --- dominant colors ------------------------------------------------------


def test_dominant_colors_solid_is_single() -> None:
    red = np.full((10, 10, 3), 0, dtype=np.uint8)
    red[:, :, 0] = 255
    colors = dominant_colors(red, k=5)
    assert len(colors) == 1
    assert colors[0]["hex"] == "#ff0000"
    assert colors[0]["proportion"] == 1.0


def test_dominant_colors_two_tone_ordering() -> None:
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    img[:7] = [255, 255, 255]  # 70% white
    colors = dominant_colors(img, k=5)
    assert len(colors) == 2
    assert colors[0]["proportion"] >= colors[1]["proportion"]
    assert abs(colors[0]["proportion"] - 0.7) < 0.01


# --- color samples ---------------------------------------------------------


def test_color_samples_capped_and_in_range() -> None:
    img = np.random.randint(0, 256, (64, 64, 3), dtype=np.uint8)
    samples = color_samples(img, n=200)
    assert len(samples) == 200
    for r, g, b in samples:
        assert 0 <= r <= 255
        assert 0 <= g <= 255
        assert 0 <= b <= 255


def test_color_samples_smaller_than_cap_returns_all_pixels() -> None:
    img = np.full((5, 5, 3), 128, dtype=np.uint8)
    samples = color_samples(img, n=200)
    assert len(samples) == 25
    assert all(px == [128, 128, 128] for px in samples)


def test_color_samples_one_pixel_image() -> None:
    tiny = np.array([[[10, 20, 30]]], dtype=np.uint8)
    samples = color_samples(tiny)
    assert samples == [[10, 20, 30]]


# --- histogram ------------------------------------------------------------


def test_histogram_counts_sum_to_pixels() -> None:
    img = np.random.randint(0, 256, (16, 16, 3), dtype=np.uint8)
    hist = compute_histogram(img, bins=256)
    assert hist["bins"] == 256
    for channel in ("r", "g", "b", "luminance"):
        assert len(hist[channel]) == 256
        assert sum(hist[channel]) == 16 * 16


def test_histogram_luminance_is_per_pixel_not_marginal() -> None:
    """A flat mid-gray image: (128, 128, 128) has real luminance 128.
    A marginal recombination would land on the same value here by
    coincidence (r == g == b), so use two flat halves with different, very
    saturated colors instead — a case where per-channel marginals and true
    per-pixel luminance genuinely diverge."""
    top = np.full((8, 16, 3), (255, 0, 0), dtype=np.uint8)  # pure red
    bottom = np.full((8, 16, 3), (0, 0, 255), dtype=np.uint8)  # pure blue
    img = np.concatenate([top, bottom], axis=0)
    hist = compute_histogram(img, bins=256)

    # True per-pixel luminance: red -> ~76, blue -> ~29 (Rec. 601 weights).
    # Half the pixels each. A marginal-recombination approach would instead
    # produce one shared bin (fully-correlated per-channel peaks summed as
    # if independent), which does not match either real value. peak_bins is
    # sorted by bin index (ascending luminance), so blue's lower value comes
    # first regardless of its position in the image.
    peak_bins = [i for i, c in enumerate(hist["luminance"]) if c > 0]
    assert len(peak_bins) == 2
    assert 27 <= peak_bins[0] <= 31
    assert 74 <= peak_bins[1] <= 78


# --- dynamic range --------------------------------------------------------


def test_dynamic_range_gradient() -> None:
    gradient = np.tile(np.linspace(0, 255, 256, dtype=np.uint8), (10, 1))
    dr = compute_dynamic_range(gradient)
    assert dr["high"] > dr["low"]
    assert dr["range"] > 200
    assert dr["stops"] > 0


def test_dynamic_range_flat_is_zero_stops() -> None:
    flat = np.full((10, 10), 128, dtype=np.uint8)
    dr = compute_dynamic_range(flat)
    assert dr["range"] == 0.0
    assert dr["stops"] == 0.0


# --- small images & pipeline ---------------------------------------------


def test_metrics_handle_one_pixel_image() -> None:
    tiny = np.array([[[120, 60, 30]]], dtype=np.uint8)
    assert compute_brightness(tiny) >= 0
    assert compute_sharpness(tiny) == 0.0
    assert len(dominant_colors(tiny)) == 1


def test_pipeline_structure_and_orientation() -> None:
    image = Image.new("RGB", (40, 20), (90, 90, 90))
    result = run_vision_analysis(image)

    assert set(result) == {
        "brightness",
        "contrast",
        "sharpness",
        "dominant_colors",
        "color_samples",
        "histogram",
        "dynamic_range",
        "dimensions",
        "orientation",
    }
    assert result["dimensions"] == {"width": 40, "height": 20, "aspect_ratio": 2.0}
    assert result["orientation"] == "landscape"


def test_pipeline_handles_grayscale_image() -> None:
    image = Image.new("L", (20, 20), 128)
    result = run_vision_analysis(image)
    assert result["orientation"] == "square"
    assert result["brightness"] == 128.0
