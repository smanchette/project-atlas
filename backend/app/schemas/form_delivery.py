from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)

from app.website_builder_core.configuration_safety import (
    DESTINATION_REFERENCE_PATTERN,
    POLICY_REFERENCE_PATTERN,
    SECRET_REFERENCE_PATTERN,
    clean_text,
    reject_secret_configuration,
    validate_key,
)
from app.website_builder_core.contracts import (
    FormDeliveryMode,
    NormalizedFormDefinition,
    NormalizedOptionalFieldValue,
    OptionalFormFieldChoice,
    OptionalFormFieldDefinition,
    OptionalFormFieldType,
    OptionalFormFieldValidationContract,
    OptionalFormFieldValidationRule,
    normalize_form_field_key,
    normalize_optional_field_value,
)


ModeLifecycle = Literal["draft", "approved", "active", "retired"]


class OptionalFormFieldValidationConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: OptionalFormFieldValidationRule
    minimum_length: int | None = Field(default=None, ge=0, le=10_000)

    def to_core(self) -> OptionalFormFieldValidationContract:
        return OptionalFormFieldValidationContract(
            rule=self.rule,
            minimum_length=self.minimum_length,
        )


class OptionalFormFieldChoiceConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice_key: str = Field(min_length=1, max_length=120)
    public_label: str = Field(min_length=1, max_length=160)

    @field_validator("choice_key")
    @classmethod
    def normalize_choice_key(cls, value: str) -> str:
        return normalize_form_field_key(value)

    @model_validator(mode="after")
    def normalize_core_choice(self) -> "OptionalFormFieldChoiceConfiguration":
        normalized = self.to_core()
        self.choice_key = normalized.choice_key
        self.public_label = normalized.public_label
        return self

    def to_core(self) -> OptionalFormFieldChoice:
        return OptionalFormFieldChoice(
            choice_key=self.choice_key,
            public_label=self.public_label,
        )


class OptionalFormFieldConfiguration(BaseModel):
    """The single governed sixth question carried by an immutable mode revision."""

    model_config = ConfigDict(extra="forbid")

    field_key: str = Field(min_length=1, max_length=120)
    public_label: str = Field(min_length=1, max_length=160)
    accessibility_label: str = Field(min_length=1, max_length=160)
    field_type: OptionalFormFieldType
    required: bool
    display_order: Literal[6]
    maximum_length: int | None = Field(default=None, ge=1, le=5_000)
    validation_contract: OptionalFormFieldValidationConfiguration
    choices: list[OptionalFormFieldChoiceConfiguration] = Field(
        default_factory=list,
        max_length=50,
    )
    provider_mapping_key: str = Field(min_length=1, max_length=120)
    help_text: str | None = Field(default=None, max_length=500)
    definition_revision_identity: str = Field(min_length=1, max_length=120)

    @field_validator(
        "field_key",
        "provider_mapping_key",
        "definition_revision_identity",
    )
    @classmethod
    def normalize_stable_key(cls, value: str) -> str:
        return normalize_form_field_key(value)

    @model_validator(mode="after")
    def validate_core_contract(self) -> "OptionalFormFieldConfiguration":
        normalized = self.to_core()
        self.field_key = normalized.field_key
        self.public_label = normalized.public_label
        self.accessibility_label = normalized.accessibility_label
        self.provider_mapping_key = normalized.provider_mapping_key
        self.help_text = normalized.help_text
        self.definition_revision_identity = (
            normalized.definition_revision_identity
        )
        return self

    def to_core(self) -> OptionalFormFieldDefinition:
        return OptionalFormFieldDefinition(
            field_key=self.field_key,
            public_label=self.public_label,
            accessibility_label=self.accessibility_label,
            field_type=self.field_type,
            required=self.required,
            display_order=self.display_order,
            maximum_length=self.maximum_length,
            validation_contract=self.validation_contract.to_core(),
            choices=tuple(choice.to_core() for choice in self.choices),
            provider_mapping_key=self.provider_mapping_key,
            help_text=self.help_text,
            definition_revision_identity=self.definition_revision_identity,
        )


class AtlasRenderedModeConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    optional_fields: list[OptionalFormFieldConfiguration] = Field(
        default_factory=list,
        max_length=1,
    )


class DisabledModeConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AtlasEmailModeConfiguration(AtlasRenderedModeConfiguration):
    model_config = ConfigDict(extra="forbid")

    transport_key_reference: str = Field(min_length=1, max_length=160)
    transport_secret_reference: str = Field(min_length=1, max_length=260)
    notification_preference: Literal["all_verified", "primary_only"]
    consent_required: bool

    @field_validator("transport_key_reference")
    @classmethod
    def validate_transport_key(cls, value: str) -> str:
        return validate_key(value, "Transport key")

    @field_validator("transport_secret_reference")
    @classmethod
    def validate_secret_reference(cls, value: str) -> str:
        if not SECRET_REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("Transport secret identity must be an opaque reference")
        return value


class ProviderOwnedModeConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    presentation_strategy: Literal[
        "external_link",
        "hosted_route",
        "sandboxed_iframe",
        "adapter_embed",
    ]
    approved_https_destination: str = Field(min_length=1, max_length=1000)
    approved_origin: str = Field(min_length=1, max_length=500)
    accessibility_title: str = Field(min_length=1, max_length=200)
    ownership_disclosure: str = Field(min_length=1, max_length=500)
    destination_verified_by: str = Field(min_length=1, max_length=160)
    destination_verified_at: datetime
    sandbox_policy: Literal[
        "allow-forms",
        "allow-forms allow-scripts",
    ] | None = None
    referrer_policy: Literal[
        "no-referrer",
        "strict-origin",
        "strict-origin-when-cross-origin",
    ] | None = None

    @field_validator(
        "accessibility_title",
        "ownership_disclosure",
        "destination_verified_by",
    )
    @classmethod
    def normalize_text(cls, value: str) -> str:
        cleaned = clean_text(value, "Provider-owned presentation field")
        if "<" in cleaned or ">" in cleaned:
            raise ValueError("Provider-owned presentation text cannot contain markup")
        return cleaned

    @model_validator(mode="after")
    def validate_destination_and_embed(self) -> "ProviderOwnedModeConfiguration":
        destination = _exact_https_url(self.approved_https_destination)
        origin = _exact_https_origin(self.approved_origin)
        parsed_destination = urlsplit(destination)
        destination_origin = f"https://{parsed_destination.hostname}"
        if parsed_destination.port is not None:
            destination_origin += f":{parsed_destination.port}"
        if destination_origin != origin:
            raise ValueError("Provider-owned destination must match its exact approved origin")
        if self.presentation_strategy == "sandboxed_iframe":
            if self.sandbox_policy is None or self.referrer_policy is None:
                raise ValueError("Sandboxed iframe presentation requires fixed sandbox and referrer policies")
        elif self.sandbox_policy is not None or self.referrer_policy is not None:
            raise ValueError("Sandbox and referrer policies apply only to sandboxed iframe presentation")
        return self


class AtlasOps360NativeModeConfiguration(AtlasRenderedModeConfiguration):
    model_config = ConfigDict(extra="forbid")

    workspace_binding_reference: str = Field(min_length=1, max_length=240)
    adapter_configuration_reference: str = Field(min_length=1, max_length=240)
    consent_required: bool

    @field_validator("workspace_binding_reference", "adapter_configuration_reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        if not _exact_opaque_reference(value, "binding-ref", "AtlasOps360 binding"):
            raise ValueError("AtlasOps360 configuration must use an opaque binding reference")
        return value


class ExternalAdapterModeConfiguration(AtlasRenderedModeConfiguration):
    model_config = ConfigDict(extra="forbid")

    adapter_configuration_reference: str = Field(min_length=1, max_length=240)
    adapter_secret_reference: str = Field(min_length=1, max_length=260)
    consent_required: bool

    @field_validator("adapter_configuration_reference")
    @classmethod
    def validate_configuration_reference(cls, value: str) -> str:
        if not _exact_opaque_reference(
            value,
            "destination-ref",
            "External adapter configuration",
        ):
            raise ValueError("External adapter configuration must use an opaque reference")
        return value

    @field_validator("adapter_secret_reference")
    @classmethod
    def validate_secret_reference(cls, value: str) -> str:
        if not SECRET_REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("External adapter secret identity must be an opaque reference")
        return value


MODE_CONFIGURATION_MODELS: dict[FormDeliveryMode, type[BaseModel]] = {
    "disabled": DisabledModeConfiguration,
    "atlas_email": AtlasEmailModeConfiguration,
    "provider_owned": ProviderOwnedModeConfiguration,
    "atlasops360_native": AtlasOps360NativeModeConfiguration,
    "external_adapter": ExternalAdapterModeConfiguration,
}


def validate_mode_configuration(
    mode: FormDeliveryMode,
    payload: dict[str, Any],
) -> dict[str, Any]:
    reject_secret_configuration(payload)
    model = MODE_CONFIGURATION_MODELS[mode].model_validate(payload)
    normalized = model.model_dump(mode="json", exclude_none=False)
    # Preserve the exact legacy five-field payload shape when no sixth field is
    # configured. This keeps existing immutable revisions byte/fingerprint safe.
    if mode in {"atlas_email", "atlasops360_native", "external_adapter"} and not normalized.get(
        "optional_fields"
    ):
        normalized.pop("optional_fields", None)
    return normalized


def optional_field_definitions_from_configuration(
    payload: dict[str, Any],
) -> tuple[OptionalFormFieldDefinition, ...]:
    raw_fields = payload.get("optional_fields", [])
    if not isinstance(raw_fields, list) or len(raw_fields) > 1:
        raise ValueError(
            "Atlas-rendered forms allow at most one optional customer-entry field."
        )
    return tuple(
        OptionalFormFieldConfiguration.model_validate(item).to_core()
        for item in raw_fields
    )


class WebsiteFormDeliveryModeRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    form_component_configuration_id: int = Field(ge=1)
    form_instance_key: str = Field(min_length=1, max_length=120)
    supersedes_delivery_mode_revision_id: int | None = Field(default=None, ge=1)
    lifecycle_status: ModeLifecycle = "draft"
    mode: FormDeliveryMode
    enabled: bool = False
    provider_key: str | None = Field(default=None, max_length=120)
    adapter_version: str | None = Field(default=None, max_length=80)
    destination_identity: str | None = Field(default=None, max_length=1000)
    configuration_payload: dict[str, Any] = Field(default_factory=dict)
    privacy_policy_reference: str | None = Field(default=None, max_length=1000)
    consent_policy_reference: str | None = Field(default=None, max_length=240)
    retention_policy_reference: str | None = Field(default=None, max_length=240)
    abuse_policy_reference: str | None = Field(default=None, max_length=240)
    success_behavior: str | None = Field(default=None, max_length=1000)
    failure_behavior: str | None = Field(default=None, max_length=1000)
    idempotency_policy_reference: str | None = Field(default=None, max_length=240)
    audit_identity: str = Field(min_length=1, max_length=160)
    approval_identity: str | None = Field(default=None, max_length=160)
    approved_at: datetime | None = None
    activation_identity: str | None = Field(default=None, max_length=160)
    activated_at: datetime | None = None
    created_by: str = Field(min_length=1, max_length=160)
    updated_by: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=2000)

    @field_validator(
        "form_instance_key",
        "provider_key",
    )
    @classmethod
    def normalize_keys(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return validate_key(
            value,
            info.field_name.replace("_", " ").title(),
            instance=info.field_name == "form_instance_key",
        )

    @field_validator(
        "approval_identity",
        "activation_identity",
        "created_by",
        "updated_by",
        "rationale",
        "success_behavior",
        "failure_behavior",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None, info) -> str | None:
        return clean_text(value, info.field_name.replace("_", " ").title()) if value is not None else None

    @field_validator("audit_identity")
    @classmethod
    def normalize_audit_identity(cls, value: str) -> str:
        return validate_key(value, "Audit identity")

    @field_validator("adapter_version", "destination_identity")
    @classmethod
    def normalize_delivery_identity(cls, value: str | None, info) -> str | None:
        return (
            clean_text(value, info.field_name.replace("_", " ").title())
            if value is not None
            else None
        )

    @field_validator(
        "consent_policy_reference",
        "retention_policy_reference",
        "abuse_policy_reference",
        "idempotency_policy_reference",
    )
    @classmethod
    def validate_policy_reference(cls, value: str | None, info) -> str | None:
        if value is not None and not POLICY_REFERENCE_PATTERN.fullmatch(value):
            raise ValueError(
                f"{info.field_name.replace('_', ' ').title()} must be an opaque policy reference"
            )
        return value

    @field_validator("privacy_policy_reference")
    @classmethod
    def validate_privacy_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = clean_text(value, "Privacy policy reference")
        if POLICY_REFERENCE_PATTERN.fullmatch(cleaned):
            return cleaned
        if cleaned.startswith("/") and not cleaned.startswith("//") and all(
            character not in cleaned for character in ("?", "#", "\\")
        ):
            return cleaned
        try:
            return _exact_https_url(cleaned)
        except ValueError as exc:
            raise ValueError(
                "Privacy policy reference must be an exact path, HTTPS URL, or opaque policy reference"
            ) from exc

    @model_validator(mode="after")
    def validate_mode_and_lifecycle(self) -> "WebsiteFormDeliveryModeRevisionCreate":
        self.configuration_payload = validate_mode_configuration(
            self.mode,
            self.configuration_payload,
        )
        if (self.approval_identity is None) != (self.approved_at is None):
            raise ValueError("Approval identity and timestamp must be configured together")
        if (self.activation_identity is None) != (self.activated_at is None):
            raise ValueError("Activation identity and timestamp must be configured together")
        if self.lifecycle_status in {"approved", "active"} and self.approval_identity is None:
            raise ValueError("Approved and active revisions require approval evidence")
        if self.lifecycle_status == "active" and self.activation_identity is None:
            raise ValueError("Active revisions require activation evidence")
        if self.enabled and (self.mode == "disabled" or self.lifecycle_status != "active"):
            raise ValueError("Only an active non-disabled mode may be enabled")
        if self.mode == "disabled":
            governed = (
                self.provider_key,
                self.adapter_version,
                self.destination_identity,
                self.privacy_policy_reference,
                self.consent_policy_reference,
                self.retention_policy_reference,
                self.abuse_policy_reference,
                self.success_behavior,
                self.failure_behavior,
                self.idempotency_policy_reference,
            )
            if self.enabled or any(value is not None for value in governed):
                raise ValueError("Disabled mode cannot contain delivery configuration")
        else:
            if not self.provider_key or not self.adapter_version or not self.destination_identity:
                raise ValueError("A non-disabled mode requires provider, adapter, and destination identities")
        if self.mode == "atlas_email" and not _exact_opaque_reference(
            self.destination_identity,
            "recipient-set-ref",
            "Atlas email recipient set",
        ):
            raise ValueError("Atlas email requires an opaque recipient-set destination")
        if self.mode == "provider_owned" and self.destination_identity != self.configuration_payload.get(
            "approved_https_destination"
        ):
            raise ValueError("Provider-owned destination identity must match the approved URL")
        if self.mode == "atlasops360_native" and not _exact_opaque_reference(
            self.destination_identity,
            "binding-ref",
            "AtlasOps360 destination",
        ):
            raise ValueError("AtlasOps360 mode requires an opaque binding destination")
        if self.mode == "external_adapter" and not _exact_opaque_reference(
            self.destination_identity,
            "destination-ref",
            "External adapter destination",
        ):
            raise ValueError("External adapter mode requires an opaque destination reference")
        if self.mode == "provider_owned":
            if not self.privacy_policy_reference:
                raise ValueError(
                    "Provider-owned mode requires its governed privacy-policy reference"
                )
            if any(
                value is not None
                for value in (
                    self.consent_policy_reference,
                    self.retention_policy_reference,
                    self.abuse_policy_reference,
                    self.idempotency_policy_reference,
                )
            ):
                raise ValueError("Provider-owned mode cannot claim Atlas collection or retention policy")
        return self


class WebsiteFormDeliveryModeRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    website_id: int
    form_component_configuration_id: int
    form_instance_key: str
    revision: int
    supersedes_delivery_mode_revision_id: int | None
    lifecycle_status: ModeLifecycle
    mode: FormDeliveryMode
    enabled: bool
    provider_key: str | None
    adapter_version: str | None
    destination_identity: str | None
    configuration_payload: dict[str, Any]
    privacy_policy_reference: str | None
    consent_policy_reference: str | None
    retention_policy_reference: str | None
    abuse_policy_reference: str | None
    success_behavior: str | None
    failure_behavior: str | None
    idempotency_policy_reference: str | None
    audit_identity: str
    approval_identity: str | None
    approved_at: datetime | None
    activation_identity: str | None
    activated_at: datetime | None
    created_by: str
    updated_by: str
    integrity_fingerprint: str
    created_at: datetime
    updated_at: datetime


class WebsiteFormRecipientRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_mode_revision_id: int = Field(ge=1)
    recipient_key: str = Field(min_length=1, max_length=120)
    supersedes_recipient_revision_id: int | None = Field(default=None, ge=1)
    email: EmailStr
    label: str | None = Field(default=None, max_length=160)
    recipient_role: Literal["primary", "secondary"]
    enabled: bool = True
    verification_status: Literal["unverified", "verified", "revoked"] = "unverified"
    verified_at: datetime | None = None
    verified_by: str | None = Field(default=None, max_length=160)
    verification_method: str | None = Field(default=None, max_length=120)
    created_by: str = Field(min_length=1, max_length=160)
    updated_by: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=2000)

    @field_validator("recipient_key")
    @classmethod
    def normalize_recipient_key(cls, value: str) -> str:
        return validate_key(value, "Recipient key", instance=True)

    @model_validator(mode="after")
    def validate_verification_evidence(self) -> "WebsiteFormRecipientRevisionCreate":
        evidence = (self.verified_at, self.verified_by, self.verification_method)
        if self.verification_status == "unverified" and any(item is not None for item in evidence):
            raise ValueError("Unverified recipient cannot contain verification evidence")
        if self.verification_status in {"verified", "revoked"} and any(item is None for item in evidence):
            raise ValueError("Verified or revoked recipient requires complete verification evidence")
        return self


class WebsiteFormRecipientRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    delivery_mode_revision_id: int
    website_id: int
    form_component_configuration_id: int
    form_instance_key: str
    recipient_key: str
    revision: int
    supersedes_recipient_revision_id: int | None
    email: str
    normalized_email: str
    label: str | None
    recipient_role: Literal["primary", "secondary"]
    enabled: bool
    verification_status: Literal["unverified", "verified", "revoked"]
    verified_at: datetime | None
    verified_by: str | None
    verification_method: str | None
    created_by: str
    updated_by: str
    integrity_fingerprint: str
    created_at: datetime
    updated_at: datetime


class FormDeliveryReadinessBlockerRead(BaseModel):
    code: str
    field: str
    reason: str


class FormDeliveryReadinessRead(BaseModel):
    status: str
    can_present: bool
    can_submit: bool
    provider_owner: str
    data_collector: str
    retention_owner: str
    atlas_stores_customer_data: bool
    external_request_behavior: str
    production_enabled: bool
    blockers: list[FormDeliveryReadinessBlockerRead]


class FormSubmissionAcceptanceRead(BaseModel):
    """Provider-neutral public acknowledgement with value-free evidence only."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted"] = "accepted"
    code: Literal["submission_accepted"] = "submission_accepted"
    safe_message: str = Field(min_length=1, max_length=500)
    provider_reference: str = Field(min_length=1, max_length=240)


class OptionalFormSubmissionInput(BaseModel):
    """One value bound to its exact governed definition; no provider payload."""

    model_config = ConfigDict(extra="forbid")

    field_key: str = Field(min_length=1, max_length=120)
    definition_revision_identity: str = Field(min_length=1, max_length=120)
    value: StrictStr | StrictBool

    @field_validator("field_key", "definition_revision_identity")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        return normalize_form_field_key(value)

    def to_envelope_value(
        self,
        definition: OptionalFormFieldDefinition,
    ) -> NormalizedOptionalFieldValue:
        if (
            self.field_key != definition.field_key
            or self.definition_revision_identity
            != definition.definition_revision_identity
        ):
            raise ValueError("The submitted optional field does not match its definition.")
        normalized = normalize_optional_field_value(definition, self.value)
        if normalized is None:
            raise ValueError("The submitted optional field value is absent.")
        return normalized


class NormalizedFormSubmissionInput(BaseModel):
    """The provider-neutral five-default/one-optional JSON request shape."""

    model_config = ConfigDict(extra="forbid")

    name: str
    phone: str
    postal_code: str
    requested_service: str
    message: str | None = None
    consent_accepted: bool | None = None
    optional_field: OptionalFormSubmissionInput | None = None

    def to_optional_envelope_binding(
        self,
        definition: NormalizedFormDefinition,
    ) -> tuple[str | None, NormalizedOptionalFieldValue | None]:
        if not definition.optional_fields:
            if self.optional_field is not None:
                raise ValueError("No governed optional field definition exists.")
            return None, None
        optional_definition = definition.optional_fields[0]
        if self.optional_field is None:
            normalized = normalize_optional_field_value(optional_definition, None)
        else:
            normalized = self.optional_field.to_envelope_value(optional_definition)
        return optional_definition.definition_revision_identity, normalized


class FormDeliveryOperatorReviewRead(BaseModel):
    current_revision: WebsiteFormDeliveryModeRevisionRead
    readiness: FormDeliveryReadinessRead
    recipient_count: int
    enabled_verified_recipient_count: int
    secret_reference_configured: bool
    configuration_summary: dict[str, Any]


def _exact_https_url(value: str) -> str:
    cleaned = clean_text(value, "Provider-owned HTTPS destination")
    try:
        parsed = urlsplit(cleaned)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("Provider-owned destination is malformed") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.hostname.startswith("*.")
        or "*" in parsed.hostname
        or port is not None and not 1 <= port <= 65535
    ):
        raise ValueError("Provider-owned destination requires an exact approved HTTPS URL")
    return cleaned


def _exact_opaque_reference(value: str, scheme: str, label: str) -> bool:
    try:
        cleaned = clean_text(value, label)
    except ValueError:
        return False
    return bool(
        cleaned == value
        and cleaned.startswith(f"{scheme}://")
        and DESTINATION_REFERENCE_PATTERN.fullmatch(cleaned)
    )


def _exact_https_origin(value: str) -> str:
    cleaned = clean_text(value, "Provider-owned origin")
    try:
        parsed = urlsplit(cleaned)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("Provider-owned origin is malformed") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or "*" in parsed.hostname
        or port is not None and not 1 <= port <= 65535
    ):
        raise ValueError("Provider-owned origin must be one exact HTTPS origin")
    result = f"https://{parsed.hostname}"
    if port is not None:
        result += f":{port}"
    return result
