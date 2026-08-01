from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from time import perf_counter
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import (
    DraftingEligibilityAssessment,
    GeneratedPage,
    PlannedPage,
    SitePlan,
    WebsiteDraftGenerationItem,
    WebsiteDraftGenerationRun,
)
from app.schemas.bulk_drafting import (
    WebsiteDraftGenerationCounts,
    WebsiteDraftGenerationItemRead,
    WebsiteDraftGenerationRunRead,
)
from app.schemas.drafting_eligibility import DraftingEligibilityManifest
from app.services.drafting_eligibility import (
    DraftingEligibilityError,
    read_manifest,
    require_effective_drafting_eligibility,
)
from app.services.planned_page_drafting import (
    COMPATIBILITY_PAGE_TYPES,
    SUPPORTED_PAGE_TYPES,
    PlannedPageDraftingError,
    draft_planned_page,
)


SUPPORTED_BATCH_PAGE_TYPES = SUPPORTED_PAGE_TYPES | COMPATIBILITY_PAGE_TYPES
TERMINAL_OUTCOMES = {
    "generated",
    "already_drafted",
    "blocked",
    "deferred",
    "excluded",
    "stale",
    "consolidation_recommended",
    "unsupported",
    "error",
}


class BulkDraftingError(ValueError):
    pass


def start_or_resume_generation(
    session: Session,
    plan_id: int,
    *,
    website_id: int,
    draft_limit: int | None = None,
) -> WebsiteDraftGenerationRunRead:
    manifest = read_manifest(session, plan_id)
    if manifest.website_id != website_id:
        raise BulkDraftingError(
            "Site Plan does not belong to the selected Website."
        )
    manifest_hash, snapshot = _manifest_identity(manifest)
    run = session.exec(
        select(WebsiteDraftGenerationRun).where(
            WebsiteDraftGenerationRun.site_plan_id == plan_id,
            WebsiteDraftGenerationRun.manifest_hash == manifest_hash,
        )
    ).first()
    if run is None:
        run = _create_run(session, manifest, manifest_hash, snapshot)
    elif run.website_id != website_id:
        raise BulkDraftingError("Batch run Website ownership is invalid.")
    if run.status in {"completed", "completed_with_errors"}:
        return read_generation_run(session, run.id or 0)
    return _execute_run(session, run.id or 0, draft_limit=draft_limit)


def resume_generation(
    session: Session,
    run_id: int,
    *,
    website_id: int,
    draft_limit: int | None = None,
) -> WebsiteDraftGenerationRunRead:
    run = session.get(WebsiteDraftGenerationRun, run_id)
    if run is None:
        raise BulkDraftingError("Website draft generation run not found.")
    if run.website_id != website_id:
        raise BulkDraftingError(
            "Batch run does not belong to the selected Website."
        )
    if run.status in {"completed", "completed_with_errors"}:
        return read_generation_run(session, run_id)
    return _execute_run(session, run_id, draft_limit=draft_limit)


def read_generation_run(
    session: Session, run_id: int
) -> WebsiteDraftGenerationRunRead:
    run = session.get(WebsiteDraftGenerationRun, run_id)
    if run is None:
        raise BulkDraftingError("Website draft generation run not found.")
    items = list(
        session.exec(
            select(WebsiteDraftGenerationItem)
            .where(WebsiteDraftGenerationItem.run_id == run_id)
            .order_by(WebsiteDraftGenerationItem.ordinal)
        ).all()
    )
    return _run_read(run, items)


def list_generation_runs(
    session: Session, plan_id: int
) -> list[WebsiteDraftGenerationRunRead]:
    plan = session.get(SitePlan, plan_id)
    if plan is None:
        raise BulkDraftingError("Site Plan not found.")
    runs = list(
        session.exec(
            select(WebsiteDraftGenerationRun)
            .where(WebsiteDraftGenerationRun.site_plan_id == plan_id)
            .order_by(WebsiteDraftGenerationRun.id.desc())
        ).all()
    )
    return [read_generation_run(session, item.id or 0) for item in runs]


def _create_run(
    session: Session,
    manifest: DraftingEligibilityManifest,
    manifest_hash: str,
    snapshot: dict[str, Any],
) -> WebsiteDraftGenerationRun:
    now = datetime.now(UTC)
    run = WebsiteDraftGenerationRun(
        website_id=manifest.website_id,
        site_plan_id=manifest.site_plan_id,
        manifest_hash=manifest_hash,
        eligibility_algorithm_version=manifest.algorithm_version,
        status="preparing",
        manifest_snapshot=snapshot,
        expected_count=len(manifest.batch_manifest.items),
        eligible_count=manifest.batch_manifest.counts.eligible,
        progress_message="Preparing inventory...",
        started_at=now,
        updated_at=now,
    )
    session.add(run)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(WebsiteDraftGenerationRun).where(
                WebsiteDraftGenerationRun.site_plan_id
                == manifest.site_plan_id,
                WebsiteDraftGenerationRun.manifest_hash == manifest_hash,
            )
        ).one()
        return existing

    assessments = {
        item.planned_page_id: item for item in manifest.assessments
    }
    for ordinal, item in enumerate(manifest.batch_manifest.items, start=1):
        planned_page = (
            session.get(PlannedPage, item.planned_page_id)
            if item.planned_page_id is not None
            else None
        )
        existing_generated = (
            session.get(GeneratedPage, planned_page.generated_page_id)
            if planned_page is not None
            and planned_page.generated_page_id is not None
            else None
        )
        assessment = (
            assessments.get(item.planned_page_id)
            if item.planned_page_id is not None
            else None
        )
        outcome = (
            "already_drafted"
            if existing_generated is not None
            and existing_generated.website_id == manifest.website_id
            else (
                "pending"
                if item.classification == "eligible"
                else _classification_outcome(item.classification)
            )
        )
        session.add(
            WebsiteDraftGenerationItem(
                run_id=run.id or 0,
                website_id=manifest.website_id,
                site_plan_id=manifest.site_plan_id,
                planned_page_id=item.planned_page_id,
                inventory_key=item.inventory_key,
                ordinal=ordinal,
                page_type=item.page_type,
                working_name=item.working_name,
                manifest_classification=item.classification,
                outcome=outcome,
                reasons=list(
                    dict.fromkeys(
                        [
                            *item.reasons,
                            *(
                                [
                                    "Existing draft preserved; no mutation "
                                    "performed."
                                ]
                                if outcome == "already_drafted"
                                else []
                            ),
                        ]
                    )
                ),
                assessment_id=assessment.id if assessment else None,
                assessment_binding=_assessment_binding(assessment),
                generated_page_id=(
                    existing_generated.id
                    if outcome == "already_drafted"
                    else None
                ),
                generated_content_hash=(
                    _generated_hash(existing_generated)
                    if outcome == "already_drafted"
                    and existing_generated is not None
                    else None
                ),
                completed_at=now if outcome != "pending" else None,
            )
        )
    run.status = "running"
    run.progress_message = "Evaluating eligibility..."
    session.add(run)
    session.commit()
    session.refresh(run)
    _refresh_run_counts(session, run.id or 0)
    return session.get(WebsiteDraftGenerationRun, run.id or 0) or run


def _execute_run(
    session: Session,
    run_id: int,
    *,
    draft_limit: int | None,
) -> WebsiteDraftGenerationRunRead:
    run = session.get(WebsiteDraftGenerationRun, run_id)
    if run is None:
        raise BulkDraftingError("Website draft generation run not found.")
    if run.status not in {"preparing", "running", "interrupted"}:
        return read_generation_run(session, run_id)
    now = datetime.now(UTC)
    run.status = "running"
    run.last_resumed_at = now
    run.progress_message = "Evaluating eligibility..."
    run.updated_at = now
    session.add(run)
    session.commit()

    started = perf_counter()
    generated_this_call = 0
    pending = list(
        session.exec(
            select(WebsiteDraftGenerationItem)
            .where(
                WebsiteDraftGenerationItem.run_id == run_id,
                WebsiteDraftGenerationItem.outcome == "pending",
            )
            .order_by(WebsiteDraftGenerationItem.ordinal)
        ).all()
    )
    for item in pending:
        if draft_limit is not None and generated_this_call >= draft_limit:
            break
        _set_progress(session, run_id, item.ordinal, run.expected_count)
        created = _process_item(session, run_id, item.id or 0)
        if created:
            generated_this_call += 1

    run = session.get(WebsiteDraftGenerationRun, run_id)
    if run is None:
        raise BulkDraftingError("Website draft generation run disappeared.")
    _refresh_run_counts(session, run_id)
    run = session.get(WebsiteDraftGenerationRun, run_id) or run
    pending_count = session.exec(
        select(WebsiteDraftGenerationItem).where(
            WebsiteDraftGenerationItem.run_id == run_id,
            WebsiteDraftGenerationItem.outcome == "pending",
        )
    ).all()
    now = datetime.now(UTC)
    elapsed_ms = max(0, int((perf_counter() - started) * 1000))
    prior_duration = run.duration_ms or 0
    run.duration_ms = prior_duration + elapsed_ms
    if pending_count:
        run.status = "interrupted"
        run.progress_message = (
            f"Paused after {run.processed_count} of {run.expected_count}; "
            "resume will continue with remaining eligible Planned Pages."
        )
    else:
        run.status = (
            "completed_with_errors" if run.error_count else "completed"
        )
        run.completed_at = now
        run.progress_message = "Completed."
    run.updated_at = now
    session.add(run)
    session.commit()
    return read_generation_run(session, run_id)


def _process_item(session: Session, run_id: int, item_id: int) -> bool:
    item = session.get(WebsiteDraftGenerationItem, item_id)
    run = session.get(WebsiteDraftGenerationRun, run_id)
    if item is None or run is None or item.outcome != "pending":
        return False
    now = datetime.now(UTC)
    item.attempt_count += 1
    item.started_at = item.started_at or now
    item.updated_at = now
    session.add(item)
    session.commit()

    page = (
        session.get(PlannedPage, item.planned_page_id)
        if item.planned_page_id is not None
        else None
    )
    if page is None:
        _finish_item(
            session, item_id, "blocked", ["Planned Page no longer exists."]
        )
        return False
    if (
        page.website_id != run.website_id
        or page.site_plan_id != run.site_plan_id
    ):
        _finish_item(
            session,
            item_id,
            "error",
            ["Planned Page Website or Site Plan ownership changed."],
        )
        return False

    existing = (
        session.get(GeneratedPage, page.generated_page_id)
        if page.generated_page_id is not None
        else None
    )
    if page.generated_page_id is not None:
        if existing is None or existing.website_id != run.website_id:
            _finish_item(
                session,
                item_id,
                "error",
                ["Existing draft linkage is missing or outside the Website."],
            )
            return False
        _finish_item(
            session,
            item_id,
            "already_drafted",
            ["Existing draft preserved; no mutation performed."],
            generated=existing,
        )
        return False

    if page.page_type not in SUPPORTED_BATCH_PAGE_TYPES:
        _finish_item(
            session,
            item_id,
            "unsupported",
            [f"{page.page_type.replace('_', ' ').title()} drafting is deferred."],
        )
        return False

    try:
        assessment = require_effective_drafting_eligibility(
            session,
            page.id or 0,
            operation="deterministic batch drafting",
        )
        item = session.get(WebsiteDraftGenerationItem, item_id)
        if item is None:
            raise BulkDraftingError("Batch item disappeared.")
        item.assessment_id = assessment.id
        item.assessment_binding = _assessment_binding(assessment)
        session.add(item)
        session.commit()
        generated, _ = draft_planned_page(
            session,
            page.id or 0,
            expected_website_id=run.website_id,
            allow_overwrite=False,
        )
    except DraftingEligibilityError as exc:
        session.rollback()
        message = str(exc)
        outcome = "stale" if "stale" in message.lower() else "blocked"
        _finish_item(session, item_id, outcome, [message])
        return False
    except (PlannedPageDraftingError, BulkDraftingError) as exc:
        session.rollback()
        _finish_item(session, item_id, "blocked", [str(exc)])
        return False
    except Exception as exc:
        session.rollback()
        _finish_item(
            session,
            item_id,
            "error",
            [f"{type(exc).__name__}: {str(exc) or 'Draft generation failed.'}"],
        )
        return False

    _finish_item(
        session,
        item_id,
        "generated",
        ["Draft created from the current effective eligibility assessment."],
        generated=generated,
    )
    return True


def _finish_item(
    session: Session,
    item_id: int,
    outcome: str,
    reasons: list[str],
    *,
    generated: GeneratedPage | None = None,
) -> None:
    item = session.get(WebsiteDraftGenerationItem, item_id)
    if item is None:
        raise BulkDraftingError("Batch item not found.")
    item.outcome = outcome
    item.reasons = list(dict.fromkeys([*item.reasons, *reasons]))
    if generated is not None:
        item.generated_page_id = generated.id
        item.generated_content_hash = _generated_hash(generated)
    item.completed_at = datetime.now(UTC)
    item.updated_at = item.completed_at
    session.add(item)
    session.commit()
    _refresh_run_counts(session, item.run_id)


def _set_progress(
    session: Session, run_id: int, ordinal: int, total: int
) -> None:
    run = session.get(WebsiteDraftGenerationRun, run_id)
    if run is None:
        raise BulkDraftingError("Website draft generation run not found.")
    run.progress_message = f"Drafting {ordinal} of {total}..."
    run.updated_at = datetime.now(UTC)
    session.add(run)
    session.commit()


def _refresh_run_counts(session: Session, run_id: int) -> None:
    run = session.get(WebsiteDraftGenerationRun, run_id)
    if run is None:
        raise BulkDraftingError("Website draft generation run not found.")
    items = list(
        session.exec(
            select(WebsiteDraftGenerationItem).where(
                WebsiteDraftGenerationItem.run_id == run_id
            )
        ).all()
    )
    by_outcome: dict[str, int] = {}
    for item in items:
        by_outcome[item.outcome] = by_outcome.get(item.outcome, 0) + 1
    run.generated_count = by_outcome.get("generated", 0)
    run.already_drafted_count = by_outcome.get("already_drafted", 0)
    run.blocked_count = by_outcome.get("blocked", 0)
    run.deferred_count = by_outcome.get("deferred", 0)
    run.excluded_count = by_outcome.get("excluded", 0)
    run.stale_count = by_outcome.get("stale", 0)
    run.consolidation_count = by_outcome.get(
        "consolidation_recommended", 0
    )
    run.error_count = by_outcome.get("error", 0)
    unsupported = by_outcome.get("unsupported", 0)
    run.skipped_count = (
        run.blocked_count
        + run.deferred_count
        + run.excluded_count
        + run.stale_count
        + run.consolidation_count
        + run.error_count
        + unsupported
    )
    run.processed_count = sum(
        count
        for outcome, count in by_outcome.items()
        if outcome in TERMINAL_OUTCOMES
    )
    run.updated_at = datetime.now(UTC)
    session.add(run)
    session.commit()


def _manifest_identity(
    manifest: DraftingEligibilityManifest,
) -> tuple[str, dict[str, Any]]:
    assessments = {
        item.planned_page_id: item for item in manifest.assessments
    }
    snapshot = {
        "website_id": manifest.website_id,
        "site_plan_id": manifest.site_plan_id,
        "algorithm_version": manifest.algorithm_version,
        "source_snapshot": manifest.source_snapshot,
        "items": [
            {
                "inventory_key": item.inventory_key,
                "planned_page_id": item.planned_page_id,
                "page_type": item.page_type,
                "classification": item.classification,
                "assessment_status": item.assessment_status,
                "current": item.current,
                "effective_eligible": item.effective_eligible,
                "reasons": item.reasons,
                "assessment_binding": _assessment_binding(
                    assessments.get(item.planned_page_id)
                ),
            }
            for item in manifest.batch_manifest.items
        ],
    }
    encoded = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest(), snapshot


def _assessment_binding(assessment: Any | None) -> dict[str, Any]:
    if assessment is None:
        return {"present": False}
    return {
        "present": True,
        "id": assessment.id,
        "status": assessment.status,
        "algorithm_version": assessment.algorithm_version,
        "current": assessment.current,
        "effective_eligible": assessment.effective_eligible,
        "assessed_at": assessment.assessed_at.isoformat(),
        "coverage_binding": assessment.coverage_binding,
        "expected_inventory_binding": assessment.expected_inventory_binding,
        "planning_record_binding": assessment.planning_record_binding,
        "distinctness_brief_binding": assessment.distinctness_brief_binding,
    }


def _classification_outcome(classification: str) -> str:
    if classification in {
        "blocked",
        "excluded",
        "deferred",
        "stale",
        "consolidation_recommended",
    }:
        return classification
    return "error"


def _generated_hash(generated: GeneratedPage) -> str:
    value = {
        "id": generated.id,
        "website_id": generated.website_id,
        "page_type": generated.page_type,
        "page_slug": generated.page_slug,
        "draft_content": generated.draft_content,
        "content_body": generated.content_body,
    }
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _run_read(
    run: WebsiteDraftGenerationRun,
    items: list[WebsiteDraftGenerationItem],
) -> WebsiteDraftGenerationRunRead:
    unsupported = sum(1 for item in items if item.outcome == "unsupported")
    counts = WebsiteDraftGenerationCounts(
        expected=run.expected_count,
        eligible=run.eligible_count,
        generated=run.generated_count,
        already_drafted=run.already_drafted_count,
        skipped=run.skipped_count,
        blocked=run.blocked_count,
        deferred=run.deferred_count,
        excluded=run.excluded_count,
        stale=run.stale_count,
        consolidation_recommended=run.consolidation_count,
        unsupported=unsupported,
        errors=run.error_count,
    )
    return WebsiteDraftGenerationRunRead(
        id=run.id or 0,
        website_id=run.website_id,
        site_plan_id=run.site_plan_id,
        manifest_hash=run.manifest_hash,
        eligibility_algorithm_version=run.eligibility_algorithm_version,
        status=run.status,
        counts=counts,
        processed_count=run.processed_count,
        progress_total=run.expected_count,
        progress_message=run.progress_message,
        started_at=run.started_at,
        last_resumed_at=run.last_resumed_at,
        completed_at=run.completed_at,
        duration_ms=run.duration_ms,
        items=[
            WebsiteDraftGenerationItemRead(
                id=item.id or 0,
                inventory_key=item.inventory_key,
                ordinal=item.ordinal,
                planned_page_id=item.planned_page_id,
                generated_page_id=item.generated_page_id,
                page_type=item.page_type,
                working_name=item.working_name,
                manifest_classification=item.manifest_classification,
                outcome=item.outcome,
                reasons=item.reasons,
                attempt_count=item.attempt_count,
                generated_content_hash=item.generated_content_hash,
                started_at=item.started_at,
                completed_at=item.completed_at,
            )
            for item in items
        ],
    )
