from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Brand,
    Business,
    City,
    County,
    GeneratedPage,
    PlannedPage,
    Service,
    SitePlan,
    Website,
    WebsiteCityCoverageDecision,
    WebsiteCountyCoverageDecision,
    WebsiteIdentity,
    WebsiteServiceCityCoverageDecision,
    WebsiteServiceCountyCoverageDecision,
    WebsiteServiceCoverageDecision,
)
from app.schemas.page_editor import ManualDraftSaveRequest
from app.services.drafting_eligibility import assess_site_plan
from app.services.page_editor import save_manual_draft
from app.services.page_export import build_page_export_package
from app.services.page_qa import evaluate_page_qa, save_page_qa
from app.services.planned_page_drafting import (
    draft_planned_page,
    evaluate_draft_readiness,
)
from app.services.site_planning import refresh_planning_record


def _website_scope(
    session: Session,
    suffix: str,
    *,
    county_names: tuple[str, ...] = ("Orange", "Seminole"),
    approve_value: bool = True,
):
    business = Business(
        company_name=f"County Business {suffix}",
        business_type="Pest control",
        phone="407-555-0100",
        email=f"county-{suffix}@example.test",
        main_city="Orlando",
        state="FL",
        description="Approved factual business description.",
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id,
        brand_name=f"County Brand {suffix}",
        status="active",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name=f"County Website {suffix}",
        domain=f"county-{suffix}.example.test",
        public_url=f"https://county-{suffix}.example.test/",
        status="active",
    )
    service = Service(
        business_id=business.id,
        service_name=f"Termite Tenting {suffix}",
        service_slug=f"termite-tenting-{suffix}",
        short_description="Approved tenting service description.",
        long_description=(
            "Approved detailed tenting service information. "
            "Call 407-555-0100 to discuss service."
        ),
        status="active",
    )
    session.add_all([website, service])
    session.flush()
    session.add(
        WebsiteIdentity(
            website_id=website.id,
            display_name=f"County Brand {suffix}",
            status="active",
        )
    )
    plan = SitePlan(
        website_id=website.id,
        plan_key="primary",
        plan_name=f"County Plan {suffix}",
    )
    session.add(plan)
    session.flush()
    session.add(
        WebsiteServiceCoverageDecision(
            website_id=website.id,
            service_id=service.id,
            status="included",
            rationale="Approved Website service.",
            decided_by="operator@example.test",
        )
    )

    county_pages: list[PlannedPage] = []
    all_cities: list[City] = []
    for county_index, county_name in enumerate(county_names):
        county = County(
            county_name=f"{county_name} {suffix} County",
            state="FL",
            status="active",
        )
        session.add(county)
        session.flush()
        session.add(
            WebsiteCountyCoverageDecision(
                website_id=website.id,
                county_id=county.id,
                status="included",
                page_appropriate=True,
                rationale="Approved County service-area page.",
                decided_by="operator@example.test",
            )
        )
        if approve_value:
            session.add(
                WebsiteServiceCountyCoverageDecision(
                    website_id=website.id,
                    service_id=service.id,
                    county_id=county.id,
                    status="included",
                    rationale="Approved exact Service × County page.",
                    decided_by="operator@example.test",
                )
            )
        cities: list[City] = []
        if approve_value:
            for city_index in range(2):
                city = City(
                    county_id=county.id,
                    city_name=f"{county_name} City {city_index + 1} {suffix}",
                    city_slug=(
                        f"{county_name.lower()}-{county_index}-{city_index}-{suffix}"
                    ),
                    state="FL",
                    status="active",
                )
                session.add(city)
                session.flush()
                cities.append(city)
                all_cities.append(city)
                session.add(
                    WebsiteCityCoverageDecision(
                        website_id=website.id,
                        city_id=city.id,
                        status="included",
                        rationale="Approved included City.",
                        decided_by="operator@example.test",
                    )
                )
                session.add(
                    WebsiteServiceCityCoverageDecision(
                        website_id=website.id,
                        service_id=service.id,
                        city_id=city.id,
                        status="included",
                        rationale="Approved Service × City coverage.",
                        decided_by="operator@example.test",
                    )
                )
        county_page = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type="county",
            working_name=(
                f"{service.service_name} in {county.county_name}, Florida"
            ),
            intended_slug=(
                f"{service.service_slug}-{county_name.lower()}-{suffix}-county-fl"
            ),
            service_id=service.id,
            county_id=county.id,
        )
        session.add(county_page)
        session.flush()
        county_pages.append(county_page)
        for city in cities:
            city_service_page = PlannedPage(
                website_id=website.id,
                site_plan_id=plan.id,
                page_type="city_service",
                working_name=f"{service.service_name} in {city.city_name}",
                intended_slug=f"{service.service_slug}-{city.city_slug}",
                service_id=service.id,
                city_id=city.id,
                county_id=county.id,
            )
            session.add(city_service_page)
    service_page = PlannedPage(
        website_id=website.id,
        site_plan_id=plan.id,
        page_type="service",
        working_name=service.service_name,
        intended_slug=service.service_slug,
        service_id=service.id,
    )
    session.add(service_page)
    session.flush()
    for page in session.exec(
        select(PlannedPage).where(PlannedPage.site_plan_id == plan.id)
    ).all():
        refresh_planning_record(session, page.id or 0, commit=False)
    session.commit()
    return website, plan, service, county_pages, all_cities


def test_county_contract_uses_approved_coverage_and_produces_distinct_briefs():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, _, county_pages, cities = _website_scope(session, "distinct")
        manifest = assess_site_plan(session, plan.id)
        assessments = {
            item.planned_page_id: item for item in manifest.assessments
        }
        briefs = {
            item.planned_page_id: item for item in manifest.distinctness_briefs
        }
        intents = {briefs[page.id].search_intent for page in county_pages}
        assert len(intents) == len(county_pages)
        for page in county_pages:
            assessment = assessments[page.id]
            brief = briefs[page.id]
            county = session.get(County, page.county_id)
            own_cities = [item for item in cities if item.county_id == county.id]
            assert assessment.status == "eligible"
            assert assessment.effective_eligible is True
            assert county.county_name in brief.search_intent
            assert all(item.city_name in brief.search_intent for item in own_cities)
            assert {
                "type": "approved_county",
                "id": county.id,
                "state": county.state,
            } in brief.approved_fact_identities
            assert brief.required_page_specific_value
            assert all(item["approved"] for item in brief.required_page_specific_value)
            assert not any(
                item["kind"] in {"duplicate_intent", "geographic_substitution"}
                for item in assessment.semantic_findings
            )
            assert evaluate_draft_readiness(session, page).status == "ready"
        assert website.id == manifest.website_id


def test_county_name_and_coverage_relationship_without_approved_value_fails_closed():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, plan, _, county_pages, _ = _website_scope(
            session,
            "name-only",
            county_names=("Orange", "Seminole"),
            approve_value=False,
        )
        manifest = assess_site_plan(session, plan.id)
        for page in county_pages:
            assessment = next(
                item
                for item in manifest.assessments
                if item.planned_page_id == page.id
            )
            assert assessment.effective_eligible is False
            assert assessment.status == "excluded_by_coverage"
            assert assessment.local_value_findings == []
            substitution = next(
                item
                for item in assessment.semantic_findings
                if item["kind"] == "geographic_substitution"
            )
            assert substitution["target_planned_page_id"] in {
                item.id for item in county_pages if item.id != page.id
            }
            assert "differ only by geography" in substitution["explanation"]
            readiness = evaluate_draft_readiness(session, page)
            assert readiness.status == "blocked"
            assert any(
                item["key"] == "approved_service_county_page"
                and item["available"] is False
                for item in readiness.required_information
            )


def test_county_draft_integrates_edit_qa_preview_contract_and_export_readiness(
    monkeypatch,
):
    for target in (
        "app.services.planned_page_drafting.require_effective_drafting_eligibility",
        "app.services.page_editor.require_effective_drafting_eligibility",
    ):
        monkeypatch.setattr(target, lambda *args, **kwargs: None)
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, _, county_pages, _ = _website_scope(
            session, "lifecycle", county_names=("Orange",)
        )
        page = county_pages[0]
        # Public destination projections intentionally fail closed unless every
        # related Planned Page has an exact Generated Page identity. Active Atlas
        # already satisfies that invariant; establish the same lifecycle state in
        # this isolated integration fixture without drafting the related pages.
        related_pages = list(
            session.exec(
                select(PlannedPage).where(
                    PlannedPage.site_plan_id == plan.id,
                    PlannedPage.id != page.id,
                )
            ).all()
        )
        for related in related_pages:
            generated_target = GeneratedPage(
                business_id=website.business_id,
                website_id=website.id,
                service_id=related.service_id,
                city_id=related.city_id,
                county_id=related.county_id,
                page_type=related.page_type,
                page_title=related.working_name,
                page_slug=related.intended_slug,
                draft_content={},
                generation_status="not_generated",
            )
            session.add(generated_target)
            session.flush()
            related.generated_page_id = generated_target.id
            session.add(related)
        session.commit()
        assess_site_plan(session, plan.id)
        generated, readiness = draft_planned_page(
            session, page.id, expected_website_id=website.id
        )
        assert readiness.status == "ready"
        assert generated.page_type == "county"
        assert generated.service_id == page.service_id
        assert generated.county_id == page.county_id
        assert {item["key"] for item in generated.draft_content["sections"]} == {
            "service_county_intro",
            "cities_served",
            "how_service_works",
            "customer_expectations",
            "preparation_guidance",
            "trust_and_license",
            "related_city_services",
        }
        assert generated.draft_content["image_placements"]
        assert generated.draft_content["related_pages"]
        public_copy = " ".join(
            [
                generated.draft_content["title"],
                generated.draft_content["h1"],
                generated.draft_content["intro"],
                generated.draft_content["call_to_action"],
                *[
                    f"{item['heading']} {item['body']}"
                    for item in generated.draft_content["sections"]
                ],
            ]
        ).lower()
        for internal_phrase in (
            "approved coverage",
            "included cities",
            "coverage relationship",
            "page appropriate",
            "inventory",
            "reconciliation",
        ):
            assert internal_phrase not in public_copy
        qa = evaluate_page_qa(session, generated.id)
        assert qa.readiness_status == "ready"
        assert next(
            item for item in qa.checks if item.key == "county_name"
        ).status == "pass"

        assess_site_plan(session, plan.id)
        draft = dict(generated.draft_content)
        editable = {
            key: draft[key]
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
        editable["intro"] = draft["intro"] + " Contact the office for current availability."
        saved, revision, saved_qa = save_manual_draft(
            session,
            generated.id,
            ManualDraftSaveRequest(
                draft=editable,
                created_by="Local reviewer",
                reason="County contract editing proof",
            ),
            run_qa=True,
        )
        assert revision.changed_fields == ["intro"]
        assert saved_qa and saved_qa.readiness_status == "ready"
        saved.status = "approved"
        session.add(saved)
        save_page_qa(session, saved.id, commit=False)
        session.commit()
        package = build_page_export_package(session, saved.id)
        assert package.export_ready is True
        assert package.county
        assert package.city is None
        assert package.service


def test_county_distinctness_and_sources_are_strictly_website_scoped():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        first_website, first_plan, _, first_pages, _ = _website_scope(
            session, "first", county_names=("Orange",)
        )
        second_website, second_plan, _, second_pages, _ = _website_scope(
            session, "second", county_names=("Orange",)
        )
        first = assess_site_plan(session, first_plan.id)
        second = assess_site_plan(session, second_plan.id)
        first_brief = next(
            item for item in first.distinctness_briefs
            if item.planned_page_id == first_pages[0].id
        )
        second_brief = next(
            item for item in second.distinctness_briefs
            if item.planned_page_id == second_pages[0].id
        )
        assert first_website.id != second_website.id
        assert not (
            set(first_brief.related_planned_page_ids)
            & {item.id for item in second_pages}
        )
        assert not (
            set(second_brief.related_planned_page_ids)
            & {item.id for item in first_pages}
        )
        assert "first" in first_brief.search_intent
        assert "second" not in first_brief.search_intent


def test_county_foundation_contains_no_production_transport():
    source = (
        Path(__file__).resolve().parents[1]
        / "app/services/county_page_contract.py"
    ).read_text(encoding="utf-8").lower()
    assert "requests." not in source
    assert "httpx." not in source
    assert "siteground" not in source
    assert "/wp-json/" not in source
