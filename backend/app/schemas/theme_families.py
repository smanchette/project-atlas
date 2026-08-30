from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ThemeFamilyLifecycle = Literal["registered", "retired"]
ThemeFamilyVersionLifecycle = Literal["preview_candidate", "approved", "retired"]
WebsiteThemeConfigurationLifecycle = Literal[
    "draft", "approved", "active", "superseded", "retired"
]
ComponentConfigurationLifecycle = Literal["current", "superseded"]
ComponentScope = Literal["website_default", "page_override"]
ThemeConfigurationAuditAction = Literal[
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
]
ComponentKey = Literal[
    "campaign_banner",
    "sticky_mobile_action_bar",
    "compact_estimate_form",
]
CampaignIntent = Literal["evergreen_conversion", "time_bound_campaign"]

_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_INSTANCE_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_:][a-z0-9]+)*$")
_SOURCE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_EVERGREEN_LANGUAGE = re.compile(
    r"(?:[$€£]\s*\d|\b\d+(?:\.\d{1,2})?\s*%|"
    r"\b\d+(?:\.\d{1,2})?\s*(?:percent|dollars?|usd)\b|"
    r"\b(?:special|sale|discount|limited[- ]time|expires?|urgenc(?:y|t)|urgent|"
    r"act\s+now|now|hurry|last\s+chance|ends?\s+soon|today(?:\s+only)?|immediately|"
    r"guarantee[ds]?|financ(?:e|ing)|price|only\s+\$|save|savings?|free|"
    r"complimentary|no[- ]cost|dollars?|usd|bucks?)\b|"
    r"\b(?:\d+(?:\.\d+)?|half|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"twenty|thirty|forty|fifty|hundred)\s+off\b)",
    re.IGNORECASE,
)
_SECRET_KEY_MARKERS = (
    "api_key",
    "access_token",
    "refresh_token",
    "password",
    "private_key",
    "secret",
    "credential",
    "token",
)
_ALLOWED_SECRET_REFERENCE_KEYS = frozenset({"provider_secret_reference"})
_SECRET_REFERENCE_PATTERN = re.compile(r"^secret-ref://[a-z0-9][a-z0-9/_-]{2,239}$")
_DESTINATION_REFERENCE_PATTERN = re.compile(
    r"^destination-ref://[a-z0-9][a-z0-9/_-]{2,239}$"
)
_SPAM_REFERENCE_PATTERN = re.compile(
    r"^spam-ref://[a-z0-9][a-z0-9/_-]{2,219}$"
)


def _clean_text(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned or any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise ValueError(f"{label} must be non-empty text without control characters")
    return cleaned


def _validate_key(value: str, label: str, *, instance: bool = False) -> str:
    cleaned = value.strip().lower()
    pattern = _INSTANCE_KEY_PATTERN if instance else _KEY_PATTERN
    if not pattern.fullmatch(cleaned):
        raise ValueError(f"{label} must be a lowercase stable key")
    return cleaned


def reject_secret_configuration(value: Any, *, path: str = "configuration_payload") -> None:
    """Reject secret-like keys recursively without inspecting or storing a secret value."""

    if isinstance(value, dict):
        for key, nested in value.items():
            camel_separated = re.sub(
                r"(?<=[a-z0-9])(?=[A-Z])",
                "_",
                str(key).strip(),
            )
            normalized = re.sub(r"[^A-Za-z0-9]+", "_", camel_separated).lower().strip("_")
            if normalized in _ALLOWED_SECRET_REFERENCE_KEYS:
                if nested is not None and (
                    not isinstance(nested, str)
                    or not _SECRET_REFERENCE_PATTERN.fullmatch(nested)
                ):
                    raise ValueError(
                        f"{path}.{key} must be an opaque secret-manager reference, never a secret value"
                    )
                continue
            if any(marker in normalized for marker in _SECRET_KEY_MARKERS):
                raise ValueError(f"{path}.{key} may not contain credentials or secrets")
            reject_secret_configuration(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            reject_secret_configuration(nested, path=f"{path}[{index}]")


class ResponsiveVisibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    desktop: bool
    tablet: bool
    mobile: bool


class ThemeFamilyComponentContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_key: str = Field(min_length=1, max_length=80)
    contract_version: int = Field(ge=1)
    optional: bool
    default_enabled: bool
    scope: Literal["website_with_optional_page_override"]
    supports_page_override: Literal[True]
    placement: str = Field(min_length=1, max_length=120)
    variant: str = Field(min_length=1, max_length=120)
    responsive_visibility: ResponsiveVisibility
    theme_compatibility: tuple[
        Literal[
            "performance-local@2",
            "performance-local@3",
            "performance-local@5",
        ], ...
    ]
    content_source: Literal[
        "governed_semantic_composition",
        "approved_runtime_configuration",
    ]
    required_configuration: list[str] = Field(default_factory=list, max_length=80)
    supports_cta_label: Literal[True]
    supports_cta_destination: Literal[True]
    accessibility_label_required: bool
    diagnostic_label: str = Field(min_length=1, max_length=240)

    @field_validator("component_key")
    @classmethod
    def validate_component_key(cls, value: str) -> str:
        return _validate_key(value, "Component key")

    @field_validator("placement", "variant", "diagnostic_label")
    @classmethod
    def validate_contract_text(cls, value: str) -> str:
        return _clean_text(value, "Component contract value")

    @field_validator("required_configuration")
    @classmethod
    def validate_required_configuration(cls, value: list[str]) -> list[str]:
        normalized = [_validate_key(item, "Required configuration key") for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Required configuration keys must be unique")
        return normalized


def _load_performance_local_v2_component_contracts() -> tuple[dict[str, Any], ...]:
    contract_path = Path(__file__).with_name("performance_local_v2_contract.json")
    raw = json.loads(contract_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RuntimeError("Performance Local v2 canonical contract must be a JSON array.")
    contracts = tuple(
        ThemeFamilyComponentContract.model_validate(item).model_dump(mode="json")
        for item in raw
    )
    expected_keys = (
        "site_header",
        "desktop_dropdown_navigation",
        "mobile_navigation_drawer",
        "campaign_banner",
        "hero_conversion_section",
        "trust_proof_strip",
        "service_or_related_card_grid",
        "split_media_text_section",
        "visual_cta_band",
        "compact_estimate_form",
        "trust_feature_cards",
        "authority_content_section",
        "numbered_process_steps",
        "faq_accordion",
        "sticky_mobile_action_bar",
        "site_footer",
        "back_to_top_control",
        "review_badge_group",
        "statistics_counter_band",
        "video_embed_section",
        "map_or_service_area_section",
        "community_program_section",
        "language_selector",
    )
    observed_keys = tuple(item["component_key"] for item in contracts)
    if observed_keys != expected_keys or list(contracts) != raw:
        raise RuntimeError(
            "Performance Local v2 canonical contract is incomplete or non-canonical."
        )
    return contracts


def _load_performance_local_v3_component_contracts() -> tuple[dict[str, Any], ...]:
    contract_path = Path(__file__).with_name("performance_local_v3_contract.json")
    raw = json.loads(contract_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RuntimeError("Performance Local v3 canonical contract must be a JSON array.")
    contracts = tuple(
        ThemeFamilyComponentContract.model_validate(item).model_dump(mode="json")
        for item in raw
    )
    expected_keys = tuple(
        item["component_key"] for item in PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS
    )
    observed_keys = tuple(item["component_key"] for item in contracts)
    if (
        observed_keys != expected_keys
        or list(contracts) != raw
        or any(item["contract_version"] != 3 for item in contracts)
        or any(item["theme_compatibility"] != ["performance-local@3"] for item in contracts)
    ):
        raise RuntimeError(
            "Performance Local v3 canonical contract is incomplete or non-canonical."
        )
    return contracts


# Single serialized authority used for durable registration/fingerprinting and
# exact frontend parity verification. Runtime camelCase configuration remains
# an adapter concern and is not persisted as the durable component contract.
PERFORMANCE_LOCAL_V2_SOURCE_COMMIT = "1b766664ea99d923195bbf98e8a1e4d833b50084"
PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS = (
    _load_performance_local_v2_component_contracts()
)
PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS = (
    _load_performance_local_v3_component_contracts()
)
PERFORMANCE_LOCAL_V3_CONTRACT_FINGERPRINT = hashlib.sha256(
    json.dumps(
        PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
).hexdigest()

class ThemeFamilyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family_key: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    provider_source_identity: str = Field(min_length=1, max_length=240)
    created_by: str = Field(min_length=1, max_length=160)

    @field_validator("family_key")
    @classmethod
    def validate_family_key(cls, value: str) -> str:
        return _validate_key(value, "Theme Family key")

    @field_validator("display_name", "description", "provider_source_identity", "created_by")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _clean_text(value, "Theme Family field")


class ThemeFamilyVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    lifecycle_status: Literal["preview_candidate"] = "preview_candidate"
    production_ready: Literal[False] = False
    source_commit: str = Field(min_length=40, max_length=40)
    supported_component_contracts: list[ThemeFamilyComponentContract] = Field(
        min_length=1,
        max_length=100,
    )
    created_by: str = Field(min_length=1, max_length=160)
    supersedes_theme_family_version_id: int | None = Field(default=None, ge=1)

    @field_validator("source_commit")
    @classmethod
    def validate_source_commit(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not _SOURCE_COMMIT_PATTERN.fullmatch(cleaned):
            raise ValueError("Source commit must be an exact lowercase 40-character Git SHA")
        return cleaned

    @field_validator("created_by")
    @classmethod
    def normalize_created_by(cls, value: str) -> str:
        return _clean_text(value, "Theme Version creator")

    @model_validator(mode="after")
    def validate_contracts(self) -> "ThemeFamilyVersionCreate":
        keys = [item.component_key for item in self.supported_component_contracts]
        if len(keys) != len(set(keys)):
            raise ValueError("Theme Version component contracts must use unique component keys")
        if any(item.contract_version != self.version for item in self.supported_component_contracts):
            raise ValueError("Every component contract must match the Theme Version")
        return self


class WebsiteThemeConfigurationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_family_version_id: int = Field(ge=1)
    configuration_key: str = Field(min_length=1, max_length=120)
    created_by: str = Field(min_length=1, max_length=160)
    creation_rationale: str = Field(min_length=1, max_length=2000)
    supersedes_configuration_id: int | None = Field(default=None, ge=1)

    @field_validator("configuration_key")
    @classmethod
    def validate_configuration_key(cls, value: str) -> str:
        return _validate_key(value, "Website Theme configuration key")

    @field_validator("created_by", "creation_rationale")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _clean_text(value, "Website Theme configuration field")


class FormFieldValidationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: Literal["nonempty_text", "phone", "postal_code", "free_text"]
    minimum_length: int = Field(default=0, ge=0, le=10000)
    maximum_length: int = Field(ge=1, le=10000)

    @model_validator(mode="after")
    def validate_lengths(self) -> "FormFieldValidationContract":
        if self.minimum_length > self.maximum_length:
            raise ValueError("Form validation minimum length cannot exceed maximum length")
        return self


FormFieldKey = Literal[
    "name",
    "phone",
    "postal-code",
    "requested-service",
    "message",
]


class CompactEstimateFormField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: FormFieldKey
    label: str = Field(min_length=1, max_length=160)
    required: bool
    control: Literal["input", "textarea"]
    input_type: Literal["text", "tel"]
    order: int = Field(ge=1, le=5)
    accessibility_label: str = Field(min_length=1, max_length=160)
    autocomplete_policy: Literal["name", "tel", "postal-code", "off"]
    maximum_length: int = Field(ge=1, le=10000)
    validation_contract: FormFieldValidationContract
    responsive_layout: Literal["half", "full"]
    provider_mapping: str = Field(
        min_length=1,
        max_length=120,
        description=(
            "Provider-neutral normalized-envelope field key; it does not select or enable an adapter."
        ),
    )

    @field_validator("label", "accessibility_label")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _clean_text(value, "Form field label")

    @field_validator("provider_mapping")
    @classmethod
    def validate_provider_mapping(cls, value: str) -> str:
        return _validate_key(value, "Provider mapping")

    @model_validator(mode="after")
    def validate_field_contract(self) -> "CompactEstimateFormField":
        if self.maximum_length != self.validation_contract.maximum_length:
            raise ValueError("Form field maximum length must match its validation contract")
        if self.control == "textarea" and self.input_type != "text":
            raise ValueError("Textarea fields must use text input semantics")
        if self.control == "input" and self.field_key == "message":
            raise ValueError("The Optional message field must be a textarea")
        return self


class EvergreenConversionBannerConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["evergreen_conversion"]
    message: str = Field(min_length=1, max_length=240)
    cta_label: str = Field(min_length=1, max_length=120)
    approval_identity: str = Field(min_length=1, max_length=160)

    @field_validator("message", "cta_label")
    @classmethod
    def validate_evergreen_text(cls, value: str) -> str:
        cleaned = _clean_text(value, "Evergreen conversion field")
        if _FORBIDDEN_EVERGREEN_LANGUAGE.search(cleaned):
            raise ValueError("Evergreen conversion text contains promotional or unsupported language")
        return cleaned

    @field_validator("approval_identity")
    @classmethod
    def normalize_approval_identity(cls, value: str) -> str:
        return _clean_text(value, "Evergreen approval identity")


class TimeBoundCampaignConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["time_bound_campaign"]
    message: str = Field(min_length=1, max_length=240)
    cta_label: str = Field(min_length=1, max_length=120)
    approved_offer_details: str = Field(min_length=1, max_length=1000)
    terms_reference: str = Field(min_length=1, max_length=1000)
    start_at: datetime
    end_at: datetime
    approval_identity: str = Field(min_length=1, max_length=160)

    @field_validator(
        "message",
        "cta_label",
        "approved_offer_details",
        "terms_reference",
        "approval_identity",
    )
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _clean_text(value, "Time-bound campaign field")

    @model_validator(mode="after")
    def validate_dates(self) -> "TimeBoundCampaignConfiguration":
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("Time-bound campaign timestamps must include a timezone")
        if self.end_at <= self.start_at:
            raise ValueError("Time-bound campaign end time must be after its start time")
        return self


class StickyCallEstimateConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_source: Literal["governed_website_identity"]
    call_label: str = Field(min_length=1, max_length=80)
    estimate_label: str = Field(min_length=1, max_length=120)
    desktop_sticky_header: bool
    mobile_sticky_bottom: bool
    hide_while_hero_actions_visible: bool
    hide_while_navigation_open: bool
    protect_form_focus: bool
    safe_area_support: bool
    prevent_content_obstruction: bool

    @field_validator("call_label", "estimate_label")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _clean_text(value, "Sticky action label")


class CompactEstimateFormConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_state: Literal["disabled_pending_provider_configuration"]
    fields: list[CompactEstimateFormField] = Field(min_length=5, max_length=5)
    submit_label: str = Field(min_length=1, max_length=120)
    preview_notice: str = Field(min_length=1, max_length=500)
    provider_key: None = None
    destination: None = None
    privacy_policy_destination: None = None
    consent_language: None = None
    data_retention_policy: None = None
    spam_strategy: None = None
    success_behavior: None = None
    failure_behavior: None = None
    audit_identity: None = None

    @field_validator("submit_label", "preview_notice")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _clean_text(value, "Estimate form field")

    @model_validator(mode="after")
    def validate_exact_fields(self) -> "CompactEstimateFormConfiguration":
        expected = [
            ("name", "Name", True, "input", "text", 1),
            ("phone", "Phone", True, "input", "tel", 2),
            ("postal-code", "ZIP code", True, "input", "text", 3),
            ("requested-service", "Requested service", True, "input", "text", 4),
            ("message", "Optional message", False, "textarea", "text", 5),
        ]
        observed = [
            (
                item.field_key,
                item.label,
                item.required,
                item.control,
                item.input_type,
                item.order,
            )
            for item in self.fields
        ]
        if observed != expected:
            raise ValueError("Compact estimate form must preserve the exact five-field contract and order")
        if any(item.accessibility_label != item.label for item in self.fields):
            raise ValueError("Each compact estimate form field requires its exact accessible label")
        if any(item.autocomplete_policy != "off" for item in self.fields):
            raise ValueError("The provider-disabled preview requires autocomplete off for every field")
        return self


FormConsentMode = Literal["not_required", "explicit"]
FormSpamStrategy = Literal[
    "honeypot",
    "rate_limit_service",
    "proof_of_work",
    "captcha_provider",
    "synthetic_test",
]


class FormProviderConfigurationV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_key: str | None = Field(default=None, max_length=120)
    destination: str | None = Field(default=None, max_length=1000)
    provider_secret_reference: str | None = Field(default=None, max_length=260)
    test_only: bool = False

    @field_validator("provider_key")
    @classmethod
    def normalize_provider_key(cls, value: str | None) -> str | None:
        return _validate_key(value, "Form provider key") if value is not None else None

    @field_validator("destination")
    @classmethod
    def validate_destination_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _clean_text(value, "Form provider destination")
        if cleaned != "memory://discard" and not _DESTINATION_REFERENCE_PATTERN.fullmatch(
            cleaned
        ):
            raise ValueError(
                "Provider destination must be a credential-free opaque destination reference"
            )
        return cleaned

    @field_validator("provider_secret_reference")
    @classmethod
    def validate_secret_reference(cls, value: str | None) -> str | None:
        if value is not None and not _SECRET_REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("Provider secret identity must be an opaque secret-manager reference")
        return value

    @model_validator(mode="after")
    def contain_test_destination(self) -> "FormProviderConfigurationV3":
        if self.test_only and self.destination not in {None, "memory://discard"}:
            raise ValueError("A test-only form provider may target only the discard destination")
        if not self.test_only and self.destination == "memory://discard":
            raise ValueError("The synthetic discard destination cannot enter production state")
        return self


class FormPrivacyConfigurationV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_destination: str | None = Field(default=None, max_length=1000)
    consent_mode: FormConsentMode | None = None
    consent_text: str | None = Field(default=None, max_length=2000)
    consent_text_version: str | None = Field(default=None, max_length=160)

    @field_validator("consent_text", "consent_text_version")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _clean_text(value, "Form privacy field") if value is not None else None

    @field_validator("policy_destination")
    @classmethod
    def validate_policy_destination(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _clean_text(value, "Privacy-policy destination")
        if "\\" in cleaned:
            raise ValueError("Privacy-policy destination contains an unsafe path separator")
        if cleaned.startswith("/") and not cleaned.startswith("//"):
            if "?" in cleaned or "#" in cleaned:
                raise ValueError("Privacy-policy destination cannot contain a query or fragment")
            return cleaned
        try:
            parsed = urlsplit(cleaned)
            hostname = parsed.hostname
            port = parsed.port
        except (TypeError, ValueError) as exc:
            raise ValueError("Privacy-policy destination is malformed") from exc
        loopback_http = parsed.scheme == "http" and hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if (
            not (parsed.scheme == "https" or loopback_http)
            or hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
            or port is not None and not 1 <= port <= 65535
        ):
            raise ValueError("Privacy-policy destination must be a safe approved URL or path")
        return cleaned

    @model_validator(mode="after")
    def validate_consent(self) -> "FormPrivacyConfigurationV3":
        if self.consent_mode == "explicit" and (
            self.consent_text is None or self.consent_text_version is None
        ):
            raise ValueError("Explicit consent requires approved text and version")
        if self.consent_mode != "explicit" and (
            self.consent_text is not None or self.consent_text_version is not None
        ):
            raise ValueError("Consent text may exist only for explicit consent")
        return self


class FormRetentionConfigurationV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration: str | None = Field(default=None, max_length=240)
    deletion_expiration_behavior: str | None = Field(default=None, max_length=1000)

    @field_validator("duration", "deletion_expiration_behavior")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _clean_text(value, "Form retention field") if value is not None else None


class FormSpamConfigurationV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: FormSpamStrategy | None = None
    configuration_reference: str | None = Field(default=None, max_length=240)

    @field_validator("configuration_reference")
    @classmethod
    def normalize_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _clean_text(value, "Spam configuration reference")
        if cleaned != "synthetic-noop" and not _SPAM_REFERENCE_PATTERN.fullmatch(
            cleaned
        ):
            raise ValueError(
                "Spam configuration identity must be a credential-free opaque reference"
            )
        return cleaned

    @model_validator(mode="after")
    def validate_strategy_reference(self) -> "FormSpamConfigurationV3":
        if (self.strategy is None) != (self.configuration_reference is None):
            raise ValueError("Spam strategy and configuration reference must be configured together")
        if self.strategy == "synthetic_test" and self.configuration_reference != "synthetic-noop":
            raise ValueError("The synthetic spam strategy requires its exact no-op reference")
        if self.strategy not in {None, "synthetic_test"} and self.configuration_reference == "synthetic-noop":
            raise ValueError("The synthetic no-op reference cannot enter production state")
        return self


class FormSecurityConfigurationV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    same_origin_policy: Literal["exact_origin"] | None = None
    csrf_policy: Literal["origin_and_token"] | None = None
    request_size_limit_bytes: int | None = Field(default=None, ge=1024, le=65536)
    idempotency_strategy: Literal["required_header"] | None = None


class CompactEstimateFormConfigurationV3(BaseModel):
    """Provider-neutral V3 configuration; it never contains submitted values."""

    model_config = ConfigDict(extra="forbid")

    submission_state: Literal[
        "disabled_pending_provider_configuration",
        "rehearsal_ready",
        "production_configured",
    ]
    fields: list[CompactEstimateFormField] = Field(min_length=5, max_length=5)
    submit_label: str = Field(min_length=1, max_length=120)
    preview_notice: str = Field(min_length=1, max_length=500)
    provider: FormProviderConfigurationV3
    privacy: FormPrivacyConfigurationV3
    retention: FormRetentionConfigurationV3
    spam: FormSpamConfigurationV3
    success_behavior: str | None = Field(default=None, max_length=1000)
    failure_behavior: str | None = Field(default=None, max_length=1000)
    security: FormSecurityConfigurationV3
    audit_identity: str | None = Field(default=None, max_length=160)

    @field_validator(
        "submit_label",
        "preview_notice",
        "success_behavior",
        "failure_behavior",
        "audit_identity",
    )
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return _clean_text(value, "V3 estimate form field") if value is not None else None

    @model_validator(mode="after")
    def validate_exact_fields_and_state(self) -> "CompactEstimateFormConfigurationV3":
        expected = [
            ("name", "Name", True, "input", "text", 1),
            ("phone", "Phone", True, "input", "tel", 2),
            ("postal-code", "ZIP code", True, "input", "text", 3),
            ("requested-service", "Requested service", True, "input", "text", 4),
            ("message", "Optional message", False, "textarea", "text", 5),
        ]
        observed = [
            (
                item.field_key,
                item.label,
                item.required,
                item.control,
                item.input_type,
                item.order,
            )
            for item in self.fields
        ]
        if observed != expected:
            raise ValueError("V3 compact estimate form must preserve the exact five-field contract")
        if any(item.accessibility_label != item.label for item in self.fields):
            raise ValueError("Every V3 estimate field requires its exact accessible label")
        if len({item.provider_mapping for item in self.fields}) != len(self.fields):
            raise ValueError("V3 provider-neutral field mappings must be unique")

        governed_values = (
            self.provider.provider_key,
            self.provider.destination,
            self.provider.provider_secret_reference,
            self.privacy.policy_destination,
            self.privacy.consent_mode,
            self.retention.duration,
            self.retention.deletion_expiration_behavior,
            self.spam.strategy,
            self.success_behavior,
            self.failure_behavior,
            self.security.same_origin_policy,
            self.security.csrf_policy,
            self.security.request_size_limit_bytes,
            self.security.idempotency_strategy,
            self.audit_identity,
        )
        if self.submission_state == "disabled_pending_provider_configuration":
            if any(value is not None for value in governed_values) or self.provider.test_only:
                raise ValueError("A disabled V3 form cannot contain delivery or readiness values")
            return self

        if any(value is None for value in governed_values):
            raise ValueError("A configured V3 form requires every delivery and readiness value")
        if self.submission_state == "rehearsal_ready":
            if not self.provider.test_only or self.spam.strategy != "synthetic_test":
                raise ValueError("Rehearsal-ready forms require the contained synthetic provider strategy")
        elif self.provider.test_only or self.spam.strategy == "synthetic_test":
            raise ValueError("Synthetic provider configuration cannot enter production state")
        return self


ComponentConfigurationPayload = (
    EvergreenConversionBannerConfiguration
    | TimeBoundCampaignConfiguration
    | StickyCallEstimateConfiguration
    | CompactEstimateFormConfiguration
    | CompactEstimateFormConfigurationV3
)


def validate_component_payload(
    component_key: str,
    payload: dict[str, Any],
    component_contract_version: int = 2,
) -> dict[str, Any]:
    reject_secret_configuration(payload)
    model: type[BaseModel]
    if component_key == "campaign_banner":
        intent = payload.get("intent")
        if intent == "evergreen_conversion":
            model = EvergreenConversionBannerConfiguration
        elif intent == "time_bound_campaign":
            model = TimeBoundCampaignConfiguration
        else:
            raise ValueError("Campaign configuration requires a supported typed intent")
    elif component_key == "sticky_mobile_action_bar":
        model = StickyCallEstimateConfiguration
    elif component_key == "compact_estimate_form":
        model = (
            CompactEstimateFormConfigurationV3
            if component_contract_version in {3, 5}
            else CompactEstimateFormConfiguration
        )
    else:
        raise ValueError("This milestone does not authorize an untyped component configuration")
    return model.model_validate(payload).model_dump(mode="json")


def validate_component_schedule(
    component_key: str,
    normalized_payload: dict[str, Any],
    effective_at: datetime | None,
    expires_at: datetime | None,
) -> None:
    if component_key != "campaign_banner":
        if effective_at is not None or expires_at is not None:
            raise ValueError("Only a time-bound campaign may define effective dates")
        return
    intent = normalized_payload.get("intent")
    if intent == "evergreen_conversion":
        if effective_at is not None or expires_at is not None:
            raise ValueError("Evergreen conversion configuration cannot define effective dates")
        return
    campaign = TimeBoundCampaignConfiguration.model_validate(normalized_payload)
    if effective_at is None or expires_at is None:
        raise ValueError("Time-bound campaign requires exact effective and expiration dates")
    if effective_at.tzinfo is None or expires_at.tzinfo is None:
        raise ValueError("Time-bound campaign component dates must include a timezone")
    if (
        effective_at.astimezone(UTC) != campaign.start_at.astimezone(UTC)
        or expires_at.astimezone(UTC) != campaign.end_at.astimezone(UTC)
    ):
        raise ValueError("Time-bound campaign component dates must match its approved payload")


class WebsiteThemeComponentConfigurationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_instance_key: str = Field(min_length=1, max_length=120)
    component_key: ComponentKey
    component_contract_version: int = Field(ge=1)
    scope_type: ComponentScope
    planned_page_id: int | None = Field(default=None, ge=1)
    enabled: bool
    variant: str = Field(min_length=1, max_length=120)
    placement: str = Field(min_length=1, max_length=120)
    responsive_visibility: ResponsiveVisibility
    configuration_payload: dict[str, Any]
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    approval_identity: str | None = Field(default=None, max_length=160)
    created_by: str = Field(min_length=1, max_length=160)
    destination_component_configuration_id: int | None = Field(default=None, ge=1)
    overrides_component_configuration_id: int | None = Field(default=None, ge=1)

    @field_validator("component_instance_key")
    @classmethod
    def validate_instance_key(cls, value: str) -> str:
        return _validate_key(value, "Component instance key", instance=True)

    @field_validator("variant", "placement", "created_by")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _clean_text(value, "Component configuration field")

    @field_validator("approval_identity")
    @classmethod
    def normalize_approval_identity(cls, value: str | None) -> str | None:
        return _clean_text(value, "Approval identity") if value is not None else None

    @model_validator(mode="after")
    def validate_configuration(self) -> "WebsiteThemeComponentConfigurationCreate":
        website_default = self.scope_type == "website_default"
        if website_default != (self.planned_page_id is None):
            raise ValueError("Page override scope requires one exact Planned Page identity")
        if website_default != (self.overrides_component_configuration_id is None):
            raise ValueError("Page override scope requires one exact Website-default component target")
        if self.expires_at and self.effective_at and self.expires_at < self.effective_at:
            raise ValueError("Component expiration cannot precede its effective time")
        self.configuration_payload = validate_component_payload(
            self.component_key,
            self.configuration_payload,
            self.component_contract_version,
        )
        validate_component_schedule(
            self.component_key,
            self.configuration_payload,
            self.effective_at,
            self.expires_at,
        )
        needs_destination = self.component_key in {
            "campaign_banner",
            "sticky_mobile_action_bar",
        }
        if needs_destination != (self.destination_component_configuration_id is not None):
            raise ValueError("Conversion actions require one exact compact-form configuration target")
        if self.component_key == "compact_estimate_form" and self.destination_component_configuration_id:
            raise ValueError("The compact form cannot target another component")
        return self


class WebsiteThemeComponentConfigurationRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    variant: str = Field(min_length=1, max_length=120)
    placement: str = Field(min_length=1, max_length=120)
    responsive_visibility: ResponsiveVisibility
    configuration_payload: dict[str, Any]
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    approval_identity: str | None = Field(default=None, max_length=160)
    updated_by: str = Field(min_length=1, max_length=160)
    revision_rationale: str = Field(min_length=1, max_length=2000)
    destination_component_configuration_id: int | None = Field(default=None, ge=1)

    @field_validator("variant", "placement", "updated_by", "revision_rationale")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _clean_text(value, "Component revision field")


class ConversionComponentGraphRevisionCreate(BaseModel):
    """One atomic form/banner/sticky revision with no invalid intermediate graph."""

    model_config = ConfigDict(extra="forbid")

    form_component_configuration_id: int = Field(ge=1)
    banner_component_configuration_id: int = Field(ge=1)
    sticky_component_configuration_id: int = Field(ge=1)
    form_revision: WebsiteThemeComponentConfigurationRevisionCreate
    banner_revision: WebsiteThemeComponentConfigurationRevisionCreate
    sticky_revision: WebsiteThemeComponentConfigurationRevisionCreate


class ThemeDraftWebsiteConfigurationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configuration_key: str = Field(min_length=1, max_length=120)
    created_by: str = Field(min_length=1, max_length=160)
    creation_rationale: str = Field(min_length=1, max_length=2000)

    @field_validator("configuration_key")
    @classmethod
    def validate_configuration_key(cls, value: str) -> str:
        return _validate_key(value, "Website Theme configuration key")

    @field_validator("created_by", "creation_rationale")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _clean_text(value, "Website Theme draft field")


class ThemeDraftBundleComponentSpec(BaseModel):
    """Pre-ID component specification used only by the atomic draft bundle."""

    model_config = ConfigDict(extra="forbid")

    component_instance_key: str = Field(min_length=1, max_length=120)
    component_key: ComponentKey
    component_contract_version: int = Field(ge=1)
    scope_type: ComponentScope = "website_default"
    planned_page_id: int | None = Field(default=None, ge=1)
    enabled: bool
    variant: str = Field(min_length=1, max_length=120)
    placement: str = Field(min_length=1, max_length=120)
    responsive_visibility: ResponsiveVisibility
    configuration_payload: dict[str, Any]
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    approval_identity: str = Field(min_length=1, max_length=160)
    created_by: str = Field(min_length=1, max_length=160)
    destination_component_instance_key: str | None = Field(
        default=None,
        max_length=120,
    )
    overrides_component_configuration_id: int | None = Field(default=None, ge=1)

    @field_validator("component_instance_key")
    @classmethod
    def validate_instance_key(cls, value: str) -> str:
        return _validate_key(value, "Component instance key", instance=True)

    @field_validator("destination_component_instance_key")
    @classmethod
    def validate_destination_key(cls, value: str | None) -> str | None:
        return (
            _validate_key(value, "Destination component instance key", instance=True)
            if value is not None
            else None
        )

    @field_validator("variant", "placement", "created_by", "approval_identity")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _clean_text(value, "Theme draft component field")

    @model_validator(mode="after")
    def validate_configuration(self) -> "ThemeDraftBundleComponentSpec":
        if self.scope_type != "website_default" or self.planned_page_id is not None:
            raise ValueError("The initial atomic draft bundle supports only Website-default components")
        if self.overrides_component_configuration_id is not None:
            raise ValueError("The initial atomic draft bundle creates no Page overrides")
        if self.expires_at and self.effective_at and self.expires_at < self.effective_at:
            raise ValueError("Component expiration cannot precede its effective time")
        self.configuration_payload = validate_component_payload(
            self.component_key,
            self.configuration_payload,
            self.component_contract_version,
        )
        validate_component_schedule(
            self.component_key,
            self.configuration_payload,
            self.effective_at,
            self.expires_at,
        )
        requires_destination = self.component_key in {
            "campaign_banner",
            "sticky_mobile_action_bar",
        }
        if requires_destination != (self.destination_component_instance_key is not None):
            raise ValueError("Conversion actions require the exact compact-form instance key")
        return self


class ThemeDraftBundleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_family: ThemeFamilyCreate
    theme_version: ThemeFamilyVersionCreate
    website_configuration: ThemeDraftWebsiteConfigurationSpec
    components: list[ThemeDraftBundleComponentSpec] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_exact_bundle(self) -> "ThemeDraftBundleCreate":
        by_key = {item.component_key: item for item in self.components}
        expected = {
            "campaign_banner",
            "sticky_mobile_action_bar",
            "compact_estimate_form",
        }
        if set(by_key) != expected or len(by_key) != len(self.components):
            raise ValueError("Atomic Theme draft bundle requires exactly one banner, sticky action, and form")
        form_key = by_key["compact_estimate_form"].component_instance_key
        for key in ("campaign_banner", "sticky_mobile_action_bar"):
            if by_key[key].destination_component_instance_key != form_key:
                raise ValueError("Every conversion action must target the exact compact-form instance")
        return self


class ThemeFamilyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    family_key: str
    display_name: str
    description: str
    provider_source_identity: str
    lifecycle_status: ThemeFamilyLifecycle
    created_by: str
    retired_by: str | None
    retired_at: datetime | None
    integrity_fingerprint: str
    created_at: datetime
    updated_at: datetime


class ThemeFamilyVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    theme_family_id: int
    version: int
    lifecycle_status: ThemeFamilyVersionLifecycle
    production_ready: bool
    source_commit: str
    compatibility_identity: str
    supported_component_contracts: list[dict[str, Any]]
    created_by: str
    retired_by: str | None
    retired_at: datetime | None
    supersedes_theme_family_version_id: int | None
    integrity_fingerprint: str
    created_at: datetime
    updated_at: datetime


class WebsiteThemeConfigurationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    website_id: int
    business_id: int
    theme_family_version_id: int
    configuration_key: str
    version: int
    lifecycle_status: WebsiteThemeConfigurationLifecycle
    created_by: str
    updated_by: str
    creation_rationale: str
    approved_by: str | None
    approved_at: datetime | None
    activated_by: str | None
    activated_at: datetime | None
    rollback_by: str | None
    rollback_at: datetime | None
    materialized_theme_id: int | None
    website_theme_selection_id: int | None
    supersedes_configuration_id: int | None
    integrity_fingerprint: str
    created_at: datetime
    updated_at: datetime


class WebsiteThemeComponentConfigurationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    website_theme_configuration_id: int
    website_id: int
    planned_page_id: int | None
    theme_family_version_id: int
    component_instance_key: str
    component_key: str
    component_contract_version: int
    revision: int
    scope_type: ComponentScope
    lifecycle_status: ComponentConfigurationLifecycle
    enabled: bool
    variant: str
    placement: str
    responsive_visibility: dict[str, bool]
    configuration_payload: dict[str, Any]
    effective_at: datetime | None
    expires_at: datetime | None
    approval_identity: str | None
    created_by: str
    updated_by: str
    activation_identity: str | None
    activated_at: datetime | None
    rollback_identity: str | None
    rollback_at: datetime | None
    destination_component_configuration_id: int | None
    overrides_component_configuration_id: int | None
    supersedes_component_configuration_id: int | None
    integrity_fingerprint: str
    created_at: datetime
    updated_at: datetime


class ConversionComponentGraphRevisionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    form: WebsiteThemeComponentConfigurationRead
    banner: WebsiteThemeComponentConfigurationRead
    sticky: WebsiteThemeComponentConfigurationRead


class ThemeConfigurationAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    theme_family_id: int | None
    theme_family_version_id: int | None
    website_theme_configuration_id: int | None
    component_configuration_id: int | None
    action_type: ThemeConfigurationAuditAction
    actor: str
    rationale: str
    snapshot: dict[str, Any]
    snapshot_hash: str
    created_at: datetime


class GovernedThemeActionsRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone_display: str | None
    call_destination: str | None
    call_label: str | None
    estimate_label: str | None
    estimate_destination_component_configuration_id: int | None
    desktop_header_actions_enabled: bool
    mobile_sticky_actions_enabled: bool
    desktop_header_estimate_destination_component_configuration_id: int | None
    mobile_sticky_estimate_destination_component_configuration_id: int | None


class FormProviderStateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_state: Literal["disabled_pending_provider_configuration"]
    provider_key: None = None
    destination: None = None
    can_submit: Literal[False] = False
    collects_data: Literal[False] = False


ProductionFormSubmissionBlockerCode = Literal[
    "missing_provider",
    "missing_destination",
    "missing_privacy_policy_destination",
    "missing_consent_language",
    "missing_data_retention_policy",
    "missing_spam_strategy",
    "missing_success_behavior",
    "missing_failure_behavior",
    "missing_audit_identity",
    "insecure_secret_handling",
    "provider_adapter_unavailable",
]


class ProductionFormSubmissionPreflightInput(BaseModel):
    """Provider-neutral production preflight; this schema stores and submits nothing."""

    model_config = ConfigDict(extra="forbid")

    provider_key: str | None = Field(default=None, max_length=120)
    destination: str | None = Field(default=None, max_length=1000)
    privacy_policy_destination: str | None = Field(default=None, max_length=1000)
    consent_required: bool = False
    consent_language: str | None = Field(default=None, max_length=2000)
    data_retention_policy: str | None = Field(default=None, max_length=2000)
    spam_strategy: str | None = Field(default=None, max_length=2000)
    success_behavior: str | None = Field(default=None, max_length=2000)
    failure_behavior: str | None = Field(default=None, max_length=2000)
    audit_identity: str | None = Field(default=None, max_length=160)
    secret_handling_policy: Literal["external_secret_manager_reference_only"] | None = None

    @field_validator(
        "provider_key",
        "destination",
        "privacy_policy_destination",
        "consent_language",
        "data_retention_policy",
        "spam_strategy",
        "success_behavior",
        "failure_behavior",
        "audit_identity",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _clean_text(value, "Production form contract field") if value is not None else None


class ProductionFormSubmissionContractRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_key: str
    destination: str
    privacy_policy_destination: str
    consent_required: bool
    consent_language: str | None
    data_retention_policy: str
    spam_strategy: str
    success_behavior: str
    failure_behavior: str
    audit_identity: str
    secret_handling_policy: Literal["external_secret_manager_reference_only"]


class ProductionFormSubmissionReadinessItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ProductionFormSubmissionBlockerCode
    field: str
    reason: str


class ProductionFormSubmissionReadinessRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["blocked"] = "blocked"
    contract_complete: bool
    provider_adapter_registered: Literal[False] = False
    can_submit: Literal[False] = False
    delivery_attempted: Literal[False] = False
    contract: ProductionFormSubmissionContractRead | None
    blockers: list[ProductionFormSubmissionReadinessItem]


class ThemeConfigurationExportComponentRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_configuration_id: int
    component_instance_key: str
    component_key: str
    component_contract_version: int
    revision: int
    scope_type: ComponentScope
    planned_page_id: int | None
    destination_component_configuration_id: int | None
    overrides_component_configuration_id: int | None
    integrity_fingerprint: str


class ThemeConfigurationExportEligibilityRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website_id: int
    business_id: int
    theme_family_id: int
    family_key: str
    theme_family_version_id: int
    family_version: int
    theme_compatibility_identity: str
    theme_family_version_integrity_fingerprint: str
    website_theme_configuration_id: int
    configuration_key: str
    configuration_version: int
    configuration_lifecycle_status: Literal["active"]
    configuration_integrity_fingerprint: str
    theme_id: int
    website_theme_selection_id: int
    generated_page_id: int
    planned_page_id: int
    effective_components: list[ThemeConfigurationExportComponentRead]
    audit_snapshot_hashes: list[str]


class PerformanceLocalV3ExportEligibilityRead(
    ThemeConfigurationExportEligibilityRead
):
    model_config = ConfigDict(extra="forbid")

    activation_audit_identity: list[str]
    banner_intent: str | None
    sticky_action_identity: dict[str, Any] | None
    form_state: str
    provider_state: dict[str, Any]
    privacy_consent_readiness: dict[str, Any]


class ThemeActivationReadinessItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    reason: str


class ThemeActivationReadinessRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["blocked"] = "blocked"
    can_activate: Literal[False] = False
    can_publish: Literal[False] = False
    can_deploy: Literal[False] = False
    production_ready: Literal[False] = False
    incomplete_items: list[ThemeActivationReadinessItem]


class ThemeDraftPreviewRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_label: Literal["DRAFT PREVIEW — NOT ACTIVE"]
    theme_family: ThemeFamilyRead
    theme_version: ThemeFamilyVersionRead
    website_configuration: WebsiteThemeConfigurationRead
    components: list[WebsiteThemeComponentConfigurationRead]
    audit_history: list[ThemeConfigurationAuditRead]
    governed_actions: GovernedThemeActionsRead
    provider_state: FormProviderStateRead
    readiness: ThemeActivationReadinessRead
    requested_generated_page_id: int | None
    export_eligible: Literal[False] = False
    privacy_status: Literal["blocked_pending_privacy_configuration"] = (
        "blocked_pending_privacy_configuration"
    )
    activation_status: Literal["blocked"] = "blocked"
    publication_status: Literal["blocked"] = "blocked"
    deployment_status: Literal["blocked"] = "blocked"


class FormReadinessItemRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    field: str
    reason: str


class FormProviderReadinessStateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_key: str | None
    destination_configured: bool
    adapter_registered: bool
    test_only: bool


class FormPrivacyReadinessStateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_configured: bool
    consent_mode: FormConsentMode | None
    consent_text_version: str | None
    ready: bool


class FormRetentionReadinessStateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_configured: bool
    deletion_behavior_configured: bool
    ready: bool


class FormSpamReadinessStateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: FormSpamStrategy | None
    ready: bool


class FormBehaviorReadinessStateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success_configured: bool
    failure_configured: bool
    ready: bool


class FormSecurityReadinessStateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_reference_configured: bool
    same_origin_policy: str | None
    csrf_policy: str | None
    csrf_token: str | None
    request_size_limit_bytes: int | None
    idempotency_strategy: str | None
    ready: bool


class PerformanceLocalFormReadinessRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["blocked", "ready"]
    can_submit: bool
    submission_state: str
    component_configuration_id: int | None
    provider_state: FormProviderReadinessStateRead
    privacy: FormPrivacyReadinessStateRead
    retention: FormRetentionReadinessStateRead
    spam: FormSpamReadinessStateRead
    behavior: FormBehaviorReadinessStateRead
    security: FormSecurityReadinessStateRead
    audit_identity: str | None
    blockers: list[FormReadinessItemRead]


class PerformanceLocalFormSubmissionInput(BaseModel):
    """The normalized public JSON shape; routes still parse the raw Request manually."""

    model_config = ConfigDict(extra="forbid")

    name: str
    phone: str
    postal_code: str
    requested_service: str
    message: str | None = None
    consent_accepted: bool | None = None


class PerformanceLocalFormSubmissionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted"] = "accepted"
    code: Literal["submission_accepted"] = "submission_accepted"
    safe_message: str
    provider_reference: str


class ThemeDeliveryExportEligibilityRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eligible: bool
    mode: Literal["public", "internal_rehearsal"]
    identity: dict[str, Any] | None
    blockers: list[FormReadinessItemRead]


class ThemeDeliveryRendererResultRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "blocked"]
    result_code: str
    evaluated_page_id: int


class ThemeDeliveryBlockerRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    category: Literal[
        "theme",
        "configuration",
        "component",
        "media",
        "qa",
        "form",
        "privacy",
        "export",
        "publication",
    ]
    reason: str


class PerformanceLocalDeliveryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    renderer_contract: Literal["performance-local-delivery@1"] = (
        "performance-local-delivery@1"
    )
    mode: Literal["active", "inactive_draft_preview", "activation_rehearsal"]
    non_active_label: Literal[
        "DRAFT PREVIEW — NOT ACTIVE",
        "ACTIVATION REHEARSAL — DISPOSABLE",
    ] | None
    page: dict[str, Any]
    composition: dict[str, Any]
    theme_family: ThemeFamilyRead
    theme_version: ThemeFamilyVersionRead
    website_configuration: WebsiteThemeConfigurationRead
    components: list[WebsiteThemeComponentConfigurationRead]
    audit_history: list[ThemeConfigurationAuditRead]
    governed_actions: GovernedThemeActionsRead
    form_readiness: PerformanceLocalFormReadinessRead
    export_eligibility: ThemeDeliveryExportEligibilityRead
    renderer_result: ThemeDeliveryRendererResultRead
    blockers: list[ThemeDeliveryBlockerRead]


class ThemeActivationMutationRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int
    operation: str
    target_type: str
    target_id: int | None
    expected_before: str | None
    expected_after: str | None


class ThemeActivationComponentRevisionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_configuration_id: int
    component_instance_key: str
    component_key: str
    revision: int
    integrity_fingerprint: str
    destination_component_configuration_id: int | None
    overrides_component_configuration_id: int | None
    planned_page_id: int | None


class ThemeActivationPlanRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website_id: int
    current_theme_id: int | None
    current_selection_id: int | None
    target_theme_family_id: int
    target_theme_family_version_id: int
    target_configuration_id: int
    component_configuration_ids: list[int]
    component_revision_graph: list[ThemeActivationComponentRevisionRead]
    affected_composition_ids: list[int]
    expected_qa_invalidation_count: int
    expected_refresh_count: int
    expected_export_state: Literal["blocked", "internal_rehearsal_only"]
    form_blockers: list[FormReadinessItemRead]
    privacy_blockers: list[FormReadinessItemRead]
    publication_blockers: list[FormReadinessItemRead]
    rollback_theme_id: int | None
    rollback_selection_id: int | None
    backup_requirements: list[str]
    mutation_ledger: list[ThemeActivationMutationRead]
    audit_events: list[str]
    write_count: Literal[0] = 0


class ThemeActivationRehearsalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_configuration_fingerprint: str
    expected_current_selection_id: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=160)
    confirmation: Literal["DISPOSABLE PERFORMANCE LOCAL V3 REHEARSAL"]

    @field_validator("expected_configuration_fingerprint")
    @classmethod
    def validate_expected_fingerprint(cls, value: str) -> str:
        return validate_fingerprint(value, "Expected rehearsal configuration fingerprint")

    @field_validator("actor")
    @classmethod
    def normalize_actor(cls, value: str) -> str:
        return _clean_text(value, "Rehearsal actor")


class ThemeActivationRehearsalRollbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_configuration_fingerprint: str
    expected_prior_selection_id: int = Field(ge=1)
    expected_rehearsal_theme_id: int = Field(ge=1)
    expected_rehearsal_selection_id: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=160)
    confirmation: Literal["ROLL BACK DISPOSABLE PERFORMANCE LOCAL V3 REHEARSAL"]

    @field_validator("expected_configuration_fingerprint")
    @classmethod
    def validate_expected_fingerprint(cls, value: str) -> str:
        return validate_fingerprint(value, "Expected rehearsal configuration fingerprint")

    @field_validator("actor")
    @classmethod
    def normalize_actor(cls, value: str) -> str:
        return _clean_text(value, "Rehearsal rollback actor")


class ThemeActivationRehearsalRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["activated", "rolled_back"]
    website_id: int
    configuration_id: int
    prior_theme_id: int
    prior_selection_id: int
    rehearsal_theme_id: int
    rehearsal_selection_id: int
    active_selection_count: int
    v3_active_selection_count: int
    mutation_ledger: list[ThemeActivationMutationRead]
    audit_event_types: list[str]


class PerformanceLocalFullSitePageRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_page_id: int
    planned_page_id: int
    page_type: str
    theme_family_id: int
    theme_family_key: str
    theme_version_id: int
    theme_version: int
    configuration_id: int
    component_graph_identity: str
    composition_id: int
    composition_version: int
    composition_source_hash: str
    media_reference_ids: list[int]
    wordpress_media_reference_ids: list[int]
    local_only_media_reference_ids: list[int]
    media_fallback_used: bool
    scope_integrity: Literal["exact", "blocked"] = "exact"
    required_media_state: str
    form_state: str
    banner_state: str
    sticky_action_state: str
    renderer_result: str
    export_eligible: bool
    qa_readiness_result: str
    blockers: list[str]


class PerformanceLocalFullSiteAuditRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website_id: int
    evaluated_page_count: int
    ready_count: int
    blocked_count: int
    pages: list[PerformanceLocalFullSitePageRead]


def validate_fingerprint(value: str, label: str) -> str:
    if not _FINGERPRINT_PATTERN.fullmatch(value):
        raise ValueError(f"{label} is not a canonical SHA-256 fingerprint")
    return value
