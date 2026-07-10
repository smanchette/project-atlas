from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import GeneratedPage, GeneratedPageRevision
from app.schemas.page_editor import (
    ApprovedPageRepairRequest,
    ApprovedPageRepairResponse,
    GeneratedPageRevisionRead,
    ManualDraftSaveRequest,
    ManualDraftSaveResponse,
)
from app.services.approved_page_repair import repair_approved_page
from app.services.page_editor import save_manual_draft

router = APIRouter(prefix="/generated-pages", tags=["page editor"])


@router.get("/{page_id}/revisions", response_model=list[GeneratedPageRevisionRead])
def read_page_revisions(
    page_id: int,
    session: Session = Depends(get_session),
) -> list[GeneratedPageRevision]:
    if not session.get(GeneratedPage, page_id):
        raise HTTPException(status_code=404, detail="Generated page not found")
    return list(
        session.exec(
            select(GeneratedPageRevision)
            .where(GeneratedPageRevision.generated_page_id == page_id)
            .order_by(GeneratedPageRevision.created_at.desc())
        ).all()
    )


@router.put("/{page_id}/draft", response_model=ManualDraftSaveResponse)
def update_manual_draft(
    page_id: int,
    payload: ManualDraftSaveRequest,
    session: Session = Depends(get_session),
) -> dict:
    page, revision, qa_result = save_manual_draft(session, page_id, payload)
    return {"page": page, "revision": revision, "qa_result": qa_result}


@router.put("/{page_id}/draft-and-qa", response_model=ManualDraftSaveResponse)
def update_manual_draft_and_run_qa(
    page_id: int,
    payload: ManualDraftSaveRequest,
    session: Session = Depends(get_session),
) -> dict:
    page, revision, qa_result = save_manual_draft(
        session,
        page_id,
        payload,
        run_qa=True,
    )
    return {"page": page, "revision": revision, "qa_result": qa_result}


@router.put("/{page_id}/approved-repair", response_model=ApprovedPageRepairResponse)
def repair_approved_draft_content(
    page_id: int,
    payload: ApprovedPageRepairRequest,
    session: Session = Depends(get_session),
) -> ApprovedPageRepairResponse:
    return repair_approved_page(session, page_id, payload)
