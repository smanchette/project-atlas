import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";

import {
  PerformanceLocalRenderer,
  performanceLocalDiagnostics,
  type PerformanceLocalCampaign,
  type PerformanceLocalRuntimeToggles,
} from "../src/components/PerformanceLocalRenderer";
import {
  ATLAS_DIAGNOSTIC_THEME,
  PERFORMANCE_LOCAL_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_THEME,
  performanceLocalOptionalComponentAttributes,
  performanceLocalOptionalConfiguration,
  performanceLocalViewport,
  resolveOptionalComponent,
} from "../src/components/performanceLocalTheme";
import type {
  GeneratedPage,
  PageComponentInstance,
  PageComposition,
} from "../src/types";
import { selectedTheme } from "./theme-fixtures";

const websiteId = 31;
const enabledToggles: PerformanceLocalRuntimeToggles = {
  campaignBanner: true,
  compactEstimateForm: true,
  finalCta: true,
  stickyActionBar: true,
  trustStrip: true,
};
const disabledToggles: PerformanceLocalRuntimeToggles = {
  campaignBanner: false,
  compactEstimateForm: false,
  finalCta: false,
  stickyActionBar: false,
  trustStrip: false,
};

test("optional provider, proof, location, and language contracts fail closed without exact evidence", () => {
  const optionalKeys = [
    "review_badge_group",
    "statistics_counter_band",
    "video_embed_section",
    "map_or_service_area_section",
    "community_program_section",
    "language_selector",
  ] as const;
  for (const key of optionalKeys) {
    const absent = resolveOptionalComponent(key, null, websiteId, "desktop");
    assert.equal(absent.visible, false);
    const incomplete = resolveOptionalComponent(key, { enabled: true, websiteId }, websiteId, "desktop");
    assert.equal(incomplete.visible, false);
    assert.ok(incomplete.errors.length > 0);
  }
  const crossWebsite = resolveOptionalComponent(
    "review_badge_group",
    performanceLocalOptionalConfiguration(
      "review_badge_group",
      websiteId + 1,
      "Approved review evidence",
      {
        provider: "Approved provider",
        rating: 4.8,
        reviewCount: 24,
        ratingApprovalStatus: "approved",
        reviewCountApprovalStatus: "approved",
        verificationDate: "2026-08-12",
        destination: "/reviews",
        trademarkUseAuthorization: "approval-1",
      },
    ),
    websiteId,
    "desktop",
  );
  assert.equal(crossWebsite.visible, false);
  assert.ok(crossWebsite.errors.some((error) => error.includes("Website boundary")));
});

test("production estimate forms fail closed without provider, privacy, retention, and audit controls", () => {
  const preview = resolveOptionalComponent(
    "compact_estimate_form",
    performanceLocalOptionalConfiguration(
      "compact_estimate_form",
      websiteId,
      "Estimate request preview",
      { previewOnly: true, productionMode: false },
    ),
    websiteId,
    "desktop",
  );
  assert.equal(preview.visible, true);
  const production = resolveOptionalComponent(
    "compact_estimate_form",
    performanceLocalOptionalConfiguration(
      "compact_estimate_form",
      websiteId,
      "Estimate request",
      { previewOnly: false, productionMode: true },
    ),
    websiteId,
    "desktop",
  );
  assert.equal(production.visible, false);
  assert.ok(production.errors.some((error) => error.includes("privacyPolicyDestination")));
  assert.ok(production.errors.some((error) => error.includes("auditIdentity")));
});

test("visible optional components use one Website-scoped contract and expose exact diagnostics", () => {
  const configuration = performanceLocalOptionalConfiguration(
    "trust_proof_strip",
    websiteId,
    "Approved business credentials",
    { sourceIdentity: "trust-instance", approvalIdentity: "source-hash" },
  );
  const resolution = resolveOptionalComponent(
    "trust_proof_strip",
    configuration,
    websiteId,
    "desktop",
  );
  assert.equal(resolution.visible, true);
  const attributes = performanceLocalOptionalComponentAttributes("trust_proof_strip", resolution);
  assert.deepEqual(attributes, {
    "data-component-key": "trust_proof_strip",
    "data-component-version": "1",
    "data-component-optional": "true",
    "data-component-scope": "website_with_optional_page_override",
    "data-component-placement": "after_hero",
    "data-component-variant": "approved_facts_only",
    "data-component-content-source": "governed_semantic_composition",
    "data-component-theme-compatibility": "performance-local@1",
    "data-component-resolution": "visible",
  });
  assert.throws(
    () => performanceLocalOptionalComponentAttributes("visual_cta_band", resolution),
    /fail-closed resolution/,
  );

  const exactOverride = { ...configuration, pageOverrideId: 1101 };
  assert.equal(
    resolveOptionalComponent(
      "trust_proof_strip",
      exactOverride,
      websiteId,
      "desktop",
      new Date("2026-08-12T12:00:00Z"),
      1101,
    ).visible,
    true,
  );
  const wrongPage = resolveOptionalComponent(
    "trust_proof_strip",
    exactOverride,
    websiteId,
    "desktop",
    new Date("2026-08-12T12:00:00Z"),
    1102,
  );
  assert.equal(wrongPage.visible, false);
  assert.ok(wrongPage.errors.some((error) => error.includes("Page override boundary")));
});

function component(
  instanceKey: string,
  componentKey: string,
  region: "header" | "main" | "footer",
  resolvedData: Record<string, unknown>,
  inputBindings: Record<string, unknown> = {},
  position = 0,
): PageComponentInstance {
  return {
    instance_key: instanceKey,
    component_key: componentKey,
    contract_version: 1,
    region,
    position,
    variant: "default",
    input_bindings: inputBindings,
    resolved_data: resolvedData,
  };
}

function navigationItem(
  id: number,
  plannedPageId: number,
  generatedPageId: number,
  label: string,
  position: number,
  parentId: number | null = null,
) {
  return {
    navigation_item_id: id,
    target_planned_page_id: plannedPageId,
    target_generated_page_id: generatedPageId,
    parent_navigation_item_id: parentId,
    position,
    status: "active",
    label,
    slug: label.toLowerCase().replace(/\s+/g, "-"),
  };
}

function fixtureComponents(options: { phone?: string; mediaDuplicates?: boolean } = {}) {
  const phone = options.phone === undefined ? "+1 555 010 0200" : options.phone;
  const components: PageComponentInstance[] = [
    component("header-1", "website_header", "header", {
      company_name: "Example Local Service",
      display_name: "Example Local Service",
      email: "hello@example.test",
      identity_assets: {},
      phone,
      tagline: "Approved local help",
    }),
    component("primary-nav-1", "primary_navigation", "header", {
      label: "Primary navigation",
      items: [
        navigationItem(1, 11, 101, "Home", 0),
        navigationItem(2, 12, 102, "Services", 1),
        navigationItem(3, 13, 103, "Example service", 0, 2),
      ],
    }),
    component("utility-nav-1", "utility_navigation", "header", {
      label: "Utility navigation",
      items: [navigationItem(4, 14, 104, "Contact", 0)],
    }),
    component("hero-1", "hero", "main", {
      intro: "An approved concise introduction.",
      page_type: "service",
      phone,
      title: "Example approved service",
    }),
    component("trust-1", "trust_license", "main", {
      certified_operator: "Approved operator",
      license_number: "LIC-123",
    }),
    component("section-1", "content_section", "main", {
      body: "Approved authority content remains unchanged.",
      heading: "Why it matters",
    }),
    component(
      "media-1",
      "media_placement",
      "main",
      {
        alt_text: "Approved supporting visual",
        asset_url: "/media/approved-support.webp",
        caption: "Approved caption",
        effective_display_preset: "hero_desktop",
        focal_x: 0.4,
        focal_y: 0.6,
        image_role: "process",
        image_title: "Approved visual",
        placement_contract_version: 2,
        stored_display_preset: "hero_desktop",
      },
      {
        placement_contract_version: 2,
        target_component_instance_key: "section-1",
      },
      1,
    ),
    component("related-1", "related_page_links", "main", {
      links: [
        {
          label: "Related approved page",
          purpose: "Continue the visitor journey",
          slug: "related-approved-page",
          target_generated_page_id: 105,
          target_planned_page_id: 15,
        },
      ],
    }),
    component("faq-1", "faq", "main", {
      items: [{ question: "What happens next?", answer: "An approved answer." }],
    }),
    component("contact-1", "contact_pathways", "main", {
      display_name: "Example Local Service",
    }),
    component("final-1", "final_cta", "main", {
      body: "Use an approved contact pathway.",
      heading: "Ready to get started?",
    }),
    component("footer-nav-1", "footer_navigation", "footer", {
      label: "Footer navigation",
      items: [navigationItem(5, 16, 106, "Privacy", 0)],
    }),
    component("footer-1", "website_footer", "footer", {
      business_type: "Local service business",
      company_name: "Example Local Service",
      email: "hello@example.test",
      identity_assets: {},
      license_number: "LIC-123",
      phone,
    }),
  ];
  if (options.mediaDuplicates) {
    components.push(
      component(
        "media-duplicate",
        "media_placement",
        "main",
        {
          alt_text: "A conflicting visual",
          asset_url: "/media/conflicting.webp",
          effective_display_preset: "hero_desktop",
          placement_contract_version: 2,
          stored_display_preset: "hero_desktop",
        },
        {
          placement_contract_version: 2,
          target_component_instance_key: "section-1",
        },
        2,
      ),
    );
  }
  return components;
}

function composition(
  effectiveComponents = fixtureComponents(),
  overrides: Partial<PageComposition> = {},
): PageComposition {
  return {
    id: 801,
    website_id: websiteId,
    site_plan_id: 901,
    planned_page_id: 1001,
    generated_page_id: 1101,
    composition_version: 8,
    generated_components: [],
    operator_decisions: [],
    effective_components: effectiveComponents,
    source_snapshot: {},
    source_hash: "c".repeat(64),
    resolved_theme: selectedTheme(),
    status: "current",
    validation_errors: [],
    generated_at: "2026-08-12T12:00:00Z",
    ...overrides,
  };
}

function page(overrides: Partial<GeneratedPage> = {}): GeneratedPage {
  return {
    id: 1101,
    business_id: 21,
    website_id: websiteId,
    service_id: 5,
    page_type: "service",
    page_title: "Example approved service",
    page_slug: "example-approved-service",
    generation_status: "generated",
    qa_status: "ready",
    status: "draft",
    created_at: "2026-08-12T12:00:00Z",
    updated_at: "2026-08-12T12:00:00Z",
    ...overrides,
  };
}

function campaign(overrides: Partial<PerformanceLocalCampaign> = {}): PerformanceLocalCampaign {
  return {
    ...performanceLocalOptionalConfiguration(
      "campaign_banner",
      websiteId,
      "Approved campaign",
    ),
    approvalIdentity: "operator-approval-1",
    campaignLabel: "Request an approved estimate",
    ctaDestination: "#estimate",
    ctaLabel: "Request estimate",
    enabled: true,
    endDate: "2026-08-31T23:59:59Z",
    startDate: "2026-08-01T00:00:00Z",
    termsReference: "approved-terms-1",
    websiteId,
    ...overrides,
  };
}

function render(
  toggles: PerformanceLocalRuntimeToggles,
  options: {
    brandAccent?: string | null;
    campaign?: PerformanceLocalCampaign | null;
    composition?: PageComposition;
    page?: GeneratedPage;
    previewedAt?: Date;
  } = {},
) {
  return renderToStaticMarkup(
    <StaticRouter location="/theme-lab/generated-pages/1101">
      <PerformanceLocalRenderer
        brandAccent={options.brandAccent}
        campaign={options.campaign}
        composition={options.composition ?? composition()}
        page={options.page ?? page()}
        toggles={toggles}
        previewedAt={options.previewedAt ?? new Date("2026-08-12T12:00:00Z")}
      />
    </StaticRouter>,
  );
}

test("the performance renderer consumes composition identity without mutating Atlas inputs", () => {
  const sourceComposition = composition();
  const sourcePage = page();
  const beforeComposition = structuredClone(sourceComposition);
  const beforePage = structuredClone(sourcePage);
  const markup = render(enabledToggles, {
    campaign: campaign(),
    composition: sourceComposition,
    page: sourcePage,
  });
  assert.match(markup, /data-atlas-adapter="performance-local"/);
  assert.match(markup, /data-atlas-adapter-version="1"/);
  assert.match(markup, /data-composition-id="801"/);
  assert.match(markup, /data-composition-version="8"/);
  assert.match(markup, /data-generated-page-id="1101"/);
  assert.deepEqual(sourceComposition, beforeComposition);
  assert.deepEqual(sourcePage, beforePage);
});

test("stale, cross-Website, and mismatched page compositions fail closed", () => {
  const staleMarkup = render(disabledToggles, {
    composition: composition(fixtureComponents(), { status: "stale" }),
  });
  assert.match(staleMarkup, /Performance Local preview unavailable/);
  assert.match(staleMarkup, /composition is not current/);
  assert.doesNotMatch(staleMarkup, /performanceLocalHeader/);

  const wrongWebsiteMarkup = render(disabledToggles, {
    page: page({ website_id: websiteId + 1 }),
  });
  assert.match(wrongWebsiteMarkup, /cross the Website ownership boundary/);
  assert.doesNotMatch(wrongWebsiteMarkup, /performanceLocalHeader/);

  const wrongPageMarkup = render(disabledToggles, {
    page: page({ id: 9999 }),
  });
  assert.match(wrongPageMarkup, /does not belong to this Generated Page/);
  assert.doesNotMatch(wrongPageMarkup, /performanceLocalHeader/);
});

test("disabled optional capabilities render no wrapper, placeholder, or dead action", () => {
  const markup = render(disabledToggles, { campaign: campaign() });
  for (const className of [
    "performanceLocalCampaign",
    "performanceLocalTrustStrip",
    "performanceLocalFinalCta",
    "performanceLocalEstimateForm",
    "performanceLocalStickyActions",
  ]) {
    assert.doesNotMatch(markup, new RegExp(`class="${className}`));
  }
  assert.doesNotMatch(markup, /Request an approved estimate/);
  assert.doesNotMatch(markup, /data-component-key="compact_estimate_form"/);
});

test("missing governed phone hides every Call action and an empty sticky bar", () => {
  const withoutPhone = composition(fixtureComponents({ phone: "" }));
  const markup = render(
    { ...disabledToggles, stickyActionBar: true },
    { composition: withoutPhone },
  );
  assert.doesNotMatch(markup, /href="tel:/);
  assert.doesNotMatch(markup, />Call(?:\s|<)/);
  assert.doesNotMatch(markup, /class="performanceLocalStickyActions/);
});

test("missing approved estimate destination hides every Estimate action", () => {
  const markup = render({
    ...disabledToggles,
    finalCta: true,
    stickyActionBar: true,
  });
  assert.doesNotMatch(markup, />Request estimate</);
  assert.doesNotMatch(markup, /href="#estimate"/);
  assert.match(markup, /class="performanceLocalStickyActions/);
  assert.match(markup, /href="tel:\+15550100200"/);
});

test("campaigns render only for exact Website ownership, approval evidence, safe destinations, and active dates", () => {
  const valid = render(enabledToggles, { campaign: campaign() });
  assert.match(valid, /class="performanceLocalCampaign"/);
  assert.match(valid, /Request an approved estimate/);

  for (const invalid of [
    campaign({ approvalIdentity: "" }),
    campaign({ ctaDestination: "https://external.example/estimate" }),
    campaign({ ctaDestination: "tel:------" }),
    campaign({ websiteId: websiteId + 1 }),
    campaign({ endDate: "2026-08-02T00:00:00Z", startDate: "2026-08-03T00:00:00Z" }),
  ]) {
    const markup = render(enabledToggles, { campaign: invalid });
    assert.doesNotMatch(markup, /class="performanceLocalCampaign"/);
  }
  const expired = render(enabledToggles, {
    campaign: campaign(),
    previewedAt: new Date("2026-09-01T00:00:00Z"),
  });
  assert.doesNotMatch(expired, /class="performanceLocalCampaign"/);
  assert.match(expired, /outside its approved active dates/);
});

test("the Theme Lab accent override accepts opaque hex only and derives readable text contrast", () => {
  const valid = render(disabledToggles, { brandAccent: "#83F441" });
  assert.match(valid, /data-runtime-brand-accent="validated-preview-override"/);
  assert.match(valid, /--performance-local-accent:#83F441/);
  assert.match(valid, /--performance-local-accent-text:#000000/);

  const transparent = render(disabledToggles, { brandAccent: "#83F44180" });
  assert.match(transparent, /data-runtime-brand-accent="governed-primary"/);
  assert.doesNotMatch(transparent, /--performance-local-accent:/);
});

test("the preview estimate form is explicit, inert, local, and has no persistence destination", () => {
  const markup = render(enabledToggles);
  assert.match(markup, /<form[^>]+aria-label="Estimate request preview"/);
  assert.match(markup, /data-preview-only="true"/);
  assert.match(markup, /autocomplete="off"/i);
  assert.match(markup, /Preview only\. Information entered here is not submitted or saved\./);
  for (const field of [
    "preview-name",
    "preview-phone",
    "preview-postal-code",
    "preview-requested-service",
    "preview-message",
  ]) {
    assert.match(markup, new RegExp(`name="${field}"`));
  }
  assert.doesNotMatch(markup, /\saction=/);
  assert.doesNotMatch(markup, /\smethod=/);
  assert.doesNotMatch(markup, /fetch\(|XMLHttpRequest|navigator\.sendBeacon/);
});

test("desktop dropdown and mobile navigation are collapsed in initial output", () => {
  const markup = render(disabledToggles);
  assert.match(markup, /aria-label="Toggle Services submenu"[^>]+aria-expanded="false"/);
  assert.match(markup, /id="performance-local-submenu-2"[^>]+hidden=""/);
  assert.match(markup, /aria-label="Open website navigation"[^>]+aria-expanded="false"/);
  assert.doesNotMatch(markup, /role="dialog"/);
  assert.match(markup, /<main id="main-content">/);
  assert.match(markup, /href="#main-content"/);
});

test("governed media binds once to its exact component, preserves alt and role, and never crops", () => {
  const markup = render(disabledToggles);
  assert.equal((markup.match(/src="\/media\/approved-support\.webp"/g) ?? []).length, 1);
  assert.match(markup, /alt="Approved supporting visual"/);
  assert.match(markup, /data-semantic-media-role="process"/);
  assert.match(markup, /data-effective-display-preset="hero_desktop"/);
  assert.match(markup, /object-fit:contain/);
  assert.match(markup, /object-position:40% 60%/);

  const duplicateComposition = composition(fixtureComponents({ mediaDuplicates: true }));
  const duplicateMarkup = render(disabledToggles, { composition: duplicateComposition });
  assert.doesNotMatch(duplicateMarkup, /approved-support\.webp|conflicting\.webp/);
  assert.match(duplicateMarkup, /Multiple governed media placements target exact component instance section-1/);
});

test("rendered optional wrappers expose the centralized contract identity", () => {
  const markup = render(enabledToggles, { campaign: campaign() });
  for (const key of [
    "campaign_banner",
    "trust_proof_strip",
    "trust_feature_cards",
    "visual_cta_band",
    "compact_estimate_form",
    "sticky_mobile_action_bar",
  ]) {
    assert.match(markup, new RegExp(`data-component-key="${key}"`));
  }
  assert.match(markup, /data-component-version="1"/);
  assert.match(markup, /data-component-scope="website_with_optional_page_override"/);
  assert.match(markup, /data-component-theme-compatibility="performance-local@1"/);
});

test("diagnostics describe only effective enabled capabilities and preserve fail-closed warnings", () => {
  const base = composition();
  const disabled = performanceLocalDiagnostics(base, disabledToggles);
  assert.ok(disabled.enabledComponents.includes("site_header"));
  assert.ok(disabled.enabledComponents.includes("hero_conversion_section"));
  assert.ok(!disabled.enabledComponents.includes("campaign_banner"));
  assert.ok(!disabled.enabledComponents.includes("compact_estimate_form"));
  assert.deepEqual(disabled.errors, []);

  const enabled = performanceLocalDiagnostics(base, enabledToggles, { campaignVisible: true });
  for (const key of [
    "trust_proof_strip",
    "visual_cta_band",
    "compact_estimate_form",
    "sticky_mobile_action_bar",
    "campaign_banner",
  ]) {
    assert.ok(enabled.enabledComponents.includes(key), `${key} should be enabled`);
  }
  const warned = performanceLocalDiagnostics(
    composition(fixtureComponents({ mediaDuplicates: true })),
    disabledToggles,
    { campaignError: "Campaign configuration is incomplete." },
  );
  assert.ok(warned.warnings.some((warning) => warning.includes("Multiple governed media")));
  assert.ok(warned.warnings.includes("Campaign configuration is incomplete."));
});

test("generic renderer source contains no business, Page, requirement, reference-domain, or asset hardcodes", () => {
  const sourcePath = resolve(process.cwd(), "src/components/PerformanceLocalRenderer.tsx");
  const source = readFileSync(sourcePath, "utf8");
  for (const prohibited of [
    /Flo-Zone/i,
    /drywood/i,
    /Orlando/i,
    /Page\s*41/i,
    /Requirement\s*25[678]/i,
    /pestcontrolinorlandofl/i,
    /\$29\.99/,
    /\(321\)\s*559[-\s]*7378/,
    /media-3[123]|requirement-25[678]/i,
  ]) {
    assert.doesNotMatch(source, prohibited);
  }
  assert.doesNotMatch(source, /https?:\/\//);
  assert.doesNotMatch(source, /fetch\(|XMLHttpRequest|navigator\.sendBeacon|localStorage|sessionStorage/);
});

test("Theme Lab is a top-level local read-only route over the exact current page and composition APIs", () => {
  const appSource = readFileSync(resolve(process.cwd(), "src/App.tsx"), "utf8");
  const labSource = readFileSync(resolve(process.cwd(), "src/pages/ThemeLabPage.tsx"), "utf8");
  assert.match(appSource, /path="\/theme-lab\/generated-pages\/:id"/);
  assert.match(labSource, /data-theme-lab="local-only"/);
  assert.match(labSource, /Not selected or published/);
  assert.match(labSource, /`\/api\/generated-pages\/\$\{pageId\}`/);
  assert.match(labSource, /`\/api\/site-plans\/generated-pages\/\$\{pageId\}\/composition`/);
  assert.doesNotMatch(labSource, /method:\s*"(?:POST|PUT|PATCH|DELETE)"/);
  assert.doesNotMatch(labSource, /localStorage|sessionStorage|navigator\.sendBeacon|XMLHttpRequest/);
  assert.doesNotMatch(labSource, /Flo-Zone|drywood|Orlando|Page\s*41|pestcontrolinorlandofl/i);
});

test("responsive CSS reserves safe sticky space, preserves governed media, and keeps controls accessible", () => {
  const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");
  assert.doesNotMatch(css, /\.performanceLocalSite\s*\{[^}]*overflow-x:\s*(?:clip|hidden)/s);
  assert.match(css, /\.performanceLocalMedia-hero-desktop[^}]*aspect-ratio:\s*16\s*\/\s*9/s);
  assert.match(css, /\.performanceLocalMedia img\s*\{[^}]*object-fit:\s*contain/s);
  assert.match(css, /\.performanceLocalButton[^}]*min-height:\s*48px/s);
  assert.match(css, /\.performanceLocalMenuTrigger[^}]*width:\s*48px[^}]*height:\s*48px/s);
  assert.match(css, /@media \(max-width:\s*1100px\)[\s\S]*\.performanceLocalCardGrid\s*\{[^}]*repeat\(2/s);
  assert.match(css, /@media \(max-width:\s*760px\)[\s\S]*\.performanceLocalSplitGrid[^}]*grid-template-columns:\s*1fr/s);
  assert.match(css, /\.performanceLocalSite\[data-sticky-actions-visible="true"\] \.performanceLocalFooter\s*\{[^}]*padding-bottom:\s*calc\(116px \+ env\(safe-area-inset-bottom\)\)/s);
  assert.match(css, /\.performanceLocalStickyActions\s*\{[^}]*bottom:\s*0[^}]*env\(safe-area-inset-bottom\)/s);
  assert.match(css, /\.performanceLocalBackToTop\s*\{[^}]*bottom:\s*calc\(80px \+ env\(safe-area-inset-bottom\)\)/s);
  assert.match(css, /@media \(prefers-reduced-motion:\s*reduce\)/);
});
