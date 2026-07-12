from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.models import ImageMetadata
from app.schemas.wordpress import WordPressMediaAttachmentMatch
from app.services import wordpress_media_sync as media_sync


def _image_record(**overrides: object) -> ImageMetadata:
    values = {
        "business_id": 1,
        "file_name": "orlando-drywood-termite-tenting-hero.png",
        "image_role": "hero",
        "review_status": "reviewed",
        "asset_url": "/media/orlando-drywood-termite-tenting-hero.png",
    }
    values.update(overrides)
    return ImageMetadata(**values)


def test_media_routes_are_orlando_only_and_no_get_or_bulk_upload_route_exists() -> None:
    with TestClient(app) as client:
        response = client.post("/api/wordpress/media/dry-run/42")
    assert response.status_code == 404
    routes = {(route.path, method) for route in app.routes for method in (getattr(route, "methods", None) or set())}
    assert ("/api/wordpress/media/dry-run/{page_id}", "POST") in routes
    assert ("/api/wordpress/media/upload/{page_id}", "POST") in routes
    assert not any("bulk" in path or "featured" in path for path, _ in routes if "/wordpress/media/" in path)


def test_media_path_traversal_and_outside_absolute_path_are_blocked() -> None:
    traversal, traversal_error = media_sync._resolve_media_path(
        _image_record(asset_url="/media/../secrets/orlando-drywood-termite-tenting-hero.png")
    )
    outside, outside_error = media_sync._resolve_media_path(
        _image_record(asset_url="C:/temp/orlando-drywood-termite-tenting-hero.png")
    )
    assert traversal is None and "/media/" in (traversal_error or "")
    assert outside is None and "/media/" in (outside_error or "")


def test_atlas_media_asset_url_resolves_despite_legacy_file_name() -> None:
    path, error = media_sync._resolve_media_path(
        _image_record(file_name="orlando-drywood-termite-tenting.jpg")
    )
    assert error is None
    assert path is not None
    assert path.name == "orlando-drywood-termite-tenting-hero.png"
    assert path.is_relative_to(path.parent.resolve())


def test_missing_atlas_asset_file_blocks() -> None:
    path, error = media_sync._resolve_media_path(
        _image_record(asset_url="/media/atlas-file-that-does-not-exist.png")
    )
    assert path is None
    assert "does not exist" in (error or "")


def test_orlando_file_inspection_matches_verified_properties() -> None:
    path, error = media_sync._resolve_media_path(
        _image_record(file_name="orlando-drywood-termite-tenting.jpg")
    )
    assert error is None and path is not None
    mime, size, width, height, checksum, validation_error = media_sync._inspect_file(path)
    assert validation_error is None
    assert (mime, size, width, height) == ("image/png", 2_823_150, 1672, 941)
    assert checksum == "9f94d1ba555c2f3655bd600a61aac3247ab2a1a951a6cf73b1152d94fe40b2a0"


def test_not_already_mapped_does_not_claim_match_when_lookup_unavailable() -> None:
    gate = media_sync._not_already_mapped_gate(
        _image_record(wordpress_media_id=None),
        WordPressMediaAttachmentMatch(status="unavailable", message="Credentials missing."),
    )
    assert gate.passed is True
    assert "verified WordPress attachment" not in gate.message


def test_not_already_mapped_fails_only_for_verified_attachment_match() -> None:
    image = _image_record(wordpress_media_id=None)
    unverified = media_sync._not_already_mapped_gate(
        image,
        WordPressMediaAttachmentMatch(status="matched", message="Incomplete match."),
    )
    verified = media_sync._not_already_mapped_gate(
        image,
        WordPressMediaAttachmentMatch(
            status="matched", wordpress_media_id=123, wordpress_media_url="https://example.test/hero.png", message="Verified."
        ),
    )
    assert unverified.passed is True
    assert verified.passed is False
    assert "verified WordPress attachment" in verified.message


def test_inspect_file_accepts_png_and_hashes_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "hero.png"
    Image.new("RGB", (17, 11), "blue").save(path)
    mime, size, width, height, checksum, error = media_sync._inspect_file(path)
    assert (mime, width, height, error) == ("image/png", 17, 11, None)
    assert size == len(path.read_bytes())
    assert checksum == media_sync.hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("name", ["hero.gif", "hero.txt"])
def test_inspect_file_blocks_unsupported_or_mismatched_mime(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    Image.new("RGB", (8, 8), "red").save(path, format="PNG")
    assert media_sync._inspect_file(path)[-1] is not None


def test_inspect_file_blocks_corrupt_image(tmp_path: Path) -> None:
    path = tmp_path / "hero.png"
    path.write_bytes(b"not an image")
    assert "corrupt" in (media_sync._inspect_file(path)[-1] or "")


def test_signed_media_token_is_bound_tamper_evident_and_expires() -> None:
    token = media_sync._sign(41, "abc", datetime.now(UTC) + timedelta(minutes=1))
    assert media_sync._verify(token, 41)["checksum"] == "abc"
    with pytest.raises(HTTPException):
        media_sync._verify(token, 42)
    with pytest.raises(HTTPException):
        media_sync._verify(token[:-1] + ("A" if token[-1] != "A" else "B"), 41)
    expired = media_sync._sign(41, "abc", datetime.now(UTC) - timedelta(seconds=1))
    with pytest.raises(HTTPException):
        media_sync._verify(expired, 41)
