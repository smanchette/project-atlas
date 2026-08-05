import type { CSSProperties } from "react";

import type {
  ResolvedWebsiteTheme,
  ThemeColorTokenName,
  ThemeDesignTokens,
  ThemeSpacingTokenName,
} from "../types";

type ThemeCssProperties = CSSProperties & Record<`--atlas-${string}`, string | number>;

export type ThemePresentation = {
  style: ThemeCssProperties;
  attributes: {
    "data-atlas-theme-mode": "selected" | "neutral_fallback";
    "data-atlas-theme-key": string;
    "data-atlas-theme-version": string;
    "data-atlas-theme-token-hash": string;
    "data-atlas-reduced-motion": string;
    "data-atlas-theme-viewport": "mobile" | "tablet" | "desktop";
    "data-atlas-content-alignment": "left" | "center";
    "data-atlas-mobile-stack": "true" | "false";
    "data-atlas-overflow-behavior": "wrap" | "scroll_explicit";
  };
};

const colorNames: ThemeColorTokenName[] = [
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
];

const spacingNames: ThemeSpacingTokenName[] = [
  "zero",
  "xs",
  "sm",
  "md",
  "lg",
  "xl",
  "xxl",
];

/**
 * The only frontend adapter between Atlas semantic components and a governed Theme.
 * It projects approved tokens into CSS custom properties; it owns no business facts,
 * page-type logic, component selection, or Theme defaults.
 */
export function themePresentation(
  resolved: ResolvedWebsiteTheme,
  websiteId: number,
  viewportWidth: number,
): ThemePresentation {
  const validationError = themeValidationError(resolved, websiteId);
  if (validationError) throw new Error(validationError);
  const identity = resolved.source_identity;
  return {
    style: designTokenCssVariables(resolved.effective_tokens),
    attributes: {
      "data-atlas-theme-mode": resolved.fallback_used ? "neutral_fallback" : "selected",
      "data-atlas-theme-key": String(identity.theme_key),
      "data-atlas-theme-version": String(identity.theme_version),
      "data-atlas-theme-token-hash": String(identity.token_hash_sha256),
      "data-atlas-reduced-motion": resolved.effective_tokens.motion.reduced_motion,
      "data-atlas-theme-viewport": themeViewport(
        resolved.effective_tokens,
        viewportWidth,
      ),
      "data-atlas-content-alignment": resolved.effective_tokens.layout.content_alignment,
      "data-atlas-mobile-stack": String(
        resolved.effective_tokens.layout.mobile_stack,
      ) as "true" | "false",
      "data-atlas-overflow-behavior": resolved.effective_tokens.layout.overflow_behavior,
    },
  };
}

export function themeViewport(
  tokens: ThemeDesignTokens,
  viewportWidth: number,
): "mobile" | "tablet" | "desktop" {
  if (!Number.isFinite(viewportWidth) || viewportWidth <= 0) {
    throw new Error("Theme viewport width must be a positive finite number.");
  }
  if (viewportWidth <= tokens.responsive.mobile_max) return "mobile";
  if (
    viewportWidth >= tokens.responsive.tablet_min &&
    viewportWidth <= tokens.responsive.tablet_max
  ) {
    return "tablet";
  }
  if (viewportWidth >= tokens.responsive.desktop_min) return "desktop";
  throw new Error("Theme responsive breakpoints do not classify the viewport.");
}

export function themeValidationError(
  resolved: ResolvedWebsiteTheme | null | undefined,
  websiteId: number,
): string | null {
  if (!resolved || typeof resolved !== "object") {
    return "The semantic composition has no authoritative Theme resolution.";
  }
  if (resolved.website_id !== websiteId) {
    return "The resolved Theme crosses the Website ownership boundary.";
  }
  if (!resolved.accessibility?.valid || resolved.accessibility.failures.length) {
    return "The resolved Theme does not satisfy its accessibility contract.";
  }
  try {
    designTokenCssVariables(resolved.effective_tokens);
  } catch (value) {
    return value instanceof Error
      ? `The resolved Theme token contract is invalid: ${value.message}`
      : "The resolved Theme token contract is invalid.";
  }
  const accessibility = themeAccessibilityAudit(resolved.effective_tokens);
  if (accessibility.failures.length) {
    return `The resolved Theme accessibility evidence conflicts with its effective tokens: ${accessibility.failures.join("; ")}`;
  }
  for (const [key, ratio] of Object.entries(accessibility.ratios)) {
    const recorded = resolved.accessibility.ratios[key];
    if (!Number.isFinite(recorded) || Math.abs(recorded - ratio) > 0.01) {
      return `The resolved Theme accessibility evidence does not match the effective token pair ${key}.`;
    }
  }

  const identity = resolved.source_identity;
  if (!identity || identity.website_id !== websiteId) {
    return "The Theme source identity does not match this Website.";
  }
  if (!isSha256(identity.token_hash_sha256)) {
    return "The Theme source identity has no valid token checksum.";
  }
  if (identity.token_contract_version !== 1) {
    return "The Theme token contract version is unsupported.";
  }

  if (resolved.fallback_used) {
    if (
      identity.mode !== "neutral_fallback" ||
      identity.theme_id !== null ||
      identity.selection_id !== null ||
      resolved.theme != null ||
      resolved.selection != null ||
      !resolved.fallback_reason?.trim()
    ) {
      return "The neutral Theme fallback identity is ambiguous.";
    }
    return null;
  }

  const theme = resolved.theme;
  const selection = resolved.selection;
  if (!theme || !selection) {
    return "The selected Theme is missing its governed Theme or selection record.";
  }
  if (
    identity.mode !== "selected" ||
    theme.website_id !== websiteId ||
    selection.website_id !== websiteId ||
    selection.theme_id !== theme.id ||
    selection.status !== "active" ||
    theme.lifecycle_status !== "available" ||
    theme.approval_status !== "approved"
  ) {
    return "The selected Theme is not an active approved Website-owned version.";
  }
  if (
    identity.theme_id !== theme.id ||
    identity.theme_key !== theme.theme_key ||
    identity.theme_version !== theme.version ||
    identity.token_contract_version !== theme.token_contract_version ||
    identity.token_hash_sha256 !== theme.token_hash_sha256 ||
    identity.selection_id !== selection.id ||
    identity.selection_version !== selection.version
  ) {
    return "The Theme source identity does not match the governed selection.";
  }
  return null;
}

export function designTokenCssVariables(tokens: ThemeDesignTokens): ThemeCssProperties {
  validateTokenShape(tokens);
  const style = {} as ThemeCssProperties;
  for (const name of colorNames) style[`--atlas-color-${dash(name)}`] = tokens.colors[name];
  style["--atlas-font-heading"] = tokens.typography.heading_family;
  style["--atlas-font-body"] = tokens.typography.body_family;
  style["--atlas-font-weight-heading"] = tokens.typography.heading_weight;
  style["--atlas-font-weight-body"] = tokens.typography.body_weight;
  for (const [name, value] of Object.entries(tokens.typography.font_scale)) {
    style[`--atlas-font-size-${dash(name)}`] = `${value}rem`;
  }
  style["--atlas-line-height-heading"] = tokens.typography.line_height.heading;
  style["--atlas-line-height-body"] = tokens.typography.line_height.body;
  style["--atlas-letter-spacing-heading"] = `${tokens.typography.letter_spacing.heading}em`;
  style["--atlas-letter-spacing-body"] = `${tokens.typography.letter_spacing.body}em`;
  for (const name of spacingNames) style[`--atlas-space-${name}`] = `${tokens.spacing.scale[name]}rem`;
  for (const [name, value] of Object.entries(tokens.spacing.section_spacing)) {
    style[`--atlas-section-space-${dash(name)}`] = `${value}rem`;
  }
  for (const [name, value] of Object.entries(tokens.content_widths)) {
    style[`--atlas-content-width-${dash(name)}`] = `${value}px`;
  }
  for (const [name, value] of Object.entries(tokens.borders.widths)) {
    style[`--atlas-border-${dash(name)}`] = `${value}px`;
  }
  for (const [name, value] of Object.entries(tokens.borders.radii)) {
    style[`--atlas-radius-${dash(name)}`] = `${value}px`;
  }
  for (const [name, value] of Object.entries(tokens.shadows)) {
    style[`--atlas-shadow-${dash(name)}`] = value;
  }

  style["--atlas-button-background"] = tokens.colors[tokens.buttons.background];
  style["--atlas-button-text"] = tokens.colors[tokens.buttons.text];
  style["--atlas-button-border"] = tokens.colors[tokens.buttons.border];
  style["--atlas-button-hover"] = tokens.colors[tokens.buttons.hover_background];
  style["--atlas-button-focus"] = tokens.colors[tokens.buttons.focus];
  style["--atlas-button-border-width"] = `${tokens.borders.widths[tokens.buttons.border_width]}px`;
  style["--atlas-button-radius"] = `${tokens.borders.radii[tokens.buttons.border_radius]}px`;
  style["--atlas-button-padding-inline"] = `${tokens.spacing.scale[tokens.buttons.padding_inline]}rem`;
  style["--atlas-button-padding-block"] = `${tokens.spacing.scale[tokens.buttons.padding_block]}rem`;
  style["--atlas-button-min-height"] = `${tokens.buttons.min_height}px`;
  style["--atlas-button-font-weight"] = tokens.buttons.font_weight;

  style["--atlas-card-background"] = tokens.colors[tokens.cards.background];
  style["--atlas-card-text"] = tokens.colors[tokens.cards.text];
  style["--atlas-card-border"] = tokens.colors[tokens.cards.border];
  style["--atlas-card-border-width"] = `${tokens.borders.widths[tokens.cards.border_width]}px`;
  style["--atlas-card-radius"] = `${tokens.borders.radii[tokens.cards.border_radius]}px`;
  style["--atlas-card-shadow"] = tokens.shadows[tokens.cards.shadow];
  style["--atlas-card-padding"] = `${tokens.spacing.scale[tokens.cards.padding]}rem`;

  style["--atlas-nav-background"] = tokens.colors[tokens.navigation.background];
  style["--atlas-nav-text"] = tokens.colors[tokens.navigation.text];
  style["--atlas-nav-hover"] = tokens.colors[tokens.navigation.hover];
  style["--atlas-nav-active"] = tokens.colors[tokens.navigation.active];
  style["--atlas-nav-focus"] = tokens.colors[tokens.navigation.focus];
  style["--atlas-nav-item-spacing"] = `${tokens.spacing.scale[tokens.navigation.item_spacing]}rem`;
  style["--atlas-nav-min-target"] = `${tokens.navigation.min_target_size}px`;

  style["--atlas-cta-background"] = tokens.colors[tokens.cta.background];
  style["--atlas-cta-text"] = tokens.colors[tokens.cta.text];
  style["--atlas-cta-button-background"] = tokens.colors[tokens.cta.button_background];
  style["--atlas-cta-button-text"] = tokens.colors[tokens.cta.button_text];
  style["--atlas-cta-focus"] = tokens.colors[tokens.cta.focus];
  style["--atlas-cta-radius"] = `${tokens.borders.radii[tokens.cta.border_radius]}px`;
  style["--atlas-cta-section-spacing"] = `${tokens.spacing.scale[tokens.cta.section_spacing]}rem`;
  style["--atlas-cta-min-target"] = `${tokens.cta.min_target_size}px`;

  style["--atlas-breakpoint-mobile-max"] = `${tokens.responsive.mobile_max}px`;
  style["--atlas-breakpoint-tablet-min"] = `${tokens.responsive.tablet_min}px`;
  style["--atlas-breakpoint-tablet-max"] = `${tokens.responsive.tablet_max}px`;
  style["--atlas-breakpoint-desktop-min"] = `${tokens.responsive.desktop_min}px`;
  style["--atlas-layout-max-columns"] = tokens.layout.max_content_columns;
  style["--atlas-layout-alignment"] = tokens.layout.content_alignment;
  style["--atlas-layout-gutter"] = `${tokens.spacing.scale[tokens.layout.gutter]}rem`;
  style["--atlas-motion-fast"] = `${tokens.motion.duration_fast_ms}ms`;
  style["--atlas-motion-normal"] = `${tokens.motion.duration_normal_ms}ms`;
  style["--atlas-motion-slow"] = `${tokens.motion.duration_slow_ms}ms`;
  style["--atlas-motion-easing"] = tokens.motion.easing;
  return style;
}

function validateTokenShape(tokens: ThemeDesignTokens) {
  if (!tokens || typeof tokens !== "object") throw new Error("tokens must be an object");
  for (const name of colorNames) {
    if (!/^#[0-9A-Fa-f]{6}$/.test(tokens.colors?.[name])) {
      throw new Error(`colors.${name} must be a six-digit hexadecimal color`);
    }
  }
  if (!/^[A-Za-z0-9 ,.'"-]{1,240}$/.test(tokens.typography?.heading_family ?? "")) {
    throw new Error("typography.heading_family is unsafe");
  }
  if (!/^[A-Za-z0-9 ,.'"-]{1,240}$/.test(tokens.typography?.body_family ?? "")) {
    throw new Error("typography.body_family is unsafe");
  }
  assertFiniteRecord(tokens.typography.font_scale, "typography.font_scale");
  assertFiniteRecord(tokens.typography.line_height, "typography.line_height");
  assertFiniteRecord(tokens.typography.letter_spacing, "typography.letter_spacing");
  assertFiniteRecord(tokens.spacing.scale, "spacing.scale");
  assertFiniteRecord(tokens.spacing.section_spacing, "spacing.section_spacing");
  assertFiniteRecord(tokens.content_widths, "content_widths");
  assertFiniteRecord(tokens.borders.widths, "borders.widths");
  assertFiniteRecord(tokens.borders.radii, "borders.radii");
  assertFiniteRecord(tokens.responsive, "responsive");
  for (const [name, value] of Object.entries(tokens.shadows)) {
    if (
      typeof value !== "string" ||
      !value.trim() ||
      /(?:url\(|expression\(|javascript:|;)/i.test(value)
    ) {
      throw new Error(`shadows.${name} is unsafe`);
    }
  }
  if (!/^(?:linear|ease|ease-in|ease-out|ease-in-out|cubic-bezier\([0-9., -]+\))$/.test(tokens.motion.easing)) {
    throw new Error("motion.easing is unsafe");
  }
  for (const value of [
    tokens.typography.heading_weight,
    tokens.typography.body_weight,
    tokens.buttons.min_height,
    tokens.buttons.font_weight,
    tokens.navigation.min_target_size,
    tokens.cta.min_target_size,
    tokens.layout.max_content_columns,
    tokens.motion.duration_fast_ms,
    tokens.motion.duration_normal_ms,
    tokens.motion.duration_slow_ms,
  ]) {
    if (!Number.isFinite(value)) throw new Error("numeric token values must be finite");
  }
}

export function themeAccessibilityAudit(tokens: ThemeDesignTokens): {
  ratios: Record<string, number>;
  failures: string[];
} {
  const pairs: Array<[string, ThemeColorTokenName, ThemeColorTokenName, number]> = [
    ["body_text_on_background", "text", "background", 4.5],
    ["body_text_on_surface", "text", "surface", 4.5],
    ["heading_on_background", "heading", "background", 4.5],
    ["heading_on_surface", "heading", "surface", 4.5],
    ["primary_content", "primary_foreground", "primary", 4.5],
    ["secondary_content", "secondary_foreground", "secondary", 4.5],
    ["accent_content", "accent_foreground", "accent", 4.5],
    ["neutral_content", "neutral_foreground", "neutral", 4.5],
    ["success_content", "success_foreground", "success", 4.5],
    ["warning_content", "warning_foreground", "warning", 4.5],
    ["error_content", "error_foreground", "error", 4.5],
    ["button_text", tokens.buttons.text, tokens.buttons.background, 4.5],
    ["button_hover_text", tokens.buttons.text, tokens.buttons.hover_background, 4.5],
    ["button_boundary", tokens.buttons.background, "background", 3],
    ["button_focus", tokens.buttons.focus, tokens.buttons.background, 3],
    ["card_text", tokens.cards.text, tokens.cards.background, 4.5],
    ["card_boundary", tokens.cards.border, tokens.cards.background, 3],
    ["navigation_text", tokens.navigation.text, tokens.navigation.background, 4.5],
    ["navigation_hover", tokens.navigation.hover, tokens.navigation.background, 4.5],
    ["navigation_active", tokens.navigation.active, tokens.navigation.background, 4.5],
    ["navigation_focus", tokens.navigation.focus, tokens.navigation.background, 3],
    ["cta_text", tokens.cta.text, tokens.cta.background, 4.5],
    ["cta_button_text", tokens.cta.button_text, tokens.cta.button_background, 4.5],
    ["cta_button_boundary", tokens.cta.button_background, tokens.cta.background, 3],
    ["cta_focus", tokens.cta.focus, tokens.cta.background, 3],
    ["page_focus", "focus", "background", 3],
    ["surface_focus", "focus", "surface", 3],
  ];
  const ratios: Record<string, number> = {};
  const failures: string[] = [];
  for (const [label, foreground, background, threshold] of pairs) {
    const ratio = Math.round(
      contrastRatio(tokens.colors[foreground], tokens.colors[background]) * 100,
    ) / 100;
    ratios[label] = ratio;
    if (ratio + 1e-9 < threshold) {
      failures.push(`${label} contrast ${ratio.toFixed(2)}:1 is below ${threshold.toFixed(1)}:1`);
    }
  }
  return { ratios, failures };
}

function contrastRatio(left: string, right: string) {
  const high = Math.max(relativeLuminance(left), relativeLuminance(right));
  const low = Math.min(relativeLuminance(left), relativeLuminance(right));
  return (high + 0.05) / (low + 0.05);
}

function relativeLuminance(value: string) {
  const channels = [1, 3, 5].map((start) => parseInt(value.slice(start, start + 2), 16) / 255);
  const [red, green, blue] = channels.map((channel) =>
    channel <= 0.04045
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function assertFiniteRecord(value: Record<string, number>, path: string) {
  if (!value || typeof value !== "object") throw new Error(`${path} must be an object`);
  if (Object.values(value).some((item) => !Number.isFinite(item))) {
    throw new Error(`${path} values must be finite`);
  }
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/i.test(value);
}

function dash(value: string) {
  return value.replace(/_/g, "-");
}
