# Project Atlas v0.59.76 — Browser-Verified HTTP 403 Provider Binding

## Scope

This backend-only correction changes the pre-enable cache-aware rendering proof policy. It does not change Metadata Bridge PHP, enable rendering, purge cache, create a production audit, or authorize a production operation.

## Separated proof responsibilities

Fresh signed schema-v1 browser evidence remains authoritative for the public DOM and head output: metadata inventory, title, canonical, H1, visible content, featured image, media-32 absence, navigation success, privacy findings, and rendered hashes. Atlas validates its signature, freshness, exact canonical URL, successful HTTP 200 browser navigation, zero redirects, and absence of login, admin, authenticated, challenge, error, cookie, credential, authorization-header, or secret state.

The separate credential-free direct HTTP observation is transport evidence only. It contributes the final URL, redirect count, HTTP status, observation time, content type, response-body SHA-256, challenge/error classification, and allowlisted sanitized cache/security headers. Its body is never rendered-page evidence when the response is HTTP 403. Direct-response DOM fields and hashes are not used to override or replace the signed browser evidence.

## Supported HTTP 403 provider observation

Pre-enable provider binding may accept HTTP 403 only when all of these conditions hold:

- the signed browser evidence is valid, fresh, credential-free, and bound to the exact Orlando canonical URL;
- browser navigation succeeded with HTTP 200 HTML, zero redirects, and no login, admin, authenticated, challenge, or error context;
- the direct observation uses source `public`, has the exact same canonical final URL, has zero redirects, and falls within the browser-evidence lifetime;
- the direct response retains only sanitized headers and a lowercase 64-character response-body SHA-256;
- the direct response is not HTTP 202 and is not classified as a challenge, bot-protection, login, admin, authenticated, or error page;
- recognized SiteGround provider evidence is present: `x-proxy-cache-info: DT:<number>`, `x-cache-enabled: true`, or a recognized `x-proxy-cache` status. `server: nginx` remains supporting evidence only.

Empty headers, nginx alone, malformed values, caller-supplied cache headers, redirects, URL mismatch, timing mismatch, HTTP 202, and challenge/error classifications fail closed.

## Pre-enable stale-state proof

The old policy required the direct request itself to return HTTP 200 with `X-Proxy-Cache: HIT` and a body matching the browser capture. That was not usable when SiteGround returned provider-identifying HTTP 403 to the backend while an isolated browser loaded the exact public page successfully.

The corrected policy proves the pre-enable state from independent facts:

- signed browser evidence proves the public metadata is absent and page identity is exact;
- the staged payload, payload hash, revision 1, and disabled rendering state remain exact;
- the Atlas metadata state remains staged;
- the direct observation independently proves the SiteGround provider and is safely bound by URL, redirects, time, status, body hash, and sanitized headers.

The policy does not claim a literal cache HIT when none was observed.

## Diagnostics

The pre-enable diagnostic contract includes:

- `direct_cache_hit_verified`
- `direct_cache_miss_verified`
- `provider_verified_status_blocked`
- `browser_public_state_verified`
- `browser_public_state_verified_cache_provider_bound`
- `public_observation_mismatch`
- `challenge_response_rejected`

Existing provider-header diagnostics remain available for missing, malformed, unrecognized, HIT, MISS, and BYPASS observations.

## Final-verification boundary

The correction is limited to rendering preflight. Rendering apply and cache apply remain separately protected by short-lived one-time handles and exact phrases. Origin preview verification is unchanged. Post-purge verification still requires HTTP 200 at the exact canonical URL with the exact approved meta description, ordered Organization and Service JSON-LD nodes, canonical, H1, media-32 absence, refreshed cache identity, a matching second public response, unchanged payload/revision/page/media state, and exactly one fixed cache operation. HTTP 202, HTTP 403, redirects, missing metadata, duplicate metadata, forbidden schema, and content mismatch remain failures.

## Artifact boundary

Metadata Bridge remains version 0.57.6. Its PHP source and release ZIP are unchanged. The locked ZIP SHA-256 remains `3b2d0035f995c3006e0d3be02596bd2cf19ef7e4a97572168621beb7a9abf788`.
