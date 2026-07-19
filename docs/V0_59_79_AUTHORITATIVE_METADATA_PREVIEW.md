# Project Atlas v0.59.79 — Authoritative Metadata Preview

This release corrects the Metadata Bridge REST preview locally and prepares a separately guarded 0.57.6-to-0.57.7 upgrade. Publication does not authorize a live bootstrap installation, plugin upgrade, rendering change, metadata change, cache purge, page/media change, or recovery action.

## Root cause and renderer contract

Metadata Bridge 0.57.6 used `atlas_metadata_head_markup()` for both the public `wp_head` hook and the authenticated preview. That function began with `is_page(8)`. WordPress REST requests do not establish the normal page-8 main query, so the authoritative preview could receive an empty renderer result and return `atlas_rendering_preview_unavailable` HTTP 409 even when the exact enabled payload was valid.

Metadata Bridge 0.57.7 separates three responsibilities:

1. `atlas_metadata_head_markup_from_snapshot()` is a pure deterministic serializer. It accepts an already-read plugin snapshot, validates the exact payload and hash, and returns the description and JSON-LD markup without consulting query context or performing a write.
2. `atlas_metadata_public_request_is_page_8()` is the strict public guard. It permits only the frontend WordPress page 8 and rejects admin, REST, AJAX, cron, CLI, feeds, search, archives, editor previews, and unrelated pages.
3. `atlas_metadata_head_markup()` is the public wrapper. The `wp_head` hook calls it at priority 20. The authenticated preview validates the exact published post identity and calls the pure serializer directly, so REST preview correctness no longer depends on `is_page()`.

The preview remains read-only. Disabled rendering, missing or malformed payload, invalid payload hash, wrong post identity, or any other real state inconsistency remains an explicit HTTP 409. The route never returns credentials, cookies, authorization headers, authenticated HTML, or secret-bearing state.

## Immutable artifacts

Metadata Bridge version: `0.57.7`

ZIP: `wordpress/dist/project-atlas-metadata-bridge-0.57.7.zip`

ZIP SHA-256: `ada4d97ea627a148d07fda809c1776a91a87d7a7e4957de3bece423a9bb80a62`

Upgrade bootstrap version: `0.3.0`

Upgrade bootstrap ZIP SHA-256: `de5bfb7875b6f84f2009ef2043c1c86c7f9d20f0f973a5cb16b478fe37e83bef`

Both archives have deterministic timestamps, POSIX paths, one top-level directory, no duplicate/traversal entries, and byte-equal source contents.

## Separately guarded future upgrade

The new immutable upgrade profile supports exactly active Metadata Bridge 0.57.6 to active 0.57.7 with phrase `UPGRADE PROJECT ATLAS METADATA BRIDGE TO 0.57.7`. Its token-free preflight binds the final published runtime identity; exact current and target artifacts; fresh signed schema-v1 evidence; validated Atlas and SiteGround backups; verified installation, activation, prior-upgrade, bootstrap-cleanup, staging, and recovery-disable audits; exact plugin inventories; staged payload hash `fe24398ee322ca8557814feb034a0ccff0302d5d26b6ea47b11001567854711d`; revision 1; disabled rendering; page 8, media 31/32, site identity, and zero cache purges.

Apply requires a short-lived one-time process-memory handle and the exact phrase. It can send only one multipart POST to bootstrap 0.3.0 with the fixed 0.57.7 ZIP. The bootstrap accepts no caller-selected URL, path, version, target, activation choice, or archive. It preserves active status, the staged payload, revision 1, disabled rendering, unrelated plugins, page/media state, Site Title, Tagline, and cache state. Post-upgrade checks are read-only. Bootstrap 0.3.0 deactivation and deletion remain separately phrase-gated cleanup phases.

Historical 0.57.4-to-0.57.5 and 0.57.5-to-0.57.6 profiles and artifacts remain immutable. No profile can authorize an arbitrary version transition.

## Recovery boundary

No automatic downgrade, deactivation, cache purge, restoration, or retry occurs after uncertain success. The read-only recovery assessment reports `no_action`, `guarded_downgrade`, or `siteground_restore` from observed state. Any live upgrade, cleanup, rendering enablement, or cache purge requires a later explicit phase with fresh, unexpired backup evidence and runtime identity.
