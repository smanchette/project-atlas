import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowLeft, Image, Phone, ShieldCheck } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { apiRequest } from "../api";
import {
  WebsiteIdentityLogo,
  installIdentityHeadTags,
  removeIdentityHeadTags,
} from "../components/WebsiteIdentityPresentation";
import type {
  ApprovalAudit,
  GeneratedPage,
  GeneratedPageRevision,
  PageComponentInstance,
  PageComposition,
  PageQAResult
} from "../types";

type PreviewData = {
  page: GeneratedPage;
  composition: PageComposition;
  requestKey: string;
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
  return (
    <div className="servicePreview atlasBasePresentation">
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
        <div className={`previewQaBanner ${qaResult.readiness_status}`}>
          <div className="previewContainer">
            <AlertTriangle size={17} aria-hidden="true" />
            <strong>Internal QA: {qaResult.readiness_status.replace(/_/g, " ")}</strong>
            <span>{qaResult.failed_count} blockers | {qaResult.warning_count} warnings</span>
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
      return (
        <section className="previewBand" key={component.instance_key} aria-label={text(data.purpose)}>
          <div className="previewContainer">
            {data.asset_url ? (
              <figure className="previewGalleryItem">
                <img
                  src={text(data.asset_url)}
                  alt={text(data.alt_text)}
                  title={text(data.image_title)}
                  style={{ objectPosition: `${number(data.focal_x, 0.5) * 100}% ${number(data.focal_y, 0.5) * 100}%` }}
                />
                {Boolean(data.caption) && <figcaption>{text(data.caption)}</figcaption>}
              </figure>
            ) : (
              <div className="previewImagePlaceholder">
                <Image size={28} aria-hidden="true" /><strong>{text(data.purpose)}</strong>
                <span>Placement reserved for future approved media.</span>
              </div>
            )}
          </div>
        </section>
      );
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

function Navigation({ component }: { component: PageComponentInstance }) {
  const items = array(component.resolved_data.items);
  return (
    <nav className={`semanticNavigation semanticNavigation-${component.component_key}`} aria-label={text(component.resolved_data.label)}>
      <div className="previewContainer"><ul>{items.map((item, index) => { const value = record(item); return <li key={`${text(value.slug)}-${index}`}><a href={`/${text(value.slug).replace(/^\/+|\/+$/g, "")}/`}>{text(value.label)}</a></li>; })}</ul></div>
    </nav>
  );
}

function RelatedLinks({ component }: { component: PageComponentInstance }) {
  const links = array(component.resolved_data.links);
  return (
    <section className="previewBand previewBandMuted" aria-label="Related destinations">
      <div className="previewContainer"><h2>Related pages</h2><div className="semanticDestinationGrid">
        {links.map((item, index) => { const value = record(item); return <article key={`${text(value.slug)}-${index}`}><h3><a href={`/${text(value.slug).replace(/^\/+|\/+$/g, "")}/`}>{text(value.label)}</a></h3><p>{text(value.purpose)}</p></article>; })}
      </div></div>
    </section>
  );
}

function ContactLink({ value, kind, button = false }: { value: string; kind: "phone" | "email"; button?: boolean }) {
  const href = kind === "phone" ? `tel:${value.replace(/[^\d+]/g, "")}` : `mailto:${value}`;
  return <a className={button ? "previewButton previewButtonPrimary" : "previewPhoneLink"} href={href}>{kind === "phone" && <Phone size={18} aria-hidden="true" />}<span>{kind === "phone" ? `Call ${value}` : value}</span></a>;
}

function PreviewState({ message, error = false }: { message: string; error?: boolean }) {
  return <main className="previewState"><div><p className="previewSectionLabel">{error ? "Preview Error" : "Atlas Preview"}</p><h1>{message}</h1><Link to="/generated-pages" className="previewButton previewButtonPrimary"><ArrowLeft size={18} aria-hidden="true" /> Back to Generated Pages</Link></div></main>;
}

function text(value: unknown) { return typeof value === "string" || typeof value === "number" ? String(value) : ""; }
function array(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function record(value: unknown): Record<string, unknown> { return value && typeof value === "object" ? value as Record<string, unknown> : {}; }
function number(value: unknown, fallback: number) { return typeof value === "number" && Number.isFinite(value) ? value : fallback; }

export function compositionValidationError(composition: PageComposition): string | null {
  if (composition.validation_errors.length) {
    return composition.validation_errors.join(" ");
  }
  if (composition.status !== "current") {
    return "The semantic page composition is not current.";
  }
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
