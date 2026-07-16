# Project Atlas Upgrade Bootstrap 0.1.0

This separately versioned plugin exposes one application-password-compatible REST mutation: replace the active `project-atlas-metadata-bridge/project-atlas-metadata-bridge.php` installation from exactly version 0.57.4 with the exact locked 0.57.5 ZIP.

It accepts no URL, path, slug, version, method, extraction destination, overwrite target, activation choice, or arbitrary archive. The uploaded bytes must match SHA-256 `09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7`, the two-file portable archive inventory, and both locked file checksums. It requires an authenticated user with `update_plugins`, direct WordPress filesystem access, one active 0.57.4 bridge, and preserves the active-plugin option.

The endpoint becomes fail-closed after success because the bridge is no longer version 0.57.4. Bootstrap installation and later removal or deactivation require separate guarded approvals and audits. This artifact is not authorized for live installation by source publication.
