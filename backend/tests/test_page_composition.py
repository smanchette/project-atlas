from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.backup import export_backup, restore_backup
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
    SemanticComponentDefinition,
    Service,
    SitePlan,
    Theme,
    Website,
    WebsiteIdentity,
    WebsiteIdentityAssetAssignment,
    WebsiteThemeSelection,
)
from app.schemas.page_composition import PageCompositionDecisionUpdate
from app.services.page_composition import (
    PageCompositionError,
    list_component_registry,
    read_composition_for_generated_page,
    refresh_site_plan_compositions,
    update_operator_composition_decisions,
)
from app.services.site_connections import ensure_site_connection_foundation
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
                "sections": [{"key": "overview", "heading": "Overview", "body": "Approved facts only."}],
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
            "target",
            "Active Navigation Items cannot share the same target Planned Page.",
        ),
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
        refresh_site_plan_compositions(session, plan.id)
        website_id = website.id
        exported = export_backup(session, backup_dir=tmp_path)
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
