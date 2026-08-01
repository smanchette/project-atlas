from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlmodel import SQLModel

from app.core.config import get_settings
from app.models import entities  # noqa: F401


BACKEND = Path(__file__).parents[1]


def test_0037_adds_registry_and_composition_tables_on_disposable_database(monkeypatch, tmp_path):
    database = tmp_path / "composition.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()


def test_0037_adopts_compatible_tables_precreated_by_local_startup(monkeypatch, tmp_path):
    database = tmp_path / "composition-precreated.sqlite3"
    url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(config, "20260731_0036")

    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM semanticcomponentdefinition")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM pagecomposition")).scalar_one() == 0

    command.upgrade(config, "20260801_0037")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM semanticcomponentdefinition")).scalar_one() == 15
        assert connection.execute(text("SELECT COUNT(*) FROM pagecomposition")).scalar_one() == 0
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260801_0037"
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(config, "20260801_0037")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    assert {"semanticcomponentdefinition", "pagecomposition"} <= set(inspector.get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM semanticcomponentdefinition")).scalar_one() == 15
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260801_0037"
    command.downgrade(config, "20260731_0036")
    assert "pagecomposition" not in inspect(engine).get_table_names()
    assert "semanticcomponentdefinition" not in inspect(engine).get_table_names()
    get_settings.cache_clear()
