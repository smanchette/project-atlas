# Project Atlas v0.59.57 Metadata Bridge upgrade authorization correction

This release corrects the guarded upgrade transport only. It does not authorize live WordPress access, installation of the bootstrap helper, a Metadata Bridge upgrade, metadata staging, rendering enablement, cache purge, restoration, or any page or media change.

## Why the v0.59.55 transport failed

The v0.59.55 apply service used `POST /wp-admin/update.php?action=upload-plugin`. That WordPress Admin form requires an authenticated browser-cookie session and its upload nonce. WordPress application passwords authenticate REST and XML-RPC requests; they do not create a wp-admin cookie session. Supplying HTTP Basic application-password credentials to the wp-admin upload page therefore cannot yield the required nonce.

The exact published Metadata Bridge 0.57.4 ZIP was inspected byte-for-byte. It contains status and metadata routes only. It has no self-upgrade route, no arbitrary upload route, and no dormant deployment helper. WordPress core has no application-password REST operation that uploads this private fixed ZIP. A direct live correction without a bootstrap would therefore be an impossible design.

## Separately gated bootstrap boundary

v0.59.57 adds `project-atlas-upgrade-bootstrap` version 0.1.0 as a separately versioned artifact. It is not part of Metadata Bridge 0.57.5 and is not installed by Atlas. Its installation and activation require a later, separate approval and audit. Until its authenticated status route proves the exact contract, upgrade preflight fails closed and returns no handle.

Bootstrap artifact:

- ZIP: `project-atlas-upgrade-bootstrap-0.1.0.zip`
- SHA-256: `4c8b4b0c697b2b352a10f405950c7b6a750236be96aec81fcd45176ece1189bd`
- status: `GET /wp-json/project-atlas-deployment/v1/metadata-bridge/upgrade-0575/status`
- mutation: `POST /wp-json/project-atlas-deployment/v1/metadata-bridge/upgrade-0575`

Both routes require an authenticated user with `update_plugins`. Application-password authentication is supported because these are REST routes. No administrator password, cookie, wp-admin page, or nonce bypass exists.

## Fixed request and mutation

Atlas sends one multipart field named `artifact`. The endpoint, method, field name, plugin slug, entry path, current version, target version, ZIP filename, ZIP checksum, extraction root, and overwrite target are source constants. The API caller cannot select them.

The endpoint accepts only:

- active `project-atlas-metadata-bridge/project-atlas-metadata-bridge.php`;
- current version exactly 0.57.4;
- target archive exactly `project-atlas-metadata-bridge-0.57.5.zip`;
- archive SHA-256 `09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7`;
- exactly the portable two-file bridge directory;
- entry SHA-256 `64a20b6d6a03cef5430dd19fdc1e7eebfd6a3a0f8dcb201eaae5ee30250a3d5c`;
- README SHA-256 `1fe57ecff9906707ae84e6b725f44f59d6e1195d9e4bf6300cce7b1667ca71ab`;
- direct WordPress filesystem mode.

Traversal, wrapper directories, duplicates, extra files, missing files, byte drift, wrong versions, inactive or duplicate bridge installations, and caller-selected targets fail closed. The helper invokes WordPress `Plugin_Upgrader` only after complete validation and preserves the existing active-plugin option. It exposes no page, media, metadata, rendering, cache, activation, deactivation, deletion, restoration, Site Title, Tagline, URL-download, FTP, SSH, or shell operation.

After a successful transition, the endpoint becomes fail-closed because its current-version gate requires 0.57.4 and the bridge is now 0.57.5. Bootstrap removal or deactivation remains a separate guarded lifecycle and must not be bundled into the upgrade.

## Existing Atlas workflow

The Atlas routes remain:

- `POST /api/wordpress/deployment/metadata-bridge/upgrade/preflight/{page_id}`
- `POST /api/wordpress/deployment/metadata-bridge/upgrade/apply/{page_id}`
- `POST /api/wordpress/deployment/metadata-bridge/upgrade/recovery/assess/{page_id}`

Preflight remains token-free, read-only, backup/evidence/runtime bound, and zero-write. It now also verifies the exact bootstrap identity and availability. Apply still requires a short-lived one-time process-memory handle and the exact phrase `UPGRADE PROJECT ATLAS METADATA BRIDGE TO 0.57.5`. It commits one pending Atlas audit before the single fixed REST mutation and finalizes only that audit after read-only verification.

Publication alone authorizes neither bootstrap installation nor live upgrade. A future live plan must separately install and activate the bootstrap safely, verify it, create fresh backups and evidence, run a new zero-write upgrade preflight, perform the phrase-gated upgrade, and later remove or deactivate the bootstrap under its own approval.
