from __future__ import annotations

from dataclasses import dataclass

from app.website_builder_core.contracts import FormDeliveryMode
from app.website_builder_core.registry import ProviderDescriptor


@dataclass(frozen=True)
class FormDeliveryReadinessBlocker:
    code: str
    field: str
    reason: str


@dataclass(frozen=True)
class FormDeliveryReadinessInput:
    mode: FormDeliveryMode
    lifecycle_status: str
    enabled: bool
    scope_valid: bool
    fingerprint_valid: bool
    website_enabled: bool
    component_enabled: bool
    approval_identity: str | None
    activation_identity: str | None
    provider_key: str | None
    adapter_version: str | None
    destination_identity: str | None
    privacy_policy_reference: str | None
    consent_required: bool
    consent_policy_reference: str | None
    retention_policy_reference: str | None
    abuse_policy_reference: str | None
    success_behavior: str | None
    failure_behavior: str | None
    idempotency_policy_reference: str | None
    audit_identity: str | None
    verified_recipient_count: int = 0
    verified_primary_recipient_count: int = 0
    notification_preference: str | None = None
    secret_reference_configured: bool = False
    secure_payload_store_available: bool = False
    provider_owned_presentation_ready: bool = False
    form_contract_version: int = 1
    website_identity: str = "*"


@dataclass(frozen=True)
class FormDeliveryReadiness:
    status: str
    can_present: bool
    can_submit: bool
    provider_owner: str
    data_collector: str
    retention_owner: str
    atlas_stores_customer_data: bool
    external_request_behavior: str
    production_enabled: bool
    blockers: tuple[FormDeliveryReadinessBlocker, ...]


def evaluate_form_delivery_readiness(
    value: FormDeliveryReadinessInput,
    provider: ProviderDescriptor | None,
) -> FormDeliveryReadiness:
    blockers: list[FormDeliveryReadinessBlocker] = []

    def require(condition: bool, code: str, field: str, reason: str) -> None:
        if not condition:
            blockers.append(FormDeliveryReadinessBlocker(code, field, reason))

    require(value.scope_valid, "invalid_form_scope", "scope", "The mode crosses its Website or form scope.")
    require(value.fingerprint_valid, "invalid_mode_fingerprint", "integrity_fingerprint", "The mode fingerprint is invalid.")
    require(value.website_enabled, "disabled_website", "website", "The Website is disabled.")
    require(value.component_enabled, "disabled_form_component", "form_component", "The form component is disabled.")

    if value.mode == "disabled":
        require(not value.enabled, "invalid_disabled_mode", "enabled", "Disabled mode cannot be enabled.")
        require(value.provider_key is None, "invalid_disabled_provider", "provider_key", "Disabled mode cannot name a provider.")
        require(value.destination_identity is None, "invalid_disabled_destination", "destination_identity", "Disabled mode cannot name a destination.")
        return FormDeliveryReadiness(
            status="disabled" if not blockers else "blocked",
            can_present=False,
            can_submit=False,
            provider_owner="none",
            data_collector="none",
            retention_owner="none",
            atlas_stores_customer_data=False,
            external_request_behavior="none",
            production_enabled=False,
            blockers=tuple(blockers),
        )

    require(value.lifecycle_status == "active", "mode_not_active", "lifecycle_status", "The current mode revision is not active.")
    require(value.enabled, "mode_not_enabled", "enabled", "The current mode revision is not enabled.")
    require(bool(value.approval_identity), "missing_mode_approval", "approval_identity", "Approved configuration evidence is required.")
    require(bool(value.activation_identity), "missing_mode_activation", "activation_identity", "Activation evidence is required.")
    require(bool(value.provider_key), "missing_provider", "provider_key", "A provider identity is required.")
    require(bool(value.adapter_version), "missing_adapter_version", "adapter_version", "An adapter version is required.")
    require(bool(value.destination_identity), "missing_destination", "destination_identity", "A governed destination identity is required.")
    require(bool(value.audit_identity), "missing_audit_identity", "audit_identity", "An audit identity is required.")

    compatible = bool(
        provider
        and value.provider_key == provider.provider_key
        and value.adapter_version == provider.adapter_version
        and provider.supports(
            mode=value.mode,
            form_contract_version=value.form_contract_version,
            website_identity=value.website_identity,
        )
    )
    require(compatible, "provider_adapter_unavailable", "provider_key", "No compatible enabled adapter is installed.")

    if value.mode == "provider_owned":
        require(bool(value.privacy_policy_reference), "missing_privacy_policy", "privacy_policy_reference", "An approved provider privacy-policy reference is required.")
        require(value.provider_owned_presentation_ready, "provider_presentation_unavailable", "configuration_payload", "The provider-owned presentation is not safe and ready.")
        owner = provider.provider_type if provider else "external_provider"
        return FormDeliveryReadiness(
            status="ready" if not blockers else "blocked",
            can_present=not blockers,
            can_submit=False,
            provider_owner=owner,
            data_collector="external_provider",
            retention_owner=provider.retention_owner if provider else "external_provider",
            atlas_stores_customer_data=False,
            external_request_behavior=provider.external_request_behavior if provider else "provider_owned",
            production_enabled=not blockers,
            blockers=tuple(blockers),
        )

    for condition, code, field, reason in (
        (bool(value.privacy_policy_reference), "missing_privacy_policy", "privacy_policy_reference", "An approved privacy-policy reference is required."),
        (not value.consent_required or bool(value.consent_policy_reference), "missing_consent_policy", "consent_policy_reference", "An approved consent-policy reference is required."),
        (bool(value.retention_policy_reference), "missing_retention_policy", "retention_policy_reference", "An approved retention-policy reference is required."),
        (bool(value.abuse_policy_reference), "missing_abuse_policy", "abuse_policy_reference", "An approved abuse policy is required."),
        (bool(value.success_behavior), "missing_success_behavior", "success_behavior", "An approved success behavior is required."),
        (bool(value.failure_behavior), "missing_failure_behavior", "failure_behavior", "An approved failure behavior is required."),
        (bool(value.idempotency_policy_reference), "missing_idempotency_policy", "idempotency_policy_reference", "An approved idempotency policy is required."),
        (value.secure_payload_store_available, "secure_payload_store_unavailable", "payload_storage", "Secure payload storage and key management are unavailable."),
    ):
        require(condition, code, field, reason)

    if value.mode == "atlas_email":
        recipient_ready = (
            value.verified_primary_recipient_count > 0
            if value.notification_preference == "primary_only"
            else value.verified_recipient_count > 0
        )
        require(recipient_ready, "blocked_missing_verified_recipient", "recipients", "The configured notification preference has no enabled verified recipient.")
    if provider and provider.secret_reference_required:
        require(value.secret_reference_configured, "missing_secret_reference", "secret_reference", "An active opaque secret reference is required.")

    return FormDeliveryReadiness(
        status="ready" if not blockers else "blocked",
        can_present=not blockers,
        can_submit=not blockers,
        provider_owner=provider.provider_type if provider else "unavailable",
        data_collector="atlas",
        retention_owner=provider.retention_owner if provider else "atlas",
        atlas_stores_customer_data=not blockers,
        external_request_behavior=provider.external_request_behavior if provider else "none",
        production_enabled=not blockers,
        blockers=tuple(blockers),
    )
