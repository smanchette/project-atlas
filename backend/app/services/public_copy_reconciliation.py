from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import re
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import (
    Brand,
    BrandAsset,
    Business,
    City,
    County,
    DraftingEligibilityAssessment,
    DraftingEligibilityDisposition,
    GeneratedPage,
    GeneratedPageQAResult,
    GeneratedPageRevision,
    ImageMetadata,
    InternalLinkIntent,
    KnowledgeBlock,
    NavigationItem,
    NavigationSet,
    PageComposition,
    PageCompositionRevision,
    PageImageAssignment,
    PlannedPageMediaRequirement,
    PlannedPage,
    PlanningRecord,
    PreDraftDistinctnessBrief,
    ScopedMediaAuthorization,
    SemanticComponentDefinition,
    Service,
    SitePlan,
    SupportingPageAuthorization,
    Theme,
    Website,
    WebsiteCityCoverageDecision,
    WebsiteCountyCoverageDecision,
    WebsiteIdentity,
    WebsiteIdentityAssetAssignment,
    WebsiteMediaPlanningRecord,
    WebsiteServiceCityCoverageDecision,
    WebsiteServiceCountyCoverageDecision,
    WebsiteServiceCoverageDecision,
    WebsiteThemeSelection,
)
from app.schemas.generation import DraftContent
from app.schemas.site_plans import PlannedPageDraftContent
from app.services.approval_audit import draft_content_hash
from app.services.draft_generation import render_content_body
from app.services.page_composition import (
    read_composition_for_generated_page,
    refresh_site_plan_compositions,
)
from app.services.page_composition_history import (
    COMPOSITION_REFRESH_ACTOR,
    COMPOSITION_REFRESH_SOURCE,
    PageCompositionHistoryError,
    current_composition_revision,
)
from app.services.page_editor import (
    MANIFEST_BOUND_FULL_DRAFT_REVISION_REASON_PREFIX,
    ManifestBoundFullDraftRevisionAuthority,
    save_full_draft_revision,
)
from app.services.page_qa import (
    effective_page_qa_state,
    qa_result_record_hash,
    save_page_qa,
)
from app.services.planned_page_drafting import render_planned_page_content
from app.services.public_copy_manifest import (
    PUBLIC_COPY_LOCKED_SOURCE_TABLE_NAMES,
    PublicCopyManifestError,
    PublicCopyManifestPackage,
    canonical_json_sha256,
    canonical_model_row_sha256,
    canonical_model_rows_sha256,
    canonicalize_model_row_timestamps,
    revalidate_public_copy_manifest_package,
)
from app.services.public_copy_audit import (
    PublicCopyAuditInput,
    PublicCopyAuditBatchResult,
    audit_public_copy_pages,
)
from app.services.public_destination_copy import (
    PUBLIC_COPY_RULESET_HASH,
    PUBLIC_COPY_RULESET_IDENTITY,
    PUBLIC_COPY_RULESET_KEY,
    PUBLIC_COPY_RULESET_VERSION,
    build_public_copy_reconciled_draft,
)
from app.services.website_context import build_website_context


PUBLIC_COPY_RECONCILIATION_REASON_PREFIX = (
    MANIFEST_BOUND_FULL_DRAFT_REVISION_REASON_PREFIX
)

_LOCKED_SOURCE_MODELS: tuple[tuple[type[Any], str], ...] = (
    (BrandAsset, "brand_assets"),
    (Brand, "brands"),
    (Business, "businesses"),
    (City, "cities"),
    (County, "counties"),
    (DraftingEligibilityAssessment, "drafting_eligibility_assessments"),
    (DraftingEligibilityDisposition, "drafting_eligibility_dispositions"),
    (ImageMetadata, "image_metadata"),
    (KnowledgeBlock, "knowledge_blocks"),
    (NavigationItem, "navigation_items"),
    (NavigationSet, "navigation_sets"),
    (PageImageAssignment, "page_image_assignments"),
    (PlannedPageMediaRequirement, "planned_page_media_requirements"),
    (PlannedPage, "planned_pages"),
    (PlanningRecord, "planning_records"),
    (PreDraftDistinctnessBrief, "pre_draft_distinctness_briefs"),
    (ScopedMediaAuthorization, "scoped_media_authorizations"),
    (SemanticComponentDefinition, "semantic_component_definitions"),
    (Service, "services"),
    (SitePlan, "site_plans"),
    (SupportingPageAuthorization, "supporting_page_authorizations"),
    (Theme, "themes"),
    (WebsiteCityCoverageDecision, "website_city_coverage_decisions"),
    (WebsiteCountyCoverageDecision, "website_county_coverage_decisions"),
    (WebsiteIdentity, "website_identities"),
    (WebsiteIdentityAssetAssignment, "website_identity_asset_assignments"),
    (WebsiteMediaPlanningRecord, "website_media_planning_records"),
    (
        WebsiteServiceCityCoverageDecision,
        "website_service_city_coverage_decisions",
    ),
    (
        WebsiteServiceCountyCoverageDecision,
        "website_service_county_coverage_decisions",
    ),
    (WebsiteServiceCoverageDecision, "website_service_coverage_decisions"),
    (WebsiteThemeSelection, "website_theme_selections"),
    (Website, "websites"),
)

_RECONCILIATION_TABLE_MODELS: tuple[type[Any], ...] = (
    *(model for model, _table_name in _LOCKED_SOURCE_MODELS),
    GeneratedPage,
    GeneratedPageQAResult,
    GeneratedPageRevision,
    InternalLinkIntent,
    PageComposition,
    PageCompositionRevision,
)

_IMMUTABLE_HISTORY_MODELS: dict[str, type[Any]] = {
    "generated_page_revisions": GeneratedPageRevision,
    "page_composition_revisions": PageCompositionRevision,
    "generated_page_qa_results": GeneratedPageQAResult,
}

_GENERATED_PAGE_PRESERVED_FIELDS = (
    "id",
    "business_id",
    "website_id",
    "service_id",
    "city_id",
    "county_id",
    "page_type",
    "page_slug",
    "generation_status",
    "generated_at",
    "internal_notes",
    "last_reviewed_at",
    "last_reviewed_by",
    "status",
    "wordpress_post_id",
    "wordpress_url",
    "wordpress_status",
    "wordpress_created_at",
    "last_wordpress_sync_at",
    "created_at",
)


class PublicCopyReconciliationError(ValueError):
    pass


class PublicCopyReconciliationInjectedFailure(PublicCopyReconciliationError):
    pass


@dataclass(frozen=True)
class PublicCopyPageReconciliation:
    planned_page_id: int
    generated_page_id: int
    old_generated_page_revision_id: int | None
    new_generated_page_revision_id: int
    old_content_hash: str
    new_content_hash: str
    composition_id: int
    old_composition_version: int
    new_composition_version: int
    old_composition_source_hash: str
    new_composition_source_hash: str
    old_qa_result_id: int
    new_qa_result_id: int
    new_qa_result_hash: str


@dataclass(frozen=True)
class PublicCopyReconciliationResult:
    status: str
    manifest_file_sha256: str
    ruleset_payload_sha256: str
    website_id: int
    site_plan_id: int
    affected_page_count: int
    page_results: tuple[PublicCopyPageReconciliation, ...]
    appended_evidence_row_count: int
    updated_head_row_count: int
    superseded_qa_row_count: int
    public_copy_audit_fingerprint: str
    public_copy_warning_count: int
    public_copy_informational_count: int


def reconcile_public_copy(
    session: Session,
    package: PublicCopyManifestPackage,
    *,
    actor: str,
    commit: bool = True,
    inject_failure_after_qa: int | None = None,
) -> PublicCopyReconciliationResult:
    """Apply one sealed all-page copy correction as a fail-closed unit.

    The function intentionally has no route.  A trusted local orchestration
    runner must load a caller-SHA-pinned manifest package and provide a fresh
    Session.  Every source identity is locked and validated before the first
    Generated Page revision is appended.
    """

    reconciliation_actor = actor.strip()
    try:
        revalidate_public_copy_manifest_package(package)
    except PublicCopyManifestError as exc:
        raise PublicCopyReconciliationError(str(exc)) from exc
    if not reconciliation_actor or reconciliation_actor != actor:
        raise PublicCopyReconciliationError(
            "Public-copy reconciliation requires an exact nonempty actor identity."
        )
    if inject_failure_after_qa is not None and (
        isinstance(inject_failure_after_qa, bool)
        or not isinstance(inject_failure_after_qa, int)
        or inject_failure_after_qa <= 0
    ):
        raise PublicCopyReconciliationError(
            "Injected-failure QA count must be a positive integer."
        )

    manifest = package.manifest
    scope = manifest["scope"]
    website_id = int(scope["website_id"])
    site_plan_id = int(scope["site_plan_id"])
    bindings = list(manifest["page_bindings"])
    if (
        inject_failure_after_qa is not None
        and inject_failure_after_qa > len(bindings)
    ):
        raise PublicCopyReconciliationError(
            "Injected-failure QA count exceeds the complete affected-page scope."
        )
    reason = (
        f"{PUBLIC_COPY_RECONCILIATION_REASON_PREFIX}"
        f"{package.manifest_file_sha256}"
    )
    try:
        state = _lock_and_preflight(
            session,
            package,
            actor=reconciliation_actor,
            reason=reason,
        )
        if state.classification == "all_after":
            current_audit = _audit_current_scope(
                session,
                bindings=bindings,
                manifest=manifest,
                ruleset=package.ruleset,
                navigation_identity_bindings=(
                    state.navigation_identity_bindings
                ),
            )
            result = PublicCopyReconciliationResult(
                status="already_applied",
                manifest_file_sha256=package.manifest_file_sha256,
                ruleset_payload_sha256=package.ruleset_payload_sha256,
                website_id=website_id,
                site_plan_id=site_plan_id,
                affected_page_count=len(bindings),
                page_results=(),
                appended_evidence_row_count=0,
                updated_head_row_count=0,
                superseded_qa_row_count=0,
                public_copy_audit_fingerprint=current_audit.fingerprint,
                public_copy_warning_count=current_audit.warning_finding_count,
                public_copy_informational_count=(
                    current_audit.informational_finding_count
                ),
            )
            if commit:
                # Release all read/lock state without recording even a commit-time
                # database change for the exact repeated-run path.
                session.rollback()
            return result

        old_state = {
            int(binding["planned_page_id"]): {
                "revision_id": binding["current_revision"][
                    "latest_page_revision_id"
                ],
                "content_hash": binding["current_revision"]["content_hash"],
                "composition_id": binding["current_composition"]["id"],
                "composition_version": binding["current_composition"]["version"],
                "composition_source_hash": binding["current_composition"][
                    "source_hash"
                ],
                "qa_id": binding["current_qa"]["id"],
                "page_revision_snapshot": _row_snapshot(
                    session.get(
                        GeneratedPageRevision,
                        binding["current_revision"]["latest_page_revision_id"],
                    )
                    if binding["current_revision"]["latest_page_revision_id"]
                    is not None
                    else None
                ),
                "composition_revision_snapshot": _row_snapshot(
                    session.get(
                        PageCompositionRevision,
                        binding["current_composition"]["history_revision_id"],
                    )
                ),
                "qa_snapshot": _row_snapshot(
                    session.get(
                        GeneratedPageQAResult,
                        binding["current_qa"]["id"],
                    )
                ),
            }
            for binding in bindings
        }
        new_revisions: dict[int, GeneratedPageRevision] = {}
        revision_authority_by_planned = {
            authority.planned_page_id: authority
            for authority in state.drafting_evidence.revision_authorities
        }
        for binding in bindings:
            planned_id = int(binding["planned_page_id"])
            generated_id = int(binding["generated_page_id"])
            page, revision = save_full_draft_revision(
                session,
                generated_id,
                binding["expected_draft_content"],
                expected_current_hash=binding["current_revision"]["content_hash"],
                created_by=reconciliation_actor,
                reason=reason,
                allowed_page_statuses=frozenset(
                    {binding["page_identity"]["generated_page_status"]}
                ),
                expected_changed_fields=binding[
                    "expected_changed_top_level_fields"
                ],
                manifest_bound_authority=revision_authority_by_planned[
                    planned_id
                ],
                commit=False,
            )
            if draft_content_hash(page.draft_content or {}) != binding[
                "expected_new_content_hash"
            ]:
                raise PublicCopyReconciliationError(
                    f"Generated Page {generated_id} did not reach its sealed post-state."
                )
            new_revisions[planned_id] = revision
        session.flush()

        refresh = refresh_site_plan_compositions(
            session,
            site_plan_id,
            commit=False,
        )
        if refresh.blocked:
            raise PublicCopyReconciliationError(
                "Composition refresh blocked after Generated Page reconciliation."
            )
        if (
            refresh.created != 0
            or refresh.refreshed != len(bindings)
            or refresh.unchanged != 0
            or len(refresh.compositions) != len(bindings)
        ):
            raise PublicCopyReconciliationError(
                "Composition refresh did not advance exactly the sealed affected-page set."
            )
        if {item.planned_page_id for item in refresh.compositions} != {
            int(binding["planned_page_id"]) for binding in bindings
        }:
            raise PublicCopyReconciliationError(
                "Composition refresh returned a different Planned Page scope."
            )

        qa_results: dict[int, Any] = {}
        for qa_index, binding in enumerate(bindings, start=1):
            planned_id = int(binding["planned_page_id"])
            generated_id = int(binding["generated_page_id"])
            qa_results[planned_id] = save_page_qa(
                session,
                generated_id,
                commit=False,
            )
            if inject_failure_after_qa == qa_index:
                raise PublicCopyReconciliationInjectedFailure(
                    f"Injected public-copy reconciliation failure after QA {qa_index}."
                )
        session.flush()

        page_results: list[PublicCopyPageReconciliation] = []
        for binding in bindings:
            planned_id = int(binding["planned_page_id"])
            generated_id = int(binding["generated_page_id"])
            expected_hash = binding["expected_new_content_hash"]
            revision = new_revisions[planned_id]
            if (
                revision.id is None
                or revision.draft_hash_after != expected_hash
                or revision.created_by != reconciliation_actor
                or revision.reason != reason
            ):
                raise PublicCopyReconciliationError(
                    f"Generated Page {generated_id} revision evidence is not exact."
                )
            composition_read = read_composition_for_generated_page(
                session,
                generated_id,
            )
            composition = session.get(PageComposition, composition_read.id)
            if composition is None:
                raise PublicCopyReconciliationError(
                    f"Generated Page {generated_id} lost its current composition."
                )
            try:
                composition_revision = current_composition_revision(
                    session,
                    composition,
                )
            except PageCompositionHistoryError as exc:
                raise PublicCopyReconciliationError(str(exc)) from exc
            if (
                composition_revision.generated_page_revision_id != revision.id
                or composition_revision.content_hash != expected_hash
                or composition.composition_version
                != old_state[planned_id]["composition_version"] + 1
            ):
                raise PublicCopyReconciliationError(
                    f"Generated Page {generated_id} composition successor is not exact."
                )
            _assert_composition_copy_only_successor(
                session,
                binding,
                current=composition_revision,
            )
            qa = qa_results[planned_id]
            if (
                qa.qa_result_id is None
                or qa.latest_generated_page_revision_id != revision.id
                or qa.content_hash != expected_hash
                or qa.page_composition_id != composition.id
                or qa.composition_version != composition.composition_version
                or qa.composition_source_hash != composition.source_hash
            ):
                raise PublicCopyReconciliationError(
                    f"Generated Page {generated_id} QA successor is not exact."
                )
            current_page = session.get(GeneratedPage, generated_id)
            current_planned = session.get(PlannedPage, planned_id)
            current_qa_row = session.get(GeneratedPageQAResult, qa.qa_result_id)
            if (
                current_page is None
                or current_planned is None
                or current_qa_row is None
            ):
                raise PublicCopyReconciliationError(
                    f"Generated Page {generated_id} lost its post-state QA evidence."
                )
            _assert_page_identity(
                session,
                current_planned,
                current_page,
                binding,
                before=False,
            )
            _assert_after_identity(
                session,
                binding,
                page=current_page,
                latest_revision=revision,
                composition=composition,
                qa=current_qa_row,
                actor=reconciliation_actor,
                reason=reason,
            )
            _assert_prior_evidence_preserved(
                session,
                binding,
                new_qa_id=qa.qa_result_id,
                expected_predecessor_snapshot=old_state[planned_id],
            )
            page_results.append(
                PublicCopyPageReconciliation(
                    planned_page_id=planned_id,
                    generated_page_id=generated_id,
                    old_generated_page_revision_id=old_state[planned_id][
                        "revision_id"
                    ],
                    new_generated_page_revision_id=revision.id,
                    old_content_hash=old_state[planned_id]["content_hash"],
                    new_content_hash=expected_hash,
                    composition_id=composition.id or 0,
                    old_composition_version=old_state[planned_id][
                        "composition_version"
                    ],
                    new_composition_version=composition.composition_version,
                    old_composition_source_hash=old_state[planned_id][
                        "composition_source_hash"
                    ],
                    new_composition_source_hash=composition.source_hash,
                    old_qa_result_id=old_state[planned_id]["qa_id"],
                    new_qa_result_id=qa.qa_result_id,
                    new_qa_result_hash=qa.result_hash,
                )
            )
        _assert_operator_intents_exact(session, manifest)
        current_audit = _audit_current_scope(
            session,
            bindings=bindings,
            manifest=manifest,
            ruleset=package.ruleset,
            navigation_identity_bindings=state.navigation_identity_bindings,
        )
        _assert_immutable_history_snapshot(
            manifest,
            classification="all_after",
            generated_page_revisions=_lock_all_rows(
                session, GeneratedPageRevision
            ),
            page_composition_revisions=_lock_all_rows(
                session, PageCompositionRevision
            ),
            generated_page_qa_results=_lock_all_rows(
                session, GeneratedPageQAResult
            ),
        )
        if commit:
            session.commit()
        return PublicCopyReconciliationResult(
            status="applied",
            manifest_file_sha256=package.manifest_file_sha256,
            ruleset_payload_sha256=package.ruleset_payload_sha256,
            website_id=website_id,
            site_plan_id=site_plan_id,
            affected_page_count=len(bindings),
            page_results=tuple(page_results),
            appended_evidence_row_count=len(bindings) * 3,
            updated_head_row_count=len(bindings) * 2,
            superseded_qa_row_count=len(bindings),
            public_copy_audit_fingerprint=current_audit.fingerprint,
            public_copy_warning_count=current_audit.warning_finding_count,
            public_copy_informational_count=(
                current_audit.informational_finding_count
            ),
        )
    except Exception:
        session.rollback()
        raise


@dataclass(frozen=True)
class _ManifestBoundDraftingEvidencePreflight:
    manifest_file_sha256: str
    planned_page_ids: tuple[int, ...]
    assessment_row_ids: tuple[int, ...]
    assessment_status_counts: tuple[tuple[str, int], ...]
    scoped_assessment_rows_sha256: str
    locked_assessment_rows_sha256: str
    revision_authorities: tuple[ManifestBoundFullDraftRevisionAuthority, ...]


@dataclass(frozen=True)
class _GovernedNavigationItemBinding:
    navigation_item_id: int
    target_planned_page_id: int
    target_generated_page_id: int | None
    target_slug: str
    label: str
    parent_navigation_item_id: int | None
    position: int
    status: str
    identity_terms: tuple[str, ...]


@dataclass(frozen=True)
class _GovernedNavigationSetBinding:
    navigation_set_id: int
    set_type: str
    label: str
    items: tuple[_GovernedNavigationItemBinding, ...]


@dataclass(frozen=True)
class _PreflightState:
    classification: str
    candidate_audit_fingerprint: str
    drafting_evidence: _ManifestBoundDraftingEvidencePreflight
    navigation_identity_bindings: tuple[_GovernedNavigationSetBinding, ...]


def _lock_and_preflight(
    session: Session,
    package: PublicCopyManifestPackage,
    *,
    actor: str,
    reason: str,
) -> _PreflightState:
    _lock_reconciliation_tables(session)
    manifest = package.manifest
    scope = manifest["scope"]
    website_id = int(scope["website_id"])
    site_plan_id = int(scope["site_plan_id"])
    bindings = list(manifest["page_bindings"])
    binding_by_planned = {
        int(item["planned_page_id"]): item for item in bindings
    }
    planned_ids = list(binding_by_planned)
    generated_ids = [int(item["generated_page_id"]) for item in bindings]
    plan = session.exec(
        select(SitePlan)
        .where(SitePlan.id == site_plan_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
    if plan is None or plan.website_id != website_id:
        raise PublicCopyReconciliationError(
            "Correction manifest does not match the locked Website/SitePlan scope."
        )
    planned_rows = list(
        session.exec(
            select(PlannedPage)
            .where(PlannedPage.site_plan_id == site_plan_id)
            .order_by(PlannedPage.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    if [row.id for row in planned_rows] != planned_ids:
        raise PublicCopyReconciliationError(
            "Locked Planned Page inventory differs from the complete sealed scope."
        )
    generated_rows = list(
        session.exec(
            select(GeneratedPage)
            .where(GeneratedPage.website_id == website_id)
            .order_by(GeneratedPage.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    if [row.id for row in generated_rows] != sorted(generated_ids):
        raise PublicCopyReconciliationError(
            "Complete Website Generated Page inventory differs from the sealed scope."
        )
    generated_by_id = {row.id: row for row in generated_rows}
    composition_rows = list(
        session.exec(
            select(PageComposition)
            .where(PageComposition.site_plan_id == site_plan_id)
            .order_by(PageComposition.planned_page_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    if [row.planned_page_id for row in composition_rows] != planned_ids:
        raise PublicCopyReconciliationError(
            "Locked Page Composition inventory differs from the sealed scope."
        )
    composition_by_planned = {row.planned_page_id: row for row in composition_rows}
    qa_rows = list(
        session.exec(
            select(GeneratedPageQAResult)
            .where(
                GeneratedPageQAResult.site_plan_id == site_plan_id,
                GeneratedPageQAResult.lifecycle_status == "current",
            )
            .order_by(GeneratedPageQAResult.planned_page_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    if [row.planned_page_id for row in qa_rows] != planned_ids:
        raise PublicCopyReconciliationError(
            "Locked current-QA inventory differs from the sealed scope."
        )
    qa_by_planned = {row.planned_page_id: row for row in qa_rows}
    intents = list(
        session.exec(
            select(InternalLinkIntent)
            .where(InternalLinkIntent.site_plan_id == site_plan_id)
            .order_by(InternalLinkIntent.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    _assert_operator_intents_exact(session, manifest, rows=intents)
    locked_sources = _lock_and_validate_governed_sources(
        session,
        manifest=manifest,
        plan=plan,
        planned_rows=planned_rows,
        generated_rows=generated_rows,
    )
    navigation_identity_bindings = _governed_navigation_identity_bindings(
        website_id=website_id,
        site_plan_id=site_plan_id,
        locked_sources=locked_sources,
    )
    drafting_evidence = _preflight_manifest_bound_drafting_evidence(
        manifest=manifest,
        manifest_file_sha256=package.manifest_file_sha256,
        actor=actor,
        reason=reason,
        website_id=website_id,
        site_plan_id=site_plan_id,
        bindings=bindings,
        assessment_rows=locked_sources[DraftingEligibilityAssessment],
    )

    # The manifest seals the complete immutable-history inventory, not merely
    # the current Website slice. Lock every row so unrelated historical
    # evidence cannot drift while the site-wide batch is being applied.
    revisions = _lock_all_rows(session, GeneratedPageRevision)
    composition_history_rows = _lock_all_rows(
        session, PageCompositionRevision
    )
    all_qa_rows = _lock_all_rows(session, GeneratedPageQAResult)
    latest_by_generated: dict[int, GeneratedPageRevision] = {}
    for revision in revisions:
        current = latest_by_generated.get(revision.generated_page_id)
        if current is None or (revision.created_at, revision.id or 0) > (
            current.created_at,
            current.id or 0,
        ):
            latest_by_generated[revision.generated_page_id] = revision
    planned_by_id = {row.id: row for row in planned_rows}
    before_count = after_count = 0
    candidate_drafts: dict[int, dict[str, Any]] = {}
    for binding in bindings:
        planned_id = int(binding["planned_page_id"])
        generated_id = int(binding["generated_page_id"])
        page = generated_by_id[generated_id]
        current_hash = draft_content_hash(page.draft_content or {})
        if current_hash == binding["current_revision"]["content_hash"]:
            before_count += 1
        elif current_hash == binding["expected_new_content_hash"]:
            after_count += 1
        else:
            raise PublicCopyReconciliationError(
                f"Generated Page {generated_id} is neither the sealed before nor after state."
            )
        _assert_page_identity(
            session,
            planned_by_id[planned_id],
            page,
            binding,
            before=current_hash == binding["current_revision"]["content_hash"],
        )
        composition = composition_by_planned[planned_id]
        qa = qa_by_planned[planned_id]
        if current_hash == binding["current_revision"]["content_hash"]:
            _assert_before_identity(
                session,
                binding,
                page=page,
                latest_revision=latest_by_generated.get(generated_id),
                composition=composition,
                qa=qa,
            )
        else:
            _assert_after_identity(
                session,
                binding,
                page=page,
                latest_revision=latest_by_generated.get(generated_id),
                composition=composition,
                qa=qa,
                actor=actor,
                reason=reason,
            )
            _assert_prior_evidence_preserved(
                session,
                binding,
                new_qa_id=qa.id or 0,
            )
    if before_count and after_count:
        raise PublicCopyReconciliationError(
            "Correction scope is a mixed before/after state; refusing a partial replay."
        )
    if before_count != len(bindings) and after_count != len(bindings):
        raise PublicCopyReconciliationError(
            "Correction scope classification is incomplete."
        )
    _assert_immutable_history_snapshot(
        manifest,
        classification="all_before" if before_count else "all_after",
        generated_page_revisions=revisions,
        page_composition_revisions=composition_history_rows,
        generated_page_qa_results=all_qa_rows,
    )

    # Re-derive all source-owned copy only after the complete identity preflight,
    # but still before the first write.
    for binding in bindings:
        planned_id = int(binding["planned_page_id"])
        generated_id = int(binding["generated_page_id"])
        page = generated_by_id[generated_id]
        if before_count:
            derived = build_public_copy_reconciled_draft(
                session,
                planned_by_id[planned_id],
                page.draft_content or {},
            )
            if derived != binding["expected_draft_content"]:
                raise PublicCopyReconciliationError(
                    f"Generated Page {generated_id} source-derived candidate differs from the sealed manifest."
                )
            candidate_drafts[planned_id] = derived
        elif page.draft_content != binding["expected_draft_content"]:
            raise PublicCopyReconciliationError(
                f"Generated Page {generated_id} all-after payload differs from the sealed manifest."
            )
        else:
            candidate_drafts[planned_id] = page.draft_content or {}
    _assert_correction_ledger_against_locked_drafts(
        manifest,
        bindings=binding_by_planned,
        generated_by_id=generated_by_id,
        intents_by_id={row.id: row for row in intents if row.id is not None},
        all_before=bool(before_count),
    )
    candidate_audit = _audit_draft_scope(
        bindings=bindings,
        drafts_by_planned=candidate_drafts,
        manifest=manifest,
        ruleset=package.ruleset,
    )
    return _PreflightState(
        classification="all_before" if before_count else "all_after",
        candidate_audit_fingerprint=candidate_audit.fingerprint,
        drafting_evidence=drafting_evidence,
        navigation_identity_bindings=navigation_identity_bindings,
    )


def _lock_reconciliation_tables(session: Session) -> None:
    """Prevent PostgreSQL DML phantoms across the sealed reconciliation scope."""

    connection = session.connection()
    if connection.dialect.name != "postgresql":
        return
    table_names = sorted(
        {model.__table__.name for model in _RECONCILIATION_TABLE_MODELS}
    )
    quote = connection.dialect.identifier_preparer.quote
    identifiers = ", ".join(quote(name) for name in table_names)
    connection.exec_driver_sql(
        f"LOCK TABLE {identifiers} IN SHARE ROW EXCLUSIVE MODE"
    )


def _preflight_manifest_bound_drafting_evidence(
    *,
    manifest: dict[str, Any],
    manifest_file_sha256: str,
    actor: str,
    reason: str,
    website_id: int,
    site_plan_id: int,
    bindings: list[dict[str, Any]],
    assessment_rows: list[DraftingEligibilityAssessment],
) -> _ManifestBoundDraftingEvidencePreflight:
    """Bind revision authority to sealed pre-existing drafting evidence.

    Drafting eligibility decides whether a new draft may be created or an
    ordinary edit may replace it.  This reconciliation instead repairs exact
    already-generated content under a complete SHA-pinned correction manifest.
    It therefore preserves and validates every assessment row without
    reinterpreting a historical non-eligible status as a veto over the narrower
    authorized revision.
    """

    expected_ids = tuple(int(binding["planned_page_id"]) for binding in bindings)
    scoped_rows = tuple(
        sorted(
            (
                row
                for row in assessment_rows
                if row.site_plan_id == site_plan_id
            ),
            key=lambda row: int(row.planned_page_id),
        )
    )
    observed_ids = tuple(int(row.planned_page_id) for row in scoped_rows)
    if observed_ids != expected_ids:
        raise PublicCopyReconciliationError(
            "Drafting-eligibility assessment inventory differs from the complete sealed page scope."
        )
    if any(
        row.id is None
        or row.website_id != website_id
        or row.site_plan_id != site_plan_id
        for row in scoped_rows
    ):
        raise PublicCopyReconciliationError(
            "Drafting-eligibility assessment evidence is outside the sealed Website/SitePlan scope."
        )

    locked_hashes = manifest.get("governed_fact_snapshot", {}).get(
        "locked_source_table_sha256"
    )
    expected_locked_hash = (
        locked_hashes.get("drafting_eligibility_assessments")
        if isinstance(locked_hashes, dict)
        else None
    )
    observed_locked_hash = canonical_model_rows_sha256(
        DraftingEligibilityAssessment,
        [row.model_dump(mode="json") for row in assessment_rows],
    )
    if expected_locked_hash != observed_locked_hash:
        raise PublicCopyReconciliationError(
            "Locked drafting-eligibility evidence differs from the sealed manifest."
        )

    status_counts: dict[str, int] = {}
    for row in scoped_rows:
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
    authorities = tuple(
        ManifestBoundFullDraftRevisionAuthority(
            manifest_file_sha256=manifest_file_sha256,
            website_id=website_id,
            site_plan_id=site_plan_id,
            planned_page_id=int(binding["planned_page_id"]),
            generated_page_id=int(binding["generated_page_id"]),
            expected_current_hash=binding["current_revision"]["content_hash"],
            expected_new_hash=binding["expected_new_content_hash"],
            actor=actor,
            reason=reason,
            planned_page_status=binding["page_identity"][
                "planned_page_status"
            ],
            generated_page_status=binding["page_identity"][
                "generated_page_status"
            ],
            expected_changed_fields=tuple(
                sorted(set(binding["expected_changed_top_level_fields"]))
            ),
        )
        for binding in bindings
    )
    return _ManifestBoundDraftingEvidencePreflight(
        manifest_file_sha256=manifest_file_sha256,
        planned_page_ids=expected_ids,
        assessment_row_ids=tuple(int(row.id or 0) for row in scoped_rows),
        assessment_status_counts=tuple(sorted(status_counts.items())),
        scoped_assessment_rows_sha256=canonical_model_rows_sha256(
            DraftingEligibilityAssessment,
            [row.model_dump(mode="json") for row in scoped_rows],
        ),
        locked_assessment_rows_sha256=observed_locked_hash,
        revision_authorities=authorities,
    )


def _lock_all_rows(session: Session, model: type[Any]) -> list[Any]:
    """Lock one complete governed source table in deterministic identity order."""

    return list(
        session.exec(
            select(model)
            .order_by(model.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )


def _assert_immutable_history_snapshot(
    manifest: dict[str, Any],
    *,
    classification: str,
    generated_page_revisions: list[GeneratedPageRevision],
    page_composition_revisions: list[PageCompositionRevision],
    generated_page_qa_results: list[GeneratedPageQAResult],
) -> None:
    expected = manifest.get("immutable_history_snapshot")
    if not isinstance(expected, dict):
        raise PublicCopyReconciliationError(
            "Correction manifest lacks its immutable-history snapshot."
        )
    observed_rows: dict[str, list[Any]] = {
        "generated_page_revisions": generated_page_revisions,
        "page_composition_revisions": page_composition_revisions,
        "generated_page_qa_results": generated_page_qa_results,
    }
    if classification == "all_before":
        if any(not rows for rows in observed_rows.values()):
            raise PublicCopyReconciliationError(
                "Immutable-history inventory is unexpectedly empty."
            )
        observed = {
            table_name: {
                **{
                    "row_count": len(rows),
                    "maximum_id": max(int(row.id or 0) for row in rows),
                    "canonical_rows_sha256": canonical_model_rows_sha256(
                        _IMMUTABLE_HISTORY_MODELS[table_name],
                        [row.model_dump(mode="json") for row in rows],
                    ),
                },
                **(
                    _qa_history_snapshot_fields(rows)
                    if table_name == "generated_page_qa_results"
                    else {}
                ),
            }
            for table_name, rows in observed_rows.items()
        }
        if observed == expected:
            return
    elif classification == "all_after":
        expected_new_rows = len(manifest["page_bindings"])
        for table_name in (
            "generated_page_revisions",
            "page_composition_revisions",
        ):
            contract = expected[table_name]
            rows = observed_rows[table_name]
            old_rows = [
                row for row in rows if int(row.id or 0) <= contract["maximum_id"]
            ]
            new_rows = [
                row for row in rows if int(row.id or 0) > contract["maximum_id"]
            ]
            if (
                len(old_rows) != contract["row_count"]
                or len(new_rows) != expected_new_rows
                or canonical_model_rows_sha256(
                    _IMMUTABLE_HISTORY_MODELS[table_name],
                    [row.model_dump(mode="json") for row in old_rows],
                )
                != contract["canonical_rows_sha256"]
            ):
                break
        else:
            qa_contract = expected["generated_page_qa_results"]
            qa_rows = observed_rows["generated_page_qa_results"]
            old_qa = [
                row
                for row in qa_rows
                if int(row.id or 0) <= qa_contract["maximum_id"]
            ]
            new_qa = [
                row
                for row in qa_rows
                if int(row.id or 0) > qa_contract["maximum_id"]
            ]
            current_ids = set(qa_contract["current_row_ids"])
            transitioned = [row for row in old_qa if row.id in current_ids]
            noncurrent = [row for row in old_qa if row.id not in current_ids]
            if (
                len(old_qa) == qa_contract["row_count"]
                and len(new_qa) == expected_new_rows
                and [row.id for row in transitioned]
                == qa_contract["current_row_ids"]
                and canonical_model_rows_sha256(
                    GeneratedPageQAResult,
                    [row.model_dump(mode="json") for row in noncurrent],
                )
                == qa_contract["canonical_noncurrent_rows_sha256"]
                and canonical_json_sha256(
                    [_qa_preserved_snapshot(row) for row in transitioned]
                )
                == qa_contract["canonical_current_preserved_rows_sha256"]
            ):
                return
    else:  # pragma: no cover - caller owns the closed classification
        raise PublicCopyReconciliationError(
            "Immutable-history validation received an unknown state classification."
        )
    raise PublicCopyReconciliationError(
        "Immutable Generated Page, Page Composition, or QA history differs "
        "from the sealed pre-reconciliation snapshot."
    )


def _qa_preserved_snapshot(row: GeneratedPageQAResult) -> dict[str, Any]:
    values = canonicalize_model_row_timestamps(
        GeneratedPageQAResult,
        row.model_dump(mode="json"),
    )
    values.pop("lifecycle_status", None)
    values.pop("updated_at", None)
    return values


def _qa_history_snapshot_fields(rows: list[Any]) -> dict[str, Any]:
    current = [row for row in rows if row.lifecycle_status == "current"]
    noncurrent = [row for row in rows if row.lifecycle_status != "current"]
    return {
        "current_row_ids": [int(row.id or 0) for row in current],
        "canonical_noncurrent_rows_sha256": canonical_model_rows_sha256(
            GeneratedPageQAResult,
            [row.model_dump(mode="json") for row in noncurrent],
        ),
        "canonical_current_preserved_rows_sha256": canonical_json_sha256(
            [_qa_preserved_snapshot(row) for row in current]
        ),
    }


def _lock_and_validate_governed_sources(
    session: Session,
    *,
    manifest: dict[str, Any],
    plan: SitePlan,
    planned_rows: list[PlannedPage],
    generated_rows: list[GeneratedPage],
) -> dict[type[Any], list[Any]]:
    """Freeze every non-copy source domain consumed by composition refresh.

    The active-local reconciliation is intentionally site-wide and exclusive.
    Locking the complete small governed tables avoids a source writer committing
    between draft derivation and the final current-composition validation.  Page,
    composition, QA, and intent rows are locked by the caller before this helper.
    """

    del planned_rows, generated_rows  # both scopes were already proven by the caller
    locked: dict[type[Any], list[Any]] = {}
    for model, _table_name in _LOCKED_SOURCE_MODELS:
        locked[model] = _lock_all_rows(session, model)

    snapshot = manifest.get("governed_fact_snapshot")
    if not isinstance(snapshot, dict):
        raise PublicCopyReconciliationError(
            "Correction manifest lacks its governed-fact snapshot."
        )
    website_rows = [row for row in locked[Website] if row.id == plan.website_id]
    if len(website_rows) != 1:
        raise PublicCopyReconciliationError(
            "Locked Site Plan Website is missing from the governed source inventory."
        )
    website = website_rows[0]
    business_rows = [
        row for row in locked[Business] if row.id == website.business_id
    ]
    brand_rows = [row for row in locked[Brand] if row.id == website.brand_id]
    if len(business_rows) != 1 or len(brand_rows) != 1:
        raise PublicCopyReconciliationError(
            "Locked Website Business/Brand identity is incomplete."
        )

    def exact_fields(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
        values = row.model_dump(mode="json")
        return {field: values.get(field) for field in fields}

    observed_business = exact_fields(
        business_rows[0],
        (
            "id",
            "brand_name",
            "company_name",
            "business_type",
            "phone",
            "email",
            "website",
            "main_city",
            "state",
            "license_number",
            "certified_operator",
            "description",
        ),
    )
    observed_brand = exact_fields(
        brand_rows[0],
        ("id", "business_id", "brand_name", "tagline", "description", "status"),
    )
    observed_website = exact_fields(
        website,
        (
            "id",
            "business_id",
            "brand_id",
            "website_name",
            "domain",
            "public_url",
            "locale",
        ),
    )
    if (
        snapshot.get("business") != observed_business
        or snapshot.get("brand") != observed_brand
        or snapshot.get("website") != observed_website
    ):
        raise PublicCopyReconciliationError(
            "Locked Business/Brand/Website facts differ from the sealed manifest."
        )
    for model, field in (
        (Service, "services_sha256"),
        (County, "counties_sha256"),
        (City, "cities_sha256"),
        (KnowledgeBlock, "knowledge_blocks_sha256"),
    ):
        observed_hash = canonical_model_rows_sha256(
            model,
            [row.model_dump(mode="json") for row in locked[model]],
        )
        if snapshot.get(field) != observed_hash:
            raise PublicCopyReconciliationError(
                f"Locked governed source inventory differs at {field}."
            )
    locked_hashes = snapshot.get("locked_source_table_sha256")
    if not isinstance(locked_hashes, dict):
        raise PublicCopyReconciliationError(
            "Correction manifest lacks its complete locked-source hashes."
        )
    observed_locked_hashes = {
        table_name: canonical_model_rows_sha256(
            model,
            [row.model_dump(mode="json") for row in locked[model]],
        )
        for model, table_name in _LOCKED_SOURCE_MODELS
    }
    if tuple(sorted(observed_locked_hashes)) != tuple(
        sorted(PUBLIC_COPY_LOCKED_SOURCE_TABLE_NAMES)
    ):
        raise PublicCopyReconciliationError(
            "Locked-source model coverage differs from the manifest contract."
        )
    if locked_hashes != observed_locked_hashes:
        raise PublicCopyReconciliationError(
            "A locked transaction source table differs from the sealed manifest."
        )
    return locked


def _governed_navigation_identity_bindings(
    *,
    website_id: int,
    site_plan_id: int,
    locked_sources: dict[type[Any], list[Any]],
) -> tuple[_GovernedNavigationSetBinding, ...]:
    """Bind each public navigation label to its exact governed target identity."""

    navigation_sets = {
        int(row.id): row
        for row in locked_sources[NavigationSet]
        if row.id is not None
        and row.website_id == website_id
        and row.site_plan_id == site_plan_id
        and row.status == "active"
    }
    if {
        row.set_type for row in navigation_sets.values()
    } != {"primary", "utility", "footer"} or len(navigation_sets) != 3:
        raise PublicCopyReconciliationError(
            "Locked active Navigation Set inventory is not exactly primary, utility, and footer."
        )
    planned_pages = {
        int(row.id): row
        for row in locked_sources[PlannedPage]
        if row.id is not None
        and row.website_id == website_id
        and row.site_plan_id == site_plan_id
    }
    cities = {
        int(row.id): row
        for row in locked_sources[City]
        if row.id is not None
    }
    counties = {
        int(row.id): row
        for row in locked_sources[County]
        if row.id is not None
    }
    items_by_set: dict[int, list[_GovernedNavigationItemBinding]] = {
        navigation_set_id: [] for navigation_set_id in navigation_sets
    }
    seen: set[tuple[int, int]] = set()
    for item in locked_sources[NavigationItem]:
        if item.status != "active":
            continue
        if (
            item.id is None
            or item.website_id != website_id
            or item.site_plan_id != site_plan_id
            or item.navigation_set_id not in navigation_sets
        ):
            raise PublicCopyReconciliationError(
                "Active Navigation Item leaves the locked Website, Site Plan, or "
                "active Navigation Set scope."
            )
        target = planned_pages.get(int(item.target_planned_page_id))
        if target is None:
            raise PublicCopyReconciliationError(
                "Active Navigation Item target leaves the complete locked Planned Page scope."
            )
        identity_terms: set[str] = set()
        if target.city_id is not None:
            city = cities.get(int(target.city_id))
            if city is None or city.county_id != target.county_id:
                raise PublicCopyReconciliationError(
                    "Navigation target City identity differs from the locked Planned Page."
                )
            if isinstance(city.city_name, str) and city.city_name.strip():
                identity_terms.add(city.city_name.strip())
        if target.county_id is not None:
            county = counties.get(int(target.county_id))
            if county is None:
                raise PublicCopyReconciliationError(
                    "Navigation target County identity is missing from the locked scope."
                )
            if isinstance(county.county_name, str) and county.county_name.strip():
                identity_terms.add(county.county_name.strip())
        identity = (int(item.navigation_set_id), int(item.id))
        if identity in seen:
            raise PublicCopyReconciliationError(
                "Active Navigation Item identity is duplicated in the locked scope."
            )
        seen.add(identity)
        items_by_set[identity[0]].append(
            _GovernedNavigationItemBinding(
                navigation_item_id=identity[1],
                target_planned_page_id=int(target.id),
                target_generated_page_id=(
                    int(target.generated_page_id)
                    if target.generated_page_id is not None
                    else None
                ),
                target_slug=str(target.intended_slug),
                label=str(item.label),
                parent_navigation_item_id=(
                    int(item.parent_navigation_item_id)
                    if item.parent_navigation_item_id is not None
                    else None
                ),
                position=int(item.position),
                status=str(item.status),
                identity_terms=tuple(sorted(identity_terms)),
            )
        )
    return tuple(
        sorted(
            (
                _GovernedNavigationSetBinding(
                    navigation_set_id=navigation_set_id,
                    set_type=str(navigation_set.set_type),
                    label=str(navigation_set.label),
                    items=tuple(
                        sorted(
                            items_by_set[navigation_set_id],
                            key=lambda value: (
                                value.position,
                                value.navigation_item_id,
                            ),
                        )
                    ),
                )
                for navigation_set_id, navigation_set in navigation_sets.items()
            ),
            key=lambda value: value.navigation_set_id,
        )
    )


_SECTION_FIELD_PATH = re.compile(
    r"^draft_content\.sections\[key=([^\]]+)\]\.body"
    r"(?:::exact_sentence\[knowledge_block_id=([1-9][0-9]*)\])?$"
)
_DESTINATION_FIELD_PATH = re.compile(
    r"^draft_content\.public_destination_copy"
    r"\[source_kind=([a-z_]+),source_record_id=([1-9][0-9]*)\]"
    r"\.description$"
)
_TOP_LEVEL_FIELD_PATH = re.compile(
    r"^draft_content\.([a-z][a-z0-9_]*)$"
)


def _draft_field_value(draft: dict[str, Any], field_path: str) -> Any:
    section_match = _SECTION_FIELD_PATH.fullmatch(field_path)
    if section_match:
        section_key = section_match.group(1)
        matches = [
            item
            for item in draft.get("sections", [])
            if isinstance(item, dict) and item.get("key") == section_key
        ]
        if len(matches) != 1:
            raise PublicCopyReconciliationError(
                f"Correction field path does not resolve one section: {field_path}."
            )
        return matches[0].get("body")
    destination_match = _DESTINATION_FIELD_PATH.fullmatch(field_path)
    if destination_match:
        source_kind = destination_match.group(1)
        source_record_id = int(destination_match.group(2))
        matches = [
            item
            for item in draft.get("public_destination_copy", [])
            if isinstance(item, dict)
            and item.get("source_kind") == source_kind
            and item.get("source_record_id") == source_record_id
        ]
        if len(matches) > 1:
            raise PublicCopyReconciliationError(
                f"Correction field path resolves duplicate destination copy: {field_path}."
            )
        return matches[0].get("description") if matches else None
    top_level_match = _TOP_LEVEL_FIELD_PATH.fullmatch(field_path)
    if top_level_match:
        return draft.get(top_level_match.group(1))
    raise PublicCopyReconciliationError(
        f"Correction field path is outside the executable public-draft contract: {field_path}."
    )


def _assert_correction_ledger_against_locked_drafts(
    manifest: dict[str, Any],
    *,
    bindings: dict[int, dict[str, Any]],
    generated_by_id: dict[int, GeneratedPage],
    intents_by_id: dict[int, InternalLinkIntent],
    all_before: bool,
) -> None:
    for correction in manifest.get("corrections", []):
        planned_id = int(correction["planned_page_id"])
        binding = bindings.get(planned_id)
        if binding is None:
            raise PublicCopyReconciliationError(
                "Correction ledger references an unbound Planned Page."
            )
        page = generated_by_id[int(binding["generated_page_id"])]
        before_draft = page.draft_content or {}
        expected_draft = binding["expected_draft_content"]
        field_path = str(correction["field_path"])
        current_value = _draft_field_value(before_draft, field_path)
        expected_value = _draft_field_value(expected_draft, field_path)
        operation = correction["operation"]
        original = correction["original_text"]
        replacement = correction.get("replacement_text")

        if operation == "replace_exact_value":
            if expected_value != replacement:
                raise PublicCopyReconciliationError(
                    f"Correction {correction['entry_id']} replacement is not the sealed after value."
                )
            if all_before and current_value != original:
                raise PublicCopyReconciliationError(
                    f"Correction {correction['entry_id']} original value is not current."
                )
            if not all_before and current_value != replacement:
                raise PublicCopyReconciliationError(
                    f"Correction {correction['entry_id']} after value is not current."
                )
        elif operation == "remove_exact_sentence":
            if not isinstance(original, str) or not isinstance(expected_value, str):
                raise PublicCopyReconciliationError(
                    f"Correction {correction['entry_id']} sentence omission is malformed."
                )
            if all_before:
                if not isinstance(current_value, str) or current_value.count(original) != 1:
                    raise PublicCopyReconciliationError(
                        f"Correction {correction['entry_id']} original sentence is not exact."
                    )
                prefix = " " + original
                removed = (
                    current_value.replace(prefix, "", 1)
                    if prefix in current_value
                    else current_value.replace(original, "", 1)
                )
                if removed != expected_value:
                    raise PublicCopyReconciliationError(
                        f"Correction {correction['entry_id']} omission changes more than one exact sentence."
                    )
            elif current_value != expected_value or original in current_value:
                raise PublicCopyReconciliationError(
                    f"Correction {correction['entry_id']} omission after-state is not exact."
                )
        elif operation == "add_destination_derived_public_projection":
            item = correction.get("public_destination_item")
            destination = correction.get("destination_identity")
            if not isinstance(item, dict) or not isinstance(destination, dict):
                raise PublicCopyReconciliationError(
                    f"Correction {correction['entry_id']} destination evidence is missing."
                )
            matching_items = [
                value
                for value in expected_draft.get("public_destination_copy", [])
                if isinstance(value, dict)
                and value.get("source_kind") == item.get("source_kind")
                and value.get("source_record_id") == item.get("source_record_id")
            ]
            if matching_items != [item] or expected_value != replacement:
                raise PublicCopyReconciliationError(
                    f"Correction {correction['entry_id']} public destination projection is not exact."
                )
            if {
                "planned_page_id": item.get("target_planned_page_id"),
                "generated_page_id": item.get("target_generated_page_id"),
                "slug": item.get("slug"),
                "working_name": item.get("label"),
            } != {
                "planned_page_id": destination.get("planned_page_id"),
                "generated_page_id": destination.get("generated_page_id"),
                "slug": destination.get("slug"),
                "working_name": destination.get("working_name"),
            }:
                raise PublicCopyReconciliationError(
                    f"Correction {correction['entry_id']} target identity is contradictory."
                )
            if item.get("source_kind") != "internal_link_intent":
                raise PublicCopyReconciliationError(
                    f"Correction {correction['entry_id']} has an unsupported destination source."
                )
            intent = intents_by_id.get(int(item["source_record_id"]))
            if intent is None or intent.purpose != original:
                raise PublicCopyReconciliationError(
                    f"Correction {correction['entry_id']} operator-purpose predecessor is not exact."
                )
            if all_before and current_value is not None:
                raise PublicCopyReconciliationError(
                    f"Correction {correction['entry_id']} projection already exists in the before state."
                )
            if not all_before and current_value != replacement:
                raise PublicCopyReconciliationError(
                    f"Correction {correction['entry_id']} projection after-state is not exact."
                )
        else:  # pragma: no cover - strict manifest validation owns this boundary
            raise PublicCopyReconciliationError(
                f"Correction {correction['entry_id']} operation is unsupported."
            )


def _assert_page_identity(
    session: Session,
    planned: PlannedPage,
    generated: GeneratedPage,
    binding: dict[str, Any],
    *,
    before: bool,
) -> None:
    identity = binding["page_identity"]
    planned_values = {
        "planned_page_status": planned.planning_status,
        "planned_page_parent_id": planned.parent_planned_page_id,
        "service_id": planned.service_id,
        "county_id": planned.county_id,
        "city_id": planned.city_id,
    }
    expected_planned_values = {
        key: identity.get(key) for key in planned_values
    }
    if planned_values != expected_planned_values:
        raise PublicCopyReconciliationError(
            f"Planned Page {planned.id} identity differs from the sealed manifest."
        )
    if (
        planned.website_id != binding["website_id"]
        or planned.site_plan_id != binding["site_plan_id"]
        or planned.generated_page_id != generated.id
        or planned.page_type != binding["page_type"]
        or planned.working_name != binding["working_name"]
        or planned.intended_slug != binding["slug"]
        or generated.website_id != binding["website_id"]
        or generated.page_type != identity["generated_page_type"]
        or generated.page_slug != identity["generated_page_slug"]
        or generated.status != identity["generated_page_status"]
        or generated.generation_status != identity["generated_page_generation_status"]
    ):
        raise PublicCopyReconciliationError(
            f"Generated Page {generated.id} scope/type/slug/status identity changed."
        )
    current_draft = generated.draft_content or {}
    if generated.content_body != _rendered_draft_content(
        session,
        generated,
        current_draft,
    ):
        raise PublicCopyReconciliationError(
            f"Generated Page {generated.id} rendered content body is not canonical."
        )
    if _generated_page_preserved_state_hash(generated) != identity.get(
        "generated_page_preserved_state_sha256"
    ):
        raise PublicCopyReconciliationError(
            f"Generated Page {generated.id} changed a preserved identity or publication field."
        )
    if before:
        before_values = {
            "generated_page_title": generated.page_title,
            "generated_page_qa_status": generated.qa_status,
            "generated_page_meta_title": generated.meta_title,
            "generated_page_meta_description": generated.meta_description,
            "generated_page_h1": generated.h1,
        }
        if before_values != {key: identity.get(key) for key in before_values}:
            raise PublicCopyReconciliationError(
                f"Generated Page {generated.id} public mirror fields changed before reconciliation."
            )
        expected_body_hash = identity.get("generated_page_content_body_sha256")
        if (
            expected_body_hash is not None
            and hashlib.sha256(
                (generated.content_body or "").encode("utf-8")
            ).hexdigest()
            != expected_body_hash
        ):
            raise PublicCopyReconciliationError(
                f"Generated Page {generated.id} rendered body differs from its sealed identity."
            )
        expected_updated_at = identity.get("generated_page_updated_at")
        observed_updated_at = canonicalize_model_row_timestamps(
            GeneratedPage,
            {"updated_at": generated.model_dump(mode="json").get("updated_at")},
        )["updated_at"]
        if (
            expected_updated_at is not None
            and observed_updated_at != expected_updated_at
        ):
            raise PublicCopyReconciliationError(
                f"Generated Page {generated.id} update identity differs from its sealed state."
            )
    else:
        draft = binding["expected_draft_content"]
        if (
            generated.page_title != draft["title"]
            or generated.meta_title != draft["meta_title"]
            or generated.meta_description != draft["meta_description"]
            or generated.h1 != draft["h1"]
        ):
            raise PublicCopyReconciliationError(
                f"Generated Page {generated.id} public mirror fields do not match its after draft."
            )


def _rendered_draft_content(
    session: Session,
    page: GeneratedPage,
    draft: dict[str, Any],
) -> str:
    if draft.get("schema_version") == "planned-page-draft-v1":
        return render_planned_page_content(
            PlannedPageDraftContent.model_validate(draft)
        )
    return render_content_body(
        DraftContent.model_validate(draft),
        build_website_context(session, page_id=page.id or 0),
    )


def _assert_before_identity(
    session: Session,
    binding: dict[str, Any],
    *,
    page: GeneratedPage,
    latest_revision: GeneratedPageRevision | None,
    composition: PageComposition,
    qa: GeneratedPageQAResult,
) -> None:
    current_revision = binding["current_revision"]
    if (
        (latest_revision.id if latest_revision else None)
        != current_revision["latest_page_revision_id"]
        or (latest_revision.draft_hash_after if latest_revision else None)
        != current_revision["latest_page_revision_hash_after"]
    ):
        raise PublicCopyReconciliationError(
            f"Generated Page {page.id} latest revision identity changed."
        )
    observed_revision_row_hash = (
        canonical_model_row_sha256(
            GeneratedPageRevision,
            latest_revision.model_dump(mode="json"),
        )
        if latest_revision is not None
        else None
    )
    if observed_revision_row_hash != current_revision.get(
        "latest_page_revision_row_sha256"
    ):
        raise PublicCopyReconciliationError(
            f"Generated Page {page.id} latest revision row differs from its sealed evidence."
        )
    current_composition = binding["current_composition"]
    if (
        composition.id != current_composition["id"]
        or composition.composition_version != current_composition["version"]
        or composition.source_hash != current_composition["source_hash"]
    ):
        raise PublicCopyReconciliationError(
            f"Generated Page {page.id} current composition identity changed."
        )
    try:
        revision = current_composition_revision(session, composition, lock=True)
    except PageCompositionHistoryError as exc:
        raise PublicCopyReconciliationError(str(exc)) from exc
    if (
        revision.id != current_composition["history_revision_id"]
        or revision.revision_hash != current_composition["history_revision_hash"]
        or canonical_model_row_sha256(
            PageCompositionRevision,
            revision.model_dump(mode="json"),
        )
        != current_composition["history_revision_row_sha256"]
        or revision.content_hash != current_composition["content_hash"]
        or revision.generated_page_revision_id
        != current_revision["bound_generated_page_revision_id"]
    ):
        raise PublicCopyReconciliationError(
            f"Generated Page {page.id} immutable composition binding changed."
        )
    current_qa = binding["current_qa"]
    if (
        qa.id != current_qa["id"]
        or qa.result_hash != current_qa["result_hash"]
        or qa.source_hash != current_qa["source_hash"]
        or qa.qa_ruleset_key != current_qa["ruleset_key"]
        or qa.qa_ruleset_version != current_qa["ruleset_version"]
        or qa.qa_ruleset_hash != current_qa["ruleset_hash"]
        or qa.readiness_status != current_qa["readiness_status"]
        or qa.page_composition_id != composition.id
        or qa.composition_version != composition.composition_version
        or qa.composition_source_hash != composition.source_hash
        or qa.content_hash != current_revision["content_hash"]
        or _qa_preserved_evidence_hash(qa)
        != current_qa["preserved_evidence_sha256"]
    ):
        raise PublicCopyReconciliationError(
            f"Generated Page {page.id} current QA identity changed."
        )
    if qa_result_record_hash(qa.model_dump(mode="python")) != qa.result_hash:
        raise PublicCopyReconciliationError(
            f"Generated Page {page.id} current QA evidence hash is invalid."
        )


def _assert_after_identity(
    session: Session,
    binding: dict[str, Any],
    *,
    page: GeneratedPage,
    latest_revision: GeneratedPageRevision | None,
    composition: PageComposition,
    qa: GeneratedPageQAResult,
    actor: str,
    reason: str,
) -> None:
    expected_hash = binding["expected_new_content_hash"]
    if (
        latest_revision is None
        or latest_revision.generated_page_id != page.id
        or latest_revision.draft_hash_before
        != binding["current_revision"]["content_hash"]
        or draft_content_hash(latest_revision.draft_content_before)
        != binding["current_revision"]["content_hash"]
        or latest_revision.draft_hash_after != expected_hash
        or latest_revision.draft_content_after != binding["expected_draft_content"]
        or latest_revision.changed_fields
        != binding["expected_changed_top_level_fields"]
        or latest_revision.created_by != actor
        or latest_revision.reason != reason
    ):
        raise PublicCopyReconciliationError(
            f"Generated Page {page.id} after-state revision evidence is not exact."
        )
    if not _same_instant(page.updated_at, latest_revision.created_at):
        raise PublicCopyReconciliationError(
            f"Generated Page {page.id} head timestamp is not bound to its new revision."
        )
    try:
        composition_revision = current_composition_revision(
            session,
            composition,
            lock=True,
        )
    except PageCompositionHistoryError as exc:
        raise PublicCopyReconciliationError(str(exc)) from exc
    if (
        composition.id != binding["current_composition"]["id"]
        or composition.composition_version
        != binding["current_composition"]["version"] + 1
        or composition_revision.supersedes_revision_id
        != binding["current_composition"]["history_revision_id"]
        or composition_revision.supersedes_revision_hash
        != binding["current_composition"]["history_revision_hash"]
        or composition_revision.generated_page_revision_id != latest_revision.id
        or composition_revision.content_hash != expected_hash
        or composition_revision.recorded_by != COMPOSITION_REFRESH_ACTOR
        or composition_revision.record_source != COMPOSITION_REFRESH_SOURCE
        or qa.supersedes_qa_result_id != binding["current_qa"]["id"]
        or qa.latest_generated_page_revision_id != latest_revision.id
        or qa.content_hash != expected_hash
        or qa.page_composition_id != composition.id
        or qa.composition_version != composition.composition_version
        or qa.composition_source_hash != composition.source_hash
        or not _same_instant(qa.created_at, qa.evaluated_at)
        or not _same_instant(qa.updated_at, qa.evaluated_at)
    ):
        raise PublicCopyReconciliationError(
            f"Generated Page {page.id} after-state composition/QA binding is not exact."
        )
    _assert_composition_copy_only_successor(
        session,
        binding,
        current=composition_revision,
    )
    _assert_effective_qa_identity(session, page, qa)


def _same_instant(left: datetime, right: datetime) -> bool:
    def normalized(value: datetime) -> datetime:
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )

    return normalized(left) == normalized(right)


def _assert_effective_qa_identity(
    session: Session,
    page: GeneratedPage,
    row: GeneratedPageQAResult,
) -> None:
    effective = effective_page_qa_state(session, page)
    if (
        effective.classification != "current_exact_identity_match"
        or effective.record is None
        or effective.record.id != row.id
        or effective.result is None
        or effective.result.qa_result_id != row.id
    ):
        reason = " ".join(effective.reasons)
        raise PublicCopyReconciliationError(
            f"Generated Page {page.id} durable QA is not exact-current: {reason}"
        )


def _assert_composition_copy_only_successor(
    session: Session,
    binding: dict[str, Any],
    *,
    current: PageCompositionRevision,
) -> None:
    previous = session.get(
        PageCompositionRevision,
        binding["current_composition"]["history_revision_id"],
    )
    if previous is None:
        raise PublicCopyReconciliationError(
            "Prior Page Composition revision disappeared during reconciliation."
        )
    expected_snapshot = deepcopy(previous.source_snapshot)
    expected_snapshot["draft_hash"] = binding["expected_new_content_hash"]
    expected_snapshot["generated_page_updated_at"] = current.source_snapshot.get(
        "generated_page_updated_at"
    )
    expected_snapshot["public_destination_copy"] = deepcopy(
        binding["expected_draft_content"]["public_destination_copy"]
    )
    if current.source_snapshot != expected_snapshot:
        raise PublicCopyReconciliationError(
            "Page Composition successor contains a non-copy authoritative-source change."
        )

    expected_components = deepcopy(previous.generated_components)
    destination_component_count = 0
    for component in expected_components:
        if component.get("component_key") not in {
            "related_page_links",
            "destination_cards",
        }:
            continue
        destination_component_count += 1
        bindings = component.setdefault("input_bindings", {})
        bindings["public_destination_copy"] = deepcopy(
            binding["expected_draft_content"]["public_destination_copy"]
        )
        bindings["public_copy_ruleset"] = {
            "key": PUBLIC_COPY_RULESET_KEY,
            "version": PUBLIC_COPY_RULESET_VERSION,
            "identity": PUBLIC_COPY_RULESET_IDENTITY,
            "hash": PUBLIC_COPY_RULESET_HASH,
        }
    if destination_component_count != 1:
        raise PublicCopyReconciliationError(
            "Page Composition predecessor does not contain one exact related-destination component."
        )
    if current.generated_components != expected_components:
        raise PublicCopyReconciliationError(
            "Page Composition successor changes a non-copy component or binding."
        )
    if current.operator_decisions != previous.operator_decisions:
        raise PublicCopyReconciliationError(
            "Page Composition successor changes operator decisions."
        )


def _assert_prior_evidence_preserved(
    session: Session,
    binding: dict[str, Any],
    *,
    new_qa_id: int,
    expected_predecessor_snapshot: dict[str, Any] | None = None,
) -> None:
    prior_composition = session.get(
        PageCompositionRevision,
        binding["current_composition"]["history_revision_id"],
    )
    if (
        prior_composition is None
        or prior_composition.page_composition_id
        != binding["current_composition"]["id"]
        or prior_composition.composition_version
        != binding["current_composition"]["version"]
        or prior_composition.source_hash
        != binding["current_composition"]["source_hash"]
        or prior_composition.revision_hash
        != binding["current_composition"]["history_revision_hash"]
        or canonical_model_row_sha256(
            PageCompositionRevision,
            prior_composition.model_dump(mode="json"),
        )
        != binding["current_composition"]["history_revision_row_sha256"]
        or prior_composition.content_hash
        != binding["current_composition"]["content_hash"]
    ):
        raise PublicCopyReconciliationError(
            "Prior immutable Page Composition revision evidence was not preserved exactly."
        )
    if (
        expected_predecessor_snapshot is not None
        and _row_snapshot(prior_composition)
        != expected_predecessor_snapshot["composition_revision_snapshot"]
    ):
        raise PublicCopyReconciliationError(
            "Prior Page Composition revision changed outside its immutable identity."
        )
    prior_page_revision_id = binding["current_revision"]["latest_page_revision_id"]
    if prior_page_revision_id is not None:
        prior_page_revision = session.get(
            GeneratedPageRevision,
            prior_page_revision_id,
        )
        if (
            prior_page_revision is None
            or prior_page_revision.draft_hash_after
            != binding["current_revision"]["latest_page_revision_hash_after"]
            or canonical_model_row_sha256(
                GeneratedPageRevision,
                prior_page_revision.model_dump(mode="json"),
            )
            != binding["current_revision"].get(
                "latest_page_revision_row_sha256"
            )
        ):
            raise PublicCopyReconciliationError(
                "Prior Generated Page revision evidence was not preserved exactly."
            )
        if (
            expected_predecessor_snapshot is not None
            and _row_snapshot(prior_page_revision)
            != expected_predecessor_snapshot["page_revision_snapshot"]
        ):
            raise PublicCopyReconciliationError(
                "Prior Generated Page revision changed after preflight."
            )
    prior_qa = session.get(GeneratedPageQAResult, binding["current_qa"]["id"])
    if (
        prior_qa is None
        or prior_qa.id == new_qa_id
        or prior_qa.lifecycle_status != "superseded"
        or prior_qa.result_hash != binding["current_qa"]["result_hash"]
        or prior_qa.source_hash != binding["current_qa"]["source_hash"]
        or prior_qa.qa_ruleset_hash != binding["current_qa"]["ruleset_hash"]
        or prior_qa.page_composition_id != binding["current_composition"]["id"]
        or prior_qa.composition_version
        != binding["current_composition"]["version"]
        or prior_qa.composition_source_hash
        != binding["current_composition"]["source_hash"]
        or _qa_preserved_evidence_hash(prior_qa)
        != binding["current_qa"]["preserved_evidence_sha256"]
    ):
        raise PublicCopyReconciliationError(
            f"Prior QA {binding['current_qa']['id']} evidence was not preserved exactly."
        )
    if qa_result_record_hash(prior_qa.model_dump(mode="python")) != prior_qa.result_hash:
        raise PublicCopyReconciliationError(
            f"Prior QA {binding['current_qa']['id']} result hash no longer matches its evidence."
        )
    new_qa = session.get(GeneratedPageQAResult, new_qa_id)
    if (
        new_qa is None
        or new_qa.supersedes_qa_result_id != prior_qa.id
        or not _same_instant(prior_qa.updated_at, new_qa.evaluated_at)
    ):
        raise PublicCopyReconciliationError(
            f"Prior QA {binding['current_qa']['id']} lifecycle timestamp is not "
            "bound to its exact successor."
        )
    if expected_predecessor_snapshot is not None:
        expected_prior_qa = deepcopy(
            expected_predecessor_snapshot["qa_snapshot"]
        )
        expected_prior_qa["lifecycle_status"] = "superseded"
        expected_prior_qa["updated_at"] = _row_snapshot(new_qa)["evaluated_at"]
        if _row_snapshot(prior_qa) != expected_prior_qa:
            raise PublicCopyReconciliationError(
                f"Prior QA {binding['current_qa']['id']} changed outside its lifecycle transition."
            )


def _row_snapshot(row: Any | None) -> dict[str, Any] | None:
    return row.model_dump(mode="json") if row is not None else None


def _generated_page_preserved_state_hash(page: GeneratedPage) -> str:
    values = page.model_dump(mode="json")
    return canonical_model_row_sha256(
        GeneratedPage,
        {field: values.get(field) for field in _GENERATED_PAGE_PRESERVED_FIELDS},
    )


def _qa_preserved_evidence_hash(row: GeneratedPageQAResult) -> str:
    values = canonicalize_model_row_timestamps(
        GeneratedPageQAResult,
        row.model_dump(mode="json"),
    )
    values.pop("lifecycle_status", None)
    values.pop("updated_at", None)
    return canonical_json_sha256(values)


def _audit_draft_scope(
    *,
    bindings: list[dict[str, Any]],
    drafts_by_planned: dict[int, dict[str, Any]],
    manifest: dict[str, Any],
    ruleset: dict[str, Any],
    compositions_by_planned: dict[int, Any] | None = None,
    allowed_identity_terms_by_planned_path: (
        dict[int, dict[str, tuple[str, ...]]] | None
    ) = None,
) -> PublicCopyAuditBatchResult:
    site_terms, allowed_by_planned = _audit_identity_terms(manifest)
    values: list[PublicCopyAuditInput] = []
    for binding in bindings:
        planned_id = int(binding["planned_page_id"])
        generated_id = int(binding["generated_page_id"])
        draft = drafts_by_planned.get(planned_id)
        if draft is None:
            raise PublicCopyReconciliationError(
                f"Public-copy audit lacks Planned Page {planned_id}."
            )
        composition = (
            compositions_by_planned.get(planned_id)
            if compositions_by_planned is not None
            else None
        )
        if hasattr(composition, "model_dump"):
            composition = composition.model_dump(mode="json")
        values.append(
            PublicCopyAuditInput(
                website_id=int(binding["website_id"]),
                site_identity_terms=tuple(site_terms),
                allowed_identity_terms=tuple(
                    sorted(allowed_by_planned.get(planned_id, set()))
                ),
                allowed_navigation_identity_terms_by_path=(
                    allowed_identity_terms_by_planned_path.get(planned_id, {})
                    if allowed_identity_terms_by_planned_path is not None
                    else {}
                ),
                planned_page_id=planned_id,
                generated_page_id=generated_id,
                page_type=str(binding["page_type"]),
                draft_content=draft,
                composition=composition,
                ruleset_key=str(ruleset["key"]),
                ruleset_version=str(ruleset["version"]),
                ruleset_identity=str(ruleset["identity"]),
                ruleset_canonical_payload_sha256=str(
                    ruleset["seal"]["canonical_payload_sha256"]
                ),
            )
        )
    result = audit_public_copy_pages(values)
    if result.evaluated_page_count != len(bindings):
        raise PublicCopyReconciliationError(
            "Public-copy audit did not evaluate the complete sealed page scope."
        )
    repair_findings = [
        finding
        for page in result.results
        for finding in page.findings
        if finding.severity == "BLOCKER"
        or finding.safe_correction_status == "source_repair_required"
    ]
    if repair_findings:
        first = repair_findings[0]
        raise PublicCopyReconciliationError(
            "Public-copy audit rejected the candidate scope at "
            f"Generated Page {first.generated_page_id} {first.field_path}: "
            f"{first.rule_id} {first.message}"
        )
    return result


def _audit_current_scope(
    session: Session,
    *,
    bindings: list[dict[str, Any]],
    manifest: dict[str, Any],
    ruleset: dict[str, Any],
    navigation_identity_bindings: tuple[
        _GovernedNavigationSetBinding, ...
    ],
) -> PublicCopyAuditBatchResult:
    drafts: dict[int, dict[str, Any]] = {}
    compositions: dict[int, Any] = {}
    allowed_by_planned_path: dict[int, dict[str, tuple[str, ...]]] = {}
    for binding in bindings:
        planned_id = int(binding["planned_page_id"])
        generated_id = int(binding["generated_page_id"])
        generated = session.get(GeneratedPage, generated_id)
        if generated is None:
            raise PublicCopyReconciliationError(
                f"Generated Page {generated_id} disappeared before public-copy audit."
            )
        drafts[planned_id] = generated.draft_content or {}
        composition = read_composition_for_generated_page(
            session,
            generated_id,
        )
        compositions[planned_id] = composition
        allowed_by_planned_path[planned_id] = (
            _navigation_identity_terms_by_composition_path(
                composition=composition,
                navigation_identity_bindings=navigation_identity_bindings,
            )
        )
    return _audit_draft_scope(
        bindings=bindings,
        drafts_by_planned=drafts,
        manifest=manifest,
        ruleset=ruleset,
        compositions_by_planned=compositions,
        allowed_identity_terms_by_planned_path=allowed_by_planned_path,
    )


def _navigation_identity_terms_by_composition_path(
    *,
    composition: Any,
    navigation_identity_bindings: tuple[
        _GovernedNavigationSetBinding, ...
    ],
) -> dict[str, tuple[str, ...]]:
    payload = (
        composition.model_dump(mode="json")
        if hasattr(composition, "model_dump")
        else composition
    )
    if not isinstance(payload, dict):
        raise PublicCopyReconciliationError(
            "Current composition cannot bind governed navigation identity paths."
        )
    components = payload.get("effective_components")
    generated_components = payload.get("generated_components")
    operator_decisions = payload.get("operator_decisions")
    if (
        not isinstance(components, list)
        or not isinstance(generated_components, list)
        or not isinstance(operator_decisions, list)
    ):
        raise PublicCopyReconciliationError(
            "Current composition lacks its generated, decision, or effective component inventory."
        )
    expected_by_set = {
        binding.navigation_set_id: binding
        for binding in navigation_identity_bindings
    }
    if len(expected_by_set) != len(navigation_identity_bindings):
        raise PublicCopyReconciliationError(
            "Locked Navigation Set binding inventory contains a duplicate identity."
        )
    navigation_component_keys = {
        "primary_navigation",
        "utility_navigation",
        "footer_navigation",
    }
    generated_by_set: dict[int, dict[str, Any]] = {}
    for generated in generated_components:
        if not isinstance(generated, dict):
            continue
        component_key = generated.get("component_key")
        if component_key not in navigation_component_keys:
            continue
        source_bindings = generated.get("input_bindings")
        if not isinstance(source_bindings, dict):
            raise PublicCopyReconciliationError(
                "Generated navigation component lacks its source binding."
            )
        navigation_set_id = source_bindings.get("navigation_set_id")
        governed_set = expected_by_set.get(navigation_set_id)
        if (
            isinstance(navigation_set_id, bool)
            or not isinstance(navigation_set_id, int)
            or governed_set is None
            or navigation_set_id in generated_by_set
            or source_bindings != {"navigation_set_id": navigation_set_id}
            or component_key != f"{governed_set.set_type}_navigation"
            or not isinstance(generated.get("instance_key"), str)
            or not generated["instance_key"]
        ):
            raise PublicCopyReconciliationError(
                "Generated navigation component differs from its exact locked Navigation Set binding."
            )
        generated_by_set[navigation_set_id] = generated
    if set(generated_by_set) != set(expected_by_set):
        raise PublicCopyReconciliationError(
            "Generated navigation component inventory differs from the locked Navigation Set scope."
        )
    decisions_by_instance: dict[str, dict[str, Any]] = {}
    for decision in operator_decisions:
        if not isinstance(decision, dict):
            raise PublicCopyReconciliationError(
                "Current composition contains a malformed operator decision."
            )
        instance_key = decision.get("instance_key")
        if not isinstance(instance_key, str):
            raise PublicCopyReconciliationError(
                "Current composition contains an operator decision without an exact instance."
            )
        if instance_key in decisions_by_instance:
            raise PublicCopyReconciliationError(
                "Current composition contains duplicate operator decisions."
            )
        decisions_by_instance[instance_key] = decision
    suppressed_set_ids: set[int] = set()
    for navigation_set_id, generated in generated_by_set.items():
        decision = decisions_by_instance.get(str(generated["instance_key"]))
        if decision is None or decision.get("action") != "suppress":
            continue
        if expected_by_set[navigation_set_id].set_type == "primary":
            raise PublicCopyReconciliationError(
                "Primary Navigation cannot be absent through an operator suppression."
            )
        suppressed_set_ids.add(navigation_set_id)
    result: dict[str, tuple[str, ...]] = {}
    observed_navigation_sets: set[int] = set()
    for component_index, component in enumerate(components):
        if not isinstance(component, dict):
            continue
        component_key = component.get("component_key")
        if component_key not in navigation_component_keys:
            continue
        bindings = component.get("input_bindings")
        resolved = component.get("resolved_data")
        if not isinstance(bindings, dict) or not isinstance(resolved, dict):
            raise PublicCopyReconciliationError(
                "Navigation component lacks exact source bindings or resolved data."
            )
        navigation_set_id = bindings.get("navigation_set_id")
        if (
            isinstance(navigation_set_id, bool)
            or not isinstance(navigation_set_id, int)
            or navigation_set_id <= 0
            or navigation_set_id in observed_navigation_sets
            or navigation_set_id not in expected_by_set
            or navigation_set_id in suppressed_set_ids
        ):
            raise PublicCopyReconciliationError(
                "Navigation component references an unknown or duplicate locked Navigation Set."
            )
        governed_set = expected_by_set[navigation_set_id]
        if component_key != f"{governed_set.set_type}_navigation":
            raise PublicCopyReconciliationError(
                "Navigation component type differs from its exact locked Navigation Set type."
            )
        if bindings != {"navigation_set_id": navigation_set_id}:
            raise PublicCopyReconciliationError(
                "Navigation component source binding differs from its exact locked form."
            )
        if set(resolved) != {"label", "items"} or resolved.get(
            "label"
        ) != governed_set.label:
            raise PublicCopyReconciliationError(
                "Navigation component label or resolved-data shape differs from its locked source."
            )
        items = resolved.get("items")
        if not isinstance(items, list) or len(items) != len(governed_set.items):
            raise PublicCopyReconciliationError(
                "Navigation component lacks its exact resolved item inventory."
            )
        for item_index, (item, governed_item) in enumerate(
            zip(items, governed_set.items, strict=True)
        ):
            if not isinstance(item, dict):
                raise PublicCopyReconciliationError(
                    "Navigation component contains a malformed resolved item."
                )
            expected_item = {
                "navigation_item_id": governed_item.navigation_item_id,
                "target_planned_page_id": governed_item.target_planned_page_id,
                "target_generated_page_id": governed_item.target_generated_page_id,
                "label": governed_item.label,
                "slug": governed_item.target_slug,
                "parent_navigation_item_id": (
                    governed_item.parent_navigation_item_id
                ),
                "position": governed_item.position,
                "status": governed_item.status,
            }
            if item != expected_item or any(
                type(item[key]) is not type(expected)
                for key, expected in expected_item.items()
            ):
                raise PublicCopyReconciliationError(
                    "Navigation component item differs from its exact ordered locked source binding."
                )
            path = (
                f"composition.effective_components[{component_index}]"
                f".resolved_data.items[{item_index}].label"
            )
            if governed_item.identity_terms:
                result[path] = governed_item.identity_terms
        observed_navigation_sets.add(navigation_set_id)
    if observed_navigation_sets != set(expected_by_set) - suppressed_set_ids:
        raise PublicCopyReconciliationError(
            "Current composition navigation-set inventory differs from the locked source scope."
        )
    return result


def _audit_identity_terms(
    manifest: dict[str, Any],
) -> tuple[list[str], dict[int, set[str]]]:
    identity_fact_names = {"city.city_name", "county.county_name"}
    site_terms: set[str] = set()
    allowed: dict[int, set[str]] = {
        int(binding["planned_page_id"]): set()
        for binding in manifest.get("page_bindings", [])
    }
    business = manifest.get("governed_fact_snapshot", {}).get("business", {})
    if isinstance(business, dict):
        main_city = business.get("main_city")
        if isinstance(main_city, str) and main_city.strip():
            for values in allowed.values():
                values.add(main_city.strip())
    for correction in manifest.get("corrections", []):
        if not isinstance(correction, dict):
            continue
        facts = correction.get("governed_facts_used")
        if not isinstance(facts, list):
            continue
        correction_terms = {
            str(item.get("value")).strip()
            for item in facts
            if isinstance(item, dict)
            and item.get("fact") in identity_fact_names
            and isinstance(item.get("value"), str)
            and str(item.get("value")).strip()
        }
        site_terms.update(correction_terms)
        source_id = correction.get("planned_page_id")
        if isinstance(source_id, int) and source_id in allowed:
            allowed[source_id].update(correction_terms)
        destination = correction.get("destination_identity")
        if isinstance(destination, dict):
            target_id = destination.get("planned_page_id")
            if isinstance(target_id, int) and target_id in allowed:
                allowed[target_id].update(correction_terms)
    return sorted(site_terms), allowed


def _assert_operator_intents_exact(
    session: Session,
    manifest: dict[str, Any],
    *,
    rows: list[InternalLinkIntent] | None = None,
) -> None:
    contract = manifest["operator_intent_preservation"]
    if rows is None:
        rows = list(
            session.exec(
                select(InternalLinkIntent)
                .where(
                    InternalLinkIntent.site_plan_id
                    == manifest["scope"]["site_plan_id"]
                )
                .order_by(InternalLinkIntent.id)
            ).all()
        )
    if len(rows) != contract["row_count"]:
        raise PublicCopyReconciliationError(
            "Operator InternalLinkIntent row count changed."
        )
    fields = (
        "id",
        "website_id",
        "site_plan_id",
        "source_planned_page_id",
        "target_planned_page_id",
        "relationship_type",
        "purpose",
        "anchor_guidance",
        "rationale",
        "decision_version",
        "source_suggestion_key",
        "approval_state",
        "decided_by",
        "decided_at",
        "created_at",
        "updated_at",
    )
    snapshot = []
    for row in rows:
        dumped = row.model_dump(mode="json")
        snapshot.append({field: dumped.get(field) for field in fields})
    if canonical_model_rows_sha256(
        InternalLinkIntent,
        snapshot,
    ) != contract["canonical_snapshot_sha256"]:
        raise PublicCopyReconciliationError(
            "Operator InternalLinkIntent content or provenance changed."
        )
