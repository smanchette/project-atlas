from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import (
    ApprovalAudit,
    City,
    County,
    GeneratedPage,
    GeneratedPageRevision,
    ImageMetadata,
    PageImageAssignment,
    Service,
)
from app.schemas.approval_queue import ApprovalQueueItem, ApprovalQueueResponse


def build_approval_queue(session: Session) -> ApprovalQueueResponse:
    pages = list(session.exec(select(GeneratedPage).order_by(GeneratedPage.id)).all())
    cities = {item.id: item for item in session.exec(select(City)).all()}
    counties = {item.id: item for item in session.exec(select(County)).all()}
    services = {item.id: item for item in session.exec(select(Service)).all()}
    revision_counts, latest_revisions = _revision_summary(session)
    approval_counts = _count_by_page(session, ApprovalAudit)
    hero_statuses = _hero_statuses(session)

    items = [
        _queue_item(
            page,
            city=cities.get(page.city_id),
            county=counties.get(page.county_id),
            service=services.get(page.service_id),
            revision_count=revision_counts.get(page.id or 0, 0),
            latest_revision_at=latest_revisions.get(page.id or 0),
            approval_count=approval_counts.get(page.id or 0, 0),
            hero_image_status=hero_statuses.get(page.id or 0, "missing"),
        )
        for page in pages
    ]
    return ApprovalQueueResponse(total_count=len(items), items=items)


def _queue_item(
    page: GeneratedPage,
    *,
    city: City | None,
    county: County | None,
    service: Service | None,
    revision_count: int,
    latest_revision_at: datetime | None,
    approval_count: int,
    hero_image_status: str,
) -> ApprovalQueueItem:
    has_blockers = page.qa_status == "blocked" or _qa_count(page.qa_result, "failed_count", "fail") > 0
    has_warnings = (
        page.qa_status == "needs_review"
        or _qa_count(page.qa_result, "warning_count", "warning") > 0
    )
    edited_since_last_qa = bool(
        latest_revision_at
        and (
            page.qa_checked_at is None
            or _utc_timestamp(latest_revision_at) > _utc_timestamp(page.qa_checked_at)
        )
    )
    missing_media = hero_image_status != "reviewed"
    approved_but_unpublished = page.status == "approved" and not page.wordpress_url
    is_ready_for_approval = bool(
        page.status == "draft"
        and page.qa_status == "ready"
        and page.qa_checked_at
        and not has_blockers
        and not has_warnings
        and not edited_since_last_qa
        and not missing_media
    )
    needs_manual_review = bool(
        page.status == "draft"
        and (
            page.qa_status == "not_run"
            or has_blockers
            or has_warnings
            or edited_since_last_qa
            or missing_media
        )
    )

    return ApprovalQueueItem(
        page_id=page.id or 0,
        page_title=page.page_title,
        city_id=page.city_id,
        city_name=city.city_name if city else "",
        county_id=page.county_id,
        county_name=county.county_name if county else "",
        service_id=page.service_id,
        service_name=service.service_name if service else "",
        page_status=page.status,
        qa_status=page.qa_status,
        qa_checked_at=page.qa_checked_at,
        latest_revision_at=latest_revision_at,
        revision_count=revision_count,
        approval_history_count=approval_count,
        hero_image_status=hero_image_status,
        last_reviewed_at=page.last_reviewed_at,
        internal_notes_snippet=_notes_snippet(page.internal_notes),
        is_ready_for_approval=is_ready_for_approval,
        has_blockers=has_blockers,
        has_warnings=has_warnings,
        edited_since_last_qa=edited_since_last_qa,
        approved_but_unpublished=approved_but_unpublished,
        missing_media=missing_media,
        needs_manual_review=needs_manual_review,
        next_recommended_action=_next_action(
            page,
            is_ready_for_approval=is_ready_for_approval,
            has_blockers=has_blockers,
            has_warnings=has_warnings,
            edited_since_last_qa=edited_since_last_qa,
            approved_but_unpublished=approved_but_unpublished,
            missing_media=missing_media,
        ),
    )


def _revision_summary(session: Session) -> tuple[dict[int, int], dict[int, datetime]]:
    rows = session.exec(
        select(
            GeneratedPageRevision.generated_page_id,
            func.count(GeneratedPageRevision.id),
            func.max(GeneratedPageRevision.created_at),
        ).group_by(GeneratedPageRevision.generated_page_id)
    ).all()
    counts = {page_id: count for page_id, count, _ in rows}
    latest = {page_id: created_at for page_id, _, created_at in rows if created_at}
    return counts, latest


def _count_by_page(session: Session, model: Any) -> dict[int, int]:
    rows = session.exec(
        select(model.generated_page_id, func.count(model.id)).group_by(
            model.generated_page_id
        )
    ).all()
    return {page_id: count for page_id, count in rows}


def _hero_statuses(session: Session) -> dict[int, str]:
    assignments = session.exec(
        select(PageImageAssignment).where(
            PageImageAssignment.image_role == "hero",
            PageImageAssignment.status == "active",
        )
    ).all()
    statuses: dict[int, list[str]] = defaultdict(list)
    for assignment in assignments:
        image = session.get(ImageMetadata, assignment.image_metadata_id)
        if not image or image.review_status != "reviewed":
            status = "unreviewed"
        elif not (
            (assignment.override_alt_text or "").strip()
            or (image.reviewed_alt_text or "").strip()
            or (image.alt_text or "").strip()
        ):
            status = "missing_alt_text"
        else:
            status = "reviewed"
        statuses[assignment.generated_page_id].append(status)

    rank = {"unreviewed": 0, "missing_alt_text": 1, "reviewed": 2}
    return {
        page_id: max(page_statuses, key=lambda status: rank[status])
        for page_id, page_statuses in statuses.items()
    }


def _qa_count(result: dict[str, Any] | None, count_key: str, item_status: str) -> int:
    if not result:
        return 0
    value = result.get(count_key)
    if isinstance(value, int):
        return value
    checks = result.get("checks")
    if not isinstance(checks, list):
        return 0
    return sum(
        isinstance(item, dict) and item.get("status") == item_status
        for item in checks
    )


def _notes_snippet(notes: str | None) -> str | None:
    normalized = " ".join((notes or "").split())
    if not normalized:
        return None
    return normalized if len(normalized) <= 120 else f"{normalized[:117]}..."


def _utc_timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _next_action(
    page: GeneratedPage,
    *,
    is_ready_for_approval: bool,
    has_blockers: bool,
    has_warnings: bool,
    edited_since_last_qa: bool,
    approved_but_unpublished: bool,
    missing_media: bool,
) -> str:
    if approved_but_unpublished:
        return "Hold for a future explicit publishing workflow."
    if page.status == "published":
        return "No approval queue action is required."
    if page.qa_status == "not_run":
        return "Run QA."
    if edited_since_last_qa:
        return "Run QA again after the latest manual edit."
    if missing_media:
        return "Assign and review a complete hero image."
    if has_blockers:
        return "Open issues and resolve QA blockers."
    if has_warnings:
        return "Review QA warnings and confirm the page manually."
    if is_ready_for_approval:
        return "Review the preview, then approve explicitly when satisfied."
    return "Review the page status and QA details."
