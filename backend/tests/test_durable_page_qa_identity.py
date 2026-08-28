from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    ApprovalAudit,
    Business,
    City,
    County,
    GeneratedPage,
    GeneratedPageQAResult,
    GeneratedPageRevision,
    ImageMetadata,
    PageComposition,
    PageCompositionRevision,
    PageImageAssignment,
    PlannedPage,
    Service,
    SitePlan,
    Website,
    WordPressDraftAudit,
)
from app.schemas.entities import GeneratedPageUpdate
from app.schemas.qa import QACheckItem
from app.services import page_qa as page_qa_service
from app.services.page_qa import (
    _record_as_result,
    authoritative_page_qa_state,
    effective_page_qa_state,
    generated_page_with_effective_qa,
    get_page_qa,
    historical_qa_payload_hash,
    qa_result_record_hash,
    reconcile_page_qa,
    resolve_qa_composition_revision,
    save_page_qa,
)
from app.services.page_type_review import CITY_SERVICE_CONTRACT, PLANNED_PAGE_CONTRACTS
from app.services.page_composition_history import (
    advance_composition_revision,
    canonical_payload_hash,
    create_initial_composition_revision,
    current_composition_revision,
)
from app.services.approval_audit import approve_page_with_audit
from app.services.approval_queue import build_approval_queue
from app.services.page_export import build_page_export_package
from app.services.website_readiness import evaluate_website_readiness
from app.services.wordpress_drafts import dry_run_wordpress_draft


EXPECTED_NON_CITY_RULESET_HASHES = {
    "about": "8209af7b1cb695805fdbbb64b33c57a8ea09656f4e42e665ec42c1d9bd334d11",
    "contact": "0d16343c42f630e388961b188c8f611a5b122e2e734cba947883203aee66f79e",
    "county": "9feb447a6ce0f63240362f6013044958a6bb8ac32c4d00c7b273bd585b366341",
    "faq": "6208c14ed7a3f07a06b2bce1a0eec4d3ccf071d5b9a64641d8e58901fd34db83",
    "home": "8d4253d1c2127f9367ca7d487208c5a428f0f37eda1e51c96859e5fbb98e7bf3",
    "informational": "ea187e65c4b408595c5770527e6fa6f9269a02d13fbbeaca9e253adde715d11f",
    "service": "bd70184abb78dcd6f6dc80e2c596816c2c8078ae2e8629def3991b657529d67b",
}
EXPECTED_NON_CITY_RULESET_AGGREGATE = (
    "a221abe857021477e3774e05b7d4c0c97206a19a9ad63738487e333f615892a4"
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_city_service_public_cta_policy_changes_only_city_ruleset_identity() -> None:
    def legacy_ruleset_hash(contract) -> str:
        return page_qa_service._canonical_hash(
            {
                "algorithm_key": page_qa_service.PAGE_QA_ALGORITHM_KEY,
                "algorithm_version": page_qa_service.PAGE_QA_ALGORITHM_VERSION,
                "ruleset_key": page_qa_service.PAGE_QA_RULESET_KEY,
                "ruleset_version": page_qa_service.PAGE_QA_RULESET_VERSION,
                "contract": page_qa_service.asdict(contract),
                "forbidden_phrases": sorted(page_qa_service.FORBIDDEN_PHRASES),
                "placeholder_patterns": list(page_qa_service.PLACEHOLDER_PATTERNS),
                "check_remediation": page_qa_service.CHECK_REMEDIATION,
            }
        )

    non_city_hashes = {
        page_type: page_qa_service._qa_ruleset_hash(contract)
        for page_type, contract in sorted(PLANNED_PAGE_CONTRACTS.items())
    }
    assert non_city_hashes == EXPECTED_NON_CITY_RULESET_HASHES
    assert (
        page_qa_service._canonical_hash(non_city_hashes)
        == EXPECTED_NON_CITY_RULESET_AGGREGATE
    )
    for page_type, contract in PLANNED_PAGE_CONTRACTS.items():
        assert legacy_ruleset_hash(contract) == EXPECTED_NON_CITY_RULESET_HASHES[
            page_type
        ]

    legacy_city_hash = legacy_ruleset_hash(CITY_SERVICE_CONTRACT)
    assert (
        legacy_city_hash
        == page_qa_service.LEGACY_CITY_SERVICE_QA_RULESET_HASH
    )
    assert page_qa_service._qa_ruleset_hash(CITY_SERVICE_CONTRACT) != legacy_city_hash


@pytest.fixture(autouse=True)
def synthetic_composition_reader(monkeypatch: pytest.MonkeyPatch):
    """Keep unit scopes small while real composition drift is integration-tested."""

    original = page_qa_service.read_composition_for_generated_page

    def read(session: Session, generated_page_id: int):
        composition = session.exec(
            select(PageComposition).where(
                PageComposition.generated_page_id == generated_page_id
            )
        ).first()
        if composition and "fixture" in (composition.source_snapshot or {}):
            return SimpleNamespace(id=composition.id)
        return original(session, generated_page_id)

    monkeypatch.setattr(page_qa_service, "read_composition_for_generated_page", read)


def _scope(
    session: Session,
    *,
    suffix: str | None = None,
    generated_page_id: int | None = None,
) -> tuple[Business, Website, SitePlan, PlannedPage, GeneratedPage, PageComposition]:
    suffix = suffix or uuid4().hex[:8]
    business = Business(
        company_name=f"QA Business {suffix}",
        brand_name=f"QA Brand {suffix}",
        business_type="Local service business",
        phone="407-555-0100",
        state="FL",
    )
    session.add(business)
    session.flush()
    website = Website(
        business_id=business.id,
        website_name=f"QA Website {suffix}",
        domain=f"qa-{suffix}.example.test",
        public_url=f"https://qa-{suffix}.example.test",
        status="active",
    )
    session.add(website)
    session.flush()
    plan = SitePlan(
        website_id=website.id,
        plan_key="primary",
        plan_name="Primary Site Plan",
        status="active",
    )
    session.add(plan)
    session.flush()
    title = f"Approved Information {suffix}"
    draft = {
        "schema_version": "planned-page-draft-v1",
        "page_type": "informational",
        "title": title,
        "meta_title": title,
        "meta_description": "Approved information for local customers.",
        "h1": title,
        "intro": "This page explains approved information for local customers.",
        "sections": [
            {
                "key": "approved_information",
                "heading": "Approved information",
                "body": "This information comes from approved business records.",
            },
            {
                "key": "next_steps",
                "heading": "Next steps",
                "body": "Call 407-555-0100 to speak with the business.",
            },
        ],
        "faq_items": [],
        "image_placements": [],
        "related_pages": [],
        "call_to_action": "Call 407-555-0100 for approved next steps.",
        "status": "draft",
    }
    page = GeneratedPage(
        id=generated_page_id,
        business_id=business.id,
        website_id=website.id,
        page_type="informational",
        page_title=title,
        page_slug=f"approved-information-{suffix}",
        meta_title=title,
        meta_description="Approved information for local customers.",
        h1=title,
        draft_content=draft,
        generation_status="generated",
        status="draft",
    )
    session.add(page)
    session.flush()
    planned = PlannedPage(
        website_id=website.id,
        site_plan_id=plan.id,
        page_type="informational",
        working_name=title,
        intended_slug=page.page_slug,
        generated_page_id=page.id,
        planning_status="planned",
    )
    session.add(planned)
    session.flush()
    composition_snapshot = {
        "fixture": suffix,
        "draft_hash": page_qa_service._content_hash(page),
    }
    composition = PageComposition(
        website_id=website.id,
        site_plan_id=plan.id,
        planned_page_id=planned.id,
        generated_page_id=page.id,
        composition_version=1,
        generated_components=[],
        operator_decisions=[],
        source_snapshot=composition_snapshot,
        source_hash=canonical_payload_hash(composition_snapshot),
        status="current",
    )
    session.add(composition)
    session.flush()
    create_initial_composition_revision(
        session,
        composition,
        recorded_by="test:durable-page-qa-identity",
        record_source="test_fixture",
    )
    session.commit()
    return business, website, plan, planned, page, composition


def _city_service_scope(
    session: Session,
    *,
    suffix: str,
) -> tuple[Business, Website, SitePlan, PlannedPage, GeneratedPage, PageComposition]:
    business, website, plan, planned, page, composition = _scope(
        session,
        suffix=suffix,
    )
    business.email = f"public-{suffix}@example.test"
    business.license_number = f"SYNTHETIC-LICENSE-{suffix}"
    business.certified_operator = f"Synthetic Operator {suffix}"
    service = Service(
        business_id=business.id,
        service_name=f"Synthetic Property Care {suffix}",
        service_slug=f"synthetic-property-care-{suffix}",
    )
    county = County(county_name=f"Synthetic County {suffix}", state="FL")
    session.add(service)
    session.add(county)
    session.flush()
    city = City(
        county_id=county.id,
        city_name=f"Example City {suffix}",
        city_slug=f"example-city-{suffix}",
        state="FL",
    )
    session.add(city)
    session.flush()

    title = f"Synthetic Property Care in Example City {suffix}"
    legacy_cta = (
        f"To discuss {service.service_name.lower()} in {city.city_name}, contact "
        f"{business.company_name} at {business.phone} or {business.email}. "
        f"Florida license {business.license_number}; certified operator "
        f"{business.certified_operator}."
    )
    page.page_type = "city_service"
    page.service_id = service.id
    page.city_id = city.id
    page.county_id = county.id
    page.page_title = title
    page.meta_title = title
    page.meta_description = "Synthetic City-Service QA fixture."
    page.h1 = title
    page.draft_content = {
        "title": title,
        "meta_title": title,
        "meta_description": page.meta_description,
        "h1": title,
        "intro": f"Synthetic introduction for {service.service_name} in {city.city_name}.",
        "why_it_matters": "Synthetic why-it-matters content.",
        "signs_section": "Synthetic signs content.",
        "process_section": "Synthetic process content.",
        "prep_section": "Synthetic preparation content.",
        "realtor_property_manager_section": "Synthetic coordination content.",
        "faq_items": [
            {
                "question": "What is the synthetic service process?",
                "answer": "The synthetic service follows reviewed preparation steps.",
            }
        ],
        "call_to_action": legacy_cta,
        "internal_notes": (
            f"Internal credentials: {business.license_number}; "
            f"{business.certified_operator}."
        ),
        "status": "draft",
    }
    planned.page_type = "city_service"
    planned.service_id = service.id
    planned.city_id = city.id
    planned.county_id = county.id
    planned.working_name = title
    session.add(business)
    session.add(page)
    session.add(planned)
    snapshot = deepcopy(composition.source_snapshot)
    snapshot["draft_hash"] = page_qa_service._content_hash(page)
    snapshot["fixture_revision"] = "city_service"
    now = datetime.now(UTC)
    advance_composition_revision(
        session,
        composition,
        generated_components=composition.generated_components,
        operator_decisions=composition.operator_decisions,
        source_snapshot=snapshot,
        source_hash=canonical_payload_hash(snapshot),
        generated_at=now,
        decided_by=composition.decided_by,
        decided_at=composition.decided_at,
        recorded_at=now,
        recorded_by="test:durable-page-qa-identity",
        record_source="test_city_fixture",
    )
    session.commit()
    return business, website, plan, planned, page, composition


def _freeze_exact_legacy_city_service_qa(
    session: Session,
    page: GeneratedPage,
) -> GeneratedPageQAResult:
    save_page_qa(session, page.id)
    record = _current_record(session, page.id)
    legacy_source = page_qa_service._semantic_qa_source_snapshot(
        session,
        page,
        contract=CITY_SERVICE_CONTRACT,
        legacy_city_service_policy=True,
    )
    record.source_hash = page_qa_service._canonical_hash(legacy_source)
    record.qa_ruleset_hash = page_qa_service.LEGACY_CITY_SERVICE_QA_RULESET_HASH
    legacy_result = page_qa_service._evaluate_page_qa(
        session,
        page.id,
        legacy_city_service_policy=True,
    )
    record.check_payload = [
        item.model_dump(mode="json") for item in legacy_result.checks
    ]
    record.passed_count = legacy_result.passed_count
    record.warning_count = legacy_result.warning_count
    record.failed_count = legacy_result.failed_count
    record.readiness_status = legacy_result.readiness_status
    _project_record(session, page, record)
    return record


def _current_record(session: Session, page_id: int) -> GeneratedPageQAResult:
    return session.exec(
        select(GeneratedPageQAResult).where(
            GeneratedPageQAResult.generated_page_id == page_id,
            GeneratedPageQAResult.lifecycle_status == "current",
        )
    ).one()


def _advance_fixture_composition(
    session: Session,
    composition: PageComposition,
    *,
    marker: str,
) -> None:
    snapshot = deepcopy(composition.source_snapshot)
    snapshot["fixture_revision"] = marker
    now = datetime.now(UTC)
    advance_composition_revision(
        session,
        composition,
        generated_components=composition.generated_components,
        operator_decisions=composition.operator_decisions,
        source_snapshot=snapshot,
        source_hash=canonical_payload_hash(snapshot),
        generated_at=now,
        decided_by=composition.decided_by,
        decided_at=composition.decided_at,
        recorded_at=now,
        recorded_by="test:durable-page-qa-identity",
        record_source="test_successor",
    )


def _project_record(
    session: Session,
    page: GeneratedPage,
    record: GeneratedPageQAResult,
) -> None:
    record.result_hash = qa_result_record_hash(record.model_dump(mode="python"))
    result = _record_as_result(record)
    page.qa_status = result.readiness_status
    page.qa_result = result.model_dump(mode="json", exclude={"persisted"})
    page.qa_checked_at = result.checked_at
    session.add(record)
    session.add(page)
    session.flush()


def _synthetic_city_cta_checks(cta: str) -> dict[str, QACheckItem]:
    checks: list[QACheckItem] = []
    page_qa_service._evaluate_city_service_public_cta(
        checks,
        draft={"call_to_action": cta},
        business={
            "company_name": "Synthetic Home Services",
            "brand_name": "Synthetic Home Services",
            "phone": "555-010-2200",
            "public_email": "hello@synthetic.example",
            "license_number": "SYNTHETIC-LICENSE-42",
            "certified_operator": "Synthetic Operator",
        },
        website={"public_url": "https://synthetic.example"},
        service={"service_name": "Synthetic Property Care"},
        city={"city_name": "Example City"},
    )
    return {check.key: check for check in checks}


def test_city_service_qa_does_not_treat_invalid_configured_phone_as_unconfigured() -> None:
    checks: list[QACheckItem] = []
    page_qa_service._evaluate_city_service_public_cta(
        checks,
        draft={
            "call_to_action": (
                "To discuss Synthetic Property Care in Example City, "
                "contact Synthetic Home Services."
            )
        },
        business={
            "company_name": "Synthetic Home Services",
            "brand_name": "Synthetic Home Services",
            "phone": "123",
            "public_email": "",
            "license_number": "SYNTHETIC-LICENSE-42",
            "certified_operator": "Synthetic Operator",
        },
        website={"public_url": ""},
        service={"service_name": "Synthetic Property Care"},
        city={"city_name": "Example City"},
    )

    by_key = {check.key: check for check in checks}
    assert by_key["cta_ownership"].status == "pass"
    assert by_key["cta_contact"].status == "fail"


def test_city_service_qa_rejects_malformed_configured_public_url() -> None:
    checks: list[QACheckItem] = []
    malformed_url = "https://synthetic..example"
    page_qa_service._evaluate_city_service_public_cta(
        checks,
        draft={
            "call_to_action": (
                "To discuss Synthetic Property Care in Example City, "
                f"contact Synthetic Home Services through {malformed_url}."
            )
        },
        business={
            "company_name": "Synthetic Home Services",
            "brand_name": "Synthetic Home Services",
            "phone": "",
            "public_email": "",
            "license_number": "SYNTHETIC-LICENSE-42",
            "certified_operator": "Synthetic Operator",
        },
        website={"public_url": malformed_url},
        service={"service_name": "Synthetic Property Care"},
        city={"city_name": "Example City"},
    )

    by_key = {check.key: check for check in checks}
    assert by_key["cta_contact"].status == "fail"
    assert by_key["cta_destinations"].status == "fail"


def test_exact_legacy_city_service_qa_predecessor_accepts_one_frozen_blocked_row(
    db_session: Session,
) -> None:
    *_, page, _ = _city_service_scope(db_session, suffix="legacy-exact")
    record = _freeze_exact_legacy_city_service_qa(db_session, page)
    effective = effective_page_qa_state(db_session, page.id)

    assert record.readiness_status == "blocked"
    assert effective.current is False
    assert effective.classification == "stale_qa_algorithm"
    assert page_qa_service.is_exact_legacy_city_service_qa_predecessor(
        db_session,
        page,
        record,
    )


@pytest.mark.parametrize(
    "tamper",
    [
        "ruleset_hash",
        "source_hash",
        "check_order",
        "check_payload_shape",
        "check_payload_extra_field",
        "projection",
        "projection_nested_extra",
        "lifecycle",
        "duplicate_current",
        "non_city_page",
    ],
)
def test_exact_legacy_city_service_qa_predecessor_rejects_identity_tampering(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    *_, page, _ = _city_service_scope(db_session, suffix=f"legacy-{tamper}")
    record = _freeze_exact_legacy_city_service_qa(db_session, page)

    if tamper == "ruleset_hash":
        record.qa_ruleset_hash = "f" * 64
        _project_record(db_session, page, record)
    elif tamper == "source_hash":
        record.source_hash = "e" * 64
        _project_record(db_session, page, record)
    elif tamper == "check_order":
        payload = deepcopy(record.check_payload or [])
        payload[0], payload[1] = payload[1], payload[0]
        record.check_payload = payload
        _project_record(db_session, page, record)
    elif tamper == "check_payload_shape":
        payload = deepcopy(record.check_payload or [])
        payload[0]["message"] = "Rehashed but noncanonical legacy message."
        payload[0]["severity"] = "warning"
        record.check_payload = payload
        _project_record(db_session, page, record)
    elif tamper == "check_payload_extra_field":
        payload = deepcopy(record.check_payload or [])
        payload[0]["unexpected"] = "rehashed extra field"
        record.check_payload = payload
        _project_record(db_session, page, record)
    elif tamper == "projection":
        projection = deepcopy(page.qa_result or {})
        projection["source_hash"] = "d" * 64
        page.qa_result = projection
        db_session.add(page)
        db_session.flush()
    elif tamper == "projection_nested_extra":
        projection = deepcopy(page.qa_result or {})
        projection["checks"][0]["unexpected"] = "nested projection tamper"
        page.qa_result = projection
        db_session.add(page)
        db_session.flush()
    elif tamper == "lifecycle":
        record.lifecycle_status = "superseded"
        _project_record(db_session, page, record)
    elif tamper == "duplicate_current":
        monkeypatch.setattr(
            page_qa_service,
            "_current_qa_records",
            lambda *_: [record, record.model_copy(deep=True)],
        )
    elif tamper == "non_city_page":
        page.page_type = "informational"
        db_session.add(page)
        db_session.flush()

    assert not page_qa_service.is_exact_legacy_city_service_qa_predecessor(
        db_session,
        page,
        record,
    )


def test_public_email_changes_stale_only_city_service_qa_source_identity(
    db_session: Session,
) -> None:
    informational_business, *_, informational_page, _ = _scope(
        db_session,
        suffix="email-non-city",
    )
    city_business, *_, city_page, _ = _city_service_scope(
        db_session,
        suffix="email-city",
    )
    informational_business.email = "before-non-city@example.test"
    city_business.email = "before-city@example.test"
    db_session.add(informational_business)
    db_session.add(city_business)
    db_session.commit()
    save_page_qa(db_session, informational_page.id)
    save_page_qa(db_session, city_page.id)

    informational_business.email = "after-non-city@example.test"
    city_business.email = "after-city@example.test"
    db_session.add(informational_business)
    db_session.add(city_business)
    db_session.flush()

    informational_state = effective_page_qa_state(db_session, informational_page.id)
    city_state = effective_page_qa_state(db_session, city_page.id)

    assert informational_state.classification == "current_exact_identity_match"
    assert city_state.classification == "otherwise_invalid"
    assert city_state.reasons == ("QA evaluator inputs changed after evaluation.",)


@pytest.mark.parametrize(
    ("governed_value", "replacement"),
    [
        ("Synthetic Home Services", "Different Synthetic Company"),
        ("Synthetic Property Care", "Different Synthetic Service"),
        ("Example City", "Alternate Municipality"),
    ],
)
def test_city_service_cta_ownership_rejects_each_substituted_governed_identity(
    governed_value: str,
    replacement: str,
) -> None:
    baseline = (
        "To discuss Synthetic Property Care in Example City, contact "
        "Synthetic Home Services at 555-010-2200."
    )
    checks = _synthetic_city_cta_checks(baseline.replace(governed_value, replacement))

    assert checks["cta_ownership"].status == "fail"
    assert checks["cta_contact"].status == "pass"


@pytest.mark.parametrize(
    ("destination", "expected_status"),
    [
        ("tel:5550102200", "pass"),
        ("https://synthetic.example/request", "pass"),
        ("/request-estimate", "pass"),
        ("#estimate", "pass"),
        (r"/\evil.example", "fail"),
        (r"\\evil.example", "fail"),
        ("/\t/evil.example", "fail"),
        ("/\r/evil.example", "fail"),
        ("/\n/evil.example", "fail"),
        ("\x00//evil.example", "fail"),
        ("\x01//evil.example", "fail"),
        ("\x07//evil.example", "fail"),
        ("\x1f//evil.example", "fail"),
        ("\x00\\\\evil.example", "fail"),
        ("\x00javascript:alert", "fail"),
        ("synthetic.example::", "fail"),
        ("https://different.example/request", "fail"),
    ],
)
def test_city_service_cta_destination_policy_is_governed_and_origin_exact(
    destination: str,
    expected_status: str,
) -> None:
    cta = (
        "To discuss Synthetic Property Care in Example City, contact "
        f"Synthetic Home Services at 555-010-2200 or {destination}."
    )
    checks = _synthetic_city_cta_checks(cta)

    assert checks["cta_ownership"].status == "pass"
    assert checks["cta_contact"].status == "pass"
    assert checks["cta_destinations"].status == expected_status


def test_requested_page_binding_returns_only_the_requested_current_result(
    db_session: Session,
) -> None:
    *_, first_page, _ = _scope(db_session, suffix="requested-first")
    *_, second_page, _ = _scope(db_session, suffix="requested-second")
    first = save_page_qa(db_session, first_page.id)
    second = save_page_qa(db_session, second_page.id)

    observed = get_page_qa(db_session, second_page.id)

    assert first.qa_result_id != second.qa_result_id
    assert observed.page_id == second_page.id
    assert observed.qa_result_id == second.qa_result_id
    assert observed.website_id == second_page.website_id
    assert observed.currentness_status == "current_exact_identity_match"


def test_unplanned_generated_page_fails_closed_before_qa_persistence(
    db_session: Session,
) -> None:
    *_, planned, page, _ = _scope(db_session, suffix="unplanned")
    planned.generated_page_id = None
    db_session.add(planned)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        save_page_qa(db_session, page.id)

    assert exc_info.value.status_code == 409
    assert "Planned Page and Site Plan owner" in str(exc_info.value.detail)
    assert list(
        db_session.exec(
            select(GeneratedPageQAResult).where(
                GeneratedPageQAResult.generated_page_id == page.id
            )
        ).all()
    ) == []


def test_legacy_page_1_result_cannot_bind_to_requested_page_41(
    db_session: Session,
) -> None:
    *_, first_page, _ = _scope(
        db_session,
        suffix="page-one",
        generated_page_id=1,
    )
    *_, requested_page, _ = _scope(
        db_session,
        suffix="page-forty-one",
        generated_page_id=41,
    )
    requested_page.qa_result = {
        "page_id": first_page.id,
        "readiness_status": "ready",
    }
    requested_page.qa_status = "ready"
    requested_page.qa_checked_at = datetime.now(UTC)
    db_session.add(requested_page)
    db_session.commit()

    state = effective_page_qa_state(db_session, requested_page.id)

    assert first_page.id == 1
    assert requested_page.id == 41
    assert state.classification == "wrong_page_identity"
    assert "1 != 41" in state.reasons[0]


def test_cross_website_current_result_fails_closed(db_session: Session) -> None:
    *_, page, _ = _scope(db_session, suffix="cross-site-source")
    _, other_website, *_ = _scope(db_session, suffix="cross-site-other")
    save_page_qa(db_session, page.id)
    record = _current_record(db_session, page.id)
    record.website_id = other_website.id
    db_session.add(record)
    db_session.flush()

    state = effective_page_qa_state(db_session, page.id)

    assert state.classification == "wrong_website_identity"
    assert state.current is False


def test_newer_revision_makes_current_result_stale(db_session: Session) -> None:
    *_, page, _ = _scope(db_session, suffix="stale-revision")
    content_hash = authoritative_page_qa_state(db_session, page).content_hash
    # These page revisions intentionally occur after the composition evidence;
    # they must not be backdated into that immutable composition revision.
    initial_time = datetime.now(UTC) + timedelta(seconds=1)
    first_revision = GeneratedPageRevision(
        generated_page_id=page.id,
        created_at=initial_time,
        created_by="QA test",
        reason="Initial revision",
        draft_hash_before="0" * 64,
        draft_hash_after=content_hash,
        draft_content_before={},
        draft_content_after=deepcopy(page.draft_content or {}),
        changed_fields=["draft_content"],
    )
    db_session.add(first_revision)
    db_session.commit()
    saved = save_page_qa(db_session, page.id)
    second_revision = GeneratedPageRevision(
        generated_page_id=page.id,
        created_at=initial_time + timedelta(seconds=1),
        created_by="QA test",
        reason="Identity-only revision",
        draft_hash_before=content_hash,
        draft_hash_after=content_hash,
        draft_content_before=deepcopy(page.draft_content or {}),
        draft_content_after=deepcopy(page.draft_content or {}),
        changed_fields=[],
    )
    db_session.add(second_revision)
    db_session.commit()

    state = effective_page_qa_state(db_session, page.id)

    assert saved.latest_generated_page_revision_id == first_revision.id
    assert second_revision.id != first_revision.id
    assert state.classification == "stale_generated_revision"


def test_content_change_makes_current_result_stale(db_session: Session) -> None:
    *_, page, _ = _scope(db_session, suffix="stale-content")
    save_page_qa(db_session, page.id)
    changed = deepcopy(page.draft_content or {})
    changed["intro"] = "Changed after the durable QA evaluation."
    page.draft_content = changed
    db_session.add(page)
    db_session.flush()

    state = effective_page_qa_state(db_session, page.id)

    assert state.classification == "stale_content_hash"


def test_composition_change_makes_current_result_stale(db_session: Session) -> None:
    *_, page, composition = _scope(db_session, suffix="stale-composition")
    save_page_qa(db_session, page.id)
    bound_qa = _current_record(db_session, page.id)
    _advance_fixture_composition(
        db_session,
        composition,
        marker="stale-composition",
    )

    state = effective_page_qa_state(db_session, page.id)
    historical_revision = resolve_qa_composition_revision(db_session, bound_qa)
    current_revision = current_composition_revision(db_session, composition)

    assert state.classification == "stale_composition"
    assert historical_revision.composition_version == 1
    assert current_revision.composition_version == 2
    assert historical_revision.id != current_revision.id


def test_malformed_composition_history_invalidates_all_downstream_qa_gates_without_writes(
    db_session: Session,
) -> None:
    _, website, plan, planned, page, composition = _scope(
        db_session,
        suffix="malformed-history-gates",
    )
    saved = save_page_qa(db_session, page.id)
    assert saved.readiness_status == "ready"
    revision = db_session.exec(
        select(PageCompositionRevision).where(
            PageCompositionRevision.page_composition_id == composition.id,
            PageCompositionRevision.composition_version
            == composition.composition_version,
        )
    ).one()
    revision.recorded_by = "tampered:durable-qa-gates"
    db_session.add(revision)
    db_session.flush()

    qa_count_before = len(
        db_session.exec(
            select(GeneratedPageQAResult).where(
                GeneratedPageQAResult.generated_page_id == page.id
            )
        ).all()
    )
    approval_count_before = len(
        db_session.exec(
            select(ApprovalAudit).where(ApprovalAudit.generated_page_id == page.id)
        ).all()
    )
    wordpress_audit_count_before = len(
        db_session.exec(
            select(WordPressDraftAudit).where(
                WordPressDraftAudit.generated_page_id == page.id
            )
        ).all()
    )
    page_before = (page.status, page.updated_at, deepcopy(page.qa_result))
    composition_before = (
        composition.status,
        composition.composition_version,
        composition.source_hash,
    )

    effective = effective_page_qa_state(db_session, page.id)
    assert effective.classification == "otherwise_invalid"
    assert effective.current is False
    assert effective.ready is False
    assert "immutable hash" in effective.reasons[0]

    with pytest.raises(HTTPException) as exc_info:
        approve_page_with_audit(
            db_session,
            page.id,
            approved_by="History Gate Approver",
        )
    assert exc_info.value.status_code == 409
    assert "immutable hash" in str(exc_info.value.detail)

    queue = build_approval_queue(db_session, website_id=website.id)
    queue_item = next(item for item in queue.items if item.page_id == page.id)
    assert queue_item.is_ready_for_approval is False
    assert queue_item.needs_manual_review is True
    assert queue_item.qa_status == "not_run"

    export = build_page_export_package(db_session, page.id)
    assert export.export_ready is False
    assert any(item.code == "qa_stale" for item in export.warnings)

    readiness = evaluate_website_readiness(db_session, plan.id)
    content = next(
        item for item in readiness.categories if item.key == "content_readiness"
    )
    stale_qa = next(item for item in content.items if item.key == "page_qa_stale")
    assert planned.id in stale_qa.affected_planned_page_ids

    dry_run = dry_run_wordpress_draft(db_session, page.id)
    gates = {item.code: item.passed for item in dry_run.gate_results}
    assert dry_run.ready is False
    assert gates["qa_ready"] is False
    assert gates["qa_current"] is False
    assert gates["export_clear"] is False

    assert len(
        db_session.exec(
            select(GeneratedPageQAResult).where(
                GeneratedPageQAResult.generated_page_id == page.id
            )
        ).all()
    ) == qa_count_before
    assert len(
        db_session.exec(
            select(ApprovalAudit).where(ApprovalAudit.generated_page_id == page.id)
        ).all()
    ) == approval_count_before
    assert len(
        db_session.exec(
            select(WordPressDraftAudit).where(
                WordPressDraftAudit.generated_page_id == page.id
            )
        ).all()
    ) == wordpress_audit_count_before
    db_session.refresh(page)
    db_session.refresh(composition)
    assert (page.status, page.updated_at, page.qa_result) == page_before
    assert (
        composition.status,
        composition.composition_version,
        composition.source_hash,
    ) == composition_before
    assert not db_session.new and not db_session.dirty and not db_session.deleted


def test_algorithm_change_makes_current_result_stale(db_session: Session) -> None:
    *_, page, _ = _scope(db_session, suffix="stale-algorithm")
    save_page_qa(db_session, page.id)
    record = _current_record(db_session, page.id)
    record.qa_algorithm_version = "legacy"
    db_session.add(record)
    db_session.flush()

    state = effective_page_qa_state(db_session, page.id)

    assert state.classification == "stale_qa_algorithm"


def test_consumed_source_change_invalidates_current_result(db_session: Session) -> None:
    business, *_, page, _ = _scope(db_session, suffix="stale-source")
    save_page_qa(db_session, page.id)
    business.phone = "407-555-0199"
    db_session.add(business)
    db_session.flush()

    state = effective_page_qa_state(db_session, page.id)

    assert state.classification == "otherwise_invalid"
    assert state.reasons == ("QA evaluator inputs changed after evaluation.",)


def test_website_configuration_change_invalidates_current_result(
    db_session: Session,
) -> None:
    _, website, *_, page, _ = _scope(db_session, suffix="stale-website-config")
    website.configuration = {"short_brand_name": "before"}
    db_session.add(website)
    db_session.commit()
    save_page_qa(db_session, page.id)
    website.configuration = {"short_brand_name": "after"}
    db_session.add(website)
    db_session.flush()

    state = effective_page_qa_state(db_session, page.id)

    assert state.classification == "otherwise_invalid"
    assert state.reasons == ("QA evaluator inputs changed after evaluation.",)


def test_generated_page_api_projection_uses_authoritative_effective_qa(
    db_session: Session,
) -> None:
    *_, page, composition = _scope(db_session, suffix="effective-read")
    saved = save_page_qa(db_session, page.id)

    current = generated_page_with_effective_qa(db_session, page)
    assert current["qa_status"] == saved.readiness_status
    assert current["qa_result"]["persisted"] is True
    assert current["qa_result"]["page_id"] == page.id

    _advance_fixture_composition(
        db_session,
        composition,
        marker="effective-read",
    )

    stale = generated_page_with_effective_qa(db_session, page)
    assert stale["qa_status"] == "not_run"
    assert stale["qa_checked_at"] is None
    assert stale["qa_result"]["persisted"] is False
    assert stale["qa_result"]["currentness_status"] == "stale_composition"


def test_missing_result_orphan_and_duplicate_current_fail_closed(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    *_, page, _ = _scope(db_session, suffix="missing-duplicate")
    missing = effective_page_qa_state(db_session, page.id)
    orphan = effective_page_qa_state(db_session, 999_999)
    save_page_qa(db_session, page.id)
    record = _current_record(db_session, page.id)
    duplicate = record.model_copy(update={"id": (record.id or 0) + 10_000})
    monkeypatch.setattr(
        page_qa_service,
        "_current_qa_records",
        lambda _session, _page_id: [record, duplicate],
    )
    duplicate_state = effective_page_qa_state(db_session, page.id)

    assert missing.classification == "missing_qa"
    assert orphan.classification == "orphaned_qa"
    assert duplicate_state.classification == "duplicate_current_qa"


def test_missing_generated_page_projection_invalidates_bound_result(
    db_session: Session,
) -> None:
    *_, page, _ = _scope(db_session, suffix="missing-projection")
    save_page_qa(db_session, page.id)
    page.qa_result = None
    db_session.add(page)
    db_session.flush()

    state = effective_page_qa_state(db_session, page.id)

    assert state.classification == "otherwise_invalid"
    assert state.reasons == (
        "Generated Page QA projection is missing or malformed.",
    )


def test_evaluator_snapshot_blocks_mid_evaluation_assignment_drift(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    business, website, *_, page, _ = _scope(
        db_session,
        suffix="evaluator-snapshot",
    )
    image = ImageMetadata(
        business_id=business.id,
        website_id=website.id,
        file_name="concurrent-assignment.jpg",
        image_role="support",
        review_status="reviewed",
    )
    db_session.add(image)
    db_session.commit()
    original = page_qa_service.authoritative_page_qa_state

    def drift_before_identity_binding(
        session: Session,
        generated_page: GeneratedPage,
        *,
        evaluator_snapshot=None,
    ):
        session.add(
            PageImageAssignment(
                generated_page_id=generated_page.id,
                image_metadata_id=image.id,
                image_role="support",
                status="active",
            )
        )
        session.flush()
        return original(
            session,
            generated_page,
            evaluator_snapshot=evaluator_snapshot,
        )

    with monkeypatch.context() as scoped:
        scoped.setattr(
            page_qa_service,
            "authoritative_page_qa_state",
            drift_before_identity_binding,
        )
        saved = save_page_qa(db_session, page.id)

    state = effective_page_qa_state(db_session, page.id)

    assert saved.readiness_status == "ready"
    assert state.current is False
    assert state.ready is False
    assert state.classification == "otherwise_invalid"
    assert state.reasons == ("QA evaluator inputs changed after evaluation.",)


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    [
        ("source_hash", "f" * 64),
        ("passed_count", 99),
        ("checks", []),
        ("qa_algorithm_version", "tampered"),
        ("currentness_reasons", ["tampered"]),
    ],
)
def test_full_generated_page_projection_must_match_durable_result(
    db_session: Session,
    field: str,
    tampered_value: object,
) -> None:
    *_, page, _ = _scope(db_session, suffix=f"projection-{field}")
    save_page_qa(db_session, page.id)
    projection = deepcopy(page.qa_result or {})
    projection[field] = tampered_value
    page.qa_result = projection
    db_session.add(page)
    db_session.flush()

    state = effective_page_qa_state(db_session, page.id)

    assert state.current is False
    assert state.ready is False
    assert state.classification == "otherwise_invalid"
    assert state.reasons == (
        "Generated Page QA projection does not match its durable QA result.",
    )


def test_nested_generated_page_projection_tamper_fails_closed(
    db_session: Session,
) -> None:
    *_, page, _ = _scope(db_session, suffix="projection-nested-extra")
    save_page_qa(db_session, page.id)
    projection = deepcopy(page.qa_result or {})
    projection["checks"][0]["unexpected"] = "nested projection tamper"
    page.qa_result = projection
    db_session.add(page)
    db_session.flush()

    state = effective_page_qa_state(db_session, page.id)

    assert state.current is False
    assert state.ready is False
    assert state.classification == "otherwise_invalid"
    assert state.reasons == (
        "Generated Page QA projection does not match its durable QA result.",
    )


@pytest.mark.parametrize(
    ("readiness_status", "check_status", "severity", "counts", "expected_ready"),
    [
        ("ready", "pass", "blocker", (1, 0, 0), True),
        ("needs_review", "warning", "warning", (0, 1, 0), False),
        ("blocked", "fail", "blocker", (0, 0, 1), False),
    ],
)
def test_exact_current_ready_warning_and_failure_results_are_bound(
    db_session: Session,
    readiness_status: str,
    check_status: str,
    severity: str,
    counts: tuple[int, int, int],
    expected_ready: bool,
) -> None:
    *_, page, _ = _scope(db_session, suffix=f"current-{readiness_status}")
    save_page_qa(db_session, page.id)
    record = _current_record(db_session, page.id)
    record.readiness_status = readiness_status
    record.passed_count, record.warning_count, record.failed_count = counts
    record.check_payload = [
        {
            "key": "contract",
            "label": "QA contract",
            "status": check_status,
            "severity": severity,
            "message": f"Synthetic {check_status} outcome.",
            "suggested_fix": "" if check_status == "pass" else "Review the page.",
            "issue_location": "content",
        }
    ]
    _project_record(db_session, page, record)

    state = effective_page_qa_state(db_session, page.id)

    assert state.classification == "current_exact_identity_match"
    assert state.result is not None
    assert state.result.readiness_status == readiness_status
    assert state.ready is expected_ready


def test_reconciliation_is_idempotent_supersedes_current_and_preserves_history(
    db_session: Session,
) -> None:
    *_, page, _ = _scope(db_session, suffix="reconciliation")
    historical_payload = {
        "page_id": page.id,
        "readiness_status": "ready",
        "checks": [{"key": "legacy", "status": "pass"}],
    }
    historical = GeneratedPageQAResult(
        generated_page_id=page.id,
        lifecycle_status="historical_unbound",
        result_hash=historical_qa_payload_hash(historical_payload),
        historical_payload=historical_payload,
    )
    db_session.add(historical)
    db_session.commit()

    first = reconcile_page_qa(db_session, page.id)
    first_count = len(
        db_session.exec(
            select(GeneratedPageQAResult).where(
                GeneratedPageQAResult.generated_page_id == page.id
            )
        ).all()
    )
    repeated = reconcile_page_qa(db_session, page.id)
    repeated_count = len(
        db_session.exec(
            select(GeneratedPageQAResult).where(
                GeneratedPageQAResult.generated_page_id == page.id
            )
        ).all()
    )

    changed = deepcopy(page.draft_content or {})
    changed["intro"] = "A real draft change requires a new durable QA result."
    page.draft_content = changed
    db_session.add(page)
    db_session.commit()
    replacement = reconcile_page_qa(db_session, page.id)
    records = list(
        db_session.exec(
            select(GeneratedPageQAResult)
            .where(GeneratedPageQAResult.generated_page_id == page.id)
            .order_by(GeneratedPageQAResult.id)
        ).all()
    )
    preserved_history = next(row for row in records if row.id == historical.id)
    superseded = next(row for row in records if row.id == first.qa_result_id)
    current = next(row for row in records if row.id == replacement.qa_result_id)

    assert first_count == 2
    assert repeated_count == first_count
    assert repeated.qa_result_id == first.qa_result_id
    assert preserved_history.lifecycle_status == "historical_unbound"
    assert preserved_history.historical_payload == historical_payload
    assert preserved_history.result_hash == historical_qa_payload_hash(
        historical_payload
    )
    assert superseded.lifecycle_status == "superseded"
    assert current.lifecycle_status == "current"
    assert current.supersedes_qa_result_id == superseded.id
    assert len(records) == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("qa_status", "ready"),
        ("qa_result", {"page_id": 41}),
        ("qa_checked_at", "2026-08-09T12:00:00Z"),
    ],
)
def test_generated_page_update_rejects_raw_qa_fields(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GeneratedPageUpdate.model_validate({field: value})
