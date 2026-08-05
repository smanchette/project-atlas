from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ColorTokenName = Literal[
    "primary",
    "primary_foreground",
    "secondary",
    "secondary_foreground",
    "accent",
    "accent_foreground",
    "neutral",
    "neutral_foreground",
    "background",
    "surface",
    "text",
    "heading",
    "success",
    "success_foreground",
    "warning",
    "warning_foreground",
    "error",
    "error_foreground",
    "focus",
]
BorderWidthTokenName = Literal["thin", "medium", "thick"]
BorderRadiusTokenName = Literal["small", "medium", "large", "pill"]
ShadowTokenName = Literal["none", "low", "medium", "high"]
SpacingTokenName = Literal["zero", "xs", "sm", "md", "lg", "xl", "xxl"]

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_SAFE_FONT_FAMILY = re.compile(r"^[A-Za-z0-9 ,.'\"-]{1,240}$")
_SAFE_EASING = re.compile(r"^(?:linear|ease|ease-in|ease-out|ease-in-out|cubic-bezier\([0-9., -]+\))$")


def _normalize_hex(value: str) -> str:
    cleaned = value.strip()
    if not _HEX_COLOR.fullmatch(cleaned):
        raise ValueError("Design-token colors must use six-digit hexadecimal notation")
    return cleaned.upper()


class ThemeColorTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str
    primary_foreground: str
    secondary: str
    secondary_foreground: str
    accent: str
    accent_foreground: str
    neutral: str
    neutral_foreground: str
    background: str
    surface: str
    text: str
    heading: str
    success: str
    success_foreground: str
    warning: str
    warning_foreground: str
    error: str
    error_foreground: str
    focus: str

    @field_validator("*", mode="before")
    @classmethod
    def validate_color(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Design-token colors must be strings")
        return _normalize_hex(value)


class ThemeTypographyTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading_family: str = Field(min_length=1, max_length=240)
    body_family: str = Field(min_length=1, max_length=240)
    heading_weight: int = Field(ge=100, le=900, multiple_of=100)
    body_weight: int = Field(ge=100, le=900, multiple_of=100)
    font_scale: dict[str, float]
    line_height: dict[str, float]
    letter_spacing: dict[str, float]

    @field_validator("heading_family", "body_family")
    @classmethod
    def validate_font_family(cls, value: str) -> str:
        cleaned = value.strip()
        if not _SAFE_FONT_FAMILY.fullmatch(cleaned):
            raise ValueError("Font-family tokens contain unsupported characters")
        return cleaned

    @field_validator("font_scale")
    @classmethod
    def validate_font_scale(cls, value: dict[str, float]) -> dict[str, float]:
        required = ("xs", "sm", "base", "lg", "xl", "xxl", "display")
        if set(value) != set(required):
            raise ValueError(f"Font scale must define exactly: {', '.join(required)}")
        normalized = {key: float(value[key]) for key in required}
        if any(item <= 0 or item > 8 for item in normalized.values()):
            raise ValueError("Font-scale values must be greater than zero and no more than 8rem")
        if any(normalized[left] >= normalized[right] for left, right in zip(required, required[1:])):
            raise ValueError("Font-scale values must increase monotonically")
        return normalized

    @field_validator("line_height")
    @classmethod
    def validate_line_height(cls, value: dict[str, float]) -> dict[str, float]:
        required = ("heading", "body")
        if set(value) != set(required):
            raise ValueError("Line height must define exactly heading and body")
        normalized = {key: float(value[key]) for key in required}
        if any(item < 1 or item > 2.5 for item in normalized.values()):
            raise ValueError("Line-height values must be between 1 and 2.5")
        return normalized

    @field_validator("letter_spacing")
    @classmethod
    def validate_letter_spacing(cls, value: dict[str, float]) -> dict[str, float]:
        required = ("heading", "body")
        if set(value) != set(required):
            raise ValueError("Letter spacing must define exactly heading and body")
        normalized = {key: float(value[key]) for key in required}
        if any(item < -0.1 or item > 0.25 for item in normalized.values()):
            raise ValueError("Letter-spacing values must be between -0.1em and 0.25em")
        return normalized


class ThemeSpacingTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scale: dict[str, float]
    section_spacing: dict[str, float]

    @field_validator("scale")
    @classmethod
    def validate_scale(cls, value: dict[str, float]) -> dict[str, float]:
        required = ("zero", "xs", "sm", "md", "lg", "xl", "xxl")
        if set(value) != set(required):
            raise ValueError(f"Spacing scale must define exactly: {', '.join(required)}")
        normalized = {key: float(value[key]) for key in required}
        if normalized["zero"] != 0:
            raise ValueError("Spacing scale zero must equal 0")
        if any(item < 0 or item > 20 for item in normalized.values()):
            raise ValueError("Spacing values must be between 0 and 20rem")
        if any(normalized[left] >= normalized[right] for left, right in zip(required, required[1:])):
            raise ValueError("Positive spacing values must increase monotonically")
        return normalized

    @field_validator("section_spacing")
    @classmethod
    def validate_section_spacing(cls, value: dict[str, float]) -> dict[str, float]:
        required = ("mobile", "tablet", "desktop")
        if set(value) != set(required):
            raise ValueError("Section spacing must define exactly mobile, tablet, and desktop")
        normalized = {key: float(value[key]) for key in required}
        if any(item <= 0 or item > 24 for item in normalized.values()):
            raise ValueError("Section spacing must be greater than zero and no more than 24rem")
        if not normalized["mobile"] <= normalized["tablet"] <= normalized["desktop"]:
            raise ValueError("Section spacing must not decrease at wider breakpoints")
        return normalized


class ThemeContentWidthTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narrow: int = Field(ge=320, le=1600)
    content: int = Field(ge=320, le=1920)
    wide: int = Field(ge=320, le=2560)

    @model_validator(mode="after")
    def validate_order(self) -> ThemeContentWidthTokens:
        if not self.narrow < self.content < self.wide:
            raise ValueError("Content widths must increase from narrow to content to wide")
        return self


class ThemeBorderTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    widths: dict[str, float]
    radii: dict[str, float]

    @field_validator("widths")
    @classmethod
    def validate_widths(cls, value: dict[str, float]) -> dict[str, float]:
        required = ("thin", "medium", "thick")
        if set(value) != set(required):
            raise ValueError("Border widths must define exactly thin, medium, and thick")
        normalized = {key: float(value[key]) for key in required}
        if any(item <= 0 or item > 8 for item in normalized.values()):
            raise ValueError("Border widths must be greater than zero and no more than 8px")
        if not normalized["thin"] <= normalized["medium"] <= normalized["thick"]:
            raise ValueError("Border widths must increase from thin to thick")
        return normalized

    @field_validator("radii")
    @classmethod
    def validate_radii(cls, value: dict[str, float]) -> dict[str, float]:
        required = ("small", "medium", "large", "pill")
        if set(value) != set(required):
            raise ValueError("Border radii must define exactly small, medium, large, and pill")
        normalized = {key: float(value[key]) for key in required}
        if any(item < 0 or item > 9999 for item in normalized.values()):
            raise ValueError("Border radii must be between 0 and 9999px")
        if not normalized["small"] <= normalized["medium"] <= normalized["large"] < normalized["pill"]:
            raise ValueError("Border radii must increase from small to pill")
        return normalized


class ThemeShadowTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    none: str = "none"
    low: str = Field(min_length=1, max_length=200)
    medium: str = Field(min_length=1, max_length=200)
    high: str = Field(min_length=1, max_length=200)

    @field_validator("*")
    @classmethod
    def validate_shadow(cls, value: str) -> str:
        cleaned = value.strip()
        lowered = cleaned.lower()
        if any(fragment in lowered for fragment in ("url(", "expression(", "javascript:", ";")):
            raise ValueError("Shadow tokens contain unsupported CSS")
        return cleaned


class ThemeButtonTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    background: ColorTokenName
    text: ColorTokenName
    border: ColorTokenName
    hover_background: ColorTokenName
    focus: ColorTokenName
    border_width: BorderWidthTokenName
    border_radius: BorderRadiusTokenName
    padding_inline: SpacingTokenName
    padding_block: SpacingTokenName
    min_height: int = Field(ge=44, le=96)
    font_weight: int = Field(ge=100, le=900, multiple_of=100)


class ThemeCardTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    background: ColorTokenName
    text: ColorTokenName
    border: ColorTokenName
    border_width: BorderWidthTokenName
    border_radius: BorderRadiusTokenName
    shadow: ShadowTokenName
    padding: SpacingTokenName


class ThemeNavigationTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    background: ColorTokenName
    text: ColorTokenName
    hover: ColorTokenName
    active: ColorTokenName
    focus: ColorTokenName
    item_spacing: SpacingTokenName
    min_target_size: int = Field(ge=44, le=96)


class ThemeCtaTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    background: ColorTokenName
    text: ColorTokenName
    button_background: ColorTokenName
    button_text: ColorTokenName
    focus: ColorTokenName
    border_radius: BorderRadiusTokenName
    section_spacing: SpacingTokenName
    min_target_size: int = Field(ge=44, le=96)


class ThemeResponsiveTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mobile_max: int = Field(ge=320, le=900)
    tablet_min: int = Field(ge=320, le=1200)
    tablet_max: int = Field(ge=640, le=1600)
    desktop_min: int = Field(ge=800, le=2560)

    @model_validator(mode="after")
    def validate_ranges(self) -> ThemeResponsiveTokens:
        if self.tablet_min != self.mobile_max + 1 or self.desktop_min != self.tablet_max + 1:
            raise ValueError("Responsive breakpoints must be contiguous")
        if self.tablet_min >= self.tablet_max:
            raise ValueError("Tablet breakpoint range is invalid")
        return self


class ThemeLayoutTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_content_columns: int = Field(ge=1, le=4)
    content_alignment: Literal["left", "center"]
    mobile_stack: bool
    gutter: SpacingTokenName
    overflow_behavior: Literal["wrap", "scroll_explicit"]


class ThemeMotionTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_fast_ms: int = Field(ge=0, le=1000)
    duration_normal_ms: int = Field(ge=0, le=1500)
    duration_slow_ms: int = Field(ge=0, le=2500)
    easing: str = Field(min_length=1, max_length=100)
    reduced_motion: Literal["disable_nonessential", "reduce_to_instant"]

    @field_validator("easing")
    @classmethod
    def validate_easing(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not _SAFE_EASING.fullmatch(cleaned):
            raise ValueError("Motion easing is invalid")
        return cleaned

    @model_validator(mode="after")
    def validate_durations(self) -> ThemeMotionTokens:
        if not self.duration_fast_ms <= self.duration_normal_ms <= self.duration_slow_ms:
            raise ValueError("Motion durations must increase from fast to slow")
        return self


class ThemeDesignTokens(BaseModel):
    """Governed presentation tokens; no business facts, content, or media live here."""

    model_config = ConfigDict(extra="forbid")

    colors: ThemeColorTokens
    typography: ThemeTypographyTokens
    spacing: ThemeSpacingTokens
    content_widths: ThemeContentWidthTokens
    borders: ThemeBorderTokens
    shadows: ThemeShadowTokens
    buttons: ThemeButtonTokens
    cards: ThemeCardTokens
    navigation: ThemeNavigationTokens
    cta: ThemeCtaTokens
    responsive: ThemeResponsiveTokens
    layout: ThemeLayoutTokens
    motion: ThemeMotionTokens


class ThemeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_key: str = Field(min_length=1, max_length=120)
    theme_name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    token_contract_version: int = Field(default=1, ge=1)
    design_tokens: ThemeDesignTokens
    created_by: str = Field(min_length=1, max_length=160)
    provenance_type: str = Field(min_length=1, max_length=40)
    provenance_notes: str = Field(min_length=1, max_length=2000)
    replaces_theme_id: int | None = None


class ThemeApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str = Field(min_length=1, max_length=160)


class ThemeRetirementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retired_by: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=2000)


class WebsiteThemeSelectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_id: int
    selected_by: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=2000)


class ThemeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    website_id: int
    business_id: int
    brand_id: int
    theme_key: str
    theme_name: str
    version: int
    token_contract_version: int
    design_tokens: ThemeDesignTokens
    token_hash_sha256: str
    description: str | None
    lifecycle_status: str
    approval_status: str
    created_by: str
    provenance_type: str
    provenance_notes: str
    approved_by: str | None
    approved_at: datetime | None
    retired_by: str | None
    retirement_rationale: str | None
    retired_at: datetime | None
    replaces_theme_id: int | None
    created_at: datetime
    updated_at: datetime


class WebsiteThemeSelectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    website_id: int
    theme_id: int
    version: int
    status: str
    selected_by: str
    rationale: str
    selected_at: datetime
    replaced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ThemeAccessibilityResult(BaseModel):
    valid: bool
    ratios: dict[str, float]
    failures: list[str]


class ResolvedWebsiteTheme(BaseModel):
    website_id: int
    theme: ThemeRead | None
    selection: WebsiteThemeSelectionRead | None
    effective_tokens: ThemeDesignTokens
    accessibility: ThemeAccessibilityResult
    fallback_used: bool
    fallback_reason: str | None
    source_identity: dict[str, str | int | bool | None]


class WebsiteThemeStateRead(BaseModel):
    website_id: int
    resolved: ResolvedWebsiteTheme
    active: WebsiteThemeSelectionRead | None
    history: list[WebsiteThemeSelectionRead]
