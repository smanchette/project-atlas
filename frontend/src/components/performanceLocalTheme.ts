export type ThemeFamilyLifecycleStatus = "preview_candidate" | "internal_diagnostic";
export const PERFORMANCE_LOCAL_THEME_VERSION = 2 as const;
export const PERFORMANCE_LOCAL_THEME_COMPATIBILITY = "performance-local@2" as const;
export type PerformanceLocalViewport = "mobile" | "tablet" | "desktop";
export type PerformanceLocalVisibility = {
  desktop: boolean;
  tablet: boolean;
  mobile: boolean;
};

export type PerformanceLocalComponentKey =
  | "site_header"
  | "desktop_dropdown_navigation"
  | "mobile_navigation_drawer"
  | "campaign_banner"
  | "hero_conversion_section"
  | "trust_proof_strip"
  | "service_or_related_card_grid"
  | "split_media_text_section"
  | "visual_cta_band"
  | "compact_estimate_form"
  | "trust_feature_cards"
  | "authority_content_section"
  | "numbered_process_steps"
  | "faq_accordion"
  | "sticky_mobile_action_bar"
  | "site_footer"
  | "back_to_top_control"
  | "review_badge_group"
  | "statistics_counter_band"
  | "video_embed_section"
  | "map_or_service_area_section"
  | "community_program_section"
  | "language_selector";

export type ThemeFamilyComponentContract = {
  key: PerformanceLocalComponentKey;
  version: typeof PERFORMANCE_LOCAL_THEME_VERSION;
  optional: boolean;
  defaultEnabled: boolean;
  scope: "website_with_optional_page_override";
  supportsPageOverride: true;
  placement: string;
  variant: string;
  visibility: PerformanceLocalVisibility;
  themeCompatibility: readonly [typeof PERFORMANCE_LOCAL_THEME_COMPATIBILITY];
  contentSource: "governed_semantic_composition" | "approved_runtime_configuration";
  supportsCtaLabel: true;
  supportsCtaDestination: true;
  accessibilityLabelRequired: true;
  requiredConfiguration: readonly string[];
  diagnosticLabel: string;
};

export type SerializedThemeFamilyComponentContract = Readonly<{
  component_key: PerformanceLocalComponentKey;
  contract_version: typeof PERFORMANCE_LOCAL_THEME_VERSION;
  optional: boolean;
  default_enabled: boolean;
  scope: "website_with_optional_page_override";
  supports_page_override: true;
  placement: string;
  variant: string;
  responsive_visibility: PerformanceLocalVisibility;
  theme_compatibility: readonly [typeof PERFORMANCE_LOCAL_THEME_COMPATIBILITY];
  content_source: ThemeFamilyComponentContract["contentSource"];
  required_configuration: readonly string[];
  supports_cta_label: true;
  supports_cta_destination: true;
  accessibility_label_required: boolean;
  diagnostic_label: string;
}>;

export type ThemeFamilyDefinition = {
  key: string;
  displayName: string;
  version: 1 | typeof PERFORMANCE_LOCAL_THEME_VERSION;
  status: ThemeFamilyLifecycleStatus;
  websiteIndependent: true;
  productionReady: boolean;
  compatibilityIdentity: string;
  designContract: {
    typography: Readonly<Record<string, string>>;
    spacing: Readonly<Record<string, string>>;
    contentWidths: Readonly<Record<string, string>>;
    colors: Readonly<Record<string, string>>;
    bordersAndRadii: Readonly<Record<string, string>>;
    shadows: Readonly<Record<string, string>>;
    buttonVariants: readonly string[];
    cardVariants: readonly string[];
    sectionVariants: readonly string[];
    imageTreatments: readonly string[];
    headerVariant: string;
    navigationVariant: string;
    heroVariant: string;
    footerVariant: string;
    responsiveBreakpoints: Readonly<Record<PerformanceLocalViewport, string>>;
    accessibilityContract: readonly string[];
  };
  supportedComponents: readonly ThemeFamilyComponentContract[];
  previewMetadata: {
    localOnly: true;
    persistsSelection: false;
    mutatesSource: false;
    description: string;
  };
};

const EVERY_VIEWPORT: PerformanceLocalVisibility = Object.freeze({
  desktop: true,
  tablet: true,
  mobile: true,
});

function componentContract(
  key: PerformanceLocalComponentKey,
  options: {
    optional?: boolean;
    defaultEnabled?: boolean;
    placement: string;
    variant: string;
    visibility?: PerformanceLocalVisibility;
    contentSource?: ThemeFamilyComponentContract["contentSource"];
    requiredConfiguration?: readonly string[];
    diagnosticLabel: string;
  },
): ThemeFamilyComponentContract {
  const requiredConfiguration = options.optional
    ? [
        "enabled",
        "websiteId",
        "themeCompatibility",
        "placement",
        "variant",
        "visibility",
        "contentSource",
        "accessibilityLabel",
        ...(options.requiredConfiguration ?? []),
      ]
    : [...(options.requiredConfiguration ?? [])];
  return Object.freeze({
    key,
    version: PERFORMANCE_LOCAL_THEME_VERSION,
    optional: options.optional ?? false,
    defaultEnabled: options.defaultEnabled ?? true,
    scope: "website_with_optional_page_override",
    supportsPageOverride: true,
    placement: options.placement,
    variant: options.variant,
    visibility: Object.freeze(options.visibility ?? EVERY_VIEWPORT),
    themeCompatibility: Object.freeze([PERFORMANCE_LOCAL_THEME_COMPATIBILITY] as const),
    contentSource: options.contentSource ?? "governed_semantic_composition",
    supportsCtaLabel: true,
    supportsCtaDestination: true,
    accessibilityLabelRequired: true,
    requiredConfiguration: Object.freeze([...new Set(requiredConfiguration)]),
    diagnosticLabel: options.diagnosticLabel,
  });
}

export const PERFORMANCE_LOCAL_COMPONENT_CONTRACTS = Object.freeze([
  componentContract("site_header", { placement: "header", variant: "compact_sticky", diagnosticLabel: "Compact governed site header" }),
  componentContract("desktop_dropdown_navigation", { placement: "header_navigation", variant: "intentional_dropdown", visibility: { desktop: true, tablet: false, mobile: false }, diagnosticLabel: "Collapsed desktop navigation groups" }),
  componentContract("mobile_navigation_drawer", { placement: "header_navigation", variant: "modal_drawer", visibility: { desktop: false, tablet: true, mobile: true }, diagnosticLabel: "Collapsed mobile navigation drawer" }),
  componentContract("campaign_banner", { optional: true, defaultEnabled: false, placement: "before_header", variant: "single_safe_strip", contentSource: "approved_runtime_configuration", requiredConfiguration: ["intent", "campaignLabel", "ctaLabel", "ctaDestination", "approvalIdentity"], diagnosticLabel: "Approved evergreen or time-bounded conversion banner" }),
  componentContract("hero_conversion_section", { placement: "main_start", variant: "visual_conversion", diagnosticLabel: "Governed visual conversion hero" }),
  componentContract("trust_proof_strip", { optional: true, placement: "after_hero", variant: "approved_facts_only", requiredConfiguration: ["sourceIdentity", "approvalIdentity"], diagnosticLabel: "Approved credential proof" }),
  componentContract("service_or_related_card_grid", { placement: "main", variant: "responsive_cards", diagnosticLabel: "Governed related destinations" }),
  componentContract("split_media_text_section", { placement: "main", variant: "alternating_contain", diagnosticLabel: "Exact-target media and approved copy" }),
  componentContract("visual_cta_band", { optional: true, placement: "before_footer", variant: "high_contrast", requiredConfiguration: ["sourceIdentity", "ctaLabel", "ctaDestination"], diagnosticLabel: "Governed final conversion section" }),
  componentContract("compact_estimate_form", { optional: true, placement: "visual_cta_band", variant: "preview_inert", contentSource: "approved_runtime_configuration", requiredConfiguration: ["previewOnly"], diagnosticLabel: "Inert local preview form" }),
  componentContract("trust_feature_cards", { optional: true, placement: "after_hero", variant: "approved_facts_only", requiredConfiguration: ["sourceIdentity", "approvalIdentity"], diagnosticLabel: "Approved trust facts" }),
  componentContract("authority_content_section", { placement: "main", variant: "readable_measure", diagnosticLabel: "Approved authority content" }),
  componentContract("numbered_process_steps", { placement: "main", variant: "source_preserving_sequence", diagnosticLabel: "Approved process content" }),
  componentContract("faq_accordion", { placement: "main", variant: "native_disclosure", diagnosticLabel: "Accessible FAQ disclosures" }),
  componentContract("sticky_mobile_action_bar", { optional: true, placement: "viewport_bottom", variant: "safe_area_single_layer", visibility: { desktop: false, tablet: false, mobile: true }, requiredConfiguration: ["sourceIdentity", "actionLabel", "phoneOrEstimateDestination"], diagnosticLabel: "Mobile conversion actions" }),
  componentContract("site_footer", { placement: "footer", variant: "structured", diagnosticLabel: "Governed site footer" }),
  componentContract("back_to_top_control", { placement: "viewport_edge", variant: "accessible_control", diagnosticLabel: "Back-to-top control" }),
  componentContract("review_badge_group", { optional: true, defaultEnabled: false, placement: "main", variant: "verified_only", contentSource: "approved_runtime_configuration", requiredConfiguration: ["provider", "rating", "reviewCount", "ratingApprovalStatus", "reviewCountApprovalStatus", "verificationDate", "destination", "trademarkUseAuthorization", "approvalIdentity"], diagnosticLabel: "Verified review or badge evidence" }),
  componentContract("statistics_counter_band", { optional: true, defaultEnabled: false, placement: "main", variant: "sourced_metrics", contentSource: "approved_runtime_configuration", requiredConfiguration: ["metricLabel", "value", "source", "effectiveDate", "approvalIdentity"], diagnosticLabel: "Approved sourced statistics" }),
  componentContract("video_embed_section", { optional: true, defaultEnabled: false, placement: "main", variant: "privacy_gated", contentSource: "approved_runtime_configuration", requiredConfiguration: ["approvedProvider", "approvedUrlOrMediaIdentity", "title", "accessibilityText", "privacyMode", "approvalIdentity"], diagnosticLabel: "Approved privacy-aware video" }),
  componentContract("map_or_service_area_section", { optional: true, defaultEnabled: false, placement: "main", variant: "accurate_location", contentSource: "approved_runtime_configuration", requiredConfiguration: ["approvedLocationOrServiceArea", "approvedProvider", "externalRequestConsent", "locationStatus", "storefrontStatus", "approvalIdentity"], diagnosticLabel: "Approved location or service area" }),
  componentContract("community_program_section", { optional: true, defaultEnabled: false, placement: "main", variant: "approved_program", contentSource: "approved_runtime_configuration", requiredConfiguration: ["approvedProgramIdentity", "approvedCopy", "destination", "effectiveStartDate", "effectiveEndDate", "approvalIdentity"], diagnosticLabel: "Approved community program" }),
  componentContract("language_selector", { optional: true, defaultEnabled: false, placement: "header_utility", variant: "translated_routes_only", contentSource: "approved_runtime_configuration", requiredConfiguration: ["actualTranslatedContent", "translatedRoutes", "canonicalHreflangConfiguration", "languageLabels", "routingBehavior", "approvalIdentity"], diagnosticLabel: "Approved translated-route selector" }),
] satisfies readonly ThemeFamilyComponentContract[]);

const RUNTIME_TO_DURABLE_CONFIGURATION_KEY = Object.freeze({
  visibility: "responsive_visibility",
} satisfies Readonly<Record<string, string>>);

const OPTIONAL_RUNTIME_CONFIGURATION_KEYS = Object.freeze([
  "enabled",
  "websiteId",
  "themeCompatibility",
  "placement",
  "variant",
  "visibility",
  "contentSource",
  "accessibilityLabel",
]);

export const PERFORMANCE_LOCAL_V2_SOURCE_COMMIT =
  "1b766664ea99d923195bbf98e8a1e4d833b50084" as const;

// The durable Theme Version is attributed to source commit 1b766664..., where
// the v2 campaign contract was time-bounded. Later typed evergreen support is
// configuration validation, not a silent rewrite of that source contract.
const SOURCE_COMMIT_CONTRACT_OVERRIDES = Object.freeze({
  campaign_banner: Object.freeze({
    requiredConfiguration: Object.freeze([
      "campaignLabel",
      "ctaLabel",
      "ctaDestination",
      "startDate",
      "endDate",
      "termsReference",
      "approvalIdentity",
    ]),
    diagnosticLabel: "Approved time-bounded campaign",
  }),
});

function durableConfigurationKey(value: string): string {
  const explicit = RUNTIME_TO_DURABLE_CONFIGURATION_KEY[
    value as keyof typeof RUNTIME_TO_DURABLE_CONFIGURATION_KEY
  ];
  if (explicit) return explicit;
  return value.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase();
}

export function serializePerformanceLocalComponentContract(
  contract: ThemeFamilyComponentContract,
): SerializedThemeFamilyComponentContract {
  const sourceOverride = SOURCE_COMMIT_CONTRACT_OVERRIDES[
    contract.key as keyof typeof SOURCE_COMMIT_CONTRACT_OVERRIDES
  ];
  const runtimeCapabilityKeys = sourceOverride?.requiredConfiguration ?? (
    contract.optional
      ? contract.requiredConfiguration.slice(OPTIONAL_RUNTIME_CONFIGURATION_KEYS.length)
      : contract.requiredConfiguration
  );
  const durableCapabilityKeys = runtimeCapabilityKeys.map(durableConfigurationKey);
  const requiredConfiguration = contract.optional
    ? [
        ...OPTIONAL_RUNTIME_CONFIGURATION_KEYS.map(durableConfigurationKey),
        ...durableCapabilityKeys,
      ]
    : [...durableCapabilityKeys];
  return Object.freeze({
    component_key: contract.key,
    contract_version: contract.version,
    optional: contract.optional,
    default_enabled: contract.defaultEnabled,
    scope: contract.scope,
    supports_page_override: contract.supportsPageOverride,
    placement: contract.placement,
    variant: contract.variant,
    responsive_visibility: Object.freeze({ ...contract.visibility }),
    theme_compatibility: Object.freeze([...contract.themeCompatibility]) as readonly [
      typeof PERFORMANCE_LOCAL_THEME_COMPATIBILITY,
    ],
    content_source: contract.contentSource,
    required_configuration: Object.freeze(requiredConfiguration),
    supports_cta_label: contract.supportsCtaLabel,
    supports_cta_destination: contract.supportsCtaDestination,
    accessibility_label_required: contract.accessibilityLabelRequired,
    diagnostic_label: sourceOverride?.diagnosticLabel ?? contract.diagnosticLabel,
  });
}

export const PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS = Object.freeze(
  PERFORMANCE_LOCAL_COMPONENT_CONTRACTS.map(
    serializePerformanceLocalComponentContract,
  ),
);

export function performanceLocalComponentContract(
  key: PerformanceLocalComponentKey | string,
): ThemeFamilyComponentContract | undefined {
  return PERFORMANCE_LOCAL_COMPONENT_CONTRACTS.find((item) => item.key === key);
}

/**
 * Accepts only an opaque six-digit runtime color. Invalid preview input falls
 * back to the approved governed primary color and never creates a Theme token.
 */
export function resolvePerformanceLocalBrandAccent(
  runtimeBrandAccent: unknown,
  governedPrimary: string,
): string {
  if (!/^#[\da-f]{6}$/i.test(governedPrimary)) {
    throw new Error("The governed primary color must be an opaque #RRGGBB value.");
  }
  return typeof runtimeBrandAccent === "string" && /^#[\da-f]{6}$/i.test(runtimeBrandAccent)
    ? runtimeBrandAccent
    : governedPrimary;
}

const GOVERNED_TOKEN_ROLES = Object.freeze({
  typography: Object.freeze({ heading: "governed.typography.heading_family", body: "governed.typography.body_family", scale: "governed.typography.font_scale" }),
  spacing: Object.freeze({ scale: "governed.spacing.scale", sections: "governed.spacing.section_spacing" }),
  contentWidths: Object.freeze({ narrow: "governed.content_widths.narrow", content: "governed.content_widths.content", wide: "governed.content_widths.wide" }),
  colors: Object.freeze({ brand: "governed.colors.primary", brandText: "governed.colors.primary_foreground", background: "governed.colors.background", surface: "governed.colors.surface", text: "governed.colors.text", focus: "governed.colors.focus" }),
  bordersAndRadii: Object.freeze({ widths: "governed.borders.widths", radii: "governed.borders.radii" }),
  shadows: Object.freeze({ levels: "governed.shadows", policy: "restrained_elevation" }),
});

export const PERFORMANCE_LOCAL_THEME: ThemeFamilyDefinition = Object.freeze({
  key: "performance-local",
  displayName: "Performance Local",
  version: PERFORMANCE_LOCAL_THEME_VERSION,
  status: "preview_candidate",
  websiteIndependent: true,
  productionReady: false,
  compatibilityIdentity: `atlas-semantic-composition@1|${PERFORMANCE_LOCAL_THEME_COMPATIBILITY}`,
  designContract: Object.freeze({
    ...GOVERNED_TOKEN_ROLES,
    buttonVariants: Object.freeze(["primary", "secondary", "phone", "compact"]),
    cardVariants: Object.freeze(["related", "trust", "form"]),
    sectionVariants: Object.freeze(["authority", "split", "muted", "conversion", "process"]),
    imageTreatments: Object.freeze(["intrinsic_contain", "sixteen_by_nine_contain"]),
    headerVariant: "compact_sticky",
    navigationVariant: "desktop_dropdown_mobile_drawer",
    heroVariant: "visual_conversion",
    footerVariant: "structured",
    responsiveBreakpoints: Object.freeze({ mobile: "max-width: 760px", tablet: "761px to 1100px", desktop: "min-width: 1101px" }),
    accessibilityContract: Object.freeze(["WCAG_2_2_AA_contrast", "minimum_44px_targets", "keyboard_navigation", "visible_focus", "reduced_motion", "semantic_disclosures", "modal_focus_containment"]),
  }),
  supportedComponents: PERFORMANCE_LOCAL_COMPONENT_CONTRACTS,
  previewMetadata: Object.freeze({
    localOnly: true,
    persistsSelection: false,
    mutatesSource: false,
    description: "Read-only Theme Lab adapter over current governed Atlas source identity.",
  }),
});

export const ATLAS_DIAGNOSTIC_THEME: ThemeFamilyDefinition = Object.freeze({
  key: "atlas-diagnostic",
  displayName: "Atlas Diagnostic",
  version: 1,
  status: "internal_diagnostic",
  websiteIndependent: true,
  productionReady: false,
  compatibilityIdentity: "atlas-semantic-composition@1|atlas-diagnostic@1",
  designContract: Object.freeze({
    ...GOVERNED_TOKEN_ROLES,
    buttonVariants: Object.freeze(["diagnostic"]),
    cardVariants: Object.freeze(["diagnostic"]),
    sectionVariants: Object.freeze(["raw_semantic_region"]),
    imageTreatments: Object.freeze(["governed_preset"]),
    headerVariant: "diagnostic",
    navigationVariant: "diagnostic",
    heroVariant: "diagnostic",
    footerVariant: "diagnostic",
    responsiveBreakpoints: Object.freeze({ mobile: "governed", tablet: "governed", desktop: "governed" }),
    accessibilityContract: Object.freeze(["diagnostic_only"]),
  }),
  supportedComponents: Object.freeze([]),
  previewMetadata: Object.freeze({
    localOnly: true,
    persistsSelection: false,
    mutatesSource: false,
    description: "Internal raw semantic-composition diagnostic; not a production Theme.",
  }),
});

export type OptionalComponentResolution = {
  key: PerformanceLocalComponentKey;
  visible: boolean;
  errors: readonly string[];
  diagnostics: string;
};

export type PerformanceLocalOptionalConfiguration = {
  enabled: boolean;
  websiteId: number;
  pageOverrideId?: number | null;
  themeCompatibility: typeof PERFORMANCE_LOCAL_THEME_COMPATIBILITY;
  placement: string;
  variant: string;
  visibility: PerformanceLocalVisibility;
  contentSource: ThemeFamilyComponentContract["contentSource"];
  accessibilityLabel: string;
  ctaLabel?: string;
  ctaDestination?: string;
  [key: string]: unknown;
};

export type OptionalComponentDiagnosticAttributes = Readonly<{
  "data-component-key": PerformanceLocalComponentKey;
  "data-component-version": "2";
  "data-component-optional": "true";
  "data-component-scope": ThemeFamilyComponentContract["scope"];
  "data-component-placement": string;
  "data-component-variant": string;
  "data-component-content-source": ThemeFamilyComponentContract["contentSource"];
  "data-component-theme-compatibility": typeof PERFORMANCE_LOCAL_THEME_COMPATIBILITY;
  "data-component-resolution": "visible";
}>;

/**
 * Builds the common, contract-owned portion of an optional-component
 * configuration. Capability-specific evidence still has to be supplied by the
 * caller and is checked by resolveOptionalComponent before anything may render.
 */
export function performanceLocalOptionalConfiguration(
  key: PerformanceLocalComponentKey,
  websiteId: number,
  accessibilityLabel: string,
  configuration: Readonly<Record<string, unknown>> = {},
): PerformanceLocalOptionalConfiguration {
  const contract = optionalContract(key);
  if (!contract) throw new Error(`${key} is not an optional Performance Local capability.`);
  const resolvedConfiguration = key === "campaign_banner" &&
    !hasOwn(configuration, "intent") &&
    present(configuration.startDate) &&
    present(configuration.endDate) &&
    present(configuration.termsReference)
    ? {
        ...configuration,
        intent: "time_bound_campaign",
        offerDetails: configuration.offerDetails ?? configuration.campaignLabel,
      }
    : configuration;
  return Object.freeze({
    ...resolvedConfiguration,
    enabled: true,
    websiteId,
    themeCompatibility: contract.themeCompatibility[0],
    placement: contract.placement,
    variant: contract.variant,
    visibility: Object.freeze({ ...contract.visibility }),
    contentSource: contract.contentSource,
    accessibilityLabel,
  }) as PerformanceLocalOptionalConfiguration;
}

/**
 * Diagnostic markup is emitted only after centralized resolution says the
 * optional capability is visible. This keeps DOM claims aligned with the same
 * contract that authorized rendering.
 */
export function performanceLocalOptionalComponentAttributes(
  key: PerformanceLocalComponentKey,
  resolution: OptionalComponentResolution,
): OptionalComponentDiagnosticAttributes {
  const contract = optionalContract(key);
  if (!contract) throw new Error(`${key} is not an optional Performance Local capability.`);
  if (resolution.key !== key || !resolution.visible || resolution.errors.length > 0) {
    throw new Error(`${key} cannot expose visible-component diagnostics after a fail-closed resolution.`);
  }
  return Object.freeze({
    "data-component-key": key,
    "data-component-version": String(PERFORMANCE_LOCAL_THEME_VERSION) as "2",
    "data-component-optional": "true",
    "data-component-scope": contract.scope,
    "data-component-placement": contract.placement,
    "data-component-variant": contract.variant,
    "data-component-content-source": contract.contentSource,
    "data-component-theme-compatibility": contract.themeCompatibility[0],
    "data-component-resolution": "visible",
  });
}

export function resolveOptionalComponent(
  key: PerformanceLocalComponentKey,
  configuration: unknown,
  expectedWebsiteId: number,
  viewport: PerformanceLocalViewport,
  now = new Date(),
  expectedPageId?: number | null,
): OptionalComponentResolution {
  const contract = optionalContract(key);
  if (!contract) {
    return { key, visible: false, errors: Object.freeze(["The component is not an optional Performance Local capability."]), diagnostics: `${key}: unsupported optional resolution` };
  }
  if (!contract.visibility[viewport]) {
    return { key, visible: false, errors: Object.freeze([]), diagnostics: `${key}: hidden at ${viewport}` };
  }
  const value = record(configuration);
  if (value.enabled !== true) {
    return { key, visible: false, errors: Object.freeze([]), diagnostics: `${key}: disabled` };
  }
  const missing = contract.requiredConfiguration.filter((field) => !present(value[field]));
  const errors: string[] = missing.map((field) => `Missing required configuration: ${field}.`);
  if (!(now instanceof Date) || !Number.isFinite(now.getTime())) {
    errors.push("Optional component evaluation time is invalid.");
  }
  if (!Number.isSafeInteger(expectedWebsiteId) || expectedWebsiteId <= 0) {
    errors.push("Expected Website identity must be a positive integer.");
  } else if (value.websiteId !== expectedWebsiteId) {
    errors.push("Configuration crosses the Website boundary.");
  }
  validateOptionalScope(value, contract, expectedPageId, errors);

  validateCapabilityConfiguration(key, value, now, errors);

  return {
    key,
    visible: errors.length === 0,
    errors: Object.freeze(errors),
    diagnostics: errors.length ? `${key}: fail closed (${errors.join(" ")})` : `${key}: configured for ${viewport}`,
  };
}

export function performanceLocalViewport(width: number): PerformanceLocalViewport {
  if (!Number.isFinite(width) || width <= 0) throw new Error("Viewport width must be a positive finite number.");
  if (width <= 760) return "mobile";
  if (width <= 1100) return "tablet";
  return "desktop";
}

function validateOptionalScope(
  value: Record<string, unknown>,
  contract: ThemeFamilyComponentContract,
  expectedPageId: number | null | undefined,
  errors: string[],
) {
  if (hasOwn(value, "pageOverrideId") && value.pageOverrideId !== null && value.pageOverrideId !== undefined) {
    if (!Number.isSafeInteger(value.pageOverrideId) || Number(value.pageOverrideId) <= 0) {
      errors.push("Page override identity must be a positive integer or null.");
    } else if (!Number.isSafeInteger(expectedPageId) || Number(expectedPageId) <= 0) {
      errors.push("Current Page identity is required for a page-scoped optional override.");
    } else if (value.pageOverrideId !== expectedPageId) {
      errors.push("Configuration crosses the Page override boundary.");
    }
  }
  if (present(value.themeCompatibility) && value.themeCompatibility !== contract.themeCompatibility[0]) {
    errors.push(`Theme compatibility does not match ${PERFORMANCE_LOCAL_THEME_COMPATIBILITY}.`);
  }
  if (present(value.placement) && value.placement !== contract.placement) {
    errors.push("Placement does not match the component contract.");
  }
  if (present(value.variant) && value.variant !== contract.variant) {
    errors.push("Variant does not match the component contract.");
  }
  if (present(value.contentSource) && value.contentSource !== contract.contentSource) {
    errors.push("Content source does not match the component contract.");
  }
  if (present(value.visibility) && !matchesVisibility(value.visibility, contract.visibility)) {
    errors.push("Visibility does not match the component contract.");
  }
  if (present(value.accessibilityLabel) && !cleanText(value.accessibilityLabel)) {
    errors.push("Accessibility label must be non-empty text.");
  }
  if (present(value.ctaLabel) !== present(value.ctaDestination)) {
    errors.push("CTA label and destination must be configured together.");
  }
  if (present(value.ctaLabel) && !cleanText(value.ctaLabel)) {
    errors.push("CTA label must be non-empty text.");
  }
  if (present(value.ctaDestination) && !isPerformanceLocalSafeDestination(value.ctaDestination)) {
    errors.push("CTA destination is not an approved local action destination.");
  }
}

function validateCapabilityConfiguration(
  key: PerformanceLocalComponentKey,
  value: Record<string, unknown>,
  now: Date,
  errors: string[],
) {
  switch (key) {
    case "campaign_banner":
      validateTextFields(value, ["campaignLabel", "ctaLabel", "approvalIdentity"], "Campaign", errors);
      if (!isPerformanceLocalSafeDestination(value.ctaDestination)) {
        errors.push("Campaign CTA destination is not an approved local action destination.");
      }
      validateCampaignConfiguration(value, now, errors);
      break;
    case "trust_proof_strip":
    case "trust_feature_cards":
      validateTextFields(value, ["sourceIdentity", "approvalIdentity"], "Trust component", errors);
      break;
    case "visual_cta_band":
      validateTextFields(value, ["sourceIdentity", "ctaLabel"], "Visual CTA", errors);
      if (!isPerformanceLocalSafeDestination(value.ctaDestination)) {
        errors.push("Visual CTA destination is not an approved local action destination.");
      }
      break;
    case "sticky_mobile_action_bar":
      validateTextFields(value, ["sourceIdentity", "actionLabel"], "Sticky action", errors);
      if (!isPerformanceLocalSafeDestination(value.phoneOrEstimateDestination)) {
        errors.push("Sticky action destination is not an approved local action destination.");
      }
      break;
    case "review_badge_group":
      validateReviewConfiguration(value, now, errors);
      break;
    case "statistics_counter_band":
      validateStatisticsConfiguration(value, now, errors);
      break;
    case "video_embed_section":
      validateVideoConfiguration(value, errors);
      break;
    case "map_or_service_area_section":
      validateTextFields(value, ["approvedLocationOrServiceArea", "approvedProvider", "approvalIdentity"], "Map or service-area", errors);
      if (value.externalRequestConsent !== true) errors.push("Map or service-area external request consent is not approved.");
      if (value.locationStatus !== "approved") errors.push("Map or service-area location status is not approved.");
      if (!["storefront", "service_area_only"].includes(String(value.storefrontStatus))) {
        errors.push("Map or service-area storefront status is not approved.");
      }
      break;
    case "community_program_section":
      validateTextFields(value, ["approvedProgramIdentity", "approvedCopy", "approvalIdentity"], "Community program", errors);
      if (!isPerformanceLocalSafeDestination(value.destination)) {
        errors.push("Community program destination is not an approved local action destination.");
      }
      validateEffectiveDateRange(value, "effectiveStartDate", "effectiveEndDate", now, "Community program", errors);
      break;
    case "language_selector":
      validateLanguageConfiguration(value, errors);
      break;
    case "compact_estimate_form":
      validateEstimateFormConfiguration(value, errors);
      break;
    default:
      break;
  }
}

function validateCampaignConfiguration(
  value: Record<string, unknown>,
  now: Date,
  errors: string[],
) {
  const intent = value.intent === "evergreen_conversion" || value.intent === "time_bound_campaign"
    ? value.intent
    : null;
  if (!intent) {
    errors.push("Campaign intent must be evergreen_conversion or time_bound_campaign.");
    return;
  }
  if (intent === "evergreen_conversion") {
    const prohibitedFields = [
      "startDate",
      "endDate",
      "termsReference",
      "price",
      "qualifier",
      "discount",
      "urgency",
      "financing",
      "guarantee",
    ] as const;
    for (const field of prohibitedFields) {
      if (present(value[field])) {
        errors.push(`Evergreen conversion configuration cannot include ${field}.`);
      }
    }
    const evergreenCopy = [value.campaignLabel, value.ctaLabel]
      .filter((item): item is string => typeof item === "string")
      .join(" ");
    if (
      /(?:[$€£]\s*\d|\b\d+(?:\.\d{1,2})?\s*%|\b\d+(?:\.\d{1,2})?\s*(?:percent|dollars?|usd)\b|\b(?:special|sale|discount|limited[- ]time|expires?|urgenc(?:y|t)|urgent|act\s+now|now|hurry|last\s+chance|ends?\s+soon|today(?:\s+only)?|immediately|guarantee[ds]?|financ(?:e|ing)|price|only\s+\$|save|savings?|free|complimentary|no[- ]cost|dollars?|usd|bucks?)\b|\b(?:\d+(?:\.\d+)?|half|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|hundred)\s+off\b)/i.test(
        evergreenCopy,
      )
    ) {
      errors.push("Evergreen conversion copy contains promotional or unsupported language.");
    }
    return;
  }
  if (!present(value.termsReference)) {
    errors.push("Time-bound campaign configuration requires termsReference.");
  }
  if (
    value.intent === "time_bound_campaign" &&
    !present(value.offerDetails) &&
    !present(value.approvedOfferDetails)
  ) {
    errors.push("Time-bound campaign configuration requires approved offer details.");
  }
  validateTextFields(value, ["termsReference"], "Campaign", errors);
  validateCampaignDates(value, now, errors);
}

function validateCampaignDates(value: Record<string, unknown>, now: Date, errors: string[]) {
  const start = exactInstant(value.startDate);
  const end = exactInstant(value.endDate);
  if (!start || !end || end.getTime() <= start.getTime()) {
    errors.push("Campaign dates are missing or invalid.");
    return;
  }
  if (!Number.isFinite(now.getTime())) {
    errors.push("Campaign evaluation time is invalid.");
    return;
  }
  if (now.getTime() < start.getTime() || now.getTime() >= end.getTime()) {
    errors.push("Campaign is outside its approved active dates.");
  }
}

function validateReviewConfiguration(value: Record<string, unknown>, now: Date, errors: string[]) {
  validateTextFields(value, ["provider", "trademarkUseAuthorization", "approvalIdentity"], "Review", errors);
  if (typeof value.rating !== "number" || !Number.isFinite(value.rating) || value.rating < 0 || value.rating > 5) {
    errors.push("Review rating must be a finite number from 0 through 5.");
  }
  if (!Number.isSafeInteger(value.reviewCount) || Number(value.reviewCount) < 0) {
    errors.push("Review count must be a non-negative integer.");
  }
  if (value.ratingApprovalStatus !== "approved" || value.reviewCountApprovalStatus !== "approved") {
    errors.push("Review rating and count must each have approved status.");
  }
  const verified = exactCalendarDate(value.verificationDate);
  if (!verified || (Number.isFinite(now.getTime()) && verified.getTime() > now.getTime())) {
    errors.push("Review verification date is invalid or in the future.");
  }
  if (!isPerformanceLocalSafeDestination(value.destination)) {
    errors.push("Review destination is not an approved local action destination.");
  }
}

function validateStatisticsConfiguration(value: Record<string, unknown>, now: Date, errors: string[]) {
  validateTextFields(value, ["metricLabel", "source", "approvalIdentity"], "Statistic", errors);
  const validValue = (typeof value.value === "number" && Number.isFinite(value.value)) ||
    (typeof value.value === "string" && value.value.trim().length > 0);
  if (!validValue) errors.push("Statistic value must be finite or a non-empty approved display value.");
  const effective = exactCalendarDate(value.effectiveDate);
  if (!effective || (Number.isFinite(now.getTime()) && effective.getTime() > now.getTime())) {
    errors.push("Statistic effective date is invalid or in the future.");
  }
}

function validateVideoConfiguration(value: Record<string, unknown>, errors: string[]) {
  validateTextFields(value, ["approvedProvider", "title", "accessibilityText", "approvalIdentity"], "Video", errors);
  if (!["local_media", "click_to_load", "privacy_enhanced"].includes(String(value.privacyMode))) {
    errors.push("Video privacy mode is not supported.");
  }
  const identity = value.approvedUrlOrMediaIdentity;
  if (isLocalMediaIdentity(identity)) return;
  if (!isApprovedHttpsDestination(identity)) {
    errors.push("Video URL or media identity is invalid.");
    return;
  }
  if (value.externalRequestConsent !== true) {
    errors.push("External video requests require explicit approval.");
  }
  if (value.privacyMode === "local_media") {
    errors.push("An external video URL cannot use local-media privacy mode.");
  }
}

function validateLanguageConfiguration(value: Record<string, unknown>, errors: string[]) {
  validateTextFields(value, ["approvalIdentity"], "Language selector", errors);
  if (value.actualTranslatedContent !== true) errors.push("Actual translated content is not approved.");
  if (value.canonicalHreflangConfiguration !== "approved") {
    errors.push("Canonical and hreflang configuration is not approved.");
  }
  if (value.routingBehavior !== "approved_local_routes") {
    errors.push("Translated routing behavior is not approved.");
  }
  const routes = translatedRouteLanguages(value.translatedRoutes);
  const labels = translatedLanguageLabels(value.languageLabels);
  if (!routes || !labels || routes.length !== labels.size || routes.some((language) => !labels.has(language))) {
    errors.push("Translated routes or language labels are absent, external, or inconsistent.");
  }
}

function validateEstimateFormConfiguration(value: Record<string, unknown>, errors: string[]) {
  if (value.productionMode !== true) {
    if (value.previewOnly !== true) errors.push("Preview estimate forms must be explicitly preview-only.");
    return;
  }
  if (value.previewOnly !== false) errors.push("A production estimate form cannot also be marked preview-only.");
  const productionFields = [
    "submissionProvider",
    "destination",
    "privacyPolicyDestination",
    "retentionPolicy",
    "spamStrategy",
    "requiredConsent",
    "successBehavior",
    "failureBehavior",
    "auditIdentity",
  ] as const;
  for (const field of productionFields) {
    if (!present(value[field])) errors.push(`Production form is missing ${field}.`);
  }
  validateTextFields(
    value,
    ["submissionProvider", "retentionPolicy", "spamStrategy", "successBehavior", "failureBehavior", "auditIdentity"],
    "Production form",
    errors,
  );
  if (present(value.destination) && !isApprovedHttpsOrLocalDestination(value.destination)) {
    errors.push("Production form submission destination is invalid.");
  }
  if (present(value.privacyPolicyDestination) && !isApprovedHttpsOrLocalDestination(value.privacyPolicyDestination)) {
    errors.push("Production form privacy-policy destination is invalid.");
  }
  if (present(value.requiredConsent) && value.requiredConsent !== true) {
    errors.push("Production form required consent is not approved.");
  }
}

function validateEffectiveDateRange(
  value: Record<string, unknown>,
  startKey: string,
  endKey: string,
  now: Date,
  label: string,
  errors: string[],
) {
  const start = exactCalendarDate(value[startKey]);
  const end = exactCalendarDate(value[endKey]);
  if (!start || !end || end.getTime() < start.getTime()) {
    errors.push(`${label} effective dates are missing or invalid.`);
    return;
  }
  if (Number.isFinite(now.getTime()) && now.getTime() < start.getTime()) {
    errors.push(`${label} approval is outside its effective dates.`);
  }
  if (Number.isFinite(now.getTime()) && now.getTime() > end.getTime() + 86_399_999) {
    errors.push(`${label} approval is outside its effective dates.`);
  }
}

function exactInstant(value: unknown): Date | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(value)) return null;
  const instant = new Date(value);
  return Number.isFinite(instant.getTime()) ? instant : null;
}

function exactCalendarDate(value: unknown): Date | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const instant = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(instant.getTime()) && instant.toISOString().slice(0, 10) === value ? instant : null;
}

function translatedRouteLanguages(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  const languages: string[] = [];
  for (const item of value) {
    const route = record(item);
    if (typeof route.language !== "string" || !cleanIdentifier(route.language) || !isLocalRoute(route.destination)) return null;
    languages.push(route.language.trim().toLowerCase());
  }
  return new Set(languages).size === languages.length ? languages : null;
}

function translatedLanguageLabels(value: unknown): Set<string> | null {
  if (Array.isArray(value) && value.length > 0) {
    const labels = value.map((item) => record(item));
    if (labels.some((item) => typeof item.language !== "string" || !cleanIdentifier(item.language) || !present(item.label))) return null;
    return new Set(labels.map((item) => String(item.language).trim().toLowerCase()));
  }
  const labels = record(value);
  const entries = Object.entries(labels);
  if (entries.length === 0 || entries.some(([language, label]) => !cleanIdentifier(language) || !present(label))) return null;
  return new Set(entries.map(([language]) => language.trim().toLowerCase()));
}

function validateTextFields(
  value: Record<string, unknown>,
  fields: readonly string[],
  label: string,
  errors: string[],
) {
  for (const field of fields) {
    if (present(value[field]) && !cleanText(value[field])) {
      errors.push(`${label} ${field} must be non-empty text.`);
    }
  }
}

function cleanText(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && !/[\u0000-\u001f\u007f]/.test(value);
}

export function isPerformanceLocalSafeDestination(value: unknown): boolean {
  if (typeof value !== "string" || value !== value.trim() || /[\u0000-\u001f\u007f\\]/.test(value)) return false;
  return isLocalRoute(value) || /^#[A-Za-z][A-Za-z0-9_:.\-]*$/.test(value) || /^tel:\+?[0-9][0-9().\- ]{5,24}$/.test(value);
}

function isApprovedHttpsOrLocalDestination(value: unknown): boolean {
  return isPerformanceLocalSafeDestination(value) || isApprovedHttpsDestination(value);
}

function isApprovedHttpsDestination(value: unknown): boolean {
  if (typeof value !== "string" || value !== value.trim()) return false;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" && !parsed.username && !parsed.password && Boolean(parsed.hostname);
  } catch {
    return false;
  }
}

function isLocalMediaIdentity(value: unknown): boolean {
  return isLocalRoute(value) || (typeof value === "string" && /^(?:media|asset):[A-Za-z0-9][A-Za-z0-9_.:\-]*$/.test(value));
}

function isLocalRoute(value: unknown): boolean {
  return typeof value === "string" && /^\/(?!\/)[^\s\\]*$/.test(value);
}

function cleanIdentifier(value: string): boolean {
  return /^[A-Za-z][A-Za-z0-9_-]*$/.test(value.trim());
}

function matchesVisibility(value: unknown, expected: PerformanceLocalVisibility): boolean {
  const visibility = record(value);
  return visibility.desktop === expected.desktop && visibility.tablet === expected.tablet && visibility.mobile === expected.mobile;
}

function present(value: unknown): boolean {
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  return value !== null && value !== undefined;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function optionalContract(key: PerformanceLocalComponentKey): ThemeFamilyComponentContract | undefined {
  const contract = performanceLocalComponentContract(key);
  return contract?.optional ? contract : undefined;
}
