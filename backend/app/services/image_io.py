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


def open_image(data: bytes) -> Image.Image:
    """Decode bytes into a PIL image, validating that it's a real image.

    Pillow's `verify()` consumes the file object, so we open twice: once to
    verify integrity, once to return a usable image.

    Applies the EXIF orientation tag (common on phone photos, which often
    store the sensor's native landscape buffer plus a tag saying "rotate
    this for display") so `.size` and every downstream consumer — vision
    metrics, composition geometry, the image sent to the AI — see the photo
    the way it actually displays, not the raw unrotated buffer.
    """
    try:
        Image.open(io.BytesIO(data)).verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageValidationError("File is not a valid image.") from exc

    image = Image.open(io.BytesIO(data))
    if image.format not in ALLOWED_FORMATS:
        raise ImageValidationError(f"Unsupported image format: {image.format}.")

    original_format = image.format
    image = ImageOps.exif_transpose(image)
    image.format = original_format
    return image


def describe_image(image: Image.Image, *, filename: str, size_bytes: int) -> dict:
    """Extract basic, display-ready metadata about an image."""
    width, height = image.size
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
