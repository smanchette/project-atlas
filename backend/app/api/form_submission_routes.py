from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.form_delivery import FormSubmissionAcceptanceRead
from app.services.form_submission_gateway import (
    FormGatewayError,
    preflight_form_gateway,
)


router = APIRouter(tags=["form submission gateway"])


@router.post(
    "/websites/{website_id}/forms/{component_configuration_id}/submissions",
    response_model=FormSubmissionAcceptanceRead,
)
async def submit_website_form(
    website_id: int,
    component_configuration_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> FormSubmissionAcceptanceRead:
    # Remove query values from the live request scope before any route error can
    # reach an access logger. Readiness is still evaluated first, and a blocked
    # form never consumes, decodes, validates, stores, or reflects the body.
    query_was_present = bool(
        request.scope.pop("atlas_form_query_was_present", False)
        or request.scope.get("query_string", b"")
    )
    if query_was_present:
        request.scope["query_string"] = b""
    try:
        preflight_form_gateway(
            session,
            website_id,
            component_configuration_id,
        )
        if query_was_present:
            raise FormGatewayError(
                400,
                "query_parameters_forbidden",
                "Form submissions do not accept query parameters.",
            )
        raise FormGatewayError(
            503,
            "form_delivery_mode_unavailable",
            "Form submission is not available.",
        )
    except FormGatewayError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.safe_message},
        ) from exc


# Temporary import compatibility for callers while the public route and
# response contract are now provider-neutral.
submit_performance_local_form = submit_website_form
