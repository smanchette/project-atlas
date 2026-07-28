from collections.abc import Iterable

from fastapi import HTTPException
from sqlmodel import Session

from app.models import GeneratedPage, Website


def require_page_website(
    session: Session,
    page: GeneratedPage,
    *,
    expected_website_id: int | None = None,
) -> int:
    if page.website_id is None:
        raise HTTPException(
            status_code=409,
            detail=f"Generated Page {page.id} has no Website ownership.",
        )
    website = session.get(Website, page.website_id)
    if not website or website.business_id != page.business_id:
        raise HTTPException(
            status_code=409,
            detail=f"Generated Page {page.id} has invalid Website ownership.",
        )
    if expected_website_id is not None and page.website_id != expected_website_id:
        raise HTTPException(
            status_code=409,
            detail=f"Generated Page {page.id} does not belong to Website {expected_website_id}.",
        )
    return page.website_id


def require_single_website_selection(
    session: Session,
    pages: Iterable[GeneratedPage],
    *,
    website_id: int | None = None,
    operation: str,
) -> int:
    page_list = list(pages)
    if website_id is not None:
        website = session.get(Website, website_id)
        if not website:
            raise HTTPException(status_code=404, detail=f"Website not found: {website_id}")
        for page in page_list:
            require_page_website(session, page, expected_website_id=website_id)
        return website_id
    website_ids = {require_page_website(session, page) for page in page_list}
    if len(website_ids) != 1:
        raise HTTPException(
            status_code=409,
            detail=f"{operation} requires exactly one explicitly selected Website.",
        )
    return next(iter(website_ids))
