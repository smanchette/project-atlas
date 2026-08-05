from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.session import get_session
from app.models import Theme, WebsiteThemeSelection
from app.schemas.themes import (
    ResolvedWebsiteTheme,
    ThemeApprovalRequest,
    ThemeCreate,
    ThemeRead,
    ThemeRetirementRequest,
    WebsiteThemeSelectionCreate,
    WebsiteThemeSelectionRead,
    WebsiteThemeStateRead,
)
from app.services.themes import (
    ThemeError,
    approve_theme,
    create_theme,
    list_website_themes,
    read_website_theme_state,
    resolve_website_theme,
    retire_theme,
    select_website_theme,
)


router = APIRouter(tags=["themes"])


@router.get("/websites/{website_id}/themes", response_model=list[ThemeRead])
def themes_for_website(
    website_id: int,
    session: Session = Depends(get_session),
) -> list[Theme]:
    try:
        return list_website_themes(session, website_id)
    except ThemeError as exc:
        raise _http_error(exc) from exc


@router.post("/websites/{website_id}/themes", response_model=ThemeRead, status_code=201)
def create_website_theme(
    website_id: int,
    payload: ThemeCreate,
    session: Session = Depends(get_session),
) -> Theme:
    try:
        return create_theme(session, website_id, payload)
    except ThemeError as exc:
        raise _http_error(exc) from exc


@router.post("/themes/{theme_id}/approve", response_model=ThemeRead)
def approve_website_theme(
    theme_id: int,
    payload: ThemeApprovalRequest,
    session: Session = Depends(get_session),
) -> Theme:
    try:
        return approve_theme(session, theme_id, approved_by=payload.approved_by)
    except ThemeError as exc:
        raise _http_error(exc) from exc


@router.post("/themes/{theme_id}/retire", response_model=ThemeRead)
def retire_website_theme(
    theme_id: int,
    payload: ThemeRetirementRequest,
    session: Session = Depends(get_session),
) -> Theme:
    try:
        return retire_theme(
            session,
            theme_id,
            retired_by=payload.retired_by,
            rationale=payload.rationale,
        )
    except ThemeError as exc:
        raise _http_error(exc) from exc


@router.get("/websites/{website_id}/theme", response_model=ResolvedWebsiteTheme)
def effective_website_theme(
    website_id: int,
    session: Session = Depends(get_session),
) -> ResolvedWebsiteTheme:
    try:
        return resolve_website_theme(session, website_id)
    except ThemeError as exc:
        raise _http_error(exc) from exc


@router.get("/websites/{website_id}/theme-selection", response_model=WebsiteThemeStateRead)
def website_theme_selection_history(
    website_id: int,
    session: Session = Depends(get_session),
) -> WebsiteThemeStateRead:
    try:
        return read_website_theme_state(session, website_id)
    except ThemeError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/websites/{website_id}/theme-selection",
    response_model=WebsiteThemeSelectionRead,
    status_code=201,
)
def select_theme_for_website(
    website_id: int,
    payload: WebsiteThemeSelectionCreate,
    session: Session = Depends(get_session),
) -> WebsiteThemeSelection:
    try:
        return select_website_theme(
            session,
            website_id,
            theme_id=payload.theme_id,
            selected_by=payload.selected_by,
            rationale=payload.rationale,
        )
    except ThemeError as exc:
        raise _http_error(exc) from exc


def _http_error(exc: ThemeError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )
