from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlmodel import Session

from app.core.config import get_settings
from app.models import (
    Business,
    GeneratedPage,
    GeneratedPageQAResult,
    PlannedPage,
    SitePlan,
    Website,
)
from app.services.page_qa import historical_qa_payload_hash


BACKEND = Path(__file__).parents[1]
REVISION_0042 = "20260809_0042"
REVISION_0043 = "20260809_0043"
REVISION_0044 = "20260810_0044"
REVISION_0045 = "20260813_0045"
TABLE = "generatedpageqaresult"
CURRENT_INDEX = "uq_generatedpageqaresult_current_page"


def _config(monkeypatch: pytest.MonkeyPatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def _migration_module():
    path = (
        BACKEND
        / "alembic"
        / "versions"
        / "20260809_0043_durable_generated_page_qa_results.py"
    )
    spec = importlib.util.spec_from_file_location(
        "durable_page_qa_migration_0043",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _replace_model_created_table_ddl(
    engine,
    *,
    old: str,
    new: str,
) -> None:
    """Recreate only the empty pre-created table with one bad clause."""

    with engine.begin() as connection:
        ddl = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = :table_name"
            ),
            {"table_name": TABLE},
        ).scalar_one()
        assert ddl.count(old) == 1
        connection.execute(text(f"DROP TABLE {TABLE}"))
        connection.execute(text(ddl.replace(old, new, 1)))
    for index in sorted(
        GeneratedPageQAResult.__table__.indexes,
        key=lambda candidate: candidate.name or "",
    ):
        index.create(bind=engine)


def _assert_failed_adoption_remains_at_0042(engine) -> None:
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0042
        assert (
            connection.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
            == 0
        )


def _seed_0042_page(
    engine,
    *,
    qa_result: dict | None,
) -> tuple[int, int, int, int]:
    with Session(engine) as session:
        business = Business(
            company_name="Durable QA Migration Company",
            business_type="Local service business",
            phone="407-555-0100",
            state="FL",
        )
        session.add(business)
        session.flush()
        website = Website(
            business_id=business.id,
            website_name="Durable QA Migration Website",
            domain="durable-qa-migration.example.test",
            public_url="https://durable-qa-migration.example.test",
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
        page = GeneratedPage(
            id=41,
            business_id=business.id,
            website_id=website.id,
            page_type="informational",
            page_title="Migration Page",
            page_slug="migration-page",
            draft_content={"schema_version": "planned-page-draft-v1"},
            qa_status="ready" if qa_result else "not_run",
            qa_result=qa_result,
            qa_checked_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
            if qa_result
            else None,
        )
        session.add(page)
        session.flush()
        planned = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type="informational",
            working_name="Migration Page",
            intended_slug="migration-page",
            generated_page_id=page.id,
        )
        session.add(planned)
        session.commit()
        return website.id or 0, plan.id or 0, planned.id or 0, page.id or 0


def test_0043_clean_upgrade_creates_empty_durable_qa_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "durable-qa-clean.sqlite3"
    config = _config(monkeypatch, database)

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    assert TABLE in inspector.get_table_names()
    assert "uq_generatedpageqaresult_current_page" in {
        item["name"] for item in inspector.get_indexes(TABLE)
    }
    with engine.connect() as connection:
        assert (
            connection.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
            == 0
        )
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260817_0047"
    engine.dispose()
    get_settings.cache_clear()


def test_0043_adopts_exact_empty_model_created_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "durable-qa-model-created.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0042)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    _seed_0042_page(
        engine,
        qa_result={"page_id": 1, "readiness_status": "ready"},
    )
    GeneratedPageQAResult.__table__.create(engine)
    assert TABLE in inspect(engine).get_table_names()
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.connect() as connection:
        assert (
            connection.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
            == 1
        )
        assert connection.execute(
            text(f"SELECT lifecycle_status FROM {TABLE}")
        ).scalar_one() == "historical_unbound"
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260817_0047"
    inspector = inspect(engine)
    assert "uq_generatedpageqaresult_current_page" in {
        item["name"] for item in inspector.get_indexes(TABLE)
    }
    engine.dispose()
    get_settings.cache_clear()


def test_0043_refuses_same_named_nonunique_current_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "durable-qa-malformed-current-index.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0042)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    GeneratedPageQAResult.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(text(f"DROP INDEX {CURRENT_INDEX}"))
        connection.execute(
            text(
                f"CREATE INDEX {CURRENT_INDEX} ON {TABLE} (generated_page_id)"
            )
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="malformed current-result index"):
        command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0042
    malformed = next(
        item
        for item in inspect(engine).get_indexes(TABLE)
        if item["name"] == CURRENT_INDEX
    )
    assert bool(malformed["unique"]) is False
    engine.dispose()
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("old", "new", "constraint_name"),
    [
        (
            "supersedes_qa_result_id IS NULL OR supersedes_qa_result_id != id",
            "supersedes_qa_result_id IS NULL OR supersedes_qa_result_id = id",
            "ck_generatedpageqaresult_not_self_superseding",
        ),
        (
            "length(trim(qa_algorithm_key)) > 0",
            "length(trim(qa_algorithm_key)) >= 0",
            "ck_generatedpageqaresult_bound_evidence",
        ),
    ],
)
def test_0043_refuses_semantically_malformed_same_named_check_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    old: str,
    new: str,
    constraint_name: str,
) -> None:
    database = tmp_path / f"durable-qa-malformed-{constraint_name}.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0042)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    GeneratedPageQAResult.__table__.create(engine)
    _replace_model_created_table_ddl(engine, old=old, new=new)
    engine.dispose()

    with pytest.raises(RuntimeError, match=rf"malformed {constraint_name} CHECK"):
        command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    _assert_failed_adoption_remains_at_0042(engine)
    engine.dispose()
    get_settings.cache_clear()


def test_0043_refuses_malformed_foreign_key_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "durable-qa-malformed-foreign-key.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0042)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    GeneratedPageQAResult.__table__.create(engine)
    _replace_model_created_table_ddl(
        engine,
        old="FOREIGN KEY(website_id) REFERENCES website (id)",
        new="FOREIGN KEY(website_id) REFERENCES website (id) ON DELETE CASCADE",
    )
    engine.dispose()

    with pytest.raises(RuntimeError, match="incompatible foreign key contract"):
        command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    _assert_failed_adoption_remains_at_0042(engine)
    engine.dispose()
    get_settings.cache_clear()


def test_0043_foreign_key_contract_rejects_schema_options_and_duplicates() -> None:
    migration = _migration_module()
    exact = [
        {
            "constrained_columns": [column],
            "referred_schema": None,
            "referred_table": referred_table,
            "referred_columns": [referred_column],
            "options": {},
        }
        for column, referred_table, referred_column in sorted(
            migration.EXPECTED_FOREIGN_KEYS
        )
    ]

    class ForeignKeyInspector:
        def __init__(self, foreign_keys):
            self.foreign_keys = foreign_keys

        def get_foreign_keys(self, _table):
            return self.foreign_keys

    migration._validate_foreign_key_contracts(ForeignKeyInspector(exact))

    altered_schema = [dict(item) for item in exact]
    altered_schema[0]["referred_schema"] = "public"
    with pytest.raises(RuntimeError, match="incompatible foreign key contract"):
        migration._validate_foreign_key_contracts(
            ForeignKeyInspector(altered_schema)
        )

    altered_options = [dict(item) for item in exact]
    altered_options[0]["options"] = {"onupdate": "CASCADE"}
    with pytest.raises(RuntimeError, match="incompatible foreign key contract"):
        migration._validate_foreign_key_contracts(
            ForeignKeyInspector(altered_options)
        )

    with pytest.raises(RuntimeError, match="incompatible foreign key contract"):
        migration._validate_foreign_key_contracts(
            ForeignKeyInspector([*exact, dict(exact[0])])
        )


@pytest.mark.parametrize(
    "unexpected_check",
    [
        "CHECK (result_hash IS NOT NULL)",
        (
            "CONSTRAINT ck_generatedpageqaresult_passed_count "
            "CHECK (passed_count IS NULL OR passed_count >= 0)"
        ),
    ],
)
def test_0043_refuses_unnamed_or_duplicate_check_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    unexpected_check: str,
) -> None:
    database = tmp_path / "durable-qa-unexpected-check.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0042)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    GeneratedPageQAResult.__table__.create(engine)
    identity_constraint = (
        "CONSTRAINT uq_generatedpageqaresult_page_result_hash "
        "UNIQUE (generated_page_id, result_hash)"
    )
    _replace_model_created_table_ddl(
        engine,
        old=identity_constraint,
        new=f"{unexpected_check}, {identity_constraint}",
    )
    engine.dispose()

    with pytest.raises(RuntimeError, match="unexpected CHECK contract"):
        command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    _assert_failed_adoption_remains_at_0042(engine)
    engine.dispose()
    get_settings.cache_clear()


def test_0043_refuses_partial_predicate_on_noncurrent_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "durable-qa-malformed-noncurrent-index.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0042)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    GeneratedPageQAResult.__table__.create(engine)
    index_name = "ix_generatedpageqaresult_website_id"
    with engine.begin() as connection:
        connection.execute(text(f"DROP INDEX {index_name}"))
        connection.execute(
            text(
                f"CREATE INDEX {index_name} ON {TABLE} (website_id) "
                "WHERE website_id IS NOT NULL"
            )
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match=rf"malformed {index_name} index"):
        command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    _assert_failed_adoption_remains_at_0042(engine)
    malformed = next(
        item
        for item in inspect(engine).get_indexes(TABLE)
        if item["name"] == index_name
    )
    assert str(malformed["dialect_options"]["sqlite_where"]) == (
        "website_id IS NOT NULL"
    )
    engine.dispose()
    get_settings.cache_clear()


def test_0043_refuses_to_adopt_nonempty_model_created_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "durable-qa-model-created-nonempty.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0042)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    _, _, _, page_id = _seed_0042_page(engine, qa_result=None)
    GeneratedPageQAResult.__table__.create(engine)
    now = datetime(2026, 8, 9, 12, 0)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                INSERT INTO {TABLE} (
                    created_at, updated_at, generated_page_id, lifecycle_status,
                    result_hash, historical_payload
                ) VALUES (
                    :created_at, :updated_at, :generated_page_id,
                    'historical_unbound', :result_hash, :historical_payload
                )
                """
            ),
            {
                "created_at": now,
                "updated_at": now,
                "generated_page_id": page_id,
                "result_hash": "a" * 64,
                "historical_payload": json.dumps({"page_id": page_id}),
            },
        )
    engine.dispose()

    with pytest.raises(
        RuntimeError,
        match="not the exact empty model-created schema",
    ):
        command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0042
        assert (
            connection.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
            == 1
        )
    engine.dispose()
    get_settings.cache_clear()


def test_0043_backfills_raw_legacy_payload_as_unbound_history_without_current_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "durable-qa-populated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0042)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    legacy_payload = {
        "page_id": 1,
        "readiness_status": "ready",
        "passed_count": 3,
        "warning_count": 0,
        "failed_count": 0,
        "checks": [{"key": "legacy", "status": "pass"}],
        "nested": {"preserve": [True, None, "exact"]},
    }
    website_id, plan_id, planned_id, page_id = _seed_0042_page(
        engine,
        qa_result=legacy_payload,
    )
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.connect() as connection:
        row = connection.execute(
            text(f"SELECT * FROM {TABLE} WHERE generated_page_id = :page_id"),
            {"page_id": page_id},
        ).mappings().one()
        preserved = connection.execute(
            text("SELECT qa_result FROM generatedpage WHERE id = :page_id"),
            {"page_id": page_id},
        ).scalar_one()
        assert row["website_id"] == website_id
        assert row["site_plan_id"] == plan_id
        assert row["planned_page_id"] == planned_id
        assert row["lifecycle_status"] == "historical_unbound"
        assert row["result_hash"] == historical_qa_payload_hash(legacy_payload)
        assert row["content_hash"] is None
        assert row["source_hash"] is None
        assert connection.execute(
            text(
                f"SELECT COUNT(*) FROM {TABLE} "
                "WHERE lifecycle_status = 'current'"
            )
        ).scalar_one() == 0
        assert json.loads(row["historical_payload"]) == legacy_payload
        assert json.loads(preserved) == legacy_payload
        assert legacy_payload["page_id"] == 1
        assert page_id == 41
    engine.dispose()
    get_settings.cache_clear()


def test_0043_downgrade_succeeds_when_only_unbound_history_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "durable-qa-safe-downgrade.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0042)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    legacy_payload = {"page_id": 1, "readiness_status": "blocked"}
    _seed_0042_page(engine, qa_result=legacy_payload)
    engine.dispose()
    command.upgrade(config, REVISION_0045)

    command.downgrade(config, REVISION_0042)

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0042
        preserved = connection.execute(
            text("SELECT qa_result FROM generatedpage WHERE id = 41")
        ).scalar_one()
        assert json.loads(preserved) == legacy_payload
    engine.dispose()
    get_settings.cache_clear()


@pytest.mark.parametrize("lifecycle_status", ["current", "superseded"])
def test_0043_downgrade_refuses_to_drop_bound_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lifecycle_status: str,
) -> None:
    database = tmp_path / f"durable-qa-blocked-{lifecycle_status}.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0042)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    website_id, plan_id, planned_id, page_id = _seed_0042_page(
        engine,
        qa_result=None,
    )
    engine.dispose()
    command.upgrade(config, REVISION_0045)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    now = datetime(2026, 8, 9, 12, 0)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                INSERT INTO {TABLE} (
                    created_at, updated_at, website_id, site_plan_id,
                    planned_page_id, generated_page_id, content_hash, source_hash,
                    qa_algorithm_key, qa_algorithm_version, qa_ruleset_key,
                    qa_ruleset_version, qa_ruleset_hash, readiness_status,
                    passed_count, warning_count, failed_count, check_payload,
                    evaluated_at, lifecycle_status, result_hash, historical_payload
                ) VALUES (
                    :created_at, :updated_at, :website_id, :site_plan_id,
                    :planned_page_id, :generated_page_id, :content_hash, :source_hash,
                    :algorithm_key, :algorithm_version, :ruleset_key,
                    :ruleset_version, :ruleset_hash, :readiness_status,
                    1, 0, 0, :check_payload,
                    :evaluated_at, :lifecycle_status, :result_hash, NULL
                )
                """
            ),
            {
                "created_at": now,
                "updated_at": now,
                "website_id": website_id,
                "site_plan_id": plan_id,
                "planned_page_id": planned_id,
                "generated_page_id": page_id,
                "content_hash": "a" * 64,
                "source_hash": "b" * 64,
                "algorithm_key": "atlas-page-qa",
                "algorithm_version": "2",
                "ruleset_key": "atlas-page-qa-rules",
                "ruleset_version": "2",
                "ruleset_hash": "c" * 64,
                "readiness_status": "ready",
                "check_payload": "[]",
                "evaluated_at": now,
                "lifecycle_status": lifecycle_status,
                "result_hash": "d" * 64,
            },
        )
    engine.dispose()

    with pytest.raises(
        RuntimeError,
        match="durable current or superseded QA results exist",
    ):
        command.downgrade(config, REVISION_0042)

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert TABLE in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0043
        assert (
            connection.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
            == 1
        )
    engine.dispose()
    get_settings.cache_clear()


def test_0043_current_index_declares_matching_predicates() -> None:
    migration = _migration_module()
    calls: list[tuple[str, dict]] = []

    class CaptureOperations:
        @staticmethod
        def create_index(name, _table, _columns, **kwargs):
            calls.append((name, kwargs))

    migration.op = CaptureOperations()
    migration._create_indexes()
    _, kwargs = next(
        call for call in calls if call[0] == migration.CURRENT_INDEX
    )

    assert str(kwargs["sqlite_where"]) == migration.CURRENT_PREDICATE
    assert str(kwargs["postgresql_where"]) == migration.CURRENT_PREDICATE
    assert migration.down_revision == REVISION_0042


def test_0043_accepts_equivalent_postgresql_check_rendering() -> None:
    migration = _migration_module()
    checks = dict(migration.CHECK_CONTRACTS)
    checks["ck_generatedpageqaresult_lifecycle"] = (
        "lifecycle_status::text = ANY "
        "(ARRAY['current'::character varying, "
        "'superseded'::character varying, "
        "'historical_unbound'::character varying]::text[])"
    )
    checks["ck_generatedpageqaresult_readiness"] = (
        "readiness_status IS NULL OR (readiness_status::text = ANY "
        "(ARRAY['ready'::character varying, "
        "'needs_review'::character varying, "
        "'blocked'::character varying]::text[]))"
    )
    checks["ck_generatedpageqaresult_not_self_superseding"] = (
        "((supersedes_qa_result_id IS NULL) OR "
        "(supersedes_qa_result_id <> id))"
    )
    bound_evidence = migration.BOUND_EVIDENCE_CHECK
    for field in (
        "qa_algorithm_key",
        "qa_algorithm_version",
        "qa_ruleset_key",
        "qa_ruleset_version",
    ):
        bound_evidence = bound_evidence.replace(
            f"length(trim({field}))",
            f"length(TRIM(BOTH FROM {field}))",
        )
    checks["ck_generatedpageqaresult_bound_evidence"] = bound_evidence

    migration._validate_check_contracts(checks)
