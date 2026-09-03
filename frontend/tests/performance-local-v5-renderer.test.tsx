import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";

import {
  PerformanceLocalV5LayoutBody,
  PerformanceLocalV5TopConversionStack,
  type PerformanceLocalV5LayoutBodyProps,
  type PerformanceLocalV5RegionPlan,
  type PerformanceLocalV5TopAction,
} from "../src/components/PerformanceLocalV5Layouts";
import PerformanceLocalV5Renderer, {
  performanceLocalV5FooterBoundaryReached,
  type PerformanceLocalV5PreviewSurface,
  type PerformanceLocalV5ReadinessProjection,
} from "../src/components/PerformanceLocalV5Renderer";
import PerformanceLocalRenderer, {
  performanceLocalFormDomId,
  type PerformanceLocalEstimateField,
  PerformanceLocalEstimateFormConfiguration,
  PerformanceLocalGovernedContact,
} from "../src/components/PerformanceLocalRenderer";
import type { PerformanceLocalDeliveryConfiguration } from "../src/components/performanceLocalDelivery";
import {
  resolvePerformanceLocalV5TopAction,
  type PerformanceLocalV5ActionConfiguration,
  type PerformanceLocalV5FormIdentity,
} from "../src/components/performanceLocalV5Actions";
import type {
  PerformanceLocalV5CountyCityPresentation,
  PerformanceLocalV5DestinationConsumptionRecord,
  PerformanceLocalV5HomeServicePresentation,
  PerformanceLocalV5LayoutAudit,
} from "../src/components/performanceLocalV5LayoutContract";
import {
  isPerformanceLocalV5SafeGoogleMapsEmbedUrl,
  isPerformanceLocalV5SafeHttpsDestination,
  isPerformanceLocalV5SafeLocalImageUrl,
  resolvePerformanceLocalV5GoogleMapsEmbedInput,
  resolvePerformanceLocalV5OptionalModules,
  type PerformanceLocalV5OptionalModulePageConfiguration,
  type PerformanceLocalV5OptionalModulePresentation,
} from "../src/components/performanceLocalV5OptionalModules";
import type { GeneratedPage, PageComponentInstance, PageComposition } from "../src/types";
import { selectedTheme } from "./theme-fixtures";

const root = process.cwd();

test("all six non-city layouts use one contained inert five-field final conversion", () => {
  for (const pageType of ["home", "service", "county", "about", "contact", "faq"] as const) {
    const markup = renderLayout(pageType, "truthful");
    assert.equal(count(markup, 'data-v5-shared-final-conversion="true"'), 1, pageType);
    assert.equal(count(markup, 'data-field-key="'), 5, pageType);
    assert.equal(count(markup, "readonly=\"\""), 5, pageType);
    assert.match(markup, /<button type="submit" disabled="">Request Estimate<\/button>/, pageType);
    assert.match(markup, /href="tel:5550100200"/, pageType);
    assert.match(markup, /href="#performance-local-estimate-form-91"/, pageType);
    const finalIndex = markup.indexOf('data-v5-shared-final-conversion="true"');
    assert.ok(markup.indexOf("<form", finalIndex) > finalIndex, pageType);
    assert.equal(markup.slice(0, finalIndex).includes("<form"), false, pageType);
  }
});

test("Home uses the audited featured-service projection and preserves the related remainder", () => {
  const featured = renderLayout("home", "truthful");
  assert.match(featured, /data-v5-service-presentation="featured"/);
  assert.match(featured, /Exact featured service/);
  assert.match(featured, /Exact featured description\./);
  assert.match(featured, /Exact source purpose\./);
  assert.match(featured, /href="\/theme-lab\/performance-local\/v5\/generated-pages\/1201"/);
  assert.equal(count(featured, "Exact featured service"), 1);
  assert.equal(count(featured, "Exact remaining destination"), 1);

  const props = layoutProps("home", "truthful");
  const first = props.homeServicePresentation.services[0];
  const secondDestination = destination(1, "service_grid", "Second exact service", 1203);
  const gridPresentation: PerformanceLocalV5HomeServicePresentation = {
    ...props.homeServicePresentation,
    mode: "grid",
    services: [
      first,
      {
        sourceItemIndex: 1,
        exactSourceItem: "Second exact service: Second exact description.",
        title: "Second exact service",
        description: "Second exact description.",
        matchedLinkIndex: 1,
        destination: secondDestination,
      },
    ],
  };
  const grid = staticMarkup({ ...props, homeServicePresentation: gridPresentation });
  assert.match(grid, /data-v5-service-presentation="grid"/);
  assert.equal(count(grid, "performanceLocalV5ServiceEntry"), 2);
});

test("Service guidance uses closed native disclosures with exact complete answers", () => {
  const markup = renderLayout("service", "truthful");
  assert.equal(count(markup, "<details>"), 3);
  assert.equal(count(markup, "<details open"), 0);
  assert.match(markup, /<summary>Exact detail one<\/summary>/);
  assert.match(markup, /Exact answer one\./);
  assert.match(markup, /<summary>Exact detail two<\/summary>/);
  assert.match(markup, /Exact answer two\./);
  assert.doesNotMatch(markup, /top questions|category|search/i);
});

test("County consumes audited city and remainder partitions once and keeps its FAQ", () => {
  const markup = renderLayout("county", "truthful");
  assert.equal(count(markup, ">Exact City One</a>"), 1);
  assert.equal(count(markup, ">Exact City Two</a>"), 1);
  assert.equal(count(markup, ">Exact county remainder</a>"), 1);
  assert.match(markup, /data-v5-city-index="0"/);
  assert.match(markup, /data-v5-city-index="1"/);
  assert.match(markup, /href="\/theme-lab\/performance-local\/v5\/generated-pages\/1301"/);
  assert.match(markup, /Exact city purpose one\./);
  assert.match(markup, /Exact city purpose two\./);
  assert.match(markup, /Exact County question\?/);
  assert.match(markup, /Exact County answer\./);
  assert.match(markup, /data-v5-layout-key="performance-local-v5-service-county"/);
});

test("About and Contact use only their V5 manifest regions", () => {
  const about = renderLayout("about", "truthful");
  assert.match(about, /data-v5-composition="story-and-credentials"/);
  assert.match(about, /Exact company story/);
  assert.match(about, /Exact experience/);
  assert.match(about, /Exact purpose/);
  assert.equal(count(about, "<form"), 1);

  const contact = renderLayout("contact", "truthful");
  assert.match(contact, /data-v5-region="contact_information"/);
  assert.match(contact, /Exact ways to contact/);
  assert.match(contact, /Exact Hours source text\./);
  assert.match(contact, /Exact Service Area source text\./);
  assert.equal(count(contact, "Exact Hours source text."), 1);
  assert.equal(count(contact, "Exact Service Area source text."), 1);
  assert.doesNotMatch(contact, /contact_expectations/);
});

test("FAQ remains closed by default and its source support is inside final conversion", () => {
  const markup = renderLayout("faq", "truthful");
  assert.match(markup, /<summary>Exact FAQ question\?<\/summary>/);
  assert.match(markup, /Exact FAQ answer\./);
  assert.equal(count(markup, "<details>"), 1);
  const finalIndex = markup.indexOf('data-v5-shared-final-conversion="true"');
  assert.ok(markup.indexOf("Exact contact support", finalIndex) > finalIndex);
  assert.ok(markup.indexOf("LIC-123", finalIndex) > finalIndex);
});

test("truthful missing media has no wrapper while structural demo uses the exact placement", () => {
  const truthful = renderLayout("service", "truthful");
  assert.doesNotMatch(truthful, /performanceLocalV5DemoMedia|performanceLocalV5MediaFrame/);
  assert.match(truthful, /performanceLocalV5HeroGrid performanceLocalV5HeroGridSingle/);
  assert.match(truthful, /data-v5-hero-media-state="omitted"/);
  const demo = renderLayout("service", "structural_demo");
  assert.match(demo, /DEMO MEDIA SLOT — NOT SITE CONTENT/);
  assert.match(demo, /data-v5-hero-media-state="demo"/);
  assert.doesNotMatch(demo, /performanceLocalV5HeroGridSingle/);
  assert.match(demo, /data-v5-demo-target-instance-key="hero"/);
  assert.equal(count(demo, 'data-source-instance-key="media_placement:hero"'), 1);
});

test("non-city V5 renderer is statically isolated from all V4 presenters and classes", () => {
  const layouts = source("src/components/PerformanceLocalV5Layouts.tsx");
  const renderer = source("src/components/PerformanceLocalV5Renderer.tsx");
  assert.doesNotMatch(layouts, /PerformanceLocalV4|performanceLocalV4/);
  assert.doesNotMatch(renderer, /PerformanceLocalV4|performanceLocalV4/);
  assert.match(renderer, /querySelector<HTMLElement>\("\.performanceLocalV5Footer"\)/);
  assert.match(renderer, /className="performanceLocalV5Site"/);
  assert.match(renderer, /if \(pageType === "city_service"\)/);
  assert.match(renderer, /<PerformanceLocalRenderer/);
  assert.match(layouts, /data-v5-menu-open=\{menuOpen \? "true" : "false"\}/);
  assert.match(layouts, /closeMenu\(\{ restoreFocus: true \}\)/);
});

test("City-Service changes only the governed top presentation and preserves the configured legacy subtree", () => {
  const page = cityServicePage();
  const composition = cityServiceComposition();
  const audit = cityServiceAudit();
  const configuration = cityServiceConfiguration();
  const previewedAt = new Date("2026-08-17T12:00:00Z");
  const suppressedStickyActions = { ...configuration.stickyActions, desktopHeaderActionsEnabled: false };
  const suppressedToggles = {
    ...configuration.toggles,
    campaignBanner: false,
    stickyActionBar: false,
    trustStrip: false,
  };
  const actionConfiguration = cityServiceActionConfiguration(configuration, "generated_page");
  const legacyCapabilities = renderToStaticMarkup(
    <StaticRouter location="/theme-lab/performance-local/v5/generated-pages/41">
      <PerformanceLocalRenderer
        page={page}
        composition={composition}
        campaign={null}
        estimateForm={configuration.estimateForm}
        formSubmission={configuration.formSubmission}
        governedContact={configuration.governedContact}
        rendererIdentity={configuration.rendererIdentity}
        stickyActions={configuration.stickyActions}
        toggles={{ ...configuration.toggles, campaignBanner: false, stickyActionBar: false }}
        previewedAt={previewedAt}
      />
    </StaticRouter>,
  );
  assert.match(legacyCapabilities, /class="performanceLocalTrustStrip"/);
  assert.equal(count(legacyCapabilities, "JB360566"), 2);
  assert.match(legacyCapabilities, /Jordan Ward/);
  assert.match(legacyCapabilities, /class="performanceLocalButton performanceLocalHeaderEstimate"/);
  const direct = renderToStaticMarkup(
    <StaticRouter location="/theme-lab/performance-local/v5/generated-pages/41">
      <PerformanceLocalRenderer
        page={page}
        composition={composition}
        campaign={null}
        estimateForm={configuration.estimateForm}
        formSubmission={configuration.formSubmission}
        governedContact={configuration.governedContact}
        rendererIdentity={configuration.rendererIdentity}
        stickyActions={suppressedStickyActions}
        toggles={suppressedToggles}
        previewedAt={previewedAt}
      />
    </StaticRouter>,
  );
  for (const campaignBannerEnabled of [true, false]) {
    const wrapped = renderToStaticMarkup(
      <StaticRouter location="/theme-lab/performance-local/v5/generated-pages/41">
        <PerformanceLocalV5Renderer
          actionConfiguration={actionConfiguration}
          audit={audit}
          campaignBannerEnabled={campaignBannerEnabled}
          composition={composition}
          page={page}
          previewedAt={previewedAt}
          readiness={cityServiceReadiness}
          reviewMode="truthful"
          previewSurface="generated_page"
          v3Configuration={configuration}
        />
      </StaticRouter>,
    );
    assert.match(wrapped, /class="performanceLocalV5CityServicePreview"/);
    assert.match(wrapped, /data-v5-preservation-control="below-hero-legacy-subtree"/);
    assert.match(wrapped, /data-v5-top-preview="hero-and-conversion-stack"/);
    assert.match(wrapped, /data-v5-top-action-mode="estimate"/);
    assert.match(wrapped, /href="tel:5550100200"[^>]*aria-label="Call \(555\) 010-0200"/);
    assert.match(wrapped, /<strong>\(555\) 010-0200<\/strong>/);
    assert.match(wrapped, /class="performanceLocalV5StickyActionBanner"[^>]*aria-label="Request an Estimate"/);
    assert.match(wrapped, /href="\/theme-lab\/performance-local\/v5\/generated-pages\/41\/request-an-estimate"[^>]*>Request an Estimate<\/a>/);
    assert.doesNotMatch(wrapped, /class="performanceLocalCampaign/);
    assert.doesNotMatch(wrapped, /class="performanceLocalStickyActions/);
    assert.doesNotMatch(wrapped, /class="performanceLocalTrustStrip"/);
    assert.doesNotMatch(wrapped, /Jordan Ward/);
    assert.equal(count(wrapped, "JB360566"), 1);
    assert.match(wrapped, /class="performanceLocalFooterContact"[\s\S]*?<span>License JB360566<\/span>/);
    assert.equal(count(wrapped, "Exact governed Page 41 introductory paragraph for the focused top presentation."), 1);
    const headerStart = wrapped.indexOf('<header class="performanceLocalHeader"');
    const headerEnd = wrapped.indexOf("</header>", headerStart);
    assert.ok(headerStart >= 0 && headerEnd > headerStart, wrapped);
    const headerMarkup = wrapped.slice(headerStart, headerEnd);
    assert.doesNotMatch(headerMarkup, /performanceLocalPhone|performanceLocalHeaderEstimate|href="tel:/);
    assert.match(headerMarkup, /class="performanceLocalMenuTrigger"/);
    const heroStart = wrapped.indexOf('<section class="performanceLocalHero"');
    const heroEnd = wrapped.indexOf("</section>", heroStart);
    assert.ok(heroStart >= 0 && heroEnd > heroStart, wrapped);
    const heroMarkup = wrapped.slice(heroStart, heroEnd);
    assert.match(heroMarkup, /href="tel:5550100200"/);
    assert.match(heroMarkup, /href="#performance-local-form-config-91">Request an Estimate<\/a>/);
    assert.equal(count(wrapped, "2326ac885a03490482e47dcc26d0eca3-optimized.webp"), 1);
    assert.equal(count(wrapped, 'data-source-instance-key="media_placement:hero"'), 1);
    assert.match(wrapped, /alt="Flo-Zone technician outside a branded tented Orlando property"/);
    assert.match(wrapped, /object-position:50% 50%/);
    assert.doesNotMatch(wrapped, /DEMO SPECIAL — NOT SITE CONTENT/);
    const start = wrapped.indexOf('<div class="performanceLocalSite"');
    assert.ok(start >= 0, wrapped);
    const delegatedSubtree = wrapped.slice(start, -"</div>".length);
    assert.equal(delegatedSubtree, direct);
  }
});

test("top conversion presenter supports all permanent action modes and fails closed when disabled", () => {
  const destination = "#performance-local-form-config-91";
  const enabledModes: readonly PerformanceLocalV5TopAction[] = [
    { mode: "special", label: "Exact governed special", destination },
    { accessibilityLabel: "Request an Estimate page", mode: "estimate", label: "Request an Estimate", destination },
    { mode: "service_promotion", label: "Exact governed service promotion", destination },
  ];
  for (const action of enabledModes) {
    const markup = renderToStaticMarkup(
      <PerformanceLocalV5TopConversionStack action={action} callLabel="Call" contact={governedContact} />,
    );
    assert.match(markup, new RegExp(`data-v5-top-action-mode="${action.mode}"`));
    assert.match(markup, /data-v5-top-action-enabled="true"/);
    assert.equal(count(markup, "performanceLocalV5StickyActionBanner"), 1);
    assert.match(markup, new RegExp(`href="${destination}"`));
    if (action.mode === "estimate") assert.match(markup, /aria-label="Request an Estimate page"/);
  }
  const disabled = renderToStaticMarkup(
    <PerformanceLocalV5TopConversionStack action={{ mode: "disabled" }} callLabel="Call" contact={governedContact} />,
  );
  assert.match(disabled, /data-v5-top-action-mode="disabled"/);
  assert.match(disabled, /data-v5-top-action-enabled="false"/);
  assert.doesNotMatch(disabled, /performanceLocalV5StickyActionBanner/);
  assert.match(disabled, /href="tel:5550100200"/);
});

test("the centralized resolver authorizes exact Estimate destinations and rejects unsafe or unbound configuration", () => {
  const delivery = cityServiceConfiguration();
  const exactFormIdentity = cityServiceFormIdentity(delivery);
  const configured = cityServiceActionConfiguration(delivery, "generated_page");
  const evaluatedAt = new Date("2026-08-23T18:00:00Z");
  const exactRoute = resolvePerformanceLocalV5TopAction({
    configuration: configured,
    currentRoute: "/theme-lab/performance-local/v5/generated-pages/41",
    currentSurface: "site",
    evaluatedAt,
    exactFormIdentity,
  });
  assert.deepEqual(exactRoute, {
    action: {
      accessibilityLabel: "Request an Estimate",
      destination: "/theme-lab/performance-local/v5/generated-pages/41/request-an-estimate",
      label: "Request an Estimate",
      mode: "estimate",
    },
    reason: "configured_action",
  });

  const exactAnchor = resolvePerformanceLocalV5TopAction({
    configuration: {
      ...configured,
      sticky: { destination: exactFormIdentity.destination, mode: "estimate", publicLabel: "Request an Estimate" },
    },
    currentRoute: "/theme-lab/performance-local/v5/generated-pages/41",
    currentSurface: "site",
    evaluatedAt,
    exactFormIdentity,
  });
  assert.equal(exactAnchor.action.mode === "estimate" ? exactAnchor.action.destination : null, exactFormIdentity.destination);

  for (const configuration of [
    { ...configured, sticky: { destination: "https://example.test/estimate", mode: "estimate", publicLabel: "Request an Estimate" } },
    { ...configured, sticky: { destination: "//example.test/estimate", mode: "estimate", publicLabel: "Request an Estimate" } },
    { ...configured, sticky: { destination: "/unauthorized-estimate", mode: "estimate", publicLabel: "Request an Estimate" } },
    { ...configured, estimate: { enabled: false } },
    { ...configured, estimate: configured.estimate.enabled ? { ...configured.estimate, introduction: " " } : configured.estimate },
  ] as readonly PerformanceLocalV5ActionConfiguration[]) {
    assert.deepEqual(resolvePerformanceLocalV5TopAction({
      configuration,
      currentRoute: "/theme-lab/performance-local/v5/generated-pages/41",
      currentSurface: "site",
      evaluatedAt,
      exactFormIdentity,
    }).action, { mode: "disabled" });
  }
});

test("Special expiration, fallback, and self-link decisions are deterministic and fail closed", () => {
  const delivery = cityServiceConfiguration();
  const exactFormIdentity = cityServiceFormIdentity(delivery);
  const configured = cityServiceActionConfiguration(delivery, "special");
  assert.equal(configured.special.enabled, true);
  const evaluatedAt = new Date("2026-08-23T18:00:00Z");
  const siteInput = {
    currentRoute: "/theme-lab/performance-local/v5/generated-pages/41",
    currentSurface: "site" as const,
    evaluatedAt,
    exactFormIdentity,
  };
  const active = resolvePerformanceLocalV5TopAction({ configuration: configured, ...siteInput });
  assert.equal(active.action.mode, "special");

  const expired: PerformanceLocalV5ActionConfiguration = {
    ...configured,
    special: configured.special.enabled ? { ...configured.special, expiresAt: "2026-08-23T17:59:59Z" } : configured.special,
  };
  const expiredResult = resolvePerformanceLocalV5TopAction({ configuration: expired, ...siteInput });
  assert.equal(expiredResult.reason, "estimate_fallback");
  assert.equal(expiredResult.action.mode, "estimate");

  for (const sticky of [
    { destination: configured.special.enabled ? configured.special.route : "/invalid", mode: "special", publicLabel: " " },
    { accessibilityLabel: " ", destination: configured.special.enabled ? configured.special.route : "/invalid", mode: "special", publicLabel: "Exact governed special" },
    { destination: "/unauthorized-special", mode: "special", publicLabel: "Exact governed special" },
  ] as const) {
    const invalidExpired: PerformanceLocalV5ActionConfiguration = { ...expired, sticky };
    const invalidExpiredResult = resolvePerformanceLocalV5TopAction({ configuration: invalidExpired, ...siteInput });
    assert.equal(invalidExpiredResult.reason, "invalid_configuration");
    assert.deepEqual(invalidExpiredResult.action, { mode: "disabled" });
  }

  const exactBoundary: PerformanceLocalV5ActionConfiguration = {
    ...configured,
    special: configured.special.enabled ? { ...configured.special, expiresAt: "2026-08-23T18:00:00Z" } : configured.special,
  };
  assert.equal(resolvePerformanceLocalV5TopAction({ configuration: exactBoundary, ...siteInput }).reason, "estimate_fallback");

  const invalidExpiration: PerformanceLocalV5ActionConfiguration = {
    ...configured,
    special: configured.special.enabled ? { ...configured.special, expiresAt: "August eventually" } : configured.special,
  };
  const invalidResult = resolvePerformanceLocalV5TopAction({ configuration: invalidExpiration, ...siteInput });
  assert.equal(invalidResult.reason, "invalid_configuration");
  assert.deepEqual(invalidResult.action, { mode: "disabled" });

  const noFallback: PerformanceLocalV5ActionConfiguration = { ...expired, estimate: { enabled: false } };
  assert.equal(resolvePerformanceLocalV5TopAction({ configuration: noFallback, ...siteInput }).reason, "expired_without_fallback");

  const specialSelfLink = resolvePerformanceLocalV5TopAction({
    configuration: configured,
    currentRoute: configured.special.enabled ? configured.special.route : "/invalid",
    currentSurface: "special",
    evaluatedAt,
    exactFormIdentity,
  });
  assert.equal(specialSelfLink.reason, "self_link_switched_to_estimate");
  assert.equal(specialSelfLink.action.mode, "estimate");

  const specialWithoutBodyEstimate = configured.special.enabled ? {
    ...configured,
    special: { ...configured.special, estimateActionEnabled: false },
  } : configured;
  const specialWithoutBodyEstimateSelfLink = resolvePerformanceLocalV5TopAction({
    configuration: specialWithoutBodyEstimate,
    currentRoute: specialWithoutBodyEstimate.special.enabled ? specialWithoutBodyEstimate.special.route : "/invalid",
    currentSurface: "special",
    evaluatedAt,
    exactFormIdentity,
  });
  assert.equal(specialWithoutBodyEstimateSelfLink.reason, "self_link_switched_to_estimate");
  assert.equal(specialWithoutBodyEstimateSelfLink.action.mode, "estimate");

  const identicalRoutes: PerformanceLocalV5ActionConfiguration = configured.estimate.enabled && configured.special.enabled ? {
    ...configured,
    special: { ...configured.special, route: configured.estimate.route },
    sticky: {
      destination: configured.estimate.route,
      mode: "special",
      publicLabel: "Exact governed special",
    },
  } : configured;
  const identicalRouteResult = resolvePerformanceLocalV5TopAction({ configuration: identicalRoutes, ...siteInput });
  assert.equal(identicalRouteResult.reason, "invalid_configuration");
  assert.deepEqual(identicalRouteResult.action, { mode: "disabled" });

  const estimateSticky: PerformanceLocalV5ActionConfiguration = configured.estimate.enabled ? {
    ...configured,
    sticky: {
      destination: configured.estimate.route,
      mode: "estimate",
      publicLabel: "Request an Estimate",
    },
  } : configured;
  const estimateSelfLink = resolvePerformanceLocalV5TopAction({
    configuration: estimateSticky,
    currentRoute: estimateSticky.estimate.enabled ? estimateSticky.estimate.route : "/invalid",
    currentSurface: "estimate",
    evaluatedAt,
    exactFormIdentity,
  });
  assert.equal(estimateSelfLink.reason, "self_link_switched_to_special");
  assert.equal(estimateSelfLink.action.mode, "special");
});

test("service promotion mode accepts only an explicitly authorized internal route", () => {
  const delivery = cityServiceConfiguration();
  const exactFormIdentity = cityServiceFormIdentity(delivery);
  const base = cityServiceActionConfiguration(delivery, "generated_page");
  const evaluatedAt = new Date("2026-08-23T18:00:00Z");
  const route = "/theme-lab/performance-local/v5/generated-pages/73";
  const configured: PerformanceLocalV5ActionConfiguration = {
    ...base,
    authorizedServicePromotionDestinations: [route],
    sticky: { destination: route, mode: "service_promotion", publicLabel: "Drywood Termite Tenting" },
  };
  assert.equal(resolvePerformanceLocalV5TopAction({
    configuration: configured,
    currentRoute: "/theme-lab/performance-local/v5/generated-pages/41",
    currentSurface: "site",
    evaluatedAt,
    exactFormIdentity,
  }).action.mode, "service_promotion");
  for (const destination of ["/not-allowlisted", "https://example.test/service", "//example.test/service"]) {
    const rejected: PerformanceLocalV5ActionConfiguration = {
      ...configured,
      sticky: { ...configured.sticky, destination } as PerformanceLocalV5ActionConfiguration["sticky"],
    };
    assert.deepEqual(resolvePerformanceLocalV5TopAction({
      configuration: rejected,
      currentRoute: "/theme-lab/performance-local/v5/generated-pages/41",
      currentSurface: "site",
      evaluatedAt,
      exactFormIdentity,
    }).action, { mode: "disabled" });
  }
});

test("conditional Special and Estimate surfaces reuse the shared shell and the one inert governed form", () => {
  const special = renderCityServiceSurface("special");
  assert.match(special, /class="performanceLocalV5Site performanceLocalV5ConditionalPage"/);
  assert.match(special, /data-v5-conditional-surface="special"/);
  assert.match(special, /data-v5-action-resolution="self_link_switched_to_estimate"/);
  assert.match(special, /data-v5-top-action-mode="estimate"/);
  assert.equal(count(special, "DEMO SPECIAL — NOT SITE CONTENT"), 1);
  assert.match(special, /No public Special is configured\. This local Theme Lab preview demonstrates the optional Special-page layout only\./);
  assert.match(special, /href="tel:5550100200"/);
  assert.match(special, /href="\/theme-lab\/performance-local\/v5\/generated-pages\/41\/request-an-estimate"/);
  assert.doesNotMatch(special, /performanceLocalV5SpecialDetails|<form/);
  assert.match(special, /class="performanceLocalV5Header"/);
  assert.match(special, /class="performanceLocalV5Footer"/);
  assert.doesNotMatch(special, /performanceLocalV5StickyActions/);

  const estimate = renderCityServiceSurface("estimate");
  assert.match(estimate, /data-v5-conditional-surface="estimate"/);
  assert.match(estimate, /data-v5-top-action-mode="special"/);
  assert.equal(count(estimate, "DEMO SPECIAL — NOT SITE CONTENT"), 3);
  assert.equal(count(estimate, "<form"), 1);
  assert.equal(count(estimate, 'data-field-key="'), 5);
  assert.equal(count(estimate, "readonly=\"\""), 5);
  assert.equal(count(estimate, "Preview only. Information entered here is not submitted or saved."), 1);
  assert.match(estimate, /class="performanceLocalV5ConditionalIntroduction">Request an estimate for the service in this area\.<\/p>/);
  assert.match(estimate, /data-v5-maximum-field-count="6"/);
  assert.match(estimate, /data-provider-configured="false"/);
  assert.match(estimate, /data-collects-data="false"/);
  assert.match(estimate, /<button type="submit" disabled="">Request an Estimate<\/button>/);
  assert.equal(count(estimate, `id="${performanceLocalFormDomId(91)}"`), 1);
  assert.doesNotMatch(estimate, /performanceLocalV5StickyActions/);

  const disabled = renderCityServiceSurface("sticky_disabled");
  assert.match(disabled, /class="performanceLocalV5CityServicePreview"/);
  assert.match(disabled, /data-v5-top-action-enabled="false"/);
  assert.match(disabled, /data-v5-top-action-mode="disabled"/);
  assert.doesNotMatch(disabled, /performanceLocalV5StickyActionBanner/);
  assert.match(disabled, /performanceLocalV5StickyPhoneBar/);
});

test("optional module resolver is page-scoped, independent, exact-keyed, and fail-closed", () => {
  const valid = optionalModuleConfiguration("both");
  const resolved = resolveOptionalModules(valid);
  assert.equal(resolved.reviewTrust?.sources.length, 3);
  assert.equal(resolved.locationMap?.mode, "business_location");
  assert.equal(resolved.locationMap?.sectionHeading, "Our Location");
  assert.equal(resolved.locationMap?.mode === "business_location" ? resolved.locationMap.approvedAddressLines.length : 0, 2);

  const cityServiceArea = resolveOptionalModules({ locationMap: validCityServiceAreaConfiguration() });
  assert.equal(cityServiceArea.locationMap?.mode, "city_service_area");
  assert.equal(cityServiceArea.locationMap?.sectionHeading, "Serving Orlando, Florida");
  assert.equal(cityServiceArea.locationMap?.mode === "city_service_area" ? cityServiceArea.locationMap.targetCity : null, "Orlando");
  assert.equal(cityServiceArea.locationMap?.mode === "city_service_area" ? cityServiceArea.locationMap.targetState : null, "Florida");
  assert.equal(
    resolveOptionalModules({ locationMap: validCityServiceAreaConfiguration() }, { pageType: "service" }).locationMap?.mode,
    "city_service_area",
  );

  for (const pageType of ["home", "county", "about", "contact", "faq", "special", "estimate", null]) {
    assert.deepEqual(resolveOptionalModules(valid, { pageType }), { locationMap: null, reviewTrust: null }, String(pageType));
  }
  assert.deepEqual(resolveOptionalModules(undefined), { locationMap: null, reviewTrust: null });
  assert.deepEqual(resolveOptionalModules({}), { locationMap: null, reviewTrust: null });
  assert.deepEqual(resolveOptionalModules({ reviewTrust: { enabled: false } }), { locationMap: null, reviewTrust: null });
  assert.deepEqual(resolveOptionalModules({ locationMap: { mode: "disabled" } }), { locationMap: null, reviewTrust: null });
  assert.deepEqual(resolveOptionalModules({ locationMap: { mode: "disabled", extra: true } } as unknown), { locationMap: null, reviewTrust: null });
  assert.deepEqual(resolveOptionalModules({ locationMap: { enabled: true } } as unknown), { locationMap: null, reviewTrust: null });
  assert.deepEqual(resolveOptionalModules({ locationMap: { mode: "unknown" } } as unknown), { locationMap: null, reviewTrust: null });
  assert.deepEqual(resolveOptionalModules({ reviewTrust: valid.reviewTrust, surprise: true }), { locationMap: null, reviewTrust: null });

  const sources = validReviewTrustConfiguration().sources!;
  for (const reviewTrust of [
    { ...validReviewTrustConfiguration(), sources: [...sources, sources[0]] },
    { ...validReviewTrustConfiguration(), sources: [sources[0], { ...sources[1], sourceKey: sources[0].sourceKey }] },
    { ...validReviewTrustConfiguration(), unknown: true },
    { ...validReviewTrustConfiguration(), heading: " " },
  ]) {
    const result = resolveOptionalModules({ locationMap: validBusinessLocationConfiguration(), reviewTrust } as unknown);
    assert.equal(result.reviewTrust, null);
    assert.ok(result.locationMap);
  }

  const partiallyInvalid = resolveOptionalModules({
    reviewTrust: {
      ...validReviewTrustConfiguration(),
      sources: [
        sources[0],
        { ...sources[1], enabled: false },
        { ...sources[2], imageAltText: "" },
      ],
    },
  });
  assert.equal(partiallyInvalid.reviewTrust?.sources.length, 1);
  assert.equal(partiallyInvalid.reviewTrust?.sources[0].sourceKey, "approved-source-one");

  const unknownKeySource = resolveOptionalModules({
    reviewTrust: {
      ...validReviewTrustConfiguration(),
      sources: [sources[0], { ...sources[1], extra: "unknown" }],
    },
  });
  assert.equal(unknownKeySource.reviewTrust?.sources.length, 1);
  assert.equal(unknownKeySource.reviewTrust?.sources[0].sourceKey, "approved-source-one");

  for (const source of [
    { ...sources[0], badgeImageReference: "missing-reference" },
    { ...sources[0], publicName: "" },
    { ...sources[0], description: "" },
    { ...sources[0], imageAltText: "" },
    { ...sources[0], profileDestination: "javascript:alert(1)" },
    { ...sources[0], verifiedRatingText: " " },
    { ...sources[0], extra: "unknown" },
  ]) {
    assert.equal(resolveOptionalModules({ reviewTrust: { enabled: true, sources: [source] } }).reviewTrust, null);
  }
});

test("optional URL, image, and Google embed gates accept only explicit safe shapes", () => {
  for (const value of [
    "https://reviews.example.com/flo-zone",
    "https://maps.example.com/directions?to=approved",
  ]) assert.equal(isPerformanceLocalV5SafeHttpsDestination(value), true, value);
  for (const value of [
    "http://reviews.example.com/flo-zone",
    "//reviews.example.com/flo-zone",
    "javascript:alert(1)",
    "data:text/html,unsafe",
    "file:///private",
    "mailto:review@example.com",
    "https://localhost/review",
    "https://0.0.0.0/review",
    "https://100.64.0.1/review",
    "https://[::1]/review",
    "https://[fc00::1]/review",
    "https://[fe80::1]/review",
    "https://router.home.arpa/review",
    "https://user:pass@example.com/review",
    "not a url",
  ]) assert.equal(isPerformanceLocalV5SafeHttpsDestination(value), false, value);

  for (const value of [
    "/assets/review-source.svg",
    "/media/review-source.webp",
    "/api/media/files/review-source.png",
  ]) assert.equal(isPerformanceLocalV5SafeLocalImageUrl(value), true, value);
  for (const value of [
    "https://example.com/review.svg",
    "//example.com/review.svg",
    "/public/review.svg",
    "/assets/review.svg?version=1",
    "/assets/%2e%2e%2fprivate.svg",
    "/assets/review.txt",
    "data:image/svg+xml,unsafe",
  ]) assert.equal(isPerformanceLocalV5SafeLocalImageUrl(value), false, value);

  for (const value of [
    "https://www.google.com/maps/embed?pb=approved-binding",
    "https://www.google.com/maps/embed/v1/place?key=approved-key&q=approved-location",
    "https://www.google.com/maps/embed/v1/directions?key=approved-key&origin=approved-origin&destination=approved-destination",
    "https://www.google.com/maps/embed/v1/view?key=approved-key&center=28.5,-81.4&zoom=11",
    "https://www.google.com/maps/embed/v1/streetview?key=approved-key&location=28.5,-81.4",
  ]) assert.equal(isPerformanceLocalV5SafeGoogleMapsEmbedUrl(value), true, value);
  for (const value of [
    "http://www.google.com/maps/embed?pb=unsafe",
    "//www.google.com/maps/embed?pb=unsafe",
    "https://google.com/maps/embed?pb=wrong-origin",
    "https://maps.google.com/maps/embed?pb=wrong-origin",
    "https://www.google.com/maps/search/?api=1&query=ordinary-search",
    "https://www.google.com/maps/embed",
    "https://www.google.com/maps/embed/v1/place?key=approved-key",
    "https://www.google.com/maps/embed/v1/view?key=approved-key&location=28.5,-81.4",
    "https://www.google.com/maps/embed/v1/streetview?key=approved-key&center=28.5,-81.4",
    "https://maps.app.goo.gl/shortened",
    "https://www.google.com.evil.example/maps/embed?pb=lookalike",
  ]) assert.equal(isPerformanceLocalV5SafeGoogleMapsEmbedUrl(value), false, value);

  const copiedEmbedUrl = "https://www.google.com/maps/embed/v1/place?key=approved-key&q=Orlando%2C+Florida";
  const copiedEmbedCode = `<iframe src="https://www.google.com/maps/embed/v1/place?key=approved-key&amp;q=Orlando%2C+Florida" width="600" height="450" style="border:0" allowfullscreen="" loading="eager" referrerpolicy="unsafe-url" onload="ignored()"></iframe>`;
  assert.equal(resolvePerformanceLocalV5GoogleMapsEmbedInput(copiedEmbedUrl), copiedEmbedUrl);
  assert.equal(resolvePerformanceLocalV5GoogleMapsEmbedInput(copiedEmbedCode), copiedEmbedUrl);
  for (const value of [
    `<iframe src="http://www.google.com/maps/embed?pb=unsafe"></iframe>`,
    `<iframe src="https://www.google.com/maps/search/?api=1&q=unsafe"></iframe>`,
    `<iframe data-src="https://www.google.com/maps/embed?pb=missing-src"></iframe>`,
    `<iframe src=https://www.google.com/maps/embed?pb=unquoted></iframe>`,
    `<iframe src="https://www.google.com/maps/embed?pb=one" src="https://www.google.com/maps/embed?pb=two"></iframe>`,
    `<iframe src="https://www.google.com/maps/embed?pb=body">not empty</iframe>`,
    `<div><iframe src="https://www.google.com/maps/embed?pb=wrapped"></iframe></div>`,
    `<iframe src="https://www.google.com/maps/embed?pb=unclosed">`,
    `<script>unsafe()</script>`,
    `<iframe src="https://www.google.com/maps/embed?pb=${"x".repeat(16_384)}"></iframe>`,
  ]) assert.equal(resolvePerformanceLocalV5GoogleMapsEmbedInput(value), null, value.slice(0, 100));

  for (const locationMap of [
    { ...validBusinessLocationConfiguration(), approvedAddressLines: [] },
    { ...validBusinessLocationConfiguration(), approvedAddressLines: ["1", "2", "3", "4"] },
    { ...validBusinessLocationConfiguration(), approvedAddressLines: ["Private residence"] },
    { ...validBusinessLocationConfiguration(), approvedLocationName: "" },
    { ...validBusinessLocationConfiguration(), mapTitle: "" },
    { ...validBusinessLocationConfiguration(), governedPhoneDisplay: "(555) 999-9999" },
    { ...validBusinessLocationConfiguration(), directionsDestination: "mailto:unsafe@example.com" },
    { ...validBusinessLocationConfiguration(), googleMapsEmbedInput: "https://www.google.com/maps/search/?api=1&q=unsafe" },
    { ...validBusinessLocationConfiguration(), targetCity: "Orlando" },
    { ...validBusinessLocationConfiguration(), unknown: true },
    { ...validCityServiceAreaConfiguration(), targetCity: "Tampa" },
    { ...validCityServiceAreaConfiguration(), targetState: "Georgia" },
    { ...validCityServiceAreaConfiguration(), sectionHeading: "Our Location" },
    { ...validCityServiceAreaConfiguration(), sectionHeading: "Our Orlando Location" },
    { ...validCityServiceAreaConfiguration(), sectionHeading: "Orlando Office" },
    { ...validCityServiceAreaConfiguration(), description: "Visit our office in this service area." },
    { ...validCityServiceAreaConfiguration(), description: "Visit us at 123 Main Street." },
    { ...validCityServiceAreaConfiguration(), approvedAddressLines: ["123 Not Allowed Street"] },
    { ...validCityServiceAreaConfiguration(), googleMapsEmbedInput: "https://www.google.com/maps/search/?api=1&q=unsafe" },
    { ...validCityServiceAreaConfiguration(), unknown: true },
  ]) {
    const result = resolveOptionalModules({ locationMap, reviewTrust: validReviewTrustConfiguration() } as unknown);
    assert.equal(result.locationMap, null);
    assert.ok(result.reviewTrust);
  }

  assert.equal(
    resolveOptionalModules(
      { locationMap: validCityServiceAreaConfiguration() },
      { governedTargetCity: null, governedTargetState: null },
    ).locationMap,
    null,
  );
});

test("Service and City-Service render the two demo modules only at their approved seams", () => {
  const configuration = optionalModuleConfiguration("both", true);
  const demoResolution = resolveOptionalModules(configuration, { presentation: "theme_lab_demo" });
  const service = staticMarkup({
    ...layoutProps("service", "truthful"),
    optionalModules: demoResolution,
  });
  const serviceHeroEnd = service.indexOf("</section>", service.indexOf('data-v5-region="hero"'));
  const serviceTrust = service.indexOf('data-v5-optional-module="review-trust"');
  const serviceOverview = service.indexOf("Exact service overview");
  const serviceFaq = service.indexOf("Exact service FAQ?");
  const serviceLocation = service.indexOf('data-v5-optional-module="location-map"');
  const serviceFinal = service.indexOf('data-v5-shared-final-conversion="true"');
  assert.ok(serviceHeroEnd < serviceTrust && serviceTrust < serviceOverview);
  assert.ok(serviceFaq < serviceLocation && serviceLocation < serviceFinal);
  assert.equal(count(service, "<h1"), 1);

  const city = renderCityServiceSurface("review_trust_location_map", {
    configuration,
    presentation: "theme_lab_demo",
  });
  const cityHeroEnd = city.indexOf("</section>", city.indexOf('class="performanceLocalHero"'));
  const cityTrust = city.indexOf('data-v5-optional-module="review-trust"');
  const cityLocation = city.indexOf('data-v5-optional-module="location-map"');
  const cityFinal = city.indexOf('class="performanceLocalFinalCta"');
  assert.ok(cityHeroEnd < cityTrust && cityTrust < cityLocation && cityLocation < cityFinal);
  assert.equal(count(city, "DEMO TRUST SOURCE — NOT SITE CONTENT"), 3);
  assert.equal(count(city, "DEMO BADGE — NOT SITE CONTENT"), 3);
  assert.equal(count(city, 'data-v5-demo-trust-optional-fields="true"'), 3);
  assert.equal(count(city, "Optional rating / count"), 3);
  assert.equal(count(city, "Optional profile link"), 3);
  assert.equal(count(city, "DEMO MAP — NOT SITE CONTENT"), 1);
  assert.equal(count(city, "Serving Orlando, Florida"), 1);
  assert.equal(count(city, "<h1"), 1);
  assert.equal(count(city, "<iframe"), 0);
  assert.doesNotMatch(city.slice(cityLocation, cityFinal), /<address|Approved public location|Our Location|DEMO LOCATION|DEMO APPROVED ADDRESS|Get directions|performanceLocalV5LocationActions/);
  assert.doesNotMatch(city.slice(cityTrust, cityLocation), /<img|verifiedRating|verifiedReviewCount|href="https:/);
  assert.doesNotMatch(city.slice(cityTrust, cityLocation), /<a\b/);
  assert.doesNotMatch(city.slice(cityTrust, cityLocation), />0[123]</);
  assert.doesNotMatch(city, /performanceLocalStickyActions|performanceLocalV5StickyActions/);

  const ordinary = renderCityServiceSurface("generated_page");
  assert.doesNotMatch(ordinary, /data-v5-optional-module|performanceLocalV5OptionalModule|DEMO MAP|DEMO TRUST/);
  const special = renderCityServiceSurface("special", { configuration, presentation: "theme_lab_demo" });
  const estimate = renderCityServiceSurface("estimate", { configuration, presentation: "theme_lab_demo" });
  assert.doesNotMatch(special, /data-v5-optional-module/);
  assert.doesNotMatch(estimate, /data-v5-optional-module/);
});

test("public optional modules contain only approved local images and the allowlisted lazy map embed", () => {
  const publicMarkup = renderCityServiceSurface("generated_page", {
    configuration: optionalModuleConfiguration("both"),
    presentation: "public",
  });
  const trustStart = publicMarkup.indexOf('data-v5-optional-module="review-trust"');
  const locationStart = publicMarkup.indexOf('data-v5-optional-module="location-map"');
  const trustMarkup = publicMarkup.slice(trustStart, locationStart);
  const locationMarkup = publicMarkup.slice(locationStart, publicMarkup.indexOf('class="performanceLocalFinalCta"'));
  assert.match(trustMarkup, /<img alt="Approved source one" decoding="async" loading="lazy" src="\/assets\/review-source-one\.svg"/);
  assert.match(trustMarkup, /href="https:\/\/reviews\.example\.com\/source-one" rel="noopener noreferrer" target="_blank"/);
  assert.match(trustMarkup, /4\.9 out of 5/);
  assert.match(trustMarkup, /127 public reviews/);
  assert.match(locationMarkup, /Approved public office/);
  assert.match(locationMarkup, /Our Location/);
  assert.match(publicMarkup, /data-v5-location-mode="business_location"/);
  assert.match(locationMarkup, /123 Approved Avenue/);
  assert.match(locationMarkup, /href="tel:5550100200"/);
  assert.match(locationMarkup, /href="https:\/\/maps\.example\.com\/directions\?to=approved" rel="noopener noreferrer" target="_blank"/);
  assert.match(locationMarkup, /<iframe loading="lazy" referrerPolicy="strict-origin-when-cross-origin" src="https:\/\/www\.google\.com\/maps\/embed\?pb=approved-binding" title="Approved public office map"><\/iframe>/);
  assert.doesNotMatch(locationMarkup, / allow=|allowFullScreen|sandbox=/);
});

test("iframe-code input is reduced to one safe source and city-service-area output has no office shell", () => {
  const codeInput = `<iframe src="https://www.google.com/maps/embed/v1/place?key=approved-key&amp;q=Approved+Office" width="600" height="450" style="border:0" allowfullscreen="" loading="eager" referrerpolicy="unsafe-url" onload="ignored()"></iframe>`;
  const publicBusiness = renderCityServiceSurface("generated_page", {
    configuration: {
      locationMap: {
        ...validBusinessLocationConfiguration(),
        googleMapsEmbedInput: codeInput,
      },
    },
    presentation: "public",
  });
  const businessLocation = publicBusiness.slice(
    publicBusiness.indexOf('data-v5-optional-module="location-map"'),
    publicBusiness.indexOf('class="performanceLocalFinalCta"'),
  );
  assert.match(businessLocation, /src="https:\/\/www\.google\.com\/maps\/embed\/v1\/place\?key=approved-key&amp;q=Approved\+Office"/);
  assert.match(businessLocation, /loading="lazy"/);
  assert.match(businessLocation, /referrerPolicy="strict-origin-when-cross-origin"/);
  assert.doesNotMatch(businessLocation, /onload|style=|width="600"|height="450"|unsafe-url|allowFullScreen| allow=/);

  const publicCityArea = renderCityServiceSurface("generated_page", {
    configuration: { locationMap: validCityServiceAreaConfiguration() },
    presentation: "public",
  });
  const cityLocation = publicCityArea.slice(
    publicCityArea.indexOf('data-v5-optional-module="location-map"'),
    publicCityArea.indexOf('class="performanceLocalFinalCta"'),
  );
  assert.match(publicCityArea, /data-v5-location-mode="city_service_area"/);
  assert.match(publicCityArea, /data-v5-service-area-city="Orlando"/);
  assert.match(cityLocation, /Serving Orlando, Florida/);
  assert.doesNotMatch(cityLocation, /<address|Our Office|Our Orlando Location|Our Location|storefront|Google Business Profile|Get directions|performanceLocalV5LocationActions/);
});

test("V5 styles are additive, namespace-only, responsive, and never target the screenshot attribute", () => {
  const css = source("src/styles.css");
  const marker = css.indexOf("/* Performance Local V5:");
  assert.ok(marker > 0);
  const v5 = css.slice(marker);
  assert.doesNotMatch(v5, /\.performanceLocalV4/);
  assert.doesNotMatch(v5, /\[data-v5-site-root\]/);
  assert.doesNotMatch(v5, /min-height:\s*100vh|height:\s*100vh/);
  assert.match(v5, /\.performanceLocalV5DisclosureGrid details\[open\][\s\S]*?grid-column:\s*1 \/ -1/);
  assert.match(v5, /@media \(max-width:\s*760px\)[\s\S]*?\.performanceLocalV5DisclosureGrid[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(v5, /\.performanceLocalV5DestinationGrid[\s\S]*?grid-template-columns:\s*repeat\(3,/);
  assert.match(v5, /\.performanceLocalV5DestinationGrid\[data-v5-destination-count="1"\][\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(v5, /\.performanceLocalV5DestinationGrid\[data-v5-destination-count="2"\][\s\S]*?grid-template-columns:\s*repeat\(2,/);
  assert.match(v5, /\.performanceLocalV5HeroGrid\.performanceLocalV5HeroGridSingle[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(v5, /\.performanceLocalV5StructuredBody\[data-v5-structured-group-count="1"\] > :only-child[\s\S]*?grid-column:\s*1 \/ -1/);
  assert.match(v5, /@media \(max-width:\s*900px\)[\s\S]*?\.performanceLocalV5FinalGrid[\s\S]*?\.performanceLocalV5FormGrid[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(v5, /\.performanceLocalV5FormCompact[\s\S]*?padding:\s*clamp\(/);
  assert.match(v5, /\.performanceLocalV5TopConversionStack[\s\S]*?position:\s*fixed[\s\S]*?height:\s*var\(--plv5-city-stack-height\)/);
  assert.match(v5, /--plv5-city-stack-height:\s*calc\(/);
  assert.match(v5, /\.performanceLocalV5CityServicePreview \.performanceLocalHeader[\s\S]*?position:\s*absolute/);
  assert.match(v5, /\.performanceLocalV5CityServicePreview \.performanceLocalHeroMedia[\s\S]*?position:\s*absolute/);
  assert.match(v5, /\.performanceLocalV5CityServicePreview \.performanceLocalHeroMedia img[\s\S]*?object-fit:\s*cover !important/);
  assert.match(v5, /\.performanceLocalEstimateForm[\s\S]*?scroll-margin-block-start:\s*calc\([\s\S]*?var\(--plv5-viewport-top-offset\)[\s\S]*?var\(--plv5-city-stack-height\)[\s\S]*?16px[\s\S]*?\)/);
  assert.match(v5, /\.performanceLocalHeader:has\(\.performanceLocalDrawerBackdrop\)[\s\S]*?backdrop-filter:\s*none/);
  assert.match(v5, /@media \(max-width:\s*1100px\)[\s\S]*?object-position:\s*43% 50% !important/);
  assert.match(v5, /@media \(max-width:\s*760px\)[\s\S]*?object-position:\s*10% 50% !important/);
  assert.match(v5, /@media \(max-width:\s*760px\)[\s\S]*?\.performanceLocalHeroGrid[\s\S]*?grid-template-rows:[\s\S]*?\[visual-start\][\s\S]*?\[visual-end intro-start\]/);
  assert.match(v5, /@media \(max-width:\s*760px\)[\s\S]*?\.performanceLocalHeroContent[\s\S]*?display:\s*contents/);
  assert.match(v5, /@media \(max-width:\s*760px\)[\s\S]*?\.performanceLocalHeroSummary[\s\S]*?grid-row:\s*intro-start \/ intro-end/);
  assert.match(v5, /@media \(max-width:\s*760px\)[\s\S]*?\.performanceLocalHeroMedia[\s\S]*?grid-row:\s*visual-start \/ visual-end/);
  assert.match(v5, /@media \(max-width:\s*760px\)[\s\S]*?\.performanceLocalHeroMedia figcaption[\s\S]*?display:\s*none/);
  assert.doesNotMatch(v5, /@media \(max-width:\s*760px\)[\s\S]*?min-height:\s*1220px/);
  assert.match(v5, /\.performanceLocalV5ReviewTrustGrid[\s\S]*?grid-template-columns:\s*repeat\(3,/);
  assert.match(v5, /\.performanceLocalV5ReviewTrustGrid\[data-v5-source-count="1"\][\s\S]*?width:\s*min\(100%, 420px\)/);
  assert.match(v5, /\.performanceLocalV5OptionalLink[\s\S]*?min-height:\s*44px/);
  assert.match(v5, /\.performanceLocalV5ReviewTrustBadge img[\s\S]*?object-fit:\s*contain/);
  assert.match(v5, /\.performanceLocalV5ReviewTrustBadgeDemo span[\s\S]*?width:\s*min\(100%, 230px\)[\s\S]*?border-radius:\s*9px/);
  assert.doesNotMatch(v5, /\.performanceLocalV5ReviewTrustBadgeDemo span[\s\S]*?border-radius:\s*50%/);
  assert.match(v5, /\.performanceLocalV5MapFrame[\s\S]*?height:\s*clamp\(380px, 34vw, 480px\)/);
  assert.match(v5, /@media \(max-width:\s*760px\)[\s\S]*?\.performanceLocalV5MapFrame[\s\S]*?height:\s*clamp\(240px, 68vw, 300px\)/);
  assert.match(v5, /@media \(max-width:\s*760px\)[\s\S]*?\.performanceLocalV5ReviewTrustGrid[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\)/);
  const cityMarker = css.indexOf("/* Performance Local V5 City-Service: approved top conversion and over-photo hero preview. */");
  const conditionalMarker = css.indexOf("/* Performance Local V5 conditional Special and Estimate destination previews. */");
  const optionalModuleMarker = css.indexOf("/* Performance Local V5 page-scoped optional Review/Trust and Location/Map modules. */");
  assert.ok(cityMarker > 0 && conditionalMarker > cityMarker && optionalModuleMarker > conditionalMarker);
  assert.equal(
    createHash("sha256").update(css.slice(cityMarker, conditionalMarker)).digest("hex"),
    "7897a04f8b1358bf9d70e752c122562baf3408124a1e2bab8186fe50618a7948",
  );
  assert.equal(
    createHash("sha256").update(css.slice(conditionalMarker, optionalModuleMarker)).digest("hex"),
    "74f95cc1eea6c52822b3a6761291eed71c649252ca6272f52c7cebe474bdfc0e",
  );
});

test("V5 top conversion positioning is viewport-owned, flow-reserved, and offset-safe", () => {
  const css = source("src/styles.css");
  const marker = css.indexOf("/* Performance Local V5:");
  assert.ok(marker > 0);
  const v5 = css.slice(marker);

  const cityRoot = cssRule(v5, ".performanceLocalV5CityServicePreview");
  const conditionalRoot = cssRule(v5, ".performanceLocalV5ConditionalPage");
  for (const rootRule of [cityRoot, conditionalRoot]) {
    assert.match(rootRule, /--plv5-viewport-top-offset:\s*0px/);
    assert.match(rootRule, /padding-block-start:\s*var\(--plv5-city-stack-height\)/);
  }

  const stack = cssRule(v5, ".performanceLocalV5TopConversionStack");
  assert.match(stack, /position:\s*fixed/);
  assert.doesNotMatch(stack, /position:\s*sticky/);
  assert.match(stack, /top:\s*var\(--plv5-viewport-top-offset\)/);
  assert.match(stack, /right:\s*0/);
  assert.match(stack, /left:\s*0/);
  assert.match(stack, /height:\s*var\(--plv5-city-stack-height\)/);

  const disabledRoots = cssRule(v5, [
    '.performanceLocalV5CityServicePreview[data-v5-top-action-enabled="false"],',
    '.performanceLocalV5ConditionalPage[data-v5-top-action-enabled="false"]',
  ].join("\n"));
  assert.match(disabledRoots, /--plv5-city-action-height:\s*0px/);
  const disabledStack = cssRule(v5, '.performanceLocalV5TopConversionStack[data-v5-top-action-enabled="false"]');
  assert.match(disabledStack, /height:\s*calc\(var\(--plv5-city-phone-height\) \+ var\(--plv5-city-safe-top\)\)/);
  assert.match(disabledStack, /grid-template-rows:\s*calc\(var\(--plv5-city-phone-height\) \+ var\(--plv5-city-safe-top\)\)/);

  const adminSelector = [
    "body.admin-bar .performanceLocalV5CityServicePreview,",
    "body.admin-bar .performanceLocalV5ConditionalPage",
  ].join("\n");
  assert.match(cssRule(v5, adminSelector), /--plv5-viewport-top-offset:\s*32px/);
  const mobileAdminMarker = v5.indexOf("@media screen and (max-width: 782px)");
  assert.ok(mobileAdminMarker > 0);
  const mobileAdminSelector = adminSelector.split("\n").map((selector) => `  ${selector}`).join("\n");
  assert.match(cssRule(v5.slice(mobileAdminMarker), mobileAdminSelector), /--plv5-viewport-top-offset:\s*46px/);

  const narrowAdminMarker = v5.indexOf("@media screen and (max-width: 600px)");
  assert.ok(narrowAdminMarker > mobileAdminMarker);
  const narrowAdmin = v5.slice(narrowAdminMarker);
  const narrowAdminRoots = cssRule(narrowAdmin, mobileAdminSelector);
  assert.match(narrowAdminRoots, /--plv5-viewport-top-offset:\s*0px/);
  assert.match(narrowAdminRoots, /padding-block-start:\s*0/);
  const narrowAdminStackSelector = [
    "  body.admin-bar .performanceLocalV5CityServicePreview .performanceLocalV5TopConversionStack,",
    "  body.admin-bar .performanceLocalV5ConditionalPage .performanceLocalV5TopConversionStack",
  ].join("\n");
  const narrowAdminStack = cssRule(narrowAdmin, narrowAdminStackSelector);
  assert.match(narrowAdminStack, /position:\s*sticky/);
  assert.doesNotMatch(narrowAdminStack, /position:\s*fixed/);

  const cityAnchors = cssRule(v5, [
    ".performanceLocalV5CityServicePreview #main-content,",
    ".performanceLocalV5CityServicePreview .performanceLocalEstimateForm,",
    ".performanceLocalV5CityServicePreview .performanceLocalEstimateForm :where(input, textarea, button)",
  ].join("\n"));
  assert.match(cityAnchors, /scroll-margin-block-start:\s*calc\([\s\S]*?var\(--plv5-viewport-top-offset\)[\s\S]*?var\(--plv5-city-stack-height\)[\s\S]*?16px[\s\S]*?\)/);

  const conditionalHeader = cssRule(v5, ".performanceLocalV5ConditionalPage .performanceLocalV5Header");
  assert.match(conditionalHeader, /top:\s*calc\(var\(--plv5-viewport-top-offset\) \+ var\(--plv5-city-stack-height\)\)/);
  const releasedConditionalHeader = cssRule(v5, [
    '.performanceLocalV5ConditionalPage[data-v5-menu-open="true"] .performanceLocalV5Header,',
    '.performanceLocalV5ConditionalPage[data-v5-form-focus-risk="true"] .performanceLocalV5Header',
  ].join("\n"));
  assert.match(releasedConditionalHeader, /top:\s*var\(--plv5-viewport-top-offset\)/);
  const conditionalAnchors = cssRule(v5, [
    ".performanceLocalV5ConditionalPage #performance-local-v5-conditional-main,",
    ".performanceLocalV5ConditionalPage .performanceLocalV5Form,",
    ".performanceLocalV5ConditionalPage .performanceLocalV5Form :where(input, textarea, button)",
  ].join("\n"));
  assert.match(conditionalAnchors, /scroll-margin-block-start:\s*calc\([\s\S]*?var\(--plv5-viewport-top-offset\)[\s\S]*?var\(--plv5-city-stack-height\)[\s\S]*?94px[\s\S]*?\)/);

  const v5Header = cssRule(v5, ".performanceLocalV5Header");
  assert.match(v5Header, /position:\s*sticky/);
  assert.doesNotMatch(v5Header, /position:\s*fixed/);
  const cityHeader = cssRule(v5, ".performanceLocalV5CityServicePreview .performanceLocalHeader");
  assert.match(cityHeader, /position:\s*absolute/);
  assert.doesNotMatch(cityHeader, /position:\s*fixed/);
});

test("V5 top-interface labels use one real-weight system typography treatment", () => {
  const css = source("src/styles.css");
  const marker = css.indexOf("/* Performance Local V5 City-Service: approved top conversion and over-photo hero preview. */");
  assert.ok(marker > 0);
  const city = css.slice(marker);
  const selector = [
    ".performanceLocalV5StickyPhoneBar a,",
    ".performanceLocalV5StickyPhoneBar strong,",
    ".performanceLocalV5StickyActionBanner a,",
    ".performanceLocalV5CityServicePreview .performanceLocalDesktopNavigation :where(a, span, button),",
    ".performanceLocalV5CityServicePreview .performanceLocalDrawerList :where(a, span, button)",
  ].join("\n");
  const interfaceTypography = cssRule(city, selector);

  assert.match(interfaceTypography, /font-family:\s*var\(--atlas-font-body, system-ui, sans-serif\)/);
  assert.match(interfaceTypography, /font-style:\s*normal/);
  assert.match(interfaceTypography, /font-synthesis:\s*none/);
  assert.match(interfaceTypography, /font-weight:\s*700/);
  assert.match(interfaceTypography, /text-shadow:\s*none/);
  assert.match(interfaceTypography, /-webkit-text-stroke:\s*0/);
  assert.match(interfaceTypography, /filter:\s*none/);
  assert.match(interfaceTypography, /opacity:\s*1/);
  assert.doesNotMatch(interfaceTypography, /transform|font-size|line-height|letter-spacing/);

  const heroButton = cssRule(css, [
    ".performanceLocalButton,",
    ".performanceLocalStickyActions > a,",
    ".performanceLocalCampaign a,",
    ".performanceLocalEstimateForm button",
  ].join("\n"));
  assert.match(heroButton, /font-weight:\s*850/);
  assert.doesNotMatch(heroButton, /font-synthesis/);
});

test("footer collision boundary is fail-closed and deterministic", () => {
  assert.equal(performanceLocalV5FooterBoundaryReached({ footerTop: 844, viewportBottom: 844 }), true);
  assert.equal(performanceLocalV5FooterBoundaryReached({ footerTop: 845, viewportBottom: 844 }), false);
  assert.equal(performanceLocalV5FooterBoundaryReached({ footerTop: Number.NaN, viewportBottom: 844 }), true);
  assert.equal(performanceLocalV5FooterBoundaryReached({ footerTop: 1200, viewportBottom: 0 }), true);
});

function renderLayout(
  pageType: PerformanceLocalV5LayoutBodyProps["pageType"],
  reviewMode: PerformanceLocalV5LayoutBodyProps["reviewMode"],
): string {
  return staticMarkup(layoutProps(pageType, reviewMode));
}

function staticMarkup(props: PerformanceLocalV5LayoutBodyProps): string {
  return renderToStaticMarkup(
    <StaticRouter location="/theme-lab/performance-local/v5/generated-pages/1001">
      <PerformanceLocalV5LayoutBody {...props} />
    </StaticRouter>,
  );
}

function layoutProps(
  pageType: PerformanceLocalV5LayoutBodyProps["pageType"],
  reviewMode: PerformanceLocalV5LayoutBodyProps["reviewMode"],
): PerformanceLocalV5LayoutBodyProps {
  const fixtures = pageFixture(pageType);
  return {
    callLabel: "Call",
    componentByInstanceKey: new Map(fixtures.components.map((component) => [component.instance_key, component])),
    countyCityPresentation: fixtures.county,
    destinationForGeneratedPageId: (id) => `/theme-lab/performance-local/v5/generated-pages/${id}`,
    estimateDestination: "#performance-local-estimate-form-91",
    estimateForm: estimateForm(),
    governedContact,
    homeServicePresentation: fixtures.home,
    layoutKey: pageType === "county" ? "performance-local-v5-service-county" : `performance-local-v5-${pageType}`,
    onFormFocusRiskChange: () => undefined,
    pageType,
    regions: fixtures.regions,
    reviewMode,
  };
}

function pageFixture(pageType: PerformanceLocalV5LayoutBodyProps["pageType"]): {
  components: PageComponentInstance[];
  county: PerformanceLocalV5CountyCityPresentation;
  home: PerformanceLocalV5HomeServicePresentation;
  regions: PerformanceLocalV5RegionPlan[];
} {
  const hero = component("hero", "hero", { title: `Exact ${pageType} H1`, intro: `Exact ${pageType} intro.` });
  const media = component("media_placement:hero", "media_placement", { requirement_state: "required" }, {
    target_component_instance_key: "hero",
    target_component_key: "hero",
    target_region: "main",
  });
  const trust = component("trust_license", "trust_license", { license_number: "LIC-123", certified_operator: "Exact operator" });
  const final = component("final_cta", "final_cta", { heading: "Exact final heading", body: "Exact final body." });
  const components: PageComponentInstance[] = [hero, media, trust, final];
  const regions: PerformanceLocalV5RegionPlan[] = [
    region("hero", [hero, media]),
    region("trust", [trust]),
    region("final_conversion", [final]),
  ];
  let home = notApplicableHome();
  let county = notApplicableCounty();

  if (pageType === "home") {
    const primary = section("primary_services", "Exact service discovery", "- Exact featured service: Exact featured description.");
    const value = section("trust", "Exact value heading", "Exact value body.");
    const area = section("service_area", "Exact service area", "Exact service area body.");
    const links = destinations("related_page_links", [
      ["Exact featured service", "Exact featured description.", 1201],
      ["Exact remaining destination", "Exact remaining purpose.", 1202],
    ]);
    components.push(primary, value, area, links);
    regions.push(region("service_discovery", [primary]), region("company_value", [value]), region("service_area_discovery", [area]), region("supporting_discovery", [links]));
    home = {
      status: "ready",
      primaryServicesSourceInstanceKey: primary.instance_key,
      relatedLinksSourceInstanceKey: links.instance_key,
      mode: "featured",
      services: [{
        sourceItemIndex: 0,
        exactSourceItem: "Exact featured service: Exact featured description.",
        title: "Exact featured service",
        description: "Exact featured description.",
        matchedLinkIndex: 0,
        destination: destination(0, "featured_service", "Exact featured service", 1201),
      }],
      remainingLinkIndices: [1],
      remainingDestinations: [destination(1, "related_destination", "Exact remaining destination", 1202, "Exact remaining purpose.")],
    };
  } else if (pageType === "service") {
    const overview = summary("service_overview", "Exact service overview", "Exact overview body.");
    const guidance = section("approved_guidance", "Exact customer guidance", "### Exact detail one\nExact answer one.\n\n### Exact detail two\nExact answer two.");
    const area = section("service_area", "Exact service area", "Exact service area body.");
    const related = destinations("destination_cards", [["Exact service destination", "Exact destination purpose.", 1201]]);
    const faq = faqComponent("Exact service FAQ?", "Exact service FAQ answer.");
    components.push(overview, guidance, area, related, faq);
    regions.push(region("service_overview", [overview]), region("approved_guidance", [guidance]), region("service_area_discovery", [area]), region("related_discovery", [related]), region("faq", [faq]));
  } else if (pageType === "county") {
    const overview = summary("service_county_intro", "Exact county overview", "Exact county overview body.");
    const cities = section("cities_served", "Exact cities served", "Exact City One, Exact City Two");
    const process = section("how_service_works", "Exact process", "Exact process body.");
    const expectations = section("customer_expectations", "Exact expectations", "### Exact detail one\nExact answer one.\n\n### Exact detail two\nExact answer two.");
    const preparation = section("preparation_guidance", "Exact preparation", "Exact preparation body.");
    const credentials = section("trust_and_license", "Exact county credentials", "Exact county credential body.");
    const relatedCities = section("related_city_services", "Exact city service routes", "Exact City One, Exact City Two");
    const cards = destinations("destination_cards", [
      ["Exact City One", "Exact city purpose one.", 1301],
      ["Exact City Two", "Exact city purpose two.", 1302],
      ["Exact county remainder", "Exact county remainder purpose.", 1303],
    ]);
    const faq = faqComponent("Exact County question?", "Exact County answer.");
    components.push(overview, cities, process, expectations, preparation, credentials, relatedCities, cards, faq);
    regions.push(region("county_overview", [overview]), region("city_discovery", [cities]), region("service_process", [process]), region("customer_expectations", [expectations]), region("preparation_guidance", [preparation]), region("county_credentials", [credentials]), region("related_city_discovery", [relatedCities, cards]), region("faq", [faq]));
    county = {
      status: "ready",
      citiesServedSourceInstanceKey: cities.instance_key,
      relatedCityServicesSourceInstanceKey: relatedCities.instance_key,
      destinationCardsSourceInstanceKey: cards.instance_key,
      validatedCityPrefixCount: 2,
      cityEntries: [
        { cityIndex: 0, cityName: "Exact City One", originalLinkIndex: 0, destination: destination(0, "county_city", "Exact City One", 1301, "Exact city purpose one.") },
        { cityIndex: 1, cityName: "Exact City Two", originalLinkIndex: 1, destination: destination(1, "county_city", "Exact City Two", 1302, "Exact city purpose two.") },
      ],
      remainingLinkIndices: [2],
      remainingDestinations: [destination(2, "related_destination", "Exact county remainder", 1303, "Exact county remainder purpose.")],
    };
  } else if (pageType === "about") {
    const story = section("company_story", "Exact company story", "Exact company story body.");
    const experience = section("experience", "Exact experience", "Exact experience body.");
    const purpose = section("mission", "Exact purpose", "Exact purpose body.");
    const related = destinations("related_page_links", [["Exact About destination", "Exact About purpose.", 1201]]);
    components.push(story, experience, purpose, related);
    regions.push(region("company_story", [story]), region("experience", [experience]), region("service_philosophy", [purpose]), region("service_discovery", [related]));
  } else if (pageType === "contact") {
    const pathways = component("contact_pathways", "contact_pathways", { email: "exact@example.test" });
    const ways = section("ways_to_contact", "Exact ways to contact", "Exact ways to contact body.");
    const hours = section("hours", "Hours", "Exact Hours source text.");
    const area = section("service_area", "Service Area", "Exact Service Area source text.");
    const related = destinations("related_page_links", [["Exact Contact destination", "Exact Contact purpose.", 1201]]);
    components.push(pathways, ways, hours, area, related);
    regions.push(region("immediate_contact", [pathways]), region("contact_information", [trust, ways, hours, area]), region("related_discovery", [related]));
  } else {
    const faq = faqComponent("Exact FAQ question?", "Exact FAQ answer.");
    const related = destinations("related_page_links", [["Exact FAQ destination", "Exact FAQ purpose.", 1201]]);
    const contact = section("contact", "Exact contact support", "Exact contact support body.");
    components.push(faq, related, contact);
    regions.push(region("faq", [faq]), region("related_discovery", [related]), region("contact_support", [contact]));
  }
  return { components, county, home, regions };
}

function region(regionKey: string, components: readonly PageComponentInstance[]): PerformanceLocalV5RegionPlan {
  return {
    regionKey,
    requirement: "required",
    sourceInstanceKeys: components.map((component) => component.instance_key),
    presentationGroups: [],
    missing: false,
  };
}

function component(
  instanceKey: string,
  componentKey: string,
  resolvedData: Record<string, unknown>,
  inputBindings: Record<string, unknown> = {},
): PageComponentInstance {
  return {
    instance_key: instanceKey,
    component_key: componentKey,
    contract_version: 1,
    region: "main",
    position: 0,
    variant: "default",
    input_bindings: inputBindings,
    resolved_data: resolvedData,
  };
}

function section(key: string, heading: string, body: string): PageComponentInstance {
  return component(`content_section:${key}`, "content_section", { heading, body }, { section_key: key });
}

function summary(key: string, heading: string, body: string): PageComponentInstance {
  return component(`service_summary:${key}`, "service_summary", { heading, body }, { section_key: key });
}

function faqComponent(question: string, answer: string): PageComponentInstance {
  return component("faq", "faq", { items: [{ question, answer }] });
}

function destinations(
  componentKey: "related_page_links" | "destination_cards",
  items: readonly (readonly [string, string, number])[],
): PageComponentInstance {
  return component(componentKey, componentKey, {
    links: items.map(([label, purpose, target], index) => ({
      label,
      purpose,
      slug: `exact-${target}`,
      target_generated_page_id: target,
      target_planned_page_id: 2200 + index,
    })),
  });
}

function destination(
  index: number,
  presentationSlot: PerformanceLocalV5DestinationConsumptionRecord["presentationSlot"],
  label: string,
  targetGeneratedPageId: number,
  purpose = "Exact source purpose.",
): PerformanceLocalV5DestinationConsumptionRecord {
  return {
    sourceInstanceKey: "related_page_links",
    originalLinkIndex: index,
    presentationSlot,
    label,
    purpose,
    slug: `exact-${targetGeneratedPageId}`,
    targetPlannedPageId: 2200 + index,
    targetGeneratedPageId,
  };
}

function notApplicableHome(): PerformanceLocalV5HomeServicePresentation {
  return {
    status: "not_applicable",
    primaryServicesSourceInstanceKey: null,
    relatedLinksSourceInstanceKey: null,
    mode: null,
    services: [],
    remainingLinkIndices: [],
    remainingDestinations: [],
  };
}

function notApplicableCounty(): PerformanceLocalV5CountyCityPresentation {
  return {
    status: "not_applicable",
    citiesServedSourceInstanceKey: null,
    relatedCityServicesSourceInstanceKey: null,
    destinationCardsSourceInstanceKey: null,
    validatedCityPrefixCount: 0,
    cityEntries: [],
    remainingLinkIndices: [],
    remainingDestinations: [],
  };
}

const governedContact: PerformanceLocalGovernedContact = {
  callDestination: "tel:5550100200",
  phoneDisplay: "(555) 010-0200",
  websiteId: 1,
};

const cityServiceReadiness: PerformanceLocalV5ReadinessProjection = Object.freeze({
  mediaReady: false,
  qaReady: true,
  formReady: false,
  activationReady: false,
  exportReady: false,
  publicationReady: false,
});

function cityServicePage(): GeneratedPage {
  return {
    id: 41,
    business_id: 1,
    website_id: 1,
    service_id: 5,
    page_type: "city_service",
    page_title: "Exact Page 41 control",
    page_slug: "exact-page-41-control",
    generation_status: "generated",
    qa_status: "ready",
    status: "draft",
    created_at: "2026-08-17T12:00:00Z",
    updated_at: "2026-08-17T12:00:00Z",
  };
}

function cityServiceComposition(): PageComposition {
  const header = component("website_header", "website_header", {
    display_name: "Flo-Zone",
    tagline: "Drywood Termite Solution",
  });
  const primaryNavigation = component("primary_navigation", "primary_navigation", {
    label: "Primary Navigation",
    items: [{
      label: "Home",
      navigation_item_id: 1,
      parent_navigation_item_id: null,
      position: 0,
      slug: "home",
      status: "active",
      target_generated_page_id: 69,
      target_planned_page_id: 79,
    }],
  });
  const utilityNavigation = component("utility_navigation", "utility_navigation", {
    label: "Utility Navigation",
    items: [],
  });
  const hero = component("hero", "hero", {
    page_type: "city_service",
    title: "Drywood Termite Tenting in Orlando, Florida",
    intro: "Exact governed Page 41 introductory paragraph for the focused top presentation.",
  });
  const heroMedia = component("media_placement:hero", "media_placement", {
    asset_url: "/media/optimized/2326ac885a03490482e47dcc26d0eca3-optimized.webp",
    alt_text: "Flo-Zone technician outside a branded tented Orlando property",
    caption: "Exact governed Page 41 hero caption.",
    display_preset: "hero_desktop",
    focal_x: 0.5,
    focal_y: 0.5,
    image_role: "hero",
    image_title: "Exact governed Page 41 hero",
  }, {
    target_component_instance_key: hero.instance_key,
    target_component_key: hero.component_key,
    target_region: "main",
  });
  const finalCta = component("final_cta", "final_cta", {
    heading: "Exact governed final conversion",
    body: "Exact governed final conversion body.",
  });
  const trust = component("trust_license", "trust_license", {
    license_number: "JB360566",
    certified_operator: "Jordan Ward",
  });
  const footer = component("website_footer", "website_footer", {
    display_name: "Flo-Zone",
    license_number: "JB360566",
  });
  const footerNavigation = component("footer_navigation", "footer_navigation", {
    label: "Footer Navigation",
    items: [],
  });
  const components = [
    header,
    primaryNavigation,
    utilityNavigation,
    hero,
    heroMedia,
    trust,
    finalCta,
    footerNavigation,
    footer,
  ];
  return {
    id: 801,
    website_id: 1,
    site_plan_id: 901,
    planned_page_id: 1001,
    generated_page_id: 41,
    composition_version: 8,
    generated_components: components,
    operator_decisions: [],
    effective_components: components,
    source_snapshot: { page_type: "city_service" },
    source_hash: "a".repeat(64),
    resolved_theme: selectedTheme(1),
    status: "current",
    validation_errors: [],
    generated_at: "2026-08-17T12:00:00Z",
  };
}

function cityServiceAudit(): PerformanceLocalV5LayoutAudit {
  return {
    resolutionStatus: "resolved",
    status: "ready",
    layoutReady: true,
    layoutKey: "performance-local-v5-city-service",
    pageType: "city_service",
    blockers: [],
    consumption: [
      "website_header",
      "primary_navigation",
      "utility_navigation",
      "hero",
      "media_placement:hero",
      "trust_license",
      "final_cta",
      "footer_navigation",
      "website_footer",
    ].map((instanceKey) => ({ instanceKey })),
    regions: [
      {
        regionKey: "site_header",
        sourceInstanceKeys: ["website_header", "primary_navigation", "utility_navigation"],
      },
      {
        regionKey: "site_footer",
        sourceInstanceKeys: ["footer_navigation", "website_footer"],
      },
    ],
  } as PerformanceLocalV5LayoutAudit;
}

function cityServiceConfiguration(): PerformanceLocalDeliveryConfiguration {
  const form = {
    ...estimateForm(),
    ctaLabel: "Request an Estimate",
    submitLabel: "Request an Estimate",
  };
  const fields = form.fields as readonly PerformanceLocalEstimateField[];
  return {
    campaign: {
      approvalIdentity: "approved-campaign",
      campaignLabel: "Request an Estimate",
      ctaDestination: `#${performanceLocalFormDomId(form.componentConfigurationId)}`,
      ctaLabel: "Request an Estimate",
      destinationComponentConfigurationId: form.componentConfigurationId,
      enabled: true,
      intent: "evergreen_conversion",
      websiteId: 1,
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
    estimateForm: { ...form, fields },
    formSubmission: {
      endpoint: null,
      readiness: {
        status: "blocked",
        can_submit: false,
        component_configuration_id: form.componentConfigurationId,
        blockers: [],
      },
    },
    governedContact,
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
      componentConfigurationId: 92,
      desktopHeaderActionsEnabled: true,
      destinationComponentConfigurationId: form.componentConfigurationId,
      enabled: true,
      estimateLabel: "Request an Estimate",
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

function cityServiceFormIdentity(
  configuration: PerformanceLocalDeliveryConfiguration,
): PerformanceLocalV5FormIdentity {
  return {
    componentConfigurationId: configuration.estimateForm.componentConfigurationId,
    componentInstanceKey: configuration.estimateForm.componentInstanceKey,
    destination: `#${performanceLocalFormDomId(configuration.estimateForm.componentConfigurationId)}`,
  };
}

function cityServiceActionConfiguration(
  configuration: PerformanceLocalDeliveryConfiguration,
  surface: PerformanceLocalV5PreviewSurface,
): PerformanceLocalV5ActionConfiguration {
  const baseRoute = "/theme-lab/performance-local/v5/generated-pages/41";
  const estimateRoute = `${baseRoute}/request-an-estimate`;
  const specialRoute = `${baseRoute}/special`;
  const specialEnabled = surface === "special" || surface === "estimate";
  return {
    authorizedServicePromotionDestinations: [],
    estimate: {
      enabled: true,
      formIdentity: cityServiceFormIdentity(configuration),
      heading: "Request an Estimate",
      introduction: "Request an estimate for the service in this area.",
      phoneAlternativeEnabled: true,
      route: estimateRoute,
    },
    special: specialEnabled ? {
      callActionEnabled: true,
      description: "No public Special is configured. This local Theme Lab preview demonstrates the optional Special-page layout only.",
      enabled: true,
      estimateActionEnabled: true,
      expiresAt: null,
      headline: "DEMO SPECIAL — NOT SITE CONTENT",
      route: specialRoute,
    } : { enabled: false },
    sticky: surface === "sticky_disabled" ? { mode: "disabled" } : specialEnabled ? {
      accessibilityLabel: "DEMO SPECIAL — NOT SITE CONTENT",
      destination: specialRoute,
      mode: "special",
      publicLabel: "DEMO SPECIAL — NOT SITE CONTENT",
    } : {
      accessibilityLabel: "Request an Estimate",
      destination: estimateRoute,
      mode: "estimate",
      publicLabel: "Request an Estimate",
    },
  };
}

function renderCityServiceSurface(
  surface: PerformanceLocalV5PreviewSurface,
  optionalModules: Readonly<{
    configuration: PerformanceLocalV5OptionalModulePageConfiguration;
    presentation: PerformanceLocalV5OptionalModulePresentation;
  }> | null = null,
): string {
  const configuration = cityServiceConfiguration();
  const suffix = surface === "special"
    ? "/special"
    : surface === "estimate"
      ? "/request-an-estimate"
      : surface === "sticky_disabled"
        ? "/sticky-disabled"
        : surface === "review_trust"
          ? "/review-trust"
          : surface === "location_map"
            ? "/location-map"
            : surface === "review_trust_location_map"
              ? "/review-trust-location-map"
        : "";
  return renderToStaticMarkup(
    <StaticRouter location={`/theme-lab/performance-local/v5/generated-pages/41${suffix}`}>
      <PerformanceLocalV5Renderer
        actionConfiguration={cityServiceActionConfiguration(configuration, surface)}
        audit={cityServiceAudit()}
        campaignBannerEnabled={false}
        composition={cityServiceComposition()}
        optionalModuleApprovedLocalImages={APPROVED_OPTIONAL_MODULE_IMAGES}
        optionalModuleConfiguration={optionalModules?.configuration}
        optionalModuleGovernedTargetCity="Orlando"
        optionalModuleGovernedTargetState="Florida"
        optionalModulePresentation={optionalModules?.presentation}
        page={cityServicePage()}
        previewedAt={new Date("2026-08-23T18:00:00Z")}
        readiness={cityServiceReadiness}
        reviewMode="truthful"
        previewSurface={surface}
        v3Configuration={configuration}
      />
    </StaticRouter>,
  );
}

const APPROVED_OPTIONAL_MODULE_IMAGES = Object.freeze({
  "approved-source-1": "/assets/review-source-one.svg",
  "approved-source-2": "/assets/review-source-two.svg",
  "approved-source-3": "/assets/review-source-three.svg",
});

function validReviewTrustConfiguration(demo = false) {
  const publicNames = demo
    ? [
        "DEMO TRUST SOURCE — NOT SITE CONTENT",
        "DEMO TRUST SOURCE — NOT SITE CONTENT",
        "DEMO TRUST SOURCE — NOT SITE CONTENT",
      ]
    : ["Approved source one", "Approved source two", "Approved source three"];
  return {
    enabled: true,
    heading: "Review and trust sources",
    sources: [
      {
        badgeImageReference: "approved-source-1",
        description: demo ? "Structural preview for one approved source." : "Exact approved source description one.",
        enabled: true,
        imageAltText: demo ? "Demo trust source structure one" : "Approved source one",
        ...(demo ? {} : {
          profileDestination: "https://reviews.example.com/source-one",
          verifiedRatingText: "4.9 out of 5",
          verifiedReviewCountText: "127 public reviews",
        }),
        publicName: publicNames[0],
        sourceKey: "approved-source-one",
      },
      {
        badgeImageReference: "approved-source-2",
        description: demo ? "Structural preview for a second approved source." : "Exact approved source description two.",
        enabled: true,
        imageAltText: demo ? "Demo trust source structure two" : "Approved source two",
        publicName: publicNames[1],
        sourceKey: "approved-source-two",
      },
      {
        badgeImageReference: "approved-source-3",
        description: demo ? "Structural preview for a third approved source." : "Exact approved source description three.",
        enabled: true,
        imageAltText: demo ? "Demo trust source structure three" : "Approved source three",
        publicName: publicNames[2],
        sourceKey: "approved-source-three",
      },
    ],
  };
}

function validBusinessLocationConfiguration() {
  return {
    approvedAddressLines: ["123 Approved Avenue", "Orlando, FL 32801"],
    approvedLocationName: "Approved public office",
    description: "Exact approved public location description.",
    directionsDestination: "https://maps.example.com/directions?to=approved",
    googleMapsEmbedInput: "https://www.google.com/maps/embed?pb=approved-binding",
    governedPhoneDisplay: "(555) 010-0200",
    mapTitle: "Approved public office map",
    mode: "business_location" as const,
  };
}

function validCityServiceAreaConfiguration(demo = false) {
  return {
    description: demo
      ? "Synthetic preview of a manually approved city service-area map."
      : "Exact manually approved service-area description.",
    googleMapsEmbedInput: demo
      ? "https://www.google.com/maps/embed?pb=theme-lab-demo"
      : "https://www.google.com/maps/embed?pb=approved-orlando-service-area",
    mapTitle: demo ? "Orlando service-area demo map — not site content" : "Orlando service-area map",
    mode: "city_service_area" as const,
    sectionHeading: "Serving Orlando, Florida",
    targetCity: "Orlando",
    targetState: "Florida",
  };
}

function optionalModuleConfiguration(
  mode: "both" | "location" | "review",
  demo = false,
): PerformanceLocalV5OptionalModulePageConfiguration {
  return {
    ...(mode === "both" || mode === "location" ? {
      locationMap: demo ? validCityServiceAreaConfiguration(true) : validBusinessLocationConfiguration(),
    } : {}),
    ...(mode === "both" || mode === "review" ? { reviewTrust: validReviewTrustConfiguration(demo) } : {}),
  };
}

function resolveOptionalModules(
  raw: unknown,
  overrides: Partial<{
    governedTargetCity: string | null;
    governedTargetState: string | null;
    pageType: unknown;
    presentation: PerformanceLocalV5OptionalModulePresentation;
  }> = {},
) {
  return resolvePerformanceLocalV5OptionalModules(raw, {
    approvedLocalImages: APPROVED_OPTIONAL_MODULE_IMAGES,
    governedPhoneDisplay: governedContact.phoneDisplay,
    governedTargetCity: Object.prototype.hasOwnProperty.call(overrides, "governedTargetCity")
      ? overrides.governedTargetCity ?? null
      : "Orlando",
    governedTargetState: Object.prototype.hasOwnProperty.call(overrides, "governedTargetState")
      ? overrides.governedTargetState ?? null
      : "Florida",
    pageType: Object.prototype.hasOwnProperty.call(overrides, "pageType") ? overrides.pageType : "city_service",
    presentation: overrides.presentation ?? "public",
  });
}

function estimateForm(): PerformanceLocalEstimateFormConfiguration {
  const specs = [
    ["name", "Name", "input", "text", true, "half", "contact_name"],
    ["phone", "Phone", "input", "tel", true, "half", "phone"],
    ["postal-code", "ZIP code", "input", "text", true, "half", "postal_code"],
    ["requested-service", "Requested service", "input", "text", true, "half", "requested_service"],
    ["message", "Optional message", "textarea", undefined, false, "full", "message"],
  ] as const;
  return {
    componentConfigurationId: 91,
    componentInstanceKey: "performance-local:compact-estimate-form-v3",
    ctaLabel: "Request Estimate",
    fields: specs.map(([key, label, control, type, required, responsive, mapping], index) => ({
      accessibilityLabel: label,
      autoComplete: "off" as const,
      control,
      inputMode: key === "phone" ? "tel" as const : key === "postal-code" ? "numeric" as const : "text" as const,
      key,
      label,
      maxLength: 500,
      order: index + 1,
      providerMapping: mapping,
      required,
      responsive: { desktop: responsive, tablet: responsive, mobile: "full" as const },
      rows: control === "textarea" ? 3 : undefined,
      type,
      validation: { maximumLength: 500, minimumLength: required ? 1 : 0, rule: "nonempty_text" as const },
    })),
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
  } as PerformanceLocalEstimateFormConfiguration;
}

function source(path: string): string {
  return readFileSync(join(root, path), "utf8");
}

function cssRule(css: string, selector: string): string {
  const normalizedCss = css.replace(/\r\n/g, "\n");
  const marker = `${selector.replace(/\r\n/g, "\n")} {`;
  const start = normalizedCss.indexOf(marker);
  assert.ok(start >= 0, `Missing CSS rule: ${selector}`);
  const bodyStart = start + marker.length;
  const end = normalizedCss.indexOf("}", bodyStart);
  assert.ok(end > bodyStart, `Unterminated CSS rule: ${selector}`);
  return normalizedCss.slice(bodyStart, end);
}

function count(value: string, needle: string): number {
  return value.split(needle).length - 1;
}
