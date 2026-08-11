from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import os
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlmodel import Session, SQLModel, select

from app.models import (
    GeneratedPage,
    NavigationSet,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    ScopedMediaAuthorization,
    SitePlan,
)
from app.schemas.page_media_planning import PageMediaBatchAssignmentRequest
from app.services import page_composition as composition_service
from app.services.page_composition import refresh_site_plan_compositions
from app.services.page_media_planning import (
    PageMediaPlanningError,
    assign_media_batch_to_requirements,
)
from app.services.site_connections import ensure_site_connection_foundation
from tests.test_page_composition import _seed_registry
from tests.test_page_media_batch_assignment import _prepare_batch


POSTGRES_ADMIN_URL_ENV = "ATLAS_DISPOSABLE_POSTGRES_ADMIN_URL"
DISPOSABLE_DATABASE_PREFIX = "atlas_batch_concurrency_test_"
LOCAL_POSTGRES_HOSTS = {"127.0.0.1", "localhost", "postgres"}


class _FirstWriteLockBarrierSession(Session):
    """Synchronize workers immediately before their first SELECT FOR UPDATE."""

    def __init__(self, bind: Engine, barrier: Barrier) -> None:
        super().__init__(bind)
        self._first_write_lock_barrier = barrier
        self._first_write_lock_seen = False

    def exec(self, statement: Any, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        if (
            not self._first_write_lock_seen
            and getattr(statement, "_for_update_arg", None) is not None
        ):
            self._first_write_lock_seen = True
            self._first_write_lock_barrier.wait(timeout=15)
        return super().exec(statement, *args, **kwargs)


@pytest.fixture
def disposable_postgres_engine() -> Engine:
    admin_url_value = os.getenv(POSTGRES_ADMIN_URL_ENV)
    if not admin_url_value:
        pytest.skip(
            f"Set {POSTGRES_ADMIN_URL_ENV} to an explicit local PostgreSQL "
            "administrative URL to run the real concurrency test."
        )

    admin_url = make_url(admin_url_value)
    if admin_url.get_backend_name() != "postgresql":
        pytest.fail("The disposable concurrency test requires PostgreSQL.")
    if admin_url.host not in LOCAL_POSTGRES_HOSTS:
        pytest.fail(
            "The disposable concurrency test refuses a non-local PostgreSQL host."
        )
    if (admin_url.database or "").lower() == "atlas":
        pytest.fail(
            "The disposable concurrency test refuses the active Atlas database."
        )

    database_name = f"{DISPOSABLE_DATABASE_PREFIX}{uuid4().hex}"
    assert database_name != "atlas"
    target_url = admin_url.set(database=database_name)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    target_engine: Engine | None = None
    try:
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            ).scalar_one_or_none()
            assert exists is None
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')

        target_engine = create_engine(target_url, pool_pre_ping=True)
        SQLModel.metadata.create_all(target_engine)
        yield target_engine
    finally:
        if target_engine is not None:
            target_engine.dispose(close=True)
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": database_name},
            )
            connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}"'
            )
            remaining = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            ).scalar_one_or_none()
            assert remaining is None
        admin_engine.dispose(close=True)


def test_concurrent_conflicting_batches_have_one_winner_and_no_partial_result(
    disposable_postgres_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = disposable_postgres_engine
    with Session(engine) as setup_session:
        fixture = _prepare_batch(
            setup_session,
            monkeypatch,
            tmp_path,
            suffix="postgres-concurrent-batch",
        )
        plan_id = fixture.plan.id
        planned_page_id = fixture.planned.id
        composition_id = fixture.composition.id
        payload_data = fixture.payload.model_dump(mode="json")
        initial_composition_version = fixture.composition.composition_version
        initial_composition_source_hash = fixture.composition.source_hash

    assert plan_id is not None
    assert planned_page_id is not None
    assert composition_id is not None
    start_barrier = Barrier(2)

    def run_batch() -> tuple[str, str]:
        payload = PageMediaBatchAssignmentRequest.model_validate(payload_data)
        with _FirstWriteLockBarrierSession(engine, start_barrier) as session:
            try:
                result = assign_media_batch_to_requirements(
                    session,
                    plan_id,
                    payload,
                )
                return "success", result.composition_status
            except PageMediaPlanningError as exc:
                return "rejected", str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: run_batch(), range(2)))

    assert [status for status, _detail in outcomes].count("success") == 1
    assert [status for status, _detail in outcomes].count("rejected") == 1
    winner = next(detail for status, detail in outcomes if status == "success")
    loser = next(detail for status, detail in outcomes if status == "rejected")
    assert winner == "stale"
    assert "Starting Page Composition is stale" in loser

    with Session(engine) as verification_session:
        assignments = list(
            verification_session.exec(
                select(PageImageAssignment)
                .where(PageImageAssignment.planned_page_id == planned_page_id)
                .order_by(PageImageAssignment.media_requirement_id)
            ).all()
        )
        assert len(assignments) == len(payload_data["assignments"])
        assert all(row.status == "active" for row in assignments)
        assert len({row.media_requirement_id for row in assignments}) == len(assignments)
        assert all(row.assignment_version == 1 for row in assignments)

        composition = verification_session.get(PageComposition, composition_id)
        assert composition is not None
        assert composition.status == "stale"
        assert composition.composition_version == initial_composition_version
        assert composition.source_hash == initial_composition_source_hash

        authorization_history = list(
            verification_session.exec(
                select(ScopedMediaAuthorization).where(
                    ScopedMediaAuthorization.planned_page_id == planned_page_id
                )
            ).all()
        )
        assert len(authorization_history) == 2 * len(assignments)
        assert sum(
            row.lifecycle_status == "current" for row in authorization_history
        ) == len(assignments)
        assert sum(
            row.lifecycle_status == "superseded" for row in authorization_history
        ) == len(assignments)
        assert all(
            row.page_image_assignment_id is not None
            for row in authorization_history
            if row.lifecycle_status == "current"
        )


def test_concurrent_batch_and_composition_refresh_never_publish_a_pre_batch_snapshot(
    disposable_postgres_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = disposable_postgres_engine
    with Session(engine) as setup_session:
        _seed_registry(setup_session)
        fixture = _prepare_batch(
            setup_session,
            monkeypatch,
            tmp_path,
            suffix="postgres-batch-refresh",
        )
        ensure_site_connection_foundation(setup_session, fixture.plan)
        decided_at = datetime(2026, 8, 11, 16, 0, tzinfo=UTC)
        for navigation_set in setup_session.exec(
            select(NavigationSet).where(
                NavigationSet.site_plan_id == fixture.plan.id
            )
        ).all():
            navigation_set.status = "active"
            navigation_set.rationale = (
                "Approve the disposable concurrency-test navigation contract."
            )
            navigation_set.decided_by = "Concurrency Test Operator"
            navigation_set.decision_version = 1
            navigation_set.decided_at = decided_at
            setup_session.add(navigation_set)
        setup_session.commit()
        initial_refresh = refresh_site_plan_compositions(
            setup_session,
            fixture.plan.id,
        )
        assert initial_refresh.blocked == []
        refreshed_composition = setup_session.get(
            PageComposition,
            fixture.composition.id,
        )
        assert refreshed_composition is not None
        assert refreshed_composition.status == "current"
        payload = fixture.payload.model_copy(
            update={
                "expected_composition_version": (
                    refreshed_composition.composition_version
                ),
                "expected_composition_source_hash": (
                    refreshed_composition.source_hash
                ),
            },
            deep=True,
        )
        plan_id = fixture.plan.id
        planned_page_id = fixture.planned.id
        generated_page_id = fixture.generated.id
        composition_id = fixture.composition.id
        payload_data = payload.model_dump(mode="json")

    assert plan_id is not None
    assert planned_page_id is not None
    assert generated_page_id is not None
    assert composition_id is not None
    start_barrier = Barrier(2)

    def run_batch() -> str:
        payload = PageMediaBatchAssignmentRequest.model_validate(payload_data)
        with _FirstWriteLockBarrierSession(engine, start_barrier) as session:
            result = assign_media_batch_to_requirements(session, plan_id, payload)
            return result.composition_status

    def run_refresh() -> tuple[int, int, int, tuple[str, ...]]:
        with _FirstWriteLockBarrierSession(engine, start_barrier) as session:
            result = refresh_site_plan_compositions(session, plan_id)
            return (
                result.created,
                result.refreshed,
                result.unchanged,
                tuple(str(item.get("reason") or "") for item in result.blocked),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        batch_future = executor.submit(run_batch)
        refresh_future = executor.submit(run_refresh)
        batch_status = batch_future.result(timeout=30)
        refresh_counts = refresh_future.result(timeout=30)

    assert batch_status == "stale"
    assert refresh_counts in {(0, 1, 0, ()), (0, 0, 1, ())}

    with Session(engine) as verification_session:
        plan = verification_session.get(SitePlan, plan_id)
        planned = verification_session.get(PlannedPage, planned_page_id)
        generated = verification_session.get(GeneratedPage, generated_page_id)
        composition = verification_session.get(PageComposition, composition_id)
        assert plan is not None
        assert planned is not None
        assert generated is not None
        assert composition is not None

        assignments = list(
            verification_session.exec(
                select(PageImageAssignment)
                .where(PageImageAssignment.planned_page_id == planned_page_id)
                .order_by(PageImageAssignment.media_requirement_id)
            ).all()
        )
        assignment_ids = {row.id for row in assignments}
        assert len(assignments) == len(payload_data["assignments"])
        assert None not in assignment_ids

        live_snapshot = composition_service._source_snapshot(
            verification_session,
            plan,
            planned,
            generated,
        )
        live_hash = composition_service._hash(live_snapshot)
        live_assignment_ids = {
            row["id"] for row in live_snapshot["media_assignments"]
        }
        assert live_assignment_ids == assignment_ids

        if composition.status == "current":
            assert refresh_counts == (0, 1, 0, ())
            assert composition.source_hash == live_hash
            assert composition.source_snapshot == live_snapshot
            current_read = composition_service._read(
                verification_session,
                composition,
                require_current=True,
            )
            assert current_read.status == "current"
            assert current_read.validation_errors == []
            rendered_assignment_ids = {
                component.input_bindings.get("page_image_assignment_id")
                for component in current_read.effective_components
                if component.component_key == "media_placement"
            }
            assert rendered_assignment_ids == assignment_ids
        else:
            assert composition.status == "stale"
            assert refresh_counts == (0, 0, 1, ())
            assert composition.source_hash != live_hash
            stale_read = composition_service._read(
                verification_session,
                composition,
                require_current=False,
            )
            assert stale_read.status == "stale"
            assert any(
                "authoritative source changed" in error
                for error in stale_read.validation_errors
            )
            with pytest.raises(
                composition_service.PageCompositionError,
                match="authoritative source changed",
            ):
                composition_service._read(
                    verification_session,
                    composition,
                    require_current=True,
                )
