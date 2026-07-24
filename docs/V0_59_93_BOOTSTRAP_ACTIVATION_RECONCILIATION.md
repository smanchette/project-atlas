# Project Atlas v0.59.93 — Bootstrap activation reconciliation

v0.59.92 correctly performed the one authorized WordPress mutation that changed
the exact Upgrade Bootstrap 0.3.0 from inactive to active. Its post-mutation
verifier nevertheless failed because it retained a generic pre-activation
active-inventory gate and treated volatile SiteGround cache telemetry as both
durable WordPress state and stable page identity.

v0.59.93 makes the post-activation contract lifecycle-aware. The expected full
and active inventories are derived from the verified inactive upload snapshot
by changing only the fixed Bootstrap entry from `inactive` to ordinary
`active`. A network-active, duplicated, alternate-path, wrong-version, or
wrong-checksum Bootstrap remains invalid. No unrelated plugin delta is allowed.

Durable protected state contains the page, canonical body, media, Site Title,
Tagline, payload, revision, rendering setting, and cache-purge count. Cache
headers and provider diagnostics are not durable state. During post-mutation
verification only, `HIT`, `MISS`, `EXPIRED`, and `BYPASS` may vary while the
exact origin, final URL, HTTP 200 result, SiteGround/nginx provider family,
credential-free privacy classification, challenge/error absence, and signed
rendered-head and visible-content identities remain fail-closed.

The reconciliation workflow is restricted to Audit ID 2 in its exact
`recovery_required` verifier-defect state:

- `POST /api/wordpress/deployment/upgrade-bootstrap/recovery/reconciliation/preflight/41`
- `POST /api/wordpress/deployment/upgrade-bootstrap/recovery/reconciliation/apply/41`

The preflight requires a fresh valid schema-v1 browser proof and a structurally
valid Atlas Data backup created after the v0.59.93 runtime manifest was loaded.
The backup filename, byte size, SHA-256, timestamp, Audit ID 2 state, and
operator-confirmed OneDrive path/synchronization are bound into a short-lived
single-use handle.

The exact phrase is:

`RECONCILE PROJECT ATLAS BOOTSTRAP ACTIVATION FOR AUDIT 2 WITHOUT ANOTHER WORDPRESS WRITE`

Apply performs one Atlas audit-row finalization only. It preserves the original
WordPress activation write, checksum result, `verification_failed` and
`recovery_required` history, original failure gates, recovery snapshot, and
recovery inventories, then appends
`post_activation_verifier_contract_defect_reconciled`. It performs zero
WordPress, plugin, cache, content, media, payload, revision, rendering, Site
Title, or Tagline writes. Repeated use of the same successfully consumed handle
is an idempotent zero-write replay.

After reconciliation, stop. Metadata Bridge 0.57.7 upgrade, rendering,
SiteGround cache purge, and Bootstrap cleanup remain separately guarded.
