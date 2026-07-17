# Project Atlas v0.59.62 metadata snapshot parity

This release corrects the backend side of the existing Metadata Bridge 0.57.5 optimistic-lock contract. It is a local source release only. It does not authorize live WordPress access, another staging attempt, rendering enablement, rollback, cache purge, or any page/media change.

## Root cause

The authenticated bridge status response contains both `checksum` and `plugin_checksum`. Both are the SHA-256 produced by the installed plugin executable using `hash_file('sha256', __FILE__)`. The backend previously removed `plugin_checksum` in `_public_status()` and then constructed `expected_snapshot_hash` from that redacted object. Its missing field serialized as JSON `null`, while the bridge hashed the real executable checksum. The bridge therefore returned HTTP 409 before any metadata mutation.

Failed `WordPressMetadataLifecycleAudit` ID 1 is preserved exactly as historical evidence: `stage_metadata_payload`, `pending -> failed`, one rejected PUT, HTTP 409, zero accepted WordPress state mutations, and no metadata-state row.

## Two-layer safety contract

The plugin-owned optimistic snapshot contains exactly the fields already enforced by `atlas_metadata_snapshot_hash()` in Metadata Bridge 0.57.5:

1. `rendering_enabled`
2. `enabled_metadata_state`
3. `activation_generation`
4. `plugin_checksum`
5. `payload_hash`
6. `revision`
7. `payload`

The backend now requires every field, preserves strict JSON types, requires a lowercase 64-character executable checksum, verifies `plugin_checksum == checksum`, requires bridge version 0.57.5 and active status, and hashes compact JSON with recursively sorted object keys, PHP-compatible escaped Unicode, and unescaped slashes. The serialized characters are encoded as UTF-8 bytes. Missing, malformed, stale, or mismatched values fail before a WordPress request.

The broader Atlas lifecycle binding remains a separate outer layer. It binds plugin slug, entry, version, release ZIP checksum, active status, repository/runtime identity, backup identities, page/body snapshot, media 31/32 snapshots, Site Title, Tagline, cache observation, evidence hashes, audit history, action, and expiry. These fields are not added to the plugin-owned optimistic hash because Metadata Bridge 0.57.5 does not hash them; they remain fail-closed preflight and post-verification gates.

## Three distinct hashes

- Release ZIP SHA-256 `09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7` authenticates the portable 0.57.5 distribution artifact.
- Installed executable checksum is returned by the live bridge and is derived from the exact installed `project-atlas-metadata-bridge.php` bytes. It is not interchangeable with the ZIP checksum.
- Optimistic snapshot SHA-256 binds the seven canonical plugin-owned state fields above. It changes whenever the executable checksum or lifecycle state changes.

## Safe diagnostics

No WordPress error message, credential, handle, payload content, authentication data, or filesystem path is returned as a diagnostic. The allowlisted reason codes are:

- `plugin_checksum_missing`
- `plugin_checksum_mismatch`
- `snapshot_field_mismatch`
- `optimistic_snapshot_hash_mismatch`
- `wordpress_http_<status>` for an otherwise unclassified response

HTTP 409 behavior remains fail-closed. The backend never retries automatically.

## Write boundary

Preflight remains zero-write. Staging apply can reach only `PUT /wp-json/project-atlas/v2/pages/8/metadata/stage`. Its body contains the exact canonical payload, payload hash, expected revision, and expected optimistic snapshot hash. It cannot enable rendering or reach page, media, cache, Site Title, Tagline, plugin installation, activation, upgrade, cleanup, or deletion writes. Metadata Bridge checks revision and snapshot hash before calling any `update_post_meta` or `delete_post_meta` mutation.

Metadata Bridge PHP did not change. The plugin remains version 0.57.5 and its existing ZIP remains authoritative. A fresh published Atlas runtime, backups, evidence, preflight, and separate authorization are required before staging may be attempted again.
