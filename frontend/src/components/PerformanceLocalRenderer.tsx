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
} from "../types";
import { resolvePerformanceLocalStickyVisibility } from "./performanceLocalInteractions";

export type PerformanceLocalRuntimeToggles = {
  campaignBanner: boolean;
  compactEstimateForm: boolean;
  finalCta: boolean;
  headerEstimateCta?: boolean;
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
  autoComplete?: string;
  control: "input" | "textarea";
  inputMode?: "email" | "numeric" | "search" | "tel" | "text" | "url";
  key: PerformanceLocalEstimateFieldKey;
  label: string;
  required?: boolean;
  rows?: number;
  type?: "email" | "tel" | "text";
}>;

export type PerformanceLocalEstimateFormConfiguration = Readonly<{
  fields: readonly PerformanceLocalEstimateField[];
  previewNotice: string;
  submitLabel: string;
  visualState?: "idle" | "disabled" | "error" | "success";
}>;

export type PerformanceLocalCampaign = PerformanceLocalOptionalConfiguration & {
  approvalIdentity: string;
  campaignLabel: string;
  ctaDestination: string;
  ctaLabel: string;
  enabled: boolean;
  endDate: string;
  qualifier?: string | null;
  price?: string | null;
  startDate: string;
  termsReference: string;
  websiteId: number;
};

export type PerformanceLocalDiagnostics = {
  disabledComponents: string[];
  enabledComponents: string[];
  effectiveVariants: Record<string, string>;
  errors: string[];
  failClosedComponents: string[];
  warnings: string[];
};

export type PerformanceLocalRendererProps = {
  /** Local Theme Lab-only visual direction; accepts opaque #RRGGBB and is never persisted. */
  brandAccent?: string | null;
  campaign?: PerformanceLocalCampaign | null;
  composition: PageComposition;
  estimateForm?: PerformanceLocalEstimateFormConfiguration | null;
  page: GeneratedPage;
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

const DEFAULT_ESTIMATE_FORM: PerformanceLocalEstimateFormConfiguration = Object.freeze({
  fields: Object.freeze([
    Object.freeze({ key: "name", label: "Name", control: "input", type: "text", autoComplete: "off" }),
    Object.freeze({ key: "phone", label: "Phone", control: "input", type: "tel", inputMode: "tel", autoComplete: "off" }),
    Object.freeze({ key: "postal-code", label: "ZIP code", control: "input", type: "text", inputMode: "numeric", autoComplete: "off" }),
    Object.freeze({ key: "requested-service", label: "Requested service", control: "input", type: "text", autoComplete: "off" }),
    Object.freeze({ key: "message", label: "Optional message", control: "textarea", rows: 3, autoComplete: "off" }),
  ]),
  previewNotice: "Preview only. Information entered here is not submitted or saved.",
  submitLabel: "Preview request",
  visualState: "idle",
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
  estimateForm = DEFAULT_ESTIMATE_FORM,
  page,
  toggles = EMPTY_TOGGLES,
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
  const phone = cleanText(headerData.phone) || cleanText(hero?.resolved_data.phone);
  const email = cleanText(headerData.email) || cleanText(hero?.resolved_data.email);
  const resolvedEstimateForm = validateEstimateFormConfiguration(estimateForm);
  const estimateDestination =
    toggles.compactEstimateForm && toggles.finalCta && finalCta && resolvedEstimateForm
      ? "#estimate"
      : null;
  const phoneDestination = safePhoneDestination(phone);
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
      )
    : null;
  const finalAction = estimateDestination
    ? { ctaLabel: "Request estimate", ctaDestination: estimateDestination }
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
      )
    : null;
  const stickyAction = estimateDestination
    ? { actionLabel: "Request estimate", phoneOrEstimateDestination: estimateDestination }
    : phoneDestination
      ? { actionLabel: "Call", phoneOrEstimateDestination: phoneDestination }
      : null;
  const stickyState = toggles.stickyActionBar && stickyAction
    ? governedOptionalState(
        "sticky_mobile_action_bar",
        composition.website_id,
        "Contact actions",
        { sourceIdentity: composition.source_hash, ...stickyAction },
        "mobile",
        page.id,
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
  );
  const diagnostics = performanceLocalDiagnostics(composition, toggles, {
    campaignError: campaignState.error,
    campaignVisible: Boolean(campaignState.campaign),
    media,
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
      data-atlas-adapter-version={PERFORMANCE_LOCAL_THEME_VERSION}
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
          phone={phone}
          estimateDestination={toggles.headerEstimateCta === false ? null : estimateDestination}
          mobileMenuOpen={mobileMenuOpen}
          onMobileMenuOpenChange={setMobileMenuOpen}
        />
      )}
      <main id="main-content">
        {hero && (
          <HeroSection
            component={hero}
            media={media.byTarget.get(hero.instance_key)}
            phone={phone}
            estimateDestination={estimateDestination}
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
            phone={phone}
            email={email}
          />
        ))}
        {finalCtaVisible && finalCta && finalState?.attributes && (
          <FinalConversionSection
            component={finalCta}
            phone={phone}
            email={email}
            showForm={formVisible}
            attributes={finalState.attributes}
            formAttributes={formState?.attributes ?? null}
            formConfiguration={resolvedEstimateForm}
            onFormFocusRiskChange={setFormFocusRisk}
          />
        )}
      </main>
      {footer && (
        <PerformanceFooter
          component={footer}
          navigation={footerNavigation}
          phone={phone}
          email={email}
        />
      )}
      <BackToTopControl suppressed={formFocusRisk || mobileMenuOpen} />
      {stickyVisibility.visible && (
        <StickyMobileActions
          phone={phone}
          estimateDestination={estimateDestination}
          attributes={stickyState!.attributes!}
        />
      )}
      <output className="performanceLocalDiagnostics" hidden data-diagnostic-count={diagnostics.errors.length + diagnostics.warnings.length}>
        {JSON.stringify(diagnostics)}
      </output>
    </div>
  );
}

export function performanceLocalDiagnostics(
  composition: PageComposition,
  toggles: PerformanceLocalRuntimeToggles,
  context: {
    campaignError?: string | null;
    campaignVisible?: boolean;
    media?: MediaBindingResult;
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
  const header = composition.effective_components.find((item) => item.component_key === "website_header");
  const hero = composition.effective_components.find((item) => item.component_key === "hero");
  const phone = cleanText(header?.resolved_data.phone) || cleanText(hero?.resolved_data.phone);
  const phoneDestination = safePhoneDestination(phone);
  const estimateDestination = finalCtaVisible && toggles.compactEstimateForm ? "#estimate" : "";
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

function CampaignBanner({
  campaign,
  attributes,
}: {
  campaign: PerformanceLocalCampaign;
  attributes: OptionalComponentDiagnosticAttributes;
}) {
  return (
    <aside className="performanceLocalCampaign" aria-label={campaign.campaignLabel} {...attributes}>
      <div className="performanceLocalContainer performanceLocalCampaignInner">
        <p>
          <strong>{campaign.campaignLabel}</strong>
          {campaign.price ? <span>{campaign.price}</span> : null}
          {campaign.qualifier ? <span>{campaign.qualifier}</span> : null}
        </p>
        <a href={campaign.ctaDestination}>{campaign.ctaLabel}</a>
      </div>
    </aside>
  );
}

function PerformanceHeader({
  component,
  estimateDestination,
  mobileMenuOpen,
  onMobileMenuOpenChange,
  primaryNavigation,
  utilityNavigation,
  phone,
}: {
  component: PageComponentInstance;
  estimateDestination: string | null;
  mobileMenuOpen: boolean;
  onMobileMenuOpenChange: (open: boolean) => void;
  primaryNavigation?: PageComponentInstance;
  utilityNavigation?: PageComponentInstance;
  phone: string;
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
        <DesktopNavigation navigation={navigation} />
        <div className="performanceLocalHeaderActions">
          {phone ? <PhoneLink value={phone} compact /> : null}
          {estimateDestination ? (
            <a className="performanceLocalButton performanceLocalHeaderEstimate" href={estimateDestination}>
              Request estimate
            </a>
          ) : null}
          <MobileNavigation
            navigation={navigation}
            phone={phone}
            estimateDestination={estimateDestination}
            open={mobileMenuOpen}
            onOpenChange={onMobileMenuOpenChange}
          />
        </div>
      </div>
    </header>
  );
}

function DesktopNavigation({ navigation }: { navigation: NavigationResolution }) {
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
                <ThemeLabDestination node={node} />
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
                        <NavigationBranch key={child.navigationItemId} node={child} />
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
  estimateDestination,
  navigation,
  onOpenChange,
  open,
  phone,
}: {
  estimateDestination: string | null;
  navigation: NavigationResolution;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  phone: string;
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
                        <ThemeLabDestination node={node} />
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
                            <NavigationBranch key={child.navigationItemId} node={child} onNavigate={close} />
                          ))}
                        </ul>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
            <div className="performanceLocalDrawerActions">
              {phone ? <PhoneLink value={phone} compact={false} /> : null}
              {estimateDestination ? (
                <a className="performanceLocalButton performanceLocalButtonSecondary" href={estimateDestination} onClick={close}>
                  Request estimate
                </a>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function NavigationBranch({ node, onNavigate }: { node: ResolvedNavigationItem; onNavigate?: () => void }) {
  return (
    <li data-navigation-item-id={node.navigationItemId} onClick={onNavigate}>
      <ThemeLabDestination node={node} />
      {node.children.length ? (
        <ul>
          {node.children.map((child) => (
            <NavigationBranch key={child.navigationItemId} node={child} onNavigate={onNavigate} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function ThemeLabDestination({ node }: { node: ResolvedNavigationItem }) {
  if (!node.targetGeneratedPageId) {
    return <span aria-disabled="true">{node.label}</span>;
  }
  return (
    <NavLink
      to={`/theme-lab/generated-pages/${node.targetGeneratedPageId}`}
      data-canonical-slug={node.canonicalSlug}
      className={({ isActive }) => isActive ? "performanceLocalActiveDestination" : undefined}
    >
      {node.label}
    </NavLink>
  );
}

function HeroSection({
  component,
  conversionRef,
  media,
  phone,
  estimateDestination,
}: {
  component: PageComponentInstance;
  conversionRef: RefObject<HTMLDivElement>;
  media?: PageComponentInstance;
  phone: string;
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
            {phone ? <PhoneLink value={phone} compact={false} /> : null}
            {estimateDestination ? <a className="performanceLocalButton performanceLocalButtonSecondary" href={estimateDestination}>Request estimate</a> : null}
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
  attributes: OptionalComponentDiagnosticAttributes;
  featureAttributes: OptionalComponentDiagnosticAttributes;
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
  component,
  media,
  index,
  phone,
  email,
}: {
  component: PageComponentInstance;
  media?: PageComponentInstance;
  index: number;
  phone: string;
  email: string;
}) {
  switch (component.component_key) {
    case "content_section":
    case "service_summary":
      return <AuthoritySection component={component} media={media} reverse={index % 2 === 1} />;
    case "destination_cards":
    case "related_page_links":
      return <RelatedCardGrid component={component} />;
    case "faq":
      return <FaqAccordion component={component} />;
    case "contact_pathways":
      return <ContactPathways component={component} phone={phone} email={email} />;
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

function RelatedCardGrid({ component }: { component: PageComponentInstance }) {
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
                    <Link to={`/theme-lab/generated-pages/${id}`} data-canonical-slug={cleanText(link.slug)}>
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
  phone,
  email,
}: {
  component: PageComponentInstance;
  phone: string;
  email: string;
}) {
  const displayName = cleanText(component.resolved_data.display_name);
  if (!phone && !email) return null;
  return (
    <section className="performanceLocalSection performanceLocalContact" aria-label="Contact options">
      <div className="performanceLocalContainer performanceLocalSectionCopy">
        <h2>{displayName ? `Contact ${displayName}` : "Contact the business"}</h2>
        <div className="performanceLocalActionRow">
          {phone ? <PhoneLink value={phone} compact={false} /> : null}
          {email ? <EmailLink value={email} /> : null}
        </div>
      </div>
    </section>
  );
}

function FinalConversionSection({
  component,
  formConfiguration,
  phone,
  email,
  onFormFocusRiskChange,
  showForm,
  attributes,
  formAttributes,
}: {
  component: PageComponentInstance;
  formConfiguration: PerformanceLocalEstimateFormConfiguration | null;
  phone: string;
  email: string;
  onFormFocusRiskChange: (focused: boolean) => void;
  showForm: boolean;
  attributes: OptionalComponentDiagnosticAttributes;
  formAttributes: OptionalComponentDiagnosticAttributes | null;
}) {
  const data = component.resolved_data;
  const heading = cleanText(data.heading);
  const body = cleanText(data.body);
  if (!heading && !body && !showForm && !phone && !email) return null;
  return (
    <section id="estimate" className="performanceLocalFinalCta" {...attributes}>
      <div className={`performanceLocalContainer ${showForm ? "performanceLocalFinalGrid" : "performanceLocalFinalSingle"}`}>
        <div className="performanceLocalSectionCopy">
          {heading ? <h2>{heading}</h2> : null}
          {body ? <p>{body}</p> : null}
          <div className="performanceLocalActionRow">
            {phone ? <PhoneLink value={phone} compact={false} /> : null}
            {email ? <EmailLink value={email} /> : null}
          </div>
        </div>
        {showForm && formAttributes && formConfiguration ? (
          <CompactEstimateForm
            attributes={formAttributes}
            configuration={formConfiguration}
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
  onFocusRiskChange,
}: {
  attributes: OptionalComponentDiagnosticAttributes;
  configuration: PerformanceLocalEstimateFormConfiguration;
  onFocusRiskChange: (focused: boolean) => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  function preventSubmission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
  }
  const disabled = configuration.visualState === "disabled";
  const visualState = configuration.visualState ?? "idle";
  const stateMessage = visualState === "success"
    ? "Preview success appearance — no request was sent."
    : visualState === "error"
      ? "Preview error appearance — review the highlighted fields."
      : visualState === "disabled"
        ? "Preview controls are disabled."
        : "Preview form is ready for local interaction only.";
  return (
    <form
      ref={formRef}
      className="performanceLocalEstimateForm"
      aria-label="Estimate request preview"
      data-preview-only="true"
      data-visual-state={visualState}
      autoComplete="off"
      onSubmit={preventSubmission}
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
        <label key={field.key} className={field.control === "textarea" ? "performanceLocalFormWide" : undefined}>
          {field.label}
          {field.control === "textarea" ? (
            <textarea
              name={`preview-${field.key}`}
              rows={field.rows ?? 3}
              autoComplete={field.autoComplete ?? "off"}
              required={field.required}
              disabled={disabled}
            />
          ) : (
            <input
              name={`preview-${field.key}`}
              type={field.type ?? "text"}
              inputMode={field.inputMode}
              autoComplete={field.autoComplete ?? "off"}
              required={field.required}
              disabled={disabled}
            />
          )}
        </label>
      ))}
      <button type="submit" disabled={disabled}>{configuration.submitLabel}</button>
    </form>
  );
}

function PerformanceFooter({
  component,
  navigation,
  phone,
  email,
}: {
  component: PageComponentInstance;
  navigation?: PageComponentInstance;
  phone: string;
  email: string;
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
              {tree.nodes.map((node) => <NavigationBranch key={node.navigationItemId} node={node} />)}
            </ul>
          </nav>
        ) : null}
        <div className="performanceLocalFooterContact">
          {phone ? <PhoneLink value={phone} compact={false} /> : null}
          {email ? <EmailLink value={email} /> : null}
          {cleanText(data.license_number) ? <span>License {cleanText(data.license_number)}</span> : null}
        </div>
      </div>
    </footer>
  );
}

function StickyMobileActions({
  phone,
  estimateDestination,
  attributes,
}: {
  phone: string;
  estimateDestination: string | null;
  attributes: OptionalComponentDiagnosticAttributes;
}) {
  if (!phone && !estimateDestination) return null;
  return (
    <aside className="performanceLocalStickyActions" aria-label="Contact actions" {...attributes}>
      {phone ? <PhoneLink value={phone} compact /> : null}
      {estimateDestination ? <a href={estimateDestination}>Request estimate</a> : null}
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

function PhoneLink({ value, compact }: { value: string; compact: boolean }) {
  const destination = safePhoneDestination(value);
  if (!destination) return null;
  return (
    <a className={`performanceLocalButton performanceLocalPhone${compact ? " performanceLocalButtonCompact" : ""}`} href={destination}>
      <Phone size={18} aria-hidden="true" />
      <span>{compact ? "Call" : `Call ${value}`}</span>
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
): {
  campaign: PerformanceLocalCampaign | null;
  error: string | null;
  attributes: OptionalComponentDiagnosticAttributes | null;
} {
  const resolution = resolveOptionalComponent(
    "campaign_banner",
    campaign,
    websiteId,
    "desktop",
    previewedAt,
    pageId,
  );
  if (!campaign?.enabled || !resolution.visible) {
    return {
      campaign: null,
      error: resolution.errors.length ? resolution.errors.join(" ") : null,
      attributes: null,
    };
  }
  return {
    campaign,
    error: null,
    attributes: performanceLocalOptionalComponentAttributes("campaign_banner", resolution),
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
): PerformanceLocalEstimateFormConfiguration | null {
  if (!value || !cleanText(value.previewNotice) || !cleanText(value.submitLabel)) return null;
  if (value.visualState && !["idle", "disabled", "error", "success"].includes(value.visualState)) {
    return null;
  }
  if (!Array.isArray(value.fields) || value.fields.length !== 5) return null;
  const expected = new Set<PerformanceLocalEstimateFieldKey>([
    "name",
    "phone",
    "postal-code",
    "requested-service",
    "message",
  ]);
  const seen = new Set<PerformanceLocalEstimateFieldKey>();
  for (const field of value.fields) {
    if (!field || !expected.has(field.key) || seen.has(field.key) || !cleanText(field.label)) return null;
    if (field.control !== "input" && field.control !== "textarea") return null;
    if (field.autoComplete && field.autoComplete !== "off") return null;
    if (field.control === "textarea" && field.type) return null;
    seen.add(field.key);
  }
  return seen.size === expected.size ? value : null;
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
): {
  configuration: PerformanceLocalOptionalConfiguration;
  resolution: OptionalComponentResolution;
  attributes: OptionalComponentDiagnosticAttributes | null;
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
      ? performanceLocalOptionalComponentAttributes(key, resolution)
      : null,
  };
}

export default PerformanceLocalRenderer;
