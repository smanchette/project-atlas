from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from app.schemas.theme_families import (
    CompactEstimateFormConfiguration,
    FormProviderStateRead,
    ProductionFormSubmissionContractRead,
    ProductionFormSubmissionPreflightInput,
    ProductionFormSubmissionReadinessItem,
    ProductionFormSubmissionReadinessRead,
)


class FormProviderError(ValueError):
    """Fail-closed error for a missing or incomplete submission-provider contract."""


@dataclass(frozen=True)
class NormalizedFormSubmissionEnvelope:
    """Provider-independent validated values for a future authorized submit path.

    No route constructs this envelope in the durable preview milestone. Keeping
    it immutable and provider-neutral prevents the public form contract from
    depending on email, CRM, WordPress, or any other delivery adapter.
    """

    website_id: int
    component_configuration_id: int
    name: str
    phone: str
    postal_code: str
    requested_service: str
    message: str | None
    consent_identity: str | None
    audit_identity: str


@dataclass(frozen=True)
class FormSubmissionResult:
    status: str
    provider_reference: str | None
    safe_message: str


@runtime_checkable
class FormSubmissionProvider(Protocol):
    """Future delivery adapter boundary; implementations own delivery only."""

    provider_key: str

    def submit(
        self,
        envelope: NormalizedFormSubmissionEnvelope,
    ) -> FormSubmissionResult: ...


# This milestone deliberately registers no delivery adapter. A mapping proxy
# makes accidental runtime registration impossible without an explicit source
# change and a separately authorized provider milestone.
FORM_SUBMISSION_PROVIDERS: Mapping[str, FormSubmissionProvider] = MappingProxyType({})


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
