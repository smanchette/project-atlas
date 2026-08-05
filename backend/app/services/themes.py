from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.models import PageComposition, Theme, Website, WebsiteThemeSelection
from app.schemas.themes import (
    ResolvedWebsiteTheme,
    ThemeAccessibilityResult,
    ThemeCreate,
    ThemeDesignTokens,
    ThemeRead,
    WebsiteThemeSelectionRead,
    WebsiteThemeStateRead,
)


THEME_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
TOKEN_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_TOKEN_CONTRACT_VERSION = 1
THEME_PROVENANCE_TYPES = {
    "operator_configured",
    "company_original",
    "licensed",
    "third_party",
}


class ThemeError(ValueError):
    """Fail-closed Theme-domain error suitable for API and composition callers."""

    def __init__(self, message: str, *, status_code: int = 409, code: str = "theme_invalid"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _default_design_tokens() -> ThemeDesignTokens:
    return ThemeDesignTokens.model_validate(
        {
            "colors": {
                "primary": "#1F2937",
                "primary_foreground": "#FFFFFF",
                "secondary": "#374151",
                "secondary_foreground": "#FFFFFF",
                "accent": "#0F766E",
                "accent_foreground": "#FFFFFF",
                "neutral": "#4B5563",
                "neutral_foreground": "#FFFFFF",
                "background": "#FFFFFF",
                "surface": "#F3F4F6",
                "text": "#111827",
                "heading": "#0F172A",
                "success": "#166534",
                "success_foreground": "#FFFFFF",
                "warning": "#92400E",
                "warning_foreground": "#FFFFFF",
                "error": "#B91C1C",
                "error_foreground": "#FFFFFF",
                "focus": "#005FCC",
            },
            "typography": {
                "heading_family": "system-ui, sans-serif",
                "body_family": "system-ui, sans-serif",
                "heading_weight": 700,
                "body_weight": 400,
                "font_scale": {
                    "xs": 0.75,
                    "sm": 0.875,
                    "base": 1.0,
                    "lg": 1.125,
                    "xl": 1.25,
                    "xxl": 1.5,
                    "display": 2.25,
                },
                "line_height": {"heading": 1.2, "body": 1.6},
                "letter_spacing": {"heading": -0.02, "body": 0.0},
            },
            "spacing": {
                "scale": {
                    "zero": 0,
                    "xs": 0.25,
                    "sm": 0.5,
                    "md": 1.0,
                    "lg": 1.5,
                    "xl": 2.0,
                    "xxl": 3.0,
                },
                "section_spacing": {"mobile": 3.0, "tablet": 4.0, "desktop": 5.0},
            },
            "content_widths": {"narrow": 720, "content": 1120, "wide": 1440},
            "borders": {
                "widths": {"thin": 1, "medium": 2, "thick": 3},
                "radii": {"small": 4, "medium": 8, "large": 16, "pill": 9999},
            },
            "shadows": {
                "none": "none",
                "low": "0 1px 2px rgba(15, 23, 42, 0.12)",
                "medium": "0 4px 12px rgba(15, 23, 42, 0.16)",
                "high": "0 12px 28px rgba(15, 23, 42, 0.20)",
            },
            "buttons": {
                "background": "primary",
                "text": "primary_foreground",
                "border": "primary_foreground",
                "hover_background": "secondary",
                "focus": "primary_foreground",
                "border_width": "medium",
                "border_radius": "medium",
                "padding_inline": "lg",
                "padding_block": "sm",
                "min_height": 44,
                "font_weight": 700,
            },
            "cards": {
                "background": "surface",
                "text": "text",
                "border": "neutral",
                "border_width": "thin",
                "border_radius": "large",
                "shadow": "low",
                "padding": "lg",
            },
            "navigation": {
                "background": "primary",
                "text": "primary_foreground",
                "hover": "primary_foreground",
                "active": "primary_foreground",
                "focus": "primary_foreground",
                "item_spacing": "md",
                "min_target_size": 44,
            },
            "cta": {
                "background": "surface",
                "text": "heading",
                "button_background": "primary",
                "button_text": "primary_foreground",
                "focus": "focus",
                "border_radius": "large",
                "section_spacing": "xl",
                "min_target_size": 44,
            },
            "responsive": {
                "mobile_max": 767,
                "tablet_min": 768,
                "tablet_max": 1023,
                "desktop_min": 1024,
            },
            "layout": {
                "max_content_columns": 3,
                "content_alignment": "left",
                "mobile_stack": True,
                "gutter": "lg",
                "overflow_behavior": "wrap",
            },
            "motion": {
                "duration_fast_ms": 120,
                "duration_normal_ms": 200,
                "duration_slow_ms": 320,
                "easing": "ease-out",
                "reduced_motion": "disable_nonessential",
            },
        }
    )


DEFAULT_THEME_TOKENS = _default_design_tokens()


def canonical_token_hash(tokens: ThemeDesignTokens) -> str:
    canonical = json.dumps(
        tokens.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_theme_accessibility(tokens: ThemeDesignTokens) -> ThemeAccessibilityResult:
    colors = tokens.colors.model_dump()
    pairs: tuple[tuple[str, str, str, float], ...] = (
        ("body_text_on_background", "text", "background", 4.5),
        ("body_text_on_surface", "text", "surface", 4.5),
        ("heading_on_background", "heading", "background", 4.5),
        ("heading_on_surface", "heading", "surface", 4.5),
        ("primary_content", "primary_foreground", "primary", 4.5),
        ("secondary_content", "secondary_foreground", "secondary", 4.5),
        ("accent_content", "accent_foreground", "accent", 4.5),
        ("neutral_content", "neutral_foreground", "neutral", 4.5),
        ("success_content", "success_foreground", "success", 4.5),
        ("warning_content", "warning_foreground", "warning", 4.5),
        ("error_content", "error_foreground", "error", 4.5),
        ("button_text", tokens.buttons.text, tokens.buttons.background, 4.5),
        ("button_hover_text", tokens.buttons.text, tokens.buttons.hover_background, 4.5),
        ("button_boundary", tokens.buttons.background, "background", 3.0),
        ("button_focus", tokens.buttons.focus, tokens.buttons.background, 3.0),
        ("card_text", tokens.cards.text, tokens.cards.background, 4.5),
        ("card_boundary", tokens.cards.border, tokens.cards.background, 3.0),
        ("navigation_text", tokens.navigation.text, tokens.navigation.background, 4.5),
        ("navigation_hover", tokens.navigation.hover, tokens.navigation.background, 4.5),
        ("navigation_active", tokens.navigation.active, tokens.navigation.background, 4.5),
        ("navigation_focus", tokens.navigation.focus, tokens.navigation.background, 3.0),
        ("cta_text", tokens.cta.text, tokens.cta.background, 4.5),
        ("cta_button_text", tokens.cta.button_text, tokens.cta.button_background, 4.5),
        ("cta_button_boundary", tokens.cta.button_background, tokens.cta.background, 3.0),
        ("cta_focus", tokens.cta.focus, tokens.cta.background, 3.0),
        ("page_focus", "focus", "background", 3.0),
        ("surface_focus", "focus", "surface", 3.0),
    )
    ratios: dict[str, float] = {}
    failures: list[str] = []
    for label, foreground, background, threshold in pairs:
        ratio = round(_contrast_ratio(colors[foreground], colors[background]), 2)
        ratios[label] = ratio
        if ratio + 1e-9 < threshold:
            failures.append(f"{label} contrast {ratio:.2f}:1 is below {threshold:.1f}:1")
    return ThemeAccessibilityResult(valid=not failures, ratios=ratios, failures=failures)


def create_theme(session: Session, website_id: int, payload: ThemeCreate) -> Theme:
    website = _website(session, website_id)
    if website.brand_id is None:
        raise ThemeError("Website must select a Brand before creating a Theme.")
    key = payload.theme_key.strip().lower()
    if not THEME_KEY_PATTERN.fullmatch(key):
        raise ThemeError(
            "Theme key must contain only lowercase letters, numbers, hyphens, or underscores.",
            status_code=422,
            code="theme_key_invalid",
        )
    if payload.token_contract_version != SUPPORTED_TOKEN_CONTRACT_VERSION:
        raise ThemeError(
            f"Unsupported Theme token contract version: {payload.token_contract_version}.",
            status_code=422,
            code="theme_contract_unsupported",
        )
    provenance_type = payload.provenance_type.strip().lower()
    if provenance_type not in THEME_PROVENANCE_TYPES:
        raise ThemeError("Theme provenance type is unsupported.", status_code=422)
    created_by = _required(payload.created_by, "Theme creator")
    provenance_notes = _required(payload.provenance_notes, "Theme provenance notes")
    theme_name = _required(payload.theme_name, "Theme name")

    replacement: Theme | None = None
    version = 1
    latest = session.exec(
        select(Theme)
        .where(Theme.website_id == website_id, Theme.theme_key == key)
        .order_by(Theme.version.desc())
    ).first()
    if payload.replaces_theme_id is not None:
        replacement = session.get(Theme, payload.replaces_theme_id)
        if (
            not replacement
            or replacement.website_id != website_id
            or replacement.business_id != website.business_id
            or replacement.brand_id != website.brand_id
            or replacement.theme_key != key
        ):
            raise ThemeError("Theme replacement must reference the same Website, Brand, and theme key.", status_code=422)
        if not latest or latest.id != replacement.id:
            raise ThemeError("Theme replacement must reference the latest Theme version.")
        version = replacement.version + 1
    elif latest:
        raise ThemeError("Theme key already exists; create an explicit replacement version.")

    tokens = ThemeDesignTokens.model_validate(payload.design_tokens.model_dump(mode="json"))
    theme = Theme(
        website_id=website.id,
        business_id=website.business_id,
        brand_id=website.brand_id,
        theme_key=key,
        theme_name=theme_name,
        version=version,
        token_contract_version=SUPPORTED_TOKEN_CONTRACT_VERSION,
        design_tokens=tokens.model_dump(mode="json"),
        token_hash_sha256=canonical_token_hash(tokens),
        description=_optional(payload.description),
        lifecycle_status="draft",
        approval_status="pending_review",
        created_by=created_by,
        provenance_type=provenance_type,
        provenance_notes=provenance_notes,
        replaces_theme_id=replacement.id if replacement else None,
    )
    session.add(theme)
    session.commit()
    session.refresh(theme)
    return theme


def approve_theme(session: Session, theme_id: int, *, approved_by: str) -> Theme:
    theme = _theme(session, theme_id)
    approved_by = _required(approved_by, "Theme approval operator")
    if theme.lifecycle_status == "available" and theme.approval_status == "approved":
        if theme.approved_by != approved_by:
            raise ThemeError("Theme was already approved by a different operator.")
        tokens = _validate_theme_record(session, theme, require_approved=True)
        accessibility = validate_theme_accessibility(tokens)
        if not accessibility.valid:
            raise ThemeError("Approved Theme no longer passes accessibility validation.")
        return theme
    if theme.lifecycle_status != "draft" or theme.approval_status != "pending_review":
        raise ThemeError("Only a draft, pending-review Theme can be approved.")
    tokens = _validate_theme_record(session, theme, require_approved=False)
    accessibility = validate_theme_accessibility(tokens)
    if not accessibility.valid:
        raise ThemeError(
            "Theme approval failed accessibility validation: " + "; ".join(accessibility.failures),
            code="theme_accessibility_invalid",
        )
    later = session.exec(
        select(Theme).where(
            Theme.website_id == theme.website_id,
            Theme.theme_key == theme.theme_key,
            Theme.version > theme.version,
        )
    ).all()
    if any(item.approval_status == "approved" or item.approved_at is not None for item in later):
        raise ThemeError("A superseded Theme version cannot be approved.")
    now = datetime.now(UTC)
    theme.lifecycle_status = "available"
    theme.approval_status = "approved"
    theme.approved_by = approved_by
    theme.approved_at = now
    theme.updated_at = now
    session.add(theme)
    session.commit()
    session.refresh(theme)
    return theme


def retire_theme(session: Session, theme_id: int, *, retired_by: str, rationale: str) -> Theme:
    theme = _theme(session, theme_id)
    retired_by = _required(retired_by, "Theme retirement operator")
    rationale = _required(rationale, "Theme retirement rationale")
    if theme.lifecycle_status == "retired":
        if theme.retired_by == retired_by and theme.retirement_rationale == rationale:
            return theme
        raise ThemeError("Theme is already retired with different retirement provenance.")
    active = session.exec(
        select(WebsiteThemeSelection).where(
            WebsiteThemeSelection.theme_id == theme.id,
            WebsiteThemeSelection.status == "active",
        )
    ).first()
    if active:
        raise ThemeError("Replace the active Website Theme selection before retiring this Theme.")
    now = datetime.now(UTC)
    theme.lifecycle_status = "retired"
    theme.retired_by = retired_by
    theme.retirement_rationale = rationale
    theme.retired_at = now
    theme.updated_at = now
    session.add(theme)
    session.commit()
    session.refresh(theme)
    return theme


def select_website_theme(
    session: Session,
    website_id: int,
    *,
    theme_id: int,
    selected_by: str,
    rationale: str,
) -> WebsiteThemeSelection:
    website = _website(session, website_id)
    selected_by = _required(selected_by, "Theme selection operator")
    rationale = _required(rationale, "Theme selection rationale")
    theme = _theme(session, theme_id)
    if (
        theme.website_id != website.id
        or theme.business_id != website.business_id
        or website.brand_id is None
        or theme.brand_id != website.brand_id
    ):
        raise ThemeError("Theme does not belong to this Website's Business and Brand.", status_code=422)
    _validate_theme_record(session, theme, require_approved=True)
    current_rows = list(
        session.exec(
            select(WebsiteThemeSelection).where(
                WebsiteThemeSelection.website_id == website.id,
                WebsiteThemeSelection.status == "active",
            )
        ).all()
    )
    if len(current_rows) > 1:
        raise ThemeError("Website has multiple active Theme selections.")
    previous = current_rows[0] if current_rows else None
    if previous and previous.theme_id == theme.id:
        return previous
    latest = session.exec(
        select(WebsiteThemeSelection)
        .where(WebsiteThemeSelection.website_id == website.id)
        .order_by(WebsiteThemeSelection.version.desc())
    ).first()
    now = datetime.now(UTC)
    if previous:
        previous.status = "replaced"
        previous.replaced_at = now
        previous.updated_at = now
        session.add(previous)
    selection = WebsiteThemeSelection(
        website_id=website.id,
        theme_id=theme.id,
        version=(latest.version + 1) if latest else 1,
        status="active",
        selected_by=selected_by,
        rationale=rationale,
        selected_at=now,
    )
    session.add(selection)
    for composition in session.exec(
        select(PageComposition).where(PageComposition.website_id == website.id)
    ).all():
        composition.status = "stale"
        composition.updated_at = now
        session.add(composition)
    session.commit()
    session.refresh(selection)
    return selection


def list_website_themes(session: Session, website_id: int) -> list[Theme]:
    _website(session, website_id)
    return list(
        session.exec(
            select(Theme)
            .where(Theme.website_id == website_id)
            .order_by(Theme.theme_key, Theme.version.desc())
        ).all()
    )


def resolve_website_theme(session: Session, website_id: int) -> ResolvedWebsiteTheme:
    website = _website(session, website_id)
    active_rows = list(
        session.exec(
            select(WebsiteThemeSelection).where(
                WebsiteThemeSelection.website_id == website.id,
                WebsiteThemeSelection.status == "active",
            )
        ).all()
    )
    if len(active_rows) > 1:
        raise ThemeError("Website has multiple active Theme selections.")
    if not active_rows:
        accessibility = validate_theme_accessibility(DEFAULT_THEME_TOKENS)
        token_hash = canonical_token_hash(DEFAULT_THEME_TOKENS)
        return ResolvedWebsiteTheme(
            website_id=website.id,
            theme=None,
            selection=None,
            effective_tokens=DEFAULT_THEME_TOKENS,
            accessibility=accessibility,
            fallback_used=True,
            fallback_reason="No approved Theme is selected; Atlas neutral presentation is active.",
            source_identity={
                "mode": "neutral_fallback",
                "website_id": website.id,
                "theme_id": None,
                "theme_key": "atlas-neutral",
                "theme_version": 1,
                "token_contract_version": SUPPORTED_TOKEN_CONTRACT_VERSION,
                "token_hash_sha256": token_hash,
                "selection_id": None,
                "selection_version": None,
            },
        )
    selection = active_rows[0]
    theme = session.get(Theme, selection.theme_id)
    if not theme:
        raise ThemeError("Active Theme selection references a missing Theme.")
    if theme.website_id != website.id or theme.business_id != website.business_id or theme.brand_id != website.brand_id:
        raise ThemeError("Active Theme selection crosses a Website, Business, or Brand boundary.")
    tokens = _validate_theme_record(session, theme, require_approved=True)
    accessibility = validate_theme_accessibility(tokens)
    if not accessibility.valid:
        raise ThemeError("Selected Theme fails accessibility validation.")
    return ResolvedWebsiteTheme(
        website_id=website.id,
        theme=ThemeRead.model_validate(theme),
        selection=WebsiteThemeSelectionRead.model_validate(selection),
        effective_tokens=tokens,
        accessibility=accessibility,
        fallback_used=False,
        fallback_reason=None,
        source_identity={
            "mode": "selected",
            "website_id": website.id,
            "theme_id": theme.id,
            "theme_key": theme.theme_key,
            "theme_version": theme.version,
            "token_contract_version": theme.token_contract_version,
            "token_hash_sha256": theme.token_hash_sha256,
            "selection_id": selection.id,
            "selection_version": selection.version,
        },
    )


def read_website_theme_state(session: Session, website_id: int) -> WebsiteThemeStateRead:
    resolved = resolve_website_theme(session, website_id)
    rows = list(
        session.exec(
            select(WebsiteThemeSelection)
            .where(WebsiteThemeSelection.website_id == website_id)
            .order_by(WebsiteThemeSelection.version.desc())
        ).all()
    )
    history = [WebsiteThemeSelectionRead.model_validate(item) for item in rows]
    active = next((item for item in history if item.status == "active"), None)
    return WebsiteThemeStateRead(
        website_id=website_id,
        resolved=resolved,
        active=active,
        history=history,
    )


def _validate_theme_record(
    session: Session,
    theme: Theme,
    *,
    require_approved: bool,
) -> ThemeDesignTokens:
    website = session.get(Website, theme.website_id)
    if (
        not website
        or website.business_id != theme.business_id
        or website.brand_id is None
        or website.brand_id != theme.brand_id
    ):
        raise ThemeError("Theme ownership is invalid.")
    if not THEME_KEY_PATTERN.fullmatch(theme.theme_key):
        raise ThemeError("Theme key is invalid.")
    if theme.version < 1 or theme.token_contract_version != SUPPORTED_TOKEN_CONTRACT_VERSION:
        raise ThemeError("Theme version or token contract is unsupported.")
    if theme.provenance_type not in THEME_PROVENANCE_TYPES or not theme.provenance_notes.strip():
        raise ThemeError("Theme provenance is invalid.")
    if not theme.created_by.strip() or not theme.theme_name.strip():
        raise ThemeError("Theme operator provenance or identity is invalid.")
    if theme.replaces_theme_id is None:
        if theme.version != 1:
            raise ThemeError("Theme replacement chain is invalid.")
    else:
        replaced = session.get(Theme, theme.replaces_theme_id)
        if (
            not replaced
            or replaced.website_id != theme.website_id
            or replaced.business_id != theme.business_id
            or replaced.brand_id != theme.brand_id
            or replaced.theme_key != theme.theme_key
            or theme.version != replaced.version + 1
        ):
            raise ThemeError("Theme replacement chain is invalid.")
    try:
        tokens = ThemeDesignTokens.model_validate(theme.design_tokens)
    except Exception as exc:
        raise ThemeError("Theme design-token contract is invalid.") from exc
    observed_hash = canonical_token_hash(tokens)
    if not TOKEN_HASH_PATTERN.fullmatch(theme.token_hash_sha256) or observed_hash != theme.token_hash_sha256:
        raise ThemeError("Theme token hash does not match the governed token contract.")
    if require_approved and (
        theme.approval_status != "approved"
        or theme.lifecycle_status != "available"
        or not theme.approved_by
        or theme.approved_at is None
    ):
        raise ThemeError("Website may select only an approved, available Theme.")
    return tokens


def _theme(session: Session, theme_id: int) -> Theme:
    theme = session.get(Theme, theme_id)
    if not theme:
        raise ThemeError("Theme not found.", status_code=404, code="theme_not_found")
    return theme


def _website(session: Session, website_id: int) -> Website:
    website = session.get(Website, website_id)
    if not website:
        raise ThemeError("Website not found.", status_code=404, code="website_not_found")
    return website


def _required(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ThemeError(f"{label} is required.", status_code=422)
    return cleaned


def _optional(value: str | None) -> str | None:
    cleaned = value.strip() if value else ""
    return cleaned or None


def _contrast_ratio(first: str, second: str) -> float:
    high, low = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _relative_luminance(value: str) -> float:
    channels = [int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)]

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else math.pow((channel + 0.055) / 1.055, 2.4)

    red, green, blue = (linear(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue
