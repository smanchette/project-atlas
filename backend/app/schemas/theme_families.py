from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

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
    theme_compatibility: tuple[Literal["performance-local@2"]]
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


# Single serialized authority used for durable registration/fingerprinting and
# exact frontend parity verification. Runtime camelCase configuration remains
# an adapter concern and is not persisted as the durable component contract.
PERFORMANCE_LOCAL_V2_SOURCE_COMMIT = "1b766664ea99d923195bbf98e8a1e4d833b50084"
PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS = (
    _load_performance_local_v2_component_contracts()
)

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


ComponentConfigurationPayload = (
    EvergreenConversionBannerConfiguration
    | TimeBoundCampaignConfiguration
    | StickyCallEstimateConfiguration
    | CompactEstimateFormConfiguration
)


def validate_component_payload(
    component_key: str,
    payload: dict[str, Any],
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
        model = CompactEstimateFormConfiguration
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


def validate_fingerprint(value: str, label: str) -> str:
    if not _FINGERPRINT_PATTERN.fullmatch(value):
        raise ValueError(f"{label} is not a canonical SHA-256 fingerprint")
    return value
