import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { renderToStaticMarkup } from "react-dom/server";

import UniversalFormModesReview, { UNIVERSAL_FORM_DELIVERY_MODES, UNIVERSAL_FORM_MODE_REVIEWS } from "../src/components/UniversalFormModesReview";
import UniversalFormModesReviewPage, { isLoopbackThemeLabHost } from "../src/pages/UniversalFormModesReviewPage";

const root = process.cwd();
const componentSource = readFileSync(resolve(root, "src/components/UniversalFormModesReview.tsx"), "utf8");
const appSource = readFileSync(resolve(root, "src/App.tsx"), "utf8");
const styles = readFileSync(resolve(root, "src/styles.css"), "utf8");

test("the review exposes exactly the five explicit Website form delivery modes", () => {
  assert.deepEqual(UNIVERSAL_FORM_DELIVERY_MODES, ["disabled", "atlas_email", "provider_owned", "atlasops360_native", "external_adapter"]);
  assert.equal(UNIVERSAL_FORM_MODE_REVIEWS.length, 5);
  for (const review of UNIVERSAL_FORM_MODE_REVIEWS) {
    assert.equal(review.productionEnabled, false);
    assert.equal(review.atlasStoresCustomerData, false);
    assert.equal(review.externalRequestNow, false);
    assert.ok(review.providerOwner && review.collector && review.notificationDestination && review.retentionOwner && review.readiness);
    assert.ok(Array.isArray(review.missingConfig));
  }
});

test("the static evidence renders every required state and safe ownership fact", () => {
  const markup = renderToStaticMarkup(<UniversalFormModesReview />);
  const panels = [
    "architecture-summary", "disabled-mode", "atlas-email-blocked", "atlas-email-test-ready", "provider-owned-hosted",
    "provider-owned-missing-origin", "atlasops360-unavailable", "atlasops360-test-adapter", "external-adapter-missing",
    "recipient-verification", "policy-blockers", "outbox-status", "retry-state", "permanent-failure",
    "universal-form-mode-contact-sheet", "universal-form-master-contact-sheet",
  ];
  for (const panel of panels) assert.match(markup, new RegExp(`data-review-panel=\\"${panel}\\"`));
  assert.match(markup, /DEMO CONFIGURATION/);
  assert.match(markup, /NOT ACTIVE/);
  assert.match(markup, /No public form surface/);
  assert.match(markup, /No wrapper, destination, envelope, outbox, or delivery attempt/);
  assert.match(markup, /No hosted surface rendered/);
  assert.match(markup, /allow-forms only/);
  assert.match(markup, /no-referrer/);
  assert.match(markup, /A mutable business contact is not recipient approval/);

  const selfContainedPanels = [
    "disabled-mode", "atlas-email-blocked", "atlas-email-test-ready", "provider-owned-hosted",
    "provider-owned-missing-origin", "atlasops360-unavailable", "atlasops360-test-adapter",
    "external-adapter-missing", "recipient-verification", "policy-blockers", "outbox-status",
    "retry-state", "permanent-failure",
  ];
  for (const panel of selfContainedPanels) {
    const start = markup.indexOf(`id=\"${panel}\"`);
    const end = markup.indexOf("</section>", start);
    assert.notEqual(start, -1, `${panel} is present`);
    const fragment = markup.slice(start, end);
    for (const fact of ["Provider owner", "Collector", "Notification destination", "Retention owner", "Readiness", "Missing configuration", "Production enabled: no", "Atlas stores customer data: no", "External request now: no"]) {
      assert.match(fragment, new RegExp(fact), `${panel} includes ${fact}`);
    }
  }
  const masterStart = markup.indexOf('id=\"universal-form-master-contact-sheet\"');
  const masterFragment = markup.slice(masterStart, markup.indexOf("</section>", masterStart));
  for (const heading of ["Provider owner", "Collector", "Notification destination", "Retention owner", "Readiness", "Missing configuration", "Production", "Atlas customer data", "Request now"]) {
    assert.match(masterFragment, new RegExp(heading));
  }
  assert.equal((masterFragment.match(/role="listitem"/g) ?? []).length, 5);
  assert.doesNotMatch(masterFragment, /<table|overflow-x/);
});

test("the source cannot submit, persist, embed executable provider content, or contact a service", () => {
  for (const forbidden of [/fetch\s*\(/, /apiRequest/, /<form\b/i, /<iframe\b/i, /<script\b/i, /dangerouslySetInnerHTML/, /localStorage/, /sessionStorage/, /indexedDB/, /document\.cookie/, /sendBeacon/, /WebSocket/, /EventSource/, /https?:\/\//i]) {
    assert.doesNotMatch(componentSource, forbidden);
  }
  assert.doesNotMatch(componentSource, /@[a-z0-9.-]+\.[a-z]{2,}/i);
  assert.doesNotMatch(componentSource, /Flo[- ]?Zone|GorillaDesk/i);
});

test("the local review route is lazy, loopback-gated, and absent from dashboard navigation", () => {
  assert.match(appSource, /lazy\(\s*\(\) => import\(\"\.\/pages\/UniversalFormModesReviewPage\"\)/);
  assert.match(appSource, /path=\"\/theme-lab\/universal-form-modes\"/);
  assert.equal((appSource.match(/\/theme-lab\/universal-form-modes/g) ?? []).length, 1);
  assert.equal(isLoopbackThemeLabHost("localhost"), true);
  assert.equal(isLoopbackThemeLabHost("127.0.0.1"), true);
  assert.equal(isLoopbackThemeLabHost("::1"), true);
  assert.equal(isLoopbackThemeLabHost("atlas.example"), false);
  assert.match(renderToStaticMarkup(<UniversalFormModesReviewPage />), /Universal form delivery modes/);
});

test("public delivery, renderer, and export surfaces do not import the operator review", () => {
  for (const path of ["src/components/PerformanceLocalRenderer.tsx", "src/pages/PerformanceLocalDeliveryPage.tsx", "src/pages/ExportPackagePage.tsx"]) {
    assert.doesNotMatch(readFileSync(resolve(root, path), "utf8"), /UniversalFormModesReview|universal-form-modes/);
  }
});

test("review styling is scoped, accessible, and responsive without horizontal overflow", () => {
  assert.match(styles, /\.universalFormModesReview\s*\{/);
  assert.match(styles, /\.universalFormModesReviewJump a:focus-visible/);
  assert.match(styles, /min-height:\s*44px/);
  assert.match(styles, /overflow-wrap:\s*anywhere/);
  assert.match(styles, /@media \(max-width:\s*720px\)/);
  assert.match(styles, /\.universalFormModesReviewGrid[^{]*\{[\s\S]*grid-template-columns:\s*1fr/);
  assert.match(styles, /\.universalFormModesReviewMasterGrid\s*\{[\s\S]*grid-template-columns:\s*repeat\(5/);
  assert.doesNotMatch(styles, /\.universalFormModesReviewTableWrap|\.universalFormModesReviewMasterGrid[^}]*overflow-x/);
});
