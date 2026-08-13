import { AlertTriangle, ArrowLeft, FlaskConical } from "lucide-react";
import {
  type Dispatch,
  type SetStateAction,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { apiRequest } from "../api";
import {
  ATLAS_DIAGNOSTIC_THEME,
  PERFORMANCE_LOCAL_THEME,
  performanceLocalOptionalConfiguration,
  performanceLocalViewport,
} from "../components/performanceLocalTheme";
import PerformanceLocalRenderer, {
  performanceLocalDiagnostics,
  type PerformanceLocalCampaign,
  type PerformanceLocalRuntimeToggles,
} from "../components/PerformanceLocalRenderer";
import { performanceLocalActivationReadiness } from "../components/performanceLocalReadiness";
import {
  installIdentityHeadTags,
  removeIdentityHeadTags,
} from "../components/WebsiteIdentityPresentation";
import { themePresentation } from "../components/themeAdapter";
import {
  compositionValidationError,
  renderComponent,
} from "./GeneratedPagePreview";
import type { GeneratedPage, PageComposition } from "../types";

type AdapterKey = "atlas-diagnostic" | "performance-local";

type ThemeLabData = {
  composition: PageComposition;
  page: GeneratedPage;
  requestKey: string;
};

const INITIAL_TOGGLES: PerformanceLocalRuntimeToggles = {
  campaignBanner: false,
  compactEstimateForm: true,
  finalCta: true,
  headerEstimateCta: true,
  stickyActionBar: true,
  trustStrip: true,
};

const RUNTIME_PREVIEW_CAMPAIGN_LABEL = "Request a Drywood Termite Tenting Estimate";

function ThemeLabPage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const requestKey = id ?? "missing";
  const [data, setData] = useState<ThemeLabData | null>(null);
  const [requestStateKey, setRequestStateKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adapter, setAdapter] = useState<AdapterKey>("performance-local");
  const [toggles, setToggles] = useState(() => previewToggles(searchParams));
  const [diagnosticOverlays, setDiagnosticOverlays] = useState(
    () => searchParams.get("diagnostics") === "1",
  );
  const [galleryAccess, setGalleryAccess] = useState(
    () => searchParams.get("gallery") === "1",
  );
  const loadGeneration = useRef(0);
  const previewSessionTime = useRef(new Date()).current;
  const viewportWidth = useViewportWidth();

  useLayoutEffect(() => {
    removeIdentityHeadTags(document);
    return () => removeIdentityHeadTags(document);
  }, [requestKey]);

  useEffect(() => {
    const generation = ++loadGeneration.current;
    let cancelled = false;
    const isCurrent = () => !cancelled && generation === loadGeneration.current;
    setRequestStateKey(requestKey);
    setLoading(true);
    setError(null);
    setData(null);
    document.title = "Performance Local Theme Lab | Project Atlas";
    removeIdentityHeadTags(document);

    async function loadThemeLab() {
      const pageId = positiveInteger(id);
      if (!pageId) {
        if (isCurrent()) {
          setError("Invalid generated page ID.");
          setLoading(false);
        }
        return;
      }
      try {
        const [page, composition] = await Promise.all([
          apiRequest<GeneratedPage>(`/api/generated-pages/${pageId}`),
          apiRequest<PageComposition>(`/api/site-plans/generated-pages/${pageId}/composition`),
        ]);
        const validationError = themeLabValidationError(page, composition);
        if (validationError) throw new Error(validationError);
        if (!isCurrent()) return;
        setData({ page, composition, requestKey });
        document.title = `${page.page_title} | Performance Local Theme Lab`;
      } catch (value) {
        if (!isCurrent()) return;
        setError(value instanceof Error ? value.message : "Unable to load Theme Lab.");
      } finally {
        if (isCurrent()) setLoading(false);
      }
    }

    void loadThemeLab();
    return () => {
      cancelled = true;
      if (generation === loadGeneration.current) loadGeneration.current += 1;
      removeIdentityHeadTags(document);
      document.title = "Project Atlas";
    };
  }, [requestKey]);

  const currentData =
    requestStateKey === requestKey && data?.requestKey === requestKey ? data : null;

  useEffect(() => {
    if (!currentData) return;
    const header = currentData.composition.effective_components.find(
      (item) => item.component_key === "website_header",
    );
    return installIdentityHeadTags(document, asRecord(header?.resolved_data.identity_assets));
  }, [currentData]);

  if (requestStateKey !== requestKey || loading) {
    return <ThemeLabState message="Loading current semantic composition..." />;
  }
  if (error || !currentData) {
    return <ThemeLabState message={error ?? "Theme Lab is unavailable."} error />;
  }

  const { composition, page } = currentData;
  const governedPresentation = themePresentation(
    composition.resolved_theme,
    composition.website_id,
    viewportWidth,
  );
  const adapterTheme = adapter === "performance-local"
    ? PERFORMANCE_LOCAL_THEME
    : ATLAS_DIAGNOSTIC_THEME;
  const adapterMetadata = catalogMetadata(adapterTheme);
  const breakpoint = adapter === "performance-local"
    ? performanceLocalViewport(viewportWidth)
    : governedPresentation.attributes["data-atlas-theme-viewport"];
  const campaignPageId = positiveInteger(searchParams.get("campaignPageId"));
  const runtimeCampaign = campaignPageId === page.id
    ? performanceLocalPreviewCampaign(composition.website_id, page.id, previewSessionTime)
    : null;
  const effectiveCampaign = toggles.campaignBanner && toggles.finalCta && toggles.compactEstimateForm
    ? runtimeCampaign
    : null;
  const diagnostics = performanceLocalDiagnostics(composition, toggles, {
    campaignVisible: Boolean(effectiveCampaign),
  });
  const readiness = performanceLocalActivationReadiness({
    previewImplementationPresent: true,
    observedThemeFamilyVersion: PERFORMANCE_LOCAL_THEME.version,
  });
  const governedContacts = themeLabGovernedContacts(composition);
  const runtimeBrandAccent = searchParams.get("brandAccent");
  const reviewMode = searchParams.get("review") === "1";

  return (
    <div className="themeLab" data-theme-lab="local-only" data-review-mode={reviewMode ? "true" : "false"}>
      {!reviewMode ? <header className="themeLabToolbar">
        <div className="themeLabToolbarTitle">
          <Link to={`/generated-pages/${page.id}/preview`} className="themeLabBackLink">
            <ArrowLeft size={16} aria-hidden="true" /> Diagnostic preview
          </Link>
          <span><FlaskConical size={17} aria-hidden="true" /> Local Theme Lab</span>
          <strong>Not selected or published</strong>
        </div>
        <div className="themeLabAdapterSelector" role="group" aria-label="Preview adapter">
          <button
            type="button"
            className={adapter === "atlas-diagnostic" ? "active" : ""}
            aria-pressed={adapter === "atlas-diagnostic"}
            onClick={() => setAdapter("atlas-diagnostic")}
          >
            Diagnostic
          </button>
          <button
            type="button"
            className={adapter === "performance-local" ? "active" : ""}
            aria-pressed={adapter === "performance-local"}
            onClick={() => setAdapter("performance-local")}
          >
            Performance Local
          </button>
        </div>
      </header> : null}

      {!reviewMode ? <aside className="themeLabControls" aria-label="Runtime preview controls">
        <div>
          <p className="themeLabEyebrow">Source-only preview adapter</p>
          <h2>{adapterMetadata.displayName}</h2>
          <dl>
            <div><dt>Key</dt><dd>{adapterMetadata.key}</dd></div>
            <div><dt>Version</dt><dd>{adapterMetadata.version}</dd></div>
            <div><dt>Status</dt><dd>{adapterMetadata.status}</dd></div>
            <div><dt>Production ready</dt><dd>{adapter === "performance-local" ? "No" : "Not applicable"}</dd></div>
            <div><dt>Breakpoint</dt><dd>{breakpoint}</dd></div>
          </dl>
        </div>
        {adapter === "performance-local" ? (
          <fieldset>
            <legend>Client-only component toggles</legend>
            <RuntimeToggle
              label="Campaign banner"
              checked={toggles.campaignBanner}
              note={runtimeCampaign
                ? "Runtime-only page-scoped preview; no price, urgency, or production offer."
                : "Fails closed until the current Page identity is supplied through runtime-only preview scope."}
              onChange={(checked) => setToggle(setToggles, "campaignBanner", checked)}
            />
            <RuntimeToggle
              label="Header estimate CTA"
              checked={toggles.headerEstimateCta !== false}
              note="Visible only while the safe local estimate destination exists."
              onChange={(checked) => setToggle(setToggles, "headerEstimateCta", checked)}
            />
            <RuntimeToggle
              label="Trust strip"
              checked={toggles.trustStrip}
              onChange={(checked) => setToggle(setToggles, "trustStrip", checked)}
            />
            <RuntimeToggle
              label="Final CTA section"
              checked={toggles.finalCta}
              onChange={(checked) => setToggle(setToggles, "finalCta", checked)}
            />
            <RuntimeToggle
              label="Compact estimate form"
              checked={toggles.compactEstimateForm}
              note="Preview only; never submitted or saved."
              onChange={(checked) => setToggle(setToggles, "compactEstimateForm", checked)}
            />
            <RuntimeToggle
              label="Mobile sticky actions"
              checked={toggles.stickyActionBar}
              onChange={(checked) => setToggle(setToggles, "stickyActionBar", checked)}
            />
            <RuntimeToggle
              label="Optional component gallery"
              checked={galleryAccess}
              note="Reveals a separate demo-only local route; never enters Page content."
              onChange={setGalleryAccess}
            />
            <RuntimeToggle
              label="Diagnostic overlays"
              checked={diagnosticOverlays}
              note="Local visual labels only; no source or Atlas state change."
              onChange={setDiagnosticOverlays}
            />
            {galleryAccess ? (
              <Link className="previewButton previewButtonSecondary" to="/theme-lab/performance-local/components">
                Open demo-only component gallery
              </Link>
            ) : null}
          </fieldset>
        ) : null}
        <details className="themeLabDiagnostics" open>
          <summary>Adapter diagnostics</summary>
          <dl>
            <div><dt>Generated Page</dt><dd>{page.id}</dd></div>
            <div><dt>Website</dt><dd>{composition.website_id}</dd></div>
            <div><dt>Site Plan</dt><dd>{composition.site_plan_id}</dd></div>
            <div><dt>Planned Page</dt><dd>{composition.planned_page_id}</dd></div>
            <div><dt>Composition</dt><dd>{composition.id} / v{composition.composition_version}</dd></div>
            <div><dt>Source hash</dt><dd><code>{composition.source_hash}</code></dd></div>
            <div><dt>QA identity</dt><dd>{page.qa_result?.qa_result_id ? `QA ${page.qa_result.qa_result_id}` : "Unavailable"}</dd></div>
            <div><dt>QA readiness</dt><dd>{page.qa_result?.readiness_status ?? page.qa_status}</dd></div>
            <div><dt>Enabled components</dt><dd>{adapter === "performance-local" ? diagnostics.enabledComponents.join(", ") : "Authoritative diagnostic composition"}</dd></div>
            <div><dt>Disabled components</dt><dd>{adapter === "performance-local" ? diagnostics.disabledComponents.join(", ") : "Not applicable"}</dd></div>
            <div><dt>Fail-closed components</dt><dd>{adapter === "performance-local" ? diagnostics.failClosedComponents.join(", ") || "None" : "Not applicable"}</dd></div>
            <div><dt>Governed contacts</dt><dd>{governedContacts.join(", ") || "No current contact destination"}</dd></div>
            <div><dt>Effective variants</dt><dd>{adapter === "performance-local" ? Object.entries(diagnostics.effectiveVariants).map(([key, value]) => `${key}: ${value}`).join(", ") : "Raw semantic component variants"}</dd></div>
            <div><dt>Warnings</dt><dd>{adapter === "performance-local" ? diagnostics.warnings.length : 0}</dd></div>
          </dl>
          {diagnostics.warnings.length && adapter === "performance-local" ? (
            <ul>{diagnostics.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          ) : null}
        </details>
        <details className="themeLabTokens">
          <summary>Effective governed design tokens</summary>
          <pre>{JSON.stringify(composition.resolved_theme.effective_tokens, null, 2)}</pre>
        </details>
        {adapter === "performance-local" ? (
          <section className="themeLabReadiness" aria-labelledby="performance-local-activation-readiness">
            <p className="themeLabEyebrow">Diagnostic only</p>
            <h2 id="performance-local-activation-readiness">Activation readiness</h2>
            <p role="status"><strong>Blocked — Performance Local is not activated and is not production-ready.</strong></p>
            <dl>
              <div><dt>Theme family</dt><dd>{readiness.themeKey} v{readiness.themeFamilyVersion}</dd></div>
              <div><dt>Lifecycle</dt><dd>{readiness.lifecycle}</dd></div>
              <div><dt>Incomplete inputs</dt><dd>{readiness.incompleteCount}</dd></div>
              <div><dt>Can activate</dt><dd>No</dd></div>
            </dl>
            <ul>
              {readiness.items.map((item) => (
                <li key={item.key} data-readiness-status={item.status}>
                  <strong>{item.label}: incomplete</strong>
                  <span>{item.reason}</span>
                </li>
              ))}
            </ul>
            <p>This read-only panel has no mutation control and cannot activate, publish, or deploy a Theme.</p>
          </section>
        ) : null}
      </aside> : null}

      <section
        className="themeLabCanvas"
        aria-label={`${adapterMetadata.displayName} page preview`}
        data-atlas-theme-family={adapterMetadata.key}
        data-atlas-theme-family-version={adapterMetadata.version}
        data-atlas-theme-family-status={adapterMetadata.status}
        data-atlas-preview-breakpoint={breakpoint}
        data-diagnostic-overlays={diagnosticOverlays ? "visible" : "hidden"}
        style={governedPresentation.style}
        {...governedPresentation.attributes}
      >
        {adapter === "performance-local" ? (
          <PerformanceLocalRenderer
            brandAccent={runtimeBrandAccent}
            campaign={effectiveCampaign}
            page={page}
            composition={composition}
            previewedAt={previewSessionTime}
            toggles={toggles}
          />
        ) : (
          <DiagnosticComposition composition={composition} />
        )}
      </section>
    </div>
  );
}

function DiagnosticComposition({ composition }: { composition: PageComposition }) {
  const components = composition.effective_components;
  return (
    <div className="servicePreview atlasBasePresentation" data-atlas-adapter="atlas-diagnostic">
      {components.filter((component) => component.region === "header").map(renderComponent)}
      <main id="main-content">
        {components.filter((component) => component.region === "main").map(renderComponent)}
      </main>
      <footer className="previewFooter">
        {components.filter((component) => component.region === "footer").map(renderComponent)}
      </footer>
    </div>
  );
}

function RuntimeToggle({
  checked,
  disabled = false,
  label,
  note,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  note?: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="themeLabToggle">
      <span>
        <strong>{label}</strong>
        {note ? <small>{note}</small> : null}
      </span>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.currentTarget.checked)}
      />
    </label>
  );
}

function ThemeLabState({ message, error = false }: { message: string; error?: boolean }) {
  return (
    <main className="previewState themeLabState">
      <div>
        {error ? <AlertTriangle aria-hidden="true" /> : <FlaskConical aria-hidden="true" />}
        <p className="previewSectionLabel">{error ? "Theme Lab unavailable" : "Local Theme Lab"}</p>
        <h1>{message}</h1>
        <Link to="/generated-pages" className="previewButton previewButtonPrimary">
          <ArrowLeft size={18} aria-hidden="true" /> Back to Generated Pages
        </Link>
      </div>
    </main>
  );
}

function themeLabValidationError(page: GeneratedPage, composition: PageComposition): string | null {
  const compositionError = compositionValidationError(composition);
  if (compositionError) return compositionError;
  if (page.id !== composition.generated_page_id) {
    return "The semantic composition does not belong to this Generated Page.";
  }
  if (!page.website_id || page.website_id !== composition.website_id) {
    return "The Generated Page and semantic composition cross the Website ownership boundary.";
  }
  if (!page.draft_content) {
    return "Generate a structured draft before opening Theme Lab.";
  }
  return null;
}

function catalogMetadata(value: unknown): {
  displayName: string;
  key: string;
  status: string;
  version: string;
} {
  const record = asRecord(value);
  return {
    displayName: cleanText(record.displayName) || cleanText(record.display_name) || cleanText(record.name) || "Theme adapter",
    key: cleanText(record.key) || cleanText(record.themeKey) || cleanText(record.theme_key) || "unknown",
    status: cleanText(record.status) || cleanText(record.lifecycleStatus) || cleanText(record.lifecycle_status) || "internal",
    version: cleanText(record.version) || "1",
  };
}

function setToggle(
  setter: Dispatch<SetStateAction<PerformanceLocalRuntimeToggles>>,
  key: keyof PerformanceLocalRuntimeToggles,
  checked: boolean,
) {
  setter((current) => ({ ...current, [key]: checked }));
}

function previewToggles(searchParams: URLSearchParams): PerformanceLocalRuntimeToggles {
  return {
    ...INITIAL_TOGGLES,
    campaignBanner: searchParams.get("campaign") === "1",
    compactEstimateForm: searchParams.get("form") !== "0",
    finalCta: searchParams.get("final") !== "0",
    headerEstimateCta: searchParams.get("headerEstimate") !== "0",
    stickyActionBar: searchParams.get("sticky") !== "0",
    trustStrip: searchParams.get("trust") !== "0",
  };
}

function performanceLocalPreviewCampaign(
  websiteId: number,
  pageId: number,
  previewedAt: Date,
): PerformanceLocalCampaign {
  const startDate = new Date(previewedAt.getTime() - 60 * 60 * 1000).toISOString();
  const endDate = new Date(previewedAt.getTime() + 24 * 60 * 60 * 1000).toISOString();
  return {
    ...performanceLocalOptionalConfiguration(
      "campaign_banner",
      websiteId,
      "Estimate campaign preview",
      {
        pageOverrideId: pageId,
        approvalIdentity: "operator-authorized-local-theme-lab-preview",
        campaignLabel: RUNTIME_PREVIEW_CAMPAIGN_LABEL,
        ctaDestination: "#estimate",
        ctaLabel: "Request estimate",
        endDate,
        startDate,
        termsReference: "Performance Local v2 Theme Lab preview only; no production offer or price.",
      },
    ),
    approvalIdentity: "operator-authorized-local-theme-lab-preview",
    campaignLabel: RUNTIME_PREVIEW_CAMPAIGN_LABEL,
    ctaDestination: "#estimate",
    ctaLabel: "Request estimate",
    enabled: true,
    endDate,
    startDate,
    termsReference: "Performance Local v2 Theme Lab preview only; no production offer or price.",
    websiteId,
  };
}

function themeLabGovernedContacts(composition: PageComposition): string[] {
  const header = composition.effective_components.find(
    (component) => component.component_key === "website_header",
  );
  const data = asRecord(header?.resolved_data);
  const contacts = [cleanText(data.phone), cleanText(data.email)].filter(Boolean);
  return [...new Set(contacts)];
}

function useViewportWidth() {
  const [width, setWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    const update = () => setWidth(window.innerWidth);
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return width;
}

function positiveInteger(value: unknown): number | null {
  const numeric = typeof value === "string" && value.trim() ? Number(value) : value;
  return typeof numeric === "number" && Number.isInteger(numeric) && numeric > 0 ? numeric : null;
}

function cleanText(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value).trim() : "";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export default ThemeLabPage;
