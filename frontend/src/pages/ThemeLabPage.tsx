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
  performanceLocalViewport,
} from "../components/performanceLocalTheme";
import PerformanceLocalRenderer, {
  performanceLocalDiagnostics,
  type PerformanceLocalRuntimeToggles,
} from "../components/PerformanceLocalRenderer";
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
  stickyActionBar: true,
  trustStrip: true,
};

function ThemeLabPage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const requestKey = id ?? "missing";
  const [data, setData] = useState<ThemeLabData | null>(null);
  const [requestStateKey, setRequestStateKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adapter, setAdapter] = useState<AdapterKey>("performance-local");
  const [toggles, setToggles] = useState(INITIAL_TOGGLES);
  const loadGeneration = useRef(0);
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
  const diagnostics = performanceLocalDiagnostics(composition, toggles);
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
          <h1>{adapterMetadata.displayName}</h1>
          <dl>
            <div><dt>Key</dt><dd>{adapterMetadata.key}</dd></div>
            <div><dt>Version</dt><dd>{adapterMetadata.version}</dd></div>
            <div><dt>Status</dt><dd>{adapterMetadata.status}</dd></div>
            <div><dt>Breakpoint</dt><dd>{breakpoint}</dd></div>
          </dl>
        </div>
        {adapter === "performance-local" ? (
          <fieldset>
            <legend>Client-only component toggles</legend>
            <RuntimeToggle
              label="Campaign banner"
              checked={toggles.campaignBanner}
              disabled
              note="Unavailable until approved dates and terms are configured."
              onChange={(checked) => setToggle(setToggles, "campaignBanner", checked)}
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
            <div><dt>Enabled components</dt><dd>{adapter === "performance-local" ? diagnostics.enabledComponents.join(", ") : "Authoritative diagnostic composition"}</dd></div>
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
      </aside> : null}

      <section
        className="themeLabCanvas"
        aria-label={`${adapterMetadata.displayName} page preview`}
        data-atlas-theme-family={adapterMetadata.key}
        data-atlas-theme-family-version={adapterMetadata.version}
        data-atlas-theme-family-status={adapterMetadata.status}
        data-atlas-preview-breakpoint={breakpoint}
        style={governedPresentation.style}
        {...governedPresentation.attributes}
      >
        {adapter === "performance-local" ? (
          <PerformanceLocalRenderer
            brandAccent={runtimeBrandAccent}
            page={page}
            composition={composition}
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
