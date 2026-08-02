import type {
  BrandAsset,
  Website,
  WebsiteContext,
  WebsiteIdentityAssets,
} from "../types";

export const IDENTITY_SLOTS = [
  "header_logo",
  "footer_logo",
  "favicon",
  "browser_icon",
  "apple_touch_icon",
  "open_graph_image",
] as const;

export type IdentitySlot = (typeof IDENTITY_SLOTS)[number];

export const IDENTITY_SLOT_CONTRACTS: Record<
  IdentitySlot,
  { assetTypes: readonly string[]; requiredUsage: string }
> = {
  header_logo: {
    assetTypes: ["primary_logo", "alternate_logo", "brand_mark"],
    requiredUsage: "website_header",
  },
  footer_logo: {
    assetTypes: ["primary_logo", "alternate_logo", "brand_mark"],
    requiredUsage: "website_footer",
  },
  favicon: { assetTypes: ["favicon"], requiredUsage: "browser_tab" },
  browser_icon: { assetTypes: ["browser_icon"], requiredUsage: "browser_tab" },
  apple_touch_icon: {
    assetTypes: ["apple_touch_icon"],
    requiredUsage: "browser_tab",
  },
  open_graph_image: {
    assetTypes: ["open_graph_image"],
    requiredUsage: "social_preview",
  },
};

export type BrandAssetContextBinding = {
  websiteId: number;
  businessId: number;
  brandId: number;
  identityId: number;
};

export function bindWebsiteContext(
  website: Website,
  context: WebsiteContext,
): BrandAssetContextBinding {
  if (context.website.legacy_fallback) {
    throw new Error(
      "Brand Assets require a persisted Website Context; a legacy fallback cannot be used.",
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

  return {
    websiteId: website.id,
    businessId: context.business.id,
    brandId: context.brand.id as number,
    identityId: context.identity.id as number,
  };
}

export function validateContextOwnedAssets(
  assets: BrandAsset[],
  binding: BrandAssetContextBinding,
): BrandAsset[] {
  if (
    assets.some(
      (asset) =>
        asset.business_id !== binding.businessId || asset.brand_id !== binding.brandId,
    )
  ) {
    throw new Error(
      "Brand Asset results crossed the authoritative Website Context ownership boundary.",
    );
  }
  return assets;
}

export function validateIdentitySelections(
  selections: WebsiteIdentityAssets,
  binding: BrandAssetContextBinding,
): WebsiteIdentityAssets {
  if (
    selections.website_identity_id !== binding.identityId ||
    selections.website_id !== binding.websiteId ||
    selections.brand_id !== binding.brandId
  ) {
    throw new Error(
      "Website Identity selections do not match the authoritative Website Context.",
    );
  }

  const assignments = [
    ...Object.values(selections.active),
    ...selections.history,
  ];
  if (
    assignments.some(
      (assignment) =>
        assignment.website_identity_id !== binding.identityId ||
        assignment.website_id !== binding.websiteId ||
        assignment.brand_id !== binding.brandId ||
        (assignment.asset !== null &&
          assignment.asset !== undefined &&
          (assignment.asset.business_id !== binding.businessId ||
            assignment.asset.brand_id !== binding.brandId)),
    )
  ) {
    throw new Error(
      "A Website Identity assignment crossed the authoritative Website Context ownership boundary.",
    );
  }
  return selections;
}

export function isAssetCompatibleWithSlot(
  asset: BrandAsset,
  slot: IdentitySlot,
  binding?: BrandAssetContextBinding,
): boolean {
  if (
    binding &&
    (asset.business_id !== binding.businessId || asset.brand_id !== binding.brandId)
  ) {
    return false;
  }
  const contract = IDENTITY_SLOT_CONTRACTS[slot];
  return (
    asset.status === "approved" &&
    contract.assetTypes.includes(asset.asset_type) &&
    asset.approved_usage.includes(contract.requiredUsage) &&
    !asset.restrictions.includes(contract.requiredUsage)
  );
}

export function currentApprovedAssets(assets: BrandAsset[]): BrandAsset[] {
  const byId = new Map(assets.map((asset) => [asset.id, asset]));
  const supersededIds = new Set<number>();

  for (const asset of assets) {
    // Approval is durable provenance. A later version that was approved and then
    // retired must still supersede every ancestor in its replacement chain.
    if (asset.status !== "approved" && !asset.approved_at) continue;
    let replacedId = asset.replaces_brand_asset_id ?? null;
    const visited = new Set<number>();
    while (replacedId !== null && !visited.has(replacedId)) {
      visited.add(replacedId);
      supersededIds.add(replacedId);
      replacedId = byId.get(replacedId)?.replaces_brand_asset_id ?? null;
    }
  }

  return assets.filter(
    (asset) => asset.status === "approved" && !supersededIds.has(asset.id),
  );
}
