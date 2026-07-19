# Project Atlas v0.59.78 — Volatile Public-Observation Binding

## Defect and scope

Cache-aware rendering preflight bound the complete public HTTP observation, including its capture timestamp. Apply correctly reran the public observation, but the later timestamp necessarily changed the binding hash and caused HTTP 409 before the rendering write. The separate cache-purge handle had the same structural risk. This release changes backend binding only. Metadata Bridge PHP, payload, revision, page, media, and cache behavior are unchanged.

## Stable fingerprint

The deterministic stable observation fingerprint contains only invariant safety facts:

* the locked canonical request URL, exact final URL, and redirect count;
* exact HTTP status and normalized response classification;
* HTML/non-HTML content-type class;
* SiteGround provider verification, reason classifications, and sanitized provider headers;
* challenge, error, admin, login, and authenticated-context classifications;
* the response body hash and normalized rendered/metadata hashes for HTTP 200 observations;
* signed evidence ID, rendered-head hash, visible-content hash, metadata-inventory hash, and page-identity hash when browser evidence is part of the phase.

Provider header names are normalized to lowercase. Status values are normalized by contract. `x-proxy-cache-info` retains its provider marker while normalizing the naturally changing `DT:<number>` value. The fingerprint excludes `Age`, `Date`, `Expires`, `Last-Modified`, request IDs, generated timestamps, observation timestamps, and elapsed duration. The public-header sanitizer never admits credentials, cookies, authorization headers, or arbitrary response headers.

Raw sanitized observations are retained in the preflight diagnostics. They are not byte-for-byte authorization inputs.

## Temporal contract

Rendering preflight requires its provider observation to occur no earlier than signed-evidence capture and no later than evidence expiry or the SiteGround backup deadline. Cache preflight requires its observation before the backup deadline. Each one-time process-memory handle binds:

* the original preflight observation timestamp;
* a maximum preflight-to-apply interval of two minutes;
* a one-second clock-reversal tolerance;
* evidence expiry for rendering;
* handle expiry;
* SiteGround backup deadline.

Apply must observe at or after preflight within the tolerance, remain inside the bounded interval, and remain before every applicable expiry. The caller cannot supply an observation timestamp or stable fingerprint.

## Apply drift behavior

Both apply routes atomically consume their handle and rerun their complete preflight. A later timestamp or changed cache `Age` is recorded as the passed diagnostic `volatile_timestamp_change_allowed` or `volatile_cache_age_change_allowed`. Meaningful drift remains blocked with an explicit category:

* `stable_public_observation_mismatch`
* `public_observation_expired`
* `apply_observation_before_preflight`
* `observation_window_exceeded`
* `cache_provider_drift`
* `public_url_drift`
* `public_identity_drift`

Disappearing or invalid provider evidence, redirect or URL changes, HTTP/challenge classification changes, rendered or metadata inventory drift, page/media drift, runtime drift, plugin/payload/revision drift, audit drift, or backup drift cannot be masked by volatile transport changes.

## Write and final-verification guarantees

Preflights remain zero-write. Rendering apply remains separately phrase-gated and can call only the existing fixed rendering-enable operation once. Cache apply remains separately phrase-gated and can call only the existing single-canonical-URL SiteGround purge operation once. No new WordPress, cache, metadata, page, media, plugin, or Atlas write path is introduced.

The pre-enable provider-bound HTTP 403 policy is unchanged: its body is never public-page evidence. Post-purge verification is not relaxed and still requires two credential-free HTTP 200 responses containing the exact approved public metadata and unchanged page/media state.
