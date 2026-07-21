# Project Atlas v0.59.88 — Bootstrap Renewal Response Contract

## Defect corrected

The v0.59.87 operator interface loaded the zero-write recovery assessment, but the response exposed only a generic operation status, classification, recommendation, backup objects, and raw renewal history. The frontend consequently derived protected facts such as active source, expiration, renewal capacity, and eligibility. Its apply action also used the incorrect label `Commit active backup renewal`.

v0.59.88 makes the backend recovery response authoritative. The existing `status = recovery_assessment_complete` remains the operation result, while `audit_status` separately reports the durable establishment lifecycle state.

## Authoritative recovery state

The typed response explicitly reports:

- audit status, lifecycle classification, deterministic reason code, recommendation, and next required action;
- renewal eligibility and blocked state;
- immutable original backup plus server-computed expiration status;
- effective active backup, locked source (`original`, `replacement`, or `none`), expiration status, and active renewal sequence;
- renewal history enriched with server-computed active and expiration fields;
- renewal count, maximum of three, remaining capacity, and limit state;
- whether manual upload is durably observable, verification evidence exists, activation has started, checksum quarantine is active, or another mutation is pending.

Expiration is `valid`, `expired`, `missing`, or `invalid`. The server clock is authoritative. Nullable booleans are used when expiration or upload state cannot be proven rather than manufacturing a value.

## Operator interface

The interface displays durable lifecycle, original authorization backup, effective active backup, renewal capacity, and workflow state from response fields. It does not infer active source from list length or eligibility from the browser clock. The exact actions are:

- **Run renewal preflight**
- **Apply guarded renewal**

The successful state continues to say **Active backup renewed** and **Original authorization backup preserved**.

## Request and mutation boundary

The response fields are display-only. Preflight still accepts only fixed audit ID 1 and explicit replacement backup identities, method/reference, timezone-aware completion/deadline, confirmer, and four operator-controlled attestations. Apply still accepts only the safe process-memory handle fingerprint and exact phrase. Callers cannot submit audit status, source, expiration, renewal capacity, original-backup changes, active pointers, protected hashes, runtime identity, plugin paths, or credentials.

Recovery assessment performs no WordPress or cache request and no Atlas write. The original authorization backup remains immutable; a guarded apply can append one renewal and advance only the active backup pointer.
