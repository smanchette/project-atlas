# Project Atlas v0.59.83 — Manual-Install Verification Idempotency

## Defect and invariant

The v0.59.82 manual bootstrap workflow correctly serialized simultaneous successful verification requests, but a later retry was allowed to run the pre-success failure transition logic. If current protected state or inventory differed, that retry could replace the durable `manual_installation_inventory_verified` checkpoint with `manual_installation_mismatch`, append a transition, and increment the Atlas audit-write count.

v0.59.83 makes `manual_installation_inventory_verified` a monotonic successful checkpoint. Once committed, the manual-install verification route has only two outcomes:

- an equivalent, current retry returns the existing successful status with `idempotent_replay=true`, `request_atlas_write_count=0`, and no durable mutation;
- a stale, expired, drifted, or otherwise non-equivalent retry returns HTTP 409 with a non-secret reason code and performs no durable mutation.

The checkpoint cannot move backward to a mismatch, failure, recovery, or waiting state through this retry route. A later state transition is possible only through an independently gated activation or separately approved recovery workflow.

## Durable equivalence binding

The first successful verification stores a SHA-256 fingerprint and its sanitized canonical proof in the already-existing upload snapshot. The proof binds:

- establishment audit ID, Atlas page 41, and WordPress page 8;
- the fixed bootstrap slug, directory, entry, version, ZIP checksum, entry checksum, and inactive status;
- independent runtime identity;
- Atlas and SiteGround backup identity and deadline fields;
- signed browser-evidence ID;
- exact bootstrap classification;
- complete and active plugin-inventory hashes;
- protected page, body, media, Site Title/Tagline, rendered state, cache state, rendering flag, payload hash, revision, and payload snapshots.

The request schema forbids extra fields, so callers cannot submit a fingerprint, audit status, transition history, or write count. The proof contains no credentials, cookies, raw handles, authorization headers, or signing keys.

## Locking and transaction boundary

Verification acquires the existing backend process lock before reading or inspecting the audit. It then reads the selected audit with `SELECT ... FOR UPDATE` and refreshes any identity-map value. The lock remains held through classification and the one successful commit. PostgreSQL supplies the row lock; the process lock supplies equivalent serialization for SQLite tests and prevents same-process competitors from making a decision on stale state.

The status is therefore re-read inside the serialized transaction. Only an `awaiting_manual_bootstrap_installation` audit may make the first success or an approved pre-success failure transition. Every concurrency loser observes the committed successful checkpoint and is classified as an idempotent replay or zero-write conflict. A rollback before commit leaves the audit waiting and never exposes a false successful state.

## Response and conflict taxonomy

Equivalent replay returns HTTP 200 with:

- `status=manual_installation_inventory_verified`;
- `idempotent_replay=true`;
- `reason_code=manual_install_verification_idempotent_replay`;
- `request_atlas_write_count=0`.

Non-equivalent replay returns HTTP 409 and one of:

- `manual_install_protected_state_drift`;
- `manual_install_inventory_drift`;
- `manual_install_backup_identity_drift`;
- `manual_install_evidence_mismatch`;
- `manual_install_request_stale`;
- `manual_install_conflicting_retry`;
- `manual_install_retry_not_equivalent`.

The first authorization write and first successful verification write remain the only two Atlas audit writes at this checkpoint, and the successful transition appears exactly once.

## Safety boundary and related workflow review

Pre-success behavior is unchanged: no upload remains waiting, and genuine active/partial/mismatched upload observations may use the existing fail-closed transition contract. Post-success retry classification is deliberately separated and never invokes that transition path.

Activation preflight remains independent and revalidates credentials, backups, runtime identity, inactive bootstrap identity, complete inventories, and protected state. Equivalent or conflicting verification retries do not erase activation eligibility; actual current-state drift may still block activation through those gates. Recovery assessment remains read-only and may report current drift without rewriting the checkpoint.

The bootstrap authorization, bootstrap activation, plugin-upgrade verification, bootstrap-cleanup verification, rendering recovery, and cache-aware finalization workflows were reviewed for the same freely retryable post-success verification pattern. Their mutation paths are already protected by consumed one-time handles, fixed status gates, or separate read-only recovery endpoints. No identical downgrade-on-retry path was found, so they are unchanged.

This release adds no WordPress or cache mutation path and authorizes no live operation.
