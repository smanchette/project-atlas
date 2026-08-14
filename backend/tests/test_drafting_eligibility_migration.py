from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings

BACKEND = Path(__file__).parents[1]

def _config(monkeypatch, path: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def test_clean_database_migrates_to_current_head(monkeypatch, tmp_path):
    database = tmp_path / "clean.sqlite3"
    command.upgrade(_config(monkeypatch, database), "head")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert {
        "draftingeligibilityassessment",
        "draftingeligibilitydisposition",
        "supportingpageauthorization",
        "predraftdistinctnessbrief",
        "websitedraftgenerationrun",
        "websitedraftgenerationitem",
        "websiteservicecountycoveragedecision",
        "semanticcomponentdefinition",
        "pagecomposition",
        "theme",
        "websitethemeselection",
    } <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260813_0045"


def test_populated_0032_upgrade_preserves_existing_page(monkeypatch, tmp_path):
    database = tmp_path / "populated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260730_0032")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO business "
                "(company_name,business_type,state,created_at,updated_at) "
                "VALUES ('Preserved','Service','FL',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM business")).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM draftingeligibilityassessment")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM draftingeligibilitydisposition")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM supportingpageauthorization")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM predraftdistinctnessbrief")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM websitedraftgenerationrun")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM websitedraftgenerationitem")
        ).scalar_one() == 0
