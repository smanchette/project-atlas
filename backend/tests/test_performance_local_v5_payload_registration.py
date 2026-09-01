from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import or_
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Brand,
    BrandAsset,
    Business,
    GeneratedPage,
    GeneratedPageRevision,
    ImageMetadata,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    PlannedPageMediaRequirement,
    SitePlan,
    Theme,
    ThemeConfigurationAudit,
    ThemeFamilyVersion,
    Website,
    WebsiteIdentity,
    WebsiteIdentityAssetAssignment,
    WebsiteMediaPlanningRecord,
    WebsiteThemeComponentConfiguration,
    WebsiteThemeConfiguration,
    WebsiteThemeSelection,
)
from app.schemas.theme_families import (
    PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS,
    PERFORMANCE_LOCAL_V2_SOURCE_COMMIT,
    PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS,
    ThemeFamilyCreate,
    ThemeFamilyVersionCreate,
    WebsiteThemeComponentConfigurationCreate,
    WebsiteThemeConfigurationCreate,
)
from app.schemas.performance_local_v5 import (
    PerformanceLocalV5PayloadBuild,
    PerformanceLocalV5PreparedPayload,
    PerformanceLocalV5SourceBindings,
    PerformanceLocalV5VerifiedMediaMap,
)
from app.services import theme_configurations as theme_service
from app.services import performance_local_v5_payload as payload_service
from app.services.performance_local_v5_payload import (
    PerformanceLocalV5PayloadError,
    _upload_path,
    _verified_wordpress_media_path,
    build_performance_local_v5_staging_payload,
    canonical_performance_local_v5_json,
    finalize_performance_local_v5_staging_payload,
    performance_local_v5_payload_sha256,
    prepare_performance_local_v5_staging_payload,
)
from app.services.performance_local_v5_registration import (
    PERFORMANCE_LOCAL_V5_CONFIGURATION_KEY,
    PERFORMANCE_LOCAL_V5_FAMILY_VERSION,
    PERFORMANCE_LOCAL_V5_THEME_KEY,
    PerformanceLocalV5RegistrationError,
    apply_performance_local_v5_registration,
    plan_performance_local_v5_registration,
)
from app.services.themes import DEFAULT_THEME_TOKENS, canonical_token_hash


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as value:
        yield value


def _form_fields() -> list[dict]:
    definitions = (
        ("name", "Name", True, "input", "text", 1, "nonempty_text", 1, 100, "half", "name"),
        ("phone", "Phone", True, "input", "tel", 2, "phone", 7, 40, "half", "phone"),
        ("postal-code", "ZIP code", True, "input", "text", 3, "postal_code", 5, 12, "half", "postal_code"),
        ("requested-service", "Requested service", True, "input", "text", 4, "nonempty_text", 1, 160, "half", "requested_service"),
        ("message", "Optional message", False, "textarea", "text", 5, "free_text", 0, 2000, "full", "message"),
    )
    return [
        {
            "field_key": key,
            "label": label,
            "required": required,
            "control": control,
            "input_type": input_type,
            "order": order,
            "accessibility_label": label,
            "autocomplete_policy": "off",
            "maximum_length": maximum,
            "validation_contract": {
                "rule": rule,
                "minimum_length": minimum,
                "maximum_length": maximum,
            },
            "responsive_layout": layout,
            "provider_mapping": mapping,
        }
        for (
            key,
            label,
            required,
            control,
            input_type,
            order,
            rule,
            minimum,
            maximum,
            layout,
            mapping,
        ) in definitions
    ]


def _contract(key: str) -> dict:
    return next(
        deepcopy(item)
        for item in PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS
        if item["component_key"] == key
    )


def _seed_v3_graph(session: Session) -> tuple[int, int, int]:
    business = Business(
        company_name="Disposable V5 Registration",
        business_type="synthetic test",
        phone="(407) 555-0100",
        state="FL",
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id,
        brand_name="Disposable Brand",
        tagline="Synthetic fixture",
        status="active",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name="Disposable Website",
        domain="v5-registration.example.test",
        public_url="https://v5-registration.example.test",
        status="active",
    )
    session.add(website)
    session.flush()
    now = datetime.now(UTC)
    source_theme = Theme(
        website_id=website.id,
        business_id=business.id,
        brand_id=brand.id,
        theme_key="flo-zone-default",
        theme_name="Flo-Zone Default",
        version=1,
        token_contract_version=1,
        design_tokens=DEFAULT_THEME_TOKENS.model_dump(mode="json"),
        token_hash_sha256=canonical_token_hash(DEFAULT_THEME_TOKENS),
        lifecycle_status="available",
        approval_status="approved",
        created_by="fixture",
        provenance_type="operator_configured",
        provenance_notes="Disposable exact predecessor Theme.",
        approved_by="fixture",
        approved_at=now,
    )
    session.add(source_theme)
    session.flush()
    source_selection = WebsiteThemeSelection(
        website_id=website.id,
        theme_id=source_theme.id,
        version=1,
        status="active",
        selected_by="fixture",
        rationale="Disposable exact predecessor selection.",
        selected_at=now,
    )
    session.add(source_selection)
    session.commit()

    family = theme_service.register_theme_family(
        session,
        ThemeFamilyCreate(
            family_key="performance-local",
            display_name="Performance Local",
            description="Disposable Performance Local family.",
            provider_source_identity="atlas-source:performance-local",
            created_by="fixture",
        ),
    )
    v2 = theme_service.register_theme_family_version(
        session,
        family.id,
        ThemeFamilyVersionCreate(
            version=2,
            source_commit=PERFORMANCE_LOCAL_V2_SOURCE_COMMIT,
            supported_component_contracts=list(PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS),
            created_by="fixture",
        ),
    )
    v3 = theme_service.register_theme_family_version(
        session,
        family.id,
        ThemeFamilyVersionCreate(
            version=3,
            source_commit="3" * 40,
            supported_component_contracts=list(PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS),
            created_by="fixture",
            supersedes_theme_family_version_id=v2.id,
        ),
    )
    configuration = theme_service.create_website_theme_configuration(
        session,
        website.id,
        WebsiteThemeConfigurationCreate(
            theme_family_version_id=v3.id,
            configuration_key="performance-local-v3",
            created_by="fixture",
            creation_rationale="Disposable exact V3 governed source graph.",
        ),
    )
    form = theme_service.create_component_configuration(
        session,
        website.id,
        configuration.id,
        WebsiteThemeComponentConfigurationCreate(
            component_instance_key="estimate-form-default",
            component_key="compact_estimate_form",
            component_contract_version=3,
            scope_type="website_default",
            enabled=True,
            variant=_contract("compact_estimate_form")["variant"],
            placement=_contract("compact_estimate_form")["placement"],
            responsive_visibility=_contract("compact_estimate_form")["responsive_visibility"],
            configuration_payload={
                "submission_state": "disabled_pending_provider_configuration",
                "fields": _form_fields(),
                "submit_label": "Request an Estimate",
                "preview_notice": "Provider configuration is pending.",
                "provider": {
                    "provider_key": None,
                    "destination": None,
                    "provider_secret_reference": None,
                    "test_only": False,
                },
                "privacy": {
                    "policy_destination": None,
                    "consent_mode": None,
                    "consent_text": None,
                    "consent_text_version": None,
                },
                "retention": {
                    "duration": None,
                    "deletion_expiration_behavior": None,
                },
                "spam": {"strategy": None, "configuration_reference": None},
                "success_behavior": None,
                "failure_behavior": None,
                "security": {
                    "same_origin_policy": None,
                    "csrf_policy": None,
                    "request_size_limit_bytes": None,
                    "idempotency_strategy": None,
                },
                "audit_identity": None,
            },
            approval_identity="fixture",
            created_by="fixture",
        ),
    )
    for key, instance_key, payload in (
        (
            "campaign_banner",
            "campaign-default",
            {
                "intent": "evergreen_conversion",
                "message": "Request an Estimate",
                "cta_label": "Request an Estimate",
                "approval_identity": "fixture",
            },
        ),
        (
            "sticky_mobile_action_bar",
            "conversion-actions-default",
            {
                "call_source": "governed_website_identity",
                "call_label": "Call",
                "estimate_label": "Request an Estimate",
                "desktop_sticky_header": True,
                "mobile_sticky_bottom": True,
                "hide_while_hero_actions_visible": True,
                "hide_while_navigation_open": True,
                "protect_form_focus": True,
                "safe_area_support": True,
                "prevent_content_obstruction": True,
            },
        ),
    ):
        contract = _contract(key)
        theme_service.create_component_configuration(
            session,
            website.id,
            configuration.id,
            WebsiteThemeComponentConfigurationCreate(
                component_instance_key=instance_key,
                component_key=key,
                component_contract_version=3,
                scope_type="website_default",
                enabled=True,
                variant=contract["variant"],
                placement=contract["placement"],
                responsive_visibility=contract["responsive_visibility"],
                configuration_payload=payload,
                approval_identity="fixture",
                created_by="fixture",
                destination_component_configuration_id=form.id,
            ),
        )
    return website.id, v2.id, v3.id


def _v5_audits(
    session: Session,
    *,
    version_id: int,
    configuration_id: int,
    component_ids: list[int],
) -> list[ThemeConfigurationAudit]:
    return list(
        session.exec(
            select(ThemeConfigurationAudit)
            .where(
                or_(
                    ThemeConfigurationAudit.theme_family_version_id == version_id,
                    ThemeConfigurationAudit.website_theme_configuration_id
                    == configuration_id,
                    ThemeConfigurationAudit.component_configuration_id.in_(
                        component_ids
                    ),
                )
            )
            .order_by(
                ThemeConfigurationAudit.created_at,
                ThemeConfigurationAudit.id,
            )
        ).all()
    )


def _v5_audit_natural_identities(
    session: Session,
    *,
    version_id: int,
    configuration_id: int,
    component_ids: list[int],
) -> list[tuple[str, str]]:
    components = {
        item.id: item.component_key
        for item in session.exec(
            select(WebsiteThemeComponentConfiguration).where(
                WebsiteThemeComponentConfiguration.id.in_(component_ids)
            )
        ).all()
    }
    identities: list[tuple[str, str]] = []
    for audit in _v5_audits(
        session,
        version_id=version_id,
        configuration_id=configuration_id,
        component_ids=component_ids,
    ):
        theme_service._validate_audit(audit)
        assert audit.snapshot_hash != theme_service.canonical_json_hash(audit.snapshot)
        if audit.theme_family_version_id == version_id:
            target = "family_version"
        elif audit.website_theme_configuration_id == configuration_id:
            target = "configuration"
        else:
            target = components[audit.component_configuration_id]
        identities.append((target, audit.action_type))
    return identities


def write_built_payload_json(
    build: PerformanceLocalV5PayloadBuild,
    destination: Path,
) -> Path:
    """Emit the actual builder value in the PHP harness's fixture-array shape."""

    destination.write_text(
        json.dumps(
            [build.payload],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination.resolve()


def _resolved_component(
    instance_key: str,
    resolved_data: dict,
    *,
    component_key: str | None = None,
    variant: str = "default",
    input_bindings: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        instance_key=instance_key,
        component_key=component_key or instance_key.split(":", 1)[0],
        variant=variant,
        input_bindings=input_bindings or {},
        resolved_data=resolved_data,
    )


def _seed_builder_scope(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> SimpleNamespace:
    website_id, _v2_id, _v3_id = _seed_v3_graph(session)
    website = session.get(Website, website_id)
    assert website is not None
    business = session.get(Business, website.business_id)
    brand = session.get(Brand, website.brand_id)
    assert business is not None and brand is not None
    business.email = "hello@flo-zone.example.test"
    business.brand_name = "Flo-Zone"
    business.main_city = "Orlando"
    brand.tagline = "Tenting done with care"
    session.add(business)
    session.add(brand)

    now = datetime.now(UTC)
    site_plan = SitePlan(
        website_id=website.id,
        plan_key="builder-fixture",
        plan_name="Disposable builder fixture",
        status="approved",
        version=1,
    )
    session.add(site_plan)
    session.flush()
    page = GeneratedPage(
        id=41,
        business_id=business.id,
        website_id=website.id,
        page_type="city_service",
        page_title="Drywood Termite Tenting in Orlando, Florida",
        page_slug="drywood-termite-tenting-orlando-fl",
        meta_title="Drywood Termite Tenting in Orlando, Florida",
        meta_description="Governed disposable description for Orlando.",
        h1="Drywood Termite Tenting in Orlando, Florida",
        draft_content={
            "h1": "Drywood Termite Tenting in Orlando, Florida",
            "intro": "Governed introduction for the current Orlando City-Service page.",
            "call_to_action": "Request a governed estimate for service in Orlando.",
        },
        generation_status="generated",
        qa_status="passed",
        status="approved",
        wordpress_post_id=8,
    )
    session.add(page)
    session.flush()
    planned = PlannedPage(
        id=41,
        website_id=website.id,
        site_plan_id=site_plan.id,
        page_type="city_service",
        working_name="Orlando City Service",
        intended_slug=page.page_slug,
        planning_status="approved",
        generated_page_id=page.id,
    )
    session.add(planned)
    session.flush()
    page_revision = GeneratedPageRevision(
        id=64,
        generated_page_id=page.id,
        created_at=now,
        created_by="Disposable Builder",
        reason="Exact v9/current builder fixture.",
        draft_hash_before="0" * 64,
        draft_hash_after="a" * 64,
        draft_content_before={},
        draft_content_after=deepcopy(page.draft_content),
        changed_fields=["draft_content"],
    )
    session.add(page_revision)
    session.flush()
    composition = PageComposition(
        id=41,
        website_id=website.id,
        site_plan_id=site_plan.id,
        planned_page_id=planned.id,
        generated_page_id=page.id,
        composition_version=9,
        generated_components=[],
        operator_decisions=[],
        source_snapshot={},
        source_hash="c" * 64,
        status="current",
        generated_at=now,
        decided_by="Disposable Builder",
        decided_at=now,
    )
    session.add(composition)
    planning = WebsiteMediaPlanningRecord(
        website_id=website.id,
        business_id=business.id,
        site_plan_id=site_plan.id,
        version=1,
        algorithm_version="disposable-builder-v1",
        generated_media_suggestions=[],
        source_snapshot={},
        source_hash="9" * 64,
        generated_at=now,
    )
    session.add(planning)
    session.flush()

    media_rows: list[tuple] = []
    media_specs = (
        ("hero", "hero", "hero", "hero-desktop.webp", "1" * 64),
        (
            "why-it-matters",
            "service_summary:why_it_matters",
            "service_summary",
            "why-it-matters.webp",
            "2" * 64,
        ),
        (
            "what-to-look-for",
            "content_section:signs_section",
            "content_section",
            "what-to-look-for.webp",
            "3" * 64,
        ),
    )
    for index, (placement, target, component_key, filename, checksum) in enumerate(
        media_specs, start=1
    ):
        requirement = PlannedPageMediaRequirement(
            website_id=website.id,
            business_id=business.id,
            site_plan_id=site_plan.id,
            planned_page_id=planned.id,
            planning_record_id=planning.id,
            component_or_section=component_key,
            target_component_instance_key=target,
            placement_key=placement,
            contract_version=2,
            version=1,
            requirement_state="required",
            purpose=f"Governed {placement} presentation.",
            customer_outcome="Understand the service.",
            intended_subject="Flo-Zone service work",
            orientation="landscape",
            aspect_ratio="16:9",
            minimum_width=1200,
            minimum_height=675,
            crop_intent="responsive focal crop",
            focal_point_intent="preserve governed subject",
            responsive_behavior="responsive picture",
            accessibility_intent="descriptive alternative text",
            approved_source_constraints=["governed-only"],
            permitted_reuse_policy="requirement_only",
            replacement_policy="append_only",
            compatible_page_types=["city_service"],
            decided_by="Disposable Builder",
            rationale="Exact disposable governed media requirement.",
            decided_at=now,
            lifecycle_status="active",
        )
        session.add(requirement)
        session.flush()
        image = ImageMetadata(
            business_id=business.id,
            website_id=website.id,
            media_key=f"builder-{placement}",
            media_version=1,
            file_name=filename,
            image_title=f"Governed {placement} image",
            alt_text=f"Governed {placement} scene",
            asset_url=f"/media/{filename}",
            original_filename=filename,
            stored_filename=filename,
            mime_type="image/webp",
            file_size=1000 + index,
            width=1600,
            height=900,
            checksum_sha256=checksum,
            managed_storage_path=f"media/originals/{filename}",
            acquisition_source="company_archive",
            creator_source_identity="Flo-Zone",
            created_by="Disposable Builder",
            provenance_type="company_original",
            provenance_notes="Disposable governed builder fixture.",
            rights_status="owned",
            rights_holder="Flo-Zone",
            rights_notes="Owned disposable fixture identity.",
            approved_usage=[placement],
            prohibited_usage=["unapproved_reuse"],
            permitted_placement_keys=[placement],
            accessibility_intent="Use the exact governed alt text.",
            governance_status="approved",
            required_authorization_terms=["requirement_only_usage"],
            usage_authorization_mode="scoped_required",
            approval_version=1,
            approved_by="Disposable Builder",
            approved_at=now,
            focal_x=0.5,
            focal_y=0.5,
            image_role="hero" if placement == "hero" else "support",
            review_status="reviewed",
            exif_status="stripped",
            wordpress_media_id=100 + index,
            wordpress_media_url=(
                f"https://staging.example.test/wp-content/uploads/atlas-v5/{filename}"
            ),
            wordpress_media_status="reconciled",
            wordpress_media_checksum=checksum,
        )
        session.add(image)
        session.flush()
        assignment = PageImageAssignment(
            generated_page_id=page.id,
            image_metadata_id=image.id,
            website_id=website.id,
            site_plan_id=site_plan.id,
            planned_page_id=planned.id,
            media_requirement_id=requirement.id,
            assignment_version=1,
            media_version=1,
            placement_contract_version=2,
            assigned_by="Disposable Builder",
            assignment_rationale="Exact disposable governed assignment.",
            assigned_at=now,
            image_role="hero" if placement == "hero" else f"support-{index}",
            display_preset="hero_desktop" if placement == "hero" else "content_landscape",
            status="active",
        )
        session.add(assignment)
        session.flush()
        authorization = SimpleNamespace(
            id=200 + index,
            authorization_version=2,
            authorization_fingerprint=str(index + 3) * 64,
        )
        media_rows.append((requirement, image, assignment, authorization, target))

    identity = WebsiteIdentity(
        website_id=website.id,
        display_name=brand.brand_name,
        status="active",
        approved_at=now,
    )
    session.add(identity)
    session.flush()
    logo_rows = {}
    logo_assignments = {}
    for role, checksum in (("header_logo", "7" * 64), ("footer_logo", "8" * 64)):
        asset = BrandAsset(
            business_id=business.id,
            brand_id=brand.id,
            asset_key=f"builder-{role}",
            version=1,
            asset_type="primary_logo",
            variant_key="default",
            purpose=f"Governed {role} identity.",
            approved_usage=[role],
            restrictions=["no-unapproved-use"],
            accessibility_description="Flo-Zone Pest and Termite Solutions",
            original_filename=f"{role}.webp",
            stored_filename=f"{role}.webp",
            asset_url=f"/wp-content/uploads/atlas-v5/{role}.webp",
            mime_type="image/webp",
            file_size=800,
            width=480,
            height=160,
            checksum_sha256=checksum,
            provenance_type="company_original",
            provenance_notes="Disposable governed logo fixture.",
            rights_status="owned",
            rights_holder="Flo-Zone",
            rights_notes="Owned identity asset.",
            status="approved",
            created_by="Disposable Builder",
            approved_by="Disposable Builder",
            approved_at=now,
        )
        session.add(asset)
        session.flush()
        logo_rows[role] = asset
        assignment = WebsiteIdentityAssetAssignment(
            website_identity_id=identity.id,
            website_id=website.id,
            brand_id=brand.id,
            brand_asset_id=asset.id,
            slot=role,
            version=1,
            status="active",
            assigned_by="Disposable Builder",
            rationale="Exact disposable governed logo assignment.",
            assigned_at=now,
        )
        session.add(assignment)
        session.flush()
        logo_assignments[role] = assignment

    header_assets = {
        "header_logo": {
            "asset_id": logo_rows["header_logo"].id,
            "asset_key": logo_rows["header_logo"].asset_key,
            "version": 1,
            "asset_type": "primary_logo",
            "asset_url": logo_rows["header_logo"].asset_url,
            "accessibility_description": logo_rows[
                "header_logo"
            ].accessibility_description,
        }
    }
    footer_assets = {
        "footer_logo": {
            "asset_id": logo_rows["footer_logo"].id,
            "asset_key": logo_rows["footer_logo"].asset_key,
            "version": 1,
            "asset_type": "primary_logo",
            "asset_url": logo_rows["footer_logo"].asset_url,
            "accessibility_description": logo_rows[
                "footer_logo"
            ].accessibility_description,
        }
    }
    public_identity = {
        "display_name": "Flo-Zone",
        "company_name": business.company_name,
        "business_type": business.business_type,
        "phone": business.phone,
        "email": business.email,
        "tagline": brand.tagline,
    }
    components = [
        _resolved_component(
            "website_header", {**public_identity, "identity_assets": header_assets}
        ),
        _resolved_component(
            "website_footer", {**public_identity, "identity_assets": footer_assets}
        ),
        _resolved_component(
            "utility_navigation",
            {
                "items": [
                    {
                        "navigation_item_id": 1,
                        "label": "Home",
                        "slug": "home",
                        "parent_navigation_item_id": None,
                        "status": "active",
                    }
                ]
            },
        ),
        _resolved_component(
            "primary_navigation",
            {
                "items": [
                    {
                        "navigation_item_id": 2,
                        "label": "Contact",
                        "slug": "contact",
                        "parent_navigation_item_id": None,
                        "status": "active",
                    }
                ]
            },
        ),
        _resolved_component(
            "footer_navigation",
            {
                "items": [
                    {
                        "navigation_item_id": 3,
                        "label": "Frequently Asked Questions",
                        "slug": "frequently-asked-questions",
                        "parent_navigation_item_id": None,
                        "status": "active",
                    }
                ]
            },
        ),
        _resolved_component(
            "hero",
            {
                "title": page.h1,
                "intro": page.draft_content["intro"],
                "phone": business.phone,
                "page_type": page.page_type,
            },
        ),
        _resolved_component(
            "service_summary:why_it_matters",
            {"key": "why_it_matters", "heading": "Why It Matters", "body": "Governed why-it-matters copy."},
            component_key="service_summary",
        ),
        _resolved_component(
            "content_section:signs_section",
            {"key": "signs_section", "heading": "What to Look For", "body": "Governed signs copy."},
            component_key="content_section",
        ),
        _resolved_component(
            "content_section:process_section",
            {"key": "process_section", "heading": "How Service Works", "body": "Governed process copy."},
            component_key="content_section",
        ),
        _resolved_component(
            "content_section:prep_section",
            {"key": "prep_section", "heading": "Preparing the Property", "body": "Governed preparation copy."},
            component_key="content_section",
        ),
        _resolved_component(
            "content_section:realtor_property_manager_section",
            {"key": "realtor_property_manager_section", "heading": "Coordinated Service", "body": "Governed coordination copy."},
            component_key="content_section",
        ),
        _resolved_component(
            "final_cta",
            {
                "heading": "Request an Estimate",
                "body": page.draft_content["call_to_action"],
            },
        ),
        _resolved_component(
            "destination_cards",
            {
                "links": [
                    {
                        "label": "Frequently Asked Questions",
                        "slug": "frequently-asked-questions",
                        "relationship_type": "related",
                    }
                ]
            },
        ),
        _resolved_component(
            "faq",
            {
                "items": [
                    {
                        "question": "How is service coordinated?",
                        "answer": "The governed process is reviewed before service.",
                    }
                ]
            },
        ),
    ]
    for requirement, image, assignment, _authorization, target in media_rows:
        components.append(
            _resolved_component(
                f"media_placement:requirement-{requirement.id}",
                {
                    "media_id": image.id,
                    "asset_url": image.asset_url,
                    "alt_text": image.alt_text,
                    "image_title": image.image_title,
                    "focal_x": image.focal_x,
                    "focal_y": image.focal_y,
                },
                component_key="media_placement",
                variant="approved_media",
                input_bindings={
                    "media_requirement_id": requirement.id,
                    "page_image_assignment_id": assignment.id,
                    "target_component_instance_key": target,
                },
            )
        )
    source_theme = session.exec(
        select(Theme).where(
            Theme.website_id == website.id,
            Theme.theme_key == "flo-zone-default",
        )
    ).one()
    resolved = SimpleNamespace(
        effective_components=components,
        resolved_theme={
            "fallback_used": False,
            "source_identity": {
                "theme_key": source_theme.theme_key,
                "theme_version": source_theme.version,
                "token_contract_version": source_theme.token_contract_version,
                "token_hash_sha256": source_theme.token_hash_sha256,
            },
            "effective_tokens": deepcopy(source_theme.design_tokens),
        },
    )
    qa_record = SimpleNamespace(
        id=121,
        latest_generated_page_revision_id=page_revision.id,
        page_composition_id=composition.id,
        composition_version=9,
        composition_source_hash=composition.source_hash,
        result_hash="d" * 64,
    )
    qa_state = SimpleNamespace(ready=True, record=qa_record)
    composition_revision = SimpleNamespace(
        id=107,
        generated_page_revision_id=page_revision.id,
        revision_hash="b" * 64,
    )
    authorizations = {
        requirement.id: authorization
        for requirement, _image, _assignment, authorization, _target in media_rows
    }
    session.commit()
    monkeypatch.setattr(
        payload_service,
        "read_composition_for_generated_page",
        lambda _session, _page_id: resolved,
    )
    monkeypatch.setattr(
        payload_service,
        "effective_page_qa_state",
        lambda _session, _page: qa_state,
    )
    monkeypatch.setattr(
        payload_service,
        "current_composition_revision",
        lambda _session, _composition: composition_revision,
    )
    monkeypatch.setattr(
        payload_service,
        "current_scoped_media_authorization",
        lambda _session, requirement_id: authorizations.get(requirement_id),
    )
    monkeypatch.setattr(
        payload_service,
        "scoped_media_authorization_errors",
        lambda *_args, **_kwargs: [],
    )
    return SimpleNamespace(
        website=website,
        business=business,
        brand=brand,
        page=page,
        planned=planned,
        page_revision=page_revision,
        composition=composition,
        qa_state=qa_state,
        qa_record=qa_record,
        composition_revision=composition_revision,
        resolved=resolved,
        media_rows=media_rows,
        authorizations=authorizations,
        logo_rows=logo_rows,
        logo_assignments=logo_assignments,
        header_assets=header_assets,
        footer_assets=footer_assets,
    )


def _verified_media_mapping(
    prepared: PerformanceLocalV5PreparedPayload,
    *,
    staging_origin: str = "https://staging.example.test",
) -> dict:
    entries: list[dict] = []
    for index, item in enumerate(prepared.required_media, start=1):
        entries.append(
            {
                "governed_asset_class": "page_media",
                "requirement_id": item.requirement_id,
                "placement_key": item.placement_key,
                "target_component_instance_key": item.target_component_instance_key,
                "assignment_id": item.assignment_id,
                "assignment_version": item.assignment_version,
                "authorization_id": item.authorization_id,
                "authorization_version": item.authorization_version,
                "authorization_fingerprint": item.authorization_fingerprint,
                "governed_asset_id": item.image_metadata_id,
                "governed_asset_key": item.media_key,
                "governed_asset_version": item.media_version,
                "expected_sha256": item.checksum_sha256,
                "expected_mime_type": item.source_mime_type,
                "expected_width": item.source_width,
                "expected_height": item.source_height,
                "wordpress_attachment_id": 500 + index,
                "wordpress_original_url": (
                    f"{staging_origin}/wp-content/uploads/2026/08/"
                    f"{item.source_filename}"
                ),
                "observed_sha256": item.checksum_sha256,
                "observed_mime_type": item.source_mime_type,
                "observed_width": item.source_width,
                "observed_height": item.source_height,
            }
        )
    for index, item in enumerate(prepared.required_logo_media, start=4):
        assert item.assignment_id is not None
        assert item.assignment_version is not None
        entries.append(
            {
                "governed_asset_class": "brand_asset",
                "requirement_id": None,
                "placement_key": item.role,
                "target_component_instance_key": item.target_component_instance_key,
                "assignment_id": item.assignment_id,
                "assignment_version": item.assignment_version,
                "authorization_id": None,
                "authorization_version": None,
                "authorization_fingerprint": None,
                "governed_asset_id": item.brand_asset_id,
                "governed_asset_key": item.asset_key,
                "governed_asset_version": item.asset_version,
                "expected_sha256": item.checksum_sha256,
                "expected_mime_type": item.source_mime_type,
                "expected_width": item.source_width,
                "expected_height": item.source_height,
                "wordpress_attachment_id": 500 + index,
                "wordpress_original_url": (
                    f"{staging_origin}/wp-content/uploads/2026/08/"
                    f"{item.source_filename}"
                ),
                "observed_sha256": item.checksum_sha256,
                "observed_mime_type": item.source_mime_type,
                "observed_width": item.source_width,
                "observed_height": item.source_height,
            }
        )
    return {
        "mapping_schema": (
            "project-atlas-performance-local-v5-verified-media-map@1"
        ),
        "context": {
            "website_id": prepared.website_id,
            "planned_page_id": prepared.planned_page_id,
            "generated_page_id": prepared.generated_page_id,
            "wordpress_post_id": prepared.wordpress_post_id,
            "staging_origin": staging_origin,
            "source_bindings": prepared.source_bindings.model_dump(mode="json"),
        },
        "entries": entries,
    }


def _mapping_entry(mapping: dict, placement_key: str) -> dict:
    return next(
        item
        for item in mapping["entries"]
        if item["placement_key"] == placement_key
    )


def _reseal_prepared(
    prepared: PerformanceLocalV5PreparedPayload,
    **updates,
) -> PerformanceLocalV5PreparedPayload:
    candidate = prepared.model_copy(update=updates)
    preparation = {
        "website_id": candidate.website_id,
        "planned_page_id": candidate.planned_page_id,
        "generated_page_id": candidate.generated_page_id,
        "wordpress_post_id": candidate.wordpress_post_id,
        "metadata_key": candidate.metadata_key,
        "payload_schema": candidate.payload_schema,
        "payload_template": candidate.payload_template,
        "source_bindings": candidate.source_bindings.model_dump(mode="json"),
        "required_media": [
            item.model_dump(mode="json") for item in candidate.required_media
        ],
        "required_logo_media": [
            item.model_dump(mode="json") for item in candidate.required_logo_media
        ],
    }
    return candidate.model_copy(
        update={
            "preparation_sha256": performance_local_v5_payload_sha256(preparation)
        }
    )


def test_canonical_payload_hash_preserves_list_order_and_unicode() -> None:
    left = {"z": ["Flo-Zone", "Orlando"], "a": {"é": "✓", "b": 1}}
    right = {"a": {"b": 1, "é": "✓"}, "z": ["Flo-Zone", "Orlando"]}

    assert canonical_performance_local_v5_json(left) == canonical_performance_local_v5_json(right)
    assert b"\\u" not in canonical_performance_local_v5_json(left)
    assert performance_local_v5_payload_sha256(left) == performance_local_v5_payload_sha256(right)
    assert performance_local_v5_payload_sha256({"z": list(reversed(left["z"])), "a": left["a"]}) != performance_local_v5_payload_sha256(left)


def test_canonical_payload_hash_matches_php_line_separator_and_float_vector() -> None:
    vector = {
        "whole": 16.0,
        "zero": 0.0,
        "negative_zero": -0.0,
        "fraction": 0.5,
        "small_exponent": 1e-7,
        "large_exponent": 1e20,
        "line_separators": "before\u2028between\u2029after",
    }
    expected = (
        '{"fraction":0.5,"large_exponent":1.0e+20,'
        '"line_separators":"before\u2028between\u2029after",'
        '"negative_zero":-0.0,"small_exponent":1.0e-7,'
        '"whole":16.0,"zero":0.0}'
    ).encode("utf-8")

    assert canonical_performance_local_v5_json(vector) == expected
    assert performance_local_v5_payload_sha256(vector) == (
        "b0ef0698db793640caf91ed603fdee9ab7b288cd3e71e30acc65a0988d60f276"
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_payload_hash_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        canonical_performance_local_v5_json({"value": value})


def test_page_41_current_source_identity_fixture_is_exact() -> None:
    bindings = PerformanceLocalV5SourceBindings(
        generated_page_revision_id=64,
        generated_page_revision_hash="a" * 64,
        page_composition_id=41,
        composition_version=9,
        page_composition_revision_id=107,
        page_composition_revision_hash="b" * 64,
        composition_source_hash="c" * 64,
        qa_result_id=121,
        qa_result_hash="d" * 64,
    )

    assert (
        bindings.generated_page_revision_id,
        bindings.page_composition_id,
        bindings.composition_version,
        bindings.page_composition_revision_id,
        bindings.qa_result_id,
    ) == (64, 41, 9, 107, 121)


def test_prepare_finalize_accepts_date_paths_binds_map_hash_and_is_deterministic(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_builder_scope(session, monkeypatch)
    pending_before = (set(session.new), set(session.dirty), set(session.deleted))
    table_counts_before = {
        model: len(session.exec(select(model)).all())
        for model in (
            GeneratedPage,
            GeneratedPageRevision,
            PageComposition,
            PlannedPageMediaRequirement,
            ImageMetadata,
            PageImageAssignment,
            WebsiteIdentityAssetAssignment,
        )
    }

    prepared = prepare_performance_local_v5_staging_payload(session, 41)
    repeated_prepared = prepare_performance_local_v5_staging_payload(session, 41)
    mapping = _verified_media_mapping(prepared)
    finalized = finalize_performance_local_v5_staging_payload(
        prepared,
        mapping,
        expected_staging_origin="https://staging.example.test",
    )
    reordered_mapping = deepcopy(mapping)
    reordered_mapping["entries"].reverse()
    repeated_finalized = finalize_performance_local_v5_staging_payload(
        repeated_prepared,
        reordered_mapping,
        expected_staging_origin="https://staging.example.test",
    )

    assert prepared.model_dump(mode="json") == repeated_prepared.model_dump(mode="json")
    assert finalized.model_dump(mode="json") == repeated_finalized.model_dump(
        mode="json"
    )
    assert performance_local_v5_payload_sha256(mapping) != (
        performance_local_v5_payload_sha256(reordered_mapping)
    )
    assert prepared.template_sha256 == performance_local_v5_payload_sha256(
        prepared.payload_template
    )
    prepared_media = [*prepared.required_media, *prepared.required_logo_media]
    assert all(
        item.payload_src.startswith(payload_service._PREPARED_TOKEN_PREFIX)
        for item in prepared_media
    )
    for item in prepared_media:
        with pytest.raises(PerformanceLocalV5PayloadError):
            _upload_path(item.payload_src, "prepared media sentinel")
    mapping_hash = performance_local_v5_payload_sha256(mapping)
    mapping_inputs = [
        item
        for item in finalized.payload["payload_identity"]["frozen_inputs"]
        if item["path"] == payload_service._VERIFIED_MEDIA_FROZEN_INPUT
    ]
    assert mapping_inputs == [
        {
            "path": payload_service._VERIFIED_MEDIA_FROZEN_INPUT,
            "sha256": mapping_hash,
        }
    ]
    all_media = [*finalized.required_media, *finalized.required_logo_media]
    assert len(all_media) == 5
    assert all(item.ready for item in all_media)
    assert all(item.blocker is None for item in all_media)
    assert all(item.verification_source == "verified_media_mapping" for item in all_media)
    assert all(
        item.payload_src.startswith("/wp-content/uploads/2026/08/")
        for item in all_media
    )
    assert payload_service._PREPARED_TOKEN_PREFIX not in canonical_performance_local_v5_json(
        finalized.payload
    ).decode("utf-8")
    assert (set(session.new), set(session.dirty), set(session.deleted)) == pending_before
    assert {
        model: len(session.exec(select(model)).all()) for model in table_counts_before
    } == table_counts_before


@pytest.mark.parametrize("tamper", ["payload_template", "preparation_identity"])
def test_finalize_rejects_tampered_prepared_payload(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    _seed_builder_scope(session, monkeypatch)
    prepared = prepare_performance_local_v5_staging_payload(session, 41)
    mapping = _verified_media_mapping(prepared)
    if tamper == "payload_template":
        payload_template = deepcopy(prepared.payload_template)
        payload_template["page"]["h1"] += " tampered"
        prepared = prepared.model_copy(
            update={"payload_template": payload_template}
        )
    else:
        required_media = list(prepared.required_media)
        required_media[0] = required_media[0].model_copy(
            update={"media_key": required_media[0].media_key + "-tampered"}
        )
        prepared = prepared.model_copy(update={"required_media": required_media})

    with pytest.raises(PerformanceLocalV5PayloadError) as rejected:
        finalize_performance_local_v5_staging_payload(
            prepared,
            mapping,
            expected_staging_origin="https://staging.example.test",
        )

    assert rejected.value.code == "performance_local_v5_payload_template_invalid"


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("missing", "performance_local_v5_verified_media_mapping_invalid"),
        ("extra", "performance_local_v5_verified_media_mapping_invalid"),
        ("duplicate", "performance_local_v5_verified_media_mapping_invalid"),
        ("context_bool_id", "performance_local_v5_verified_media_mapping_invalid"),
        (
            "context_numeric_string",
            "performance_local_v5_verified_media_mapping_invalid",
        ),
        (
            "source_binding_bool_id",
            "performance_local_v5_verified_media_mapping_invalid",
        ),
        (
            "source_binding_numeric_string",
            "performance_local_v5_verified_media_mapping_invalid",
        ),
        (
            "entry_bool_attachment_id",
            "performance_local_v5_verified_media_mapping_invalid",
        ),
        (
            "entry_numeric_string",
            "performance_local_v5_verified_media_mapping_invalid",
        ),
        ("unknown_map_field", "performance_local_v5_verified_media_mapping_invalid"),
        (
            "unknown_context_field",
            "performance_local_v5_verified_media_mapping_invalid",
        ),
        (
            "unknown_source_binding_field",
            "performance_local_v5_verified_media_mapping_invalid",
        ),
        ("unknown_entry_field", "performance_local_v5_verified_media_mapping_invalid"),
        ("stale_context", "performance_local_v5_verified_media_mapping_stale"),
        ("stale_governed_field", "performance_local_v5_verified_media_mapping_stale"),
        ("hash_mismatch", "performance_local_v5_verified_media_mapping_mismatch"),
        ("mime_mismatch", "performance_local_v5_verified_media_mapping_mismatch"),
        ("dimension_mismatch", "performance_local_v5_verified_media_mapping_mismatch"),
        ("invalid_origin", "performance_local_v5_verified_media_mapping_invalid"),
        ("invalid_hostname", "performance_local_v5_verified_media_mapping_invalid"),
        ("stale_origin", "performance_local_v5_verified_media_mapping_stale"),
        ("cross_origin", "performance_local_v5_verified_media_mapping_invalid"),
        (
            "noncanonical_entry_origin",
            "performance_local_v5_verified_media_mapping_invalid",
        ),
        ("invalid_path", "performance_local_v5_verified_media_mapping_invalid"),
        ("double_slash", "performance_local_v5_verified_media_mapping_invalid"),
        ("query", "performance_local_v5_verified_media_mapping_invalid"),
        ("ambiguous_attachment", "performance_local_v5_verified_media_mapping_ambiguous"),
        ("ambiguous_url", "performance_local_v5_verified_media_mapping_ambiguous"),
    ],
)
def test_finalize_rejects_inexact_or_ambiguous_verified_media_maps_without_writes(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_code: str,
) -> None:
    _seed_builder_scope(session, monkeypatch)
    prepared = prepare_performance_local_v5_staging_payload(session, 41)
    mapping = _verified_media_mapping(prepared)
    pending_before = (set(session.new), set(session.dirty), set(session.deleted))

    if case == "missing":
        mapping["entries"].pop()
    elif case == "extra":
        extra = deepcopy(mapping["entries"][0])
        extra["governed_asset_id"] = 999_999
        extra["wordpress_attachment_id"] = 999_999
        extra["wordpress_original_url"] = (
            "https://staging.example.test/wp-content/uploads/2026/08/extra.webp"
        )
        mapping["entries"].append(extra)
    elif case == "duplicate":
        mapping["entries"][-1] = deepcopy(mapping["entries"][0])
    elif case == "context_bool_id":
        mapping["context"]["website_id"] = True
    elif case == "context_numeric_string":
        mapping["context"]["planned_page_id"] = str(
            mapping["context"]["planned_page_id"]
        )
    elif case == "source_binding_bool_id":
        mapping["context"]["source_bindings"]["qa_result_id"] = True
    elif case == "source_binding_numeric_string":
        mapping["context"]["source_bindings"]["composition_version"] = str(
            mapping["context"]["source_bindings"]["composition_version"]
        )
    elif case == "entry_bool_attachment_id":
        mapping["entries"][0]["wordpress_attachment_id"] = True
    elif case == "entry_numeric_string":
        mapping["entries"][0]["assignment_id"] = str(
            mapping["entries"][0]["assignment_id"]
        )
    elif case == "unknown_map_field":
        mapping["unexpected"] = "rejected"
    elif case == "unknown_context_field":
        mapping["context"]["unexpected"] = "rejected"
    elif case == "unknown_source_binding_field":
        mapping["context"]["source_bindings"]["unexpected"] = "rejected"
    elif case == "unknown_entry_field":
        mapping["entries"][0]["unexpected"] = "rejected"
    elif case == "stale_context":
        mapping["context"]["source_bindings"]["qa_result_id"] += 1
    elif case == "stale_governed_field":
        mapping["entries"][0]["governed_asset_key"] += "-stale"
    elif case == "hash_mismatch":
        mapping["entries"][0]["observed_sha256"] = "f" * 64
    elif case == "mime_mismatch":
        mapping["entries"][0]["observed_mime_type"] = "image/png"
    elif case == "dimension_mismatch":
        mapping["entries"][0]["observed_width"] += 1
    elif case == "invalid_origin":
        mapping["context"]["staging_origin"] = "http://staging.example.test"
    elif case == "invalid_hostname":
        mapping["context"]["staging_origin"] = "https://staging-.example.test"
    elif case == "stale_origin":
        mapping["context"]["staging_origin"] = "https://other.example.test"
    elif case == "cross_origin":
        mapping["entries"][0]["wordpress_original_url"] = (
            "https://other.example.test/wp-content/uploads/2026/08/hero-desktop.webp"
        )
    elif case == "noncanonical_entry_origin":
        mapping["entries"][0]["wordpress_original_url"] = (
            "https://STAGING.EXAMPLE.TEST/wp-content/uploads/2026/08/hero-desktop.webp"
        )
    elif case == "invalid_path":
        mapping["entries"][0]["wordpress_original_url"] = (
            "https://staging.example.test/wp-content/uploads/unmanaged/hero.webp"
        )
    elif case == "double_slash":
        mapping["entries"][0]["wordpress_original_url"] = (
            "https://staging.example.test/wp-content/uploads/2026//hero.webp"
        )
    elif case == "query":
        mapping["entries"][0]["wordpress_original_url"] += "?size=full"
    elif case == "ambiguous_attachment":
        header = _mapping_entry(mapping, "header_logo")
        footer = _mapping_entry(mapping, "footer_logo")
        footer["wordpress_attachment_id"] = header["wordpress_attachment_id"]
    elif case == "ambiguous_url":
        header = _mapping_entry(mapping, "header_logo")
        footer = _mapping_entry(mapping, "footer_logo")
        footer["wordpress_original_url"] = header["wordpress_original_url"]
    else:  # pragma: no cover - the parameter table is exhaustive
        raise AssertionError(case)

    with pytest.raises(PerformanceLocalV5PayloadError) as rejected:
        finalize_performance_local_v5_staging_payload(
            prepared,
            mapping,
            expected_staging_origin="https://staging.example.test",
        )

    assert rejected.value.code == expected_code
    assert (set(session.new), set(session.dirty), set(session.deleted)) == pending_before


def test_finalize_revalidates_preconstructed_mapping_instances_strictly(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_builder_scope(session, monkeypatch)
    prepared = prepare_performance_local_v5_staging_payload(session, 41)
    mapping = PerformanceLocalV5VerifiedMediaMap.model_validate(
        _verified_media_mapping(prepared)
    )
    invalid_entry = mapping.entries[0].model_copy(
        update={"wordpress_attachment_id": True}
    )
    invalid_mapping = mapping.model_copy(
        update={"entries": [invalid_entry, *mapping.entries[1:]]}
    )

    with pytest.raises(PerformanceLocalV5PayloadError) as rejected:
        finalize_performance_local_v5_staging_payload(
            prepared,
            invalid_mapping,
            expected_staging_origin="https://staging.example.test",
        )

    assert (
        rejected.value.code
        == "performance_local_v5_verified_media_mapping_invalid"
    )


@pytest.mark.parametrize(
    ("reuse_mode", "accepted"),
    [
        ("exact_attachment_and_url", True),
        ("same_url_different_attachment", False),
        ("same_attachment_different_url", False),
    ],
)
def test_finalize_allows_only_one_exact_attachment_url_pair_for_intentional_reuse(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    reuse_mode: str,
    accepted: bool,
) -> None:
    _seed_builder_scope(session, monkeypatch)
    prepared = prepare_performance_local_v5_staging_payload(session, 41)
    first, second, third = prepared.required_media
    reused_second = second.model_copy(
        update={
            "image_metadata_id": first.image_metadata_id,
            "media_key": first.media_key,
            "media_version": first.media_version,
            "source_filename": first.source_filename,
            "source_mime_type": first.source_mime_type,
            "source_width": first.source_width,
            "source_height": first.source_height,
            "checksum_sha256": first.checksum_sha256,
        }
    )
    prepared = _reseal_prepared(
        prepared,
        required_media=[first, reused_second, third],
    )
    mapping = _verified_media_mapping(prepared)
    first_entry = mapping["entries"][0]
    second_entry = mapping["entries"][1]
    if reuse_mode == "exact_attachment_and_url":
        second_entry["wordpress_attachment_id"] = first_entry[
            "wordpress_attachment_id"
        ]
    elif reuse_mode == "same_attachment_different_url":
        second_entry["wordpress_attachment_id"] = first_entry[
            "wordpress_attachment_id"
        ]
        second_entry["wordpress_original_url"] = (
            "https://staging.example.test/wp-content/uploads/2026/08/reused-hero.webp"
        )
    elif reuse_mode != "same_url_different_attachment":  # pragma: no cover
        raise AssertionError(reuse_mode)

    if accepted:
        finalized = finalize_performance_local_v5_staging_payload(
            prepared,
            mapping,
            expected_staging_origin="https://staging.example.test",
        )
        assert finalized.required_media[0].wordpress_media_id == (
            finalized.required_media[1].wordpress_media_id
        )
        assert finalized.required_media[0].payload_src == (
            finalized.required_media[1].payload_src
        )
    else:
        with pytest.raises(PerformanceLocalV5PayloadError) as rejected:
            finalize_performance_local_v5_staging_payload(
                prepared,
                mapping,
                expected_staging_origin="https://staging.example.test",
            )
        assert (
            rejected.value.code
            == "performance_local_v5_verified_media_mapping_ambiguous"
        )


def test_payload_preparation_rejects_cross_scope_logo_assignment(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _seed_builder_scope(session, monkeypatch)
    assignment = scope.logo_assignments["header_logo"]
    assignment.brand_id += 1000
    session.add(assignment)
    session.flush()

    with pytest.raises(PerformanceLocalV5PayloadError) as rejected:
        prepare_performance_local_v5_staging_payload(session, 41)

    assert rejected.value.code == "performance_local_v5_logo_identity_blocked"


def test_disposable_builder_binds_current_v9_content_cta_media_and_writes_nothing(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scope = _seed_builder_scope(session, monkeypatch)
    pending_before = (set(session.new), set(session.dirty), set(session.deleted))
    table_counts_before = {
        model: len(session.exec(select(model)).all())
        for model in (
            GeneratedPage,
            GeneratedPageRevision,
            PageComposition,
            PlannedPageMediaRequirement,
            ImageMetadata,
            PageImageAssignment,
        )
    }

    build = build_performance_local_v5_staging_payload(session, 41)

    assert build.wordpress_post_id == 8
    planned_inputs = [
        item
        for item in build.payload["payload_identity"]["frozen_inputs"]
        if item["path"].startswith("atlas/planned-page/")
    ]
    assert planned_inputs == [
        {
            "path": "atlas/planned-page/41",
            "sha256": performance_local_v5_payload_sha256(
                payload_service._planned_page_identity(scope.planned)
            ),
        }
    ]
    assert (
        build.source_bindings.generated_page_revision_id,
        build.source_bindings.page_composition_id,
        build.source_bindings.composition_version,
        build.source_bindings.page_composition_revision_id,
        build.source_bindings.qa_result_id,
    ) == (64, 41, 9, 107, 121)
    assert build.payload["page"]["h1"] == scope.page.h1
    assert build.payload["hero"]["introduction"] == scope.page.draft_content["intro"]
    assert build.payload["sections"][-1]["body"] == scope.page.draft_content[
        "call_to_action"
    ]
    assert build.payload["sticky_action"]["action"] == {
        "mode": "estimate",
        "label": "Request an Estimate",
        "href": "/request-an-estimate/",
    }
    assert build.payload["hero"]["estimate_action"] == {
        "label": "Request an Estimate",
        "href": "/request-an-estimate/",
    }
    assert len(build.required_media) == 3
    assert {
        (
            item.source_filename,
            item.source_mime_type,
            item.source_width,
            item.source_height,
            item.ready,
        )
        for item in build.required_media
    } == {
        ("hero-desktop.webp", "image/webp", 1600, 900, True),
        ("why-it-matters.webp", "image/webp", 1600, 900, True),
        ("what-to-look-for.webp", "image/webp", 1600, 900, True),
    }
    assert all(
        item.verification_source == "persisted_atlas"
        and item.observed_remote_sha256 == item.checksum_sha256
        and item.observed_remote_mime_type == item.source_mime_type
        and item.observed_remote_width == item.source_width
        and item.observed_remote_height == item.source_height
        for item in build.required_media
    )
    assert len(build.required_logo_media) == 2
    assert {item.role for item in build.required_logo_media} == {
        "header_logo",
        "footer_logo",
    }
    assert all(not item.ready for item in build.required_logo_media)
    assert {
        item.blocker for item in build.required_logo_media
    } == {"REMOTE_MEDIA_SYNC_REQUIRED"}
    assert all(item.payload_src for item in build.required_logo_media)
    assert {
        (item.role, item.assignment_id, item.assignment_version)
        for item in build.required_logo_media
    } == {
        (
            role,
            scope.logo_assignments[role].id,
            scope.logo_assignments[role].version,
        )
        for role in ("header_logo", "footer_logo")
    }
    assert not any(
        item["path"] == payload_service._VERIFIED_MEDIA_FROZEN_INPUT
        for item in build.payload["payload_identity"]["frozen_inputs"]
    )
    serialized = canonical_performance_local_v5_json(build.payload).decode("utf-8")
    for private_key in ("recipient_email", "from_email", "provider_secret_reference"):
        assert private_key not in serialized
    emitted = write_built_payload_json(build, tmp_path / "actual-builder-payload.json")
    assert json.loads(emitted.read_text(encoding="utf-8")) == [build.payload]
    assert (set(session.new), set(session.dirty), set(session.deleted)) == pending_before
    assert {
        model: len(session.exec(select(model)).all()) for model in table_counts_before
    } == table_counts_before


def test_disposable_builder_rejects_missing_and_stale_qa(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _seed_builder_scope(session, monkeypatch)
    scope.qa_state.ready = False
    scope.qa_state.record = None
    with pytest.raises(PerformanceLocalV5PayloadError) as missing:
        build_performance_local_v5_staging_payload(session, 41)
    assert missing.value.code == "performance_local_v5_qa_stale"

    scope.qa_state.ready = True
    scope.qa_state.record = scope.qa_record
    scope.qa_record.composition_version = 8
    with pytest.raises(PerformanceLocalV5PayloadError) as stale:
        build_performance_local_v5_staging_payload(session, 41)
    assert stale.value.code == "performance_local_v5_source_binding_stale"


def test_disposable_builder_rejects_non_city_service(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _seed_builder_scope(session, monkeypatch)
    scope.page.page_type = "service"
    session.add(scope.page)
    session.commit()

    with pytest.raises(PerformanceLocalV5PayloadError) as blocked:
        build_performance_local_v5_staging_payload(session, 41)

    assert blocked.value.code == "performance_local_v5_page_type_blocked"


def test_disposable_builder_rejects_missing_scoped_authorization_and_remote_media(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _seed_builder_scope(session, monkeypatch)
    missing_requirement = scope.media_rows[0][0]
    scope.authorizations.pop(missing_requirement.id)
    with pytest.raises(PerformanceLocalV5PayloadError, match="lacks a current scoped"):
        build_performance_local_v5_staging_payload(session, 41)

    scope.authorizations[missing_requirement.id] = scope.media_rows[0][3]
    monkeypatch.setattr(
        payload_service,
        "scoped_media_authorization_errors",
        lambda *_args, **_kwargs: ["authorization fingerprint is stale"],
    )
    with pytest.raises(PerformanceLocalV5PayloadError, match="authorization is stale"):
        build_performance_local_v5_staging_payload(session, 41)

    monkeypatch.setattr(
        payload_service,
        "scoped_media_authorization_errors",
        lambda *_args, **_kwargs: [],
    )
    image = scope.media_rows[0][1]
    image.wordpress_media_url = None
    image.wordpress_media_status = None
    image.wordpress_media_checksum = None
    session.add(image)
    session.commit()
    with pytest.raises(PerformanceLocalV5PayloadError) as remote:
        build_performance_local_v5_staging_payload(session, 41)
    assert remote.value.code == "REMOTE_MEDIA_SYNC_REQUIRED"
    assert remote.value.source_identity is not None
    assert remote.value.source_identity.source_bindings.composition_version == 9
    assert len(remote.value.required_media) == 3
    assert [item.ready for item in remote.value.required_media].count(False) == 1
    assert len(remote.value.required_logo_media) == 2


def test_disposable_builder_reports_governed_logo_transport_blocker(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _seed_builder_scope(session, monkeypatch)
    asset = scope.logo_rows["header_logo"]
    asset.asset_url = "/media/header-logo.webp"
    session.add(asset)
    scope.header_assets["header_logo"]["asset_url"] = asset.asset_url
    session.commit()

    with pytest.raises(PerformanceLocalV5PayloadError) as blocked:
        build_performance_local_v5_staging_payload(session, 41)

    assert blocked.value.code == "REMOTE_MEDIA_SYNC_REQUIRED"
    identity = next(
        item
        for item in blocked.value.required_logo_media
        if item.role == "header_logo"
    )
    assert identity.brand_asset_id == asset.id
    assert identity.checksum_sha256 == asset.checksum_sha256
    assert identity.source_filename == "header_logo.webp"
    assert identity.blocker == "REMOTE_MEDIA_SYNC_REQUIRED"
    assert identity.ready is False


def test_disposable_builder_rejects_disabled_or_unresolved_estimate_action(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _seed_builder_scope(session, monkeypatch)
    sticky = session.exec(
        select(WebsiteThemeComponentConfiguration).where(
            WebsiteThemeComponentConfiguration.website_id == scope.website.id,
            WebsiteThemeComponentConfiguration.component_key
            == "sticky_mobile_action_bar",
            WebsiteThemeComponentConfiguration.component_contract_version == 3,
        )
    ).one()
    sticky.enabled = False
    sticky.integrity_fingerprint = theme_service._component_fingerprint_from_record(
        sticky
    )
    session.add(sticky)
    session.commit()

    with pytest.raises(PerformanceLocalV5PayloadError) as blocked:
        build_performance_local_v5_staging_payload(session, 41)

    assert blocked.value.code == "performance_local_v5_registration_conflict"


def test_disposable_builder_uses_exact_selected_v5_graph_after_registration(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _seed_builder_scope(session, monkeypatch)
    applied = apply_performance_local_v5_registration(
        session,
        scope.website.id,
        actor="Disposable V5 Builder Test",
    )
    assert applied.status == "APPLIED"

    build = build_performance_local_v5_staging_payload(session, 41)

    frozen_paths = {
        item["path"] for item in build.payload["payload_identity"]["frozen_inputs"]
    }
    assert (
        f"atlas/website-theme-configuration/"
        f"{applied.identity.website_theme_configuration_id}"
    ) in frozen_paths
    assert all(
        f"atlas/website-theme-component-configuration/{component_id}" in frozen_paths
        for component_id in applied.identity.component_configuration_ids
    )


def test_wordpress_media_path_is_never_synthesized() -> None:
    checksum = "a" * 64
    image = ImageMetadata(
        business_id=1,
        file_name="hero.webp",
        checksum_sha256=checksum,
        wordpress_media_id=31,
        wordpress_media_url="http://localhost:8000/media/originals/hero.webp",
        wordpress_media_status="verified",
        wordpress_media_checksum=checksum,
    )
    assert _verified_wordpress_media_path(image) is None

    image.wordpress_media_url = (
        "https://staging.example.test/wp-content/uploads/atlas-v5/hero.webp"
    )
    assert _verified_wordpress_media_path(image) == "/wp-content/uploads/atlas-v5/hero.webp"
    assert _upload_path(image.wordpress_media_url, "test") == "/wp-content/uploads/atlas-v5/hero.webp"

    image.wordpress_media_url += "?cache=1"
    assert _verified_wordpress_media_path(image) is None


def test_registration_plan_apply_and_repeat_are_deterministic(session: Session) -> None:
    website_id, v2_id, v3_id = _seed_v3_graph(session)
    durable_insert_models = (
        ThemeFamilyVersion,
        WebsiteThemeConfiguration,
        WebsiteThemeComponentConfiguration,
        ThemeConfigurationAudit,
        Theme,
        WebsiteThemeSelection,
    )
    durable_counts_before = {
        model: len(session.exec(select(model)).all())
        for model in durable_insert_models
    }
    preserved_versions_before = {
        item.id: deepcopy(item.model_dump())
        for item in session.exec(
            select(ThemeFamilyVersion).where(
                ThemeFamilyVersion.id.in_([v2_id, v3_id])
            )
        ).all()
    }
    preserved_v3_components_before = {
        item.id: deepcopy(item.model_dump())
        for item in session.exec(
            select(WebsiteThemeComponentConfiguration).where(
                WebsiteThemeComponentConfiguration.website_id == website_id,
                WebsiteThemeComponentConfiguration.component_contract_version == 3,
            )
        ).all()
    }
    preserved_v3_configuration = session.exec(
        select(WebsiteThemeConfiguration).where(
            WebsiteThemeConfiguration.website_id == website_id,
            WebsiteThemeConfiguration.configuration_key == "performance-local-v3",
        )
    ).one()
    preserved_v3_configuration_before = deepcopy(
        preserved_v3_configuration.model_dump()
    )
    default_theme = session.exec(
        select(Theme).where(
            Theme.website_id == website_id,
            Theme.theme_key == "flo-zone-default",
        )
    ).one()
    default_theme_before = deepcopy(default_theme.model_dump())
    prior_selection = session.exec(
        select(WebsiteThemeSelection).where(
            WebsiteThemeSelection.website_id == website_id,
            WebsiteThemeSelection.status == "active",
        )
    ).one()
    prior_selection_before = deepcopy(prior_selection.model_dump())
    pending_before = (set(session.new), set(session.dirty), set(session.deleted))

    planned = plan_performance_local_v5_registration(session, website_id)

    assert planned.status == "PLANNED"
    assert [item.order for item in planned.actions] == list(range(1, 9))
    assert (set(session.new), set(session.dirty), set(session.deleted)) == pending_before

    applied = apply_performance_local_v5_registration(
        session,
        website_id,
        actor="Disposable V5 Registration Test",
    )
    assert applied.status == "APPLIED"
    assert len(applied.identity.component_configuration_ids) == 3
    assert len(applied.audit_ids) == 6
    assert applied.identity.theme_family_version_id is not None
    assert applied.identity.website_theme_configuration_id is not None
    assert _v5_audit_natural_identities(
        session,
        version_id=applied.identity.theme_family_version_id,
        configuration_id=applied.identity.website_theme_configuration_id,
        component_ids=applied.identity.component_configuration_ids,
    ) == [
        ("family_version", "family_version_registered"),
        ("configuration", "website_draft_created"),
        ("compact_estimate_form", "component_created"),
        ("campaign_banner", "component_created"),
        ("sticky_mobile_action_bar", "component_created"),
        ("family_version", "family_version_approved"),
        ("configuration", "website_configuration_approved"),
        ("configuration", "website_configuration_activated"),
        ("compact_estimate_form", "component_activated"),
        ("campaign_banner", "component_activated"),
        ("sticky_mobile_action_bar", "component_activated"),
    ]
    durable_count_deltas = {
        model: len(session.exec(select(model)).all()) - durable_counts_before[model]
        for model in durable_insert_models
    }
    assert durable_count_deltas == {
        ThemeFamilyVersion: 1,
        WebsiteThemeConfiguration: 1,
        WebsiteThemeComponentConfiguration: 3,
        ThemeConfigurationAudit: 11,
        Theme: 1,
        WebsiteThemeSelection: 1,
    }
    assert sum(durable_count_deltas.values()) == 18
    replaced_selection = session.get(WebsiteThemeSelection, prior_selection.id)
    assert replaced_selection is not None
    assert replaced_selection.status == "replaced"
    assert replaced_selection.version == 1
    assert replaced_selection.theme_id == prior_selection_before["theme_id"]

    durable_before_replay = {
        model: [
            deepcopy(item.model_dump())
            for item in session.exec(select(model).order_by(model.id)).all()
        ]
        for model in durable_insert_models
    }

    unchanged = plan_performance_local_v5_registration(session, website_id)
    repeated = apply_performance_local_v5_registration(
        session,
        website_id,
        actor="Disposable V5 Registration Test",
    )
    assert unchanged.status == "UNCHANGED"
    assert repeated.status == "UNCHANGED"
    assert repeated.identity == applied.identity
    assert repeated.audit_ids == []
    assert {
        model: [
            item.model_dump()
            for item in session.exec(select(model).order_by(model.id)).all()
        ]
        for model in durable_insert_models
    } == durable_before_replay

    session.expire_all()
    assert {
        item.id: item.model_dump()
        for item in session.exec(
            select(ThemeFamilyVersion).where(
                ThemeFamilyVersion.id.in_([v2_id, v3_id])
            )
        ).all()
    } == preserved_versions_before
    assert {
        item.id: item.model_dump()
        for item in session.exec(
            select(WebsiteThemeComponentConfiguration).where(
                WebsiteThemeComponentConfiguration.website_id == website_id,
                WebsiteThemeComponentConfiguration.component_contract_version == 3,
            )
        ).all()
    } == preserved_v3_components_before
    assert session.get(
        WebsiteThemeConfiguration, preserved_v3_configuration.id
    ).model_dump() == preserved_v3_configuration_before
    assert session.get(Theme, default_theme.id).model_dump() == default_theme_before

    versions = session.exec(select(ThemeFamilyVersion)).all()
    assert {item.id for item in versions} >= {v2_id, v3_id}
    assert [item.version for item in versions].count(PERFORMANCE_LOCAL_V5_FAMILY_VERSION) == 1
    assert len(
        session.exec(
            select(WebsiteThemeComponentConfiguration).where(
                WebsiteThemeComponentConfiguration.website_id == website_id,
                WebsiteThemeComponentConfiguration.component_contract_version == 3,
            )
        ).all()
    ) == 3
    assert len(
        session.exec(
            select(WebsiteThemeComponentConfiguration).where(
                WebsiteThemeComponentConfiguration.website_id == website_id,
                WebsiteThemeComponentConfiguration.component_contract_version == 5,
            )
        ).all()
    ) == 3
    assert len(
        session.exec(
            select(Theme).where(
                Theme.website_id == website_id,
                Theme.theme_key == PERFORMANCE_LOCAL_V5_THEME_KEY,
            )
        ).all()
    ) == 1
    assert sum(
        item.status == "active"
        for item in session.exec(
            select(WebsiteThemeSelection).where(
                WebsiteThemeSelection.website_id == website_id
            )
        ).all()
    ) == 1


def test_registration_genuine_audit_mismatch_fails_closed_and_rolls_back(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website_id, _, _ = _seed_v3_graph(session)
    preserved_models = (
        ThemeFamilyVersion,
        WebsiteThemeConfiguration,
        WebsiteThemeComponentConfiguration,
        ThemeConfigurationAudit,
        Theme,
        WebsiteThemeSelection,
    )
    durable_before = {
        model: [
            deepcopy(item.model_dump())
            for item in session.exec(select(model).order_by(model.id)).all()
        ]
        for model in preserved_models
    }
    append_audit = theme_service._append_audit

    def append_one_wrong_action(*args: object, **kwargs: object) -> ThemeConfigurationAudit:
        snapshot = kwargs.get("snapshot")
        if (
            kwargs.get("action_type") == "component_activated"
            and isinstance(snapshot, dict)
            and snapshot.get("component_key") == "campaign_banner"
        ):
            kwargs["action_type"] = "component_created"
        return append_audit(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(theme_service, "_append_audit", append_one_wrong_action)

    with pytest.raises(
        PerformanceLocalV5RegistrationError,
        match="V5 audit graph is not exact",
    ):
        apply_performance_local_v5_registration(
            session,
            website_id,
            actor="Disposable V5 Registration Test",
        )

    assert {
        model: [
            item.model_dump()
            for item in session.exec(select(model).order_by(model.id)).all()
        ]
        for model in preserved_models
    } == durable_before
    assert not session.exec(
        select(ThemeFamilyVersion).where(
            ThemeFamilyVersion.version == PERFORMANCE_LOCAL_V5_FAMILY_VERSION
        )
    ).all()
    assert not session.exec(
        select(Theme).where(Theme.theme_key == PERFORMANCE_LOCAL_V5_THEME_KEY)
    ).all()


def test_registration_replay_rejects_a_corrupted_audit_envelope(
    session: Session,
) -> None:
    website_id, _, _ = _seed_v3_graph(session)
    applied = apply_performance_local_v5_registration(
        session,
        website_id,
        actor="Disposable V5 Registration Test",
    )
    assert applied.identity.theme_family_version_id is not None
    assert applied.identity.website_theme_configuration_id is not None
    audit = _v5_audits(
        session,
        version_id=applied.identity.theme_family_version_id,
        configuration_id=applied.identity.website_theme_configuration_id,
        component_ids=applied.identity.component_configuration_ids,
    )[0]
    audit.snapshot = {**audit.snapshot, "deliberate_test_tamper": True}
    session.add(audit)
    session.commit()
    counts_before = {
        model: len(session.exec(select(model)).all())
        for model in (
            ThemeFamilyVersion,
            WebsiteThemeConfiguration,
            WebsiteThemeComponentConfiguration,
            ThemeConfigurationAudit,
            Theme,
            WebsiteThemeSelection,
        )
    }

    plan = plan_performance_local_v5_registration(session, website_id)

    assert plan.status == "CONFLICT"
    assert any("audit graph is not exact" in blocker for blocker in plan.blockers)
    with pytest.raises(PerformanceLocalV5RegistrationError):
        apply_performance_local_v5_registration(
            session,
            website_id,
            actor="Disposable V5 Registration Test",
        )
    assert {
        model: len(session.exec(select(model)).all()) for model in counts_before
    } == counts_before


def test_partial_v5_registration_is_a_conflict(session: Session) -> None:
    website_id, _, _ = _seed_v3_graph(session)
    source = session.exec(
        select(Theme).where(
            Theme.website_id == website_id,
            Theme.theme_key == "flo-zone-default",
        )
    ).one()
    session.add(
        Theme(
            website_id=website_id,
            business_id=source.business_id,
            brand_id=source.brand_id,
            theme_key=PERFORMANCE_LOCAL_V5_THEME_KEY,
            theme_name="Partial V5",
            version=1,
            token_contract_version=source.token_contract_version,
            design_tokens=source.design_tokens,
            token_hash_sha256=source.token_hash_sha256,
            lifecycle_status="available",
            approval_status="approved",
            created_by="fixture",
            provenance_type="operator_configured",
            provenance_notes="Deliberately incomplete disposable fixture.",
            approved_by="fixture",
            approved_at=datetime.now(UTC),
        )
    )
    session.commit()

    plan = plan_performance_local_v5_registration(session, website_id)

    assert plan.status == "CONFLICT"
    assert plan.actions == []
    assert any("partial" in item.lower() for item in plan.blockers)
    assert not session.exec(
        select(ThemeFamilyVersion).where(
            ThemeFamilyVersion.version == PERFORMANCE_LOCAL_V5_FAMILY_VERSION
        )
    ).all()


def test_exact_v5_plan_rejects_component_drift_from_governed_v3(session: Session) -> None:
    website_id, _, _ = _seed_v3_graph(session)
    applied = apply_performance_local_v5_registration(
        session,
        website_id,
        actor="Disposable V5 Registration Test",
    )
    campaign = session.exec(
        select(WebsiteThemeComponentConfiguration).where(
            WebsiteThemeComponentConfiguration.id.in_(
                applied.identity.component_configuration_ids
            ),
            WebsiteThemeComponentConfiguration.component_key == "campaign_banner",
        )
    ).one()
    campaign.configuration_payload = {
        **campaign.configuration_payload,
        "message": "Tampered but internally fingerprinted",
    }
    campaign.integrity_fingerprint = theme_service._component_fingerprint_from_record(
        campaign
    )
    session.add(campaign)
    session.commit()

    plan = plan_performance_local_v5_registration(session, website_id)

    assert plan.status == "CONFLICT"
    assert any("exact governed V3 input" in item for item in plan.blockers)
