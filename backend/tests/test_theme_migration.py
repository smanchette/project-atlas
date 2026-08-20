from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlmodel import Session, SQLModel

from app.core.config import get_settings
from app.db import session as db_session
from app.models import Brand, Business, GeneratedPageQAResult, Website
from app.models import entities  # noqa: F401


BACKEND = Path(__file__).parents[1]

EXPECTED_VERSION_CHECKS = {
    "theme": {
        "ck_theme_version": "version >= 1",
        "ck_theme_token_contract_version": "token_contract_version >= 1",
    },
    "websitethemeselection": {
        "ck_websitethemeselection_version": "version >= 1",
    },
}


def _config(monkeypatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def _canonical_check(expression: str) -> str:
    normalized = "".join(expression.lower().replace('"', "").split())
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1]
    return normalized


def _assert_version_checks(engine) -> None:
    inspector = inspect(engine)
    for table, expected in EXPECTED_VERSION_CHECKS.items():
        observed = {
            item["name"]: item.get("sqltext") or ""
            for item in inspector.get_check_constraints(table)
            if item.get("name")
        }
        for name, expression in expected.items():
            assert name in observed
            assert _canonical_check(observed[name]) == _canonical_check(expression)


def _create_pre_0048_runtime_tables() -> None:
    """Exercise historical startup without projecting the future history FK."""

    table = GeneratedPageQAResult.__table__
    history_fk = next(
        constraint
        for constraint in table.constraints
        if constraint.name == "fk_generatedpageqaresult_composition_revision"
    )
    table.constraints.remove(history_fk)
    try:
        db_session.create_db_and_tables()
    finally:
        table.append_constraint(history_fk)


def test_0039_adds_theme_tables_on_clean_disposable_database(monkeypatch, tmp_path) -> None:
    database = tmp_path / "themes-clean.sqlite3"
    config = _config(monkeypatch, database)

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    assert {"theme", "websitethemeselection"} <= set(inspector.get_table_names())
    assert "uq_websitethemeselection_active_website" in {
        item["name"] for item in inspector.get_indexes("websitethemeselection")
    }
    _assert_version_checks(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260820_0048"
    get_settings.cache_clear()


def test_runtime_startup_does_not_precreate_0045_alembic_owned_tables(
    monkeypatch,
    tmp_path,
) -> None:
    database = tmp_path / "themes-precreated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260801_0038")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    monkeypatch.setattr(db_session, "engine", engine)
    _create_pre_0048_runtime_tables()

    assert {
        "themefamily",
        "themefamilyversion",
        "websitethemeconfiguration",
        "websitethemecomponentconfiguration",
        "themeconfigurationaudit",
    }.isdisjoint(inspect(engine).get_table_names())

    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM theme")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM websitethemeselection")).scalar_one() == 0
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260820_0048"
    _assert_version_checks(engine)
    get_settings.cache_clear()


def test_0039_rejects_precreated_theme_table_without_version_checks(monkeypatch, tmp_path) -> None:
    database = tmp_path / "themes-incompatible.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260801_0038")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE theme (
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    id INTEGER NOT NULL PRIMARY KEY,
                    website_id INTEGER NOT NULL,
                    business_id INTEGER NOT NULL,
                    brand_id INTEGER NOT NULL,
                    theme_key VARCHAR(120) NOT NULL,
                    theme_name VARCHAR(160) NOT NULL,
                    version INTEGER NOT NULL,
                    token_contract_version INTEGER NOT NULL,
                    design_tokens JSON NOT NULL,
                    token_hash_sha256 VARCHAR(64) NOT NULL,
                    description VARCHAR(2000),
                    lifecycle_status VARCHAR(24) NOT NULL,
                    approval_status VARCHAR(24) NOT NULL,
                    created_by VARCHAR(160) NOT NULL,
                    provenance_type VARCHAR(40) NOT NULL,
                    provenance_notes VARCHAR(2000) NOT NULL,
                    approved_by VARCHAR(160),
                    approved_at DATETIME,
                    retired_by VARCHAR(160),
                    retirement_rationale VARCHAR(2000),
                    retired_at DATETIME,
                    replaces_theme_id INTEGER
                )
                """
            )
        )

    with pytest.raises(RuntimeError, match="ck_theme_version differs"):
        command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260801_0038"
    get_settings.cache_clear()


def test_0039_preserves_populated_website_ownership_records(monkeypatch, tmp_path) -> None:
    database = tmp_path / "themes-populated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260801_0038")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with Session(engine) as session:
        business = Business(company_name="Preserved Company", business_type="test", state="FL")
        session.add(business)
        session.commit()
        session.refresh(business)
        brand = Brand(business_id=business.id, brand_name="Preserved Brand", status="active")
        session.add(brand)
        session.commit()
        session.refresh(brand)
        website = Website(
            business_id=business.id,
            brand_id=brand.id,
            website_name="Preserved Website",
            domain="preserved.example.test",
            public_url="https://preserved.example.test",
            status="active",
        )
        session.add(website)
        session.commit()
        website_id = website.id
    engine.dispose()

    command.upgrade(config, "head")

    with Session(engine) as session:
        preserved = session.get(Website, website_id)
        assert preserved is not None
        assert preserved.website_name == "Preserved Website"
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM theme")).scalar_one() == 0
    get_settings.cache_clear()
