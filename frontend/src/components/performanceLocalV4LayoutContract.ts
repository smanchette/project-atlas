import type {
  GeneratedPage,
  PageComponentInstance,
  PageComposition,
  PlannedPage,
} from "../types";
import {
  PERFORMANCE_LOCAL_V4_COMPATIBILITY_IDENTITY,
  PERFORMANCE_LOCAL_V4_DIAGNOSTIC_IDENTITY,
  PERFORMANCE_LOCAL_V4_RENDERER_CONTRACT,
} from "./performanceLocalThemeV4";

export type PerformanceLocalV4PageType =
  | "home"
  | "service"
  | "county"
  | "city_service"
  | "about"
  | "contact"
  | "faq";

export type PerformanceLocalV4LayoutKey =
  | "performance-local-v4-home"
  | "performance-local-v4-service"
  | "performance-local-v4-service-county"
  | "performance-local-v4-city-service"
  | "performance-local-v4-about"
  | "performance-local-v4-contact"
  | "performance-local-v4-faq";

export const PERFORMANCE_LOCAL_V4_COUNTY_RELATED_CITY_GROUP_KEY =
  "performance-local-v4-service-county:related_city_discovery" as const;

export type PerformanceLocalV4RegionKey =
  | "site_header"
  | "hero"
  | "trust"
  | "service_discovery"
  | "company_value"
  | "service_area_discovery"
  | "supporting_discovery"
  | "final_conversion"
  | "site_footer"
  | "service_overview"
  | "approved_guidance"
  | "related_discovery"
  | "faq"
  | "county_overview"
  | "city_discovery"
  | "service_process"
  | "customer_expectations"
  | "preparation_guidance"
  | "county_credentials"
  | "related_city_discovery"
  | "company_story"
  | "credentials"
  | "service_philosophy"
  | "immediate_contact"
  | "contact_expectations"
  | "contact_support"
  | "service_context"
  | "signs"
  | "process"
  | "destination_discovery";

export type PerformanceLocalV4ConsumptionMode =
  | "direct"
  | "nested_navigation"
  | "attached_media"
  | "adjacent_group";

export type PerformanceLocalV4BlockerCategory =
  | "resolution"
  | "scope"
  | "source"
  | "component"
  | "layout"
  | "media";

export type PerformanceLocalV4Blocker = Readonly<{
  code: string;
  category: PerformanceLocalV4BlockerCategory;
  message: string;
  instanceKey?: string;
  regionKey?: PerformanceLocalV4RegionKey;
}>;

export type PerformanceLocalV4Diagnostic = Readonly<{
  code: string;
  severity: "info" | "warning" | "error";
  message: string;
  instanceKey?: string;
  regionKey?: PerformanceLocalV4RegionKey;
}>;

export type PerformanceLocalV4ComponentSelector = Readonly<{
  selectorKey: string;
  componentKey: string;
  sectionKey?: string;
  cardinality: "exactly_one" | "zero_or_one";
  consumptionMode: "direct" | "nested_navigation" | "adjacent_group";
}>;

export type PerformanceLocalV4SemanticRegionRule = Readonly<{
  regionKey: PerformanceLocalV4RegionKey;
  requirement: "required" | "optional";
  presentationVariant: string;
  selectors: readonly PerformanceLocalV4ComponentSelector[];
}>;

export type PerformanceLocalV4LayoutManifest = Readonly<{
  layoutKey: PerformanceLocalV4LayoutKey;
  layoutVersion: 1;
  displayName: string;
  supportedPageType: PerformanceLocalV4PageType;
  requiredSemanticRegions: readonly PerformanceLocalV4RegionKey[];
  optionalSemanticRegions: readonly PerformanceLocalV4RegionKey[];
  semanticRegions: readonly PerformanceLocalV4SemanticRegionRule[];
  sourceOrderRules: Readonly<{
    regionOrder: "manifest_presentation_order" | "strict_source_order";
    withinRegion: "source_position_then_instance_key";
    attachedMedia: "immediately_with_exact_target";
    undeclaredComponents: "block";
  }>;
  presentationGroupingRules: readonly Readonly<{
    regionKey: PerformanceLocalV4RegionKey;
    groupKey: string;
    adjacency: "not_required" | "required";
  }>[];
  conversionPlacementRules: readonly string[];
  mediaSlotRules: readonly string[];
  navigationDiscoveryRules: readonly string[];
  navigationPresentationPolicy: Readonly<{
    sourceClaimPolicy: "consume_each_navigation_component_exactly_once";
    headerSetPriority: readonly ["primary_navigation", "utility_navigation"];
    duplicateHeaderTargetPolicy: "retain_source_claim_dedupe_presentation_by_target_planned_page_id";
    footerTargetScope: "independent_footer_navigation";
    invalidTargetPolicy: "block";
  }>;
  responsiveBehavior: readonly string[];
  accessibilityExpectations: readonly string[];
  missingInputBehavior: Readonly<{
    requiredRegion: "block_layout";
    optionalRegion: "omit_without_wrapper";
    requiredMedia: "omit_media_and_block_media_readiness";
    optionalMedia: "omit_without_wrapper";
    structuralDemoMedia: "theme_lab_only_labeled_non_content";
    genericFallback: "forbidden";
  }>;
  diagnosticIdentity: typeof PERFORMANCE_LOCAL_V4_DIAGNOSTIC_IDENTITY;
  compatibilityIdentity: typeof PERFORMANCE_LOCAL_V4_COMPATIBILITY_IDENTITY;
  rendererContract: typeof PERFORMANCE_LOCAL_V4_RENDERER_CONTRACT;
}>;

export type PerformanceLocalV4LayoutResolution =
  | Readonly<{
      status: "resolved";
      pageType: PerformanceLocalV4PageType;
      manifest: PerformanceLocalV4LayoutManifest;
    }>
  | Readonly<{
      status: "blocked";
      rawPageType: string | null;
      blockers: readonly PerformanceLocalV4Blocker[];
    }>;

export type PerformanceLocalV4ConsumptionRecord = Readonly<{
  instanceKey: string;
  componentKey: string;
  regionKey: PerformanceLocalV4RegionKey;
  groupKey: string | null;
  mode: PerformanceLocalV4ConsumptionMode;
  sourcePosition: number;
}>;

export type PerformanceLocalV4RegionAudit = Readonly<{
  regionKey: PerformanceLocalV4RegionKey;
  requirement: "required" | "optional";
  presentationVariant: string;
  sourceInstanceKeys: readonly string[];
  presentationGroups: readonly Readonly<{
    groupKey: string;
    sourceInstanceKeys: readonly string[];
  }>[];
  missing: boolean;
}>;

export type PerformanceLocalV4LayoutAudit = Readonly<{
  resolutionStatus: "resolved" | "blocked";
  status: "ready" | "blocked";
  layoutReady: boolean;
  pageType: PerformanceLocalV4PageType | null;
  layoutKey: PerformanceLocalV4LayoutKey | null;
  layoutVersion: 1 | null;
  diagnosticIdentity: typeof PERFORMANCE_LOCAL_V4_DIAGNOSTIC_IDENTITY;
  compatibilityIdentity: typeof PERFORMANCE_LOCAL_V4_COMPATIBILITY_IDENTITY;
  sourceIdentity: Readonly<{
    websiteId: number | null;
    sitePlanId: number | null;
    plannedPageId: number | null;
    generatedPageId: number | null;
    compositionId: number | null;
    compositionVersion: number | null;
    compositionSourceHash: string | null;
  }>;
  manifest: PerformanceLocalV4LayoutManifest | null;
  regions: readonly PerformanceLocalV4RegionAudit[];
  consumption: readonly PerformanceLocalV4ConsumptionRecord[];
  sourceComponentCount: number;
  consumedComponentCount: number;
  unconsumedSourceInstanceKeys: readonly string[];
  duplicatedSourceInstanceKeys: readonly string[];
  missingRequiredRegionKeys: readonly PerformanceLocalV4RegionKey[];
  missingOptionalRegionKeys: readonly PerformanceLocalV4RegionKey[];
  ownershipMismatches: readonly string[];
  blockers: readonly PerformanceLocalV4Blocker[];
  diagnostics: readonly PerformanceLocalV4Diagnostic[];
  truthfulRendererResult: "ready" | "blocked";
  structuralDemoRendererResult: "ready" | "blocked";
}>;

export type PerformanceLocalV4CompositionAuditInput = Readonly<{
  page: GeneratedPage;
  plannedPage: PlannedPage;
  composition: PageComposition;
}>;

const COMMON_CONVERSION_RULES = Object.freeze([
  "Optional governed campaign banner precedes the site header and leaves no gap when disabled.",
  "Governed Call and Request Estimate actions retain their exact V3 destinations and labels.",
  "The compact estimate form remains provider-disabled with five defaults and six maximum.",
  "Mobile sticky actions retain hero, menu, form-focus, footer, back-to-top, and safe-area guards.",
]);

const COMMON_MEDIA_RULES = Object.freeze([
  "Bind media only through media_placement.target_component_instance_key.",
  "A missing asset produces no blank wrapper, legacy fallback, or cross-page fallback.",
  "Required missing media blocks media readiness without fabricating site content.",
  "Demo media slots exist only in the explicitly labeled operator Theme Lab mode.",
]);

const COMMON_NAVIGATION_RULES = Object.freeze([
  "Consume only resolved Navigation Set, internal-link, and draft-related destinations from the same Website and Site Plan.",
  "Do not infer routes, Cities, Counties, Services, labels, or slugs from prose.",
  "Consume primary and utility source components once, then present primary first and omit a utility item whose governed target Planned Page is already presented.",
  "Reject duplicates within one Navigation Set and all cross-scope destinations; governed global Navigation Sets may include the current page, while contextual and related destination components may not.",
]);

const COMMON_NAVIGATION_PRESENTATION_POLICY = Object.freeze({
  sourceClaimPolicy: "consume_each_navigation_component_exactly_once" as const,
  headerSetPriority: Object.freeze([
    "primary_navigation",
    "utility_navigation",
  ] as const),
  duplicateHeaderTargetPolicy: "retain_source_claim_dedupe_presentation_by_target_planned_page_id" as const,
  footerTargetScope: "independent_footer_navigation" as const,
  invalidTargetPolicy: "block" as const,
});

const COMMON_RESPONSIVE_RULES = Object.freeze([
  "Desktop uses readable governed content widths and balanced grids.",
  "Tablet collapses grids without clipped content or desktop-only narrow columns.",
  "Mobile stacks regions, keeps 44px targets, and reserves sticky safe-area clearance.",
  "Media preserves its governed preset without stretching or destructive cropping.",
]);

const COMMON_ACCESSIBILITY_RULES = Object.freeze([
  "Preserve semantic landmarks and one source-backed page heading.",
  "Use source headings; never invent a visible heading to fill a layout slot.",
  "Preserve keyboard navigation, visible focus, reduced motion, menu ARIA state, Escape, and focus restoration.",
  "FAQ disclosures retain accessible controls and relationships.",
  "Demo placeholders are visibly and programmatically identified as non-content.",
]);

function selector(
  selectorKey: string,
  componentKey: string,
  options: Partial<Pick<
    PerformanceLocalV4ComponentSelector,
    "sectionKey" | "cardinality" | "consumptionMode"
  >> = {},
): PerformanceLocalV4ComponentSelector {
  return Object.freeze({
    selectorKey,
    componentKey,
    ...(options.sectionKey ? { sectionKey: options.sectionKey } : {}),
    cardinality: options.cardinality ?? "exactly_one",
    consumptionMode: options.consumptionMode ?? "direct",
  });
}

function region(
  regionKey: PerformanceLocalV4RegionKey,
  requirement: "required" | "optional",
  presentationVariant: string,
  selectors: readonly PerformanceLocalV4ComponentSelector[],
): PerformanceLocalV4SemanticRegionRule {
  return Object.freeze({
    regionKey,
    requirement,
    presentationVariant,
    selectors: Object.freeze([...selectors]),
  });
}

function headerRegion(): PerformanceLocalV4SemanticRegionRule {
  return region("site_header", "required", "governed_header", [
    selector("website_header", "website_header"),
    selector("utility_navigation", "utility_navigation", {
      consumptionMode: "nested_navigation",
    }),
    selector("primary_navigation", "primary_navigation", {
      consumptionMode: "nested_navigation",
    }),
  ]);
}

function heroRegion(): PerformanceLocalV4SemanticRegionRule {
  return region("hero", "required", "source_backed_hero", [
    selector("hero", "hero"),
  ]);
}

function trustRegion(requirement: "required" | "optional" = "optional") {
  return region("trust", requirement, "governed_credentials", [
    selector("trust_license", "trust_license", {
      cardinality: requirement === "required" ? "exactly_one" : "zero_or_one",
    }),
  ]);
}

function finalRegion(): PerformanceLocalV4SemanticRegionRule {
  return region("final_conversion", "required", "governed_final_conversion", [
    selector("final_cta", "final_cta"),
  ]);
}

function footerRegion(): PerformanceLocalV4SemanticRegionRule {
  return region("site_footer", "required", "governed_footer", [
    selector("footer_navigation", "footer_navigation", {
      consumptionMode: "nested_navigation",
    }),
    selector("website_footer", "website_footer"),
  ]);
}

function contentSelector(
  sectionKey: string,
  options: Partial<Pick<
    PerformanceLocalV4ComponentSelector,
    "cardinality" | "consumptionMode"
  >> = {},
) {
  return selector(`content_section:${sectionKey}`, "content_section", {
    ...options,
    sectionKey,
  });
}

function serviceSummarySelector(sectionKey: string) {
  return selector(`service_summary:${sectionKey}`, "service_summary", { sectionKey });
}

function layoutManifest(
  layoutKey: PerformanceLocalV4LayoutKey,
  displayName: string,
  supportedPageType: PerformanceLocalV4PageType,
  semanticRegions: readonly PerformanceLocalV4SemanticRegionRule[],
  options: Readonly<{
    strictSourceOrder?: boolean;
    conversionPlacementRules?: readonly string[];
    navigationDiscoveryRules?: readonly string[];
  }> = {},
): PerformanceLocalV4LayoutManifest {
  const frozenRegions = Object.freeze([...semanticRegions]);
  return Object.freeze({
    layoutKey,
    layoutVersion: 1 as const,
    displayName,
    supportedPageType,
    requiredSemanticRegions: Object.freeze(
      frozenRegions.filter((item) => item.requirement === "required").map((item) => item.regionKey),
    ),
    optionalSemanticRegions: Object.freeze(
      frozenRegions.filter((item) => item.requirement === "optional").map((item) => item.regionKey),
    ),
    semanticRegions: frozenRegions,
    sourceOrderRules: Object.freeze({
      regionOrder: options.strictSourceOrder
        ? "strict_source_order" as const
        : "manifest_presentation_order" as const,
      withinRegion: "source_position_then_instance_key" as const,
      attachedMedia: "immediately_with_exact_target" as const,
      undeclaredComponents: "block" as const,
    }),
    presentationGroupingRules: Object.freeze(frozenRegions
      .filter((item) => item.selectors.some(
        (candidate) => candidate.consumptionMode === "adjacent_group",
      ))
      .map((item) => Object.freeze({
        regionKey: item.regionKey,
        groupKey: `${layoutKey}:${item.regionKey}`,
        adjacency: "required" as const,
      }))),
    conversionPlacementRules: Object.freeze([
      ...COMMON_CONVERSION_RULES,
      ...(options.conversionPlacementRules ?? []),
    ]),
    mediaSlotRules: COMMON_MEDIA_RULES,
    navigationDiscoveryRules: Object.freeze([
      ...COMMON_NAVIGATION_RULES,
      ...(options.navigationDiscoveryRules ?? []),
    ]),
    navigationPresentationPolicy: COMMON_NAVIGATION_PRESENTATION_POLICY,
    responsiveBehavior: COMMON_RESPONSIVE_RULES,
    accessibilityExpectations: COMMON_ACCESSIBILITY_RULES,
    missingInputBehavior: Object.freeze({
      requiredRegion: "block_layout" as const,
      optionalRegion: "omit_without_wrapper" as const,
      requiredMedia: "omit_media_and_block_media_readiness" as const,
      optionalMedia: "omit_without_wrapper" as const,
      structuralDemoMedia: "theme_lab_only_labeled_non_content" as const,
      genericFallback: "forbidden" as const,
    }),
    diagnosticIdentity: PERFORMANCE_LOCAL_V4_DIAGNOSTIC_IDENTITY,
    compatibilityIdentity: PERFORMANCE_LOCAL_V4_COMPATIBILITY_IDENTITY,
    rendererContract: PERFORMANCE_LOCAL_V4_RENDERER_CONTRACT,
  });
}

const HOME_MANIFEST = layoutManifest(
  "performance-local-v4-home",
  "Home",
  "home",
  [
    headerRegion(),
    heroRegion(),
    trustRegion("required"),
    region("service_discovery", "required", "primary_service_grid", [
      contentSelector("primary_services"),
    ]),
    region("company_value", "required", "company_value", [contentSelector("trust")]),
    region("service_area_discovery", "optional", "service_area", [
      contentSelector("service_area", { cardinality: "zero_or_one" }),
    ]),
    region("supporting_discovery", "optional", "related_pages", [
      selector("related_page_links", "related_page_links", { cardinality: "zero_or_one" }),
    ]),
    finalRegion(),
    footerRegion(),
  ],
  {
    navigationDiscoveryRules: [
      "Home service discovery may expose only source-backed service copy and governed destinations.",
    ],
  },
);

const SERVICE_MANIFEST = layoutManifest(
  "performance-local-v4-service",
  "Service",
  "service",
  [
    headerRegion(),
    heroRegion(),
    trustRegion(),
    region("service_overview", "required", "service_overview", [
      serviceSummarySelector("service_overview"),
    ]),
    region("approved_guidance", "required", "source_backed_guidance", [
      contentSelector("approved_guidance"),
    ]),
    region("service_area_discovery", "optional", "service_area", [
      contentSelector("service_area", { cardinality: "zero_or_one" }),
    ]),
    region("related_discovery", "optional", "governed_destination_cards", [
      selector("destination_cards", "destination_cards", { cardinality: "zero_or_one" }),
    ]),
    region("faq", "optional", "accessible_faq", [
      selector("faq", "faq", { cardinality: "zero_or_one" }),
    ]),
    finalRegion(),
    footerRegion(),
  ],
  {
    navigationDiscoveryRules: [
      "Related services and service areas use only governed destination-card routes.",
    ],
  },
);

const COUNTY_MANIFEST = layoutManifest(
  "performance-local-v4-service-county",
  "Service-County",
  "county",
  [
    headerRegion(),
    heroRegion(),
    trustRegion(),
    region("county_overview", "required", "county_service_overview", [
      serviceSummarySelector("service_county_intro"),
    ]),
    region("city_discovery", "required", "county_city_discovery", [
      contentSelector("cities_served"),
    ]),
    region("service_process", "required", "source_backed_process", [
      contentSelector("how_service_works"),
    ]),
    region("customer_expectations", "required", "customer_expectations", [
      contentSelector("customer_expectations"),
    ]),
    region("preparation_guidance", "optional", "preparation_guidance", [
      contentSelector("preparation_guidance", { cardinality: "zero_or_one" }),
    ]),
    region("county_credentials", "optional", "county_credentials", [
      contentSelector("trust_and_license", { cardinality: "zero_or_one" }),
    ]),
    region("related_city_discovery", "optional", "governed_city_routes", [
      contentSelector("related_city_services", {
        cardinality: "zero_or_one",
        consumptionMode: "adjacent_group",
      }),
      selector("destination_cards", "destination_cards", {
        cardinality: "zero_or_one",
        consumptionMode: "adjacent_group",
      }),
    ]),
    region("faq", "optional", "accessible_faq", [
      selector("faq", "faq", { cardinality: "zero_or_one" }),
    ]),
    finalRegion(),
    footerRegion(),
  ],
  {
    navigationDiscoveryRules: [
      "City discovery uses only exact governed City-Service destinations and never infers Cities from prose.",
      "Related city services may merge only when their exact source body equals one unique ordered prefix of the adjacent governed destination-card labels, leaving at least two governed destinations.",
      "The durable Atlas page type is county; service_county is layout terminology only and is not an accepted resolver input.",
    ],
  },
);

const ABOUT_MANIFEST = layoutManifest(
  "performance-local-v4-about",
  "About",
  "about",
  [
    headerRegion(),
    heroRegion(),
    region("company_story", "required", "company_story", [contentSelector("company_story")]),
    region("credentials", "required", "governed_credentials", [
      selector("trust_license", "trust_license"),
      contentSelector("experience"),
    ]),
    region("service_philosophy", "required", "service_philosophy", [
      contentSelector("mission"),
    ]),
    region("service_discovery", "optional", "related_pages", [
      selector("related_page_links", "related_page_links", { cardinality: "zero_or_one" }),
    ]),
    finalRegion(),
    footerRegion(),
  ],
);

const CONTACT_MANIFEST = layoutManifest(
  "performance-local-v4-contact",
  "Contact",
  "contact",
  [
    headerRegion(),
    heroRegion(),
    region("immediate_contact", "required", "immediate_contact_actions", [
      selector("trust_license", "trust_license"),
      contentSelector("ways_to_contact"),
      selector("contact_pathways", "contact_pathways"),
    ]),
    finalRegion(),
    region("contact_expectations", "optional", "contact_expectations", [
      contentSelector("hours", { cardinality: "zero_or_one" }),
    ]),
    region("service_area_discovery", "optional", "service_area", [
      contentSelector("service_area", { cardinality: "zero_or_one" }),
    ]),
    region("related_discovery", "optional", "related_pages", [
      selector("related_page_links", "related_page_links", { cardinality: "zero_or_one" }),
    ]),
    footerRegion(),
  ],
  {
    conversionPlacementRules: [
      "Place the inert compact estimate form after the immediate governed contact actions.",
      "Do not expose an address, office hours, response promise, recipient, outbox, or provider unless governed source supplies it.",
    ],
  },
);

const FAQ_MANIFEST = layoutManifest(
  "performance-local-v4-faq",
  "FAQ",
  "faq",
  [
    headerRegion(),
    heroRegion(),
    region("faq", "required", "accessible_faq", [selector("faq", "faq")]),
    region("related_discovery", "optional", "related_pages", [
      selector("related_page_links", "related_page_links", { cardinality: "zero_or_one" }),
    ]),
    region("contact_support", "optional", "contact_support", [
      contentSelector("contact", { cardinality: "zero_or_one" }),
    ]),
    trustRegion(),
    finalRegion(),
    footerRegion(),
  ],
  {
    navigationDiscoveryRules: [
      "FAQ categories or in-page navigation are absent unless source headings explicitly provide them.",
    ],
  },
);

const CITY_SERVICE_MANIFEST = layoutManifest(
  "performance-local-v4-city-service",
  "City-Service",
  "city_service",
  [
    headerRegion(),
    heroRegion(),
    trustRegion("required"),
    region("service_context", "required", "legacy_service_context", [
      serviceSummarySelector("why_it_matters"),
    ]),
    region("signs", "required", "legacy_signs", [contentSelector("signs_section")]),
    region("process", "required", "legacy_canonical_process", [
      contentSelector("process_section", { consumptionMode: "adjacent_group" }),
      contentSelector("prep_section", { consumptionMode: "adjacent_group" }),
      contentSelector("realtor_property_manager_section", { consumptionMode: "adjacent_group" }),
    ]),
    region("destination_discovery", "required", "legacy_destination_cards", [
      selector("destination_cards", "destination_cards"),
    ]),
    region("faq", "required", "legacy_accessible_faq", [selector("faq", "faq")]),
    finalRegion(),
    footerRegion(),
  ],
  { strictSourceOrder: true },
);

export const PERFORMANCE_LOCAL_V4_LAYOUT_MANIFESTS = Object.freeze({
  home: HOME_MANIFEST,
  service: SERVICE_MANIFEST,
  county: COUNTY_MANIFEST,
  city_service: CITY_SERVICE_MANIFEST,
  about: ABOUT_MANIFEST,
  contact: CONTACT_MANIFEST,
  faq: FAQ_MANIFEST,
} satisfies Readonly<Record<PerformanceLocalV4PageType, PerformanceLocalV4LayoutManifest>>);

export function resolvePerformanceLocalV4Layout(rawPageType: unknown): PerformanceLocalV4LayoutResolution {
  if (
    typeof rawPageType === "string" &&
    Object.prototype.hasOwnProperty.call(PERFORMANCE_LOCAL_V4_LAYOUT_MANIFESTS, rawPageType)
  ) {
    const pageType = rawPageType as PerformanceLocalV4PageType;
    return Object.freeze({
      status: "resolved" as const,
      pageType,
      manifest: PERFORMANCE_LOCAL_V4_LAYOUT_MANIFESTS[pageType],
    });
  }
  const raw = typeof rawPageType === "string" ? rawPageType : null;
  const noAlias = raw === "service_county";
  return Object.freeze({
    status: "blocked" as const,
    rawPageType: raw,
    blockers: Object.freeze([Object.freeze({
      code: noAlias ? "service_county_alias_forbidden" : "unsupported_page_type",
      category: "resolution" as const,
      message: noAlias
        ? "service_county is not an Atlas page type; use the exact durable county vocabulary without aliasing."
        : "The page type has no explicit Performance Local V4 layout and cannot use a generic fallback.",
    })]),
  });
}

// Implemented below the source-defined manifest registry so UI consumers never
// need to reproduce selection, ownership, or component-consumption rules.
export function auditPerformanceLocalV4Composition(
  input: PerformanceLocalV4CompositionAuditInput,
): PerformanceLocalV4LayoutAudit {
  return auditComposition(input);
}

function auditComposition(
  input: PerformanceLocalV4CompositionAuditInput,
): PerformanceLocalV4LayoutAudit {
  const { page, plannedPage, composition } = input;
  const resolution = resolvePerformanceLocalV4Layout(page.page_type);
  const components = [...composition.effective_components];
  const sourceIdentity = Object.freeze({
    websiteId: positiveIntegerOrNull(composition.website_id),
    sitePlanId: positiveIntegerOrNull(composition.site_plan_id),
    plannedPageId: positiveIntegerOrNull(composition.planned_page_id),
    generatedPageId: positiveIntegerOrNull(composition.generated_page_id),
    compositionId: positiveIntegerOrNull(composition.id),
    compositionVersion: positiveIntegerOrNull(composition.composition_version),
    compositionSourceHash: validFingerprint(composition.source_hash)
      ? composition.source_hash
      : null,
  });

  if (resolution.status === "blocked") {
    return deepFreeze({
      resolutionStatus: "blocked" as const,
      status: "blocked" as const,
      layoutReady: false,
      pageType: null,
      layoutKey: null,
      layoutVersion: null,
      diagnosticIdentity: PERFORMANCE_LOCAL_V4_DIAGNOSTIC_IDENTITY,
      compatibilityIdentity: PERFORMANCE_LOCAL_V4_COMPATIBILITY_IDENTITY,
      sourceIdentity,
      manifest: null,
      regions: [],
      consumption: [],
      sourceComponentCount: components.length,
      consumedComponentCount: 0,
      unconsumedSourceInstanceKeys: components
        .map((component) => component.instance_key)
        .sort(),
      duplicatedSourceInstanceKeys: duplicateValues(
        components.map((component) => component.instance_key),
      ),
      missingRequiredRegionKeys: [],
      missingOptionalRegionKeys: [],
      ownershipMismatches: [],
      blockers: [...resolution.blockers],
      diagnostics: resolution.blockers.map((blocker) => ({
        code: blocker.code,
        severity: "error" as const,
        message: blocker.message,
      })),
      truthfulRendererResult: "blocked" as const,
      structuralDemoRendererResult: "blocked" as const,
    });
  }

  const manifest = resolution.manifest;
  const blockers: PerformanceLocalV4Blocker[] = [];
  const blockerKeys = new Set<string>();
  const diagnostics: PerformanceLocalV4Diagnostic[] = [];
  const ownershipMismatches: string[] = [];
  const duplicated = new Set<string>();
  const claims = new Map<string, PerformanceLocalV4ConsumptionRecord>();
  const orderedComponents = components
    .map((component, sourceIndex) => ({ component, sourceIndex }))
    .sort((left, right) =>
      left.component.position - right.component.position ||
      left.component.instance_key.localeCompare(right.component.instance_key) ||
      left.sourceIndex - right.sourceIndex,
    );
  const componentByInstanceKey = new Map<string, PageComponentInstance>();
  const sourceIndexByInstanceKey = new Map<string, number>();

  const addBlocker = (blocker: PerformanceLocalV4Blocker) => {
    const key = [blocker.code, blocker.instanceKey, blocker.regionKey, blocker.message].join("|");
    if (blockerKeys.has(key)) return;
    blockerKeys.add(key);
    blockers.push(Object.freeze({ ...blocker }));
    diagnostics.push(Object.freeze({
      code: blocker.code,
      severity: "error" as const,
      message: blocker.message,
      ...(blocker.instanceKey ? { instanceKey: blocker.instanceKey } : {}),
      ...(blocker.regionKey ? { regionKey: blocker.regionKey } : {}),
    }));
  };

  const addOwnershipMismatch = (
    code: string,
    message: string,
    instanceKey?: string,
  ) => {
    ownershipMismatches.push(message);
    addBlocker({
      code,
      category: "scope",
      message,
      ...(instanceKey ? { instanceKey } : {}),
    });
  };

  validateTopLevelOwnership(input, resolution.pageType, addOwnershipMismatch, addBlocker);

  for (const [orderedIndex, { component }] of orderedComponents.entries()) {
    if (!component.instance_key || component.instance_key.trim() !== component.instance_key) {
      addBlocker({
        code: "invalid_component_instance_key",
        category: "component",
        message: "Every source component requires one exact non-blank instance key.",
        instanceKey: component.instance_key,
      });
    }
    if (!Number.isSafeInteger(component.position) || component.position < 0) {
      addBlocker({
        code: "invalid_component_source_position",
        category: "source",
        message: "Every source component requires a non-negative integer source position.",
        instanceKey: component.instance_key,
      });
    }
    if (componentByInstanceKey.has(component.instance_key)) {
      duplicated.add(component.instance_key);
      addBlocker({
        code: "duplicate_component_instance_key",
        category: "component",
        message: "The composition contains a duplicated source component instance key.",
        instanceKey: component.instance_key,
      });
    } else {
      componentByInstanceKey.set(component.instance_key, component);
      sourceIndexByInstanceKey.set(component.instance_key, orderedIndex);
    }
  }

  for (const position of duplicateValues(components.map((component) => String(component.position)))) {
    addBlocker({
      code: "ambiguous_component_source_order",
      category: "source",
      message: `Multiple source components share position ${position}.`,
    });
  }

  const sourceSnapshot = asRecord(composition.source_snapshot);
  const sourceTargetIdentities = collectSourceTargetIdentities(sourceSnapshot);
  const navigationSetIds = collectRecordIds(sourceSnapshot?.navigation_sets);
  const internalLinkIds = collectRecordIds(sourceSnapshot?.internal_links);
  const mediaRequirements = collectMediaRequirements(
    asRecord(sourceSnapshot?.page_media)?.requirements,
  );
  const draftRelatedPageIds = collectTargetPlannedPageIds(sourceSnapshot?.draft_related_targets);

  for (const component of components) {
    validateComponentOwnership(
      component,
      input,
      navigationSetIds,
      internalLinkIds,
      mediaRequirements,
      draftRelatedPageIds,
      sourceTargetIdentities,
      addOwnershipMismatch,
    );
  }

  const groupKeyByRegion = new Map(
    manifest.presentationGroupingRules.map((rule) => [rule.regionKey, rule.groupKey]),
  );
  const selectorMissingByRegion = new Map<PerformanceLocalV4RegionKey, boolean>();
  const regionClaimKeys = new Map<PerformanceLocalV4RegionKey, Set<string>>();

  const claim = (
    component: PageComponentInstance,
    regionKey: PerformanceLocalV4RegionKey,
    mode: PerformanceLocalV4ConsumptionMode,
  ) => {
    const existing = claims.get(component.instance_key);
    if (existing) {
      duplicated.add(component.instance_key);
      addBlocker({
        code: "source_component_claimed_multiple_times",
        category: "component",
        message: `Source component ${component.instance_key} is claimed by more than one V4 presentation rule.`,
        instanceKey: component.instance_key,
        regionKey,
      });
      return;
    }
    const record = Object.freeze({
      instanceKey: component.instance_key,
      componentKey: component.component_key,
      regionKey,
      groupKey: mode === "adjacent_group"
        ? groupKeyByRegion.get(regionKey) ?? null
        : null,
      mode,
      sourcePosition: component.position,
    });
    claims.set(component.instance_key, record);
    const keys = regionClaimKeys.get(regionKey) ?? new Set<string>();
    keys.add(component.instance_key);
    regionClaimKeys.set(regionKey, keys);
  };

  for (const regionRule of manifest.semanticRegions) {
    let requiredSelectorMissing = false;
    for (const selectorRule of regionRule.selectors) {
      const matches = components.filter((component) =>
        component.component_key !== "media_placement" &&
        selectorMatches(component, selectorRule),
      );
      const expectedExactlyOne = selectorRule.cardinality === "exactly_one";
      if ((expectedExactlyOne && matches.length !== 1) || (!expectedExactlyOne && matches.length > 1)) {
        if (matches.length === 0) {
          if (expectedExactlyOne) requiredSelectorMissing = true;
        } else {
          for (const match of matches) duplicated.add(match.instance_key);
          addBlocker({
            code: "ambiguous_layout_selector",
            category: "layout",
            message: `Selector ${selectorRule.selectorKey} matched ${matches.length} components instead of ${expectedExactlyOne ? "exactly one" : "zero or one"}.`,
            regionKey: regionRule.regionKey,
          });
        }
        continue;
      }
      for (const component of matches) {
        claim(component, regionRule.regionKey, selectorRule.consumptionMode);
      }
    }
    selectorMissingByRegion.set(regionRule.regionKey, requiredSelectorMissing);
    if (regionRule.requirement === "required" && requiredSelectorMissing) {
      addBlocker({
        code: "missing_required_semantic_region",
        category: "layout",
        message: `Required semantic region ${regionRule.regionKey} lacks one or more exact source components.`,
        regionKey: regionRule.regionKey,
      });
    }
  }

  const mediaByTarget = new Map<string, PageComponentInstance[]>();
  for (const media of components.filter((component) => component.component_key === "media_placement")) {
    const target = exactString(media.input_bindings.target_component_instance_key);
    if (!target) {
      addBlocker({
        code: "media_target_missing",
        category: "media",
        message: "A media placement lacks its exact target component instance key.",
        instanceKey: media.instance_key,
      });
      continue;
    }
    const values = mediaByTarget.get(target) ?? [];
    values.push(media);
    mediaByTarget.set(target, values);
  }

  for (const [targetKey, mediaComponents] of mediaByTarget) {
    const target = componentByInstanceKey.get(targetKey);
    const targetClaim = claims.get(targetKey);
    if (!target || target.component_key === "media_placement" || !targetClaim) {
      for (const media of mediaComponents) {
        addBlocker({
          code: "media_target_not_consumed",
          category: "media",
          message: `Media placement target ${targetKey} is missing, is media, or has no exact V4 region claim.`,
          instanceKey: media.instance_key,
        });
      }
      continue;
    }
    if (mediaComponents.length !== 1) {
      for (const media of mediaComponents) duplicated.add(media.instance_key);
      addBlocker({
        code: "duplicate_media_target",
        category: "media",
        message: `Multiple governed media placements target exact component ${targetKey}.`,
        instanceKey: targetKey,
      });
      continue;
    }
    const media = mediaComponents[0];
    const targetComponentKey = exactString(media.input_bindings.target_component_key);
    const targetRegion = exactString(media.input_bindings.target_region);
    if (targetComponentKey && targetComponentKey !== target.component_key) {
      addBlocker({
        code: "media_target_component_mismatch",
        category: "media",
        message: "The media placement target component key does not match its exact target instance.",
        instanceKey: media.instance_key,
      });
      continue;
    }
    if (targetRegion && targetRegion !== target.region) {
      addBlocker({
        code: "media_target_region_mismatch",
        category: "media",
        message: "The media placement target region does not match its exact target instance.",
        instanceKey: media.instance_key,
      });
      continue;
    }
    claim(media, targetClaim.regionKey, "attached_media");
    if (!renderableMediaSource(media)) {
      diagnostics.push(Object.freeze({
        code: "media_asset_missing_truthful_omission",
        severity: "warning" as const,
        message: "Missing governed media must be omitted without an empty wrapper; media readiness remains separate.",
        instanceKey: media.instance_key,
        regionKey: targetClaim.regionKey,
      }));
    }
  }

  for (const groupingRule of manifest.presentationGroupingRules) {
    if (groupingRule.adjacency !== "required") continue;
    const regionRule = manifest.semanticRegions.find(
      (candidate) => candidate.regionKey === groupingRule.regionKey,
    );
    const grouped = [...claims.values()]
      .filter((record) =>
        record.regionKey === groupingRule.regionKey && record.mode === "adjacent_group",
      )
      .sort(compareConsumption);
    const indices = grouped.map((record) => sourceIndexByInstanceKey.get(record.instanceKey) ?? -1);
    const expectedOrder = regionRule?.selectors
      .filter((selectorRule) => selectorRule.consumptionMode === "adjacent_group")
      .flatMap((selectorRule) => components
        .filter((component) => selectorMatches(component, selectorRule))
        .map((component) => component.instance_key)) ?? [];
    if (regionRule?.requirement === "optional" && grouped.length === 0) continue;
    if (
      grouped.length < 2 ||
      indices.some((index, position) => position > 0 && index !== indices[position - 1] + 1) ||
      !sameStringArray(grouped.map((record) => record.instanceKey), expectedOrder)
    ) {
      addBlocker({
        code: "non_adjacent_source_group",
        category: "layout",
        message: `Presentation group ${groupingRule.groupKey} may group only its exact adjacent source sequence.`,
        regionKey: groupingRule.regionKey,
      });
    }
    if (
      groupingRule.groupKey === PERFORMANCE_LOCAL_V4_COUNTY_RELATED_CITY_GROUP_KEY &&
      grouped.length > 0
    ) {
      validateCountyRelatedCityPresentationGroup(
        grouped
          .map((record) => componentByInstanceKey.get(record.instanceKey))
          .filter((component): component is PageComponentInstance => Boolean(component)),
        addBlocker,
      );
    }
  }

  const regions = manifest.semanticRegions.map((regionRule): PerformanceLocalV4RegionAudit => {
    const records = [...claims.values()]
      .filter((record) => record.regionKey === regionRule.regionKey)
      .sort(compareConsumption);
    const sourceInstanceKeys = records.map((record) => record.instanceKey);
    const missing = sourceInstanceKeys.length === 0 || Boolean(selectorMissingByRegion.get(regionRule.regionKey));
    if (regionRule.requirement === "optional" && missing) {
      diagnostics.push(Object.freeze({
        code: "optional_region_omitted",
        severity: "info" as const,
        message: `Optional semantic region ${regionRule.regionKey} is absent and must leave no wrapper.`,
        regionKey: regionRule.regionKey,
      }));
    }
    const groupingRule = manifest.presentationGroupingRules.find(
      (candidate) => candidate.regionKey === regionRule.regionKey && candidate.adjacency === "required",
    );
    const groupedSourceInstanceKeys = groupingRule
      ? records
        .filter((record) =>
          record.mode === "adjacent_group" && record.groupKey === groupingRule.groupKey,
        )
        .map((record) => record.instanceKey)
      : [];
    return Object.freeze({
      regionKey: regionRule.regionKey,
      requirement: regionRule.requirement,
      presentationVariant: regionRule.presentationVariant,
      sourceInstanceKeys: Object.freeze(sourceInstanceKeys),
      presentationGroups: groupingRule && groupedSourceInstanceKeys.length
        ? Object.freeze([Object.freeze({
            groupKey: groupingRule.groupKey,
            sourceInstanceKeys: Object.freeze(groupedSourceInstanceKeys),
          })])
        : Object.freeze([]),
      missing,
    });
  });

  if (manifest.sourceOrderRules.regionOrder === "strict_source_order") {
    const presentationOrder = regions.flatMap((regionAudit) => regionAudit.sourceInstanceKeys);
    const sourceOrder = orderedComponents.map(({ component }) => component.instance_key);
    if (!sameStringArray(presentationOrder, sourceOrder)) {
      addBlocker({
        code: "strict_source_order_changed",
        category: "layout",
        message: "The City-Service preservation manifest must consume every component in exact source order.",
      });
    }
  }

  const unconsumed = orderedComponents
    .filter(({ component }) => !claims.has(component.instance_key))
    .map(({ component }) => component.instance_key);
  if (unconsumed.length) {
    addBlocker({
      code: "unconsumed_source_components",
      category: "component",
      message: `The V4 manifest left ${unconsumed.length} source component(s) unconsumed.`,
    });
  }

  const missingRequired = regions
    .filter((item) => item.requirement === "required" && item.missing)
    .map((item) => item.regionKey);
  const missingOptional = regions
    .filter((item) => item.requirement === "optional" && item.missing)
    .map((item) => item.regionKey);
  const consumption = [...claims.values()].sort(compareConsumption);
  const duplicatedSourceInstanceKeys = [...duplicated].sort();
  const layoutReady =
    blockers.length === 0 &&
    missingRequired.length === 0 &&
    unconsumed.length === 0 &&
    duplicatedSourceInstanceKeys.length === 0 &&
    consumption.length === components.length;

  return deepFreeze({
    resolutionStatus: "resolved" as const,
    status: layoutReady ? "ready" as const : "blocked" as const,
    layoutReady,
    pageType: resolution.pageType,
    layoutKey: manifest.layoutKey,
    layoutVersion: manifest.layoutVersion,
    diagnosticIdentity: manifest.diagnosticIdentity,
    compatibilityIdentity: manifest.compatibilityIdentity,
    sourceIdentity,
    manifest,
    regions,
    consumption,
    sourceComponentCount: components.length,
    consumedComponentCount: consumption.length,
    unconsumedSourceInstanceKeys: unconsumed,
    duplicatedSourceInstanceKeys,
    missingRequiredRegionKeys: missingRequired,
    missingOptionalRegionKeys: missingOptional,
    ownershipMismatches: uniqueSorted(ownershipMismatches),
    blockers,
    diagnostics,
    truthfulRendererResult: layoutReady ? "ready" as const : "blocked" as const,
    structuralDemoRendererResult: layoutReady ? "ready" as const : "blocked" as const,
  });
}

type SourceTargetIdentity = Readonly<{
  plannedPageId: number;
  generatedPageId: number | null;
  websiteId: number;
  sitePlanId: number;
  slug: string;
}>;

type SourceMediaRequirement = Readonly<{
  id: number;
  targetComponentInstanceKey: string | null;
  componentOrSection: string | null;
  contractVersion: number | null;
  lifecycleStatus: string | null;
}>;

function validateTopLevelOwnership(
  input: PerformanceLocalV4CompositionAuditInput,
  resolvedPageType: PerformanceLocalV4PageType,
  addOwnershipMismatch: (code: string, message: string, instanceKey?: string) => void,
  addBlocker: (blocker: PerformanceLocalV4Blocker) => void,
) {
  const { page, plannedPage, composition } = input;
  const generatedWebsiteId = positiveIntegerOrNull(page.website_id);
  const expectedWebsiteId = positiveIntegerOrNull(plannedPage.website_id);
  const expectedSitePlanId = positiveIntegerOrNull(plannedPage.site_plan_id);
  if (
    generatedWebsiteId === null ||
    expectedWebsiteId === null ||
    composition.website_id !== expectedWebsiteId ||
    generatedWebsiteId !== expectedWebsiteId
  ) {
    addOwnershipMismatch(
      "website_scope_mismatch",
      "Generated Page, Planned Page, and Composition Website identities must match exactly.",
    );
  }
  if (
    expectedSitePlanId === null ||
    composition.site_plan_id !== expectedSitePlanId ||
    composition.planned_page_id !== plannedPage.id
  ) {
    addOwnershipMismatch(
      "site_plan_scope_mismatch",
      "Composition and Planned Page Site Plan/page identities must match exactly.",
    );
  }
  if (
    composition.generated_page_id !== page.id ||
    plannedPage.generated_page_id !== page.id
  ) {
    addOwnershipMismatch(
      "generated_page_scope_mismatch",
      "Planned Page and Composition must bind the exact Generated Page.",
    );
  }
  if (plannedPage.page_type !== resolvedPageType || page.page_type !== plannedPage.page_type) {
    addOwnershipMismatch(
      "page_type_scope_mismatch",
      "Generated and Planned Page types must match the exact resolved V4 page type.",
    );
  }
  if (page.page_slug !== plannedPage.intended_slug) {
    addOwnershipMismatch(
      "page_slug_scope_mismatch",
      "Generated Page slug must match its exact Planned Page destination slug.",
    );
  }
  if (composition.status !== "current" || composition.validation_errors.length) {
    addBlocker({
      code: "composition_not_current",
      category: "source",
      message: "V4 accepts only a current composition with no validation errors.",
    });
  }
  if (!validFingerprint(composition.source_hash)) {
    addBlocker({
      code: "composition_source_identity_invalid",
      category: "source",
      message: "V4 requires the exact 64-character Composition source hash.",
    });
  }
  const snapshot = asRecord(composition.source_snapshot);
  if (!snapshot) {
    addOwnershipMismatch(
      "composition_source_snapshot_missing",
      "Composition source snapshot is missing.",
    );
    return;
  }
  const snapshotPairs: Array<[string, number]> = [
    ["website_id", composition.website_id],
    ["site_plan_id", composition.site_plan_id],
    ["planned_page_id", composition.planned_page_id],
    ["generated_page_id", composition.generated_page_id],
  ];
  for (const [key, expected] of snapshotPairs) {
    if (snapshot[key] !== expected) {
      addOwnershipMismatch(
        "composition_source_snapshot_scope_mismatch",
        `Composition source snapshot ${key} does not match its owning record.`,
      );
    }
  }
}

function validateComponentOwnership(
  component: PageComponentInstance,
  input: PerformanceLocalV4CompositionAuditInput,
  navigationSetIds: ReadonlySet<number>,
  internalLinkIds: ReadonlySet<number>,
  mediaRequirements: ReadonlyMap<number, SourceMediaRequirement>,
  draftRelatedPageIds: ReadonlySet<number>,
  sourceTargets: ReadonlyMap<number, SourceTargetIdentity>,
  addOwnershipMismatch: (code: string, message: string, instanceKey?: string) => void,
) {
  const bindings = asRecord(component.input_bindings) ?? {};
  if (
    "generated_page_id" in bindings &&
    bindings.generated_page_id !== input.page.id
  ) {
    addOwnershipMismatch(
      "component_generated_page_mismatch",
      `Component ${component.instance_key} crosses its Generated Page boundary.`,
      component.instance_key,
    );
  }
  if (
    "website_id" in bindings &&
    bindings.website_id !== input.composition.website_id
  ) {
    addOwnershipMismatch(
      "component_website_mismatch",
      `Component ${component.instance_key} crosses its Website boundary.`,
      component.instance_key,
    );
  }
  if ("navigation_set_id" in bindings) {
    const navigationSetId = positiveIntegerOrNull(bindings.navigation_set_id);
    if (navigationSetId === null || !navigationSetIds.has(navigationSetId)) {
      addOwnershipMismatch(
        "navigation_set_source_mismatch",
        `Navigation component ${component.instance_key} is not bound to its Composition source snapshot.`,
        component.instance_key,
      );
    }
  }
  for (const rawId of asArray(bindings.internal_link_intent_ids)) {
    const id = positiveIntegerOrNull(rawId);
    if (id === null || !internalLinkIds.has(id)) {
      addOwnershipMismatch(
        "internal_link_source_mismatch",
        `Component ${component.instance_key} references an ungoverned internal-link identity.`,
        component.instance_key,
      );
    }
  }
  for (const rawId of asArray(bindings.draft_related_page_ids)) {
    const id = positiveIntegerOrNull(rawId);
    if (id === null || !draftRelatedPageIds.has(id)) {
      addOwnershipMismatch(
        "draft_related_source_mismatch",
        `Component ${component.instance_key} references an ungoverned related Planned Page.`,
        component.instance_key,
      );
    }
  }
  if (component.component_key === "media_placement") {
    const requirementId = positiveIntegerOrNull(bindings.media_requirement_id);
    const requirement = requirementId === null ? null : mediaRequirements.get(requirementId) ?? null;
    if (!requirement) {
      addOwnershipMismatch(
        "media_requirement_source_mismatch",
        `Media component ${component.instance_key} is not bound to a current source-snapshot requirement.`,
        component.instance_key,
      );
    } else if (
      (requirement.targetComponentInstanceKey !== null &&
        requirement.targetComponentInstanceKey !== bindings.target_component_instance_key) ||
      (requirement.componentOrSection !== null &&
        requirement.componentOrSection !== bindings.target_component_key) ||
      (requirement.contractVersion !== null &&
        requirement.contractVersion !== bindings.placement_contract_version) ||
      (requirement.lifecycleStatus !== null && requirement.lifecycleStatus !== "active")
    ) {
      addOwnershipMismatch(
        "media_requirement_binding_mismatch",
        `Media component ${component.instance_key} does not match its exact source-snapshot requirement target/version/lifecycle.`,
        component.instance_key,
      );
    }
  }
  const resolvedPageType = exactString(component.resolved_data.page_type);
  if (resolvedPageType && resolvedPageType !== input.page.page_type) {
    addOwnershipMismatch(
      "resolved_page_type_mismatch",
      `Component ${component.instance_key} exposes another page type.`,
      component.instance_key,
    );
  }
  const resolvedDestinationIds: number[] = [];
  const isNavigationComponent = [
    "primary_navigation",
    "utility_navigation",
    "footer_navigation",
  ].includes(component.component_key);
  visitResolvedTargets(component.resolved_data, (target) => {
    const plannedPageId = positiveIntegerOrNull(target.target_planned_page_id);
    if (plannedPageId === null) return;
    resolvedDestinationIds.push(plannedPageId);
    const source = sourceTargets.get(plannedPageId);
    const generatedPageId = positiveIntegerOrNull(target.target_generated_page_id);
    const slug = exactString(target.slug);
    if (
      !source ||
      (plannedPageId === input.plannedPage.id && !isNavigationComponent) ||
      source.websiteId !== input.composition.website_id ||
      source.sitePlanId !== input.composition.site_plan_id ||
      (generatedPageId !== null && source.generatedPageId !== generatedPageId) ||
      (slug && source.slug !== slug)
    ) {
      addOwnershipMismatch(
        "resolved_destination_scope_mismatch",
        `Component ${component.instance_key} exposes a destination outside its governed source identity.`,
        component.instance_key,
      );
    }
  });
  if (
    isNavigationComponent &&
    duplicateValues(resolvedDestinationIds.map(String)).length
  ) {
    addOwnershipMismatch(
      "navigation_set_duplicate_target",
      `Navigation component ${component.instance_key} repeats a governed target within one Navigation Set.`,
      component.instance_key,
    );
  }
}

function selectorMatches(
  component: PageComponentInstance,
  selectorRule: PerformanceLocalV4ComponentSelector,
): boolean {
  if (component.component_key !== selectorRule.componentKey) return false;
  if (selectorRule.sectionKey === undefined) return true;
  return component.input_bindings.section_key === selectorRule.sectionKey;
}

function compareConsumption(
  left: PerformanceLocalV4ConsumptionRecord,
  right: PerformanceLocalV4ConsumptionRecord,
) {
  return left.sourcePosition - right.sourcePosition || left.instanceKey.localeCompare(right.instanceKey);
}

function collectSourceTargetIdentities(
  snapshot: Record<string, unknown> | null,
): ReadonlyMap<number, SourceTargetIdentity> {
  const result = new Map<number, SourceTargetIdentity>();
  const candidates: unknown[] = [];
  for (const item of asArray(snapshot?.navigation_items)) {
    candidates.push(asRecord(item)?.target);
  }
  for (const item of asArray(snapshot?.internal_links)) {
    candidates.push(asRecord(item)?.target);
  }
  candidates.push(...asArray(snapshot?.draft_related_targets));
  for (const candidate of candidates) {
    const target = asRecord(candidate);
    const plannedPageId = positiveIntegerOrNull(target?.planned_page_id);
    const websiteId = positiveIntegerOrNull(target?.website_id);
    const sitePlanId = positiveIntegerOrNull(target?.site_plan_id);
    const generatedPageId = positiveIntegerOrNull(target?.generated_page_id);
    const slug = exactString(target?.intended_slug);
    if (plannedPageId === null || websiteId === null || sitePlanId === null || !slug) continue;
    result.set(plannedPageId, Object.freeze({
      plannedPageId,
      generatedPageId,
      websiteId,
      sitePlanId,
      slug,
    }));
  }
  return result;
}

function collectRecordIds(value: unknown): ReadonlySet<number> {
  const result = new Set<number>();
  for (const item of asArray(value)) {
    const id = positiveIntegerOrNull(asRecord(item)?.id);
    if (id !== null) result.add(id);
  }
  return result;
}

function collectMediaRequirements(
  value: unknown,
): ReadonlyMap<number, SourceMediaRequirement> {
  const result = new Map<number, SourceMediaRequirement>();
  for (const item of asArray(value)) {
    const record = asRecord(item);
    const id = positiveIntegerOrNull(record?.id);
    if (id === null) continue;
    result.set(id, Object.freeze({
      id,
      targetComponentInstanceKey: exactString(record?.target_component_instance_key),
      componentOrSection: exactString(record?.component_or_section),
      contractVersion: positiveIntegerOrNull(record?.contract_version),
      lifecycleStatus: exactString(record?.lifecycle_status),
    }));
  }
  return result;
}

function collectTargetPlannedPageIds(value: unknown): ReadonlySet<number> {
  const result = new Set<number>();
  for (const item of asArray(value)) {
    const id = positiveIntegerOrNull(asRecord(item)?.planned_page_id);
    if (id !== null) result.add(id);
  }
  return result;
}

function visitResolvedTargets(
  value: unknown,
  visit: (target: Record<string, unknown>) => void,
) {
  if (Array.isArray(value)) {
    for (const item of value) visitResolvedTargets(item, visit);
    return;
  }
  const record = asRecord(value);
  if (!record) return;
  if ("target_planned_page_id" in record) visit(record);
  for (const child of Object.values(record)) visitResolvedTargets(child, visit);
}

function renderableMediaSource(component: PageComponentInstance): boolean {
  const source = exactString(component.resolved_data.asset_url);
  const alt = exactString(component.resolved_data.alt_text);
  return Boolean(source && alt && (/^https?:\/\//i.test(source) || source.startsWith("/")));
}

function duplicateValues(values: readonly string[]): string[] {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const value of values) {
    if (seen.has(value)) duplicates.add(value);
    seen.add(value);
  }
  return [...duplicates].sort();
}

function validateCountyRelatedCityPresentationGroup(
  components: readonly PageComponentInstance[],
  addBlocker: (blocker: PerformanceLocalV4Blocker) => void,
) {
  const regionKey = "related_city_discovery" as const;
  const source = components[0];
  const destinations = components[1];
  if (
    components.length !== 2 ||
    source?.component_key !== "content_section" ||
    source.input_bindings.section_key !== "related_city_services" ||
    destinations?.component_key !== "destination_cards"
  ) {
    addBlocker({
      code: "county_related_city_merge_component_mismatch",
      category: "layout",
      message: "County related-city presentation requires the exact related_city_services and destination_cards source pair in source order.",
      regionKey,
    });
    return;
  }

  const heading = exactString(source.resolved_data.heading);
  const body = exactString(source.resolved_data.body);
  const sourceListValid = Boolean(heading && body);
  if (!sourceListValid) {
    addBlocker({
      code: "county_related_city_merge_source_invalid",
      category: "source",
      message: "County related_city_services requires one exact heading and one exact non-blank source label list.",
      instanceKey: source.instance_key,
      regionKey,
    });
  }

  const links = asArray(destinations.resolved_data.links).map(asRecord);
  const destinationLabels = links.map((link) => exactString(link?.label));
  const destinationTargetIds = links.map((link) => positiveIntegerOrNull(link?.target_planned_page_id));
  const destinationGeneratedPageIds = links.map(
    (link) => positiveIntegerOrNull(link?.target_generated_page_id),
  );
  const destinationSlugs = links.map((link) => exactString(link?.slug));
  const destinationsValid = Boolean(
    links.length > 0 &&
    links.every((link) => link !== null) &&
    destinationLabels.every((label): label is string => label !== null) &&
    destinationTargetIds.every((id): id is number => id !== null) &&
    destinationGeneratedPageIds.every((id): id is number => id !== null) &&
    destinationSlugs.every((slug): slug is string => slug !== null) &&
    new Set(destinationLabels).size === destinationLabels.length &&
    new Set(destinationTargetIds).size === destinationTargetIds.length &&
    new Set(destinationGeneratedPageIds).size === destinationGeneratedPageIds.length &&
    new Set(destinationSlugs).size === destinationSlugs.length
  );
  if (!destinationsValid) {
    addBlocker({
      code: "county_related_city_merge_destinations_invalid",
      category: "source",
      message: "County destination_cards requires unique labels and unique complete governed route identities.",
      instanceKey: destinations.instance_key,
      regionKey,
    });
    return;
  }
  if (!sourceListValid) return;

  const exactDestinationLabels = destinationLabels as string[];
  const matchingPrefixLengths = exactDestinationLabels
    .map((_, index) => index + 1)
    .filter((length) => exactDestinationLabels.slice(0, length).join(", ") === body);
  if (matchingPrefixLengths.length !== 1) {
    addBlocker({
      code: "county_related_city_merge_prefix_mismatch",
      category: "layout",
      message: "County related_city_services labels must exactly equal the ordered prefix of governed destination-card labels.",
      instanceKey: source.instance_key,
      regionKey,
    });
    return;
  }
  if (exactDestinationLabels.length - matchingPrefixLengths[0] < 2) {
    addBlocker({
      code: "county_related_city_merge_insufficient_remaining_destinations",
      category: "layout",
      message: "County destination cards must retain at least two governed destinations after the duplicated city-label prefix.",
      instanceKey: destinations.instance_key,
      regionKey,
    });
  }
}

function uniqueSorted(values: readonly string[]): string[] {
  return [...new Set(values)].sort();
}

function sameStringArray(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function validFingerprint(value: unknown): value is string {
  return typeof value === "string" && /^[\da-f]{64}$/i.test(value);
}

function positiveIntegerOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : null;
}

function exactString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 && value.trim() === value ? value : null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function deepFreeze<T>(value: T): T {
  if (typeof value !== "object" || value === null || Object.isFrozen(value)) return value;
  for (const child of Object.values(value as Record<string, unknown>)) deepFreeze(child);
  return Object.freeze(value);
}
