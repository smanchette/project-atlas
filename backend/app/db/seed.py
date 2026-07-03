from sqlmodel import Session, select

from app.db.city_data import COUNTY_CITY_MAP, priority_for_city, slugify_city_name
from app.db.knowledge_block_data import KNOWLEDGE_BLOCKS
from app.db.session import create_db_and_tables, engine
from app.models import (
    Business,
    City,
    County,
    GeneratedPage,
    ImageMetadata,
    KnowledgeBlock,
    PageImageAssignment,
    Service,
    Setting,
)
from app.services.page_queue import create_city_service_page_queue


FLO_ZONE_COMPANY_NAME = "Flo-Zone Pest And Termite Solutions Inc"


def seed_database(session: Session) -> None:
    business = upsert_business(session)
    service = upsert_service(session, business)
    cities = upsert_counties_and_cities(session)
    upsert_knowledge_blocks(session, business, service)
    image, seed_hero_assignment = upsert_image_metadata(session, business, service, cities["Orlando"])
    upsert_settings(session)
    create_city_service_page_queue(
        session,
        business_company_name=FLO_ZONE_COMPANY_NAME,
        service_slug="drywood-termite-tenting",
    )
    if seed_hero_assignment:
        upsert_initial_hero_assignment(session, business, service, cities["Orlando"], image)


def upsert_business(session: Session) -> Business:
    business = session.exec(select(Business).where(Business.company_name == FLO_ZONE_COMPANY_NAME)).first()
    payload = {
        "company_name": FLO_ZONE_COMPANY_NAME,
        "brand_name": "Flo-Zone Tenting",
        "business_type": "Drywood termite treatments",
        "phone": "(844) 600-8368",
        "email": "Office@Flo-ZoneTenting.com",
        "website": "https://www.Flo-ZoneTenting.com",
        "main_city": "Orlando",
        "state": "FL",
        "license_number": "JB360566",
        "certified_operator": "Jordan Ward",
        "description": (
            "Drywood termite tenting provider serving homeowners, realtors, property managers, "
            "commercial clients, and investors across Central Florida target counties."
        ),
    }
    if business:
        for key, value in payload.items():
            setattr(business, key, value)
    else:
        business = Business(**payload)
    session.add(business)
    session.commit()
    session.refresh(business)
    return business


def upsert_service(session: Session, business: Business) -> Service:
    service = session.exec(
        select(Service).where(Service.business_id == business.id, Service.service_slug == "drywood-termite-tenting")
    ).first()
    payload = {
        "business_id": business.id,
        "service_name": "Drywood Termite Tenting",
        "service_slug": "drywood-termite-tenting",
        "service_category": "Termite Treatment",
        "short_description": "Structural fumigation service for drywood termite infestations.",
        "long_description": (
            "Drywood termite tenting for homes and commercial properties, coordinated for local "
            "Florida markets with clear preparation and re-entry requirements."
        ),
        "status": "active",
    }
    if service:
        for key, value in payload.items():
            setattr(service, key, value)
    else:
        service = Service(**payload)
    session.add(service)
    session.commit()
    session.refresh(service)
    return service


def upsert_counties_and_cities(session: Session) -> dict[str, City]:
    cities: dict[str, City] = {}

    for county_name, city_names in COUNTY_CITY_MAP.items():
        county = session.exec(select(County).where(County.county_name == county_name, County.state == "FL")).first()
        if county:
            county.status = "active"
        else:
            county = County(state="FL", county_name=county_name, status="active")
        session.add(county)
        session.commit()
        session.refresh(county)

        for city_name in city_names:
            city_slug = slugify_city_name(city_name)
            city = session.exec(select(City).where(City.city_slug == city_slug, City.state == "FL")).first()
            payload = {
                "county_id": county.id,
                "city_name": city_name,
                "state": "FL",
                "city_slug": city_slug,
                "priority": priority_for_city(city_name),
                "is_primary_market": city_name == "Orlando",
                "status": "active",
            }
            if city:
                for key, value in payload.items():
                    setattr(city, key, value)
            else:
                city = City(**payload)
            session.add(city)
            session.commit()
            session.refresh(city)
            cities[city_name] = city

    return cities


def upsert_image_metadata(
    session: Session,
    business: Business,
    service: Service,
    orlando: City,
) -> tuple[ImageMetadata, bool]:
    image = session.exec(
        select(ImageMetadata).where(
            ImageMetadata.business_id == business.id,
            ImageMetadata.file_name == "orlando-drywood-termite-tenting.jpg",
        )
    ).first()
    seed_hero_assignment = image is None or not image.asset_url
    payload = {
        "business_id": business.id,
        "service_id": service.id,
        "city_id": orlando.id,
        "county_id": orlando.county_id,
        "file_name": "orlando-drywood-termite-tenting.jpg",
        "image_title": "Drywood Termite Tenting at an Orlando Florida Home",
        "alt_text": "Drywood termite tenting service in Orlando Florida",
        "reviewed_alt_text": (
            "Two-story Orlando Florida home professionally covered for drywood termite tenting"
        ),
        "caption": "Flo-Zone drywood termite tenting in Orlando, FL.",
        "asset_url": "/media/orlando-drywood-termite-tenting-hero.png",
        "image_role": "hero",
        "review_status": "reviewed",
        "geo_city": "Orlando",
        "geo_state": "FL",
        "image_prompt": "Exterior of a Florida home prepared for drywood termite tenting in Orlando.",
        "exif_status": "pending",
    }
    if image:
        for key, value in payload.items():
            setattr(image, key, value)
    else:
        image = ImageMetadata(**payload)
    session.add(image)
    session.commit()
    session.refresh(image)
    return image, seed_hero_assignment


def upsert_initial_hero_assignment(
    session: Session,
    business: Business,
    service: Service,
    orlando: City,
    image: ImageMetadata,
) -> None:
    page = session.exec(
        select(GeneratedPage).where(
            GeneratedPage.business_id == business.id,
            GeneratedPage.service_id == service.id,
            GeneratedPage.city_id == orlando.id,
            GeneratedPage.page_type == "city_service",
        )
    ).first()
    if not page or page.id is None or image.id is None:
        return

    assignment = session.exec(
        select(PageImageAssignment).where(
            PageImageAssignment.generated_page_id == page.id,
            PageImageAssignment.image_role == "hero",
        )
    ).first()
    if assignment:
        return
    session.add(
        PageImageAssignment(
            generated_page_id=page.id,
            image_metadata_id=image.id,
            image_role="hero",
            sort_order=0,
            status="active",
        )
    )
    session.commit()


def upsert_knowledge_blocks(session: Session, business: Business, service: Service) -> None:
    for block_payload in KNOWLEDGE_BLOCKS:
        block = session.exec(select(KnowledgeBlock).where(KnowledgeBlock.slug == block_payload["slug"])).first()
        payload = {
            **block_payload,
            "business_id": business.id,
            "service_id": service.id,
        }
        if block:
            for key, value in payload.items():
                setattr(block, key, value)
        else:
            block = KnowledgeBlock(**payload)
        session.add(block)
    session.commit()


def upsert_settings(session: Session) -> None:
    settings = [
        ("default_state", "FL", "Default state for local SEO records."),
        ("content_generation_enabled", "true", "Controlled draft generation is enabled in v0.5."),
        (
            "target_customer_types",
            "homeowners,realtors,property managers,investors,commercial clients",
            "Default audiences for local service draft generation.",
        ),
        (
            "content_safety_rules",
            (
                "Use careful qualifiers such as often, may, can help, and commonly used. "
                "Customers must follow preparation and re-entry instructions, with re-entry only after clearance."
            ),
            "Public wording rules applied to generated drafts.",
        ),
    ]
    for setting_key, setting_value, description in settings:
        setting = session.exec(select(Setting).where(Setting.setting_key == setting_key)).first()
        if setting:
            setting.setting_value = setting_value
            setting.description = description
        else:
            setting = Setting(setting_key=setting_key, setting_value=setting_value, description=description)
        session.add(setting)
    session.commit()


def main() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        seed_database(session)


if __name__ == "__main__":
    main()
