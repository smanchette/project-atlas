# Project Atlas Metadata Bridge 0.57.11

Version 0.57.11 is a narrow successor to 0.57.10 in the same Metadata Bridge plugin family. It preserves the complete Performance Local V5 renderer, private one-page metadata transport, and WordPress-native estimate-form delivery contract while extending only the V5 asset-path validator.

The V5 payload may continue to use the existing `/wp-content/uploads/atlas-v5/...` paths. It may also use a core WordPress original upload path in the exact form `/wp-content/uploads/YYYY/MM/filename.ext`, with a four-digit nonzero year, month `01` through `12`, one ASCII-safe filename segment, and an approved image extension. Arbitrary uploads subdirectories, query strings, fragments, encoded paths, traversal, backslashes, and external URLs remain outside the payload contract. Exact attachment, origin, byte-hash, MIME-type, and dimension verification remains the responsibility of the governed Atlas-side media mapping before payload finalization.

The private route family is `GET`, `POST`, and `DELETE /wp-json/project-atlas/v4/performance-local-v5/page-payload/(?P<post_id>\d+)`. It is available only when WordPress reports `local` or `staging`, requires normal authenticated WordPress REST access (including standard Application Password authentication), `manage_options`, and `edit_post` for the exact target page. It accepts or removes only `_project_atlas_performance_local_v5_v1`; it never changes the page title, slug, content, excerpt, status, author, parent, menu order, featured image, or `_wp_page_template`.

The payload schema remains `project-atlas-performance-local-v5-wordpress@1`. POST is strict, payload-size bounded, hash- and identity-bound, validator-gated, read-back verified, idempotent for an exact current payload, and restores the prior metadata state if post-write verification fails. DELETE is expected-hash bound and removes only that one private metadata key. GET returns sanitized state and hashes, never the raw payload. The metadata remains excluded from core WordPress page REST responses.

The existing V5 renderer remains fail-closed outside `local` and `staging`. It selects its contained front-end template only for a published page carrying validator-passing V5 metadata. It does not register an editor template, add a block-editor chooser entry, or write `_wp_page_template`.

The estimate-delivery option remains `_project_atlas_estimate_form_delivery_v1` with schema `project-atlas-estimate-form-delivery@1`. Version 0.57.11 does not seed or enable delivery, add SMTP or provider integration, store customer submissions, expose private delivery configuration, or change the existing `wp_mail()` contract.

This package does not authorize production installation, production access, live recipient configuration, media substitution, bulk page application, export, publication, or deployment.
