import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

import { renderToStaticMarkup } from "react-dom/server";

import { PerformanceLocalV4ReviewPage } from "../src/pages/PerformanceLocalV4ReviewPage";
import { isLoopbackThemeLabHost } from "../src/pages/UniversalFormModesReviewPage";

const root = process.cwd();
const source = (path: string) => readFileSync(resolve(root, path), "utf8");

test("the V4 operator review fails closed outside exact loopback hosts", () => {
  for (const hostname of ["localhost", "127.0.0.1", "::1", "[::1]"]) {
    assert.equal(isLoopbackThemeLabHost(hostname), true, hostname);
  }
  for (const hostname of ["atlas.example", "localhost.example", "0.0.0.0", "127.0.0.2", ""]) {
    assert.equal(isLoopbackThemeLabHost(hostname), false, hostname);
  }

  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { location: { hostname: "atlas.example" } },
  });
  try {
    const markup = renderToStaticMarkup(<PerformanceLocalV4ReviewPage />);
    assert.match(markup, /role="alert"/);
    assert.match(markup, /<h1>Local Theme Lab only<\/h1>/);
    assert.doesNotMatch(markup, /data-v4-preview-canvas|performanceLocalV4Site/);
  } finally {
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else delete (globalThis as { window?: unknown }).window;
  }
});

test("App exposes one lazy operator route and no public V4 delivery route", () => {
  const app = source("src/App.tsx");
  assert.match(app, /lazy\(\s*\(\) => import\("\.\/pages\/PerformanceLocalV4ReviewPage"\)/);
  assert.match(
    app,
    /path="\/theme-lab\/performance-local\/v4\/generated-pages\/:id"\s*element=\{<ThemeLabRoute><PerformanceLocalV4ReviewPage \/><\/ThemeLabRoute>\}/,
  );
  assert.equal(count(app, "/theme-lab/performance-local/v4/generated-pages/:id"), 1);
  assert.doesNotMatch(app, /path="\/(?:delivery|public|export)[^"]*performance-local\/v4/i);
});

test("review joins exact read-only V3 evidence, applies governed tokens, and keeps one preview H1", () => {
  const review = source("src/pages/PerformanceLocalV4ReviewPage.tsx");
  assert.match(review, /isLoopbackThemeLabHost\(hostname\)/);
  assert.match(review, /family_key=performance-local&family_version=3&page_id=/);
  assert.match(review, /performanceLocalDeliveryValidationError\(/);
  assert.match(review, /performanceLocalDeliveryConfiguration\(delivery\)/);
  assert.match(review, /exactPlannedPage\(sitePlan, delivery\)/);
  assert.match(review, /auditPerformanceLocalV4Composition\(\{/);
  assert.match(review, /sameCanonicalJson\(requestedPage, delivery\.page\)/);
  assert.match(review, /themePresentation\(\s*delivery\.composition\.resolved_theme/);
  assert.match(review, /style=\{governedPresentation\.style\}/);
  assert.match(review, /\{\.\.\.governedPresentation\.attributes\}/);
  assert.match(
    review,
    /<strong className="performanceLocalV4ReviewTitle">\{PERFORMANCE_LOCAL_V4_PREVIEW_LABEL\}<\/strong>/,
  );
  assert.doesNotMatch(review, /<h1[^>]*>\{PERFORMANCE_LOCAL_V4_PREVIEW_LABEL\}/);
  assert.match(review, /campaign=\{campaignBannerEnabled \? configuration\.campaign : null\}/);
  assert.match(review, /campaignBanner: campaignBannerEnabled/);
  assert.match(review, /activationReady: false/);
  assert.match(review, /exportReady: false/);
  assert.match(review, /publicationReady: false/);
  assert.match(review, /Public-export eligible[^\n]+false/);
});

test("review source has no persistence, mutation, external fetch, activation, export, or public-delivery side effect", () => {
  const review = source("src/pages/PerformanceLocalV4ReviewPage.tsx");
  assert.doesNotMatch(review, /localStorage|sessionStorage|indexedDB|sendBeacon|XMLHttpRequest|FormData/);
  assert.doesNotMatch(review, /\bfetch\s*\(|method\s*:\s*["'](?:POST|PUT|PATCH|DELETE)["']/i);
  assert.doesNotMatch(review, /https?:\/\//i);
  assert.doesNotMatch(review, /\b(?:activateTheme|createTheme|publishTheme|deployTheme|exportPackage)\s*\(/i);
  assert.equal(count(review, "apiRequest<"), 4);
});

test("V4 modules remain absent from public delivery, export, legacy renderer, and Theme Lab sources", () => {
  for (const path of [
    "src/pages/PerformanceLocalDeliveryPage.tsx",
    "src/pages/ExportPackagePage.tsx",
    "src/components/performanceLocalDelivery.ts",
    "src/components/PerformanceLocalRenderer.tsx",
    "src/pages/ThemeLabPage.tsx",
  ]) {
    const contents = source(path);
    assert.doesNotMatch(
      contents,
      /PerformanceLocalV4|performanceLocalV4|performanceLocalThemeV4|performance-local@4/,
      path,
    );
  }
});

test("V4 CSS stays scoped, governed, responsive, accessible, and free of page-wide clipping", () => {
  const styles = source("src/styles.css");
  const start = styles.indexOf("/* Performance Local V4 is an operator-only");
  const end = styles.indexOf("/* Local-only universal form delivery evidence surface.", start);
  assert.ok(start >= 0 && end > start);
  const v4 = styles.slice(start, end);
  for (const line of v4.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed.startsWith(".") && trimmed.endsWith("{")) {
      assert.match(trimmed, /^\.performanceLocalV4/, trimmed);
    }
  }
  assert.doesNotMatch(v4, /\.performanceLocalSite\b|\.themeLab\b/);
  assert.doesNotMatch(v4, /overflow-x\s*:\s*(?:hidden|clip)/);
  assert.match(v4, /--plv4-forest:\s*var\(--atlas-color-primary,/);
  assert.match(v4, /--plv4-forest-foreground:\s*var\(--atlas-color-primary-foreground,/);
  assert.match(v4, /--plv4-secondary-foreground:\s*var\(--atlas-color-secondary-foreground,/);
  assert.match(v4, /--plv4-lime:\s*var\(--atlas-color-accent,/);
  assert.match(v4, /--plv4-lime-foreground:\s*var\(--atlas-color-accent-foreground,/);
  assert.match(
    v4,
    /--plv4-muted:\s*color-mix\(in srgb, var\(--plv4-ink\) 74%, var\(--plv4-surface\)\)/,
  );
  assert.match(
    v4,
    /--plv4-line:\s*color-mix\(in srgb, var\(--plv4-ink\) 22%, var\(--plv4-surface\)\)/,
  );
  assert.match(v4, /--plv4-focus:\s*var\(--atlas-color-focus,/);
  assert.doesNotMatch(v4, /var\(--atlas-color-neutral-foreground/);
  assert.match(
    v4,
    /\.performanceLocalV4Campaign[\s\S]+?background:\s*var\(--plv4-lime\);[\s\S]+?color:\s*var\(--plv4-lime-foreground\);/,
  );
  assert.match(
    v4,
    /\.performanceLocalV4Region-hero[\s\S]+?background:\s*var\(--plv4-forest\);[\s\S]+?color:\s*var\(--plv4-forest-foreground\);/,
  );
  assert.match(
    v4,
    /\.performanceLocalV4Region-final_conversion[\s\S]+?background:\s*var\(--plv4-forest-deep\);[\s\S]+?color:\s*var\(--plv4-secondary-foreground\);/,
  );
  assert.match(v4, /font-family:\s*var\(--atlas-font-body,/);
  assert.match(v4, /width:\s*min\(var\(--atlas-content-width-wide,/);
  assert.match(v4, /object-fit:\s*contain/);
  assert.match(v4, /min-height:\s*44px/);
  assert.match(v4, /min-height:\s*48px/);
  assert.match(v4, /@media \(max-width:\s*1100px\)/);
  assert.match(v4, /@media \(max-width:\s*760px\)/);
  assert.match(v4, /@media \(max-width:\s*440px\)/);
  assert.match(v4, /@media \(prefers-reduced-motion:\s*reduce\)/);
  assert.match(v4, /performanceLocalV4StructuredBody/);
  assert.match(v4, /:has\(> :nth-child\(2\)\)/);
  assert.match(
    v4,
    /\.performanceLocalV4CardGrid h2 a \{[\s\S]+?min-width:\s*44px;[\s\S]+?min-height:\s*44px;/,
  );

  for (const [foreground, background] of [
    ["#FFFFFF", "#1B5E20"],
    ["#FFFFFF", "#2E7D32"],
    ["#FFFFFF", "#33691E"],
  ] as const) assert.ok(contrastRatio(foreground, background) >= 4.5);
  const themeOneMuted = mixHex("#1A1A1A", "#F1F8E9", 0.74);
  assert.ok(contrastRatio(themeOneMuted, "#FFFFFF") >= 4.5);
  assert.ok(contrastRatio(themeOneMuted, "#F1F8E9") >= 4.5);
});

test("mobile focus, sticky guards, placeholders, and source locators remain explicit", () => {
  const layouts = source("src/components/PerformanceLocalV4Layouts.tsx");
  const renderer = source("src/components/PerformanceLocalV4Renderer.tsx");
  assert.match(layouts, /event\.key === "Escape"/);
  assert.match(layouts, /document\.body\.style\.overflow = "hidden"/);
  assert.match(layouts, /triggerRef\.current\?\.focus\(\)/);
  assert.match(layouts, /className="performanceLocalV4NavigationToggle"/);
  assert.match(layouts, /aria-label=\{`Toggle \$\{node\.label\} submenu`\}/);
  assert.match(layouts, /aria-expanded=\{expanded\}/);
  assert.match(layouts, /aria-controls=\{submenuId\}/);
  assert.match(layouts, /event\.key !== "Escape" \|\| !expanded/);
  assert.match(layouts, /setExpanded\(false\);\s*triggerRef\.current\?\.focus\(\)/);
  assert.match(layouts, /onFocusCapture=\{\(\) => onFormFocusRiskChange\(true\)\}/);
  assert.match(layouts, /onBlurCapture=/);
  assert.match(layouts, /data-v4-demo-media-slot=\{slot\}/);
  assert.match(layouts, /data-source-instance-key=\{component\?\.instance_key\}/);
  assert.match(renderer, /formFocusRisk/);
  assert.match(renderer, /heroConversionVisible/);
  assert.match(renderer, /mobileMenuOpen/);
  assert.match(renderer, /data-v4-layout-ready/);
  assert.match(renderer, /data-v4-media-ready/);
  assert.match(renderer, /data-v4-qa-ready/);
  assert.match(renderer, /data-v4-form-ready/);
});

test("footer and post-site diagnostics suppress every fixed V4 control without masking content", () => {
  const renderer = source("src/components/PerformanceLocalV4Renderer.tsx");
  const review = source("src/pages/PerformanceLocalV4ReviewPage.tsx");
  assert.match(renderer, /const \[footerBoundaryReached, setFooterBoundaryReached\] = useState\(true\)/);
  assert.match(renderer, /querySelector<HTMLElement>\(\s*"\.performanceLocalV4Footer"/);
  assert.match(renderer, /footerElement\.getBoundingClientRect\(\)\.top/);
  assert.match(renderer, /window\.addEventListener\("scroll", scheduleBoundaryRecompute, \{ passive: true \}\)/);
  assert.match(renderer, /window\.addEventListener\("resize", scheduleBoundaryRecompute\)/);
  assert.match(renderer, /window\.requestAnimationFrame\(recomputeBoundary\)/);
  assert.match(renderer, /return input\.footerTop <= input\.viewportBottom/);
  assert.match(renderer, /reason: "hidden_footer_or_post_site_content"/);
  assert.match(renderer, /data-v4-fixed-controls-suppressed=\{footerBoundaryReached/);
  assert.match(
    renderer,
    /suppressed=\{formFocusRisk \|\| mobileMenuOpen \|\| footerBoundaryReached\}/,
  );
  assert.match(renderer, /\{stickyVisibility\.visible && stickyActions \? \(/);
  assert.ok(
    review.indexOf('data-v4-preview-canvas="true"') <
      review.indexOf('data-v4-diagnostic-panel="true"'),
  );
});

test("mobile City-Service review clears preserved V3 fixed controls outside the unchanged subtree", () => {
  const review = source("src/pages/PerformanceLocalV4ReviewPage.tsx");
  const renderer = source("src/components/PerformanceLocalV4Renderer.tsx");
  const styles = source("src/styles.css");
  const diagnosticIndex = review.indexOf('className="performanceLocalV4DiagnosticPanel"');

  assert.ok(diagnosticIndex > review.indexOf('rendererSelection === "v4"'));
  assert.ok(diagnosticIndex > review.indexOf('data-v4-v3-control="true"'));
  assert.match(
    review,
    /data-v4-post-site-clearance=\{\s*audit\.pageType === "city_service"\s*\? "legacy-mobile-fixed-controls"\s*:\s*"standard"\s*\}/,
  );
  assert.match(
    styles,
    /@media \(max-width:\s*760px\)[\s\S]+?\.performanceLocalV4DiagnosticPanel\[data-v4-post-site-clearance="legacy-mobile-fixed-controls"\] \{\s*padding-bottom:\s*calc\(180px \+ env\(safe-area-inset-bottom\)\);\s*\}/,
  );
  assert.doesNotMatch(renderer, /data-v4-post-site-clearance|legacy-mobile-fixed-controls/);
  assert.match(renderer, /if \(pageType === "city_service"\) \{[\s\S]+?<PerformanceLocalRenderer/);
});

function count(value: string, needle: string): number {
  return value.split(needle).length - 1;
}

function contrastRatio(left: string, right: string): number {
  const luminance = (value: string) => {
    const channels = value.slice(1).match(/.{2}/g)!.map((channel) => parseInt(channel, 16) / 255);
    const linear = channels.map((channel) => channel <= 0.04045
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4);
    return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
  };
  const first = luminance(left);
  const second = luminance(right);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

function mixHex(foreground: string, background: string, foregroundWeight: number): string {
  const channels = (value: string) => value.slice(1).match(/.{2}/g)!.map((channel) => parseInt(channel, 16));
  const front = channels(foreground);
  const back = channels(background);
  return `#${front.map((channel, index) => Math.round(
    channel * foregroundWeight + back[index] * (1 - foregroundWeight),
  ).toString(16).padStart(2, "0")).join("")}`;
}
