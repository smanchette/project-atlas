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
  PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS,
  PERFORMANCE_LOCAL_V2_SOURCE_COMMIT,
  performanceLocalOptionalConfiguration,
  performanceLocalViewport,
} from "../components/performanceLocalTheme";
import PerformanceLocalRenderer, {
  performanceLocalDiagnostics,
  performanceLocalFormDomId,
  type PerformanceLocalCampaign,
  type PerformanceLocalEstimateField,
  type PerformanceLocalEstimateFormConfiguration,
  type PerformanceLocalGovernedContact,
  type PerformanceLocalRuntimeToggles,
  type PerformanceLocalStickyActionConfiguration,
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
import type {
  GeneratedPage,
  PageComposition,
  ThemeDraftPreviewRead,
  WebsiteThemeComponentConfigurationRead,
} from "../types";

type AdapterKey = "atlas-diagnostic" | "performance-local";

type ThemeLabData = {
  composition: PageComposition;
  draftPreview: ThemeDraftPreviewRead;
  page: GeneratedPage;
  requestKey: string;
};

const INITIAL_TOGGLES: PerformanceLocalRuntimeToggles = {
  campaignBanner: true,
  compactEstimateForm: true,
  estimateAction: true,
  finalCta: true,
  headerEstimateCta: true,
  phoneAction: true,
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
        const page = await apiRequest<GeneratedPage>(`/api/generated-pages/${pageId}`);
        const [composition, draftPreview] = await Promise.all([
          apiRequest<PageComposition>(`/api/site-plans/generated-pages/${pageId}/composition`),
          apiRequest<ThemeDraftPreviewRead>(
            `/api/websites/${page.website_id}/theme-configurations/draft-preview?family_key=performance-local&family_version=2&page_id=${pageId}`,
          ),
        ]);
        const validationError = themeLabValidationError(page, composition, draftPreview);
        if (validationError) throw new Error(validationError);
        if (!isCurrent()) return;
        setData({ page, composition, draftPreview, requestKey });
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

  const { composition, draftPreview, page } = currentData;
  const durableConfiguration = performanceLocalDraftConfiguration(draftPreview);
  if (!durableConfiguration) {
    return <ThemeLabState message="Durable Performance Local configuration is incomplete or unsafe." error />;
  }
  const governedPresentation = themePresentation(
    composition.resolved_theme,
    composition.website_id,
    viewportWidth,
  );
  const adapterMetadata = adapter === "performance-local"
    ? {
        displayName: draftPreview.theme_family.display_name,
        key: draftPreview.theme_family.family_key,
        status: draftPreview.theme_version.lifecycle_status,
        version: String(draftPreview.theme_version.version),
      }
    : catalogMetadata(ATLAS_DIAGNOSTIC_THEME);
  const breakpoint = adapter === "performance-local"
    ? performanceLocalViewport(viewportWidth)
    : governedPresentation.attributes["data-atlas-theme-viewport"];
  const estimateDestination = toggles.estimateAction !== false && toggles.compactEstimateForm && toggles.finalCta
    ? `#${performanceLocalFormDomId(durableConfiguration.estimateForm.componentConfigurationId)}`
    : null;
  const phoneDestination = toggles.phoneAction === false
    ? null
    : durableConfiguration.governedContact?.callDestination ?? null;
  const diagnostics = performanceLocalDiagnostics(composition, toggles, {
    campaignVisible: Boolean(toggles.campaignBanner && estimateDestination),
    estimateDestination,
    phoneDestination,
  });
  const readiness = draftPreview.readiness;
  const governedContacts = [
    draftPreview.governed_actions.phone_display,
    draftPreview.governed_actions.call_destination,
  ].filter((value): value is string => Boolean(value));
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
          <strong>{draftPreview.preview_label}</strong>
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

      <div className="themeLabDraftBanner" role="status" data-draft-active="false">
        <strong>{draftPreview.preview_label}</strong>
        <span>Read-only durable Website draft · export ineligible · provider disabled</span>
      </div>

      {!reviewMode ? <aside className="themeLabControls" aria-label="Runtime preview controls">
        <div>
          <p className="themeLabEyebrow">Durable inactive draft adapter</p>
          <h2>{adapterMetadata.displayName}</h2>
          <dl>
            <div><dt>Key</dt><dd>{adapterMetadata.key}</dd></div>
            <div><dt>Version</dt><dd>{adapterMetadata.version}</dd></div>
            <div><dt>Status</dt><dd>{adapterMetadata.status}</dd></div>
            <div><dt>Production ready</dt><dd>{adapter === "performance-local" ? formatBoolean(draftPreview.theme_version.production_ready) : "Not applicable"}</dd></div>
            <div><dt>Breakpoint</dt><dd>{breakpoint}</dd></div>
            {adapter === "performance-local" ? <div><dt>Family ID</dt><dd>{draftPreview.theme_family.id}</dd></div> : null}
            {adapter === "performance-local" ? <div><dt>Version ID</dt><dd>{draftPreview.theme_version.id}</dd></div> : null}
            {adapter === "performance-local" ? <div><dt>Website config</dt><dd>{draftPreview.website_configuration.id} / v{draftPreview.website_configuration.version}</dd></div> : null}
            {adapter === "performance-local" ? <div><dt>Draft lifecycle</dt><dd>{draftPreview.website_configuration.lifecycle_status}</dd></div> : null}
          </dl>
        </div>
        {adapter === "performance-local" ? (
          <fieldset>
            <legend>Client-only component toggles</legend>
            <RuntimeToggle
              label="Evergreen conversion banner"
              checked={toggles.campaignBanner}
              note="Suppresses the durable draft locally; it never edits the component configuration."
              onChange={(checked) => setToggle(setToggles, "campaignBanner", checked)}
            />
            <RuntimeToggle
              label="Governed Call actions"
              checked={toggles.phoneAction !== false}
              note="Local fail-closed preview of the missing-phone state."
              onChange={(checked) => setToggle(setToggles, "phoneAction", checked)}
            />
            <RuntimeToggle
              label="Configured Estimate actions"
              checked={toggles.estimateAction !== false}
              note="Local fail-closed preview of a missing exact form destination."
              onChange={(checked) => setToggle(setToggles, "estimateAction", checked)}
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
          <details className="themeLabDurableMetadata" open>
            <summary>Durable draft identity</summary>
            <dl>
              <div><dt>Theme Family</dt><dd>{draftPreview.theme_family.id} · {draftPreview.theme_family.family_key}</dd></div>
              <div><dt>Family lifecycle</dt><dd>{draftPreview.theme_family.lifecycle_status}</dd></div>
              <div><dt>Family fingerprint</dt><dd><code>{draftPreview.theme_family.integrity_fingerprint}</code></dd></div>
              <div><dt>Theme Version</dt><dd>{draftPreview.theme_version.id} · v{draftPreview.theme_version.version}</dd></div>
              <div><dt>Version lifecycle</dt><dd>{draftPreview.theme_version.lifecycle_status}</dd></div>
              <div><dt>Production ready</dt><dd>{formatBoolean(draftPreview.theme_version.production_ready)}</dd></div>
              <div><dt>Source commit</dt><dd><code>{draftPreview.theme_version.source_commit}</code></dd></div>
              <div><dt>Compatibility</dt><dd>{draftPreview.theme_version.compatibility_identity}</dd></div>
              <div><dt>Version fingerprint</dt><dd><code>{draftPreview.theme_version.integrity_fingerprint}</code></dd></div>
              <div><dt>Website configuration</dt><dd>{draftPreview.website_configuration.id} · v{draftPreview.website_configuration.version}</dd></div>
              <div><dt>Configuration lifecycle</dt><dd>{draftPreview.website_configuration.lifecycle_status}</dd></div>
              <div><dt>Configuration fingerprint</dt><dd><code>{draftPreview.website_configuration.integrity_fingerprint}</code></dd></div>
              <div><dt>Banner intent</dt><dd>{durableConfiguration.campaign?.intent ?? "disabled or outside effective window"}</dd></div>
              <div><dt>Sticky actions</dt><dd>{durableConfiguration.stickyActions.enabled ? "configured · inactive draft" : "disabled"}</dd></div>
              <div><dt>Form state</dt><dd>{draftPreview.provider_state.submission_state}</dd></div>
              <div><dt>Provider</dt><dd>{draftPreview.provider_state.provider_key ?? "not configured"}</dd></div>
              <div><dt>Privacy</dt><dd>{themeDraftPrivacyStatus(draftPreview)}</dd></div>
              <div><dt>Activation</dt><dd>{draftPreview.activation_status}</dd></div>
              <div><dt>Publication</dt><dd>{draftPreview.publication_status}</dd></div>
              <div><dt>Deployment</dt><dd>{draftPreview.deployment_status}</dd></div>
              <div><dt>Public export</dt><dd>{draftPreview.export_eligible ? "eligible" : "ineligible"}</dd></div>
            </dl>
            <h3>Component configuration identities</h3>
            <ul className="themeLabIdentityList">
              {draftPreview.components.map((component) => (
                <li key={component.id}>
                  <strong>{component.component_key}</strong>
                  <span>ID {component.id} · revision {component.revision} · {component.scope_type} · {component.lifecycle_status}</span>
                  <span>Target ID {component.destination_component_configuration_id ?? "none"}</span>
                  <code>{component.integrity_fingerprint}</code>
                </li>
              ))}
            </ul>
            <h3>Audit identities</h3>
            <ul className="themeLabIdentityList">
              {draftPreview.audit_history.map((audit) => (
                <li key={audit.id}>
                  <strong>Audit {audit.id} · {audit.action_type}</strong>
                  <span>{audit.actor} · {themeAuditTarget(audit)}</span>
                  <code>{audit.snapshot_hash}</code>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        {adapter === "performance-local" ? (
          <section className="themeLabReadiness" aria-labelledby="performance-local-activation-readiness">
            <p className="themeLabEyebrow">Diagnostic only</p>
            <h2 id="performance-local-activation-readiness">Activation readiness</h2>
            <p role="status"><strong>Blocked — Performance Local is not activated and is not production-ready.</strong></p>
            <dl>
              <div><dt>Theme family</dt><dd>{draftPreview.theme_family.family_key} v{draftPreview.theme_version.version}</dd></div>
              <div><dt>Lifecycle</dt><dd>{draftPreview.theme_version.lifecycle_status}</dd></div>
              <div><dt>Incomplete inputs</dt><dd>{readiness.incomplete_items.length}</dd></div>
              <div><dt>Can activate</dt><dd>{formatBoolean(readiness.can_activate)}</dd></div>
              <div><dt>Can publish</dt><dd>{formatBoolean(readiness.can_publish)}</dd></div>
              <div><dt>Can deploy</dt><dd>{formatBoolean(readiness.can_deploy)}</dd></div>
            </dl>
            <ul>
              {readiness.incomplete_items.map((item) => (
                <li key={item.key} data-readiness-status="incomplete">
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
            campaign={durableConfiguration.campaign}
            page={page}
            composition={composition}
            estimateForm={durableConfiguration.estimateForm}
            governedContact={durableConfiguration.governedContact}
            previewedAt={previewSessionTime}
            stickyActions={durableConfiguration.stickyActions}
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

function themeLabValidationError(
  page: GeneratedPage,
  composition: PageComposition,
  draftPreview: ThemeDraftPreviewRead,
): string | null {
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
  if (
    draftPreview.preview_label !== "DRAFT PREVIEW — NOT ACTIVE" ||
    draftPreview.theme_family.family_key !== "performance-local" ||
    draftPreview.theme_version.version !== 2 ||
    draftPreview.theme_version.theme_family_id !== draftPreview.theme_family.id ||
    draftPreview.theme_version.lifecycle_status !== "preview_candidate" ||
    draftPreview.theme_version.production_ready !== false ||
    draftPreview.website_configuration.website_id !== composition.website_id ||
    draftPreview.website_configuration.theme_family_version_id !== draftPreview.theme_version.id ||
    draftPreview.website_configuration.lifecycle_status !== "draft" ||
    draftPreview.website_configuration.materialized_theme_id !== null ||
    draftPreview.website_configuration.website_theme_selection_id !== null ||
    draftPreview.requested_generated_page_id !== page.id
  ) {
    return "The durable Theme draft identity is incompatible, active, or crosses its Website or Page boundary.";
  }
  if (
    draftPreview.export_eligible !== false ||
    draftPreview.privacy_status !== "blocked_pending_privacy_configuration" ||
    draftPreview.activation_status !== "blocked" ||
    draftPreview.publication_status !== "blocked" ||
    draftPreview.deployment_status !== "blocked" ||
    draftPreview.readiness.can_activate !== false ||
    draftPreview.readiness.can_publish !== false ||
    draftPreview.readiness.can_deploy !== false ||
    draftPreview.provider_state.submission_state !== "disabled_pending_provider_configuration" ||
    draftPreview.provider_state.provider_key !== null ||
    draftPreview.provider_state.destination !== null ||
    draftPreview.provider_state.can_submit !== false ||
    draftPreview.provider_state.collects_data !== false
  ) {
    return "The durable Theme draft is not safely blocked from activation, export, or form submission.";
  }
  if (
    !canonicalFingerprint(draftPreview.theme_family.integrity_fingerprint) ||
    !canonicalFingerprint(draftPreview.theme_version.integrity_fingerprint) ||
    !canonicalFingerprint(draftPreview.website_configuration.integrity_fingerprint) ||
    draftPreview.components.some((component) =>
      component.website_id !== composition.website_id ||
      component.website_theme_configuration_id !== draftPreview.website_configuration.id ||
      component.theme_family_version_id !== draftPreview.theme_version.id ||
      !canonicalFingerprint(component.integrity_fingerprint)
    ) ||
    draftPreview.audit_history.some((audit) => !canonicalFingerprint(audit.snapshot_hash))
  ) {
    return "Durable Theme draft fingerprints or ownership identities are invalid.";
  }
  if (!durableThemeContractIdentity(draftPreview)) {
    return "The durable Theme Version or component metadata does not match the exact source contract.";
  }
  if (!performanceLocalDraftConfiguration(draftPreview)) {
    return "The exact banner, sticky-action, governed-contact, or compact-form contract is incomplete.";
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
    campaignBanner: searchParams.get("campaign") !== "0",
    compactEstimateForm: searchParams.get("form") !== "0",
    estimateAction: searchParams.get("estimate") !== "0",
    finalCta: searchParams.get("final") !== "0",
    headerEstimateCta: searchParams.get("headerEstimate") !== "0",
    phoneAction: searchParams.get("phone") !== "0",
    stickyActionBar: searchParams.get("sticky") !== "0",
    trustStrip: searchParams.get("trust") !== "0",
  };
}

type DurablePerformanceLocalConfiguration = Readonly<{
  campaign: PerformanceLocalCampaign | null;
  estimateForm: PerformanceLocalEstimateFormConfiguration;
  governedContact: PerformanceLocalGovernedContact | null;
  stickyActions: PerformanceLocalStickyActionConfiguration;
}>;

export function performanceLocalDraftConfiguration(
  preview: ThemeDraftPreviewRead,
): DurablePerformanceLocalConfiguration | null {
  if (!durableThemeContractIdentity(preview)) return null;
  const banners = preview.components.filter(
    (component) => component.component_key === "campaign_banner",
  );
  if (banners.length > 1) return null;
  const banner = banners[0] ?? null;
  const sticky = exactComponent(preview.components, "sticky_mobile_action_bar");
  const form = exactComponent(preview.components, "compact_estimate_form");
  if (!sticky || !form || !sticky.enabled || !form.enabled) return null;
  if (
    sticky.destination_component_configuration_id !== form.id ||
    preview.governed_actions.estimate_destination_component_configuration_id !== form.id
  ) return null;

  const stickyPayload = sticky.configuration_payload;
  const formPayload = form.configuration_payload;
  const stickyEstimateLabel = exactText(stickyPayload.estimate_label);
  const callLabel = exactText(stickyPayload.call_label);
  if (!stickyEstimateLabel || !callLabel) return null;
  if (stickyPayload.call_source !== "governed_website_identity") return null;
  if (
    preview.governed_actions.call_label !== callLabel ||
    preview.governed_actions.estimate_label !== stickyEstimateLabel ||
    preview.governed_actions.desktop_header_actions_enabled !== true ||
    preview.governed_actions.mobile_sticky_actions_enabled !== true ||
    preview.governed_actions.desktop_header_estimate_destination_component_configuration_id !== form.id ||
    preview.governed_actions.mobile_sticky_estimate_destination_component_configuration_id !== form.id
  ) return null;
  for (const requirement of [
    "desktop_sticky_header",
    "mobile_sticky_bottom",
    "hide_while_hero_actions_visible",
    "hide_while_navigation_open",
    "protect_form_focus",
    "safe_area_support",
    "prevent_content_obstruction",
  ]) {
    if (stickyPayload[requirement] !== true) return null;
  }

  const estimateForm = durableEstimateForm(form, formPayload, preview, stickyEstimateLabel);
  if (!estimateForm) return null;
  let campaign: PerformanceLocalCampaign | null = null;
  if (banner?.enabled) {
    if (banner.destination_component_configuration_id !== form.id) return null;
    const bannerPayload = banner.configuration_payload;
    const bannerLabel = exactText(bannerPayload.message);
    const ctaLabel = exactText(bannerPayload.cta_label);
    const approvalIdentity = exactText(bannerPayload.approval_identity);
    if (!bannerLabel || !ctaLabel || !approvalIdentity || ctaLabel !== stickyEstimateLabel) return null;
    const ctaDestination = `#${performanceLocalFormDomId(form.id)}`;
    const commonCampaign = {
      ...performanceLocalOptionalConfiguration(
        "campaign_banner",
        preview.website_configuration.website_id,
        bannerLabel,
        {
          approvalIdentity,
          campaignLabel: bannerLabel,
          ctaDestination,
          ctaLabel,
        },
      ),
      approvalIdentity,
      campaignLabel: bannerLabel,
      ctaDestination,
      ctaLabel,
      destinationComponentConfigurationId: form.id,
      enabled: true,
      websiteId: preview.website_configuration.website_id,
    };
    if (bannerPayload.intent === "evergreen_conversion") {
      campaign = { ...commonCampaign, intent: "evergreen_conversion" };
    } else if (bannerPayload.intent === "time_bound_campaign") {
      const startDate = exactText(bannerPayload.start_at);
      const endDate = exactText(bannerPayload.end_at);
      const termsReference = exactText(bannerPayload.terms_reference);
      const offerDetails = exactText(bannerPayload.approved_offer_details);
      if (!startDate || !endDate || !termsReference || !offerDetails) return null;
      campaign = {
        ...commonCampaign,
        intent: "time_bound_campaign",
        startDate,
        endDate,
        termsReference,
        offerDetails,
      };
    } else {
      return null;
    }
  }

  const phoneDisplay = exactText(preview.governed_actions.phone_display);
  const callDestination = exactText(preview.governed_actions.call_destination);
  const governedContact = phoneDisplay && callDestination
    ? {
        callDestination,
        phoneDisplay,
        websiteId: preview.website_configuration.website_id,
      }
    : null;
  if (Boolean(phoneDisplay) !== Boolean(callDestination)) return null;

  return {
    campaign,
    estimateForm,
    governedContact,
    stickyActions: {
      callLabel,
      componentConfigurationId: sticky.id,
      desktopHeaderActionsEnabled: true,
      destinationComponentConfigurationId: form.id,
      enabled: true,
      estimateLabel: stickyEstimateLabel,
      mobileStickyActionsEnabled: true,
    },
  };
}

function durableEstimateForm(
  component: WebsiteThemeComponentConfigurationRead,
  payload: Record<string, unknown>,
  preview: ThemeDraftPreviewRead,
  ctaLabel: string,
): PerformanceLocalEstimateFormConfiguration | null {
  if (
    payload.submission_state !== "disabled_pending_provider_configuration" ||
    payload.provider_key !== null ||
    payload.destination !== null ||
    payload.privacy_policy_destination !== null ||
    payload.consent_language !== null ||
    payload.data_retention_policy !== null ||
    payload.spam_strategy !== null ||
    payload.success_behavior !== null ||
    payload.failure_behavior !== null ||
    payload.audit_identity !== null ||
    !Array.isArray(payload.fields) ||
    payload.fields.length !== 5
  ) return null;
  const fields = payload.fields.map(performanceLocalDurableEstimateField);
  if (fields.some((field) => field === null)) return null;
  const submitLabel = exactText(payload.submit_label);
  const previewNotice = exactText(payload.preview_notice);
  if (!submitLabel || !previewNotice) return null;
  return {
    componentConfigurationId: component.id,
    componentInstanceKey: component.component_instance_key,
    ctaLabel,
    fields: fields as PerformanceLocalEstimateField[],
    previewNotice,
    providerState: {
      canSubmit: false,
      collectsData: false,
      destination: null,
      providerKey: null,
      submissionState: "disabled_pending_provider_configuration",
    },
    submitLabel,
    visualState: "idle",
  };
}

export function performanceLocalDurableEstimateField(
  value: unknown,
): PerformanceLocalEstimateField | null {
  const field = asRecord(value);
  const validation = asRecord(field.validation_contract);
  const key = exactText(field.field_key);
  const label = exactText(field.label);
  const accessibilityLabel = exactText(field.accessibility_label);
  const providerMapping = exactText(field.provider_mapping);
  const autoComplete = exactText(field.autocomplete_policy);
  const control = field.control;
  const inputType = field.input_type;
  const responsiveLayout = field.responsive_layout;
  const rule = validation.rule;
  if (
    !isEstimateFieldKey(key) ||
    !label ||
    !accessibilityLabel ||
    !providerMapping ||
    autoComplete !== "off" ||
    (control !== "input" && control !== "textarea") ||
    (inputType !== "text" && inputType !== "tel") ||
    (responsiveLayout !== "half" && responsiveLayout !== "full") ||
    !["nonempty_text", "phone", "postal_code", "free_text"].includes(String(rule)) ||
    typeof field.required !== "boolean" ||
    !positiveInteger(field.order) ||
    !positiveInteger(field.maximum_length) ||
    !Number.isSafeInteger(validation.minimum_length) ||
    Number(validation.minimum_length) < 0 ||
    validation.maximum_length !== field.maximum_length
  ) return null;
  return {
    accessibilityLabel,
    autoComplete,
    control,
    inputMode: key === "phone" ? "tel" : key === "postal-code" ? "numeric" : "text",
    key,
    label,
    maxLength: Number(field.maximum_length),
    order: Number(field.order),
    providerMapping,
    required: field.required,
    responsive: {
      desktop: responsiveLayout,
      tablet: responsiveLayout,
      mobile: "full",
    },
    rows: control === "textarea" ? 3 : undefined,
    type: control === "input" ? inputType : undefined,
    validation: {
      maximumLength: Number(validation.maximum_length),
      minimumLength: Number(validation.minimum_length),
      rule: rule as PerformanceLocalEstimateField["validation"]["rule"],
    },
  };
}

function exactComponent(
  components: WebsiteThemeComponentConfigurationRead[],
  key: string,
): WebsiteThemeComponentConfigurationRead | null {
  const matches = components.filter((component) => component.component_key === key);
  return matches.length === 1 ? matches[0] : null;
}

function durableThemeContractIdentity(preview: ThemeDraftPreviewRead): boolean {
  if (
    preview.theme_version.source_commit !== PERFORMANCE_LOCAL_V2_SOURCE_COMMIT ||
    !sameCanonicalJson(
      preview.theme_version.supported_component_contracts,
      PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS,
    )
  ) return false;
  return preview.components.every((component) => {
    const contract = PERFORMANCE_LOCAL_SERIALIZED_COMPONENT_CONTRACTS.find(
      (candidate) => candidate.component_key === component.component_key,
    );
    return Boolean(
      contract &&
      component.component_contract_version === contract.contract_version &&
      component.placement === contract.placement &&
      component.variant === contract.variant &&
      sameCanonicalJson(
        component.responsive_visibility,
        contract.responsive_visibility,
      ) &&
      (
        component.scope_type === "website_default" ||
        (component.scope_type === "page_override" && contract.supports_page_override)
      )
    );
  });
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

function isEstimateFieldKey(value: unknown): value is PerformanceLocalEstimateField["key"] {
  return typeof value === "string" && ["name", "phone", "postal-code", "requested-service", "message"].includes(value);
}

function exactText(value: unknown): string | null {
  return typeof value === "string" && value === value.trim() && value.length > 0 && !/[\u0000-\u001f\u007f]/.test(value)
    ? value
    : null;
}

function canonicalFingerprint(value: unknown): boolean {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function formatBoolean(value: boolean): "Yes" | "No" {
  return value ? "Yes" : "No";
}

function themeDraftPrivacyStatus(preview: ThemeDraftPreviewRead): string {
  return preview.privacy_status;
}

function themeAuditTarget(
  audit: ThemeDraftPreviewRead["audit_history"][number],
): string {
  if (audit.component_configuration_id) return `component configuration ${audit.component_configuration_id}`;
  if (audit.website_theme_configuration_id) return `Website configuration ${audit.website_theme_configuration_id}`;
  if (audit.theme_family_version_id) return `Theme Version ${audit.theme_family_version_id}`;
  if (audit.theme_family_id) return `Theme Family ${audit.theme_family_id}`;
  return "unknown target";
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
