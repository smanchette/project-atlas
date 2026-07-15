# Project Atlas v0.59.22 guarded Orlando heading correction

This local implementation defines a single-purpose workflow for Atlas page 41 and WordPress page 8. It does not authorize or perform the live correction.

## Locked change

The only permitted WordPress payload field is `content`. The complete body may differ only at its opening tag:

```html
<h1>Drywood Termite Tenting in Orlando, Florida</h1>
```

becomes:

```html
<h2>Drywood Termite Tenting in Orlando, Florida</h2>
```

The current canonical body SHA-256 is `1144c89c046bfd74d3381560afdc5b7ec81f9a01e6de73fa929f2dc3b7ef7705`. The proposed canonical body SHA-256 is `c031a7aa841b8e9a0316956dd3bf25178f390e64d01ceb9d9cd4273cc4aed195`.

## Endpoints and stopping points

1. `POST /api/wordpress/heading-correction/dry-run/41` performs authenticated page/media GETs and a credential-free public-page GET. It requires fresh Atlas Data, Media, and Program backup identities and verified runtime release identity. Only a fully passing inspection creates a short-lived signed token and returns an opaque one-time handle plus `CORRECT ORLANDO DUPLICATE H1`. The raw token exists only in backend process memory: it is never returned, logged, serialized, audited, backed up, or persisted.
2. `POST /api/wordpress/heading-correction/apply/41` accepts only that opaque handle, the same backups, and the exact phrase. It atomically consumes the handle, retrieves and clears the raw token in backend memory, reruns every gate, commits a dedicated pending audit, and sends one request whose JSON object has exactly one key: `content`. The token fingerprint prevents replay without exposing the token. An unknown, expired, already-consumed, mismatched, or restart-cleared handle fails closed; there is no operator-supplied raw-token fallback.
3. `POST /api/wordpress/heading-correction/verify/41` is read-only. It verifies the locked H2 body, the single theme-owned H1, protected page fields, both media snapshots, canonical URL, metadata absence, and the absence of any cache-purge operation in this workflow.
4. `POST /api/wordpress/heading-correction/reconcile/41` is Atlas-only. It is available only for a `reconciliation_required` audit, reruns the complete read-only verification, requires `FINALIZE ORLANDO H1 CORRECTION AUDIT`, and never resends the WordPress write.

Any network uncertainty or failure after WordPress may have accepted the request produces a hard reconciliation stop. No automatic retry exists.

The frontend retains only the opaque handle in component memory. It never uses `localStorage` or other persistent browser storage for the handle, and it never receives the raw token. A page reload or backend restart therefore requires a new dry run.

## Explicit exclusions

The workflow cannot change title, slug, URL, status, excerpt, canonical, template, parent, menu order, featured media, metadata, or media. It does not edit themes, use CSS, install or activate the Metadata Bridge, apply metadata, purge cache, restore backups, perform duplicate cleanup, or update another Atlas page.

Migration `20260714_0016` adds the dedicated heading-correction audit. Data Backup v0.32 includes that audit and continues to accept earlier supported backup versions with an empty correction-audit group.

Publication, a successful dry run, and read-only verification do not themselves authorize a live correction.
