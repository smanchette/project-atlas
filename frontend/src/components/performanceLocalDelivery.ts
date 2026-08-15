import {
  performanceLocalOptionalConfiguration,
} from "./performanceLocalTheme";
import {
  PERFORMANCE_LOCAL_V3_RENDERER_CONTRACT,
  PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY,
  PERFORMANCE_LOCAL_V3_THEME_VERSION,
  performanceLocalV3ComponentContract,
} from "./performanceLocalThemeV3";
import {
  performanceLocalFormDomId,
  type PerformanceLocalCampaign,
  type PerformanceLocalEstimateField,
  type PerformanceLocalEstimateFieldKey,
  type PerformanceLocalEstimateFormConfiguration,
  type PerformanceLocalFormSubmission,
  type PerformanceLocalGovernedContact,
  type PerformanceLocalRendererIdentity,
  type PerformanceLocalRuntimeToggles,
  type PerformanceLocalStickyActionConfiguration,
} from "./PerformanceLocalRenderer";
import type {
  PerformanceLocalDeliveryMode,
  PerformanceLocalDeliveryRead,
  WebsiteThemeComponentConfigurationRead,
} from "../types";

const NON_ACTIVE_LABELS = Object.freeze({
  active: null,
  inactive_draft_preview: "DRAFT PREVIEW — NOT ACTIVE",
  activation_rehearsal: "ACTIVATION REHEARSAL — DISPOSABLE",
} as const);

const EXPECTED_FORM_FIELDS = Object.freeze([
  ["name", "Name", true, "input", "text", 1],
  ["phone", "Phone", true, "input", "tel", 2],
  ["postal-code", "ZIP code", true, "input", "text", 3],
  ["requested-service", "Requested service", true, "input", "text", 4],
  ["message", "Optional message", false, "textarea", "text", 5],
] as const);

export type PerformanceLocalDeliveryConfiguration = Readonly<{
  campaign: PerformanceLocalCampaign | null;
  estimateForm: PerformanceLocalEstimateFormConfiguration;
  formSubmission: PerformanceLocalFormSubmission;
  governedContact: PerformanceLocalGovernedContact | null;
  rendererIdentity: PerformanceLocalRendererIdentity;
  stickyActions: PerformanceLocalStickyActionConfiguration;
  toggles: PerformanceLocalRuntimeToggles;
}>;

export function performanceLocalDeliveryPagePath(
  mode: PerformanceLocalDeliveryMode,
  pageId: number,
  configurationId?: number | null,
): string {
  requirePositiveInteger(pageId, "Generated Page identity");
  if (mode === "active") return `/delivery/generated-pages/${pageId}`;
  requirePositiveInteger(configurationId, "Website Theme configuration identity");
  const segment = mode === "inactive_draft_preview" ? "local-preview" : "rehearsal";
  return `/delivery/${segment}/configurations/${configurationId}/generated-pages/${pageId}`;
}

export function performanceLocalDeliveryApiPath(
  mode: PerformanceLocalDeliveryMode,
  pageId: number,
  configurationId?: number | null,
): string {
  requirePositiveInteger(pageId, "Generated Page identity");
  if (mode === "active") return `/api/theme-delivery/active/generated-pages/${pageId}`;
  requirePositiveInteger(configurationId, "Website Theme configuration identity");
  const segment = mode === "inactive_draft_preview" ? "local-preview" : "rehearsal";
  return `/api/theme-delivery/${segment}/configurations/${configurationId}/generated-pages/${pageId}`;
}

/**
 * Rejects any delivery response whose server-resolved identity is not exact.
 * This function deliberately validates identity and scope, while the server
 * remains authoritative for publication, media, QA, provider, and export
 * readiness represented by renderer_result and its blocker lists.
 */
export function performanceLocalDeliveryValidationError(
  delivery: PerformanceLocalDeliveryRead,
  expectedMode: PerformanceLocalDeliveryMode,
  expectedPageId: number,
  expectedConfigurationId?: number | null,
): string | null {
  if (delivery.renderer_contract !== PERFORMANCE_LOCAL_V3_RENDERER_CONTRACT) {
    return "The delivery renderer contract is not supported.";
  }
  if (delivery.mode !== expectedMode || delivery.non_active_label !== NON_ACTIVE_LABELS[expectedMode]) {
    return "The server-resolved delivery mode or safety label does not match this route.";
  }
  if (
    !positiveInteger(expectedPageId) ||
    delivery.page.id !== expectedPageId ||
    delivery.composition.generated_page_id !== expectedPageId ||
    delivery.renderer_result.evaluated_page_id !== expectedPageId
  ) {
    return "The delivery result does not belong to the requested Generated Page.";
  }
  if (
    !positiveInteger(delivery.page.website_id) ||
    delivery.page.website_id !== delivery.composition.website_id ||
    delivery.page.website_id !== delivery.website_configuration.website_id ||
    delivery.page.business_id !== delivery.website_configuration.business_id
  ) {
    return "The delivery result crosses a Website or Business ownership boundary.";
  }
  if (
    !Array.isArray(delivery.composition.validation_errors) ||
    !positiveInteger(delivery.composition.id) ||
    !positiveInteger(delivery.composition.planned_page_id) ||
    !hexFingerprint(delivery.composition.source_hash)
  ) {
    return "The semantic composition identity is malformed.";
  }
  const compositionBlocked = delivery.composition.status !== "current" ||
    delivery.composition.validation_errors.length !== 0;
  if (compositionBlocked) {
    const governedBlockers = delivery.blockers.filter(
      (blocker) => blocker.category === "media" || blocker.category === "qa",
    );
    if (
      delivery.renderer_result.status !== "blocked" ||
      governedBlockers.length === 0 ||
      delivery.composition.validation_errors.some(
        (reason) => !governedBlockers.some((blocker) => blocker.reason === reason),
      )
    ) {
      return "A non-current composition may appear only as an exact governed blocked result.";
    }
  }

  const family = delivery.theme_family;
  const version = delivery.theme_version;
  const configuration = delivery.website_configuration;
  if (
    family.family_key !== "performance-local" ||
    family.lifecycle_status !== "registered" ||
    version.theme_family_id !== family.id ||
    version.version !== PERFORMANCE_LOCAL_V3_THEME_VERSION ||
    !hexCommit(version.source_commit) ||
    !hexFingerprint(family.integrity_fingerprint) ||
    !hexFingerprint(version.integrity_fingerprint) ||
    !hexFingerprint(version.compatibility_identity) ||
    !sameCanonicalJson(
      version.supported_component_contracts,
      PERFORMANCE_LOCAL_V3_SERIALIZED_COMPONENT_CONTRACTS,
    )
  ) {
    return "The Performance Local V3 source identity or canonical component contract is invalid.";
  }
  if (
    configuration.theme_family_version_id !== version.id ||
    !positiveInteger(configuration.id) ||
    !positiveInteger(configuration.version) ||
    !hexFingerprint(configuration.integrity_fingerprint)
  ) {
    return "The Website Theme configuration identity is invalid.";
  }
  if (expectedMode !== "active" && configuration.id !== expectedConfigurationId) {
    return "The explicit non-active route does not identify this Website Theme configuration.";
  }

  if (expectedMode === "active") {
    const resolvedTheme = delivery.composition.resolved_theme;
    if (
      version.lifecycle_status !== "approved" ||
      version.production_ready !== true ||
      configuration.lifecycle_status !== "active" ||
      !positiveInteger(configuration.materialized_theme_id) ||
      !positiveInteger(configuration.website_theme_selection_id) ||
      configuration.approved_by === null ||
      configuration.approved_at === null ||
      configuration.activated_by === null ||
      configuration.activated_at === null ||
      configuration.rollback_by !== null ||
      configuration.rollback_at !== null ||
      resolvedTheme.website_id !== configuration.website_id ||
      resolvedTheme.theme?.id !== configuration.materialized_theme_id ||
      resolvedTheme.selection?.id !== configuration.website_theme_selection_id ||
      resolvedTheme.selection?.status !== "active" ||
      resolvedTheme.selection.website_id !== configuration.website_id ||
      resolvedTheme.selection.theme_id !== configuration.materialized_theme_id
    ) {
      return "Active delivery requires the exact approved materialization and sole active selection.";
    }
  } else if (expectedMode === "inactive_draft_preview") {
    if (
      version.lifecycle_status !== "preview_candidate" ||
      version.production_ready !== false ||
      configuration.lifecycle_status !== "draft" ||
      configuration.materialized_theme_id !== null ||
      configuration.website_theme_selection_id !== null ||
      configuration.activated_by !== null ||
      configuration.activated_at !== null ||
      configuration.rollback_by !== null ||
      configuration.rollback_at !== null
    ) {
      return "Inactive preview requires the exact unmaterialized V3 preview candidate draft.";
    }
  } else {
    if (version.lifecycle_status !== "preview_candidate" || version.production_ready !== false) {
      return "Activation rehearsal requires the non-production V3 preview candidate identity.";
    }
    if (configuration.lifecycle_status === "draft") {
      if (
        configuration.materialized_theme_id !== null ||
        configuration.website_theme_selection_id !== null ||
        configuration.activated_by !== null ||
        configuration.activated_at !== null ||
        configuration.rollback_by !== null ||
        configuration.rollback_at !== null
      ) return "Pre-activation rehearsal must remain an exact unmaterialized draft.";
    } else if (configuration.lifecycle_status === "active") {
      const resolvedTheme = delivery.composition.resolved_theme;
      if (
        !positiveInteger(configuration.materialized_theme_id) ||
        !positiveInteger(configuration.website_theme_selection_id) ||
        configuration.approved_by === null ||
        configuration.approved_at === null ||
        configuration.activated_by === null ||
        configuration.activated_at === null ||
        configuration.rollback_by !== null ||
        configuration.rollback_at !== null ||
        resolvedTheme.website_id !== configuration.website_id ||
        resolvedTheme.theme?.id !== configuration.materialized_theme_id ||
        resolvedTheme.selection?.id !== configuration.website_theme_selection_id ||
        resolvedTheme.selection?.status !== "active" ||
        resolvedTheme.selection.website_id !== configuration.website_id ||
        resolvedTheme.selection.theme_id !== configuration.materialized_theme_id
      ) return "Activated rehearsal lacks its exact disposable Theme materialization and selection.";
    } else {
      return "Rehearsal delivery accepts only the exact draft or activated disposable identity.";
    }
  }

  const componentError = componentGraphValidationError(delivery);
  if (componentError) return componentError;
  const auditError = auditValidationError(delivery, expectedMode);
  if (auditError) return auditError;
  const formError = formReadinessIdentityError(delivery);
  if (formError) return formError;

  if (
    !["ready", "blocked"].includes(delivery.renderer_result.status) ||
    !exactText(delivery.renderer_result.result_code)
  ) {
    return "The server renderer result is malformed.";
  }
  if (
    delivery.export_eligibility.eligible !== (delivery.export_eligibility.identity !== null) ||
    (delivery.export_eligibility.eligible && delivery.export_eligibility.blockers.length !== 0) ||
    (!delivery.export_eligibility.eligible && delivery.export_eligibility.blockers.length === 0)
  ) return "Theme export eligibility and its governed identity/blockers are inconsistent.";
  if (expectedMode === "inactive_draft_preview" && (
    delivery.export_eligibility.eligible ||
    delivery.export_eligibility.mode !== "public" ||
    delivery.export_eligibility.identity !== null
  )) {
    return "An inactive draft cannot expose public export eligibility.";
  }
  if (expectedMode === "active" && delivery.export_eligibility.mode !== "public") {
    return "Active delivery cannot consume an internal rehearsal export identity.";
  }
  if (expectedMode === "active" && delivery.renderer_result.status === "ready" && (
    delivery.form_readiness.status !== "ready" ||
    delivery.form_readiness.can_submit !== true
  )) {
    return "Active public rendering requires ready governed form delivery.";
  }
  if (expectedMode === "activation_rehearsal" && delivery.export_eligibility.mode !== "internal_rehearsal") {
    return "Activation rehearsal may expose only an internal rehearsal export identity.";
  }
  if (expectedMode === "activation_rehearsal") {
    const activated = configuration.lifecycle_status === "active";
    if (!activated && (
      delivery.export_eligibility.eligible || delivery.export_eligibility.identity !== null
    )) return "Pre-activation rehearsal cannot expose an internal export identity.";
    if (activated && delivery.renderer_result.status === "ready" &&
      delivery.form_readiness.status !== "ready") {
      return "Ready activated rehearsal requires ready governed form delivery.";
    }
  }
  return null;
}

export function performanceLocalDeliveryConfiguration(
  delivery: PerformanceLocalDeliveryRead,
): PerformanceLocalDeliveryConfiguration | null {
  const formComponent = effectiveComponent(delivery, "compact_estimate_form");
  const stickyComponent = effectiveComponent(delivery, "sticky_mobile_action_bar");
  const bannerComponent = effectiveComponent(delivery, "campaign_banner");
  if (!formComponent || !stickyComponent || !formComponent.enabled || !stickyComponent.enabled) return null;

  const estimateForm = estimateFormConfiguration(delivery, formComponent);
  if (!estimateForm) return null;
  const formDestination = `#${performanceLocalFormDomId(formComponent.id)}`;
  const governed = delivery.governed_actions;
  if (
    governed.estimate_destination_component_configuration_id !== formComponent.id ||
    governed.desktop_header_estimate_destination_component_configuration_id !== formComponent.id ||
    governed.mobile_sticky_estimate_destination_component_configuration_id !== formComponent.id
  ) return null;

  const stickyPayload = stickyComponent.configuration_payload;
  const callLabel = exactText(stickyPayload.call_label);
  const estimateLabel = exactText(stickyPayload.estimate_label);
  if (
    stickyComponent.destination_component_configuration_id !== formComponent.id ||
    stickyPayload.call_source !== "governed_website_identity" ||
    !callLabel ||
    !estimateLabel ||
    callLabel !== governed.call_label ||
    estimateLabel !== governed.estimate_label ||
    stickyPayload.desktop_sticky_header !== governed.desktop_header_actions_enabled ||
    stickyPayload.mobile_sticky_bottom !== governed.mobile_sticky_actions_enabled
  ) return null;
  for (const safety of [
    "hide_while_hero_actions_visible",
    "hide_while_navigation_open",
    "protect_form_focus",
    "safe_area_support",
    "prevent_content_obstruction",
  ]) {
    if (stickyPayload[safety] !== true) return null;
  }

  const phoneDisplay = exactText(governed.phone_display);
  const callDestination = exactText(governed.call_destination);
  if (Boolean(phoneDisplay) !== Boolean(callDestination)) return null;
  const governedContact = phoneDisplay && callDestination
    ? Object.freeze({
        callDestination,
        phoneDisplay,
        websiteId: delivery.website_configuration.website_id,
      })
    : null;

  const campaign = bannerComponent?.enabled
    ? campaignConfiguration(delivery, bannerComponent, formDestination, formComponent.id)
    : null;
  if (bannerComponent?.enabled && !campaign) return null;

  const formSubmission: PerformanceLocalFormSubmission = delivery.form_readiness.status === "ready"
    ? Object.freeze({
        endpoint: `/api/websites/${delivery.website_configuration.website_id}/forms/${formComponent.id}/submissions`,
        readiness: delivery.form_readiness,
      })
    : Object.freeze({ endpoint: null, readiness: delivery.form_readiness });
  const configurationId = delivery.mode === "active" ? null : delivery.website_configuration.id;
  const rendererIdentity: PerformanceLocalRendererIdentity = Object.freeze({
    componentVersion: "3",
    deliveryMode: delivery.mode,
    exposeDiagnostics: false,
    themeCompatibility: PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY,
    themeVersion: PERFORMANCE_LOCAL_V3_THEME_VERSION,
    destinationForGeneratedPageId: (pageId: number) =>
      performanceLocalDeliveryPagePath(delivery.mode, pageId, configurationId),
  });
  const semanticKeys = new Set(
    delivery.composition.effective_components.map((component) => component.component_key),
  );
  const toggles: PerformanceLocalRuntimeToggles = Object.freeze({
    campaignBanner: Boolean(campaign),
    compactEstimateForm: true,
    estimateAction: true,
    finalCta: semanticKeys.has("final_cta"),
    headerEstimateCta: governed.desktop_header_actions_enabled,
    phoneAction: Boolean(governedContact),
    stickyActionBar: governed.mobile_sticky_actions_enabled,
    trustStrip: semanticKeys.has("trust_license"),
  });

  return Object.freeze({
    campaign,
    estimateForm,
    formSubmission,
    governedContact,
    rendererIdentity,
    stickyActions: Object.freeze({
      callLabel,
      componentConfigurationId: stickyComponent.id,
      desktopHeaderActionsEnabled: governed.desktop_header_actions_enabled,
      destinationComponentConfigurationId: formComponent.id,
      enabled: true,
      estimateLabel,
      mobileStickyActionsEnabled: governed.mobile_sticky_actions_enabled,
    }),
    toggles,
  });
}

function componentGraphValidationError(delivery: PerformanceLocalDeliveryRead): string | null {
  if (!Array.isArray(delivery.components) || delivery.components.length < 2) {
    return "The Website Theme component graph is incomplete.";
  }
  const componentIds = new Set<number>();
  const scopeKeys = new Set<string>();
  for (const component of delivery.components) {
    const contract = performanceLocalV3ComponentContract(component.component_key);
    const scopeKey = `${component.component_key}:${component.scope_type}:${component.planned_page_id ?? "website"}`;
    if (
      !contract ||
      componentIds.has(component.id) ||
      scopeKeys.has(scopeKey) ||
      !positiveInteger(component.id) ||
      !positiveInteger(component.revision) ||
      component.website_theme_configuration_id !== delivery.website_configuration.id ||
      component.website_id !== delivery.website_configuration.website_id ||
      component.theme_family_version_id !== delivery.theme_version.id ||
      component.component_contract_version !== PERFORMANCE_LOCAL_V3_THEME_VERSION ||
      component.lifecycle_status !== "current" ||
      component.placement !== contract.placement ||
      component.variant !== contract.variant ||
      !sameCanonicalJson(component.responsive_visibility, contract.responsive_visibility) ||
      !hexFingerprint(component.integrity_fingerprint) ||
      !safeInstanceKey(component.component_instance_key)
    ) {
      return "A component revision does not match the exact canonical V3 graph identity.";
    }
    if (component.scope_type === "website_default") {
      if (component.planned_page_id !== null) return "A Website-default component contains Page scope.";
    } else if (
      component.scope_type !== "page_override" ||
      component.planned_page_id !== delivery.composition.planned_page_id ||
      !contract.supports_page_override
    ) {
      return "A component Page override crosses the requested Planned Page scope.";
    }
    const activationRequired = delivery.mode === "active" || (
      delivery.mode === "activation_rehearsal" &&
      delivery.website_configuration.lifecycle_status === "active"
    );
    if (activationRequired && (
      !exactText(component.activation_identity) ||
      component.activated_at === null ||
      component.rollback_identity !== null ||
      component.rollback_at !== null
    )) {
      return "An active component lacks exact activation evidence.";
    }
    if (!activationRequired && (
      component.activation_identity !== null ||
      component.activated_at !== null ||
      component.rollback_identity !== null ||
      component.rollback_at !== null
    )) {
      return "A non-active component graph contains activation evidence.";
    }
    const payloadError = componentPayloadValidationError(component);
    if (payloadError) return payloadError;
    componentIds.add(component.id);
    scopeKeys.add(scopeKey);
  }
  if (!effectiveComponent(delivery, "compact_estimate_form") || !effectiveComponent(delivery, "sticky_mobile_action_bar")) {
    return "The exact form and sticky-action component revisions are required.";
  }
  return null;
}

function auditValidationError(
  delivery: PerformanceLocalDeliveryRead,
  mode: PerformanceLocalDeliveryMode,
): string | null {
  if (!Array.isArray(delivery.audit_history)) return "Theme configuration audit history is missing.";
  const componentIds = new Set(delivery.components.map((component) => component.id));
  for (const audit of delivery.audit_history) {
    if (
      !positiveInteger(audit.id) ||
      !hexFingerprint(audit.snapshot_hash) ||
      !exactText(audit.action_type) ||
      !exactText(audit.actor) ||
      (audit.theme_family_id !== null && audit.theme_family_id !== delivery.theme_family.id) ||
      (audit.theme_family_version_id !== null && audit.theme_family_version_id !== delivery.theme_version.id) ||
      (audit.website_theme_configuration_id !== null &&
        audit.website_theme_configuration_id !== delivery.website_configuration.id) ||
      (audit.component_configuration_id !== null && !componentIds.has(audit.component_configuration_id))
    ) {
      return "Theme delivery audit identity is malformed or crosses configuration scope.";
    }
  }
  const hasAudit = (
    actionType: string,
    target: "family" | "version" | "configuration" | "component",
    targetId: number,
  ) => delivery.audit_history.some((audit) =>
    audit.action_type === actionType &&
    (target === "family"
      ? audit.theme_family_id === targetId
      : target === "version"
        ? audit.theme_family_version_id === targetId
        : target === "configuration"
          ? audit.website_theme_configuration_id === targetId
          : audit.component_configuration_id === targetId),
  );
  if (
    !hasAudit("family_registered", "family", delivery.theme_family.id) ||
    !hasAudit("family_version_registered", "version", delivery.theme_version.id) ||
    !delivery.audit_history.some((audit) =>
      ["website_draft_created", "website_configuration_revision_created"].includes(audit.action_type) &&
      audit.website_theme_configuration_id === delivery.website_configuration.id,
    ) ||
    delivery.components.some((component) => !delivery.audit_history.some((audit) =>
      ["component_created", "component_revision_created"].includes(audit.action_type) &&
      audit.component_configuration_id === component.id,
    ))
  ) return "Theme delivery lacks exact creation audit coverage.";
  if (delivery.theme_version.lifecycle_status === "approved" &&
    !hasAudit("family_version_approved", "version", delivery.theme_version.id)) {
    return "Approved Theme delivery lacks its version approval audit.";
  }
  if (delivery.website_configuration.approved_at !== null &&
    !hasAudit("website_configuration_approved", "configuration", delivery.website_configuration.id)) {
    return "Approved Website configuration lacks its approval audit.";
  }
  const activationRequired = mode === "active" || (
    mode === "activation_rehearsal" &&
    delivery.website_configuration.lifecycle_status === "active"
  );
  if (!activationRequired) return null;
  const configurationActivated = delivery.audit_history.some(
    (audit) => audit.action_type === "website_configuration_activated" &&
      audit.website_theme_configuration_id === delivery.website_configuration.id,
  );
  const activatedComponents = new Set(
    delivery.audit_history
      .filter((audit) => audit.action_type === "component_activated")
      .map((audit) => audit.component_configuration_id),
  );
  if (!configurationActivated || delivery.components.some(
    (component) => !activatedComponents.has(component.id),
  )) {
    return "Active delivery lacks the exact configuration or component activation audits.";
  }
  return null;
}

function formReadinessIdentityError(delivery: PerformanceLocalDeliveryRead): string | null {
  const readiness = delivery.form_readiness;
  const form = effectiveComponent(delivery, "compact_estimate_form");
  if (!form || readiness.component_configuration_id !== form.id) {
    return "Form readiness does not identify the exact effective form revision.";
  }
  if (
    (readiness.status === "ready") !== readiness.can_submit ||
    (readiness.status === "ready" && readiness.blockers.length !== 0) ||
    (readiness.status === "blocked" && readiness.can_submit)
  ) {
    return "Form submission readiness is internally inconsistent.";
  }
  const payload = form.configuration_payload;
  const provider = record(payload.provider);
  const privacy = record(payload.privacy);
  const retention = record(payload.retention);
  const spam = record(payload.spam);
  const security = record(payload.security);
  if (!provider || !privacy || !retention || !spam || !security) {
    return "The V3 form readiness source contract is incomplete.";
  }
  const configuredState = payload.submission_state === "rehearsal_ready" ||
    payload.submission_state === "production_configured";
  const privacyReady = readiness.privacy.destination_configured &&
    readiness.privacy.consent_mode !== null &&
    (readiness.privacy.consent_mode !== "explicit" ||
      readiness.privacy.consent_text_version !== null);
  const retentionReady = readiness.retention.duration_configured &&
    readiness.retention.deletion_behavior_configured;
  const behaviorReady = readiness.behavior.success_configured &&
    readiness.behavior.failure_configured;
  const securityReady = readiness.security.secret_reference_configured &&
    readiness.security.same_origin_policy !== null &&
    readiness.security.csrf_policy !== null &&
    positiveInteger(readiness.security.request_size_limit_bytes) &&
    readiness.security.idempotency_strategy !== null;
  if (
    (!configuredState && payload.submission_state !== "disabled_pending_provider_configuration") ||
    readiness.submission_state !== payload.submission_state ||
    readiness.provider_state.provider_key !== null ||
    provider.provider_key !== null ||
    provider.destination !== null ||
    provider.provider_secret_reference !== null ||
    spam.configuration_reference !== null ||
    readiness.provider_state.destination_configured !== configuredState ||
    readiness.security.secret_reference_configured !== configuredState ||
    readiness.provider_state.test_only !== provider.test_only ||
    readiness.privacy.destination_configured !== Boolean(nullableText(privacy.policy_destination)) ||
    readiness.privacy.consent_mode !== privacy.consent_mode ||
    readiness.privacy.consent_text_version !== nullableText(privacy.consent_text_version) ||
    readiness.retention.duration_configured !== Boolean(nullableText(retention.duration)) ||
    readiness.retention.deletion_behavior_configured !== Boolean(
      nullableText(retention.deletion_expiration_behavior),
    ) ||
    readiness.spam.strategy !== spam.strategy ||
    readiness.behavior.success_configured !== Boolean(nullableText(payload.success_behavior)) ||
    readiness.behavior.failure_configured !== Boolean(nullableText(payload.failure_behavior)) ||
    readiness.security.same_origin_policy !== security.same_origin_policy ||
    readiness.security.csrf_policy !== security.csrf_policy ||
    readiness.security.request_size_limit_bytes !== security.request_size_limit_bytes ||
    readiness.security.idempotency_strategy !== security.idempotency_strategy ||
    readiness.audit_identity !== nullableText(payload.audit_identity) ||
    readiness.privacy.ready !== privacyReady ||
    readiness.retention.ready !== retentionReady ||
    readiness.spam.ready !== (readiness.spam.strategy !== null) ||
    readiness.behavior.ready !== behaviorReady ||
    readiness.security.ready !== securityReady
  ) {
    return "Form readiness does not match its governed provider/privacy/security configuration.";
  }
  return null;
}

function componentPayloadValidationError(
  component: WebsiteThemeComponentConfigurationRead,
): string | null {
  const payload = component.configuration_payload;
  if (component.component_key === "campaign_banner") {
    const common = ["intent", "message", "cta_label", "approval_identity"];
    const timed = ["approved_offer_details", "terms_reference", "start_at", "end_at"];
    const intent = payload.intent;
    if (
      !hasExactKeys(payload, intent === "time_bound_campaign" ? [...common, ...timed] : common) ||
      (intent !== "evergreen_conversion" && intent !== "time_bound_campaign") ||
      !exactText(payload.message) ||
      !exactText(payload.cta_label) ||
      !exactText(payload.approval_identity) ||
      (component.enabled && component.approval_identity !== payload.approval_identity)
    ) return "The campaign banner payload is not the exact approved V3 contract.";
    if (intent === "time_bound_campaign" && (
      !exactText(payload.approved_offer_details) ||
      !exactText(payload.terms_reference) ||
      !exactInstant(payload.start_at) ||
      !exactInstant(payload.end_at) ||
      Date.parse(String(payload.end_at)) <= Date.parse(String(payload.start_at))
    )) return "The time-bound campaign schedule is invalid.";
    return null;
  }
  if (component.component_key === "sticky_mobile_action_bar") {
    const keys = [
      "call_source", "call_label", "estimate_label", "desktop_sticky_header",
      "mobile_sticky_bottom", "hide_while_hero_actions_visible",
      "hide_while_navigation_open", "protect_form_focus", "safe_area_support",
      "prevent_content_obstruction",
    ];
    if (!hasExactKeys(payload, keys) || payload.call_source !== "governed_website_identity") {
      return "The sticky-action payload is not the exact governed V3 contract.";
    }
    if (!exactText(payload.call_label) || !exactText(payload.estimate_label) || keys.slice(3).some(
      (key) => typeof payload[key] !== "boolean",
    )) return "The sticky-action labels or safety states are invalid.";
    return null;
  }
  if (component.component_key === "compact_estimate_form") {
    if (!hasExactKeys(payload, [
      "submission_state", "fields", "submit_label", "preview_notice", "provider", "privacy",
      "retention", "spam", "success_behavior", "failure_behavior", "security", "audit_identity",
    ])) return "The form payload contains an unsupported or missing field.";
    const provider = record(payload.provider);
    const privacy = record(payload.privacy);
    const retention = record(payload.retention);
    const spam = record(payload.spam);
    const security = record(payload.security);
    if (
      !provider || !privacy || !retention || !spam || !security ||
      !hasExactKeys(provider, ["provider_key", "destination", "provider_secret_reference", "test_only"]) ||
      !hasExactKeys(privacy, ["policy_destination", "consent_mode", "consent_text", "consent_text_version"]) ||
      !hasExactKeys(retention, ["duration", "deletion_expiration_behavior"]) ||
      !hasExactKeys(spam, ["strategy", "configuration_reference"]) ||
      !hasExactKeys(security, [
        "same_origin_policy", "csrf_policy", "request_size_limit_bytes", "idempotency_strategy",
      ]) ||
      provider.provider_key !== null ||
      provider.destination !== null ||
      provider.provider_secret_reference !== null ||
      spam.configuration_reference !== null ||
      !Array.isArray(payload.fields) || payload.fields.length !== EXPECTED_FORM_FIELDS.length ||
      !exactText(payload.submit_label) || !exactText(payload.preview_notice)
    ) return "The nested provider-independent form payload is incomplete.";
    for (const [index, field] of payload.fields.entries()) {
      if (!estimateField(field, index)) return "The durable five-field form contract changed.";
    }
    return null;
  }
  return Object.keys(payload).length === 0
    ? null
    : "A non-configured semantic component unexpectedly contains runtime configuration.";
}

function estimateFormConfiguration(
  delivery: PerformanceLocalDeliveryRead,
  component: WebsiteThemeComponentConfigurationRead,
): PerformanceLocalEstimateFormConfiguration | null {
  const payload = component.configuration_payload;
  if (!Array.isArray(payload.fields)) return null;
  const fields = payload.fields.map((field, index) => estimateField(field, index));
  if (fields.some((field) => field === null)) return null;
  const provider = record(payload.provider);
  const privacy = record(payload.privacy);
  if (!provider || !privacy) return null;
  const submissionState = exactText(payload.submission_state);
  const disabled = submissionState === "disabled_pending_provider_configuration";
  const consentMode = privacy.consent_mode;
  const consent = consentMode === "explicit" || consentMode === "not_required"
    ? Object.freeze({
        mode: consentMode,
        privacyPolicyDestination: nullableText(privacy.policy_destination),
        text: consentMode === "explicit" ? nullableText(privacy.consent_text) : null,
        textVersion: consentMode === "explicit" ? nullableText(privacy.consent_text_version) : null,
      })
    : undefined;
  return Object.freeze({
    componentConfigurationId: component.id,
    componentInstanceKey: component.component_instance_key,
    ctaLabel: exactText(delivery.governed_actions.estimate_label),
    fields: fields as PerformanceLocalEstimateField[],
    previewNotice: exactText(payload.preview_notice),
    providerState: Object.freeze({
      canSubmit: delivery.form_readiness.can_submit,
      collectsData: delivery.form_readiness.can_submit,
      destination: null,
      destinationConfigured: delivery.form_readiness.provider_state.destination_configured,
      providerKey: null,
      submissionState,
      testOnly: delivery.form_readiness.provider_state.test_only,
    }),
    consent,
    submitLabel: exactText(payload.submit_label),
    visualState: disabled ? "disabled" : "idle",
  });
}

function campaignConfiguration(
  delivery: PerformanceLocalDeliveryRead,
  component: WebsiteThemeComponentConfigurationRead,
  ctaDestination: string,
  formComponentId: number,
): PerformanceLocalCampaign | null {
  if (component.destination_component_configuration_id !== formComponentId) return null;
  const payload = component.configuration_payload;
  const campaignLabel = exactText(payload.message);
  const ctaLabel = exactText(payload.cta_label);
  const approvalIdentity = exactText(payload.approval_identity);
  if (!campaignLabel || !ctaLabel || !approvalIdentity) return null;
  const common = {
    ...performanceLocalOptionalConfiguration(
      "campaign_banner",
      delivery.website_configuration.website_id,
      campaignLabel,
      { approvalIdentity, campaignLabel, ctaDestination, ctaLabel },
    ),
    approvalIdentity,
    campaignLabel,
    ctaDestination,
    ctaLabel,
    destinationComponentConfigurationId: formComponentId,
    enabled: true,
    websiteId: delivery.website_configuration.website_id,
  };
  if (payload.intent === "evergreen_conversion") {
    return Object.freeze({ ...common, intent: "evergreen_conversion" });
  }
  if (payload.intent !== "time_bound_campaign") return null;
  const startDate = exactText(payload.start_at);
  const endDate = exactText(payload.end_at);
  const termsReference = exactText(payload.terms_reference);
  const offerDetails = exactText(payload.approved_offer_details);
  if (!startDate || !endDate || !termsReference || !offerDetails) return null;
  return Object.freeze({
    ...common,
    intent: "time_bound_campaign",
    startDate,
    endDate,
    termsReference,
    offerDetails,
  });
}

function estimateField(value: unknown, index: number): PerformanceLocalEstimateField | null {
  const field = record(value);
  const expected = EXPECTED_FORM_FIELDS[index];
  const validation = field ? record(field.validation_contract) : null;
  if (
    !field || !validation || !expected ||
    !hasExactKeys(field, [
      "field_key", "label", "required", "control", "input_type", "order",
      "accessibility_label", "autocomplete_policy", "maximum_length",
      "validation_contract", "responsive_layout", "provider_mapping",
    ]) ||
    !hasExactKeys(validation, ["rule", "minimum_length", "maximum_length"]) ||
    field.field_key !== expected[0] ||
    field.label !== expected[1] ||
    field.required !== expected[2] ||
    field.control !== expected[3] ||
    field.input_type !== expected[4] ||
    field.order !== expected[5] ||
    field.accessibility_label !== expected[1] ||
    !["name", "tel", "postal-code", "off"].includes(String(field.autocomplete_policy)) ||
    !positiveInteger(field.maximum_length) ||
    validation.maximum_length !== field.maximum_length ||
    !Number.isSafeInteger(validation.minimum_length) || Number(validation.minimum_length) < 0 ||
    !["nonempty_text", "phone", "postal_code", "free_text"].includes(String(validation.rule)) ||
    (field.responsive_layout !== "half" && field.responsive_layout !== "full") ||
    !safeKey(field.provider_mapping)
  ) return null;
  return Object.freeze({
    accessibilityLabel: String(field.accessibility_label),
    autoComplete: String(field.autocomplete_policy) as PerformanceLocalEstimateField["autoComplete"],
    control: expected[3],
    inputMode: expected[0] === "phone" ? "tel" : expected[0] === "postal-code" ? "numeric" : "text",
    key: expected[0] as PerformanceLocalEstimateFieldKey,
    label: expected[1],
    maxLength: Number(field.maximum_length),
    order: expected[5],
    providerMapping: String(field.provider_mapping),
    required: expected[2],
    responsive: Object.freeze({
      desktop: field.responsive_layout as "half" | "full",
      tablet: field.responsive_layout as "half" | "full",
      mobile: "full" as const,
    }),
    rows: expected[3] === "textarea" ? 3 : undefined,
    type: expected[3] === "input" ? expected[4] : undefined,
    validation: Object.freeze({
      maximumLength: Number(validation.maximum_length),
      minimumLength: Number(validation.minimum_length),
      rule: validation.rule as PerformanceLocalEstimateField["validation"]["rule"],
    }),
  });
}

function effectiveComponent(
  delivery: PerformanceLocalDeliveryRead,
  key: string,
): WebsiteThemeComponentConfigurationRead | null {
  const matches = delivery.components.filter((component) => component.component_key === key);
  const pageOverrides = matches.filter(
    (component) => component.scope_type === "page_override" &&
      component.planned_page_id === delivery.composition.planned_page_id,
  );
  if (pageOverrides.length > 1) return null;
  if (pageOverrides.length === 1) return pageOverrides[0];
  const defaults = matches.filter(
    (component) => component.scope_type === "website_default" && component.planned_page_id === null,
  );
  return defaults.length === 1 ? defaults[0] : null;
}

export function sameCanonicalJson(left: unknown, right: unknown): boolean {
  try {
    return JSON.stringify(canonicalJson(left)) === JSON.stringify(canonicalJson(right));
  } catch {
    return false;
  }
}

function canonicalJson(value: unknown): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (Array.isArray(value)) return value.map(canonicalJson);
  if (typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, nested]) => [key, canonicalJson(nested)]),
    );
  }
  throw new Error("Non-JSON value");
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const observed = Object.keys(value).sort();
  const expected = [...keys].sort();
  return observed.length === expected.length && observed.every((key, index) => key === expected[index]);
}

function exactText(value: unknown): string {
  return typeof value === "string" && value === value.trim() &&
    value.length > 0 && !/[\u0000-\u001f\u007f]/.test(value)
    ? value
    : "";
}

function nullableText(value: unknown): string | null {
  if (value === null) return null;
  return exactText(value) || null;
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function requirePositiveInteger(value: unknown, label: string): asserts value is number {
  if (!positiveInteger(value)) throw new Error(`${label} must be a positive integer.`);
}

function hexFingerprint(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function hexCommit(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{40}$/.test(value);
}

function safeInstanceKey(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z][A-Za-z0-9:_-]{2,159}$/.test(value);
}

function safeKey(value: unknown): value is string {
  return typeof value === "string" && /^[a-z][a-z0-9_-]{0,119}$/.test(value);
}

function exactInstant(value: unknown): value is string {
  return typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value));
}
