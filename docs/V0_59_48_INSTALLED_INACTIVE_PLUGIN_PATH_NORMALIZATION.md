# Project Atlas v0.59.48 — Installed-Inactive Plugin Path Normalization

## Scope

This release corrects only the installed-inactive reconciliation verifier. WordPress core REST represents a plugin entry without the final `.php`, for example:

```text
project-atlas-metadata-bridge/project-atlas-metadata-bridge
```

The authorized artifact entry remains:

```text
project-atlas-metadata-bridge/project-atlas-metadata-bridge.php
```

The verifier now interprets the extensionless identifier as the authorized entry only after strict validation. It also accepts the already-complete entry and normalizes Windows separators to POSIX separators. It rejects absolute paths, traversal, empty segments, null bytes, malformed characters, leading or trailing slashes, and ambiguous normalized matches. Similar slugs and different entry filenames never become the authorized bridge.

## Raw inventory integrity

Normalization is used only to select the matching inventory row. Atlas does not rewrite the WordPress response. Complete-plugin and active-plugin inventory hashes continue to use the exact raw REST values and existing status data. The previously locked inventory hashes therefore retain their meaning.

## Installed-inactive gates

The normalized singleton row supplies the core WordPress inactive status and declared plugin version. Duplicate raw rows or distinct raw identifiers that normalize to the same authorized entry fail the singleton gate.

The safety gate is now named `inactive_safety_corroboration`. It does not claim a direct read of `_project_atlas_metadata_safety_v1`. The private option is known to exist from the separately recorded read-only diagnosis, but WordPress core exposes its serialized value only as an opaque placeholder while the target plugin is inactive.

Safety is corroborated from all of the following:

- the normalized singleton is inactive in core inventory;
- Atlas metadata state and audit row counts are `0/0`;
- page, canonical body, media 31, and media 32 snapshots remain exact;
- signed rendered evidence is verified and contains no Atlas marker or metadata payload;
- media 32 remains absent;
- the cache observation remains unchanged and reconciliation has no purge transport.

## Mutation boundary

Verification remains token-free, GET-only, and performs zero WordPress and Atlas writes. Finalization remains a separate one-time-handle and exact-phrase operation that can update only the existing Atlas audit and append its reconciliation transition. This release adds no WordPress upload, installation, activation, deactivation, option, metadata, page, media, cache, removal, or restoration transport.

Publishing v0.59.48 does not authorize live evidence capture or reconciliation.
