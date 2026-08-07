import io

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app

client = TestClient(app)


def _png_bytes(size: tuple[int, int] = (800, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 120, 120)).save(buf, format="PNG")
    return buf.getvalue()


def test_analyze_returns_image_info() -> None:
    files = {"file": ("test.png", _png_bytes(), "image/png")}
    response = client.post("/api/analyze", files=files)

    assert response.status_code == 200
    info = response.json()["image"]
    assert info["width"] == 800
    assert info["height"] == 600
    assert info["format"] == "PNG"


def test_analyze_rejects_non_image() -> None:
    files = {"file": ("notes.txt", b"hello world", "text/plain")}
    response = client.post("/api/analyze", files=files)
    assert response.status_code == 422


def _rotated_portrait_jpeg_bytes() -> bytes:
    # Phones commonly store a portrait shot in the sensor's native landscape
    # buffer plus an EXIF Orientation tag telling viewers to rotate it. This
    # mirrors that: a 400x300 (landscape) buffer tagged orientation=6, which
    # should display and analyze as a 300x400 portrait.
    image = Image.new("RGB", (400, 300), (120, 120, 120))
    exif = image.getexif()
    exif[0x0112] = 6  # Orientation
    buf = io.BytesIO()
    image.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def test_analyze_reports_orientation_from_exif_not_raw_buffer() -> None:
    files = {"file": ("portrait.jpg", _rotated_portrait_jpeg_bytes(), "image/jpeg")}
    response = client.post("/api/analyze", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["image"]["width"] == 300
    assert body["image"]["height"] == 400
    assert body["image"]["format"] == "JPEG"
    assert body["vision"]["orientation"] == "portrait"
    assert body["vision"]["dimensions"]["width"] == 300
    assert body["vision"]["dimensions"]["height"] == 400
