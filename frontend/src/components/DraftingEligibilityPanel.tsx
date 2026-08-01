import { useEffect, useState } from "react";

import { apiRequest } from "../api";
import type {
  DraftingEligibilityManifest,
  WebsiteDraftGenerationRun
} from "../types";

type Props = {
  planId: number;
  websiteId: number;
  manifest: DraftingEligibilityManifest;
  working: boolean;
  reload: () => Promise<void>;
  reportMessage: (message: string) => void;
};

export default function DraftingEligibilityPanel({
  planId,
  websiteId,
  manifest,
  working,
  reload,
  reportMessage
}: Props) {
  const [rationale, setRationale] = useState<Record<number, string>>({});
  const [actor, setActor] = useState<Record<number, string>>({});
  const [generationRun, setGenerationRun] =
    useState<WebsiteDraftGenerationRun | null>(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    void loadLatestRun();
  }, [planId]);

  async function loadLatestRun() {
    try {
      const runs = await apiRequest<WebsiteDraftGenerationRun[]>(
        `/api/site-plans/${planId}/draft-generation/runs`
      );
      setGenerationRun(runs[0] ?? null);
    } catch (error) {
      reportMessage(
        error instanceof Error
          ? error.message
          : "Unable to load Website draft-generation history."
      );
    }
  }

  async function assess() {
    await apiRequest(`/api/site-plans/${planId}/drafting-eligibility/assess`, {
      method: "POST"
    });
    await reload();
    reportMessage("Eligibility refreshed. No drafts or content were created.");
  }

  async function decide(assessmentId: number, decision: string) {
    await apiRequest(
      `/api/site-plans/drafting-eligibility/${assessmentId}/disposition`,
      {
        method: "PUT",
        body: JSON.stringify({
          decision,
          rationale: rationale[assessmentId] ?? "",
          decided_by: actor[assessmentId] ?? "",
          accepted_exception: decision === "exception_approved"
        })
      }
    );
    await reload();
  }

  async function generateEligibleDrafts() {
    setGenerating(true);
    reportMessage("Preparing inventory and evaluating current eligibility...");
    try {
      const result = await apiRequest<WebsiteDraftGenerationRun>(
        `/api/site-plans/${planId}/draft-generation/start`,
        {
          method: "POST",
          body: JSON.stringify({ website_id: websiteId })
        }
      );
      setGenerationRun(result);
      await reload();
      reportMessage(result.progress_message);
    } finally {
      setGenerating(false);
    }
  }

  async function resumeGeneration() {
    if (!generationRun) return;
    setGenerating(true);
    reportMessage(
      `Resuming after ${generationRun.processed_count} of ${generationRun.progress_total}...`
    );
    try {
      const result = await apiRequest<WebsiteDraftGenerationRun>(
        `/api/site-plans/draft-generation/runs/${generationRun.id}/resume`,
        {
          method: "POST",
          body: JSON.stringify({ website_id: websiteId })
        }
      );
      setGenerationRun(result);
      await reload();
      reportMessage(result.progress_message);
    } finally {
      setGenerating(false);
    }
  }

  return (
    <section className="panel eligibilityPanel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Coverage-gated drafting</p>
          <h2>Drafting eligibility and semantic distinctness</h2>
          <p>
            Atlas findings remain separate from operator decisions. Refreshing this
            review never creates drafts.
          </p>
        </div>
        <button className="secondaryButton" disabled={working} onClick={() => void assess()}>
          Refresh assessment
        </button>
      </div>
      <div className="eligibilityCounts">
        {Object.entries(manifest.counts).map(([key, value]) => (
          <span className="countBadge" key={key}>{key}: {value}</span>
        ))}
      </div>
      <p>
        PlannedPage-first batch manifest:{" "}
        <strong>{manifest.batch_manifest.preview_ready ? "ready" : "blocked"}</strong>
      </p>
      <div className="eligibilityCounts">
        {Object.entries(manifest.batch_manifest.counts).map(([key, value]) => (
          <span className="countBadge" key={`batch-${key}`}>{key}: {value}</span>
        ))}
      </div>
      {manifest.batch_manifest.items.map((item) => (
        <p key={item.inventory_key}>
          {item.working_name}: <strong>{item.classification}</strong>
        </p>
      ))}
      <div className="batchGeneration">
        <div className="panelHeader">
          <div>
            <h3>Deterministic Website draft generation</h3>
            <p>
              Creates only currently eligible missing drafts. Existing drafts are
              preserved; blocked, deferred, excluded, stale, unsupported, and
              consolidation candidates are reported without mutation.
            </p>
          </div>
          {generationRun?.status === "interrupted" ? (
            <button
              className="primaryButton"
              disabled={working || generating}
              onClick={() => void resumeGeneration()}
            >
              Resume remaining drafts
            </button>
          ) : (
            <button
              className="primaryButton"
              disabled={
                working ||
                generating ||
                (manifest.batch_manifest.counts.eligible ?? 0) === 0
              }
              onClick={() => void generateEligibleDrafts()}
            >
              Generate eligible drafts
            </button>
          )}
        </div>
        {generationRun && (
          <>
            <p>
              <strong>{generationRun.progress_message}</strong>{" "}
              ({generationRun.processed_count}/{generationRun.progress_total})
            </p>
            <div className="eligibilityCounts">
              {Object.entries(generationRun.counts).map(([key, value]) => (
                <span className="countBadge" key={`generation-${key}`}>
                  {key}: {value}
                </span>
              ))}
            </div>
            <p>
              Run {generationRun.id} · {generationRun.status} ·{" "}
              {generationRun.duration_ms ?? 0} ms
            </p>
          </>
        )}
      </div>
      <div className="eligibilityRows">
        {manifest.assessments.map((item) => (
          <article className="eligibilityRow" key={item.id}>
            <div>
              <strong>Planned Page {item.planned_page_id}</strong>
              <span className={`confidenceBadge ${item.current ? "high" : "low"}`}>
                {item.status}
              </span>
              <p>{item.reasons.join(" ")}</p>
              <small>
                Local evidence: {item.local_value_findings.length}; semantic findings:{" "}
                {item.semantic_findings.length}
              </small>
              {manifest.distinctness_briefs
                .filter((brief) => brief.planned_page_id === item.planned_page_id)
                .map((brief) => (
                  <small key={brief.id}>
                    Intent: {brief.search_intent || "not yet established"}; approved
                    page-specific value: {brief.required_page_specific_value.length}
                  </small>
                ))}
            </div>
            <div className="eligibilityDecision">
              <input
                placeholder="Operator identity"
                value={actor[item.id] ?? ""}
                onChange={(event) =>
                  setActor({ ...actor, [item.id]: event.target.value })
                }
              />
              <textarea
                placeholder="Required rationale"
                value={rationale[item.id] ?? ""}
                onChange={(event) =>
                  setRationale({ ...rationale, [item.id]: event.target.value })
                }
              />
              <div>
                <button onClick={() => void decide(item.id, "accepted")}>Accept</button>
                <button onClick={() => void decide(item.id, "deferred")}>Defer</button>
                <button onClick={() => void decide(item.id, "consolidate")}>Consolidate</button>
                <button onClick={() => void decide(item.id, "exception_approved")}>
                  Approve exception
                </button>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
