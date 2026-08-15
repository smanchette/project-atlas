import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";

import PerformanceLocalRenderer, {
  performanceLocalActionCopyEquivalent,
  performanceLocalFormDomId,
  performanceLocalSemanticActionKey,
} from "../src/components/PerformanceLocalRenderer";
import {
  performanceLocalDeliveryApiPath,
  performanceLocalDeliveryConfiguration,
  performanceLocalDeliveryPagePath,
  performanceLocalDeliveryValidationError,
} from "../src/components/performanceLocalDelivery";
import {
  PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_THEME,
  PERFORMANCE_LOCAL_V2_SOURCE_COMMIT,
} from "../src/components/performanceLocalTheme";
import {
  PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_V3_THEME,
} from "../src/components/performanceLocalThemeV3";
import {
  PerformanceLocalDeliveryBlocked,
  performanceLocalDeliveryFailureMessage,
} from "../src/pages/PerformanceLocalDeliveryPage";
import type {
  GeneratedPage,
  PageComponentInstance,
  PageComposition,
  PerformanceLocalDeliveryMode,
  PerformanceLocalDeliveryRead,
  PerformanceLocalFormReadinessRead,
  ThemeConfigurationAuditIdentityRead,
  WebsiteThemeComponentConfigurationRead,
} from "../src/types";
import { selectedTheme } from "./theme-fixtures";

const websiteId = 31;
const businessId = 21;
const generatedPageId = 1101;
const plannedPageId = 1001;
const configurationId = 91;
const formId = 44;
const bannerId = 45;
const stickyId = 46;

test("V3 is a distinct source-defined preview candidate with exact server contract parity", () => {
  const serverV2 = JSON.parse(readFileSync(
    resolve(process.cwd(), "../backend/app/schemas/performance_local_v2_contract.json"),
    "utf8",
  ));
  const serverV3 = JSON.parse(readFileSync(
    resolve(process.cwd(), "../backend/app/schemas/performance_local_v3_contract.json"),
    "utf8",
  ));
  assert.equal(PERFORMANCE_LOCAL_THEME.key, "performance-local");
  assert.equal(PERFORMANCE_LOCAL_THEME.version, 2);
  assert.equal(PERFORMANCE_LOCAL_V2_SOURCE_COMMIT, "1b766664ea99d923195bbf98e8a1e4d833b50084");
  assert.deepEqual(PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS, serverV2);
  assert.equal(PERFORMANCE_LOCAL_V3_THEME.key, "performance-local");
  assert.equal(PERFORMANCE_LOCAL_V3_THEME.version, 3);
  assert.equal(PERFORMANCE_LOCAL_V3_THEME.status, "preview_candidate");
  assert.equal(PERFORMANCE_LOCAL_V3_THEME.productionReady, false);
  assert.equal(PERFORMANCE_LOCAL_V3_THEME.websiteIndependent, true);
  assert.notStrictEqual(PERFORMANCE_LOCAL_V3_THEME, PERFORMANCE_LOCAL_THEME);
  assert.deepEqual(PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS, serverV3);
  assert.equal(serverV3.length, 23);
  assert.deepEqual(
    serverV3.map((contract: { component_key: string }) => contract.component_key),
    serverV2.map((contract: { component_key: string }) => contract.component_key),
  );
  assert.ok(serverV3.every((contract: { contract_version: number }) => contract.contract_version === 3));
  assert.ok(serverV2.every((contract: { contract_version: number }) => contract.contract_version === 2));
  assert.equal(
    serverV3.find((contract: { component_key: string }) => contract.component_key === "campaign_banner").variant,
    "single_action_safe_strip",
  );
  assert.equal(
    serverV3.find((contract: { component_key: string }) => contract.component_key === "compact_estimate_form").variant,
    "provider_independent_gateway",
  );
});

test("canonical UI and API delivery routes are mode-separated and never query fabricated", () => {
  assert.equal(
    performanceLocalDeliveryPagePath("active", generatedPageId),
    "/delivery/generated-pages/1101",
  );
  assert.equal(
    performanceLocalDeliveryPagePath("inactive_draft_preview", generatedPageId, configurationId),
    "/delivery/local-preview/configurations/91/generated-pages/1101",
  );
  assert.equal(
    performanceLocalDeliveryPagePath("activation_rehearsal", generatedPageId, configurationId),
    "/delivery/rehearsal/configurations/91/generated-pages/1101",
  );
  assert.equal(
    performanceLocalDeliveryApiPath("active", generatedPageId),
    "/api/theme-delivery/active/generated-pages/1101",
  );
  assert.equal(
    performanceLocalDeliveryApiPath("inactive_draft_preview", generatedPageId, configurationId),
    "/api/theme-delivery/local-preview/configurations/91/generated-pages/1101",
  );
  assert.equal(
    performanceLocalDeliveryApiPath("activation_rehearsal", generatedPageId, configurationId),
    "/api/theme-delivery/rehearsal/configurations/91/generated-pages/1101",
  );
  assert.throws(
    () => performanceLocalDeliveryApiPath("inactive_draft_preview", generatedPageId),
    /configuration identity/,
  );

  const appSource = source("src/App.tsx");
  const pageSource = source("src/pages/PerformanceLocalDeliveryPage.tsx");
  assert.match(appSource, /path="\/delivery\/generated-pages\/:id"/);
  assert.match(appSource, /path="\/delivery\/local-preview\/configurations\/:configurationId\/generated-pages\/:id"/);
  assert.match(appSource, /path="\/delivery\/rehearsal\/configurations\/:configurationId\/generated-pages\/:id"/);
  assert.match(appSource, /requestedMode="active"/);
  assert.match(appSource, /requestedMode="inactive_draft_preview"/);
  assert.match(appSource, /requestedMode="activation_rehearsal"/);
  assert.doesNotMatch(pageSource, /useSearchParams|URLSearchParams|location\.search/);
  assert.doesNotMatch(pageSource, /theme-lab|ThemeLab/);
  assert.match(pageSource, /performanceLocalDeliveryApiPath\(requestedMode, pageId, requestedConfigurationId\)/);
});

test("inactive preview accepts only its exact page, Website, config, scope, fingerprints, and audits", () => {
  const delivery = deliveryFixture("inactive_draft_preview");
  assert.equal(validate(delivery, "inactive_draft_preview"), null);
  assert.ok(performanceLocalDeliveryConfiguration(delivery));

  const wrongConfiguration = clone(delivery);
  wrongConfiguration.website_configuration.id += 1;
  assert.match(
    validate(wrongConfiguration, "inactive_draft_preview") ?? "",
    /configuration identity|does not identify|component revision/,
  );

  const wrongWebsite = clone(delivery);
  wrongWebsite.components[0].website_id += 1;
  assert.match(validate(wrongWebsite, "inactive_draft_preview") ?? "", /component revision/);

  const wrongPage = clone(delivery);
  wrongPage.composition.generated_page_id += 1;
  assert.match(validate(wrongPage, "inactive_draft_preview") ?? "", /requested Generated Page/);

  const wrongOverride = clone(delivery);
  wrongOverride.components[0].scope_type = "page_override";
  wrongOverride.components[0].planned_page_id = plannedPageId + 1;
  assert.match(validate(wrongOverride, "inactive_draft_preview") ?? "", /Page override/);

  const wrongFingerprint = clone(delivery);
  wrongFingerprint.components[0].integrity_fingerprint = "not-a-fingerprint";
  assert.match(validate(wrongFingerprint, "inactive_draft_preview") ?? "", /component revision/);

  const wrongContract = clone(delivery);
  wrongContract.theme_version.supported_component_contracts[0].variant = "tampered";
  assert.match(validate(wrongContract, "inactive_draft_preview") ?? "", /canonical component contract/);

  const missingAudit = clone(delivery);
  missingAudit.audit_history = missingAudit.audit_history.filter(
    (audit) => audit.component_configuration_id !== formId,
  );
  assert.match(validate(missingAudit, "inactive_draft_preview") ?? "", /creation audit coverage/);
});

test("governed stale or missing-media composition remains visible only as a labeled blocked result", () => {
  const blocked = deliveryFixture("inactive_draft_preview");
  blocked.composition.status = "stale";
  blocked.composition.validation_errors = ["Required governed media is missing."];
  blocked.renderer_result.status = "blocked";
  blocked.renderer_result.result_code = "renderer_blocked_by_governed_readiness";
  blocked.blockers.push({
    code: "composition_readiness_1",
    category: "media",
    reason: "Required governed media is missing.",
  });
  assert.equal(validate(blocked, "inactive_draft_preview"), null);

  const fabricatedReady = clone(blocked);
  fabricatedReady.renderer_result.status = "ready";
  assert.match(validate(fabricatedReady, "inactive_draft_preview") ?? "", /governed blocked result/);

  const mismatchedReason = clone(blocked);
  mismatchedReason.blockers.find((blocker) => blocker.code === "composition_readiness_1")!.reason =
    "Different blocker.";
  assert.match(validate(mismatchedReason, "inactive_draft_preview") ?? "", /governed blocked result/);
});

test("rehearsal supports exact pre-activation and activated disposable phases without entering public delivery", () => {
  const preActivation = deliveryFixture("activation_rehearsal");
  preActivation.renderer_result.status = "blocked";
  preActivation.renderer_result.result_code = "renderer_blocked_by_governed_readiness";
  preActivation.export_eligibility.mode = "internal_rehearsal";
  preActivation.blockers.push({ code: "form_not_ready", category: "form", reason: "Synthetic provider is not ready." });
  assert.equal(validate(preActivation, "activation_rehearsal"), null);

  const activated = activatedRehearsalFixture();
  assert.equal(validate(activated, "activation_rehearsal"), null);
  assert.ok(performanceLocalDeliveryConfiguration(activated));
  assert.match(validate(activated, "active") ?? "", /delivery mode|safety label/);
  assert.match(validate(activated, "inactive_draft_preview") ?? "", /delivery mode|safety label/);

  const missingActivationAudit = clone(activated);
  missingActivationAudit.audit_history = missingActivationAudit.audit_history.filter(
    (audit) => !(audit.action_type === "component_activated" && audit.component_configuration_id === formId),
  );
  assert.match(validate(missingActivationAudit, "activation_rehearsal") ?? "", /activation audits/);

  const rehearsalOnPublicMode = clone(activated);
  rehearsalOnPublicMode.mode = "active";
  rehearsalOnPublicMode.non_active_label = null;
  assert.match(validate(rehearsalOnPublicMode, "active") ?? "", /approved materialization|source identity/);
});

test("public delivery enforces redacted provider identities while safe readiness booleans remain usable", () => {
  const activated = activatedRehearsalFixture();
  const form = activated.components.find((component) => component.id === formId)!;
  const provider = form.configuration_payload.provider as Record<string, unknown>;
  assert.equal(provider.provider_key, null);
  assert.equal(provider.destination, null);
  assert.equal(provider.provider_secret_reference, null);
  assert.equal((form.configuration_payload.spam as Record<string, unknown>).configuration_reference, null);
  assert.equal(activated.form_readiness.provider_state.provider_key, null);
  assert.equal(activated.form_readiness.provider_state.destination_configured, true);
  assert.equal(activated.form_readiness.security.secret_reference_configured, true);
  assert.equal(validate(activated, "activation_rehearsal"), null);

  const leakedProvider = clone(activated);
  const leakedForm = leakedProvider.components.find((component) => component.id === formId)!;
  (leakedForm.configuration_payload.provider as Record<string, unknown>).provider_key = "synthetic-discard";
  assert.match(validate(leakedProvider, "activation_rehearsal") ?? "", /redacted|provider-independent|readiness/);

  const leakedDestination = clone(activated);
  const destinationForm = leakedDestination.components.find((component) => component.id === formId)!;
  (destinationForm.configuration_payload.provider as Record<string, unknown>).destination = "memory://discard";
  assert.match(validate(leakedDestination, "activation_rehearsal") ?? "", /redacted|provider-independent|readiness/);
});

test("equivalent evergreen copy renders exactly one full-banner action with exact destination", () => {
  assert.equal(performanceLocalSemanticActionKey("Request an Estimate"), "request estimate");
  assert.equal(performanceLocalSemanticActionKey(" Request—Estimate! "), "request estimate");
  assert.equal(performanceLocalActionCopyEquivalent("Request an Estimate", "Request Estimate"), true);
  assert.equal(performanceLocalActionCopyEquivalent("Seasonal inspection", "Request Estimate"), false);

  const delivery = deliveryFixture("inactive_draft_preview");
  const configuration = performanceLocalDeliveryConfiguration(delivery)!;
  const markup = renderDelivery(delivery, configuration);
  const banner = bannerMarkup(markup);
  assert.match(banner, /data-public-action-copy="semantic_duplicate_suppressed"/);
  assert.match(banner, /class="performanceLocalContainer performanceLocalCampaignSingleAction"/);
  assert.match(banner, new RegExp(`href="#${performanceLocalFormDomId(formId)}"`));
  assert.equal((banner.match(/<a\b/g) ?? []).length, 1);
  assert.equal(visibleText(banner), "Request an Estimate");
  assert.doesNotMatch(visibleText(banner), /Request Estimate Request Estimate/);

  const css = source("src/styles.css");
  assert.match(css, /\.performanceLocalCampaign \.performanceLocalCampaignSingleAction\s*\{[^}]*width:\s*100%;[^}]*min-height:\s*56px;/s);
  assert.match(css, /\.performanceLocalCampaign \.performanceLocalCampaignSingleAction:hover/);
  assert.match(css, /\.performanceLocalCampaign \.performanceLocalCampaignSingleAction:focus-visible/);
  assert.match(css, /\.performanceLocalCampaign \.performanceLocalCampaignSingleAction:active/);
});

test("distinct campaign copy retains separate offer and action while disabled or unsafe banners leave no wrapper", () => {
  const delivery = deliveryFixture("inactive_draft_preview");
  const banner = delivery.components.find((component) => component.id === bannerId)!;
  banner.configuration_payload = {
    intent: "time_bound_campaign",
    message: "Seasonal inspection availability",
    cta_label: "Request Estimate",
    approved_offer_details: "Approved seasonal availability details",
    terms_reference: "terms-v1",
    start_at: "2026-08-01T00:00:00Z",
    end_at: "2026-09-01T00:00:00Z",
    approval_identity: "banner-approval-v3",
  };
  const configuration = performanceLocalDeliveryConfiguration(delivery)!;
  const markup = renderDelivery(delivery, configuration);
  const distinctBanner = bannerMarkup(markup);
  assert.match(distinctBanner, /data-public-action-copy="distinct_copy_and_action"/);
  assert.equal((distinctBanner.match(/<a\b/g) ?? []).length, 1);
  assert.match(visibleText(distinctBanner), /Seasonal inspection availability/);
  assert.match(visibleText(distinctBanner), /Request Estimate/);

  const disabled = deliveryFixture("inactive_draft_preview");
  disabled.components.find((component) => component.id === bannerId)!.enabled = false;
  const disabledConfiguration = performanceLocalDeliveryConfiguration(disabled)!;
  assert.doesNotMatch(renderDelivery(disabled, disabledConfiguration), /class="performanceLocalCampaign/);

  const exact = deliveryFixture("inactive_draft_preview");
  const unsafeConfiguration = performanceLocalDeliveryConfiguration(exact)!;
  const unsafeCampaign = {
    ...unsafeConfiguration.campaign!,
    ctaDestination: "#missing-form-revision",
  };
  const unsafeMarkup = renderDelivery(exact, { ...unsafeConfiguration, campaign: unsafeCampaign });
  assert.doesNotMatch(unsafeMarkup, /class="performanceLocalCampaign/);
});

test("delivery output excludes Theme Lab diagnostics while Theme Lab defaults retain them", () => {
  const delivery = deliveryFixture("inactive_draft_preview");
  const configuration = performanceLocalDeliveryConfiguration(delivery)!;
  const publicMarkup = renderDelivery(delivery, configuration);
  assert.match(publicMarkup, /data-atlas-adapter-version="3"/);
  assert.match(publicMarkup, /data-atlas-delivery-mode="inactive_draft_preview"/);
  assert.doesNotMatch(publicMarkup, /performanceLocalDiagnostics/);
  assert.doesNotMatch(publicMarkup, /data-component-version=/);
  assert.doesNotMatch(publicMarkup, /data-component-theme-compatibility=/);
  assert.doesNotMatch(publicMarkup, /data-provider-state=|data-provider-configured=/);
  assert.doesNotMatch(publicMarkup, /data-provider-mapping=|data-validation-contract=/);
  assert.doesNotMatch(publicMarkup, /performanceLocalFormReadiness|Submission readiness/);

  const themeLabMarkup = renderToStaticMarkup(
    <StaticRouter location="/theme-lab/generated-pages/1101">
      <PerformanceLocalRenderer
        campaign={configuration.campaign}
        composition={delivery.composition}
        estimateForm={configuration.estimateForm}
        formSubmission={configuration.formSubmission}
        governedContact={configuration.governedContact}
        page={delivery.page}
        stickyActions={configuration.stickyActions}
        toggles={configuration.toggles}
        previewedAt={new Date("2026-08-15T12:00:00Z")}
      />
    </StaticRouter>,
  );
  assert.match(themeLabMarkup, /data-atlas-adapter-version="2"/);
  assert.match(themeLabMarkup, /data-component-version="2"/);
  assert.match(themeLabMarkup, /performanceLocalDiagnostics/);
  assert.match(themeLabMarkup, /data-provider-state=/);
  assert.match(themeLabMarkup, /data-provider-mapping=/);
  assert.match(themeLabMarkup, /performanceLocalFormReadiness/);
});

test("disabled forms collect nothing; ready rehearsal forms expose only the normalized Atlas gateway boundary", () => {
  const draft = deliveryFixture("inactive_draft_preview");
  const draftConfiguration = performanceLocalDeliveryConfiguration(draft)!;
  const draftMarkup = renderDelivery(draft, draftConfiguration);
  const draftForm = formMarkup(draftMarkup);
  assert.match(draftForm, /data-preview-only="true"/);
  assert.match(draftForm, /data-collects-data="false"/);
  assert.doesNotMatch(draftForm, /data-form-readiness=|Submission readiness/);
  assert.doesNotMatch(draftForm, /data-provider-state=|data-provider-mapping=/);
  assert.doesNotMatch(draftForm, /\sname=/);
  assert.match(draftForm, /<button type="submit" disabled=""/);

  const rehearsal = activatedRehearsalFixture();
  const readyConfiguration = performanceLocalDeliveryConfiguration(rehearsal)!;
  const readyMarkup = renderDelivery(rehearsal, {
    ...readyConfiguration,
    formSubmission: {
      ...readyConfiguration.formSubmission,
      submit: async () => ({
        status: "accepted",
        code: "submission_accepted",
        safe_message: "Synthetic request accepted.",
        provider_reference: null,
      }),
    },
  });
  const readyForm = formMarkup(readyMarkup);
  assert.match(readyForm, /data-preview-only="false"/);
  assert.match(readyForm, /data-collects-data="true"/);
  assert.doesNotMatch(readyForm, /data-form-readiness=|Submission readiness/);
  assert.doesNotMatch(readyForm, /data-provider-state=|data-provider-mapping=/);
  for (const name of ["name", "phone", "postal-code", "requested-service", "message"]) {
    assert.match(readyForm, new RegExp(`name="${name}"`));
  }
  assert.doesNotMatch(readyForm, /provider_key|provider_secret_reference|memory:\/\/|synthetic-discard/);

  const rendererSource = source("src/components/PerformanceLocalRenderer.tsx");
  const pageSource = source("src/pages/PerformanceLocalDeliveryPage.tsx");
  const ownedSource = `${rendererSource}\n${pageSource}`;
  assert.doesNotMatch(ownedSource, /localStorage|sessionStorage|sendBeacon|XMLHttpRequest|console\.|analytics/i);
  assert.match(pageSource, /"Idempotency-Key": idempotencyKey/);
  assert.match(pageSource, /"X-Atlas-CSRF-Token": csrfToken/);
  assert.match(pageSource, /JSON\.stringify\(payload\)/);
  assert.doesNotMatch(pageSource, /consent_identity|idempotency_key/);
  assert.match(rendererSource, /postal_code: formStringValue\(values, "postal-code"\)/);
  assert.match(rendererSource, /requested_service: formStringValue\(values, "requested-service"\)/);
});

test("public blocked delivery is generic while operator preview and rehearsal retain typed evidence", () => {
  const active = activeDeliveryFixture();
  active.renderer_result.status = "blocked";
  active.renderer_result.result_code = "sensitive_internal_result_code";
  active.blockers = [{
    code: "sensitive_internal_blocker",
    category: "privacy",
    reason: "Internal provider governance detail.",
  }];
  const publicMarkup = renderToStaticMarkup(
    <PerformanceLocalDeliveryBlocked delivery={active} />,
  );
  assert.match(publicMarkup, /Performance Local delivery unavailable/);
  assert.doesNotMatch(publicMarkup, /sensitive_internal|provider governance|<code>|<li>/);

  const rehearsal = clone(active);
  rehearsal.mode = "activation_rehearsal";
  rehearsal.non_active_label = "ACTIVATION REHEARSAL — DISPOSABLE";
  const rehearsalMarkup = renderToStaticMarkup(
    <PerformanceLocalDeliveryBlocked delivery={rehearsal} />,
  );
  assert.match(rehearsalMarkup, /sensitive_internal_result_code/);
  assert.match(rehearsalMarkup, /Internal provider governance detail/);
});

test("active load, validation, and presentation failures never expose internal detail", () => {
  for (const detail of [
    "Audit 91 has a mismatched fingerprint.",
    "The exact Website scope is invalid.",
    "Provider secret reference synthetic-sensitive-value.",
  ]) {
    assert.equal(
      performanceLocalDeliveryFailureMessage("active", new Error(detail)),
      "Performance Local delivery is unavailable.",
    );
    assert.equal(
      performanceLocalDeliveryFailureMessage("inactive_draft_preview", new Error(detail)),
      detail,
    );
    assert.equal(
      performanceLocalDeliveryFailureMessage("activation_rehearsal", new Error(detail)),
      detail,
    );
  }
});

test("safe loopback privacy destinations are rehearsal-only in the renderer", () => {
  const rehearsal = activatedRehearsalFixture();
  const rehearsalForm = rehearsal.components.find((component) => component.id === formId)!;
  (rehearsalForm.configuration_payload.privacy as Record<string, unknown>).policy_destination =
    "http://localhost/privacy";
  const rehearsalConfiguration = performanceLocalDeliveryConfiguration(rehearsal)!;
  const rehearsalWithSubmit = {
    ...rehearsalConfiguration,
    formSubmission: {
      ...rehearsalConfiguration.formSubmission,
      submit: async () => ({
        status: "accepted" as const,
        code: "submission_accepted" as const,
        safe_message: "Synthetic request accepted.",
        provider_reference: null,
      }),
    },
  };
  assert.match(
    formMarkup(renderDelivery(rehearsal, rehearsalWithSubmit)),
    /aria-label="Estimate request"[^>]*data-collects-data="true"/,
  );

  const active = activeDeliveryFixture();
  const activeForm = active.components.find((component) => component.id === formId)!;
  (activeForm.configuration_payload.privacy as Record<string, unknown>).policy_destination =
    "http://localhost/privacy";
  const activeConfiguration = performanceLocalDeliveryConfiguration(active)!;
  assert.doesNotMatch(
    renderDelivery(active, activeConfiguration),
    /class="performanceLocalEstimateForm"/,
  );
});

test("active public rendering requires approved production identity, readiness, export, and activation audits", () => {
  const active = activeDeliveryFixture();
  assert.equal(validate(active, "active"), null);
  assert.ok(performanceLocalDeliveryConfiguration(active));

  const draftOnPublicRoute = deliveryFixture("inactive_draft_preview");
  draftOnPublicRoute.mode = "active";
  draftOnPublicRoute.non_active_label = null;
  assert.match(validate(draftOnPublicRoute, "active") ?? "", /approved materialization/);

  const missingActivation = clone(active);
  missingActivation.audit_history = missingActivation.audit_history.filter(
    (audit) => audit.action_type !== "website_configuration_activated",
  );
  assert.match(validate(missingActivation, "active") ?? "", /activation audits/);

  const noPublicExport = clone(active);
  noPublicExport.export_eligibility.eligible = false;
  noPublicExport.export_eligibility.identity = null;
  noPublicExport.export_eligibility.blockers = [{
    code: "publication_authorization_missing",
    field: "public_export",
    reason: "Publication authorization is required before export.",
  }];
  assert.equal(validate(noPublicExport, "active"), null);
});

function deliveryFixture(mode: PerformanceLocalDeliveryMode): PerformanceLocalDeliveryRead {
  const components = [
    formComponent(),
    bannerComponent(),
    stickyComponent(),
  ];
  const readiness = blockedReadiness();
  return {
    renderer_contract: "performance-local-delivery@1",
    mode,
    non_active_label: mode === "active"
      ? null
      : mode === "inactive_draft_preview"
        ? "DRAFT PREVIEW — NOT ACTIVE"
        : "ACTIVATION REHEARSAL — DISPOSABLE",
    page: page(),
    composition: composition(),
    theme_family: {
      id: 1,
      family_key: "performance-local",
      display_name: "Performance Local",
      description: "Source-defined local service delivery.",
      provider_source_identity: "project-atlas",
      lifecycle_status: "registered",
      created_by: "Operator",
      retired_by: null,
      retired_at: null,
      integrity_fingerprint: "a".repeat(64),
      created_at: "2026-08-15T10:00:00Z",
      updated_at: "2026-08-15T10:00:00Z",
    },
    theme_version: {
      id: 3,
      theme_family_id: 1,
      version: 3,
      lifecycle_status: "preview_candidate",
      production_ready: false,
      source_commit: "d".repeat(40),
      compatibility_identity: "b".repeat(64),
      supported_component_contracts: clone(PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS) as Record<string, unknown>[],
      created_by: "Operator",
      retired_by: null,
      retired_at: null,
      supersedes_theme_family_version_id: 1,
      integrity_fingerprint: "c".repeat(64),
      created_at: "2026-08-15T10:01:00Z",
      updated_at: "2026-08-15T10:01:00Z",
    },
    website_configuration: {
      id: configurationId,
      website_id: websiteId,
      business_id: businessId,
      theme_family_version_id: 3,
      configuration_key: "performance-local-v3-draft",
      version: 2,
      lifecycle_status: "draft",
      created_by: "Operator",
      updated_by: "Operator",
      creation_rationale: "Exact V3 rehearsal fixture.",
      approved_by: null,
      approved_at: null,
      activated_by: null,
      activated_at: null,
      rollback_by: null,
      rollback_at: null,
      materialized_theme_id: null,
      website_theme_selection_id: null,
      supersedes_configuration_id: 1,
      integrity_fingerprint: "e".repeat(64),
      created_at: "2026-08-15T10:02:00Z",
      updated_at: "2026-08-15T10:02:00Z",
    },
    components,
    audit_history: creationAudits(components),
    governed_actions: {
      phone_display: "(555) 010-0200",
      call_destination: "tel:+15550100200",
      call_label: "Call",
      estimate_label: "Request Estimate",
      estimate_destination_component_configuration_id: formId,
      desktop_header_actions_enabled: true,
      mobile_sticky_actions_enabled: true,
      desktop_header_estimate_destination_component_configuration_id: formId,
      mobile_sticky_estimate_destination_component_configuration_id: formId,
    },
    form_readiness: readiness,
    export_eligibility: {
      eligible: false,
      mode: mode === "activation_rehearsal" ? "internal_rehearsal" : "public",
      identity: null,
      blockers: [{ code: "form_not_ready", field: "form_readiness", reason: "Form is blocked." }],
    },
    renderer_result: {
      status: "ready",
      result_code: "renderer_ready",
      evaluated_page_id: generatedPageId,
    },
    blockers: readiness.blockers.map((blocker) => ({
      code: blocker.code,
      category: blocker.field.startsWith("privacy") ? "privacy" as const : "form" as const,
      reason: blocker.reason,
    })),
  };
}

function activatedRehearsalFixture(): PerformanceLocalDeliveryRead {
  const delivery = configuredDelivery("activation_rehearsal", true);
  delivery.theme_version.lifecycle_status = "preview_candidate";
  delivery.theme_version.production_ready = false;
  return delivery;
}

function activeDeliveryFixture(): PerformanceLocalDeliveryRead {
  const delivery = configuredDelivery("active", false);
  delivery.theme_version.lifecycle_status = "approved";
  delivery.theme_version.production_ready = true;
  delivery.audit_history.push(audit(20, "family_version_approved", "version", 3));
  return delivery;
}

function configuredDelivery(
  mode: "active" | "activation_rehearsal",
  testOnly: boolean,
): PerformanceLocalDeliveryRead {
  const delivery = deliveryFixture(mode);
  delivery.website_configuration.lifecycle_status = "active";
  delivery.website_configuration.approved_by = "Disposable Operator";
  delivery.website_configuration.approved_at = "2026-08-15T11:00:00Z";
  delivery.website_configuration.activated_by = "Disposable Operator";
  delivery.website_configuration.activated_at = "2026-08-15T11:01:00Z";
  delivery.website_configuration.materialized_theme_id = 71;
  delivery.website_configuration.website_theme_selection_id = 81;
  delivery.components.forEach((component) => {
    component.activation_identity = "Disposable Operator";
    component.activated_at = "2026-08-15T11:01:00Z";
  });
  const form = delivery.components.find((component) => component.id === formId)!;
  form.approval_identity = "form-audit-v3";
  form.configuration_payload = configuredFormPayload(testOnly);
  delivery.form_readiness = readyReadiness(testOnly);
  delivery.renderer_result = {
    status: "ready",
    result_code: "renderer_ready",
    evaluated_page_id: generatedPageId,
  };
  delivery.export_eligibility = {
    eligible: true,
    mode: mode === "active" ? "public" : "internal_rehearsal",
    identity: { website_configuration_id: configurationId },
    blockers: [],
  };
  delivery.blockers = [];
  delivery.audit_history.push(
    audit(21, "website_configuration_approved", "configuration", configurationId),
    audit(22, "website_configuration_activated", "configuration", configurationId),
    ...delivery.components.map((component, index) =>
      audit(30 + index, "component_activated", "component", component.id)),
  );
  return delivery;
}

function formComponent(): WebsiteThemeComponentConfigurationRead {
  return componentConfiguration(
    formId,
    "compact_estimate_form",
    "performance-local:compact-estimate-form-v3",
    disabledFormPayload(),
    null,
    null,
  );
}

function bannerComponent(): WebsiteThemeComponentConfigurationRead {
  return componentConfiguration(
    bannerId,
    "campaign_banner",
    "performance-local:evergreen-estimate-banner-v3",
    {
      intent: "evergreen_conversion",
      message: "Request an Estimate",
      cta_label: "Request Estimate",
      approval_identity: "banner-approval-v3",
    },
    formId,
    "banner-approval-v3",
  );
}

function stickyComponent(): WebsiteThemeComponentConfigurationRead {
  return componentConfiguration(
    stickyId,
    "sticky_mobile_action_bar",
    "performance-local:sticky-call-estimate-actions-v3",
    {
      call_source: "governed_website_identity",
      call_label: "Call",
      estimate_label: "Request Estimate",
      desktop_sticky_header: true,
      mobile_sticky_bottom: true,
      hide_while_hero_actions_visible: true,
      hide_while_navigation_open: true,
      protect_form_focus: true,
      safe_area_support: true,
      prevent_content_obstruction: true,
    },
    formId,
    "sticky-approval-v3",
  );
}

function componentConfiguration(
  id: number,
  key: string,
  instanceKey: string,
  payload: Record<string, unknown>,
  destinationId: number | null,
  approvalIdentity: string | null,
): WebsiteThemeComponentConfigurationRead {
  const contract = PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS.find(
    (candidate) => candidate.component_key === key,
  )!;
  return {
    id,
    website_theme_configuration_id: configurationId,
    website_id: websiteId,
    planned_page_id: null,
    theme_family_version_id: 3,
    component_instance_key: instanceKey,
    component_key: key,
    component_contract_version: 3,
    revision: 1,
    scope_type: "website_default",
    lifecycle_status: "current",
    enabled: true,
    variant: contract.variant,
    placement: contract.placement,
    responsive_visibility: clone(contract.responsive_visibility) as Record<string, boolean>,
    configuration_payload: payload,
    effective_at: null,
    expires_at: null,
    approval_identity: approvalIdentity,
    created_by: "Operator",
    updated_by: "Operator",
    activation_identity: null,
    activated_at: null,
    rollback_identity: null,
    rollback_at: null,
    destination_component_configuration_id: destinationId,
    overrides_component_configuration_id: null,
    supersedes_component_configuration_id: null,
    integrity_fingerprint: String(id % 10).repeat(64),
    created_at: "2026-08-15T10:03:00Z",
    updated_at: "2026-08-15T10:03:00Z",
  };
}

function disabledFormPayload(): Record<string, unknown> {
  return {
    submission_state: "disabled_pending_provider_configuration",
    fields: formFields(),
    submit_label: "Request Estimate",
    preview_notice: "Preview only. Information entered here is not submitted or saved.",
    provider: {
      provider_key: null,
      destination: null,
      provider_secret_reference: null,
      test_only: false,
    },
    privacy: {
      policy_destination: null,
      consent_mode: null,
      consent_text: null,
      consent_text_version: null,
    },
    retention: { duration: null, deletion_expiration_behavior: null },
    spam: { strategy: null, configuration_reference: null },
    success_behavior: null,
    failure_behavior: null,
    security: {
      same_origin_policy: null,
      csrf_policy: null,
      request_size_limit_bytes: null,
      idempotency_strategy: null,
    },
    audit_identity: null,
  };
}

function configuredFormPayload(testOnly: boolean): Record<string, unknown> {
  return {
    ...disabledFormPayload(),
    submission_state: testOnly ? "rehearsal_ready" : "production_configured",
    preview_notice: testOnly
      ? "Disposable synthetic rehearsal. Submitted values are discarded."
      : "Your request is sent through the governed secure gateway.",
    provider: {
      provider_key: null,
      destination: null,
      provider_secret_reference: null,
      test_only: testOnly,
    },
    privacy: {
      policy_destination: "/privacy",
      consent_mode: "not_required",
      consent_text: null,
      consent_text_version: null,
    },
    retention: {
      duration: "synthetic-session-only",
      deletion_expiration_behavior: "discard-immediately",
    },
    spam: {
      strategy: testOnly ? "synthetic_test" : "proof_of_work",
      configuration_reference: null,
    },
    success_behavior: "Show a safe accepted message.",
    failure_behavior: "Show a safe generic failure message.",
    security: {
      same_origin_policy: "exact_origin",
      csrf_policy: "origin_and_token",
      request_size_limit_bytes: 8192,
      idempotency_strategy: "required_header",
    },
    audit_identity: "form-audit-v3",
  };
}

function formFields(): Record<string, unknown>[] {
  const definitions = [
    ["name", "Name", true, "input", "text", 1, 160, "nonempty_text", 1, "contact_name", "half"],
    ["phone", "Phone", true, "input", "tel", 2, 40, "phone", 6, "contact_phone", "half"],
    ["postal-code", "ZIP code", true, "input", "text", 3, 20, "postal_code", 3, "postal_code", "half"],
    ["requested-service", "Requested service", true, "input", "text", 4, 160, "nonempty_text", 1, "requested_service", "half"],
    ["message", "Optional message", false, "textarea", "text", 5, 1000, "free_text", 0, "message", "full"],
  ] as const;
  return definitions.map(([key, label, required, control, inputType, order, maximum, rule, minimum, mapping, layout]) => ({
    field_key: key,
    label,
    required,
    control,
    input_type: inputType,
    order,
    accessibility_label: label,
    autocomplete_policy: "off",
    maximum_length: maximum,
    validation_contract: {
      rule,
      minimum_length: minimum,
      maximum_length: maximum,
    },
    responsive_layout: layout,
    provider_mapping: mapping,
  }));
}

function blockedReadiness(): PerformanceLocalFormReadinessRead {
  const blockers = [
    { code: "missing_provider", field: "provider.provider_key", reason: "A governed provider is required." },
    { code: "missing_privacy", field: "privacy.policy_destination", reason: "An approved privacy destination is required." },
    { code: "missing_retention", field: "retention.duration", reason: "An approved retention duration is required." },
    { code: "missing_spam", field: "spam.strategy", reason: "An anti-spam strategy is required." },
    { code: "missing_success", field: "success_behavior", reason: "A success behavior is required." },
    { code: "missing_failure", field: "failure_behavior", reason: "A failure behavior is required." },
    { code: "missing_audit", field: "audit_identity", reason: "An audit identity is required." },
  ];
  return {
    status: "blocked",
    can_submit: false,
    submission_state: "disabled_pending_provider_configuration",
    component_configuration_id: formId,
    provider_state: {
      provider_key: null,
      destination_configured: false,
      adapter_registered: false,
      test_only: false,
    },
    privacy: {
      destination_configured: false,
      consent_mode: null,
      consent_text_version: null,
      ready: false,
    },
    retention: {
      duration_configured: false,
      deletion_behavior_configured: false,
      ready: false,
    },
    spam: { strategy: null, ready: false },
    behavior: { success_configured: false, failure_configured: false, ready: false },
    security: {
      secret_reference_configured: false,
      same_origin_policy: null,
      csrf_policy: null,
      csrf_token: null,
      request_size_limit_bytes: null,
      idempotency_strategy: null,
      ready: false,
    },
    audit_identity: null,
    blockers,
  };
}

function readyReadiness(testOnly: boolean): PerformanceLocalFormReadinessRead {
  return {
    status: "ready",
    can_submit: true,
    submission_state: testOnly ? "rehearsal_ready" : "production_configured",
    component_configuration_id: formId,
    provider_state: {
      provider_key: null,
      destination_configured: true,
      adapter_registered: true,
      test_only: testOnly,
    },
    privacy: {
      destination_configured: true,
      consent_mode: "not_required",
      consent_text_version: null,
      ready: true,
    },
    retention: {
      duration_configured: true,
      deletion_behavior_configured: true,
      ready: true,
    },
    spam: { strategy: testOnly ? "synthetic_test" : "proof_of_work", ready: true },
    behavior: { success_configured: true, failure_configured: true, ready: true },
    security: {
      secret_reference_configured: true,
      same_origin_policy: "exact_origin",
      csrf_policy: "origin_and_token",
      csrf_token: "a".repeat(64),
      request_size_limit_bytes: 8192,
      idempotency_strategy: "required_header",
      ready: true,
    },
    audit_identity: "form-audit-v3",
    blockers: [],
  };
}

function creationAudits(
  components: WebsiteThemeComponentConfigurationRead[],
): ThemeConfigurationAuditIdentityRead[] {
  return [
    audit(1, "family_registered", "family", 1),
    audit(2, "family_version_registered", "version", 3),
    audit(3, "website_configuration_revision_created", "configuration", configurationId),
    ...components.map((component, index) =>
      audit(4 + index, "component_created", "component", component.id)),
  ];
}

function audit(
  id: number,
  actionType: string,
  target: "family" | "version" | "configuration" | "component",
  targetId: number,
): ThemeConfigurationAuditIdentityRead {
  return {
    id,
    theme_family_id: target === "family" ? targetId : null,
    theme_family_version_id: target === "version" ? targetId : null,
    website_theme_configuration_id: target === "configuration" ? targetId : null,
    component_configuration_id: target === "component" ? targetId : null,
    action_type: actionType,
    actor: "Operator",
    rationale: "Exact fixture audit.",
    snapshot: {},
    snapshot_hash: (id % 10).toString().repeat(64),
    created_at: "2026-08-15T10:04:00Z",
  };
}

function page(): GeneratedPage {
  return {
    id: generatedPageId,
    business_id: businessId,
    website_id: websiteId,
    service_id: 5,
    page_type: "service",
    page_title: "Example approved service",
    page_slug: "example-approved-service",
    generation_status: "generated",
    qa_status: "ready",
    status: "draft",
    created_at: "2026-08-15T09:00:00Z",
    updated_at: "2026-08-15T09:00:00Z",
  };
}

function composition(): PageComposition {
  return {
    id: 801,
    website_id: websiteId,
    site_plan_id: 901,
    planned_page_id: plannedPageId,
    generated_page_id: generatedPageId,
    composition_version: 8,
    generated_components: [],
    operator_decisions: [],
    effective_components: [
      semanticComponent("final-cta-1", "final_cta", "main", {
        heading: "Ready to get started?",
        body: "Use an approved contact pathway.",
      }),
    ],
    source_snapshot: {},
    source_hash: "f".repeat(64),
    resolved_theme: selectedTheme(websiteId),
    status: "current",
    validation_errors: [],
    generated_at: "2026-08-15T09:05:00Z",
  };
}

function semanticComponent(
  instanceKey: string,
  componentKey: string,
  region: string,
  resolvedData: Record<string, unknown>,
): PageComponentInstance {
  return {
    instance_key: instanceKey,
    component_key: componentKey,
    contract_version: 2,
    region,
    position: 1,
    variant: "default",
    input_bindings: {},
    resolved_data: resolvedData,
  };
}

function renderDelivery(
  delivery: PerformanceLocalDeliveryRead,
  configuration: NonNullable<ReturnType<typeof performanceLocalDeliveryConfiguration>>,
): string {
  return renderToStaticMarkup(
    <StaticRouter location={performanceLocalDeliveryPagePath(
      delivery.mode,
      generatedPageId,
      delivery.mode === "active" ? null : configurationId,
    )}>
      <PerformanceLocalRenderer
        campaign={configuration.campaign}
        composition={delivery.composition}
        estimateForm={configuration.estimateForm}
        formSubmission={configuration.formSubmission}
        governedContact={configuration.governedContact}
        page={delivery.page}
        rendererIdentity={configuration.rendererIdentity}
        stickyActions={configuration.stickyActions}
        toggles={configuration.toggles}
        previewedAt={new Date("2026-08-15T12:00:00Z")}
      />
    </StaticRouter>,
  );
}

function validate(
  delivery: PerformanceLocalDeliveryRead,
  expectedMode: PerformanceLocalDeliveryMode,
): string | null {
  return performanceLocalDeliveryValidationError(
    delivery,
    expectedMode,
    generatedPageId,
    expectedMode === "active" ? null : configurationId,
  );
}

function bannerMarkup(markup: string): string {
  const match = markup.match(/<aside class="performanceLocalCampaign[\s\S]*?<\/aside>/);
  assert.ok(match, "Expected one visible campaign banner.");
  return match[0];
}

function formMarkup(markup: string): string {
  const match = markup.match(/<form[^>]*class="performanceLocalEstimateForm"[\s\S]*?<\/form>/);
  assert.ok(match, "Expected one visible governed estimate form.");
  return match[0];
}

function visibleText(markup: string): string {
  return markup
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

function source(path: string): string {
  return readFileSync(resolve(process.cwd(), path), "utf8");
}

function clone<T>(value: T): T {
  return structuredClone(value);
}
