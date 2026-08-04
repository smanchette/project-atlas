from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from conftest import TEST_MEDIA_PATH
from app.main import app


def _image_payload(image_format: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (8, 8), (60, 220, 20, 255)).save(buffer, format=image_format)
    return buffer.getvalue()


def test_media_static_responses_preserve_narrow_mime_types() -> None:
    identifier = uuid4().hex
    fixtures = {
        TEST_MEDIA_PATH / "optimized" / f"{identifier}-optimized.webp": _image_payload("WEBP"),
        TEST_MEDIA_PATH / "thumbnails" / f"{identifier}-thumbnail.webp": _image_payload("WEBP"),
        TEST_MEDIA_PATH / "originals" / f"{identifier}.png": _image_payload("PNG"),
        TEST_MEDIA_PATH / f"{identifier}.css": b".atlas-test { color: green; }\n",
    }

    for path, payload in fixtures.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    try:
        with TestClient(app) as client:
            optimized = client.get(f"/media/optimized/{identifier}-optimized.webp")
            thumbnail = client.get(f"/media/thumbnails/{identifier}-thumbnail.webp")
            original = client.get(f"/media/originals/{identifier}.png")
            unrelated = client.get(f"/media/{identifier}.css")

        assert optimized.status_code == 200
        assert optimized.headers["content-type"] == "image/webp"
        assert thumbnail.status_code == 200
        assert thumbnail.headers["content-type"] == "image/webp"
        assert original.status_code == 200
        assert original.headers["content-type"] == "image/png"
        assert unrelated.status_code == 200
        assert unrelated.headers["content-type"].startswith("text/css")
    finally:
        for path in fixtures:
            path.unlink(missing_ok=True)
