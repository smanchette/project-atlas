from __future__ import annotations

from urllib.parse import urlparse

from sqlmodel import Session, select

from app.models import Brand, Business, City, County, GeneratedPage, Service, Website, WebsiteIdentity
from app.schemas.website_context import (
    WebsiteContextBrand,
    WebsiteContextBusiness,
    WebsiteContextGeography,
    WebsiteContextIdentity,
    WebsiteContextRead,
    WebsiteContextService,
    WebsiteContextSite,
)


class WebsiteContextError(ValueError):
    pass


def resolve_website_for_business(
    session: Session,
    business: Business,
    *,
    website_id: int | None = None,
) -> Website | None:
    if website_id is not None:
        website = session.get(Website, website_id)
        if not website or website.business_id != business.id:
            raise WebsiteContextError("Website does not belong to the selected business.")
        return website
    websites = list(session.exec(
        select(Website)
        .where(Website.business_id == business.id, Website.status == "active")
        .order_by(Website.id)
    ).all())
    if len(websites) > 1:
        raise WebsiteContextError(
            "Explicit Website selection is required because this business has multiple active Websites."
        )
    return websites[0] if websites else None


def build_website_context(
    session: Session,
    *,
    website_id: int | None = None,
    page_id: int | None = None,
    business_id: int | None = None,
) -> WebsiteContextRead:
    page = session.get(GeneratedPage, page_id) if page_id is not None else None
    if page_id is not None and not page:
        raise WebsiteContextError(f"Generated page not found: {page_id}")
    resolved_business_id = page.business_id if page else business_id
    if resolved_business_id is None:
        website = session.get(Website, website_id) if website_id is not None else None
        resolved_business_id = website.business_id if website else None
    business = session.get(Business, resolved_business_id) if resolved_business_id is not None else None
    if not business or business.id is None:
        raise WebsiteContextError("Website context requires an existing business.")

    selected_website_id = page.website_id if page and page.website_id is not None else website_id
    website = resolve_website_for_business(session, business, website_id=selected_website_id)
    brand = session.get(Brand, website.brand_id) if website and website.brand_id else None
    if brand and brand.business_id != business.id:
        raise WebsiteContextError("Website brand does not belong to the selected business.")
    identity = session.exec(
        select(WebsiteIdentity).where(WebsiteIdentity.website_id == website.id)
    ).first() if website and website.id else None
    services = list(
        session.exec(
            select(Service)
            .where(Service.business_id == business.id, Service.status == "active")
            .order_by(Service.service_name)
        ).all()
    )
    city = session.get(City, page.city_id) if page and page.city_id else None
    county = session.get(County, page.county_id) if page and page.county_id else None

    legacy_url = _public_url(business.website)
    public_name = brand.brand_name if brand else business.brand_name or business.company_name
    display_name = identity.display_name if identity else public_name
    configuration = dict(website.configuration) if website else {}
    state_code = city.state if city else business.state
    state_name = str(configuration.get("state_name") or state_code)

    return WebsiteContextRead(
        business=WebsiteContextBusiness(
            id=business.id,
            company_name=business.company_name,
            business_type=business.business_type,
            phone=business.phone,
            email=business.email,
            main_city=business.main_city,
            state=business.state,
            license_number=business.license_number,
            certified_operator=business.certified_operator,
            description=business.description,
        ),
        brand=WebsiteContextBrand(
            id=brand.id if brand else None,
            public_name=public_name,
            tagline=brand.tagline if brand else None,
            description=brand.description if brand else None,
            identity_settings=dict(brand.identity_settings) if brand else {},
        ),
        website=WebsiteContextSite(
            id=website.id if website else None,
            website_name=website.website_name if website else display_name,
            domain=website.domain if website else urlparse(legacy_url).netloc,
            public_url=website.public_url if website else legacy_url,
            locale=website.locale if website else "en-US",
            primary_language=website.primary_language if website else "en",
            configuration=configuration,
            status=website.status if website else "legacy",
            legacy_fallback=website is None,
        ),
        identity=WebsiteContextIdentity(
            id=identity.id if identity else None,
            display_name=display_name,
            favicon_url=identity.favicon_url if identity else None,
            browser_icon_url=identity.browser_icon_url if identity else None,
            apple_touch_icon_url=identity.apple_touch_icon_url if identity else None,
            social_identity_image_url=identity.social_identity_image_url if identity else None,
            status=identity.status if identity else "legacy",
        ),
        services=[
            WebsiteContextService(
                id=service.id or 0,
                service_name=service.service_name,
                service_slug=service.service_slug,
                service_category=service.service_category,
                short_description=service.short_description,
                long_description=service.long_description,
                status=service.status,
            )
            for service in services
        ],
        geography=WebsiteContextGeography(
            city_id=city.id if city else None,
            city_name=city.city_name if city else None,
            county_id=county.id if county else None,
            county_name=county.county_name if county else None,
            state_code=state_code,
            state_name=state_name,
        ) if page else None,
    )


def website_config_value(context: WebsiteContextRead, key: str, default: str = "") -> str:
    value = context.website.configuration.get(key, default)
    return str(value) if value is not None else default


def _public_url(value: str | None) -> str:
    url = (value or "").strip().rstrip("/")
    if url and not urlparse(url).scheme:
        url = f"https://{url}"
    return url
