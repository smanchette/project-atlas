# Project Atlas Product Specification

**Version:** 1.2

**Status:** Governing Product Specification

**Governing document:** `PROJECT_ATLAS_CONSTITUTION.md`

**Related documents:** `PROJECT_ATLAS_ARCHITECTURE.md`, `PROJECT_ATLAS_COMPLETE_WEBSITE_BLUEPRINT.md`, `PROJECT_ATLAS_ROADMAP.md`, `PROJECT_ATLAS_CHANGELOG.md`

---

## 1. Purpose

This Product Specification defines what Project Atlas is capable of doing as a complete business website creation and management platform. It establishes the responsibilities, boundaries, relationships, configuration surfaces, extension points, and implementation goals of the major Atlas subsystems.

This document is implementation-independent. It does not prescribe programming languages, frameworks, database schemas, user-interface designs, infrastructure providers, or content-management systems. Those decisions belong in technical designs and implementation records.

The Complete Website Blueprint defines how Atlas approaches the creation and operation of complete websites. This Product Specification defines the platform capabilities that make that approach possible.

Flo-Zone Pest And Termite Solutions Inc. is the current reference implementation. Its facts, assets, providers, pages, and operational choices are configuration used to validate Atlas. They are not platform requirements.

---

## 2. Relationship to Governing Documents

The Project Atlas governing hierarchy is:

1. `PROJECT_ATLAS_CONSTITUTION.md` — permanent mission, values, and highest design authority.
2. `PROJECT_ATLAS_ARCHITECTURE.md` — platform boundaries, major domains, and cross-cutting architectural rules.
3. `PROJECT_ATLAS_COMPLETE_WEBSITE_BLUEPRINT.md` — principles and operating model for complete business websites.
4. `PROJECT_ATLAS_PRODUCT_SPECIFICATION.md` — product capabilities and subsystem contracts.
5. `PROJECT_ATLAS_ROADMAP.md` — implementation sequence and current priorities.
6. `PROJECT_ATLAS_CHANGELOG.md` — historical record of material decisions and milestones.

The Constitution takes precedence in any conflict. This Specification must remain consistent with the Architecture and Blueprint. The Roadmap may defer capabilities defined here, but it must not silently remove them. The Changelog records changes without creating requirements.

Implementation documentation may refine a subsystem contract, but it may not weaken its governing boundary without an approved update to the appropriate governing document.

---

## 3. Product Vision

Atlas is a multi-company, multi-website, multi-brand platform that turns verified business knowledge, approved content, governed media, and explicit design configuration into complete, reviewable, deployable, verifiable, and maintainable business websites.

Atlas must be capable of:

- modeling a business without coupling facts to a specific page or design;
- planning a complete website as a connected system;
- producing grounded content and media through controlled workflows;
- supporting multiple themes, providers, rendering environments, and publishing destinations;
- reviewing and approving consequential work;
- deploying changes with bounded authority, verification, audit, and recovery;
- maintaining websites after publication;
- observing search, AI discovery, reviews, analytics, competitors, and website health without treating observations as verified facts;
- integrating with operational systems without absorbing private operational data into public content; and
- expanding into hosted, multi-tenant, white-label, mobile, desktop, API, plugin, and software-development-kit products.

The first complete Flo-Zone website proves these capabilities in a real setting. A second company must be supportable through configuration and extension rather than a rewrite of the platform.

Atlas Website Builder is both a complete standalone product and an included, optionally integrated AtlasOps360 module. Both paths consume one Website Builder Core. AtlasOps360 may depend on the stable core contracts, but the core must not depend on AtlasOps360, fork for AtlasOps360, or require an AtlasOps360 account, database, authentication system, deployment, or subscription.

---

## 4. Platform Architecture Overview

Atlas is organized into independently governed capability planes:

| Plane | Primary responsibility |
| --- | --- |
| Identity | Organizations, companies, brands, websites, users, roles, and approved business facts |
| Knowledge | Sources, facts, claims, assumptions, questions, provenance, confidence, and approvals |
| Planning | Website scope, content briefs, pages, relationships, navigation, media needs, and discovery goals |
| Experience | Components, themes, layouts, presentation, responsive behavior, and accessibility |
| Media | Brand assets, website identity, images, derivatives, provenance, rights, and approvals |
| Form delivery | Website/form mode revisions, recipients, normalized envelopes, adapter readiness, and minimal delivery evidence |
| Intelligence | Search, AI discovery, health, analytics, competitors, reviews, customer questions, and recommendations |
| Delivery | Provider connections, deployment, rendering, verification, backups, audits, recovery, and maintenance |
| Operations boundary | Customer, job, scheduling, dispatch, and other private operational systems connected only through approved adapters |

Subsystems communicate through explicit contracts. No plane may silently assume ownership of another plane's state. A page may reference a fact, media asset, component, and intelligence recommendation, but those records retain separate identities and approval histories.

Atlas must support operator interfaces, automation, and external APIs over the same governed domain capabilities. No interface receives special permission to bypass approval, tenancy, validation, or audit rules.

---

## 5. Core Domain Model

The core model consists of distinct but related concepts:

- **Organization:** an ownership or tenancy boundary.
- **Company:** a legal or operating business entity.
- **Brand:** a public identity associated with a company.
- **Website:** a governed digital property with its own identity, configuration, content, providers, and lifecycle.
- **User, role, and permission:** the actor and authority model.
- **Business fact:** an approved statement about a company, service, location, qualification, policy, or contact channel.
- **Knowledge item:** sourced information classified as fact, claim, assumption, observation, guidance, or unresolved question.
- **Content item:** audience-facing language derived from approved knowledge for a defined purpose.
- **Page and page relationship:** a planned website unit and its semantic connections.
- **Component, theme, and layout:** presentation definitions that consume content without owning its factual meaning.
- **Form-delivery-mode revision:** the explicit, immutable Website/form choice and readiness configuration for one form component.
- **Form-recipient revision:** a Website/form-scoped, normalized and verification-aware delivery destination that is separate from transport credentials.
- **Submission envelope, outbox record, and delivery attempt:** the provider-neutral submission identity and minimum safe delivery evidence, not a customer or lead record.
- **Media item:** an asset with provenance, rights, approval, and derivative relationships.
- **Intelligence observation:** a time-bound external signal with provider, scope, confidence, and limitations.
- **Provider connection:** a configured integration with an external system.
- **Approval:** an actor-bound decision over a defined object and version.
- **Deployment, verification, audit, backup, and recovery record:** evidence of controlled production operation.
- **Operational reference:** a bounded pointer to private operational data that remains owned by another system.

The following separation is mandatory:

| Domain | Must contain | Must not become automatically |
| --- | --- | --- |
| Business facts | Verified company truth and approved claims | Page copy, design, or intelligence |
| Knowledge | Sourced facts, claims, assumptions, observations, and questions | Approved public content |
| Content | Audience-facing expression with purpose and version | Authoritative business truth |
| Presentation | Components, themes, layouts, and tokens | Content or factual ownership |
| Media | Assets, rights, provenance, and derivatives | Proof of a claim without validation |
| Form delivery | Explicit Website/form mode, destination, recipients, policies, envelope, readiness, and delivery evidence | Theme behavior, portal state, customer records, or CRM workflow |
| Intelligence | Attributed, time-bound signals and recommendations | Verified knowledge or publishing authority |
| Operational data | Private customers, jobs, schedules, and service records | Public website data |

Every company-owned and website-owned record must carry the correct ownership boundary. Cross-company and cross-website reuse must be explicit, authorized, and traceable.

---

## Major Atlas Subsystems

Each subsystem contract defines a durable product responsibility. Current releases may implement only part of a contract. Deferred capability remains an architectural commitment, not a claim of present availability.

## 6. Business Identity Manager

**Responsibility:** Maintain the authoritative, presentation-neutral identity of organizations, companies, services, locations, service areas, contact channels, qualifications, policies, trust evidence, and approved business claims.

**Boundary:** It owns business-fact status, provenance, validity, and approval. It does not own page copy, layouts, media files, analytics, or private customer records.

**Relationships:** Supplies approved facts to knowledge, content, schema, page planning, navigation, deployment verification, and provider integrations.

**Configuration and extensibility:** Supports company-specific fields, industries, validation policies, effective dates, regional requirements, and controlled custom fact types without embedding one company's values in platform logic.

**Implementation goal:** Provide one traceable source of approved business truth across every website and channel. Flo-Zone's identity is configuration within this model.

---

## 7. Brand Assets Manager

**Responsibility:** Manage approved logos, logo variants, brand marks, color references, typography assets, usage rules, source files, ownership, provenance, and replacement history.

**Boundary:** It owns source brand assets and their approvals. It does not own component layouts, page imagery, website icon selection, or business facts.

**Relationships:** Supplies approved assets to Website Identity, Theme and Design, Media, Component Registry, previews, and deployment verification.

**Configuration and extensibility:** Supports multiple brands per company, multiple variants per asset, responsive placement constraints, size and clear-space rules, light and dark treatments, and future brand-asset types.

**Implementation goal:** Allow a brand to evolve without rewriting content or coupling the business to a single theme. Flo-Zone's logos and visual rules remain Flo-Zone configuration.

---

## 8. Website Identity Manager

**Responsibility:** Manage the site-specific identity presented to browsers, devices, social platforms, crawlers, and future application surfaces.

**Boundary:** It owns favicon, browser icon, Apple Touch icon, future PWA icon, Open Graph identity, site-name association, and publication state. It does not own the underlying brand source files or page-specific media.

**Relationships:** Consumes approved Brand Assets and website configuration; supplies identity artifacts to rendering, SEO, social metadata, deployment, and verification.

**Configuration and extensibility:** Supports per-website identity sets, format and dimension requirements, platform variants, fallbacks, versioning, and additional device identity standards.

**Implementation goal:** Make website identity explicit, portable, replaceable, and independently verifiable across multiple sites and brands.

---

## 9. Knowledge Management System

**Responsibility:** Gather, classify, source, review, approve, version, and retire knowledge used by Atlas.

**Boundary:** It distinguishes facts, claims, assumptions, guidance, observations, unresolved questions, confidence, provenance, and effective time. It does not automatically convert research or intelligence into public content.

**Relationships:** Receives verified business facts, research, provider observations, customer questions, and authorized operational insights. Supplies grounded knowledge to content planning, page planning, schema, SEO, media briefs, and quality assurance.

**Configuration and extensibility:** Supports source types, industry vocabularies, confidence models, approval policies, localization, retention, and opt-in shared knowledge with explicit privacy and tenancy rules.

**Implementation goal:** Ensure Atlas can explain why a statement is available for use, who approved it, where it came from, and when it must be reviewed.

---

## 10. Content Planning System

**Responsibility:** Define content purpose, audience, intent, required knowledge, structure, voice, calls to action, trust elements, localization needs, review criteria, and maintenance expectations before drafting.

**Boundary:** It plans content but does not establish business facts, select final presentation, own media, or authorize publication.

**Relationships:** Consumes approved knowledge, page purpose, brand guidance, search intent, customer questions, and intelligence signals. Produces versioned briefs for content generation and human writing.

**Configuration and extensibility:** Supports industry-specific brief types, editorial policies, voice profiles, content providers, AI model adapters, multi-language plans, and human-only workflows.

**Implementation goal:** Make generated or written content deliberate, grounded, reviewable, non-duplicative, and maintainable rather than prompt-driven.

---

## 11. Page Planning System

**Responsibility:** Define the website's page inventory, page types, audiences, service and geography relationships, URL intentions, content dependencies, component needs, media plans, conversion goals, internal relationships, and lifecycle state.

**Boundary:** It owns the plan and relationships, not final prose, rendered layout, media binaries, or publishing-provider records.

**Relationships:** Coordinates Business Identity, Knowledge, Content Planning, Navigation, SEO, Component Registry, Media, approval, deployment, and maintenance.

**Configuration and extensibility:** Supports reusable page-type definitions, company-specific page inventories, legitimate local coverage, custom relationship types, consolidation, replacement, retirement, and multiple CMS targets.

**Implementation goal:** Produce complete, coherent website structures without thin pages, accidental duplication, cannibalization, or provider-specific coupling.

---

## 12. Component Registry

**Responsibility:** Catalog reusable semantic components, their purposes, input contracts, variants, compatibility, accessibility obligations, validation rules, and lifecycle status.

**Boundary:** Components present approved inputs. They do not own business facts, content meaning, media provenance, or provider credentials.

**Relationships:** Receives presentation configuration from themes and approved inputs from content, media, identity, navigation, and portal systems. Supplies compositions to rendering engines and previews.

**Configuration and extensibility:** Supports component families, versioned contracts, multiple design-system implementations, provider-specific render adapters, deprecation, migration, and third-party extensions.

**Implementation goal:** Enable consistent, testable website composition while allowing materially different designs and rendering engines.

---

## 12A. Website Builder Core and Universal Form Delivery

**Responsibility:** Provide the one reusable complete-site engine used by standalone Atlas Website Builder and by the optional Website Builder module included with AtlasOps360. The core owns Websites, Pages, content, Theme Families and Theme Versions, component configuration, media governance, SEO, navigation, form presentation and field contracts, provider-neutral submission envelopes, publishing and deployment adapters, and Website-scoped integration configuration. Its form-delivery subsystem owns explicit mode revisions, recipient revisions, normalized submission contracts, readiness, and the minimum safe outbox and immutable attempt evidence required for reliable delivery.

**Boundary:** AtlasOps360 may consume the core through a one-way dependency, but it may not own, absorb, replace, or fork it. The core has no hard runtime dependency on an AtlasOps360 account, database, authentication system, deployment, or subscription, and integration must not use cross-product table access. Form delivery is not Theme behavior, customer-portal routing, a lead inbox, a sales pipeline, a scheduling or estimating system, or a CRM. Production customer values must not be stored in plaintext and remain unavailable for persistence or delivery without approved encryption and key management.

**Relationships:** Themes own accessible form presentation and component compatibility. Website/form configuration owns exactly one effective revision with one of five modes: `disabled`, `atlas_email`, `provider_owned`, `atlasops360_native`, or `external_adapter`. Providers own provider-specific delivery or embedded-form behavior. Atlas-owned modes use the existing form gateway, one normalized envelope containing the exact five standard fields and at most one governed optional-field value and definition revision, and the single existing provider registry. Provider-owned forms and customer portals remain separate capabilities.

**Atlas-rendered field contract:** Forms using `atlas_email`, `atlasops360_native`, or `external_adapter` have exactly five fixed, ordered defaults: Name (`name`), Phone (`phone`), ZIP code (`postal_code`), Requested Service (`requested_service`), and Optional Message (`message`). They may add zero or one optional sixth customer-entry field after those defaults, for a maximum of six. Its immutable configuration revision includes a stable key, public label, accessibility label, controlled type, required state, fixed sixth display order, applicable maximum length, validation contract, applicable choices, provider mapping key, and optional help text. Allowed types are `email`, `short_text`, `dropdown`, `radio`, `checkbox`, `date`, and `textarea`; dropdown and radio choices each remain one field regardless of choice count.

Optional keys are normalized deterministically before comparison and must not collide with another field or the reserved `name`, `phone`, `postal_code`, `requested_service`, `message`, `consent`, `privacy`, `honeypot`, `captcha`, `idempotency`, `request_id`, `website_id`, `form_id`, `provider_key`, `destination`, `payload`, or `secret` keys. File upload, password, payment-card, banking, Social Security number, medical-information, arbitrary HTML or JavaScript, uncontrolled hidden, raw-provider-payload, secret, and credential fields are prohibited. Blank labels, invalid types, missing choices for dropdown or radio, choices on incompatible types, overlength values, duplicate or normalized-key collisions, unknown submitted keys, a seventh field, or more than one additional field fail closed. An omitted optional sixth value is valid; an omitted required sixth value is not. No extra field is silently dropped, selected, or converted to metadata.

Provider-owned forms are exempt because the provider owns their field definitions and counts. Privacy consent controls, terms acknowledgments, honeypots, CAPTCHA and anti-spam controls, hidden security identifiers, idempotency values, audit metadata, and system-generated routing fields are system or provider controls, not customer-entry questions, and do not count toward the Atlas-rendered maximum. The submission envelope contains the exact five standard fields, zero or one normalized optional value, and the exact field-definition revision, with no arbitrary extra keys; adapters receive that optional value only through the existing provider-neutral mapping contract.

Form-definition creation and revision, readiness, Atlas-rendered resolution, submission-envelope validation, provider mapping, backup validation, restore validation, Theme Lab preview, and public-render eligibility each enforce the limit independently. Backup and restore preserve the exact five standards and optional definition, choices, order, required state, provider mapping, validation, immutable revision identity, and integrity fingerprint and reject seven-field, collision, contract-alteration, or fingerprint tampering.

**Configuration and extensibility:** Configuration records are immutable and revisioned, scoped to the exact Website and form component, and organized as a chain with exactly one current head for that scope. Each delivery-mode revision owns the exact current heads of its immutable recipient chains. Initial recipient roots and same-mode address, role, enabled-state, or verification successors may be appended only while that email-mode revision is current and has no submission evidence. A first submission or delivery-mode successor freezes that snapshot; recipient heads may then be carried forward only to the directly superseding email-mode revision. No mode may be inferred from a Theme, portal setting, provider presence, or another mode, and no mode may silently fall back. `atlas_email` is the universal standalone option and requires independently ready recipients, policies, transport, secret reference, idempotency, and secure payload handling. `provider_owned` supports approved external links, hosted routes, sandboxed iframes, or adapter-controlled embeds with verified origins or destinations, accessibility labels, privacy disclosure, and fixed sandbox and referrer policies where applicable, while rejecting arbitrary HTML or JavaScript, unrestricted origins, embedded secrets, and misleading retention claims. `atlasops360_native` is a future optional first-party adapter. `external_adapter` requires an installed approved adapter. GorillaDesk is one possible provider-owned-form example, not a dependency.

**Implementation goal:** Let every Website choose an explicit form path, including no form, while keeping standalone Atlas complete, allowing later AtlasOps360 connection without rebuilding the Website, and preventing provider or operational dependencies from spreading into the shared core. The current foundation defines contracts and fail-closed readiness; it does not declare any production email transport, provider-owned form, AtlasOps360 adapter, external adapter, or customer-submission path active.

---

## 13. Theme & Design System

**Responsibility:** Define design tokens, typography, color, spacing, sizing, borders, elevation, motion, responsive behavior, layout systems, component mappings, and brand application.

**Boundary:** It governs presentation and does not alter factual meaning, content approval, media provenance, or website structure.

**Relationships:** Consumes brand and website identity configuration; configures registered components and rendering adapters; supplies presentation rules to preview, accessibility, visual QA, and deployment.

**Configuration and extensibility:** Supports multiple design systems, replaceable layouts, per-brand themes, theme inheritance, safe overrides, theme adapters, and future rendering technologies.

**Implementation goal:** Permit a company or website to change its visual system without rewriting facts, content, pages, or media records.

---

## 14. Navigation Manager

**Responsibility:** Manage global, local, utility, footer, breadcrumb, contextual, and conversion navigation as explicit, versioned website structures.

**Boundary:** It owns navigation relationships and labels. It does not infer authorization to create pages, expose disabled features, or publish private operational routes.

**Relationships:** Consumes the approved page graph, audience journeys, portal availability, and website configuration. Supplies menus, internal links, breadcrumbs, and route visibility to components and rendering engines.

**Configuration and extensibility:** Supports multiple navigation sets, responsive variants, localization, role-aware private navigation, provider routes, and complete suppression of disabled optional capabilities.

**Implementation goal:** Make navigation intentional, accessible, testable, and independent of the order in which pages were created.

---

## 15. Media & Image Management

**Responsibility:** Plan, ingest, classify, approve, transform, version, publish, replace, and retire images and other website media.

**Boundary:** It owns asset records, provenance, rights, technical derivatives, accessibility metadata, and usage assignments. It does not invent factual evidence or own page copy.

**Relationships:** Receives plans from Page and Content Planning, brand sources from Brand Assets, and generated candidates from the AI Image Generation Pipeline. Supplies approved variants to components, identity, SEO, deployment, and verification.

**Configuration and extensibility:** Supports configurable image counts, approximately three to five images for substantial pages when appropriate, uploaded and licensed media, responsive formats, crop policies, storage providers, delivery networks, and future media types.

**Implementation goal:** Deliver purposeful, rights-aware, responsive media with traceable provenance. Atlas must never fabricate GPS metadata; verified GPS may be preserved only for legitimate company photographs when authentic, relevant, privacy-safe, and authorized.

---

## 16. AI Image Generation Pipeline

**Responsibility:** Turn approved image requirements into controlled briefs, provider requests, candidate assets, review records, and provenance-rich media submissions.

**Boundary:** It creates candidates, not approved media. It cannot assert that generated scenes, people, equipment, locations, or events are real.

**Relationships:** Consumes page purpose, brand constraints, knowledge, prohibited details, composition requirements, and intended placement. Sends candidates to Media Management and human approval.

**Configuration and extensibility:** Supports multiple AI provider adapters, model selection, cost and usage controls, deterministic brief versions, safety policies, style constraints, watermark or disclosure policies, and provider replacement.

**Implementation goal:** Make AI image production reproducible, reviewable, provider-independent, and incapable of bypassing media approval or provenance.

---

## 17. Structured Knowledge & Schema Engine

**Responsibility:** Map approved entities, facts, claims, page meaning, and relationships into machine-readable structures appropriate to the target channel.

**Boundary:** It represents approved knowledge; it does not create new facts, hide unsupported claims in markup, or override visible content policy.

**Relationships:** Consumes Business Identity, Knowledge, Page Planning, Content, Website Identity, and provider capabilities. Supplies structured outputs to rendering, SEO, deployment, and verification.

**Configuration and extensibility:** Supports schema vocabularies, versioned mappings, industry extensions, multi-language values, channel-specific serializers, validation profiles, and future knowledge-exchange formats.

**Implementation goal:** Keep machine-readable identity consistent with approved public meaning while allowing standards to evolve independently of stored facts.

---

## 18. SEO & Discovery Engine

**Responsibility:** Plan and evaluate search intent, titles, summaries, canonical identity, local coverage, page relationships, internal links, crawlability, duplication, cannibalization, structured discovery, and AI-readable clarity.

**Boundary:** It recommends and validates; it cannot invent business facts, force publication, or prioritize rankings over usefulness and truth.

**Relationships:** Consumes approved knowledge, page plans, content, navigation, structured knowledge, media, search observations, and website configuration. Supplies requirements and findings to planning, QA, maintenance, and intelligence.

**Configuration and extensibility:** Supports Google, Bing, Yahoo, emerging search systems, AI discovery channels, regional markets, language-specific discovery, provider adapters, and evolving standards.

**Implementation goal:** Improve legitimate discoverability while preventing doorway pages, thin content, unsupported localization, and channel-specific manipulation.

---

## 19. Customer Portal Framework

**Responsibility:** Provide optional website entry points to customer-facing operational services while preserving security and product boundaries.

**Boundary:** It manages portal availability, presentation, provider routing, and verified connection state. Customer, job, payment, scheduling, and service records remain owned by the operational provider.

**Relationships:** Uses Provider Adapters, Navigation, Components, Website Configuration, authentication boundaries, and verification. It may connect to GorillaDesk, AtlasOps360, or future providers.

**Configuration and extensibility:** Supports provider selection, per-website enablement, labels, routes, authentication mode, health state, and explicit unavailable behavior. When disabled, a portal must be hidden completely.

**Implementation goal:** Allow portal providers to change without exposing private data to public website generation or coupling navigation to a single vendor. Portal configuration must not select, infer, or substitute for a form-delivery mode.

---

## 20. Provider Adapter Framework

**Responsibility:** Define bounded, replaceable interfaces between Atlas and external providers.

**Boundary:** An adapter translates capabilities and observations. It does not redefine Atlas domain truth, tenancy, approval, security, audit, or recovery rules.

**Relationships:** Serves CMS providers, rendering engines, AI services, image generators, Website form delivery, CRM systems, customer portals, analytics, search, reviews, storage, delivery, authentication, and operational platforms.

**Configuration and extensibility:** Adapters declare identity, version, capabilities, permissions, configuration schema, credential requirements, rate limits, health, failure modes, data classifications, and supported operations.

**Implementation goal:** Support multiple CMS providers, rendering engines, AI providers, CRM integrations, GorillaDesk, AtlasOps360, and future services without spreading provider-specific behavior through core domains or permitting adapters to become implicit form-mode fallbacks.

---

## 21. Intelligence Framework

**Responsibility:** Acquire, classify, normalize, retain, compare, and present time-bound external observations and derived recommendations.

**Boundary:** Intelligence remains distinct from business facts, approved knowledge, content, and operational truth. It cannot publish or promote itself without a governed decision.

**Relationships:** Receives signals from search trends, AI discovery, website health, competitor observations, analytics, Search Console, review monitoring, customer questions, and authorized operational adapters. Supplies attributed opportunities and risks to knowledge review, planning, QA, and maintenance.

**Configuration and extensibility:** Supports provider adapters, scopes, schedules, retention, confidence, regional and language contexts, privacy controls, opt-in aggregation, and explainable recommendation policies.

**Implementation goal:** Grow Atlas's awareness without creating an uncontrolled data-sharing network or confusing observations with verified guidance.

---

## 22. Deployment Framework

**Responsibility:** Plan and execute bounded changes to publishing destinations and related infrastructure through explicit preflight, authorization, apply, and post-deployment stages.

**Boundary:** It may perform only the operation and scope that were approved. It does not own content decisions, business facts, credentials outside their protected boundary, or recovery policy.

**Relationships:** Consumes approved artifacts, provider adapters, runtime identity, configuration, backups, approvals, and protected-state snapshots. Produces deployment records for Verification and Audit & Recovery.

**Configuration and extensibility:** Supports multiple CMS providers, rendering engines, hosting environments, deployment strategies, artifact formats, backup requirements, and provider-specific guarded operations.

**Implementation goal:** Make every consequential production mutation explicit, least-privileged, single-purpose, non-ambiguous, and recoverable.

---

## 23. Verification Framework

**Responsibility:** Establish whether proposed, stored, deployed, and publicly rendered states match their approved identities and contracts.

**Boundary:** Verification observes and classifies. It does not silently repair, retry, approve, or reinterpret materially different state.

**Relationships:** Uses authenticated and credential-free observations, rendered identity, provider state, page and media identity, structured outputs, accessibility, security, privacy, transport, and protected-state contracts. Supplies evidence to approvals, deployments, audits, recovery, and maintenance.

**Configuration and extensibility:** Supports provider-specific observation adapters, browser and API verification, deterministic hashes, visual comparison, mobile and desktop clients, multiple rendering engines, and future channel validators.

**Implementation goal:** Fail closed when identity or evidence is unavailable, ambiguous, stale, unsafe, or materially different, while distinguishing durable state from permitted volatile observations.

---

## 24. Audit & Recovery Framework

**Responsibility:** Preserve who acted, what was authorized, what changed, which evidence and backups applied, what verification found, how state transitioned, and what recovery remains available.

**Boundary:** Audits are durable historical records, not mutable summaries that erase failures. Recovery cannot broaden the original authority or assume a production mutation succeeded.

**Relationships:** Receives records from approvals, deployment, verification, configuration, backups, providers, and operators. Supplies history, reconciliation, rollback, incident diagnosis, compliance evidence, and maintenance context.

**Configuration and extensibility:** Supports operation-specific audit types, append-only histories, recovery policies, backup classes, retention, export, tenant boundaries, and external audit integrations.

**Implementation goal:** Make consequential work understandable and recoverable years later without exposing secrets or requiring reconstruction from logs.

---

## Cross-Cutting Systems

## 25. Security Model

Atlas security is based on explicit identity, tenant isolation, least privilege, secret isolation, exact-origin enforcement, bounded credentials, input validation, output sanitization, secure defaults, and auditable high-risk operations.

Security applies consistently across operator interfaces, automation, mobile and desktop applications, REST and GraphQL APIs, plugins, SDK clients, providers, and background work. No interface may bypass service-level authorization.

Secrets must remain outside content, media, evidence, logs, backups not designed for secrets, public APIs, source control, and client state. Website configuration may hold opaque secret references but never secret values. Form logs and delivery-attempt evidence must exclude customer field values, raw request bodies, recipient lists, provider payloads, and secret-reference values. External data is untrusted until validated. Private operational data requires explicit scope and must not leak into public website domains.

The implementation goal is a security model that scales from a local proving environment to multi-tenant hosted operation without changing its trust principles.

---

## 26. Approval Workflow

Atlas approvals bind an authorized actor to a defined object, version, scope, decision, time, and consequence. Approval of one domain does not imply approval of another.

The workflow must support approvals for facts, knowledge, site plans, content, media, themes, exceptions, deployment, recovery, and publication. It must also support rejection, requested changes, expiration, revocation where safe, and historical preservation.

Automated checks may satisfy deterministic gates. Human review remains required for material factual interpretation, brand suitability, legal sensitivity, public claims, consequential production changes, and other judgment-dependent decisions.

The implementation goal is a resumable, operator-readable workflow in which blocked conditions and required decisions are explicit.

---

## 27. Versioning Strategy

Atlas must version governing documents, application releases, migrations, provider adapters, components, themes, configuration schemas, content, media derivatives, approvals, artifacts, deployments, and audit transitions according to their own lifecycles.

Versions must preserve identity and compatibility information. A version change in one domain must not imply that unrelated domains changed. Published artifacts and consequential approvals must be reproducible or verifiable from their recorded identities.

Compatibility policies should distinguish additive change, deprecation, migration, and breaking change. Historical records must remain interpretable after new versions are introduced.

The implementation goal is controlled evolution without rewriting history or coupling every domain to one global version number.

---

## 28. Configuration Management

Configuration defines company-, brand-, website-, environment-, provider-, language-, region-, theme-, workflow-, and policy-specific behavior without altering core product logic.

Configuration must be:

- scoped to the correct owner;
- schema-defined and validated;
- versioned where consequential;
- portable and exportable where customer-owned;
- separated from secrets;
- distinguishable from business facts and content;
- reviewable before production use; and
- observable without exposing sensitive values.

Defaults must be safe and must not embed Flo-Zone facts or provider assumptions. Environment configuration must not silently override durable company truth.

Consequential form-delivery configuration must be revisioned at the Website/form boundary, retain supersession lineage and audit identity, and fail closed when recipient verification, policy, provider, transport, adapter, destination, consent, anti-abuse, idempotency, or secure-payload requirements are incomplete. Recipient addresses are configuration, not transport credentials.

The implementation goal is to support new companies and websites primarily through governed configuration rather than source-code changes.

---

## 29. Multi-Company Architecture

Atlas must support multiple companies with explicit ownership, authorization, data isolation, configuration, audit, export, backup, and recovery boundaries.

Company-private facts, knowledge, content, media, intelligence, credentials, and operational references must not leak across companies. Shared resources require explicit classification, ownership, permitted use, and revocation behavior.

An organization may own multiple companies, and authorized users may operate across them, but access must be role-based and traceable. Multi-tenant deployment must preserve the same rules at scale.

Flo-Zone is one company context and must never become the implicit default tenant.

---

## 30. Multi-Website Architecture

A company may operate multiple websites with distinct domains, identities, audiences, brands, languages, page inventories, themes, form-delivery modes and recipients, providers, credentials, deployments, and maintenance schedules.

Websites may reuse approved company facts or assets through explicit references. They must not share content, media assignments, canonical identity, provider configuration, or publication state accidentally.

The model must support website creation, cloning of reusable configuration without copying private state, migration between providers, archival, replacement, export, and recovery.

The implementation goal is to make website ownership and scope explicit at every planning, rendering, deployment, verification, and audit boundary.

---

## 31. Multi-Brand Architecture

A company may own or operate multiple brands. Each brand may have its own public name, visual assets, voice guidance, service emphasis, websites, and approved relationships to the company.

Brand identity must remain separate from legal company facts and website identity. A brand may serve multiple websites, and a website may reference an approved brand, but those associations must be explicit and versioned.

The architecture must prevent a logo, claim, tone, or media asset approved for one brand from appearing under another without authorization.

The implementation goal is flexible brand reuse without identity ambiguity or duplication of underlying company truth.

---

## 32. Extensibility Model

Atlas extensibility is contract-based. Extensions may add providers, form-delivery adapters, components, themes, page types, validators, intelligence sources, media processors, workflow steps, exports, or operator tools without bypassing core security and governance.

The model permanently supports:

- an Atlas plugin architecture;
- a versioned Extension SDK;
- capability discovery and compatibility declarations;
- sandboxed or least-privileged execution where appropriate;
- configuration schemas;
- permission and data-classification declarations;
- lifecycle hooks with bounded authority;
- health and diagnostics;
- deprecation and migration;
- signing or provenance for distributable extensions; and
- tenant-level enablement and disablement.

Extensions may not redefine ownership, weaken validation, gain undeclared data access, bypass approvals, write directly across tenant boundaries, or conceal production mutations.

The implementation goal is a stable ecosystem boundary that allows Atlas to grow without turning core domains into provider-specific code.

---

## 33. Future Capability Commitments

Atlas must preserve architectural support for the following capabilities even when they are not implemented in the current milestone:

- deeper AtlasOps360 integration through explicit operational, identity, adapter, and API boundaries, including future optional native form notifications;
- CRM integrations, including GorillaDesk and future providers;
- additional customer portal providers;
- multiple AI text, reasoning, image, and evaluation provider adapters;
- multiple CMS providers beyond WordPress;
- multiple rendering engines and theme-adapter families;
- mobile applications using the same governed service contracts;
- desktop applications using the same governed service contracts;
- public and partner REST APIs;
- future GraphQL APIs;
- search intelligence across Google, Bing, Yahoo, and emerging systems;
- AI discovery and citation monitoring;
- competitor observations;
- analytics and Search Console integrations;
- review monitoring;
- customer-question ingestion;
- responsible knowledge growth and opt-in intelligence sharing;
- multi-language content and media workflows;
- internationalization of locale, dates, currencies, addresses, regulations, and discovery behavior;
- hosted multi-tenant deployment;
- white-label products with explicit ownership and branding boundaries;
- a governed plugin architecture; and
- a versioned Extension SDK.

These are compatibility requirements, not declarations that every capability is currently available. Roadmap sequencing should favor the first complete, repeatable website workflow while avoiding decisions that would require rebuilding the platform to add these capabilities later.

---

## Appendix A: Atlas Core Concepts

### Capability

A reusable product function with a defined responsibility, boundary, inputs, outputs, configuration, permissions, and lifecycle.

### Configuration

Governed values that specialize a capability for an organization, company, brand, website, environment, provider, language, region, or workflow.

### Domain ownership

The rule that each material value has one authoritative domain responsible for its identity, validation, approval, and lifecycle.

### Evidence

A bounded, attributable observation used to prove a defined condition without becoming the underlying business truth.

### Extension

A versioned implementation that adds capability through an approved contract without bypassing Atlas governance.

### Provider

An external system that offers a capability through a declared adapter, including CMS, rendering, AI, CRM, portal, intelligence, storage, analytics, or operational services.

### Reference implementation

A real configuration used to prove reusable Atlas capabilities. Flo-Zone is the current reference implementation and does not define universal platform requirements.

### Protected state

Durable business, website, provider, content, media, configuration, or audit state that an operation must preserve unless explicitly authorized to change it.

---

## Appendix B: Domain Glossary

**Approval**  
An authorized, version-bound decision over a defined scope and consequence.

**Business fact**  
An approved, presentation-neutral statement about a company or its legitimate operations.

**Content**  
Audience-facing expression created for a defined purpose from approved knowledge.

**Form-delivery mode**\
One explicit, revisioned Website/form choice among `disabled`, `atlas_email`, `provider_owned`, `atlasops360_native`, and `external_adapter`.

**Intelligence**  
Attributed, time-bound external observation or derived recommendation that has not automatically become approved knowledge.

**Knowledge**  
Sourced information classified by type, provenance, confidence, time, and approval state.

**Media**  
An image, logo, icon, video, document, or derivative with provenance, rights, technical identity, and approval state.

**Operational data**  
Private customer, job, scheduling, dispatch, payment, or service information owned by an operational system.

**Page**  
A planned website unit with purpose, audience, relationships, content requirements, media requirements, and lifecycle state.

**Presentation**  
The visual and interaction layer formed by components, themes, layouts, tokens, and responsive behavior.

**Provider adapter**  
A bounded translation layer between Atlas capability contracts and an external provider.

**Rendering engine**  
A provider or subsystem that turns approved page, component, theme, content, and media inputs into a user-facing representation.

**Schema**  
A machine-readable representation of approved entities, facts, and relationships; not a source of new claims.

**Submission envelope**\
The provider-neutral, versioned representation of an Atlas-owned form submission and its Website, component, mode, consent, policy, anti-abuse, idempotency, request, and destination-adapter identities.

**Website Builder Core**\
The single shared complete-site engine used by standalone Atlas Website Builder and the optional AtlasOps360 Website Builder module through a one-way, non-forked dependency.

**Website identity**  
The site-specific browser, device, social, and machine-readable identity associated with a website.

---

## Appendix C: Capability Matrix

| Capability | Primary input | Primary output | Explicitly outside its ownership | Key extension direction |
| --- | --- | --- | --- | --- |
| Business Identity | Verified company information | Approved business facts | Content and presentation | Industry and regional fact types |
| Brand Assets | Approved source assets | Versioned brand assets | Page layouts | New asset and variant types |
| Website Identity | Brand assets and site configuration | Device and social identity set | Page-specific media | PWA and future platform icons |
| Knowledge Management | Sources, facts, observations | Classified approved knowledge | Automatic publication | Shared and multilingual knowledge |
| Content Planning | Knowledge and audience intent | Versioned content brief | Business truth | Human and AI authoring providers |
| Page Planning | Site goals and domain relationships | Page graph and requirements | Final prose and layout | New page types and CMS targets |
| Component Registry | Semantic presentation contracts | Reusable components | Factual ownership | Third-party component packages |
| Website Builder Core and Form Delivery | Website, component, explicit mode, recipients, policies, and adapter readiness | Provider-neutral form behavior and minimal delivery evidence | Portal state, operational records, and CRM workflow | Atlas email, provider-owned, AtlasOps360-native, and approved external adapters |
| Theme & Design | Brand and design configuration | Presentation system | Content meaning | Multiple design and rendering systems |
| Navigation | Page graph and journeys | Menus and link structures | Page authorization | Localized and private navigation |
| Media Management | Media plans and source assets | Approved responsive media | Unsupported factual proof | New storage and media formats |
| AI Image Pipeline | Approved image briefs | Candidate assets | Media approval | Multiple image providers |
| Structured Knowledge | Approved facts and page meaning | Machine-readable structures | New facts | New vocabularies and channels |
| SEO & Discovery | Pages, content, knowledge, signals | Plans and findings | Publishing authority | Search and AI discovery providers |
| Customer Portal | Enabled provider configuration | Verified portal entry point | Operational records | GorillaDesk, AtlasOps360, future portals |
| Provider Adapters | External capability contracts | Normalized provider operations | Atlas governance | CMS, AI, CRM, rendering, intelligence |
| Intelligence | External observations | Attributed signals and recommendations | Verified business facts | Analytics, reviews, competitors, search |
| Deployment | Approved artifacts and authority | Bounded production change | Content approval | Multiple CMS and hosting providers |
| Verification | Proposed and observed identities | Pass, failure, and evidence | Silent repair | Browser, API, visual, mobile validation |
| Audit & Recovery | Actions, evidence, backups | Durable history and recovery state | Rewritten history | External audit and retention providers |

---

## Appendix D: Future Product Roadmap Alignment

| Roadmap direction | Product Specification capabilities that support it |
| --- | --- |
| Complete WordPress foundation | Provider Adapters, Deployment, Verification, Audit & Recovery |
| Complete Flo-Zone website | All identity, planning, experience, media, discovery, and delivery subsystems |
| Repeatable company onboarding | Business Identity, Configuration, Multi-Company, Multi-Website, Approval |
| Second-company proof | Tenant isolation, reusable capability contracts, provider-independent configuration |
| Operator dashboard | Shared domain services, approvals, configuration, verification, and audit state |
| Quality and template expansion | Component Registry, Theme & Design, QA-related verification, versioning |
| Website maintenance | Intelligence, Verification, Content and Page Planning, Deployment, Audit & Recovery |
| Multi-company SaaS | Security, Multi-Company, Multi-Website, multi-tenant configuration and operations |
| Product-family integration | Shared Website Builder Core, one-way AtlasOps360 adapter/API boundary, Provider Adapters, Customer Portal, shared identity contracts |
| Operational intelligence network | Intelligence, Knowledge, privacy, provenance, opt-in sharing, tenant isolation |

Roadmap phases determine implementation order. Capability boundaries in this Specification remain stable unless a governing-document update explicitly changes them.
