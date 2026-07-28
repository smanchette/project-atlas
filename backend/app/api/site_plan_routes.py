from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.site_plans import (
    PlannedPageCreate,
    PlannedPageRead,
    PlannedPageUpdate,
    PlanningRecordOverrideUpdate,
    PlanningRecordRead,
    SitePlanCreate,
    SitePlanDetail,
    SitePlanRead,
    SitePlanUpdate,
)
from app.services.site_planning import (
    SitePlanningError,
    create_planned_page,
    create_site_plan,
    list_site_plans,
    refresh_planning_record,
    site_plan_detail,
    update_planned_page,
    update_planning_overrides,
    update_site_plan,
)

router = APIRouter(prefix="/site-plans", tags=["site plans"])


@router.get("", response_model=list[SitePlanRead])
def read_site_plans(
    website_id: int | None = None,
    session: Session = Depends(get_session),
):
    return _call(list_site_plans, session, website_id=website_id)


@router.post("", response_model=SitePlanRead, status_code=201)
def add_site_plan(
    payload: SitePlanCreate,
    session: Session = Depends(get_session),
):
    return _call(create_site_plan, session, payload)


@router.get("/{plan_id}", response_model=SitePlanDetail)
def read_site_plan(
    plan_id: int,
    session: Session = Depends(get_session),
):
    return _call(site_plan_detail, session, plan_id)


@router.patch("/{plan_id}", response_model=SitePlanRead)
def edit_site_plan(
    plan_id: int,
    payload: SitePlanUpdate,
    session: Session = Depends(get_session),
):
    return _call(update_site_plan, session, plan_id, payload)


@router.post("/{plan_id}/planned-pages", response_model=PlannedPageRead, status_code=201)
def add_planned_page(
    plan_id: int,
    payload: PlannedPageCreate,
    session: Session = Depends(get_session),
):
    if payload.site_plan_id != plan_id:
        raise HTTPException(status_code=409, detail="Route and payload Site Plan IDs do not match.")
    return _call(create_planned_page, session, payload)


@router.patch("/planned-pages/{planned_page_id}", response_model=PlannedPageRead)
def edit_planned_page(
    planned_page_id: int,
    payload: PlannedPageUpdate,
    session: Session = Depends(get_session),
):
    return _call(update_planned_page, session, planned_page_id, payload)


@router.post(
    "/planned-pages/{planned_page_id}/planning-record/refresh",
    response_model=PlanningRecordRead,
)
def refresh_page_planning_record(
    planned_page_id: int,
    session: Session = Depends(get_session),
):
    return _call(refresh_planning_record, session, planned_page_id)


@router.patch(
    "/planned-pages/{planned_page_id}/planning-record/overrides",
    response_model=PlanningRecordRead,
)
def edit_page_planning_overrides(
    planned_page_id: int,
    payload: PlanningRecordOverrideUpdate,
    session: Session = Depends(get_session),
):
    return _call(
        update_planning_overrides,
        session,
        planned_page_id,
        payload.operator_overrides,
    )


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except SitePlanningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
