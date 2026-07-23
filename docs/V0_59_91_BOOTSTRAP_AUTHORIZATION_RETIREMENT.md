# Project Atlas v0.59.91 — Bootstrap authorization retirement

v0.59.91 separates two lifecycle facts that must never be conflated: retiring an unusable authorization and authorizing an already-installed inactive Bootstrap. Retirement preserves the old record; it does not verify it, delete it, or change WordPress.

## Genuine transport-drift retirement

The retirement preflight is:

`POST /api/wordpress/deployment/upgrade-bootstrap/authorization/retirement/preflight/{page_id}`

It is limited to Atlas page 41, WordPress page 8, and an `awaiting_manual_bootstrap_installation` audit with no verification evidence, activation handle, checksum result, quarantine, or pending operation. It requires the exact inactive Bootstrap 0.3.0 and independently observes the current public and authenticated GET-only state. No new browser evidence or backup is accepted by this endpoint.

The only supported reason is:

`manual_install_verification_genuine_transport_drift`

The historical authorization must prove a SiteGround/nginx HTTP 403 provider block with unavailable cache state. The current observation must prove the same public page identity over SiteGround/nginx HTTP 200 cached public HTML with cache state `HIT`. Matching transport, representation-only differences, transient failures, redirects, challenges, or page-identity changes fail closed.

The apply endpoint is:

`POST /api/wordpress/deployment/upgrade-bootstrap/authorization/retirement/apply/{page_id}`

For Audit 1 its exact phrase is:

`RETIRE PROJECT ATLAS BOOTSTRAP AUTHORIZATION FOR AUDIT 1 DUE TO GENUINE TRANSPORT DRIFT`

Apply consumes a short-lived process-memory handle and performs one Atlas audit update. It appends `authorization_retired`, records the supported reason, and preserves the authorization snapshot, both renewal records, evidence absence, write counts, and previous history. It performs zero WordPress, plugin, cache, page, media, payload, or settings writes. A retired authorization cannot be renewed, verified, activated, or reopened by an ordinary API.

## Existing exact inactive Bootstrap authorization

After retirement and fresh Atlas and SiteGround backups, the operator may use:

- `POST /api/wordpress/deployment/upgrade-bootstrap/installed-inactive/preflight/{page_id}`
- `POST /api/wordpress/deployment/upgrade-bootstrap/installed-inactive/authorize/{page_id}`

This path requires one exact inactive `project-atlas-upgrade-bootstrap` 0.3.0 installation, current HTTP 200 SiteGround cached-public transport, fresh schema-v1 evidence, fresh backup identities, and no unresolved establishment audit. It rejects reused evidence or backup identities. Its phrase is:

`AUTHORIZE PROJECT ATLAS EXISTING EXACT INACTIVE BOOTSTRAP 0.3.0`

It creates a distinct audit with authorization mode `existing_exact_inactive_bootstrap`. It does not upload, reinstall, replace, delete, activate, or otherwise mutate the plugin.

## Operator sequence

1. Retire the stale Audit 1 authorization.
2. Confirm Audit 1 is terminal and no longer unresolved.
3. Create fresh Atlas Data, Media, and Program backups.
4. Create a fresh SiteGround on-demand full-site backup.
5. Re-enter WordPress Sandbox credentials if backend recreation cleared them.
6. Capture fresh schema-v1 credential-free browser evidence.
7. Run the existing exact inactive Bootstrap preflight and authorization.
8. Verify the exact inactive inventory under the new audit.
9. Stop at `manual_installation_inventory_verified` before any activation.

Data Backup schema 0.39 preserves the authorization mode and retirement reason. Existing 0.38 backups remain accepted; restoring an old record supplies the historical `manual_upload` mode and no retirement reason. Migration 0025 refuses downgrade while retired rows exist.
