"""Narrow revision-safe refresh for legacy automatic City-Service CTAs.

This module exists only for the structured generator transition that removed
automatically appended license/operator copy.  It deliberately has no API
route, scheduler, generic copy rules, or active-database override.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping

from sqlalchemy import text
from sqlmodel import Session, select

from app.models import (
    Brand,
    BrandAsset,
    Business,
    City,
    County,
    GeneratedPage,
    GeneratedPageQAResult,
    GeneratedPageRevision,
    ImageMetadata,
    InternalLinkIntent,
    NavigationItem,
    NavigationSet,
    PageComposition,
    PageCompositionRevision,
    PageImageAssignment,
    PlannedPage,
    PlannedPageMediaRequirement,
    ScopedMediaAuthorization,
    SemanticComponentDefinition,
    Service,
    SitePlan,
    Theme,
    Website,
    WebsiteIdentity,
    WebsiteIdentityAssetAssignment,
    WebsiteMediaPlanningRecord,
    WebsiteThemeSelection,
)
from app.schemas.generation import DraftContent
from app.services.approval_audit import draft_content_hash
from app.services.draft_generation import (
    GenerationContext,
    build_automatic_public_call_to_action,
    load_generation_context,
    render_content_body,
    validate_safe_content,
)
from app.services.page_composition import (
    canonical_utc_timestamp,
    read_composition_for_generated_page,
    refresh_site_plan_compositions,
)
from app.services.page_composition_history import current_composition_revision
from app.services.page_editor import append_generated_page_revision
from app.services.page_qa import (
    effective_page_qa_state,
    is_exact_legacy_city_service_qa_predecessor,
    save_page_qa,
)
from app.services.website_context import website_config_value


MANIFEST_SCHEMA = "project-atlas-automatic-cta-refresh-manifest@1"
SOURCE_OWNER = "backend/app/services/draft_generation.py:DeterministicMockProvider.generate"
LEGACY_SOURCE_COMMIT = "bfcbcf098bc706f7928cfbe3aa23268e2654a4e5"
AUTOMATIC_CLASSIFICATION = "legacy_deterministic_mock_cta_bfcbcf0_exact"
EXCLUDED_CLASSIFICATION = "non_city_service_source_path"
CUSTOM_CLASSIFICATION = "city_service_cta_not_owned_by_exact_legacy_generator"
ALREADY_CORRECTED_CLASSIFICATION = "corrected_deterministic_mock_cta_exact"
REFRESH_ACTOR = "automatic-cta-refresh"
REFRESH_REASON = "Remove legacy automatic credential sentence from public CTA"
FAILURE_POINTS = {
    "before_first_page",
    "after_first_page",
    "at_midpoint",
    "after_drafts_before_composition",
    "after_composition_before_qa",
    "immediately_before_commit",
}
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_AUTHORITATIVE_SOURCE_TABLES = tuple(
    sorted(
        {
            model.__tablename__
            for model in (
                Brand,
                BrandAsset,
                Business,
                City,
                County,
                GeneratedPage,
                GeneratedPageQAResult,
                GeneratedPageRevision,
                ImageMetadata,
                InternalLinkIntent,
                NavigationItem,
                NavigationSet,
                PageImageAssignment,
                PageCompositionRevision,
                PlannedPage,
                PlannedPageMediaRequirement,
                ScopedMediaAuthorization,
                SemanticComponentDefinition,
                Service,
                SitePlan,
                Theme,
                Website,
                WebsiteIdentity,
                WebsiteIdentityAssetAssignment,
                WebsiteMediaPlanningRecord,
                WebsiteThemeSelection,
            )
        }
    )
)


class AutomaticCTARefreshError(ValueError):
    """The exact refresh manifest or current state failed closed."""


class InjectedAutomaticCTARefreshFailure(RuntimeError):
    """Controlled rehearsal-only failure that the caller must roll back."""


def legacy_automatic_public_call_to_action(context: GenerationContext) -> str:
    """Reconstruct the exact predecessor generator output for ownership proof."""

    business = context.business
    website = context.website_context
    return (
        f"To discuss {context.service.service_name.lower()} in {context.city.city_name}, "
        f"contact {business.company_name} at {business.phone or 'the office'} or "
        f"{business.email or website.website.public_url or 'through the company website'}. "
        f"Florida license {business.license_number or 'information available on request'}; "
        f"certified operator {business.certified_operator or 'information available on request'}."
    )


def automatic_cta_refresh_manifest_sha256(manifest: Mapping[str, Any]) -> str:
    body = {key: deepcopy(value) for key, value in manifest.items() if key != "manifest_sha256"}
    return _canonical_hash(body)


def build_automatic_cta_refresh_manifest(
    session: Session,
    plan_id: int,
    *,
    task_identity: str,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Build one read-only exact inventory; the caller owns transaction rollback."""

    plan = session.get(SitePlan, plan_id)
    if plan is None:
        raise AutomaticCTARefreshError("Site Plan not found.")
    planned_pages = list(
        session.exec(
            select(PlannedPage)
            .where(PlannedPage.site_plan_id == plan_id)
            .order_by(PlannedPage.id)
        ).all()
    )
    if not planned_pages:
        raise AutomaticCTARefreshError("Site Plan has no Planned Pages.")

    entries = [_manifest_entry(session, plan, planned) for planned in planned_pages]
    classifications: dict[str, int] = {}
    for entry in entries:
        value = str(entry["classification"])
        classifications[value] = classifications.get(value, 0) + 1
    body: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "task_identity": task_identity,
        "created_at": _timestamp(created_at or datetime.now(UTC)),
        "source_owner": SOURCE_OWNER,
        "legacy_source_commit": LEGACY_SOURCE_COMMIT,
        "website_id": plan.website_id,
        "site_plan_id": plan.id or plan_id,
        "site_plan_version": plan.version,
        "current_generated_page_count": len(entries),
        "eligible_count": classifications.get(AUTOMATIC_CLASSIFICATION, 0),
        "custom_copy_exclusion_count": classifications.get(CUSTOM_CLASSIFICATION, 0),
        "already_corrected_count": classifications.get(ALREADY_CORRECTED_CLASSIFICATION, 0),
        "classification_counts": dict(sorted(classifications.items())),
        "inventory_sha256": _canonical_hash(entries),
        "entries": entries,
    }
    body["manifest_sha256"] = automatic_cta_refresh_manifest_sha256(body)
    validate_automatic_cta_refresh_manifest(body)
    return body


def validate_automatic_cta_refresh_manifest(manifest: Mapping[str, Any]) -> None:
    required = {
        "schema",
        "task_identity",
        "created_at",
        "source_owner",
        "legacy_source_commit",
        "website_id",
        "site_plan_id",
        "site_plan_version",
        "current_generated_page_count",
        "eligible_count",
        "custom_copy_exclusion_count",
        "already_corrected_count",
        "classification_counts",
        "inventory_sha256",
        "entries",
        "manifest_sha256",
    }
    if set(manifest) != required:
        raise AutomaticCTARefreshError("Refresh manifest top-level key allowlist differs.")
    if (
        manifest.get("schema") != MANIFEST_SCHEMA
        or manifest.get("source_owner") != SOURCE_OWNER
        or manifest.get("legacy_source_commit") != LEGACY_SOURCE_COMMIT
    ):
        raise AutomaticCTARefreshError("Refresh manifest source identity differs.")
    if not isinstance(manifest.get("task_identity"), str) or not str(manifest["task_identity"]).strip():
        raise AutomaticCTARefreshError("Refresh manifest task identity is missing.")
    for key in ("website_id", "site_plan_id", "site_plan_version"):
        value = manifest.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise AutomaticCTARefreshError(
                f"Refresh manifest integer identity is invalid: {key}."
            )
    for key in (
        "current_generated_page_count",
        "eligible_count",
        "custom_copy_exclusion_count",
        "already_corrected_count",
    ):
        value = manifest.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise AutomaticCTARefreshError(
                f"Refresh manifest integer count is invalid: {key}."
            )
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise AutomaticCTARefreshError("Refresh manifest entries are missing.")
    if manifest.get("current_generated_page_count") != len(entries):
        raise AutomaticCTARefreshError("Refresh manifest page count differs from its entries.")
    generated_ids = [entry.get("generated_page_id") for entry in entries if isinstance(entry, dict)]
    planned_ids = [entry.get("planned_page_id") for entry in entries if isinstance(entry, dict)]
    if len(generated_ids) != len(entries) or len(set(generated_ids)) != len(entries):
        raise AutomaticCTARefreshError("Refresh manifest Generated Page identities are invalid or duplicated.")
    if len(planned_ids) != len(entries) or len(set(planned_ids)) != len(entries):
        raise AutomaticCTARefreshError("Refresh manifest Planned Page identities are invalid or duplicated.")
    if planned_ids != sorted(planned_ids):
        raise AutomaticCTARefreshError("Refresh manifest entries are not in deterministic identity order.")
    eligible = [entry for entry in entries if entry.get("classification") == AUTOMATIC_CLASSIFICATION]
    custom = [entry for entry in entries if entry.get("classification") == CUSTOM_CLASSIFICATION]
    corrected = [entry for entry in entries if entry.get("classification") == ALREADY_CORRECTED_CLASSIFICATION]
    classification_counts: dict[str, int] = {}
    for entry in entries:
        classification = str(entry.get("classification"))
        classification_counts[classification] = classification_counts.get(classification, 0) + 1
    if manifest.get("classification_counts") != dict(sorted(classification_counts.items())):
        raise AutomaticCTARefreshError("Refresh manifest classification counts differ.")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 1
        for value in manifest["classification_counts"].values()
    ):
        raise AutomaticCTARefreshError(
            "Refresh manifest classification count values are invalid."
        )
    if manifest.get("eligible_count") != len(eligible):
        raise AutomaticCTARefreshError("Refresh manifest eligible count differs.")
    if manifest.get("custom_copy_exclusion_count") != len(custom):
        raise AutomaticCTARefreshError("Refresh manifest custom-copy count differs.")
    if manifest.get("already_corrected_count") != len(corrected):
        raise AutomaticCTARefreshError("Refresh manifest corrected count differs.")
    if manifest.get("inventory_sha256") != _canonical_hash(entries):
        raise AutomaticCTARefreshError("Refresh manifest inventory hash differs.")
    supplied_hash = manifest.get("manifest_sha256")
    if not isinstance(supplied_hash, str) or not _SHA256.fullmatch(supplied_hash):
        raise AutomaticCTARefreshError("Refresh manifest hash is malformed.")
    if supplied_hash != automatic_cta_refresh_manifest_sha256(manifest):
        raise AutomaticCTARefreshError("Refresh manifest hash verification failed.")
    for entry in entries:
        _validate_manifest_entry(entry)
        if (
            entry["website_id"] != manifest["website_id"]
            or entry["site_plan_id"] != manifest["site_plan_id"]
        ):
            raise AutomaticCTARefreshError(
                "Refresh manifest entry hierarchy differs from its Website/Site Plan."
            )


def rehearse_automatic_cta_refresh(
    session: Session,
    manifest: Mapping[str, Any],
    *,
    dry_run: bool = False,
    failure_point: str | None = None,
    lock_nowait: bool = False,
) -> dict[str, Any]:
    """Prepare or apply the exact refresh without committing the caller session."""

    validate_automatic_cta_refresh_manifest(manifest)
    if failure_point is not None and failure_point not in FAILURE_POINTS:
        raise AutomaticCTARefreshError("Unknown automatic CTA refresh failure point.")
    legacy_entries = [
        entry for entry in manifest["entries"]
        if entry["classification"] == AUTOMATIC_CLASSIFICATION
    ]
    corrected_entries = [
        entry for entry in manifest["entries"]
        if entry["classification"] == ALREADY_CORRECTED_CLASSIFICATION
    ]
    custom_entries = [
        entry for entry in manifest["entries"]
        if entry["classification"] == CUSTOM_CLASSIFICATION
    ]
    governed_target_count = (
        len(legacy_entries) + len(corrected_entries) + len(custom_entries)
    )
    if custom_entries:
        raise AutomaticCTARefreshError("Custom or uncertain City-Service CTA ownership blocks refresh.")
    if governed_target_count == 0:
        raise AutomaticCTARefreshError("Refresh manifest contains no governed City-Service CTA pages.")
    if legacy_entries and corrected_entries:
        raise AutomaticCTARefreshError(
            "Mixed legacy/corrected automatic CTA state blocks the complete batch."
        )

    state_counts = {
        "governed_target_count": governed_target_count,
        "corrected_count": len(corrected_entries),
        "legacy_count": len(legacy_entries),
        "custom_count": len(custom_entries),
        "mixed_count": 0,
    }

    _lock_authoritative_source_tables(session)
    _assert_global_generated_page_inventory(session, manifest)
    locked = _lock_manifest_scope(session, manifest, nowait=lock_nowait)
    states: list[str] = []
    prepared: list[dict[str, Any]] = []
    for entry in manifest["entries"]:
        page = locked["generated_pages"][entry["generated_page_id"]]
        planned = locked["planned_pages"][entry["planned_page_id"]]
        composition = locked["compositions"][entry["composition_id"]]
        _assert_current_source_classification(session, entry, page)
        if entry["classification"] == ALREADY_CORRECTED_CLASSIFICATION:
            _assert_exact_corrected_identity(session, entry, page, planned, composition)
            continue
        if entry["classification"] != AUTOMATIC_CLASSIFICATION:
            _assert_exact_before_identity(session, entry, page, planned, composition)
            continue
        state, values = _eligible_state(session, entry, page, planned, composition)
        states.append(state)
        if values is not None:
            prepared.append(values)

    if corrected_entries:
        return {
            "status": "UNCHANGED",
            "manifest_sha256": manifest["manifest_sha256"],
            **state_counts,
            "eligible_count": 0,
            "page_writes": 0,
            "revision_writes": 0,
            "composition_writes": 0,
            "qa_writes": 0,
            "generated_page_revisions_created": 0,
            "composition_revisions_created": 0,
            "qa_rows_created": 0,
            "writes": 0,
        }
    if any(state == "unexpected" for state in states):
        raise AutomaticCTARefreshError("A governed CTA is neither the exact before-state nor exact refresh after-state.")
    if any(state != "before" for state in states):
        raise AutomaticCTARefreshError(
            "A legacy manifest no longer binds one exact legacy before-state."
        )
    if len(prepared) != len(legacy_entries):
        raise AutomaticCTARefreshError("Prepared automatic CTA set is incomplete.")
    if dry_run:
        return {
            "status": "DRY_RUN",
            "manifest_sha256": manifest["manifest_sha256"],
            "eligible_count": len(prepared),
            "expected_generated_page_revisions": len(prepared),
            "expected_composition_revisions": len(prepared),
            "expected_qa_rows": len(prepared),
            "writes": 0,
        }

    _inject(failure_point, "before_first_page")
    changed_at = datetime.now(UTC)
    revisions: dict[int, GeneratedPageRevision] = {}
    midpoint = (len(prepared) + 1) // 2
    for index, values in enumerate(prepared, start=1):
        page = values["page"]
        revision = append_generated_page_revision(
            session,
            page,
            before=values["before"],
            after=values["after"],
            changed_fields=["call_to_action"],
            rendered_content=values["rendered_content"],
            created_by=REFRESH_ACTOR,
            reason=REFRESH_REASON,
            changed_at=changed_at,
        )
        revisions[page.id or 0] = revision
        if index == 1:
            _inject(failure_point, "after_first_page")
        if index == midpoint:
            _inject(failure_point, "at_midpoint")
    _inject(failure_point, "after_drafts_before_composition")

    composition_result = refresh_site_plan_compositions(
        session,
        int(manifest["site_plan_id"]),
        commit=False,
    )
    expected_unchanged = len(manifest["entries"]) - len(prepared)
    if (
        composition_result.blocked
        or composition_result.created != 0
        or composition_result.refreshed != len(prepared)
        or composition_result.unchanged != expected_unchanged
    ):
        raise AutomaticCTARefreshError(
            "Composition refresh did not produce the exact governed successor counts."
        )
    _inject(failure_point, "after_composition_before_qa")

    qa_results = {
        values["page"].id or 0: save_page_qa(
            session,
            values["page"].id or 0,
            commit=False,
        )
        for values in prepared
    }
    session.flush()
    for values in prepared:
        _assert_exact_after_identity(
            session,
            values["entry"],
            values["page"],
            revisions[values["page"].id or 0],
            qa_results[values["page"].id or 0].qa_result_id,
        )
    _inject(failure_point, "immediately_before_commit")
    return {
        "status": "APPLIED_PENDING_CALLER_COMMIT",
        "manifest_sha256": manifest["manifest_sha256"],
        "eligible_count": len(prepared),
        "generated_page_revisions_created": len(revisions),
        "composition_revisions_created": composition_result.refreshed,
        "qa_rows_created": len(qa_results),
        "composition_created": composition_result.created,
        "composition_refreshed": composition_result.refreshed,
        "composition_unchanged": composition_result.unchanged,
        "writes": len(revisions) + composition_result.refreshed + len(qa_results),
    }


def _manifest_entry(
    session: Session,
    plan: SitePlan,
    planned: PlannedPage,
) -> dict[str, Any]:
    if planned.generated_page_id is None:
        raise AutomaticCTARefreshError(
            f"Planned Page {planned.id} has no Generated Page."
        )
    page = session.get(GeneratedPage, planned.generated_page_id)
    if page is None or not isinstance(page.draft_content, dict):
        raise AutomaticCTARefreshError(
            f"Generated Page {planned.generated_page_id} has no structured draft."
        )
    composition = session.exec(
        select(PageComposition).where(PageComposition.generated_page_id == page.id)
    ).one_or_none()
    if composition is None:
        raise AutomaticCTARefreshError(
            f"Generated Page {page.id} has no current Page Composition."
        )
    composition_revision = current_composition_revision(session, composition)
    qa = _current_qa(session, page.id or 0)
    revision, revision_history_sha256 = _generated_page_revision_history_identity(
        session,
        page.id or 0,
    )
    current_cta = page.draft_content.get("call_to_action")
    if not isinstance(current_cta, str) or not current_cta.strip():
        raise AutomaticCTARefreshError(f"Generated Page {page.id} has a blank CTA.")
    effective = read_composition_for_generated_page(session, page.id or 0)
    final_ctas = [
        item for item in effective.effective_components
        if item.instance_key == "final_cta"
    ]
    if (
        len(final_ctas) != 1
        or final_ctas[0].resolved_data.get("body") != current_cta
    ):
        raise AutomaticCTARefreshError(
            f"Generated Page {page.id} final CTA projection is not exact and current."
        )

    classification = EXCLUDED_CLASSIFICATION
    expected_corrected_cta_hash = None
    expected_after_draft_hash = None
    expected_after_content_body_hash = None
    credential_source_fingerprint = None
    if page.page_type == "city_service":
        context = load_generation_context(session, page.id or 0)
        legacy = legacy_automatic_public_call_to_action(context)
        corrected = build_automatic_public_call_to_action(context)
        canonical_current = render_content_body(
            DraftContent.model_validate(page.draft_content),
            context.website_context,
        )
        canonical_content_matches = canonical_current == (page.content_body or "")
        custom_credentials = _contains_governed_credential_copy_outside_cta(
            page.draft_content,
            context,
        )
        classification = _city_service_source_classification(
            current_cta=current_cta,
            legacy_cta=legacy,
            corrected_cta=corrected,
            canonical_content_matches=canonical_content_matches,
            public_page_fields_match_draft=_public_page_fields_match_draft(page),
            governed_credentials_outside_cta=custom_credentials,
        )
        expected = deepcopy(page.draft_content)
        expected["call_to_action"] = corrected
        validate_safe_content(expected)
        rendered = render_content_body(
            DraftContent.model_validate(expected),
            context.website_context,
        )
        expected_corrected_cta_hash = _text_hash(corrected)
        expected_after_draft_hash = draft_content_hash(expected)
        expected_after_content_body_hash = _text_hash(rendered)
        credential_source_fingerprint = _credential_source_fingerprint(context)

    _require_effective_qa(
        session,
        page,
        qa,
        allow_exact_legacy_city_service_predecessor=(
            classification == AUTOMATIC_CLASSIFICATION
        ),
    )

    return {
        "website_id": plan.website_id,
        "site_plan_id": plan.id,
        "planned_page_id": planned.id,
        "generated_page_id": page.id,
        "page_type": page.page_type,
        "classification": classification,
        "page_status": page.status,
        "page_updated_at": _timestamp(page.updated_at),
        "page_protected_sha256": _protected_page_hash(page),
        "planned_page_sha256": _protected_planned_page_hash(planned),
        "draft_without_cta_sha256": _draft_without_cta_hash(page.draft_content),
        "current_draft_sha256": draft_content_hash(page.draft_content),
        "current_content_body_sha256": _text_hash(page.content_body or ""),
        "current_cta_sha256": _text_hash(current_cta),
        "expected_corrected_cta_sha256": expected_corrected_cta_hash,
        "expected_after_draft_sha256": expected_after_draft_hash,
        "expected_after_content_body_sha256": expected_after_content_body_hash,
        "credential_source_fingerprint": credential_source_fingerprint,
        "generated_page_revision_id": revision.id if revision else None,
        "generated_page_revision_sha256": revision_history_sha256,
        "composition_id": composition.id,
        "composition_version": composition.composition_version,
        "composition_source_sha256": composition.source_hash,
        "composition_revision_id": composition_revision.id,
        "composition_revision_sha256": composition_revision.revision_hash,
        "qa_result_id": qa.id,
        "qa_result_sha256": qa.result_hash,
    }


def _lock_authoritative_source_tables(session: Session) -> None:
    """Fence every mutable source read by composition/QA through caller commit."""

    if session.get_bind().dialect.name != "postgresql":
        raise AutomaticCTARefreshError(
            "Automatic CTA refresh is restricted to PostgreSQL source fencing."
        )
    session.exec(
        text(
            "LOCK TABLE "
            + ", ".join(_AUTHORITATIVE_SOURCE_TABLES)
            + " IN SHARE MODE"
        )
    )


def _assert_global_generated_page_inventory(
    session: Session,
    manifest: Mapping[str, Any],
) -> None:
    """Reject an extra or missing Generated Page while the table fence is held."""

    expected_ids = [int(entry["generated_page_id"]) for entry in manifest["entries"]]
    observed_ids = [
        int(page_id)
        for page_id in session.exec(
            select(GeneratedPage.id).order_by(GeneratedPage.id)
        ).all()
    ]
    if (
        observed_ids != expected_ids
        or len(observed_ids) != int(manifest["current_generated_page_count"])
    ):
        raise AutomaticCTARefreshError(
            "Unexpected or missing global Generated Page blocks refresh."
        )


def _lock_manifest_scope(
    session: Session,
    manifest: Mapping[str, Any],
    *,
    nowait: bool,
) -> dict[str, dict[int, Any]]:
    entries = manifest["entries"]
    plan_id = int(manifest["site_plan_id"])
    plan = session.exec(
        select(SitePlan)
        .where(SitePlan.id == plan_id)
        .with_for_update(nowait=nowait)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if plan is None or plan.website_id != manifest["website_id"] or plan.version != manifest["site_plan_version"]:
        raise AutomaticCTARefreshError("Site Plan identity is stale.")

    planned_ids = [int(entry["planned_page_id"]) for entry in entries]
    generated_ids = [int(entry["generated_page_id"]) for entry in entries]
    planned_rows = _lock_rows(session, PlannedPage, planned_ids, nowait=nowait)
    generated_rows = _lock_rows(session, GeneratedPage, generated_ids, nowait=nowait)
    if set(planned_rows) != set(planned_ids) or set(generated_rows) != set(generated_ids):
        raise AutomaticCTARefreshError("Manifest page inventory is missing or stale.")
    current_planned = list(
        session.exec(
            select(PlannedPage)
            .where(PlannedPage.site_plan_id == plan_id)
            .order_by(PlannedPage.id)
        ).all()
    )
    if [row.id for row in current_planned] != planned_ids:
        raise AutomaticCTARefreshError("Unexpected or missing Planned Page blocks refresh.")

    source_ids = {
        Business: {int(row.business_id) for row in generated_rows.values()},
        Website: {int(row.website_id) for row in generated_rows.values() if row.website_id is not None},
        Service: {int(row.service_id) for row in generated_rows.values() if row.service_id is not None},
        City: {int(row.city_id) for row in generated_rows.values() if row.city_id is not None},
        County: {int(row.county_id) for row in generated_rows.values() if row.county_id is not None},
    }
    for model, identities in source_ids.items():
        if identities and set(_lock_rows(session, model, sorted(identities), nowait=nowait)) != identities:
            raise AutomaticCTARefreshError(f"Governed {model.__name__} source identity is missing.")

    composition_ids = [int(entry["composition_id"]) for entry in entries]
    compositions = _lock_rows(session, PageComposition, composition_ids, nowait=nowait)
    if set(compositions) != set(composition_ids):
        raise AutomaticCTARefreshError("Manifest Page Composition inventory is missing or stale.")
    for composition_id in composition_ids:
        current_composition_revision(
            session,
            compositions[composition_id],
            lock=True,
        )
    qa_ids = [int(entry["qa_result_id"]) for entry in entries]
    qa_rows = _lock_rows(session, GeneratedPageQAResult, qa_ids, nowait=nowait)
    if set(qa_rows) != set(qa_ids):
        raise AutomaticCTARefreshError("Manifest QA inventory is missing or stale.")
    current_qa_rows = list(
        session.exec(
            select(GeneratedPageQAResult)
            .where(
                GeneratedPageQAResult.generated_page_id.in_(generated_ids),
                GeneratedPageQAResult.lifecycle_status == "current",
            )
            .order_by(GeneratedPageQAResult.generated_page_id)
            .with_for_update(nowait=nowait)
            .execution_options(populate_existing=True)
        ).all()
    )
    if (
        len(current_qa_rows) != len(generated_ids)
        or [row.generated_page_id for row in current_qa_rows] != sorted(generated_ids)
    ):
        raise AutomaticCTARefreshError("Current QA inventory is incomplete or duplicated.")
    return {
        "planned_pages": planned_rows,
        "generated_pages": generated_rows,
        "compositions": compositions,
        "qa_rows": qa_rows,
    }


def _lock_rows(
    session: Session,
    model: type[Any],
    identities: list[int],
    *,
    nowait: bool,
) -> dict[int, Any]:
    if not identities:
        return {}
    rows = list(
        session.exec(
            select(model)
            .where(model.id.in_(identities))
            .order_by(model.id)
            .with_for_update(nowait=nowait)
            .execution_options(populate_existing=True)
        ).all()
    )
    return {row.id: row for row in rows if row.id is not None}


def _eligible_state(
    session: Session,
    entry: Mapping[str, Any],
    page: GeneratedPage,
    planned: PlannedPage,
    composition: PageComposition,
) -> tuple[str, dict[str, Any] | None]:
    _assert_common_identity(entry, page, planned, composition)
    context = load_generation_context(session, page.id or 0)
    if _contains_governed_credential_copy_outside_cta(page.draft_content or {}, context):
        raise AutomaticCTARefreshError(
            "Governed credential copy outside the automatic CTA blocks refresh."
        )
    legacy = legacy_automatic_public_call_to_action(context)
    corrected = build_automatic_public_call_to_action(context)
    if _text_hash(corrected) != entry["expected_corrected_cta_sha256"]:
        raise AutomaticCTARefreshError("Governed CTA source changed after manifest capture.")
    current = (page.draft_content or {}).get("call_to_action")
    if current == legacy:
        _assert_exact_before_identity(session, entry, page, planned, composition)
        before = deepcopy(page.draft_content or {})
        canonical_before = render_content_body(
            DraftContent.model_validate(before),
            context.website_context,
        )
        if _text_hash(canonical_before) != entry["current_content_body_sha256"]:
            raise AutomaticCTARefreshError(
                "Current rendered content is not the exact structured generator projection."
            )
        after = deepcopy(before)
        after["call_to_action"] = corrected
        validate_safe_content(after)
        rendered = render_content_body(
            DraftContent.model_validate(after),
            context.website_context,
        )
        if (
            draft_content_hash(after) != entry["expected_after_draft_sha256"]
            or _text_hash(rendered) != entry["expected_after_content_body_sha256"]
        ):
            raise AutomaticCTARefreshError("Computed CTA-only successor differs from the manifest.")
        return "before", {
            "entry": entry,
            "page": page,
            "before": before,
            "after": after,
            "rendered_content": rendered,
        }
    if current == corrected:
        _assert_exact_after_identity(session, entry, page, None, None)
        return "after", None
    return "unexpected", None


def _assert_common_identity(
    entry: Mapping[str, Any],
    page: GeneratedPage,
    planned: PlannedPage,
    composition: PageComposition,
) -> None:
    if (
        page.id != entry["generated_page_id"]
        or page.website_id != entry["website_id"]
        or planned.id != entry["planned_page_id"]
        or planned.website_id != entry["website_id"]
        or planned.site_plan_id != entry["site_plan_id"]
        or planned.generated_page_id != page.id
        or page.page_type != entry["page_type"]
        or page.status != entry["page_status"]
        or composition.id != entry["composition_id"]
        or composition.generated_page_id != page.id
        or composition.planned_page_id != planned.id
        or _protected_page_hash(page) != entry["page_protected_sha256"]
        or _protected_planned_page_hash(planned) != entry["planned_page_sha256"]
        or _draft_without_cta_hash(page.draft_content or {}) != entry["draft_without_cta_sha256"]
    ):
        raise AutomaticCTARefreshError("Protected Generated/Planned Page identity is stale.")


def _assert_exact_before_identity(
    session: Session,
    entry: Mapping[str, Any],
    page: GeneratedPage,
    planned: PlannedPage,
    composition: PageComposition,
) -> None:
    _assert_common_identity(entry, page, planned, composition)
    read_composition_for_generated_page(session, page.id or 0)
    revision, revision_history_sha256 = _generated_page_revision_history_identity(
        session,
        page.id or 0,
    )
    composition_revision = current_composition_revision(session, composition)
    qa = _current_qa(session, page.id or 0)
    _require_effective_qa(
        session,
        page,
        qa,
        allow_exact_legacy_city_service_predecessor=(
            entry.get("classification") == AUTOMATIC_CLASSIFICATION
        ),
    )
    if (
        draft_content_hash(page.draft_content or {}) != entry["current_draft_sha256"]
        or _timestamp(page.updated_at) != entry["page_updated_at"]
        or _text_hash(page.content_body or "") != entry["current_content_body_sha256"]
        or _text_hash((page.draft_content or {}).get("call_to_action", "")) != entry["current_cta_sha256"]
        or (revision.id if revision else None) != entry["generated_page_revision_id"]
        or revision_history_sha256 != entry["generated_page_revision_sha256"]
        or composition.composition_version != entry["composition_version"]
        or composition.source_hash != entry["composition_source_sha256"]
        or composition_revision.id != entry["composition_revision_id"]
        or composition_revision.revision_hash != entry["composition_revision_sha256"]
        or qa.id != entry["qa_result_id"]
        or qa.result_hash != entry["qa_result_sha256"]
    ):
        raise AutomaticCTARefreshError("Manifest before-state identity is stale.")


def _assert_exact_corrected_identity(
    session: Session,
    entry: Mapping[str, Any],
    page: GeneratedPage,
    planned: PlannedPage,
    composition: PageComposition,
) -> None:
    """Validate one freshly captured current corrected state without a write seam."""

    _assert_exact_before_identity(session, entry, page, planned, composition)
    if (
        entry["current_cta_sha256"] != entry["expected_corrected_cta_sha256"]
        or entry["current_draft_sha256"] != entry["expected_after_draft_sha256"]
        or entry["current_content_body_sha256"]
        != entry["expected_after_content_body_sha256"]
    ):
        raise AutomaticCTARefreshError(
            "Manifest corrected-state identity does not bind its current deterministic output."
        )


def _assert_exact_after_identity(
    session: Session,
    entry: Mapping[str, Any],
    page: GeneratedPage,
    known_revision: GeneratedPageRevision | None,
    known_qa_result_id: int | None,
) -> None:
    planned = session.get(PlannedPage, int(entry["planned_page_id"]))
    composition = session.get(PageComposition, int(entry["composition_id"]))
    if planned is None or composition is None:
        raise AutomaticCTARefreshError("Refresh after-state ownership is missing.")
    _assert_common_identity(entry, page, planned, composition)
    latest_revision = _latest_revision(session, page.id or 0)
    revision = known_revision or latest_revision
    prior_revision, prior_revision_history_sha256 = (
        _generated_page_revision_history_identity(
            session,
            page.id or 0,
            exclude_revision_id=revision.id if revision else None,
        )
    )
    composition_revision = current_composition_revision(session, composition)
    predecessor = session.get(
        PageCompositionRevision,
        int(entry["composition_revision_id"]),
    )
    qa = _current_qa(session, page.id or 0)
    _require_effective_qa(session, page, qa)
    effective = read_composition_for_generated_page(session, page.id or 0)
    final_ctas = [
        item for item in effective.effective_components
        if item.instance_key == "final_cta"
    ]
    if len(final_ctas) != 1:
        raise AutomaticCTARefreshError("Refresh after-state has no single effective final CTA.")
    final_body = final_ctas[0].resolved_data.get("body")
    if (
        revision is None
        or latest_revision is None
        or latest_revision.id != revision.id
        or (prior_revision.id if prior_revision else None)
        != entry["generated_page_revision_id"]
        or prior_revision_history_sha256
        != entry["generated_page_revision_sha256"]
        or predecessor is None
        or revision.created_by != REFRESH_ACTOR
        or revision.reason != REFRESH_REASON
        or revision.changed_fields != ["call_to_action"]
        or revision.draft_hash_before != entry["current_draft_sha256"]
        or revision.draft_hash_after != entry["expected_after_draft_sha256"]
        or draft_content_hash(revision.draft_content_before) != entry["current_draft_sha256"]
        or draft_content_hash(revision.draft_content_after) != entry["expected_after_draft_sha256"]
        or _timestamp(page.updated_at) != _timestamp(revision.created_at)
        or draft_content_hash(page.draft_content or {}) != entry["expected_after_draft_sha256"]
        or _text_hash(page.content_body or "") != entry["expected_after_content_body_sha256"]
        or _text_hash((page.draft_content or {}).get("call_to_action", "")) != entry["expected_corrected_cta_sha256"]
        or composition.composition_version != int(entry["composition_version"]) + 1
        or composition_revision.generated_page_revision_id != revision.id
        or composition_revision.supersedes_revision_id != entry["composition_revision_id"]
        or composition_revision.supersedes_revision_hash != entry["composition_revision_sha256"]
        or composition.generated_components != predecessor.generated_components
        or composition.operator_decisions != predecessor.operator_decisions
        or composition.source_snapshot != _expected_after_composition_snapshot(
            predecessor.source_snapshot,
            page,
            str(entry["expected_after_draft_sha256"]),
        )
        or composition.source_snapshot.get("draft_hash") != entry["expected_after_draft_sha256"]
        or _text_hash(final_body or "") != entry["expected_corrected_cta_sha256"]
        or qa.latest_generated_page_revision_id != revision.id
        or qa.page_composition_id != composition.id
        or qa.composition_version != composition.composition_version
        or qa.composition_source_hash != composition.source_hash
        or qa.supersedes_qa_result_id != entry["qa_result_id"]
        or (known_qa_result_id is not None and qa.id != known_qa_result_id)
        or not isinstance(page.qa_result, dict)
        or page.qa_result.get("qa_result_id") != qa.id
        or page.qa_result.get("result_hash") != qa.result_hash
    ):
        raise AutomaticCTARefreshError("Refresh after-state identity is incomplete or divergent.")


def _validate_manifest_entry(entry: Any) -> None:
    if not isinstance(entry, dict):
        raise AutomaticCTARefreshError("Refresh manifest entry is not an object.")
    required = {
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
        "page_type",
        "classification",
        "page_status",
        "page_updated_at",
        "page_protected_sha256",
        "planned_page_sha256",
        "draft_without_cta_sha256",
        "current_draft_sha256",
        "current_content_body_sha256",
        "current_cta_sha256",
        "expected_corrected_cta_sha256",
        "expected_after_draft_sha256",
        "expected_after_content_body_sha256",
        "credential_source_fingerprint",
        "generated_page_revision_id",
        "generated_page_revision_sha256",
        "composition_id",
        "composition_version",
        "composition_source_sha256",
        "composition_revision_id",
        "composition_revision_sha256",
        "qa_result_id",
        "qa_result_sha256",
    }
    if set(entry) != required:
        raise AutomaticCTARefreshError("Refresh manifest entry key allowlist differs.")
    classification = entry.get("classification")
    if classification not in {
        AUTOMATIC_CLASSIFICATION,
        EXCLUDED_CLASSIFICATION,
        CUSTOM_CLASSIFICATION,
        ALREADY_CORRECTED_CLASSIFICATION,
    }:
        raise AutomaticCTARefreshError("Refresh manifest classification is unknown.")
    if (
        entry.get("page_type") == "city_service"
        and classification == EXCLUDED_CLASSIFICATION
    ) or (
        entry.get("page_type") != "city_service"
        and classification != EXCLUDED_CLASSIFICATION
    ):
        raise AutomaticCTARefreshError(
            "Refresh manifest classification does not match its page type."
        )
    for key in (
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
        "composition_id",
        "composition_version",
        "composition_revision_id",
        "qa_result_id",
    ):
        if not isinstance(entry.get(key), int) or isinstance(entry.get(key), bool) or entry[key] < 1:
            raise AutomaticCTARefreshError(f"Refresh manifest identity is invalid: {key}.")
    for key in (
        "page_protected_sha256",
        "planned_page_sha256",
        "draft_without_cta_sha256",
        "current_draft_sha256",
        "current_content_body_sha256",
        "current_cta_sha256",
        "composition_source_sha256",
        "composition_revision_sha256",
        "qa_result_sha256",
    ):
        if not isinstance(entry.get(key), str) or not _SHA256.fullmatch(entry[key]):
            raise AutomaticCTARefreshError(f"Refresh manifest hash is invalid: {key}.")
    revision_id = entry.get("generated_page_revision_id")
    revision_hash = entry.get("generated_page_revision_sha256")
    if revision_id is None:
        if revision_hash is not None:
            raise AutomaticCTARefreshError("Revision hash exists without a revision identity.")
    elif (
        not isinstance(revision_id, int)
        or isinstance(revision_id, bool)
        or revision_id < 1
        or not isinstance(revision_hash, str)
        or not _SHA256.fullmatch(revision_hash)
    ):
        raise AutomaticCTARefreshError("Generated Page revision identity is invalid.")
    if classification in {
        AUTOMATIC_CLASSIFICATION,
        CUSTOM_CLASSIFICATION,
        ALREADY_CORRECTED_CLASSIFICATION,
    }:
        for key in (
            "expected_corrected_cta_sha256",
            "expected_after_draft_sha256",
            "expected_after_content_body_sha256",
            "credential_source_fingerprint",
        ):
            if not isinstance(entry.get(key), str) or not _SHA256.fullmatch(entry[key]):
                raise AutomaticCTARefreshError(f"City-Service manifest hash is invalid: {key}.")
    elif any(
        entry.get(key) is not None
        for key in (
            "expected_corrected_cta_sha256",
            "expected_after_draft_sha256",
            "expected_after_content_body_sha256",
            "credential_source_fingerprint",
        )
    ):
        raise AutomaticCTARefreshError("Non-City-Service entry contains CTA refresh identity.")
    if not isinstance(entry.get("page_updated_at"), str) or not entry["page_updated_at"].strip():
        raise AutomaticCTARefreshError("Generated Page update identity is invalid.")


def _latest_revision(session: Session, page_id: int) -> GeneratedPageRevision | None:
    revision, _history_sha256 = _generated_page_revision_history_identity(
        session,
        page_id,
    )
    return revision


def _generated_page_revision_history_identity(
    session: Session,
    page_id: int,
    *,
    exclude_revision_id: int | None = None,
) -> tuple[GeneratedPageRevision | None, str | None]:
    rows = list(
        session.exec(
            select(GeneratedPageRevision)
            .where(GeneratedPageRevision.generated_page_id == page_id)
            .order_by(
                GeneratedPageRevision.created_at,
                GeneratedPageRevision.id,
            )
        ).all()
    )
    if exclude_revision_id is not None:
        rows = [row for row in rows if row.id != exclude_revision_id]
    if not rows:
        return None, None
    return rows[-1], _canonical_hash(
        [_generated_page_revision_payload(row) for row in rows]
    )


def _generated_page_revision_payload(
    revision: GeneratedPageRevision,
) -> dict[str, Any]:
    return {
        "id": revision.id,
        "generated_page_id": revision.generated_page_id,
        "created_at": _timestamp(revision.created_at),
        "created_by": revision.created_by,
        "reason": revision.reason,
        "draft_hash_before": revision.draft_hash_before,
        "draft_hash_after": revision.draft_hash_after,
        "draft_content_before": revision.draft_content_before,
        "draft_content_after": revision.draft_content_after,
        "changed_fields": revision.changed_fields,
    }


def _current_qa(session: Session, page_id: int) -> GeneratedPageQAResult:
    rows = list(
        session.exec(
            select(GeneratedPageQAResult)
            .where(
                GeneratedPageQAResult.generated_page_id == page_id,
                GeneratedPageQAResult.lifecycle_status == "current",
            )
            .order_by(GeneratedPageQAResult.id)
        ).all()
    )
    if len(rows) != 1:
        raise AutomaticCTARefreshError(
            f"Generated Page {page_id} does not have one exact current QA result."
        )
    return rows[0]


def _require_effective_qa(
    session: Session,
    page: GeneratedPage,
    record: GeneratedPageQAResult,
    *,
    allow_exact_legacy_city_service_predecessor: bool = False,
) -> None:
    effective = effective_page_qa_state(session, page)
    exact_current = (
        effective.current
        and effective.record is not None
        and effective.result is not None
        and effective.record.id == record.id
        and effective.record.result_hash == record.result_hash
        and effective.result.qa_result_id == record.id
        and effective.result.result_hash == record.result_hash
    )
    if exact_current:
        return
    if (
        allow_exact_legacy_city_service_predecessor
        and is_exact_legacy_city_service_qa_predecessor(session, page, record)
    ):
        return
    if (
        not effective.current
        or effective.record is None
        or effective.result is None
        or effective.record.id != record.id
        or effective.record.result_hash != record.result_hash
        or effective.result.qa_result_id != record.id
        or effective.result.result_hash != record.result_hash
    ):
        raise AutomaticCTARefreshError(
            f"Generated Page {page.id} QA evidence is not current and identity-exact."
        )


def _protected_page_hash(page: GeneratedPage) -> str:
    return _canonical_hash(
        {
            "id": page.id,
            "created_at": _timestamp(page.created_at),
            "business_id": page.business_id,
            "website_id": page.website_id,
            "service_id": page.service_id,
            "city_id": page.city_id,
            "county_id": page.county_id,
            "page_type": page.page_type,
            "page_title": page.page_title,
            "page_slug": page.page_slug,
            "meta_title": page.meta_title,
            "meta_description": page.meta_description,
            "h1": page.h1,
            "generation_status": page.generation_status,
            "generated_at": _timestamp(page.generated_at),
            "internal_notes": page.internal_notes,
            "last_reviewed_at": _timestamp(page.last_reviewed_at),
            "last_reviewed_by": page.last_reviewed_by,
            "status": page.status,
            "wordpress_post_id": page.wordpress_post_id,
            "wordpress_url": page.wordpress_url,
            "wordpress_status": page.wordpress_status,
            "wordpress_created_at": _timestamp(page.wordpress_created_at),
            "last_wordpress_sync_at": _timestamp(page.last_wordpress_sync_at),
        }
    )


def _protected_planned_page_hash(page: PlannedPage) -> str:
    return _canonical_hash(page.model_dump(mode="json"))


def _expected_after_composition_snapshot(
    predecessor: Mapping[str, Any],
    page: GeneratedPage,
    draft_hash: str,
) -> dict[str, Any]:
    expected = deepcopy(dict(predecessor))
    expected["generated_page_updated_at"] = canonical_utc_timestamp(page.updated_at)
    expected["draft_hash"] = draft_hash
    return expected


def _draft_without_cta_hash(draft: Mapping[str, Any]) -> str:
    return _canonical_hash(
        {key: deepcopy(value) for key, value in draft.items() if key != "call_to_action"}
    )


def _contains_governed_credential_copy_outside_cta(
    draft: Mapping[str, Any],
    context: GenerationContext,
) -> bool:
    """Detect exact governed credential values in structured public draft fields."""

    governed_values = {
        _normalized_governed_public_text(value)
        for value in (
            context.business.license_number or "",
            context.business.certified_operator or "",
        )
        if value.strip()
    }
    if not governed_values:
        return False

    public_projection = {
        key: value
        for key, value in draft.items()
        if key not in {"call_to_action", "internal_notes", "status"}
    }

    def public_strings(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, Mapping):
            return [
                item
                for child in value.values()
                for item in public_strings(child)
            ]
        if isinstance(value, list):
            return [item for child in value for item in public_strings(child)]
        return []

    public_text = _normalized_governed_public_text(
        "\n".join(public_strings(public_projection))
    )
    return any(value in public_text for value in governed_values)


def _normalized_governed_public_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _public_page_fields_match_draft(page: GeneratedPage) -> bool:
    draft = page.draft_content if isinstance(page.draft_content, dict) else {}
    return all(
        stored == draft.get(draft_key)
        for stored, draft_key in (
            (page.page_title, "title"),
            (page.meta_title, "meta_title"),
            (page.meta_description, "meta_description"),
            (page.h1, "h1"),
        )
    )


def _credential_source_fingerprint(context: GenerationContext) -> str:
    return _canonical_hash(
        {
            "license_label": website_config_value(
                context.website_context,
                "license_label",
                "License",
            ),
            "legacy_source_commit": LEGACY_SOURCE_COMMIT,
            "legacy_source_license_label": "Florida license",
            "license_number": context.business.license_number,
            "certified_operator": context.business.certified_operator,
        }
    )


def _city_service_source_classification(
    *,
    current_cta: str,
    legacy_cta: str,
    corrected_cta: str,
    canonical_content_matches: bool,
    public_page_fields_match_draft: bool,
    governed_credentials_outside_cta: bool,
) -> str:
    if (
        current_cta == legacy_cta
        and canonical_content_matches
        and public_page_fields_match_draft
        and not governed_credentials_outside_cta
    ):
        return AUTOMATIC_CLASSIFICATION
    if (
        current_cta == corrected_cta
        and canonical_content_matches
        and public_page_fields_match_draft
        and not governed_credentials_outside_cta
    ):
        return ALREADY_CORRECTED_CLASSIFICATION
    return CUSTOM_CLASSIFICATION


def _assert_current_source_classification(
    session: Session,
    entry: Mapping[str, Any],
    page: GeneratedPage,
) -> None:
    context: GenerationContext | None = None
    corrected: str | None = None
    canonical_current: str | None = None
    if page.page_type != "city_service":
        expected_classification = EXCLUDED_CLASSIFICATION
    else:
        if not isinstance(page.draft_content, dict):
            raise AutomaticCTARefreshError(
                f"Generated Page {page.id} has no structured draft."
            )
        context = load_generation_context(session, page.id or 0)
        current_cta = page.draft_content.get("call_to_action")
        if not isinstance(current_cta, str) or not current_cta.strip():
            raise AutomaticCTARefreshError(f"Generated Page {page.id} has a blank CTA.")
        corrected = build_automatic_public_call_to_action(context)
        canonical_current = render_content_body(
            DraftContent.model_validate(page.draft_content),
            context.website_context,
        )
        expected_classification = _city_service_source_classification(
            current_cta=current_cta,
            legacy_cta=legacy_automatic_public_call_to_action(context),
            corrected_cta=corrected,
            canonical_content_matches=canonical_current == (page.content_body or ""),
            public_page_fields_match_draft=_public_page_fields_match_draft(page),
            governed_credentials_outside_cta=(
                _contains_governed_credential_copy_outside_cta(
                    page.draft_content,
                    context,
                )
            ),
        )
    if entry.get("classification") != expected_classification:
        raise AutomaticCTARefreshError(
            f"Generated Page {page.id} source classification changed after manifest capture."
        )
    if (
        context is not None
        and entry.get("credential_source_fingerprint")
        != _credential_source_fingerprint(context)
    ):
        raise AutomaticCTARefreshError(
            "Governed credential source identity changed after manifest capture."
        )
    if expected_classification == ALREADY_CORRECTED_CLASSIFICATION:
        if context is None or corrected is None or canonical_current is None:
            raise AutomaticCTARefreshError(
                "Corrected CTA source identity could not be reconstructed."
            )
        if (
            entry.get("expected_corrected_cta_sha256") != _text_hash(corrected)
            or entry.get("expected_after_draft_sha256")
            != draft_content_hash(page.draft_content or {})
            or entry.get("expected_after_content_body_sha256")
            != _text_hash(canonical_current)
        ):
            raise AutomaticCTARefreshError(
                "Corrected CTA source identity changed after manifest capture."
            )


def _inject(requested: str | None, current: str) -> None:
    if requested == current:
        raise InjectedAutomaticCTARefreshFailure(
            f"Injected automatic CTA refresh failure: {current}."
        )


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
