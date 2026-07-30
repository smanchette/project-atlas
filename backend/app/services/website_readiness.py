from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import GeneratedPage, PlannedPage, PlanningRecord, SitePlan
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
        _website_category(plan, planned_pages, generated_by_id),
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
                else "County and standalone City drafting remain deferred in this milestone."
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
                "navigation",
                "Navigation and internal links",
                "deferred",
                "Deferred to a separately approved Navigation milestone; not a current failure.",
            ),
            (
                "media",
                "Media planning and provenance",
                "deferred",
                "Deferred to a separately approved Media and Brand Assets milestone; not a current failure.",
            ),
            (
                "theme",
                "Theme and design system",
                "deferred",
                "Deferred to a separately approved presentation milestone; not a current failure.",
            ),
            (
                "components",
                "Component registry",
                "not_assessed",
                "Not assessed in this foundation and excluded from current readiness.",
            ),
            (
                "publication",
                "Publication readiness",
                "not_assessed",
                "Not assessed; no CMS or production system was contacted.",
            ),
            (
                "semantic_duplication",
                "Semantic duplication and cannibalization",
                "not_assessed",
                "Only deterministic exact conflicts are evaluated in this milestone.",
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
