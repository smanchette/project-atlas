# Project Atlas Upgrade Bootstrap 0.3.0

This separately versioned plugin exposes one application-password-compatible REST mutation: replace the active `project-atlas-metadata-bridge/project-atlas-metadata-bridge.php` installation from exactly version 0.57.6 with the exact locked 0.57.7 ZIP.

It accepts no URL, path, slug, version, method, extraction destination, overwrite target, activation choice, or arbitrary archive. The uploaded bytes must match SHA-256 `ada4d97ea627a148d07fda809c1776a91a87d7a7e4957de3bece423a9bb80a62`, the two-file portable archive inventory, and both locked file checksums. It requires an authenticated user with `update_plugins`, direct WordPress filesystem access, one active 0.57.6 bridge, and preserves the active-plugin option.

The endpoint becomes fail-closed after success because the bridge is no longer version 0.57.6. Bootstrap installation, activation, deactivation, and deletion require separately guarded approvals and audits. This artifact is not authorized for live installation by source publication.
