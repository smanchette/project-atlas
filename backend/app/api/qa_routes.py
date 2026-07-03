from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import Session
from sqlmodel import select

from app.db.session import get_session
from app.models import ApprovalAudit, GeneratedPage
from app.schemas.approval_queue import ApprovalQueueResponse
from app.schemas.entities import GeneratedPageRead
from app.schemas.qa import (
    ApprovalAuditRead,
    ApprovalHistorySummary,
    ApprovalRequest,
    PageQAResult,
    PageReviewUpdate,
    QABatchRequest,
    QABatchResponse,
)
from app.services.approval_audit import approve_page_with_audit
from app.services.approval_queue import build_approval_queue
from app.services.page_qa import (
    get_page_qa,
    preview_qa_batch,
    run_qa_batch,
    save_page_qa,
)

router = APIRouter(prefix="/generated-pages", tags=["page QA"])


@router.get("/approval-queue", response_model=ApprovalQueueResponse)
def read_approval_queue(
    session: Session = Depends(get_session),
) -> ApprovalQueueResponse:
    return build_approval_queue(session)


@router.post("/qa/batch-preview", response_model=QABatchResponse)
def batch_qa_preview(
    payload: QABatchRequest,
    session: Session = Depends(get_session),
) -> QABatchResponse:
    return preview_qa_batch(session, payload)


@router.post("/qa/batch-run", response_model=QABatchResponse)
def batch_qa_run(
    payload: QABatchRequest,
    session: Session = Depends(get_session),
) -> QABatchResponse:
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail="Batch QA run requires confirm=true after preview.",
        )
    return run_qa_batch(session, payload)


@router.get("/approval-history-summary", response_model=list[ApprovalHistorySummary])
def approval_history_summary(
    session: Session = Depends(get_session),
) -> list[ApprovalHistorySummary]:
    rows = session.exec(
        select(
            ApprovalAudit.generated_page_id,
            func.count(ApprovalAudit.id),
        ).group_by(ApprovalAudit.generated_page_id)
    ).all()
    return [
        ApprovalHistorySummary(generated_page_id=page_id, approval_count=count)
        for page_id, count in rows
    ]


@router.get("/{page_id}/qa", response_model=PageQAResult)
def read_page_qa(
    page_id: int,
    session: Session = Depends(get_session),
) -> PageQAResult:
    return get_page_qa(session, page_id)


@router.post("/{page_id}/qa/run", response_model=PageQAResult)
def run_page_qa(
    page_id: int,
    session: Session = Depends(get_session),
) -> PageQAResult:
    return save_page_qa(session, page_id)


@router.patch("/{page_id}/review", response_model=GeneratedPageRead)
def save_page_review(
    page_id: int,
    payload: PageReviewUpdate,
    session: Session = Depends(get_session),
) -> GeneratedPage:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    page.internal_notes = payload.internal_notes
    page.last_reviewed_by = (payload.last_reviewed_by or "").strip() or None
    page.last_reviewed_at = datetime.now(UTC)
    session.add(page)
    session.commit()
    session.refresh(page)
    return page


@router.get("/{page_id}/approval-history", response_model=list[ApprovalAuditRead])
def read_approval_history(
    page_id: int,
    session: Session = Depends(get_session),
) -> list[ApprovalAudit]:
    if not session.get(GeneratedPage, page_id):
        raise HTTPException(status_code=404, detail="Generated page not found")
    return list(
        session.exec(
            select(ApprovalAudit)
            .where(ApprovalAudit.generated_page_id == page_id)
            .order_by(ApprovalAudit.approved_at.desc())
        ).all()
    )


@router.post("/{page_id}/approve", response_model=GeneratedPageRead)
def approve_ready_page(
    page_id: int,
    payload: ApprovalRequest | None = None,
    session: Session = Depends(get_session),
) -> GeneratedPage:
    return approve_page_with_audit(
        session,
        page_id,
        approved_by=payload.approved_by if payload else None,
    )
