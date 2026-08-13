import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";

import PerformanceLocalComponentGallery from "../src/components/PerformanceLocalComponentGallery";
import PerformanceLocalComponentGalleryPage from "../src/pages/PerformanceLocalComponentGalleryPage";
import {
  PERFORMANCE_LOCAL_ACTIVATION_INPUTS,
  performanceLocalActivationReadiness,
} from "../src/components/performanceLocalReadiness";
import {
  ATLAS_DIAGNOSTIC_THEME,
  PERFORMANCE_LOCAL_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_THEME,
  PERFORMANCE_LOCAL_THEME_COMPATIBILITY,
  PERFORMANCE_LOCAL_THEME_VERSION,
  performanceLocalComponentContract,
  performanceLocalOptionalConfiguration,
  resolveOptionalComponent,
  resolvePerformanceLocalBrandAccent,
} from "../src/components/performanceLocalTheme";

const websiteId = 7_001;
const evaluatedAt = new Date("2026-08-13T12:00:00Z");

test("canonical Performance Local source identity advances to v2 without activation", () => {
  assert.equal(PERFORMANCE_LOCAL_THEME.key, "performance-local");
  assert.equal(PERFORMANCE_LOCAL_THEME_VERSION, 2);
  assert.equal(PERFORMANCE_LOCAL_THEME.version, 2);
  assert.equal(PERFORMANCE_LOCAL_THEME.status, "preview_candidate");
  assert.equal(PERFORMANCE_LOCAL_THEME.productionReady, false);
  assert.equal(PERFORMANCE_LOCAL_THEME.websiteIndependent, true);
  assert.equal(PERFORMANCE_LOCAL_THEME_COMPATIBILITY, "performance-local@2");
  assert.equal(
    PERFORMANCE_LOCAL_THEME.compatibilityIdentity,
    "atlas-semantic-composition@1|performance-local@2",
  );
  assert.equal(ATLAS_DIAGNOSTIC_THEME.version, 1);
  assert.equal(ATLAS_DIAGNOSTIC_THEME.status, "internal_diagnostic");
});

test("every reusable component contract is versioned, Website-scoped, and discoverable", () => {
  assert.equal(PERFORMANCE_LOCAL_COMPONENT_CONTRACTS.length, 23);
  for (const contract of PERFORMANCE_LOCAL_COMPONENT_CONTRACTS) {
    assert.equal(contract.version, 2);
    assert.equal(contract.scope, "website_with_optional_page_override");
    assert.deepEqual(contract.themeCompatibility, ["performance-local@2"]);
    assert.equal(performanceLocalComponentContract(contract.key), contract);
  }
  assert.equal(performanceLocalComponentContract("unknown_component"), undefined);
});

test("runtime brand accent injection accepts safe opaque hex and otherwise uses governed primary", () => {
  assert.equal(resolvePerformanceLocalBrandAccent("#12aBcF", "#123456"), "#12aBcF");
  assert.equal(resolvePerformanceLocalBrandAccent("transparent", "#123456"), "#123456");
  assert.equal(resolvePerformanceLocalBrandAccent("#1234", "#123456"), "#123456");
  assert.throws(() => resolvePerformanceLocalBrandAccent(null, "green"), /governed primary color/);
});

test("provider, local-area, community, language, and production-form capabilities fail closed", () => {
  const keys = [
    "review_badge_group",
    "statistics_counter_band",
    "video_embed_section",
    "map_or_service_area_section",
    "community_program_section",
    "language_selector",
  ] as const;
  for (const key of keys) {
    const result = resolveOptionalComponent(
      key,
      performanceLocalOptionalConfiguration(key, websiteId, `${key} preview`),
      websiteId,
      "desktop",
      evaluatedAt,
    );
    assert.equal(result.visible, false);
    assert.ok(result.errors.length > 0);
  }

  const form = resolveOptionalComponent(
    "compact_estimate_form",
    performanceLocalOptionalConfiguration(
      "compact_estimate_form",
      websiteId,
      "Estimate form preview",
      { previewOnly: false, productionMode: true },
    ),
    websiteId,
    "desktop",
    evaluatedAt,
  );
  assert.equal(form.visible, false);
  assert.ok(form.errors.some((error) => error.includes("requiredConsent")));
  assert.ok(form.errors.some((error) => error.includes("submissionProvider")));
});

test("review evidence requires an exact approval identity before it can render", () => {
  const review = performanceLocalOptionalConfiguration(
    "review_badge_group",
    websiteId,
    "Approved review evidence",
    {
      provider: "Approved provider",
      rating: 4.8,
      reviewCount: 24,
      ratingApprovalStatus: "approved",
      reviewCountApprovalStatus: "approved",
      verificationDate: "2026-08-12",
      destination: "/approved-review-evidence",
      trademarkUseAuthorization: "approved",
      approvalIdentity: "APPROVAL-IDENTITY",
    },
  );
  assert.equal(
    resolveOptionalComponent("review_badge_group", review, websiteId, "desktop", evaluatedAt).visible,
    true,
  );
  const missingApproval = resolveOptionalComponent(
    "review_badge_group",
    { ...review, approvalIdentity: "" },
    websiteId,
    "desktop",
    evaluatedAt,
  );
  assert.equal(missingApproval.visible, false);
  assert.ok(missingApproval.errors.some((error) => error.includes("approvalIdentity")));
  const invalidClock = resolveOptionalComponent(
    "review_badge_group",
    review,
    websiteId,
    "desktop",
    new Date(Number.NaN),
  );
  assert.equal(invalidClock.visible, false);
  assert.ok(invalidClock.errors.some((error) => error.includes("evaluation time")));
});

test("community and language contracts require exact dates, local routes, and routing approval", () => {
  const community = performanceLocalOptionalConfiguration(
    "community_program_section",
    websiteId,
    "Demo program",
    {
      approvedProgramIdentity: "DEMO-PROGRAM",
      approvedCopy: "Illustrative copy only",
      destination: "/demo-program",
      effectiveStartDate: "2026-01-01",
      effectiveEndDate: "2026-12-31",
      approvalIdentity: "DEMO-APPROVAL",
    },
  );
  assert.equal(
    resolveOptionalComponent(
      "community_program_section",
      community,
      websiteId,
      "desktop",
      evaluatedAt,
    ).visible,
    true,
  );
  assert.equal(
    resolveOptionalComponent(
      "community_program_section",
      community,
      websiteId,
      "desktop",
      new Date(Number.NaN),
    ).visible,
    false,
  );

  const statistic = performanceLocalOptionalConfiguration(
    "statistics_counter_band",
    websiteId,
    "Approved statistic",
    {
      metricLabel: "Approved metric",
      value: 1,
      source: "APPROVED-SOURCE",
      effectiveDate: "2026-08-12",
      approvalIdentity: "DEMO-APPROVAL",
    },
  );
  assert.equal(
    resolveOptionalComponent(
      "statistics_counter_band",
      statistic,
      websiteId,
      "desktop",
      new Date(Number.NaN),
    ).visible,
    false,
  );

  const language = performanceLocalOptionalConfiguration(
    "language_selector",
    websiteId,
    "Translated content selector",
    {
      actualTranslatedContent: true,
      translatedRoutes: [{ language: "es", destination: "/es/demo" }],
      canonicalHreflangConfiguration: "approved",
      languageLabels: { es: "Español" },
      routingBehavior: "approved_local_routes",
      approvalIdentity: "DEMO-APPROVAL",
    },
  );
  assert.equal(
    resolveOptionalComponent(
      "language_selector",
      language,
      websiteId,
      "desktop",
      evaluatedAt,
    ).visible,
    true,
  );
  assert.equal(
    resolveOptionalComponent(
      "language_selector",
      { ...language, translatedRoutes: [{ language: "es", destination: "https://example.invalid" }] },
      websiteId,
      "desktop",
      evaluatedAt,
    ).visible,
    false,
  );
});

const GALLERY_DUAL_STATE_COMPONENTS = [
  "review_badge_group",
  "statistics_counter_band",
  "video_embed_section",
  "map_or_service_area_section",
  "community_program_section",
  "language_selector",
] as const;

test("component gallery renders every optional capability as an enabled synthetic demo and a separate fail-closed state", () => {
  const markup = renderToStaticMarkup(
    <PerformanceLocalComponentGallery evaluatedAt={evaluatedAt} viewport="desktop" />,
  );
  assert.match(markup, /DEMO COMPONENT — NOT SITE CONTENT/);
  assert.match(markup, /data-demo-only="true"/);
  assert.match(markup, /data-external-requests="0"/);
  assert.match(markup, /data-component-key="campaign_banner"/);
  assert.match(markup, /data-resolution="demo_enabled"/);
  for (const key of GALLERY_DUAL_STATE_COMPONENTS) {
    assert.match(markup, new RegExp(`data-enabled-demo-component="${key}"`));
    assert.match(markup, new RegExp(`data-fail-closed-component="${key}"`));
  }
  assert.ok((markup.match(/DEMO COMPONENT — NOT SITE CONTENT/g) ?? []).length >= 7);
  assert.ok((markup.match(/data-component-resolution="visible"/g) ?? []).length >= 7);
  assert.ok((markup.match(/data-demo-state="fail-closed"/g) ?? []).length === 6);
  assert.match(markup, /Required scope: exact current Website identity/);
  assert.match(markup, /Missing required configuration: provider\./);
  assert.match(markup, /Missing required configuration: source\./);
  assert.match(markup, /Missing required configuration: approvedProvider\./);
  assert.match(markup, /Missing required configuration: approvedLocationOrServiceArea\./);
  assert.match(markup, /Missing required configuration: approvedProgramIdentity\./);
  assert.match(markup, /Missing required configuration: actualTranslatedContent\./);
});

test("enabled gallery demonstrations are production-styled placeholders with inert controls and no factual or provider payload", () => {
  const markup = renderToStaticMarkup(
    <PerformanceLocalComponentGallery evaluatedAt={evaluatedAt} viewport="desktop" />,
  );
  assert.match(markup, /DEMO REVIEW PROVIDER/);
  assert.match(markup, /DEMO RATING/);
  assert.match(markup, /DEMO REVIEW COUNT/);
  assert.match(markup, /DEMO METRIC A/);
  assert.match(markup, /DEMO METRIC B/);
  assert.match(markup, /DEMO METRIC C/);
  assert.ok((markup.match(/DEMO VALUE/g) ?? []).length >= 3);
  assert.match(markup, /DEMO VIDEO — NO MEDIA LOADED/);
  assert.match(markup, /DEMO ACCESSIBILITY TEXT/);
  assert.match(markup, /PROVIDER-FREE \/ REQUEST-FREE/);
  assert.match(markup, /DEMO SERVICE AREA — NO ADDRESS OR MAP PROVIDER/);
  assert.match(markup, /NO PROVIDER LOADED \/ NO REQUEST/);
  assert.match(markup, /DEMO COMMUNITY PROGRAM/);
  assert.match(markup, /DEMO DESCRIPTION/);
  assert.match(markup, /DEMO EFFECTIVE STATUS/);
  assert.match(markup, /LANGUAGE A/);
  assert.match(markup, /LANGUAGE B/);
  assert.match(markup, /disabled=""/);
  assert.doesNotMatch(markup, /https?:\/\//i);
  assert.doesNotMatch(markup, /\$\d|\b\d+(?:\.\d+)?\s*(?:stars?|reviews?|customers?|services?)\b/i);
  assert.doesNotMatch(markup, /Page 41|Flo-Zone|All American|Google|BBB|guarantee|street address|years? in business/i);
  assert.doesNotMatch(markup, /<(?:iframe|video|form|img|a)\b/i);
  assert.doesNotMatch(markup, /\bhref=/i);
  assert.doesNotMatch(
    markup,
    /\b(?:latitude|longitude)\s*[:=]\s*-?\d|-?\d{1,3}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}|maps\.google|mapbox|<map\b/i,
  );
});

test("gallery source stays lazy, local, non-persistent, and isolated from public rendering and export", () => {
  const sourceRoot = resolve(process.cwd(), "src");
  const gallerySource = readFileSync(
    resolve(sourceRoot, "components", "PerformanceLocalComponentGallery.tsx"),
    "utf8",
  );
  const appSource = readFileSync(resolve(sourceRoot, "App.tsx"), "utf8");
  const rendererSource = readFileSync(
    resolve(sourceRoot, "components", "PerformanceLocalRenderer.tsx"),
    "utf8",
  );
  const exportSource = readFileSync(resolve(sourceRoot, "pages", "ExportPackagePage.tsx"), "utf8");
  const stylesSource = readFileSync(resolve(sourceRoot, "styles.css"), "utf8");

  assert.match(
    appSource,
    /const PerformanceLocalComponentGalleryPage = lazy\([\s\S]*import\("\.\/pages\/PerformanceLocalComponentGalleryPage"\)/,
  );
  assert.doesNotMatch(rendererSource, /PerformanceLocalComponentGallery|data-enabled-demo-component/);
  assert.doesNotMatch(exportSource, /PerformanceLocalComponentGallery|data-enabled-demo-component/);
  assert.doesNotMatch(appSource, /demo-language-(?:a|b)/);
  assert.doesNotMatch(rendererSource, /demo-language-(?:a|b)/);
  assert.doesNotMatch(exportSource, /demo-language-(?:a|b)/);
  assert.doesNotMatch(
    gallerySource,
    /\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource|localStorage|sessionStorage|indexedDB|apiRequest|useEffect|useState/i,
  );
  assert.doesNotMatch(gallerySource, /https?:\/\//i);
  assert.doesNotMatch(gallerySource, /Page 41|Flo-Zone|All American|drywoodtenting\.com/i);
  assert.doesNotMatch(gallerySource, /<(?:iframe|video|form|img)\b/i);
  assert.match(
    stylesSource,
    /\.performanceLocalGalleryStatisticsDemo\s*\{[\s\S]*?grid-template-columns: repeat\(3, minmax\(0, 1fr\)\)/,
  );
  assert.match(
    stylesSource,
    /@media \(max-width: 760px\)[\s\S]*?\.performanceLocalGalleryStatisticsDemo,[\s\S]*?grid-template-columns: 1fr/,
  );
  assert.match(
    stylesSource,
    /@media \(min-width: 761px\) and \(max-width: 980px\)[\s\S]*?\.performanceLocalGalleryGrid\s*\{\s*grid-template-columns: 1fr/,
  );
});

test("activation readiness is pure, visibly incomplete, and cannot activate or publish", () => {
  const result = performanceLocalActivationReadiness({
    previewImplementationPresent: true,
    observedThemeFamilyVersion: 2,
  });
  assert.equal(result.status, "blocked");
  assert.equal(result.canActivate, false);
  assert.equal(result.canPublish, false);
  assert.equal(result.canDeploy, false);
  assert.equal(result.mutatesAtlas, false);
  assert.equal(result.productionReady, false);
  assert.equal(result.incompleteCount, PERFORMANCE_LOCAL_ACTIVATION_INPUTS.length);
  assert.equal(result.items.length, 17);
  assert.ok(result.items.every((item) => item.status === "incomplete"));
  assert.ok(result.items.some((item) => item.key === "publication_authorization"));
  assert.ok(result.items.some((item) => item.key === "production_renderer_integration"));

  const markup = renderToStaticMarkup(
    <StaticRouter location="/theme-lab/performance-local/components">
      <PerformanceLocalComponentGalleryPage />
    </StaticRouter>,
  );
  assert.match(markup, /Blocked — Performance Local is not activated and is not production-ready/);
  assert.match(markup, /href="\/generated-pages"/);
  assert.doesNotMatch(markup, /theme-lab\/generated-pages\/[0-9]+/);
});
