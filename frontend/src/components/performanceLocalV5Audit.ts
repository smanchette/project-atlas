import type {
  GeneratedPage,
  PageComposition,
  PageMediaPlanningWorkspace,
  PlannedPage,
} from "../types";
import {
  auditPerformanceLocalV5Composition,
  type PerformanceLocalV5Blocker,
  type PerformanceLocalV5LayoutAudit,
  type PerformanceLocalV5LayoutKey,
  type PerformanceLocalV5PageType,
} from "./performanceLocalV5LayoutContract";
import {
  PERFORMANCE_LOCAL_V5_FORM_FIELD_CONTRACT,
  PERFORMANCE_LOCAL_V5_THEME,
} from "./performanceLocalThemeV5";
import {
  PERFORMANCE_LOCAL_V3_RENDERER_CONTRACT,
  PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY,
} from "./performanceLocalThemeV3";
import {
  auditPerformanceLocalV4Page41Preservation,
  PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION,
  type PerformanceLocalV4Page41PreservationResult,
} from "./performanceLocalV4Audit";

export const PERFORMANCE_LOCAL_V5_CURRENT_SITE_EXPECTATION = Object.freeze({
  pageCount: 65 as const,
  sourceComponentCount: 1_165 as const,
  pageTypeDistribution: Object.freeze({
    home: 1,
    service: 1,
    county: 5,
    city_service: 55,
    about: 1,
    contact: 1,
    faq: 1,
  } satisfies Readonly<Record<PerformanceLocalV5PageType, number>>),
});

/**
 * Page 41 remains governed by the immutable approved V4 preservation control.
 * V5 reuses the frozen expectation by reference and does not relabel or fork it.
 */
export const PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION =
  PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION;
export type PerformanceLocalV5ConversionAuditEvidence = Readonly<{
  sourceThemeCompatibility: string;
  sourceRendererContract: string;
  bannerState: "enabled" | "disabled" | "blocked";
  bannerPhraseCount: number;
  formState: "provider_disabled" | "blocked" | "production_configured";
  formFieldCount: number;
  optionalFormFieldCount: number;
  maximumFormFieldCount: number;
  formCanSubmit: boolean;
  formCollectsData: boolean;
  stickyActionState: "configured" | "disabled" | "blocked";
}>;

export type PerformanceLocalV5ConversionAuditResult = Readonly<{
  safePreviewContract: boolean;
  rendererReady: boolean;
  blockers: readonly PerformanceLocalV5SiteAuditBlocker[];
}>;

export type PerformanceLocalV5Page41PreservationResult =
  PerformanceLocalV4Page41PreservationResult;
export type PerformanceLocalV5SiteAuditInput = Readonly<{
  websiteId: number;
  sitePlanId: number;
  plannedPages: readonly PlannedPage[];
  generatedPages: readonly GeneratedPage[];
  compositions: readonly PageComposition[];
  mediaWorkspace: PageMediaPlanningWorkspace;
  conversionEvidence: PerformanceLocalV5ConversionAuditEvidence;
  expectedPageCount?: 65;
}>;

export type PerformanceLocalV5SiteAuditBlocker = Readonly<{
  code: string;
  category:
    | "input"
    | "scope"
    | "layout"
    | "media"
    | "qa"
    | "form"
    | "activation"
    | "export"
    | "publication";
  reason: string;
}>;

export type PerformanceLocalV5SiteAuditRow = Readonly<{
  plannedPageId: number;
  generatedPageId: number | null;
  pageType: string;
  selectedLayoutKey: PerformanceLocalV5LayoutKey | null;
  layoutCompatibility: string | null;
  sourceComponentCount: number;
  consumedComponentCount: number;
  destinationConsumption: PerformanceLocalV5LayoutAudit["destinationConsumption"];
  homeServicePresentation: PerformanceLocalV5LayoutAudit["homeServicePresentation"] | null;
  countyCityPresentation: PerformanceLocalV5LayoutAudit["countyCityPresentation"] | null;
  unconsumedSourceComponents: readonly string[];
  duplicatedSourceComponents: readonly string[];
  unconsumedDestinationEntries: readonly string[];
  duplicatedDestinationEntries: readonly string[];
  missingRequiredSemanticRegions: readonly string[];
  missingOptionalSemanticRegions: readonly string[];
  mediaReadiness: "ready" | "blocked";
  qaReadiness: "ready" | "blocked";
  formState: PerformanceLocalV5ConversionAuditEvidence["formState"];
  bannerState: PerformanceLocalV5ConversionAuditEvidence["bannerState"];
  stickyActionState: PerformanceLocalV5ConversionAuditEvidence["stickyActionState"];
  truthfulRendererResult: "ready" | "blocked";
  structuralDemoRendererResult: "ready" | "blocked";
  publicExportEligibility: false;
  layoutReady: boolean;
  mediaReady: boolean;
  qaReady: boolean;
  formContractSafe: boolean;
  formReady: false;
  activationReady: false;
  exportReady: false;
  publicationReady: false;
  sourceContentIdentity: Readonly<{
    compositionId: number | null;
    compositionVersion: number | null;
    compositionSourceHash: string | null;
  }>;
  layoutAudit: PerformanceLocalV5LayoutAudit | null;
  blockerList: readonly PerformanceLocalV5SiteAuditBlocker[];
}>;

export type PerformanceLocalV5FullSiteAudit = Readonly<{
  status: "ready" | "blocked";
  sourceIdentity: Readonly<{
    websiteId: number;
    sitePlanId: number;
    expectedPageCount: 65;
    expectedSourceComponentCount: 1_165;
    themeFamilyKey: "performance-local";
    themeVersion: 5;
    lifecycleStatus: "preview_candidate";
    productionReady: false;
    themeCompatibilityIdentity: string;
    rendererContract: string;
    diagnosticIdentity: string;
    durableV5Registration: "absent_by_design";
    activeV5Selection: "absent_by_design";
  }>;
  counts: Readonly<{
    evaluatedPages: number;
    sourceComponents: number;
    consumedComponents: number;
    layoutReadyPages: number;
    mediaReadyPages: number;
    qaReadyPages: number;
    formReadyPages: 0;
    activationReadyPages: 0;
    exportReadyPages: 0;
    publicationReadyPages: 0;
    pageTypeDistribution: Readonly<Record<PerformanceLocalV5PageType, number>>;
  }>;
  pages: readonly PerformanceLocalV5SiteAuditRow[];
  page41Preservation: PerformanceLocalV5Page41PreservationResult | null;
  blockers: readonly PerformanceLocalV5SiteAuditBlocker[];
}>;

export function auditPerformanceLocalV5Page41Preservation(input: Readonly<{
  page: GeneratedPage;
  plannedPage: PlannedPage;
  composition: PageComposition;
  mediaWorkspace: PageMediaPlanningWorkspace;
}>): PerformanceLocalV5Page41PreservationResult {
  return auditPerformanceLocalV4Page41Preservation(input);
}
export function auditPerformanceLocalV5FullSite(
  input: PerformanceLocalV5SiteAuditInput,
): PerformanceLocalV5FullSiteAudit {
  const siteBlockers: PerformanceLocalV5SiteAuditBlocker[] = [];
  const plannedPages = [...input.plannedPages].sort((left, right) => left.id - right.id);
  uniqueIndex(plannedPages, (item) => item.id, "planned_page", siteBlockers);
  const generatedById = uniqueIndex(input.generatedPages, (item) => item.id, "generated_page", siteBlockers);
  const compositionByPlannedId = uniqueIndex(
    input.compositions,
    (item) => item.planned_page_id,
    "page_composition",
    siteBlockers,
  );
  const conversion = auditPerformanceLocalV5ConversionEvidence(input.conversionEvidence);

  if ((input.expectedPageCount ?? 65) !== 65 || plannedPages.length !== 65) {
    siteBlockers.push(blocker(
      "full_site_page_count_mismatch",
      "input",
      `The V5 current-site audit requires exactly 65 Planned Pages; received ${plannedPages.length}.`,
    ));
  }
  if (input.generatedPages.length !== 65) {
    siteBlockers.push(blocker(
      "full_site_generated_page_count_mismatch",
      "input",
      `The V5 current-site audit requires exactly 65 Generated Pages; received ${input.generatedPages.length}.`,
    ));
  }
  if (input.compositions.length !== 65) {
    siteBlockers.push(blocker(
      "full_site_composition_count_mismatch",
      "input",
      `The V5 current-site audit requires exactly 65 Page Compositions; received ${input.compositions.length}.`,
    ));
  }
  uniqueIndex(input.compositions, (item) => item.id, "page_composition_record", siteBlockers);
  if (input.compositions.some((item) => item.status !== "current" || item.validation_errors.length)) {
    siteBlockers.push(blocker(
      "full_site_composition_not_current",
      "input",
      "Every full-site Composition must be current with zero validation errors.",
    ));
  }
  if (
    input.mediaWorkspace.website_id !== input.websiteId ||
    input.mediaWorkspace.site_plan_id !== input.sitePlanId
  ) {
    siteBlockers.push(blocker(
      "media_workspace_scope_mismatch",
      "scope",
      "The Page Media workspace crosses the audited Website or Site Plan boundary.",
    ));
  }

  const rows: PerformanceLocalV5SiteAuditRow[] = [];
  const usedGeneratedIds = new Set<number>();
  const usedCompositionIds = new Set<number>();
  let page41Preservation: PerformanceLocalV5Page41PreservationResult | null = null;
  for (const plannedPage of plannedPages) {
    if (plannedPage.website_id !== input.websiteId || plannedPage.site_plan_id !== input.sitePlanId) {
      siteBlockers.push(blocker(
        "planned_page_scope_mismatch",
        "scope",
        `Planned Page ${plannedPage.id} crosses the audited Website or Site Plan boundary.`,
      ));
    }
    const generatedPage = plannedPage.generated_page_id
      ? generatedById.get(plannedPage.generated_page_id) ?? null
      : null;
    const composition = compositionByPlannedId.get(plannedPage.id) ?? null;
    if (!generatedPage || !composition) {
      rows.push(blockedJoinRow(plannedPage, generatedPage, composition, input.conversionEvidence));
      continue;
    }
    if (usedGeneratedIds.has(generatedPage.id)) {
      siteBlockers.push(blocker(
        "full_site_generated_page_not_bijective",
        "input",
        `Generated Page ${generatedPage.id} is joined to more than one Planned Page.`,
      ));
    }
    if (usedCompositionIds.has(composition.id)) {
      siteBlockers.push(blocker(
        "full_site_composition_not_bijective",
        "input",
        `Page Composition ${composition.id} is joined to more than one Planned Page.`,
      ));
    }
    usedGeneratedIds.add(generatedPage.id);
    usedCompositionIds.add(composition.id);

    const layoutAudit = auditPerformanceLocalV5Composition({
      page: generatedPage,
      plannedPage,
      composition,
    });
    const pageBlockers = layoutBlockers(layoutAudit.blockers);
    const media = mediaAudit(input.mediaWorkspace, plannedPage.id);
    const qa = qaAudit(generatedPage, composition, plannedPage);
    pageBlockers.push(...media.blockers, ...qa.blockers, ...conversion.blockers);
    let rowPage41Preservation: PerformanceLocalV5Page41PreservationResult | null = null;
    if (generatedPage.id === PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId) {
      page41Preservation = auditPerformanceLocalV5Page41Preservation({
        page: generatedPage,
        plannedPage,
        composition,
        mediaWorkspace: input.mediaWorkspace,
      });
      rowPage41Preservation = page41Preservation;
      pageBlockers.push(...page41Preservation.blockers);
    }
    const layoutReady = layoutAudit.layoutReady &&
      (rowPage41Preservation?.contentIdentityPreserved ?? true);
    const mediaReady = media.ready &&
      (rowPage41Preservation?.governedMediaIdentityPreserved ?? true);
    const qaReady = qa.ready &&
      (rowPage41Preservation?.contentIdentityPreserved ?? true);
    const page41RendererReady = rowPage41Preservation?.preserved ?? true;
    pageBlockers.push(
      blocker(
        "v5_not_durably_registered",
        "activation",
        "Performance Local V5 is source-only and has no durable Theme registration or selection.",
      ),
      blocker(
        "v5_preview_candidate_not_production_ready",
        "activation",
        "Performance Local V5 remains preview_candidate with productionReady false.",
      ),
      blocker(
        "v5_public_export_not_authorized",
        "export",
        "A source-only V5 layout has no governed public export identity.",
      ),
      blocker(
        "v5_publication_not_authorized",
        "publication",
        "This review grants no publication or activation authority.",
      ),
    );

    rows.push(deepFreeze({
      plannedPageId: plannedPage.id,
      generatedPageId: generatedPage.id,
      pageType: generatedPage.page_type,
      selectedLayoutKey: layoutAudit.layoutKey,
      layoutCompatibility: layoutAudit.layoutKey ? layoutAudit.compatibilityIdentity : null,
      sourceComponentCount: layoutAudit.sourceComponentCount,
      consumedComponentCount: layoutAudit.consumedComponentCount,
      destinationConsumption: layoutAudit.destinationConsumption,
      homeServicePresentation: layoutAudit.homeServicePresentation,
      countyCityPresentation: layoutAudit.countyCityPresentation,
      unconsumedSourceComponents: layoutAudit.unconsumedSourceInstanceKeys,
      duplicatedSourceComponents: layoutAudit.duplicatedSourceInstanceKeys,
      unconsumedDestinationEntries: layoutAudit.unconsumedDestinationEntryKeys,
      duplicatedDestinationEntries: layoutAudit.duplicatedDestinationEntryKeys,
      missingRequiredSemanticRegions: layoutAudit.missingRequiredRegionKeys,
      missingOptionalSemanticRegions: layoutAudit.missingOptionalRegionKeys,
      mediaReadiness: mediaReady ? "ready" as const : "blocked" as const,
      qaReadiness: qaReady ? "ready" as const : "blocked" as const,
      formState: input.conversionEvidence.formState,
      bannerState: input.conversionEvidence.bannerState,
      stickyActionState: input.conversionEvidence.stickyActionState,
      truthfulRendererResult: page41RendererReady
        ? layoutAudit.truthfulRendererResult
        : "blocked" as const,
      structuralDemoRendererResult: page41RendererReady
        ? layoutAudit.structuralDemoRendererResult
        : "blocked" as const,
      publicExportEligibility: false as const,
      layoutReady,
      mediaReady,
      qaReady,
      formContractSafe: conversion.safePreviewContract,
      formReady: false as const,
      activationReady: false as const,
      exportReady: false as const,
      publicationReady: false as const,
      sourceContentIdentity: Object.freeze({
        compositionId: layoutAudit.sourceIdentity.compositionId,
        compositionVersion: layoutAudit.sourceIdentity.compositionVersion,
        compositionSourceHash: layoutAudit.sourceIdentity.compositionSourceHash,
      }),
      layoutAudit,
      blockerList: uniqueBlockers(pageBlockers),
    }));
  }

  const distribution = emptyDistribution();
  for (const row of rows) {
    if (isV5PageType(row.pageType)) distribution[row.pageType] += 1;
  }
  for (const pageType of Object.keys(PERFORMANCE_LOCAL_V5_CURRENT_SITE_EXPECTATION.pageTypeDistribution) as PerformanceLocalV5PageType[]) {
    const expected = PERFORMANCE_LOCAL_V5_CURRENT_SITE_EXPECTATION.pageTypeDistribution[pageType];
    if (distribution[pageType] !== expected) {
      siteBlockers.push(blocker(
        "current_page_type_distribution_mismatch",
        "input",
        `Expected ${expected} ${pageType} page(s); received ${distribution[pageType]}.`,
      ));
    }
  }

  const sourceComponents = rows.reduce((total, row) => total + row.sourceComponentCount, 0);
  const consumedComponents = rows.reduce((total, row) => total + row.consumedComponentCount, 0);
  if (sourceComponents !== PERFORMANCE_LOCAL_V5_CURRENT_SITE_EXPECTATION.sourceComponentCount) {
    siteBlockers.push(blocker(
      "current_source_component_count_mismatch",
      "input",
      `Expected 1,165 source components; received ${sourceComponents}.`,
    ));
  }
  if (consumedComponents !== PERFORMANCE_LOCAL_V5_CURRENT_SITE_EXPECTATION.sourceComponentCount) {
    siteBlockers.push(blocker(
      "current_consumed_component_count_mismatch",
      "layout",
      `Expected 1,165 exactly-once consumed source components; received ${consumedComponents}.`,
    ));
  }
  if (rows.some((row) => !row.layoutReady)) {
    siteBlockers.push(blocker(
      "full_site_layout_not_ready",
      "layout",
      "One or more current pages failed the exact V5 layout/consumption audit.",
    ));
  }
  if (!page41Preservation) {
    siteBlockers.push(blocker(
      "page_41_preservation_input_missing",
      "input",
      "The exact 65-page audit must include Generated Page 41 and its preservation evidence.",
    ));
  }
  if (rows.length !== plannedPages.length) {
    siteBlockers.push(blocker(
      "full_site_evaluation_incomplete",
      "input",
      "The V5 audit did not produce one deterministic row per Planned Page.",
    ));
  }
  const unjoinedGeneratedIds = input.generatedPages
    .map((item) => item.id)
    .filter((id) => !usedGeneratedIds.has(id));
  const unjoinedCompositionIds = input.compositions
    .map((item) => item.id)
    .filter((id) => !usedCompositionIds.has(id));
  if (
    usedGeneratedIds.size !== 65 ||
    usedCompositionIds.size !== 65 ||
    unjoinedGeneratedIds.length ||
    unjoinedCompositionIds.length
  ) {
    siteBlockers.push(blocker(
      "full_site_inputs_not_bijective",
      "input",
      `The 65 Planned, Generated, and Composition identities must form one exact bijection; unjoined Generated IDs [${unjoinedGeneratedIds.join(", ")}], unjoined Composition IDs [${unjoinedCompositionIds.join(", ")}].`,
    ));
  }

  const counts = Object.freeze({
    evaluatedPages: rows.length,
    sourceComponents,
    consumedComponents,
    layoutReadyPages: rows.filter((row) => row.layoutReady).length,
    mediaReadyPages: rows.filter((row) => row.mediaReady).length,
    qaReadyPages: rows.filter((row) => row.qaReady).length,
    formReadyPages: 0 as const,
    activationReadyPages: 0 as const,
    exportReadyPages: 0 as const,
    publicationReadyPages: 0 as const,
    pageTypeDistribution: Object.freeze({ ...distribution }),
  });

  return deepFreeze({
    status: siteBlockers.length || rows.some((row) => row.blockerList.length)
      ? "blocked" as const
      : "ready" as const,
    sourceIdentity: Object.freeze({
      websiteId: input.websiteId,
      sitePlanId: input.sitePlanId,
      expectedPageCount: 65 as const,
      expectedSourceComponentCount: 1_165 as const,
      themeFamilyKey: PERFORMANCE_LOCAL_V5_THEME.key,
      themeVersion: PERFORMANCE_LOCAL_V5_THEME.version,
      lifecycleStatus: PERFORMANCE_LOCAL_V5_THEME.status,
      productionReady: PERFORMANCE_LOCAL_V5_THEME.productionReady,
      themeCompatibilityIdentity: PERFORMANCE_LOCAL_V5_THEME.compatibilityIdentity,
      rendererContract: PERFORMANCE_LOCAL_V5_THEME.rendererContract,
      diagnosticIdentity: PERFORMANCE_LOCAL_V5_THEME.diagnosticIdentity,
      durableV5Registration: PERFORMANCE_LOCAL_V5_THEME.durableRegistration,
      activeV5Selection: PERFORMANCE_LOCAL_V5_THEME.activeSelection,
    }),
    counts,
    pages: rows,
    page41Preservation,
    blockers: uniqueBlockers(siteBlockers),
  });
}

export function auditPerformanceLocalV5ConversionEvidence(
  evidence: PerformanceLocalV5ConversionAuditEvidence,
): PerformanceLocalV5ConversionAuditResult {
  const blockers: PerformanceLocalV5SiteAuditBlocker[] = [];
  if (
    evidence.sourceThemeCompatibility !== PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY ||
    evidence.sourceRendererContract !== PERFORMANCE_LOCAL_V3_RENDERER_CONTRACT
  ) {
    blockers.push(blocker(
      "governed_conversion_identity_mismatch",
      "form",
      "V5 may consume only the exact immutable V3 conversion identity without relabeling it.",
    ));
  }
  if (
    evidence.bannerState === "blocked" ||
    (evidence.bannerState === "enabled" && evidence.bannerPhraseCount !== 1) ||
    (evidence.bannerState === "disabled" && evidence.bannerPhraseCount !== 0)
  ) {
    blockers.push(blocker(
      "banner_state_not_truthful",
      "form",
      "The governed banner must render one Request an Estimate phrase when enabled and no gap/phrase when disabled.",
    ));
  }
  if (
    evidence.formState !== "provider_disabled" ||
    evidence.formFieldCount !== PERFORMANCE_LOCAL_V5_FORM_FIELD_CONTRACT.defaultCustomerEntryFieldCount ||
    evidence.optionalFormFieldCount !== PERFORMANCE_LOCAL_V5_FORM_FIELD_CONTRACT.activeOptionalFieldCount ||
    evidence.maximumFormFieldCount !== PERFORMANCE_LOCAL_V5_FORM_FIELD_CONTRACT.maximumCustomerEntryFieldCount ||
    evidence.formCanSubmit ||
    evidence.formCollectsData
  ) {
    blockers.push(blocker(
      "form_preview_contract_mismatch",
      "form",
      "The V5 form preview must remain provider-disabled, non-collecting, five-default, zero-optional, and six-maximum.",
    ));
  }
  if (evidence.stickyActionState === "blocked") {
    blockers.push(blocker(
      "sticky_action_contract_blocked",
      "form",
      "Mobile sticky actions did not preserve their governed interaction safety contract.",
    ));
  }
  blockers.push(blocker(
    "form_provider_disabled",
    "form",
    "The exact safe preview form is not production-ready because its provider remains disabled.",
  ));
  const safePreviewContract = blockers.every((item) => item.code === "form_provider_disabled");
  return deepFreeze({
    safePreviewContract,
    rendererReady: safePreviewContract,
    blockers,
  });
}

function mediaAudit(workspace: PageMediaPlanningWorkspace, plannedPageId: number) {
  const placements = workspace.placements.filter(
    (item) => item.planned_page.id === plannedPageId,
  );
  const blockers: PerformanceLocalV5SiteAuditBlocker[] = [];
  if (!placements.length) {
    blockers.push(blocker(
      "page_media_plan_missing",
      "media",
      "No current Page Media placement set exists for this Planned Page.",
    ));
  }
  for (const placement of placements) {
    for (const reason of placement.blocking_reasons) {
      blockers.push(blocker("page_media_blocked", "media", reason));
    }
    if (!placement.effective_requirement || placement.composition_status === "stale") {
      blockers.push(blocker(
        "page_media_identity_not_current",
        "media",
        "A Page Media placement or its exact target Composition is not current.",
      ));
    }
  }
  return { ready: blockers.length === 0, blockers };
}

function qaAudit(
  page: GeneratedPage,
  composition: PageComposition,
  plannedPage: PlannedPage,
) {
  const result = page.qa_result;
  const blockers: PerformanceLocalV5SiteAuditBlocker[] = [];
  if (
    page.qa_status !== "ready" ||
    !result ||
    result.readiness_status !== "ready" ||
    result.lifecycle_status !== "current" ||
    result.currentness_status !== "current_exact_identity_match" ||
    !result.persisted ||
    result.page_id !== page.id ||
    result.website_id !== composition.website_id ||
    result.site_plan_id !== composition.site_plan_id ||
    result.planned_page_id !== plannedPage.id ||
    result.page_composition_id !== composition.id ||
    result.composition_version !== composition.composition_version ||
    result.composition_source_hash !== composition.source_hash
  ) {
    blockers.push(blocker(
      "qa_identity_not_current",
      "qa",
      "Generated Page QA is missing, blocked, stale, or not bound to the exact current Composition identity.",
    ));
  }
  return { ready: blockers.length === 0, blockers };
}

function blockedJoinRow(
  plannedPage: PlannedPage,
  page: GeneratedPage | null,
  composition: PageComposition | null,
  conversion: PerformanceLocalV5ConversionAuditEvidence,
): PerformanceLocalV5SiteAuditRow {
  return deepFreeze({
    plannedPageId: plannedPage.id,
    generatedPageId: page?.id ?? plannedPage.generated_page_id ?? null,
    pageType: page?.page_type ?? plannedPage.page_type,
    selectedLayoutKey: null,
    layoutCompatibility: null,
    sourceComponentCount: composition?.effective_components.length ?? 0,
    consumedComponentCount: 0,
    destinationConsumption: [],
    homeServicePresentation: null,
    countyCityPresentation: null,
    unconsumedSourceComponents: composition?.effective_components.map((item) => item.instance_key) ?? [],
    duplicatedSourceComponents: [],
    unconsumedDestinationEntries: [],
    duplicatedDestinationEntries: [],
    missingRequiredSemanticRegions: [],
    missingOptionalSemanticRegions: [],
    mediaReadiness: "blocked" as const,
    qaReadiness: "blocked" as const,
    formState: conversion.formState,
    bannerState: conversion.bannerState,
    stickyActionState: conversion.stickyActionState,
    truthfulRendererResult: "blocked" as const,
    structuralDemoRendererResult: "blocked" as const,
    publicExportEligibility: false as const,
    layoutReady: false,
    mediaReady: false,
    qaReady: false,
    formContractSafe: false,
    formReady: false as const,
    activationReady: false as const,
    exportReady: false as const,
    publicationReady: false as const,
    sourceContentIdentity: Object.freeze({
      compositionId: composition?.id ?? null,
      compositionVersion: composition?.composition_version ?? null,
      compositionSourceHash: composition?.source_hash ?? null,
    }),
    layoutAudit: null,
    blockerList: [blocker(
      "full_site_page_join_missing",
      "input",
      "The Planned Page lacks its exact Generated Page or current Composition input.",
    )],
  });
}

function layoutBlockers(
  values: readonly PerformanceLocalV5Blocker[],
): PerformanceLocalV5SiteAuditBlocker[] {
  return values.map((item) => blocker(item.code, "layout", item.message));
}

function uniqueIndex<T>(
  values: readonly T[],
  key: (value: T) => number,
  label: string,
  blockers: PerformanceLocalV5SiteAuditBlocker[],
): ReadonlyMap<number, T> {
  const result = new Map<number, T>();
  for (const value of values) {
    const id = key(value);
    if (result.has(id)) {
      blockers.push(blocker(
        "duplicate_full_site_input_identity",
        "input",
        `The full-site audit received duplicate ${label} identity ${id}.`,
      ));
    } else {
      result.set(id, value);
    }
  }
  return result;
}

function blocker(
  code: string,
  category: PerformanceLocalV5SiteAuditBlocker["category"],
  reason: string,
): PerformanceLocalV5SiteAuditBlocker {
  return Object.freeze({ code, category, reason });
}

function uniqueBlockers(
  values: readonly PerformanceLocalV5SiteAuditBlocker[],
): PerformanceLocalV5SiteAuditBlocker[] {
  const result: PerformanceLocalV5SiteAuditBlocker[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const key = `${value.code}|${value.category}|${value.reason}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(value);
  }
  return result;
}

function emptyDistribution(): Record<PerformanceLocalV5PageType, number> {
  return { home: 0, service: 0, county: 0, city_service: 0, about: 0, contact: 0, faq: 0 };
}

function isV5PageType(value: string): value is PerformanceLocalV5PageType {
  return Object.prototype.hasOwnProperty.call(
    PERFORMANCE_LOCAL_V5_CURRENT_SITE_EXPECTATION.pageTypeDistribution,
    value,
  );
}

function positiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : null;
}

function deepFreeze<T>(value: T): T {
  if (typeof value !== "object" || value === null || Object.isFrozen(value)) return value;
  for (const child of Object.values(value as Record<string, unknown>)) deepFreeze(child);
  return Object.freeze(value);
}
