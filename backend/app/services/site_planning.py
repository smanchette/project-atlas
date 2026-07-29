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
    SitePlan,
    Website,
)
from app.schemas.site_plans import (
    PlannedPageCreate,
    PlannedPageRead,
    PlannedPageUpdate,
    PlanningRecordRead,
    SitePlanCreate,
    SitePlanDetail,
    SitePlanRead,
    SitePlanUpdate,
)
from app.services.website_context import build_website_context


PAGE_TYPES = {
    "home",
    "about",
    "contact",
    "service",
    "county",
    "city",
    "city_service",
    "informational",
    "faq",
}
PLANNING_ANSWER_KEYS = {
    "purpose",
    "audiences",
    "required_facts",
    "missing_required_facts",
    "relationships",
    "primary_action",
}
PURPOSES = {
    "home": "Introduce the business, establish trust, and guide visitors to the most relevant next step.",
    "about": "Explain the business identity, experience, qualifications, and reasons customers can trust it.",
    "contact": "Help prospective and existing customers contact the business through approved channels.",
    "service": "Explain an approved service and help qualified visitors decide on the next step.",
    "county": "Explain legitimate service coverage for a county or broader service area.",
    "city": "Explain legitimate service coverage and local relevance for a city or local area.",
    "city_service": "Explain an approved service for a legitimate local service area without unsupported localization.",
    "informational": "Explain an approved topic that supports customer understanding and informed next steps.",
    "faq": "Answer approved common questions and direct visitors to appropriate supporting pages or contact options.",
}
PRIMARY_ACTIONS = {
    "home": "Request an estimate or select a relevant service.",
    "about": "Learn about a service or contact the company.",
    "contact": "Contact the company through an approved channel.",
    "service": "Request an estimate for the service.",
    "county": "Find the relevant local service or request an estimate.",
    "city": "Find the relevant service or contact the company.",
    "city_service": "Request an estimate for the service in this area.",
    "informational": "Continue to a related service or contact the company.",
    "faq": "Continue to a relevant service page or contact the company.",
}


class SitePlanningError(ValueError):
    pass


def create_site_plan(session: Session, payload: SitePlanCreate) -> SitePlan:
    website = _website(session, payload.website_id)
    existing = session.exec(
        select(SitePlan).where(
            SitePlan.website_id == website.id,
            SitePlan.plan_key == payload.plan_key,
        )
    ).first()
    if existing:
        raise SitePlanningError("A Site Plan with this key already exists for the Website.")
    plan = SitePlan(**payload.model_dump())
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def update_site_plan(session: Session, plan_id: int, payload: SitePlanUpdate) -> SitePlan:
    plan = _site_plan(session, plan_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, key, value)
    plan.updated_at = datetime.now(UTC)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def list_site_plans(session: Session, *, website_id: int | None = None) -> list[SitePlan]:
    statement = select(SitePlan)
    if website_id is not None:
        _website(session, website_id)
        statement = statement.where(SitePlan.website_id == website_id)
    return list(session.exec(statement.order_by(SitePlan.website_id, SitePlan.id)).all())


def site_plan_detail(session: Session, plan_id: int) -> SitePlanDetail:
    plan = _site_plan(session, plan_id)
    pages = list(
        session.exec(
            select(PlannedPage)
            .where(PlannedPage.site_plan_id == plan.id)
            .order_by(PlannedPage.id)
        ).all()
    )
    return SitePlanDetail(
        **SitePlanRead.model_validate(plan).model_dump(),
        planned_pages=[planned_page_read(session, page) for page in pages],
    )


def create_planned_page(session: Session, payload: PlannedPageCreate) -> PlannedPageRead:
    values = payload.model_dump()
    _validate_planned_page_values(session, values)
    page = PlannedPage(**values)
    session.add(page)
    session.flush()
    record = _new_planning_record(session, page)
    session.add(record)
    session.commit()
    session.refresh(page)
    return planned_page_read(session, page)


def update_planned_page(
    session: Session,
    planned_page_id: int,
    payload: PlannedPageUpdate,
) -> PlannedPageRead:
    page = _planned_page(session, planned_page_id)
    values = {
        **page.model_dump(),
        **payload.model_dump(exclude_unset=True),
        "website_id": page.website_id,
        "site_plan_id": page.site_plan_id,
    }
    _validate_planned_page_values(session, values, planned_page_id=page.id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(page, key, value)
    page.updated_at = datetime.now(UTC)
    session.add(page)
    session.flush()
    refresh_planning_record(session, page.id or planned_page_id, commit=False)
    session.commit()
    session.refresh(page)
    return planned_page_read(session, page)


def refresh_planning_record(
    session: Session,
    planned_page_id: int,
    *,
    commit: bool = True,
) -> PlanningRecordRead:
    page = _planned_page(session, planned_page_id)
    record = session.exec(
        select(PlanningRecord).where(PlanningRecord.planned_page_id == page.id)
    ).first()
    answers, snapshot, score, missing, recommendations = _planning_material(session, page)
    if record is None:
        record = PlanningRecord(planned_page_id=page.id or planned_page_id)
    record.generated_answers = answers
    record.source_snapshot = snapshot
    record.confidence_score = score
    record.confidence_level = _confidence_level(score)
    record.missing_information = missing
    record.improvement_recommendations = recommendations
    record.generated_at = datetime.now(UTC)
    record.updated_at = datetime.now(UTC)
    session.add(record)
    if commit:
        session.commit()
        session.refresh(record)
    else:
        session.flush()
    return planning_record_read(record)


def update_planning_overrides(
    session: Session,
    planned_page_id: int,
    operator_overrides: dict[str, Any],
) -> PlanningRecordRead:
    unknown = sorted(set(operator_overrides) - PLANNING_ANSWER_KEYS)
    if unknown:
        raise SitePlanningError(
            f"Unsupported Planning Record override fields: {', '.join(unknown)}"
        )
    page = _planned_page(session, planned_page_id)
    record = session.exec(
        select(PlanningRecord).where(PlanningRecord.planned_page_id == page.id)
    ).first()
    if record is None:
        refresh_planning_record(session, planned_page_id)
        record = session.exec(
            select(PlanningRecord).where(PlanningRecord.planned_page_id == page.id)
        ).one()
    record.operator_overrides = dict(operator_overrides)
    record.reviewed_at = datetime.now(UTC)
    record.updated_at = datetime.now(UTC)
    session.add(record)
    session.commit()
    session.refresh(record)
    return planning_record_read(record)


def planned_page_read(session: Session, page: PlannedPage) -> PlannedPageRead:
    from app.services.planned_page_drafting import evaluate_draft_readiness

    record = session.exec(
        select(PlanningRecord).where(PlanningRecord.planned_page_id == page.id)
    ).first()
    if record is None:
        record_read = refresh_planning_record(session, page.id or 0)
    else:
        record_read = planning_record_read(record)
    generated = (
        session.get(GeneratedPage, page.generated_page_id)
        if page.generated_page_id is not None
        else None
    )
    return PlannedPageRead(
        **page.model_dump(),
        generated_page_status=generated.generation_status if generated else None,
        generated_draft=generated.draft_content if generated else None,
        draft_readiness=evaluate_draft_readiness(session, page, record=record),
        planning_record=record_read,
    )


def planning_record_read(record: PlanningRecord) -> PlanningRecordRead:
    effective = dict(record.generated_answers)
    effective.update(record.operator_overrides)
    return PlanningRecordRead(
        **record.model_dump(),
        effective_answers=effective,
    )


def ensure_primary_site_plan(session: Session, website: Website) -> SitePlan:
    plan = session.exec(
        select(SitePlan).where(
            SitePlan.website_id == website.id,
            SitePlan.plan_key == "primary",
        )
    ).first()
    if plan:
        return plan
    plan = SitePlan(
        website_id=website.id or 0,
        plan_key="primary",
        plan_name=f"{website.website_name} Site Plan",
        status="draft",
    )
    session.add(plan)
    session.flush()
    return plan


def backfill_existing_generated_pages(session: Session) -> int:
    created = 0
    pages = list(
        session.exec(
            select(GeneratedPage)
            .where(GeneratedPage.website_id.is_not(None))
            .order_by(GeneratedPage.id)
        ).all()
    )
    for generated in pages:
        if generated.website_id is None or generated.id is None:
            continue
        existing = session.exec(
            select(PlannedPage).where(PlannedPage.generated_page_id == generated.id)
        ).first()
        if existing:
            continue
        website = _website(session, generated.website_id)
        plan = ensure_primary_site_plan(session, website)
        planned = PlannedPage(
            website_id=website.id or 0,
            site_plan_id=plan.id or 0,
            page_type=generated.page_type,
            working_name=generated.page_title,
            intended_slug=generated.page_slug,
            service_id=generated.service_id,
            city_id=generated.city_id,
            county_id=generated.county_id,
            planning_status="generated",
            generated_page_id=generated.id,
        )
        session.add(planned)
        session.flush()
        session.add(_new_planning_record(session, planned))
        created += 1
    session.commit()
    return created


def _new_planning_record(session: Session, page: PlannedPage) -> PlanningRecord:
    answers, snapshot, score, missing, recommendations = _planning_material(session, page)
    return PlanningRecord(
        planned_page_id=page.id or 0,
        generated_answers=answers,
        operator_overrides={},
        source_snapshot=snapshot,
        confidence_score=score,
        confidence_level=_confidence_level(score),
        missing_information=missing,
        improvement_recommendations=recommendations,
        generated_at=datetime.now(UTC),
    )


def _planning_material(
    session: Session,
    page: PlannedPage,
) -> tuple[dict[str, Any], dict[str, Any], float, list[str], list[str]]:
    website = _website(session, page.website_id)
    business = session.get(Business, website.business_id)
    if not business:
        raise SitePlanningError("Website business could not be resolved.")
    context = build_website_context(
        session,
        website_id=website.id,
        business_id=business.id,
    )
    service = session.get(Service, page.service_id) if page.service_id else None
    city = session.get(City, page.city_id) if page.city_id else None
    county = session.get(County, page.county_id) if page.county_id else None
    knowledge_statement = select(KnowledgeBlock).where(
        KnowledgeBlock.business_id == business.id,
        KnowledgeBlock.status == "active",
    )
    if service is not None:
        knowledge_statement = knowledge_statement.where(
            KnowledgeBlock.service_id == service.id
        )
    knowledge = list(
        session.exec(knowledge_statement.order_by(KnowledgeBlock.sort_order)).all()
    )

    configured_audiences = context.website.configuration.get("target_customer_types")
    audiences = (
        [str(value) for value in configured_audiences if str(value).strip()]
        if isinstance(configured_audiences, list)
        else []
    )
    if not audiences:
        audiences = sorted(
            {
                block.customer_type
                for block in knowledge
                if block.customer_type and block.customer_type != "general"
            }
        ) or ["General customers"]

    facts = {
        "company_information": bool(business.company_name and business.description),
        "company_description": bool(business.description),
        "contact_information": bool(business.phone or business.email),
        "preferred_contact_methods": bool(business.phone or business.email),
        "website_identity": bool(context.identity.display_name),
        "primary_services": any(
            item.status == "active"
            and (item.short_description or item.long_description)
            for item in context.services
        ),
        "service_information": bool(
            service and (service.short_description or service.long_description)
        ),
        "service_area": bool(city or county or business.main_city),
        "primary_action": bool(business.phone or business.email),
        "trust_information": bool(
            business.license_number
            or business.certified_operator
            or context.brand.description
        ),
        "license": bool(business.license_number),
        "certified_operator": bool(business.certified_operator),
        "approved_knowledge": bool(knowledge),
        "approved_questions_and_answers": bool(knowledge)
        and all(
            item.question and item.short_answer and item.long_answer
            for item in knowledge
        ),
    }
    required_keys = ["website_identity"]
    if page.page_type == "home":
        required_keys.extend(
            ["company_information", "primary_services", "service_area", "primary_action"]
        )
    if page.page_type == "about":
        required_keys.extend(
            ["company_description", "trust_information", "contact_information"]
        )
    if page.page_type == "contact":
        required_keys.extend(
            ["contact_information", "service_area", "preferred_contact_methods"]
        )
    if page.page_type == "service":
        required_keys.extend(["service_information", "primary_action"])
    if page.page_type == "informational":
        required_keys.append("approved_knowledge")
    if page.page_type == "faq":
        required_keys.append("approved_questions_and_answers")
    if page.page_type == "city_service":
        required_keys.extend(
            ["contact_information", "service_information", "approved_knowledge"]
        )
    if page.page_type in {"county", "city"}:
        required_keys.append("contact_information")
    if page.page_type in {"county", "city", "city_service"}:
        required_keys.append("service_area")
    missing_required = [key for key in required_keys if not facts[key]]

    relationships: list[dict[str, Any]] = [
        {"type": "website", "id": website.id, "name": website.website_name},
    ]
    if website.brand_id:
        relationships.append(
            {"type": "brand", "id": website.brand_id, "name": context.brand.public_name}
        )
    if service:
        relationships.append(
            {"type": "service", "id": service.id, "name": service.service_name}
        )
    if county:
        relationships.append(
            {"type": "county", "id": county.id, "name": county.county_name}
        )
    if city:
        relationships.append({"type": "city", "id": city.id, "name": city.city_name})

    required_facts = [
        {"key": key, "available": facts[key]}
        for key in required_keys
    ]
    available_count = sum(facts[key] for key in required_keys)
    score = available_count / len(required_keys) if required_keys else 1.0
    missing_information = [_missing_label(key) for key in missing_required]
    recommendations = list(missing_information)
    if not knowledge:
        recommendations.append("Add approved FAQs or supporting knowledge.")
    if not context.identity.social_identity_image_url:
        recommendations.append("Review supporting brand or page media.")
    recommendations = list(dict.fromkeys(recommendations))
    answers = {
        "purpose": PURPOSES[page.page_type],
        "audiences": audiences,
        "required_facts": required_facts,
        "missing_required_facts": missing_required,
        "relationships": relationships,
        "primary_action": PRIMARY_ACTIONS[page.page_type],
    }
    snapshot = {
        "business_id": business.id,
        "brand_id": website.brand_id,
        "website_id": website.id,
        "website_updated_at": website.updated_at.isoformat(),
        "service_id": service.id if service else None,
        "city_id": city.id if city else None,
        "county_id": county.id if county else None,
        "knowledge_block_ids": [item.id for item in knowledge],
        "provider_sources": ["approved_website_context", "approved_knowledge"],
    }
    return answers, snapshot, round(score, 4), missing_information, recommendations


def _validate_planned_page_values(
    session: Session,
    values: dict[str, Any],
    *,
    planned_page_id: int | None = None,
) -> None:
    page_type = values.get("page_type")
    if page_type not in PAGE_TYPES:
        raise SitePlanningError(f"Unsupported page type: {page_type}")
    website = _website(session, int(values["website_id"]))
    plan = _site_plan(session, int(values["site_plan_id"]))
    if plan.website_id != website.id:
        raise SitePlanningError("Site Plan does not belong to the selected Website.")
    slug = str(values.get("intended_slug") or "").strip().lower()
    if not slug:
        raise SitePlanningError("Planned Page intended slug is required.")
    values["intended_slug"] = slug
    conflict_statement = select(PlannedPage).where(
        PlannedPage.website_id == website.id,
        PlannedPage.intended_slug == slug,
    )
    if planned_page_id is not None:
        conflict_statement = conflict_statement.where(PlannedPage.id != planned_page_id)
    if session.exec(conflict_statement).first():
        raise SitePlanningError("The intended slug is already planned for this Website.")

    service = session.get(Service, values.get("service_id")) if values.get("service_id") else None
    if service and service.business_id != website.business_id:
        raise SitePlanningError("Service does not belong to the Website business.")
    city = session.get(City, values.get("city_id")) if values.get("city_id") else None
    county = session.get(County, values.get("county_id")) if values.get("county_id") else None
    if values.get("service_id") and not service:
        raise SitePlanningError("Service not found.")
    if values.get("city_id") and not city:
        raise SitePlanningError("City not found.")
    if values.get("county_id") and not county:
        raise SitePlanningError("County not found.")
    if city and county and city.county_id != county.id:
        raise SitePlanningError("City does not belong to the selected County.")
    if page_type == "service" and not service:
        raise SitePlanningError("Service pages require a Service relationship.")
    if page_type == "county" and not county:
        raise SitePlanningError("County pages require a County relationship.")
    if page_type == "city" and not city:
        raise SitePlanningError("City pages require a City relationship.")
    if page_type == "city_service" and (not service or not city):
        raise SitePlanningError("City-Service pages require Service and City relationships.")

    parent_id = values.get("parent_planned_page_id")
    if parent_id:
        if parent_id == planned_page_id:
            raise SitePlanningError("A Planned Page cannot be its own parent.")
        parent = _planned_page(session, int(parent_id))
        if parent.site_plan_id != plan.id or parent.website_id != website.id:
            raise SitePlanningError("Parent Planned Page must belong to the same Site Plan.")
    generated_id = values.get("generated_page_id")
    if generated_id:
        generated = session.get(GeneratedPage, int(generated_id))
        if not generated:
            raise SitePlanningError("Generated Page not found.")
        if generated.website_id != website.id or generated.business_id != website.business_id:
            raise SitePlanningError("Generated Page does not belong to the selected Website.")
        existing = session.exec(
            select(PlannedPage).where(PlannedPage.generated_page_id == generated.id)
        ).first()
        if existing and existing.id != planned_page_id:
            raise SitePlanningError("Generated Page is already linked to another Planned Page.")


def _website(session: Session, website_id: int) -> Website:
    website = session.get(Website, website_id)
    if not website:
        raise SitePlanningError(f"Website not found: {website_id}")
    return website


def _site_plan(session: Session, plan_id: int) -> SitePlan:
    plan = session.get(SitePlan, plan_id)
    if not plan:
        raise SitePlanningError(f"Site Plan not found: {plan_id}")
    return plan


def _planned_page(session: Session, page_id: int) -> PlannedPage:
    page = session.get(PlannedPage, page_id)
    if not page:
        raise SitePlanningError(f"Planned Page not found: {page_id}")
    return page


def _confidence_level(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _missing_label(key: str) -> str:
    return {
        "company_information": "Add an approved company description.",
        "company_description": "Add an approved company description.",
        "contact_information": "Add approved customer contact information.",
        "preferred_contact_methods": "Identify an approved customer contact method.",
        "website_identity": "Complete and approve Website Identity information.",
        "primary_services": "Add at least one active service with an approved description.",
        "service_information": "Add approved service details.",
        "service_area": "Confirm the legitimate service area.",
        "primary_action": "Add an approved contact method for the primary call to action.",
        "trust_information": "Add approved license, operator, or company trust information.",
        "approved_knowledge": "Add approved supporting knowledge.",
        "approved_questions_and_answers": "Add at least one approved question and answer.",
    }.get(key, f"Complete approved information for {key.replace('_', ' ')}.")
