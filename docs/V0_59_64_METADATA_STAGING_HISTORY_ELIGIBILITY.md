# Project Atlas v0.59.64 metadata-staging history eligibility

This release corrects only the Atlas preflight rule that determines whether a new initial metadata-staging attempt may begin. It does not authorize live WordPress access, staging, rendering enablement, rollback, cache purge, or any page/media change.

## Root cause

The original initial-state gate required `not audits`. That correctly allowed the first attempt but permanently blocked every later attempt, including after a terminal HTTP 409 that Metadata Bridge rejected before accepting any metadata mutation. Failed lifecycle audit ID 1 must remain immutable historical evidence, so deleting or resetting the audit was not an acceptable recovery.

## Corrected eligibility

Live state must independently remain pristine:

- payload is `null`;
- payload hash is empty;
- revision is `0`;
- rendering is disabled;
- no `WordPressMetadataState` row exists;
- no legacy `WordPressMetadataSyncAudit` row exists; and
- fresh page, media, site, cache, artifact, runtime, backup, evidence, and optimistic-snapshot gates still pass.

Historical lifecycle records are then evaluated individually. No prior record is required for a first attempt. Every existing record must otherwise be a completed `stage_metadata_payload` failure with exact `pending -> failed` history and durable zero-accepted-mutation proof.

The current schema records attempted WordPress requests, not a separate accepted-mutation counter. Atlas therefore derives `accepted_metadata_mutation_count = 0` only when all of these durable facts agree:

- attempted write count is a trustworthy integer of `0` or `1`;
- an attempted request has a failed `wordpress_response` gate with a recognized plugin conflict code proving rejection before mutation (generic HTTP errors and transport failures remain uncertain);
- status is `failed`, `error_code` is `failed`, completion time exists, and Atlas finalization count is `2`;
- pre- and post-snapshots are present and byte-equivalent as structured JSON;
- both snapshots have null payload, empty payload hash, revision `0`, disabled rendering, and disabled metadata state;
- previous and final revision are both `0`; and
- previous and final rendering values are both `false`.

This derivation is deliberately fail-closed. Missing post-state, missing mutation evidence, an unfinished audit, verification uncertainty, any state delta, or any other action/status blocks a new attempt. It does not reinterpret or modify the historical audit.

Audit ID 1 predates the normalized conflict-code and `plugin_checksum` snapshot contracts. Its exact legacy combination—`HTTP 409`, absent checksum fields in both snapshots, and otherwise identical pristine pre/post state—is accepted for backward compatibility. A generic `HTTP 409` paired with a current checksum-bearing snapshot remains uncertain and blocked.

## Reason codes

- `initial_state_ready`
- `historical_failed_attempts_only`
- `pending_lifecycle_audit`
- `prior_verified_staging_exists`
- `prior_mutation_outcome_uncertain`
- `prior_failed_attempt_mutated_state`
- `live_metadata_state_not_initial`
- `conflicting_lifecycle_history`

The safe inspected-state summary may include audit ID, action, status, transitions, attempted write count, derived accepted mutation count, and derived recovery recommendation. It never includes credentials, raw handles, authentication material, raw evidence, or filesystem secrets.

## Current audit ID 1

Audit ID 1 evaluates as eligible without mutation: staging action, `failed`, `pending -> failed`, one attempted rejected PUT, identical initial pre/post snapshots, revision `0 -> 0`, rendering `false -> false`, derived accepted mutation count `0`, and recovery `no_action`. A future authorized apply creates a new audit ID; it never reuses or rewrites ID 1.

## Safety boundary

This change affects only initial staging-history eligibility. It does not change the seven-field optimistic snapshot, plugin checksum validation, canonical serialization, payload contract, handle/phrase rules, audit finalization, or any WordPress route. Staging can still reach only the fixed Metadata Bridge stage endpoint and cannot enable rendering. Rendering, disabling, and rollback remain separately gated.

Metadata Bridge PHP did not change. The plugin remains version 0.57.5 and the authoritative ZIP SHA-256 remains `09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7`.
