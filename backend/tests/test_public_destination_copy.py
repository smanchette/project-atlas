from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Brand,
    Business,
    City,
    County,
    GeneratedPage,
    InternalLinkIntent,
    PlannedPage,
    Service,
    SitePlan,
    Website,
    WebsiteIdentity,
)
from app.services.public_destination_copy import (
    PUBLIC_COPY_RULESET_HASH,
    PUBLIC_COPY_RULESET_KEY,
    PUBLIC_COPY_RULESET_VERSION,
    PublicDestinationCopyError,
    build_public_destination_copy,
    require_public_destination_copy,
)


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _scope(session: Session):
    business = Business(
        company_name="Destination Company",
        business_type="Test business",
        state="FL",
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id,
        brand_name="Destination Brand",
        status="active",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name="Destination Website",
        domain="destination.example.test",
        public_url="https://destination.example.test",
        configuration={
            "state_name": "Florida",
            "market_state_codes": ["FL"],
        },
        status="active",
    )
    session.add(website)
    session.flush()
    session.add(
        WebsiteIdentity(
            website_id=website.id,
            display_name="Destination Brand",
            status="active",
        )
    )
    service = Service(
        business_id=business.id,
        service_name="Termite Tenting",
        service_slug="destination-termite-tenting",
        status="active",
    )
    county = County(county_name="Orange County", state="FL", status="active")
    session.add_all([service, county])
    session.flush()
    city = City(
        county_id=county.id,
        city_name="Orlando",
        city_slug="destination-orlando",
        state="FL",
        status="active",
    )
    session.add(city)
    session.flush()
    plan = SitePlan(
        website_id=website.id,
        plan_key="primary",
        plan_name="Primary Site Plan",
    )
    session.add(plan)
    session.flush()

    source_generated = GeneratedPage(
        business_id=business.id,
        website_id=website.id,
        service_id=service.id,
        page_type="service",
        page_title="Termite Tenting",
        page_slug="termite-tenting",
        draft_content={"related_pages": []},
        generation_status="generated",
    )
    session.add(source_generated)
    session.flush()
    source = PlannedPage(
        website_id=website.id,
        site_plan_id=plan.id,
        page_type="service",
        working_name="Termite Tenting",
        intended_slug="termite-tenting",
        service_id=service.id,
        generated_page_id=source_generated.id,
    )
    session.add(source)
    session.flush()

    target_specs = (
        ("home", "Home", "home", None, None, None),
        ("about", "About", "about", None, None, None),
        ("contact", "Contact", "contact", None, None, None),
        ("faq", "Frequently Asked Questions", "faq", None, None, None),
        (
            "service",
            "Termite Tenting",
            "termite-tenting-details",
            service.id,
            None,
            None,
        ),
        (
            "county",
            "Termite Tenting in Orange County",
            "termite-tenting-orange-county",
            service.id,
            None,
            county.id,
        ),
        (
            "city_service",
            "Termite Tenting in Orlando",
            "termite-tenting-orlando",
            service.id,
            city.id,
            county.id,
        ),
    )
    targets: list[PlannedPage] = []
    decided_at = datetime(2026, 8, 20, tzinfo=UTC)
    for page_type, name, slug, service_id, city_id, county_id in target_specs:
        generated = GeneratedPage(
            business_id=business.id,
            website_id=website.id,
            service_id=service_id,
            city_id=city_id,
            county_id=county_id,
            page_type=page_type,
            page_title=name,
            page_slug=slug,
            draft_content={},
            generation_status="generated",
        )
        session.add(generated)
        session.flush()
        target = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type=page_type,
            working_name=name,
            intended_slug=slug,
            service_id=service_id,
            city_id=city_id,
            county_id=county_id,
            generated_page_id=generated.id,
        )
        session.add(target)
        session.flush()
        session.add(
            InternalLinkIntent(
                website_id=website.id,
                site_plan_id=plan.id,
                source_planned_page_id=source.id,
                target_planned_page_id=target.id,
                purpose=f"Operator-only purpose for {page_type}.",
                relationship_type="supporting_information",
                approval_state="approved",
                rationale=f"Approve the exact {page_type} destination.",
                decided_by="Destination Operator",
                decision_version=1,
                decided_at=decided_at,
            )
        )
        targets.append(target)
    session.flush()
    return plan, source, source_generated, targets


def test_projection_is_deterministic_typed_and_preserves_operator_purpose():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        plan, source, generated, _ = _scope(session)
        original_purposes = [
            item.purpose
            for item in session.exec(
                select(InternalLinkIntent).order_by(InternalLinkIntent.id)
            ).all()
        ]

        projection = build_public_destination_copy(
            session,
            plan,
            source,
            generated,
        )

        assert [item.description for item in projection] == [
            "Return to the Destination Brand home page.",
            "Learn more about Destination Brand.",
            "Contact Destination Brand.",
            "Read answers to common questions about Termite Tenting.",
            "View information about Termite Tenting.",
            "Explore Termite Tenting service throughout Orange County.",
            "View Termite Tenting information for Orlando, Florida.",
        ]
        assert all(item.target_generated_page_id > 0 for item in projection)
        assert all(item.ruleset_key == PUBLIC_COPY_RULESET_KEY for item in projection)
        assert all(
            item.ruleset_version == PUBLIC_COPY_RULESET_VERSION
            for item in projection
        )
        assert all(item.ruleset_hash == PUBLIC_COPY_RULESET_HASH for item in projection)
        assert [
            item.purpose
            for item in session.exec(
                select(InternalLinkIntent).order_by(InternalLinkIntent.id)
            ).all()
        ] == original_purposes


def test_revision_projection_rejects_missing_tampered_and_reordered_values():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        plan, source, generated, _ = _scope(session)
        projection = build_public_destination_copy(session, plan, source, generated)
        payload = [item.model_dump(mode="json") for item in projection]

        generated.draft_content = {
            "related_pages": [],
            "public_destination_copy": payload,
        }
        assert require_public_destination_copy(
            session, plan, source, generated
        ) == projection

        generated.draft_content["public_destination_copy"] = []
        with pytest.raises(PublicDestinationCopyError, match="missing, stale"):
            require_public_destination_copy(session, plan, source, generated)

        tampered = [dict(item) for item in payload]
        tampered[0]["ruleset_hash"] = "0" * 64
        generated.draft_content["public_destination_copy"] = tampered
        with pytest.raises(PublicDestinationCopyError, match="missing, stale"):
            require_public_destination_copy(session, plan, source, generated)

        generated.draft_content["public_destination_copy"] = list(reversed(payload))
        with pytest.raises(PublicDestinationCopyError, match="reordered"):
            require_public_destination_copy(session, plan, source, generated)


def test_target_requires_nonnull_generated_identity():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        plan, source, generated, targets = _scope(session)
        targets[0].generated_page_id = None
        session.add(targets[0])
        session.flush()

        with pytest.raises(
            PublicDestinationCopyError,
            match="lacks an exact Generated Page identity",
        ):
            build_public_destination_copy(session, plan, source, generated)


def test_draft_related_target_also_requires_exact_generated_identity():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        plan, source, generated, targets = _scope(session)
        for intent in session.exec(select(InternalLinkIntent)).all():
            session.delete(intent)
        generated.draft_content = {
            "related_pages": [
                {
                    "label": targets[0].working_name,
                    "slug": targets[0].intended_slug,
                }
            ]
        }
        targets[0].generated_page_id = None
        session.add_all([generated, targets[0]])
        session.flush()

        with pytest.raises(
            PublicDestinationCopyError,
            match="lacks an exact Generated Page identity",
        ):
            build_public_destination_copy(session, plan, source, generated)


@pytest.mark.parametrize("mismatch", ["page_type", "page_slug"])
def test_target_rejects_generated_page_type_or_slug_divergence(mismatch: str):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        plan, source, generated, targets = _scope(session)
        target_generated = session.get(GeneratedPage, targets[0].generated_page_id)
        assert target_generated is not None
        if mismatch == "page_type":
            target_generated.page_type = "about"
        else:
            target_generated.page_slug = "tampered-home"
        session.add(target_generated)
        session.flush()

        with pytest.raises(
            PublicDestinationCopyError,
            match="crosses or diverges from its exact Website, page-type, slug",
        ):
            build_public_destination_copy(session, plan, source, generated)
