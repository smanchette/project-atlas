# Project Atlas v0.59.8 deployment release identity

Project Atlas v0.59.8 separates manifest integrity from release freshness. A checksum-valid manifest is not a verified runtime identity until its version, commit, and tag match independent runtime expectations. Git-less Docker never lets the manifest authenticate itself.

The source locks manifest schema 2, source compatibility `project-atlas-release-identity-v0.59.8`, and Metadata Bridge v0.57.4 identity. It does not embed the eventual v0.59.8 commit SHA.

## Publication and runtime sequence

1. Commit the corrected source.
2. Create annotated tag `v0.59.8` at that exact commit.
3. Push the commit and annotated tag.
4. Generate a new ignored runtime manifest using the final v0.59.8 commit and tag:

   ```powershell
   $env:PYTHONPATH = (Resolve-Path backend).Path
   python backend/scripts/generate_deployment_release_manifest.py `
     --project-root . `
     --output .runtime/atlas-release.json `
     --release-version v0.59.8 `
     --require-synchronized-remote
   ```

5. Configure `ATLAS_EXPECTED_RELEASE_VERSION`, `ATLAS_EXPECTED_RELEASE_COMMIT`, and `ATLAS_EXPECTED_RELEASE_TAG` in the ignored local runtime environment.
6. Configure `ATLAS_RELEASE_MANIFEST_SHA256` from the generator output. Do not commit the manifest or local environment.
7. Recreate only the local Atlas backend. This clears the WordPress application password from process memory.
8. Verify the runtime release identity: manifest integrity verified, expected release matched, runtime identity verified, and Git metadata unavailable without claiming direct Git verification in slim Docker.
9. Create fresh Atlas Data, Media, and Program backups. Old Atlas backups must not be substituted for this new post-runtime-verification set.
10. Save and verify those three backups in the approved OneDrive backup location.
11. Create a new PowerShell stopping-point record outside the repository after the fresh Atlas backups.
12. Create a fresh SiteGround on-demand full-site backup. Old SiteGround backups must not be reused.
13. Record the durable SiteGround backup reference and timezone-aware completion timestamp.
14. Re-enter the WordPress application password only through `http://localhost:5173/wordpress-sandbox`.
15. Rerun the live read-only installation preflight.
16. Stop before installation authorization unless every gate passes.

The Atlas backup step and SiteGround backup step are separate gates. The PowerShell stopping point occurs after the fresh Atlas backups and before live preflight. Publication and a successful read-only preflight do not authorize installation; live installation authorization remains a separate Shawn-approved action.

The generator fails for a dirty tree, malformed version or commit, unsupported schema, a missing/lightweight/wrong tag, a plugin checksum mismatch, and—when `--require-synchronized-remote` is used—local/upstream/remote branch or remote annotated-tag divergence.

## Historical identities

The published `v0.59.6` tag remains valid immutable history, but its source still accepted the stale v0.59.4 Git-less manifest and is not suitable for live deployment identity. v0.59.8 supersedes it for deployment readiness. Old manifests must never be reused after a source release changes.

Missing expected-release inputs, any manifest/expected mismatch, malformed identity, checksum failure, schema/source-compatibility mismatch, or plugin mismatch returns `release_identity_unavailable`. WordPress observation, dry-run readiness, confirmation-token issuance, authorization, and audit progression remain blocked.

This workflow does not authorize live WordPress access, installation, activation, metadata application, cache purge, plugin removal, backup restoration, page changes, or media changes.
