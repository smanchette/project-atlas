from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlmodel import Session

from app.core.config import get_settings
from app.models import Brand, Business, Website


BACKEND = Path(__file__).parents[1]
DURABLE_TABLES = {
    "themefamily",
    "themefamilyversion",
    "websitethemeconfiguration",
    "websitethemecomponentconfiguration",
    "themeconfigurationaudit",
}


def test_0045_identifiers_fit_postgresql_limit() -> None:
    migration_path = (
        BACKEND
        / "alembic"
        / "versions"
        / "20260813_0045_durable_theme_configurations.py"
    )
    spec = spec_from_file_location("atlas_migration_0045", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    for column in (
        "website_theme_configuration_id",
        "destination_component_configuration_id",
        "overrides_component_configuration_id",
        "supersedes_component_configuration_id",
    ):
        identifier = migration._index_identifier(  # type: ignore[attr-defined]
            "websitethemecomponentconfiguration",
            column,
        )
        assert len(identifier.encode("utf-8")) <= 63

    source = migration_path.read_text(encoding="utf-8")
    explicit_identifiers = {
        match[0] or match[1]
        for match in re.findall(
            r'(?:name\s*=\s*"([^"]+)"|op\.create_index\(\s*"([^"]+)")',
            source,
        )
    }
    assert explicit_identifiers
    assert all(len(identifier.encode("utf-8")) <= 63 for identifier in explicit_identifiers)


def _config(monkeypatch: pytest.MonkeyPatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def test_0045_adds_exact_durable_tables_and_preserves_website_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "durable-theme-clean.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260810_0044")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with Session(engine) as session:
        business = Business(
            company_name="Preserved Company",
            business_type="test",
            state="FL",
        )
        session.add(business)
        session.flush()
        brand = Brand(
            business_id=business.id,
            brand_name="Preserved Brand",
            status="active",
        )
        session.add(brand)
        session.flush()
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

    command.upgrade(config, "20260813_0045")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    assert DURABLE_TABLES <= set(inspector.get_table_names())
    assert {
        "uq_websitethemeconfiguration_current",
    } <= {
        item["name"]
        for item in inspector.get_indexes("websitethemeconfiguration")
    }
    assert {
        "uq_themecomponentconfiguration_current_website_instance",
        "uq_themecomponentconfiguration_current_page_override",
    } <= {
        item["name"]
        for item in inspector.get_indexes("websitethemecomponentconfiguration")
    }
    component_fks = {
        tuple(item["constrained_columns"])
        for item in inspector.get_foreign_keys(
            "websitethemecomponentconfiguration"
        )
    }
    assert {
        ("destination_component_configuration_id",),
        ("overrides_component_configuration_id",),
        ("supersedes_component_configuration_id",),
    } <= component_fks
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260813_0045"
        assert connection.execute(
            text("SELECT website_name FROM website WHERE id = :id"),
            {"id": website_id},
        ).scalar_one() == "Preserved Website"
        for table in DURABLE_TABLES:
            assert connection.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar_one() == 0
    engine.dispose()
    get_settings.cache_clear()


def test_0045_refuses_any_precreated_durable_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "durable-theme-precreated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260810_0044")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE themefamily (id INTEGER PRIMARY KEY)"))

    with pytest.raises(RuntimeError, match="refuses pre-created tables"):
        command.upgrade(config, "20260813_0045")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260810_0044"
    engine.dispose()
    get_settings.cache_clear()


def test_0045_empty_tables_can_downgrade_but_governed_rows_block_downgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "durable-theme-downgrade.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260813_0045")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO themefamily "
                "(created_at, updated_at, family_key, display_name, description, "
                "provider_source_identity, lifecycle_status, created_by, "
                "integrity_fingerprint) VALUES "
                "(CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'test-family', 'Test', "
                "'Test family', 'test source', 'registered', 'Test Operator', :hash)"
            ),
            {"hash": "0" * 64},
        )

    with pytest.raises(RuntimeError, match="governed records exist"):
        command.downgrade(config, "20260810_0044")
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM themefamily"))

    command.downgrade(config, "20260810_0044")
    inspector = inspect(engine)
    assert DURABLE_TABLES.isdisjoint(inspector.get_table_names())
    engine.dispose()
    get_settings.cache_clear()
