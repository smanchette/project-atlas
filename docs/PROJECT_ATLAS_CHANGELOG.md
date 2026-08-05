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

## v0.59.96

Corrected the Metadata Bridge 0.57.7 post-upgrade cache boundary so ordinary
SiteGround HIT/MISS and recognized request-diagnostic variation cannot be
misreported as durable WordPress drift. Provider, origin, privacy,
authentication, URL, redirects, signed rendered identity, security headers,
purge count, plugin inventories, and all durable protected state remain
fail-closed.

Added a dedicated one-time Atlas-only reconciliation for the exact Upgrade
Audit ID 3 cache-boundary incident. It requires fresh signed evidence,
authenticated GET-only WordPress observations, a fresh post-runtime Atlas Data
backup, exact historical audit identity, and unchanged Metadata Bridge,
Bootstrap, page, media, settings, payload, revision, rendering, and cache-purge
state. Reconciliation performs one atomic update to Audit ID 3 and zero
WordPress, plugin, or cache writes.

## v0.59.98

Prepared the Upgrade Audit ID 3 reconciliation contract for the exact
v0.59.98 runtime and repository tag. The workflow remains fail-closed for
v0.59.96, v0.59.97, future, malformed, stale-manifest, wrong-commit, and
wrong-tag identities.

Fresh signed browser evidence must be captured after the loaded v0.59.98
runtime manifest was generated. The existing post-runtime Atlas Data backup,
one-time handle, exact Audit ID 3, confirmation phrase, one Atlas audit update,
and zero WordPress, plugin, and cache-write guarantees remain unchanged.

## v0.59.99

Added an Audit-ID-3-only compatibility rule for the historical
`x-content-type-options` observation gap. The rule proves the exact v0.59.95
capture identity and historical non-collection, then requires three stable
current anonymous public observations containing exactly one normalized
`nosniff` value.

The general cache-boundary comparator remains unchanged. Redirects, non-200
responses, malformed or duplicate header values, provider or origin drift,
other security-header differences, page identity, plugin inventories,
payload, revision, backups, runtime identity, evidence, and one-time handles
remain fail-closed. Reconciliation still performs one Atlas audit update and
zero WordPress, plugin, or cache writes.

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

## Atlas Complete Website Blueprint v1.0

Established `PROJECT_ATLAS_COMPLETE_WEBSITE_BLUEPRINT.md` as the permanent
website-specific governing blueprint beneath the Constitution.

The Blueprint defines the complete website lifecycle and the separation among
business facts, content, presentation, media, intelligence, and operational
data. It also establishes reusable Brand Assets, Website Identity, image,
theme, optional customer-portal, and future intelligence capabilities while
keeping Flo-Zone Pest And Termite Solutions Inc. as a reference implementation
rather than a platform boundary.

This was a documentation-only milestone. It did not implement or change
application, WordPress, plugin, database, migration, audit, or runtime
behavior.

---

## Atlas Product Specification v1.0

Established `PROJECT_ATLAS_PRODUCT_SPECIFICATION.md` as the permanent
capability specification for the Atlas platform.

The Product Specification defines the responsibilities, boundaries,
relationships, configuration surfaces, extension points, and implementation
goals of the major Atlas subsystems. It preserves strict separation among
business facts, knowledge, content, presentation, media, intelligence, and
operational data while establishing long-term support for provider adapters,
multiple applications and publishing systems, multi-tenant operation,
white-label products, plugins, and an Extension SDK.

Flo-Zone Pest And Termite Solutions Inc. remains the current reference
implementation and is not a platform requirement. This was a
documentation-only milestone and changed no application, WordPress, plugin,
database, migration, audit, or runtime behavior.

---

## Website Context and Business Identity Foundation

Introduced additive first-class Brand, Website, and Website Identity ownership
beneath the existing Business domain. Generated pages may bind directly to a
website, while legacy records resolve the business's active website when the
new relationship is absent.

A single website-context service now supplies approved business, brand,
website, identity, service, and page-geography information to reusable page
queueing, draft generation, export, manual editing, approved-page repair, and
preview workflows. Flo-Zone-specific presentation copy, geography labels,
knowledge-block selections, customer audiences, domain identity, and company
labels moved into Flo-Zone seed configuration. Existing locked WordPress and
SiteGround safeguards remain unchanged.

An isolated fictional company, brand, website, identity, service, and
geography fixture proves that reusable workflows select the correct context
without Flo-Zone name, service, location, URL, or branding leakage.

Data backup format 0.42 includes the new ownership records while preserving
support for earlier backups that contain none of them. Migration
`20260727_0028` creates and backfills the new records and the optional generated
page relationship. Rollback is structurally available only while no dependent
website-context data must be preserved; operational rollback should therefore
use a pre-migration Atlas Data backup rather than dropping populated ownership
tables. The migration does not change WordPress, plugin, cache, audit, or
runtime state.

This milestone intentionally does not implement themes, navigation, provider
abstraction, portals, intelligence, authentication, full Brand Assets, or live
deployment for another company.

---

## Website-Scoped Site Plan and Page-Type Architecture Foundation

Added Website-owned Site Plans, Planned Pages, and pre-generation Planning
Records. Planning supports Home, About, Contact, Service, County or service
area, City or local area, City-Service, and Informational or FAQ page types.
Atlas-generated answers use approved Website Context and knowledge while
operator overrides remain separate and identifiable. Confidence, missing
information, and improvement recommendations are advisory and do not block
generation.

Website ownership now governs slug uniqueness, existing-page lookup, batch
generation, approval and WordPress-draft queues, QA context, and bulk export.
Mixed-Website and invalid cross-business relationships fail closed, and
Businesses with multiple active Websites require explicit Website selection.

Migration `20260728_0029` creates the planning records and backfills existing
Flo-Zone generated pages into a primary Flo-Zone Site Plan without modifying
their IDs, content, titles, headings, slugs, hashes, approvals, media,
WordPress references, or audit and deployment history. Data backup format
0.43 includes the planning records and remains compatible with prior supported
formats.

The local Site Plan screen exposes planned-page relationships, status,
generated-page state, Atlas answers, operator overrides, confidence, and
nonblocking recommendations. This milestone does not add generation for new
page types, navigation construction, component or theme systems, media
redesign, provider abstraction, production publishing, or external-system
activity.

---

## Website-Scoped Semantic Component Registry and Page Composition Foundation

Established versioned semantic component contracts as Atlas's reusable,
fact-free presentation boundary. Every contract records its purpose, exact
approved input requirements, customer outcome, compatible page types,
variants, and accessibility obligations. Components consume approved Atlas
records; they do not own business facts, content, media, or operational data.

Added Website-, Site-Plan-, Planned-Page-, and Generated-Page-scoped
compositions. Atlas-generated component suggestions remain separate from
operator composition decisions, and compositions bind to exact draft,
Website Context, navigation, and internal-link source identities. Unknown,
incompatible, stale, cross-Website, or missing-input compositions fail closed.
The local Generated Page preview now renders through these contracts using one
neutral Atlas base presentation, including operator-approved navigation and
internal links without inserting links into stored content.

Migration `20260801_0037` adds the registry and composition records. Atlas Data
backup format 0.49 preserves both while remaining compatible with earlier
supported backups. Website Readiness now assesses semantic composition
coverage and freshness. Themes, Brand Assets, media ingestion or generation,
complete-site preview, publication, WordPress rendering, and SiteGround remain
deferred.

---

## Website-Scoped Brand Assets and Website Identity Asset Foundation

Added Business- and Brand-owned, versioned visual-identity assets with explicit
purpose, approved usage, restrictions, accessibility intent, local artifact
identity, provenance, rights, approval, replacement, and retirement history.
Asset existence does not imply approval. Website Identity selects only approved,
type-compatible assets through separate versioned operator decisions, preserving
selection provenance and history across replacements.

Semantic page compositions consume current Website Identity selections without
owning Brand facts or presentation rules. Approved identity artifacts may appear
in the neutral local composition preview, while legacy free-form identity URLs
are not treated as the authoritative component asset source. Composition source
identity includes selected asset versions and checksums so changed selections
make dependent compositions stale until explicitly refreshed.

Migration `20260801_0038` adds Brand Asset and Website Identity assignment
records. Atlas Data backup format 0.50 preserves the new durable records while
remaining compatible with earlier supported formats. Website Readiness now
reports approved Brand Asset governance and Website Identity selection coverage.
Themes, design tokens, page-media planning, media or AI generation, complete-site
preview, publication, WordPress rendering, and SiteGround remain deferred.

---

## Website-Scoped Theme and Design Token Foundation

Added Website-, Business-, and Brand-bound, versioned Themes with governed
lifecycle, approval, operator provenance, replacement and retirement history,
and one active Website selection. A typed design-token contract now governs
color, typography, spacing, widths, borders, elevation, controls, navigation,
CTAs, responsive behavior, layout, motion, and reduced-motion behavior without
owning business facts, content, media, navigation decisions, or Brand Assets.

One authoritative Theme adapter styles the existing semantic component
renderer. Composition source identity now includes the selected Theme,
selection version, token-contract version, and canonical token checksum, so
Theme changes make affected compositions stale until explicitly refreshed.
Theme approval fails closed when required accessibility or contrast checks do
not pass, and Website Readiness now assesses selection, approval, token
validity, accessibility, and composition freshness.

Migration `20260804_0039` adds the Theme and Website Theme selection records.
Atlas Data backup format 0.51 preserves Theme lifecycle and selection history
and exact composition bindings while remaining compatible with supported 0.50
backups. The local Flo-Zone reference Theme demonstrates the reusable contract
without embedding Flo-Zone presentation values in shared component contracts
or Theme services. Page-media planning, AI image generation, complete-site
preview, publication, WordPress rendering, and SiteGround remain deferred.

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
