from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.form_delivery import (
    FormDeliveryOperatorReviewRead,
    WebsiteFormDeliveryModeRevisionRead,
)
from app.services.form_delivery_modes import (
    FormDeliveryConfigurationError,
    read_form_delivery_mode_history,
    read_form_delivery_operator_review,
)
from app.services.form_submission_gateway import (
    FormGatewayError,
    require_local_operator_request,
)


router = APIRouter(tags=["form delivery"])


@router.get(
    "/websites/{website_id}/forms/{component_configuration_id}/delivery-mode",
    response_model=FormDeliveryOperatorReviewRead,
)
def current_form_delivery_mode_review(
    website_id: int,
    component_configuration_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> FormDeliveryOperatorReviewRead:
    try:
        require_local_operator_request(request)
        return read_form_delivery_operator_review(
            session,
            website_id,
            component_configuration_id,
        )
    except FormGatewayError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.safe_message},
        ) from exc
    except FormDeliveryConfigurationError as exc:
        raise _configuration_http_error(exc) from exc


@router.get(
    "/websites/{website_id}/forms/{component_configuration_id}/delivery-mode/history",
    response_model=list[WebsiteFormDeliveryModeRevisionRead],
)
def form_delivery_mode_history(
    website_id: int,
    component_configuration_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> list[WebsiteFormDeliveryModeRevisionRead]:
    try:
        require_local_operator_request(request)
        return read_form_delivery_mode_history(
            session,
            website_id,
            component_configuration_id,
        )
    except FormGatewayError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.safe_message},
        ) from exc
    except FormDeliveryConfigurationError as exc:
        raise _configuration_http_error(exc) from exc


def _configuration_http_error(exc: FormDeliveryConfigurationError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": "Form-delivery configuration is unavailable.",
        },
    )
