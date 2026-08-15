from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlmodel import Session, select

from app.models import (
    GeneratedPage,
    PageComposition,
    PlannedPage,
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
    GovernedThemeActionsRead,
    PerformanceLocalDeliveryRead,
    ThemeConfigurationAuditRead,
    ThemeDeliveryBlockerRead,
    ThemeDeliveryExportEligibilityRead,
    ThemeDeliveryRendererResultRead,
    ThemeFamilyRead,
    ThemeFamilyVersionRead,
    WebsiteThemeComponentConfigurationRead,
    WebsiteThemeConfigurationRead,
    validate_component_payload,
)
from app.services import page_composition as composition_service
from app.services import theme_configurations as theme_service
from app.services import themes as theme_runtime
from app.services.form_submission_gateway import evaluate_form_readiness
from app.services.page_qa import effective_page_qa_state, generated_page_with_effective_qa
from app.services.themes import ThemeError, resolve_website_theme


DeliveryMode = Literal["active", "inactive_draft_preview", "activation_rehearsal"]


class ThemeDeliveryError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 409,
        code: str = "theme_delivery_blocked",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def read_active_performance_local_delivery(
    session: Session,
    generated_page_id: int,
) -> PerformanceLocalDeliveryRead:
    page = _page(session, generated_page_id)
    try:
        resolved_theme = resolve_website_theme(session, page.website_id)
    except ThemeError as exc:
        raise ThemeDeliveryError(str(exc)) from exc
    if resolved_theme.theme is None or resolved_theme.selection is None:
        raise ThemeDeliveryError(
            "No active Performance Local Theme delivery exists for this Website.",
            status_code=404,
            code="active_performance_local_delivery_not_found",
        )
    matches = list(
        session.exec(
            select(WebsiteThemeConfiguration).where(
                WebsiteThemeConfiguration.website_id == page.website_id,
                WebsiteThemeConfiguration.lifecycle_status == "active",
                WebsiteThemeConfiguration.materialized_theme_id
                == resolved_theme.theme.id,
                WebsiteThemeConfiguration.website_theme_selection_id
                == resolved_theme.selection.id,
            )
        ).all()
    )
    if len(matches) != 1:
        raise ThemeDeliveryError(
            "The active Theme selection does not resolve one exact Website configuration.",
            status_code=404 if not matches else 409,
            code="active_performance_local_delivery_not_found",
        )
    return _read_delivery(
        session,
        page=page,
        configuration=matches[0],
        mode="active",
    )


def read_local_performance_local_preview(
    session: Session,
    configuration_id: int,
    generated_page_id: int,
) -> PerformanceLocalDeliveryRead:
    page = _page(session, generated_page_id)
    configuration = _configuration(session, configuration_id)
    if configuration.website_id != page.website_id:
        raise ThemeDeliveryError("The preview Page crosses the Website boundary.")
    return _read_delivery(
        session,
        page=page,
        configuration=configuration,
        mode="inactive_draft_preview",
    )


def read_performance_local_rehearsal_delivery(
    session: Session,
    configuration_id: int,
    generated_page_id: int,
) -> PerformanceLocalDeliveryRead:
    page = _page(session, generated_page_id)
    configuration = _configuration(session, configuration_id)
    if configuration.website_id != page.website_id:
        raise ThemeDeliveryError("The rehearsal Page crosses the Website boundary.")
    return _read_delivery(
        session,
        page=page,
        configuration=configuration,
        mode="activation_rehearsal",
    )


def _read_delivery(
    session: Session,
    *,
    page: GeneratedPage,
    configuration: WebsiteThemeConfiguration,
    mode: DeliveryMode,
) -> PerformanceLocalDeliveryRead:
    version = _version(session, configuration.theme_family_version_id)
    family = _family(session, version.theme_family_id)
    if family.family_key != "performance-local" or version.version != 3:
        raise ThemeDeliveryError(
            "The canonical Performance Local V3 renderer accepts only its exact family version.",
            code="performance_local_v3_identity_mismatch",
        )
    activated_rehearsal = (
        mode == "activation_rehearsal"
        and configuration.lifecycle_status == "active"
    )
    if activated_rehearsal:
        _validate_activated_rehearsal_configuration(
            session,
            configuration=configuration,
            version=version,
            family=family,
        )
    else:
        try:
            theme_service._validate_website_configuration(session, configuration)
        except theme_service.ThemeConfigurationError as exc:
            raise ThemeDeliveryError(str(exc)) from exc
    if mode == "inactive_draft_preview":
        if (
            configuration.lifecycle_status != "draft"
            or version.lifecycle_status != "preview_candidate"
            or version.production_ready
            or configuration.materialized_theme_id is not None
            or configuration.website_theme_selection_id is not None
        ):
            raise ThemeDeliveryError(
                "Non-active delivery requires the exact inactive V3 preview candidate.",
                code="inactive_preview_identity_mismatch",
            )
    elif mode == "activation_rehearsal" and not activated_rehearsal:
        if (
            configuration.lifecycle_status != "draft"
            or version.lifecycle_status != "preview_candidate"
            or version.production_ready
            or configuration.materialized_theme_id is not None
            or configuration.website_theme_selection_id is not None
        ):
            raise ThemeDeliveryError(
                "Rehearsal delivery requires the exact draft or activated disposable V3 identity.",
                code="rehearsal_identity_mismatch",
            )
    elif mode == "active" and (
        configuration.lifecycle_status != "active"
        or version.lifecycle_status != "approved"
        or not version.production_ready
    ):
        # This branch is deliberately independent of the explicit preview path:
        # ordinary public delivery can never fall back to a draft.
        raise ThemeDeliveryError(
            "Active delivery rejects draft or non-production Theme configuration.",
            code="active_delivery_requires_production_configuration",
        )

    planned_page_id = theme_service._preview_planned_page_id(
        session,
        website_id=page.website_id,
        generated_page_id=page.id,
    )
    if planned_page_id is None:  # generated Page identity is required above
        raise ThemeDeliveryError("The Generated Page lacks one exact Planned Page identity.")
    components = _effective_components(
        session,
        configuration,
        planned_page_id=planned_page_id,
        activated_rehearsal=activated_rehearsal,
    )
    if mode == "active" and any(
        item.enabled
        and (
            item.activation_identity is None
            or item.activated_at is None
            or item.rollback_identity is not None
            or item.rollback_at is not None
        )
        for item in components
    ):
        raise ThemeDeliveryError(
            "Active delivery requires exact non-rolled-back component activation evidence.",
            code="active_component_activation_incomplete",
        )
    form_components = [
        item
        for item in components
        if item.enabled and item.component_key == "compact_estimate_form"
    ]
    form_component = form_components[0] if len(form_components) == 1 else None
    readiness = evaluate_form_readiness(form_component, mode=mode)
    actions = _governed_actions(session, page.website_id, components)
    audits = theme_service._audit_history(
        session,
        family=family,
        family_version=version,
        website_configuration=configuration,
        component_ids={theme_service._required_id(item) for item in components},
    )
    try:
        theme_service._require_audit_coverage(
            session,
            families=[family],
            versions=[version],
            configurations=[configuration],
            components=components,
        )
    except theme_service.ThemeConfigurationError as exc:
        raise ThemeDeliveryError(str(exc), code="delivery_audit_incomplete") from exc

    strict_renderer_identity = mode == "active" or activated_rehearsal
    composition, composition_errors = _composition(
        session,
        page,
        require_current=strict_renderer_identity,
    )
    qa_state = effective_page_qa_state(session, page)
    qa_errors: list[str] = []
    if not qa_state.current:
        qa_reason = (
            "Generated Page QA is not current "
            f"({qa_state.classification})."
        )
        if strict_renderer_identity:
            raise ThemeDeliveryError(
                qa_reason,
                code="page_qa_not_ready",
            )
        qa_errors.append(qa_reason)
    elif not qa_state.ready:
        qa_reason = (
            "Generated Page QA is current but not ready "
            f"({qa_state.result.readiness_status if qa_state.result is not None else 'blocked'})."
        )
        if mode == "active":
            raise ThemeDeliveryError(
                qa_reason,
                code="page_qa_not_ready",
            )
        qa_errors.append(qa_reason)
    blockers: list[ThemeDeliveryBlockerRead] = []
    for index, reason in enumerate(composition_errors, start=1):
        blockers.append(
            ThemeDeliveryBlockerRead(
                code=f"composition_readiness_{index}",
                category="media" if "media" in reason.lower() else "qa",
                reason=reason,
            )
        )
    for index, reason in enumerate(qa_errors, start=1):
        blockers.append(
            ThemeDeliveryBlockerRead(
                code=f"page_qa_readiness_{index}",
                category="qa",
                reason=reason,
            )
        )
    if mode == "activation_rehearsal":
        activation_audits = [
            item
            for item in audits
            if item.action_type
            in {"website_configuration_activated", "component_activated"}
        ]
        if (
            configuration.lifecycle_status != "active"
            or len(activation_audits) != 1 + len(components)
            or any(
                item.activation_identity is None
                or item.activated_at is None
                or item.rollback_identity is not None
                or item.rollback_at is not None
                for item in components
            )
            ):
            blockers.append(
                ThemeDeliveryBlockerRead(
                    code="rehearsal_activation_audit_incomplete",
                    category="export",
                    reason=(
                        "Internal rehearsal export requires the exact activated disposable "
                        "configuration and component audit identities."
                    ),
                )
            )
    for item in readiness.blockers:
        blockers.append(
            ThemeDeliveryBlockerRead(
                code=item.code,
                category=(
                    "privacy"
                    if item.field.startswith(("privacy.", "retention.", "spam."))
                    else "form"
                ),
                reason=item.reason,
            )
        )

    renderer_blockers = [*composition_errors, *qa_errors]
    if mode in {"active", "activation_rehearsal"} and not readiness.can_submit:
        renderer_blockers.append("The exact governed form is not delivery-ready.")
    renderer_ready = not renderer_blockers
    export = _export_eligibility(
        session,
        mode=mode,
        page=page,
        planned_page_id=planned_page_id,
        family=family,
        version=version,
        configuration=configuration,
        components=components,
        audits=audits,
        readiness=readiness,
        renderer_ready=renderer_ready,
    )
    for item in export.blockers:
        blockers.append(
            ThemeDeliveryBlockerRead(
                code=item.code,
                category="export",
                reason=item.reason,
            )
        )
    blockers = _deduplicate_blockers(blockers)

    return PerformanceLocalDeliveryRead(
        mode=mode,
        non_active_label=(
            None
            if mode == "active"
            else (
                "DRAFT PREVIEW — NOT ACTIVE"
                if mode == "inactive_draft_preview"
                else "ACTIVATION REHEARSAL — DISPOSABLE"
            )
        ),
        page=generated_page_with_effective_qa(session, page),
        composition=composition,
        theme_family=ThemeFamilyRead.model_validate(family),
        theme_version=ThemeFamilyVersionRead.model_validate(version),
        website_configuration=WebsiteThemeConfigurationRead.model_validate(
            configuration
        ),
        components=[_public_component_read(item) for item in components],
        audit_history=[_public_audit_read(item) for item in audits],
        governed_actions=actions,
        form_readiness=_public_form_readiness(readiness),
        export_eligibility=export,
        renderer_result=ThemeDeliveryRendererResultRead(
            status="ready" if renderer_ready else "blocked",
            result_code=(
                "renderer_ready"
                if renderer_ready
                else "renderer_blocked_by_governed_readiness"
            ),
            evaluated_page_id=theme_service._required_id(page),
        ),
        blockers=blockers,
    )


def _validate_activated_rehearsal_configuration(
    session: Session,
    *,
    configuration: WebsiteThemeConfiguration,
    version: ThemeFamilyVersion,
    family: ThemeFamily,
) -> None:
    if (
        version.lifecycle_status != "preview_candidate"
        or version.production_ready
        or family.lifecycle_status != "registered"
        or configuration.lifecycle_status != "active"
        or configuration.approved_by is None
        or configuration.approved_at is None
        or configuration.activated_by is None
        or configuration.activated_at is None
        or configuration.rollback_by is not None
        or configuration.rollback_at is not None
        or configuration.materialized_theme_id is None
        or configuration.website_theme_selection_id is None
        or configuration.integrity_fingerprint
        != theme_service._website_configuration_fingerprint_from_record(configuration)
    ):
        raise ThemeDeliveryError(
            "Activated rehearsal configuration evidence is incomplete.",
            code="rehearsal_activation_identity_invalid",
        )
    website = session.get(Website, configuration.website_id)
    theme = session.get(Theme, configuration.materialized_theme_id)
    selection = session.get(
        WebsiteThemeSelection,
        configuration.website_theme_selection_id,
    )
    if (
        website is None
        or theme is None
        or selection is None
        or theme.website_id != website.id
        or theme.business_id != website.business_id
        or theme.brand_id != website.brand_id
        or theme.theme_key != family.family_key
        or theme.lifecycle_status != "available"
        or theme.approval_status != "approved"
        or selection.website_id != website.id
        or selection.theme_id != theme.id
        or selection.status != "active"
    ):
        raise ThemeDeliveryError(
            "Activated rehearsal does not bind its exact approved disposable Theme selection.",
            code="rehearsal_selection_identity_invalid",
        )
    active = list(
        session.exec(
            select(WebsiteThemeSelection).where(
                WebsiteThemeSelection.website_id == website.id,
                WebsiteThemeSelection.status == "active",
            )
        ).all()
    )
    if len(active) != 1 or active[0].id != selection.id:
        raise ThemeDeliveryError(
            "Activated rehearsal does not have exactly one active Website Theme selection.",
            code="rehearsal_selection_identity_invalid",
        )
    try:
        theme_runtime._validate_theme_record(session, theme, require_approved=True)
        resolved = resolve_website_theme(session, website.id)
    except ThemeError as exc:
        raise ThemeDeliveryError(str(exc), code="rehearsal_theme_invalid") from exc
    if (
        resolved.theme is None
        or resolved.selection is None
        or resolved.theme.id != theme.id
        or resolved.selection.id != selection.id
    ):
        raise ThemeDeliveryError(
            "Activated rehearsal Theme does not match the sole resolved selection.",
            code="rehearsal_selection_identity_invalid",
        )


def _validate_activated_rehearsal_component(
    session: Session,
    *,
    configuration: WebsiteThemeConfiguration,
    component: WebsiteThemeComponentConfiguration,
) -> None:
    if (
        component.website_theme_configuration_id != configuration.id
        or component.website_id != configuration.website_id
        or component.theme_family_version_id != configuration.theme_family_version_id
        or component.lifecycle_status != "current"
        or component.scope_type != "website_default"
        or component.planned_page_id is not None
        or component.activation_identity is None
        or component.activated_at is None
        or component.rollback_identity is not None
        or component.rollback_at is not None
        or component.integrity_fingerprint
        != theme_service._component_fingerprint_from_record(component)
    ):
        raise ThemeDeliveryError(
            "Activated rehearsal component evidence is incomplete.",
            code="rehearsal_component_identity_invalid",
        )
    try:
        normalized = validate_component_payload(
            component.component_key,
            component.configuration_payload,
            component.component_contract_version,
        )
        version = session.get(ThemeFamilyVersion, component.theme_family_version_id)
        if version is None:
            raise ValueError("Theme Family Version is missing")
        matching = [
            item
            for item in version.supported_component_contracts
            if item.get("component_key") == component.component_key
        ]
        if len(matching) != 1:
            raise ValueError("Component contract is missing")
        contract = matching[0]
        if (
            component.configuration_payload != normalized
            or contract.get("contract_version") != component.component_contract_version
            or contract.get("variant") != component.variant
            or contract.get("placement") != component.placement
            or contract.get("responsive_visibility") != component.responsive_visibility
        ):
            raise ValueError("Component contract identity does not match")
        theme_service._validate_component_approval_identity(
            component.component_key,
            normalized,
            component.approval_identity,
        )
    except (ValueError, theme_service.ThemeConfigurationError) as exc:
        raise ThemeDeliveryError(
            "Activated rehearsal component contract is invalid.",
            code="rehearsal_component_identity_invalid",
        ) from exc


def _public_component_read(
    component: WebsiteThemeComponentConfiguration,
) -> WebsiteThemeComponentConfigurationRead:
    read = WebsiteThemeComponentConfigurationRead.model_validate(component)
    if component.component_key != "compact_estimate_form":
        return read
    payload = dict(read.configuration_payload)
    provider = dict(payload.get("provider") or {})
    provider.update(
        {
            "provider_key": None,
            "destination": None,
            "provider_secret_reference": None,
        }
    )
    payload["provider"] = provider
    spam = dict(payload.get("spam") or {})
    if "configuration_reference" in spam:
        spam["configuration_reference"] = None
    payload["spam"] = spam
    return read.model_copy(update={"configuration_payload": payload})


def _public_audit_read(audit: ThemeConfigurationAudit) -> ThemeConfigurationAuditRead:
    read = ThemeConfigurationAuditRead.model_validate(audit)
    return read.model_copy(update={"snapshot": _redact_public_payload(read.snapshot)})


def _redact_public_payload(value):
    if isinstance(value, list):
        return [_redact_public_payload(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _redact_public_payload(item) for key, item in value.items()}
    provider = result.get("provider")
    if isinstance(provider, dict):
        for key in ("provider_key", "destination", "provider_secret_reference"):
            if key in provider:
                provider[key] = None
    spam = result.get("spam")
    if isinstance(spam, dict) and "configuration_reference" in spam:
        spam["configuration_reference"] = None
    return result


def _public_form_readiness(readiness):
    return readiness.model_copy(
        update={
            "provider_state": readiness.provider_state.model_copy(
                update={"provider_key": None}
            )
        }
    )


def _effective_components(
    session: Session,
    configuration: WebsiteThemeConfiguration,
    *,
    planned_page_id: int,
    activated_rehearsal: bool,
) -> list[WebsiteThemeComponentConfiguration]:
    rows = list(
        session.exec(
            select(WebsiteThemeComponentConfiguration)
            .where(
                WebsiteThemeComponentConfiguration.website_theme_configuration_id
                == configuration.id,
                WebsiteThemeComponentConfiguration.lifecycle_status == "current",
            )
            .order_by(
                WebsiteThemeComponentConfiguration.component_instance_key,
                WebsiteThemeComponentConfiguration.id,
            )
        ).all()
    )
    for row in rows:
        if activated_rehearsal:
            _validate_activated_rehearsal_component(
                session,
                configuration=configuration,
                component=row,
            )
        else:
            try:
                theme_service._validate_component_configuration(session, row)
            except theme_service.ThemeConfigurationError as exc:
                raise ThemeDeliveryError(str(exc), code="component_integrity_invalid") from exc
    resolved = theme_service._resolve_components_for_page(
        rows,
        planned_page_id,
        evaluated_at=datetime.now(UTC),
    )
    try:
        theme_service._validate_preview_components(session, configuration, resolved)
    except theme_service.ThemeConfigurationError as exc:
        raise ThemeDeliveryError(str(exc), code="component_graph_invalid") from exc
    return resolved


def _governed_actions(
    session: Session,
    website_id: int,
    components: list[WebsiteThemeComponentConfiguration],
) -> GovernedThemeActionsRead:
    website = session.get(Website, website_id)
    if website is None:
        raise ThemeDeliveryError("Website delivery scope was not found.", status_code=404)
    sticky = [
        item
        for item in components
        if item.enabled and item.component_key == "sticky_mobile_action_bar"
    ]
    if len(sticky) != 1:
        raise ThemeDeliveryError("Delivery requires one exact sticky-action policy.")
    sticky_component = sticky[0]
    payload = validate_component_payload(
        sticky_component.component_key,
        sticky_component.configuration_payload,
        sticky_component.component_contract_version,
    )
    destinations = {
        item.destination_component_configuration_id
        for item in components
        if item.enabled and item.destination_component_configuration_id is not None
    }
    if len(destinations) != 1:
        raise ThemeDeliveryError("Conversion actions do not resolve one exact form target.")
    phone_display, call_destination = theme_service._governed_phone(session, website)
    return GovernedThemeActionsRead(
        phone_display=phone_display,
        call_destination=call_destination,
        call_label=payload["call_label"],
        estimate_label=payload["estimate_label"],
        estimate_destination_component_configuration_id=next(iter(destinations)),
        desktop_header_actions_enabled=payload["desktop_sticky_header"],
        mobile_sticky_actions_enabled=payload["mobile_sticky_bottom"],
        desktop_header_estimate_destination_component_configuration_id=(
            sticky_component.destination_component_configuration_id
            if payload["desktop_sticky_header"]
            else None
        ),
        mobile_sticky_estimate_destination_component_configuration_id=(
            sticky_component.destination_component_configuration_id
            if payload["mobile_sticky_bottom"]
            else None
        ),
    )


def _composition(
    session: Session,
    page: GeneratedPage,
    *,
    require_current: bool,
) -> tuple[dict[str, object], list[str]]:
    rows = list(
        session.exec(
            select(PageComposition).where(
                PageComposition.generated_page_id == page.id
            )
        ).all()
    )
    if len(rows) != 1:
        raise ThemeDeliveryError(
            "Delivery requires one exact current Page Composition.",
            code="page_composition_missing" if not rows else "page_composition_duplicated",
        )
    record = rows[0]
    if require_current and record.status != "current":
        raise ThemeDeliveryError(
            "Delivery requires a persisted current Page Composition.",
            code="page_composition_not_current",
        )
    try:
        read = composition_service._read(
            session,
            record,
            require_current=require_current,
        )
    except composition_service.PageCompositionError as exc:
        raise ThemeDeliveryError(str(exc), code="page_composition_invalid") from exc
    errors = list(read.validation_errors)
    values = read.model_dump(mode="python")
    if record.status != "current":
        errors.append("The persisted Page Composition is not current.")
        values["status"] = "stale"
    return values, errors


def _export_eligibility(
    session: Session,
    *,
    mode: DeliveryMode,
    page: GeneratedPage,
    planned_page_id: int,
    family: ThemeFamily,
    version: ThemeFamilyVersion,
    configuration: WebsiteThemeConfiguration,
    components: list[WebsiteThemeComponentConfiguration],
    audits: list[ThemeConfigurationAudit],
    readiness,
    renderer_ready: bool,
) -> ThemeDeliveryExportEligibilityRead:
    blockers: list[FormReadinessItemRead] = []
    if not renderer_ready:
        blockers.append(
            FormReadinessItemRead(
                code="renderer_not_ready",
                field="renderer_result",
                reason="Export requires a ready production-like renderer result.",
            )
        )
    if not readiness.can_submit:
        blockers.append(
            FormReadinessItemRead(
                code="form_not_ready",
                field="form_readiness",
                reason="Export requires a ready governed form and provider boundary.",
            )
        )
    if mode == "inactive_draft_preview":
        blockers.append(
            FormReadinessItemRead(
                code="inactive_draft_export_blocked",
                field="website_configuration.lifecycle_status",
                reason="Inactive draft data is excluded from public export.",
            )
        )
    if mode == "active" and (
        version.lifecycle_status != "approved"
        or not version.production_ready
        or configuration.lifecycle_status != "active"
    ):
        blockers.append(
            FormReadinessItemRead(
                code="production_identity_incomplete",
                field="theme_version.production_ready",
                reason="Public export requires an approved production-ready active identity.",
            )
        )
    if mode == "activation_rehearsal":
        activation_audits = [
            item
            for item in audits
            if item.action_type
            in {"website_configuration_activated", "component_activated"}
        ]
        if (
            configuration.lifecycle_status != "active"
            or configuration.materialized_theme_id is None
            or configuration.website_theme_selection_id is None
            or len(activation_audits) != 1 + len(components)
            or any(
                item.activation_identity is None
                or item.activated_at is None
                or item.rollback_identity is not None
                or item.rollback_at is not None
                for item in components
            )
        ):
            blockers.append(
                FormReadinessItemRead(
                    code="rehearsal_activation_audit_incomplete",
                    field="activation_audit_identity",
                    reason=(
                        "Internal rehearsal export requires the exact activated disposable "
                        "configuration and component audit identities."
                    ),
                )
            )
    eligible = not blockers
    if mode == "active" and eligible:
        try:
            theme_service.require_theme_configuration_export_eligible(
                session,
                page.website_id,
                theme_service._required_id(configuration),
                generated_page_id=theme_service._required_id(page),
            )
        except theme_service.ThemeConfigurationError as exc:
            eligible = False
            blockers.append(
                FormReadinessItemRead(
                    code=exc.code,
                    field="public_export",
                    reason=str(exc),
                )
            )
    identity = (
        _export_identity(
            page=page,
            planned_page_id=planned_page_id,
            family=family,
            version=version,
            configuration=configuration,
            components=components,
            audits=audits,
            readiness=readiness,
        )
        if eligible
        else None
    )
    return ThemeDeliveryExportEligibilityRead(
        eligible=eligible,
        mode="internal_rehearsal" if mode == "activation_rehearsal" else "public",
        identity=identity,
        blockers=blockers,
    )


def _export_identity(
    *,
    page: GeneratedPage,
    planned_page_id: int,
    family: ThemeFamily,
    version: ThemeFamilyVersion,
    configuration: WebsiteThemeConfiguration,
    components: list[WebsiteThemeComponentConfiguration],
    audits: list[ThemeConfigurationAudit],
    readiness,
) -> dict[str, object]:
    banner = next(
        (item for item in components if item.enabled and item.component_key == "campaign_banner"),
        None,
    )
    sticky = next(
        (
            item
            for item in components
            if item.enabled and item.component_key == "sticky_mobile_action_bar"
        ),
        None,
    )
    return {
        "generated_page_id": page.id,
        "planned_page_id": planned_page_id,
        "theme_family_id": family.id,
        "theme_family_key": family.family_key,
        "theme_family_version_id": version.id,
        "theme_family_version": version.version,
        "compatibility_identity": version.compatibility_identity,
        "theme_family_version_integrity_fingerprint": version.integrity_fingerprint,
        "website_configuration_id": configuration.id,
        "website_configuration_version": configuration.version,
        "website_configuration_integrity_fingerprint": configuration.integrity_fingerprint,
        "component_revisions": [
            {
                "component_configuration_id": item.id,
                "component_instance_key": item.component_instance_key,
                "component_key": item.component_key,
                "revision": item.revision,
                "integrity_fingerprint": item.integrity_fingerprint,
            }
            for item in components
        ],
        "activation_audit_identity": sorted(
            item.snapshot_hash
            for item in audits
            if item.action_type
            in {"website_configuration_activated", "component_activated"}
        ),
        "banner_intent": (
            banner.configuration_payload.get("intent") if banner is not None else None
        ),
        "sticky_action_identity": (
            {
                "component_configuration_id": sticky.id,
                "integrity_fingerprint": sticky.integrity_fingerprint,
                "destination_component_configuration_id": (
                    sticky.destination_component_configuration_id
                ),
            }
            if sticky is not None
            else None
        ),
        "form_state": readiness.submission_state,
        "provider_state": {
            "destination_configured": readiness.provider_state.destination_configured,
            "adapter_registered": readiness.provider_state.adapter_registered,
            "test_only": readiness.provider_state.test_only,
        },
        "privacy_consent_readiness": readiness.privacy.model_dump(mode="json"),
    }


def _deduplicate_blockers(
    blockers: list[ThemeDeliveryBlockerRead],
) -> list[ThemeDeliveryBlockerRead]:
    result: list[ThemeDeliveryBlockerRead] = []
    seen: set[tuple[str, str, str]] = set()
    for blocker in blockers:
        identity = (blocker.code, blocker.category, blocker.reason)
        if identity not in seen:
            seen.add(identity)
            result.append(blocker)
    return result


def _page(session: Session, page_id: int) -> GeneratedPage:
    page = session.get(GeneratedPage, page_id)
    if page is None:
        raise ThemeDeliveryError(
            "Generated Page was not found.",
            status_code=404,
            code="generated_page_not_found",
        )
    return page


def _configuration(
    session: Session,
    configuration_id: int,
) -> WebsiteThemeConfiguration:
    configuration = session.get(WebsiteThemeConfiguration, configuration_id)
    if configuration is None:
        raise ThemeDeliveryError(
            "Website Theme configuration was not found.",
            status_code=404,
            code="theme_configuration_not_found",
        )
    return configuration


def _version(session: Session, version_id: int) -> ThemeFamilyVersion:
    version = session.get(ThemeFamilyVersion, version_id)
    if version is None:
        raise ThemeDeliveryError("Theme Family Version was not found.", status_code=404)
    try:
        theme_service._validate_family_version(session, version)
    except theme_service.ThemeConfigurationError as exc:
        raise ThemeDeliveryError(str(exc)) from exc
    return version


def _family(session: Session, family_id: int) -> ThemeFamily:
    family = session.get(ThemeFamily, family_id)
    if family is None:
        raise ThemeDeliveryError("Theme Family was not found.", status_code=404)
    try:
        theme_service._validate_family(family)
    except theme_service.ThemeConfigurationError as exc:
        raise ThemeDeliveryError(str(exc)) from exc
    return family
