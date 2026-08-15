from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db.session import get_session
from app.models import (
    ThemeFamily,
    ThemeFamilyVersion,
    WebsiteThemeComponentConfiguration,
    WebsiteThemeConfiguration,
)
from app.schemas.theme_families import (
    ConversionComponentGraphRevisionCreate,
    ConversionComponentGraphRevisionRead,
    ThemeActivationReadinessRead,
    ThemeDraftBundleCreate,
    ThemeDraftPreviewRead,
    ThemeFamilyCreate,
    ThemeFamilyRead,
    ThemeFamilyVersionCreate,
    ThemeFamilyVersionRead,
    WebsiteThemeComponentConfigurationCreate,
    WebsiteThemeComponentConfigurationRead,
    WebsiteThemeComponentConfigurationRevisionCreate,
    WebsiteThemeConfigurationCreate,
    WebsiteThemeConfigurationRead,
)
from app.services.theme_configurations import (
    ThemeConfigurationError,
    create_component_configuration,
    create_inactive_theme_draft_bundle,
    create_website_theme_configuration,
    list_theme_families,
    list_theme_family_versions,
    list_website_theme_configurations,
    read_theme_draft_preview,
    read_theme_draft_preview_by_family,
    register_theme_family,
    register_theme_family_version,
    revise_component_configuration,
    revise_conversion_component_graph,
    theme_activation_readiness,
)


router = APIRouter(tags=["theme families"])


@router.get("/theme-families", response_model=list[ThemeFamilyRead])
def theme_families(
    session: Session = Depends(get_session),
) -> list[ThemeFamily]:
    try:
        return list_theme_families(session)
    except ThemeConfigurationError as exc:
        raise _http_error(exc) from exc


@router.post("/theme-families", response_model=ThemeFamilyRead, status_code=201)
def create_theme_family(
    payload: ThemeFamilyCreate,
    session: Session = Depends(get_session),
) -> ThemeFamily:
    try:
        return register_theme_family(session, payload)
    except ThemeConfigurationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/theme-families/{theme_family_id}/versions",
    response_model=list[ThemeFamilyVersionRead],
)
def theme_family_versions(
    theme_family_id: int,
    session: Session = Depends(get_session),
) -> list[ThemeFamilyVersion]:
    try:
        return list_theme_family_versions(session, theme_family_id)
    except ThemeConfigurationError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/theme-families/{theme_family_id}/versions",
    response_model=ThemeFamilyVersionRead,
    status_code=201,
)
def create_theme_family_version(
    theme_family_id: int,
    payload: ThemeFamilyVersionCreate,
    session: Session = Depends(get_session),
) -> ThemeFamilyVersion:
    try:
        return register_theme_family_version(session, theme_family_id, payload)
    except ThemeConfigurationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/websites/{website_id}/theme-configurations",
    response_model=list[WebsiteThemeConfigurationRead],
)
def website_theme_configurations(
    website_id: int,
    family_key: str | None = Query(default=None, min_length=1, max_length=120),
    family_version: int | None = Query(default=None, ge=1),
    lifecycle_status: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[WebsiteThemeConfiguration]:
    try:
        return list_website_theme_configurations(
            session,
            website_id,
            family_key=family_key,
            family_version=family_version,
            lifecycle_status=lifecycle_status,
        )
    except ThemeConfigurationError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/websites/{website_id}/theme-configurations",
    response_model=WebsiteThemeConfigurationRead,
    status_code=201,
)
def create_website_theme_draft(
    website_id: int,
    payload: WebsiteThemeConfigurationCreate,
    session: Session = Depends(get_session),
) -> WebsiteThemeConfiguration:
    try:
        return create_website_theme_configuration(session, website_id, payload)
    except ThemeConfigurationError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/websites/{website_id}/theme-configurations/draft-bundle",
    response_model=ThemeDraftPreviewRead,
    status_code=201,
)
def create_website_theme_draft_bundle(
    website_id: int,
    payload: ThemeDraftBundleCreate,
    session: Session = Depends(get_session),
) -> ThemeDraftPreviewRead:
    try:
        return create_inactive_theme_draft_bundle(session, website_id, payload)
    except ThemeConfigurationError as exc:
        raise _http_error(exc) from exc


# This static discovery route must remain before the dynamic configuration route.
@router.get(
    "/websites/{website_id}/theme-configurations/draft-preview",
    response_model=ThemeDraftPreviewRead,
)
def website_theme_draft_preview_by_family(
    website_id: int,
    family_key: str = Query(min_length=1, max_length=120),
    family_version: int = Query(ge=1),
    page_id: int | None = Query(default=None, ge=1),
    session: Session = Depends(get_session),
) -> ThemeDraftPreviewRead:
    try:
        return read_theme_draft_preview_by_family(
            session,
            website_id,
            family_key=family_key,
            family_version=family_version,
            page_id=page_id,
        )
    except ThemeConfigurationError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/websites/{website_id}/theme-configurations/{configuration_id}/components",
    response_model=WebsiteThemeComponentConfigurationRead,
    status_code=201,
)
def create_website_theme_component(
    website_id: int,
    configuration_id: int,
    payload: WebsiteThemeComponentConfigurationCreate,
    session: Session = Depends(get_session),
) -> WebsiteThemeComponentConfiguration:
    try:
        return create_component_configuration(
            session,
            website_id,
            configuration_id,
            payload,
        )
    except ThemeConfigurationError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/websites/{website_id}/theme-configurations/{configuration_id}/components/"
    "{component_configuration_id}/revisions",
    response_model=WebsiteThemeComponentConfigurationRead,
    status_code=201,
)
def revise_website_theme_component(
    website_id: int,
    configuration_id: int,
    component_configuration_id: int,
    payload: WebsiteThemeComponentConfigurationRevisionCreate,
    session: Session = Depends(get_session),
) -> WebsiteThemeComponentConfiguration:
    try:
        return revise_component_configuration(
            session,
            website_id,
            configuration_id,
            component_configuration_id,
            payload,
        )
    except ThemeConfigurationError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/websites/{website_id}/theme-configurations/{configuration_id}/components/"
    "conversion-graph-revision",
    response_model=ConversionComponentGraphRevisionRead,
    status_code=201,
)
def revise_website_theme_conversion_graph(
    website_id: int,
    configuration_id: int,
    payload: ConversionComponentGraphRevisionCreate,
    session: Session = Depends(get_session),
) -> ConversionComponentGraphRevisionRead:
    try:
        return revise_conversion_component_graph(
            session,
            website_id,
            configuration_id,
            payload,
        )
    except ThemeConfigurationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/websites/{website_id}/theme-configurations/{configuration_id}/preview",
    response_model=ThemeDraftPreviewRead,
)
def website_theme_draft_preview(
    website_id: int,
    configuration_id: int,
    page_id: int | None = Query(default=None, ge=1),
    session: Session = Depends(get_session),
) -> ThemeDraftPreviewRead:
    try:
        return read_theme_draft_preview(
            session,
            website_id,
            configuration_id,
            page_id=page_id,
        )
    except ThemeConfigurationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/websites/{website_id}/theme-configurations/{configuration_id}/readiness",
    response_model=ThemeActivationReadinessRead,
)
def website_theme_activation_readiness(
    website_id: int,
    configuration_id: int,
    session: Session = Depends(get_session),
) -> ThemeActivationReadinessRead:
    try:
        return theme_activation_readiness(session, website_id, configuration_id)
    except ThemeConfigurationError as exc:
        raise _http_error(exc) from exc


def _http_error(exc: ThemeConfigurationError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )
