from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models import GeneratedPage
from app.schemas.page_export import (
    ExportMediaReference,
    ExportSEO,
    PageExportPackage,
)
from app.schemas.wordpress import WordPressLiveDraftStatus
from app.services import wordpress_publish, wordpress_quality_review


def _export_package(image_role: str) -> PageExportPackage:
    return PageExportPackage(
        page_id=41,
        page_status="approved",
        qa_status="passed",
        page_title="Drywood Termite Tenting in Orlando, Florida",
        url_slug="drywood-termite-tenting-orlando-fl",
        h1="Drywood Termite Tenting in Orlando, Florida",
        seo=ExportSEO(
            meta_title="Drywood Termite Tenting in Orlando, Florida",
            meta_description="Learn about drywood termite tenting in Orlando.",
            social_title="Drywood Termite Tenting in Orlando, Florida",
            social_description="Learn about drywood termite tenting in Orlando.",
            suggested_url_slug="drywood-termite-tenting-orlando-fl",
        ),
        content_sections={
            "process_section": (
                "Realtor and property manager preparation includes re-entry "
                "after clearance."
            )
        },
        faq_items=[],
        cta_block="Request an estimate.",
        city="Orlando",
        county="Orange County",
        state="FL",
        service="Drywood Termite Tenting",
        business_name="Flo-Zone",
        phone="(844) 600-8368",
        website="https://example.test",
        email="office@example.test",
        license_number="JB360566",
        certified_operator="Jordan Ward",
        assigned_media=[
            ExportMediaReference(
                image_id=301,
                image_role=image_role,
                sort_order=0,
                media_requirement_id=257,
                media_requirement_version=2,
                placement_key="city-service-hero",
                target_component_key="hero",
                target_component_instance_key="hero",
                placement_contract_version=2,
                image_title="Approved representative hero",
                alt_text="Approved representative hero image",
                asset_url="/media/page-media/originals/hero.webp",
                display_preset="hero_desktop",
                focal_x=0.5,
                focal_y=0.5,
                review_status="reviewed",
            )
        ],
        json_ld={},
        canonical_url_preview=(
            "https://example.test/drywood-termite-tenting-orlando-fl/"
        ),
        slug_conflicts=[],
        export_ready=True,
        warnings=[],
    )


def _quality_detail() -> SimpleNamespace:
    return SimpleNamespace(
        item=SimpleNamespace(
            wordpress_post_id=8,
            wordpress_url="https://example.test/?page_id=8",
            wordpress_status="draft",
        ),
        comparison=SimpleNamespace(
            atlas_saved_title="Drywood Termite Tenting in Orlando, Florida",
            atlas_saved_slug="drywood-termite-tenting-orlando-fl",
        ),
    )


def _media_quality_statuses(image_role: str) -> dict[str, str]:
    checks = wordpress_quality_review._checklist(
        _quality_detail(),
        _export_package(image_role),
    )
    return {
        check.key: check.status
        for check in checks
        if check.key
        in {
            "hero_media_status_understood",
            "alt_text_media_reviewed",
            "missing_media_issues_listed",
        }
    }


def test_wordpress_quality_guard_accepts_only_canonical_hero_output() -> None:
    assert _media_quality_statuses("hero") == {
        "hero_media_status_understood": "pass",
        "alt_text_media_reviewed": "pass",
        "missing_media_issues_listed": "pass",
    }
    assert _media_quality_statuses("city-service-hero:assignment-1") == {
        "hero_media_status_understood": "fail",
        "alt_text_media_reviewed": "fail",
        "missing_media_issues_listed": "pass",
    }


class _SessionStub:
    def __init__(self) -> None:
        self.page = SimpleNamespace(
            id=41,
            status="approved",
            wordpress_post_id=8,
            wordpress_status="draft",
        )

    def get(self, model, identity):
        if model is GeneratedPage and identity == self.page.id:
            return self.page
        return None


@pytest.mark.parametrize(
    ("image_role", "expected_ready"),
    (("hero", True), ("city-service-hero:assignment-1", False)),
)
def test_publish_dry_run_quality_gate_consumes_canonical_hero_without_network(
    monkeypatch,
    image_role: str,
    expected_ready: bool,
) -> None:
    package = _export_package(image_role)
    live_status_stub_calls = 0

    monkeypatch.setattr(
        wordpress_publish,
        "read_wordpress_settings",
        lambda _session: SimpleNamespace(
            publishing_mode="sandbox",
            site_url="https://example.test",
            username="operator",
        ),
    )
    monkeypatch.setattr(
        wordpress_publish,
        "get_wordpress_application_password",
        lambda: "memory-only-test-secret",
    )
    monkeypatch.setattr(
        wordpress_publish,
        "build_page_export_package",
        lambda _session, _page_id: package,
    )

    def quality_stub(_session, _page_id):
        statuses = _media_quality_statuses(image_role)
        return SimpleNamespace(
            manual_review=SimpleNamespace(
                review_status="ready_for_manual_publish_review"
            ),
            fail_count=sum(status == "fail" for status in statuses.values()),
        )

    monkeypatch.setattr(
        wordpress_publish,
        "build_wordpress_draft_quality_review",
        quality_stub,
    )
    monkeypatch.setattr(
        wordpress_publish,
        "build_wordpress_payload_preview",
        lambda _session, _page_id: SimpleNamespace(
            payload=SimpleNamespace(
                title=package.page_title,
                slug=package.url_slug,
                content="<p>Local preview only.</p>",
                excerpt=package.seo.meta_description,
            )
        ),
    )
    monkeypatch.setattr(
        wordpress_publish,
        "_payload_hash",
        lambda _payload: "draft-payload-hash",
    )
    monkeypatch.setattr(
        wordpress_publish,
        "_latest_successful_update_audit",
        lambda _session, _page_id: SimpleNamespace(
            payload_hash="draft-payload-hash"
        ),
    )
    monkeypatch.setattr(
        wordpress_publish,
        "effective_page_qa_state",
        lambda _session, _page: SimpleNamespace(
            ready=True,
            current=True,
            classification="current_pass",
            reasons=[],
        ),
    )

    def local_live_status(_session, page_id):
        nonlocal live_status_stub_calls
        live_status_stub_calls += 1
        return WordPressLiveDraftStatus(
            page_id=page_id,
            wordpress_post_id=8,
            rest_api_reachable=True,
            authenticated=True,
            credentials_present=True,
            wordpress_status="draft",
            is_still_draft=True,
        )

    monkeypatch.setattr(
        wordpress_publish,
        "check_live_wordpress_draft_status",
        local_live_status,
    )

    result = wordpress_publish.dry_run_wordpress_publish(_SessionStub(), 41)
    quality_gate = next(
        gate for gate in result.gate_results if gate.code == "quality_review_no_fails"
    )

    assert result.ready is expected_ready
    assert quality_gate.passed is expected_ready
    assert live_status_stub_calls == 1
