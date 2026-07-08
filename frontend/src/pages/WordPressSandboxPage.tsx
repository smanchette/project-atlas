import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Eye,
  FileJson,
  LockKeyhole,
  Plug,
  Save,
  Send
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import { apiRequest } from "../api";
import type {
  GeneratedPage,
  WordPressConnectionResult,
  WordPressDraftCreateResult,
  WordPressDraftDryRun,
  WordPressPayloadPreview,
  WordPressPublishingMode,
  WordPressSettings
} from "../types";

type SettingsForm = {
  site_url: string;
  username: string;
  application_password: string;
  publishing_mode: WordPressPublishingMode;
  clear_application_password: boolean;
};

const emptyForm: SettingsForm = {
  site_url: "",
  username: "",
  application_password: "",
  publishing_mode: "disabled",
  clear_application_password: false
};

function WordPressSandboxPage() {
  const [searchParams] = useSearchParams();
  const requestedPageId = Number(searchParams.get("page") ?? 0);
  const [settings, setSettings] = useState<WordPressSettings | null>(null);
  const [form, setForm] = useState<SettingsForm>(emptyForm);
  const [pages, setPages] = useState<GeneratedPage[]>([]);
  const [selectedPageId, setSelectedPageId] = useState(requestedPageId);
  const [preview, setPreview] = useState<WordPressPayloadPreview | null>(null);
  const [connection, setConnection] = useState<WordPressConnectionResult | null>(null);
  const [lastConnectionTestAt, setLastConnectionTestAt] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState<WordPressDraftDryRun | null>(null);
  const [confirmationPhrase, setConfirmationPhrase] = useState("");
  const [createResult, setCreateResult] = useState<WordPressDraftCreateResult | null>(null);
  const [busy, setBusy] = useState<"save" | "test" | "preview" | "dry-run" | "create" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      apiRequest<WordPressSettings>("/api/wordpress/settings"),
      apiRequest<GeneratedPage[]>("/api/generated-pages")
    ])
      .then(([loadedSettings, loadedPages]) => {
        setSettings(loadedSettings);
        setForm({
          ...emptyForm,
          site_url: loadedSettings.site_url,
          username: loadedSettings.username,
          publishing_mode: loadedSettings.publishing_mode
        });
        setPages(loadedPages);
        if (!requestedPageId && loadedPages.length > 0) {
          setSelectedPageId(loadedPages[0].id);
        }
      })
      .catch((err) => setError(messageFrom(err, "Unable to load the WordPress sandbox.")));
  }, [requestedPageId]);

  useEffect(() => {
    if (!selectedPageId) return;
    setDryRun(null);
    setConfirmationPhrase("");
    setCreateResult(null);
    setBusy("preview");
    setError(null);
    apiRequest<WordPressPayloadPreview>(
      `/api/wordpress/pages/${selectedPageId}/payload-preview`
    )
      .then(setPreview)
      .catch((err) => setError(messageFrom(err, "Unable to build the payload preview.")))
      .finally(() => setBusy(null));
  }, [selectedPageId]);

  async function saveSettings(event: React.FormEvent) {
    event.preventDefault();
    setBusy("save");
    setError(null);
    setMessage(null);
    try {
      const saved = await apiRequest<WordPressSettings>("/api/wordpress/settings", {
        method: "PUT",
        body: JSON.stringify(form)
      });
      setSettings(saved);
      setForm((current) => ({
        ...current,
        application_password: "",
        clear_application_password: false
      }));
      setMessage(
        form.application_password
          ? "Password stored in backend memory for this running backend session. No WordPress content was created."
          : saved.has_application_password
            ? "Settings saved. Password is still stored in backend memory for this running backend session."
            : "Settings saved. No password is currently stored in backend memory."
      );
    } catch (err) {
      setError(messageFrom(err, "Unable to save WordPress settings."));
    } finally {
      setBusy(null);
    }
  }

  async function testConnection() {
    setBusy("test");
    setError(null);
    setMessage(null);
    try {
      const result = await apiRequest<WordPressConnectionResult>(
        "/api/wordpress/test-connection",
        { method: "POST" }
      );
      setConnection(result);
      setLastConnectionTestAt(new Date().toISOString());
    } catch (err) {
      setError(messageFrom(err, "Unable to test the WordPress connection."));
    } finally {
      setBusy(null);
    }
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
          ? "Dry run passed. Review the exact payload and complete the confirmation step."
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
      setMessage(`WordPress draft ${result.wordpress_post_id} was created. It was not published.`);
      setDryRun(null);
      setConfirmationPhrase("");
    } catch (err) {
      setError(messageFrom(err, "WordPress draft creation was blocked or failed."));
    } finally {
      setBusy(null);
    }
  }

  const selectedPage = useMemo(
    () => pages.find((page) => page.id === selectedPageId),
    [pages, selectedPageId]
  );

  return (
    <section className="page wordpressSandboxPage">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Controlled connector workspace</p>
          <h1>WordPress Sandbox</h1>
          <p>Test REST access, inspect payloads, and create explicitly confirmed drafts only.</p>
        </div>
      </header>

      <div className="wordpressSafetyNotice">
        <LockKeyhole size={19} aria-hidden="true" />
        <div>
          <strong>Sandbox only. Atlas can create a WordPress draft only after every safety gate passes.</strong>
          <span>Publishing, updates, deletion, media upload, and bulk WordPress actions are unavailable.</span>
        </div>
      </div>
      {message && <div className="successAlert">{message}</div>}
      {error && <div className="alert">{error}</div>}

      <div className="wordpressSettingsGrid">
        <form className="panel wordpressSettingsForm" onSubmit={saveSettings}>
          <div className="panelHeader">
            <div>
              <h2>Connection Settings</h2>
              <p>Application passwords are held in backend process memory only.</p>
            </div>
            <span className={`statusBadge ${form.publishing_mode === "disabled" ? "muted" : "warning"}`}>
              {humanize(form.publishing_mode)}
            </span>
          </div>
          <label>
            WordPress site URL
            <input
              type="url"
              value={form.site_url}
              placeholder="https://example.com"
              onChange={(event) => setForm({ ...form, site_url: event.target.value })}
            />
          </label>
          <label>
            Username
            <input
              value={form.username}
              autoComplete="username"
              onChange={(event) => setForm({ ...form, username: event.target.value })}
            />
          </label>
          <label>
            Application password
            <input
              type="password"
              value={form.application_password}
              autoComplete="new-password"
              placeholder={settings?.has_application_password ? "Stored in process memory; leave blank to keep" : "Local development only"}
              onChange={(event) => setForm({ ...form, application_password: event.target.value })}
            />
          </label>
          <label>
            Publishing mode
            <select
              value={form.publishing_mode}
              onChange={(event) =>
                setForm({
                  ...form,
                  publishing_mode: event.target.value as WordPressPublishingMode
                })
              }
            >
              <option value="disabled">Disabled</option>
              <option value="sandbox">Sandbox</option>
              <option value="draft_only_future">Draft-only future placeholder</option>
            </select>
          </label>
          <label className="checkboxRow">
            <input
              type="checkbox"
              checked={form.clear_application_password}
              onChange={(event) =>
                setForm({ ...form, clear_application_password: event.target.checked })
              }
            />
            Clear the process-memory application password
          </label>
          <div className="formActions">
            <button className="primaryButton buttonWithIcon" type="submit" disabled={busy !== null}>
              <Save size={16} aria-hidden="true" />
              {busy === "save" ? "Saving..." : "Save Settings"}
            </button>
            <button className="secondaryButton buttonWithIcon" type="button" onClick={testConnection} disabled={busy !== null}>
              <Plug size={16} aria-hidden="true" />
              {busy === "test" ? "Testing..." : "Test Connection"}
            </button>
          </div>
          <p className="wordpressSecretNote">
            <LockKeyhole size={14} aria-hidden="true" />
            The password is never returned to the browser, written to Atlas records, or included in backups.
          </p>
        </form>

        <WordPressSessionStatusPanel
          settings={settings}
          connection={connection}
          lastConnectionTestAt={lastConnectionTestAt}
        />

        <section className="panel wordpressConnectionPanel">
          <h2>Connection Result</h2>
          {!connection ? (
            <p>No connection test has been run in this browser session.</p>
          ) : (
            <>
              <div className={`connectionHeadline ${connection.connection_status}`}>
                {connection.connection_status === "connected" ? (
                  <CheckCircle2 size={20} aria-hidden="true" />
                ) : (
                  <AlertTriangle size={20} aria-hidden="true" />
                )}
                <strong>{connectionSummary(connection)}</strong>
              </div>
              <dl className="detailsList compact">
                <div><dt>Credentials present</dt><dd>{yesNo(connection.credentials_present)}</dd></div>
                <div><dt>REST API reachable</dt><dd>{yesNo(connection.rest_api_reachable)}</dd></div>
                <div><dt>Authenticated</dt><dd>{yesNo(connection.authenticated)}</dd></div>
                <div><dt>Site name</dt><dd>{connection.site_name || "-"}</dd></div>
                <div><dt>Endpoint</dt><dd>{connection.endpoint || "-"}</dd></div>
              </dl>
              {connection.error_message && <div className="inlineWarning">{connection.error_message}</div>}
            </>
          )}
        </section>
      </div>

      <section className="panel wordpressPagePicker">
        <div>
          <h2>WordPress Draft Payload Preview</h2>
          <p>Approved, QA-ready pages are eligible. Other pages remain visible so blocked gates can be diagnosed.</p>
        </div>
        <label>
          Generated page
          <select
            value={selectedPageId || ""}
            onChange={(event) => setSelectedPageId(Number(event.target.value))}
          >
            {pages.map((page) => (
              <option key={page.id} value={page.id}>
                {page.page_title} · {humanize(page.status)} · QA {humanize(page.qa_status)}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="panel wordpressDraftSandbox">
        <div className="panelHeader">
          <div>
            <p className="eyebrow">Explicitly gated write action</p>
            <h2>Draft Creation Sandbox</h2>
            <p>A dry run is required before Atlas can send one draft-page request.</p>
          </div>
          <button
            className="primaryButton buttonWithIcon"
            type="button"
            onClick={runDryRun}
            disabled={!selectedPageId || busy !== null}
          >
            <ClipboardCheck size={16} aria-hidden="true" />
            {busy === "dry-run" ? "Running Dry Run..." : "Run Dry Run"}
          </button>
        </div>

        {!dryRun && !createResult && (
          <div className="wordpressDraftEmpty">
            <LockKeyhole size={20} aria-hidden="true" />
            <div>
              <p>No creation is possible until a dry run validates the current page, QA, export package, slug, credentials, and payload.</p>
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
            <div className="wordpressGateList">
              {dryRun.gate_results.map((gate) => (
                <article key={gate.code} className={gate.passed ? "passed" : "failed"}>
                  {gate.passed ? <CheckCircle2 size={17} aria-hidden="true" /> : <AlertTriangle size={17} aria-hidden="true" />}
                  <div><strong>{gate.label}</strong><p>{gate.message}</p></div>
                </article>
              ))}
            </div>

            <div className="wordpressExactPayload">
              <div>
                <h3>Exact WordPress Draft Request</h3>
                <p>This is the complete JSON body Atlas would send to the fixed WordPress pages endpoint.</p>
              </div>
              <pre className="jsonLdPreview"><code>{JSON.stringify(dryRun.payload, null, 2)}</code></pre>
              <dl className="detailsList compact">
                <div><dt>Payload hash</dt><dd><code>{dryRun.payload_hash}</code></dd></div>
                <div><dt>Atlas draft hash</dt><dd><code>{dryRun.draft_hash}</code></dd></div>
                <div><dt>Confirmation expires</dt><dd>{dryRun.expires_at ? new Date(dryRun.expires_at).toLocaleString() : "-"}</dd></div>
              </dl>
            </div>

            <div className="wordpressCreateConfirmation">
              <AlertTriangle size={19} aria-hidden="true" />
              <div>
                <strong>This will create a DRAFT only in WordPress. It will not publish the page.</strong>
                {dryRun.ready ? (
                  <>
                    <label>
                      Type the confirmation phrase exactly
                      <code>{dryRun.confirmation_phrase}</code>
                      <input
                        value={confirmationPhrase}
                        onChange={(event) => setConfirmationPhrase(event.target.value)}
                        autoComplete="off"
                      />
                    </label>
                    <button
                      className="dangerButton buttonWithIcon"
                      type="button"
                      onClick={createDraft}
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
            WordPress draft {createResult.wordpress_post_id} was created with status draft. Audit #{createResult.audit_id}.
          </div>
        )}
      </section>

      {busy === "preview" && !preview && <div className="panel">Building payload preview...</div>}
      {preview && (
        <>
          <div className="wordpressPayloadSummary">
            <div><span>Title</span><strong>{preview.payload.title}</strong></div>
            <div><span>Slug</span><code>{preview.payload.slug}</code></div>
            <div><span>WordPress status</span><strong className="statusBadge muted">{preview.payload.status}</strong></div>
            <div><span>Featured media</span><strong>{preview.payload.featured_media_reference ? "Referenced" : "Not assigned"}</strong></div>
          </div>

          <div className="wordpressPreviewGrid">
            <section className="panel">
              <div className="panelHeader">
                <div><h2>Content HTML Preview</h2><p>Rendered in an isolated, script-disabled frame.</p></div>
                <Eye size={18} aria-hidden="true" />
              </div>
              <iframe
                className="wordpressContentFrame"
                title="WordPress content HTML preview"
                sandbox=""
                srcDoc={previewDocument(preview.payload.content)}
              />
            </section>
            <section className="panel">
              <h2>Payload Details</h2>
              <dl className="detailsList compact">
                <div><dt>Excerpt</dt><dd>{preview.payload.excerpt || "-"}</dd></div>
                <div><dt>Meta title</dt><dd>{preview.payload.meta.meta_title || "-"}</dd></div>
                <div><dt>Meta description</dt><dd>{preview.payload.meta.meta_description || "-"}</dd></div>
              </dl>
              <h3>Schema block preview</h3>
              <pre className="jsonLdPreview"><code>{JSON.stringify(preview.payload.schema_block_preview, null, 2)}</code></pre>
            </section>
          </div>

          <section className="panel wordpressWarningsPanel">
            <div className="panelHeader">
              <div><h2>Export Readiness Warnings</h2><p>Warnings are advisory and never auto-fix the draft.</p></div>
              <span className="countBadge">{preview.warnings.length} items</span>
            </div>
            {preview.warnings.length === 0 ? (
              <p className="exportPass"><CheckCircle2 size={17} aria-hidden="true" /> No export warnings.</p>
            ) : (
              <div className="exportWarningList">
                {preview.warnings.map((warning) => (
                  <article key={warning.code} className={warning.severity}>
                    <AlertTriangle size={17} aria-hidden="true" />
                    <div><strong>{humanize(warning.code)}</strong><p>{warning.message}</p></div>
                  </article>
                ))}
              </div>
            )}
            <div className="formActions">
              <Link className="secondaryButton buttonWithIcon" to={`/generated-pages/${preview.page_id}/export`}>
                <FileJson size={16} aria-hidden="true" /> View Export Package
              </Link>
              <Link className="secondaryButton buttonWithIcon" to={`/generated-pages/${preview.page_id}/preview`}>
                <Eye size={16} aria-hidden="true" /> Preview Page
              </Link>
            </div>
          </section>
        </>
      )}
      {selectedPage && !preview && busy !== "preview" && <div className="alert">No payload preview is available for {selectedPage.page_title}.</div>}
    </section>
  );
}

function previewDocument(content: string) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    body{font-family:Arial,sans-serif;color:#17201c;line-height:1.6;margin:0;padding:24px;background:#fff}
    h1{font-size:30px;line-height:1.2;margin:0 0 20px}h2{font-size:20px;margin:28px 0 8px}
    h3{font-size:16px;margin:18px 0 6px}p{margin:0 0 12px}
  </style></head><body>${content}</body></html>`;
}

function WordPressSessionStatusPanel({
  settings,
  connection,
  lastConnectionTestAt
}: {
  settings: WordPressSettings | null;
  connection: WordPressConnectionResult | null;
  lastConnectionTestAt: string | null;
}) {
  const passwordPresent = Boolean(settings?.has_application_password);
  return (
    <section className="panel wordpressSessionPanel">
      <div className="panelHeader">
        <div>
          <h2>Credential Session Status</h2>
          <p>Current backend-memory credential state.</p>
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
        <div><dt>REST API reachable</dt><dd>{connection ? yesNo(connection.rest_api_reachable) : "Unknown"}</dd></div>
        <div><dt>Authenticated</dt><dd>{connection ? yesNo(connection.authenticated) : "Unknown"}</dd></div>
        <div><dt>Last connection test</dt><dd>{lastConnectionTestAt ? new Date(lastConnectionTestAt).toLocaleString() : "Unknown"}</dd></div>
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

function messageFrom(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function yesNo(value: boolean) {
  return value ? "Yes" : "No";
}

function connectionSummary(connection: WordPressConnectionResult) {
  if (connection.connection_status === "disabled") return "Disabled";
  if (!connection.rest_api_reachable) return "REST Not Reachable";
  if (!connection.credentials_present) return "REST Reachable, Credentials Missing";
  if (!connection.authenticated) return "REST Reachable, Credentials Rejected";
  return "REST Reachable, Authenticated";
}

export default WordPressSandboxPage;
