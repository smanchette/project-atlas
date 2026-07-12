import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Image, LockKeyhole, RefreshCw } from "lucide-react";

import { apiRequest } from "../api";
import type { WordPressFeaturedImageApplyResult, WordPressFeaturedImageDryRun } from "../types";

const PAGE_ID = 41;

export default function WordPressMediaSafetyPage() {
  const [dryRun, setDryRun] = useState<WordPressFeaturedImageDryRun | null>(null);
  const [phrase, setPhrase] = useState("");
  const [dataBackup, setDataBackup] = useState("");
  const [mediaBackup, setMediaBackup] = useState("");
  const [programBackup, setProgramBackup] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WordPressFeaturedImageApplyResult | null>(null);
  const canApply = useMemo(() => Boolean(
    dryRun?.ready && dryRun.confirmation_token && phrase === dryRun.confirmation_phrase &&
    dataBackup.trim() && mediaBackup.trim() && programBackup.trim()
  ), [dryRun, phrase, dataBackup, mediaBackup, programBackup]);

  async function inspect() {
    setBusy(true); setError(null); setDryRun(null); setPhrase(""); setDataBackup(""); setMediaBackup(""); setProgramBackup(""); setResult(null);
    try {
      setDryRun(await apiRequest<WordPressFeaturedImageDryRun>(`/api/wordpress/media/featured-image/dry-run/${PAGE_ID}`, { method: "POST" }));
    } catch (value) { setError(value instanceof Error ? value.message : "Featured-image dry run failed."); }
    finally { setBusy(false); }
  }

  async function apply() {
    if (!canApply || !dryRun?.confirmation_token) return;
    setBusy(true); setError(null);
    try {
      setResult(await apiRequest<WordPressFeaturedImageApplyResult>(`/api/wordpress/media/featured-image/apply/${PAGE_ID}`, {
        method: "POST",
        body: JSON.stringify({
          confirmation_token: dryRun.confirmation_token,
          confirmation_phrase: phrase,
          confirmed_data_backup_file: dataBackup.trim(),
          confirmed_media_backup_file: mediaBackup.trim(),
          confirmed_program_backup_file: programBackup.trim()
        })
      }));
    } catch (value) { setError(value instanceof Error ? value.message : "Featured-image apply was blocked."); }
    finally { setBusy(false); }
  }

  return <section className="page wordpressPublishSafetySandboxPage">
    <header className="pageHeader"><div><span className="eyebrow">Orlando only · page 41 · post 8</span><h1>WordPress Featured Image Safety</h1><p>Verify reconciled media 31, then set it as the featured image only after three backup confirmations and an exact phrase.</p></div></header>
    <div className="wordpressSafetyNotice"><LockKeyhole size={22}/><div><strong>One-field WordPress mutation</strong><p>The only planned payload is <code>{`{"featured_media":31}`}</code>. No upload, media edit, duplicate cleanup, content edit, status change, file picker, or bulk action is available.</p></div></div>
    <section className="panel"><h2>Fixed target</h2><dl className="detailGrid"><div><dt>Atlas target</dt><dd>Page 41 · Image 1 · Assignment 1</dd></div><div><dt>WordPress target</dt><dd>Post 8 · media 31</dd></div><div><dt>Excluded duplicate</dt><dd>Media 32 — untouched</dd></div></dl><button className="primaryButton buttonWithIcon" disabled={busy} onClick={inspect}><RefreshCw size={16}/>Run featured-image dry run</button></section>
    {error && <div className="errorBanner"><AlertTriangle size={18}/>{error}</div>}
    {dryRun && <>
      <section className="panel"><h2>Read-only verification</h2><dl className="detailGrid"><div><dt>Post status</dt><dd>{dryRun.post_status ?? "Unknown"}</dd></div><div><dt>Current featured_media</dt><dd>{dryRun.current_featured_media ?? "Unknown"}</dd></div><div><dt>Post slug</dt><dd>{dryRun.post_slug ?? "-"}</dd></div><div><dt>Post URL</dt><dd>{dryRun.post_url ?? "-"}</dd></div><div><dt>Media 31 remote SHA-256</dt><dd><code>{dryRun.media?.remote_checksum ?? "Unavailable"}</code></dd></div><div><dt>Planned payload</dt><dd><code>{JSON.stringify(dryRun.planned_payload)}</code></dd></div><div><dt>Excluded media IDs</dt><dd>{dryRun.excluded_media_ids.join(", ")}</dd></div></dl><GateList gates={dryRun.media?.gate_results ?? []}/><GateList gates={dryRun.gate_results}/></section>
      <section className="panel wordpressApplyPanel"><h2><Image size={20}/>Guarded featured-image apply</h2><label>Confirmed Data Backup JSON<input value={dataBackup} onChange={event => setDataBackup(event.target.value)} placeholder="atlas-backup-....json" /></label><label>Confirmed Media Backup ZIP<input value={mediaBackup} onChange={event => setMediaBackup(event.target.value)} placeholder="atlas-media-backup-....zip" /></label><label>Confirmed Program Backup ZIP<input value={programBackup} onChange={event => setProgramBackup(event.target.value)} placeholder="atlas-program-backup-....zip" /></label><label>Type exact phrase: <code>{dryRun.confirmation_phrase ?? "Available only after every gate passes"}</code><input value={phrase} onChange={event => setPhrase(event.target.value)} /></label><button className="dangerButton" disabled={!canApply || busy} onClick={apply}>Set media 31 as Orlando featured image</button><p className="helperText">Disabled until dry run, signed token, all backup filenames, and the exact phrase are present. The backend reruns every gate before sending the one-field request.</p></section>
    </>}
    {result && <section className="panel"><h2>Featured image confirmed</h2><p>Post {result.wordpress_post_id} remains publish with featured_media {result.featured_media}. Audit {result.audit_id} recorded.</p></section>}
  </section>;
}

function GateList({ gates }: { gates: { code: string; label: string; passed: boolean; message: string }[] }) {
  return <div className="wordpressGateList">{gates.map(gate => <div key={gate.code} className={gate.passed ? "gateItem passed" : "gateItem blocked"}>{gate.passed ? <CheckCircle2 size={17}/> : <AlertTriangle size={17}/>}<div><strong>{gate.label}</strong><span>{gate.message}</span></div></div>)}</div>;
}
