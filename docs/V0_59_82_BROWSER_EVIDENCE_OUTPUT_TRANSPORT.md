# Project Atlas v0.59.82 — Browser-Evidence Output Transport

## Scope

v0.59.82 corrects only the serialized transport of signed manual browser evidence. The capture helper now writes an ASCII-only JSON envelope using standard `\uXXXX` escapes for non-ASCII characters.

The evidence object after JSON parsing is unchanged. Schema-v1 and schema-v2 meanings, timestamp canonicalization, normalized metadata and heading inventories, privacy findings, canonical signature payload, and HMAC verification are unchanged. The byte-exact BOM-free UTF-8 DOM input contract introduced in v0.59.80 is also unchanged.

## Failure corrected

Windows PowerShell 5.1 interprets BOM-free UTF-8 text as the active ANSI code page when `Get-Content` is used without an explicit encoding. Reading and reserializing a signed evidence file could therefore convert the locked Orlando en dash and other Unicode content to mojibake. The backend correctly rejected the altered payload because its signature no longer matched.

ASCII JSON escapes are invariant across the relevant Windows text code pages. An operator-side PowerShell JSON round trip therefore preserves the parsed Unicode values and the existing signature.

The same hardening review also made successful inactive-bootstrap inventory verification idempotent under the existing process lock. Concurrent verification requests may repeat the read-only observations, but only one request can append the durable `manual_installation_inventory_verified` transition or increment its Atlas audit write count.

## Safety boundary

This correction does not authorize live browser capture, a manual bootstrap upload, bootstrap activation, a Metadata Bridge upgrade, metadata rendering, a cache purge, or any page, media, plugin, or settings mutation. Existing evidence expiry, URL, identity, privacy, H1, metadata, signature, and workflow gates remain fail-closed.

## Manual-handoff resumption matrix

All outcomes begin with a read-only state assessment. Sandbox credentials must be re-entered after a backend restart. Fresh evidence is required for a new authorization or preflight after evidence expiry. A fresh SiteGround backup is required whenever its recorded four-hour deadline has passed; Atlas never extends or silently substitutes that deadline.

| Morning outcome | Operator action | Next guarded milestone |
| --- | --- | --- |
| Authorization succeeded; upload not performed | Confirm the backup deadline, then upload only the exact 0.3.0 ZIP through Plugins → Add New Plugin → Upload Plugin → Install Now. Do not activate. | Manual-install verification. |
| Backup expired before upload | Do not upload. Create and attest a fresh SiteGround on-demand full-site backup. | New evidence, preflight, and manual-upload authorization. |
| Exact bootstrap uploaded inactive | Do not activate manually or alter another plugin. | Manual-install verification, then a separate activation preflight. |
| Bootstrap accidentally activated | Do not deactivate, delete, overwrite, or retry. | Read-only recovery assessment first. |
| Destination folder already exists | Do not replace or delete it. | Read-only recovery assessment and inventory classification. |
| Installation failed | Do not retry, replace, or clean up automatically. Preserve the exact WordPress result. | Read-only recovery assessment; renew backup/evidence if required by the result and deadline. |
| Wrong ZIP uploaded | Do not activate, overwrite, delete, or repair it. | Read-only recovery assessment; destructive correction requires separate approval. |
| Authorization never completed and no audit exists | Do not upload. | Re-enter Sandbox credentials if needed, create fresh backup/evidence if expired, and rerun manual-install preflight. |

After authorization, a restart invalidates the process-memory handle but preserves the durable handoff audit. After manual-install verification, activation still requires a fresh activation preflight and separate exact phrase. After activation, checksum-pending quarantine remains blocking until the authenticated fixed status route proves the exact executable checksum; expiry does not permit an automatic retry, deactivation, deletion, overwrite, or restoration.
