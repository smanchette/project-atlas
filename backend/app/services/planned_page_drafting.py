from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import re
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
    SitePlan,
)
from app.schemas.site_plans import (
    DraftReadinessRead,
    DraftSection,
    PlannedPageDraftContent,
)
from app.schemas.generation import DraftContent
from app.services.draft_generation import (
    DraftGenerationError,
    generate_page_draft,
    validate_safe_content,
)
from app.services.drafting_eligibility import (
    DraftingEligibilityError,
    require_effective_drafting_eligibility,
)
from app.services.county_page_contract import (
    CountyPageContractError,
    build_county_page_context,
)
from app.services.website_context import build_website_context
from app.services.public_destination_copy import (
    PublicDestinationCopyError,
    build_public_destination_copy,
)


SUPPORTED_PAGE_TYPES = {
    "home",
    "about",
    "contact",
    "service",
    "county",
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
    elif page.page_type == "county":
        county = session.get(County, page.county_id) if page.county_id else None
        try:
            county_context = (
                build_county_page_context(
                    session,
                    website_id=page.website_id,
                    site_plan_id=page.site_plan_id,
                    county_id=page.county_id or 0,
                    service_id=page.service_id,
                )
                if county
                else None
            )
        except CountyPageContractError:
            county_context = None
        checks.extend(
            [
                (
                    "county_relationship",
                    county is not None,
                    "Assign an approved County to this County page.",
                ),
                (
                    "approved_service_county_page",
                    bool(county_context and county_context.has_approved_value),
                    (
                        "Approve this exact Service × County page and at least one "
                        "related Service × City relationship for this Website."
                    ),
                ),
                (
                    "approved_county_cities",
                    bool(county_context and county_context.included_cities),
                    "Approve at least one included City in this County.",
                ),
                (
                    "service_relationship",
                    bool(county_context and county_context.service),
                    "Assign exactly one approved Website Service to this County page.",
                ),
                (
                    "primary_call_to_action",
                    bool(contact_methods),
                    "Add an approved phone number or email for the call to action.",
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
    try:
        require_effective_drafting_eligibility(
            session,
            planned_page_id,
            operation="Planned Page drafting",
        )
    except DraftingEligibilityError as exc:
        raise PlannedPageDraftingError(str(exc)) from exc
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

    draft = _build_draft(session, page, record, generated)
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
    generated: GeneratedPage,
) -> PlannedPageDraftContent:
    context = build_website_context(session, website_id=page.website_id)
    service = session.get(Service, page.service_id) if page.service_id else None
    knowledge = _approved_knowledge(session, context.business.id, service)
    brand_name = context.identity.display_name
    contact = _contact_text(context.business.phone, context.business.email)
    service_area = _service_area(context.business.main_city, context.business.state)
    safe_business_description = _public_business_description(context.business.description)
    call_to_action = _public_call_to_action(session, page, context, service)
    meta_description_override: str | None = None

    title: str
    h1: str
    intro: str
    sections: list[DraftSection]
    faq_items: list[dict[str, str]] = []
    image_placements: list[dict[str, str]] = []
    related_pages: list[dict[str, str]] = []

    if page.page_type == "home":
        title = brand_name
        h1 = brand_name
        intro = safe_business_description or f"{brand_name} serves customers in {service_area}."
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
        intro = (
            f"Learn about {brand_name} and its "
            f"{_primary_service_name(context).lower()} service across "
            f"{_service_region(context)}."
        )
        meta_description_override = _meta_description(
            safe_business_description,
            brand_name,
        )
        sections = [
            DraftSection(
                key="company_story",
                heading="Company Story",
                body=safe_business_description or title,
            ),
            DraftSection(
                key="experience",
                heading="Experience and Trust",
                body=_trust_text(context),
            ),
            DraftSection(
                key="mission",
                heading="Our Purpose",
                body=_mission_text(context),
            ),
        ]
    elif page.page_type == "contact":
        title = f"Contact {brand_name}"
        h1 = title
        intro = (
            f"Contact {brand_name} by phone or email to discuss "
            f"{_primary_service_name(context).lower()} and request an estimate."
        )
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
                body=(
                    f"{brand_name} provides {service.service_name.lower()} throughout "
                    f"its {_service_region(context)} service area."
                ),
            ),
        ]
    elif page.page_type == "county":
        if page.county_id is None or page.service_id is None:
            raise PlannedPageDraftingError(
                "County drafting requires exactly one Service and one County relationship."
            )
        try:
            county_context = build_county_page_context(
                session,
                website_id=page.website_id,
                site_plan_id=page.site_plan_id,
                county_id=page.county_id,
                service_id=page.service_id,
            )
        except CountyPageContractError as exc:
            raise PlannedPageDraftingError(str(exc)) from exc
        if not county_context.has_approved_value:
            raise PlannedPageDraftingError(
                "County drafting requires approved included-city and Service × City value."
            )
        county = county_context.county
        service = county_context.service
        state_name = _governed_state_name(context, county.state)
        title = page.working_name or (
            f"{service.service_name} in {county.county_name}, {state_name}"
        )
        h1 = title
        city_names = [item.city_name for item in county_context.included_cities]
        intro = (
            f"{brand_name} provides {service.service_name.lower()} for homes and "
            f"properties throughout {county.county_name}. Our team helps customers "
            "understand the process, prepare with confidence, and choose the right next step."
        )
        related_planned = [
            planned
            for related_id in county_context.related_city_service_page_ids
            if (planned := session.get(PlannedPage, related_id)) is not None
        ]
        related_pages = [
            {"label": item.working_name, "slug": item.intended_slug}
            for item in related_planned
        ]
        city_links = ", ".join(city_names)
        service_description = (
            service.long_description
            or service.short_description
            or f"Professional {service.service_name.lower()} for local properties."
        )
        expectations = (
            _knowledge_body(knowledge)
            if knowledge
            else (
                "Customers receive clear preparation guidance, coordinated scheduling, "
                "and an opportunity to ask questions before service begins."
            )
        )
        trust = _trust_text(context) or (
            f"{brand_name} serves local property owners with careful communication "
            "and service guidance from the first call through follow-up."
        )
        sections = [
            DraftSection(
                key="service_county_intro",
                heading=f"{service.service_name} for {county.county_name}",
                body=service_description,
            ),
            DraftSection(
                key="cities_served",
                heading=f"Cities We Serve in {county.county_name}",
                body=city_links,
            ),
            DraftSection(
                key="how_service_works",
                heading=f"How {service.service_name} Works",
                body=(
                    f"Our team coordinates each {service.service_name.lower()} project "
                    "from the initial conversation through preparation, service, and follow-up."
                ),
            ),
            DraftSection(
                key="customer_expectations",
                heading="What Customers Can Expect",
                body=expectations,
            ),
            DraftSection(
                key="preparation_guidance",
                heading="Preparing for Service",
                body=(
                    "Preparation depends on the property and service plan. Our team "
                    "provides clear instructions before work begins and answers questions along the way."
                ),
            ),
            DraftSection(
                key="trust_and_license",
                heading=f"Why Choose {brand_name}",
                body=trust,
            ),
            DraftSection(
                key="related_city_services",
                heading=f"Explore {service.service_name} Near You",
                body=(
                    ", ".join(item.working_name for item in related_planned)
                    if related_planned
                    else f"Contact {brand_name} to discuss service in {county.county_name}."
                ),
            ),
        ]
        faq_items = [
            {"question": item.question, "answer": item.short_answer}
            for item in knowledge
            if item.question and item.short_answer
        ][:6]
        image_placements = [
            {
                "key": "hero",
                "purpose": f"Hero image for {service.service_name} in {county.county_name}",
                "status": "planned",
            },
            {
                "key": "service",
                "purpose": f"Service process image for {service.service_name}",
                "status": "planned",
            },
            {
                "key": "local",
                "purpose": f"Property or community image for {county.county_name}",
                "status": "planned",
            },
        ]
        meta_description_override = (
            f"{brand_name} provides {service.service_name.lower()} for homes and "
            f"properties throughout {county.county_name}. Learn about preparation, "
            "service, and next steps."
        )
    elif page.page_type == "informational":
        title = page.working_name
        h1 = page.working_name
        intro = f"Learn more about {page.working_name}."
        sections = [
            DraftSection(
                key="approved_information",
                heading="Information",
                body=_knowledge_body(knowledge),
            ),
            DraftSection(
                key="next_steps",
                heading="Next Steps",
                body=call_to_action,
            ),
        ]
    elif page.page_type == "faq":
        title = page.working_name or "Frequently Asked Questions"
        h1 = title
        service_name = _primary_service_name(context)
        intro = (
            f"Find answers to common questions about {service_name.lower()}, "
            "preparation, timing, safety, and re-entry."
        )
        meta_description_override = (
            f"Find answers to common questions about {service_name} from {brand_name}."
        )
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

    meta_description = meta_description_override or _meta_description(intro, brand_name)
    draft = PlannedPageDraftContent(
        page_type=page.page_type,
        title=title,
        meta_title=f"{title} | {brand_name}" if title != brand_name else brand_name,
        meta_description=meta_description,
        h1=h1,
        intro=intro,
        sections=sections,
        faq_items=faq_items,
        image_placements=image_placements,
        related_pages=related_pages,
        call_to_action=call_to_action,
        internal_notes=(
            "Deterministic local draft assembled from approved Website Context and "
            f"Planning Record #{record.id}. Human review is required. No external AI service was called."
        ),
        planning_record_id=record.id or 0,
        planning_generated_at=record.generated_at,
        operator_override_keys=sorted(record.operator_overrides),
    )
    plan = session.get(SitePlan, page.site_plan_id)
    if plan is None:
        raise PlannedPageDraftingError("Site Plan could not be resolved for public destination copy.")
    projection = build_public_destination_copy(
        session,
        plan,
        page,
        generated,
        draft_content=draft.model_dump(mode="json"),
    )
    return draft.model_copy(update={"public_destination_copy": projection})


def build_public_copy_reconciled_draft(
    session: Session,
    planned_page: PlannedPage,
    current_draft: dict[str, Any],
) -> dict[str, Any]:
    """Build the exact source-owned successor without rewriting custom copy.

    This function intentionally recognizes only deterministic generator output
    owned by this module. Operator intent records and custom public prose are
    preserved. A known internal phrase that remains after the exact repairs
    fails closed instead of being replaced heuristically.
    """

    if not isinstance(current_draft, dict):
        raise PublicDestinationCopyError("Generated Page draft must be an object.")
    if planned_page.id is None or planned_page.generated_page_id is None:
        raise PublicDestinationCopyError(
            "Public-copy reconciliation requires exact Planned and Generated Page identities."
        )
    generated = session.get(GeneratedPage, planned_page.generated_page_id)
    plan = session.get(SitePlan, planned_page.site_plan_id)
    if generated is None or plan is None:
        raise PublicDestinationCopyError(
            "Public-copy reconciliation cannot resolve its Generated Page or Site Plan."
        )
    if (
        generated.website_id != planned_page.website_id
        or generated.page_type != planned_page.page_type
        or plan.id != planned_page.site_plan_id
        or plan.website_id != planned_page.website_id
    ):
        raise PublicDestinationCopyError(
            "Public-copy reconciliation crosses a Website, Site Plan, or page-type boundary."
        )

    candidate = deepcopy(current_draft)
    context = build_website_context(session, website_id=planned_page.website_id)
    service = (
        session.get(Service, planned_page.service_id)
        if planned_page.service_id is not None
        else None
    )
    brand_name = _required_public_text(
        context.identity.display_name,
        "Website Identity display name",
    )
    safe_business_description = _public_business_description(
        context.business.description
    )
    legacy_business_description = (
        str(context.business.description).strip()
        if _has_text(context.business.description)
        else ""
    )
    safe_trust = _trust_text(context)
    legacy_trust = _legacy_trust_text(context)
    safe_cta = _public_call_to_action(
        session,
        planned_page,
        context,
        service,
    )
    legacy_cta = (
        _legacy_call_to_action(session, planned_page, context)
        if planned_page.page_type != "city_service"
        else None
    )

    if planned_page.page_type == "home":
        _replace_exact_top_level(
            candidate,
            "intro",
            legacy_business_description,
            safe_business_description,
        )
        _replace_exact_section(candidate, "trust", legacy_trust, safe_trust)
    elif planned_page.page_type == "about":
        safe_about_intro = (
            f"Learn about {brand_name} and its "
            f"{_primary_service_name(context).lower()} service across "
            f"{_service_region(context)}."
        )
        _replace_exact_top_level(
            candidate,
            "intro",
            legacy_business_description,
            safe_about_intro,
        )
        _replace_exact_section(
            candidate,
            "company_story",
            legacy_business_description,
            safe_business_description,
        )
        _replace_exact_section(candidate, "experience", legacy_trust, safe_trust)
        record = session.exec(
            select(PlanningRecord).where(
                PlanningRecord.planned_page_id == planned_page.id
            )
        ).one_or_none()
        if record is None:
            raise PublicDestinationCopyError(
                "About reconciliation cannot resolve its Planning Record."
            )
        effective = dict(record.generated_answers)
        effective.update(record.operator_overrides)
        _replace_exact_section(
            candidate,
            "mission",
            str(effective.get("purpose") or candidate.get("title") or ""),
            _mission_text(context),
        )
    elif planned_page.page_type == "contact":
        legacy_intro = f"Use an approved contact method to reach {brand_name}."
        safe_intro = (
            f"Contact {brand_name} by phone or email to discuss "
            f"{_primary_service_name(context).lower()} and request an estimate."
        )
        _replace_exact_top_level(candidate, "intro", legacy_intro, safe_intro)
        _replace_exact_top_level(
            candidate,
            "meta_description",
            _legacy_meta_description(legacy_intro, brand_name),
            safe_intro,
        )
        _replace_exact_section(
            candidate,
            "ways_to_contact",
            _legacy_contact_text(
                context.business.phone,
                context.business.email,
                context.website.public_url,
            ),
            _contact_text(context.business.phone, context.business.email),
        )
    elif planned_page.page_type == "faq":
        service_name = _primary_service_name(context)
        legacy_intro = "Review answers drawn from approved business knowledge."
        safe_intro = (
            f"Find answers to common questions about {service_name.lower()}, "
            "preparation, timing, safety, and re-entry."
        )
        safe_meta = (
            f"Find answers to common questions about {service_name} from {brand_name}."
        )
        _replace_exact_top_level(candidate, "intro", legacy_intro, safe_intro)
        _replace_exact_top_level(
            candidate,
            "meta_description",
            _legacy_meta_description(legacy_intro, brand_name),
            safe_meta,
        )
        _replace_exact_section(
            candidate,
            "contact",
            _legacy_contact_text(
                context.business.phone,
                context.business.email,
                context.website.public_url,
            ),
            _contact_text(context.business.phone, context.business.email),
        )
    elif planned_page.page_type == "service" and service is not None:
        legacy_area = (
            "This service is available in the approved service area, including "
            f"{_service_area(context.business.main_city, context.business.state)}."
        )
        safe_area = (
            f"{brand_name} provides {service.service_name.lower()} throughout its "
            f"{_service_region(context)} service area."
        )
        _replace_exact_section(candidate, "service_area", legacy_area, safe_area)
        _remove_internal_knowledge_sentence(candidate, "approved_guidance")
    elif planned_page.page_type == "county" and service is not None:
        county = (
            session.get(County, planned_page.county_id)
            if planned_page.county_id is not None
            else None
        )
        if county is None:
            raise PublicDestinationCopyError(
                "County reconciliation cannot resolve its exact County."
            )
        safe_meta = (
            f"{brand_name} provides {service.service_name.lower()} for homes and "
            f"properties throughout {county.county_name}. Learn about preparation, "
            "service, and next steps."
        )
        legacy_meta = _legacy_meta_description(
            str(candidate.get("intro") or ""),
            brand_name,
        )
        _replace_exact_top_level(
            candidate,
            "meta_description",
            legacy_meta,
            safe_meta,
        )
        _replace_exact_section(
            candidate,
            "trust_and_license",
            legacy_trust,
            safe_trust,
        )
        _remove_internal_knowledge_sentence(candidate, "customer_expectations")

    if planned_page.page_type != "city_service":
        if legacy_cta is None:
            raise PublicDestinationCopyError(
                "Public-copy reconciliation cannot derive the exact legacy call to action."
            )
        _replace_exact_top_level(
            candidate,
            "call_to_action",
            legacy_cta,
            safe_cta,
        )

    projection = build_public_destination_copy(
        session,
        plan,
        planned_page,
        generated,
        draft_content=candidate,
    )
    candidate["public_destination_copy"] = [
        item.model_dump(mode="json") for item in projection
    ]
    _reject_remaining_internal_public_copy(candidate)
    try:
        if candidate.get("schema_version") == "planned-page-draft-v1":
            PlannedPageDraftContent.model_validate(candidate)
        else:
            DraftContent.model_validate(candidate)
        validate_safe_content(candidate)
    except Exception as exc:
        if isinstance(exc, PublicDestinationCopyError):
            raise
        raise PublicDestinationCopyError(
            "Reconciled public draft does not satisfy its exact content contract."
        ) from exc
    return candidate


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


def render_planned_page_content(draft: PlannedPageDraftContent) -> str:
    """Render the approved planned-page contract for local review consumers."""
    return _render_common_draft(draft)


def _knowledge_body(knowledge: list[KnowledgeBlock]) -> str:
    return "\n\n".join(
        f"### {item.title}\n{_public_knowledge_text(item.long_answer)}"
        for item in knowledge
    )


def _trust_text(context) -> str:
    values = []
    if _has_text(context.business.license_number):
        values.append(f"License: {context.business.license_number}.")
    if _has_text(context.business.certified_operator):
        values.append(f"Certified operator: {context.business.certified_operator}.")
    company_name = str(context.business.company_name).strip()
    service_name = _primary_service_name(context)
    region = _service_region(context)
    if company_name and service_name and region:
        values.append(
            f"{company_name} provides {service_name.lower()} across {region}."
        )
    return " ".join(values)


def _contact_text(phone: str | None, email: str | None) -> str:
    values = []
    if _has_text(phone):
        values.append(f"Phone: {phone}.")
    if _has_text(email):
        values.append(f"Email: {email}.")
    return " ".join(values)


def _legacy_contact_text(
    phone: str | None,
    email: str | None,
    public_url: str | None,
) -> str:
    values = []
    if _has_text(phone):
        values.append(f"Phone: {str(phone).strip()}.")
    if _has_text(email):
        values.append(f"Email: {str(email).strip()}.")
    if _has_text(public_url):
        values.append(f"Website: {str(public_url).strip()}.")
    return " ".join(values)


def _service_area(city: str | None, state: str | None) -> str:
    return ", ".join(value for value in (city, state) if _has_text(value))


def _governed_state_name(context, state_code: str) -> str:
    configured = context.website.configuration.get("state_name")
    market_codes = context.website.configuration.get("market_state_codes")
    if (
        _has_text(configured)
        and isinstance(market_codes, list)
        and len(market_codes) == 1
        and str(market_codes[0]).strip().casefold()
        == str(state_code).strip().casefold()
    ):
        return str(configured).strip()
    return _required_public_text(state_code, "State name")


def _meta_description(intro: str, brand_name: str) -> str:
    value = " ".join(str(intro).split())
    if brand_name.lower() not in value.lower():
        value = f"{brand_name}: {value}"
    if len(value) > 157:
        shortened = value[:158]
        boundary = shortened.rfind(" ")
        if boundary > 0:
            shortened = shortened[:boundary]
        value = shortened
    return value.rstrip(" ,.;") + ("." if value else "")


def _mission_text(context) -> str:
    brand_name = _required_public_text(
        context.identity.display_name,
        "Website Identity display name",
    )
    service_name = _primary_service_name(context)
    region = _service_region(context)
    sentence = f"{brand_name} provides {service_name.lower()} across {region}"
    license_number = context.business.license_number
    if _has_text(license_number):
        license_label = str(
            context.website.configuration.get("license_label") or "License"
        ).strip()
        sentence += f" under {license_label} {str(license_number).strip()}"
    values = [sentence + "."]
    if _has_text(context.business.certified_operator):
        values.append(
            f"Certified operator: {str(context.business.certified_operator).strip()}."
        )
    return " ".join(values)


def _public_call_to_action(
    session: Session,
    page: PlannedPage,
    context,
    service: Service | None,
) -> str:
    brand_name = _required_public_text(
        context.identity.display_name,
        "Website Identity display name",
    )
    service_name = service.service_name if service else _primary_service_name(context)
    if page.page_type == "home":
        return f"Request an Estimate or learn more about {service_name}."
    if page.page_type in {"about", "faq"}:
        return f"Learn more about {service_name} or contact {brand_name}."
    if page.page_type == "contact":
        return f"Call {brand_name} or Request an Estimate."
    if page.page_type == "service":
        return f"Request an Estimate for {service_name}."
    if page.page_type == "county":
        county = session.get(County, page.county_id) if page.county_id else None
        if county is None:
            raise PlannedPageDraftingError(
                "County call to action requires an exact County relationship."
            )
        return (
            f"Explore {service_name} in {county.county_name}, or Request an Estimate."
        )
    return f"Contact {brand_name} to discuss {service_name} or Request an Estimate."


def _primary_service_name(context) -> str:
    active = [item for item in context.services if item.status == "active"]
    if len(active) != 1:
        raise PlannedPageDraftingError(
            "Public copy requires exactly one active primary Service."
        )
    return _required_public_text(active[0].service_name, "Service name")


def _public_business_description(value: str | None) -> str:
    if not _has_text(value):
        return ""
    text = " ".join(str(value).split())
    text = re.sub(
        r"\s+target\s+counties(?=[.,;:]|$)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _service_region(context) -> str:
    description = _public_business_description(context.business.description)
    match = re.search(r"\bacross\s+([^.;]+)", description, flags=re.IGNORECASE)
    if match and match.group(1).strip():
        return match.group(1).strip()
    region = _service_area(context.business.main_city, context.business.state)
    return _required_public_text(region, "Service area")


_INTERNAL_KNOWLEDGE_SENTENCE = (
    "Flo-Zone's public service wording focuses on active drywood termite "
    "infestations unless broader pest claims are separately reviewed and approved "
    "for use."
)


def _public_knowledge_text(value: str) -> str:
    # The legacy sentence follows its public technical predecessor on the same
    # line. Remove adjacent horizontal whitespace with the sentence so the
    # omission cannot leave an orphan space before the preserved paragraph
    # break. New source rows no longer contain this sentence, but this exact
    # normalization remains necessary for revisioning legacy generated drafts.
    return re.sub(
        rf"[ \t]*{re.escape(_INTERNAL_KNOWLEDGE_SENTENCE)}",
        "",
        str(value),
    ).strip()


def _required_public_text(value: Any, label: str) -> str:
    if not _has_text(value):
        raise PlannedPageDraftingError(f"{label} is required for public copy.")
    return str(value).strip()


def _legacy_trust_text(context) -> str:
    values: list[str] = []
    if _has_text(context.business.license_number):
        values.append(f"License: {str(context.business.license_number).strip()}.")
    if _has_text(context.business.certified_operator):
        values.append(
            f"Certified operator: {str(context.business.certified_operator).strip()}."
        )
    if _has_text(context.brand.description):
        values.append(str(context.brand.description).strip())
    return " ".join(values)


def _legacy_call_to_action(
    session: Session,
    page: PlannedPage,
    context,
) -> str:
    record = session.exec(
        select(PlanningRecord).where(PlanningRecord.planned_page_id == page.id)
    ).one_or_none()
    if record is None:
        raise PublicDestinationCopyError(
            "Public-copy reconciliation cannot resolve its Planning Record."
        )
    effective = dict(record.generated_answers)
    effective.update(record.operator_overrides)
    primary_action = str(
        effective.get("primary_action")
        or "Contact the company for the appropriate next step."
    )
    values: list[str] = []
    if _has_text(context.business.phone):
        values.append(f"Phone: {str(context.business.phone).strip()}.")
    if _has_text(context.business.email):
        values.append(f"Email: {str(context.business.email).strip()}.")
    if _has_text(context.website.public_url):
        values.append(f"Website: {str(context.website.public_url).strip()}.")
    return f"{primary_action} {' '.join(values)}"


def _legacy_meta_description(intro: str, brand_name: str) -> str:
    value = " ".join(str(intro).split())
    if brand_name.lower() not in value.lower():
        value = f"{brand_name}: {value}"
    return value[:157].rstrip(" ,.;") + ("." if value else "")


def _replace_exact_top_level(
    draft: dict[str, Any],
    field: str,
    original: str,
    replacement: str,
) -> None:
    current = draft.get(field)
    if current == original or current == replacement:
        draft[field] = replacement
        return
    raise PublicDestinationCopyError(
        f"Public-copy field is neither the exact authorized before nor after value: {field}."
    )


def _replace_exact_section(
    draft: dict[str, Any],
    section_key: str,
    original: str,
    replacement: str,
) -> None:
    sections = draft.get("sections")
    if not isinstance(sections, list):
        raise PublicDestinationCopyError("Planned draft sections are malformed.")
    matches = [
        item
        for item in sections
        if isinstance(item, dict) and item.get("key") == section_key
    ]
    if len(matches) != 1:
        raise PublicDestinationCopyError(
            f"Planned draft section does not resolve exactly once: {section_key}."
        )
    current = matches[0].get("body")
    if current == original or current == replacement:
        matches[0]["body"] = replacement
        return
    raise PublicDestinationCopyError(
        "Public-copy section is neither the exact authorized before nor after value: "
        f"{section_key}."
    )


def _remove_internal_knowledge_sentence(
    draft: dict[str, Any],
    section_key: str,
) -> None:
    sections = draft.get("sections")
    if not isinstance(sections, list):
        raise PublicDestinationCopyError("Planned draft sections are malformed.")
    matches = [
        item
        for item in sections
        if isinstance(item, dict) and item.get("key") == section_key
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("body"), str):
        raise PublicDestinationCopyError(
            f"Knowledge section does not resolve exactly once: {section_key}."
        )
    body = matches[0]["body"]
    if body.count(_INTERNAL_KNOWLEDGE_SENTENCE) > 1:
        raise PublicDestinationCopyError(
            "Knowledge section contains the internal sentence more than once."
        )
    matches[0]["body"] = _public_knowledge_text(body)


_REMAINING_INTERNAL_PUBLIC_PHRASES = (
    "atlas",
    "approved business knowledge",
    "approved destination",
    "approved service plan",
    "approved service area",
    "city-service-to-contact conversion path",
    "connect the city-service page",
    "connect the service-county page",
    "exact service-county owner",
    "explain the business identity",
    "guide visitors",
    "provide a useful path",
    "public-facing brand",
    "target counties",
    "use an approved contact method",
)


def _reject_remaining_internal_public_copy(draft: dict[str, Any]) -> None:
    for path, value in _iter_reconciled_public_strings(draft):
        normalized = " ".join(value.casefold().split())
        matched = next(
            (
                phrase
                for phrase in _REMAINING_INTERNAL_PUBLIC_PHRASES
                if phrase in normalized
            ),
            None,
        )
        if matched:
            raise PublicDestinationCopyError(
                f"Known internal public copy remains at {path}: {matched}."
            )


def _iter_reconciled_public_strings(draft: dict[str, Any]):
    for key in (
        "title",
        "meta_title",
        "meta_description",
        "h1",
        "intro",
        "why_it_matters",
        "signs_section",
        "process_section",
        "prep_section",
        "realtor_property_manager_section",
        "call_to_action",
    ):
        value = draft.get(key)
        if isinstance(value, str):
            yield key, value
    for index, section in enumerate(draft.get("sections", [])):
        if not isinstance(section, dict):
            continue
        for key in ("heading", "body"):
            value = section.get(key)
            if isinstance(value, str):
                yield f"sections.{index}.{key}", value
    for index, item in enumerate(draft.get("faq_items", [])):
        if not isinstance(item, dict):
            continue
        for key in ("question", "answer"):
            value = item.get(key)
            if isinstance(value, str):
                yield f"faq_items.{index}.{key}", value
    for index, item in enumerate(draft.get("public_destination_copy", [])):
        if not isinstance(item, dict):
            continue
        for key in ("label", "description"):
            value = item.get(key)
            if isinstance(value, str):
                yield f"public_destination_copy.{index}.{key}", value


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
