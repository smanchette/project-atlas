import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import PerformanceLocalRenderer, {
  performanceLocalFormDomId,
} from "./PerformanceLocalRenderer";
import type { PerformanceLocalDeliveryConfiguration } from "./performanceLocalDelivery";
import { resolvePerformanceLocalStickyVisibility } from "./performanceLocalInteractions";
import {
  PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY,
  PERFORMANCE_LOCAL_V3_THEME_VERSION,
} from "./performanceLocalThemeV3";
import type { PerformanceLocalV5LayoutAudit } from "./performanceLocalV5LayoutContract";
import {
  PerformanceLocalV5BackToTop,
  PerformanceLocalV5CampaignBanner,
  PerformanceLocalV5EstimatePageLayout,
  PerformanceLocalV5LayoutBody,
  PerformanceLocalV5LocationMapSection,
  PerformanceLocalV5ReviewTrustSection,
  PerformanceLocalV5SiteFooter,
  PerformanceLocalV5SiteHeader,
  PerformanceLocalV5SpecialPageLayout,
  PerformanceLocalV5StickyActions,
  PerformanceLocalV5TopConversionStack,
  type PerformanceLocalV5ReviewMode,
} from "./PerformanceLocalV5Layouts";
import {
  performanceLocalV5EstimatePageIsRenderable,
  performanceLocalV5SpecialPageState,
  resolvePerformanceLocalV5TopAction,
  type PerformanceLocalV5ActionConfiguration,
  type PerformanceLocalV5FormIdentity,
} from "./performanceLocalV5Actions";
import {
  resolvePerformanceLocalV5OptionalModules,
  type PerformanceLocalV5OptionalModulePageConfiguration,
  type PerformanceLocalV5OptionalModulePresentation,
  type PerformanceLocalV5OptionalModulesResolution,
} from "./performanceLocalV5OptionalModules";
import type {
  GeneratedPage,
  PageComponentInstance,
  PageComposition,
} from "../types";

export type PerformanceLocalV5ReadinessProjection = Readonly<{
  mediaReady: boolean;
  qaReady: boolean;
  formReady: boolean;
  activationReady: false;
  exportReady: false;
  publicationReady: false;
}>;

export type PerformanceLocalV5RendererProps = Readonly<{
  actionConfiguration: PerformanceLocalV5ActionConfiguration;
  audit: PerformanceLocalV5LayoutAudit;
  campaignBannerEnabled: boolean;
  composition: PageComposition;
  page: GeneratedPage;
  optionalModuleApprovedLocalImages?: Readonly<Record<string, string>>;
  optionalModuleConfiguration?: PerformanceLocalV5OptionalModulePageConfiguration;
  optionalModuleGovernedTargetCity?: string | null;
  optionalModuleGovernedTargetState?: string | null;
  optionalModulePresentation?: PerformanceLocalV5OptionalModulePresentation;
  previewedAt?: Date;
  readiness: PerformanceLocalV5ReadinessProjection;
  reviewMode: PerformanceLocalV5ReviewMode;
  previewSurface: PerformanceLocalV5PreviewSurface;
  v3Configuration: PerformanceLocalDeliveryConfiguration;
}>;

export type PerformanceLocalV5PreviewSurface =
  | "estimate"
  | "generated_page"
  | "location_map"
  | "review_trust"
  | "review_trust_location_map"
  | "special"
  | "sticky_disabled";

export function performanceLocalV5FooterBoundaryReached(input: Readonly<{
  footerTop: number;
  viewportBottom: number;
}>): boolean {
  if (!Number.isFinite(input.footerTop) || !Number.isFinite(input.viewportBottom) || input.viewportBottom <= 0) return true;
  return input.footerTop <= input.viewportBottom;
}

export function PerformanceLocalV5Renderer({
  actionConfiguration,
  audit,
  campaignBannerEnabled,
  composition,
  optionalModuleApprovedLocalImages = Object.freeze({}),
  optionalModuleConfiguration = Object.freeze({}),
  optionalModuleGovernedTargetCity = null,
  optionalModuleGovernedTargetState = null,
  optionalModulePresentation = "public",
  page,
  previewedAt = new Date(),
  readiness,
  reviewMode,
  previewSurface,
  v3Configuration,
}: PerformanceLocalV5RendererProps) {
  const layoutKey = audit.layoutKey;
  const pageType = audit.pageType;
  if (
    audit.resolutionStatus !== "resolved" ||
    audit.status !== "ready" ||
    !audit.layoutReady ||
    !layoutKey ||
    !pageType
  ) return <PerformanceLocalV5Unavailable audit={audit} />;

  if (!v3Configuration || !exactV3ConversionInputForV5(v3Configuration, composition)) {
    return <PerformanceLocalV5Unavailable audit={audit} conversionBlocked />;
  }

  const optionalModules = resolvePerformanceLocalV5OptionalModules(optionalModuleConfiguration, {
    approvedLocalImages: optionalModuleApprovedLocalImages,
    governedPhoneDisplay: v3Configuration.governedContact?.phoneDisplay ?? null,
    governedTargetCity: optionalModuleGovernedTargetCity,
    governedTargetState: optionalModuleGovernedTargetState,
    pageType,
    presentation: optionalModulePresentation,
  });

  if (previewSurface === "special" || previewSurface === "estimate") {
    if (pageType !== "city_service") return <PerformanceLocalV5Unavailable audit={audit} conversionBlocked />;
    return (
      <PerformanceLocalV5ConditionalRenderer
        actionConfiguration={actionConfiguration}
        audit={audit}
        composition={composition}
        page={page}
        previewedAt={previewedAt}
        previewSurface={previewSurface}
        v3Configuration={v3Configuration}
      />
    );
  }

  if (pageType === "city_service") {
    const exactFormIdentity = performanceLocalV5ExactFormIdentity(v3Configuration);
    const topAction = resolvePerformanceLocalV5TopAction({
      configuration: actionConfiguration,
      currentRoute: `/theme-lab/performance-local/v5/generated-pages/${page.id}`,
      currentSurface: "site",
      evaluatedAt: previewedAt,
      exactFormIdentity,
    }).action;
    const topStackActive = Boolean(v3Configuration.governedContact) || topAction.mode !== "disabled";
    const legacyStickyActions = topStackActive
      ? { ...v3Configuration.stickyActions, desktopHeaderActionsEnabled: false }
      : v3Configuration.stickyActions;
    return (
      <div
        className="performanceLocalV5CityServicePreview"
        data-v5-site-root="true"
        data-v5-preservation-control="below-hero-legacy-subtree"
        data-v5-top-preview="hero-and-conversion-stack"
        data-v5-page-type={pageType}
        data-v5-layout-key={layoutKey}
        data-v5-layout-ready="true"
        data-v5-top-action-enabled={topAction.mode === "disabled" ? "false" : "true"}
      >
        <PerformanceLocalV5TopConversionStack
          action={topAction}
          callLabel={v3Configuration.stickyActions.callLabel}
          contact={v3Configuration.governedContact}
        />
        <PerformanceLocalRenderer
          afterHeroContent={optionalModules.reviewTrust ? (
            <PerformanceLocalV5ReviewTrustSection resolution={optionalModules.reviewTrust} />
          ) : null}
          beforeFinalConversionContent={optionalModules.locationMap ? (
            <PerformanceLocalV5LocationMapSection
              governedContact={v3Configuration.governedContact}
              resolution={optionalModules.locationMap}
            />
          ) : null}
          page={page}
          composition={composition}
          campaign={null}
          estimateForm={v3Configuration.estimateForm}
          formSubmission={v3Configuration.formSubmission}
          governedContact={v3Configuration.governedContact}
          rendererIdentity={v3Configuration.rendererIdentity}
          stickyActions={legacyStickyActions}
          toggles={{
            ...v3Configuration.toggles,
            campaignBanner: false,
            stickyActionBar: false,
            trustStrip: false,
          }}
          previewedAt={previewedAt}
        />
      </div>
    );
  }

  return (
    <PerformanceLocalV5PurposeBuiltRenderer
      audit={audit}
      campaignBannerEnabled={campaignBannerEnabled}
      composition={composition}
      page={page}
      readiness={readiness}
      reviewMode={reviewMode}
      optionalModules={optionalModules}
      v3Configuration={v3Configuration}
    />
  );
}

function PerformanceLocalV5ConditionalRenderer({
  actionConfiguration,
  audit,
  composition,
  page,
  previewedAt,
  previewSurface,
  v3Configuration,
}: Readonly<{
  actionConfiguration: PerformanceLocalV5ActionConfiguration;
  audit: PerformanceLocalV5LayoutAudit;
  composition: PageComposition;
  page: GeneratedPage;
  previewedAt: Date;
  previewSurface: "estimate" | "special";
  v3Configuration: PerformanceLocalDeliveryConfiguration;
}>) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [formFocusRisk, setFormFocusRisk] = useState(false);
  const componentByInstanceKey = useMemo(
    () => auditedComponentIndex(audit, composition),
    [audit, composition],
  );
  const headerRegion = audit.regions.find((item) => item.regionKey === "site_header") ?? null;
  const footerRegion = audit.regions.find((item) => item.regionKey === "site_footer") ?? null;
  const header = exactRegionComponent(headerRegion, componentByInstanceKey, "website_header");
  const primaryNavigation = exactRegionComponent(headerRegion, componentByInstanceKey, "primary_navigation");
  const utilityNavigation = exactRegionComponent(headerRegion, componentByInstanceKey, "utility_navigation");
  const footer = exactRegionComponent(footerRegion, componentByInstanceKey, "website_footer");
  const footerNavigation = exactRegionComponent(footerRegion, componentByInstanceKey, "footer_navigation");
  const governedContact = v3Configuration.governedContact;
  const exactFormIdentity = performanceLocalV5ExactFormIdentity(v3Configuration);
  const estimateReady = performanceLocalV5EstimatePageIsRenderable(actionConfiguration.estimate, exactFormIdentity);
  const specialReady = performanceLocalV5SpecialPageState(actionConfiguration.special, previewedAt) === "active";
  const currentRoute = previewSurface === "special" && actionConfiguration.special.enabled
    ? actionConfiguration.special.route
    : previewSurface === "estimate" && actionConfiguration.estimate.enabled
      ? actionConfiguration.estimate.route
      : "";
  const actionResolution = resolvePerformanceLocalV5TopAction({
    configuration: actionConfiguration,
    currentRoute,
    currentSurface: previewSurface,
    evaluatedAt: previewedAt,
    exactFormIdentity,
  });
  const destinationForGeneratedPageId = (generatedPageId: number) =>
    `/theme-lab/performance-local/v5/generated-pages/${generatedPageId}`;

  if (
    !header ||
    !footer ||
    !governedContact ||
    (previewSurface === "estimate" && !estimateReady) ||
    (previewSurface === "special" && !specialReady)
  ) return <PerformanceLocalV5Unavailable audit={audit} conversionBlocked />;

  return (
    <div
      className="performanceLocalV5Site performanceLocalV5ConditionalPage"
      data-v5-site-root="true"
      data-v5-conditional-surface={previewSurface}
      data-v5-top-action-enabled={actionResolution.action.mode === "disabled" ? "false" : "true"}
      data-v5-action-resolution={actionResolution.reason}
      data-v5-menu-open={mobileMenuOpen ? "true" : "false"}
      data-v5-form-focus-risk={formFocusRisk ? "true" : "false"}
    >
      <a className="performanceLocalV5SkipLink" href="#performance-local-v5-conditional-main">Skip to main content</a>
      <PerformanceLocalV5TopConversionStack
        action={actionResolution.action}
        callLabel={v3Configuration.stickyActions.callLabel}
        contact={governedContact}
      />
      <PerformanceLocalV5SiteHeader
        component={header}
        contact={null}
        destinationForGeneratedPageId={destinationForGeneratedPageId}
        estimateDestination={null}
        estimateLabel={v3Configuration.estimateForm.ctaLabel}
        menuOpen={mobileMenuOpen}
        onMenuOpenChange={setMobileMenuOpen}
        primaryNavigation={primaryNavigation}
        utilityNavigation={utilityNavigation}
      />
      <main id="performance-local-v5-conditional-main">
        {previewSurface === "special" && actionConfiguration.special.enabled ? (
          <PerformanceLocalV5SpecialPageLayout
            callLabel={v3Configuration.stickyActions.callLabel}
            configuration={actionConfiguration.special}
            contact={governedContact}
            estimateDestination={estimateReady && actionConfiguration.estimate.enabled ? actionConfiguration.estimate.route : null}
            estimateLabel={estimateReady && actionConfiguration.estimate.enabled ? actionConfiguration.estimate.heading : null}
          />
        ) : previewSurface === "estimate" && actionConfiguration.estimate.enabled ? (
          <PerformanceLocalV5EstimatePageLayout
            configuration={actionConfiguration.estimate}
            contact={governedContact}
            estimateForm={v3Configuration.estimateForm}
            onFormFocusRiskChange={setFormFocusRisk}
          />
        ) : null}
      </main>
      <PerformanceLocalV5SiteFooter
        component={footer}
        contact={governedContact}
        destinationForGeneratedPageId={destinationForGeneratedPageId}
        navigation={footerNavigation}
      />
    </div>
  );
}

function PerformanceLocalV5PurposeBuiltRenderer({
  audit,
  campaignBannerEnabled,
  composition,
  page,
  readiness,
  reviewMode,
  optionalModules,
  v3Configuration,
}: Omit<
  PerformanceLocalV5RendererProps,
  | "actionConfiguration"
  | "optionalModuleApprovedLocalImages"
  | "optionalModuleConfiguration"
  | "optionalModuleGovernedTargetCity"
  | "optionalModuleGovernedTargetState"
  | "optionalModulePresentation"
  | "previewSurface"
  | "previewedAt"
> & Readonly<{ optionalModules: PerformanceLocalV5OptionalModulesResolution }>) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [formFocusRisk, setFormFocusRisk] = useState(false);
  const [heroConversionVisible, setHeroConversionVisible] = useState(true);
  const [footerBoundaryReached, setFooterBoundaryReached] = useState(true);
  const mobileViewport = useMobileViewport();
  const componentByInstanceKey = useMemo(
    () => auditedComponentIndex(audit, composition),
    [audit, composition],
  );
  const headerRegion = audit.regions.find((item) => item.regionKey === "site_header") ?? null;
  const footerRegion = audit.regions.find((item) => item.regionKey === "site_footer") ?? null;
  const header = exactRegionComponent(headerRegion, componentByInstanceKey, "website_header");
  const primaryNavigation = exactRegionComponent(headerRegion, componentByInstanceKey, "primary_navigation");
  const utilityNavigation = exactRegionComponent(headerRegion, componentByInstanceKey, "utility_navigation");
  const footer = exactRegionComponent(footerRegion, componentByInstanceKey, "website_footer");
  const footerNavigation = exactRegionComponent(footerRegion, componentByInstanceKey, "footer_navigation");
  const estimateForm = v3Configuration.estimateForm;
  const governedContact = v3Configuration.governedContact;
  const stickyActions = v3Configuration.stickyActions;
  const estimateDestination = `#${performanceLocalFormDomId(estimateForm.componentConfigurationId)}`;
  const estimateLabel = estimateForm.ctaLabel;
  const campaign = campaignBannerEnabled ? v3Configuration.campaign : null;

  useEffect(() => {
    if (!mobileViewport) {
      setMobileMenuOpen(false);
      setFormFocusRisk(false);
    }
  }, [mobileViewport]);

  useEffect(() => {
    const heroActions = rootRef.current?.querySelector<HTMLElement>("[data-v5-hero-actions]") ?? null;
    if (!mobileViewport || !stickyActions.mobileStickyActionsEnabled || !heroActions) {
      setHeroConversionVisible(true);
      return;
    }
    if (typeof IntersectionObserver === "undefined") {
      setHeroConversionVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => setHeroConversionVisible(Boolean(entry?.isIntersecting && entry.intersectionRatio >= 0.25)),
      { root: null, rootMargin: "-68px 0px 0px 0px", threshold: [0, 0.25, 0.5, 1] },
    );
    observer.observe(heroActions);
    return () => observer.disconnect();
  }, [mobileViewport, page.id, stickyActions.mobileStickyActionsEnabled]);

  useEffect(() => {
    setFooterBoundaryReached(true);
    const footerElement = rootRef.current?.querySelector<HTMLElement>(".performanceLocalV5Footer") ?? null;
    if (!footerElement) return;
    let animationFrame: number | null = null;
    const recomputeBoundary = () => {
      animationFrame = null;
      setFooterBoundaryReached(performanceLocalV5FooterBoundaryReached({
        footerTop: footerElement.getBoundingClientRect().top,
        viewportBottom: window.innerHeight,
      }));
    };
    const scheduleBoundaryRecompute = () => {
      if (animationFrame !== null) return;
      if (typeof window.requestAnimationFrame !== "function") {
        recomputeBoundary();
        return;
      }
      animationFrame = window.requestAnimationFrame(recomputeBoundary);
    };
    recomputeBoundary();
    window.addEventListener("scroll", scheduleBoundaryRecompute, { passive: true });
    window.addEventListener("resize", scheduleBoundaryRecompute);
    return () => {
      window.removeEventListener("scroll", scheduleBoundaryRecompute);
      window.removeEventListener("resize", scheduleBoundaryRecompute);
      if (animationFrame !== null) window.cancelAnimationFrame(animationFrame);
    };
  }, [footer?.instance_key, page.id]);

  const stickyConfigured = Boolean(
    stickyActions.enabled &&
    stickyActions.mobileStickyActionsEnabled &&
    (governedContact || estimateDestination),
  );
  const baseStickyVisibility = resolvePerformanceLocalStickyVisibility({
    actionsAvailable: stickyConfigured,
    formFocusRisk,
    heroConversionVisible,
    mobileMenuOpen,
    mobileViewport,
  });
  const stickyVisibility = footerBoundaryReached
    ? { visible: false, reason: "hidden_footer_or_post_site_content" as const }
    : baseStickyVisibility;
  const destinationForGeneratedPageId = (generatedPageId: number) =>
    `/theme-lab/performance-local/v5/generated-pages/${generatedPageId}`;
  const pageType = audit.pageType as Exclude<typeof audit.pageType, "city_service" | null>;

  return (
    <div
      ref={rootRef}
      className="performanceLocalV5Site"
      data-v5-site-root="true"
      data-atlas-adapter="performance-local-v5"
      data-atlas-adapter-version="5"
      data-composition-id={composition.id}
      data-composition-version={composition.composition_version}
      data-generated-page-id={page.id}
      data-v5-review-mode={reviewMode}
      data-v5-page-type={pageType}
      data-v5-layout-key={audit.layoutKey!}
      data-v5-layout-ready="true"
      data-v5-media-ready={readiness.mediaReady ? "true" : "false"}
      data-v5-qa-ready={readiness.qaReady ? "true" : "false"}
      data-v5-form-ready={readiness.formReady ? "true" : "false"}
      data-mobile-menu-open={mobileMenuOpen ? "true" : "false"}
      data-footer-boundary-reached={footerBoundaryReached ? "true" : "false"}
      data-v5-fixed-controls-suppressed={footerBoundaryReached ? "footer_or_post_site_content" : "false"}
      data-sticky-actions-visible={stickyVisibility.visible ? "true" : "false"}
      data-sticky-actions-reason={stickyVisibility.reason}
    >
      <a className="performanceLocalV5SkipLink" href="#performance-local-v5-main-content">Skip to main content</a>
      {campaign ? <PerformanceLocalV5CampaignBanner campaign={campaign} /> : null}
      {header ? (
        <PerformanceLocalV5SiteHeader
          component={header}
          contact={stickyActions.desktopHeaderActionsEnabled ? governedContact : null}
          destinationForGeneratedPageId={destinationForGeneratedPageId}
          estimateDestination={stickyActions.desktopHeaderActionsEnabled ? estimateDestination : null}
          estimateLabel={estimateLabel}
          menuOpen={mobileMenuOpen}
          onMenuOpenChange={setMobileMenuOpen}
          primaryNavigation={primaryNavigation}
          utilityNavigation={utilityNavigation}
        />
      ) : null}
      <main id="performance-local-v5-main-content">
        <PerformanceLocalV5LayoutBody
          callLabel={stickyActions.callLabel}
          componentByInstanceKey={componentByInstanceKey}
          countyCityPresentation={audit.countyCityPresentation}
          destinationForGeneratedPageId={destinationForGeneratedPageId}
          estimateDestination={estimateDestination}
          estimateForm={estimateForm}
          governedContact={governedContact}
          homeServicePresentation={audit.homeServicePresentation}
          layoutKey={audit.layoutKey!}
          onFormFocusRiskChange={setFormFocusRisk}
          optionalModules={optionalModules}
          pageType={pageType}
          regions={audit.regions}
          reviewMode={reviewMode}
        />
      </main>
      {footer ? (
        <PerformanceLocalV5SiteFooter
          component={footer}
          contact={governedContact}
          destinationForGeneratedPageId={destinationForGeneratedPageId}
          navigation={footerNavigation}
        />
      ) : null}
      <PerformanceLocalV5BackToTop suppressed={formFocusRisk || mobileMenuOpen || footerBoundaryReached} />
      {stickyVisibility.visible ? (
        <PerformanceLocalV5StickyActions
          callLabel={stickyActions.callLabel}
          contact={governedContact}
          estimateDestination={estimateDestination}
          estimateLabel={stickyActions.estimateLabel}
        />
      ) : null}
    </div>
  );
}

function PerformanceLocalV5Unavailable({
  audit,
  conversionBlocked = false,
}: {
  audit: PerformanceLocalV5LayoutAudit;
  conversionBlocked?: boolean;
}) {
  const messages = conversionBlocked
    ? ["The exact governed V3 conversion configuration is unavailable."]
    : audit.blockers.map((blocker) => blocker.message);
  return (
    <main
      className="performanceLocalV5Unavailable"
      role="alert"
      data-v5-layout-ready="false"
      data-v5-page-type={audit.pageType ?? "unsupported"}
      data-v5-layout-key={audit.layoutKey ?? "blocked"}
    >
      <h1>Performance Local V5 preview unavailable</h1>
      {messages.length ? <ul>{messages.map((message) => <li key={message}>{message}</li>)}</ul> : (
        <p>The source composition did not pass the V5 layout contract.</p>
      )}
    </main>
  );
}

function auditedComponentIndex(
  audit: PerformanceLocalV5LayoutAudit,
  composition: PageComposition,
): ReadonlyMap<string, PageComponentInstance> {
  const source = new Map(composition.effective_components.map((component) => [component.instance_key, component]));
  const audited = new Map<string, PageComponentInstance>();
  for (const record of audit.consumption) {
    const component = source.get(record.instanceKey);
    if (component) audited.set(record.instanceKey, component);
  }
  return audited;
}

function exactRegionComponent(
  region: PerformanceLocalV5LayoutAudit["regions"][number] | null,
  components: ReadonlyMap<string, PageComponentInstance>,
  componentKey: string,
): PageComponentInstance | null {
  if (!region) return null;
  const matches = region.sourceInstanceKeys
    .map((instanceKey) => components.get(instanceKey))
    .filter((component): component is PageComponentInstance => component?.component_key === componentKey);
  return matches.length === 1 ? matches[0] : null;
}

function performanceLocalV5ExactFormIdentity(
  configuration: PerformanceLocalDeliveryConfiguration,
): PerformanceLocalV5FormIdentity {
  return {
    componentConfigurationId: configuration.estimateForm.componentConfigurationId,
    componentInstanceKey: configuration.estimateForm.componentInstanceKey,
    destination: `#${performanceLocalFormDomId(configuration.estimateForm.componentConfigurationId)}`,
  };
}

function useMobileViewport(): boolean {
  const [mobile, setMobile] = useState(() =>
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(max-width: 760px)").matches,
  );
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(max-width: 760px)");
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return mobile;
}

export function exactV3ConversionInputForV5(
  configuration: PerformanceLocalDeliveryConfiguration,
  composition: PageComposition,
): boolean {
  if (
    configuration.rendererIdentity.themeVersion !== PERFORMANCE_LOCAL_V3_THEME_VERSION ||
    configuration.rendererIdentity.componentVersion !== "3" ||
    configuration.rendererIdentity.themeCompatibility !== PERFORMANCE_LOCAL_V3_THEME_COMPATIBILITY ||
    configuration.rendererIdentity.deliveryMode !== "inactive_draft_preview" ||
    configuration.rendererIdentity.exposeDiagnostics !== false
  ) return false;
  const form = configuration.estimateForm;
  const fieldKeys = form.fields.map((field) => field.key);
  if (
    form.fields.length !== 5 ||
    new Set(fieldKeys).size !== fieldKeys.length ||
    fieldKeys.join("|") !== "name|phone|postal-code|requested-service|message" ||
    form.providerState.canSubmit !== false ||
    form.providerState.collectsData !== false ||
    form.providerState.destination !== null ||
    form.providerState.submissionState !== "disabled_pending_provider_configuration" ||
    configuration.formSubmission.endpoint !== null ||
    configuration.formSubmission.submit !== undefined
  ) return false;
  const sticky = configuration.stickyActions;
  if (
    sticky.enabled !== true ||
    sticky.desktopHeaderActionsEnabled !== true ||
    sticky.mobileStickyActionsEnabled !== true ||
    sticky.destinationComponentConfigurationId !== form.componentConfigurationId
  ) return false;
  if (configuration.governedContact && configuration.governedContact.websiteId !== composition.website_id) return false;
  if (
    configuration.campaign &&
    (
      configuration.campaign.websiteId !== composition.website_id ||
      configuration.campaign.destinationComponentConfigurationId !== form.componentConfigurationId ||
      configuration.campaign.ctaDestination !== `#${performanceLocalFormDomId(form.componentConfigurationId)}`
    )
  ) return false;
  return (
    configuration.toggles.compactEstimateForm === true &&
    configuration.toggles.finalCta === true &&
    configuration.toggles.stickyActionBar === true
  );
}

export default PerformanceLocalV5Renderer;
