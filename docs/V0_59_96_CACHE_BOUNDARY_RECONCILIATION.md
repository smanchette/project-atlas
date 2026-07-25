# Project Atlas v0.59.96 — Cache-Boundary Reconciliation

## Scope

This release preserves root-cause classification **B**: the Metadata Bridge
0.57.7 upgrade succeeded, but a transient SiteGround `HIT` to `MISS`
observation was incorrectly treated as durable protected-state drift.

The correction is limited to the locked 0.57.6-to-0.57.7 upgrade verifier and
the exact failed Upgrade Audit ID 3 recovery contract.

## Semantic cache boundary

The comparison requires normalized, flat, allowlisted headers. It permits only:

- recognized `HIT`/`MISS` request-cache status variation;
- numeric `age` variation;
- parseable `expires` variation;
- absent/present SiteGround diagnostics matching the established `DT:<number>`
  form or the observed exact structural form `<number> NC:<hex> UP:`.

It still requires exact provider family, nginx origin support, cache
enablement, URL, redirect count, HTTP status, privacy classification, response
source, rendered-head hash, visible-content hash, cache-control, validators,
and allowlisted security headers. Unknown, misspelled, nested, malformed, or
unrecognized values fail closed. Cache purge count must remain zero.

## Atlas-only reconciliation

Routes:

- `POST /api/wordpress/deployment/metadata-bridge/upgrade/reconciliation/preflight/{page_id}`
- `POST /api/wordpress/deployment/metadata-bridge/upgrade/reconciliation/apply/{page_id}`

Confirmation phrase:

`RECONCILE PROJECT ATLAS METADATA BRIDGE UPGRADE AUDIT 3 WITHOUT ANOTHER WORDPRESS WRITE`

Preflight requires the exact v0.59.96 runtime and repository identity, Audit
ID 1 `authorization_retired`, Audit ID 2 `verified`, Audit ID 3
`verification_failed`, the original one-write 0.57.6-to-0.57.7 upgrade, fresh
schema-v1 signed browser evidence, authenticated GET-only WordPress
observations, exact plugin and Bootstrap checksums, unchanged inventories and
durable protected state, zero pending lifecycle operations, and a synchronized
Atlas Data backup created after the corrected runtime was loaded.

No SiteGround backup is required because apply performs:

- WordPress writes: 0
- plugin writes: 0
- cache writes: 0
- Atlas writes: exactly 1

Apply consumes one process-memory handle and updates only Upgrade Audit ID 3.
It preserves the original `pending → verification_failed` history, failure
gates, verification findings, post-upgrade snapshot, inventories, and original
WordPress write. It appends
`cache_boundary_volatile_observation_reconciled` and moves the audit to the
existing `verified` success state.

Publication and runtime loading do not execute reconciliation.
