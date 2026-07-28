from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.backup import export_backup, restore_backup
from app.db.seed import FLO_ZONE_COMPANY_NAME, seed_database
from app.db.session import create_db_and_tables, engine
from app.models import (
    Brand,
    Business,
    GeneratedPage,
    PlannedPage,
    PlanningRecord,
    Service,
    SitePlan,
    Website,
    WebsiteIdentity,
)
from app.schemas.qa import QABatchRequest
from app.schemas.site_plans import PlannedPageCreate
from app.services.approval_queue import build_approval_queue
from app.services.draft_generation import generate_page_draft, preview_batch
from app.services.page_export import build_selected_packages
from app.services.page_qa import preview_qa_batch
from app.services.page_queue import create_city_service_page_queue
from app.services.site_planning import (
    SitePlanningError,
    backfill_existing_generated_pages,
    create_planned_page,
    refresh_planning_record,
    update_planning_overrides,
)
from app.services.website_context import WebsiteContextError, resolve_website_for_business
from app.services.wordpress_draft_queue import build_wordpress_draft_queue


def _seed() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        seed_database(session)


@pytest.fixture(autouse=True)
def _remove_temporary_secondary_websites():
    yield
    with Session(engine) as session:
        websites = list(
            session.exec(
                select(Website).where(Website.domain.like("secondary-%.example"))
            ).all()
        )
        for website in websites:
            brand_id = website.brand_id
            planned_pages = list(
                session.exec(
                    select(PlannedPage).where(PlannedPage.website_id == website.id)
                ).all()
            )
            planned_ids = [page.id for page in planned_pages if page.id is not None]
            for record in session.exec(
                select(PlanningRecord).where(
                    PlanningRecord.planned_page_id.in_(planned_ids)
                )
            ).all() if planned_ids else []:
                session.delete(record)
            for planned in planned_pages:
                session.delete(planned)
            for page in session.exec(
                select(GeneratedPage).where(GeneratedPage.website_id == website.id)
            ).all():
                session.delete(page)
            for plan in session.exec(
                select(SitePlan).where(SitePlan.website_id == website.id)
            ).all():
                session.delete(plan)
            for identity in session.exec(
                select(WebsiteIdentity).where(WebsiteIdentity.website_id == website.id)
            ).all():
                session.delete(identity)
            session.delete(website)
            if brand_id:
                brand = session.get(Brand, brand_id)
                if brand:
                    session.delete(brand)
        session.commit()


def _flo(session: Session) -> tuple[Business, Website, Service, SitePlan]:
    business = session.exec(
        select(Business).where(Business.company_name == FLO_ZONE_COMPANY_NAME)
    ).one()
    website = session.exec(
        select(Website).where(Website.business_id == business.id)
    ).first()
    service = session.exec(
        select(Service).where(Service.business_id == business.id)
    ).first()
    plan = session.exec(
        select(SitePlan).where(SitePlan.website_id == website.id)
    ).first()
    assert website and service and plan
    return business, website, service, plan


def test_all_initial_page_types_create_automatic_planning_records() -> None:
    _seed()
    suffix = uuid4().hex[:8]
    with Session(engine) as session:
        _, website, service, plan = _flo(session)
        generated = session.exec(
            select(GeneratedPage).where(GeneratedPage.website_id == website.id)
        ).first()
        assert generated and generated.city_id and generated.county_id
        cases = [
            ("home", None, None, None),
            ("about", None, None, None),
            ("contact", None, None, None),
            ("service", service.id, None, None),
            ("county", None, None, generated.county_id),
            ("city", None, generated.city_id, generated.county_id),
            ("city_service", service.id, generated.city_id, generated.county_id),
            ("informational", None, None, None),
            ("faq", None, None, None),
        ]
        for page_type, service_id, city_id, county_id in cases:
            created = create_planned_page(
                session,
                PlannedPageCreate(
                    website_id=website.id,
                    site_plan_id=plan.id,
                    page_type=page_type,
                    working_name=f"{page_type.title()} {suffix}",
                    intended_slug=f"{page_type}-{suffix}",
                    service_id=service_id,
                    city_id=city_id,
                    county_id=county_id,
                ),
            )
            assert created.planning_record.generated_answers["purpose"]
            assert created.planning_record.generated_answers["primary_action"]
            assert created.planning_record.generated_answers["relationships"]
            assert 0 <= created.planning_record.confidence_score <= 1
            assert created.planning_record.missing_information == list(
                created.planning_record.missing_information
            )
        home = session.exec(
            select(PlannedPage).where(
                PlannedPage.website_id == website.id,
                PlannedPage.intended_slug == f"home-{suffix}",
            )
        ).one()
        assert home.service_id is None
        assert home.city_id is None


def test_operator_overrides_remain_distinct_and_refresh_preserves_them() -> None:
    _seed()
    suffix = uuid4().hex[:8]
    with Session(engine) as session:
        _, website, _, plan = _flo(session)
        created = create_planned_page(
            session,
            PlannedPageCreate(
                website_id=website.id,
                site_plan_id=plan.id,
                page_type="about",
                working_name=f"About {suffix}",
                intended_slug=f"about-{suffix}",
            ),
        )
        original = created.planning_record.generated_answers["purpose"]
        overridden = update_planning_overrides(
            session,
            created.id,
            {"purpose": "Operator-reviewed purpose."},
        )
        assert overridden.generated_answers["purpose"] == original
        assert overridden.operator_overrides["purpose"] == "Operator-reviewed purpose."
        assert overridden.effective_answers["purpose"] == "Operator-reviewed purpose."
        website.configuration = {
            **website.configuration,
            "target_customer_types": ["Property managers"],
        }
        session.add(website)
        session.commit()
        refreshed = refresh_planning_record(session, created.id)
        assert refreshed.operator_overrides["purpose"] == "Operator-reviewed purpose."
        assert refreshed.generated_answers["audiences"] == ["Property managers"]
        assert refreshed.source_snapshot["provider_sources"] == [
            "approved_website_context",
            "approved_knowledge",
        ]


def test_low_confidence_and_recommendations_do_not_block_existing_generation() -> None:
    _seed()
    with Session(engine) as session:
        _, website, _, _ = _flo(session)
        page = session.exec(
            select(GeneratedPage).where(
                GeneratedPage.website_id == website.id,
                GeneratedPage.generation_status == "not_generated",
            )
        ).first()
        assert page
        planned = session.exec(
            select(PlannedPage).where(PlannedPage.generated_page_id == page.id)
        ).one()
        record = session.exec(
            select(PlanningRecord).where(PlanningRecord.planned_page_id == planned.id)
        ).one()
        record.confidence_score = 0
        record.confidence_level = "low"
        record.missing_information = ["Additional approved information would improve this page."]
        record.improvement_recommendations = ["Add supporting media."]
        session.add(record)
        session.commit()
        generated = generate_page_draft(
            session,
            page.id,
            expected_website_id=website.id,
        )
        assert generated.generation_status == "generated"


def test_two_websites_share_slug_but_lifecycle_operations_remain_isolated() -> None:
    _seed()
    suffix = uuid4().hex[:8]
    with Session(engine) as session:
        business, primary, service, _ = _flo(session)
        brand = Brand(
            business_id=business.id,
            brand_name=f"Flo Secondary {suffix}",
            status="active",
        )
        session.add(brand)
        session.flush()
        secondary = Website(
            business_id=business.id,
            brand_id=brand.id,
            website_name=f"Flo Secondary {suffix}",
            domain=f"secondary-{suffix}.example",
            public_url=f"https://secondary-{suffix}.example",
            status="active",
        )
        session.add(secondary)
        session.commit()
        session.refresh(secondary)

        with pytest.raises(WebsiteContextError, match="Explicit Website selection"):
            resolve_website_for_business(session, business)

        created_count = create_city_service_page_queue(
            session,
            business_company_name=business.company_name,
            service_slug=service.service_slug,
            website_id=secondary.id,
        )
        assert created_count > 0
        primary_page = session.exec(
            select(GeneratedPage).where(GeneratedPage.website_id == primary.id)
        ).first()
        assert primary_page
        secondary_page = session.exec(
            select(GeneratedPage).where(
                GeneratedPage.website_id == secondary.id,
                GeneratedPage.page_slug == primary_page.page_slug,
            )
        ).one()
        assert secondary_page.id != primary_page.id

        with pytest.raises(HTTPException, match="exactly one"):
            build_approval_queue(session)
        with pytest.raises(HTTPException, match="exactly one"):
            build_wordpress_draft_queue(session)

        preview = preview_batch(
            session,
            website_id=secondary.id,
            city_ids=[secondary_page.city_id],
        )
        assert preview.candidates
        assert {item.page_id for item in preview.candidates} == {secondary_page.id}
        assert all(
            item.page_id != primary_page.id for item in build_approval_queue(
                session,
                website_id=secondary.id,
            ).items
        )

        with pytest.raises(HTTPException, match="does not belong"):
            preview_qa_batch(
                session,
                QABatchRequest(
                    website_id=primary.id,
                    page_ids=[primary_page.id, secondary_page.id],
                ),
            )
        with pytest.raises(HTTPException, match="exactly one"):
            build_selected_packages(
                session,
                [primary_page.id, secondary_page.id],
            )
        with pytest.raises(HTTPException, match="does not belong"):
            generate_page_draft(
                session,
                secondary_page.id,
                expected_website_id=primary.id,
            )


def test_cross_business_planning_relationships_fail_closed() -> None:
    _seed()
    suffix = uuid4().hex[:8]
    with Session(engine) as session:
        _, website, _, plan = _flo(session)
        other_business = Business(
            company_name=f"Northstar {suffix}",
            business_type="Property maintenance",
            state="GA",
        )
        session.add(other_business)
        session.flush()
        other_service = Service(
            business_id=other_business.id,
            service_name=f"Inspection {suffix}",
            service_slug=f"inspection-{suffix}",
            status="active",
        )
        session.add(other_service)
        session.commit()
        with pytest.raises(SitePlanningError, match="does not belong"):
            create_planned_page(
                session,
                PlannedPageCreate(
                    website_id=website.id,
                    site_plan_id=plan.id,
                    page_type="service",
                    working_name=f"Wrong service {suffix}",
                    intended_slug=f"wrong-service-{suffix}",
                    service_id=other_service.id,
                ),
            )


def test_flo_zone_backfill_is_idempotent_and_preserves_generated_pages() -> None:
    _seed()
    with Session(engine) as session:
        _, website, _, plan = _flo(session)
        before = {
            page.id: page.model_dump()
            for page in session.exec(
                select(GeneratedPage)
                .where(GeneratedPage.website_id == website.id)
                .order_by(GeneratedPage.id)
            ).all()
        }
        assert backfill_existing_generated_pages(session) == 0
        after = {
            page.id: page.model_dump()
            for page in session.exec(
                select(GeneratedPage)
                .where(GeneratedPage.website_id == website.id)
                .order_by(GeneratedPage.id)
            ).all()
        }
        assert after == before
        planned = session.exec(
            select(PlannedPage).where(PlannedPage.site_plan_id == plan.id)
        ).all()
        assert len(planned) >= len(before)
        assert {item.generated_page_id for item in planned if item.generated_page_id} >= set(before)


def test_site_plan_backup_round_trip_is_complete_and_idempotent(tmp_path) -> None:
    _seed()
    suffix = uuid4().hex[:8]
    with Session(engine) as session:
        _, website, _, plan = _flo(session)
        created = create_planned_page(
            session,
            PlannedPageCreate(
                website_id=website.id,
                site_plan_id=plan.id,
                page_type="informational",
                working_name=f"Backup page {suffix}",
                intended_slug=f"backup-page-{suffix}",
            ),
        )
        record_id = created.planning_record.id
        page_id = created.id
        export = export_backup(session, backup_dir=tmp_path)

        record = session.get(PlanningRecord, record_id)
        planned = session.get(PlannedPage, page_id)
        assert record and planned
        session.delete(record)
        session.delete(planned)
        session.commit()

        restore_backup(session, export["path"])
        restore_backup(session, export["path"])
        restored = session.exec(
            select(PlannedPage).where(
                PlannedPage.website_id == website.id,
                PlannedPage.intended_slug == f"backup-page-{suffix}",
            )
        ).one()
        restored_record = session.exec(
            select(PlanningRecord).where(PlanningRecord.planned_page_id == restored.id)
        ).one()
        assert restored.working_name == f"Backup page {suffix}"
        assert restored_record.generated_answers["purpose"]
