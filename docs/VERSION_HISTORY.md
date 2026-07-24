# Project Atlas Version History

## v0.59.93

- Corrected post-activation verification so the exact Bootstrap 0.3.0 inactive-to-active transition is expected while duplicate, alternate-path, wrong-version, network-active, checksum, or unrelated plugin drift remains blocked.
- Removed volatile SiteGround cache telemetry from durable protected-state equality and permitted HIT/MISS/EXPIRED/BYPASS variation only during post-mutation verification with origin, HTTP, provider, privacy, and signed page identity still exact.
- Added a fresh-evidence, fresh-Data-backup, phrase-gated Atlas-only reconciliation for the exact Audit ID 2 verifier-defect state, preserving the original activation write and failure history while performing zero WordPress, plugin, or cache writes.
- Added migration 0026 and Data Backup schema 0.40 so the reconciliation reason, binding, one-time handle fingerprint, and completion timestamp remain durable while older supported backups remain restorable.

## v0.59.92

- Repaired the rendered-state producer contract so verified public and authenticated acquisitions retain one sanitized canonical `public_http_observation` for downstream retirement checks.
- Preserved precise DNS, connect-timeout, read-timeout, TLS, network, and acquisition-failure categories without exposing raw exception details or misreporting missing responses as origin drift.
- Kept retirement fail-closed and explicitly classified SiteGround `EXPIRED`, `MISS`, and `BYPASS` responses as non-HIT states that cannot authorize retirement.

## v0.59.91

- Added a phrase-gated Atlas-only terminal retirement for stale pre-activation Bootstrap authorizations when immutable SiteGround transport evidence proves genuine HTTP 403 block to HTTP 200 cached-public drift.
- Added a distinct fresh authorization mode for the exact installed, single, inactive Bootstrap 0.3.0 without upload, reinstall, replacement, deletion, activation, or any WordPress mutation.
- Added migration 0025 and Data Backup schema 0.39 so retirement reason, authorization mode, and renewal history remain durable while 0.38 backups remain supported.

## v0.59.90

- Added the versioned, directional `project-atlas-public-transport-identity-v2` comparison for manual Bootstrap 0.3.0 verification across the v0.59.89 centralized HTTP-client boundary.
- Canonicalized only equivalent SiteGround/nginx transport representations while preserving exact HTTP status and response-source security meaning.
- Preserved raw observations and immutable authorization history while recording safe derived compatibility diagnostics on a later successful verification.
- Kept reverse status regressions, HTTP 202 challenges, origin/redirect/provider drift, signed-identity drift, and every page/media/plugin/backup/runtime gate fail-closed.
- Left the Metadata Bridge 0.57.7 and Upgrade Bootstrap 0.3.0 artifacts unchanged and did not authorize any live action.

## v0.59.89

- Centralized every active WordPress HTTP caller behind one exact-origin request policy.
- Set `Project-Atlas-WordPress/v0.59.89` as the stable non-browser WordPress User-Agent.
- Added fail-closed host, redirect, and User-Agent override enforcement plus safe response-source classification.
- Corrected Sandbox reporting so loaded credentials remain distinct from REST reachability and authentication.
- Added the authenticated identity and optional fixed Atlas read-only status stages.
- Preserved SiteGround security and every existing guarded mutation boundary.

## v0.59.88

Completed the guarded bootstrap backup-renewal recovery contract with authoritative durable lifecycle fields. The read-only response now separates operation completion from audit status and explicitly reports backup source, server-computed expiration state, renewal capacity, eligibility, deterministic reason code, recommendation, next action, upload/verification/activation/quarantine state, and pending-operation state. The operator UI renders these fields without inferring protected lifecycle state, preserves the narrow request contract, and uses the exact actions **Run renewal preflight** and **Apply guarded renewal**. Metadata Bridge 0.57.7 and Bootstrap 0.3.0 artifacts remain unchanged, and publication does not authorize live renewal or any WordPress/cache mutation.

## v0.59.87

Corrected the guarded bootstrap backup-renewal operator interface so every replacement-backup value and safety attestation is explicit. The UI now loads audit 1 through the read-only recovery assessment, displays the immutable original backup, effective active backup, ordered renewal history, expiration and renewal-limit state, and keeps preflight and apply visibly separate. Completion and deadline require timezone-aware ISO-8601 values; the optional four-hour calculation is a deliberate reviewable action. The no-relevant-WordPress-change attestation defaults false and is never synthesized. Focused component, validation, request-contract, refresh, warning, and post-renewal tests lock the corrected behavior.

## v0.59.86

Added a dedicated Atlas-only SiteGround backup-renewal lifecycle for an unresolved manual Bootstrap 0.3.0 handoff. The original authorization backup and evidence remain immutable; each explicitly approved replacement is stored as a sequenced renewal with a separate active-backup pointer. Preflight is zero-write, apply uses a short-lived process-memory single-use fingerprint and an audit-specific phrase, equivalent retries are idempotent, and conflicting or stale requests fail closed. Manual verification and activation use the current replacement backup while preserving authorization history. Renewals are limited to three and are prohibited after manual verification or activation begins.

## v0.59.85

Separated historical manual-upload authorization evidence from fresh manual-install verification evidence. Verification now requires a new, valid, unexpired schema-v1 proof and compares a server-computed stable public-identity fingerprint that excludes evidence IDs, acquisition timestamps, durations, volatile cache headers, and ephemeral request identifiers. The original authorization evidence remains intact; the successful verification evidence identity and stable-match result are stored separately in the durable upload snapshot. Equivalent stable retries remain idempotent and zero-write, while expired, reused, tampered, or drifted evidence fails without downgrading a successful audit. Existing SiteGround backup identity and four-hour deadline remain mandatory; this release does not silently renew or replace an expired backup.

## v0.59.84

Corrected the audited bootstrap manual-upload and fixed-entry activation handoffs so rerun observations bind deterministic rendered identity rather than volatile acquisition timestamps. The stable fingerprint covers the exact URL/redirect/HTTP/content classification, signed browser identity, title, ordered H1 and canonical inventories, image identity, rendered/head/visible/raw-DOM hashes where present, metadata and privacy evidence, authentication/challenge classifications, and normalized SiteGround provider identity. Raw sanitized observations remain diagnostic. A reused v0.59.78 temporal contract permits only later observations within the signed-evidence, one-time-handle, SiteGround-backup, two-minute, and one-second clock-tolerance bounds. Stable drift fails with deterministic non-secret reason codes before any audit or write. Manual-install verification remains monotonic, and post-activation verification and recovery stay unchanged because they do not compare rerun observation timestamps. Metadata Bridge 0.57.7 and bootstrap 0.3.0 artifacts are unchanged. Publication does not authorize any live action.

## v0.59.83

Made the durable `manual_installation_inventory_verified` bootstrap checkpoint monotonic. Equivalent current retries now return idempotent success with zero request writes, while stale, expired, drifted, or conflicting retries return deterministic HTTP 409 conflicts without changing status, transition history, cumulative audit writes, or activation eligibility. A sanitized canonical proof and SHA-256 fingerprint bind the committed result; process serialization plus `SELECT ... FOR UPDATE` prevents concurrency losers from overwriting it. Pre-success failure behavior, activation revalidation, read-only recovery, Metadata Bridge 0.57.7, and bootstrap 0.3.0 remain unchanged. Publication does not authorize any live action.

## v0.59.82

Made the signed manual-browser-evidence JSON envelope safe across Windows PowerShell 5.1 by emitting ASCII-only JSON with standard Unicode escapes. Parsed evidence, schema-v1/schema-v2 meaning, canonical HMAC input, signatures, privacy gates, and the byte-exact UTF-8 DOM input contract are unchanged. Added a regression that round-trips the locked Orlando en dash through the Windows ANSI-default operator path and verifies the signature remains valid. Concurrent successful manual-install verification is now idempotent under the existing process lock, preventing duplicate audit finalization. Publication does not authorize browser capture, bootstrap upload or activation, Metadata Bridge upgrade, metadata rendering, cache purge, or page/media mutation.

## v0.59.81

- Added an audited manual handoff for the one locked upgrade-bootstrap 0.3.0 artifact, a separate fixed-entry activation, immediate authenticated executable-checksum quarantine, durable establishment audit, and read-only recovery classifications without introducing arbitrary upload or activation controls.

## v0.59.80

Replaced the browser-evidence helper's PowerShell/native standard-input text path with a byte-exact BOM-free UTF-8 file contract under ignored `.runtime`. Capture and helper independently hash the same raw bytes; invalid encoding, BOMs, replacement characters, stale or escaped inputs, symlinks, and hash drift fail closed. The helper always removes raw DOM, and the Windows-to-Linux Docker harness handles only binary paths/hashes and signed JSON without shell interpolation. Existing schema-v1/schema-v2 identity, metadata, privacy, signature, and downstream workflow gates remain strict. Metadata Bridge remains version 0.57.7 with an unchanged ZIP.

## v0.59.79

Corrected Metadata Bridge authoritative REST preview rendering by separating a deterministic query-context-independent serializer from the strict page-8 public wrapper. The public `wp_head` path still excludes admin, REST, AJAX, cron, CLI, feeds, search, archives, previews, and unrelated pages, while the authenticated read-only preview validates post identity and calls the same pure serializer directly. Added immutable Metadata Bridge 0.57.7 and bootstrap 0.3.0 artifacts plus separately locked 0.57.6-to-0.57.7 upgrade and cleanup profiles. The future upgrade preserves active status, disabled rendering, staged payload hash, revision 1, page/media/site state, and zero cache purges. Publication does not authorize any live upgrade, rendering, metadata, cache, page, or media action.

## v0.59.78

Corrected cache-aware rendering and SiteGround cache-purge apply binding so a required second public observation may have a later timestamp and naturally advanced cache age without invalidating its one-time handle. Both phases now bind a deterministic stable public-observation fingerprint and an explicit temporal contract covering the original observation, evidence lifetime where applicable, handle lifetime, backup deadline, maximum two-minute interval, and one-second clock-reversal tolerance. URL, redirects, HTTP/provider classification, sanitized stable provider headers, browser/page identity, rendered hashes, metadata inventory, runtime, plugin, payload, revision, page/media snapshots, backup identity, and audit state remain fail-closed. Raw sanitized observations remain diagnostic-only. Final post-purge verification still requires two exact HTTP 200 public responses. Metadata Bridge remains version 0.57.6 with an unchanged ZIP.

## v0.59.76

Separated cache-aware pre-enable proof responsibilities so fresh signed schema-v1 browser evidence remains authoritative for public DOM and metadata state while a credential-free direct HTTP response supplies only bound transport, body-hash, and sanitized SiteGround provider evidence. An exact, zero-redirect HTTP 403 may now identify the provider through recognized headers without treating its body as page content or claiming a cache HIT. HTTP 202, challenges, unsafe browser evidence, mismatched URLs or timing, and missing or malformed provider headers remain blocked. Post-purge HTTP 200 and exact-metadata verification is unchanged. Metadata Bridge remains version 0.57.6 with an unchanged ZIP.

## v0.59.74

Fixed the cache-aware rendering preflight without changing Metadata Bridge PHP. Plugin identity matching now reuses Atlas's established fail-closed WordPress REST identifier normalizer, preserving raw plugin inventories while accepting only the locked extensionless or complete bridge entry path. Signed browser evidence remains authoritative for DOM state, while one separate credential-free public HTTP observation supplies only allowlisted, sanitized status and cache-header evidence. The observations are bound by exact URL, zero redirects, page identity, rendered hashes, and lifetime. SiteGround detection rejects empty, malformed, unrecognized, challenge, HTTP 202/403, redirected, or identity-mismatched responses; `server: nginx` is supporting evidence only. Rendering and cache apply routes remain separate, single-use-handle and phrase gated. Metadata Bridge remains version 0.57.6 with an unchanged ZIP.

## v0.59.71

Added an independently version-bound Metadata Bridge 0.57.5-to-0.57.6 upgrade profile and single-purpose bootstrap 0.2.0. The guarded preflight binds the verified prior installation, activation, upgrade, bootstrap-cleanup, staging, and recovery-disable history; exact backups and runtime identity; the staged payload hash and revision 1; disabled rendering; page/media/cache snapshots; and both locked artifacts. Apply can perform only one fixed bootstrap replacement and preserves active status and all staged metadata state. Post-upgrade verification requires the exact disabled-preview HTTP 409 contract and registered cache-aware routes; preview output remains explicitly deferred to a later rendering preflight. Bootstrap 0.2.0 cleanup is separately phrase-gated and cannot match 0.1.0. Publication does not authorize a live bootstrap action, bridge upgrade, rendering change, cache purge, or page/media mutation.

## v0.59.68

Added a fail-closed recovery-disable eligibility path for the exact case where a rendering-enable mutation was conclusively accepted but its public rendered verification failed. Ordinary disablement after a verified enable remains unchanged. Recovery requires the fixed enable endpoint and one accepted write, exact `pending -> verification_failed` history, unchanged staged payload/hash/revision/page/media/cache state, absent public metadata, verified staging history, and the `disable_rendering` recommendation. A future recovery disable creates a new audit with completion mode `recovery_after_failed_enable_verification`; it never rewrites the failed enable audit. Migration 0021 adds durable lifecycle completion-mode and recovery-recommendation fields. Metadata Bridge PHP and the 0.57.5 ZIP are unchanged. Publication does not authorize live disablement.

## v0.59.64

Replaced the metadata-staging blanket `not audits` check with an explicit fail-closed lifecycle-history eligibility model. A pristine initial state may now proceed after terminal failed staging attempts only when durable audit evidence proves the request was rejected without an accepted metadata mutation: exact `pending -> failed` history, completed failure, trustworthy attempted-write count, failed WordPress-response gate when a request was attempted, identical initial pre/post snapshots, revision `0 -> 0`, rendering `false -> false`, and no metadata state or sync-audit rows. Pending, verified, uncertain, partially mutated, malformed, or non-staging history remains blocked with precise non-secret reason codes. Metadata Bridge PHP and the 0.57.5 ZIP are unchanged. Publication does not authorize live staging or rendering enablement.

## v0.59.62

Fixed backend/Metadata Bridge optimistic-snapshot hash parity for the separated metadata lifecycle. The backend now preserves and validates the installed executable `plugin_checksum`, canonicalizes the exact seven fields hashed by Metadata Bridge 0.57.5, and reports allowlisted non-secret conflict reason codes. Failed lifecycle audit ID 1 remains immutable historical evidence of the pre-fix HTTP 409 and its zero accepted WordPress mutations. Metadata Bridge PHP and the 0.57.5 ZIP are unchanged. Publication does not authorize another staging attempt or rendering enablement.

## v0.59.59

Added a separately gated, two-phase upgrade-bootstrap cleanup lifecycle. Token-free preflights bind fresh backups, schema-v1 evidence, verified installation/activation/upgrade audits, runtime identity, exact plugin inventories, and page/media/metadata state. Phrase-gated deactivation can only set the fixed bootstrap inactive; a separate phrase-gated deletion can only delete that already-inactive fixed bootstrap. Migration 0020 adds `WordPressBootstrapCleanupAudit`, and Data Backup v0.36 preserves its audit history. Publication does not authorize live cleanup.

## v0.59.57

Replaced the unusable wp-admin upload-nonce transport with a separately approved, application-password-compatible, single-purpose upgrade bootstrap. The exact deployed Metadata Bridge 0.57.4 artifact has no self-upgrade route, so the guarded preflight now fails closed until bootstrap 0.1.0 is separately installed and active. Atlas can then send only the locked 0.57.5 ZIP to one fixed REST endpoint. The bootstrap validates the complete archive and becomes unusable after the bridge reaches 0.57.5. Publication does not authorize bootstrap installation or the live bridge upgrade.

## v0.59.55

Added a token-free, one-time-handle guarded Metadata Bridge upgrade from 0.57.4 to 0.57.5, a fixed standard-upgrader transport, post-upgrade verification, read-only recovery assessment, `WordPressPluginUpgradeAudit`, migration 0019, and Data Backup v0.35 portability. Publication does not authorize a live upgrade.

## v0.59.54

Separated Metadata Bridge payload staging, rendering enablement, rendering disablement, and payload rollback. Metadata Bridge 0.57.5 adds four isolated plugin-owned write surfaces and disables the legacy combined apply endpoint. Atlas adds token-free preflights, short-lived one-time process-memory handles, four lifecycle audit types, four-hour backup enforcement, schema-v1 evidence fallback, exact Organization plus Service payload validation, and Data Backup v0.34 lifecycle-audit portability.

Verification before checkpoint:

- Frontend TypeScript and production build passed
- Backend tests passed: 556, with 1 intentional platform-specific skip
- Migration 0017 → 0018 → 0017 → 0018 passed
- Plugin ZIP portability and source byte comparison passed



\## v0.11



QA readiness checks, gated approval, and internal preview banner.



\## v0.12



QA remediation, notes, and approval audit trail.



\## v0.13



Manual page editor, revision history, and WordPress draft workflow foundation.



Included:



\- WordPress Sandbox

\- Draft Queue

\- Draft Review

\- Export Package page

\- WordPress draft services

\- Page export services

\- WordPress draft audit migration



Verification before checkpoint:



\- Frontend build passed

\- Backend tests passed: 119

\- Git tag: v0.13



\## v0.14



Platform Portability and Restore Readiness.



Goal:



If the current computer dies, Atlas can be rebuilt on another computer without guessing.



Planned focus:



\- New computer setup instructions

\- Backup and restore documentation

\- Protected path rules

\- Version history documentation

\- Standard verification commands
# Project Atlas version history

## v0.59.91

- Added a phrase-gated Atlas-only terminal retirement for stale pre-activation Bootstrap authorizations when immutable SiteGround transport evidence proves genuine HTTP 403 block to HTTP 200 cached-public drift.
- Added a distinct fresh authorization mode for the exact installed, single, inactive Bootstrap 0.3.0 without upload, reinstall, replacement, deletion, activation, or any WordPress mutation.
- Added migration 0025 and Data Backup schema 0.39 so retirement reason, authorization mode, and renewal history remain durable while 0.38 backups remain supported.
