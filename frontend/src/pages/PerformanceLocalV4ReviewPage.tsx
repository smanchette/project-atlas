import { AlertTriangle, ArrowLeft, FlaskConical } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
} from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { apiRequest } from "../api";
import PerformanceLocalRenderer from "../components/PerformanceLocalRenderer";
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
import PerformanceLocalV4Renderer, {
  type PerformanceLocalV4ReadinessProjection,
} from "../components/PerformanceLocalV4Renderer";
import type { PerformanceLocalV4ReviewMode } from "../components/PerformanceLocalV4Layouts";
import {
  PERFORMANCE_LOCAL_V4_DEMO_MEDIA_LABEL,
  PERFORMANCE_LOCAL_V4_PREVIEW_LABEL,
  PERFORMANCE_LOCAL_V4_THEME,
} from "../components/performanceLocalThemeV4";
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

type RendererSelection = "v4" | "v3_control";

type ReviewData = Readonly<{
  audit: PerformanceLocalV4LayoutAudit;
  configuration: PerformanceLocalDeliveryConfiguration;
  delivery: PerformanceLocalDeliveryRead;
  plannedPage: PlannedPage;
  readiness: PerformanceLocalV4ReadinessProjection;
  requestKey: string;
}>;

export function PerformanceLocalV4ReviewPage() {
  const hostname = typeof window === "undefined" ? "localhost" : window.location.hostname;
  if (!isLoopbackThemeLabHost(hostname)) {
    return (
      <main className="performanceLocalV4ReviewState" role="alert">
        <p>Performance Local V4</p>
        <h1>Local Theme Lab only</h1>
        <p>This operator review is unavailable outside a loopback host.</p>
      </main>
    );
  }
  return <PerformanceLocalV4ReviewContent />;
}

function PerformanceLocalV4ReviewContent() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const requestKey = id ?? "missing";
  const [data, setData] = useState<ReviewData | null>(null);
  const [requestStateKey, setRequestStateKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reviewMode, setReviewMode] = useState<PerformanceLocalV4ReviewMode>(() =>
    searchParams.get("mode") === "structural_demo" ? "structural_demo" : "truthful",
  );
  const [rendererSelection, setRendererSelection] = useState<RendererSelection>(() =>
    searchParams.get("renderer") === "v3" ? "v3_control" : "v4",
  );
  const [campaignBannerEnabled, setCampaignBannerEnabled] = useState(
    () => searchParams.get("banner") !== "0",
  );
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
    document.title = "Performance Local V4 Review | Project Atlas";

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
        const requestedPage = await apiRequest<GeneratedPage>(`/api/generated-pages/${pageId}`);
        const websiteId = positiveInteger(requestedPage.website_id);
        if (!websiteId) throw new Error("The requested Generated Page has no exact Website identity.");
        const draftPreview = await apiRequest<ThemeDraftPreviewRead>(
          `/api/websites/${websiteId}/theme-configurations/draft-preview?family_key=performance-local&family_version=3&page_id=${pageId}`,
        );
        const configurationId = exactV3DraftConfigurationId(draftPreview, requestedPage);
        if (!configurationId) {
          throw new Error("The exact inactive Performance Local V3 conversion configuration is unavailable.");
        }
        const delivery = await apiRequest<PerformanceLocalDeliveryRead>(
          performanceLocalDeliveryApiPath("inactive_draft_preview", pageId, configurationId),
        );
        const deliveryError = performanceLocalDeliveryValidationError(
          delivery,
          "inactive_draft_preview",
          pageId,
          configurationId,
        );
        if (deliveryError) throw new Error(deliveryError);
        const configuration = performanceLocalDeliveryConfiguration(delivery);
        if (!configuration) {
          throw new Error("The governed V3 conversion input failed its exact source contract.");
        }
        if (!sameCanonicalJson(requestedPage, delivery.page)) {
          throw new Error("The Generated Page changed between the review and governed delivery reads.");
        }
        const sitePlan = await apiRequest<SitePlanDetail>(
          `/api/site-plans/${delivery.composition.site_plan_id}`,
        );
        const plannedPage = exactPlannedPage(sitePlan, delivery);
        if (!plannedPage) {
          throw new Error("The exact Planned Page could not be joined without crossing scope.");
        }
        const audit = auditPerformanceLocalV4Composition({
          page: delivery.page,
          plannedPage,
          composition: delivery.composition,
        });
        const readiness = deliveryReadinessProjection(delivery);
        if (!isCurrent()) return;
        setData({ audit, configuration, delivery, plannedPage, readiness, requestKey });
        document.title = `${delivery.page.page_title} | Performance Local V4 Review`;
      } catch (value) {
        if (!isCurrent()) return;
        setError(value instanceof Error ? value.message : "Unable to load the V4 review surface.");
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
    if (!currentData || rendererSelection !== "v4") {
      setPlaceholderCount(0);
      return;
    }
    setPlaceholderCount(
      previewCanvasRef.current?.querySelectorAll("[data-v4-demo-media-slot]").length ?? 0,
    );
  }, [currentData, rendererSelection, reviewMode]);

  if (requestStateKey !== requestKey || loading) {
    return <ReviewState message="Loading current V4 layout review…" />;
  }
  if (error || !currentData) {
    return <ReviewState message={error ?? "V4 review is unavailable."} error />;
  }

  const { audit, configuration, delivery, plannedPage, readiness } = currentData;
  const governedPresentation = resolvedThemePresentation(
    delivery,
    viewportWidth,
  );
  if (!governedPresentation) {
    return <ReviewState message="The governed Theme presentation is invalid for this V4 review." error />;
  }
  const stickyConfigured = Boolean(
    configuration.stickyActions.enabled &&
    configuration.stickyActions.mobileStickyActionsEnabled,
  );
  return (
    <div
      className="performanceLocalV4Review"
      data-v4-review-surface="local-only"
      data-v4-review-mode={reviewMode}
      data-v4-renderer-selection={rendererSelection}
    >
      <header className="performanceLocalV4ReviewHeader">
        <div>
          <Link to="/generated-pages" className="performanceLocalV4ReviewBack">
            <ArrowLeft aria-hidden="true" /> Generated Pages
          </Link>
          <p><FlaskConical aria-hidden="true" /> Operator-only layout review</p>
          <strong className="performanceLocalV4ReviewTitle">{PERFORMANCE_LOCAL_V4_PREVIEW_LABEL}</strong>
          <span>{delivery.page.page_title}</span>
        </div>
        <div className="performanceLocalV4ReviewControls" aria-label="V4 review controls">
          <fieldset>
            <legend>Content mode</legend>
            <button
              type="button"
              aria-pressed={reviewMode === "truthful"}
              onClick={() => setReviewMode("truthful")}
            >
              Truthful resolved
            </button>
            <button
              type="button"
              aria-pressed={reviewMode === "structural_demo"}
              onClick={() => setReviewMode("structural_demo")}
            >
              Structural demo
            </button>
          </fieldset>
          <fieldset>
            <legend>Renderer</legend>
            <button
              type="button"
              aria-pressed={rendererSelection === "v4"}
              onClick={() => setRendererSelection("v4")}
            >
              V4 layout
            </button>
            <button
              type="button"
              aria-pressed={rendererSelection === "v3_control"}
              onClick={() => setRendererSelection("v3_control")}
            >
              V3 control
            </button>
          </fieldset>
          <label>
            <input
              type="checkbox"
              checked={campaignBannerEnabled}
              onChange={(event) => setCampaignBannerEnabled(event.target.checked)}
            />
            Campaign banner
          </label>
        </div>
      </header>

      {reviewMode === "structural_demo" && rendererSelection === "v4" ? (
        <p className="performanceLocalV4DemoNotice">{PERFORMANCE_LOCAL_V4_DEMO_MEDIA_LABEL}</p>
      ) : null}

      <div
        ref={previewCanvasRef}
        className="performanceLocalV4PreviewCanvas"
        data-v4-preview-canvas="true"
        data-v4-page-type={audit.pageType ?? "unsupported"}
        data-v4-layout-key={audit.layoutKey ?? "blocked"}
        style={governedPresentation.style}
        {...governedPresentation.attributes}
      >
        {rendererSelection === "v4" ? (
          <PerformanceLocalV4Renderer
            audit={audit}
            campaignBannerEnabled={campaignBannerEnabled}
            composition={delivery.composition}
            page={delivery.page}
            previewedAt={previewedAt}
            readiness={readiness}
            reviewMode={reviewMode}
            v3Configuration={configuration}
          />
        ) : (
          <div data-v4-v3-control="true">
            <PerformanceLocalRenderer
              page={delivery.page}
              composition={delivery.composition}
              campaign={campaignBannerEnabled ? configuration.campaign : null}
              estimateForm={configuration.estimateForm}
              formSubmission={configuration.formSubmission}
              governedContact={configuration.governedContact}
              rendererIdentity={configuration.rendererIdentity}
              stickyActions={configuration.stickyActions}
              toggles={{
                ...configuration.toggles,
                campaignBanner: campaignBannerEnabled,
              }}
              previewedAt={previewedAt}
            />
          </div>
        )}
      </div>

      <section
        className="performanceLocalV4DiagnosticPanel"
        data-v4-diagnostic-panel="true"
        data-v4-post-site-clearance={
          audit.pageType === "city_service"
            ? "legacy-mobile-fixed-controls"
            : "standard"
        }
        aria-labelledby="performance-local-v4-diagnostic-heading"
      >
        <div className="performanceLocalV4DiagnosticHeading">
          <div>
            <p>Source-bound review</p>
            <h2 id="performance-local-v4-diagnostic-heading">V4 page-type diagnostics</h2>
          </div>
          <span data-tone={audit.layoutReady ? "ready" : "blocked"}>
            {audit.layoutReady ? "Layout ready" : "Layout blocked"}
          </span>
        </div>
        <dl className="performanceLocalV4DiagnosticGrid">
          <Diagnostic label="Website" value={audit.sourceIdentity.websiteId} />
          <Diagnostic label="Site Plan" value={audit.sourceIdentity.sitePlanId} />
          <Diagnostic label="Planned Page" value={plannedPage.id} />
          <Diagnostic label="Generated Page" value={delivery.page.id} />
          <Diagnostic label="Composition" value={`${delivery.composition.id}/v${delivery.composition.composition_version}`} />
          <Diagnostic label="Composition source" value={delivery.composition.source_hash} />
          <Diagnostic label="Raw page type" value={delivery.page.page_type} />
          <Diagnostic label="V4 layout" value={audit.layoutKey ?? "blocked"} />
          <Diagnostic label="Compatibility" value={audit.compatibilityIdentity} />
          <Diagnostic label="Review mode" value={reviewMode} />
          <Diagnostic label="Renderer view" value={rendererSelection} />
          <Diagnostic label="Source components" value={audit.sourceComponentCount} />
          <Diagnostic label="Consumed components" value={audit.consumedComponentCount} />
          <Diagnostic label="Placeholder count" value={placeholderCount} />
          <Diagnostic label="Campaign banner" value={campaignBannerEnabled && Boolean(configuration.campaign)} />
          <Diagnostic label="Sticky actions" value={stickyConfigured} />
          <Diagnostic label="Form provider" value={delivery.form_readiness.status} />
          <Diagnostic label="Form can submit" value={delivery.form_readiness.can_submit} />
          <Diagnostic label="Layout ready" value={audit.layoutReady} />
          <Diagnostic label="Media ready" value={readiness.mediaReady} />
          <Diagnostic label="QA ready" value={readiness.qaReady} />
          <Diagnostic label="Form ready" value={readiness.formReady} />
          <Diagnostic label="Activation ready" value={readiness.activationReady} />
          <Diagnostic label="Export ready" value={readiness.exportReady} />
          <Diagnostic label="Publication ready" value={readiness.publicationReady} />
          <Diagnostic label="Public-export eligible" value={false} />
        </dl>
        <div className="performanceLocalV4DiagnosticLists">
          <DiagnosticList label="Missing required regions" values={audit.missingRequiredRegionKeys} />
          <DiagnosticList label="Missing optional regions" values={audit.missingOptionalRegionKeys} />
          <DiagnosticList label="Unconsumed source instances" values={audit.unconsumedSourceInstanceKeys} />
          <DiagnosticList label="Duplicated source instances" values={audit.duplicatedSourceInstanceKeys} />
          <DiagnosticList label="Ownership mismatches" values={audit.ownershipMismatches} />
          <DiagnosticList label="Layout blockers" values={audit.blockers.map((blocker) => `${blocker.code}: ${blocker.message}`)} />
          <DiagnosticList label="Delivery blockers" values={delivery.blockers.map((blocker) => `${blocker.code}: ${blocker.reason}`)} />
        </div>
        {audit.manifest ? (
          <details className="performanceLocalV4Manifest">
            <summary>Page-type layout manifest</summary>
            <dl>
              <Diagnostic label="Manifest" value={`${audit.manifest.layoutKey}@${audit.manifest.layoutVersion}`} />
              <Diagnostic label="Supported page type" value={audit.manifest.supportedPageType} />
              <Diagnostic label="Required regions" value={audit.manifest.requiredSemanticRegions.join(", ")} />
              <Diagnostic label="Optional regions" value={audit.manifest.optionalSemanticRegions.join(", ") || "none"} />
              <Diagnostic label="Diagnostic identity" value={audit.manifest.diagnosticIdentity} />
            </dl>
          </details>
        ) : null}
        <p className="performanceLocalV4SafetyNote">
          <AlertTriangle aria-hidden="true" /> This source-only V4 review cannot activate, export, publish, or create a Theme selection.
        </p>
      </section>
    </div>
  );
}

function Diagnostic({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{formatDiagnostic(value)}</dd>
    </div>
  );
}

function DiagnosticList({ label, values }: { label: string; values: readonly unknown[] }) {
  return (
    <div>
      <h3>{label}</h3>
      {values.length ? (
        <ul>{values.map((value, index) => <li key={`${String(value)}-${index}`}>{String(value)}</li>)}</ul>
      ) : (
        <p>None</p>
      )}
    </div>
  );
}

function ReviewState({ message, error = false }: { message: string; error?: boolean }) {
  return (
    <main className="performanceLocalV4ReviewState" role={error ? "alert" : undefined}>
      <p>{error ? "V4 review error" : "Performance Local V4"}</p>
      <h1>{message}</h1>
      <Link to="/generated-pages"><ArrowLeft aria-hidden="true" /> Generated Pages</Link>
    </main>
  );
}

function exactV3DraftConfigurationId(
  preview: ThemeDraftPreviewRead,
  page: GeneratedPage,
): number | null {
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

function exactPlannedPage(
  sitePlan: SitePlanDetail,
  delivery: PerformanceLocalDeliveryRead,
): PlannedPage | null {
  if (
    sitePlan.id !== delivery.composition.site_plan_id ||
    sitePlan.website_id !== delivery.composition.website_id
  ) return null;
  const matches = sitePlan.planned_pages.filter((plannedPage) =>
    plannedPage.id === delivery.composition.planned_page_id &&
    plannedPage.site_plan_id === sitePlan.id &&
    plannedPage.website_id === sitePlan.website_id &&
    plannedPage.generated_page_id === delivery.page.id &&
    plannedPage.page_type === delivery.page.page_type,
  );
  return matches.length === 1 ? matches[0] : null;
}

function deliveryReadinessProjection(
  delivery: PerformanceLocalDeliveryRead,
): PerformanceLocalV4ReadinessProjection {
  const mediaReady = !delivery.blockers.some((blocker) => blocker.category === "media");
  const qaReady = delivery.page.qa_status === "ready" &&
    !delivery.blockers.some((blocker) => blocker.category === "qa");
  const formReady = delivery.form_readiness.status === "ready" &&
    delivery.form_readiness.can_submit === true;
  return Object.freeze({
    mediaReady,
    qaReady,
    formReady,
    activationReady: false,
    exportReady: false,
    publicationReady: false,
  });
}

function resolvedThemePresentation(
  delivery: PerformanceLocalDeliveryRead,
  viewportWidth: number,
): ThemePresentation | null {
  try {
    return themePresentation(
      delivery.composition.resolved_theme,
      delivery.composition.website_id,
      viewportWidth,
    );
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
  return typeof numeric === "number" && Number.isSafeInteger(numeric) && numeric > 0
    ? numeric
    : null;
}

function sameCanonicalJson(left: unknown, right: unknown): boolean {
  return JSON.stringify(canonicalJsonValue(left)) === JSON.stringify(canonicalJsonValue(right));
}

function canonicalJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalJsonValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalJsonValue(item)]),
    );
  }
  return value;
}

export default PerformanceLocalV4ReviewPage;
