import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileJson,
  LockKeyhole,
  RefreshCw,
  ShieldAlert,
  ShieldCheck
} from "lucide-react";
import { Link } from "react-router-dom";

import { apiRequest } from "../api";
import type {
  WordPressDraftQualityReviewItem,
  WordPressDraftQualityReviewList,
  WordPressDraftReviewItem,
  WordPressDraftReviewList,
  WordPressPublishDryRun,
  WordPressPublishApplyResult,
  WordPressSettings
} from "../types";

function WordPressPublishSafetySandboxPage() {
  const [settings, setSettings] = useState<WordPressSettings | null>(null);
  const [drafts, setDrafts] = useState<WordPressDraftReviewItem[]>([]);
  const [qualityItems, setQualityItems] = useState<WordPressDraftQualityReviewItem[]>([]);
  const [selectedPageId, setSelectedPageId] = useState<number | null>(null);
  const [dryRun, setDryRun] = useState<WordPressPublishDryRun | null>(null);
  const [confirmationPhrase, setConfirmationPhrase] = useState("");
  const [confirmedBackupFile, setConfirmedBackupFile] = useState("");
  const [applyResult, setApplyResult] = useState<WordPressPublishApplyResult | null>(null);
  const [busy, setBusy] = useState<"load" | "dry-run" | "apply" | null>("load");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadWorkspace();
  }, []);

  async function loadWorkspace() {
    setBusy("load");
    setError(null);
    try {
      const [loadedSettings, reviewList, qualityList] = await Promise.all([
        apiRequest<WordPressSettings>("/api/wordpress/settings"),
        apiRequest<WordPressDraftReviewList>("/api/wordpress/draft-review"),
        apiRequest<WordPressDraftQualityReviewList>("/api/wordpress/draft-quality-review")
      ]);
      setSettings(loadedSettings);
      setDrafts(reviewList.items);
      setQualityItems(qualityList.items);
      setSelectedPageId((current) => current ?? reviewList.items[0]?.page_id ?? null);
    } catch (err) {
      setError(messageFrom(err, "Unable to load the WordPress publish safety sandbox."));
    } finally {
      setBusy(null);
    }
  }

  async function runDryRun() {
    if (!selectedPageId) return;
    setBusy("dry-run");
    setError(null);
    setMessage(null);
    setDryRun(null);
    setConfirmationPhrase("");
    setConfirmedBackupFile("");
    setApplyResult(null);
    try {
      const result = await apiRequest<WordPressPublishDryRun>(
        `/api/wordpress/publish/dry-run/${selectedPageId}`,
        { method: "POST" }
      );
      setDryRun(result);
      setMessage(
        result.ready
          ? "Publish dry run passed. This did not publish or update WordPress."
          : "Publish dry run completed. One or more gates are blocked."
      );
    } catch (err) {
      setError(messageFrom(err, "Unable to run the WordPress publish dry run."));
    } finally {
      setBusy(null);
    }
  }

  async function applyPublish() {
    if (!selectedPageId || !dryRun?.confirmation_token || !canApply) return;
    setBusy("apply");
    setError(null);
    setMessage(null);
    try {
      const result = await apiRequest<WordPressPublishApplyResult>(
        `/api/wordpress/publish/apply/${selectedPageId}`,
        {
          method: "POST",
          body: JSON.stringify({
            confirmation_token: dryRun.confirmation_token,
            confirmation_phrase: confirmationPhrase,
            confirmed_backup_file: confirmedBackupFile.trim()
          })
        }
      );
      setApplyResult(result);
      setDryRun(null);
      setConfirmationPhrase("");
      setConfirmedBackupFile("");
      setMessage(`WordPress post ${result.wordpress_post_id} is published and Atlas was updated.`);
    } catch (err) {
      setError(messageFrom(err, "Unable to apply the controlled WordPress publish."));
    } finally {
      setBusy(null);
    }
  }

  const selectedDraft = useMemo(
    () => drafts.find((item) => item.page_id === selectedPageId) ?? null,
    [drafts, selectedPageId]
  );
  const selectedQuality = useMemo(
    () => qualityItems.find((item) => item.page_id === selectedPageId) ?? null,
    [qualityItems, selectedPageId]
  );
  const tokenUnexpired = Boolean(dryRun?.expires_at && Date.parse(dryRun.expires_at) > Date.now());
  const canApply = Boolean(
    dryRun?.ready && dryRun.confirmation_token && tokenUnexpired &&
    confirmationPhrase === dryRun.confirmation_phrase && confirmedBackupFile.trim() &&
    selectedPageId === dryRun.page_id && busy === null
  );

  return (
    <section className="page wordpressPublishSafetySandboxPage">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Dry-run only</p>
          <h1>WordPress Publish Safety Sandbox</h1>
          <p>Validate future one-page publishing gates without publishing or changing WordPress.</p>
        </div>
      </header>

      <div className="wordpressSafetyNotice">
        <LockKeyhole size={19} aria-hidden="true" />
        <div>
          <strong>Controlled one-page publish only.</strong>
          <span>Apply remains locked until a fresh dry run, exact phrase, and confirmed current Data Backup JSON pass every backend gate.</span>
        </div>
      </div>

      {message && <div className="successAlert">{message}</div>}
      {error && <div className="alert">{error}</div>}

      <section className="panel wordpressSessionPanel">
        <div className="panelHeader">
          <div>
            <h2>Credential Session Status</h2>
            <p>Dry run requires Sandbox mode and the WordPress application password in backend memory for the live draft check.</p>
          </div>
          <span className={`statusBadge ${settings?.has_application_password ? "ready" : "warning"}`}>
            {settings?.has_application_password ? "Password In Memory" : "Password Missing"}
          </span>
        </div>
        <dl className="detailsList compact">
          <div><dt>WordPress mode</dt><dd>{settings ? humanize(settings.publishing_mode) : "Unknown"}</dd></div>
          <div><dt>Site URL configured</dt><dd>{yesNo(Boolean(settings?.site_url))}</dd></div>
          <div><dt>Username configured</dt><dd>{yesNo(Boolean(settings?.username))}</dd></div>
          <div><dt>Application password in memory</dt><dd>{yesNo(Boolean(settings?.has_application_password))}</dd></div>
        </dl>
        <p className="helperText">Atlas does not store the application password in backups, exports, logs, or browser output.</p>
      </section>

      <div className="wordpressReviewGrid">
        <section className="panel">
          <div className="panelHeader">
            <div>
              <h2>Select One Draft</h2>
              <p>Only pages with saved WordPress draft references are shown.</p>
            </div>
            <button className="secondaryButton buttonWithIcon" type="button" onClick={loadWorkspace} disabled={busy !== null}>
              <RefreshCw size={16} aria-hidden="true" />
              Refresh
            </button>
          </div>
          {busy === "load" ? (
            <p>Loading draft references...</p>
          ) : drafts.length === 0 ? (
            <p>No WordPress draft references exist yet.</p>
          ) : (
            <label>
              Existing WordPress draft page
              <select
                value={selectedPageId ?? ""}
                onChange={(event) => {
                  setSelectedPageId(Number(event.target.value));
                  setDryRun(null);
                  setConfirmationPhrase("");
                  setConfirmedBackupFile("");
                  setApplyResult(null);
                  setMessage(null);
                  setError(null);
                }}
              >
                {drafts.map((draft) => (
                  <option key={draft.page_id} value={draft.page_id}>
                    {draft.city || draft.page_title} | Post {draft.wordpress_post_id} | {draft.wordpress_status || "unknown"}
                  </option>
                ))}
              </select>
            </label>
          )}

          {selectedDraft && (
            <>
              <dl className="detailsList compact">
                <div><dt>Atlas status</dt><dd>{humanize(selectedDraft.atlas_status)}</dd></div>
                <div><dt>QA status</dt><dd>{humanize(selectedDraft.qa_status)}</dd></div>
                <div><dt>WordPress post ID</dt><dd>{selectedDraft.wordpress_post_id}</dd></div>
                <div><dt>Saved WP status</dt><dd>{selectedDraft.wordpress_status || "-"}</dd></div>
                <div><dt>Manual review</dt><dd>{selectedQuality ? humanize(selectedQuality.manual_review.review_status) : "Unknown"}</dd></div>
                <div><dt>Quality review</dt><dd>{selectedQuality ? `${selectedQuality.pass_count} pass / ${selectedQuality.warning_count} warning / ${selectedQuality.fail_count} fail` : "Unknown"}</dd></div>
              </dl>
              <div className="formActions">
                <button className="primaryButton buttonWithIcon" type="button" onClick={runDryRun} disabled={busy !== null}>
                  <ShieldCheck size={16} aria-hidden="true" />
                  {busy === "dry-run" ? "Running..." : "Run Publish Dry Run"}
                </button>
                <Link className="secondaryButton buttonWithIcon" to={`/generated-pages/${selectedDraft.page_id}/export`}>
                  <FileJson size={16} aria-hidden="true" />
                  View Export Package
                </Link>
              </div>
            </>
          )}
        </section>

        <GatePanel dryRun={dryRun} />
      </div>

      {dryRun && (
        <div className="wordpressReviewGrid">
          <HashPanel dryRun={dryRun} />
          <PayloadPanel dryRun={dryRun} />
        </div>
      )}
      {dryRun && (
        <PublishApplyPanel
          dryRun={dryRun}
          city={selectedDraft?.city || selectedDraft?.page_title || "Selected"}
          confirmationPhrase={confirmationPhrase}
          confirmedBackupFile={confirmedBackupFile}
          busy={busy}
          canApply={canApply}
          onPhraseChange={setConfirmationPhrase}
          onBackupChange={setConfirmedBackupFile}
          onApply={applyPublish}
        />
      )}
      {applyResult && (
        <section className="panel wordpressApplyPanel">
          <h2>Publish Confirmed</h2>
          <p>WordPress post {applyResult.wordpress_post_id} returned status publish.</p>
          <a href={applyResult.wordpress_url} target="_blank" rel="noreferrer">Open confirmed public URL</a>
        </section>
      )}
    </section>
  );
}

function GatePanel({ dryRun }: { dryRun: WordPressPublishDryRun | null }) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <h2>Gate Checklist</h2>
          <p>Every gate must pass before a future one-page publish apply can even be considered.</p>
        </div>
        {dryRun ? (
          <span className={`statusBadge ${dryRun.ready ? "ready" : "warning"}`}>
            {dryRun.ready ? "Dry Run Ready" : "Blocked"}
          </span>
        ) : null}
      </div>
      {!dryRun ? (
        <p>Run a dry run to see the publish gates.</p>
      ) : (
        <div className="checklistGrid">
          {dryRun.gate_results.map((gate) => (
            <article key={gate.code} className={`checkItem ${gate.passed ? "pass" : "fail"}`}>
              {gate.passed ? <CheckCircle2 size={17} aria-hidden="true" /> : <AlertTriangle size={17} aria-hidden="true" />}
              <div>
                <strong>{gate.label}</strong>
                <span>{gate.message}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function HashPanel({ dryRun }: { dryRun: WordPressPublishDryRun }) {
  const hashesMatch = dryRun.current_payload_hash === dryRun.latest_update_audit_hash;
  return (
    <section className="panel wordpressComparisonPanel">
      <div className="panelHeader">
        <div>
          <h2>Sync Check</h2>
          <p>Latest update_draft audit must match the current Atlas draft payload before future publishing.</p>
        </div>
        <span className={`statusBadge ${hashesMatch ? "ready" : "warning"}`}>
          {hashesMatch ? "Synced" : "Mismatch"}
        </span>
      </div>
      <dl className="comparisonList">
        <div><dt>Current Atlas draft payload hash</dt><dd><code>{dryRun.current_payload_hash}</code></dd></div>
        <div><dt>Latest update audit hash</dt><dd><code>{dryRun.latest_update_audit_hash || "-"}</code></dd></div>
        <div><dt>Future publish payload hash</dt><dd><code>{dryRun.publish_payload_hash}</code></dd></div>
        <div><dt>Live WordPress status</dt><dd>{dryRun.live_status?.wordpress_status || dryRun.live_status?.error_message || "-"}</dd></div>
      </dl>
      <div className="inlineWarning">
        <ShieldAlert size={17} aria-hidden="true" />
        {dryRun.public_publish_warning}
      </div>
    </section>
  );
}

function PayloadPanel({ dryRun }: { dryRun: WordPressPublishDryRun }) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <h2>Future Publish Payload Preview</h2>
          <p>Status is shown as publish for future review only. This payload was not sent.</p>
        </div>
        <span className="statusBadge warning">Status: {dryRun.payload.status}</span>
      </div>
      <dl className="detailsList compact">
        <div><dt>Title</dt><dd>{dryRun.payload.title}</dd></div>
        <div><dt>Slug</dt><dd><code>{dryRun.payload.slug}</code></dd></div>
        <div><dt>Excerpt</dt><dd>{dryRun.payload.excerpt}</dd></div>
      </dl>
      <details>
        <summary>Content HTML preview</summary>
        <pre className="codeBlock">{dryRun.payload.content}</pre>
      </details>
    </section>
  );
}

function PublishApplyPanel({
  dryRun, city, confirmationPhrase, confirmedBackupFile, busy, canApply,
  onPhraseChange, onBackupChange, onApply
}: {
  dryRun: WordPressPublishDryRun;
  city: string;
  confirmationPhrase: string;
  confirmedBackupFile: string;
  busy: "load" | "dry-run" | "apply" | null;
  canApply: boolean;
  onPhraseChange: (value: string) => void;
  onBackupChange: (value: string) => void;
  onApply: () => void;
}) {
  return (
    <section className="panel wordpressApplyPanel">
      <div className="panelHeader">
        <div>
          <h2>Controlled One-Page Publish</h2>
          <p>This final action publishes only the selected existing WordPress draft.</p>
        </div>
        <span className={`statusBadge ${dryRun.ready ? "ready" : "warning"}`}>
          {dryRun.ready ? "Generated" : "Not Generated"}
        </span>
      </div>
      <div className="wordpressSafetyNotice compact">
        <LockKeyhole size={18} aria-hidden="true" />
        <div>
          <strong>Publishing makes this page public.</strong>
          <span>No bulk, media upload, content editor, create, delete, unpublish, or automatic rollback action is available.</span>
        </div>
      </div>
      {dryRun.confirmation_phrase && (
        <>
          <div className="inlineSuccess">Required phrase: <code>{dryRun.confirmation_phrase}</code></div>
          <label>Exact confirmation phrase<input value={confirmationPhrase} onChange={(event) => onPhraseChange(event.target.value)} autoComplete="off" /></label>
          <label>Confirmed Data Backup JSON filename<input value={confirmedBackupFile} onChange={(event) => onBackupChange(event.target.value)} placeholder="atlas-backup-YYYY-MM-DD-HHMMSS.json" autoComplete="off" /></label>
          <div className="formActions">
            <button className="primaryButton" type="button" disabled={!canApply} onClick={onApply}>
              {busy === "apply" ? "Publishing..." : `Publish ${city} Page`}
            </button>
          </div>
        </>
      )}
      {dryRun.confirmation_token && (
        <p className="helperText">Signed token generated for future v0.45 planning. It expires and is valid only for this page, post ID, action, and publish payload hash.</p>
      )}
      {!dryRun.ready && <p className="helperText">Publish remains unavailable until every publish dry-run gate passes.</p>}
    </section>
  );
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function yesNo(value: boolean) {
  return value ? "Yes" : "No";
}

function messageFrom(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export default WordPressPublishSafetySandboxPage;
