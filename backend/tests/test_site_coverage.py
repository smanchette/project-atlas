from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.backup import export_backup, restore_backup
from app.db.seed import FLO_ZONE_COMPANY_NAME, seed_database
from app.models import (
    Brand,
    Business,
    City,
    County,
    GeneratedPage,
    PlannedPage,
    PlanningRecord,
    Service,
    SitePlan,
    Website,
    WebsiteCoveragePlanningRecord,
)
from app.schemas.site_coverage import (
    CountyCoverageDecisionUpdate,
    CoverageDecisionUpdate,
)
from app.services.site_connections import ensure_site_connection_foundation
from app.services.site_coverage import (
    SiteCoverageError,
    decide_city,
    decide_county,
    decide_service,
    decide_service_city,
    decide_service_county,
    ensure_coverage_foundation,
    preview_expected_inventory,
    read_coverage_policy,
    reconcile_expected_inventory,
)
from app.services.website_readiness import evaluate_website_readiness


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _scope(session: Session, *, label: str = "Coverage"):
    suffix = uuid4().hex[:8]
    business = Business(
        company_name=f"{label} Business {suffix}",
        business_type="Test",
        phone="407-555-0100",
        email=f"{suffix}@example.test",
        main_city="Orlando",
        state="FL",
        description="Approved business facts.",
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id,
        brand_name=f"{label} Brand {suffix}",
        status="active",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name=f"{label} Website {suffix}",
        domain=f"{label.lower()}-{suffix}.example",
        public_url=f"https://{label.lower()}-{suffix}.example",
        configuration={"market_state_codes": ["FL"]},
        status="active",
    )
    session.add(website)
    session.flush()
    service = Service(
        business_id=business.id,
        service_name=f"Termite Control {suffix}",
        service_slug=f"termite-control-{suffix}",
        status="active",
    )
    county = County(
        county_name=f"Orange {suffix}",
        state="FL",
        status="active",
    )
    session.add(service)
    session.add(county)
    session.flush()
    city = City(
        county_id=county.id,
        city_name=f"Orlando {suffix}",
        city_slug=f"orlando-{suffix}",
        state="FL",
        status="active",
    )
    session.add(city)
    session.flush()
    plan = SitePlan(
        website_id=website.id,
        plan_key="primary",
        plan_name=f"{label} Plan",
    )
    session.add(plan)
    session.flush()
    ensure_site_connection_foundation(session, plan, commit=False)
    ensure_coverage_foundation(session, plan, commit=False)
    session.commit()
    return business, website, service, county, city, plan


def _include_coverage(
    session: Session,
    website: Website,
    service: Service,
    county: County,
    city: City,
    plan: SitePlan,
):
    operator = "Coverage Reviewer"
    decide_service(
        session,
        plan.id,
        service.id,
        CoverageDecisionUpdate(
            status="included",
            rationale="Approved Website service.",
            decided_by=operator,
        ),
    )
    decide_county(
        session,
        plan.id,
        county.id,
        CountyCoverageDecisionUpdate(
            status="included",
            page_appropriate=True,
            rationale="Approved service area and County page.",
            decided_by=operator,
        ),
    )
    decide_city(
        session,
        plan.id,
        city.id,
        CoverageDecisionUpdate(
            status="included",
            rationale="Approved Website city.",
            decided_by=operator,
        ),
    )
    decide_service_city(
        session,
        plan.id,
        service.id,
        city.id,
        CoverageDecisionUpdate(
            status="included",
            rationale="Approved exact Service × City combination.",
            decided_by=operator,
        ),
    )
    decide_service_county(
        session,
        plan.id,
        service.id,
        county.id,
        CoverageDecisionUpdate(
            status="included",
            rationale="Approved exact Service × County page.",
            decided_by=operator,
        ),
    )


def test_candidates_remain_separate_and_cartesian_inventory_is_deterministic():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, website, service, county, city, plan = _scope(session)
        policy = read_coverage_policy(session, plan.id)
        assert policy.service_decisions == []
        assert policy.city_decisions == []
        assert policy.matrix_decisions == []
        assert policy.planning_record.generated_service_candidates

        _include_coverage(session, website, service, county, city, plan)
        preview = preview_expected_inventory(session, plan.id)
        expected_types = {
            item.page_type
            for item in preview.items
            if item.disposition == "missing"
        }
        assert expected_types == {
            "home",
            "about",
            "contact",
            "faq",
            "service",
            "county",
            "city_service",
        }
        assert preview.counts.expected == 7
        assert preview.counts.pending_decision == 0
        assert preview.reconciliation_ready is True


def test_reconciliation_creates_only_planning_records_and_is_idempotent():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, website, service, county, city, plan = _scope(session)
        _include_coverage(session, website, service, county, city, plan)
        generated_before = session.exec(select(GeneratedPage)).all()

        first = reconcile_expected_inventory(session, plan.id)
        assert first.created_count == 7
        assert first.after.missing == 0
        assert len(session.exec(select(PlannedPage)).all()) == 7
        assert len(session.exec(select(PlanningRecord)).all()) == 7
        assert session.exec(select(GeneratedPage)).all() == generated_before

        second = reconcile_expected_inventory(session, plan.id)
        assert second.created_count == 0
        assert second.idempotent is True
        assert len(session.exec(select(PlannedPage)).all()) == 7
        assert len(session.exec(select(PlanningRecord)).all()) == 7


def test_excluded_and_deferred_decisions_never_become_expected_pages():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, service, county, city, plan = _scope(session)
        decide_service(
            session,
            plan.id,
            service.id,
            CoverageDecisionUpdate(
                status="excluded",
                rationale="Not offered on this Website.",
                decided_by="Coverage Reviewer",
            ),
        )
        decide_county(
            session,
            plan.id,
            county.id,
            CountyCoverageDecisionUpdate(
                status="included",
                page_appropriate=False,
                rationale="Approved service area without a County page.",
                decided_by="Coverage Reviewer",
            ),
        )
        decide_city(
            session,
            plan.id,
            city.id,
            CoverageDecisionUpdate(
                status="deferred",
                rationale="Future market.",
                decided_by="Coverage Reviewer",
            ),
        )
        preview = preview_expected_inventory(session, plan.id)
        assert preview.counts.expected == 4
        assert preview.counts.excluded == 1
        assert preview.counts.deferred == 1
        assert not any(
            item.disposition == "missing" and item.service_id == service.id
            for item in preview.items
        )
        assert not any(
            item.disposition == "missing" and item.city_id == city.id
            for item in preview.items
        )


def test_historical_city_service_is_visible_but_never_auto_approved():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, website, service, county, city, plan = _scope(session)
        historical = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type="city_service",
            working_name="Preserved Historical Page",
            intended_slug="preserved-historical-page",
            service_id=service.id,
            county_id=county.id,
            city_id=city.id,
            planning_status="planned",
        )
        session.add(historical)
        session.commit()

        preview = preview_expected_inventory(session, plan.id)
        item = next(
            row
            for row in preview.items
            if row.planned_page_id == historical.id
        )
        assert item.disposition == "unexplained_historical"
        assert read_coverage_policy(session, plan.id).matrix_decisions == []
        assert reconcile_expected_inventory(session, plan.id).created_count == 4
        assert session.get(PlannedPage, historical.id).working_name == "Preserved Historical Page"


def test_cross_website_service_and_matrix_decisions_fail_closed():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, _, foreign_service, _, _, _ = _scope(session, label="Foreign")
        _, website, service, county, city, plan = _scope(session, label="Local")
        with pytest.raises(SiteCoverageError, match="does not belong"):
            decide_service(
                session,
                plan.id,
                foreign_service.id,
                CoverageDecisionUpdate(
                    status="included",
                    rationale="Wrong Website.",
                    decided_by="Reviewer",
                ),
            )
        _include_coverage(session, website, service, county, city, plan)
        with pytest.raises(SiteCoverageError, match="does not belong"):
            decide_service_county(
                session,
                plan.id,
                foreign_service.id,
                county.id,
                CoverageDecisionUpdate(
                    status="included",
                    rationale="Wrong Website.",
                    decided_by="Reviewer",
                ),
            )
        assert all(
            decision.service_id == service.id
            for decision in read_coverage_policy(session, plan.id).matrix_decisions
        )


def test_multiple_services_create_distinct_service_county_inventory_items():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        business, website, service, county, city, plan = _scope(session)
        _include_coverage(session, website, service, county, city, plan)
        second = Service(
            business_id=business.id,
            service_name="Rodent Exclusion",
            service_slug="rodent-exclusion",
            status="active",
        )
        session.add(second)
        session.commit()
        decide_service(
            session,
            plan.id,
            second.id,
            CoverageDecisionUpdate(
                status="included",
                rationale="Second Website service.",
                decided_by="Reviewer",
            ),
        )
        decide_service_county(
            session,
            plan.id,
            second.id,
            county.id,
            CoverageDecisionUpdate(
                status="included",
                rationale="Second exact Service × County page.",
                decided_by="Reviewer",
            ),
        )
        county_items = [
            item
            for item in preview_expected_inventory(session, plan.id).items
            if item.page_type == "county" and item.disposition == "missing"
        ]
        assert len(county_items) == 2
        assert {item.service_id for item in county_items} == {service.id, second.id}
        assert len({item.intended_slug for item in county_items}) == 2


def test_identical_names_and_shared_geography_remain_website_isolated():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, first_website, first_service, county, city, first_plan = _scope(
            session,
            label="First",
        )
        _, second_website, second_service, _, _, second_plan = _scope(
            session,
            label="Second",
        )
        second_service.service_name = first_service.service_name
        session.add(second_service)
        session.commit()
        decide_service(
            session,
            first_plan.id,
            first_service.id,
            CoverageDecisionUpdate(
                status="included",
                rationale="First Website only.",
                decided_by="First Reviewer",
            ),
        )
        decide_county(
            session,
            first_plan.id,
            county.id,
            CountyCoverageDecisionUpdate(
                status="included",
                page_appropriate=False,
                rationale="First Website geography.",
                decided_by="First Reviewer",
            ),
        )
        decide_city(
            session,
            first_plan.id,
            city.id,
            CoverageDecisionUpdate(
                status="included",
                rationale="First Website city.",
                decided_by="First Reviewer",
            ),
        )
        assert len(read_coverage_policy(session, first_plan.id).service_decisions) == 1
        assert read_coverage_policy(session, second_plan.id).service_decisions == []
        assert read_coverage_policy(session, second_plan.id).city_decisions == []
        assert first_website.id != second_website.id


def test_flo_zone_seed_pages_are_observed_without_mutation_or_silent_approval():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
        business = session.exec(
            select(Business).where(Business.company_name == FLO_ZONE_COMPANY_NAME)
        ).one()
        website = session.exec(
            select(Website).where(Website.business_id == business.id)
        ).one()
        plan = session.exec(
            select(SitePlan).where(SitePlan.website_id == website.id)
        ).one()
        generated_before = {
            page.id: page.model_dump(mode="json")
            for page in session.exec(
                select(GeneratedPage)
                .where(GeneratedPage.website_id == website.id)
                .order_by(GeneratedPage.id)
            ).all()
        }
        planned_before = {
            page.id: page.model_dump(mode="json")
            for page in session.exec(
                select(PlannedPage)
                .where(PlannedPage.website_id == website.id)
                .order_by(PlannedPage.id)
            ).all()
        }
        assert len(generated_before) == 55
        assert len(planned_before) == 55

        preview = preview_expected_inventory(session, plan.id)

        generated_after = {
            page.id: page.model_dump(mode="json")
            for page in session.exec(
                select(GeneratedPage)
                .where(GeneratedPage.website_id == website.id)
                .order_by(GeneratedPage.id)
            ).all()
        }
        planned_after = {
            page.id: page.model_dump(mode="json")
            for page in session.exec(
                select(PlannedPage)
                .where(PlannedPage.website_id == website.id)
                .order_by(PlannedPage.id)
            ).all()
        }
        assert generated_after == generated_before
        assert planned_after == planned_before
        assert preview.counts.unexplained_historical == 55
        assert read_coverage_policy(session, plan.id).matrix_decisions == []


def test_parent_decision_drift_is_reported_and_blocks_reconciliation():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, website, service, county, city, plan = _scope(session)
        _include_coverage(session, website, service, county, city, plan)
        decide_county(
            session,
            plan.id,
            county.id,
            CountyCoverageDecisionUpdate(
                status="deferred",
                page_appropriate=False,
                rationale="Temporarily deferred for review.",
                decided_by="Coverage Reviewer",
            ),
        )
        preview = preview_expected_inventory(session, plan.id)
        assert preview.counts.relationship_conflict == 3
        assert preview.reconciliation_ready is False
        policy = read_coverage_policy(session, plan.id)
        assert policy.planning_record.generated_matrix_candidates[0][
            "atlas_candidate_state"
        ] == "parent_conflict"
        with pytest.raises(SiteCoverageError, match="relationship conflicts"):
            reconcile_expected_inventory(session, plan.id)


def test_coverage_readiness_preserves_navigation_and_future_dimensions():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, website, service, county, city, plan = _scope(session)
        _include_coverage(session, website, service, county, city, plan)
        report = evaluate_website_readiness(session, plan.id)
        website_category = next(
            category
            for category in report.categories
            if category.key == "website_readiness"
        )
        keys = {item.key for item in website_category.items}
        assert "coverage_core_pages" in keys
        assert "coverage_city_service_matrix" in keys
        assert "site_connections_navigation_sets" in keys
        assert "approved_brand_assets" in keys
        assert "website_identity_asset_selections" in keys
        assert {
            "theme_selection",
            "theme_approval",
            "theme_token_contract",
            "theme_accessibility",
            "theme_composition_freshness",
        } <= keys
        future = next(
            category
            for category in report.categories
            if category.key == "future_readiness"
        )
        assert {
            "complete_site_preview",
            "media",
            "media_ingestion",
            "publication",
        } <= {
            item.key for item in future.items
        }
        assert "theme" not in {item.key for item in future.items}
        assert all(item.status in {"deferred", "not_assessed"} for item in future.items)


def test_backup_round_trip_preserves_coverage_decisions_and_provenance(tmp_path):
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _, website, service, county, city, plan = _scope(session)
        _include_coverage(session, website, service, county, city, plan)
        result = export_backup(session, backup_dir=tmp_path)

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, result["path"])
        restored_plan = session.exec(select(SitePlan)).one()
        policy = read_coverage_policy(session, restored_plan.id)
        assert len(policy.service_decisions) == 1
        assert len(policy.county_decisions) == 1
        assert len(policy.city_decisions) == 1
        assert len(policy.matrix_decisions) == 1
        assert len(policy.service_county_decisions) == 1
        assert policy.matrix_decisions[0].decided_by == "Coverage Reviewer"
        assert policy.matrix_decisions[0].decision_version == 1
        assert policy.matrix_decisions[0].decided_at is not None
        assert policy.matrix_decisions[0].rationale == (
            "Approved exact Service × City combination."
        )
        assert session.exec(select(WebsiteCoveragePlanningRecord)).one()
