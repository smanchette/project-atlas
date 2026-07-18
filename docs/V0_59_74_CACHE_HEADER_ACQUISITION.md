# Project Atlas v0.59.74 — Cache-Aware Identity and Header Acquisition

## Scope

This release corrects two backend-only preflight defects. It does not change Metadata Bridge PHP, enable rendering, purge cache, or authorize a production operation.

## Plugin identity

Cache-aware matching reuses `_normalize_plugin_identifier()` from the guarded deployment workflow. Raw WordPress REST plugin records remain unchanged for deterministic inventory hashing. Normalization is used only for identity matching and accepts exactly the locked entry path or WordPress's extensionless form. Windows separators are normalized to POSIX for matching. Absolute paths, traversal, null bytes, empty segments, malformed characters, duplicates, ambiguous matches, version drift, and inactive state fail closed. Exactly one active Metadata Bridge 0.57.6 match is required.

## Credential-free public HTTP observation

Signed schema-v1 browser evidence remains authoritative for the Orlando DOM, metadata inventory, title, H1, canonical, image, visible content, and privacy findings. When signed evidence is supplied, Atlas performs one separate credential-free direct GET to the exact canonical URL and retains only a bounded observation:

- HTTP status, final URL, redirect count, and content type;
- response-body SHA-256, normalized rendered-head hash, and visible-content hash;
- normalized public page identity;
- allowlisted cache headers.

The direct observation must return HTTP 200 HTML with zero redirects, the exact canonical URL, and hashes and identity matching the signed browser evidence. HTTP 202 SG-Captcha, HTTP 403, challenge/login/admin/error HTML, redirects, and identity or hash mismatches fail closed.

## Header privacy boundary

Header names are case-insensitive and normalized to lowercase. Repeated allowlisted values are combined in encounter order. The allowlist is:

- `age`
- `cache-control`
- `cf-cache-status`
- `etag`
- `expires`
- `last-modified`
- `server`
- `via`
- `x-cache`
- `x-cache-enabled`
- `x-proxy-cache`
- `x-proxy-cache-info`
- `x-sg-cache`

`authorization`, `cookie`, `set-cookie`, tokens, session identifiers, and all unrelated headers are excluded. Header observations are read-only, are not caller supplied, and are deterministically bound into the one-time rendering handle.

## SiteGround detection

Provider verification requires at least one recognized cache signal: `x-cache-enabled: true`, `x-proxy-cache: hit|miss|bypass`, or a recognized `x-proxy-cache-info` `DT:<number>` value. `server: nginx` is supporting evidence only and cannot establish the provider by itself. Empty, malformed, or unrecognized evidence fails closed.

The diagnostic reason-code contract includes:

- `siteground_cache_provider_verified`
- `cache_headers_missing`
- `cache_provider_unrecognized`
- `cache_header_value_invalid`
- `cache_status_hit`
- `cache_status_miss`
- `cache_status_bypass`
- `stale_public_cache_confirmed`

The rendering preflight requires a bound SiteGround cache HIT serving the signed pre-enable metadata-absent page. A MISS or BYPASS can identify the provider but cannot prove the required stale public cache state.

## Mutation boundary

Preflight remains zero-write and creates no audit. Rendering enablement and the fixed Orlando-only SiteGround purge remain separate routes with separate short-lived one-time handles and exact confirmation phrases. No page, media, payload, revision, plugin, Site Title, Tagline, or cache mutation is introduced by this correction.
