import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Link2, LockKeyhole, RefreshCw } from "lucide-react";

import { apiRequest } from "../api";
import type { WordPressMediaReconciliationApplyResult, WordPressMediaReconciliationDryRun } from "../types";

const PAGE_ID = 41;

export default function WordPressMediaSafetyPage() {
  const [dryRun, setDryRun] = useState<WordPressMediaReconciliationDryRun | null>(null);
  const [phrase, setPhrase] = useState("");
  const [backup, setBackup] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WordPressMediaReconciliationApplyResult | null>(null);
  const canReconcile = useMemo(() => Boolean(
    dryRun?.ready && dryRun.confirmation_token && phrase === dryRun.confirmation_phrase && backup.trim()
  ), [dryRun, phrase, backup]);

  async function inspect() {
    setBusy(true); setError(null); setDryRun(null); setPhrase(""); setBackup(""); setResult(null);
    try {
      setDryRun(await apiRequest<WordPressMediaReconciliationDryRun>(
        `/api/wordpress/media/reconciliation/dry-run/${PAGE_ID}`, { method: "POST" }
      ));
    } catch (value) { setError(value instanceof Error ? value.message : "Reconciliation inspection failed."); }
    finally { setBusy(false); }
  }

  async function reconcile() {
    if (!canReconcile || !dryRun?.confirmation_token) return;
    setBusy(true); setError(null);
    try {
      setResult(await apiRequest<WordPressMediaReconciliationApplyResult>(
        `/api/wordpress/media/reconciliation/apply/${PAGE_ID}`,
        { method: "POST", body: JSON.stringify({ confirmation_token: dryRun.confirmation_token, confirmation_phrase: phrase, confirmed_backup_file: backup.trim() }) }
      ));
    } catch (value) { setError(value instanceof Error ? value.message : "Reconciliation was blocked."); }
    finally { setBusy(false); }
  }

  return <section className="page wordpressPublishSafetySandboxPage">
    <header className="pageHeader"><div><span className="eyebrow">Orlando only · page 41 · post 8</span><h1>WordPress Media Reconciliation</h1><p>Verify existing attachments 31 and 32 byte-for-byte, then map Atlas only after explicit confirmation.</p></div></header>
    <div className="wordpressSafetyNotice"><LockKeyhole size={22}/><div><strong>Atlas mapping only</strong><p>No upload, retry, deletion, attachment edit, featured-image assignment, post edit, or bulk action exists on this page.</p></div></div>
    <section className="panel"><h2>Fixed target</h2><dl className="detailGrid"><div><dt>Atlas target</dt><dd>Page 41 · Image 1 · Assignment 1</dd></div><div><dt>WordPress post</dt><dd>8 · must remain publish · featured_media 0</dd></div><div><dt>Candidate attachments</dt><dd>31 and 32 only</dd></div></dl><button className="primaryButton buttonWithIcon" disabled={busy} onClick={inspect}><RefreshCw size={16}/>Run read-only reconciliation inspection</button></section>
    {error && <div className="errorBanner"><AlertTriangle size={18}/>{error}</div>}
    {dryRun && <>
      <section className="panel"><h2>Selection summary</h2><dl className="detailGrid"><div><dt>Local SHA-256</dt><dd><code>{dryRun.local_checksum}</code></dd></div><div><dt>Selected canonical ID</dt><dd>{dryRun.selected_media_id ?? "Blocked"}</dd></div><div><dt>Duplicate candidate IDs</dt><dd>{dryRun.duplicate_candidate_ids.join(", ") || "None"}</dd></div><div><dt>Post 8</dt><dd>{dryRun.post_status ?? "Unknown"}; featured_media {dryRun.post_featured_media ?? "Unknown"}</dd></div></dl></section>
      {dryRun.candidates.map(candidate => <section className="panel" key={candidate.wordpress_media_id}><h2>Candidate {candidate.wordpress_media_id} {candidate.valid ? <CheckCircle2 size={18}/> : <AlertTriangle size={18}/>}</h2><dl className="detailGrid"><div><dt>Created</dt><dd>{candidate.date_gmt ?? "-"}</dd></div><div><dt>Title</dt><dd>{candidate.title ?? "-"}</dd></div><div><dt>Alt text</dt><dd>{candidate.alt_text ?? "-"}</dd></div><div><dt>MIME / size</dt><dd>{candidate.mime_type ?? "-"} · {candidate.file_size?.toLocaleString() ?? "-"}</dd></div><div><dt>Dimensions</dt><dd>{candidate.width ?? "-"} × {candidate.height ?? "-"}</dd></div><div><dt>Parent</dt><dd>{candidate.parent_post_id ?? "Unattached"}</dd></div><div><dt>Remote SHA-256</dt><dd><code>{candidate.remote_checksum ?? "Unavailable"}</code></dd></div><div><dt>Featured references</dt><dd>{candidate.featured_references.length ? candidate.featured_references.map(reference => `${reference.object_type} ${reference.object_id} (${reference.title ?? reference.slug ?? "untitled"}, ${reference.status ?? "unknown"})`).join("; ") : "None"}</dd></div><div><dt>Source URL</dt><dd>{candidate.source_url ? <a href={candidate.source_url} target="_blank" rel="noreferrer">Read-only source</a> : "-"}</dd></div></dl><GateList gates={candidate.gate_results}/></section>)}
      <section className="panel"><h2>Required gates</h2><GateList gates={dryRun.gate_results}/></section>
      <section className="panel wordpressApplyPanel"><h2><Link2 size={20}/>Guarded Atlas reconciliation</h2><label>Confirmed Data Backup JSON filename<input value={backup} onChange={event => setBackup(event.target.value)} placeholder="atlas-backup-....json" /></label><label>Type exact phrase: <code>{dryRun.confirmation_phrase ?? "Available only after every gate passes"}</code><input value={phrase} onChange={event => setPhrase(event.target.value)} /></label><button className="dangerButton" disabled={!canReconcile || busy} onClick={reconcile}>Map Atlas to verified existing attachment</button><p className="helperText">This updates ImageMetadata and its reconciliation audit only. It sends no WordPress write request.</p></section>
    </>}
    {result && <section className="panel"><h2>Atlas mapping reconciled</h2><p>Atlas now references attachment {result.wordpress_media_id}. Duplicate candidates remain untouched. Audit {result.audit_id} recorded.</p></section>}
  </section>;
}

function GateList({ gates }: { gates: { code: string; label: string; passed: boolean; message: string }[] }) {
  return <div className="wordpressGateList">{gates.map(gate => <div key={gate.code} className={gate.passed ? "gateItem passed" : "gateItem blocked"}>{gate.passed ? <CheckCircle2 size={17}/> : <AlertTriangle size={17}/>}<div><strong>{gate.label}</strong><span>{gate.message}</span></div></div>)}</div>;
}
