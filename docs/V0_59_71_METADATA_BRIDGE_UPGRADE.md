# Project Atlas v0.59.71 guarded Metadata Bridge upgrade

## Scope and authorization boundary

v0.59.71 implements the local, fail-closed architecture for exactly one Metadata Bridge transition: active version 0.57.5 to active version 0.57.6. It does not authorize installing the bootstrap, upgrading the live plugin, enabling rendering, purging cache, changing the staged payload, or modifying page 8 or media 31/32. Every future live phase requires separate approval.

The strict runtime source identity is bound to Metadata Bridge 0.57.6, `project-atlas-metadata-bridge-0.57.6.zip`, and ZIP SHA-256 `3b2d0035f995c3006e0d3be02596bd2cf19ef7e4a97572168621beb7a9abf788`. Manifest schema, external manifest checksum, and independent expected version, commit, and tag validation remain fail-closed.

## Immutable bootstrap 0.2.0

`project-atlas-upgrade-bootstrap-0.2.0.zip` has SHA-256 `873701da2ed42212e7d7c9b12816eeb0560d2751d7494c2b706008c0d5c1383a`. It exposes only:

- `GET /wp-json/project-atlas-deployment/v1/metadata-bridge/upgrade-0576/status`
- `POST /wp-json/project-atlas-deployment/v1/metadata-bridge/upgrade-0576`

The helper accepts only the locked 0.57.6 archive while the existing bridge is active at exactly 0.57.5, rendering is disabled, the approved payload hash is `fe24398ee322ca8557814feb034a0ccff0302d5d26b6ea47b11001567854711d`, and revision is 1. It rejects archive wrappers, traversal, duplicate or unrelated files, version or byte drift, and caller-selected targets. It replaces only the existing bridge, preserves active and staged metadata state, and becomes unavailable after version 0.57.6 is present.

## Guarded upgrade

The established routes remain:

- `POST /api/wordpress/deployment/metadata-bridge/upgrade/preflight/{page_id}`
- `POST /api/wordpress/deployment/metadata-bridge/upgrade/apply/{page_id}`
- `POST /api/wordpress/deployment/metadata-bridge/upgrade/recovery/assess/{page_id}`

Apply requires the exact phrase `UPGRADE PROJECT ATLAS METADATA BRIDGE TO 0.57.6` and a short-lived, single-use process-memory handle from the zero-write preflight. Preflight binds fresh signed schema-v1 evidence; validated Atlas Data, Media, and Program backups; a timezone-aware SiteGround on-demand full-site backup no older than four hours with database, plugin-files, restore, confirmer, and no-post-backup-change attestations; verified runtime/repository identity; all required prior audits; current and target artifacts; bootstrap 0.2.0; plugin inventories; staged payload/hash/revision/status; disabled rendering; page/media snapshots; and zero cache purges.

Apply commits one pending `WordPressPluginUpgradeAudit` before exactly one fixed bootstrap request. The caller cannot select the URL, method, plugin, path, archive, version, multipart field, request body, payload, rendering state, page, media, cache, Site Title, Tagline, or unrelated plugin. There is no automatic retry or rollback after uncertain success. Only the selected upgrade audit is finalized after read-only verification.

## Deferred preview-output contract

Post-upgrade verification requires one active 0.57.6 bridge whose files match the locked artifact, unchanged unrelated plugins, staged payload and hash, revision 1, disabled rendering, staged Atlas metadata state with row counts 1/0, unchanged page/body/H1/canonical/media/site state, zero cache purges, and no public Atlas metadata.

The preview route must be registered at its exact locked path and its source implementation must match the 0.57.6 artifact. Because rendering remains disabled, the read-only preview request must fail closed with HTTP 409 and reason `atlas_rendering_preview_unavailable`. Returning preview output in this phase is a verification failure. Actual preview-output verification is deliberately deferred—not silently skipped—to the later separately authorized cache-aware rendering preflight. SiteGround purge capability, all cache-aware lifecycle routes, and the legacy combined metadata endpoint's HTTP 410 contract must also be present.

## Bootstrap cleanup

Bootstrap 0.2.0 cleanup reuses the established cleanup route family but is dispatched to a distinct version-bound profile. It requires the verified 0.57.5-to-0.57.6 upgrade audit, active bridge 0.57.6, the exact preserved staged payload/hash/revision/status, disabled rendering, and unchanged protected state.

- Deactivation phrase: `DEACTIVATE PROJECT ATLAS UPGRADE BOOTSTRAP 0.2.0`
- Deletion phrase: `DELETE PROJECT ATLAS UPGRADE BOOTSTRAP 0.2.0`

Deactivation and deletion are separate single-write operations with separate one-use handles and audit transitions. The 0.1.0 profile cannot accept the 0.2.0 identity or phrases, and the 0.2.0 profile cannot accept 0.1.0.
