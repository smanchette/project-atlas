# Project Atlas v0.59.68 guarded rendering recovery disablement

## Scope

v0.59.68 changes only Atlas eligibility for the existing fixed Metadata Bridge rendering-disable operation. It does not add a WordPress mutation path, change the staged payload, alter rendering enablement, or authorize a live operation.

Ordinary disablement remains eligible when the latest rendering operation is a verified enablement and Atlas state is `rendering_enabled` with the exact approved payload, hash, and revision 1.

Recovery disablement is separately classified as `recovery_disable_ready` only when the latest rendering operation is an exact `enable_metadata_rendering` audit ending `pending -> verification_failed`, exactly one accepted write targeted the fixed enable endpoint, durable pre/post snapshots prove only disabled-to-enabled state changed, every page/media/site/cache verification passed, only `rendered_exact` failed, public metadata remains absent, staging audit history is verified, Atlas state remains the exact staged payload at revision 1, and the recovery recommendation is `disable_rendering`.

The recovery path fails closed for missing or multiple accepted writes, wrong mutation scope, uncertain snapshots, malformed transitions, conflicting or pending lifecycle history, payload/revision drift, page/media/cache drift, public metadata presence, a mismatched recommendation, disabled rendering, rollback history, or a completed disablement.

## Audit behavior

A future approved recovery disablement creates a new `disable_metadata_rendering` lifecycle audit. Its completion mode is `recovery_after_failed_enable_verification`. The original failed enable audit is immutable and remains `verification_failed`. The only WordPress mutation remains:

`PUT /wp-json/project-atlas/v2/pages/8/metadata/rendering/disable`

The request carries only the existing expected revision, optimistic snapshot hash, and approved payload hash. Post-write verification must prove rendering disabled while payload, hash, revision, plugin activation, page, media, Site Title, Tagline, and cache observations remain unchanged.

## Source diagnosis

The read-only source diagnostic confirms Metadata Bridge 0.57.5 registers a priority-20 `wp_head` callback, targets `is_page(8)`, reads the payload and enabled flag from post 8, reads the safety option used by the enable endpoint, and contains reachable public meta-description and JSON-LD output. Local source inspection therefore does not prove a plugin-code defect; cache/optimizer delivery or a runtime hook condition remains an external diagnostic question. The diagnostic performs zero WordPress and Atlas writes.

## Release boundary

This release does not disable rendering, roll back payload data, access live WordPress, capture production evidence, purge cache, or modify page 8 or media 31/32. A separate published runtime and explicit live authorization are required before recovery disablement.
