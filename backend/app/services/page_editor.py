from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import GeneratedPage, GeneratedPageRevision, PlannedPage
from app.schemas.generation import DraftContent
from app.schemas.page_editor import ManualDraftSaveRequest
from app.schemas.qa import PageQAResult
from app.schemas.site_plans import PlannedPageDraftContent
from app.services.approval_audit import draft_content_hash
from app.services.draft_generation import (
    UnsafeContentError,
    render_content_body,
    validate_safe_content,
)
from app.services.drafting_eligibility import (
    DraftingEligibilityError,
    require_effective_drafting_eligibility,
)
from app.services.page_qa import save_page_qa
from app.services.page_type_review import review_contract_for, validate_draft_contract
from app.services.planned_page_drafting import render_planned_page_content
from app.services.website_context import build_website_context


EDITABLE_FIELD_MAP = {
    "hero_headline": "h1",
    "hero_subheadline": "hero_subheadline",
    "intro": "intro",
    "service_explanation": "service_explanation",
    "local_city_section": "local_city_section",
    "process_section": "process_section",
    "prep_reentry_section": "prep_section",
    "why_choose_section": "why_choose_section",
    "faq_items": "faq_items",
    "call_to_action": "call_to_action",
}

REQUIRED_DRAFT_FIELDS = (
    "title",
    "meta_title",
    "meta_description",
    "h1",
    "intro",
    "why_it_matters",
    "signs_section",
    "process_section",
    "prep_section",
    "realtor_property_manager_section",
    "call_to_action",
    "internal_notes",
    "status",
)


MANIFEST_BOUND_FULL_DRAFT_REVISION_REASON_PREFIX = (
    "Public-copy reconciliation manifest sha256:"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ManifestBoundFullDraftRevisionAuthority:
    """Exact internal authority for one sealed content-reconciliation write.

    Ordinary generation and editing continue to require a current effective
    pre-draft eligibility assessment.  This authority is deliberately more
    specific than a boolean bypass: it binds one manifest, Website, Site Plan,
    Planned Page, Generated Page, predecessor, successor, actor, reason,
    Planned/Generated statuses, changed-field projection, and participation in
    the caller-owned transaction.
    """

    manifest_file_sha256: str
    website_id: int
    site_plan_id: int
    planned_page_id: int
    generated_page_id: int
    expected_current_hash: str
    expected_new_hash: str
    actor: str
    reason: str
    planned_page_status: str
    generated_page_status: str
    expected_changed_fields: tuple[str, ...]


def _require_manifest_bound_full_draft_revision_authority(
    authority: ManifestBoundFullDraftRevisionAuthority,
    *,
    page: GeneratedPage,
    planned_page: PlannedPage,
    expected_current_hash: str,
    candidate_hash: str,
    actor: str,
    reason: str,
    allowed_page_statuses: frozenset[str],
    expected_changed_fields: list[str] | None,
    commit: bool,
) -> None:
    if not isinstance(authority, ManifestBoundFullDraftRevisionAuthority):
        raise HTTPException(
            status_code=409,
            detail=(
                "Manifest-bound full-draft revision authority does not match "
                "the exact locked revision scope."
            ),
        )
    manifest_sha256 = authority.manifest_file_sha256
    expected_reason = (
        f"{MANIFEST_BOUND_FULL_DRAFT_REVISION_REASON_PREFIX}{manifest_sha256}"
    )
    normalized_changed_fields = (
        tuple(sorted(set(expected_changed_fields)))
        if expected_changed_fields is not None
        else None
    )
    valid = bool(
        _SHA256_PATTERN.fullmatch(manifest_sha256)
        and authority.website_id == page.website_id == planned_page.website_id
        and authority.site_plan_id == planned_page.site_plan_id
        and authority.planned_page_id == planned_page.id
        and authority.generated_page_id == page.id
        and authority.expected_current_hash == expected_current_hash
        and authority.expected_new_hash == candidate_hash
        and authority.actor == actor
        and authority.reason == reason == expected_reason
        and authority.planned_page_status == planned_page.planning_status
        and authority.generated_page_status == page.status
        and allowed_page_statuses == frozenset({authority.generated_page_status})
        and normalized_changed_fields is not None
        and authority.expected_changed_fields == normalized_changed_fields
        and commit is False
    )
    if not valid:
        raise HTTPException(
            status_code=409,
            detail=(
                "Manifest-bound full-draft revision authority does not match "
                "the exact locked revision scope."
            ),
        )


def save_full_draft_revision(
    session: Session,
    page_id: int,
    candidate_draft: dict[str, Any],
    *,
    expected_current_hash: str,
    created_by: str,
    reason: str,
    allowed_page_statuses: frozenset[str] = frozenset({"draft"}),
    expected_changed_fields: list[str] | None = None,
    manifest_bound_authority: ManifestBoundFullDraftRevisionAuthority | None = None,
    commit: bool = True,
) -> tuple[GeneratedPage, GeneratedPageRevision]:
    """Append one exact Generated Page revision without weakening edit routes.

    This internal primitive is the canonical transaction-composable writer for
    already-built full draft payloads.  Callers must bind the exact predecessor
    hash and explicitly name every non-draft status they are authorized to
    preserve.  Manual-edit APIs continue to use their narrower editable-field
    contract and draft-only gate.
    """

    page = session.exec(
        select(GeneratedPage)
        .where(GeneratedPage.id == page_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="Generated page not found")
    if page.status not in allowed_page_statuses:
        raise HTTPException(
            status_code=409,
            detail="Generated Page status is outside the authorized full-draft revision scope.",
        )
    if not page.draft_content:
        raise HTTPException(
            status_code=409,
            detail="Generate a structured draft before creating a revision.",
        )
    actor = created_by.strip()
    revision_reason = reason.strip()
    if not actor or not revision_reason:
        raise HTTPException(
            status_code=422,
            detail="Full-draft revision actor and reason are required.",
        )
    planned_page = session.exec(
        select(PlannedPage).where(PlannedPage.generated_page_id == page.id)
    ).one_or_none()
    if planned_page is None:
        raise HTTPException(
            status_code=409,
            detail="Generated Page is not owned by exactly one Planned Page.",
        )
    if manifest_bound_authority is None:
        try:
            require_effective_drafting_eligibility(
                session,
                planned_page.id or 0,
                operation="full-draft revision",
            )
        except DraftingEligibilityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    before = deepcopy(page.draft_content)
    observed_before_hash = draft_content_hash(before)
    if observed_before_hash != expected_current_hash:
        raise HTTPException(
            status_code=409,
            detail="Generated Page content changed after full-draft revision preflight.",
        )
    candidate = deepcopy(candidate_draft)
    candidate_hash = draft_content_hash(candidate)
    if manifest_bound_authority is not None:
        _require_manifest_bound_full_draft_revision_authority(
            manifest_bound_authority,
            page=page,
            planned_page=planned_page,
            expected_current_hash=expected_current_hash,
            candidate_hash=candidate_hash,
            actor=actor,
            reason=revision_reason,
            allowed_page_statuses=allowed_page_statuses,
            expected_changed_fields=expected_changed_fields,
            commit=commit,
        )
    if candidate_hash == observed_before_hash:
        raise HTTPException(
            status_code=400,
            detail="An identical draft cannot create an empty Generated Page revision.",
        )
    contract = review_contract_for(page)
    errors = validate_draft_contract(page, candidate)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Draft validation failed.", "errors": errors},
        )
    try:
        validate_safe_content(candidate)
    except UnsafeContentError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Draft contains unsafe wording.",
                "errors": [{"field": "safety_wording", "message": str(exc)}],
            },
        ) from exc
    if contract.schema == "planned-page-draft-v1":
        rendered_content = render_planned_page_content(
            PlannedPageDraftContent.model_validate(candidate)
        )
    else:
        rendered_content = render_content_body(
            DraftContent.model_validate(candidate),
            build_website_context(session, page_id=page_id),
        )
    changed_fields = sorted(
        key
        for key in set(before) | set(candidate)
        if before.get(key) != candidate.get(key)
    )
    if not changed_fields:
        raise HTTPException(
            status_code=400,
            detail="An identical draft cannot create an empty Generated Page revision.",
        )
    if expected_changed_fields is not None and changed_fields != sorted(
        set(expected_changed_fields)
    ):
        raise HTTPException(
            status_code=409,
            detail="Generated Page changed-field projection differs from the sealed correction manifest.",
        )

    changed_at = datetime.now(UTC)
    revision = GeneratedPageRevision(
        generated_page_id=page.id or page_id,
        created_at=changed_at,
        created_by=actor,
        reason=revision_reason,
        draft_hash_before=observed_before_hash,
        draft_hash_after=candidate_hash,
        draft_content_before=before,
        draft_content_after=deepcopy(candidate),
        changed_fields=changed_fields,
    )
    page.draft_content = candidate
    page.h1 = candidate["h1"]
    page.page_title = candidate["title"]
    page.meta_title = candidate["meta_title"]
    page.meta_description = candidate["meta_description"]
    page.content_body = rendered_content
    page.qa_status = "not_run"
    page.qa_result = None
    page.qa_checked_at = None
    page.updated_at = changed_at
    session.add(page)
    session.add(revision)
    session.flush()
    if commit:
        session.commit()
        session.refresh(page)
        session.refresh(revision)
    return page, revision


def save_manual_draft(
    session: Session,
    page_id: int,
    payload: ManualDraftSaveRequest,
    *,
    run_qa: bool = False,
) -> tuple[GeneratedPage, GeneratedPageRevision, PageQAResult | None]:
    page = session.exec(
        select(GeneratedPage)
        .where(GeneratedPage.id == page_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    if page.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft pages can be edited")
    if not page.draft_content:
        raise HTTPException(status_code=409, detail="Generate a structured draft before editing")
    planned_page = session.exec(
        select(PlannedPage).where(PlannedPage.generated_page_id == page.id)
    ).first()
    if planned_page is None:
        raise HTTPException(
            status_code=409,
            detail="Draft editing blocked: Generated Page is not owned by a Planned Page.",
        )
    try:
        require_effective_drafting_eligibility(
            session,
            planned_page.id or 0,
            operation="draft editing",
        )
    except DraftingEligibilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    before = deepcopy(page.draft_content)
    contract = review_contract_for(page)
    if contract.schema == "planned-page-draft-v1":
        merged = _normalized_planned_draft(page, before, payload.draft)
        changed_fields = [
            field
            for field in (
                "title",
                "meta_title",
                "meta_description",
                "h1",
                "intro",
                "sections",
                "faq_items",
                "call_to_action",
            )
            if _normalized_value(before.get(field))
            != _normalized_value(merged.get(field))
        ]
        rendered_content = render_planned_page_content(
            PlannedPageDraftContent.model_validate(merged)
        )
    else:
        editable = _normalized_editable_fields(payload.draft)
        merged = _merge_editable_fields(before, editable)
        _validate_merged_draft(merged)
        changed_fields = [
            field
            for field, draft_key in EDITABLE_FIELD_MAP.items()
            if _normalized_value(before.get(draft_key))
            != _normalized_value(merged.get(draft_key))
        ]
        rendered_content = render_content_body(
            DraftContent.model_validate(merged),
            build_website_context(session, page_id=page_id),
        )
    if not changed_fields:
        raise HTTPException(status_code=400, detail="No draft changes were provided")

    changed_at = datetime.now(UTC)
    revision = GeneratedPageRevision(
        generated_page_id=page.id or page_id,
        created_at=changed_at,
        created_by=(payload.created_by or "").strip() or None,
        reason=(payload.reason or "").strip() or None,
        draft_hash_before=draft_content_hash(before),
        draft_hash_after=draft_content_hash(merged),
        draft_content_before=before,
        draft_content_after=deepcopy(merged),
        changed_fields=changed_fields,
    )

    page.draft_content = merged
    page.h1 = merged["h1"]
    page.page_title = merged["title"]
    page.meta_title = merged["meta_title"]
    page.meta_description = merged["meta_description"]
    page.content_body = rendered_content
    page.qa_status = "not_run"
    page.qa_result = None
    page.qa_checked_at = None
    page.updated_at = changed_at
    session.add(page)
    session.add(revision)
    session.flush()

    qa_result = save_page_qa(session, page_id, commit=False) if run_qa else None
    session.commit()
    session.refresh(page)
    session.refresh(revision)
    return page, revision, qa_result


def _normalized_editable_fields(raw: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    normalized: dict[str, Any] = {}
    missing = sorted(set(EDITABLE_FIELD_MAP) - set(raw))
    errors.extend(
        {
            "field": field,
            "message": f"{field.replace('_', ' ').title()} is required.",
        }
        for field in missing
    )
    unexpected = sorted(set(raw) - set(EDITABLE_FIELD_MAP))
    errors.extend(
        {"field": field, "message": "This field is not editable."}
        for field in unexpected
    )
    for field, value in raw.items():
        if field not in EDITABLE_FIELD_MAP:
            continue
        if field == "faq_items":
            if not isinstance(value, list):
                errors.append({"field": field, "message": "FAQ items must be a list."})
                continue
            faq_items = []
            for index, item in enumerate(value):
                question = item["question"].strip()
                answer = item["answer"].strip()
                if not question:
                    errors.append({"field": f"faq_items.{index}.question", "message": "FAQ question is required."})
                if not answer:
                    errors.append({"field": f"faq_items.{index}.answer", "message": "FAQ answer is required."})
                faq_items.append({"question": question, "answer": answer})
            if not faq_items:
                errors.append({"field": "faq_items", "message": "At least one FAQ is required."})
            normalized[field] = faq_items
        else:
            text = value.strip() if isinstance(value, str) else ""
            if not text:
                errors.append({"field": field, "message": f"{field.replace('_', ' ').title()} is required."})
            normalized[field] = text
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Draft validation failed.", "errors": errors},
        )
    return normalized


def _normalized_planned_draft(
    page: GeneratedPage,
    before: dict[str, Any],
    raw: dict[str, Any],
) -> dict[str, Any]:
    editable_fields = {
        "title",
        "meta_title",
        "meta_description",
        "h1",
        "intro",
        "sections",
        "faq_items",
        "call_to_action",
    }
    unexpected = sorted(set(raw) - editable_fields)
    if unexpected:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Draft validation failed.",
                "errors": [
                    {
                        "field": field,
                        "message": "This field is not editable for the planned-page contract.",
                    }
                    for field in unexpected
                ],
            },
        )
    merged = deepcopy(before)
    for field in editable_fields:
        if field in raw:
            merged[field] = deepcopy(raw[field])
    errors = validate_draft_contract(page, merged)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Draft validation failed.", "errors": errors},
        )
    try:
        validate_safe_content(merged)
    except UnsafeContentError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Draft contains unsafe wording.",
                "errors": [{"field": "safety_wording", "message": str(exc)}],
            },
        ) from exc
    return merged


def _merge_editable_fields(before: dict[str, Any], editable: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(before)
    for field, draft_key in EDITABLE_FIELD_MAP.items():
        merged[draft_key] = deepcopy(editable[field])
    merged["why_it_matters"] = editable["service_explanation"]
    return merged


def _validate_merged_draft(merged: dict[str, Any]) -> None:
    errors = [
        {"field": field, "message": f"{field.replace('_', ' ').title()} is required."}
        for field in REQUIRED_DRAFT_FIELDS
        if not isinstance(merged.get(field), str) or not merged[field].strip()
    ]
    faqs = merged.get("faq_items")
    if not isinstance(faqs, list) or not faqs:
        errors.append({"field": "faq_items", "message": "At least one FAQ is required."})
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Draft validation failed.", "errors": errors},
        )
    try:
        validate_safe_content(merged)
    except UnsafeContentError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Draft contains unsafe wording.",
                "errors": [{"field": "safety_wording", "message": str(exc)}],
            },
        ) from exc


def _normalized_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value
