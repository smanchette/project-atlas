import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  ExternalLink,
  FileJson,
  LockKeyhole,
  RefreshCw,
  Send
} from "lucide-react";
import { Link } from "react-router-dom";

import { apiRequest } from "../api";
import type {
  WordPressDraftCreateResult,
  WordPressDraftDryRun,
  WordPressDraftQueueGroup,
  WordPressDraftQueueItem,
  WordPressDraftQueueResponse
} from "../types";

const groups: { key: WordPressDraftQueueGroup; label: string }[] = [
  { key: "eligible", label: "Eligible for WordPress draft" },
  { key: "blocked_approval", label: "Blocked by Atlas approval" },
  { key: "blocked_qa", label: "Blocked by QA" },
  { key: "blocked_stale_qa", label: "Blocked by stale QA after edits" },
  { key: "blocked_missing_media", label: "Blocked by missing media" },
  { key: "already_has_draft", label: "Already has WordPress draft" },
  { key: "blocked_credentials", label: "Blocked by credentials/session" },
  { key: "blocked_export", label: "Blocked by export readiness" }
];

function WordPressDraftQueuePage() {
  const [queue, setQueue] = useState<WordPressDraftQueueResponse | null>(null);
  const [selectedPageId, setSelectedPageId] = useState<number | null>(null);
  const [dryRun, setDryRun] = useState<WordPressDraftDryRun | null>(null);
  const [confirmationPhrase, setConfirmationPhrase] = useState("");
  const [createResult, setCreateResult] = useState<WordPressDraftCreateResult | null>(null);
  const [busy, setBusy] = useState<"load" | "dry-run" | "create" | null>("load");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadQueue();
  }, []);

  async function loadQueue(selectPageId?: number) {
    setBusy("load");
    setError(null);
    try {
      const response = await apiRequest<WordPressDraftQueueResponse>("/api/wordpress/draft-queue");
      setQueue(response);
      setSelectedPageId((current) => {
        if (selectPageId) return selectPageId;
        if (current && response.items.some((item) => item.page_id === current)) return current;
        return (
          response.items.find((item) => item.eligible)?.page_id
          ?? response.items.find((item) => item.queue_group !== "already_has_draft")?.page_id
          ?? response.items[0]?.page_id
          ?? null
        );
      });
    } catch (err) {
      setError(messageFrom(err, "Unable to load the WordPress draft queue."));
    } finally {
      setBusy(null);
    }
  }

  function selectPage(pageId: number) {
    setSelectedPageId(pageId);
    setDryRun(null);
    setConfirmationPhrase("");
    setCreateResult(null);
    setMessage(null);
    setError(null);
  }

  async function runDryRun() {
    if (!selectedPageId) return;
    setBusy("dry-run");
    setError(null);
    setMessage(null);
    setConfirmationPhrase("");
    setCreateResult(null);
    try {
      const result = await apiRequest<WordPressDraftDryRun>(
        `/api/wordpress/draft/dry-run/${selectedPageId}`,
        { method: "POST" }
      );
      setDryRun(result);
      setMessage(
        result.ready
          ? "Dry run passed. Review the exact payload and enter the confirmation phrase."
          : "Dry run completed without contacting WordPress. One or more gates are blocked."
      );
    } catch (err) {
      setError(messageFrom(err, "Unable to run the WordPress draft dry run."));
    } finally {
      setBusy(null);
    }
  }

  async function createDraft() {
    if (!dryRun?.confirmation_token || !dryRun.confirmation_phrase) return;
    setBusy("create");
    setError(null);
    setMessage(null);
    try {
      const result = await apiRequest<WordPressDraftCreateResult>(
        `/api/wordpress/draft/create/${dryRun.page_id}`,
        {
          method: "POST",
          body: JSON.stringify({
            confirmation_token: dryRun.confirmation_token,
            confirmation_phrase: confirmationPhrase
          })
        }
      );
      setCreateResult(result);
      setMessage(`WordPress draft ${result.wordpress_post_id} was created with status draft. It was not published.`);
      setDryRun(null);
      setConfirmationPhrase("");
      await loadQueue(result.page_id);
    } catch (err) {
      setError(messageFrom(err, "WordPress draft creation was blocked or failed."));
    } finally {
      setBusy(null);
    }
  }

  const selectedItem = useMemo(
    () => queue?.items.find((item) => item.page_id === selectedPageId) ?? null,
    [queue, selectedPageId]
  );

  return (
    <section className="page wordpressDraftQueuePage">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Controlled WordPress draft queue</p>
          <h1>WordPress Draft Queue</h1>
          <p>Create WordPress drafts one page at a time after dry run and exact confirmation.</p>
        </div>
      </header>

      <div className="wordpressSafetyNotice">
        <LockKeyhole size={19} aria-hidden="true" />
        <div>
          <strong>Draft only. This does not publish. One page at a time.</strong>
          <span>Media is not uploaded yet. Existing WordPress drafts are skipped. Backend restart clears the application password from memory.</span>
        </div>
      </div>

      {message && <div className="successAlert">{message}</div>}
      {error && <div className="alert">{error}</div>}

      {queue && (
        <div className="wordpressReviewSummary">
          <div><span>Total pages</span><strong>{queue.total_count}</strong></div>
          <div><span>Eligible</span><strong>{queue.eligible_count}</strong></div>
          <div><span>Blocked</span><strong>{queue.blocked_count}</strong></div>
          <div><span>Already drafted</span><strong>{queue.already_has_draft_count}</strong></div>
        </div>
      )}

      {queue && (
        <section className="panel wordpressSessionPanel">
          <div className="panelHeader">
            <div>
              <h2>Credential Session Status</h2>
              <p>Draft creation requires Sandbox mode and the application password in backend memory.</p>
            </div>
            <span className={`statusBadge ${queue.has_application_password ? "ready" : "warning"}`}>
              {queue.has_application_password ? "Password In Memory" : "Password Missing"}
            </span>
          </div>
          <dl className="detailsList compact">
            <div><dt>WordPress mode</dt><dd>{humanize(queue.wordpress_mode)}</dd></div>
            <div><dt>Site URL configured</dt><dd>{yesNo(queue.site_url_configured)}</dd></div>
            <div><dt>Username configured</dt><dd>{yesNo(queue.username_configured)}</dd></div>
            <div><dt>Application password in memory</dt><dd>{yesNo(queue.has_application_password)}</dd></div>
          </dl>
        </section>
      )}

      <div className="wordpressQueueLayout">
        <section className="panel wordpressDraftListPanel">
          <div className="panelHeader">
            <div>
              <h2>Queue</h2>
              <p>No select-all and no bulk create controls are available.</p>
            </div>
            <button className="secondaryButton buttonWithIcon" type="button" onClick={() => loadQueue()} disabled={busy !== null}>
              <RefreshCw size={16} aria-hidden="true" />
              Refresh
            </button>
          </div>

          {busy === "load" && !queue ? (
            <p>Loading WordPress draft queue...</p>
          ) : queue ? (
            <div className="wordpressQueueGroups">
              {groups.map((group) => {
                const items = queue.items.filter((item) => item.queue_group === group.key);
                return (
                  <article key={group.key} className="wordpressQueueGroup">
                    <div className="queueGroupHeader">
                      <h3>{group.label}</h3>
                      <span className="countBadge">{items.length}</span>
                    </div>
                    {items.length === 0 ? (
                      <p className="helperText">No pages in this group.</p>
                    ) : (
                      <div className="responsiveTableWrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Page</th>
                              <th>Status</th>
                              <th>Export</th>
                              <th>WordPress</th>
                              <th>Next Action</th>
                              <th>Workflow</th>
                            </tr>
                          </thead>
                          <tbody>
                            {items.map((item) => (
                              <tr key={item.page_id} className={item.page_id === selectedPageId ? "selectedRow" : undefined}>
                                <td>
                                  <strong>{item.city || item.page_title}</strong>
                                  <span>{item.county || "-"} - {item.service || "-"}</span>
                                  <code>{item.slug}</code>
                                </td>
                                <td>
                                  <Badge label={`Atlas ${humanize(item.atlas_status)}`} tone="muted" />
                                  <Badge label={`QA ${humanize(item.qa_status)}`} tone={item.qa_status === "ready" ? "ready" : "warning"} />
                                  <span>QA {formatDateTime(item.qa_checked_at)}</span>
                                  <span>{item.revision_count} revisions - {item.approval_audit_count} approvals</span>
                                </td>
                                <td>
                                  <Badge label={item.export_ready ? "Export Ready" : "Export Blocked"} tone={item.export_ready ? "ready" : "warning"} />
                                  <span>{item.export_blocker_count} blockers - {item.export_warning_count} warnings</span>
                                </td>
                                <td>
                                  {item.wordpress_post_id ? (
                                    <>
                                      <span>ID {item.wordpress_post_id}</span>
                                      <Badge label={item.wordpress_status || "Unknown"} tone={item.wordpress_status === "draft" ? "ready" : "warning"} />
                                    </>
                                  ) : (
                                    <span>No draft ref</span>
                                  )}
                                </td>
                                <td>{item.next_required_action}</td>
                                <td>
                                  <button className="linkButton" type="button" onClick={() => selectPage(item.page_id)}>
                                    Select
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          ) : null}
        </section>

        <QueueWorkflowPanel
          selectedItem={selectedItem}
          dryRun={dryRun}
          confirmationPhrase={confirmationPhrase}
          createResult={createResult}
          busy={busy}
          onDryRun={runDryRun}
          onCreate={createDraft}
          onConfirmationChange={setConfirmationPhrase}
        />
      </div>
    </section>
  );
}

function QueueWorkflowPanel({
  selectedItem,
  dryRun,
  confirmationPhrase,
  createResult,
  busy,
  onDryRun,
  onCreate,
  onConfirmationChange
}: {
  selectedItem: WordPressDraftQueueItem | null;
  dryRun: WordPressDraftDryRun | null;
  confirmationPhrase: string;
  createResult: WordPressDraftCreateResult | null;
  busy: "load" | "dry-run" | "create" | null;
  onDryRun: () => void;
  onCreate: () => void;
  onConfirmationChange: (value: string) => void;
}) {
  return (
    <section className="panel wordpressQueueWorkflow">
      <div className="panelHeader">
        <div>
          <h2>One-Page Draft Workflow</h2>
          <p>{selectedItem ? selectedItem.page_title : "Select one page to review gates."}</p>
        </div>
        <button
          className="primaryButton buttonWithIcon"
          type="button"
          onClick={onDryRun}
          disabled={!selectedItem || busy !== null || selectedItem.queue_group === "already_has_draft"}
        >
          <ClipboardCheck size={16} aria-hidden="true" />
          {busy === "dry-run" ? "Running Dry Run..." : "Run Dry Run"}
        </button>
      </div>

      {!selectedItem ? (
        <p>Select one queue item to inspect its gates.</p>
      ) : (
        <>
          <div className="badgeStack">
            <Badge label={groupLabel(selectedItem.queue_group)} tone={selectedItem.eligible ? "ready" : selectedItem.queue_group === "already_has_draft" ? "muted" : "warning"} />
            <Badge label={`Payload ${selectedItem.payload_status}`} tone="muted" />
          </div>
          <dl className="detailsList compact">
            <div><dt>City</dt><dd>{selectedItem.city || "-"}</dd></div>
            <div><dt>County</dt><dd>{selectedItem.county || "-"}</dd></div>
            <div><dt>Slug</dt><dd><code>{selectedItem.slug}</code></dd></div>
            <div><dt>WordPress ref</dt><dd>{selectedItem.wordpress_post_id ? `ID ${selectedItem.wordpress_post_id}` : "None"}</dd></div>
          </dl>
          {selectedItem.wordpress_post_id && (
            <div className="formActions">
              <Link className="secondaryButton buttonWithIcon" to="/wordpress-draft-review">
                <ExternalLink size={16} aria-hidden="true" />
                WordPress Draft Review
              </Link>
              {selectedItem.wordpress_url && (
                <a className="secondaryButton buttonWithIcon" href={selectedItem.wordpress_url} target="_blank" rel="noreferrer">
                  <ExternalLink size={16} aria-hidden="true" />
                  View Draft URL
                </a>
              )}
            </div>
          )}

          <div className="wordpressGateList">
            {(dryRun?.gate_results ?? selectedItem.gate_results).map((gate) => (
              <article key={gate.code} className={gate.passed ? "passed" : "failed"}>
                {gate.passed ? <CheckCircle2 size={17} aria-hidden="true" /> : <AlertTriangle size={17} aria-hidden="true" />}
                <div><strong>{gate.label}</strong><p>{gate.message}</p></div>
              </article>
            ))}
          </div>

          {!dryRun && (
            <div className="wordpressDraftEmpty">
              <LockKeyhole size={20} aria-hidden="true" />
              <div>
                <p>Creation is disabled until a dry run passes for this one selected page.</p>
                <button className="dangerButton buttonWithIcon" type="button" disabled>
                  <Send size={16} aria-hidden="true" /> Create WordPress Draft
                </button>
              </div>
            </div>
          )}

          {dryRun && (
            <>
              <div className={`dryRunHeadline ${dryRun.ready ? "ready" : "blocked"}`}>
                {dryRun.ready ? <CheckCircle2 size={20} aria-hidden="true" /> : <AlertTriangle size={20} aria-hidden="true" />}
                <div>
                  <strong>{dryRun.ready ? "Dry Run Ready" : "Draft Creation Blocked"}</strong>
                  <span>WordPress was not contacted and no Atlas records were changed.</span>
                </div>
              </div>
              <div className="wordpressExactPayload">
                <div>
                  <h3>Exact WordPress Draft Request</h3>
                  <p>Status is forced to draft.</p>
                </div>
                <pre className="jsonLdPreview"><code>{JSON.stringify(dryRun.payload, null, 2)}</code></pre>
              </div>
              <div className="wordpressCreateConfirmation">
                <AlertTriangle size={19} aria-hidden="true" />
                <div>
                  <strong>This will create one DRAFT only in WordPress. It will not publish the page.</strong>
                  {dryRun.ready ? (
                    <>
                      <label>
                        Type the confirmation phrase exactly
                        <code>{dryRun.confirmation_phrase}</code>
                        <input
                          value={confirmationPhrase}
                          onChange={(event) => onConfirmationChange(event.target.value)}
                          autoComplete="off"
                        />
                      </label>
                      <button
                        className="dangerButton buttonWithIcon"
                        type="button"
                        onClick={onCreate}
                        disabled={
                          busy !== null ||
                          !dryRun.confirmation_phrase ||
                          confirmationPhrase !== dryRun.confirmation_phrase
                        }
                      >
                        <Send size={16} aria-hidden="true" />
                        {busy === "create" ? "Creating Draft..." : "Create WordPress Draft"}
                      </button>
                    </>
                  ) : (
                    <>
                      <p>Resolve every failed gate, then run a new dry run. Creation remains disabled.</p>
                      <button className="dangerButton buttonWithIcon" type="button" disabled>
                        <Send size={16} aria-hidden="true" /> Create WordPress Draft
                      </button>
                    </>
                  )}
                </div>
              </div>
            </>
          )}

          {createResult && (
            <div className="successAlert">
              WordPress post ID {createResult.wordpress_post_id} was created with status {createResult.wordpress_status}. Atlas page status was not changed to published.
            </div>
          )}

          <div className="formActions">
            <Link className="secondaryButton buttonWithIcon" to={`/generated-pages/${selectedItem.page_id}/export`}>
              <FileJson size={16} aria-hidden="true" />
              View Export Package
            </Link>
            <Link className="secondaryButton buttonWithIcon" to={`/generated-pages/${selectedItem.page_id}/preview`}>
              <ExternalLink size={16} aria-hidden="true" />
              Preview Page
            </Link>
          </div>
        </>
      )}
    </section>
  );
}

function Badge({ label, tone }: { label: string; tone: "ready" | "warning" | "danger" | "muted" }) {
  return <span className={`statusBadge ${tone}`}>{label}</span>;
}

function groupLabel(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function yesNo(value: boolean) {
  return value ? "Yes" : "No";
}

function formatDateTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "-";
}

function messageFrom(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export default WordPressDraftQueuePage;
