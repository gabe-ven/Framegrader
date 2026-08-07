"""Tests for image loading and EXIF-orientation correction."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services.image_io import describe_image, open_image

# EXIF Orientation tag values that require Pillow to rotate/flip the buffer
# to match how the photo actually displays. 1 (or absent) needs no change.
_NEEDS_ROTATION = {3: (400, 300), 6: (300, 400), 8: (300, 400)}


def _jpeg_bytes(size: tuple[int, int], orientation: int | None) -> bytes:
    image = Image.new("RGB", size, (120, 80, 40))
    buf = io.BytesIO()
    if orientation is None:
        image.save(buf, format="JPEG")
    else:
        exif = image.getexif()
        exif[0x0112] = orientation  # Orientation tag
        exif[0x010F] = "TestMake"  # Make, to confirm other tags survive
        image.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


@pytest.mark.parametrize("orientation,expected_size", list(_NEEDS_ROTATION.items()))
def test_open_image_applies_exif_orientation(orientation: int, expected_size: tuple[int, int]) -> None:
    # Raw buffer is landscape (400x300); orientation 3/6/8 all require a
    # rotation, and 6/8 land on a portrait (300x400) result.
    data = _jpeg_bytes((400, 300), orientation)
    image = open_image(data)
    assert image.size == expected_size


def test_open_image_leaves_unrotated_image_untouched() -> None:
    data = _jpeg_bytes((400, 300), orientation=1)
    image = open_image(data)
    assert image.size == (400, 300)


def test_open_image_without_exif_is_untouched() -> None:
    data = _jpeg_bytes((400, 300), orientation=None)
    image = open_image(data)
    assert image.size == (400, 300)


def test_open_image_preserves_format_after_rotation() -> None:
    # ImageOps.exif_transpose drops .format to None on the rotation branch;
    # open_image must restore it so downstream reporting stays correct.
    data = _jpeg_bytes((400, 300), orientation=6)
    image = open_image(data)
    assert image.format == "JPEG"


def test_open_image_preserves_other_exif_tags_after_rotation() -> None:
    data = _jpeg_bytes((400, 300), orientation=6)
    image = open_image(data)
    assert image.getexif().get(0x010F) == "TestMake"
    # The orientation tag itself should be cleared so nothing downstream
    # tries to rotate the already-corrected image a second time.
    assert image.getexif().get(0x0112) in (None, 1)


def test_describe_image_reports_corrected_dimensions() -> None:
    data = _jpeg_bytes((400, 300), orientation=6)
    image = open_image(data)
    info = describe_image(image, filename="portrait.jpg", size_bytes=len(data))
    assert info["width"] == 300
    assert info["height"] == 400
    assert info["format"] == "JPEG"
