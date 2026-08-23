from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Callable
import unicodedata
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Brand,
    BrandAsset,
    Business,
    City,
    County,
    DraftingEligibilityAssessment,
    DraftingEligibilityDisposition,
    GeneratedPage,
    GeneratedPageQAResult,
    GeneratedPageRevision,
    ImageMetadata,
    InternalLinkIntent,
    KnowledgeBlock,
    NavigationItem,
    NavigationSet,
    PageComposition,
    PageCompositionRevision,
    PageImageAssignment,
    PlannedPage,
    PlannedPageMediaRequirement,
    PlanningRecord,
    PreDraftDistinctnessBrief,
    SemanticComponentDefinition,
    Service,
    SitePlan,
    ScopedMediaAuthorization,
    SupportingPageAuthorization,
    Theme,
    Website,
    WebsiteCityCoverageDecision,
    WebsiteCountyCoverageDecision,
    WebsiteIdentity,
    WebsiteIdentityAssetAssignment,
    WebsiteMediaPlanningRecord,
    WebsiteServiceCityCoverageDecision,
    WebsiteServiceCountyCoverageDecision,
    WebsiteServiceCoverageDecision,
    WebsiteThemeSelection,
)
from app.services import page_composition as page_composition_service
from app.services import page_editor as page_editor_service
from app.services import public_copy_audit as public_copy_audit_service
from app.services import public_copy_reconciliation as reconciliation_service
from app.services import public_destination_copy as destination_copy_service
from app.services.approval_audit import draft_content_hash
from app.services.page_composition import refresh_site_plan_compositions
from app.services.page_composition_history import current_composition_revision
from app.services.drafting_eligibility import DraftingEligibilityError
from app.services.page_editor import (
    ManifestBoundFullDraftRevisionAuthority,
    save_full_draft_revision,
)
from app.services.page_qa import save_page_qa
from app.schemas.site_plans import PlannedPageDraftContent
from app.services.planned_page_drafting import render_planned_page_content
from app.services.public_copy_manifest import (
    PUBLIC_COPY_ACTIVE_ATLAS_REVISION,
    PUBLIC_COPY_AUTHORIZATION_LINE_COUNT,
    PUBLIC_COPY_AUTHORIZATION_ORIGINAL_0046_BOUNDARY,
    PUBLIC_COPY_AUTHORIZATION_PATH,
    PUBLIC_COPY_AUTHORIZATION_SHA256,
    PUBLIC_COPY_AUTHORIZATION_SIZE_BYTES,
    PUBLIC_COPY_DATABASE_ROW_TIMESTAMP_CONTRACT,
    PUBLIC_COPY_MANIFEST_SCHEMA,
    PUBLIC_COPY_RESUME_AUTHORIZATION_CANONICAL_ENCODING,
    PUBLIC_COPY_RESUME_AUTHORIZATION_EFFECT,
    PUBLIC_COPY_RESUME_AUTHORIZATION_LINE_COUNT,
    PUBLIC_COPY_RESUME_AUTHORIZATION_SHA256,
    PUBLIC_COPY_RESUME_AUTHORIZATION_SIZE_BYTES,
    PUBLIC_COPY_RESUME_AUTHORIZATION_SOURCE,
    PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_PATH,
    PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SCHEMA,
    PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SHA256,
    PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SIZE_BYTES,
    PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_STATUS,
    PUBLIC_COPY_RULESET_SCHEMA,
    PublicCopyManifestPackage,
    canonical_json_sha256,
    canonical_model_row_sha256,
    canonical_model_rows_sha256,
    canonicalize_model_row_timestamps,
    load_public_copy_manifest_package,
)
from app.services.public_copy_reconciliation import (
    PUBLIC_COPY_RECONCILIATION_REASON_PREFIX,
    PublicCopyReconciliationError,
    PublicCopyReconciliationInjectedFailure,
    reconcile_public_copy,
)
from app.services.public_destination_copy import (
    PUBLIC_COPY_RULESET_HASH,
    PUBLIC_COPY_RULESET_IDENTITY,
    PUBLIC_COPY_RULESET_KEY,
    PUBLIC_COPY_RULESET_VERSION,
    build_public_destination_copy,
    build_public_copy_reconciled_draft,
)
from app.services.site_connections import ensure_site_connection_foundation


_COMPONENT_CONTRACTS = {
    "website_header": (["business_identity"], ["all"], ["default"]),
    "primary_navigation": (["navigation:primary"], ["all"], ["default"]),
    "utility_navigation": (["navigation:utility"], ["all"], ["default"]),
    "footer_navigation": (["navigation:footer"], ["all"], ["default"]),
    "hero": (["draft:h1"], ["all"], ["default", "local"]),
    "content_section": (["draft:section"], ["all"], ["default", "muted"]),
    "service_summary": (
        ["service", "draft:section"],
        ["service", "county", "city_service"],
        ["default"],
    ),
    "trust_license": (["trust_information"], ["all"], ["default"]),
    "destination_cards": (
        ["related_pages"],
        ["service", "county", "city_service"],
        ["default"],
    ),
    "related_page_links": (["related_pages"], ["all"], ["default"]),
    "faq": (["draft:faq_items"], ["all"], ["default"]),
    "contact_pathways": (["contact_information"], ["contact"], ["default"]),
    "media_placement": (
        ["media_placement"],
        ["all"],
        ["placeholder", "approved_media"],
    ),
    "final_cta": (["draft:call_to_action"], ["all"], ["default"]),
    "website_footer": (["business_identity"], ["all"], ["default"]),
}

_LOCKED_SOURCE_MODELS = {
    "brand_assets": BrandAsset,
    "brands": Brand,
    "businesses": Business,
    "cities": City,
    "counties": County,
    "drafting_eligibility_assessments": DraftingEligibilityAssessment,
    "drafting_eligibility_dispositions": DraftingEligibilityDisposition,
    "image_metadata": ImageMetadata,
    "knowledge_blocks": KnowledgeBlock,
    "navigation_items": NavigationItem,
    "navigation_sets": NavigationSet,
    "page_image_assignments": PageImageAssignment,
    "planned_page_media_requirements": PlannedPageMediaRequirement,
    "planned_pages": PlannedPage,
    "planning_records": PlanningRecord,
    "pre_draft_distinctness_briefs": PreDraftDistinctnessBrief,
    "scoped_media_authorizations": ScopedMediaAuthorization,
    "semantic_component_definitions": SemanticComponentDefinition,
    "services": Service,
    "site_plans": SitePlan,
    "supporting_page_authorizations": SupportingPageAuthorization,
    "themes": Theme,
    "website_city_coverage_decisions": WebsiteCityCoverageDecision,
    "website_county_coverage_decisions": WebsiteCountyCoverageDecision,
    "website_identities": WebsiteIdentity,
    "website_identity_asset_assignments": WebsiteIdentityAssetAssignment,
    "website_media_planning_records": WebsiteMediaPlanningRecord,
    "website_service_city_coverage_decisions": WebsiteServiceCityCoverageDecision,
    "website_service_county_coverage_decisions": WebsiteServiceCountyCoverageDecision,
    "website_service_coverage_decisions": WebsiteServiceCoverageDecision,
    "website_theme_selections": WebsiteThemeSelection,
    "websites": Website,
}

_GENERATED_PAGE_PRESERVED_FIELDS = (
    "id",
    "business_id",
    "website_id",
    "service_id",
    "city_id",
    "county_id",
    "page_type",
    "page_slug",
    "generation_status",
    "generated_at",
    "internal_notes",
    "last_reviewed_at",
    "last_reviewed_by",
    "status",
    "wordpress_post_id",
    "wordpress_url",
    "wordpress_status",
    "wordpress_created_at",
    "last_wordpress_sync_at",
    "created_at",
)


@dataclass
class _Scope:
    engine: object
    session: Session
    website: Website
    plan: SitePlan
    planned_pages: list[PlannedPage]
    generated_pages: list[GeneratedPage]
    manifest: dict
    ruleset: dict

    def load_package(
        self,
        tmp_path: Path,
        *,
        mutate_manifest: Callable[[dict], None] | None = None,
    ) -> PublicCopyManifestPackage:
        manifest = deepcopy(self.manifest)
        ruleset = deepcopy(self.ruleset)
        if mutate_manifest is not None:
            mutate_manifest(manifest)
            _reseal_fixture_manifest(manifest, ruleset)
        suffix = uuid4().hex
        manifest_path = tmp_path / f"manifest-{suffix}.json"
        ruleset_path = tmp_path / f"ruleset-{suffix}.json"
        manifest_sha = _write_json(manifest_path, manifest)
        ruleset_sha = _write_json(ruleset_path, ruleset)
        return load_public_copy_manifest_package(
            manifest_path,
            manifest_sha256=manifest_sha,
            ruleset_path=ruleset_path,
            ruleset_sha256=ruleset_sha,
        )


def _fixture_ruleset() -> dict:
    ruleset = {
        "schema": PUBLIC_COPY_RULESET_SCHEMA,
        "key": PUBLIC_COPY_RULESET_KEY,
        "version": PUBLIC_COPY_RULESET_VERSION,
        "identity": PUBLIC_COPY_RULESET_IDENTITY,
        "customer_data": False,
        "normalization": {
            "unicode": "NFKC",
            "case": "casefold",
            "whitespace": "collapse",
        },
        "blockers": ["approved destination", "generated page", "atlas"],
    }
    ruleset["seal"] = {
        "canonical_payload_sha256": canonical_json_sha256(ruleset),
        "customer_data": False,
    }
    return ruleset


def _reseal_fixture_manifest(manifest: dict, ruleset: dict) -> None:
    manifest.pop("seal", None)
    manifest["seal"] = {
        "algorithm": "sha256",
        "canonicalization": (
            "UTF-8 JSON; sorted keys; separators comma/colon; "
            "ensure_ascii=true; seal excluded"
        ),
        "canonical_manifest_payload_sha256": canonical_json_sha256(manifest),
        "ruleset_canonical_payload_sha256": ruleset["seal"][
            "canonical_payload_sha256"
        ],
        "source_backup_sha256": "8" * 64,
        "original_authorization_sha256": PUBLIC_COPY_AUTHORIZATION_SHA256,
        "resume_authorization_sha256": (
            PUBLIC_COPY_RESUME_AUTHORIZATION_SHA256
        ),
        "resume_preflight_seal_sha256": (
            PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SHA256
        ),
        "operator_intents_snapshot_sha256": "9" * 64,
        "expected_page_hashes_sha256": "a" * 64,
        "pre_repair_source_module_snapshot_sha256": "b" * 64,
        "execution_source_module_list_sha256": "c" * 64,
        "locked_source_table_sha256_package_sha256": "d" * 64,
        "immutable_history_snapshot_sha256": "e" * 64,
        "customer_data": False,
    }


@pytest.fixture
def scope(monkeypatch: pytest.MonkeyPatch) -> _Scope:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(
        page_editor_service,
        "require_effective_drafting_eligibility",
        lambda *args, **kwargs: None,
    )
    session = Session(engine)
    result = _seed_scope(session, engine, monkeypatch=monkeypatch)
    try:
        yield result
    finally:
        session.close()
        engine.dispose()


def _seed_scope(
    session: Session,
    engine: object,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> _Scope:
    fixture_ruleset = _fixture_ruleset()
    fixture_ruleset_hash = fixture_ruleset["seal"][
        "canonical_payload_sha256"
    ]
    monkeypatch.setattr(
        destination_copy_service,
        "PUBLIC_COPY_RULESET_HASH",
        fixture_ruleset_hash,
    )
    monkeypatch.setattr(
        page_composition_service,
        "PUBLIC_COPY_RULESET_HASH",
        fixture_ruleset_hash,
    )
    monkeypatch.setattr(
        reconciliation_service,
        "PUBLIC_COPY_RULESET_HASH",
        fixture_ruleset_hash,
    )
    monkeypatch.setattr(
        public_copy_audit_service,
        "PUBLIC_COPY_RULESET_CANONICAL_PAYLOAD_SHA256",
        fixture_ruleset_hash,
    )
    for key, (inputs, page_types, variants) in _COMPONENT_CONTRACTS.items():
        session.add(
            SemanticComponentDefinition(
                component_key=key,
                contract_version=1,
                purpose=f"Semantic purpose for {key}.",
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
            )
        )
    business = Business(
        company_name="Example Pest Solutions Inc",
        brand_name="Example Tenting",
        business_type="Local service business",
        phone="407-555-0100",
        email="office@example.test",
        main_city="Orlando",
        state="FL",
        license_number="LIC-100",
        certified_operator="Jordan Example",
        description=(
            "Drywood termite tenting for homeowners and property professionals "
            "across Central Florida."
        ),
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id or 0,
        brand_name="Example Tenting",
        tagline="Straightforward service information",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id or 0,
        brand_id=brand.id,
        website_name="Example Tenting Website",
        domain="example-tenting.test",
        public_url="https://example-tenting.test",
        configuration={
            "state_name": "Florida",
            "market_state_codes": ["FL"],
        },
    )
    session.add(website)
    session.flush()
    session.add(
        WebsiteIdentity(
            website_id=website.id or 0,
            display_name="Example Tenting",
            status="active",
        )
    )
    service = Service(
        business_id=business.id or 0,
        service_name="Drywood Termite Tenting",
        service_slug="drywood-termite-tenting",
        short_description="Whole-structure drywood termite tenting.",
        status="active",
    )
    session.add(service)
    session.flush()
    plan = SitePlan(
        website_id=website.id or 0,
        plan_key="primary",
        plan_name="Primary Site Plan",
        status="active",
    )
    session.add(plan)
    session.flush()
    ensure_site_connection_foundation(session, plan)

    generated_pages: list[GeneratedPage] = []
    planned_pages: list[PlannedPage] = []
    for page_type, title, slug in (
        ("service", "Drywood Termite Tenting", "drywood-termite-tenting"),
        ("contact", "Contact", "contact"),
    ):
        draft = _draft(page_type, title)
        generated = GeneratedPage(
            business_id=business.id or 0,
            website_id=website.id,
            service_id=service.id if page_type == "service" else None,
            page_type=page_type,
            page_title=draft["title"],
            page_slug=slug,
            meta_title=draft["meta_title"],
            meta_description=draft["meta_description"],
            h1=draft["h1"],
            draft_content=deepcopy(draft),
            content_body=draft["intro"],
            generation_status="generated",
            status="approved",
        )
        session.add(generated)
        session.flush()
        planned = PlannedPage(
            website_id=website.id or 0,
            site_plan_id=plan.id or 0,
            page_type=page_type,
            working_name=title,
            intended_slug=slug,
            service_id=service.id if page_type == "service" else None,
            planning_status="generated",
            generated_page_id=generated.id,
        )
        session.add(planned)
        session.flush()
        planning_record = PlanningRecord(
            planned_page_id=planned.id or 0,
            generated_answers={},
            operator_overrides={},
            source_snapshot={"fixture": True},
            confidence_score=1.0,
            confidence_level="high",
            missing_information=[],
            improvement_recommendations=[],
            generated_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        )
        session.add(planning_record)
        session.flush()
        assessment_status = (
            "insufficient_local_value"
            if page_type == "service"
            else "semantic_duplication"
        )
        session.add(
            DraftingEligibilityAssessment(
                website_id=website.id or 0,
                site_plan_id=plan.id or 0,
                planned_page_id=planned.id or 0,
                status=assessment_status,
                algorithm_version="drafting-eligibility-v3",
                coverage_binding={"fixture": True, "page_type": page_type},
                expected_inventory_binding={"fixture": True},
                planning_record_binding={
                    "planning_record_id": planning_record.id,
                },
                distinctness_brief_binding={"fixture": True},
                approved_source_identities=[],
                evidence={"fixture": True},
                local_value_findings=[],
                semantic_findings=[],
                reasons=[
                    "Preserved synthetic non-eligible assessment evidence."
                ],
                assessed_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
            )
        )
        draft["planning_record_id"] = planning_record.id
        generated.draft_content = deepcopy(draft)
        generated.content_body = render_planned_page_content(
            PlannedPageDraftContent.model_validate(draft)
        )
        session.add(generated)
        generated_pages.append(generated)
        planned_pages.append(planned)

    decided_at = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    navigation_sets = {
        item.set_type: item
        for item in session.exec(
            select(NavigationSet).where(NavigationSet.site_plan_id == plan.id)
        ).all()
    }
    for navigation_set in navigation_sets.values():
        navigation_set.status = "active"
        navigation_set.rationale = "Approved navigation fixture."
        navigation_set.decided_by = "Fixture Operator"
        navigation_set.decision_version = 1
        navigation_set.decided_at = decided_at
        session.add(navigation_set)
    for position, planned in enumerate(planned_pages):
        session.add(
            NavigationItem(
                website_id=website.id or 0,
                site_plan_id=plan.id or 0,
                navigation_set_id=navigation_sets["primary"].id or 0,
                target_planned_page_id=planned.id or 0,
                label=planned.working_name,
                position=position,
                status="active",
                rationale="Approved primary navigation destination.",
                decided_by="Fixture Operator",
                decision_version=1,
                decided_at=decided_at,
            )
        )
    for set_type in ("utility", "footer"):
        session.add(
            NavigationItem(
                website_id=website.id or 0,
                site_plan_id=plan.id or 0,
                navigation_set_id=navigation_sets[set_type].id or 0,
                target_planned_page_id=planned_pages[1].id or 0,
                label="Contact",
                position=0,
                status="active",
                rationale=f"Approved {set_type} destination.",
                decided_by="Fixture Operator",
                decision_version=1,
                decided_at=decided_at,
            )
        )
    for index, (source, target) in enumerate(
        (
            (planned_pages[0], planned_pages[1]),
            (planned_pages[1], planned_pages[0]),
        ),
        start=1,
    ):
        session.add(
            InternalLinkIntent(
                website_id=website.id or 0,
                site_plan_id=plan.id or 0,
                source_planned_page_id=source.id or 0,
                target_planned_page_id=target.id or 0,
                purpose=(
                    "Connect the generated page to the approved destination."
                ),
                relationship_type="conversion",
                anchor_guidance=f"Fixture anchor {index}",
                approval_state="approved",
                rationale="Operator routing evidence remains private and immutable.",
                decided_by="Fixture Operator",
                decision_version=1,
                decided_at=decided_at,
                source_suggestion_key=f"fixture-link-{index}",
            )
        )
    session.flush()

    revision_time = datetime.now(UTC) - timedelta(days=1)
    for generated in generated_pages:
        current = deepcopy(generated.draft_content or {})
        predecessor = deepcopy(current)
        predecessor["intro"] = f"Earlier fixture copy for {generated.page_title}."
        session.add(
            GeneratedPageRevision(
                generated_page_id=generated.id or 0,
                created_at=revision_time,
                created_by="Fixture Generator",
                reason="Establish immutable predecessor evidence.",
                draft_hash_before=draft_content_hash(predecessor),
                draft_hash_after=draft_content_hash(current),
                draft_content_before=predecessor,
                draft_content_after=current,
                changed_fields=["intro"],
            )
        )
    session.commit()

    # Recreate the exact pre-foundation state: the historical composition and
    # QA are legitimate, but destination copy was not revision-owned yet. The
    # production resolver is restored before the manifest is derived or the
    # reconciliation API runs.
    strict_destination_reader = (
        page_composition_service.require_public_destination_copy
    )
    monkeypatch.setattr(
        page_composition_service,
        "require_public_destination_copy",
        lambda session, plan, planned, generated, **kwargs: (
            build_public_destination_copy(
                session,
                plan,
                planned,
                generated,
                draft_content=generated.draft_content or {},
            )
        ),
    )
    refresh = refresh_site_plan_compositions(session, plan.id or 0)
    assert refresh.blocked == []
    assert refresh.created == 2
    for generated in generated_pages:
        save_page_qa(session, generated.id or 0, commit=False)
    session.commit()
    monkeypatch.setattr(
        page_composition_service,
        "require_public_destination_copy",
        strict_destination_reader,
    )

    manifest, ruleset = _build_package_payload(
        session,
        website=website,
        plan=plan,
        planned_pages=planned_pages,
        generated_pages=generated_pages,
    )
    return _Scope(
        engine=engine,
        session=session,
        website=website,
        plan=plan,
        planned_pages=planned_pages,
        generated_pages=generated_pages,
        manifest=manifest,
        ruleset=ruleset,
    )


def _draft(page_type: str, title: str) -> dict:
    if page_type == "service":
        sections = [
            {
                "key": "service_overview",
                "heading": "Service Overview",
                "body": "Whole-structure tenting addresses active drywood termites.",
            },
            {
                "key": "approved_guidance",
                "heading": "Preparation Guidance",
                "body": "Customers receive job-specific preparation instructions.",
            },
            {
                "key": "service_area",
                "heading": "Service Area",
                "body": (
                    "Example Tenting provides drywood termite tenting throughout "
                    "its Central Florida service area."
                ),
            },
        ]
        intro = "Learn about drywood termite tenting and preparation."
        cta = "Request an Estimate for Drywood Termite Tenting."
    else:
        sections = [
            {
                "key": "ways_to_contact",
                "heading": "Ways to Contact Us",
                "body": "Phone: 407-555-0100. Email: office@example.test.",
            },
            {
                "key": "hours",
                "heading": "Availability",
                "body": "Contact the office for current availability.",
            },
            {
                "key": "service_area",
                "heading": "Service Area",
                "body": "Example Tenting serves customers across Central Florida.",
            },
        ]
        intro = (
            "Contact Example Tenting by phone or email to discuss drywood "
            "termite tenting and request an estimate."
        )
        cta = "Call Example Tenting or Request an Estimate."
    meta_description = (
        intro
        if page_type == "contact"
        else f"{title} information from Example Tenting."
    )
    return {
        "schema_version": "planned-page-draft-v1",
        "page_type": page_type,
        "title": title,
        "meta_title": f"{title} | Example Tenting",
        "meta_description": meta_description,
        "h1": title,
        "intro": intro,
        "sections": sections,
        "faq_items": [],
        "image_placements": [],
        "related_pages": [],
        "call_to_action": cta,
        "public_destination_copy": [],
        "internal_notes": "Synthetic fixture; never part of the public projection.",
        "planning_record_id": 1,
        "planning_generated_at": "2026-08-20T12:00:00+00:00",
        "operator_override_keys": [],
        "status": "approved",
    }


def _build_package_payload(
    session: Session,
    *,
    website: Website,
    plan: SitePlan,
    planned_pages: list[PlannedPage],
    generated_pages: list[GeneratedPage],
) -> tuple[dict, dict]:
    business = session.get(Business, website.business_id)
    brand = session.get(Brand, website.brand_id)
    assert business is not None
    assert brand is not None
    ruleset = _fixture_ruleset()
    corrections: list[dict] = []
    bindings: list[dict] = []
    for index, (planned, generated) in enumerate(
        zip(planned_pages, generated_pages, strict=True),
        start=1,
    ):
        current = deepcopy(generated.draft_content or {})
        expected = build_public_copy_reconciled_draft(session, planned, current)
        current_hash = draft_content_hash(current)
        expected_hash = draft_content_hash(expected)
        assert expected_hash != current_hash
        assert sorted(
            key
            for key in set(current) | set(expected)
            if current.get(key) != expected.get(key)
        ) == ["public_destination_copy"]
        revision = session.exec(
            select(GeneratedPageRevision)
            .where(GeneratedPageRevision.generated_page_id == generated.id)
            .order_by(
                GeneratedPageRevision.created_at.desc(),
                GeneratedPageRevision.id.desc(),
            )
        ).first()
        composition = session.exec(
            select(PageComposition).where(
                PageComposition.planned_page_id == planned.id
            )
        ).one()
        composition_history = current_composition_revision(session, composition)
        qa = session.exec(
            select(GeneratedPageQAResult).where(
                GeneratedPageQAResult.planned_page_id == planned.id,
                GeneratedPageQAResult.lifecycle_status == "current",
            )
        ).one()
        entry_id = f"public-copy-correction-{index:04d}"
        destination_item = expected["public_destination_copy"][0]
        intent = session.get(
            InternalLinkIntent,
            destination_item["source_record_id"],
        )
        target_planned = session.get(
            PlannedPage,
            destination_item["target_planned_page_id"],
        )
        target_generated = session.get(
            GeneratedPage,
            destination_item["target_generated_page_id"],
        )
        assert intent is not None
        assert target_planned is not None
        assert target_generated is not None
        corrections.append(
            {
                "entry_id": entry_id,
                "website_id": website.id,
                "site_plan_id": plan.id,
                "planned_page_id": planned.id,
                "generated_page_id": generated.id,
                "page_type": planned.page_type,
                "current_revision_id": (
                    composition_history.generated_page_revision_id
                ),
                "latest_page_revision_id": revision.id if revision else None,
                "current_content_hash": current_hash,
                "current_composition_id": composition.id,
                "current_composition_version": composition.composition_version,
                "current_composition_source_hash": composition.source_hash,
                "current_composition_history_revision_id": (
                    composition_history.id
                ),
                "current_qa_id": qa.id,
                "current_qa_result_hash": qa.result_hash,
                "expected_page_content_hash": expected_hash,
                "field_path": (
                    "draft_content.public_destination_copy"
                    "[source_kind=internal_link_intent,source_record_id="
                    f"{expected['public_destination_copy'][0]['source_record_id']}]"
                    ".description"
                ),
                "operation": "add_destination_derived_public_projection",
                "original_text": intent.purpose,
                "normalized_original_fingerprint": _fingerprint(
                    intent.purpose
                ),
                "replacement_text": expected["public_destination_copy"][0][
                    "description"
                ],
                "normalized_expected_fingerprint": _fingerprint(
                    expected["public_destination_copy"][0]["description"]
                ),
                "mirrored_generated_page_field": None,
                "finding_category": "related_link_description_defect",
                "finding_severity": "BLOCKER",
                "omission_decision": False,
                "source_owner": (
                    "app.services.public_destination_copy."
                    "build_public_destination_copy"
                ),
                "source_template_identity": "public-destination-copy-v1",
                "governed_facts_used": [
                    {
                        "fact": "target_planned_page.id",
                        "value": target_planned.id,
                    }
                ],
                "destination_identity": {
                    "website_id": target_planned.website_id,
                    "site_plan_id": target_planned.site_plan_id,
                    "planned_page_id": target_planned.id,
                    "generated_page_id": target_generated.id,
                    "page_type": target_planned.page_type,
                    "working_name": target_planned.working_name,
                    "slug": target_planned.intended_slug,
                    "service_id": target_planned.service_id,
                    "county_id": target_planned.county_id,
                    "city_id": target_planned.city_id,
                },
                "public_destination_item": deepcopy(destination_item),
                "provenance": {
                    "classification": (
                        "operator_governed_internal_intent_with_generator_owned_public_projection"
                    ),
                    "automatic_correction_authorized": True,
                    "operator_authored_content_changed": False,
                    "operator_internal_link_intent_preserved": True,
                },
                "rationale": "Project exact governed destination copy.",
                "reconciliation_status": (
                    "sealed_pending_disposable_clone_rehearsal"
                ),
                "customer_data": False,
            }
        )
        bindings.append(
            {
                "website_id": website.id,
                "site_plan_id": plan.id,
                "planned_page_id": planned.id,
                "generated_page_id": generated.id,
                "page_type": planned.page_type,
                "working_name": planned.working_name,
                "slug": planned.intended_slug,
                "page_identity": {
                    "planned_page_status": planned.planning_status,
                    "planned_page_parent_id": planned.parent_planned_page_id,
                    "service_id": planned.service_id,
                    "county_id": planned.county_id,
                    "city_id": planned.city_id,
                    "generated_page_type": generated.page_type,
                    "generated_page_slug": generated.page_slug,
                    "generated_page_title": generated.page_title,
                    "generated_page_status": generated.status,
                    "generated_page_generation_status": generated.generation_status,
                    "generated_page_qa_status": generated.qa_status,
                    "generated_page_meta_title": generated.meta_title,
                    "generated_page_meta_description": generated.meta_description,
                    "generated_page_h1": generated.h1,
                    "generated_page_content_body_sha256": hashlib.sha256(
                        (generated.content_body or "").encode("utf-8")
                    ).hexdigest(),
                    "generated_page_preserved_state_sha256": (
                        _generated_page_preserved_state_sha256(generated)
                    ),
                    "generated_page_updated_at": (
                        canonicalize_model_row_timestamps(
                            GeneratedPage,
                            {
                                "updated_at": generated.model_dump(
                                    mode="json"
                                )["updated_at"]
                            },
                        )["updated_at"]
                    ),
                },
                "current_revision": {
                    "bound_generated_page_revision_id": (
                        composition_history.generated_page_revision_id
                    ),
                    "latest_page_revision_id": revision.id if revision else None,
                    "latest_page_revision_hash_after": (
                        revision.draft_hash_after if revision else None
                    ),
                    "latest_page_revision_row_sha256": (
                        canonical_model_row_sha256(
                            GeneratedPageRevision,
                            revision.model_dump(mode="json"),
                        )
                        if revision
                        else None
                    ),
                    "binding_kind": "canonical_bound",
                    "content_hash": current_hash,
                    "generated_page_updated_at": (
                        canonicalize_model_row_timestamps(
                            GeneratedPage,
                            {
                                "updated_at": generated.model_dump(
                                    mode="json"
                                )["updated_at"]
                            },
                        )["updated_at"]
                    ),
                },
                "current_composition": {
                    "id": composition.id,
                    "version": composition.composition_version,
                    "source_hash": composition.source_hash,
                    "history_revision_id": composition_history.id,
                    "history_revision_hash": composition_history.revision_hash,
                    "history_revision_row_sha256": canonical_model_row_sha256(
                        PageCompositionRevision,
                        composition_history.model_dump(mode="json"),
                    ),
                    "content_hash": composition_history.content_hash,
                },
                "current_qa": {
                    "id": qa.id,
                    "result_hash": qa.result_hash,
                    "source_hash": qa.source_hash,
                    "ruleset_key": qa.qa_ruleset_key,
                    "ruleset_version": qa.qa_ruleset_version,
                    "ruleset_hash": qa.qa_ruleset_hash,
                    "readiness_status": qa.readiness_status,
                    "preserved_evidence_sha256": (
                        _qa_preserved_evidence_sha256(qa)
                    ),
                },
                "expected_new_content_hash": expected_hash,
                "expected_draft_content": expected,
                "expected_revision_required": True,
                "correction_entry_ids": [entry_id],
                "expected_changed_top_level_fields": [
                    "public_destination_copy"
                ],
                "expected_public_block_distinctness": {
                    "planned_page_id": planned.id,
                    "public_block_count": 1,
                    "inventory_sha256": canonical_json_sha256(
                        [{"path": "intro", "text": expected["intro"]}]
                    ),
                    "duplicate_group_count": 0,
                },
            }
        )
    intents = list(
        session.exec(
            select(InternalLinkIntent)
            .where(InternalLinkIntent.site_plan_id == plan.id)
            .order_by(InternalLinkIntent.id)
        ).all()
    )
    manifest = {
        "schema": PUBLIC_COPY_MANIFEST_SCHEMA,
        "database_row_timestamp_contract": (
            PUBLIC_COPY_DATABASE_ROW_TIMESTAMP_CONTRACT
        ),
        "status": "sealed_pending_disposable_clone_rehearsal",
        "customer_data": False,
        "external_request_count": 0,
        "database_read_count": 0,
        "database_write_count": 0,
        "authorization": {
            "original": {
                "path": PUBLIC_COPY_AUTHORIZATION_PATH,
                "size_bytes": PUBLIC_COPY_AUTHORIZATION_SIZE_BYTES,
                "line_count": PUBLIC_COPY_AUTHORIZATION_LINE_COUNT,
                "sha256": PUBLIC_COPY_AUTHORIZATION_SHA256,
                "historical_boundary_note": (
                    PUBLIC_COPY_AUTHORIZATION_ORIGINAL_0046_BOUNDARY
                ),
            },
            "resume_authorization": {
                "source": PUBLIC_COPY_RESUME_AUTHORIZATION_SOURCE,
                "canonical_encoding": (
                    PUBLIC_COPY_RESUME_AUTHORIZATION_CANONICAL_ENCODING
                ),
                "size_bytes": PUBLIC_COPY_RESUME_AUTHORIZATION_SIZE_BYTES,
                "line_count": PUBLIC_COPY_RESUME_AUTHORIZATION_LINE_COUNT,
                "sha256": PUBLIC_COPY_RESUME_AUTHORIZATION_SHA256,
                "active_atlas_revision": PUBLIC_COPY_ACTIVE_ATLAS_REVISION,
                "authority_effect": PUBLIC_COPY_RESUME_AUTHORIZATION_EFFECT,
            },
            "accepted_resume_preflight_seal": {
                "path": PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_PATH,
                "size_bytes": PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SIZE_BYTES,
                "sha256": PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SHA256,
                "schema": PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SCHEMA,
                "status": PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_STATUS,
                "cross_binding": {
                    "original_authorization_sha256": (
                        PUBLIC_COPY_AUTHORIZATION_SHA256
                    ),
                    "resume_authorization_sha256": (
                        PUBLIC_COPY_RESUME_AUTHORIZATION_SHA256
                    ),
                    "active_atlas_revision": PUBLIC_COPY_ACTIVE_ATLAS_REVISION,
                },
            },
        },
        "ruleset": {
            "schema": ruleset["schema"],
            "identity": ruleset["identity"],
            "canonical_payload_sha256": ruleset["seal"][
                "canonical_payload_sha256"
            ],
        },
        "scope": {
            "website_id": website.id,
            "site_plan_id": plan.id,
            "planned_page_count": len(planned_pages),
            "generated_page_count": len(generated_pages),
            "affected_page_count": len(planned_pages),
            "customer_data": False,
        },
        "governed_fact_snapshot": {
            "business": {
                key: business.model_dump(mode="json").get(key)
                for key in (
                    "id",
                    "brand_name",
                    "company_name",
                    "business_type",
                    "phone",
                    "email",
                    "website",
                    "main_city",
                    "state",
                    "license_number",
                    "certified_operator",
                    "description",
                )
            },
            "brand": {
                key: brand.model_dump(mode="json").get(key)
                for key in (
                    "id",
                    "business_id",
                    "brand_name",
                    "tagline",
                    "description",
                    "status",
                )
            },
            "website": {
                key: website.model_dump(mode="json").get(key)
                for key in (
                    "id",
                    "business_id",
                    "brand_id",
                    "website_name",
                    "domain",
                    "public_url",
                    "locale",
                )
            },
            "services_sha256": canonical_model_rows_sha256(
                Service,
                [
                    row.model_dump(mode="json")
                    for row in session.exec(select(Service).order_by(Service.id)).all()
                ]
            ),
            "counties_sha256": canonical_model_rows_sha256(
                County,
                [
                    row.model_dump(mode="json")
                    for row in session.exec(select(County).order_by(County.id)).all()
                ]
            ),
            "cities_sha256": canonical_model_rows_sha256(
                City,
                [
                    row.model_dump(mode="json")
                    for row in session.exec(select(City).order_by(City.id)).all()
                ]
            ),
            "knowledge_blocks_sha256": canonical_model_rows_sha256(
                KnowledgeBlock,
                [
                    row.model_dump(mode="json")
                    for row in session.exec(
                        select(KnowledgeBlock).order_by(KnowledgeBlock.id)
                    ).all()
                ]
            ),
            "locked_source_table_sha256": {
                table_name: canonical_model_rows_sha256(
                    model,
                    [
                        row.model_dump(mode="json")
                        for row in session.exec(
                            select(model).order_by(model.id)
                        ).all()
                    ]
                )
                for table_name, model in sorted(_LOCKED_SOURCE_MODELS.items())
            },
        },
        "immutable_history_snapshot": _immutable_history_snapshot(session),
        "execution_source_snapshot": _execution_source_snapshot(),
        "operator_intent_preservation": {
            "row_count": len(intents),
            "canonical_snapshot_sha256": canonical_model_rows_sha256(
                InternalLinkIntent,
                _intent_snapshot(intents),
            ),
            "mutation_allowed": False,
            "public_projection_field": "draft_content.public_destination_copy",
            "projection_item_count": len(intents),
            "projection_sha256": canonical_json_sha256(
                [
                    {
                        "source_planned_page_id": correction["planned_page_id"],
                        **correction["public_destination_item"],
                    }
                    for correction in corrections
                    if correction["operation"]
                    == "add_destination_derived_public_projection"
                ]
            ),
            "destination_target_type_counts": dict(
                sorted(
                    Counter(
                        correction["destination_identity"]["page_type"]
                        for correction in corrections
                        if correction["operation"]
                        == "add_destination_derived_public_projection"
                    ).items()
                )
            ),
            "source_page_type_item_counts": dict(
                sorted(
                    Counter(
                        correction["page_type"]
                        for correction in corrections
                        if correction["operation"]
                        == "add_destination_derived_public_projection"
                    ).items()
                )
            ),
        },
        "corrections": corrections,
        "page_bindings": bindings,
    }
    _reseal_fixture_manifest(manifest, ruleset)
    return manifest, ruleset


def _execution_source_snapshot() -> dict:
    root = Path(__file__).resolve().parents[2]
    paths = sorted(
        [
            candidate.relative_to(root).as_posix()
            for relative_root in ("backend/app", "backend/scripts")
            for candidate in root.joinpath(relative_root).rglob("*.py")
            if candidate.is_file()
        ]
        + ["frontend/src/components/performanceLocalV5LayoutContract.ts"]
    )
    modules = []
    for relative in paths:
        body = root.joinpath(*relative.split("/")).read_bytes()
        modules.append(
            {
                "path": relative,
                "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    return {
        "snapshot_role": "final_execution_source_after_production_freeze",
        "source_root_contract": {
            "root": "repository_root",
            "path_format": "repo_relative_posix",
            "allowed_paths": paths,
            "ordering": "lexicographic_path",
            "regular_files_only": True,
            "reject_symlinks": True,
            "hash_algorithm": "sha256-bytes",
        },
        "modules": modules,
        "canonical_module_list_sha256": canonical_json_sha256(modules),
        "git_baseline_commit": "150e022135e5564319b6b4c3e8ce6362be3f49db",
        "production_freeze_ack": "public-copy-production-source-frozen-v1",
        "performance_local_v5_layout_contract": {
            "path": (
                "frontend/src/components/performanceLocalV5LayoutContract.ts"
            ),
            "mutation_allowed": False,
            "must_equal_pre_repair_source_baseline": True,
        },
        "customer_data": False,
    }


def _intent_snapshot(rows: list[InternalLinkIntent]) -> list[dict]:
    fields = (
        "id",
        "website_id",
        "site_plan_id",
        "source_planned_page_id",
        "target_planned_page_id",
        "relationship_type",
        "purpose",
        "anchor_guidance",
        "rationale",
        "decision_version",
        "source_suggestion_key",
        "approval_state",
        "decided_by",
        "decided_at",
        "created_at",
        "updated_at",
    )
    return [
        {
            field: row.model_dump(mode="json").get(field)
            for field in fields
        }
        for row in rows
    ]


def _write_json(path: Path, value: dict) -> str:
    payload = (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode()
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _fingerprint(value: str | None) -> str:
    normalized = " ".join(
        unicodedata.normalize("NFKC", value or "").casefold().split()
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _rows(session: Session, model, *, ids: set[int] | None = None) -> list:
    values = list(session.exec(select(model).order_by(model.id)).all())
    if ids is not None:
        values = [value for value in values if value.id in ids]
    return values


def _dump(row) -> dict:
    return row.model_dump(mode="json")


def _generated_page_preserved_state_sha256(page: GeneratedPage) -> str:
    values = _dump(page)
    return canonical_model_row_sha256(
        GeneratedPage,
        {field: values.get(field) for field in _GENERATED_PAGE_PRESERVED_FIELDS}
    )


def _qa_preserved_evidence_sha256(row: GeneratedPageQAResult) -> str:
    values = canonicalize_model_row_timestamps(
        GeneratedPageQAResult,
        _dump(row),
    )
    values.pop("lifecycle_status", None)
    values.pop("updated_at", None)
    return canonical_json_sha256(values)


def _immutable_history_snapshot(session: Session) -> dict:
    generated_revisions = _rows(session, GeneratedPageRevision)
    composition_revisions = _rows(session, PageCompositionRevision)
    qa_rows = _rows(session, GeneratedPageQAResult)

    def base(model, rows: list) -> dict:
        return {
            "row_count": len(rows),
            "maximum_id": max(int(row.id or 0) for row in rows),
            "canonical_rows_sha256": canonical_model_rows_sha256(
                model,
                [_dump(row) for row in rows],
            ),
        }

    current_qa = [row for row in qa_rows if row.lifecycle_status == "current"]
    noncurrent_qa = [
        row for row in qa_rows if row.lifecycle_status != "current"
    ]
    qa_contract = base(GeneratedPageQAResult, qa_rows)
    qa_contract.update(
        {
            "current_row_ids": [int(row.id or 0) for row in current_qa],
            "canonical_noncurrent_rows_sha256": canonical_model_rows_sha256(
                GeneratedPageQAResult,
                [_dump(row) for row in noncurrent_qa],
            ),
            "canonical_current_preserved_rows_sha256": canonical_json_sha256(
                [
                    {
                        key: value
                        for key, value in canonicalize_model_row_timestamps(
                            GeneratedPageQAResult,
                            _dump(row),
                        ).items()
                        if key not in {"lifecycle_status", "updated_at"}
                    }
                    for row in current_qa
                ]
            ),
        }
    )
    return {
        "generated_page_revisions": base(
            GeneratedPageRevision,
            generated_revisions,
        ),
        "page_composition_revisions": base(
            PageCompositionRevision,
            composition_revisions,
        ),
        "generated_page_qa_results": qa_contract,
    }


def _database_fingerprint(session: Session) -> str:
    models = (
        GeneratedPage,
        GeneratedPageRevision,
        PageComposition,
        PageCompositionRevision,
        GeneratedPageQAResult,
        InternalLinkIntent,
    )
    return canonical_json_sha256(
        {
            model.__name__: [_dump(row) for row in _rows(session, model)]
            for model in models
        }
    )


def _eligibility_coverage_snapshot(session: Session) -> dict[str, dict[str, object]]:
    models = (
        DraftingEligibilityAssessment,
        DraftingEligibilityDisposition,
        PlanningRecord,
        PreDraftDistinctnessBrief,
        SupportingPageAuthorization,
        WebsiteCityCoverageDecision,
        WebsiteCountyCoverageDecision,
        WebsiteServiceCoverageDecision,
        WebsiteServiceCityCoverageDecision,
        WebsiteServiceCountyCoverageDecision,
    )
    snapshot: dict[str, dict[str, object]] = {}
    for model in models:
        rows = _rows(session, model)
        snapshot[model.__name__] = {
            "row_count": len(rows),
            "canonical_rows_sha256": canonical_model_rows_sha256(
                model,
                [row.model_dump(mode="json") for row in rows],
            ),
        }
    return snapshot


def test_all_before_batch_creates_one_exact_successor_per_page_and_preserves_history(
    scope: _Scope,
    tmp_path: Path,
) -> None:
    session = scope.session
    package = scope.load_package(tmp_path)
    page_ids = {page.id for page in scope.generated_pages if page.id is not None}
    old_revisions = {
        row.id: _dump(row)
        for row in _rows(session, GeneratedPageRevision)
        if row.generated_page_id in page_ids
    }
    old_composition_revisions = {
        row.id: _dump(row)
        for row in _rows(session, PageCompositionRevision)
        if row.generated_page_id in page_ids
    }
    old_qa = {
        row.id: _dump(row)
        for row in _rows(session, GeneratedPageQAResult)
        if row.generated_page_id in page_ids
    }
    old_intents = _intent_snapshot(_rows(session, InternalLinkIntent))

    result = reconcile_public_copy(
        session,
        package,
        actor="test:public-copy-reconciliation",
    )

    assert result.status == "applied"
    assert result.affected_page_count == 2
    assert result.appended_evidence_row_count == 6
    assert result.updated_head_row_count == 4
    assert result.superseded_qa_row_count == 2
    assert len(result.public_copy_audit_fingerprint) == 64
    assert len(result.page_results) == 2
    for item in result.page_results:
        assert item.new_generated_page_revision_id != item.old_generated_page_revision_id
        assert item.new_content_hash != item.old_content_hash
        assert item.new_composition_version == item.old_composition_version + 1
        assert item.new_composition_source_hash != item.old_composition_source_hash
        assert item.new_qa_result_id != item.old_qa_result_id
        assert len(item.new_qa_result_hash) == 64

    for generated in scope.generated_pages:
        revisions = list(
            session.exec(
                select(GeneratedPageRevision)
                .where(GeneratedPageRevision.generated_page_id == generated.id)
                .order_by(GeneratedPageRevision.id)
            ).all()
        )
        assert len(revisions) == 2
        assert revisions[-1].changed_fields == ["public_destination_copy"]
        assert revisions[-1].draft_content_after["public_destination_copy"]
        composition = session.exec(
            select(PageComposition).where(
                PageComposition.generated_page_id == generated.id
            )
        ).one()
        history = list(
            session.exec(
                select(PageCompositionRevision)
                .where(PageCompositionRevision.page_composition_id == composition.id)
                .order_by(PageCompositionRevision.composition_version)
            ).all()
        )
        assert [row.composition_version for row in history] == [1, 2]
        qa_rows = list(
            session.exec(
                select(GeneratedPageQAResult)
                .where(GeneratedPageQAResult.generated_page_id == generated.id)
                .order_by(GeneratedPageQAResult.id)
            ).all()
        )
        assert [row.lifecycle_status for row in qa_rows] == [
            "superseded",
            "current",
        ]

    current_revision_rows = {row.id: _dump(row) for row in _rows(session, GeneratedPageRevision)}
    current_composition_history = {
        row.id: _dump(row) for row in _rows(session, PageCompositionRevision)
    }
    current_qa_rows = {row.id: _dump(row) for row in _rows(session, GeneratedPageQAResult)}
    for row_id, payload in old_revisions.items():
        assert current_revision_rows[row_id] == payload
    for row_id, payload in old_composition_revisions.items():
        assert current_composition_history[row_id] == payload
    for row_id, payload in old_qa.items():
        observed = current_qa_rows[row_id]
        assert observed["lifecycle_status"] == "superseded"
        for field in (
            "result_hash",
            "source_hash",
            "qa_ruleset_hash",
            "page_composition_id",
            "composition_version",
            "composition_source_hash",
            "content_hash",
            "check_payload",
        ):
            assert observed[field] == payload[field]
    assert _intent_snapshot(_rows(session, InternalLinkIntent)) == old_intents


def test_exact_all_after_repeat_is_a_database_write_free_noop(
    scope: _Scope,
    tmp_path: Path,
) -> None:
    package = scope.load_package(tmp_path)
    first = reconcile_public_copy(
        scope.session,
        package,
        actor="test:idempotent-reconciliation",
    )
    assert first.status == "applied"
    before_repeat = _database_fingerprint(scope.session)

    repeated = reconcile_public_copy(
        scope.session,
        package,
        actor="test:idempotent-reconciliation",
    )

    assert repeated.status == "already_applied"
    assert repeated.page_results == ()
    assert repeated.appended_evidence_row_count == 0
    assert repeated.updated_head_row_count == 0
    assert repeated.superseded_qa_row_count == 0
    assert repeated.public_copy_audit_fingerprint == first.public_copy_audit_fingerprint
    assert _database_fingerprint(scope.session) == before_repeat


def test_commit_false_leaves_successful_unit_under_caller_transaction_control(
    scope: _Scope,
    tmp_path: Path,
) -> None:
    package = scope.load_package(tmp_path)
    baseline = _database_fingerprint(scope.session)

    result = reconcile_public_copy(
        scope.session,
        package,
        actor="test:caller-owned-transaction",
        commit=False,
    )

    assert result.status == "applied"
    assert _database_fingerprint(scope.session) != baseline
    scope.session.rollback()
    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline


def test_injected_failure_after_qa_rolls_back_every_row_kind(
    scope: _Scope,
    tmp_path: Path,
) -> None:
    package = scope.load_package(tmp_path)
    baseline = _database_fingerprint(scope.session)

    with pytest.raises(
        PublicCopyReconciliationInjectedFailure,
        match="after QA 1",
    ):
        reconcile_public_copy(
            scope.session,
            package,
            actor="test:injected-rollback",
            inject_failure_after_qa=1,
        )

    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline


def test_injected_failure_index_outside_complete_scope_rejects_without_writes(
    scope: _Scope,
    tmp_path: Path,
) -> None:
    package = scope.load_package(tmp_path)
    baseline = _database_fingerprint(scope.session)

    with pytest.raises(
        PublicCopyReconciliationError,
        match="exceeds the complete affected-page scope",
    ):
        reconcile_public_copy(
            scope.session,
            package,
            actor="test:invalid-injection-index",
            inject_failure_after_qa=3,
        )

    assert _database_fingerprint(scope.session) == baseline


def test_post_write_unexpected_history_append_rolls_back_complete_batch(
    scope: _Scope,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = scope.load_package(tmp_path)
    baseline = _database_fingerprint(scope.session)
    original_assertion = reconciliation_service._assert_operator_intents_exact
    assertion_count = 0

    def assert_then_append_unexpected_revision(
        session: Session,
        manifest: dict,
        *,
        rows: list[InternalLinkIntent] | None = None,
    ) -> None:
        nonlocal assertion_count
        original_assertion(session, manifest, rows=rows)
        assertion_count += 1
        if assertion_count == 1:
            return
        source = session.exec(
            select(GeneratedPageRevision).order_by(GeneratedPageRevision.id.desc())
        ).first()
        assert source is not None
        values = source.model_dump(mode="python")
        values.pop("id", None)
        # Keep the unexpected row outside every already-created composition's
        # temporal binding so only the post-write global-history gate detects it.
        values["created_at"] = datetime.now(UTC) + timedelta(days=1)
        session.add(GeneratedPageRevision(**values))
        session.flush()

    monkeypatch.setattr(
        reconciliation_service,
        "_assert_operator_intents_exact",
        assert_then_append_unexpected_revision,
    )
    with pytest.raises(
        PublicCopyReconciliationError,
        match="Immutable Generated Page, Page Composition, or QA history differs",
    ):
        reconcile_public_copy(
            scope.session,
            package,
            actor="test:unexpected-history-append",
        )

    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline


def test_complete_manifest_bound_drafting_evidence_finishes_before_first_writer(
    scope: _Scope,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = scope.load_package(tmp_path)
    expected_planned_ids = tuple(
        int(binding["planned_page_id"])
        for binding in package.manifest["page_bindings"]
    )
    original_preflight = (
        reconciliation_service._preflight_manifest_bound_drafting_evidence
    )
    original_writer = reconciliation_service.save_full_draft_revision
    complete_preflight = False
    writer_page_ids: list[int] = []
    authorities_by_planned: dict[
        int, ManifestBoundFullDraftRevisionAuthority
    ] = {}

    def tracked_preflight(*args, **kwargs):
        nonlocal complete_preflight
        result = original_preflight(*args, **kwargs)
        assert result.planned_page_ids == expected_planned_ids
        assert len(result.assessment_row_ids) == len(expected_planned_ids)
        assert result.assessment_status_counts == (
            ("insufficient_local_value", 1),
            ("semantic_duplication", 1),
        )
        assert result.locked_assessment_rows_sha256 == package.manifest[
            "governed_fact_snapshot"
        ]["locked_source_table_sha256"]["drafting_eligibility_assessments"]
        assert len(result.scoped_assessment_rows_sha256) == 64
        assert len(result.revision_authorities) == len(expected_planned_ids)
        authorities_by_planned.update(
            {
                authority.planned_page_id: authority
                for authority in result.revision_authorities
            }
        )
        complete_preflight = True
        return result

    def guarded_writer(session, page_id, candidate_draft, **kwargs):
        assert complete_preflight is True
        authority = kwargs.get("manifest_bound_authority")
        assert isinstance(authority, ManifestBoundFullDraftRevisionAuthority)
        assert authority == authorities_by_planned[authority.planned_page_id]
        assert authority.manifest_file_sha256 == package.manifest_file_sha256
        assert authority.generated_page_id == page_id
        assert authority.expected_new_hash == draft_content_hash(candidate_draft)
        writer_page_ids.append(page_id)
        return original_writer(session, page_id, candidate_draft, **kwargs)

    monkeypatch.setattr(
        reconciliation_service,
        "_preflight_manifest_bound_drafting_evidence",
        tracked_preflight,
    )
    monkeypatch.setattr(
        reconciliation_service,
        "save_full_draft_revision",
        guarded_writer,
    )

    result = reconcile_public_copy(
        scope.session,
        package,
        actor="test:eligibility-preflight-order",
    )

    assert result.status == "applied"
    assert writer_page_ids == [
        int(binding["generated_page_id"])
        for binding in package.manifest["page_bindings"]
    ]


def test_preserved_noneligible_assessments_do_not_veto_exact_reconciliation(
    scope: _Scope,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = scope.load_package(tmp_path)
    before_evidence = _eligibility_coverage_snapshot(scope.session)
    eligibility_gate_calls: list[int] = []

    def reject_current_eligibility(*args, **kwargs):
        eligibility_gate_calls.append(1)
        raise DraftingEligibilityError(
            "Ordinary current/effective eligibility must not be consulted."
        )

    monkeypatch.setattr(
        page_editor_service,
        "require_effective_drafting_eligibility",
        reject_current_eligibility,
    )
    result = reconcile_public_copy(
        scope.session,
        package,
        actor="test:preserved-noneligible-evidence",
    )

    scope.session.expire_all()
    assert result.status == "applied"
    assert eligibility_gate_calls == []
    assert _eligibility_coverage_snapshot(scope.session) == before_evidence


def test_manifest_bound_preflight_accepts_exact_preserved_55_4_6_status_mix(
) -> None:
    manifest_sha256 = "f" * 64
    website_id = 1
    site_plan_id = 2
    planned_statuses = (
        [
            (planned_id, "insufficient_local_value")
            for planned_id in range(1, 56)
        ]
        + [(planned_id, "eligible") for planned_id in range(79, 84)]
        + [
            (planned_id, "semantic_duplication")
            for planned_id in range(84, 88)
        ]
        + [(88, "eligible")]
    )
    assessment_rows = [
        DraftingEligibilityAssessment(
            id=assessment_id,
            website_id=website_id,
            site_plan_id=site_plan_id,
            planned_page_id=planned_id,
            status=status,
            algorithm_version="drafting-eligibility-v3",
            coverage_binding={"planned_page_id": planned_id},
            expected_inventory_binding={"planned_page_id": planned_id},
            planning_record_binding={"planned_page_id": planned_id},
            distinctness_brief_binding={"planned_page_id": planned_id},
            approved_source_identities=[],
            evidence={"preserved": True},
            local_value_findings=[],
            semantic_findings=[],
            reasons=["Preserved Backup 0.59 assessment status."],
            assessed_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
        for assessment_id, (planned_id, status) in enumerate(
            planned_statuses,
            start=1,
        )
    ]
    bindings = [
        {
            "planned_page_id": planned_id,
            "generated_page_id": assessment_id + 1000,
            "current_revision": {"content_hash": f"{assessment_id:064x}"},
            "expected_new_content_hash": f"{assessment_id + 1000:064x}",
            "page_identity": {
                "planned_page_status": "generated",
                "generated_page_status": "approved",
            },
            "expected_changed_top_level_fields": ["intro"],
        }
        for assessment_id, (planned_id, _status) in enumerate(
            planned_statuses,
            start=1,
        )
    ]
    locked_hash = canonical_model_rows_sha256(
        DraftingEligibilityAssessment,
        [row.model_dump(mode="json") for row in assessment_rows],
    )
    manifest = {
        "governed_fact_snapshot": {
            "locked_source_table_sha256": {
                "drafting_eligibility_assessments": locked_hash,
            }
        }
    }
    reason = f"{PUBLIC_COPY_RECONCILIATION_REASON_PREFIX}{manifest_sha256}"

    result = reconciliation_service._preflight_manifest_bound_drafting_evidence(
        manifest=manifest,
        manifest_file_sha256=manifest_sha256,
        actor="test:backup-0.59-status-mix",
        reason=reason,
        website_id=website_id,
        site_plan_id=site_plan_id,
        bindings=bindings,
        assessment_rows=assessment_rows,
    )

    assert result.planned_page_ids == tuple(
        planned_id for planned_id, _status in planned_statuses
    )
    assert result.assessment_row_ids == tuple(range(1, 66))
    assert result.assessment_status_counts == (
        ("eligible", 6),
        ("insufficient_local_value", 55),
        ("semantic_duplication", 4),
    )
    assert result.scoped_assessment_rows_sha256 == locked_hash
    assert result.locked_assessment_rows_sha256 == locked_hash
    assert len(result.revision_authorities) == 65
    assert {
        authority.manifest_file_sha256
        for authority in result.revision_authorities
    } == {manifest_sha256}


def _governed_orange_navigation_set(
    *,
    navigation_set_id: int = 3,
    set_type: str = "footer",
):
    item = reconciliation_service._GovernedNavigationItemBinding(
        navigation_item_id=22,
        target_planned_page_id=84,
        target_generated_page_id=74,
        target_slug="drywood-termite-tenting-orange-county-fl",
        label="Orange County",
        parent_navigation_item_id=18,
        position=0,
        status="active",
        identity_terms=("Orange County",),
    )
    return reconciliation_service._GovernedNavigationSetBinding(
        navigation_set_id=navigation_set_id,
        set_type=set_type,
        label=f"{set_type.title()} Navigation",
        items=(item,),
    )


def _orange_navigation_composition(
    *,
    navigation_set_id: int = 3,
    component_key: str = "footer_navigation",
):
    return {
        "generated_components": [
            {
                "instance_key": component_key,
                "component_key": component_key,
                "input_bindings": {"navigation_set_id": navigation_set_id},
            }
        ],
        "operator_decisions": [],
        "effective_components": [
            {
                "component_key": component_key,
                "input_bindings": {"navigation_set_id": navigation_set_id},
                "resolved_data": {
                    "label": "Footer Navigation",
                    "items": [
                        {
                            "navigation_item_id": 22,
                            "target_planned_page_id": 84,
                            "target_generated_page_id": 74,
                            "label": "Orange County",
                            "slug": "drywood-termite-tenting-orange-county-fl",
                            "parent_navigation_item_id": 18,
                            "position": 0,
                            "status": "active",
                        }
                    ]
                },
            }
        ]
    }


def test_navigation_identity_allowance_binds_the_exact_resolved_target_path():
    governed = _governed_orange_navigation_set()
    composition = _orange_navigation_composition()

    assert reconciliation_service._navigation_identity_terms_by_composition_path(
        composition=composition,
        navigation_identity_bindings=(governed,),
    ) == {
        "composition.effective_components[0].resolved_data.items[0].label": (
            "Orange County",
        )
    }


@pytest.mark.parametrize(
    "navigation_item_id,target_planned_page_id",
    [(999, 84), (22, 85)],
)
def test_navigation_identity_allowance_rejects_unknown_or_mismatched_binding(
    navigation_item_id: int,
    target_planned_page_id: int,
):
    governed = _governed_orange_navigation_set()
    composition = _orange_navigation_composition()
    item = composition["effective_components"][0]["resolved_data"]["items"][0]
    item["navigation_item_id"] = navigation_item_id
    item["target_planned_page_id"] = target_planned_page_id

    with pytest.raises(
        PublicCopyReconciliationError,
        match="Navigation component",
    ):
        reconciliation_service._navigation_identity_terms_by_composition_path(
            composition=composition,
            navigation_identity_bindings=(governed,),
        )


@pytest.mark.parametrize(
    "mutation",
    ["altered_label", "swapped_component_type"],
)
def test_navigation_identity_allowance_rejects_label_or_set_type_tamper(
    mutation: str,
):
    governed = _governed_orange_navigation_set()
    composition = _orange_navigation_composition()
    if mutation == "altered_label":
        composition["effective_components"][0]["resolved_data"]["items"][0][
            "label"
        ] = "Seminole County"
    else:
        composition["effective_components"][0][
            "component_key"
        ] = "primary_navigation"

    with pytest.raises(PublicCopyReconciliationError, match="Navigation component"):
        reconciliation_service._navigation_identity_terms_by_composition_path(
            composition=composition,
            navigation_identity_bindings=(governed,),
        )


def test_navigation_identity_allowance_preserves_an_exact_empty_utility_set():
    governed = reconciliation_service._GovernedNavigationSetBinding(
        navigation_set_id=2,
        set_type="utility",
        label="Utility Navigation",
        items=(),
    )
    composition = {
        "generated_components": [
            {
                "instance_key": "utility_navigation",
                "component_key": "utility_navigation",
                "input_bindings": {"navigation_set_id": 2},
            }
        ],
        "operator_decisions": [],
        "effective_components": [
            {
                "component_key": "utility_navigation",
                "input_bindings": {"navigation_set_id": 2},
                "resolved_data": {
                    "label": "Utility Navigation",
                    "items": [],
                },
            }
        ]
    }

    assert reconciliation_service._navigation_identity_terms_by_composition_path(
        composition=composition,
        navigation_identity_bindings=(governed,),
    ) == {}


def test_navigation_identity_allowance_accepts_exact_suppressed_utility_set():
    governed = reconciliation_service._GovernedNavigationSetBinding(
        navigation_set_id=2,
        set_type="utility",
        label="Utility Navigation",
        items=(),
    )
    composition = {
        "generated_components": [
            {
                "instance_key": "utility_navigation",
                "component_key": "utility_navigation",
                "input_bindings": {"navigation_set_id": 2},
            }
        ],
        "operator_decisions": [
            {
                "instance_key": "utility_navigation",
                "action": "suppress",
                "rationale": "Use primary navigation only on this page.",
            }
        ],
        "effective_components": [],
    }

    assert reconciliation_service._navigation_identity_terms_by_composition_path(
        composition=composition,
        navigation_identity_bindings=(governed,),
    ) == {}


def test_navigation_identity_allowance_rejects_missing_unsuppressed_set():
    governed = reconciliation_service._GovernedNavigationSetBinding(
        navigation_set_id=2,
        set_type="utility",
        label="Utility Navigation",
        items=(),
    )
    composition = {
        "generated_components": [
            {
                "instance_key": "utility_navigation",
                "component_key": "utility_navigation",
                "input_bindings": {"navigation_set_id": 2},
            }
        ],
        "operator_decisions": [],
        "effective_components": [],
    }

    with pytest.raises(
        PublicCopyReconciliationError,
        match="navigation-set inventory differs",
    ):
        reconciliation_service._navigation_identity_terms_by_composition_path(
            composition=composition,
            navigation_identity_bindings=(governed,),
        )


def test_ordinary_full_draft_writer_still_rejects_ineligible_page(
    scope: _Scope,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = scope.load_package(tmp_path)
    binding = package.manifest["page_bindings"][0]
    baseline = _database_fingerprint(scope.session)

    def reject_ordinary_revision(*args, **kwargs):
        raise DraftingEligibilityError(
            "full-draft revision blocked by insufficient_local_value."
        )

    monkeypatch.setattr(
        page_editor_service,
        "require_effective_drafting_eligibility",
        reject_ordinary_revision,
    )

    with pytest.raises(HTTPException) as exc_info:
        save_full_draft_revision(
            scope.session,
            binding["generated_page_id"],
            binding["expected_draft_content"],
            expected_current_hash=binding["current_revision"]["content_hash"],
            created_by="test:ordinary-ineligible",
            reason="Ordinary full-draft revision.",
            allowed_page_statuses=frozenset(
                {binding["page_identity"]["generated_page_status"]}
            ),
            expected_changed_fields=binding[
                "expected_changed_top_level_fields"
            ],
            commit=False,
        )

    assert exc_info.value.status_code == 409
    assert "blocked by insufficient_local_value" in str(exc_info.value.detail)
    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline


def test_full_draft_writer_rejects_every_tampered_authority_dimension(
    scope: _Scope,
    tmp_path: Path,
) -> None:
    package = scope.load_package(tmp_path)
    binding = package.manifest["page_bindings"][0]
    actor = "test:tampered-authority"
    reason = f"{PUBLIC_COPY_RECONCILIATION_REASON_PREFIX}{package.manifest_file_sha256}"
    authority = ManifestBoundFullDraftRevisionAuthority(
        manifest_file_sha256=package.manifest_file_sha256,
        website_id=int(binding["website_id"]),
        site_plan_id=int(binding["site_plan_id"]),
        planned_page_id=int(binding["planned_page_id"]),
        generated_page_id=int(binding["generated_page_id"]),
        expected_current_hash=binding["current_revision"]["content_hash"],
        expected_new_hash=binding["expected_new_content_hash"],
        actor=actor,
        reason=reason,
        planned_page_status=binding["page_identity"]["planned_page_status"],
        generated_page_status=binding["page_identity"][
            "generated_page_status"
        ],
        expected_changed_fields=tuple(
            binding["expected_changed_top_level_fields"]
        ),
    )
    baseline = _database_fingerprint(scope.session)
    mutations = (
        {"manifest_file_sha256": ""},
        {"manifest_file_sha256": "e" * 64},
        {"website_id": authority.website_id + 1},
        {"site_plan_id": authority.site_plan_id + 1},
        {"planned_page_id": authority.planned_page_id + 1},
        {"generated_page_id": authority.generated_page_id + 1},
        {"expected_current_hash": "0" * 64},
        {"expected_new_hash": "0" * 64},
        {"actor": f"{actor}:wrong"},
        {"reason": f"{reason}:wrong"},
        {"planned_page_status": "wrong"},
        {"generated_page_status": "wrong"},
        {"expected_changed_fields": ("intro",)},
    )

    for mutation in mutations:
        with pytest.raises(HTTPException) as exc_info:
            save_full_draft_revision(
                scope.session,
                binding["generated_page_id"],
                binding["expected_draft_content"],
                expected_current_hash=binding["current_revision"][
                    "content_hash"
                ],
                created_by=actor,
                reason=reason,
                allowed_page_statuses=frozenset(
                    {binding["page_identity"]["generated_page_status"]}
                ),
                expected_changed_fields=binding[
                    "expected_changed_top_level_fields"
                ],
                manifest_bound_authority=replace(authority, **mutation),
                commit=False,
            )
        assert exc_info.value.status_code == 409
        assert "authority does not match" in str(exc_info.value.detail)
        scope.session.rollback()

    for untyped_authority in (True, object()):
        with pytest.raises(HTTPException) as exc_info:
            save_full_draft_revision(
                scope.session,
                binding["generated_page_id"],
                binding["expected_draft_content"],
                expected_current_hash=binding["current_revision"][
                    "content_hash"
                ],
                created_by=actor,
                reason=reason,
                allowed_page_statuses=frozenset(
                    {binding["page_identity"]["generated_page_status"]}
                ),
                expected_changed_fields=binding[
                    "expected_changed_top_level_fields"
                ],
                manifest_bound_authority=untyped_authority,  # type: ignore[arg-type]
                commit=False,
            )
        assert exc_info.value.status_code == 409
        assert "authority does not match" in str(exc_info.value.detail)
        scope.session.rollback()

    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline


def test_manifest_bound_writer_rejects_per_page_commit(
    scope: _Scope,
    tmp_path: Path,
) -> None:
    package = scope.load_package(tmp_path)
    binding = package.manifest["page_bindings"][0]
    actor = "test:per-page-commit"
    reason = f"{PUBLIC_COPY_RECONCILIATION_REASON_PREFIX}{package.manifest_file_sha256}"
    authority = ManifestBoundFullDraftRevisionAuthority(
        manifest_file_sha256=package.manifest_file_sha256,
        website_id=int(binding["website_id"]),
        site_plan_id=int(binding["site_plan_id"]),
        planned_page_id=int(binding["planned_page_id"]),
        generated_page_id=int(binding["generated_page_id"]),
        expected_current_hash=binding["current_revision"]["content_hash"],
        expected_new_hash=binding["expected_new_content_hash"],
        actor=actor,
        reason=reason,
        planned_page_status=binding["page_identity"]["planned_page_status"],
        generated_page_status=binding["page_identity"][
            "generated_page_status"
        ],
        expected_changed_fields=tuple(
            binding["expected_changed_top_level_fields"]
        ),
    )
    baseline = _database_fingerprint(scope.session)

    with pytest.raises(HTTPException) as exc_info:
        save_full_draft_revision(
            scope.session,
            binding["generated_page_id"],
            binding["expected_draft_content"],
            expected_current_hash=binding["current_revision"]["content_hash"],
            created_by=actor,
            reason=reason,
            allowed_page_statuses=frozenset(
                {binding["page_identity"]["generated_page_status"]}
            ),
            expected_changed_fields=binding[
                "expected_changed_top_level_fields"
            ],
            manifest_bound_authority=authority,
            commit=True,
        )

    assert exc_info.value.status_code == 409
    assert "authority does not match" in str(exc_info.value.detail)
    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline


@pytest.mark.parametrize(
    "drift",
    ("tampered", "missing", "out_of_scope"),
)
def test_assessment_drift_rejects_complete_batch_before_first_writer(
    scope: _Scope,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    package = scope.load_package(tmp_path)
    rows = list(
        scope.session.exec(
            select(DraftingEligibilityAssessment).order_by(
                DraftingEligibilityAssessment.id
            )
        ).all()
    )
    assert len(rows) == 2
    if drift == "tampered":
        rows[0].status = "eligible"
        rows[0].reasons = ["Tampered after the manifest was sealed."]
        scope.session.add(rows[0])
    elif drift == "missing":
        scope.session.delete(rows[-1])
    elif drift == "out_of_scope":
        rows[0].website_id = (scope.website.id or 0) + 10_000
        scope.session.add(rows[0])
    else:  # pragma: no cover - fixed parametrization above
        raise AssertionError(drift)
    scope.session.commit()
    before_evidence = _eligibility_coverage_snapshot(scope.session)
    writer_page_ids: list[int] = []
    original_writer = reconciliation_service.save_full_draft_revision

    def observed_writer(session, page_id, candidate_draft, **kwargs):
        writer_page_ids.append(page_id)
        return original_writer(session, page_id, candidate_draft, **kwargs)

    monkeypatch.setattr(
        reconciliation_service,
        "save_full_draft_revision",
        observed_writer,
    )

    with pytest.raises(
        PublicCopyReconciliationError,
        match="locked transaction source table differs",
    ):
        reconcile_public_copy(
            scope.session,
            package,
            actor=f"test:assessment-{drift}",
        )

    scope.session.expire_all()
    assert writer_page_ids == []
    assert _eligibility_coverage_snapshot(scope.session) == before_evidence


def test_complete_generated_page_inventory_rejects_an_extra_page_before_writes(
    scope: _Scope,
    tmp_path: Path,
) -> None:
    package = scope.load_package(tmp_path)
    payload = scope.generated_pages[0].model_dump(mode="python")
    payload.pop("id", None)
    payload["page_slug"] = "unexpected-extra-page"
    payload["page_title"] = "Unexpected Extra Page"
    scope.session.add(GeneratedPage(**payload))
    scope.session.commit()
    baseline = _database_fingerprint(scope.session)

    with pytest.raises(
        PublicCopyReconciliationError,
        match="Complete Website Generated Page inventory",
    ):
        reconcile_public_copy(
            scope.session,
            package,
            actor="test:extra-generated-page",
        )

    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline


def test_locked_governed_source_drift_rejects_before_any_write(
    scope: _Scope,
    tmp_path: Path,
) -> None:
    package = scope.load_package(tmp_path)
    brand = scope.session.get(Brand, scope.website.brand_id)
    assert brand is not None
    brand.tagline = "Changed after the correction manifest was sealed."
    scope.session.add(brand)
    scope.session.commit()
    baseline = _database_fingerprint(scope.session)

    with pytest.raises(
        PublicCopyReconciliationError,
        match="Locked Business/Brand/Website facts differ",
    ):
        reconcile_public_copy(
            scope.session,
            package,
            actor="test:governed-source-drift",
        )

    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline


def test_all_after_rejects_rendered_qa_and_history_tamper(
    scope: _Scope,
    tmp_path: Path,
) -> None:
    package = scope.load_package(tmp_path)
    applied = reconcile_public_copy(
        scope.session,
        package,
        actor="test:after-tamper",
    )
    assert applied.status == "applied"
    baseline = _database_fingerprint(scope.session)
    generated_id = package.manifest["page_bindings"][0]["generated_page_id"]

    page = scope.session.get(GeneratedPage, generated_id)
    assert page is not None
    page.content_body = f"{page.content_body}\nTampered public body."
    scope.session.add(page)
    with pytest.raises(
        PublicCopyReconciliationError,
        match="rendered content body is not canonical",
    ):
        reconcile_public_copy(
            scope.session,
            package,
            actor="test:after-tamper",
        )
    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline

    current_qa = scope.session.exec(
        select(GeneratedPageQAResult).where(
            GeneratedPageQAResult.generated_page_id == generated_id,
            GeneratedPageQAResult.lifecycle_status == "current",
        )
    ).one()
    current_qa.result_hash = "f" * 64
    scope.session.add(current_qa)
    with pytest.raises(
        PublicCopyReconciliationError,
        match="durable QA is not exact-current",
    ):
        reconcile_public_copy(
            scope.session,
            package,
            actor="test:after-tamper",
        )
    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline

    page = scope.session.get(GeneratedPage, generated_id)
    assert page is not None
    page.qa_status = "not_run"
    scope.session.add(page)
    with pytest.raises(
        PublicCopyReconciliationError,
        match="durable QA is not exact-current",
    ):
        reconcile_public_copy(
            scope.session,
            package,
            actor="test:after-tamper",
        )
    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline

    prior_qa_id = package.manifest["page_bindings"][0]["current_qa"]["id"]
    prior_qa = scope.session.get(GeneratedPageQAResult, prior_qa_id)
    assert prior_qa is not None
    prior_qa.updated_at = prior_qa.updated_at + timedelta(seconds=1)
    scope.session.add(prior_qa)
    with pytest.raises(
        PublicCopyReconciliationError,
        match="lifecycle timestamp is not bound to its exact successor",
    ):
        reconcile_public_copy(
            scope.session,
            package,
            actor="test:after-tamper",
        )
    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline

    current_qa = scope.session.exec(
        select(GeneratedPageQAResult).where(
            GeneratedPageQAResult.generated_page_id == generated_id,
            GeneratedPageQAResult.lifecycle_status == "current",
        )
    ).one()
    current_qa.created_at = current_qa.created_at + timedelta(seconds=1)
    scope.session.add(current_qa)
    with pytest.raises(
        PublicCopyReconciliationError,
        match="after-state composition/QA binding is not exact",
    ):
        reconcile_public_copy(
            scope.session,
            package,
            actor="test:after-tamper",
        )
    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline

    latest_revision = scope.session.exec(
        select(GeneratedPageRevision)
        .where(GeneratedPageRevision.generated_page_id == generated_id)
        .order_by(GeneratedPageRevision.created_at.desc(), GeneratedPageRevision.id.desc())
    ).first()
    assert latest_revision is not None
    prior_draft = deepcopy(latest_revision.draft_content_before)
    prior_draft["intro"] = f"{prior_draft['intro']} Tampered predecessor payload."
    latest_revision.draft_content_before = prior_draft
    scope.session.add(latest_revision)
    with pytest.raises(
        PublicCopyReconciliationError,
        match="after-state revision evidence is not exact",
    ):
        reconcile_public_copy(
            scope.session,
            package,
            actor="test:after-tamper",
        )
    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline

    prior_revision_id = package.manifest["page_bindings"][0][
        "current_composition"
    ]["history_revision_id"]
    prior_revision = scope.session.get(PageCompositionRevision, prior_revision_id)
    assert prior_revision is not None
    prior_revision.recorded_by = "tampered:actor"
    scope.session.add(prior_revision)
    with pytest.raises(
        PublicCopyReconciliationError,
        match="immutable|history|hash|preserved",
    ):
        reconcile_public_copy(
            scope.session,
            package,
            actor="test:after-tamper",
        )
    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline


@pytest.mark.parametrize(
    ("drift", "match"),
    [
        ("revision", "latest revision row differs"),
        ("hash", "neither the sealed before nor after state"),
        (
            "page_type",
            "locked transaction source table differs|identity differs|scope/type/slug/status identity changed",
        ),
        (
            "website",
            "Complete Website Generated Page inventory|scope/type/slug/status identity changed",
        ),
        ("destination", "Operator InternalLinkIntent"),
        ("provenance", "Operator InternalLinkIntent"),
    ],
)
def test_complete_preflight_rejects_stale_identity_without_partial_writes(
    scope: _Scope,
    tmp_path: Path,
    drift: str,
    match: str,
) -> None:
    session = scope.session
    if drift == "revision":
        package = scope.load_package(tmp_path)
        revision_id = package.manifest["page_bindings"][1][
            "current_revision"
        ]["latest_page_revision_id"]
        revision = session.get(GeneratedPageRevision, revision_id)
        assert revision is not None
        revision.created_by = "changed-after-seal"
        session.add(revision)
        session.commit()
    elif drift == "hash":
        package = scope.load_package(tmp_path)
        page = scope.generated_pages[1]
        draft = deepcopy(page.draft_content or {})
        draft["intro"] += " Changed after sealing."
        page.draft_content = draft
        session.add(page)
        session.commit()
    elif drift == "page_type":
        package = scope.load_package(tmp_path)
        page = scope.planned_pages[1]
        page.page_type = "about"
        session.add(page)
        session.commit()
    elif drift == "website":
        package = scope.load_package(tmp_path)
        page = scope.generated_pages[1]
        page.website_id = 999999
        session.add(page)
        session.commit()
    elif drift == "destination":
        package = scope.load_package(tmp_path)
        intent = _rows(session, InternalLinkIntent)[1]
        intent.target_planned_page_id = intent.source_planned_page_id
        session.add(intent)
        session.commit()
    elif drift == "provenance":
        package = scope.load_package(tmp_path)
        intent = _rows(session, InternalLinkIntent)[1]
        intent.decided_by = "Different Operator"
        session.add(intent)
        session.commit()
    else:  # pragma: no cover - protected by the fixed parametrization above
        raise AssertionError(f"Unknown drift fixture: {drift}")
    baseline = _database_fingerprint(session)

    with pytest.raises(PublicCopyReconciliationError, match=match):
        reconcile_public_copy(
            session,
            package,
            actor="test:stale-preflight",
        )

    session.expire_all()
    assert _database_fingerprint(session) == baseline


def test_valid_mixed_before_after_scope_is_rejected_as_partial_replay(
    scope: _Scope,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = scope.load_package(tmp_path)
    session = scope.session
    actor = "test:mixed-state"
    binding = package.manifest["page_bindings"][0]
    reason = f"{PUBLIC_COPY_RECONCILIATION_REASON_PREFIX}{package.manifest_file_sha256}"
    save_full_draft_revision(
        session,
        binding["generated_page_id"],
        binding["expected_draft_content"],
        expected_current_hash=binding["current_revision"]["content_hash"],
        created_by=actor,
        reason=reason,
        allowed_page_statuses=frozenset(
            {binding["page_identity"]["generated_page_status"]}
        ),
        expected_changed_fields=binding["expected_changed_top_level_fields"],
        commit=False,
    )
    strict_destination_reader = (
        page_composition_service.require_public_destination_copy
    )
    monkeypatch.setattr(
        page_composition_service,
        "require_public_destination_copy",
        lambda session, plan, planned, generated, **kwargs: (
            build_public_destination_copy(
                session,
                plan,
                planned,
                generated,
                draft_content=generated.draft_content or {},
            )
        ),
    )
    refresh = refresh_site_plan_compositions(
        session, scope.plan.id or 0, commit=False
    )
    monkeypatch.setattr(
        page_composition_service,
        "require_public_destination_copy",
        strict_destination_reader,
    )
    assert refresh.refreshed == 1 and refresh.unchanged == 1
    save_page_qa(session, binding["generated_page_id"], commit=False)
    session.commit()
    mixed_fingerprint = _database_fingerprint(session)

    with pytest.raises(PublicCopyReconciliationError, match="mixed before/after"):
        reconcile_public_copy(session, package, actor=actor)

    session.expire_all()
    assert _database_fingerprint(session) == mixed_fingerprint


def test_post_load_manifest_path_tamper_is_rejected_before_any_write(
    scope: _Scope,
    tmp_path: Path,
) -> None:
    package = scope.load_package(tmp_path)
    package.manifest["corrections"][0]["field_path"] = (
        "draft_content.internal_notes"
    )
    baseline = _database_fingerprint(scope.session)

    with pytest.raises(PublicCopyReconciliationError, match="manifest|seal|path"):
        reconcile_public_copy(
            scope.session,
            package,
            actor="test:post-load-tamper",
        )

    scope.session.expire_all()
    assert _database_fingerprint(scope.session) == baseline
