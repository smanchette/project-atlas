import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Image, LockKeyhole, RefreshCw } from "lucide-react";

import { apiRequest } from "../api";
import type { WordPressMediaDryRun, WordPressMediaUploadResult } from "../types";

const PAGE_ID = 41;

export default function WordPressMediaSafetyPage() {
  const [dryRun, setDryRun] = useState<WordPressMediaDryRun | null>(null);
  const [phrase, setPhrase] = useState("");
  const [backup, setBackup] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WordPressMediaUploadResult | null>(null);
  const canUpload = useMemo(() => Boolean(
    dryRun?.ready && dryRun.confirmation_token && phrase === dryRun.confirmation_phrase && backup.trim()
  ), [dryRun, phrase, backup]);

  async function inspect() {
    setBusy(true); setError(null); setDryRun(null); setPhrase(""); setBackup(""); setResult(null);
    try {
      setDryRun(await apiRequest<WordPressMediaDryRun>(`/api/wordpress/media/dry-run/${PAGE_ID}`, { method: "POST" }));
    } catch (value) { setError(value instanceof Error ? value.message : "Media dry run failed."); }
    finally { setBusy(false); }
  }

  async function upload() {
    if (!canUpload || !dryRun?.confirmation_token) return;
    setBusy(true); setError(null);
    try {
      setResult(await apiRequest<WordPressMediaUploadResult>(`/api/wordpress/media/upload/${PAGE_ID}`, {
        method: "POST",
        body: JSON.stringify({ confirmation_token: dryRun.confirmation_token, confirmation_phrase: phrase, confirmed_backup_file: backup.trim() })
      }));
    } catch (value) { setError(value instanceof Error ? value.message : "Media upload was blocked."); }
    finally { setBusy(false); }
  }

  return <section className="page wordpressPublishSafetySandboxPage">
    <header className="pageHeader"><div><span className="eyebrow">Orlando only · page 41 · post 8</span><h1>WordPress Media Safety</h1><p>Inspect and, only after explicit confirmation, upload the single reviewed Orlando hero image. This never edits post content or sets a featured image.</p></div></header>
    <div className="wordpressSafetyNotice"><LockKeyhole size={22}/><div><strong>One-image safety boundary</strong><p>No bulk upload, derivatives, content insertion, featured-image assignment, post creation, deletion, or status change is available here.</p></div></div>
    <section className="panel">
      <h2>Fixed target</h2>
      <dl className="detailGrid"><div><dt>Atlas page</dt><dd>41 — Orlando</dd></div><div><dt>WordPress post</dt><dd>8 (must remain publish)</dd></div><div><dt>Assignment / image</dt><dd>1 / 1 — hero</dd></div></dl>
      <button className="primaryButton buttonWithIcon" disabled={busy} onClick={inspect}><RefreshCw size={16}/>Run media dry run</button>
    </section>
    {error && <div className="errorBanner"><AlertTriangle size={18}/>{error}</div>}
    {dryRun && <>
      <section className="panel"><h2>Read-only inspection</h2>
        <dl className="detailGrid"><div><dt>File</dt><dd>{dryRun.source_file_name}</dd></div><div><dt>MIME / size</dt><dd>{dryRun.mime_type} · {dryRun.file_size.toLocaleString()} bytes</dd></div><div><dt>Dimensions</dt><dd>{dryRun.width} × {dryRun.height}</dd></div><div><dt>SHA-256</dt><dd><code>{dryRun.checksum}</code></dd></div><div><dt>Reviewed alt text</dt><dd>{dryRun.alt_text}</dd></div><div><dt>Existing attachment</dt><dd>{dryRun.attachment_match.status}: {dryRun.attachment_match.message}</dd></div></dl>
        <div className="wordpressGateList">{dryRun.gate_results.map(g => <div key={g.code} className={g.passed ? "gateItem passed" : "gateItem blocked"}>{g.passed ? <CheckCircle2 size={17}/> : <AlertTriangle size={17}/>}<div><strong>{g.label}</strong><span>{g.message}</span></div></div>)}</div>
      </section>
      <section className="panel wordpressApplyPanel"><h2><Image size={20}/>Guarded upload (not featured image)</h2>
        <label>Confirmed Data Backup JSON filename<input value={backup} onChange={e => setBackup(e.target.value)} placeholder="atlas-backup-....json" /></label>
        <label>Type exact phrase: <code>{dryRun.confirmation_phrase ?? "Available only after all gates pass"}</code><input value={phrase} onChange={e => setPhrase(e.target.value)} /></label>
        <button className="dangerButton" disabled={!canUpload || busy} onClick={upload}>Upload one Orlando hero image</button>
        <p className="helperText">Disabled until the dry run passes, a signed token exists, the exact phrase matches, and a backup filename is supplied. The backend validates the backup again.</p>
      </section>
    </>}
    {result && <section className="panel"><h2>Upload confirmed</h2><p>Attachment {result.wordpress_media_id} was verified. No featured image was set.</p></section>}
  </section>;
}
