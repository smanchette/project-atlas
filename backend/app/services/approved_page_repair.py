from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import GeneratedPage, GeneratedPageRevision, WordPressDraftAudit, WordPressQualityReview
from app.schemas.generation import DraftContent
from app.schemas.page_editor import (
    ApprovedPageRepairRequest,
    ApprovedPageRepairResponse,
)
from app.services.approval_audit import draft_content_hash
from app.services.draft_generation import (
    UnsafeContentError,
    render_content_body,
    validate_safe_content,
)
from app.services.page_export import build_page_export_package
from app.services.page_qa import save_page_qa
from app.services.wordpress_sandbox import build_wordpress_payload_preview

REPAIRABLE_FIELDS = (
    "intro",
    "why_it_matters",
    "realtor_property_manager_section",
    "faq_items",
    "internal_notes",
)


def repair_approved_page(
    session: Session,
    page_id: int,
    payload: ApprovedPageRepairRequest,
) -> ApprovedPageRepairResponse:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    if page.status != "approved":
        raise HTTPException(status_code=409, detail="Only approved pages can use the repair workflow")
    if page.wordpress_post_id is None:
        raise HTTPException(status_code=409, detail="Approved repair requires an existing WordPress draft reference")
    if not page.draft_content:
        raise HTTPException(status_code=409, detail="Structured draft content is required before repair")

    wordpress_refs_before = _wordpress_refs(page)
    audit_count_before = _wordpress_audit_count(session, page_id)
    before = deepcopy(page.draft_content)
    payload_hash_before = _current_payload_hash(session, page_id)
    merged, changed_fields = _merge_repair_fields(before, payload)
    if not changed_fields:
        raise HTTPException(status_code=400, detail="No repair changes were provided")
    _validate_repaired_draft(merged)

    repaired_at = datetime.now(UTC)
    revision = GeneratedPageRevision(
        generated_page_id=page.id or page_id,
        created_at=repaired_at,
        created_by=(payload.repaired_by or "").strip() or None,
        reason=(payload.reason or "").strip() or "Approved page Atlas-only repair",
        draft_hash_before=draft_content_hash(before),
        draft_hash_after=draft_content_hash(merged),
        draft_content_before=before,
        draft_content_after=deepcopy(merged),
        changed_fields=changed_fields,
    )

    validated_draft = DraftContent.model_validate(merged)
    page.draft_content = merged
    page.content_body = render_content_body(validated_draft)
    page.h1 = merged["h1"]
    page.qa_status = "not_run"
    page.qa_result = None
    page.qa_checked_at = None
    page.updated_at = repaired_at
    session.add(page)
    session.add(revision)
    session.flush()

    qa_result = save_page_qa(session, page_id, commit=False)
    export_package = build_page_export_package(session, page_id)
    payload_hash_after = _current_payload_hash(session, page_id)
    _update_manual_review_note(session, page, payload, repaired_at)

    _assert_safety_invariants(
        session,
        page,
        page_id,
        wordpress_refs_before=wordpress_refs_before,
        audit_count_before=audit_count_before,
    )
    session.commit()
    session.refresh(page)
    session.refresh(revision)

    return ApprovedPageRepairResponse(
        page=page,
        revision=revision,
        qa_result=qa_result,
        export_ready=export_package.export_ready,
        export_blocker_count=sum(warning.severity == "blocker" for warning in export_package.warnings),
        export_warning_count=sum(warning.severity == "warning" for warning in export_package.warnings),
        export_warnings=[warning.model_dump(mode="json") for warning in export_package.warnings],
        draft_hash_before=revision.draft_hash_before,
        draft_hash_after=revision.draft_hash_after,
        payload_hash_before=payload_hash_before,
        payload_hash_after=payload_hash_after,
        wordpress_post_id=page.wordpress_post_id,
        wordpress_status=page.wordpress_status,
        wordpress_url=page.wordpress_url,
    )


def _merge_repair_fields(
    before: dict[str, Any],
    payload: ApprovedPageRepairRequest,
) -> tuple[dict[str, Any], list[str]]:
    raw = payload.draft.model_dump(mode="json", exclude_unset=True)
    merged = deepcopy(before)
    changed_fields: list[str] = []
    errors: list[dict[str, str]] = []
    for field, value in raw.items():
        if field not in REPAIRABLE_FIELDS:
            continue
        if field == "faq_items":
            normalized = _normalize_faq_items(value, errors)
        else:
            normalized = _normalize_text(field, value, errors)
        if errors:
            continue
        if _normalized_value(merged.get(field)) != _normalized_value(normalized):
            merged[field] = deepcopy(normalized)
            changed_fields.append(field)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Repair validation failed.", "errors": errors},
        )
    return merged, changed_fields


def _normalize_text(field: str, value: Any, errors: list[dict[str, str]]) -> str:
    if not isinstance(value, str):
        errors.append({"field": field, "message": f"{field.replace('_', ' ').title()} must be text."})
        return ""
    stripped = value.strip()
    if not stripped:
        errors.append({"field": field, "message": f"{field.replace('_', ' ').title()} is required when supplied."})
    return stripped


def _normalize_faq_items(value: Any, errors: list[dict[str, str]]) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        errors.append({"field": "faq_items", "message": "At least one FAQ item is required when FAQs are supplied."})
        return []
    normalized = []
    for index, item in enumerate(value):
        question = item.get("question", "").strip() if isinstance(item, dict) else ""
        answer = item.get("answer", "").strip() if isinstance(item, dict) else ""
        if not question:
            errors.append({"field": f"faq_items.{index}.question", "message": "FAQ question is required."})
        if not answer:
            errors.append({"field": f"faq_items.{index}.answer", "message": "FAQ answer is required."})
        normalized.append({"question": question, "answer": answer})
    return normalized


def _validate_repaired_draft(draft: dict[str, Any]) -> None:
    try:
        DraftContent.model_validate(draft)
        validate_safe_content(draft)
    except UnsafeContentError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Draft contains unsafe wording.",
                "errors": [{"field": "safety_wording", "message": str(exc)}],
            },
        ) from exc


def _wordpress_refs(page: GeneratedPage) -> tuple[int | None, str | None, str | None]:
    return page.wordpress_post_id, page.wordpress_status, page.wordpress_url


def _wordpress_audit_count(session: Session, page_id: int) -> int:
    return len(
        session.exec(
            select(WordPressDraftAudit).where(WordPressDraftAudit.generated_page_id == page_id)
        ).all()
    )


def _assert_safety_invariants(
    session: Session,
    page: GeneratedPage,
    page_id: int,
    *,
    wordpress_refs_before: tuple[int | None, str | None, str | None],
    audit_count_before: int,
) -> None:
    if page.status != "approved":
        raise RuntimeError("Approved page repair changed page status")
    if _wordpress_refs(page) != wordpress_refs_before:
        raise RuntimeError("Approved page repair changed WordPress references")
    if _wordpress_audit_count(session, page_id) != audit_count_before:
        raise RuntimeError("Approved page repair changed WordPress draft audits")


def _update_manual_review_note(
    session: Session,
    page: GeneratedPage,
    payload: ApprovedPageRepairRequest,
    repaired_at: datetime,
) -> None:
    page_id = page.id or 0
    record = session.exec(
        select(WordPressQualityReview).where(
            WordPressQualityReview.generated_page_id == page_id
        )
    ).first()
    existing_notes = (record.reviewer_notes or "").strip() if record else ""
    repair_note = (
        "Atlas content repair completed and QA rerun. "
        "WordPress logged-in visual review is still required before future manual publish review."
    )
    combined_notes = repair_note if not existing_notes else f"{existing_notes}\n\n{repair_note}"
    if record is None:
        record = WordPressQualityReview(generated_page_id=page_id)
    record.review_status = "needs_changes"
    record.reviewer_notes = combined_notes
    record.reviewed_by = (payload.repaired_by or "").strip() or record.reviewed_by
    record.reviewed_at = repaired_at
    record.updated_at = repaired_at
    session.add(record)


def _current_payload_hash(session: Session, page_id: int) -> str:
    payload = build_wordpress_payload_preview(session, page_id).payload
    canonical = json.dumps(
        {
            "title": payload.title,
            "slug": payload.slug,
            "status": payload.status,
            "content": payload.content,
            "excerpt": payload.excerpt,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalized_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value
