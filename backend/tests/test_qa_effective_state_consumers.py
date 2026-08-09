from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.models import GeneratedPage
from app.schemas.page_export import ExportSEO
from app.services import approval_queue, page_export, website_readiness


def _state(
    classification: str,
    *,
    readiness_status: str | None = None,
    failed_count: int = 0,
    warning_count: int = 0,
    reason: str = "",
):
    current = classification == "current_exact_identity_match"
    result = (
        SimpleNamespace(
            readiness_status=readiness_status,
            failed_count=failed_count,
            warning_count=warning_count,
            checked_at=datetime(2026, 8, 9, tzinfo=UTC),
        )
        if current
        else None
    )
    ready = bool(
        current
        and readiness_status == "ready"
        and failed_count == 0
        and warning_count == 0
    )
    return SimpleNamespace(
        classification=classification,
        reasons=(reason,) if reason else (),
        current=current,
        ready=ready,
        result=result,
    )


def _page(page_id: int = 41) -> GeneratedPage:
    return GeneratedPage(
        id=page_id,
        business_id=1,
        website_id=1,
        page_type="about",
        page_title="About",
        page_slug="about",
        status="draft",
    )


def test_approval_queue_rejects_page_1_result_projected_onto_page_41() -> None:
    state = _state(
        "wrong_page_identity",
        reason="Persisted QA page identity does not match the Generated Page (1 != 41).",
    )

    item = approval_queue._queue_item(
        _page(41),
        city=None,
        county=None,
        service=None,
        revision_count=0,
        latest_revision_at=None,
        approval_count=0,
        hero_image_status="missing",
        qa_state=state,
    )

    assert item.qa_status == "not_run"
    assert item.qa_checked_at is None
    assert item.is_ready_for_approval is False
    assert item.edited_since_last_qa is False
    assert item.needs_manual_review is True
    assert "identity-mismatched" in item.next_recommended_action


def test_approval_queue_allows_only_current_exact_ready_qa() -> None:
    item = approval_queue._queue_item(
        _page(41),
        city=None,
        county=None,
        service=None,
        revision_count=0,
        latest_revision_at=None,
        approval_count=0,
        hero_image_status="missing",
        qa_state=_state(
            "current_exact_identity_match",
            readiness_status="ready",
        ),
    )

    assert item.qa_status == "ready"
    assert item.qa_checked_at is not None
    assert item.is_ready_for_approval is True
    assert item.edited_since_last_qa is False
    assert item.needs_manual_review is False


class _Rows:
    def all(self):
        return []


class _SessionStub:
    def get(self, *_args):
        return None

    def exec(self, *_args):
        return _Rows()


@pytest.mark.parametrize(
    ("state", "expected_code"),
    [
        (_state("missing_qa"), "qa_not_ready"),
        (
            _state(
                "stale_composition",
                reason="QA composition identity is not current.",
            ),
            "qa_stale",
        ),
        (
            _state(
                "current_exact_identity_match",
                readiness_status="blocked",
                failed_count=1,
            ),
            "qa_blocked",
        ),
    ],
)
def test_page_export_distinguishes_missing_stale_and_failed_qa(
    monkeypatch,
    state,
    expected_code,
) -> None:
    monkeypatch.setattr(page_export, "validate_draft_contract", lambda *_args: [])
    page = _page(41)
    page.status = "approved"

    warnings = page_export._readiness_warnings(
        _SessionStub(),
        page,
        draft={},
        seo=ExportSEO(
            meta_title="About",
            meta_description="About the company.",
            social_title="About",
            social_description="About the company.",
            suggested_url_slug="about",
        ),
        media=[],
        slug_conflicts=[],
        contract=SimpleNamespace(media_policy="deferred"),
        qa_state=state,
    )

    qa_codes = [item.code for item in warnings if item.code.startswith("qa_")]
    assert qa_codes == [expected_code]
    assert page_export._effective_qa_status(state) == (
        state.result.readiness_status if state.current else "not_run"
    )


def test_website_readiness_separates_missing_stale_composition_and_failed_qa(
    monkeypatch,
) -> None:
    planned_pages = [
        SimpleNamespace(id=1, page_type="about", generated_page_id=41),
        SimpleNamespace(id=2, page_type="about", generated_page_id=42),
        SimpleNamespace(id=3, page_type="about", generated_page_id=43),
    ]
    generated = {
        page_id: SimpleNamespace(
            id=page_id,
            page_type="about",
            draft_content={"planning_generated_at": None},
        )
        for page_id in (41, 42, 43)
    }
    states = {
        41: _state(
            "stale_composition",
            reason="QA composition identity is not current.",
        ),
        42: _state("missing_qa"),
        43: _state(
            "current_exact_identity_match",
            readiness_status="blocked",
            failed_count=1,
        ),
    }
    monkeypatch.setattr(website_readiness, "review_contract_for", lambda *_args: object())
    monkeypatch.setattr(website_readiness, "validate_draft_contract", lambda *_args: [])
    monkeypatch.setattr(
        website_readiness,
        "effective_page_qa_state",
        lambda _session, page: states[page.id],
    )

    category = website_readiness._content_category(
        object(),
        planned_pages,
        generated,
        {},
    )
    items = {item.key: item for item in category.items}

    assert items["page_qa_missing"].affected_planned_page_ids == [2]
    assert items["page_qa_stale"].affected_planned_page_ids == [1]
    assert items["page_qa_failed"].affected_planned_page_ids == [3]
    assert items["page_qa"].affected_planned_page_ids == [1, 2, 3]
    assert "1 missing, 1 stale or identity-mismatched, and 1 failed" in items[
        "page_qa"
    ].message
