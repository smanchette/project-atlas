from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from threading import Event
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.pool import NullPool
from sqlmodel import Session, select

from app.core.config import get_settings
from app.models import (
    Business,
    ThemeFamily,
    ThemeFamilyVersion,
    Website,
    WebsiteThemeComponentConfiguration,
    WebsiteThemeConfiguration,
    WebsiteFormDeliveryModeRevision,
)
from app.schemas.form_delivery import (
    WebsiteFormDeliveryModeRevisionCreate,
    WebsiteFormRecipientRevisionCreate,
)
from app.services.form_delivery_modes import (
    FormDeliveryConfigurationError,
    create_form_delivery_mode_revision,
    create_form_recipient_revision,
    form_delivery_readiness,
    validate_form_delivery_records,
)
from app.services.form_delivery_outbox import enqueue_form_delivery
from app.services.form_delivery_registry import SYNTHETIC_EMAIL_PROVIDER_KEY
from app.services.form_payload_store import InMemoryTestPayloadStore
from app.website_builder_core.contracts import NormalizedSubmissionEnvelope


BACKEND = Path(__file__).parents[1]
POSTGRES_ADMIN_URL_ENV = "ATLAS_DISPOSABLE_POSTGRES_ADMIN_URL"
POSTGRES_DATABASE_NAMES_ENV = "ATLAS_DISPOSABLE_POSTGRES_DATABASE_NAMES"
LEDGER_PATH_ENV = "ATLAS_POSTGRES_REPAIR_PROGRESS_PATH"
DISPOSABLE_DATABASE_PREFIX = "atlas_pg_migration_chain_test_0047_"
LOCAL_POSTGRES_HOSTS = {"127.0.0.1", "::1", "localhost", "postgres"}
HEAD_REVISION = "20260817_0047"
EXPECTED_TABLE_COUNT = 71
EXPECTED_SEQUENCE_COUNT = 70
FORM_DELIVERY_TABLES = {
    "websiteformdeliverymoderevision",
    "websiteformrecipientrevision",
    "formsubmissionenvelope",
    "formdeliveryoutbox",
    "formdeliveryattempt",
    "formdeliveryconfigurationaudit",
}


@dataclass(frozen=True)
class _ExpectedIndex:
    table: str
    column: str


EXPECTED_REPAIRED_INDEXES = {
    "ix_wordpressbootstrapcleanupaudit_deactivation_handle_f_fc62": (
        _ExpectedIndex(
            "wordpressbootstrapcleanupaudit",
            "deactivation_handle_fingerprint",
        )
    ),
    "ix_wordpresscacheawarerenderingaudit_rendering_handle_f_e1fc": (
        _ExpectedIndex(
            "wordpresscacheawarerenderingaudit",
            "rendering_handle_fingerprint",
        )
    ),
    "ix_wordpressbootstrapestablishmentaudit_manual_handle_f_6138": (
        _ExpectedIndex(
            "wordpressbootstrapestablishmentaudit",
            "manual_handle_fingerprint",
        )
    ),
    "ix_wordpressbootstrapestablishmentaudit_activation_hand_a9b8": (
        _ExpectedIndex(
            "wordpressbootstrapestablishmentaudit",
            "activation_handle_fingerprint",
        )
    ),
}


@dataclass
class _DisposableDatabase:
    name: str
    url: URL
    engine: Engine


def _load_ledgered_database_names() -> set[str]:
    raw_path = os.getenv(LEDGER_PATH_ENV)
    if not raw_path:
        pytest.fail(
            f"{LEDGER_PATH_ENV} must identify the ignored repair-progress.json "
            "that was updated before any migration-chain database is created."
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


def test_migration_chain_ledger_reader_accepts_only_live_prerecorded_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    live_name = f"{DISPOSABLE_DATABASE_PREFIX}ledger_reader_live"
    removed_name = f"{DISPOSABLE_DATABASE_PREFIX}ledger_reader_removed"
    unrecorded_name = f"{DISPOSABLE_DATABASE_PREFIX}ledger_reader_unrecorded"
    ledger_path = tmp_path / "repair-progress.json"
    ledger_path.write_text(
        json.dumps(
            {
                "disposable_database_names": [
                    {
                        "name": live_name,
                        "recorded_before_creation": True,
                        "removed": False,
                    },
                    {
                        "name": removed_name,
                        "recorded_before_creation": True,
                        "removed": True,
                    },
                    {
                        "name": unrecorded_name,
                        "recorded_before_creation": False,
                        "removed": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(LEDGER_PATH_ENV, str(ledger_path))

    assert _load_ledgered_database_names() == {live_name}


@pytest.fixture(scope="session")
def disposable_postgres_database_factory() -> Iterator[
    Callable[[], _DisposableDatabase]
]:
    admin_url_value = os.getenv(POSTGRES_ADMIN_URL_ENV)
    if not admin_url_value:
        pytest.skip(
            f"Set {POSTGRES_ADMIN_URL_ENV} to an explicit local PostgreSQL "
            "administrative URL to run the migration-chain regressions."
        )

    database_names_value = os.getenv(POSTGRES_DATABASE_NAMES_ENV)
    if not database_names_value:
        pytest.fail(
            f"{POSTGRES_DATABASE_NAMES_ENV} must be an ordered JSON list of "
            "exact database names recorded in the task ledger before creation."
        )
    try:
        database_names = json.loads(database_names_value)
    except json.JSONDecodeError as exc:
        pytest.fail(f"{POSTGRES_DATABASE_NAMES_ENV} is not valid JSON: {exc}")
    if not isinstance(database_names, list) or not database_names:
        pytest.fail(f"{POSTGRES_DATABASE_NAMES_ENV} must be a non-empty JSON list.")
    if not all(isinstance(name, str) for name in database_names):
        pytest.fail(f"Every {POSTGRES_DATABASE_NAMES_ENV} entry must be a string.")
    if len(database_names) != len(set(database_names)):
        pytest.fail(f"{POSTGRES_DATABASE_NAMES_ENV} contains duplicate names.")
    for database_name in database_names:
        if not database_name.startswith(DISPOSABLE_DATABASE_PREFIX):
            pytest.fail(
                f"Disposable database name lacks the task prefix: {database_name!r}."
            )
        if not re.fullmatch(r"[a-z][a-z0-9_]*", database_name):
            pytest.fail(f"Unsafe disposable database name: {database_name!r}.")
        if len(database_name.encode("utf-8")) > 63:
            pytest.fail(f"Disposable database name exceeds 63 bytes: {database_name!r}.")
        if database_name.lower() == "atlas":
            pytest.fail("The active Atlas database cannot be disposable.")

    ledgered_database_names = _load_ledgered_database_names()
    missing_ledger_entries = sorted(set(database_names) - ledgered_database_names)
    if missing_ledger_entries:
        pytest.fail(
            "Every migration-chain database must be ledgered before creation; "
            "missing: " + ", ".join(missing_ledger_entries)
        )

    try:
        admin_url = make_url(admin_url_value)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.fail(f"{POSTGRES_ADMIN_URL_ENV} is not a valid database URL: {exc}")
    if admin_url.get_backend_name() != "postgresql":
        pytest.fail("The migration-chain regressions require PostgreSQL.")
    if (admin_url.host or "").lower() not in LOCAL_POSTGRES_HOSTS:
        pytest.fail(
            "The migration-chain regressions refuse a non-local PostgreSQL host."
        )
    if not admin_url.database:
        pytest.fail("The PostgreSQL administrative URL must name a database.")
    if admin_url.database.lower() == "atlas":
        pytest.fail(
            "The migration-chain regressions refuse the active Atlas database."
        )

    admin_engine = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    created: list[_DisposableDatabase] = []
    next_database_name = 0
    with admin_engine.connect() as connection:
        can_create_database = connection.execute(
            text(
                "SELECT rolsuper OR rolcreatedb "
                "FROM pg_roles WHERE rolname = current_user"
            )
        ).scalar_one()
    if not can_create_database:
        admin_engine.dispose(close=True)
        pytest.fail(
            f"{POSTGRES_ADMIN_URL_ENV} must identify a local role with CREATEDB."
        )

    def create_database() -> _DisposableDatabase:
        nonlocal next_database_name
        if next_database_name >= len(database_names):
            pytest.fail(
                f"{POSTGRES_DATABASE_NAMES_ENV} was exhausted before every requested "
                "disposable database could be created."
            )
        database_name = database_names[next_database_name]
        next_database_name += 1
        target_url = admin_url.set(database=database_name)
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            ).scalar_one_or_none()
            assert exists is None
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        database = _DisposableDatabase(
            name=database_name,
            url=target_url,
            engine=create_engine(
                target_url,
                pool_pre_ping=True,
                poolclass=NullPool,
            ),
        )
        created.append(database)
        return database

    try:
        yield create_database
    finally:
        cleanup_failures: list[str] = []
        for database in reversed(created):
            try:
                assert database.name.startswith(DISPOSABLE_DATABASE_PREFIX)
                database.engine.dispose(close=True)
                with admin_engine.connect() as connection:
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
                    remaining = connection.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :name"),
                        {"name": database.name},
                    ).scalar_one_or_none()
                    assert remaining is None
            except Exception as exc:  # pragma: no cover - teardown diagnostics
                cleanup_failures.append(f"{database.name}: {exc}")
        admin_engine.dispose(close=True)
        assert not cleanup_failures, "Disposable database cleanup failed: " + "; ".join(
            cleanup_failures
        )
        assert next_database_name == len(database_names), (
            f"{POSTGRES_DATABASE_NAMES_ENV} contained unused ledgered names: "
            + ", ".join(database_names[next_database_name:])
        )


@contextmanager
def _alembic_database_url(url: URL) -> Iterator[None]:
    rendered_url = url.render_as_string(hide_password=False)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = rendered_url
    get_settings.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def _alembic_config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def _upgrade(database: _DisposableDatabase, revision: str) -> None:
    with _alembic_database_url(database.url):
        command.upgrade(_alembic_config(), revision)


def _downgrade(database: _DisposableDatabase, revision: str) -> None:
    with _alembic_database_url(database.url):
        command.downgrade(_alembic_config(), revision)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, bytes):
        return value.hex()
    return value


CATALOG_QUERIES = {
    "tables": """
        SELECT relation.relname,
               relation.relkind,
               relation.relpersistence,
               relation.relrowsecurity,
               relation.relforcerowsecurity
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p')
        ORDER BY relation.relname
    """,
    "columns": """
        SELECT relation.relname,
               attribute.attname,
               pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
               attribute.attnotnull,
               COALESCE(
                   pg_get_expr(default_record.adbin, default_record.adrelid, true),
                   ''
               ),
               attribute.attidentity,
               attribute.attgenerated,
               COALESCE(collation_record.collname, '')
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_attribute AS attribute ON attribute.attrelid = relation.oid
        LEFT JOIN pg_attrdef AS default_record
               ON default_record.adrelid = relation.oid
              AND default_record.adnum = attribute.attnum
        LEFT JOIN pg_collation AS collation_record
               ON collation_record.oid = attribute.attcollation
              AND attribute.attcollation <> 0
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p')
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
        ORDER BY relation.relname, attribute.attname
    """,
    "constraints": """
        SELECT relation.relname,
               constraint_record.conname,
               constraint_record.contype,
               pg_get_constraintdef(constraint_record.oid, true),
               constraint_record.condeferrable,
               constraint_record.condeferred,
               constraint_record.convalidated,
               constraint_record.confmatchtype,
               constraint_record.confupdtype,
               constraint_record.confdeltype
        FROM pg_constraint AS constraint_record
        JOIN pg_class AS relation ON relation.oid = constraint_record.conrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
        ORDER BY relation.relname,
                 constraint_record.contype,
                 constraint_record.conname
    """,
    "indexes": """
        SELECT table_relation.relname,
               index_relation.relname,
               access_method.amname,
               index_record.indisunique,
               index_record.indisprimary,
               index_record.indisvalid,
               index_record.indisready,
               index_record.indnkeyatts,
               index_record.indnatts,
               pg_get_indexdef(index_record.indexrelid, 0, true),
               COALESCE(
                   pg_get_expr(
                       index_record.indpred,
                       index_record.indrelid,
                       true
                   ),
                   ''
               ),
               COALESCE(
                   pg_get_expr(
                       index_record.indexprs,
                       index_record.indrelid,
                       true
                   ),
                   ''
               )
        FROM pg_index AS index_record
        JOIN pg_class AS index_relation
          ON index_relation.oid = index_record.indexrelid
        JOIN pg_class AS table_relation
          ON table_relation.oid = index_record.indrelid
        JOIN pg_namespace AS namespace
          ON namespace.oid = table_relation.relnamespace
        JOIN pg_am AS access_method
          ON access_method.oid = index_relation.relam
        WHERE namespace.nspname = 'public'
        ORDER BY table_relation.relname, index_relation.relname
    """,
    "index_attributes": """
        SELECT table_relation.relname,
               index_relation.relname,
               slot.slot_number,
               CASE
                   WHEN slot.slot_number < index_record.indnkeyatts THEN 'key'
                   ELSE 'included'
               END,
               COALESCE(attribute.attname, ''),
               COALESCE(operator_class.opcname, ''),
               COALESCE(operator_class.opcdefault, false),
               index_record.indoption[slot.slot_number],
               COALESCE(collation_record.collname, '')
        FROM pg_index AS index_record
        JOIN pg_class AS index_relation
          ON index_relation.oid = index_record.indexrelid
        JOIN pg_class AS table_relation
          ON table_relation.oid = index_record.indrelid
        JOIN pg_namespace AS namespace
          ON namespace.oid = table_relation.relnamespace
        CROSS JOIN LATERAL generate_series(
            0,
            index_record.indnatts - 1
        ) AS slot(slot_number)
        LEFT JOIN pg_attribute AS attribute
          ON attribute.attrelid = index_record.indrelid
         AND attribute.attnum = index_record.indkey[slot.slot_number]
        LEFT JOIN pg_opclass AS operator_class
          ON operator_class.oid = index_record.indclass[slot.slot_number]
        LEFT JOIN pg_collation AS collation_record
          ON collation_record.oid = index_record.indcollation[slot.slot_number]
        WHERE namespace.nspname = 'public'
        ORDER BY table_relation.relname,
                 index_relation.relname,
                 slot.slot_number
    """,
    "sequences": """
        SELECT sequence_relation.relname,
               pg_catalog.format_type(sequence_record.seqtypid, NULL),
               sequence_record.seqstart,
               sequence_record.seqincrement,
               sequence_record.seqmax,
               sequence_record.seqmin,
               sequence_record.seqcache,
               sequence_record.seqcycle,
               COALESCE(owner_relation.relname, ''),
               COALESCE(owner_attribute.attname, ''),
               COALESCE(dependency.deptype::text, '')
        FROM pg_sequence AS sequence_record
        JOIN pg_class AS sequence_relation
          ON sequence_relation.oid = sequence_record.seqrelid
        JOIN pg_namespace AS namespace
          ON namespace.oid = sequence_relation.relnamespace
        LEFT JOIN pg_depend AS dependency
          ON dependency.classid = 'pg_class'::regclass
         AND dependency.objid = sequence_relation.oid
         AND dependency.objsubid = 0
         AND dependency.refclassid = 'pg_class'::regclass
         AND dependency.deptype IN ('a', 'i')
        LEFT JOIN pg_class AS owner_relation
          ON owner_relation.oid = dependency.refobjid
        LEFT JOIN pg_attribute AS owner_attribute
          ON owner_attribute.attrelid = dependency.refobjid
         AND owner_attribute.attnum = dependency.refobjsubid
        WHERE namespace.nspname = 'public'
        ORDER BY sequence_relation.relname
    """,
    "enums": """
        SELECT type_record.typname,
               enum_record.enumsortorder,
               enum_record.enumlabel
        FROM pg_type AS type_record
        JOIN pg_namespace AS namespace
          ON namespace.oid = type_record.typnamespace
        JOIN pg_enum AS enum_record
          ON enum_record.enumtypid = type_record.oid
        WHERE namespace.nspname = 'public'
        ORDER BY type_record.typname, enum_record.enumsortorder
    """,
    "views": """
        SELECT relation.relname,
               relation.relkind,
               pg_get_viewdef(relation.oid, true)
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('v', 'm')
        ORDER BY relation.relname
    """,
}


def test_catalog_snapshot_column_contract_ignores_physical_ordinals() -> None:
    query = " ".join(CATALOG_QUERIES["columns"].split())
    projection = query.split(" FROM pg_class AS relation", maxsplit=1)[0]
    assert "attribute.attnum" not in projection
    assert query.endswith("ORDER BY relation.relname, attribute.attname")


def _catalog_snapshot(engine: Engine) -> dict[str, tuple[tuple[Any, ...], ...]]:
    snapshot: dict[str, tuple[tuple[Any, ...], ...]] = {}
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            for label, query in CATALOG_QUERIES.items():
                snapshot[label] = tuple(
                    tuple(_freeze(value) for value in row)
                    for row in connection.execute(text(query))
                )
    return snapshot


def _application_data_fingerprints(engine: Engine) -> dict[str, tuple[int, str]]:
    fingerprints: dict[str, tuple[int, str]] = {}
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            table_names = tuple(
                str(name)
                for name in connection.execute(
                    text(
                        "SELECT relation.relname FROM pg_class AS relation "
                        "JOIN pg_namespace AS namespace "
                        "ON namespace.oid = relation.relnamespace "
                        "WHERE namespace.nspname = 'public' "
                        "AND relation.relkind IN ('r','p') "
                        "AND relation.relname <> 'alembic_version' "
                        "ORDER BY relation.relname"
                    )
                ).scalars()
            )
            preparer = connection.dialect.identifier_preparer
            for table_name in table_names:
                quoted_table = preparer.quote(table_name)
                digest = hashlib.sha256()
                row_count = 0
                rows = connection.exec_driver_sql(
                    f"SELECT to_jsonb(source_row)::text FROM {quoted_table} AS source_row "
                    "ORDER BY to_jsonb(source_row)::text"
                ).scalars()
                for row in rows:
                    digest.update(str(row).encode("utf-8"))
                    digest.update(b"\x00")
                    row_count += 1
                fingerprints[table_name] = (row_count, digest.hexdigest())
    return fingerprints


def _sequence_state(engine: Engine) -> dict[str, tuple[int, bool]]:
    state: dict[str, tuple[int, bool]] = {}
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            names = tuple(
                str(name)
                for name in connection.execute(
                    text(
                        "SELECT relation.relname FROM pg_class AS relation "
                        "JOIN pg_namespace AS namespace "
                        "ON namespace.oid = relation.relnamespace "
                        "WHERE namespace.nspname = 'public' "
                        "AND relation.relkind = 'S' ORDER BY relation.relname"
                    )
                ).scalars()
            )
            preparer = connection.dialect.identifier_preparer
            for name in names:
                last_value, is_called = connection.exec_driver_sql(
                    f"SELECT last_value, is_called FROM {preparer.quote(name)}"
                ).one()
                state[name] = (int(last_value), bool(is_called))
    return state


def _assert_clean_seed_safety(engine: Engine) -> None:
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM business "
                    "WHERE company_name = "
                    "'Flo-Zone Pest And Termite Solutions Inc'"
                )
            ).scalar_one() == 1
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM website "
                    "WHERE domain = 'www.flo-zonetenting.com'"
                )
            ).scalar_one() == 1
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM websitethemeselection "
                    "WHERE status = 'active'"
                )
            ).scalar_one() == 0
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM themefamilyversion AS version "
                    "JOIN themefamily AS family "
                    "ON family.id = version.theme_family_id "
                    "WHERE family.family_key = 'performance-local' "
                    "AND version.version = 3"
                )
            ).scalar_one() == 0
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
            sensitive_matches = tuple(
                name
                for name in table_names
                if re.search(
                    r"(?:customer|form.*submission|submission.*form|"
                    r"lead.*submission)",
                    name,
                )
            )
            assert sensitive_matches == ("formsubmissionenvelope",)
            for table in FORM_DELIVERY_TABLES:
                assert connection.execute(
                    text(f"SELECT COUNT(*) FROM {table}")
                ).scalar_one() == 0
            envelope_columns = set(
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'formsubmissionenvelope'"
                    )
                ).scalars()
            )
            assert envelope_columns.isdisjoint(
                {"name", "phone", "postal_code", "zip", "requested_service", "message", "raw_body", "recipient", "payload"}
            )

    from app.services import form_submission_contracts, form_submission_gateway

    assert dict(form_submission_contracts.FORM_SUBMISSION_PROVIDERS) == {}
    assert dict(form_submission_gateway.PRODUCTION_SUBMISSION_PROVIDERS) == {}
    assert dict(form_submission_gateway.PRODUCTION_SPAM_CONTROLS) == {}
    assert dict(form_submission_gateway.PRODUCTION_IDEMPOTENCY_BOUNDARIES) == {}


def _assert_two_seed_enabled_starts_are_safe(
    database: _DisposableDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as app_main
    from app.db import session as db_session

    before_schema = _catalog_snapshot(database.engine)
    monkeypatch.setattr(db_session, "engine", database.engine)
    monkeypatch.setattr(app_main, "engine", database.engine)
    monkeypatch.setattr(app_main.settings, "seed_on_startup", True)

    with TestClient(app_main.app) as client:
        assert client.get("/health").json()["status"] == "ok"
    assert _catalog_snapshot(database.engine) == before_schema
    _assert_form_delivery_0047_surface(database.engine)
    after_first_data = _application_data_fingerprints(database.engine)
    after_first_sequences = _sequence_state(database.engine)
    _assert_clean_seed_safety(database.engine)

    with TestClient(app_main.app) as client:
        assert client.get("/health").json()["status"] == "ok"
    assert _catalog_snapshot(database.engine) == before_schema
    _assert_form_delivery_0047_surface(database.engine)
    assert _application_data_fingerprints(database.engine) == after_first_data
    assert _sequence_state(database.engine) == after_first_sequences
    _assert_clean_seed_safety(database.engine)


def _current_revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()


def _assert_table_absent(engine: Engine, table: str) -> None:
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT to_regclass(:qualified_name)"),
            {"qualified_name": f"public.{table}"},
        ).scalar_one()
    assert exists is None


def _index_semantics(engine: Engine, index_name: str) -> dict[str, Any]:
    with engine.connect() as connection:
        index_row = connection.execute(
            text(
                """
                SELECT index_record.indexrelid,
                       index_relation.relname,
                       table_relation.relname,
                       access_method.amname,
                       index_record.indisunique,
                       index_record.indisprimary,
                       index_record.indisvalid,
                       index_record.indisready,
                       index_record.indnkeyatts,
                       index_record.indnatts,
                       pg_get_expr(
                           index_record.indpred,
                           index_record.indrelid,
                           true
                       ),
                       pg_get_expr(
                           index_record.indexprs,
                           index_record.indrelid,
                           true
                       )
                FROM pg_index AS index_record
                JOIN pg_class AS index_relation
                  ON index_relation.oid = index_record.indexrelid
                JOIN pg_class AS table_relation
                  ON table_relation.oid = index_record.indrelid
                JOIN pg_namespace AS namespace
                  ON namespace.oid = table_relation.relnamespace
                JOIN pg_am AS access_method
                  ON access_method.oid = index_relation.relam
                WHERE namespace.nspname = 'public'
                  AND index_relation.relname = :index_name
                """
            ),
            {"index_name": index_name},
        ).one()
        index_oid = index_row[0]
        columns = tuple(
            tuple(row)
            for row in connection.execute(
                text(
                    """
                    SELECT slot.slot_number,
                           attribute.attname,
                           operator_class.opcname,
                           operator_class.opcdefault,
                           index_record.indoption[slot.slot_number],
                           (
                               index_record.indcollation[slot.slot_number]
                               = attribute.attcollation
                           ) AS uses_column_collation
                    FROM pg_index AS index_record
                    CROSS JOIN LATERAL generate_series(
                        0,
                        index_record.indnatts - 1
                    ) AS slot(slot_number)
                    LEFT JOIN pg_attribute AS attribute
                      ON attribute.attrelid = index_record.indrelid
                     AND attribute.attnum =
                         index_record.indkey[slot.slot_number]
                    LEFT JOIN pg_opclass AS operator_class
                      ON operator_class.oid =
                         index_record.indclass[slot.slot_number]
                    WHERE index_record.indexrelid = :index_oid
                    ORDER BY slot.slot_number
                    """
                ),
                {"index_oid": index_oid},
            )
        )
    key_count = index_row[8]
    return {
        "name": index_row[1],
        "table": index_row[2],
        "access_method": index_row[3],
        "unique": index_row[4],
        "primary": index_row[5],
        "valid": index_row[6],
        "ready": index_row[7],
        "key_count": key_count,
        "attribute_count": index_row[9],
        "predicate": index_row[10],
        "expressions": index_row[11],
        "key_columns": tuple(row[1] for row in columns[:key_count]),
        "included_columns": tuple(row[1] for row in columns[key_count:]),
        "operator_classes": tuple(row[2] for row in columns[:key_count]),
        "default_operator_classes": tuple(
            row[3] for row in columns[:key_count]
        ),
        "options": tuple(row[4] for row in columns[:key_count]),
        "uses_column_collation": tuple(
            row[5] for row in columns[:key_count]
        ),
    }


def _assert_exact_repaired_indexes(
    engine: Engine,
    names: set[str] | None = None,
) -> None:
    selected_names = names or set(EXPECTED_REPAIRED_INDEXES)
    assert selected_names <= set(EXPECTED_REPAIRED_INDEXES)
    for name in sorted(selected_names):
        expected = EXPECTED_REPAIRED_INDEXES[name]
        observed = _index_semantics(engine, name)
        assert observed["name"] == name
        assert len(name.encode("utf-8")) <= 63
        assert observed["table"] == expected.table
        assert observed["access_method"] == "btree"
        assert observed["unique"] is False
        assert observed["primary"] is False
        assert observed["valid"] is True
        assert observed["ready"] is True
        assert observed["key_count"] == 1
        assert observed["attribute_count"] == 1
        assert observed["predicate"] is None
        assert observed["expressions"] is None
        assert observed["key_columns"] == (expected.column,)
        assert observed["included_columns"] == ()
        assert len(observed["operator_classes"]) == 1
        assert observed["default_operator_classes"] == (True,)
        assert observed["options"] == (0,)
        assert observed["uses_column_collation"] == (True,)


def _assert_head_contract(engine: Engine) -> None:
    with engine.connect() as connection:
        table_count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relkind IN ('r', 'p')
                """
            )
        ).scalar_one()
        sequence_count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relkind = 'S'
                """
            )
        ).scalar_one()
        versions = tuple(
            connection.execute(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            ).scalars()
        )
        overlong_identifiers = tuple(
            connection.execute(
                text(
                    """
                    WITH public_identifiers AS (
                        SELECT 'relation' AS kind,
                               '' AS parent,
                               relation.relname AS identifier
                        FROM pg_class AS relation
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = 'public'
                        UNION ALL
                        SELECT 'column', relation.relname, attribute.attname
                        FROM pg_attribute AS attribute
                        JOIN pg_class AS relation
                          ON relation.oid = attribute.attrelid
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = 'public'
                          AND attribute.attnum > 0
                          AND NOT attribute.attisdropped
                        UNION ALL
                        SELECT 'constraint', relation.relname,
                               constraint_record.conname
                        FROM pg_constraint AS constraint_record
                        JOIN pg_class AS relation
                          ON relation.oid = constraint_record.conrelid
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = 'public'
                        UNION ALL
                        SELECT 'type', '', type_record.typname
                        FROM pg_type AS type_record
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = type_record.typnamespace
                        WHERE namespace.nspname = 'public'
                          AND type_record.typtype IN ('d', 'e')
                    )
                    SELECT kind, parent, identifier, octet_length(identifier)
                    FROM public_identifiers
                    WHERE octet_length(identifier) > 63
                    ORDER BY kind, parent, identifier
                    """
                )
            )
        )
    assert table_count == EXPECTED_TABLE_COUNT
    assert sequence_count == EXPECTED_SEQUENCE_COUNT
    assert versions == (HEAD_REVISION,)
    assert overlong_identifiers == ()
    assert len(EXPECTED_REPAIRED_INDEXES) == 4
    assert len(EXPECTED_REPAIRED_INDEXES) == len(set(EXPECTED_REPAIRED_INDEXES))
    _assert_exact_repaired_indexes(engine)
    _assert_form_delivery_0047_surface(engine)


def _migration_0041_module():
    path = (
        BACKEND
        / "alembic"
        / "versions"
        / "20260807_0041_page_media_planning_provenance.py"
    )
    spec = importlib.util.spec_from_file_location("atlas_migration_0041_pg", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration_0046_module():
    path = (
        BACKEND
        / "alembic"
        / "versions"
        / "20260815_0046_postgresql_schema_convergence.py"
    )
    spec = importlib.util.spec_from_file_location("atlas_migration_0046_pg", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _migration_0047_module():
    path = (
        BACKEND
        / "alembic"
        / "versions"
        / "20260817_0047_universal_form_delivery_modes.py"
    )
    spec = importlib.util.spec_from_file_location("atlas_migration_0047_pg", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assert_canonical_0046_surface(engine: Engine) -> None:
    migration = _migration_0046_module()
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            observed = migration._read_postgres_surface(
                connection,
                post_upgrade=True,
            )
    assert observed == migration._expected_postgres_surface("canonical")


def _assert_form_delivery_0047_surface(engine: Engine) -> None:
    migration = _migration_0047_module()
    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            ).scalars()
        )
        assert FORM_DELIVERY_TABLES <= tables
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == HEAD_REVISION
        migration._assert_exact_owned_shape(connection)


def _assert_0045_source_contract(engine: Engine, expected: str) -> None:
    migration = _migration_0046_module()
    with engine.connect() as connection:
        observed = migration._read_postgres_surface(connection)
    assert migration._classify_postgres_surface(observed) == expected


def _assert_0041_postgresql_deparse(engine: Engine) -> None:
    expected = "requirement_state IN ('required','advisory','excluded','deferred')"
    with engine.connect() as connection:
        observed_rows = tuple(
            connection.execute(
                text(
                    """
                    SELECT pg_get_expr(
                               constraint_record.conbin,
                               constraint_record.conrelid,
                               true
                           )
                    FROM pg_constraint AS constraint_record
                    JOIN pg_class AS relation
                      ON relation.oid = constraint_record.conrelid
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                      AND relation.relname = 'plannedpagemediarequirement'
                      AND constraint_record.conname =
                          'ck_plannedpagemediarequirement_state'
                      AND constraint_record.contype = 'c'
                    """
                )
            ).scalars()
        )
    assert len(observed_rows) == 1
    observed = observed_rows[0]
    assert observed != expected
    assert "= ANY" in observed.upper()
    assert "ARRAY[" in observed.upper()
    migration = _migration_0041_module()
    assert migration._canonical(observed) == migration._canonical(expected)


def _seed_postgresql_form_delivery_scope(
    database: _DisposableDatabase,
) -> tuple[int, int, int]:
    token = uuid4().hex
    with Session(database.engine) as session:
        business = Business(
            company_name=f"0047 race {token}",
            business_type="test",
            state="FL",
        )
        session.add(business)
        session.flush()
        website = Website(
            business_id=business.id,
            website_name="0047 race",
            domain=f"{token}.example.test",
            public_url=f"https://{token}.example.test",
            status="active",
        )
        session.add(website)
        session.flush()
        family = ThemeFamily(
            family_key=f"pg-race-{token}",
            display_name="PG 0047 race",
            description="Disposable PostgreSQL form-delivery race.",
            provider_source_identity="test-source",
            lifecycle_status="registered",
            created_by="test",
            integrity_fingerprint="a" * 64,
        )
        session.add(family)
        session.flush()
        version = ThemeFamilyVersion(
            theme_family_id=family.id,
            version=3,
            lifecycle_status="preview_candidate",
            production_ready=False,
            source_commit="b" * 40,
            compatibility_identity=token.ljust(64, "0")[:64],
            supported_component_contracts=[],
            created_by="test",
            integrity_fingerprint="c" * 64,
        )
        session.add(version)
        session.flush()
        configuration = WebsiteThemeConfiguration(
            website_id=website.id,
            business_id=business.id,
            theme_family_version_id=version.id,
            configuration_key="pg-0047-race",
            version=1,
            lifecycle_status="draft",
            created_by="test",
            updated_by="test",
            creation_rationale="Disposable PostgreSQL race.",
            integrity_fingerprint="d" * 64,
        )
        session.add(configuration)
        session.flush()
        component = WebsiteThemeComponentConfiguration(
            website_theme_configuration_id=configuration.id,
            website_id=website.id,
            theme_family_version_id=version.id,
            component_instance_key="compact-estimate-form:website",
            component_key="compact_estimate_form",
            component_contract_version=3,
            revision=1,
            scope_type="website_default",
            lifecycle_status="current",
            enabled=True,
            variant="compact-estimate-form",
            placement="final-cta",
            responsive_visibility={"desktop": True, "tablet": True, "mobile": True},
            configuration_payload={},
            created_by="test",
            updated_by="test",
            integrity_fingerprint="e" * 64,
        )
        session.add(component)
        session.commit()
        now = datetime.now(UTC)
        disabled = create_form_delivery_mode_revision(
            session,
            website.id,
            WebsiteFormDeliveryModeRevisionCreate(
                form_component_configuration_id=component.id,
                form_instance_key=component.component_instance_key,
                lifecycle_status="active",
                mode="disabled",
                enabled=False,
                configuration_payload={},
                audit_identity="pg-0047-disabled-audit",
                approval_identity="pg-0047-disabled-approval",
                approved_at=now,
                activation_identity="pg-0047-disabled-activation",
                activated_at=now,
                created_by="test",
                updated_by="test",
                rationale="Establish the explicit disabled root.",
            ),
        )
        email = create_form_delivery_mode_revision(
            session,
            website.id,
            WebsiteFormDeliveryModeRevisionCreate(
                form_component_configuration_id=component.id,
                form_instance_key=component.component_instance_key,
                supersedes_delivery_mode_revision_id=disabled.id,
                lifecycle_status="active",
                mode="atlas_email",
                enabled=True,
                provider_key=SYNTHETIC_EMAIL_PROVIDER_KEY,
                adapter_version="test-v1",
                destination_identity="recipient-set-ref://synthetic/pg-race",
                configuration_payload={
                    "transport_key_reference": "synthetic-mail",
                    "transport_secret_reference": "secret-ref://synthetic/mail-transport",
                    "notification_preference": "all_verified",
                    "consent_required": False,
                },
                privacy_policy_reference="/privacy",
                retention_policy_reference="policy-ref://synthetic/retention",
                abuse_policy_reference="policy-ref://synthetic/abuse",
                success_behavior="Show a generic success state.",
                failure_behavior="Show a generic failure state.",
                idempotency_policy_reference="policy-ref://synthetic/idempotency",
                audit_identity="pg-0047-email-audit",
                approval_identity="pg-0047-email-approval",
                approved_at=now,
                activation_identity="pg-0047-email-activation",
                activated_at=now,
                created_by="test",
                updated_by="test",
                rationale="Create the disposable race email mode.",
            ),
        )
        create_form_recipient_revision(
            session,
            website.id,
            WebsiteFormRecipientRevisionCreate(
                delivery_mode_revision_id=email.id,
                recipient_key="primary-office",
                email="synthetic.recipient@example.com",
                recipient_role="primary",
                enabled=True,
                verification_status="verified",
                verified_at=now,
                verified_by="test",
                verification_method="synthetic_test",
                created_by="test",
                updated_by="test",
                rationale="Create the disposable verified recipient.",
            ),
        )
        return website.id, component.id, email.id


def _postgresql_disabled_successor_payload(
    component: WebsiteThemeComponentConfiguration,
    predecessor_id: int,
) -> WebsiteFormDeliveryModeRevisionCreate:
    now = datetime.now(UTC)
    return WebsiteFormDeliveryModeRevisionCreate(
        form_component_configuration_id=component.id,
        form_instance_key=component.component_instance_key,
        supersedes_delivery_mode_revision_id=predecessor_id,
        lifecycle_status="active",
        mode="disabled",
        enabled=False,
        configuration_payload={},
        audit_identity="pg-0047-successor-audit",
        approval_identity="pg-0047-successor-approval",
        approved_at=now,
        activation_identity="pg-0047-successor-activation",
        activated_at=now,
        created_by="test",
        updated_by="test",
        rationale="Win the serialized successor race.",
    )


def test_two_clean_base_to_head_postgresql_installs_are_equivalent_and_repeatable(
    disposable_postgres_database_factory: Callable[[], _DisposableDatabase],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = disposable_postgres_database_factory()
    second = disposable_postgres_database_factory()

    _upgrade(first, "head")
    _assert_head_contract(first.engine)
    first_snapshot = _catalog_snapshot(first.engine)
    _upgrade(first, "head")
    assert _catalog_snapshot(first.engine) == first_snapshot
    _assert_two_seed_enabled_starts_are_safe(first, monkeypatch)
    assert _catalog_snapshot(first.engine) == first_snapshot

    _upgrade(second, "head")
    _assert_head_contract(second.engine)
    second_snapshot = _catalog_snapshot(second.engine)
    _upgrade(second, "head")
    assert _catalog_snapshot(second.engine) == second_snapshot
    _assert_two_seed_enabled_starts_are_safe(second, monkeypatch)
    assert _catalog_snapshot(second.engine) == second_snapshot

    assert second_snapshot == first_snapshot


def test_segmented_postgresql_migrations_downgrade_and_reupgrade_safely(
    disposable_postgres_database_factory: Callable[[], _DisposableDatabase],
) -> None:
    database = disposable_postgres_database_factory()
    cleanup_index = {
        "ix_wordpressbootstrapcleanupaudit_deactivation_handle_f_fc62"
    }
    cache_index = {
        "ix_wordpresscacheawarerenderingaudit_rendering_handle_f_e1fc"
    }
    establishment_indexes = {
        "ix_wordpressbootstrapestablishmentaudit_manual_handle_f_6138",
        "ix_wordpressbootstrapestablishmentaudit_activation_hand_a9b8",
    }

    _upgrade(database, "20260716_0019")
    _upgrade(database, "20260716_0020")
    assert _current_revision(database.engine) == "20260716_0020"
    _assert_exact_repaired_indexes(database.engine, cleanup_index)
    _downgrade(database, "20260716_0019")
    assert _current_revision(database.engine) == "20260716_0019"
    _assert_table_absent(database.engine, "wordpressbootstrapcleanupaudit")
    _upgrade(database, "20260716_0020")
    _assert_exact_repaired_indexes(database.engine, cleanup_index)

    _upgrade(database, "20260717_0021")
    _upgrade(database, "20260717_0022")
    assert _current_revision(database.engine) == "20260717_0022"
    _assert_exact_repaired_indexes(database.engine, cleanup_index | cache_index)
    _downgrade(database, "20260717_0021")
    assert _current_revision(database.engine) == "20260717_0021"
    _assert_table_absent(database.engine, "wordpresscacheawarerenderingaudit")
    _upgrade(database, "20260717_0022")
    _assert_exact_repaired_indexes(database.engine, cleanup_index | cache_index)

    _upgrade(database, "20260719_0023")
    assert _current_revision(database.engine) == "20260719_0023"
    _assert_exact_repaired_indexes(
        database.engine,
        cleanup_index | cache_index | establishment_indexes,
    )
    _downgrade(database, "20260717_0022")
    assert _current_revision(database.engine) == "20260717_0022"
    _assert_table_absent(
        database.engine,
        "wordpressbootstrapestablishmentaudit",
    )
    _upgrade(database, "20260719_0023")
    _assert_exact_repaired_indexes(
        database.engine,
        cleanup_index | cache_index | establishment_indexes,
    )

    _upgrade(database, "20260805_0040")
    _upgrade(database, "20260807_0041")
    assert _current_revision(database.engine) == "20260807_0041"
    _assert_0041_postgresql_deparse(database.engine)
    first_0041_snapshot = _catalog_snapshot(database.engine)
    _upgrade(database, "20260807_0041")
    assert _catalog_snapshot(database.engine) == first_0041_snapshot

    _downgrade(database, "20260805_0040")
    assert _current_revision(database.engine) == "20260805_0040"
    _assert_table_absent(database.engine, "plannedpagemediarequirement")
    _assert_table_absent(database.engine, "websitemediaplanningrecord")
    _upgrade(database, "20260807_0041")
    _assert_0041_postgresql_deparse(database.engine)
    assert _catalog_snapshot(database.engine) == first_0041_snapshot

    _upgrade(database, "20260813_0045")
    assert _current_revision(database.engine) == "20260813_0045"
    _assert_0045_source_contract(database.engine, "clean")

    _upgrade(database, "20260815_0046")
    assert _current_revision(database.engine) == "20260815_0046"
    _assert_canonical_0046_surface(database.engine)
    convergence_snapshot = _catalog_snapshot(database.engine)
    convergence_data = _application_data_fingerprints(database.engine)
    convergence_sequences = _sequence_state(database.engine)
    _upgrade(database, HEAD_REVISION)
    _assert_head_contract(database.engine)
    head_data = _application_data_fingerprints(database.engine)
    head_sequences = _sequence_state(database.engine)
    assert {
        key: head_data[key] for key in convergence_data
    } == convergence_data
    assert {
        key: head_sequences[key] for key in convergence_sequences
    } == convergence_sequences
    with database.engine.connect() as connection:
        for table in FORM_DELIVERY_TABLES:
            assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
    head_snapshot = _catalog_snapshot(database.engine)
    _upgrade(database, HEAD_REVISION)
    assert _catalog_snapshot(database.engine) == head_snapshot
    _downgrade(database, "20260815_0046")
    assert _catalog_snapshot(database.engine) == convergence_snapshot
    assert _application_data_fingerprints(database.engine) == convergence_data
    assert _sequence_state(database.engine) == convergence_sequences
    _assert_canonical_0046_surface(database.engine)
    for table in FORM_DELIVERY_TABLES:
        _assert_table_absent(database.engine, table)
    _upgrade(database, HEAD_REVISION)
    _assert_form_delivery_0047_surface(database.engine)
    assert _catalog_snapshot(database.engine) == head_snapshot
    assert _application_data_fingerprints(database.engine) == head_data
    assert _sequence_state(database.engine) == head_sequences


@pytest.mark.parametrize(
    "mutation_sql",
    (
        "ALTER TABLE formdeliveryattempt SET (fillfactor=70)",
        "ALTER TABLE formdeliveryattempt ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE formdeliveryattempt ALTER COLUMN safe_provider_reference SET STORAGE EXTERNAL",
        "ALTER INDEX formdeliveryattempt_pkey SET (fillfactor=70)",
        "CREATE POLICY unexpected ON formdeliveryattempt USING (true)",
        "CREATE SEQUENCE unexpected_owned_seq OWNED BY formdeliveryattempt.id",
        "CREATE RULE unexpected AS ON UPDATE TO formdeliveryattempt DO NOTHING",
        "ALTER TABLE formdeliveryoutbox RENAME CONSTRAINT fk_fdo_mode TO fk_fdo_mode_changed",
        "DROP INDEX ix_fdo_status; CREATE INDEX ix_fdo_status ON formdeliveryoutbox(status COLLATE \"C\")",
        "ALTER TABLE formdeliveryoutbox DISABLE TRIGGER ALL",
    ),
)
def test_postgresql_0047_unknown_shape_refuses_downgrade_without_mutation(
    disposable_postgres_database_factory: Callable[[], _DisposableDatabase],
    mutation_sql: str,
) -> None:
    database = disposable_postgres_database_factory()
    _upgrade(database, HEAD_REVISION)
    with database.engine.begin() as connection:
        for statement in mutation_sql.split("; "):
            connection.exec_driver_sql(statement)
    before = _catalog_snapshot(database.engine)
    with pytest.raises(RuntimeError, match="exact 0047 contract"):
        _downgrade(database, "20260815_0046")
    assert _current_revision(database.engine) == HEAD_REVISION
    assert _catalog_snapshot(database.engine) == before


def test_postgresql_0047_populated_refusal_is_fail_before_mutation(
    disposable_postgres_database_factory: Callable[[], _DisposableDatabase],
) -> None:
    database = disposable_postgres_database_factory()
    _upgrade(database, HEAD_REVISION)
    token = uuid4().hex
    with Session(database.engine) as session:
        business = Business(
            company_name=f"0047 populated guard {token}",
            business_type="test",
            state="FL",
        )
        session.add(business)
        session.flush()
        website = Website(
            business_id=business.id,
            website_name="0047 populated guard",
            domain=f"{token}.example.test",
            public_url=f"https://{token}.example.test",
            status="active",
        )
        session.add(website)
        session.flush()
        family = ThemeFamily(
            family_key=f"pg-0047-{token}",
            display_name="PG 0047 guard",
            description="Disposable PostgreSQL form-delivery guard.",
            provider_source_identity="test-source",
            lifecycle_status="registered",
            created_by="test",
            integrity_fingerprint="a" * 64,
        )
        session.add(family)
        session.flush()
        version = ThemeFamilyVersion(
            theme_family_id=family.id,
            version=3,
            lifecycle_status="preview_candidate",
            production_ready=False,
            source_commit="b" * 40,
            compatibility_identity=token.ljust(64, "0")[:64],
            supported_component_contracts=[],
            created_by="test",
            integrity_fingerprint="c" * 64,
        )
        session.add(version)
        session.flush()
        configuration = WebsiteThemeConfiguration(
            website_id=website.id,
            business_id=business.id,
            theme_family_version_id=version.id,
            configuration_key="pg-0047-guard",
            version=1,
            lifecycle_status="draft",
            created_by="test",
            updated_by="test",
            creation_rationale="Disposable PostgreSQL guard.",
            integrity_fingerprint="d" * 64,
        )
        session.add(configuration)
        session.flush()
        component = WebsiteThemeComponentConfiguration(
            website_theme_configuration_id=configuration.id,
            website_id=website.id,
            theme_family_version_id=version.id,
            component_instance_key="compact-estimate-form:website",
            component_key="compact_estimate_form",
            component_contract_version=3,
            revision=1,
            scope_type="website_default",
            lifecycle_status="current",
            enabled=True,
            variant="compact-estimate-form",
            placement="final-cta",
            responsive_visibility={"desktop": True, "tablet": True, "mobile": True},
            configuration_payload={},
            created_by="test",
            updated_by="test",
            integrity_fingerprint="e" * 64,
        )
        session.add(component)
        session.commit()
        now = datetime.now(UTC)
        create_form_delivery_mode_revision(
            session,
            website.id,
            WebsiteFormDeliveryModeRevisionCreate(
                form_component_configuration_id=component.id,
                form_instance_key=component.component_instance_key,
                lifecycle_status="active",
                mode="disabled",
                enabled=False,
                configuration_payload={},
                audit_identity="pg-0047-populated-guard",
                approval_identity="pg-0047-approval",
                approved_at=now,
                activation_identity="pg-0047-activation",
                activated_at=now,
                created_by="test",
                updated_by="test",
                rationale="Prove populated downgrade refusal.",
            ),
        )
    before_catalog = _catalog_snapshot(database.engine)
    before_data = _application_data_fingerprints(database.engine)
    before_sequences = _sequence_state(database.engine)
    with database.engine.connect() as connection:
        before_counts = {
            table: connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            for table in FORM_DELIVERY_TABLES
        }
    with pytest.raises(RuntimeError, match="governed records exist"):
        _downgrade(database, "20260815_0046")
    assert _current_revision(database.engine) == HEAD_REVISION
    assert _catalog_snapshot(database.engine) == before_catalog
    assert _application_data_fingerprints(database.engine) == before_data
    assert _sequence_state(database.engine) == before_sequences
    with database.engine.connect() as connection:
        assert {
            table: connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            for table in FORM_DELIVERY_TABLES
        } == before_counts


def test_postgresql_0047_mode_successor_serializes_against_recipient_append(
    disposable_postgres_database_factory: Callable[[], _DisposableDatabase],
) -> None:
    database = disposable_postgres_database_factory()
    _upgrade(database, HEAD_REVISION)
    with _alembic_database_url(database.url):
        website_id, component_id, email_id = _seed_postgresql_form_delivery_scope(
            database
        )
        successor_locked = Event()
        recipient_started = Event()
        finish_successor = Event()

        def create_successor() -> int:
            with Session(database.engine) as session:
                locked = session.exec(
                    select(WebsiteFormDeliveryModeRevision)
                    .where(WebsiteFormDeliveryModeRevision.id == email_id)
                    .with_for_update()
                ).one()
                component = session.get(
                    WebsiteThemeComponentConfiguration,
                    component_id,
                )
                assert component is not None
                successor_locked.set()
                assert finish_successor.wait(timeout=20)
                successor = create_form_delivery_mode_revision(
                    session,
                    website_id,
                    _postgresql_disabled_successor_payload(component, locked.id),
                )
                assert successor.id is not None
                return successor.id

        def append_recipient() -> str:
            assert successor_locked.wait(timeout=20)
            with Session(database.engine) as session:
                recipient_started.set()
                try:
                    create_form_recipient_revision(
                        session,
                        website_id,
                        WebsiteFormRecipientRevisionCreate(
                            delivery_mode_revision_id=email_id,
                            recipient_key="racing-secondary",
                            email="racing.secondary@example.com",
                            recipient_role="secondary",
                            enabled=True,
                            verification_status="unverified",
                            created_by="test",
                            updated_by="test",
                            rationale="Attempt a serialized recipient append.",
                        ),
                    )
                except FormDeliveryConfigurationError as exc:
                    return str(exc)
                return "unexpected-success"

        with ThreadPoolExecutor(max_workers=2) as executor:
            successor_future = executor.submit(create_successor)
            assert successor_locked.wait(timeout=20)
            recipient_future = executor.submit(append_recipient)
            assert recipient_started.wait(timeout=20)
            finish_successor.set()
            assert successor_future.result(timeout=20) > email_id
            assert "frozen recipient snapshot" in recipient_future.result(timeout=20)

        with Session(database.engine) as session:
            assert validate_form_delivery_records(session)[
                "website_form_delivery_mode_revisions"
            ] == 3


def test_postgresql_0047_enqueue_serializes_against_recipient_append(
    disposable_postgres_database_factory: Callable[[], _DisposableDatabase],
) -> None:
    database = disposable_postgres_database_factory()
    _upgrade(database, HEAD_REVISION)
    with _alembic_database_url(database.url):
        website_id, component_id, email_id = _seed_postgresql_form_delivery_scope(
            database
        )
        enqueue_locked = Event()
        recipient_started = Event()
        finish_enqueue = Event()
        payload_store = InMemoryTestPayloadStore(test_environment_allowed=True)
        received_at = datetime.now(UTC)

        def enqueue_submission() -> int:
            with Session(database.engine) as session:
                email = session.exec(
                    select(WebsiteFormDeliveryModeRevision)
                    .where(WebsiteFormDeliveryModeRevision.id == email_id)
                    .with_for_update()
                ).one()
                enqueue_locked.set()
                assert finish_enqueue.wait(timeout=20)
                readiness = form_delivery_readiness(
                    session,
                    email,
                    allow_test_only=True,
                    secure_payload_store_available=True,
                )
                outbox = enqueue_form_delivery(
                    session,
                    mode_revision=email,
                    readiness=readiness,
                    envelope=NormalizedSubmissionEnvelope(
                        website_id=website_id,
                        component_configuration_id=component_id,
                        component_revision=1,
                        delivery_mode_revision_id=email_id,
                        submission_contract_version=3,
                        name="Synthetic Person",
                        phone="+14075550100",
                        postal_code="32801",
                        requested_service="Synthetic service",
                        message="Synthetic message",
                        consent_accepted=None,
                        audit_identity=email.audit_identity,
                        idempotency_key="pg-race-idempotency-key-00000001",
                        privacy_policy_identity=email.privacy_policy_reference,
                        retention_policy_identity=email.retention_policy_reference,
                        abuse_policy_identity=email.abuse_policy_reference,
                        anti_spam_decision="synthetic_allow",
                        request_identity="f" * 64,
                        destination_adapter_key=email.provider_key,
                        received_at=received_at,
                    ),
                    payload_store=payload_store,
                    expires_at=received_at + timedelta(hours=1),
                )
                assert outbox.id is not None
                return outbox.id

        def append_recipient() -> str:
            assert enqueue_locked.wait(timeout=20)
            with Session(database.engine) as session:
                recipient_started.set()
                try:
                    create_form_recipient_revision(
                        session,
                        website_id,
                        WebsiteFormRecipientRevisionCreate(
                            delivery_mode_revision_id=email_id,
                            recipient_key="too-late-secondary",
                            email="too.late@example.com",
                            recipient_role="secondary",
                            enabled=True,
                            verification_status="unverified",
                            created_by="test",
                            updated_by="test",
                            rationale="Attempt an append after first submission.",
                        ),
                    )
                except FormDeliveryConfigurationError as exc:
                    return str(exc)
                return "unexpected-success"

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                enqueue_future = executor.submit(enqueue_submission)
                assert enqueue_locked.wait(timeout=20)
                recipient_future = executor.submit(append_recipient)
                assert recipient_started.wait(timeout=20)
                finish_enqueue.set()
                assert enqueue_future.result(timeout=20) > 0
                assert "submission evidence" in recipient_future.result(timeout=20)
            with Session(database.engine) as session:
                graph = validate_form_delivery_records(session)
                assert graph["form_submission_envelopes"] == 1
                assert graph["form_delivery_outbox_records"] == 1
        finally:
            payload_store.clear()
        assert payload_store.payload_count == 0
