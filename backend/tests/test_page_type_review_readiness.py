from uuid import uuid4

import pytest
from sqlmodel import Session, select

from app.db.session import create_db_and_tables, engine
from app.models import (
    Brand,
    Business,
    GeneratedPage,
    GeneratedPageRevision,
    PlannedPage,
    PlanningRecord,
    SitePlan,
    Website,
    WebsiteIdentity,
)
from app.schemas.page_editor import ManualDraftSaveRequest
from app.schemas.site_plans import PlannedPageCreate
from app.services.page_editor import save_manual_draft
from app.services.page_export import build_page_export_package
from app.services.page_qa import evaluate_page_qa
from app.services.approval_queue import build_approval_queue
from app.services.page_type_review import (
    CITY_SERVICE_CONTRACT,
    PLANNED_PAGE_CONTRACTS,
)
from app.services.planned_page_drafting import draft_planned_page
from app.services.site_planning import create_planned_page
from app.services.website_readiness import evaluate_website_readiness


@pytest.fixture(autouse=True)
def isolate_review_contract_tests_from_predraft_gate(monkeypatch):
    for target in (
        "app.services.planned_page_drafting.require_effective_drafting_eligibility",
        "app.services.draft_generation.require_effective_drafting_eligibility",
        "app.services.page_editor.require_effective_drafting_eligibility",
    ):
        monkeypatch.setattr(target, lambda *args, **kwargs: None)


def test_review_contract_registry_is_explicit_and_preserves_legacy_boundary() -> None:
    assert set(PLANNED_PAGE_CONTRACTS) == {
        "home",
        "about",
        "contact",
        "service",
        "county",
        "informational",
        "faq",
    }
    assert all(
        contract.schema == "planned-page-draft-v1"
        and contract.media_policy == "deferred"
        for contract in PLANNED_PAGE_CONTRACTS.values()
    )
    assert CITY_SERVICE_CONTRACT.schema == "legacy-city-service-v1"
    assert CITY_SERVICE_CONTRACT.media_policy == "required"
    assert CITY_SERVICE_CONTRACT.require_service is True
    assert CITY_SERVICE_CONTRACT.require_city is True
    assert CITY_SERVICE_CONTRACT.require_county is True
    assert PLANNED_PAGE_CONTRACTS["county"].require_county is True
    assert PLANNED_PAGE_CONTRACTS["county"].require_service is True
    assert PLANNED_PAGE_CONTRACTS["county"].required_section_keys == (
        "service_county_intro",
        "cities_served",
        "how_service_works",
        "customer_expectations",
        "preparation_guidance",
        "trust_and_license",
        "related_city_services",
    )


def _scope(session: Session):
    suffix = uuid4().hex[:10]
    business = Business(
        company_name=f"Readiness Business {suffix}",
        business_type="Test business",
        phone="407-555-0100",
        email=f"hello-{suffix}@example.test",
        main_city="Orlando",
        state="FL",
        license_number=f"TEST-{suffix}",
        description="A factual test business description.",
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id,
        brand_name=f"Readiness Brand {suffix}",
        status="active",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name=f"Readiness Website {suffix}",
        domain=f"readiness-{suffix}.example",
        public_url=f"https://readiness-{suffix}.example",
        status="active",
    )
    session.add(website)
    session.flush()
    session.add(
        WebsiteIdentity(
            website_id=website.id,
            display_name=f"Readiness Brand {suffix}",
            status="active",
        )
    )
    plan = SitePlan(
        website_id=website.id,
        plan_key="primary",
        plan_name="Readiness Test Plan",
    )
    session.add(plan)
    session.commit()
    planned = create_planned_page(
        session,
        PlannedPageCreate(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type="about",
            working_name="About",
            intended_slug="about",
        ),
    )
    return business, website, plan, session.get(PlannedPage, planned.id)


def _cleanup(session: Session, website_id: int, business_id: int) -> None:
    plans = list(session.exec(select(SitePlan).where(SitePlan.website_id == website_id)).all())
    planned = list(
        session.exec(select(PlannedPage).where(PlannedPage.website_id == website_id)).all()
    )
    generated_ids = [page.generated_page_id for page in planned if page.generated_page_id]
    planned_ids = [page.id for page in planned if page.id]
    if generated_ids:
        for revision in session.exec(
            select(GeneratedPageRevision).where(
                GeneratedPageRevision.generated_page_id.in_(generated_ids)
            )
        ).all():
            session.delete(revision)
    if planned_ids:
        for record in session.exec(
            select(PlanningRecord).where(PlanningRecord.planned_page_id.in_(planned_ids))
        ).all():
            session.delete(record)
    for page in planned:
        session.delete(page)
    session.flush()
    if generated_ids:
        for generated in session.exec(
            select(GeneratedPage).where(GeneratedPage.id.in_(generated_ids))
        ).all():
            session.delete(generated)
    for plan in plans:
        session.delete(plan)
    for identity in session.exec(
        select(WebsiteIdentity).where(WebsiteIdentity.website_id == website_id)
    ).all():
        session.delete(identity)
    website = session.get(Website, website_id)
    brand_id = website.brand_id if website else None
    if website:
        session.delete(website)
    session.flush()
    if brand_id:
        brand = session.get(Brand, brand_id)
        if brand:
            session.delete(brand)
    business = session.get(Business, business_id)
    if business:
        session.delete(business)
    session.commit()


def test_planned_page_contract_supports_edit_qa_export_and_readiness() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        business, website, plan, planned = _scope(session)
        business_id, website_id = business.id, website.id
        try:
            generated, readiness = draft_planned_page(
                session,
                planned.id,
                expected_website_id=website.id,
            )
            assert readiness.status == "ready"
            initial = evaluate_page_qa(session, generated.id)
            assert initial.readiness_status == "ready"
            assert not any(check.key.startswith("hero_") for check in initial.checks)

            before = dict(generated.draft_content)
            editable = {
                key: before[key]
                for key in (
                    "title",
                    "meta_title",
                    "meta_description",
                    "h1",
                    "intro",
                    "sections",
                    "faq_items",
                    "call_to_action",
                )
            }
            editable["intro"] = "An operator-reviewed factual company introduction."
            saved, revision, qa = save_manual_draft(
                session,
                generated.id,
                ManualDraftSaveRequest(
                    draft=editable,
                    created_by="Local reviewer",
                    reason="Review the About introduction",
                ),
                run_qa=True,
            )
            assert qa and qa.readiness_status == "ready"
            assert revision.changed_fields == ["intro"]
            assert saved.draft_content["planning_record_id"] == before["planning_record_id"]
            assert saved.draft_content["schema_version"] == "planned-page-draft-v1"

            saved.status = "approved"
            session.add(saved)
            session.commit()
            package = build_page_export_package(session, saved.id)
            assert package.export_ready is True
            assert package.city is None
            assert package.service is None
            assert "WebPage" in {
                node["@type"] for node in package.json_ld["@graph"]
            }

            report = evaluate_website_readiness(session, plan.id)
            assert [category.label for category in report.categories] == [
                "Business Readiness",
                "Content Readiness",
                "Website Readiness",
                "Future Readiness",
            ]
            assert report.review_ready is False
            website_readiness = next(
                category
                for category in report.categories
                if category.key == "website_readiness"
            )
            assert any(
                item.key == "site_connections_orphaned_pages"
                and item.status == "needs_attention"
                for item in website_readiness.items
            )
            future = report.categories[-1]
            assert future.status == "deferred"
            assert all(
                item.status in {"deferred", "not_assessed"} for item in future.items
            )

            queue = build_approval_queue(session, website_id=website.id)
            assert queue.total_count == 1
            assert queue.items[0].page_id == saved.id
            assert queue.items[0].service_id is None
            assert queue.items[0].service_name == ""
        finally:
            _cleanup(session, website_id, business_id)


def test_readiness_is_website_scoped_and_unknown_draft_contract_fails_closed() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        business, website, plan, planned = _scope(session)
        business_id, website_id = business.id, website.id
        try:
            generated, _ = draft_planned_page(
                session,
                planned.id,
                expected_website_id=website.id,
            )
            broken = dict(generated.draft_content)
            broken["schema_version"] = "fabricated-draft-v9"
            generated.draft_content = broken
            session.add(generated)
            session.commit()
            qa = evaluate_page_qa(session, generated.id)
            schema_check = next(check for check in qa.checks if check.key == "draft_schema")
            assert schema_check.status == "fail"

            report = evaluate_website_readiness(session, plan.id)
            content = next(
                category
                for category in report.categories
                if category.key == "content_readiness"
            )
            contract_item = next(
                item for item in content.items if item.key == "page_type_contracts"
            )
            assert contract_item.status == "needs_attention"
            assert contract_item.affected_planned_page_ids == [planned.id]
            assert all(
                page_id == planned.id
                for category in report.categories
                for item in category.items
                for page_id in item.affected_planned_page_ids
            )
        finally:
            _cleanup(session, website_id, business_id)
