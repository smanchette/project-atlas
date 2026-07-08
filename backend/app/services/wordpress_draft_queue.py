from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import ApprovalAudit, City, County, GeneratedPage, GeneratedPageRevision, Service
from app.schemas.wordpress import (
    WordPressDraftGateResult,
    WordPressDraftQueueItem,
    WordPressDraftQueueResponse,
)
from app.services.page_export import build_page_export_package
from app.services.wordpress_sandbox import get_wordpress_application_password, read_wordpress_settings


def build_wordpress_draft_queue(session: Session) -> WordPressDraftQueueResponse:
    settings = read_wordpress_settings(session)
    has_password = bool(get_wordpress_application_password())
    pages = session.exec(select(GeneratedPage).order_by(GeneratedPage.id)).all()
    cities = {item.id: item for item in session.exec(select(City)).all()}
    counties = {item.id: item for item in session.exec(select(County)).all()}
    services = {item.id: item for item in session.exec(select(Service)).all()}
    revision_counts, latest_revisions = _revision_summary(session)
    approval_counts = _approval_counts(session)

    items = [
        _queue_item(
            session,
            page,
            city=cities.get(page.city_id),
            county=counties.get(page.county_id),
            service=services.get(page.service_id),
            revision_count=revision_counts.get(page.id or 0, 0),
            latest_revision_at=latest_revisions.get(page.id or 0),
            approval_count=approval_counts.get(page.id or 0, 0),
            mode_is_sandbox=settings.publishing_mode == "sandbox",
            credentials_ready=bool(settings.site_url and settings.username and has_password),
        )
        for page in pages
    ]
    return WordPressDraftQueueResponse(
        total_count=len(items),
        eligible_count=sum(item.eligible for item in items),
        blocked_count=sum(not item.eligible and item.queue_group != "already_has_draft" for item in items),
        already_has_draft_count=sum(item.queue_group == "already_has_draft" for item in items),
        wordpress_mode=settings.publishing_mode,
        has_application_password=has_password,
        site_url_configured=bool(settings.site_url),
        username_configured=bool(settings.username),
        items=items,
    )


def _queue_item(
    session: Session,
    page: GeneratedPage,
    *,
    city: City | None,
    county: County | None,
    service: Service | None,
    revision_count: int,
    latest_revision_at: datetime | None,
    approval_count: int,
    mode_is_sandbox: bool,
    credentials_ready: bool,
) -> WordPressDraftQueueItem:
    package = build_page_export_package(session, page.id or 0)
    blockers = [warning for warning in package.warnings if warning.severity == "blocker"]
    warnings = [warning for warning in package.warnings if warning.severity == "warning"]
    qa_current = bool(
        page.qa_checked_at
        and (
            latest_revision_at is None
            or _timestamp(page.qa_checked_at) >= _timestamp(latest_revision_at)
        )
    )
    has_missing_media = any(warning.code in {"hero_missing", "alt_text_missing"} for warning in blockers)
    gates = [
        _gate("sandbox_mode", "WordPress mode is sandbox", mode_is_sandbox, "Set WordPress mode to Sandbox."),
        _gate("credentials_ready", "Connection credentials are available", credentials_ready, "Re-enter the WordPress application password after backend restart."),
        _gate("page_approved", "Atlas page is approved", page.status == "approved", "Approve the page in Atlas first."),
        _gate("qa_ready", "QA status is ready", page.qa_status == "ready" and page.qa_checked_at is not None, "Run QA and resolve all blockers."),
        _gate("qa_current", "QA is current after edits", qa_current, "Run QA again after the latest manual edit."),
        _gate("export_clear", "Export package has no blockers", not blockers, "Resolve export blockers before creating a draft."),
        _gate("slug_unique", "Slug has no conflicts", not package.slug_conflicts, "Resolve the slug conflict before creating a draft."),
        _gate("not_already_created", "No existing WordPress draft reference", page.wordpress_post_id is None, "This page already has a WordPress draft reference."),
        _gate("draft_status", "Payload status is draft", True, "WordPress payload status must be draft."),
    ]
    eligible = all(gate.passed for gate in gates)
    group = _group(
        page,
        mode_is_sandbox=mode_is_sandbox,
        credentials_ready=credentials_ready,
        qa_current=qa_current,
        has_missing_media=has_missing_media,
        blockers=blockers,
    )
    return WordPressDraftQueueItem(
        page_id=page.id or 0,
        page_title=page.page_title,
        city=city.city_name if city else None,
        county=county.county_name if county else None,
        service=service.service_name if service else None,
        atlas_status=page.status,
        qa_status=page.qa_status,
        qa_checked_at=page.qa_checked_at.isoformat() if page.qa_checked_at else None,
        revision_count=revision_count,
        latest_revision_at=latest_revision_at.isoformat() if latest_revision_at else None,
        approval_audit_count=approval_count,
        export_ready=package.export_ready,
        export_blocker_count=len(blockers),
        export_warning_count=len(warnings),
        slug=package.url_slug,
        slug_conflicts=package.slug_conflicts,
        wordpress_post_id=page.wordpress_post_id,
        wordpress_status=page.wordpress_status,
        wordpress_url=page.wordpress_url,
        queue_group=group,
        eligible=eligible,
        gate_results=gates,
        next_required_action=_next_action(group),
    )


def _group(
    page: GeneratedPage,
    *,
    mode_is_sandbox: bool,
    credentials_ready: bool,
    qa_current: bool,
    has_missing_media: bool,
    blockers: list[Any],
) -> str:
    if page.wordpress_post_id is not None:
        return "already_has_draft"
    if not mode_is_sandbox or not credentials_ready:
        return "blocked_credentials"
    if page.status != "approved":
        return "blocked_approval"
    if page.qa_status != "ready" or page.qa_checked_at is None:
        return "blocked_qa"
    if not qa_current:
        return "blocked_stale_qa"
    if has_missing_media:
        return "blocked_missing_media"
    if blockers:
        return "blocked_export"
    return "eligible"


def _next_action(group: str) -> str:
    return {
        "eligible": "Run dry run, review the exact payload, then confirm one draft only.",
        "blocked_approval": "Approve the page explicitly in Atlas after QA is ready.",
        "blocked_qa": "Run QA and resolve blockers or warnings.",
        "blocked_stale_qa": "Run QA again after the latest manual edit.",
        "blocked_missing_media": "Assign and review required hero media and alt text.",
        "already_has_draft": "Review the saved WordPress draft reference. Updates are not available yet.",
        "blocked_credentials": "Set Sandbox mode and re-enter the WordPress application password.",
        "blocked_export": "Resolve export blockers such as slug or metadata issues.",
    }[group]


def _revision_summary(session: Session) -> tuple[dict[int, int], dict[int, datetime]]:
    rows = session.exec(
        select(
            GeneratedPageRevision.generated_page_id,
            func.count(GeneratedPageRevision.id),
            func.max(GeneratedPageRevision.created_at),
        ).group_by(GeneratedPageRevision.generated_page_id)
    ).all()
    return (
        {page_id: count for page_id, count, _ in rows},
        {page_id: created_at for page_id, _, created_at in rows if created_at},
    )


def _approval_counts(session: Session) -> dict[int, int]:
    rows = session.exec(
        select(ApprovalAudit.generated_page_id, func.count(ApprovalAudit.id)).group_by(
            ApprovalAudit.generated_page_id
        )
    ).all()
    return {page_id: count for page_id, count in rows}


def _gate(code: str, label: str, passed: bool, failure_message: str) -> WordPressDraftGateResult:
    return WordPressDraftGateResult(
        code=code,
        label=label,
        passed=passed,
        message="Passed." if passed else failure_message,
    )


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()
