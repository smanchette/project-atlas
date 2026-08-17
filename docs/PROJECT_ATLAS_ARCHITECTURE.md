# Project Atlas Architecture

**Version:** 1.1

**Status:** Living Technical Blueprint

**Governing document:** `PROJECT_ATLAS_CONSTITUTION.md`

---

## Purpose

This document describes how Atlas is organized and how its major systems should work together. It is intentionally high-level and should evolve as implementation details become clearer.

If an architecture decision conflicts with the Constitution, the Constitution takes precedence.

---

## Architectural Goals

Atlas should be multi-company, multi-site, multi-user, multi-industry, role-based, secure, auditable, recoverable, modular, testable, portable, SaaS-capable, and ready for responsible AI integrations.

Flo-Zone is the first proving ground, not the permanent boundary of the architecture.

---

## Core Domain Model

Atlas should treat these as distinct, related concepts:

- Organization
- Company
- Brand
- Website
- User
- Role
- Permission
- Service
- Industry
- County
- City
- Location
- Service area
- Page
- Page type
- Page relationship
- Form component
- Form-delivery-mode revision
- Form-recipient revision
- Submission envelope
- Delivery outbox record
- Delivery attempt
- Keyword
- Search intent
- Research source
- Fact
- Claim
- Assumption
- Knowledge item
- Media item
- Template
- Content draft
- Approval
- Deployment
- Backup
- Audit record
- Recovery operation
- Maintenance task

Each record should belong to the correct company and website context. Cross-company access must be explicit and controlled.

---

## Major System Boundaries

### Company and Website Management

Organization identity, company identity, brands, contact details, websites, site settings, publishing destinations, tenancy, users, and roles.

### Services and Geography

Services, industries, counties, cities, locations, service areas, service-to-location relationships, coverage rules, and legitimate page opportunities.

### Research Engine

Company, competitor, location, regulation, customer-concern, and source research; research gaps; uncertainty; and source metadata.

### Knowledge System

Verified facts, approved claims, assumptions, unresolved questions, provenance, confidence, effective dates, and company, industry, location, and operational knowledge.

### Site Architecture and SEO Planner

Website structure, page inventory, page types, relationships, keyword targets, search intent, coverage gaps, duplicate and cannibalization detection, internal links, navigation, and expansion planning.

### Content Generation Engine

Page briefs, long-form content, localized content, FAQs, calls to action, trust elements, titles, meta descriptions, schema, supporting articles, updates, and rewrites.

Generation should be knowledge-grounded, company-specific, location-aware, non-duplicative, reviewable, and versioned.

### Media Engine

Image requirements, prompts, generated and uploaded media, featured and inline images, alt text, captions, approvals, WordPress mappings, and media QA.

### Template and Layout System

Site-wide design rules, page templates, components, layout variants, brand application, reusable blocks, and controlled variation.

### Website Builder Core

One shared Website Builder Core owns the reusable complete-site engine: Websites, Pages, content, Theme Families and Theme Versions, component configuration, media governance, SEO, navigation, form presentation and field contracts, provider-neutral submission envelopes, publishing and deployment adapters, and Website-scoped integration configuration.

The same core supports both the complete standalone Atlas Website Builder product and the optional Website Builder module included with AtlasOps360. Neither product is a prerequisite for the other. The core must not fork, and a standalone Atlas Website must be connectable to AtlasOps360 later without rebuilding the Website.

### Form Presentation and Delivery

Form presentation and form delivery are separate responsibilities. Themes own presentation and component compatibility. Website configuration owns one explicit delivery-mode revision and, where required, its destination for each form component. Revision records are immutable, and each Website/form chain has exactly one current head. Providers own their provider-specific delivery or embedded-form behavior.

The supported Website/form-scoped modes are exactly `disabled`, `atlas_email`, `provider_owned`, `atlasops360_native`, and `external_adapter`. A mode must never be inferred from a Theme, customer-portal setting, provider presence, or another mode, and no mode may silently fall back to another. Missing configuration fails closed.

Atlas-owned delivery modes use one normalized submission-envelope contract and provider adapters. Website/form-scoped recipient revisions and the minimum safe outbox and immutable attempt evidence support reliable Atlas email delivery without turning Atlas into a CRM, lead pipeline, customer system, scheduling system, or AtlasOps360 substitute. Each delivery-mode revision owns the exact current heads of its immutable recipient chains. Initial recipient roots and same-mode address, enabled-state, role, or verification successors may be appended only while that email-mode revision is current and has no submission evidence. A first submission or delivery-mode successor freezes that snapshot; recipient heads may then be carried forward only to the directly superseding email-mode revision. Production customer values must not be retained in plaintext; production persistence remains unavailable until approved encryption and key management exist.

`atlas_email` is the universal standalone delivery option. `provider_owned` permits an approved provider to own submission receipt, delivery, retention, and provider-side notifications while Atlas owns only safe presentation, configuration, readiness, audit, and fail-closed behavior. `atlasops360_native` is a future optional first-party adapter. `external_adapter` requires an installed approved adapter. GorillaDesk is one possible provider-owned-form example, not a core dependency.

### Quality Assurance System

Fact validation, claim validation, content structure, word count, duplicate and cannibalization checks, brand and contact verification, service-area validation, media, metadata, schema, internal links, visual checks, and human approvals.

### Approval Workflow

Research, knowledge, site architecture, content, media, deployment, publication, and exception approvals.

### WordPress Integration

Authentication, exact-origin validation, categories, pages, posts, slugs, media, featured images, metadata, schema, draft and publish state, plugin integration, read-only verification, and controlled writes.

### Deployment Engine

Deployment planning, preflight gates, backup requirements, one-time handles, confirmation phrases, atomic apply operations, post-deployment verification, failure handling, recovery, and audit history.

### Rendering and Verification

Public acquisition, authenticated inspection, DOM identity, visible-content identity, metadata, schema, media, privacy, provider, origin, and visual verification.

Durable content identity should remain distinguishable from volatile transport and cache behavior.

### Backup and Recovery

Atlas Data, Media, and Program backups; external hosting backups; backup identity and freshness; restore validation; rollback plans; recovery workflows; and historical preservation.

### Audit and History

Who acted, what changed, why it changed, which authorization allowed it, which backups protected it, which evidence verified it, which checks passed or failed, and how recovery occurred.

### Operator Dashboard

Companies, websites, services, locations, research, knowledge, site plans, content, media, QA, approvals, deployment, recovery, maintenance, users, and roles.

### Website Maintenance Engine

Freshness, page refreshes, coverage expansion, link checking, metadata and media repair, deployment drift, missing coverage, versions, and controlled updates.

---

## Cross-Cutting Platform Services

### Authentication and Authorization

User authentication, company membership, site access, role-based permissions, high-risk operation controls, and session management.

### Security

Secret isolation, credential-memory boundaries, exact-origin enforcement, least privilege, input validation, output sanitization, auditability, secure customer-submission handling, and secure backups. Website configuration may reference protected credentials but must never contain their secret values.

### Storage

Relational business data, structured knowledge, media, backups, versioned artifacts, and audit records.

### AI Services

Provider abstraction, model and prompt configuration, cost controls, grounding, structured outputs, evaluation, safety, and quality gates.

### Observability

Logs, metrics, health checks, deployment status, error classification, and operator-readable diagnostics.

### Testing

Unit, integration, migration, backup/restore, network-isolated, WordPress contract, deterministic artifact, and end-to-end tests.

---

## Multi-Tenant and Multi-Site Rules

- Company-owned records should carry explicit company or organization boundaries.
- Website-owned records should carry explicit site boundaries where appropriate.
- Shared knowledge must be explicitly classified as shared.
- Company-private knowledge must not leak across tenants.
- Authorization checks must occur at service and API boundaries.
- Backups and restores must preserve tenant boundaries.
- Audits must identify the affected company and site.
- Templates may be shared, but content and company facts must remain isolated.
- Form-delivery modes, recipients, policy references, and destinations must be scoped to the exact Website and form component.

---

## Data Ownership and Portability

Atlas should preserve the customer's ability to export company data, website data, content, media, structured knowledge, and appropriate audit history; move to another hosting environment; and restore from backups.

Atlas should not depend on artificial lock-in.

---

## Integration Boundaries

### Auto Blog Builder

Potential shared services include AI providers, media generation, approved knowledge, topic planning, QA, storage, and auditing. The products should remain independently operable.

### AtlasOps360

AtlasOps360 includes an optional Website Builder module backed by the same Website Builder Core used by standalone Atlas. AtlasOps360 may add native lead creation, notifications, assignment, follow-up, customer records, communications history, scheduling, estimating, reporting, and attribution around that core, but it does not own, absorb, replace, or fork it.

The integration is optional and first-party. The Website Builder Core must have no hard runtime dependency on an AtlasOps360 account, database, authentication system, deployment, or subscription, and the products must not assume shared database access. Stable contracts, service boundaries, adapters, or APIs carry approved information between them; cross-product table access is prohibited. External operational systems, including GorillaDesk and other CRM or field-service providers, remain optional.

Form delivery is distinct from customer-portal routing. Future AtlasOps360-native form delivery receives the provider-neutral submission envelope through its adapter boundary only when explicitly selected and configured for that Website and form.

---

## Long-Term Intelligence Architecture

The opt-in intelligence network should include explicit participation, anonymization, tenant isolation, structured contributions, provenance, confidence, observation-versus-guidance classification, aggregation, privacy controls, governance, withdrawal and retention rules, and responsible AI access.

It must not be retrofitted through uncontrolled sharing of company data.

---

## Current Technical Direction

Atlas currently uses a backend application, frontend application, PostgreSQL, Docker Compose, runtime release manifests, versioned migrations, WordPress REST integration, Atlas WordPress plugins, Program/Data/Media backups, guarded lifecycle operations, and evidence and verification workflows. Its Website Builder and form-delivery foundation remains provider-neutral and keeps all production form providers and customer-submission paths disabled until their independent readiness requirements are satisfied.

Exact implementation details should remain in technical references and code rather than overloading this high-level document.

---

## Architectural Decision Rule

Before changing architecture:

1. Read the Constitution.
2. Identify the company, site, user, and data boundaries affected.
3. Identify the current milestone.
4. Preserve future expansion.
5. Avoid unnecessary coupling.
6. Preserve security, auditability, backup, recovery, and portability.
7. Document major decisions.
8. Stop for explicit approval before changing the Constitution.

This Architecture document should evolve as Atlas grows.
