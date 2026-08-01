from __future__ import annotations

from datetime import UTC, datetime
from difflib import SequenceMatcher
import hashlib
import json
import re
from typing import Any

from sqlmodel import Session, select

from app.models import (
    Brand,
    Business,
    City,
    County,
    DraftingEligibilityAssessment,
    DraftingEligibilityDisposition,
    GeneratedPage,
    KnowledgeBlock,
    PlannedPage,
    PlanningRecord,
    PreDraftDistinctnessBrief,
    Service,
    SitePlan,
    SupportingPageAuthorization,
    Website,
    WebsiteCityCoverageDecision,
    WebsiteCountyCoverageDecision,
    WebsiteServiceCityCoverageDecision,
    WebsiteServiceCoverageDecision,
    WebsiteIdentity,
)
from app.schemas.drafting_eligibility import (
    CandidateDraftInput,
    CandidateDraftValidationFinding,
    CandidateDraftValidationResult,
    DraftingBatchManifest,
    DraftingBatchManifestCounts,
    DraftingBatchManifestItem,
    DraftingEligibilityManifest,
    EligibilityAssessmentRead,
    EligibilityDispositionRead,
    EligibilityDispositionUpdate,
    EligibilityManifestCounts,
    PreDraftDistinctnessBriefRead,
)
from app.services.page_type_review import validate_draft_contract
from app.services.county_page_contract import (
    CountyPageContractError,
    build_county_page_context,
)
from app.services.site_coverage import preview_expected_inventory


ALGORITHM_VERSION = "drafting-eligibility-v3"
BRIEF_ALGORITHM_VERSION = "pre-draft-distinctness-v2"
EXCEPTION_ALLOWED_STATUSES = {"consolidation_recommended"}


class DraftingEligibilityError(ValueError):
    pass


def assess_site_plan(
    session: Session, plan_id: int
) -> DraftingEligibilityManifest:
    plan, website = _scope(session, plan_id)
    inventory = preview_expected_inventory(session, plan_id)
    pages = list(
        session.exec(
            select(PlannedPage)
            .where(PlannedPage.site_plan_id == plan_id)
            .order_by(PlannedPage.id)
        ).all()
    )
    inventory_by_page = {
        item.planned_page_id: item
        for item in inventory.items
        if item.planned_page_id is not None
    }
    coverage_binding = _coverage_binding(session, website.id or 0)
    inventory_binding = _inventory_binding(inventory)
    now = datetime.now(UTC)
    briefs: dict[int, PreDraftDistinctnessBrief] = {}
    for page in pages:
        if page.id is None:
            continue
        record = session.exec(
            select(PlanningRecord).where(
                PlanningRecord.planned_page_id == page.id
            )
        ).first()
        briefs[page.id] = _upsert_distinctness_brief(
            session,
            plan,
            website,
            page,
            record,
            pages,
            generated_at=now,
        )
    session.flush()
    for page in pages:
        if page.id is None:
            continue
        record = session.exec(
            select(PlanningRecord).where(
                PlanningRecord.planned_page_id == page.id
            )
        ).first()
        sources = _approved_source_identities(session, website, page)
        brief = briefs[page.id]
        local_findings = _local_value_findings(page, brief)
        semantic_findings = _semantic_findings(
            session, website, page, brief, briefs
        )
        status, reasons = _status(
            inventory_by_page.get(page.id),
            record,
            local_findings,
            semantic_findings,
        )
        existing = session.exec(
            select(DraftingEligibilityAssessment).where(
                DraftingEligibilityAssessment.planned_page_id == page.id
            )
        ).first()
        values = dict(
            website_id=website.id or 0,
            site_plan_id=plan.id or plan_id,
            planned_page_id=page.id,
            status=status,
            algorithm_version=ALGORITHM_VERSION,
            coverage_binding=coverage_binding,
            expected_inventory_binding=inventory_binding,
            planning_record_binding=_planning_binding(record),
            distinctness_brief_binding=_brief_binding(brief),
            approved_source_identities=sources,
            evidence={
                "page_type": page.page_type,
                "intended_slug": page.intended_slug,
                "generated_page_id": page.generated_page_id,
            },
            local_value_findings=local_findings,
            semantic_findings=semantic_findings,
            reasons=reasons,
            assessed_at=now,
            updated_at=now,
        )
        if existing is None:
            existing = DraftingEligibilityAssessment(**values)
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        session.add(existing)
    session.commit()
    return read_manifest(session, plan_id)


def read_manifest(
    session: Session, plan_id: int
) -> DraftingEligibilityManifest:
    plan, website = _scope(session, plan_id)
    inventory = preview_expected_inventory(session, plan_id)
    coverage_binding = _coverage_binding(session, website.id or 0)
    inventory_binding = _inventory_binding(inventory)
    assessments = list(
        session.exec(
            select(DraftingEligibilityAssessment)
            .where(DraftingEligibilityAssessment.site_plan_id == plan_id)
            .order_by(DraftingEligibilityAssessment.planned_page_id)
        ).all()
    )
    dispositions = {
        item.planned_page_id: item
        for item in session.exec(
            select(DraftingEligibilityDisposition).where(
                DraftingEligibilityDisposition.site_plan_id == plan_id
            )
        ).all()
    }
    pages = {
        item.id: item
        for item in session.exec(
            select(PlannedPage).where(PlannedPage.site_plan_id == plan_id)
        ).all()
    }
    briefs = {
        item.planned_page_id: item
        for item in session.exec(
            select(PreDraftDistinctnessBrief).where(
                PreDraftDistinctnessBrief.site_plan_id == plan_id
            )
        ).all()
    }
    reads: list[EligibilityAssessmentRead] = []
    counts = EligibilityManifestCounts(expected=inventory.counts.expected)
    for assessment in assessments:
        page = pages.get(assessment.planned_page_id)
        brief = briefs.get(assessment.planned_page_id)
        record = session.exec(
            select(PlanningRecord).where(
                PlanningRecord.planned_page_id == assessment.planned_page_id
            )
        ).first()
        current = bool(
            page
            and assessment.algorithm_version == ALGORITHM_VERSION
            and assessment.coverage_binding == coverage_binding
            and assessment.expected_inventory_binding == inventory_binding
            and assessment.planning_record_binding == _planning_binding(record)
            and brief is not None
            and assessment.distinctness_brief_binding == _brief_binding(brief)
            and assessment.approved_source_identities
            == _approved_source_identities(session, website, page)
        )
        status = assessment.status if current else "stale_assessment"
        setattr(counts, status, getattr(counts, status) + 1)
        counts.assessed += 1
        disposition = dispositions.get(assessment.planned_page_id)
        exception = bool(
            current
            and status in EXCEPTION_ALLOWED_STATUSES
            and disposition
            and disposition.assessment_id == assessment.id
            and disposition.decision == "exception_approved"
            and disposition.accepted_exception
            and disposition.decided_at >= assessment.assessed_at
        )
        values = assessment.model_dump()
        values["status"] = status
        reads.append(
            EligibilityAssessmentRead(
                **values,
                current=current,
                effective_eligible=current
                and (status == "eligible" or exception),
                operator_disposition=(
                    EligibilityDispositionRead.model_validate(disposition)
                    if disposition
                    else None
                ),
            )
        )
    batch_manifest = _batch_manifest(
        website.id or 0,
        plan.id or plan_id,
        inventory,
        reads,
    )
    return DraftingEligibilityManifest(
        website_id=website.id or 0,
        site_plan_id=plan.id or plan_id,
        algorithm_version=ALGORITHM_VERSION,
        source_snapshot={
            "coverage": coverage_binding,
            "expected_inventory": inventory_binding,
            "algorithm_version": ALGORITHM_VERSION,
        },
        counts=counts,
        assessments=reads,
        distinctness_briefs=[
            PreDraftDistinctnessBriefRead.model_validate(item)
            for item in sorted(briefs.values(), key=lambda value: value.planned_page_id)
        ],
        inventory_exceptions=[
            {
                "inventory_key": item.inventory_key,
                "page_type": item.page_type,
                "working_name": item.working_name,
                "disposition": item.disposition,
                "reason": item.reason,
            }
            for item in inventory.items
            if item.disposition != "matching"
        ],
        batch_preview_ready=batch_manifest.preview_ready,
        batch_manifest=batch_manifest,
        generated_at=max(
            (item.assessed_at for item in assessments),
            default=datetime.now(UTC),
        ),
    )


def record_disposition(
    session: Session,
    assessment_id: int,
    payload: EligibilityDispositionUpdate,
) -> EligibilityDispositionRead:
    assessment = session.get(DraftingEligibilityAssessment, assessment_id)
    if assessment is None:
        raise DraftingEligibilityError("Drafting eligibility assessment not found.")
    if not payload.rationale.strip() or not payload.decided_by.strip():
        raise DraftingEligibilityError(
            "Operator rationale and decision provenance are required."
        )
    if payload.accepted_exception and (
        payload.decision != "exception_approved"
        or assessment.status not in EXCEPTION_ALLOWED_STATUSES
    ):
        raise DraftingEligibilityError(
            "This fail-closed eligibility status cannot be overridden."
        )
    existing = session.exec(
        select(DraftingEligibilityDisposition).where(
            DraftingEligibilityDisposition.planned_page_id
            == assessment.planned_page_id
        )
    ).first()
    if existing is None:
        existing = DraftingEligibilityDisposition(
            website_id=assessment.website_id,
            site_plan_id=assessment.site_plan_id,
            planned_page_id=assessment.planned_page_id,
            assessment_id=assessment.id or assessment_id,
            decision=payload.decision,
            rationale=payload.rationale.strip(),
            decided_by=payload.decided_by.strip(),
            accepted_exception=payload.accepted_exception,
        )
    else:
        existing.assessment_id = assessment.id or assessment_id
        existing.decision = payload.decision
        existing.rationale = payload.rationale.strip()
        existing.decided_by = payload.decided_by.strip()
        existing.accepted_exception = payload.accepted_exception
        existing.decision_version += 1
        existing.decided_at = datetime.now(UTC)
        existing.updated_at = existing.decided_at
    session.add(existing)
    session.commit()
    session.refresh(existing)
    return EligibilityDispositionRead.model_validate(existing)


def effective_batch_eligibility(
    session: Session, planned_page_id: int
) -> tuple[bool, str | None, str | None]:
    page = session.get(PlannedPage, planned_page_id)
    if page is None:
        return False, None, "Planned Page not found."
    manifest = read_manifest(session, page.site_plan_id)
    item = next(
        (
            assessment
            for assessment in manifest.assessments
            if assessment.planned_page_id == planned_page_id
        ),
        None,
    )
    if item is None:
        return (
            False,
            None,
            "No current coverage-gated drafting eligibility assessment.",
        )
    if item.effective_eligible:
        return True, item.status, None
    return False, item.status, "; ".join(item.reasons) or item.status


def _scope(session: Session, plan_id: int) -> tuple[SitePlan, Website]:
    plan = session.get(SitePlan, plan_id)
    if plan is None:
        raise DraftingEligibilityError("Site Plan not found.")
    website = session.get(Website, plan.website_id)
    if website is None:
        raise DraftingEligibilityError("Website not found.")
    return plan, website


def _coverage_binding(session: Session, website_id: int) -> dict[str, Any]:
    classes = (
        WebsiteServiceCoverageDecision,
        WebsiteCountyCoverageDecision,
        WebsiteCityCoverageDecision,
        WebsiteServiceCityCoverageDecision,
        SupportingPageAuthorization,
    )
    rows: list[dict[str, Any]] = []
    for model in classes:
        for item in session.exec(
            select(model).where(model.website_id == website_id)
        ).all():
            rows.append(
                {
                    "type": model.__name__,
                    "id": item.id,
                    "status": item.status,
                    "version": item.decision_version,
                    "updated_at": item.updated_at.isoformat(),
                }
            )
    return {"rows": sorted(rows, key=lambda item: (item["type"], item["id"]))}


def _inventory_binding(inventory: Any) -> dict[str, Any]:
    rows = [
        {
            "key": item.inventory_key,
            "disposition": item.disposition,
            "planned_page_id": item.planned_page_id,
        }
        for item in inventory.items
    ]
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "counts": inventory.counts.model_dump()}


def _planning_binding(record: PlanningRecord | None) -> dict[str, Any]:
    if record is None:
        return {"present": False}
    raw = {
        "generated_answers": record.generated_answers,
        "operator_overrides": record.operator_overrides,
        "source_snapshot": record.source_snapshot,
        "missing_information": record.missing_information,
        "generated_at": record.generated_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }
    digest = hashlib.sha256(
        json.dumps(raw, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()
    return {"present": True, "sha256": digest}


def _approved_source_identities(
    session: Session, website: Website, page: PlannedPage
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    business = session.get(Business, website.business_id)
    brand = session.get(Brand, website.brand_id) if website.brand_id else None
    identity = session.exec(
        select(WebsiteIdentity).where(WebsiteIdentity.website_id == website.id)
    ).first()
    for source_type, source in (
        ("business", business),
        ("brand", brand),
        ("website", website),
        ("website_identity", identity),
    ):
        if source is not None:
            sources.append(
                {
                    "type": source_type,
                    "id": source.id,
                    "updated_at": source.updated_at.isoformat(),
                }
            )
    sources.append(
        {
            "type": "planned_page",
            "id": page.id,
            "updated_at": page.updated_at.isoformat(),
        }
    )
    if page.service_id:
        service = session.get(Service, page.service_id)
        if service:
            sources.append(
                {"type": "service", "id": service.id, "updated_at": service.updated_at.isoformat()}
            )
    if page.city_id:
        city = session.get(City, page.city_id)
        if city:
            sources.append(
                {
                    "type": "city",
                    "id": city.id,
                    "identity_sha256": _identity_hash(city.model_dump()),
                }
            )
    if page.county_id:
        county = session.get(County, page.county_id)
        if county:
            sources.append(
                {
                    "type": "county",
                    "id": county.id,
                    "identity_sha256": _identity_hash(county.model_dump()),
                }
            )
    if page.page_type == "county" and page.county_id:
        try:
            county_context = build_county_page_context(
                session,
                website_id=website.id or page.website_id,
                site_plan_id=page.site_plan_id,
                county_id=page.county_id,
                service_id=page.service_id,
            )
        except CountyPageContractError:
            county_context = None
        if county_context is not None:
            sources.extend(county_context.approved_source_identities)
    for block in session.exec(
        select(KnowledgeBlock).where(
            KnowledgeBlock.business_id == website.business_id,
            KnowledgeBlock.status == "active",
        )
    ).all():
        if page.service_id is None or block.service_id == page.service_id:
            sources.append(
                {"type": "knowledge_block", "id": block.id, "updated_at": block.updated_at.isoformat()}
            )
    return sorted(sources, key=lambda item: (item["type"], item["id"] or 0))


def _upsert_distinctness_brief(
    session: Session,
    plan: SitePlan,
    website: Website,
    page: PlannedPage,
    record: PlanningRecord | None,
    pages: list[PlannedPage],
    *,
    generated_at: datetime,
) -> PreDraftDistinctnessBrief:
    answers = (
        {**record.generated_answers, **record.operator_overrides}
        if record is not None
        else {}
    )
    city = session.get(City, page.city_id) if page.city_id else None
    county_context = None
    if page.page_type == "county" and page.county_id:
        try:
            county_context = build_county_page_context(
                session,
                website_id=website.id or page.website_id,
                site_plan_id=plan.id or page.site_plan_id,
                county_id=page.county_id,
                service_id=page.service_id,
            )
        except CountyPageContractError:
            county_context = None
    sources = _approved_source_identities(session, website, page)
    audience = _string_list(answers.get("audiences") or answers.get("audience"))
    search_intent = str(answers.get("search_intent") or "").strip()
    if county_context is not None and county_context.has_approved_value:
        search_intent = county_context.search_intent
    elif not search_intent:
        service = session.get(Service, page.service_id) if page.service_id else None
        search_intent = " ".join(
            value
            for value in (
                page.page_type.replace("_", " "),
                service.service_name if service else "",
                city.city_name if city else "",
                str(answers.get("purpose") or ""),
            )
            if value
        ).strip()
    page_specific_value = [
        {
            "kind": "operator_approved_page_specific_value",
            "value": value,
            "approved": True,
            "source": "planning_record_operator_override",
        }
        for value in _string_list(answers.get("page_specific_value"))
    ]
    if county_context is not None:
        page_specific_value.extend(county_context.approved_values())
    if city and city.notes and city.notes.strip():
        page_specific_value.append(
            {
                "kind": "approved_city_note",
                "value": city.notes.strip(),
                "approved": True,
                "source": f"city:{city.id}",
            }
        )
    unique_elements: list[dict[str, Any]] = []
    for key, kind in (
        ("unique_sections", "proposed_unique_section"),
        ("unique_questions", "proposed_unique_question"),
    ):
        unique_elements.extend(
            {
                "kind": kind,
                "value": value,
                "source": "planning_record_operator_override",
            }
            for value in _string_list(answers.get(key))
        )
    if county_context is not None:
        unique_elements.extend(county_context.unique_elements())
    knowledge_sources = [
        item for item in sources if item["type"] == "knowledge_block"
    ]
    for identity_value in knowledge_sources:
        block = session.get(KnowledgeBlock, identity_value["id"])
        if block:
            unique_elements.append(
                {
                    "kind": "approved_knowledge",
                    "value": block.title,
                    "source": f"knowledge_block:{block.id}",
                }
            )
    related: list[int] = []
    competing: list[int] = []
    for other in pages:
        if other.id is None or other.id == page.id:
            continue
        if (
            (page.service_id and page.service_id == other.service_id)
            or (page.city_id and page.city_id == other.city_id)
            or (page.county_id and page.county_id == other.county_id)
            or page.parent_planned_page_id == other.id
            or other.parent_planned_page_id == page.id
        ):
            related.append(other.id)
        if other.page_type == page.page_type and (
            page.service_id == other.service_id
            or page.city_id == other.city_id
        ):
            competing.append(other.id)
    if county_context is not None:
        related.extend(county_context.related_service_page_ids)
        related.extend(county_context.related_city_service_page_ids)
        competing.extend(county_context.competing_county_page_ids)
    values: dict[str, Any] = {
        "website_id": website.id or 0,
        "site_plan_id": plan.id or page.site_plan_id,
        "planned_page_id": page.id or 0,
        "algorithm_version": BRIEF_ALGORITHM_VERSION,
        "intended_audience": audience,
        "search_intent": search_intent,
        "approved_fact_identities": [
            item for item in sources if item["type"] != "knowledge_block"
        ],
        "approved_knowledge_identities": knowledge_sources,
        "conversion_purpose": str(
            answers.get("primary_action")
            or answers.get("conversion_purpose")
            or ""
        ).strip(),
        "required_page_specific_value": page_specific_value,
        "proposed_unique_elements": unique_elements,
        "related_planned_page_ids": sorted(set(related)),
        "competing_planned_page_ids": sorted(set(competing)),
        "source_binding": {
            "planning_record": _planning_binding(record),
            "approved_sources": sources,
            "planned_page": {
                "id": page.id,
                "page_type": page.page_type,
                "intended_slug": page.intended_slug,
                "service_id": page.service_id,
                "city_id": page.city_id,
                "county_id": page.county_id,
                "updated_at": page.updated_at.isoformat(),
            },
        },
    }
    brief_hash = hashlib.sha256(
        json.dumps(values, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()
    existing = session.exec(
        select(PreDraftDistinctnessBrief).where(
            PreDraftDistinctnessBrief.planned_page_id == page.id
        )
    ).first()
    if existing is None:
        existing = PreDraftDistinctnessBrief(
            **values,
            brief_hash=brief_hash,
            generated_at=generated_at,
        )
    elif existing.brief_hash != brief_hash:
        for key, value in values.items():
            setattr(existing, key, value)
        existing.brief_hash = brief_hash
        existing.generated_at = generated_at
        existing.updated_at = generated_at
    session.add(existing)
    return existing


def _brief_binding(brief: PreDraftDistinctnessBrief) -> dict[str, Any]:
    return {
        "id": brief.id,
        "algorithm_version": brief.algorithm_version,
        "brief_hash": brief.brief_hash,
    }


def _local_value_findings(
    page: PlannedPage,
    brief: PreDraftDistinctnessBrief,
) -> list[dict[str, Any]]:
    if page.page_type not in {"city_service", "county"}:
        return [
            {
                "kind": "approved_source",
                "source": item,
                "explanation": "Approved Website information is bound to the brief.",
            }
            for item in brief.approved_fact_identities
        ]
    return [
        {
            **item,
            "explanation": (
                "Approved page-specific value distinguishes this local page "
                "beyond its coverage relationship or geographic name."
            ),
        }
        for item in brief.required_page_specific_value
        if item.get("approved") is True and str(item.get("value") or "").strip()
    ]


def _semantic_findings(
    session: Session,
    website: Website,
    page: PlannedPage,
    brief: PreDraftDistinctnessBrief,
    briefs: dict[int, PreDraftDistinctnessBrief],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    peers = session.exec(
        select(PlannedPage).where(
            PlannedPage.website_id == website.id,
            PlannedPage.id != page.id,
        )
    ).all()
    intent = _normalize(brief.search_intent)
    intent_geo_free = _without_geography(session, page, intent)
    local_values = {
        _normalize(str(item.get("value") or ""))
        for item in brief.required_page_specific_value
        if item.get("approved") is True
    }
    for peer in peers:
        peer_brief = briefs.get(peer.id or 0)
        if peer_brief:
            peer_intent = _normalize(peer_brief.search_intent)
            peer_intent_geo_free = _without_geography(
                session, peer, peer_intent
            )
            peer_local_values = {
                _normalize(str(item.get("value") or ""))
                for item in peer_brief.required_page_specific_value
                if item.get("approved") is True
            }
            if intent and intent == peer_intent:
                results.append(
                    {
                        "kind": "duplicate_intent",
                        "target_planned_page_id": peer.id,
                        "score": 1.0,
                        "explanation": (
                            "Both Planned Pages have the same deterministic search intent."
                        ),
                    }
                )
            if (
                page.page_type == "county"
                and peer.page_type == "county"
                and intent_geo_free
                and intent_geo_free == peer_intent_geo_free
                and (not local_values or not peer_local_values)
            ):
                results.append(
                    {
                        "kind": "geographic_substitution",
                        "target_planned_page_id": peer.id,
                        "score": 1.0,
                        "explanation": (
                            "The County intents differ only by geography and one or "
                            "both pages lack approved County-specific value."
                        ),
                    }
                )
            if (
                page.page_type == "city_service"
                and peer.page_type == "city_service"
                and page.service_id == peer.service_id
                and intent_geo_free
                and intent_geo_free == peer_intent_geo_free
                and (not local_values or not peer_local_values)
            ):
                results.append(
                    {
                        "kind": "geographic_substitution",
                        "target_planned_page_id": peer.id,
                        "score": 1.0,
                        "explanation": (
                            "The Service × City intents differ only by geography and "
                            "one or both pages lack approved page-specific value."
                        ),
                    }
                )
        current = _page_text(session, page)
        other = _page_text(session, peer)
        if not current or not other:
            continue
        normalized = _normalize(current)
        geo_free = _without_geography(session, page, normalized)
        other_normalized = _normalize(other)
        other_geo_free = _without_geography(session, peer, other_normalized)
        current_generated = session.get(GeneratedPage, page.generated_page_id)
        peer_generated = session.get(GeneratedPage, peer.generated_page_id)
        current_sections = _section_map(current_generated)
        peer_sections = _section_map(peer_generated)
        comparable_keys = set(current_sections) & set(peer_sections)
        shared_keys = [
            key
            for key in comparable_keys
            if current_sections[key] == peer_sections[key]
        ]
        shared_ratio = (
            len(shared_keys) / len(comparable_keys)
            if comparable_keys
            else 0.0
        )
        title_score = _similarity(
            current_generated.page_title if current_generated else "",
            peer_generated.page_title if peer_generated else "",
        )
        h1_score = _similarity(
            current_generated.h1 if current_generated else "",
            peer_generated.h1 if peer_generated else "",
        )
        intent_overlap = bool(
            page.page_type == peer.page_type
            and (
                (page.service_id and page.service_id == peer.service_id)
                or (page.city_id and page.city_id == peer.city_id)
                or (page.county_id and page.county_id == peer.county_id)
            )
        )
        if normalized == other_normalized:
            results.append(
                {
                    "kind": "exact_duplicate",
                    "target_planned_page_id": peer.id,
                    "score": 1.0,
                    "explanation": "The rendered draft is an exact duplicate of another Website page.",
                }
            )
        elif geo_free and geo_free == other_geo_free:
            results.append(
                {
                    "kind": "geographic_substitution",
                    "target_planned_page_id": peer.id,
                    "score": 1.0,
                    "explanation": "The rendered draft differs only by geographic substitution.",
                }
            )
        else:
            left, right = set(normalized.split()), set(other_normalized.split())
            score = len(left & right) / max(1, len(left | right))
            if score >= 0.9:
                results.append(
                    {
                        "kind": "near_duplicate",
                        "target_planned_page_id": peer.id,
                        "score": round(score, 4),
                        "explanation": "The rendered drafts have at least 90% token overlap.",
                    }
                )
        if shared_ratio >= 0.6:
            results.append(
                {
                    "kind": "shared_section_ratio",
                    "target_planned_page_id": peer.id,
                    "score": round(shared_ratio, 4),
                    "contributing_sections": sorted(shared_keys),
                    "explanation": "At least 60% of comparable draft sections are identical.",
                }
            )
        if max(title_score, h1_score) >= 0.9:
            results.append(
                {
                    "kind": "title_h1_similarity",
                    "target_planned_page_id": peer.id,
                    "title_score": round(title_score, 4),
                    "h1_score": round(h1_score, 4),
                    "explanation": "The title or H1 is at least 90% similar to another Website page.",
                }
            )
        if intent_overlap:
            results.append(
                {
                    "kind": "search_intent_overlap",
                    "target_planned_page_id": peer.id,
                    "relationships": {
                        "service": page.service_id == peer.service_id,
                        "city": page.city_id == peer.city_id,
                        "county": page.county_id == peer.county_id,
                    },
                    "explanation": "Related pages share an approved Service, City, or County intent boundary.",
                }
            )
        if intent_overlap and shared_ratio >= 0.6 and max(title_score, h1_score) >= 0.9:
            results.append(
                {
                    "kind": "likely_cannibalization",
                    "target_planned_page_id": peer.id,
                    "contributing_sections": sorted(shared_keys),
                    "explanation": "Related intent, headings, and shared sections indicate likely cannibalization.",
                }
            )
    unique: dict[tuple[str, int | None], dict[str, Any]] = {}
    for result in results:
        unique[(result["kind"], result.get("target_planned_page_id"))] = result
    return list(unique.values())


def _status(
    inventory_item: Any,
    record: PlanningRecord | None,
    local_findings: list[dict[str, Any]],
    semantic_findings: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    if inventory_item is None or inventory_item.disposition in {
        "excluded", "unsupported_extra", "unexplained_historical"
    }:
        return "excluded_by_coverage", [
            "The page is not explicitly included by the current Coverage Matrix."
        ]
    if inventory_item.disposition in {"deferred", "pending_decision"}:
        return "deferred", [inventory_item.reason]
    if inventory_item.disposition != "matching":
        return "blocked_missing_required_information", [inventory_item.reason]
    if record is None:
        return "blocked_missing_required_information", ["Planning Record is missing."]
    if record.missing_information:
        return "blocked_missing_required_information", list(record.missing_information)
    if inventory_item.page_type in {"city_service", "county"} and not local_findings:
        return "insufficient_local_value", [
            "Coverage relationships do not establish approved page-specific value "
            f"for this {inventory_item.page_type.replace('_', ' ').title()} page."
        ]
    if any(
        item["kind"] in {"exact_duplicate", "duplicate_intent"}
        for item in semantic_findings
    ):
        return "semantic_duplication", [
            "The page duplicates an existing Website page or approved search intent."
        ]
    if any(item["kind"] == "geographic_substitution" for item in semantic_findings):
        return "consolidation_recommended", [
            "Draft differs from another page only by geographic substitution."
        ]
    if any(item["kind"] == "likely_cannibalization" for item in semantic_findings):
        return "semantic_duplication", [
            "Related page intent, headings, and shared sections indicate likely cannibalization."
        ]
    if any(item["kind"] == "near_duplicate" for item in semantic_findings):
        return "semantic_duplication", ["Draft content is semantically near-duplicate."]
    return "eligible", ["Current approved inputs support drafting."]


def _page_text(session: Session, page: PlannedPage) -> str:
    generated = (
        session.get(GeneratedPage, page.generated_page_id)
        if page.generated_page_id
        else None
    )
    if not generated:
        return ""
    return " ".join(
        value
        for value in (
            generated.page_title,
            generated.h1 or "",
            generated.content_body or "",
            json.dumps(generated.draft_content or {}, sort_keys=True),
        )
        if value
    )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _section_map(page: GeneratedPage | None) -> dict[str, str]:
    if page is None or not isinstance(page.draft_content, dict):
        return {}
    return {
        key: normalized
        for key, value in page.draft_content.items()
        if key not in {"title", "meta_title", "meta_description", "h1", "status"}
        and (normalized := _normalize(json.dumps(value, sort_keys=True)))
    }


def _similarity(left: str | None, right: str | None) -> float:
    left_value, right_value = _normalize(left or ""), _normalize(right or "")
    if not left_value or not right_value:
        return 0.0
    return SequenceMatcher(None, left_value, right_value).ratio()


def _without_geography(
    session: Session, page: PlannedPage, value: str
) -> str:
    names: list[str] = []
    if page.city_id:
        city = session.get(City, page.city_id)
        if city:
            names.append(city.city_name)
    if page.county_id:
        county = session.get(County, page.county_id)
        if county:
            names.append(county.county_name)
    result = value
    for name in names:
        result = re.sub(rf"\b{re.escape(_normalize(name))}\b", "<geography>", result)
    return result


def _batch_manifest(
    website_id: int,
    site_plan_id: int,
    inventory: Any,
    assessments: list[EligibilityAssessmentRead],
) -> DraftingBatchManifest:
    by_page = {item.planned_page_id: item for item in assessments}
    items: list[DraftingBatchManifestItem] = []
    counts = DraftingBatchManifestCounts()
    blockers: list[str] = []
    for inventory_item in inventory.items:
        assessment = (
            by_page.get(inventory_item.planned_page_id)
            if inventory_item.planned_page_id is not None
            else None
        )
        if inventory_item.disposition in {
            "excluded",
            "unsupported_extra",
            "unexplained_historical",
        }:
            classification = "excluded"
        elif inventory_item.disposition == "deferred":
            classification = "deferred"
        elif inventory_item.disposition != "matching":
            classification = "blocked"
        elif assessment is None or not assessment.current:
            classification = "stale"
        elif assessment.effective_eligible:
            classification = "eligible"
        elif assessment.status == "consolidation_recommended":
            classification = "consolidation_recommended"
        elif assessment.status == "deferred":
            classification = "deferred"
        elif assessment.status == "excluded_by_coverage":
            classification = "excluded"
        else:
            classification = "blocked"
        setattr(counts, classification, getattr(counts, classification) + 1)
        reasons = (
            list(assessment.reasons)
            if assessment is not None
            else [inventory_item.reason]
        )
        items.append(
            DraftingBatchManifestItem(
                inventory_key=inventory_item.inventory_key,
                planned_page_id=inventory_item.planned_page_id,
                page_type=inventory_item.page_type,
                working_name=inventory_item.working_name,
                classification=classification,
                assessment_status=assessment.status if assessment else None,
                current=assessment.current if assessment else False,
                effective_eligible=(
                    assessment.effective_eligible if assessment else False
                ),
                reasons=reasons,
            )
        )
        if classification in {"blocked", "stale", "consolidation_recommended"}:
            blockers.append(
                f"{inventory_item.working_name}: {classification} "
                f"({'; '.join(reasons)})"
            )
    return DraftingBatchManifest(
        website_id=website_id,
        site_plan_id=site_plan_id,
        items=items,
        counts=counts,
        preview_ready=not blockers and counts.eligible > 0,
        blocking_reasons=blockers,
    )


def require_effective_drafting_eligibility(
    session: Session,
    planned_page_id: int,
    *,
    operation: str = "draft",
) -> EligibilityAssessmentRead:
    page = session.get(PlannedPage, planned_page_id)
    if page is None:
        raise DraftingEligibilityError("Planned Page not found.")
    manifest = read_manifest(session, page.site_plan_id)
    assessment = next(
        (
            item
            for item in manifest.assessments
            if item.planned_page_id == planned_page_id
        ),
        None,
    )
    if assessment is None:
        raise DraftingEligibilityError(
            f"{operation} blocked: no pre-draft eligibility assessment exists."
        )
    if not assessment.current:
        raise DraftingEligibilityError(
            f"{operation} blocked: pre-draft eligibility is stale."
        )
    if not assessment.effective_eligible:
        raise DraftingEligibilityError(
            f"{operation} blocked by {assessment.status}: "
            f"{'; '.join(assessment.reasons)}"
        )
    return assessment


def validate_candidate_drafts(
    session: Session,
    plan_id: int,
    candidates: list[CandidateDraftInput],
) -> CandidateDraftValidationResult:
    plan, website = _scope(session, plan_id)
    findings: list[CandidateDraftValidationFinding] = []
    normalized_candidates: dict[int, str] = {}
    for candidate in candidates:
        page = session.get(PlannedPage, candidate.planned_page_id)
        if (
            page is None
            or page.site_plan_id != plan_id
            or page.website_id != website.id
        ):
            findings.append(
                CandidateDraftValidationFinding(
                    kind="website_scope",
                    planned_page_id=candidate.planned_page_id,
                    explanation="Candidate Planned Page is outside the requested Website.",
                )
            )
            continue
        try:
            require_effective_drafting_eligibility(
                session, page.id or 0, operation="candidate validation"
            )
        except DraftingEligibilityError as exc:
            findings.append(
                CandidateDraftValidationFinding(
                    kind="eligibility",
                    planned_page_id=page.id or 0,
                    explanation=str(exc),
                )
            )
        if page.generated_page_id and not (
            candidate.replacement_approved
            and str(candidate.replacement_approved_by or "").strip()
            and str(candidate.replacement_rationale or "").strip()
        ):
            findings.append(
                CandidateDraftValidationFinding(
                    kind="replacement_not_approved",
                    planned_page_id=page.id or 0,
                    explanation=(
                        "An existing draft cannot be replaced without explicit "
                        "operator approval, provenance, and rationale."
                    ),
                )
            )
        probe = GeneratedPage(
            business_id=website.business_id,
            website_id=website.id,
            service_id=page.service_id,
            city_id=page.city_id,
            county_id=page.county_id,
            page_type=page.page_type,
            page_title=str(candidate.draft_content.get("title") or page.working_name),
            page_slug=page.intended_slug,
        )
        for error in validate_draft_contract(probe, candidate.draft_content):
            findings.append(
                CandidateDraftValidationFinding(
                    kind="page_type_contract",
                    planned_page_id=page.id or 0,
                    explanation=error["message"],
                    evidence={"field": error["field"]},
                )
            )
        normalized_candidates[page.id or 0] = _normalize(
            json.dumps(candidate.draft_content, sort_keys=True)
        )
    candidate_ids = sorted(normalized_candidates)
    for index, left_id in enumerate(candidate_ids):
        for right_id in candidate_ids[index + 1 :]:
            left = normalized_candidates[left_id]
            right = normalized_candidates[right_id]
            score = _token_overlap(left, right)
            if left == right or score >= 0.9:
                findings.append(
                    CandidateDraftValidationFinding(
                        kind=(
                            "candidate_duplicate"
                            if left == right
                            else "candidate_near_duplicate"
                        ),
                        planned_page_id=left_id,
                        target_planned_page_id=right_id,
                        explanation=(
                            "Candidate drafts are exact semantic duplicates."
                            if left == right
                            else "Candidate drafts have at least 90% token overlap."
                        ),
                        evidence={"score": round(1.0 if left == right else score, 4)},
                    )
                )
    candidate_id_set = set(candidate_ids)
    existing_pages = session.exec(
        select(PlannedPage).where(
            PlannedPage.website_id == website.id,
            PlannedPage.generated_page_id.is_not(None),
        )
    ).all()
    for candidate_id, candidate_text in normalized_candidates.items():
        candidate_page = session.get(PlannedPage, candidate_id)
        if candidate_page is None:
            continue
        candidate_geo_free = _without_geography(
            session, candidate_page, candidate_text
        )
        for existing_page in existing_pages:
            if existing_page.id in candidate_id_set:
                continue
            existing_text = _normalize(_page_text(session, existing_page))
            if not existing_text:
                continue
            score = _token_overlap(candidate_text, existing_text)
            kind: str | None = None
            explanation = ""
            if candidate_text == existing_text:
                kind = "candidate_existing_duplicate"
                explanation = "Candidate exactly duplicates an existing Website draft."
            elif (
                candidate_geo_free
                and candidate_geo_free
                == _without_geography(session, existing_page, existing_text)
            ):
                kind = "candidate_existing_geographic_substitution"
                explanation = (
                    "Candidate differs from an existing Website draft only by geography."
                )
            elif score >= 0.9:
                kind = "candidate_existing_near_duplicate"
                explanation = (
                    "Candidate has at least 90% token overlap with an existing "
                    "Website draft."
                )
            if kind:
                findings.append(
                    CandidateDraftValidationFinding(
                        kind=kind,
                        planned_page_id=candidate_id,
                        target_planned_page_id=existing_page.id,
                        explanation=explanation,
                        evidence={"score": round(score, 4)},
                    )
                )
    return CandidateDraftValidationResult(
        website_id=website.id or 0,
        site_plan_id=plan.id or plan_id,
        valid=not findings,
        findings=findings,
    )


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        values = value.values()
    elif isinstance(value, list):
        values = value
    else:
        values = [value]
    return [
        str(item).strip()
        for item in values
        if str(item).strip()
    ]


def _token_overlap(left: str, right: str) -> float:
    left_tokens, right_tokens = set(left.split()), set(right.split())
    return len(left_tokens & right_tokens) / max(
        1, len(left_tokens | right_tokens)
    )


def _identity_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
