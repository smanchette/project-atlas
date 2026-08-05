import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { CheckCircle2, Palette, ShieldCheck } from "lucide-react";

import { apiRequest } from "../api";
import { bindWebsiteContext } from "../components/brandAssetContext";
import type {
  ThemeDesignTokens,
  Website,
  WebsiteContext,
  WebsiteTheme,
  WebsiteThemeState,
} from "../types";

export default function ThemesPage() {
  const [websites, setWebsites] = useState<Website[]>([]);
  const [websiteId, setWebsiteId] = useState(0);
  const [context, setContext] = useState<WebsiteContext | null>(null);
  const [themes, setThemes] = useState<WebsiteTheme[]>([]);
  const [themeState, setThemeState] = useState<WebsiteThemeState | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const loadGeneration = useRef(0);

  useEffect(() => {
    async function loadWebsites() {
      try {
        const rows = await apiRequest<Website[]>("/api/websites");
        setWebsites(rows);
        setWebsiteId(rows[0]?.id ?? 0);
      } catch (value) {
        setError(value instanceof Error ? value.message : "Unable to load Websites.");
      }
    }
    void loadWebsites();
  }, []);

  useEffect(() => {
    if (websiteId) void loadThemeContext(websiteId);
    else clearThemeContext();
  }, [websiteId, websites]);

  function clearThemeContext() {
    loadGeneration.current += 1;
    setContext(null);
    setThemes([]);
    setThemeState(null);
  }

  async function loadThemeContext(selectedWebsiteId: number) {
    const generation = ++loadGeneration.current;
    const website = websites.find((item) => item.id === selectedWebsiteId);
    if (!website) {
      clearThemeContext();
      return;
    }
    setWorking(true);
    setError("");
    setContext(null);
    setThemes([]);
    setThemeState(null);
    try {
      const nextContext = await apiRequest<WebsiteContext>(
        `/api/websites/${selectedWebsiteId}/context`,
      );
      const binding = bindWebsiteContext(website, nextContext);
      const [themeRows, nextState] = await Promise.all([
        apiRequest<WebsiteTheme[]>(`/api/websites/${selectedWebsiteId}/themes`),
        apiRequest<WebsiteThemeState>(
          `/api/websites/${selectedWebsiteId}/theme-selection`,
        ),
      ]);
      if (
        themeRows.some(
          (theme) =>
            theme.website_id !== binding.websiteId ||
            theme.business_id !== binding.businessId ||
            theme.brand_id !== binding.brandId,
        ) ||
        nextState.website_id !== binding.websiteId
      ) {
        throw new Error("Theme results crossed the authoritative Website Context boundary.");
      }
      if (generation !== loadGeneration.current) return;
      setContext(nextContext);
      setThemes(themeRows);
      setThemeState(nextState);
    } catch (value) {
      if (generation !== loadGeneration.current) return;
      setError(
        value instanceof Error
          ? value.message
          : "Unable to load the governed Theme context.",
      );
    } finally {
      if (generation === loadGeneration.current) setWorking(false);
    }
  }

  async function reload() {
    if (websiteId) await loadThemeContext(websiteId);
  }

  async function createTheme(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!context) {
      setError("Resolve an authoritative Website Context before creating a Theme.");
      return;
    }
    const form = new FormData(event.currentTarget);
    let designTokens: ThemeDesignTokens;
    try {
      designTokens = parseDesignTokens(String(form.get("design_tokens") ?? ""));
    } catch (value) {
      setError(value instanceof Error ? value.message : "Design-token JSON is invalid.");
      return;
    }
    const replacement = Number(form.get("replaces_theme_id") || 0);
    setWorking(true);
    setError("");
    setMessage("");
    try {
      const created = await apiRequest<WebsiteTheme>(
        `/api/websites/${websiteId}/themes`,
        {
          method: "POST",
          body: JSON.stringify({
            theme_key: String(form.get("theme_key") ?? "").trim(),
            theme_name: String(form.get("theme_name") ?? "").trim(),
            description: String(form.get("description") ?? "").trim() || null,
            token_contract_version: 1,
            design_tokens: designTokens,
            created_by: String(form.get("created_by") ?? "").trim(),
            provenance_type: String(form.get("provenance_type") ?? "").trim(),
            provenance_notes: String(form.get("provenance_notes") ?? "").trim(),
            replaces_theme_id: replacement || null,
          }),
        },
      );
      setMessage(`${created.theme_name} version ${created.version} is pending approval.`);
      event.currentTarget.reset();
      await reload();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Theme creation failed.");
    } finally {
      setWorking(false);
    }
  }

  async function approve(theme: WebsiteTheme) {
    if (!isOwnedTheme(theme, websiteId)) return;
    const approvedBy = window.prompt("Operator name for Theme approval provenance:");
    if (!approvedBy?.trim()) return;
    await mutate(
      `/api/themes/${theme.id}/approve`,
      { approved_by: approvedBy.trim() },
      `${theme.theme_name} version ${theme.version} approved.`,
    );
  }

  async function selectTheme(theme: WebsiteTheme) {
    if (!isOwnedTheme(theme, websiteId)) return;
    const selectedBy = window.prompt("Operator name for Theme selection provenance:");
    if (!selectedBy?.trim()) return;
    const rationale = window.prompt("Rationale for selecting this Website Theme:");
    if (!rationale?.trim()) return;
    await mutate(
      `/api/websites/${websiteId}/theme-selection`,
      {
        theme_id: theme.id,
        selected_by: selectedBy.trim(),
        rationale: rationale.trim(),
      },
      `${theme.theme_name} version ${theme.version} selected for this Website.`,
    );
  }

  async function retire(theme: WebsiteTheme) {
    if (!isOwnedTheme(theme, websiteId)) return;
    const retiredBy = window.prompt("Operator name for Theme retirement provenance:");
    if (!retiredBy?.trim()) return;
    const rationale = window.prompt("Why is this Theme version being retired?");
    if (!rationale?.trim()) return;
    await mutate(
      `/api/themes/${theme.id}/retire`,
      { retired_by: retiredBy.trim(), rationale: rationale.trim() },
      `${theme.theme_name} version ${theme.version} retired with history preserved.`,
    );
  }

  async function mutate(path: string, payload: object, successMessage: string) {
    setWorking(true);
    setError("");
    setMessage("");
    try {
      await apiRequest(path, { method: "POST", body: JSON.stringify(payload) });
      setMessage(successMessage);
      await reload();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Theme operation failed.");
    } finally {
      setWorking(false);
    }
  }

  const activeTheme = useMemo(
    () => themes.find((theme) => theme.id === themeState?.active?.theme_id) ?? null,
    [themeState?.active?.theme_id, themes],
  );

  return (
    <section className="page themesPage">
      <header className="pageHeader">
        <div>
          <span className="eyebrow">Website presentation governance</span>
          <h1>Themes &amp; Design Tokens</h1>
          <p>
            Govern one Website-scoped presentation contract. Components consume the
            selected Theme; Themes never own business facts, content, or Brand Assets.
          </p>
        </div>
      </header>

      {error && <div className="errorBanner">{error}</div>}
      {message && <div className="successBanner">{message}</div>}

      <section className="panel">
        <h2>Authoritative Website Context</h2>
        <label>
          Website
          <select
            value={websiteId}
            disabled={working}
            onChange={(event) => {
              setMessage("");
              setWebsiteId(Number(event.target.value));
            }}
          >
            {!websites.length && <option value={0}>No Websites available</option>}
            {websites.map((website) => (
              <option key={website.id} value={website.id}>
                {website.website_name} ({website.domain})
              </option>
            ))}
          </select>
        </label>
        {context && (
          <dl className="detailGrid themeContextSummary">
            <div><dt>Business</dt><dd>{context.business.company_name}</dd></div>
            <div><dt>Brand</dt><dd>{context.brand.public_name}</dd></div>
            <div><dt>Website</dt><dd>{context.website.website_name}</dd></div>
            <div>
              <dt>Current presentation</dt>
              <dd>
                {themeState?.resolved.fallback_used
                  ? "Neutral Atlas fallback - Theme selection required"
                  : `${activeTheme?.theme_name ?? "Selected Theme"} v${activeTheme?.version ?? "?"}`}
              </dd>
            </div>
          </dl>
        )}
      </section>

      <section className="panel">
        <h2><Palette size={20} aria-hidden="true" /> Governed Theme versions</h2>
        {!themes.length && !working && (
          <p className="helperText">No governed Theme exists for this Website.</p>
        )}
        <div className="themeGrid">
          {themes.map((theme) => {
            const selected = themeState?.active?.theme_id === theme.id;
            return (
              <article className="themeCard" key={theme.id}>
                <div className="themeCardHeader">
                  <div>
                    <span className={`statusBadge ${theme.approval_status}`}>
                      {humanize(theme.approval_status)}
                    </span>
                    <h3>{theme.theme_name} <small>v{theme.version}</small></h3>
                  </div>
                  {selected && <span className="readinessStatus ready"><CheckCircle2 size={15} /> Selected</span>}
                </div>
                <p>{theme.description || "No description recorded."}</p>
                <dl className="themeEvidence">
                  <div><dt>Theme key</dt><dd>{theme.theme_key}</dd></div>
                  <div><dt>Token contract</dt><dd>v{theme.token_contract_version}</dd></div>
                  <div><dt>Token SHA-256</dt><dd><code>{theme.token_hash_sha256}</code></dd></div>
                  <div><dt>Lifecycle</dt><dd>{humanize(theme.lifecycle_status)}</dd></div>
                  <div><dt>Created by</dt><dd>{theme.created_by}</dd></div>
                  <div><dt>Provenance</dt><dd>{humanize(theme.provenance_type)} - {theme.provenance_notes}</dd></div>
                </dl>
                <div className="formActions">
                  {theme.approval_status !== "approved" && theme.lifecycle_status !== "retired" && (
                    <button disabled={working} onClick={() => void approve(theme)}>
                      <ShieldCheck size={16} /> Approve
                    </button>
                  )}
                  {canSelectTheme(theme, selected) && (
                    <button className="primaryButton" disabled={working} onClick={() => void selectTheme(theme)}>
                      Select for Website
                    </button>
                  )}
                  {theme.lifecycle_status !== "retired" && !selected && (
                    <button disabled={working} onClick={() => void retire(theme)}>Retire</button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
        <p className="helperText">
          Selection history: {themeState?.history.length ?? 0} durable record(s).
          Replacing a selection preserves history and intentionally stales bound compositions.
        </p>
      </section>

      <section className="panel">
        <h2>Create governed Theme version</h2>
        <p>
          Submit the complete typed token contract. Server validation rejects unknown,
          unsafe, incomplete, or inaccessible values before approval.
        </p>
        {!context ? (
          <p className="helperText">Resolve a Website Context before creating a Theme.</p>
        ) : (
          <form onSubmit={createTheme}>
            <div className="fieldGrid">
              <label>Theme key<input name="theme_key" pattern="[a-z0-9_-]+" required /></label>
              <label>Theme name<input name="theme_name" required /></label>
              <label>
                Explicit replacement
                <select name="replaces_theme_id">
                  <option value="">New Theme key</option>
                  {themes.map((theme) => (
                    <option key={theme.id} value={theme.id}>{theme.theme_name} v{theme.version}</option>
                  ))}
                </select>
              </label>
              <label>Creator / operator<input name="created_by" required /></label>
              <label>Provenance classification<input name="provenance_type" required /></label>
              <label>Provenance notes<textarea name="provenance_notes" required /></label>
              <label>Description<textarea name="description" /></label>
            </div>
            <label>
              Typed design-token contract (JSON)
              <textarea
                className="themeTokenEditor"
                name="design_tokens"
                spellCheck={false}
                required
                placeholder="Paste the complete governed ThemeDesignTokens JSON object."
              />
            </label>
            <button className="primaryButton" disabled={working}>Create pending Theme</button>
          </form>
        )}
      </section>
    </section>
  );
}

export function parseDesignTokens(value: string): ThemeDesignTokens {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error("Design-token input must be valid JSON.");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Design-token input must be one JSON object.");
  }
  return parsed as ThemeDesignTokens;
}

function isOwnedTheme(theme: WebsiteTheme, websiteId: number) {
  return theme.website_id === websiteId;
}

export function canSelectTheme(theme: WebsiteTheme, selected: boolean) {
  return (
    theme.approval_status === "approved" &&
    theme.lifecycle_status === "available" &&
    !selected
  );
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}
