\# Project Atlas Version History

## v0.59.54

Separated Metadata Bridge payload staging, rendering enablement, rendering disablement, and payload rollback. Metadata Bridge 0.57.5 adds four isolated plugin-owned write surfaces and disables the legacy combined apply endpoint. Atlas adds token-free preflights, short-lived one-time process-memory handles, four lifecycle audit types, four-hour backup enforcement, schema-v1 evidence fallback, exact Organization plus Service payload validation, and Data Backup v0.34 lifecycle-audit portability.

Verification before checkpoint:

- Frontend TypeScript and production build passed
- Backend tests passed: 556, with 1 intentional platform-specific skip
- Migration 0017 → 0018 → 0017 → 0018 passed
- Plugin ZIP portability and source byte comparison passed



\## v0.11



QA readiness checks, gated approval, and internal preview banner.



\## v0.12



QA remediation, notes, and approval audit trail.



\## v0.13



Manual page editor, revision history, and WordPress draft workflow foundation.



Included:



\- WordPress Sandbox

\- Draft Queue

\- Draft Review

\- Export Package page

\- WordPress draft services

\- Page export services

\- WordPress draft audit migration



Verification before checkpoint:



\- Frontend build passed

\- Backend tests passed: 119

\- Git tag: v0.13



\## v0.14



Platform Portability and Restore Readiness.



Goal:



If the current computer dies, Atlas can be rebuilt on another computer without guessing.



Planned focus:



\- New computer setup instructions

\- Backup and restore documentation

\- Protected path rules

\- Version history documentation

\- Standard verification commands
