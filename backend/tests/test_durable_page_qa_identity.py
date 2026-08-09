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
    Business,
    GeneratedPage,
    GeneratedPageQAResult,
    GeneratedPageRevision,
    ImageMetadata,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    SitePlan,
    Website,
)
from app.schemas.entities import GeneratedPageUpdate
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
    save_page_qa,
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
    composition = PageComposition(
        website_id=website.id,
        site_plan_id=plan.id,
        planned_page_id=planned.id,
        generated_page_id=page.id,
        composition_version=1,
        generated_components=[],
        operator_decisions=[],
        source_snapshot={"fixture": suffix},
        source_hash="a" * 64,
        status="current",
    )
    session.add(composition)
    session.commit()
    return business, website, plan, planned, page, composition


def _current_record(session: Session, page_id: int) -> GeneratedPageQAResult:
    return session.exec(
        select(GeneratedPageQAResult).where(
            GeneratedPageQAResult.generated_page_id == page_id,
            GeneratedPageQAResult.lifecycle_status == "current",
        )
    ).one()


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
    initial_time = datetime.now(UTC) - timedelta(seconds=2)
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
    composition.composition_version += 1
    composition.source_hash = "b" * 64
    db_session.add(composition)
    db_session.flush()

    state = effective_page_qa_state(db_session, page.id)

    assert state.classification == "stale_composition"


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

    composition.composition_version += 1
    composition.source_hash = "f" * 64
    db_session.add(composition)
    db_session.flush()

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
