# Project Atlas Architecture

**Version:** 1.0

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

Secret isolation, credential-memory boundaries, exact-origin enforcement, least privilege, input validation, output sanitization, auditability, and secure backups.

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

---

## Data Ownership and Portability

Atlas should preserve the customer's ability to export company data, website data, content, media, structured knowledge, and appropriate audit history; move to another hosting environment; and restore from backups.

Atlas should not depend on artificial lock-in.

---

## Integration Boundaries

### Auto Blog Builder

Potential shared services include AI providers, media generation, approved knowledge, topic planning, QA, storage, and auditing. The products should remain independently operable.

### AtlasOps360

Potential shared services include company identity, authentication, services, locations, customer questions, operational knowledge, reviews, storage, backups, auditing, and infrastructure. Operational and website responsibilities should remain clearly separated.

---

## Long-Term Intelligence Architecture

The opt-in intelligence network should include explicit participation, anonymization, tenant isolation, structured contributions, provenance, confidence, observation-versus-guidance classification, aggregation, privacy controls, governance, withdrawal and retention rules, and responsible AI access.

It must not be retrofitted through uncontrolled sharing of company data.

---

## Current Technical Direction

Atlas currently uses a backend application, frontend application, PostgreSQL, Docker Compose, runtime release manifests, versioned migrations, WordPress REST integration, Atlas WordPress plugins, Program/Data/Media backups, guarded lifecycle operations, and evidence and verification workflows.

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
