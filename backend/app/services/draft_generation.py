from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlmodel import Session, select

from app.core.config import get_settings
from app.models import Business, City, County, GeneratedPage, KnowledgeBlock, Service, Setting
from app.schemas.generation import BatchCandidate, BatchPreviewResponse, DraftContent, FAQItem
from app.schemas.website_context import WebsiteContextRead
from app.services.website_context import build_website_context, website_config_value

FORBIDDEN_PHRASES = (
    "100% guaranteed",
    "always eliminates",
    "permanent protection",
    "safe for everyone",
    "no risk",
    "harmless",
    "pesticide-free",
)

DEFAULT_CUSTOMERS = (
    "homeowners",
    "realtors",
    "property managers",
    "investors",
    "commercial clients",
)

DEFAULT_SAFE_WORDING = (
    "Use careful qualifiers such as often, may, can help, and commonly used. "
    "Require customers to follow all preparation and re-entry instructions and state that "
    "re-entry is allowed only after clearance."
)


class DraftGenerationError(ValueError):
    pass


class UnsafeContentError(DraftGenerationError):
    pass


class DraftProvider(Protocol):
    name: str

    def generate(self, context: "GenerationContext", prompt: str) -> DraftContent:
        ...


@dataclass
class GenerationContext:
    page: GeneratedPage
    business: Business
    service: Service
    city: City
    county: County
    knowledge_blocks: list[KnowledgeBlock]
    settings: dict[str, str]
    customer_types: list[str]
    website_context: WebsiteContextRead


def load_generation_context(session: Session, page_id: int) -> GenerationContext:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise DraftGenerationError(f"Generated page not found: {page_id}")
    if page.page_type != "city_service":
        raise DraftGenerationError("Draft generation currently supports city-service pages only.")
    if page.city_id is None or page.county_id is None:
        raise DraftGenerationError("City-service page is missing its city or county relationship.")

    business = session.get(Business, page.business_id)
    service = session.get(Service, page.service_id)
    city = session.get(City, page.city_id)
    county = session.get(County, page.county_id)
    if not business or not service or not city or not county:
        raise DraftGenerationError("Generated page has an unresolved business, service, city, or county.")

    knowledge_blocks = list(
        session.exec(
            select(KnowledgeBlock)
            .where(
                KnowledgeBlock.business_id == business.id,
                KnowledgeBlock.service_id == service.id,
                KnowledgeBlock.status == "active",
            )
            .order_by(KnowledgeBlock.sort_order)
        ).all()
    )
    if not knowledge_blocks:
        raise DraftGenerationError("No active knowledge blocks are available for this service.")

    setting_records = session.exec(select(Setting)).all()
    settings = {
        setting.setting_key: setting.setting_value or ""
        for setting in setting_records
    }
    website_context = build_website_context(session, page_id=page_id)
    website_customers = website_context.website.configuration.get("target_customer_types")
    if isinstance(website_customers, list):
        configured_customers = [str(value).strip() for value in website_customers if str(value).strip()]
    else:
        configured_customers = [
            value.strip()
            for value in str(website_customers or settings.get("target_customer_types", "")).split(",")
            if value.strip()
        ]

    return GenerationContext(
        page=page,
        business=business,
        service=service,
        city=city,
        county=county,
        knowledge_blocks=knowledge_blocks,
        settings=settings,
        customer_types=configured_customers or list(DEFAULT_CUSTOMERS),
        website_context=website_context,
    )


def assemble_generation_prompt(context: GenerationContext) -> str:
    business = context.business
    service = context.service
    safety_rules = context.settings.get("content_safety_rules") or DEFAULT_SAFE_WORDING
    county_label = _county_label(context.county.county_name)
    knowledge_text = "\n\n".join(
        (
            f"[{block.category}] {block.title}\n"
            f"Question: {block.question}\n"
            f"Answer: {block.long_answer}\n"
            f"Confidence: {block.confidence_level}\n"
            f"Source: {block.source_notes or 'Business review required'}"
        )
        for block in context.knowledge_blocks
    )

    return (
        "Create a structured local service page draft for human review. Do not publish it.\n\n"
        f"Business: {business.company_name}\n"
        f"Phone: {business.phone or 'Not provided'}\n"
        f"Website: {context.website_context.website.public_url or 'Not provided'}\n"
        f"Email: {business.email or 'Not provided'}\n"
        f"License: {business.license_number or 'Not provided'}\n"
        f"Certified operator: {business.certified_operator or 'Not provided'}\n"
        f"Service: {service.service_name}\n"
        f"City: {context.city.city_name}\n"
        f"County: {county_label}\n"
        f"State: {context.city.state}\n"
        f"Target customers: {', '.join(context.customer_types)}\n\n"
        f"Safety rules: {safety_rules}\n"
        f"Never use these claims: {', '.join(FORBIDDEN_PHRASES)}.\n"
        "Use only facts supported by the business data and knowledge blocks.\n\n"
        f"Knowledge blocks:\n{knowledge_text}"
    )


class DeterministicMockProvider:
    name = "mock"

    def generate(self, context: GenerationContext, prompt: str) -> DraftContent:
        del prompt
        business = context.business
        city = context.city.city_name
        county = _county_label(context.county.county_name)
        service = context.service.service_name
        website = context.website_context
        short_brand_name = website_config_value(website, "short_brand_name", website.brand.public_name)
        state_name = website_config_value(website, "state_name", context.city.state)
        license_label = website_config_value(website, "license_label", "License")
        customer_text = ", ".join(context.customer_types[:-1]) + f", and {context.customer_types[-1]}"
        values = {
            "company_name": business.company_name,
            "short_brand_name": short_brand_name,
            "service_name": service,
            "service_lower": service.lower(),
            "city": city,
            "county": county,
            "state_name": state_name,
            "phone_or_brand": business.phone or short_brand_name,
        }
        description_template = website_config_value(
            website,
            "draft_meta_description_template",
            "{company_name} provides {service_lower} in {city}, {state_name}.",
        )
        intro_suffix = website_config_value(
            website,
            "draft_intro_suffix",
            "Service recommendations and scope depend on the property and the approved service plan.",
        )
        process_template = website_config_value(
            website,
            "draft_process_template",
            "A {service_lower} project begins with assessment, planning, and clear customer instructions. "
            "Timing and access requirements depend on the approved service plan.",
        )
        realtor_template = website_config_value(
            website,
            "draft_realtor_template",
            "Realtors and property managers in {city} can help projects stay on schedule by coordinating "
            "occupants, access, and service requirements early.",
        )

        return DraftContent(
            title=f"{service} in {city}, {context.city.state}",
            meta_title=f"{service} in {city}, {context.city.state} | {short_brand_name}",
            meta_description=description_template.format(**values),
            h1=f"{service} in {city}, {state_name}",
            intro=(
                f"{business.company_name} provides {service.lower()} for {customer_text} in {city} and "
                f"throughout {county}. {intro_suffix}"
            ),
            why_it_matters=_knowledge_answer(
                context,
                website_config_value(website, "why_knowledge_slug"),
                (
                    f"{service} can address service needs identified during assessment. "
                    "The appropriate scope depends on the property and the approved service plan."
                ),
            ),
            signs_section=_knowledge_answer(
                context,
                website_config_value(website, "signs_knowledge_slug"),
                (
                    f"Possible signs and service needs vary by property. A qualified assessment can help "
                    f"determine whether {service.lower()} is an appropriate next step."
                ),
            ),
            process_section=process_template.format(**values),
            prep_section=_knowledge_answer(
                context,
                website_config_value(website, "prep_knowledge_slug"),
                (
                    "Occupants, pets, plants, and specified consumable items must be removed or prepared as "
                    f"directed. Customers should follow every preparation and re-entry instruction from {short_brand_name}."
                ),
            ),
            realtor_property_manager_section=realtor_template.format(**values),
            faq_items=_faq_items(context),
            call_to_action=(
                f"To discuss {service.lower()} in {city}, contact {business.company_name} at "
                f"{business.phone or 'the office'} or "
                f"{business.email or website.website.public_url or 'through the company website'}. "
                f"{license_label} {business.license_number or 'information available on request'}; "
                f"certified operator {business.certified_operator or 'information available on request'}."
            ),
            internal_notes=(
                f"Deterministic mock draft assembled from {len(context.knowledge_blocks)} active knowledge blocks. "
                "Human review is required before approval. No external AI service was called."
            ),
            status="draft",
        )


def get_draft_provider() -> DraftProvider:
    settings = get_settings()
    if settings.ai_provider == "mock" or not settings.ai_api_key:
        return DeterministicMockProvider()
    raise DraftGenerationError(f"AI provider is not configured: {settings.ai_provider}")


def generate_page_draft(
    session: Session,
    page_id: int,
    *,
    allow_overwrite: bool = False,
    provider: DraftProvider | None = None,
    commit: bool = True,
) -> GeneratedPage:
    context = load_generation_context(session, page_id)
    _ensure_page_can_generate(context.page, allow_overwrite=allow_overwrite)
    prompt = assemble_generation_prompt(context)
    selected_provider = provider or get_draft_provider()
    draft = selected_provider.generate(context, prompt)
    validate_safe_content(draft.model_dump(mode="json"))

    page = context.page
    page.page_title = draft.title
    page.meta_title = draft.meta_title
    page.meta_description = draft.meta_description
    page.h1 = draft.h1
    page.draft_content = draft.model_dump(mode="json")
    page.content_body = render_content_body(draft, context.website_context)
    page.generation_status = "generated"
    page.generated_at = datetime.now(UTC)
    page.qa_status = "not_run"
    page.qa_result = None
    page.qa_checked_at = None
    page.updated_at = datetime.now(UTC)
    page.status = "draft"
    session.add(page)
    if commit:
        session.commit()
        session.refresh(page)
    else:
        session.flush()
    return page


def preview_batch(
    session: Session,
    *,
    county_ids: list[int] | None = None,
    city_ids: list[int] | None = None,
    status: str | None = None,
) -> BatchPreviewResponse:
    pages = _filtered_city_service_pages(
        session,
        county_ids=county_ids or [],
        city_ids=city_ids or [],
        status=status,
    )
    candidates: list[BatchCandidate] = []
    for page in pages:
        city = session.get(City, page.city_id) if page.city_id is not None else None
        county = session.get(County, page.county_id) if page.county_id is not None else None
        eligible = page.status == "draft" and city is not None and county is not None
        reason = None if eligible else _batch_skip_reason(page, city, county)
        candidates.append(
            BatchCandidate(
                page_id=page.id or 0,
                page_title=page.page_title,
                city_name=city.city_name if city else "Unknown",
                county_name=county.county_name if county else "Unknown",
                page_status=page.status,
                generation_status=page.generation_status,
                eligible=eligible,
                reason=reason,
            )
        )

    eligible_count = sum(candidate.eligible for candidate in candidates)
    return BatchPreviewResponse(
        matched_count=len(candidates),
        eligible_count=eligible_count,
        skipped_count=len(candidates) - eligible_count,
        candidates=candidates,
    )


def generate_batch(
    session: Session,
    *,
    county_ids: list[int] | None = None,
    city_ids: list[int] | None = None,
    status: str | None = None,
    provider: DraftProvider | None = None,
) -> list[int]:
    preview = preview_batch(
        session,
        county_ids=county_ids,
        city_ids=city_ids,
        status=status,
    )
    page_ids = [candidate.page_id for candidate in preview.candidates if candidate.eligible]
    try:
        for page_id in page_ids:
            generate_page_draft(
                session,
                page_id,
                provider=provider,
                allow_overwrite=False,
                commit=False,
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return page_ids


def validate_safe_content(value: Any) -> None:
    text = " ".join(_iter_strings(value)).lower()
    found = [phrase for phrase in FORBIDDEN_PHRASES if phrase in text]
    if found:
        raise UnsafeContentError(f"Generated draft contains unsafe wording: {', '.join(found)}")


def render_content_body(
    draft: DraftContent,
    website_context: WebsiteContextRead | None = None,
) -> str:
    def heading(key: str, default: str) -> str:
        return website_config_value(website_context, key, default) if website_context else default

    faq_text = "\n\n".join(
        f"### {item.question}\n{item.answer}"
        for item in draft.faq_items
    )
    return (
        f"{draft.intro}\n\n"
        f"## {heading('content_heading_why', 'Why This Service Matters')}\n{draft.why_it_matters}\n\n"
        f"## {heading('content_heading_signs', 'What to Look For')}\n{draft.signs_section}\n\n"
        f"## {heading('content_heading_process', 'The Service Process')}\n{draft.process_section}\n\n"
        f"## {heading('content_heading_prep', 'Preparing for Service')}\n{draft.prep_section}\n\n"
        f"## {heading('content_heading_professionals', 'For Property Professionals')}\n{draft.realtor_property_manager_section}\n\n"
        f"## Frequently Asked Questions\n{faq_text}\n\n"
        f"## {heading('content_heading_contact', 'Contact the Company')}\n{draft.call_to_action}"
    )


def _ensure_page_can_generate(page: GeneratedPage, *, allow_overwrite: bool) -> None:
    if page.status in {"approved", "published"} and not allow_overwrite:
        raise DraftGenerationError(f"Page status '{page.status}' requires explicit overwrite confirmation.")
    if page.status != "draft" and not allow_overwrite:
        raise DraftGenerationError(f"Page status '{page.status}' is not eligible for draft generation.")


def _knowledge_answer(context: GenerationContext, slug: str, fallback: str) -> str:
    block = next((item for item in context.knowledge_blocks if item.slug == slug), None)
    return block.long_answer if block else fallback


def _county_label(county_name: str) -> str:
    return county_name if county_name.lower().endswith(" county") else f"{county_name} County"


def _faq_items(context: GenerationContext) -> list[FAQItem]:
    configured = context.website_context.website.configuration.get("faq_knowledge_slugs")
    preferred_slugs = (
        tuple(str(value) for value in configured)
        if isinstance(configured, list)
        else tuple(block.slug for block in context.knowledge_blocks)
    )
    by_slug = {block.slug: block for block in context.knowledge_blocks}
    return [
        FAQItem(question=by_slug[slug].question, answer=by_slug[slug].short_answer)
        for slug in preferred_slugs
        if slug in by_slug
    ]


def _iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def _filtered_city_service_pages(
    session: Session,
    *,
    county_ids: list[int],
    city_ids: list[int],
    status: str | None,
) -> list[GeneratedPage]:
    statement = select(GeneratedPage).where(GeneratedPage.page_type == "city_service")
    if county_ids:
        statement = statement.where(GeneratedPage.county_id.in_(county_ids))
    if city_ids:
        statement = statement.where(GeneratedPage.city_id.in_(city_ids))
    if status:
        statement = statement.where(GeneratedPage.status == status)
    return list(session.exec(statement.order_by(GeneratedPage.page_title)).all())


def _batch_skip_reason(page: GeneratedPage, city: City | None, county: County | None) -> str:
    if not city or not county:
        return "Missing city or county relationship"
    if page.status in {"approved", "published"}:
        return f"Protected {page.status} page"
    return f"Status '{page.status}' is not draft"
