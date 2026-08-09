from datetime import UTC, datetime, timedelta
from pathlib import Path
import inspect
from types import SimpleNamespace

import pytest
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.models import GeneratedPage, ImageMetadata, PageImageAssignment, Website
from app.schemas.wordpress import (
    WordPressMediaAttachmentMatch, WordPressMediaFeaturedReference,
    WordPressMediaReconciliationCandidate,
)
from app.services import wordpress_media_sync as media_sync
from app.services.website_media_safety import (
    filter_wordpress_media_ids,
    is_wordpress_media_excluded,
    wordpress_source_matches_policy,
    website_external_media_policy_snapshot,
)


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
    assert ("/api/wordpress/media/featured-image/dry-run/{page_id}", "POST") in routes
    assert ("/api/wordpress/media/featured-image/apply/{page_id}", "POST") in routes
    assert ("/api/wordpress/media/featured-image/verify/{page_id}", "POST") in routes
    assert not any("bulk" in path or "delete" in path for path, _ in routes if "/wordpress/media/" in path)


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


def _flo_zone_website() -> Website:
    return Website(
        id=1,
        business_id=1,
        brand_id=1,
        website_name="Flo-Zone Tenting",
        domain="www.flo-zonetenting.com",
        public_url="https://www.Flo-ZoneTenting.com",
        configuration={
            "short_brand_name": "Flo-Zone",
            "why_knowledge_slug": (
                "why-fumigation-is-most-complete-drywood-termite-treatment"
            ),
        },
    )


def _other_website() -> Website:
    return Website(
        id=2,
        business_id=2,
        brand_id=2,
        website_name="Other Website",
        domain="other.example.test",
        public_url="https://other.example.test",
    )


def test_flo_zone_media_32_is_removed_from_candidate_discovery() -> None:
    assert filter_wordpress_media_ids(
        _flo_zone_website(),
        media_sync.CANDIDATE_MEDIA_IDS,
    ) == (31,)


def test_flo_zone_recent_media_inspector_never_returns_media_32(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website = _flo_zone_website()
    website.id = 1
    page = GeneratedPage(
        id=41,
        business_id=1,
        website_id=1,
        page_type="city_service",
        page_title="Orlando",
        page_slug=media_sync.EXPECTED_SLUG,
        h1="Orlando",
    )
    image = _image_record(id=1, image_title="Orlando hero")
    assignment = PageImageAssignment(
        id=1,
        generated_page_id=41,
        image_metadata_id=1,
        image_role="hero",
        override_alt_text="Orlando hero alt",
    )

    class FakeSession:
        def get(self, model, record_id):
            return {
                (GeneratedPage, 41): page,
                (ImageMetadata, 1): image,
                (PageImageAssignment, 1): assignment,
                (Website, 1): website,
            }.get((model, record_id))

    records = [
        {
            "id": media_id,
            "date_gmt": "2026-07-12T08:36:08",
            "source_url": f"https://www.drywoodtenting.com/orlando-hero-{media_id}.png",
            "mime_type": "image/png",
            "slug": f"orlando-hero-{media_id}",
            "title": {"rendered": "Orlando hero"},
            "alt_text": "Orlando hero alt",
            "media_details": {"file": f"orlando-hero-{media_id}.png"},
            "meta": {},
        }
        for media_id in (32, 31)
    ]

    class InspectorClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url: str, **kwargs):
            return httpx.Response(
                200,
                request=httpx.Request("GET", url),
                json=records,
            )

    monkeypatch.setattr(
        media_sync,
        "read_wordpress_settings",
        lambda session: SimpleNamespace(
            site_url="https://www.drywoodtenting.com",
            username="operator",
        ),
    )
    monkeypatch.setattr(
        media_sync,
        "get_wordpress_application_password",
        lambda: "unused",
    )
    monkeypatch.setattr(
        media_sync,
        "_resolve_media_path",
        lambda image: (Path("orlando-hero.png"), None),
    )
    monkeypatch.setattr(
        media_sync,
        "_inspect_file",
        lambda path: ("image/png", 10, 10, 10, "abc", None),
    )
    monkeypatch.setattr(
        media_sync,
        "wordpress_http_client",
        lambda *args, **kwargs: InspectorClient(),
    )

    result = media_sync.inspect_wordpress_media(FakeSession(), 41)
    assert result.candidate_count == 1
    assert [item.wordpress_media_id for item in result.candidates] == [31]


def test_flo_zone_media_32_cannot_be_selected_for_reconciliation() -> None:
    selected, duplicates = media_sync._select_reconciliation_candidate(
        [_candidate(32, "2026-07-12T08:36:08")],
        website=_flo_zone_website(),
    )
    assert selected is None
    assert duplicates == []


def test_flo_zone_media_32_cannot_displace_newer_media_31() -> None:
    selected, duplicates = media_sync._select_reconciliation_candidate(
        [
            _candidate(32, "2026-07-12T08:00:00"),
            _candidate(31, "2026-07-12T09:00:00"),
        ],
        website=_flo_zone_website(),
    )
    assert selected and selected.wordpress_media_id == 31
    assert duplicates == []


def test_flo_zone_media_32_remains_excluded_when_otherwise_valid() -> None:
    valid_32 = _candidate(32, "2026-07-12T08:00:00", valid=True)
    assert valid_32.valid is True
    selected, _ = media_sync._select_reconciliation_candidate(
        [valid_32],
        website=_flo_zone_website(),
    )
    assert selected is None


def test_flo_zone_media_31_remains_eligible() -> None:
    selected, duplicates = media_sync._select_reconciliation_candidate(
        [_candidate(31, "2026-07-12T08:36:08")],
        website=_flo_zone_website(),
    )
    assert selected and selected.wordpress_media_id == 31
    assert duplicates == []


def test_other_website_media_32_remains_eligible() -> None:
    selected, duplicates = media_sync._select_reconciliation_candidate(
        [_candidate(32, "2026-07-12T08:36:08")],
        website=_other_website(),
    )
    assert selected and selected.wordpress_media_id == 32
    assert duplicates == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("website_name", "Flo-Zone Tenting"),
        ("domain", "www.flo-zonetenting.com"),
        ("public_url", "https://www.Flo-ZoneTenting.com"),
    ],
)
def test_partial_flo_zone_identity_match_does_not_scope_other_website_media_32(
    field: str,
    value: str,
) -> None:
    website = _other_website()
    setattr(website, field, value)
    assert filter_wordpress_media_ids(website, (31, 32)) == (31, 32)


def test_fixed_wordpress_media_lookup_blocks_absent_site_policy_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        media_sync,
        "wordpress_http_client",
        lambda *args, **kwargs: pytest.fail("A missing site policy must block before HTTP."),
    )
    match = media_sync._attachment_match(
        "https://www.drywoodtenting.com",
        "operator",
        "unused",
        _image_record(wordpress_media_id=None),
        "abc",
        website=_other_website(),
    )
    assert match.status == "blocked"
    assert "Website-scoped" in match.message


def test_reconciliation_token_binds_site_scoped_policy_fingerprint() -> None:
    website = _flo_zone_website()
    fingerprint = str(
        website_external_media_policy_snapshot(website)["fingerprint"]
    )
    token = media_sync._sign_reconciliation(
        "abc",
        [_candidate(31, "2026-07-12T08:36:08")],
        31,
        [],
        datetime.now(UTC) + timedelta(minutes=1),
        candidate_ids=(31,),
        policy_fingerprint=fingerprint,
    )
    body = media_sync._verify_reconciliation(token, 41)
    assert body["candidate_ids"] == [31]
    assert body["external_media_policy_fingerprint"] == fingerprint


def test_saved_flo_zone_media_32_mapping_blocks_before_candidate_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        media_sync,
        "wordpress_http_client",
        lambda *args, **kwargs: pytest.fail("Excluded media must not be queried."),
    )
    match = media_sync._attachment_match(
        "https://www.drywoodtenting.com",
        "operator",
        "unused",
        _image_record(wordpress_media_id=32),
        "abc",
        website=_flo_zone_website(),
    )
    assert match.status == "blocked"
    assert "Website-scoped" in match.message


def test_generic_attachment_search_skips_32_and_matches_31(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta = {
        "_atlas_managed_media": "true",
        "_atlas_image_metadata_id": "1",
        "_atlas_generated_page_id": "41",
        "_atlas_source_checksum": "abc",
    }

    class SearchClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url: str, **kwargs):
            request = httpx.Request("GET", url)
            return httpx.Response(
                200,
                request=request,
                json=[
                    {"id": 32, "source_url": "https://example.test/32.png", "meta": meta},
                    {"id": 31, "source_url": "https://example.test/31.png", "meta": meta},
                ],
            )

    monkeypatch.setattr(
        media_sync,
        "wordpress_http_client",
        lambda *args, **kwargs: SearchClient(),
    )
    match = media_sync._attachment_match(
        "https://www.drywoodtenting.com",
        "operator",
        "unused",
        _image_record(wordpress_media_id=None),
        "abc",
        website=_flo_zone_website(),
    )
    assert match.status == "matched"
    assert match.wordpress_media_id == 31


def test_existing_flo_zone_media_31_mapping_stays_verified_and_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = _image_record(wordpress_media_id=31)
    meta = {
        "_atlas_managed_media": "true",
        "_atlas_image_metadata_id": "1",
        "_atlas_generated_page_id": "41",
        "_atlas_source_checksum": "abc",
    }

    class MappedClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url: str, **kwargs):
            request = httpx.Request("GET", url)
            return httpx.Response(
                200,
                request=request,
                json={
                    "id": 31,
                    "source_url": "https://example.test/31.png",
                    "meta": meta,
                },
            )

    monkeypatch.setattr(
        media_sync,
        "wordpress_http_client",
        lambda *args, **kwargs: MappedClient(),
    )
    match = media_sync._attachment_match(
        "https://www.drywoodtenting.com",
        "operator",
        "unused",
        image,
        "abc",
        website=_flo_zone_website(),
    )
    assert not is_wordpress_media_excluded(_flo_zone_website(), 31)
    assert match.status == "matched"
    assert match.wordpress_media_id == 31
    assert image.wordpress_media_id == 31


def test_flo_zone_identity_tuple_keeps_policy_fail_closed_after_mutable_identity_drift() -> None:
    website = _flo_zone_website()
    website.id = 1
    website.business_id = 999
    website.brand_id = 999
    website.website_name = "Drifted Website"
    website.domain = "drifted.example.test"
    website.public_url = "https://drifted.example.test"
    assert filter_wordpress_media_ids(website, (31, 32)) == (31,)


def test_flo_zone_stable_identity_keeps_policy_after_backup_id_remapping() -> None:
    website = _flo_zone_website()
    website.id = 901
    website.business_id = 902
    website.brand_id = 903
    assert filter_wordpress_media_ids(website, (31, 32)) == (31,)


def test_unrelated_website_reusing_id_one_does_not_receive_flo_zone_policy() -> None:
    website = _other_website()
    website.id = 1
    website.business_id = 1
    website.brand_id = 1
    assert filter_wordpress_media_ids(website, (31, 32)) == (31, 32)


def test_flo_zone_policy_rejects_an_unexpected_wordpress_source_origin() -> None:
    website = _flo_zone_website()
    assert wordpress_source_matches_policy(
        website,
        "https://www.drywoodtenting.com",
    )
    assert not wordpress_source_matches_policy(
        website,
        "https://other-wordpress.example.test",
    )


def test_wordpress_source_gate_fails_closed_when_flo_zone_identity_drifted() -> None:
    website = _flo_zone_website()
    website.business_id = 999
    assert filter_wordpress_media_ids(website, (31, 32)) == (31,)
    assert not wordpress_source_matches_policy(
        website,
        "https://www.drywoodtenting.com",
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


def test_featured_image_post_verification_requires_publish_media_31_and_identity() -> None:
    valid = {"id": 8, "status": "publish", "featured_media": 31, "slug": media_sync.EXPECTED_SLUG, "link": media_sync.EXPECTED_ORLANDO_URL}
    media_sync._verify_featured_post(valid, "test")
    for key, value in (("id", 9), ("status", "draft"), ("featured_media", 32), ("slug", "wrong"), ("link", "https://example.test/wrong")):
        changed = {**valid, key: value}
        with pytest.raises(RuntimeError, match=key):
            media_sync._verify_featured_post(changed, "test")


def test_featured_image_token_is_fixed_to_media_31_and_tamper_evident() -> None:
    candidate = _candidate(31, "2026-07-12T08:36:08")
    post = {"status": "publish", "slug": media_sync.EXPECTED_SLUG, "link": media_sync.EXPECTED_ORLANDO_URL, "featured_media": 0}
    token = media_sync._sign_featured_image("abc", candidate, post, datetime.now(UTC) + timedelta(minutes=1))
    body = media_sync._verify_featured_image(token, 41)
    assert body["wordpress_media_id"] == 31
    assert body["snapshot"]["planned_payload"] == {"featured_media": 31}
    assert body["snapshot"]["excluded_media_ids"] == [32]
    encoded, signature = token.split(".", 1)
    tampered = f"{encoded}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
    with pytest.raises(HTTPException):
        media_sync._verify_featured_image(tampered, 41)


def test_featured_image_archive_backup_gates_require_current_exact_names() -> None:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d-%H%M%S")
    assert media_sync._archive_backup_gate(f"atlas-media-backup-{stamp}.zip", "media").passed
    assert media_sync._archive_backup_gate(f"atlas-program-backup-{stamp}.zip", "program").passed
    assert not media_sync._archive_backup_gate("../atlas-media-backup.zip", "media").passed
    old = (datetime.now().astimezone() - timedelta(days=2)).strftime("%Y-%m-%d-%H%M%S")
    assert not media_sync._archive_backup_gate(f"atlas-media-backup-{old}.zip", "media").passed


def test_featured_image_apply_has_exactly_one_wordpress_write_and_safe_payload() -> None:
    source = inspect.getsource(media_sync.apply_wordpress_featured_image)
    assert source.count("client.post(") == 1
    assert 'json={"featured_media": 31}' in source
    for forbidden in ('"title"', '"slug"', '"content"', '"excerpt"', '"status"', "client.patch(", "client.put(", "client.delete("):
        assert forbidden not in source
    assert "/media/32" not in source


def test_final_featured_post_gates_pass_only_for_publish_media_31() -> None:
    valid = {"id": 8, "status": "publish", "featured_media": 31, "slug": media_sync.EXPECTED_SLUG, "link": media_sync.EXPECTED_ORLANDO_URL}
    assert all(gate.passed for gate in media_sync._final_featured_post_gates(valid))
    for featured_media in (0, 32):
        gates = media_sync._final_featured_post_gates({**valid, "featured_media": featured_media})
        assert next(gate for gate in gates if gate.code == "featured_media").passed is False
    gates = media_sync._final_featured_post_gates({**valid, "status": "draft"})
    assert next(gate for gate in gates if gate.code == "post_publish").passed is False


def test_post_featured_verification_is_read_only_and_creates_no_token() -> None:
    source = inspect.getsource(media_sync.verify_wordpress_featured_image)
    for forbidden in ("session.add(", "session.commit(", "client.post(", "client.patch(", "client.put(", "client.delete(", "_sign_"):
        assert forbidden not in source
    schema = media_sync.WordPressFeaturedImageVerification(
        page_id=41, wordpress_post_id=8, wordpress_media_id=31,
        gate_results=[], status="verified", apply_needed=False,
        featured_image_correct=True,
    )
    assert schema.ready is False
    assert schema.confirmation_token is None
    assert schema.confirmation_phrase is None
    assert schema.read_only is True


def test_post_featured_reference_policy_allows_orlando_only() -> None:
    assert media_sync._featured_references_allowed({("page", 8)}, {("page", 8)})
    assert media_sync._featured_references_allowed(set(), set())
    assert not media_sync._featured_references_allowed({("page", 8), ("post", 77)}, {("page", 8)})
    assert not media_sync._featured_references_allowed({("page", 8)}, set())
