from datetime import UTC, datetime
import importlib.util
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.core.config import get_settings
from app.models import Business, SitePlan, Website


BACKEND = Path(__file__).parents[1]
TABLES = ("navigationset", "navigationitem", "internallinkintent")
PROVENANCE_COLUMNS = {
    "rationale",
    "decided_by",
    "decision_version",
    "decided_at",
    "source_suggestion_key",
}


def test_0040_constraint_canonicalization_accepts_postgresql_normalization():
    migration_path = (
        BACKEND
        / "alembic"
        / "versions"
        / "20260805_0040_navigation_decision_provenance.py"
    )
    spec = importlib.util.spec_from_file_location("navigation_0040", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    expected = migration._constraint_expression()
    postgresql = (
        "CHECK ((((decision_version IS NULL) AND (decided_by IS NULL) AND "
        "(rationale IS NULL) AND (decided_at IS NULL) AND "
        "(source_suggestion_key IS NULL)) OR ((decision_version IS NOT NULL) "
        "AND (decision_version >= 1) AND (decided_by IS NOT NULL) AND "
        "(rationale IS NOT NULL) AND (decided_at IS NOT NULL))))"
    )
    assert migration._canonical(postgresql) == migration._canonical(expected)
    materially_different = expected.replace(
        "(decision_version IS NOT NULL AND decision_version >= 1",
        "(decision_version IS NOT NULL OR decision_version >= 1",
    )
    assert migration._canonical(materially_different) != migration._canonical(expected)


def _config(monkeypatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def test_0040_adds_nullable_provenance_and_exact_constraints(monkeypatch, tmp_path):
    database = tmp_path / "navigation-provenance-clean.sqlite3"
    config = _config(monkeypatch, database)

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    for table in TABLES:
        assert PROVENANCE_COLUMNS <= {
            item["name"] for item in inspector.get_columns(table)
        }
        assert f"ck_{table}_decision_provenance" in {
            item["name"] for item in inspector.get_check_constraints(table)
        }
        assert f"ix_{table}_decided_at" in {
            item["name"] for item in inspector.get_indexes(table)
        }
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260815_0046"
    get_settings.cache_clear()


def test_0040_preserves_legacy_rows_null_and_rejects_partial_provenance(
    monkeypatch,
    tmp_path,
):
    database = tmp_path / "navigation-provenance-populated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260804_0039")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    now = datetime.now(UTC).isoformat()
    with Session(engine) as session:
        business = Business(
            company_name="Legacy Company",
            business_type="Test",
            state="FL",
        )
        session.add(business)
        session.flush()
        website = Website(
            business_id=business.id,
            website_name="Legacy Website",
            domain="legacy.example.test",
            public_url="https://legacy.example.test",
            status="active",
        )
        session.add(website)
        session.flush()
        plan = SitePlan(
            website_id=website.id,
            plan_key="primary",
            plan_name="Legacy Plan",
        )
        session.add(plan)
        session.commit()
        website_id = website.id
        plan_id = plan.id
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO navigationset "
                "(created_at, updated_at, website_id, site_plan_id, set_type, label, status, version) "
                "VALUES (:now, :now, :website_id, :plan_id, 'primary', "
                "'Primary Navigation', 'draft', 1)"
            ),
            {"now": now, "website_id": website_id, "plan_id": plan_id},
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        legacy = connection.execute(
            text(
                "SELECT rationale, decided_by, decision_version, decided_at, "
                "source_suggestion_key FROM navigationset WHERE site_plan_id=:plan_id"
            ),
            {"plan_id": plan_id},
        ).one()
        assert tuple(legacy) == (None, None, None, None, None)
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE navigationset SET decided_by='Partial Operator' "
                    "WHERE site_plan_id=:plan_id"
                ),
                {"plan_id": plan_id},
            )
    get_settings.cache_clear()
