import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";

import {
  bindWebsiteContext,
  currentApprovedAssets,
  isAssetCompatibleWithSlot,
  validateContextOwnedAssets,
  validateIdentitySelections,
} from "../src/components/brandAssetContext";
import {
  identityHeadDescriptors,
  installIdentityHeadTags,
  isSafeIdentityAssetUrl,
  removeIdentityHeadTags,
} from "../src/components/WebsiteIdentityPresentation";
import {
  compositionValidationError,
  hasCurrentPreviewData,
  previewRequestKey,
  renderComponent,
} from "../src/pages/GeneratedPagePreview";
import {
  BrandAssetEvidence,
  hasProhibitedUsageDecision,
} from "../src/pages/BrandAssetsPage";
import type {
  BrandAsset,
  PageComponentInstance,
  PageComposition,
  Website,
  WebsiteContext,
  WebsiteIdentityAssetAssignment,
  WebsiteIdentityAssets,
} from "../src/types";

const website: Website = {
  id: 31,
  business_id: 11,
  brand_id: 21,
  website_name: "Flo-Zone Website",
  domain: "example.test",
  public_url: "https://example.test",
  locale: "en-US",
  primary_language: "en",
  configuration: {},
  status: "active",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const context: WebsiteContext = {
  business: {
    id: 11,
    company_name: "Flo-Zone Pest And Termite Solutions Inc.",
    business_type: "Pest control service",
    state: "FL",
  },
  brand: {
    id: 21,
    public_name: "Flo-Zone",
    identity_settings: {},
  },
  website: {
    id: 31,
    website_name: "Flo-Zone Website",
    domain: "example.test",
    public_url: "https://example.test",
    locale: "en-US",
    primary_language: "en",
    configuration: {},
    status: "active",
    legacy_fallback: false,
  },
  identity: { id: 41, display_name: "Flo-Zone", status: "approved" },
};

const binding = bindWebsiteContext(website, context);

function asset(overrides: Partial<BrandAsset> = {}): BrandAsset {
  return {
    id: 1,
    business_id: 11,
    brand_id: 21,
    asset_key: "primary-logo",
    version: 1,
    asset_type: "primary_logo",
    variant_key: "default",
    purpose: "Primary logo",
    approved_usage: ["website_header", "website_footer"],
    restrictions: [],
    accessibility_description: "Flo-Zone primary logo",
    original_filename: "logo.png",
    asset_url: "/api/brand-assets/1/file",
    mime_type: "image/png",
    file_size: 100,
    width: 400,
    height: 120,
    checksum_sha256: "a".repeat(64),
    provenance_type: "company_original",
    rights_status: "owned",
    status: "approved",
    created_by: "Operator",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

function assignment(
  value: BrandAsset,
  overrides: Partial<WebsiteIdentityAssetAssignment> = {},
): WebsiteIdentityAssetAssignment {
  return {
    id: 1,
    website_identity_id: 41,
    website_id: 31,
    brand_id: 21,
    brand_asset_id: value.id,
    slot: "header_logo",
    version: 1,
    status: "active",
    assigned_by: "Operator",
    assigned_at: "2026-08-01T00:00:00Z",
    asset: value,
    ...overrides,
  };
}

test("one authoritative Website Context binds Website, Business, Brand, and Identity", () => {
  assert.deepEqual(binding, {
    websiteId: 31,
    businessId: 11,
    brandId: 21,
    identityId: 41,
  });
});

test("cross-Website, cross-Business, and cross-Brand contexts fail closed", () => {
  assert.throws(
    () =>
      bindWebsiteContext(website, {
        ...context,
        website: { ...context.website, id: 32 },
      }),
    /does not match the selected Website/,
  );
  assert.throws(
    () =>
      bindWebsiteContext(website, {
        ...context,
        business: { ...context.business, id: 12 },
      }),
    /Business does not own/,
  );
  assert.throws(
    () =>
      bindWebsiteContext(website, {
        ...context,
        brand: { ...context.brand, id: 22 },
      }),
    /Brand does not match/,
  );
});

test("legacy fallback and missing Website Identity fail closed", () => {
  assert.throws(
    () =>
      bindWebsiteContext(website, {
        ...context,
        website: { ...context.website, legacy_fallback: true },
      }),
    /legacy fallback cannot be used/,
  );
  assert.throws(
    () =>
      bindWebsiteContext(website, {
        ...context,
        identity: { ...context.identity, id: null },
      }),
    /persisted Website Identity/,
  );
});

test("cross-owner asset results and identity assignments fail closed", () => {
  assert.throws(
    () => validateContextOwnedAssets([asset({ brand_id: 99 })], binding),
    /ownership boundary/,
  );
  const value = asset();
  const selections: WebsiteIdentityAssets = {
    website_identity_id: 41,
    website_id: 31,
    brand_id: 21,
    active: { header_logo: assignment(value, { website_id: 99 }) },
    history: [],
    missing_slots: [],
  };
  assert.throws(
    () => validateIdentitySelections(selections, binding),
    /ownership boundary/,
  );
});

test("incompatible slot types, usage restrictions, and cross-owner assets are unavailable", () => {
  assert.equal(isAssetCompatibleWithSlot(asset(), "header_logo", binding), true);
  assert.equal(
    isAssetCompatibleWithSlot(asset({ asset_type: "favicon" }), "header_logo", binding),
    false,
  );
  assert.equal(
    isAssetCompatibleWithSlot(asset({ approved_usage: ["website_footer"] }), "header_logo", binding),
    false,
  );
  assert.equal(
    isAssetCompatibleWithSlot(asset({ restrictions: ["website_header"] }), "header_logo", binding),
    false,
  );
  assert.equal(
    isAssetCompatibleWithSlot(asset({ brand_id: 99 }), "header_logo", binding),
    false,
  );
});

test("approved descendants supersede every ancestor across retired intermediate versions", () => {
  const first = asset({ id: 1, version: 1 });
  const second = asset({
    id: 2,
    version: 2,
    status: "retired",
    replaces_brand_asset_id: 1,
  });
  const third = asset({ id: 3, version: 3, replaces_brand_asset_id: 2 });
  assert.deepEqual(currentApprovedAssets([first, second, third]).map((item) => item.id), [3]);
});

test("retired descendants with durable approval provenance never resurrect an ancestor", () => {
  const first = asset({ id: 1, version: 1 });
  const second = asset({
    id: 2,
    version: 2,
    status: "retired",
    approved_at: "2026-08-01T01:00:00Z",
    replaces_brand_asset_id: 1,
  });
  const third = asset({
    id: 3,
    version: 3,
    status: "retired",
    approved_at: "2026-08-01T02:00:00Z",
    replaces_brand_asset_id: 2,
  });
  assert.deepEqual(currentApprovedAssets([first, second, third]), []);
});

const resolvedAssets = {
  header_logo: {
    asset_type: "primary_logo",
    asset_url: "/assets/header.png",
    accessibility_description: "Flo-Zone primary logo",
  },
  footer_logo: {
    asset_type: "alternate_logo",
    asset_url: "/assets/footer.png",
    accessibility_description: "Flo-Zone footer logo",
  },
  favicon: {
    asset_type: "favicon",
    asset_url: "/assets/favicon.png",
    accessibility_description: "Flo-Zone favicon",
  },
  browser_icon: {
    asset_type: "browser_icon",
    asset_url: "/assets/browser.png",
    accessibility_description: "Flo-Zone browser icon",
  },
  apple_touch_icon: {
    asset_type: "apple_touch_icon",
    asset_url: "/assets/apple.png",
    accessibility_description: "Flo-Zone Apple Touch icon",
  },
  open_graph_image: {
    asset_type: "open_graph_image",
    asset_url: "/assets/social.png",
    accessibility_description: "Flo-Zone social identity",
  },
};

function component(
  componentKey: "website_header" | "website_footer",
  identityAssets: Record<string, unknown>,
): PageComponentInstance {
  return {
    instance_key: componentKey,
    component_key: componentKey,
    contract_version: 1,
    region: componentKey === "website_header" ? "header" : "footer",
    position: 0,
    variant: "default",
    input_bindings: {},
    resolved_data: {
      identity_assets: identityAssets,
      display_name: "Flo-Zone Pest And Termite Solutions Inc.",
      company_name: "Flo-Zone Pest And Termite Solutions Inc.",
      tagline: "Local expertise",
      business_type: "Pest control service",
    },
  };
}

test("header and footer render governed logos with accessible descriptions", () => {
  const header = renderToStaticMarkup(renderComponent(component("website_header", resolvedAssets)));
  const footer = renderToStaticMarkup(renderComponent(component("website_footer", resolvedAssets)));
  assert.match(header, /class="previewBrandLogo"/);
  assert.match(header, /src="\/assets\/header\.png"/);
  assert.match(header, /alt="Flo-Zone primary logo"/);
  assert.match(footer, /class="previewBrandLogo previewFooterLogo"/);
  assert.match(footer, /src="\/assets\/footer\.png"/);
  assert.match(footer, /alt="Flo-Zone footer logo"/);
});

test("missing or incompatible identity assets retain safe text fallback", () => {
  const missingHeader = renderToStaticMarkup(
    renderComponent(component("website_header", {})),
  );
  const incompatibleHeader = renderToStaticMarkup(
    renderComponent(
      component("website_header", {
        header_logo: { ...resolvedAssets.header_logo, asset_type: "favicon" },
      }),
    ),
  );
  const footer = renderToStaticMarkup(renderComponent(component("website_footer", {})));
  assert.match(missingHeader, /previewBrandMark/);
  assert.match(missingHeader, /Flo-Zone Pest And Termite Solutions Inc\./);
  assert.match(incompatibleHeader, /previewBrandMark/);
  assert.doesNotMatch(incompatibleHeader, /<img/);
  assert.match(footer, /Flo-Zone Pest And Termite Solutions Inc\./);
  assert.doesNotMatch(footer, /<img/);
});

test("favicon, shortcut icon, Apple Touch, and Open Graph descriptors are exact", () => {
  assert.deepEqual(identityHeadDescriptors(resolvedAssets), [
    {
      tag: "link",
      slot: "favicon",
      attributes: { rel: "icon", href: "/assets/favicon.png" },
    },
    {
      tag: "link",
      slot: "browser_icon",
      attributes: { rel: "shortcut icon", href: "/assets/browser.png" },
    },
    {
      tag: "link",
      slot: "apple_touch_icon",
      attributes: { rel: "apple-touch-icon", href: "/assets/apple.png" },
    },
    {
      tag: "meta",
      slot: "open_graph_image",
      attributes: { property: "og:image", content: "/assets/social.png" },
    },
    {
      tag: "meta",
      slot: "open_graph_image",
      attributes: {
        property: "og:image:alt",
        content: "Flo-Zone social identity",
      },
    },
  ]);
});

test("identity head tags are installed, attributed, and completely removed", () => {
  const nodes: FakeElement[] = [];
  const fakeDocument = {
    createElement(tag: "link" | "meta") {
      return new FakeElement(tag);
    },
    head: {
      appendChild(node: FakeElement) {
        nodes.push(node);
        return node;
      },
    },
  } as unknown as Document;
  const cleanup = installIdentityHeadTags(fakeDocument, resolvedAssets);
  assert.equal(nodes.length, 5);
  assert.deepEqual(
    nodes.map((node) => node.attributes["data-atlas-identity-slot"]),
    ["favicon", "browser_icon", "apple_touch_icon", "open_graph_image", "open_graph_image"],
  );
  assert.ok(nodes.every((node) => node.attributes["data-atlas-identity"] === "true"));
  cleanup();
  assert.ok(nodes.every((node) => node.removed));
});

test("starting a new preview removes every previously installed identity head tag", () => {
  const nodes: FakeElement[] = [];
  const fakeDocument = {
    createElement(tag: "link" | "meta") {
      return new FakeElement(tag);
    },
    head: {
      appendChild(node: FakeElement) {
        nodes.push(node);
        return node;
      },
    },
    querySelectorAll(selector: string) {
      assert.equal(selector, '[data-atlas-identity="true"]');
      return nodes.filter((node) => !node.removed);
    },
  } as unknown as Document;
  installIdentityHeadTags(fakeDocument, resolvedAssets);
  assert.equal(nodes.filter((node) => !node.removed).length, 5);
  removeIdentityHeadTags(fakeDocument);
  assert.equal(nodes.filter((node) => !node.removed).length, 0);

  const source = readFileSync(
    resolve(process.cwd(), "src/pages/GeneratedPagePreview.tsx"),
    "utf8",
  );
  assert.match(source, /const generation = \+\+loadGeneration\.current/);
  assert.match(source, /setData\(null\)/);
  assert.match(source, /removeIdentityHeadTags\(document\)/);
  assert.match(source, /if \(!isCurrentLoad\(\)\) return/);
  assert.match(source, /useLayoutEffect\(\(\) => \{/);
});

test("request-key guard hides valid prior content during new and failed navigation", () => {
  const firstKey = previewRequestKey("65", false);
  const nextKey = previewRequestKey("66", false);
  const firstData = { requestKey: firstKey };

  assert.equal(hasCurrentPreviewData(firstKey, firstKey, firstData), true);
  // The route key changes synchronously before effects reset the old state.
  assert.equal(hasCurrentPreviewData(nextKey, firstKey, firstData), false);
  // The new request starts and clears data before a failed response is shown.
  assert.equal(hasCurrentPreviewData(nextKey, nextKey, null), false);
  // A late prior response remains invisible even after the new error state commits.
  assert.equal(hasCurrentPreviewData(nextKey, nextKey, firstData), false);
});

test("malformed or slot-incompatible head assets are not inserted", () => {
  assert.deepEqual(
    identityHeadDescriptors({
      favicon: { ...resolvedAssets.favicon, asset_type: "open_graph_image" },
      browser_icon: { ...resolvedAssets.browser_icon, accessibility_description: "" },
      open_graph_image: { ...resolvedAssets.open_graph_image, asset_url: "" },
    }),
    [],
  );
});

test("only HTTP(S) and single-root-relative governed asset URLs are accepted", () => {
  assert.equal(isSafeIdentityAssetUrl("/api/brand-assets/1/file"), true);
  assert.equal(isSafeIdentityAssetUrl("https://assets.example.test/logo.png"), true);
  assert.equal(isSafeIdentityAssetUrl("http://localhost:8000/logo.png"), true);
  assert.equal(isSafeIdentityAssetUrl("//attacker.example/logo.png"), false);
  assert.equal(isSafeIdentityAssetUrl("javascript:alert(1)"), false);
  assert.equal(isSafeIdentityAssetUrl("data:image/svg+xml,<svg/>"), false);
  assert.equal(isSafeIdentityAssetUrl("relative/logo.png"), false);
});

test("unsafe identity URLs fall back to text and never emit head tags", () => {
  const unsafeAssets = {
    header_logo: {
      ...resolvedAssets.header_logo,
      asset_url: "javascript:alert(1)",
    },
    favicon: {
      ...resolvedAssets.favicon,
      asset_url: "data:image/png;base64,unsafe",
    },
    open_graph_image: {
      ...resolvedAssets.open_graph_image,
      asset_url: "//attacker.example/social.png",
    },
  };
  const header = renderToStaticMarkup(
    renderComponent(component("website_header", unsafeAssets)),
  );
  assert.match(header, /previewBrandMark/);
  assert.doesNotMatch(header, /<img/);
  assert.deepEqual(identityHeadDescriptors(unsafeAssets), []);
});

test("stale composition after an identity replacement remains fail-closed", () => {
  const composition: PageComposition = {
    id: 1,
    website_id: 31,
    site_plan_id: 1,
    planned_page_id: 1,
    generated_page_id: 1,
    composition_version: 1,
    generated_components: [],
    operator_decisions: [],
    effective_components: [],
    source_snapshot: {},
    source_hash: "a".repeat(64),
    status: "stale",
    validation_errors: [],
    generated_at: "2026-08-01T00:00:00Z",
  };
  assert.equal(
    compositionValidationError(composition),
    "The semantic page composition is not current.",
  );
  assert.equal(compositionValidationError({ ...composition, status: "current" }), null);
});

test("responsive logo constraints are explicit for header, footer, and mobile", () => {
  const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
  assert.match(css, /\.previewBrandLogo\s*\{[^}]*max-width:\s*min\(180px, 42vw\)/s);
  assert.match(css, /\.previewBrandLogo\s*\{[^}]*max-height:\s*48px[^}]*object-fit:\s*contain/s);
  assert.match(css, /\.previewFooterLogo\s*\{[^}]*max-width:\s*min\(150px, 42vw\)[^}]*max-height:\s*42px/s);
  assert.match(css, /@media \(max-width: 620px\)[\s\S]*?\.previewBrandLogo\s*\{[^}]*max-width:\s*min\(150px, 48vw\)/);
});

test("Brand Assets UI does not independently list Brand or Website Identity selectors", () => {
  const source = readFileSync(resolve(process.cwd(), "src/pages/BrandAssetsPage.tsx"), "utf8");
  assert.match(source, /Authoritative Website Context/);
  assert.match(source, /\/api\/websites\/\$\{selectedWebsiteId\}\/context/);
  assert.doesNotMatch(source, /apiRequest<Brand\[\]>\("\/api\/brands"\)/);
  assert.doesNotMatch(source, /apiRequest<WebsiteIdentity\[\]>\("\/api\/website-identities"\)/);
  assert.match(source, /Rationale for this Website Identity asset selection/);
  assert.doesNotMatch(source, /rationale:\s*"Approved Website Identity selection"/);
  assert.match(source, /name="provenance_notes" required/);
  assert.match(source, /name="rights_holder" required/);
  assert.match(source, /name="rights_notes" required/);
  assert.match(source, /Creator \/ source identity/);
});

test("a prohibited-usage decision is required before asset submission", () => {
  assert.equal(hasProhibitedUsageDecision([]), false);
  assert.equal(hasProhibitedUsageDecision([""]), false);
  assert.equal(hasProhibitedUsageDecision(["website_header"]), true);
});

test("approval review renders complete governed evidence before the action", () => {
  const checksum = "0123456789abcdef".repeat(4);
  const reviewAsset = asset({
    version: 3,
    replaces_brand_asset_id: 2,
    original_filename: "flo-zone-primary-logo.png",
    mime_type: "image/png",
    file_size: 12_345,
    width: 1200,
    height: 400,
    checksum_sha256: checksum,
    provenance_type: "company_original",
    provenance_notes: "Supplied from the approved company source package.",
    rights_status: "owned",
    rights_holder: "Flo-Zone Pest And Termite Solutions Inc.",
    rights_notes: "Approved for the governed Website identity roles.",
    created_by: "Shawn Manchette",
    purpose: "Primary logo for Website identity",
    approved_usage: ["website_header", "website_footer"],
    restrictions: ["browser_tab"],
    accessibility_description: "Flo-Zone Pest And Termite Solutions logo",
  });
  const html = renderToStaticMarkup(<BrandAssetEvidence asset={reviewAsset} />);
  for (const expected of [
    "Version 3",
    "Replaces Brand Asset 2",
    "Primary Logo",
    "Primary logo for Website identity",
    "Website Header, Website Footer",
    "Browser Tab",
    "Flo-Zone Pest And Termite Solutions logo",
    "flo-zone-primary-logo.png",
    "image/png",
    "12345 bytes",
    "1200×400 pixels",
    checksum,
    "Company Original",
    "Supplied from the approved company source package.",
    "Owned",
    "Flo-Zone Pest And Termite Solutions Inc.",
    "Approved for the governed Website identity roles.",
    "Shawn Manchette",
  ]) {
    assert.match(html, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  const source = readFileSync(resolve(process.cwd(), "src/pages/BrandAssetsPage.tsx"), "utf8");
  assert.ok(source.indexOf("<BrandAssetEvidence asset={asset} />") < source.indexOf("Approve asset"));
  assert.doesNotMatch(html, /0123456789ab…/);
});

class FakeElement {
  readonly attributes: Record<string, string> = {};
  removed = false;

  constructor(readonly tagName: string) {}

  setAttribute(name: string, value: string) {
    this.attributes[name] = value;
  }

  remove() {
    this.removed = true;
  }
}
