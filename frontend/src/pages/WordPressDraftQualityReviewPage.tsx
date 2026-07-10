import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  FileSearch,
  RefreshCw,
  ShieldCheck
} from "lucide-react";
import { Link } from "react-router-dom";

import { apiRequest } from "../api";
import type {
  WordPressDraftQualityReviewItem,
  WordPressDraftQualityReviewList,
  WordPressManualQualityReviewStatus,
  WordPressQualityCheck
} from "../types";

function WordPressDraftQualityReviewPage() {
  const [list, setList] = useState<WordPressDraftQualityReviewList>({
    total_count: 0,
    ready_count: 0,
    needs_review_count: 0,
    blocked_count: 0,
    items: []
  });
  const [selectedPageId, setSelectedPageId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    loadQualityReview();
  }, []);

  async function loadQualityReview() {
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const response = await apiRequest<WordPressDraftQualityReviewList>("/api/wordpress/draft-quality-review");
      setList(response);
      setSelectedPageId((current) => current ?? response.items[0]?.page_id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load WordPress quality review.");
    } finally {
      setLoading(false);
    }
  }

  const selected = useMemo(
    () => list.items.find((item) => item.page_id === selectedPageId) ?? null,
    [list.items, selectedPageId]
  );

  return (
    <section className="page wordpressQualityReviewPage">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Manual draft review</p>
          <h1>WP Quality Review</h1>
          <p>Review the existing WordPress drafts for future publish-worthiness without changing Atlas or WordPress.</p>
        </div>
        <button className="secondaryButton buttonWithIcon" type="button" onClick={loadQualityReview} disabled={loading}>
          <RefreshCw size={16} aria-hidden="true" />
          Refresh
        </button>
      </header>

      <div className="wordpressSafetyNotice">
        <ShieldCheck size={19} aria-hidden="true" />
        <div>
          <strong>Computed checklist with manual notes. This page has no publish, create, update, delete, media upload, or bulk actions.</strong>
          <span>Only manual review status, reviewer notes, reviewer name, and reviewed timestamp are saved in Atlas.</span>
        </div>
      </div>

      {error && <div className="alert">{error}</div>}
      {message && <div className="successAlert">{message}</div>}

      <div className="wordpressReviewSummary">
        <div><span>Drafts</span><strong>{list.total_count}</strong></div>
        <div><span>Ready</span><strong>{list.ready_count}</strong></div>
        <div><span>Needs Review</span><strong>{list.needs_review_count}</strong></div>
        <div><span>Blocked</span><strong>{list.blocked_count}</strong></div>
      </div>

      <section className="panel wordpressDraftListPanel">
        <div className="panelHeader">
          <div>
            <h2>Draft Quality Checklist</h2>
            <p>Computed checks plus manual review prompts for each saved WordPress draft.</p>
          </div>
        </div>

        {loading ? (
          <p>Loading quality checklist...</p>
        ) : list.items.length === 0 ? (
          <p>No WordPress draft references exist yet.</p>
        ) : (
          <div className="responsiveTableWrap">
            <table className="wordpressQualityTable">
              <thead>
                <tr>
                  <th>City</th>
                  <th>Atlas</th>
                  <th>WordPress</th>
                  <th>Slug</th>
                  <th>Checklist</th>
                  <th>Match</th>
                  <th>Review</th>
                </tr>
              </thead>
              <tbody>
                {list.items.map((item) => (
                  <tr key={item.page_id} className={item.page_id === selectedPageId ? "selectedRow" : undefined}>
                    <td>
                      <strong>{item.city || item.page_title}</strong>
                      <span>{item.county || "-"}</span>
                    </td>
                    <td>
                      <Badge label={humanize(item.atlas_status)} tone="muted" />
                      <Badge label={`QA ${humanize(item.qa_status)}`} tone={item.qa_status === "ready" ? "ready" : "warning"} />
                    </td>
                    <td>
                      <div>ID {item.wordpress_post_id}</div>
                      <Badge label={item.wordpress_status || "Unknown"} tone={item.wordpress_status === "draft" ? "ready" : "danger"} />
                      {item.wordpress_url && (
                        <a href={item.wordpress_url} target="_blank" rel="noreferrer">
                          View <ExternalLink size={13} aria-hidden="true" />
                        </a>
                      )}
                    </td>
                    <td><code>{item.slug}</code></td>
                    <td>
                      <div className="qualityCounts">
                        <span className="pass">{item.pass_count} pass</span>
                        <span className="warning">{item.warning_count} warning</span>
                        <span className={item.fail_count ? "fail" : "pass"}>{item.fail_count} fail</span>
                      </div>
                    </td>
                    <td>
                      <Badge
                        label={item.payload_hash_matches_audit ? "Hash Match" : "Hash Mismatch"}
                        tone={item.payload_hash_matches_audit ? "ready" : "danger"}
                      />
                      <Badge
                        label={readinessLabel(item)}
                        tone={readinessTone(item)}
                      />
                    </td>
                    <td>
                      <button className="linkButton" type="button" onClick={() => setSelectedPageId(item.page_id)}>
                        View Checklist
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {selected && (
        <QualityDetail
          item={selected}
          onSaved={(updated) => {
            setList((current) => ({
              ...current,
              items: current.items.map((item) => item.page_id === updated.page_id ? updated : item)
            }));
            setMessage("Manual review notes saved.");
          }}
          onError={setError}
        />
      )}
    </section>
  );
}

function QualityDetail({
  item,
  onSaved,
  onError
}: {
  item: WordPressDraftQualityReviewItem;
  onSaved: (item: WordPressDraftQualityReviewItem) => void;
  onError: (message: string) => void;
}) {
  const [reviewStatus, setReviewStatus] = useState<WordPressManualQualityReviewStatus>(item.manual_review.review_status);
  const [reviewerNotes, setReviewerNotes] = useState(item.manual_review.reviewer_notes ?? "");
  const [reviewedBy, setReviewedBy] = useState(item.manual_review.reviewed_by ?? "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setReviewStatus(item.manual_review.review_status);
    setReviewerNotes(item.manual_review.reviewer_notes ?? "");
    setReviewedBy(item.manual_review.reviewed_by ?? "");
  }, [item]);

  const grouped = item.checklist.reduce<Record<string, WordPressQualityCheck[]>>((acc, check) => {
    acc[check.review_field] = [...(acc[check.review_field] ?? []), check];
    return acc;
  }, {});
  const hasUnsavedChanges =
    reviewStatus !== item.manual_review.review_status ||
    reviewerNotes !== (item.manual_review.reviewer_notes ?? "") ||
    reviewedBy !== (item.manual_review.reviewed_by ?? "");

  async function saveManualReview() {
    setSaving(true);
    onError("");
    try {
      const updated = await apiRequest<WordPressDraftQualityReviewItem>(
        `/api/wordpress/draft-quality-review/${item.page_id}/manual-review`,
        {
          method: "PATCH",
          body: JSON.stringify({
            review_status: reviewStatus,
            reviewer_notes: reviewerNotes,
            reviewed_by: reviewedBy
          })
        }
      );
      onSaved(updated);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Unable to save manual review notes.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel wordpressQualityDetail">
      <div className="panelHeader">
        <div>
          <h2>{item.city} Quality Review</h2>
          <p>{item.page_title}</p>
        </div>
        <div className="badgeStack">
          <Badge label={readinessLabel(item)} tone={readinessTone(item)} />
          <Badge label={item.safe_for_future_manual_review ? "Safe For Manual Review" : "Blocked"} tone={item.safe_for_future_manual_review ? "ready" : "danger"} />
        </div>
      </div>

      <div className="qualityLinkBar">
        {item.wordpress_url && (
          <a className="secondaryButton buttonWithIcon" href={item.wordpress_url} target="_blank" rel="noreferrer">
            <ExternalLink size={16} aria-hidden="true" />
            WordPress Draft
          </a>
        )}
        {item.admin_edit_url && (
          <a className="secondaryButton buttonWithIcon" href={item.admin_edit_url} target="_blank" rel="noreferrer">
            <ExternalLink size={16} aria-hidden="true" />
            Admin Edit Link
          </a>
        )}
        <Link className="secondaryButton buttonWithIcon" to={`/generated-pages/${item.page_id}/preview`}>
          <FileSearch size={16} aria-hidden="true" />
          Atlas Preview
        </Link>
      </div>

      {item.blockers_or_issues.length > 0 && (
        <div className="qualityIssueSummary">
          <AlertTriangle size={18} aria-hidden="true" />
          <div>
            <strong>Review items</strong>
            <ul>
              {item.blockers_or_issues.slice(0, 8).map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <section className="manualQualityReviewForm">
        <div className="panelHeader">
          <div>
            <h3>Manual Review Notes</h3>
            <p>Saved in Atlas only. This does not approve, publish, update WordPress, or change the computed checklist.</p>
          </div>
          {hasUnsavedChanges && <span className="unsavedBadge">Unsaved changes</span>}
        </div>
        <div className="manualQualityFields">
          <label>
            <span>Review status</span>
            <select value={reviewStatus} onChange={(event) => setReviewStatus(event.target.value as WordPressManualQualityReviewStatus)}>
              <option value="not_reviewed">Not reviewed</option>
              <option value="in_review">In review</option>
              <option value="needs_changes">Needs changes</option>
              <option value="ready_for_manual_publish_review">Ready for manual publish review</option>
            </select>
          </label>
          <label>
            <span>Reviewed by</span>
            <input value={reviewedBy} onChange={(event) => setReviewedBy(event.target.value)} placeholder="Optional reviewer name" />
          </label>
          <label className="manualQualityNotes">
            <span>Reviewer notes</span>
            <textarea
              value={reviewerNotes}
              onChange={(event) => setReviewerNotes(event.target.value)}
              placeholder="Add notes from the manual WordPress draft review."
            />
          </label>
        </div>
        <div className="formActions">
          <button className="primaryButton" type="button" onClick={saveManualReview} disabled={saving || !hasUnsavedChanges}>
            {saving ? "Saving..." : "Save Manual Review"}
          </button>
          <span className="helperText manualQualityTimestamp">
            Last reviewed: {formatDateTime(item.manual_review.reviewed_at)}
          </span>
        </div>
      </section>

      <div className="qualityChecklistGroups">
        {Object.entries(grouped).map(([group, checks]) => (
          <article key={group} className="qualityChecklistGroup">
            <h3>{humanize(group)}</h3>
            <div className="qualityChecklist">
              {checks.map((check) => (
                <div key={check.key} className={`qualityCheck ${check.status}`}>
                  {check.status === "pass" ? (
                    <CheckCircle2 size={17} aria-hidden="true" />
                  ) : (
                    <AlertTriangle size={17} aria-hidden="true" />
                  )}
                  <div>
                    <strong>{check.label}</strong>
                    <p>{check.message}</p>
                  </div>
                  <Badge label={check.status} tone={checkTone(check.status)} />
                </div>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function Badge({ label, tone }: { label: string; tone: "ready" | "warning" | "danger" | "muted" }) {
  return <span className={`statusBadge ${tone}`}>{label}</span>;
}

function checkTone(status: WordPressQualityCheck["status"]): "ready" | "warning" | "danger" {
  if (status === "pass") return "ready";
  if (status === "warning") return "warning";
  return "danger";
}

function readinessLabel(item: WordPressDraftQualityReviewItem) {
  return humanize(item.overall_publish_readiness);
}

function readinessTone(item: WordPressDraftQualityReviewItem): "ready" | "warning" | "danger" {
  if (item.overall_publish_readiness === "ready") return "ready";
  if (item.overall_publish_readiness === "blocked") return "danger";
  return "warning";
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDateTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "Not reviewed yet";
}

export default WordPressDraftQualityReviewPage;
