import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Images,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { Link } from "react-router-dom";

import { apiRequest } from "../api";
import {
  bindPageMediaContext,
  effectivePlacementId,
  isCurrentPageMediaLoad,
  isPageMediaAssetEligible,
  isSafeLocalMediaUrl,
  pageMediaAssetId,
  pageMediaPlacementKey,
  placementReadinessStatus,
  validatePageMediaWorkspace,
} from "../components/pageMediaContext";
import type { PageMediaContextBinding } from "../components/pageMediaContext";
import type {
  PageMediaAssetCandidate,
  PageMediaPlacement,
  PageMediaPlanningWorkspace,
  PageMediaRequirementState,
  SitePlan,
  SitePlanCompositionRefreshResult,
  Website,
  WebsiteContext,
} from "../types";

export type DecisionFormState = {
  requirementState: PageMediaRequirementState;
  operator: string;
  rationale: string;
  componentOrSection: string;
  purpose: string;
  customerOutcome: string;
  intendedSubject: string;
  orientation: string;
  aspectRatio: string;
  minimumWidth: string;
  minimumHeight: string;
  cropIntent: string;
  focalPointIntent: string;
  responsiveBehavior: string;
  accessibilityIntent: string;
  captionIntent: string;
  approvedSourceConstraints: string;
  permittedReusePolicy: string;
  replacementPolicy: string;
  compatiblePageTypes: string;
};

type AssignmentFormState = {
  imageMetadataId: string;
  operator: string;
  rationale: string;
};

export default function PageMediaPlanningPage() {
  const [websites, setWebsites] = useState<Website[]>([]);
  const [websiteId, setWebsiteId] = useState(0);
  const [context, setContext] = useState<WebsiteContext | null>(null);
  const [plans, setPlans] = useState<SitePlan[]>([]);
  const [sitePlanId, setSitePlanId] = useState(0);
  const [binding, setBinding] = useState<PageMediaContextBinding | null>(null);
  const [workspace, setWorkspace] = useState<PageMediaPlanningWorkspace | null>(null);
  const [selectedPlacementKey, setSelectedPlacementKey] = useState("");
  const [search, setSearch] = useState("");
  const [pageTypeFilter, setPageTypeFilter] = useState("all");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [working, setWorking] = useState(false);
  const scopeGeneration = useRef(0);
  const workspaceGeneration = useRef(0);

  useEffect(() => {
    async function loadWebsites() {
      try {
        const rows = await apiRequest<Website[]>("/api/websites");
        setWebsites(rows);
        setWebsiteId(rows[0]?.id ?? 0);
      } catch (value) {
        setError(value instanceof Error ? value.message : "Unable to load Websites.");
      }
    }
    void loadWebsites();
  }, []);

  useEffect(() => {
    if (websiteId) void loadWebsiteScope(websiteId);
    else clearWebsiteScope();
  }, [websiteId, websites]);

  const selectedWebsite = websites.find((item) => item.id === websiteId) ?? null;
  const selectedPlan = plans.find((item) => item.id === sitePlanId) ?? null;
  const selectedPlacement = workspace?.placements.find(
    (placement) => placementIdentity(placement) === selectedPlacementKey,
  ) ?? null;
  const visiblePlacements = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (workspace?.placements ?? []).filter((placement) => {
      if (pageTypeFilter !== "all" && placement.planned_page.page_type !== pageTypeFilter) {
        return false;
      }
      return (
        !needle ||
        placement.planned_page.working_name.toLowerCase().includes(needle) ||
        pageMediaPlacementKey(placement).toLowerCase().includes(needle) ||
        placement.suggestion?.purpose.toLowerCase().includes(needle)
      );
    });
  }, [pageTypeFilter, search, workspace?.placements]);
  const pageTypes = useMemo(
    () => Array.from(new Set((workspace?.placements ?? []).map((item) => item.planned_page.page_type))).sort(),
    [workspace?.placements],
  );

  function clearWebsiteScope() {
    scopeGeneration.current += 1;
    workspaceGeneration.current += 1;
    setContext(null);
    setPlans([]);
    setSitePlanId(0);
    setBinding(null);
    setWorkspace(null);
    setSelectedPlacementKey("");
  }

  async function loadWebsiteScope(selectedWebsiteId: number) {
    const generation = ++scopeGeneration.current;
    workspaceGeneration.current += 1;
    const website = websites.find((item) => item.id === selectedWebsiteId);
    setContext(null);
    setPlans([]);
    setSitePlanId(0);
    setBinding(null);
    setWorkspace(null);
    setSelectedPlacementKey("");
    setMessage("");
    setError("");
    if (!website) return;
    setLoading(true);
    try {
      const [nextContext, nextPlans] = await Promise.all([
        apiRequest<WebsiteContext>(`/api/websites/${selectedWebsiteId}/context`),
        apiRequest<SitePlan[]>(`/api/site-plans?website_id=${selectedWebsiteId}`),
      ]);
      if (!isCurrentPageMediaLoad(generation, scopeGeneration.current)) return;
      setContext(nextContext);
      setPlans(nextPlans);
      const plan = nextPlans[0];
      if (!plan) return;
      const nextBinding = bindPageMediaContext(website, nextContext, plan);
      setSitePlanId(plan.id);
      setBinding(nextBinding);
      await loadWorkspace(plan, nextBinding);
    } catch (value) {
      if (!isCurrentPageMediaLoad(generation, scopeGeneration.current)) return;
      setError(
        value instanceof Error
          ? value.message
          : "Unable to load the authoritative Page Media context.",
      );
    } finally {
      if (isCurrentPageMediaLoad(generation, scopeGeneration.current)) setLoading(false);
    }
  }

  async function chooseSitePlan(nextSitePlanId: number) {
    setSitePlanId(nextSitePlanId);
    setWorkspace(null);
    setSelectedPlacementKey("");
    setMessage("");
    setError("");
    const plan = plans.find((item) => item.id === nextSitePlanId);
    if (!plan || !selectedWebsite || !context) {
      setBinding(null);
      return;
    }
    try {
      const nextBinding = bindPageMediaContext(selectedWebsite, context, plan);
      setBinding(nextBinding);
      await loadWorkspace(plan, nextBinding);
    } catch (value) {
      setError(value instanceof Error ? value.message : "Unable to load the selected Site Plan.");
    }
  }

  async function loadWorkspace(plan: SitePlan, owner: PageMediaContextBinding) {
    const generation = ++workspaceGeneration.current;
    setLoading(true);
    try {
      const result = await apiRequest<PageMediaPlanningWorkspace>(
        `/api/site-plans/${plan.id}/page-media`,
      );
      const validated = validatePageMediaWorkspace(result, owner);
      if (!isCurrentPageMediaLoad(generation, workspaceGeneration.current)) return;
      setWorkspace(validated);
      setSelectedPlacementKey((current) =>
        validated.placements.some((item) => placementIdentity(item) === current)
          ? current
          : validated.placements[0]
            ? placementIdentity(validated.placements[0])
            : "",
      );
    } finally {
      if (isCurrentPageMediaLoad(generation, workspaceGeneration.current)) setLoading(false);
    }
  }

  async function refreshSuggestions() {
    if (!selectedPlan || !binding) return;
    await mutateWorkspace(
      `/api/site-plans/${selectedPlan.id}/page-media/suggestions/refresh`,
      undefined,
      "Atlas Page Media suggestions refreshed. Operator decisions remain separate.",
    );
  }

  async function decidePlacement(
    placement: PageMediaPlacement,
    form: DecisionFormState,
  ) {
    if (!workspace || !binding) return;
    let payload;
    try {
      payload = buildPageMediaDecisionPayload(workspace, placement, form);
    } catch (value) {
      setError(value instanceof Error ? value.message : "The Page Media decision is invalid.");
      return;
    }
    await mutateWorkspace(
      `/api/site-plans/${workspace.site_plan_id}/page-media/placements/decide`,
      payload,
      "The operator Page Media decision was recorded with provenance.",
    );
  }

  async function assignAsset(
    placement: PageMediaPlacement,
    form: AssignmentFormState,
  ) {
    if (!workspace || !binding) return;
    const placementId = effectivePlacementId(placement);
    if (placementId === null) {
      setError("Record an included operator requirement before assigning media.");
      return;
    }
    let payload;
    try {
      payload = buildPageMediaAssignmentPayload(placement, form);
    } catch (value) {
      setError(value instanceof Error ? value.message : "The Page Media assignment is invalid.");
      return;
    }
    await mutateWorkspace(
      `/api/site-plans/${workspace.site_plan_id}/page-media/placements/${placementId}/assign`,
      payload,
      "The approved media assignment was recorded. Compositions were not refreshed automatically.",
    );
  }

  async function refreshCompositions() {
    if (!workspace || !binding) return;
    setWorking(true);
    setError("");
    setMessage("");
    try {
      const result = await apiRequest<SitePlanCompositionRefreshResult>(
        `/api/site-plans/${workspace.site_plan_id}/compositions/refresh`,
        { method: "POST" },
      );
      setMessage(
        `Explicit composition refresh complete: ${result.refreshed} refreshed, ${result.unchanged} unchanged, ${result.blocked.length} blocked.`,
      );
      if (selectedPlan) await loadWorkspace(selectedPlan, binding);
    } catch (value) {
      setError(value instanceof Error ? value.message : "Unable to refresh compositions.");
    } finally {
      setWorking(false);
    }
  }

  async function mutateWorkspace(path: string, payload: object | undefined, success: string) {
    if (!binding) return;
    setWorking(true);
    setError("");
    setMessage("");
    try {
      const result = await apiRequest<PageMediaPlanningWorkspace>(path, {
        method: "POST",
        ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
      });
      setWorkspace(validatePageMediaWorkspace(result, binding));
      setMessage(success);
    } catch (value) {
      setError(value instanceof Error ? value.message : "The Page Media operation failed.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="page pageMediaPlanningPage">
      <header className="pageHeader">
        <div>
          <span className="eyebrow">Website media governance</span>
          <h1>Page Media Planning</h1>
          <p>
            Plan purposeful, rights-aware media for one Website and Site Plan. Atlas
            suggestions never become operator approval or assignments implicitly.
          </p>
        </div>
      </header>

      {error && <div className="errorBanner">{error}</div>}
      {message && <div className="successBanner">{message}</div>}

      <section className="panel pageMediaContextPanel">
        <div className="panelHeader">
          <div>
            <h2>Authoritative Website Context</h2>
            <p>Website, Business, Brand, Identity, and Site Plan are one fail-closed scope.</p>
          </div>
          {loading && <span className="statusBadge muted">Loading</span>}
        </div>
        <div className="pageMediaContextSelectors">
          <label>
            <span>Website</span>
            <select
              value={websiteId}
              disabled={working || loading}
              onChange={(event) => setWebsiteId(Number(event.target.value))}
            >
              {!websites.length && <option value={0}>No Websites available</option>}
              {websites.map((website) => (
                <option key={website.id} value={website.id}>
                  {website.website_name} ({website.domain})
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Site Plan</span>
            <select
              value={sitePlanId}
              disabled={working || loading || !plans.length}
              onChange={(event) => void chooseSitePlan(Number(event.target.value))}
            >
              {!plans.length && <option value={0}>No Site Plan available</option>}
              {plans.map((plan) => (
                <option key={plan.id} value={plan.id}>
                  {plan.plan_name} (v{plan.version})
                </option>
              ))}
            </select>
          </label>
        </div>
        {context && binding && selectedPlan && (
          <dl className="detailGrid pageMediaContextSummary">
            <div><dt>Business</dt><dd>{context.business.company_name}</dd></div>
            <div><dt>Brand</dt><dd>{context.brand.public_name}</dd></div>
            <div><dt>Website</dt><dd>{context.website.website_name}</dd></div>
            <div><dt>Ownership</dt><dd>Website {binding.websiteId} · Site Plan {binding.sitePlanId}</dd></div>
          </dl>
        )}
      </section>

      {workspace && (
        <>
          <section className="panel pageMediaSummaryPanel">
            <div className="panelHeader">
              <div>
                <h2>Planning summary</h2>
                <p>
                  Planning record {workspace.planning_record
                    ? `v${workspace.planning_record.version}`
                    : "not generated"} · evaluated {formatDate(workspace.evaluated_at)}
                </p>
              </div>
              <span className={`readinessStatus ${workspace.ready ? "ready" : "needs_attention"}`}>
                {workspace.ready ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
                {workspace.ready ? "Ready" : "Needs attention"}
              </span>
            </div>
            <div className="pageMediaSummaryGrid">
              {pageMediaSummaryEntries(workspace).map(([key, count]) => (
                <article key={key}><strong>{count}</strong><span>{humanize(key)}</span></article>
              ))}
            </div>
            <div className="formActions">
              <button
                className="secondaryButton buttonWithIcon"
                disabled={working}
                onClick={() => void refreshSuggestions()}
              >
                <RefreshCw size={16} /> Refresh Atlas suggestions
              </button>
              <button
                className="secondaryButton buttonWithIcon"
                disabled={working || !workspace.placements.some((item) => item.composition_status === "stale")}
                onClick={() => void refreshCompositions()}
              >
                <RefreshCw size={16} /> Refresh stale compositions
              </button>
            </div>
            <p className="helperText">
              Composition refresh is always a separate explicit action; decisions and assignments never refresh automatically.
            </p>
          </section>

          <section className="panel pageMediaDiagnosticsPanel">
            <h2>Deterministic diagnostics</h2>
            {!workspace.diagnostics.length && <p className="helperText">No diagnostics reported.</p>}
            <ul className="pageMediaDiagnosticList">
              {workspace.diagnostics.map((diagnostic, index) => (
                <li key={`${diagnostic.category}:${diagnostic.planned_page_id ?? "site"}:${diagnostic.placement_key ?? "all"}:${diagnostic.record_id ?? index}`}>
                  <span className={`readinessStatus ${diagnostic.status}`}>{humanize(diagnostic.status)}</span>
                  <div><strong>{humanize(diagnostic.category)}</strong><p>{diagnostic.message}</p></div>
                </li>
              ))}
            </ul>
          </section>

          <section className="pageMediaWorkspace">
            <section className="panel pageMediaInventoryPanel">
              <div className="panelHeader">
                <div><h2>Planned Page placements</h2><p>{visiblePlacements.length} shown</p></div>
              </div>
              <div className="pageMediaFilters">
                <label><span>Search</span><input value={search} onChange={(event) => setSearch(event.target.value)} /></label>
                <label>
                  <span>Page type</span>
                  <select value={pageTypeFilter} onChange={(event) => setPageTypeFilter(event.target.value)}>
                    <option value="all">All page types</option>
                    {pageTypes.map((pageType) => <option key={pageType} value={pageType}>{humanize(pageType)}</option>)}
                  </select>
                </label>
              </div>
              <div className="pageMediaPlacementList">
                {visiblePlacements.map((placement) => {
                  const status = placementReadinessStatus(placement);
                  return (
                    <button
                      type="button"
                      key={placementIdentity(placement)}
                      className={selectedPlacementKey === placementIdentity(placement) ? "selected" : ""}
                      onClick={() => setSelectedPlacementKey(placementIdentity(placement))}
                    >
                      <span><strong>{placement.planned_page.working_name}</strong><small>{humanize(placement.planned_page.page_type)} · {humanize(pageMediaPlacementKey(placement))}</small></span>
                      <span className={`readinessStatus ${status}`}>{humanize(status)}</span>
                    </button>
                  );
                })}
              </div>
            </section>

            <section className="panel pageMediaPlacementPanel">
              {!selectedPlacement ? (
                <p className="helperText">Select a Planned Page placement to review it.</p>
              ) : (
                <PlacementWorkspace
                  key={`${placementIdentity(selectedPlacement)}:${workspace.planning_record?.version ?? "none"}:${selectedPlacement.effective_requirement?.id ?? "suggestion"}:${selectedPlacement.effective_requirement?.version ?? 0}`}
                  placement={selectedPlacement}
                  assets={workspace.assets}
                  planningRecordVersion={workspace.planning_record?.version ?? null}
                  working={working}
                  onDecide={decidePlacement}
                  onAssign={assignAsset}
                />
              )}
            </section>
          </section>
        </>
      )}
    </section>
  );
}

function PlacementWorkspace({
  placement,
  assets,
  planningRecordVersion,
  working,
  onDecide,
  onAssign,
}: {
  placement: PageMediaPlacement;
  assets: PageMediaAssetCandidate[];
  planningRecordVersion: number | null;
  working: boolean;
  onDecide: (placement: PageMediaPlacement, form: DecisionFormState) => Promise<void>;
  onAssign: (placement: PageMediaPlacement, form: AssignmentFormState) => Promise<void>;
}) {
  const requirement = placement.effective_requirement;
  const suggestion = placement.suggestion;
  const [decisionForm, setDecisionForm] = useState<DecisionFormState>(() =>
    decisionFormFromPlacement(placement),
  );
  const [assignmentForm, setAssignmentForm] = useState<AssignmentFormState>({
    imageMetadataId: "",
    operator: "",
    rationale: "",
  });
  const compatibleAssets = placement.compatible_asset_ids
    .map((id) => assets.find((asset) => pageMediaAssetId(asset) === id))
    .filter((asset): asset is PageMediaAssetCandidate => Boolean(asset))
    .filter((asset) => isPageMediaAssetEligible(asset, requirement?.accessibility_intent ?? suggestion?.accessibility_intent));
  const activeAsset = placement.active_assignment
    ? assets.find((asset) => pageMediaAssetId(asset) === placement.active_assignment?.image_metadata_id) ?? null
    : null;

  return (
    <div className="pageMediaPlacementWorkspace">
      <div className="panelHeader">
        <div>
          <span className="eyebrow">{humanize(placement.planned_page.page_type)}</span>
          <h2>{placement.planned_page.working_name}</h2>
          <p>{humanize(pageMediaPlacementKey(placement))} · composition {humanize(placement.composition_status)}</p>
        </div>
        {placement.planned_page.generated_page_id && (
          <Link className="linkButton buttonWithIcon" to={`/generated-pages/${placement.planned_page.generated_page_id}/preview`}>
            <ExternalLink size={15} /> Local preview
          </Link>
        )}
      </div>

      {placement.blocking_reasons.length > 0 && (
        <div className="pageMediaBlockers">
          <strong><AlertTriangle size={16} /> Current blockers</strong>
          <ul>{placement.blocking_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </div>
      )}

      <section className="pageMediaEvidenceSection atlasSuggestionSection">
        <h3>Atlas-generated suggestion</h3>
        <p className="helperText">Read-only planning guidance. It is not an operator decision or assignment.</p>
        {suggestion ? (
          <dl className="pageMediaEvidenceGrid">
            <div><dt>Purpose</dt><dd>{suggestion.purpose}</dd></div>
            <div><dt>Requirement</dt><dd>{humanize(suggestion.requirement_state)}</dd></div>
            <div><dt>Customer outcome</dt><dd>{suggestion.customer_outcome}</dd></div>
            <div><dt>Subject guidance</dt><dd>{suggestion.intended_subject}</dd></div>
            <div><dt>Accessibility</dt><dd>{humanize(suggestion.accessibility_intent)}</dd></div>
            <div><dt>Responsive behavior</dt><dd>{suggestion.responsive_behavior}</dd></div>
            <div><dt>Crop intent</dt><dd>{suggestion.crop_intent}</dd></div>
          </dl>
        ) : (
          <p className="helperText">No current Atlas suggestion. Refresh suggestions before recording a decision.</p>
        )}
      </section>

      <section className="pageMediaEvidenceSection operatorDecisionSection">
        <h3>Operator requirement decision</h3>
        {requirement ? (
          <dl className="pageMediaEvidenceGrid">
            <div><dt>Requirement</dt><dd>{humanize(requirement.requirement_state)}</dd></div>
            <div><dt>Provenance</dt><dd>{requirement.decided_by} · decision v{requirement.version} · {formatDate(requirement.decided_at)}</dd></div>
            <div><dt>Rationale</dt><dd>{requirement.rationale}</dd></div>
          </dl>
        ) : <p className="helperText">No operator decision exists.</p>}
        <form
          className="pageMediaDecisionForm"
          onSubmit={(event) => {
            event.preventDefault();
            void onDecide(placement, decisionForm);
          }}
        >
          <label>
            <span>Requirement decision</span>
            <select value={decisionForm.requirementState} onChange={(event) => setDecisionForm((current) => ({ ...current, requirementState: event.target.value as PageMediaRequirementState }))}>
              <option value="required">Required</option>
              <option value="advisory">Advisory</option>
              <option value="excluded">Excluded</option>
              <option value="deferred">Deferred</option>
            </select>
          </label>
          <label><span>Operator *</span><input value={decisionForm.operator} onChange={(event) => setDecisionForm((current) => ({ ...current, operator: event.target.value }))} required /></label>
          <label className="pageMediaWideField"><span>Rationale *</span><textarea value={decisionForm.rationale} onChange={(event) => setDecisionForm((current) => ({ ...current, rationale: event.target.value }))} required /></label>
          <details className="pageMediaContractEditor pageMediaWideField">
            <summary>Review or modify the placement contract</summary>
            <p className="helperText">
              These fields become a new versioned operator decision. Atlas guidance above remains unchanged.
            </p>
            <div className="pageMediaContractGrid">
              <label><span>Semantic component *</span><input value={decisionForm.componentOrSection} onChange={(event) => setDecisionForm((current) => ({ ...current, componentOrSection: event.target.value }))} required /></label>
              <label><span>Orientation *</span><select value={decisionForm.orientation} onChange={(event) => setDecisionForm((current) => ({ ...current, orientation: event.target.value }))}><option value="any">Any</option><option value="landscape">Landscape</option><option value="portrait">Portrait</option><option value="square">Square</option></select></label>
              <label><span>Aspect ratio *</span><input value={decisionForm.aspectRatio} onChange={(event) => setDecisionForm((current) => ({ ...current, aspectRatio: event.target.value }))} required /></label>
              <label><span>Minimum width *</span><input type="number" min={1} value={decisionForm.minimumWidth} onChange={(event) => setDecisionForm((current) => ({ ...current, minimumWidth: event.target.value }))} required /></label>
              <label><span>Minimum height *</span><input type="number" min={1} value={decisionForm.minimumHeight} onChange={(event) => setDecisionForm((current) => ({ ...current, minimumHeight: event.target.value }))} required /></label>
              <label><span>Accessibility intent *</span><input value={decisionForm.accessibilityIntent} onChange={(event) => setDecisionForm((current) => ({ ...current, accessibilityIntent: event.target.value }))} required /></label>
              <label className="pageMediaWideField"><span>Purpose *</span><textarea value={decisionForm.purpose} onChange={(event) => setDecisionForm((current) => ({ ...current, purpose: event.target.value }))} required /></label>
              <label className="pageMediaWideField"><span>Customer outcome *</span><textarea value={decisionForm.customerOutcome} onChange={(event) => setDecisionForm((current) => ({ ...current, customerOutcome: event.target.value }))} required /></label>
              <label className="pageMediaWideField"><span>Intended subject *</span><textarea value={decisionForm.intendedSubject} onChange={(event) => setDecisionForm((current) => ({ ...current, intendedSubject: event.target.value }))} required /></label>
              <label className="pageMediaWideField"><span>Crop intent *</span><textarea value={decisionForm.cropIntent} onChange={(event) => setDecisionForm((current) => ({ ...current, cropIntent: event.target.value }))} required /></label>
              <label className="pageMediaWideField"><span>Focal-point intent *</span><textarea value={decisionForm.focalPointIntent} onChange={(event) => setDecisionForm((current) => ({ ...current, focalPointIntent: event.target.value }))} required /></label>
              <label className="pageMediaWideField"><span>Responsive behavior *</span><textarea value={decisionForm.responsiveBehavior} onChange={(event) => setDecisionForm((current) => ({ ...current, responsiveBehavior: event.target.value }))} required /></label>
              <label className="pageMediaWideField"><span>Caption intent</span><textarea value={decisionForm.captionIntent} onChange={(event) => setDecisionForm((current) => ({ ...current, captionIntent: event.target.value }))} /></label>
              <label className="pageMediaWideField"><span>Approved source constraints * (comma or line separated)</span><textarea value={decisionForm.approvedSourceConstraints} onChange={(event) => setDecisionForm((current) => ({ ...current, approvedSourceConstraints: event.target.value }))} required /></label>
              <label className="pageMediaWideField"><span>Permitted reuse policy *</span><textarea value={decisionForm.permittedReusePolicy} onChange={(event) => setDecisionForm((current) => ({ ...current, permittedReusePolicy: event.target.value }))} required /></label>
              <label className="pageMediaWideField"><span>Replacement policy *</span><textarea value={decisionForm.replacementPolicy} onChange={(event) => setDecisionForm((current) => ({ ...current, replacementPolicy: event.target.value }))} required /></label>
              <label className="pageMediaWideField"><span>Compatible page types * (comma or line separated)</span><textarea value={decisionForm.compatiblePageTypes} onChange={(event) => setDecisionForm((current) => ({ ...current, compatiblePageTypes: event.target.value }))} required /></label>
            </div>
          </details>
          <button className="primaryButton" disabled={working || !suggestion || planningRecordVersion === null || !decisionForm.operator.trim() || !decisionForm.rationale.trim()}>
            Record new decision version
          </button>
        </form>
        <p className="helperText">History retained: {placement.requirement_history.length} durable decision record(s).</p>
      </section>

      <section className="pageMediaEvidenceSection mediaAssignmentSection">
        <h3>Approved media assignment</h3>
        {placement.active_assignment && activeAsset ? (
          <article className="pageMediaActiveAsset">
            <MediaAssetEvidence asset={activeAsset} />
            <p>Assigned by {placement.active_assignment.assigned_by || "unknown"} · assignment v{placement.active_assignment.assignment_version ?? "legacy"}</p>
            <p>{placement.active_assignment.assignment_rationale || "No assignment rationale recorded."}</p>
          </article>
        ) : <p className="helperText">No approved media is assigned to this placement.</p>}
        <form
          className="pageMediaAssignmentForm"
          onSubmit={(event) => {
            event.preventDefault();
            void onAssign(placement, assignmentForm);
          }}
        >
          <label className="pageMediaWideField">
            <span>Compatible approved asset</span>
            <select value={assignmentForm.imageMetadataId} onChange={(event) => setAssignmentForm((current) => ({ ...current, imageMetadataId: event.target.value }))}>
              <option value="">No asset selected</option>
              {compatibleAssets.map((asset) => <option key={pageMediaAssetId(asset)} value={pageMediaAssetId(asset)}>{asset.image_title}</option>)}
            </select>
          </label>
          <label><span>Operator *</span><input value={assignmentForm.operator} onChange={(event) => setAssignmentForm((current) => ({ ...current, operator: event.target.value }))} required /></label>
          <label className="pageMediaWideField"><span>Assignment rationale *</span><textarea value={assignmentForm.rationale} onChange={(event) => setAssignmentForm((current) => ({ ...current, rationale: event.target.value }))} required /></label>
          <button className="primaryButton" disabled={working || !requirement || !["required", "advisory"].includes(requirement.requirement_state) || !assignmentForm.imageMetadataId || !assignmentForm.operator.trim() || !assignmentForm.rationale.trim()}>
            Assign approved asset
          </button>
        </form>
        <div className="pageMediaCandidateGrid">
          {compatibleAssets.map((asset) => <MediaAssetEvidence key={pageMediaAssetId(asset)} asset={asset} />)}
        </div>
      </section>

      <section className="pageMediaEvidenceSection legacyObservationSection">
        <h3>Historical assignment observations</h3>
        <p className="helperText">Observed legacy records are preserved but never treated as Page Media approval.</p>
        {!placement.legacy_assignments.length ? <p>None observed.</p> : (
          <ul>{placement.legacy_assignments.map((item) => <li key={item.id}>Assignment {item.id} · image {item.image_metadata_id} · {humanize(item.image_role)} · {humanize(item.status)}</li>)}</ul>
        )}
      </section>
    </div>
  );
}

function MediaAssetEvidence({ asset }: { asset: PageMediaAssetCandidate }) {
  const candidateSource = asset.thumbnail_url || asset.optimized_url || asset.asset_url;
  const source = candidateSource && isSafeLocalMediaUrl(candidateSource) ? candidateSource : null;
  return (
    <article className="pageMediaAssetCard">
      {source ? <img src={source} alt={asset.reviewed_alt_text || ""} /> : <div className="pageMediaMissingAsset"><Images size={24} /><span>Managed preview unavailable</span></div>}
      <div>
        <strong>{asset.image_title || asset.media_key || `Media asset ${asset.id}`}</strong>
        <span><ShieldCheck size={14} /> {humanize(asset.provenance_type || "not_recorded")} · {humanize(asset.rights_status || "not_recorded")}</span>
        <small>{asset.width ?? "?"} × {asset.height ?? "?"} · SHA-256 {(asset.checksum_sha256 || "not recorded").slice(0, 12)}{asset.checksum_sha256 ? "…" : ""}</small>
        <small>{asset.reviewed_alt_text || "Decorative or alt-text intent pending"}</small>
        <details className="pageMediaAssetGovernance">
          <summary>Governance evidence</summary>
          <dl>
            <div><dt>Status</dt><dd>{humanize(asset.governance_status)}</dd></div>
            <div><dt>Acquisition</dt><dd>{humanize(asset.acquisition_source || "not_recorded")}</dd></div>
            <div><dt>Creator/source</dt><dd>{asset.creator_source_identity || "Not recorded"}</dd></div>
            <div><dt>Provenance notes</dt><dd>{asset.provenance_notes || "Not recorded"}</dd></div>
            <div><dt>Rights holder</dt><dd>{asset.rights_holder || "Not recorded"}</dd></div>
            <div><dt>Rights notes</dt><dd>{asset.rights_notes || "Not recorded"}</dd></div>
            <div><dt>Approved usage</dt><dd>{asset.approved_usage.join(", ") || "None recorded"}</dd></div>
            <div><dt>Prohibited usage</dt><dd>{asset.prohibited_usage.join(", ") || "None recorded"}</dd></div>
            <div><dt>Permitted placements</dt><dd>{asset.permitted_placement_keys.join(", ") || "None recorded"}</dd></div>
            <div><dt>Accessibility</dt><dd>{asset.accessibility_intent || "Not recorded"}</dd></div>
            <div><dt>Approval</dt><dd>{asset.approved_by ? `${asset.approved_by} · v${asset.approval_version ?? "?"} · ${asset.approved_at ? formatDate(asset.approved_at) : "time missing"}` : "Not approved"}</dd></div>
            <div><dt>GPS/EXIF</dt><dd>{humanize(asset.gps_metadata_status || "not_recorded")}</dd></div>
          </dl>
        </details>
      </div>
    </article>
  );
}

export function buildPageMediaDecisionPayload(
  workspace: PageMediaPlanningWorkspace,
  placement: PageMediaPlacement,
  form: DecisionFormState,
) {
  const operator = form.operator.trim();
  const rationale = form.rationale.trim();
  const suggestion = placement.suggestion;
  if (!workspace.planning_record || !suggestion) {
    throw new Error("A current Atlas planning record and suggestion are required.");
  }
  if (!operator || !rationale) {
    throw new Error("Operator identity and rationale are required.");
  }
  return {
    website_id: workspace.website_id,
    site_plan_id: workspace.site_plan_id,
    planned_page_id: placement.planned_page.id,
    placement_key: pageMediaPlacementKey(placement),
    requirement_state: form.requirementState,
    decided_by: operator,
    rationale,
    source_suggestion_key: suggestion.suggestion_key,
    expected_planning_version: workspace.planning_record.version,
    component_or_section: requiredValue(form.componentOrSection, "Semantic component"),
    purpose: requiredValue(form.purpose, "Purpose"),
    customer_outcome: requiredValue(form.customerOutcome, "Customer outcome"),
    intended_subject: requiredValue(form.intendedSubject, "Intended subject"),
    orientation: requiredValue(form.orientation, "Orientation"),
    aspect_ratio: requiredValue(form.aspectRatio, "Aspect ratio"),
    minimum_width: positiveInteger(form.minimumWidth, "Minimum width"),
    minimum_height: positiveInteger(form.minimumHeight, "Minimum height"),
    crop_intent: requiredValue(form.cropIntent, "Crop intent"),
    focal_point_intent: requiredValue(form.focalPointIntent, "Focal-point intent"),
    responsive_behavior: requiredValue(form.responsiveBehavior, "Responsive behavior"),
    accessibility_intent: requiredValue(form.accessibilityIntent, "Accessibility intent"),
    caption_intent: form.captionIntent.trim() || null,
    approved_source_constraints: normalizedList(form.approvedSourceConstraints, "Approved source constraints"),
    permitted_reuse_policy: requiredValue(form.permittedReusePolicy, "Permitted reuse policy"),
    replacement_policy: requiredValue(form.replacementPolicy, "Replacement policy"),
    compatible_page_types: normalizedList(form.compatiblePageTypes, "Compatible page types"),
  };
}

function decisionFormFromPlacement(placement: PageMediaPlacement): DecisionFormState {
  const source = placement.effective_requirement ?? placement.suggestion;
  return {
    requirementState: source?.requirement_state ?? "advisory",
    operator: "",
    rationale: "",
    componentOrSection: source?.component_or_section ?? "",
    purpose: source?.purpose ?? "",
    customerOutcome: source?.customer_outcome ?? "",
    intendedSubject: source?.intended_subject ?? "",
    orientation: source?.orientation ?? "landscape",
    aspectRatio: source?.aspect_ratio ?? "16:9",
    minimumWidth: source?.minimum_width ? String(source.minimum_width) : "",
    minimumHeight: source?.minimum_height ? String(source.minimum_height) : "",
    cropIntent: source?.crop_intent ?? "",
    focalPointIntent: source?.focal_point_intent ?? "",
    responsiveBehavior: source?.responsive_behavior ?? "",
    accessibilityIntent: source?.accessibility_intent ?? "informative",
    captionIntent: source?.caption_intent ?? "",
    approvedSourceConstraints: (source?.approved_source_constraints ?? []).join("\n"),
    permittedReusePolicy: source?.permitted_reuse_policy ?? "",
    replacementPolicy: source?.replacement_policy ?? "",
    compatiblePageTypes: (source?.compatible_page_types ?? []).join("\n"),
  };
}

function requiredValue(value: string, label: string): string {
  const cleaned = value.trim();
  if (!cleaned) throw new Error(`${label} is required.`);
  return cleaned;
}

function positiveInteger(value: string, label: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${label} must be a positive integer.`);
  }
  return parsed;
}

function normalizedList(value: string, label: string): string[] {
  const values = Array.from(
    new Set(
      value
        .split(/[\n,]/)
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean),
    ),
  );
  if (!values.length) throw new Error(`${label} must include at least one value.`);
  return values;
}

export function buildPageMediaAssignmentPayload(
  placement: PageMediaPlacement,
  form: AssignmentFormState,
) {
  const imageMetadataId = Number(form.imageMetadataId);
  const operator = form.operator.trim();
  const rationale = form.rationale.trim();
  if (!Number.isInteger(imageMetadataId) || imageMetadataId <= 0) {
    throw new Error("Select one compatible approved media asset.");
  }
  if (!operator || !rationale) {
    throw new Error("Assignment operator identity and rationale are required.");
  }
  if (
    !placement.effective_requirement ||
    !["required", "advisory"].includes(placement.effective_requirement.requirement_state)
  ) {
    throw new Error("Only a required or advisory Page Media requirement can receive an assignment.");
  }
  if (!placement.compatible_asset_ids.includes(imageMetadataId)) {
    throw new Error("The selected asset is not compatible with this Page Media placement.");
  }
  return {
    image_metadata_id: imageMetadataId,
    assigned_by: operator,
    rationale,
    expected_requirement_version: placement.effective_requirement.version,
  };
}

function placementIdentity(placement: PageMediaPlacement) {
  return `${placement.planned_page.id}:${pageMediaPlacementKey(placement)}`;
}

function pageMediaSummaryEntries(
  workspace: PageMediaPlanningWorkspace,
): Array<[string, number]> {
  return Object.entries(workspace.summary).filter(
    (entry): entry is [string, number] => typeof entry[1] === "number",
  );
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}
