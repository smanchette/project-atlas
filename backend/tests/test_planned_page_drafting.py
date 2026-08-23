from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.seed import FLO_ZONE_COMPANY_NAME, seed_database
from app.db.session import create_db_and_tables, engine
from app.models import (
    Brand,
    Business,
    City,
    GeneratedPage,
    PlannedPage,
    PlanningRecord,
    Service,
    SitePlan,
    Website,
)
from app.schemas.site_plans import PlannedPageCreate
from app.schemas.entities import GeneratedPageCreate
from app.services.crud import create_record
from app.services.planned_page_drafting import (
    _INTERNAL_KNOWLEDGE_SENTENCE,
    _public_knowledge_text,
    _remove_internal_knowledge_sentence,
    PlannedPageDraftingError,
    draft_planned_page,
    evaluate_draft_readiness,
)
from app.services.public_destination_copy import (
    PublicDestinationCopyError,
    build_public_copy_reconciled_draft,
)
from app.services.site_planning import (
    create_planned_page,
    refresh_planning_record,
    update_planning_overrides,
)


@pytest.fixture(autouse=True)
def isolate_existing_drafting_contract_tests_from_predraft_gate(monkeypatch):
    """The authoritative gate has dedicated tests; this module tests draft rendering."""
    monkeypatch.setattr(
        "app.services.planned_page_drafting.require_effective_drafting_eligibility",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.draft_generation.require_effective_drafting_eligibility",
        lambda *args, **kwargs: None,
    )


def _seed() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        seed_database(session)


@pytest.fixture()
def drafting_scope():
    suffix = uuid4().hex[:10]
    yield suffix
    with Session(engine) as session:
        planned = list(
            session.exec(
                select(PlannedPage).where(
                    PlannedPage.intended_slug.like(f"draft-{suffix}-%")
                )
            ).all()
        )
        planned_ids = [item.id for item in planned if item.id is not None]
        generated_ids = [
            item.generated_page_id
            for item in planned
            if item.generated_page_id is not None
        ]
        if planned_ids:
            for record in session.exec(
                select(PlanningRecord).where(
                    PlanningRecord.planned_page_id.in_(planned_ids)
                )
            ).all():
                session.delete(record)
        for item in planned:
            session.delete(item)
        session.flush()
        if generated_ids:
            for generated in session.exec(
                select(GeneratedPage).where(GeneratedPage.id.in_(generated_ids))
            ).all():
                session.delete(generated)
        secondary = session.exec(
            select(Website).where(Website.domain == f"draft-{suffix}.example")
        ).first()
        if secondary:
            brand_id = secondary.brand_id
            for plan in session.exec(
                select(SitePlan).where(SitePlan.website_id == secondary.id)
            ).all():
                session.delete(plan)
            session.delete(secondary)
            session.flush()
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


def _planned(
    session: Session,
    *,
    website: Website,
    plan: SitePlan,
    suffix: str,
    page_type: str,
    service_id: int | None = None,
) -> PlannedPage:
    created = create_planned_page(
        session,
        PlannedPageCreate(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type=page_type,
            working_name=f"{page_type.replace('_', ' ').title()} Draft {suffix}",
            intended_slug=f"draft-{suffix}-{page_type}",
            service_id=service_id,
        ),
    )
    return session.get(PlannedPage, created.id)


@pytest.mark.parametrize(
    ("page_type", "expected_sections"),
    [
        ("home", {"primary_services", "trust", "service_area"}),
        ("about", {"company_story", "experience", "mission"}),
        ("contact", {"ways_to_contact", "hours", "service_area"}),
        ("service", {"service_overview", "approved_guidance", "service_area"}),
        ("informational", {"approved_information", "next_steps"}),
        ("faq", {"contact"}),
    ],
)
def test_core_page_types_create_common_reviewable_drafts(
    drafting_scope: str,
    page_type: str,
    expected_sections: set[str],
) -> None:
    _seed()
    with Session(engine) as session:
        _, website, service, plan = _flo(session)
        planned = _planned(
            session,
            website=website,
            plan=plan,
            suffix=f"{drafting_scope}-{page_type}",
            page_type=page_type,
            service_id=service.id if page_type == "service" else None,
        )
        readiness = evaluate_draft_readiness(session, planned)
        assert readiness.status == "ready", readiness.blocking_reasons

        generated, result = draft_planned_page(
            session,
            planned.id,
            expected_website_id=website.id,
        )
        session.refresh(planned)
        draft = generated.draft_content
        assert result.status == "ready"
        assert planned.generated_page_id == generated.id
        assert planned.planning_status == "drafted"
        assert generated.website_id == website.id
        assert generated.page_type == page_type
        assert generated.service_id == (service.id if page_type == "service" else None)
        assert draft["schema_version"] == "planned-page-draft-v1"
        assert draft["page_type"] == page_type
        assert draft["planning_record_id"]
        assert {section["key"] for section in draft["sections"]} == expected_sections
        assert generated.content_body.startswith(draft["intro"])
        if page_type == "about":
            company_story = next(
                section["body"]
                for section in draft["sections"]
                if section["key"] == "company_story"
            )
            assert draft["intro"] != company_story
            assert draft["intro"].startswith("Learn about Flo-Zone Tenting and its ")
            assert "service across Central Florida." in draft["intro"]
        if page_type == "faq":
            assert draft["faq_items"]


@pytest.mark.parametrize(
    ("page_type", "section_key"),
    (("contact", "ways_to_contact"), ("faq", "contact")),
)
def test_contact_sections_reconcile_exact_legacy_url_and_reject_custom_copy(
    drafting_scope: str,
    page_type: str,
    section_key: str,
) -> None:
    _seed()
    with Session(engine) as session:
        _, website, _, plan = _flo(session)
        planned = _planned(
            session,
            website=website,
            plan=plan,
            suffix=f"{drafting_scope}-{page_type}-contact-copy",
            page_type=page_type,
        )
        generated, _ = draft_planned_page(
            session,
            planned.id,
            expected_website_id=website.id,
        )
        current = deepcopy(generated.draft_content)
        section = next(
            item for item in current["sections"] if item["key"] == section_key
        )
        safe_contact = section["body"]
        section["body"] = f"{safe_contact} Website: {website.public_url}."

        reconciled = build_public_copy_reconciled_draft(
            session,
            planned,
            current,
        )
        reconciled_section = next(
            item
            for item in reconciled["sections"]
            if item["key"] == section_key
        )
        assert reconciled_section["body"] == safe_contact
        assert "Website:" not in reconciled_section["body"]

        custom = deepcopy(current)
        next(
            item for item in custom["sections"] if item["key"] == section_key
        )["body"] = "Operator-authored contact copy."
        with pytest.raises(
            PublicDestinationCopyError,
            match="neither the exact authorized before nor after value",
        ):
            build_public_copy_reconciled_draft(
                session,
                planned,
                custom,
            )


@pytest.mark.parametrize(
    ("page_type", "section_key"),
    [
        ("service", "approved_guidance"),
        ("county", "customer_expectations"),
        ("county", "customer_expectations"),
        ("county", "customer_expectations"),
        ("county", "customer_expectations"),
        ("county", "customer_expectations"),
    ],
    ids=[
        "service",
        "county-1",
        "county-2",
        "county-3",
        "county-4",
        "county-5",
    ],
)
def test_all_technical_page_candidates_omit_internal_sentence_without_orphan_space(
    page_type: str,
    section_key: str,
) -> None:
    before = (
        "### What Tenting Targets\n"
        "Structural fumigation targets active infestations inside the structure "
        f"at the time of treatment. {_INTERNAL_KNOWLEDGE_SENTENCE}\n\n"
        "### Limits of Tenting\n"
        "Preserved technical guidance."
    )
    expected = (
        "### What Tenting Targets\n"
        "Structural fumigation targets active infestations inside the structure "
        "at the time of treatment.\n\n"
        "### Limits of Tenting\n"
        "Preserved technical guidance."
    )
    draft = {
        "page_type": page_type,
        "sections": [
            {
                "key": section_key,
                "heading": "What Customers Should Know",
                "body": before,
            }
        ],
    }

    _remove_internal_knowledge_sentence(draft, section_key)

    assert draft["sections"][0]["body"] == expected
    assert _public_knowledge_text(before) == expected
    assert "treatment. \n\n" not in draft["sections"][0]["body"]


def test_technical_candidate_rejects_duplicate_internal_sentence() -> None:
    draft = {
        "sections": [
            {
                "key": "approved_guidance",
                "heading": "What Customers Should Know",
                "body": (
                    f"Public technical sentence. {_INTERNAL_KNOWLEDGE_SENTENCE}\n\n"
                    f"Repeated instruction. {_INTERNAL_KNOWLEDGE_SENTENCE}"
                ),
            }
        ]
    }

    with pytest.raises(
        PublicDestinationCopyError,
        match="contains the internal sentence more than once",
    ):
        _remove_internal_knowledge_sentence(draft, "approved_guidance")


def test_refresh_uses_effective_planning_record_and_preserves_override(
    drafting_scope: str,
) -> None:
    _seed()
    with Session(engine) as session:
        _, website, _, plan = _flo(session)
        planned = _planned(
            session,
            website=website,
            plan=plan,
            suffix=drafting_scope,
            page_type="informational",
        )
        override = "Explain approved termite information for property owners."
        update_planning_overrides(session, planned.id, {"purpose": override})
        refresh_planning_record(session, planned.id)
        generated, _ = draft_planned_page(
            session,
            planned.id,
            expected_website_id=website.id,
        )
        assert generated.draft_content["intro"] == (
            f"Learn more about {planned.working_name}."
        )
        assert generated.draft_content["operator_override_keys"] == ["purpose"]

        refreshed, _ = draft_planned_page(
            session,
            planned.id,
            expected_website_id=website.id,
            allow_overwrite=True,
        )
        record = session.exec(
            select(PlanningRecord).where(PlanningRecord.planned_page_id == planned.id)
        ).one()
        assert refreshed.id == generated.id
        assert record.operator_overrides == {"purpose": override}
        assert refreshed.draft_content["intro"] == (
            f"Learn more about {planned.working_name}."
        )


def test_readiness_blocks_absent_required_approved_information(
    drafting_scope: str,
) -> None:
    _seed()
    with Session(engine) as session:
        business = Business(
            company_name=f"Draft Readiness {drafting_scope}",
            business_type="Test business",
            state="",
        )
        session.add(business)
        session.flush()
        brand = Brand(
            business_id=business.id,
            brand_name=f"Draft Brand {drafting_scope}",
            status="active",
        )
        session.add(brand)
        session.flush()
        website = Website(
            business_id=business.id,
            brand_id=brand.id,
            website_name=f"Draft Website {drafting_scope}",
            domain=f"draft-{drafting_scope}.example",
            public_url=f"https://draft-{drafting_scope}.example",
            status="active",
        )
        session.add(website)
        session.flush()
        plan = SitePlan(
            website_id=website.id,
            plan_key="primary",
            plan_name="Readiness Test",
        )
        session.add(plan)
        session.commit()
        planned = _planned(
            session,
            website=website,
            plan=plan,
            suffix=drafting_scope,
            page_type="home",
        )
        readiness = evaluate_draft_readiness(session, planned)
        assert readiness.status == "blocked"
        keys = {
            item["key"]
            for item in readiness.required_information
            if not item["available"]
        }
        assert {"primary_services", "primary_service_area", "primary_call_to_action"} <= keys
        with pytest.raises(PlannedPageDraftingError, match="not ready to draft"):
            draft_planned_page(
                session,
                planned.id,
                expected_website_id=website.id,
            )
        assert planned.generated_page_id is None


def test_cross_website_drafting_fails_closed(drafting_scope: str) -> None:
    _seed()
    with Session(engine) as session:
        business, website, _, plan = _flo(session)
        brand = Brand(
            business_id=business.id,
            brand_name=f"Secondary {drafting_scope}",
            status="active",
        )
        session.add(brand)
        session.flush()
        secondary = Website(
            business_id=business.id,
            brand_id=brand.id,
            website_name=f"Secondary {drafting_scope}",
            domain=f"draft-{drafting_scope}.example",
            public_url=f"https://draft-{drafting_scope}.example",
            status="active",
        )
        session.add(secondary)
        session.commit()
        planned = _planned(
            session,
            website=website,
            plan=plan,
            suffix=drafting_scope,
            page_type="about",
        )
        with pytest.raises(PlannedPageDraftingError, match="does not belong"):
            draft_planned_page(
                session,
                planned.id,
                expected_website_id=secondary.id,
            )
        assert planned.generated_page_id is None


def test_generic_generated_page_creation_cannot_bypass_planned_page_authority() -> None:
    _seed()
    with Session(engine) as session:
        _, website, service, _ = _flo(session)
        with pytest.raises(HTTPException, match="must originate"):
            create_record(
                session,
                GeneratedPage,
                GeneratedPageCreate(
                    business_id=website.business_id,
                    website_id=website.id,
                    service_id=service.id,
                    page_type="service",
                    page_title="Bypass attempt",
                    page_slug=f"bypass-{uuid4().hex[:8]}",
                ),
            )


def test_city_service_compatibility_adapter_preserves_legacy_contract() -> None:
    _seed()
    with Session(engine) as session:
        _, website, _, _ = _flo(session)
        generated = session.exec(
            select(GeneratedPage).where(
                GeneratedPage.website_id == website.id,
                GeneratedPage.page_type == "city_service",
                GeneratedPage.generation_status == "not_generated",
            )
        ).first()
        assert generated
        planned = session.exec(
            select(PlannedPage).where(PlannedPage.generated_page_id == generated.id)
        ).one()
        result, readiness = draft_planned_page(
            session,
            planned.id,
            expected_website_id=website.id,
        )
        assert readiness.status == "ready"
        assert result.id == generated.id
        assert result.service_id is not None
        assert "why_it_matters" in result.draft_content
        assert "schema_version" not in result.draft_content


def test_standalone_city_drafting_remains_fail_closed(
    drafting_scope: str,
) -> None:
    _seed()
    with Session(engine) as session:
        _, website, _, plan = _flo(session)
        generated = session.exec(
            select(GeneratedPage).where(GeneratedPage.website_id == website.id)
        ).first()
        assert generated and generated.county_id
        city = session.exec(
            select(City).where(City.county_id == generated.county_id)
        ).first()
        assert city
        created = create_planned_page(
            session,
            PlannedPageCreate(
                website_id=website.id,
                site_plan_id=plan.id,
                page_type="city",
                working_name=f"City Draft {drafting_scope}",
                intended_slug=f"draft-{drafting_scope}-city",
                city_id=city.id,
                county_id=generated.county_id,
            ),
        )
        planned = session.get(PlannedPage, created.id)
        readiness = evaluate_draft_readiness(session, planned)
        assert readiness.status == "unsupported"
        with pytest.raises(PlannedPageDraftingError, match="not ready to draft"):
            draft_planned_page(
                session,
                planned.id,
                expected_website_id=website.id,
            )


def test_drafting_foundation_contains_no_production_transport() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app/services/planned_page_drafting.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "requests." not in lowered
    assert "httpx." not in lowered
    assert "siteground" not in lowered
    assert "/wp-json/" not in lowered
