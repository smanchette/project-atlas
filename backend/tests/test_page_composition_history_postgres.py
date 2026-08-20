from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import re
from threading import Event
from typing import Any, Iterator

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool
from sqlmodel import Session, select

from app.core.config import get_settings
from app.models import (
    GeneratedPage,
    GeneratedPageQAResult,
    GeneratedPageRevision,
    PageComposition,
    PageCompositionRevision,
)
from app.schemas.page_editor import ManualDraftSaveRequest
from app.services.approval_audit import draft_content_hash
from app.services.page_composition import (
    PageCompositionError,
    refresh_site_plan_compositions,
)
from app.services.page_composition_history import (
    PageCompositionHistoryError,
    advance_composition_revision,
    canonical_payload_hash,
    current_composition_revision,
    read_composition_revision,
    validate_composition_stream,
)
from app.services.page_qa import resolve_qa_composition_revision


BACKEND = Path(__file__).parents[1]
ROOT = BACKEND.parent
REVISION_0046 = "20260815_0046"
REVISION_0047 = "20260817_0047"
REVISION_0048 = "20260820_0048"
TABLE = "pagecompositionrevision"

ADMIN_URL_ENV = "ATLAS_DISPOSABLE_POSTGRES_ADMIN_URL"
DATABASE_NAMES_ENV = "ATLAS_DISPOSABLE_POSTGRES_DATABASE_NAMES"
EXECUTION_LEDGER_ENV = "ATLAS_COMPOSITION_HISTORY_POSTGRES_EXECUTION_LEDGER"
EXACT_MEDIA_PUBLIC_URL = "http://localhost:8000/media"
SEALED_POSTGRES_HOST = "atlas_pch_migration_pg_072303"
LOCAL_POSTGRES_HOSTS = {SEALED_POSTGRES_HOST}
PRELOADED_EXACT_DUMP_ORDINALS = (2, 7)

HISTORY_EVIDENCE_HOST_PATH = (
    ".runtime/page-composition-history-progress/recovery/legacy-v7-evidence/"
    "page-composition-history-evidence-v1.json"
)
HISTORY_EVIDENCE_CONTAINER_PATH = Path(
    "/recovery/legacy-v7-evidence/page-composition-history-evidence-v1.json"
)
HISTORY_EVIDENCE_SHA256 = (
    "103b18190fe8279064e295a8a6a803cc2f01ac578572b2e1f9d08277b83ae241"
)
HISTORY_EVIDENCE_PROVENANCE_PATH = (
    ".runtime/page-composition-history-progress/recovery/legacy-v7-evidence/"
    "legacy-v7-evidence-provenance.json"
)
HISTORY_EVIDENCE_PROVENANCE_SHA256 = (
    "65770d9a3efaa02eb7a25f01a8449a8b55a6f6ad73a7946afba24103dfb767f4"
)
HISTORY_EVIDENCE_VALIDATION_PATH = (
    ".runtime/page-composition-history-progress/recovery/legacy-v7-evidence/"
    "page-composition-history-evidence-v1-validation-manifest.json"
)
HISTORY_EVIDENCE_VALIDATION_SHA256 = (
    "b1150dffedb4ebee87ca1f471acb578668cbb02050d7915ea3a85b49d18b3917"
)
HISTORY_EVIDENCE_SOURCE_BACKUP_PATH = (
    "backend/backups/atlas-backup-2026-08-12-044908.json"
)
HISTORY_EVIDENCE_SOURCE_BACKUP_CONTAINER_PATH = Path(
    "/app/backups/atlas-backup-2026-08-12-044908.json"
)
HISTORY_EVIDENCE_SOURCE_BACKUP_SHA256 = (
    "b470e827e975f72ccb563d3ef8ffda2df7b3a4f48520ffcbc865cc8f02e1e78a"
)
PAGE41_V7_SOURCE_HASH = (
    "c4cb3b62997aa02145202e27cf281165f661b487a9c4e48f60efcdf2ee867132"
)
PAGE41_V7_REVISION_HASH = (
    "4daa5521f2c9abc19979b91e176d620dce306665ac4139d532bac6eaa3ff9704"
)
QA55_RESULT_HASH = (
    "94b7ef084879723081aea521e3e2baca893b544b841c29f68256d026882b48d9"
)

SEALED_LEDGER_PATH = (
    ".runtime/page-composition-history-progress/recovery/"
    "pre-20260820-072303Z/disposable-postgresql-ledger.json"
)
SEALED_LEDGER_SHA256 = (
    "fd88e6515dd8c50b0a51f12fa60d7de658df03cdcb3bb3c6702d5f42b3e974f1"
)
SEALED_HARNESS_PATH = (
    ".runtime/page-composition-history-progress/recovery/"
    "pre-20260820-072303Z/disposable-migration-harness.ps1"
)
SEALED_HARNESS_SHA256 = (
    "f0e37bdd68fc6e7cb15686ecd6fe58af722a078bdabd117ecf7072477e67b8fa"
)

EXPECTED_DATABASE_NAMES = (
    "atlas_pch_01_clean_0047_head",
    "atlas_pch_02_active_0046_0047_head",
    "atlas_pch_03_existing_0047_head",
    "atlas_pch_04_repeated_upgrade",
    "atlas_pch_05_data058_restore_head",
    "atlas_pch_06_repeated_restore",
    "atlas_pch_07_controlled_refresh",
    "atlas_pch_08_no_change_refresh",
    "atlas_pch_09_concurrent_refresh",
    "atlas_pch_10_injected_failure",
    "atlas_pch_11_tampered_payload",
    "atlas_pch_12_tampered_source_hash",
    "atlas_pch_13_tampered_lineage",
    "atlas_pch_14_cross_page_history",
    "atlas_pch_15_cross_website_history",
    "atlas_pch_16_unknown_schema_variant",
    "atlas_pch_17_downgrade_contract",
)

ARTIFACT_CONTRACT = {
    "exact_postgresql_dump": (
        "artifacts/atlas-postgresql-2026-08-20-072303.dump",
        "3b8b6b9b650b860cc2216683ab727a07303dcffe7a2f1cf9aa82f9d65541c925",
    ),
    "data_058": (
        "artifacts/atlas-backup-2026-08-20-072303.json",
        "a45afa194eb8f99aefd9c6a351fc57603e057ea2561b86c72293bbe832ce035e",
    ),
    "composition_fingerprints": (
        "current-composition-fingerprints.json",
        "5b35f02f742db1eeae6804ffeee7006315337569fa92983e6e03285eecf5d07a",
    ),
    "qa_fingerprints": (
        "current-qa-fingerprints.json",
        "047b35cc5be0ef27f7925058d53fb31be9a4e0c360ce414c8c5b9cebb7403ab7",
    ),
    "protected_media_fingerprints": (
        "protected-media-fingerprint.json",
        "28c6201611ece6c802c4fc51ef161f7938b83e8f97c956114b6e1b05fbc2c663",
    ),
}


@dataclass
class _Database:
    ordinal: int
    name: str
    url: URL
    engine: Engine


@dataclass
class _PostgresPlan:
    admin_engine: Engine
    admin_url: URL
    execution_ledger_path: Path
    execution_ledger: dict[str, Any]
    recovery_root: Path
    databases: tuple[_Database, ...]
    used_ordinals: set[int] = field(default_factory=set)

    def database(self, ordinal: int) -> _Database:
        assert 1 <= ordinal <= len(self.databases)
        assert ordinal not in self.used_ordinals, (
            f"Disposable PostgreSQL scenario {ordinal} was consumed twice."
        )
        self.used_ordinals.add(ordinal)
        database = self.databases[ordinal - 1]
        assert database.ordinal == ordinal
        assert database.name == EXPECTED_DATABASE_NAMES[ordinal - 1]
        return database

    def artifact(self, key: str) -> Path:
        relative, expected_sha256 = ARTIFACT_CONTRACT[key]
        path = self.recovery_root / relative
        assert path.is_file(), f"Required sealed artifact is absent: {path}"
        assert _sha256(path) == expected_sha256
        return path

    def history_evidence(self) -> Path:
        path = HISTORY_EVIDENCE_CONTAINER_PATH
        assert path.is_file(), f"Required history evidence is absent: {path}"
        assert _sha256(path) == HISTORY_EVIDENCE_SHA256
        return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _validate_execution_ledger(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"PostgreSQL execution ledger does not exist: {path}"
    payload = _load_json(path)
    assert payload.get("schema") == (
        "atlas-page-composition-history-postgresql-execution-ledger@1"
    )
    if payload.get("source_freeze_go_received") is not True:
        pytest.fail(
            "PostgreSQL execution ledger is not released by exact SOURCE-FREEZE-GO."
        )
    sealed = payload.get("sealed_preedit_ledger")
    assert sealed == {
        "path": SEALED_LEDGER_PATH,
        "sha256": SEALED_LEDGER_SHA256,
    }
    harness = payload.get("sealed_harness")
    assert harness == {
        "path": SEALED_HARNESS_PATH,
        "sha256": SEALED_HARNESS_SHA256,
    }
    assert _sha256(ROOT / SEALED_LEDGER_PATH) == SEALED_LEDGER_SHA256
    assert _sha256(ROOT / SEALED_HARNESS_PATH) == SEALED_HARNESS_SHA256
    records = payload.get("disposable_database_names")
    assert isinstance(records, list) and len(records) == len(EXPECTED_DATABASE_NAMES)
    assert tuple(record.get("name") for record in records) == EXPECTED_DATABASE_NAMES
    for ordinal, record in enumerate(records, start=1):
        assert record.get("ordinal") == ordinal
        assert record.get("recorded_before_creation") is True
        assert record.get("removed") is not True
    exact_dump_relative, exact_dump_sha256 = ARTIFACT_CONTRACT[
        "exact_postgresql_dump"
    ]
    assert payload.get("preloaded_exact_dump") == {
        "artifact": {
            "path": (
                ".runtime/page-composition-history-progress/recovery/"
                "pre-20260820-072303Z/" + exact_dump_relative
            ),
            "sha256": exact_dump_sha256,
        },
        "database_ordinals": list(PRELOADED_EXACT_DUMP_ORDINALS),
        "database_names": [
            EXPECTED_DATABASE_NAMES[ordinal - 1]
            for ordinal in PRELOADED_EXACT_DUMP_ORDINALS
        ],
        "restored_before_tests": True,
    }
    assert payload.get("legacy_history_evidence") == {
        "artifact": {
            "host_path": HISTORY_EVIDENCE_HOST_PATH,
            "container_path": str(HISTORY_EVIDENCE_CONTAINER_PATH),
            "sha256": HISTORY_EVIDENCE_SHA256,
        },
        "provenance_manifest": {
            "path": HISTORY_EVIDENCE_PROVENANCE_PATH,
            "sha256": HISTORY_EVIDENCE_PROVENANCE_SHA256,
        },
        "validation_manifest": {
            "path": HISTORY_EVIDENCE_VALIDATION_PATH,
            "sha256": HISTORY_EVIDENCE_VALIDATION_SHA256,
        },
        "source_artifact": {
            "path": HISTORY_EVIDENCE_SOURCE_BACKUP_PATH,
            "container_path": str(HISTORY_EVIDENCE_SOURCE_BACKUP_CONTAINER_PATH),
            "sha256": HISTORY_EVIDENCE_SOURCE_BACKUP_SHA256,
            "size_bytes": 21_460_515,
            "backup_version": "0.56",
            "created_at": "2026-08-12T04:49:08.797723+00:00",
        },
        "target_backup": {
            "path": (
                ".runtime/page-composition-history-progress/recovery/"
                "pre-20260820-072303Z/" + ARTIFACT_CONTRACT["data_058"][0]
            ),
            "sha256": ARTIFACT_CONTRACT["data_058"][1],
        },
        "validated_before_tests": True,
    }
    assert _sha256(ROOT / HISTORY_EVIDENCE_HOST_PATH) == HISTORY_EVIDENCE_SHA256
    assert (
        _sha256(ROOT / HISTORY_EVIDENCE_PROVENANCE_PATH)
        == HISTORY_EVIDENCE_PROVENANCE_SHA256
    )
    assert (
        _sha256(ROOT / HISTORY_EVIDENCE_VALIDATION_PATH)
        == HISTORY_EVIDENCE_VALIDATION_SHA256
    )
    assert (
        _sha256(HISTORY_EVIDENCE_SOURCE_BACKUP_CONTAINER_PATH)
        == HISTORY_EVIDENCE_SOURCE_BACKUP_SHA256
    )
    recovery_root = payload.get("recovery_root")
    assert isinstance(recovery_root, str)
    assert (ROOT / recovery_root).resolve().is_dir()
    return payload


def _write_execution_ledger(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


@pytest.fixture(scope="session")
def page_composition_postgres_plan(
    request: pytest.FixtureRequest,
) -> Iterator[_PostgresPlan]:
    admin_url_value = os.getenv(ADMIN_URL_ENV)
    if not admin_url_value:
        pytest.skip(
            f"Set {ADMIN_URL_ENV} only after SOURCE-FREEZE-GO to run the 17-path "
            "Page Composition PostgreSQL matrix."
        )

    previous_media_public_url = os.environ.get("MEDIA_PUBLIC_URL")
    os.environ["MEDIA_PUBLIC_URL"] = EXACT_MEDIA_PUBLIC_URL
    get_settings.cache_clear()

    def restore_media_public_url() -> None:
        if previous_media_public_url is None:
            os.environ.pop("MEDIA_PUBLIC_URL", None)
        else:
            os.environ["MEDIA_PUBLIC_URL"] = previous_media_public_url
        get_settings.cache_clear()

    request.addfinalizer(restore_media_public_url)
    if str(get_settings().media_public_url) != EXACT_MEDIA_PUBLIC_URL:
        pytest.fail("The PostgreSQL matrix media URL contract is not exact.")

    names_value = os.getenv(DATABASE_NAMES_ENV)
    if not names_value:
        pytest.fail(f"{DATABASE_NAMES_ENV} must contain the sealed ordered JSON list.")
    try:
        names = json.loads(names_value)
    except json.JSONDecodeError as exc:
        pytest.fail(f"{DATABASE_NAMES_ENV} is invalid JSON: {exc}")
    if names != list(EXPECTED_DATABASE_NAMES):
        pytest.fail(
            f"{DATABASE_NAMES_ENV} must equal the exact sealed 17-name order."
        )
    for name in names:
        if not re.fullmatch(r"atlas_pch_[a-z0-9_]+", name) or len(name) > 63:
            pytest.fail(f"Unsafe disposable PostgreSQL name: {name!r}")

    ledger_value = os.getenv(EXECUTION_LEDGER_ENV)
    if not ledger_value:
        pytest.fail(
            f"{EXECUTION_LEDGER_ENV} must point to the ignored execution ledger "
            "recorded before Provision."
        )
    ledger_path = Path(ledger_value).resolve()
    ledger = _validate_execution_ledger(ledger_path)
    recovery_root = (ROOT / str(ledger["recovery_root"])).resolve()

    try:
        admin_url = make_url(admin_url_value)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.fail(f"{ADMIN_URL_ENV} is not a valid URL: {exc}")
    if admin_url.get_backend_name() != "postgresql":
        pytest.fail("The 17-path matrix requires PostgreSQL.")
    if (admin_url.host or "").lower() not in LOCAL_POSTGRES_HOSTS:
        pytest.fail("The 17-path matrix refuses non-local PostgreSQL.")
    if not admin_url.database or admin_url.database.lower() == "atlas":
        pytest.fail("The administrative URL must name a non-Atlas database.")
    if admin_url.database in EXPECTED_DATABASE_NAMES:
        pytest.fail("The administrative database cannot be a scenario database.")

    admin_engine = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    databases = [
        _Database(
            ordinal,
            name,
            admin_url.set(database=name),
            create_engine(
                admin_url.set(database=name),
                pool_pre_ping=True,
                poolclass=NullPool,
            ),
        )
        for ordinal, name in enumerate(EXPECTED_DATABASE_NAMES, start=1)
    ]
    plan: _PostgresPlan | None = None
    try:
        with admin_engine.connect() as connection:
            can_manage = connection.execute(
                text(
                    "SELECT rolsuper OR rolcreatedb FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            ).scalar_one()
            if not can_manage:
                pytest.fail(f"{ADMIN_URL_ENV} must identify a local CREATEDB role.")
            existing = tuple(
                connection.execute(
                    text(
                        "SELECT datname FROM pg_database "
                        "WHERE datname = ANY(:names) ORDER BY datname"
                    ),
                    {"names": list(EXPECTED_DATABASE_NAMES)},
                ).scalars()
            )
            if set(existing) != set(EXPECTED_DATABASE_NAMES):
                pytest.fail(
                    "Harness Provision must precreate exactly all 17 scenario databases."
                )

        for database in databases:
            with database.engine.connect() as connection:
                relation_count = connection.execute(
                    text(
                        "SELECT COUNT(*) FROM pg_class AS relation "
                        "JOIN pg_namespace AS namespace "
                        "ON namespace.oid = relation.relnamespace "
                        "WHERE namespace.nspname = 'public' "
                        "AND relation.relkind IN ('r','p','v','m','S')"
                    )
                ).scalar_one()
            if database.ordinal in PRELOADED_EXACT_DUMP_ORDINALS:
                if relation_count == 0:
                    pytest.fail(
                        "Exact-dump scenario database was not preloaded: "
                        f"{database.name}"
                    )
                _assert_exact_preloaded_clone(database.engine, recovery_root)
            elif relation_count != 0:
                pytest.fail(
                    "Provisioned scenario database is not pristine: "
                    f"{database.name}"
                )

        for record in ledger["disposable_database_names"]:
            record["created"] = True
        ledger["status"] = "PROVISIONED_TESTS_RUNNING"
        _write_execution_ledger(ledger_path, ledger)
        plan = _PostgresPlan(
            admin_engine=admin_engine,
            admin_url=admin_url,
            execution_ledger_path=ledger_path,
            execution_ledger=ledger,
            recovery_root=recovery_root,
            databases=tuple(databases),
        )
        yield plan
    finally:
        cleanup_failures: list[str] = []
        for database in reversed(databases):
            try:
                database.engine.dispose(close=True)
                with admin_engine.connect() as connection:
                    connection.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = :name AND pid <> pg_backend_pid()"
                        ),
                        {"name": database.name},
                    )
                    connection.exec_driver_sql(
                        f'DROP DATABASE IF EXISTS "{database.name}"'
                    )
            except Exception as exc:  # pragma: no cover - teardown diagnostics
                cleanup_failures.append(f"{database.name}: {exc}")
        try:
            with admin_engine.connect() as connection:
                remaining = tuple(
                    connection.execute(
                        text(
                            "SELECT datname FROM pg_database "
                            "WHERE datname = ANY(:names) ORDER BY datname"
                        ),
                        {"names": list(EXPECTED_DATABASE_NAMES)},
                    ).scalars()
                )
            if remaining:
                cleanup_failures.append("still present: " + ", ".join(remaining))
        finally:
            admin_engine.dispose(close=True)

        if plan is not None:
            for record in ledger["disposable_database_names"]:
                record["removed"] = record["name"] not in {
                    failure.split(":", 1)[0] for failure in cleanup_failures
                }
                record["confirmed_absent"] = not cleanup_failures
            ledger["cleanup"] = {
                "sessions_terminated": not cleanup_failures,
                "all_databases_removed": not cleanup_failures,
                "all_databases_confirmed_absent": not cleanup_failures,
            }
            ledger["status"] = "PASS_CLEANED" if not cleanup_failures else "FAIL_CLEANUP"
            _write_execution_ledger(ledger_path, ledger)
            if not cleanup_failures:
                assert plan.used_ordinals == set(range(1, 18)), (
                    "Every authorized PostgreSQL path must consume its exact database."
                )
        assert not cleanup_failures, "PostgreSQL cleanup failed: " + "; ".join(
            cleanup_failures
        )


@contextmanager
def _database_url(url: URL) -> Iterator[None]:
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def _alembic_config(
    *,
    history_evidence: Path | None = None,
) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    if history_evidence is not None:
        config.set_main_option(
            "page_composition_history_evidence_path",
            str(history_evidence),
        )
        config.set_main_option(
            "page_composition_history_evidence_sha256",
            HISTORY_EVIDENCE_SHA256,
        )
    return config


def _upgrade(
    database: _Database,
    revision: str,
    *,
    history_evidence: Path | None = None,
) -> None:
    with _database_url(database.url):
        command.upgrade(
            _alembic_config(history_evidence=history_evidence),
            revision,
        )


def _downgrade(database: _Database, revision: str) -> None:
    with _database_url(database.url):
        command.downgrade(_alembic_config(), revision)


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(text("SELECT version_num FROM alembic_version"))
            .scalar_one()
        )


def _migration_module():
    path = (
        BACKEND
        / "alembic"
        / "versions"
        / "20260820_0048_append_only_page_composition_history.py"
    )
    spec = spec_from_file_location("atlas_history_migration_0048_pg", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _test_module(name: str):
    path = BACKEND / "tests" / f"{name}.py"
    spec = spec_from_file_location(f"atlas_pg_helper_{name}", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _restore_data_058(plan: _PostgresPlan, database: _Database) -> dict[str, Any]:
    return _restore_backup_file(
        database,
        plan.artifact("data_058"),
        history_evidence=plan.history_evidence(),
    )


def _restore_backup_file(
    database: _Database,
    backup_file: Path,
    *,
    history_evidence: Path | None = None,
) -> dict[str, Any]:
    from app.db.backup import restore_backup

    previous = os.environ.get("MEDIA_PUBLIC_URL")
    os.environ["MEDIA_PUBLIC_URL"] = "http://localhost:8000/media"
    get_settings.cache_clear()
    try:
        with Session(database.engine) as session:
            return restore_backup(
                session,
                backup_file,
                page_composition_history_evidence_path=history_evidence,
                page_composition_history_evidence_sha256=(
                    HISTORY_EVIDENCE_SHA256
                    if history_evidence is not None
                    else None
                ),
            )
    finally:
        if previous is None:
            os.environ.pop("MEDIA_PUBLIC_URL", None)
        else:
            os.environ["MEDIA_PUBLIC_URL"] = previous
        get_settings.cache_clear()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return normalized.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return value


def _query_fingerprint(engine: Engine, sql: str, parameters: dict | None = None) -> str:
    with engine.connect() as connection:
        rows = [
            json.dumps(
                _canonical_value(dict(row._mapping)),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            for row in connection.execute(text(sql), parameters or {})
        ]
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def _capture_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _canonical_value(value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _capture_json_rows(
    engine: Engine,
    table: str,
    where: str = "TRUE",
    parameters: dict | None = None,
) -> list[dict[str, Any]]:
    assert re.fullmatch(r"[a-z][a-z0-9_]*", table)
    with engine.connect() as connection:
        quoted = connection.dialect.identifier_preparer.quote(table)
        rows = connection.execute(
            text(
                f"SELECT to_jsonb(source) FROM "
                f"(SELECT * FROM {quoted} WHERE {where} ORDER BY id) AS source"
            ),
            parameters or {},
        ).scalars()
        return [_canonical_value(row) for row in rows]


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


def _assert_sealed_protected_media(
    engine: Engine,
    identity: dict[str, Any],
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    governed_images = identity["page41_governed_images"]
    all_assignments = identity["page41_all_assignments"]
    authorizations = identity["page41_authorizations"]
    image_ids = tuple(int(row["id"]) for row in governed_images)
    assignment_ids = tuple(int(row["id"]) for row in all_assignments)
    authorization_ids = tuple(int(row["id"]) for row in authorizations)
    assert image_ids and assignment_ids and authorization_ids
    assert len(set(image_ids)) == len(image_ids)
    assert len(set(assignment_ids)) == len(assignment_ids)
    assert len(set(authorization_ids)) == len(authorization_ids)

    assert _capture_json_rows(
        engine,
        "imagemetadata",
        "id = ANY(:ids)",
        {"ids": list(image_ids)},
    ) == governed_images
    assert _capture_json_rows(
        engine,
        "pageimageassignment",
        "id = ANY(:ids)",
        {"ids": list(assignment_ids)},
    ) == all_assignments
    assert _capture_json_rows(
        engine,
        "scopedmediaauthorization",
        "id = ANY(:ids)",
        {"ids": list(authorization_ids)},
    ) == authorizations
    assert _capture_json_rows(
        engine,
        "pageimageassignment",
        "generated_page_id = 41 AND status = 'active' "
        "AND media_requirement_id IS NOT NULL",
    ) == identity["page41_governed_active_assignments"]
    assert _capture_json_rows(
        engine,
        "imagemetadata",
        "wordpress_media_id = 31",
    ) == identity["media31"]
    assert _capture_json_rows(
        engine,
        "imagemetadata",
        "wordpress_media_id = 32",
    ) == identity["media32"]
    assert _capture_digest(_capture_json_rows(engine, "imagemetadata")) == identity[
        "all_image_metadata_sha256"
    ]
    assert _capture_digest(
        _capture_json_rows(engine, "pageimageassignment")
    ) == identity["all_page_image_assignments_sha256"]
    return image_ids, assignment_ids, authorization_ids


def _assert_exact_preloaded_clone(engine: Engine, recovery_root: Path) -> None:
    assert _revision(engine) == REVISION_0046
    composition_relative, composition_sha256 = ARTIFACT_CONTRACT[
        "composition_fingerprints"
    ]
    qa_relative, qa_sha256 = ARTIFACT_CONTRACT["qa_fingerprints"]
    media_relative, media_sha256 = ARTIFACT_CONTRACT["protected_media_fingerprints"]
    composition_path = recovery_root / composition_relative
    qa_path = recovery_root / qa_relative
    media_path = recovery_root / media_relative
    assert _sha256(composition_path) == composition_sha256
    assert _sha256(qa_path) == qa_sha256
    assert _sha256(media_path) == media_sha256
    compositions = _load_json(composition_path)
    qa = _load_json(qa_path)
    media = _load_json(media_path)

    composition_rows = _capture_json_rows(engine, "pagecomposition")
    qa_rows = _capture_json_rows(engine, "generatedpageqaresult")
    assert len(composition_rows) == (
        compositions["current_count"] + compositions["historical_count"]
    ) == 65
    assert len(qa_rows) == qa["current_count"] + qa["historical_count"] == 80
    assert _capture_digest(composition_rows) == compositions["all_history_sha256"]
    assert _capture_digest(qa_rows) == qa["all_history_sha256"]
    expected_composition = next(
        row
        for row in compositions["current_identities"]
        if row["generated_page_id"] == 41
    )
    expected_qa = next(
        row for row in qa["current_identities"] if row["generated_page_id"] == 41
    )
    observed_composition = next(
        row
        for row in composition_rows
        if row["id"] == expected_composition["composition_id"]
    )
    observed_qa = next(row for row in qa_rows if row["id"] == expected_qa["qa_id"])
    assert _capture_digest(observed_composition) == expected_composition["row_sha256"]
    assert _capture_digest(observed_qa) == expected_qa["row_sha256"]
    _assert_sealed_protected_media(engine, media["database_media_identity"])


def _catalog_snapshot(engine: Engine) -> tuple[tuple[Any, ...], ...]:
    with engine.connect() as connection:
        return tuple(
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT relation.relkind, relation.relname "
                    "FROM pg_class AS relation "
                    "JOIN pg_namespace AS namespace "
                    "ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = 'public' "
                    "ORDER BY relation.relkind, relation.relname"
                )
            )
        )


def _seed_migration_bound_composition(database: _Database) -> dict[str, object]:
    helper = _test_module("test_page_composition_history_migration")
    return helper._seed_bound_composition(database.engine)


def _seed_synthetic_head(database: _Database, *, suffix: str) -> dict[str, Any]:
    helper = _test_module("test_page_composition")
    with Session(database.engine) as session:
        website, plan, pages = helper._scope(session, suffix=suffix)
        result = refresh_site_plan_compositions(session, plan.id or 0)
        assert result.blocked == []
        assert result.created == 2
        compositions = list(
            session.exec(
                select(PageComposition)
                .where(PageComposition.site_plan_id == plan.id)
                .order_by(PageComposition.id)
            ).all()
        )
        assert len(compositions) == 2
        return {
            "website_id": website.id,
            "plan_id": plan.id,
            "pages": tuple((planned.id, generated.id) for planned, generated in pages),
            "composition_ids": tuple(item.id for item in compositions),
        }


def _record_clone_only_draft_change(
    session: Session,
    generated_page_id: int,
    *,
    field: str,
    value: Any,
    actor: str,
) -> GeneratedPageRevision:
    page = session.exec(
        select(GeneratedPage)
        .where(GeneratedPage.id == generated_page_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    before = deepcopy(page.draft_content or {})
    after = deepcopy(before)
    after[field] = value
    changed_at = datetime.now(UTC)
    revision = GeneratedPageRevision(
        generated_page_id=generated_page_id,
        created_at=changed_at,
        created_by=actor,
        reason="Disposable Page Composition history source-only control",
        draft_hash_before=draft_content_hash(before),
        draft_hash_after=draft_content_hash(after),
        draft_content_before=before,
        draft_content_after=after,
        changed_fields=[field],
    )
    page.draft_content = after
    page.updated_at = changed_at
    session.add(revision)
    session.add(page)
    session.commit()
    session.refresh(revision)
    return revision


def _history_rows(engine: Engine, composition_id: int) -> tuple[tuple[Any, ...], ...]:
    with engine.connect() as connection:
        return tuple(
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT id, composition_version, source_hash, revision_hash, "
                    "supersedes_revision_id, supersedes_revision_hash, lineage_kind "
                    "FROM pagecompositionrevision "
                    "WHERE page_composition_id = :composition_id "
                    "ORDER BY composition_version, id"
                ),
                {"composition_id": composition_id},
            )
        )


def _insert_bound_qa(
    session: Session,
    composition: PageComposition,
) -> GeneratedPageQAResult:
    record = GeneratedPageQAResult(
        website_id=composition.website_id,
        site_plan_id=composition.site_plan_id,
        planned_page_id=composition.planned_page_id,
        generated_page_id=composition.generated_page_id,
        latest_generated_page_revision_id=None,
        content_hash=str(composition.source_snapshot["draft_hash"]),
        source_hash="1" * 64,
        page_composition_id=composition.id,
        composition_version=composition.composition_version,
        composition_source_hash=composition.source_hash,
        qa_algorithm_key="history-postgres-test",
        qa_algorithm_version="1",
        qa_ruleset_key="history-postgres-test",
        qa_ruleset_version="1",
        qa_ruleset_hash="2" * 64,
        readiness_status="ready",
        passed_count=1,
        warning_count=0,
        failed_count=0,
        check_payload=[],
        evaluated_at=datetime.now(UTC),
        lifecycle_status="current",
        result_hash="3" * 64,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def _disable_immutability_triggers(connection) -> None:
    connection.exec_driver_sql(
        "ALTER TABLE pagecompositionrevision DISABLE TRIGGER "
        "trg_pagecomprev_immutable_rows"
    )
    connection.exec_driver_sql(
        "ALTER TABLE pagecompositionrevision DISABLE TRIGGER "
        "trg_pagecomprev_immutable_truncate"
    )


def _enable_immutability_triggers(connection) -> None:
    connection.exec_driver_sql(
        "ALTER TABLE pagecompositionrevision ENABLE TRIGGER "
        "trg_pagecomprev_immutable_rows"
    )
    connection.exec_driver_sql(
        "ALTER TABLE pagecompositionrevision ENABLE TRIGGER "
        "trg_pagecomprev_immutable_truncate"
    )


def test_01_clean_base_to_0047_to_0048_has_exact_postgresql_contract(
    page_composition_postgres_plan: _PostgresPlan,
) -> None:
    database = page_composition_postgres_plan.database(1)
    _upgrade(database, REVISION_0047)
    assert _revision(database.engine) == REVISION_0047
    assert TABLE not in inspect(database.engine).get_table_names()

    _upgrade(database, REVISION_0048)
    assert _revision(database.engine) == REVISION_0048
    migration = _migration_module()
    with database.engine.connect() as connection:
        migration._assert_owned_shape(connection)
        assert connection.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() == 0
    owned_identifiers = {
        migration.TABLE,
        migration.CURRENT_HEAD_FK,
        migration.QA_REVISION_FK,
        migration.IMMUTABLE_FUNCTION,
        migration.IMMUTABLE_ROW_TRIGGER,
        migration.IMMUTABLE_TRUNCATE_TRIGGER,
        migration.SQLITE_UPDATE_TRIGGER,
        migration.SQLITE_DELETE_TRIGGER,
        *migration.EXPECTED_CHECKS,
        *migration.EXPECTED_UNIQUES,
        *migration.EXPECTED_INDEXES,
        *migration.EXPECTED_HISTORY_FKS,
    }
    assert all(len(name.encode("utf-8")) <= 63 for name in owned_identifiers)


def test_02_exact_active_0046_clone_upgrades_through_0047_without_identity_drift(
    page_composition_postgres_plan: _PostgresPlan,
) -> None:
    plan = page_composition_postgres_plan
    database = plan.database(2)
    expected = _load_json(plan.artifact("composition_fingerprints"))
    expected_page41 = next(
        item for item in expected["current_identities"] if item["generated_page_id"] == 41
    )
    before_compositions = _query_fingerprint(
        database.engine, "SELECT * FROM pagecomposition ORDER BY id"
    )
    before_qa = _query_fingerprint(
        database.engine, "SELECT * FROM generatedpageqaresult ORDER BY id"
    )
    before_sequences = _sequence_state(database.engine)
    with database.engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT id, composition_version, source_hash FROM pagecomposition "
                "WHERE generated_page_id = 41"
            )
        ).one() == (
            expected_page41["composition_id"],
            expected_page41["composition_version"],
            expected_page41["source_hash"],
        )

    _upgrade(database, REVISION_0047)
    assert _revision(database.engine) == REVISION_0047
    after_0047_sequences = _sequence_state(database.engine)
    assert {
        name: after_0047_sequences[name] for name in before_sequences
    } == before_sequences
    _upgrade(
        database,
        REVISION_0048,
        history_evidence=plan.history_evidence(),
    )
    assert _revision(database.engine) == REVISION_0048
    after_0048_sequences = _sequence_state(database.engine)
    with database.engine.connect() as connection:
        history_sequence = str(
            connection.execute(
                text("SELECT pg_get_serial_sequence(:table, 'id')"),
                {"table": TABLE},
            ).scalar_one()
        ).rsplit(".", 1)[-1]
    assert history_sequence not in after_0047_sequences
    assert set(after_0048_sequences) == set(after_0047_sequences) | {
        history_sequence
    }
    assert {
        name: state
        for name, state in after_0048_sequences.items()
        if name != history_sequence
    } == after_0047_sequences
    assert _query_fingerprint(
        database.engine, "SELECT * FROM pagecomposition ORDER BY id"
    ) == before_compositions
    assert _query_fingerprint(
        database.engine, "SELECT * FROM generatedpageqaresult ORDER BY id"
    ) == before_qa
    with database.engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM pagecompositionrevision")
        ).scalar_one() == expected["current_count"] + 1
        page41_history = connection.execute(
            text(
                "SELECT id, composition_version, source_hash, revision_hash, "
                "lineage_kind, supersedes_revision_id, supersedes_revision_hash, "
                "record_source FROM pagecompositionrevision "
                "WHERE page_composition_id = 41 ORDER BY composition_version"
            )
        ).all()
        assert len(page41_history) == 2
        historical, current = page41_history
        assert tuple(historical[1:]) == (
            7,
            PAGE41_V7_SOURCE_HASH,
            PAGE41_V7_REVISION_HASH,
            "legacy_root",
            None,
            None,
            "legacy_history_evidence_v1",
        )
        assert tuple(current[1:]) == (
            8,
            expected_page41["source_hash"],
            current.revision_hash,
            "successor",
            historical.id,
            PAGE41_V7_REVISION_HASH,
            "migration_0048_backfill",
        )
    with Session(database.engine) as session:
        composition = session.get(PageComposition, 41)
        assert composition is not None
        current = current_composition_revision(session, composition)
        historical = read_composition_revision(session, 41, 7)
        qa55 = session.get(GeneratedPageQAResult, 55)
        assert current.composition_version == 8
        assert current.source_hash == expected_page41["source_hash"]
        assert current.supersedes_revision_id == historical.id
        assert historical.revision_hash == PAGE41_V7_REVISION_HASH
        assert qa55 is not None and qa55.result_hash == QA55_RESULT_HASH
        assert resolve_qa_composition_revision(session, qa55).id == historical.id


def test_03_existing_populated_0047_schema_backfills_exact_root_and_qa(
    page_composition_postgres_plan: _PostgresPlan,
) -> None:
    database = page_composition_postgres_plan.database(3)
    _upgrade(database, REVISION_0047)
    identities = _seed_migration_bound_composition(database)
    before = _query_fingerprint(
        database.engine,
        "SELECT * FROM pagecomposition WHERE id = :id",
        {"id": identities["composition_id"]},
    )
    _upgrade(database, REVISION_0048)
    assert _query_fingerprint(
        database.engine,
        "SELECT * FROM pagecomposition WHERE id = :id",
        {"id": identities["composition_id"]},
    ) == before
    with Session(database.engine) as session:
        composition = session.get(PageComposition, identities["composition_id"])
        qa = session.get(GeneratedPageQAResult, identities["qa_id"])
        assert composition is not None and qa is not None
        root = current_composition_revision(session, composition)
        assert root.lineage_kind == "legacy_root"
        assert root.generated_page_revision_id == identities["generated_revision_id"]
        assert resolve_qa_composition_revision(session, qa).id == root.id


def test_04_repeated_upgrade_to_head_is_catalog_and_data_idempotent(
    page_composition_postgres_plan: _PostgresPlan,
) -> None:
    database = page_composition_postgres_plan.database(4)
    _upgrade(database, REVISION_0047)
    identities = _seed_migration_bound_composition(database)
    _upgrade(database, REVISION_0048)
    catalog = _catalog_snapshot(database.engine)
    history = _history_rows(database.engine, int(identities["composition_id"]))
    _upgrade(database, REVISION_0048)
    assert _catalog_snapshot(database.engine) == catalog
    assert _history_rows(database.engine, int(identities["composition_id"])) == history


def test_05_data_058_restore_to_0048_synthesizes_truthful_history_and_exports_059(
    page_composition_postgres_plan: _PostgresPlan,
    tmp_path: Path,
) -> None:
    from app.db.backup import BACKUP_VERSION, export_backup, load_backup

    plan = page_composition_postgres_plan
    database = plan.database(5)
    _upgrade(database, REVISION_0048)
    restored = _restore_data_058(plan, database)
    assert restored["records_processed"] > 0
    assert BACKUP_VERSION == "0.59"
    with Session(database.engine) as session:
        compositions = list(session.exec(select(PageComposition)).all())
        revisions = list(session.exec(select(PageCompositionRevision)).all())
        assert len(compositions) == 65
        assert len(revisions) == 66
        assert all(
            len(validate_composition_stream(session, composition))
            == (2 if composition.id == 41 else 1)
            for composition in compositions
        )
        page41 = session.get(PageComposition, 41)
        qa55 = session.get(GeneratedPageQAResult, 55)
        assert page41 is not None and qa55 is not None
        stream41 = validate_composition_stream(session, page41)
        assert [revision.composition_version for revision in stream41] == [7, 8]
        assert stream41[0].revision_hash == PAGE41_V7_REVISION_HASH
        assert stream41[1].lineage_kind == "successor"
        assert resolve_qa_composition_revision(session, qa55).id == stream41[0].id
        exported = export_backup(session, backup_dir=tmp_path)
    payload = load_backup(Path(exported["path"]))
    assert payload["metadata"]["version"] == "0.59"
    assert payload["metadata"]["table_counts"]["page_composition_revisions"] == 66


def test_06_repeated_data_058_restore_preserves_exact_history_fingerprints(
    page_composition_postgres_plan: _PostgresPlan,
    tmp_path: Path,
) -> None:
    from app.db.backup import export_backup, load_backup

    plan = page_composition_postgres_plan
    database = plan.database(6)
    _upgrade(database, REVISION_0048)
    restored_058 = _restore_data_058(plan, database)
    with Session(database.engine) as session:
        exported = export_backup(
            session,
            backup_dir=tmp_path,
            created_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        )
    payload_059_path = Path(exported["path"])
    payload_059 = load_backup(payload_059_path)
    assert payload_059["metadata"]["version"] == "0.59"
    assert payload_059["metadata"]["table_counts"][
        "page_composition_revisions"
    ] == payload_059["metadata"]["table_counts"]["page_compositions"] + 1
    snapshot = (
        _query_fingerprint(database.engine, "SELECT * FROM pagecomposition ORDER BY id"),
        _query_fingerprint(
            database.engine, "SELECT * FROM pagecompositionrevision ORDER BY id"
        ),
        _query_fingerprint(
            database.engine, "SELECT * FROM generatedpageqaresult ORDER BY id"
        ),
        _sequence_state(database.engine),
    )
    expected_records = sum(payload_059["metadata"]["table_counts"].values())
    assert restored_058["records_processed"] < expected_records
    for _replay in range(2):
        restored_059 = _restore_backup_file(database, payload_059_path)
        assert restored_059["records_processed"] == expected_records
        assert snapshot == (
            _query_fingerprint(
                database.engine, "SELECT * FROM pagecomposition ORDER BY id"
            ),
            _query_fingerprint(
                database.engine, "SELECT * FROM pagecompositionrevision ORDER BY id"
            ),
            _query_fingerprint(
                database.engine, "SELECT * FROM generatedpageqaresult ORDER BY id"
            ),
            _sequence_state(database.engine),
        )


def test_07_page41_source_only_refresh_preserves_v8_qa80_and_protected_output(
    page_composition_postgres_plan: _PostgresPlan,
) -> None:
    plan = page_composition_postgres_plan
    database = plan.database(7)
    composition_package = _load_json(plan.artifact("composition_fingerprints"))
    qa_package = _load_json(plan.artifact("qa_fingerprints"))
    media_package = _load_json(plan.artifact("protected_media_fingerprints"))
    expected_composition = next(
        item
        for item in composition_package["current_identities"]
        if item["generated_page_id"] == 41
    )
    expected_qa = next(
        item for item in qa_package["current_identities"] if item["generated_page_id"] == 41
    )
    assert expected_composition["composition_id"] == 41
    assert expected_composition["composition_version"] == 8
    assert expected_qa["qa_id"] == 80
    assert expected_qa["composition_id"] == expected_composition["composition_id"]
    assert expected_qa["composition_version"] == expected_composition[
        "composition_version"
    ]
    assert expected_qa["generated_page_id"] == expected_composition[
        "generated_page_id"
    ]
    legacy_composition_rows = _capture_json_rows(
        database.engine,
        "pagecomposition",
        "id = :id",
        {"id": expected_composition["composition_id"]},
    )
    assert len(legacy_composition_rows) == 1
    assert _capture_digest(legacy_composition_rows[0]) == expected_composition[
        "row_sha256"
    ]
    legacy_qa80_rows = _capture_json_rows(
        database.engine,
        "generatedpageqaresult",
        "id = :id",
        {"id": expected_qa["qa_id"]},
    )
    assert len(legacy_qa80_rows) == 1
    assert _capture_digest(legacy_qa80_rows[0]) == expected_qa["row_sha256"]

    media_identity = media_package["database_media_identity"]
    assert len(media_identity["page41_governed_images"]) == 3
    assert len(
        media_identity["page41_governed_active_assignments"]
    ) == 3
    image_ids, assignment_ids, authorization_ids = _assert_sealed_protected_media(
        database.engine,
        media_identity,
    )

    _upgrade(
        database,
        REVISION_0048,
        history_evidence=plan.history_evidence(),
    )

    protected_queries = (
        (
            "SELECT * FROM imagemetadata WHERE id = ANY(:ids) ORDER BY id",
            {"ids": list(image_ids)},
        ),
        (
            "SELECT * FROM pageimageassignment WHERE id = ANY(:ids) ORDER BY id",
            {"ids": list(assignment_ids)},
        ),
        (
            "SELECT * FROM scopedmediaauthorization "
            "WHERE id = ANY(:ids) ORDER BY id",
            {"ids": list(authorization_ids)},
        ),
        (
            "SELECT * FROM plannedpagemediarequirement "
            "WHERE planned_page_id = 41 ORDER BY id",
            None,
        ),
        ("SELECT * FROM theme ORDER BY id", None),
        ("SELECT * FROM websitethemeselection ORDER BY id", None),
    )
    protected_before = tuple(
        _query_fingerprint(database.engine, query, parameters)
        for query, parameters in protected_queries
    )
    public_before = _query_fingerprint(
        database.engine,
        "SELECT content_body, status, h1, page_title, meta_title, meta_description, "
        "wordpress_post_id, wordpress_status, wordpress_url "
        "FROM generatedpage WHERE id = 41",
    )
    qa80_before = _query_fingerprint(
        database.engine,
        "SELECT * FROM generatedpageqaresult WHERE id = 80",
    )
    with Session(database.engine) as session:
        composition = session.get(PageComposition, 41)
        assert composition is not None
        recovered_v7 = read_composition_revision(
            session,
            41,
            7,
            generated_page_id=41,
            website_id=1,
        )
        revision_v8 = read_composition_revision(
            session,
            41,
            8,
            generated_page_id=41,
            website_id=1,
        )
        components_v8 = deepcopy(revision_v8.generated_components)
        source_v8 = revision_v8.source_hash
        assert source_v8 == expected_composition["source_hash"]
        assert recovered_v7.source_hash == PAGE41_V7_SOURCE_HASH
        assert recovered_v7.revision_hash == PAGE41_V7_REVISION_HASH
        assert revision_v8.supersedes_revision_id == recovered_v7.id
        assert revision_v8.supersedes_revision_hash == recovered_v7.revision_hash
        assert revision_v8.page_composition_id == expected_composition["composition_id"]
        assert revision_v8.generated_page_id == expected_composition["generated_page_id"]
        assert revision_v8.planned_page_id == expected_composition["planned_page_id"]
        assert revision_v8.site_plan_id == expected_composition["site_plan_id"]
        assert revision_v8.composition_version == expected_composition["composition_version"]
        qa55 = session.get(GeneratedPageQAResult, 55)
        qa80 = session.get(GeneratedPageQAResult, expected_qa["qa_id"])
        assert qa55 is not None and qa80 is not None
        assert qa55.result_hash == QA55_RESULT_HASH
        assert resolve_qa_composition_revision(session, qa55).id == recovered_v7.id
        assert resolve_qa_composition_revision(session, qa80).id == revision_v8.id
        assert (
            qa80.id,
            qa80.generated_page_id,
            qa80.page_composition_id,
            qa80.composition_version,
            qa80.composition_source_hash,
            qa80.content_hash,
            qa80.source_hash,
            qa80.result_hash,
            qa80.readiness_status,
            qa80.passed_count,
            qa80.warning_count,
            qa80.failed_count,
        ) == (
            expected_qa["qa_id"],
            expected_qa["generated_page_id"],
            expected_qa["composition_id"],
            expected_qa["composition_version"],
            expected_composition["source_hash"],
            expected_qa["content_hash"],
            expected_qa["source_hash"],
            expected_qa["result_hash"],
            expected_qa["readiness_status"],
            expected_qa["passed_count"],
            expected_qa["warning_count"],
            expected_qa["failed_count"],
        )
        page = session.get(GeneratedPage, 41)
        assert page is not None and page.status == "published"
        public_draft_v8 = {
            key: deepcopy(value)
            for key, value in (page.draft_content or {}).items()
            if key != "internal_notes"
        }
        revision = _record_clone_only_draft_change(
            session,
            41,
            field="internal_notes",
            value=(
                str((page.draft_content or {}).get("internal_notes") or "")
                + " [disposable composition-history source control]"
            ),
            actor="migration-test:page41-source-control",
        )
        generated_revision_id = revision.id

    with Session(database.engine) as session:
        refreshed = refresh_site_plan_compositions(session, 1)
        assert refreshed.blocked == []
        assert refreshed.refreshed == 1
        composition = session.get(PageComposition, 41)
        qa55 = session.get(GeneratedPageQAResult, 55)
        qa80 = session.get(GeneratedPageQAResult, 80)
        page = session.get(GeneratedPage, 41)
        assert (
            composition is not None
            and qa55 is not None
            and qa80 is not None
            and page is not None
        )
        assert composition.composition_version == 9
        current = current_composition_revision(session, composition)
        historical = read_composition_revision(
            session, 41, 8, generated_page_id=41, website_id=1
        )
        assert current.generated_page_revision_id == generated_revision_id
        assert current.generated_components == components_v8
        assert historical.generated_components == components_v8
        assert historical.source_hash == expected_composition["source_hash"] == source_v8
        assert historical.revision_hash == current.supersedes_revision_hash
        assert resolve_qa_composition_revision(session, qa80).id == historical.id
        assert resolve_qa_composition_revision(session, qa55).composition_version == 7
        assert {
            key: deepcopy(value)
            for key, value in (page.draft_content or {}).items()
            if key != "internal_notes"
        } == public_draft_v8
        assert page.status == "published"

    assert qa80_before == _query_fingerprint(
        database.engine, "SELECT * FROM generatedpageqaresult WHERE id = 80"
    )
    qa80_after_rows = _capture_json_rows(
        database.engine,
        "generatedpageqaresult",
        "id = :id",
        {"id": expected_qa["qa_id"]},
    )
    assert len(qa80_after_rows) == 1
    assert _capture_digest(qa80_after_rows[0]) == expected_qa["row_sha256"]
    assert public_before == _query_fingerprint(
        database.engine,
        "SELECT content_body, status, h1, page_title, meta_title, meta_description, "
        "wordpress_post_id, wordpress_status, wordpress_url "
        "FROM generatedpage WHERE id = 41",
    )
    assert protected_before == tuple(
        _query_fingerprint(database.engine, query, parameters)
        for query, parameters in protected_queries
    )
    assert _assert_sealed_protected_media(
        database.engine,
        media_identity,
    ) == (image_ids, assignment_ids, authorization_ids)
    for table in (
        "websiteformdeliverymoderevision",
        "websiteformrecipientrevision",
        "formsubmissionenvelope",
        "formdeliveryoutbox",
        "formdeliveryattempt",
        "formdeliveryconfigurationaudit",
    ):
        with database.engine.connect() as connection:
            assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0


def test_08_no_change_refresh_creates_no_duplicate_revision(
    page_composition_postgres_plan: _PostgresPlan,
) -> None:
    database = page_composition_postgres_plan.database(8)
    _upgrade(database, REVISION_0048)
    scope = _seed_synthetic_head(database, suffix="pg08")
    before = tuple(
        _history_rows(database.engine, int(composition_id))
        for composition_id in scope["composition_ids"]
    )
    with Session(database.engine) as session:
        result = refresh_site_plan_compositions(session, int(scope["plan_id"]))
        assert result.blocked == []
        assert result.created == result.refreshed == 0
        assert result.unchanged == 2
    assert before == tuple(
        _history_rows(database.engine, int(composition_id))
        for composition_id in scope["composition_ids"]
    )


def test_09_concurrent_refresh_and_canonical_writer_interleaving_are_serialized(
    page_composition_postgres_plan: _PostgresPlan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import page_composition as composition_service
    from app.services import page_editor

    database = page_composition_postgres_plan.database(9)
    _upgrade(database, REVISION_0048)
    scope = _seed_synthetic_head(database, suffix="pg09")
    target_page_id = int(scope["pages"][0][1])
    target_composition_id = int(scope["composition_ids"][0])
    with Session(database.engine) as session:
        _record_clone_only_draft_change(
            session,
            target_page_id,
            field="internal_notes",
            value="concurrent refresh source change",
            actor="migration-test:concurrent-refresh",
        )

    def refresh_worker() -> tuple[int, int]:
        with Session(database.engine) as session:
            result = refresh_site_plan_compositions(session, int(scope["plan_id"]))
            assert result.blocked == []
            return result.refreshed, result.unchanged

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _value: refresh_worker(), range(2)))
    assert sorted(outcomes) == [(0, 2), (1, 1)]
    assert len(_history_rows(database.engine, target_composition_id)) == 2

    monkeypatch.setattr(
        page_editor,
        "require_effective_drafting_eligibility",
        lambda *_args, **_kwargs: None,
    )
    original_projection = composition_service._authoritative_projection
    projection_locked = Event()
    release_projection = Event()
    paused = False

    def paused_projection(*args, **kwargs):
        nonlocal paused
        generated = args[3]
        if generated.id == target_page_id and not paused:
            paused = True
            projection_locked.set()
            assert release_projection.wait(10)
        return original_projection(*args, **kwargs)

    monkeypatch.setattr(
        composition_service,
        "_authoritative_projection",
        paused_projection,
    )
    writer_started = Event()
    writer_done = Event()

    def writer_worker() -> int:
        writer_started.set()
        try:
            with Session(database.engine) as session:
                page = session.get(GeneratedPage, target_page_id)
                assert page is not None
                changed_intro = str((page.draft_content or {})["intro"]) + " Updated."
                sections = deepcopy((page.draft_content or {}).get("sections") or [])
                if not any(section.get("key") == "service_area" for section in sections):
                    sections.append(
                        {
                            "key": "service_area",
                            "heading": "Service area",
                            "body": "Approved service-area facts only.",
                        }
                    )
                _page, revision, _qa = page_editor.save_manual_draft(
                    session,
                    target_page_id,
                    ManualDraftSaveRequest(
                        draft={"intro": changed_intro, "sections": sections},
                        created_by="migration-test:writer-lock",
                        reason="Real PostgreSQL writer serialization regression",
                    ),
                )
                assert revision.id is not None
                return revision.id
        finally:
            writer_done.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        refresh_future = executor.submit(refresh_worker)
        assert projection_locked.wait(10)
        writer_future = executor.submit(writer_worker)
        assert writer_started.wait(10)
        assert writer_done.wait(0.5) is False
        release_projection.set()
        assert refresh_future.result(timeout=20) == (0, 2)
        writer_revision_id = writer_future.result(timeout=20)

    with Session(database.engine) as session:
        composition = session.get(PageComposition, target_composition_id)
        assert composition is not None
        stream_before_final_refresh = validate_composition_stream(session, composition)
        assert len(stream_before_final_refresh) == 2
        final = refresh_site_plan_compositions(session, int(scope["plan_id"]))
        assert final.blocked == [] and final.refreshed == 1
        session.refresh(composition)
        stream = validate_composition_stream(session, composition)
        assert len(stream) == 3
        assert stream[-1].generated_page_revision_id == writer_revision_id


def test_10_mid_refresh_failure_rolls_back_current_head_and_history(
    page_composition_postgres_plan: _PostgresPlan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import page_composition as composition_service

    database = page_composition_postgres_plan.database(10)
    _upgrade(database, REVISION_0048)
    scope = _seed_synthetic_head(database, suffix="pg10")
    target_page_id = int(scope["pages"][0][1])
    with Session(database.engine) as session:
        _record_clone_only_draft_change(
            session,
            target_page_id,
            field="internal_notes",
            value="injected rollback source",
            actor="migration-test:rollback",
        )
    before = (
        _query_fingerprint(database.engine, "SELECT * FROM pagecomposition ORDER BY id"),
        _query_fingerprint(
            database.engine, "SELECT * FROM pagecompositionrevision ORDER BY id"
        ),
    )

    def fail_validation(*_args, **_kwargs):
        raise PageCompositionError("injected PostgreSQL refresh failure")

    monkeypatch.setattr(composition_service, "_validate", fail_validation)
    with Session(database.engine) as session:
        result = refresh_site_plan_compositions(session, int(scope["plan_id"]))
        assert result.created == result.refreshed == result.unchanged == 0
        assert result.blocked
    assert before == (
        _query_fingerprint(database.engine, "SELECT * FROM pagecomposition ORDER BY id"),
        _query_fingerprint(
            database.engine, "SELECT * FROM pagecompositionrevision ORDER BY id"
        ),
    )


def test_11_pg_triggers_reject_update_delete_truncate_and_payload_tamper_fails_closed(
    page_composition_postgres_plan: _PostgresPlan,
) -> None:
    database = page_composition_postgres_plan.database(11)
    _upgrade(database, REVISION_0047)
    identities = _seed_migration_bound_composition(database)
    _upgrade(database, REVISION_0048)
    composition_id = int(identities["composition_id"])
    before = _history_rows(database.engine, composition_id)
    mutations = (
        "UPDATE pagecompositionrevision SET recorded_by = 'tamper'",
        "DELETE FROM pagecompositionrevision",
        "TRUNCATE TABLE pagecompositionrevision CASCADE",
    )
    for statement in mutations:
        with pytest.raises(DBAPIError, match="immutable"):
            with database.engine.begin() as connection:
                connection.exec_driver_sql(statement)
        assert _history_rows(database.engine, composition_id) == before

    with database.engine.begin() as connection:
        _disable_immutability_triggers(connection)
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE pagecompositionrevision "
                    "SET generated_components = CAST(:payload AS JSON) "
                    "WHERE page_composition_id = :composition_id"
                ),
                {
                    "payload": json.dumps([{"tampered": True}]),
                    "composition_id": composition_id,
                },
            )
    finally:
        with database.engine.begin() as connection:
            _enable_immutability_triggers(connection)
    with Session(database.engine) as session:
        with pytest.raises(PageCompositionHistoryError, match="hash|diverges"):
            read_composition_revision(
                session,
                composition_id,
                int(identities["version"]),
            )


def test_12_tampered_source_hash_fails_closed_even_when_head_tuple_is_substituted(
    page_composition_postgres_plan: _PostgresPlan,
) -> None:
    database = page_composition_postgres_plan.database(12)
    _upgrade(database, REVISION_0047)
    identities = _seed_migration_bound_composition(database)
    _upgrade(database, REVISION_0048)
    composition_id = int(identities["composition_id"])
    substituted = "f" * 64
    with database.engine.begin() as connection:
        _disable_immutability_triggers(connection)
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE pagecompositionrevision SET source_hash = :hash "
                    "WHERE page_composition_id = :composition_id"
                ),
                {"hash": substituted, "composition_id": composition_id},
            )
            connection.execute(
                text(
                    "UPDATE pagecomposition SET source_hash = :hash "
                    "WHERE id = :composition_id"
                ),
                {"hash": substituted, "composition_id": composition_id},
            )
            connection.execute(
                text(
                    "UPDATE generatedpageqaresult SET composition_source_hash = :hash "
                    "WHERE page_composition_id = :composition_id"
                ),
                {"hash": substituted, "composition_id": composition_id},
            )
    finally:
        with database.engine.begin() as connection:
            _enable_immutability_triggers(connection)
    with Session(database.engine) as session:
        composition = session.get(PageComposition, composition_id)
        assert composition is not None
        with pytest.raises(PageCompositionHistoryError, match="source hash"):
            current_composition_revision(session, composition)


def test_13_tampered_predecessor_hash_lineage_fails_closed(
    page_composition_postgres_plan: _PostgresPlan,
) -> None:
    database = page_composition_postgres_plan.database(13)
    _upgrade(database, REVISION_0047)
    identities = _seed_migration_bound_composition(database)
    _upgrade(database, REVISION_0048)
    composition_id = int(identities["composition_id"])
    with Session(database.engine) as session:
        composition = session.get(PageComposition, composition_id)
        assert composition is not None
        snapshot = {**composition.source_snapshot, "lineage_control": True}
        advance_composition_revision(
            session,
            composition,
            generated_components=composition.generated_components,
            operator_decisions=composition.operator_decisions,
            source_snapshot=snapshot,
            source_hash=canonical_payload_hash(snapshot),
            generated_at=composition.generated_at + timedelta(seconds=1),
            decided_by=composition.decided_by,
            decided_at=composition.decided_at,
            recorded_at=datetime.now(UTC),
            recorded_by="migration-test:lineage",
            record_source="lineage_test",
        )
        session.commit()
    with database.engine.begin() as connection:
        _disable_immutability_triggers(connection)
        connection.execute(
            text(
                "UPDATE pagecompositionrevision "
                "SET supersedes_revision_hash = :hash "
                "WHERE page_composition_id = :composition_id "
                "AND lineage_kind = 'successor'"
            ),
            {"hash": "e" * 64, "composition_id": composition_id},
        )
        _enable_immutability_triggers(connection)
    with Session(database.engine) as session:
        composition = session.get(PageComposition, composition_id)
        assert composition is not None
        with pytest.raises(PageCompositionHistoryError, match="hash|lineage"):
            validate_composition_stream(session, composition)


def test_14_cross_page_historical_reference_and_qa_substitution_fail_closed(
    page_composition_postgres_plan: _PostgresPlan,
) -> None:
    database = page_composition_postgres_plan.database(14)
    _upgrade(database, REVISION_0048)
    scope = _seed_synthetic_head(database, suffix="pg14")
    first_page_id = int(scope["pages"][0][1])
    second_page_id = int(scope["pages"][1][1])
    first_composition_id = int(scope["composition_ids"][0])
    with Session(database.engine) as session:
        composition = session.get(PageComposition, first_composition_id)
        assert composition is not None
        qa = _insert_bound_qa(session, composition)
        with pytest.raises(PageCompositionHistoryError, match="Generated Page boundary"):
            read_composition_revision(
                session,
                first_composition_id,
                composition.composition_version,
                generated_page_id=second_page_id,
            )
        qa_id = qa.id
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE generatedpageqaresult SET generated_page_id = :page_id "
                "WHERE id = :qa_id"
            ),
            {"page_id": second_page_id, "qa_id": qa_id},
        )
    with Session(database.engine) as session:
        with pytest.raises(ValueError, match="Generated Page boundary"):
            resolve_qa_composition_revision(session, int(qa_id))
    assert first_page_id != second_page_id


def test_15_cross_website_historical_reference_and_qa_substitution_fail_closed(
    page_composition_postgres_plan: _PostgresPlan,
) -> None:
    database = page_composition_postgres_plan.database(15)
    _upgrade(database, REVISION_0048)
    first = _seed_synthetic_head(database, suffix="pg15a")
    second = _seed_synthetic_head(database, suffix="pg15b")
    composition_id = int(first["composition_ids"][0])
    second_website_id = int(second["website_id"])
    with Session(database.engine) as session:
        composition = session.get(PageComposition, composition_id)
        assert composition is not None
        qa = _insert_bound_qa(session, composition)
        with pytest.raises(PageCompositionHistoryError, match="Website boundary"):
            read_composition_revision(
                session,
                composition_id,
                composition.composition_version,
                website_id=second_website_id,
            )
        qa_id = qa.id
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE generatedpageqaresult SET website_id = :website_id "
                "WHERE id = :qa_id"
            ),
            {"website_id": second_website_id, "qa_id": qa_id},
        )
    with Session(database.engine) as session:
        with pytest.raises(ValueError, match="Website boundary"):
            resolve_qa_composition_revision(session, int(qa_id))


def test_16_unknown_partial_history_schema_is_rejected_transactionally(
    page_composition_postgres_plan: _PostgresPlan,
) -> None:
    database = page_composition_postgres_plan.database(16)
    _upgrade(database, REVISION_0047)
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE pagecompositionrevision (id BIGINT PRIMARY KEY)"
        )
    before = _catalog_snapshot(database.engine)
    with pytest.raises(RuntimeError, match="refuses pre-created|pre-created"):
        _upgrade(database, REVISION_0048)
    assert _revision(database.engine) == REVISION_0047
    assert _catalog_snapshot(database.engine) == before


def test_17_downgrade_is_lossless_only_for_pristine_migration_roots(
    page_composition_postgres_plan: _PostgresPlan,
) -> None:
    database = page_composition_postgres_plan.database(17)
    _upgrade(database, REVISION_0047)
    identities = _seed_migration_bound_composition(database)
    before = _query_fingerprint(
        database.engine,
        "SELECT * FROM pagecomposition WHERE id = :id",
        {"id": identities["composition_id"]},
    )
    _upgrade(database, REVISION_0048)
    _downgrade(database, REVISION_0047)
    assert _revision(database.engine) == REVISION_0047
    assert TABLE not in inspect(database.engine).get_table_names()
    assert _query_fingerprint(
        database.engine,
        "SELECT * FROM pagecomposition WHERE id = :id",
        {"id": identities["composition_id"]},
    ) == before

    _upgrade(database, REVISION_0048)
    composition_id = int(identities["composition_id"])
    with Session(database.engine) as session:
        composition = session.get(PageComposition, composition_id)
        assert composition is not None
        snapshot = {**composition.source_snapshot, "downgrade_successor": True}
        advance_composition_revision(
            session,
            composition,
            generated_components=composition.generated_components,
            operator_decisions=composition.operator_decisions,
            source_snapshot=snapshot,
            source_hash=canonical_payload_hash(snapshot),
            generated_at=composition.generated_at + timedelta(seconds=1),
            decided_by=composition.decided_by,
            decided_at=composition.decided_at,
            recorded_at=datetime.now(UTC),
            recorded_by="migration-test:downgrade",
            record_source="downgrade_successor_test",
        )
        session.commit()
    before_blocked = (
        _catalog_snapshot(database.engine),
        _history_rows(database.engine, composition_id),
    )
    with pytest.raises(RuntimeError, match="Recover through an accepted backup|successor"):
        _downgrade(database, REVISION_0047)
    assert _revision(database.engine) == REVISION_0048
    assert before_blocked == (
        _catalog_snapshot(database.engine),
        _history_rows(database.engine, composition_id),
    )
