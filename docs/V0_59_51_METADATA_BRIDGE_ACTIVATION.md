# Project Atlas v0.59.51 — Guarded Metadata Bridge Activation

This release adds activation as a distinct lifecycle after the verified installed-inactive deployment. It does not authorize production activation or metadata deployment.

## Routes

- `POST /api/wordpress/deployment/metadata-bridge/activation/preflight/{page_id}` performs read-only inspection and creates no audit, nonce, token, Atlas row, or WordPress write.
- `POST /api/wordpress/deployment/metadata-bridge/activation/apply/{page_id}` accepts only an in-memory activation handle and the exact phrase `ACTIVATE PROJECT ATLAS METADATA BRIDGE`.

Both routes are hard-locked to Atlas page 41 and WordPress page 8. Installation, reconciliation, metadata apply, rollback, cache, page, media, plugin deletion, and restoration transports are not reachable from the activation service.

## Preflight request and binding

The request binds the verified installation audit, plugin slug/path/version and authorized ZIP checksum, inactive plugin inventories, page/body/media snapshots, expected runtime identity, repository identity attestations, fresh Atlas and SiteGround backup evidence, clean PHP/browser findings, and fresh signed schema-v1 browser evidence. Git is intentionally unavailable inside the slim backend container; exact HEAD/origin/tag, clean-tree, and protected-path facts are explicit request-bound operator evidence and are checked against the independently checksum-verified runtime identity.

Every gate must pass. A successful response is `activation_preflight_ready` and includes:

- a cryptographically random opaque handle stored only in backend process memory;
- its SHA-256 fingerprint, expiration, and a binding hash covering the full request, observed state, expected post-state, evidence, backup deadline, and handle expiration;
- the exact phrase;
- deterministic expected post-activation plugin and active-plugin inventory hashes;
- explicit zero WordPress writes and zero Atlas writes.

The handle is single-use, expires after at most ten minutes, never survives a backend restart, is removed on consume/expiry, and has no raw-token fallback. Wrong phrases are rejected before consumption. State drift after preflight causes a fresh preflight requirement.

## Single WordPress write

The activation function has one fixed write transport:

```text
POST /wp-json/wp/v2/plugins/project-atlas-metadata-bridge/project-atlas-metadata-bridge
{"status":"active"}
```

The endpoint path, method, and JSON body are constants. The service exposes no caller-controlled WordPress method, path, or body. It cannot reach plugin installation/deletion, page/media/settings, metadata, cache, or restore endpoints. WordPress activation invokes the plugin's existing activation hook, which initializes the private safety option with rendering disabled; that is part of the single WordPress activation request, not a second Atlas request.

Immediately before that request, Atlas creates one pending `WordPressActivationAudit`. Afterward, read-only GET observations verify the plugin, disabled safety status, empty payload/hash, revision zero, inventories, page, media, rendered metadata absence, site identity, and cache boundary. Atlas then finalizes only that audit. The response reports one WordPress request and two bounded Atlas persistence phases.

If the WordPress result is uncertain or final verification fails, Atlas records `failed` or `verification_failed` and stops. It never retries, deactivates, restores, purges cache, or applies metadata automatically.

## Activation audit

`WordPressActivationAudit` is separate from installation audit 1. Statuses are:

- `pending`
- `verified`
- `verification_failed`
- `failed`

It records the installation-audit reference, binding and handle fingerprints, phrase hash, runtime/artifact/backup/evidence identity, pre/post snapshots, gate results, exact write scopes/counts, and `pending → final` history. It stores no credentials, evidence signing key, raw handle, application password, or browser HTML.

Data Backup schema v0.33 includes this table while retaining compatibility with older backups, which import with an empty activation-audit group.

## Metadata separation

Activation does not authorize metadata. A verified active plugin must still report rendering disabled, payload `null`, empty payload hash, and revision `0`. Metadata state/audit rows remain absent. Any later metadata apply requires its own separately approved preflight, phrase/token, audit, backup gate, and route.
