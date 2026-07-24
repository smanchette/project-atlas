# Project Atlas Changelog

**Version:** 1.0

**Status:** Historical Project Record

---

## Purpose

This document records major Project Atlas milestones and important changes in direction. It does not replace Git history or detailed release notes. Its purpose is to help future stewards understand how Atlas evolved and why major phases existed.

---

## Founding Vision

Project Atlas was established as a complete business website creation and management platform.

Its permanent promise is:

> **Atlas is not being built to generate pages. Atlas is being built to create, publish, and maintain complete, high-quality business websites that businesses, search engines, AI systems, and whatever comes next can confidently rely on for years.**

Flo-Zone Pest And Termite Solutions Inc. became the first real-world proving ground.

---

## Early Product Direction

The project vision expanded beyond isolated WordPress publishing to include complete website creation, local SEO, research and structured knowledge, AI content and media, QA and approvals, WordPress deployment and verification, backups and recovery, operator workflows, maintenance, multi-company expansion, SaaS capability, product-family collaboration, and long-term operational intelligence.

---

## WordPress Foundation Phase

A substantial foundational phase focused on safe WordPress deployment, including authentication, exact-origin controls, guarded writes, backups, rollback, audit history, evidence capture, public and authenticated verification, plugin lifecycle management, fail-closed identity checks, recovery workflows, deterministic releases, runtime manifests, migrations, and secret isolation.

This phase was necessary to make later full-site generation trustworthy and recoverable.

---

## Flo-Zone Orlando Proof

Atlas created and verified the Orlando drywood-termite tenting page for Flo-Zone, including approved company identity, contact information, license and certified-operator information, page content, featured media, WordPress deployment, metadata, structured data, read-only live verification, rollback, and safety controls.

This proved important publishing capabilities but did not represent the complete Atlas website vision.

---

## v0.59.89

Centralized WordPress HTTP client, explicit Atlas User-Agent, SiteGround/nginx compatibility, guarded backup renewal, and runtime validation.

## v0.59.90

Cross-release public transport identity, canonical compatibility, representation-level normalization, and preservation of real status, source, provider, origin, redirect, privacy, and page-identity drift protections.

## v0.59.91

Guarded retirement of stale Bootstrap authorizations, terminal `authorization_retired` status, fresh authorization for an already-installed inactive Bootstrap, and preservation of historical authorization and renewal records.

Audit ID 1 was retired because its authorization remained bound to an obsolete HTTP 403 provider-block transport identity.

## v0.59.92

Correct public-observation producer/consumer contract, sanitized observations, precise DNS/timeout/TLS/network classifications, correct acquisition-failure versus origin-drift handling, and strict SiteGround cache semantics.

A fresh installed-inactive authorization created Audit ID 2. It reached `manual_installation_inventory_verified`. Bootstrap 0.3.0 was then activated through one guarded plugin-status write.

Post-activation verification incorrectly moved Audit ID 2 to `recovery_required` because of verifier defects rather than a genuine WordPress or plugin-integrity problem.

## v0.59.93

**Published commit:** `fdb91b392aa64fb9dbd03750c1dd10190149dcd9`

Major changes:

- Correct post-activation inventory expectations
- Remove generic pre-activation inventory gates from post-activation verification
- Require exact ordinary active Bootstrap state
- Reject network-active Bootstrap
- Exclude volatile cache headers from durable protected state
- Permit cache-state variation only during post-mutation verification
- Preserve strict origin, URL, HTTP, provider, privacy, challenge/error, and signed DOM checks
- Add one-time Atlas-only activation reconciliation
- Preserve original activation write, checksum, failure history, and audit records
- Guarantee zero additional WordPress writes during reconciliation

### Current known checkpoint when Documentation Foundation v1.0 was created

- Runtime: v0.59.93
- Migration: `20260723_0026`
- Audit ID 1: `authorization_retired`
- Audit ID 2: `recovery_required`, awaiting guarded reconciliation
- Bootstrap 0.3.0: active
- Metadata Bridge: active at 0.57.6
- Rendering: disabled
- WordPress content and settings: unchanged
- Repository: clean and synchronized

---

## Atlas Documentation Foundation v1.0

The following governing documents were established:

- `PROJECT_ATLAS_CONSTITUTION.md`
- `PROJECT_ATLAS_ROADMAP.md`
- `PROJECT_ATLAS_ARCHITECTURE.md`
- `PROJECT_ATLAS_CHANGELOG.md`

Purpose:

- Preserve the complete long-term vision
- Separate permanent principles from current priorities
- Guide future architecture
- Preserve major project history
- Help future developers, operators, AI systems, and family stewards understand why Atlas exists

---

## Next Planned Milestones

1. Reconcile Audit ID 2 under v0.59.93.
2. Complete remaining Bootstrap and rendering foundation only as required.
3. Complete the full Flo-Zone website.
4. Convert that process into a repeatable company-onboarding and website-generation workflow.
5. Build a second company website.
6. Improve templates, QA, speed, and operator controls.
7. Expand advanced SaaS, maintenance, integration, and intelligence capabilities later.

---

## Changelog Maintenance Rule

Add entries for major releases, major architectural shifts, important product-direction decisions, major safety or recovery milestones, completion of major roadmap phases, and Constitution revisions.

Routine implementation details should remain in Git history and release notes.

The Constitution governs the project. The Roadmap describes what comes next. The Architecture describes how the platform is organized. This Changelog explains how Atlas arrived there.
