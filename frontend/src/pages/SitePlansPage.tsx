import { useEffect, useMemo, useState } from "react";
import { ClipboardList, FilePlus2, RefreshCw, Save } from "lucide-react";

import { apiRequest } from "../api";
import type {
  City,
  County,
  PageType,
  PlannedPage,
  Service,
  SitePlan,
  SitePlanDetail,
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
        const [detail, readinessReport] = await Promise.all([
          apiRequest<SitePlanDetail>(`/api/site-plans/${rows[0].id}`),
          apiRequest<WebsiteReadinessReport>(`/api/site-plans/${rows[0].id}/readiness`)
        ]);
        setPlan(detail);
        setReadiness(readinessReport);
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
