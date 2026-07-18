# Project Atlas Upgrade Bootstrap 0.2.0

This separately versioned plugin exposes one application-password-compatible REST mutation: replace the active `project-atlas-metadata-bridge/project-atlas-metadata-bridge.php` installation from exactly version 0.57.5 with the exact locked 0.57.6 ZIP.

It accepts no URL, path, slug, version, method, extraction destination, overwrite target, activation choice, or arbitrary archive. The uploaded bytes must match SHA-256 `3b2d0035f995c3006e0d3be02596bd2cf19ef7e4a97572168621beb7a9abf788`, the two-file portable archive inventory, and both locked file checksums. It requires an authenticated user with `update_plugins`, direct WordPress filesystem access, one active 0.57.5 bridge, and preserves the active-plugin option.

The endpoint becomes fail-closed after success because the bridge is no longer version 0.57.5. Bootstrap installation, activation, deactivation, and deletion require separately guarded approvals and audits. This artifact is not authorized for live installation by source publication.
