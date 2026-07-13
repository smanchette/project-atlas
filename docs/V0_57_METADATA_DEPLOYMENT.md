# v0.57 Orlando Metadata Bridge Deployment Readiness

This document is an instruction set only. v0.57 local implementation does not install, activate, deploy, purge caches, or write to WordPress.

Project Atlas milestone v0.57.7 intentionally contains Project Atlas Metadata Bridge v0.57.4. Bridge behavior and its portable ZIP were frozen at v0.57.4; v0.57.5 through v0.57.7 changed only Atlas test-database isolation and deterministic validation coverage.

This commit does not authorize live plugin installation or activation, metadata apply or rollback, cache purge, media cleanup, deployment, or any WordPress write.

## Fixed scope

- Atlas page 41, WordPress page 8, slug `drywood-termite-tenting-orlando-fl`.
- WordPress media 31 is the only social and structured-data image.
- WordPress media 32 is explicitly excluded and is never readied for cleanup.
- The generic `My WordPress` title suffix remains unchanged.
- The bridge never sends or edits title, H1, content, excerpt, slug, URL, status, canonical, featured image, Site Title, Tagline, attachment data, or cache settings.

## Artifact installation (future separately approved action)

1. Confirm the ZIP SHA-256 against `wordpress/checksums.sha256`.
2. Confirm a WordPress backup identifier, timestamp, database inclusion, plugin-file inclusion, and tested restore access.
   Atlas Data Backup JSON is opened and structurally validated. Atlas Media and Program Backup filenames are format-validated because those streamed ZIPs are not retained by Atlas; their possession and contents remain operator attestations. WordPress durability, inclusion, and restore capability are also explicitly operator-attested, not claimed as programmatically verified.
3. In WordPress Admin, upload the versioned ZIP. Do not activate during the installation confirmation step.
4. Confirm installation completed and the plugin version is 0.57.4. Activation rotates the dedicated Atlas safety generation and forces rendering off with one narrowly scoped option write.
5. Activate as a separate confirmed action. Activation writes only the dedicated Atlas safety-state option to rotate the generation and force rendering off; it writes no page 8 post meta or payload and renders nothing.
6. Run the Atlas metadata dry run. Do not apply unless every gate passes and a short-lived signed token is produced.
7. Enter the exact phrase `APPLY ORLANDO METADATA TO WORDPRESS` and the required backup confirmations.

## Verification-first cache process

After a future apply, use the read-only verify route first. Compare authenticated/bypass HTML and public response headers, including SiteGround `x-proxy-cache`. If the origin/rendered metadata is correct but public HTML is stale, stop and request separate cache-purge approval. Apply and deployment never purge caches.

## Rollback

Rollback is a separate dry-run and apply flow. It requires the captured pre-apply snapshot, current payload-hash match, a fresh signed token, Atlas and WordPress backup references, and the exact phrase `ROLL BACK ORLANDO METADATA`. It restores the prior metadata bridge state only; it does not restore WordPress globally or mutate page content/media.

## Failure recovery

If WordPress accepts metadata but Atlas audit finalization fails, do not retry apply. Run read-only verification and reconcile the observed plugin revision/payload hash before any separately designed recovery. A failed audit preserves actionable error text and the pre-apply snapshot.
