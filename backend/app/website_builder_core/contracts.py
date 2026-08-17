from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal, Protocol, runtime_checkable

from app.website_builder_core.configuration_safety import (
    FINGERPRINT_PATTERN,
    KEY_PATTERN,
    SOURCE_REFERENCE_PATTERN,
)


FormDeliveryMode = Literal[
    "disabled",
    "atlas_email",
    "provider_owned",
    "atlasops360_native",
    "external_adapter",
]

FORM_DELIVERY_MODES = frozenset(
    {
        "disabled",
        "atlas_email",
        "provider_owned",
        "atlasops360_native",
        "external_adapter",
    }
)
ATLAS_OWNED_FORM_MODES = frozenset(
    {"atlas_email", "atlasops360_native", "external_adapter"}
)

FormFieldValueKind = Literal["text", "phone", "postal_code", "free_text"]
NormalizedEnvelopeField = Literal[
    "name",
    "phone",
    "postal_code",
    "requested_service",
    "message",
]


@dataclass(frozen=True)
class NormalizedFormFieldDefinition:
    """One provider-neutral field mapped to the normalized envelope."""

    field_key: str
    envelope_field: NormalizedEnvelopeField
    required: bool
    value_kind: FormFieldValueKind
    order: int
    minimum_length: int
    maximum_length: int

    def __post_init__(self) -> None:
        if not self.field_key or self.field_key.strip() != self.field_key:
            raise ValueError("A normalized form field requires a stable field key.")
        if self.order < 1:
            raise ValueError("A normalized form field order must be positive.")
        if self.minimum_length < 0 or self.maximum_length < self.minimum_length:
            raise ValueError("A normalized form field requires bounded lengths.")


@dataclass(frozen=True)
class NormalizedFormDefinition:
    """Immutable shared form/component contract used by every delivery mode."""

    component_key: str
    contract_version: int
    fields: tuple[NormalizedFormFieldDefinition, ...]

    def __post_init__(self) -> None:
        if not self.component_key or self.component_key.strip() != self.component_key:
            raise ValueError("A normalized form definition requires a component key.")
        if self.contract_version < 1:
            raise ValueError("A normalized form contract version must be positive.")
        if not self.fields:
            raise ValueError("A normalized form definition requires fields.")
        if tuple(field.order for field in self.fields) != tuple(
            range(1, len(self.fields) + 1)
        ):
            raise ValueError("Normalized form fields must use contiguous ordered positions.")
        if len({field.field_key for field in self.fields}) != len(self.fields):
            raise ValueError("Normalized form field keys must be unique.")
        if len({field.envelope_field for field in self.fields}) != len(self.fields):
            raise ValueError("Normalized envelope mappings must be unique.")


@dataclass(frozen=True)
class FormRequestSecurityPolicy:
    request_size_limit_bytes: int
    require_same_origin: bool
    require_csrf_token: bool
    require_idempotency_key: bool

    def __post_init__(self) -> None:
        if not 1024 <= self.request_size_limit_bytes <= 1_048_576:
            raise ValueError("The form request-size limit is outside the safe range.")


UNIVERSAL_ESTIMATE_FORM_DEFINITION = NormalizedFormDefinition(
    component_key="compact_estimate_form",
    contract_version=3,
    fields=(
        NormalizedFormFieldDefinition("name", "name", True, "text", 1, 1, 100),
        NormalizedFormFieldDefinition("phone", "phone", True, "phone", 2, 7, 40),
        NormalizedFormFieldDefinition(
            "postal-code", "postal_code", True, "postal_code", 3, 5, 12
        ),
        NormalizedFormFieldDefinition(
            "requested-service", "requested_service", True, "text", 4, 1, 160
        ),
        NormalizedFormFieldDefinition(
            "message", "message", False, "free_text", 5, 0, 2000
        ),
    ),
)
UNIVERSAL_FORM_REQUEST_SECURITY = FormRequestSecurityPolicy(
    request_size_limit_bytes=65_536,
    require_same_origin=True,
    require_csrf_token=True,
    require_idempotency_key=True,
)


class IdempotencyConflict(Exception):
    """Provider-neutral signal for a replay key bound to different content."""


@dataclass(frozen=True)
class NormalizedSubmissionEnvelope:
    """The single provider-neutral five-field submission contract.

    Values live only in this in-memory contract unless an authorized secure
    payload store accepts them. Provider-specific fields are intentionally
    excluded.
    """

    website_id: int
    component_configuration_id: int
    name: str
    phone: str
    postal_code: str
    requested_service: str
    message: str | None
    consent_accepted: bool | None
    audit_identity: str
    idempotency_key: str
    component_revision: int | None = None
    delivery_mode_revision_id: int | None = None
    submission_contract_version: int = 1
    consent_version: str | None = None
    privacy_policy_identity: str | None = None
    retention_policy_identity: str | None = None
    abuse_policy_identity: str | None = None
    anti_spam_decision: str | None = None
    request_identity: str | None = None
    source_page_identity: str | None = None
    destination_adapter_key: str | None = None
    received_at: datetime | None = None

    def __post_init__(self) -> None:
        positive_identities = (
            self.website_id,
            self.component_configuration_id,
            self.submission_contract_version,
        )
        if any(value < 1 for value in positive_identities):
            raise ValueError("Normalized submission identities must be positive.")
        for value in (self.component_revision, self.delivery_mode_revision_id):
            if value is not None and value < 1:
                raise ValueError("Optional normalized submission identities must be positive.")
        if not KEY_PATTERN.fullmatch(self.audit_identity):
            raise ValueError("The submission audit identity must be a stable governed key.")
        if not self.idempotency_key or len(self.idempotency_key) > 200 or any(
            ord(character) < 32 or ord(character) == 127
            for character in self.idempotency_key
        ):
            raise ValueError("The submission idempotency key is invalid.")
        if self.request_identity is not None and not FINGERPRINT_PATTERN.fullmatch(
            self.request_identity
        ):
            raise ValueError("The request identity must be an opaque digest.")
        for label, value in (
            ("anti-spam decision", self.anti_spam_decision),
            ("consent version", self.consent_version),
            ("destination adapter", self.destination_adapter_key),
        ):
            if value is not None and not KEY_PATTERN.fullmatch(value):
                raise ValueError(f"The {label} must be a stable governed key.")
        if self.source_page_identity is not None and not SOURCE_REFERENCE_PATTERN.fullmatch(
            self.source_page_identity
        ):
            raise ValueError("The source page identity must be an opaque reference.")


@dataclass(frozen=True)
class ProviderDeliveryContext:
    """Credential-free governed delivery metadata."""

    provider_key: str
    destination_reference: str
    secret_reference: str
    audit_identity: str
    privacy_policy_destination: str
    consent_mode: str
    consent_text_version: str | None
    retention_duration: str
    deletion_expiration_behavior: str
    spam_strategy: str
    spam_configuration_reference: str
    success_behavior: str
    failure_behavior: str


@dataclass(frozen=True)
class DeliveryAttemptResult:
    outcome: Literal["delivered", "transient_failure", "permanent_failure"]
    safe_error_code: str | None = None
    safe_provider_reference: str | None = None


@dataclass(frozen=True)
class DeliveryRecipientSnapshot:
    """One exact in-memory recipient resolved from immutable Atlas evidence."""

    recipient_key: str
    normalized_email: str
    recipient_role: Literal["primary", "secondary"]


@dataclass(frozen=True)
class DeliveryAdapterContext:
    """Credential-free provider context; it has no Atlas persistence dependency."""

    delivery_identity: str
    idempotency_digest: str
    mode: FormDeliveryMode
    provider_key: str
    adapter_version: str
    destination_identity: str
    configuration_references: tuple[tuple[str, str], ...]
    privacy_policy_reference: str
    consent_required: bool
    consent_policy_reference: str | None
    retention_policy_reference: str
    abuse_policy_reference: str
    idempotency_policy_reference: str
    audit_identity: str
    recipients: tuple[DeliveryRecipientSnapshot, ...] = ()


@dataclass(frozen=True)
class FormDeliveryPresentation:
    kind: Literal[
        "external_link",
        "hosted_route",
        "sandboxed_iframe",
        "adapter_embed",
    ]
    destination: str
    title: str
    ownership_disclosure: str
    approved_origin: str
    sandbox_policy: str | None = None
    referrer_policy: str | None = None


@runtime_checkable
class SubmissionProvider(Protocol):
    provider_key: str

    def submit(
        self,
        context: ProviderDeliveryContext,
        envelope: NormalizedSubmissionEnvelope,
    ) -> object: ...


@runtime_checkable
class DeliveryAdapter(Protocol):
    provider_key: str

    def deliver(
        self,
        context: DeliveryAdapterContext,
        envelope: NormalizedSubmissionEnvelope,
    ) -> DeliveryAttemptResult: ...


@runtime_checkable
class PresentationAdapter(Protocol):
    provider_key: str

    def presentation(self, configuration: dict[str, object]) -> FormDeliveryPresentation: ...


@runtime_checkable
class SpamControlAdapter(Protocol):
    strategy: str

    def supports_reference(self, configuration_reference: str) -> bool: ...

    def verify(
        self,
        context: ProviderDeliveryContext,
        envelope: NormalizedSubmissionEnvelope,
    ) -> None: ...


@runtime_checkable
class IdempotencyBoundary(Protocol):
    strategy: str

    def deliver(
        self,
        *,
        namespace: str,
        request_identity: str,
        operation: Callable[[], object],
    ) -> object: ...
