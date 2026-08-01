from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from app.models import (
    City,
    County,
    PlannedPage,
    Service,
    SitePlan,
    Website,
    WebsiteCityCoverageDecision,
    WebsiteCountyCoverageDecision,
    WebsiteServiceCityCoverageDecision,
    WebsiteServiceCountyCoverageDecision,
    WebsiteServiceCoverageDecision,
)


class CountyPageContractError(ValueError):
    pass


@dataclass(frozen=True)
class CountyPageContext:
    county: County
    service: Service
    included_cities: tuple[City, ...]
    related_service_page_ids: tuple[int, ...]
    related_city_service_page_ids: tuple[int, ...]
    competing_county_page_ids: tuple[int, ...]
    approved_source_identities: tuple[dict[str, Any], ...]

    @property
    def has_approved_value(self) -> bool:
        return bool(self.included_cities)

    @property
    def search_intent(self) -> str:
        cities = ", ".join(item.city_name for item in self.included_cities)
        return (
            f"{self.service.service_name} for customers in "
            f"{self.county.county_name}, {self.county.state}; "
            f"locally supported cities: {cities}"
        )

    def approved_values(self) -> list[dict[str, Any]]:
        if not self.has_approved_value:
            return []
        city_names = ", ".join(item.city_name for item in self.included_cities)
        return [
            {
                "kind": "approved_service_county_relationship",
                "value": (
                    f"{self.service.service_name} is approved for a dedicated page "
                    f"in {self.county.county_name}."
                ),
                "approved": True,
                "source": "website_service_county_coverage_decisions",
            },
            {
                "kind": "approved_service_city_value",
                "value": (
                    f"The approved {self.service.service_name} cities in "
                    f"{self.county.county_name} are {city_names}."
                ),
                "approved": True,
                "source": "website_service_city_coverage_decisions",
            },
        ]

    def unique_elements(self) -> list[dict[str, Any]]:
        if not self.has_approved_value:
            return []
        return [
            {
                "kind": "proposed_unique_section",
                "value": (
                    f"{self.service.service_name} guidance for "
                    f"{self.county.county_name}."
                ),
                "source": "approved_service_county_relationship",
            },
            {
                "kind": "proposed_unique_section",
                "value": (
                    "City-specific paths: "
                    + ", ".join(item.city_name for item in self.included_cities)
                ),
                "source": "approved_service_city_relationships",
            },
            {
                "kind": "proposed_unique_section",
                "value": (
                    f"{len(self.related_city_service_page_ids)} related "
                    f"{self.service.service_name} City-Service pages."
                ),
                "source": "approved_site_plan_relationships",
            },
        ]


def build_county_page_context(
    session: Session,
    *,
    website_id: int,
    site_plan_id: int,
    county_id: int,
    service_id: int | None = None,
) -> CountyPageContext:
    website = session.get(Website, website_id)
    plan = session.get(SitePlan, site_plan_id)
    county = session.get(County, county_id)
    service = session.get(Service, service_id) if service_id else None
    if website is None or plan is None or county is None:
        raise CountyPageContractError(
            "Service-County page Website, Site Plan, or County is missing."
        )
    if plan.website_id != website.id:
        raise CountyPageContractError(
            "Service-County page Site Plan is outside the Website."
        )
    if service is None:
        raise CountyPageContractError(
            "County pages require exactly one approved Service relationship."
        )
    if service.business_id != website.business_id:
        raise CountyPageContractError(
            "Service-County page Service is outside the Website business."
        )

    service_parent = session.exec(
        select(WebsiteServiceCoverageDecision).where(
            WebsiteServiceCoverageDecision.website_id == website.id,
            WebsiteServiceCoverageDecision.service_id == service.id,
        )
    ).first()
    county_parent = session.exec(
        select(WebsiteCountyCoverageDecision).where(
            WebsiteCountyCoverageDecision.website_id == website.id,
            WebsiteCountyCoverageDecision.county_id == county.id,
        )
    ).first()
    service_county = session.exec(
        select(WebsiteServiceCountyCoverageDecision).where(
            WebsiteServiceCountyCoverageDecision.website_id == website.id,
            WebsiteServiceCountyCoverageDecision.service_id == service.id,
            WebsiteServiceCountyCoverageDecision.county_id == county.id,
        )
    ).first()
    if not service_parent or service_parent.status != "included":
        raise CountyPageContractError("Website Service is not included.")
    if (
        not county_parent
        or county_parent.status != "included"
        or not county_parent.page_appropriate
    ):
        raise CountyPageContractError(
            "Website County is not included and page-appropriate."
        )
    if not service_county or service_county.status != "included":
        raise CountyPageContractError(
            "An explicit included Service × County authorization is required."
        )

    approved_city_ids = {
        item.city_id
        for item in session.exec(
            select(WebsiteCityCoverageDecision).where(
                WebsiteCityCoverageDecision.website_id == website.id,
                WebsiteCityCoverageDecision.status == "included",
            )
        ).all()
    }
    service_city_decisions = list(
        session.exec(
            select(WebsiteServiceCityCoverageDecision).where(
                WebsiteServiceCityCoverageDecision.website_id == website.id,
                WebsiteServiceCityCoverageDecision.service_id == service.id,
                WebsiteServiceCityCoverageDecision.status == "included",
            )
        ).all()
    )
    service_city_decisions = [
        item for item in service_city_decisions if item.city_id in approved_city_ids
    ]
    cities = [
        city
        for decision in service_city_decisions
        if (city := session.get(City, decision.city_id)) is not None
        and city.county_id == county.id
        and city.status == "active"
    ]
    cities.sort(key=lambda item: (item.city_name.lower(), item.id or 0))
    city_ids = {item.id for item in cities}

    planned_pages = list(
        session.exec(
            select(PlannedPage).where(
                PlannedPage.website_id == website.id,
                PlannedPage.site_plan_id == plan.id,
            )
        ).all()
    )
    related_service_ids = tuple(
        sorted(
            item.id
            for item in planned_pages
            if item.id is not None
            and item.page_type == "service"
            and item.service_id == service.id
        )
    )
    related_city_service_ids = tuple(
        sorted(
            item.id
            for item in planned_pages
            if item.id is not None
            and item.page_type == "city_service"
            and item.service_id == service.id
            and item.city_id in city_ids
        )
    )
    competing_county_ids = tuple(
        sorted(
            item.id
            for item in planned_pages
            if item.id is not None
            and item.page_type == "county"
            and item.service_id == service.id
            and item.county_id != county.id
        )
    )

    sources: list[dict[str, Any]] = [
        {"type": "approved_service", "id": service.id, "business_id": service.business_id},
        {"type": "approved_county", "id": county.id, "state": county.state},
        _decision_identity("service_coverage_decision", service_parent),
        _decision_identity("county_coverage_decision", county_parent),
        _decision_identity("service_county_coverage_decision", service_county),
    ]
    sources.extend(
        _decision_identity("service_city_coverage_decision", item)
        for item in service_city_decisions
        if item.city_id in city_ids
    )
    sources.extend(
        {"type": "approved_city", "id": item.id, "county_id": item.county_id}
        for item in cities
    )
    return CountyPageContext(
        county=county,
        service=service,
        included_cities=tuple(cities),
        related_service_page_ids=related_service_ids,
        related_city_service_page_ids=related_city_service_ids,
        competing_county_page_ids=competing_county_ids,
        approved_source_identities=tuple(
            sorted(
                sources,
                key=lambda item: (str(item["type"]), int(item.get("id") or 0)),
            )
        ),
    )


def _decision_identity(kind: str, decision: Any) -> dict[str, Any]:
    return {
        "type": kind,
        "id": decision.id,
        "status": decision.status,
        "decision_version": decision.decision_version,
        "updated_at": decision.updated_at.isoformat(),
    }
