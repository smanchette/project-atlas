\# Project Atlas Version History

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
