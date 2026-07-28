from sqlmodel import Session, select

from app.db.city_data import slugify_city_name
from app.models import Business, City, GeneratedPage, Service
from app.schemas.website_context import WebsiteContextRead
from app.services.website_context import build_website_context
from app.services.site_planning import backfill_existing_generated_pages

PAGE_TYPE_CITY_SERVICE = "city_service"


def build_city_service_page_payload(
    business: Business,
    service: Service,
    city: City,
    context: WebsiteContextRead,
) -> dict[str, str | int | None]:
    city_display = city.city_name
    config = context.website.configuration
    state_slug = str(config.get("state_slug") or city.state).lower()
    state_name = str(config.get("state_name") or city.state)
    short_brand_name = str(config.get("short_brand_name") or context.brand.public_name)
    page_slug = f"{service.service_slug}-{city.city_slug}-{state_slug}"
    description_template = str(
        config.get("page_meta_description_template")
        or "{company_name} provides {service_lower} in {city}, {state_name}."
    )
    return {
        "business_id": business.id,
        "website_id": context.website.id,
        "service_id": service.id,
        "city_id": city.id,
        "county_id": city.county_id,
        "page_type": PAGE_TYPE_CITY_SERVICE,
        "page_title": f"{service.service_name} in {city_display}, {city.state}",
        "page_slug": page_slug,
        "meta_title": f"{service.service_name} in {city_display}, {city.state} | {short_brand_name}",
        "meta_description": description_template.format(
            company_name=business.company_name,
            service_name=service.service_name,
            service_lower=service.service_name.lower(),
            city=city_display,
            state_name=state_name,
        ),
        "h1": f"{service.service_name} in {city_display}, {state_name}",
        "status": "draft",
    }


def create_city_service_page_queue(
    session: Session,
    *,
    business_company_name: str,
    service_slug: str,
    website_id: int | None = None,
) -> int:
    business = session.exec(select(Business).where(Business.company_name == business_company_name)).first()
    if not business or business.id is None:
        raise ValueError(f"Business not found: {business_company_name}")

    service = session.exec(
        select(Service).where(Service.business_id == business.id, Service.service_slug == service_slug)
    ).first()
    if not service or service.id is None:
        raise ValueError(f"Service not found for business {business_company_name}: {service_slug}")

    context = build_website_context(
        session,
        business_id=business.id,
        website_id=website_id,
    )
    state_codes = context.website.configuration.get("market_state_codes")
    city_statement = select(City)
    if isinstance(state_codes, list) and state_codes:
        city_statement = city_statement.where(
            City.state.in_([str(value).upper() for value in state_codes])
        )
    cities = session.exec(city_statement.order_by(City.city_name)).all()
    created_count = 0

    for city in cities:
        if city.id is None:
            continue
        if city.city_slug != slugify_city_name(city.city_name):
            city.city_slug = slugify_city_name(city.city_name)

        payload = build_city_service_page_payload(business, service, city, context)
        page = session.exec(
            select(GeneratedPage).where(
                GeneratedPage.business_id == business.id,
                GeneratedPage.website_id == context.website.id,
                GeneratedPage.service_id == service.id,
                GeneratedPage.city_id == city.id,
                GeneratedPage.page_type == PAGE_TYPE_CITY_SERVICE,
            )
        ).first()

        if page:
            page.business_id = business.id
            if page.website_id is None:
                page.website_id = context.website.id
            page.service_id = service.id
            page.city_id = city.id
            page.county_id = city.county_id
            page.page_type = PAGE_TYPE_CITY_SERVICE
            for key in ("page_title", "page_slug", "meta_title", "meta_description", "h1"):
                if not getattr(page, key):
                    setattr(page, key, payload[key])
            session.add(page)
            continue

        page = GeneratedPage(**payload)
        session.add(page)
        created_count += 1

    session.commit()
    backfill_existing_generated_pages(session)
    return created_count
