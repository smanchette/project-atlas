import {
  ArrowUp,
  ChevronDown,
  Mail,
  Menu,
  Phone,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  type CSSProperties,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  type RefObject,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, NavLink } from "react-router-dom";

import { WebsiteIdentityLogo } from "./WebsiteIdentityPresentation";
import {
  PERFORMANCE_LOCAL_THEME_VERSION,
  performanceLocalOptionalComponentAttributes,
  performanceLocalOptionalConfiguration,
  resolveOptionalComponent,
  type OptionalComponentDiagnosticAttributes,
  type OptionalComponentResolution,
  type PerformanceLocalOptionalConfiguration,
} from "./performanceLocalTheme";
import {
  buildNavigationTree,
  compositionValidationError,
  resolvePageMediaDisplayPreset,
  type ResolvedNavigationItem,
} from "../pages/GeneratedPagePreview";
import type {
  GeneratedPage,
  PageComponentInstance,
  PageComposition,
  PageMediaDisplayPreset,
  PerformanceLocalDeliveryMode,
  PerformanceLocalFormReadinessRead,
  PerformanceLocalSubmissionAcceptedRead,
} from "../types";
import { resolvePerformanceLocalStickyVisibility } from "./performanceLocalInteractions";

export type PerformanceLocalRuntimeToggles = {
  campaignBanner: boolean;
  compactEstimateForm: boolean;
  estimateAction?: boolean;
  finalCta: boolean;
  headerEstimateCta?: boolean;
  phoneAction?: boolean;
  stickyActionBar: boolean;
  trustStrip: boolean;
};

export type PerformanceLocalEstimateFieldKey =
  | "name"
  | "phone"
  | "postal-code"
  | "requested-service"
  | "message";

export type PerformanceLocalEstimateField = Readonly<{
  accessibilityLabel: string;
  autoComplete?: string;
  control: "input" | "textarea";
  inputMode?: "email" | "numeric" | "search" | "tel" | "text" | "url";
  key: PerformanceLocalEstimateFieldKey;
  label: string;
  maxLength: number;
  order: number;
  providerMapping: string;
  required: boolean;
  responsive: Readonly<{
    desktop: "half" | "full";
    tablet: "half" | "full";
    mobile: "full";
  }>;
  rows?: number;
  type?: "email" | "tel" | "text";
  validation: Readonly<{
    maximumLength: number;
    minimumLength: number;
    rule: "nonempty_text" | "phone" | "postal_code" | "free_text";
  }>;
}>;

export type PerformanceLocalEstimateFormConfiguration = Readonly<{
  componentConfigurationId: number;
  componentInstanceKey: string;
  ctaLabel: string;
  fields: readonly PerformanceLocalEstimateField[];
  previewNotice: string;
  providerState: Readonly<{
    canSubmit: boolean;
    collectsData: boolean;
    destination: string | null;
    destinationConfigured?: boolean;
    /** Public delivery intentionally redacts the provider identity. */
    providerKey?: string | null;
    submissionState: string;
    testOnly?: boolean;
  }>;
  consent?: Readonly<{
    mode: "not_required" | "explicit";
    privacyPolicyDestination: string | null;
    text: string | null;
    textVersion: string | null;
  }>;
  submitLabel: string;
  visualState?: "idle" | "disabled" | "error" | "success";
}>;

type PerformanceLocalCampaignBase = PerformanceLocalOptionalConfiguration & {
  approvalIdentity: string;
  campaignLabel: string;
  ctaDestination: string;
  ctaLabel: string;
  destinationComponentConfigurationId: number;
  enabled: boolean;
  websiteId: number;
};

export type PerformanceLocalEvergreenCampaign = PerformanceLocalCampaignBase & {
  intent: "evergreen_conversion";
  endDate?: never;
  qualifier?: never;
  price?: never;
  startDate?: never;
  termsReference?: never;
};

export type PerformanceLocalTimeBoundCampaign = PerformanceLocalCampaignBase & {
  intent: "time_bound_campaign";
  endDate: string;
  offerDetails: string;
  qualifier?: string | null;
  price?: string | null;
  startDate: string;
  termsReference: string;
};

export type PerformanceLocalCampaign =
  | PerformanceLocalEvergreenCampaign
  | PerformanceLocalTimeBoundCampaign;

export type PerformanceLocalGovernedContact = Readonly<{
  callDestination: string;
  phoneDisplay: string;
  websiteId: number;
}>;

export type PerformanceLocalStickyActionConfiguration = Readonly<{
  callLabel: string;
  componentConfigurationId: number;
  desktopHeaderActionsEnabled: boolean;
  destinationComponentConfigurationId: number;
  enabled: boolean;
  estimateLabel: string;
  mobileStickyActionsEnabled: boolean;
}>;

export function performanceLocalFormDomId(componentConfigurationId: number): string {
  if (!Number.isSafeInteger(componentConfigurationId) || componentConfigurationId <= 0) {
    throw new Error("Compact estimate form configuration identity must be a positive integer.");
  }
  return `performance-local-form-config-${componentConfigurationId}`;
}

export type PerformanceLocalDiagnostics = {
  disabledComponents: string[];
  enabledComponents: string[];
  effectiveVariants: Record<string, string>;
  errors: string[];
  failClosedComponents: string[];
  warnings: string[];
};

export type PerformanceLocalFormSubmissionPayload = Readonly<{
  name: string;
  phone: string;
  postal_code: string;
  requested_service: string;
  message: string | null;
  consent_accepted: boolean | null;
}>;

export type PerformanceLocalFormSubmission = Readonly<{
  endpoint: string | null;
  readiness: PerformanceLocalFormReadinessRead;
  submit?: (
    payload: PerformanceLocalFormSubmissionPayload,
    idempotencyKey: string,
  ) => Promise<PerformanceLocalSubmissionAcceptedRead>;
}>;

type ResolvedPerformanceLocalFormSubmission = Readonly<{
  canSubmit: boolean;
  endpoint: string | null;
  readiness: PerformanceLocalFormReadinessRead;
  submit: PerformanceLocalFormSubmission["submit"];
}>;

export type PerformanceLocalRendererIdentity = Readonly<{
  componentVersion: "2" | "3";
  deliveryMode: "theme_lab" | PerformanceLocalDeliveryMode;
  exposeDiagnostics: boolean;
  themeCompatibility: "performance-local@2" | "performance-local@3";
  themeVersion: 2 | 3;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
}>;

export type PerformanceLocalRenderedComponentAttributes = Readonly<Partial<
  Omit<
    OptionalComponentDiagnosticAttributes,
    "data-component-version" | "data-component-theme-compatibility"
  > & {
    "data-component-version": "2" | "3";
    "data-component-theme-compatibility": "performance-local@2" | "performance-local@3";
  }
>>;

export type PerformanceLocalRendererProps = {
  /** Local Theme Lab-only visual direction; accepts opaque #RRGGBB and is never persisted. */
  brandAccent?: string | null;
  campaign?: PerformanceLocalCampaign | null;
  composition: PageComposition;
  estimateForm?: PerformanceLocalEstimateFormConfiguration | null;
  formSubmission?: PerformanceLocalFormSubmission | null;
  governedContact?: PerformanceLocalGovernedContact | null;
  rendererIdentity?: PerformanceLocalRendererIdentity;
  page: GeneratedPage;
  stickyActions?: PerformanceLocalStickyActionConfiguration | null;
  toggles: PerformanceLocalRuntimeToggles;
  /** A deterministic clock may be provided by tests. It never persists state. */
  previewedAt?: Date;
};

type MediaBindingResult = {
  byTarget: Map<string, PageComponentInstance>;
  errors: string[];
  unbound: PageComponentInstance[];
};

type RenderableMedia = {
  alt: string;
  caption: string;
  focalX: number;
  focalY: number;
  preset: PageMediaDisplayPreset;
  role: string;
  source: string;
  title: string;
};

const EMPTY_TOGGLES: PerformanceLocalRuntimeToggles = {
  campaignBanner: false,
  compactEstimateForm: false,
  finalCta: false,
  stickyActionBar: false,
  trustStrip: false,
};

const THEME_LAB_RENDERER_IDENTITY: PerformanceLocalRendererIdentity = Object.freeze({
  componentVersion: "2",
  deliveryMode: "theme_lab",
  exposeDiagnostics: true,
  themeCompatibility: "performance-local@2",
  themeVersion: 2,
  destinationForGeneratedPageId: (generatedPageId: number) =>
    `/theme-lab/generated-pages/${generatedPageId}`,
});

const CANONICAL_PROCESS_SECTION_KEYS = Object.freeze([
  "process_section",
  "prep_section",
  "realtor_property_manager_section",
] as const);

export function PerformanceLocalRenderer({
  brandAccent = null,
  campaign = null,
  composition,
  estimateForm = null,
  formSubmission = null,
  governedContact = null,
  page,
  stickyActions = null,
  toggles = EMPTY_TOGGLES,
  rendererIdentity = THEME_LAB_RENDERER_IDENTITY,
  previewedAt = new Date(),
}: PerformanceLocalRendererProps) {
  const components = composition.effective_components;
  const byKey = useMemo(() => indexComponents(components), [components]);
  const media = useMemo(() => bindMediaToExactTargets(components), [components]);
  const header = first(byKey, "website_header");
  const hero = first(byKey, "hero");
  const trust = first(byKey, "trust_license");
  const finalCta = first(byKey, "final_cta");
  const footer = first(byKey, "website_footer");
  const primaryNavigation = first(byKey, "primary_navigation");
  const utilityNavigation = first(byKey, "utility_navigation");
  const footerNavigation = first(byKey, "footer_navigation");
  const headerData = header?.resolved_data ?? {};
  const email = cleanText(headerData.email) || cleanText(hero?.resolved_data.email);
  const resolvedEstimateForm = validateEstimateFormConfiguration(
    estimateForm,
    rendererIdentity.deliveryMode,
  );
  const resolvedFormSubmission = validateFormSubmission(
    formSubmission,
    resolvedEstimateForm,
    composition.website_id,
    rendererIdentity.deliveryMode,
  );
  const resolvedContact = toggles.phoneAction === false
    ? null
    : validateGovernedContact(governedContact, composition.website_id);
  const resolvedStickyActions = validateStickyActionConfiguration(
    stickyActions,
    resolvedEstimateForm,
  );
  const estimateDestination =
    toggles.estimateAction !== false &&
    toggles.compactEstimateForm &&
    toggles.finalCta &&
    finalCta &&
    resolvedStickyActions &&
    (resolvedStickyActions.desktopHeaderActionsEnabled || resolvedStickyActions.mobileStickyActionsEnabled) &&
    resolvedEstimateForm
      ? `#${performanceLocalFormDomId(resolvedEstimateForm.componentConfigurationId)}`
      : null;
  const estimateLabel = resolvedEstimateForm?.ctaLabel ?? "";
  const phoneDestination = resolvedContact?.callDestination ?? null;
  const heroActionRef = useRef<HTMLDivElement>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [formFocusRisk, setFormFocusRisk] = useState(false);
  const [heroConversionVisible, setHeroConversionVisible] = useState(true);
  const mobileViewport = useMobileViewport();

  useEffect(() => {
    if (mobileViewport) return;
    setMobileMenuOpen(false);
    setFormFocusRisk(false);
  }, [mobileViewport]);

  useEffect(() => {
    if (!estimateDestination) setFormFocusRisk(false);
  }, [estimateDestination]);

  useEffect(() => {
    const target = heroActionRef.current;
    if (!toggles.stickyActionBar || !mobileViewport || !target) {
      setHeroConversionVisible(true);
      return;
    }
    if (typeof IntersectionObserver === "undefined") {
      // Fail closed when the browser cannot establish whether the opening
      // conversion controls remain visible.
      setHeroConversionVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        setHeroConversionVisible(Boolean(entry?.isIntersecting && entry.intersectionRatio >= 0.25));
      },
      {
        root: null,
        rootMargin: "-68px 0px 0px 0px",
        threshold: [0, 0.25, 0.5, 1],
      },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [mobileViewport, toggles.stickyActionBar, page.id]);

  const validationError = rendererValidationError(page, composition);
  if (validationError) {
    return (
      <main className="performanceLocalUnavailable" role="alert" data-atlas-adapter="performance-local">
        <h1>Performance Local preview unavailable</h1>
        <p>{validationError}</p>
      </main>
    );
  }
  const trustState = toggles.trustStrip && trust && trustFacts(trust).length
    ? governedOptionalState(
        "trust_proof_strip",
        composition.website_id,
        "Approved business credentials",
        { sourceIdentity: trust.instance_key, approvalIdentity: composition.source_hash },
        "desktop",
        page.id,
        rendererIdentity,
      )
    : null;
  const trustFeatureState = trustState?.resolution.visible
    ? governedOptionalState(
        "trust_feature_cards",
        composition.website_id,
        "Approved credential facts",
        { sourceIdentity: trust?.instance_key, approvalIdentity: composition.source_hash },
        "desktop",
        page.id,
        rendererIdentity,
      )
    : null;
  const finalAction = estimateDestination
    ? { ctaLabel: estimateLabel, ctaDestination: estimateDestination }
    : phoneDestination
      ? { ctaLabel: "Call", ctaDestination: phoneDestination }
      : null;
  const finalState = toggles.finalCta && finalCta && finalAction
    ? governedOptionalState(
        "visual_cta_band",
        composition.website_id,
        "Contact the business",
        { sourceIdentity: finalCta.instance_key, ...finalAction },
        "desktop",
        page.id,
        rendererIdentity,
      )
    : null;
  const formState = finalState?.resolution.visible && toggles.compactEstimateForm && resolvedEstimateForm
    ? governedOptionalState(
        "compact_estimate_form",
        composition.website_id,
        "Estimate request preview",
        { previewOnly: true, productionMode: false },
        "desktop",
        page.id,
        rendererIdentity,
      )
    : null;
  const stickyAction = resolvedStickyActions && (estimateDestination || phoneDestination)
    ? {
        actionLabel: estimateDestination
          ? resolvedStickyActions.estimateLabel
          : resolvedStickyActions.callLabel,
        phoneOrEstimateDestination: estimateDestination ?? phoneDestination,
        sourceIdentity: `component-configuration:${resolvedStickyActions.componentConfigurationId}`,
      }
    : null;
  const stickyState = toggles.stickyActionBar && resolvedStickyActions?.mobileStickyActionsEnabled && stickyAction
    ? governedOptionalState(
        "sticky_mobile_action_bar",
        composition.website_id,
        "Contact actions",
        stickyAction,
        "mobile",
        page.id,
        rendererIdentity,
      )
    : null;
  const trustVisible = Boolean(trustState?.resolution.visible);
  const finalCtaVisible = Boolean(finalState?.resolution.visible);
  const formVisible = Boolean(formState?.resolution.visible);
  const stickyConfigured = Boolean(stickyState?.resolution.visible);
  const stickyVisibility = resolvePerformanceLocalStickyVisibility({
    actionsAvailable: stickyConfigured,
    formFocusRisk,
    heroConversionVisible,
    mobileMenuOpen,
    mobileViewport,
  });
  const campaignState = resolveCampaign(
    toggles.campaignBanner ? campaign : null,
    composition.website_id,
    page.id,
    previewedAt,
    estimateDestination ? resolvedEstimateForm : null,
    rendererIdentity,
  );
  const diagnostics = performanceLocalDiagnostics(composition, toggles, {
    campaignError: campaignState.error,
    campaignVisible: Boolean(campaignState.campaign),
    estimateDestination,
    media,
    phoneDestination,
  });
  const mainComponents = components.filter(
    (component) =>
      component.region === "main" &&
      component.component_key !== "hero" &&
      component.component_key !== "trust_license" &&
      component.component_key !== "final_cta" &&
      component.component_key !== "media_placement",
  );
  const mainPresentation = buildMainPresentation(mainComponents);
  const runtimeAccent = validatedOpaqueCssColor(brandAccent);
  const runtimeStyle = runtimeAccent
    ? ({
        "--performance-local-accent": runtimeAccent,
        "--performance-local-accent-text": contrastTextColor(runtimeAccent),
      } as CSSProperties)
    : undefined;
  return (
    <div
      className="performanceLocalSite"
      data-atlas-adapter="performance-local"
      data-atlas-adapter-version={rendererIdentity.themeVersion}
      data-atlas-delivery-mode={rendererIdentity.deliveryMode}
      data-composition-id={composition.id}
      data-composition-version={composition.composition_version}
      data-generated-page-id={page.id}
      data-runtime-brand-accent={runtimeAccent ? "validated-preview-override" : "governed-primary"}
      data-mobile-menu-open={mobileMenuOpen ? "true" : "false"}
      data-sticky-actions-visible={stickyVisibility.visible ? "true" : "false"}
      data-sticky-actions-reason={stickyVisibility.reason}
      style={runtimeStyle}
    >
      <a className="performanceLocalSkipLink" href="#main-content">
        Skip to main content
      </a>
      {campaignState.campaign && campaignState.attributes && (
        <CampaignBanner campaign={campaignState.campaign} attributes={campaignState.attributes} />
      )}
      {header && (
        <PerformanceHeader
          component={header}
          primaryNavigation={primaryNavigation}
          utilityNavigation={utilityNavigation}
          contact={resolvedStickyActions?.desktopHeaderActionsEnabled ? resolvedContact : null}
          estimateLabel={estimateLabel}
          estimateDestination={
            toggles.headerEstimateCta === false || !resolvedStickyActions?.desktopHeaderActionsEnabled
              ? null
              : estimateDestination
          }
          mobileMenuOpen={mobileMenuOpen}
          onMobileMenuOpenChange={setMobileMenuOpen}
          destinationForGeneratedPageId={rendererIdentity.destinationForGeneratedPageId}
        />
      )}
      <main id="main-content">
        {hero && (
          <HeroSection
            component={hero}
            media={media.byTarget.get(hero.instance_key)}
            contact={resolvedContact}
            estimateDestination={estimateDestination}
            estimateLabel={estimateLabel}
            conversionRef={heroActionRef}
          />
        )}
        {trustVisible && trust && trustState?.attributes && trustFeatureState?.attributes && (
          <TrustStrip
            component={trust}
            attributes={trustState.attributes}
            featureAttributes={trustFeatureState.attributes}
          />
        )}
        {mainPresentation.map((item, index) => item.kind === "process" ? (
          <CanonicalProcessSequence
            key={item.components.map((component) => component.instance_key).join("|")}
            components={item.components}
          />
        ) : (
          <PerformanceComponent
            key={item.component.instance_key}
            component={item.component}
            media={media.byTarget.get(item.component.instance_key)}
            index={index}
            contact={resolvedContact}
            email={email}
            destinationForGeneratedPageId={rendererIdentity.destinationForGeneratedPageId}
          />
        ))}
        {finalCtaVisible && finalCta && finalState?.attributes && (
          <FinalConversionSection
            component={finalCta}
            contact={resolvedContact}
            email={email}
            showForm={formVisible}
            attributes={finalState.attributes}
            formAttributes={formState?.attributes ?? null}
            formConfiguration={resolvedEstimateForm}
            formSubmission={resolvedFormSubmission}
            exposeDiagnostics={rendererIdentity.exposeDiagnostics}
            onFormFocusRiskChange={setFormFocusRisk}
          />
        )}
      </main>
      {footer && (
        <PerformanceFooter
          component={footer}
          navigation={footerNavigation}
          contact={resolvedContact}
          email={email}
          destinationForGeneratedPageId={rendererIdentity.destinationForGeneratedPageId}
        />
      )}
      <BackToTopControl suppressed={formFocusRisk || mobileMenuOpen} />
      {stickyVisibility.visible && (
        <StickyMobileActions
          contact={resolvedContact}
          estimateDestination={estimateDestination}
          estimateLabel={resolvedStickyActions!.estimateLabel}
          callLabel={resolvedStickyActions!.callLabel}
          attributes={stickyState!.attributes!}
        />
      )}
      {rendererIdentity.exposeDiagnostics ? (
        <output className="performanceLocalDiagnostics" hidden data-diagnostic-count={diagnostics.errors.length + diagnostics.warnings.length}>
          {JSON.stringify(diagnostics)}
        </output>
      ) : null}
    </div>
  );
}

export function performanceLocalDiagnostics(
  composition: PageComposition,
  toggles: PerformanceLocalRuntimeToggles,
  context: {
    campaignError?: string | null;
    campaignVisible?: boolean;
    estimateDestination?: string | null;
    media?: MediaBindingResult;
    phoneDestination?: string | null;
  } = {},
): PerformanceLocalDiagnostics {
  const media = context.media ?? bindMediaToExactTargets(composition.effective_components);
  const campaignError = context.campaignError ?? null;
  const keys = new Set(composition.effective_components.map((item) => item.component_key));
  const enabledComponents: string[] = [];
  if (keys.has("website_header")) enabledComponents.push("site_header");
  if (keys.has("primary_navigation") || keys.has("utility_navigation")) {
    enabledComponents.push("desktop_dropdown_navigation", "mobile_navigation_drawer");
  }
  if (keys.has("hero")) enabledComponents.push("hero_conversion_section");
  if (keys.has("destination_cards") || keys.has("related_page_links")) {
    enabledComponents.push("service_or_related_card_grid");
  }
  if (media.byTarget.size) enabledComponents.push("split_media_text_section");
  if (keys.has("content_section") || keys.has("service_summary")) {
    enabledComponents.push("authority_content_section");
  }
  if (keys.has("faq")) enabledComponents.push("faq_accordion");
  if (keys.has("website_footer")) enabledComponents.push("site_footer");
  if (composition.effective_components.length) enabledComponents.push("back_to_top_control");
  const trust = composition.effective_components.find((item) => item.component_key === "trust_license");
  if (toggles.trustStrip && trust && trustFacts(trust).length) {
    enabledComponents.push("trust_proof_strip", "trust_feature_cards");
  }
  const diagnosticMainComponents = composition.effective_components.filter(
    (item) => item.region === "main" && item.component_key !== "media_placement",
  );
  if (
    composition.effective_components.some((item) => structuredSteps(item).length) ||
    buildMainPresentation(diagnosticMainComponents).some((item) => item.kind === "process")
  ) {
    enabledComponents.push("numbered_process_steps");
  }
  const finalCtaVisible = toggles.finalCta && keys.has("final_cta");
  if (finalCtaVisible) enabledComponents.push("visual_cta_band");
  if (finalCtaVisible && toggles.compactEstimateForm) enabledComponents.push("compact_estimate_form");
  const phoneDestination = context.phoneDestination ?? "";
  const estimateDestination = context.estimateDestination ?? "";
  if (toggles.stickyActionBar && (phoneDestination || estimateDestination)) {
    enabledComponents.push("sticky_mobile_action_bar");
  }
  if (context.campaignVisible) enabledComponents.push("campaign_banner");

  const warnings = [...media.errors];
  if (campaignError) warnings.push(campaignError);
  if (media.unbound.length) {
    warnings.push(`${media.unbound.length} governed media placement(s) have no exact render target.`);
  }
  for (const [target, component] of media.byTarget) {
    if (!renderableMedia(component)) {
      warnings.push(`Governed media for exact component instance ${target} is incomplete, unsafe, or incompatible and was hidden.`);
    }
  }
  const effectiveVariants: Record<string, string> = {};
  if (enabledComponents.includes("site_header")) effectiveVariants.header = "compact_sticky";
  if (
    enabledComponents.includes("desktop_dropdown_navigation") ||
    enabledComponents.includes("mobile_navigation_drawer")
  ) {
    effectiveVariants.navigation = "dropdown_and_drawer";
  }
  if (enabledComponents.includes("hero_conversion_section")) effectiveVariants.hero = "visual_conversion";
  if (
    enabledComponents.includes("split_media_text_section") ||
    enabledComponents.includes("authority_content_section")
  ) {
    effectiveVariants.content = "alternating_split";
  }
  if (enabledComponents.includes("site_footer")) effectiveVariants.footer = "structured";
  const allOptionalComponents = [
    "campaign_banner",
    "trust_proof_strip",
    "trust_feature_cards",
    "visual_cta_band",
    "compact_estimate_form",
    "sticky_mobile_action_bar",
    "review_badge_group",
    "statistics_counter_band",
    "video_embed_section",
    "map_or_service_area_section",
    "community_program_section",
    "language_selector",
  ];
  const disabledComponents = allOptionalComponents.filter(
    (key) => !enabledComponents.includes(key),
  );
  const failClosedComponents = [
    ...(campaignError ? ["campaign_banner"] : []),
    ...(media.errors.length || media.unbound.length ? ["split_media_text_section"] : []),
  ];
  return {
    disabledComponents,
    enabledComponents,
    effectiveVariants,
    errors: [],
    failClosedComponents,
    warnings,
  };
}

const SEMANTIC_ACTION_ARTICLES = new Set(["a", "an", "the"]);

/**
 * Conservatively compares public action copy without hard-coding any business
 * phrase. Unicode compatibility normalization, punctuation folding, and
 * standalone English articles are the only semantic reductions performed.
 */
export function performanceLocalSemanticActionKey(value: unknown): string {
  if (typeof value !== "string") return "";
  return value
    .normalize("NFKC")
    .toLocaleLowerCase("en-US")
    .replace(/&/g, " and ")
    .replace(/[\p{C}\p{P}\p{S}]+/gu, " ")
    .trim()
    .split(/\s+/u)
    .filter((token) => token && !SEMANTIC_ACTION_ARTICLES.has(token))
    .join(" ");
}

export function performanceLocalActionCopyEquivalent(
  message: unknown,
  actionLabel: unknown,
): boolean {
  const messageKey = performanceLocalSemanticActionKey(message);
  const actionKey = performanceLocalSemanticActionKey(actionLabel);
  return Boolean(messageKey && actionKey && messageKey === actionKey);
}

function CampaignBanner({
  campaign,
  attributes,
}: {
  campaign: PerformanceLocalCampaign;
  attributes: PerformanceLocalRenderedComponentAttributes;
}) {
  const singleAction = campaign.intent === "evergreen_conversion" &&
    performanceLocalActionCopyEquivalent(campaign.campaignLabel, campaign.ctaLabel);
  return (
    <aside
      className={`performanceLocalCampaign${singleAction ? " performanceLocalCampaignSingle" : ""}`}
      aria-label={campaign.campaignLabel}
      data-conversion-intent={campaign.intent}
      data-public-action-copy={singleAction ? "semantic_duplicate_suppressed" : "distinct_copy_and_action"}
      {...attributes}
    >
      {singleAction ? (
        <a
          className="performanceLocalContainer performanceLocalCampaignSingleAction"
          href={campaign.ctaDestination}
        >
          <strong>{campaign.campaignLabel}</strong>
        </a>
      ) : (
        <div className="performanceLocalContainer performanceLocalCampaignInner">
          <p>
            <strong>{campaign.campaignLabel}</strong>
            {campaign.price ? <span>{campaign.price}</span> : null}
            {campaign.qualifier ? <span>{campaign.qualifier}</span> : null}
          </p>
          <a href={campaign.ctaDestination}>{campaign.ctaLabel}</a>
        </div>
      )}
    </aside>
  );
}

function PerformanceHeader({
  contact,
  component,
  estimateLabel,
  estimateDestination,
  mobileMenuOpen,
  onMobileMenuOpenChange,
  primaryNavigation,
  utilityNavigation,
  destinationForGeneratedPageId,
}: {
  contact: PerformanceLocalGovernedContact | null;
  component: PageComponentInstance;
  estimateLabel: string;
  estimateDestination: string | null;
  mobileMenuOpen: boolean;
  onMobileMenuOpenChange: (open: boolean) => void;
  primaryNavigation?: PageComponentInstance;
  utilityNavigation?: PageComponentInstance;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
}) {
  const data = component.resolved_data;
  const identityAssets = asRecord(data.identity_assets);
  const displayName = cleanText(data.display_name) || cleanText(data.company_name);
  const navigation = resolveHeaderNavigation(primaryNavigation, utilityNavigation);

  return (
    <header className="performanceLocalHeader" data-component-key="site_header">
      <div className="performanceLocalContainer performanceLocalHeaderInner">
        <div className="performanceLocalBrand" aria-label={displayName || "Website home"}>
          <WebsiteIdentityLogo
            identityAssets={identityAssets}
            slot="header_logo"
            displayName={displayName}
          />
          <span className="performanceLocalBrandText">
            <strong>{displayName}</strong>
            {cleanText(data.tagline) ? <small>{cleanText(data.tagline)}</small> : null}
          </span>
        </div>
        <DesktopNavigation
          navigation={navigation}
          destinationForGeneratedPageId={destinationForGeneratedPageId}
        />
        <div className="performanceLocalHeaderActions">
          {contact ? <PhoneLink contact={contact} compact /> : null}
          {estimateDestination ? (
            <a className="performanceLocalButton performanceLocalHeaderEstimate" href={estimateDestination}>
              {estimateLabel}
            </a>
          ) : null}
          <MobileNavigation
            navigation={navigation}
            contact={contact}
            estimateDestination={estimateDestination}
            estimateLabel={estimateLabel}
            open={mobileMenuOpen}
            onOpenChange={onMobileMenuOpenChange}
            destinationForGeneratedPageId={destinationForGeneratedPageId}
          />
        </div>
      </div>
    </header>
  );
}

function DesktopNavigation({
  navigation,
  destinationForGeneratedPageId,
}: {
  navigation: NavigationResolution;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
}) {
  const [openId, setOpenId] = useState<number | null>(null);
  const triggers = useRef(new Map<number, HTMLButtonElement>());

  function onKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    if (event.key !== "Escape" || openId === null) return;
    event.preventDefault();
    const trigger = triggers.current.get(openId);
    setOpenId(null);
    trigger?.focus();
  }

  return (
    <nav className="performanceLocalDesktopNavigation" aria-label="Primary navigation" onKeyDown={onKeyDown}>
      {navigation.error ? (
        <span className="performanceLocalNavigationUnavailable" role="status">
          Navigation unavailable
        </span>
      ) : (
        <ul>
          {navigation.nodes.map((node) => {
            const expanded = openId === node.navigationItemId;
            return (
              <li key={node.navigationItemId} data-navigation-item-id={node.navigationItemId}>
                <PerformanceLocalDestination
                  node={node}
                  destinationForGeneratedPageId={destinationForGeneratedPageId}
                />
                {node.children.length ? (
                  <>
                    <button
                      ref={(element) => {
                        if (element) triggers.current.set(node.navigationItemId, element);
                        else triggers.current.delete(node.navigationItemId);
                      }}
                      type="button"
                      aria-label={`Toggle ${node.label} submenu`}
                      aria-expanded={expanded}
                      aria-controls={`performance-local-submenu-${node.navigationItemId}`}
                      onClick={() => setOpenId(expanded ? null : node.navigationItemId)}
                    >
                      <ChevronDown size={16} aria-hidden="true" />
                    </button>
                    <ul
                      id={`performance-local-submenu-${node.navigationItemId}`}
                      className="performanceLocalDropdown"
                      hidden={!expanded}
                    >
                      {node.children.map((child) => (
                        <NavigationBranch
                          key={child.navigationItemId}
                          node={child}
                          destinationForGeneratedPageId={destinationForGeneratedPageId}
                        />
                      ))}
                    </ul>
                  </>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}

function MobileNavigation({
  contact,
  estimateDestination,
  estimateLabel,
  navigation,
  onOpenChange,
  open,
  destinationForGeneratedPageId,
}: {
  contact: PerformanceLocalGovernedContact | null;
  estimateDestination: string | null;
  estimateLabel: string;
  navigation: NavigationResolution;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
}) {
  const [expandedGroups, setExpandedGroups] = useState<Set<number>>(() => new Set());
  const triggerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = focusableElements(drawerRef.current);
    (focusable[0] ?? drawerRef.current)?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  function close() {
    onOpenChange(false);
    window.setTimeout(() => triggerRef.current?.focus(), 0);
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = focusableElements(drawerRef.current);
    if (!focusable.length) {
      event.preventDefault();
      return;
    }
    const firstElement = focusable[0];
    const lastElement = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === firstElement) {
      event.preventDefault();
      lastElement.focus();
    } else if (!event.shiftKey && document.activeElement === lastElement) {
      event.preventDefault();
      firstElement.focus();
    }
  }

  function toggleGroup(id: number) {
    setExpandedGroups((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="performanceLocalMobileNavigation">
      <button
        ref={triggerRef}
        className="performanceLocalMenuTrigger"
        type="button"
        aria-label="Open website navigation"
        aria-expanded={open}
        aria-controls="performance-local-mobile-drawer"
        onClick={() => onOpenChange(true)}
      >
        <Menu aria-hidden="true" />
      </button>
      {open ? (
        <div className="performanceLocalDrawerBackdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) close();
        }}>
          <div
            ref={drawerRef}
            id="performance-local-mobile-drawer"
            className="performanceLocalDrawer"
            role="dialog"
            aria-modal="true"
            aria-label="Website navigation"
            tabIndex={-1}
            onKeyDown={onKeyDown}
          >
            <div className="performanceLocalDrawerHeader">
              <strong>Menu</strong>
              <button type="button" aria-label="Close website navigation" onClick={close}>
                <X aria-hidden="true" />
              </button>
            </div>
            {navigation.error ? (
              <p role="status">Navigation unavailable: {navigation.error}</p>
            ) : (
              <ul className="performanceLocalDrawerList">
                {navigation.nodes.map((node) => {
                  const expanded = expandedGroups.has(node.navigationItemId);
                  return (
                    <li key={node.navigationItemId}>
                      <div className="performanceLocalDrawerRow" onClick={close}>
                        <PerformanceLocalDestination
                          node={node}
                          destinationForGeneratedPageId={destinationForGeneratedPageId}
                        />
                        {node.children.length ? (
                          <button
                            type="button"
                            aria-label={`Toggle ${node.label} submenu`}
                            aria-expanded={expanded}
                            aria-controls={`performance-local-mobile-group-${node.navigationItemId}`}
                            onClick={(event) => {
                              event.stopPropagation();
                              toggleGroup(node.navigationItemId);
                            }}
                          >
                            <ChevronDown aria-hidden="true" />
                          </button>
                        ) : null}
                      </div>
                      {node.children.length ? (
                        <ul id={`performance-local-mobile-group-${node.navigationItemId}`} hidden={!expanded}>
                          {node.children.map((child) => (
                            <NavigationBranch
                              key={child.navigationItemId}
                              node={child}
                              onNavigate={close}
                              destinationForGeneratedPageId={destinationForGeneratedPageId}
                            />
                          ))}
                        </ul>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
            <div className="performanceLocalDrawerActions">
              {contact ? <PhoneLink contact={contact} compact={false} /> : null}
              {estimateDestination ? (
                <a className="performanceLocalButton performanceLocalButtonSecondary" href={estimateDestination} onClick={close}>
                  {estimateLabel}
                </a>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function NavigationBranch({
  node,
  onNavigate,
  destinationForGeneratedPageId,
}: {
  node: ResolvedNavigationItem;
  onNavigate?: () => void;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
}) {
  return (
    <li data-navigation-item-id={node.navigationItemId} onClick={onNavigate}>
      <PerformanceLocalDestination
        node={node}
        destinationForGeneratedPageId={destinationForGeneratedPageId}
      />
      {node.children.length ? (
        <ul>
          {node.children.map((child) => (
            <NavigationBranch
              key={child.navigationItemId}
              node={child}
              onNavigate={onNavigate}
              destinationForGeneratedPageId={destinationForGeneratedPageId}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function PerformanceLocalDestination({
  node,
  destinationForGeneratedPageId,
}: {
  node: ResolvedNavigationItem;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
}) {
  if (!node.targetGeneratedPageId) {
    return <span aria-disabled="true">{node.label}</span>;
  }
  return (
    <NavLink
      to={destinationForGeneratedPageId(node.targetGeneratedPageId)}
      data-canonical-slug={node.canonicalSlug}
      className={({ isActive }) => isActive ? "performanceLocalActiveDestination" : undefined}
    >
      {node.label}
    </NavLink>
  );
}

function HeroSection({
  contact,
  component,
  conversionRef,
  estimateLabel,
  media,
  estimateDestination,
}: {
  contact: PerformanceLocalGovernedContact | null;
  component: PageComponentInstance;
  conversionRef: RefObject<HTMLDivElement>;
  estimateLabel: string;
  media?: PageComponentInstance;
  estimateDestination: string | null;
}) {
  const data = component.resolved_data;
  const resolvedMedia = media ? renderableMedia(media) : null;
  return (
    <section className="performanceLocalHero" data-component-key="hero_conversion_section">
      <div className="performanceLocalContainer performanceLocalHeroGrid">
        <div className="performanceLocalHeroContent">
          {cleanText(data.page_type) ? (
            <p className="performanceLocalEyebrow">{cleanText(data.page_type).replace(/_/g, " ")}</p>
          ) : null}
          <h1>{cleanText(data.title)}</h1>
          {cleanText(data.intro) ? <p className="performanceLocalHeroSummary">{cleanText(data.intro)}</p> : null}
          <div ref={conversionRef} className="performanceLocalActionRow performanceLocalHeroActions" data-hero-conversion-actions>
            {contact ? <PhoneLink contact={contact} compact={false} /> : null}
            {estimateDestination ? <a className="performanceLocalButton performanceLocalButtonSecondary" href={estimateDestination}>{estimateLabel}</a> : null}
          </div>
        </div>
        {resolvedMedia ? <GovernedMedia media={resolvedMedia} component={media!} className="performanceLocalHeroMedia" priority /> : null}
      </div>
    </section>
  );
}

function TrustStrip({
  component,
  attributes,
  featureAttributes,
}: {
  component: PageComponentInstance;
  attributes: PerformanceLocalRenderedComponentAttributes;
  featureAttributes: PerformanceLocalRenderedComponentAttributes;
}) {
  const facts = trustFacts(component);
  if (!facts.length) return null;
  return (
    <section
      className="performanceLocalTrustStrip"
      aria-label="Approved business credentials"
      data-component-capabilities="trust_proof_strip trust_feature_cards"
      {...attributes}
    >
      <div className="performanceLocalContainer performanceLocalTrustGrid">
        {facts.map((fact) => (
          <article key={fact.label} {...featureAttributes}>
            <ShieldCheck aria-hidden="true" />
            <span>{fact.label}</span>
            <strong>{fact.value}</strong>
          </article>
        ))}
      </div>
    </section>
  );
}

function PerformanceComponent({
  contact,
  component,
  media,
  index,
  email,
  destinationForGeneratedPageId,
}: {
  contact: PerformanceLocalGovernedContact | null;
  component: PageComponentInstance;
  media?: PageComponentInstance;
  index: number;
  email: string;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
}) {
  switch (component.component_key) {
    case "content_section":
    case "service_summary":
      return <AuthoritySection component={component} media={media} reverse={index % 2 === 1} />;
    case "destination_cards":
    case "related_page_links":
      return (
        <RelatedCardGrid
          component={component}
          destinationForGeneratedPageId={destinationForGeneratedPageId}
        />
      );
    case "faq":
      return <FaqAccordion component={component} />;
    case "contact_pathways":
      return <ContactPathways component={component} contact={contact} email={email} />;
    default:
      return null;
  }
}

function AuthoritySection({
  component,
  media,
  reverse,
}: {
  component: PageComponentInstance;
  media?: PageComponentInstance;
  reverse: boolean;
}) {
  const data = component.resolved_data;
  const heading = cleanText(data.heading);
  const body = cleanText(data.body);
  const resolvedMedia = media ? renderableMedia(media) : null;
  const steps = structuredSteps(component);
  if (!heading && !body && !resolvedMedia && !steps.length) return null;
  return (
    <section
      className={`performanceLocalSection ${resolvedMedia ? "performanceLocalSplitSection" : "performanceLocalAuthoritySection"}${steps.length ? " performanceLocalProcessSection" : ""}${reverse ? " performanceLocalSplitReverse" : ""}`}
      data-component-key={steps.length ? "numbered_process_steps" : resolvedMedia ? "split_media_text_section" : "authority_content_section"}
      data-component-capabilities={steps.length && resolvedMedia ? "numbered_process_steps split_media_text_section" : undefined}
      data-source-instance-key={component.instance_key}
    >
      <div className="performanceLocalContainer performanceLocalSplitGrid">
        <div className="performanceLocalSectionCopy">
          {heading ? <h2>{heading}</h2> : null}
          {body ? <p>{body}</p> : null}
          {steps.length ? (
            <ol className="performanceLocalProcessSteps">
              {steps.map((step, stepIndex) => (
                <li key={`${step.heading}-${stepIndex}`}>
                  {step.heading ? <strong>{step.heading}</strong> : null}
                  {step.body ? <span>{step.body}</span> : null}
                </li>
              ))}
            </ol>
          ) : null}
        </div>
        {resolvedMedia ? <GovernedMedia media={resolvedMedia} component={media!} /> : null}
      </div>
    </section>
  );
}

type MainPresentationItem =
  | Readonly<{ kind: "component"; component: PageComponentInstance }>
  | Readonly<{ kind: "process"; components: readonly PageComponentInstance[] }>;

/**
 * The legacy Page draft exposes the process as three adjacent, source-identified
 * semantic sections rather than a fabricated steps array. Group only the exact
 * canonical sequence and leave partial or reordered source untouched.
 */
export function buildMainPresentation(
  components: readonly PageComponentInstance[],
): readonly MainPresentationItem[] {
  const indices = CANONICAL_PROCESS_SECTION_KEYS.map((sectionKey) =>
    components.findIndex((component) => sourceSectionIdentity(component) === sectionKey),
  );
  const completeAdjacentSequence = indices.every((index, position) =>
    index >= 0 && (position === 0 || index === indices[position - 1] + 1),
  );
  if (!completeAdjacentSequence) {
    return components.map((component) => ({ kind: "component" as const, component }));
  }
  const grouped = indices.map((index) => components[index]);
  const groupedInstanceKeys = new Set(grouped.map((component) => component.instance_key));
  return components.flatMap((component, index): MainPresentationItem[] => {
    if (index === indices[0]) return [{ kind: "process", components: grouped }];
    if (groupedInstanceKeys.has(component.instance_key)) return [];
    return [{ kind: "component", component }];
  });
}

function CanonicalProcessSequence({
  components,
}: {
  components: readonly PageComponentInstance[];
}) {
  const steps = components.map((component) => ({
    body: sourceText(component.resolved_data.body),
    component,
    heading: sourceText(component.resolved_data.heading),
    sectionKey: sourceSectionIdentity(component),
  }));
  if (steps.some((step) => !step.heading && !step.body)) return null;
  return (
    <section
      className="performanceLocalSection performanceLocalCanonicalProcess"
      data-component-key="numbered_process_steps"
      data-process-source="canonical_section_sequence"
    >
      <div className="performanceLocalContainer">
        <ol className="performanceLocalCanonicalProcessList">
          {steps.map((step, index) => (
            <li key={step.component.instance_key} data-source-section-key={step.sectionKey}>
              <span className="performanceLocalStepMarker" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <div className="performanceLocalProcessCopy">
                {step.heading ? <h2>{step.heading}</h2> : null}
                {step.body ? <p>{step.body}</p> : null}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function GovernedMedia({
  component,
  media,
  className = "",
  priority = false,
}: {
  component: PageComponentInstance;
  media: RenderableMedia;
  className?: string;
  priority?: boolean;
}) {
  return (
    <figure
      className={`performanceLocalMedia performanceLocalMedia-${media.preset.replace(/_/g, "-")} ${className}`.trim()}
      data-source-instance-key={component.instance_key}
      data-semantic-media-role={media.role}
      data-effective-display-preset={media.preset}
    >
      <div className="performanceLocalMediaFrame">
        <img
          src={media.source}
          alt={media.alt}
          title={media.title || undefined}
          decoding="async"
          loading={priority ? "eager" : "lazy"}
          style={{
            objectFit: "contain",
            objectPosition: `${media.focalX * 100}% ${media.focalY * 100}%`,
          }}
        />
      </div>
      {media.caption ? <figcaption>{media.caption}</figcaption> : null}
    </figure>
  );
}

function RelatedCardGrid({
  component,
  destinationForGeneratedPageId,
}: {
  component: PageComponentInstance;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
}) {
  const links = asArray(component.resolved_data.links).map(asRecord).filter((link) => cleanText(link.label));
  if (!links.length) return null;
  return (
    <section className="performanceLocalSection performanceLocalRelated" aria-label="Related destinations" data-component-key="service_or_related_card_grid">
      <div className="performanceLocalContainer">
        <h2>Related pages</h2>
        <div className="performanceLocalCardGrid">
          {links.map((link, index) => {
            const id = positiveInteger(link.target_generated_page_id);
            return (
              <article key={`${positiveInteger(link.target_planned_page_id) ?? cleanText(link.slug)}-${index}`}>
                <h3>
                  {id ? (
                    <Link to={destinationForGeneratedPageId(id)} data-canonical-slug={cleanText(link.slug)}>
                      {cleanText(link.label)}
                    </Link>
                  ) : (
                    <span>{cleanText(link.label)}</span>
                  )}
                </h3>
                {cleanText(link.purpose) ? <p>{cleanText(link.purpose)}</p> : null}
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function FaqAccordion({ component }: { component: PageComponentInstance }) {
  const items = asArray(component.resolved_data.items)
    .map(asRecord)
    .filter((item) => cleanText(item.question) && cleanText(item.answer));
  if (!items.length) return null;
  return (
    <section className="performanceLocalSection performanceLocalFaq" data-component-key="faq_accordion">
      <div className="performanceLocalContainer performanceLocalNarrow">
        <h2>Frequently asked questions</h2>
        <div className="performanceLocalFaqList">
          {items.map((item, index) => (
            <details key={`${cleanText(item.question)}-${index}`}>
              <summary>{cleanText(item.question)}</summary>
              <p>{cleanText(item.answer)}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

function ContactPathways({
  component,
  contact,
  email,
}: {
  component: PageComponentInstance;
  contact: PerformanceLocalGovernedContact | null;
  email: string;
}) {
  const displayName = cleanText(component.resolved_data.display_name);
  if (!contact && !email) return null;
  return (
    <section className="performanceLocalSection performanceLocalContact" aria-label="Contact options">
      <div className="performanceLocalContainer performanceLocalSectionCopy">
        <h2>{displayName ? `Contact ${displayName}` : "Contact the business"}</h2>
        <div className="performanceLocalActionRow">
          {contact ? <PhoneLink contact={contact} compact={false} /> : null}
          {email ? <EmailLink value={email} /> : null}
        </div>
      </div>
    </section>
  );
}

function FinalConversionSection({
  contact,
  component,
  formConfiguration,
  formSubmission,
  exposeDiagnostics,
  email,
  onFormFocusRiskChange,
  showForm,
  attributes,
  formAttributes,
}: {
  contact: PerformanceLocalGovernedContact | null;
  component: PageComponentInstance;
  formConfiguration: PerformanceLocalEstimateFormConfiguration | null;
  formSubmission: ResolvedPerformanceLocalFormSubmission | null;
  exposeDiagnostics: boolean;
  email: string;
  onFormFocusRiskChange: (focused: boolean) => void;
  showForm: boolean;
  attributes: PerformanceLocalRenderedComponentAttributes;
  formAttributes: PerformanceLocalRenderedComponentAttributes | null;
}) {
  const data = component.resolved_data;
  const heading = cleanText(data.heading);
  const body = cleanText(data.body);
  if (!heading && !body && !showForm && !contact && !email) return null;
  return (
    <section className="performanceLocalFinalCta" {...attributes}>
      <div className={`performanceLocalContainer ${showForm ? "performanceLocalFinalGrid" : "performanceLocalFinalSingle"}`}>
        <div className="performanceLocalSectionCopy">
          {heading ? <h2>{heading}</h2> : null}
          {body ? <p>{body}</p> : null}
          <div className="performanceLocalActionRow">
            {contact ? <PhoneLink contact={contact} compact={false} /> : null}
            {email ? <EmailLink value={email} /> : null}
          </div>
        </div>
        {showForm && formAttributes && formConfiguration ? (
          <CompactEstimateForm
            attributes={formAttributes}
            configuration={formConfiguration}
            submission={formSubmission}
            exposeDiagnostics={exposeDiagnostics}
            onFocusRiskChange={onFormFocusRiskChange}
          />
        ) : null}
      </div>
    </section>
  );
}

function CompactEstimateForm({
  attributes,
  configuration,
  submission,
  exposeDiagnostics,
  onFocusRiskChange,
}: {
  attributes: PerformanceLocalRenderedComponentAttributes;
  configuration: PerformanceLocalEstimateFormConfiguration;
  submission: ResolvedPerformanceLocalFormSubmission | null;
  exposeDiagnostics: boolean;
  onFocusRiskChange: (focused: boolean) => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const idempotencyKey = useRef<string | null>(null);
  const [submissionState, setSubmissionState] = useState<
    "idle" | "submitting" | "success" | "error"
  >("idle");
  const [submissionMessage, setSubmissionMessage] = useState("");
  const canSubmit = Boolean(submission?.canSubmit && submission.submit);
  const visualDisabled = configuration.visualState === "disabled";
  const controlsReadOnly = !canSubmit;

  async function handleSubmission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || !submission?.submit || submissionState === "submitting") return;
    const key = idempotencyKey.current ?? createFormIdempotencyKey();
    if (!key) {
      setSubmissionState("error");
      setSubmissionMessage("The request could not be sent. Please try again.");
      return;
    }
    idempotencyKey.current = key;
    const form = event.currentTarget;
    const values = new FormData(form);
    const message = formStringValue(values, "message");
    const payload: PerformanceLocalFormSubmissionPayload = {
      name: formStringValue(values, "name"),
      phone: formStringValue(values, "phone"),
      postal_code: formStringValue(values, "postal-code"),
      requested_service: formStringValue(values, "requested-service"),
      message: message.length ? message : null,
      consent_accepted: configuration.consent?.mode === "explicit"
        ? values.get("consent-accepted") === "accepted"
        : null,
    };
    setSubmissionState("submitting");
    setSubmissionMessage("Sending request…");
    try {
      const result = await submission.submit(payload, key);
      if (result.status !== "accepted" || result.code !== "submission_accepted") {
        throw new Error("Unexpected form gateway result.");
      }
      setSubmissionState("success");
      setSubmissionMessage(safeFormStatusMessage(result.safe_message) || "Request accepted.");
      form.reset();
      idempotencyKey.current = null;
    } catch {
      setSubmissionState("error");
      setSubmissionMessage("The request could not be sent. Please try again.");
    }
  }

  const visualState = configuration.visualState ?? "idle";
  const stateMessage = submissionState !== "idle"
    ? submissionMessage
    : visualState === "success"
      ? "Preview success appearance — no request was sent."
      : visualState === "error"
        ? "Preview error appearance — review the highlighted fields."
        : visualState === "disabled"
          ? "Preview controls are disabled."
          : canSubmit
            ? submission?.readiness.provider_state.test_only
              ? "Synthetic rehearsal gateway ready. Submitted test values are transient and are not retained."
              : "Submission gateway is ready."
            : "Provider is not configured. Submission is disabled and no data is collected.";

  return (
    <form
      ref={formRef}
      id={performanceLocalFormDomId(configuration.componentConfigurationId)}
      className="performanceLocalEstimateForm"
      aria-label={canSubmit ? "Estimate request" : "Estimate request preview"}
      aria-busy={submissionState === "submitting"}
      data-preview-only={canSubmit ? "false" : "true"}
      data-provider-state={exposeDiagnostics ? configuration.providerState.submissionState : undefined}
      data-provider-configured={exposeDiagnostics
        ? submission?.readiness.provider_state.adapter_registered ? "true" : "false"
        : undefined}
      data-collects-data={canSubmit ? "true" : "false"}
      data-controls-read-only={controlsReadOnly ? "true" : "false"}
      data-visual-state={submissionState === "idle" ? visualState : submissionState}
      autoComplete="off"
      onSubmit={handleSubmission}
      onFocusCapture={() => onFocusRiskChange(true)}
      onBlurCapture={() => {
        window.requestAnimationFrame(() => {
          onFocusRiskChange(Boolean(formRef.current?.contains(document.activeElement)));
        });
      }}
      {...attributes}
    >
      <div className="performanceLocalFormNotice" role="note">
        {configuration.previewNotice}
      </div>
      <p className="performanceLocalFormState" role="status" aria-live="polite">
        {stateMessage}
      </p>
      {configuration.fields.map((field) => (
        <label
          key={field.key}
          className={field.responsive.desktop === "full" ? "performanceLocalFormWide" : undefined}
          data-field-order={field.order}
          data-field-responsive={`${field.responsive.desktop}:${field.responsive.tablet}:${field.responsive.mobile}`}
          data-provider-mapping={exposeDiagnostics ? field.providerMapping : undefined}
          data-validation-contract={exposeDiagnostics
            ? `${field.validation.rule}:${field.validation.minimumLength}:${field.validation.maximumLength}`
            : undefined}
        >
          {field.label}
          {field.control === "textarea" ? (
            <textarea
              data-field-key={field.key}
              aria-label={field.accessibilityLabel}
              rows={field.rows ?? 3}
              autoComplete={field.autoComplete ?? "off"}
              maxLength={field.maxLength}
              name={canSubmit ? field.key : undefined}
              readOnly={controlsReadOnly}
              required={field.required}
              disabled={visualDisabled || submissionState === "submitting"}
            />
          ) : (
            <input
              data-field-key={field.key}
              aria-label={field.accessibilityLabel}
              type={field.type ?? "text"}
              inputMode={field.inputMode}
              autoComplete={field.autoComplete ?? "off"}
              maxLength={field.maxLength}
              name={canSubmit ? field.key : undefined}
              readOnly={controlsReadOnly}
              required={field.required}
              disabled={visualDisabled || submissionState === "submitting"}
            />
          )}
        </label>
      ))}
      {canSubmit && configuration.consent?.mode === "explicit" ? (
        <label className="performanceLocalFormConsent performanceLocalFormWide">
          <input
            aria-label={configuration.consent.text ?? "Consent"}
            name="consent-accepted"
            type="checkbox"
            value="accepted"
            required
            disabled={submissionState === "submitting"}
          />
          <span>{configuration.consent.text}</span>
          {configuration.consent.privacyPolicyDestination ? (
            <a href={configuration.consent.privacyPolicyDestination}>Privacy policy</a>
          ) : null}
        </label>
      ) : null}
      <button type="submit" disabled={!canSubmit || visualDisabled || submissionState === "submitting"}>
        {submissionState === "submitting" ? "Sending…" : configuration.submitLabel}
      </button>
      {exposeDiagnostics && submission?.readiness
        ? <FormReadinessPanel readiness={submission.readiness} />
        : null}
    </form>
  );
}

function FormReadinessPanel({
  readiness,
}: {
  readiness: PerformanceLocalFormReadinessRead;
}) {
  return (
    <aside
      className="performanceLocalFormReadiness"
      aria-label="Form submission readiness"
      data-form-readiness={readiness.status}
    >
      <div className="performanceLocalFormReadinessHeading">
        <strong>Submission readiness</strong>
        <span>{readiness.status === "ready" ? "Ready" : "Blocked"}</span>
      </div>
      <dl>
        <div><dt>Provider</dt><dd>{readiness.provider_state.adapter_registered ? "Ready" : "Missing"}</dd></div>
        <div><dt>Privacy / consent</dt><dd>{readiness.privacy.ready ? "Ready" : "Missing"}</dd></div>
        <div><dt>Retention</dt><dd>{readiness.retention.ready ? "Ready" : "Missing"}</dd></div>
        <div><dt>Spam protection</dt><dd>{readiness.spam.ready ? "Ready" : "Missing"}</dd></div>
        <div><dt>Success / failure</dt><dd>{readiness.behavior.ready ? "Ready" : "Missing"}</dd></div>
        <div><dt>Security / audit</dt><dd>{readiness.security.ready && readiness.audit_identity ? "Ready" : "Missing"}</dd></div>
      </dl>
      {readiness.blockers.length ? (
        <ul>
          {readiness.blockers.map((blocker) => (
            <li key={`${blocker.code}:${blocker.field}`}>{blocker.reason}</li>
          ))}
        </ul>
      ) : null}
    </aside>
  );
}

function formStringValue(values: FormData, key: string): string {
  const value = values.get(key);
  return typeof value === "string" ? value : "";
}

function createFormIdempotencyKey(): string | null {
  if (typeof globalThis.crypto?.getRandomValues !== "function") return null;
  const bytes = new Uint8Array(24);
  globalThis.crypto.getRandomValues(bytes);
  return `atlas-${Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")}`;
}

function safeFormStatusMessage(value: unknown): string {
  return typeof value === "string" && value === value.trim() && value.length <= 300 &&
    !/[\u0000-\u001f\u007f]/.test(value)
    ? value
    : "";
}

function PerformanceFooter({
  contact,
  component,
  navigation,
  email,
  destinationForGeneratedPageId,
}: {
  contact: PerformanceLocalGovernedContact | null;
  component: PageComponentInstance;
  navigation?: PageComponentInstance;
  email: string;
  destinationForGeneratedPageId: (generatedPageId: number) => string;
}) {
  const data = component.resolved_data;
  const displayName = cleanText(data.company_name) || cleanText(data.display_name);
  const tree = navigation ? buildNavigationTree(asArray(navigation.resolved_data.items)) : { nodes: [], error: null };
  return (
    <footer className="performanceLocalFooter" data-component-key="site_footer">
      <div className="performanceLocalContainer performanceLocalFooterGrid">
        <div className="performanceLocalFooterBrand">
          <WebsiteIdentityLogo
            identityAssets={asRecord(data.identity_assets)}
            slot="footer_logo"
            displayName={displayName}
          />
          <strong>{displayName}</strong>
          {cleanText(data.business_type) ? <span>{cleanText(data.business_type)}</span> : null}
        </div>
        {!tree.error && tree.nodes.length ? (
          <nav aria-label={cleanText(navigation?.resolved_data.label) || "Footer navigation"}>
            <ul>
              {tree.nodes.map((node) => (
                <NavigationBranch
                  key={node.navigationItemId}
                  node={node}
                  destinationForGeneratedPageId={destinationForGeneratedPageId}
                />
              ))}
            </ul>
          </nav>
        ) : null}
        <div className="performanceLocalFooterContact">
          {contact ? <PhoneLink contact={contact} compact={false} /> : null}
          {email ? <EmailLink value={email} /> : null}
          {cleanText(data.license_number) ? <span>License {cleanText(data.license_number)}</span> : null}
        </div>
      </div>
    </footer>
  );
}

function StickyMobileActions({
  callLabel,
  contact,
  estimateDestination,
  estimateLabel,
  attributes,
}: {
  callLabel: string;
  contact: PerformanceLocalGovernedContact | null;
  estimateDestination: string | null;
  estimateLabel: string;
  attributes: PerformanceLocalRenderedComponentAttributes;
}) {
  if (!contact && !estimateDestination) return null;
  return (
    <aside className="performanceLocalStickyActions" aria-label="Contact actions" {...attributes}>
      {contact ? <PhoneLink contact={contact} compact label={callLabel} /> : null}
      {estimateDestination ? <a href={estimateDestination}>{estimateLabel}</a> : null}
    </aside>
  );
}

function BackToTopControl({ suppressed }: { suppressed: boolean }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const updateVisibility = () => {
      setVisible(window.scrollY >= Math.max(480, window.innerHeight * 0.75));
    };
    updateVisibility();
    window.addEventListener("scroll", updateVisibility, { passive: true });
    return () => window.removeEventListener("scroll", updateVisibility);
  }, []);
  if (!visible || suppressed) return null;
  return (
    <button
      className="performanceLocalBackToTop"
      type="button"
      aria-label="Back to top"
      data-component-key="back_to_top_control"
      onClick={() => {
        const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
        window.scrollTo({ top: 0, behavior: reducedMotion ? "auto" : "smooth" });
      }}
    >
      <ArrowUp aria-hidden="true" />
    </button>
  );
}

function PhoneLink({
  compact,
  contact,
  label,
}: {
  compact: boolean;
  contact: PerformanceLocalGovernedContact;
  label?: string;
}) {
  return (
    <a className={`performanceLocalButton performanceLocalPhone${compact ? " performanceLocalButtonCompact" : ""}`} href={contact.callDestination}>
      <Phone size={18} aria-hidden="true" />
      <span>{label ?? (compact ? "Call" : `Call ${contact.phoneDisplay}`)}</span>
    </a>
  );
}

function EmailLink({ value }: { value: string }) {
  const email = value.trim();
  if (!email || !email.includes("@") || /[\r\n]/.test(email)) return null;
  return (
    <a className="performanceLocalButton performanceLocalButtonSecondary" href={`mailto:${email}`}>
      <Mail size={18} aria-hidden="true" />
      <span>Email</span>
    </a>
  );
}

type NavigationResolution = {
  error: string | null;
  nodes: ResolvedNavigationItem[];
};

function resolveHeaderNavigation(
  primary?: PageComponentInstance,
  utility?: PageComponentInstance,
): NavigationResolution {
  const primaryTree = primary
    ? buildNavigationTree(asArray(primary.resolved_data.items))
    : { nodes: [], error: null };
  if (primaryTree.error) return primaryTree;
  const utilityTree = utility
    ? buildNavigationTree(asArray(utility.resolved_data.items))
    : { nodes: [], error: null };
  if (utilityTree.error) return utilityTree;
  const seenTargets = new Set<number>();
  const primaryNodes = deduplicateNavigation(primaryTree.nodes, seenTargets);
  const utilityNodes = deduplicateNavigation(utilityTree.nodes, seenTargets);
  return { nodes: [...primaryNodes, ...utilityNodes], error: null };
}

function deduplicateNavigation(
  nodes: ResolvedNavigationItem[],
  seenTargets: Set<number>,
): ResolvedNavigationItem[] {
  const result: ResolvedNavigationItem[] = [];
  for (const node of nodes) {
    if (seenTargets.has(node.targetPlannedPageId)) continue;
    seenTargets.add(node.targetPlannedPageId);
    result.push({
      ...node,
      children: deduplicateNavigation(node.children, seenTargets),
    });
  }
  return result;
}

function bindMediaToExactTargets(components: PageComponentInstance[]): MediaBindingResult {
  const validTargets = new Set(
    components
      .filter((component) => component.component_key !== "media_placement")
      .map((component) => component.instance_key),
  );
  const byTarget = new Map<string, PageComponentInstance>();
  const errors: string[] = [];
  const unbound: PageComponentInstance[] = [];
  for (const component of components) {
    if (component.component_key !== "media_placement") continue;
    const target = cleanText(component.input_bindings.target_component_instance_key);
    if (!target || !validTargets.has(target)) {
      unbound.push(component);
      continue;
    }
    if (byTarget.has(target)) {
      byTarget.delete(target);
      errors.push(`Multiple governed media placements target exact component instance ${target}; all media for that target were hidden.`);
      continue;
    }
    if (errors.some((error) => error.includes(`instance ${target};`))) continue;
    byTarget.set(target, component);
  }
  return { byTarget, errors, unbound };
}

function renderableMedia(component: PageComponentInstance): RenderableMedia | null {
  const data = component.resolved_data;
  const source = cleanText(data.asset_url);
  const alt = cleanText(data.alt_text);
  if (!source || !alt || !safeAssetUrl(source)) return null;
  const resolution = resolvePageMediaDisplayPreset(data, component.input_bindings);
  if (resolution.error || !resolution.preset) return null;
  return {
    alt,
    caption: cleanText(data.caption),
    focalX: boundedNumber(data.focal_x, 0.5),
    focalY: boundedNumber(data.focal_y, 0.5),
    preset: resolution.preset,
    role: cleanText(data.image_role),
    source,
    title: cleanText(data.image_title),
  };
}

function resolveCampaign(
  campaign: PerformanceLocalCampaign | null,
  websiteId: number,
  pageId: number,
  previewedAt: Date,
  estimateForm: PerformanceLocalEstimateFormConfiguration | null,
  rendererIdentity: PerformanceLocalRendererIdentity,
): {
  campaign: PerformanceLocalCampaign | null;
  error: string | null;
  attributes: PerformanceLocalRenderedComponentAttributes | null;
} {
  const resolution = resolveOptionalComponent(
    "campaign_banner",
    campaign,
    websiteId,
    "desktop",
    previewedAt,
    pageId,
  );
  const exactDestinationError = campaign && (
    !estimateForm ||
    campaign.destinationComponentConfigurationId !== estimateForm.componentConfigurationId ||
    campaign.ctaDestination !== `#${performanceLocalFormDomId(estimateForm.componentConfigurationId)}`
  )
    ? "Campaign CTA does not resolve to the exact configured compact estimate form."
    : null;
  if (!campaign?.enabled || !resolution.visible || exactDestinationError) {
    return {
      campaign: null,
      error: [resolution.errors.join(" "), exactDestinationError].filter(Boolean).join(" ") || null,
      attributes: null,
    };
  }
  return {
    campaign,
    error: null,
    attributes: renderedComponentAttributes(
      performanceLocalOptionalComponentAttributes("campaign_banner", resolution),
      rendererIdentity,
    ),
  };
}

function rendererValidationError(
  page: GeneratedPage,
  composition: PageComposition,
): string | null {
  const compositionError = compositionValidationError(composition);
  if (compositionError) return compositionError;
  if (page.id !== composition.generated_page_id) {
    return "The semantic composition does not belong to this Generated Page.";
  }
  if (!page.website_id || page.website_id !== composition.website_id) {
    return "The Generated Page and composition cross the Website ownership boundary.";
  }
  return null;
}

function indexComponents(components: PageComponentInstance[]) {
  const byKey = new Map<string, PageComponentInstance[]>();
  for (const component of components) {
    const values = byKey.get(component.component_key) ?? [];
    values.push(component);
    byKey.set(component.component_key, values);
  }
  return byKey;
}

function first(
  index: Map<string, PageComponentInstance[]>,
  key: string,
): PageComponentInstance | undefined {
  return index.get(key)?.[0];
}

function focusableElements(root: HTMLElement | null): HTMLElement[] {
  if (!root) return [];
  return Array.from(
    root.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) =>
    !element.closest('[hidden], [aria-hidden="true"], [inert]') &&
    element.getAttribute("aria-disabled") !== "true",
  );
}

function safeAssetUrl(value: string): boolean {
  if (!value || /[\u0000-\u001f\u007f\\]/.test(value)) return false;
  if (value.startsWith("/")) return !value.startsWith("//");
  try {
    const parsed = new URL(value);
    return (
      (parsed.protocol === "http:" || parsed.protocol === "https:") &&
      !parsed.username &&
      !parsed.password &&
      (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1" || parsed.hostname === "[::1]")
    );
  } catch {
    return false;
  }
}

function safePhoneDestination(value: string): string | null {
  const phone = value.replace(/[^\d+]/g, "");
  return /^\+?\d{6,25}$/.test(phone) ? `tel:${phone}` : null;
}

function validatedOpaqueCssColor(value: unknown): string | null {
  const color = cleanText(value);
  return /^#[\da-f]{6}$/i.test(color) ? color : null;
}

function contrastTextColor(value: string): "#000000" | "#ffffff" {
  const channels = [1, 3, 5].map((offset) => parseInt(value.slice(offset, offset + 2), 16) / 255);
  const [red, green, blue] = channels.map((channel) =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  );
  const luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue;
  return luminance > 0.179 ? "#000000" : "#ffffff";
}

function boundedNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1
    ? value
    : fallback;
}

function positiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}

function cleanText(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value).trim() : "";
}

function sourceText(value: unknown): string {
  return typeof value === "string" && value.trim().length > 0 ? value : "";
}

function sourceSectionIdentity(component: PageComponentInstance): string {
  return cleanText(component.input_bindings.section_key);
}

function validateEstimateFormConfiguration(
  value: PerformanceLocalEstimateFormConfiguration | null | undefined,
  deliveryMode: PerformanceLocalRendererIdentity["deliveryMode"],
): PerformanceLocalEstimateFormConfiguration | null {
  if (
    !value ||
    !positiveInteger(value.componentConfigurationId) ||
    !safeDomId(value.componentInstanceKey) ||
    !cleanText(value.ctaLabel) ||
    !cleanText(value.previewNotice) ||
    !cleanText(value.submitLabel)
  ) return null;
  const providerDisabled =
    value.providerState.submissionState !== "disabled_pending_provider_configuration" ||
    (value.providerState.providerKey ?? null) !== null ||
    value.providerState.destination !== null ||
    value.providerState.destinationConfigured === true ||
    value.providerState.canSubmit !== false ||
    value.providerState.collectsData !== false
      ? false
      : true;
  const providerConfigured =
    ["rehearsal_ready", "production_configured"].includes(value.providerState.submissionState) &&
    value.providerState.destination === null &&
    (value.providerState.providerKey ?? null) === null &&
    value.providerState.destinationConfigured === true &&
    value.providerState.canSubmit === value.providerState.collectsData;
  if (!providerDisabled && !providerConfigured) return null;
  if (value.consent) {
    if (!safePrivacyPolicyDestination(value.consent.privacyPolicyDestination, deliveryMode)) return null;
    if (value.consent.mode === "explicit") {
      if (!cleanText(value.consent.text) || !cleanText(value.consent.textVersion)) return null;
    } else if (
      value.consent.mode !== "not_required" ||
      value.consent.text !== null ||
      value.consent.textVersion !== null
    ) return null;
  }
  if (value.visualState && !["idle", "disabled", "error", "success"].includes(value.visualState)) {
    return null;
  }
  if (!Array.isArray(value.fields) || value.fields.length !== 5) return null;
  const expectedFields = [
    ["name", "Name"],
    ["phone", "Phone"],
    ["postal-code", "ZIP code"],
    ["requested-service", "Requested service"],
    ["message", "Optional message"],
  ] as const satisfies readonly (readonly [PerformanceLocalEstimateFieldKey, string])[];
  const expected = new Set<PerformanceLocalEstimateFieldKey>(expectedFields.map(([key]) => key));
  const seen = new Set<PerformanceLocalEstimateFieldKey>();
  for (const [index, field] of value.fields.entries()) {
    const expectedField = expectedFields[index];
    if (
      !field ||
      !expectedField ||
      field.key !== expectedField[0] ||
      field.label !== expectedField[1] ||
      field.order !== index + 1 ||
      !expected.has(field.key) ||
      seen.has(field.key) ||
      !cleanText(field.accessibilityLabel) ||
      !Number.isSafeInteger(field.maxLength) ||
      field.maxLength <= 0 ||
      field.maxLength > 10_000 ||
      !cleanText(field.providerMapping) ||
      !["nonempty_text", "phone", "postal_code", "free_text"].includes(field.validation?.rule) ||
      !Number.isSafeInteger(field.validation?.minimumLength) ||
      field.validation.minimumLength < 0 ||
      field.validation.maximumLength !== field.maxLength ||
      field.validation.minimumLength > field.validation.maximumLength ||
      !["half", "full"].includes(field.responsive?.desktop) ||
      !["half", "full"].includes(field.responsive?.tablet) ||
      field.responsive?.mobile !== "full"
    ) return null;
    if (field.control !== "input" && field.control !== "textarea") return null;
    if (field.autoComplete && !["off", "name", "tel", "postal-code"].includes(field.autoComplete)) return null;
    if (field.control === "textarea" && field.type) return null;
    seen.add(field.key);
  }
  return seen.size === expected.size ? value : null;
}

function validateFormSubmission(
  value: PerformanceLocalFormSubmission | null | undefined,
  form: PerformanceLocalEstimateFormConfiguration | null,
  websiteId: number,
  deliveryMode: PerformanceLocalRendererIdentity["deliveryMode"],
): ResolvedPerformanceLocalFormSubmission | null {
  if (!value || !form) return null;
  const readiness = value.readiness;
  if (readiness.component_configuration_id !== form.componentConfigurationId) return null;
  if (readiness.status === "blocked") {
    if (readiness.can_submit || value.endpoint !== null || value.submit) return null;
    return Object.freeze({
      canSubmit: false,
      endpoint: null,
      readiness,
      submit: undefined,
    });
  }

  const expectedEndpoint =
    `/api/websites/${websiteId}/forms/${form.componentConfigurationId}/submissions`;
  const consentMatches = readiness.privacy.consent_mode === form.consent?.mode && (
    readiness.privacy.consent_mode !== "explicit" ||
    readiness.privacy.consent_text_version === form.consent?.textVersion
  );
  const providerModeAllowed = readiness.provider_state.test_only
    ? deliveryMode === "activation_rehearsal"
    : deliveryMode === "active";
  if (
    readiness.status !== "ready" ||
    readiness.can_submit !== true ||
    readiness.blockers.length !== 0 ||
    !cleanText(readiness.submission_state) ||
    readiness.provider_state.provider_key !== null ||
    !readiness.provider_state.destination_configured ||
    !readiness.provider_state.adapter_registered ||
    !providerModeAllowed ||
    !readiness.privacy.ready ||
    !readiness.privacy.destination_configured ||
    !consentMatches ||
    !readiness.retention.ready ||
    !readiness.spam.ready ||
    !readiness.behavior.ready ||
    !readiness.security.ready ||
    !cleanText(readiness.security.same_origin_policy) ||
    !cleanText(readiness.security.csrf_policy) ||
    !safeCsrfToken(readiness.security.csrf_token) ||
    !positiveInteger(readiness.security.request_size_limit_bytes) ||
    !cleanText(readiness.security.idempotency_strategy) ||
    !cleanText(readiness.audit_identity) ||
    value.endpoint !== expectedEndpoint ||
    typeof value.submit !== "function"
  ) return null;
  return Object.freeze({
    canSubmit: true,
    endpoint: value.endpoint,
    readiness,
    submit: value.submit,
  });
}

function safePrivacyPolicyDestination(
  value: unknown,
  deliveryMode: PerformanceLocalRendererIdentity["deliveryMode"],
): boolean {
  if (typeof value !== "string" || value !== value.trim() || /[\u0000-\u001f\u007f\\]/.test(value)) {
    return false;
  }
  if (/^\/(?!\/)[^\s\\]*$/.test(value)) {
    return !value.includes("?") && !value.includes("#");
  }
  try {
    const parsed = new URL(value);
    const loopbackRehearsal = deliveryMode === "activation_rehearsal" &&
      parsed.protocol === "http:" &&
      ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
    return (parsed.protocol === "https:" || loopbackRehearsal) &&
      !parsed.username &&
      !parsed.password &&
      !parsed.search &&
      !parsed.hash &&
      parsed.pathname.startsWith("/") &&
      Boolean(parsed.hostname);
  } catch {
    return false;
  }
}

function safeCsrfToken(value: unknown): value is string {
  return typeof value === "string" && value.length >= 16 && value.length <= 512 &&
    /^[A-Za-z0-9._~+\/-]+$/.test(value);
}

function validateGovernedContact(
  value: PerformanceLocalGovernedContact | null | undefined,
  websiteId: number,
): PerformanceLocalGovernedContact | null {
  if (
    !value ||
    value.websiteId !== websiteId ||
    !cleanText(value.phoneDisplay) ||
    safePhoneDestination(value.phoneDisplay) !== value.callDestination
  ) return null;
  return value;
}

function validateStickyActionConfiguration(
  value: PerformanceLocalStickyActionConfiguration | null | undefined,
  form: PerformanceLocalEstimateFormConfiguration | null,
): PerformanceLocalStickyActionConfiguration | null {
  if (
    !value ||
    value.enabled !== true ||
    !positiveInteger(value.componentConfigurationId) ||
    !positiveInteger(value.destinationComponentConfigurationId) ||
    typeof value.desktopHeaderActionsEnabled !== "boolean" ||
    typeof value.mobileStickyActionsEnabled !== "boolean" ||
    !cleanText(value.callLabel) ||
    !cleanText(value.estimateLabel) ||
    !form ||
    value.destinationComponentConfigurationId !== form.componentConfigurationId
  ) return null;
  return value;
}

function safeDomId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z][A-Za-z0-9_:.-]*$/.test(value);
}

function useMobileViewport(): boolean {
  const query = "(max-width: 760px)";
  const [mobile, setMobile] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false,
  );
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const update = () => setMobile(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);
  return mobile;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function trustFacts(component: PageComponentInstance): { label: string; value: string }[] {
  const data = component.resolved_data;
  return [
    cleanText(data.license_number)
      ? { label: "License", value: cleanText(data.license_number) }
      : null,
    cleanText(data.certified_operator)
      ? { label: "Certified operator", value: cleanText(data.certified_operator) }
      : null,
  ].filter((item): item is { label: string; value: string } => item !== null);
}

function structuredSteps(component: PageComponentInstance): { heading: string; body: string }[] {
  return asArray(component.resolved_data.steps)
    .map((value) => {
      if (typeof value === "string") return { heading: "", body: cleanText(value) };
      const step = asRecord(value);
      return {
        heading: cleanText(step.heading) || cleanText(step.title) || cleanText(step.label),
        body: cleanText(step.body) || cleanText(step.description),
      };
    })
    .filter((step) => step.heading || step.body);
}

function governedOptionalState(
  key: Parameters<typeof performanceLocalOptionalConfiguration>[0],
  websiteId: number,
  accessibilityLabel: string,
  configuration: Readonly<Record<string, unknown>>,
  viewport: "desktop" | "tablet" | "mobile" = "desktop",
  pageId?: number | null,
  rendererIdentity: PerformanceLocalRendererIdentity = THEME_LAB_RENDERER_IDENTITY,
): {
  configuration: PerformanceLocalOptionalConfiguration;
  resolution: OptionalComponentResolution;
  attributes: PerformanceLocalRenderedComponentAttributes | null;
} {
  const resolvedConfiguration = performanceLocalOptionalConfiguration(
    key,
    websiteId,
    accessibilityLabel,
    configuration,
  );
  const resolution = resolveOptionalComponent(
    key,
    resolvedConfiguration,
    websiteId,
    viewport,
    new Date(),
    pageId,
  );
  return {
    configuration: resolvedConfiguration,
    resolution,
    attributes: resolution.visible
      ? renderedComponentAttributes(
          performanceLocalOptionalComponentAttributes(key, resolution),
          rendererIdentity,
        )
      : null,
  };
}

function renderedComponentAttributes(
  attributes: OptionalComponentDiagnosticAttributes,
  rendererIdentity: PerformanceLocalRendererIdentity,
): PerformanceLocalRenderedComponentAttributes {
  // These attributes are intentionally diagnostic-only. Canonical delivery
  // exposes its V3 identity on the renderer root, never Theme Lab internals on
  // each public component.
  if (!rendererIdentity.exposeDiagnostics) return Object.freeze({});
  return Object.freeze({
    ...attributes,
    "data-component-version": rendererIdentity.componentVersion,
    "data-component-theme-compatibility": rendererIdentity.themeCompatibility,
  });
}

export default PerformanceLocalRenderer;
