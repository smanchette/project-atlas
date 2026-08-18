import assert from "node:assert/strict";
import test from "node:test";

import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";

import PerformanceLocalRenderer, {
  performanceLocalFormDomId,
  type PerformanceLocalEstimateField,
} from "../src/components/PerformanceLocalRenderer";
import type { PerformanceLocalDeliveryConfiguration } from "../src/components/performanceLocalDelivery";
import {
  PerformanceLocalV4LayoutBody,
  type PerformanceLocalV4ReviewMode,
} from "../src/components/PerformanceLocalV4Layouts";
import PerformanceLocalV4Renderer, {
  exactV3ConversionInput,
  performanceLocalV4FooterBoundaryReached,
  type PerformanceLocalV4ReadinessProjection,
} from "../src/components/PerformanceLocalV4Renderer";
import {
  auditPerformanceLocalV4Composition,
  PERFORMANCE_LOCAL_V4_LAYOUT_MANIFESTS,
  type PerformanceLocalV4LayoutAudit,
  type PerformanceLocalV4PageType,
  type PerformanceLocalV4RegionKey,
} from "../src/components/performanceLocalV4LayoutContract";
import { PERFORMANCE_LOCAL_V4_DEMO_MEDIA_LABEL } from "../src/components/performanceLocalThemeV4";
import type {
  GeneratedPage,
  PageComponentInstance,
  PageComposition,
  PerformanceLocalFormReadinessRead,
  PlannedPage,
} from "../src/types";
import { selectedTheme } from "./theme-fixtures";

const websiteId = 31;
const generatedPageId = 1101;
const formConfigurationId = 44;
const hash = "a".repeat(64);
const readiness: PerformanceLocalV4ReadinessProjection = Object.freeze({
  mediaReady: false,
  qaReady: true,
  formReady: false,
  activationReady: false,
  exportReady: false,
  publicationReady: false,
});

test("six supported non-city page types use distinct V4 layout branches", () => {
  const expected = {
    home: "performanceLocalV4LayoutHome",
    service: "performanceLocalV4LayoutService",
    county: "performanceLocalV4LayoutCounty",
    about: "performanceLocalV4LayoutAbout",
    contact: "performanceLocalV4LayoutContact",
    faq: "performanceLocalV4LayoutFaq",
  } as const;
  for (const [pageType, className] of Object.entries(expected)) {
    const markup = renderToStaticMarkup(
      <StaticRouter location="/theme-lab/performance-local/v4/generated-pages/1101">
        <PerformanceLocalV4LayoutBody
          componentByInstanceKey={new Map()}
          destinationForGeneratedPageId={(id) => `/theme-lab/performance-local/v4/generated-pages/${id}`}
          estimateDestination={null}
          estimateForm={null}
          governedContact={null}
          layoutKey={PERFORMANCE_LOCAL_V4_LAYOUT_MANIFESTS[pageType as keyof typeof expected].layoutKey}
          onFormFocusRiskChange={() => undefined}
          pageType={pageType as keyof typeof expected}
          regions={[]}
          reviewMode="truthful"
        />
      </StaticRouter>,
    );
    assert.match(markup, new RegExp(className));
    assert.match(markup, new RegExp(`data-v4-page-type="${pageType}"`));
  }
});

test("long approved guidance preserves every source heading and paragraph without Markdown markers", () => {
  const source = component(
    "content_section:approved_guidance",
    "content_section",
    "main",
    {
      heading: "Approved guidance",
      body: [
        "### First exact source heading",
        "First exact source paragraph remains word-for-word.",
        "",
        "### Second exact source heading",
        "Second exact source paragraph remains word-for-word.",
        "",
        "### Third exact source heading",
        "Third exact source paragraph remains word-for-word.",
      ].join("\n"),
    },
    { section_key: "approved_guidance" },
  );
  const markup = renderToStaticMarkup(
    <StaticRouter location="/theme-lab/performance-local/v4/generated-pages/1101">
      <PerformanceLocalV4LayoutBody
        componentByInstanceKey={new Map([[source.instance_key, source]])}
        destinationForGeneratedPageId={(id) => `/theme-lab/performance-local/v4/generated-pages/${id}`}
        estimateDestination={null}
        estimateForm={null}
        governedContact={null}
        layoutKey="performance-local-v4-service"
        onFormFocusRiskChange={() => undefined}
        pageType="service"
        regions={[{
          regionKey: "approved_guidance",
          requirement: "required",
          presentationVariant: "approved_guidance",
          sourceInstanceKeys: [source.instance_key],
          presentationGroups: [],
          missing: false,
        }]}
        reviewMode="truthful"
      />
    </StaticRouter>,
  );
  for (const exactText of [
    "First exact source heading",
    "First exact source paragraph remains word-for-word.",
    "Second exact source heading",
    "Second exact source paragraph remains word-for-word.",
    "Third exact source heading",
    "Third exact source paragraph remains word-for-word.",
  ]) assert.equal(count(markup, exactText), 1, exactText);
  assert.equal((markup.match(/<h3>/g) ?? []).length, 3);
  assert.equal((markup.match(/performanceLocalV4SourceSection/g) ?? []).length, 3);
  assert.doesNotMatch(markup, /###/);
});

test("truthful Home renders one H1, complete landmarks, exact source copy, governed routes, and an inert five-field form", () => {
  const components = homeComponents();
  const markup = renderV4("home", components, homeRegions(components), "truthful");
  assert.equal((markup.match(/<h1(?:\s|>)/g) ?? []).length, 1);
  assert.match(markup, /<header class="performanceLocalV4Header"/);
  assert.match(markup, /<main id="performance-local-v4-main-content">/);
  assert.match(markup, /<footer class="performanceLocalV4Footer"/);
  assert.match(markup, /href="#performance-local-v4-main-content"/);
  assert.match(markup, />Approved Home heading</);
  assert.match(markup, />Approved service discovery</);
  assert.match(markup, />Approved value heading</);
  assert.doesNotMatch(markup, /Related pages|Frequently asked questions|Contact the business/);
  assert.match(markup, /data-v4-source-list-region="service_discovery"/);
  assert.match(markup, />Approved service: Exact source-backed description\.</);
  assert.match(markup, /href="\/theme-lab\/performance-local\/v4\/generated-pages\/1102"/);
  assert.match(markup, /data-canonical-slug="approved-related"/);
  assert.match(markup, /<form[^>]+aria-label="Estimate request preview"/);
  assert.match(markup, new RegExp(`id="${performanceLocalFormDomId(formConfigurationId)}"`));
  assert.equal((markup.match(/readonly=""/g) ?? []).length, 5);
  assert.doesNotMatch(markup, /<form[^>]+\s(?:action|method|name)=/i);
  assert.match(markup, /<button type="submit" disabled=""/);
  assert.match(markup, /data-provider-state="disabled_pending_provider_configuration"/);
  assert.match(markup, /data-collects-data="false"/);
  assert.match(markup, /data-public-action-copy="semantic_duplicate_suppressed"/);
  assert.equal((markup.match(/<strong>Request an Estimate<\/strong>/g) ?? []).length, 1);
});

test("truthful missing media omits wrappers while structural demo uses labeled DOM-only placeholders", () => {
  const components = homeComponents();
  const regions = homeRegions(components);
  const truthful = renderV4("home", components, regions, "truthful");
  const demo = renderV4("home", components, regions, "structural_demo");
  assert.doesNotMatch(truthful, new RegExp(PERFORMANCE_LOCAL_V4_DEMO_MEDIA_LABEL));
  assert.doesNotMatch(truthful, /performanceLocalV4MediaFrame/);
  assert.match(demo, /data-v4-demo-media-slot="hero"/);
  assert.match(demo, /data-v4-demo-media-slot="supporting"/);
  assert.match(demo, new RegExp(PERFORMANCE_LOCAL_V4_DEMO_MEDIA_LABEL));
  assert.match(demo, /role="img"/);
  assert.doesNotMatch(demo, /<img|background-image|\ssrc=/i);
});

test("FAQ uses exact accessible disclosures without invented categories or headings", () => {
  const base = homeComponents().filter((item) => [
    "website_header",
    "primary_navigation",
    "utility_navigation",
    "hero",
    "final_cta",
    "footer_navigation",
    "website_footer",
  ].includes(item.component_key));
  const faq = component("faq", "faq", "main", {
    items: [{ question: "Exact approved question?", answer: "Exact approved answer." }],
  }, {}, 8);
  const components = [...base.slice(0, 4), faq, ...base.slice(4)];
  const regions: RegionFixture[] = [
    ["site_header", ["website_header", "utility_navigation", "primary_navigation"]],
    ["hero", ["hero", "media_placement:hero"]],
    ["faq", ["faq"]],
    ["final_conversion", ["final_cta"]],
    ["site_footer", ["footer_navigation", "website_footer"]],
  ];
  const markup = renderV4("faq", components, regions, "truthful");
  assert.match(markup, /<details><summary>Exact approved question\?<\/summary><p>Exact approved answer\.<\/p><\/details>/);
  assert.doesNotMatch(markup, /Frequently asked questions|FAQ category|category/i);
  assert.equal((markup.match(/<h1(?:\s|>)/g) ?? []).length, 1);
});

test("a real composition audit drives purpose-built hero, media, FAQ, and form presenters exactly once", () => {
  const fixture = auditedFaqFixture();
  const audit = auditPerformanceLocalV4Composition(fixture);
  assert.equal(
    audit.status,
    "ready",
    JSON.stringify({ blockers: audit.blockers, ownership: audit.ownershipMismatches }),
  );
  assert.equal(audit.layoutReady, true);
  assert.ok(audit.regions.every((region) => region.presentationGroups.length === 0));
  const markup = renderToStaticMarkup(
    <StaticRouter location="/theme-lab/performance-local/v4/generated-pages/1101">
      <PerformanceLocalV4Renderer
        audit={audit}
        campaignBannerEnabled
        composition={fixture.composition}
        page={fixture.page}
        readiness={readiness}
        reviewMode="structural_demo"
        v3Configuration={conversionConfiguration()}
      />
    </StaticRouter>,
  );

  assert.equal((markup.match(/<h1(?:\s|>)/g) ?? []).length, 1);
  assert.match(markup, />Audited FAQ heading<\/h1>/);
  assert.match(markup, /href="tel:\+15550100200"/);
  assert.match(markup, new RegExp(`href="#${performanceLocalFormDomId(formConfigurationId)}"`));
  assert.equal((markup.match(/data-v4-demo-media-slot=/g) ?? []).length, 3);
  assert.match(markup, /<details><summary>Audited exact question\?<\/summary><p>Audited exact answer\.<\/p><\/details>/);
  assert.equal((markup.match(/readonly=""/g) ?? []).length, 5);
  assert.match(markup, /<button type="submit" disabled=""/);
  assert.match(
    markup,
    /data-v4-navigation-source-instance-keys="primary_navigation\|utility_navigation"/,
  );
  assert.match(
    markup,
    /<a[^>]+href="\/theme-lab\/performance-local\/v4\/generated-pages\/1103"[^>]*>Audited parent service<\/a>/,
  );
  assert.match(markup, /<button[^>]+aria-label="Toggle Audited parent service submenu"/);
  assert.match(markup, /aria-expanded="false"/);
  assert.match(markup, /aria-controls="performance-local-v4-submenu-[^"]+-11"/);
  assert.match(
    markup,
    /<a[^>]+href="\/theme-lab\/performance-local\/v4\/generated-pages\/1105"[^>]*>Audited county<\/a>/,
  );
  assert.doesNotMatch(markup, /Duplicate utility FAQ/);
  for (const source of fixture.composition.effective_components) {
    if (source.component_key === "primary_navigation" || source.component_key === "utility_navigation") {
      assert.equal(count(markup, source.instance_key), 1, source.instance_key);
      continue;
    }
    assert.equal(
      count(markup, `data-source-instance-key="${source.instance_key}"`),
      1,
      source.instance_key,
    );
  }
});

test("a real County audit merges the exact duplicated city prefix into governed routes once", () => {
  const fixture = auditedCountyFixture();
  const audit = auditPerformanceLocalV4Composition(fixture);
  assert.equal(
    audit.status,
    "ready",
    JSON.stringify({ blockers: audit.blockers, ownership: audit.ownershipMismatches }),
  );
  assert.deepEqual(
    audit.regions.find((region) => region.regionKey === "related_city_discovery")?.presentationGroups,
    [{
      groupKey: "performance-local-v4-service-county:related_city_discovery",
      sourceInstanceKeys: ["content_section:related_city_services", "destination_cards"],
    }],
  );
  const markup = renderToStaticMarkup(
    <StaticRouter location="/theme-lab/performance-local/v4/generated-pages/1101">
      <PerformanceLocalV4Renderer
        audit={audit}
        campaignBannerEnabled
        composition={fixture.composition}
        page={fixture.page}
        readiness={readiness}
        reviewMode="truthful"
        v3Configuration={conversionConfiguration()}
      />
    </StaticRouter>,
  );

  assert.match(
    markup,
    /data-v4-presentation-group="performance-local-v4-service-county:related_city_discovery"/,
  );
  assert.match(
    markup,
    /data-v4-group-source-instance-keys="content_section:related_city_services\|destination_cards"/,
  );
  assert.match(markup, /data-v4-source-body-consumption="deduplicated_exact_destination_label_prefix"/);
  assert.equal(count(markup, 'data-source-instance-key="content_section:related_city_services"'), 1);
  assert.equal(count(markup, 'data-source-instance-key="destination_cards"'), 1);
  assert.equal(count(markup, "Audited related city routes"), 1);
  assert.doesNotMatch(markup, /Drywood Termite Tenting in Audited City One, FL, Drywood Termite Tenting in Audited City Two, FL/);
  for (const label of [
    "Drywood Termite Tenting in Audited City One, FL",
    "Drywood Termite Tenting in Audited City Two, FL",
    "Governed service destination",
    "Governed contact destination",
  ]) assert.equal(count(markup, label), 1, label);
  for (const id of [1301, 1302, 1303, 1304]) {
    assert.match(markup, new RegExp(`href="/theme-lab/performance-local/v4/generated-pages/${id}"`));
  }
  assert.equal(count(markup, "Separate coverage-only city"), 1);
  assert.equal((markup.match(/<h1(?:\s|>)/g) ?? []).length, 1);
});

test("all V4 rendering fails closed without exact governed V3 conversion input", () => {
  const components = homeComponents();
  const composition = compositionFixture(components, "home");
  const audit = readyAudit("home", components, homeRegions(components));
  const markup = renderToStaticMarkup(
    <StaticRouter location="/theme-lab/performance-local/v4/generated-pages/1101">
      <PerformanceLocalV4Renderer
        audit={audit}
        campaignBannerEnabled
        composition={composition}
        page={pageFixture("home")}
        readiness={readiness}
        reviewMode="truthful"
        v3Configuration={null as unknown as PerformanceLocalDeliveryConfiguration}
      />
    </StaticRouter>,
  );
  assert.match(markup, /data-v4-layout-ready="false"/);
  assert.match(markup, /exact governed V3 conversion configuration is unavailable/);
  assert.doesNotMatch(markup, /class="performanceLocalV4Site"/);

  const valid = conversionConfiguration();
  assert.equal(exactV3ConversionInput(valid, composition), true);
  const tampered = {
    ...valid,
    estimateForm: {
      ...valid.estimateForm,
      fields: [...valid.estimateForm.fields, valid.estimateForm.fields[0]],
    },
  } as PerformanceLocalDeliveryConfiguration;
  assert.equal(exactV3ConversionInput(tampered, composition), false);
});

test("live footer geometry restores fixed controls after a large diagnostics-to-site scroll jump", () => {
  assert.equal(performanceLocalV4FooterBoundaryReached({
    footerTop: 1_200,
    viewportBottom: 844,
  }), false);
  assert.equal(performanceLocalV4FooterBoundaryReached({
    footerTop: 760,
    viewportBottom: 844,
  }), true);
  assert.equal(performanceLocalV4FooterBoundaryReached({
    footerTop: -900,
    viewportBottom: 844,
  }), true);
  const afterLargeJump = performanceLocalV4FooterBoundaryReached({
    footerTop: 5_400,
    viewportBottom: 844,
  });
  assert.equal(afterLargeJump, false);
  assert.equal(performanceLocalV4FooterBoundaryReached({
    footerTop: Number.NaN,
    viewportBottom: 844,
  }), true);
});

test("City-Service delegates a byte-identical legacy subtree for both banner states", () => {
  const components = homeComponents();
  const composition = compositionFixture(components, "city_service");
  const page = pageFixture("city_service");
  const audit = readyAudit("city_service", components, [
    ["site_header", ["website_header", "utility_navigation", "primary_navigation"]],
    ["hero", ["hero"]],
    ["trust", ["trust_license"]],
    ["service_context", ["content_section:primary_services"]],
    ["destination_discovery", ["related_page_links"]],
    ["final_conversion", ["final_cta"]],
    ["site_footer", ["footer_navigation", "website_footer"]],
  ]);
  const configuration = conversionConfiguration();
  const previewedAt = new Date("2026-08-17T12:00:00Z");
  for (const campaignBannerEnabled of [true, false]) {
    const toggles = { ...configuration.toggles, campaignBanner: campaignBannerEnabled };
    const direct = renderToStaticMarkup(
      <StaticRouter location="/theme-lab/performance-local/v4/generated-pages/1101">
        <PerformanceLocalRenderer
          page={page}
          composition={composition}
          campaign={campaignBannerEnabled ? configuration.campaign : null}
          estimateForm={configuration.estimateForm}
          formSubmission={configuration.formSubmission}
          governedContact={configuration.governedContact}
          rendererIdentity={configuration.rendererIdentity}
          stickyActions={configuration.stickyActions}
          toggles={toggles}
          previewedAt={previewedAt}
        />
      </StaticRouter>,
    );
    const wrapped = renderToStaticMarkup(
      <StaticRouter location="/theme-lab/performance-local/v4/generated-pages/1101">
        <PerformanceLocalV4Renderer
          audit={audit}
          campaignBannerEnabled={campaignBannerEnabled}
          composition={composition}
          page={page}
          previewedAt={previewedAt}
          readiness={readiness}
          reviewMode="truthful"
          v3Configuration={configuration}
        />
      </StaticRouter>,
    );
    assert.match(wrapped, /data-v4-preservation-control="true"/);
    const start = wrapped.indexOf('<div class="performanceLocalSite"');
    assert.ok(start >= 0);
    const delegatedSubtree = wrapped.slice(start, -"</div>".length);
    assert.equal(delegatedSubtree, direct);
  }
});

function renderV4(
  pageType: Exclude<PerformanceLocalV4PageType, "city_service">,
  components: PageComponentInstance[],
  regions: RegionFixture[],
  reviewMode: PerformanceLocalV4ReviewMode,
): string {
  return renderToStaticMarkup(
    <StaticRouter location="/theme-lab/performance-local/v4/generated-pages/1101">
      <PerformanceLocalV4Renderer
        audit={readyAudit(pageType, components, regions)}
        campaignBannerEnabled
        composition={compositionFixture(components, pageType)}
        page={pageFixture(pageType)}
        readiness={readiness}
        reviewMode={reviewMode}
        v3Configuration={conversionConfiguration()}
      />
    </StaticRouter>,
  );
}

type RegionFixture = readonly [PerformanceLocalV4RegionKey, readonly string[]];

function readyAudit(
  pageType: PerformanceLocalV4PageType,
  components: PageComponentInstance[],
  regionFixtures: readonly RegionFixture[],
): PerformanceLocalV4LayoutAudit {
  const manifest = PERFORMANCE_LOCAL_V4_LAYOUT_MANIFESTS[pageType];
  const regionForKey = new Map(
    regionFixtures.flatMap(([regionKey, keys]) => keys.map((key) => [key, regionKey] as const)),
  );
  const consumption = components
    .filter((item) => regionForKey.has(item.instance_key))
    .map((item, sourcePosition) => ({
      instanceKey: item.instance_key,
      componentKey: item.component_key,
      regionKey: regionForKey.get(item.instance_key)!,
      groupKey: null,
      mode: item.component_key === "media_placement"
        ? "attached_media" as const
        : ["primary_navigation", "utility_navigation", "footer_navigation"].includes(item.component_key)
          ? "nested_navigation" as const
          : "direct" as const,
      sourcePosition,
    }));
  return {
    resolutionStatus: "resolved",
    status: "ready",
    layoutReady: true,
    pageType,
    layoutKey: manifest.layoutKey,
    layoutVersion: 1,
    diagnosticIdentity: manifest.diagnosticIdentity,
    compatibilityIdentity: manifest.compatibilityIdentity,
    sourceIdentity: {
      websiteId,
      sitePlanId: 901,
      plannedPageId: 1001,
      generatedPageId,
      compositionId: 801,
      compositionVersion: 8,
      compositionSourceHash: hash,
    },
    manifest,
    regions: regionFixtures.map(([regionKey, sourceInstanceKeys]) => ({
      regionKey,
      requirement: "required",
      presentationVariant: regionKey,
      sourceInstanceKeys,
      presentationGroups: [],
      missing: false,
    })),
    consumption,
    sourceComponentCount: consumption.length,
    consumedComponentCount: consumption.length,
    unconsumedSourceInstanceKeys: [],
    duplicatedSourceInstanceKeys: [],
    missingRequiredRegionKeys: [],
    missingOptionalRegionKeys: [],
    ownershipMismatches: [],
    blockers: [],
    diagnostics: [],
    truthfulRendererResult: "ready",
    structuralDemoRendererResult: "ready",
  };
}

function homeRegions(components: PageComponentInstance[]): RegionFixture[] {
  const existing = new Set(components.map((item) => item.instance_key));
  return [
    ["site_header", ["website_header", "utility_navigation", "primary_navigation"]],
    ["hero", ["hero"]],
    ["trust", ["trust_license"]],
    ["service_discovery", ["content_section:primary_services"]],
    ["company_value", ["content_section:trust", "media_placement:trust"]],
    ["supporting_discovery", ["related_page_links"]],
    ["final_conversion", ["final_cta"]],
    ["site_footer", ["footer_navigation", "website_footer"]],
  ].map(([regionKey, keys]) => [
    regionKey,
    (keys as string[]).filter((key) => existing.has(key)),
  ] as RegionFixture);
}

function homeComponents(): PageComponentInstance[] {
  return [
    component("website_header", "website_header", "header", {
      display_name: "Approved Local Service",
      company_name: "Approved Local Service",
      tagline: "Exact approved tagline",
      identity_assets: {},
    }, { website_id: websiteId }, 0),
    component("utility_navigation", "utility_navigation", "header", {
      label: "Utility navigation",
      items: [navigationItem(2, 1002, 1102, "Approved contact", 0)],
    }, {}, 1),
    component("primary_navigation", "primary_navigation", "header", {
      label: "Primary navigation",
      items: [navigationItem(1, 1001, 1101, "Approved home", 0)],
    }, {}, 2),
    component("hero", "hero", "main", {
      page_type: "home",
      title: "Approved Home heading",
      intro: "Approved source introduction.",
    }, {}, 3),
    component("media_placement:hero", "media_placement", "main", {
      requirement_state: "required",
    }, {
      target_component_instance_key: "hero",
      target_component_key: "hero",
      target_region: "main",
    }, 4),
    component("trust_license", "trust_license", "main", {
      license_number: "LIC-123",
      certified_operator: "Approved operator",
    }, {}, 5),
    component("content_section:primary_services", "content_section", "main", {
      heading: "Approved service discovery",
      body: "- Approved service: Exact source-backed description.",
    }, { section_key: "primary_services" }, 6),
    component("content_section:trust", "content_section", "main", {
      heading: "Approved value heading",
      body: "Approved value copy remains exact.",
    }, { section_key: "trust" }, 7),
    component("media_placement:trust", "media_placement", "main", {
      requirement_state: "required",
    }, {
      target_component_instance_key: "content_section:trust",
      target_component_key: "content_section",
      target_region: "main",
    }, 8),
    component("related_page_links", "related_page_links", "main", {
      links: [{
        label: "Approved related destination",
        purpose: "Approved route purpose.",
        slug: "approved-related",
        target_generated_page_id: 1102,
        target_planned_page_id: 1002,
      }],
    }, {}, 9),
    component("final_cta", "final_cta", "main", {
      heading: "Approved final action",
      body: "Approved final action copy.",
    }, {}, 10),
    component("footer_navigation", "footer_navigation", "footer", {
      label: "Footer navigation",
      items: [navigationItem(3, 1001, 1101, "Approved home", 0)],
    }, {}, 11),
    component("website_footer", "website_footer", "footer", {
      company_name: "Approved Local Service",
      business_type: "Approved local business",
      license_number: "LIC-123",
      identity_assets: {},
    }, { website_id: websiteId }, 12),
  ];
}

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
  targetGeneratedPageId: number,
  label: string,
  position: number,
  parentNavigationItemId: number | null = null,
) {
  return {
    navigation_item_id: id,
    target_planned_page_id: plannedPageId,
    target_generated_page_id: targetGeneratedPageId,
    parent_navigation_item_id: parentNavigationItemId,
    position,
    status: "active",
    label,
    slug: label.toLowerCase().replace(/\s+/g, "-"),
  };
}

function compositionFixture(
  components: PageComponentInstance[],
  pageType: PerformanceLocalV4PageType,
): PageComposition {
  return {
    id: 801,
    website_id: websiteId,
    site_plan_id: 901,
    planned_page_id: 1001,
    generated_page_id: generatedPageId,
    composition_version: 8,
    generated_components: [],
    operator_decisions: [],
    effective_components: components,
    source_snapshot: { page_type: pageType },
    source_hash: hash,
    resolved_theme: selectedTheme(),
    status: "current",
    validation_errors: [],
    generated_at: "2026-08-17T12:00:00Z",
  };
}

function auditedFaqFixture(): {
  page: GeneratedPage;
  plannedPage: PlannedPage;
  composition: PageComposition;
} {
  const navigationTarget = {
    planned_page_id: 1003,
    website_id: websiteId,
    site_plan_id: 901,
    generated_page_id: 1103,
    intended_slug: "approved-contact",
  };
  const childNavigationTarget = {
    planned_page_id: 1005,
    website_id: websiteId,
    site_plan_id: 901,
    generated_page_id: 1105,
    intended_slug: "approved-county",
  };
  const footerTarget = {
    planned_page_id: 1004,
    website_id: websiteId,
    site_plan_id: 901,
    generated_page_id: 1104,
    intended_slug: "approved-home",
  };
  const relatedTarget = {
    planned_page_id: 1002,
    website_id: websiteId,
    site_plan_id: 901,
    generated_page_id: 1102,
    intended_slug: "approved-related",
  };
  const components: PageComponentInstance[] = [
    component("website_header", "website_header", "header", {
      display_name: "Audited Local Service",
      company_name: "Audited Local Service",
      tagline: "Audited exact tagline",
      identity_assets: {},
    }, { website_id: websiteId }, 0),
    component("utility_navigation", "utility_navigation", "header", {
      label: "Utility navigation",
      items: [{
        ...navigationItem(27, 1003, 1103, "Duplicate utility FAQ", 0),
        slug: "approved-contact",
      }],
    }, { navigation_set_id: 2 }, 1),
    component("primary_navigation", "primary_navigation", "header", {
      label: "Primary navigation",
      items: [
        {
          ...navigationItem(11, 1003, 1103, "Audited parent service", 0),
          slug: "approved-contact",
        },
        {
          ...navigationItem(12, 1005, 1105, "Audited county", 1, 11),
          slug: "approved-county",
        },
      ],
    }, { navigation_set_id: 1 }, 2),
    component("hero", "hero", "main", {
      page_type: "faq",
      title: "Audited FAQ heading",
      intro: "Audited FAQ introduction.",
    }, { generated_page_id: generatedPageId }, 3),
    component("media_placement:hero", "media_placement", "main", {
      requirement_state: "required",
    }, mediaBindings(1, "hero", "hero"), 4),
    component("trust_license", "trust_license", "main", {
      license_number: "AUDIT-123",
      certified_operator: "Audited operator",
    }, { website_id: websiteId }, 5),
    component("content_section:contact", "content_section", "main", {
      heading: "Audited contact support",
      body: "Audited contact support copy.",
    }, { generated_page_id: generatedPageId, section_key: "contact" }, 6),
    component("media_placement:contact", "media_placement", "main", {
      requirement_state: "required",
    }, mediaBindings(2, "content_section:contact", "content_section"), 7),
    component("related_page_links", "related_page_links", "main", {
      links: [{
        label: "Audited related destination",
        purpose: "Audited exact purpose.",
        slug: "approved-related",
        target_generated_page_id: 1102,
        target_planned_page_id: 1002,
      }],
    }, { internal_link_intent_ids: [], draft_related_page_ids: [] }, 8),
    component("faq", "faq", "main", {
      items: [{ question: "Audited exact question?", answer: "Audited exact answer." }],
    }, { generated_page_id: generatedPageId }, 9),
    component("media_placement:faq", "media_placement", "main", {
      requirement_state: "required",
    }, mediaBindings(3, "faq", "faq"), 10),
    component("final_cta", "final_cta", "main", {
      heading: "Audited final action",
      body: "Audited final action copy.",
    }, { generated_page_id: generatedPageId, website_id: websiteId }, 11),
    component("footer_navigation", "footer_navigation", "footer", {
      label: "Footer navigation",
      items: [{
        ...navigationItem(31, 1004, 1104, "Audited home", 0),
        slug: "approved-home",
      }],
    }, { navigation_set_id: 3 }, 12),
    component("website_footer", "website_footer", "footer", {
      company_name: "Audited Local Service",
      business_type: "Audited local business",
      license_number: "AUDIT-123",
      identity_assets: {},
    }, { website_id: websiteId }, 13),
  ];
  const mediaRequirements = [
    mediaRequirement(1, "hero", "hero"),
    mediaRequirement(2, "content_section:contact", "content_section"),
    mediaRequirement(3, "faq", "faq"),
  ];
  const page = pageFixture("faq");
  const plannedPage: PlannedPage = {
    id: 1001,
    website_id: websiteId,
    site_plan_id: 901,
    page_type: "faq",
    working_name: "Audited FAQ",
    intended_slug: "approved-page",
    planning_status: "planned",
    generated_page_id: generatedPageId,
    draft_readiness: {
      status: "ready",
      page_type_supported: true,
      required_information: [],
      blocking_reasons: [],
      recommendations: [],
    },
    planning_record: {
      id: 3001,
      planned_page_id: 1001,
      generated_answers: {},
      operator_overrides: {},
      effective_answers: {},
      source_snapshot: {},
      confidence_score: 1,
      confidence_level: "high",
      missing_information: [],
      improvement_recommendations: [],
      generated_at: "2026-08-17T12:00:00Z",
      updated_at: "2026-08-17T12:00:00Z",
    },
    created_at: "2026-08-17T12:00:00Z",
    updated_at: "2026-08-17T12:00:00Z",
  };
  const composition: PageComposition = {
    ...compositionFixture(components, "faq"),
    source_snapshot: {
      website_id: websiteId,
      site_plan_id: 901,
      site_plan_version: 1,
      planned_page_id: 1001,
      generated_page_id: generatedPageId,
      navigation_sets: [{ id: 1 }, { id: 2 }, { id: 3 }],
      navigation_items: [
        { id: 11, navigation_set_id: 1, target: navigationTarget },
        { id: 12, navigation_set_id: 1, target: childNavigationTarget },
        { id: 27, navigation_set_id: 2, target: navigationTarget },
        { id: 31, navigation_set_id: 3, target: footerTarget },
      ],
      internal_links: [],
      draft_related_targets: [relatedTarget],
      page_media: { requirements: mediaRequirements },
    },
  };
  return { page, plannedPage, composition };
}

function auditedCountyFixture(): {
  page: GeneratedPage;
  plannedPage: PlannedPage;
  composition: PageComposition;
} {
  const cityLabels = [
    "Drywood Termite Tenting in Audited City One, FL",
    "Drywood Termite Tenting in Audited City Two, FL",
  ];
  const destinationLabels = [
    ...cityLabels,
    "Governed service destination",
    "Governed contact destination",
  ];
  const targets = destinationLabels.map((_, index) => ({
    planned_page_id: 1201 + index,
    website_id: websiteId,
    site_plan_id: 901,
    generated_page_id: 1301 + index,
    intended_slug: `audited-county-destination-${index + 1}`,
  }));
  const components: PageComponentInstance[] = [
    component("website_header", "website_header", "header", {
      display_name: "Audited County Service",
      company_name: "Audited County Service",
      tagline: "Audited County tagline",
      identity_assets: {},
    }, { website_id: websiteId }, 0),
    component("utility_navigation", "utility_navigation", "header", {
      label: "Utility navigation",
      items: [],
    }, { navigation_set_id: 2 }, 1),
    component("primary_navigation", "primary_navigation", "header", {
      label: "Primary navigation",
      items: [],
    }, { navigation_set_id: 1 }, 2),
    component("hero", "hero", "main", {
      page_type: "county",
      title: "Audited County heading",
      intro: "Audited County introduction.",
    }, { generated_page_id: generatedPageId }, 3),
    component("media_placement:hero", "media_placement", "main", {
      requirement_state: "required",
    }, mediaBindings(1, "hero", "hero"), 4),
    component("trust_license", "trust_license", "main", {
      license_number: "COUNTY-123",
      certified_operator: "Audited County operator",
    }, { website_id: websiteId }, 5),
    component("service_summary:service_county_intro", "service_summary", "main", {
      heading: "Audited County overview",
      body: "Audited County overview copy.",
    }, { generated_page_id: generatedPageId, section_key: "service_county_intro" }, 6),
    component("media_placement:service_county_intro", "media_placement", "main", {
      requirement_state: "required",
    }, mediaBindings(2, "service_summary:service_county_intro", "service_summary"), 7),
    component("content_section:cities_served", "content_section", "main", {
      heading: "Audited coverage",
      body: "- Separate coverage-only city",
    }, { generated_page_id: generatedPageId, section_key: "cities_served" }, 8),
    component("media_placement:cities_served", "media_placement", "main", {
      requirement_state: "required",
    }, mediaBindings(3, "content_section:cities_served", "content_section"), 9),
    component("content_section:how_service_works", "content_section", "main", {
      heading: "Audited service process",
      body: "Audited service process copy.",
    }, { generated_page_id: generatedPageId, section_key: "how_service_works" }, 10),
    component("content_section:customer_expectations", "content_section", "main", {
      heading: "Audited customer expectations",
      body: "Audited customer expectations copy.",
    }, { generated_page_id: generatedPageId, section_key: "customer_expectations" }, 11),
    component("content_section:preparation_guidance", "content_section", "main", {
      heading: "Audited preparation guidance",
      body: "Audited preparation guidance copy.",
    }, { generated_page_id: generatedPageId, section_key: "preparation_guidance" }, 12),
    component("content_section:trust_and_license", "content_section", "main", {
      heading: "Audited County credentials",
      body: "Audited County credentials copy.",
    }, { generated_page_id: generatedPageId, section_key: "trust_and_license" }, 13),
    component("content_section:related_city_services", "content_section", "main", {
      heading: "Audited related city routes",
      body: cityLabels.join(", "),
    }, { generated_page_id: generatedPageId, section_key: "related_city_services" }, 14),
    component("destination_cards", "destination_cards", "main", {
      links: destinationLabels.map((label, index) => ({
        label,
        purpose: `Audited governed purpose ${index + 1}.`,
        slug: targets[index].intended_slug,
        target_generated_page_id: targets[index].generated_page_id,
        target_planned_page_id: targets[index].planned_page_id,
      })),
    }, {
      internal_link_intent_ids: [],
      draft_related_page_ids: targets.map((target) => target.planned_page_id),
    }, 15),
    component("faq", "faq", "main", {
      items: [{ question: "Audited County question?", answer: "Audited County answer." }],
    }, { generated_page_id: generatedPageId }, 16),
    component("final_cta", "final_cta", "main", {
      heading: "Audited County final action",
      body: "Audited County final copy.",
    }, { generated_page_id: generatedPageId, website_id: websiteId }, 17),
    component("footer_navigation", "footer_navigation", "footer", {
      label: "Footer navigation",
      items: [],
    }, { navigation_set_id: 3 }, 18),
    component("website_footer", "website_footer", "footer", {
      company_name: "Audited County Service",
      business_type: "Audited local business",
      license_number: "COUNTY-123",
      identity_assets: {},
    }, { website_id: websiteId }, 19),
  ];
  const page = pageFixture("county");
  const plannedPage: PlannedPage = {
    id: 1001,
    website_id: websiteId,
    site_plan_id: 901,
    page_type: "county",
    working_name: "Audited County",
    intended_slug: "approved-page",
    planning_status: "planned",
    generated_page_id: generatedPageId,
    draft_readiness: {
      status: "ready",
      page_type_supported: true,
      required_information: [],
      blocking_reasons: [],
      recommendations: [],
    },
    planning_record: {
      id: 3002,
      planned_page_id: 1001,
      generated_answers: {},
      operator_overrides: {},
      effective_answers: {},
      source_snapshot: {},
      confidence_score: 1,
      confidence_level: "high",
      missing_information: [],
      improvement_recommendations: [],
      generated_at: "2026-08-17T12:00:00Z",
      updated_at: "2026-08-17T12:00:00Z",
    },
    created_at: "2026-08-17T12:00:00Z",
    updated_at: "2026-08-17T12:00:00Z",
  };
  const mediaRequirements = [
    mediaRequirement(1, "hero", "hero"),
    mediaRequirement(2, "service_summary:service_county_intro", "service_summary"),
    mediaRequirement(3, "content_section:cities_served", "content_section"),
  ];
  const composition: PageComposition = {
    ...compositionFixture(components, "county"),
    composition_version: 8,
    source_snapshot: {
      website_id: websiteId,
      site_plan_id: 901,
      site_plan_version: 1,
      planned_page_id: 1001,
      generated_page_id: generatedPageId,
      navigation_sets: [{ id: 1 }, { id: 2 }, { id: 3 }],
      navigation_items: [],
      internal_links: [],
      draft_related_targets: targets,
      page_media: { requirements: mediaRequirements },
    },
  };
  return { page, plannedPage, composition };
}

function mediaBindings(id: number, targetInstanceKey: string, targetComponentKey: string) {
  return {
    media_requirement_id: id,
    target_component_instance_key: targetInstanceKey,
    target_component_key: targetComponentKey,
    target_region: "main",
    placement_contract_version: 2,
  };
}

function mediaRequirement(id: number, targetInstanceKey: string, targetComponentKey: string) {
  return {
    id,
    target_component_instance_key: targetInstanceKey,
    component_or_section: targetComponentKey,
    contract_version: 2,
    lifecycle_status: "active",
  };
}

function pageFixture(pageType: PerformanceLocalV4PageType): GeneratedPage {
  return {
    id: generatedPageId,
    business_id: 21,
    website_id: websiteId,
    service_id: pageType === "home" || pageType === "about" || pageType === "contact" || pageType === "faq" ? null : 5,
    page_type: pageType,
    page_title: "Approved page title",
    page_slug: "approved-page",
    generation_status: "generated",
    qa_status: "ready",
    status: "draft",
    created_at: "2026-08-17T12:00:00Z",
    updated_at: "2026-08-17T12:00:00Z",
  };
}

function conversionConfiguration(): PerformanceLocalDeliveryConfiguration {
  const fields = estimateFields();
  const blockedReadiness = {
    status: "blocked",
    can_submit: false,
    component_configuration_id: formConfigurationId,
    blockers: [],
  } as unknown as PerformanceLocalFormReadinessRead;
  return {
    campaign: {
      approvalIdentity: "approved-campaign",
      campaignLabel: "Request an Estimate",
      ctaDestination: `#${performanceLocalFormDomId(formConfigurationId)}`,
      ctaLabel: "Request Estimate",
      destinationComponentConfigurationId: formConfigurationId,
      enabled: true,
      intent: "evergreen_conversion",
      websiteId,
      optional: true,
      scope: "website_with_optional_page_override",
      pageOverrideId: null,
      themeCompatibility: "performance-local@2",
      placement: "before_header",
      variant: "single_action_safe_strip",
      responsiveVisibility: { desktop: true, tablet: true, mobile: true },
      contentSource: "approved_runtime_configuration",
      accessibilityLabel: "Request an Estimate",
    },
    estimateForm: {
      componentConfigurationId: formConfigurationId,
      componentInstanceKey: "performance-local:compact-estimate-form-v3",
      ctaLabel: "Request Estimate",
      fields,
      previewNotice: "Preview only. Information entered here is not submitted or saved.",
      providerState: {
        canSubmit: false,
        collectsData: false,
        destination: null,
        providerKey: null,
        submissionState: "disabled_pending_provider_configuration",
      },
      submitLabel: "Request Estimate",
      visualState: "idle",
    },
    formSubmission: {
      endpoint: null,
      readiness: blockedReadiness,
    },
    governedContact: {
      callDestination: "tel:+15550100200",
      phoneDisplay: "(555) 010-0200",
      websiteId,
    },
    rendererIdentity: {
      componentVersion: "3",
      deliveryMode: "inactive_draft_preview",
      exposeDiagnostics: false,
      themeCompatibility: "performance-local@3",
      themeVersion: 3,
      destinationForGeneratedPageId: (id) => `/delivery/local-preview/configurations/91/generated-pages/${id}`,
    },
    stickyActions: {
      callLabel: "Call",
      componentConfigurationId: 45,
      desktopHeaderActionsEnabled: true,
      destinationComponentConfigurationId: formConfigurationId,
      enabled: true,
      estimateLabel: "Request Estimate",
      mobileStickyActionsEnabled: true,
    },
    toggles: {
      campaignBanner: true,
      compactEstimateForm: true,
      estimateAction: true,
      finalCta: true,
      headerEstimateCta: true,
      phoneAction: true,
      stickyActionBar: true,
      trustStrip: true,
    },
  } as PerformanceLocalDeliveryConfiguration;
}

function estimateFields(): PerformanceLocalEstimateField[] {
  const specs = [
    ["name", "Name", "input", "text", "nonempty_text", true, "half", "contact_name"],
    ["phone", "Phone", "input", "tel", "phone", true, "half", "phone"],
    ["postal-code", "ZIP code", "input", "text", "postal_code", true, "half", "postal_code"],
    ["requested-service", "Requested service", "input", "text", "nonempty_text", true, "half", "requested_service"],
    ["message", "Optional message", "textarea", undefined, "free_text", false, "full", "message"],
  ] as const;
  return specs.map(([key, label, control, type, rule, required, responsive, mapping], index) => ({
    accessibilityLabel: label,
    autoComplete: "off",
    control,
    inputMode: key === "phone" ? "tel" : key === "postal-code" ? "numeric" : "text",
    key,
    label,
    maxLength: 500,
    order: index + 1,
    providerMapping: mapping,
    required,
    responsive: { desktop: responsive, tablet: responsive, mobile: "full" },
    rows: control === "textarea" ? 3 : undefined,
    type,
    validation: { maximumLength: 500, minimumLength: required ? 1 : 0, rule },
  }));
}

function count(value: string, needle: string): number {
  return value.split(needle).length - 1;
}
