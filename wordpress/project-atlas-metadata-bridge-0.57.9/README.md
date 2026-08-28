# Project Atlas Metadata Bridge 0.57.9

Version 0.57.9 is an append-only rehearsal successor to 0.57.8. It preserves the guarded metadata lifecycle and the contained Performance Local V5 renderer, and adds one WordPress-native delivery path for the renderer's existing estimate form.

The delivery option is `_project_atlas_estimate_form_delivery_v1` with schema `project-atlas-estimate-form-delivery@1`. Unless the complete exact option matches the rendered Website, form version, and canonical field-definition hash, the renderer emits the same inert, unnamed, read-only form as 0.57.8. The plugin does not seed or enable delivery on activation.

When an exact configuration is enabled, the existing City-Service final form and Request an Estimate form receive a runtime HMAC-signed token and submit same-origin JSON to `POST /wp-json/project-atlas/v4/performance-local-v5/estimate`. WordPress validates the exact page and field contract, origin, token, honeypot, rate window, and idempotency identity before one synchronous `wp_mail()` call. Mail is plain text. Request-scoped From filters are removed after the call, and Reply-To is available only for an explicitly bound governed sixth email field. The private recipient and private Website-domain From identity remain server-side and never supply or replace the optional public Website contact email.

Field validation returns the fixed public message `Please check the highlighted fields and try again.` with HTTP 422 and no mail attempt. The client preserves values, marks and focuses the first field that fails the governed validation metadata, and clears that field state when it is edited. A genuine `wp_mail()` failure remains a separate HTTP 503 state using the configured generic delivery-failure message, preserves values, and does not mark customer fields invalid.

No customer values, raw address, user agent, token, idempotency identity, or mail content are stored by the plugin. Short-lived abuse metadata contains only keyed hashes, counters, states, and expirations. The browser client writes no storage, analytics, logs, URL values, or third-party requests.

The underlying V5 renderer remains local-rehearsal-only and still accepts only the exact `project-atlas-performance-local-v5-wordpress@1` post-meta contract at `_project_atlas_performance_local_v5_v1`. This package does not authorize installation on production, activation, live recipient configuration, SMTP/provider configuration, export, publication, or deployment.
