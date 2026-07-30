import { useState } from "react";
import { RefreshCw } from "lucide-react";

import { apiRequest } from "../api";
import type {
  CoverageDecisionStatus,
  CoverageInventoryPreview,
  CoveragePolicy
} from "../types";

type Candidate = Record<string, unknown>;
type DecisionDraft = {
  status: CoverageDecisionStatus;
  rationale: string;
  decided_by: string;
  page_appropriate?: boolean;
};

const EMPTY_DECISION: DecisionDraft = {
  status: "included",
  rationale: "",
  decided_by: ""
};

export default function CoveragePlanningPanel({
  planId,
  policy,
  inventory,
  working,
  reload,
  reportMessage
}: {
  planId: number;
  policy: CoveragePolicy;
  inventory: CoverageInventoryPreview;
  working: boolean;
  reload: () => Promise<void>;
  reportMessage: (message: string) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, DecisionDraft>>({});
  const [busy, setBusy] = useState(false);

  function draft(key: string, existing?: Partial<DecisionDraft>) {
    return drafts[key] ?? { ...EMPTY_DECISION, ...existing };
  }

  function updateDraft(
    key: string,
    change: Partial<DecisionDraft>,
    existing?: Partial<DecisionDraft>
  ) {
    setDrafts((current) => ({
      ...current,
      [key]: { ...draft(key, existing), ...change }
    }));
  }

  async function saveDecision(
    key: string,
    path: string,
    existing?: Partial<DecisionDraft>,
    county = false
  ) {
    const value = draft(key, existing);
    if (!value.decided_by.trim()) {
      reportMessage("Operator provenance is required for every coverage decision.");
      return;
    }
    setBusy(true);
    try {
      await apiRequest(`/api/site-plans/${planId}/coverage/${path}`, {
        method: "PUT",
        body: JSON.stringify({
          status: value.status,
          rationale: value.rationale.trim() || null,
          decided_by: value.decided_by.trim(),
          ...(county ? { page_appropriate: Boolean(value.page_appropriate) } : {})
        })
      });
      setDrafts((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      await reload();
      reportMessage("Coverage decision saved with operator provenance.");
    } catch (error) {
      reportMessage(error instanceof Error ? error.message : "Unable to save coverage decision.");
    } finally {
      setBusy(false);
    }
  }

  async function refreshCandidates() {
    setBusy(true);
    try {
      await apiRequest(`/api/site-plans/${planId}/coverage/candidates/refresh`, {
        method: "POST"
      });
      await reload();
      reportMessage("Atlas coverage candidates refreshed; operator decisions were unchanged.");
    } catch (error) {
      reportMessage(error instanceof Error ? error.message : "Unable to refresh candidates.");
    } finally {
      setBusy(false);
    }
  }

  async function reconcile() {
    setBusy(true);
    try {
      const result = await apiRequest<{ created_count: number }>(
        `/api/site-plans/${planId}/coverage/reconcile`,
        { method: "POST" }
      );
      await reload();
      reportMessage(
        result.created_count
          ? `${result.created_count} missing Planned Page record(s) created without drafts or content.`
          : "Coverage inventory already matches; reconciliation was idempotent."
      );
    } catch (error) {
      reportMessage(error instanceof Error ? error.message : "Unable to reconcile coverage.");
    } finally {
      setBusy(false);
    }
  }

  const disabled = working || busy;
  const counts = inventory.counts;

  return (
    <section className="panel coveragePlanningPanel">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Approved coverage matrix</p>
          <h2>Expected Website inventory</h2>
          <p>
            Atlas candidates remain separate from explicit operator decisions. Reconciliation
            creates only missing Planned Pages and Planning Records.
          </p>
        </div>
        <button className="secondaryButton" disabled={disabled} onClick={refreshCandidates}>
          <RefreshCw size={16} /> Refresh candidates
        </button>
      </div>

      <div className="coverageCountGrid">
        {Object.entries(counts).map(([key, value]) => (
          <div key={key}>
            <strong>{value}</strong>
            <span>{key.replace(/_/g, " ")}</span>
          </div>
        ))}
      </div>

      <CoverageDecisionGroup
        title="Services"
        candidates={policy.planning_record.generated_service_candidates}
        keyFor={(item) => `service:${numberValue(item.service_id)}`}
        labelFor={(item) => stringValue(item.service_name)}
        existingFor={(item) => {
          const found = policy.service_decisions.find(
            (decision) => decision.service_id === numberValue(item.service_id)
          );
          return found
            ? {
                status: found.status,
                rationale: found.rationale ?? "",
                decided_by: found.decided_by
              }
            : undefined;
        }}
        draft={draft}
        updateDraft={updateDraft}
        save={(item, key, existing) =>
          saveDecision(key, `services/${numberValue(item.service_id)}`, existing)
        }
        disabled={disabled}
      />

      <CoverageDecisionGroup
        title="Counties and county-page appropriateness"
        candidates={policy.planning_record.generated_county_candidates}
        keyFor={(item) => `county:${numberValue(item.county_id)}`}
        labelFor={(item) => `${stringValue(item.county_name)}, ${stringValue(item.state)}`}
        existingFor={(item) => {
          const found = policy.county_decisions.find(
            (decision) => decision.county_id === numberValue(item.county_id)
          );
          return found
            ? {
                status: found.status,
                rationale: found.rationale ?? "",
                decided_by: found.decided_by,
                page_appropriate: found.page_appropriate
              }
            : { page_appropriate: false };
        }}
        draft={draft}
        updateDraft={updateDraft}
        save={(item, key, existing) =>
          saveDecision(key, `counties/${numberValue(item.county_id)}`, existing, true)
        }
        disabled={disabled}
        county
      />

      <CoverageDecisionGroup
        title="Cities"
        candidates={policy.planning_record.generated_city_candidates}
        keyFor={(item) => `city:${numberValue(item.city_id)}`}
        labelFor={(item) => `${stringValue(item.city_name)}, ${stringValue(item.state)}`}
        existingFor={(item) => {
          const found = policy.city_decisions.find(
            (decision) => decision.city_id === numberValue(item.city_id)
          );
          return found
            ? {
                status: found.status,
                rationale: found.rationale ?? "",
                decided_by: found.decided_by
              }
            : undefined;
        }}
        draft={draft}
        updateDraft={updateDraft}
        save={(item, key, existing) =>
          saveDecision(key, `cities/${numberValue(item.city_id)}`, existing)
        }
        disabled={disabled}
      />

      <CoverageDecisionGroup
        title="Explicit Service × City combinations"
        candidates={policy.planning_record.generated_matrix_candidates}
        keyFor={(item) =>
          `matrix:${numberValue(item.service_id)}:${numberValue(item.city_id)}`
        }
        labelFor={(item) =>
          `${stringValue(item.service_name)} × ${stringValue(item.city_name)}`
        }
        existingFor={(item) => {
          const found = policy.matrix_decisions.find(
            (decision) =>
              decision.service_id === numberValue(item.service_id) &&
              decision.city_id === numberValue(item.city_id)
          );
          return found
            ? {
                status: found.status,
                rationale: found.rationale ?? "",
                decided_by: found.decided_by
              }
            : undefined;
        }}
        draft={draft}
        updateDraft={updateDraft}
        save={(item, key, existing) =>
          saveDecision(
            key,
            `services/${numberValue(item.service_id)}/cities/${numberValue(item.city_id)}`,
            existing
          )
        }
        disabled={disabled}
      />

      <div className="coverageInventoryList">
        <h3>Deterministic inventory preview</h3>
        {inventory.items.map((item) => (
          <article key={`${item.inventory_key}:${item.disposition}:${item.planned_page_id ?? ""}`}>
            <div>
              <strong>{item.working_name}</strong>
              <code>/{item.intended_slug}</code>
            </div>
            <span className={`readinessStatus ${inventoryTone(item.disposition)}`}>
              {item.disposition.replace(/_/g, " ")}
            </span>
            <p>{item.reason}</p>
          </article>
        ))}
      </div>

      {inventory.blocking_reasons.map((reason) => (
        <p className="formError" key={reason}>{reason}</p>
      ))}
      <button
        className="primaryButton"
        disabled={disabled || !inventory.reconciliation_ready}
        onClick={reconcile}
      >
        Reconcile missing Planned Pages
      </button>
    </section>
  );
}

function CoverageDecisionGroup({
  title,
  candidates,
  keyFor,
  labelFor,
  existingFor,
  draft,
  updateDraft,
  save,
  disabled,
  county = false
}: {
  title: string;
  candidates: Candidate[];
  keyFor: (item: Candidate) => string;
  labelFor: (item: Candidate) => string;
  existingFor: (item: Candidate) => Partial<DecisionDraft> | undefined;
  draft: (key: string, existing?: Partial<DecisionDraft>) => DecisionDraft;
  updateDraft: (
    key: string,
    change: Partial<DecisionDraft>,
    existing?: Partial<DecisionDraft>
  ) => void;
  save: (item: Candidate, key: string, existing?: Partial<DecisionDraft>) => void;
  disabled: boolean;
  county?: boolean;
}) {
  return (
    <div className="coverageDecisionGroup">
      <h3>{title}</h3>
      {candidates.length === 0 && <p>No current Atlas candidates.</p>}
      {candidates.map((item) => {
        const key = keyFor(item);
        const existing = existingFor(item);
        const value = draft(key, existing);
        return (
          <div className="coverageDecisionRow" key={key}>
            <div className="coverageCandidateIdentity">
              <strong>{labelFor(item)}</strong>
              <small>
                Atlas candidate: {stringValue(item.atlas_candidate_state) || "eligible"}
              </small>
            </div>
            <select
              value={value.status}
              onChange={(event) =>
                updateDraft(
                  key,
                  { status: event.target.value as CoverageDecisionStatus },
                  existing
                )
              }
            >
              <option value="included">Included</option>
              <option value="excluded">Excluded</option>
              <option value="deferred">Deferred</option>
            </select>
            {county && (
              <label className="checkboxLabel">
                <input
                  type="checkbox"
                  checked={Boolean(value.page_appropriate)}
                  onChange={(event) =>
                    updateDraft(
                      key,
                      { page_appropriate: event.target.checked },
                      existing
                    )
                  }
                />
                County page appropriate
              </label>
            )}
            <input
              value={value.rationale}
              placeholder="Decision rationale"
              onChange={(event) =>
                updateDraft(key, { rationale: event.target.value }, existing)
              }
            />
            <input
              value={value.decided_by}
              placeholder="Operator name"
              onChange={(event) =>
                updateDraft(key, { decided_by: event.target.value }, existing)
              }
            />
            <button
              className="secondaryButton"
              disabled={disabled}
              onClick={() => save(item, key, existing)}
            >
              Save decision
            </button>
          </div>
        );
      })}
    </div>
  );
}

function numberValue(value: unknown) {
  return typeof value === "number" ? value : Number(value);
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : String(value ?? "");
}

function inventoryTone(disposition: string) {
  if (disposition === "matching") return "ready";
  if (disposition === "excluded" || disposition === "deferred") return "deferred";
  return "needs_attention";
}
