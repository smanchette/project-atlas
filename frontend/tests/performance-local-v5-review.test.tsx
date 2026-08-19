import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

import { renderToStaticMarkup } from "react-dom/server";

import {
  isCurrentSupportedPerformanceLocalV5Page,
  PerformanceLocalV5ReviewPage,
} from "../src/pages/PerformanceLocalV5ReviewPage";
import { isLoopbackThemeLabHost } from "../src/pages/UniversalFormModesReviewPage";
import type { GeneratedPage } from "../src/types";

const root = process.cwd();
const source = (path: string) => readFileSync(resolve(root, path), "utf8");

test("the V5 operator review is loopback-only and fails closed elsewhere", () => {
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
    const markup = renderToStaticMarkup(<PerformanceLocalV5ReviewPage />);
    assert.match(markup, /Local Theme Lab only/);
    assert.match(markup, /unavailable outside a loopback host/);
    assert.doesNotMatch(markup, /data-v5-preview-canvas|data-v5-site-root/);
  } finally {
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else Reflect.deleteProperty(globalThis, "window");
  }
});

test("App exposes exactly one lazy local V5 route", () => {
  const app = source("src/App.tsx");
  assert.match(app, /lazy\(\s*\(\) => import\("\.\/pages\/PerformanceLocalV5ReviewPage"\)/);
  assert.match(
    app,
    /path="\/theme-lab\/performance-local\/v5\/generated-pages\/:id"\s*element=\{<ThemeLabRoute><PerformanceLocalV5ReviewPage \/><\/ThemeLabRoute>\}/,
  );
  assert.equal(count(app, "/theme-lab/performance-local/v5/generated-pages/:id"), 1);
});

test("the review exposes the exact draft label, representative selector, modes, V4 control, and banner toggle", () => {
  const review = source("src/pages/PerformanceLocalV5ReviewPage.tsx");
  assert.match(review, /PERFORMANCE_LOCAL_V5_PREVIEW_LABEL/);
  assert.match(review, /Representative page/);
  assert.match(review, /Truthful resolved/);
  assert.match(review, /Structural demo/);
  assert.match(review, /V5 layout/);
  assert.match(review, /V4 control/);
  assert.match(review, /Campaign banner/);
  assert.match(review, /PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION\.generatedPageId/);
  assert.doesNotMatch(review, /generatedPageId:\s*41|\bid\s*===\s*41/);
});

test("review data access is read-only, exact-scope, and uses governed V3 conversion input", () => {
  const review = source("src/pages/PerformanceLocalV5ReviewPage.tsx");
  assert.match(review, /apiRequest<GeneratedPage>\(`\/api\/generated-pages\/\$\{pageId\}`\)/);
  assert.match(review, /apiRequest<GeneratedPage\[\]>\("\/api\/generated-pages"\)/);
  assert.match(review, /family_key=performance-local&family_version=3&page_id=\$\{pageId\}/);
  assert.match(review, /performanceLocalDeliveryApiPath\("inactive_draft_preview"/);
  assert.match(review, /exactPlannedPage\(sitePlan, delivery\)/);
  assert.match(review, /sameCanonicalJson\(requestedPage, delivery\.page\)/);
  assert.doesNotMatch(review, /method:\s*["'](?:POST|PUT|PATCH|DELETE)["']/);
  assert.doesNotMatch(review, /localStorage|sessionStorage|indexedDB|document\.cookie/);
});

test("direct governed targets may be nonrepresentative but must remain current, supported, and in Website scope", () => {
  const requested = generatedPageIdentity(84, 7, "city_service");
  const representative = generatedPageIdentity(41, 7, "city_service");
  assert.equal(isCurrentSupportedPerformanceLocalV5Page(requested, [representative, requested], 7), true);
  assert.equal(isCurrentSupportedPerformanceLocalV5Page(requested, [representative], 7), false);
  assert.equal(
    isCurrentSupportedPerformanceLocalV5Page(requested, [representative, generatedPageIdentity(84, 8, "city_service")], 7),
    false,
  );
  assert.equal(
    isCurrentSupportedPerformanceLocalV5Page(generatedPageIdentity(84, 7, "unsupported"), [requested], 7),
    false,
  );
});

test("operator controls and diagnostics remain outside the stable site root", () => {
  const review = source("src/pages/PerformanceLocalV5ReviewPage.tsx");
  const renderer = source("src/components/PerformanceLocalV5Renderer.tsx");
  const controlsIndex = review.indexOf('className="performanceLocalV5ReviewControls"');
  const previewIndex = review.indexOf('className="performanceLocalV5PreviewCanvas"');
  const diagnosticIndex = review.indexOf('className="performanceLocalV5DiagnosticPanel"');
  assert.ok(controlsIndex >= 0 && controlsIndex < previewIndex);
  assert.ok(diagnosticIndex > previewIndex);
  assert.match(renderer, /className="performanceLocalV5Site"[\s\S]*?data-v5-site-root="true"/);
  assert.doesNotMatch(renderer, /data-v5-diagnostic-panel|performanceLocalV5DiagnosticPanel/);
  assert.match(renderer, /data-v5-site-root="true"[\s\S]*?data-v5-preservation-control="true"/);
});

test("diagnostics separate layout, media, QA, form, activation, export, and publication readiness", () => {
  const review = source("src/pages/PerformanceLocalV5ReviewPage.tsx");
  for (const label of [
    "Layout ready",
    "Media ready",
    "QA ready",
    "Form ready",
    "Activation ready",
    "Export ready",
    "Publication ready",
    "Source components",
    "Consumed components",
    "Unconsumed destination entries",
    "Duplicated destination entries",
    "Missing required regions",
  ]) assert.match(review, new RegExp(label));
  assert.match(review, /productionReady/);
  assert.match(review, /preview_candidate|PERFORMANCE_LOCAL_V5_THEME\.status/);
});

test("truthful and demo state are visibly separated and placeholders remain operator-only", () => {
  const review = source("src/pages/PerformanceLocalV5ReviewPage.tsx");
  const layouts = source("src/components/PerformanceLocalV5Layouts.tsx");
  assert.match(review, /reviewMode === "structural_demo" && rendererSelection === "v5"/);
  assert.match(review, /PERFORMANCE_LOCAL_V5_DEMO_MEDIA_LABEL/);
  assert.match(layouts, /if \(reviewMode !== "structural_demo" \|\| !component\) return null/);
  assert.match(layouts, /data-v5-demo-target-instance-key=\{targetInstanceKey\}/);
  assert.doesNotMatch(layouts, /fetch\(|apiRequest\(|XMLHttpRequest|WebSocket/);
});

test("the review CSS is responsive and keeps the preview canvas free of diagnostic styling", () => {
  const css = source("src/styles.css");
  const marker = css.indexOf("/* Performance Local V5:");
  assert.ok(marker > 0);
  const v5 = css.slice(marker);
  assert.match(v5, /\.performanceLocalV5ReviewHeader/);
  assert.match(v5, /\.performanceLocalV5DiagnosticPanel/);
  assert.match(v5, /\.performanceLocalV5PreviewCanvas/);
  assert.match(v5, /@media \(max-width:\s*760px\)/);
  assert.doesNotMatch(v5, /\.performanceLocalV4/);
  assert.doesNotMatch(v5, /\[data-v5-site-root\]/);
});

function count(value: string, needle: string): number {
  return value.split(needle).length - 1;
}

function generatedPageIdentity(id: number, websiteId: number, pageType: string): GeneratedPage {
  return { id, website_id: websiteId, page_type: pageType } as GeneratedPage;
}
