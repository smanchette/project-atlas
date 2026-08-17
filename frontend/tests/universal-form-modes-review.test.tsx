import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { renderToStaticMarkup } from "react-dom/server";

import UniversalFormModesReview, {
  THEME_LAB_DEMO_DEFAULT_FIELD_COUNT,
  THEME_LAB_DEMO_FIELD_REVIEW_STATE_IDS,
  THEME_LAB_DEMO_MAX_FIELD_COUNT,
  THEME_LAB_DEMO_STANDARD_FIELDS,
  UNIVERSAL_FORM_DELIVERY_MODES,
  UNIVERSAL_FORM_MODE_REVIEWS,
} from "../src/components/UniversalFormModesReview";
import UniversalFormModesReviewPage, { isLoopbackThemeLabHost } from "../src/pages/UniversalFormModesReviewPage";

const root = process.cwd();
const componentSource = readFileSync(resolve(root, "src/components/UniversalFormModesReview.tsx"), "utf8");
const appSource = readFileSync(resolve(root, "src/App.tsx"), "utf8");
const styles = readFileSync(resolve(root, "src/styles.css"), "utf8");

function panelFragment(markup: string, panel: string): string {
  const start = markup.indexOf(`id="${panel}"`);
  assert.notEqual(start, -1, `${panel} is present`);
  return markup.slice(start, markup.indexOf("</section>", start));
}

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
  assert.match(markup, /DEMO CONFIGURATION — NOT ACTIVE/);
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

test("Atlas-managed field review fixes the exact five defaults in order and caps the total at six", () => {
  assert.equal(THEME_LAB_DEMO_DEFAULT_FIELD_COUNT, 5);
  assert.equal(THEME_LAB_DEMO_MAX_FIELD_COUNT, 6);
  assert.deepEqual(
    THEME_LAB_DEMO_STANDARD_FIELDS.map(({ key, label }) => ({ key, label })),
    [
      { key: "name", label: "Name" },
      { key: "phone", label: "Phone" },
      { key: "postal_code", label: "ZIP code" },
      { key: "requested_service", label: "Requested Service" },
      { key: "message", label: "Optional Message" },
    ],
  );

  const markup = renderToStaticMarkup(<UniversalFormModesReview />);
  const defaultFive = panelFragment(markup, "atlas-fields-default-five");
  assert.match(defaultFive, /data-field-count="5"/);
  assert.match(defaultFive, /data-field-valid="true"/);
  assert.equal((defaultFive.match(/data-field-key=/g) ?? []).length, 5);

  let priorIndex = -1;
  for (const field of THEME_LAB_DEMO_STANDARD_FIELDS) {
    const index = defaultFive.indexOf(`data-field-key="${field.key}"`);
    assert.ok(index > priorIndex, `${field.key} retains its standard display order`);
    priorIndex = index;
  }

  const validSix = panelFragment(markup, "atlas-fields-valid-six");
  assert.match(validSix, /data-field-count="6"/);
  assert.match(validSix, /data-field-valid="true"/);
  assert.equal((validSix.match(/data-field-key=/g) ?? []).length, 6);
  assert.match(validSix, /data-field-key="project_timeline"/);
  assert.match(validSix, /demo-field-revision-006/);
});

test("the Theme Lab exposes exactly six field-limit review states and fails closed for seven and reserved keys", () => {
  assert.deepEqual(THEME_LAB_DEMO_FIELD_REVIEW_STATE_IDS, [
    "atlas-fields-default-five",
    "atlas-fields-valid-six",
    "atlas-fields-rejected-seven",
    "atlas-fields-reserved-key",
    "atlas-fields-choice-types",
    "atlas-fields-mobile-six",
  ]);

  const markup = renderToStaticMarkup(<UniversalFormModesReview />);
  for (const panel of THEME_LAB_DEMO_FIELD_REVIEW_STATE_IDS) {
    assert.equal((markup.match(new RegExp(`data-review-panel="${panel}"`, "g")) ?? []).length, 1);
  }

  const rejectedSeven = panelFragment(markup, "atlas-fields-rejected-seven");
  assert.match(rejectedSeven, /data-field-count="7"/);
  assert.match(rejectedSeven, /data-field-valid="false"/);
  assert.equal((rejectedSeven.match(/data-field-key=/g) ?? []).length, 7);
  assert.match(rejectedSeven, /Nothing is silently dropped or reclassified/);

  const reserved = panelFragment(markup, "atlas-fields-reserved-key");
  assert.match(reserved, /data-field-valid="false"/);
  assert.match(reserved, /Request-ID/);
  assert.match(reserved, /request_id/);
  assert.match(reserved, /Rejected · reserved system key/);
});

test("choice groups each count as one field and the mobile review contains all six fields", () => {
  const markup = renderToStaticMarkup(<UniversalFormModesReview />);
  const choices = panelFragment(markup, "atlas-fields-choice-types");
  assert.equal((choices.match(/data-choice-field-type=/g) ?? []).length, 2);
  assert.match(choices, /data-choice-field-type="dropdown"/);
  assert.match(choices, /data-choice-field-type="radio"/);
  assert.equal((choices.match(/one field/g) ?? []).length, 2);
  assert.match(choices, /two alternative synthetic sixth-field revisions/);

  const mobile = panelFragment(markup, "atlas-fields-mobile-six");
  assert.match(mobile, /data-mobile-field-count="6"/);
  assert.equal((mobile.match(/data-field-key=/g) ?? []).length, 6);
  assert.match(mobile, /390 px review frame/);
  assert.match(mobile, /Single column · no submit control/);
});

test("the source cannot submit, persist, embed executable provider content, or contact a service", () => {
  for (const forbidden of [/fetch\s*\(/, /apiRequest/, /<(?:form|button|input|select|textarea)\b/i, /<iframe\b/i, /<script\b/i, /dangerouslySetInnerHTML/, /onSubmit\s*=/, /onClick\s*=/, /localStorage/, /sessionStorage/, /indexedDB/, /document\.cookie/, /sendBeacon/, /XMLHttpRequest/, /WebSocket/, /EventSource/, /https?:\/\//i]) {
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
  assert.match(styles, /\.universalFormModesReviewMobileFrame\s*\{[\s\S]*width:\s*min\(390px,\s*100%\)/);
  assert.match(styles, /\.universalFormModesReviewMobileFrame \.universalFormModesReviewFieldList\s*\{[\s\S]*grid-template-columns:\s*1fr/);
  assert.match(styles, /\.universalFormModesReviewChoiceExamples[^{]*\{[\s\S]*grid-template-columns:\s*1fr/);
  assert.match(styles, /\.universalFormModesReviewMasterGrid\s*\{[\s\S]*grid-template-columns:\s*repeat\(5/);
  assert.doesNotMatch(styles, /\.universalFormModesReviewTableWrap|\.universalFormModesReviewMasterGrid[^}]*overflow-x/);
});
