from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models import (
    GeneratedPage,
    ImageMetadata,
    PageImageAssignment,
    PlannedPage,
    Website,
    WebsiteMediaPlanningRecord,
)
from app.schemas.entities import ImageMetadataRead
from app.schemas.media import (
    AssignedMediaRead,
    MediaAssignmentCreateRequest,
    MediaAssignmentOrderRequest,
    MediaAssignmentRequest,
    MediaAssignmentUpdateRequest,
)
from app.services.website_media_safety import is_image_metadata_excluded

router = APIRouter(prefix="/generated-pages", tags=["page media"])

ALLOWED_IMAGE_ROLES = {"hero", "service", "support"}
ALLOWED_DISPLAY_PRESETS = {
    "hero_desktop",
    "hero_mobile",
    "card_thumbnail",
    "square",
    "original",
}
DEFAULT_PRESETS = {
    "hero": "hero_desktop",
    "service": "card_thumbnail",
    "support": "card_thumbnail",
}


@router.get("/{page_id}/media", response_model=list[AssignedMediaRead])
def list_page_media(
    page_id: int,
    session: Session = Depends(get_session),
) -> list[AssignedMediaRead]:
    _get_page(session, page_id)
    assignments = session.exec(
        select(PageImageAssignment)
        .where(
            PageImageAssignment.generated_page_id == page_id,
            PageImageAssignment.status == "active",
        )
        .order_by(
            PageImageAssignment.image_role,
            PageImageAssignment.sort_order,
            PageImageAssignment.id,
        )
    ).all()
    if any(
        _assignment_uses_excluded_image(session, assignment)
        for assignment in assignments
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Active assignment references media excluded by the Website-scoped "
                "external-media safety policy"
            ),
        )
    return [_serialize_assignment(session, assignment) for assignment in assignments]


@router.get("/{page_id}/media/candidates", response_model=list[ImageMetadataRead])
def list_page_media_candidates(
    page_id: int,
    session: Session = Depends(get_session),
) -> list[ImageMetadataRead]:
    page = _get_page(session, page_id)
    website = _website_for_page(session, page)
    candidates = session.exec(
        select(ImageMetadata)
        .where(ImageMetadata.business_id == page.business_id)
        .order_by(ImageMetadata.id)
    ).all()
    compatible: list[ImageMetadataRead] = []
    for image in candidates:
        try:
            _validate_image_for_page(page, image, website)
        except HTTPException:
            continue
        compatible.append(ImageMetadataRead.model_validate(image))
    return compatible


@router.post("/{page_id}/media", response_model=AssignedMediaRead, status_code=201)
def create_page_media(
    page_id: int,
    payload: MediaAssignmentCreateRequest,
    session: Session = Depends(get_session),
) -> AssignedMediaRead:
    page = _get_page(session, page_id)
    _require_legacy_page_media_workflow(session, page)
    role = _normalize_role(payload.image_role)
    image = _get_compatible_image(session, page, payload.image_metadata_id)
    _ensure_not_duplicate(session, page_id, image.id or 0, role)
    if role == "hero":
        _ensure_hero_available(session, page_id)

    assignment = PageImageAssignment(
        generated_page_id=page_id,
        image_metadata_id=image.id or 0,
        image_role=role,
        sort_order=(
            payload.sort_order
            if payload.sort_order is not None
            else _next_sort_order(session, page_id, role)
        ),
        override_focal_x=payload.override_focal_x,
        override_focal_y=payload.override_focal_y,
        override_alt_text=_clean_optional(payload.override_alt_text),
        display_preset=_normalize_preset(payload.display_preset, role),
        status="active",
    )
    _invalidate_page_qa(page)
    session.add(page)
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return _serialize_assignment(session, assignment)


@router.patch(
    "/{page_id}/media/assignments/{assignment_id}",
    response_model=AssignedMediaRead,
)
def update_page_media(
    page_id: int,
    assignment_id: int,
    payload: MediaAssignmentUpdateRequest,
    session: Session = Depends(get_session),
) -> AssignedMediaRead:
    page = _get_page(session, page_id)
    _require_legacy_page_media_workflow(session, page)
    assignment = _get_assignment(session, page_id, assignment_id)
    _require_legacy_assignment_mutation(assignment)
    _require_assignment_not_excluded(session, assignment)
    updates = payload.model_dump(exclude_unset=True)
    if "display_preset" in updates:
        assignment.display_preset = _normalize_preset(
            updates.pop("display_preset"),
            assignment.image_role,
        )
    if "override_alt_text" in updates:
        assignment.override_alt_text = _clean_optional(
            updates.pop("override_alt_text")
        )
    for key, value in updates.items():
        setattr(assignment, key, value)
    assignment.updated_at = datetime.now(UTC)
    _invalidate_page_qa(page)
    session.add(page)
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return _serialize_assignment(session, assignment)


@router.delete("/{page_id}/media/assignments/{assignment_id}")
def remove_page_media_assignment(
    page_id: int,
    assignment_id: int,
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    page = _get_page(session, page_id)
    _require_legacy_page_media_workflow(session, page)
    assignment = _get_assignment(session, page_id, assignment_id)
    _require_legacy_assignment_mutation(assignment)
    _invalidate_page_qa(page)
    session.add(page)
    session.delete(assignment)
    session.commit()
    return {"ok": True}


@router.put("/{page_id}/media/order/{image_role}", response_model=list[AssignedMediaRead])
def reorder_page_media(
    page_id: int,
    image_role: str,
    payload: MediaAssignmentOrderRequest,
    session: Session = Depends(get_session),
) -> list[AssignedMediaRead]:
    role = _normalize_role(image_role)
    page = _get_page(session, page_id)
    _require_legacy_page_media_workflow(session, page)
    assignments = session.exec(
        select(PageImageAssignment).where(
            PageImageAssignment.generated_page_id == page_id,
            PageImageAssignment.image_role == role,
            PageImageAssignment.status == "active",
        )
    ).all()
    for assignment in assignments:
        _require_legacy_assignment_mutation(assignment)
        _require_assignment_not_excluded(session, assignment)
    assignment_by_id = {
        assignment.id: assignment
        for assignment in assignments
        if assignment.id is not None
    }
    if (
        len(payload.assignment_ids) != len(set(payload.assignment_ids))
        or set(payload.assignment_ids) != set(assignment_by_id)
    ):
        raise HTTPException(
            status_code=422,
            detail="Order must include every active assignment in this role exactly once",
        )
    for index, assignment_id in enumerate(payload.assignment_ids):
        assignment = assignment_by_id[assignment_id]
        assignment.sort_order = index * 10
        assignment.updated_at = datetime.now(UTC)
        session.add(assignment)
    _invalidate_page_qa(page)
    session.add(page)
    session.commit()
    ordered = [assignment_by_id[assignment_id] for assignment_id in payload.assignment_ids]
    for assignment in ordered:
        session.refresh(assignment)
    return [_serialize_assignment(session, assignment) for assignment in ordered]


@router.put("/{page_id}/media/{image_role}", response_model=AssignedMediaRead)
def assign_page_media(
    page_id: int,
    image_role: str,
    payload: MediaAssignmentRequest,
    session: Session = Depends(get_session),
) -> AssignedMediaRead:
    role = _normalize_role(image_role)
    page = _get_page(session, page_id)
    _require_legacy_page_media_workflow(session, page)
    image = _get_compatible_image(session, page, payload.image_metadata_id)

    if role == "hero":
        assignment = session.exec(
            select(PageImageAssignment).where(
                PageImageAssignment.generated_page_id == page_id,
                PageImageAssignment.image_role == role,
            )
        ).first()
        if assignment:
            _require_legacy_assignment_mutation(assignment)
            duplicate = session.exec(
                select(PageImageAssignment).where(
                    PageImageAssignment.generated_page_id == page_id,
                    PageImageAssignment.image_metadata_id == image.id,
                    PageImageAssignment.image_role == role,
                    PageImageAssignment.id != assignment.id,
                )
            ).first()
            if duplicate:
                raise HTTPException(
                    status_code=409,
                    detail="This image is already assigned to the page in this role",
                )
            assignment.image_metadata_id = image.id or 0
            assignment.status = "active"
            assignment.updated_at = datetime.now(UTC)
        else:
            assignment = PageImageAssignment(
                generated_page_id=page_id,
                image_metadata_id=image.id or 0,
                image_role=role,
                sort_order=0,
                display_preset=DEFAULT_PRESETS[role],
                status="active",
            )
    else:
        existing = session.exec(
            select(PageImageAssignment).where(
                PageImageAssignment.generated_page_id == page_id,
                PageImageAssignment.image_metadata_id == image.id,
                PageImageAssignment.image_role == role,
            )
        ).first()
        if existing:
            _require_legacy_assignment_mutation(existing)
            return _serialize_assignment(session, existing)
        assignment = PageImageAssignment(
            generated_page_id=page_id,
            image_metadata_id=image.id or 0,
            image_role=role,
            sort_order=_next_sort_order(session, page_id, role),
            display_preset=DEFAULT_PRESETS[role],
            status="active",
        )

    session.add(assignment)
    _invalidate_page_qa(page)
    session.add(page)
    session.commit()
    session.refresh(assignment)
    return _serialize_assignment(session, assignment)


@router.delete("/{page_id}/media/{image_role}")
def remove_page_media(
    page_id: int,
    image_role: str,
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    role = _normalize_role(image_role)
    page = _get_page(session, page_id)
    _require_legacy_page_media_workflow(session, page)
    assignment = session.exec(
        select(PageImageAssignment)
        .where(
            PageImageAssignment.generated_page_id == page_id,
            PageImageAssignment.image_role == role,
        )
        .order_by(PageImageAssignment.sort_order, PageImageAssignment.id)
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Page media assignment not found")
    _require_legacy_assignment_mutation(assignment)
    _invalidate_page_qa(page)
    session.add(page)
    session.delete(assignment)
    session.commit()
    return {"ok": True}


def _get_page(session: Session, page_id: int) -> GeneratedPage:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    return page


def _require_legacy_page_media_workflow(
    session: Session,
    page: GeneratedPage,
) -> None:
    planned_page = session.exec(
        select(PlannedPage).where(
            PlannedPage.generated_page_id == page.id,
        )
    ).first()
    if planned_page is None:
        return
    planning_record = session.exec(
        select(WebsiteMediaPlanningRecord).where(
            WebsiteMediaPlanningRecord.site_plan_id == planned_page.site_plan_id,
        )
    ).first()
    if planning_record is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Governed page-media assignments must use the Website-scoped Page Media "
                "workspace after a media plan exists for this Site Plan."
            ),
        )


def _get_assignment(
    session: Session,
    page_id: int,
    assignment_id: int,
) -> PageImageAssignment:
    assignment = session.get(PageImageAssignment, assignment_id)
    if not assignment or assignment.generated_page_id != page_id:
        raise HTTPException(status_code=404, detail="Page media assignment not found")
    return assignment


def _get_compatible_image(
    session: Session,
    page: GeneratedPage,
    image_id: int,
) -> ImageMetadata:
    image = session.get(ImageMetadata, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image metadata not found")
    website = _website_for_page(session, page)
    _validate_image_for_page(page, image, website)
    return image


def _normalize_role(image_role: str) -> str:
    role = image_role.strip().lower()
    if role not in ALLOWED_IMAGE_ROLES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_ROLES))
        raise HTTPException(
            status_code=422,
            detail=f"Image role must be one of: {allowed}",
        )
    return role


def _normalize_preset(display_preset: str | None, image_role: str) -> str:
    preset = (display_preset or DEFAULT_PRESETS[image_role]).strip().lower()
    if preset not in ALLOWED_DISPLAY_PRESETS:
        allowed = ", ".join(sorted(ALLOWED_DISPLAY_PRESETS))
        raise HTTPException(
            status_code=422,
            detail=f"Display preset must be one of: {allowed}",
        )
    return preset


def _ensure_not_duplicate(
    session: Session,
    page_id: int,
    image_id: int,
    role: str,
) -> None:
    duplicate = session.exec(
        select(PageImageAssignment).where(
            PageImageAssignment.generated_page_id == page_id,
            PageImageAssignment.image_metadata_id == image_id,
            PageImageAssignment.image_role == role,
        )
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail="This image is already assigned to the page in this role",
        )


def _ensure_hero_available(session: Session, page_id: int) -> None:
    existing = session.exec(
        select(PageImageAssignment).where(
            PageImageAssignment.generated_page_id == page_id,
            PageImageAssignment.image_role == "hero",
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="A hero image is already assigned to this page",
        )


def _next_sort_order(session: Session, page_id: int, role: str) -> int:
    assignments = session.exec(
        select(PageImageAssignment).where(
            PageImageAssignment.generated_page_id == page_id,
            PageImageAssignment.image_role == role,
        )
    ).all()
    return max((assignment.sort_order for assignment in assignments), default=0) + 10


def _validate_image_for_page(
    page: GeneratedPage,
    image: ImageMetadata,
    website: Website,
) -> None:
    if is_image_metadata_excluded(website, image):
        raise HTTPException(
            status_code=409,
            detail=(
                "Image is excluded by the Website-scoped external-media safety policy"
            ),
        )
    governed_identity = any(
        value is not None
        for value in (
            image.website_id,
            image.media_key,
            image.media_version,
            image.managed_storage_path,
            image.approval_version,
        )
    )
    if image.governance_status != "legacy_unverified" or governed_identity:
        raise HTTPException(
            status_code=409,
            detail=(
                "Governed page media must be assigned through its Website-scoped "
                "media requirement."
            ),
        )
    if image.business_id != page.business_id:
        raise HTTPException(status_code=409, detail="Image belongs to a different business")
    if image.service_id is not None and image.service_id != page.service_id:
        raise HTTPException(status_code=409, detail="Image belongs to a different service")
    if image.city_id is not None and image.city_id != page.city_id:
        raise HTTPException(status_code=409, detail="Image belongs to a different city")
    if image.county_id is not None and image.county_id != page.county_id:
        raise HTTPException(status_code=409, detail="Image belongs to a different county")
    if image.review_status != "reviewed":
        raise HTTPException(status_code=409, detail="Image must be reviewed before assignment")
    if not image.reviewed_alt_text:
        raise HTTPException(
            status_code=409,
            detail="Image requires reviewed alt text before assignment",
        )
    if not image.asset_url:
        raise HTTPException(
            status_code=409,
            detail="Image requires an asset URL before assignment",
        )


def _serialize_assignment(
    session: Session,
    assignment: PageImageAssignment,
) -> AssignedMediaRead:
    image = session.get(ImageMetadata, assignment.image_metadata_id)
    if not image:
        raise HTTPException(status_code=500, detail="Assigned image metadata is missing")
    page = _get_page(session, assignment.generated_page_id)
    website = _website_for_page(session, page)
    if is_image_metadata_excluded(website, image):
        raise HTTPException(
            status_code=409,
            detail=(
                "Assigned image is excluded by the Website-scoped external-media "
                "safety policy"
            ),
        )
    return AssignedMediaRead(
        assignment_id=assignment.id or 0,
        generated_page_id=assignment.generated_page_id,
        image_role=assignment.image_role,
        sort_order=assignment.sort_order,
        override_focal_x=assignment.override_focal_x,
        override_focal_y=assignment.override_focal_y,
        override_alt_text=assignment.override_alt_text,
        display_preset=assignment.display_preset,
        effective_focal_x=(
            assignment.override_focal_x
            if assignment.override_focal_x is not None
            else image.focal_x
        ),
        effective_focal_y=(
            assignment.override_focal_y
            if assignment.override_focal_y is not None
            else image.focal_y
        ),
        effective_alt_text=(
            assignment.override_alt_text or image.reviewed_alt_text or image.alt_text or ""
        ),
        status=assignment.status,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
        image=ImageMetadataRead.model_validate(image),
    )


def _clean_optional(value: str | None) -> str | None:
    cleaned = value.strip() if value else ""
    return cleaned or None


def _website_for_page(session: Session, page: GeneratedPage) -> Website:
    website = session.get(Website, page.website_id)
    if not website:
        raise HTTPException(
            status_code=409,
            detail="Generated Page does not resolve to an existing Website",
        )
    return website


def _assignment_uses_excluded_image(
    session: Session,
    assignment: PageImageAssignment,
) -> bool:
    page = session.get(GeneratedPage, assignment.generated_page_id)
    image = session.get(ImageMetadata, assignment.image_metadata_id)
    website = session.get(Website, page.website_id) if page else None
    return is_image_metadata_excluded(website, image)


def _require_assignment_not_excluded(
    session: Session,
    assignment: PageImageAssignment,
) -> None:
    if _assignment_uses_excluded_image(session, assignment):
        raise HTTPException(
            status_code=409,
            detail=(
                "Assignment references media excluded by the Website-scoped "
                "external-media safety policy"
            ),
        )


def _require_legacy_assignment_mutation(assignment: PageImageAssignment) -> None:
    governed_binding = any(
        value is not None
        for value in (
            assignment.website_id,
            assignment.site_plan_id,
            assignment.planned_page_id,
            assignment.media_requirement_id,
            assignment.assignment_version,
            assignment.media_version,
            assignment.placement_contract_version,
        )
    )
    if governed_binding:
        raise HTTPException(
            status_code=409,
            detail=(
                "Governed page-media assignments cannot be changed through the legacy "
                "Generated Page media endpoint. Use the Website-scoped page-media workflow."
            ),
        )


def _invalidate_page_qa(page: GeneratedPage) -> None:
    page.qa_status = "not_run"
    page.qa_result = None
    page.qa_checked_at = None
