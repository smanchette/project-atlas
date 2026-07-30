from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any

from sqlmodel import Session, select

from app.models import (
    City,
    County,
    GeneratedPage,
    PlannedPage,
    Service,
    SitePlan,
    Website,
    WebsiteCityCoverageDecision,
    WebsiteCountyCoverageDecision,
    WebsiteCoveragePlanningRecord,
    WebsiteServiceCityCoverageDecision,
    WebsiteServiceCoverageDecision,
)
from app.schemas.site_coverage import (
    CityCoverageDecisionRead,
    CountyCoverageDecisionRead,
    CountyCoverageDecisionUpdate,
    CoverageDecisionUpdate,
    CoverageInventoryCounts,
    CoverageInventoryItem,
    CoverageInventoryPreview,
    CoveragePlanningRecordRead,
    CoveragePolicyRead,
    CoverageReconciliationResult,
    ServiceCityCoverageDecisionRead,
    ServiceCoverageDecisionRead,
)
from app.schemas.site_plans import PlannedPageCreate
from app.services.site_planning import create_planned_page


COVERAGE_STATUSES = {"included", "excluded", "deferred"}
CORE_PAGE_SPECS = (
    ("home", "Home", "home"),
    ("about", "About", "about"),
    ("contact", "Contact", "contact"),
    ("faq", "Frequently Asked Questions", "faq"),
)


class SiteCoverageError(ValueError):
    pass


def ensure_coverage_foundation(
    session: Session,
    plan: SitePlan,
    *,
    commit: bool = False,
) -> WebsiteCoveragePlanningRecord:
    if plan.id is None:
        session.add(plan)
        session.flush()
    record = session.exec(
        select(WebsiteCoveragePlanningRecord).where(
            WebsiteCoveragePlanningRecord.site_plan_id == plan.id
        )
    ).first()
    if record is None:
        record = WebsiteCoveragePlanningRecord(
            website_id=plan.website_id,
            site_plan_id=plan.id or 0,
        )
        session.add(record)
        session.flush()
    _refresh_candidates(session, plan, record)
    if commit:
        session.commit()
        session.refresh(record)
    return record


def refresh_coverage_candidates(
    session: Session,
    plan_id: int,
) -> CoveragePlanningRecordRead:
    plan = _plan(session, plan_id)
    record = ensure_coverage_foundation(session, plan, commit=True)
    return CoveragePlanningRecordRead.model_validate(record)


def read_coverage_policy(session: Session, plan_id: int) -> CoveragePolicyRead:
    plan = _plan(session, plan_id)
    record = session.exec(
        select(WebsiteCoveragePlanningRecord).where(
            WebsiteCoveragePlanningRecord.site_plan_id == plan.id
        )
    ).first()
    if record is None:
        raise SiteCoverageError(
            "Coverage foundation is missing; run the additive coverage migration."
        )
    return CoveragePolicyRead(
        website_id=plan.website_id,
        site_plan_id=plan.id or plan_id,
        planning_record=CoveragePlanningRecordRead.model_validate(record),
        service_decisions=[
            ServiceCoverageDecisionRead.model_validate(item)
            for item in _service_decisions(session, plan.website_id)
        ],
        county_decisions=[
            CountyCoverageDecisionRead.model_validate(item)
            for item in _county_decisions(session, plan.website_id)
        ],
        city_decisions=[
            CityCoverageDecisionRead.model_validate(item)
            for item in _city_decisions(session, plan.website_id)
        ],
        matrix_decisions=[
            ServiceCityCoverageDecisionRead.model_validate(item)
            for item in _matrix_decisions(session, plan.website_id)
        ],
    )


def decide_service(
    session: Session,
    plan_id: int,
    service_id: int,
    payload: CoverageDecisionUpdate,
) -> ServiceCoverageDecisionRead:
    plan = _plan(session, plan_id)
    website = _website(session, plan.website_id)
    service = session.get(Service, service_id)
    if not service or service.business_id != website.business_id:
        raise SiteCoverageError(
            "Service does not belong to the selected Website business."
        )
    decision = session.exec(
        select(WebsiteServiceCoverageDecision).where(
            WebsiteServiceCoverageDecision.website_id == website.id,
            WebsiteServiceCoverageDecision.service_id == service.id,
        )
    ).first()
    decision = _apply_decision(
        decision,
        WebsiteServiceCoverageDecision,
        payload,
        website_id=website.id,
        service_id=service.id,
    )
    session.add(decision)
    session.commit()
    session.refresh(decision)
    _refresh_plan_candidates(session, plan)
    return ServiceCoverageDecisionRead.model_validate(decision)


def decide_county(
    session: Session,
    plan_id: int,
    county_id: int,
    payload: CountyCoverageDecisionUpdate,
) -> CountyCoverageDecisionRead:
    plan = _plan(session, plan_id)
    county = session.get(County, county_id)
    if not county:
        raise SiteCoverageError("County not found.")
    _require_candidate_county(session, plan, county)
    decision = session.exec(
        select(WebsiteCountyCoverageDecision).where(
            WebsiteCountyCoverageDecision.website_id == plan.website_id,
            WebsiteCountyCoverageDecision.county_id == county.id,
        )
    ).first()
    decision = _apply_decision(
        decision,
        WebsiteCountyCoverageDecision,
        payload,
        website_id=plan.website_id,
        county_id=county.id,
        page_appropriate=payload.page_appropriate,
    )
    session.add(decision)
    session.commit()
    session.refresh(decision)
    _refresh_plan_candidates(session, plan)
    return CountyCoverageDecisionRead.model_validate(decision)


def decide_city(
    session: Session,
    plan_id: int,
    city_id: int,
    payload: CoverageDecisionUpdate,
) -> CityCoverageDecisionRead:
    plan = _plan(session, plan_id)
    city = session.get(City, city_id)
    if not city:
        raise SiteCoverageError("City not found.")
    county = session.get(County, city.county_id)
    if not county:
        raise SiteCoverageError("City has no resolvable County.")
    _require_candidate_county(session, plan, county)
    if payload.status == "included":
        county_decision = _county_decision(
            session,
            plan.website_id,
            county.id or 0,
        )
        if not county_decision or county_decision.status != "included":
            raise SiteCoverageError(
                "Include the City County before including the Website city."
            )
    decision = session.exec(
        select(WebsiteCityCoverageDecision).where(
            WebsiteCityCoverageDecision.website_id == plan.website_id,
            WebsiteCityCoverageDecision.city_id == city.id,
        )
    ).first()
    decision = _apply_decision(
        decision,
        WebsiteCityCoverageDecision,
        payload,
        website_id=plan.website_id,
        city_id=city.id,
    )
    session.add(decision)
    session.commit()
    session.refresh(decision)
    _refresh_plan_candidates(session, plan)
    return CityCoverageDecisionRead.model_validate(decision)


def decide_service_city(
    session: Session,
    plan_id: int,
    service_id: int,
    city_id: int,
    payload: CoverageDecisionUpdate,
) -> ServiceCityCoverageDecisionRead:
    plan = _plan(session, plan_id)
    website = _website(session, plan.website_id)
    service = session.get(Service, service_id)
    city = session.get(City, city_id)
    if not service or service.business_id != website.business_id:
        raise SiteCoverageError(
            "Service does not belong to the selected Website business."
        )
    if not city:
        raise SiteCoverageError("City not found.")
    service_decision = _service_decision(session, website.id or 0, service.id or 0)
    city_decision = _city_decision(session, website.id or 0, city.id or 0)
    county_decision = _county_decision(
        session,
        website.id or 0,
        city.county_id,
    )
    if payload.status == "included":
        if not service_decision or service_decision.status != "included":
            raise SiteCoverageError(
                "Include the Website service before including a Service × City combination."
            )
        if not city_decision or city_decision.status != "included":
            raise SiteCoverageError(
                "Include the Website city before including a Service × City combination."
            )
        if not county_decision or county_decision.status != "included":
            raise SiteCoverageError(
                "Include the City County before including a Service × City combination."
            )
    decision = session.exec(
        select(WebsiteServiceCityCoverageDecision).where(
            WebsiteServiceCityCoverageDecision.website_id == website.id,
            WebsiteServiceCityCoverageDecision.service_id == service.id,
            WebsiteServiceCityCoverageDecision.city_id == city.id,
        )
    ).first()
    decision = _apply_decision(
        decision,
        WebsiteServiceCityCoverageDecision,
        payload,
        website_id=website.id,
        service_id=service.id,
        city_id=city.id,
    )
    session.add(decision)
    session.commit()
    session.refresh(decision)
    _refresh_plan_candidates(session, plan)
    return ServiceCityCoverageDecisionRead.model_validate(decision)


def preview_expected_inventory(
    session: Session,
    plan_id: int,
) -> CoverageInventoryPreview:
    plan = _plan(session, plan_id)
    website = _website(session, plan.website_id)
    pages = list(
        session.exec(
            select(PlannedPage)
            .where(PlannedPage.site_plan_id == plan.id)
            .order_by(PlannedPage.id)
        ).all()
    )
    services = {
        item.id: item
        for item in session.exec(
            select(Service).where(Service.business_id == website.business_id)
        ).all()
        if item.id is not None
    }
    cities = {
        item.id: item
        for item in session.exec(select(City)).all()
        if item.id is not None
    }
    counties = {
        item.id: item
        for item in session.exec(select(County)).all()
        if item.id is not None
    }
    service_decisions = {
        item.service_id: item
        for item in _service_decisions(session, website.id or 0)
    }
    city_decisions = {
        item.city_id: item
        for item in _city_decisions(session, website.id or 0)
    }
    county_decisions = {
        item.county_id: item
        for item in _county_decisions(session, website.id or 0)
    }
    matrix_decisions = {
        (item.service_id, item.city_id): item
        for item in _matrix_decisions(session, website.id or 0)
    }
    expected_specs: list[dict[str, Any]] = [
        _spec(page_type, name, slug)
        for page_type, name, slug in CORE_PAGE_SPECS
    ]
    for service_id, decision in sorted(service_decisions.items()):
        service = services.get(service_id)
        if decision.status == "included" and service:
            expected_specs.append(
                _spec(
                    "service",
                    service.service_name,
                    service.service_slug,
                    service_id=service.id,
                )
            )
    for county_id, decision in sorted(county_decisions.items()):
        county = counties.get(county_id)
        if (
            decision.status == "included"
            and decision.page_appropriate
            and county
        ):
            expected_specs.append(
                _spec(
                    "county",
                    county.county_name,
                    _slugify(county.county_name),
                    county_id=county.id,
                )
            )
    included_services = {
        key for key, value in service_decisions.items() if value.status == "included"
    }
    included_cities = {
        key for key, value in city_decisions.items() if value.status == "included"
    }
    for service_id in sorted(included_services):
        for city_id in sorted(included_cities):
            service = services.get(service_id)
            city = cities.get(city_id)
            decision = matrix_decisions.get((service_id, city_id))
            if not service or not city:
                continue
            if decision and decision.status == "included":
                expected_specs.append(
                    _spec(
                        "city_service",
                        f"{service.service_name} in {city.city_name}, {city.state}",
                        f"{service.service_slug}-{city.city_slug}-{city.state.lower()}",
                        service_id=service.id,
                        city_id=city.id,
                        county_id=city.county_id,
                    )
                )

    items: list[CoverageInventoryItem] = []
    matched_page_ids: set[int] = set()
    for service_id, decision in sorted(service_decisions.items()):
        if service_id not in services:
            items.append(
                _invalid_decision_item(
                    f"service-decision:{decision.id}",
                    "service",
                    "Coverage decision references a Service outside the Website business.",
                    service_id=service_id,
                )
            )
    for city_id, decision in sorted(city_decisions.items()):
        city = cities.get(city_id)
        county_decision = (
            county_decisions.get(city.county_id)
            if city
            else None
        )
        if city is None:
            items.append(
                _invalid_decision_item(
                    f"city-decision:{decision.id}",
                    "city",
                    "Coverage decision references an unresolved City.",
                    city_id=city_id,
                )
            )
        elif decision.status == "included" and (
            county_decision is None or county_decision.status != "included"
        ):
            items.append(
                _invalid_decision_item(
                    f"city-decision:{decision.id}",
                    "city",
                    "Included City coverage requires its County to remain included.",
                    city_id=city_id,
                    county_id=city.county_id,
                )
            )
    for (service_id, city_id), decision in sorted(matrix_decisions.items()):
        service = services.get(service_id)
        city = cities.get(city_id)
        service_parent = service_decisions.get(service_id)
        city_parent = city_decisions.get(city_id)
        county_parent = county_decisions.get(city.county_id) if city else None
        if (
            service is None
            or city is None
            or service_parent is None
            or service_parent.status != "included"
            or city_parent is None
            or city_parent.status != "included"
            or county_parent is None
            or county_parent.status != "included"
        ):
            items.append(
                _invalid_decision_item(
                    f"service-city-decision:{decision.id}",
                    "city_service",
                    "Service × City decision conflicts with its Website-scoped parent coverage.",
                    service_id=service_id,
                    city_id=city_id,
                    county_id=city.county_id if city else None,
                )
            )
    for spec in expected_specs:
        matches = [page for page in pages if _page_matches(page, spec)]
        slug_owners = [
            page
            for page in pages
            if page.intended_slug == spec["intended_slug"]
            and not _page_matches(page, spec)
        ]
        if slug_owners:
            matched_page_ids.add(slug_owners[0].id or 0)
            items.append(
                _inventory_item(
                    spec,
                    "slug_conflict",
                    "The deterministic slug belongs to a different Planned Page.",
                    planned_page=slug_owners[0],
                )
            )
        elif matches:
            matches.sort(key=lambda page: page.id or 0)
            matched_page_ids.add(matches[0].id or 0)
            items.append(
                _inventory_item(
                    spec,
                    "matching",
                    "An existing Planned Page matches this approved inventory item.",
                    planned_page=matches[0],
                )
            )
            for duplicate in matches[1:]:
                items.append(
                    _item_from_page(
                        duplicate,
                        "unsupported_extra",
                        "More than one Planned Page represents the same expected inventory item.",
                    )
                )
                matched_page_ids.add(duplicate.id or 0)
        else:
            items.append(
                _inventory_item(
                    spec,
                    "missing",
                    "This approved inventory item has no matching Planned Page.",
                )
            )

    for service_id, decision in sorted(service_decisions.items()):
        if decision.status in {"excluded", "deferred"}:
            service = services.get(service_id)
            if service:
                items.append(
                    _inventory_item(
                        _spec(
                            "service",
                            service.service_name,
                            service.service_slug,
                            service_id=service.id,
                        ),
                        decision.status,
                        decision.rationale
                        or f"Operator marked this Website service {decision.status}.",
                    )
                )
    for county_id, decision in sorted(county_decisions.items()):
        if decision.status in {"excluded", "deferred"}:
            county = counties.get(county_id)
            if county:
                items.append(
                    _inventory_item(
                        _spec(
                            "county",
                            county.county_name,
                            _slugify(county.county_name),
                            county_id=county.id,
                        ),
                        decision.status,
                        decision.rationale
                        or f"Operator marked this Website County {decision.status}.",
                    )
                )
    for city_id, decision in sorted(city_decisions.items()):
        if decision.status in {"excluded", "deferred"}:
            city = cities.get(city_id)
            if city:
                items.append(
                    CoverageInventoryItem(
                        inventory_key=f"city:{city.id}",
                        page_type="city",
                        working_name=city.city_name,
                        intended_slug=city.city_slug,
                        city_id=city.id,
                        county_id=city.county_id,
                        disposition=decision.status,
                        reason=decision.rationale
                        or f"Operator marked this Website City {decision.status}.",
                    )
                )
    for service_id in sorted(included_services):
        for city_id in sorted(included_cities):
            service = services.get(service_id)
            city = cities.get(city_id)
            if not service or not city:
                continue
            decision = matrix_decisions.get((service_id, city_id))
            spec = _spec(
                "city_service",
                f"{service.service_name} in {city.city_name}, {city.state}",
                f"{service.service_slug}-{city.city_slug}-{city.state.lower()}",
                service_id=service.id,
                city_id=city.id,
                county_id=city.county_id,
            )
            if decision is None:
                items.append(
                    _inventory_item(
                        spec,
                        "pending_decision",
                        "Atlas candidate requires an explicit operator decision.",
                    )
                )
            elif decision.status in {"excluded", "deferred"}:
                items.append(
                    _inventory_item(
                        spec,
                        decision.status,
                        decision.rationale
                        or f"Operator marked this Service × City combination {decision.status}.",
                    )
                )

    for page in pages:
        if (page.id or 0) in matched_page_ids:
            continue
        relationship_error = _relationship_error(
            page,
            website,
            services,
            cities,
            counties,
        )
        if relationship_error:
            items.append(
                _item_from_page(
                    page,
                    "relationship_conflict",
                    relationship_error,
                )
            )
            continue
        if page.page_type == "service":
            decision = service_decisions.get(page.service_id)
            if not decision or decision.status != "included":
                items.append(
                    _item_from_page(
                        page,
                        "unexplained_historical",
                        "Historical Service page has no included operator coverage decision.",
                    )
                )
                continue
        if page.page_type == "county":
            decision = county_decisions.get(page.county_id)
            if (
                not decision
                or decision.status != "included"
                or not decision.page_appropriate
            ):
                items.append(
                    _item_from_page(
                        page,
                        "unexplained_historical",
                        "Historical County page has no included page-appropriate operator decision.",
                    )
                )
                continue
        if page.page_type == "city":
            items.append(
                _item_from_page(
                    page,
                    "unexplained_historical",
                    "Historical standalone City page remains visible but is not part of the current expected inventory.",
                )
            )
            continue
        if page.page_type == "city_service":
            decision = matrix_decisions.get((page.service_id, page.city_id))
            if not decision or decision.status != "included":
                items.append(
                    _item_from_page(
                        page,
                        "unexplained_historical",
                        "Historical City-Service page has no included operator coverage decision.",
                    )
                )
                continue
        if page.page_type == "informational":
            items.append(
                _item_from_page(
                    page,
                    "matching",
                    "Operator-created supporting page remains part of the Site Plan.",
                )
            )
            matched_page_ids.add(page.id or 0)
            continue
        items.append(
            _item_from_page(
                page,
                "unsupported_extra",
                "Planned Page is outside the current approved expected inventory.",
            )
        )

    counts = CoverageInventoryCounts(
        expected=sum(item.disposition in {"matching", "missing"} for item in items),
        planned=sum(item.disposition == "matching" for item in items),
        missing=sum(item.disposition == "missing" for item in items),
        excluded=sum(item.disposition == "excluded" for item in items),
        deferred=sum(item.disposition == "deferred" for item in items),
        pending_decision=sum(
            item.disposition == "pending_decision" for item in items
        ),
        unsupported_extra=sum(
            item.disposition == "unsupported_extra" for item in items
        ),
        unexplained_historical=sum(
            item.disposition == "unexplained_historical" for item in items
        ),
        relationship_conflict=sum(
            item.disposition == "relationship_conflict" for item in items
        ),
        slug_conflict=sum(item.disposition == "slug_conflict" for item in items),
    )
    blockers = []
    if counts.relationship_conflict:
        blockers.append("Resolve coverage relationship conflicts before reconciliation.")
    if counts.slug_conflict:
        blockers.append("Resolve deterministic slug conflicts before reconciliation.")
    return CoverageInventoryPreview(
        website_id=website.id or 0,
        site_plan_id=plan.id or plan_id,
        counts=counts,
        items=items,
        reconciliation_ready=not blockers,
        blocking_reasons=blockers,
    )


def reconcile_expected_inventory(
    session: Session,
    plan_id: int,
) -> CoverageReconciliationResult:
    before = preview_expected_inventory(session, plan_id)
    if not before.reconciliation_ready:
        raise SiteCoverageError("Coverage inventory reconciliation is blocked: " + " ".join(before.blocking_reasons))
    plan = _plan(session, plan_id)
    created_ids: list[int] = []
    for item in before.items:
        if item.disposition != "missing":
            continue
        created = create_planned_page(
            session,
            PlannedPageCreate(
                website_id=plan.website_id,
                site_plan_id=plan.id or plan_id,
                page_type=item.page_type,
                working_name=item.working_name,
                intended_slug=item.intended_slug,
                service_id=item.service_id,
                city_id=item.city_id,
                county_id=item.county_id,
                planning_status="planned",
            ),
        )
        created_ids.append(created.id)
    after = preview_expected_inventory(session, plan_id)
    return CoverageReconciliationResult(
        website_id=plan.website_id,
        site_plan_id=plan.id or plan_id,
        created_planned_page_ids=created_ids,
        created_count=len(created_ids),
        before=before.counts,
        after=after.counts,
        idempotent=not created_ids,
    )


def _refresh_candidates(
    session: Session,
    plan: SitePlan,
    record: WebsiteCoveragePlanningRecord,
) -> None:
    website = _website(session, plan.website_id)
    services = list(
        session.exec(
            select(Service)
            .where(
                Service.business_id == website.business_id,
                Service.status == "active",
            )
            .order_by(Service.id)
        ).all()
    )
    counties, cities = _candidate_geography(session, website)
    service_decisions = {
        item.service_id: item
        for item in _service_decisions(session, website.id or 0)
    }
    city_decisions = {
        item.city_id: item
        for item in _city_decisions(session, website.id or 0)
    }
    county_decisions = {
        item.county_id: item
        for item in _county_decisions(session, website.id or 0)
    }
    matrix_decisions = {
        (item.service_id, item.city_id): item
        for item in _matrix_decisions(session, website.id or 0)
    }
    record.website_id = website.id or 0
    record.generated_service_candidates = [
        {
            "candidate_key": f"service:{service.id}",
            "service_id": service.id,
            "service_name": service.service_name,
            "atlas_candidate_state": "eligible",
        }
        for service in services
    ]
    record.generated_county_candidates = [
        {
            "candidate_key": f"county:{county.id}",
            "county_id": county.id,
            "county_name": county.county_name,
            "state": county.state,
            "atlas_candidate_state": "eligible",
        }
        for county in counties
    ]
    record.generated_city_candidates = [
        {
            "candidate_key": f"city:{city.id}",
            "city_id": city.id,
            "city_name": city.city_name,
            "county_id": city.county_id,
            "state": city.state,
            "atlas_candidate_state": "eligible",
        }
        for city in cities
    ]
    included_services = [
        service
        for service in services
        if service_decisions.get(service.id)
        and service_decisions[service.id].status == "included"
    ]
    included_cities = [
        city
        for city in cities
        if city_decisions.get(city.id)
        and city_decisions[city.id].status == "included"
        and county_decisions.get(city.county_id)
        and county_decisions[city.county_id].status == "included"
    ]
    service_by_id = {service.id: service for service in services}
    city_by_id = {city.id: city for city in cities}
    eligible_matrix_pairs = {
        (service.id, city.id)
        for service in included_services
        for city in included_cities
    }
    matrix_pairs = eligible_matrix_pairs | set(matrix_decisions)
    record.generated_matrix_candidates = [
        {
            "candidate_key": f"service-city:{service.id}:{city.id}",
            "service_id": service.id,
            "service_name": service.service_name,
            "city_id": city.id,
            "city_name": city.city_name,
            "county_id": city.county_id,
            "atlas_candidate_state": (
                "eligible"
                if (service.id, city.id) in eligible_matrix_pairs
                else "parent_conflict"
            ),
        }
        for service_id, city_id in sorted(matrix_pairs)
        if (service := service_by_id.get(service_id)) is not None
        if (city := city_by_id.get(city_id)) is not None
    ]
    record.source_snapshot = {
        "website_id": website.id,
        "business_id": website.business_id,
        "site_plan_id": plan.id,
        "site_plan_version": plan.version,
        "website_updated_at": website.updated_at.isoformat(),
        "service_ids": [service.id for service in services],
        "county_ids": [county.id for county in counties],
        "city_ids": [city.id for city in cities],
    }
    now = datetime.now(UTC)
    record.generated_at = now
    record.updated_at = now
    session.add(record)
    session.flush()


def _candidate_geography(
    session: Session,
    website: Website,
) -> tuple[list[County], list[City]]:
    configured = website.configuration.get("market_state_codes")
    states = (
        [str(value).upper() for value in configured if str(value).strip()]
        if isinstance(configured, list)
        else []
    )
    county_statement = select(County).where(County.status == "active")
    city_statement = select(City).where(City.status == "active")
    if states:
        county_statement = county_statement.where(County.state.in_(states))
        city_statement = city_statement.where(City.state.in_(states))
    counties = list(session.exec(county_statement.order_by(County.id)).all())
    cities = list(session.exec(city_statement.order_by(City.id)).all())
    return counties, cities


def _require_candidate_county(
    session: Session,
    plan: SitePlan,
    county: County,
) -> None:
    website = _website(session, plan.website_id)
    counties, _ = _candidate_geography(session, website)
    if county.id not in {item.id for item in counties}:
        raise SiteCoverageError(
            "County is outside the Website candidate geography."
        )


def _refresh_plan_candidates(session: Session, plan: SitePlan) -> None:
    record = session.exec(
        select(WebsiteCoveragePlanningRecord).where(
            WebsiteCoveragePlanningRecord.site_plan_id == plan.id
        )
    ).first()
    if record:
        _refresh_candidates(session, plan, record)
        session.commit()


def _apply_decision(existing, model, payload, **identity):
    status = payload.status.strip().lower()
    if status not in COVERAGE_STATUSES:
        raise SiteCoverageError("Coverage status must be included, excluded, or deferred.")
    operator = " ".join(payload.decided_by.split())
    if not operator:
        raise SiteCoverageError("Operator decision provenance is required.")
    rationale = " ".join((payload.rationale or "").split()) or None
    if existing is None:
        return model(
            **identity,
            status=status,
            rationale=rationale,
            decided_by=operator,
            decided_at=datetime.now(UTC),
        )
    existing.status = status
    existing.rationale = rationale
    existing.decided_by = operator
    existing.decision_version += 1
    existing.decided_at = datetime.now(UTC)
    existing.updated_at = datetime.now(UTC)
    for key, value in identity.items():
        setattr(existing, key, value)
    return existing


def _spec(
    page_type: str,
    working_name: str,
    intended_slug: str,
    *,
    service_id: int | None = None,
    city_id: int | None = None,
    county_id: int | None = None,
) -> dict[str, Any]:
    return {
        "inventory_key": (
            f"{page_type}:{service_id or '-'}:{city_id or '-'}:{county_id or '-'}"
        ),
        "page_type": page_type,
        "working_name": working_name,
        "intended_slug": intended_slug,
        "service_id": service_id,
        "city_id": city_id,
        "county_id": county_id,
    }


def _page_matches(page: PlannedPage, spec: dict[str, Any]) -> bool:
    return (
        page.page_type == spec["page_type"]
        and page.service_id == spec["service_id"]
        and page.city_id == spec["city_id"]
        and page.county_id == spec["county_id"]
    )


def _inventory_item(
    spec: dict[str, Any],
    disposition: str,
    reason: str,
    *,
    planned_page: PlannedPage | None = None,
) -> CoverageInventoryItem:
    return CoverageInventoryItem(
        **spec,
        disposition=disposition,
        planned_page_id=planned_page.id if planned_page else None,
        generated_page_id=planned_page.generated_page_id if planned_page else None,
        reason=reason,
    )


def _item_from_page(
    page: PlannedPage,
    disposition: str,
    reason: str,
) -> CoverageInventoryItem:
    return CoverageInventoryItem(
        inventory_key=f"planned:{page.id}",
        page_type=page.page_type,
        working_name=page.working_name,
        intended_slug=page.intended_slug,
        service_id=page.service_id,
        city_id=page.city_id,
        county_id=page.county_id,
        disposition=disposition,
        planned_page_id=page.id,
        generated_page_id=page.generated_page_id,
        reason=reason,
    )


def _invalid_decision_item(
    inventory_key: str,
    page_type: str,
    reason: str,
    *,
    service_id: int | None = None,
    city_id: int | None = None,
    county_id: int | None = None,
) -> CoverageInventoryItem:
    return CoverageInventoryItem(
        inventory_key=inventory_key,
        page_type=page_type,
        working_name="Invalid coverage relationship",
        intended_slug=f"invalid-{inventory_key.replace(':', '-')}",
        service_id=service_id,
        city_id=city_id,
        county_id=county_id,
        disposition="relationship_conflict",
        reason=reason,
    )


def _relationship_error(
    page: PlannedPage,
    website: Website,
    services: dict[int, Service],
    cities: dict[int, City],
    counties: dict[int, County],
) -> str | None:
    if page.website_id != website.id:
        return "Planned Page crosses the selected Website boundary."
    if page.service_id and page.service_id not in services:
        return "Planned Page Service does not belong to the Website business."
    if page.city_id and page.city_id not in cities:
        return "Planned Page City cannot be resolved."
    if page.county_id and page.county_id not in counties:
        return "Planned Page County cannot be resolved."
    if page.city_id and page.county_id:
        city = cities[page.city_id]
        if city.county_id != page.county_id:
            return "Planned Page City and County relationships conflict."
    return None


def _slugify(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def _service_decisions(session: Session, website_id: int):
    return list(
        session.exec(
            select(WebsiteServiceCoverageDecision)
            .where(WebsiteServiceCoverageDecision.website_id == website_id)
            .order_by(WebsiteServiceCoverageDecision.service_id)
        ).all()
    )


def _county_decisions(session: Session, website_id: int):
    return list(
        session.exec(
            select(WebsiteCountyCoverageDecision)
            .where(WebsiteCountyCoverageDecision.website_id == website_id)
            .order_by(WebsiteCountyCoverageDecision.county_id)
        ).all()
    )


def _city_decisions(session: Session, website_id: int):
    return list(
        session.exec(
            select(WebsiteCityCoverageDecision)
            .where(WebsiteCityCoverageDecision.website_id == website_id)
            .order_by(WebsiteCityCoverageDecision.city_id)
        ).all()
    )


def _matrix_decisions(session: Session, website_id: int):
    return list(
        session.exec(
            select(WebsiteServiceCityCoverageDecision)
            .where(WebsiteServiceCityCoverageDecision.website_id == website_id)
            .order_by(
                WebsiteServiceCityCoverageDecision.service_id,
                WebsiteServiceCityCoverageDecision.city_id,
            )
        ).all()
    )


def _service_decision(session: Session, website_id: int, service_id: int):
    return session.exec(
        select(WebsiteServiceCoverageDecision).where(
            WebsiteServiceCoverageDecision.website_id == website_id,
            WebsiteServiceCoverageDecision.service_id == service_id,
        )
    ).first()


def _county_decision(session: Session, website_id: int, county_id: int):
    return session.exec(
        select(WebsiteCountyCoverageDecision).where(
            WebsiteCountyCoverageDecision.website_id == website_id,
            WebsiteCountyCoverageDecision.county_id == county_id,
        )
    ).first()


def _city_decision(session: Session, website_id: int, city_id: int):
    return session.exec(
        select(WebsiteCityCoverageDecision).where(
            WebsiteCityCoverageDecision.website_id == website_id,
            WebsiteCityCoverageDecision.city_id == city_id,
        )
    ).first()


def _plan(session: Session, plan_id: int) -> SitePlan:
    plan = session.get(SitePlan, plan_id)
    if not plan:
        raise SiteCoverageError("Site Plan not found.")
    return plan


def _website(session: Session, website_id: int) -> Website:
    website = session.get(Website, website_id)
    if not website:
        raise SiteCoverageError("Website not found.")
    return website
