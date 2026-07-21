# Project Atlas v0.59.85 — Fresh Manual-Install Evidence

## Root cause and lifecycle model

Manual bootstrap upload is a human handoff. The signed browser evidence used to authorize that handoff has a fifteen-minute lifetime and can legitimately expire while the operator uploads the fixed ZIP in WordPress Admin. The previous verification path nevertheless required that original evidence to remain current while also including its ID and timestamps in protected-state equality. Reusing it failed as expired; replacing it with fresh evidence failed as drift.

v0.59.85 separates the two proofs without erasing either:

- **Authorization evidence** records the public and protected state before the manual handoff. Its ID, capture time, expiry, schema/helper identity, and stable fingerprint remain historical audit data.
- **Verification evidence** is newly captured after the upload. It must be signed, schema v1, unexpired, credential-free, and use an ID different from the authorization evidence. Its identity, times, stable fingerprint, and match result are stored separately in the durable upload snapshot.

No raw evidence payload, HMAC signature, cookie, credential, Authorization header, or runtime handle is persisted in the new audit summaries.

## Stable cross-phase identity

Atlas computes the fingerprint; request models forbid caller-supplied fingerprint fields. The stable value binds the canonical requested and final URL, redirect/status/response classification, normalized content type and SiteGround provider identity, title, ordered H1 and canonical inventories, featured image identity, rendered-head/visible-content/raw-DOM hashes where available, metadata-inventory hash, schema/helper compatibility, and credential/cookie/admin/login/challenge/error classifications.

The cross-phase value excludes evidence ID, capture and expiry timestamps, observation timestamps, request start/completion time, elapsed duration, HTTP Date/Age/Expires/Last-Modified, and ephemeral request identifiers. Those remain diagnostic or historical fields and are never treated as permission to ignore meaningful identity drift.

## Verification, idempotency, and concurrency

The first valid fresh verification uses the existing process lock and `SELECT ... FOR UPDATE`, records the fresh verification evidence summary, and transitions exactly once to `manual_installation_inventory_verified`. WordPress and cache writes remain zero. A retry using either the same valid verification evidence or another fresh evidence ID with the same stable identity returns the committed result with zero writes. Non-equivalent, expired, reused authorization, invalid-signature, runtime, backup, inventory, privacy, or protected-state requests return deterministic conflicts and cannot downgrade durable success.

Activation preflight continues to require current valid evidence, current credentials, exact inventory, protected state, runtime identity, and an unexpired SiteGround backup. Its handle remains process-memory-only, short-lived, single-use, and restart-invalidated. Fixed-entry activation and immediate checksum quarantine are unchanged.

## Backup deadline

The authorization records the original SiteGround backup identity. Manual verification and activation must still finish within that backup's four-hour deadline. v0.59.85 does not renew a backup, attach a replacement backup to the existing audit, or silently substitute identity. If the original deadline expires, the audit remains unchanged and a separately designed guarded backup-renewal or reauthorization workflow is required.

## Related workflow review

The bootstrap manual upload is the only current workflow that deliberately pauses between authorization and an inventory-verification request while reusing the plugin-upgrade proof model. Metadata Bridge installation uses its dedicated installed-inactive reconciliation with fresh evidence. Bootstrap cleanup, plugin upgrade, activation, metadata lifecycle, rendering, and cache operations keep preflight/apply handles inside short immediate handoffs and already revalidate current evidence. No equivalent cross-human-delay change was applied outside bootstrap establishment.
