from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.session import get_session
from app.models import PlannedPage
from app.schemas.site_plans import (
    PlannedPageCreate,
    PlannedPageDraftRequest,
    PlannedPageDraftResponse,
    PlannedPageRead,
    PlannedPageUpdate,
    PlanningRecordOverrideUpdate,
    PlanningRecordRead,
    SitePlanCreate,
    SitePlanDetail,
    SitePlanRead,
    WebsiteReadinessReport,
    SitePlanUpdate,
)
from app.schemas.site_connections import (
    InternalLinkIntentCreate,
    InternalLinkIntentRead,
    InternalLinkIntentUpdate,
    NavigationItemCreate,
    NavigationItemRead,
    NavigationItemUpdate,
    NavigationSetDecisionUpdate,
    NavigationSetRead,
    SiteConnectionPlanRead,
    SiteConnectionPlanningRecordRead,
)
from app.schemas.site_coverage import (
    CityCoverageDecisionRead,
    CountyCoverageDecisionRead,
    CountyCoverageDecisionUpdate,
    CoverageDecisionUpdate,
    CoverageInventoryPreview,
    CoveragePlanningRecordRead,
    CoveragePolicyRead,
    CoverageReconciliationResult,
    ServiceCityCoverageDecisionRead,
    ServiceCountyCoverageDecisionRead,
    ServiceCoverageDecisionRead,
    SupportingPageAuthorizationRead,
)
from app.schemas.drafting_eligibility import (
    CandidateDraftInput,
    CandidateDraftValidationResult,
    DraftingBatchManifest,
    DraftingEligibilityManifest,
    EligibilityDispositionRead,
    EligibilityDispositionUpdate,
)
from app.schemas.bulk_drafting import (
    WebsiteDraftGenerationRequest,
    WebsiteDraftGenerationRunRead,
)
from app.schemas.page_composition import (
    PageCompositionDecisionUpdate,
    PageCompositionRead,
    SemanticComponentDefinitionRead,
    SitePlanCompositionRefreshResult,
)
from app.services.bulk_drafting import (
    BulkDraftingError,
    list_generation_runs,
    read_generation_run,
    resume_generation,
    start_or_resume_generation,
)
from app.services.drafting_eligibility import (
    DraftingEligibilityError,
    assess_site_plan,
    read_manifest,
    record_disposition,
    validate_candidate_drafts,
)
from app.services.site_coverage import (
    SiteCoverageError,
    decide_city,
    decide_county,
    decide_service,
    decide_service_city,
    decide_service_county,
    decide_supporting_page,
    preview_expected_inventory,
    read_coverage_policy,
    reconcile_expected_inventory,
    refresh_coverage_candidates,
)
from app.services.site_connections import (
    SiteConnectionError,
    create_internal_link_intent,
    create_navigation_item,
    delete_internal_link_intent,
    delete_navigation_item,
    read_site_connection_plan,
    refresh_site_connection_suggestions,
    update_internal_link_intent,
    update_navigation_item,
    update_navigation_set,
)
from app.services.planned_page_drafting import (
    PlannedPageDraftingError,
    draft_planned_page,
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
from app.services.website_readiness import (
    WebsiteReadinessError,
    evaluate_website_readiness,
)
from app.services.page_composition import (
    PageCompositionError,
    list_component_registry,
    read_composition_for_generated_page,
    read_site_plan_compositions,
    refresh_site_plan_compositions,
    update_operator_composition_decisions,
)

router = APIRouter(prefix="/site-plans", tags=["site plans"])


@router.get("/components/registry", response_model=list[SemanticComponentDefinitionRead])
def read_semantic_component_registry(session: Session = Depends(get_session)):
    return _composition_call(list_component_registry, session)


@router.get(
    "/generated-pages/{generated_page_id}/composition",
    response_model=PageCompositionRead,
)
def read_generated_page_composition(
    generated_page_id: int,
    session: Session = Depends(get_session),
):
    return _composition_call(
        read_composition_for_generated_page,
        session,
        generated_page_id,
    )


@router.patch(
    "/compositions/{composition_id}/operator-decisions",
    response_model=PageCompositionRead,
)
def edit_composition_decisions(
    composition_id: int,
    payload: PageCompositionDecisionUpdate,
    session: Session = Depends(get_session),
):
    return _composition_call(
        update_operator_composition_decisions,
        session,
        composition_id,
        payload,
    )


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


@router.get("/{plan_id}/readiness", response_model=WebsiteReadinessReport)
def read_site_plan_readiness(
    plan_id: int,
    session: Session = Depends(get_session),
):
    try:
        return evaluate_website_readiness(session, plan_id)
    except WebsiteReadinessError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{plan_id}/compositions", response_model=list[PageCompositionRead])
def read_page_compositions(
    plan_id: int,
    session: Session = Depends(get_session),
):
    return _composition_call(read_site_plan_compositions, session, plan_id)


@router.post(
    "/{plan_id}/compositions/refresh",
    response_model=SitePlanCompositionRefreshResult,
)
def refresh_page_compositions(
    plan_id: int,
    session: Session = Depends(get_session),
):
    return _composition_call(refresh_site_plan_compositions, session, plan_id)


@router.get("/{plan_id}/connections", response_model=SiteConnectionPlanRead)
def read_site_connections(
    plan_id: int,
    session: Session = Depends(get_session),
):
    return _connection_call(read_site_connection_plan, session, plan_id)


@router.post(
    "/{plan_id}/connections/suggestions/refresh",
    response_model=SiteConnectionPlanningRecordRead,
)
def refresh_site_connections(
    plan_id: int,
    session: Session = Depends(get_session),
):
    return _connection_call(
        refresh_site_connection_suggestions,
        session,
        plan_id,
    )


@router.patch(
    "/navigation-sets/{navigation_set_id}",
    response_model=NavigationSetRead,
)
def decide_navigation_set(
    navigation_set_id: int,
    payload: NavigationSetDecisionUpdate,
    session: Session = Depends(get_session),
):
    return _connection_call(
        update_navigation_set,
        session,
        navigation_set_id,
        payload,
    )


@router.post(
    "/{plan_id}/navigation-items",
    response_model=NavigationItemRead,
    status_code=201,
)
def add_navigation_item(
    plan_id: int,
    payload: NavigationItemCreate,
    session: Session = Depends(get_session),
):
    if payload.site_plan_id != plan_id:
        raise HTTPException(
            status_code=409,
            detail="Route and payload Site Plan IDs do not match.",
        )
    return _connection_call(create_navigation_item, session, payload)


@router.patch(
    "/navigation-items/{item_id}",
    response_model=NavigationItemRead,
)
def edit_navigation_item(
    item_id: int,
    payload: NavigationItemUpdate,
    session: Session = Depends(get_session),
):
    return _connection_call(update_navigation_item, session, item_id, payload)


@router.delete("/navigation-items/{item_id}")
def remove_navigation_item(
    item_id: int,
    session: Session = Depends(get_session),
):
    _connection_call(delete_navigation_item, session, item_id)
    return {"ok": True}


@router.post(
    "/{plan_id}/internal-link-intents",
    response_model=InternalLinkIntentRead,
    status_code=201,
)
def add_internal_link_intent(
    plan_id: int,
    payload: InternalLinkIntentCreate,
    session: Session = Depends(get_session),
):
    if payload.site_plan_id != plan_id:
        raise HTTPException(
            status_code=409,
            detail="Route and payload Site Plan IDs do not match.",
        )
    return _connection_call(create_internal_link_intent, session, payload)


@router.patch(
    "/internal-link-intents/{intent_id}",
    response_model=InternalLinkIntentRead,
)
def edit_internal_link_intent(
    intent_id: int,
    payload: InternalLinkIntentUpdate,
    session: Session = Depends(get_session),
):
    return _connection_call(
        update_internal_link_intent,
        session,
        intent_id,
        payload,
    )


@router.delete("/internal-link-intents/{intent_id}")
def remove_internal_link_intent(
    intent_id: int,
    session: Session = Depends(get_session),
):
    _connection_call(delete_internal_link_intent, session, intent_id)
    return {"ok": True}


@router.get("/{plan_id}/coverage", response_model=CoveragePolicyRead)
def read_site_coverage(
    plan_id: int,
    session: Session = Depends(get_session),
):
    return _coverage_call(read_coverage_policy, session, plan_id)


@router.post(
    "/{plan_id}/coverage/candidates/refresh",
    response_model=CoveragePlanningRecordRead,
)
def refresh_site_coverage_candidates(
    plan_id: int,
    session: Session = Depends(get_session),
):
    return _coverage_call(refresh_coverage_candidates, session, plan_id)


@router.put(
    "/{plan_id}/coverage/services/{service_id}",
    response_model=ServiceCoverageDecisionRead,
)
def update_site_coverage_service(
    plan_id: int,
    service_id: int,
    payload: CoverageDecisionUpdate,
    session: Session = Depends(get_session),
):
    return _coverage_call(
        decide_service,
        session,
        plan_id,
        service_id,
        payload,
    )


@router.put(
    "/{plan_id}/coverage/counties/{county_id}",
    response_model=CountyCoverageDecisionRead,
)
def update_site_coverage_county(
    plan_id: int,
    county_id: int,
    payload: CountyCoverageDecisionUpdate,
    session: Session = Depends(get_session),
):
    return _coverage_call(
        decide_county,
        session,
        plan_id,
        county_id,
        payload,
    )


@router.put(
    "/{plan_id}/coverage/cities/{city_id}",
    response_model=CityCoverageDecisionRead,
)
def update_site_coverage_city(
    plan_id: int,
    city_id: int,
    payload: CoverageDecisionUpdate,
    session: Session = Depends(get_session),
):
    return _coverage_call(
        decide_city,
        session,
        plan_id,
        city_id,
        payload,
    )


@router.put(
    "/{plan_id}/coverage/services/{service_id}/cities/{city_id}",
    response_model=ServiceCityCoverageDecisionRead,
)
def update_site_coverage_service_city(
    plan_id: int,
    service_id: int,
    city_id: int,
    payload: CoverageDecisionUpdate,
    session: Session = Depends(get_session),
):
    return _coverage_call(
        decide_service_city,
        session,
        plan_id,
        service_id,
        city_id,
        payload,
    )


@router.put(
    "/{plan_id}/coverage/services/{service_id}/counties/{county_id}",
    response_model=ServiceCountyCoverageDecisionRead,
)
def update_site_coverage_service_county(
    plan_id: int,
    service_id: int,
    county_id: int,
    payload: CoverageDecisionUpdate,
    session: Session = Depends(get_session),
):
    return _coverage_call(
        decide_service_county,
        session,
        plan_id,
        service_id,
        county_id,
        payload,
    )


@router.put(
    "/{plan_id}/coverage/supporting-pages/{planned_page_id}",
    response_model=SupportingPageAuthorizationRead,
)
def update_supporting_page_authorization(
    plan_id: int,
    planned_page_id: int,
    payload: CoverageDecisionUpdate,
    session: Session = Depends(get_session),
):
    return _coverage_call(
        decide_supporting_page,
        session,
        plan_id,
        planned_page_id,
        payload,
    )


@router.get(
    "/{plan_id}/coverage/inventory",
    response_model=CoverageInventoryPreview,
)
def preview_site_coverage_inventory(
    plan_id: int,
    session: Session = Depends(get_session),
):
    return _coverage_call(preview_expected_inventory, session, plan_id)


@router.post(
    "/{plan_id}/coverage/reconcile",
    response_model=CoverageReconciliationResult,
)
def reconcile_site_coverage_inventory(
    plan_id: int,
    session: Session = Depends(get_session),
):
    return _coverage_call(reconcile_expected_inventory, session, plan_id)


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
    "/planned-pages/{planned_page_id}/draft",
    response_model=PlannedPageDraftResponse,
)
def create_or_refresh_planned_page_draft(
    planned_page_id: int,
    payload: PlannedPageDraftRequest,
    session: Session = Depends(get_session),
):
    try:
        generated, readiness = draft_planned_page(
            session,
            planned_page_id,
            expected_website_id=payload.website_id,
            allow_overwrite=payload.allow_overwrite,
        )
    except PlannedPageDraftingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    planned = session.get(PlannedPage, planned_page_id)
    if not planned or not generated.draft_content:
        raise HTTPException(status_code=500, detail="Draft linkage was not persisted.")
    return PlannedPageDraftResponse(
        planned_page_id=planned_page_id,
        generated_page_id=generated.id or 0,
        generation_status=generated.generation_status,
        planning_status=planned.planning_status,
        readiness=readiness,
        draft_content=generated.draft_content,
    )


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


@router.get(
    "/{plan_id}/drafting-eligibility",
    response_model=DraftingEligibilityManifest,
)
def read_drafting_eligibility(
    plan_id: int,
    session: Session = Depends(get_session),
):
    return _eligibility_call(read_manifest, session, plan_id)


@router.post(
    "/{plan_id}/drafting-eligibility/assess",
    response_model=DraftingEligibilityManifest,
)
def refresh_drafting_eligibility(
    plan_id: int,
    session: Session = Depends(get_session),
):
    return _eligibility_call(assess_site_plan, session, plan_id)


@router.get(
    "/{plan_id}/drafting-batch-manifest",
    response_model=DraftingBatchManifest,
)
def read_drafting_batch_manifest(
    plan_id: int,
    session: Session = Depends(get_session),
):
    return _eligibility_call(read_manifest, session, plan_id).batch_manifest


@router.post(
    "/{plan_id}/drafting-candidates/validate",
    response_model=CandidateDraftValidationResult,
)
def validate_drafting_candidates(
    plan_id: int,
    payload: list[CandidateDraftInput],
    session: Session = Depends(get_session),
):
    return _eligibility_call(
        validate_candidate_drafts,
        session,
        plan_id,
        payload,
    )


@router.put(
    "/drafting-eligibility/{assessment_id}/disposition",
    response_model=EligibilityDispositionRead,
)
def edit_drafting_eligibility_disposition(
    assessment_id: int,
    payload: EligibilityDispositionUpdate,
    session: Session = Depends(get_session),
):
    return _eligibility_call(
        record_disposition, session, assessment_id, payload
    )


@router.get(
    "/{plan_id}/draft-generation/runs",
    response_model=list[WebsiteDraftGenerationRunRead],
)
def read_website_draft_generation_runs(
    plan_id: int,
    session: Session = Depends(get_session),
):
    return _bulk_drafting_call(list_generation_runs, session, plan_id)


@router.get(
    "/draft-generation/runs/{run_id}",
    response_model=WebsiteDraftGenerationRunRead,
)
def read_website_draft_generation_run(
    run_id: int,
    session: Session = Depends(get_session),
):
    return _bulk_drafting_call(read_generation_run, session, run_id)


@router.post(
    "/{plan_id}/draft-generation/start",
    response_model=WebsiteDraftGenerationRunRead,
)
def start_website_draft_generation(
    plan_id: int,
    payload: WebsiteDraftGenerationRequest,
    session: Session = Depends(get_session),
):
    return _bulk_drafting_call(
        start_or_resume_generation,
        session,
        plan_id,
        website_id=payload.website_id,
        draft_limit=payload.draft_limit,
    )


@router.post(
    "/draft-generation/runs/{run_id}/resume",
    response_model=WebsiteDraftGenerationRunRead,
)
def resume_website_draft_generation(
    run_id: int,
    payload: WebsiteDraftGenerationRequest,
    session: Session = Depends(get_session),
):
    return _bulk_drafting_call(
        resume_generation,
        session,
        run_id,
        website_id=payload.website_id,
        draft_limit=payload.draft_limit,
    )


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except SitePlanningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _connection_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except SiteConnectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _coverage_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except SiteCoverageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _eligibility_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (DraftingEligibilityError, SiteCoverageError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _bulk_drafting_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (BulkDraftingError, DraftingEligibilityError, SiteCoverageError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _composition_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except PageCompositionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
