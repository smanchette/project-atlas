# Project Atlas v0.59.54 separated metadata lifecycle

This release implements local architecture only. It does not authorize upgrading the live bridge, staging production metadata, enabling rendering, disabling rendering, rolling back a payload, purging cache, or changing page 8 or media 31/32. The live bridge remains 0.57.4 until a separately approved upgrade phase installs Metadata Bridge 0.57.5.

## Approved payload

Canonical payload serialization is UTF-8 JSON with sorted object keys and compact separators. The payload has only the fixed schema/page identity, the approved meta description, and JSON-LD containing exactly two ordered nodes: `Organization` and `Service`. The Organization contains the approved name, phone, email, and license identifier. The Service contains `Drywood termite tenting`, `Orlando, Florida`, and an `@id` reference to that Organization. `LocalBusiness`, `WebSite`, `WebPage`, `Person`, `ImageObject`, and every other schema node are rejected. No Open Graph, Twitter, canonical-write, image, media ID, excluded-media ID, or media 32 field exists in the payload.

## Routes and phrases

All Atlas routes use `POST`; all preflights are token-free and write-free. Successful preflights return a short-lived opaque handle plus its SHA-256 fingerprint. The handle maps to immutable proof held only in backend process memory, is single-use, expires after at most ten minutes, and is invalidated by backend restart. No signed authorization token, nonce, or raw credential is returned or persisted.

| Operation | Preflight | Apply | Exact phrase |
|---|---|---|---|
| Stage payload | `/api/wordpress/metadata/staging/preflight/41` | `/api/wordpress/metadata/staging/apply/41` | `STAGE PROJECT ATLAS METADATA PAYLOAD` |
| Enable rendering | `/api/wordpress/metadata/rendering/preflight/41` | `/api/wordpress/metadata/rendering/apply/41` | `ENABLE PROJECT ATLAS METADATA RENDERING` |
| Disable rendering | `/api/wordpress/metadata/rendering/disable/preflight/41` | `/api/wordpress/metadata/rendering/disable/apply/41` | `DISABLE PROJECT ATLAS METADATA RENDERING` |
| Roll back payload | `/api/wordpress/metadata/staging/rollback/preflight/41` | `/api/wordpress/metadata/staging/rollback/apply/41` | `ROLL BACK PROJECT ATLAS METADATA PAYLOAD` |

The apply request shape is always exactly:

```json
{"lifecycle_handle":"<opaque process-memory handle>","confirmation_phrase":"<exact operation phrase>"}
```

The preflight request extends the activation proof with activation audit ID 1 and the exact candidate payload. It binds the signed schema-v1 evidence, four-hour SiteGround backup, three Atlas backup identities, runtime and repository identity, plugin/inventory identity, page/body/media snapshots, candidate payload hash, prior lifecycle audits, cache observation, action, and expiry.

## WordPress contract

Metadata Bridge 0.57.5 exposes four fixed plugin-owned `PUT` operations:

- staging writes only payload, payload hash, and revision `0 → 1`, while forcing the per-page rendering marker absent;
- enablement writes only the per-page rendering marker and the plugin-owned safety authorization; it accepts no payload and preserves revision `1`;
- disablement removes only the rendering marker and disables the safety authorization; it preserves payload, hash, and revision `1`;
- rollback refuses to run while rendering is enabled, then removes payload, hash, and revision so the snapshot returns to null, empty hash, and revision `0`.

Each apply makes exactly one WordPress REST mutation request. No route can write page content, title, H1, slug, URL, status, excerpt, canonical, template, featured media, media records, Site Title, Tagline, plugin installation/activation state, or cache. Verification performs GET/read requests only. The legacy v1 combined metadata apply endpoint now returns HTTP 410 and cannot be reached by the new workflow.

## Audits and state

Migration `20260716_0018` adds `WordPressMetadataLifecycleAudit`. Its four distinct `action_type` values are `stage_metadata_payload`, `enable_metadata_rendering`, `disable_metadata_rendering`, and `rollback_metadata_payload`. Each record stores prior/final state, evidence ID and hashes, backup and runtime identity, handle fingerprint, phrase hash, payload hash and revisions, rendering state, page/media snapshots, gates, write counts/scopes, result, and transition history. Apply commits a pending audit before WordPress access and finalizes only that audit and the single page-41 metadata state after read-only verification. Data Backup v0.34 exports and restores these records while retaining compatibility with older backups.

## Required deployment order

Publication of v0.59.54 does not authorize a live action. A later plan must separately upgrade the installed bridge from 0.57.4 to 0.57.5 and reconcile that upgrade before any lifecycle preflight can pass. Every live operation then requires fresh Atlas backups, a SiteGround on-demand full-site backup no more than four hours old, fresh signed schema-v1 evidence, credentials entered only through `/wordpress-sandbox`, a successful zero-write preflight, and its own exact phrase. Cache purge remains a hard stop and a separate future approval.
