from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlmodel import SQLModel

from app.core.config import get_settings
from app.models import entities  # noqa: F401


BACKEND = Path(__file__).parents[1]


def _config(monkeypatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def test_0038_adds_brand_asset_tables_on_disposable_database(monkeypatch, tmp_path):
    database = tmp_path / "brand-assets.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260801_0038")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert {"brandasset", "websiteidentityassetassignment"} <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260801_0038"


def test_0038_adopts_compatible_tables_precreated_by_local_startup(monkeypatch, tmp_path):
    database = tmp_path / "brand-assets-precreated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260801_0037")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    SQLModel.metadata.create_all(engine)
    command.upgrade(config, "20260801_0038")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM brandasset")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM websiteidentityassetassignment")).scalar_one() == 0
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260801_0038"


def test_0038_repairs_empty_early_precreated_asset_table(monkeypatch, tmp_path):
    database = tmp_path / "brand-assets-early-precreated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260801_0037")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE brandasset DROP COLUMN retired_by"))
        connection.execute(text("ALTER TABLE brandasset DROP COLUMN retirement_rationale"))
        connection.execute(text("ALTER TABLE brandasset DROP COLUMN retired_at"))
    command.upgrade(config, "20260801_0038")
    columns = {column["name"] for column in inspect(engine).get_columns("brandasset")}
    assert {"retired_by", "retirement_rationale", "retired_at"} <= columns
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260801_0038"
