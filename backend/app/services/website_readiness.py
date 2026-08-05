from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import (
    BrandAsset,
    GeneratedPage,
    PlannedPage,
    PlanningRecord,
    SitePlan,
    Website,
    WebsiteIdentity,
    WebsiteIdentityAssetAssignment,
)
from app.services.brand_assets import identity_asset_contract_error
from app.schemas.site_plans import (
    WebsiteReadinessCategory,
    WebsiteReadinessItem,
    WebsiteReadinessReport,
)
from app.services.page_type_review import (
    DEFERRED_PAGE_TYPES,
    review_contract_for,
    validate_draft_contract,
)
from app.services.website_context import build_website_context


class WebsiteReadinessError(ValueError):
    pass


def evaluate_website_readiness(
    session: Session,
    plan_id: int,
) -> WebsiteReadinessReport:
    plan = session.get(SitePlan, plan_id)
    if not plan:
        raise WebsiteReadinessError("Site Plan not found.")
    context = build_website_context(session, website_id=plan.website_id)
    planned_pages = list(
        session.exec(
            select(PlannedPage)
            .where(PlannedPage.site_plan_id == plan.id)
            .order_by(PlannedPage.id)
        ).all()
    )
    generated_by_id = {
        page.id: page
        for page in session.exec(
            select(GeneratedPage).where(GeneratedPage.website_id == plan.website_id)
        ).all()
        if page.id is not None
    }
    records_by_page = {
        record.planned_page_id: record
        for record in session.exec(
            select(PlanningRecord).where(
                PlanningRecord.planned_page_id.in_(
                    [page.id for page in planned_pages if page.id is not None]
                )
            )
        ).all()
    } if planned_pages else {}

    categories = [
        _business_category(context, planned_pages),
        _content_category(planned_pages, generated_by_id, records_by_page),
        _website_category(session, plan, planned_pages, generated_by_id),
        _future_category(),
    ]
    current_categories = categories[:3]
    return WebsiteReadinessReport(
        website_id=plan.website_id,
        site_plan_id=plan.id or plan_id,
        site_plan_version=plan.version,
        review_ready=all(category.status == "ready" for category in current_categories),
        evaluated_at=datetime.now(UTC),
        categories=categories,
    )


def _business_category(context, pages: list[PlannedPage]) -> WebsiteReadinessCategory:
    business = context.business
    identity = context.identity
    items = [
        _item(
            "business_identity",
            "Approved business identity",
            bool(business.company_name and business.business_type and business.state),
            "Business name, type, and state are available.",
            "Business name, type, or state is missing.",
        ),
        _item(
            "website_identity",
            "Website identity",
            bool(identity.display_name and context.website.domain and context.website.public_url),
            "Website display name, domain, and public URL are available.",
            "Website identity, domain, or public URL is missing.",
        ),
        _item(
            "contact_path",
            "Customer contact path",
            bool(business.phone or business.email),
            "At least one approved contact method is available.",
            "No approved phone number or email address is available.",
        ),
    ]
    service_pages = [page for page in pages if page.page_type in {"service", "city_service"}]
    missing_service = [page.id or 0 for page in service_pages if page.service_id is None]
    items.append(
        WebsiteReadinessItem(
            key="service_relationships",
            label="Service relationships",
            status="ready" if not missing_service else "needs_attention",
            message=(
                "All service-oriented Planned Pages reference an approved Service."
                if not missing_service
                else "One or more service-oriented Planned Pages lack a Service relationship."
            ),
            affected_planned_page_ids=missing_service,
        )
    )
    return _category("business_readiness", "Business Readiness", items)


def _content_category(
    pages: list[PlannedPage],
    generated_by_id: dict[int, GeneratedPage],
    records_by_page: dict[int, PlanningRecord],
) -> WebsiteReadinessCategory:
    items: list[WebsiteReadinessItem] = []
    items.append(
        _item(
            "planned_inventory",
            "Planned page inventory",
            bool(pages),
            f"{len(pages)} Planned Page(s) define the current Site Plan.",
            "The Site Plan has no Planned Pages.",
        )
    )
    missing_records = [page.id or 0 for page in pages if page.id not in records_by_page]
    items.append(
        WebsiteReadinessItem(
            key="planning_records",
            label="Planning Records",
            status="ready" if not missing_records else "needs_attention",
            message=(
                "Every Planned Page has a Planning Record."
                if not missing_records
                else "One or more Planned Pages lack a Planning Record."
            ),
            affected_planned_page_ids=missing_records,
        )
    )
    deferred = [
        page.id or 0 for page in pages if page.page_type in DEFERRED_PAGE_TYPES
    ]
    items.append(
        WebsiteReadinessItem(
            key="supported_page_types",
            label="Currently reviewable page types",
            status="ready" if not deferred else "deferred",
            message=(
                "All Planned Pages use currently supported review contracts."
                if not deferred
                else "Standalone City drafting remains deferred in this milestone."
            ),
            affected_planned_page_ids=deferred,
        )
    )
    missing_drafts: list[int] = []
    invalid_drafts: list[int] = []
    stale_drafts: list[int] = []
    stale_qa: list[int] = []
    for planned in pages:
        if planned.page_type in DEFERRED_PAGE_TYPES:
            continue
        generated = generated_by_id.get(planned.generated_page_id or -1)
        if not generated or not generated.draft_content:
            missing_drafts.append(planned.id or 0)
            continue
        try:
            review_contract_for(generated)
        except ValueError:
            invalid_drafts.append(planned.id or 0)
            continue
        if validate_draft_contract(generated, generated.draft_content):
            invalid_drafts.append(planned.id or 0)
        record = records_by_page.get(planned.id or -1)
        draft_planning_time = _datetime(generated.draft_content.get("planning_generated_at"))
        if (
            record is not None
            and draft_planning_time is not None
            and _timestamp(draft_planning_time) < _timestamp(record.generated_at)
        ):
            stale_drafts.append(planned.id or 0)
        if (
            generated.qa_status != "ready"
            or generated.qa_checked_at is None
            or (
                generated.qa_checked_at is not None
                and _timestamp(generated.qa_checked_at) < _timestamp(generated.updated_at)
            )
        ):
            stale_qa.append(planned.id or 0)
    items.extend(
        [
            WebsiteReadinessItem(
                key="draft_coverage",
                label="Draft coverage",
                status="ready" if not missing_drafts else "needs_attention",
                message=(
                    "Every currently supported Planned Page has exactly one linked draft."
                    if not missing_drafts
                    else "One or more currently supported Planned Pages have no linked draft."
                ),
                affected_planned_page_ids=missing_drafts,
            ),
            WebsiteReadinessItem(
                key="page_type_contracts",
                label="Page-type review contracts",
                status="ready" if not invalid_drafts else "needs_attention",
                message=(
                    "Every available draft matches its authoritative page-type contract."
                    if not invalid_drafts
                    else "One or more drafts do not match their page-type review contract."
                ),
                affected_planned_page_ids=invalid_drafts,
            ),
            WebsiteReadinessItem(
                key="draft_freshness",
                label="Planning Record draft freshness",
                status="ready" if not stale_drafts else "needs_attention",
                message=(
                    "Every available planned-page draft reflects its current Planning Record."
                    if not stale_drafts
                    else "One or more drafts predate their current Planning Record."
                ),
                affected_planned_page_ids=stale_drafts,
            ),
            WebsiteReadinessItem(
                key="page_qa",
                label="Current per-page QA",
                status="ready" if not stale_qa else "needs_attention",
                message=(
                    "Every available supported draft has current ready QA."
                    if not stale_qa
                    else "One or more available drafts need current page-type-aware QA."
                ),
                affected_planned_page_ids=stale_qa,
            ),
        ]
    )
    return _category("content_readiness", "Content Readiness", items)


def _website_category(
    session: Session,
    plan: SitePlan,
    pages: list[PlannedPage],
    generated_by_id: dict[int, GeneratedPage],
) -> WebsiteReadinessCategory:
    page_ids = {page.id for page in pages if page.id is not None}
    invalid_parents = [
        page.id or 0
        for page in pages
        if page.parent_planned_page_id is not None
        and page.parent_planned_page_id not in page_ids
    ]
    cycles = _hierarchy_cycles(pages)
    wrong_website = [
        page.id or 0
        for page in pages
        if page.website_id != plan.website_id
        or (
            page.generated_page_id is not None
            and (
                page.generated_page_id not in generated_by_id
                or generated_by_id[page.generated_page_id].website_id != plan.website_id
            )
        )
    ]
    slug_conflicts = _duplicates(
        pages, lambda page: _normalized(page.intended_slug)
    )
    title_conflicts = _generated_duplicates(
        pages, generated_by_id, lambda draft: _normalized(draft.get("title"))
    )
    h1_conflicts = _generated_duplicates(
        pages, generated_by_id, lambda draft: _normalized(draft.get("h1"))
    )
    items = [
        WebsiteReadinessItem(
            key="website_ownership",
            label="Website ownership",
            status="ready" if not wrong_website else "needs_attention",
            message=(
                "All Site Plan, Planned Page, and Generated Page links remain Website-scoped."
                if not wrong_website
                else "A Planned Page or Generated Page crosses the Site Plan Website boundary."
            ),
            affected_planned_page_ids=wrong_website,
        ),
        WebsiteReadinessItem(
            key="page_hierarchy",
            label="Page hierarchy",
            status="ready" if not invalid_parents and not cycles else "needs_attention",
            message=(
                "Parent relationships are contained within the Site Plan and are acyclic."
                if not invalid_parents and not cycles
                else "The Site Plan contains an invalid parent or hierarchy cycle."
            ),
            affected_planned_page_ids=sorted(set(invalid_parents + cycles)),
        ),
        WebsiteReadinessItem(
            key="slug_identity",
            label="Slug and canonical intent",
            status="ready" if not slug_conflicts else "needs_attention",
            message=(
                "Planned slugs are unique within the Website."
                if not slug_conflicts
                else "Duplicate planned slugs would create conflicting canonical intent."
            ),
            affected_planned_page_ids=slug_conflicts,
        ),
        WebsiteReadinessItem(
            key="title_consistency",
            label="Cross-page title consistency",
            status="ready" if not title_conflicts else "needs_attention",
            message=(
                "No exact duplicate generated titles were detected."
                if not title_conflicts
                else "Exact duplicate generated titles require review."
            ),
            affected_planned_page_ids=title_conflicts,
        ),
        WebsiteReadinessItem(
            key="h1_consistency",
            label="Cross-page H1 consistency",
            status="ready" if not h1_conflicts else "needs_attention",
            message=(
                "No exact duplicate generated H1 headings were detected."
                if not h1_conflicts
                else "Exact duplicate generated H1 headings require review."
            ),
            affected_planned_page_ids=h1_conflicts,
        ),
    ]
    from app.services.site_connections import evaluate_site_connection_diagnostics

    connection_diagnostics = evaluate_site_connection_diagnostics(session, plan)
    items.extend(
        WebsiteReadinessItem(
            key=f"site_connections_{diagnostic.key}",
            label=diagnostic.label,
            status=diagnostic.status,
            message=diagnostic.message,
            affected_planned_page_ids=diagnostic.affected_planned_page_ids,
        )
        for diagnostic in connection_diagnostics
    )
    from app.services.site_coverage import (
        SiteCoverageError,
        preview_expected_inventory,
    )

    try:
        coverage = preview_expected_inventory(session, plan.id or 0)
    except SiteCoverageError as exc:
        items.append(
            WebsiteReadinessItem(
                key="coverage_foundation",
                label="Approved Website coverage policy",
                status="needs_attention",
                message=str(exc),
            )
        )
    else:
        by_disposition = {
            disposition: [
                item
                for item in coverage.items
                if item.disposition == disposition
            ]
            for disposition in (
                "missing",
                "pending_decision",
                "unsupported_extra",
                "unexplained_historical",
            )
        }
        missing_core = [
            item
            for item in by_disposition["missing"]
            if item.page_type in {"home", "about", "contact", "faq"}
        ]
        missing_services = [
            item
            for item in by_disposition["missing"]
            if item.page_type == "service"
        ]
        missing_matrix = [
            item
            for item in by_disposition["missing"]
            if item.page_type == "city_service"
        ]
        missing_counties = [
            item
            for item in by_disposition["missing"]
            if item.page_type == "county"
        ]
        coverage_items = (
            (
                "coverage_core_pages",
                "Core-page coverage",
                missing_core,
                "Home, About, Contact, and FAQ coverage is complete.",
                "One or more required core pages are missing.",
            ),
            (
                "coverage_service_pages",
                "Approved Service-page coverage",
                missing_services,
                "Every included Website service has a Planned Service page.",
                "One or more included Website services lack a Planned Service page.",
            ),
            (
                "coverage_city_service_matrix",
                "Approved City-Service matrix coverage",
                missing_matrix + by_disposition["pending_decision"],
                "Every operator-included Service × City combination is planned and no candidate awaits a decision.",
                "City-Service coverage is missing or awaiting an operator decision.",
            ),
            (
                "coverage_county_pages",
                "County and service-area coverage",
                missing_counties,
                "Every included County marked page-appropriate is planned.",
                "One or more page-appropriate County decisions lack a Planned Page.",
            ),
            (
                "coverage_unsupported_extras",
                "Unsupported coverage combinations",
                by_disposition["unsupported_extra"],
                "No Planned Page is outside the approved expected inventory.",
                "One or more Planned Pages are outside the approved expected inventory.",
            ),
            (
                "coverage_unexplained_historical",
                "Unexplained historical combinations",
                by_disposition["unexplained_historical"],
                "Every historical coverage page has an explicit included operator decision.",
                "Historical pages remain visible without silently becoming operator approval.",
            ),
        )
        items.extend(
            WebsiteReadinessItem(
                key=key,
                label=label,
                status="ready" if not affected else "needs_attention",
                message=pass_message if not affected else fail_message,
                affected_planned_page_ids=sorted(
                    {
                        item.planned_page_id
                        for item in affected
                        if item.planned_page_id is not None
                    }
                ),
            )
            for key, label, affected, pass_message, fail_message in coverage_items
        )
        items.extend(
            [
                WebsiteReadinessItem(
                    key="coverage_excluded",
                    label="Explicitly excluded coverage",
                    status="ready",
                    message=(
                        f"{coverage.counts.excluded} coverage item(s) are explicitly excluded "
                        "and are not expected pages."
                    ),
                ),
                WebsiteReadinessItem(
                    key="coverage_deferred",
                    label="Explicitly deferred coverage",
                    status="ready",
                    message=(
                        f"{coverage.counts.deferred} coverage item(s) remain explicitly deferred "
                        "and visible for later review."
                    ),
                ),
            ]
        )
    from app.services.drafting_eligibility import (
        DraftingEligibilityError,
        read_manifest,
    )

    try:
        eligibility = read_manifest(session, plan.id or 0)
    except (DraftingEligibilityError, SiteCoverageError) as exc:
        items.append(
            WebsiteReadinessItem(
                key="drafting_eligibility",
                label="Coverage-gated drafting eligibility",
                status="needs_attention",
                message=str(exc),
            )
        )
    else:
        cannibalization_count = sum(
            1
            for assessment in eligibility.assessments
            if any(
                finding.get("kind") == "likely_cannibalization"
                for finding in assessment.semantic_findings
            )
        )
        eligibility_specs = (
            (
                "drafting_eligibility_coverage",
                "Coverage-gated assessments",
                eligibility.counts.excluded_by_coverage,
                "All assessed expected pages are explicitly covered.",
                "One or more pages are excluded by current coverage decisions.",
            ),
            (
                "drafting_eligibility_freshness",
                "Eligibility assessment freshness",
                eligibility.counts.stale_assessment,
                "Eligibility assessments reflect current approved inputs.",
                "One or more eligibility assessments are stale.",
            ),
            (
                "drafting_local_value",
                "Approved local value",
                eligibility.counts.insufficient_local_value,
                "Assessed local pages have sufficient approved local-value evidence.",
                "One or more pages need approved local-value evidence or an operator disposition.",
            ),
            (
                "semantic_duplication",
                "Semantic duplication",
                eligibility.counts.semantic_duplication,
                "No current semantic duplicates were detected.",
                "One or more pages require semantic-duplication review.",
            ),
            (
                "semantic_consolidation",
                "Consolidation recommendations",
                eligibility.counts.consolidation_recommended,
                "No current pages require consolidation review.",
                "One or more pages appear to differ only by geographic substitution.",
            ),
            (
                "semantic_cannibalization",
                "Cannibalization risk",
                cannibalization_count,
                "No current deterministic cannibalization risks were detected.",
                "One or more related pages have overlapping intent, headings, and sections.",
            ),
            (
                "drafting_required_information",
                "Drafting required information",
                eligibility.counts.blocked_missing_required_information,
                "Current assessments contain required approved information.",
                "One or more pages lack required approved information.",
            ),
        )
        items.extend(
            WebsiteReadinessItem(
                key=key,
                label=label,
                status="ready" if count == 0 else "needs_attention",
                message=pass_message if count == 0 else fail_message,
            )
            for key, label, count, pass_message, fail_message in eligibility_specs
        )
        missing_briefs = max(
            0,
            len(eligibility.assessments) - len(eligibility.distinctness_briefs),
        )
        items.extend(
            [
                WebsiteReadinessItem(
                    key="pre_draft_distinctness_briefs",
                    label="Pre-Draft Distinctness Briefs",
                    status="ready" if missing_briefs == 0 else "needs_attention",
                    message=(
                        "Every assessed Planned Page has a current deterministic "
                        "distinctness brief."
                        if missing_briefs == 0
                        else "One or more assessed Planned Pages lack a distinctness brief."
                    ),
                ),
                WebsiteReadinessItem(
                    key="drafting_batch_manifest",
                    label="Complete pre-draft batch manifest",
                    status=(
                        "ready"
                        if eligibility.batch_manifest.preview_ready
                        else "needs_attention"
                    ),
                    message=(
                        "Every expected page has a current effective eligibility result."
                        if eligibility.batch_manifest.preview_ready
                        else "The complete expected inventory contains blocked, stale, "
                        "or consolidation-recommended pages."
                    ),
                    affected_planned_page_ids=[
                        item.planned_page_id
                        for item in eligibility.batch_manifest.items
                        if item.planned_page_id is not None
                        and item.classification
                        in {"blocked", "stale", "consolidation_recommended"}
                    ],
                ),
            ]
        )
    from app.services.page_composition import composition_diagnostics

    missing_compositions, stale_compositions = composition_diagnostics(session, plan)
    items.extend(
        [
            WebsiteReadinessItem(
                key="semantic_component_compositions",
                label="Semantic page compositions",
                status="ready" if not missing_compositions else "needs_attention",
                message=(
                    "Every generated Planned Page has a Website-scoped semantic composition."
                    if not missing_compositions
                    else "One or more generated Planned Pages lack a semantic composition."
                ),
                affected_planned_page_ids=missing_compositions,
            ),
            WebsiteReadinessItem(
                key="semantic_component_freshness",
                label="Composition contract and source freshness",
                status="ready" if not stale_compositions else "needs_attention",
                message=(
                    "Every semantic composition matches current approved sources and component contracts."
                    if not stale_compositions
                    else "One or more compositions are stale, invalid, or cross a protected boundary."
                ),
                affected_planned_page_ids=stale_compositions,
            ),
        ]
    )
    website = session.get(Website, plan.website_id)
    identity = session.exec(
        select(WebsiteIdentity).where(WebsiteIdentity.website_id == plan.website_id)
    ).first()
    approved_assets = list(session.exec(
        select(BrandAsset).where(
            BrandAsset.brand_id == website.brand_id,
            BrandAsset.business_id == website.business_id,
            BrandAsset.status == "approved",
        )
    ).all()) if website and website.brand_id is not None else []
    active_selections = list(session.exec(
        select(WebsiteIdentityAssetAssignment).where(
            WebsiteIdentityAssetAssignment.website_identity_id == identity.id,
            WebsiteIdentityAssetAssignment.status == "active",
        )
    ).all()) if identity and identity.id is not None else []
    required_slots = {
        "header_logo", "footer_logo", "favicon", "browser_icon",
        "apple_touch_icon", "open_graph_image",
    }
    selected_slots: set[str] = set()
    invalid_slots: list[str] = []
    for selection in active_selections:
        asset = session.get(BrandAsset, selection.brand_asset_id)
        if (
            not website
            or not asset
            or asset.status != "approved"
            or selection.website_id != website.id
            or selection.brand_id != website.brand_id
            or asset.business_id != website.business_id
            or asset.brand_id != website.brand_id
            or identity_asset_contract_error(asset, selection.slot) is not None
        ):
            invalid_slots.append(selection.slot)
        else:
            selected_slots.add(selection.slot)
    items.extend(
        [
            WebsiteReadinessItem(
                key="approved_brand_assets",
                label="Approved Brand Assets",
                status="ready" if approved_assets else "needs_attention",
                message=(
                    "The Website Brand owns approved, governed visual-identity assets."
                    if approved_assets
                    else "The Website Brand has no approved visual-identity assets."
                ),
            ),
            WebsiteReadinessItem(
                key="website_identity_asset_selections",
                label="Website Identity asset selections",
                status="ready" if required_slots <= selected_slots and not invalid_slots else "needs_attention",
                message=(
                    "Website Identity selects approved assets for every supported identity slot."
                    if required_slots <= selected_slots and not invalid_slots
                    else "Website Identity needs valid approved selections"
                    + (
                        " for: " + ", ".join(sorted(required_slots - selected_slots))
                        if required_slots - selected_slots else ""
                    )
                    + (
                        "; invalid or unapproved selections: " + ", ".join(sorted(set(invalid_slots)))
                        if invalid_slots else ""
                    )
                    + "."
                ),
            ),
        ]
    )
    from app.services.themes import ThemeError, resolve_website_theme

    try:
        resolved_theme = resolve_website_theme(session, plan.website_id)
    except ThemeError as exc:
        theme_error = str(exc)
        items.extend(
            WebsiteReadinessItem(
                key=key,
                label=label,
                status="needs_attention",
                message=f"Website Theme validation failed closed: {theme_error}",
            )
            for key, label in (
                ("theme_selection", "Selected Website Theme"),
                ("theme_approval", "Theme approval"),
                ("theme_token_contract", "Design token contract"),
                ("theme_accessibility", "Theme accessibility validation"),
                ("theme_composition_freshness", "Theme composition freshness"),
            )
        )
    else:
        selected = not resolved_theme.fallback_used
        selected_theme = resolved_theme.theme
        items.extend(
            [
                WebsiteReadinessItem(
                    key="theme_selection",
                    label="Selected Website Theme",
                    status="ready" if selected else "needs_attention",
                    message=(
                        "The Website has exactly one active governed Theme selection."
                        if selected
                        else "No governed Theme is selected; local previews use the explicit neutral fallback."
                    ),
                ),
                WebsiteReadinessItem(
                    key="theme_approval",
                    label="Theme approval",
                    status="ready" if selected else "not_assessed",
                    message=(
                        "The selected Theme is approved and available."
                        if selected
                        else "Theme approval is not assessed until a governed Theme is selected."
                    ),
                ),
                WebsiteReadinessItem(
                    key="theme_token_contract",
                    label="Design token contract",
                    status="ready" if selected else "not_assessed",
                    message=(
                        f"Theme {selected_theme.theme_key} v{selected_theme.version} has a current typed token contract."
                        if selected and selected_theme is not None
                        else "Design tokens are not assessed until a governed Theme is selected."
                    ),
                ),
                WebsiteReadinessItem(
                    key="theme_accessibility",
                    label="Theme accessibility validation",
                    status="ready" if selected else "not_assessed",
                    message=(
                        "The selected Theme passed deterministic contrast, focus, motion, target-size, and layout validation."
                        if selected
                        else "Theme accessibility is not assessed until a governed Theme is selected."
                    ),
                ),
                WebsiteReadinessItem(
                    key="theme_composition_freshness",
                    label="Theme composition freshness",
                    status="ready" if selected and not stale_compositions else (
                        "needs_attention" if selected else "not_assessed"
                    ),
                    message=(
                        "Every semantic composition is bound to the exact selected Theme identity and token hash."
                        if selected and not stale_compositions
                        else "One or more semantic compositions must be refreshed for the selected Theme."
                        if selected
                        else "Theme-bound composition freshness is not assessed until a governed Theme is selected."
                    ),
                    affected_planned_page_ids=stale_compositions if selected else [],
                ),
            ]
        )
    return _category("website_readiness", "Website Readiness", items)


def _future_category() -> WebsiteReadinessCategory:
    items = [
        WebsiteReadinessItem(
            key=key,
            label=label,
            status=status,
            message=message,
        )
        for key, label, status, message in (
            (
                "media",
                "Page-media planning and provenance",
                "deferred",
                "Deferred to a separately approved page-media milestone; not a current failure.",
            ),
            (
                "media_ingestion",
                "Media ingestion and generation",
                "deferred",
                "Deferred to a separately approved media milestone; not a current failure.",
            ),
            (
                "complete_site_preview",
                "Complete-site preview",
                "not_assessed",
                "Not assessed; this milestone verifies page compositions only.",
            ),
            (
                "publication",
                "Publication readiness",
                "not_assessed",
                "Not assessed; no CMS or production system was contacted.",
            ),
        )
    ]
    return WebsiteReadinessCategory(
        key="future_readiness",
        label="Future Readiness",
        status="deferred",
        items=items,
    )


def _category(key: str, label: str, items: list[WebsiteReadinessItem]):
    status = (
        "needs_attention"
        if any(item.status == "needs_attention" for item in items)
        else "deferred"
        if any(item.status == "deferred" for item in items)
        else "not_assessed"
        if any(item.status == "not_assessed" for item in items)
        else "ready"
    )
    return WebsiteReadinessCategory(key=key, label=label, status=status, items=items)


def _item(
    key: str,
    label: str,
    passed: bool,
    pass_message: str,
    fail_message: str,
) -> WebsiteReadinessItem:
    return WebsiteReadinessItem(
        key=key,
        label=label,
        status="ready" if passed else "needs_attention",
        message=pass_message if passed else fail_message,
    )


def _hierarchy_cycles(pages: list[PlannedPage]) -> list[int]:
    parent_by_id = {
        page.id: page.parent_planned_page_id
        for page in pages
        if page.id is not None
    }
    affected: set[int] = set()
    for start in parent_by_id:
        trail: list[int] = []
        current: int | None = start
        while current is not None and current in parent_by_id:
            if current in trail:
                affected.update(trail[trail.index(current) :])
                break
            trail.append(current)
            current = parent_by_id[current]
    return sorted(affected)


def _duplicates(pages: list[PlannedPage], value_for) -> list[int]:
    values = [value_for(page) for page in pages]
    counts = Counter(value for value in values if value)
    return [
        page.id or 0
        for page, value in zip(pages, values, strict=True)
        if value and counts[value] > 1
    ]


def _generated_duplicates(
    pages: list[PlannedPage],
    generated_by_id: dict[int, GeneratedPage],
    value_for,
) -> list[int]:
    values: list[tuple[PlannedPage, str]] = []
    for planned in pages:
        generated = generated_by_id.get(planned.generated_page_id or -1)
        if generated and generated.draft_content:
            values.append((planned, value_for(generated.draft_content)))
    counts = Counter(value for _, value in values if value)
    return [
        page.id or 0 for page, value in values if value and counts[value] > 1
    ]


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()
