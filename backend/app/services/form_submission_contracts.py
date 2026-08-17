from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError
from sqlmodel import Session

from app.models import Website, WebsiteThemeComponentConfiguration
from app.schemas.theme_families import (
    CompactEstimateFormConfiguration,
    CompactEstimateFormConfigurationV3,
    FormBehaviorReadinessStateRead,
    FormPrivacyReadinessStateRead,
    FormProviderStateRead,
    FormProviderReadinessStateRead,
    FormReadinessItemRead,
    FormRetentionReadinessStateRead,
    FormSecurityReadinessStateRead,
    FormSpamReadinessStateRead,
    PerformanceLocalFormReadinessRead,
    ProductionFormSubmissionContractRead,
    ProductionFormSubmissionPreflightInput,
    ProductionFormSubmissionReadinessItem,
    ProductionFormSubmissionReadinessRead,
)
from app.services.form_delivery_registry import PRODUCTION_SUBMISSION_PROVIDERS
from app.website_builder_core.contracts import (
    FormRequestSecurityPolicy,
    NormalizedFormDefinition,
    NormalizedSubmissionEnvelope,
    SubmissionProvider,
    UNIVERSAL_ESTIMATE_FORM_DEFINITION,
    UNIVERSAL_FORM_REQUEST_SECURITY,
)


class FormProviderError(ValueError):
    """Fail-closed error for a missing or incomplete submission-provider contract."""


def _spam_adapter_supports(
    adapter: object | None,
    configuration_reference: str | None,
) -> bool:
    if adapter is None or not configuration_reference:
        return False
    try:
        return bool(adapter.supports_reference(configuration_reference))  # type: ignore[attr-defined]
    except Exception:
        return False


# Compatibility names over the single shared Website Builder Core contracts.
NormalizedFormSubmissionEnvelope = NormalizedSubmissionEnvelope
FormSubmissionProvider = SubmissionProvider


@dataclass(frozen=True)
class FormSubmissionResult:
    status: str
    provider_reference: str | None
    safe_message: str


@dataclass(frozen=True)
class UniversalFormGatewayScope:
    """Scalar persistence projection for the provider-neutral gateway."""

    website_id: int
    website_public_url: str
    component_configuration_id: int
    component_instance_key: str
    component_revision: int
    component_integrity_fingerprint: str
    definition: NormalizedFormDefinition
    security: FormRequestSecurityPolicy


def resolve_universal_form_gateway_scope(
    session: Session,
    website_id: int,
    component_configuration_id: int,
) -> UniversalFormGatewayScope | None:
    """Adapt Atlas persistence to the one shared form-definition contract."""

    website = session.get(Website, website_id)
    component = session.get(
        WebsiteThemeComponentConfiguration,
        component_configuration_id,
    )
    if website is None or component is None:
        return None
    definition = UNIVERSAL_ESTIMATE_FORM_DEFINITION
    if (
        component.website_id != website_id
        or component.component_key != definition.component_key
        or component.component_contract_version != definition.contract_version
        or component.lifecycle_status != "current"
        or not component.enabled
        or component.scope_type != "website_default"
        or component.planned_page_id is not None
        or component.overrides_component_configuration_id is not None
    ):
        return None
    return UniversalFormGatewayScope(
        website_id=website.id,
        website_public_url=website.public_url,
        component_configuration_id=component.id,
        component_instance_key=component.component_instance_key,
        component_revision=component.revision,
        component_integrity_fingerprint=component.integrity_fingerprint,
        definition=definition,
        security=UNIVERSAL_FORM_REQUEST_SECURITY,
    )


# Backward-compatible name over the one canonical sealed production registry.
# It remains empty for this milestone.
FORM_SUBMISSION_PROVIDERS: Mapping[str, FormSubmissionProvider] = (
    PRODUCTION_SUBMISSION_PROVIDERS
)


def provider_disabled_state() -> FormProviderStateRead:
    return FormProviderStateRead(
        submission_state="disabled_pending_provider_configuration",
        provider_key=None,
        destination=None,
        can_submit=False,
        collects_data=False,
    )


def validate_provider_disabled_form(
    configuration: CompactEstimateFormConfiguration,
) -> None:
    """Revalidate that a durable preview form cannot collect or deliver data."""

    if configuration.submission_state != "disabled_pending_provider_configuration":
        raise FormProviderError("The draft form is not in the provider-disabled state.")
    if any(
        value is not None
        for value in (
            configuration.provider_key,
            configuration.destination,
            configuration.privacy_policy_destination,
            configuration.consent_language,
            configuration.data_retention_policy,
            configuration.spam_strategy,
            configuration.success_behavior,
            configuration.failure_behavior,
            configuration.audit_identity,
        )
    ):
        raise FormProviderError(
            "The provider-disabled form may not contain delivery, privacy, or submission configuration."
        )
    if FORM_SUBMISSION_PROVIDERS:
        raise FormProviderError("No form provider may be registered for this preview milestone.")


def require_submission_provider(provider_key: str | None) -> FormSubmissionProvider:
    """Fail closed until a future milestone explicitly registers a provider."""

    if not provider_key:
        raise FormProviderError(
            "Form submission is disabled pending provider configuration."
        )
    provider = FORM_SUBMISSION_PROVIDERS.get(provider_key)
    if provider is None:
        raise FormProviderError("The requested submission provider is not registered.")
    return provider


def production_form_submission_readiness(
    payload: ProductionFormSubmissionPreflightInput,
) -> ProductionFormSubmissionReadinessRead:
    """Evaluate production form governance without persisting or delivering anything."""

    blockers: list[ProductionFormSubmissionReadinessItem] = []

    def require(field: str, value: str | None, code: str, reason: str) -> None:
        if value is None:
            blockers.append(
                ProductionFormSubmissionReadinessItem(
                    code=code,
                    field=field,
                    reason=reason,
                )
            )

    require(
        "provider_key",
        payload.provider_key,
        "missing_provider",
        "A production submission provider identity is required.",
    )
    require(
        "destination",
        payload.destination,
        "missing_destination",
        "A governed production delivery destination is required.",
    )
    require(
        "privacy_policy_destination",
        payload.privacy_policy_destination,
        "missing_privacy_policy_destination",
        "An approved privacy-policy destination is required.",
    )
    if payload.consent_required:
        require(
            "consent_language",
            payload.consent_language,
            "missing_consent_language",
            "Approved consent language is required when consent is required.",
        )
    require(
        "data_retention_policy",
        payload.data_retention_policy,
        "missing_data_retention_policy",
        "An approved data-retention policy is required.",
    )
    require(
        "spam_strategy",
        payload.spam_strategy,
        "missing_spam_strategy",
        "An approved spam and abuse-control strategy is required.",
    )
    require(
        "success_behavior",
        payload.success_behavior,
        "missing_success_behavior",
        "An approved success behavior is required.",
    )
    require(
        "failure_behavior",
        payload.failure_behavior,
        "missing_failure_behavior",
        "An approved failure behavior is required.",
    )
    require(
        "audit_identity",
        payload.audit_identity,
        "missing_audit_identity",
        "An exact production submission audit identity is required.",
    )
    if payload.secret_handling_policy != "external_secret_manager_reference_only":
        blockers.append(
            ProductionFormSubmissionReadinessItem(
                code="insecure_secret_handling",
                field="secret_handling_policy",
                reason=(
                    "Provider credentials must remain outside Atlas records and be referenced "
                    "only through an authorized external secret manager."
                ),
            )
        )

    contract_blockers = list(blockers)
    contract_complete = not contract_blockers
    contract = (
        ProductionFormSubmissionContractRead(
            provider_key=payload.provider_key,
            destination=payload.destination,
            privacy_policy_destination=payload.privacy_policy_destination,
            consent_required=payload.consent_required,
            consent_language=payload.consent_language,
            data_retention_policy=payload.data_retention_policy,
            spam_strategy=payload.spam_strategy,
            success_behavior=payload.success_behavior,
            failure_behavior=payload.failure_behavior,
            audit_identity=payload.audit_identity,
            secret_handling_policy=payload.secret_handling_policy,
        )
        if contract_complete
        else None
    )
    blockers.append(
        ProductionFormSubmissionReadinessItem(
            code="provider_adapter_unavailable",
            field="provider_key",
            reason="No production submission provider adapter is registered in this milestone.",
        )
    )
    return ProductionFormSubmissionReadinessRead(
        contract_complete=contract_complete,
        contract=contract,
        blockers=blockers,
    )

def _blocker(code: str, field: str, reason: str) -> FormReadinessItemRead:
    return FormReadinessItemRead(code=code, field=field, reason=reason)


def _missing_form_readiness(
    *,
    component_configuration_id: int | None = None,
    submission_state: str = "missing",
    initial: list[FormReadinessItemRead] | None = None,
) -> PerformanceLocalFormReadinessRead:
    blockers = list(initial or [])
    if not blockers:
        blockers.append(
            _blocker(
                "form_contract_unavailable",
                "configuration_payload",
                "The legacy Theme form contract is unavailable.",
            )
        )
    return PerformanceLocalFormReadinessRead(
        status="blocked",
        can_submit=False,
        submission_state=submission_state,
        component_configuration_id=component_configuration_id,
        provider_state=FormProviderReadinessStateRead(
            provider_key=None,
            destination_configured=False,
            adapter_registered=False,
            test_only=False,
        ),
        privacy=FormPrivacyReadinessStateRead(
            destination_configured=False,
            consent_mode=None,
            consent_text_version=None,
            ready=False,
        ),
        retention=FormRetentionReadinessStateRead(
            duration_configured=False,
            deletion_behavior_configured=False,
            ready=False,
        ),
        spam=FormSpamReadinessStateRead(strategy=None, ready=False),
        behavior=FormBehaviorReadinessStateRead(
            success_configured=False,
            failure_configured=False,
            ready=False,
        ),
        security=FormSecurityReadinessStateRead(
            secret_reference_configured=False,
            same_origin_policy=None,
            csrf_policy=None,
            csrf_token=None,
            request_size_limit_bytes=None,
            idempotency_strategy=None,
            ready=False,
        ),
        audit_identity=None,
        blockers=blockers,
    )


def evaluate_performance_local_form_readiness(
    component: WebsiteThemeComponentConfiguration | None,
    *,
    mode: Literal["active", "inactive_draft_preview", "activation_rehearsal"],
    test_environment_allowed: bool | None = None,
) -> PerformanceLocalFormReadinessRead:
    # Theme/V3 adaptation lives here; the universal gateway imports none of
    # these concrete schemas or registries.
    from app.services import form_submission_gateway as gateway

    disposable_rehearsal_environment_allowed = (
        gateway.disposable_rehearsal_environment_allowed
    )
    TEST_ONLY_SUBMISSION_PROVIDERS = gateway.TEST_ONLY_SUBMISSION_PROVIDERS
    PRODUCTION_SUBMISSION_PROVIDERS = gateway.PRODUCTION_SUBMISSION_PROVIDERS
    TEST_ONLY_SPAM_CONTROLS = gateway.TEST_ONLY_SPAM_CONTROLS
    PRODUCTION_SPAM_CONTROLS = gateway.PRODUCTION_SPAM_CONTROLS
    TEST_ONLY_IDEMPOTENCY_BOUNDARIES = gateway.TEST_ONLY_IDEMPOTENCY_BOUNDARIES
    PRODUCTION_IDEMPOTENCY_BOUNDARIES = gateway.PRODUCTION_IDEMPOTENCY_BOUNDARIES
    _is_loopback_http_policy_destination = (
        gateway._is_loopback_http_policy_destination
    )
    _csrf_token = gateway._csrf_token

    if component is None:
        return _missing_form_readiness()

    try:
        contract = CompactEstimateFormConfigurationV3.model_validate(
            component.configuration_payload
        )
    except ValidationError:
        return _missing_form_readiness(
            component_configuration_id=component.id,
            submission_state="invalid",
            initial=[
                _blocker(
                    "invalid_form_contract",
                    "configuration_payload",
                    "The governed V3 form contract is invalid.",
                )
            ],
        )

    if test_environment_allowed is None:
        test_environment_allowed = disposable_rehearsal_environment_allowed()
    rehearsal_adapter = (
        mode == "activation_rehearsal"
        and contract.provider.test_only
        and test_environment_allowed
        and contract.provider.provider_key in TEST_ONLY_SUBMISSION_PROVIDERS
    )
    production_adapter = (
        mode == "active"
        and not contract.provider.test_only
        and contract.provider.provider_key in PRODUCTION_SUBMISSION_PROVIDERS
    )
    adapter_registered = rehearsal_adapter or production_adapter
    rehearsal_spam_adapter = TEST_ONLY_SPAM_CONTROLS.get(
        contract.spam.strategy or ""
    )
    production_spam_adapter = PRODUCTION_SPAM_CONTROLS.get(
        contract.spam.strategy or ""
    )
    rehearsal_spam_control = (
        mode == "activation_rehearsal"
        and contract.provider.test_only
        and test_environment_allowed
        and _spam_adapter_supports(
            rehearsal_spam_adapter,
            contract.spam.configuration_reference,
        )
    )
    production_spam_control = (
        mode == "active"
        and not contract.provider.test_only
        and _spam_adapter_supports(
            production_spam_adapter,
            contract.spam.configuration_reference,
        )
    )
    spam_control_registered = rehearsal_spam_control or production_spam_control
    idempotency_strategy = contract.security.idempotency_strategy
    rehearsal_idempotency_boundary = (
        mode == "activation_rehearsal"
        and contract.provider.test_only
        and test_environment_allowed
        and idempotency_strategy in TEST_ONLY_IDEMPOTENCY_BOUNDARIES
    )
    production_idempotency_boundary = (
        mode == "active"
        and not contract.provider.test_only
        and idempotency_strategy in PRODUCTION_IDEMPOTENCY_BOUNDARIES
    )
    idempotency_boundary_registered = (
        rehearsal_idempotency_boundary or production_idempotency_boundary
    )

    blockers: list[FormReadinessItemRead] = []

    def require(field: str, value: object, code: str, reason: str) -> None:
        if value is None or value is False or value == "":
            blockers.append(_blocker(code, field, reason))

    require(
        "provider.provider_key",
        contract.provider.provider_key,
        "missing_provider",
        "A governed submission-provider identity is required.",
    )
    require(
        "provider.destination",
        contract.provider.destination,
        "missing_provider_destination",
        "A governed provider destination is required.",
    )
    if not adapter_registered:
        blockers.append(
            _blocker(
                "provider_adapter_unavailable",
                "provider.provider_key",
                "No adapter is registered for this form in the current runtime mode.",
            )
        )
    require(
        "privacy.policy_destination",
        contract.privacy.policy_destination,
        "missing_privacy_destination",
        "An approved privacy-policy destination is required.",
    )
    active_loopback_privacy = (
        mode == "active"
        and _is_loopback_http_policy_destination(
            contract.privacy.policy_destination
        )
    )
    if active_loopback_privacy:
        blockers.append(
            _blocker(
                "loopback_privacy_destination_forbidden",
                "privacy.policy_destination",
                "Active delivery requires a relative or HTTPS privacy-policy destination.",
            )
        )
    require(
        "privacy.consent_mode",
        contract.privacy.consent_mode,
        "missing_consent_mode",
        "An approved consent mode is required.",
    )
    if contract.privacy.consent_mode == "explicit":
        require(
            "privacy.consent_text_version",
            contract.privacy.consent_text_version,
            "missing_consent_text_version",
            "Explicit consent requires an approved text version.",
        )
    require(
        "retention.duration",
        contract.retention.duration,
        "missing_retention_duration",
        "An approved retention duration is required.",
    )
    require(
        "retention.deletion_expiration_behavior",
        contract.retention.deletion_expiration_behavior,
        "missing_deletion_behavior",
        "An approved deletion or expiration behavior is required.",
    )
    require(
        "spam.strategy",
        contract.spam.strategy,
        "missing_spam_strategy",
        "An approved spam-control strategy is required.",
    )
    if not spam_control_registered:
        blockers.append(
            _blocker(
                "spam_adapter_unavailable",
                "spam.strategy",
                "No Atlas-owned spam-control adapter is registered for this strategy.",
            )
        )
    require(
        "success_behavior",
        contract.success_behavior,
        "missing_success_behavior",
        "An approved success behavior is required.",
    )
    require(
        "failure_behavior",
        contract.failure_behavior,
        "missing_failure_behavior",
        "An approved failure behavior is required.",
    )
    require(
        "provider.provider_secret_reference",
        contract.provider.provider_secret_reference,
        "missing_secret_reference",
        "An opaque provider secret reference is required.",
    )
    require(
        "security.same_origin_policy",
        contract.security.same_origin_policy,
        "missing_same_origin_policy",
        "An exact same-origin policy is required.",
    )
    require(
        "security.csrf_policy",
        contract.security.csrf_policy,
        "missing_csrf_policy",
        "An origin-and-token CSRF policy is required.",
    )
    require(
        "security.request_size_limit_bytes",
        contract.security.request_size_limit_bytes,
        "missing_request_size_policy",
        "A bounded request-size policy is required.",
    )
    require(
        "security.idempotency_strategy",
        contract.security.idempotency_strategy,
        "missing_idempotency_strategy",
        "A required-header idempotency strategy is required.",
    )
    if not idempotency_boundary_registered:
        blockers.append(
            _blocker(
                "idempotency_boundary_unavailable",
                "security.idempotency_strategy",
                "No Atlas-owned idempotency boundary is registered for this strategy.",
            )
        )
    require(
        "audit_identity",
        contract.audit_identity,
        "missing_audit_identity",
        "An exact form-governance audit identity is required.",
    )
    if contract.submission_state == "disabled_pending_provider_configuration":
        blockers.insert(
            0,
            _blocker(
                "submission_disabled",
                "submission_state",
                "Form submission is disabled pending governed configuration.",
            ),
        )
    if mode == "activation_rehearsal" and not test_environment_allowed:
        blockers.append(
            _blocker(
                "rehearsal_environment_refused",
                "provider.test_only",
                "The synthetic adapter is restricted to an explicit disposable loopback runtime.",
            )
        )
    if mode != "activation_rehearsal" and contract.provider.test_only:
        blockers.append(
            _blocker(
                "test_provider_containment",
                "provider.test_only",
                "A test-only provider cannot enter active delivery.",
            )
        )

    ready = not blockers
    privacy_ready = bool(
        contract.privacy.policy_destination
        and not active_loopback_privacy
        and contract.privacy.consent_mode
        and (
            contract.privacy.consent_mode != "explicit"
            or contract.privacy.consent_text_version
        )
    )
    retention_ready = bool(
        contract.retention.duration
        and contract.retention.deletion_expiration_behavior
    )
    behavior_ready = bool(contract.success_behavior and contract.failure_behavior)
    security_ready = bool(
        contract.provider.provider_secret_reference
        and contract.security.same_origin_policy
        and contract.security.csrf_policy
        and contract.security.request_size_limit_bytes
        and contract.security.idempotency_strategy
        and idempotency_boundary_registered
    )
    return PerformanceLocalFormReadinessRead(
        status="ready" if ready else "blocked",
        can_submit=ready,
        submission_state=contract.submission_state,
        component_configuration_id=component.id,
        provider_state=FormProviderReadinessStateRead(
            provider_key=contract.provider.provider_key,
            destination_configured=contract.provider.destination is not None,
            adapter_registered=adapter_registered,
            test_only=contract.provider.test_only,
        ),
        privacy=FormPrivacyReadinessStateRead(
            destination_configured=contract.privacy.policy_destination is not None,
            consent_mode=contract.privacy.consent_mode,
            consent_text_version=contract.privacy.consent_text_version,
            ready=privacy_ready,
        ),
        retention=FormRetentionReadinessStateRead(
            duration_configured=contract.retention.duration is not None,
            deletion_behavior_configured=(
                contract.retention.deletion_expiration_behavior is not None
            ),
            ready=retention_ready,
        ),
        spam=FormSpamReadinessStateRead(
            strategy=contract.spam.strategy,
            ready=bool(contract.spam.strategy and spam_control_registered),
        ),
        behavior=FormBehaviorReadinessStateRead(
            success_configured=contract.success_behavior is not None,
            failure_configured=contract.failure_behavior is not None,
            ready=behavior_ready,
        ),
        security=FormSecurityReadinessStateRead(
            secret_reference_configured=(
                contract.provider.provider_secret_reference is not None
            ),
            same_origin_policy=contract.security.same_origin_policy,
            csrf_policy=contract.security.csrf_policy,
            csrf_token=(
                _csrf_token(component, contract.audit_identity)
                if security_ready and ready
                else None
            ),
            request_size_limit_bytes=contract.security.request_size_limit_bytes,
            idempotency_strategy=contract.security.idempotency_strategy,
            ready=security_ready,
        ),
        audit_identity=contract.audit_identity,
        blockers=blockers,
    )
