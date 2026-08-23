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
  PerformanceLocalV5LayoutBody,
  PerformanceLocalV5SiteFooter,
  PerformanceLocalV5SiteHeader,
  PerformanceLocalV5StickyActions,
  PerformanceLocalV5TopConversionStack,
  type PerformanceLocalV5ReviewMode,
  type PerformanceLocalV5TopAction,
} from "./PerformanceLocalV5Layouts";
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
  audit: PerformanceLocalV5LayoutAudit;
  campaignBannerEnabled: boolean;
  composition: PageComposition;
  page: GeneratedPage;
  previewedAt?: Date;
  readiness: PerformanceLocalV5ReadinessProjection;
  reviewMode: PerformanceLocalV5ReviewMode;
  v3Configuration: PerformanceLocalDeliveryConfiguration;
}>;

export function performanceLocalV5FooterBoundaryReached(input: Readonly<{
  footerTop: number;
  viewportBottom: number;
}>): boolean {
  if (!Number.isFinite(input.footerTop) || !Number.isFinite(input.viewportBottom) || input.viewportBottom <= 0) return true;
  return input.footerTop <= input.viewportBottom;
}

export function PerformanceLocalV5Renderer({
  audit,
  campaignBannerEnabled,
  composition,
  page,
  previewedAt = new Date(),
  readiness,
  reviewMode,
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

  if (pageType === "city_service") {
    const estimateDestination = `#${performanceLocalFormDomId(v3Configuration.estimateForm.componentConfigurationId)}`;
    const topAction = performanceLocalV5CityServiceTopAction(v3Configuration, estimateDestination);
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
      >
        <PerformanceLocalV5TopConversionStack
          action={topAction}
          callLabel={v3Configuration.stickyActions.callLabel}
          contact={v3Configuration.governedContact}
        />
        <PerformanceLocalRenderer
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
      v3Configuration={v3Configuration}
    />
  );
}

export function performanceLocalV5CityServiceTopAction(
  configuration: PerformanceLocalDeliveryConfiguration,
  estimateDestination: string,
): PerformanceLocalV5TopAction {
  const campaign = configuration.campaign;
  if (
    campaign?.enabled &&
    campaign.intent === "evergreen_conversion" &&
    campaign.ctaDestination === estimateDestination &&
    campaign.campaignLabel.trim()
  ) {
    return Object.freeze({
      destination: estimateDestination,
      label: campaign.campaignLabel,
      mode: "request_estimate" as const,
    });
  }
  return Object.freeze({ mode: "disabled" as const });
}

function PerformanceLocalV5PurposeBuiltRenderer({
  audit,
  campaignBannerEnabled,
  composition,
  page,
  readiness,
  reviewMode,
  v3Configuration,
}: Omit<PerformanceLocalV5RendererProps, "previewedAt">) {
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
