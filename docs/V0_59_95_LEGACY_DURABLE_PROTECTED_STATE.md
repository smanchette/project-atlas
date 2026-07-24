# Project Atlas v0.59.95 — Legacy Durable Protected-State Compatibility

## Scope

Audit ID 2 was created under the v0.59.92 protected-state shape. That shape
included a sanitized top-level `cache_headers` object even though SiteGround
cache transport is volatile. Current protected snapshots intentionally omit
that field.

v0.59.95 normalizes only this recognized historical top-level key when an
already-stored protected-state record is compared with a current observation.
The stored audit and backup data are not rewritten.

## Fail-closed contract

The compatibility rule excludes exactly:

- the previously established `rendered` field; and
- the legacy top-level `cache_headers` field, only for an already-stored
  protected-state object.

Current snapshot construction is unchanged. Unknown keys, misspellings such as
`cache_header`, arbitrary transport fields, and nested unexpected keys remain
comparison-visible and fail closed. Page, body, media, Site Title, Tagline,
payload, revision, rendering, purge-count, plugin-inventory, Bootstrap, and
Metadata Bridge drift remain blocked.

## Operational boundary

Publication and runtime loading do not reconcile Audit ID 2. After v0.59.95 is
loaded, a new Atlas Data backup must be created after the runtime generation
time. WordPress Sandbox credentials must be re-entered if backend recreation
clears them. Reconciliation remains a separately approved, fresh-evidence,
one-time-handle operation with zero WordPress, plugin, and cache writes.
