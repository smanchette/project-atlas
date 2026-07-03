from datetime import UTC, datetime
import hashlib
import json

from fastapi import HTTPException
from sqlmodel import Session

from app.models import ApprovalAudit, GeneratedPage
from app.services.page_qa import save_page_qa


def draft_content_hash(draft_content: dict | None) -> str:
    canonical = json.dumps(
        draft_content or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def approve_page_with_audit(
    session: Session,
    page_id: int,
    *,
    approved_by: str | None = None,
) -> GeneratedPage:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    if page.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft pages can be approved")

    result = save_page_qa(session, page_id, commit=False)
    if result.readiness_status != "ready":
        session.commit()
        raise HTTPException(
            status_code=409,
            detail=f"Page QA status is {result.readiness_status}; resolve QA items before approval",
        )

    approved_at = datetime.now(UTC)
    status_before = page.status
    status_after = "approved"
    audit = ApprovalAudit(
        generated_page_id=page.id or page_id,
        approved_at=approved_at,
        approved_by=(approved_by or "").strip() or None,
        qa_status_at_approval=result.readiness_status,
        qa_checked_at=result.checked_at,
        qa_result_snapshot=result.model_dump(mode="json", exclude={"persisted"}),
        draft_hash_at_approval=draft_content_hash(page.draft_content),
        page_status_before=status_before,
        page_status_after=status_after,
    )
    page.status = status_after
    page.updated_at = approved_at
    session.add(page)
    session.add(audit)
    session.commit()
    session.refresh(page)
    return page
