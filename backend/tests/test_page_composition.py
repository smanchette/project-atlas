from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.backup import (
    BackupValidationError,
    export_backup,
    load_backup,
    restore_backup,
)
from app.models import (
    Brand,
    BrandAsset,
    Business,
    GeneratedPage,
    ImageMetadata,
    InternalLinkIntent,
    NavigationItem,
    NavigationSet,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    PlannedPageMediaRequirement,
    SemanticComponentDefinition,
    Service,
    SiteConnectionPlanningRecord,
    SitePlan,
    Theme,
    Website,
    WebsiteIdentity,
    WebsiteIdentityAssetAssignment,
    WebsiteMediaPlanningRecord,
    WebsiteCoveragePlanningRecord,
    WebsiteThemeSelection,
)
from app.schemas.page_composition import PageCompositionDecisionUpdate
from app.schemas.page_media_planning import PageMediaPlacementDecisionRequest
from app.services.page_composition import (
    PageCompositionError,
    list_component_registry,
    read_composition_for_generated_page,
    read_site_plan_compositions,
    refresh_site_plan_compositions,
    update_operator_composition_decisions,
)
from app.services.page_qa import effective_page_qa_state, get_page_qa, save_page_qa
from app.services import page_composition as composition_service
from app.services.page_media_planning import (
    decide_media_placement,
    refresh_site_plan_media_suggestions,
    validate_required_media_for_page,
)
from app.services.site_connections import ensure_site_connection_foundation
from app.services.site_coverage import ensure_coverage_foundation
from app.services.themes import (
    DEFAULT_THEME_TOKENS,
    approve_theme,
    create_theme,
    select_website_theme,
)
from app.schemas.themes import ThemeCreate


CONTRACTS = {
    "website_header": (["business_identity", "brand", "website_identity", "contact_information"], ["all"], ["default"]),
    "primary_navigation": (["navigation:primary"], ["all"], ["default"]),
    "utility_navigation": (["navigation:utility"], ["all"], ["default"]),
    "footer_navigation": (["navigation:footer"], ["all"], ["default"]),
    "hero": (["draft:h1", "draft:intro", "contact_information"], ["all"], ["default", "service", "local"]),
    "content_section": (["draft:section"], ["all"], ["default", "muted"]),
    "service_summary": (["service", "draft:section"], ["service", "county", "city_service"], ["default"]),
    "trust_license": (["trust_information"], ["all"], ["default"]),
    "destination_cards": (["related_pages"], ["service", "county", "city_service"], ["default"]),
    "related_page_links": (["related_pages"], ["all"], ["default"]),
    "faq": (["draft:faq_items"], ["all"], ["default"]),
    "contact_pathways": (["website_identity", "contact_information"], ["contact"], ["default"]),
    "media_placement": (["media_placement"], ["all"], ["placeholder", "approved_media"]),
    "final_cta": (["draft:title", "draft:call_to_action", "contact_information"], ["all"], ["default"]),
    "website_footer": (["business_identity", "website_identity"], ["all"], ["default"]),
}


def _engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


def _seed_registry(session: Session):
    for key, (inputs, page_types, variants) in CONTRACTS.items():
        session.add(SemanticComponentDefinition(
            component_key=key,
            contract_version=1,
            purpose=f"Purpose for {key}.",
            required_inputs=inputs,
            customer_outcome=f"Customer outcome for {key}.",
            compatible_page_types=page_types,
            supported_variants=variants,
            accessibility_requirements=[
                "Keyboard accessible.",
                "Visible focus.",
                "Meet WCAG AA contrast.",
                "Usable at mobile, tablet, and desktop widths.",
            ],
        ))
    session.commit()


def _scope(session: Session, *, suffix: str | None = None, phone: str | None = "407-555-0100"):
    suffix = suffix or uuid4().hex[:8]
    business = Business(company_name=f"Composition {suffix}", business_type="Test business", phone=phone, email=f"{suffix}@example.test", state="FL", license_number=f"LIC-{suffix}")
    session.add(business); session.flush()
    brand = Brand(business_id=business.id, brand_name=f"Brand {suffix}", tagline="Approved tagline")
    session.add(brand); session.flush()
    website = Website(business_id=business.id, brand_id=brand.id, website_name=f"Website {suffix}", domain=f"{suffix}.example.test", public_url=f"https://{suffix}.example.test")
    session.add(website); session.flush()
    session.add(WebsiteIdentity(website_id=website.id, display_name=brand.brand_name, status="active"))
    service = Service(business_id=business.id, service_name="Approved Service", service_slug=f"service-{suffix}", status="active")
    session.add(service); session.flush()
    plan = SitePlan(website_id=website.id, plan_key="primary", plan_name="Primary")
    session.add(plan); session.flush()
    ensure_site_connection_foundation(session, plan)
    pages = []
    for index, (page_type, name) in enumerate((("service", "Service"), ("contact", "Contact"))):
        generated = GeneratedPage(
            business_id=business.id,
            website_id=website.id,
            service_id=service.id if page_type == "service" else None,
            page_type=page_type,
            page_title=name,
            page_slug=f"{name.lower()}-{suffix}",
            h1=name,
            draft_content={
                "schema_version": "planned-page-draft-v1", "page_type": page_type,
                "title": name, "meta_title": name, "meta_description": f"Approved {name}",
                "h1": name, "intro": f"Approved introduction for {name}.",
                "sections": (
                    [
                        {
                            "key": "service_overview",
                            "heading": "Overview",
                            "body": "Approved facts only.",
                        },
                        {
                            "key": "approved_guidance",
                            "heading": "Guidance",
                            "body": "Approved guidance only.",
                        },
                    ]
                    if page_type == "service"
                    else [
                        {
                            "key": "ways_to_contact",
                            "heading": "Ways to contact",
                            "body": "Approved contact facts only.",
                        },
                        {
                            "key": "service_area",
                            "heading": "Service area",
                            "body": "Approved service-area facts only.",
                        },
                    ]
                ),
                "faq_items": [{"question": "A question?", "answer": "An approved answer."}] if page_type == "service" else [],
                "image_placements": [{"key": "hero", "purpose": "Support page orientation", "status": "planned"}],
                "related_pages": [], "call_to_action": "Contact the business.", "internal_notes": "",
                "planning_record_id": index + 1, "planning_generated_at": "2026-08-01T00:00:00+00:00",
                "operator_override_keys": [], "status": "draft",
            },
            generation_status="generated",
        )
        session.add(generated); session.flush()
        planned = PlannedPage(website_id=website.id, site_plan_id=plan.id, page_type=page_type, working_name=name, intended_slug=generated.page_slug, service_id=generated.service_id, generated_page_id=generated.id)
        session.add(planned); session.flush(); pages.append((planned, generated))
    sets = {value.set_type: value for value in session.exec(select(NavigationSet).where(NavigationSet.site_plan_id == plan.id)).all()}
    decided_at = datetime(2026, 8, 1, tzinfo=UTC)
    for nav_set in sets.values():
        nav_set.status = "active"
        nav_set.rationale = f"Approve the {nav_set.set_type} navigation set for testing."
        nav_set.decided_by = "Composition Operator"
        nav_set.decision_version = 1
        nav_set.decided_at = decided_at
        session.add(nav_set)
    for index, (planned, _) in enumerate(pages):
        session.add(NavigationItem(
            website_id=website.id,
            site_plan_id=plan.id,
            navigation_set_id=sets["primary"].id,
            target_planned_page_id=planned.id,
            label=planned.working_name,
            position=index,
            status="active",
            rationale="Expose an approved destination in primary navigation.",
            decided_by="Composition Operator",
            decision_version=1,
            decided_at=decided_at,
        ))
    for set_type in ("utility", "footer"):
        session.add(NavigationItem(
            website_id=website.id,
            site_plan_id=plan.id,
            navigation_set_id=sets[set_type].id,
            target_planned_page_id=pages[1][0].id,
            label="Contact",
            position=0,
            status="active",
            rationale=f"Expose Contact in {set_type} navigation.",
            decided_by="Composition Operator",
            decision_version=1,
            decided_at=decided_at,
        ))
    session.add(InternalLinkIntent(
        website_id=website.id,
        site_plan_id=plan.id,
        source_planned_page_id=pages[0][0].id,
        target_planned_page_id=pages[1][0].id,
        purpose="Continue to approved contact options.",
        relationship_type="conversion",
        approval_state="approved",
        rationale="Connect Service visitors to the approved Contact destination.",
        decided_by="Composition Operator",
        decision_version=1,
        decided_at=decided_at,
    ))
    session.commit()
    return website, plan, pages


def _canonical_json_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _export_ready_composition_backup(tmp_path: Path, *, suffix: str) -> dict:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, _ = _scope(session, suffix=suffix)
        result = refresh_site_plan_compositions(session, plan.id)
        assert result.blocked == [] and result.created == 2
        exported = export_backup(session, backup_dir=tmp_path)
    return json.loads(Path(exported["path"]).read_text(encoding="utf-8"))


def _write_backup_payload(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_registry_contracts_define_purpose_inputs_outcome_and_accessibility():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        registry = list_component_registry(session)
        assert {item.component_key for item in registry} == set(CONTRACTS)
        assert all(item.purpose and item.required_inputs and item.customer_outcome for item in registry)
        assert all(item.accessibility_requirements for item in registry)
        assert all(
            any("contrast" in requirement.lower() for requirement in item.accessibility_requirements)
            and any("mobile" in requirement.lower() for requirement in item.accessibility_requirements)
            for item in registry
        )


def test_live_composition_source_drift_invalidates_bound_qa_without_stale_marker():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, pages = _scope(session)
        refresh = refresh_site_plan_compositions(session, plan.id)
        assert refresh.blocked == []
        page = pages[0][1]
        saved = save_page_qa(session, page.id)
        assert saved.page_composition_id is not None
        composition = session.get(PageComposition, saved.page_composition_id)
        assert composition is not None and composition.status == "current"
        stored_source_hash = composition.source_hash
        navigation_item = session.exec(
            select(NavigationItem)
            .where(NavigationItem.site_plan_id == plan.id)
            .order_by(NavigationItem.id)
        ).first()
        assert navigation_item is not None
        navigation_item.label = f"{navigation_item.label} changed"
        navigation_item.updated_at = datetime.now(UTC)
        session.add(navigation_item)
        session.flush()

        state = effective_page_qa_state(session, page.id)

        assert composition.status == "current"
        assert composition.source_hash == stored_source_hash
        assert state.classification == "otherwise_invalid"
        assert "Composition is not authoritative" in state.reasons[0]
        with pytest.raises(HTTPException) as read_error:
            get_page_qa(session, page.id)
        assert read_error.value.status_code == 409
        assert "non-authoritative page identity" in str(read_error.value.detail)
        with pytest.raises(HTTPException) as save_error:
            save_page_qa(session, page.id)
        assert save_error.value.status_code == 409


def test_current_composition_hash_is_stable_when_0045_utc_naive_values_become_aware():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, pages = _scope(session, suffix="utc-aware-current")
        result = refresh_site_plan_compositions(session, plan.id)
        assert result.blocked == []
        composition = session.exec(
            select(PageComposition).where(
                PageComposition.generated_page_id == pages[0][1].id
            )
        ).one()
        source_snapshot = json.loads(json.dumps(composition.source_snapshot))
        source_hash = composition.source_hash
        assert source_snapshot["navigation_sets"][0]["updated_at"].endswith(
            "+00:00"
        ) is False

        for model in (NavigationSet, NavigationItem, InternalLinkIntent):
            for record in session.exec(select(model)).all():
                for field in ("created_at", "updated_at"):
                    value = getattr(record, field)
                    if value.tzinfo is None:
                        setattr(record, field, value.replace(tzinfo=UTC))
                session.add(record)
        session.flush()

        current = read_composition_for_generated_page(session, pages[0][1].id)

        assert current.status == "current"
        assert current.validation_errors == []
        assert current.source_hash == source_hash
        assert current.source_snapshot == source_snapshot
        naive = datetime(2026, 8, 1, 12, 30, 45)
        assert composition_service.canonical_utc_timestamp(naive) == (
            composition_service.canonical_utc_timestamp(
                datetime.fromisoformat("2026-08-01T08:30:45-04:00")
            )
        )


def test_all_0046_converged_backup_timestamps_compare_and_bind_as_utc():
    from app.db import backup as backup_service

    legacy = {}
    aware = {}
    field_count = 0
    for group, fields in backup_service._CONVERGED_UTC_TIMESTAMP_FIELDS.items():
        legacy[group] = [{field: "2026-08-01T12:30:45" for field in fields}]
        aware[group] = [{field: "2026-08-01T08:30:45-04:00" for field in fields}]
        field_count += len(fields)
    assert field_count == 24

    backup_service._canonicalize_converged_utc_timestamps(legacy)
    backup_service._canonicalize_converged_utc_timestamps(aware)
    assert legacy == aware

    for model, fields in backup_service._CONVERGED_UTC_MODEL_FIELDS.items():
        normalized = backup_service._normalize_converged_utc_restore_values(
            model,
            {field: "2026-08-01T12:30:45" for field in fields},
        )
        assert all(
            normalized[field].tzinfo is UTC
            and normalized[field].utcoffset().total_seconds() == 0
            for field in fields
        )


def test_read_rejects_incomplete_generated_component_projection():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, pages = _scope(session, suffix="component-completeness")
        result = refresh_site_plan_compositions(session, plan.id)
        assert result.blocked == []
        composition = session.exec(
            select(PageComposition).where(
                PageComposition.generated_page_id == pages[0][1].id
            )
        ).one()
        composition.generated_components = composition.generated_components[:-1]
        session.add(composition)
        session.flush()

        with pytest.raises(
            PageCompositionError,
            match="head diverges from revision field generated_components",
        ):
            read_composition_for_generated_page(session, pages[0][1].id)


def test_refresh_builds_fact_free_suggestions_and_resolves_approved_inputs():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); website, plan, pages = _scope(session)
        original_draft = dict(pages[0][1].draft_content)
        result = refresh_site_plan_compositions(session, plan.id)
        assert (result.created, result.refreshed, result.blocked) == (2, 0, [])
        service = read_composition_for_generated_page(session, pages[0][1].id)
        assert service.website_id == website.id and service.status == "current"
        assert service.operator_decisions == []
        destinations = next(
            item for item in service.effective_components
            if item.component_key == "destination_cards"
        )
        assert destinations.resolved_data["links"] == [{
            "target_planned_page_id": pages[1][0].id,
            "target_generated_page_id": pages[1][1].id,
            "label": pages[1][0].working_name,
            "slug": pages[1][0].intended_slug,
            "purpose": "Continue to approved contact options.",
            "relationship_type": "conversion",
        }]
        assert any(item.component_key == "media_placement" for item in service.effective_components)
        assert all("company_name" not in item for item in service.generated_components)
        assert any(item.resolved_data.get("company_name") == f"Composition {website.domain.split('.')[0]}" for item in service.effective_components)
        assert session.get(GeneratedPage, pages[0][1].id).draft_content == original_draft
        assert "website_identity_assets" not in session.exec(
            select(PageComposition).where(PageComposition.generated_page_id == pages[0][1].id)
        ).one().source_snapshot
        assert service.source_snapshot["theme"]["mode"] == "neutral_fallback"
        assert service.resolved_theme["fallback_used"] is True


def test_navigation_resolution_preserves_hierarchy_and_preview_target_identity():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix="navigation")
        primary = session.exec(select(NavigationSet).where(
            NavigationSet.site_plan_id == plan.id,
            NavigationSet.set_type == "primary",
        )).one()
        primary_items = list(session.exec(select(NavigationItem).where(
            NavigationItem.navigation_set_id == primary.id,
        ).order_by(NavigationItem.position)).all())
        parent, child = primary_items
        child.parent_navigation_item_id = parent.id
        child.updated_at = datetime(2026, 8, 2, tzinfo=UTC)
        session.add(child)
        utility = session.exec(select(NavigationSet).where(
            NavigationSet.site_plan_id == plan.id,
            NavigationSet.set_type == "utility",
        )).one()
        disabled = session.exec(select(NavigationItem).where(
            NavigationItem.navigation_set_id == utility.id,
        )).one()
        disabled.status = "disabled"
        disabled.rationale = None
        disabled.decided_by = None
        disabled.decision_version = None
        disabled.decided_at = None
        session.add(disabled)
        rejected_link = session.exec(select(InternalLinkIntent).where(
            InternalLinkIntent.site_plan_id == plan.id,
            InternalLinkIntent.approval_state == "approved",
        )).one()
        rejected_link.approval_state = "rejected"
        rejected_link.rationale = None
        rejected_link.decided_by = None
        rejected_link.decision_version = None
        rejected_link.decided_at = None
        session.add(rejected_link)
        session.commit()

        result = refresh_site_plan_compositions(session, plan.id)
        assert result.blocked == []
        composition = read_composition_for_generated_page(session, pages[0][1].id)
        primary_component = next(
            item for item in composition.effective_components
            if item.component_key == "primary_navigation"
        )
        assert primary_component.resolved_data["items"] == [
            {
                "navigation_item_id": parent.id,
                "target_planned_page_id": pages[0][0].id,
                "target_generated_page_id": pages[0][1].id,
                "label": parent.label,
                "slug": pages[0][0].intended_slug,
                "parent_navigation_item_id": None,
                "position": parent.position,
                "status": "active",
            },
            {
                "navigation_item_id": child.id,
                "target_planned_page_id": pages[1][0].id,
                "target_generated_page_id": pages[1][1].id,
                "label": child.label,
                "slug": pages[1][0].intended_slug,
                "parent_navigation_item_id": parent.id,
                "position": child.position,
                "status": "active",
            },
        ]
        utility_component = next(
            item for item in composition.effective_components
            if item.component_key == "utility_navigation"
        )
        assert utility_component.resolved_data["items"] == []
        assert all(
            item["id"] != disabled.id
            for item in composition.source_snapshot["navigation_items"]
        )
        assert composition.source_snapshot["internal_links"] == []
        assert all(
            item.component_key != "destination_cards"
            for item in composition.effective_components
        )


@pytest.mark.parametrize(
    ("duplicate_kind", "expected_reason"),
    [
        (
            "position",
            "Active sibling Navigation Items cannot share the same position.",
        ),
        (
            "label",
            "Active sibling Navigation Items cannot share a case-insensitive label.",
        ),
    ],
)
def test_composition_rejects_duplicate_active_navigation_restored_data(
    duplicate_kind: str,
    expected_reason: str,
):
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, _ = _scope(
            session,
            suffix=f"duplicate-{duplicate_kind}",
        )
        primary = session.exec(select(NavigationSet).where(
            NavigationSet.site_plan_id == plan.id,
            NavigationSet.set_type == "primary",
        )).one()
        parent, sibling = list(session.exec(select(NavigationItem).where(
            NavigationItem.navigation_set_id == primary.id,
        ).order_by(NavigationItem.position)).all())
        if duplicate_kind == "target":
            sibling.target_planned_page_id = parent.target_planned_page_id
        elif duplicate_kind == "position":
            sibling.position = parent.position
        else:
            sibling.label = f"  {parent.label.swapcase()}  "

        # no_autoflush models a raw/restored row that bypassed the normal
        # service and relational constraints while exercising the composition gate.
        with session.no_autoflush:
            result = refresh_site_plan_compositions(session, plan.id, commit=False)
        assert result.created == 0
        assert result.refreshed == 0
        assert result.unchanged == 0
        assert result.blocked
        assert all(item["reason"] == expected_reason for item in result.blocked)
        session.rollback()


@pytest.mark.parametrize("parent_state", ["inactive", "under_governed"])
def test_active_navigation_child_requires_active_governed_parent(parent_state: str):
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, _ = _scope(
            session,
            suffix=f"parent-{parent_state}",
        )
        primary = session.exec(select(NavigationSet).where(
            NavigationSet.site_plan_id == plan.id,
            NavigationSet.set_type == "primary",
        )).one()
        parent, child = list(session.exec(select(NavigationItem).where(
            NavigationItem.navigation_set_id == primary.id,
        ).order_by(NavigationItem.position)).all())
        child.parent_navigation_item_id = parent.id
        if parent_state == "inactive":
            parent.status = "disabled"
            expected_reason = "Active Navigation Item parent is missing or inactive."
        else:
            parent.rationale = None
            parent.decided_by = None
            parent.decision_version = None
            parent.decided_at = None
            expected_reason = (
                "Active Navigation Item parent lacks authoritative operator decision provenance."
            )
        session.add(parent)
        session.add(child)
        session.commit()

        result = refresh_site_plan_compositions(session, plan.id)
        assert result.created == 0
        assert result.blocked
        assert all(item["reason"] == expected_reason for item in result.blocked)


def test_navigation_target_identity_change_stales_and_rebinds_compositions():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix="target-stale")
        initial = refresh_site_plan_compositions(session, plan.id)
        assert initial.created == 2 and initial.blocked == []
        target = pages[1][0]
        before = read_composition_for_generated_page(session, pages[0][1].id)
        target_bindings = [
            item["target"] for item in before.source_snapshot["navigation_items"]
            if item["target"]["planned_page_id"] == target.id
        ]
        assert target_bindings
        assert all(item["generated_page_id"] == pages[1][1].id for item in target_bindings)
        assert all(item["intended_slug"] == target.intended_slug for item in target_bindings)

        target.working_name = "Updated Contact Destination"
        target.intended_slug = "updated-contact-destination"
        session.add(target)
        session.commit()
        with pytest.raises(PageCompositionError, match="stale"):
            read_composition_for_generated_page(session, pages[0][1].id)

        refreshed = refresh_site_plan_compositions(session, plan.id)
        assert refreshed.refreshed == 2 and refreshed.blocked == []
        rebound = read_composition_for_generated_page(session, pages[0][1].id)
        primary = next(
            item for item in rebound.effective_components
            if item.component_key == "primary_navigation"
        )
        rebound_target = next(
            item for item in primary.resolved_data["items"]
            if item["target_planned_page_id"] == target.id
        )
        assert rebound_target["slug"] == "updated-contact-destination"
        assert rebound_target["target_generated_page_id"] == pages[1][1].id


def test_active_navigation_and_approved_links_require_decision_provenance():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, _ = _scope(session, suffix="legacy-nav")
        nav_item = session.exec(select(NavigationItem).where(
            NavigationItem.site_plan_id == plan.id,
            NavigationItem.status == "active",
        )).first()
        nav_item.rationale = None
        nav_item.decided_by = None
        nav_item.decision_version = None
        nav_item.decided_at = None
        session.add(nav_item)
        session.commit()
        result = refresh_site_plan_compositions(session, plan.id)
        assert result.created == 0
        assert all(
            "Navigation Item lacks authoritative operator decision provenance"
            in item["reason"]
            for item in result.blocked
        )

    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix="legacy-link")
        link = session.exec(select(InternalLinkIntent).where(
            InternalLinkIntent.site_plan_id == plan.id,
            InternalLinkIntent.approval_state == "approved",
        )).one()
        link.rationale = None
        link.decided_by = None
        link.decision_version = None
        link.decided_at = None
        session.add(link)
        session.commit()
        result = refresh_site_plan_compositions(session, plan.id)
        blocker = next(
            item for item in result.blocked
            if item["planned_page_id"] == pages[0][0].id
        )
        assert "internal-link intent lacks authoritative operator decision provenance" in blocker["reason"]


def test_approved_internal_links_for_source_cannot_duplicate_target():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix="duplicate-link-target")
        session.add(InternalLinkIntent(
            website_id=plan.website_id,
            site_plan_id=plan.id,
            source_planned_page_id=pages[0][0].id,
            target_planned_page_id=pages[1][0].id,
            purpose="Explain a second approved relationship to the same destination.",
            relationship_type="supporting_information",
            approval_state="approved",
            rationale="Approve the additional relationship for corruption-boundary testing.",
            decided_by="Composition Operator",
            decision_version=1,
            decided_at=datetime(2026, 8, 1, tzinfo=UTC),
        ))
        session.commit()

        result = refresh_site_plan_compositions(session, plan.id)
        blocker = next(
            item for item in result.blocked
            if item["planned_page_id"] == pages[0][0].id
        )
        assert blocker["reason"] == (
            "Approved internal-link intents for one source cannot share a target Planned Page."
        )
        assert session.exec(select(PageComposition).where(
            PageComposition.planned_page_id == pages[0][0].id,
        )).first() is None


def test_navigation_and_link_targets_fail_closed_when_missing_or_cross_scope():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, _ = _scope(session, suffix="bad-nav-target")
        _, _, other_pages = _scope(session, suffix="other-nav-target")
        nav_item = session.exec(select(NavigationItem).where(
            NavigationItem.site_plan_id == plan.id,
            NavigationItem.status == "active",
        )).first()
        nav_item.target_planned_page_id = other_pages[0][0].id
        session.add(nav_item)
        session.commit()
        result = refresh_site_plan_compositions(session, plan.id)
        assert result.created == 0
        assert all("target crosses the Website or Site Plan boundary" in item["reason"] for item in result.blocked)

    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix="missing-link-target")
        link = session.exec(select(InternalLinkIntent).where(
            InternalLinkIntent.site_plan_id == plan.id,
            InternalLinkIntent.approval_state == "approved",
        )).one()
        link.target_planned_page_id = 999_999
        session.add(link)
        session.commit()
        result = refresh_site_plan_compositions(session, plan.id)
        blocker = next(
            item for item in result.blocked
            if item["planned_page_id"] == pages[0][0].id
        )
        assert "target Planned Page is missing" in blocker["reason"]


def test_operator_decisions_remain_separate_and_cannot_fabricate_components():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session)
        refresh_site_plan_compositions(session, plan.id)
        composition = session.exec(select(PageComposition).where(PageComposition.generated_page_id == pages[0][1].id)).one()
        result = update_operator_composition_decisions(session, composition.id, PageCompositionDecisionUpdate(decisions=[{"instance_key": "media_placement:hero", "action": "suppress", "rationale": "Await approved media."}], decided_by="Test Operator"))
        assert result.decided_by == "Test Operator"
        assert result.operator_decisions[0]["provenance"] == "operator"
        assert not any(item.instance_key == "media_placement:hero" for item in result.effective_components)
        refresh_site_plan_compositions(session, plan.id)
        preserved = read_composition_for_generated_page(session, pages[0][1].id)
        assert preserved.operator_decisions == result.operator_decisions
        with pytest.raises(PageCompositionError, match="unknown generated instance"):
            update_operator_composition_decisions(session, composition.id, PageCompositionDecisionUpdate(decisions=[{"instance_key": "fabricated", "action": "suppress"}], decided_by="Test Operator"))


def test_stale_and_cross_website_compositions_fail_closed():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix="first")
        other, other_plan, _ = _scope(session, suffix="second")
        refresh_site_plan_compositions(session, plan.id)
        assert session.exec(
            select(PageComposition).where(PageComposition.site_plan_id == other_plan.id)
        ).first() is None
        generated = pages[0][1]
        generated.draft_content = {**generated.draft_content, "intro": "Changed after composition."}
        session.add(generated); session.commit()
        with pytest.raises(PageCompositionError, match="stale"):
            read_composition_for_generated_page(session, generated.id)
        composition = session.exec(select(PageComposition).where(PageComposition.generated_page_id == generated.id)).one()
        composition.website_id = other.id; session.add(composition); session.commit()
        with pytest.raises(PageCompositionError, match="ownership boundary"):
            read_composition_for_generated_page(session, generated.id)


def test_approved_website_context_change_makes_composition_stale():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix="context")
        refresh_site_plan_compositions(session, plan.id)
        business = session.get(Business, pages[0][1].business_id)
        business.phone = "407-555-0199"; session.add(business); session.commit()
        with pytest.raises(PageCompositionError, match="stale"):
            read_composition_for_generated_page(session, pages[0][1].id)


def test_selected_theme_exact_identity_invalidates_and_rebinds_compositions():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); website, plan, pages = _scope(session, suffix="theme")
        refresh_site_plan_compositions(session, plan.id)
        before = read_composition_for_generated_page(session, pages[0][1].id)
        assert before.source_snapshot["theme"]["mode"] == "neutral_fallback"

        theme = create_theme(
            session,
            website.id,
            ThemeCreate(
                theme_key="approved-theme",
                theme_name="Approved Theme",
                design_tokens=DEFAULT_THEME_TOKENS,
                created_by="Theme Operator",
                provenance_type="operator_configured",
                provenance_notes="Approved test Theme configuration.",
            ),
        )
        approve_theme(session, theme.id, approved_by="Theme Approver")
        selection = select_website_theme(
            session,
            website.id,
            theme_id=theme.id,
            selected_by="Theme Operator",
            rationale="Select the approved Website presentation.",
        )
        with pytest.raises(PageCompositionError, match="stale"):
            read_composition_for_generated_page(session, pages[0][1].id)

        result = refresh_site_plan_compositions(session, plan.id)
        assert result.refreshed == 2 and result.blocked == []
        after = read_composition_for_generated_page(session, pages[0][1].id)
        binding = after.source_snapshot["theme"]
        assert binding == {
            "mode": "selected",
            "website_id": website.id,
            "theme_id": theme.id,
            "theme_key": theme.theme_key,
            "theme_version": theme.version,
            "token_contract_version": theme.token_contract_version,
            "token_hash_sha256": theme.token_hash_sha256,
            "selection_id": selection.id,
            "selection_version": selection.version,
        }
        assert after.resolved_theme["fallback_used"] is False
        assert after.resolved_theme["effective_tokens"]["colors"]["background"] == "#FFFFFF"


def test_invalid_cross_website_theme_selection_fails_composition_closed():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); website, plan, _ = _scope(session, suffix="theme-owner")
        other, _, _ = _scope(session, suffix="theme-other")
        theme = create_theme(
            session,
            other.id,
            ThemeCreate(
                theme_key="other-theme",
                theme_name="Other Theme",
                design_tokens=DEFAULT_THEME_TOKENS,
                created_by="Theme Operator",
                provenance_type="operator_configured",
                provenance_notes="Second Website Theme.",
            ),
        )
        approve_theme(session, theme.id, approved_by="Theme Approver")
        session.add(WebsiteThemeSelection(
            website_id=website.id,
            theme_id=theme.id,
            version=1,
            status="active",
            selected_by="Corrupt fixture",
            rationale="Exercise fail-closed ownership validation.",
        ))
        session.commit()
        result = refresh_site_plan_compositions(session, plan.id)
        assert result.created == 0
        assert result.blocked
        assert all("crosses a Website" in item["reason"] for item in result.blocked)


def test_missing_required_approved_contact_input_blocks_composition():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix="missing", phone=None)
        business = session.get(Business, pages[0][1].business_id)
        business.email = None; session.add(business); session.commit()
        result = refresh_site_plan_compositions(session, plan.id)
        assert result.created == 0
        assert len(result.blocked) == 2
        assert all("contact_information" in item["reason"] for item in result.blocked)


@pytest.mark.parametrize(
    "page_type",
    ["home", "about", "contact", "service", "county", "informational", "faq"],
)
def test_supported_planned_page_types_use_the_same_component_registry(page_type):
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix=page_type)
        planned, generated = pages[0]
        planned.page_type = page_type
        generated.page_type = page_type
        generated.service_id = generated.service_id if page_type in {"service", "county"} else None
        planned.service_id = generated.service_id
        generated.draft_content = {**generated.draft_content, "page_type": page_type}
        session.add(planned); session.add(generated); session.commit()
        result = refresh_site_plan_compositions(session, plan.id)
        assert not any(item["planned_page_id"] == planned.id for item in result.blocked)
        composition = read_composition_for_generated_page(session, generated.id)
        assert composition.effective_components[0].component_key == "website_header"
        assert composition.effective_components[-1].component_key == "website_footer"


def test_legacy_city_service_draft_composes_without_rewriting_content():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix="legacy")
        planned, generated = pages[0]
        legacy = {
            "title": "Legacy City Service", "h1": "Legacy City Service",
            "intro": "Approved legacy introduction.", "why_it_matters": "Approved local value.",
            "process_section": "Approved process.", "faq_items": [{"question": "Question?", "answer": "Answer."}],
            "call_to_action": "Call for approved service.",
        }
        planned.page_type = "city_service"; generated.page_type = "city_service"; generated.draft_content = legacy
        session.add(planned); session.add(generated); session.commit()
        refresh_site_plan_compositions(session, plan.id)
        composition = read_composition_for_generated_page(session, generated.id)
        assert any(item.component_key == "service_summary" for item in composition.effective_components)
        assert session.get(GeneratedPage, generated.id).draft_content == legacy


def test_approved_draft_related_pages_render_without_creating_link_decisions():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix="draft-links")
        planned, generated = pages[0]
        target = pages[1][0]
        for link in session.exec(select(InternalLinkIntent)).all():
            session.delete(link)
        generated.draft_content = {
            **generated.draft_content,
            "related_pages": [{"label": target.working_name, "slug": target.intended_slug}],
        }
        session.add(generated); session.commit()

        result = refresh_site_plan_compositions(session, plan.id)
        assert result.blocked == []
        composition = read_composition_for_generated_page(session, generated.id)
        destinations = next(
            item for item in composition.effective_components
            if item.component_key == "destination_cards"
        )
        assert destinations.resolved_data["links"] == [{
            "target_planned_page_id": target.id,
            "target_generated_page_id": target.generated_page_id,
            "label": target.working_name,
            "slug": target.intended_slug,
            "purpose": "Explore approved related service information.",
            "relationship_type": "approved_draft_relationship",
        }]
        assert session.exec(select(InternalLinkIntent)).all() == []


def test_approved_draft_related_page_outside_the_site_plan_fails_closed():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix="bad-draft-link")
        _, other_plan, other_pages = _scope(session, suffix="other-draft-link")
        generated = pages[0][1]
        generated.draft_content = {
            **generated.draft_content,
            "related_pages": [{
                "label": other_pages[0][0].working_name,
                "slug": other_pages[0][0].intended_slug,
            }],
        }
        session.add(generated); session.commit()

        result = refresh_site_plan_compositions(session, plan.id)
        blocker = next(item for item in result.blocked if item["planned_page_id"] == pages[0][0].id)
        assert "crosses the Website boundary" in blocker["reason"]
        assert session.exec(
            select(PageComposition).where(PageComposition.site_plan_id == other_plan.id)
        ).all() == []


def test_existing_reviewed_media_is_consumed_without_becoming_component_owned():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix="media")
        generated = pages[0][1]
        image = ImageMetadata(
            business_id=generated.business_id,
            file_name="approved.webp",
            asset_url="/media/approved.webp",
            reviewed_alt_text="Approved service photograph",
            review_status="reviewed",
        )
        session.add(image); session.flush()
        assignment = PageImageAssignment(
            generated_page_id=generated.id,
            image_metadata_id=image.id,
            image_role="hero",
            status="active",
        )
        session.add(assignment); session.commit()
        refresh_site_plan_compositions(session, plan.id)
        composition = read_composition_for_generated_page(session, generated.id)
        media = next(
            item for item in composition.effective_components
            if item.instance_key == f"media_placement:assignment-{assignment.id}"
        )
        assert media.variant == "approved_media"
        assert media.resolved_data["asset_url"] == "/media/approved.webp"
        generated_record = next(
            item for item in composition.generated_components
            if item["instance_key"] == media.instance_key
        )
        assert "asset_url" not in generated_record


def test_flo_zone_media_32_is_excluded_from_legacy_composition_fallback():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        website, plan, pages = _scope(session, suffix="excludedlegacy32")
        website.website_name = "Flo-Zone Tenting"
        website.domain = "www.flo-zonetenting.com"
        website.public_url = "https://www.Flo-ZoneTenting.com"
        generated = pages[0][1]
        image = ImageMetadata(
            business_id=generated.business_id,
            file_name="excluded-32.webp",
            asset_url="/media/excluded-32.webp",
            reviewed_alt_text="Excluded external media",
            review_status="reviewed",
            wordpress_media_id=32,
        )
        session.add(website)
        session.add(image)
        session.flush()
        assignment = PageImageAssignment(
            generated_page_id=generated.id,
            image_metadata_id=image.id,
            image_role="hero",
            status="active",
        )
        session.add(assignment)
        session.commit()

        refresh_site_plan_compositions(session, plan.id)
        composition = read_composition_for_generated_page(session, generated.id)
        assert not any(
            item.input_bindings.get("page_image_assignment_id") == assignment.id
            for item in composition.effective_components
        )
        assert not any(
            item["image_metadata_id"] == image.id
            for item in composition.source_snapshot["media_assignments"]
        )


def test_flo_zone_media_32_fails_closed_in_generic_composition_resolution():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        website, plan, pages = _scope(session, suffix="excludedresolve32")
        website.website_name = "Flo-Zone Tenting"
        website.domain = "www.flo-zonetenting.com"
        website.public_url = "https://www.Flo-ZoneTenting.com"
        generated = pages[0][1]
        image = ImageMetadata(
            business_id=generated.business_id,
            file_name="excluded-resolution-32.webp",
            asset_url="/media/excluded-resolution-32.webp",
            reviewed_alt_text="Excluded external media",
            review_status="reviewed",
            wordpress_media_id=32,
        )
        session.add(website)
        session.add(image)
        session.flush()
        assignment = PageImageAssignment(
            generated_page_id=generated.id,
            image_metadata_id=image.id,
            image_role="hero",
            status="active",
        )
        session.add(assignment)
        session.commit()
        refresh_site_plan_compositions(session, plan.id)
        composition = session.exec(
            select(PageComposition).where(
                PageComposition.generated_page_id == generated.id
            )
        ).one()

        with pytest.raises(PageCompositionError, match="Website-scoped"):
            composition_service._resolve_instance(
                session,
                composition,
                generated,
                {
                    "instance_key": "media_placement:forced-32",
                    "component_key": "media_placement",
                    "contract_version": 1,
                    "region": "main",
                    "position": 99,
                    "variant": "approved_media",
                    "input_bindings": {
                        "page_image_assignment_id": assignment.id,
                    },
                },
            )


def test_scoped_media_exclusion_does_not_change_website_identity_assets():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        website, plan, pages = _scope(session, suffix="identitypreserved")
        website.website_name = "Flo-Zone Tenting"
        website.domain = "www.flo-zonetenting.com"
        website.public_url = "https://www.Flo-ZoneTenting.com"
        identity = session.exec(
            select(WebsiteIdentity).where(WebsiteIdentity.website_id == website.id)
        ).one()
        asset = BrandAsset(
            business_id=website.business_id,
            brand_id=website.brand_id,
            asset_key="preserved-logo",
            version=1,
            asset_type="primary_logo",
            variant_key="default",
            purpose="Identify the approved Website Brand.",
            approved_usage=["website_header"],
            restrictions=["social_preview"],
            accessibility_description="Approved preserved logo",
            original_filename="preserved-logo.png",
            stored_filename="preserved-logo.png",
            asset_url="/media/preserved-logo.webp",
            optimized_url="/media/preserved-logo.webp",
            mime_type="image/png",
            file_size=100,
            width=400,
            height=120,
            checksum_sha256="e" * 64,
            provenance_type="company_original",
            rights_status="owned",
            status="approved",
            created_by="Identity Operator",
            approved_by="Identity Operator",
        )
        session.add(website)
        session.add(asset)
        session.flush()
        identity_assignment = WebsiteIdentityAssetAssignment(
            website_identity_id=identity.id,
            website_id=website.id,
            brand_id=website.brand_id,
            brand_asset_id=asset.id,
            slot="header_logo",
            version=1,
            status="active",
            assigned_by="Identity Operator",
        )
        session.add(identity_assignment)
        session.commit()

        refresh_site_plan_compositions(session, plan.id)
        composition = read_composition_for_generated_page(
            session,
            pages[0][1].id,
        )
        header = next(
            item
            for item in composition.effective_components
            if item.component_key == "website_header"
        )
        assert header.resolved_data["identity_assets"]["header_logo"][
            "asset_id"
        ] == asset.id
        assert len(session.exec(select(BrandAsset)).all()) == 1
        assert len(session.exec(select(WebsiteIdentityAssetAssignment)).all()) == 1


def test_approved_website_identity_asset_is_consumed_and_invalidates_stale_composition():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); website, plan, pages = _scope(session, suffix="identityasset")
        refresh_site_plan_compositions(session, plan.id)
        generated = pages[0][1]
        identity = session.exec(select(WebsiteIdentity).where(WebsiteIdentity.website_id == website.id)).one()
        asset = BrandAsset(
            business_id=website.business_id, brand_id=website.brand_id,
            asset_key="primary-logo", version=1, asset_type="primary_logo",
            variant_key="default", purpose="Identify the approved Brand.",
            approved_usage=["website_header"], restrictions=["social_preview"],
            accessibility_description="Approved company logo", original_filename="logo.png",
            stored_filename="logo.png", asset_url="/media/logo.webp",
            optimized_url="/media/logo.webp", mime_type="image/png", file_size=100,
            width=400, height=120, checksum_sha256="b" * 64,
            provenance_type="company_original", rights_status="owned", status="approved",
            created_by="Operator", approved_by="Operator",
        )
        session.add(asset); session.flush()
        session.add(WebsiteIdentityAssetAssignment(
            website_identity_id=identity.id, website_id=website.id,
            brand_id=website.brand_id, brand_asset_id=asset.id,
            slot="header_logo", version=1, status="active", assigned_by="Operator",
        ))
        session.commit()
        with pytest.raises(PageCompositionError, match="authoritative source changed"):
            read_composition_for_generated_page(session, generated.id)
        refresh_site_plan_compositions(session, plan.id)
        composition = read_composition_for_generated_page(session, generated.id)
        header = next(item for item in composition.effective_components if item.component_key == "website_header")
        assert header.resolved_data["identity_assets"]["header_logo"]["asset_url"] == "/media/logo.webp"
        assert "purpose" not in header.resolved_data["identity_assets"]["header_logo"]


def test_incompatible_active_identity_asset_selection_fails_composition_closed():
    engine = _engine(); SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session); website, plan, _ = _scope(session, suffix="invalididentityasset")
        identity = session.exec(select(WebsiteIdentity).where(WebsiteIdentity.website_id == website.id)).one()
        asset = BrandAsset(
            business_id=website.business_id, brand_id=website.brand_id,
            asset_key="browser-favicon", version=1, asset_type="favicon",
            variant_key="default", purpose="Identify a browser tab.",
            approved_usage=["browser_tab"], restrictions=[],
            accessibility_description="Temporary browser identity", original_filename="favicon.png",
            stored_filename="favicon.png", asset_url="/media/favicon.png",
            optimized_url="/media/favicon.webp", mime_type="image/png", file_size=100,
            width=32, height=32, checksum_sha256="c" * 64,
            provenance_type="company_original", rights_status="owned", status="approved",
            created_by="Operator", approved_by="Operator",
        )
        session.add(asset); session.flush()
        session.add(WebsiteIdentityAssetAssignment(
            website_identity_id=identity.id, website_id=website.id,
            brand_id=website.brand_id, brand_asset_id=asset.id,
            slot="header_logo", version=1, status="active", assigned_by="Operator",
        ))
        session.commit()
        result = refresh_site_plan_compositions(session, plan.id)
        assert result.created == 0
        assert result.blocked
        assert all(
            "invalid or crosses an ownership boundary" in item["reason"]
            for item in result.blocked
        )


def test_backup_051_round_trip_preserves_assets_theme_and_scoped_compositions(tmp_path):
    source_engine = _engine(); SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_registry(session); website, plan, _ = _scope(session, suffix="backup")
        identity = session.exec(
            select(WebsiteIdentity).where(WebsiteIdentity.website_id == website.id)
        ).one()
        from app.db import backup as backup_service
        media_public_base = str(backup_service.get_settings().media_public_url).rstrip("/")
        asset = BrandAsset(
            business_id=website.business_id, brand_id=website.brand_id,
            asset_key="backup-logo", version=1, asset_type="primary_logo",
            variant_key="default", purpose="Identify the Website Brand.",
            approved_usage=["website_header"], restrictions=["social_preview"],
            accessibility_description="Approved test logo", original_filename="backup-logo.png",
            stored_filename="backup-logo.png",
            asset_url=f"{media_public_base}/originals/backup-logo.png",
            optimized_url=f"{media_public_base}/optimized/backup-logo-optimized.webp",
            thumbnail_url=f"{media_public_base}/thumbnails/backup-logo-thumbnail.webp",
            mime_type="image/png", file_size=100,
            width=400, height=120, checksum_sha256="d" * 64,
            provenance_type="company_original", provenance_notes="Approved test source.",
            rights_status="owned", rights_holder="Test Owner", rights_notes="Owned test fixture.",
            status="approved", created_by="Operator", approved_by="Operator",
            approved_at=datetime.now(UTC),
        )
        session.add(asset); session.flush()
        session.add(WebsiteIdentityAssetAssignment(
            website_identity_id=identity.id, website_id=website.id,
            brand_id=website.brand_id, brand_asset_id=asset.id,
            slot="header_logo", version=1, status="active",
            assigned_by="Operator", rationale="Approved Website header identity.",
        ))
        session.commit()
        theme = create_theme(
            session,
            website.id,
            ThemeCreate(
                theme_key="backup-theme", theme_name="Backup Theme",
                design_tokens=DEFAULT_THEME_TOKENS,
                created_by="Theme Operator", provenance_type="operator_configured",
                provenance_notes="Backup round-trip Theme.",
            ),
        )
        approve_theme(session, theme.id, approved_by="Theme Approver")
        selection = select_website_theme(
            session, website.id, theme_id=theme.id,
            selected_by="Theme Operator", rationale="Backup round-trip selection.",
        )
        ensure_coverage_foundation(session, plan)
        refresh_site_plan_compositions(session, plan.id)
        website_id = website.id
        source_composition_identity = {
            row.id: (
                row.composition_version,
                row.status,
                row.source_hash,
            )
            for row in session.exec(select(PageComposition)).all()
        }
        exported = export_backup(session, backup_dir=tmp_path)
        source_data = load_backup(Path(exported["path"]))["data"]
        deterministic_groups = (
            "site_connection_planning_records",
            "website_coverage_planning_records",
            "navigation_sets",
            "navigation_items",
            "internal_link_intents",
        )
        source_deterministic_state = {
            group: source_data[group] for group in deterministic_groups
        }
        assert source_data["site_connection_planning_records"][0][
            "source_snapshot"
        ]["planned_pages"] == []
        for group in (
            "navigation_sets",
            "navigation_items",
            "internal_link_intents",
        ):
            assert all(
                record["decided_at"] is None
                or record["decided_at"].endswith("Z")
                for record in source_data[group]
            )
        assert exported["table_counts"]["website_identity_asset_assignments"] == 1
        assert exported["table_counts"]["themes"] == 1
        assert exported["table_counts"]["website_theme_selections"] == 1
        assert exported["table_counts"]["semantic_component_definitions"] == 15
        assert exported["table_counts"]["page_compositions"] == 2

    restored_engine = _engine(); SQLModel.metadata.create_all(restored_engine)
    with Session(restored_engine) as session:
        restored = restore_backup(session, exported["path"])
        assert restored["status"] == "restored"
        assert len(session.exec(select(SemanticComponentDefinition)).all()) == 15
        rows = list(session.exec(select(PageComposition)).all())
        assert len(rows) == 2
        assert {
            row.id: (
                row.composition_version,
                row.status,
                row.source_hash,
            )
            for row in rows
        } == source_composition_identity
        assert all(row.website_id == website_id for row in rows)
        assert len(session.exec(select(WebsiteIdentityAssetAssignment)).all()) == 1
        restored_theme = session.exec(select(Theme)).one()
        restored_selection = session.exec(select(WebsiteThemeSelection)).one()
        assert restored_theme.token_hash_sha256 == theme.token_hash_sha256
        assert restored_selection.version == selection.version
        restored_composition = read_composition_for_generated_page(
            session, rows[0].generated_page_id
        )
        assert restored_composition.source_snapshot["theme"]["theme_id"] == restored_theme.id
        assert restored_composition.source_snapshot["theme"]["selection_id"] == restored_selection.id
        assert backup_service._restore_managed_tables_match_backup(
            session,
            source_data,
        )
        for model, fields in backup_service._CONVERGED_UTC_MODEL_FIELDS.items():
            for record in session.exec(select(model)).all():
                for field in fields:
                    value = getattr(record, field)
                    if value is not None and value.tzinfo is None:
                        setattr(record, field, value.replace(tzinfo=UTC))
                session.add(record)
        session.flush()
        assert backup_service._restore_managed_tables_match_backup(
            session,
            source_data,
        )
        first_reexport = export_backup(session, backup_dir=tmp_path)
        first_data = load_backup(Path(first_reexport["path"]))["data"]
        assert {
            group: first_data[group] for group in deterministic_groups
        } == source_deterministic_state
        restore_backup(session, exported["path"])
        assert {
            row.id: (
                row.composition_version,
                row.status,
                row.source_hash,
            )
            for row in session.exec(select(PageComposition)).all()
        } == source_composition_identity
        second_reexport = export_backup(session, backup_dir=tmp_path)
        second_data = load_backup(Path(second_reexport["path"]))["data"]
        assert {
            group: second_data[group] for group in deterministic_groups
        } == source_deterministic_state
        assert session.exec(select(SiteConnectionPlanningRecord)).one().model_dump(
            mode="json"
        )["source_snapshot"]["planned_pages"] == []
        assert session.exec(select(WebsiteCoveragePlanningRecord)).one()

    legacy_payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    legacy_payload["metadata"]["version"] = "0.56"
    for group in (
        "theme_families",
        "theme_family_versions",
        "website_theme_configurations",
        "website_theme_component_configurations",
        "theme_configuration_audits",
    ):
        assert legacy_payload["data"].pop(group) == []
        assert legacy_payload["metadata"]["table_counts"].pop(group) == 0
    legacy_payload["data"].pop("page_composition_revisions")
    legacy_payload["metadata"]["table_counts"].pop(
        "page_composition_revisions"
    )
    legacy_path = tmp_path / "atlas-backup-legacy-056.json"
    legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    legacy_source_data = load_backup(legacy_path)["data"]

    legacy_engine = _engine(); SQLModel.metadata.create_all(legacy_engine)
    with Session(legacy_engine) as session:
        restore_backup(session, legacy_path)
        restore_backup(session, legacy_path)
        legacy_reexport = export_backup(session, backup_dir=tmp_path)
        legacy_restored_data = load_backup(Path(legacy_reexport["path"]))["data"]
        assert {
            group: legacy_restored_data[group] for group in deterministic_groups
        } == {
            group: legacy_source_data[group] for group in deterministic_groups
        }


@pytest.mark.parametrize(
    "corruption",
    ("changed_snapshot_field", "missing_snapshot_field", "missing_component"),
)
def test_backup_057_identity_shortcut_rebuilds_divergent_projection(
    tmp_path: Path,
    corruption: str,
):
    payload = _export_ready_composition_backup(
        tmp_path,
        suffix=f"projection-{corruption}",
    )
    source = payload["data"]["page_compositions"][0]
    expected_snapshot = json.loads(json.dumps(source["source_snapshot"]))
    expected_components = json.loads(json.dumps(source["generated_components"]))
    expected_hash = source["source_hash"]
    expected_version = source["composition_version"]
    if corruption == "changed_snapshot_field":
        source["source_snapshot"]["navigation_sets"][0]["label"] = "Tampered"
        source["source_hash"] = _canonical_json_hash(source["source_snapshot"])
    elif corruption == "missing_snapshot_field":
        source["source_snapshot"]["navigation_sets"][0].pop("label")
        source["source_hash"] = _canonical_json_hash(source["source_snapshot"])
    else:
        source["generated_components"].pop()
    path = _write_backup_payload(
        tmp_path,
        f"divergent-{corruption}.json",
        payload,
    )
    with pytest.raises(
        BackupValidationError,
        match="current row does not exactly mirror its history tip",
    ):
        load_backup(path)


def test_backup_057_identity_shortcut_rebuilds_after_draft_source_tamper(
    tmp_path: Path,
):
    payload = _export_ready_composition_backup(tmp_path, suffix="draft-tamper")
    source = payload["data"]["page_compositions"][0]
    generated = next(
        record
        for record in payload["data"]["generated_pages"]
        if record["id"] == source["generated_page_id"]
    )
    prior_draft_hash = source["source_snapshot"]["draft_hash"]
    generated["draft_content"]["h1"] = "Changed authoritative heading"
    path = _write_backup_payload(tmp_path, "draft-source-tamper.json", payload)
    load_backup(path)

    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        restore_backup(session, path)
        restored = session.get(PageComposition, source["id"])
        assert restored is not None
        assert restored.source_snapshot["draft_hash"] == _canonical_json_hash(
            generated["draft_content"]
        )
        assert restored.source_snapshot["draft_hash"] != prior_draft_hash
        assert read_composition_for_generated_page(
            session,
            restored.generated_page_id,
        ).status == "current"


def test_backup_057_partial_composition_set_is_completed_authoritatively(
    tmp_path: Path,
):
    payload = _export_ready_composition_backup(tmp_path, suffix="partial-set")
    payload["data"]["page_compositions"].pop()
    payload["metadata"]["table_counts"]["page_compositions"] -= 1
    path = _write_backup_payload(tmp_path, "partial-composition-set.json", payload)
    with pytest.raises(
        BackupValidationError,
        match="unresolved reference in page_composition_revisions.page_composition_id",
    ):
        load_backup(path)


def test_backup_057_missing_connection_planning_record_is_restored_before_currentness(
    tmp_path: Path,
):
    payload = _export_ready_composition_backup(tmp_path, suffix="missing-planning")
    payload["data"]["site_connection_planning_records"] = []
    payload["metadata"]["table_counts"]["site_connection_planning_records"] = 0
    path = _write_backup_payload(tmp_path, "missing-planning-record.json", payload)
    load_backup(path)

    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        restored = restore_backup(session, path)
        assert restored["status"] == "restored"
        planning_records = session.exec(select(SiteConnectionPlanningRecord)).all()
        assert len(planning_records) == 1
        compositions = session.exec(select(PageComposition)).all()
        assert compositions
        assert all(composition.status == "current" for composition in compositions)
        for composition in compositions:
            current = read_composition_for_generated_page(
                session,
                composition.generated_page_id,
            )
            assert current.status == "current"
            assert current.validation_errors == []


def test_backup_057_invalid_operator_decision_cannot_preserve_current(
    tmp_path: Path,
):
    payload = _export_ready_composition_backup(tmp_path, suffix="invalid-decision")
    payload["data"]["page_compositions"][0]["operator_decisions"] = [
        {
            "instance_key": "hero",
            "action": "suppress",
            "provenance": "operator",
            "decided_by": "Tampered backup",
            "decided_at": "2026-08-01T00:00:00+00:00",
        }
    ]
    path = _write_backup_payload(tmp_path, "invalid-operator-decision.json", payload)
    with pytest.raises(
        BackupValidationError,
        match="current row does not exactly mirror its history tip",
    ):
        load_backup(path)


def test_real_050_backup_without_theme_groups_restores_with_neutral_fallback(tmp_path):
    source_engine = _engine(); SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_registry(session); _, plan, pages = _scope(session, suffix="legacy050")
        refresh_site_plan_compositions(session, plan.id)
        exported = export_backup(session, backup_dir=tmp_path)

    backup_path = tmp_path / "legacy-050.json"
    payload = json.loads((tmp_path / exported["file_name"]).read_text(encoding="utf-8"))
    payload["metadata"]["version"] = "0.50"
    for group in ("themes", "website_theme_selections"):
        payload["data"].pop(group, None)
        payload["metadata"]["table_counts"].pop(group, None)
    payload["data"].pop("page_composition_revisions", None)
    payload["metadata"]["table_counts"].pop(
        "page_composition_revisions",
        None,
    )
    for composition in payload["data"]["page_compositions"]:
        source_snapshot = dict(composition["source_snapshot"])
        source_snapshot.pop("theme", None)
        composition["source_snapshot"] = source_snapshot
        composition["source_hash"] = hashlib.sha256(
            json.dumps(
                source_snapshot,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
    backup_path.write_text(json.dumps(payload), encoding="utf-8")

    restored_engine = _engine(); SQLModel.metadata.create_all(restored_engine)
    with Session(restored_engine) as session:
        restored = restore_backup(session, backup_path)
        assert restored["status"] == "restored"
        assert session.exec(select(Theme)).all() == []
        assert session.exec(select(WebsiteThemeSelection)).all() == []
        restored_plan = session.exec(select(SitePlan)).one()
        generated_id = session.exec(
            select(GeneratedPage).order_by(GeneratedPage.id)
        ).first().id
        try:
            current = read_composition_for_generated_page(session, generated_id)
        except PageCompositionError as exc:
            assert "stale" in str(exc)
            result = refresh_site_plan_compositions(session, restored_plan.id)
            assert result.refreshed == 2 and result.blocked == []
            current = read_composition_for_generated_page(session, generated_id)
        assert current.resolved_theme["fallback_used"] is True


def test_governed_media_placements_bind_to_exact_semantic_regions_and_versions():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        website, plan, pages = _scope(session)
        service_draft = dict(pages[0][1].draft_content)
        service_draft["sections"] = [
            *service_draft["sections"],
            {
                "key": "preparation",
                "heading": "Preparation",
                "body": "Approved preparation information.",
            },
            {
                "key": "guidance",
                "heading": "Guidance",
                "body": "Approved customer guidance.",
            },
        ]
        pages[0][1].draft_content = service_draft
        session.add(pages[0][1])
        session.commit()
        baseline = refresh_site_plan_compositions(session, plan.id)
        assert baseline.blocked == []
        initial_composition = session.exec(
            select(PageComposition).where(
                PageComposition.planned_page_id == pages[0][0].id
            )
        ).one()
        content_instances = [
            item["instance_key"]
            for item in initial_composition.generated_components
            if item["component_key"] == "content_section"
        ]
        assert len(content_instances) >= 2
        preexisting_suppression = content_instances[-1]
        update_operator_composition_decisions(
            session,
            initial_composition.id,
            PageCompositionDecisionUpdate(
                decisions=[
                    {
                        "instance_key": preexisting_suppression,
                        "action": "suppress",
                        "rationale": "Suppress one optional repeated section.",
                    }
                ],
                decided_by="Composition Media Operator",
            ),
        )
        workspace = refresh_site_plan_media_suggestions(session, plan.id)
        assert workspace.planning_record is not None
        for placement in workspace.placements:
            suggestion = placement.suggestion
            assert suggestion is not None
            decide_media_placement(
                session,
                plan.id,
                PageMediaPlacementDecisionRequest(
                    website_id=website.id,
                    site_plan_id=plan.id,
                    planned_page_id=placement.planned_page.id,
                    placement_key=suggestion["placement_key"],
                    requirement_state="advisory",
                    decided_by="Composition Media Operator",
                    rationale="Approve the exact governed semantic media placement.",
                    expected_planning_version=workspace.planning_record.version,
                    source_suggestion_key=suggestion["suggestion_key"],
                ),
            )

        initial_refresh = refresh_site_plan_compositions(session, plan.id)
        assert initial_refresh.blocked == []
        service_page = pages[0][0]
        composition = session.exec(
            select(PageComposition).where(
                PageComposition.planned_page_id == service_page.id
            )
        ).one()
        components = composition.generated_components
        media_components = [
            item for item in components if item["component_key"] == "media_placement"
        ]
        assert media_components
        for media in media_components:
            bindings = media["input_bindings"]
            target_index = next(
                index
                for index, item in enumerate(components)
                if item["instance_key"]
                == bindings["target_component_instance_key"]
            )
            media_index = components.index(media)
            assert media_index > target_index
            assert all(
                item["component_key"] == "media_placement"
                and item["input_bindings"]["target_component_instance_key"]
                == bindings["target_component_instance_key"]
                for item in components[target_index + 1 : media_index + 1]
            )
            assert media["region"] == bindings["target_region"]
            requirement = session.get(
                PlannedPageMediaRequirement,
                bindings["media_requirement_id"],
            )
            assert requirement is not None
            assert bindings["target_component_key"] == requirement.component_or_section

        requirements = composition.source_snapshot["page_media"]["requirements"]
        assert all(item["component_contract_version"] == 1 for item in requirements)
        guidance_requirement = next(
            item
            for item in session.exec(
                select(PlannedPageMediaRequirement).where(
                    PlannedPageMediaRequirement.planned_page_id == service_page.id
                )
            ).all()
            if item.placement_key == "service-guidance"
        )
        guidance_media = next(
            item
            for item in components
            if item["component_key"] == "media_placement"
            and item["input_bindings"].get("media_requirement_id")
            == guidance_requirement.id
        )
        suppressed_target = guidance_media["input_bindings"][
            "target_component_instance_key"
        ]
        assert suppressed_target != preexisting_suppression
        with pytest.raises(
            PageCompositionError,
            match="cannot be suppressed while an active Page Media placement targets it",
        ):
            update_operator_composition_decisions(
                session,
                composition.id,
                PageCompositionDecisionUpdate(
                    decisions=[
                        {
                            "instance_key": suppressed_target,
                            "action": "suppress",
                            "rationale": "Suppress the optional guidance section.",
                        }
                    ],
                    decided_by="Composition Media Operator",
                ),
            )
        session.refresh(composition)
        assert composition.operator_decisions[0]["instance_key"] == preexisting_suppression
        composition.operator_decisions = [
            {
                "instance_key": suppressed_target,
                "action": "suppress",
                "rationale": "Simulate direct suppression drift.",
                "provenance": "operator",
            }
        ]
        session.add(composition)
        session.flush()
        with pytest.raises(
            PageCompositionError,
            match="head diverges from revision field operator_decisions",
        ):
            read_site_plan_compositions(session, plan.id)
        session.rollback()
        composition = session.get(PageComposition, composition.id)
        assert composition is not None
        update_operator_composition_decisions(
            session,
            composition.id,
            PageCompositionDecisionUpdate(
                decisions=[],
                decided_by="Composition Media Operator",
            ),
        )
        session.add(
            SemanticComponentDefinition(
                component_key="hero",
                contract_version=2,
                purpose="Purpose for the updated governed hero contract.",
                required_inputs=CONTRACTS["hero"][0],
                customer_outcome="Customer outcome for the updated hero contract.",
                compatible_page_types=["all"],
                supported_variants=CONTRACTS["hero"][2],
                accessibility_requirements=["Provide an accessible responsive hero."],
                status="active",
            )
        )
        session.commit()

        stale_refresh = refresh_site_plan_compositions(session, plan.id)
        assert stale_refresh.compositions == []
        assert all(
            "Page Media planning suggestions are stale" in item["reason"]
            for item in stale_refresh.blocked
        )
        updated_workspace = refresh_site_plan_media_suggestions(session, plan.id)
        assert updated_workspace.planning_record is not None
        for placement in updated_workspace.placements:
            suggestion = placement.suggestion
            assert suggestion is not None
            decide_media_placement(
                session,
                plan.id,
                PageMediaPlacementDecisionRequest(
                    website_id=website.id,
                    site_plan_id=plan.id,
                    planned_page_id=placement.planned_page.id,
                    placement_key=suggestion["placement_key"],
                    requirement_state="advisory",
                    decided_by="Composition Media Operator",
                    rationale="Reapprove the exact placement after its component contract changed.",
                    expected_planning_version=updated_workspace.planning_record.version,
                    source_suggestion_key=suggestion["suggestion_key"],
                ),
            )
        refreshed = refresh_site_plan_compositions(session, plan.id)
        assert refreshed.blocked == []
        refreshed_service = next(
            item
            for item in refreshed.compositions
            if item.planned_page_id == service_page.id
        )
        refreshed_requirements = refreshed_service.source_snapshot["page_media"][
            "requirements"
        ]
        hero_requirement = next(
            item
            for item in refreshed_requirements
            if item["component_or_section"] == "hero"
        )
        assert hero_requirement["component_contract_version"] == 2


def test_required_media_without_assignment_refreshes_as_an_honest_placeholder():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        website, plan, pages = _scope(session, suffix="required-placeholder")
        service_draft = dict(pages[0][1].draft_content)
        service_draft["sections"] = [
            *service_draft["sections"],
            {
                "key": "guidance",
                "heading": "Guidance",
                "body": "Approved customer guidance.",
            },
        ]
        pages[0][1].draft_content = service_draft
        session.add(pages[0][1])
        session.commit()
        baseline = refresh_site_plan_compositions(session, plan.id)
        assert baseline.blocked == []
        workspace = refresh_site_plan_media_suggestions(session, plan.id)
        assert workspace.planning_record is not None
        for placement in workspace.placements:
            suggestion = placement.suggestion
            assert suggestion is not None
            decide_media_placement(
                session,
                plan.id,
                PageMediaPlacementDecisionRequest(
                    website_id=website.id,
                    site_plan_id=plan.id,
                    planned_page_id=placement.planned_page.id,
                    placement_key=suggestion["placement_key"],
                    requirement_state=suggestion["requirement_state"],
                    decided_by="Composition Media Operator",
                    rationale="Approve the validated placement without implying media exists.",
                    expected_planning_version=workspace.planning_record.version,
                    source_suggestion_key=suggestion["suggestion_key"],
                ),
            )

        refreshed = refresh_site_plan_compositions(session, plan.id)

        assert refreshed.blocked == []
        assert refreshed.refreshed == len(pages)
        assert all(item.status == "current" for item in refreshed.compositions)
        placeholders = [
            item
            for composition in refreshed.compositions
            for item in composition.effective_components
            if item.component_key == "media_placement"
        ]
        assert placeholders
        assert all(item.variant == "placeholder" for item in placeholders)
        assert all(not item.resolved_data.get("asset_url") for item in placeholders)
        service_page = pages[0][0]
        strict_errors = validate_required_media_for_page(
            session,
            service_page,
        )
        assert "Required media placement service-hero has no approved assignment." in strict_errors


@pytest.mark.parametrize("binding_version", (None, 1))
def test_v2_composition_rejects_missing_or_mismatched_binding_contract_version(
    binding_version,
    monkeypatch,
):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        website, plan, pages = _scope(session, suffix=f"binding-version-{binding_version}")
        baseline = refresh_site_plan_compositions(session, plan.id)
        assert baseline.blocked == []
        planned, generated = pages[0]
        composition = session.exec(
            select(PageComposition).where(
                PageComposition.generated_page_id == generated.id
            )
        ).one()
        planning = WebsiteMediaPlanningRecord(
            website_id=website.id,
            business_id=website.business_id,
            site_plan_id=plan.id,
            version=1,
            algorithm_version="page-media-planning-v2",
            generated_media_suggestions=[],
            source_snapshot={},
            source_hash="a" * 64,
        )
        session.add(planning)
        session.flush()
        requirement = PlannedPageMediaRequirement(
            website_id=website.id,
            business_id=website.business_id,
            site_plan_id=plan.id,
            planned_page_id=planned.id,
            planning_record_id=planning.id,
            component_or_section="hero",
            target_component_instance_key="hero",
            placement_key="service-hero-contract-test",
            contract_version=2,
            version=1,
            requirement_state="advisory",
            purpose="Validate the exact hero media contract.",
            customer_outcome="Understand the approved service.",
            intended_subject="Approved service evidence.",
            orientation="landscape",
            aspect_ratio="16:9",
            minimum_width=1200,
            minimum_height=675,
            crop_intent="Preserve the meaningful subject.",
            focal_point_intent="Use the approved focal point.",
            responsive_behavior="Use approved responsive derivatives.",
            accessibility_intent="informative",
            approved_source_constraints=["approved_company_media"],
            permitted_reuse_policy="Reuse only for this approved purpose.",
            replacement_policy="Replacement requires operator approval.",
            compatible_page_types=[planned.page_type],
            decided_by="Composition Contract Operator",
            rationale="Exercise fail-closed persisted binding validation.",
            lifecycle_status="active",
        )
        session.add(requirement)
        session.flush()
        components = list(composition.generated_components)
        bindings = {
            "media_requirement_id": requirement.id,
            "target_component_key": "hero",
            "target_component_instance_key": "hero",
        }
        if binding_version is not None:
            bindings["placement_contract_version"] = binding_version
        components.append(
            {
                "instance_key": f"media_placement:requirement-{requirement.id}",
                "component_key": "media_placement",
                "contract_version": 1,
                "region": "main",
                "position": max(item["position"] for item in components) + 1,
                "variant": "placeholder",
                "input_bindings": bindings,
                "provenance": "atlas_generated",
            }
        )
        composition.generated_components = components
        session.add(composition)
        session.commit()
        monkeypatch.setattr(
            "app.services.page_media_planning.validate_required_media_for_page",
            lambda *_args, **_kwargs: [],
        )

        with pytest.raises(
            PageCompositionError,
            match="placement contract version does not match",
        ):
            composition_service._validate(
                session,
                composition,
                plan,
                planned,
                generated,
            )
