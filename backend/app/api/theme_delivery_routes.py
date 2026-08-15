from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.theme_families import (
    PerformanceLocalDeliveryRead,
    PerformanceLocalFullSiteAuditRead,
    ThemeActivationPlanRead,
    ThemeActivationRehearsalCreate,
    ThemeActivationRehearsalRead,
    ThemeActivationRehearsalRollbackCreate,
)
from app.schemas.page_export import ThemeConfiguredPageExportPackage
from app.services.form_submission_gateway import (
    FormGatewayError,
    require_local_operator_request,
    require_loopback_request,
)
from app.services.theme_activation_rehearsal import (
    ThemeActivationRehearsalError,
    activate_theme_configuration_rehearsal,
    audit_performance_local_full_site_rehearsal,
    plan_theme_activation_rehearsal,
    rollback_theme_configuration_rehearsal,
)
from app.services.theme_delivery import (
    ThemeDeliveryError,
    read_active_performance_local_delivery,
    read_local_performance_local_preview,
    read_performance_local_rehearsal_delivery,
)
from app.services.page_export import build_theme_configured_page_export_package


router = APIRouter(prefix="/theme-delivery", tags=["theme delivery"])


@router.get(
    "/active/generated-pages/{page_id}",
    response_model=PerformanceLocalDeliveryRead,
)
def active_performance_local_delivery(
    page_id: int,
    session: Session = Depends(get_session),
) -> PerformanceLocalDeliveryRead:
    try:
        return read_active_performance_local_delivery(session, page_id)
    except ThemeDeliveryError as exc:
        raise _public_delivery_http_error() from exc


@router.get(
    "/active/generated-pages/{page_id}/export-package",
    response_model=ThemeConfiguredPageExportPackage,
)
def active_performance_local_export(
    page_id: int,
    session: Session = Depends(get_session),
) -> ThemeConfiguredPageExportPackage:
    try:
        delivery = read_active_performance_local_delivery(session, page_id)
    except ThemeDeliveryError as exc:
        raise _public_delivery_http_error() from exc
    if not delivery.export_eligibility.eligible:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "theme_configuration_export_blocked",
                "message": "The active Theme delivery is not eligible for public export.",
            },
        )
    return build_theme_configured_page_export_package(
        session,
        page_id,
        delivery.website_configuration.id,
    )


@router.get(
    "/local-preview/configurations/{configuration_id}/generated-pages/{page_id}",
    response_model=PerformanceLocalDeliveryRead,
)
def local_performance_local_preview(
    configuration_id: int,
    page_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> PerformanceLocalDeliveryRead:
    try:
        require_local_operator_request(request)
        return read_local_performance_local_preview(
            session,
            configuration_id,
            page_id,
        )
    except FormGatewayError as exc:
        raise _gateway_http_error(exc) from exc
    except ThemeDeliveryError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/rehearsal/configurations/{configuration_id}/generated-pages/{page_id}",
    response_model=PerformanceLocalDeliveryRead,
)
def rehearsal_performance_local_delivery(
    configuration_id: int,
    page_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> PerformanceLocalDeliveryRead:
    try:
        require_loopback_request(request)
        return read_performance_local_rehearsal_delivery(
            session,
            configuration_id,
            page_id,
        )
    except FormGatewayError as exc:
        raise _gateway_http_error(exc) from exc
    except ThemeDeliveryError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/rehearsal/websites/{website_id}/configurations/{configuration_id}/activation-plan",
    response_model=ThemeActivationPlanRead,
)
def rehearsal_activation_plan(
    website_id: int,
    configuration_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> ThemeActivationPlanRead:
    try:
        require_loopback_request(request)
        return plan_theme_activation_rehearsal(
            session,
            website_id,
            configuration_id,
        )
    except FormGatewayError as exc:
        raise _gateway_http_error(exc) from exc
    except ThemeActivationRehearsalError as exc:
        raise _rehearsal_http_error(exc) from exc


@router.post(
    "/rehearsal/websites/{website_id}/configurations/{configuration_id}/activate",
    response_model=ThemeActivationRehearsalRead,
)
def activate_rehearsal_configuration(
    website_id: int,
    configuration_id: int,
    payload: ThemeActivationRehearsalCreate,
    request: Request,
    session: Session = Depends(get_session),
) -> ThemeActivationRehearsalRead:
    try:
        require_loopback_request(request)
        return activate_theme_configuration_rehearsal(
            session,
            website_id,
            configuration_id,
            payload,
        )
    except FormGatewayError as exc:
        raise _gateway_http_error(exc) from exc
    except ThemeActivationRehearsalError as exc:
        raise _rehearsal_http_error(exc) from exc


@router.post(
    "/rehearsal/websites/{website_id}/configurations/{configuration_id}/rollback",
    response_model=ThemeActivationRehearsalRead,
)
def rollback_rehearsal_configuration(
    website_id: int,
    configuration_id: int,
    payload: ThemeActivationRehearsalRollbackCreate,
    request: Request,
    session: Session = Depends(get_session),
) -> ThemeActivationRehearsalRead:
    try:
        require_loopback_request(request)
        return rollback_theme_configuration_rehearsal(
            session,
            website_id,
            configuration_id,
            payload,
        )
    except FormGatewayError as exc:
        raise _gateway_http_error(exc) from exc
    except ThemeActivationRehearsalError as exc:
        raise _rehearsal_http_error(exc) from exc


@router.get(
    "/rehearsal/websites/{website_id}/configurations/{configuration_id}/full-site-audit",
    response_model=PerformanceLocalFullSiteAuditRead,
)
def full_site_rehearsal_audit(
    website_id: int,
    configuration_id: int,
    request: Request,
    expected_page_count: int | None = Query(default=None, ge=1),
    session: Session = Depends(get_session),
) -> PerformanceLocalFullSiteAuditRead:
    try:
        require_loopback_request(request)
        return audit_performance_local_full_site_rehearsal(
            session,
            website_id,
            configuration_id,
            expected_page_count=expected_page_count,
        )
    except FormGatewayError as exc:
        raise _gateway_http_error(exc) from exc
    except ThemeActivationRehearsalError as exc:
        raise _rehearsal_http_error(exc) from exc


def _http_error(exc: ThemeDeliveryError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


def _public_delivery_http_error() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "performance_local_delivery_unavailable",
            "message": "Performance Local delivery is unavailable.",
        },
    )


def _gateway_http_error(exc: FormGatewayError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.safe_message},
    )


def _rehearsal_http_error(exc: ThemeActivationRehearsalError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )
