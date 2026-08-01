import { CSSProperties, useEffect, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, Image, Phone, ShieldCheck } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { apiRequest } from "../api";
import type { ApprovalAudit, AssignedMedia, City, County, GeneratedPage, GeneratedPageRevision, PageQAResult, PlannedPageDraftContent, Service, WebsiteContext } from "../types";

type PreviewData = {
  page: GeneratedPage;
  context: WebsiteContext;
  service: Service | null;
  city: City | null;
  county: County | null;
  media: AssignedMedia[];
};

type PlannedPagePreviewDraft = PlannedPageDraftContent;

function GeneratedPagePreview() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const showQa = searchParams.get("qa") === "1";
  const [data, setData] = useState<PreviewData | null>(null);
  const [qaResult, setQaResult] = useState<PageQAResult | null>(null);
  const [approvalCount, setApprovalCount] = useState(0);
  const [revisionCount, setRevisionCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadPreview() {
      const pageId = Number(id);
      if (!Number.isInteger(pageId)) {
        setError("Invalid generated page ID.");
        setLoading(false);
        return;
      }

      try {
        const page = await apiRequest<GeneratedPage>(`/api/generated-pages/${pageId}`);
        const [context, service, city, county, media] = await Promise.all([
          apiRequest<WebsiteContext>(`/api/generated-pages/${pageId}/website-context`),
          page.service_id
            ? apiRequest<Service>(`/api/services/${page.service_id}`)
            : Promise.resolve(null),
          page.city_id ? apiRequest<City>(`/api/cities/${page.city_id}`) : Promise.resolve(null),
          page.county_id ? apiRequest<County>(`/api/counties/${page.county_id}`) : Promise.resolve(null),
          apiRequest<AssignedMedia[]>(`/api/generated-pages/${page.id}/media`)
        ]);
        setData({ page, context, service, city, county, media });
        if (showQa) {
          const [qa, history, revisions] = await Promise.all([
            apiRequest<PageQAResult>(`/api/generated-pages/${page.id}/qa`),
            apiRequest<ApprovalAudit[]>(`/api/generated-pages/${page.id}/approval-history`),
            apiRequest<GeneratedPageRevision[]>(`/api/generated-pages/${page.id}/revisions`)
          ]);
          setQaResult(qa);
          setApprovalCount(history.length);
          setRevisionCount(revisions.length);
        }
        document.title = `${page.page_title} | Atlas Preview`;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load page preview.");
      } finally {
        setLoading(false);
      }
    }

    loadPreview();
    return () => {
      document.title = "Project Atlas";
    };
  }, [id, showQa]);

  if (loading) {
    return <PreviewState message="Loading page preview..." />;
  }

  if (error || !data) {
    return <PreviewState message={error ?? "Page preview is unavailable."} error />;
  }

  const draft = data.page.draft_content;
  if (!draft) {
    return <PreviewState message="Generate a structured draft before opening its customer-facing preview." />;
  }

  const { context, service, city, county, media } = data;
  if (isPlannedPageDraft(draft)) {
    return <PlannedPagePreview draft={draft} context={context} service={service} county={county} />;
  }
  if (!service) {
    return <PreviewState message="This legacy service-page draft is missing its Service relationship." error />;
  }
  const { business, brand, website } = context;
  const config = website.configuration;
  const configText = (key: string, fallback: string) =>
    typeof config[key] === "string" ? String(config[key]) : fallback;
  const phone = business.phone ?? "Contact us";
  const phoneHref = `tel:${phone.replace(/[^\d+]/g, "")}`;
  const location = city ? `${city.city_name}, ${city.state}` : business.main_city ?? business.state;
  const heroAssignment = media.find((assignment) => assignment.image_role === "hero");
  const heroImage = heroAssignment?.image;
  const heroSource = heroImage?.optimized_url || heroImage?.asset_url;
  const serviceAssignments = media.filter((assignment) => assignment.image_role === "service").sort(compareAssignments);
  const supportAssignments = media.filter((assignment) => assignment.image_role === "support").sort(compareAssignments);

  return (
    <div className="servicePreview">
      <div className="previewReviewBar">
        <div className="previewReviewInner">
          <Link to="/generated-pages" className="previewBackLink">
            <ArrowLeft size={16} aria-hidden="true" />
            Back to Atlas
          </Link>
          <span>Draft preview</span>
          <strong>Not published</strong>
        </div>
      </div>

      {showQa && qaResult && (
        <div className={`previewQaBanner ${qaResult.readiness_status}`}>
          <div className="previewContainer">
            <AlertTriangle size={17} aria-hidden="true" />
            <strong>Internal QA: {qaResult.readiness_status.replace(/_/g, " ")}</strong>
            <span>{qaResult.failed_count} blockers | {qaResult.warning_count} warnings</span>
            <span>{approvalCount ? `${approvalCount} prior approval${approvalCount === 1 ? "" : "s"}` : "No approval history"}</span>
            <span>{revisionCount} manual revision{revisionCount === 1 ? "" : "s"}</span>
          </div>
        </div>
      )}

      <header className="previewSiteHeader">
        <div className="previewContainer previewHeaderInner">
          <div className="previewBrand">
            <span className="previewBrandMark">
              {typeof brand.identity_settings.brand_mark === "string" ? brand.identity_settings.brand_mark : brand.public_name.slice(0, 2).toUpperCase()}
            </span>
            <div>
              <strong>{context.identity.display_name}</strong>
              <span>{brand.tagline ?? business.business_type}</span>
            </div>
          </div>
          <a className="previewPhoneLink" href={phoneHref}>
            <Phone size={18} aria-hidden="true" />
            <span>{phone}</span>
          </a>
        </div>
      </header>

      <main>
        <section className={heroSource ? "previewHero hasImage" : "previewHero"}>
          <div className="previewHeroMedia" aria-label={heroAssignment?.effective_alt_text ?? "Hero image placeholder"}>
            {heroSource ? (
              <img
                src={heroSource}
                alt={heroAssignment?.effective_alt_text ?? ""}
                title={heroImage.image_title}
                style={focalStyle(heroAssignment?.effective_focal_x, heroAssignment?.effective_focal_y)}
              />
            ) : (
              <div className="previewMediaLabel">
                <Image size={18} aria-hidden="true" />
                Hero image placeholder
              </div>
            )}
          </div>
          <div className="previewContainer previewHeroContent">
            <p className="previewKicker">{service.service_name} | {location}</p>
            <h1>{draft.h1}</h1>
            <p>{draft.hero_subheadline || draft.intro}</p>
            <div className="previewHeroActions">
              <a className="previewButton previewButtonPrimary" href={phoneHref}>
                <Phone size={18} aria-hidden="true" />
                Call {phone}
              </a>
              <a className="previewButton previewButtonSecondary" href="#estimate">
                Request an Estimate
              </a>
            </div>
            <div className="previewTrustLine">
              <ShieldCheck size={19} aria-hidden="true" />
              <span>{configText("preview_trust_line", `Licensed ${business.business_type}`)}</span>
            </div>
          </div>
        </section>

        <section className="previewBand">
          <div className="previewContainer previewIntroGrid">
            <div>
              <p className="previewSectionLabel">{configText("preview_service_label", "Local Service")}</p>
              <h2>Why {configText("preview_why_subject", service.service_name.toLowerCase())} matters in {city?.city_name ?? location}</h2>
              <p>{draft.intro}</p>
              <p>{draft.service_explanation || draft.why_it_matters}</p>
            </div>
            {serviceAssignments.length ? (
              <MediaGallery assignments={serviceAssignments} className="previewServiceGallery" />
            ) : (
              <div className="previewImagePlaceholder">
                <Image size={28} aria-hidden="true" />
                <strong>Service image placeholder</strong>
                <span>{service.service_name} photography will appear here.</span>
              </div>
            )}
          </div>
        </section>

        <section className="previewBand previewBandMuted">
          <div className="previewContainer previewTextSection">
            <p className="previewSectionLabel">What to Look For</p>
            <h2>{configText("preview_signs_heading", `Signs related to ${service.service_name.toLowerCase()}`)}</h2>
            <p>{draft.signs_section}</p>
          </div>
        </section>

        <section className="previewBand">
          <div className="previewContainer previewTwoColumn">
            <article>
              <p className="previewSectionLabel">{configText("preview_treatment_label", "Service")}</p>
              <h2>{configText("preview_process_heading", `How ${service.service_name.toLowerCase()} works`)}</h2>
              <p>{draft.process_section}</p>
            </article>
            <article>
              <p className="previewSectionLabel">{configText("preview_preparation_label", "Before Service")}</p>
              <h2>{configText("preview_preparation_heading", "Preparing the property")}</h2>
              <p>{draft.prep_section}</p>
            </article>
          </div>
        </section>

        <section className="previewBand previewProfessionalBand">
          <div className="previewContainer previewProfessionalInner">
            <CheckCircle2 size={30} aria-hidden="true" />
            <div>
              <p className="previewSectionLabel">Coordinated Service</p>
              <h2>Local service for {city?.city_name ?? location}</h2>
              <p>{draft.local_city_section || draft.realtor_property_manager_section}</p>
            </div>
          </div>
        </section>

        <section className="previewBand">
          <div className="previewContainer previewTextSection">
            <p className="previewSectionLabel">{configText("preview_why_label", `Why ${brand.public_name}`)}</p>
            <h2>Careful coordination from preparation through clearance</h2>
            <p>{draft.why_choose_section || draft.realtor_property_manager_section}</p>
          </div>
        </section>

        <section className="previewBand previewBandMuted">
          <div className="previewContainer">
            <p className="previewSectionLabel">{configText("preview_gallery_label", "Service Gallery")}</p>
            <h2>{configText("preview_gallery_heading", `${service.service_name} project views`)}</h2>
            {supportAssignments.length ? (
              <MediaGallery assignments={supportAssignments} className="previewSupportGallery" />
            ) : (
              <div className="previewImagePlaceholder previewGalleryPlaceholder">
                <Image size={28} aria-hidden="true" />
                <strong>Support image placeholder</strong>
                <span>Additional project photography will appear here.</span>
              </div>
            )}
          </div>
        </section>

        <section className="previewBand">
          <div className="previewContainer previewFaqSection">
            <p className="previewSectionLabel">Frequently Asked Questions</p>
            <h2>{configText("preview_faq_heading", `${service.service_name} questions`)}</h2>
            <div className="previewFaqList">
              {draft.faq_items.map((item) => (
                <details key={item.question}>
                  <summary>{item.question}</summary>
                  <p>{item.answer}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="previewFinalCta" id="estimate">
          <div className="previewContainer previewFinalCtaInner">
            <div>
              <p className="previewSectionLabel">{configText("preview_contact_label", `Talk With ${brand.public_name}`)}</p>
              <h2>Request service information for {city?.city_name ?? location}</h2>
              <p>{draft.call_to_action}</p>
            </div>
            <div className="previewFinalActions">
              <a className="previewButton previewButtonLight" href={phoneHref}>
                <Phone size={18} aria-hidden="true" />
                Call {phone}
              </a>
              <a className="previewButton previewButtonOutline" href={`mailto:${business.email ?? ""}`}>
                Request an Estimate
              </a>
            </div>
          </div>
        </section>
      </main>

      <footer className="previewFooter">
        <div className="previewContainer previewFooterInner">
          <strong>{business.company_name}</strong>
          <span>
            {business.license_number
              ? `${configText("license_label", "License")} ${business.license_number}`
              : configText("preview_trust_line", `Licensed ${business.business_type}`)}
            {business.certified_operator ? ` | Certified Operator: ${business.certified_operator}` : ""}
          </span>
          {county && <span>Serving {county.county_name} and surrounding target markets.</span>}
        </div>
      </footer>
    </div>
  );
}

function isPlannedPageDraft(draft: GeneratedPage["draft_content"]): draft is PlannedPagePreviewDraft {
  return (
    typeof draft === "object"
    && draft !== null
    && "schema_version" in draft
    && draft.schema_version === "planned-page-draft-v1"
  );
}

function PlannedPagePreview({
  draft,
  context,
  service,
  county
}: {
  draft: PlannedPagePreviewDraft;
  context: WebsiteContext;
  service: Service | null;
  county: County | null;
}) {
  const { business, brand } = context;
  const phone = business.phone ?? "Contact us";
  const phoneHref = `tel:${phone.replace(/[^\d+]/g, "")}`;

  return (
    <div className="servicePreview">
      <div className="previewReviewBar">
        <div className="previewReviewInner">
          <Link to="/site-plans" className="previewBackLink">
            <ArrowLeft size={16} aria-hidden="true" />
            Back to Site Plans
          </Link>
          <span>{draft.page_type.replace(/_/g, " ")} draft preview</span>
          <strong>Not published</strong>
        </div>
      </div>

      <header className="previewSiteHeader">
        <div className="previewContainer previewHeaderInner">
          <div className="previewBrand">
            <span className="previewBrandMark">
              {typeof brand.identity_settings.brand_mark === "string"
                ? brand.identity_settings.brand_mark
                : brand.public_name.slice(0, 2).toUpperCase()}
            </span>
            <div>
              <strong>{context.identity.display_name}</strong>
              <span>{brand.tagline ?? business.business_type}</span>
            </div>
          </div>
          <a className="previewPhoneLink" href={phoneHref}>
            <Phone size={18} aria-hidden="true" />
            <span>{phone}</span>
          </a>
        </div>
      </header>

      <main>
        <section className="previewHero">
          <div className="previewContainer previewHeroContent">
            <p className="previewKicker">
              {draft.page_type === "county" && service && county
                ? `${service.service_name} | ${county.county_name}`
                : `${draft.page_type.replace(/_/g, " ")} page`}
            </p>
            <h1>{draft.h1}</h1>
            <p>{draft.intro}</p>
            <div className="previewHeroActions">
              <a className="previewButton previewButtonPrimary" href={phoneHref}>
                <Phone size={18} aria-hidden="true" />
                Call {phone}
              </a>
              <a className="previewButton previewButtonSecondary" href="#estimate">
                Request an Estimate
              </a>
            </div>
            <div className="previewTrustLine">
              <ShieldCheck size={19} aria-hidden="true" />
              <span>
                {business.license_number
                  ? `Licensed ${business.business_type} | ${business.license_number}`
                  : `Established ${business.business_type}`}
              </span>
            </div>
          </div>
        </section>

        {draft.page_type === "county" && (draft.image_placements ?? []).length > 0 && (
          <section className="previewBand">
            <div className="previewContainer previewMediaGallery previewSupportGallery">
              {(draft.image_placements ?? []).map((placement) => (
                <div className="previewImagePlaceholder" key={placement.key}>
                  <Image size={28} aria-hidden="true" />
                  <strong>{placement.purpose}</strong>
                  <span>Image placement ready for future approved media.</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {draft.sections
          .filter(
            (section) =>
              draft.page_type !== "county"
              || !["cities_served", "related_city_services"].includes(section.key)
          )
          .map((section, index) => (
          <section className={index % 2 ? "previewBand previewBandMuted" : "previewBand"} key={section.key}>
            <div className="previewContainer previewTextSection">
              <h2>{section.heading}</h2>
              <p>{section.body}</p>
            </div>
          </section>
          ))}

        {(draft.related_pages ?? []).length > 0 && (
          <section className="previewBand previewBandMuted">
            <div className="previewContainer">
              <p className="previewSectionLabel">
                {draft.page_type === "county" && service
                  ? `${service.service_name} Near You`
                  : "Service Near You"}
              </p>
              <h2>
                {draft.page_type === "county" && county
                  ? `Cities We Serve in ${county.county_name}`
                  : "Explore Local Service Pages"}
              </h2>
              <div className="previewFaqList">
                {(draft.related_pages ?? []).map((page) => (
                  <article key={page.slug}>
                    <strong>{page.label}</strong>
                    <p>Learn more about service options for this community.</p>
                  </article>
                ))}
              </div>
            </div>
          </section>
        )}

        {draft.faq_items.length > 0 && (
          <section className="previewBand previewBandMuted">
            <div className="previewContainer previewFaqSection">
              <p className="previewSectionLabel">Frequently Asked Questions</p>
              <div className="previewFaqList">
                {draft.faq_items.map((item) => (
                  <details key={item.question}>
                    <summary>{item.question}</summary>
                    <p>{item.answer}</p>
                  </details>
                ))}
              </div>
            </div>
          </section>
        )}

        <section className="previewFinalCta" id="estimate">
          <div className="previewContainer previewFinalCtaInner">
            <div>
              <p className="previewSectionLabel">Next Step</p>
              <h2>{draft.title}</h2>
              <p>{draft.call_to_action}</p>
            </div>
            <div className="previewFinalActions">
              <a className="previewButton previewButtonLight" href={phoneHref}>
                <Phone size={18} aria-hidden="true" />
                Call {phone}
              </a>
              <a className="previewButton previewButtonOutline" href={`mailto:${business.email ?? ""}`}>
                Request an Estimate
              </a>
            </div>
          </div>
        </section>
      </main>

      <footer className="previewFooter">
        <div className="previewContainer previewFooterInner">
          <strong>{business.company_name}</strong>
          <span>
            {business.license_number
              ? `License ${business.license_number}`
              : business.business_type}
          </span>
        </div>
      </footer>
    </div>
  );
}

function PreviewState({ message, error = false }: { message: string; error?: boolean }) {
  return (
    <main className="previewState">
      <div>
        <p className="previewSectionLabel">{error ? "Preview Error" : "Atlas Preview"}</p>
        <h1>{message}</h1>
        <Link to="/generated-pages" className="previewButton previewButtonPrimary">
          <ArrowLeft size={18} aria-hidden="true" />
          Back to Generated Pages
        </Link>
      </div>
    </main>
  );
}

function MediaGallery({
  assignments,
  className
}: {
  assignments: AssignedMedia[];
  className: string;
}) {
  return (
    <div className={`previewMediaGallery ${className}`}>
      {assignments.map((assignment) => (
        <figure
          key={assignment.assignment_id}
          className={`previewGalleryItem ${presetClass(assignment.display_preset)}`}
        >
          <img
            src={assignment.image.optimized_url || assignment.image.asset_url}
            alt={assignment.effective_alt_text}
            title={assignment.image.image_title}
            style={focalStyle(assignment.effective_focal_x, assignment.effective_focal_y)}
          />
          {assignment.image.caption && <figcaption>{assignment.image.caption}</figcaption>}
        </figure>
      ))}
    </div>
  );
}

function presetClass(preset: AssignedMedia["display_preset"]) {
  return `preset-${preset.replace(/_/g, "-")}`;
}

function compareAssignments(left: AssignedMedia, right: AssignedMedia) {
  return left.sort_order - right.sort_order || left.assignment_id - right.assignment_id;
}

function focalStyle(focalX = 0.5, focalY = 0.5) {
  const normalizedX = Math.min(1, Math.max(0, focalX));
  const normalizedY = Math.min(1, Math.max(0, focalY));
  return {
    "--focal-x": `${normalizedX * 100}%`,
    "--focal-y": `${normalizedY * 100}%`
  } as CSSProperties;
}

export default GeneratedPagePreview;
