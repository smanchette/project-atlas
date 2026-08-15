from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_
from sqlmodel import Session, select

from app.models import (
    Business,
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
    CompactEstimateFormConfiguration,
    ConversionComponentGraphRevisionCreate,
    ConversionComponentGraphRevisionRead,
    FormProviderStateRead,
    GovernedThemeActionsRead,
    PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS,
    PERFORMANCE_LOCAL_V2_SOURCE_COMMIT,
    PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS,
    PerformanceLocalV3ExportEligibilityRead,
    ThemeActivationReadinessItem,
    ThemeActivationReadinessRead,
    ThemeConfigurationAuditRead,
    ThemeConfigurationExportComponentRead,
    ThemeConfigurationExportEligibilityRead,
    ThemeDraftPreviewRead,
    ThemeDraftBundleCreate,
    ThemeFamilyCreate,
    ThemeFamilyRead,
    ThemeFamilyVersionCreate,
    ThemeFamilyVersionRead,
    WebsiteThemeComponentConfigurationCreate,
    WebsiteThemeComponentConfigurationRead,
    WebsiteThemeComponentConfigurationRevisionCreate,
    WebsiteThemeConfigurationCreate,
    WebsiteThemeConfigurationRead,
    validate_component_payload,
    validate_fingerprint,
)
from app.services.form_submission_contracts import (
    provider_disabled_state,
    validate_provider_disabled_form,
)
from app.services.themes import ThemeError, resolve_website_theme


_PHONE_PATTERN = re.compile(r"^\+?\d{6,25}$")
_AUDIT_ACTION_TYPES = frozenset(
    {
        "family_registered",
        "family_version_registered",
        "family_version_approved",
        "website_draft_created",
        "website_configuration_revision_created",
        "website_configuration_approved",
        "website_configuration_activated",
        "website_configuration_superseded",
        "website_configuration_rolled_back",
        "website_configuration_retired",
        "component_created",
        "component_revision_created",
        "component_superseded",
        "component_activated",
        "component_rolled_back",
        "family_retired",
        "family_version_retired",
    }
)


class ThemeConfigurationError(ValueError):
    """Fail-closed durable Theme-family/configuration domain error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 409,
        code: str = "theme_configuration_invalid",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def canonical_json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def register_theme_family(
    session: Session,
    payload: ThemeFamilyCreate,
    *,
    _commit_changes: bool = True,
) -> ThemeFamily:
    fingerprint = _family_fingerprint(
        family_key=payload.family_key,
        display_name=payload.display_name,
        description=payload.description,
        provider_source_identity=payload.provider_source_identity,
        lifecycle_status="registered",
        created_by=payload.created_by,
        retired_by=None,
        retired_at=None,
    )
    existing = session.exec(
        select(ThemeFamily).where(ThemeFamily.family_key == payload.family_key)
    ).first()
    if existing:
        _validate_family(existing)
        if existing.integrity_fingerprint != fingerprint:
            raise ThemeConfigurationError(
                "Theme Family key already exists with different governed identity."
            )
        return existing

    family = ThemeFamily(
        **payload.model_dump(mode="python"),
        lifecycle_status="registered",
        integrity_fingerprint=fingerprint,
    )
    session.add(family)
    session.flush()
    _append_audit(
        session,
        action_type="family_registered",
        actor=payload.created_by,
        rationale="Register the Website-independent Theme Family contract.",
        snapshot=_family_fingerprint_payload(family),
        theme_family_id=_required_id(family),
    )
    if _commit_changes:
        _commit(session)
        session.refresh(family)
    else:
        session.flush()
    return family


def register_theme_family_version(
    session: Session,
    theme_family_id: int,
    payload: ThemeFamilyVersionCreate,
    *,
    _commit_changes: bool = True,
) -> ThemeFamilyVersion:
    family = _theme_family(session, theme_family_id)
    _validate_family(family)
    if family.lifecycle_status != "registered":
        raise ThemeConfigurationError("Retired Theme Families cannot receive a new version.")

    contracts = [item.model_dump(mode="json") for item in payload.supported_component_contracts]
    if family.family_key == "performance-local" and payload.version == 2:
        expected_contracts = list(PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS)
        if (
            contracts != expected_contracts
            or payload.source_commit != PERFORMANCE_LOCAL_V2_SOURCE_COMMIT
        ):
            raise ThemeConfigurationError(
                "Performance Local v2 registration requires the exact canonical source commit and server contract."
            )
    if family.family_key == "performance-local" and payload.version == 3:
        if contracts != list(PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS):
            raise ThemeConfigurationError(
                "Performance Local v3 registration requires the exact canonical server contract."
            )
        if payload.supersedes_theme_family_version_id is None:
            raise ThemeConfigurationError(
                "Performance Local v3 registration requires the exact v2 predecessor identity."
            )
    compatibility_identity = canonical_json_hash(
        {
            "family_key": family.family_key,
            "version": payload.version,
            "supported_component_contracts": contracts,
        }
    )
    fingerprint = _family_version_fingerprint(
        theme_family_id=theme_family_id,
        version=payload.version,
        lifecycle_status=payload.lifecycle_status,
        production_ready=payload.production_ready,
        source_commit=payload.source_commit,
        compatibility_identity=compatibility_identity,
        supported_component_contracts=contracts,
        created_by=payload.created_by,
        retired_by=None,
        retired_at=None,
        supersedes_theme_family_version_id=payload.supersedes_theme_family_version_id,
    )
    existing = session.exec(
        select(ThemeFamilyVersion).where(
            ThemeFamilyVersion.theme_family_id == theme_family_id,
            ThemeFamilyVersion.version == payload.version,
        )
    ).first()
    if existing:
        _validate_family_version(session, existing)
        if existing.integrity_fingerprint != fingerprint:
            raise ThemeConfigurationError(
                "Theme Family version already exists with different contract evidence."
            )
        return existing

    predecessor = None
    if payload.supersedes_theme_family_version_id is not None:
        predecessor = _theme_family_version(
            session,
            payload.supersedes_theme_family_version_id,
        )
        _validate_family_version(session, predecessor)
        if predecessor.theme_family_id != theme_family_id or predecessor.version >= payload.version:
            raise ThemeConfigurationError(
                "Theme Family version lineage must remain within one family and increase."
            )
        if (
            family.family_key == "performance-local"
            and payload.version == 3
            and predecessor.version != 2
        ):
            raise ThemeConfigurationError(
                "Performance Local v3 must supersede the exact Performance Local v2 version."
            )

    version = ThemeFamilyVersion(
        theme_family_id=theme_family_id,
        version=payload.version,
        lifecycle_status=payload.lifecycle_status,
        production_ready=payload.production_ready,
        source_commit=payload.source_commit,
        compatibility_identity=compatibility_identity,
        supported_component_contracts=contracts,
        created_by=payload.created_by,
        supersedes_theme_family_version_id=(predecessor.id if predecessor else None),
        integrity_fingerprint=fingerprint,
    )
    session.add(version)
    session.flush()
    _append_audit(
        session,
        action_type="family_version_registered",
        actor=payload.created_by,
        rationale="Register an immutable Theme Family contract version.",
        snapshot=_family_version_fingerprint_payload(version),
        theme_family_version_id=_required_id(version),
    )
    if _commit_changes:
        _commit(session)
        session.refresh(version)
    else:
        session.flush()
    return version


def create_website_theme_configuration(
    session: Session,
    website_id: int,
    payload: WebsiteThemeConfigurationCreate,
    *,
    _commit_changes: bool = True,
) -> WebsiteThemeConfiguration:
    website = _website(session, website_id)
    version = _theme_family_version(session, payload.theme_family_version_id)
    _validate_family_version(session, version)
    if version.lifecycle_status != "preview_candidate" or version.production_ready:
        raise ThemeConfigurationError(
            "This route creates only inactive preview-candidate Website drafts."
        )

    predecessor = None
    next_version = 1
    if payload.supersedes_configuration_id is not None:
        predecessor = _website_configuration(
            session,
            payload.supersedes_configuration_id,
            for_update=True,
        )
        _validate_website_configuration(session, predecessor)
        if (
            predecessor.website_id != website_id
            or predecessor.theme_family_version_id != version.id
            or predecessor.configuration_key != payload.configuration_key
            or predecessor.lifecycle_status not in {"draft", "approved"}
        ):
            raise ThemeConfigurationError(
                "Website Theme configuration supersession crosses scope or lifecycle."
            )
        next_version = predecessor.version + 1

    fingerprint = _website_configuration_fingerprint(
        website_id=website_id,
        business_id=website.business_id,
        theme_family_version_id=_required_id(version),
        configuration_key=payload.configuration_key,
        version=next_version,
        lifecycle_status="draft",
        created_by=payload.created_by,
        updated_by=payload.created_by,
        creation_rationale=payload.creation_rationale,
        approved_by=None,
        approved_at=None,
        activated_by=None,
        activated_at=None,
        rollback_by=None,
        rollback_at=None,
        materialized_theme_id=None,
        website_theme_selection_id=None,
        supersedes_configuration_id=(predecessor.id if predecessor else None),
    )

    existing = session.exec(
        select(WebsiteThemeConfiguration).where(
            WebsiteThemeConfiguration.website_id == website_id,
            WebsiteThemeConfiguration.theme_family_version_id == version.id,
            WebsiteThemeConfiguration.configuration_key == payload.configuration_key,
            WebsiteThemeConfiguration.version == next_version,
        )
    ).first()
    if existing:
        _validate_website_configuration(session, existing)
        if existing.integrity_fingerprint != fingerprint:
            raise ThemeConfigurationError(
                "Website Theme configuration version already exists with different evidence."
            )
        return existing

    if predecessor:
        predecessor.lifecycle_status = "superseded"
        predecessor.updated_by = payload.created_by
        predecessor.updated_at = _utc_now()
        predecessor.integrity_fingerprint = _website_configuration_fingerprint_from_record(
            predecessor
        )
        session.add(predecessor)
        _append_audit(
            session,
            action_type="website_configuration_superseded",
            actor=payload.created_by,
            rationale=payload.creation_rationale,
            snapshot=_website_configuration_fingerprint_payload(predecessor),
            website_theme_configuration_id=_required_id(predecessor),
        )

    configuration = WebsiteThemeConfiguration(
        website_id=website_id,
        business_id=website.business_id,
        theme_family_version_id=_required_id(version),
        configuration_key=payload.configuration_key,
        version=next_version,
        lifecycle_status="draft",
        created_by=payload.created_by,
        updated_by=payload.created_by,
        creation_rationale=payload.creation_rationale,
        supersedes_configuration_id=(predecessor.id if predecessor else None),
        integrity_fingerprint=fingerprint,
    )
    session.add(configuration)
    session.flush()
    _append_audit(
        session,
        action_type=(
            "website_configuration_revision_created"
            if predecessor is not None
            else "website_draft_created"
        ),
        actor=payload.created_by,
        rationale=payload.creation_rationale,
        snapshot=_website_configuration_fingerprint_payload(configuration),
        website_theme_configuration_id=_required_id(configuration),
    )
    if _commit_changes:
        _commit(session)
        session.refresh(configuration)
    else:
        session.flush()
    return configuration


def create_inactive_theme_draft_bundle(
    session: Session,
    website_id: int,
    payload: ThemeDraftBundleCreate,
) -> ThemeDraftPreviewRead:
    """Atomically create the complete inactive family/version/draft/component graph.

    All caller-controlled schemas and existing scope identities are validated
    before the first row is added. The family, version, Website draft, exact
    three component records, and their audits then share one commit boundary.
    Any failure rolls the entire newly created graph back.
    """

    try:
        _prevalidate_draft_bundle(session, website_id, payload)
        family = register_theme_family(
            session,
            payload.theme_family,
            _commit_changes=False,
        )
        family_version = register_theme_family_version(
            session,
            _required_id(family),
            payload.theme_version,
            _commit_changes=False,
        )
        configuration = create_website_theme_configuration(
            session,
            website_id,
            WebsiteThemeConfigurationCreate(
                theme_family_version_id=_required_id(family_version),
                configuration_key=payload.website_configuration.configuration_key,
                created_by=payload.website_configuration.created_by,
                creation_rationale=payload.website_configuration.creation_rationale,
            ),
            _commit_changes=False,
        )

        by_key = {item.component_key: item for item in payload.components}
        ordered = [
            by_key["compact_estimate_form"],
            by_key["campaign_banner"],
            by_key["sticky_mobile_action_bar"],
        ]
        created_by_instance: dict[str, WebsiteThemeComponentConfiguration] = {}
        for specification in ordered:
            destination = (
                created_by_instance.get(
                    specification.destination_component_instance_key or ""
                )
                if specification.destination_component_instance_key
                else None
            )
            if specification.destination_component_instance_key and destination is None:
                raise ThemeConfigurationError(
                    "Atomic Theme draft component destination was not created in dependency order."
                )
            component = create_component_configuration(
                session,
                website_id,
                _required_id(configuration),
                WebsiteThemeComponentConfigurationCreate(
                    component_instance_key=specification.component_instance_key,
                    component_key=specification.component_key,
                    component_contract_version=specification.component_contract_version,
                    scope_type=specification.scope_type,
                    planned_page_id=specification.planned_page_id,
                    enabled=specification.enabled,
                    variant=specification.variant,
                    placement=specification.placement,
                    responsive_visibility=specification.responsive_visibility,
                    configuration_payload=specification.configuration_payload,
                    effective_at=specification.effective_at,
                    expires_at=specification.expires_at,
                    approval_identity=specification.approval_identity,
                    created_by=specification.created_by,
                    destination_component_configuration_id=(
                        _required_id(destination) if destination else None
                    ),
                    overrides_component_configuration_id=(
                        specification.overrides_component_configuration_id
                    ),
                ),
                _commit_changes=False,
            )
            created_by_instance[specification.component_instance_key] = component

        preview = read_theme_draft_preview(
            session,
            website_id,
            _required_id(configuration),
        )
        _commit(session)
        return preview
    except Exception:
        session.rollback()
        raise


def create_component_configuration(
    session: Session,
    website_id: int,
    configuration_id: int,
    payload: WebsiteThemeComponentConfigurationCreate,
    *,
    _commit_changes: bool = True,
) -> WebsiteThemeComponentConfiguration:
    configuration = _website_configuration(session, configuration_id, for_update=True)
    _validate_website_configuration(session, configuration)
    _require_configuration_scope(configuration, website_id)
    _require_inactive_draft(configuration)
    family_version = _theme_family_version(
        session,
        configuration.theme_family_version_id,
    )
    _validate_family_version(session, family_version)
    _validate_component_contract(family_version, payload)
    _validate_planned_page_scope(
        session,
        website_id=website_id,
        scope_type=payload.scope_type,
        planned_page_id=payload.planned_page_id,
    )
    override_target = _validate_override_target(
        session,
        configuration=configuration,
        component_key=payload.component_key,
        component_contract_version=payload.component_contract_version,
        scope_type=payload.scope_type,
        overrides_component_configuration_id=payload.overrides_component_configuration_id,
    )
    destination = _validate_destination(
        session,
        configuration=configuration,
        component_key=payload.component_key,
        destination_id=payload.destination_component_configuration_id,
    )
    normalized_payload = validate_component_payload(
        payload.component_key,
        payload.configuration_payload,
        payload.component_contract_version,
    )
    _validate_component_approval_identity(
        payload.component_key,
        normalized_payload,
        payload.approval_identity,
    )
    _validate_provider_state(
        payload.component_key,
        normalized_payload,
        payload.component_contract_version,
    )

    fingerprint = _component_fingerprint(
        website_theme_configuration_id=configuration_id,
        website_id=website_id,
        planned_page_id=payload.planned_page_id,
        theme_family_version_id=configuration.theme_family_version_id,
        component_instance_key=payload.component_instance_key,
        component_key=payload.component_key,
        component_contract_version=payload.component_contract_version,
        revision=1,
        scope_type=payload.scope_type,
        lifecycle_status="current",
        enabled=payload.enabled,
        variant=payload.variant,
        placement=payload.placement,
        responsive_visibility=payload.responsive_visibility.model_dump(mode="json"),
        configuration_payload=normalized_payload,
        effective_at=payload.effective_at,
        expires_at=payload.expires_at,
        approval_identity=payload.approval_identity,
        created_by=payload.created_by,
        updated_by=payload.created_by,
        activation_identity=None,
        activated_at=None,
        rollback_identity=None,
        rollback_at=None,
        destination_component_configuration_id=(destination.id if destination else None),
        overrides_component_configuration_id=(override_target.id if override_target else None),
        supersedes_component_configuration_id=None,
    )
    existing_statement = select(WebsiteThemeComponentConfiguration).where(
        WebsiteThemeComponentConfiguration.website_theme_configuration_id
        == configuration_id,
        WebsiteThemeComponentConfiguration.lifecycle_status == "current",
    )
    if payload.scope_type == "website_default":
        existing_statement = existing_statement.where(
            WebsiteThemeComponentConfiguration.scope_type == "website_default",
            WebsiteThemeComponentConfiguration.component_instance_key
            == payload.component_instance_key,
        )
    else:
        existing_statement = existing_statement.where(
            WebsiteThemeComponentConfiguration.scope_type == "page_override",
            WebsiteThemeComponentConfiguration.planned_page_id == payload.planned_page_id,
            WebsiteThemeComponentConfiguration.overrides_component_configuration_id
            == payload.overrides_component_configuration_id,
        )
    existing = session.exec(existing_statement).first()
    if existing:
        _validate_component_configuration(session, existing)
        if existing.integrity_fingerprint != fingerprint:
            raise ThemeConfigurationError(
                "Component instance already has a different current configuration."
            )
        return existing

    component = WebsiteThemeComponentConfiguration(
        website_theme_configuration_id=configuration_id,
        website_id=website_id,
        planned_page_id=payload.planned_page_id,
        theme_family_version_id=configuration.theme_family_version_id,
        component_instance_key=payload.component_instance_key,
        component_key=payload.component_key,
        component_contract_version=payload.component_contract_version,
        revision=1,
        scope_type=payload.scope_type,
        lifecycle_status="current",
        enabled=payload.enabled,
        variant=payload.variant,
        placement=payload.placement,
        responsive_visibility=payload.responsive_visibility.model_dump(mode="json"),
        configuration_payload=normalized_payload,
        effective_at=payload.effective_at,
        expires_at=payload.expires_at,
        approval_identity=payload.approval_identity,
        created_by=payload.created_by,
        updated_by=payload.created_by,
        destination_component_configuration_id=(destination.id if destination else None),
        overrides_component_configuration_id=(override_target.id if override_target else None),
        integrity_fingerprint=fingerprint,
    )
    session.add(component)
    session.flush()
    _append_audit(
        session,
        action_type="component_created",
        actor=payload.created_by,
        rationale="Create an inactive Website Theme component configuration.",
        snapshot=_component_fingerprint_payload(component),
        component_configuration_id=_required_id(component),
    )
    if _commit_changes:
        _commit(session)
        session.refresh(component)
    else:
        session.flush()
    return component


def revise_component_configuration(
    session: Session,
    website_id: int,
    configuration_id: int,
    component_configuration_id: int,
    payload: WebsiteThemeComponentConfigurationRevisionCreate,
) -> WebsiteThemeComponentConfiguration:
    configuration = _website_configuration(session, configuration_id, for_update=True)
    _validate_website_configuration(session, configuration)
    _require_configuration_scope(configuration, website_id)
    _require_inactive_draft(configuration)
    current = _component_configuration(
        session,
        component_configuration_id,
        for_update=True,
    )
    _validate_component_configuration(session, current)
    if (
        current.website_theme_configuration_id != configuration_id
        or current.website_id != website_id
        or current.lifecycle_status != "current"
    ):
        raise ThemeConfigurationError(
            "Component revision crosses Website/configuration scope or is not current."
        )
    dependent = session.exec(
        select(WebsiteThemeComponentConfiguration).where(
            WebsiteThemeComponentConfiguration.website_theme_configuration_id
            == configuration_id,
            WebsiteThemeComponentConfiguration.lifecycle_status == "current",
            or_(
                WebsiteThemeComponentConfiguration.destination_component_configuration_id
                == component_configuration_id,
                WebsiteThemeComponentConfiguration.overrides_component_configuration_id
                == component_configuration_id,
            ),
        )
    ).first()
    if dependent is not None:
        raise ThemeConfigurationError(
            "A component with current conversion or Page-override dependents requires "
            "a future atomic coordinated revision."
        )

    create_shape = WebsiteThemeComponentConfigurationCreate(
        component_instance_key=current.component_instance_key,
        component_key=current.component_key,
        component_contract_version=current.component_contract_version,
        scope_type=current.scope_type,
        planned_page_id=current.planned_page_id,
        enabled=payload.enabled,
        variant=payload.variant,
        placement=payload.placement,
        responsive_visibility=payload.responsive_visibility,
        configuration_payload=payload.configuration_payload,
        effective_at=payload.effective_at,
        expires_at=payload.expires_at,
        approval_identity=payload.approval_identity,
        created_by=payload.updated_by,
        destination_component_configuration_id=payload.destination_component_configuration_id,
        overrides_component_configuration_id=current.overrides_component_configuration_id,
    )
    family_version = _theme_family_version(
        session,
        configuration.theme_family_version_id,
    )
    _validate_component_contract(family_version, create_shape)
    destination = _validate_destination(
        session,
        configuration=configuration,
        component_key=current.component_key,
        destination_id=payload.destination_component_configuration_id,
    )
    normalized_payload = validate_component_payload(
        current.component_key,
        payload.configuration_payload,
        current.component_contract_version,
    )
    _validate_component_approval_identity(
        current.component_key,
        normalized_payload,
        payload.approval_identity,
    )
    _validate_provider_state(
        current.component_key,
        normalized_payload,
        current.component_contract_version,
    )

    next_revision = current.revision + 1
    current.lifecycle_status = "superseded"
    current.updated_by = payload.updated_by
    current.updated_at = _utc_now()
    current.integrity_fingerprint = _component_fingerprint_from_record(current)
    session.add(current)

    replacement = WebsiteThemeComponentConfiguration(
        website_theme_configuration_id=configuration_id,
        website_id=website_id,
        planned_page_id=current.planned_page_id,
        theme_family_version_id=current.theme_family_version_id,
        component_instance_key=current.component_instance_key,
        component_key=current.component_key,
        component_contract_version=current.component_contract_version,
        revision=next_revision,
        scope_type=current.scope_type,
        lifecycle_status="current",
        enabled=payload.enabled,
        variant=payload.variant,
        placement=payload.placement,
        responsive_visibility=payload.responsive_visibility.model_dump(mode="json"),
        configuration_payload=normalized_payload,
        effective_at=payload.effective_at,
        expires_at=payload.expires_at,
        approval_identity=payload.approval_identity,
        created_by=payload.updated_by,
        updated_by=payload.updated_by,
        destination_component_configuration_id=(destination.id if destination else None),
        overrides_component_configuration_id=current.overrides_component_configuration_id,
        supersedes_component_configuration_id=_required_id(current),
        integrity_fingerprint="0" * 64,
    )
    replacement.integrity_fingerprint = _component_fingerprint_from_record(replacement)
    session.add(replacement)
    session.flush()
    _append_audit(
        session,
        action_type="component_superseded",
        actor=payload.updated_by,
        rationale=payload.revision_rationale,
        snapshot=_component_fingerprint_payload(current),
        component_configuration_id=_required_id(current),
    )
    _append_audit(
        session,
        action_type="component_revision_created",
        actor=payload.updated_by,
        rationale=payload.revision_rationale,
        snapshot=_component_fingerprint_payload(replacement),
        component_configuration_id=_required_id(replacement),
    )
    _commit(session)
    session.refresh(replacement)
    return replacement


def revise_conversion_component_graph(
    session: Session,
    website_id: int,
    configuration_id: int,
    payload: ConversionComponentGraphRevisionCreate,
) -> ConversionComponentGraphRevisionRead:
    """Atomically supersede the exact form/banner/sticky conversion graph."""

    try:
        return _revise_conversion_component_graph(
            session,
            website_id,
            configuration_id,
            payload,
        )
    except Exception:
        session.rollback()
        raise


def _revise_conversion_component_graph(
    session: Session,
    website_id: int,
    configuration_id: int,
    payload: ConversionComponentGraphRevisionCreate,
) -> ConversionComponentGraphRevisionRead:

    configuration = _website_configuration(session, configuration_id, for_update=True)
    _validate_website_configuration(session, configuration)
    _require_configuration_scope(configuration, website_id)
    _require_inactive_draft(configuration)
    by_key = {
        "compact_estimate_form": _component_configuration(
            session,
            payload.form_component_configuration_id,
            for_update=True,
        ),
        "campaign_banner": _component_configuration(
            session,
            payload.banner_component_configuration_id,
            for_update=True,
        ),
        "sticky_mobile_action_bar": _component_configuration(
            session,
            payload.sticky_component_configuration_id,
            for_update=True,
        ),
    }
    if len({_required_id(item) for item in by_key.values()}) != 3:
        raise ThemeConfigurationError("Atomic conversion revision requires three distinct components.")
    for expected_key, component in by_key.items():
        _validate_component_configuration(session, component)
        if (
            component.website_theme_configuration_id != configuration_id
            or component.website_id != website_id
            or component.theme_family_version_id
            != configuration.theme_family_version_id
            or component.component_key != expected_key
            or component.lifecycle_status != "current"
            or component.scope_type != "website_default"
        ):
            raise ThemeConfigurationError(
                "Atomic conversion revision crosses scope or does not target the exact current graph."
            )

    form = by_key["compact_estimate_form"]
    banner = by_key["campaign_banner"]
    sticky = by_key["sticky_mobile_action_bar"]
    if (
        form.destination_component_configuration_id is not None
        or banner.destination_component_configuration_id != form.id
        or sticky.destination_component_configuration_id != form.id
    ):
        raise ThemeConfigurationError(
            "Atomic conversion revision requires banner and sticky actions to target the exact form."
        )
    graph_ids = {_required_id(form), _required_id(banner), _required_id(sticky)}
    outside_dependent = session.exec(
        select(WebsiteThemeComponentConfiguration).where(
            WebsiteThemeComponentConfiguration.website_theme_configuration_id
            == configuration_id,
            WebsiteThemeComponentConfiguration.lifecycle_status == "current",
            WebsiteThemeComponentConfiguration.id.notin_(graph_ids),
            or_(
                WebsiteThemeComponentConfiguration.destination_component_configuration_id.in_(
                    graph_ids
                ),
                WebsiteThemeComponentConfiguration.overrides_component_configuration_id.in_(
                    graph_ids
                ),
            ),
        )
    ).first()
    if outside_dependent is not None:
        raise ThemeConfigurationError(
            "Atomic conversion revision cannot strand a current Page override or outside dependency."
        )

    revisions = {
        "compact_estimate_form": payload.form_revision,
        "campaign_banner": payload.banner_revision,
        "sticky_mobile_action_bar": payload.sticky_revision,
    }
    for key, revision in revisions.items():
        expected_destination = None if key == "compact_estimate_form" else form.id
        if revision.destination_component_configuration_id != expected_destination:
            raise ThemeConfigurationError(
                "Atomic conversion revision must bind action intent to the current exact form; "
                "the service binds replacements to the new form identity."
            )
        current = by_key[key]
        create_shape = WebsiteThemeComponentConfigurationCreate(
            component_instance_key=current.component_instance_key,
            component_key=current.component_key,
            component_contract_version=current.component_contract_version,
            scope_type=current.scope_type,
            planned_page_id=current.planned_page_id,
            enabled=revision.enabled,
            variant=revision.variant,
            placement=revision.placement,
            responsive_visibility=revision.responsive_visibility,
            configuration_payload=revision.configuration_payload,
            effective_at=revision.effective_at,
            expires_at=revision.expires_at,
            approval_identity=revision.approval_identity,
            created_by=revision.updated_by,
            destination_component_configuration_id=expected_destination,
            overrides_component_configuration_id=current.overrides_component_configuration_id,
        )
        family_version = _theme_family_version(
            session,
            configuration.theme_family_version_id,
        )
        _validate_component_contract(family_version, create_shape)
        normalized = validate_component_payload(
            key,
            revision.configuration_payload,
            current.component_contract_version,
        )
        _validate_component_approval_identity(
            key,
            normalized,
            revision.approval_identity,
        )
        _validate_provider_state(key, normalized, current.component_contract_version)

    transitioned_at = _utc_now()
    for key, current in by_key.items():
        current.lifecycle_status = "superseded"
        current.updated_by = revisions[key].updated_by
        current.updated_at = transitioned_at
        current.integrity_fingerprint = _component_fingerprint_from_record(current)
        session.add(current)

    replacements: dict[str, WebsiteThemeComponentConfiguration] = {}
    for key in (
        "compact_estimate_form",
        "campaign_banner",
        "sticky_mobile_action_bar",
    ):
        current = by_key[key]
        revision = revisions[key]
        normalized = validate_component_payload(
            key,
            revision.configuration_payload,
            current.component_contract_version,
        )
        destination = (
            None
            if key == "compact_estimate_form"
            else _required_id(replacements["compact_estimate_form"])
        )
        replacement = WebsiteThemeComponentConfiguration(
            website_theme_configuration_id=configuration_id,
            website_id=website_id,
            planned_page_id=current.planned_page_id,
            theme_family_version_id=current.theme_family_version_id,
            component_instance_key=current.component_instance_key,
            component_key=current.component_key,
            component_contract_version=current.component_contract_version,
            revision=current.revision + 1,
            scope_type=current.scope_type,
            lifecycle_status="current",
            enabled=revision.enabled,
            variant=revision.variant,
            placement=revision.placement,
            responsive_visibility=revision.responsive_visibility.model_dump(mode="json"),
            configuration_payload=normalized,
            effective_at=revision.effective_at,
            expires_at=revision.expires_at,
            approval_identity=revision.approval_identity,
            created_by=revision.updated_by,
            updated_by=revision.updated_by,
            destination_component_configuration_id=destination,
            overrides_component_configuration_id=current.overrides_component_configuration_id,
            supersedes_component_configuration_id=_required_id(current),
            integrity_fingerprint="0" * 64,
        )
        replacement.integrity_fingerprint = _component_fingerprint_from_record(replacement)
        session.add(replacement)
        session.flush()
        replacements[key] = replacement

    for key, current in by_key.items():
        revision = revisions[key]
        replacement = replacements[key]
        _append_audit(
            session,
            action_type="component_superseded",
            actor=revision.updated_by,
            rationale=revision.revision_rationale,
            snapshot=_component_fingerprint_payload(current),
            component_configuration_id=_required_id(current),
        )
        _append_audit(
            session,
            action_type="component_revision_created",
            actor=revision.updated_by,
            rationale=revision.revision_rationale,
            snapshot=_component_fingerprint_payload(replacement),
            component_configuration_id=_required_id(replacement),
        )
    _commit(session)
    for replacement in replacements.values():
        session.refresh(replacement)
    return ConversionComponentGraphRevisionRead(
        form=WebsiteThemeComponentConfigurationRead.model_validate(
            replacements["compact_estimate_form"]
        ),
        banner=WebsiteThemeComponentConfigurationRead.model_validate(
            replacements["campaign_banner"]
        ),
        sticky=WebsiteThemeComponentConfigurationRead.model_validate(
            replacements["sticky_mobile_action_bar"]
        ),
    )


def list_theme_families(session: Session) -> list[ThemeFamily]:
    families = list(session.exec(select(ThemeFamily).order_by(ThemeFamily.family_key)).all())
    for family in families:
        _validate_family(family)
    return families


def list_theme_family_versions(
    session: Session,
    theme_family_id: int,
) -> list[ThemeFamilyVersion]:
    family = _theme_family(session, theme_family_id)
    _validate_family(family)
    versions = list(
        session.exec(
            select(ThemeFamilyVersion)
            .where(ThemeFamilyVersion.theme_family_id == theme_family_id)
            .order_by(ThemeFamilyVersion.version)
        ).all()
    )
    for version in versions:
        _validate_family_version(session, version)
    return versions


def list_website_theme_configurations(
    session: Session,
    website_id: int,
    *,
    family_key: str | None = None,
    family_version: int | None = None,
    lifecycle_status: str | None = None,
) -> list[WebsiteThemeConfiguration]:
    _website(session, website_id)
    statement = (
        select(WebsiteThemeConfiguration)
        .join(
            ThemeFamilyVersion,
            ThemeFamilyVersion.id
            == WebsiteThemeConfiguration.theme_family_version_id,
        )
        .join(ThemeFamily, ThemeFamily.id == ThemeFamilyVersion.theme_family_id)
        .where(WebsiteThemeConfiguration.website_id == website_id)
    )
    if family_key is not None:
        statement = statement.where(ThemeFamily.family_key == family_key)
    if family_version is not None:
        statement = statement.where(ThemeFamilyVersion.version == family_version)
    if lifecycle_status is not None:
        statement = statement.where(
            WebsiteThemeConfiguration.lifecycle_status == lifecycle_status
        )
    rows = list(
        session.exec(
            statement.order_by(
                WebsiteThemeConfiguration.configuration_key,
                WebsiteThemeConfiguration.version,
            )
        ).all()
    )
    for row in rows:
        _validate_website_configuration(session, row)
    return rows


def read_theme_draft_preview_by_family(
    session: Session,
    website_id: int,
    *,
    family_key: str,
    family_version: int,
    page_id: int | None = None,
) -> ThemeDraftPreviewRead:
    matches = list_website_theme_configurations(
        session,
        website_id,
        family_key=family_key,
        family_version=family_version,
        lifecycle_status="draft",
    )
    if not matches:
        raise ThemeConfigurationError(
            "No current inactive Website Theme draft matches the requested family identity.",
            status_code=404,
            code="theme_draft_not_found",
        )
    if len(matches) != 1:
        raise ThemeConfigurationError(
            "Multiple current inactive Website Theme drafts match the requested family identity."
        )
    return read_theme_draft_preview(
        session,
        website_id,
        _required_id(matches[0]),
        page_id=page_id,
    )


def read_theme_draft_preview(
    session: Session,
    website_id: int,
    configuration_id: int,
    *,
    page_id: int | None = None,
) -> ThemeDraftPreviewRead:
    website = _website(session, website_id)
    configuration = _website_configuration(session, configuration_id)
    _validate_website_configuration(session, configuration)
    _require_configuration_scope(configuration, website_id)
    _require_inactive_draft(configuration)
    family_version = _theme_family_version(
        session,
        configuration.theme_family_version_id,
    )
    _validate_family_version(session, family_version)
    family = _theme_family(session, family_version.theme_family_id)
    _validate_family(family)
    if family_version.lifecycle_status != "preview_candidate" or family_version.production_ready:
        raise ThemeConfigurationError(
            "Draft preview accepts only a non-production preview-candidate Theme Version."
        )

    planned_page_id = _preview_planned_page_id(
        session,
        website_id=website_id,
        generated_page_id=page_id,
    )
    all_components = list(
        session.exec(
            select(WebsiteThemeComponentConfiguration)
            .where(
                WebsiteThemeComponentConfiguration.website_theme_configuration_id
                == configuration_id,
                WebsiteThemeComponentConfiguration.lifecycle_status == "current",
            )
            .order_by(
                WebsiteThemeComponentConfiguration.component_key,
                WebsiteThemeComponentConfiguration.component_instance_key,
            )
        ).all()
    )
    for component in all_components:
        _validate_component_configuration(session, component)
    components = _resolve_components_for_page(
        all_components,
        planned_page_id,
        evaluated_at=_utc_now(),
    )
    _validate_preview_components(session, configuration, components)

    estimate_destinations = {
        item.destination_component_configuration_id
        for item in components
        if item.enabled and item.destination_component_configuration_id is not None
    }
    if len(estimate_destinations) > 1:
        raise ThemeConfigurationError(
            "Draft conversion actions resolve to more than one compact-form target."
        )
    sticky_actions = [
        item
        for item in components
        if item.enabled and item.component_key == "sticky_mobile_action_bar"
    ]
    if len(sticky_actions) > 1:
        raise ThemeConfigurationError(
            "Draft preview resolves more than one sticky conversion-action policy."
        )
    sticky_action = sticky_actions[0] if sticky_actions else None
    sticky_payload = (
        validate_component_payload(
            sticky_action.component_key,
            sticky_action.configuration_payload,
            sticky_action.component_contract_version,
        )
        if sticky_action is not None
        else None
    )
    sticky_destination = (
        sticky_action.destination_component_configuration_id
        if sticky_action is not None
        else None
    )
    desktop_header_actions_enabled = bool(
        sticky_payload and sticky_payload["desktop_sticky_header"]
    )
    mobile_sticky_actions_enabled = bool(
        sticky_payload and sticky_payload["mobile_sticky_bottom"]
    )
    phone_display, call_destination = _governed_phone(session, website)
    audits = _audit_history(
        session,
        family=family,
        family_version=family_version,
        website_configuration=configuration,
        component_ids={_required_id(item) for item in components},
    )
    _require_audit_coverage(
        session,
        families=[family],
        versions=[family_version],
        configurations=[configuration],
        components=components,
    )
    readiness = theme_activation_readiness(
        session,
        website_id,
        configuration_id,
    )
    return ThemeDraftPreviewRead(
        preview_label="DRAFT PREVIEW — NOT ACTIVE",
        theme_family=ThemeFamilyRead.model_validate(family),
        theme_version=ThemeFamilyVersionRead.model_validate(family_version),
        website_configuration=WebsiteThemeConfigurationRead.model_validate(
            configuration
        ),
        components=[
            WebsiteThemeComponentConfigurationRead.model_validate(item)
            for item in components
        ],
        audit_history=[ThemeConfigurationAuditRead.model_validate(item) for item in audits],
        governed_actions=GovernedThemeActionsRead(
            phone_display=phone_display,
            call_destination=call_destination,
            call_label=(sticky_payload["call_label"] if sticky_payload else None),
            estimate_label=(
                sticky_payload["estimate_label"] if sticky_payload else None
            ),
            estimate_destination_component_configuration_id=(
                next(iter(estimate_destinations)) if estimate_destinations else None
            ),
            desktop_header_actions_enabled=desktop_header_actions_enabled,
            mobile_sticky_actions_enabled=mobile_sticky_actions_enabled,
            desktop_header_estimate_destination_component_configuration_id=(
                sticky_destination if desktop_header_actions_enabled else None
            ),
            mobile_sticky_estimate_destination_component_configuration_id=(
                sticky_destination if mobile_sticky_actions_enabled else None
            ),
        ),
        provider_state=provider_disabled_state(),
        readiness=readiness,
        requested_generated_page_id=page_id,
        export_eligible=False,
        publication_status="blocked",
        deployment_status="blocked",
    )


def theme_activation_readiness(
    session: Session,
    website_id: int,
    configuration_id: int,
) -> ThemeActivationReadinessRead:
    configuration = _website_configuration(session, configuration_id)
    _validate_website_configuration(session, configuration)
    _require_configuration_scope(configuration, website_id)
    version = _theme_family_version(session, configuration.theme_family_version_id)
    _validate_family_version(session, version)
    items = [
        ThemeActivationReadinessItem(
            key="production_ready",
            label="Production-ready Theme Version",
            reason="The durable Theme Version remains preview_candidate with productionReady false.",
        ),
        ThemeActivationReadinessItem(
            key="production_theme_selection",
            label="Active governed Website Theme selection",
            reason="The inactive draft is not materialized as an approved Theme or active selection.",
        ),
        ThemeActivationReadinessItem(
            key="production_renderer",
            label="Production renderer integration",
            reason="Theme Lab is an isolated local draft preview, not a production renderer.",
        ),
        ThemeActivationReadinessItem(
            key="export_integration",
            label="Canonical public export integration",
            reason="Draft and preview-candidate configuration is excluded from public export.",
        ),
        ThemeActivationReadinessItem(
            key="form_provider",
            label="Submission provider and destination",
            reason="The compact form remains disabled pending provider configuration.",
        ),
        ThemeActivationReadinessItem(
            key="privacy_and_consent",
            label="Privacy, consent, retention, and abuse controls",
            reason="Production privacy and submission controls are not configured or approved.",
        ),
        ThemeActivationReadinessItem(
            key="publication_authorization",
            label="Publication authorization",
            reason="No publication authorization exists for this draft.",
        ),
        ThemeActivationReadinessItem(
            key="deployment_authorization",
            label="Deployment authorization",
            reason="No deployment authorization exists for this draft.",
        ),
    ]
    return ThemeActivationReadinessRead(
        status="blocked",
        can_activate=False,
        can_publish=False,
        can_deploy=False,
        production_ready=False,
        incomplete_items=items,
    )


def require_theme_configuration_export_eligible(
    session: Session,
    website_id: int,
    configuration_id: int,
    *,
    generated_page_id: int,
) -> ThemeConfigurationExportEligibilityRead | PerformanceLocalV3ExportEligibilityRead:
    """Return the exact active Page-scoped export graph or fail closed."""

    configuration = _website_configuration(session, configuration_id)
    _validate_website_configuration(session, configuration)
    _require_configuration_scope(configuration, website_id)
    version = _theme_family_version(session, configuration.theme_family_version_id)
    _validate_family_version(session, version)
    family = _theme_family(session, version.theme_family_id)
    _validate_family(family)
    if (
        configuration.lifecycle_status != "active"
        or not version.production_ready
        or version.lifecycle_status != "approved"
        or configuration.materialized_theme_id is None
        or configuration.website_theme_selection_id is None
    ):
        raise ThemeConfigurationError(
            "Draft or preview-candidate Theme configuration is not eligible for public export.",
            code="theme_configuration_export_blocked",
        )
    theme = session.get(Theme, configuration.materialized_theme_id)
    selection = session.get(
        WebsiteThemeSelection,
        configuration.website_theme_selection_id,
    )
    if (
        theme is None
        or selection is None
        or theme.website_id != website_id
        or selection.website_id != website_id
        or selection.theme_id != theme.id
        or selection.status != "active"
        or theme.lifecycle_status != "available"
        or theme.approval_status != "approved"
    ):
        raise ThemeConfigurationError(
            "Theme configuration does not bind the exact active approved Website Theme selection.",
            code="theme_configuration_export_blocked",
        )
    planned_page_id = _preview_planned_page_id(
        session,
        website_id=website_id,
        generated_page_id=generated_page_id,
    )
    if planned_page_id is None:  # pragma: no cover - generated_page_id is required
        raise ThemeConfigurationError("Public export requires one exact Planned Page target.")
    all_components = list(
        session.exec(
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
        ).all()
    )
    for component in all_components:
        _validate_component_configuration(session, component)
    resolved = _resolve_components_for_page(
        all_components,
        planned_page_id,
        evaluated_at=_utc_now(),
    )
    effective_components = [item for item in resolved if item.enabled]
    _validate_preview_components(session, configuration, effective_components)
    if any(
        item.activation_identity is None
        or item.activated_at is None
        or item.rollback_identity is not None
        or item.rollback_at is not None
        for item in effective_components
    ):
        raise ThemeConfigurationError(
            "Public export requires every enabled effective Theme component to have exact non-rolled-back activation evidence.",
            code="theme_configuration_export_blocked",
        )
    _require_audit_coverage(
        session,
        families=[family],
        versions=[version],
        configurations=[configuration],
        components=effective_components,
    )
    audits = _audit_history(
        session,
        family=family,
        family_version=version,
        website_configuration=configuration,
        component_ids={_required_id(item) for item in effective_components},
    )
    form_readiness = None
    if family.family_key == "performance-local" and version.version == 3:
        from app.services import page_composition as composition_service
        from app.services.form_submission_gateway import evaluate_form_readiness
        from app.services.page_qa import effective_page_qa_state

        page = session.get(GeneratedPage, generated_page_id)
        compositions = list(
            session.exec(
                select(PageComposition).where(
                    PageComposition.generated_page_id == generated_page_id
                )
            ).all()
        )
        if (
            page is None
            or page.website_id != website_id
            or len(compositions) != 1
            or compositions[0].status != "current"
        ):
            raise ThemeConfigurationError(
                "Public V3 export requires one persisted current Page Composition.",
                code="theme_configuration_export_blocked",
            )
        try:
            composition_service._read(
                session,
                compositions[0],
                require_current=True,
            )
        except composition_service.PageCompositionError as exc:
            raise ThemeConfigurationError(
                "Public V3 export requires a recomputed current Page Composition.",
                code="theme_configuration_export_blocked",
            ) from exc
        if not effective_page_qa_state(session, page).ready:
            raise ThemeConfigurationError(
                "Public V3 export requires exact current ready Page QA evidence.",
                code="theme_configuration_export_blocked",
            )

        forms = [
            item
            for item in effective_components
            if item.component_key == "compact_estimate_form"
        ]
        if len(forms) != 1:
            raise ThemeConfigurationError(
                "Public export requires one exact governed V3 form.",
                code="theme_configuration_export_blocked",
            )
        form_readiness = evaluate_form_readiness(forms[0], mode="active")
        if not form_readiness.can_submit:
            raise ThemeConfigurationError(
                "Public export requires complete provider, privacy, consent, retention, spam, security, and audit readiness.",
                code="theme_configuration_export_blocked",
            )
    banner = next(
        (
            item
            for item in effective_components
            if item.component_key == "campaign_banner"
        ),
        None,
    )
    sticky = next(
        (
            item
            for item in effective_components
            if item.component_key == "sticky_mobile_action_bar"
        ),
        None,
    )
    identity_values = dict(
        website_id=website_id,
        business_id=configuration.business_id,
        theme_family_id=_required_id(family),
        family_key=family.family_key,
        theme_family_version_id=_required_id(version),
        family_version=version.version,
        theme_compatibility_identity=version.compatibility_identity,
        theme_family_version_integrity_fingerprint=version.integrity_fingerprint,
        website_theme_configuration_id=_required_id(configuration),
        configuration_key=configuration.configuration_key,
        configuration_version=configuration.version,
        configuration_lifecycle_status="active",
        configuration_integrity_fingerprint=configuration.integrity_fingerprint,
        theme_id=_required_id(theme),
        website_theme_selection_id=_required_id(selection),
        generated_page_id=generated_page_id,
        planned_page_id=planned_page_id,
        effective_components=[
            ThemeConfigurationExportComponentRead(
                component_configuration_id=_required_id(item),
                component_instance_key=item.component_instance_key,
                component_key=item.component_key,
                component_contract_version=item.component_contract_version,
                revision=item.revision,
                scope_type=item.scope_type,
                planned_page_id=item.planned_page_id,
                destination_component_configuration_id=(
                    item.destination_component_configuration_id
                ),
                overrides_component_configuration_id=(
                    item.overrides_component_configuration_id
                ),
                integrity_fingerprint=item.integrity_fingerprint,
            )
            for item in effective_components
        ],
        audit_snapshot_hashes=sorted(item.snapshot_hash for item in audits),
    )
    if form_readiness is None:
        return ThemeConfigurationExportEligibilityRead(**identity_values)
    return PerformanceLocalV3ExportEligibilityRead(
        **identity_values,
        activation_audit_identity=sorted(
            item.snapshot_hash
            for item in audits
            if item.action_type
            in {"website_configuration_activated", "component_activated"}
        ),
        banner_intent=(
            banner.configuration_payload.get("intent") if banner is not None else None
        ),
        sticky_action_identity=(
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
        form_state=form_readiness.submission_state,
        provider_state={
            "destination_configured": (
                form_readiness.provider_state.destination_configured
            ),
            "adapter_registered": form_readiness.provider_state.adapter_registered,
            "test_only": form_readiness.provider_state.test_only,
        },
        privacy_consent_readiness=form_readiness.privacy.model_dump(mode="json"),
    )


def validate_theme_configuration_records(session: Session) -> dict[str, int]:
    """Validate the complete durable Theme-family graph after restore or migration."""

    families = list(session.exec(select(ThemeFamily).order_by(ThemeFamily.id)).all())
    versions = list(
        session.exec(select(ThemeFamilyVersion).order_by(ThemeFamilyVersion.id)).all()
    )
    configurations = list(
        session.exec(
            select(WebsiteThemeConfiguration).order_by(WebsiteThemeConfiguration.id)
        ).all()
    )
    components = list(
        session.exec(
            select(WebsiteThemeComponentConfiguration).order_by(
                WebsiteThemeComponentConfiguration.id
            )
        ).all()
    )
    audits = list(
        session.exec(
            select(ThemeConfigurationAudit).order_by(ThemeConfigurationAudit.id)
        ).all()
    )
    for record in families:
        _validate_family(record)
    for record in versions:
        _validate_family_version(session, record)
    for record in configurations:
        _validate_website_configuration(session, record)
    for record in components:
        _validate_component_configuration(session, record)
    for record in audits:
        _validate_audit(record)
        target_model: type[Any]
        target_id: int
        if record.theme_family_id is not None:
            target_model, target_id = ThemeFamily, record.theme_family_id
        elif record.theme_family_version_id is not None:
            target_model, target_id = ThemeFamilyVersion, record.theme_family_version_id
        elif record.website_theme_configuration_id is not None:
            target_model, target_id = (
                WebsiteThemeConfiguration,
                record.website_theme_configuration_id,
            )
        elif record.component_configuration_id is not None:
            target_model, target_id = (
                WebsiteThemeComponentConfiguration,
                record.component_configuration_id,
            )
        else:  # pragma: no cover - guarded by _validate_audit
            raise ThemeConfigurationError("Theme configuration audit has no target.")
        if session.get(target_model, target_id) is None:
            raise ThemeConfigurationError(
                "Theme configuration audit references a missing durable target."
            )
    _require_audit_coverage(
        session,
        families=families,
        versions=versions,
        configurations=configurations,
        components=components,
    )
    return {
        "theme_families": len(families),
        "theme_family_versions": len(versions),
        "website_theme_configurations": len(configurations),
        "website_theme_component_configurations": len(components),
        "theme_configuration_audits": len(audits),
    }


def _prevalidate_draft_bundle(
    session: Session,
    website_id: int,
    payload: ThemeDraftBundleCreate,
) -> None:
    _website(session, website_id)
    if (
        payload.theme_family.family_key != "performance-local"
        or payload.theme_version.version != 2
        or payload.theme_version.lifecycle_status != "preview_candidate"
        or payload.theme_version.production_ready
        or payload.theme_version.source_commit != PERFORMANCE_LOCAL_V2_SOURCE_COMMIT
    ):
        raise ThemeConfigurationError(
            "Atomic durable draft creation is limited to the exact authorized Performance Local v2 preview candidate."
        )
    contracts = [
        item.model_dump(mode="json")
        for item in payload.theme_version.supported_component_contracts
    ]
    if contracts != list(PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS):
        raise ThemeConfigurationError(
            "Atomic Performance Local v2 draft requires the complete canonical server component contract."
        )
    for specification in payload.components:
        _validate_component_contract_records(contracts, specification)
        _validate_planned_page_scope(
            session,
            website_id=website_id,
            scope_type=specification.scope_type,
            planned_page_id=specification.planned_page_id,
        )
        _validate_component_approval_identity(
            specification.component_key,
            specification.configuration_payload,
            specification.approval_identity,
        )
        _validate_provider_state(
            specification.component_key,
            specification.configuration_payload,
        )


def _validate_family(record: ThemeFamily) -> None:
    validate_fingerprint(record.integrity_fingerprint, "Theme Family fingerprint")
    _require_stored_text(record.created_by, "Theme Family creator", 160)
    try:
        ThemeFamilyCreate(
            family_key=record.family_key,
            display_name=record.display_name,
            description=record.description,
            provider_source_identity=record.provider_source_identity,
            created_by=record.created_by,
        )
    except ValueError as exc:
        raise ThemeConfigurationError(
            "Theme Family immutable creation identity is invalid."
        ) from exc
    if (record.retired_by is None) != (record.retired_at is None):
        raise ThemeConfigurationError("Theme Family retirement evidence is incomplete.")
    if record.retired_by is not None and not record.retired_by.strip():
        raise ThemeConfigurationError("Theme Family retirement actor is invalid.")
    if record.lifecycle_status == "registered" and record.retired_at is not None:
        raise ThemeConfigurationError("Registered Theme Family contains retirement evidence.")
    if record.lifecycle_status == "retired" and record.retired_at is None:
        raise ThemeConfigurationError("Retired Theme Family lacks retirement evidence.")
    _require_timestamp_order(
        record.created_at,
        record.updated_at,
        "Theme Family update precedes its creation.",
    )
    if record.retired_at is not None:
        _require_timestamp_order(
            record.created_at,
            record.retired_at,
            "Theme Family retirement precedes its creation.",
        )
    expected = _family_fingerprint_from_record(record)
    if record.integrity_fingerprint != expected:
        raise ThemeConfigurationError("Theme Family integrity fingerprint does not match.")


def _validate_family_version(session: Session, record: ThemeFamilyVersion) -> None:
    validate_fingerprint(record.compatibility_identity, "Theme compatibility identity")
    validate_fingerprint(record.integrity_fingerprint, "Theme Version fingerprint")
    _require_stored_text(record.created_by, "Theme Version creator", 160)
    try:
        ThemeFamilyVersionCreate(
            version=record.version,
            lifecycle_status="preview_candidate",
            production_ready=False,
            source_commit=record.source_commit,
            supported_component_contracts=record.supported_component_contracts,
            created_by=record.created_by,
            supersedes_theme_family_version_id=(
                record.supersedes_theme_family_version_id
            ),
        )
    except ValueError as exc:
        raise ThemeConfigurationError(
            "Theme Version immutable creation identity is invalid."
        ) from exc
    family = _theme_family(session, record.theme_family_id)
    _validate_family(family)
    if (record.retired_by is None) != (record.retired_at is None):
        raise ThemeConfigurationError("Theme Version retirement evidence is incomplete.")
    if record.retired_by is not None and not record.retired_by.strip():
        raise ThemeConfigurationError("Theme Version retirement actor is invalid.")
    if record.lifecycle_status != "retired" and record.retired_at is not None:
        raise ThemeConfigurationError("Non-retired Theme Version contains retirement evidence.")
    if record.lifecycle_status == "retired" and record.retired_at is None:
        raise ThemeConfigurationError("Retired Theme Version lacks retirement evidence.")
    _require_timestamp_order(
        record.created_at,
        record.updated_at,
        "Theme Version update precedes its creation.",
    )
    if record.retired_at is not None:
        _require_timestamp_order(
            record.created_at,
            record.retired_at,
            "Theme Version retirement precedes its creation.",
        )
    expected_compatibility = canonical_json_hash(
        {
            "family_key": family.family_key,
            "version": record.version,
            "supported_component_contracts": record.supported_component_contracts,
        }
    )
    if record.compatibility_identity != expected_compatibility:
        raise ThemeConfigurationError("Theme Version compatibility identity does not match.")
    if family.family_key == "performance-local" and record.version == 2 and (
        record.source_commit != PERFORMANCE_LOCAL_V2_SOURCE_COMMIT
        or record.supported_component_contracts
        != list(PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS)
    ):
        raise ThemeConfigurationError(
            "Performance Local v2 Theme Version does not match the exact canonical source commit and server contract."
        )
    if family.family_key == "performance-local" and record.version == 3 and (
        record.supported_component_contracts
        != list(PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS)
    ):
        raise ThemeConfigurationError(
            "Performance Local v3 Theme Version does not match the exact canonical server contract."
        )
    if record.integrity_fingerprint != _family_version_fingerprint_from_record(record):
        raise ThemeConfigurationError("Theme Version integrity fingerprint does not match.")
    if record.production_ready and record.lifecycle_status != "approved":
        raise ThemeConfigurationError("Only an approved Theme Version may be production-ready.")
    if record.supersedes_theme_family_version_id is not None:
        predecessor = _theme_family_version(
            session,
            record.supersedes_theme_family_version_id,
        )
        if predecessor.theme_family_id != record.theme_family_id or predecessor.version >= record.version:
            raise ThemeConfigurationError("Theme Version lineage is inconsistent.")
        _require_timestamp_order(
            predecessor.updated_at,
            record.created_at,
            "Theme Version successor predates predecessor transition."
        )


def _validate_website_configuration(
    session: Session,
    record: WebsiteThemeConfiguration,
) -> None:
    validate_fingerprint(
        record.integrity_fingerprint,
        "Website Theme configuration fingerprint",
    )
    _require_stored_text(record.created_by, "Website Theme configuration creator", 160)
    _require_stored_text(record.updated_by, "Website Theme configuration updater", 160)
    _require_stored_text(
        record.creation_rationale,
        "Website Theme configuration creation rationale",
        2000,
    )
    try:
        WebsiteThemeConfigurationCreate(
            theme_family_version_id=record.theme_family_version_id,
            configuration_key=record.configuration_key,
            created_by=record.created_by,
            creation_rationale=record.creation_rationale,
            supersedes_configuration_id=record.supersedes_configuration_id,
        )
    except ValueError as exc:
        raise ThemeConfigurationError(
            "Website Theme configuration immutable creation identity is invalid."
        ) from exc
    website = _website(session, record.website_id)
    version = _theme_family_version(session, record.theme_family_version_id)
    _validate_family_version(session, version)
    if record.business_id != website.business_id:
        raise ThemeConfigurationError(
            "Website Theme configuration crosses the Website Business boundary."
        )
    evidence_pairs = (
        (record.approved_by, record.approved_at),
        (record.activated_by, record.activated_at),
        (record.rollback_by, record.rollback_at),
    )
    if any((actor is None) != (timestamp is None) for actor, timestamp in evidence_pairs):
        raise ThemeConfigurationError(
            "Website Theme configuration lifecycle evidence is incomplete."
        )
    if any(
        actor is not None and not actor.strip()
        for actor, _timestamp in evidence_pairs
    ):
        raise ThemeConfigurationError(
            "Website Theme configuration lifecycle actor is invalid."
        )
    if (record.materialized_theme_id is None) != (
        record.website_theme_selection_id is None
    ):
        raise ThemeConfigurationError(
            "Website Theme configuration Theme-selection identity is incomplete."
        )
    lifecycle_evidence = (
        record.approved_by,
        record.activated_by,
        record.rollback_by,
        record.materialized_theme_id,
        record.website_theme_selection_id,
    )
    if record.lifecycle_status == "draft" and any(
        item is not None for item in lifecycle_evidence
    ):
        raise ThemeConfigurationError(
            "Draft Website Theme configuration contains later lifecycle evidence."
        )
    if record.lifecycle_status == "approved" and (
        record.approved_by is None
        or any(
            item is not None
            for item in (
                record.activated_by,
                record.rollback_by,
                record.materialized_theme_id,
                record.website_theme_selection_id,
            )
        )
    ):
        raise ThemeConfigurationError(
            "Approved Website Theme configuration has invalid lifecycle evidence."
        )
    if record.rollback_by is not None and record.activated_by is None:
        raise ThemeConfigurationError(
            "Website Theme configuration rollback lacks activation evidence."
        )
    if record.activated_by is not None and record.approved_by is None:
        raise ThemeConfigurationError(
            "Website Theme configuration activation lacks approval evidence."
        )
    _require_timestamp_order(
        record.created_at,
        record.updated_at,
        "Website Theme configuration update precedes its creation.",
    )
    if record.approved_at is not None:
        _require_timestamp_order(
            record.created_at,
            record.approved_at,
            "Website Theme configuration approval precedes its creation.",
        )
    if record.activated_at is not None:
        _require_timestamp_order(
            record.approved_at,
            record.activated_at,
            "Website Theme configuration activation precedes its approval.",
        )
    if record.rollback_at is not None:
        _require_timestamp_order(
            record.activated_at,
            record.rollback_at,
            "Website Theme configuration rollback precedes its activation.",
        )

    family = _theme_family(session, version.theme_family_id)
    materialized_theme: Theme | None = None
    materialized_selection: WebsiteThemeSelection | None = None
    if record.materialized_theme_id is not None:
        materialized_theme = session.get(Theme, record.materialized_theme_id)
        materialized_selection = session.get(
            WebsiteThemeSelection,
            record.website_theme_selection_id,
        )
        if (
            materialized_theme is None
            or materialized_selection is None
            or materialized_theme.website_id != website.id
            or materialized_theme.business_id != record.business_id
            or materialized_theme.brand_id != website.brand_id
            or materialized_theme.theme_key != family.family_key
            or materialized_selection.website_id != website.id
            or materialized_selection.theme_id != materialized_theme.id
        ):
            raise ThemeConfigurationError(
                "Website Theme configuration crosses its exact governed Theme-selection identity."
            )

    if record.lifecycle_status == "active":
        if (
            record.approved_by is None
            or record.activated_by is None
            or record.rollback_by is not None
            or materialized_theme is None
            or materialized_selection is None
            or version.lifecycle_status != "approved"
            or not version.production_ready
            or family.lifecycle_status != "registered"
            or materialized_theme.lifecycle_status != "available"
            or materialized_theme.approval_status != "approved"
            or materialized_selection.status != "active"
        ):
            raise ThemeConfigurationError(
                "Active Website Theme configuration lacks its exact approved active Theme selection."
            )
        try:
            resolved = resolve_website_theme(session, website.id)
        except ThemeError as exc:
            raise ThemeConfigurationError(
                "Active Website Theme configuration does not resolve to one valid governed Website Theme."
            ) from exc
        if (
            resolved.theme is None
            or resolved.selection is None
            or resolved.theme.id != materialized_theme.id
            or resolved.selection.id != materialized_selection.id
        ):
            raise ThemeConfigurationError(
                "Active Website Theme configuration does not bind the sole resolved Website Theme selection."
            )
    if record.integrity_fingerprint != _website_configuration_fingerprint_from_record(record):
        raise ThemeConfigurationError(
            "Website Theme configuration integrity fingerprint does not match."
        )
    if record.supersedes_configuration_id is not None:
        predecessor = _website_configuration(session, record.supersedes_configuration_id)
        if (
            predecessor.website_id != record.website_id
            or predecessor.theme_family_version_id != record.theme_family_version_id
            or predecessor.configuration_key != record.configuration_key
            or predecessor.version + 1 != record.version
        ):
            raise ThemeConfigurationError("Website Theme configuration lineage is inconsistent.")
        _require_timestamp_order(
            predecessor.updated_at,
            record.created_at,
            "Website Theme configuration successor predates predecessor supersession.",
        )


def _validate_component_configuration(
    session: Session,
    record: WebsiteThemeComponentConfiguration,
) -> None:
    validate_fingerprint(record.integrity_fingerprint, "Component configuration fingerprint")
    _require_stored_text(record.created_by, "Theme component creator", 160)
    _require_stored_text(record.updated_by, "Theme component updater", 160)
    evidence_pairs = (
        (record.activation_identity, record.activated_at),
        (record.rollback_identity, record.rollback_at),
    )
    if any((identity is None) != (timestamp is None) for identity, timestamp in evidence_pairs):
        raise ThemeConfigurationError("Theme component lifecycle evidence is incomplete.")
    if any(
        identity is not None and not identity.strip()
        for identity, _timestamp in evidence_pairs
    ):
        raise ThemeConfigurationError("Theme component lifecycle identity is invalid.")
    if record.rollback_identity is not None and record.activation_identity is None:
        raise ThemeConfigurationError("Theme component rollback lacks activation evidence.")
    _require_timestamp_order(
        record.created_at,
        record.updated_at,
        "Theme component update precedes its creation.",
    )
    if record.activated_at is not None:
        _require_timestamp_order(
            record.created_at,
            record.activated_at,
            "Theme component activation precedes its creation.",
        )
    if record.rollback_at is not None:
        _require_timestamp_order(
            record.activated_at,
            record.rollback_at,
            "Theme component rollback precedes its activation.",
        )
    configuration = _website_configuration(
        session,
        record.website_theme_configuration_id,
    )
    _validate_website_configuration(session, configuration)
    if (
        record.website_id != configuration.website_id
        or record.theme_family_version_id != configuration.theme_family_version_id
    ):
        raise ThemeConfigurationError(
            "Component configuration crosses its Website Theme configuration scope."
        )
    _validate_planned_page_scope(
        session,
        website_id=record.website_id,
        scope_type=record.scope_type,
        planned_page_id=record.planned_page_id,
    )
    normalized = validate_component_payload(
        record.component_key,
        record.configuration_payload,
        record.component_contract_version,
    )
    if normalized != record.configuration_payload:
        raise ThemeConfigurationError("Component configuration payload is not canonical.")
    contract_payload = WebsiteThemeComponentConfigurationCreate(
        component_instance_key=record.component_instance_key,
        component_key=record.component_key,
        component_contract_version=record.component_contract_version,
        scope_type=record.scope_type,
        planned_page_id=record.planned_page_id,
        enabled=record.enabled,
        variant=record.variant,
        placement=record.placement,
        responsive_visibility=record.responsive_visibility,
        configuration_payload=record.configuration_payload,
        effective_at=(
            _as_utc(record.effective_at) if record.effective_at is not None else None
        ),
        expires_at=(
            _as_utc(record.expires_at) if record.expires_at is not None else None
        ),
        approval_identity=record.approval_identity,
        created_by=record.created_by,
        destination_component_configuration_id=record.destination_component_configuration_id,
        overrides_component_configuration_id=record.overrides_component_configuration_id,
    )
    version = _theme_family_version(session, record.theme_family_version_id)
    _validate_component_contract(version, contract_payload)
    _validate_component_approval_identity(
        record.component_key,
        record.configuration_payload,
        record.approval_identity,
    )
    _validate_provider_state(
        record.component_key,
        record.configuration_payload,
        record.component_contract_version,
    )
    _validate_destination(
        session,
        configuration=configuration,
        component_key=record.component_key,
        destination_id=record.destination_component_configuration_id,
        allow_self_record_id=record.id,
        require_current_target=record.lifecycle_status == "current",
    )
    _validate_override_target(
        session,
        configuration=configuration,
        component_key=record.component_key,
        component_contract_version=record.component_contract_version,
        scope_type=record.scope_type,
        overrides_component_configuration_id=record.overrides_component_configuration_id,
        allow_self_record_id=record.id,
        require_current_target=record.lifecycle_status == "current",
    )
    if record.integrity_fingerprint != _component_fingerprint_from_record(record):
        raise ThemeConfigurationError("Component configuration integrity fingerprint does not match.")
    if record.supersedes_component_configuration_id is not None:
        predecessor = _component_configuration(
            session,
            record.supersedes_component_configuration_id,
        )
        if (
            predecessor.website_theme_configuration_id
            != record.website_theme_configuration_id
            or predecessor.component_instance_key != record.component_instance_key
            or predecessor.revision + 1 != record.revision
        ):
            raise ThemeConfigurationError("Component configuration lineage is inconsistent.")
        _require_timestamp_order(
            predecessor.updated_at,
            record.created_at,
            "Theme component successor predates predecessor supersession.",
        )


def _validate_component_contract(
    version: ThemeFamilyVersion,
    payload: WebsiteThemeComponentConfigurationCreate,
) -> None:
    _validate_component_contract_records(version.supported_component_contracts, payload)


def _validate_component_contract_records(
    contracts: list[dict[str, Any]],
    payload: Any,
) -> None:
    matching = [
        item
        for item in contracts
        if item.get("component_key") == payload.component_key
    ]
    if len(matching) != 1:
        raise ThemeConfigurationError(
            "Theme Version does not define exactly one matching component contract."
        )
    contract = matching[0]
    if (
        contract.get("contract_version") != payload.component_contract_version
        or contract.get("placement") != payload.placement
        or contract.get("variant") != payload.variant
        or contract.get("responsive_visibility")
        != payload.responsive_visibility.model_dump(mode="json")
    ):
        raise ThemeConfigurationError(
            "Component configuration is incompatible with the exact Theme Version contract."
        )
    if payload.scope_type == "page_override" and contract.get("supports_page_override") is not True:
        raise ThemeConfigurationError("Component contract does not support a Page override.")


def _validate_planned_page_scope(
    session: Session,
    *,
    website_id: int,
    scope_type: str,
    planned_page_id: int | None,
) -> None:
    if scope_type == "website_default" and planned_page_id is None:
        return
    if scope_type != "page_override" or planned_page_id is None:
        raise ThemeConfigurationError("Component Page scope is incomplete.")
    page = session.get(PlannedPage, planned_page_id)
    if page is None:
        raise ThemeConfigurationError(
            "Planned Page override target was not found.",
            status_code=404,
            code="planned_page_not_found",
        )
    if page.website_id != website_id:
        raise ThemeConfigurationError("Component Page override crosses the Website boundary.")


def _validate_destination(
    session: Session,
    *,
    configuration: WebsiteThemeConfiguration,
    component_key: str,
    destination_id: int | None,
    allow_self_record_id: int | None = None,
    require_current_target: bool = True,
) -> WebsiteThemeComponentConfiguration | None:
    requires_destination = component_key in {
        "campaign_banner",
        "sticky_mobile_action_bar",
    }
    if requires_destination and destination_id is None:
        raise ThemeConfigurationError(
            "Conversion action configuration requires the exact compact-form target."
        )
    if not requires_destination and destination_id is not None:
        raise ThemeConfigurationError(
            "Only a conversion action may reference a compact-form target."
        )
    if destination_id is None:
        return None
    if destination_id == allow_self_record_id:
        raise ThemeConfigurationError("A component cannot target itself.")
    destination = _component_configuration(session, destination_id)
    if (
        destination.website_theme_configuration_id != configuration.id
        or destination.website_id != configuration.website_id
        or destination.theme_family_version_id
        != configuration.theme_family_version_id
        or destination.component_key != "compact_estimate_form"
        or (
            require_current_target
            and destination.lifecycle_status != "current"
        )
        or destination.lifecycle_status not in {"current", "superseded"}
        or not destination.enabled
    ):
        raise ThemeConfigurationError(
            "Conversion destination is not the exact current enabled compact-form configuration."
        )
    _validate_component_configuration_without_destination(session, destination)
    return destination


def _validate_override_target(
    session: Session,
    *,
    configuration: WebsiteThemeConfiguration,
    component_key: str,
    component_contract_version: int,
    scope_type: str,
    overrides_component_configuration_id: int | None,
    allow_self_record_id: int | None = None,
    require_current_target: bool = True,
) -> WebsiteThemeComponentConfiguration | None:
    if scope_type == "website_default":
        if overrides_component_configuration_id is not None:
            raise ThemeConfigurationError(
                "A Website-default component cannot override another component."
            )
        return None
    if overrides_component_configuration_id is None:
        raise ThemeConfigurationError(
            "A Page override requires one exact Website-default component target."
        )
    if overrides_component_configuration_id == allow_self_record_id:
        raise ThemeConfigurationError("A component cannot override itself.")
    target = _component_configuration(
        session,
        overrides_component_configuration_id,
    )
    if (
        target.website_theme_configuration_id != configuration.id
        or target.website_id != configuration.website_id
        or target.theme_family_version_id != configuration.theme_family_version_id
        or target.scope_type != "website_default"
        or (require_current_target and target.lifecycle_status != "current")
        or target.lifecycle_status not in {"current", "superseded"}
        or target.component_key != component_key
        or target.component_contract_version != component_contract_version
    ):
        raise ThemeConfigurationError(
            "Page override target is not the exact current same-contract Website-default component."
        )
    return target


def _validate_component_configuration_without_destination(
    session: Session,
    record: WebsiteThemeComponentConfiguration,
) -> None:
    if record.destination_component_configuration_id is not None:
        raise ThemeConfigurationError("Compact form may not target another component.")
    normalized = validate_component_payload(
        record.component_key,
        record.configuration_payload,
        record.component_contract_version,
    )
    if normalized != record.configuration_payload:
        raise ThemeConfigurationError("Destination compact-form payload is not canonical.")
    _validate_provider_state(
        record.component_key,
        normalized,
        record.component_contract_version,
    )
    if record.integrity_fingerprint != _component_fingerprint_from_record(record):
        raise ThemeConfigurationError("Destination compact-form fingerprint does not match.")


def _validate_component_approval_identity(
    component_key: str,
    payload: dict[str, Any],
    approval_identity: str | None,
) -> None:
    if not approval_identity or not approval_identity.strip():
        raise ThemeConfigurationError(
            "Inactive conversion component configuration requires operator approval identity."
        )
    payload_identity = payload.get("approval_identity")
    if component_key == "campaign_banner" and payload_identity != approval_identity:
        raise ThemeConfigurationError(
            "Campaign approval identity must match its component decision identity."
        )


def _validate_provider_state(
    component_key: str,
    payload: dict[str, Any],
    component_contract_version: int = 2,
) -> None:
    if component_key != "compact_estimate_form":
        return
    if component_contract_version == 3:
        return
    configuration = CompactEstimateFormConfiguration.model_validate(payload)
    validate_provider_disabled_form(configuration)


def _validate_preview_components(
    session: Session,
    configuration: WebsiteThemeConfiguration,
    components: list[WebsiteThemeComponentConfiguration],
) -> None:
    enabled_components = [item for item in components if item.enabled]
    enabled_forms = [
        item
        for item in enabled_components
        if item.component_key == "compact_estimate_form"
    ]
    enabled_sticky_actions = [
        item
        for item in enabled_components
        if item.component_key == "sticky_mobile_action_bar"
    ]
    enabled_banners = [
        item
        for item in enabled_components
        if item.component_key == "campaign_banner"
    ]
    if len(enabled_forms) != 1:
        raise ThemeConfigurationError(
            "Page-scoped Theme graph requires exactly one enabled compact estimate form."
        )
    if len(enabled_sticky_actions) != 1:
        raise ThemeConfigurationError(
            "Page-scoped Theme graph requires exactly one enabled sticky conversion-action policy."
        )
    if len(enabled_banners) > 1:
        raise ThemeConfigurationError(
            "Page-scoped Theme graph allows at most one enabled effective campaign banner."
        )
    sole_form_id = _required_id(enabled_forms[0])
    if any(
        item.destination_component_configuration_id != sole_form_id
        for item in (*enabled_sticky_actions, *enabled_banners)
    ):
        raise ThemeConfigurationError(
            "Every enabled Page-scoped conversion action must target the sole enabled compact estimate form."
        )
    current_ids = {_required_id(item) for item in components}
    for component in components:
        destination_id = component.destination_component_configuration_id
        if destination_id is not None and destination_id not in current_ids:
            raise ThemeConfigurationError(
                "Effective conversion component loses its exact compact-form target in this Page scope."
            )
        _validate_destination(
            session,
            configuration=configuration,
            component_key=component.component_key,
            destination_id=destination_id,
            allow_self_record_id=component.id,
        )


def _resolve_components_for_page(
    rows: list[WebsiteThemeComponentConfiguration],
    planned_page_id: int | None,
    *,
    evaluated_at: datetime,
) -> list[WebsiteThemeComponentConfiguration]:
    defaults = [item for item in rows if item.scope_type == "website_default"]
    overrides = [
        item
        for item in rows
        if item.scope_type == "page_override" and item.planned_page_id == planned_page_id
    ]
    overridden_ids = {
        item.overrides_component_configuration_id
        for item in overrides
        if item.overrides_component_configuration_id is not None
    }
    selected = [item for item in defaults if item.id not in overridden_ids]
    selected.extend(overrides)
    effective = [
        item
        for item in selected
        if _component_is_effective_at(item, evaluated_at=evaluated_at)
    ]
    return sorted(effective, key=lambda item: (item.placement, item.component_instance_key))


def _component_is_effective_at(
    component: WebsiteThemeComponentConfiguration,
    *,
    evaluated_at: datetime,
) -> bool:
    if not component.enabled or component.component_key != "campaign_banner":
        return True
    payload = validate_component_payload(
        component.component_key,
        component.configuration_payload,
        component.component_contract_version,
    )
    if payload.get("intent") != "time_bound_campaign":
        return True
    if component.effective_at is None or component.expires_at is None:
        raise ThemeConfigurationError("Time-bound campaign schedule is incomplete.")
    now = _as_utc(evaluated_at)
    return _as_utc(component.effective_at) <= now < _as_utc(component.expires_at)


def _preview_planned_page_id(
    session: Session,
    *,
    website_id: int,
    generated_page_id: int | None,
) -> int | None:
    if generated_page_id is None:
        return None
    generated = session.get(GeneratedPage, generated_page_id)
    if generated is None:
        raise ThemeConfigurationError(
            "Generated Page preview target was not found.",
            status_code=404,
            code="generated_page_not_found",
        )
    if generated.website_id != website_id:
        raise ThemeConfigurationError("Draft preview Page crosses the Website boundary.")
    matches = list(
        session.exec(
            select(PlannedPage).where(
                PlannedPage.website_id == website_id,
                PlannedPage.generated_page_id == generated_page_id,
            )
        ).all()
    )
    if len(matches) != 1:
        raise ThemeConfigurationError(
            "Generated Page does not resolve to exactly one Website-owned Planned Page."
        )
    return _required_id(matches[0])


def _governed_phone(
    session: Session,
    website: Website,
) -> tuple[str | None, str | None]:
    business = session.get(Business, website.business_id)
    if business is None or not business.phone or not business.phone.strip():
        return None, None
    display = business.phone.strip()
    normalized = re.sub(r"[^\d+]", "", display)
    if not _PHONE_PATTERN.fullmatch(normalized):
        return display, None
    return display, f"tel:{normalized}"


def _audit_history(
    session: Session,
    *,
    family: ThemeFamily,
    family_version: ThemeFamilyVersion,
    website_configuration: WebsiteThemeConfiguration,
    component_ids: set[int],
) -> list[ThemeConfigurationAudit]:
    conditions = [
        ThemeConfigurationAudit.theme_family_id == family.id,
        ThemeConfigurationAudit.theme_family_version_id == family_version.id,
        ThemeConfigurationAudit.website_theme_configuration_id
        == website_configuration.id,
    ]
    if component_ids:
        conditions.append(
            ThemeConfigurationAudit.component_configuration_id.in_(component_ids)
        )
    rows = list(
        session.exec(
            select(ThemeConfigurationAudit)
            .where(or_(*conditions))
            .order_by(ThemeConfigurationAudit.created_at, ThemeConfigurationAudit.id)
        ).all()
    )
    for row in rows:
        _validate_audit(row)
    return rows


def _append_audit(
    session: Session,
    *,
    action_type: str,
    actor: str,
    rationale: str,
    snapshot: dict[str, Any],
    theme_family_id: int | None = None,
    theme_family_version_id: int | None = None,
    website_theme_configuration_id: int | None = None,
    component_configuration_id: int | None = None,
) -> ThemeConfigurationAudit:
    if action_type not in _AUDIT_ACTION_TYPES:
        raise ThemeConfigurationError("Theme configuration audit action is not supported.")
    created_at = _utc_now()
    hash_payload = {
        "theme_family_id": theme_family_id,
        "theme_family_version_id": theme_family_version_id,
        "website_theme_configuration_id": website_theme_configuration_id,
        "component_configuration_id": component_configuration_id,
        "action_type": action_type,
        "actor": actor,
        "rationale": rationale,
        "snapshot": snapshot,
        "created_at": _datetime_value(created_at),
    }
    snapshot_hash = canonical_json_hash(hash_payload)
    existing = session.exec(
        select(ThemeConfigurationAudit).where(
            ThemeConfigurationAudit.snapshot_hash == snapshot_hash
        )
    ).first()
    if existing:
        _validate_audit(existing)
        return existing
    audit = ThemeConfigurationAudit(
        theme_family_id=theme_family_id,
        theme_family_version_id=theme_family_version_id,
        website_theme_configuration_id=website_theme_configuration_id,
        component_configuration_id=component_configuration_id,
        action_type=action_type,
        actor=actor,
        rationale=rationale,
        snapshot=snapshot,
        snapshot_hash=snapshot_hash,
        created_at=created_at,
    )
    session.add(audit)
    return audit


def _validate_audit(record: ThemeConfigurationAudit) -> None:
    validate_fingerprint(record.snapshot_hash, "Theme configuration audit hash")
    _require_stored_text(record.actor, "Theme configuration audit actor", 160)
    _require_stored_text(record.rationale, "Theme configuration audit rationale", 2000)
    if record.action_type not in _AUDIT_ACTION_TYPES:
        raise ThemeConfigurationError("Theme configuration audit action is not supported.")
    targets = [
        record.theme_family_id,
        record.theme_family_version_id,
        record.website_theme_configuration_id,
        record.component_configuration_id,
    ]
    if sum(value is not None for value in targets) != 1:
        raise ThemeConfigurationError("Theme configuration audit does not have one exact target.")
    expected = canonical_json_hash(
        {
            "theme_family_id": record.theme_family_id,
            "theme_family_version_id": record.theme_family_version_id,
            "website_theme_configuration_id": record.website_theme_configuration_id,
            "component_configuration_id": record.component_configuration_id,
            "action_type": record.action_type,
            "actor": record.actor,
            "rationale": record.rationale,
            "snapshot": record.snapshot,
            "created_at": _datetime_value(record.created_at),
        }
    )
    if record.snapshot_hash != expected:
        raise ThemeConfigurationError("Theme configuration audit snapshot hash does not match.")


def _require_audit_coverage(
    session: Session,
    *,
    families: list[ThemeFamily],
    versions: list[ThemeFamilyVersion],
    configurations: list[WebsiteThemeConfiguration],
    components: list[WebsiteThemeComponentConfiguration],
) -> None:
    required: list[tuple[Any, int, str, str, datetime]] = []

    def add(
        column: Any,
        record: Any,
        action_type: str,
        label: str,
        *,
        not_before: datetime | None = None,
    ) -> None:
        required.append(
            (
                column,
                _required_id(record),
                action_type,
                label,
                not_before or record.created_at,
            )
        )

    for record in families:
        add(
            ThemeConfigurationAudit.theme_family_id,
            record,
            "family_registered",
            "Theme Family registration",
        )
        if record.lifecycle_status == "retired":
            add(
                ThemeConfigurationAudit.theme_family_id,
                record,
                "family_retired",
                "Theme Family retirement",
                not_before=record.retired_at,
            )
    for record in versions:
        add(
            ThemeConfigurationAudit.theme_family_version_id,
            record,
            "family_version_registered",
            "Theme Family Version registration",
        )
        if record.lifecycle_status == "approved":
            add(
                ThemeConfigurationAudit.theme_family_version_id,
                record,
                "family_version_approved",
                "Theme Family Version approval",
                not_before=record.updated_at,
            )
        if record.lifecycle_status == "retired":
            add(
                ThemeConfigurationAudit.theme_family_version_id,
                record,
                "family_version_retired",
                "Theme Family Version retirement",
                not_before=record.retired_at,
            )
    for record in configurations:
        add(
            ThemeConfigurationAudit.website_theme_configuration_id,
            record,
            (
                "website_draft_created"
                if record.version == 1
                else "website_configuration_revision_created"
            ),
            "Website Theme configuration creation",
        )
        if record.approved_at is not None:
            add(
                ThemeConfigurationAudit.website_theme_configuration_id,
                record,
                "website_configuration_approved",
                "Website Theme configuration approval",
                not_before=record.approved_at,
            )
        if record.activated_at is not None:
            add(
                ThemeConfigurationAudit.website_theme_configuration_id,
                record,
                "website_configuration_activated",
                "Website Theme configuration activation",
                not_before=record.activated_at,
            )
        if record.lifecycle_status == "superseded":
            add(
                ThemeConfigurationAudit.website_theme_configuration_id,
                record,
                "website_configuration_superseded",
                "Website Theme configuration supersession",
                not_before=record.updated_at,
            )
        if record.rollback_at is not None:
            add(
                ThemeConfigurationAudit.website_theme_configuration_id,
                record,
                "website_configuration_rolled_back",
                "Website Theme configuration rollback",
                not_before=record.rollback_at,
            )
        if record.lifecycle_status == "retired":
            add(
                ThemeConfigurationAudit.website_theme_configuration_id,
                record,
                "website_configuration_retired",
                "Website Theme configuration retirement",
                not_before=record.updated_at,
            )
    for record in components:
        add(
            ThemeConfigurationAudit.component_configuration_id,
            record,
            "component_created" if record.revision == 1 else "component_revision_created",
            "Website Theme component revision creation",
        )
        if record.lifecycle_status == "superseded":
            add(
                ThemeConfigurationAudit.component_configuration_id,
                record,
                "component_superseded",
                "Website Theme component supersession",
                not_before=record.updated_at,
            )
        if record.activated_at is not None:
            add(
                ThemeConfigurationAudit.component_configuration_id,
                record,
                "component_activated",
                "Website Theme component activation",
                not_before=record.activated_at,
            )
        if record.rollback_at is not None:
            add(
                ThemeConfigurationAudit.component_configuration_id,
                record,
                "component_rolled_back",
                "Website Theme component rollback",
                not_before=record.rollback_at,
            )

    for column, target_id, action_type, label, not_before in required:
        matches = list(
            session.exec(
                select(ThemeConfigurationAudit).where(
                    column == target_id,
                    ThemeConfigurationAudit.action_type == action_type,
                )
            ).all()
        )
        if len(matches) != 1:
            raise ThemeConfigurationError(
                f"{label} does not have exactly one required immutable audit record."
            )
        _validate_audit(matches[0])
        if _as_utc(matches[0].created_at) < _as_utc(not_before):
            raise ThemeConfigurationError(
                f"{label} audit chronology precedes its durable target transition."
            )


def _family_fingerprint_payload(record: ThemeFamily) -> dict[str, Any]:
    return {
        "family_key": record.family_key,
        "display_name": record.display_name,
        "description": record.description,
        "provider_source_identity": record.provider_source_identity,
        "lifecycle_status": record.lifecycle_status,
        "created_by": record.created_by,
        "retired_by": record.retired_by,
        "retired_at": _datetime_value(record.retired_at),
    }


def _family_fingerprint_from_record(record: ThemeFamily) -> str:
    return canonical_json_hash(_family_fingerprint_payload(record))


def _family_fingerprint(**values: Any) -> str:
    return canonical_json_hash(
        {
            **values,
            "retired_at": _datetime_value(values.get("retired_at")),
        }
    )


def _family_version_fingerprint_payload(record: ThemeFamilyVersion) -> dict[str, Any]:
    return {
        "theme_family_id": record.theme_family_id,
        "version": record.version,
        "lifecycle_status": record.lifecycle_status,
        "production_ready": record.production_ready,
        "source_commit": record.source_commit,
        "compatibility_identity": record.compatibility_identity,
        "supported_component_contracts": record.supported_component_contracts,
        "created_by": record.created_by,
        "retired_by": record.retired_by,
        "retired_at": _datetime_value(record.retired_at),
        "supersedes_theme_family_version_id": record.supersedes_theme_family_version_id,
    }


def _family_version_fingerprint_from_record(record: ThemeFamilyVersion) -> str:
    return canonical_json_hash(_family_version_fingerprint_payload(record))


def _family_version_fingerprint(**values: Any) -> str:
    return canonical_json_hash(
        {
            **values,
            "retired_at": _datetime_value(values.get("retired_at")),
        }
    )


def _website_configuration_fingerprint_payload(
    record: WebsiteThemeConfiguration,
) -> dict[str, Any]:
    return {
        "website_id": record.website_id,
        "business_id": record.business_id,
        "theme_family_version_id": record.theme_family_version_id,
        "configuration_key": record.configuration_key,
        "version": record.version,
        "lifecycle_status": record.lifecycle_status,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
        "creation_rationale": record.creation_rationale,
        "approved_by": record.approved_by,
        "approved_at": _datetime_value(record.approved_at),
        "activated_by": record.activated_by,
        "activated_at": _datetime_value(record.activated_at),
        "rollback_by": record.rollback_by,
        "rollback_at": _datetime_value(record.rollback_at),
        "materialized_theme_id": record.materialized_theme_id,
        "website_theme_selection_id": record.website_theme_selection_id,
        "supersedes_configuration_id": record.supersedes_configuration_id,
    }


def _website_configuration_fingerprint_from_record(
    record: WebsiteThemeConfiguration,
) -> str:
    return canonical_json_hash(_website_configuration_fingerprint_payload(record))


def _website_configuration_fingerprint(**values: Any) -> str:
    normalized = dict(values)
    for key in ("approved_at", "activated_at", "rollback_at"):
        normalized[key] = _datetime_value(normalized.get(key))
    return canonical_json_hash(normalized)


def _component_fingerprint_payload(
    record: WebsiteThemeComponentConfiguration,
) -> dict[str, Any]:
    return {
        "website_theme_configuration_id": record.website_theme_configuration_id,
        "website_id": record.website_id,
        "planned_page_id": record.planned_page_id,
        "theme_family_version_id": record.theme_family_version_id,
        "component_instance_key": record.component_instance_key,
        "component_key": record.component_key,
        "component_contract_version": record.component_contract_version,
        "revision": record.revision,
        "scope_type": record.scope_type,
        "lifecycle_status": record.lifecycle_status,
        "enabled": record.enabled,
        "variant": record.variant,
        "placement": record.placement,
        "responsive_visibility": record.responsive_visibility,
        "configuration_payload": record.configuration_payload,
        "effective_at": _datetime_value(record.effective_at),
        "expires_at": _datetime_value(record.expires_at),
        "approval_identity": record.approval_identity,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
        "activation_identity": record.activation_identity,
        "activated_at": _datetime_value(record.activated_at),
        "rollback_identity": record.rollback_identity,
        "rollback_at": _datetime_value(record.rollback_at),
        "destination_component_configuration_id": record.destination_component_configuration_id,
        "overrides_component_configuration_id": record.overrides_component_configuration_id,
        "supersedes_component_configuration_id": record.supersedes_component_configuration_id,
    }


def _component_fingerprint_from_record(
    record: WebsiteThemeComponentConfiguration,
) -> str:
    return canonical_json_hash(_component_fingerprint_payload(record))


def _component_fingerprint(**values: Any) -> str:
    normalized = dict(values)
    for key in ("effective_at", "expires_at", "activated_at", "rollback_at"):
        normalized[key] = _datetime_value(normalized.get(key))
    return canonical_json_hash(normalized)


def _datetime_value(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_timestamp_order(
    earlier: datetime | None,
    later: datetime | None,
    message: str,
) -> None:
    if earlier is None or later is None or _as_utc(later) < _as_utc(earlier):
        raise ThemeConfigurationError(message)


def _require_stored_text(value: str, label: str, maximum_length: int) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum_length
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ThemeConfigurationError(
            f"{label} must be non-empty bounded text without control characters."
        )


def _theme_family(session: Session, family_id: int) -> ThemeFamily:
    record = session.get(ThemeFamily, family_id)
    if record is None:
        raise ThemeConfigurationError(
            "Theme Family was not found.",
            status_code=404,
            code="theme_family_not_found",
        )
    return record


def _theme_family_version(session: Session, version_id: int) -> ThemeFamilyVersion:
    record = session.get(ThemeFamilyVersion, version_id)
    if record is None:
        raise ThemeConfigurationError(
            "Theme Family Version was not found.",
            status_code=404,
            code="theme_family_version_not_found",
        )
    return record


def _website(session: Session, website_id: int) -> Website:
    record = session.get(Website, website_id)
    if record is None:
        raise ThemeConfigurationError(
            "Website was not found.",
            status_code=404,
            code="website_not_found",
        )
    return record


def _website_configuration(
    session: Session,
    configuration_id: int,
    *,
    for_update: bool = False,
) -> WebsiteThemeConfiguration:
    statement = select(WebsiteThemeConfiguration).where(
        WebsiteThemeConfiguration.id == configuration_id
    )
    if for_update:
        statement = statement.with_for_update()
    record = session.exec(statement).first()
    if record is None:
        raise ThemeConfigurationError(
            "Website Theme configuration was not found.",
            status_code=404,
            code="website_theme_configuration_not_found",
        )
    return record


def _component_configuration(
    session: Session,
    component_id: int,
    *,
    for_update: bool = False,
) -> WebsiteThemeComponentConfiguration:
    statement = select(WebsiteThemeComponentConfiguration).where(
        WebsiteThemeComponentConfiguration.id == component_id
    )
    if for_update:
        statement = statement.with_for_update()
    record = session.exec(statement).first()
    if record is None:
        raise ThemeConfigurationError(
            "Website Theme component configuration was not found.",
            status_code=404,
            code="theme_component_configuration_not_found",
        )
    return record


def _require_configuration_scope(
    configuration: WebsiteThemeConfiguration,
    website_id: int,
) -> None:
    if configuration.website_id != website_id:
        raise ThemeConfigurationError(
            "Website Theme configuration crosses the Website boundary."
        )


def _require_inactive_draft(configuration: WebsiteThemeConfiguration) -> None:
    if (
        configuration.lifecycle_status != "draft"
        or configuration.approved_by is not None
        or configuration.approved_at is not None
        or configuration.activated_by is not None
        or configuration.activated_at is not None
        or configuration.rollback_by is not None
        or configuration.rollback_at is not None
        or configuration.materialized_theme_id is not None
        or configuration.website_theme_selection_id is not None
    ):
        raise ThemeConfigurationError(
            "Theme Lab may consume only an inactive, unapproved Website Theme draft."
        )


def _required_id(record: Any) -> int:
    if record.id is None:
        raise ThemeConfigurationError("Durable Theme record has no database identity.")
    return int(record.id)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
