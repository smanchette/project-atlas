from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import (
    GeneratedPage,
    GeneratedPageQAResult,
    ImageMetadata,
    PageComposition,
    PlannedPage,
    SitePlan,
    Theme,
    ThemeConfigurationAudit,
    ThemeFamily,
    ThemeFamilyVersion,
    Website,
    WebsiteThemeComponentConfiguration,
    WebsiteThemeConfiguration,
    WebsiteThemeSelection,
)
from app.schemas.theme_families import (
    FormReadinessItemRead,
    PerformanceLocalFullSiteAuditRead,
    PerformanceLocalFullSitePageRead,
    ThemeActivationComponentRevisionRead,
    ThemeActivationMutationRead,
    ThemeActivationPlanRead,
    ThemeActivationRehearsalCreate,
    ThemeActivationRehearsalRead,
    ThemeActivationRehearsalRollbackCreate,
)
from app.services import page_composition as composition_service
from app.services import theme_configurations as theme_service
from app.services import themes as theme_runtime
from app.services.form_submission_gateway import (
    disposable_rehearsal_environment_allowed,
    evaluate_form_readiness,
    is_explicit_disposable_database_name,
)
from app.services.page_qa import save_page_qa
from app.services.page_composition_history import (
    PageCompositionHistoryError,
    current_composition_revision,
)
from app.services.theme_delivery import (
    ThemeDeliveryError,
    read_performance_local_rehearsal_delivery,
)


_EXPECTED_CONVERSION_COMPONENT_KEYS = frozenset(
    {"campaign_banner", "sticky_mobile_action_bar", "compact_estimate_form"}
)


class ThemeActivationRehearsalError(ValueError):
    """Fail-closed error for read-only planning and disposable rehearsal writes."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 409,
        code: str = "theme_activation_rehearsal_blocked",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def plan_theme_activation_rehearsal(
    session: Session,
    website_id: int,
    configuration_id: int,
) -> ThemeActivationPlanRead:
    """Calculate the exact future mutation without issuing or staging a write."""

    pending_before = _session_pending_identity(session)
    with session.no_autoflush:
        website, configuration, version, family, components = _draft_graph(
            session,
            website_id,
            configuration_id,
        )
        selection, current_theme = _sole_active_selection(session, website)
        compositions = list(
            session.exec(
                select(PageComposition)
                .where(PageComposition.website_id == website.id)
                .order_by(PageComposition.id)
            ).all()
        )
        generated_ids = [item.generated_page_id for item in compositions]
        current_qa = (
            list(
                session.exec(
                    select(GeneratedPageQAResult).where(
                        GeneratedPageQAResult.generated_page_id.in_(generated_ids),
                        GeneratedPageQAResult.lifecycle_status == "current",
                    )
                ).all()
            )
            if generated_ids
            else []
        )
        form = next(
            item
            for item in components
            if item.component_key == "compact_estimate_form"
        )
        # Planning describes the target disposable runtime. It does not make the
        # active-local runtime pretend that the test provider is currently usable.
        readiness = evaluate_form_readiness(
            form,
            mode="activation_rehearsal",
            test_environment_allowed=True,
        )
        form_blockers = list(readiness.blockers)
        privacy_blockers = [
            item
            for item in form_blockers
            if item.field.startswith(("privacy.", "retention.", "spam."))
        ]
        publication_blockers = _publication_blockers()
        incomplete_compositions = _composition_plan_blockers(
            session,
            website=website,
            compositions=compositions,
        )
        publication_blockers.extend(incomplete_compositions)

        component_ids = [_id(item) for item in components]
        composition_ids = [_id(item) for item in compositions]
        mutation_ledger = _planned_mutation_ledger(
            website_id=_id(website),
            configuration_id=_id(configuration),
            current_theme_id=_id(current_theme),
            current_selection_id=_id(selection),
            component_ids=component_ids,
            composition_ids=composition_ids,
            generated_page_ids=generated_ids,
        )
        audit_events = [
            "website_configuration_approved",
            "website_configuration_activated",
            *[f"component_activated:{item_id}" for item_id in component_ids],
            *[f"component_rolled_back:{item_id}" for item_id in component_ids],
            "website_configuration_rolled_back",
        ]

        result = ThemeActivationPlanRead(
            website_id=_id(website),
            current_theme_id=_id(current_theme),
            current_selection_id=_id(selection),
            target_theme_family_id=_id(family),
            target_theme_family_version_id=_id(version),
            target_configuration_id=_id(configuration),
            component_configuration_ids=component_ids,
            component_revision_graph=_component_revision_graph(components),
            affected_composition_ids=composition_ids,
            expected_qa_invalidation_count=len(current_qa),
            expected_refresh_count=len(compositions),
            expected_export_state=(
                "internal_rehearsal_only"
                if readiness.can_submit and not incomplete_compositions
                else "blocked"
            ),
            form_blockers=form_blockers,
            privacy_blockers=privacy_blockers,
            publication_blockers=publication_blockers,
            rollback_theme_id=_id(current_theme),
            rollback_selection_id=_id(selection),
            backup_requirements=[
                "Verified Atlas Data backup of the exact pre-rehearsal source database",
                "Verified PostgreSQL custom-format dump of the exact pre-rehearsal source database",
                "Protected-media fingerprint captured before cloning",
                "Exact prior Theme and Website selection identity captured in the activation audit",
                "Disposable-database identity and drop verification recorded after rollback",
            ],
            mutation_ledger=mutation_ledger,
            audit_events=audit_events,
            write_count=0,
        )

    if _session_pending_identity(session) != pending_before:
        raise ThemeActivationRehearsalError(
            "Activation planning attempted to stage a database mutation.",
            code="activation_plan_write_detected",
        )
    return result


def activate_theme_configuration_rehearsal(
    session: Session,
    website_id: int,
    configuration_id: int,
    payload: ThemeActivationRehearsalCreate,
) -> ThemeActivationRehearsalRead:
    """Atomically materialize V3 only in a guarded disposable database."""

    _require_disposable_runtime(session)
    plan = plan_theme_activation_rehearsal(session, website_id, configuration_id)
    if plan.form_blockers:
        raise ThemeActivationRehearsalError(
            "The provider-disabled or incomplete form graph cannot be activated.",
            code="rehearsal_form_readiness_blocked",
        )
    if plan.expected_export_state != "internal_rehearsal_only":
        raise ThemeActivationRehearsalError(
            "The target graph is not ready for an internal activation rehearsal.",
            code="rehearsal_graph_not_ready",
        )
    if plan.current_selection_id != payload.expected_current_selection_id:
        raise ThemeActivationRehearsalError(
            "The active Website Theme selection changed after planning.",
            code="rehearsal_selection_precondition_failed",
        )

    try:
        website, configuration, version, family, components = _locked_draft_graph(
            session,
            website_id,
            configuration_id,
        )
        if configuration.integrity_fingerprint != payload.expected_configuration_fingerprint:
            raise ThemeActivationRehearsalError(
                "The Website Theme configuration changed after planning.",
                code="rehearsal_configuration_precondition_failed",
            )
        if (
            [_id(item) for item in components] != plan.component_configuration_ids
            or _component_revision_graph(components) != plan.component_revision_graph
        ):
            raise ThemeActivationRehearsalError(
                "The component revision graph changed after planning.",
                code="rehearsal_component_graph_precondition_failed",
            )
        prior_selection, prior_theme = _sole_active_selection(
            session,
            website,
            lock=True,
        )
        if _id(prior_selection) != payload.expected_current_selection_id:
            raise ThemeActivationRehearsalError(
                "The active Website Theme selection changed after planning.",
                code="rehearsal_selection_precondition_failed",
            )

        version_identity = (
            version.lifecycle_status,
            version.production_ready,
            version.integrity_fingerprint,
        )
        transitioned_at = _utc_now()
        prior_selection_snapshot = _selection_snapshot(prior_selection)
        configuration_snapshot = _configuration_snapshot(configuration)
        component_snapshots = {
            str(_id(item)): _component_snapshot(item) for item in components
        }

        rehearsal_theme = _create_rehearsal_theme(
            session,
            website=website,
            family=family,
            source_theme=prior_theme,
            actor=payload.actor,
            transitioned_at=transitioned_at,
        )
        rehearsal_selection = _replace_active_selection(
            session,
            website=website,
            prior_selection=prior_selection,
            rehearsal_theme=rehearsal_theme,
            actor=payload.actor,
            transitioned_at=transitioned_at,
        )

        configuration.lifecycle_status = "approved"
        configuration.approved_by = payload.actor
        configuration.approved_at = transitioned_at
        configuration.updated_by = payload.actor
        configuration.updated_at = transitioned_at
        configuration.integrity_fingerprint = (
            theme_service._website_configuration_fingerprint_from_record(configuration)
        )
        session.add(configuration)
        activation_audits: list[ThemeConfigurationAudit] = []
        activation_audits.append(theme_service._append_audit(
            session,
            action_type="website_configuration_approved",
            actor=payload.actor,
            rationale="Approve the exact disposable Performance Local V3 rehearsal graph.",
            snapshot=theme_service._website_configuration_fingerprint_payload(
                configuration
            ),
            website_theme_configuration_id=_id(configuration),
        ))

        configuration.lifecycle_status = "active"
        configuration.activated_by = payload.actor
        configuration.activated_at = transitioned_at
        configuration.materialized_theme_id = _id(rehearsal_theme)
        configuration.website_theme_selection_id = _id(rehearsal_selection)
        configuration.integrity_fingerprint = (
            theme_service._website_configuration_fingerprint_from_record(configuration)
        )
        session.add(configuration)
        activation_audits.append(theme_service._append_audit(
            session,
            action_type="website_configuration_activated",
            actor=payload.actor,
            rationale="Activate Performance Local V3 in the guarded disposable rehearsal only.",
            snapshot={
                **theme_service._website_configuration_fingerprint_payload(
                    configuration
                ),
                "rehearsal_state": {
                    "prior_selection": prior_selection_snapshot,
                    "configuration_before": configuration_snapshot,
                    "components_before": component_snapshots,
                    "rehearsal_theme_id": _id(rehearsal_theme),
                    "rehearsal_selection_id": _id(rehearsal_selection),
                    "theme_family_version_lifecycle_status": version.lifecycle_status,
                    "theme_family_version_production_ready": version.production_ready,
                },
            },
            website_theme_configuration_id=_id(configuration),
        ))

        for component in components:
            component.activation_identity = payload.actor
            component.activated_at = transitioned_at
            component.updated_at = transitioned_at
            component.integrity_fingerprint = (
                theme_service._component_fingerprint_from_record(component)
            )
            session.add(component)
            activation_audits.append(theme_service._append_audit(
                session,
                action_type="component_activated",
                actor=payload.actor,
                rationale="Activate this exact component revision in the disposable rehearsal.",
                snapshot=theme_service._component_fingerprint_payload(component),
                component_configuration_id=_id(component),
            ))

        session.flush()
        if version_identity != (
            version.lifecycle_status,
            version.production_ready,
            version.integrity_fingerprint,
        ):
            raise ThemeActivationRehearsalError(
                "The rehearsal attempted to change the immutable V3 preview-candidate identity.",
                code="rehearsal_version_mutation_detected",
            )
        _validate_activated_graph(
            session,
            configuration=configuration,
            version=version,
            family=family,
            components=components,
        )
        _refresh_stale_compositions_and_qa(
            session,
            website=website,
            expected_composition_ids=set(plan.affected_composition_ids),
        )
        active_count = _active_selection_count(session, _id(website))
        v3_active_count = _selection_match_count(
            session,
            website_id=_id(website),
            theme_id=_id(rehearsal_theme),
            status="active",
        )
        if active_count != 1 or v3_active_count != 1:
            raise ThemeActivationRehearsalError(
                "Disposable activation did not produce one exact active V3 selection.",
                code="rehearsal_selection_invariant_failed",
            )
        generated_page_ids = _generated_page_ids_for_compositions(
            session,
            plan.affected_composition_ids,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return ThemeActivationRehearsalRead(
        status="activated",
        website_id=website_id,
        configuration_id=configuration_id,
        prior_theme_id=_id(prior_theme),
        prior_selection_id=_id(prior_selection),
        rehearsal_theme_id=_id(rehearsal_theme),
        rehearsal_selection_id=_id(rehearsal_selection),
        active_selection_count=active_count,
        v3_active_selection_count=v3_active_count,
        mutation_ledger=_actual_activation_ledger(
            configuration=configuration,
            components=components,
            prior_selection=prior_selection,
            rehearsal_theme=rehearsal_theme,
            rehearsal_selection=rehearsal_selection,
            composition_ids=plan.affected_composition_ids,
            generated_page_ids=generated_page_ids,
            audits=activation_audits,
        ),
        audit_event_types=[
            "website_configuration_approved",
            "website_configuration_activated",
            *["component_activated" for _item in components],
        ],
    )


def rollback_theme_configuration_rehearsal(
    session: Session,
    website_id: int,
    configuration_id: int,
    payload: ThemeActivationRehearsalRollbackCreate,
) -> ThemeActivationRehearsalRead:
    """Roll back the disposable materialization to its exact prior selection."""

    _require_disposable_runtime(session)
    try:
        configuration = _locked_configuration(session, configuration_id)
        if configuration.website_id != website_id:
            raise ThemeActivationRehearsalError(
                "The rollback configuration crosses the Website boundary.",
                code="rehearsal_scope_mismatch",
            )
        if configuration.integrity_fingerprint != payload.expected_configuration_fingerprint:
            raise ThemeActivationRehearsalError(
                "The activated configuration changed before rollback.",
                code="rehearsal_configuration_precondition_failed",
            )
        version = _record(
            session,
            ThemeFamilyVersion,
            configuration.theme_family_version_id,
            "Theme Family Version",
        )
        family = _record(
            session,
            ThemeFamily,
            version.theme_family_id,
            "Theme Family",
        )
        if (
            family.family_key != "performance-local"
            or version.version != 3
            or version.lifecycle_status != "preview_candidate"
            or version.production_ready
            or configuration.lifecycle_status != "active"
            or configuration.materialized_theme_id
            != payload.expected_rehearsal_theme_id
            or configuration.website_theme_selection_id
            != payload.expected_rehearsal_selection_id
        ):
            raise ThemeActivationRehearsalError(
                "The activated disposable V3 identity is not exact.",
                code="rehearsal_activation_identity_mismatch",
            )
        website = _record(session, Website, website_id, "Website")
        prior_selection = _locked_selection(
            session,
            payload.expected_prior_selection_id,
        )
        rehearsal_selection = _locked_selection(
            session,
            payload.expected_rehearsal_selection_id,
        )
        rehearsal_theme = _record(
            session,
            Theme,
            payload.expected_rehearsal_theme_id,
            "Rehearsal Theme",
        )
        prior_theme = _record(
            session,
            Theme,
            prior_selection.theme_id,
            "Prior Theme",
        )
        active = _active_selections(session, website_id, lock=True)
        if (
            len(active) != 1
            or _id(active[0]) != _id(rehearsal_selection)
            or rehearsal_selection.theme_id != _id(rehearsal_theme)
            or prior_selection.website_id != website_id
            or rehearsal_selection.website_id != website_id
        ):
            raise ThemeActivationRehearsalError(
                "The disposable selection graph changed before rollback.",
                code="rehearsal_selection_precondition_failed",
            )
        activation_audit = _activation_state_audit(
            session,
            configuration_id=configuration_id,
            rehearsal_theme_id=_id(rehearsal_theme),
            rehearsal_selection_id=_id(rehearsal_selection),
        )
        rehearsal_state = activation_audit.snapshot["rehearsal_state"]
        expected_prior = rehearsal_state["prior_selection"]
        if int(expected_prior["id"]) != payload.expected_prior_selection_id:
            raise ThemeActivationRehearsalError(
                "The rollback target differs from the captured pre-activation selection.",
                code="rehearsal_rollback_target_mismatch",
            )

        components = _current_components(session, configuration_id, lock=True)
        _validate_activated_graph(
            session,
            configuration=configuration,
            version=version,
            family=family,
            components=components,
        )
        transitioned_at = _utc_now()
        rollback_audits: list[ThemeConfigurationAudit] = []
        for component in components:
            component.rollback_identity = payload.actor
            component.rollback_at = transitioned_at
            component.updated_at = transitioned_at
            component.integrity_fingerprint = (
                theme_service._component_fingerprint_from_record(component)
            )
            rollback_audits.append(theme_service._append_audit(
                session,
                action_type="component_rolled_back",
                actor=payload.actor,
                rationale="Roll back this exact disposable rehearsal component revision.",
                snapshot=theme_service._component_fingerprint_payload(component),
                component_configuration_id=_id(component),
            ))
            _restore_component(
                component,
                rehearsal_state["components_before"][str(_id(component))],
            )
            session.add(component)

        configuration.lifecycle_status = "superseded"
        configuration.rollback_by = payload.actor
        configuration.rollback_at = transitioned_at
        configuration.updated_by = payload.actor
        configuration.updated_at = transitioned_at
        configuration.integrity_fingerprint = (
            theme_service._website_configuration_fingerprint_from_record(configuration)
        )
        rollback_audits.append(theme_service._append_audit(
            session,
            action_type="website_configuration_rolled_back",
            actor=payload.actor,
            rationale="Restore the exact pre-activation Theme and selection in the disposable rehearsal.",
            snapshot=theme_service._website_configuration_fingerprint_payload(
                configuration
            ),
            website_theme_configuration_id=_id(configuration),
        ))
        _restore_configuration(
            configuration,
            rehearsal_state["configuration_before"],
        )
        session.add(configuration)

        rehearsal_selection.status = "replaced"
        rehearsal_selection.replaced_at = transitioned_at
        rehearsal_selection.updated_at = transitioned_at
        session.add(rehearsal_selection)
        # Clear the partial unique active-selection slot before restoring its predecessor.
        session.flush([rehearsal_selection])
        _restore_selection(prior_selection, expected_prior)
        session.add(prior_selection)

        rehearsal_theme.lifecycle_status = "retired"
        rehearsal_theme.retired_by = payload.actor
        rehearsal_theme.retirement_rationale = (
            "Disposable Performance Local V3 activation rehearsal rolled back."
        )
        rehearsal_theme.retired_at = transitioned_at
        rehearsal_theme.updated_at = transitioned_at
        session.add(rehearsal_theme)

        affected = list(
            session.exec(
                select(PageComposition)
                .where(PageComposition.website_id == website_id)
                .order_by(PageComposition.id)
                .with_for_update()
            ).all()
        )
        _require_valid_composition_heads(session, affected, lock=True)
        for composition in affected:
            composition.status = "stale"
            composition.updated_at = transitioned_at
            session.add(composition)
        session.flush()
        _refresh_stale_compositions_and_qa(
            session,
            website=website,
            expected_composition_ids={_id(item) for item in affected},
        )

        active_count = _active_selection_count(session, website_id)
        v3_active_count = _selection_match_count(
            session,
            website_id=website_id,
            theme_id=_id(rehearsal_theme),
            status="active",
        )
        if (
            active_count != 1
            or v3_active_count != 0
            or prior_selection.status != "active"
            or prior_selection.theme_id != _id(prior_theme)
        ):
            raise ThemeActivationRehearsalError(
                "Rollback did not restore the exact prior active selection.",
                code="rehearsal_rollback_invariant_failed",
            )
        theme_service._validate_website_configuration(session, configuration)
        for component in components:
            theme_service._validate_component_configuration(session, component)
        theme_runtime._validate_theme_record(
            session,
            prior_theme,
            require_approved=True,
        )
        generated_page_ids = sorted(item.generated_page_id for item in affected)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return ThemeActivationRehearsalRead(
        status="rolled_back",
        website_id=website_id,
        configuration_id=configuration_id,
        prior_theme_id=_id(prior_theme),
        prior_selection_id=_id(prior_selection),
        rehearsal_theme_id=_id(rehearsal_theme),
        rehearsal_selection_id=_id(rehearsal_selection),
        active_selection_count=active_count,
        v3_active_selection_count=v3_active_count,
        mutation_ledger=_actual_rollback_ledger(
            configuration=configuration,
            components=components,
            prior_selection=prior_selection,
            rehearsal_theme=rehearsal_theme,
            rehearsal_selection=rehearsal_selection,
            composition_ids=[_id(item) for item in affected],
            generated_page_ids=generated_page_ids,
            audits=rollback_audits,
        ),
        audit_event_types=[
            *["component_rolled_back" for _item in components],
            "website_configuration_rolled_back",
        ],
    )


def audit_performance_local_full_site_rehearsal(
    session: Session,
    website_id: int,
    configuration_id: int,
    *,
    expected_page_count: int | None = None,
) -> PerformanceLocalFullSiteAuditRead:
    """Read and type every Page result from the activated disposable renderer."""

    _require_disposable_runtime(session)
    configuration = _record(
        session,
        WebsiteThemeConfiguration,
        configuration_id,
        "Website Theme configuration",
    )
    if configuration.website_id != website_id or configuration.lifecycle_status != "active":
        raise ThemeActivationRehearsalError(
            "Full-site rehearsal requires the exact activated disposable configuration.",
            code="full_site_rehearsal_identity_mismatch",
        )
    active = _active_selections(session, website_id)
    if (
        len(active) != 1
        or configuration.website_theme_selection_id != _id(active[0])
    ):
        raise ThemeActivationRehearsalError(
            "Full-site rehearsal requires one exact active Website selection.",
            code="full_site_selection_invariant_failed",
        )
    planned_pages = list(
        session.exec(
            select(PlannedPage)
            .where(
                PlannedPage.website_id == website_id,
                PlannedPage.generated_page_id.is_not(None),
            )
            .order_by(PlannedPage.generated_page_id)
        ).all()
    )
    if expected_page_count is not None and len(planned_pages) != expected_page_count:
        raise ThemeActivationRehearsalError(
            f"Full-site rehearsal requires exactly {expected_page_count} current Generated Pages; found {len(planned_pages)}.",
            code="full_site_page_count_mismatch",
        )
    rows: list[PerformanceLocalFullSitePageRead] = []
    for planned in planned_pages:
        generated_id = planned.generated_page_id
        if generated_id is None:  # guarded by the query
            continue
        try:
            delivery = read_performance_local_rehearsal_delivery(
                session,
                configuration_id,
                generated_id,
            )
        except ThemeDeliveryError as exc:
            raise ThemeActivationRehearsalError(
                f"Generated Page {generated_id} could not enter the exact rehearsal renderer: {exc}",
                code=exc.code,
            ) from exc

        composition = delivery.composition
        components = delivery.components
        scope_blockers = _delivery_scope_blockers(
            website_id=website_id,
            configuration_id=configuration_id,
            planned_page_id=_id(planned),
            components=components,
        )
        integrity_blockers = list(scope_blockers)
        media_ids = _composition_media_ids(composition)
        (
            wordpress_media_ids,
            local_only_media_ids,
            media_identity_blockers,
        ) = _wordpress_media_evidence(
            session,
            media_ids,
        )
        integrity_blockers.extend(media_identity_blockers)
        media_fallback = _composition_uses_media_fallback(composition)
        if media_fallback:
            integrity_blockers.append(
                "media_fallback|media|A legacy or ungoverned media fallback entered the rehearsal composition."
            )
        missing_required_media = _missing_required_media(composition)
        delivery_blockers = [
            f"{item.code}|{item.category}|{item.reason}" for item in delivery.blockers
        ]
        blockers = _deduplicate_strings([*delivery_blockers, *integrity_blockers])
        required_media_state = (
            "blocked_missing_required_media"
            if missing_required_media
            or any("|media|" in item for item in blockers)
            else "ready"
        )
        form_state = (
            f"{delivery.form_readiness.submission_state}:"
            f"{delivery.form_readiness.status}"
        )
        banner_state = _banner_state(components)
        sticky_state = _sticky_state(components)
        renderer_ready = (
            delivery.renderer_result.status == "ready" and not integrity_blockers
        )
        export_eligible = delivery.export_eligibility.eligible and not integrity_blockers
        qa_status = str(delivery.page.get("qa_status") or "not_run")
        rows.append(
            PerformanceLocalFullSitePageRead(
                generated_page_id=generated_id,
                planned_page_id=_id(planned),
                page_type=planned.page_type,
                theme_family_id=delivery.theme_family.id,
                theme_family_key=delivery.theme_family.family_key,
                theme_version_id=delivery.theme_version.id,
                theme_version=delivery.theme_version.version,
                configuration_id=delivery.website_configuration.id,
                component_graph_identity=theme_service.canonical_json_hash(
                    [
                        {
                            "id": item.id,
                            "instance": item.component_instance_key,
                            "fingerprint": item.integrity_fingerprint,
                            "scope": item.scope_type,
                            "planned_page_id": item.planned_page_id,
                            "destination": item.destination_component_configuration_id,
                        }
                        for item in components
                    ]
                ),
                composition_id=int(composition["id"]),
                composition_version=int(composition["composition_version"]),
                composition_source_hash=str(composition["source_hash"]),
                media_reference_ids=media_ids,
                wordpress_media_reference_ids=wordpress_media_ids,
                local_only_media_reference_ids=local_only_media_ids,
                media_fallback_used=media_fallback,
                scope_integrity="blocked" if scope_blockers else "exact",
                required_media_state=required_media_state,
                form_state=form_state,
                banner_state=banner_state,
                sticky_action_state=sticky_state,
                renderer_result=(
                    delivery.renderer_result.result_code
                    if renderer_ready
                    else "renderer_blocked_by_governed_readiness"
                ),
                export_eligible=export_eligible,
                qa_readiness_result=qa_status,
                blockers=blockers,
            )
        )
    ready_count = sum(
        1
        for item in rows
        if item.renderer_result == "renderer_ready"
        and item.export_eligible
        and item.required_media_state == "ready"
        and item.qa_readiness_result == "ready"
        and not item.blockers
    )
    return PerformanceLocalFullSiteAuditRead(
        website_id=website_id,
        evaluated_page_count=len(rows),
        ready_count=ready_count,
        blocked_count=len(rows) - ready_count,
        pages=rows,
    )


def _draft_graph(
    session: Session,
    website_id: int,
    configuration_id: int,
) -> tuple[
    Website,
    WebsiteThemeConfiguration,
    ThemeFamilyVersion,
    ThemeFamily,
    list[WebsiteThemeComponentConfiguration],
]:
    website = _record(session, Website, website_id, "Website")
    configuration = _record(
        session,
        WebsiteThemeConfiguration,
        configuration_id,
        "Website Theme configuration",
    )
    if configuration.website_id != website_id:
        raise ThemeActivationRehearsalError(
            "The target configuration crosses the Website boundary.",
            code="rehearsal_scope_mismatch",
        )
    version = _record(
        session,
        ThemeFamilyVersion,
        configuration.theme_family_version_id,
        "Theme Family Version",
    )
    family = _record(
        session,
        ThemeFamily,
        version.theme_family_id,
        "Theme Family",
    )
    try:
        theme_service._validate_family(family)
        theme_service._validate_family_version(session, version)
        theme_service._validate_website_configuration(session, configuration)
    except theme_service.ThemeConfigurationError as exc:
        raise ThemeActivationRehearsalError(str(exc)) from exc
    if (
        family.family_key != "performance-local"
        or family.lifecycle_status != "registered"
        or version.version != 3
        or version.lifecycle_status != "preview_candidate"
        or version.production_ready
        or configuration.lifecycle_status != "draft"
        or configuration.materialized_theme_id is not None
        or configuration.website_theme_selection_id is not None
    ):
        raise ThemeActivationRehearsalError(
            "Planning requires the exact inactive Performance Local V3 preview candidate.",
            code="rehearsal_draft_identity_mismatch",
        )
    components = _current_components(session, configuration_id)
    if (
        len(components) != len(_EXPECTED_CONVERSION_COMPONENT_KEYS)
        or {item.component_key for item in components}
        != _EXPECTED_CONVERSION_COMPONENT_KEYS
        or any(
            item.scope_type != "website_default" or item.planned_page_id is not None
            for item in components
        )
    ):
        raise ThemeActivationRehearsalError(
            "The V3 rehearsal requires the exact three-node Website-default conversion graph.",
            code="rehearsal_component_graph_mismatch",
        )
    try:
        for component in components:
            theme_service._validate_component_configuration(session, component)
        theme_service._validate_preview_components(session, configuration, components)
    except theme_service.ThemeConfigurationError as exc:
        raise ThemeActivationRehearsalError(str(exc)) from exc
    return website, configuration, version, family, components


def _locked_draft_graph(
    session: Session,
    website_id: int,
    configuration_id: int,
):
    _locked_configuration(session, configuration_id)
    _current_components(session, configuration_id, lock=True)
    return _draft_graph(session, website_id, configuration_id)


def _validate_activated_graph(
    session: Session,
    *,
    configuration: WebsiteThemeConfiguration,
    version: ThemeFamilyVersion,
    family: ThemeFamily,
    components: list[WebsiteThemeComponentConfiguration],
) -> None:
    from app.services import theme_delivery as delivery_service

    try:
        delivery_service._validate_activated_rehearsal_configuration(
            session,
            configuration=configuration,
            version=version,
            family=family,
        )
        for component in components:
            delivery_service._validate_activated_rehearsal_component(
                session,
                configuration=configuration,
                component=component,
            )
        theme_service._require_audit_coverage(
            session,
            families=[family],
            versions=[version],
            configurations=[configuration],
            components=components,
        )
    except (ThemeDeliveryError, theme_service.ThemeConfigurationError) as exc:
        raise ThemeActivationRehearsalError(str(exc)) from exc


def _create_rehearsal_theme(
    session: Session,
    *,
    website: Website,
    family: ThemeFamily,
    source_theme: Theme,
    actor: str,
    transitioned_at: datetime,
) -> Theme:
    latest = session.exec(
        select(Theme)
        .where(
            Theme.website_id == website.id,
            Theme.theme_key == family.family_key,
        )
        .order_by(Theme.version.desc())
        .with_for_update()
    ).first()
    theme = Theme(
        website_id=_id(website),
        business_id=website.business_id,
        brand_id=website.brand_id,
        theme_key=family.family_key,
        theme_name="Performance Local V3 Disposable Rehearsal",
        version=(latest.version + 1 if latest is not None else 1),
        token_contract_version=source_theme.token_contract_version,
        design_tokens=source_theme.design_tokens,
        token_hash_sha256=source_theme.token_hash_sha256,
        description="Disposable Performance Local V3 materialization; never production eligible.",
        lifecycle_status="available",
        approval_status="approved",
        created_by=actor,
        provenance_type="operator_configured",
        provenance_notes="Synthetic disposable activation rehearsal using the prior governed token set.",
        approved_by=actor,
        approved_at=transitioned_at,
        replaces_theme_id=(_id(latest) if latest is not None else None),
        created_at=transitioned_at,
        updated_at=transitioned_at,
    )
    session.add(theme)
    session.flush()
    try:
        theme_runtime._validate_theme_record(session, theme, require_approved=True)
    except theme_runtime.ThemeError as exc:
        raise ThemeActivationRehearsalError(str(exc)) from exc
    return theme


def _replace_active_selection(
    session: Session,
    *,
    website: Website,
    prior_selection: WebsiteThemeSelection,
    rehearsal_theme: Theme,
    actor: str,
    transitioned_at: datetime,
) -> WebsiteThemeSelection:
    latest = session.exec(
        select(WebsiteThemeSelection)
        .where(WebsiteThemeSelection.website_id == website.id)
        .order_by(WebsiteThemeSelection.version.desc())
        .with_for_update()
    ).first()
    prior_selection.status = "replaced"
    prior_selection.replaced_at = transitioned_at
    prior_selection.updated_at = transitioned_at
    session.add(prior_selection)
    selection = WebsiteThemeSelection(
        website_id=_id(website),
        theme_id=_id(rehearsal_theme),
        version=(latest.version + 1 if latest is not None else 1),
        status="active",
        selected_by=actor,
        rationale="Disposable Performance Local V3 activation rehearsal.",
        selected_at=transitioned_at,
        created_at=transitioned_at,
        updated_at=transitioned_at,
    )
    session.add(selection)
    compositions = list(
        session.exec(
            select(PageComposition)
            .where(PageComposition.website_id == website.id)
            .order_by(PageComposition.id)
            .with_for_update()
        ).all()
    )
    _require_valid_composition_heads(session, compositions, lock=True)
    for composition in compositions:
        if composition.status != "current":
            raise ThemeActivationRehearsalError(
                "Only current compositions may be invalidated by the rehearsal selection.",
                code="rehearsal_preexisting_stale_composition",
            )
        composition.status = "stale"
        composition.updated_at = transitioned_at
        session.add(composition)
    session.flush()
    return selection


def _refresh_stale_compositions_and_qa(
    session: Session,
    *,
    website: Website,
    expected_composition_ids: set[int],
) -> None:
    rows = list(
        session.exec(
            select(PageComposition)
            .where(PageComposition.website_id == website.id)
            .order_by(PageComposition.id)
        ).all()
    )
    _require_valid_composition_heads(session, rows)
    if {_id(item) for item in rows} != expected_composition_ids or any(
        item.status != "stale" for item in rows
    ):
        raise ThemeActivationRehearsalError(
            "The composition invalidation set differs from the exact activation plan.",
            code="rehearsal_composition_invalidation_mismatch",
        )
    site_plan_ids = sorted({item.site_plan_id for item in rows})
    refreshed_ids: set[int] = set()
    for site_plan_id in site_plan_ids:
        result = composition_service.refresh_site_plan_compositions(
            session,
            site_plan_id,
            commit=False,
        )
        if result.created or result.unchanged or result.blocked:
            raise ThemeActivationRehearsalError(
                "Rehearsal refresh must update only the legitimately stale, existing compositions.",
                code="rehearsal_composition_refresh_mismatch",
            )
        refreshed_ids.update(item.id for item in result.compositions)
    if refreshed_ids != expected_composition_ids:
        raise ThemeActivationRehearsalError(
            "The refreshed composition set differs from the exact activation plan.",
            code="rehearsal_composition_refresh_mismatch",
        )
    generated_ids = sorted(item.generated_page_id for item in rows)
    for generated_page_id in generated_ids:
        save_page_qa(session, generated_page_id, commit=False)
    session.flush()


def _composition_plan_blockers(
    session: Session,
    *,
    website: Website,
    compositions: list[PageComposition],
) -> list[FormReadinessItemRead]:
    blockers: list[FormReadinessItemRead] = []
    planned = list(
        session.exec(
            select(PlannedPage).where(
                PlannedPage.website_id == website.id,
                PlannedPage.generated_page_id.is_not(None),
            )
        ).all()
    )
    if len(planned) != len(compositions):
        blockers.append(
            FormReadinessItemRead(
                code="composition_coverage_incomplete",
                field="page_compositions",
                reason="Every current Generated Page requires one exact existing composition before rehearsal.",
            )
        )
    if any(item.status != "current" for item in compositions):
        blockers.append(
            FormReadinessItemRead(
                code="composition_preexisting_stale",
                field="page_compositions.status",
                reason="The rehearsal may refresh only compositions made stale by its own Theme selection.",
            )
        )
    for composition in compositions:
        try:
            current_composition_revision(session, composition)
        except PageCompositionHistoryError as exc:
            blockers.append(
                FormReadinessItemRead(
                    code="composition_history_invalid",
                    field="page_compositions.history",
                    reason=str(exc),
                )
            )
            break
    return blockers


def _publication_blockers() -> list[FormReadinessItemRead]:
    return [
        FormReadinessItemRead(
            code="preview_candidate_not_production_ready",
            field="theme_version.production_ready",
            reason="V3 remains preview_candidate with productionReady false.",
        ),
        FormReadinessItemRead(
            code="public_export_not_authorized",
            field="public_export.authorization",
            reason="The disposable internal export rehearsal grants no public export authority.",
        ),
        FormReadinessItemRead(
            code="publication_not_authorized",
            field="publication.authorization",
            reason="No publication or deployment authorization exists.",
        ),
    ]


def _planned_mutation_ledger(
    *,
    website_id: int,
    configuration_id: int,
    current_theme_id: int,
    current_selection_id: int,
    component_ids: list[int],
    composition_ids: list[int],
    generated_page_ids: list[int],
) -> list[ThemeActivationMutationRead]:
    values: list[tuple[str, str, int | None, str | None, str | None]] = [
        ("materialize_disposable_theme", "theme", None, None, "available:approved"),
        (
            "replace_active_selection",
            "website_theme_selection",
            current_selection_id,
            f"active:theme={current_theme_id}",
            "replaced",
        ),
        ("create_rehearsal_selection", "website_theme_selection", None, None, "active:v3"),
        ("approve_configuration", "website_theme_configuration", configuration_id, "draft", "approved"),
        ("append_configuration_approval_audit", "theme_configuration_audit", None, None, "website_configuration_approved"),
        ("activate_configuration", "website_theme_configuration", configuration_id, "approved", "active:disposable"),
        ("append_configuration_activation_audit", "theme_configuration_audit", None, None, "website_configuration_activated"),
    ]
    for item_id in component_ids:
        values.extend(
            [
                ("activate_component_revision", "component_configuration", item_id, "current:inactive", "current:activated"),
                ("append_component_activation_audit", "theme_configuration_audit", None, None, f"component_activated:{item_id}"),
            ]
        )
    values.extend(
        ("refresh_theme_stale_composition", "page_composition", item_id, "stale", "current")
        for item_id in composition_ids
    )
    values.extend(
        ("persist_final_state_qa", "generated_page", item_id, "theme_identity_stale", "current_exact_identity")
        for item_id in generated_page_ids
    )
    for item_id in component_ids:
        values.extend(
            [
                ("record_component_rollback", "component_configuration", item_id, "activated", "rollback_evidence_captured"),
                ("append_component_rollback_audit", "theme_configuration_audit", None, None, f"component_rolled_back:{item_id}"),
                ("restore_component_revision", "component_configuration", item_id, "rollback_evidence_captured", "exact_prior_fingerprint"),
            ]
        )
    values.extend(
        [
            ("record_configuration_rollback", "website_theme_configuration", configuration_id, "active:disposable", "rollback_evidence_captured"),
            ("append_configuration_rollback_audit", "theme_configuration_audit", None, None, "website_configuration_rolled_back"),
            ("restore_inactive_configuration", "website_theme_configuration", configuration_id, "rollback_evidence_captured", "draft:exact_prior_fingerprint"),
            ("replace_rehearsal_selection", "website_theme_selection", None, "active", "replaced"),
            ("restore_prior_selection", "website_theme_selection", current_selection_id, "replaced", f"active:theme={current_theme_id}"),
            ("retire_rehearsal_theme", "theme", None, "available", "retired"),
        ]
    )
    values.extend(
        ("refresh_rollback_stale_composition", "page_composition", item_id, "stale", "current")
        for item_id in composition_ids
    )
    values.extend(
        ("persist_rollback_state_qa", "generated_page", item_id, "theme_identity_stale", "current_exact_identity")
        for item_id in generated_page_ids
    )
    return [
        ThemeActivationMutationRead(
            sequence=index,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            expected_before=before,
            expected_after=after,
        )
        for index, (operation, target_type, target_id, before, after) in enumerate(
            values,
            start=1,
        )
    ]


def _component_revision_graph(
    components: list[WebsiteThemeComponentConfiguration],
) -> list[ThemeActivationComponentRevisionRead]:
    return [
        ThemeActivationComponentRevisionRead(
            component_configuration_id=_id(item),
            component_instance_key=item.component_instance_key,
            component_key=item.component_key,
            revision=item.revision,
            integrity_fingerprint=item.integrity_fingerprint,
            destination_component_configuration_id=(
                item.destination_component_configuration_id
            ),
            overrides_component_configuration_id=(
                item.overrides_component_configuration_id
            ),
            planned_page_id=item.planned_page_id,
        )
        for item in components
    ]


def _actual_activation_ledger(
    *,
    configuration: WebsiteThemeConfiguration,
    components: list[WebsiteThemeComponentConfiguration],
    prior_selection: WebsiteThemeSelection,
    rehearsal_theme: Theme,
    rehearsal_selection: WebsiteThemeSelection,
    composition_ids: list[int],
    generated_page_ids: list[int],
    audits: list[ThemeConfigurationAudit],
) -> list[ThemeActivationMutationRead]:
    values = [
        ("materialized", "theme", _id(rehearsal_theme), None, "available:approved"),
        ("replaced", "website_theme_selection", _id(prior_selection), "active", "replaced"),
        ("created", "website_theme_selection", _id(rehearsal_selection), None, "active"),
        ("activated", "website_theme_configuration", _id(configuration), "draft", "active"),
        *[
            ("activated", "component_configuration", _id(item), "current:inactive", "current:activated")
            for item in components
        ],
        *[
            ("refreshed", "page_composition", item_id, "stale", "current")
            for item_id in composition_ids
        ],
        *[
            ("persisted_final_state_qa", "generated_page", item_id, "stale_or_prior", "current_exact_identity")
            for item_id in generated_page_ids
        ],
        *[
            ("appended", "theme_configuration_audit", _id(item), None, item.action_type)
            for item in audits
        ],
    ]
    return _numbered_mutations(values)


def _actual_rollback_ledger(
    *,
    configuration: WebsiteThemeConfiguration,
    components: list[WebsiteThemeComponentConfiguration],
    prior_selection: WebsiteThemeSelection,
    rehearsal_theme: Theme,
    rehearsal_selection: WebsiteThemeSelection,
    composition_ids: list[int],
    generated_page_ids: list[int],
    audits: list[ThemeConfigurationAudit],
) -> list[ThemeActivationMutationRead]:
    values = [
        *[
            ("rolled_back", "component_configuration", _id(item), "activated", "exact_prior")
            for item in components
        ],
        ("rolled_back", "website_theme_configuration", _id(configuration), "active", "draft:exact_prior"),
        ("replaced", "website_theme_selection", _id(rehearsal_selection), "active", "replaced"),
        ("restored", "website_theme_selection", _id(prior_selection), "replaced", "active"),
        ("retired", "theme", _id(rehearsal_theme), "available", "retired"),
        *[
            ("refreshed", "page_composition", item_id, "stale", "current")
            for item_id in composition_ids
        ],
        *[
            ("persisted_rollback_state_qa", "generated_page", item_id, "stale_or_prior", "current_exact_identity")
            for item_id in generated_page_ids
        ],
        *[
            ("appended", "theme_configuration_audit", _id(item), None, item.action_type)
            for item in audits
        ],
    ]
    return _numbered_mutations(values)


def _numbered_mutations(
    values: list[tuple[str, str, int | None, str | None, str | None]],
) -> list[ThemeActivationMutationRead]:
    return [
        ThemeActivationMutationRead(
            sequence=index,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            expected_before=before,
            expected_after=after,
        )
        for index, (operation, target_type, target_id, before, after) in enumerate(
            values,
            start=1,
        )
    ]


def _delivery_scope_blockers(
    *,
    website_id: int,
    configuration_id: int,
    planned_page_id: int,
    components,
) -> list[str]:
    blockers: list[str] = []
    instances = [item.component_instance_key for item in components]
    if len(instances) != len(set(instances)):
        blockers.append(
            "duplicate_component_instance|component|The effective Page graph duplicates a component instance."
        )
    for item in components:
        if (
            item.website_id != website_id
            or item.website_theme_configuration_id != configuration_id
            or (
                item.scope_type == "website_default"
                and item.planned_page_id is not None
            )
            or (
                item.scope_type == "page_override"
                and item.planned_page_id != planned_page_id
            )
        ):
            blockers.append(
                f"component_scope_leak|component|Component {item.id} crosses its exact Website, configuration, or Page scope."
            )
    return blockers


def _composition_media_ids(composition: dict[str, Any]) -> list[int]:
    snapshot = composition.get("source_snapshot") or {}
    values: set[int] = set()
    for item in snapshot.get("media_assignments") or []:
        value = item.get("image_metadata_id") if isinstance(item, dict) else None
        if isinstance(value, int):
            values.add(value)
    page_media = snapshot.get("page_media") or {}
    for item in page_media.get("assignments") or []:
        value = item.get("asset_id") if isinstance(item, dict) else None
        if isinstance(value, int):
            values.add(value)
    return sorted(values)


def _wordpress_media_evidence(
    session: Session,
    image_metadata_ids: list[int],
) -> tuple[list[int], list[int], list[str]]:
    if not image_metadata_ids:
        return [], [], []
    rows = list(
        session.exec(
            select(ImageMetadata).where(ImageMetadata.id.in_(image_metadata_ids))
        ).all()
    )
    by_id = {_id(item): item for item in rows}
    wordpress_ids: list[int] = []
    local_only_ids: list[int] = []
    blockers: list[str] = []
    for image_metadata_id in image_metadata_ids:
        record = by_id.get(image_metadata_id)
        if record is None:
            blockers.append(
                "media_identity_unresolved|media|"
                f"Atlas ImageMetadata {image_metadata_id} does not exist."
            )
            continue
        if record.wordpress_media_id is None:
            local_only_ids.append(image_metadata_id)
        else:
            wordpress_ids.append(record.wordpress_media_id)
    if len(wordpress_ids) != len(set(wordpress_ids)):
        blockers.append(
            "media_identity_duplicated|media|"
            "Multiple Atlas ImageMetadata records resolve to one WordPress media identity."
        )
    return sorted(set(wordpress_ids)), sorted(local_only_ids), blockers


def _composition_uses_media_fallback(composition: dict[str, Any]) -> bool:
    for item in composition.get("effective_components") or []:
        if item.get("component_key") != "media_placement":
            continue
        bindings = item.get("input_bindings") or {}
        if "media_requirement_id" not in bindings and (
            "page_image_assignment_id" in bindings or "placement_key" in bindings
        ):
            return True
    return False


def _missing_required_media(composition: dict[str, Any]) -> bool:
    page_media = (composition.get("source_snapshot") or {}).get("page_media") or {}
    required = {
        item.get("id")
        for item in page_media.get("requirements") or []
        if isinstance(item, dict) and item.get("requirement_state") == "required"
    }
    assigned = {
        item.get("requirement_id")
        for item in page_media.get("assignments") or []
        if isinstance(item, dict) and item.get("asset_id") is not None
    }
    return bool(required - assigned)


def _banner_state(components) -> str:
    banners = [
        item
        for item in components
        if item.component_key == "campaign_banner" and item.enabled
    ]
    if not banners:
        return "disabled"
    if len(banners) != 1:
        return "blocked_duplicate"
    return f"enabled:{banners[0].configuration_payload.get('intent', 'unknown')}"


def _sticky_state(components) -> str:
    forms = {
        item.id
        for item in components
        if item.component_key == "compact_estimate_form" and item.enabled
    }
    sticky = [
        item
        for item in components
        if item.component_key == "sticky_mobile_action_bar" and item.enabled
    ]
    if not sticky:
        return "disabled"
    if len(sticky) != 1 or sticky[0].destination_component_configuration_id not in forms:
        return "blocked_destination"
    return "ready:exact_form_destination"


def _configuration_snapshot(record: WebsiteThemeConfiguration) -> dict[str, Any]:
    return {
        **theme_service._website_configuration_fingerprint_payload(record),
        "integrity_fingerprint": record.integrity_fingerprint,
        "updated_at": theme_service._datetime_value(record.updated_at),
    }


def _component_snapshot(record: WebsiteThemeComponentConfiguration) -> dict[str, Any]:
    return {
        "activation_identity": record.activation_identity,
        "activated_at": theme_service._datetime_value(record.activated_at),
        "rollback_identity": record.rollback_identity,
        "rollback_at": theme_service._datetime_value(record.rollback_at),
        "integrity_fingerprint": record.integrity_fingerprint,
        "updated_at": theme_service._datetime_value(record.updated_at),
    }


def _selection_snapshot(record: WebsiteThemeSelection) -> dict[str, Any]:
    return {
        "id": _id(record),
        "theme_id": record.theme_id,
        "status": record.status,
        "replaced_at": theme_service._datetime_value(record.replaced_at),
        "updated_at": theme_service._datetime_value(record.updated_at),
    }


def _restore_configuration(
    record: WebsiteThemeConfiguration,
    snapshot: dict[str, Any],
) -> None:
    for key in (
        "lifecycle_status",
        "updated_by",
        "approved_by",
        "activated_by",
        "rollback_by",
        "materialized_theme_id",
        "website_theme_selection_id",
        "integrity_fingerprint",
    ):
        setattr(record, key, snapshot[key])
    for key in ("approved_at", "activated_at", "rollback_at", "updated_at"):
        setattr(record, key, _parse_datetime(snapshot[key]))


def _restore_component(
    record: WebsiteThemeComponentConfiguration,
    snapshot: dict[str, Any],
) -> None:
    for key in (
        "activation_identity",
        "rollback_identity",
        "integrity_fingerprint",
    ):
        setattr(record, key, snapshot[key])
    for key in ("activated_at", "rollback_at", "updated_at"):
        setattr(record, key, _parse_datetime(snapshot[key]))


def _restore_selection(
    record: WebsiteThemeSelection,
    snapshot: dict[str, Any],
) -> None:
    record.status = snapshot["status"]
    record.replaced_at = _parse_datetime(snapshot["replaced_at"])
    record.updated_at = _parse_datetime(snapshot["updated_at"])


def _activation_state_audit(
    session: Session,
    *,
    configuration_id: int,
    rehearsal_theme_id: int,
    rehearsal_selection_id: int,
) -> ThemeConfigurationAudit:
    rows = list(
        session.exec(
            select(ThemeConfigurationAudit)
            .where(
                ThemeConfigurationAudit.website_theme_configuration_id
                == configuration_id,
                ThemeConfigurationAudit.action_type
                == "website_configuration_activated",
            )
            .order_by(ThemeConfigurationAudit.created_at.desc())
        ).all()
    )
    matches = [
        item
        for item in rows
        if isinstance(item.snapshot.get("rehearsal_state"), dict)
        and item.snapshot["rehearsal_state"].get("rehearsal_theme_id")
        == rehearsal_theme_id
        and item.snapshot["rehearsal_state"].get("rehearsal_selection_id")
        == rehearsal_selection_id
    ]
    if len(matches) != 1:
        raise ThemeActivationRehearsalError(
            "The exact disposable activation state audit is missing or ambiguous.",
            code="rehearsal_activation_audit_missing",
        )
    return matches[0]


def _current_components(
    session: Session,
    configuration_id: int,
    *,
    lock: bool = False,
) -> list[WebsiteThemeComponentConfiguration]:
    statement = (
        select(WebsiteThemeComponentConfiguration)
        .where(
            WebsiteThemeComponentConfiguration.website_theme_configuration_id
            == configuration_id,
            WebsiteThemeComponentConfiguration.lifecycle_status == "current",
        )
        .order_by(
            WebsiteThemeComponentConfiguration.component_instance_key,
            WebsiteThemeComponentConfiguration.id,
        )
    )
    if lock:
        statement = statement.with_for_update()
    return list(session.exec(statement).all())


def _generated_page_ids_for_compositions(
    session: Session,
    composition_ids: list[int],
) -> list[int]:
    if not composition_ids:
        return []
    rows = list(
        session.exec(
            select(PageComposition)
            .where(PageComposition.id.in_(composition_ids))
            .order_by(PageComposition.id)
        ).all()
    )
    if [item.id for item in rows] != composition_ids:
        raise ThemeActivationRehearsalError(
            "The final QA ledger differs from the exact composition plan.",
            code="rehearsal_qa_ledger_mismatch",
        )
    _require_valid_composition_heads(session, rows)
    return [item.generated_page_id for item in rows]


def _require_valid_composition_heads(
    session: Session,
    compositions: list[PageComposition],
    *,
    lock: bool = False,
) -> None:
    for composition in compositions:
        try:
            current_composition_revision(session, composition, lock=lock)
        except PageCompositionHistoryError as exc:
            raise ThemeActivationRehearsalError(
                str(exc),
                code="rehearsal_composition_history_invalid",
            ) from exc


def _sole_active_selection(
    session: Session,
    website: Website,
    *,
    lock: bool = False,
) -> tuple[WebsiteThemeSelection, Theme]:
    rows = _active_selections(session, _id(website), lock=lock)
    if len(rows) != 1:
        raise ThemeActivationRehearsalError(
            "Activation planning requires one exact current Website Theme selection.",
            code="rehearsal_selection_invariant_failed",
        )
    theme = _record(session, Theme, rows[0].theme_id, "Current Theme")
    try:
        theme_runtime._validate_theme_record(session, theme, require_approved=True)
    except theme_runtime.ThemeError as exc:
        raise ThemeActivationRehearsalError(str(exc)) from exc
    return rows[0], theme


def _active_selections(
    session: Session,
    website_id: int,
    *,
    lock: bool = False,
) -> list[WebsiteThemeSelection]:
    statement = (
        select(WebsiteThemeSelection)
        .where(
            WebsiteThemeSelection.website_id == website_id,
            WebsiteThemeSelection.status == "active",
        )
        .order_by(WebsiteThemeSelection.id)
    )
    if lock:
        statement = statement.with_for_update()
    return list(session.exec(statement).all())


def _active_selection_count(session: Session, website_id: int) -> int:
    return len(_active_selections(session, website_id))


def _selection_match_count(
    session: Session,
    *,
    website_id: int,
    theme_id: int,
    status: str,
) -> int:
    return len(
        session.exec(
            select(WebsiteThemeSelection).where(
                WebsiteThemeSelection.website_id == website_id,
                WebsiteThemeSelection.theme_id == theme_id,
                WebsiteThemeSelection.status == status,
            )
        ).all()
    )


def _locked_configuration(
    session: Session,
    configuration_id: int,
) -> WebsiteThemeConfiguration:
    record = session.exec(
        select(WebsiteThemeConfiguration)
        .where(WebsiteThemeConfiguration.id == configuration_id)
        .with_for_update()
    ).one_or_none()
    if record is None:
        raise ThemeActivationRehearsalError(
            "Website Theme configuration not found.",
            status_code=404,
            code="theme_configuration_not_found",
        )
    return record


def _locked_selection(
    session: Session,
    selection_id: int,
) -> WebsiteThemeSelection:
    record = session.exec(
        select(WebsiteThemeSelection)
        .where(WebsiteThemeSelection.id == selection_id)
        .with_for_update()
    ).one_or_none()
    if record is None:
        raise ThemeActivationRehearsalError(
            "Website Theme selection not found.",
            status_code=404,
            code="theme_selection_not_found",
        )
    return record


def _require_disposable_runtime(session: Session) -> None:
    if not disposable_rehearsal_environment_allowed():
        raise ThemeActivationRehearsalError(
            "Activation rehearsal is unavailable outside an explicit disposable loopback runtime.",
            status_code=404,
            code="rehearsal_route_unavailable",
        )
    bind = session.get_bind()
    database_name = str(getattr(bind.url, "database", "") or "").lower()
    exact_sqlite_memory = (
        getattr(bind.dialect, "name", "") == "sqlite"
        and database_name in {"", ":memory:"}
        and str(bind.url) in {"sqlite://", "sqlite:///:memory:"}
    )
    if database_name == "atlas" or not (
        exact_sqlite_memory
        or is_explicit_disposable_database_name(database_name)
    ):
        raise ThemeActivationRehearsalError(
            "Activation rehearsal refused the active or non-disposable database.",
            status_code=404,
            code="rehearsal_route_unavailable",
        )


def _session_pending_identity(session: Session) -> tuple[frozenset[int], ...]:
    return (
        frozenset(id(item) for item in session.new),
        frozenset(id(item) for item in session.dirty),
        frozenset(id(item) for item in session.deleted),
    )


def _record(session: Session, model, record_id: int, label: str):
    record = session.get(model, record_id)
    if record is None:
        raise ThemeActivationRehearsalError(
            f"{label} not found.",
            status_code=404,
            code="rehearsal_record_not_found",
        )
    return record


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _deduplicate_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _id(record: Any) -> int:
    if record.id is None:
        raise ThemeActivationRehearsalError(
            "The rehearsal encountered an unpersisted durable identity."
        )
    return int(record.id)
