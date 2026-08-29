# Project Atlas Roadmap

**Version:** 1.2

**Status:** Active Planning Document

**Governing document:** `PROJECT_ATLAS_CONSTITUTION.md`

---

## Purpose

This roadmap describes what Atlas is building next and how the project will move from its current foundation into a complete business website creation and management platform.

The Roadmap is expected to change as the project advances. If the Roadmap conflicts with the Constitution, the Constitution takes precedence.

---

## Current Product Direction

Atlas has left the architecture-building phase and is ready to make websites. The current phase is website-production-first, beginning with controlled Flo-Zone WordPress staging.

The immediate product milestone is:

> **Atlas can take a company's information, branding, services, and service areas and generate a complete, review-ready WordPress website with high-quality content, media, local SEO structure, deployment verification, and quality assurance.**

The architecture must remain compatible with multi-company, multi-site, multi-user, multi-industry, role-based, secure, auditable, and future SaaS operation.

Atlas Website Builder remains a complete standalone product and is also an
included, optionally integrated AtlasOps360 module. Both paths use one
non-forked Website Builder Core. AtlasOps360 and external operational software
remain optional, and deeper integrations must use stable adapters, service
boundaries, or APIs rather than shared database access.

---

## Phase 1: WordPress Foundation Ready for Website Production

### Objective

Maintain the Bootstrap, Metadata Bridge, rendering, verification, recovery, and audit foundation required for safe website production without reopening generalized infrastructure work.

### Historical pre-staging checkpoint

The following checkpoint is retained as historical context and is not the current production state:

- Runtime: v0.59.93
- Audit ID 1: `authorization_retired`
- Audit ID 2: `recovery_required`, awaiting guarded reconciliation
- Bootstrap 0.3.0: active
- Metadata Bridge: active at 0.57.6
- Rendering: disabled
- WordPress content and settings: unchanged

### Current status

- The guarded foundation required to begin controlled website production is complete.
- Performance Local V5 is the approved presentation; no V6 is required.
- Metadata Bridge 0.57.9 is the current staging target. Version 0.57.8 introduced the contained V5 renderer, and 0.57.9 added WordPress-native email delivery within the same plugin family.
- Additional infrastructure remains deferred unless the website-production workflow proves it necessary.
- No Metadata Bridge 0.57.9 staging installation or activation, V5 registration or selection, real form delivery, publication, or deployment has occurred.

---

## Phase 2: Complete the Full Flo-Zone Website

### Objective

Use Flo-Zone Pest And Termite Solutions Inc. as the first complete real-world website produced and managed through Atlas.

### Current status and immediate priority

- The active automatic CTA correction is complete for 55 City-Service pages. The ten non-City-Service pages were excluded, and the final all-corrected replay returned `UNCHANGED` with zero persistent changes. This milestone is permanently closed; no further replay is planned.
- Page 41 is the completed City-Service media pilot. Its current QA identity must be re-queried during staging work before it is called staging-ready.
- Media placement remains for 54 additional City-Service pages; Page 41 media must not be reused automatically.
- The ten non-City-Service pages still need a practical staging and rendering decision. The full set of 65 pages has not been rendered through V5 or declared publication-ready.
- The immediate sequence is Flo-Zone WordPress staging; Metadata Bridge 0.57.9 installation and activation; V5 registration and selection; Page 41 rendering and visual review; real staging form configuration; one controlled receipt test; and a first small website-production batch.
- Governed content and media scale only after the first batch is approved. No staging installation, real form delivery, publication, or deployment has occurred.

### Required scope

- Home page
- About page
- Contact page
- Core drywood-termite tenting service pages
- Other approved service pages
- County pages
- City pages
- Service-by-city pages where useful
- Supporting informational pages
- FAQs
- Calls to action
- Trust and credibility elements
- Conversion content
- Internal linking and navigation
- Images and media
- Titles and meta descriptions
- Structured data
- Draft review
- Publishing
- Post-publication visual verification

### Local coverage

Build legitimate coverage throughout Orange, Seminole, Volusia, Lake, and Flagler Counties without repetitive doorway pages or fabricated local details.

### Completion conditions

- Complete agreed site structure exists
- Required pages pass research, content, media, metadata, schema, and visual QA
- Navigation and internal links are intentional
- Draft and publish workflows are proven
- Deployment verification is complete
- Rollback and audit history remain intact

---

## Phase 3: Repeatable Company Onboarding and Website Generation

### Objective

Turn the Flo-Zone process into a reusable workflow for a new company.

### Foundation implemented locally

The Website Context and Business Identity Foundation now provides additive
Business-to-Brand-to-Website ownership, one Website Identity record per
website, and one website-scoped context for page queueing, draft generation,
export, editing, repair, and preview. Flo-Zone remains seeded reference data,
and an isolated fictional-company fixture proves that reusable workflows can
select another website without source customization or identity leakage.

This foundation does not complete company onboarding, site planning, themes,
navigation, provider abstraction, or second-company deployment.

### Website-scoped planning foundation implemented locally

Website-owned Site Plans and Planned Pages now define the planning boundary
before content generation. Initial page types cover Home, About, Contact,
Service, County or service area, City or local area, City-Service, and
Informational or FAQ pages. Each Planned Page has an automatically generated,
operator-reviewable Planning Record based on approved Website Context and
knowledge. Confidence and missing-information recommendations remain advisory
and nonblocking.

Existing Flo-Zone generated pages are backfilled without changing their
content or lifecycle history. Page slugs, queueing, batch generation, QA,
approval, WordPress-draft review, and bulk export now enforce Website
boundaries. Content generation for the new page types and second-company
deployment remain future milestones. Subsequent local foundations now cover
navigation, semantic components, Themes, media governance, and the
provider-neutral form-delivery contracts described below.

### Universal form-delivery foundation implemented locally

The shared Website Builder Core now defines one provider-neutral,
Website/form-scoped delivery subsystem for both standalone Atlas and the
optional AtlasOps360 Website Builder module. Its immutable configuration
supports exactly `disabled`, `atlas_email`, `provider_owned`,
`atlasops360_native`, and `external_adapter`, with no Theme inference, portal
conflation, or fallback between modes. Atlas email is the universal standalone
path; provider-owned forms, future AtlasOps360-native delivery, and approved
external adapters remain explicit alternatives.

The foundation includes immutable mode revisions with one current chain head
per Website/form, revisioned recipient configuration, one normalized envelope
with five fixed defaults and at most one governed optional sixth field,
fail-closed provider readiness, and only the safe outbox and immutable attempt
evidence needed for reliable delivery. It is not a lead inbox, sales pipeline,
scheduling system, customer system, or CRM.
Production provider registrations, transports, and customer-payload storage
remain unavailable until their independent recipient, policy, anti-abuse,
idempotency, encryption, key-management, secret, adapter, and activation gates
are satisfied. No active Website/form mode is selected by this foundation.

Atlas-rendered `atlas_email`, `atlasops360_native`, and `external_adapter`
forms retain the exact ordered Name, Phone, ZIP code, Requested Service, and
Optional Message defaults and may add no more than one governed optional
customer-entry field. A seventh field fails closed. Provider-owned field counts
remain with the provider, while privacy, consent, anti-abuse, security,
idempotency, audit, and routing controls do not count as customer-entry fields.

### Inputs

- Company identity
- Branding
- Contact details
- Goals
- Services
- Locations and service areas
- Licenses and qualifications
- Trust elements
- Existing website information
- Approved facts
- Research needs
- Media preferences
- Publishing destination
- Form-delivery choice, recipients, policies, and provider or adapter references

### Outputs

- Proposed site architecture
- Research plan
- Knowledge gaps
- Page inventory
- Content plan
- Media plan
- SEO structure
- Draft website
- QA results
- Approval workflow
- Publishing and verification plan
- Form-delivery readiness plan

### Completion conditions

- A new company can be added without modifying core source code
- Company, site, service, and location data remain separate
- Work can resume from a saved state
- Missing information and blocked steps are clear
- Each form component has one explicit Website-scoped mode with no implicit fallback
- The result is a complete website, not unrelated pages

---

## Phase 4: Second Company Proof

Build a complete website for a second company to prove Atlas is reusable across companies, brands, services, and industries without a major architectural rewrite.

---

## Phase 5: Operator Dashboard

Add a clear interface for company management, site management, research review, site planning, content and media review, form-mode and delivery-readiness review, QA, approvals, deployment, recovery, saved progress, and user roles.

---

## Phase 6: Quality, Speed, and Template Expansion

Improve generation speed, research quality, content consistency, media quality, template variety, duplicate detection, cannibalization detection, internal-link planning, visual QA, and operator clarity.

Templates should create efficiency without making websites identical.

---

## Phase 7: Website Maintenance

Add controlled workflows for content freshness, page refreshes, service and location expansion, link checking, metadata and media repair, deployment drift, missing coverage, versions, and safe updates.

---

## Phase 8: Multi-Company SaaS Expansion

Future capabilities include hosted deployment, tenant management, advanced roles, billing, usage controls, organization policies, scaled storage and backup, monitoring, support, compliance, and data controls.

These should not delay the first complete website-generation milestone.

---

## Phase 9: Product-Family Integration

### Auto Blog Builder

Potential collaboration includes supporting articles, topic expansion, shared approved knowledge, media services, QA, storage, and auditing.

### AtlasOps360

AtlasOps360 includes the Website Builder as an optional first-party module
backed by the same Website Builder Core as standalone Atlas. The dependency is
one-way: AtlasOps360 may integrate the core, but the core must not require an
AtlasOps360 account, database, authentication system, deployment, or
subscription. Neither product is a prerequisite for the other, the core must
not fork, and a standalone Atlas Website must be connectable later without
rebuilding the Website.

Future deeper collaboration may include company identity, service definitions,
locations, operational knowledge, customer questions, review data, native form
notifications, lead creation and assignment, follow-up, scheduling, estimating,
reporting, and attribution. These capabilities belong around the core and must
cross stable adapter, service, or API boundaries rather than shared tables.
GorillaDesk and other CRM or field-service systems remain optional external
providers, not Atlas or AtlasOps360 prerequisites.

---

## Phase 10: Operational Intelligence Network

Create an opt-in network through which participating companies may contribute anonymized, structured real-world operational information to identify trends, discover gaps, improve recommendations, compare patterns, improve industry knowledge, create competitive advantage, and support responsible AI integrations.

This requires careful privacy, security, anonymization, governance, and data-ownership design.

---

## Deferred Features

These remain part of the long-term vision but should not delay the first useful product:

- Advanced SaaS billing
- Advanced role administration
- Deep analytics
- Automated competitor monitoring
- Complex recommendation systems
- Large reporting dashboards
- Deeper AtlasOps360 operational integration
- Advanced maintenance automation
- Large-scale intelligence-network expansion

---

## Roadmap Decision Rule

Before adding a milestone, ask:

1. Does it comply with the Constitution?
2. Does it help Atlas create or maintain complete business websites?
3. Is it necessary now?
4. Does it preserve multi-company, multi-site, multi-user, and multi-industry expansion?
5. Can it wait until after the first complete website milestone?

The Constitution always takes precedence over this Roadmap.
