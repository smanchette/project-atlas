import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, LockKeyhole } from "lucide-react";
import { ApiError, apiRequest } from "../api";
import type {
  WordPressBootstrapBackupEvidence,
  WordPressBootstrapBackupRenewalPreflight,
  WordPressBootstrapBackupRenewalRecovery,
  WordPressBootstrapBackupRenewalResult,
} from "../types";

export const BOOTSTRAP_AUDIT_ID = 1;
export const MAX_BACKUP_RENEWALS = 3;
export const BACKUP_RENEWAL_PHRASE = "RENEW PROJECT ATLAS BOOTSTRAP HANDOFF BACKUP FOR AUDIT 1";

export type RenewalForm = {
  atlasDataBackupFile: string;
  atlasMediaBackupFile: string;
  atlasProgramBackupFile: string;
  method: string;
  reference: string;
  completedAt: string;
  deadline: string;
  confirmer: string;
  databaseIncluded: boolean;
  pluginsIncluded: boolean;
  restoreConfirmed: boolean;
  noRelevantChange: boolean;
};

export const emptyRenewalForm = (): RenewalForm => ({
  atlasDataBackupFile: "",
  atlasMediaBackupFile: "",
  atlasProgramBackupFile: "",
  method: "",
  reference: "",
  completedAt: "",
  deadline: "",
  confirmer: "",
  databaseIncluded: false,
  pluginsIncluded: false,
  restoreConfirmed: false,
  noRelevantChange: false,
});

const ZONED_ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})$/;

export function validateRenewalForm(
  form: RenewalForm,
  recovery: WordPressBootstrapBackupRenewalRecovery | null,
  now = Date.now(),
): Record<string, string> {
  const errors: Record<string, string> = {};
  const requireText = (key: keyof RenewalForm, message: string) => {
    if (!String(form[key]).trim()) errors[key] = message;
  };
  requireText("atlasDataBackupFile", "Atlas Data Backup identity is required.");
  requireText("atlasMediaBackupFile", "Atlas Media Backup identity is required.");
  requireText("atlasProgramBackupFile", "Atlas Program Backup identity is required.");
  requireText("method", "SiteGround backup method is required.");
  requireText("reference", "Replacement backup reference is required.");
  requireText("confirmer", "Confirmer identity is required.");
  if (!form.completedAt) errors.completedAt = "Timezone-aware completion is required.";
  else if (!ZONED_ISO.test(form.completedAt) || !Number.isFinite(Date.parse(form.completedAt))) errors.completedAt = "Completion must be an unambiguous ISO-8601 timestamp with Z or an offset.";
  if (!form.deadline) errors.deadline = "Timezone-aware deadline is required.";
  else if (!ZONED_ISO.test(form.deadline) || !Number.isFinite(Date.parse(form.deadline))) errors.deadline = "Deadline must be an unambiguous ISO-8601 timestamp with Z or an offset.";
  const completed = Date.parse(form.completedAt);
  const deadline = Date.parse(form.deadline);
  if (!errors.completedAt && !errors.deadline && deadline <= completed) errors.deadline = "Deadline must be after completion.";
  if (!errors.deadline && deadline <= now) errors.deadline = "Replacement backup is already expired.";
  if (!form.databaseIncluded) errors.databaseIncluded = "Confirm that the database is included.";
  if (!form.pluginsIncluded) errors.pluginsIncluded = "Confirm that wp-content/plugins is included.";
  if (!form.restoreConfirmed) errors.restoreConfirmed = "Confirm restore capability.";
  if (!form.noRelevantChange) errors.noRelevantChange = "Explicitly confirm that no relevant WordPress change followed the backup.";
  const count = recovery?.renewal_history.length ?? 0;
  if (count >= MAX_BACKUP_RENEWALS) errors.renewalLimit = "The maximum of three guarded renewals has been reached.";
  if (recovery && !["renewal_required", "replacement_backup_expired"].includes(recovery.classification)) {
    errors.auditEligibility = `Audit is not eligible: ${recovery.classification}.`;
  }
  const activeDeadline = Date.parse(recovery?.active_backup.deadline ?? "");
  if (recovery && Number.isFinite(activeDeadline) && activeDeadline > now) errors.activeBackup = "The current active backup has not expired.";
  return errors;
}

export function buildRenewalPayload(form: RenewalForm) {
  return {
    establishment_audit_id: BOOTSTRAP_AUDIT_ID,
    atlas_data_backup_file: form.atlasDataBackupFile.trim(),
    atlas_media_backup_file: form.atlasMediaBackupFile.trim(),
    atlas_program_backup_file: form.atlasProgramBackupFile.trim(),
    replacement_backup_method: form.method.trim(),
    replacement_backup_reference: form.reference.trim(),
    replacement_backup_completed_at: form.completedAt.trim(),
    replacement_backup_deadline: form.deadline.trim(),
    database_included_attestation: form.databaseIncluded,
    plugins_included_attestation: form.pluginsIncluded,
    restore_capability_attestation: form.restoreConfirmed,
    no_relevant_wordpress_change_after_backup: form.noRelevantChange,
    confirmer_identity: form.confirmer.trim(),
  };
}

function expired(deadline: unknown, now: number): boolean {
  const value = typeof deadline === "string" ? Date.parse(deadline) : Number.NaN;
  return Number.isFinite(value) && value <= now;
}

function flag(value: unknown): string {
  return value === true ? "yes" : value === false ? "no" : "not recorded";
}

export function BackupDetails({ backup, now }: { backup: WordPressBootstrapBackupEvidence; now: number }) {
  return <dl className="wordpressSettingsGrid">
    <div><dt>Reference</dt><dd>{backup.wordpress_backup_reference ?? "not recorded"}</dd></div>
    <div><dt>Completion</dt><dd>{backup.wordpress_backup_completed_at ?? "not recorded"}</dd></div>
    <div><dt>Deadline</dt><dd>{backup.deadline ?? "not recorded"}</dd></div>
    <div><dt>Status</dt><dd>{expired(backup.deadline, now) ? "expired" : "active"}</dd></div>
    <div><dt>Database included</dt><dd>{flag(backup.wordpress_database_included_attestation)}</dd></div>
    <div><dt>wp-content/plugins included</dt><dd>{flag(backup.wordpress_plugins_included_attestation)}</dd></div>
    <div><dt>Restore capability</dt><dd>{flag(backup.wordpress_restore_capability_attestation)}</dd></div>
  </dl>;
}

export function RenewalHistoryList({ renewals, now }: { renewals: WordPressBootstrapBackupRenewalResult["renewal_history"]; now: number }) {
  const ordered = [...renewals].sort((a, b) => a.sequence - b.sequence);
  if (ordered.length === 0) return <p>No replacement backup renewal has been recorded.</p>;
  return <ol>{ordered.map((renewal, index) => <li key={renewal.sequence} data-testid={`renewal-${renewal.sequence}`}>
    <strong>Renewal {renewal.sequence} — {index === ordered.length - 1 ? "active" : "historical"}</strong>
    <BackupDetails backup={renewal.replacement} now={now}/>
    <p>Committed: {renewal.approved_at ?? "not recorded"} · status: {renewal.status}</p>
  </li>)}</ol>;
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError && error.detail && typeof error.detail === "object" && "reason_code" in error.detail) {
    return `${String((error.detail as { reason_code: unknown }).reason_code)}: ${error.message}`;
  }
  return error instanceof Error ? error.message : "Backup-renewal request failed.";
}

export default function BootstrapBackupRenewalPanel() {
  const [form, setForm] = useState<RenewalForm>(emptyRenewalForm);
  const [recovery, setRecovery] = useState<WordPressBootstrapBackupRenewalRecovery | null>(null);
  const [preflight, setPreflight] = useState<WordPressBootstrapBackupRenewalPreflight | null>(null);
  const [result, setResult] = useState<WordPressBootstrapBackupRenewalResult | null>(null);
  const [phrase, setPhrase] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());

  const loadAudit = useCallback(async () => {
    setError("");
    try {
      setRecovery(await apiRequest<WordPressBootstrapBackupRenewalRecovery>(
        "/api/wordpress/deployment/upgrade-bootstrap/backup-renewal/recovery/assess/41",
        { method: "POST", body: JSON.stringify({ establishment_audit_id: BOOTSTRAP_AUDIT_ID }) },
      ));
    } catch (value) {
      setError(errorText(value));
    }
  }, []);

  useEffect(() => { void loadAudit(); }, [loadAudit]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const update = <K extends keyof RenewalForm>(key: K, value: RenewalForm[K]) => {
    setForm(current => ({ ...current, [key]: value }));
    setPreflight(null);
    setResult(null);
    setPhrase("");
    setError("");
  };
  const errors = useMemo(() => validateRenewalForm(form, recovery, now), [form, recovery, now]);
  const canPreflight = recovery !== null && Object.keys(errors).length === 0 && !busy;
  const renewals = [...(result?.renewal_history ?? recovery?.renewal_history ?? [])].sort((a, b) => a.sequence - b.sequence);
  const original = result?.original_backup ?? recovery?.original_backup;
  const active = result?.active_backup ?? recovery?.active_backup;
  const renewalCount = renewals.length;
  const preflightExpiresAt = preflight?.expires_at ? Date.parse(preflight.expires_at) : Number.NaN;
  const preflightHandleFresh = Boolean(preflight?.renewal_handle_fingerprint && Number.isFinite(preflightExpiresAt) && preflightExpiresAt > now);

  const calculateDeadline = () => {
    const completed = Date.parse(form.completedAt);
    if (Number.isFinite(completed)) update("deadline", new Date(completed + 4 * 60 * 60 * 1000).toISOString());
    else setError("Enter a valid timezone-aware completion before calculating the deadline.");
  };
  const runPreflight = async () => {
    if (!canPreflight) return;
    setBusy(true); setError(""); setResult(null); setPhrase("");
    try {
      setPreflight(await apiRequest<WordPressBootstrapBackupRenewalPreflight>(
        "/api/wordpress/deployment/upgrade-bootstrap/backup-renewal/preflight/41",
        { method: "POST", body: JSON.stringify(buildRenewalPayload(form)) },
      ));
    } catch (value) { setError(errorText(value)); }
    finally { setBusy(false); }
  };
  const applyRenewal = async () => {
    if (!preflightHandleFresh || !preflight?.renewal_handle_fingerprint || phrase !== BACKUP_RENEWAL_PHRASE) return;
    setBusy(true); setError("");
    try {
      const committed = await apiRequest<WordPressBootstrapBackupRenewalResult>(
        "/api/wordpress/deployment/upgrade-bootstrap/backup-renewal/apply/41",
        { method: "POST", body: JSON.stringify({ renewal_handle_fingerprint: preflight.renewal_handle_fingerprint, confirmation_phrase: phrase }) },
      );
      setResult(committed); setPreflight(null); setPhrase("");
      await loadAudit();
    } catch (value) { setError(errorText(value)); setPreflight(null); setPhrase(""); }
    finally { setBusy(false); }
  };

  return <section className="panel" aria-labelledby="bootstrap-backup-renewal-title">
    <h2 id="bootstrap-backup-renewal-title">Guarded SiteGround backup renewal for audit 1</h2>
    <div className="wordpressSafetyNotice"><LockKeyhole size={20}/><div><strong>The bootstrap is already uploaded.</strong><ul>
      <li>Do not upload it again and do not activate it manually.</li>
      <li>The original SiteGround backup expired and remains preserved as audit history.</li>
      <li>A fresh replacement SiteGround full-site backup is required.</li>
      <li>Renewal modifies no WordPress state, performs no cache purge, and does not activate the bootstrap.</li>
      <li>Renewal advances only the audit-bound active backup after guarded approval.</li>
      <li>The replacement expires at its recorded deadline; complete manual verification before then or renew again.</li>
      <li>Maximum renewal count: {MAX_BACKUP_RENEWALS}.</li>
    </ul></div></div>
    {error && <div className="errorBanner" role="alert"><AlertTriangle size={18}/>{error}</div>}

    <h3>Original authorization backup — expired and preserved as audit history</h3>
    {original ? <BackupDetails backup={original} now={now}/> : <p>Loading immutable original backup…</p>}

    <h3>Current effective active backup</h3>
    <p>{renewalCount ? "Active replacement backup" : "Original authorization backup (no replacement recorded)"}</p>
    {active && <BackupDetails backup={active} now={now}/>}
    <p>Renewal count: <strong>{renewalCount} of {MAX_BACKUP_RENEWALS}</strong></p>

    <h3>Renewal history</h3>
    <RenewalHistoryList renewals={renewals} now={now}/>

    <fieldset disabled={busy || renewalCount >= MAX_BACKUP_RENEWALS}>
      <legend>Enter replacement backup information</legend>
      <label>Atlas Data Backup identity<input value={form.atlasDataBackupFile} onChange={event=>update("atlasDataBackupFile",event.target.value)}/></label>
      <label>Atlas Media Backup identity<input value={form.atlasMediaBackupFile} onChange={event=>update("atlasMediaBackupFile",event.target.value)}/></label>
      <label>Atlas Program Backup identity<input value={form.atlasProgramBackupFile} onChange={event=>update("atlasProgramBackupFile",event.target.value)}/></label>
      <label>SiteGround backup method<input value={form.method} onChange={event=>update("method",event.target.value)} placeholder="SiteGround on-demand full-site backup"/></label>
      <label>Replacement backup reference/name<input value={form.reference} onChange={event=>update("reference",event.target.value)}/></label>
      <label>Completion — timezone-aware ISO-8601<input value={form.completedAt} onChange={event=>update("completedAt",event.target.value)} placeholder="2026-07-21T08:00:00-04:00" aria-describedby="completion-preview"/></label>
      <p id="completion-preview">Submitted completion: <code>{form.completedAt || "not entered"}</code></p>
      <label>Deadline — timezone-aware ISO-8601<input value={form.deadline} onChange={event=>update("deadline",event.target.value)} placeholder="2026-07-21T12:00:00-04:00" aria-describedby="deadline-preview"/></label>
      <button type="button" className="secondaryButton" onClick={calculateDeadline}>Calculate four-hour deadline for review</button>
      <p id="deadline-preview">Submitted deadline: <code>{form.deadline || "not entered"}</code></p>
      <label>Confirmer identity<input value={form.confirmer} onChange={event=>update("confirmer",event.target.value)}/></label>
      <label><input type="checkbox" checked={form.databaseIncluded} onChange={event=>update("databaseIncluded",event.target.checked)}/> I confirm the replacement backup includes the WordPress database.</label>
      <label><input type="checkbox" checked={form.pluginsIncluded} onChange={event=>update("pluginsIncluded",event.target.checked)}/> I confirm the replacement backup includes wp-content/plugins.</label>
      <label><input type="checkbox" checked={form.restoreConfirmed} onChange={event=>update("restoreConfirmed",event.target.checked)}/> I confirm SiteGround restore capability.</label>
      <label><input type="checkbox" checked={form.noRelevantChange} onChange={event=>update("noRelevantChange",event.target.checked)}/> I confirm that no relevant WordPress change occurred after this replacement SiteGround backup completed.</label>
    </fieldset>
    {Object.values(errors).map(message => <p className="helperText" key={message}>{message}</p>)}
    <button className="primaryButton" disabled={!canPreflight} onClick={()=>void runPreflight()}>Run zero-write renewal preflight</button>

    {preflight && <section aria-label="Renewal preflight review">
      <h3>Review preflight</h3>
      <p>Status: <code>{preflight.status}</code> · reason: <code>{preflight.reason_code}</code></p>
      <p>WordPress writes {preflight.wordpress_write_count} · cache writes {preflight.cache_write_count} · Atlas writes {preflight.atlas_write_count}</p>
      {preflight.renewal_handle_fingerprint && <p>Safe handle fingerprint: <code data-testid="handle-fingerprint">{preflight.renewal_handle_fingerprint}</code></p>}
      <p>Preflight authorization: {preflightHandleFresh ? `valid until ${preflight.expires_at}` : "expired or unavailable — run a new preflight"}.</p>
      <ul>{preflight.gate_results.map(gate=><li key={gate.code}>{gate.passed?"Passed":"Failed"}: {gate.label}{!gate.passed&&gate.message?` — ${gate.message}`:""}</li>)}</ul>
      {preflight.ready && <><label>Exact approval phrase<input aria-label="Exact approval phrase" value={phrase} onChange={event=>setPhrase(event.target.value)} autoComplete="off"/></label>
        <p><code>{BACKUP_RENEWAL_PHRASE}</code></p>
        <button className="primaryButton" disabled={busy || !preflightHandleFresh || phrase !== BACKUP_RENEWAL_PHRASE} onClick={()=>void applyRenewal()}>Commit active backup renewal</button></>}
    </section>}

    {result && <div className="wordpressSafetyNotice" role="status"><CheckCircle2 size={20}/><div>
      <strong>Active backup renewed — sequence {result.renewal_sequence}</strong>
      <p>Original backup remains preserved. Active deadline: {result.active_backup.deadline ?? "not recorded"}.</p>
      <p>WordPress writes {result.wordpress_write_count} · cache writes {result.cache_write_count} · Atlas audit writes {result.request_atlas_write_count}.</p>
      <p>Next required step: capture fresh browser evidence and run manual-install verification. Evidence capture and verification were not started automatically.</p>
    </div></div>}
    {renewalCount >= MAX_BACKUP_RENEWALS && <p role="alert">Renewal limit reached. Renewal is disabled. Recovery recommendation: {recovery?.recommendation ?? result?.recovery_recommendation ?? "separately approved recovery required"}.</p>}
  </section>;
}
