from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from app.api.site_plan_routes import router as site_plan_router
from app.db.session import get_session
from app.models import (
    Business,
    GeneratedPage,
    GeneratedPageRevision,
    PageComposition,
    PageCompositionRevision,
)
from app.schemas.page_composition import PageCompositionDecisionUpdate
from app.services import page_composition as composition_service
from app.services.page_composition import (
    PageCompositionError,
    refresh_site_plan_compositions,
    update_operator_composition_decisions,
)
from app.services.page_composition_history import (
    PageCompositionHistoryError,
    canonical_utc_timestamp,
    canonical_payload_hash,
    composition_revision_hash,
    current_composition_revision,
    list_composition_revisions,
    read_composition_revision,
)

from test_page_composition import _engine, _scope, _seed_registry


def _one_composition(session: Session, generated_page_id: int) -> PageComposition:
    return session.exec(
        select(PageComposition).where(
            PageComposition.generated_page_id == generated_page_id
        )
    ).one()


def test_refresh_records_append_only_history_and_noop_is_idempotent() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, pages = _scope(session, suffix="history-refresh")

        created = refresh_site_plan_compositions(session, plan.id)
        assert created.created == 2 and created.blocked == []
        composition = _one_composition(session, pages[0][1].id)
        initial = read_composition_revision(session, composition.id, 1)
        initial_evidence = deepcopy(initial.model_dump(mode="python"))

        business = session.get(Business, pages[0][1].business_id)
        assert business is not None
        business.phone = "407-555-0199"
        session.add(business)
        session.commit()

        refreshed = refresh_site_plan_compositions(session, plan.id)
        assert refreshed.refreshed == 2 and refreshed.blocked == []
        session.refresh(composition)
        history = list_composition_revisions(session, composition.id)
        assert [item.composition_version for item in history] == [1, 2]
        assert history[0].model_dump(mode="python") == initial_evidence
        assert history[1].supersedes_revision_id == history[0].id
        assert history[1].supersedes_revision_hash == history[0].revision_hash
        assert current_composition_revision(session, composition).id == history[1].id

        repeated = refresh_site_plan_compositions(session, plan.id)
        assert repeated.unchanged == 2 and repeated.blocked == []
        assert len(list_composition_revisions(session, composition.id)) == 2


def test_operator_successor_preserves_generation_identity_and_is_idempotent() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, pages = _scope(session, suffix="history-operator")
        assert refresh_site_plan_compositions(session, plan.id).blocked == []
        composition = _one_composition(session, pages[0][1].id)
        original_generated_at = composition.generated_at
        original_components = deepcopy(composition.generated_components)
        original_snapshot = deepcopy(composition.source_snapshot)
        original_source_hash = composition.source_hash
        payload = PageCompositionDecisionUpdate(
            decisions=[
                {
                    "instance_key": "media_placement:hero",
                    "action": "suppress",
                    "rationale": "Await approved media.",
                }
            ],
            decided_by="History Operator",
        )

        updated = update_operator_composition_decisions(
            session,
            composition.id,
            payload,
        )
        session.refresh(composition)
        history = list_composition_revisions(session, composition.id)
        assert updated.composition_version == 2
        assert len(history) == 2
        assert composition.generated_components == original_components
        assert composition.source_snapshot == original_snapshot
        assert composition.source_hash == original_source_hash
        assert canonical_utc_timestamp(composition.generated_at) == canonical_utc_timestamp(
            original_generated_at
        )
        assert history[1].generated_components == original_components
        assert history[1].source_snapshot == original_snapshot
        assert history[1].source_hash == original_source_hash
        assert canonical_utc_timestamp(history[1].generated_at) == canonical_utc_timestamp(
            original_generated_at
        )
        assert history[1].record_source == "operator_decision"
        assert history[1].decided_at is not None

        repeated = update_operator_composition_decisions(
            session,
            composition.id,
            payload,
        )
        assert repeated.composition_version == 2
        assert len(list_composition_revisions(session, composition.id)) == 2


def test_current_resolution_rejects_tampered_evidence_and_non_tip_head() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, pages = _scope(session, suffix="history-tamper")
        assert refresh_site_plan_compositions(session, plan.id).blocked == []
        composition = _one_composition(session, pages[0][1].id)
        revision = current_composition_revision(session, composition)
        revision.recorded_by = "tampered actor"
        session.add(revision)
        session.flush()

        with pytest.raises(PageCompositionHistoryError, match="immutable hash"):
            current_composition_revision(session, composition)

        session.rollback()
        composition = _one_composition(session, pages[0][1].id)
        initial = current_composition_revision(session, composition)
        business = session.get(Business, pages[0][1].business_id)
        assert business is not None
        business.phone = "407-555-0188"
        session.add(business)
        session.commit()
        assert refresh_site_plan_compositions(session, plan.id).blocked == []
        session.refresh(composition)
        tip = current_composition_revision(session, composition)
        assert tip.composition_version == initial.composition_version + 1

        composition.composition_version = initial.composition_version
        composition.generated_components = deepcopy(initial.generated_components)
        composition.operator_decisions = deepcopy(initial.operator_decisions)
        composition.source_snapshot = deepcopy(initial.source_snapshot)
        composition.source_hash = initial.source_hash
        composition.generated_at = initial.generated_at
        composition.decided_by = initial.decided_by
        composition.decided_at = initial.decided_at
        session.add(composition)
        session.flush()

        with pytest.raises(PageCompositionHistoryError, match="unique lineage tip"):
            current_composition_revision(session, composition)


def test_stale_operator_update_does_not_append_history() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, pages = _scope(session, suffix="history-stale-operator")
        assert refresh_site_plan_compositions(session, plan.id).blocked == []
        composition = _one_composition(session, pages[0][1].id)
        version = composition.composition_version
        history_count = len(list_composition_revisions(session, composition.id))
        business = session.get(Business, pages[0][1].business_id)
        assert business is not None
        business.phone = "407-555-0177"
        session.add(business)
        session.commit()

        with pytest.raises(PageCompositionError, match="stale"):
            update_operator_composition_decisions(
                session,
                composition.id,
                PageCompositionDecisionUpdate(
                    decisions=[
                        {
                            "instance_key": "media_placement:hero",
                            "action": "suppress",
                        }
                    ],
                    decided_by="History Operator",
                ),
            )

        session.rollback()
        session.refresh(composition)
        assert composition.composition_version == version
        assert len(list_composition_revisions(session, composition.id)) == history_count


def test_batch_failure_rolls_back_heads_and_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, pages = _scope(session, suffix="history-rollback")
        original_compose = composition_service._compose

        def fail_second(session_: Session, plan_, planned_):
            if planned_.id == pages[1][0].id:
                raise PageCompositionError("injected composition failure")
            return original_compose(session_, plan_, planned_)

        monkeypatch.setattr(composition_service, "_compose", fail_second)
        result = refresh_site_plan_compositions(session, plan.id)

        assert result.created == 0
        assert result.refreshed == 0
        assert result.unchanged == 0
        assert result.blocked == [
            {
                "planned_page_id": pages[1][0].id,
                "reason": "injected composition failure",
            }
        ]
        assert session.exec(select(PageComposition)).all() == []
        assert session.exec(select(PageCompositionRevision)).all() == []


def test_refresh_resolves_return_payload_before_commit_source_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, pages = _scope(session, suffix="history-return-race")
        target_page_id = pages[0][1].id
        original_commit = session.commit
        original_read = composition_service._read
        commit_started = False
        read_after_commit: list[bool] = []

        def tracked_read(*args, **kwargs):
            read_after_commit.append(commit_started)
            return original_read(*args, **kwargs)

        def commit_then_change_source() -> None:
            nonlocal commit_started
            commit_started = True
            original_commit()
            generated = session.get(GeneratedPage, target_page_id)
            assert generated is not None
            changed_draft = deepcopy(generated.draft_content or {})
            changed_draft["intro"] = f"{changed_draft['intro']} Concurrent update."
            generated.draft_content = changed_draft
            session.add(generated)
            original_commit()

        monkeypatch.setattr(composition_service, "_read", tracked_read)
        monkeypatch.setattr(session, "commit", commit_then_change_source)

        result = refresh_site_plan_compositions(session, plan.id)

        assert result.created == 2 and result.blocked == []
        assert read_after_commit == [False, False]
        with pytest.raises(PageCompositionError, match="stale"):
            composition_service.read_composition_for_generated_page(
                session,
                target_page_id,
            )


def test_refresh_result_read_failure_rolls_back_heads_and_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, _ = _scope(session, suffix="history-read-rollback")

        def fail_result_read(*_args, **_kwargs):
            raise PageCompositionError("injected result read failure")

        monkeypatch.setattr(composition_service, "_read", fail_result_read)
        with pytest.raises(PageCompositionError, match="injected result read failure"):
            refresh_site_plan_compositions(session, plan.id)

        assert session.exec(select(PageComposition)).all() == []
        assert session.exec(select(PageCompositionRevision)).all() == []


def test_generated_page_revision_anchor_rejects_null_older_and_cross_page() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, pages = _scope(session, suffix="history-generated-revision")
        target_page = pages[0][1]
        other_page = pages[1][1]
        target_hash = canonical_payload_hash(target_page.draft_content or {})
        other_hash = canonical_payload_hash(other_page.draft_content or {})
        created_at = datetime.now(UTC) - timedelta(minutes=2)
        older = GeneratedPageRevision(
            generated_page_id=target_page.id,
            created_at=created_at,
            created_by="History Test",
            reason="older matching revision",
            draft_hash_before="0" * 64,
            draft_hash_after=target_hash,
            draft_content_before={},
            draft_content_after=target_page.draft_content or {},
            changed_fields=["draft_content"],
        )
        latest = GeneratedPageRevision(
            generated_page_id=target_page.id,
            created_at=created_at + timedelta(seconds=1),
            created_by="History Test",
            reason="latest matching revision",
            draft_hash_before=target_hash,
            draft_hash_after=target_hash,
            draft_content_before=target_page.draft_content or {},
            draft_content_after=target_page.draft_content or {},
            changed_fields=[],
        )
        cross_page = GeneratedPageRevision(
            generated_page_id=other_page.id,
            created_at=created_at + timedelta(seconds=1),
            created_by="History Test",
            reason="cross-page revision",
            draft_hash_before="0" * 64,
            draft_hash_after=other_hash,
            draft_content_before={},
            draft_content_after=other_page.draft_content or {},
            changed_fields=["draft_content"],
        )
        session.add(older)
        session.add(latest)
        session.add(cross_page)
        session.commit()
        assert refresh_site_plan_compositions(session, plan.id).blocked == []
        composition = _one_composition(session, target_page.id)
        head = current_composition_revision(session, composition)
        assert head.generated_page_revision_id == latest.id

        for invalid_id in (None, older.id, cross_page.id):
            head = current_composition_revision(session, composition)
            head.generated_page_revision_id = invalid_id
            values = head.model_dump(mode="python")
            head.revision_hash = composition_revision_hash(values)
            session.add(head)
            session.flush()
            with pytest.raises(
                PageCompositionHistoryError,
                match="exact Generated Page revision binding",
            ):
                current_composition_revision(session, composition)
            session.rollback()
            composition = _one_composition(session, target_page.id)


def test_operator_successor_keeps_derivation_time_revision_eligibility() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, pages = _scope(session, suffix="history-decision-cutoff")
        assert refresh_site_plan_compositions(session, plan.id).blocked == []
        page = pages[0][1]
        composition = _one_composition(session, page.id)
        generated_at = composition.generated_at
        generated_at_utc = (
            generated_at.replace(tzinfo=UTC)
            if generated_at.tzinfo is None
            else generated_at.astimezone(UTC)
        )
        later_page_revision = GeneratedPageRevision(
            generated_page_id=page.id,
            created_at=generated_at_utc + timedelta(microseconds=1),
            created_by="History Test",
            reason="Created after composition derivation",
            draft_hash_before=composition.source_snapshot["draft_hash"],
            draft_hash_after=composition.source_snapshot["draft_hash"],
            draft_content_before=page.draft_content or {},
            draft_content_after=page.draft_content or {},
            changed_fields=[],
        )
        session.add(later_page_revision)
        session.commit()

        update_operator_composition_decisions(
            session,
            composition.id,
            PageCompositionDecisionUpdate(
                decisions=[
                    {
                        "instance_key": "media_placement:hero",
                        "action": "suppress",
                    }
                ],
                decided_by="History Operator",
            ),
        )
        history = list_composition_revisions(session, composition.id)

        assert [item.generated_page_revision_id for item in history] == [None, None]
        assert all(
            canonical_utc_timestamp(item.generated_at)
            == canonical_utc_timestamp(generated_at)
            for item in history
        )
        assert canonical_utc_timestamp(history[1].recorded_at) > canonical_utc_timestamp(
            later_page_revision.created_at
        )


def test_history_routes_list_and_read_only_raw_immutable_evidence() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        _, plan, pages = _scope(session, suffix="history-routes")
        assert refresh_site_plan_compositions(session, plan.id).blocked == []
        composition = _one_composition(session, pages[0][1].id)
        update_operator_composition_decisions(
            session,
            composition.id,
            PageCompositionDecisionUpdate(
                decisions=[
                    {
                        "instance_key": "media_placement:hero",
                        "action": "suppress",
                    }
                ],
                decided_by="History Route Operator",
            ),
        )

        test_app = FastAPI()
        test_app.include_router(site_plan_router)

        def override_session():
            yield session

        test_app.dependency_overrides[get_session] = override_session
        with TestClient(test_app) as client:
            listed = client.get(
                f"/site-plans/compositions/{composition.id}/revisions"
            )
            historical = client.get(
                f"/site-plans/compositions/{composition.id}/revisions/1"
            )
            missing = client.get(
                f"/site-plans/compositions/{composition.id}/revisions/999"
            )

        assert listed.status_code == 200
        assert [item["composition_version"] for item in listed.json()] == [1, 2]
        assert historical.status_code == 200
        assert historical.json()["composition_version"] == 1
        assert historical.json()["is_head_revision"] is False
        assert missing.status_code == 409
        assert "does not resolve exactly once" in missing.json()["detail"]
        for payload in [*listed.json(), historical.json()]:
            assert "effective_components" not in payload
            assert "resolved_theme" not in payload
            assert "validation_errors" not in payload


def test_historical_reads_and_rehashed_scope_substitution_fail_closed() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_registry(session)
        website, plan, pages = _scope(session, suffix="history-scope-owner")
        other_website, _, other_pages = _scope(
            session,
            suffix="history-scope-other",
        )
        assert refresh_site_plan_compositions(session, plan.id).blocked == []
        composition = _one_composition(session, pages[0][1].id)

        with pytest.raises(
            PageCompositionHistoryError,
            match="Generated Page boundary",
        ):
            read_composition_revision(
                session,
                composition.id,
                1,
                generated_page_id=other_pages[0][1].id,
            )
        with pytest.raises(
            PageCompositionHistoryError,
            match="Website boundary",
        ):
            read_composition_revision(
                session,
                composition.id,
                1,
                website_id=other_website.id,
            )

        substitutions = (
            ("website_id", other_website.id),
            ("planned_page_id", other_pages[0][0].id),
            ("generated_page_id", other_pages[0][1].id),
        )
        for field, value in substitutions:
            revision = current_composition_revision(session, composition)
            setattr(revision, field, value)
            revision.revision_hash = composition_revision_hash(
                revision.model_dump(mode="python")
            )
            session.add(revision)
            session.flush()
            with pytest.raises(
                PageCompositionHistoryError,
                match="exact ownership boundary",
            ):
                read_composition_revision(session, composition.id, 1)
            session.rollback()
            composition = _one_composition(session, pages[0][1].id)
