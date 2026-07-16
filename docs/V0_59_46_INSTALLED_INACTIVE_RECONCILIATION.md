# Project Atlas v0.59.46 — Installed-Inactive Deployment Reconciliation

## Purpose and boundary

This release adds one narrow recovery path for an already-installed, inactive Metadata Bridge whose original deployment audit remains `awaiting_manual_installation`. It does not install, activate, deactivate, delete, overwrite, restore, or configure the plugin. It does not apply metadata, purge cache, update page 8, change media 31 or 32, change Site Title or Tagline, update drafts, or perform duplicate cleanup.

The workflow is limited to Atlas page 41, WordPress page 8, Metadata Bridge `0.57.4`, entry file `project-atlas-metadata-bridge/project-atlas-metadata-bridge.php`, and the locked ZIP SHA-256 `939412e6e80e8344d95274444fda65b6122fe0c8249a2ced0a8582a418c4e232`.

## Token-free verification

`POST /api/wordpress/deployment/metadata-bridge/install/reconciliation/verify/41`

The request is strict and rejects extra fields. It contains:

- deployment audit ID;
- fresh signed `project-atlas-manual-browser-evidence` schema v1;
- expected plugin slug, entry path, version, ZIP checksum, full inventory hash, and active inventory hash;
- expected page snapshot, canonical body, media 31, and media 32 hashes;
- independently expected Atlas version, commit, tag, manifest SHA-256, and source-compatibility identity.

The endpoint validates the fresh evidence before making authenticated WordPress reads. It accepts the existing signed-evidence fallback after a generic public HTTP 403, while authenticated page 8, media 31, media 32, and plugin inventory reads remain mandatory. Every WordPress request in this service passes through a GET-only transport guard.

A successful response reports `reconciliation_ready`, an opaque one-time reconciliation handle, a binding hash, expiry, the exact phrase, and the proposed Atlas-only changes. It issues no installation token or nonce, consumes no installation nonce, creates no audit, and performs zero WordPress and zero Atlas writes.

The binding covers the audit and target IDs, independently expected runtime identity, audit revision and status, original consumed authorization nonce identity, full transition-history hash, plugin and artifact identity, plugin inventories, page/body/media/cache snapshots, complete signed-evidence identity and hashes, evidence expiry, and reconciliation generation.

The handle lives only in backend process memory. Its lifetime is the earlier of ten minutes or the signed evidence expiry. A backend restart clears it.

## Atlas-only finalization

`POST /api/wordpress/deployment/metadata-bridge/install/reconciliation/apply/41`

The strict request contains only:

```json
{
  "reconciliation_handle": "<opaque process-memory handle>",
  "confirmation_phrase": "RECONCILE INSTALLED INACTIVE METADATA BRIDGE"
}
```

The phrase is exact. The handle is atomically consumed and cannot be replayed. The endpoint reruns the complete read-only verification from the fresh evidence stored with the handle and compares the new binding hash before writing Atlas state.

The only successful writes are:

1. update the existing deployment audit from `awaiting_manual_installation` to the existing terminal status `verified`; and
2. append one transition whose reason explicitly identifies installed-inactive Atlas-only reconciliation.

The original authorization nonce and original transitions are preserved. No second deployment audit is created. The audit evidence summary records `completion_mode: installed_inactive_reconciliation`, the evidence ID and hashes, handle fingerprint, prior and final status, original transition-history hash, zero WordPress writes, and the two-row Atlas write scope. Accidental activation and guarded deactivation history is not rewritten as a normal manual completion.

## Inactive-plugin inspection limitation

> **v0.59.48 correction:** WordPress core REST reports the `plugin` identity without its final `.php`. v0.59.48 normalizes that narrowly for identity matching while preserving the exact raw REST inventory for hashing. The details and fail-closed cases are recorded in `V0_59_48_INSTALLED_INACTIVE_PLUGIN_PATH_NORMALIZATION.md`.

An inactive WordPress plugin cannot expose its own REST status route. Therefore Atlas does not claim a direct inactive-plugin option, payload, revision, or private post-meta read. The inactive safety state is fail-closed corroborated from all of the following together:

- the exact plugin is inactive;
- Atlas metadata state and audit row counts are both zero;
- page, body, and media snapshots remain exact;
- fresh signed public evidence proves no Atlas marker, meta description, Open Graph, Twitter, JSON-LD, or media 32 reference;
- active-plugin inventory remains at the pre-install baseline;
- the cache observation remains unchanged, and reconciliation has no cache-purge transport.

If any corroborating gate fails, reconciliation is blocked. Direct installed plugin bytes are likewise not exposed by WordPress REST while inactive; Atlas verifies the locked local ZIP byte-for-byte against source and requires the installed entry path and declared version to match the authorized audit. The report must describe this accurately and must not claim a direct remote file checksum.

## Publication is not live authorization

Publishing v0.59.46 does not authorize live evidence capture or either reconciliation endpoint. It does not authorize plugin installation, activation, deactivation, removal, metadata application, cache purge, restoration, or page/media changes. A later phase must generate a fresh ignored runtime manifest for the published commit and tag before any separately approved live reconciliation.
