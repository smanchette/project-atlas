# Project Atlas v0.59.81 — Audited Manual Bootstrap Handoff

v0.59.81 adds a dedicated lifecycle for establishing the locked `project-atlas-upgrade-bootstrap` 0.3.0 plugin without adding an arbitrary plugin uploader, WordPress Admin automation, or caller-selected activation target.

## Fixed identity and phrases

- ZIP: `project-atlas-upgrade-bootstrap-0.3.0.zip`
- ZIP SHA-256: `de5bfb7875b6f84f2009ef2043c1c86c7f9d20f0f973a5cb16b478fe37e83bef`
- Entry: `project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap.php`
- Entry SHA-256: `a977c077573ab732213a06d17dcc317b09854564777ce9cb24c869383972cd53`
- Manual handoff phrase: `AUTHORIZE MANUAL UPLOAD OF PROJECT ATLAS UPGRADE BOOTSTRAP 0.3.0`
- Activation phrase: `ACTIVATE PROJECT ATLAS UPGRADE BOOTSTRAP 0.3.0`

The API accepts no caller-supplied plugin slug, path, URL, version, checksum, filesystem location, or activation target. Handles are random, process-memory only, ten-minute maximum lifetime, and single-use. A backend restart invalidates every handle.

## State machine

The zero-write manual-install preflight binds release/runtime identity, credentials, backups and deadline, audit history, bridge 0.57.6 identity, staged payload/revision, complete plugin inventory, page 8, media 31/32, Site Title/Tagline, rendered state, and cache observations. Exact phrase authorization creates only an `awaiting_manual_bootstrap_installation` audit. Shawn then uses WordPress Admin's supported upload screen and must not activate the plugin.

Read-only upload verification distinguishes no upload, exact inactive upload, manual activation, wrong version/path/entry, duplicate, partial/conflicting installation, unrelated plugin drift, and protected-state drift. Exact inactive verification transitions to `manual_installation_inventory_verified` and permits a separate activation preflight and handle.

As of v0.59.83, that successful verification is monotonic. A current retry bound to the same sanitized proof returns an idempotent zero-write success; a stale, expired, drifted, or conflicting retry returns a zero-write HTTP 409 and cannot downgrade the audit or erase activation eligibility. The decision is serialized by the backend process lock plus a database `SELECT ... FOR UPDATE`. Pre-success failure transitions remain unchanged.

Activation changes only the fixed WordPress plugin status to `active` using a request whose JSON keys are exactly `status`. Before that write the audit transitions to `activation_pending_checksum_verification`.

## Approved residual risk and quarantine

WordPress core exposes an inactive plugin's entry/path/version/status but does not expose its PHP executable checksum. The approved Option 1 exception therefore permits one narrowly scoped code execution after exact inactive entry, directory, version, singleton inventory, and protected-state verification.

The active bootstrap is quarantined immediately. No bootstrap mutation, bridge upgrade, metadata/rendering action, cache action, cleanup, or other mutation is permitted. Atlas calls only the fixed authenticated read-only bootstrap status route and requires its source identity plus the exact executable SHA-256 above.

An exact match transitions the establishment audit to `verified`; only then may the later 0.57.6-to-0.57.7 bridge-upgrade gate become eligible. A missing, malformed, unavailable, or mismatched checksum records the specific intermediate result and then `recovery_required`. Atlas does not retry activation, deactivate, delete, overwrite, restore, or otherwise recover automatically.

## Dedicated routes

- `POST /api/wordpress/deployment/upgrade-bootstrap/manual-install/preflight/{page_id}`
- `POST /api/wordpress/deployment/upgrade-bootstrap/manual-install/authorize/{page_id}`
- `POST /api/wordpress/deployment/upgrade-bootstrap/manual-install/verify/{page_id}`
- `POST /api/wordpress/deployment/upgrade-bootstrap/activation/preflight/{page_id}`
- `POST /api/wordpress/deployment/upgrade-bootstrap/activation/apply/{page_id}`
- `POST /api/wordpress/deployment/upgrade-bootstrap/recovery/assess/{page_id}`

The recovery route is read-only and returns one recommendation: `no_action`, `proceed_to_bridge_upgrade`, `guarded_bootstrap_recovery`, `guarded_bootstrap_cleanup`, `retry_from_fresh_backup`, or `siteground_restore`.

Publication does not authorize a live manual upload, activation, bridge upgrade, metadata operation, cache purge, cleanup, restoration, page/media/settings change, or any other production action.
