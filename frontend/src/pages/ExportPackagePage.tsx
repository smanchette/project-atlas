import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  CheckCircle2,
  Clipboard,
  Download,
  FileJson,
  Image as ImageIcon,
  Plug
} from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { apiRequest, requestPageExport } from "../api";
import type { PageExportPackage } from "../types";

function ExportPackagePage() {
  const { id } = useParams();
  const pageId = Number(id);
  const [exportPackage, setExportPackage] = useState<PageExportPackage | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!pageId) {
      setError("Invalid generated page ID.");
      return;
    }
    apiRequest<PageExportPackage>(`/api/generated-pages/${pageId}/export-package`)
      .then(setExportPackage)
      .catch((err) => setError(err instanceof Error ? err.message : "Unable to load export package."));
  }, [pageId]);

  async function copyValue(key: string, value: string) {
    try {
      await copyText(value);
      setCopied(key);
      setMessage("Copied to clipboard.");
      window.setTimeout(() => setCopied(null), 1600);
    } catch {
      setError("Unable to copy this value.");
    }
  }

  async function downloadExport() {
    if (!exportPackage) return;
    setDownloading(true);
    setError(null);
    try {
      const download = await requestPageExport(exportPackage.page_id);
      downloadBlob(download.blob, download.fileName);
      setMessage(`${download.fileName} downloaded.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to download export JSON.");
    } finally {
      setDownloading(false);
    }
  }

  if (error && !exportPackage) {
    return <main className="exportPackageStandalone"><div className="alert">{error}</div></main>;
  }
  if (!exportPackage) {
    return <main className="exportPackageStandalone"><div className="panel">Loading export package...</div></main>;
  }

  const blockerCount = exportPackage.warnings.filter((item) => item.severity === "blocker").length;
  const warningCount = exportPackage.warnings.filter((item) => item.severity === "warning").length;
  const jsonLdText = JSON.stringify(exportPackage.json_ld, null, 2);

  return (
    <section className="page exportPackagePage">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Review-only connector preparation</p>
          <h1>Export Package</h1>
          <p className="exportPackageTitle">{exportPackage.page_title}</p>
        </div>
        <div className="headerActions">
          <Link className="secondaryButton buttonWithIcon" to="/generated-pages">
            <ArrowLeft size={16} aria-hidden="true" /> Generated Pages
          </Link>
          <Link className="secondaryButton buttonWithIcon" to={`/wordpress-sandbox?page=${exportPackage.page_id}`}>
            <Plug size={16} aria-hidden="true" /> Open WordPress Draft Sandbox
          </Link>
          <button className="primaryButton buttonWithIcon" type="button" onClick={downloadExport} disabled={downloading}>
            <Download size={16} aria-hidden="true" />
            {downloading ? "Downloading..." : "Download Export JSON"}
          </button>
        </div>
      </header>

      <div className="exportNotice">
        <FileJson size={18} aria-hidden="true" />
        Export preview only. Atlas will not publish or call WordPress.
      </div>
      {message && <div className="successAlert">{message}</div>}
      {error && <div className="alert">{error}</div>}

      <div className="exportStatusGrid">
        <StatusTile label="Export readiness" value={exportPackage.export_ready ? "Ready" : "Blocked"} ready={exportPackage.export_ready} />
        <StatusTile label="Page status" value={humanize(exportPackage.page_status)} />
        <StatusTile label="QA status" value={humanize(exportPackage.qa_status)} ready={exportPackage.qa_status === "ready"} />
        <StatusTile label="Blockers" value={String(blockerCount)} ready={blockerCount === 0} />
        <StatusTile label="Warnings" value={String(warningCount)} ready={warningCount === 0} />
      </div>

      <section className="panel exportWarningsPanel">
        <div className="panelHeader">
          <div><h2>Readiness Warnings</h2><p>Advisory only. Nothing is changed automatically.</p></div>
          <span className="countBadge">{exportPackage.warnings.length} items</span>
        </div>
        {exportPackage.warnings.length === 0 ? (
          <p className="exportPass"><CheckCircle2 size={17} aria-hidden="true" /> No export warnings.</p>
        ) : (
          <div className="exportWarningList">
            {exportPackage.warnings.map((warning) => (
              <article key={warning.code} className={warning.severity}>
                <AlertTriangle size={17} aria-hidden="true" />
                <div><strong>{humanize(warning.code)}</strong><p>{warning.message}</p></div>
              </article>
            ))}
          </div>
        )}
      </section>

      <div className="exportTwoColumn">
        <section className="panel">
          <h2>Slug and Canonical Preview</h2>
          <CopyRow label="Current URL slug" value={exportPackage.url_slug} copyKey="slug" copied={copied} onCopy={copyValue} />
          <CopyRow label="Suggested URL slug" value={exportPackage.seo.suggested_url_slug} copyKey="suggested_slug" copied={copied} onCopy={copyValue} />
          <CopyRow label="Canonical URL" value={exportPackage.canonical_url_preview} copyKey="canonical" copied={copied} onCopy={copyValue} />
          {exportPackage.slug_conflicts.length > 0 && (
            <p className="fieldWarning">Conflicts with page IDs: {exportPackage.slug_conflicts.join(", ")}</p>
          )}
        </section>
        <section className="panel">
          <h2>Page Context</h2>
          <dl className="detailsList compact">
            <div><dt>Business</dt><dd>{exportPackage.business_name}</dd></div>
            <div><dt>Service</dt><dd>{exportPackage.service}</dd></div>
            <div><dt>Location</dt><dd>{exportPackage.city}, {exportPackage.state} · {exportPackage.county}</dd></div>
            <div><dt>Phone</dt><dd>{exportPackage.phone ?? "-"}</dd></div>
            <div><dt>License / Operator</dt><dd>{exportPackage.license_number ?? "-"} · {exportPackage.certified_operator ?? "-"}</dd></div>
          </dl>
        </section>
      </div>

      <section className="panel">
        <h2>SEO and Social Metadata</h2>
        <div className="exportMetadataList">
          <CopyRow label={`Meta title (${exportPackage.seo.meta_title.length}/60)`} value={exportPackage.seo.meta_title} copyKey="meta_title" copied={copied} onCopy={copyValue} />
          <CopyRow label={`Meta description (${exportPackage.seo.meta_description.length}/160)`} value={exportPackage.seo.meta_description} copyKey="meta_description" copied={copied} onCopy={copyValue} />
          <CopyRow label="Social title" value={exportPackage.seo.social_title} copyKey="social_title" copied={copied} onCopy={copyValue} />
          <CopyRow label="Social description" value={exportPackage.seo.social_description} copyKey="social_description" copied={copied} onCopy={copyValue} />
        </div>
      </section>

      <section className="panel">
        <h2>Structured Content</h2>
        <div className="exportContentSections">
          <article><h3>H1</h3><p>{exportPackage.h1}</p></article>
          {Object.entries(exportPackage.content_sections).map(([key, value]) => (
            <article key={key}><h3>{humanize(key)}</h3><p>{value}</p></article>
          ))}
          <article><h3>CTA Block</h3><p>{exportPackage.cta_block}</p></article>
        </div>
        <h3 className="exportFaqHeading">FAQs</h3>
        <div className="exportFaqList">
          {exportPackage.faq_items.map((item) => (
            <article key={item.question}><strong>{item.question}</strong><p>{item.answer}</p></article>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panelHeader"><div><h2>Assigned Media References</h2><p>References and reviewed alt text only. No image binaries are included.</p></div><span className="countBadge">{exportPackage.assigned_media.length} images</span></div>
        <div className="exportMediaList">
          {exportPackage.assigned_media.map((media) => (
            <article key={`${media.image_id}-${media.image_role}`}>
              <ImageIcon size={18} aria-hidden="true" />
              <div><strong>{media.image_title || `Image ${media.image_id}`}</strong><span>{humanize(media.image_role)} · {media.alt_text || "Missing alt text"}</span><small>{media.optimized_url || media.asset_url || "No asset URL"}</small></div>
            </article>
          ))}
          {exportPackage.assigned_media.length === 0 && <p>No media references assigned.</p>}
        </div>
      </section>

      <section className="panel">
        <div className="panelHeader"><div><h2>JSON-LD Schema Preview</h2><p>Preview only. Not injected into any public page.</p></div>
          <button className="secondaryButton buttonWithIcon" type="button" onClick={() => copyValue("json_ld", jsonLdText)}>
            {copied === "json_ld" ? <Check size={15} aria-hidden="true" /> : <Clipboard size={15} aria-hidden="true" />}
            {copied === "json_ld" ? "Copied" : "Copy JSON-LD"}
          </button>
        </div>
        <pre className="jsonLdPreview"><code>{jsonLdText}</code></pre>
      </section>
    </section>
  );
}

function CopyRow({ label, value, copyKey, copied, onCopy }: { label: string; value: string; copyKey: string; copied: string | null; onCopy: (key: string, value: string) => Promise<void> }) {
  return (
    <div className="exportCopyRow">
      <div><span>{label}</span><code>{value || "Missing"}</code></div>
      <button type="button" className="iconButton" disabled={!value} onClick={() => onCopy(copyKey, value)} title={`Copy ${label}`} aria-label={`Copy ${label}`}>
        {copied === copyKey ? <Check size={15} aria-hidden="true" /> : <Clipboard size={15} aria-hidden="true" />}
      </button>
    </div>
  );
}

function StatusTile({ label, value, ready }: { label: string; value: string; ready?: boolean }) {
  return <div className={`exportStatusTile ${ready === true ? "ready" : ready === false ? "blocked" : ""}`}><span>{label}</span><strong>{value}</strong></div>;
}

async function copyText(value: string) {
  const textArea = document.createElement("textarea");
  textArea.value = value;
  textArea.style.position = "fixed";
  textArea.style.left = "-9999px";
  textArea.style.top = "0";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  textArea.setSelectionRange(0, value.length);
  const handleCopy = (event: ClipboardEvent) => {
    event.clipboardData?.setData("text/plain", value);
    event.preventDefault();
  };
  document.addEventListener("copy", handleCopy);
  const copied = document.execCommand("copy");
  document.removeEventListener("copy", handleCopy);
  textArea.remove();
  if (copied) return;
  await navigator.clipboard.writeText(value);
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

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}

export default ExportPackagePage;
