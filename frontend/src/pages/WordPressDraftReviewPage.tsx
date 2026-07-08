import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  FileJson,
  RefreshCw,
  ShieldCheck
} from "lucide-react";
import { Link } from "react-router-dom";

import { apiRequest } from "../api";
import type {
  WordPressDraftComparison,
  WordPressDraftReviewDetail,
  WordPressDraftReviewItem,
  WordPressDraftReviewList,
  WordPressLiveDraftStatus,
  WordPressSettings
} from "../types";

function WordPressDraftReviewPage() {
  const [list, setList] = useState<WordPressDraftReviewList>({ total_count: 0, items: [] });
  const [selectedPageId, setSelectedPageId] = useState<number | null>(null);
  const [detail, setDetail] = useState<WordPressDraftReviewDetail | null>(null);
  const [settings, setSettings] = useState<WordPressSettings | null>(null);
  const [liveStatus, setLiveStatus] = useState<WordPressLiveDraftStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<"detail" | "live" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    loadList();
  }, []);

  useEffect(() => {
    if (!selectedPageId) return;
    setWorking("detail");
    setError(null);
    setLiveStatus(null);
    apiRequest<WordPressDraftReviewDetail>(`/api/wordpress/draft-review/${selectedPageId}`)
      .then(setDetail)
      .catch((err) => setError(messageFrom(err, "Unable to load the draft review.")))
      .finally(() => setWorking(null));
  }, [selectedPageId]);

  async function loadList() {
    setLoading(true);
    setError(null);
    try {
      const [response, loadedSettings] = await Promise.all([
        apiRequest<WordPressDraftReviewList>("/api/wordpress/draft-review"),
        apiRequest<WordPressSettings>("/api/wordpress/settings")
      ]);
      setList(response);
      setSettings(loadedSettings);
      setSelectedPageId((current) => current ?? response.items[0]?.page_id ?? null);
    } catch (err) {
      setError(messageFrom(err, "Unable to load WordPress draft reviews."));
    } finally {
      setLoading(false);
    }
  }

  async function checkLiveStatus() {
    if (!selectedPageId) return;
    setWorking("live");
    setError(null);
    setMessage(null);
    try {
      const response = await apiRequest<WordPressLiveDraftStatus>(
        `/api/wordpress/draft-review/${selectedPageId}/live-status`
      );
      setLiveStatus(response);
      setMessage(response.error_message ? "Read-only status check returned an issue." : "Read-only status check completed.");
    } catch (err) {
      setError(messageFrom(err, "Unable to check the WordPress draft status."));
    } finally {
      setWorking(null);
    }
  }

  const selectedItem = useMemo(
    () => list.items.find((item) => item.page_id === selectedPageId) ?? null,
    [list.items, selectedPageId]
  );

  const comparison = detail?.comparison ?? null;

  return (
    <section className="page wordpressDraftReviewPage">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Read-only WordPress review</p>
          <h1>WordPress Draft Review</h1>
          <p>Monitor created WordPress drafts before creating any additional city drafts.</p>
        </div>
      </header>

      <div className="wordpressSafetyNotice">
        <ShieldCheck size={19} aria-hidden="true" />
        <div>
          <strong>Review only. This page cannot create, update, delete, upload media, or publish WordPress content.</strong>
          <span>The live status action uses a WordPress REST GET request for the saved post ID.</span>
        </div>
      </div>

      <WordPressSessionStatusPanel settings={settings} liveStatus={liveStatus} />

      {message && <div className="successAlert">{message}</div>}
      {error && <div className="alert">{error}</div>}

      <div className="wordpressReviewSummary">
        <div><span>Draft refs</span><strong>{list.total_count}</strong></div>
        <div><span>Safe drafts</span><strong>{list.items.filter((item) => item.badges.includes("Safe Draft")).length}</strong></div>
        <div><span>Needs review</span><strong>{list.items.filter((item) => item.badges.includes("Needs Review")).length}</strong></div>
        <div><span>Changed since draft</span><strong>{list.items.filter((item) => item.badges.includes("Atlas Changed Since Draft")).length}</strong></div>
      </div>

      <section className="panel wordpressDraftListPanel">
        <div className="panelHeader">
          <div>
            <h2>Draft References</h2>
            <p>Atlas pages with saved WordPress draft references.</p>
          </div>
          <button className="secondaryButton buttonWithIcon" type="button" onClick={loadList} disabled={loading || working !== null}>
            <RefreshCw size={16} aria-hidden="true" />
            Refresh
          </button>
        </div>

        {loading ? (
          <p>Loading WordPress draft references...</p>
        ) : list.items.length === 0 ? (
          <p>No WordPress draft references exist yet.</p>
        ) : (
          <div className="responsiveTableWrap">
            <table>
              <thead>
                <tr>
                  <th>Atlas Page</th>
                  <th>Location</th>
                  <th>Status</th>
                  <th>WordPress</th>
                  <th>Audit</th>
                  <th>Badges</th>
                  <th>Review</th>
                </tr>
              </thead>
              <tbody>
                {list.items.map((item) => (
                  <tr key={item.page_id} className={item.page_id === selectedPageId ? "selectedRow" : undefined}>
                    <td>
                      <strong>{item.page_title}</strong>
                      <span>{item.service || "-"}</span>
                    </td>
                    <td>{item.city || "-"}<br /><span>{item.county || "-"}</span></td>
                    <td>
                      <Badge label={`Atlas ${humanize(item.atlas_status)}`} tone="muted" />
                      <Badge label={`QA ${humanize(item.qa_status)}`} tone={item.qa_status === "ready" ? "ready" : "warning"} />
                    </td>
                    <td>
                      <div>ID {item.wordpress_post_id}</div>
                      <Badge label={item.wordpress_status || "Unknown"} tone={item.wordpress_status === "draft" ? "ready" : "warning"} />
                      {item.wordpress_url && (
                        <a href={item.wordpress_url} target="_blank" rel="noreferrer">
                          View URL <ExternalLink size={13} aria-hidden="true" />
                        </a>
                      )}
                    </td>
                    <td>
                      <div>{item.successful_draft_audit_count} successful</div>
                      <span>{formatDateTime(item.latest_draft_audit_at)}</span>
                    </td>
                    <td>
                      <div className="badgeStack">
                        {item.badges.map((badge) => (
                          <Badge key={badge} label={badge} tone={badgeTone(badge)} />
                        ))}
                      </div>
                    </td>
                    <td>
                      <button className="linkButton" type="button" onClick={() => setSelectedPageId(item.page_id)}>
                        Review
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {selectedItem && (
        <div className="wordpressReviewGrid">
          <section className="panel">
            <div className="panelHeader">
              <div>
                <h2>Selected Draft</h2>
                <p>{selectedItem.page_title}</p>
              </div>
              <button
                className="primaryButton buttonWithIcon"
                type="button"
                onClick={checkLiveStatus}
                disabled={working !== null}
              >
                <RefreshCw size={16} aria-hidden="true" />
                {working === "live" ? "Checking..." : "Check WordPress Draft Status"}
              </button>
            </div>
            <dl className="detailsList compact">
              <div><dt>WordPress post ID</dt><dd>{selectedItem.wordpress_post_id}</dd></div>
              <div><dt>Saved WordPress status</dt><dd>{selectedItem.wordpress_status || "-"}</dd></div>
              <div><dt>Last sync</dt><dd>{formatDateTime(selectedItem.last_wordpress_sync_at)}</dd></div>
              <div><dt>Payload hash</dt><dd><code>{shortHash(selectedItem.audit_payload_hash)}</code></dd></div>
              <div><dt>Draft hash</dt><dd><code>{shortHash(selectedItem.audit_draft_hash)}</code></dd></div>
            </dl>
            <div className="formActions">
              {selectedItem.admin_edit_url && (
                <a className="secondaryButton buttonWithIcon" href={selectedItem.admin_edit_url} target="_blank" rel="noreferrer">
                  <ExternalLink size={16} aria-hidden="true" />
                  Open Admin Edit Link
                </a>
              )}
              <Link className="secondaryButton buttonWithIcon" to={`/generated-pages/${selectedItem.page_id}/export`}>
                <FileJson size={16} aria-hidden="true" />
                View Export Package
              </Link>
            </div>
          </section>

          <LiveStatusPanel status={liveStatus} />
          <ComparisonPanel comparison={comparison} liveStatus={liveStatus} loading={working === "detail"} />
        </div>
      )}
    </section>
  );
}

function LiveStatusPanel({ status }: { status: WordPressLiveDraftStatus | null }) {
  return (
    <section className="panel">
      <h2>Live WordPress Status</h2>
      {!status ? (
        <p>Run the read-only status check to compare the saved Atlas reference with WordPress.</p>
      ) : status.error_message ? (
        <>
          <div className="inlineWarning">
            <AlertTriangle size={17} aria-hidden="true" />
            {status.error_message}
          </div>
          {status.error_message.toLowerCase().includes("password") && (
            <p className="helperText">
              The saved WordPress draft reference still exists in Atlas. Live checking requires re-entering the application password after backend restart.
            </p>
          )}
        </>
      ) : (
        <>
          <div className="badgeStack">
            <Badge label={status.is_still_draft ? "Draft Confirmed" : "Needs Review"} tone={status.is_still_draft ? "ready" : "warning"} />
            {status.appears_published && <Badge label="Published Warning" tone="danger" />}
          </div>
          <dl className="detailsList compact">
            <div><dt>WordPress status</dt><dd>{status.wordpress_status || "-"}</dd></div>
            <div><dt>WordPress title</dt><dd>{stripHtml(status.wordpress_title) || "-"}</dd></div>
            <div><dt>WordPress slug</dt><dd>{status.wordpress_slug || "-"}</dd></div>
            <div><dt>Modified</dt><dd>{status.wordpress_modified || "-"}</dd></div>
            <div><dt>Link</dt><dd>{status.wordpress_link ? <a href={status.wordpress_link} target="_blank" rel="noreferrer">{status.wordpress_link}</a> : "-"}</dd></div>
          </dl>
        </>
      )}
    </section>
  );
}

function WordPressSessionStatusPanel({
  settings,
  liveStatus
}: {
  settings: WordPressSettings | null;
  liveStatus: WordPressLiveDraftStatus | null;
}) {
  const passwordPresent = Boolean(settings?.has_application_password);
  return (
    <section className="panel wordpressSessionPanel">
      <div className="panelHeader">
        <div>
          <h2>Credential Session Status</h2>
          <p>Live status checks need the password in backend memory, but draft references remain visible without it.</p>
        </div>
        <span className={`statusBadge ${passwordPresent ? "ready" : "warning"}`}>
          {passwordPresent ? "Password In Memory" : "Password Missing"}
        </span>
      </div>
      <dl className="detailsList compact">
        <div><dt>WordPress mode</dt><dd>{settings ? humanize(settings.publishing_mode) : "Unknown"}</dd></div>
        <div><dt>Site URL configured</dt><dd>{yesNo(Boolean(settings?.site_url))}</dd></div>
        <div><dt>Username configured</dt><dd>{yesNo(Boolean(settings?.username))}</dd></div>
        <div><dt>Application password in memory</dt><dd>{yesNo(passwordPresent)}</dd></div>
        <div><dt>REST API reachable</dt><dd>{triState(liveStatus?.rest_api_reachable)}</dd></div>
        <div><dt>Authenticated</dt><dd>{triState(liveStatus?.authenticated)}</dd></div>
      </dl>
      <div className={passwordPresent ? "inlineSuccess" : "inlineWarning"}>
        {passwordPresent
          ? "Application password is currently stored in backend memory."
          : "Application password is missing. Re-enter it after backend restart."}
      </div>
      <p className="helperText">REST API reachable does not mean credentials are authenticated. Atlas does not store the application password in backups or the database.</p>
    </section>
  );
}

function ComparisonPanel({
  comparison,
  liveStatus,
  loading
}: {
  comparison: WordPressDraftComparison | null;
  liveStatus: WordPressLiveDraftStatus | null;
  loading: boolean;
}) {
  if (loading) {
    return <section className="panel"><p>Loading comparison...</p></section>;
  }
  if (!comparison) {
    return <section className="panel"><p>Select a draft to view comparison details.</p></section>;
  }

  return (
    <section className="panel wordpressComparisonPanel">
      <div className="panelHeader">
        <div>
          <h2>Atlas vs WordPress</h2>
          <p>Read-only comparison for the selected draft.</p>
        </div>
        {comparison.atlas_export_differs_from_original ? (
          <Badge label="Atlas Changed Since Draft" tone="warning" />
        ) : (
          <Badge label="Safe Draft" tone="ready" />
        )}
      </div>
      {comparison.atlas_export_differs_from_original && (
        <div className="inlineWarning">
          <AlertTriangle size={17} aria-hidden="true" />
          Atlas content has changed since this WordPress draft was created. Review before updating later.
        </div>
      )}
      <dl className="comparisonList">
        <div><dt>Atlas saved title</dt><dd>{comparison.atlas_saved_title}</dd></div>
        <div><dt>WordPress title</dt><dd>{stripHtml(liveStatus?.wordpress_title ?? comparison.wordpress_title) || "-"}</dd></div>
        <div><dt>Atlas saved slug</dt><dd><code>{comparison.atlas_saved_slug}</code></dd></div>
        <div><dt>WordPress slug</dt><dd><code>{liveStatus?.wordpress_slug ?? comparison.wordpress_slug ?? "-"}</code></dd></div>
        <div><dt>Expected status</dt><dd>{comparison.atlas_expected_status}</dd></div>
        <div><dt>Actual status</dt><dd>{liveStatus?.wordpress_status ?? comparison.wordpress_actual_status ?? "-"}</dd></div>
        <div><dt>Atlas WordPress URL</dt><dd>{comparison.atlas_wordpress_url || "-"}</dd></div>
        <div><dt>WordPress link</dt><dd>{liveStatus?.wordpress_link ?? comparison.wordpress_link ?? "-"}</dd></div>
        <div><dt>Audit payload hash</dt><dd><code>{comparison.audit_payload_hash || "-"}</code></dd></div>
        <div><dt>Current export payload hash</dt><dd><code>{comparison.current_export_payload_hash}</code></dd></div>
        <div><dt>Audit draft hash</dt><dd><code>{comparison.audit_draft_hash || "-"}</code></dd></div>
      </dl>
      {comparison.message && <p className="helperText">{comparison.message}</p>}
    </section>
  );
}

function Badge({ label, tone }: { label: string; tone: "ready" | "warning" | "danger" | "muted" }) {
  return <span className={`statusBadge ${tone}`}>{label}</span>;
}

function badgeTone(label: string): "ready" | "warning" | "danger" | "muted" {
  if (label === "Safe Draft" || label === "Draft Confirmed") return "ready";
  if (label === "Published Warning" || label === "WordPress Not Found") return "danger";
  if (label === "Needs Review" || label === "Atlas Changed Since Draft") return "warning";
  return "muted";
}

function formatDateTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "-";
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function shortHash(value?: string | null) {
  return value ? value.slice(0, 12) : "-";
}

function stripHtml(value?: string | null) {
  return value ? value.replace(/<[^>]*>/g, "") : "";
}

function yesNo(value: boolean) {
  return value ? "Yes" : "No";
}

function triState(value?: boolean | null) {
  if (value === true) return "Yes";
  if (value === false) return "No";
  return "Unknown";
}

function messageFrom(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export default WordPressDraftReviewPage;
