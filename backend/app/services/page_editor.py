from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session

from app.models import GeneratedPage, GeneratedPageRevision
from app.schemas.generation import DraftContent
from app.schemas.page_editor import ManualDraftSaveRequest
from app.schemas.qa import PageQAResult
from app.services.approval_audit import draft_content_hash
from app.services.draft_generation import (
    UnsafeContentError,
    render_content_body,
    validate_safe_content,
)
from app.services.page_qa import save_page_qa


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
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    if page.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft pages can be edited")
    if not page.draft_content:
        raise HTTPException(status_code=409, detail="Generate a structured draft before editing")

    before = deepcopy(page.draft_content)
    editable = _normalized_editable_fields(payload)
    merged = _merge_editable_fields(before, editable)
    _validate_merged_draft(merged)

    changed_fields = [
        field
        for field, draft_key in EDITABLE_FIELD_MAP.items()
        if _normalized_value(before.get(draft_key)) != _normalized_value(merged.get(draft_key))
    ]
    if not changed_fields:
        raise HTTPException(status_code=400, detail="No draft changes were provided")

    validated_draft = DraftContent.model_validate(merged)
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
    page.content_body = render_content_body(validated_draft)
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


def _normalized_editable_fields(payload: ManualDraftSaveRequest) -> dict[str, Any]:
    raw = payload.draft.model_dump(mode="json")
    errors: list[dict[str, str]] = []
    normalized: dict[str, Any] = {}
    for field, value in raw.items():
        if field == "faq_items":
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
            text = value.strip()
            if not text:
                errors.append({"field": field, "message": f"{field.replace('_', ' ').title()} is required."})
            normalized[field] = text
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Draft validation failed.", "errors": errors},
        )
    return normalized


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
