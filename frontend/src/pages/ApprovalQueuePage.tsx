import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Download,
  Eye,
  FileClock,
  FileJson,
  ImageOff,
  Monitor,
  Pencil,
  ShieldCheck
} from "lucide-react";
import { Link } from "react-router-dom";

import { apiRequest, requestBulkPageExport } from "../api";
import type { ApprovalQueueItem, ApprovalQueueResponse, BulkExportPreview, QABatchResponse } from "../types";

type QueueFilter =
  | "all"
  | "ready"
  | "blocked"
  | "needs_review"
  | "edited"
  | "approved"
  | "missing_media"
  | "not_run";

type SortKey = "city" | "county" | "qa_status" | "qa_checked_at" | "revision_count" | "last_reviewed_at";

const filterOptions: { value: QueueFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "ready", label: "Ready for approval" },
  { value: "blocked", label: "Blocked" },
  { value: "needs_review", label: "Needs review" },
  { value: "edited", label: "Edited since QA" },
  { value: "approved", label: "Approved not published" },
  { value: "missing_media", label: "Missing media" },
  { value: "not_run", label: "QA not run" }
];

function ApprovalQueuePage() {
  const [queue, setQueue] = useState<ApprovalQueueResponse>({ total_count: 0, items: [] });
  const [filter, setFilter] = useState<QueueFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("city");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [exportWorking, setExportWorking] = useState(false);
  const [exportPreview, setExportPreview] = useState<BulkExportPreview | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadQueue() {
    setLoading(true);
    setError(null);
    try {
      setQueue(await apiRequest<ApprovalQueueResponse>("/api/generated-pages/approval-queue"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load the approval queue.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadQueue();
  }, []);

  const visibleItems = useMemo(
    () => queue.items.filter((item) => matchesFilter(item, filter)).sort(sorters[sortKey]),
    [queue.items, filter, sortKey]
  );

  const counts = useMemo(
    () => ({
      ready: queue.items.filter((item) => item.is_ready_for_approval).length,
      blocked: queue.items.filter((item) => item.has_blockers).length,
      warnings: queue.items.filter((item) => item.has_warnings).length,
      edited: queue.items.filter((item) => item.edited_since_last_qa).length,
      approved: queue.items.filter((item) => item.approved_but_unpublished).length,
      notRun: queue.items.filter((item) => item.qa_status === "not_run").length
    }),
    [queue.items]
  );

  function toggleSelected(pageId: number) {
    setExportPreview(null);
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(pageId)) next.delete(pageId);
      else next.add(pageId);
      return next;
    });
  }

  function toggleVisible() {
    setExportPreview(null);
    const visibleIds = visibleItems.map((item) => item.page_id);
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
    setSelectedIds((current) => {
      const next = new Set(current);
      visibleIds.forEach((id) => (allVisibleSelected ? next.delete(id) : next.add(id)));
      return next;
    });
  }

  async function runSelectedQa() {
    if (selectedIds.size === 0) return;
    setWorking(true);
    setError(null);
    setMessage(null);
    try {
      const result = await apiRequest<QABatchResponse>("/api/generated-pages/qa/batch-run", {
        method: "POST",
        body: JSON.stringify({ page_ids: Array.from(selectedIds), confirm: true })
      });
      setMessage(`QA updated for ${result.saved_count} selected page${result.saved_count === 1 ? "" : "s"}.`);
      setSelectedIds(new Set());
      await loadQueue();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to run QA for selected pages.");
    } finally {
      setWorking(false);
    }
  }

  async function runPageQa(item: ApprovalQueueItem) {
    setWorking(true);
    setError(null);
    setMessage(null);
    try {
      await apiRequest(`/api/generated-pages/${item.page_id}/qa/run`, { method: "POST" });
      setMessage(`QA updated for ${item.city_name}.`);
      await loadQueue();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to run page QA.");
    } finally {
      setWorking(false);
    }
  }

  async function previewSelectedExports() {
    if (selectedIds.size === 0) return;
    setExportWorking(true);
    setError(null);
    setMessage(null);
    try {
      setExportPreview(
        await apiRequest<BulkExportPreview>("/api/generated-pages/export/bulk-preview", {
          method: "POST",
          body: JSON.stringify({ page_ids: Array.from(selectedIds) })
        })
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to preview selected exports.");
    } finally {
      setExportWorking(false);
    }
  }

  async function downloadSelectedExports() {
    if (selectedIds.size === 0) return;
    setExportWorking(true);
    setError(null);
    try {
      const download = await requestBulkPageExport(Array.from(selectedIds));
      downloadBlob(download.blob, download.fileName);
      setMessage(`${download.fileName} downloaded. No media binaries were included.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to download selected exports.");
    } finally {
      setExportWorking(false);
    }
  }

  const allVisibleSelected =
    visibleItems.length > 0 && visibleItems.every((item) => selectedIds.has(item.page_id));

  return (
    <section className="page approvalQueuePage">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Publishing readiness</p>
          <h1>Approval Queue</h1>
        </div>
        <div className="headerActions">
          <button className="secondaryButton buttonWithIcon" type="button" disabled={selectedIds.size === 0 || exportWorking} onClick={previewSelectedExports}>
            <FileJson size={17} aria-hidden="true" /> Preview Exports
          </button>
          <button className="secondaryButton buttonWithIcon" type="button" disabled={selectedIds.size === 0 || exportWorking} onClick={downloadSelectedExports}>
            <Download size={17} aria-hidden="true" /> Download Export ZIP
          </button>
          <button
            className="primaryButton buttonWithIcon"
            type="button"
            disabled={selectedIds.size === 0 || working}
            onClick={runSelectedQa}
          >
            <ShieldCheck size={17} aria-hidden="true" />
            {working ? "Running QA..." : `Run QA on selected (${selectedIds.size})`}
          </button>
        </div>
      </header>
      <p className="helperText">
        Review readiness across generated pages. This workspace cannot approve or publish pages.
      </p>

      {error && <div className="alert">{error}</div>}
      {message && <div className="successMessage">{message}</div>}

      {exportPreview && (
        <section className="panel exportBulkPreview">
          <div className="panelHeader">
            <div><h2>Selected Export Preview</h2><p>Review-only packages. Downloading does not approve or publish pages.</p></div>
            <button className="primaryButton buttonWithIcon" type="button" disabled={exportWorking} onClick={downloadSelectedExports}>
              <Download size={16} aria-hidden="true" /> Download {exportPreview.selected_count} JSON Packages
            </button>
          </div>
          <div className="batchSummary">
            <span>Selected: {exportPreview.selected_count}</span>
            <span className="ready">Export ready: {exportPreview.export_ready_count}</span>
            <span className="needs_review">Warnings: {exportPreview.warning_count}</span>
            <span className="blocked">Blockers: {exportPreview.blocker_count}</span>
          </div>
          <div className="exportBulkCandidates">
            {exportPreview.candidates.map((candidate) => (
              <div key={candidate.page_id}>
                <strong>{candidate.page_title}</strong>
                <code>{candidate.url_slug}</code>
                <span>{candidate.blocker_count} blockers · {candidate.warning_count} warnings</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="queueSummaryGrid" aria-label="Approval queue summary">
        <QueueSummary label="Ready" value={counts.ready} tone="ready" />
        <QueueSummary label="Blocked" value={counts.blocked} tone="blocked" />
        <QueueSummary label="Warnings" value={counts.warnings} tone="warning" />
        <QueueSummary label="Edited since QA" value={counts.edited} tone="edited" />
        <QueueSummary label="Approved not published" value={counts.approved} tone="approved" />
        <QueueSummary label="QA not run" value={counts.notRun} tone="neutral" />
      </div>

      <section className="panel queueControls" aria-label="Queue filters and sorting">
        <div className="queueFilterTabs" role="tablist" aria-label="Readiness filter">
          {filterOptions.map((option) => (
            <button
              key={option.value}
              className={filter === option.value ? "active" : ""}
              type="button"
              role="tab"
              aria-selected={filter === option.value}
              onClick={() => setFilter(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <label className="queueSort">
          <span>Sort by</span>
          <select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)}>
            <option value="city">City</option>
            <option value="county">County</option>
            <option value="qa_status">QA status</option>
            <option value="qa_checked_at">Last QA checked</option>
            <option value="revision_count">Revision count</option>
            <option value="last_reviewed_at">Last reviewed</option>
          </select>
        </label>
      </section>

      <section className="panel queueTablePanel">
        <div className="panelHeader">
          <div>
            <h2>{visibleItems.length} pages</h2>
            <p>{selectedIds.size} selected for QA or review-only export actions.</p>
          </div>
        </div>
        {loading ? (
          <p>Loading approval queue...</p>
        ) : visibleItems.length === 0 ? (
          <p>No pages match this readiness filter.</p>
        ) : (
          <div className="tableWrap">
            <table className="queueTable">
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      aria-label="Select all visible pages"
                      checked={allVisibleSelected}
                      onChange={toggleVisible}
                    />
                  </th>
                  <th>Page</th>
                  <th>Readiness</th>
                  <th>QA / Review</th>
                  <th>History</th>
                  <th>Next action</th>
                  <th>Quick links</th>
                </tr>
              </thead>
              <tbody>
                {visibleItems.map((item) => (
                  <tr key={item.page_id}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Select ${item.city_name}`}
                        checked={selectedIds.has(item.page_id)}
                        onChange={() => toggleSelected(item.page_id)}
                      />
                    </td>
                    <td className="queuePageIdentity">
                      <strong>{item.city_name}</strong>
                      <span>{item.county_name}</span>
                      <small>{item.service_name}</small>
                      <small>Page: {humanize(item.page_status)}</small>
                    </td>
                    <td>
                      <div className="queueBadges">
                        {item.is_ready_for_approval && <QueueBadge tone="ready" label="Ready" />}
                        {item.has_blockers && <QueueBadge tone="blocked" label="Blocked" />}
                        {item.has_warnings && <QueueBadge tone="warning" label="Warning" />}
                        {item.edited_since_last_qa && <QueueBadge tone="edited" label="Edited since QA" />}
                        {item.missing_media && <QueueBadge tone="media" label="Missing Media" />}
                        {item.approved_but_unpublished && (
                          <QueueBadge tone="approved" label="Approved Not Published" />
                        )}
                        {item.qa_status === "not_run" && <QueueBadge tone="neutral" label="QA Not Run" />}
                      </div>
                    </td>
                    <td className="queueDetailCell">
                      <span>QA: {humanize(item.qa_status)}</span>
                      <small>{item.qa_checked_at ? formatDate(item.qa_checked_at) : "Never checked"}</small>
                      <span className={`heroStatus ${item.hero_image_status}`}>
                        {item.hero_image_status === "reviewed" ? (
                          <CheckCircle2 size={14} aria-hidden="true" />
                        ) : (
                          <ImageOff size={14} aria-hidden="true" />
                        )}
                        Hero: {humanize(item.hero_image_status)}
                      </span>
                      <small>Reviewed: {item.last_reviewed_at ? formatDate(item.last_reviewed_at) : "Not recorded"}</small>
                      {item.internal_notes_snippet && <em>{item.internal_notes_snippet}</em>}
                    </td>
                    <td className="queueDetailCell">
                      <span>{item.revision_count} revisions</span>
                      <span>{item.approval_history_count} approvals</span>
                    </td>
                    <td className="queueNextAction">{item.next_recommended_action}</td>
                    <td>
                      <div className="queueQuickLinks">
                        <Link to={`/generated-pages/${item.page_id}/preview`} title="Open customer preview">
                          <Eye size={15} aria-hidden="true" /> Preview
                        </Link>
                        <Link to={`/generated-pages/${item.page_id}/preview?qa=1`} title="Open internal QA preview">
                          <Monitor size={15} aria-hidden="true" /> Internal Preview
                        </Link>
                        {item.page_status === "draft" && (
                          <Link to={`/generated-pages?page=${item.page_id}&action=edit`}>
                            <Pencil size={15} aria-hidden="true" /> Edit Draft
                          </Link>
                        )}
                        <Link to={`/generated-pages?page=${item.page_id}&action=issues`}>
                          <ClipboardList size={15} aria-hidden="true" /> View Issues
                        </Link>
                        <button type="button" disabled={working} onClick={() => runPageQa(item)}>
                          <ShieldCheck size={15} aria-hidden="true" /> Run QA
                        </button>
                        <Link to={`/generated-pages?page=${item.page_id}&action=history`}>
                          <FileClock size={15} aria-hidden="true" /> Approval History
                        </Link>
                        <Link to={`/generated-pages/${item.page_id}/export`}>
                          <FileJson size={15} aria-hidden="true" /> View Export Package
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}

function QueueSummary({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className={`queueSummary ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function QueueBadge({ label, tone }: { label: string; tone: string }) {
  return (
    <span className={`queueBadge ${tone}`}>
      {tone === "blocked" || tone === "warning" ? (
        <AlertTriangle size={13} aria-hidden="true" />
      ) : (
        <CheckCircle2 size={13} aria-hidden="true" />
      )}
      {label}
    </span>
  );
}

function matchesFilter(item: ApprovalQueueItem, filter: QueueFilter) {
  if (filter === "ready") return item.is_ready_for_approval;
  if (filter === "blocked") return item.has_blockers;
  if (filter === "needs_review") return item.has_warnings || item.qa_status === "needs_review";
  if (filter === "edited") return item.edited_since_last_qa;
  if (filter === "approved") return item.approved_but_unpublished;
  if (filter === "missing_media") return item.missing_media;
  if (filter === "not_run") return item.qa_status === "not_run";
  return true;
}

const sorters: Record<SortKey, (left: ApprovalQueueItem, right: ApprovalQueueItem) => number> = {
  city: (left, right) => left.city_name.localeCompare(right.city_name),
  county: (left, right) =>
    left.county_name.localeCompare(right.county_name) || left.city_name.localeCompare(right.city_name),
  qa_status: (left, right) =>
    left.qa_status.localeCompare(right.qa_status) || left.city_name.localeCompare(right.city_name),
  qa_checked_at: (left, right) => dateValue(left.qa_checked_at) - dateValue(right.qa_checked_at),
  revision_count: (left, right) => right.revision_count - left.revision_count,
  last_reviewed_at: (left, right) => dateValue(left.last_reviewed_at) - dateValue(right.last_reviewed_at)
};

function dateValue(value?: string | null) {
  return value ? new Date(value).getTime() : Number.MAX_SAFE_INTEGER;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}

function downloadBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default ApprovalQueuePage;
