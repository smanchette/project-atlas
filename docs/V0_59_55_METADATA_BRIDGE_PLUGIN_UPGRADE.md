# Project Atlas v0.59.55 guarded Metadata Bridge plugin upgrade

This release implements the guarded upgrade architecture only. It does not authorize a live WordPress request, plugin upgrade, metadata staging, rendering change, cache purge, restoration, page change, or media change.

## Routes and authorization

- `POST /api/wordpress/deployment/metadata-bridge/upgrade/preflight/{page_id}` performs the complete read-only inspection. It creates no audit and performs zero WordPress and Atlas writes.
- `POST /api/wordpress/deployment/metadata-bridge/upgrade/apply/{page_id}` accepts only an opaque process-memory handle and the exact phrase `UPGRADE PROJECT ATLAS METADATA BRIDGE TO 0.57.5`.
- `POST /api/wordpress/deployment/metadata-bridge/upgrade/recovery/assess/{page_id}` is read-only and recommends `no_action`, `guarded_downgrade`, or `siteground_restore`. It never performs recovery.

The preflight handle lasts at most ten minutes and is further bounded by signed-evidence expiry and the four-hour SiteGround backup deadline. It is consumed atomically, is invalidated by backend restart, and is never stored in the database, a file, a backup, logs, or persistent frontend storage. The WordPress upload nonce is acquired transiently from the standard authenticated upload page and is never returned or persisted.

## Fixed mutation boundary

Apply can reach only the standard WordPress upload-overwrite endpoint:

`POST /wp-admin/update.php?action=upload-plugin`

The multipart upload is fixed in source to `project-atlas-metadata-bridge-0.57.5.zip`, SHA-256 `09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7`, with `overwrite_package=1`. The caller cannot choose the URL, HTTP method, slug, entry path, ZIP, version, multipart fields, or payload. No activation, deactivation, install-as-duplicate, deletion, metadata, page, media, cache, restoration, Site Title, or Tagline transport is reachable from the service.

The current artifact is locked to Metadata Bridge 0.57.4 and SHA-256 `939412e6e80e8344d95274444fda65b6122fe0c8249a2ced0a8582a418c4e232`. The target is exactly 0.57.5. Preflight requires verified installation and activation audit ID 1, an active singleton plugin, the authorized executable checksum, empty metadata state, disabled rendering, revision zero, unchanged page 8 and media 31/32, signed schema-v1 evidence, clean runtime/repository identity, validated Atlas backups, and a fresh SiteGround on-demand full-site backup.

## Audit and verification

Migration `20260716_0019` adds `WordPressPluginUpgradeAudit` with statuses `pending`, `verified`, `verification_failed`, and `failed`. It records the previous and target artifacts, runtime and backup identities, evidence hashes, handle and phrase fingerprints, previous and final inventories, metadata/rendering state, page/media snapshots, exact write scopes and counts, gate findings, recovery recommendation, and transition history. Data Backup v0.35 exports and restores the audit while remaining compatible with prior backup versions.

One pending audit is committed before the one WordPress replacement request. Read-only verification then requires version 0.57.5, the locked executable checksum, unchanged active status and unrelated plugins, empty disabled metadata state, unchanged page/media/site/cache state, the four separated lifecycle routes, and the locked artifact contract that disables the legacy combined apply route with HTTP 410. Verification failure never triggers an automatic downgrade or SiteGround restore.

After publication, a new ignored runtime manifest for the final v0.59.55 commit and tag is required before a separately approved live upgrade phase. That later phase also requires fresh SiteGround backup evidence, fresh signed schema-v1 evidence, and WordPress credentials entered only through `/wordpress-sandbox`.
