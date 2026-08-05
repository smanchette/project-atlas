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
        assert "website_identity_assets" not in session.exec(
            select(PageComposition).where(PageComposition.generated_page_id == pages[0][1].id)
        ).one().source_snapshot
        assert service.source_snapshot["theme"]["mode"] == "neutral_fallback"
        assert service.resolved_theme["fallback_used"] is True


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
