import { useEffect, useMemo, useState } from "react";
import { ClipboardList, FilePlus2, RefreshCw, Save, Trash2 } from "lucide-react";

import { apiRequest } from "../api";
import CoveragePlanningPanel from "../components/CoveragePlanningPanel";
import DraftingEligibilityPanel from "../components/DraftingEligibilityPanel";
import type {
  City,
  CoverageInventoryPreview,
  CoveragePolicy,
  DraftingEligibilityManifest,
  County,
  InternalLinkIntent,
  NavigationItem,
  PageComposition,
  PageType,
  PlannedPage,
  Service,
  SitePlan,
  SitePlanDetail,
  SiteConnectionPlan,
  SitePlanCompositionRefreshResult,
  Website,
  WebsiteReadinessReport
} from "../types";

const PAGE_TYPES: Array<{ value: PageType; label: string }> = [
  { value: "home", label: "Home" },
  { value: "about", label: "About" },
  { value: "contact", label: "Contact" },
  { value: "service", label: "Service" },
  { value: "county", label: "County / Service Area" },
  { value: "city", label: "City / Local Area" },
  { value: "city_service", label: "City-Service" },
  { value: "informational", label: "Informational" },
  { value: "faq", label: "Informational / FAQ" }
];

type DraftPage = {
  page_type: PageType;
  working_name: string;
  intended_slug: string;
  service_id: string;
  city_id: string;
  county_id: string;
  parent_planned_page_id: string;
};

const EMPTY_PAGE: DraftPage = {
  page_type: "home",
  working_name: "",
  intended_slug: "",
  service_id: "",
  city_id: "",
  county_id: "",
  parent_planned_page_id: ""
};

export default function SitePlansPage() {
  const [websites, setWebsites] = useState<Website[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [cities, setCities] = useState<City[]>([]);
  const [counties, setCounties] = useState<County[]>([]);
  const [websiteId, setWebsiteId] = useState<number | null>(null);
  const [plans, setPlans] = useState<SitePlan[]>([]);
  const [plan, setPlan] = useState<SitePlanDetail | null>(null);
  const [readiness, setReadiness] = useState<WebsiteReadinessReport | null>(null);
  const [connections, setConnections] = useState<SiteConnectionPlan | null>(null);
  const [coveragePolicy, setCoveragePolicy] = useState<CoveragePolicy | null>(null);
  const [coverageInventory, setCoverageInventory] =
    useState<CoverageInventoryPreview | null>(null);
  const [eligibility, setEligibility] =
    useState<DraftingEligibilityManifest | null>(null);
  const [compositions, setCompositions] = useState<PageComposition[]>([]);
  const [draft, setDraft] = useState<DraftPage>(EMPTY_PAGE);
  const [purposeOverrides, setPurposeOverrides] = useState<Record<number, string>>({});
  const [message, setMessage] = useState("");
  const [working, setWorking] = useState(false);

  const website = websites.find((item) => item.id === websiteId);
  const websiteServices = useMemo(
    () => services.filter((item) => item.business_id === website?.business_id),
    [services, website?.business_id]
  );

  useEffect(() => {
    void loadReferenceData();
  }, []);

  useEffect(() => {
    if (websiteId !== null) void loadPlans(websiteId);
  }, [websiteId]);

  async function loadReferenceData() {
    try {
      const [websiteRows, serviceRows, cityRows, countyRows] = await Promise.all([
        apiRequest<Website[]>("/api/websites"),
        apiRequest<Service[]>("/api/services"),
        apiRequest<City[]>("/api/cities?limit=500"),
        apiRequest<County[]>("/api/counties?limit=500")
      ]);
      setWebsites(websiteRows);
      setServices(serviceRows);
      setCities(cityRows);
      setCounties(countyRows);
      setWebsiteId(websiteRows[0]?.id ?? null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load Site Plan data.");
    }
  }

  async function loadPlans(selectedWebsiteId: number) {
    try {
      const rows = await apiRequest<SitePlan[]>(
        `/api/site-plans?website_id=${selectedWebsiteId}`
      );
      setPlans(rows);
      if (rows[0]) {
        const [detail, readinessReport, connectionPlan, policy, inventory, eligibilityManifest, compositionRows] = await Promise.all([
          apiRequest<SitePlanDetail>(`/api/site-plans/${rows[0].id}`),
          apiRequest<WebsiteReadinessReport>(`/api/site-plans/${rows[0].id}/readiness`),
          apiRequest<SiteConnectionPlan>(`/api/site-plans/${rows[0].id}/connections`),
          apiRequest<CoveragePolicy>(`/api/site-plans/${rows[0].id}/coverage`),
          apiRequest<CoverageInventoryPreview>(
            `/api/site-plans/${rows[0].id}/coverage/inventory`
          ),
          apiRequest<DraftingEligibilityManifest>(
            `/api/site-plans/${rows[0].id}/drafting-eligibility`
          ),
          apiRequest<PageComposition[]>(`/api/site-plans/${rows[0].id}/compositions`),
        ]);
        setPlan(detail);
        setReadiness(readinessReport);
        setConnections(connectionPlan);
        setCoveragePolicy(policy);
        setCoverageInventory(inventory);
        setEligibility(eligibilityManifest);
        setCompositions(compositionRows);
        setPurposeOverrides(
          Object.fromEntries(
            detail.planned_pages.map((page) => [
              page.id,
              String(page.planning_record.operator_overrides.purpose ?? "")
            ])
          )
        );
      } else {
        setPlan(null);
        setReadiness(null);
        setConnections(null);
        setCoveragePolicy(null);
        setCoverageInventory(null);
        setEligibility(null);
        setCompositions([]);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load Site Plans.");
    }
  }

  async function createPlan() {
    if (!websiteId || !website) return;
    setWorking(true);
    try {
      await apiRequest<SitePlan>("/api/site-plans", {
        method: "POST",
        body: JSON.stringify({
          website_id: websiteId,
          plan_key: "primary",
          plan_name: `${website.website_name} Site Plan`,
          status: "draft"
        })
      });
      await loadPlans(websiteId);
      setMessage("Site Plan created.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create Site Plan.");
    } finally {
      setWorking(false);
    }
  }

  async function createPage() {
    if (!websiteId || !plan) return;
    setWorking(true);
    try {
      await apiRequest<PlannedPage>(`/api/site-plans/${plan.id}/planned-pages`, {
        method: "POST",
        body: JSON.stringify({
          website_id: websiteId,
          site_plan_id: plan.id,
          page_type: draft.page_type,
          working_name: draft.working_name,
          intended_slug: draft.intended_slug,
          service_id: numberOrNull(draft.service_id),
          city_id: numberOrNull(draft.city_id),
          county_id: numberOrNull(draft.county_id),
          parent_planned_page_id: numberOrNull(draft.parent_planned_page_id),
          planning_status: "planned"
        })
      });
      setDraft(EMPTY_PAGE);
      await loadPlans(websiteId);
      setMessage("Planned Page and Planning Record created.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create Planned Page.");
    } finally {
      setWorking(false);
    }
  }

  async function refreshRecord(pageId: number) {
    if (!websiteId) return;
    setWorking(true);
    try {
      await apiRequest(`/api/site-plans/planned-pages/${pageId}/planning-record/refresh`, {
        method: "POST"
      });
      await loadPlans(websiteId);
      setMessage("Planning Record refreshed from approved information.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to refresh Planning Record.");
    } finally {
      setWorking(false);
    }
  }

  async function savePurposeOverride(page: PlannedPage) {
    if (!websiteId) return;
    const purpose = (purposeOverrides[page.id] ?? "").trim();
    const existing = { ...page.planning_record.operator_overrides };
    if (purpose) existing.purpose = purpose;
    else delete existing.purpose;
    setWorking(true);
    try {
      await apiRequest(
        `/api/site-plans/planned-pages/${page.id}/planning-record/overrides`,
        {
          method: "PATCH",
          body: JSON.stringify({ operator_overrides: existing })
        }
      );
      await loadPlans(websiteId);
      setMessage("Operator override saved separately from Atlas answers.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save override.");
    } finally {
      setWorking(false);
    }
  }

  async function draftPage(page: PlannedPage) {
    if (!websiteId) return;
    setWorking(true);
    try {
      await apiRequest(`/api/site-plans/planned-pages/${page.id}/draft`, {
        method: "POST",
        body: JSON.stringify({
          website_id: websiteId,
          allow_overwrite: Boolean(page.generated_page_id)
        })
      });
      await loadPlans(websiteId);
      setMessage(
        page.generated_page_id
          ? "Reviewable draft refreshed from the current Planning Record."
          : "Reviewable draft created from the current Planning Record."
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create draft.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="pageStack sitePlanPage">
      <section className="panel">
        <div className="panelHeader">
          <div>
            <p className="eyebrow">Website Planning</p>
            <h1>Site Plan</h1>
            <p>Plan the complete website before content generation.</p>
          </div>
          <ClipboardList size={28} aria-hidden="true" />
        </div>
        <label>
          <span>Selected Website</span>
          <select
            value={websiteId ?? ""}
            onChange={(event) => setWebsiteId(Number(event.target.value))}
          >
            {websites.map((item) => (
              <option key={item.id} value={item.id}>
                {item.website_name} — {item.domain}
              </option>
            ))}
          </select>
        </label>
        {message && <p className="statusMessage">{message}</p>}
      </section>

      {!plan ? (
        <section className="panel">
          <h2>No Site Plan</h2>
          <p>Create the primary Site Plan for the selected Website.</p>
          <button className="primaryButton" disabled={working || !websiteId} onClick={createPlan}>
            Create Site Plan
          </button>
        </section>
      ) : (
        <>
          <section className="panel">
            <div className="panelHeader">
              <div>
                <h2>{plan.plan_name}</h2>
                <p>{plan.planned_pages.length} planned pages · Version {plan.version}</p>
              </div>
              <span className="countBadge">{plan.status}</span>
            </div>
            <div className="sitePlanForm">
              <label>
                <span>Page Type</span>
                <select
                  value={draft.page_type}
                  onChange={(event) =>
                    setDraft({ ...draft, page_type: event.target.value as PageType })
                  }
                >
                  {PAGE_TYPES.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>Working Page Name</span>
                <input
                  value={draft.working_name}
                  onChange={(event) => setDraft({ ...draft, working_name: event.target.value })}
                />
              </label>
              <label>
                <span>Intended Slug</span>
                <input
                  value={draft.intended_slug}
                  onChange={(event) => setDraft({ ...draft, intended_slug: event.target.value })}
                />
              </label>
              <RelationSelect
                label="Service"
                value={draft.service_id}
                onChange={(value) => setDraft({ ...draft, service_id: value })}
                options={websiteServices.map((item) => [item.id, item.service_name])}
              />
              <RelationSelect
                label="County"
                value={draft.county_id}
                onChange={(value) => setDraft({ ...draft, county_id: value })}
                options={counties.map((item) => [item.id, `${item.county_name}, ${item.state}`])}
              />
              <RelationSelect
                label="City"
                value={draft.city_id}
                onChange={(value) => setDraft({ ...draft, city_id: value })}
                options={cities.map((item) => [item.id, `${item.city_name}, ${item.state}`])}
              />
              <RelationSelect
                label="Parent Page"
                value={draft.parent_planned_page_id}
                onChange={(value) => setDraft({ ...draft, parent_planned_page_id: value })}
                options={plan.planned_pages.map((item) => [item.id, item.working_name])}
              />
              <button
                className="primaryButton"
                disabled={working || !draft.working_name.trim() || !draft.intended_slug.trim()}
                onClick={createPage}
              >
                Add Planned Page
              </button>
            </div>
          </section>

          {readiness && <WebsiteReadinessPanel report={readiness} />}
          {websiteId && (
            <CompositionFoundationPanel
              plan={plan}
              compositions={compositions}
              working={working}
              setWorking={setWorking}
              reload={() => loadPlans(websiteId)}
              reportMessage={setMessage}
            />
          )}
          {coveragePolicy && coverageInventory && websiteId && (
            <CoveragePlanningPanel
              key={`coverage-${plan.id}`}
              planId={plan.id}
              policy={coveragePolicy}
              inventory={coverageInventory}
              working={working}
              reload={() => loadPlans(websiteId)}
              reportMessage={setMessage}
            />
          )}
          {eligibility && websiteId && (
            <DraftingEligibilityPanel
              planId={plan.id}
              websiteId={websiteId}
              manifest={eligibility}
              working={working}
              reload={() => loadPlans(websiteId)}
              reportMessage={setMessage}
            />
          )}
          {connections && websiteId && (
            <SiteConnectionPanel
              key={plan.id}
              plan={plan}
              connections={connections}
              websiteId={websiteId}
              reload={() => loadPlans(websiteId)}
              reportMessage={setMessage}
            />
          )}

          <section className="sitePlanCards">
            {plan.planned_pages.map((page) => (
              <article className="panel plannedPageCard" key={page.id}>
                <div className="panelHeader">
                  <div>
                    <p className="eyebrow">{labelForPageType(page.page_type)}</p>
                    <h2>{page.working_name}</h2>
                    <code>/{page.intended_slug}</code>
                  </div>
                  <div>
                    <span className="countBadge">{page.planning_status}</span>
                    <span className={`confidenceBadge ${page.planning_record.confidence_level}`}>
                      {Math.round(page.planning_record.confidence_score * 100)}% confidence
                    </span>
                    <span className={`confidenceBadge ${readinessTone(page)}`}>
                      {readinessLabel(page)}
                    </span>
                  </div>
                </div>
                <dl className="planningAnswers">
                  <div>
                    <dt>Why this page exists</dt>
                    <dd>{answerText(page, "purpose")}</dd>
                  </div>
                  <div>
                    <dt>Audience</dt>
                    <dd>{answerList(page, "audiences")}</dd>
                  </div>
                  <div>
                    <dt>Primary visitor action</dt>
                    <dd>{answerText(page, "primary_action")}</dd>
                  </div>
                  <div>
                    <dt>Required approved facts</dt>
                    <dd>{requiredFactsText(page)}</dd>
                  </div>
                  <div>
                    <dt>Missing required facts</dt>
                    <dd>{answerList(page, "missing_required_facts")}</dd>
                  </div>
                  <div>
                    <dt>Relationships</dt>
                    <dd>{relationshipText(page)}</dd>
                  </div>
                  <div>
                    <dt>Draft status</dt>
                    <dd>{page.generated_page_id ? `Generated Page #${page.generated_page_id} · ${page.generated_page_status}` : "Not drafted"}</dd>
                  </div>
                </dl>
                {page.draft_readiness.blocking_reasons.length > 0 && (
                  <div className="planningRecommendations">
                    <strong>Draft readiness blockers</strong>
                    <ul>
                      {page.draft_readiness.blocking_reasons.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="planningRecommendations">
                  <strong>Missing information and recommendations</strong>
                  {page.planning_record.improvement_recommendations.length ? (
                    <ul>
                      {page.planning_record.improvement_recommendations.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>No current recommendations.</p>
                  )}
                </div>
                <div className="planningRecommendations">
                  <strong>Operator overrides</strong>
                  <p>{operatorOverridesText(page)}</p>
                </div>
                <label>
                  <span>Operator purpose override</span>
                  <textarea
                    value={purposeOverrides[page.id] ?? ""}
                    placeholder="Leave blank to use the Atlas-generated answer."
                    onChange={(event) =>
                      setPurposeOverrides({
                        ...purposeOverrides,
                        [page.id]: event.target.value
                      })
                    }
                  />
                </label>
                <div className="editorActions">
                  <button
                    className="primaryButton buttonWithIcon"
                    disabled={working || page.draft_readiness.status !== "ready"}
                    onClick={() => draftPage(page)}
                  >
                    {page.generated_page_id ? (
                      <><RefreshCw size={16} aria-hidden="true" /> Refresh Draft</>
                    ) : (
                      <><FilePlus2 size={16} aria-hidden="true" /> Create Draft</>
                    )}
                  </button>
                  <button className="secondaryButton buttonWithIcon" disabled={working} onClick={() => refreshRecord(page.id)}>
                    <RefreshCw size={16} aria-hidden="true" /> Refresh Atlas Answers
                  </button>
                  <button className="primaryButton buttonWithIcon" disabled={working} onClick={() => savePurposeOverride(page)}>
                    <Save size={16} aria-hidden="true" /> Save Override
                  </button>
                </div>
                {page.generated_draft && <DraftSummary draft={page.generated_draft} />}
              </article>
            ))}
          </section>
        </>
      )}
    </div>
  );
}

function SiteConnectionPanel({
  plan,
  connections,
  websiteId,
  reload,
  reportMessage
}: {
  plan: SitePlanDetail;
  connections: SiteConnectionPlan;
  websiteId: number;
  reload: () => Promise<void>;
  reportMessage: (message: string) => void;
}) {
  const eligiblePages = plan.planned_pages.filter(
    (page) => page.page_type !== "city"
  );
  const firstSet = connections.navigation_sets[0];
  const [navSetId, setNavSetId] = useState(String(firstSet?.id ?? ""));
  const [navTargetId, setNavTargetId] = useState("");
  const [navParentId, setNavParentId] = useState("");
  const [navLabel, setNavLabel] = useState("");
  const [navPosition, setNavPosition] = useState("0");
  const [linkSourceId, setLinkSourceId] = useState("");
  const [linkTargetId, setLinkTargetId] = useState("");
  const [linkType, setLinkType] = useState<InternalLinkIntent["relationship_type"]>("conversion");
  const [linkPurpose, setLinkPurpose] = useState("");
  const [anchorGuidance, setAnchorGuidance] = useState("");
  const [busy, setBusy] = useState(false);

  const selectedSet = connections.navigation_sets.find(
    (item) => item.id === Number(navSetId)
  );
  const parentOptions = connections.navigation_items.filter(
    (item) => item.navigation_set_id === selectedSet?.id
  );
  const pageName = (id: number) =>
    plan.planned_pages.find((page) => page.id === id)?.working_name ?? `Planned Page #${id}`;

  async function refreshSuggestions() {
    setBusy(true);
    try {
      await apiRequest(
        `/api/site-plans/${plan.id}/connections/suggestions/refresh`,
        { method: "POST" }
      );
      await reload();
      reportMessage("Atlas connection suggestions refreshed; operator decisions were unchanged.");
    } catch (error) {
      reportMessage(error instanceof Error ? error.message : "Unable to refresh suggestions.");
    } finally {
      setBusy(false);
    }
  }

  async function addNavigationItem() {
    const target = eligiblePages.find((page) => page.id === Number(navTargetId));
    if (!selectedSet || !target) return;
    setBusy(true);
    try {
      await apiRequest(`/api/site-plans/${plan.id}/navigation-items`, {
        method: "POST",
        body: JSON.stringify({
          website_id: websiteId,
          site_plan_id: plan.id,
          navigation_set_id: selectedSet.id,
          target_planned_page_id: target.id,
          parent_navigation_item_id: numberOrNull(navParentId),
          label: navLabel.trim() || target.working_name,
          position: Number(navPosition) || 0,
          status: "active"
        })
      });
      setNavTargetId("");
      setNavParentId("");
      setNavLabel("");
      setNavPosition("0");
      await reload();
      reportMessage("Operator navigation decision added.");
    } catch (error) {
      reportMessage(error instanceof Error ? error.message : "Unable to add navigation item.");
    } finally {
      setBusy(false);
    }
  }

  async function removeNavigationItem(itemId: number) {
    setBusy(true);
    try {
      await apiRequest(`/api/site-plans/navigation-items/${itemId}`, {
        method: "DELETE"
      });
      await reload();
      reportMessage("Navigation item removed.");
    } catch (error) {
      reportMessage(error instanceof Error ? error.message : "Unable to remove navigation item.");
    } finally {
      setBusy(false);
    }
  }

  async function addInternalLink() {
    if (!linkSourceId || !linkTargetId || !linkPurpose.trim()) return;
    setBusy(true);
    try {
      await apiRequest(`/api/site-plans/${plan.id}/internal-link-intents`, {
        method: "POST",
        body: JSON.stringify({
          website_id: websiteId,
          site_plan_id: plan.id,
          source_planned_page_id: Number(linkSourceId),
          target_planned_page_id: Number(linkTargetId),
          purpose: linkPurpose,
          relationship_type: linkType,
          anchor_guidance: anchorGuidance.trim() || null,
          approval_state: "proposed"
        })
      });
      setLinkTargetId("");
      setLinkPurpose("");
      setAnchorGuidance("");
      await reload();
      reportMessage("Proposed internal-link decision added; no content was modified.");
    } catch (error) {
      reportMessage(error instanceof Error ? error.message : "Unable to add internal-link intent.");
    } finally {
      setBusy(false);
    }
  }

  async function updateInternalLink(
    intent: InternalLinkIntent,
    approvalState: InternalLinkIntent["approval_state"]
  ) {
    setBusy(true);
    try {
      await apiRequest(`/api/site-plans/internal-link-intents/${intent.id}`, {
        method: "PATCH",
        body: JSON.stringify({ approval_state: approvalState })
      });
      await reload();
      reportMessage(`Internal-link decision marked ${approvalState}.`);
    } catch (error) {
      reportMessage(error instanceof Error ? error.message : "Unable to update internal-link intent.");
    } finally {
      setBusy(false);
    }
  }

  async function removeInternalLink(intentId: number) {
    setBusy(true);
    try {
      await apiRequest(`/api/site-plans/internal-link-intents/${intentId}`, {
        method: "DELETE"
      });
      await reload();
      reportMessage("Internal-link decision removed.");
    } catch (error) {
      reportMessage(error instanceof Error ? error.message : "Unable to remove internal-link intent.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel siteConnectionPanel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Website Experience Planning</p>
          <h2>Navigation and Internal Links</h2>
          <p>Atlas suggestions remain separate from operator decisions. No draft content or CMS menu is changed here.</p>
        </div>
        <span className={`readinessStatus ${connections.ready ? "ready" : "needs_attention"}`}>
          {connections.ready ? "Ready" : "Needs attention"}
        </span>
      </div>

      <div className="connectionDiagnostics">
        {connections.diagnostics.map((diagnostic) => (
          <article key={diagnostic.key}>
            <div>
              <strong>{diagnostic.label}</strong>
              <span className={`readinessStatus ${diagnostic.status}`}>
                {humanizeReadiness(diagnostic.status)}
              </span>
            </div>
            <p>{diagnostic.message}</p>
            {diagnostic.affected_planned_page_ids.length > 0 && (
              <small>Planned Page IDs: {diagnostic.affected_planned_page_ids.join(", ")}</small>
            )}
          </article>
        ))}
      </div>

      <div className="connectionSuggestionSummary">
        <div>
          <strong>Atlas-generated suggestions</strong>
          <p>
            {connections.planning_record.generated_navigation_suggestions.length} navigation and{" "}
            {connections.planning_record.generated_internal_link_suggestions.length} internal-link suggestions.
          </p>
        </div>
        <button className="secondaryButton buttonWithIcon" disabled={busy} onClick={refreshSuggestions}>
          <RefreshCw size={16} aria-hidden="true" /> Refresh Suggestions
        </button>
      </div>
      <details>
        <summary>Review Atlas suggestions</summary>
        <div className="suggestionLists">
          <ul>
            {connections.planning_record.generated_navigation_suggestions.map((suggestion) => (
              <li key={String(suggestion.suggestion_key)}>
                {String(suggestion.set_type)} · {pageName(Number(suggestion.target_planned_page_id))} · {String(suggestion.rationale)}
              </li>
            ))}
          </ul>
          <ul>
            {connections.planning_record.generated_internal_link_suggestions.map((suggestion) => (
              <li key={String(suggestion.suggestion_key)}>
                {pageName(Number(suggestion.source_planned_page_id))} → {pageName(Number(suggestion.target_planned_page_id))}: {String(suggestion.purpose)}
              </li>
            ))}
          </ul>
        </div>
      </details>

      <div className="connectionPlanningGrid">
        <section>
          <h3>Operator navigation decisions</h3>
          <div className="connectionForm">
            <label>
              <span>Navigation set</span>
              <select value={navSetId} onChange={(event) => {
                setNavSetId(event.target.value);
                setNavParentId("");
              }}>
                {connections.navigation_sets.map((item) => (
                  <option key={item.id} value={item.id}>{item.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Target page</span>
              <select value={navTargetId} onChange={(event) => {
                const value = event.target.value;
                setNavTargetId(value);
                const target = eligiblePages.find((page) => page.id === Number(value));
                if (target) setNavLabel(target.working_name);
              }}>
                <option value="">Select a supported Planned Page</option>
                {eligiblePages.map((page) => (
                  <option key={page.id} value={page.id}>{page.working_name}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Label</span>
              <input value={navLabel} onChange={(event) => setNavLabel(event.target.value)} />
            </label>
            <label>
              <span>Parent item</span>
              <select value={navParentId} onChange={(event) => setNavParentId(event.target.value)}>
                <option value="">Top level</option>
                {parentOptions.map((item) => (
                  <option key={item.id} value={item.id}>{item.label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Position</span>
              <input type="number" min="0" value={navPosition} onChange={(event) => setNavPosition(event.target.value)} />
            </label>
            <button className="primaryButton" disabled={busy || !navTargetId} onClick={addNavigationItem}>
              Add Navigation Item
            </button>
          </div>
          <div className="connectionRecordList">
            {connections.navigation_sets.map((navSet) => (
              <div key={navSet.id}>
                <strong>{navSet.label}</strong>
                {connections.navigation_items
                  .filter((item) => item.navigation_set_id === navSet.id)
                  .map((item) => (
                    <NavigationItemEditor
                      key={item.id}
                      item={item}
                      items={connections.navigation_items.filter(
                        (candidate) =>
                          candidate.navigation_set_id === navSet.id &&
                          candidate.id !== item.id
                      )}
                      pageName={pageName}
                      disabled={busy}
                      onSaved={async () => {
                        await reload();
                        reportMessage("Navigation label, order, or hierarchy updated.");
                      }}
                      onError={reportMessage}
                      onRemove={() => removeNavigationItem(item.id)}
                    />
                  ))}
              </div>
            ))}
          </div>
        </section>

        <section>
          <h3>Operator internal-link decisions</h3>
          <div className="connectionForm">
            <label>
              <span>Source page</span>
              <select value={linkSourceId} onChange={(event) => setLinkSourceId(event.target.value)}>
                <option value="">Select source</option>
                {eligiblePages.map((page) => <option key={page.id} value={page.id}>{page.working_name}</option>)}
              </select>
            </label>
            <label>
              <span>Target page</span>
              <select value={linkTargetId} onChange={(event) => setLinkTargetId(event.target.value)}>
                <option value="">Select target</option>
                {eligiblePages.map((page) => <option key={page.id} value={page.id}>{page.working_name}</option>)}
              </select>
            </label>
            <label>
              <span>Relationship</span>
              <select value={linkType} onChange={(event) => setLinkType(event.target.value as InternalLinkIntent["relationship_type"])}>
                <option value="conversion">Conversion</option>
                <option value="hierarchy">Hierarchy</option>
                <option value="related_content">Related content</option>
                <option value="supporting_information">Supporting information</option>
              </select>
            </label>
            <label>
              <span>Purpose</span>
              <input value={linkPurpose} onChange={(event) => setLinkPurpose(event.target.value)} />
            </label>
            <label>
              <span>Anchor guidance</span>
              <input value={anchorGuidance} onChange={(event) => setAnchorGuidance(event.target.value)} />
            </label>
            <button className="primaryButton" disabled={busy || !linkSourceId || !linkTargetId || !linkPurpose.trim()} onClick={addInternalLink}>
              Add Proposed Link
            </button>
          </div>
          <div className="connectionRecordList">
            {connections.internal_link_intents.map((intent) => (
              <div className="connectionRecord" key={intent.id}>
                <div>
                  <strong>{pageName(intent.source_planned_page_id)} → {pageName(intent.target_planned_page_id)}</strong>
                  <p>{intent.relationship_type}: {intent.purpose}</p>
                </div>
                <select
                  aria-label={`Approval state for internal link ${intent.id}`}
                  value={intent.approval_state}
                  disabled={busy}
                  onChange={(event) =>
                    updateInternalLink(
                      intent,
                      event.target.value as InternalLinkIntent["approval_state"]
                    )
                  }
                >
                  <option value="proposed">Proposed</option>
                  <option value="approved">Approved</option>
                  <option value="rejected">Rejected</option>
                </select>
                <button className="iconButton" disabled={busy} onClick={() => removeInternalLink(intent.id)} aria-label={`Remove internal link ${intent.id}`}>
                  <Trash2 size={16} aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}

function NavigationItemEditor({
  item,
  items,
  pageName,
  disabled,
  onSaved,
  onError,
  onRemove
}: {
  item: NavigationItem;
  items: NavigationItem[];
  pageName: (id: number) => string;
  disabled: boolean;
  onSaved: () => Promise<void>;
  onError: (message: string) => void;
  onRemove: () => void;
}) {
  const [label, setLabel] = useState(item.label);
  const [position, setPosition] = useState(String(item.position));
  const [parentId, setParentId] = useState(String(item.parent_navigation_item_id ?? ""));
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await apiRequest(`/api/site-plans/navigation-items/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          label,
          position: Number(position) || 0,
          parent_navigation_item_id: numberOrNull(parentId)
        })
      });
      await onSaved();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Unable to update navigation item.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="connectionRecord navigationRecord">
      <div>
        <strong>{pageName(item.target_planned_page_id)}</strong>
        <small>Navigation Item #{item.id}</small>
      </div>
      <input aria-label={`Label for navigation item ${item.id}`} value={label} onChange={(event) => setLabel(event.target.value)} />
      <input aria-label={`Position for navigation item ${item.id}`} type="number" min="0" value={position} onChange={(event) => setPosition(event.target.value)} />
      <select aria-label={`Parent for navigation item ${item.id}`} value={parentId} onChange={(event) => setParentId(event.target.value)}>
        <option value="">Top level</option>
        {items.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.label}</option>)}
      </select>
      <button className="secondaryButton buttonWithIcon" disabled={disabled || saving} onClick={save}>
        <Save size={15} aria-hidden="true" /> Save
      </button>
      <button className="iconButton" disabled={disabled || saving} onClick={onRemove} aria-label={`Remove navigation item ${item.id}`}>
        <Trash2 size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

function WebsiteReadinessPanel({ report }: { report: WebsiteReadinessReport }) {
  return (
    <section className="panel websiteReadinessPanel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Website-Scoped Review</p>
          <h2>Website Readiness</h2>
          <p>Current review dimensions are evaluated independently from deferred future systems.</p>
        </div>
        <span className={`readinessStatus ${report.review_ready ? "ready" : "needs_attention"}`}>
          {report.review_ready ? "Review ready" : "Needs attention"}
        </span>
      </div>
      <div className="readinessCategoryGrid">
        {report.categories.map((category) => (
          <article className="readinessCategory" key={category.key}>
            <div className="readinessCategoryHeader">
              <h3>{category.label}</h3>
              <span className={`readinessStatus ${category.status}`}>
                {humanizeReadiness(category.status)}
              </span>
            </div>
            <ul className="readinessItemList">
              {category.items.map((item) => (
                <li key={item.key}>
                  <div>
                    <strong>{item.label}</strong>
                    <span className={`readinessStatus ${item.status}`}>
                      {humanizeReadiness(item.status)}
                    </span>
                  </div>
                  <p>{item.message}</p>
                  {item.affected_planned_page_ids.length > 0 && (
                    <small>Planned Page IDs: {item.affected_planned_page_ids.join(", ")}</small>
                  )}
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  );
}

function humanizeReadiness(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function CompositionFoundationPanel({
  plan,
  compositions,
  working,
  setWorking,
  reload,
  reportMessage
}: {
  plan: SitePlanDetail;
  compositions: PageComposition[];
  working: boolean;
  setWorking: (value: boolean) => void;
  reload: () => Promise<void>;
  reportMessage: (message: string) => void;
}) {
  async function refresh() {
    setWorking(true);
    try {
      const result = await apiRequest<SitePlanCompositionRefreshResult>(
        `/api/site-plans/${plan.id}/compositions/refresh`,
        { method: "POST" }
      );
      reportMessage(
        `Semantic compositions: ${result.created} created, ${result.refreshed} refreshed, ` +
        `${result.unchanged} unchanged, ${result.blocked.length} blocked.`
      );
      await reload();
    } catch (error) {
      reportMessage(error instanceof Error ? error.message : "Unable to refresh semantic compositions.");
    } finally {
      setWorking(false);
    }
  }

  const generatedCount = plan.planned_pages.filter((page) => page.generated_page_id).length;
  const current = compositions.filter(
    (item) => item.status === "current" && item.validation_errors.length === 0
  );
  return (
    <section className="panel compositionFoundationPanel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Reusable Presentation Layer</p>
          <h2>Semantic Page Compositions</h2>
          <p>
            Atlas suggestions remain separate from operator decisions and bind to exact
            Website Context, draft, navigation, and internal-link sources.
          </p>
        </div>
        <span className={`readinessStatus ${current.length === generatedCount ? "ready" : "needs_attention"}`}>
          {current.length} of {generatedCount} current
        </span>
      </div>
      <div className="panelActions">
        <button className="secondaryButton buttonWithIcon" disabled={working} onClick={refresh}>
          <RefreshCw size={16} aria-hidden="true" /> Refresh compositions
        </button>
      </div>
      <div className="compositionSummaryGrid">
        {compositions.map((composition) => {
          const page = plan.planned_pages.find((item) => item.id === composition.planned_page_id);
          return (
            <article key={composition.id}>
              <strong>{page?.working_name ?? `Planned Page ${composition.planned_page_id}`}</strong>
              <span>{composition.effective_components.length} semantic components</span>
              <span>{composition.operator_decisions.length} operator decision(s)</span>
              <span className={`readinessStatus ${composition.validation_errors.length ? "needs_attention" : "ready"}`}>
                {composition.validation_errors.length ? "Stale or invalid" : "Current"}
              </span>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function DraftSummary({ draft }: { draft: Record<string, unknown> }) {
  const sections = Array.isArray(draft.sections)
    ? draft.sections as Array<{ key?: string; heading?: string; body?: string }>
    : [];
  const faqs = Array.isArray(draft.faq_items) ? draft.faq_items : [];
  return (
    <div className="planningRecommendations">
      <strong>Reviewable draft</strong>
      <p><strong>{String(draft.h1 ?? draft.title ?? "Untitled draft")}</strong></p>
      <p>{String(draft.intro ?? "")}</p>
      {sections.length > 0 && (
        <ul>
          {sections.map((section) => (
            <li key={section.key ?? section.heading}>
              <strong>{section.heading ?? section.key}</strong>: {section.body}
            </li>
          ))}
        </ul>
      )}
      {faqs.length > 0 && (
        <p>{faqs.length} approved FAQ item{faqs.length === 1 ? "" : "s"} included.</p>
      )}
    </div>
  );
}

function readinessLabel(page: PlannedPage) {
  if (page.draft_readiness.status === "ready") return "Ready to draft";
  if (page.draft_readiness.status === "unsupported") return "Drafting deferred";
  return "Draft blocked";
}

function readinessTone(page: PlannedPage) {
  if (page.draft_readiness.status === "ready") return "high";
  if (page.draft_readiness.status === "unsupported") return "medium";
  return "low";
}

function RelationSelect({
  label,
  value,
  options,
  onChange
}: {
  label: string;
  value: string;
  options: Array<[number, string]>;
  onChange: (value: string) => void;
}) {
  return (
    <label>
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">None</option>
        {options.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select>
    </label>
  );
}

function answerText(page: PlannedPage, key: string) {
  return String(page.planning_record.effective_answers[key] ?? "Not yet determined.");
}

function answerList(page: PlannedPage, key: string) {
  const value = page.planning_record.effective_answers[key];
  return Array.isArray(value) ? value.join(", ") : String(value ?? "Not yet determined.");
}

function relationshipText(page: PlannedPage) {
  const value = page.planning_record.effective_answers.relationships;
  if (!Array.isArray(value)) return "Website";
  return value
    .map((item) => {
      const relation = item as { type?: string; name?: string; id?: number };
      return `${relation.type ?? "relationship"}: ${relation.name ?? `#${relation.id}`}`;
    })
    .join(" · ");
}

function requiredFactsText(page: PlannedPage) {
  const value = page.planning_record.effective_answers.required_facts;
  if (!Array.isArray(value)) return "Not yet determined.";
  return value
    .map((item) => {
      const fact = item as { key?: string; available?: boolean };
      return `${String(fact.key ?? "fact").replace(/_/g, " ")}: ${fact.available ? "available" : "missing"}`;
    })
    .join(", ");
}

function operatorOverridesText(page: PlannedPage) {
  const entries = Object.entries(page.planning_record.operator_overrides);
  if (!entries.length) return "No operator overrides.";
  return entries
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
    .join(" · ");
}

function labelForPageType(value: PageType) {
  return PAGE_TYPES.find((item) => item.value === value)?.label ?? value;
}

function numberOrNull(value: string) {
  return value ? Number(value) : null;
}
