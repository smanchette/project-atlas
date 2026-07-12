from datetime import UTC, datetime, timedelta
from pathlib import Path
import inspect

import pytest
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.models import ImageMetadata
from app.schemas.wordpress import (
    WordPressMediaAttachmentMatch, WordPressMediaFeaturedReference,
    WordPressMediaReconciliationCandidate,
)
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
    assert ("/api/wordpress/media/inspect/{page_id}", "GET") in routes
    assert ("/api/wordpress/media/reconciliation/dry-run/{page_id}", "POST") in routes
    assert ("/api/wordpress/media/reconciliation/apply/{page_id}", "POST") in routes
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


def test_attachment_verification_reports_each_actionable_mismatch() -> None:
    mismatches = media_sync._verification_mismatches(
        {
            "id": 88,
            "alt_text": "",
            "mime_type": "image/jpeg",
            "source_url": None,
            "meta": {},
        },
        media_id=77,
        expected_url=None,
        mime_type="image/png",
        alt_text="Reviewed Orlando alt text",
        checksum="abc123",
    )
    message = "; ".join(mismatches)
    assert "media_id expected 77" in message
    assert "alt_text expected" in message
    assert "mime_type expected 'image/png'" in message
    assert "source_url expected a non-empty string" in message
    assert "meta._atlas_source_checksum expected 'abc123', got None" in message
    assert "meta._atlas_image_metadata_id expected '1', got None" in message
    assert "meta._atlas_generated_page_id expected '41', got None" in message
    assert "meta._atlas_managed_media expected 'true', got None" in message


def test_attachment_verification_accepts_exact_rest_response() -> None:
    assert media_sync._verification_mismatches(
        {
            "id": 77,
            "alt_text": "Reviewed Orlando alt text",
            "mime_type": "image/png",
            "source_url": "https://example.test/orlando.png",
            "meta": {
                "_atlas_source_checksum": "abc123",
                "_atlas_image_metadata_id": "1",
                "_atlas_generated_page_id": "41",
                "_atlas_managed_media": "true",
            },
        },
        media_id=77,
        expected_url=None,
        mime_type="image/png",
        alt_text="Reviewed Orlando alt text",
        checksum="abc123",
    ) == []


def _candidate(media_id: int, date: str, valid: bool = True) -> WordPressMediaReconciliationCandidate:
    return WordPressMediaReconciliationCandidate(
        wordpress_media_id=media_id, date_gmt=date, source_url=f"https://example.test/{media_id}.png",
        remote_checksum="abc", valid=valid, gate_results=[],
    )


def test_reconciliation_selects_only_valid_candidate() -> None:
    selected, duplicates = media_sync._select_reconciliation_candidate([
        _candidate(31, "2026-07-12T08:36:08"), _candidate(32, "2026-07-12T08:38:46", False),
    ])
    assert selected and selected.wordpress_media_id == 31
    assert duplicates == []


def test_reconciliation_selects_earliest_and_records_duplicate() -> None:
    selected, duplicates = media_sync._select_reconciliation_candidate([
        _candidate(32, "2026-07-12T08:38:46"), _candidate(31, "2026-07-12T08:36:08"),
    ])
    assert selected and selected.wordpress_media_id == 31
    assert duplicates == [32]


def test_reconciliation_equal_dates_select_lowest_id() -> None:
    selected, duplicates = media_sync._select_reconciliation_candidate([
        _candidate(32, "2026-07-12T08:36:08"), _candidate(31, "2026-07-12T08:36:08"),
    ])
    assert selected and selected.wordpress_media_id == 31
    assert duplicates == [32]


def test_remote_byte_hashing_matches_exact_response() -> None:
    content = b"exact-original-image-bytes"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=content, request=request))
    with httpx.Client(transport=transport) as client:
        checksum, size = media_sync._download_checksum(client, "https://example.test/hero.png", "https://example.test")
    assert checksum == media_sync.hashlib.sha256(content).hexdigest()
    assert size == len(content)


def test_remote_redirect_to_other_host_blocks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.test/hero.png"}, request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="outside"):
            media_sync._download_checksum(client, "https://example.test/hero.png", "https://example.test")


def test_reconciliation_token_is_bound_and_tamper_evident() -> None:
    candidates = [_candidate(31, "2026-07-12T08:36:08"), _candidate(32, "2026-07-12T08:38:46")]
    token = media_sync._sign_reconciliation("abc", candidates, 31, [32], datetime.now(UTC) + timedelta(minutes=1))
    body = media_sync._verify_reconciliation(token, 41)
    assert body["selected_media_id"] == 31 and body["duplicate_candidate_ids"] == [32]
    with pytest.raises(HTTPException):
        media_sync._verify_reconciliation(token, 42)
    encoded, signature = token.split(".", 1)
    tampered = f"{encoded}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
    with pytest.raises(HTTPException):
        media_sync._verify_reconciliation(tampered, 41)


def test_reconciliation_workflow_contains_no_wordpress_write_request() -> None:
    source = "\n".join((
        inspect.getsource(media_sync.dry_run_wordpress_media_reconciliation),
        inspect.getsource(media_sync._inspect_reconciliation_candidate),
        inspect.getsource(media_sync._download_checksum),
        inspect.getsource(media_sync.reconcile_wordpress_media),
    ))
    for forbidden in ("client.post(", "client.patch(", "client.put(", "client.delete("):
        assert forbidden not in source


def test_featured_reference_detector_filters_actual_media_id_and_reports_object() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pages"):
            payload = [{"id": 8, "featured_media": 0, "title": {"rendered": "Orlando"}, "status": "publish", "slug": "orlando", "link": "https://example.test/orlando"}]
        else:
            payload = [{"id": 77, "featured_media": 32, "title": {"rendered": "Referenced post"}, "status": "draft", "slug": "referenced-post", "link": "https://example.test/?p=77"}]
        return httpx.Response(200, json=payload, request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        references = media_sync._find_featured_references(client, "https://example.test/wp-json/wp/v2", httpx.BasicAuth("u", "p"), 32)
    assert len(references) == 1
    assert references[0].object_type == "post"
    assert references[0].object_id == 77
    assert references[0].title == "Referenced post"
    assert "post 77" in media_sync._featured_reference_message(references)


def _featured_blocked_candidate(media_id: int, object_id: int) -> WordPressMediaReconciliationCandidate:
    reference = WordPressMediaFeaturedReference(object_type="page", object_id=object_id, title="Using page", status="publish", slug="using-page")
    return WordPressMediaReconciliationCandidate(
        wordpress_media_id=media_id, date_gmt="2026-07-12T08:36:08",
        remote_checksum="abc", valid=False, featured_references=[reference],
        gate_results=[
            media_sync._gate("remote_checksum", "Hash", True, "Hash mismatch."),
            media_sync._gate("not_featured_elsewhere", "Featured usage", False, "Used."),
        ],
    )


def test_hash_passes_but_featured_usage_gets_accurate_selection_message() -> None:
    message = media_sync._candidate_selection_failure([_featured_blocked_candidate(32, 77)])
    assert "byte-matching" in message
    assert "featured-media usage" in message
    assert "page 77" in message
    assert "byte-level verification" not in message


def test_one_valid_candidate_selected_when_other_is_featured_elsewhere() -> None:
    selected, duplicates = media_sync._select_reconciliation_candidate([
        _candidate(31, "2026-07-12T08:36:08"), _featured_blocked_candidate(32, 77),
    ])
    assert selected and selected.wordpress_media_id == 31
    assert duplicates == []


def test_both_candidates_featured_elsewhere_block_with_reference_ids() -> None:
    candidates = [_featured_blocked_candidate(31, 76), _featured_blocked_candidate(32, 77)]
    selected, duplicates = media_sync._select_reconciliation_candidate(candidates)
    message = media_sync._candidate_selection_failure(candidates)
    assert selected is None and duplicates == []
    assert "page 76" in message and "page 77" in message
