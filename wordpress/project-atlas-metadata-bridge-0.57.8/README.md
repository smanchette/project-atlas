# Project Atlas Metadata Bridge 0.57.8

Version 0.57.8 is an append-only local rehearsal successor to 0.57.7. It preserves the complete guarded page-8 metadata lifecycle and adds one contained, Bridge-owned Performance Local V5 renderer for disposable WordPress review.

The V5 renderer accepts only the exact `project-atlas-performance-local-v5-wordpress@1` post-meta contract at `_project_atlas_performance_local_v5_v1`. It is fail-closed unless WordPress reports the `local` environment and the payload is explicitly marked `rehearsal_only`. It owns its template and local assets, makes no external request, registers no REST route or form endpoint, sends no mail, and stores no submission data. Invalid payloads and unrelated pages retain their normal WordPress template.

The V5 rehearsal surfaces are generic `city_service`, `estimate`, and `special_demo` layouts. No generated-page, WordPress-post, company, city, phone, logo, image, or domain identity is embedded in the V5 renderer. The special surface is synthetic and requires the exact visible marker `DEMO SPECIAL — NOT SITE CONTENT`. All estimate controls are read-only and disabled; the form has no action, endpoint, or named controls.

The production deployment release remains locked to the separately preserved 0.57.7 package. This source package does not authorize installation, activation, registration, export, publication, deployment, form-provider configuration, or a production Bridge upgrade.
