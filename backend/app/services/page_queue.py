from sqlmodel import Session, select

from app.db.city_data import slugify_city_name
from app.models import Business, City, GeneratedPage, Service

PAGE_TYPE_CITY_SERVICE = "city_service"


def build_city_service_page_payload(business: Business, service: Service, city: City) -> dict[str, str | int | None]:
    city_display = city.city_name
    page_slug = f"{service.service_slug}-{city.city_slug}-fl"
    return {
        "business_id": business.id,
        "service_id": service.id,
        "city_id": city.id,
        "county_id": city.county_id,
        "page_type": PAGE_TYPE_CITY_SERVICE,
        "page_title": f"Drywood Termite Tenting in {city_display}, FL",
        "page_slug": page_slug,
        "meta_title": f"Drywood Termite Tenting in {city_display}, FL | Flo-Zone",
        "meta_description": (
            "Flo-Zone Pest And Termite Solutions Inc helps homeowners, realtors, property managers, "
            f"investors, and commercial clients with drywood termite tenting in {city_display}, Florida."
        ),
        "h1": f"Drywood Termite Tenting in {city_display}, Florida",
        "status": "draft",
    }


def create_city_service_page_queue(
    session: Session,
    *,
    business_company_name: str,
    service_slug: str,
) -> int:
    business = session.exec(select(Business).where(Business.company_name == business_company_name)).first()
    if not business or business.id is None:
        raise ValueError(f"Business not found: {business_company_name}")

    service = session.exec(
        select(Service).where(Service.business_id == business.id, Service.service_slug == service_slug)
    ).first()
    if not service or service.id is None:
        raise ValueError(f"Service not found for business {business_company_name}: {service_slug}")

    cities = session.exec(select(City).order_by(City.city_name)).all()
    created_count = 0

    for city in cities:
        if city.id is None:
            continue
        if city.city_slug != slugify_city_name(city.city_name):
            city.city_slug = slugify_city_name(city.city_name)

        payload = build_city_service_page_payload(business, service, city)
        page = session.exec(
            select(GeneratedPage).where(
                GeneratedPage.business_id == business.id,
                GeneratedPage.service_id == service.id,
                GeneratedPage.city_id == city.id,
                GeneratedPage.page_type == PAGE_TYPE_CITY_SERVICE,
            )
        ).first()

        if page:
            page.business_id = business.id
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
    return created_count
