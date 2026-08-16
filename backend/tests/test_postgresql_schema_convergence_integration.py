from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.pool import NullPool
from sqlmodel import Session, select

from app.core.config import get_settings


BACKEND = Path(__file__).parents[1]
ADMIN_URL_ENV = "ATLAS_DISPOSABLE_POSTGRES_ADMIN_URL"
DATABASE_NAMES_ENV = "ATLAS_DISPOSABLE_POSTGRES_DATABASE_NAMES"
LEDGER_PATH_ENV = "ATLAS_POSTGRES_REPAIR_PROGRESS_PATH"
BACKUP_PATH_ENV = "ATLAS_POSTGRES_BACKUP_057_PATH"
DATABASE_PREFIX = "atlas_pg_migration_chain_test_0046_"
LOCAL_POSTGRES_HOSTS = {"127.0.0.1", "::1", "localhost", "postgres"}
SOURCE_REVISION = "20260813_0045"
HEAD_REVISION = "20260815_0046"
EXPECTED_APPLICATION_ROWS = 1639
EXPECTED_BACKUP_SHA256 = (
    "014239052df4f913a0ab9c04fe118ab2d1f58758ee747a19e389b3b98da17282"
)
EXPECTED_COMPOSITION_SOURCE_SHA256 = (
    "8fc324478bf1685f1c2551620a96e23a08f7d0b6af6bad7a573715c226579b50"
)
EXPECTED_QA_RESULT_SHA256 = (
    "f69fd05e9eb851d1cdee95ae102dd4b8060e5aa7ad1b70b0c00e4b020cac5518"
)
EXPECTED_MEDIA_31_SHA256 = (
    "9f94d1ba555c2f3655bd600a61aac3247ab2a1a951a6cf73b1152d94fe40b2a0"
)


@dataclass
class _Database:
    name: str
    url: URL
    engine: Engine


class _PostgresPlan:
    def __init__(self, *, admin_url: URL, names: tuple[str, ...]) -> None:
        self.admin_url = admin_url
        self.names = names
        self.next_name = 0
        self.admin_engine = create_engine(
            admin_url,
            isolation_level="AUTOCOMMIT",
            poolclass=NullPool,
        )
        self.owned: list[_Database] = []

    def _consume_name(self) -> str:
        if self.next_name >= len(self.names):
            pytest.fail(
                f"{DATABASE_NAMES_ENV} was exhausted before every requested "
                "integration database could be acquired."
            )
        name = self.names[self.next_name]
        self.next_name += 1
        return name

    def _database(self, name: str) -> _Database:
        target_url = self.admin_url.set(database=name)
        database = _Database(
            name=name,
            url=target_url,
            engine=create_engine(
                target_url,
                connect_args={"options": "-c timezone=UTC"},
                pool_pre_ping=True,
                poolclass=NullPool,
            ),
        )
        self.owned.append(database)
        with database.engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT current_database()").scalar_one() == name
            assert int(
                connection.exec_driver_sql("SHOW server_version_num").scalar_one()
            ) // 10000 == 16
            assert connection.exec_driver_sql("SHOW TimeZone").scalar_one() == "UTC"
        return database

    def create(self) -> _Database:
        name = self._consume_name()
        with self.admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": name},
            ).scalar_one_or_none()
            assert exists is None, f"Disposable database already exists: {name}"
            connection.exec_driver_sql(
                f'CREATE DATABASE "{name}" TEMPLATE template0'
            )
        return self._database(name)

    def adopt_precreated(self) -> _Database:
        """Adopt an exact, operator-restored active-style disposable clone."""

        name = self._consume_name()
        with self.admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": name},
            ).scalar_one_or_none()
        assert exists == 1, (
            "The active-style integration database must be restored from the sealed "
            f"0045 dump before pytest starts: {name}"
        )
        return self._database(name)

    def close(self) -> None:
        failures: list[str] = []
        for database in reversed(self.owned):
            try:
                assert database.name in self.names
                assert database.name.startswith(DATABASE_PREFIX)
                database.engine.dispose(close=True)
                with self.admin_engine.connect() as connection:
                    connection.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) "
                            "FROM pg_stat_activity "
                            "WHERE datname = :name AND pid <> pg_backend_pid()"
                        ),
                        {"name": database.name},
                    )
                    connection.exec_driver_sql(
                        f'DROP DATABASE IF EXISTS "{database.name}"'
                    )
                    assert connection.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :name"),
                        {"name": database.name},
                    ).scalar_one_or_none() is None
            except Exception as exc:  # pragma: no cover - teardown diagnostics
                failures.append(f"{database.name}: {exc}")
        self.admin_engine.dispose(close=True)
        if self.next_name != len(self.names):
            failures.append(
                "unused ledgered names: " + ", ".join(self.names[self.next_name :])
            )
        assert not failures, "PostgreSQL integration cleanup failed: " + "; ".join(
            failures
        )


def _load_database_names() -> tuple[str, ...]:
    raw = os.getenv(DATABASE_NAMES_ENV)
    if not raw:
        pytest.fail(
            f"{DATABASE_NAMES_ENV} must be an ordered JSON list of names recorded "
            "in repair-progress.json before creation."
        )
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        pytest.fail(f"{DATABASE_NAMES_ENV} is not valid JSON: {exc}")
    if not isinstance(values, list) or not values:
        pytest.fail(f"{DATABASE_NAMES_ENV} must be a non-empty JSON list.")
    if not all(isinstance(value, str) for value in values):
        pytest.fail(f"Every {DATABASE_NAMES_ENV} entry must be a string.")
    names = tuple(values)
    if len(names) != len(set(names)):
        pytest.fail(f"{DATABASE_NAMES_ENV} contains duplicate names.")
    for name in names:
        if not name.startswith(DATABASE_PREFIX):
            pytest.fail(f"Disposable database lacks the task prefix: {name!r}.")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            pytest.fail(f"Unsafe disposable database name: {name!r}.")
        if len(name.encode("utf-8")) > 63:
            pytest.fail(f"Disposable database name exceeds 63 bytes: {name!r}.")
        if name.lower() in {"atlas", "postgres", "template0", "template1"}:
            pytest.fail(f"Protected database cannot be disposable: {name!r}.")
    return names


def _load_ledgered_names() -> set[str]:
    raw_path = os.getenv(LEDGER_PATH_ENV)
    if not raw_path:
        pytest.fail(
            f"{LEDGER_PATH_ENV} must identify the ignored repair-progress.json "
            "that was updated before any integration database was created."
        )
    path = Path(raw_path)
    if not path.is_file():
        pytest.fail(f"PostgreSQL repair ledger does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        pytest.fail(f"PostgreSQL repair ledger is unreadable: {exc}")
    records = payload.get("disposable_database_names")
    if not isinstance(records, list):
        pytest.fail("PostgreSQL repair ledger lacks disposable_database_names.")
    return {
        str(record["name"])
        for record in records
        if isinstance(record, dict)
        and isinstance(record.get("name"), str)
        and record.get("recorded_before_creation") is True
        and record.get("removed") is not True
    }


@pytest.fixture(scope="session")
def postgres_plan() -> Iterator[_PostgresPlan]:
    raw_admin_url = os.getenv(ADMIN_URL_ENV)
    if not raw_admin_url:
        pytest.skip(
            f"Set {ADMIN_URL_ENV} to an explicit local PostgreSQL administrative "
            "URL to run the schema-convergence integration matrix."
        )
    try:
        admin_url = make_url(raw_admin_url)
    except Exception as exc:
        pytest.fail(f"{ADMIN_URL_ENV} is not a valid URL: {exc}")
    if admin_url.get_backend_name() != "postgresql":
        pytest.fail("Schema-convergence integration requires PostgreSQL.")
    if (admin_url.host or "").lower() not in LOCAL_POSTGRES_HOSTS:
        pytest.fail("Schema-convergence integration refuses a non-local host.")
    if not admin_url.database or admin_url.database.lower() == "atlas":
        pytest.fail(
            "The PostgreSQL administrative URL must name a non-Atlas admin database."
        )

    names = _load_database_names()
    ledgered = _load_ledgered_names()
    missing = sorted(set(names) - ledgered)
    if missing:
        pytest.fail(
            "Every integration database must be ledgered before creation; missing: "
            + ", ".join(missing)
        )

    plan = _PostgresPlan(admin_url=admin_url, names=names)
    try:
        with plan.admin_engine.connect() as connection:
            assert int(
                connection.exec_driver_sql("SHOW server_version_num").scalar_one()
            ) // 10000 == 16
            can_create = connection.execute(
                text(
                    "SELECT rolsuper OR rolcreatedb "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).scalar_one()
            assert can_create is True
        yield plan
    finally:
        plan.close()


def _migration_module():
    path = (
        BACKEND
        / "alembic"
        / "versions"
        / "20260815_0046_postgresql_schema_convergence.py"
    )
    spec = importlib.util.spec_from_file_location(
        "atlas_migration_0046_integration", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def migration():
    return _migration_module()


@pytest.fixture
def accepted_backup_media_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    # The accepted operator backup was captured with the real loopback media
    # base.  The global test conftest deliberately substitutes testserver, so
    # restore validation must bind the backup's exact governed URL identity.
    monkeypatch.setenv("MEDIA_PUBLIC_URL", "http://localhost:8000/media")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@contextmanager
def _database_url(url: URL) -> Iterator[None]:
    previous = os.environ.get("DATABASE_URL")
    previous_pgoptions = os.environ.get("PGOPTIONS")
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    os.environ["PGOPTIONS"] = "-c timezone=UTC"
    get_settings.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        if previous_pgoptions is None:
            os.environ.pop("PGOPTIONS", None)
        else:
            os.environ["PGOPTIONS"] = previous_pgoptions
        get_settings.cache_clear()


def _alembic_config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def _upgrade(database: _Database, revision: str) -> None:
    with _database_url(database.url):
        command.upgrade(_alembic_config(), revision)


def _downgrade(database: _Database, revision: str) -> None:
    with _database_url(database.url):
        command.downgrade(_alembic_config(), revision)


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        )


def _manifest_sha256(engine: Engine, migration: Any) -> str:
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            return str(migration._catalog_manifest_sha256(connection))


def _surface(engine: Engine, migration: Any):
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            return migration._read_postgres_surface(connection)


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return {"datetime_utc": value.isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, time):
        return {"time": value.isoformat(timespec="microseconds")}
    if isinstance(value, timedelta):
        return {"timedelta_microseconds": int(value.total_seconds() * 1_000_000)}
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            return {"float": repr(value)}
        return value
    if isinstance(value, UUID):
        return {"uuid": str(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"bytes": bytes(value).hex()}
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return {"type": type(value).__name__, "value": str(value)}


def _data_fingerprints(engine: Engine) -> dict[str, tuple[int, str]]:
    fingerprints: dict[str, tuple[int, str]] = {}
    preparer = engine.dialect.identifier_preparer
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            tables = tuple(
                str(value)
                for value in connection.execute(
                    text(
                        "SELECT relation.relname "
                        "FROM pg_class AS relation "
                        "JOIN pg_namespace AS namespace "
                        "ON namespace.oid = relation.relnamespace "
                        "WHERE namespace.nspname = 'public' "
                        "AND relation.relkind IN ('r','p') "
                        "AND relation.relname <> 'alembic_version' "
                        "ORDER BY relation.relname"
                    )
                ).scalars()
            )
            for table in tables:
                columns = tuple(
                    str(value)
                    for value in connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = 'public' AND table_name = :table "
                            "ORDER BY column_name"
                        ),
                        {"table": table},
                    ).scalars()
                )
                quoted_columns = ", ".join(preparer.quote(column) for column in columns)
                quoted_table = preparer.quote(table)
                serialized_rows = []
                for row in connection.exec_driver_sql(
                    f"SELECT {quoted_columns} FROM {quoted_table}"
                ):
                    payload = {
                        column: _canonical_value(value)
                        for column, value in zip(columns, row, strict=True)
                    }
                    serialized_rows.append(
                        json.dumps(
                            payload,
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
                serialized_rows.sort()
                digest = hashlib.sha256(
                    "\n".join(serialized_rows).encode("utf-8")
                ).hexdigest()
                fingerprints[table] = (len(serialized_rows), digest)
    return fingerprints


def _sequence_state(engine: Engine) -> dict[str, tuple[int, bool]]:
    state: dict[str, tuple[int, bool]] = {}
    preparer = engine.dialect.identifier_preparer
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            names = tuple(
                str(value)
                for value in connection.execute(
                    text(
                        "SELECT relation.relname "
                        "FROM pg_class AS relation "
                        "JOIN pg_namespace AS namespace "
                        "ON namespace.oid = relation.relnamespace "
                        "WHERE namespace.nspname = 'public' "
                        "AND relation.relkind = 'S' ORDER BY relation.relname"
                    )
                ).scalars()
            )
            for name in names:
                last_value, is_called = connection.exec_driver_sql(
                    f"SELECT last_value, is_called FROM {preparer.quote(name)}"
                ).one()
                state[name] = (int(last_value), bool(is_called))
    return state


def _application_row_count(fingerprints: dict[str, tuple[int, str]]) -> int:
    return sum(count for count, _digest in fingerprints.values())


def _require_frozen_success_digests(migration: Any) -> None:
    pending = {
        variant: digest
        for variant, digest in migration.EXPECTED_CATALOG_MANIFEST_SHA256.items()
        if re.fullmatch(r"[0-9a-f]{64}", str(digest)) is None
    }
    assert pending == {}, (
        "Successful PostgreSQL convergence tests require independently frozen "
        f"clean, active, and canonical manifests; pending: {pending}"
    )


def _backup_path() -> Path:
    raw = os.getenv(BACKUP_PATH_ENV)
    if not raw:
        pytest.fail(
            f"{BACKUP_PATH_ENV} must identify the accepted Backup 0.57 artifact."
        )
    path = Path(raw)
    if not path.is_file():
        pytest.fail(f"Accepted Backup 0.57 artifact does not exist: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == EXPECTED_BACKUP_SHA256
    return path


def _restore_accepted_backup(engine: Engine, backup_path: Path) -> dict[str, Any]:
    from app.db.backup import restore_backup

    with Session(engine) as session:
        return restore_backup(session, backup_path)


def _rows(connection: Any, statement: str) -> tuple[tuple[Any, ...], ...]:
    return tuple(tuple(row) for row in connection.execute(text(statement)))


def _contains_excluded_media_32(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("excluded_media_ids") == [32]:
            return True
        return any(_contains_excluded_media_32(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_excluded_media_32(item) for item in value)
    return False


def _assert_production_form_registries_empty() -> None:
    from app.services import form_submission_contracts, form_submission_gateway

    assert dict(form_submission_contracts.FORM_SUBMISSION_PROVIDERS) == {}
    assert dict(form_submission_gateway.PRODUCTION_SUBMISSION_PROVIDERS) == {}
    assert dict(form_submission_gateway.PRODUCTION_SPAM_CONTROLS) == {}
    assert dict(form_submission_gateway.PRODUCTION_IDEMPOTENCY_BOUNDARIES) == {}


def _assert_accepted_application_identities(engine: Engine) -> None:
    """Assert the operator-accepted Backup 0.57 identities and safety absences."""

    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")

            assert _rows(
                connection,
                "SELECT id, website_id, theme_key, version, approval_status, "
                "lifecycle_status, token_hash_sha256 FROM theme ORDER BY id",
            ) == (
                (
                    1,
                    1,
                    "flo-zone-default",
                    1,
                    "approved",
                    "available",
                    "6cf9ab63471f66bd935bef75416c1a25674655f6f3b61ad6837120a5415819c6",
                ),
            )
            assert _rows(
                connection,
                "SELECT id, website_id, theme_id, version, status "
                "FROM websitethemeselection ORDER BY id",
            ) == ((1, 1, 1, 1, "active"),)

            assert _rows(
                connection,
                "SELECT id, family_key, display_name, lifecycle_status, "
                "provider_source_identity, integrity_fingerprint "
                "FROM themefamily ORDER BY id",
            ) == (
                (
                    1,
                    "performance-local",
                    "Performance Local",
                    "registered",
                    "Atlas source-defined Performance Local v2 registry",
                    "aa81cdb1503d46d428b4ea78a32274af1a26d33d772e00412ef282229cea37c7",
                ),
            )
            assert _rows(
                connection,
                "SELECT id, theme_family_id, version, lifecycle_status, "
                "production_ready, source_commit, integrity_fingerprint, "
                "compatibility_identity FROM themefamilyversion ORDER BY id",
            ) == (
                (
                    1,
                    1,
                    2,
                    "preview_candidate",
                    False,
                    "1b766664ea99d923195bbf98e8a1e4d833b50084",
                    "e18a8dd02e44e6627d3ac2fd879c27f7d77ec2e5f42c02a134f220cd8e9c3850",
                    "7253d5410454eac475b9792723222bcc35a0ab817504d0046efae5b44d324aa8",
                ),
            )
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM themefamilyversion AS version "
                    "JOIN themefamily AS family "
                    "ON family.id = version.theme_family_id "
                    "WHERE family.family_key = 'performance-local' "
                    "AND version.version = 3"
                )
            ).scalar_one() == 0

            assert _rows(
                connection,
                "SELECT id, website_id, theme_family_version_id, "
                "configuration_key, version, lifecycle_status, "
                "website_theme_selection_id, materialized_theme_id, "
                "activated_at, integrity_fingerprint "
                "FROM websitethemeconfiguration ORDER BY id",
            ) == (
                (
                    1,
                    1,
                    1,
                    "performance-local-draft",
                    1,
                    "draft",
                    None,
                    None,
                    None,
                    "1e8e71f40ff7fcfae3296d76ca2e073610b92c8044ee14346b7e66a748692873",
                ),
            )
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM websitethemeconfiguration AS config "
                    "JOIN themefamilyversion AS version "
                    "ON version.id = config.theme_family_version_id "
                    "JOIN themefamily AS family "
                    "ON family.id = version.theme_family_id "
                    "WHERE family.family_key = 'performance-local' AND ("
                    "config.lifecycle_status = 'active' "
                    "OR config.website_theme_selection_id IS NOT NULL "
                    "OR config.materialized_theme_id IS NOT NULL "
                    "OR config.activated_at IS NOT NULL)"
                )
            ).scalar_one() == 0

            assert _rows(
                connection,
                "SELECT id, website_theme_configuration_id, component_key, "
                "revision, lifecycle_status, integrity_fingerprint "
                "FROM websitethemecomponentconfiguration ORDER BY id",
            ) == (
                (
                    1,
                    1,
                    "compact_estimate_form",
                    1,
                    "current",
                    "f7a09dae04d6ecde0c15c3273c299987c95e28ba0d27df7e0ea26db7f76835ab",
                ),
                (
                    2,
                    1,
                    "campaign_banner",
                    1,
                    "current",
                    "fc1cf0c215fbaa9c270d098d64ad02e54900b383ff0fa9a9d521f0f9b3b2c5ef",
                ),
                (
                    3,
                    1,
                    "sticky_mobile_action_bar",
                    1,
                    "current",
                    "a8d474cede3d55c4851351daa24b5e1d3f3af410d5f6239b5b86262a9ba4e625",
                ),
            )
            assert _rows(
                connection,
                "SELECT id, website_theme_configuration_id, "
                "component_configuration_id, action_type "
                "FROM themeconfigurationaudit ORDER BY id",
            ) == (
                (1, None, None, "family_registered"),
                (2, None, None, "family_version_registered"),
                (3, 1, None, "website_draft_created"),
                (4, None, 1, "component_created"),
                (5, None, 2, "component_created"),
                (6, None, 3, "component_created"),
            )

            assert _rows(
                connection,
                "SELECT id, planned_page_id, generated_page_id, "
                "composition_version, status, source_hash "
                "FROM pagecomposition WHERE id = 41",
            ) == (
                (
                    41,
                    41,
                    41,
                    8,
                    "current",
                    EXPECTED_COMPOSITION_SOURCE_SHA256,
                ),
            )
            assert _rows(
                connection,
                "SELECT id, generated_page_id, planned_page_id, "
                "page_composition_id, composition_version, lifecycle_status, "
                "readiness_status, passed_count, warning_count, failed_count, "
                "composition_source_hash, result_hash "
                "FROM generatedpageqaresult WHERE id = 80",
            ) == (
                (
                    80,
                    41,
                    41,
                    41,
                    8,
                    "current",
                    "ready",
                    23,
                    0,
                    0,
                    EXPECTED_COMPOSITION_SOURCE_SHA256,
                    EXPECTED_QA_RESULT_SHA256,
                ),
            )

            assert _rows(
                connection,
                "SELECT id, wordpress_media_id, wordpress_media_status, "
                "file_name, asset_url, review_status, wordpress_media_checksum "
                "FROM imagemetadata WHERE wordpress_media_id = 31",
            ) == (
                (
                    1,
                    31,
                    "reconciled",
                    "orlando-drywood-termite-tenting.jpg",
                    "/media/orlando-drywood-termite-tenting-hero.png",
                    "reviewed",
                    EXPECTED_MEDIA_31_SHA256,
                ),
            )
            assert connection.execute(
                text("SELECT COUNT(*) FROM imagemetadata WHERE wordpress_media_id = 32")
            ).scalar_one() == 0
            media_gate_results = connection.execute(
                text(
                    "SELECT gate_results FROM wordpressmediasyncaudit "
                    "WHERE id = 4 AND wordpress_media_id = 31"
                )
            ).scalar_one()
            assert _contains_excluded_media_32(media_gate_results)

            table_names = tuple(
                str(name)
                for name in connection.execute(
                    text(
                        "SELECT relation.relname FROM pg_class AS relation "
                        "JOIN pg_namespace AS namespace "
                        "ON namespace.oid = relation.relnamespace "
                        "WHERE namespace.nspname = 'public' "
                        "AND relation.relkind IN ('r','p')"
                    )
                ).scalars()
            )
            customer_or_submission_tables = tuple(
                name
                for name in table_names
                if re.search(
                    r"(?:customer|form.*submission|submission.*form|"
                    r"lead.*submission)",
                    name,
                )
            )
            assert customer_or_submission_tables == ()

    _assert_production_form_registries_empty()


def test_postgresql_active_style_0045_upgrade_preserves_every_row_and_sequence(
    postgres_plan: _PostgresPlan,
    migration: Any,
) -> None:
    _require_frozen_success_digests(migration)
    database = postgres_plan.adopt_precreated()
    assert _revision(database.engine) == SOURCE_REVISION
    source = _surface(database.engine, migration)
    assert migration._classify_postgres_surface(source) == "active"
    assert source.catalog_manifest_sha256 == (
        migration.EXPECTED_CATALOG_MANIFEST_SHA256["active"]
    )
    assert len(source.tables) == 65
    assert len(source.sequences) == 64

    before_data = _data_fingerprints(database.engine)
    before_sequences = _sequence_state(database.engine)
    assert _application_row_count(before_data) == EXPECTED_APPLICATION_ROWS
    _assert_accepted_application_identities(database.engine)

    _upgrade(database, HEAD_REVISION)

    assert _revision(database.engine) == HEAD_REVISION
    assert _surface(database.engine, migration) == migration._expected_postgres_surface(
        "canonical"
    )
    assert _data_fingerprints(database.engine) == before_data
    assert _sequence_state(database.engine) == before_sequences
    _assert_accepted_application_identities(database.engine)


def test_postgresql_active_blocked_disposition_fails_before_mutation_or_remap(
    postgres_plan: _PostgresPlan,
    migration: Any,
) -> None:
    _require_frozen_success_digests(migration)
    database = postgres_plan.adopt_precreated()
    assert _revision(database.engine) == SOURCE_REVISION
    assert _surface(database.engine, migration) == migration._expected_postgres_surface(
        "active"
    )
    assert _application_row_count(
        _data_fingerprints(database.engine)
    ) == EXPECTED_APPLICATION_ROWS
    _assert_accepted_application_identities(database.engine)

    with database.engine.begin() as connection:
        inserted = connection.execute(
            text(
                "INSERT INTO draftingeligibilitydisposition ("
                "created_at, updated_at, id, website_id, site_plan_id, "
                "planned_page_id, assessment_id, decision, rationale, "
                "decided_by, accepted_exception, decision_version, decided_at"
                ") SELECT TIMESTAMP '2026-08-16 00:00:00', "
                "TIMESTAMP '2026-08-16 00:00:00', "
                "nextval('draftingeligibilitydisposition_id_seq'), "
                "assessment.website_id, assessment.site_plan_id, "
                "assessment.planned_page_id, assessment.id, 'blocked', "
                "'0046 fail-closed data-preflight probe', "
                "'Project Atlas integration test', false, 1, "
                "TIMESTAMP '2026-08-16 00:00:00' "
                "FROM draftingeligibilityassessment AS assessment "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM draftingeligibilitydisposition AS disposition "
                "WHERE disposition.planned_page_id = assessment.planned_page_id"
                ") ORDER BY assessment.id LIMIT 1 "
                "RETURNING id, decision"
            )
        ).one()
    inserted_id = int(inserted[0])
    assert str(inserted[1]) == "blocked"
    assert _surface(database.engine, migration) == migration._expected_postgres_surface(
        "active"
    )

    before_manifest = _manifest_sha256(database.engine, migration)
    before_data = _data_fingerprints(database.engine)
    before_sequences = _sequence_state(database.engine)
    assert _application_row_count(before_data) == EXPECTED_APPLICATION_ROWS + 1

    with pytest.raises(
        RuntimeError,
        match="cannot replace the disposition vocabulary",
    ):
        _upgrade(database, HEAD_REVISION)

    assert _revision(database.engine) == SOURCE_REVISION
    assert _manifest_sha256(database.engine, migration) == before_manifest
    assert _surface(database.engine, migration) == migration._expected_postgres_surface(
        "active"
    )
    assert _data_fingerprints(database.engine) == before_data
    assert _sequence_state(database.engine) == before_sequences
    _assert_accepted_application_identities(database.engine)
    with database.engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM draftingeligibilitydisposition "
                "WHERE id = :id AND decision = 'blocked'"
            ),
            {"id": inserted_id},
        ).scalar_one() == 1


def test_postgresql_backup_057_restores_to_head_and_repeats_exactly(
    postgres_plan: _PostgresPlan,
    migration: Any,
    accepted_backup_media_settings: None,
    tmp_path: Path,
) -> None:
    from app.db.backup import (
        BACKUP_VERSION,
        _restore_managed_tables_are_empty,
        export_backup,
        load_backup,
    )

    _require_frozen_success_digests(migration)
    backup_path = _backup_path()
    payload = load_backup(backup_path)
    assert BACKUP_VERSION == "0.57"
    assert payload["metadata"]["version"] == "0.57"
    assert sum(payload["metadata"]["table_counts"].values()) == (
        EXPECTED_APPLICATION_ROWS
    )

    database = postgres_plan.create()
    _upgrade(database, HEAD_REVISION)
    assert _revision(database.engine) == HEAD_REVISION
    canonical_manifest = _manifest_sha256(database.engine, migration)
    assert canonical_manifest == migration.EXPECTED_CATALOG_MANIFEST_SHA256[
        "canonical"
    ]
    migration_owned_rows = _data_fingerprints(database.engine)
    assert _application_row_count(migration_owned_rows) == 15
    assert migration_owned_rows["semanticcomponentdefinition"][0] == 15
    assert all(
        count == 0
        for table, (count, _digest) in migration_owned_rows.items()
        if table != "semanticcomponentdefinition"
    )
    with Session(database.engine) as session:
        from app.models.entities import SemanticComponentDefinition

        fields = (
            "id",
            "component_key",
            "contract_version",
            "purpose",
            "required_inputs",
            "customer_outcome",
            "compatible_page_types",
            "supported_variants",
            "accessibility_requirements",
            "status",
        )
        observed_contracts = {
            record.component_key: tuple(
                tuple(value) if isinstance(value, list) else value
                for value in (getattr(record, field) for field in fields)
            )
            for record in session.exec(select(SemanticComponentDefinition)).all()
        }
        expected_contracts = {
            record["component_key"]: tuple(
                tuple(record[field]) if isinstance(record[field], list) else record[field]
                for field in fields
            )
            for record in payload["data"]["semantic_component_definitions"]
        }
        assert observed_contracts.keys() == expected_contracts.keys()
        assert observed_contracts["related_page_links"][3] == (
            "Present approved contextual page relationships."
        )
        assert expected_contracts["related_page_links"][3] == (
            "Present operator-approved contextual page relationships."
        )
        observed_contracts["related_page_links"] = (
            *observed_contracts["related_page_links"][:3],
            expected_contracts["related_page_links"][3],
            *observed_contracts["related_page_links"][4:],
        )
        assert observed_contracts == expected_contracts
        assert _restore_managed_tables_are_empty(session, payload["data"]) is True

    first = _restore_accepted_backup(database.engine, backup_path)
    assert first["records_processed"] == EXPECTED_APPLICATION_ROWS
    first_data = _data_fingerprints(database.engine)
    first_sequences = _sequence_state(database.engine)
    assert _application_row_count(first_data) == EXPECTED_APPLICATION_ROWS
    assert _manifest_sha256(database.engine, migration) == canonical_manifest
    _assert_accepted_application_identities(database.engine)

    second = _restore_accepted_backup(database.engine, backup_path)
    assert second["records_processed"] == EXPECTED_APPLICATION_ROWS
    assert _data_fingerprints(database.engine) == first_data
    assert _sequence_state(database.engine) == first_sequences
    assert _manifest_sha256(database.engine, migration) == canonical_manifest
    _assert_accepted_application_identities(database.engine)

    with Session(database.engine) as session:
        exported = export_backup(session, backup_dir=tmp_path)
    exported_payload = load_backup(Path(exported["path"]))
    assert exported_payload["metadata"]["version"] == "0.57"
    assert exported_payload["metadata"]["table_counts"] == payload["metadata"][
        "table_counts"
    ]
    assert _data_fingerprints(database.engine) == first_data
    assert _sequence_state(database.engine) == first_sequences

    _upgrade(database, "head")
    assert _revision(database.engine) == HEAD_REVISION
    assert _manifest_sha256(database.engine, migration) == canonical_manifest
    assert _data_fingerprints(database.engine) == first_data
    assert _sequence_state(database.engine) == first_sequences
    _assert_accepted_application_identities(database.engine)


def test_postgresql_startup_is_schema_noop_and_second_start_is_idempotent(
    postgres_plan: _PostgresPlan,
    migration: Any,
    accepted_backup_media_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as app_main
    from app.db import session as db_session

    _require_frozen_success_digests(migration)
    database = postgres_plan.create()
    _upgrade(database, HEAD_REVISION)
    _restore_accepted_backup(database.engine, _backup_path())

    before_manifest = _manifest_sha256(database.engine, migration)
    before_data = _data_fingerprints(database.engine)
    before_sequences = _sequence_state(database.engine)
    assert _application_row_count(before_data) == EXPECTED_APPLICATION_ROWS
    _assert_accepted_application_identities(database.engine)

    monkeypatch.setattr(db_session, "engine", database.engine)
    monkeypatch.setattr(app_main, "engine", database.engine)
    monkeypatch.setattr(app_main.settings, "seed_on_startup", True)

    with TestClient(app_main.app) as client:
        assert client.get("/health").json()["status"] == "ok"
    after_first_manifest = _manifest_sha256(database.engine, migration)
    after_first_data = _data_fingerprints(database.engine)
    after_first_sequences = _sequence_state(database.engine)
    assert {
        table: count for table, (count, _digest) in after_first_data.items()
    } == {table: count for table, (count, _digest) in before_data.items()}
    assert after_first_sequences == before_sequences
    _assert_accepted_application_identities(database.engine)

    with TestClient(app_main.app) as client:
        assert client.get("/health").json()["status"] == "ok"
    _assert_accepted_application_identities(database.engine)

    assert _revision(database.engine) == HEAD_REVISION
    assert after_first_manifest == before_manifest
    assert _manifest_sha256(database.engine, migration) == before_manifest
    # The first seed-enabled start may legitimately refresh ordinary seed-owned
    # values in this disposable restore target.  Idempotency means the second
    # independent start produces no further row or sequence change.
    assert _data_fingerprints(database.engine) == after_first_data
    assert _sequence_state(database.engine) == after_first_sequences


def test_postgresql_0046_downgrade_fails_before_schema_data_or_sequence_change(
    postgres_plan: _PostgresPlan,
    migration: Any,
) -> None:
    _require_frozen_success_digests(migration)
    database = postgres_plan.create()
    _upgrade(database, HEAD_REVISION)
    before_manifest = _manifest_sha256(database.engine, migration)
    before_data = _data_fingerprints(database.engine)
    before_sequences = _sequence_state(database.engine)

    with pytest.raises(RuntimeError, match="intentionally irreversible"):
        _downgrade(database, SOURCE_REVISION)

    assert _revision(database.engine) == HEAD_REVISION
    assert _manifest_sha256(database.engine, migration) == before_manifest
    assert _data_fingerprints(database.engine) == before_data
    assert _sequence_state(database.engine) == before_sequences


UNKNOWN_MUTATIONS: dict[str, tuple[str, ...]] = {
    "table": ("ALTER TABLE business SET (fillfactor = 80)",),
    "column_type": (
        "ALTER TABLE business ALTER COLUMN description "
        "TYPE text USING description::text",
    ),
    "column_default": (
        "ALTER TABLE business ALTER COLUMN description "
        "SET DEFAULT 'unexpected'",
    ),
    "column_nullability": (
        "ALTER TABLE business ALTER COLUMN description SET NOT NULL",
    ),
    "column_collation": (
        'ALTER TABLE business ALTER COLUMN description TYPE varchar COLLATE "C" '
        "USING description::varchar",
    ),
    "primary": (
        "ALTER TABLE business RENAME CONSTRAINT business_pkey "
        "TO business_pkey_unexpected",
    ),
    "unique": (
        "ALTER TABLE siteplan RENAME CONSTRAINT uq_siteplan_website_key "
        "TO uq_siteplan_website_key_unexpected",
    ),
    "check": (
        "ALTER TABLE themefamilyversion RENAME CONSTRAINT "
        "ck_themefamilyversion_version TO ck_themefamilyversion_version_unexpected",
    ),
    "foreign_key_name": (
        "ALTER TABLE generatedpage RENAME CONSTRAINT "
        "generatedpage_business_id_fkey TO generatedpage_business_id_fkey_unexpected",
    ),
    "foreign_key_action": (
        "ALTER TABLE generatedpage DROP CONSTRAINT generatedpage_business_id_fkey",
        "ALTER TABLE generatedpage ADD CONSTRAINT generatedpage_business_id_fkey "
        "FOREIGN KEY (business_id) REFERENCES business(id) ON DELETE CASCADE",
    ),
    "index": (
        "ALTER INDEX ix_business_company_name SET (fillfactor = 70)",
    ),
    "index_opclass": (
        "DROP INDEX ix_business_company_name",
        "CREATE INDEX ix_business_company_name "
        "ON business (company_name varchar_pattern_ops)",
    ),
    "index_order": (
        "DROP INDEX ix_business_company_name",
        "CREATE INDEX ix_business_company_name ON business (company_name DESC)",
    ),
    "index_predicate": (
        "DROP INDEX ix_business_company_name",
        "CREATE INDEX ix_business_company_name "
        "ON business (company_name) WHERE id > 0",
    ),
    "index_include": (
        "DROP INDEX ix_business_company_name",
        "CREATE INDEX ix_business_company_name "
        "ON business (company_name) INCLUDE (description)",
    ),
    "sequence_cache": ("ALTER SEQUENCE business_id_seq CACHE 7",),
    "sequence_owner": ("ALTER SEQUENCE business_id_seq OWNED BY NONE",),
    "rls": ("ALTER TABLE business ENABLE ROW LEVEL SECURITY",),
}


@pytest.mark.parametrize("mutation", tuple(UNKNOWN_MUTATIONS), ids=tuple(UNKNOWN_MUTATIONS))
def test_postgresql_unknown_0045_near_match_fails_before_mutation(
    postgres_plan: _PostgresPlan,
    migration: Any,
    mutation: str,
) -> None:
    database = postgres_plan.create()
    _upgrade(database, SOURCE_REVISION)
    assert _revision(database.engine) == SOURCE_REVISION
    assert migration._classify_postgres_surface(
        _surface(database.engine, migration)
    ) == "clean"

    with database.engine.begin() as connection:
        for statement in UNKNOWN_MUTATIONS[mutation]:
            connection.exec_driver_sql(statement)

    before_manifest = _manifest_sha256(database.engine, migration)
    before_data = _data_fingerprints(database.engine)
    before_sequences = _sequence_state(database.engine)
    assert before_manifest != migration.EXPECTED_CATALOG_MANIFEST_SHA256["clean"]

    with pytest.raises(
        RuntimeError,
        match="unknown PostgreSQL 0045 schema before DDL",
    ):
        _upgrade(database, HEAD_REVISION)

    assert _revision(database.engine) == SOURCE_REVISION
    assert _manifest_sha256(database.engine, migration) == before_manifest
    assert _data_fingerprints(database.engine) == before_data
    assert _sequence_state(database.engine) == before_sequences
    with database.engine.connect() as connection:
        assert connection.execute(
            text("SELECT to_regclass('public.wordpressmetadatastate')")
        ).scalar_one() is None
        assert connection.execute(
            text("SELECT to_regclass('public.wordpressmetadatasyncaudit')")
        ).scalar_one() is None
        assert connection.execute(
            text("SELECT to_regclass('public.wordpressqualityreview')")
        ).scalar_one() is None
