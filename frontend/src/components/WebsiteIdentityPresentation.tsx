import type { IdentitySlot } from "./brandAssetContext";
import { IDENTITY_SLOT_CONTRACTS } from "./brandAssetContext";

type ResolvedIdentityAsset = {
  asset_type: string;
  asset_url: string;
  accessibility_description: string;
};

type IdentityAssets = Record<string, unknown>;

export type IdentityHeadDescriptor = {
  tag: "link" | "meta";
  slot: IdentitySlot;
  attributes: Record<string, string>;
};

export function WebsiteIdentityLogo({
  identityAssets,
  slot,
  displayName,
}: {
  identityAssets: IdentityAssets;
  slot: "header_logo" | "footer_logo";
  displayName: string;
}) {
  const asset = resolvedIdentityAsset(identityAssets, slot);
  if (asset) {
    return (
      <img
        className={
          slot === "footer_logo"
            ? "previewBrandLogo previewFooterLogo"
            : "previewBrandLogo"
        }
        src={asset.asset_url}
        alt={asset.accessibility_description}
      />
    );
  }
  if (slot === "footer_logo") return null;
  return (
    <span className="previewBrandMark" aria-hidden="true">
      {initials(displayName)}
    </span>
  );
}

export function identityHeadDescriptors(
  identityAssets: IdentityAssets,
): IdentityHeadDescriptor[] {
  const values: IdentityHeadDescriptor[] = [];
  const linkSlots: Array<{
    slot: "favicon" | "browser_icon" | "apple_touch_icon";
    rel: string;
  }> = [
    { slot: "favicon", rel: "icon" },
    { slot: "browser_icon", rel: "shortcut icon" },
    { slot: "apple_touch_icon", rel: "apple-touch-icon" },
  ];
  for (const { slot, rel } of linkSlots) {
    const asset = resolvedIdentityAsset(identityAssets, slot);
    if (!asset) continue;
    values.push({
      tag: "link",
      slot,
      attributes: { rel, href: asset.asset_url },
    });
  }

  const openGraph = resolvedIdentityAsset(identityAssets, "open_graph_image");
  if (openGraph) {
    values.push({
      tag: "meta",
      slot: "open_graph_image",
      attributes: { property: "og:image", content: openGraph.asset_url },
    });
    values.push({
      tag: "meta",
      slot: "open_graph_image",
      attributes: {
        property: "og:image:alt",
        content: openGraph.accessibility_description,
      },
    });
  }
  return values;
}

export function installIdentityHeadTags(
  targetDocument: Document,
  identityAssets: IdentityAssets,
): () => void {
  const elements = identityHeadDescriptors(identityAssets).map((descriptor) => {
    const element = targetDocument.createElement(descriptor.tag);
    for (const [name, value] of Object.entries(descriptor.attributes)) {
      element.setAttribute(name, value);
    }
    element.setAttribute("data-atlas-identity", "true");
    element.setAttribute("data-atlas-identity-slot", descriptor.slot);
    targetDocument.head.appendChild(element);
    return element;
  });
  return () => elements.forEach((element) => element.remove());
}

export function removeIdentityHeadTags(targetDocument: Document): void {
  targetDocument
    .querySelectorAll('[data-atlas-identity="true"]')
    .forEach((element) => element.remove());
}

function resolvedIdentityAsset(
  identityAssets: IdentityAssets,
  slot: IdentitySlot,
): ResolvedIdentityAsset | null {
  const value = identityAssets[slot];
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const asset = value as Record<string, unknown>;
  const assetType = cleanText(asset.asset_type);
  const assetUrl = cleanText(asset.asset_url);
  const accessibilityDescription = cleanText(asset.accessibility_description);
  if (
    !IDENTITY_SLOT_CONTRACTS[slot].assetTypes.includes(assetType) ||
    !isSafeIdentityAssetUrl(assetUrl) ||
    !accessibilityDescription
  ) {
    return null;
  }
  return {
    asset_type: assetType,
    asset_url: assetUrl,
    accessibility_description: accessibilityDescription,
  };
}

export function isSafeIdentityAssetUrl(value: string): boolean {
  if (!value || /[\u0000-\u001f\u007f\\]/.test(value)) return false;
  if (value.startsWith("/")) return !value.startsWith("//");
  try {
    const parsed = new URL(value);
    return (
      (parsed.protocol === "http:" || parsed.protocol === "https:") &&
      !parsed.username &&
      !parsed.password
    );
  } catch {
    return false;
  }
}

function cleanText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function initials(value: string): string {
  return (
    value
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase() || "A"
  );
}
