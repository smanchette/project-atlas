import type {
  PageMediaAssetCandidate,
  PageMediaPlacement,
  PageMediaPlanningWorkspace,
  PageMediaRequirementDecision,
  SitePlan,
  Website,
  WebsiteContext,
} from "../types";

export type PageMediaContextBinding = {
  websiteId: number;
  businessId: number;
  brandId: number;
  identityId: number;
  sitePlanId: number;
};

export function bindPageMediaContext(
  website: Website,
  context: WebsiteContext,
  sitePlan: SitePlan,
): PageMediaContextBinding {
  if (context.website.legacy_fallback) {
    throw new Error(
      "Page Media planning requires a persisted Website Context; a legacy fallback cannot be used.",
    );
  }
  if (context.website.id !== website.id) {
    throw new Error("Website Context does not match the selected Website.");
  }
  if (context.business.id !== website.business_id) {
    throw new Error("Website Context Business does not own the selected Website.");
  }
  if (!Number.isInteger(context.brand.id) || context.brand.id !== website.brand_id) {
    throw new Error("Website Context Brand does not match the selected Website.");
  }
  if (!Number.isInteger(context.identity.id)) {
    throw new Error("The selected Website does not have a persisted Website Identity.");
  }
  if (sitePlan.website_id !== website.id) {
    throw new Error("The selected Site Plan does not belong to the selected Website.");
  }
  return {
    websiteId: website.id,
    businessId: context.business.id,
    brandId: context.brand.id as number,
    identityId: context.identity.id as number,
    sitePlanId: sitePlan.id,
  };
}

export function validatePageMediaWorkspace(
  workspace: PageMediaPlanningWorkspace,
  binding: PageMediaContextBinding,
): PageMediaPlanningWorkspace {
  if (
    workspace.website_id !== binding.websiteId ||
    workspace.business_id !== binding.businessId ||
    workspace.site_plan_id !== binding.sitePlanId
  ) {
    throw new Error(
      "Page Media results crossed the authoritative Website or Site Plan boundary.",
    );
  }
  if (
    workspace.planning_record &&
    (workspace.planning_record.website_id !== binding.websiteId ||
      workspace.planning_record.business_id !== binding.businessId ||
      workspace.planning_record.site_plan_id !== binding.sitePlanId)
  ) {
    throw new Error("The Page Media planning record crossed its ownership boundary.");
  }

  validateAssetCollection(workspace.assets, binding);
  const assetIds = new Set(workspace.assets.map(pageMediaAssetId));
  const placementKeys = new Set<string>();
  const placementIds = new Set<number>();
  for (const placement of workspace.placements) {
    validatePlacement(placement, binding, assetIds);
    const scopedKey = `${placement.planned_page.id}:${pageMediaPlacementKey(placement)}`;
    if (placementKeys.has(scopedKey)) {
      throw new Error("Page Media results contain a duplicate Planned Page placement key.");
    }
    placementKeys.add(scopedKey);
    const placementId = effectivePlacementId(placement);
    if (placementId !== null) {
      if (placementIds.has(placementId)) {
        throw new Error("Page Media results contain a duplicate placement identity.");
      }
      placementIds.add(placementId);
    }
  }
  for (const suggestion of workspace.planning_record?.generated_media_suggestions ?? []) {
    if (
      suggestion.website_id !== binding.websiteId ||
      suggestion.business_id !== binding.businessId ||
      suggestion.site_plan_id !== binding.sitePlanId
    ) {
      throw new Error("An Atlas media suggestion crossed its ownership boundary.");
    }
  }
  return workspace;
}

function validateAssetCollection(
  assets: PageMediaAssetCandidate[],
  binding: PageMediaContextBinding,
) {
  const ids = new Set<number>();
  for (const asset of assets) {
    const id = pageMediaAssetId(asset);
    if (!Number.isInteger(id) || id <= 0) {
      throw new Error("A Page Media asset is missing a valid governed identity.");
    }
    if (ids.has(id)) {
      throw new Error("Page Media results contain a duplicate asset identity.");
    }
    if (asset.business_id !== binding.businessId) {
      throw new Error("A Page Media asset crossed the Website Context Business boundary.");
    }
    const isExplicitLegacyObservation =
      asset.website_id === null && asset.governance_status === "legacy_unverified";
    if (asset.website_id !== binding.websiteId && !isExplicitLegacyObservation) {
      throw new Error("A Page Media asset crossed the selected Website boundary.");
    }
    ids.add(id);
  }
}

function validatePlacement(
  placement: PageMediaPlacement,
  binding: PageMediaContextBinding,
  assetIds: Set<number>,
) {
  if (
    placement.planned_page.website_id !== binding.websiteId ||
    placement.planned_page.site_plan_id !== binding.sitePlanId
  ) {
    throw new Error("A Page Media placement crossed its Website, Site Plan, or Planned Page boundary.");
  }
  if (placement.suggestion) {
    if (
      placement.suggestion.website_id !== binding.websiteId ||
      placement.suggestion.business_id !== binding.businessId ||
      placement.suggestion.site_plan_id !== binding.sitePlanId ||
      placement.suggestion.planned_page_id !== placement.planned_page.id ||
      placement.suggestion.placement_key !== pageMediaPlacementKey(placement)
    ) {
      throw new Error("A Page Media suggestion does not match its placement.");
    }
  }
  const decisions = [
    ...placement.requirement_history,
    ...(placement.effective_requirement ? [placement.effective_requirement] : []),
  ];
  if (
    decisions.some(
      (decision) =>
        decision.website_id !== binding.websiteId ||
        decision.business_id !== binding.businessId ||
        decision.site_plan_id !== binding.sitePlanId ||
        decision.planned_page_id !== placement.planned_page.id ||
        decision.placement_key !== pageMediaPlacementKey(placement),
    )
  ) {
    throw new Error("A Page Media operator decision crossed its placement boundary.");
  }
  if (
    placement.compatible_asset_ids.some(
      (assetId) => !Number.isInteger(assetId) || !assetIds.has(assetId),
    )
  ) {
    throw new Error("A compatible Page Media asset is missing or belongs outside the workspace.");
  }
  if (
    placement.active_assignment &&
    (placement.active_assignment.website_id !== binding.websiteId ||
      placement.active_assignment.site_plan_id !== binding.sitePlanId ||
      placement.active_assignment.planned_page_id !== placement.planned_page.id ||
      placement.active_assignment.generated_page_id !== placement.planned_page.generated_page_id ||
      placement.active_assignment.media_requirement_id !== placement.effective_requirement?.id ||
      !assetIds.has(placement.active_assignment.image_metadata_id))
  ) {
    throw new Error("The active Page Media assignment crossed its ownership boundary.");
  }
  if (
    placement.legacy_assignments.some(
      (assignment) =>
        assignment.generated_page_id !== placement.planned_page.generated_page_id ||
        (assignment.website_id !== null && assignment.website_id !== binding.websiteId) ||
        (assignment.site_plan_id !== null && assignment.site_plan_id !== binding.sitePlanId) ||
        (assignment.planned_page_id !== null &&
          assignment.planned_page_id !== placement.planned_page.id),
    )
  ) {
    throw new Error("A legacy Page Media observation crossed its ownership boundary.");
  }
}

export function effectiveRequirementDecision(
  history: PageMediaRequirementDecision[],
): PageMediaRequirementDecision | null {
  if (!history.length) return null;
  const versions = new Set<number>();
  let current: PageMediaRequirementDecision | null = null;
  for (const decision of history) {
    if (!Number.isInteger(decision.version) || decision.version <= 0) {
      throw new Error("Page Media decision versions must be positive integers.");
    }
    if (versions.has(decision.version)) {
      throw new Error("Page Media decision history contains a duplicate version.");
    }
    versions.add(decision.version);
    if (!current || decision.version > current.version) current = decision;
  }
  return current;
}

export function pageMediaAssetId(asset: PageMediaAssetCandidate): number {
  return asset.id;
}

export function isPageMediaAssetEligible(
  asset: PageMediaAssetCandidate,
  accessibilityIntent = "informative",
): boolean {
  const path = asset.optimized_url || asset.asset_url || asset.thumbnail_url || "";
  const rights = asset.rights_status?.trim().toLowerCase() ?? "";
  return (
    asset.governance_status.trim().toLowerCase() === "approved" &&
    !asset.retired_at &&
    Boolean(asset.provenance_type?.trim()) &&
    !["", "unknown", "unverified", "pending"].includes(rights) &&
    /^[a-f0-9]{64}$/i.test(asset.checksum_sha256 ?? "") &&
    isSafeLocalMediaUrl(path) &&
    (accessibilityIntent === "decorative" || Boolean(asset.reviewed_alt_text?.trim()))
  );
}

export function isSafeLocalMediaUrl(value: string): boolean {
  if (!value || value.includes("\\") || /[\u0000-\u001f]/.test(value)) return false;
  if (value.startsWith("/") && !value.startsWith("//")) return true;
  try {
    const parsed = new URL(value);
    return (
      ["http:", "https:"].includes(parsed.protocol) &&
      ["localhost", "127.0.0.1", "testserver"].includes(parsed.hostname) &&
      parsed.pathname.startsWith("/media/")
    );
  } catch {
    return false;
  }
}

export function effectivePlacementId(placement: PageMediaPlacement): number | null {
  const value = placement.placement_id ?? placement.effective_requirement?.id ?? null;
  return Number.isInteger(value) && Number(value) > 0 ? Number(value) : null;
}

export function pageMediaPlacementKey(placement: PageMediaPlacement): string {
  return (
    placement.effective_requirement?.placement_key ||
    placement.suggestion?.placement_key ||
    "unplanned"
  );
}

export function placementReadinessStatus(
  placement: PageMediaPlacement,
): string {
  return placement.readiness || "needs_attention";
}

export function isCurrentPageMediaLoad(
  requestGeneration: number,
  currentGeneration: number,
): boolean {
  return requestGeneration === currentGeneration;
}
