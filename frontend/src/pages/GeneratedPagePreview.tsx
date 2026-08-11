import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowLeft, Image, Phone, ShieldCheck } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { apiRequest } from "../api";
import {
  WebsiteIdentityLogo,
  installIdentityHeadTags,
  removeIdentityHeadTags,
} from "../components/WebsiteIdentityPresentation";
import {
  themePresentation,
  themeValidationError,
} from "../components/themeAdapter";
import type {
  ApprovalAudit,
  GeneratedPage,
  GeneratedPageRevision,
  PageComponentInstance,
  PageComposition,
  PageMediaDisplayPreset,
  PageQAResult,
  ResolvedPageMediaData,
} from "../types";

type PreviewData = {
  page: GeneratedPage;
  composition: PageComposition;
  requestKey: string;
};

export type ResolvedNavigationItem = {
  navigationItemId: number;
  targetPlannedPageId: number;
  targetGeneratedPageId: number | null;
  parentNavigationItemId: number | null;
  position: number;
  label: string;
  canonicalSlug: string;
  children: ResolvedNavigationItem[];
};

export type NavigationTreeResult = {
  nodes: ResolvedNavigationItem[];
  error: string | null;
};

function GeneratedPagePreview() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const showQa = searchParams.get("qa") === "1";
  const requestKey = previewRequestKey(id, showQa);
  const [data, setData] = useState<PreviewData | null>(null);
  const [qaResult, setQaResult] = useState<PageQAResult | null>(null);
  const [approvalCount, setApprovalCount] = useState(0);
  const [revisionCount, setRevisionCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [requestStateKey, setRequestStateKey] = useState("");
  const loadGeneration = useRef(0);
  const viewportWidth = useViewportWidth();

  useLayoutEffect(() => {
    removeIdentityHeadTags(document);
    return () => removeIdentityHeadTags(document);
  }, [requestKey]);

  useEffect(() => {
    const generation = ++loadGeneration.current;
    let cancelled = false;
    const isCurrentLoad = () =>
      !cancelled && generation === loadGeneration.current;
    setRequestStateKey(requestKey);
    setLoading(true);
    setError(null);
    setData(null);
    setQaResult(null);
    setApprovalCount(0);
    setRevisionCount(0);
    document.title = "Project Atlas";
    removeIdentityHeadTags(document);

    async function loadPreview() {
      const pageId = Number(id);
      if (!Number.isInteger(pageId)) {
        if (isCurrentLoad()) {
          setError("Invalid generated page ID.");
          setLoading(false);
        }
        return;
      }
      try {
        const [page, composition] = await Promise.all([
          apiRequest<GeneratedPage>(`/api/generated-pages/${pageId}`),
          apiRequest<PageComposition>(`/api/site-plans/generated-pages/${pageId}/composition`)
        ]);
        const compositionError = compositionValidationError(composition);
        if (compositionError) throw new Error(compositionError);
        let nextQaResult: PageQAResult | null = null;
        let nextApprovalCount = 0;
        let nextRevisionCount = 0;
        if (showQa) {
          const [qa, history, revisions] = await Promise.all([
            apiRequest<PageQAResult>(`/api/generated-pages/${pageId}/qa`),
            apiRequest<ApprovalAudit[]>(`/api/generated-pages/${pageId}/approval-history`),
            apiRequest<GeneratedPageRevision[]>(`/api/generated-pages/${pageId}/revisions`)
          ]);
          nextQaResult = qa;
          nextApprovalCount = history.length;
          nextRevisionCount = revisions.length;
        }
        if (!isCurrentLoad()) return;
        setData({ page, composition, requestKey });
        setQaResult(nextQaResult);
        setApprovalCount(nextApprovalCount);
        setRevisionCount(nextRevisionCount);
        document.title = `${page.page_title} | Atlas Preview`;
      } catch (value) {
        if (!isCurrentLoad()) return;
        setData(null);
        removeIdentityHeadTags(document);
        setError(value instanceof Error ? value.message : "Unable to load page preview.");
      } finally {
        if (isCurrentLoad()) setLoading(false);
      }
    }
    void loadPreview();
    return () => {
      cancelled = true;
      if (generation === loadGeneration.current) loadGeneration.current += 1;
      removeIdentityHeadTags(document);
      document.title = "Project Atlas";
    };
  }, [requestKey]);

  useEffect(() => {
    if (!data || data.requestKey !== requestKey) return;
    const header = data.composition.effective_components.find(item => item.component_key === "website_header");
    const identityAssets = record(header?.resolved_data.identity_assets);
    return installIdentityHeadTags(document, identityAssets);
  }, [data, requestKey]);

  const currentData = hasCurrentPreviewData(requestKey, requestStateKey, data)
    ? data
    : null;
  if (requestStateKey !== requestKey || loading) {
    return <PreviewState message="Loading semantic page composition..." />;
  }
  if (error || !currentData) return <PreviewState message={error ?? "Page preview is unavailable."} error />;
  if (!currentData.page.draft_content) {
    return <PreviewState message="Generate a structured draft before composing its preview." error />;
  }

  const components = currentData.composition.effective_components;
  const presentation = themePresentation(
    currentData.composition.resolved_theme,
    currentData.composition.website_id,
    viewportWidth,
  );
  return (
    <div
      className="servicePreview atlasBasePresentation"
      style={presentation.style}
      {...presentation.attributes}
    >
      <div className="previewReviewBar">
        <div className="previewReviewInner">
          <Link to="/site-plans" className="previewBackLink">
            <ArrowLeft size={16} aria-hidden="true" /> Back to Site Plans
          </Link>
          <span>Semantic composition v{currentData.composition.composition_version}</span>
          <strong>Not published</strong>
        </div>
      </div>
      {showQa && qaResult && (
        <div
          className={`previewQaBanner ${
            effectiveQaDisplayStatus(qaResult)
          }`}
        >
          <div className="previewContainer">
            <AlertTriangle size={17} aria-hidden="true" />
            <strong>
              Internal QA:{" "}
              {effectiveQaDisplayStatus(qaResult) !== "not_run"
                ? qaResult.readiness_status.replace(/_/g, " ")
                : "not current for this page identity"}
            </strong>
            <span>{qaResult.failed_count} blockers | {qaResult.warning_count} warnings</span>
            {effectiveQaDisplayStatus(qaResult) === "not_run" && (
              <span>
                {qaResult.currentness_reasons.join(" ") ||
                  `Fresh candidate: ${qaResult.readiness_status.replace(/_/g, " ")}; not saved.`}
              </span>
            )}
            <span>{approvalCount} approval record(s) | {revisionCount} revision(s)</span>
          </div>
        </div>
      )}
      {components.filter((item) => item.region === "header").map(renderComponent)}
      <main id="main-content">
        {components.filter((item) => item.region === "main").map(renderComponent)}
      </main>
      <footer className="previewFooter">
        {components.filter((item) => item.region === "footer").map(renderComponent)}
      </footer>
    </div>
  );
}

export function renderComponent(component: PageComponentInstance) {
  const data = component.resolved_data;
  switch (component.component_key) {
    case "website_header":
      {
      const assets = record(data.identity_assets);
      return (
        <header className="previewSiteHeader" key={component.instance_key}>
          <div className="previewContainer previewHeaderInner">
            <div className="previewBrand">
              <WebsiteIdentityLogo
                identityAssets={assets}
                slot="header_logo"
                displayName={text(data.display_name)}
              />
              <div><strong>{text(data.display_name)}</strong><span>{text(data.tagline) || text(data.business_type)}</span></div>
            </div>
            {data.phone ? <ContactLink value={text(data.phone)} kind="phone" /> : <ContactLink value={text(data.email)} kind="email" />}
          </div>
        </header>
      );
      }
    case "primary_navigation":
    case "utility_navigation":
    case "footer_navigation":
      return <Navigation component={component} key={component.instance_key} />;
    case "hero":
      return (
        <section className="previewHero" key={component.instance_key}>
          <div className="previewContainer previewHeroContent">
            <p className="previewKicker">{text(data.page_type).replace(/_/g, " ")} page</p>
            <h1>{text(data.title)}</h1><p>{text(data.intro)}</p>
            <div className="previewHeroActions">
              {Boolean(data.phone) && <ContactLink value={text(data.phone)} kind="phone" button />}
              {Boolean(data.email) && <ContactLink value={text(data.email)} kind="email" button />}
            </div>
          </div>
        </section>
      );
    case "trust_license":
      return (
        <section className="previewBand previewProfessionalBand" key={component.instance_key} aria-label="Business trust information">
          <div className="previewContainer previewProfessionalInner"><ShieldCheck size={30} aria-hidden="true" /><div>
            <h2>Approved business credentials</h2>
            <p>{data.license_number ? `License ${text(data.license_number)}` : text(data.business_type)}{data.certified_operator ? ` | Certified Operator: ${text(data.certified_operator)}` : ""}</p>
          </div></div>
        </section>
      );
    case "content_section":
    case "service_summary":
      return (
        <section className={component.variant === "muted" ? "previewBand previewBandMuted" : "previewBand"} key={component.instance_key}>
          <div className="previewContainer previewTextSection"><h2>{text(data.heading)}</h2><p>{text(data.body)}</p></div>
        </section>
      );
    case "media_placement":
      return <MediaPlacement component={component} key={component.instance_key} />;
    case "destination_cards":
    case "related_page_links":
      return <RelatedLinks component={component} key={component.instance_key} />;
    case "faq": {
      const items = array(data.items);
      return (
        <section className="previewBand previewBandMuted" key={component.instance_key}>
          <div className="previewContainer previewFaqSection"><h2>Frequently Asked Questions</h2>
            <div className="previewFaqList">{items.map((item, index) => {
              const value = record(item); return <details key={`${text(value.question)}-${index}`}><summary>{text(value.question)}</summary><p>{text(value.answer)}</p></details>;
            })}</div>
          </div>
        </section>
      );
    }
    case "contact_pathways":
      return (
        <section className="previewBand" key={component.instance_key}>
          <div className="previewContainer previewTextSection"><h2>Contact {text(data.display_name)}</h2>
            <div className="previewHeroActions">{Boolean(data.phone) && <ContactLink value={text(data.phone)} kind="phone" button />}{Boolean(data.email) && <ContactLink value={text(data.email)} kind="email" button />}</div>
          </div>
        </section>
      );
    case "final_cta":
      return (
        <section className="previewFinalCta" id="estimate" key={component.instance_key}>
          <div className="previewContainer previewFinalCtaInner"><div><p className="previewSectionLabel">Next Step</p><h2>{text(data.heading)}</h2><p>{text(data.body)}</p></div>
            <div className="previewFinalActions">{Boolean(data.phone) && <ContactLink value={text(data.phone)} kind="phone" button />}{Boolean(data.email) && <ContactLink value={text(data.email)} kind="email" button />}</div>
          </div>
        </section>
      );
    case "website_footer":
      {
      const assets = record(data.identity_assets);
      return (
        <div className="previewContainer previewFooterInner" key={component.instance_key}>
          <WebsiteIdentityLogo
            identityAssets={assets}
            slot="footer_logo"
            displayName={text(data.company_name)}
          />
          <div><strong>{text(data.company_name)}</strong><span>{data.license_number ? `License ${text(data.license_number)}` : text(data.business_type)}</span></div>
        </div>
      );
      }
    default:
      return <PreviewState key={component.instance_key} message={`Unsupported semantic component: ${component.component_key}`} error />;
  }
}

const PAGE_MEDIA_DISPLAY_PRESETS = new Set<PageMediaDisplayPreset>([
  "hero_desktop",
  "hero_mobile",
  "card_thumbnail",
  "square",
  "original",
]);

export type PageMediaDisplayPresetResolution = {
  preset: PageMediaDisplayPreset | null;
  source: "effective" | "stored_legacy" | "legacy_fallback" | "unassigned" | "blocked_current";
  error: string | null;
};

/**
 * Resolve presentation only from the governed preset contract. Free-text media
 * metadata and semantic role are deliberately excluded from this decision.
 */
export function resolvePageMediaDisplayPreset(
  resolvedData: Record<string, unknown>,
  inputBindings: Record<string, unknown> = {},
): PageMediaDisplayPresetResolution {
  const contractVersion = positiveInteger(
    resolvedData.placement_contract_version,
  ) ?? positiveInteger(inputBindings.placement_contract_version);
  const effectiveRaw = normalizedString(resolvedData.effective_display_preset);
  const storedRaw = normalizedString(resolvedData.stored_display_preset);
  const legacyStoredRaw = normalizedString(resolvedData.display_preset);
  const effective = displayPreset(effectiveRaw);
  const stored = displayPreset(storedRaw);
  const legacyStored = displayPreset(legacyStoredRaw);
  const isCurrentGovernedContract = contractVersion !== null && contractVersion >= 2;
  const hasAssignedAsset = Boolean(normalizedString(resolvedData.asset_url));

  if (isCurrentGovernedContract) {
    if (!effective) {
      if (!hasAssignedAsset) {
        return { preset: null, source: "unassigned", error: null };
      }
      return {
        preset: null,
        source: "blocked_current",
        error: "The current governed media display preset is missing or unsupported.",
      };
    }
    if (hasAssignedAsset && (!stored || stored !== effective)) {
      return {
        preset: null,
        source: "blocked_current",
        error: "The stored and effective governed media display presets are not current.",
      };
    }
    return { preset: effective, source: "effective", error: null };
  }

  if (effective) return { preset: effective, source: "effective", error: null };
  const historicalStored = stored ?? legacyStored;
  if (historicalStored) {
    return {
      preset: historicalStored,
      source: "stored_legacy",
      error: null,
    };
  }
  return { preset: "original", source: "legacy_fallback", error: null };
}

export function pageMediaDisplayPresetClassName(
  preset: PageMediaDisplayPreset,
): string {
  return `previewGalleryItem preset-${preset.replace(/_/g, "-")}`;
}

function MediaPlacement({ component }: { component: PageComponentInstance }) {
  const data: ResolvedPageMediaData = component.resolved_data;
  const resolution = resolvePageMediaDisplayPreset(data, component.input_bindings);
  const semanticRole = normalizedString(data.image_role);
  const hasAssignedAsset = Boolean(normalizedString(data.asset_url));
  const diagnostics = {
    "data-effective-display-preset": resolution.preset ?? (hasAssignedAsset ? "blocked" : "unassigned"),
    "data-display-preset-source": resolution.source,
    "data-semantic-media-role": semanticRole || undefined,
  };

  if (resolution.error || (hasAssignedAsset && !resolution.preset)) {
    return (
      <section
        className="previewBand"
        aria-label={text(data.purpose)}
        data-display-preset-status="blocked"
        {...diagnostics}
      >
        <div className="previewContainer">
          <div className="previewImagePlaceholder previewMediaPresetError" role="alert">
            <AlertTriangle size={28} aria-hidden="true" />
            <strong>Governed media unavailable.</strong>
            <span>{resolution.error}</span>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section
      className="previewBand"
      aria-label={text(data.purpose)}
      data-display-preset-status={hasAssignedAsset ? "resolved" : "unassigned"}
      {...diagnostics}
    >
      <div className="previewContainer">
        {hasAssignedAsset && resolution.preset ? (
          <figure
            className={pageMediaDisplayPresetClassName(resolution.preset)}
            {...diagnostics}
          >
            <div className="previewMediaFrame">
              <img
                src={text(data.asset_url)}
                alt={text(data.alt_text)}
                title={text(data.image_title)}
                style={{ objectPosition: `${number(data.focal_x, 0.5) * 100}% ${number(data.focal_y, 0.5) * 100}%` }}
              />
            </div>
            {Boolean(data.caption) && <figcaption>{text(data.caption)}</figcaption>}
          </figure>
        ) : (
          <div className="previewImagePlaceholder" {...diagnostics}>
            <Image size={28} aria-hidden="true" /><strong>{text(data.purpose)}</strong>
            <span>Placement reserved for future approved media.</span>
          </div>
        )}
      </div>
    </section>
  );
}

export function effectiveQaDisplayStatus(result: PageQAResult): string {
  return result.persisted === true &&
    result.currentness_status === "current_exact_identity_match"
    ? result.readiness_status
    : "not_run";
}

function Navigation({ component }: { component: PageComponentInstance }) {
  const items = array(component.resolved_data.items);
  const tree = buildNavigationTree(items);
  const label = text(component.resolved_data.label) || "Website navigation";
  return (
    <nav className={`semanticNavigation semanticNavigation-${component.component_key}`} aria-label={label}>
      <div className="previewContainer">
        {tree.error ? (
          <p className="semanticNavigationUnavailable" role="status">
            Navigation unavailable: {tree.error}
          </p>
        ) : (
          <NavigationList nodes={tree.nodes} />
        )}
      </div>
    </nav>
  );
}

function NavigationList({ nodes, nested = false }: { nodes: ResolvedNavigationItem[]; nested?: boolean }) {
  return (
    <ul className={nested ? "semanticNavigationChildren" : "semanticNavigationList"}>
      {nodes.map((node) => (
        <li key={node.navigationItemId} data-navigation-item-id={node.navigationItemId}>
          <LocalPreviewDestination
            label={node.label}
            canonicalSlug={node.canonicalSlug}
            targetGeneratedPageId={node.targetGeneratedPageId}
          />
          {node.children.length > 0 && <NavigationList nodes={node.children} nested />}
        </li>
      ))}
    </ul>
  );
}

function RelatedLinks({ component }: { component: PageComponentInstance }) {
  const links = array(component.resolved_data.links);
  return (
    <section className="previewBand previewBandMuted" aria-label="Related destinations">
      <div className="previewContainer"><h2>Related pages</h2><div className="semanticDestinationGrid">
        {links.map((item, index) => {
          const value = record(item);
          return (
            <article key={`${text(value.slug)}-${index}`}>
              <h3>
                <LocalPreviewDestination
                  label={text(value.label)}
                  canonicalSlug={text(value.slug)}
                  targetGeneratedPageId={nullablePositiveInteger(value.target_generated_page_id)}
                />
              </h3>
              <p>{text(value.purpose)}</p>
            </article>
          );
        })}
      </div></div>
    </section>
  );
}

function LocalPreviewDestination({
  label,
  canonicalSlug,
  targetGeneratedPageId
}: {
  label: string;
  canonicalSlug: string;
  targetGeneratedPageId: number | null;
}) {
  const destination = localPreviewDestination(targetGeneratedPageId);
  if (!destination) {
    return (
      <span
        className="semanticDestinationUnavailable"
        data-canonical-slug={canonicalSlug}
        aria-disabled="true"
      >
        {label} <small>(local preview unavailable)</small>
      </span>
    );
  }
  return (
    <Link to={destination} data-canonical-slug={canonicalSlug} title={`Canonical path: /${canonicalSlug.replace(/^\/+|\/+$/g, "")}/`}>
      {label}
    </Link>
  );
}

function ContactLink({ value, kind, button = false }: { value: string; kind: "phone" | "email"; button?: boolean }) {
  const href = kind === "phone" ? `tel:${value.replace(/[^\d+]/g, "")}` : `mailto:${value}`;
  return <a className={button ? "previewButton previewButtonPrimary" : "previewPhoneLink"} href={href}>{kind === "phone" && <Phone size={18} aria-hidden="true" />}<span>{kind === "phone" ? `Call ${value}` : value}</span></a>;
}

function PreviewState({ message, error = false }: { message: string; error?: boolean }) {
  return <main className="previewState"><div><p className="previewSectionLabel">{error ? "Preview Error" : "Atlas Preview"}</p><h1>{message}</h1><Link to="/generated-pages" className="previewButton previewButtonPrimary"><ArrowLeft size={18} aria-hidden="true" /> Back to Generated Pages</Link></div></main>;
}

export function localPreviewDestination(targetGeneratedPageId: unknown): string | null {
  const id = nullablePositiveInteger(targetGeneratedPageId);
  return id === null ? null : `/generated-pages/${id}/preview`;
}

export function buildNavigationTree(values: unknown[]): NavigationTreeResult {
  const parsed: ResolvedNavigationItem[] = [];
  const ids = new Set<number>();
  const targetIds = new Set<number>();
  for (const raw of values) {
    const value = record(raw);
    const status = text(value.status);
    if (status && status !== "active") continue;
    const navigationItemId = nullablePositiveInteger(value.navigation_item_id);
    const targetPlannedPageId = nullablePositiveInteger(value.target_planned_page_id);
    const parentNavigationItemId = value.parent_navigation_item_id == null
      ? null
      : nullablePositiveInteger(value.parent_navigation_item_id);
    const position = nonNegativeInteger(value.position);
    const label = text(value.label).trim();
    const canonicalSlug = text(value.slug).trim();
    if (navigationItemId === null || targetPlannedPageId === null || position === null || !label || !canonicalSlug) {
      return { nodes: [], error: "an active item has incomplete authoritative identity or ordering data." };
    }
    if (value.parent_navigation_item_id != null && parentNavigationItemId === null) {
      return { nodes: [], error: `item ${navigationItemId} has an invalid parent identity.` };
    }
    if (ids.has(navigationItemId)) {
      return { nodes: [], error: `duplicate navigation item identity ${navigationItemId}.` };
    }
    if (targetIds.has(targetPlannedPageId)) {
      return { nodes: [], error: `duplicate navigation target Planned Page ${targetPlannedPageId}.` };
    }
    ids.add(navigationItemId);
    targetIds.add(targetPlannedPageId);
    parsed.push({
      navigationItemId,
      targetPlannedPageId,
      targetGeneratedPageId: nullablePositiveInteger(value.target_generated_page_id),
      parentNavigationItemId,
      position,
      label,
      canonicalSlug,
      children: []
    });
  }

  const byId = new Map(parsed.map((item) => [item.navigationItemId, item]));
  for (const item of parsed) {
    if (item.parentNavigationItemId === item.navigationItemId) {
      return { nodes: [], error: `item ${item.navigationItemId} cannot be its own parent.` };
    }
    if (item.parentNavigationItemId !== null && !byId.has(item.parentNavigationItemId)) {
      return { nodes: [], error: `item ${item.navigationItemId} references missing parent ${item.parentNavigationItemId}.` };
    }
  }

  const visiting = new Set<number>();
  const visited = new Set<number>();
  function visit(item: ResolvedNavigationItem): boolean {
    if (visiting.has(item.navigationItemId)) return false;
    if (visited.has(item.navigationItemId)) return true;
    visiting.add(item.navigationItemId);
    if (item.parentNavigationItemId !== null) {
      const parent = byId.get(item.parentNavigationItemId);
      if (!parent || !visit(parent)) return false;
    }
    visiting.delete(item.navigationItemId);
    visited.add(item.navigationItemId);
    return true;
  }
  for (const item of parsed) {
    if (!visit(item)) {
      return { nodes: [], error: `navigation hierarchy contains a cycle involving item ${item.navigationItemId}.` };
    }
  }

  const groups = new Map<number | null, ResolvedNavigationItem[]>();
  for (const item of parsed) {
    const group = groups.get(item.parentNavigationItemId) ?? [];
    group.push(item);
    groups.set(item.parentNavigationItemId, group);
  }
  for (const [parentId, siblings] of groups) {
    const positions = new Set<number>();
    const labels = new Set<string>();
    for (const sibling of siblings) {
      const normalizedLabel = sibling.label.toLowerCase().replace(/\s+/g, " ");
      if (positions.has(sibling.position)) {
        return { nodes: [], error: `sibling ordering conflict at position ${sibling.position}${parentId === null ? "" : ` under item ${parentId}`}.` };
      }
      if (labels.has(normalizedLabel)) {
        return { nodes: [], error: `duplicate sibling label “${sibling.label}”.` };
      }
      positions.add(sibling.position);
      labels.add(normalizedLabel);
    }
    siblings.sort((left, right) => left.position - right.position || left.navigationItemId - right.navigationItemId);
  }
  for (const item of parsed) item.children = groups.get(item.navigationItemId) ?? [];
  return { nodes: groups.get(null) ?? [], error: null };
}

function text(value: unknown) { return typeof value === "string" || typeof value === "number" ? String(value) : ""; }
function normalizedString(value: unknown): string { return typeof value === "string" ? value.trim() : ""; }
function array(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function record(value: unknown): Record<string, unknown> { return value && typeof value === "object" ? value as Record<string, unknown> : {}; }
function number(value: unknown, fallback: number) { return typeof value === "number" && Number.isFinite(value) ? value : fallback; }
function positiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}
function displayPreset(value: string): PageMediaDisplayPreset | null {
  return PAGE_MEDIA_DISPLAY_PRESETS.has(value as PageMediaDisplayPreset)
    ? value as PageMediaDisplayPreset
    : null;
}
function nullablePositiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}
function nonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function useViewportWidth() {
  const [width, setWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    function update() {
      setWidth(window.innerWidth);
    }
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return width;
}

export function compositionValidationError(composition: PageComposition): string | null {
  if (composition.validation_errors.length) {
    return composition.validation_errors.join(" ");
  }
  if (composition.status !== "current") {
    return "The semantic page composition is not current.";
  }
  const themeError = themeValidationError(
    composition.resolved_theme,
    composition.website_id,
  );
  if (themeError) return themeError;
  return null;
}

export function previewRequestKey(
  id: string | undefined,
  showQa: boolean,
): string {
  return `${id ?? "missing"}:${showQa ? "qa" : "preview"}`;
}

export function hasCurrentPreviewData(
  requestKey: string,
  requestStateKey: string,
  data: { requestKey: string } | null,
): data is { requestKey: string } {
  return (
    requestStateKey === requestKey &&
    data !== null &&
    data.requestKey === requestKey
  );
}

export default GeneratedPagePreview;
