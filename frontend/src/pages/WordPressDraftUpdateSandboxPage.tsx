import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FileJson,
  LockKeyhole,
  RefreshCw,
  ShieldCheck
} from "lucide-react";
import { Link } from "react-router-dom";

import { apiRequest } from "../api";
import type {
  WordPressDraftReviewItem,
  WordPressDraftReviewList,
  WordPressDraftUpdateApplyResult,
  WordPressDraftUpdateDryRun,
  WordPressSettings
} from "../types";

function WordPressDraftUpdateSandboxPage() {
  const [settings, setSettings] = useState<WordPressSettings | null>(null);
  const [drafts, setDrafts] = useState<WordPressDraftReviewItem[]>([]);
  const [selectedPageId, setSelectedPageId] = useState<number | null>(null);
  const [dryRun, setDryRun] = useState<WordPressDraftUpdateDryRun | null>(null);
  const [confirmationPhrase, setConfirmationPhrase] = useState("");
  const [applyResult, setApplyResult] = useState<WordPressDraftUpdateApplyResult | null>(null);
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
      const [loadedSettings, reviewList] = await Promise.all([
        apiRequest<WordPressSettings>("/api/wordpress/settings"),
        apiRequest<WordPressDraftReviewList>("/api/wordpress/draft-review")
      ]);
      setSettings(loadedSettings);
      setDrafts(reviewList.items);
      setSelectedPageId((current) => current ?? reviewList.items[0]?.page_id ?? null);
    } catch (err) {
      setError(messageFrom(err, "Unable to load the WordPress draft update sandbox."));
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
    setApplyResult(null);
    try {
      const result = await apiRequest<WordPressDraftUpdateDryRun>(
        `/api/wordpress/draft-update/dry-run/${selectedPageId}`,
        { method: "POST" }
      );
      setDryRun(result);
      setMessage(
        result.ready
          ? "Dry run passed. This did not update WordPress."
          : "Dry run completed. One or more gates are blocked."
      );
    } catch (err) {
      setError(messageFrom(err, "Unable to run the WordPress draft update dry run."));
    } finally {
      setBusy(null);
    }
  }

  async function applyUpdate() {
    if (!selectedPageId || !dryRun?.confirmation_token) return;
    setBusy("apply");
    setError(null);
    setMessage(null);
    try {
      const result = await apiRequest<WordPressDraftUpdateApplyResult>(
        `/api/wordpress/draft-update/apply/${selectedPageId}`,
        {
          method: "POST",
          body: JSON.stringify({
            confirmation_token: dryRun.confirmation_token,
            confirmation_phrase: confirmationPhrase
          })
        }
      );
      setApplyResult(result);
      setMessage("WordPress draft update completed. WordPress status remained draft.");
      await loadWorkspace();
    } catch (err) {
      setError(messageFrom(err, "Unable to apply the WordPress draft update."));
    } finally {
      setBusy(null);
    }
  }

  const selectedDraft = useMemo(
    () => drafts.find((item) => item.page_id === selectedPageId) ?? null,
    [drafts, selectedPageId]
  );

  return (
    <section className="page wordpressDraftUpdateSandboxPage">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Dry-run only</p>
          <h1>WordPress Draft Update Sandbox</h1>
          <p>Preview and validate updates for existing WordPress drafts without changing WordPress.</p>
        </div>
      </header>

      <div className="wordpressSafetyNotice">
        <LockKeyhole size={19} aria-hidden="true" />
        <div>
          <strong>Controlled draft-only update sandbox.</strong>
          <span>Apply stays locked until a dry run passes and the exact confirmation phrase is entered. No publishing, draft creation, deletion, media upload, or bulk update is available.</span>
        </div>
      </div>

      {message && <div className="successAlert">{message}</div>}
      {error && <div className="alert">{error}</div>}

      <section className="panel wordpressSessionPanel">
        <div className="panelHeader">
          <div>
            <h2>Credential Session Status</h2>
            <p>Dry run requires Sandbox mode and the WordPress application password in backend memory for the live GET check.</p>
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
              <h2>Select Existing Draft</h2>
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
                <div><dt>Original payload hash</dt><dd><code>{shortHash(selectedDraft.audit_payload_hash)}</code></dd></div>
              </dl>
              <div className="formActions">
                <button className="primaryButton buttonWithIcon" type="button" onClick={runDryRun} disabled={busy !== null}>
                  <ShieldCheck size={16} aria-hidden="true" />
                  {busy === "dry-run" ? "Running..." : "Run Update Dry Run"}
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
          <ComparisonPanel dryRun={dryRun} />
          <PayloadPanel dryRun={dryRun} />
        </div>
      )}
      {dryRun && (
        <ApplyPanel
          busy={busy === "apply"}
          confirmationPhrase={confirmationPhrase}
          dryRun={dryRun}
          applyResult={applyResult}
          onApply={applyUpdate}
          onConfirmationPhraseChange={setConfirmationPhrase}
        />
      )}
    </section>
  );
}

function GatePanel({ dryRun }: { dryRun: WordPressDraftUpdateDryRun | null }) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <h2>Gate Checklist</h2>
          <p>Every gate must pass before the controlled draft-only update can be applied.</p>
        </div>
        {dryRun ? (
          <span className={`statusBadge ${dryRun.ready ? "ready" : "warning"}`}>
            {dryRun.ready ? "Dry Run Ready" : "Blocked"}
          </span>
        ) : null}
      </div>
      {!dryRun ? (
        <p>Run a dry run to see the update gates.</p>
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

function ComparisonPanel({ dryRun }: { dryRun: WordPressDraftUpdateDryRun }) {
  const comparison = dryRun.comparison;
  return (
    <section className="panel wordpressComparisonPanel">
      <div className="panelHeader">
        <div>
          <h2>Original vs Current Atlas</h2>
          <p>Read-only comparison against the original successful create_draft audit.</p>
        </div>
        <span className={`statusBadge ${comparison.payload_changed_since_create ? "warning" : "ready"}`}>
          {comparison.payload_changed_since_create ? "Changed" : "Payload Match"}
        </span>
      </div>
      <dl className="comparisonList">
        <div><dt>Original create audit</dt><dd>{comparison.original_create_audit_id ?? "-"}</dd></div>
        <div><dt>Original payload hash</dt><dd><code>{comparison.original_payload_hash || "-"}</code></dd></div>
        <div><dt>Current payload hash</dt><dd><code>{comparison.current_payload_hash}</code></dd></div>
        <div><dt>Original draft hash</dt><dd><code>{comparison.original_draft_hash || "-"}</code></dd></div>
        <div><dt>Current draft hash</dt><dd><code>{comparison.current_draft_hash}</code></dd></div>
        <div><dt>Media reference hash</dt><dd><code>{comparison.media_reference_hash}</code></dd></div>
        <div><dt>Live WordPress status</dt><dd>{dryRun.live_status?.wordpress_status || dryRun.live_status?.error_message || "-"}</dd></div>
      </dl>
      {comparison.media_reference_warning && (
        <div className="inlineWarning">
          <AlertTriangle size={17} aria-hidden="true" />
          {comparison.media_reference_warning}
        </div>
      )}
      <h3>Changed Summary</h3>
      <ul className="plainList">
        {comparison.changed_summary.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      {dryRun.confirmation_phrase && (
        <div className="inlineSuccess">
          Confirmation phrase generated: <code>{dryRun.confirmation_phrase}</code>
        </div>
      )}
      {dryRun.confirmation_token && (
        <p className="helperText">Signed token generated. It expires and is valid only for this page and current payload hash.</p>
      )}
    </section>
  );
}

function PayloadPanel({ dryRun }: { dryRun: WordPressDraftUpdateDryRun }) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <h2>Exact Draft Payload Preview</h2>
          <p>Status is forced to draft. This payload was not sent as an update.</p>
        </div>
        <span className="statusBadge ready">Status: {dryRun.payload.status}</span>
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

function ApplyPanel({
  applyResult,
  busy,
  confirmationPhrase,
  dryRun,
  onApply,
  onConfirmationPhraseChange
}: {
  applyResult: WordPressDraftUpdateApplyResult | null;
  busy: boolean;
  confirmationPhrase: string;
  dryRun: WordPressDraftUpdateDryRun;
  onApply: () => void;
  onConfirmationPhraseChange: (value: string) => void;
}) {
  const expectedPhrase = dryRun.confirmation_phrase ?? "";
  const phraseMatches = Boolean(expectedPhrase) && confirmationPhrase.trim() === expectedPhrase;
  const canApply = dryRun.ready && Boolean(dryRun.confirmation_token) && phraseMatches && !busy;

  return (
    <section className="panel wordpressApplyPanel">
      <div className="panelHeader">
        <div>
          <h2>Controlled Draft Update Apply</h2>
          <p>Updates existing WordPress DRAFT only. Does not publish.</p>
        </div>
        <span className={`statusBadge ${canApply ? "ready" : "warning"}`}>
          {canApply ? "Ready To Apply" : "Locked"}
        </span>
      </div>
      <div className="wordpressSafetyNotice compact">
        <LockKeyhole size={18} aria-hidden="true" />
        <div>
          <strong>One page only. Status is forced to draft.</strong>
          <span>No publishing, media upload, deletion, draft creation, or bulk update controls are available.</span>
        </div>
      </div>
      {dryRun.comparison.media_reference_warning && (
        <div className="inlineWarning">
          <AlertTriangle size={17} aria-hidden="true" />
          Media references and assignment-level alt text may not be fully represented in the payload hash. Review the WordPress draft visually after update.
        </div>
      )}
      <label>
        Type the exact confirmation phrase
        <input
          value={confirmationPhrase}
          onChange={(event) => onConfirmationPhraseChange(event.target.value)}
          placeholder={expectedPhrase || "Run a passing dry run first"}
          disabled={!dryRun.ready}
        />
      </label>
      <div className="formActions">
        <button className="primaryButton buttonWithIcon" type="button" onClick={onApply} disabled={!canApply}>
          <ShieldCheck size={16} aria-hidden="true" />
          {busy ? "Applying..." : "Apply Draft Update"}
        </button>
      </div>
      {!dryRun.ready && <p className="helperText">Apply is disabled because the dry run gates are not all passing.</p>}
      {dryRun.ready && !phraseMatches && (
        <p className="helperText">Apply remains disabled until the exact confirmation phrase is entered.</p>
      )}
      {applyResult && (
        <div className="inlineSuccess">
          Updated WordPress post {applyResult.wordpress_post_id}; returned status {applyResult.wordpress_status}. Audit {applyResult.audit_id} recorded.
        </div>
      )}
    </section>
  );
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function yesNo(value: boolean) {
  return value ? "Yes" : "No";
}

function shortHash(value?: string | null) {
  return value ? value.slice(0, 12) : "-";
}

function messageFrom(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export default WordPressDraftUpdateSandboxPage;
