"""Loading and validating uploaded images.

Kept framework-agnostic: takes raw bytes, returns PIL images / plain dicts, and
raises `ImageValidationError` on bad input. The API layer translates that into
an HTTP response.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

# Formats we accept. EXIF lives mainly in JPEG/TIFF, but we allow common
# web formats too so users can analyze anything.
ALLOWED_FORMATS: set[str] = {"JPEG", "PNG", "WEBP", "TIFF", "BMP"}
ALLOWED_CONTENT_TYPES: set[str] = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/tiff",
    "image/bmp",
}


# EXIF orientation tag; values 5-8 are the 90-degree rotations.
_ORIENTATION_TAG = 0x0112


class ImageValidationError(Exception):
    """Raised when an upload is not a usable image."""


def validate_upload(data: bytes, content_type: str | None, max_bytes: int) -> None:
    """Cheap, fail-fast checks before we try to decode the image."""
    if not data:
        raise ImageValidationError("Uploaded file is empty.")
    if len(data) > max_bytes:
        mb = max_bytes / (1024 * 1024)
        raise ImageValidationError(f"Image exceeds the {mb:.0f}MB size limit.")
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise ImageValidationError(f"Unsupported content type: {content_type}.")


def read_display_dimensions(data: bytes) -> tuple[int, int] | None:
    """Original width/height as displayed, read from the header without decoding.

    Needed because `open_image` may hand back a scaled-down decode: the reported
    dimensions must describe the photograph the user uploaded, not our working
    copy. Parsing the header costs nothing — no pixels are decoded.
    """
    try:
        with Image.open(io.BytesIO(data)) as probe:
            width, height = probe.size
            orientation = probe.getexif().get(_ORIENTATION_TAG)
    except (UnidentifiedImageError, OSError):
        return None
    # Orientations 5-8 are the 90-degree rotations, which swap the axes.
    if orientation in (5, 6, 7, 8):
        return height, width
    return width, height


def open_image(data: bytes, *, decode_max_edge: int | None = None) -> Image.Image:
    """Decode bytes into a PIL image, validating that it's a real image.

    Pillow's `verify()` consumes the file object, so we open twice: once to
    verify integrity, once to return a usable image.

    Applies the EXIF orientation tag (common on phone photos, which often
    store the sensor's native landscape buffer plus a tag saying "rotate
    this for display") so `.size` and every downstream consumer — vision
    metrics, composition geometry, the image sent to the AI — see the photo
    the way it actually displays, not the raw unrotated buffer.

    ``decode_max_edge`` asks libjpeg to decode at a reduced scale rather than
    decoding in full and shrinking afterwards. Peak RSS for one 26MP frame drops
    from ~238MB to ~86MB, which is the difference between fitting a 512MB
    instance and being OOM-killed by it. Pillow picks the smallest power-of-two
    scale still at or above the requested size, so the result is never smaller
    than the 1920px every downstream metric caps itself at — no accuracy is
    traded for the memory. It is a no-op for formats without scaled decoding
    (PNG, WEBP, BMP), which is why downscale_to_megapixels still backstops it.
    """
    try:
        Image.open(io.BytesIO(data)).verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageValidationError("File is not a valid image.") from exc

    image = Image.open(io.BytesIO(data))
    if image.format not in ALLOWED_FORMATS:
        raise ImageValidationError(f"Unsupported image format: {image.format}.")

    original_format = image.format
    if decode_max_edge and decode_max_edge > 0:
        # Must precede any pixel access, including exif_transpose.
        image.draft("RGB", (decode_max_edge, decode_max_edge))
    image = ImageOps.exif_transpose(image)
    image.format = original_format
    return image


def downscale_to_megapixels(image: Image.Image, max_megapixels: float) -> Image.Image:
    """Shrink ``image`` so it holds at most ``max_megapixels``, preserving aspect.

    Every metric downstream is normalized or scale-independent and already caps
    its own working resolution at 1920px, so this costs no accuracy. What it
    buys is a bound on peak memory: the upload limit is measured in bytes, and
    bytes say nothing about pixel count — a 3MB JPEG can decode to 100MP. Left
    unbounded, one large upload can push RSS past a small instance's ceiling
    and get the process OOM-killed.

    Returns the original object when it already fits, or when the cap is
    disabled with a non-positive value.
    """
    if max_megapixels <= 0:
        return image

    width, height = image.size
    megapixels = (width * height) / 1_000_000
    if megapixels <= max_megapixels:
        return image

    scale = (max_megapixels / megapixels) ** 0.5
    return image.resize(
        (max(1, int(width * scale)), max(1, int(height * scale))), Image.LANCZOS
    )


def describe_image(
    image: Image.Image,
    *,
    filename: str,
    size_bytes: int,
    dimensions: tuple[int, int] | None = None,
) -> dict:
    """Extract basic, display-ready metadata about an image.

    ``dimensions`` overrides the reported size. `open_image` may return a
    scaled-down decode (see its ``decode_max_edge``), and this metadata is
    meant to describe the uploaded photograph, not our working copy.
    """
    width, height = dimensions or image.size
    megapixels = round((width * height) / 1_000_000, 1)
    return {
        "filename": filename,
        "format": image.format,
        "mode": image.mode,
        "width": width,
        "height": height,
        "megapixels": megapixels,
        "aspect_ratio": round(width / height, 2) if height else 0.0,
        "size_bytes": size_bytes,
    }
