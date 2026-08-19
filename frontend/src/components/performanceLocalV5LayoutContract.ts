import type {
  GeneratedPage,
  PageComponentInstance,
  PageComposition,
  PlannedPage,
} from "../types";
import {
  PERFORMANCE_LOCAL_V5_COMPATIBILITY_IDENTITY,
  PERFORMANCE_LOCAL_V5_DIAGNOSTIC_IDENTITY,
  PERFORMANCE_LOCAL_V5_RENDERER_CONTRACT,
} from "./performanceLocalThemeV5";

export type PerformanceLocalV5PageType =
  | "home"
  | "service"
  | "county"
  | "city_service"
  | "about"
  | "contact"
  | "faq";

export type PerformanceLocalV5LayoutKey =
  | "performance-local-v5-home"
  | "performance-local-v5-service"
  | "performance-local-v5-service-county"
  | "performance-local-v5-city-service"
  | "performance-local-v5-about"
  | "performance-local-v5-contact"
  | "performance-local-v5-faq";

export const PERFORMANCE_LOCAL_V5_COUNTY_RELATED_CITY_GROUP_KEY =
  "performance-local-v5-service-county:related_city_discovery" as const;

export type PerformanceLocalV5RegionKey =
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
  | "experience"
  | "service_philosophy"
  | "immediate_contact"
  | "contact_information"
  | "contact_support"
  | "service_context"
  | "signs"
  | "process"
  | "destination_discovery";

export type PerformanceLocalV5ConsumptionMode =
  | "direct"
  | "nested_navigation"
  | "attached_media"
  | "adjacent_group";

export type PerformanceLocalV5BlockerCategory =
  | "resolution"
  | "scope"
  | "source"
  | "component"
  | "layout"
  | "media";

export type PerformanceLocalV5Blocker = Readonly<{
  code: string;
  category: PerformanceLocalV5BlockerCategory;
  message: string;
  instanceKey?: string;
  regionKey?: PerformanceLocalV5RegionKey;
}>;

export type PerformanceLocalV5Diagnostic = Readonly<{
  code: string;
  severity: "info" | "warning" | "error";
  message: string;
  instanceKey?: string;
  regionKey?: PerformanceLocalV5RegionKey;
}>;

export type PerformanceLocalV5ComponentSelector = Readonly<{
  selectorKey: string;
  componentKey: string;
  sectionKey?: string;
  cardinality: "exactly_one" | "zero_or_one";
  consumptionMode: "direct" | "nested_navigation" | "adjacent_group";
}>;

export type PerformanceLocalV5SemanticRegionRule = Readonly<{
  regionKey: PerformanceLocalV5RegionKey;
  requirement: "required" | "optional";
  presentationVariant: string;
  selectors: readonly PerformanceLocalV5ComponentSelector[];
}>;

export type PerformanceLocalV5VisualCompositionRule = Readonly<{
  compositionKey: string;
  regionKeys: readonly PerformanceLocalV5RegionKey[];
  presentationVariant: string;
  sourceOrder: "region_then_source_position";
}>;

export type PerformanceLocalV5ProgressiveDisclosureRule = Readonly<{
  regionKey: PerformanceLocalV5RegionKey;
  defaultState: "closed";
  answerPolicy: "complete_source_exact";
  openPresentation: "full_content_width";
  maximumColumns: Readonly<{ desktop: 2; tablet: 2; mobile: 1 }>;
}>;

export type PerformanceLocalV5LayoutManifest = Readonly<{
  layoutKey: PerformanceLocalV5LayoutKey;
  layoutVersion: 2;
  displayName: string;
  supportedPageType: PerformanceLocalV5PageType;
  requiredSemanticRegions: readonly PerformanceLocalV5RegionKey[];
  optionalSemanticRegions: readonly PerformanceLocalV5RegionKey[];
  semanticRegions: readonly PerformanceLocalV5SemanticRegionRule[];
  visualCompositionRules: readonly PerformanceLocalV5VisualCompositionRule[];
  progressiveDisclosureRules: readonly PerformanceLocalV5ProgressiveDisclosureRule[];
  sourceOrderRules: Readonly<{
    regionOrder: "manifest_presentation_order" | "strict_source_order";
    withinRegion: "source_position_then_instance_key";
    attachedMedia: "immediately_with_exact_target";
    undeclaredComponents: "block";
  }>;
  presentationGroupingRules: readonly Readonly<{
    regionKey: PerformanceLocalV5RegionKey;
    groupKey: string;
    adjacency: "not_required" | "required";
  }>[];
  destinationEntryPolicy: Readonly<{
    sourceComponentConsumption: "one_logical_claim";
    nestedEntryConsumption: "each_original_index_exactly_once";
    homeServiceMatching: "exact_title_to_exact_governed_label";
    countyCityMatching: "exact_ordered_city_suffix_to_governed_prefix";
    fallback: "forbidden";
  }>;
  finalConversionPolicy: Readonly<{
    sharedAcrossPurposeBuiltLayouts: true;
    page41DelegationUnchanged: true;
    exactCallAction: true;
    exactEstimateDestination: true;
    providerDisabled: true;
    defaultFieldCount: 5;
    maximumFieldCount: 6;
  }>;
  visibleTextColumnPolicy: Readonly<{ desktop: 3; tablet: 2; mobile: 1 }>;
  contentHeightPolicy: Readonly<{
    ordinaryContentMinimumHeight: "forbidden";
    viewportHeightOutsideMobileDrawer: "forbidden";
    shortTextOnlyFullWidthBand: "forbidden_when_composable";
  }>;
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
  diagnosticIdentity: typeof PERFORMANCE_LOCAL_V5_DIAGNOSTIC_IDENTITY;
  compatibilityIdentity: typeof PERFORMANCE_LOCAL_V5_COMPATIBILITY_IDENTITY;
  rendererContract: typeof PERFORMANCE_LOCAL_V5_RENDERER_CONTRACT;
}>;

export type PerformanceLocalV5LayoutResolution =
  | Readonly<{
      status: "resolved";
      pageType: PerformanceLocalV5PageType;
      manifest: PerformanceLocalV5LayoutManifest;
    }>
  | Readonly<{
      status: "blocked";
      rawPageType: string | null;
      blockers: readonly PerformanceLocalV5Blocker[];
    }>;

export type PerformanceLocalV5ConsumptionRecord = Readonly<{
  instanceKey: string;
  componentKey: string;
  regionKey: PerformanceLocalV5RegionKey;
  groupKey: string | null;
  mode: PerformanceLocalV5ConsumptionMode;
  sourcePosition: number;
}>;

export type PerformanceLocalV5RegionAudit = Readonly<{
  regionKey: PerformanceLocalV5RegionKey;
  requirement: "required" | "optional";
  presentationVariant: string;
  sourceInstanceKeys: readonly string[];
  presentationGroups: readonly Readonly<{
    groupKey: string;
    sourceInstanceKeys: readonly string[];
  }>[];
  missing: boolean;
}>;

export type PerformanceLocalV5DestinationPresentationSlot =
  | "featured_service"
  | "service_grid"
  | "county_city"
  | "related_destination";

export type PerformanceLocalV5DestinationConsumptionRecord = Readonly<{
  sourceInstanceKey: string;
  originalLinkIndex: number;
  presentationSlot: PerformanceLocalV5DestinationPresentationSlot;
  label: string;
  purpose: string;
  slug: string;
  targetPlannedPageId: number;
  targetGeneratedPageId: number;
}>;

export type PerformanceLocalV5HomeServiceEntry = Readonly<{
  sourceItemIndex: number;
  exactSourceItem: string;
  title: string;
  description: string;
  matchedLinkIndex: number;
  destination: PerformanceLocalV5DestinationConsumptionRecord;
}>;

export type PerformanceLocalV5HomeServicePresentation = Readonly<{
  status: "ready" | "blocked" | "not_applicable";
  primaryServicesSourceInstanceKey: string | null;
  relatedLinksSourceInstanceKey: string | null;
  mode: "featured" | "grid" | null;
  services: readonly PerformanceLocalV5HomeServiceEntry[];
  remainingLinkIndices: readonly number[];
  remainingDestinations: readonly PerformanceLocalV5DestinationConsumptionRecord[];
}>;

export type PerformanceLocalV5CountyCityEntry = Readonly<{
  cityIndex: number;
  cityName: string;
  originalLinkIndex: number;
  destination: PerformanceLocalV5DestinationConsumptionRecord;
}>;

export type PerformanceLocalV5CountyCityPresentation = Readonly<{
  status: "ready" | "blocked" | "not_applicable";
  citiesServedSourceInstanceKey: string | null;
  relatedCityServicesSourceInstanceKey: string | null;
  destinationCardsSourceInstanceKey: string | null;
  validatedCityPrefixCount: number;
  cityEntries: readonly PerformanceLocalV5CountyCityEntry[];
  remainingLinkIndices: readonly number[];
  remainingDestinations: readonly PerformanceLocalV5DestinationConsumptionRecord[];
}>;

export type PerformanceLocalV5LayoutAudit = Readonly<{
  resolutionStatus: "resolved" | "blocked";
  status: "ready" | "blocked";
  layoutReady: boolean;
  pageType: PerformanceLocalV5PageType | null;
  layoutKey: PerformanceLocalV5LayoutKey | null;
  layoutVersion: 2 | null;
  diagnosticIdentity: typeof PERFORMANCE_LOCAL_V5_DIAGNOSTIC_IDENTITY;
  compatibilityIdentity: typeof PERFORMANCE_LOCAL_V5_COMPATIBILITY_IDENTITY;
  sourceIdentity: Readonly<{
    websiteId: number | null;
    sitePlanId: number | null;
    plannedPageId: number | null;
    generatedPageId: number | null;
    compositionId: number | null;
    compositionVersion: number | null;
    compositionSourceHash: string | null;
  }>;
  manifest: PerformanceLocalV5LayoutManifest | null;
  regions: readonly PerformanceLocalV5RegionAudit[];
  consumption: readonly PerformanceLocalV5ConsumptionRecord[];
  destinationConsumption: readonly PerformanceLocalV5DestinationConsumptionRecord[];
  homeServicePresentation: PerformanceLocalV5HomeServicePresentation;
  countyCityPresentation: PerformanceLocalV5CountyCityPresentation;
  sourceComponentCount: number;
  consumedComponentCount: number;
  unconsumedSourceInstanceKeys: readonly string[];
  duplicatedSourceInstanceKeys: readonly string[];
  unconsumedDestinationEntryKeys: readonly string[];
  duplicatedDestinationEntryKeys: readonly string[];
  missingRequiredRegionKeys: readonly PerformanceLocalV5RegionKey[];
  missingOptionalRegionKeys: readonly PerformanceLocalV5RegionKey[];
  ownershipMismatches: readonly string[];
  blockers: readonly PerformanceLocalV5Blocker[];
  diagnostics: readonly PerformanceLocalV5Diagnostic[];
  truthfulRendererResult: "ready" | "blocked";
  structuralDemoRendererResult: "ready" | "blocked";
}>;

export type PerformanceLocalV5CompositionAuditInput = Readonly<{
  page: GeneratedPage;
  plannedPage: PlannedPage;
  composition: PageComposition;
}>;

const COMMON_CONVERSION_RULES = Object.freeze([
  "Every purpose-built page uses one shared final-conversion presentation.",
  "Governed Call and Request Estimate actions retain their exact V3 destinations and labels.",
  "All form controls remain inside one provider-disabled five-default/six-maximum panel.",
  "Mobile sticky actions retain hero, menu, form-focus, footer, back-to-top, and safe-area guards.",
]);

const COMMON_MEDIA_RULES = Object.freeze([
  "Bind media only through media_placement.target_component_instance_key.",
  "A missing optional asset produces no wrapper, legacy fallback, or cross-page fallback.",
  "Required missing media blocks media readiness without making truthful layout structure fail.",
  "Demo media slots exist only in the explicitly labeled operator Theme Lab mode.",
]);

const COMMON_NAVIGATION_RULES = Object.freeze([
  "Consume only governed same-Website and same-Site-Plan destinations.",
  "Do not infer routes, Cities, Counties, Services, labels, or slugs from prose.",
  "Split contextual link presentation only through audited original link indices.",
  "Reject duplicate or incomplete contextual destination identities.",
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
  "Desktop uses the governed wide content container and at most three visible text-card columns.",
  "Tablet uses at most two visible text-card columns without clipping controls.",
  "Mobile uses one readable text column and reserves fixed-action safe-area clearance.",
  "Ordinary content height follows content; viewport height is reserved for the mobile drawer.",
]);

const COMMON_ACCESSIBILITY_RULES = Object.freeze([
  "Preserve semantic landmarks, a skip target, and one source-backed H1.",
  "Progressive disclosures are native, closed by default, keyboard operable, and source exact.",
  "Preserve visible focus, reduced motion, menu Escape, focus trap, and focus restoration.",
  "All action and disclosure controls retain a minimum 44px target.",
]);

const DESTINATION_ENTRY_POLICY = Object.freeze({
  sourceComponentConsumption: "one_logical_claim" as const,
  nestedEntryConsumption: "each_original_index_exactly_once" as const,
  homeServiceMatching: "exact_title_to_exact_governed_label" as const,
  countyCityMatching: "exact_ordered_city_suffix_to_governed_prefix" as const,
  fallback: "forbidden" as const,
});

const FINAL_CONVERSION_POLICY = Object.freeze({
  sharedAcrossPurposeBuiltLayouts: true as const,
  page41DelegationUnchanged: true as const,
  exactCallAction: true as const,
  exactEstimateDestination: true as const,
  providerDisabled: true as const,
  defaultFieldCount: 5 as const,
  maximumFieldCount: 6 as const,
});

const COLUMN_POLICY = Object.freeze({ desktop: 3 as const, tablet: 2 as const, mobile: 1 as const });
const HEIGHT_POLICY = Object.freeze({
  ordinaryContentMinimumHeight: "forbidden" as const,
  viewportHeightOutsideMobileDrawer: "forbidden" as const,
  shortTextOnlyFullWidthBand: "forbidden_when_composable" as const,
});

function selector(
  selectorKey: string,
  componentKey: string,
  options: Partial<Pick<PerformanceLocalV5ComponentSelector, "sectionKey" | "cardinality" | "consumptionMode">> = {},
): PerformanceLocalV5ComponentSelector {
  return Object.freeze({
    selectorKey,
    componentKey,
    ...(options.sectionKey ? { sectionKey: options.sectionKey } : {}),
    cardinality: options.cardinality ?? "exactly_one",
    consumptionMode: options.consumptionMode ?? "direct",
  });
}

function region(
  regionKey: PerformanceLocalV5RegionKey,
  requirement: "required" | "optional",
  presentationVariant: string,
  selectors: readonly PerformanceLocalV5ComponentSelector[],
): PerformanceLocalV5SemanticRegionRule {
  return Object.freeze({ regionKey, requirement, presentationVariant, selectors: Object.freeze([...selectors]) });
}

function visual(
  compositionKey: string,
  presentationVariant: string,
  regionKeys: readonly PerformanceLocalV5RegionKey[],
): PerformanceLocalV5VisualCompositionRule {
  return Object.freeze({
    compositionKey,
    presentationVariant,
    regionKeys: Object.freeze([...regionKeys]),
    sourceOrder: "region_then_source_position" as const,
  });
}

function disclosure(regionKey: PerformanceLocalV5RegionKey): PerformanceLocalV5ProgressiveDisclosureRule {
  return Object.freeze({
    regionKey,
    defaultState: "closed" as const,
    answerPolicy: "complete_source_exact" as const,
    openPresentation: "full_content_width" as const,
    maximumColumns: Object.freeze({ desktop: 2 as const, tablet: 2 as const, mobile: 1 as const }),
  });
}

function headerRegion() {
  return region("site_header", "required", "governed_header", [
    selector("website_header", "website_header"),
    selector("utility_navigation", "utility_navigation", { consumptionMode: "nested_navigation" }),
    selector("primary_navigation", "primary_navigation", { consumptionMode: "nested_navigation" }),
  ]);
}

function heroRegion() {
  return region("hero", "required", "source_backed_hero", [selector("hero", "hero")]);
}

function trustRegion(requirement: "required" | "optional" = "optional") {
  return region("trust", requirement, "governed_credential_strip", [
    selector("trust_license", "trust_license", {
      cardinality: requirement === "required" ? "exactly_one" : "zero_or_one",
    }),
  ]);
}

function finalRegion() {
  return region("final_conversion", "required", "shared_governed_final_conversion", [
    selector("final_cta", "final_cta"),
  ]);
}

function footerRegion() {
  return region("site_footer", "required", "governed_footer", [
    selector("footer_navigation", "footer_navigation", { consumptionMode: "nested_navigation" }),
    selector("website_footer", "website_footer"),
  ]);
}

function contentSelector(
  sectionKey: string,
  options: Partial<Pick<PerformanceLocalV5ComponentSelector, "cardinality" | "consumptionMode">> = {},
) {
  return selector(`content_section:${sectionKey}`, "content_section", { ...options, sectionKey });
}

function serviceSummarySelector(sectionKey: string) {
  return selector(`service_summary:${sectionKey}`, "service_summary", { sectionKey });
}

function layoutManifest(
  layoutKey: PerformanceLocalV5LayoutKey,
  displayName: string,
  supportedPageType: PerformanceLocalV5PageType,
  semanticRegions: readonly PerformanceLocalV5SemanticRegionRule[],
  options: Readonly<{
    strictSourceOrder?: boolean;
    visualCompositionRules?: readonly PerformanceLocalV5VisualCompositionRule[];
    progressiveDisclosureRules?: readonly PerformanceLocalV5ProgressiveDisclosureRule[];
    navigationDiscoveryRules?: readonly string[];
  }> = {},
): PerformanceLocalV5LayoutManifest {
  const frozenRegions = Object.freeze([...semanticRegions]);
  return deepFreeze({
    layoutKey,
    layoutVersion: 2 as const,
    displayName,
    supportedPageType,
    requiredSemanticRegions: frozenRegions.filter((item) => item.requirement === "required").map((item) => item.regionKey),
    optionalSemanticRegions: frozenRegions.filter((item) => item.requirement === "optional").map((item) => item.regionKey),
    semanticRegions: frozenRegions,
    visualCompositionRules: Object.freeze([...(options.visualCompositionRules ?? [])]),
    progressiveDisclosureRules: Object.freeze([...(options.progressiveDisclosureRules ?? [])]),
    sourceOrderRules: Object.freeze({
      regionOrder: options.strictSourceOrder ? "strict_source_order" as const : "manifest_presentation_order" as const,
      withinRegion: "source_position_then_instance_key" as const,
      attachedMedia: "immediately_with_exact_target" as const,
      undeclaredComponents: "block" as const,
    }),
    presentationGroupingRules: frozenRegions
      .filter((item) => item.selectors.some((candidate) => candidate.consumptionMode === "adjacent_group"))
      .map((item) => Object.freeze({
        regionKey: item.regionKey,
        groupKey: `${layoutKey}:${item.regionKey}`,
        adjacency: "required" as const,
      })),
    destinationEntryPolicy: DESTINATION_ENTRY_POLICY,
    finalConversionPolicy: FINAL_CONVERSION_POLICY,
    visibleTextColumnPolicy: COLUMN_POLICY,
    contentHeightPolicy: HEIGHT_POLICY,
    conversionPlacementRules: COMMON_CONVERSION_RULES,
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
    diagnosticIdentity: PERFORMANCE_LOCAL_V5_DIAGNOSTIC_IDENTITY,
    compatibilityIdentity: PERFORMANCE_LOCAL_V5_COMPATIBILITY_IDENTITY,
    rendererContract: PERFORMANCE_LOCAL_V5_RENDERER_CONTRACT,
  });
}

const HOME_MANIFEST = layoutManifest(
  "performance-local-v5-home", "Home", "home",
  [
    headerRegion(), heroRegion(), trustRegion("required"),
    region("service_discovery", "required", "featured_or_grid_service_discovery", [contentSelector("primary_services")]),
    region("company_value", "required", "company_value", [contentSelector("trust")]),
    region("service_area_discovery", "required", "compact_service_area", [contentSelector("service_area")]),
    region("supporting_discovery", "required", "audited_related_remainder", [selector("related_page_links", "related_page_links")]),
    finalRegion(), footerRegion(),
  ],
  { visualCompositionRules: [
    visual("home-service-discovery", "featured_or_grid_service", ["service_discovery"]),
    visual("home-authority", "company_value_with_service_area", ["company_value", "service_area_discovery"]),
    visual("home-related", "related_destination_remainder", ["supporting_discovery"]),
    visual("home-final", "shared_final_conversion", ["final_conversion"]),
  ] },
);

const SERVICE_MANIFEST = layoutManifest(
  "performance-local-v5-service", "Service", "service",
  [
    headerRegion(), heroRegion(), trustRegion(),
    region("service_overview", "required", "service_overview", [serviceSummarySelector("service_overview")]),
    region("approved_guidance", "required", "closed_source_disclosures", [contentSelector("approved_guidance")]),
    region("service_area_discovery", "required", "compact_service_area", [contentSelector("service_area")]),
    region("related_discovery", "required", "governed_destination_cards", [selector("destination_cards", "destination_cards")]),
    region("faq", "optional", "closed_faq_disclosures", [selector("faq", "faq", { cardinality: "zero_or_one" })]),
    finalRegion(), footerRegion(),
  ],
  { visualCompositionRules: [
    visual("service-overview", "editorial_overview", ["service_overview"]),
    visual("service-guidance", "progressive_disclosure", ["approved_guidance"]),
    visual("service-discovery-support", "service_area_with_related", ["service_area_discovery", "related_discovery"]),
    visual("service-final", "shared_final_conversion", ["final_conversion"]),
  ], progressiveDisclosureRules: [disclosure("approved_guidance"), disclosure("faq")] },
);

const COUNTY_MANIFEST = layoutManifest(
  "performance-local-v5-service-county", "Service-County", "county",
  [
    headerRegion(), heroRegion(), trustRegion(),
    region("county_overview", "required", "county_service_overview", [serviceSummarySelector("service_county_intro")]),
    region("city_discovery", "required", "audited_governed_city_grid", [contentSelector("cities_served")]),
    region("service_process", "required", "source_backed_process", [contentSelector("how_service_works")]),
    region("customer_expectations", "required", "closed_source_disclosures", [contentSelector("customer_expectations")]),
    region("preparation_guidance", "required", "preparation_guidance", [contentSelector("preparation_guidance")]),
    region("county_credentials", "required", "county_credentials", [contentSelector("trust_and_license")]),
    region("related_city_discovery", "required", "audited_city_and_related_partition", [
      contentSelector("related_city_services", { consumptionMode: "adjacent_group" }),
      selector("destination_cards", "destination_cards", { consumptionMode: "adjacent_group" }),
    ]),
    region("faq", "required", "closed_faq_disclosures", [selector("faq", "faq")]),
    finalRegion(), footerRegion(),
  ],
  { visualCompositionRules: [
    visual("county-overview", "county_overview", ["county_overview"]),
    visual("county-city-discovery", "single_governed_city_grid", ["city_discovery", "related_city_discovery"]),
    visual("county-process", "process_then_disclosures", ["service_process", "customer_expectations"]),
    visual("county-authority", "preparation_with_credentials", ["preparation_guidance", "county_credentials"]),
    visual("county-related", "related_destination_remainder", ["related_city_discovery"]),
    visual("county-final", "shared_final_conversion", ["final_conversion"]),
  ], progressiveDisclosureRules: [disclosure("customer_expectations"), disclosure("faq")] },
);

const ABOUT_MANIFEST = layoutManifest(
  "performance-local-v5-about", "About", "about",
  [
    headerRegion(), heroRegion(),
    region("company_story", "required", "company_story", [contentSelector("company_story")]),
    trustRegion("required"),
    region("experience", "required", "experience_and_trust", [contentSelector("experience")]),
    region("service_philosophy", "required", "service_philosophy", [contentSelector("mission")]),
    region("service_discovery", "required", "governed_related_navigation", [selector("related_page_links", "related_page_links")]),
    finalRegion(), footerRegion(),
  ],
  { visualCompositionRules: [
    visual("about-story-authority", "story_with_credential_strip", ["company_story", "trust"]),
    visual("about-experience", "spaced_experience", ["experience"]),
    visual("about-purpose", "purpose_with_related_navigation", ["service_philosophy", "service_discovery"]),
    visual("about-final", "shared_final_conversion", ["final_conversion"]),
  ] },
);

const CONTACT_MANIFEST = layoutManifest(
  "performance-local-v5-contact", "Contact", "contact",
  [
    headerRegion(), heroRegion(),
    region("immediate_contact", "required", "immediate_contact_actions", [selector("contact_pathways", "contact_pathways")]),
    region("contact_information", "required", "compact_contact_information", [
      selector("trust_license", "trust_license"),
      contentSelector("ways_to_contact"),
      contentSelector("hours"),
      contentSelector("service_area"),
    ]),
    finalRegion(),
    region("related_discovery", "required", "governed_related_navigation", [selector("related_page_links", "related_page_links")]),
    footerRegion(),
  ],
  { visualCompositionRules: [
    visual("contact-actions", "immediate_contact_actions", ["immediate_contact"]),
    visual("contact-information", "balanced_compact_information_grid", ["contact_information"]),
    visual("contact-final", "shared_final_conversion", ["final_conversion"]),
    visual("contact-related", "compact_related_navigation", ["related_discovery"]),
  ] },
);

const FAQ_MANIFEST = layoutManifest(
  "performance-local-v5-faq", "FAQ", "faq",
  [
    headerRegion(), heroRegion(),
    region("faq", "required", "closed_faq_disclosures", [selector("faq", "faq")]),
    region("related_discovery", "required", "governed_related_navigation", [selector("related_page_links", "related_page_links")]),
    region("contact_support", "required", "final_conversion_support", [contentSelector("contact")]),
    trustRegion("required"), finalRegion(), footerRegion(),
  ],
  { visualCompositionRules: [
    visual("faq-questions", "responsive_closed_disclosure_grid", ["faq"]),
    visual("faq-related", "compact_related_navigation", ["related_discovery"]),
    visual("faq-final", "support_and_credentials_with_shared_final", ["contact_support", "trust", "final_conversion"]),
  ], progressiveDisclosureRules: [disclosure("faq")] },
);

const CITY_SERVICE_MANIFEST = layoutManifest(
  "performance-local-v5-city-service", "City-Service", "city_service",
  [
    headerRegion(), heroRegion(), trustRegion("required"),
    region("service_context", "required", "legacy_service_context", [serviceSummarySelector("why_it_matters")]),
    region("signs", "required", "legacy_signs", [contentSelector("signs_section")]),
    region("process", "required", "legacy_canonical_process", [
      contentSelector("process_section", { consumptionMode: "adjacent_group" }),
      contentSelector("prep_section", { consumptionMode: "adjacent_group" }),
      contentSelector("realtor_property_manager_section", { consumptionMode: "adjacent_group" }),
    ]),
    region("destination_discovery", "required", "legacy_destination_cards", [selector("destination_cards", "destination_cards")]),
    region("faq", "required", "legacy_accessible_faq", [selector("faq", "faq")]),
    finalRegion(), footerRegion(),
  ],
  { strictSourceOrder: true },
);

export const PERFORMANCE_LOCAL_V5_LAYOUT_MANIFESTS = Object.freeze({
  home: HOME_MANIFEST,
  service: SERVICE_MANIFEST,
  county: COUNTY_MANIFEST,
  city_service: CITY_SERVICE_MANIFEST,
  about: ABOUT_MANIFEST,
  contact: CONTACT_MANIFEST,
  faq: FAQ_MANIFEST,
} satisfies Readonly<Record<PerformanceLocalV5PageType, PerformanceLocalV5LayoutManifest>>);

export function resolvePerformanceLocalV5Layout(rawPageType: unknown): PerformanceLocalV5LayoutResolution {
  if (
    typeof rawPageType === "string" &&
    Object.prototype.hasOwnProperty.call(PERFORMANCE_LOCAL_V5_LAYOUT_MANIFESTS, rawPageType)
  ) {
    const pageType = rawPageType as PerformanceLocalV5PageType;
    return Object.freeze({ status: "resolved" as const, pageType, manifest: PERFORMANCE_LOCAL_V5_LAYOUT_MANIFESTS[pageType] });
  }
  const raw = typeof rawPageType === "string" ? rawPageType : null;
  const alias = raw === "service_county";
  return Object.freeze({
    status: "blocked" as const,
    rawPageType: raw,
    blockers: Object.freeze([Object.freeze({
      code: alias ? "service_county_alias_forbidden" : "unsupported_page_type",
      category: "resolution" as const,
      message: alias
        ? "service_county is not an Atlas page type; V5 requires the exact durable county vocabulary."
        : "The page type has no explicit Performance Local V5 layout and cannot use a generic fallback.",
    })]),
  });
}

// The source-ownership and exact nested-entry audit is implemented below so
// renderers consume one canonical projection rather than reconstructing joins.
export function auditPerformanceLocalV5Composition(
  input: PerformanceLocalV5CompositionAuditInput,
): PerformanceLocalV5LayoutAudit {
  return auditComposition(input);
}

function auditComposition(
  input: PerformanceLocalV5CompositionAuditInput,
): PerformanceLocalV5LayoutAudit {
  const { page, plannedPage, composition } = input;
  const resolution = resolvePerformanceLocalV5Layout(page.page_type);
  const components = [...composition.effective_components];
  const sourceIdentity = Object.freeze({
    websiteId: positiveIntegerOrNull(composition.website_id),
    sitePlanId: positiveIntegerOrNull(composition.site_plan_id),
    plannedPageId: positiveIntegerOrNull(composition.planned_page_id),
    generatedPageId: positiveIntegerOrNull(composition.generated_page_id),
    compositionId: positiveIntegerOrNull(composition.id),
    compositionVersion: positiveIntegerOrNull(composition.composition_version),
    compositionSourceHash: validFingerprint(composition.source_hash) ? composition.source_hash : null,
  });
  const notApplicableHome = emptyHomePresentation("not_applicable");
  const notApplicableCounty = emptyCountyPresentation("not_applicable");

  if (resolution.status === "blocked") {
    return deepFreeze({
      resolutionStatus: "blocked" as const,
      status: "blocked" as const,
      layoutReady: false,
      pageType: null,
      layoutKey: null,
      layoutVersion: null,
      diagnosticIdentity: PERFORMANCE_LOCAL_V5_DIAGNOSTIC_IDENTITY,
      compatibilityIdentity: PERFORMANCE_LOCAL_V5_COMPATIBILITY_IDENTITY,
      sourceIdentity,
      manifest: null,
      regions: [],
      consumption: [],
      destinationConsumption: [],
      homeServicePresentation: notApplicableHome,
      countyCityPresentation: notApplicableCounty,
      sourceComponentCount: components.length,
      consumedComponentCount: 0,
      unconsumedSourceInstanceKeys: components.map((item) => item.instance_key).sort(),
      duplicatedSourceInstanceKeys: duplicateValues(components.map((item) => item.instance_key)),
      unconsumedDestinationEntryKeys: contextualEntryKeys(components),
      duplicatedDestinationEntryKeys: [],
      missingRequiredRegionKeys: [],
      missingOptionalRegionKeys: [],
      ownershipMismatches: [],
      blockers: [...resolution.blockers],
      diagnostics: resolution.blockers.map((item) => ({
        code: item.code,
        severity: "error" as const,
        message: item.message,
      })),
      truthfulRendererResult: "blocked" as const,
      structuralDemoRendererResult: "blocked" as const,
    });
  }

  const manifest = resolution.manifest;
  const blockers: PerformanceLocalV5Blocker[] = [];
  const blockerKeys = new Set<string>();
  const diagnostics: PerformanceLocalV5Diagnostic[] = [];
  const ownershipMismatches: string[] = [];
  const duplicatedComponents = new Set<string>();
  const claims = new Map<string, PerformanceLocalV5ConsumptionRecord>();
  const componentByInstanceKey = new Map<string, PageComponentInstance>();
  const sourceIndexByInstanceKey = new Map<string, number>();
  const orderedComponents = components
    .map((component, originalIndex) => ({ component, originalIndex }))
    .sort((left, right) =>
      left.component.position - right.component.position ||
      left.component.instance_key.localeCompare(right.component.instance_key) ||
      left.originalIndex - right.originalIndex,
    );

  const addBlocker = (blocker: PerformanceLocalV5Blocker) => {
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
  const addOwnershipMismatch = (code: string, message: string, instanceKey?: string) => {
    ownershipMismatches.push(message);
    addBlocker({ code, category: "scope", message, ...(instanceKey ? { instanceKey } : {}) });
  };

  validateTopLevelOwnership(input, resolution.pageType, addOwnershipMismatch, addBlocker);
  for (const [orderedIndex, { component }] of orderedComponents.entries()) {
    if (!exactString(component.instance_key)) {
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
      duplicatedComponents.add(component.instance_key);
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
  for (const position of duplicateValues(components.map((item) => String(item.position)))) {
    addBlocker({
      code: "ambiguous_component_source_order",
      category: "source",
      message: `Multiple source components share position ${position}.`,
    });
  }

  const snapshot = asRecord(composition.source_snapshot);
  const sourceTargets = collectSourceTargetIdentities(snapshot);
  const navigationSetIds = collectRecordIds(snapshot?.navigation_sets);
  const internalLinkIds = collectRecordIds(snapshot?.internal_links);
  const mediaRequirements = collectMediaRequirements(asRecord(snapshot?.page_media)?.requirements);
  const draftRelatedPageIds = collectTargetPlannedPageIds(snapshot?.draft_related_targets);
  for (const component of components) {
    validateComponentOwnership(
      component,
      input,
      navigationSetIds,
      internalLinkIds,
      mediaRequirements,
      draftRelatedPageIds,
      sourceTargets,
      addOwnershipMismatch,
    );
  }

  const groupKeyByRegion = new Map(
    manifest.presentationGroupingRules.map((item) => [item.regionKey, item.groupKey]),
  );
  const selectorMissingByRegion = new Map<PerformanceLocalV5RegionKey, boolean>();
  const claim = (
    component: PageComponentInstance,
    regionKey: PerformanceLocalV5RegionKey,
    mode: PerformanceLocalV5ConsumptionMode,
  ) => {
    if (claims.has(component.instance_key)) {
      duplicatedComponents.add(component.instance_key);
      addBlocker({
        code: "source_component_claimed_multiple_times",
        category: "component",
        message: `Source component ${component.instance_key} is claimed by more than one V5 presentation rule.`,
        instanceKey: component.instance_key,
        regionKey,
      });
      return;
    }
    claims.set(component.instance_key, Object.freeze({
      instanceKey: component.instance_key,
      componentKey: component.component_key,
      regionKey,
      groupKey: mode === "adjacent_group" ? groupKeyByRegion.get(regionKey) ?? null : null,
      mode,
      sourcePosition: component.position,
    }));
  };

  for (const regionRule of manifest.semanticRegions) {
    let requiredSelectorMissing = false;
    for (const selectorRule of regionRule.selectors) {
      const matches = components.filter((component) =>
        component.component_key !== "media_placement" && selectorMatches(component, selectorRule),
      );
      const exactlyOne = selectorRule.cardinality === "exactly_one";
      if ((exactlyOne && matches.length !== 1) || (!exactlyOne && matches.length > 1)) {
        if (matches.length === 0) {
          if (exactlyOne) requiredSelectorMissing = true;
        } else {
          matches.forEach((item) => duplicatedComponents.add(item.instance_key));
          addBlocker({
            code: "ambiguous_layout_selector",
            category: "layout",
            message: `Selector ${selectorRule.selectorKey} matched ${matches.length} components instead of ${exactlyOne ? "exactly one" : "zero or one"}.`,
            regionKey: regionRule.regionKey,
          });
        }
        continue;
      }
      matches.forEach((item) => claim(item, regionRule.regionKey, selectorRule.consumptionMode));
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

  attachMediaClaims(components, componentByInstanceKey, claims, claim, addBlocker, diagnostics);
  validateAdjacentGroups(
    manifest,
    components,
    claims,
    componentByInstanceKey,
    sourceIndexByInstanceKey,
    addBlocker,
  );

  const regions = manifest.semanticRegions.map((regionRule): PerformanceLocalV5RegionAudit => {
    const records = [...claims.values()]
      .filter((item) => item.regionKey === regionRule.regionKey)
      .sort(compareConsumption);
    const sourceInstanceKeys = records.map((item) => item.instanceKey);
    const missing = sourceInstanceKeys.length === 0 || Boolean(selectorMissingByRegion.get(regionRule.regionKey));
    if (regionRule.requirement === "optional" && missing) {
      diagnostics.push(Object.freeze({
        code: "optional_region_omitted",
        severity: "info" as const,
        message: `Optional semantic region ${regionRule.regionKey} is absent and must leave no wrapper.`,
        regionKey: regionRule.regionKey,
      }));
    }
    const grouping = manifest.presentationGroupingRules.find((item) => item.regionKey === regionRule.regionKey);
    const groupedKeys = grouping
      ? records.filter((item) => item.mode === "adjacent_group" && item.groupKey === grouping.groupKey).map((item) => item.instanceKey)
      : [];
    return Object.freeze({
      regionKey: regionRule.regionKey,
      requirement: regionRule.requirement,
      presentationVariant: regionRule.presentationVariant,
      sourceInstanceKeys: Object.freeze(sourceInstanceKeys),
      presentationGroups: grouping && groupedKeys.length ? Object.freeze([Object.freeze({
        groupKey: grouping.groupKey,
        sourceInstanceKeys: Object.freeze(groupedKeys),
      })]) : Object.freeze([]),
      missing,
    });
  });

  if (manifest.sourceOrderRules.regionOrder === "strict_source_order") {
    const presentationOrder = regions.flatMap((item) => item.sourceInstanceKeys);
    const sourceOrder = orderedComponents.map(({ component }) => component.instance_key);
    if (!sameStringArray(presentationOrder, sourceOrder)) {
      addBlocker({
        code: "strict_source_order_changed",
        category: "layout",
        message: "The City-Service preservation manifest must consume every component in exact source order.",
      });
    }
  }

  validateProgressiveDisclosureSources(resolution.pageType, componentByInstanceKey, addBlocker);
  const projection = destinationProjection(resolution.pageType, componentByInstanceKey, addBlocker);
  const expectedDestinationEntryKeys = contextualEntryKeys(components);
  const consumedDestinationEntryKeys = projection.destinationConsumption.map(destinationEntryKey);
  const duplicatedDestinationEntryKeys = duplicateValues(consumedDestinationEntryKeys);
  const consumedEntrySet = new Set(consumedDestinationEntryKeys);
  const unconsumedDestinationEntryKeys = expectedDestinationEntryKeys.filter((key) => !consumedEntrySet.has(key));
  if (duplicatedDestinationEntryKeys.length) {
    addBlocker({
      code: "destination_entry_consumed_multiple_times",
      category: "layout",
      message: "One or more contextual destination entries are assigned to multiple V5 presentation slots.",
    });
  }
  if (unconsumedDestinationEntryKeys.length) {
    addBlocker({
      code: "unconsumed_destination_entries",
      category: "layout",
      message: `V5 left ${unconsumedDestinationEntryKeys.length} contextual destination entry or entries unconsumed.`,
    });
  }

  const unconsumedSourceInstanceKeys = orderedComponents
    .filter(({ component }) => !claims.has(component.instance_key))
    .map(({ component }) => component.instance_key);
  if (unconsumedSourceInstanceKeys.length) {
    addBlocker({
      code: "unconsumed_source_components",
      category: "component",
      message: `The V5 manifest left ${unconsumedSourceInstanceKeys.length} source component(s) unconsumed.`,
    });
  }
  const missingRequiredRegionKeys = regions
    .filter((item) => item.requirement === "required" && item.missing)
    .map((item) => item.regionKey);
  const missingOptionalRegionKeys = regions
    .filter((item) => item.requirement === "optional" && item.missing)
    .map((item) => item.regionKey);
  const consumption = [...claims.values()].sort(compareConsumption);
  const duplicatedSourceInstanceKeys = [...duplicatedComponents].sort();
  const layoutReady =
    blockers.length === 0 &&
    missingRequiredRegionKeys.length === 0 &&
    unconsumedSourceInstanceKeys.length === 0 &&
    duplicatedSourceInstanceKeys.length === 0 &&
    unconsumedDestinationEntryKeys.length === 0 &&
    duplicatedDestinationEntryKeys.length === 0 &&
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
    destinationConsumption: projection.destinationConsumption,
    homeServicePresentation: projection.homeServicePresentation,
    countyCityPresentation: projection.countyCityPresentation,
    sourceComponentCount: components.length,
    consumedComponentCount: consumption.length,
    unconsumedSourceInstanceKeys,
    duplicatedSourceInstanceKeys,
    unconsumedDestinationEntryKeys,
    duplicatedDestinationEntryKeys,
    missingRequiredRegionKeys,
    missingOptionalRegionKeys,
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

type DestinationProjectionResult = Readonly<{
  destinationConsumption: readonly PerformanceLocalV5DestinationConsumptionRecord[];
  homeServicePresentation: PerformanceLocalV5HomeServicePresentation;
  countyCityPresentation: PerformanceLocalV5CountyCityPresentation;
}>;

type ParsedDestination = PerformanceLocalV5DestinationConsumptionRecord;

function validateTopLevelOwnership(
  input: PerformanceLocalV5CompositionAuditInput,
  resolvedPageType: PerformanceLocalV5PageType,
  addOwnershipMismatch: (code: string, message: string, instanceKey?: string) => void,
  addBlocker: (blocker: PerformanceLocalV5Blocker) => void,
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
      "Generated and Planned Page types must match the exact resolved V5 page type.",
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
      message: "V5 accepts only a current composition with no validation errors.",
    });
  }
  if (!validFingerprint(composition.source_hash)) {
    addBlocker({
      code: "composition_source_identity_invalid",
      category: "source",
      message: "V5 requires the exact 64-character Composition source hash.",
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
  input: PerformanceLocalV5CompositionAuditInput,
  navigationSetIds: ReadonlySet<number>,
  internalLinkIds: ReadonlySet<number>,
  mediaRequirements: ReadonlyMap<number, SourceMediaRequirement>,
  draftRelatedPageIds: ReadonlySet<number>,
  sourceTargets: ReadonlyMap<number, SourceTargetIdentity>,
  addOwnershipMismatch: (code: string, message: string, instanceKey?: string) => void,
) {
  const bindings = asRecord(component.input_bindings) ?? {};
  if ("generated_page_id" in bindings && bindings.generated_page_id !== input.page.id) {
    addOwnershipMismatch(
      "component_generated_page_mismatch",
      `Component ${component.instance_key} crosses its Generated Page boundary.`,
      component.instance_key,
    );
  }
  if ("website_id" in bindings && bindings.website_id !== input.composition.website_id) {
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
  if (isNavigationComponent) {
    validateNavigationResolvedItems(component, addOwnershipMismatch);
  }
  visitResolvedTargets(component.resolved_data, (target) => {
    const plannedPageId = positiveIntegerOrNull(target.target_planned_page_id);
    if (plannedPageId === null) {
      addOwnershipMismatch(
        "resolved_destination_identity_incomplete",
        `Component ${component.instance_key} exposes a destination without an exact Planned Page identity.`,
        component.instance_key,
      );
      return;
    }
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
  if (isNavigationComponent && duplicateValues(resolvedDestinationIds.map(String)).length) {
    addOwnershipMismatch(
      "navigation_set_duplicate_target",
      `Navigation component ${component.instance_key} repeats a governed target within one Navigation Set.`,
      component.instance_key,
    );
  }
}

function validateNavigationResolvedItems(
  component: PageComponentInstance,
  addOwnershipMismatch: (code: string, message: string, instanceKey: string) => void,
) {
  type NavigationIdentity = Readonly<{
    id: number;
    targetPlannedPageId: number;
    targetGeneratedPageId: number;
    parentId: number | null;
    position: number;
    label: string;
  }>;
  const parsed: NavigationIdentity[] = [];
  const rawItems = component.resolved_data.items;
  let invalid = !Array.isArray(rawItems);
  for (const rawItem of asArray(rawItems)) {
    const item = asRecord(rawItem);
    const status = exactString(item?.status);
    if (status && status !== "active") continue;
    const id = positiveIntegerOrNull(item?.navigation_item_id);
    const targetPlannedPageId = positiveIntegerOrNull(item?.target_planned_page_id);
    const targetGeneratedPageId = positiveIntegerOrNull(item?.target_generated_page_id);
    const parentId = item?.parent_navigation_item_id == null
      ? null
      : positiveIntegerOrNull(item.parent_navigation_item_id);
    const position = nonNegativeIntegerOrNull(item?.position);
    const label = exactString(item?.label);
    const slug = exactString(item?.slug);
    if (
      !item ||
      id === null ||
      targetPlannedPageId === null ||
      targetGeneratedPageId === null ||
      position === null ||
      !label ||
      !slug ||
      (item.parent_navigation_item_id != null && parentId === null)
    ) {
      invalid = true;
      continue;
    }
    parsed.push(Object.freeze({
      id,
      targetPlannedPageId,
      targetGeneratedPageId,
      parentId,
      position,
      label,
    }));
  }
  const ids = parsed.map((item) => String(item.id));
  const targets = parsed.map((item) => String(item.targetPlannedPageId));
  if (duplicateValues(ids).length || duplicateValues(targets).length) invalid = true;
  const byId = new Map(parsed.map((item) => [item.id, item]));
  for (const item of parsed) {
    if (item.parentId === item.id || (item.parentId !== null && !byId.has(item.parentId))) {
      invalid = true;
    }
  }
  const visiting = new Set<number>();
  const visited = new Set<number>();
  function visit(item: NavigationIdentity): boolean {
    if (visiting.has(item.id)) return false;
    if (visited.has(item.id)) return true;
    visiting.add(item.id);
    if (item.parentId !== null) {
      const parent = byId.get(item.parentId);
      if (!parent || !visit(parent)) return false;
    }
    visiting.delete(item.id);
    visited.add(item.id);
    return true;
  }
  if (parsed.some((item) => !visit(item))) invalid = true;

  const siblings = new Map<number | null, NavigationIdentity[]>();
  for (const item of parsed) {
    const group = siblings.get(item.parentId) ?? [];
    group.push(item);
    siblings.set(item.parentId, group);
  }
  for (const group of siblings.values()) {
    if (duplicateValues(group.map((item) => String(item.position))).length) invalid = true;
    if (duplicateValues(group.map((item) => item.label.toLowerCase().replace(/\s+/g, " "))).length) {
      invalid = true;
    }
  }

  if (invalid) {
    addOwnershipMismatch(
      "navigation_resolved_tree_invalid",
      `Navigation component ${component.instance_key} has incomplete, duplicate, cyclic, or unordered active item identities.`,
      component.instance_key,
    );
  }
}

function selectorMatches(
  component: PageComponentInstance,
  selectorRule: PerformanceLocalV5ComponentSelector,
): boolean {
  if (component.component_key !== selectorRule.componentKey) return false;
  if (selectorRule.sectionKey === undefined) return true;
  return component.input_bindings.section_key === selectorRule.sectionKey;
}

function compareConsumption(
  left: PerformanceLocalV5ConsumptionRecord,
  right: PerformanceLocalV5ConsumptionRecord,
) {
  return left.sourcePosition - right.sourcePosition || left.instanceKey.localeCompare(right.instanceKey);
}

function collectSourceTargetIdentities(
  snapshot: Record<string, unknown> | null,
): ReadonlyMap<number, SourceTargetIdentity> {
  const result = new Map<number, SourceTargetIdentity>();
  const candidates: unknown[] = [];
  for (const item of asArray(snapshot?.navigation_items)) candidates.push(asRecord(item)?.target);
  for (const item of asArray(snapshot?.internal_links)) candidates.push(asRecord(item)?.target);
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

function collectMediaRequirements(value: unknown): ReadonlyMap<number, SourceMediaRequirement> {
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

function visitResolvedTargets(value: unknown, visit: (target: Record<string, unknown>) => void) {
  if (Array.isArray(value)) {
    for (const item of value) visitResolvedTargets(item, visit);
    return;
  }
  const record = asRecord(value);
  if (!record) return;
  if ("target_planned_page_id" in record) visit(record);
  for (const child of Object.values(record)) visitResolvedTargets(child, visit);
}

function attachMediaClaims(
  components: readonly PageComponentInstance[],
  componentByInstanceKey: ReadonlyMap<string, PageComponentInstance>,
  claims: ReadonlyMap<string, PerformanceLocalV5ConsumptionRecord>,
  claim: (
    component: PageComponentInstance,
    regionKey: PerformanceLocalV5RegionKey,
    mode: PerformanceLocalV5ConsumptionMode,
  ) => void,
  addBlocker: (blocker: PerformanceLocalV5Blocker) => void,
  diagnostics: PerformanceLocalV5Diagnostic[],
) {
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
          message: `Media placement target ${targetKey} is missing, is media, or has no exact V5 region claim.`,
          instanceKey: media.instance_key,
        });
      }
      continue;
    }
    if (mediaComponents.length !== 1) {
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
}

function validateAdjacentGroups(
  manifest: PerformanceLocalV5LayoutManifest,
  components: readonly PageComponentInstance[],
  claims: ReadonlyMap<string, PerformanceLocalV5ConsumptionRecord>,
  componentByInstanceKey: ReadonlyMap<string, PageComponentInstance>,
  sourceIndexByInstanceKey: ReadonlyMap<string, number>,
  addBlocker: (blocker: PerformanceLocalV5Blocker) => void,
) {
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
      groupingRule.groupKey === PERFORMANCE_LOCAL_V5_COUNTY_RELATED_CITY_GROUP_KEY &&
      grouped.length > 0
    ) {
      validateCountyRelatedCityComponentPair(
        grouped
          .map((record) => componentByInstanceKey.get(record.instanceKey))
          .filter((component): component is PageComponentInstance => Boolean(component)),
        addBlocker,
      );
    }
  }
}

function validateCountyRelatedCityComponentPair(
  components: readonly PageComponentInstance[],
  addBlocker: (blocker: PerformanceLocalV5Blocker) => void,
) {
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
      regionKey: "related_city_discovery",
    });
  }
}

function destinationProjection(
  pageType: PerformanceLocalV5PageType,
  componentByInstanceKey: ReadonlyMap<string, PageComponentInstance>,
  addBlocker: (blocker: PerformanceLocalV5Blocker) => void,
): DestinationProjectionResult {
  if (pageType === "home") {
    return projectHomeServices(componentByInstanceKey, addBlocker);
  }
  if (pageType === "county") {
    return projectCountyCities(componentByInstanceKey, addBlocker);
  }
  const destinationConsumption = contextualComponents(componentByInstanceKey)
    .flatMap((component) => parseDestinationLinks(component, addBlocker))
    .map((destination) => withDestinationSlot(destination, "related_destination"));
  return Object.freeze({
    destinationConsumption: Object.freeze(destinationConsumption),
    homeServicePresentation: emptyHomePresentation("not_applicable"),
    countyCityPresentation: emptyCountyPresentation("not_applicable"),
  });
}

function projectHomeServices(
  componentByInstanceKey: ReadonlyMap<string, PageComponentInstance>,
  addBlocker: (blocker: PerformanceLocalV5Blocker) => void,
): DestinationProjectionResult {
  const primary = findSectionComponent(componentByInstanceKey, "primary_services");
  const related = findComponent(componentByInstanceKey, "related_page_links");
  let valid = true;
  const fail = (blocker: PerformanceLocalV5Blocker) => {
    valid = false;
    addBlocker(blocker);
  };
  if (!primary || !related) {
    fail({
      code: "home_service_projection_source_missing",
      category: "layout",
      message: "Home service presentation requires the exact primary_services and related_page_links source instances.",
      regionKey: "service_discovery",
    });
  }

  const parsedServices: Array<Readonly<{
    sourceItemIndex: number;
    exactSourceItem: string;
    title: string;
    description: string;
  }>> = [];
  if (primary) {
    const heading = exactString(primary.resolved_data.heading);
    const body = exactString(primary.resolved_data.body);
    if (!heading || !body) {
      fail({
        code: "home_primary_services_source_invalid",
        category: "source",
        message: "Home primary_services requires one exact non-blank heading and source service list.",
        instanceKey: primary.instance_key,
        regionKey: "service_discovery",
      });
    } else {
      const sourceItems = body.split(/\r?\n/).filter((line) => line.trim().length > 0);
      for (const [sourceItemIndex, rawItem] of sourceItems.entries()) {
        const match = /^- ([^:\r\n]+): (.+)$/.exec(rawItem);
        if (!match || rawItem.trim() !== rawItem || !exactString(match[1]) || !exactString(match[2])) {
          fail({
            code: "home_primary_service_item_invalid",
            category: "source",
            message: `Home primary_services item ${sourceItemIndex} must be the exact '- Title: Description' source shape.`,
            instanceKey: primary.instance_key,
            regionKey: "service_discovery",
          });
          continue;
        }
        parsedServices.push(Object.freeze({
          sourceItemIndex,
          exactSourceItem: rawItem,
          title: match[1],
          description: match[2],
        }));
      }
      if (!sourceItems.length) {
        fail({
          code: "home_primary_services_empty",
          category: "source",
          message: "Home primary_services must contain at least one exact service item.",
          instanceKey: primary.instance_key,
          regionKey: "service_discovery",
        });
      }
      if (duplicateValues(parsedServices.map((item) => item.title)).length) {
        fail({
          code: "home_primary_service_title_duplicate",
          category: "source",
          message: "Home primary_services titles must be unique for an exact governed destination join.",
          instanceKey: primary.instance_key,
          regionKey: "service_discovery",
        });
      }
    }
  }

  const parsedLinks = related
    ? parseDestinationLinks(related, (blocker) => {
      valid = false;
      addBlocker(blocker);
    }, "home_related_destinations_invalid")
    : [];
  const usedLinkIndices = new Set<number>();
  const slot = parsedServices.length === 1 ? "featured_service" as const : "service_grid" as const;
  const services: PerformanceLocalV5HomeServiceEntry[] = [];
  for (const service of parsedServices) {
    const matches = parsedLinks.filter((destination) => destination.label === service.title);
    if (matches.length !== 1 || usedLinkIndices.has(matches[0]?.originalLinkIndex ?? -1)) {
      fail({
        code: "home_service_destination_match_invalid",
        category: "layout",
        message: `Home service '${service.title}' must match exactly one unused governed related-link label.`,
        instanceKey: related?.instance_key,
        regionKey: "service_discovery",
      });
      continue;
    }
    const destination = withDestinationSlot(matches[0], slot);
    usedLinkIndices.add(destination.originalLinkIndex);
    services.push(Object.freeze({
      ...service,
      matchedLinkIndex: destination.originalLinkIndex,
      destination,
    }));
  }
  const remainingDestinations = parsedLinks
    .filter((destination) => !usedLinkIndices.has(destination.originalLinkIndex))
    .map((destination) => withDestinationSlot(destination, "related_destination"));
  const destinationConsumption = valid
    ? [...services.map((item) => item.destination), ...remainingDestinations]
      .sort(compareDestinationConsumption)
    : [];
  const presentation: PerformanceLocalV5HomeServicePresentation = Object.freeze({
    status: valid ? "ready" as const : "blocked" as const,
    primaryServicesSourceInstanceKey: primary?.instance_key ?? null,
    relatedLinksSourceInstanceKey: related?.instance_key ?? null,
    mode: parsedServices.length === 0 ? null : parsedServices.length === 1 ? "featured" as const : "grid" as const,
    services: Object.freeze(services),
    remainingLinkIndices: Object.freeze(remainingDestinations.map((item) => item.originalLinkIndex)),
    remainingDestinations: Object.freeze(remainingDestinations),
  });
  return Object.freeze({
    destinationConsumption: Object.freeze(destinationConsumption),
    homeServicePresentation: presentation,
    countyCityPresentation: emptyCountyPresentation("not_applicable"),
  });
}

function projectCountyCities(
  componentByInstanceKey: ReadonlyMap<string, PageComponentInstance>,
  addBlocker: (blocker: PerformanceLocalV5Blocker) => void,
): DestinationProjectionResult {
  const citiesSource = findSectionComponent(componentByInstanceKey, "cities_served");
  const relatedSource = findSectionComponent(componentByInstanceKey, "related_city_services");
  const cards = findComponent(componentByInstanceKey, "destination_cards");
  let valid = true;
  const fail = (blocker: PerformanceLocalV5Blocker) => {
    valid = false;
    addBlocker(blocker);
  };
  if (!citiesSource || !relatedSource || !cards) {
    fail({
      code: "county_related_city_merge_component_mismatch",
      category: "layout",
      message: "County city presentation requires exact cities_served, related_city_services, and destination_cards source instances.",
      regionKey: "related_city_discovery",
    });
  }

  const cities: string[] = [];
  if (citiesSource) {
    const heading = exactString(citiesSource.resolved_data.heading);
    const body = exactString(citiesSource.resolved_data.body);
    if (!heading || !body) {
      fail({
        code: "county_cities_served_source_invalid",
        category: "source",
        message: "County cities_served requires one exact heading and one exact ordered city list.",
        instanceKey: citiesSource.instance_key,
        regionKey: "city_discovery",
      });
    } else {
      const values = body.split(", ");
      if (
        !values.length ||
        values.some((value) => !exactString(value)) ||
        values.join(", ") !== body ||
        duplicateValues(values).length
      ) {
        fail({
          code: "county_cities_served_source_invalid",
          category: "source",
          message: "County cities_served must be an exact comma-space-separated list of unique non-blank City names.",
          instanceKey: citiesSource.instance_key,
          regionKey: "city_discovery",
        });
      } else {
        cities.push(...values);
      }
    }
  }

  let relatedBody: string | null = null;
  if (relatedSource) {
    const heading = exactString(relatedSource.resolved_data.heading);
    relatedBody = exactString(relatedSource.resolved_data.body);
    if (!heading || !relatedBody) {
      fail({
        code: "county_related_city_merge_source_invalid",
        category: "source",
        message: "County related_city_services requires one exact heading and one exact non-blank source label list.",
        instanceKey: relatedSource.instance_key,
        regionKey: "related_city_discovery",
      });
    }
  }

  const parsedLinks = cards
    ? parseDestinationLinks(cards, (blocker) => {
      valid = false;
      addBlocker(blocker);
    }, "county_related_city_merge_destinations_invalid")
    : [];
  const matchingPrefixLengths = relatedBody
    ? parsedLinks
      .map((_, index) => index + 1)
      .filter((length) => parsedLinks.slice(0, length).map((item) => item.label).join(", ") === relatedBody)
    : [];
  let prefixCount = matchingPrefixLengths.length === 1 ? matchingPrefixLengths[0] : 0;
  if (relatedBody && matchingPrefixLengths.length !== 1) {
    fail({
      code: "county_related_city_merge_prefix_mismatch",
      category: "layout",
      message: "County related_city_services labels must exactly equal the ordered prefix of governed destination-card labels.",
      instanceKey: relatedSource?.instance_key,
      regionKey: "related_city_discovery",
    });
  }
  if (prefixCount > 0 && parsedLinks.length - prefixCount < 2) {
    fail({
      code: "county_related_city_merge_insufficient_remaining_destinations",
      category: "layout",
      message: "County destination cards must retain at least two governed destinations after the duplicated city-label prefix.",
      instanceKey: cards?.instance_key,
      regionKey: "related_city_discovery",
    });
  }
  if (prefixCount > 0 && prefixCount !== cities.length) {
    fail({
      code: "county_city_count_mismatch",
      category: "layout",
      message: "County cities_served count must exactly equal the governed related-city destination prefix count.",
      instanceKey: citiesSource?.instance_key,
      regionKey: "city_discovery",
    });
  }

  const cityEntries: PerformanceLocalV5CountyCityEntry[] = [];
  let governedRegionLabel: string | null = null;
  for (let index = 0; index < Math.min(prefixCount, cities.length); index += 1) {
    const cityName = cities[index];
    const rawDestination = parsedLinks[index];
    const locationMarker = ` in ${cityName}, `;
    const markerIndex = rawDestination.label.lastIndexOf(locationMarker);
    const serviceLabel = markerIndex > 0 ? rawDestination.label.slice(0, markerIndex) : "";
    const regionLabel = markerIndex > 0
      ? rawDestination.label.slice(markerIndex + locationMarker.length)
      : "";
    const exactGovernedLocation =
      markerIndex > 0 &&
      rawDestination.label.indexOf(locationMarker) === markerIndex &&
      serviceLabel.trim() === serviceLabel &&
      serviceLabel.length > 0 &&
      regionLabel.trim() === regionLabel &&
      regionLabel.length > 0;
    if (!exactGovernedLocation) {
      fail({
        code: "county_city_destination_mismatch",
        category: "layout",
        message: `County City '${cityName}' must match the exact ordered governed destination-label suffix.`,
        instanceKey: cards?.instance_key,
        regionKey: "city_discovery",
      });
    } else if (governedRegionLabel === null) {
      governedRegionLabel = regionLabel;
    } else if (regionLabel !== governedRegionLabel) {
      fail({
        code: "county_city_destination_region_mismatch",
        category: "layout",
        message: "County City destinations must use one exact source-governed region label.",
        instanceKey: cards?.instance_key,
        regionKey: "city_discovery",
      });
    }
    const destination = withDestinationSlot(rawDestination, "county_city");
    cityEntries.push(Object.freeze({
      cityIndex: index,
      cityName,
      originalLinkIndex: destination.originalLinkIndex,
      destination,
    }));
  }
  const partitionCount = prefixCount > 0 ? prefixCount : 0;
  const cityDestinations = parsedLinks
    .slice(0, partitionCount)
    .map((destination) => withDestinationSlot(destination, "county_city"));
  const remainingDestinations = parsedLinks
    .slice(partitionCount)
    .map((destination) => withDestinationSlot(destination, "related_destination"));
  const destinationConsumption = valid
    ? [...cityDestinations, ...remainingDestinations].sort(compareDestinationConsumption)
    : [];
  const validatedCityPrefixCount = valid && prefixCount === cities.length ? prefixCount : 0;
  const presentation: PerformanceLocalV5CountyCityPresentation = Object.freeze({
    status: valid ? "ready" as const : "blocked" as const,
    citiesServedSourceInstanceKey: citiesSource?.instance_key ?? null,
    relatedCityServicesSourceInstanceKey: relatedSource?.instance_key ?? null,
    destinationCardsSourceInstanceKey: cards?.instance_key ?? null,
    validatedCityPrefixCount,
    cityEntries: Object.freeze(cityEntries),
    remainingLinkIndices: Object.freeze(remainingDestinations.map((item) => item.originalLinkIndex)),
    remainingDestinations: Object.freeze(remainingDestinations),
  });
  return Object.freeze({
    destinationConsumption: Object.freeze(destinationConsumption),
    homeServicePresentation: emptyHomePresentation("not_applicable"),
    countyCityPresentation: presentation,
  });
}

function contextualComponents(
  componentByInstanceKey: ReadonlyMap<string, PageComponentInstance>,
): PageComponentInstance[] {
  return [...componentByInstanceKey.values()]
    .filter((component) =>
      component.component_key === "related_page_links" || component.component_key === "destination_cards",
    )
    .sort((left, right) => left.position - right.position || left.instance_key.localeCompare(right.instance_key));
}

function parseDestinationLinks(
  component: PageComponentInstance,
  addBlocker: (blocker: PerformanceLocalV5Blocker) => void,
  invalidCode = "contextual_destination_entry_invalid",
): ParsedDestination[] {
  const rawLinks = component.resolved_data.links;
  if (!Array.isArray(rawLinks)) {
    addBlocker({
      code: invalidCode,
      category: "source",
      message: `Contextual destination source ${component.instance_key} requires an exact links array.`,
      instanceKey: component.instance_key,
    });
    return [];
  }
  const result: ParsedDestination[] = [];
  for (const [originalLinkIndex, rawLink] of rawLinks.entries()) {
    const link = asRecord(rawLink);
    const label = exactString(link?.label);
    const purpose = exactString(link?.purpose);
    const slug = exactString(link?.slug);
    const targetPlannedPageId = positiveIntegerOrNull(link?.target_planned_page_id);
    const targetGeneratedPageId = positiveIntegerOrNull(link?.target_generated_page_id);
    if (!link || !label || !purpose || !slug || targetPlannedPageId === null || targetGeneratedPageId === null) {
      addBlocker({
        code: invalidCode,
        category: "source",
        message: `Contextual destination entry ${component.instance_key}[${originalLinkIndex}] lacks an exact label, purpose, slug, or governed target identity.`,
        instanceKey: component.instance_key,
      });
      continue;
    }
    result.push(Object.freeze({
      sourceInstanceKey: component.instance_key,
      originalLinkIndex,
      presentationSlot: "related_destination" as const,
      label,
      purpose,
      slug,
      targetPlannedPageId,
      targetGeneratedPageId,
    }));
  }
  const duplicateIdentity = [
    ...duplicateValues(result.map((item) => item.label)),
    ...duplicateValues(result.map((item) => item.slug)),
    ...duplicateValues(result.map((item) => String(item.targetPlannedPageId))),
    ...duplicateValues(result.map((item) => String(item.targetGeneratedPageId))),
  ];
  if (duplicateIdentity.length) {
    addBlocker({
      code: invalidCode,
      category: "source",
      message: `Contextual destination source ${component.instance_key} requires unique labels, slugs, and complete governed target identities.`,
      instanceKey: component.instance_key,
    });
  }
  return result;
}

function withDestinationSlot(
  destination: ParsedDestination,
  presentationSlot: PerformanceLocalV5DestinationPresentationSlot,
): PerformanceLocalV5DestinationConsumptionRecord {
  return Object.freeze({ ...destination, presentationSlot });
}

function compareDestinationConsumption(
  left: PerformanceLocalV5DestinationConsumptionRecord,
  right: PerformanceLocalV5DestinationConsumptionRecord,
) {
  return left.sourceInstanceKey.localeCompare(right.sourceInstanceKey) ||
    left.originalLinkIndex - right.originalLinkIndex;
}

function findSectionComponent(
  components: ReadonlyMap<string, PageComponentInstance>,
  sectionKey: string,
): PageComponentInstance | null {
  return [...components.values()].find((component) =>
    component.component_key === "content_section" && component.input_bindings.section_key === sectionKey,
  ) ?? null;
}

function findComponent(
  components: ReadonlyMap<string, PageComponentInstance>,
  componentKey: string,
): PageComponentInstance | null {
  return [...components.values()].find((component) => component.component_key === componentKey) ?? null;
}

function validateProgressiveDisclosureSources(
  pageType: PerformanceLocalV5PageType,
  componentByInstanceKey: ReadonlyMap<string, PageComponentInstance>,
  addBlocker: (blocker: PerformanceLocalV5Blocker) => void,
) {
  const disclosureSections = pageType === "service"
    ? ["approved_guidance"]
    : pageType === "county"
      ? ["customer_expectations"]
      : [];
  for (const sectionKey of disclosureSections) {
    const component = findSectionComponent(componentByInstanceKey, sectionKey);
    if (!component) continue;
    const heading = exactString(component.resolved_data.heading);
    const body = exactString(component.resolved_data.body);
    if (!heading || !body || !structuredDisclosureBodyIsValid(body)) {
      addBlocker({
        code: "progressive_disclosure_source_invalid",
        category: "source",
        message: `${sectionKey} must preserve one exact heading and complete source-defined '### Heading' disclosure groups.`,
        instanceKey: component.instance_key,
        regionKey: sectionKey === "approved_guidance" ? "approved_guidance" : "customer_expectations",
      });
    }
  }
  if (pageType === "service" || pageType === "county" || pageType === "faq") {
    const faq = findComponent(componentByInstanceKey, "faq");
    if (!faq) return;
    const rawItems = faq.resolved_data.items;
    const items = Array.isArray(rawItems) ? rawItems : [];
    const questions: string[] = [];
    const validItems = Array.isArray(rawItems) && items.length > 0 && items.every((item) => {
      const record = asRecord(item);
      const question = exactString(record?.question);
      const answer = exactString(record?.answer);
      if (question) questions.push(question);
      return Boolean(record && question && answer);
    });
    if (!validItems || duplicateValues(questions).length) {
      addBlocker({
        code: "faq_disclosure_source_invalid",
        category: "source",
        message: "FAQ progressive disclosure requires ordered unique exact question/answer source items.",
        instanceKey: faq.instance_key,
        regionKey: "faq",
      });
    }
  }
}

function structuredDisclosureBodyIsValid(body: string): boolean {
  const lines = body.split(/\r?\n/);
  const headings = new Set<string>();
  let groupCount = 0;
  let currentGroupHasContent = false;
  let currentGroupOpen = false;
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;
    const headingMatch = /^###\s+(.+)$/.exec(line);
    if (headingMatch) {
      if (currentGroupOpen && !currentGroupHasContent) return false;
      const heading = exactString(headingMatch[1].trim());
      if (!heading || headings.has(heading)) return false;
      headings.add(heading);
      groupCount += 1;
      currentGroupOpen = true;
      currentGroupHasContent = false;
      continue;
    }
    if (!currentGroupOpen || /^#{1,6}\s/.test(line)) return false;
    currentGroupHasContent = true;
  }
  return groupCount > 0 && currentGroupHasContent;
}

function contextualEntryKeys(components: readonly PageComponentInstance[]): string[] {
  return [...components]
    .filter((component) =>
      component.component_key === "related_page_links" || component.component_key === "destination_cards",
    )
    .sort((left, right) => left.position - right.position || left.instance_key.localeCompare(right.instance_key))
    .flatMap((component) => Array.isArray(component.resolved_data.links)
      ? component.resolved_data.links.map((_, originalLinkIndex) =>
        `${component.instance_key}:${originalLinkIndex}`,
      )
      : []);
}

function destinationEntryKey(
  destination: PerformanceLocalV5DestinationConsumptionRecord,
): string {
  return `${destination.sourceInstanceKey}:${destination.originalLinkIndex}`;
}

function emptyHomePresentation(
  status: "blocked" | "not_applicable",
): PerformanceLocalV5HomeServicePresentation {
  return Object.freeze({
    status,
    primaryServicesSourceInstanceKey: null,
    relatedLinksSourceInstanceKey: null,
    mode: null,
    services: Object.freeze([]),
    remainingLinkIndices: Object.freeze([]),
    remainingDestinations: Object.freeze([]),
  });
}

function emptyCountyPresentation(
  status: "blocked" | "not_applicable",
): PerformanceLocalV5CountyCityPresentation {
  return Object.freeze({
    status,
    citiesServedSourceInstanceKey: null,
    relatedCityServicesSourceInstanceKey: null,
    destinationCardsSourceInstanceKey: null,
    validatedCityPrefixCount: 0,
    cityEntries: Object.freeze([]),
    remainingLinkIndices: Object.freeze([]),
    remainingDestinations: Object.freeze([]),
  });
}

function renderableMediaSource(component: PageComponentInstance): boolean {
  const source = exactString(component.resolved_data.asset_url);
  const alt = exactString(component.resolved_data.alt_text);
  if (!source || !alt) return false;
  if (source.startsWith("/") && !source.startsWith("//")) return true;
  try {
    const url = new URL(source);
    return (url.protocol === "http:" || url.protocol === "https:") &&
      !url.username &&
      !url.password &&
      ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  } catch {
    return false;
  }
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

function nonNegativeIntegerOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
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
