from typing import Any

from sqlmodel import Field, SQLModel


class WebsiteContextBusiness(SQLModel):
    id: int
    company_name: str
    business_type: str
    phone: str | None = None
    email: str | None = None
    main_city: str | None = None
    state: str
    license_number: str | None = None
    certified_operator: str | None = None
    description: str | None = None


class WebsiteContextBrand(SQLModel):
    id: int | None = None
    public_name: str
    tagline: str | None = None
    description: str | None = None
    identity_settings: dict[str, Any] = Field(default_factory=dict)


class WebsiteContextSite(SQLModel):
    id: int | None = None
    website_name: str
    domain: str
    public_url: str
    locale: str
    primary_language: str
    configuration: dict[str, Any] = Field(default_factory=dict)
    status: str
    legacy_fallback: bool = False


class WebsiteContextIdentity(SQLModel):
    id: int | None = None
    display_name: str
    favicon_url: str | None = None
    browser_icon_url: str | None = None
    apple_touch_icon_url: str | None = None
    social_identity_image_url: str | None = None
    status: str


class WebsiteContextService(SQLModel):
    id: int
    service_name: str
    service_slug: str
    service_category: str | None = None
    short_description: str | None = None
    long_description: str | None = None
    status: str


class WebsiteContextGeography(SQLModel):
    city_id: int | None = None
    city_name: str | None = None
    county_id: int | None = None
    county_name: str | None = None
    state_code: str | None = None
    state_name: str | None = None


class WebsiteContextRead(SQLModel):
    business: WebsiteContextBusiness
    brand: WebsiteContextBrand
    website: WebsiteContextSite
    identity: WebsiteContextIdentity
    services: list[WebsiteContextService]
    geography: WebsiteContextGeography | None = None

