from copy import deepcopy
from datetime import UTC, datetime
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

    revision = append_generated_page_revision(
        session,
        page,
        before=before,
        after=merged,
        changed_fields=changed_fields,
        rendered_content=rendered_content,
        created_by=(payload.created_by or "").strip() or None,
        reason=(payload.reason or "").strip() or None,
    )

    qa_result = save_page_qa(session, page_id, commit=False) if run_qa else None
    session.commit()
    session.refresh(page)
    session.refresh(revision)
    return page, revision, qa_result


def append_generated_page_revision(
    session: Session,
    page: GeneratedPage,
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    changed_fields: list[str],
    rendered_content: str,
    created_by: str | None,
    reason: str | None,
    changed_at: datetime | None = None,
) -> GeneratedPageRevision:
    """Append one normal draft revision without owning the caller transaction.

    The caller must lock and validate ``page`` before calling this low-level
    persistence seam.  Keeping the commit boundary outside this function lets
    governed batch operations reuse the same revision shape atomically while
    preserving the existing manual editor's behavior.
    """

    page_id = page.id
    if page_id is None:
        raise RuntimeError("Generated Page revision requires a persisted page.")
    if not changed_fields:
        raise RuntimeError("Generated Page revision requires at least one changed field.")
    before_hash = draft_content_hash(before)
    after_hash = draft_content_hash(after)
    if (
        not isinstance(page.draft_content, dict)
        or draft_content_hash(page.draft_content) != before_hash
    ):
        raise RuntimeError("Generated Page revision before-state differs from the locked page.")
    if before_hash == after_hash:
        raise RuntimeError("Generated Page revision requires a changed draft hash.")
    changed_at = changed_at or datetime.now(UTC)
    revision = GeneratedPageRevision(
        generated_page_id=page_id,
        created_at=changed_at,
        created_by=created_by,
        reason=reason,
        draft_hash_before=before_hash,
        draft_hash_after=after_hash,
        draft_content_before=deepcopy(before),
        draft_content_after=deepcopy(after),
        changed_fields=list(changed_fields),
    )

    page.draft_content = deepcopy(after)
    page.h1 = after["h1"]
    page.page_title = after["title"]
    page.meta_title = after["meta_title"]
    page.meta_description = after["meta_description"]
    page.content_body = rendered_content
    page.qa_status = "not_run"
    page.qa_result = None
    page.qa_checked_at = None
    page.updated_at = changed_at
    session.add(page)
    session.add(revision)
    session.flush()
    return revision


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
