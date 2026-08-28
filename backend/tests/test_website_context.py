from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from app.db.session import engine
from app.main import app
from app.models import (
    Brand,
    Business,
    City,
    County,
    GeneratedPage,
    KnowledgeBlock,
    Service,
    Website,
    WebsiteIdentity,
)
from app.services.draft_generation import (
    assemble_generation_prompt,
    build_automatic_public_call_to_action,
    generate_page_draft,
    load_generation_context,
)
from app.services.page_export import build_page_export_package
from app.services.page_queue import build_city_service_page_payload, create_city_service_page_queue
from app.services.website_context import build_website_context


@pytest.fixture(autouse=True)
def isolate_context_tests_from_predraft_gate(monkeypatch):
    monkeypatch.setattr(
        "app.services.draft_generation.require_effective_drafting_eligibility",
        lambda *args, **kwargs: None,
    )


def test_seeded_flo_zone_has_first_class_website_context() -> None:
    with TestClient(app) as client:
        businesses = client.get("/api/businesses").json()
        business_id = next(
            item["id"]
            for item in businesses
            if item["company_name"] == "Flo-Zone Pest And Termite Solutions Inc"
        )
        websites = client.get("/api/websites").json()
        website = next(item for item in websites if item["business_id"] == business_id)
        response = client.get(f"/api/websites/{website['id']}/context")

    assert response.status_code == 200
    context = response.json()
    assert context["business"]["company_name"] == "Flo-Zone Pest And Termite Solutions Inc"
    assert context["brand"]["public_name"] == "Flo-Zone"
    assert context["website"]["public_url"] == "https://www.Flo-ZoneTenting.com"
    assert context["website"]["legacy_fallback"] is False
    assert context["identity"]["display_name"] == "Flo-Zone Tenting"


def test_brand_website_and_identity_can_be_entered_and_managed_through_api() -> None:
    suffix = uuid4().hex[:8]
    with TestClient(app) as client:
        business = client.post(
            "/api/businesses",
            json={
                "company_name": f"Website Setup Company {suffix}",
                "business_type": "Fictional test company",
                "state": "EX",
            },
        ).json()
        brand = client.post(
            "/api/brands",
            json={
                "business_id": business["id"],
                "brand_name": f"Website Setup Brand {suffix}",
                "tagline": "A fictional identity",
            },
        ).json()
        website = client.post(
            "/api/websites",
            json={
                "business_id": business["id"],
                "brand_id": brand["id"],
                "website_name": f"Website Setup {suffix}",
                "domain": f"{suffix}.setup.example",
                "public_url": f"https://{suffix}.setup.example",
                "locale": "en-US",
                "primary_language": "en",
            },
        ).json()
        identity_response = client.post(
            "/api/website-identities",
            json={
                "website_id": website["id"],
                "display_name": f"Website Setup {suffix}",
                "favicon_url": f"https://{suffix}.setup.example/favicon.ico",
                "browser_icon_url": f"https://{suffix}.setup.example/icon.png",
                "apple_touch_icon_url": f"https://{suffix}.setup.example/apple-touch.png",
                "social_identity_image_url": f"https://{suffix}.setup.example/social.png",
                "status": "draft",
            },
        )
        assert identity_response.status_code == 201
        identity = identity_response.json()
        context = client.get(f"/api/websites/{website['id']}/context").json()
        assert context["identity"]["favicon_url"].endswith("/favicon.ico")
        assert context["brand"]["public_name"] == brand["brand_name"]

        assert client.delete(f"/api/website-identities/{identity['id']}").status_code == 200
        assert client.delete(f"/api/websites/{website['id']}").status_code == 200
        assert client.delete(f"/api/brands/{brand['id']}").status_code == 200
        assert client.delete(f"/api/businesses/{business['id']}").status_code == 200


def test_fictional_company_isolated_across_queue_generation_export_and_context() -> None:
    suffix = uuid4().hex[:8]
    forbidden = (
        "flo-zone",
        "drywood",
        "termite",
        "florida",
        "orlando",
        "flo-zonetenting.com",
    )
    isolated_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(isolated_engine)
    with Session(isolated_engine) as session:
            business = Business(
                company_name=f"Northstar Home Services {suffix}",
                brand_name=f"Northstar {suffix}",
                business_type="Exterior home care",
                phone="(555) 010-2020",
                email=f"hello-{suffix}@northstar.example",
                website=f"https://{suffix}.northstar.example",
                main_city="Exampleville",
                state="EX",
                license_number="EX-100",
                certified_operator="Casey Example",
                description="A fictional test-only exterior home-care company.",
            )
            session.add(business)
            session.commit()
            session.refresh(business)
            brand = Brand(
                business_id=business.id,
                brand_name=f"Northstar {suffix}",
                tagline="Clear care for every exterior",
                identity_settings={"brand_mark": "NS"},
                status="active",
            )
            session.add(brand)
            session.commit()
            session.refresh(brand)
            website = Website(
                business_id=business.id,
                brand_id=brand.id,
                website_name=f"Northstar Example {suffix}",
                domain=f"{suffix}.northstar.example",
                public_url=f"https://{suffix}.northstar.example",
                locale="en-US",
                primary_language="en",
                configuration={
                    "short_brand_name": f"Northstar {suffix}",
                    "state_name": "Example State",
                    "state_slug": "ex",
                    "license_label": "Example License",
                    "content_heading_contact": f"Contact Northstar {suffix}",
                    "market_state_codes": ["EX"],
                    "target_customer_types": ["homeowners", "property managers"],
                },
                status="active",
            )
            session.add(website)
            session.commit()
            session.refresh(website)
            identity = WebsiteIdentity(
                website_id=website.id,
                display_name=f"Northstar Example {suffix}",
                favicon_url=f"https://{suffix}.northstar.example/favicon.ico",
                browser_icon_url=f"https://{suffix}.northstar.example/icon-32.png",
                apple_touch_icon_url=f"https://{suffix}.northstar.example/apple-touch.png",
                social_identity_image_url=f"https://{suffix}.northstar.example/social.png",
                status="active",
            )
            county = County(state="EX", county_name=f"Example County {suffix}", status="active")
            session.add(identity)
            session.add(county)
            session.commit()
            session.refresh(county)
            city = City(
                county_id=county.id,
                city_name=f"Exampleville {suffix}",
                state="EX",
                city_slug=f"exampleville-{suffix}",
                status="active",
            )
            service = Service(
                business_id=business.id,
                service_name="Exterior Home Care",
                service_slug=f"exterior-home-care-{suffix}",
                short_description="A fictional exterior home-care service.",
                status="active",
            )
            session.add(city)
            session.add(service)
            session.commit()
            session.refresh(city)
            session.refresh(service)
            context = build_website_context(
                session,
                business_id=business.id,
                website_id=website.id,
            )
            payload = build_city_service_page_payload(business, service, city, context)
            created = create_city_service_page_queue(
                session,
                business_company_name=business.company_name,
                service_slug=service.service_slug,
                website_id=website.id,
            )
            page = session.exec(
                select(GeneratedPage).where(
                    GeneratedPage.business_id == business.id,
                    GeneratedPage.website_id == website.id,
                )
            ).one()
            session.add(
                KnowledgeBlock(
                    business_id=business.id,
                    service_id=service.id,
                    title="Service planning",
                    slug=f"service-planning-{suffix}",
                    question="How is service planned?",
                    short_answer="The service is planned after an assessment.",
                    long_answer="The service is planned after an assessment and review of the approved scope.",
                    category="service_basics",
                    confidence_level="high",
                    sort_order=1,
                    status="active",
                )
            )
            session.commit()

            generation_context = load_generation_context(session, page.id)
            generated = generate_page_draft(session, page.id)
            package = build_page_export_package(session, page.id)

            expected_public_cta = (
                f"To discuss exterior home care in {city.city_name}, contact {business.company_name} "
                f"at {business.phone} or {business.email}."
            )
            assert generated.draft_content["call_to_action"] == expected_public_cta
            assert "EX-100" not in generated.draft_content["call_to_action"]
            assert "Casey Example" not in generated.draft_content["call_to_action"]
            assert "Example License" not in generated.draft_content["call_to_action"]
            assert "certified operator" not in generated.draft_content["call_to_action"].lower()
            assert "information available on request" not in generated.draft_content["call_to_action"]
            assert generation_context.business.license_number == "EX-100"
            assert generation_context.business.certified_operator == "Casey Example"
            prompt = assemble_generation_prompt(generation_context)
            assert "License: EX-100" in prompt
            assert "Certified operator: Casey Example" in prompt

            generation_context.business.phone = "(555) 010-2020"
            generation_context.business.email = None
            generation_context.website_context.website.public_url = ""
            assert build_automatic_public_call_to_action(generation_context).endswith(
                "at (555) 010-2020."
            )
            generation_context.business.phone = None
            generation_context.business.email = f"hello-{suffix}@northstar.example"
            assert build_automatic_public_call_to_action(generation_context).endswith(
                f"at hello-{suffix}@northstar.example."
            )
            generation_context.business.email = None
            generation_context.website_context.website.public_url = (
                f"https://{suffix}.northstar.example"
            )
            assert build_automatic_public_call_to_action(generation_context).endswith(
                f"through https://{suffix}.northstar.example."
            )
            generation_context.website_context.website.public_url = ""
            no_contact_cta = build_automatic_public_call_to_action(generation_context)
            assert no_contact_cta == (
                f"To discuss exterior home care in {city.city_name}, contact {business.company_name}."
            )
            assert "the office" not in no_contact_cta
            assert "company website" not in no_contact_cta
            assert " or " not in no_contact_cta

            combined = json.dumps(
                {
                    "context": context.model_dump(mode="json"),
                    "payload": payload,
                    "draft": generated.draft_content,
                    "export": package.model_dump(mode="json"),
                },
                sort_keys=True,
            ).lower()
            assert generation_context.website_context.website.id == website.id
            assert created == 1
            assert generated.website_id == website.id
            assert package.website == website.public_url
            assert package.canonical_url_preview.startswith(f"{website.public_url}/")
            assert f"northstar {suffix}" in combined
            assert "example state" in combined
            assert not any(value in combined for value in forbidden)


def test_website_context_rejects_cross_business_website_binding() -> None:
    isolated_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(isolated_engine)
    with Session(isolated_engine) as session:
            flo_zone = Business(
                company_name="Flo-Zone Pest And Termite Solutions Inc",
                business_type="Reference",
                state="FL",
            )
            foreign = Business(
                company_name=f"Foreign Context {uuid4().hex}",
                business_type="Fictional",
                state="EX",
            )
            session.add(flo_zone)
            session.add(foreign)
            session.commit()
            session.refresh(flo_zone)
            session.refresh(foreign)
            website = Website(
                business_id=flo_zone.id,
                website_name="Reference",
                domain="reference.example",
                public_url="https://reference.example",
                status="active",
            )
            session.add(website)
            session.commit()
            session.refresh(website)

            try:
                build_website_context(
                    session,
                    business_id=foreign.id,
                    website_id=website.id,
                )
            except ValueError as exc:
                assert "does not belong" in str(exc)
            else:
                raise AssertionError("Cross-business website binding was accepted")
