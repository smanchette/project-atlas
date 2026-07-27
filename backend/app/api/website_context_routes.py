from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.website_context import WebsiteContextRead
from app.services.website_context import WebsiteContextError, build_website_context


router = APIRouter(tags=["website context"])


@router.get("/websites/{website_id}/context", response_model=WebsiteContextRead)
def read_website_context(
    website_id: int,
    session: Session = Depends(get_session),
) -> WebsiteContextRead:
    try:
        return build_website_context(session, website_id=website_id)
    except WebsiteContextError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/generated-pages/{page_id}/website-context", response_model=WebsiteContextRead)
def read_page_website_context(
    page_id: int,
    session: Session = Depends(get_session),
) -> WebsiteContextRead:
    try:
        return build_website_context(session, page_id=page_id)
    except WebsiteContextError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

