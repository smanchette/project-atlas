from pathlib import Path
import importlib.util

import pytest

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


def test_0020_upgrade_downgrade_reupgrade_bootstrap_cleanup_audit(monkeypatch, tmp_path):
    database = tmp_path / "bootstrap-cleanup-matrix.sqlite3"; config = config_for(monkeypatch, database)
    command.upgrade(config, "20260716_0019")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO setting (setting_key, setting_value, description, created_at, updated_at) VALUES ('cleanup-migration-sentinel','kept','unrelated','2026-07-16','2026-07-16')"))
    command.upgrade(config, "20260716_0020")
    inspector = inspect(engine)
    assert "wordpressbootstrapcleanupaudit" in inspector.get_table_names()
    assert {item["name"] for item in inspector.get_unique_constraints("wordpressbootstrapcleanupaudit")} >= {
        "uq_wordpressbootstrapcleanupaudit_deactivation_handle",
        "uq_wordpressbootstrapcleanupaudit_deletion_handle",
    }
    assert {item["name"] for item in inspector.get_check_constraints("wordpressbootstrapcleanupaudit")} >= {
        "ck_wordpressbootstrapcleanupaudit_action",
        "ck_wordpressbootstrapcleanupaudit_status",
    }
    command.downgrade(config, "20260716_0019")
    assert "wordpressbootstrapcleanupaudit" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT setting_value FROM setting WHERE setting_key='cleanup-migration-sentinel'" )).scalar_one() == "kept"
    command.upgrade(config, "20260716_0020")
    assert "wordpressbootstrapcleanupaudit" in inspect(engine).get_table_names()
    get_settings.cache_clear()


def test_0021_upgrade_downgrade_reupgrade_lifecycle_recovery_fields(monkeypatch, tmp_path):
    database = tmp_path / "metadata-recovery-matrix.sqlite3"
    config = config_for(monkeypatch, database)
    command.upgrade(config, "20260716_0020")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO setting (setting_key, setting_value, description, created_at, updated_at) VALUES ('recovery-migration-sentinel','kept','unrelated','2026-07-17','2026-07-17')"))
    command.upgrade(config, "20260717_0021")
    columns = {item["name"] for item in inspect(engine).get_columns("wordpressmetadatalifecycleaudit")}
    assert {"completion_mode", "recovery_recommendation"} <= columns
    indexes = {item["name"] for item in inspect(engine).get_indexes("wordpressmetadatalifecycleaudit")}
    assert "ix_wordpressmetadatalifecycleaudit_completion_mode" in indexes
    command.downgrade(config, "20260716_0020")
    columns = {item["name"] for item in inspect(engine).get_columns("wordpressmetadatalifecycleaudit")}
    assert "completion_mode" not in columns and "recovery_recommendation" not in columns
    with engine.connect() as connection:
        assert connection.execute(text("SELECT setting_value FROM setting WHERE setting_key='recovery-migration-sentinel'")).scalar_one() == "kept"
    command.upgrade(config, "20260717_0021")
    columns = {item["name"] for item in inspect(engine).get_columns("wordpressmetadatalifecycleaudit")}
    assert {"completion_mode", "recovery_recommendation"} <= columns
    get_settings.cache_clear()


def test_0025_upgrade_downgrade_reupgrade_bootstrap_retirement_fields(monkeypatch, tmp_path):
    database = tmp_path / "bootstrap-retirement-matrix.sqlite3"
    config = config_for(monkeypatch, database)
    command.upgrade(config, "20260720_0024")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    command.upgrade(config, "20260722_0025")
    inspector = inspect(engine)
    columns = {item["name"] for item in inspector.get_columns("wordpressbootstrapestablishmentaudit")}
    assert {"authorization_mode", "retirement_reason"} <= columns
    constraints = {item["name"] for item in inspector.get_check_constraints("wordpressbootstrapestablishmentaudit")}
    assert {
        "ck_wordpressbootstrapestablishmentaudit_status",
        "ck_wordpressbootstrapestablishmentaudit_authorization_mode",
        "ck_wordpressbootstrapestablishmentaudit_retirement_reason",
    } <= constraints
    command.downgrade(config, "20260720_0024")
    columns = {item["name"] for item in inspect(engine).get_columns("wordpressbootstrapestablishmentaudit")}
    assert "authorization_mode" not in columns and "retirement_reason" not in columns
    command.upgrade(config, "20260722_0025")
    assert {"authorization_mode", "retirement_reason"} <= {
        item["name"] for item in inspect(engine).get_columns("wordpressbootstrapestablishmentaudit")
    }
    get_settings.cache_clear()


def test_0025_downgrade_refuses_retired_rows(monkeypatch):
    path = BACKEND / "alembic/versions/20260722_0025_bootstrap_authorization_retirement.py"
    spec = importlib.util.spec_from_file_location("atlas_migration_0025_guard", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    class Result:
        def scalar_one(self):
            return 1

    class Bind:
        def execute(self, statement):
            return Result()

    monkeypatch.setattr(migration.op, "get_bind", lambda: Bind())
    with pytest.raises(RuntimeError, match="authorization_retired"):
        migration.downgrade()


def test_0026_upgrade_downgrade_reupgrade_activation_reconciliation_fields(
    monkeypatch,
    tmp_path,
):
    database = tmp_path / "bootstrap-activation-reconciliation.sqlite3"
    config = config_for(monkeypatch, database)
    command.upgrade(config, "20260722_0025")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    command.upgrade(config, "20260723_0026")
    inspector = inspect(engine)
    columns = {
        item["name"]
        for item in inspector.get_columns("wordpressbootstrapestablishmentaudit")
    }
    assert {
        "reconciliation_reason",
        "reconciliation_handle_fingerprint",
        "reconciliation_binding_hash",
        "reconciled_at",
    } <= columns
    constraints = {
        item["name"]
        for item in inspector.get_check_constraints(
            "wordpressbootstrapestablishmentaudit"
        )
    }
    unique = {
        item["name"]
        for item in inspector.get_unique_constraints(
            "wordpressbootstrapestablishmentaudit"
        )
    }
    assert "ck_wordpressbootstrapestablishmentaudit_reconciliation" in constraints
    assert (
        "uq_wordpressbootstrapestablishmentaudit_reconciliation_handle"
        in unique
    )
    command.downgrade(config, "20260722_0025")
    columns = {
        item["name"]
        for item in inspect(engine).get_columns(
            "wordpressbootstrapestablishmentaudit"
        )
    }
    assert "reconciliation_reason" not in columns
    command.upgrade(config, "20260723_0026")
    assert "reconciliation_reason" in {
        item["name"]
        for item in inspect(engine).get_columns(
            "wordpressbootstrapestablishmentaudit"
        )
    }
    get_settings.cache_clear()


def test_0026_downgrade_refuses_reconciled_rows(monkeypatch):
    path = (
        BACKEND
        / "alembic/versions/20260723_0026_bootstrap_activation_reconciliation.py"
    )
    spec = importlib.util.spec_from_file_location("atlas_migration_0026_guard", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    class Result:
        def scalar_one(self):
            return 1

    class Bind:
        def execute(self, statement):
            return Result()

    monkeypatch.setattr(migration.op, "get_bind", lambda: Bind())
    with pytest.raises(RuntimeError, match="reconciled"):
        migration.downgrade()


def test_0026_postgresql_identifiers_fit_the_63_byte_limit():
    path = (
        BACKEND
        / "alembic/versions/20260723_0026_bootstrap_activation_reconciliation.py"
    )
    source = path.read_text(encoding="utf-8")
    identifiers = {
        token.strip('"')
        for token in source.replace("(", " ").replace(")", " ").replace(",", " ").split()
        if token.startswith(
            (
                '"ix_wordpressbootstrap',
                '"uq_wordpressbootstrap',
                '"ck_wordpressbootstrap',
            )
        )
    }
    assert identifiers
    assert all(len(identifier.encode("utf-8")) <= 63 for identifier in identifiers)
