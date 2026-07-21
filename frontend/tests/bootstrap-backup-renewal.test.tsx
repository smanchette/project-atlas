import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { ApiError } from "../src/api";
import {
  BACKUP_RENEWAL_PHRASE,
  BackupDetails,
  MAX_BACKUP_RENEWALS,
  RenewalHistoryList,
  RenewalStateSummary,
  buildRenewalPayload,
  emptyRenewalForm,
  errorText,
  validateRenewalForm,
  type RenewalForm,
} from "../src/components/BootstrapBackupRenewalPanel";
import type { WordPressBootstrapBackupRenewalRecovery, WordPressBootstrapBackupRenewalRecord } from "../src/types";

const NOW = Date.parse("2026-07-21T12:00:00Z");
const original = {
  wordpress_backup_reference: "Atlas Backup",
  wordpress_backup_completed_at: "2026-07-20T19:35:00Z",
  deadline: "2026-07-20T23:35:00Z",
  wordpress_database_included_attestation: true,
  wordpress_plugins_included_attestation: true,
  wordpress_restore_capability_attestation: true,
};
const replacement = {
  ...original,
  wordpress_backup_reference: "Atlas Backup 2",
  wordpress_backup_completed_at: "2026-07-21T12:30:00Z",
  deadline: "2026-07-21T16:30:00Z",
};
const recovery = (
  renewalHistory: WordPressBootstrapBackupRenewalRecord[] = [],
  overrides: Partial<WordPressBootstrapBackupRenewalRecovery> = {},
): WordPressBootstrapBackupRenewalRecovery => ({
  page_id: 41, wordpress_post_id: 8, establishment_audit_id: 1,
  status: "recovery_assessment_complete", audit_status: "awaiting_manual_bootstrap_installation",
  classification: "renewal_required", reason_code: "bootstrap_backup_renewal_replacement_required",
  recommendation: "create_fresh_siteground_backup",
  next_required_action: "create_fresh_siteground_backup_then_run_guarded_backup_renewal",
  renewal_eligible: true, renewal_blocked: false,
  original_backup: original, active_backup: renewalHistory.at(-1)?.replacement ?? original,
  original_backup_expired: true, original_backup_expiration_status: "expired", original_backup_remaining_seconds: 0,
  active_backup_source: renewalHistory.length ? "replacement" : "original",
  active_backup_expired: renewalHistory.length ? false : true,
  active_backup_expiration_status: renewalHistory.length ? "valid" : "expired",
  active_backup_remaining_seconds: renewalHistory.length ? 16_200 : 0,
  active_renewal_sequence: renewalHistory.at(-1)?.sequence ?? null,
  renewal_history: renewalHistory, renewal_count: renewalHistory.length, maximum_renewals: 3,
  renewals_remaining: Math.max(0, 3 - renewalHistory.length), renewal_limit_reached: renewalHistory.length >= 3,
  bootstrap_manually_uploaded: true, verification_evidence_present: false, activation_started: false,
  checksum_quarantine_active: false, pending_operation: false,
  wordpress_write_count: 0, cache_write_count: 0, atlas_write_count: 0,
  ...overrides,
});
const validForm = (): RenewalForm => ({
  atlasDataBackupFile: "atlas-data.json", atlasMediaBackupFile: "atlas-media.zip", atlasProgramBackupFile: "atlas-program.zip",
  method: "SiteGround on-demand full-site backup", reference: "Atlas Backup 2",
  completedAt: "2026-07-21T08:30:00-04:00", deadline: "2026-07-21T12:30:00-04:00", confirmer: "Shawn Manchette",
  databaseIncluded: true, pluginsIncluded: true, restoreConfirmed: true, noRelevantChange: true,
});
const record = (sequence: number, active = false): WordPressBootstrapBackupRenewalRecord => ({
  sequence, replacement: { ...replacement, wordpress_backup_reference: `Atlas Backup ${sequence + 1}` },
  approved_at: `2026-07-21T1${sequence}:00:00Z`, status: "committed", active,
  replacement_expired: false, replacement_expiration_status: "valid",
});
const source = readFileSync(resolve(process.cwd(), "src/components/BootstrapBackupRenewalPanel.tsx"), "utf8");

test("original backup completion and deadline render", () => {
  const html = renderToStaticMarkup(<BackupDetails backup={original} expirationStatus="expired"/>);
  assert.match(html, /2026-07-20T19:35:00Z/); assert.match(html, /2026-07-20T23:35:00Z/);
});
test("expired original backup is textually labeled", () => assert.match(renderToStaticMarkup(<BackupDetails backup={original} expirationStatus="expired"/>), />expired</));
test("empty renewal history state renders", () => assert.match(renderToStaticMarkup(<RenewalHistoryList renewals={[]}/>), /No replacement backup renewal has been recorded/));
test("one renewal renders reference and sequence", () => { const html=renderToStaticMarkup(<RenewalHistoryList renewals={[record(1,true)]}/>); assert.match(html,/Renewal 1/); assert.match(html,/Atlas Backup 2/); });
test("multiple renewals render in sequence order", () => { const html=renderToStaticMarkup(<RenewalHistoryList renewals={[record(2,true),record(1)]}/>); assert.ok(html.indexOf("Renewal 1")<html.indexOf("Renewal 2")); });
test("backend-designated replacement is identified as active", () => { const html=renderToStaticMarkup(<RenewalHistoryList renewals={[record(1),record(2,true)]}/>); assert.match(html,/Renewal 2 — active/); assert.match(html,/Renewal 1 — historical/); });
test("renewal count and maximum are displayed", () => { assert.equal(MAX_BACKUP_RENEWALS,3); assert.match(source,/Renewal count:/); });
test("current audit fixture renders durable status rather than generic operation status", () => {
  const html=renderToStaticMarkup(<RenewalStateSummary recovery={recovery()}/>);
  assert.match(html,/Audit status<\/dt><dd>awaiting_manual_bootstrap_installation/);
  assert.match(html,/Assessment operation<\/dt><dd>recovery_assessment_complete/);
});
test("current audit fixture renders eligibility reason and next action", () => {
  const html=renderToStaticMarkup(<RenewalStateSummary recovery={recovery()}/>);
  assert.match(html,/Renewal eligible<\/dt><dd>yes/);
  assert.match(html,/bootstrap_backup_renewal_replacement_required/);
  assert.match(html,/create_fresh_siteground_backup_then_run_guarded_backup_renewal/);
});
test("workflow state renders upload verification activation quarantine and pending flags", () => {
  const html=renderToStaticMarkup(<RenewalStateSummary recovery={recovery()}/>);
  assert.match(html,/Bootstrap already uploaded<\/dt><dd>yes/);
  assert.match(html,/Verification evidence<\/dt><dd>absent/);
  assert.match(html,/Activation<\/dt><dd>not started/);
  assert.match(html,/Checksum quarantine<\/dt><dd>inactive/);
  assert.match(html,/Pending operation<\/dt><dd>none/);
});
test("protected lifecycle display uses explicit response fields", () => {
  assert.match(source,/recovery\.audit_status/);
  assert.match(source,/recovery\?\.active_backup_source/);
  assert.match(source,/recovery\?\.renewal_count/);
  assert.match(source,/recovery\?\.maximum_renewals/);
  assert.match(source,/recovery\.renewal_eligible/);
  assert.doesNotMatch(source,/renewalCount\s*\?\s*"Active replacement backup"/);
});
test("explicit deadline is required", () => { const form=validForm(); form.deadline=""; assert.match(validateRenewalForm(form,recovery(),NOW).deadline,/required/); });
test("explicit completion is required", () => { const form=validForm(); form.completedAt=""; assert.match(validateRenewalForm(form,recovery(),NOW).completedAt,/required/); });
test("database checkbox is required", () => { const form=validForm(); form.databaseIncluded=false; assert.ok(validateRenewalForm(form,recovery(),NOW).databaseIncluded); });
test("plugins checkbox is required", () => { const form=validForm(); form.pluginsIncluded=false; assert.ok(validateRenewalForm(form,recovery(),NOW).pluginsIncluded); });
test("restore checkbox is required", () => { const form=validForm(); form.restoreConfirmed=false; assert.ok(validateRenewalForm(form,recovery(),NOW).restoreConfirmed); });
test("no-change attestation defaults false", () => assert.equal(emptyRenewalForm().noRelevantChange,false));
test("submission validation blocks unchecked no-change attestation", () => { const form=validForm(); form.noRelevantChange=false; assert.ok(validateRenewalForm(form,recovery(),NOW).noRelevantChange); });
test("request uses actual false operator attestation", () => { const form=validForm(); form.noRelevantChange=false; assert.equal(buildRenewalPayload(form).no_relevant_wordpress_change_after_backup,false); });
test("hard-coded true attestation is absent", () => assert.doesNotMatch(source,/no_relevant_wordpress_change_after_backup\s*:\s*true/));
test("exact timezone-aware values are submitted unchanged", () => { const form=validForm(); const payload=buildRenewalPayload(form); assert.equal(payload.replacement_backup_completed_at,form.completedAt); assert.equal(payload.replacement_backup_deadline,form.deadline); });
test("timezone-naive completion is blocked", () => { const form=validForm(); form.completedAt="2026-07-21T08:30:00"; assert.match(validateRenewalForm(form,recovery(),NOW).completedAt,/offset/); });
test("deadline before completion is blocked", () => { const form=validForm(); form.deadline="2026-07-21T08:00:00-04:00"; assert.match(validateRenewalForm(form,recovery(),NOW).deadline,/after completion/); });
test("expired replacement is blocked", () => { const form=validForm(); form.completedAt="2026-07-21T06:00:00Z"; form.deadline="2026-07-21T10:00:00Z"; assert.match(validateRenewalForm(form,recovery(),NOW).deadline,/expired/); });
test("backend reason code and message are displayed accurately", () => assert.equal(errorText(new ApiError(409,"State changed",{reason_code:"bootstrap_backup_renewal_state_drift"})),"bootstrap_backup_renewal_state_drift: State changed"));
test("preflight and apply remain separate with exact labels", () => { assert.match(source,/backup-renewal\/preflight\/41/); assert.match(source,/backup-renewal\/apply\/41/); assert.match(source,/Run renewal preflight/); assert.match(source,/Apply guarded renewal/); assert.doesNotMatch(source,/Commit active backup renewal/); });
test("raw handle is never displayed", () => { assert.doesNotMatch(source,/raw handle/i); assert.match(source,/Safe handle fingerprint/); });
test("exact phrase is required", () => assert.equal(BACKUP_RENEWAL_PHRASE,"RENEW PROJECT ATLAS BOOTSTRAP HANDOFF BACKUP FOR AUDIT 1"));
test("expired process-memory preflight is labeled and cannot apply", () => { assert.match(source,/expired or unavailable — run a new preflight/); assert.match(source,/!preflightHandleFresh/); });
test("refresh defaults clear attestation and form state", () => assert.deepEqual(emptyRenewalForm(),emptyRenewalForm()));
test("no persistent browser storage is used", () => { assert.doesNotMatch(source,/localStorage|sessionStorage/); assert.match(source,/useState\(\"\"\)/); });
test("existing bootstrap warning is displayed", () => assert.match(source,/bootstrap is already uploaded/i));
test("do not upload again warning is displayed", () => assert.match(source,/Do not upload it again/));
test("do not activate warning is displayed", () => assert.match(source,/do not activate it manually/));
test("successful renewal shows active replacement and next step", () => { assert.match(source,/Active backup renewed/); assert.match(source,/capture fresh browser evidence and run manual-install verification/); });
test("expired replacement remains eligible below limit", () => {
  const expiredRecord = record(1);
  expiredRecord.replacement = { ...expiredRecord.replacement, deadline: "2026-07-21T11:00:00Z" };
  assert.equal(Object.keys(validateRenewalForm(validForm(),recovery([expiredRecord],{classification:"replacement_backup_expired",renewal_eligible:true,renewal_blocked:false,active_backup_expired:true,active_backup_expiration_status:"expired"}),NOW)).length,0);
});
test("renewal limit disables the action from authoritative response", () => assert.match(validateRenewalForm(validForm(),recovery([record(1),record(2),record(3,true)],{renewal_limit_reached:true,renewal_eligible:false,renewal_blocked:true,renewals_remaining:0}),NOW).renewalLimit,/maximum/));
test("request contract contains only approved keys", () => assert.deepEqual(Object.keys(buildRenewalPayload(validForm())).sort(),[
  "atlas_data_backup_file","atlas_media_backup_file","atlas_program_backup_file","confirmer_identity","database_included_attestation","establishment_audit_id","no_relevant_wordpress_change_after_backup","plugins_included_attestation","replacement_backup_completed_at","replacement_backup_deadline","replacement_backup_method","replacement_backup_reference","restore_capability_attestation",
].sort()));
test("request cannot choose protected or original state", () => { const keys=Object.keys(buildRenewalPayload(validForm())).join(" "); assert.doesNotMatch(keys,/active_backup|renewal_sequence|original_backup|protected|runtime|plugin_path|credential|restore_command/); });
test("audit ID is fixed rather than operator-entered", () => { assert.equal(buildRenewalPayload(validForm()).establishment_audit_id,1); assert.doesNotMatch(source,/establishment_audit_id.*<input/); });
test("explicit calculation is reviewable rather than silent", () => { assert.match(source,/Calculate four-hour deadline for review/); assert.match(source,/Submitted deadline/); });
