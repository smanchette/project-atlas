from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings


BACKEND = Path(__file__).parents[1]


def config_for(monkeypatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def test_clean_database_upgrade_through_0015(monkeypatch, tmp_path):
    database = tmp_path / "clean.sqlite3"; config = config_for(monkeypatch, database)
    command.upgrade(config, "20260712_0015")
    inspector = inspect(create_engine(f"sqlite:///{database.as_posix()}"))
    assert {"wordpressdeploymentaudit", "wordpressdeploymentnonce", "wordpressdeploymenttransition"} <= set(inspector.get_table_names())
    get_settings.cache_clear()


def test_0014_upgrade_downgrade_reupgrade_preserves_unrelated_data(monkeypatch, tmp_path):
    database = tmp_path / "matrix.sqlite3"; config = config_for(monkeypatch, database)
    command.upgrade(config, "20260712_0014")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO setting (setting_key, setting_value, description, created_at, updated_at) VALUES ('migration-sentinel','kept','unrelated','2026-07-12','2026-07-12')"))
    command.upgrade(config, "20260712_0015")
    inspector = inspect(engine)
    assert {"wordpressdeploymentaudit", "wordpressdeploymentnonce", "wordpressdeploymenttransition"} <= set(inspector.get_table_names())
    assert any(item["name"] == "uq_wordpressdeploymentaudit_deployment_key" for item in inspector.get_unique_constraints("wordpressdeploymentaudit"))
    assert {item["name"] for item in inspector.get_check_constraints("wordpressdeploymentaudit")} >= {"ck_wordpressdeploymentaudit_action", "ck_wordpressdeploymentaudit_status"}
    assert {item["name"] for item in inspector.get_indexes("wordpressdeploymentaudit")} >= {"ix_wordpressdeploymentaudit_authorization_jti", "ix_wordpressdeploymentaudit_status", "ix_wordpressdeploymentaudit_attempted_at"}
    command.downgrade(config, "20260712_0014")
    assert not ({"wordpressdeploymentaudit", "wordpressdeploymentnonce", "wordpressdeploymenttransition"} & set(inspect(engine).get_table_names()))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT setting_value FROM setting WHERE setting_key='migration-sentinel'")).scalar_one() == "kept"
    command.upgrade(config, "20260712_0015")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT setting_value FROM setting WHERE setting_key='migration-sentinel'")).scalar_one() == "kept"
    get_settings.cache_clear()


def test_0016_upgrade_downgrade_reupgrade_activation_audit(monkeypatch, tmp_path):
    database = tmp_path / "activation-matrix.sqlite3"; config = config_for(monkeypatch, database)
    command.upgrade(config, "20260714_0016")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO setting (setting_key, setting_value, description, created_at, updated_at) VALUES ('activation-migration-sentinel','kept','unrelated','2026-07-16','2026-07-16')"))
    command.upgrade(config, "20260716_0017")
    inspector = inspect(engine)
    assert "wordpressactivationaudit" in inspector.get_table_names()
    assert any(item["name"] == "uq_wordpressactivationaudit_handle_fingerprint" for item in inspector.get_unique_constraints("wordpressactivationaudit"))
    assert {item["name"] for item in inspector.get_check_constraints("wordpressactivationaudit")} >= {"ck_wordpressactivationaudit_action", "ck_wordpressactivationaudit_status"}
    command.downgrade(config, "20260714_0016")
    assert "wordpressactivationaudit" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT setting_value FROM setting WHERE setting_key='activation-migration-sentinel'" )).scalar_one() == "kept"
    command.upgrade(config, "20260716_0017")
    assert "wordpressactivationaudit" in inspect(engine).get_table_names()
    get_settings.cache_clear()


def test_0018_upgrade_downgrade_reupgrade_plugin_upgrade_audit(monkeypatch, tmp_path):
    database = tmp_path / "upgrade-matrix.sqlite3"; config = config_for(monkeypatch, database)
    command.upgrade(config, "20260716_0018")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO setting (setting_key, setting_value, description, created_at, updated_at) VALUES ('upgrade-migration-sentinel','kept','unrelated','2026-07-16','2026-07-16')"))
    command.upgrade(config, "20260716_0019")
    inspector = inspect(engine)
    assert "wordpresspluginupgradeaudit" in inspector.get_table_names()
    assert any(item["name"] == "uq_wordpresspluginupgradeaudit_handle_fingerprint" for item in inspector.get_unique_constraints("wordpresspluginupgradeaudit"))
    assert {item["name"] for item in inspector.get_check_constraints("wordpresspluginupgradeaudit")} >= {"ck_wordpresspluginupgradeaudit_action", "ck_wordpresspluginupgradeaudit_status"}
    command.downgrade(config, "20260716_0018")
    assert "wordpresspluginupgradeaudit" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT setting_value FROM setting WHERE setting_key='upgrade-migration-sentinel'")).scalar_one() == "kept"
    command.upgrade(config, "20260716_0019")
    assert "wordpresspluginupgradeaudit" in inspect(engine).get_table_names()
    get_settings.cache_clear()
