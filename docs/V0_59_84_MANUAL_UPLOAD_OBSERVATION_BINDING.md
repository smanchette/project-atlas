# Project Atlas v0.59.84 — Manual-Upload Observation Binding

## Defect and scope

The v0.59.83 manual-upload preflight and authorization each acquired a fresh rendered-page observation. The complete protected binding included `public_http_observation.observed_at`, so an otherwise identical authorization rerun produced a different hash and failed with HTTP 409. No audit or production write occurred.

v0.59.84 changes only the audited bootstrap-establishment handoffs that compare a preflight observation with a later live rerun:

- manual-install preflight to authorization; and
- fixed-entry activation preflight to activation apply.

Manual-install verification continues to use its monotonic durable proof. Post-activation checksum verification and read-only recovery assessment do not compare two acquisition timestamps and therefore require no temporal handoff change.

## Stable and volatile fields

The stable fingerprint includes, when supplied by the applicable contract:

- fixed requested URL, normalized final URL, redirect count, HTTP status, response classification, and normalized content-type class;
- deterministic rendered-head, visible-content, response-body, metadata-inventory, and raw-DOM hashes;
- document title, ordered H1 inventory, canonical inventory, featured-image URL and alt text;
- signed evidence ID, schema/version, helper version, acquisition source, navigation outcome, complete page identity and its hash, signature identity, absence findings, and privacy attestations;
- cookie-free, credential-free, authentication, admin, login, challenge, error, Atlas-marker, and media-32 classifications; and
- normalized SiteGround provider/cache identity and stable allowlisted provider headers.

The following remain in raw sanitized diagnostic snapshots but are excluded from equality:

- observation, capture-start, capture-completion, generated-at, and transport timestamps;
- elapsed durations;
- HTTP `Date`, cache `Age`, `Expires`, and `Last-Modified` values; and
- ephemeral request or correlation identifiers not included in the signed identity contract.

Callers cannot provide or override either the stable fingerprint or its temporal fields. Request models remain `extra="forbid"`.

## Temporal contract

The process-memory handle binds the original preflight observation time, signed-evidence expiry, handle expiry, SiteGround backup deadline, two-minute maximum rerun interval, and one-second clock-reversal tolerance. All timestamps must be timezone-aware.

Authorization may use a later observation only when it is no earlier than preflight beyond tolerance, no more than two minutes later, and both observation and authorization remain before evidence, handle, and backup expiry. Future-dated observations, clock reversal beyond tolerance, expired bounds, missing timestamps, or altered bound constants fail closed.

## Drift policy and reason codes

Authorization reruns every existing runtime, repository, backup, artifact, plugin, payload/revision/rendering, audit, page, media, settings, evidence, and pending-operation gate. Stable changes are rejected before creating an audit. Permitted volatile movement adds the successful diagnostic gate `manual_upload_volatile_timestamp_change_allowed`.

Manual-upload binding failures use deterministic non-secret codes:

- `manual_upload_stable_observation_mismatch`
- `manual_upload_observation_expired`
- `manual_upload_observation_before_preflight`
- `manual_upload_observation_window_exceeded`
- `manual_upload_public_identity_drift`
- `manual_upload_rendered_hash_drift`
- `manual_upload_runtime_drift`
- `manual_upload_backup_drift`

Activation uses the corresponding `bootstrap_activation_*` codes. Raw handles, credentials, cookies, authorization headers, and sensitive response headers are never included.

## Handle and write guarantees

The opaque handle and bound raw token state remain process-memory only, short-lived, single-use, and restart-invalidated. Successful manual authorization creates exactly one `awaiting_manual_bootstrap_installation` audit and performs one Atlas audit write, zero WordPress writes, and zero cache writes. Any stable or temporal mismatch consumes the handle, creates no audit, and performs no write. Activation remains a separate fixed-entry, phrase-gated operation.

The v0.59.78 stable-versus-volatile public-observation normalizer and temporal validator are reused so cache-aware and bootstrap-establishment handoffs share the same URL, provider-header, elapsed-window, and clock-tolerance semantics.
