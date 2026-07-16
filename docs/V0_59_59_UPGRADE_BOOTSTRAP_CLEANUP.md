# Project Atlas v0.59.59 guarded upgrade-bootstrap cleanup

This release adds the local architecture for removing the single-purpose Metadata Bridge upgrade bootstrap after the verified 0.57.5 bridge upgrade. Publication does not authorize live WordPress access, bootstrap deactivation or deletion, metadata staging, rendering, cache purge, restoration, or page/media changes.

## Fixed scope

The only cleanup target is:

- slug: `project-atlas-upgrade-bootstrap`
- entry: `project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap.php`
- version: `0.1.0`
- approved ZIP SHA-256: `4c8b4b0c697b2b352a10f405950c7b6a750236be96aec81fcd45176ece1189bd`

The protected Metadata Bridge must remain installed once, active, version 0.57.5, rendering-disabled, payload-free, and at revision 0. The page 8 body, media 31/32, site identity, plugin inventories, metadata rows, and cache observations are bound into each short-lived authorization.

## Routes and separation

All four Atlas routes use `POST` so requests can carry signed evidence and backup proof without placing it in URLs:

- `POST /api/wordpress/deployment/upgrade-bootstrap/cleanup/preflight/{page_id}`
- `POST /api/wordpress/deployment/upgrade-bootstrap/cleanup/deactivate/{page_id}`
- `POST /api/wordpress/deployment/upgrade-bootstrap/cleanup/delete/preflight/{page_id}`
- `POST /api/wordpress/deployment/upgrade-bootstrap/cleanup/delete/apply/{page_id}`

Both preflights are token-free, nonce-free, audit-free, and write-free. They require page 41/post 8; verified installation, activation, and upgrade audits; fresh schema-v1 browser evidence; independently verified runtime identity; a clean synchronized repository; protected paths unchanged; validated Atlas backup identities; a current four-hour SiteGround on-demand full-site backup; and exact page/media/plugin/metadata state.

The deactivation phrase is exactly:

`DEACTIVATE PROJECT ATLAS UPGRADE BOOTSTRAP`

The deletion phrase is separately gated and exactly:

`DELETE PROJECT ATLAS UPGRADE BOOTSTRAP`

Each successful preflight creates only a cryptographically random, ten-minute-or-shorter process-memory handle. The handle is bound to the action, page/post, audit IDs, runtime and repository identity, backup, evidence hashes and expiration, bootstrap and bridge identities, current inventories, page/media state, and expected post-action inventories. Handles are consumed atomically, cannot be replayed, are removed on expiry or validation failure, and disappear on backend restart. No signed raw token is returned or persisted. The opaque handle is not written to an audit, backup, file, log, or local storage; only its SHA-256 fingerprint is durable after apply begins.

## Exact WordPress writes

Deactivation is hard-coded to one request:

`POST /wp-json/wp/v2/plugins/project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap`

with exactly:

```json
{"status":"inactive"}
```

Deletion is hard-coded to one request with no body:

`DELETE /wp-json/wp/v2/plugins/project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap`

The API caller supplies only an opaque cleanup handle and the exact phase phrase. No caller field can select a plugin, slug, path, endpoint, HTTP method, status, or deletion body. No Metadata Bridge, page, media, metadata, rendering, cache, restoration, Site Title, Tagline, draft, or unrelated-plugin write is reachable from these functions. There is no automatic recovery and no automatic second WordPress write.

## Verification and audit contract

`WordPressBootstrapCleanupAudit` is introduced by migration `20260716_0020`, whose parent is `20260716_0019`. Its statuses are:

- `pending`
- `deactivated`
- `verified`
- `verification_failed`
- `failed`

Deactivation creates the audit as pending before its one WordPress write and finalizes it as `deactivated` only after GET-only verification proves the bootstrap remains installed once but inactive, its REST endpoints are absent, the bridge remains active at 0.57.5, and every protected state is unchanged.

Deletion requires a fresh preflight and a selected `deactivated` audit. It moves only that audit through a new pending transition, performs one fixed DELETE, then finalizes it as `verified` only after GET-only verification proves the bootstrap inventory entry and REST namespace are absent, separated metadata routes remain registered, the legacy combined apply contract remains disabled, and all bridge/page/media/metadata/cache invariants remain unchanged.

The audit stores only handle fingerprints and phrase hashes—not raw handles or credentials—plus exact identities, backup/evidence bindings, inventories, snapshots, gate results, write counts/scopes, transitions, findings, and recovery guidance. Data Backup v0.36 includes the table; older supported backups restore it as an empty group.

## Fail-closed recovery

No recovery runs automatically. After uncertain or failed deactivation verification, the only reported outcomes are `no_action`, `guarded_reactivation`, or `siteground_restore`. After uncertain or failed deletion verification, they are `no_action`, `guarded_reinstall`, or `siteground_restore`. Any recovery needs a later, explicit approval and fresh gates.

## Live boundary

This source release does not perform cleanup. A later live phase requires fresh Atlas and SiteGround backups, a stopping-point record, re-entered process-memory WordPress credentials, fresh signed browser evidence, successful token-free preflight, and the separately exact phrase for that phase. Deactivation and deletion must never be bundled.
