from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.datastructures import Headers

from app.core.config import Settings
from app.models import (
    Brand,
    Business,
    GeneratedPage,
    ImageMetadata,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    PlannedPageMediaRequirement,
    SemanticComponentDefinition,
    Service,
    SitePlan,
    Website,
    WebsiteIdentity,
    WebsiteMediaPlanningRecord,
)
from app.schemas.page_media_planning import (
    PageMediaAssignmentRequest,
    PageMediaPlacementDecisionRequest,
)
from app.schemas.entities import ImageMetadataUpdate
from app.schemas.media import (
    MediaAssignmentOrderRequest,
    MediaAssignmentRequest,
    MediaAssignmentUpdateRequest,
)
from app.api.page_media_routes import (
    assign_page_media,
    list_page_media,
    list_page_media_candidates,
    remove_page_media,
    remove_page_media_assignment,
    reorder_page_media,
    update_page_media,
)
from app.services import page_media_planning as media_planning
from app.services.crud import delete_record, update_record
from app.services.page_media_planning import (
    PAGE_TYPE_MEDIA_CONTRACTS,
    PageMediaPlanningError,
    approve_page_media_asset,
    assign_media_to_requirement,
    create_governed_page_media_asset,
    decide_media_placement,
    effective_media_requirements,
    read_page_media_workspace,
    refresh_site_plan_media_suggestions,
    validate_required_media_for_page,
)
from app.services.website_readiness import evaluate_website_readiness
from app.services.approval_queue import build_approval_queue
from app.services.page_export import build_page_export_package
from app.services.page_qa import evaluate_page_qa, get_page_qa


COMPOSITION_COMPONENT_KEYS_BY_CONTRACT: dict[str, tuple[str, ...]] = {
    "home": ("hero", "trust_license", "content_section", "related_page_links"),
    "about": ("hero", "trust_license", "content_section"),
    "contact": ("hero", "trust_license", "content_section", "contact_pathways"),
    "faq": ("hero", "trust_license", "content_section", "faq"),
    "service": ("hero", "trust_license", "service_summary", "content_section"),
    "service_county": ("hero", "trust_license", "service_summary", "content_section"),
    "city_service": ("hero", "trust_license", "service_summary", "content_section"),
    "informational": ("hero", "trust_license", "content_section"),
}


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _scope(
    session: Session,
    suffix: str | None = None,
    *,
    page_types: tuple[str, ...] = ("home",),
):
    suffix = suffix or uuid4().hex[:8]
    business = Business(
        company_name=f"Page Media {suffix}",
        business_type="Local service business",
        phone="407-555-0100",
        email=f"{suffix}@example.test",
        state="FL",
        license_number=f"LIC-{suffix}",
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id,
        brand_name=f"Page Media Brand {suffix}",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name=f"Page Media Website {suffix}",
        domain=f"{suffix}.example.test",
        public_url=f"https://{suffix}.example.test",
    )
    session.add(website)
    session.flush()
    session.add(
        WebsiteIdentity(
            website_id=website.id,
            display_name=brand.brand_name,
            status="active",
        )
    )
    service = Service(
        business_id=business.id,
        service_name=f"Approved Service {suffix}",
        service_slug=f"approved-service-{suffix}",
        status="active",
    )
    session.add(service)
    session.flush()
    plan = SitePlan(
        website_id=website.id,
        plan_key="primary",
        plan_name="Primary Site Plan",
        status="active",
    )
    session.add(plan)
    session.flush()

    existing_component_keys = {
        row.component_key for row in session.exec(select(SemanticComponentDefinition)).all()
    }
    for component_key in sorted(
        {
            contract["component_or_section"]
            for contracts in PAGE_TYPE_MEDIA_CONTRACTS.values()
            for contract in contracts
        }
        - existing_component_keys
    ):
        session.add(
            SemanticComponentDefinition(
                component_key=component_key,
                contract_version=1,
                purpose=f"Render the approved {component_key} contract.",
                required_inputs=["media_placement"],
                customer_outcome=f"Understand the approved {component_key} information.",
                compatible_page_types=["all"],
                supported_variants=["default", "placeholder", "approved_media"],
                accessibility_requirements=["Provide an accessible media alternative."],
                status="active",
            )
        )
    session.flush()

    pages: list[tuple[PlannedPage, GeneratedPage]] = []
    for index, requested_type in enumerate(page_types):
        page_type = "county" if requested_type == "service_county" else requested_type
        service_id = (
            service.id
            if requested_type in {"service", "service_county", "city_service"}
            else None
        )
        slug = f"{requested_type.replace('_', '-')}-{suffix}-{index}"
        generated = GeneratedPage(
            business_id=business.id,
            website_id=website.id,
            service_id=service_id,
            page_type=page_type,
            page_title=f"{requested_type.title()} {index}",
            page_slug=slug,
            h1=f"{requested_type.title()} {index}",
            draft_content={
                "schema_version": "planned-page-draft-v1",
                "page_type": page_type,
                "title": f"{requested_type.title()} {index}",
                "h1": f"{requested_type.title()} {index}",
                "intro": "Approved information only.",
                "sections": [],
                "faq_items": [],
                "image_placements": [],
                "related_pages": [],
                "call_to_action": "Contact the business.",
                "status": "draft",
            },
            generation_status="generated",
        )
        session.add(generated)
        session.flush()
        planned = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type=page_type,
            working_name=f"{requested_type.title()} {index}",
            intended_slug=slug,
            service_id=service_id,
            generated_page_id=generated.id,
        )
        session.add(planned)
        session.flush()
        session.add(
            PageComposition(
                website_id=website.id,
                site_plan_id=plan.id,
                planned_page_id=planned.id,
                generated_page_id=generated.id,
                generated_components=[
                    {
                        "instance_key": f"{component_key}:{component_index}",
                        "component_key": component_key,
                        "position": component_index,
                    }
                    for component_index, component_key in enumerate(
                        COMPOSITION_COMPONENT_KEYS_BY_CONTRACT[requested_type]
                    )
                ],
                source_snapshot={"baseline": True},
                source_hash="a" * 64,
                status="current",
            )
        )
        pages.append((planned, generated))
    session.commit()
    return business, website, plan, pages


def _decision(
    workspace,
    placement,
    *,
    state: str | None = None,
    operator: str = "Page Media Operator",
    rationale: str = "Approve this placement contract for the selected Website.",
):
    suggestion = placement.suggestion
    assert suggestion is not None
    return PageMediaPlacementDecisionRequest(
        website_id=workspace.website_id,
        site_plan_id=workspace.site_plan_id,
        planned_page_id=placement.planned_page.id,
        placement_key=suggestion["placement_key"],
        requirement_state=state or suggestion["requirement_state"],
        decided_by=operator,
        rationale=rationale,
        expected_planning_version=workspace.planning_record.version,
        source_suggestion_key=suggestion["suggestion_key"],
    )


def _decide_all(
    session: Session,
    plan_id: int,
    workspace,
    *,
    states: dict[str, str] | None = None,
):
    states = states or {}
    for placement in workspace.placements:
        if placement.suggestion is None:
            continue
        payload = _decision(
            workspace,
            placement,
            state=states.get(placement.suggestion["placement_key"]),
        )
        decide_media_placement(session, plan_id, payload)
    return read_page_media_workspace(session, plan_id)


def _image_bytes(size: tuple[int, int] = (1200, 675)) -> bytes:
    target = BytesIO()
    Image.new("RGB", size, "#245b46").save(target, format="PNG")
    return target.getvalue()


def _upload(filename: str, payload: bytes) -> UploadFile:
    return UploadFile(
        file=BytesIO(payload),
        filename=filename,
        headers=Headers({"content-type": "image/png"}),
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        media_root=tmp_path,
        media_public_url="http://testserver/media",
        media_max_upload_bytes=10 * 1024 * 1024,
        media_max_pixels=4_000_000,
    )


def _bind_flo_zone_identity(session: Session, website: Website) -> None:
    website.website_name = "Flo-Zone Tenting"
    website.domain = "www.flo-zonetenting.com"
    website.public_url = "https://www.Flo-ZoneTenting.com"
    session.add(website)
    session.commit()


def _create_asset(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    business_id: int,
    website_id: int,
    media_key: str,
    placement_key: str,
    size: tuple[int, int] = (1200, 675),
    gps_present: bool = False,
):
    settings = _settings(tmp_path)
    monkeypatch.setattr(media_planning, "get_settings", lambda: settings)
    monkeypatch.setattr(
        media_planning,
        "managed_original_contains_gps",
        lambda _filename, _settings_value: gps_present,
    )
    return asyncio.run(
        create_governed_page_media_asset(
            session,
            file=_upload(f"{media_key}.png", _image_bytes(size)),
            website_id=website_id,
            business_id=business_id,
            media_key=media_key,
            image_title=f"Approved {media_key}",
            reviewed_alt_text=f"Approved {media_key} visual",
            acquisition_source="operator_upload",
            creator_source_identity="Company operator",
            provenance_type="company_original",
            provenance_notes="Supplied by the company operator for local governed use.",
            rights_status="owned",
            rights_holder="Company operator",
            rights_notes="Ownership and Website use were explicitly approved.",
            approved_usage=["page_media"],
            prohibited_usage=["website_identity"],
            permitted_placement_keys=[placement_key],
            accessibility_intent="informative",
            created_by="Page Media Operator",
        )
    )


def test_page_type_contracts_are_bounded_and_define_complete_customer_purpose():
    assert set(PAGE_TYPE_MEDIA_CONTRACTS) == {
        "home",
        "about",
        "contact",
        "faq",
        "service",
        "service_county",
        "city_service",
        "informational",
    }
    contract_fields = {
        "placement_key",
        "component_or_section",
        "requirement_state",
        "purpose",
        "customer_outcome",
        "intended_subject",
        "orientation",
        "aspect_ratio",
        "minimum_width",
        "minimum_height",
        "crop_intent",
        "focal_point_intent",
        "responsive_behavior",
        "accessibility_intent",
        "caption_intent",
        "approved_source_constraints",
        "permitted_reuse_policy",
        "replacement_policy",
        "contract_version",
    }
    for page_type, contracts in PAGE_TYPE_MEDIA_CONTRACTS.items():
        assert 1 <= len(contracts) <= 3, page_type
        assert len({item["placement_key"] for item in contracts}) == len(contracts)
        assert all(set(item) == contract_fields for item in contracts)
        assert all(item["requirement_state"] in {"required", "advisory"} for item in contracts)
        assert all(item["purpose"] and item["customer_outcome"] for item in contracts)
        assert all(item["approved_source_constraints"] for item in contracts)

    home_service_overview = next(
        contract
        for contract in PAGE_TYPE_MEDIA_CONTRACTS["home"]
        if contract["placement_key"] == "home-service-overview"
    )
    assert home_service_overview["component_or_section"] == "related_page_links"
    assert "related_page_links" in COMPOSITION_COMPONENT_KEYS_BY_CONTRACT["home"]
    assert "service_summary" not in COMPOSITION_COMPONENT_KEYS_BY_CONTRACT["home"]


def test_flo_zone_media_32_is_excluded_from_compatible_candidate_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, plan, _ = _scope(session, "excluded-candidate")
        _bind_flo_zone_identity(session, website)
        workspace = _decide_all(
            session,
            plan.id,
            refresh_site_plan_media_suggestions(session, plan.id),
        )
        asset = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=business.id,
            website_id=website.id,
            media_key="excluded-media-32",
            placement_key="home-hero",
        )
        asset = approve_page_media_asset(
            session,
            asset.id,
            expected_website_id=website.id,
            expected_business_id=business.id,
            approved_by="Approval Operator",
            expected_media_version=1,
        )
        asset.wordpress_media_id = 32
        session.add(asset)
        session.commit()

        observed = read_page_media_workspace(session, plan.id)
        hero = next(
            item
            for item in observed.placements
            if item.effective_requirement
            and item.effective_requirement.placement_key == "home-hero"
        )
        assert asset.id not in {item.id for item in observed.assets}
        assert asset.id not in hero.compatible_asset_ids
        assert workspace.website_id == observed.website_id


def test_flo_zone_media_32_is_excluded_from_governed_assignment_eligibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, plan, pages = _scope(session, "excluded-governed")
        _bind_flo_zone_identity(session, website)
        workspace = _decide_all(
            session,
            plan.id,
            refresh_site_plan_media_suggestions(session, plan.id),
        )
        requirement = next(
            item
            for item in effective_media_requirements(session, pages[0][0].id)
            if item.placement_key == "home-hero"
        )
        asset = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=business.id,
            website_id=website.id,
            media_key="excluded-governed-32",
            placement_key="home-hero",
        )
        asset = approve_page_media_asset(
            session,
            asset.id,
            expected_website_id=website.id,
            expected_business_id=business.id,
            approved_by="Approval Operator",
            expected_media_version=1,
        )
        asset.wordpress_media_id = 32
        session.add(asset)
        session.commit()

        with pytest.raises(PageMediaPlanningError, match="Website-scoped"):
            assign_media_to_requirement(
                session,
                plan.id,
                requirement.id,
                PageMediaAssignmentRequest(
                    image_metadata_id=asset.id,
                    assigned_by="Assignment Operator",
                    rationale="Attempt the exact approved placement.",
                    expected_requirement_version=requirement.version,
                ),
            )
        assert workspace.summary.approved_assignments == 0


def test_flo_zone_media_32_is_rejected_at_governed_approval_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, _, _ = _scope(session, "excluded-approval")
        _bind_flo_zone_identity(session, website)
        asset = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=business.id,
            website_id=website.id,
            media_key="excluded-approval-32",
            placement_key="home-hero",
        )
        asset.wordpress_media_id = 32
        session.add(asset)
        session.commit()

        with pytest.raises(PageMediaPlanningError, match="Website-scoped"):
            approve_page_media_asset(
                session,
                asset.id,
                expected_website_id=website.id,
                expected_business_id=business.id,
                approved_by="Approval Operator",
                expected_media_version=1,
            )
        assert session.get(ImageMetadata, asset.id).governance_status == "pending_review"


def test_flo_zone_media_32_is_excluded_from_direct_legacy_assignment() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, _, pages = _scope(session, "excluded-legacy")
        _bind_flo_zone_identity(session, website)
        image = ImageMetadata(
            business_id=business.id,
            file_name="excluded-32.png",
            asset_url="/media/excluded-32.png",
            reviewed_alt_text="Excluded external image",
            review_status="reviewed",
            wordpress_media_id=32,
        )
        session.add(image)
        session.commit()

        with pytest.raises(HTTPException, match="Website-scoped"):
            assign_page_media(
                pages[0][1].id,
                "hero",
                MediaAssignmentRequest(image_metadata_id=image.id),
                session,
            )
        assert session.exec(select(PageImageAssignment)).all() == []


def test_flo_zone_media_32_is_not_returned_by_legacy_page_candidate_output() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, _, pages = _scope(session, "excluded-legacy-candidates")
        _bind_flo_zone_identity(session, website)
        eligible = ImageMetadata(
            business_id=business.id,
            file_name="eligible-31.png",
            asset_url="/media/eligible-31.png",
            reviewed_alt_text="Eligible external image",
            review_status="reviewed",
            wordpress_media_id=31,
        )
        excluded = ImageMetadata(
            business_id=business.id,
            file_name="excluded-32.png",
            asset_url="/media/excluded-32.png",
            reviewed_alt_text="Excluded external image",
            review_status="reviewed",
            wordpress_media_id=32,
        )
        session.add(eligible)
        session.add(excluded)
        session.commit()

        candidates = list_page_media_candidates(pages[0][1].id, session)
        assert [item.wordpress_media_id for item in candidates] == [31]


def test_existing_flo_zone_media_32_assignment_blocks_all_read_fallbacks() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, plan, pages = _scope(session, "excluded-read-paths")
        _bind_flo_zone_identity(session, website)
        page = pages[0][1]
        image = ImageMetadata(
            business_id=business.id,
            file_name="excluded-read-path-32.png",
            asset_url="/media/excluded-read-path-32.png",
            reviewed_alt_text="Excluded external image",
            review_status="reviewed",
            wordpress_media_id=32,
        )
        session.add(image)
        session.flush()
        session.add(
            PageImageAssignment(
                generated_page_id=page.id,
                image_metadata_id=image.id,
                image_role="hero",
                status="active",
            )
        )
        session.commit()

        workspace = read_page_media_workspace(session, plan.id)
        assert any(
            "excluded by the Website-scoped" in reason
            for placement in workspace.placements
            for reason in placement.blocking_reasons
        )
        with pytest.raises(HTTPException, match="Website-scoped"):
            list_page_media(page.id, session)
        qa = evaluate_page_qa(session, page.id)
        excluded_check = next(
            item for item in qa.checks if item.key == "excluded_external_media"
        )
        assert excluded_check.status == "fail"
        export = build_page_export_package(session, page.id)
        assert export.assigned_media == []
        assert any(
            warning.code == "excluded_external_media"
            and warning.severity == "blocker"
            for warning in export.warnings
        )
        queue_item = build_approval_queue(
            session,
            website_id=website.id,
        ).items[0]
        assert queue_item.hero_image_status == "excluded"
        assert queue_item.is_ready_for_approval is False
        assert queue_item.has_blockers is True
        assert queue_item.missing_media is True
        report = evaluate_website_readiness(session, plan.id)
        website_category = next(
            item for item in report.categories if item.key == "website_readiness"
        )
        compatibility = next(
            item
            for item in website_category.items
            if item.key == "page_media_assignment_compatibility"
        )
        assert compatibility.status == "needs_attention"
        assert compatibility.affected_planned_page_ids == [pages[0][0].id]


def test_persisted_page_qa_is_not_reused_when_excluded_media_is_active() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, _, pages = _scope(session, "excluded-persisted-qa")
        _bind_flo_zone_identity(session, website)
        page = pages[0][1]
        baseline = evaluate_page_qa(session, page.id)
        page.qa_result = baseline.model_dump(mode="json", exclude={"persisted"})
        page.qa_status = baseline.readiness_status
        page.qa_checked_at = baseline.checked_at
        image = ImageMetadata(
            business_id=business.id,
            file_name="excluded-persisted-qa-32.png",
            asset_url="/media/excluded-persisted-qa-32.png",
            reviewed_alt_text="Excluded persisted QA image",
            review_status="reviewed",
            wordpress_media_id=32,
        )
        session.add(page)
        session.add(image)
        session.flush()
        session.add(
            PageImageAssignment(
                generated_page_id=page.id,
                image_metadata_id=image.id,
                image_role="hero",
                status="active",
            )
        )
        session.commit()

        observed = get_page_qa(session, page.id)
        assert observed.persisted is False
        assert any(
            item.key == "excluded_external_media" and item.status == "fail"
            for item in observed.checks
        )


def test_excluded_legacy_assignment_update_fails_before_mutation() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, _, pages = _scope(session, "excluded-update")
        _bind_flo_zone_identity(session, website)
        page = pages[0][1]
        page.qa_status = "ready"
        image = ImageMetadata(
            business_id=business.id,
            file_name="excluded-update-32.png",
            asset_url="/media/excluded-update-32.png",
            reviewed_alt_text="Excluded external image",
            review_status="reviewed",
            wordpress_media_id=32,
        )
        session.add(page)
        session.add(image)
        session.flush()
        assignment = PageImageAssignment(
            generated_page_id=page.id,
            image_metadata_id=image.id,
            image_role="support",
            sort_order=10,
            status="active",
        )
        session.add(assignment)
        session.commit()

        with pytest.raises(HTTPException, match="Website-scoped"):
            update_page_media(
                page.id,
                assignment.id,
                MediaAssignmentUpdateRequest(sort_order=99),
                session,
            )
        session.refresh(assignment)
        session.refresh(page)
        assert assignment.sort_order == 10
        assert page.qa_status == "ready"


def test_other_website_media_32_remains_assignable_under_existing_rules() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, _, pages = _scope(session, "other-site-media-32")
        assert website.id == 1
        image = ImageMetadata(
            business_id=business.id,
            file_name="other-site-32.png",
            asset_url="/media/other-site-32.png",
            reviewed_alt_text="Other Website approved image",
            review_status="reviewed",
            wordpress_media_id=32,
        )
        session.add(image)
        session.commit()

        assignment = assign_page_media(
            pages[0][1].id,
            "hero",
            MediaAssignmentRequest(image_metadata_id=image.id),
            session,
        )
        assert assignment.image.wordpress_media_id == 32


def test_decided_required_without_assignment_uses_assignment_readiness() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, plan, _ = _scope(session, "missing-assignment-status")
        workspace = _decide_all(
            session,
            plan.id,
            refresh_site_plan_media_suggestions(session, plan.id),
        )
        hero = next(
            item
            for item in workspace.placements
            if item.effective_requirement
            and item.effective_requirement.placement_key == "home-hero"
        )
        advisory = next(
            item
            for item in workspace.placements
            if item.effective_requirement
            and item.effective_requirement.requirement_state == "advisory"
        )
        assert hero.readiness == "awaiting_assignment"
        assert hero.blocking_reasons == [
            "Required media placement has no approved assignment."
        ]
        assert workspace.summary.missing_required_media == 1
        assert advisory.readiness == "advisory_unfilled"
        assert advisory.blocking_reasons == []


def test_unfilled_advisory_stays_advisory_and_nonrequired() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, plan, pages = _scope(session, "advisory-unfilled-status")
        workspace = _decide_all(
            session,
            plan.id,
            refresh_site_plan_media_suggestions(session, plan.id),
            states={"home-hero": "excluded"},
        )
        advisory = next(
            item
            for item in workspace.placements
            if item.effective_requirement
            and item.effective_requirement.requirement_state == "advisory"
        )
        assert advisory.readiness == "advisory_unfilled"
        assert advisory.blocking_reasons == []
        assert workspace.summary.missing_required_media == 0
        assert validate_required_media_for_page(session, pages[0][0]) == []


def test_refresh_creates_versioned_suggestions_without_operator_decisions_for_all_page_types():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, website, plan, pages = _scope(
            session,
            "all-contracts",
            page_types=tuple(PAGE_TYPE_MEDIA_CONTRACTS),
        )
        result = refresh_site_plan_media_suggestions(session, plan.id)
        expected_count = sum(len(value) for value in PAGE_TYPE_MEDIA_CONTRACTS.values())
        assert result.website_id == website.id
        assert result.summary.planned_pages == len(PAGE_TYPE_MEDIA_CONTRACTS)
        assert result.summary.suggested_placements == expected_count
        assert result.planning_record.version == 1
        assert session.exec(select(PlannedPageMediaRequirement)).all() == []
        assert all(item.suggestion["website_id"] == website.id for item in result.placements)
        assert all(item.suggestion["site_plan_id"] == plan.id for item in result.placements)
        assert {
            item.suggestion["contract_page_type"] for item in result.placements
        } == set(PAGE_TYPE_MEDIA_CONTRACTS)
        assert all(
            session.get(PageComposition, index + 1).status == "stale"
            for index, _ in enumerate(pages)
        )

        second = refresh_site_plan_media_suggestions(session, plan.id)
        assert second.planning_record.id == result.planning_record.id
        assert second.planning_record.version == 1
        assert len(session.exec(select(WebsiteMediaPlanningRecord)).all()) == 1


def test_suggestion_and_decision_writes_can_share_one_rollback_safe_transaction():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, plan, _ = _scope(session, "atomic-population")
        workspace = refresh_site_plan_media_suggestions(
            session,
            plan.id,
            commit=False,
        )
        hero = next(
            item
            for item in workspace.placements
            if item.suggestion
            and item.suggestion["placement_key"] == "home-hero"
        )
        result = decide_media_placement(
            session,
            plan.id,
            _decision(workspace, hero, operator="Shawn Manchette"),
            commit=False,
            return_workspace=False,
        )
        assert result is None
        assert len(session.exec(select(WebsiteMediaPlanningRecord)).all()) == 1
        assert len(session.exec(select(PlannedPageMediaRequirement)).all()) == 1

        session.rollback()

        assert session.exec(select(WebsiteMediaPlanningRecord)).all() == []
        assert session.exec(select(PlannedPageMediaRequirement)).all() == []
        composition = session.exec(select(PageComposition)).one()
        assert composition.status == "current"


@pytest.mark.parametrize("contract_page_type", tuple(PAGE_TYPE_MEDIA_CONTRACTS))
def test_every_page_type_requires_target_in_its_exact_composition_before_decision(
    contract_page_type: str,
):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, plan, pages = _scope(
            session,
            f"exact-target-{contract_page_type}",
            page_types=(contract_page_type,),
        )
        workspace = refresh_site_plan_media_suggestions(session, plan.id)
        placement = next(
            item
            for item in workspace.placements
            if item.suggestion
        )
        target = placement.suggestion["component_or_section"]
        assert session.exec(
            select(SemanticComponentDefinition).where(
                SemanticComponentDefinition.component_key == target,
                SemanticComponentDefinition.status == "active",
            )
        ).first()

        composition = session.exec(
            select(PageComposition).where(
                PageComposition.planned_page_id == pages[0][0].id
            )
        ).one()
        composition.generated_components = [
            item
            for item in composition.generated_components
            if item.get("component_key") != target
        ]
        session.add(composition)
        session.commit()

        with pytest.raises(
            PageMediaPlanningError,
            match="exact Planned Page composition",
        ):
            decide_media_placement(
                session,
                plan.id,
                _decision(workspace, placement),
            )
        assert session.exec(select(PlannedPageMediaRequirement)).all() == []

        with pytest.raises(
            PageMediaPlanningError,
            match="exact Planned Page composition",
        ):
            refresh_site_plan_media_suggestions(session, plan.id)


def test_media_planning_rejects_a_target_when_all_exact_instances_are_suppressed():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, plan, pages = _scope(session, "suppressed-exact-target")
        workspace = refresh_site_plan_media_suggestions(session, plan.id)
        placement = next(
            item
            for item in workspace.placements
            if item.suggestion
            and item.suggestion["placement_key"] == "home-service-overview"
        )
        target = placement.suggestion["component_or_section"]
        composition = session.exec(
            select(PageComposition).where(
                PageComposition.planned_page_id == pages[0][0].id
            )
        ).one()
        target_instances = [
            item["instance_key"]
            for item in composition.generated_components
            if item.get("component_key") == target
        ]
        assert target_instances
        composition.operator_decisions = [
            {
                "instance_key": instance_key,
                "action": "suppress",
                "rationale": "Suppress this exact optional component.",
                "provenance": "operator",
            }
            for instance_key in target_instances
        ]
        session.add(composition)
        session.commit()

        with pytest.raises(
            PageMediaPlanningError,
            match="exact Planned Page composition",
        ):
            decide_media_placement(
                session,
                plan.id,
                _decision(workspace, placement),
            )
        assert session.exec(select(PlannedPageMediaRequirement)).all() == []

        with pytest.raises(
            PageMediaPlanningError,
            match="exact Planned Page composition",
        ):
            refresh_site_plan_media_suggestions(session, plan.id)


def test_existing_media_decision_fails_readiness_after_its_target_is_suppressed():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, plan, pages = _scope(session, "suppressed-target-readiness")
        workspace = refresh_site_plan_media_suggestions(session, plan.id)
        placement = next(
            item
            for item in workspace.placements
            if item.suggestion
            and item.suggestion["placement_key"] == "home-service-overview"
        )
        decide_media_placement(
            session,
            plan.id,
            _decision(workspace, placement),
        )
        target = placement.suggestion["component_or_section"]
        composition = session.exec(
            select(PageComposition).where(
                PageComposition.planned_page_id == pages[0][0].id
            )
        ).one()
        composition.operator_decisions = [
            {
                "instance_key": item["instance_key"],
                "action": "suppress",
                "rationale": "Suppress this exact optional component.",
                "provenance": "operator",
            }
            for item in composition.generated_components
            if item.get("component_key") == target
        ]
        assert composition.operator_decisions
        session.add(composition)
        session.commit()

        errors = validate_required_media_for_page(
            session,
            pages[0][0],
            require_approved_assignments=False,
        )
        assert any(
            "home-service-overview target is missing from the exact effective"
            in error
            for error in errors
        )
        refreshed_workspace = read_page_media_workspace(session, plan.id)
        refreshed_placement = next(
            item
            for item in refreshed_workspace.placements
            if item.placement_id
            and item.effective_requirement
            and item.effective_requirement.placement_key
            == "home-service-overview"
        )
        assert refreshed_placement.readiness == "stale"
        assert any(
            "exact effective Planned Page composition" in reason
            for reason in refreshed_placement.blocking_reasons
        )
        assert refreshed_workspace.ready is False
        report = evaluate_website_readiness(session, plan.id)
        website_category = next(
            item for item in report.categories if item.key == "website_readiness"
        )
        media_items = {
            item.key: item
            for item in website_category.items
            if item.key.startswith("page_media_")
        }
        freshness = media_items["page_media_composition_freshness"]
        assert freshness.status == "needs_attention"
        assert freshness.affected_planned_page_ids == [pages[0][0].id]


def test_operator_decisions_preserve_provenance_history_and_remain_separate_from_suggestions():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, plan, _ = _scope(session, "provenance")
        workspace = refresh_site_plan_media_suggestions(session, plan.id)
        hero = next(
            item for item in workspace.placements
            if item.suggestion["placement_key"] == "home-hero"
        )
        original_suggestions = list(workspace.planning_record.generated_media_suggestions)
        payload = _decision(
            workspace,
            hero,
            operator="Shawn Manchette",
            rationale="Approve the authentic Home hero placement contract.",
        ).model_copy(update={
            "approved_source_constraints": [
                *hero.suggestion["approved_source_constraints"],
                "County-specific imagery requires authentic or truthfully licensed evidence.",
            ],
            "permitted_reuse_policy": (
                "Never use the same exact asset twice on one page for different purposes."
            ),
        })
        decided = decide_media_placement(session, plan.id, payload)
        current = next(
            item.effective_requirement for item in decided.placements
            if item.suggestion["placement_key"] == "home-hero"
        )
        assert current.version == 1
        assert current.requirement_state == "required"
        assert current.decided_by == "Shawn Manchette"
        assert current.rationale == "Approve the authentic Home hero placement contract."
        assert current.source_suggestion_key == hero.suggestion["suggestion_key"]
        assert current.planning_record_id == workspace.planning_record.id
        assert current.approved_source_constraints == [
            *hero.suggestion["approved_source_constraints"],
            "County-specific imagery requires authentic or truthfully licensed evidence.",
        ]
        assert current.permitted_reuse_policy == (
            "Never use the same exact asset twice on one page for different purposes."
        )
        assert decided.planning_record.generated_media_suggestions == original_suggestions

        same = decide_media_placement(session, plan.id, payload)
        assert len(session.exec(select(PlannedPageMediaRequirement)).all()) == 1
        assert next(
            item.effective_requirement.id for item in same.placements
            if item.suggestion["placement_key"] == "home-hero"
        ) == current.id

        canonical_same = decide_media_placement(
            session,
            plan.id,
            payload.model_copy(update={"placement_key": "  HOME-HERO  "}),
        )
        assert len(session.exec(select(PlannedPageMediaRequirement)).all()) == 1
        assert next(
            item.effective_requirement.id for item in canonical_same.placements
            if item.suggestion["placement_key"] == "home-hero"
        ) == current.id

        with pytest.raises(PageMediaPlanningError, match="missing active semantic component"):
            decide_media_placement(
                session,
                plan.id,
                payload.model_copy(
                    update={"component_or_section": "unknown-media-region"}
                ),
            )
        assert len(session.exec(select(PlannedPageMediaRequirement)).all()) == 1

        changed = payload.model_copy(
            update={
                "requirement_state": "advisory",
                "rationale": "Retain the placement as an advisory operator decision.",
            }
        )
        decide_media_placement(session, plan.id, changed)
        history = list(
            session.exec(
                select(PlannedPageMediaRequirement).order_by(
                    PlannedPageMediaRequirement.version
                )
            ).all()
        )
        assert [item.version for item in history] == [1, 2]
        assert [item.lifecycle_status for item in history] == ["superseded", "active"]
        assert history[1].replaces_requirement_id == history[0].id


def test_media_plans_and_decisions_fail_closed_across_websites():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, website_a, plan_a, _ = _scope(session, "isolation-a")
        _, website_b, plan_b, pages_b = _scope(session, "isolation-b")
        workspace_a = refresh_site_plan_media_suggestions(session, plan_a.id)
        refresh_site_plan_media_suggestions(session, plan_b.id)
        placement_a = workspace_a.placements[0]
        crossed = _decision(workspace_a, placement_a).model_copy(
            update={
                "website_id": website_b.id,
                "planned_page_id": pages_b[0][0].id,
            }
        )
        with pytest.raises(PageMediaPlanningError, match="crosses"):
            decide_media_placement(session, plan_a.id, crossed)
        assert session.exec(
            select(PlannedPageMediaRequirement).where(
                PlannedPageMediaRequirement.website_id == website_a.id
            )
        ).all() == []
        assert read_page_media_workspace(session, plan_a.id).website_id == website_a.id
        assert read_page_media_workspace(session, plan_b.id).website_id == website_b.id


def test_required_advisory_excluded_and_deferred_semantics_are_deterministic():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, plan, pages = _scope(
            session,
            "states",
            page_types=("home", "about"),
        )
        workspace = refresh_site_plan_media_suggestions(session, plan.id)
        states = {
            "home-hero": "required",
            "home-trust": "advisory",
            "home-service-overview": "deferred",
            "about-company": "excluded",
            "about-trust": "excluded",
        }
        result = _decide_all(session, plan.id, workspace, states=states)
        assert result.summary.required_placements == 1
        assert result.summary.advisory_placements == 1
        assert result.summary.excluded_placements == 2
        assert result.summary.deferred_placements == 1
        assert result.summary.missing_required_media == 1
        by_key = {
            item.suggestion["placement_key"]: item for item in result.placements
        }
        assert by_key["home-hero"].blocking_reasons == [
            "Required media placement has no approved assignment."
        ]
        assert by_key["home-trust"].readiness == "advisory_unfilled"
        assert by_key["home-service-overview"].readiness == "deferred"
        assert by_key["about-company"].readiness == "excluded"
        assert by_key["about-trust"].readiness == "excluded"
        errors = validate_required_media_for_page(session, pages[0][0])
        assert errors == [
            "Required media placement home-hero has no approved assignment."
        ]

        report = evaluate_website_readiness(session, plan.id)
        website_category = next(
            item for item in report.categories if item.key == "website_readiness"
        )
        media_items = {
            item.key: item for item in website_category.items
            if item.key.startswith("page_media_")
        }
        assert media_items["page_media_required_assignments"].status == "needs_attention"
        assert media_items["page_media_required_assignments"].affected_planned_page_ids == [
            pages[0][0].id
        ]
        future = next(item for item in report.categories if item.key == "future_readiness")
        media_ingestion = next(item for item in future.items if item.key == "media_ingestion")
        assert media_ingestion.status == "deferred"


def test_governed_asset_approval_revalidates_rights_binary_identity_and_gps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, _, _ = _scope(session, "governance")
        settings = _settings(tmp_path)
        monkeypatch.setattr(media_planning, "get_settings", lambda: settings)

        with pytest.raises(PageMediaPlanningError, match="inconsistent"):
            asyncio.run(
                create_governed_page_media_asset(
                    session,
                    file=_upload("invalid-source.png", _image_bytes()),
                    website_id=website.id,
                    business_id=business.id,
                    media_key="invalid-source",
                    image_title="Invalid source",
                    reviewed_alt_text="Test image",
                    acquisition_source="generated",
                    creator_source_identity="Company operator",
                    provenance_type="company_original",
                    provenance_notes="This incompatible classification must fail.",
                    rights_status="owned",
                    rights_holder="Company operator",
                    rights_notes="No upload may occur for the invalid combination.",
                    approved_usage=["page_media"],
                    prohibited_usage=["website_identity"],
                    permitted_placement_keys=["home-hero"],
                    accessibility_intent="informative",
                    created_by="Page Media Operator",
                )
            )

        with pytest.raises(PageMediaPlanningError, match="rights holder"):
            asyncio.run(
                create_governed_page_media_asset(
                    session,
                    file=_upload("missing-rights.png", _image_bytes()),
                    website_id=website.id,
                    business_id=business.id,
                    media_key="missing-rights",
                    image_title="Missing rights",
                    reviewed_alt_text="Test image",
                    acquisition_source="operator_upload",
                    creator_source_identity="Company operator",
                    provenance_type="company_original",
                    provenance_notes="Operator-supplied source.",
                    rights_status="owned",
                    rights_holder=" ",
                    rights_notes="Owned by the business.",
                    approved_usage=["page_media"],
                    prohibited_usage=["website_identity"],
                    permitted_placement_keys=["home-hero"],
                    accessibility_intent="informative",
                    created_by="Operator",
                )
            )

        approved = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=business.id,
            website_id=website.id,
            media_key="approved-hero",
            placement_key="home-hero",
        )
        approved = approve_page_media_asset(
            session,
            approved.id,
            expected_website_id=website.id,
            expected_business_id=business.id,
            approved_by="Approval Operator",
            expected_media_version=1,
        )
        assert approved.governance_status == "approved"
        assert approved.approval_version == 1
        assert approved.approved_by == "Approval Operator"
        assert approved.gps_metadata_status == "absent"
        assert approved.gps_metadata == {}

        tampered = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=business.id,
            website_id=website.id,
            media_key="tampered-hero",
            placement_key="home-hero",
        )
        original_path = tmp_path / "originals" / tampered.stored_filename
        original_path.write_bytes(_image_bytes((1201, 675)))
        with pytest.raises(PageMediaPlanningError, match="binary identity"):
            approve_page_media_asset(
                session,
                tampered.id,
                expected_website_id=website.id,
                expected_business_id=business.id,
                approved_by="Approval Operator",
                expected_media_version=1,
            )

        gps = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=business.id,
            website_id=website.id,
            media_key="unverified-gps",
            placement_key="home-hero",
            gps_present=True,
        )
        assert gps.gps_metadata_status == "present_unverified"
        assert gps.gps_metadata == {}
        with pytest.raises(
            PageMediaPlanningError,
            match="incomplete|Unverified GPS",
        ):
            approve_page_media_asset(
                session,
                gps.id,
                expected_website_id=website.id,
                expected_business_id=business.id,
                approved_by="Approval Operator",
                expected_media_version=1,
            )


def test_assignment_requires_exact_current_contract_and_preserves_composition_staleness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, plan, pages = _scope(session, "assignment")
        workspace = refresh_site_plan_media_suggestions(session, plan.id)
        workspace = _decide_all(session, plan.id, workspace)
        requirement = next(
            item for item in effective_media_requirements(session, pages[0][0].id)
            if item.placement_key == "home-hero"
        )
        composition = session.exec(
            select(PageComposition).where(PageComposition.planned_page_id == pages[0][0].id)
        ).one()
        composition.status = "current"
        session.add(composition)
        session.commit()

        legacy = ImageMetadata(
            business_id=business.id,
            file_name="historical.jpg",
            image_title="Historical media",
        )
        session.add(legacy)
        session.flush()
        session.add(
            PageImageAssignment(
                generated_page_id=pages[0][1].id,
                image_metadata_id=legacy.id,
                image_role="hero",
            )
        )
        session.commit()
        assert validate_required_media_for_page(session, pages[0][0]) == [
            "Required media placement home-hero has no approved assignment."
        ]
        before = read_page_media_workspace(session, plan.id)
        hero = next(
            item for item in before.placements
            if item.effective_requirement
            and item.effective_requirement.placement_key == "home-hero"
        )
        assert hero.active_assignment is None
        assert len(hero.legacy_assignments) == 1

        asset = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=business.id,
            website_id=website.id,
            media_key="assignment-hero",
            placement_key="home-hero",
        )
        asset = approve_page_media_asset(
            session,
            asset.id,
            expected_website_id=website.id,
            expected_business_id=business.id,
            approved_by="Approval Operator",
            expected_media_version=1,
        )
        payload = PageMediaAssignmentRequest(
            image_metadata_id=asset.id,
            assigned_by="Assignment Operator",
            rationale="Assign the exact approved media to the exact Home hero contract.",
            expected_requirement_version=requirement.version,
        )
        result = assign_media_to_requirement(
            session,
            plan.id,
            requirement.id,
            payload,
        )
        assignment = next(
            item.active_assignment for item in result.placements
            if item.effective_requirement
            and item.effective_requirement.id == requirement.id
        )
        assert assignment.website_id == website.id
        assert assignment.site_plan_id == plan.id
        assert assignment.planned_page_id == pages[0][0].id
        assert assignment.media_requirement_id == requirement.id
        assert assignment.assignment_version == 1
        assert assignment.media_version == asset.media_version
        assert assignment.placement_contract_version == requirement.contract_version
        assert assignment.assigned_by == "Assignment Operator"
        assert assignment.assignment_rationale.startswith("Assign the exact")
        assert session.get(PageComposition, composition.id).status == "stale"
        assert validate_required_media_for_page(session, pages[0][0]) == []

        repeated = assign_media_to_requirement(
            session,
            plan.id,
            requirement.id,
            payload,
        )
        assert len(
            session.exec(
                select(PageImageAssignment).where(
                    PageImageAssignment.media_requirement_id == requirement.id
                )
            ).all()
        ) == 1
        assert next(
            item.active_assignment.id for item in repeated.placements
            if item.effective_requirement
            and item.effective_requirement.id == requirement.id
        ) == assignment.id

        stale_version = payload.model_copy(update={"expected_requirement_version": 99})
        with pytest.raises(PageMediaPlanningError, match="version changed"):
            assign_media_to_requirement(
                session,
                plan.id,
                requirement.id,
                stale_version,
            )

        hero_placement = next(
            item for item in workspace.placements
            if item.suggestion
            and item.suggestion["placement_key"] == "home-hero"
        )
        decide_media_placement(
            session,
            plan.id,
            _decision(
                workspace,
                hero_placement,
                rationale="Supersede the Home hero placement with a reviewed decision.",
            ),
        )
        requirements = list(
            session.exec(
                select(PlannedPageMediaRequirement).where(
                    PlannedPageMediaRequirement.planned_page_id
                    == pages[0][0].id,
                    PlannedPageMediaRequirement.placement_key == "home-hero",
                ).order_by(PlannedPageMediaRequirement.version)
            ).all()
        )
        assert [item.lifecycle_status for item in requirements] == [
            "superseded",
            "active",
        ]
        replaced_assignment = session.get(PageImageAssignment, assignment.id)
        assert replaced_assignment.status == "replaced"
        assert replaced_assignment.replaced_by == "Page Media Operator"
        assert "Placement decision superseded" in (
            replaced_assignment.replacement_rationale or ""
        )
        assert replaced_assignment.replaced_at is not None


def test_assignment_rejects_cross_website_media_and_excluded_placements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business_a, website_a, plan_a, pages_a = _scope(session, "asset-a")
        business_b, website_b, _, _ = _scope(session, "asset-b")
        workspace = refresh_site_plan_media_suggestions(session, plan_a.id)
        workspace = _decide_all(
            session,
            plan_a.id,
            workspace,
            states={"home-service-overview": "excluded"},
        )
        requirements = {
            item.placement_key: item
            for item in effective_media_requirements(session, pages_a[0][0].id)
        }
        foreign = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=business_b.id,
            website_id=website_b.id,
            media_key="foreign-hero",
            placement_key="home-hero",
        )
        with pytest.raises(PageMediaPlanningError, match="crosses"):
            approve_page_media_asset(
                session,
                foreign.id,
                expected_website_id=website_a.id,
                expected_business_id=business_a.id,
                approved_by="Approval Operator",
                expected_media_version=1,
            )
        foreign = approve_page_media_asset(
            session,
            foreign.id,
            expected_website_id=website_b.id,
            expected_business_id=business_b.id,
            approved_by="Approval Operator",
            expected_media_version=1,
        )
        with pytest.raises(PageMediaPlanningError, match="crosses"):
            assign_media_to_requirement(
                session,
                plan_a.id,
                requirements["home-hero"].id,
                PageMediaAssignmentRequest(
                    image_metadata_id=foreign.id,
                    assigned_by="Assignment Operator",
                    rationale="This cross-Website attempt must be rejected.",
                    expected_requirement_version=requirements["home-hero"].version,
                ),
            )
        with pytest.raises(PageMediaPlanningError, match="Excluded or deferred"):
            assign_media_to_requirement(
                session,
                plan_a.id,
                requirements["home-service-overview"].id,
                PageMediaAssignmentRequest(
                    image_metadata_id=foreign.id,
                    assigned_by="Assignment Operator",
                    rationale="Excluded placements must remain unassigned.",
                    expected_requirement_version=requirements[
                        "home-service-overview"
                    ].version,
                ),
            )
        assert session.exec(
            select(PageImageAssignment).where(
                PageImageAssignment.website_id == pages_a[0][0].website_id
            )
        ).all() == []
        assert business_a.id != business_b.id


def test_generic_image_metadata_mutation_rejects_governed_identity_and_preserves_legacy():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, _, _ = _scope(session, "crud-guard")
        governed = ImageMetadata(
            business_id=business.id,
            website_id=website.id,
            media_key="governed-identity",
            media_version=1,
            file_name="governed.png",
            image_title="Governed identity",
        )
        legacy_update = ImageMetadata(
            business_id=business.id,
            file_name="legacy-update.png",
            image_title="Legacy update",
        )
        legacy_delete = ImageMetadata(
            business_id=business.id,
            file_name="legacy-delete.png",
            image_title="Legacy delete",
        )
        session.add(governed)
        session.add(legacy_update)
        session.add(legacy_delete)
        session.commit()

        with pytest.raises(HTTPException, match="Governed page media") as update_error:
            update_record(
                session,
                ImageMetadata,
                governed.id,
                ImageMetadataUpdate(image_title="Bypass attempt"),
            )
        assert update_error.value.status_code == 409
        assert session.get(ImageMetadata, governed.id).image_title == "Governed identity"
        with pytest.raises(HTTPException, match="Governed page media") as delete_error:
            delete_record(session, ImageMetadata, governed.id)
        assert delete_error.value.status_code == 409
        assert session.get(ImageMetadata, governed.id) is not None

        updated = update_record(
            session,
            ImageMetadata,
            legacy_update.id,
            ImageMetadataUpdate(image_title="Updated legacy title"),
        )
        assert updated.image_title == "Updated legacy title"
        assert delete_record(session, ImageMetadata, legacy_delete.id) == {"ok": True}
        assert session.get(ImageMetadata, legacy_delete.id) is None


def test_legacy_page_media_endpoints_reject_governed_assignment_mutations():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, plan, pages = _scope(session, "assignment-guard")
        workspace = refresh_site_plan_media_suggestions(session, plan.id)
        workspace = _decide_all(session, plan.id, workspace)
        requirement = next(
            item for item in effective_media_requirements(session, pages[0][0].id)
            if item.placement_key == "home-hero"
        )
        image = ImageMetadata(
            business_id=business.id,
            file_name="legacy-source.png",
            image_title="Legacy source",
            reviewed_alt_text="Reviewed legacy source",
            asset_url="http://testserver/media/legacy-source.png",
            review_status="reviewed",
        )
        replacement = ImageMetadata(
            business_id=business.id,
            file_name="legacy-replacement.png",
            image_title="Legacy replacement",
            reviewed_alt_text="Reviewed legacy replacement",
            asset_url="http://testserver/media/legacy-replacement.png",
            review_status="reviewed",
        )
        session.add(image)
        session.add(replacement)
        session.flush()
        governed = PageImageAssignment(
            generated_page_id=pages[0][1].id,
            image_metadata_id=image.id,
            website_id=website.id,
            site_plan_id=plan.id,
            planned_page_id=pages[0][0].id,
            media_requirement_id=requirement.id,
            assignment_version=1,
            media_version=1,
            placement_contract_version=requirement.contract_version,
            assigned_by="Governed assignment operator",
            assignment_rationale="Bind exact governed media contract.",
            assigned_at=datetime.now(UTC),
            image_role="hero",
            status="active",
        )
        session.add(governed)
        session.commit()

        attempts = (
            lambda: update_page_media(
                pages[0][1].id,
                governed.id,
                MediaAssignmentUpdateRequest(sort_order=20),
                session,
            ),
            lambda: remove_page_media_assignment(
                pages[0][1].id,
                governed.id,
                session,
            ),
            lambda: reorder_page_media(
                pages[0][1].id,
                "hero",
                MediaAssignmentOrderRequest(assignment_ids=[governed.id]),
                session,
            ),
            lambda: assign_page_media(
                pages[0][1].id,
                "hero",
                MediaAssignmentRequest(image_metadata_id=replacement.id),
                session,
            ),
            lambda: remove_page_media(
                pages[0][1].id,
                "hero",
                session,
            ),
        )
        for attempt in attempts:
            with pytest.raises(HTTPException, match="Governed page-media assignments") as exc:
                attempt()
            assert exc.value.status_code == 409
        preserved = session.get(PageImageAssignment, governed.id)
        assert preserved is not None
        assert preserved.image_metadata_id == image.id
        assert preserved.sort_order == 0
        assert preserved.status == "active"


def test_legacy_page_media_creation_cannot_bypass_an_established_governed_plan():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, _, plan, pages = _scope(session, "creation-guard")
        refresh_site_plan_media_suggestions(session, plan.id)
        legacy = ImageMetadata(
            business_id=business.id,
            file_name="reviewed-legacy.png",
            image_title="Reviewed legacy media",
            reviewed_alt_text="Reviewed legacy media",
            asset_url="http://testserver/media/reviewed-legacy.png",
            review_status="reviewed",
        )
        session.add(legacy)
        session.commit()

        with pytest.raises(
            HTTPException,
            match="Governed page-media assignments",
        ) as exc:
            assign_page_media(
                pages[0][1].id,
                "hero",
                MediaAssignmentRequest(image_metadata_id=legacy.id),
                session,
            )
        assert exc.value.status_code == 409
        assert session.exec(
            select(PageImageAssignment).where(
                PageImageAssignment.generated_page_id == pages[0][1].id
            )
        ).all() == []


def test_legacy_page_media_update_delete_reorder_and_replacement_remain_compatible():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, _, _, pages = _scope(session, "legacy-compatible")
        images: list[ImageMetadata] = []
        for index in range(3):
            image = ImageMetadata(
                business_id=business.id,
                file_name=f"legacy-{index}.png",
                image_title=f"Legacy {index}",
                reviewed_alt_text=f"Reviewed legacy {index}",
                asset_url=f"http://testserver/media/legacy-{index}.png",
                review_status="reviewed",
            )
            session.add(image)
            session.flush()
            images.append(image)
        hero = PageImageAssignment(
            generated_page_id=pages[0][1].id,
            image_metadata_id=images[0].id,
            image_role="hero",
            sort_order=0,
        )
        support_one = PageImageAssignment(
            generated_page_id=pages[0][1].id,
            image_metadata_id=images[0].id,
            image_role="support",
            sort_order=0,
        )
        support_two = PageImageAssignment(
            generated_page_id=pages[0][1].id,
            image_metadata_id=images[1].id,
            image_role="support",
            sort_order=10,
        )
        session.add(hero)
        session.add(support_one)
        session.add(support_two)
        session.commit()

        updated = update_page_media(
            pages[0][1].id,
            support_one.id,
            MediaAssignmentUpdateRequest(override_alt_text="Operator override"),
            session,
        )
        assert updated.override_alt_text == "Operator override"
        reordered = reorder_page_media(
            pages[0][1].id,
            "support",
            MediaAssignmentOrderRequest(
                assignment_ids=[support_two.id, support_one.id]
            ),
            session,
        )
        assert [item.assignment_id for item in reordered] == [
            support_two.id,
            support_one.id,
        ]
        replaced = assign_page_media(
            pages[0][1].id,
            "hero",
            MediaAssignmentRequest(image_metadata_id=images[2].id),
            session,
        )
        assert replaced.assignment_id == hero.id
        assert replaced.image.id == images[2].id
        assert remove_page_media(pages[0][1].id, "hero", session) == {"ok": True}
        assert session.get(PageImageAssignment, hero.id) is None
        assert remove_page_media_assignment(
            pages[0][1].id,
            support_one.id,
            session,
        ) == {"ok": True}
        assert session.get(PageImageAssignment, support_one.id) is None
        assert session.get(PageImageAssignment, support_two.id) is not None


def test_approval_retry_revalidates_an_already_approved_managed_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, _, _ = _scope(session, "approval-retry")
        asset = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=business.id,
            website_id=website.id,
            media_key="retry-hero",
            placement_key="home-hero",
        )
        approved = approve_page_media_asset(
            session,
            asset.id,
            expected_website_id=website.id,
            expected_business_id=business.id,
            approved_by="Approval Operator",
            expected_media_version=1,
        )
        (tmp_path / "originals" / approved.stored_filename).write_bytes(
            _image_bytes((1201, 675))
        )
        with pytest.raises(PageMediaPlanningError, match="binary identity"):
            approve_page_media_asset(
                session,
                approved.id,
                expected_website_id=website.id,
                expected_business_id=business.id,
                approved_by="Approval Operator",
                expected_media_version=1,
            )


def test_media_planning_refresh_stales_only_the_page_whose_source_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, plan, pages = _scope(
            session,
            "page-scoped-stale",
            page_types=("home", "about"),
        )
        workspace = refresh_site_plan_media_suggestions(session, plan.id)
        workspace = _decide_all(session, plan.id, workspace)
        about_requirement = next(
            item
            for item in effective_media_requirements(session, pages[1][0].id)
            if item.placement_key == "about-company"
        )
        business = session.get(Business, pages[1][1].business_id)
        website = session.get(Website, pages[1][0].website_id)
        assert business and website
        asset = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=business.id,
            website_id=website.id,
            media_key="unaffected-about",
            placement_key="about-company",
        )
        asset = approve_page_media_asset(
            session,
            asset.id,
            expected_website_id=website.id,
            expected_business_id=business.id,
            approved_by="Approval Operator",
            expected_media_version=1,
        )
        assignment_payload = PageMediaAssignmentRequest(
            image_metadata_id=asset.id,
            assigned_by="Assignment Operator",
            rationale="Bind the unaffected About placement.",
            expected_requirement_version=about_requirement.version,
        )
        assigned_workspace = assign_media_to_requirement(
            session,
            plan.id,
            about_requirement.id,
            assignment_payload,
        )
        about_assignment_id = next(
            item.active_assignment.id
            for item in assigned_workspace.placements
            if item.effective_requirement
            and item.effective_requirement.id == about_requirement.id
        )
        compositions = list(
            session.exec(
                select(PageComposition).where(PageComposition.site_plan_id == plan.id)
            ).all()
        )
        for composition in compositions:
            composition.status = "current"
            session.add(composition)
        session.commit()

        pages[0][0].updated_at = datetime.now(UTC)
        session.add(pages[0][0])
        session.commit()
        refreshed = refresh_site_plan_media_suggestions(session, plan.id)
        assert refreshed.planning_record.version == 2

        composition_by_page = {
            item.planned_page_id: item
            for item in session.exec(
                select(PageComposition).where(PageComposition.site_plan_id == plan.id)
            ).all()
        }
        assert composition_by_page[pages[0][0].id].status == "stale"
        assert composition_by_page[pages[1][0].id].status == "current"
        about_placements = [
            item
            for item in refreshed.placements
            if item.planned_page.id == pages[1][0].id
        ]
        assert all(
            all(
                "stale planning version" not in reason
                for reason in item.blocking_reasons
            )
            for item in about_placements
        )
        home_placements = [
            item
            for item in refreshed.placements
            if item.planned_page.id == pages[0][0].id
        ]
        assert any(
            any(
                "stale planning version" in reason
                for reason in item.blocking_reasons
            )
            for item in home_placements
        )
        about_suggestion = next(
            item
            for item in refreshed.placements
            if item.planned_page.id == pages[1][0].id
            and item.suggestion
            and item.suggestion["placement_key"] == "about-company"
        )
        same_decision = _decision(refreshed, about_suggestion)
        unchanged = decide_media_placement(session, plan.id, same_decision)
        unchanged_requirement = next(
            item.effective_requirement
            for item in unchanged.placements
            if item.planned_page.id == pages[1][0].id
            and item.effective_requirement
            and item.effective_requirement.placement_key == "about-company"
        )
        assert unchanged_requirement.id == about_requirement.id
        assert session.get(PageImageAssignment, about_assignment_id).status == "active"
        assert composition_by_page[pages[1][0].id].status == "current"


def test_assignment_rejects_stale_planning_source_and_versions_changed_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, plan, pages = _scope(session, "stale-assignment")
        workspace = refresh_site_plan_media_suggestions(session, plan.id)
        workspace = _decide_all(session, plan.id, workspace)
        requirement = next(
            item
            for item in effective_media_requirements(session, pages[0][0].id)
            if item.placement_key == "home-hero"
        )
        asset = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=business.id,
            website_id=website.id,
            media_key="stale-assignment-hero",
            placement_key="home-hero",
        )
        asset = approve_page_media_asset(
            session,
            asset.id,
            expected_website_id=website.id,
            expected_business_id=business.id,
            approved_by="Approval Operator",
            expected_media_version=1,
        )
        payload = PageMediaAssignmentRequest(
            image_metadata_id=asset.id,
            assigned_by="Assignment Operator",
            rationale="Bind only after a current Page Media assessment.",
            expected_requirement_version=requirement.version,
        )
        pages[0][0].updated_at = datetime.now(UTC)
        session.add(pages[0][0])
        session.commit()
        with pytest.raises(PageMediaPlanningError, match="suggestions are stale"):
            assign_media_to_requirement(
                session,
                plan.id,
                requirement.id,
                payload,
            )
        assert session.exec(
            select(PageImageAssignment).where(
                PageImageAssignment.media_requirement_id == requirement.id
            )
        ).all() == []


def test_assignment_binding_drift_blocks_readiness_and_changed_decision_versions():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, plan, pages = _scope(session, "binding-drift")
        workspace = refresh_site_plan_media_suggestions(session, plan.id)
        workspace = _decide_all(session, plan.id, workspace)
        requirement = next(
            item
            for item in effective_media_requirements(session, pages[0][0].id)
            if item.placement_key == "home-hero"
        )
        asset = ImageMetadata(
            business_id=business.id,
            website_id=website.id,
            media_key="binding-drift-hero",
            media_version=1,
            file_name="binding-drift.png",
            image_title="Binding drift",
            reviewed_alt_text="Approved binding drift visual",
            asset_url="http://testserver/media/optimized/binding-drift.webp",
            optimized_url="http://testserver/media/optimized/binding-drift.webp",
            thumbnail_url="http://testserver/media/thumbnails/binding-drift.webp",
            original_filename="binding-drift.png",
            stored_filename="binding-drift.png",
            managed_storage_path="originals/binding-drift.png",
            mime_type="image/png",
            file_size=100,
            width=1200,
            height=675,
            checksum_sha256="b" * 64,
            acquisition_source="operator_upload",
            creator_source_identity="Company operator",
            created_by="Page Media Operator",
            provenance_type="company_original",
            provenance_notes="Company-supplied governed media.",
            rights_status="owned",
            rights_holder="Company operator",
            rights_notes="Approved for this Website.",
            approved_usage=["page_media"],
            prohibited_usage=["website_identity"],
            permitted_placement_keys=["home-hero"],
            accessibility_intent="informative",
            governance_status="approved",
            approval_version=1,
            approved_by="Approval Operator",
            approved_at=datetime.now(UTC),
            gps_metadata_status="absent",
            gps_metadata={},
            review_status="reviewed",
        )
        session.add(asset)
        session.flush()
        assignment = PageImageAssignment(
            generated_page_id=pages[0][1].id,
            image_metadata_id=asset.id,
            website_id=website.id,
            site_plan_id=plan.id,
            planned_page_id=pages[0][0].id,
            media_requirement_id=requirement.id,
            assignment_version=1,
            media_version=99,
            placement_contract_version=requirement.contract_version,
            assigned_by="Assignment Operator",
            assignment_rationale="A corrupted media-version binding must fail closed.",
            assigned_at=datetime.now(UTC),
            image_role="home-hero:assignment-1",
            status="active",
        )
        session.add(assignment)
        session.commit()

        errors = validate_required_media_for_page(session, pages[0][0])
        assert any("exact approved media version" in error for error in errors)
        observed = read_page_media_workspace(session, plan.id)
        hero = next(
            item
            for item in observed.placements
            if item.effective_requirement
            and item.effective_requirement.id == requirement.id
        )
        assert any(
            "exact approved media version" in error
            for error in hero.blocking_reasons
        )
