import {
  type RefObject,
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
import type { PerformanceLocalV4LayoutAudit } from "./performanceLocalV4LayoutContract";
import {
  PerformanceLocalV4BackToTop,
  PerformanceLocalV4CampaignBanner,
  PerformanceLocalV4LayoutBody,
  PerformanceLocalV4SiteFooter,
  PerformanceLocalV4SiteHeader,
  PerformanceLocalV4StickyActions,
  type PerformanceLocalV4ReviewMode,
} from "./PerformanceLocalV4Layouts";
import type {
  GeneratedPage,
  PageComponentInstance,
  PageComposition,
} from "../types";

export type PerformanceLocalV4ReadinessProjection = Readonly<{
  mediaReady: boolean;
  qaReady: boolean;
  formReady: boolean;
  activationReady: false;
  exportReady: false;
  publicationReady: false;
}>;

export type PerformanceLocalV4RendererProps = Readonly<{
  audit: PerformanceLocalV4LayoutAudit;
  campaignBannerEnabled: boolean;
  composition: PageComposition;
  page: GeneratedPage;
  previewedAt?: Date;
  readiness: PerformanceLocalV4ReadinessProjection;
  reviewMode: PerformanceLocalV4ReviewMode;
  v3Configuration: PerformanceLocalDeliveryConfiguration;
}>;

export function performanceLocalV4FooterBoundaryReached(input: Readonly<{
  footerTop: number;
  viewportBottom: number;
}>): boolean {
  if (
    !Number.isFinite(input.footerTop) ||
    !Number.isFinite(input.viewportBottom) ||
    input.viewportBottom <= 0
  ) return true;
  return input.footerTop <= input.viewportBottom;
}

export function PerformanceLocalV4Renderer({
  audit,
  campaignBannerEnabled,
  composition,
  page,
  previewedAt = new Date(),
  readiness,
  reviewMode,
  v3Configuration,
}: PerformanceLocalV4RendererProps) {
  const layoutKey = audit.layoutKey;
  const pageType = audit.pageType;
  if (
    audit.resolutionStatus !== "resolved" ||
    audit.status !== "ready" ||
    !audit.layoutReady ||
    !layoutKey ||
    !pageType
  ) {
    return <PerformanceLocalV4Unavailable audit={audit} />;
  }

  if (!v3Configuration || !exactV3ConversionInput(v3Configuration, composition)) {
    return <PerformanceLocalV4Unavailable audit={audit} conversionBlocked />;
  }

  if (pageType === "city_service") {
    return (
      <div
        data-v4-preservation-control="true"
        data-v4-page-type={pageType}
        data-v4-layout-key={layoutKey}
        data-v4-layout-ready="true"
      >
        <PerformanceLocalRenderer
          page={page}
          composition={composition}
          campaign={campaignBannerEnabled ? v3Configuration.campaign : null}
          estimateForm={v3Configuration.estimateForm}
          formSubmission={v3Configuration.formSubmission}
          governedContact={v3Configuration.governedContact}
          rendererIdentity={v3Configuration.rendererIdentity}
          stickyActions={v3Configuration.stickyActions}
          toggles={{
            ...v3Configuration.toggles,
            campaignBanner: campaignBannerEnabled,
          }}
          previewedAt={previewedAt}
        />
      </div>
    );
  }

  return (
    <PerformanceLocalV4PurposeBuiltRenderer
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

function PerformanceLocalV4PurposeBuiltRenderer({
  audit,
  campaignBannerEnabled,
  composition,
  page,
  readiness,
  reviewMode,
  v3Configuration,
}: Omit<PerformanceLocalV4RendererProps, "previewedAt">) {
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
  const headerRegion = audit.regions.find((region) => region.regionKey === "site_header") ?? null;
  const footerRegion = audit.regions.find((region) => region.regionKey === "site_footer") ?? null;
  const header = exactRegionComponent(headerRegion, componentByInstanceKey, "website_header");
  const primaryNavigation = exactRegionComponent(headerRegion, componentByInstanceKey, "primary_navigation");
  const utilityNavigation = exactRegionComponent(headerRegion, componentByInstanceKey, "utility_navigation");
  const footer = exactRegionComponent(footerRegion, componentByInstanceKey, "website_footer");
  const footerNavigation = exactRegionComponent(footerRegion, componentByInstanceKey, "footer_navigation");
  const estimateForm = v3Configuration?.estimateForm ?? null;
  const governedContact = v3Configuration?.governedContact ?? null;
  const stickyActions = v3Configuration?.stickyActions ?? null;
  const estimateDestination = estimateForm
    ? `#${performanceLocalFormDomId(estimateForm.componentConfigurationId)}`
    : null;
  const estimateLabel = estimateForm?.ctaLabel ?? "";
  const campaign = campaignBannerEnabled ? v3Configuration?.campaign ?? null : null;

  useEffect(() => {
    if (!mobileViewport) {
      setMobileMenuOpen(false);
      setFormFocusRisk(false);
    }
  }, [mobileViewport]);

  useEffect(() => {
    const heroActions = rootRef.current?.querySelector<HTMLElement>("[data-v4-hero-actions]") ?? null;
    if (!mobileViewport || !stickyActions?.mobileStickyActionsEnabled || !heroActions) {
      setHeroConversionVisible(true);
      return;
    }
    if (typeof IntersectionObserver === "undefined") {
      setHeroConversionVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        setHeroConversionVisible(Boolean(entry?.isIntersecting && entry.intersectionRatio >= 0.25));
      },
      { root: null, rootMargin: "-68px 0px 0px 0px", threshold: [0, 0.25, 0.5, 1] },
    );
    observer.observe(heroActions);
    return () => observer.disconnect();
  }, [mobileViewport, page.id, stickyActions?.mobileStickyActionsEnabled]);

  useEffect(() => {
    setFooterBoundaryReached(true);
    const footerElement = rootRef.current?.querySelector<HTMLElement>(
      ".performanceLocalV4Footer",
    ) ?? null;
    if (!footerElement) {
      setFooterBoundaryReached(true);
      return;
    }
    let animationFrame: number | null = null;
    const recomputeBoundary = () => {
      animationFrame = null;
      setFooterBoundaryReached(performanceLocalV4FooterBoundaryReached({
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
    stickyActions?.enabled &&
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
    `/theme-lab/performance-local/v4/generated-pages/${generatedPageId}`;
  const layoutKey = audit.layoutKey!;
  const pageType = audit.pageType as Exclude<typeof audit.pageType, "city_service" | null>;

  return (
    <div
      ref={rootRef}
      className="performanceLocalV4Site"
      data-atlas-adapter="performance-local-v4"
      data-atlas-adapter-version="4"
      data-composition-id={composition.id}
      data-composition-version={composition.composition_version}
      data-generated-page-id={page.id}
      data-v4-review-mode={reviewMode}
      data-v4-page-type={pageType}
      data-v4-layout-key={layoutKey}
      data-v4-layout-ready={audit.layoutReady ? "true" : "false"}
      data-v4-media-ready={readiness.mediaReady ? "true" : "false"}
      data-v4-qa-ready={readiness.qaReady ? "true" : "false"}
      data-v4-form-ready={readiness.formReady ? "true" : "false"}
      data-mobile-menu-open={mobileMenuOpen ? "true" : "false"}
      data-footer-boundary-reached={footerBoundaryReached ? "true" : "false"}
      data-v4-fixed-controls-suppressed={footerBoundaryReached ? "footer_or_post_site_content" : "false"}
      data-sticky-actions-visible={stickyVisibility.visible ? "true" : "false"}
      data-sticky-actions-reason={stickyVisibility.reason}
    >
      <a className="performanceLocalV4SkipLink" href="#performance-local-v4-main-content">
        Skip to main content
      </a>
      {campaign ? <PerformanceLocalV4CampaignBanner campaign={campaign} /> : null}
      {header ? (
        <PerformanceLocalV4SiteHeader
          component={header}
          contact={stickyActions?.desktopHeaderActionsEnabled ? governedContact : null}
          destinationForGeneratedPageId={destinationForGeneratedPageId}
          estimateDestination={stickyActions?.desktopHeaderActionsEnabled ? estimateDestination : null}
          estimateLabel={estimateLabel}
          menuOpen={mobileMenuOpen}
          onMenuOpenChange={setMobileMenuOpen}
          primaryNavigation={primaryNavigation}
          utilityNavigation={utilityNavigation}
        />
      ) : null}
      <main id="performance-local-v4-main-content">
        <PerformanceLocalV4LayoutBody
          componentByInstanceKey={componentByInstanceKey}
          destinationForGeneratedPageId={destinationForGeneratedPageId}
          estimateDestination={estimateDestination}
          estimateForm={estimateForm}
          governedContact={governedContact}
          layoutKey={layoutKey}
          onFormFocusRiskChange={setFormFocusRisk}
          pageType={pageType}
          regions={audit.regions}
          reviewMode={reviewMode}
        />
      </main>
      {footer ? (
        <PerformanceLocalV4SiteFooter
          component={footer}
          contact={governedContact}
          destinationForGeneratedPageId={destinationForGeneratedPageId}
          navigation={footerNavigation}
        />
      ) : null}
      <PerformanceLocalV4BackToTop
        suppressed={formFocusRisk || mobileMenuOpen || footerBoundaryReached}
      />
      {stickyVisibility.visible && stickyActions ? (
        <PerformanceLocalV4StickyActions
          callLabel={stickyActions.callLabel}
          contact={governedContact}
          estimateDestination={estimateDestination}
          estimateLabel={stickyActions.estimateLabel}
        />
      ) : null}
      <output
        hidden
        data-v4-renderer-diagnostics="true"
        data-v4-diagnostic-identity={audit.diagnosticIdentity}
      >
        {JSON.stringify({
          blockers: audit.blockers,
          diagnostics: audit.diagnostics,
          missingOptionalRegionKeys: audit.missingOptionalRegionKeys,
          readiness,
        })}
      </output>
    </div>
  );
}

function PerformanceLocalV4Unavailable({
  audit,
  conversionBlocked = false,
}: {
  audit: PerformanceLocalV4LayoutAudit;
  conversionBlocked?: boolean;
}) {
  const messages = conversionBlocked
    ? ["The exact governed V3 conversion configuration is unavailable."]
    : audit.blockers.map((blocker) => blocker.message);
  return (
    <main
      className="performanceLocalV4Unavailable"
      role="alert"
      data-v4-layout-ready="false"
      data-v4-page-type={audit.pageType ?? "unsupported"}
      data-v4-layout-key={audit.layoutKey ?? "blocked"}
    >
      <h1>Performance Local V4 preview unavailable</h1>
      {messages.length ? (
        <ul>{messages.map((message) => <li key={message}>{message}</li>)}</ul>
      ) : (
        <p>The source composition did not pass the V4 layout contract.</p>
      )}
    </main>
  );
}

function auditedComponentIndex(
  audit: PerformanceLocalV4LayoutAudit,
  composition: PageComposition,
): ReadonlyMap<string, PageComponentInstance> {
  const source = new Map(
    composition.effective_components.map((component) => [component.instance_key, component]),
  );
  const audited = new Map<string, PageComponentInstance>();
  for (const record of audit.consumption) {
    const component = source.get(record.instanceKey);
    if (component) audited.set(record.instanceKey, component);
  }
  return audited;
}

function exactRegionComponent(
  region: PerformanceLocalV4LayoutAudit["regions"][number] | null,
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

export function exactV3ConversionInput(
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
  if (
    configuration.governedContact &&
    configuration.governedContact.websiteId !== composition.website_id
  ) return false;
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

export default PerformanceLocalV4Renderer;
