from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.backup import export_backup, restore_backup
from app.models import (
    Brand,
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
    Website,
    WebsiteIdentity,
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
    for index, (planned, _) in enumerate(pages):
        session.add(NavigationItem(website_id=website.id, site_plan_id=plan.id, navigation_set_id=sets["primary"].id, target_planned_page_id=planned.id, label=planned.working_name, position=index, status="active"))
    session.add(NavigationItem(website_id=website.id, site_plan_id=plan.id, navigation_set_id=sets["utility"].id, target_planned_page_id=pages[1][0].id, label="Contact", position=0, status="active"))
    session.add(NavigationItem(website_id=website.id, site_plan_id=plan.id, navigation_set_id=sets["footer"].id, target_planned_page_id=pages[1][0].id, label="Contact", position=0, status="active"))
    session.add(InternalLinkIntent(website_id=website.id, site_plan_id=plan.id, source_planned_page_id=pages[0][0].id, target_planned_page_id=pages[1][0].id, purpose="Continue to approved contact options.", relationship_type="conversion", approval_state="approved"))
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
        assert any(item.component_key == "destination_cards" for item in service.effective_components)
        assert any(item.component_key == "media_placement" for item in service.effective_components)
        assert all("company_name" not in item for item in service.generated_components)
        assert any(item.resolved_data.get("company_name") == f"Composition {website.domain.split('.')[0]}" for item in service.effective_components)
        assert session.get(GeneratedPage, pages[0][1].id).draft_content == original_draft


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


def test_backup_049_round_trip_preserves_registry_and_scoped_compositions(tmp_path):
    source_engine = _engine(); SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_registry(session); website, plan, _ = _scope(session, suffix="backup")
        refresh_site_plan_compositions(session, plan.id)
        website_id = website.id
        exported = export_backup(session, backup_dir=tmp_path)
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
