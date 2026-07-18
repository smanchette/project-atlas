# Project Atlas v0.59.70 cache-aware metadata rendering

## Release boundary

This release implements and tests a guarded cache-aware lifecycle. It does not access live WordPress, enable production rendering, purge the production cache, change the staged payload, update page 8 or media 31/32, or perform a production Atlas write. The currently installed Metadata Bridge 0.57.5 does not contain the required read-only preview and fixed cache-purge transports. Metadata Bridge 0.57.6 must be installed through a separately approved guarded plugin upgrade before this workflow can pass a live preflight.

## Fixed routes and phrases

Atlas exposes four POST routes locked to Atlas page 41 and WordPress page 8:

- `/api/wordpress/metadata/rendering/cache-aware/preflight/41` — zero-write rendering inspection.
- `/api/wordpress/metadata/rendering/cache-aware/apply/41` — exact phrase `ENABLE PROJECT ATLAS METADATA RENDERING`; one fixed rendering-enable request only.
- `/api/wordpress/cache/siteground/preflight/41` — zero-write origin/cache inspection and a distinct short-lived handle.
- `/api/wordpress/cache/siteground/apply/41` — exact phrase `PURGE SITEGROUND CACHE FOR PROJECT ATLAS PAGE 8`; one fixed cache operation only.

Opaque handles are random, single-use, process-memory-only, expire within ten minutes, and disappear on backend restart. The rendering handle cannot authorize a purge, and the purge handle cannot authorize rendering. Neither handle is stored in an audit or backup.

## Authoritative origin proof

Metadata Bridge 0.57.6 owns the authenticated GET route `/wp-json/project-atlas/v3/pages/8/metadata/rendering/preview`. It invokes the same `atlas_metadata_head_markup()` function used by the priority-20 public `wp_head` callback and returns only normalized metadata findings, the renderer hash, the exact canonical URL, and the plugin snapshot. It never returns or stores authenticated page HTML, cookies, credentials, or authorization headers and performs no write.

Origin verification requires one approved description, one Organization node, one Service node, no other schema type, the exact canonical URL, the exact staged payload hash, revision 1, and enabled rendering. This mechanism was selected because request `Cache-Control` headers did not prove a SiteGround bypass and because the preview directly exercises the plugin-owned public renderer without treating authenticated HTML as final public evidence.

## SiteGround cache operation

Metadata Bridge 0.57.6 owns the authenticated POST route `/wp-json/project-atlas/v3/pages/8/cache/siteground/purge`. Its request accepts no caller-controlled URL, scope, command, or cache setting. After proving the exact enabled payload at revision 1, it calls SiteGround Speed Optimizer's documented public function:

`sg_cachepress_purge_cache('https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/')`

The exact scope is `single_canonical_url`. The route fails closed if the SiteGround function is unavailable, the state differs, the function rejects the request, or the result does not report exactly one purge. It cannot mutate payload, revision, rendering, page, media, site identity, plugins, or drafts.

## Durable audit and verification

Migration `20260717_0022` adds `WordPressCacheAwareRenderingAudit`. It does not modify lifecycle audits 2, 3, or 4. Successful transitions are `pending_rendering → origin_verified → pending_cache_purge → verified`. Terminal outcomes are `verification_failed` or `failed`.

The audit records rendering authorization and its one WordPress write, normalized authoritative verification, SiteGround provider and single-URL scope, purge authorization and its one cache write, pre/post cache headers, credential-free public hashes, payload hash/revision, page/media snapshots, Atlas write count, final state, and recovery recommendation. Rendering is finalized in `WordPressMetadataState` only after authoritative and public verification both pass.

After purge, two isolated credential-free GETs must prove that the old object is no longer served through a MISS/bypass/expired signal, reset cache age, or changed cache identity. Both responses must contain exactly the approved description and Organization plus Service graph, unchanged title/canonical/H1/body/media, no media 32, and the unchanged payload/revision. A correct second cached response proves the refreshed object remains correct.

## Failure behavior

- Enablement failure before acceptance ends `failed`; no purge occurs.
- Missing or mismatched authoritative output ends `verification_failed` with `disable_rendering`; no purge occurs.
- Purge failure remains explicit and recommends `retry_cache_purge` or separately guarded disablement; no automatic recovery runs.
- Public absence, mismatch, duplicate metadata, forbidden schema, or unproven refresh ends `verification_failed` with `disable_rendering`.
- No failure path changes the payload, revision, page, media, Site Title, Tagline, plugin state, or drafts.

Reason codes include `origin_metadata_verified`, `origin_metadata_missing`, `public_cache_hit_stale`, `cache_bypass_unproven`, `cache_provider_unavailable`, `cache_purge_scope_unsupported`, `cache_purge_ready`, `cache_purge_failed`, `public_metadata_verified`, `public_metadata_still_stale`, `public_metadata_mismatch`, `unapproved_schema_node_present`, and `duplicate_metadata_present`.

## Plugin artifact

Metadata Bridge version: `0.57.6`

ZIP: `wordpress/dist/project-atlas-metadata-bridge-0.57.6.zip`

Versioned source: `wordpress/project-atlas-metadata-bridge-0.57.6/`

ZIP SHA-256: `3b2d0035f995c3006e0d3be02596bd2cf19ef7e4a97572168621beb7a9abf788`

Source and archive bytes must remain identical and portable. The published 0.57.5 source directory and guarded 0.57.4-to-0.57.5 upgrade contract remain unchanged; a later release must add and validate the separately guarded 0.57.5-to-0.57.6 upgrade workflow. Publication of Atlas v0.59.70 does not itself authorize that live upgrade or any later rendering/cache operation.
