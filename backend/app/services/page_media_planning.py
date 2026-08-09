from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlmodel import Session, select

from app.core.config import get_settings
from app.models import (
    Business,
    GeneratedPage,
    ImageMetadata,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    PlannedPageMediaRequirement,
    PlanningRecord,
    SemanticComponentDefinition,
    SitePlan,
    Website,
    WebsiteMediaPlanningRecord,
)
from app.schemas.page_media_planning import (
    PageMediaAssetRead,
    PageMediaAssignmentRead,
    PageMediaAssignmentRequest,
    PageMediaDiagnostic,
    PageMediaPlacementDecisionRequest,
    PageMediaPlacementWorkspace,
    PageMediaPlannedPageIdentity,
    PageMediaPlanningRecordRead,
    PageMediaPlanningSummary,
    PageMediaWorkspace,
    PlannedPageMediaRequirementRead,
)
from app.services.media_uploads import (
    inspect_managed_original,
    is_safe_image_filename,
    managed_original_contains_gps,
    remove_stored_media_files,
    store_uploaded_image,
)
from app.services.website_media_safety import (
    is_image_metadata_excluded,
)


ALGORITHM_VERSION = "page-media-planning-v1"
PLACEMENT_CONTRACT_VERSION = 1
REQUIREMENT_STATES = {"required", "advisory", "excluded", "deferred"}
GOVERNANCE_STATUSES = {
    "legacy_unverified",
    "pending_review",
    "approved",
    "rejected",
    "retired",
}
PROVENANCE_TYPES = {
    "company_original",
    "commissioned",
    "licensed",
    "stock",
    "generated",
    "public_domain",
}
RIGHTS_STATUSES = {"owned", "commissioned", "licensed", "public_domain"}
ACQUISITION_SOURCES = {
    "company_photograph",
    "commissioned",
    "licensed",
    "stock",
    "generated",
    "operator_upload",
    "public_domain",
}
ACQUISITION_PROVENANCE: dict[str, set[str]] = {
    "company_photograph": {"company_original"},
    "commissioned": {"commissioned"},
    "licensed": {"licensed"},
    "stock": {"stock", "licensed"},
    "generated": {"generated"},
    "operator_upload": set(PROVENANCE_TYPES),
    "public_domain": {"public_domain"},
}
PROVENANCE_RIGHTS: dict[str, set[str]] = {
    "company_original": {"owned"},
    "commissioned": {"commissioned", "owned"},
    "licensed": {"licensed"},
    "stock": {"licensed"},
    "generated": {"owned", "licensed"},
    "public_domain": {"public_domain"},
}
ORIENTATIONS = {"any", "landscape", "portrait", "square"}
DISPLAY_PRESETS = {
    "hero_desktop",
    "hero_mobile",
    "card_thumbnail",
    "square",
    "original",
}


def _placement(
    key: str,
    component: str,
    state: str,
    purpose: str,
    outcome: str,
    subject: str,
    *,
    orientation: str = "landscape",
    aspect_ratio: str = "16:9",
    minimum_width: int = 1200,
    minimum_height: int = 675,
    crop: str = "Preserve the meaningful subject while adapting to responsive containers.",
    focal: str = "Record an operator-reviewed focal point when the subject is not centered.",
    responsive: str = "Use approved responsive derivatives without stretching or destructive cropping.",
    accessibility: str = "informative",
    caption: str | None = None,
    source_constraints: list[str] | None = None,
    reuse: str = "Reuse only when the same approved subject and customer purpose remain accurate.",
    replacement: str = "Replacement requires an approved governed asset and explicit operator decision.",
) -> dict[str, Any]:
    return {
        "placement_key": key,
        "component_or_section": component,
        "requirement_state": state,
        "purpose": purpose,
        "customer_outcome": outcome,
        "intended_subject": subject,
        "orientation": orientation,
        "aspect_ratio": aspect_ratio,
        "minimum_width": minimum_width,
        "minimum_height": minimum_height,
        "crop_intent": crop,
        "focal_point_intent": focal,
        "responsive_behavior": responsive,
        "accessibility_intent": accessibility,
        "caption_intent": caption,
        "approved_source_constraints": source_constraints
        or ["approved_company_media", "licensed_media", "approved_generated_media"],
        "permitted_reuse_policy": reuse,
        "replacement_policy": replacement,
        "contract_version": PLACEMENT_CONTRACT_VERSION,
    }


PAGE_TYPE_MEDIA_CONTRACTS: dict[str, list[dict[str, Any]]] = {
    "home": [
        _placement(
            "home-hero",
            "hero",
            "required",
            "Establish the Website's primary service and identity visually.",
            "Understand the business's principal value and next action immediately.",
            "An approved business-appropriate service or company image.",
        ),
        _placement(
            "home-trust",
            "trust_license",
            "advisory",
            "Support trust and credibility without replacing approved factual evidence.",
            "Recognize credible, relevant evidence about the business.",
            "Approved team, equipment, process, or trust-supporting company imagery.",
        ),
        _placement(
            "home-service-overview",
            "related_page_links",
            "advisory",
            "Help visitors understand the principal service offering.",
            "Connect the business's service to a recognizable customer need.",
            "An approved service process, outcome-neutral illustration, or legitimate company photograph.",
        ),
    ],
    "about": [
        _placement(
            "about-company",
            "hero",
            "required",
            "Introduce the real company and reinforce its identity.",
            "Understand who stands behind the service.",
            "An approved company, team, facility, equipment, or operator image.",
        ),
        _placement(
            "about-trust",
            "trust_license",
            "advisory",
            "Support approved experience, licensing, or service-quality information.",
            "Gain confidence from relevant and truthful visual evidence.",
            "Approved trust-supporting company media.",
        ),
    ],
    "contact": [
        _placement(
            "contact-context",
            "contact_pathways",
            "advisory",
            "Provide useful context beside contact and estimate pathways.",
            "Feel confident that the contact path belongs to the correct business.",
            "Approved company, office, vehicle, or service-context media.",
        ),
    ],
    "faq": [
        _placement(
            "faq-guidance",
            "faq",
            "advisory",
            "Clarify a frequently asked service or preparation concept when imagery is useful.",
            "Understand an answer more easily without decorative clutter.",
            "Approved explanatory, process, preparation, or company media.",
        ),
    ],
    "service": [
        _placement(
            "service-hero",
            "hero",
            "required",
            "Identify the approved service and establish relevance.",
            "Understand which service the page explains.",
            "Approved service-specific company, process, equipment, or illustrative media.",
        ),
        _placement(
            "service-process",
            "service_summary",
            "advisory",
            "Explain an approved part of the service process.",
            "Know what to expect without unsupported promises.",
            "Approved process, equipment, preparation, or guidance media.",
        ),
        _placement(
            "service-guidance",
            "content_section",
            "advisory",
            "Support practical preparation or customer guidance.",
            "Take an informed next step.",
            "Approved preparation, guidance, or supporting service media.",
        ),
    ],
    "service_county": [
        _placement(
            "service-county-hero",
            "hero",
            "required",
            "Connect the approved service with its legitimate county service area.",
            "Understand the service and geographic scope without fabricated local proof.",
            "Approved service media or authentic, authorized service-area imagery.",
        ),
        _placement(
            "service-county-property",
            "content_section",
            "advisory",
            "Support useful property or service-area context.",
            "Recognize relevant property or preparation considerations.",
            "Authentic authorized company media, licensed generic property media, or approved illustration.",
        ),
        _placement(
            "service-county-guidance",
            "service_summary",
            "advisory",
            "Explain service or preparation details relevant to the page.",
            "Understand the process and next action.",
            "Approved service-process or preparation media.",
        ),
    ],
    "city_service": [
        _placement(
            "city-service-hero",
            "hero",
            "required",
            "Connect an approved service with a legitimate city coverage page.",
            "Understand the service-area relationship without fabricated local evidence.",
            "Approved service media or authentic, authorized local company photography.",
        ),
        _placement(
            "city-service-process",
            "service_summary",
            "advisory",
            "Explain approved service or preparation details.",
            "Know what to expect and how to proceed.",
            "Approved process, preparation, equipment, or guidance media.",
        ),
    ],
    "informational": [
        _placement(
            "informational-hero",
            "hero",
            "advisory",
            "Orient the reader to the approved informational topic.",
            "Recognize the topic and its relevance.",
            "Approved explanatory or topic-specific media.",
        ),
        _placement(
            "informational-support",
            "content_section",
            "advisory",
            "Improve understanding of a substantive section.",
            "Understand the guidance more clearly.",
            "Approved explanatory, process, or reference media.",
        ),
    ],
}


class PageMediaPlanningError(ValueError):
    pass


def read_page_media_workspace(session: Session, plan_id: int) -> PageMediaWorkspace:
    plan, website = _plan_context(session, plan_id)
    pages = list(
        session.exec(
            select(PlannedPage)
            .where(PlannedPage.site_plan_id == plan.id)
            .order_by(PlannedPage.id)
        ).all()
    )
    planning_record = _current_planning_record(session, plan.id or plan_id)
    _require_planning_record_scope(planning_record, plan, website)
    current_source_hash = _hash(_planning_source_snapshot(session, plan, pages))
    planning_current = bool(
        planning_record and planning_record.source_hash == current_source_hash
    )
    suggestions = (
        planning_record.generated_media_suggestions if planning_record else []
    )
    suggestions_by_page: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for suggestion in suggestions:
        page_id = suggestion.get("planned_page_id")
        placement_key = suggestion.get("placement_key")
        if isinstance(page_id, int) and isinstance(placement_key, str):
            suggestions_by_page[page_id][placement_key] = suggestion

    requirements = list(
        session.exec(
            select(PlannedPageMediaRequirement)
            .where(PlannedPageMediaRequirement.site_plan_id == plan.id)
            .order_by(
                PlannedPageMediaRequirement.planned_page_id,
                PlannedPageMediaRequirement.placement_key,
                PlannedPageMediaRequirement.version,
            )
        ).all()
    )
    history_by_key: dict[tuple[int, str], list[PlannedPageMediaRequirement]] = defaultdict(list)
    for requirement in requirements:
        scoped_page = next(
            (page for page in pages if page.id == requirement.planned_page_id),
            None,
        )
        scope_errors = _requirement_scope_errors(
            session,
            requirement,
            scoped_page,
            plan,
            website,
        )
        if scope_errors:
            raise PageMediaPlanningError(" ".join(scope_errors))
        history_by_key[(requirement.planned_page_id, requirement.placement_key)].append(requirement)
    effective_by_key = {
        key: max(values, key=lambda value: value.version)
        for key, values in history_by_key.items()
        if values
    }
    assets = list(
        session.exec(
            select(ImageMetadata)
            .where(ImageMetadata.website_id == website.id)
            .order_by(ImageMetadata.media_key, ImageMetadata.media_version)
        ).all()
    )
    assets = [
        asset for asset in assets if not is_image_metadata_excluded(website, asset)
    ]
    assignments = list(
        session.exec(
            select(PageImageAssignment)
            .where(PageImageAssignment.generated_page_id.in_(
                [page.generated_page_id for page in pages if page.generated_page_id]
            ))
            .order_by(PageImageAssignment.id)
        ).all()
    ) if any(page.generated_page_id for page in pages) else []
    assignments_by_requirement: dict[int, list[PageImageAssignment]] = defaultdict(list)
    legacy_by_page: dict[int, list[PageImageAssignment]] = defaultdict(list)
    excluded_legacy_by_page: dict[int, list[PageImageAssignment]] = defaultdict(list)
    page_by_generated = {
        page.generated_page_id: page for page in pages if page.generated_page_id
    }
    for assignment in assignments:
        if assignment.media_requirement_id:
            assignments_by_requirement[assignment.media_requirement_id].append(assignment)
        else:
            page = page_by_generated.get(assignment.generated_page_id)
            image = session.get(ImageMetadata, assignment.image_metadata_id)
            if page and page.id:
                target = (
                    excluded_legacy_by_page
                    if is_image_metadata_excluded(website, image)
                    else legacy_by_page
                )
                target[page.id].append(assignment)
    known_asset_ids = {asset.id for asset in assets if asset.id is not None}
    for image_id in sorted({assignment.image_metadata_id for assignment in assignments}):
        if image_id in known_asset_ids:
            continue
        legacy_asset = session.get(ImageMetadata, image_id)
        if (
            legacy_asset
            and legacy_asset.website_id is None
            and legacy_asset.business_id == website.business_id
            and not is_image_metadata_excluded(website, legacy_asset)
        ):
            assets.append(legacy_asset)

    compositions = {
        row.planned_page_id: row
        for row in session.exec(
            select(PageComposition).where(PageComposition.site_plan_id == plan.id)
        ).all()
    }
    diagnostics: list[PageMediaDiagnostic] = []
    placements: list[PageMediaPlacementWorkspace] = []
    ready_pages: set[int] = set()
    page_type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    required_count = advisory_count = excluded_count = deferred_count = 0
    approved_assignment_count = missing_required = incomplete_governance = incompatible_count = 0
    stale_compositions: set[int] = set()
    pages_with_plan: set[int] = set()

    for page in pages:
        page_id = page.id or 0
        identity = _page_identity(page)
        excluded_legacy_blocker = (
            "Active legacy assignment references media excluded by the Website-scoped "
            "external-media safety policy."
            if excluded_legacy_by_page.get(page_id)
            else None
        )
        if excluded_legacy_blocker:
            incompatible_count += len(excluded_legacy_by_page[page_id])
        try:
            exact_component_keys = _exact_page_composition_component_keys(
                session,
                page,
                plan,
                website,
            )
            exact_target_error = None
        except PageMediaPlanningError as exc:
            exact_component_keys = set()
            exact_target_error = str(exc)
        page_suggestions = suggestions_by_page.get(page_id, {})
        page_keys = set(page_suggestions) | {
            key for candidate_page_id, key in effective_by_key if candidate_page_id == page_id
        }
        page_ready = planning_current and bool(page_suggestions)
        if not page_keys:
            placements.append(
                PageMediaPlacementWorkspace(
                    placement_id=None,
                    planned_page=identity,
                    suggestion=None,
                    effective_requirement=None,
                    requirement_history=[],
                    active_assignment=None,
                    legacy_assignments=[_assignment_read(item) for item in legacy_by_page.get(page_id, [])],
                    compatible_asset_ids=[],
                    blocking_reasons=[
                        "No current Page Media plan exists for this Planned Page.",
                        *([excluded_legacy_blocker] if excluded_legacy_blocker else []),
                    ],
                    composition_status=_composition_status(compositions.get(page_id)),
                    readiness="missing_plan",
                )
            )
            diagnostics.append(PageMediaDiagnostic(
                category="media_plan",
                status="needs_attention",
                message="Planned Page has no current media-plan suggestions.",
                planned_page_id=page_id,
            ))
            page_type_counts[page.page_type]["pages"] += 1
            page_type_counts[page.page_type]["without_plan"] += 1
            continue

        if planning_current:
            pages_with_plan.add(page_id)
        page_type_counts[page.page_type]["pages"] += 1
        page_type_counts[page.page_type]["with_plan"] += 1
        for placement_key in sorted(page_keys):
            suggestion = page_suggestions.get(placement_key)
            history = history_by_key.get((page_id, placement_key), [])
            effective = effective_by_key.get((page_id, placement_key))
            blocking: list[str] = []
            if excluded_legacy_blocker:
                blocking.append(excluded_legacy_blocker)
            active_assignment = None
            compatible_ids: list[int] = []
            readiness = "awaiting_operator_decision"
            if not planning_current:
                blocking.append("Page Media planning suggestions are stale.")
                readiness = "stale"
                page_ready = False
            if effective is None:
                blocking.append("Atlas suggestion has no operator-approved placement decision.")
                page_ready = False
            elif planning_record and not _requirement_matches_current_planning(
                session,
                effective,
                planning_record,
            ):
                blocking.append("Operator placement decision is bound to a stale planning version.")
                readiness = "stale"
                page_ready = False
            elif effective.lifecycle_status != "active":
                blocking.append("Placement decision is not active.")
                page_ready = False
            else:
                state = effective.requirement_state
                if state == "required":
                    required_count += 1
                elif state == "advisory":
                    advisory_count += 1
                elif state == "excluded":
                    excluded_count += 1
                elif state == "deferred":
                    deferred_count += 1
                if state in {"excluded", "deferred"}:
                    readiness = state
                else:
                    if effective.component_or_section not in exact_component_keys:
                        blocking.append(
                            exact_target_error
                            or (
                                "Media placement target is missing from the exact "
                                "effective Planned Page composition."
                            )
                        )
                        readiness = "stale"
                    else:
                        for asset in assets:
                            if not _asset_compatibility_errors(session, asset, effective, page, website):
                                compatible_ids.append(asset.id or 0)
                        active = [
                            item
                            for item in assignments_by_requirement.get(effective.id or 0, [])
                            if item.status == "active"
                        ]
                        if len(active) > 1:
                            blocking.append("Placement has multiple active governed assignments.")
                            incompatible_count += 1
                        elif active:
                            active_assignment = active[0]
                            asset = session.get(ImageMetadata, active_assignment.image_metadata_id)
                            errors = (
                                _assignment_binding_errors(
                                    active_assignment,
                                    asset,
                                    effective,
                                    page,
                                    website,
                                )
                                + _asset_compatibility_errors(
                                    session,
                                    asset,
                                    effective,
                                    page,
                                    website,
                                )
                                if asset
                                else ["Assigned governed media is missing."]
                            )
                            if errors:
                                blocking.extend(errors)
                                incompatible_count += 1
                            else:
                                approved_assignment_count += 1
                                readiness = "ready"
                        elif state == "required":
                            blocking.append("Required media placement has no approved assignment.")
                            missing_required += 1
                            readiness = "awaiting_assignment"
                        else:
                            readiness = "advisory_unfilled"
            if blocking:
                page_ready = False
                diagnostics.extend(
                    PageMediaDiagnostic(
                        category="placement",
                        status="needs_attention",
                        message=message,
                        planned_page_id=page_id,
                        placement_key=placement_key,
                        record_id=effective.id if effective else None,
                    )
                    for message in blocking
                )
            composition_status = _composition_status(compositions.get(page_id))
            if composition_status == "stale":
                stale_compositions.add(page_id)
            placements.append(PageMediaPlacementWorkspace(
                placement_id=effective.id if effective else None,
                planned_page=identity,
                suggestion=suggestion,
                effective_requirement=_requirement_read(effective) if effective else None,
                requirement_history=[_requirement_read(item) for item in history],
                active_assignment=_assignment_read(active_assignment) if active_assignment else None,
                legacy_assignments=[_assignment_read(item) for item in legacy_by_page.get(page_id, [])],
                compatible_asset_ids=compatible_ids,
                blocking_reasons=blocking,
                composition_status=composition_status,
                readiness=readiness,
            ))
        if page_ready:
            ready_pages.add(page_id)
            page_type_counts[page.page_type]["ready"] += 1

    for asset in assets:
        if not _governance_complete(asset):
            incomplete_governance += 1
    summary = PageMediaPlanningSummary(
        planned_pages=len(pages),
        pages_with_current_plan=len(pages_with_plan),
        pages_without_plan=len(pages) - len(pages_with_plan),
        suggested_placements=len(suggestions),
        required_placements=required_count,
        advisory_placements=advisory_count,
        excluded_placements=excluded_count,
        deferred_placements=deferred_count,
        approved_assignments=approved_assignment_count,
        missing_required_media=missing_required,
        incomplete_governance=incomplete_governance,
        incompatible_assignments=incompatible_count,
        stale_compositions=len(stale_compositions),
        pages_media_ready=len(ready_pages),
        page_type_coverage={key: dict(value) for key, value in sorted(page_type_counts.items())},
    )
    return PageMediaWorkspace(
        website_id=website.id or 0,
        business_id=website.business_id,
        site_plan_id=plan.id or plan_id,
        site_plan_version=plan.version,
        planning_record=_planning_record_read(planning_record) if planning_record else None,
        placements=placements,
        assets=[_asset_read(item) for item in assets],
        diagnostics=diagnostics,
        summary=summary,
        ready=(
            planning_current
            and len(ready_pages) == len(pages)
            and not diagnostics
            and not stale_compositions
        ),
        evaluated_at=datetime.now(UTC),
    )


def refresh_site_plan_media_suggestions(
    session: Session,
    plan_id: int,
    *,
    commit: bool = True,
) -> PageMediaWorkspace:
    plan, website = _plan_context(session, plan_id)
    pages = list(session.exec(
        select(PlannedPage).where(PlannedPage.site_plan_id == plan.id).order_by(PlannedPage.id)
    ).all())
    suggestions, snapshot, source_hash = _prepare_site_plan_media_suggestions(
        session,
        plan,
        website,
        pages,
    )
    current = _current_planning_record(session, plan.id or plan_id)
    _require_planning_record_scope(current, plan, website)
    if current and current.source_hash == source_hash and current.generated_media_suggestions == suggestions:
        return read_page_media_workspace(session, plan_id)
    version = (current.version + 1) if current else 1
    record = WebsiteMediaPlanningRecord(
        website_id=website.id or 0,
        business_id=website.business_id,
        site_plan_id=plan.id or plan_id,
        version=version,
        algorithm_version=ALGORITHM_VERSION,
        generated_media_suggestions=suggestions,
        source_snapshot=snapshot,
        source_hash=source_hash,
        generated_at=datetime.now(UTC),
        replaces_record_id=current.id if current else None,
    )
    session.add(record)
    for page in pages:
        page_id = page.id or 0
        if (
            current is None
            or _planning_page_binding(current, page_id)
            != _planning_page_binding(record, page_id)
        ):
            _mark_composition_stale(session, page_id)
    if commit:
        session.commit()
    else:
        session.flush()
    return read_page_media_workspace(session, plan_id)


def _prepare_site_plan_media_suggestions(
    session: Session,
    plan: SitePlan,
    website: Website,
    pages: list[PlannedPage],
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """Build and validate the immutable suggestion manifest without mutating state."""
    active_component_keys = {
        row.component_key
        for row in session.exec(
            select(SemanticComponentDefinition).where(
                SemanticComponentDefinition.status == "active"
            )
        ).all()
    }
    suggestions: list[dict[str, Any]] = []
    for page in pages:
        contract_key = _page_contract_key(page)
        contracts = PAGE_TYPE_MEDIA_CONTRACTS.get(contract_key)
        if contracts is None:
            continue
        composition_component_keys = _exact_page_composition_component_keys(
            session,
            page,
            plan,
            website,
        )
        for contract in contracts:
            if contract["component_or_section"] not in active_component_keys:
                raise PageMediaPlanningError(
                    "Page Media contract references a missing active semantic component: "
                    f"{contract['component_or_section']}."
                )
            _require_exact_page_composition_target(
                page,
                contract["component_or_section"],
                composition_component_keys,
            )
            value = dict(contract)
            value.update({
                "suggestion_key": f"{contract_key}:v{PLACEMENT_CONTRACT_VERSION}:{contract['placement_key']}",
                "website_id": website.id,
                "business_id": website.business_id,
                "site_plan_id": plan.id,
                "planned_page_id": page.id,
                "page_type": page.page_type,
                "contract_page_type": contract_key,
                "compatible_page_types": [page.page_type],
            })
            suggestions.append(value)
    snapshot = _planning_source_snapshot(session, plan, pages)
    return suggestions, snapshot, _hash(snapshot)


def decide_media_placement(
    session: Session,
    plan_id: int,
    payload: PageMediaPlacementDecisionRequest,
    *,
    commit: bool = True,
    return_workspace: bool = True,
) -> PageMediaWorkspace | None:
    plan, website = _plan_context(session, plan_id)
    if payload.site_plan_id != plan.id or payload.website_id != website.id:
        raise PageMediaPlanningError("Placement decision crosses the selected Website or Site Plan boundary.")
    page = session.get(PlannedPage, payload.planned_page_id)
    if not page or page.website_id != website.id or page.site_plan_id != plan.id:
        raise PageMediaPlanningError("Planned Page does not belong to the selected Website and Site Plan.")
    placement_key = _identifier(payload.placement_key, "Placement key")
    payload = payload.model_copy(update={"placement_key": placement_key})
    planning_record = _current_planning_record(session, plan.id or plan_id)
    _require_planning_record_scope(planning_record, plan, website)
    if not planning_record:
        raise PageMediaPlanningError("Refresh Atlas media-plan suggestions before recording an operator decision.")
    current_hash = _hash(_planning_source_snapshot(
        session,
        plan,
        list(session.exec(select(PlannedPage).where(PlannedPage.site_plan_id == plan.id).order_by(PlannedPage.id)).all()),
    ))
    if planning_record.source_hash != current_hash:
        raise PageMediaPlanningError("Page Media planning suggestions are stale and must be refreshed.")
    if payload.expected_planning_version != planning_record.version:
        raise PageMediaPlanningError("Page Media planning version changed; reload before deciding.")
    suggestion = next((
        value
        for value in planning_record.generated_media_suggestions
        if value.get("planned_page_id") == page.id
        and value.get("placement_key") == payload.placement_key
        and (
            payload.source_suggestion_key is None
            or value.get("suggestion_key") == payload.source_suggestion_key
        )
    ), None)
    if payload.source_suggestion_key and suggestion is None:
        raise PageMediaPlanningError("Source suggestion is missing or belongs to another Planned Page.")
    values = _requirement_values(payload, suggestion, page)
    values["business_id"] = website.business_id
    values["planning_record_id"] = planning_record.id
    component = session.exec(
        select(SemanticComponentDefinition).where(
            SemanticComponentDefinition.component_key
            == values["component_or_section"],
            SemanticComponentDefinition.status == "active",
        ).order_by(
            SemanticComponentDefinition.contract_version.desc(),
            SemanticComponentDefinition.id.desc(),
        )
    ).first()
    if component is None:
        raise PageMediaPlanningError(
            "Placement decision references a missing active semantic component."
        )
    if (
        "all" not in component.compatible_page_types
        and page.page_type not in component.compatible_page_types
    ):
        raise PageMediaPlanningError(
            "Placement semantic component is incompatible with this Planned Page type."
        )
    _require_exact_page_composition_target(
        page,
        values["component_or_section"],
        _exact_page_composition_component_keys(session, page, plan, website),
    )
    history = list(session.exec(
        select(PlannedPageMediaRequirement).where(
            PlannedPageMediaRequirement.planned_page_id == page.id,
            PlannedPageMediaRequirement.placement_key == payload.placement_key,
        ).order_by(PlannedPageMediaRequirement.version)
    ).all())
    current = history[-1] if history else None
    comparison = {
        key: values[key]
        for key in values
        if key
        not in {
            "version",
            "replaces_requirement_id",
            "decided_at",
            "lifecycle_status",
            "planning_record_id",
        }
    }
    if current:
        current_values = current.model_dump()
        if (
            all(
                current_values.get(key) == value
                for key, value in comparison.items()
            )
            and current.lifecycle_status == "active"
            and _requirement_matches_current_planning(
                session,
                current,
                planning_record,
            )
        ):
            return (
                read_page_media_workspace(session, plan_id)
                if return_workspace
                else None
            )
        current.lifecycle_status = "superseded"
        current.updated_at = datetime.now(UTC)
        session.add(current)
        active_assignments = list(
            session.exec(
                select(PageImageAssignment).where(
                    PageImageAssignment.media_requirement_id == current.id,
                    PageImageAssignment.status == "active",
                )
            ).all()
        )
        if len(active_assignments) > 1:
            raise PageMediaPlanningError(
                "Superseded media placement has multiple active governed assignments."
            )
        for assignment in active_assignments:
            assignment.status = "replaced"
            assignment.replaced_by = _required_text(
                payload.decided_by,
                "Decision operator",
            )
            assignment.replacement_rationale = (
                "Placement decision superseded: "
                + _required_text(payload.rationale, "Decision rationale")
            )
            assignment.replaced_at = datetime.now(UTC)
            assignment.updated_at = datetime.now(UTC)
            session.add(assignment)
    requirement = PlannedPageMediaRequirement(
        **values,
        version=(current.version + 1 if current else 1),
        replaces_requirement_id=current.id if current else None,
        lifecycle_status="active",
        decided_at=datetime.now(UTC),
    )
    session.add(requirement)
    _mark_composition_stale(session, page.id or 0)
    if commit:
        session.commit()
    else:
        session.flush()
    return (
        read_page_media_workspace(session, plan_id)
        if return_workspace
        else None
    )


async def create_governed_page_media_asset(
    session: Session,
    *,
    file: UploadFile,
    website_id: int,
    business_id: int,
    media_key: str,
    image_title: str,
    reviewed_alt_text: str | None,
    acquisition_source: str,
    creator_source_identity: str,
    provenance_type: str,
    provenance_notes: str,
    rights_status: str,
    rights_holder: str,
    rights_notes: str,
    approved_usage: list[str],
    prohibited_usage: list[str],
    permitted_placement_keys: list[str],
    accessibility_intent: str,
    created_by: str,
    replaces_image_metadata_id: int | None = None,
) -> ImageMetadata:
    website = session.get(Website, website_id)
    if not website or website.business_id != business_id:
        raise PageMediaPlanningError("Website does not belong to the selected Business.")
    key = _identifier(media_key, "Media key")
    acquisition = acquisition_source.strip().lower()
    provenance = provenance_type.strip().lower()
    rights = rights_status.strip().lower()
    if acquisition not in ACQUISITION_SOURCES:
        raise PageMediaPlanningError("Unsupported media acquisition source.")
    if provenance not in PROVENANCE_TYPES or rights not in RIGHTS_STATUSES:
        raise PageMediaPlanningError("Approved provenance and rights classifications are required.")
    if not _source_governance_valid(acquisition, provenance, rights):
        raise PageMediaPlanningError(
            "Media acquisition source, provenance classification, and rights status are inconsistent."
        )
    required_text = {
        "image title": image_title,
        "creator or source identity": creator_source_identity,
        "provenance notes": provenance_notes,
        "rights holder": rights_holder,
        "rights notes": rights_notes,
        "accessibility intent": accessibility_intent,
        "operator identity": created_by,
    }
    for label, value in required_text.items():
        if not value.strip():
            raise PageMediaPlanningError(f"Page media {label} is required.")
    usage = _clean_list(approved_usage)
    prohibited = _clean_list(prohibited_usage)
    placements = _clean_list(permitted_placement_keys)
    if not usage or not prohibited or not placements:
        raise PageMediaPlanningError("Approved usage, prohibited usage, and permitted placement keys are required.")
    if set(usage) & set(prohibited):
        raise PageMediaPlanningError("Approved and prohibited usage cannot overlap.")
    replacement = None
    version = 1
    if replaces_image_metadata_id is not None:
        replacement = session.get(ImageMetadata, replaces_image_metadata_id)
        if (
            not replacement
            or replacement.website_id != website_id
            or replacement.business_id != business_id
            or replacement.media_key != key
            or replacement.media_version is None
        ):
            raise PageMediaPlanningError("Replacement must reference the same governed Website media key.")
        version = replacement.media_version + 1
    latest = session.exec(
        select(ImageMetadata).where(
            ImageMetadata.website_id == website_id,
            ImageMetadata.media_key == key,
        ).order_by(ImageMetadata.media_version.desc())
    ).first()
    if latest and replacement is None:
        raise PageMediaPlanningError("Media key already exists; create an explicit replacement version.")
    if latest and latest.media_version and version <= latest.media_version:
        raise PageMediaPlanningError("Replacement media version is not current.")

    settings = get_settings()
    stored = await store_uploaded_image(file, settings)
    try:
        gps_present = managed_original_contains_gps(stored.stored_filename, settings)
    except Exception:
        remove_stored_media_files(stored, settings)
        raise
    row = ImageMetadata(
        business_id=business_id,
        website_id=website_id,
        media_key=key,
        media_version=version,
        file_name=stored.stored_filename,
        image_title=image_title.strip(),
        alt_text=reviewed_alt_text.strip() if reviewed_alt_text else None,
        reviewed_alt_text=reviewed_alt_text.strip() if reviewed_alt_text else None,
        asset_url=stored.asset_url,
        optimized_url=stored.optimized_url,
        thumbnail_url=stored.thumbnail_url,
        original_filename=stored.original_filename,
        stored_filename=stored.stored_filename,
        managed_storage_path=f"originals/{stored.stored_filename}",
        mime_type=stored.mime_type,
        file_size=stored.file_size,
        width=stored.width,
        height=stored.height,
        checksum_sha256=stored.checksum_sha256,
        acquisition_source=acquisition,
        creator_source_identity=creator_source_identity.strip(),
        provenance_type=provenance,
        provenance_notes=provenance_notes.strip(),
        rights_status=rights,
        rights_holder=rights_holder.strip(),
        rights_notes=rights_notes.strip(),
        approved_usage=usage,
        prohibited_usage=prohibited,
        permitted_placement_keys=placements,
        accessibility_intent=accessibility_intent.strip(),
        governance_status="pending_review",
        review_status="pending_review",
        approval_version=None,
        replaces_image_metadata_id=replaces_image_metadata_id,
        gps_metadata_status="present_unverified" if gps_present else "absent",
        gps_metadata={},
        exif_status="present_unverified" if gps_present else "optimized_copy_stripped",
        created_by=created_by.strip(),
    )
    try:
        session.add(row)
        session.commit()
        session.refresh(row)
    except Exception:
        session.rollback()
        remove_stored_media_files(stored, settings)
        raise
    return row


def approve_page_media_asset(
    session: Session,
    image_id: int,
    *,
    expected_website_id: int,
    expected_business_id: int,
    approved_by: str,
    expected_media_version: int,
) -> ImageMetadata:
    asset = _asset(session, image_id)
    if (
        asset.website_id != expected_website_id
        or asset.business_id != expected_business_id
    ):
        raise PageMediaPlanningError(
            "Page-media approval crosses the selected Website or Business boundary."
        )
    if asset.media_version != expected_media_version:
        raise PageMediaPlanningError("Page media version changed before approval.")
    website = session.get(Website, expected_website_id)
    if not website:
        raise PageMediaPlanningError("Page-media approval Website is missing.")
    if is_image_metadata_excluded(website, asset):
        raise PageMediaPlanningError(
            "Page media is excluded by the Website-scoped external-media safety policy."
        )
    if asset.governance_status == "approved":
        if asset.approved_by != approved_by.strip():
            raise PageMediaPlanningError(
                "Page media is already approved by another recorded operator."
            )
        _validate_asset_governance(asset, require_approved=True)
        _revalidate_managed_asset(asset)
        if _is_asset_superseded(session, asset):
            raise PageMediaPlanningError(
                "A superseded page-media version cannot be re-approved."
            )
        return asset
    if asset.governance_status != "pending_review":
        raise PageMediaPlanningError("Only pending-review governed page media can be approved.")
    _validate_asset_governance(asset, require_approved=False)
    _revalidate_managed_asset(asset)
    if _is_asset_superseded(session, asset):
        raise PageMediaPlanningError("A superseded page-media version cannot be approved.")
    asset.governance_status = "approved"
    asset.review_status = "reviewed"
    asset.approval_version = (asset.approval_version or 0) + 1
    asset.approved_by = _required_text(approved_by, "Approval operator")
    asset.approved_at = datetime.now(UTC)
    asset.updated_at = datetime.now(UTC)
    superseded_ids = [
        row.id
        for row in session.exec(
            select(ImageMetadata).where(
                ImageMetadata.website_id == asset.website_id,
                ImageMetadata.media_key == asset.media_key,
                ImageMetadata.media_version < asset.media_version,
            )
        ).all()
        if row.id is not None
    ]
    if superseded_ids:
        assignments = session.exec(
            select(PageImageAssignment).where(
                PageImageAssignment.image_metadata_id.in_(superseded_ids),
                PageImageAssignment.status == "active",
                PageImageAssignment.media_requirement_id.is_not(None),
            )
        ).all()
        for assignment in assignments:
            if assignment.planned_page_id:
                _mark_composition_stale(session, assignment.planned_page_id)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def retire_page_media_asset(
    session: Session,
    image_id: int,
    *,
    expected_website_id: int,
    expected_business_id: int,
    retired_by: str,
    rationale: str,
    expected_media_version: int,
) -> ImageMetadata:
    asset = _asset(session, image_id)
    if (
        asset.website_id != expected_website_id
        or asset.business_id != expected_business_id
    ):
        raise PageMediaPlanningError(
            "Page-media retirement crosses the selected Website or Business boundary."
        )
    if asset.media_version != expected_media_version:
        raise PageMediaPlanningError("Page media version changed before retirement.")
    if asset.governance_status == "retired":
        return asset
    if asset.governance_status != "approved":
        raise PageMediaPlanningError("Only approved governed page media can be retired.")
    asset.governance_status = "retired"
    asset.review_status = "retired"
    asset.retired_by = _required_text(retired_by, "Retirement operator")
    asset.retirement_rationale = _required_text(rationale, "Retirement rationale")
    asset.retired_at = datetime.now(UTC)
    asset.updated_at = datetime.now(UTC)
    assignments = list(session.exec(
        select(PageImageAssignment).where(
            PageImageAssignment.image_metadata_id == asset.id,
            PageImageAssignment.status == "active",
            PageImageAssignment.media_requirement_id.is_not(None),
        )
    ).all())
    for assignment in assignments:
        assignment.status = "retired"
        assignment.retired_by = asset.retired_by
        assignment.retirement_rationale = asset.retirement_rationale
        assignment.retired_at = asset.retired_at
        assignment.updated_at = datetime.now(UTC)
        session.add(assignment)
        if assignment.planned_page_id:
            _mark_composition_stale(session, assignment.planned_page_id)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def assign_media_to_requirement(
    session: Session,
    plan_id: int,
    requirement_id: int,
    payload: PageMediaAssignmentRequest,
) -> PageMediaWorkspace:
    plan, website = _plan_context(session, plan_id)
    requirement = session.get(PlannedPageMediaRequirement, requirement_id)
    if (
        not requirement
        or requirement.website_id != website.id
        or requirement.business_id != website.business_id
        or requirement.site_plan_id != plan.id
        or requirement.lifecycle_status != "active"
    ):
        raise PageMediaPlanningError("Media placement is missing, stale, or crosses the selected Site Plan.")
    if requirement.version != payload.expected_requirement_version:
        raise PageMediaPlanningError("Media placement version changed; reload before assigning.")
    if requirement.requirement_state not in {"required", "advisory"}:
        raise PageMediaPlanningError("Excluded or deferred placements cannot receive media assignments.")
    current_planning = _current_planning_record(session, plan.id or plan_id)
    _require_planning_record_scope(current_planning, plan, website)
    if not current_planning or not _requirement_matches_current_planning(
        session,
        requirement,
        current_planning,
    ):
        raise PageMediaPlanningError("Media placement is bound to a stale planning record.")
    pages = list(
        session.exec(
            select(PlannedPage)
            .where(PlannedPage.site_plan_id == plan.id)
            .order_by(PlannedPage.id)
        ).all()
    )
    if current_planning.source_hash != _hash(
        _planning_source_snapshot(session, plan, pages)
    ):
        raise PageMediaPlanningError(
            "Page Media planning suggestions are stale and must be refreshed."
        )
    page = session.get(PlannedPage, requirement.planned_page_id)
    if not page or page.website_id != website.id or page.site_plan_id != plan.id or not page.generated_page_id:
        raise PageMediaPlanningError("Media placement does not resolve to a Generated Page in this Website.")
    generated = session.get(GeneratedPage, page.generated_page_id)
    if not generated or generated.website_id != website.id or generated.business_id != website.business_id:
        raise PageMediaPlanningError("Generated Page crosses the Website or Business boundary.")
    asset = _asset(session, payload.image_metadata_id)
    errors = _asset_compatibility_errors(session, asset, requirement, page, website)
    if errors:
        raise PageMediaPlanningError(" ".join(errors))
    _revalidate_managed_asset(asset)
    history = list(session.exec(
        select(PageImageAssignment).where(
            PageImageAssignment.media_requirement_id == requirement.id,
        ).order_by(PageImageAssignment.assignment_version.desc())
    ).all())
    active_rows = [item for item in history if item.status == "active"]
    if len(active_rows) > 1:
        raise PageMediaPlanningError("Media placement has multiple active governed assignments.")
    active = active_rows[0] if active_rows else None
    latest = history[0] if history else None
    clean_operator = _required_text(payload.assigned_by, "Assignment operator")
    clean_rationale = _required_text(payload.rationale, "Assignment rationale")
    clean_override_alt = (
        payload.override_alt_text.strip() if payload.override_alt_text else None
    )
    display_preset = (
        payload.display_preset
        or ("hero_desktop" if "hero" in requirement.placement_key else "card_thumbnail")
    ).strip().lower()
    if display_preset not in DISPLAY_PRESETS:
        raise PageMediaPlanningError("Page-media display preset is unsupported.")
    if (
        active
        and active.image_metadata_id == asset.id
        and active.media_version == asset.media_version
        and active.assignment_version is not None
        and active.placement_contract_version == requirement.contract_version
        and active.assigned_by == clean_operator
        and active.assignment_rationale == clean_rationale
        and active.override_focal_x == payload.override_focal_x
        and active.override_focal_y == payload.override_focal_y
        and active.override_alt_text == clean_override_alt
        and active.display_preset == display_preset
    ):
        return read_page_media_workspace(session, plan_id)
    version = (latest.assignment_version + 1) if latest and latest.assignment_version else 1
    if active:
        active.status = "replaced"
        active.replaced_by = clean_operator
        active.replacement_rationale = clean_rationale
        active.replaced_at = datetime.now(UTC)
        active.updated_at = datetime.now(UTC)
        session.add(active)
    role = f"{requirement.placement_key}:assignment-{version}"
    assignment = PageImageAssignment(
        generated_page_id=generated.id or 0,
        image_metadata_id=asset.id or 0,
        website_id=website.id,
        site_plan_id=plan.id,
        planned_page_id=page.id,
        media_requirement_id=requirement.id,
        assignment_version=version,
        media_version=asset.media_version,
        placement_contract_version=requirement.contract_version,
        image_role=role,
        sort_order=0,
        override_focal_x=payload.override_focal_x,
        override_focal_y=payload.override_focal_y,
        override_alt_text=clean_override_alt,
        display_preset=display_preset,
        status="active",
        assigned_by=clean_operator,
        assignment_rationale=clean_rationale,
        assigned_at=datetime.now(UTC),
        replaces_page_image_assignment_id=latest.id if latest else None,
    )
    generated.qa_status = "not_run"
    generated.qa_result = None
    generated.qa_checked_at = None
    session.add(generated)
    session.add(assignment)
    _mark_composition_stale(session, page.id or 0)
    session.commit()
    return read_page_media_workspace(session, plan_id)


def effective_media_requirements(
    session: Session,
    planned_page_id: int,
) -> list[PlannedPageMediaRequirement]:
    rows = list(session.exec(
        select(PlannedPageMediaRequirement).where(
            PlannedPageMediaRequirement.planned_page_id == planned_page_id
        ).order_by(
            PlannedPageMediaRequirement.placement_key,
            PlannedPageMediaRequirement.version,
        )
    ).all())
    latest: dict[str, PlannedPageMediaRequirement] = {}
    for row in rows:
        if row.lifecycle_status == "active":
            latest[row.placement_key] = row
    return [latest[key] for key in sorted(latest)]


def governed_assignment_for_requirement(
    session: Session,
    requirement_id: int,
) -> PageImageAssignment | None:
    rows = list(session.exec(
        select(PageImageAssignment).where(
            PageImageAssignment.media_requirement_id == requirement_id,
            PageImageAssignment.status == "active",
        )
    ).all())
    if len(rows) > 1:
        raise PageMediaPlanningError("Media placement has multiple active governed assignments.")
    return rows[0] if rows else None


def validate_required_media_for_page(
    session: Session,
    planned_page: PlannedPage,
    *,
    require_approved_assignments: bool = True,
) -> list[str]:
    errors: list[str] = []
    plan = session.get(SitePlan, planned_page.site_plan_id)
    website = session.get(Website, planned_page.website_id)
    if not plan or not website or plan.website_id != website.id:
        return ["Page Media validation cannot resolve the Website and Site Plan boundary."]
    current_planning = _current_planning_record(session, plan.id or 0)
    _require_planning_record_scope(current_planning, plan, website)
    if current_planning is None:
        # Legacy compositions remain valid until an operator starts the governed
        # Page Media planning workflow for this Site Plan.
        return []
    pages = list(
        session.exec(
            select(PlannedPage)
            .where(PlannedPage.site_plan_id == plan.id)
            .order_by(PlannedPage.id)
        ).all()
    )
    if current_planning.source_hash != _hash(_planning_source_snapshot(session, plan, pages)):
        errors.append("Page Media planning suggestions are stale.")
    try:
        exact_component_keys = _exact_page_composition_component_keys(
            session,
            planned_page,
            plan,
            website,
        )
    except PageMediaPlanningError as exc:
        errors.append(str(exc))
        exact_component_keys = set()
    requirements = effective_media_requirements(session, planned_page.id or 0)
    requirements_by_key = {item.placement_key: item for item in requirements}
    suggestion_keys = {
        value.get("placement_key")
        for value in current_planning.generated_media_suggestions
        if value.get("planned_page_id") == planned_page.id
        and isinstance(value.get("placement_key"), str)
    }
    for placement_key in sorted(suggestion_keys):
        if placement_key not in requirements_by_key:
            errors.append(
                f"Media placement {placement_key} has no current operator decision."
            )
    for requirement in requirements:
        errors.extend(
            _requirement_scope_errors(
                session,
                requirement,
                planned_page,
                plan,
                website,
            )
        )
        if not current_planning or not _requirement_matches_current_planning(
            session,
            requirement,
            current_planning,
        ):
            errors.append(f"Media placement {requirement.placement_key} is bound to a stale planning record.")
            continue
        if requirement.requirement_state not in {"required", "advisory"}:
            continue
        if requirement.component_or_section not in exact_component_keys:
            errors.append(
                "Media placement "
                f"{requirement.placement_key} target is missing from the exact "
                "effective Planned Page composition."
            )
            continue
        assignment = governed_assignment_for_requirement(session, requirement.id or 0)
        if assignment is None:
            if (
                require_approved_assignments
                and requirement.requirement_state == "required"
            ):
                errors.append(f"Required media placement {requirement.placement_key} has no approved assignment.")
            continue
        asset = session.get(ImageMetadata, assignment.image_metadata_id)
        if not asset:
            errors.append(f"Assigned media for {requirement.placement_key} is missing.")
            continue
        errors.extend(
            _assignment_binding_errors(
                assignment,
                asset,
                requirement,
                planned_page,
                website,
            )
        )
        errors.extend(
            _asset_compatibility_errors(
                session,
                asset,
                requirement,
                planned_page,
                website,
            )
        )
    return errors


def media_source_snapshot(
    session: Session,
    planned_page: PlannedPage,
) -> dict[str, Any]:
    plan = session.get(SitePlan, planned_page.site_plan_id)
    if not plan:
        raise PageMediaPlanningError(
            "Page Media composition source references a missing Site Plan."
        )
    planning = _current_planning_record(session, plan.id or 0)
    website = session.get(Website, planned_page.website_id)
    if not website or plan.website_id != website.id:
        raise PageMediaPlanningError(
            "Page Media composition source crosses a Website or Site Plan boundary."
        )
    _require_planning_record_scope(planning, plan, website)
    requirements = effective_media_requirements(session, planned_page.id or 0)
    for requirement in requirements:
        scope_errors = _requirement_scope_errors(
            session,
            requirement,
            planned_page,
            plan,
            website,
        )
        if scope_errors:
            raise PageMediaPlanningError(" ".join(scope_errors))
    has_suggestions = bool(
        planning
        and any(
            value.get("planned_page_id") == planned_page.id
            for value in planning.generated_media_suggestions
        )
    )
    if not has_suggestions and not requirements:
        return {"planning_record": None, "requirements": [], "assignments": []}
    assignments: list[dict[str, Any]] = []
    for requirement in requirements:
        assignment = governed_assignment_for_requirement(session, requirement.id or 0)
        asset = session.get(ImageMetadata, assignment.image_metadata_id) if assignment else None
        if is_image_metadata_excluded(website, asset):
            assignment = None
            asset = None
        assignments.append({
            "requirement_id": requirement.id,
            "requirement_version": requirement.version,
            "placement_contract_version": requirement.contract_version,
            "assignment_id": assignment.id if assignment else None,
            "assignment_version": assignment.assignment_version if assignment else None,
            "asset_id": asset.id if asset else None,
            "media_version": asset.media_version if asset else None,
            "checksum_sha256": asset.checksum_sha256 if asset else None,
            "governance_status": asset.governance_status if asset else None,
        })
    return {
        "planning_record": (
            _planning_page_binding(planning, planned_page.id or 0)
            if planning
            else None
        ),
        "requirements": [
            {
                "id": item.id,
                "placement_key": item.placement_key,
                "version": item.version,
                "contract_version": item.contract_version,
                "component_or_section": item.component_or_section,
                "component_contract_version": _active_component_contract_version(
                    session,
                    item.component_or_section,
                ),
                "requirement_state": item.requirement_state,
                "planning_record_id": item.planning_record_id,
                "lifecycle_status": item.lifecycle_status,
            }
            for item in requirements
        ],
        "assignments": assignments,
    }


def _active_component_contract_version(session: Session, component_key: str) -> int:
    component = session.exec(
        select(SemanticComponentDefinition).where(
            SemanticComponentDefinition.component_key == component_key,
            SemanticComponentDefinition.status == "active",
        ).order_by(
            SemanticComponentDefinition.contract_version.desc(),
            SemanticComponentDefinition.id.desc(),
        )
    ).first()
    if component is None:
        raise PageMediaPlanningError(
            "Page Media placement references a missing active semantic component."
        )
    return component.contract_version


def _planning_source_snapshot(
    session: Session,
    plan: SitePlan,
    pages: list[PlannedPage],
) -> dict[str, Any]:
    component_versions: dict[str, int] = {}
    for row in session.exec(
        select(SemanticComponentDefinition).where(
            SemanticComponentDefinition.status == "active"
        )
    ).all():
        component_versions[row.component_key] = max(
            component_versions.get(row.component_key, 0),
            row.contract_version,
        )
    planning_records = {
        row.planned_page_id: row
        for row in session.exec(
            select(PlanningRecord).where(
                PlanningRecord.planned_page_id.in_([page.id for page in pages if page.id])
            )
        ).all()
    } if pages else {}
    return {
        "website_id": plan.website_id,
        "site_plan_id": plan.id,
        "site_plan_version": plan.version,
        "algorithm_version": ALGORITHM_VERSION,
        "placement_contract_version": PLACEMENT_CONTRACT_VERSION,
        "component_contract_versions": component_versions,
        "planned_pages": [
            {
                "id": page.id,
                "page_type": page.page_type,
                "contract_page_type": _page_contract_key(page),
                "service_id": page.service_id,
                "city_id": page.city_id,
                "county_id": page.county_id,
                "generated_page_id": page.generated_page_id,
                "updated_at": page.updated_at.isoformat(),
                "planning_record_updated_at": (
                    planning_records[page.id].updated_at.isoformat()
                    if page.id in planning_records
                    else None
                ),
            }
            for page in pages
        ],
    }


def _planning_page_binding(
    planning: WebsiteMediaPlanningRecord,
    planned_page_id: int,
) -> dict[str, Any]:
    """Return only media-planning inputs that can affect one Planned Page.

    The Website planning record is versioned as a whole, but unrelated page changes
    must not stale every composition or invalidate unchanged operator decisions.
    """

    snapshot = planning.source_snapshot or {}
    page_snapshot = next(
        (
            value
            for value in snapshot.get("planned_pages", [])
            if value.get("id") == planned_page_id
        ),
        None,
    )
    suggestions = sorted(
        (
            dict(value)
            for value in planning.generated_media_suggestions or []
            if value.get("planned_page_id") == planned_page_id
        ),
        key=lambda value: (
            str(value.get("placement_key") or ""),
            str(value.get("suggestion_key") or ""),
        ),
    )
    component_keys = {
        str(value.get("component_or_section"))
        for value in suggestions
        if value.get("component_or_section")
    }
    component_versions = snapshot.get("component_contract_versions", {})
    return {
        "algorithm_version": planning.algorithm_version,
        "placement_contract_version": snapshot.get("placement_contract_version"),
        "planned_page": page_snapshot,
        "component_contract_versions": {
            key: component_versions.get(key) for key in sorted(component_keys)
        },
        "suggestions": suggestions,
    }


def _requirement_matches_current_planning(
    session: Session,
    requirement: PlannedPageMediaRequirement,
    current: WebsiteMediaPlanningRecord,
) -> bool:
    if (
        current.website_id != requirement.website_id
        or current.business_id != requirement.business_id
        or current.site_plan_id != requirement.site_plan_id
    ):
        return False
    if requirement.planning_record_id == current.id:
        return True
    historical = session.get(
        WebsiteMediaPlanningRecord,
        requirement.planning_record_id,
    )
    if historical is None:
        return False
    if (
        historical.website_id != requirement.website_id
        or historical.business_id != requirement.business_id
        or historical.site_plan_id != requirement.site_plan_id
    ):
        return False
    return _planning_page_binding(
        historical,
        requirement.planned_page_id,
    ) == _planning_page_binding(
        current,
        requirement.planned_page_id,
    )


def _requirement_values(
    payload: PageMediaPlacementDecisionRequest,
    suggestion: dict[str, Any] | None,
    page: PlannedPage,
) -> dict[str, Any]:
    base = dict(suggestion or {})
    for field in (
        "component_or_section", "purpose", "customer_outcome", "intended_subject",
        "orientation", "aspect_ratio", "minimum_width", "minimum_height",
        "crop_intent", "focal_point_intent", "responsive_behavior",
        "accessibility_intent", "caption_intent", "approved_source_constraints",
        "permitted_reuse_policy", "replacement_policy", "compatible_page_types",
    ):
        value = getattr(payload, field)
        if value is not None:
            base[field] = value
    required = (
        "component_or_section", "purpose", "customer_outcome", "intended_subject",
        "orientation", "aspect_ratio", "minimum_width", "minimum_height",
        "crop_intent", "focal_point_intent",
        "responsive_behavior", "accessibility_intent", "approved_source_constraints",
        "permitted_reuse_policy", "replacement_policy", "compatible_page_types",
    )
    missing = [field for field in required if not base.get(field)]
    if missing:
        raise PageMediaPlanningError(
            "Placement decision is missing contract fields: " + ", ".join(missing) + "."
        )
    orientation = str(base["orientation"]).strip().lower()
    if orientation not in ORIENTATIONS:
        raise PageMediaPlanningError("Placement orientation is unsupported.")
    compatible = _clean_list(base["compatible_page_types"])
    if page.page_type not in compatible:
        raise PageMediaPlanningError("Placement contract is incompatible with this Planned Page type.")
    source_constraints = _clean_prose_list(base["approved_source_constraints"])
    if not source_constraints:
        raise PageMediaPlanningError("Approved source constraints are required.")
    return {
        "website_id": page.website_id,
        "business_id": base.get("business_id") or 0,
        "site_plan_id": page.site_plan_id,
        "planned_page_id": page.id or 0,
        "planning_record_id": base.get("planning_record_id"),
        "component_or_section": str(base["component_or_section"]).strip(),
        "placement_key": payload.placement_key.strip().lower(),
        "contract_version": int(base.get("contract_version") or PLACEMENT_CONTRACT_VERSION),
        "requirement_state": payload.requirement_state,
        "purpose": str(base["purpose"]).strip(),
        "customer_outcome": str(base["customer_outcome"]).strip(),
        "intended_subject": str(base["intended_subject"]).strip(),
        "orientation": orientation,
        "aspect_ratio": str(base["aspect_ratio"]).strip().lower(),
        "minimum_width": base.get("minimum_width"),
        "minimum_height": base.get("minimum_height"),
        "crop_intent": str(base["crop_intent"]).strip(),
        "focal_point_intent": str(base["focal_point_intent"]).strip(),
        "responsive_behavior": str(base["responsive_behavior"]).strip(),
        "accessibility_intent": str(base["accessibility_intent"]).strip(),
        "caption_intent": str(base["caption_intent"]).strip() if base.get("caption_intent") else None,
        "approved_source_constraints": source_constraints,
        "permitted_reuse_policy": str(base["permitted_reuse_policy"]).strip(),
        "replacement_policy": str(base["replacement_policy"]).strip(),
        "compatible_page_types": compatible,
        "source_suggestion_key": payload.source_suggestion_key or base.get("suggestion_key"),
        "decided_by": _required_text(payload.decided_by, "Decision operator"),
        "rationale": _required_text(payload.rationale, "Decision rationale"),
    }


def _asset_compatibility_errors(
    session: Session,
    asset: ImageMetadata | None,
    requirement: PlannedPageMediaRequirement,
    page: PlannedPage,
    website: Website,
) -> list[str]:
    if asset is None:
        return ["Governed media asset is missing."]
    errors: list[str] = []
    if asset.website_id != website.id or asset.business_id != website.business_id:
        errors.append("Media asset crosses the Website or Business boundary.")
    if is_image_metadata_excluded(website, asset):
        errors.append(
            "Media asset is excluded by the Website-scoped external-media safety policy."
        )
    if asset.governance_status != "approved":
        errors.append("Media asset is not approved through governed page-media approval.")
    if asset.retired_at or _is_asset_superseded(session, asset):
        errors.append("Media asset is retired or superseded.")
    if page.page_type not in requirement.compatible_page_types:
        errors.append("Media placement is incompatible with this page type.")
    usages = set(asset.approved_usage or [])
    prohibited = set(asset.prohibited_usage or [])
    keys = set(asset.permitted_placement_keys or [])
    placement_tokens = {
        requirement.placement_key,
        requirement.component_or_section,
        "page_media",
        "*",
    }
    if not usages.intersection(placement_tokens):
        errors.append("Media approved usage does not permit this placement.")
    if prohibited.intersection(placement_tokens):
        errors.append("Media prohibited usage blocks this placement.")
    if "*" not in keys and requirement.placement_key not in keys:
        errors.append("Media is not permitted for this exact placement key.")
    source_tokens = {
        "company_original": "approved_company_media",
        "commissioned": "approved_company_media",
        "licensed": "licensed_media",
        "stock": "licensed_media",
        "generated": "approved_generated_media",
        "public_domain": "public_domain_media",
    }
    provenance_token = source_tokens.get(asset.provenance_type or "")
    asset_source_tokens = {provenance_token} if provenance_token else set()
    if not set(requirement.approved_source_constraints or []).intersection(asset_source_tokens):
        errors.append("Media source provenance is not permitted by this placement contract.")
    if not _governance_complete(asset):
        errors.append("Media provenance, rights, technical identity, or accessibility governance is incomplete.")
    orientation = _asset_orientation(asset)
    if requirement.orientation != "any" and orientation != requirement.orientation:
        errors.append("Media orientation is incompatible with the approved placement.")
    if requirement.minimum_width and (asset.width or 0) < requirement.minimum_width:
        errors.append("Media width is below the approved practical minimum.")
    if requirement.minimum_height and (asset.height or 0) < requirement.minimum_height:
        errors.append("Media height is below the approved practical minimum.")
    if requirement.aspect_ratio not in {"any", "auto"} and asset.width and asset.height:
        expected = _parse_aspect_ratio(requirement.aspect_ratio)
        if expected is None or abs((asset.width / asset.height) - expected) > 0.35:
            errors.append("Media aspect ratio is incompatible with the approved placement.")
    if requirement.accessibility_intent != "decorative" and not asset.reviewed_alt_text:
        errors.append("Informative media requires reviewed alt text.")
    return list(dict.fromkeys(errors))


def _assignment_binding_errors(
    assignment: PageImageAssignment,
    asset: ImageMetadata,
    requirement: PlannedPageMediaRequirement,
    page: PlannedPage,
    website: Website,
) -> list[str]:
    errors: list[str] = []
    if assignment.status != "active":
        errors.append("Governed media assignment is not active.")
    if (
        assignment.website_id != website.id
        or assignment.site_plan_id != page.site_plan_id
        or assignment.planned_page_id != page.id
        or assignment.media_requirement_id != requirement.id
    ):
        errors.append("Governed media assignment crosses its Website, Site Plan, page, or placement boundary.")
    if assignment.generated_page_id != page.generated_page_id:
        errors.append("Governed media assignment targets the wrong Generated Page.")
    if assignment.image_metadata_id != asset.id or assignment.media_version != asset.media_version:
        errors.append("Governed media assignment is not bound to the exact approved media version.")
    if assignment.placement_contract_version != requirement.contract_version:
        errors.append("Governed media assignment is not bound to the exact placement-contract version.")
    if (
        assignment.assignment_version is None
        or not assignment.assigned_by
        or not assignment.assignment_rationale
        or assignment.assigned_at is None
    ):
        errors.append("Governed media assignment provenance is incomplete.")
    return errors


def _validate_asset_governance(asset: ImageMetadata, *, require_approved: bool) -> None:
    if require_approved and asset.governance_status != "approved":
        raise PageMediaPlanningError("Governed page media is not approved.")
    if not _governance_complete(asset):
        raise PageMediaPlanningError("Page media provenance, rights, usage, accessibility, or technical identity is incomplete.")
    if asset.gps_metadata_status == "present_unverified":
        raise PageMediaPlanningError("Unverified GPS metadata blocks page-media approval.")
    if asset.gps_metadata_status == "verified_authorized":
        if asset.acquisition_source != "company_photograph":
            raise PageMediaPlanningError("Only a legitimate company photograph may preserve verified GPS metadata.")
        if not asset.gps_authorized_by or not asset.gps_authorized_at or not asset.gps_authorization_notes:
            raise PageMediaPlanningError("Verified GPS retention requires explicit privacy-safe operator authorization.")
    if asset.acquisition_source in {"generated", "stock"} and asset.gps_metadata_status not in {"absent", "stripped"}:
        raise PageMediaPlanningError("Generated or stock media cannot contain preserved GPS metadata.")


def _governance_complete(asset: ImageMetadata) -> bool:
    required = (
        asset.website_id,
        asset.media_key,
        asset.media_version,
        asset.mime_type,
        asset.file_size,
        asset.width,
        asset.height,
        asset.checksum_sha256,
        asset.managed_storage_path,
        asset.acquisition_source,
        asset.creator_source_identity,
        asset.provenance_type,
        asset.provenance_notes,
        asset.rights_status,
        asset.rights_holder,
        asset.rights_notes,
        asset.accessibility_intent,
        asset.stored_filename,
        asset.asset_url,
        asset.optimized_url,
        asset.thumbnail_url,
    )
    return (
        all(value is not None and value != "" for value in required)
        and asset.provenance_type in PROVENANCE_TYPES
        and asset.rights_status in RIGHTS_STATUSES
        and asset.acquisition_source in ACQUISITION_SOURCES
        and _source_governance_valid(
            asset.acquisition_source or "",
            asset.provenance_type or "",
            asset.rights_status or "",
        )
        and bool(asset.approved_usage)
        and bool(asset.prohibited_usage)
        and bool(asset.permitted_placement_keys)
        and asset.gps_metadata_status in {"absent", "stripped", "verified_authorized"}
        and (asset.accessibility_intent == "decorative" or bool(asset.reviewed_alt_text))
        and (
            asset.governance_status not in {"approved", "retired"}
            or (
                asset.approval_version is not None
                and bool(asset.approved_by)
                and asset.approved_at is not None
            )
        )
        and (
            asset.governance_status != "retired"
            or (
                bool(asset.retired_by)
                and bool(asset.retirement_rationale)
                and asset.retired_at is not None
            )
        )
        and (
            asset.gps_metadata_status != "verified_authorized"
            or (
                asset.acquisition_source == "company_photograph"
                and bool(asset.gps_metadata)
                and bool(asset.gps_authorized_by)
                and asset.gps_authorized_at is not None
                and bool(asset.gps_authorization_notes)
            )
        )
        and (
            asset.acquisition_source not in {"generated", "stock"}
            or asset.gps_metadata_status in {"absent", "stripped"}
        )
        and (
            (asset.media_version == 1 and asset.replaces_image_metadata_id is None)
            or (
                asset.media_version is not None
                and asset.media_version > 1
                and asset.replaces_image_metadata_id is not None
            )
        )
    )


def _revalidate_managed_asset(asset: ImageMetadata) -> None:
    if not asset.stored_filename or not asset.original_filename:
        raise PageMediaPlanningError("Managed original filename is missing.")
    if not is_safe_image_filename(asset.stored_filename) or not is_safe_image_filename(asset.original_filename):
        raise PageMediaPlanningError("Managed page-media filename is unsafe.")
    observed = inspect_managed_original(asset.stored_filename, get_settings())
    expected = {
        "stored_filename": asset.stored_filename,
        "mime_type": asset.mime_type,
        "file_size": asset.file_size,
        "width": asset.width,
        "height": asset.height,
        "checksum_sha256": asset.checksum_sha256,
    }
    actual = {
        "stored_filename": observed.stored_filename,
        "mime_type": observed.mime_type,
        "file_size": observed.file_size,
        "width": observed.width,
        "height": observed.height,
        "checksum_sha256": observed.checksum_sha256,
    }
    if expected != actual:
        raise PageMediaPlanningError("Managed page-media original no longer matches its recorded binary identity.")
    expected_path = f"originals/{asset.stored_filename}"
    if asset.managed_storage_path != expected_path or Path(asset.managed_storage_path).as_posix() != expected_path:
        raise PageMediaPlanningError("Managed page-media path is invalid.")
    settings = get_settings()
    public_base = settings.media_public_url.rstrip("/")
    root = settings.media_root.resolve()
    for value, directory in (
        (asset.asset_url, "optimized"),
        (asset.optimized_url, "optimized"),
        (asset.thumbnail_url, "thumbnails"),
    ):
        prefix = f"{public_base}/{directory}/"
        if not value or not value.startswith(prefix):
            raise PageMediaPlanningError("Recorded managed media URLs are incomplete or invalid.")
        filename = value.removeprefix(prefix)
        if not is_safe_image_filename(filename):
            raise PageMediaPlanningError("Recorded managed media URL contains an unsafe filename.")
        directory_root = (root / directory).resolve()
        path = (directory_root / filename).resolve()
        try:
            valid_derivative = (
                path.parent == directory_root
                and path.is_file()
                and path.stat().st_size > 0
            )
        except OSError as exc:
            raise PageMediaPlanningError(
                "Recorded managed media derivative is missing or unreadable."
            ) from exc
        if not valid_derivative:
            raise PageMediaPlanningError(
                "Recorded managed media derivative is missing or unreadable."
            )
    _validate_asset_governance(asset, require_approved=False)


def _mark_composition_stale(session: Session, planned_page_id: int) -> None:
    composition = session.exec(
        select(PageComposition).where(PageComposition.planned_page_id == planned_page_id)
    ).first()
    if composition:
        composition.status = "stale"
        composition.updated_at = datetime.now(UTC)
        session.add(composition)


def _exact_page_composition_component_keys(
    session: Session,
    page: PlannedPage,
    plan: SitePlan,
    website: Website,
) -> set[str]:
    composition = session.exec(
        select(PageComposition).where(
            PageComposition.planned_page_id == page.id
        )
    ).first()
    if composition is None:
        raise PageMediaPlanningError(
            f"No exact Page Composition exists for Planned Page {page.id}."
        )
    if (
        composition.website_id != website.id
        or composition.site_plan_id != plan.id
        or composition.planned_page_id != page.id
        or composition.generated_page_id != page.generated_page_id
    ):
        raise PageMediaPlanningError(
            "Page Composition crosses its Website, Site Plan, Planned Page, "
            "or Generated Page boundary."
        )
    suppressed_instance_keys = {
        str(value.get("instance_key") or "").strip()
        for value in composition.operator_decisions
        if isinstance(value, dict)
        and value.get("action") == "suppress"
        and str(value.get("instance_key") or "").strip()
    }
    return {
        component_key.strip()
        for value in composition.generated_components
        if isinstance(value, dict)
        and str(value.get("instance_key") or "").strip()
        not in suppressed_instance_keys
        and isinstance((component_key := value.get("component_key")), str)
        and component_key.strip()
    }


def _require_exact_page_composition_target(
    page: PlannedPage,
    component_key: str,
    composition_component_keys: set[str],
) -> None:
    if component_key not in composition_component_keys:
        raise PageMediaPlanningError(
            "Page Media placement target is missing from the exact Planned Page "
            f"composition: {component_key} (Planned Page {page.id})."
        )


def _plan_context(session: Session, plan_id: int) -> tuple[SitePlan, Website]:
    plan = session.get(SitePlan, plan_id)
    if not plan:
        raise PageMediaPlanningError("Site Plan not found.")
    website = session.get(Website, plan.website_id)
    if not website:
        raise PageMediaPlanningError("Site Plan Website not found.")
    business = session.get(Business, website.business_id)
    if not business:
        raise PageMediaPlanningError("Website Business not found.")
    return plan, website


def _require_planning_record_scope(
    planning: WebsiteMediaPlanningRecord | None,
    plan: SitePlan,
    website: Website,
) -> None:
    if planning is None:
        return
    if (
        planning.website_id != website.id
        or planning.business_id != website.business_id
        or planning.site_plan_id != plan.id
    ):
        raise PageMediaPlanningError(
            "Page Media planning record crosses its Website, Business, or Site Plan boundary."
        )


def _requirement_scope_errors(
    session: Session,
    requirement: PlannedPageMediaRequirement,
    page: PlannedPage | None,
    plan: SitePlan,
    website: Website,
) -> list[str]:
    errors: list[str] = []
    if page is None:
        errors.append("Page Media placement references a missing Planned Page.")
    elif page.website_id != website.id or page.site_plan_id != plan.id:
        errors.append("Page Media placement references a Planned Page outside its Website or Site Plan.")
    if (
        requirement.website_id != website.id
        or requirement.business_id != website.business_id
        or requirement.site_plan_id != plan.id
        or (page is not None and requirement.planned_page_id != page.id)
    ):
        errors.append("Page Media placement crosses its Website, Business, Site Plan, or page boundary.")
    planning = session.get(
        WebsiteMediaPlanningRecord,
        requirement.planning_record_id,
    )
    if (
        planning is None
        or planning.website_id != requirement.website_id
        or planning.business_id != requirement.business_id
        or planning.site_plan_id != requirement.site_plan_id
    ):
        errors.append("Page Media placement references an invalid planning-record boundary.")
    return errors


def _current_planning_record(
    session: Session,
    plan_id: int,
) -> WebsiteMediaPlanningRecord | None:
    return session.exec(
        select(WebsiteMediaPlanningRecord)
        .where(WebsiteMediaPlanningRecord.site_plan_id == plan_id)
        .order_by(WebsiteMediaPlanningRecord.version.desc())
    ).first()


def _page_contract_key(page: PlannedPage) -> str:
    if page.page_type == "county" and page.service_id:
        return "service_county"
    return page.page_type


def _page_identity(page: PlannedPage) -> PageMediaPlannedPageIdentity:
    return PageMediaPlannedPageIdentity(
        id=page.id or 0,
        website_id=page.website_id,
        site_plan_id=page.site_plan_id,
        generated_page_id=page.generated_page_id,
        page_type=page.page_type,
        working_name=page.working_name,
        intended_slug=page.intended_slug,
    )


def _planning_record_read(row: WebsiteMediaPlanningRecord) -> PageMediaPlanningRecordRead:
    return PageMediaPlanningRecordRead(**row.model_dump())


def _requirement_read(row: PlannedPageMediaRequirement) -> PlannedPageMediaRequirementRead:
    return PlannedPageMediaRequirementRead(**row.model_dump())


def _asset_read(row: ImageMetadata) -> PageMediaAssetRead:
    values = row.model_dump()
    for key in ("approved_usage", "prohibited_usage", "permitted_placement_keys"):
        values[key] = values.get(key) or []
    values["gps_metadata"] = values.get("gps_metadata") or {}
    values["gps_metadata_status"] = values.get("gps_metadata_status") or "unknown"
    return PageMediaAssetRead(**values)


def _assignment_read(row: PageImageAssignment) -> PageMediaAssignmentRead:
    return PageMediaAssignmentRead(**row.model_dump())


def _asset(session: Session, image_id: int) -> ImageMetadata:
    asset = session.get(ImageMetadata, image_id)
    if not asset:
        raise PageMediaPlanningError("Page media asset not found.")
    return asset


def _asset_orientation(asset: ImageMetadata) -> str:
    if not asset.width or not asset.height:
        return "unknown"
    ratio = asset.width / asset.height
    if 0.92 <= ratio <= 1.08:
        return "square"
    return "landscape" if ratio > 1 else "portrait"


def _parse_aspect_ratio(value: str) -> float | None:
    try:
        left, right = value.split(":", 1)
        result = float(left) / float(right)
    except (ValueError, ZeroDivisionError):
        return None
    return result if result > 0 else None


def _is_asset_superseded(session: Session, asset: ImageMetadata) -> bool:
    if not asset.website_id or not asset.media_key or not asset.media_version:
        return False
    later = session.exec(
        select(ImageMetadata).where(
            ImageMetadata.website_id == asset.website_id,
            ImageMetadata.media_key == asset.media_key,
            ImageMetadata.media_version > asset.media_version,
        )
    ).all()
    return any(item.governance_status == "approved" or item.approved_at for item in later)


def _composition_status(composition: PageComposition | None) -> str:
    return composition.status if composition else "missing"


def _required_text(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise PageMediaPlanningError(f"{label} is required.")
    return cleaned


def _identifier(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if not normalized or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-_"
        for character in normalized
    ):
        raise PageMediaPlanningError(f"{label} must use lowercase letters, numbers, hyphens, or underscores.")
    return normalized


def _clean_list(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip().lower() for value in values if value.strip()))


def _clean_prose_list(values: list[str]) -> list[str]:
    """Trim and deduplicate governed prose without changing operator wording."""
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _source_governance_valid(
    acquisition_source: str,
    provenance_type: str,
    rights_status: str,
) -> bool:
    return (
        provenance_type in ACQUISITION_PROVENANCE.get(acquisition_source, set())
        and rights_status in PROVENANCE_RIGHTS.get(provenance_type, set())
    )


def _hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
