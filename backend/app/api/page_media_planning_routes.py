import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.page_media_planning import (
    PageMediaAssetApprovalRequest,
    PageMediaAssetRead,
    PageMediaAssetRetirementRequest,
    PageMediaAssignmentRequest,
    PageMediaPlacementDecisionRequest,
    PageMediaWorkspace,
)
from app.schemas.scoped_media_authorizations import (
    ScopedMediaAuthorizationRead,
    ScopedMediaAuthorizationRequest,
    normalize_scoped_media_required_terms,
)
from app.services.brand_assets import parse_string_list
from app.services.page_media_planning import (
    PageMediaPlanningError,
    approve_page_media_asset,
    assign_media_to_requirement,
    create_governed_page_media_asset,
    decide_media_placement,
    page_media_asset_read,
    read_page_media_workspace,
    refresh_site_plan_media_suggestions,
    retire_page_media_asset,
)
from app.services.scoped_media_authorizations import (
    ScopedMediaAuthorizationError,
    create_scoped_media_authorization,
    list_scoped_media_authorizations,
)


router = APIRouter(tags=["page media planning"])


@router.get(
    "/site-plans/{plan_id}/page-media",
    response_model=PageMediaWorkspace,
)
def page_media_workspace(
    plan_id: int,
    session: Session = Depends(get_session),
) -> PageMediaWorkspace:
    return _planning_call(read_page_media_workspace, session, plan_id)


@router.post(
    "/site-plans/{plan_id}/page-media/suggestions/refresh",
    response_model=PageMediaWorkspace,
)
def refresh_page_media_suggestions(
    plan_id: int,
    session: Session = Depends(get_session),
) -> PageMediaWorkspace:
    return _planning_call(refresh_site_plan_media_suggestions, session, plan_id)


@router.post(
    "/site-plans/{plan_id}/page-media/placements/decide",
    response_model=PageMediaWorkspace,
)
def record_page_media_decision(
    plan_id: int,
    payload: PageMediaPlacementDecisionRequest,
    session: Session = Depends(get_session),
) -> PageMediaWorkspace:
    return _planning_call(decide_media_placement, session, plan_id, payload)


@router.post(
    "/site-plans/{plan_id}/page-media/placements/{requirement_id}/assign",
    response_model=PageMediaWorkspace,
)
def assign_page_media(
    plan_id: int,
    requirement_id: int,
    payload: PageMediaAssignmentRequest,
    session: Session = Depends(get_session),
) -> PageMediaWorkspace:
    return _planning_call(
        assign_media_to_requirement,
        session,
        plan_id,
        requirement_id,
        payload,
    )


@router.get(
    "/site-plans/{plan_id}/page-media/authorizations",
    response_model=list[ScopedMediaAuthorizationRead],
)
def page_media_authorization_history(
    plan_id: int,
    media_requirement_id: int | None = None,
    image_metadata_id: int | None = None,
    session: Session = Depends(get_session),
) -> list[ScopedMediaAuthorizationRead]:
    return _authorization_call(
        list_scoped_media_authorizations,
        session,
        plan_id,
        media_requirement_id=media_requirement_id,
        image_metadata_id=image_metadata_id,
    )


@router.post(
    "/site-plans/{plan_id}/page-media/authorizations",
    response_model=ScopedMediaAuthorizationRead,
    status_code=201,
)
def authorize_scoped_page_media(
    plan_id: int,
    payload: ScopedMediaAuthorizationRequest,
    session: Session = Depends(get_session),
) -> ScopedMediaAuthorizationRead:
    return _authorization_call(
        create_scoped_media_authorization,
        session,
        plan_id,
        payload,
    )


@router.post(
    "/page-media/assets/upload",
    response_model=PageMediaAssetRead,
    status_code=201,
)
async def upload_governed_page_media(
    file: UploadFile = File(...),
    website_id: int = Form(...),
    business_id: int = Form(...),
    media_key: str = Form(...),
    image_title: str = Form(...),
    reviewed_alt_text: str | None = Form(default=None),
    acquisition_source: str = Form(...),
    creator_source_identity: str = Form(...),
    provenance_type: str = Form(...),
    provenance_notes: str = Form(...),
    rights_status: str = Form(...),
    rights_holder: str = Form(...),
    rights_notes: str = Form(...),
    approved_usage: str = Form(...),
    prohibited_usage: str = Form(...),
    permitted_placement_keys: str = Form(...),
    accessibility_intent: str = Form(...),
    created_by: str = Form(...),
    usage_authorization_mode: str = Form(default="contract_default"),
    required_authorization_terms: str = Form(default="[]"),
    replaces_image_metadata_id: int | None = Form(default=None),
    session: Session = Depends(get_session),
) -> PageMediaAssetRead:
    try:
        try:
            required_terms_value = json.loads(required_authorization_terms)
            required_terms = normalize_scoped_media_required_terms(
                required_terms_value
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        asset = await create_governed_page_media_asset(
            session,
            file=file,
            website_id=website_id,
            business_id=business_id,
            media_key=media_key,
            image_title=image_title,
            reviewed_alt_text=reviewed_alt_text,
            acquisition_source=acquisition_source,
            creator_source_identity=creator_source_identity,
            provenance_type=provenance_type,
            provenance_notes=provenance_notes,
            rights_status=rights_status,
            rights_holder=rights_holder,
            rights_notes=rights_notes,
            approved_usage=parse_string_list(approved_usage, "Approved usage"),
            prohibited_usage=parse_string_list(prohibited_usage, "Prohibited usage"),
            permitted_placement_keys=parse_string_list(
                permitted_placement_keys,
                "Permitted placement keys",
            ),
            accessibility_intent=accessibility_intent,
            created_by=created_by,
            usage_authorization_mode=usage_authorization_mode,
            required_authorization_terms=required_terms,
            replaces_image_metadata_id=replaces_image_metadata_id,
        )
        return page_media_asset_read(asset)
    except PageMediaPlanningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/page-media/assets/{image_id}/approve",
    response_model=PageMediaAssetRead,
)
def approve_governed_page_media(
    image_id: int,
    payload: PageMediaAssetApprovalRequest,
    session: Session = Depends(get_session),
) -> PageMediaAssetRead:
    asset = _planning_call(
        approve_page_media_asset,
        session,
        image_id,
        expected_website_id=payload.website_id,
        expected_business_id=payload.business_id,
        approved_by=payload.approved_by,
        expected_media_version=payload.expected_media_version,
    )
    return page_media_asset_read(asset)


@router.post(
    "/page-media/assets/{image_id}/retire",
    response_model=PageMediaAssetRead,
)
def retire_governed_page_media(
    image_id: int,
    payload: PageMediaAssetRetirementRequest,
    session: Session = Depends(get_session),
) -> PageMediaAssetRead:
    asset = _planning_call(
        retire_page_media_asset,
        session,
        image_id,
        expected_website_id=payload.website_id,
        expected_business_id=payload.business_id,
        retired_by=payload.retired_by,
        rationale=payload.rationale,
        expected_media_version=payload.expected_media_version,
    )
    return page_media_asset_read(asset)


def _planning_call(function, session: Session, *args, **kwargs):
    try:
        return function(session, *args, **kwargs)
    except PageMediaPlanningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _authorization_call(function, session: Session, *args, **kwargs):
    try:
        return function(session, *args, **kwargs)
    except ScopedMediaAuthorizationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
