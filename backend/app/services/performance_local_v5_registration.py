from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import (
    Theme,
    ThemeConfigurationAudit,
    ThemeFamily,
    ThemeFamilyVersion,
    Website,
    WebsiteThemeComponentConfiguration,
    WebsiteThemeConfiguration,
    WebsiteThemeSelection,
)
from app.schemas.performance_local_v5 import (
    PerformanceLocalV5RegistrationAction,
    PerformanceLocalV5RegistrationApplyResult,
    PerformanceLocalV5RegistrationIdentity,
    PerformanceLocalV5RegistrationPlan,
)
from app.schemas.theme_families import (
    PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS,
    ThemeFamilyVersionCreate,
    WebsiteThemeComponentConfigurationCreate,
    WebsiteThemeConfigurationCreate,
)
from app.services import theme_configurations as theme_service
from app.services import themes as runtime_theme_service


PERFORMANCE_LOCAL_V5_SOURCE_COMMIT = "dfa360e13084ec80f3e4b8b959abded33ca3bc64"
PERFORMANCE_LOCAL_V5_CONFIGURATION_KEY = "performance-local-v5"
PERFORMANCE_LOCAL_V5_THEME_KEY = "performance-local"
PERFORMANCE_LOCAL_V5_FAMILY_VERSION = 5
PERFORMANCE_LOCAL_V5_COMPONENT_CONTRACTS = tuple(
    {
        **deepcopy(contract),
        "contract_version": PERFORMANCE_LOCAL_V5_FAMILY_VERSION,
        "theme_compatibility": ["performance-local@5"],
    }
    for contract in PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS
)
PERFORMANCE_LOCAL_V5_CONTRACT_FINGERPRINT = theme_service.canonical_json_hash(
    PERFORMANCE_LOCAL_V5_COMPONENT_CONTRACTS
)

_COMPONENT_KEYS = frozenset(
    {"campaign_banner", "sticky_mobile_action_bar", "compact_estimate_form"}
)


class PerformanceLocalV5RegistrationError(ValueError):
    """Fail-closed V5 registration/configuration/selection domain error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 409,
        code: str = "performance_local_v5_registration_blocked",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def plan_performance_local_v5_registration(
    session: Session,
    website_id: int,
    *,
    source_commit: str = PERFORMANCE_LOCAL_V5_SOURCE_COMMIT,
) -> PerformanceLocalV5RegistrationPlan:
    """Return a deterministic read-only all-missing/exact/conflict plan."""

    pending_before = _pending_identity(session)
    with session.no_autoflush:
        result = _plan(session, website_id, source_commit=source_commit, lock=False)
    if _pending_identity(session) != pending_before:
        raise PerformanceLocalV5RegistrationError(
            "V5 registration planning attempted to stage an Atlas write.",
            code="performance_local_v5_registration_plan_write_detected",
        )
    return result


def apply_performance_local_v5_registration(
    session: Session,
    website_id: int,
    *,
    actor: str,
    source_commit: str = PERFORMANCE_LOCAL_V5_SOURCE_COMMIT,
) -> PerformanceLocalV5RegistrationApplyResult:
    """Atomically apply a previously authorized durable V5 graph.

    This callable is intentionally not wired to an API route and is not invoked
    by payload building or staging orchestration. A future operator must grant
    separate authority before calling it against active Atlas.
    """

    actor = actor.strip()
    if not actor:
        raise PerformanceLocalV5RegistrationError(
            "A durable operator identity is required.",
            status_code=422,
        )
    if any(_pending_identity(session)):
        raise PerformanceLocalV5RegistrationError(
            "V5 registration apply requires a clean Session write set.",
            code="performance_local_v5_registration_pending_writes",
        )
    try:
        plan = _plan(session, website_id, source_commit=source_commit, lock=True)
        if plan.status == "UNCHANGED":
            return PerformanceLocalV5RegistrationApplyResult(
                status="UNCHANGED",
                website_id=website_id,
                identity=plan.identity,
                audit_ids=[],
            )
        if plan.status != "PLANNED":
            raise PerformanceLocalV5RegistrationError(
                "V5 registration conflicts with existing durable state: "
                + "; ".join(plan.blockers),
                code="performance_local_v5_registration_conflict",
            )

        website = _locked_record(session, Website, website_id, "Website")
        family, predecessor = _locked_family_prerequisites(session)
        source_components, source_configuration = _source_v3_graph(
            session, website_id, lock=True
        )
        prior_selection, source_theme = _sole_active_selection(
            session, website, lock=True
        )
        version = theme_service.register_theme_family_version(
            session,
            _id(family),
            ThemeFamilyVersionCreate(
                version=PERFORMANCE_LOCAL_V5_FAMILY_VERSION,
                lifecycle_status="preview_candidate",
                production_ready=False,
                source_commit=source_commit,
                supported_component_contracts=list(
                    PERFORMANCE_LOCAL_V5_COMPONENT_CONTRACTS
                ),
                created_by=actor,
                supersedes_theme_family_version_id=_id(predecessor),
            ),
            _commit_changes=False,
        )
        configuration = theme_service.create_website_theme_configuration(
            session,
            website_id,
            WebsiteThemeConfigurationCreate(
                theme_family_version_id=_id(version),
                configuration_key=PERFORMANCE_LOCAL_V5_CONFIGURATION_KEY,
                created_by=actor,
                creation_rationale=(
                    "Create the exact production-ready Performance Local V5 "
                    "Website configuration."
                ),
            ),
            _commit_changes=False,
        )

        created_components: dict[str, WebsiteThemeComponentConfiguration] = {}
        for key in (
            "compact_estimate_form",
            "campaign_banner",
            "sticky_mobile_action_bar",
        ):
            source = source_components[key]
            contract = _component_contract(key)
            destination = (
                None
                if key == "compact_estimate_form"
                else _id(created_components["compact_estimate_form"])
            )
            created_components[key] = theme_service.create_component_configuration(
                session,
                website_id,
                _id(configuration),
                WebsiteThemeComponentConfigurationCreate(
                    component_instance_key=source.component_instance_key,
                    component_key=key,
                    component_contract_version=PERFORMANCE_LOCAL_V5_FAMILY_VERSION,
                    scope_type="website_default",
                    planned_page_id=None,
                    enabled=source.enabled,
                    variant=str(contract["variant"]),
                    placement=str(contract["placement"]),
                    responsive_visibility=contract["responsive_visibility"],
                    configuration_payload=deepcopy(source.configuration_payload),
                    effective_at=source.effective_at,
                    expires_at=source.expires_at,
                    # Preserve the governed decision identity embedded in the
                    # source graph; the new registration/apply actor remains
                    # separately recorded as creator and activation identity.
                    approval_identity=source.approval_identity,
                    created_by=actor,
                    destination_component_configuration_id=destination,
                    overrides_component_configuration_id=None,
                ),
                _commit_changes=False,
            )

        # Creation timestamps are assigned by the existing services during
        # their flushes. Transition timestamps must follow those durable
        # creation boundaries, including on databases with strict ordering.
        now = datetime.now(UTC)
        version.lifecycle_status = "approved"
        version.production_ready = True
        version.updated_at = now
        version.integrity_fingerprint = theme_service._family_version_fingerprint_from_record(
            version
        )
        session.add(version)
        approval_audits: list[ThemeConfigurationAudit] = []
        approval_audits.append(
            theme_service._append_audit(
                session,
                action_type="family_version_approved",
                actor=actor,
                rationale=(
                    "Approve the exact committed Performance Local V5 contract as "
                    "production-ready."
                ),
                snapshot=theme_service._family_version_fingerprint_payload(version),
                theme_family_version_id=_id(version),
            )
        )

        configuration.lifecycle_status = "approved"
        configuration.approved_by = actor
        configuration.approved_at = now
        configuration.updated_by = actor
        configuration.updated_at = now
        configuration.integrity_fingerprint = (
            theme_service._website_configuration_fingerprint_from_record(configuration)
        )
        session.add(configuration)
        approval_audits.append(
            theme_service._append_audit(
                session,
                action_type="website_configuration_approved",
                actor=actor,
                rationale="Approve the exact Performance Local V5 component graph.",
                snapshot=theme_service._website_configuration_fingerprint_payload(
                    configuration
                ),
                website_theme_configuration_id=_id(configuration),
            )
        )

        materialized_theme = _materialize_theme(
            session,
            website=website,
            source_theme=source_theme,
            actor=actor,
            now=now,
        )
        selection = _replace_selection(
            session,
            website=website,
            prior_selection=prior_selection,
            theme=materialized_theme,
            actor=actor,
            now=now,
        )

        configuration.lifecycle_status = "active"
        configuration.activated_by = actor
        configuration.activated_at = now
        configuration.materialized_theme_id = _id(materialized_theme)
        configuration.website_theme_selection_id = _id(selection)
        configuration.updated_at = now
        configuration.integrity_fingerprint = (
            theme_service._website_configuration_fingerprint_from_record(configuration)
        )
        session.add(configuration)
        approval_audits.append(
            theme_service._append_audit(
                session,
                action_type="website_configuration_activated",
                actor=actor,
                rationale="Select the exact durable Performance Local V5 Website graph.",
                snapshot=theme_service._website_configuration_fingerprint_payload(
                    configuration
                ),
                website_theme_configuration_id=_id(configuration),
            )
        )

        for component in created_components.values():
            component.activation_identity = actor
            component.activated_at = now
            component.updated_at = now
            component.integrity_fingerprint = theme_service._component_fingerprint_from_record(
                component
            )
            session.add(component)
            approval_audits.append(
                theme_service._append_audit(
                    session,
                    action_type="component_activated",
                    actor=actor,
                    rationale="Activate this exact Performance Local V5 component revision.",
                    snapshot=theme_service._component_fingerprint_payload(component),
                    component_configuration_id=_id(component),
                )
            )

        session.flush()
        _validate_applied_graph(
            session,
            website=website,
            family=family,
            predecessor=predecessor,
            version=version,
            configuration=configuration,
            components=created_components,
            materialized_theme=materialized_theme,
            selection=selection,
            source_theme=source_theme,
            source_configuration=source_configuration,
            source_commit=source_commit,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return PerformanceLocalV5RegistrationApplyResult(
        status="APPLIED",
        website_id=website_id,
        identity=PerformanceLocalV5RegistrationIdentity(
            theme_family_id=_id(family),
            theme_family_version_id=_id(version),
            website_theme_configuration_id=_id(configuration),
            component_configuration_ids=sorted(
                _id(item) for item in created_components.values()
            ),
            materialized_theme_id=_id(materialized_theme),
            website_theme_selection_id=_id(selection),
        ),
        audit_ids=sorted(_id(item) for item in approval_audits),
    )


def _plan(
    session: Session,
    website_id: int,
    *,
    source_commit: str,
    lock: bool,
) -> PerformanceLocalV5RegistrationPlan:
    if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        raise PerformanceLocalV5RegistrationError(
            "V5 source commit must be an exact lowercase Git SHA.", status_code=422
        )
    website = _query_record(session, Website, website_id, "Website", lock=lock)
    if website.status != "active" or website.brand_id is None:
        return _conflict(website_id, source_commit, "Website scope is not active and branded.")
    try:
        family, predecessor = _locked_family_prerequisites(session, lock=lock)
        _source_v3_graph(session, website_id, lock=lock)
        _sole_active_selection(session, website, lock=lock)
    except (
        PerformanceLocalV5RegistrationError,
        theme_service.ThemeConfigurationError,
        runtime_theme_service.ThemeError,
    ) as exc:
        return _conflict(website_id, source_commit, str(exc))

    version_rows = _select_all(
        session,
        select(ThemeFamilyVersion).where(
            ThemeFamilyVersion.theme_family_id == family.id,
            ThemeFamilyVersion.version == PERFORMANCE_LOCAL_V5_FAMILY_VERSION,
        ),
        lock=lock,
    )
    configurations = _select_all(
        session,
        select(WebsiteThemeConfiguration).where(
            WebsiteThemeConfiguration.website_id == website_id,
            WebsiteThemeConfiguration.configuration_key
            == PERFORMANCE_LOCAL_V5_CONFIGURATION_KEY,
        ),
        lock=lock,
    )
    materialized_themes = _select_all(
        session,
        select(Theme).where(
            Theme.website_id == website_id,
            Theme.theme_key == PERFORMANCE_LOCAL_V5_THEME_KEY,
        ),
        lock=lock,
    )

    if not version_rows and not configurations and not materialized_themes:
        return PerformanceLocalV5RegistrationPlan(
            status="PLANNED",
            website_id=website_id,
            expected_source_commit=source_commit,
            expected_contract_fingerprint=PERFORMANCE_LOCAL_V5_CONTRACT_FINGERPRINT,
            identity=PerformanceLocalV5RegistrationIdentity(
                theme_family_id=_id(family)
            ),
            actions=[
                PerformanceLocalV5RegistrationAction(
                    order=index,
                    action=action,
                    target=target,
                )
                for index, (action, target) in enumerate(
                    (
                        ("register_family_version", "performance-local@5"),
                        ("create_configuration", PERFORMANCE_LOCAL_V5_CONFIGURATION_KEY),
                        ("create_component_graph", "three-node governed conversion graph"),
                        ("approve_family_version", "performance-local@5"),
                        ("approve_configuration", PERFORMANCE_LOCAL_V5_CONFIGURATION_KEY),
                        ("materialize_theme", PERFORMANCE_LOCAL_V5_THEME_KEY),
                        ("select_theme", PERFORMANCE_LOCAL_V5_THEME_KEY),
                        ("activate_configuration", PERFORMANCE_LOCAL_V5_CONFIGURATION_KEY),
                    ),
                    start=1,
                )
            ],
        )

    if len(version_rows) != 1 or len(configurations) != 1 or len(materialized_themes) != 1:
        return _conflict(
            website_id,
            source_commit,
            "Durable V5 resources are partial, duplicated, or cross-version.",
        )
    version = version_rows[0]
    configuration = configurations[0]
    materialized_theme = materialized_themes[0]
    components = _select_all(
        session,
        select(WebsiteThemeComponentConfiguration).where(
            WebsiteThemeComponentConfiguration.website_theme_configuration_id
            == configuration.id,
            WebsiteThemeComponentConfiguration.lifecycle_status == "current",
        ),
        lock=lock,
    )
    selection_rows = _select_all(
        session,
        select(WebsiteThemeSelection).where(
            WebsiteThemeSelection.id == configuration.website_theme_selection_id
        ),
        lock=lock,
    ) if configuration.website_theme_selection_id is not None else []
    if len(selection_rows) != 1:
        return _conflict(website_id, source_commit, "V5 selection identity is incomplete.")
    selection = selection_rows[0]
    prior_theme = _prior_theme_for_selection(session, selection)
    try:
        _validate_applied_graph(
            session,
            website=website,
            family=family,
            predecessor=predecessor,
            version=version,
            configuration=configuration,
            components={item.component_key: item for item in components},
            materialized_theme=materialized_theme,
            selection=selection,
            source_theme=prior_theme,
            source_configuration=_source_v3_graph(
                session, website_id, lock=lock
            )[1],
            source_commit=source_commit,
        )
    except (
        PerformanceLocalV5RegistrationError,
        theme_service.ThemeConfigurationError,
        runtime_theme_service.ThemeError,
    ) as exc:
        return _conflict(website_id, source_commit, str(exc))
    return PerformanceLocalV5RegistrationPlan(
        status="UNCHANGED",
        website_id=website_id,
        expected_source_commit=source_commit,
        expected_contract_fingerprint=PERFORMANCE_LOCAL_V5_CONTRACT_FINGERPRINT,
        identity=PerformanceLocalV5RegistrationIdentity(
            theme_family_id=_id(family),
            theme_family_version_id=_id(version),
            website_theme_configuration_id=_id(configuration),
            component_configuration_ids=sorted(_id(item) for item in components),
            materialized_theme_id=_id(materialized_theme),
            website_theme_selection_id=_id(selection),
        ),
    )


def _validate_applied_graph(
    session: Session,
    *,
    website: Website,
    family: ThemeFamily,
    predecessor: ThemeFamilyVersion,
    version: ThemeFamilyVersion,
    configuration: WebsiteThemeConfiguration,
    components: dict[str, WebsiteThemeComponentConfiguration],
    materialized_theme: Theme,
    selection: WebsiteThemeSelection,
    source_theme: Theme,
    source_configuration: WebsiteThemeConfiguration | None,
    source_commit: str,
) -> None:
    theme_service._validate_family(family)
    theme_service._validate_family_version(session, version)
    theme_service._validate_website_configuration(session, configuration)
    runtime_theme_service._validate_theme_record(
        session, materialized_theme, require_approved=True
    )
    if (
        family.family_key != "performance-local"
        or predecessor.theme_family_id != family.id
        or predecessor.version != 3
        or version.theme_family_id != family.id
        or version.version != 5
        or version.lifecycle_status != "approved"
        or not version.production_ready
        or version.source_commit != source_commit
        or version.supersedes_theme_family_version_id != predecessor.id
        or version.supported_component_contracts
        != list(PERFORMANCE_LOCAL_V5_COMPONENT_CONTRACTS)
        or version.compatibility_identity
        != theme_service.canonical_json_hash(
            {
                "family_key": "performance-local",
                "version": 5,
                "supported_component_contracts": list(
                    PERFORMANCE_LOCAL_V5_COMPONENT_CONTRACTS
                ),
            }
        )
    ):
        raise PerformanceLocalV5RegistrationError("V5 Family Version identity differs.")
    if (
        configuration.website_id != website.id
        or configuration.business_id != website.business_id
        or configuration.theme_family_version_id != version.id
        or configuration.configuration_key != PERFORMANCE_LOCAL_V5_CONFIGURATION_KEY
        or configuration.version != 1
        or configuration.lifecycle_status != "active"
        or configuration.materialized_theme_id != materialized_theme.id
        or configuration.website_theme_selection_id != selection.id
    ):
        raise PerformanceLocalV5RegistrationError("V5 Website configuration differs.")
    if len(components) != 3 or set(components) != _COMPONENT_KEYS:
        raise PerformanceLocalV5RegistrationError("V5 component graph is not exact.")
    for key, component in components.items():
        theme_service._validate_component_configuration(session, component)
        contract = _component_contract(key)
        if (
            component.website_id != website.id
            or component.website_theme_configuration_id != configuration.id
            or component.theme_family_version_id != version.id
            or component.component_contract_version != 5
            or component.scope_type != "website_default"
            or component.planned_page_id is not None
            or component.lifecycle_status != "current"
            or not component.enabled
            or component.placement != contract["placement"]
            or component.variant != contract["variant"]
            or component.responsive_visibility != contract["responsive_visibility"]
            or component.activation_identity is None
            or component.activated_at is None
            or component.rollback_identity is not None
            or component.rollback_at is not None
        ):
            raise PerformanceLocalV5RegistrationError(
                f"V5 component identity differs: {key}."
            )
    form_id = _id(components["compact_estimate_form"])
    if (
        components["compact_estimate_form"].destination_component_configuration_id
        is not None
        or components["campaign_banner"].destination_component_configuration_id
        != form_id
        or components["sticky_mobile_action_bar"].destination_component_configuration_id
        != form_id
    ):
        raise PerformanceLocalV5RegistrationError("V5 conversion destinations differ.")
    if source_configuration is not None:
        source_rows = _source_v3_graph(session, website.id)[0]
        for key in _COMPONENT_KEYS:
            if (
                components[key].configuration_payload
                != source_rows[key].configuration_payload
                or components[key].enabled != source_rows[key].enabled
                or components[key].component_instance_key
                != source_rows[key].component_instance_key
            ):
                raise PerformanceLocalV5RegistrationError(
                    f"V5 component is not the exact governed V3 input: {key}."
                )
    if (
        materialized_theme.website_id != website.id
        or materialized_theme.business_id != website.business_id
        or materialized_theme.brand_id != website.brand_id
        or materialized_theme.theme_key != PERFORMANCE_LOCAL_V5_THEME_KEY
        or materialized_theme.version != 1
        or materialized_theme.design_tokens != source_theme.design_tokens
        or materialized_theme.token_hash_sha256 != source_theme.token_hash_sha256
        or selection.website_id != website.id
        or selection.theme_id != materialized_theme.id
        or selection.status != "active"
    ):
        raise PerformanceLocalV5RegistrationError("Materialized V5 Theme/selection differs.")
    active = list(
        session.exec(
            select(WebsiteThemeSelection).where(
                WebsiteThemeSelection.website_id == website.id,
                WebsiteThemeSelection.status == "active",
            )
        ).all()
    )
    if len(active) != 1 or active[0].id != selection.id:
        raise PerformanceLocalV5RegistrationError("Website active selection is not singular.")


def _source_v3_graph(
    session: Session,
    website_id: int,
    *,
    lock: bool = False,
) -> tuple[dict[str, WebsiteThemeComponentConfiguration], WebsiteThemeConfiguration]:
    statement = (
        select(WebsiteThemeComponentConfiguration)
        .join(
            WebsiteThemeConfiguration,
            WebsiteThemeConfiguration.id
            == WebsiteThemeComponentConfiguration.website_theme_configuration_id,
        )
        .join(
            ThemeFamilyVersion,
            ThemeFamilyVersion.id
            == WebsiteThemeComponentConfiguration.theme_family_version_id,
        )
        .join(ThemeFamily, ThemeFamily.id == ThemeFamilyVersion.theme_family_id)
        .where(
            WebsiteThemeComponentConfiguration.website_id == website_id,
            WebsiteThemeComponentConfiguration.lifecycle_status == "current",
            WebsiteThemeComponentConfiguration.component_key.in_(_COMPONENT_KEYS),
            WebsiteThemeConfiguration.lifecycle_status.in_({"draft", "approved", "active"}),
            ThemeFamily.family_key == "performance-local",
            ThemeFamilyVersion.version == 3,
        )
    )
    rows = _select_all(session, statement, lock=lock)
    if len(rows) != 3 or {item.component_key for item in rows} != _COMPONENT_KEYS:
        raise PerformanceLocalV5RegistrationError(
            "Durable V3 governed conversion input is not one exact three-node graph."
        )
    configuration_ids = {item.website_theme_configuration_id for item in rows}
    if len(configuration_ids) != 1:
        raise PerformanceLocalV5RegistrationError("V3 components cross configurations.")
    configuration = _query_record(
        session,
        WebsiteThemeConfiguration,
        next(iter(configuration_ids)),
        "V3 Website Theme configuration",
        lock=lock,
    )
    for item in rows:
        theme_service._validate_component_configuration(session, item)
        if (
            not item.enabled
            or item.component_contract_version != 3
            or item.scope_type != "website_default"
            or item.planned_page_id is not None
            or item.rollback_identity is not None
            or item.rollback_at is not None
        ):
            raise PerformanceLocalV5RegistrationError(
                f"Durable V3 governed conversion input is not enabled and exact: {item.component_key}."
            )
    by_key = {item.component_key: item for item in rows}
    form_id = _id(by_key["compact_estimate_form"])
    if (
        by_key["compact_estimate_form"].destination_component_configuration_id
        is not None
        or by_key["campaign_banner"].destination_component_configuration_id
        != form_id
        or by_key["sticky_mobile_action_bar"].destination_component_configuration_id
        != form_id
    ):
        raise PerformanceLocalV5RegistrationError(
            "Durable V3 conversion actions do not target the exact governed form."
        )
    return by_key, configuration


def _locked_family_prerequisites(
    session: Session,
    *,
    lock: bool = True,
) -> tuple[ThemeFamily, ThemeFamilyVersion]:
    families = _select_all(
        session,
        select(ThemeFamily).where(ThemeFamily.family_key == "performance-local"),
        lock=lock,
    )
    if len(families) != 1:
        raise PerformanceLocalV5RegistrationError(
            "The existing Performance Local Theme Family is not singular."
        )
    family = families[0]
    theme_service._validate_family(family)
    versions = _select_all(
        session,
        select(ThemeFamilyVersion).where(
            ThemeFamilyVersion.theme_family_id == family.id,
            ThemeFamilyVersion.version == 3,
        ),
        lock=lock,
    )
    if len(versions) != 1:
        raise PerformanceLocalV5RegistrationError(
            "The immutable durable Performance Local V3 predecessor is missing."
        )
    predecessor = versions[0]
    theme_service._validate_family_version(session, predecessor)
    return family, predecessor


def _sole_active_selection(
    session: Session,
    website: Website,
    *,
    lock: bool,
) -> tuple[WebsiteThemeSelection, Theme]:
    statement = select(WebsiteThemeSelection).where(
        WebsiteThemeSelection.website_id == website.id,
        WebsiteThemeSelection.status == "active",
    )
    rows = _select_all(session, statement, lock=lock)
    if len(rows) != 1:
        raise PerformanceLocalV5RegistrationError(
            "Website must have one exact active Theme selection."
        )
    selection = rows[0]
    theme = _query_record(session, Theme, selection.theme_id, "active Theme", lock=lock)
    runtime_theme_service._validate_theme_record(session, theme, require_approved=True)
    if (
        theme.website_id != website.id
        or theme.business_id != website.business_id
        or theme.brand_id != website.brand_id
    ):
        raise PerformanceLocalV5RegistrationError("Active Theme crosses Website scope.")
    return selection, theme


def _materialize_theme(
    session: Session,
    *,
    website: Website,
    source_theme: Theme,
    actor: str,
    now: datetime,
) -> Theme:
    theme = Theme(
        website_id=_id(website),
        business_id=website.business_id,
        brand_id=website.brand_id,
        theme_key=PERFORMANCE_LOCAL_V5_THEME_KEY,
        theme_name="Performance Local V5",
        version=1,
        token_contract_version=source_theme.token_contract_version,
        design_tokens=deepcopy(source_theme.design_tokens),
        token_hash_sha256=source_theme.token_hash_sha256,
        description="Durable production-ready Performance Local V5 Website Theme.",
        lifecycle_status="available",
        approval_status="approved",
        created_by=actor,
        provenance_type="operator_configured",
        provenance_notes=(
            f"Materialized from governed Theme {source_theme.id} with unchanged token identity."
        ),
        approved_by=actor,
        approved_at=now,
    )
    session.add(theme)
    session.flush()
    runtime_theme_service._validate_theme_record(session, theme, require_approved=True)
    return theme


def _replace_selection(
    session: Session,
    *,
    website: Website,
    prior_selection: WebsiteThemeSelection,
    theme: Theme,
    actor: str,
    now: datetime,
) -> WebsiteThemeSelection:
    prior_selection.status = "replaced"
    prior_selection.replaced_at = now
    prior_selection.updated_at = now
    session.add(prior_selection)
    session.flush([prior_selection])
    latest = session.exec(
        select(WebsiteThemeSelection)
        .where(WebsiteThemeSelection.website_id == website.id)
        .order_by(WebsiteThemeSelection.version.desc())
    ).first()
    selection = WebsiteThemeSelection(
        website_id=_id(website),
        theme_id=_id(theme),
        version=(latest.version + 1) if latest else 1,
        status="active",
        selected_by=actor,
        rationale="Select the exact production-ready Performance Local V5 graph.",
        selected_at=now,
    )
    session.add(selection)
    session.flush()
    return selection


def _prior_theme_for_selection(
    session: Session,
    selection: WebsiteThemeSelection,
) -> Theme:
    prior = session.exec(
        select(WebsiteThemeSelection).where(
            WebsiteThemeSelection.website_id == selection.website_id,
            WebsiteThemeSelection.version == selection.version - 1,
            WebsiteThemeSelection.status == "replaced",
        )
    ).one_or_none()
    if prior is None:
        raise PerformanceLocalV5RegistrationError(
            "V5 selection lacks its exact preserved predecessor selection."
        )
    return _query_record(session, Theme, prior.theme_id, "prior Theme", lock=False)


def _component_contract(key: str) -> dict[str, Any]:
    matches = [
        contract
        for contract in PERFORMANCE_LOCAL_V5_COMPONENT_CONTRACTS
        if contract["component_key"] == key
    ]
    if len(matches) != 1:
        raise PerformanceLocalV5RegistrationError(f"V5 contract is missing {key}.")
    return matches[0]


def _conflict(
    website_id: int,
    source_commit: str,
    *blockers: str,
) -> PerformanceLocalV5RegistrationPlan:
    return PerformanceLocalV5RegistrationPlan(
        status="CONFLICT",
        website_id=website_id,
        expected_source_commit=source_commit,
        expected_contract_fingerprint=PERFORMANCE_LOCAL_V5_CONTRACT_FINGERPRINT,
        identity=PerformanceLocalV5RegistrationIdentity(),
        blockers=sorted(set(blockers)),
    )


def _select_all(session: Session, statement: Any, *, lock: bool) -> list[Any]:
    if lock:
        statement = statement.with_for_update()
    return list(session.exec(statement).all())


def _query_record(
    session: Session,
    model: Any,
    record_id: int,
    label: str,
    *,
    lock: bool,
) -> Any:
    statement = select(model).where(model.id == record_id)
    if lock:
        statement = statement.with_for_update()
    record = session.exec(statement).one_or_none()
    if record is None:
        raise PerformanceLocalV5RegistrationError(f"{label} was not found.")
    return record


def _locked_record(
    session: Session, model: Any, record_id: int, label: str
) -> Any:
    return _query_record(session, model, record_id, label, lock=True)


def _id(record: Any) -> int:
    value = getattr(record, "id", None)
    if type(value) is not int or value <= 0:
        raise PerformanceLocalV5RegistrationError("Durable identity was not assigned.")
    return value


def _pending_identity(session: Session) -> tuple[frozenset[int], frozenset[int], frozenset[int]]:
    return (
        frozenset(id(item) for item in session.new),
        frozenset(id(item) for item in session.dirty),
        frozenset(id(item) for item in session.deleted),
    )
