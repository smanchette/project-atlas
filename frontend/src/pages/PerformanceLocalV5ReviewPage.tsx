import {
  AlertTriangle,
  ArrowLeft,
  FlaskConical,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import { apiRequest } from "../api";
import {
  performanceLocalDeliveryApiPath,
  performanceLocalDeliveryConfiguration,
  performanceLocalDeliveryValidationError,
  type PerformanceLocalDeliveryConfiguration,
} from "../components/performanceLocalDelivery";
import {
  auditPerformanceLocalV4Composition,
  type PerformanceLocalV4LayoutAudit,
} from "../components/performanceLocalV4LayoutContract";
import {
  PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION,
} from "../components/performanceLocalV5Audit";
import {
  auditPerformanceLocalV5Composition,
  type PerformanceLocalV5LayoutAudit,
  type PerformanceLocalV5PageType,
} from "../components/performanceLocalV5LayoutContract";
import PerformanceLocalV4Renderer from "../components/PerformanceLocalV4Renderer";
import PerformanceLocalV5Renderer, {
  type PerformanceLocalV5PreviewSurface,
  type PerformanceLocalV5ReadinessProjection,
} from "../components/PerformanceLocalV5Renderer";
import type { PerformanceLocalV5ReviewMode } from "../components/PerformanceLocalV5Layouts";
import type { PerformanceLocalV5ActionConfiguration } from "../components/performanceLocalV5Actions";
import { performanceLocalFormDomId } from "../components/PerformanceLocalRenderer";
import {
  PERFORMANCE_LOCAL_V5_DEMO_MEDIA_LABEL,
  PERFORMANCE_LOCAL_V5_PREVIEW_LABEL,
  PERFORMANCE_LOCAL_V5_THEME,
} from "../components/performanceLocalThemeV5";
import {
  themePresentation,
  type ThemePresentation,
} from "../components/themeAdapter";
import type {
  GeneratedPage,
  PerformanceLocalDeliveryRead,
  PlannedPage,
  SitePlanDetail,
  ThemeDraftPreviewRead,
} from "../types";
import { isLoopbackThemeLabHost } from "./UniversalFormModesReviewPage";

type RendererSelection = "v5" | "v4_control";

type RepresentativePage = Readonly<{
  generatedPageId: number;
  pageTitle: string;
  pageType: PerformanceLocalV5PageType;
}>;

type ReviewData = Readonly<{
  configuration: PerformanceLocalDeliveryConfiguration;
  delivery: PerformanceLocalDeliveryRead;
  plannedPage: PlannedPage;
  readiness: PerformanceLocalV5ReadinessProjection;
  representatives: readonly RepresentativePage[];
  requestKey: string;
  v4Audit: PerformanceLocalV4LayoutAudit;
  v5Audit: PerformanceLocalV5LayoutAudit;
}>;

const PAGE_TYPE_ORDER: readonly PerformanceLocalV5PageType[] = Object.freeze([
  "home",
  "service",
  "county",
  "about",
  "contact",
  "faq",
  "city_service",
]);

export function PerformanceLocalV5ReviewPage({
  previewSurface = "generated_page",
}: {
  previewSurface?: PerformanceLocalV5PreviewSurface;
}) {
  const hostname = typeof window === "undefined" ? "localhost" : window.location.hostname;
  if (!isLoopbackThemeLabHost(hostname)) {
    return (
      <main className="performanceLocalV5ReviewState" role="alert">
        <p>Performance Local V5</p>
        <h1>Local Theme Lab only</h1>
        <p>This operator review is unavailable outside a loopback host.</p>
      </main>
    );
  }
  return <PerformanceLocalV5ReviewContent previewSurface={previewSurface} />;
}

function PerformanceLocalV5ReviewContent({
  previewSurface,
}: {
  previewSurface: PerformanceLocalV5PreviewSurface;
}) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestKey = `${id ?? "missing"}:${previewSurface}`;
  const [data, setData] = useState<ReviewData | null>(null);
  const [requestStateKey, setRequestStateKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reviewMode, setReviewMode] = useState<PerformanceLocalV5ReviewMode>(() =>
    searchParams.get("mode") === "structural_demo" ? "structural_demo" : "truthful",
  );
  const [rendererSelection, setRendererSelection] = useState<RendererSelection>(() =>
    searchParams.get("renderer") === "v4" ? "v4_control" : "v5",
  );
  const [campaignBannerEnabled, setCampaignBannerEnabled] = useState(() => searchParams.get("banner") !== "0");
  const [placeholderCount, setPlaceholderCount] = useState(0);
  const loadGeneration = useRef(0);
  const previewCanvasRef = useRef<HTMLDivElement>(null);
  const previewedAt = useRef(new Date()).current;
  const viewportWidth = useViewportWidth();

  useEffect(() => {
    const generation = ++loadGeneration.current;
    let cancelled = false;
    const isCurrent = () => !cancelled && generation === loadGeneration.current;
    setRequestStateKey(requestKey);
    setData(null);
    setError(null);
    setLoading(true);
    setPlaceholderCount(0);
    document.title = "Performance Local V5 Review | Project Atlas";

    async function loadReview() {
      const pageId = positiveInteger(id);
      if (!pageId) {
        if (isCurrent()) {
          setError("Invalid generated page ID.");
          setLoading(false);
        }
        return;
      }
      try {
        const [requestedPage, currentPages] = await Promise.all([
          apiRequest<GeneratedPage>(`/api/generated-pages/${pageId}`),
          apiRequest<GeneratedPage[]>("/api/generated-pages"),
        ]);
        const websiteId = positiveInteger(requestedPage.website_id);
        if (!websiteId) throw new Error("The requested Generated Page has no exact Website identity.");
        const representatives = representativePages(currentPages, websiteId);
        if (!isCurrentSupportedPerformanceLocalV5Page(requestedPage, currentPages, websiteId)) {
          throw new Error("The requested page is not an exact current supported page for its Website.");
        }
        const draftPreview = await apiRequest<ThemeDraftPreviewRead>(
          `/api/websites/${websiteId}/theme-configurations/draft-preview?family_key=performance-local&family_version=3&page_id=${pageId}`,
        );
        const configurationId = exactV3DraftConfigurationId(draftPreview, requestedPage);
        if (!configurationId) throw new Error("The exact inactive Performance Local V3 conversion configuration is unavailable.");
        const delivery = await apiRequest<PerformanceLocalDeliveryRead>(
          performanceLocalDeliveryApiPath("inactive_draft_preview", pageId, configurationId),
        );
        const deliveryError = performanceLocalDeliveryValidationError(delivery, "inactive_draft_preview", pageId, configurationId);
        if (deliveryError) throw new Error(deliveryError);
        const configuration = performanceLocalDeliveryConfiguration(delivery);
        if (!configuration) throw new Error("The governed V3 conversion input failed its exact source contract.");
        if (!sameCanonicalJson(requestedPage, delivery.page)) {
          throw new Error("The Generated Page changed between the review and governed delivery reads.");
        }
        const sitePlan = await apiRequest<SitePlanDetail>(`/api/site-plans/${delivery.composition.site_plan_id}`);
        const plannedPage = exactPlannedPage(sitePlan, delivery);
        if (!plannedPage) throw new Error("The exact Planned Page could not be joined without crossing scope.");
        const auditInput = { page: delivery.page, plannedPage, composition: delivery.composition };
        const v5Audit = auditPerformanceLocalV5Composition(auditInput);
        const v4Audit = auditPerformanceLocalV4Composition(auditInput);
        const readiness = deliveryReadinessProjection(delivery);
        if (!isCurrent()) return;
        setData({
          configuration,
          delivery,
          plannedPage,
          readiness,
          representatives,
          requestKey,
          v4Audit,
          v5Audit,
        });
        document.title = `${delivery.page.page_title} | Performance Local V5 Review`;
      } catch (value) {
        if (!isCurrent()) return;
        setError(value instanceof Error ? value.message : "Unable to load the V5 review surface.");
      } finally {
        if (isCurrent()) setLoading(false);
      }
    }

    void loadReview();
    return () => {
      cancelled = true;
      if (generation === loadGeneration.current) loadGeneration.current += 1;
      document.title = "Project Atlas";
    };
  }, [requestKey]);

  const currentData = requestStateKey === requestKey && data?.requestKey === requestKey ? data : null;

  useEffect(() => {
    if (!currentData || rendererSelection !== "v5") {
      setPlaceholderCount(0);
      return;
    }
    setPlaceholderCount(previewCanvasRef.current?.querySelectorAll("[data-v5-demo-media-slot]").length ?? 0);
  }, [currentData, rendererSelection, reviewMode]);

  if (requestStateKey !== requestKey || loading) return <ReviewState message="Loading current V5 layout review…" />;
  if (error || !currentData) return <ReviewState message={error ?? "V5 review is unavailable."} error />;

  const {
    configuration,
    delivery,
    plannedPage,
    readiness,
    representatives,
    v4Audit,
    v5Audit,
  } = currentData;
  const governedPresentation = resolvedThemePresentation(delivery, viewportWidth);
  if (!governedPresentation) return <ReviewState message="The governed Theme presentation is invalid for this V5 review." error />;
  const stickyConfigured = Boolean(configuration.stickyActions.enabled && configuration.stickyActions.mobileStickyActionsEnabled);
  const actionConfiguration = performanceLocalV5ThemeLabActionConfiguration(
    configuration,
    delivery.page.id,
    plannedPage,
    previewSurface,
  );
  const selectedRepresentativeId = representatives.some((candidate) => candidate.generatedPageId === delivery.page.id)
    ? delivery.page.id
    : "";

  return (
    <div
      className="performanceLocalV5Review"
      data-v5-review-surface="local-only"
      data-v5-review-mode={reviewMode}
      data-v5-renderer-selection={rendererSelection}
    >
      <header className="performanceLocalV5ReviewHeader">
        <div>
          <Link to="/generated-pages" className="performanceLocalV5ReviewBack"><ArrowLeft aria-hidden="true" /> Generated Pages</Link>
          <p><FlaskConical aria-hidden="true" /> Operator-only layout review</p>
          <strong className="performanceLocalV5ReviewTitle">{PERFORMANCE_LOCAL_V5_PREVIEW_LABEL}</strong>
          <span>{delivery.page.page_title}</span>
        </div>
        <div className="performanceLocalV5ReviewControls" aria-label="V5 review controls">
          <label>
            Representative page
            <select
              aria-label="Representative page"
              value={selectedRepresentativeId}
              onChange={(event) => navigate(`/theme-lab/performance-local/v5/generated-pages/${event.target.value}`)}
            >
              {selectedRepresentativeId === "" ? <option value="" disabled>Choose a representative</option> : null}
              {representatives.map((candidate) => (
                <option key={candidate.generatedPageId} value={candidate.generatedPageId}>
                  {pageTypeLabel(candidate.pageType)} — {candidate.pageTitle}
                </option>
              ))}
            </select>
          </label>
          <fieldset>
            <legend>Content mode</legend>
            <button type="button" aria-pressed={reviewMode === "truthful"} onClick={() => setReviewMode("truthful")}>Truthful resolved</button>
            <button type="button" aria-pressed={reviewMode === "structural_demo"} onClick={() => setReviewMode("structural_demo")}>Structural demo</button>
          </fieldset>
          <fieldset>
            <legend>Renderer</legend>
            <button type="button" aria-pressed={rendererSelection === "v5"} onClick={() => setRendererSelection("v5")}>V5 layout</button>
            <button type="button" aria-pressed={rendererSelection === "v4_control"} onClick={() => setRendererSelection("v4_control")}>V4 control</button>
          </fieldset>
          <label className="performanceLocalV5ReviewCheckbox">
            <input type="checkbox" checked={campaignBannerEnabled} onChange={(event) => setCampaignBannerEnabled(event.target.checked)} />
            Campaign banner
          </label>
        </div>
      </header>

      {reviewMode === "structural_demo" && rendererSelection === "v5" ? (
        <p className="performanceLocalV5DemoNotice">{PERFORMANCE_LOCAL_V5_DEMO_MEDIA_LABEL}</p>
      ) : null}

      <div
        ref={previewCanvasRef}
        className="performanceLocalV5PreviewCanvas"
        data-v5-preview-canvas="true"
        data-v5-page-type={v5Audit.pageType ?? "unsupported"}
        data-v5-layout-key={v5Audit.layoutKey ?? "blocked"}
        style={governedPresentation.style}
        {...governedPresentation.attributes}
      >
        {rendererSelection === "v5" ? (
          <PerformanceLocalV5Renderer
            actionConfiguration={actionConfiguration}
            audit={v5Audit}
            campaignBannerEnabled={campaignBannerEnabled}
            composition={delivery.composition}
            page={delivery.page}
            previewedAt={previewedAt}
            readiness={readiness}
            reviewMode={reviewMode}
            previewSurface={previewSurface}
            v3Configuration={configuration}
          />
        ) : (
          <div data-v5-v4-control="true">
            <PerformanceLocalV4Renderer
              audit={v4Audit}
              campaignBannerEnabled={campaignBannerEnabled}
              composition={delivery.composition}
              page={delivery.page}
              previewedAt={previewedAt}
              readiness={readiness}
              reviewMode={reviewMode}
              v3Configuration={configuration}
            />
          </div>
        )}
      </div>

      <section className="performanceLocalV5DiagnosticPanel" data-v5-diagnostic-panel="true" aria-labelledby="performance-local-v5-diagnostic-heading">
        <div className="performanceLocalV5DiagnosticHeading">
          <div><p>Source-bound review</p><h2 id="performance-local-v5-diagnostic-heading">V5 page-type diagnostics</h2></div>
          <span data-tone={v5Audit.layoutReady ? "ready" : "blocked"}>{v5Audit.layoutReady ? "Layout ready" : "Layout blocked"}</span>
        </div>
        <dl className="performanceLocalV5DiagnosticGrid">
          <Diagnostic label="Website" value={v5Audit.sourceIdentity.websiteId} />
          <Diagnostic label="Site Plan" value={v5Audit.sourceIdentity.sitePlanId} />
          <Diagnostic label="Planned Page" value={plannedPage.id} />
          <Diagnostic label="Generated Page" value={delivery.page.id} />
          <Diagnostic label="Composition" value={`${delivery.composition.id}/v${delivery.composition.composition_version}`} />
          <Diagnostic label="Composition source" value={delivery.composition.source_hash} />
          <Diagnostic label="Raw page type" value={delivery.page.page_type} />
          <Diagnostic label="V5 layout" value={v5Audit.layoutKey ?? "blocked"} />
          <Diagnostic label="Compatibility" value={v5Audit.compatibilityIdentity} />
          <Diagnostic label="Renderer contract" value={PERFORMANCE_LOCAL_V5_THEME.rendererContract} />
          <Diagnostic label="Lifecycle" value={PERFORMANCE_LOCAL_V5_THEME.status} />
          <Diagnostic label="Production ready" value={PERFORMANCE_LOCAL_V5_THEME.productionReady} />
          <Diagnostic label="Review mode" value={reviewMode} />
          <Diagnostic label="Renderer view" value={rendererSelection} />
          <Diagnostic label="Source components" value={v5Audit.sourceComponentCount} />
          <Diagnostic label="Consumed components" value={v5Audit.consumedComponentCount} />
          <Diagnostic label="Audited destinations" value={v5Audit.destinationConsumption.length} />
          <Diagnostic label="Placeholder count" value={placeholderCount} />
          <Diagnostic label="Campaign banner" value={campaignBannerEnabled && Boolean(configuration.campaign)} />
          <Diagnostic label="Sticky actions" value={stickyConfigured} />
          <Diagnostic label="Form provider" value={delivery.form_readiness.status} />
          <Diagnostic label="Form can submit" value={delivery.form_readiness.can_submit} />
          <Diagnostic label="Layout ready" value={v5Audit.layoutReady} />
          <Diagnostic label="Media ready" value={readiness.mediaReady} />
          <Diagnostic label="QA ready" value={readiness.qaReady} />
          <Diagnostic label="Form ready" value={readiness.formReady} />
          <Diagnostic label="Activation ready" value={readiness.activationReady} />
          <Diagnostic label="Export ready" value={readiness.exportReady} />
          <Diagnostic label="Publication ready" value={readiness.publicationReady} />
        </dl>
        <div className="performanceLocalV5DiagnosticLists">
          <DiagnosticList label="Missing required regions" values={v5Audit.missingRequiredRegionKeys} />
          <DiagnosticList label="Missing optional regions" values={v5Audit.missingOptionalRegionKeys} />
          <DiagnosticList label="Unconsumed source instances" values={v5Audit.unconsumedSourceInstanceKeys} />
          <DiagnosticList label="Duplicated source instances" values={v5Audit.duplicatedSourceInstanceKeys} />
          <DiagnosticList label="Unconsumed destination entries" values={v5Audit.unconsumedDestinationEntryKeys} />
          <DiagnosticList label="Duplicated destination entries" values={v5Audit.duplicatedDestinationEntryKeys} />
          <DiagnosticList label="Ownership mismatches" values={v5Audit.ownershipMismatches} />
          <DiagnosticList label="Layout blockers" values={v5Audit.blockers.map((blocker) => `${blocker.code}: ${blocker.message}`)} />
          <DiagnosticList label="Delivery blockers" values={delivery.blockers.map((blocker) => `${blocker.code}: ${blocker.reason}`)} />
        </div>
        {v5Audit.manifest ? (
          <details className="performanceLocalV5Manifest">
            <summary>Page-type layout manifest</summary>
            <dl>
              <Diagnostic label="Manifest" value={`${v5Audit.manifest.layoutKey}@${v5Audit.manifest.layoutVersion}`} />
              <Diagnostic label="Supported page type" value={v5Audit.manifest.supportedPageType} />
              <Diagnostic label="Required regions" value={v5Audit.manifest.requiredSemanticRegions.join(", ")} />
              <Diagnostic label="Optional regions" value={v5Audit.manifest.optionalSemanticRegions.join(", ") || "none"} />
              <Diagnostic label="Diagnostic identity" value={v5Audit.manifest.diagnosticIdentity} />
            </dl>
          </details>
        ) : null}
        <p className="performanceLocalV5SafetyNote"><AlertTriangle aria-hidden="true" /> This source-only V5 review cannot activate, export, publish, or create a Theme selection.</p>
      </section>
    </div>
  );
}

function Diagnostic({ label, value }: { label: string; value: unknown }) {
  return <div><dt>{label}</dt><dd>{formatDiagnostic(value)}</dd></div>;
}

function DiagnosticList({ label, values }: { label: string; values: readonly unknown[] }) {
  return (
    <div>
      <h3>{label}</h3>
      {values.length ? <ul>{values.map((value, index) => <li key={`${String(value)}-${index}`}>{String(value)}</li>)}</ul> : <p>None</p>}
    </div>
  );
}

function ReviewState({ message, error = false }: { message: string; error?: boolean }) {
  return (
    <main className="performanceLocalV5ReviewState" role={error ? "alert" : undefined}>
      <p>{error ? "V5 review error" : "Performance Local V5"}</p>
      <h1>{message}</h1>
      <Link to="/generated-pages"><ArrowLeft aria-hidden="true" /> Generated Pages</Link>
    </main>
  );
}

function representativePages(pages: readonly GeneratedPage[], websiteId: number): RepresentativePage[] {
  const supported = new Set(PAGE_TYPE_ORDER);
  const byType = new Map<PerformanceLocalV5PageType, GeneratedPage>();
  for (const page of [...pages].sort((left, right) => left.id - right.id)) {
    if (page.website_id !== websiteId || !supported.has(page.page_type as PerformanceLocalV5PageType)) continue;
    const pageType = page.page_type as PerformanceLocalV5PageType;
    if (
      pageType === "city_service" &&
      page.id !== PERFORMANCE_LOCAL_V5_PAGE_41_EXPECTATION.generatedPageId
    ) continue;
    if (!byType.has(pageType)) byType.set(pageType, page);
  }
  return PAGE_TYPE_ORDER.flatMap((pageType) => {
    const page = byType.get(pageType);
    return page ? [{ generatedPageId: page.id, pageTitle: page.page_title, pageType }] : [];
  });
}

export function isCurrentSupportedPerformanceLocalV5Page(
  requestedPage: GeneratedPage,
  currentPages: readonly GeneratedPage[],
  websiteId: number,
): boolean {
  if (
    requestedPage.website_id !== websiteId ||
    !PAGE_TYPE_ORDER.includes(requestedPage.page_type as PerformanceLocalV5PageType)
  ) return false;
  return currentPages.filter((page) =>
    page.id === requestedPage.id &&
    page.website_id === websiteId &&
    page.page_type === requestedPage.page_type
  ).length === 1;
}

function pageTypeLabel(pageType: PerformanceLocalV5PageType): string {
  return pageType === "county" ? "Service-County" : pageType === "city_service" ? "City-Service" : pageType[0].toUpperCase() + pageType.slice(1);
}

function exactV3DraftConfigurationId(preview: ThemeDraftPreviewRead, page: GeneratedPage): number | null {
  const configurationId = positiveInteger(preview.website_configuration.id);
  if (
    preview.theme_family.family_key !== "performance-local" ||
    preview.theme_version.version !== 3 ||
    preview.theme_version.lifecycle_status !== "preview_candidate" ||
    preview.theme_version.production_ready !== false ||
    preview.website_configuration.lifecycle_status !== "draft" ||
    preview.website_configuration.website_id !== page.website_id ||
    preview.requested_generated_page_id !== page.id ||
    preview.website_configuration.materialized_theme_id !== null ||
    preview.website_configuration.website_theme_selection_id !== null ||
    preview.export_eligible !== false ||
    preview.readiness.can_activate !== false ||
    preview.readiness.can_publish !== false ||
    preview.readiness.can_deploy !== false
  ) return null;
  return configurationId;
}

function exactPlannedPage(sitePlan: SitePlanDetail, delivery: PerformanceLocalDeliveryRead): PlannedPage | null {
  if (sitePlan.id !== delivery.composition.site_plan_id || sitePlan.website_id !== delivery.composition.website_id) return null;
  const matches = sitePlan.planned_pages.filter((plannedPage) =>
    plannedPage.id === delivery.composition.planned_page_id &&
    plannedPage.site_plan_id === sitePlan.id &&
    plannedPage.website_id === sitePlan.website_id &&
    plannedPage.generated_page_id === delivery.page.id &&
    plannedPage.page_type === delivery.page.page_type,
  );
  return matches.length === 1 ? matches[0] : null;
}

function deliveryReadinessProjection(delivery: PerformanceLocalDeliveryRead): PerformanceLocalV5ReadinessProjection {
  const mediaReady = !delivery.blockers.some((blocker) => blocker.category === "media");
  const qaReady = delivery.page.qa_status === "ready" && !delivery.blockers.some((blocker) => blocker.category === "qa");
  const formReady = delivery.form_readiness.status === "ready" && delivery.form_readiness.can_submit === true;
  return Object.freeze({ mediaReady, qaReady, formReady, activationReady: false, exportReady: false, publicationReady: false });
}

export function performanceLocalV5ThemeLabActionConfiguration(
  configuration: PerformanceLocalDeliveryConfiguration,
  generatedPageId: number,
  plannedPage: PlannedPage,
  previewSurface: PerformanceLocalV5PreviewSurface,
): PerformanceLocalV5ActionConfiguration {
  const baseRoute = `/theme-lab/performance-local/v5/generated-pages/${generatedPageId}`;
  const estimateRoute = `${baseRoute}/request-an-estimate`;
  const specialRoute = `${baseRoute}/special`;
  const formIdentity = {
    componentConfigurationId: configuration.estimateForm.componentConfigurationId,
    componentInstanceKey: configuration.estimateForm.componentInstanceKey,
    destination: `#${performanceLocalFormDomId(configuration.estimateForm.componentConfigurationId)}`,
  };
  const campaign = configuration.campaign;
  const approvedPrimaryAction = plannedPage.planning_record.effective_answers.primary_action;
  const governedEstimateIntroduction = typeof approvedPrimaryAction === "string"
    ? approvedPrimaryAction
    : "";
  const estimateEnabled = Boolean(
    campaign?.enabled &&
    campaign.intent === "evergreen_conversion" &&
    campaign.campaignLabel === "Request an Estimate" &&
    campaign.ctaLabel === "Request an Estimate" &&
    campaign.ctaDestination === formIdentity.destination &&
    configuration.estimateForm.ctaLabel === "Request an Estimate",
  );
  const estimate: PerformanceLocalV5ActionConfiguration["estimate"] = estimateEnabled ? {
    enabled: true,
    formIdentity,
    heading: "Request an Estimate",
    introduction: governedEstimateIntroduction,
    phoneAlternativeEnabled: Boolean(configuration.governedContact),
    route: estimateRoute,
  } : { enabled: false };
  const demoSpecialEnabled = previewSurface === "special" || previewSurface === "estimate";
  const demoSpecialLabel = "DEMO SPECIAL — NOT SITE CONTENT";
  const special: PerformanceLocalV5ActionConfiguration["special"] = demoSpecialEnabled ? {
    callActionEnabled: true,
    description: "No public Special is configured. This local Theme Lab preview demonstrates the optional Special-page layout only.",
    enabled: true,
    estimateActionEnabled: true,
    expiresAt: null,
    headline: demoSpecialLabel,
    route: specialRoute,
  } : { enabled: false };
  const sticky: PerformanceLocalV5ActionConfiguration["sticky"] = previewSurface === "sticky_disabled"
    ? { mode: "disabled" }
    : demoSpecialEnabled
      ? {
          accessibilityLabel: demoSpecialLabel,
          destination: specialRoute,
          mode: "special",
          publicLabel: demoSpecialLabel,
        }
      : {
          accessibilityLabel: "Request an Estimate",
          destination: estimateRoute,
          mode: "estimate",
          publicLabel: "Request an Estimate",
        };
  return Object.freeze({
    authorizedServicePromotionDestinations: Object.freeze([]),
    estimate,
    special,
    sticky,
  });
}

function resolvedThemePresentation(delivery: PerformanceLocalDeliveryRead, viewportWidth: number): ThemePresentation | null {
  try {
    return themePresentation(delivery.composition.resolved_theme, delivery.composition.website_id, viewportWidth);
  } catch {
    return null;
  }
}

function useViewportWidth(): number {
  const [width, setWidth] = useState(() => typeof window === "undefined" ? 1440 : window.innerWidth);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const update = () => setWidth(window.innerWidth);
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return width;
}

function formatDiagnostic(value: unknown): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === null || value === undefined || value === "") return "Not available";
  return String(value);
}

function positiveInteger(value: unknown): number | null {
  const numeric = typeof value === "string" && value.trim() ? Number(value) : value;
  return typeof numeric === "number" && Number.isSafeInteger(numeric) && numeric > 0 ? numeric : null;
}

function sameCanonicalJson(left: unknown, right: unknown): boolean {
  return JSON.stringify(canonicalJsonValue(left)) === JSON.stringify(canonicalJsonValue(right));
}

function canonicalJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalJsonValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalJsonValue(item)]));
  }
  return value;
}

export default PerformanceLocalV5ReviewPage;
