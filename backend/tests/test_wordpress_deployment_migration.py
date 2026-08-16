from pathlib import Path
import importlib.util
import re

import pytest

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Index, MetaData, String, Table, create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.core.config import get_settings


BACKEND = Path(__file__).parents[1]


POSTGRESQL_INDEX_IDENTITIES = {
    (
        "20260716_0020_wordpress_bootstrap_cleanup_audits.py",
        "wordpressbootstrapcleanupaudit",
        "deactivation_handle_fingerprint",
    ): "ix_wordpressbootstrapcleanupaudit_deactivation_handle_f_fc62",
    (
        "20260717_0022_cache_aware_rendering_audits.py",
        "wordpresscacheawarerenderingaudit",
        "rendering_handle_fingerprint",
    ): "ix_wordpresscacheawarerenderingaudit_rendering_handle_f_e1fc",
    (
        "20260719_0023_wordpress_bootstrap_establishment_audits.py",
        "wordpressbootstrapestablishmentaudit",
        "manual_handle_fingerprint",
    ): "ix_wordpressbootstrapestablishmentaudit_manual_handle_f_6138",
    (
        "20260719_0023_wordpress_bootstrap_establishment_audits.py",
        "wordpressbootstrapestablishmentaudit",
        "activation_handle_fingerprint",
    ): "ix_wordpressbootstrapestablishmentaudit_activation_hand_a9b8",
}


def _migration_module(file_name: str):
    path = BACKEND / "alembic" / "versions" / file_name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _captured_postgresql_indexes(monkeypatch, file_name: str):
    module = _migration_module(file_name)
    captured = []
    operations = Operations(MigrationContext.configure(dialect_name="postgresql"))

    class Inspector:
        @staticmethod
        def get_table_names():
            return []

    class CaptureOperations:
        @staticmethod
        def get_bind():
            return object()

        @staticmethod
        def create_table(*_args, **_kwargs):
            return None

        @staticmethod
        def f(name):
            return operations.f(name)

        @staticmethod
        def create_index(name, table_name, columns, *, unique=False, **kwargs):
            captured.append((name, table_name, tuple(columns), unique, kwargs))

    monkeypatch.setattr(module.sa, "inspect", lambda _bind: Inspector())
    monkeypatch.setattr(module, "op", CaptureOperations())
    module.upgrade()
    return captured


def _postgresql_index_name(captured_index) -> str:
    name, table_name, columns, unique, kwargs = captured_index
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        *[Column(column_name, String()) for column_name in columns],
    )
    index = Index(name, *[table.c[column_name] for column_name in columns], unique=unique, **kwargs)
    sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    match = re.match(r"CREATE(?: UNIQUE)? INDEX ([^ ]+) ON ", sql)
    assert match is not None
    return match.group(1).strip('"')


def config_for(monkeypatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def test_0020_0022_0023_indexes_compile_to_stable_postgresql_identities(
    monkeypatch,
):
    files = (
        "20260716_0020_wordpress_bootstrap_cleanup_audits.py",
        "20260717_0022_cache_aware_rendering_audits.py",
        "20260719_0023_wordpress_bootstrap_establishment_audits.py",
    )
    emitted = {}
    for file_name in files:
        for captured in _captured_postgresql_indexes(monkeypatch, file_name):
            name, table_name, columns, unique, kwargs = captured
            physical_name = _postgresql_index_name(captured)
            assert len(physical_name.encode("utf-8")) <= 63
            assert unique is False
            assert len(columns) == 1
            assert kwargs == {}
            emitted[(file_name, table_name, columns[0])] = physical_name
            logical_name = str(name)
            if len(logical_name.encode("utf-8")) <= 63:
                assert physical_name == logical_name

    assert len(emitted.values()) == len(set(emitted.values()))
    for identity, expected_name in POSTGRESQL_INDEX_IDENTITIES.items():
        assert emitted[identity] == expected_name


def test_0020_0022_0023_reject_raw_prefix_and_near_match_as_emitted_identity(
    monkeypatch,
):
    emitted = {
        (file_name, table_name, columns[0]): _postgresql_index_name(captured)
        for file_name in {
            identity[0] for identity in POSTGRESQL_INDEX_IDENTITIES
        }
        for captured in _captured_postgresql_indexes(monkeypatch, file_name)
        for _name, table_name, columns, _unique, _kwargs in [captured]
    }
    for identity, expected_name in POSTGRESQL_INDEX_IDENTITIES.items():
        file_name, table_name, column_name = identity
        logical_name = (
            f"ix_{table_name}_{column_name}"
            if file_name != "20260716_0020_wordpress_bootstrap_cleanup_audits.py"
            else f"ix_wordpressbootstrapcleanupaudit_{column_name}"
        )
        raw_prefix = logical_name.encode("utf-8")[:63].decode("utf-8")
        near_match = f"{expected_name[:-1]}0"
        assert emitted[identity] == expected_name
        assert raw_prefix != expected_name
        assert near_match != expected_name
        assert raw_prefix not in emitted.values()
        assert near_match not in emitted.values()


def test_0022_0023_upgrade_downgrade_reupgrade_preserves_exact_indexes(
    monkeypatch,
    tmp_path,
):
    database = tmp_path / "rendering-establishment-matrix.sqlite3"
    config = config_for(monkeypatch, database)
    command.upgrade(config, "20260717_0021")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO setting "
                "(setting_key, setting_value, description, created_at, updated_at) "
                "VALUES ('index-repair-sentinel','kept','unrelated',"
                "'2026-07-19','2026-07-19')"
            )
        )

    command.upgrade(config, "20260719_0023")
    expected = {
        "wordpresscacheawarerenderingaudit": {
            "ix_wordpresscacheawarerenderingaudit_rendering_handle_fingerprint",
        },
        "wordpressbootstrapestablishmentaudit": {
            "ix_wordpressbootstrapestablishmentaudit_manual_handle_fingerprint",
            "ix_wordpressbootstrapestablishmentaudit_activation_handle_fingerprint",
        },
    }
    for table_name, names in expected.items():
        with engine.connect() as connection:
            observed = list(
                connection.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='index' AND tbl_name=:table_name "
                        "AND sql IS NOT NULL ORDER BY name"
                    ),
                    {"table_name": table_name},
                ).scalars()
            )
        assert names <= set(observed)
        assert len(observed) == len(set(observed))

    command.downgrade(config, "20260717_0021")
    assert not {
        "wordpresscacheawarerenderingaudit",
        "wordpressbootstrapestablishmentaudit",
    } & set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT setting_value FROM setting "
                "WHERE setting_key='index-repair-sentinel'"
            )
        ).scalar_one() == "kept"

    command.upgrade(config, "20260719_0023")
    for table_name, names in expected.items():
        with engine.connect() as connection:
            observed = list(
                connection.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='index' AND tbl_name=:table_name "
                        "AND sql IS NOT NULL ORDER BY name"
                    ),
                    {"table_name": table_name},
                ).scalars()
            )
        assert names <= set(observed)
        assert len(observed) == len(set(observed))
    get_settings.cache_clear()


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


def test_0027_upgrade_downgrade_reupgrade_plugin_reconciliation_fields(
    monkeypatch,
    tmp_path,
):
    database = tmp_path / "plugin-upgrade-reconciliation.sqlite3"
    config = config_for(monkeypatch, database)
    command.upgrade(config, "20260723_0026")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    command.upgrade(config, "20260725_0027")
    columns = {
        item["name"]
        for item in inspect(engine).get_columns("wordpresspluginupgradeaudit")
    }
    assert {
        "reconciliation_reason",
        "reconciliation_handle_fingerprint",
        "reconciliation_binding_hash",
        "reconciliation_snapshot",
        "reconciled_at",
    } <= columns
    constraints = {
        item["name"]
        for item in inspect(engine).get_check_constraints(
            "wordpresspluginupgradeaudit"
        )
    }
    unique = {
        item["name"]
        for item in inspect(engine).get_unique_constraints(
            "wordpresspluginupgradeaudit"
        )
    }
    assert "ck_wppluginupgradeaudit_reconciliation" in constraints
    assert "uq_wppluginupgradeaudit_reconciliation_handle" in unique
    command.downgrade(config, "20260723_0026")
    assert "reconciliation_reason" not in {
        item["name"]
        for item in inspect(engine).get_columns("wordpresspluginupgradeaudit")
    }
    command.upgrade(config, "20260725_0027")
    assert "reconciliation_reason" in {
        item["name"]
        for item in inspect(engine).get_columns("wordpresspluginupgradeaudit")
    }
    get_settings.cache_clear()


def test_0027_downgrade_refuses_reconciled_rows(monkeypatch):
    path = (
        BACKEND
        / "alembic/versions/20260725_0027_plugin_upgrade_reconciliation.py"
    )
    spec = importlib.util.spec_from_file_location("atlas_migration_0027_guard", path)
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


def test_0027_postgresql_identifiers_fit_the_63_byte_limit():
    path = (
        BACKEND
        / "alembic/versions/20260725_0027_plugin_upgrade_reconciliation.py"
    )
    source = path.read_text(encoding="utf-8")
    identifiers = {
        token.strip('"')
        for token in source.replace("(", " ").replace(")", " ").replace(",", " ").split()
        if token.startswith(
            (
                '"ix_wpplugin',
                '"uq_wpplugin',
                '"ck_wpplugin',
            )
        )
    }
    assert identifiers
    assert all(len(identifier.encode("utf-8")) <= 63 for identifier in identifiers)
