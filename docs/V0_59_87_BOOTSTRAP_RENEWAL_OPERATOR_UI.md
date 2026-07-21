# Project Atlas v0.59.87 — Bootstrap Renewal Operator UI

## Defect corrected

v0.59.86 provided the guarded Atlas-only backup-renewal backend, but its first operator panel did not show original completion or renewal history, silently calculated the replacement deadline, and incorrectly synthesized the no-relevant-WordPress-change attestation as `true`. That interface was blocked from live use.

v0.59.87 removes the synthesized attestation. The replacement form begins empty, every inclusion and safety checkbox begins unchecked, and preflight remains disabled until the operator explicitly supplies and affirms the complete contract.

## Audit state display

On mount, the panel calls the read-only recovery assessment for fixed audit ID 1. It displays the immutable original authorization backup reference, completion, deadline, expiration, database inclusion, `wp-content/plugins` inclusion, and restore capability. It separately displays the effective active backup and labels it as the original or an active replacement.

Renewal records are sorted by sequence and show only safe operational fields: sequence, reference, completion, deadline, inclusion/restore attestations, committed time, status, and active or historical classification. Handles, signatures, protected hashes, credentials, and internal identity fingerprints are not rendered. An empty history is stated explicitly. Renewal count is displayed against the fixed maximum of three.

## Explicit replacement contract

The operator must enter Atlas Data, Media, and Program backup identities; SiteGround method and reference; timezone-aware ISO-8601 completion and deadline; and confirmer identity. Database inclusion, plugin inclusion, restore capability, and the statement “I confirm that no relevant WordPress change occurred after this replacement SiteGround backup completed” require four independent unchecked controls.

The UI never invents a deadline. A separate **Calculate four-hour deadline for review** action is available only as an explicit convenience after a valid completion value, and the exact ISO-8601 deadline remains visible and editable before submission. The backend remains authoritative for the exact four-hour policy.

## Guarded flow

1. Load audit 1 through read-only recovery assessment.
2. Enter and review every replacement-backup field and attestation.
3. Run the zero-write renewal preflight.
4. Review every gate and the safe handle fingerprint.
5. Enter the exact phrase `RENEW PROJECT ATLAS BOOTSTRAP HANDOFF BACKUP FOR AUDIT 1`.
6. Commit only the audit-bound active-backup renewal.
7. Review sequence, active deadline, original preservation, and write counts.
8. Capture fresh browser evidence and run manual-install verification in a separately approved phase.

Edits invalidate the displayed preflight and clear its phrase. Reloading resets the form, attestations, fingerprint, and phrase, then reloads durable audit history. No state is stored in browser persistent storage.

## Safety and expiration

The UI sends exactly the backend renewal schema. Audit ID is fixed to 1; callers cannot choose the original backup, active pointer, sequence, status, runtime/plugin identity, or protected hashes. It collects no SiteGround, SFTP, FTP, or SSH credentials and offers no restore, plugin upload, activation, WordPress write, or cache action.

An expired active replacement can be renewed again only while the backend reports the audit eligible and fewer than three renewals exist. At the limit, renewal controls are disabled and the backend recovery recommendation is shown. Previous renewal history is never overwritten.
