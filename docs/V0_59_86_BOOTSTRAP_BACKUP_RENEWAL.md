# Project Atlas v0.59.86 — Guarded Bootstrap Backup Renewal

## Purpose

An audit-bound SiteGround backup cannot be silently replaced after a human manual-upload delay. The original backup is authorization history: changing its reference or completion time would rewrite the conditions under which the upload was authorized. v0.59.86 adds a separate Atlas-only renewal lifecycle for an existing unresolved bootstrap-establishment audit.

## Routes and approval

- `POST /api/wordpress/deployment/upgrade-bootstrap/backup-renewal/preflight/{page_id}`
- `POST /api/wordpress/deployment/upgrade-bootstrap/backup-renewal/apply/{page_id}`
- `POST /api/wordpress/deployment/upgrade-bootstrap/backup-renewal/recovery/assess/{page_id}`

For audit 1 the exact phrase is `RENEW PROJECT ATLAS BOOTSTRAP HANDOFF BACKUP FOR AUDIT 1`. It authorizes one Atlas audit update only. It authorizes no WordPress, cache, plugin, upload, activation, verification, checksum, restore, page, media, settings, payload, or rendering action.

## Immutable and active backup model

`backup_evidence` remains the immutable original authorization backup. Migration 0024 adds `backup_renewals`, an ordered JSON history, and `active_backup_evidence`, the current replacement used by later verification and activation timing gates. Each renewal records its sequence, replacement evidence, prior and current identity fingerprints, handle fingerprint, approval time, and committed status. Authorization evidence, protected state, source inventories, and prior transitions are not rewritten.

## State machine and safety

Renewal is limited to `awaiting_manual_bootstrap_installation` before verification, activation, or checksum quarantine. The active backup must be expired, the replacement must be newer and unexpired, and its deadline must be exactly four hours after its timezone-aware completion. Database, `wp-content/plugins`, restore, no-post-backup-change, operator, and Atlas backup attestations are mandatory. The preflight writes nothing. Apply consumes a short-lived process-memory fingerprint, reruns all gates under the process lock and database row lock, and appends one `backup_renewal_N_committed` event.

Equivalent retry through a new preflight is idempotent and zero-write. A consumed handle cannot be replayed. Non-equivalent renewal while the active backup remains valid is blocked. If a replacement expires before manual verification, another renewal is permitted up to a conservative maximum of three. Renewal is prohibited after verification or activation begins; checksum-quarantine expiration requires read-only recovery assessment and a separately approved recovery plan.

## Continuation

After renewal, the operator must not repeat the upload or activate the bootstrap. Atlas requires fresh signed schema-v1 evidence and the existing manual-install verification route. Verification compares the current live state with the original stable authorization identity while binding timing and backup gates to the active replacement. Successful verification preserves both the original backup and renewal history. Activation remains separately gated and independently revalidates the replacement backup, inventory, runtime, credentials, evidence, and protected state.

Recovery assessment is read-only and returns one of: create a fresh SiteGround backup, run guarded renewal, proceed to manual verification, renew again, require new authorization, guarded bootstrap recovery, SiteGround restore, or no action.
