from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import (
    Business,
    City,
    County,
    GeneratedPage,
    KnowledgeBlock,
    PlannedPage,
    PlanningRecord,
    Service,
)
from app.schemas.site_plans import (
    DraftReadinessRead,
    DraftSection,
    PlannedPageDraftContent,
)
from app.services.draft_generation import (
    DraftGenerationError,
    generate_page_draft,
    validate_safe_content,
)
from app.services.website_context import build_website_context


SUPPORTED_PAGE_TYPES = {
    "home",
    "about",
    "contact",
    "service",
    "informational",
    "faq",
}
COMPATIBILITY_PAGE_TYPES = {"city_service"}


class PlannedPageDraftingError(DraftGenerationError):
    pass


def evaluate_draft_readiness(
    session: Session,
    page: PlannedPage,
    *,
    record: PlanningRecord | None = None,
) -> DraftReadinessRead:
    if page.page_type not in SUPPORTED_PAGE_TYPES | COMPATIBILITY_PAGE_TYPES:
        return DraftReadinessRead(
            status="unsupported",
            page_type_supported=False,
            blocking_reasons=[
                f"{page.page_type.replace('_', ' ').title()} drafting is deferred."
            ],
            recommendations=[],
        )

    website_context = build_website_context(session, website_id=page.website_id)
    business = session.get(Business, website_context.business.id)
    service = session.get(Service, page.service_id) if page.service_id else None
    knowledge = _approved_knowledge(session, business.id if business else 0, service)
    contact_methods = [
        value
        for value in (website_context.business.phone, website_context.business.email)
        if _has_text(value)
    ]
    trust_values = [
        value
        for value in (
            website_context.business.license_number,
            website_context.business.certified_operator,
            website_context.brand.description,
        )
        if _has_text(value)
    ]
    primary_services = [
        item
        for item in website_context.services
        if item.status == "active"
        and (_has_text(item.short_description) or _has_text(item.long_description))
    ]
    service_area_available = bool(
        _has_text(website_context.business.main_city)
        or _has_text(website_context.business.state)
    )

    checks: list[tuple[str, bool, str]] = [
        (
            "website_identity",
            _has_text(website_context.identity.display_name),
            "Complete the approved Website Identity display name.",
        )
    ]
    if page.page_type == "home":
        checks.extend(
            [
                (
                    "company_identity",
                    bool(business and _has_text(business.company_name)),
                    "Complete the approved company identity.",
                ),
                (
                    "primary_services",
                    bool(primary_services),
                    "Add at least one active service with an approved description.",
                ),
                (
                    "primary_service_area",
                    service_area_available,
                    "Confirm the approved primary service area.",
                ),
                (
                    "primary_call_to_action",
                    bool(contact_methods),
                    "Add an approved phone number or email for the primary call to action.",
                ),
            ]
        )
    elif page.page_type == "about":
        checks.extend(
            [
                (
                    "company_description",
                    bool(business and _has_text(business.description)),
                    "Add an approved company description.",
                ),
                (
                    "trust_information",
                    bool(trust_values),
                    "Add approved license, operator, or company trust information.",
                ),
                (
                    "contact_information",
                    bool(contact_methods),
                    "Add an approved phone number or email.",
                ),
            ]
        )
    elif page.page_type == "contact":
        checks.extend(
            [
                (
                    "contact_methods",
                    bool(contact_methods),
                    "Add at least one approved contact method.",
                ),
                (
                    "service_area",
                    service_area_available,
                    "Confirm the approved service area.",
                ),
                (
                    "preferred_contact_methods",
                    bool(contact_methods),
                    "Identify at least one approved customer contact method.",
                ),
            ]
        )
    elif page.page_type in {"service", "city_service"}:
        checks.extend(
            [
                (
                    "service_relationship",
                    service is not None,
                    "Assign an approved Service to this Planned Page.",
                ),
                (
                    "service_information",
                    bool(
                        service
                        and (
                            _has_text(service.short_description)
                            or _has_text(service.long_description)
                        )
                    ),
                    "Add approved descriptive information for the assigned Service.",
                ),
                (
                    "primary_call_to_action",
                    bool(contact_methods),
                    "Add an approved phone number or email for the call to action.",
                ),
            ]
        )
        if page.page_type == "city_service":
            city = session.get(City, page.city_id) if page.city_id else None
            county = session.get(County, page.county_id) if page.county_id else None
            checks.extend(
                [
                    (
                        "city_relationship",
                        city is not None,
                        "Assign an approved City to this City-Service page.",
                    ),
                    (
                        "county_relationship",
                        county is not None,
                        "Assign the City-Service page's approved County.",
                    ),
                    (
                        "approved_knowledge",
                        bool(knowledge),
                        "Add approved supporting knowledge for the assigned Service.",
                    ),
                ]
            )
    elif page.page_type == "informational":
        checks.append(
            (
                "approved_knowledge",
                bool(knowledge),
                "Add approved knowledge for this informational topic.",
            )
        )
    elif page.page_type == "faq":
        checks.append(
            (
                "approved_questions_and_answers",
                bool(knowledge)
                and all(
                    _has_text(item.question)
                    and _has_text(item.short_answer)
                    and _has_text(item.long_answer)
                    for item in knowledge
                ),
                "Add at least one approved question and answer.",
            )
        )

    required_information = [
        {"key": key, "available": available}
        for key, available, _ in checks
    ]
    blocking_reasons = [
        recommendation
        for _, available, recommendation in checks
        if not available
    ]
    planning_record = record or session.exec(
        select(PlanningRecord).where(PlanningRecord.planned_page_id == page.id)
    ).first()
    recommendations = list(
        dict.fromkeys(
            [
                *blocking_reasons,
                *(planning_record.improvement_recommendations if planning_record else []),
            ]
        )
    )
    return DraftReadinessRead(
        status="blocked" if blocking_reasons else "ready",
        page_type_supported=True,
        required_information=required_information,
        blocking_reasons=blocking_reasons,
        recommendations=recommendations,
    )


def draft_planned_page(
    session: Session,
    planned_page_id: int,
    *,
    expected_website_id: int,
    allow_overwrite: bool = False,
) -> tuple[GeneratedPage, DraftReadinessRead]:
    page = session.get(PlannedPage, planned_page_id)
    if not page:
        raise PlannedPageDraftingError("Planned Page not found.")
    if page.website_id != expected_website_id:
        raise PlannedPageDraftingError(
            "Planned Page does not belong to the selected Website."
        )

    # Refresh generated planning material immediately before drafting. The refresh
    # intentionally preserves operator_overrides.
    from app.services.site_planning import refresh_planning_record

    refresh_planning_record(session, planned_page_id, commit=False)
    record = session.exec(
        select(PlanningRecord).where(PlanningRecord.planned_page_id == page.id)
    ).one()
    readiness = evaluate_draft_readiness(session, page, record=record)
    if readiness.status != "ready":
        raise PlannedPageDraftingError(
            "Planned Page is not ready to draft: "
            + "; ".join(readiness.blocking_reasons)
        )

    if page.page_type == "city_service":
        generated = _ensure_city_service_compatibility_page(session, page)
        generated = generate_page_draft(
            session,
            generated.id or 0,
            expected_website_id=page.website_id,
            allow_overwrite=allow_overwrite,
            commit=False,
        )
        page.planning_status = "drafted"
        page.updated_at = datetime.now(UTC)
        session.add(page)
        session.commit()
        session.refresh(generated)
        return generated, readiness

    if page.page_type not in SUPPORTED_PAGE_TYPES:
        raise PlannedPageDraftingError(
            f"{page.page_type.replace('_', ' ').title()} drafting is deferred."
        )

    generated = (
        session.get(GeneratedPage, page.generated_page_id)
        if page.generated_page_id is not None
        else None
    )
    if generated:
        _ensure_refresh_allowed(generated, allow_overwrite=allow_overwrite)
    else:
        generated = _new_generated_page(session, page)
        session.add(generated)
        session.flush()
        page.generated_page_id = generated.id

    draft = _build_draft(session, page, record)
    payload = draft.model_dump(mode="json")
    validate_safe_content(payload)
    now = datetime.now(UTC)
    generated.page_type = page.page_type
    generated.page_title = draft.title
    generated.page_slug = page.intended_slug
    generated.service_id = page.service_id
    generated.city_id = page.city_id
    generated.county_id = page.county_id
    generated.meta_title = draft.meta_title
    generated.meta_description = draft.meta_description
    generated.h1 = draft.h1
    generated.draft_content = payload
    generated.content_body = _render_common_draft(draft)
    generated.generation_status = "generated"
    generated.generated_at = now
    generated.qa_status = "not_run"
    generated.qa_result = None
    generated.qa_checked_at = None
    generated.status = "draft"
    generated.updated_at = now
    page.planning_status = "drafted"
    page.updated_at = now
    session.add(generated)
    session.add(page)
    session.commit()
    session.refresh(generated)
    return generated, readiness


def _build_draft(
    session: Session,
    page: PlannedPage,
    record: PlanningRecord,
) -> PlannedPageDraftContent:
    context = build_website_context(session, website_id=page.website_id)
    business = session.get(Business, context.business.id)
    service = session.get(Service, page.service_id) if page.service_id else None
    knowledge = _approved_knowledge(session, context.business.id, service)
    effective_answers = dict(record.generated_answers)
    effective_answers.update(record.operator_overrides)
    brand_name = context.identity.display_name
    contact = _contact_text(context.business.phone, context.business.email, context.website.public_url)
    service_area = _service_area(context.business.main_city, context.business.state)
    primary_action = str(
        effective_answers.get("primary_action")
        or "Contact the company for the appropriate next step."
    )
    call_to_action = f"{primary_action} {contact}"

    title: str
    h1: str
    intro: str
    sections: list[DraftSection]
    faq_items: list[dict[str, str]] = []

    if page.page_type == "home":
        title = brand_name
        h1 = brand_name
        intro = (
            business.description
            if business and _has_text(business.description)
            else f"{brand_name} serves customers in {service_area}."
        )
        services = [
            f"{item.service_name}: {item.short_description or item.long_description}"
            for item in context.services
            if item.status == "active"
            and (_has_text(item.short_description) or _has_text(item.long_description))
        ]
        sections = [
            DraftSection(
                key="primary_services",
                heading="Services",
                body="\n".join(f"- {item}" for item in services),
            ),
            DraftSection(
                key="trust",
                heading="Why Customers Choose Us",
                body=_trust_text(context),
            ),
            DraftSection(
                key="service_area",
                heading="Service Area",
                body=f"{brand_name} serves {service_area}.",
            ),
        ]
    elif page.page_type == "about":
        title = f"About {brand_name}"
        h1 = title
        intro = business.description or context.brand.description or title
        sections = [
            DraftSection(
                key="company_story",
                heading="Company Story",
                body=business.description or context.brand.description or title,
            ),
            DraftSection(
                key="experience",
                heading="Experience and Trust",
                body=_trust_text(context),
            ),
            DraftSection(
                key="mission",
                heading="Our Purpose",
                body=str(effective_answers.get("purpose") or title),
            ),
        ]
    elif page.page_type == "contact":
        title = f"Contact {brand_name}"
        h1 = title
        intro = f"Use an approved contact method to reach {brand_name}."
        hours = context.website.configuration.get("business_hours")
        sections = [
            DraftSection(
                key="ways_to_contact",
                heading="Ways to Contact Us",
                body=contact,
            ),
            DraftSection(
                key="hours",
                heading="Hours",
                body=str(hours) if _has_text(hours) else "Contact the office for current availability.",
            ),
            DraftSection(
                key="service_area",
                heading="Service Area",
                body=f"Primary service area: {service_area}.",
            ),
        ]
    elif page.page_type == "service":
        if service is None:
            raise PlannedPageDraftingError("Service relationship could not be resolved.")
        title = service.service_name
        h1 = service.service_name
        intro = service.short_description or service.long_description or service.service_name
        sections = [
            DraftSection(
                key="service_overview",
                heading="Service Overview",
                body=service.long_description or service.short_description or service.service_name,
            ),
            DraftSection(
                key="approved_guidance",
                heading="What Customers Should Know",
                body=_knowledge_body(knowledge),
            ),
            DraftSection(
                key="service_area",
                heading="Service Area",
                body=f"This service is available in the approved service area, including {service_area}.",
            ),
        ]
    elif page.page_type == "informational":
        title = page.working_name
        h1 = page.working_name
        intro = str(effective_answers.get("purpose") or page.working_name)
        sections = [
            DraftSection(
                key="approved_information",
                heading="Approved Information",
                body=_knowledge_body(knowledge),
            ),
            DraftSection(
                key="next_steps",
                heading="Next Steps",
                body=primary_action,
            ),
        ]
    elif page.page_type == "faq":
        title = page.working_name or "Frequently Asked Questions"
        h1 = title
        intro = "Review answers drawn from approved business knowledge."
        faq_items = [
            {"question": item.question, "answer": item.short_answer}
            for item in knowledge
        ]
        sections = [
            DraftSection(
                key="contact",
                heading="Still Have Questions?",
                body=contact,
            )
        ]
    else:
        raise PlannedPageDraftingError(f"Unsupported page type: {page.page_type}")

    meta_description = _meta_description(intro, brand_name)
    return PlannedPageDraftContent(
        page_type=page.page_type,
        title=title,
        meta_title=f"{title} | {brand_name}" if title != brand_name else brand_name,
        meta_description=meta_description,
        h1=h1,
        intro=intro,
        sections=sections,
        faq_items=faq_items,
        call_to_action=call_to_action,
        internal_notes=(
            "Deterministic local draft assembled from approved Website Context and "
            f"Planning Record #{record.id}. Human review is required. No external AI service was called."
        ),
        planning_record_id=record.id or 0,
        planning_generated_at=record.generated_at,
        operator_override_keys=sorted(record.operator_overrides),
    )


def _new_generated_page(session: Session, page: PlannedPage) -> GeneratedPage:
    context = build_website_context(session, website_id=page.website_id)
    return GeneratedPage(
        business_id=context.business.id,
        website_id=page.website_id,
        service_id=page.service_id,
        city_id=page.city_id,
        county_id=page.county_id,
        page_type=page.page_type,
        page_title=page.working_name,
        page_slug=page.intended_slug,
        status="draft",
        generation_status="not_generated",
    )


def _ensure_city_service_compatibility_page(
    session: Session,
    page: PlannedPage,
) -> GeneratedPage:
    generated = (
        session.get(GeneratedPage, page.generated_page_id)
        if page.generated_page_id is not None
        else None
    )
    if generated:
        return generated
    if not page.service_id or not page.city_id:
        raise PlannedPageDraftingError(
            "City-Service compatibility requires Service and City relationships."
        )
    city = session.get(City, page.city_id)
    county_id = page.county_id or (city.county_id if city else None)
    if county_id is None:
        raise PlannedPageDraftingError(
            "City-Service compatibility requires an approved County relationship."
        )
    page.county_id = county_id
    generated = _new_generated_page(session, page)
    session.add(generated)
    session.flush()
    page.generated_page_id = generated.id
    session.add(page)
    session.flush()
    return generated


def _ensure_refresh_allowed(page: GeneratedPage, *, allow_overwrite: bool) -> None:
    if page.status in {"approved", "published"}:
        raise PlannedPageDraftingError(
            f"Protected {page.status} pages cannot be refreshed by the drafting foundation."
        )
    if page.generation_status == "generated" and not allow_overwrite:
        raise PlannedPageDraftingError(
            "A draft already exists; use Refresh Draft to replace the reviewable draft."
        )


def _approved_knowledge(
    session: Session,
    business_id: int,
    service: Service | None,
) -> list[KnowledgeBlock]:
    statement = select(KnowledgeBlock).where(
        KnowledgeBlock.business_id == business_id,
        KnowledgeBlock.status == "active",
    )
    if service is not None:
        statement = statement.where(KnowledgeBlock.service_id == service.id)
    return list(session.exec(statement.order_by(KnowledgeBlock.sort_order, KnowledgeBlock.id)).all())


def _render_common_draft(draft: PlannedPageDraftContent) -> str:
    section_text = "\n\n".join(
        f"## {section.heading}\n{section.body}"
        for section in draft.sections
    )
    faq_text = "\n\n".join(
        f"### {item['question']}\n{item['answer']}"
        for item in draft.faq_items
    )
    parts = [draft.intro, section_text, faq_text, f"## Next Step\n{draft.call_to_action}"]
    return "\n\n".join(part for part in parts if part)


def _knowledge_body(knowledge: list[KnowledgeBlock]) -> str:
    return "\n\n".join(
        f"### {item.title}\n{item.long_answer}"
        for item in knowledge
    )


def _trust_text(context) -> str:
    values = []
    if _has_text(context.business.license_number):
        values.append(f"License: {context.business.license_number}.")
    if _has_text(context.business.certified_operator):
        values.append(f"Certified operator: {context.business.certified_operator}.")
    if _has_text(context.brand.description):
        values.append(str(context.brand.description))
    return " ".join(values)


def _contact_text(phone: str | None, email: str | None, public_url: str | None) -> str:
    values = []
    if _has_text(phone):
        values.append(f"Phone: {phone}.")
    if _has_text(email):
        values.append(f"Email: {email}.")
    if _has_text(public_url):
        values.append(f"Website: {public_url}.")
    return " ".join(values)


def _service_area(city: str | None, state: str | None) -> str:
    return ", ".join(value for value in (city, state) if _has_text(value))


def _meta_description(intro: str, brand_name: str) -> str:
    value = " ".join(str(intro).split())
    if brand_name.lower() not in value.lower():
        value = f"{brand_name}: {value}"
    return value[:157].rstrip(" ,.;") + ("." if value else "")


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
