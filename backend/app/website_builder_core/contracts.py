from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
import unicodedata
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

DEFAULT_CUSTOMER_ENTRY_FIELD_COUNT = 5
MAXIMUM_CUSTOMER_ENTRY_FIELD_COUNT = 6
STANDARD_CUSTOMER_ENTRY_FIELD_KEYS = (
    "name",
    "phone",
    "postal_code",
    "requested_service",
    "message",
)
STANDARD_CUSTOMER_ENTRY_FIELD_LABELS = (
    "Name",
    "Phone",
    "ZIP code",
    "Requested Service",
    "Optional Message",
)
SYSTEM_FORM_CONTROL_KEYS = frozenset(
    {
        "consent",
        "consent_accepted",
        "consent_version",
        "privacy",
        "privacy_policy_identity",
        "terms",
        "honeypot",
        "captcha",
        "csrf",
        "csrf_token",
        "idempotency",
        "idempotency_key",
        "request_id",
        "request_identity",
        "website_id",
        "form_id",
        "component_configuration_id",
        "component_revision",
        "delivery_mode_revision_id",
        "submission_contract_version",
        "provider_key",
        "destination",
        "destination_adapter_key",
        "payload",
        "secret",
        "audit_identity",
        "retention_policy_identity",
        "abuse_policy_identity",
        "anti_spam_decision",
        "source_page_identity",
        "received_at",
        "optional_field",
        "optional_fields",
        "optional_field_definition_revision_identity",
    }
)
RESERVED_OPTIONAL_FIELD_KEYS = frozenset(STANDARD_CUSTOMER_ENTRY_FIELD_KEYS).union(
    SYSTEM_FORM_CONTROL_KEYS
)

OptionalFormFieldType = Literal[
    "email",
    "short_text",
    "dropdown",
    "radio",
    "checkbox",
    "date",
    "textarea",
]
OptionalFormFieldValidationRule = Literal[
    "email_address",
    "trimmed_text",
    "listed_choice",
    "boolean",
    "iso_date",
]

_OPTIONAL_FIELD_TYPES = frozenset(
    {
        "email",
        "short_text",
        "dropdown",
        "radio",
        "checkbox",
        "date",
        "textarea",
    }
)
_VALIDATION_RULE_BY_TYPE: dict[str, str] = {
    "email": "email_address",
    "short_text": "trimmed_text",
    "dropdown": "listed_choice",
    "radio": "listed_choice",
    "checkbox": "boolean",
    "date": "iso_date",
    "textarea": "trimmed_text",
}
_KEY_SEPARATOR_PATTERN = re.compile(r"[\s_-]+")
_NORMALIZED_FIELD_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_EMAIL_VALUE_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SENSITIVE_PURPOSE_TOKENS = frozenset(
    {
        "bank",
        "banking",
        "card",
        "credential",
        "credentials",
        "file",
        "medical",
        "password",
        "payload",
        "secret",
        "ssn",
        "upload",
    }
)
_SENSITIVE_PURPOSE_PHRASES = (
    "account number",
    "bank account",
    "credit card",
    "debit card",
    "health information",
    "payment card",
    "provider payload",
    "raw payload",
    "routing number",
    "social security",
)


def normalize_form_field_key(value: str) -> str:
    """Return the one deterministic representation used for collision checks."""

    if not isinstance(value, str):
        raise ValueError("A form field key must be text.")
    normalized = _KEY_SEPARATOR_PATTERN.sub(
        "_",
        unicodedata.normalize("NFKC", value).strip().casefold(),
    )
    if len(normalized) > 120 or not _NORMALIZED_FIELD_KEY_PATTERN.fullmatch(
        normalized
    ):
        raise ValueError("A form field key must normalize to a stable snake-case key.")
    return normalized


def _clean_public_field_text(value: str, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    cleaned = unicodedata.normalize("NFC", value).strip()
    if (
        not cleaned
        or len(cleaned) > maximum
        or "<" in cleaned
        or ">" in cleaned
        or any(unicodedata.category(character).startswith("C") for character in cleaned)
    ):
        raise ValueError(
            f"{label} must be bounded plain text without markup or control characters."
        )
    return cleaned


def _reject_sensitive_field_purpose(*values: str | None) -> None:
    for value in values:
        if value is None:
            continue
        words = re.sub(
            r"[^a-z0-9]+",
            " ",
            unicodedata.normalize("NFKC", value).casefold(),
        ).strip()
        tokens = frozenset(words.split())
        if tokens.intersection(_SENSITIVE_PURPOSE_TOKENS) or any(
            phrase in words for phrase in _SENSITIVE_PURPOSE_PHRASES
        ):
            raise ValueError(
                "The optional field cannot request a forbidden sensitive or payload value."
            )


@dataclass(frozen=True)
class OptionalFormFieldValidationContract:
    """Small controlled rule set; callers cannot provide executable validation."""

    rule: OptionalFormFieldValidationRule
    minimum_length: int | None = None

    def __post_init__(self) -> None:
        if self.rule not in set(_VALIDATION_RULE_BY_TYPE.values()):
            raise ValueError("The optional field validation rule is not supported.")
        if self.minimum_length is not None and (
            isinstance(self.minimum_length, bool)
            or not isinstance(self.minimum_length, int)
            or not 0 <= self.minimum_length <= 10_000
        ):
            raise ValueError("The optional field minimum length is invalid.")


@dataclass(frozen=True)
class OptionalFormFieldChoice:
    choice_key: str
    public_label: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "choice_key", normalize_form_field_key(self.choice_key))
        object.__setattr__(
            self,
            "public_label",
            _clean_public_field_text(
                self.public_label,
                "An optional field choice label",
                maximum=160,
            ),
        )


@dataclass(frozen=True)
class OptionalFormFieldDefinition:
    """The one governed sixth customer-entry question for an Atlas-rendered form."""

    field_key: str
    public_label: str
    accessibility_label: str
    field_type: OptionalFormFieldType
    required: bool
    display_order: int
    maximum_length: int | None
    validation_contract: OptionalFormFieldValidationContract
    choices: tuple[OptionalFormFieldChoice, ...]
    provider_mapping_key: str
    help_text: str | None
    definition_revision_identity: str

    def __post_init__(self) -> None:
        if not isinstance(
            self.validation_contract,
            OptionalFormFieldValidationContract,
        ):
            raise ValueError("The optional field validation contract is invalid.")
        object.__setattr__(self, "field_key", normalize_form_field_key(self.field_key))
        object.__setattr__(
            self,
            "provider_mapping_key",
            normalize_form_field_key(self.provider_mapping_key),
        )
        object.__setattr__(
            self,
            "definition_revision_identity",
            normalize_form_field_key(self.definition_revision_identity),
        )
        if self.field_key in RESERVED_OPTIONAL_FIELD_KEYS:
            raise ValueError("The optional field key is reserved.")
        if self.provider_mapping_key in RESERVED_OPTIONAL_FIELD_KEYS:
            raise ValueError("The optional field provider mapping key is reserved.")
        object.__setattr__(
            self,
            "public_label",
            _clean_public_field_text(
                self.public_label,
                "The optional field public label",
                maximum=160,
            ),
        )
        object.__setattr__(
            self,
            "accessibility_label",
            _clean_public_field_text(
                self.accessibility_label,
                "The optional field accessibility label",
                maximum=160,
            ),
        )
        if self.help_text is not None:
            object.__setattr__(
                self,
                "help_text",
                _clean_public_field_text(
                    self.help_text,
                    "The optional field help text",
                    maximum=500,
                ),
            )
        _reject_sensitive_field_purpose(
            self.field_key,
            self.provider_mapping_key,
            self.public_label,
            self.accessibility_label,
            self.help_text,
        )
        object.__setattr__(self, "choices", tuple(self.choices))
        if any(
            not isinstance(choice, OptionalFormFieldChoice)
            for choice in self.choices
        ):
            raise ValueError("The optional field choices are invalid.")
        for choice in self.choices:
            _reject_sensitive_field_purpose(
                choice.choice_key,
                choice.public_label,
            )

        if self.field_type not in _OPTIONAL_FIELD_TYPES:
            raise ValueError("The optional field type is not supported.")
        if not isinstance(self.required, bool):
            raise ValueError("The optional field required state must be boolean.")
        if self.display_order != MAXIMUM_CUSTOMER_ENTRY_FIELD_COUNT:
            raise ValueError("The optional field must be displayed sixth.")
        expected_rule = _VALIDATION_RULE_BY_TYPE[self.field_type]
        if self.validation_contract.rule != expected_rule:
            raise ValueError("The optional field validation rule does not match its type.")

        text_type = self.field_type in {"email", "short_text", "textarea"}
        if text_type:
            upper_bound = {
                "email": 254,
                "short_text": 500,
                "textarea": 5_000,
            }[self.field_type]
            if (
                isinstance(self.maximum_length, bool)
                or not isinstance(self.maximum_length, int)
                or not 1 <= self.maximum_length <= upper_bound
            ):
                raise ValueError(
                    "The optional text field requires a bounded maximum length."
                )
            minimum = self.validation_contract.minimum_length
            if minimum is None or minimum > self.maximum_length:
                raise ValueError(
                    "The optional text field requires a compatible minimum length."
                )
            if self.required and minimum < 1:
                raise ValueError(
                    "A required optional text field must require at least one character."
                )
        elif self.maximum_length is not None:
            raise ValueError(
                "A controlled choice, checkbox, or date field cannot define a maximum length."
            )
        elif self.validation_contract.minimum_length is not None:
            raise ValueError(
                "A controlled choice, checkbox, or date field cannot define a text minimum."
            )

        choice_type = self.field_type in {"dropdown", "radio"}
        if choice_type:
            if not 1 <= len(self.choices) <= 50:
                raise ValueError("Dropdown and radio fields require bounded choices.")
            if len({choice.choice_key for choice in self.choices}) != len(self.choices):
                raise ValueError("Optional field choice keys must be unique.")
            normalized_labels = {
                unicodedata.normalize("NFKC", choice.public_label).casefold()
                for choice in self.choices
            }
            if len(normalized_labels) != len(self.choices):
                raise ValueError("Optional field choice labels must be unique.")
        elif self.choices:
            raise ValueError("Choices apply only to dropdown and radio fields.")


@dataclass(frozen=True)
class NormalizedOptionalFieldValue:
    field_key: str
    definition_revision_identity: str
    provider_mapping_key: str
    value: str | bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_key", normalize_form_field_key(self.field_key))
        object.__setattr__(
            self,
            "definition_revision_identity",
            normalize_form_field_key(self.definition_revision_identity),
        )
        object.__setattr__(
            self,
            "provider_mapping_key",
            normalize_form_field_key(self.provider_mapping_key),
        )
        if not isinstance(self.value, (str, bool)):
            raise ValueError("A normalized optional field value must be text or boolean.")


def optional_form_field_definition_payload(
    definition: OptionalFormFieldDefinition,
) -> dict[str, object]:
    """Return the complete canonical value bound to one immutable identity."""

    if not isinstance(definition, OptionalFormFieldDefinition):
        raise ValueError("The optional field definition is invalid.")
    return {
        "field_key": definition.field_key,
        "public_label": definition.public_label,
        "accessibility_label": definition.accessibility_label,
        "field_type": definition.field_type,
        "required": definition.required,
        "display_order": definition.display_order,
        "maximum_length": definition.maximum_length,
        "validation_contract": {
            "rule": definition.validation_contract.rule,
            "minimum_length": definition.validation_contract.minimum_length,
        },
        "choices": [
            {
                "choice_key": choice.choice_key,
                "public_label": choice.public_label,
            }
            for choice in definition.choices
        ],
        "provider_mapping_key": definition.provider_mapping_key,
        "help_text": definition.help_text,
        "definition_revision_identity": definition.definition_revision_identity,
    }

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
    optional_fields: tuple[OptionalFormFieldDefinition, ...] = ()

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
        expected_standard_fields = (
            ("name", "name", True, "text", 1, 1, 100),
            ("phone", "phone", True, "phone", 2, 7, 40),
            ("postal-code", "postal_code", True, "postal_code", 3, 5, 12),
            (
                "requested-service",
                "requested_service",
                True,
                "text",
                4,
                1,
                160,
            ),
            ("message", "message", False, "free_text", 5, 0, 2000),
        )
        observed_standard_fields = tuple(
            (
                field.field_key,
                field.envelope_field,
                field.required,
                field.value_kind,
                field.order,
                field.minimum_length,
                field.maximum_length,
            )
            for field in self.fields
        )
        if observed_standard_fields != expected_standard_fields:
            raise ValueError(
                "Atlas-rendered forms must preserve the exact five standard fields and order."
            )
        object.__setattr__(self, "optional_fields", tuple(self.optional_fields))
        if any(
            not isinstance(field, OptionalFormFieldDefinition)
            for field in self.optional_fields
        ):
            raise ValueError("The optional form field definition is invalid.")
        if len(self.optional_fields) > 1:
            raise ValueError(
                "Atlas-rendered forms allow at most one optional customer-entry field."
            )
        if (
            len(self.fields) + len(self.optional_fields)
            > MAXIMUM_CUSTOMER_ENTRY_FIELD_COUNT
        ):
            raise ValueError(
                "Atlas-rendered forms cannot exceed six customer-entry fields."
            )
        normalized_keys = [
            normalize_form_field_key(field.field_key) for field in self.fields
        ] + [field.field_key for field in self.optional_fields]
        if len(set(normalized_keys)) != len(normalized_keys):
            raise ValueError("Atlas-rendered form field keys collide after normalization.")

    @property
    def customer_entry_field_count(self) -> int:
        """Count customer questions only; system and provider controls are excluded."""

        return len(self.fields) + len(self.optional_fields)

    def with_optional_fields(
        self,
        optional_fields: tuple[OptionalFormFieldDefinition, ...],
    ) -> "NormalizedFormDefinition":
        return NormalizedFormDefinition(
            component_key=self.component_key,
            contract_version=self.contract_version,
            fields=self.fields,
            optional_fields=optional_fields,
        )


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
    """The provider-neutral five-default/one-optional submission contract.

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
    optional_field_definition_revision_identity: str | None = None
    optional_field: NormalizedOptionalFieldValue | None = None

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
        if self.optional_field is not None and not isinstance(
            self.optional_field,
            NormalizedOptionalFieldValue,
        ):
            raise ValueError(
                "The submission envelope accepts only one governed optional field value."
            )
        if self.optional_field_definition_revision_identity is not None:
            normalized_revision = normalize_form_field_key(
                self.optional_field_definition_revision_identity
            )
            if normalized_revision != self.optional_field_definition_revision_identity:
                raise ValueError(
                    "The optional field definition revision must be an exact normalized identity."
                )
        if self.optional_field is not None and (
            self.optional_field_definition_revision_identity
            != self.optional_field.definition_revision_identity
        ):
            raise ValueError(
                "The optional field value must match the envelope definition revision."
            )


def normalize_optional_field_value(
    definition: OptionalFormFieldDefinition,
    raw_value: object,
) -> NormalizedOptionalFieldValue | None:
    """Normalize one submitted sixth value against its immutable definition."""

    if raw_value is None:
        if definition.required:
            raise ValueError("The required optional field value is missing.")
        return None

    normalized: str | bool
    if definition.field_type == "checkbox":
        if type(raw_value) is not bool:
            raise ValueError("A checkbox value must be boolean.")
        normalized = raw_value
    elif not isinstance(raw_value, str):
        raise ValueError("The optional field value must match its configured type.")
    elif definition.field_type in {"dropdown", "radio"}:
        selected = normalize_form_field_key(raw_value)
        if selected not in {choice.choice_key for choice in definition.choices}:
            raise ValueError("The optional field choice is not configured.")
        normalized = selected
    elif definition.field_type == "date":
        cleaned_date = unicodedata.normalize("NFKC", raw_value).strip()
        try:
            parsed_date = date.fromisoformat(cleaned_date)
        except ValueError as exc:
            raise ValueError("The optional date must use ISO YYYY-MM-DD format.") from exc
        if len(cleaned_date) != 10 or parsed_date.isoformat() != cleaned_date:
            raise ValueError("The optional date must use ISO YYYY-MM-DD format.")
        normalized = cleaned_date
    else:
        cleaned = unicodedata.normalize("NFC", raw_value).strip()
        permitted_line_break = definition.field_type == "textarea"
        if permitted_line_break:
            cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        if not cleaned:
            if definition.required:
                raise ValueError("The required optional field value is blank.")
            return None
        if "<" in cleaned or ">" in cleaned:
            raise ValueError("The optional field value cannot contain markup.")
        for character in cleaned:
            if unicodedata.category(character).startswith("C") and not (
                permitted_line_break and character == "\n"
            ):
                raise ValueError("The optional field value contains a control character.")
        if not permitted_line_break and ("\r" in cleaned or "\n" in cleaned):
            raise ValueError("The optional field value cannot contain line breaks.")
        minimum = definition.validation_contract.minimum_length or 0
        maximum = definition.maximum_length
        if maximum is None or not minimum <= len(cleaned) <= maximum:
            raise ValueError("The optional field value is outside its configured length.")
        if definition.field_type == "email":
            if (
                not _EMAIL_VALUE_PATTERN.fullmatch(cleaned)
                or cleaned.startswith(".")
                or cleaned.endswith(".")
                or ".." in cleaned
            ):
                raise ValueError("The optional email value is invalid.")
            local, domain = cleaned.rsplit("@", 1)
            if (
                not local
                or not domain
                or any(
                    not label or label.startswith("-") or label.endswith("-")
                    for label in domain.split(".")
                )
            ):
                raise ValueError("The optional email value is invalid.")
            cleaned = f"{local}@{domain.casefold()}"
        normalized = cleaned

    return NormalizedOptionalFieldValue(
        field_key=definition.field_key,
        definition_revision_identity=definition.definition_revision_identity,
        provider_mapping_key=definition.provider_mapping_key,
        value=normalized,
    )


def validate_submission_optional_field_binding(
    definition: NormalizedFormDefinition,
    value: NormalizedOptionalFieldValue | None,
    definition_revision_identity: str | None,
) -> None:
    """Bind an internal envelope to the exact immutable form definition."""

    if not definition.optional_fields:
        if value is not None or definition_revision_identity is not None:
            raise ValueError(
                "The submission contains an optional value with no governed definition."
            )
        return
    optional_definition = definition.optional_fields[0]
    if (
        definition_revision_identity
        != optional_definition.definition_revision_identity
    ):
        raise ValueError(
            "The submission does not name its exact optional field definition revision."
        )
    normalized = normalize_optional_field_value(
        optional_definition,
        value.value if value is not None else None,
    )
    if normalized != value:
        raise ValueError(
            "The submission optional value does not match its exact governed definition."
        )


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
