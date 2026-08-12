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
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link } from "react-router-dom";

import { WebsiteIdentityLogo } from "./WebsiteIdentityPresentation";
import {
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

export type PerformanceLocalRuntimeToggles = {
  campaignBanner: boolean;
  compactEstimateForm: boolean;
  finalCta: boolean;
  stickyActionBar: boolean;
  trustStrip: boolean;
};

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
  enabledComponents: string[];
  effectiveVariants: Record<string, string>;
  errors: string[];
  warnings: string[];
};

export type PerformanceLocalRendererProps = {
  /** Local Theme Lab-only visual direction; accepts opaque #RRGGBB and is never persisted. */
  brandAccent?: string | null;
  campaign?: PerformanceLocalCampaign | null;
  composition: PageComposition;
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

export function PerformanceLocalRenderer({
  brandAccent = null,
  campaign = null,
  composition,
  page,
  toggles = EMPTY_TOGGLES,
  previewedAt = new Date(),
}: PerformanceLocalRendererProps) {
  const components = composition.effective_components;
  const byKey = useMemo(() => indexComponents(components), [components]);
  const media = useMemo(() => bindMediaToExactTargets(components), [components]);
  const validationError = rendererValidationError(page, composition);
  if (validationError) {
    return (
      <main className="performanceLocalUnavailable" role="alert" data-atlas-adapter="performance-local">
        <h1>Performance Local preview unavailable</h1>
        <p>{validationError}</p>
      </main>
    );
  }
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
  const estimateDestination =
    toggles.compactEstimateForm && toggles.finalCta && finalCta ? "#estimate" : null;
  const phoneDestination = safePhoneDestination(phone);
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
  const formState = finalState?.resolution.visible && toggles.compactEstimateForm
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
  const stickyVisible = Boolean(stickyState?.resolution.visible);
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
      data-atlas-adapter-version="1"
      data-composition-id={composition.id}
      data-composition-version={composition.composition_version}
      data-generated-page-id={page.id}
      data-runtime-brand-accent={runtimeAccent ? "validated-preview-override" : "governed-primary"}
      data-sticky-actions-visible={stickyVisible ? "true" : "false"}
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
        />
      )}
      <main id="main-content">
        {hero && (
          <HeroSection
            component={hero}
            media={media.byTarget.get(hero.instance_key)}
            phone={phone}
            estimateDestination={estimateDestination}
          />
        )}
        {trustVisible && trust && trustState?.attributes && trustFeatureState?.attributes && (
          <TrustStrip
            component={trust}
            attributes={trustState.attributes}
            featureAttributes={trustFeatureState.attributes}
          />
        )}
        {mainComponents.map((component, index) => (
          <PerformanceComponent
            key={component.instance_key}
            component={component}
            media={media.byTarget.get(component.instance_key)}
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
      <BackToTopControl />
      {stickyVisible && (
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
  if (composition.effective_components.some((item) => structuredSteps(item).length)) {
    enabledComponents.push("numbered_process_steps");
  }
  const finalCtaVisible = toggles.finalCta && keys.has("final_cta");
  if (finalCtaVisible) enabledComponents.push("visual_cta_band");
  if (finalCtaVisible && toggles.compactEstimateForm) enabledComponents.push("compact_estimate_form");
  const header = composition.effective_components.find((item) => item.component_key === "website_header");
  const hero = composition.effective_components.find((item) => item.component_key === "hero");
  const phone = cleanText(header?.resolved_data.phone) || cleanText(hero?.resolved_data.phone);
  const estimateDestination = finalCtaVisible && toggles.compactEstimateForm ? "#estimate" : "";
  if (toggles.stickyActionBar && (phone || estimateDestination)) {
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
  return {
    enabledComponents,
    effectiveVariants,
    errors: [],
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
  primaryNavigation,
  utilityNavigation,
  phone,
}: {
  component: PageComponentInstance;
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
          <MobileNavigation navigation={navigation} phone={phone} />
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

function MobileNavigation({ navigation, phone }: { navigation: NavigationResolution; phone: string }) {
  const [open, setOpen] = useState(false);
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
    setOpen(false);
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
        onClick={() => setOpen(true)}
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
            {phone ? <PhoneLink value={phone} compact={false} /> : null}
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
    <Link
      to={`/theme-lab/generated-pages/${node.targetGeneratedPageId}`}
      data-canonical-slug={node.canonicalSlug}
    >
      {node.label}
    </Link>
  );
}

function HeroSection({
  component,
  media,
  phone,
  estimateDestination,
}: {
  component: PageComponentInstance;
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
          {cleanText(data.intro) ? <p>{cleanText(data.intro)}</p> : null}
          <div className="performanceLocalActionRow">
            {phone ? <PhoneLink value={phone} compact={false} /> : null}
            {estimateDestination ? <a className="performanceLocalButton performanceLocalButtonSecondary" href={estimateDestination}>Request estimate</a> : null}
          </div>
        </div>
        {resolvedMedia ? <GovernedMedia media={resolvedMedia} component={media!} className="performanceLocalHeroMedia" /> : null}
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

function GovernedMedia({
  component,
  media,
  className = "",
}: {
  component: PageComponentInstance;
  media: RenderableMedia;
  className?: string;
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
  phone,
  email,
  showForm,
  attributes,
  formAttributes,
}: {
  component: PageComponentInstance;
  phone: string;
  email: string;
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
        {showForm && formAttributes ? <CompactEstimateForm attributes={formAttributes} /> : null}
      </div>
    </section>
  );
}

function CompactEstimateForm({ attributes }: { attributes: OptionalComponentDiagnosticAttributes }) {
  function preventSubmission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
  }
  return (
    <form
      className="performanceLocalEstimateForm"
      aria-label="Estimate request preview"
      data-preview-only="true"
      autoComplete="off"
      onSubmit={preventSubmission}
      {...attributes}
    >
      <div className="performanceLocalFormNotice" role="note">
        Preview only. Information entered here is not submitted or saved.
      </div>
      <label>
        Name
        <input name="preview-name" autoComplete="off" />
      </label>
      <label>
        Phone
        <input name="preview-phone" type="tel" autoComplete="off" />
      </label>
      <label>
        ZIP code
        <input name="preview-postal-code" inputMode="numeric" autoComplete="off" />
      </label>
      <label>
        Requested service
        <input name="preview-requested-service" autoComplete="off" />
      </label>
      <label className="performanceLocalFormWide">
        Optional message
        <textarea name="preview-message" rows={3} autoComplete="off" />
      </label>
      <button type="submit">Preview request</button>
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

function BackToTopControl() {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const updateVisibility = () => {
      setVisible(window.scrollY >= Math.max(480, window.innerHeight * 0.75));
    };
    updateVisibility();
    window.addEventListener("scroll", updateVisibility, { passive: true });
    return () => window.removeEventListener("scroll", updateVisibility);
  }, []);
  if (!visible) return null;
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
  const phone = value.replace(/[^\d+]/g, "");
  if (!phone) return null;
  return (
    <a className={`performanceLocalButton performanceLocalPhone${compact ? " performanceLocalButtonCompact" : ""}`} href={`tel:${phone}`}>
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
