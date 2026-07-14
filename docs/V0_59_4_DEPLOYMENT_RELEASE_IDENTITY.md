# Project Atlas v0.59.4 deployment release identity

> Historical record only. The v0.59.4 checksum-only Git-less identity design was superseded by v0.59.8 and must not be used for deployment readiness. The published v0.59.6 tag remains valid history but is also unsuitable for live deployment identity.

The source tree contains only immutable deployment workflow expectations and Metadata Bridge v0.57.4 artifact facts. It does not contain a Git commit SHA that claims to identify its own commit.

Live installation authorization fails closed until Atlas validates a post-publication runtime manifest. Missing, stale, malformed, mismatched, or checksum-invalid identity is reported as `release_identity_unavailable`; no confirmation token is issued.

## Publication and runtime sequence

1. Commit the reviewed v0.59.4 source.
2. Create annotated tag `v0.59.4` pointing to that commit.
3. Push the source commit and annotated tag.
4. Generate the ignored runtime manifest only after the commit and tag exist:

   ```powershell
   $env:PYTHONPATH = (Resolve-Path backend).Path
   python backend/scripts/generate_deployment_release_manifest.py `
     --project-root . `
     --output .runtime/atlas-release.json
   ```

5. Copy the printed SHA-256 into `ATLAS_RELEASE_MANIFEST_SHA256` in the local runtime environment. Do not commit the manifest or its runtime environment file.
6. Rebuild or restart the local Atlas backend. Docker Compose mounts only `wordpress/` at `/atlas-program/wordpress` and the ignored `.runtime/` directory at `/atlas-runtime`, both read-only. Git metadata is not mounted into the backend runtime.
7. Confirm the readiness API reports `release_status: verified`, `verification_source: checksum_verified_manifest`, Atlas v0.59.4, the final commit, tag v0.59.4, and Metadata Bridge v0.57.4.
8. Run the read-only preflight.
9. Create fresh Atlas backups and a fresh SiteGround on-demand full-site backup before any separately approved authorization. The earlier backup cannot be reused outside its four-hour window or after a relevant WordPress state change.

On a development host where `.git` is present, the same manifest is additionally checked against Git HEAD and the tag target. A checksum-verified manifest is required in both modes; environment version/commit/tag values alone are never accepted.

This source correction does not authorize live WordPress access, plugin installation or activation, metadata application, cache purge, plugin removal, backup restoration, page changes, or media changes.
