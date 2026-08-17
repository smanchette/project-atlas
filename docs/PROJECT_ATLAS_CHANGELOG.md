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

## Website-Scoped Approved Navigation Population and Visitor-Journey Foundation

Added Website- and Site-Plan-scoped approved primary, utility, and footer
navigation together with explicit internal-link visitor journeys. Operator
decisions retain rationale, identity, version, timestamp, and optional exact
suggestion provenance, while Atlas-generated suggestions remain separate from
approved decisions.

Navigation and link validation now fails closed for cross-Website references,
self-links, duplicates, cycles, inactive parents, missing targets, broken
conversion paths, and under-governed records. Composition previews resolve
approved navigation and internal links to exact local Generated Page previews
without rewriting stored page content.

Migration `20260805_0040` adds decision provenance to navigation sets, items,
and internal-link intents. Atlas Data backup format 0.52 preserves the durable
graph and exact suggestion bindings while retaining supported 0.51 restore
compatibility. Website Readiness now assesses approved navigation, visitor
journeys, and composition freshness.

This milestone does not insert links into content, render or publish WordPress
menus, modify page content, implement media or complete-site preview, publish,
deploy, or access WordPress, SiteGround, or other production systems.

---

## Website-Scoped Page-Media Planning and Provenance Foundation

Added Website-, Site-Plan-, and Planned-Page-scoped media planning with
versioned Atlas suggestions and separate, explicit operator placement
decisions. Reusable page-type contracts define purposeful semantic-component
placements, customer outcomes, subject and responsive guidance, accessibility
intent, source constraints, reuse policy, and replacement policy without
embedding Flo-Zone files or treating image quantity as a quota.

Ordinary page media can now carry exact managed-binary identity, Website and
Business ownership, provenance, rights, approved and prohibited usage,
accessibility intent, approval lifecycle, replacement and retirement history,
and privacy-safe GPS authorization state. Approval re-reads the managed
original and derivatives and fails closed on unsafe paths, binary drift,
signature or MIME disagreement, missing governance, or unverified location
metadata. Governed assignments bind exact media and placement versions to one
Website, Site Plan, Planned Page, Generated Page, and operator decision.

Page-media plan and assignment identities participate in composition source
freshness. Required missing or incompatible media blocks governed composition
refresh, while advisory, excluded, and deferred placements remain accurately
nonblocking. Existing media and assignments remain unchanged and are not
silently granted ownership, provenance, rights, or approval. Website Readiness
now reports Page Media coverage, decisions, required assignments, governance,
compatibility, composition freshness, and page-type coverage.

Migration `20260807_0041` adds the planning, governance, and assignment fields.
Atlas Data backup format 0.53 preserves the new lifecycle and version bindings
while retaining supported 0.52 restore compatibility. This milestone imports,
generates, approves, and assigns no new Flo-Zone page media and performs no
WordPress, SiteGround, publication, deployment, Theme, Brand Asset, Website
Identity, navigation, or content operation.

---

## Website-Scoped Media Authorization and Canonical Role Safety Foundation

Added typed, versioned, Website- and Site-Plan-scoped media authorizations that
bind the exact Planned Page, optional Generated Page, media requirement and
version, placement contract, approved asset version and checksum, optional
assignment, operator decision, lifecycle, and supersession history. Enforceable
reuse policies now fail closed across candidate discovery, assignment and
replacement, composition, QA, approval, export, and publication preparation;
free-text rationale does not grant authority or broaden use to another page or
Website.

Established canonical semantic media-role resolution from the complete
versioned page-type placement contract while preserving exact stored placement
identity. Migration `20260810_0044` adds the durable authorization records and
asset authorization mode. Atlas Data backup format 0.56 preserves exact
authorization and supersession graphs while retaining supported 0.55 restore
compatibility.

All existing Atlas page, plan, composition, QA, identity, navigation,
legacy-media, WordPress, audit, deployment, and verification state remained
unchanged. This milestone imported, approved, assigned, generated, or modified
no image and performed no WordPress, SiteGround, publication, deployment, or
external-provider activity.

---

## Performance Local Theme Foundation v1

Added the Website-independent, source-defined `performance-local` Theme Family
as a local `preview_candidate`, while retaining the existing raw presentation
as an internal diagnostic adapter. An operator-authorized, public read-only
audit of the operator-owned reference website informed reusable conversion
patterns without copying its source, assets, plugins, or unsafe overlapping
controls.

Performance Local maps current governed semantic composition, navigation,
identity, content, and exact page-media bindings into modular header,
dropdown/drawer navigation, visual hero, trust, split-media, card, FAQ, CTA,
preview-form, footer, and responsive conversion contracts. Optional campaign,
review, statistic, video, map, community, and language capabilities fail closed
when their required approval, rights, provenance, routing, privacy, or provider
configuration is absent. Sticky behavior reserves responsive safe space, and
the compact estimate form is inert in Theme Lab: it sends, stores, and logs no
visitor data.

This milestone adds no durable Theme, component, or selection record; changes
no Atlas database, schema, composition, QA, content, navigation, media, or
identity state; and performs no WordPress, SiteGround, publication, deployment,
or production operation.

---

## Performance Local Conversion Theme v2

Advanced the Website-independent, source-defined `performance-local` Theme
Family to version 2 while retaining its `preview_candidate` lifecycle and
`productionReady: false` boundary. A renewed public read-only review of the
operator-owned reference website informed deeper conversion parity without
copying its content, claims, assets, source, plugins, widgets, prices, contact
details, or unsafe fixed-control behavior.

Performance Local v2 strengthens the governed header, campaign, hero, trust,
split-media, source-preserving numbered-process, related-page, FAQ, final-call-
to-action, inert estimate-form, mobile-action, footer, and back-to-top
presentation. Mobile conversion actions now respond to hero visibility, menu
state, and form focus rather than competing with the visitor's current task.
An isolated, demo-only optional-component gallery retains the enabled campaign
example and now pairs unmistakably synthetic, contract-valid enabled
presentations with resolver-backed fail-closed states for review, statistic,
video, map, community, and language capabilities. The gallery adds no public
facts, registered routes, provider integrations, requests, storage, or
production-renderer output. Theme Lab reports activation-readiness gaps
explicitly and cannot activate or persist a Theme.

This milestone creates no durable Theme, selection, component configuration,
or Atlas record; changes no database, schema, composition, QA, content,
navigation, media, identity, or export state; and performs no WordPress,
SiteGround, publication, deployment, or production operation.

---

## Durable Performance Local Theme and Conversion Configuration Foundation

Added a generic durable Theme-family architecture separating reusable Theme
identity and version contracts from Website activation. Migration
`20260813_0045` adds governed Theme Family, Theme Version, Website
configuration, component-revision, and immutable audit records. Performance
Local remains version 2, `preview_candidate`, `productionReady: false`, and
bound to source commit `1b766664ea99d923195bbf98e8a1e4d833b50084`.

Theme Lab now renders an explicitly requested durable draft as `DRAFT PREVIEW
— NOT ACTIVE`. The Website-scoped configuration supports one evergreen
“Request an Estimate” banner, sticky governed Call and Request Estimate
actions, and one inert compact estimate form with exactly five fields. The
form remains provider-disabled, collects and submits no data, and stores no
credentials or delivery destination.

Atlas Data backup format 0.57 preserves Theme-family identity, versions,
inactive Website configurations, component lineage, lifecycle evidence,
fingerprints, audits, and provider-disabled state. Restore remains fail-closed
and inactive; draft or preview-candidate configurations are ineligible for
public export.

The authorized active-local mutation created exactly one Website-independent
Performance Local family, one version-2 record, one inactive Flo-Zone Website
draft, three component configurations, and their six required immutable audit
records. Existing Theme 1 and active selection 1, Page 41 composition and QA
identities, and governed media remained unchanged. No Theme was activated, no
provider was enabled, and no WordPress, publication, deployment, or
customer-data operation occurred.

---

## Performance Local v3 Delivery and Form Gateway

Added a distinct source-defined Performance Local version-3 preview candidate
without changing the durable version-2 contract or activating a Theme. The V3
delivery contract resolves active, explicit local-preview, and disposable
rehearsal modes server-side; validates current composition, QA, media, scope,
component, audit, and selection evidence; and renders the evergreen estimate
banner as one accessible action when its configured message and call to action
are semantically equivalent.

Added a provider-independent, fail-closed form gateway with bounded raw JSON
handling and explicit privacy, consent, retention, spam, security, audit,
success, and failure readiness. Production provider, spam, and idempotency
registries remain empty. Test delivery is isolated to guarded disposable
rehearsals, and no form value is stored, logged, reflected, or sent externally
when the production boundary is unavailable.

Added zero-write activation planning plus disposable activation, full-site
rendering audit, internal export, and exact rollback rehearsal. A clean-install
migration audit proved the safe identifier-only repair candidates for historical
PostgreSQL index names and contained a separate historical constraint-expression
compatibility blocker; no historical migration was changed. Active Atlas retains
its existing Theme selection and durable V2 draft, contains no V3 durable row,
and received no customer data, WordPress, publication, or deployment action.

---

## PostgreSQL Canonical Schema Convergence

Implemented fail-closed Alembic revision `20260815_0046` to converge the two
accepted PostgreSQL 16 revision-0045 schema variants—a repaired clean install
and the active-style Atlas schema—onto one frozen semantic manifest. The
revision makes the three formerly runtime-created WordPress metadata and
quality-review tables and their sequences Alembic-owned; converges canonical
types, UTC timestamp semantics, server defaults, CHECK constraints, indexes,
and sequence ownership; preserves the `deferred` drafting-disposition
vocabulary; rejects unknown source variants before mutation; and intentionally
refuses downgrade before mutation.

Preserved the deterministic identifier-only corrections in migrations `0020`,
`0022`, and `0023` and the narrow PostgreSQL CHECK-expression compatibility
repair in migration `0041`. Application startup now respects Alembic ownership,
while Backup 0.57 restore and Page Composition currentness use stable UTC source
identity and require complete authoritative source and generated-component
equality before preserving composition identity.

Focused migration and model tests and guarded PostgreSQL 16 catalog evidence
established frozen clean-0045, active-0045, and canonical-0046 identities with
no declared row transformation. Revision 0046 has not been applied to active
local Atlas; active-local migrations and application-row mutations remain
zero.

---

## Shared Website Builder Core and Universal Form Delivery Foundation

Updated the Architecture, Complete Website Blueprint, Product Specification,
and Roadmap to version 1.1. The governing model now defines Atlas Website
Builder as both a complete standalone product and an included, optionally
integrated AtlasOps360 module backed by one non-forked Website Builder Core.
AtlasOps360 may consume stable core contracts through a one-way adapter,
service, or API boundary, but the core requires no AtlasOps360 account,
database, authentication system, deployment, or subscription. GorillaDesk and
other operational systems remain optional providers.

Added one provider-neutral, Website/form-scoped delivery foundation with
exactly five explicit modes: `disabled`, `atlas_email`, `provider_owned`,
`atlasops360_native`, and `external_adapter`. Mode revision records are
immutable, and each Website/form chain has exactly one current head. Durable
recipient revisions, one normalized five-field submission envelope, the
existing form gateway and provider
registry, and fail-closed readiness prevent Theme or portal inference and
prohibit fallback between modes. Atlas email is the universal standalone path;
AtlasOps360-native delivery remains a future optional first-party adapter, and
provider-owned forms keep submission receipt, delivery, retention, and
notifications with the selected provider.

Migration `20260817_0047` adds the additive form-delivery configuration,
envelope, outbox, immutable attempt, and configuration-audit records. Atlas
Data backup format 0.58 preserves their dependency graph and remains compatible
with supported 0.57 data. The outbox retains only minimum safe delivery
evidence and does not create a lead inbox, customer system, sales pipeline,
scheduling system, estimating workflow, or CRM. Because Atlas has no approved
production customer-payload encryption and key-management boundary, production
payload persistence and delivery remain blocked rather than storing plaintext.

Production provider registrations and transports remain empty or disabled;
test adapters are confined to disposable, network-isolated rehearsal. No form
mode or recipient was seeded into active Atlas, Performance Local V3 remains
inactive, and no Theme version 4 was created. Active local Atlas remains at
revision `20260815_0046`; no email was sent, no customer data was collected,
and no AtlasOps360, GorillaDesk, WordPress, publication, or deployment request
occurred.

---

## Atlas-Managed Form Field Limit

Updated the Architecture, Complete Website Blueprint, Product Specification,
and Roadmap to version 1.2. Atlas-rendered `atlas_email`,
`atlasops360_native`, and `external_adapter` forms now retain five fixed,
ordered default customer-entry fields—Name, Phone, ZIP code, Requested
Service, and Optional Message—and may add no more than one governed optional
sixth field. A seventh field, more than one additional field, duplicate or
reserved keys, and incompatible definitions or values fail closed without
silent dropping, selection, or conversion to metadata.

The optional sixth-field contract is immutable, provider-neutral, and limited
to controlled `email`, `short_text`, `dropdown`, `radio`, `checkbox`, `date`,
and `textarea` types. Its normalized value and exact definition revision extend
the existing submission envelope and adapter mapping without allowing arbitrary
extra keys.
Provider-owned forms remain exempt, and privacy, consent, anti-abuse, security,
idempotency, audit, and routing controls do not count as customer-entry fields.

Backup and restore preserve the exact optional-field definition, choices,
ordering, validation, mapping, identity, and fingerprint and reject seven-field
or integrity tampering. Theme Lab provides a synthetic operator-only review of
the five-field default, valid sixth field, rejected seventh field, reserved-key
rejection, controlled choices, and responsive layout under
`DEMO CONFIGURATION — NOT ACTIVE`; it has no submission, persistence, storage,
network, provider, or activation control. No migration or backup-format advance
was required. Active local Atlas remained at revision `20260815_0046` with no
application-row mutation. No active form mode was seeded, no customer data was
collected, and no email or provider request was sent.

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
