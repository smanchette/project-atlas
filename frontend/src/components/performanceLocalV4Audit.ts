import type {
  GeneratedPage,
  PageComposition,
  PageMediaPlanningWorkspace,
  PlannedPage,
} from "../types";
import {
  auditPerformanceLocalV4Composition,
  type PerformanceLocalV4Blocker,
  type PerformanceLocalV4LayoutAudit,
  type PerformanceLocalV4LayoutKey,
  type PerformanceLocalV4PageType,
} from "./performanceLocalV4LayoutContract";
import {
  PERFORMANCE_LOCAL_V4_FORM_FIELD_CONTRACT,
  PERFORMANCE_LOCAL_V4_THEME,
} from "./performanceLocalThemeV4";
import {
  PERFORMANCE_LOCAL_V3_RENDERER_CONTRACT,
  PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY,
} from "./performanceLocalThemeV3";

export const PERFORMANCE_LOCAL_V4_CURRENT_SITE_EXPECTATION = Object.freeze({
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
  } satisfies Readonly<Record<PerformanceLocalV4PageType, number>>),
});

export const PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION = Object.freeze({
  generatedPageId: 41 as const,
  plannedPageId: 41 as const,
  pageType: "city_service" as const,
  compositionId: 41 as const,
  compositionVersion: 8 as const,
  compositionSourceHash: "8fc324478bf1685f1c2551620a96e23a08f7d0b6af6bad7a573715c226579b50" as const,
  qaResultId: 80 as const,
  qaPassedCount: 23 as const,
  qaWarningCount: 0 as const,
  qaFailedCount: 0 as const,
  qaResultHash: "f69fd05e9eb851d1cdee95ae102dd4b8060e5aa7ad1b70b0c00e4b020cac5518" as const,
  governedMedia: Object.freeze([
    Object.freeze({
      assignmentId: 13 as const,
      imageMetadataId: 8 as const,
      mediaRequirementId: 257 as const,
      semanticRole: "hero" as const,
      placementKey: "city-service-hero" as const,
      mediaComponentInstanceKey: "media_placement:requirement-257" as const,
      targetComponentKey: "hero" as const,
      targetComponentInstanceKey: "hero" as const,
      targetRegion: "main" as const,
      displayPreset: "hero_desktop" as const,
      placementContractVersion: 2 as const,
      requirementVersion: 2 as const,
    }),
    Object.freeze({
      assignmentId: 14 as const,
      imageMetadataId: 9 as const,
      mediaRequirementId: 258 as const,
      semanticRole: "service" as const,
      placementKey: "city-service-process" as const,
      mediaComponentInstanceKey: "media_placement:requirement-258" as const,
      targetComponentKey: "service_summary" as const,
      targetComponentInstanceKey: "service_summary:why_it_matters" as const,
      targetRegion: "main" as const,
      displayPreset: "hero_desktop" as const,
      placementContractVersion: 2 as const,
      requirementVersion: 2 as const,
    }),
    Object.freeze({
      assignmentId: 15 as const,
      imageMetadataId: 10 as const,
      mediaRequirementId: 256 as const,
      semanticRole: "support" as const,
      placementKey: "city-service-evidence" as const,
      mediaComponentInstanceKey: "media_placement:requirement-256" as const,
      targetComponentKey: "content_section" as const,
      targetComponentInstanceKey: "content_section:signs_section" as const,
      targetRegion: "main" as const,
      displayPreset: "hero_desktop" as const,
      placementContractVersion: 2 as const,
      requirementVersion: 1 as const,
    }),
  ]),
});

export type PerformanceLocalV4ConversionAuditEvidence = Readonly<{
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

export type PerformanceLocalV4ConversionAuditResult = Readonly<{
  safePreviewContract: boolean;
  rendererReady: boolean;
  blockers: readonly PerformanceLocalV4SiteAuditBlocker[];
}>;

export type PerformanceLocalV4Page41PreservationResult = Readonly<{
  preserved: boolean;
  contentIdentityPreserved: boolean;
  governedMediaIdentityPreserved: boolean;
  compositionIdentity: Readonly<{
    generatedPageId: number;
    plannedPageId: number;
    compositionId: number;
    compositionVersion: number;
    compositionSourceHash: string;
    qaResultId: number | null;
    qaResultHash: string | null;
  }>;
  governedMediaIdentities: readonly Readonly<{
    assignmentId: number;
    imageMetadataId: number;
    mediaRequirementId: number;
    semanticRole: string;
    placementKey: string;
    mediaComponentInstanceKey: string;
    targetComponentKey: string;
    targetComponentInstanceKey: string;
    targetRegion: string;
    displayPreset: string;
    placementContractVersion: number;
    requirementVersion: number;
  }>[];
  blockers: readonly PerformanceLocalV4SiteAuditBlocker[];
}>;

export type PerformanceLocalV4SiteAuditInput = Readonly<{
  websiteId: number;
  sitePlanId: number;
  plannedPages: readonly PlannedPage[];
  generatedPages: readonly GeneratedPage[];
  compositions: readonly PageComposition[];
  mediaWorkspace: PageMediaPlanningWorkspace;
  conversionEvidence: PerformanceLocalV4ConversionAuditEvidence;
  expectedPageCount?: 65;
}>;

export type PerformanceLocalV4SiteAuditBlocker = Readonly<{
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

export type PerformanceLocalV4SiteAuditRow = Readonly<{
  plannedPageId: number;
  generatedPageId: number | null;
  pageType: string;
  selectedLayoutKey: PerformanceLocalV4LayoutKey | null;
  layoutCompatibility: string | null;
  sourceComponentCount: number;
  consumedComponentCount: number;
  unconsumedSourceComponents: readonly string[];
  duplicatedSourceComponents: readonly string[];
  missingRequiredSemanticRegions: readonly string[];
  missingOptionalSemanticRegions: readonly string[];
  mediaReadiness: "ready" | "blocked";
  qaReadiness: "ready" | "blocked";
  formState: PerformanceLocalV4ConversionAuditEvidence["formState"];
  bannerState: PerformanceLocalV4ConversionAuditEvidence["bannerState"];
  stickyActionState: PerformanceLocalV4ConversionAuditEvidence["stickyActionState"];
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
  layoutAudit: PerformanceLocalV4LayoutAudit | null;
  blockerList: readonly PerformanceLocalV4SiteAuditBlocker[];
}>;

export type PerformanceLocalV4FullSiteAudit = Readonly<{
  status: "ready" | "blocked";
  sourceIdentity: Readonly<{
    websiteId: number;
    sitePlanId: number;
    expectedPageCount: 65;
    expectedSourceComponentCount: 1_165;
    themeCompatibilityIdentity: string;
    durableV4Registration: "absent_by_design";
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
    pageTypeDistribution: Readonly<Record<PerformanceLocalV4PageType, number>>;
  }>;
  pages: readonly PerformanceLocalV4SiteAuditRow[];
  page41Preservation: PerformanceLocalV4Page41PreservationResult | null;
  blockers: readonly PerformanceLocalV4SiteAuditBlocker[];
}>;

export function auditPerformanceLocalV4Page41Preservation(input: Readonly<{
  page: GeneratedPage;
  plannedPage: PlannedPage;
  composition: PageComposition;
  mediaWorkspace: PageMediaPlanningWorkspace;
}>): PerformanceLocalV4Page41PreservationResult {
  const expected = PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION;
  const blockers: PerformanceLocalV4SiteAuditBlocker[] = [];
  const qa = input.page.qa_result;
  const contentIdentityPreserved = (
    input.page.id === expected.generatedPageId &&
    input.page.page_type === expected.pageType &&
    input.page.qa_status === "ready" &&
    input.plannedPage.id === expected.plannedPageId &&
    input.plannedPage.generated_page_id === expected.generatedPageId &&
    input.plannedPage.page_type === expected.pageType &&
    input.composition.id === expected.compositionId &&
    input.composition.planned_page_id === expected.plannedPageId &&
    input.composition.generated_page_id === expected.generatedPageId &&
    input.composition.composition_version === expected.compositionVersion &&
    input.composition.status === "current" &&
    input.composition.validation_errors.length === 0 &&
    input.composition.source_hash === expected.compositionSourceHash &&
    qa?.qa_result_id === expected.qaResultId &&
    qa.page_id === expected.generatedPageId &&
    qa.planned_page_id === expected.plannedPageId &&
    qa.page_composition_id === expected.compositionId &&
    qa.composition_version === expected.compositionVersion &&
    qa.composition_source_hash === expected.compositionSourceHash &&
    qa.lifecycle_status === "current" &&
    qa.readiness_status === "ready" &&
    qa.currentness_status === "current_exact_identity_match" &&
    qa.persisted &&
    qa.passed_count === expected.qaPassedCount &&
    qa.warning_count === expected.qaWarningCount &&
    qa.failed_count === expected.qaFailedCount &&
    qa.result_hash === expected.qaResultHash
  );
  if (!contentIdentityPreserved) {
    blockers.push(blocker(
      "page_41_content_or_qa_identity_drift",
      "input",
      "Page 41 must remain Generated 41 / Planned 41 / Composition 41 v8 with its exact source hash and current QA 80 identity.",
    ));
  }

  const mediaComponents = input.composition.effective_components.filter(
    (component) => component.component_key === "media_placement",
  );
  const pagePlacements = input.mediaWorkspace.placements.filter(
    (placement) =>
      placement.planned_page.id === expected.plannedPageId &&
      placement.planned_page.generated_page_id === expected.generatedPageId,
  );
  const expectedAssetIds = new Set<number>(expected.governedMedia.map((item) => item.imageMetadataId));
  const governedMediaIdentities: Array<PerformanceLocalV4Page41PreservationResult["governedMediaIdentities"][number]> = [];
  let governedMediaIdentityPreserved = (
    mediaComponents.length === expected.governedMedia.length &&
    pagePlacements.length === expected.governedMedia.length
  );

  for (const mediaIdentity of expected.governedMedia) {
    const placement = pagePlacements.find(
      (candidate) => candidate.active_assignment?.id === mediaIdentity.assignmentId,
    );
    const assignment = placement?.active_assignment ?? null;
    const requirement = placement?.effective_requirement ?? null;
    const asset = input.mediaWorkspace.assets.find(
      (candidate) => candidate.id === mediaIdentity.imageMetadataId,
    ) ?? null;
    const component = mediaComponents.find(
      (candidate) => positiveInteger(candidate.input_bindings.page_image_assignment_id) === mediaIdentity.assignmentId,
    );
    const resolvedData = component?.resolved_data ?? {};
    const expectedAlt = assignment?.override_alt_text?.trim() || asset?.reviewed_alt_text?.trim() || "";
    const expectedAssetUrl = asset?.optimized_url || asset?.asset_url || "";
    const identityPreserved = Boolean(
      placement &&
      assignment &&
      requirement &&
      asset &&
      component &&
      component.instance_key === mediaIdentity.mediaComponentInstanceKey &&
      component.region === mediaIdentity.targetRegion &&
      placement.composition_status === "current" &&
      placement.blocking_reasons.length === 0 &&
      assignment.id === mediaIdentity.assignmentId &&
      assignment.image_metadata_id === mediaIdentity.imageMetadataId &&
      assignment.media_requirement_id === mediaIdentity.mediaRequirementId &&
      assignment.generated_page_id === expected.generatedPageId &&
      assignment.planned_page_id === expected.plannedPageId &&
      assignment.website_id === input.composition.website_id &&
      assignment.site_plan_id === input.composition.site_plan_id &&
      assignment.image_role === mediaIdentity.semanticRole &&
      assignment.status === "active" &&
      assignment.placement_contract_version === mediaIdentity.placementContractVersion &&
      assignment.display_preset === mediaIdentity.displayPreset &&
      assignment.effective_display_preset === mediaIdentity.displayPreset &&
      requirement.id === mediaIdentity.mediaRequirementId &&
      requirement.website_id === input.composition.website_id &&
      requirement.site_plan_id === input.composition.site_plan_id &&
      requirement.planned_page_id === expected.plannedPageId &&
      requirement.placement_key === mediaIdentity.placementKey &&
      requirement.component_or_section === mediaIdentity.targetComponentKey &&
      requirement.target_component_instance_key === mediaIdentity.targetComponentInstanceKey &&
      requirement.contract_version === mediaIdentity.placementContractVersion &&
      requirement.version === mediaIdentity.requirementVersion &&
      requirement.effective_display_preset === mediaIdentity.displayPreset &&
      positiveInteger(component.input_bindings.media_requirement_id) === mediaIdentity.mediaRequirementId &&
      positiveInteger(component.input_bindings.placement_contract_version) === mediaIdentity.placementContractVersion &&
      positiveInteger(component.input_bindings.page_image_assignment_id) === mediaIdentity.assignmentId &&
      component.input_bindings.target_component_key === mediaIdentity.targetComponentKey &&
      component.input_bindings.target_component_instance_key === mediaIdentity.targetComponentInstanceKey &&
      component.input_bindings.target_region === mediaIdentity.targetRegion &&
      resolvedData.media_requirement_id === mediaIdentity.mediaRequirementId &&
      resolvedData.placement_contract_version === mediaIdentity.placementContractVersion &&
      resolvedData.image_role === mediaIdentity.semanticRole &&
      resolvedData.placement_key === mediaIdentity.placementKey &&
      resolvedData.component_or_section === mediaIdentity.targetComponentKey &&
      resolvedData.target_component_instance_key === mediaIdentity.targetComponentInstanceKey &&
      resolvedData.target_region === mediaIdentity.targetRegion &&
      resolvedData.stored_display_preset === mediaIdentity.displayPreset &&
      resolvedData.effective_display_preset === mediaIdentity.displayPreset &&
      resolvedData.display_preset === mediaIdentity.displayPreset &&
      expectedAlt &&
      resolvedData.alt_text === expectedAlt &&
      expectedAssetUrl &&
      resolvedData.asset_url === expectedAssetUrl &&
      assignment.media_version === asset.media_version &&
      resolvedData.media_version === asset.media_version
    );
    governedMediaIdentityPreserved &&= identityPreserved;
    governedMediaIdentities.push(Object.freeze({
      assignmentId: assignment?.id ?? mediaIdentity.assignmentId,
      imageMetadataId: assignment?.image_metadata_id ?? mediaIdentity.imageMetadataId,
      mediaRequirementId: requirement?.id ?? mediaIdentity.mediaRequirementId,
      semanticRole: typeof resolvedData.image_role === "string"
        ? resolvedData.image_role
        : mediaIdentity.semanticRole,
      placementKey: requirement?.placement_key ?? mediaIdentity.placementKey,
      mediaComponentInstanceKey: component?.instance_key ?? mediaIdentity.mediaComponentInstanceKey,
      targetComponentKey: typeof component?.input_bindings.target_component_key === "string"
        ? component.input_bindings.target_component_key
        : mediaIdentity.targetComponentKey,
      targetComponentInstanceKey: typeof component?.input_bindings.target_component_instance_key === "string"
        ? component.input_bindings.target_component_instance_key
        : mediaIdentity.targetComponentInstanceKey,
      targetRegion: typeof component?.input_bindings.target_region === "string"
        ? component.input_bindings.target_region
        : mediaIdentity.targetRegion,
      displayPreset: assignment?.effective_display_preset ?? mediaIdentity.displayPreset,
      placementContractVersion: assignment?.placement_contract_version ?? mediaIdentity.placementContractVersion,
      requirementVersion: requirement?.version ?? mediaIdentity.requirementVersion,
    }));
    if (!identityPreserved) {
      blockers.push(blocker(
        "page_41_governed_media_identity_drift",
        "media",
        `Page 41 governed assignment ${mediaIdentity.assignmentId}, image ${mediaIdentity.imageMetadataId}, and requirement ${mediaIdentity.mediaRequirementId} must retain their exact role, preset, contract, source, and Composition bindings.`,
      ));
    }
  }

  const governedAssetLeak = input.mediaWorkspace.placements.some(
    (placement) =>
      placement.planned_page.id !== expected.plannedPageId &&
      placement.active_assignment !== null &&
      expectedAssetIds.has(placement.active_assignment.image_metadata_id),
  );
  if (governedAssetLeak) {
    governedMediaIdentityPreserved = false;
    blockers.push(blocker(
      "page_41_governed_media_cross_page_leak",
      "media",
      "Page 41 governed image identities 8, 9, and 10 must not be assigned to another page.",
    ));
  }

  return deepFreeze({
    preserved: contentIdentityPreserved && governedMediaIdentityPreserved,
    contentIdentityPreserved,
    governedMediaIdentityPreserved,
    compositionIdentity: Object.freeze({
      generatedPageId: input.page.id,
      plannedPageId: input.plannedPage.id,
      compositionId: input.composition.id,
      compositionVersion: input.composition.composition_version,
      compositionSourceHash: input.composition.source_hash,
      qaResultId: qa?.qa_result_id ?? null,
      qaResultHash: qa?.result_hash ?? null,
    }),
    governedMediaIdentities,
    blockers: uniqueBlockers(blockers),
  });
}

export function auditPerformanceLocalV4FullSite(
  input: PerformanceLocalV4SiteAuditInput,
): PerformanceLocalV4FullSiteAudit {
  const siteBlockers: PerformanceLocalV4SiteAuditBlocker[] = [];
  const plannedPages = [...input.plannedPages].sort((left, right) => left.id - right.id);
  uniqueIndex(plannedPages, (item) => item.id, "planned_page", siteBlockers);
  const generatedById = uniqueIndex(input.generatedPages, (item) => item.id, "generated_page", siteBlockers);
  const compositionByPlannedId = uniqueIndex(
    input.compositions,
    (item) => item.planned_page_id,
    "page_composition",
    siteBlockers,
  );
  const conversion = auditPerformanceLocalV4ConversionEvidence(input.conversionEvidence);

  if ((input.expectedPageCount ?? 65) !== 65 || plannedPages.length !== 65) {
    siteBlockers.push(blocker(
      "full_site_page_count_mismatch",
      "input",
      `The V4 current-site audit requires exactly 65 Planned Pages; received ${plannedPages.length}.`,
    ));
  }
  if (input.generatedPages.length !== 65) {
    siteBlockers.push(blocker(
      "full_site_generated_page_count_mismatch",
      "input",
      `The V4 current-site audit requires exactly 65 Generated Pages; received ${input.generatedPages.length}.`,
    ));
  }
  if (input.compositions.length !== 65) {
    siteBlockers.push(blocker(
      "full_site_composition_count_mismatch",
      "input",
      `The V4 current-site audit requires exactly 65 Page Compositions; received ${input.compositions.length}.`,
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

  const rows: PerformanceLocalV4SiteAuditRow[] = [];
  const usedGeneratedIds = new Set<number>();
  const usedCompositionIds = new Set<number>();
  let page41Preservation: PerformanceLocalV4Page41PreservationResult | null = null;
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

    const layoutAudit = auditPerformanceLocalV4Composition({
      page: generatedPage,
      plannedPage,
      composition,
    });
    const pageBlockers = layoutBlockers(layoutAudit.blockers);
    const media = mediaAudit(input.mediaWorkspace, plannedPage.id);
    const qa = qaAudit(generatedPage, composition, plannedPage);
    pageBlockers.push(...media.blockers, ...qa.blockers, ...conversion.blockers);
    let rowPage41Preservation: PerformanceLocalV4Page41PreservationResult | null = null;
    if (generatedPage.id === PERFORMANCE_LOCAL_V4_PAGE_41_EXPECTATION.generatedPageId) {
      page41Preservation = auditPerformanceLocalV4Page41Preservation({
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
        "v4_not_durably_registered",
        "activation",
        "Performance Local V4 is source-only and has no durable Theme registration or selection.",
      ),
      blocker(
        "v4_preview_candidate_not_production_ready",
        "activation",
        "Performance Local V4 remains preview_candidate with productionReady false.",
      ),
      blocker(
        "v4_public_export_not_authorized",
        "export",
        "A source-only V4 layout has no governed public export identity.",
      ),
      blocker(
        "v4_publication_not_authorized",
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
      unconsumedSourceComponents: layoutAudit.unconsumedSourceInstanceKeys,
      duplicatedSourceComponents: layoutAudit.duplicatedSourceInstanceKeys,
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
    if (isV4PageType(row.pageType)) distribution[row.pageType] += 1;
  }
  for (const pageType of Object.keys(PERFORMANCE_LOCAL_V4_CURRENT_SITE_EXPECTATION.pageTypeDistribution) as PerformanceLocalV4PageType[]) {
    const expected = PERFORMANCE_LOCAL_V4_CURRENT_SITE_EXPECTATION.pageTypeDistribution[pageType];
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
  if (sourceComponents !== PERFORMANCE_LOCAL_V4_CURRENT_SITE_EXPECTATION.sourceComponentCount) {
    siteBlockers.push(blocker(
      "current_source_component_count_mismatch",
      "input",
      `Expected 1,165 source components; received ${sourceComponents}.`,
    ));
  }
  if (rows.some((row) => !row.layoutReady)) {
    siteBlockers.push(blocker(
      "full_site_layout_not_ready",
      "layout",
      "One or more current pages failed the exact V4 layout/consumption audit.",
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
      "The V4 audit did not produce one deterministic row per Planned Page.",
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
      themeCompatibilityIdentity: PERFORMANCE_LOCAL_V4_THEME.compatibilityIdentity,
      durableV4Registration: "absent_by_design" as const,
    }),
    counts,
    pages: rows,
    page41Preservation,
    blockers: uniqueBlockers(siteBlockers),
  });
}

export function auditPerformanceLocalV4ConversionEvidence(
  evidence: PerformanceLocalV4ConversionAuditEvidence,
): PerformanceLocalV4ConversionAuditResult {
  const blockers: PerformanceLocalV4SiteAuditBlocker[] = [];
  if (
    evidence.sourceThemeCompatibility !== PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY ||
    evidence.sourceRendererContract !== PERFORMANCE_LOCAL_V3_RENDERER_CONTRACT
  ) {
    blockers.push(blocker(
      "governed_conversion_identity_mismatch",
      "form",
      "V4 may consume only the exact immutable V3 conversion identity without relabeling it.",
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
    evidence.formFieldCount !== PERFORMANCE_LOCAL_V4_FORM_FIELD_CONTRACT.defaultCustomerEntryFieldCount ||
    evidence.optionalFormFieldCount !== PERFORMANCE_LOCAL_V4_FORM_FIELD_CONTRACT.activeOptionalFieldCount ||
    evidence.maximumFormFieldCount !== PERFORMANCE_LOCAL_V4_FORM_FIELD_CONTRACT.maximumCustomerEntryFieldCount ||
    evidence.formCanSubmit ||
    evidence.formCollectsData
  ) {
    blockers.push(blocker(
      "form_preview_contract_mismatch",
      "form",
      "The V4 form preview must remain provider-disabled, non-collecting, five-default, zero-optional, and six-maximum.",
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
  const blockers: PerformanceLocalV4SiteAuditBlocker[] = [];
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
  const blockers: PerformanceLocalV4SiteAuditBlocker[] = [];
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
  conversion: PerformanceLocalV4ConversionAuditEvidence,
): PerformanceLocalV4SiteAuditRow {
  return deepFreeze({
    plannedPageId: plannedPage.id,
    generatedPageId: page?.id ?? plannedPage.generated_page_id ?? null,
    pageType: page?.page_type ?? plannedPage.page_type,
    selectedLayoutKey: null,
    layoutCompatibility: null,
    sourceComponentCount: composition?.effective_components.length ?? 0,
    consumedComponentCount: 0,
    unconsumedSourceComponents: composition?.effective_components.map((item) => item.instance_key) ?? [],
    duplicatedSourceComponents: [],
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
  values: readonly PerformanceLocalV4Blocker[],
): PerformanceLocalV4SiteAuditBlocker[] {
  return values.map((item) => blocker(item.code, "layout", item.message));
}

function uniqueIndex<T>(
  values: readonly T[],
  key: (value: T) => number,
  label: string,
  blockers: PerformanceLocalV4SiteAuditBlocker[],
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
  category: PerformanceLocalV4SiteAuditBlocker["category"],
  reason: string,
): PerformanceLocalV4SiteAuditBlocker {
  return Object.freeze({ code, category, reason });
}

function uniqueBlockers(
  values: readonly PerformanceLocalV4SiteAuditBlocker[],
): PerformanceLocalV4SiteAuditBlocker[] {
  const result: PerformanceLocalV4SiteAuditBlocker[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const key = `${value.code}|${value.category}|${value.reason}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(value);
  }
  return result;
}

function emptyDistribution(): Record<PerformanceLocalV4PageType, number> {
  return { home: 0, service: 0, county: 0, city_service: 0, about: 0, contact: 0, faq: 0 };
}

function isV4PageType(value: string): value is PerformanceLocalV4PageType {
  return Object.prototype.hasOwnProperty.call(
    PERFORMANCE_LOCAL_V4_CURRENT_SITE_EXPECTATION.pageTypeDistribution,
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
