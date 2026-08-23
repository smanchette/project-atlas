from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from threading import Event
from typing import Any, Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from app.services import public_copy_reconciliation as reconciliation_service
from app.services.public_copy_manifest import PublicCopyManifestPackage
from app.services.public_copy_reconciliation import (
    PublicCopyReconciliationError,
    reconcile_public_copy,
)
from scripts import public_copy_reconciliation_runner as runner


BACKEND = Path(__file__).parents[1]
ROOT = BACKEND.parent

POSTGRES_GO_ENV = "ATLAS_PUBLIC_COPY_REHEARSAL_POSTGRES_GO"
POSTGRES_GO_VALUE = "SOURCE-FREEZE/PG-GO"
POSTGRES_ADMIN_URL_ENV = "ATLAS_PUBLIC_COPY_REHEARSAL_POSTGRES_ADMIN_URL"
POSTGRES_DATABASE_NAMES_ENV = (
    "ATLAS_PUBLIC_COPY_REHEARSAL_POSTGRES_DATABASE_NAMES"
)
POSTGRES_EXECUTION_LEDGER_ENV = (
    "ATLAS_PUBLIC_COPY_REHEARSAL_POSTGRES_EXECUTION_LEDGER"
)
POSTGRES_EXECUTION_LEDGER_SHA256_ENV = (
    "ATLAS_PUBLIC_COPY_REHEARSAL_POSTGRES_EXECUTION_LEDGER_SHA256"
)

EXECUTION_LEDGER_SCHEMA = (
    "atlas-public-copy-reconciliation-postgresql-execution-ledger@1"
)
EXECUTION_OPERATION = "public_copy_reconciliation_postgresql_rehearsal_only"
EXPECTED_DATABASE_PREFIX = "atlas_pcopy_rehearsal_"
EXPECTED_DATABASE_NAMES = ("atlas_pcopy_rehearsal_01",)
EXPECTED_POSTGRES_HOST = "atlas_pcopy_rehearsal_pg"
EXPECTED_ATLAS_REVISION = "20260820_0048"
EXPECTED_AFFECTED_PAGE_COUNT = 65
EXPECTED_INJECTED_FAILURE_AFTER_QA = 33
EXPECTED_PAGE_41_ID = 41
EXPECTED_PAGE_41_COMPOSITION_VERSION = 8
EXPECTED_PAGE_41_QA_ID = 80
EXPECTED_ACTOR = "public-copy-reconciliation-operator"

MANIFEST_RELATIVE_PATH = (
    ".runtime/public-copy-cleanup-progress/"
    "public-copy-correction-manifest.json"
)
RULESET_RELATIVE_PATH = (
    ".runtime/public-copy-cleanup-progress/public-copy-ruleset.json"
)
RUNNER_RELATIVE_PATH = "backend/scripts/public_copy_reconciliation_runner.py"
INVOCATION_CONFIG_RELATIVE_PATH = (
    ".runtime/public-copy-cleanup-progress/"
    "public-copy-reconciliation-invocation.json"
)

SEQUENCE_RESTORE_ALLOWLIST = (
    "generatedpagerevision_id_seq",
    "pagecompositionrevision_id_seq",
    "generatedpageqaresult_id_seq",
)

PROTECTED_TABLES = (
    # Complete governed copy/composition source inventory and operator intents.
    "brand",
    "business",
    "city",
    "county",
    "draftingeligibilityassessment",
    "draftingeligibilitydisposition",
    "internallinkintent",
    "knowledgeblock",
    "navigationitem",
    "navigationset",
    "plannedpage",
    "planningrecord",
    "predraftdistinctnessbrief",
    "service",
    "siteplan",
    "supportingpageauthorization",
    "website",
    "websitecitycoveragedecision",
    "websitecountycoveragedecision",
    "websiteidentity",
    "websiteservicecitycoveragedecision",
    "websiteservicecountycoveragedecision",
    "websiteservicecoveragedecision",
    # Governed media and assignments, including Page 41.
    "brandasset",
    "imagemetadata",
    "pageimageassignment",
    "plannedpagemediarequirement",
    "scopedmediaauthorization",
    "websiteidentityassetassignment",
    "websitemediaplanningrecord",
    # Theme and the immutable Performance Local V2/V3 configuration domain.
    "semanticcomponentdefinition",
    "theme",
    "themeconfigurationaudit",
    "themefamily",
    "themefamilyversion",
    "websitethemecomponentconfiguration",
    "websitethemeconfiguration",
    "websitethemeselection",
    # Forms, provider planning, and customer-data-bearing tables.
    "formdeliveryattempt",
    "formdeliveryconfigurationaudit",
    "formdeliveryoutbox",
    "formsubmissionenvelope",
    "siteconnectionplanningrecord",
    "websiteformdeliverymoderevision",
    "websiteformrecipientrevision",
)

CUSTOMER_DATA_TABLES = (
    "formsubmissionenvelope",
    "formdeliveryoutbox",
    "formdeliveryattempt",
)

HISTORY_TABLES = (
    "generatedpagerevision",
    "pagecompositionrevision",
    "generatedpageqaresult",
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SAFE_DATABASE_PATTERN = re.compile(r"^atlas_pcopy_rehearsal_[0-9]{2}$")
_SAFE_TABLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class _PreparedRunner:
    success: runner.PreparedInvocation
    injected_failure: runner.PreparedInvocation


@dataclass
class _PostgresRehearsalPlan:
    admin_engine: Engine
    database_engine: Engine
    admin_url: URL
    database_url: URL
    database_name: str
    execution_ledger_path: Path
    execution_ledger: dict[str, Any]
    prepared: _PreparedRunner


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


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_sha256(value: Any, *, field: str) -> str:
    assert isinstance(value, str) and _SHA256_PATTERN.fullmatch(value), (
        f"{field} must be one exact lowercase SHA-256 value."
    )
    return value


def _is_link_or_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _assert_no_link_components(path: Path, *, stop: Path) -> None:
    resolved_stop = stop.resolve(strict=True)
    current = path.absolute()
    while True:
        if _is_link_or_reparse(current):
            raise AssertionError(
                f"PostgreSQL rehearsal path has a symlink/reparse component: {current}"
            )
        if current == resolved_stop:
            return
        parent = current.parent
        if parent == current:
            raise AssertionError(
                f"PostgreSQL rehearsal path escaped its approved root: {path}"
            )
        current = parent


def _strict_json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    if payload.startswith(b"\xef\xbb\xbf") or b"\x00" in payload:
        raise AssertionError(f"{label} is not exact BOM-free UTF-8 JSON.")

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AssertionError(f"{label} contains duplicate key {key!r}.")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise AssertionError(f"{label} contains non-finite JSON value {value}.")

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=object_pairs,
            parse_constant=invalid_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"{label} is not strict UTF-8 JSON.") from exc
    assert isinstance(value, dict), f"{label} must be a JSON object."
    return value


def _require_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    *,
    field: str,
) -> None:
    assert set(value) == expected, f"{field} has an incomplete or unknown contract."


def _resolve_repo_file(
    contract: dict[str, Any],
    *,
    field: str,
    exact_relative_path: str | None = None,
    required_parent: str | None = None,
) -> Path:
    _require_exact_keys(contract, {"path", "sha256"}, field=field)
    relative_value = contract["path"]
    assert isinstance(relative_value, str) and relative_value
    assert "\\" not in relative_value
    relative = PurePosixPath(relative_value)
    assert not relative.is_absolute() and ".." not in relative.parts
    if exact_relative_path is not None:
        assert relative_value == exact_relative_path
    if required_parent is not None:
        assert relative_value.startswith(required_parent.rstrip("/") + "/")
    candidate = ROOT.joinpath(*relative.parts)
    _assert_no_link_components(candidate, stop=ROOT)
    resolved = candidate.resolve(strict=True)
    assert resolved.is_file() and not _is_link_or_reparse(resolved)
    assert _sha256_file(resolved) == _required_sha256(
        contract["sha256"], field=f"{field}.sha256"
    )
    return resolved


def _load_execution_ledger(path: Path, expected_sha256: str) -> dict[str, Any]:
    runtime_root = (ROOT / ".runtime" / "public-copy-cleanup-progress").resolve(
        strict=True
    )
    _assert_no_link_components(path, stop=runtime_root)
    resolved = path.resolve(strict=True)
    assert resolved.is_file() and not _is_link_or_reparse(resolved)
    expected = _required_sha256(
        expected_sha256,
        field=POSTGRES_EXECUTION_LEDGER_SHA256_ENV,
    )
    payload = resolved.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == expected
    return _strict_json_object(payload, label="PostgreSQL rehearsal execution ledger")


def _write_execution_ledger(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    temporary.replace(path)


def _validate_execution_ledger(
    payload: dict[str, Any],
    *,
    clone_database_url: str,
) -> tuple[dict[str, Path], str]:
    _require_exact_keys(
        payload,
        {
            "schema",
            "operation",
            "source_freeze_go_received",
            "postgresql_go_received",
            "atlas_revision",
            "database_prefix",
            "disposable_database_names",
            "source_pins",
            "runner_contract",
            "preloaded_post_0048_clone",
            "sequence_restore_allowlist",
            "no_migration",
            "customer_data",
            "external_requests",
            "status",
            "reports",
            "cleanup",
        },
        field="PostgreSQL rehearsal execution ledger",
    )
    assert payload["schema"] == EXECUTION_LEDGER_SCHEMA
    assert payload["operation"] == EXECUTION_OPERATION
    assert payload["source_freeze_go_received"] is True
    assert payload["postgresql_go_received"] is True
    assert payload["atlas_revision"] == EXPECTED_ATLAS_REVISION
    assert payload["database_prefix"] == EXPECTED_DATABASE_PREFIX
    assert payload["no_migration"] is True
    assert payload["customer_data"] is False
    assert payload["external_requests"] is False
    assert payload["status"] == "PROVISIONED_SOURCE_FREEZE_PG_GO"
    assert payload["reports"] == []
    assert payload["cleanup"] == {
        "sessions_terminated": False,
        "database_removed": False,
        "database_confirmed_absent": False,
    }

    records = payload["disposable_database_names"]
    assert records == [
        {
            "ordinal": 1,
            "name": EXPECTED_DATABASE_NAMES[0],
            "recorded_before_creation": True,
            "created": True,
            "removed": False,
            "confirmed_absent": False,
        }
    ]
    assert payload["sequence_restore_allowlist"] == list(
        SEQUENCE_RESTORE_ALLOWLIST
    )

    pins = payload["source_pins"]
    assert isinstance(pins, dict)
    _require_exact_keys(
        pins,
        {
            "source_root",
            "manifest",
            "ruleset",
            "runner",
            "invocation_config",
            "postgres_rehearsal_harness",
            "postgres_rehearsal_conftest",
        },
        field="source_pins",
    )
    source_root_contract = pins["source_root"]
    _require_exact_keys(
        source_root_contract, {"path", "sha256"}, field="source_pins.source_root"
    )
    assert source_root_contract["path"] == "."
    source_root_sha256 = _required_sha256(
        source_root_contract["sha256"], field="source_pins.source_root.sha256"
    )
    observed_root, observed_root_sha256 = runner._validate_source_root(ROOT)
    assert observed_root == ROOT.resolve(strict=True)
    assert observed_root_sha256 == source_root_sha256
    resolved_pins = {
        "source_root": observed_root,
        "manifest": _resolve_repo_file(
            pins["manifest"],
            field="source_pins.manifest",
            exact_relative_path=MANIFEST_RELATIVE_PATH,
        ),
        "ruleset": _resolve_repo_file(
            pins["ruleset"],
            field="source_pins.ruleset",
            exact_relative_path=RULESET_RELATIVE_PATH,
        ),
        "runner": _resolve_repo_file(
            pins["runner"],
            field="source_pins.runner",
            exact_relative_path=RUNNER_RELATIVE_PATH,
        ),
        "invocation_config": _resolve_repo_file(
            pins["invocation_config"],
            field="source_pins.invocation_config",
            exact_relative_path=INVOCATION_CONFIG_RELATIVE_PATH,
        ),
        "postgres_rehearsal_harness": _resolve_repo_file(
            pins["postgres_rehearsal_harness"],
            field="source_pins.postgres_rehearsal_harness",
            exact_relative_path=runner.POSTGRES_REHEARSAL_HARNESS_PATH,
        ),
        "postgres_rehearsal_conftest": _resolve_repo_file(
            pins["postgres_rehearsal_conftest"],
            field="source_pins.postgres_rehearsal_conftest",
            exact_relative_path=runner.POSTGRES_REHEARSAL_CONFTEST_PATH,
        ),
    }
    assert pins["runner"]["sha256"] == runner.runner_file_sha256()
    assert pins["postgres_rehearsal_harness"]["sha256"] == _sha256_file(
        Path(__file__)
    )
    assert pins["postgres_rehearsal_conftest"]["sha256"] == _sha256_file(
        BACKEND / "tests" / "conftest.py"
    )

    runner_contract = payload["runner_contract"]
    assert isinstance(runner_contract, dict)
    _require_exact_keys(
        runner_contract,
        {
            "actor",
            "target_role",
            "success_mode",
            "failure_mode",
            "inject_failure_after_qa",
            "commit",
            "clone_database_url_sha256",
            "expected_affected_page_count",
        },
        field="runner_contract",
    )
    assert runner_contract == {
        "actor": EXPECTED_ACTOR,
        "target_role": runner.TARGET_ROLE_DISPOSABLE_CLONE,
        "success_mode": runner.MODE_REHEARSAL_SUCCESS,
        "failure_mode": runner.MODE_REHEARSAL_INJECTED_FAILURE,
        "inject_failure_after_qa": EXPECTED_INJECTED_FAILURE_AFTER_QA,
        "commit": True,
        "clone_database_url_sha256": hashlib.sha256(
            clone_database_url.encode("utf-8")
        ).hexdigest(),
        "expected_affected_page_count": EXPECTED_AFFECTED_PAGE_COUNT,
    }

    clone = payload["preloaded_post_0048_clone"]
    assert isinstance(clone, dict)
    _require_exact_keys(
        clone,
        {
            "database_name",
            "dump",
            "restored_before_tests",
            "migration_applied_by_test",
            "atlas_revision",
            "database_fingerprint_sha256",
            "sequence_state_sha256",
        },
        field="preloaded_post_0048_clone",
    )
    assert clone["database_name"] == EXPECTED_DATABASE_NAMES[0]
    assert clone["restored_before_tests"] is True
    assert clone["migration_applied_by_test"] is False
    assert clone["atlas_revision"] == EXPECTED_ATLAS_REVISION
    _required_sha256(
        clone["database_fingerprint_sha256"],
        field="preloaded_post_0048_clone.database_fingerprint_sha256",
    )
    _required_sha256(
        clone["sequence_state_sha256"],
        field="preloaded_post_0048_clone.sequence_state_sha256",
    )
    resolved_pins["dump"] = _resolve_repo_file(
        clone["dump"],
        field="preloaded_post_0048_clone.dump",
        required_parent=".runtime/public-copy-cleanup-progress/recovery",
    )
    return resolved_pins, source_root_sha256


def _runner_arguments(
    *,
    database_url: str,
    pins: dict[str, Path],
    ledger: dict[str, Any],
    mode: str,
) -> runner.RunnerArguments:
    source_pins = ledger["source_pins"]
    return runner.RunnerArguments(
        database_url=database_url,
        source_root=pins["source_root"],
        manifest_path=pins["manifest"],
        manifest_sha256=source_pins["manifest"]["sha256"],
        ruleset_path=pins["ruleset"],
        ruleset_sha256=source_pins["ruleset"]["sha256"],
        invocation_config_path=pins["invocation_config"],
        invocation_config_sha256=source_pins["invocation_config"]["sha256"],
        target_role=runner.TARGET_ROLE_DISPOSABLE_CLONE,
        mode=mode,
        actor=EXPECTED_ACTOR,
        commit=True,
    )


def _prepare_runner(
    *,
    database_url: str,
    pins: dict[str, Path],
    ledger: dict[str, Any],
) -> _PreparedRunner:
    success = runner.prepare_invocation(
        _runner_arguments(
            database_url=database_url,
            pins=pins,
            ledger=ledger,
            mode=runner.MODE_REHEARSAL_SUCCESS,
        )
    )
    injected_failure = runner.prepare_invocation(
        _runner_arguments(
            database_url=database_url,
            pins=pins,
            ledger=ledger,
            mode=runner.MODE_REHEARSAL_INJECTED_FAILURE,
        )
    )
    assert success.package == injected_failure.package
    assert success.invocation["inject_failure_after_qa"] is None
    assert (
        injected_failure.invocation["inject_failure_after_qa"]
        == EXPECTED_INJECTED_FAILURE_AFTER_QA
    )
    return _PreparedRunner(success=success, injected_failure=injected_failure)


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        rows = tuple(
            connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version ORDER BY version_num"
            ).scalars()
        )
    assert rows == (EXPECTED_ATLAS_REVISION,)
    return rows[0]


def _public_table_names(connection) -> tuple[str, ...]:
    return tuple(
        str(name)
        for name in connection.execute(
            text(
                "SELECT relation.relname FROM pg_class AS relation "
                "JOIN pg_namespace AS namespace "
                "ON namespace.oid = relation.relnamespace "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relkind IN ('r','p') "
                "ORDER BY relation.relname"
            )
        ).scalars()
    )


def _capture_table_rows_on_connection(
    connection: Any,
    table: str,
    *,
    where: str = "TRUE",
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    assert _SAFE_TABLE_PATTERN.fullmatch(table)
    quoted = connection.dialect.identifier_preparer.quote(table)
    rows = list(
        connection.execute(
            text(
                f"SELECT to_jsonb(source) FROM "
                f"(SELECT * FROM {quoted} WHERE {where}) AS source"
            ),
            parameters or {},
        ).scalars()
    )
    canonical = [_canonical_value(row) for row in rows]
    return sorted(canonical, key=lambda item: _canonical_json_bytes(item))


def _capture_table_rows(
    engine: Engine,
    table: str,
    *,
    where: str = "TRUE",
    parameters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return _capture_table_rows_on_connection(
            connection,
            table,
            where=where,
            parameters=parameters,
        )


def _table_fingerprint_on_connection(
    connection: Any,
    table: str,
) -> dict[str, Any]:
    rows = _capture_table_rows_on_connection(connection, table)
    return {"row_count": len(rows), "sha256": _canonical_sha256(rows)}


def _database_fingerprint(engine: Engine) -> str:
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            tables = _public_table_names(connection)
            return _canonical_sha256(
                {
                    table: _table_fingerprint_on_connection(connection, table)
                    for table in tables
                }
            )


def _protected_fingerprints(engine: Engine) -> dict[str, dict[str, Any]]:
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            tables = set(_public_table_names(connection))
            assert set(PROTECTED_TABLES).issubset(tables)
            return {
                table: _table_fingerprint_on_connection(connection, table)
                for table in PROTECTED_TABLES
            }


def _history_rows(engine: Engine) -> dict[str, list[dict[str, Any]]]:
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            return {
                table: _capture_table_rows_on_connection(connection, table)
                for table in HISTORY_TABLES
            }


def _rows_by_id(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result = {int(row["id"]): row for row in rows}
    assert len(result) == len(rows)
    return result


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


def _assert_no_other_database_sessions(engine: Engine) -> None:
    with engine.connect() as connection:
        other_sessions = connection.execute(
            text(
                "SELECT COUNT(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        ).scalar_one()
    assert other_sessions == 0, (
        "Disposable public-copy clone has an unauthorized concurrent session."
    )


def _restore_allowlisted_clone_sequences(
    plan: _PostgresRehearsalPlan,
    before: dict[str, tuple[int, bool]],
    after: dict[str, tuple[int, bool]],
) -> None:
    changed = {name for name in before if before[name] != after.get(name)}
    assert changed == set(SEQUENCE_RESTORE_ALLOWLIST)
    assert set(before) == set(after)
    assert plan.database_name == EXPECTED_DATABASE_NAMES[0]
    assert plan.execution_ledger["sequence_restore_allowlist"] == list(
        SEQUENCE_RESTORE_ALLOWLIST
    )

    with plan.database_engine.begin() as connection:
        connection.exec_driver_sql(
            "LOCK TABLE generatedpagerevision, pagecompositionrevision, "
            "generatedpageqaresult IN ACCESS EXCLUSIVE MODE"
        )
        other_sessions = connection.execute(
            text(
                "SELECT COUNT(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        ).scalar_one()
        assert other_sessions == 0, (
            "Clone-only sequence restoration refuses concurrent database sessions."
        )
        preparer = connection.dialect.identifier_preparer
        for name in SEQUENCE_RESTORE_ALLOWLIST:
            value, is_called = before[name]
            connection.execute(
                text(
                    f"SELECT setval(CAST(:sequence AS regclass), :value, :is_called)"
                ),
                {
                    "sequence": f"public.{preparer.quote(name)}",
                    "value": value,
                    "is_called": is_called,
                },
            )
    assert _sequence_state(plan.database_engine) == before


def _assert_no_customer_data(engine: Engine) -> None:
    for table in CUSTOMER_DATA_TABLES:
        rows = _capture_table_rows(engine, table)
        assert rows == [], f"Disposable clone unexpectedly contains {table} rows."


def _assert_exact_inventory(
    engine: Engine,
    package: PublicCopyManifestPackage,
) -> None:
    scope = package.manifest["scope"]
    bindings = package.manifest["page_bindings"]
    assert scope["affected_page_count"] == EXPECTED_AFFECTED_PAGE_COUNT
    assert len(bindings) == EXPECTED_AFFECTED_PAGE_COUNT
    planned_ids = [int(item["planned_page_id"]) for item in bindings]
    generated_ids = sorted(int(item["generated_page_id"]) for item in bindings)
    assert len(set(planned_ids)) == len(set(generated_ids)) == 65
    with engine.connect() as connection:
        observed_planned = list(
            connection.execute(
                text(
                    "SELECT id FROM plannedpage WHERE site_plan_id = :site_plan_id "
                    "ORDER BY id"
                ),
                {"site_plan_id": int(scope["site_plan_id"])},
            ).scalars()
        )
        observed_generated = list(
            connection.execute(
                text(
                    "SELECT id FROM generatedpage WHERE website_id = :website_id "
                    "ORDER BY id"
                ),
                {"website_id": int(scope["website_id"])},
            ).scalars()
        )
        observed_compositions = list(
            connection.execute(
                text(
                    "SELECT planned_page_id FROM pagecomposition "
                    "WHERE site_plan_id = :site_plan_id ORDER BY planned_page_id"
                ),
                {"site_plan_id": int(scope["site_plan_id"])},
            ).scalars()
        )
        observed_current_qa = list(
            connection.execute(
                text(
                    "SELECT planned_page_id FROM generatedpageqaresult "
                    "WHERE site_plan_id = :site_plan_id "
                    "AND lifecycle_status = 'current' ORDER BY planned_page_id"
                ),
                {"site_plan_id": int(scope["site_plan_id"])},
            ).scalars()
        )
    assert observed_planned == planned_ids
    assert observed_generated == generated_ids
    assert observed_compositions == planned_ids
    assert observed_current_qa == planned_ids


def _assert_preloaded_page41_identity(
    engine: Engine,
    package: PublicCopyManifestPackage,
) -> dict[str, Any]:
    binding = next(
        item
        for item in package.manifest["page_bindings"]
        if int(item["generated_page_id"]) == EXPECTED_PAGE_41_ID
    )
    assert int(binding["current_composition"]["id"]) == EXPECTED_PAGE_41_ID
    assert (
        int(binding["current_composition"]["version"])
        == EXPECTED_PAGE_41_COMPOSITION_VERSION
    )
    assert int(binding["current_qa"]["id"]) == EXPECTED_PAGE_41_QA_ID
    history_id = int(binding["current_composition"]["history_revision_id"])
    composition_rows = _capture_table_rows(
        engine,
        "pagecompositionrevision",
        where="id = :id",
        parameters={"id": history_id},
    )
    qa_rows = _capture_table_rows(
        engine,
        "generatedpageqaresult",
        where="id = :id",
        parameters={"id": EXPECTED_PAGE_41_QA_ID},
    )
    assert len(composition_rows) == len(qa_rows) == 1
    assert composition_rows[0]["page_composition_id"] == EXPECTED_PAGE_41_ID
    assert (
        composition_rows[0]["composition_version"]
        == EXPECTED_PAGE_41_COMPOSITION_VERSION
    )
    assert qa_rows[0]["generated_page_id"] == EXPECTED_PAGE_41_ID
    assert qa_rows[0]["page_composition_id"] == EXPECTED_PAGE_41_ID
    assert qa_rows[0]["composition_version"] == EXPECTED_PAGE_41_COMPOSITION_VERSION
    assert qa_rows[0]["lifecycle_status"] == "current"
    return {
        "binding": binding,
        "composition_history_id": history_id,
        "composition_revision": composition_rows[0],
        "qa80": qa_rows[0],
    }


def _assert_preexisting_history_preserved(
    before: dict[str, list[dict[str, Any]]],
    after: dict[str, list[dict[str, Any]]],
) -> None:
    before_gpr = _rows_by_id(before["generatedpagerevision"])
    after_gpr = _rows_by_id(after["generatedpagerevision"])
    assert {row_id: after_gpr[row_id] for row_id in before_gpr} == before_gpr
    assert len(after_gpr) == len(before_gpr) + EXPECTED_AFFECTED_PAGE_COUNT

    before_composition = _rows_by_id(before["pagecompositionrevision"])
    after_composition = _rows_by_id(after["pagecompositionrevision"])
    assert {
        row_id: after_composition[row_id] for row_id in before_composition
    } == before_composition
    assert len(after_composition) == (
        len(before_composition) + EXPECTED_AFFECTED_PAGE_COUNT
    )

    before_qa = _rows_by_id(before["generatedpageqaresult"])
    after_qa = _rows_by_id(after["generatedpageqaresult"])
    historical_before = {
        row_id: row
        for row_id, row in before_qa.items()
        if row["lifecycle_status"] != "current"
    }
    assert {row_id: after_qa[row_id] for row_id in historical_before} == (
        historical_before
    )
    current_before = {
        row_id: row
        for row_id, row in before_qa.items()
        if row["lifecycle_status"] == "current"
    }
    assert len(current_before) == EXPECTED_AFFECTED_PAGE_COUNT
    successors = {
        int(row["supersedes_qa_result_id"]): row
        for row in after_qa.values()
        if row.get("supersedes_qa_result_id") is not None
        and int(row["id"]) not in before_qa
    }
    assert set(successors) == set(current_before)
    for row_id, prior in current_before.items():
        observed = after_qa[row_id]
        successor = successors[row_id]
        expected = deepcopy(prior)
        expected["lifecycle_status"] = "superseded"
        expected["updated_at"] = successor["created_at"]
        assert observed == expected
        assert successor["lifecycle_status"] == "current"
    assert len(after_qa) == len(before_qa) + EXPECTED_AFFECTED_PAGE_COUNT


def _assert_page41_successor(
    engine: Engine,
    *,
    report: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    result = report["reconciliation_result"]
    page_result = next(
        item
        for item in result["page_results"]
        if int(item["generated_page_id"]) == EXPECTED_PAGE_41_ID
    )
    assert page_result["old_composition_version"] == 8
    assert page_result["new_composition_version"] == 9
    assert page_result["old_qa_result_id"] == EXPECTED_PAGE_41_QA_ID
    assert page_result["new_qa_result_id"] > EXPECTED_PAGE_41_QA_ID
    assert page_result["old_composition_source_hash"] != (
        page_result["new_composition_source_hash"]
    )

    old_composition = _capture_table_rows(
        engine,
        "pagecompositionrevision",
        where="id = :id",
        parameters={"id": baseline["composition_history_id"]},
    )
    assert old_composition == [baseline["composition_revision"]]
    current_composition = _capture_table_rows(
        engine,
        "pagecomposition",
        where="id = :id",
        parameters={"id": EXPECTED_PAGE_41_ID},
    )
    assert len(current_composition) == 1
    assert current_composition[0]["composition_version"] == 9
    new_history = _capture_table_rows(
        engine,
        "pagecompositionrevision",
        where="page_composition_id = :id AND composition_version = 9",
        parameters={"id": EXPECTED_PAGE_41_ID},
    )
    assert len(new_history) == 1
    assert new_history[0]["supersedes_revision_id"] == (
        baseline["composition_history_id"]
    )
    assert new_history[0]["supersedes_revision_hash"] == (
        baseline["composition_revision"]["revision_hash"]
    )
    assert new_history[0]["generated_page_revision_id"] == (
        page_result["new_generated_page_revision_id"]
    )

    qa80 = _capture_table_rows(
        engine,
        "generatedpageqaresult",
        where="id = :id",
        parameters={"id": EXPECTED_PAGE_41_QA_ID},
    )
    assert len(qa80) == 1 and qa80[0]["lifecycle_status"] == "superseded"
    new_qa = _capture_table_rows(
        engine,
        "generatedpageqaresult",
        where="id = :id",
        parameters={"id": int(page_result["new_qa_result_id"])},
    )
    assert len(new_qa) == 1
    assert new_qa[0]["lifecycle_status"] == "current"
    assert new_qa[0]["supersedes_qa_result_id"] == EXPECTED_PAGE_41_QA_ID
    assert new_qa[0]["page_composition_id"] == EXPECTED_PAGE_41_ID
    assert new_qa[0]["composition_version"] == 9
    return {
        "page_result": page_result,
        "new_composition_revision": new_history[0],
        "qa80": qa80[0],
        "new_qa": new_qa[0],
    }


def _append_report(
    plan: _PostgresRehearsalPlan,
    *,
    stage: str,
    report: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    plan.execution_ledger["reports"].append(
        {
            "stage": stage,
            "outcome": report["outcome"],
            "transaction_outcome": report["transaction_outcome"],
            "report_sha256": report["report_sha256"],
            "evidence_sha256": _canonical_sha256(evidence),
        }
    )
    _write_execution_ledger(
        plan.execution_ledger_path,
        plan.execution_ledger,
    )


def _append_stage_evidence(
    plan: _PostgresRehearsalPlan,
    *,
    stage: str,
    outcome: str,
    evidence: dict[str, Any],
) -> None:
    item = {
        "stage": stage,
        "outcome": outcome,
        "evidence_sha256": _canonical_sha256(evidence),
    }
    plan.execution_ledger["reports"].append(item)
    _write_execution_ledger(
        plan.execution_ledger_path,
        plan.execution_ledger,
    )


def _assert_two_session_governed_writer_rejected(
    plan: _PostgresRehearsalPlan,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, str]:
    original = reconciliation_service._assert_correction_ledger_against_locked_drafts
    source_locks_held = Event()
    release_reconciliation = Event()
    paused_once = False

    def paused(*args: Any, **kwargs: Any) -> Any:
        nonlocal paused_once
        if not paused_once:
            paused_once = True
            source_locks_held.set()
            assert release_reconciliation.wait(20)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        reconciliation_service,
        "_assert_correction_ledger_against_locked_drafts",
        paused,
    )
    business_id = int(
        plan.prepared.success.package.manifest["governed_fact_snapshot"][
            "business"
        ]["id"]
    )
    with plan.database_engine.connect() as connection:
        eligibility_id = int(
            connection.execute(
                text("SELECT MIN(id) FROM draftingeligibilityassessment")
            ).scalar_one()
        )

    def reconciliation_worker() -> str:
        with Session(plan.database_engine) as session:
            result = reconcile_public_copy(
                session,
                plan.prepared.success.package,
                actor=EXPECTED_ACTOR,
                commit=True,
            )
            return result.status

    def blocked_writer(
        statement: str,
        parameters: dict[str, Any],
        started: Event,
        finished: Event,
        label: str,
    ) -> str | None:
        started.set()
        try:
            with plan.database_engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL lock_timeout = '750ms'")
                connection.execute(text(statement), parameters)
        except DBAPIError as exc:
            return getattr(exc.orig, "sqlstate", None)
        finally:
            finished.set()
        raise AssertionError(
            f"{label} was not blocked and rejected."
        )

    attempts = (
        (
            "governed_source_update",
            "UPDATE business SET description = description "
            "WHERE id = :business_id",
            {"business_id": business_id},
        ),
        (
            "governed_source_zero_row_insert",
            "INSERT INTO business SELECT * FROM business WHERE false",
            {},
        ),
        (
            "eligibility_update",
            "UPDATE draftingeligibilityassessment SET status = status "
            "WHERE id = :eligibility_id",
            {"eligibility_id": eligibility_id},
        ),
        (
            "eligibility_zero_row_insert",
            "INSERT INTO draftingeligibilityassessment "
            "SELECT * FROM draftingeligibilityassessment WHERE false",
            {},
        ),
    )
    sqlstates: dict[str, str] = {}

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            reconcile_future = executor.submit(reconciliation_worker)
            assert source_locks_held.wait(20)
            for label, statement, parameters in attempts:
                started = Event()
                finished = Event()
                writer_future = executor.submit(
                    blocked_writer,
                    statement,
                    parameters,
                    started,
                    finished,
                    label,
                )
                assert started.wait(10)
                assert finished.wait(0.2) is False
                sqlstate = writer_future.result(timeout=10)
                assert sqlstate == "55P03"
                sqlstates[label] = sqlstate
            release_reconciliation.set()
            assert reconcile_future.result(timeout=180) == "already_applied"
    finally:
        release_reconciliation.set()
    return sqlstates


def _assert_history_triggers_reject_mutation(
    engine: Engine,
    *,
    page41_revision_id: int,
    expected_history: list[dict[str, Any]],
) -> None:
    statements = (
        (
            "UPDATE pagecompositionrevision SET recorded_by = recorded_by "
            "WHERE id = :id",
            {"id": page41_revision_id},
        ),
        (
            "DELETE FROM pagecompositionrevision WHERE id = :id",
            {"id": page41_revision_id},
        ),
        ("TRUNCATE TABLE pagecompositionrevision, generatedpageqaresult, pagecomposition", {}),
    )
    for statement, parameters in statements:
        with pytest.raises(DBAPIError, match="immutable"):
            with engine.begin() as connection:
                connection.execute(text(statement), parameters)
        assert _capture_table_rows(engine, "pagecompositionrevision") == (
            expected_history
        )


def _tamper_current_destination_binding(engine: Engine) -> int:
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT id, generated_components FROM pagecomposition ORDER BY id"
            )
        ).all()
        for composition_id, raw_components in rows:
            components = deepcopy(raw_components)
            if not isinstance(components, list):
                continue
            for component in components:
                if not isinstance(component, dict):
                    continue
                bindings = component.get("input_bindings")
                if not isinstance(bindings, dict):
                    continue
                projection = bindings.get("public_destination_copy")
                if not isinstance(projection, list) or not projection:
                    continue
                item = projection[0]
                if not isinstance(item, dict) or not isinstance(
                    item.get("description"), str
                ):
                    continue
                item["description"] += " [disposable-tamper]"
                connection.execute(
                    text(
                        "UPDATE pagecomposition "
                        "SET generated_components = CAST(:payload AS JSON) "
                        "WHERE id = :id"
                    ),
                    {
                        "payload": json.dumps(components, ensure_ascii=True),
                        "id": int(composition_id),
                    },
                )
                return int(composition_id)
    raise AssertionError("No bound public-destination component was available to tamper.")


@pytest.fixture(scope="session")
def public_copy_postgres_plan() -> Iterator[_PostgresRehearsalPlan]:
    go_value = os.getenv(POSTGRES_GO_ENV)
    if go_value is None:
        pytest.skip(
            f"Set {POSTGRES_GO_ENV}={POSTGRES_GO_VALUE!r} only after exact "
            "SOURCE-FREEZE and PostgreSQL GO."
        )
    if go_value != POSTGRES_GO_VALUE:
        pytest.fail(f"{POSTGRES_GO_ENV} is not the exact authorized GO token.")

    names_value = os.getenv(POSTGRES_DATABASE_NAMES_ENV)
    if not names_value:
        pytest.fail(f"{POSTGRES_DATABASE_NAMES_ENV} must contain the exact JSON list.")
    try:
        names = json.loads(names_value)
    except json.JSONDecodeError as exc:
        pytest.fail(f"{POSTGRES_DATABASE_NAMES_ENV} is invalid JSON: {exc}")
    if names != list(EXPECTED_DATABASE_NAMES):
        pytest.fail(
            f"{POSTGRES_DATABASE_NAMES_ENV} must equal "
            f"{json.dumps(list(EXPECTED_DATABASE_NAMES))}."
        )
    if any(_SAFE_DATABASE_PATTERN.fullmatch(name) is None for name in names):
        pytest.fail("Disposable PostgreSQL database name is unsafe.")

    admin_url_value = os.getenv(POSTGRES_ADMIN_URL_ENV)
    if not admin_url_value:
        pytest.fail(f"{POSTGRES_ADMIN_URL_ENV} is required after PostgreSQL GO.")
    try:
        admin_url = make_url(admin_url_value)
    except Exception as exc:
        pytest.fail(f"{POSTGRES_ADMIN_URL_ENV} is not a valid URL: {exc}")
    if not (
        admin_url.drivername == "postgresql"
        or admin_url.drivername.startswith("postgresql+")
    ):
        pytest.fail("The rehearsal administrative URL must use PostgreSQL.")
    if (admin_url.host or "").lower() != EXPECTED_POSTGRES_HOST:
        pytest.fail(
            f"The rehearsal accepts only dedicated host {EXPECTED_POSTGRES_HOST!r}."
        )
    if admin_url.database != "postgres":
        pytest.fail("The administrative URL must name only the postgres database.")
    database_name = EXPECTED_DATABASE_NAMES[0]
    database_url = admin_url.set(database=database_name)
    database_url_value = database_url.render_as_string(hide_password=False)
    assert "active" not in database_url_value.lower()

    ledger_value = os.getenv(POSTGRES_EXECUTION_LEDGER_ENV)
    ledger_sha256 = os.getenv(POSTGRES_EXECUTION_LEDGER_SHA256_ENV)
    if not ledger_value or not ledger_sha256:
        pytest.fail(
            f"{POSTGRES_EXECUTION_LEDGER_ENV} and "
            f"{POSTGRES_EXECUTION_LEDGER_SHA256_ENV} are both required after GO."
        )
    ledger_path = Path(ledger_value).absolute()
    ledger = _load_execution_ledger(ledger_path, ledger_sha256)
    pins, _source_root_sha256 = _validate_execution_ledger(
        ledger,
        clone_database_url=database_url_value,
    )
    prepared = _prepare_runner(
        database_url=database_url_value,
        pins=pins,
        ledger=ledger,
    )

    admin_engine = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    database_engine = create_engine(
        database_url,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    plan = _PostgresRehearsalPlan(
        admin_engine=admin_engine,
        database_engine=database_engine,
        admin_url=admin_url,
        database_url=database_url,
        database_name=database_name,
        execution_ledger_path=ledger_path,
        execution_ledger=ledger,
        prepared=prepared,
    )
    cleanup_failures: list[str] = []
    connected = False
    try:
        with admin_engine.connect() as connection:
            connected = True
            can_manage = connection.execute(
                text(
                    "SELECT rolsuper OR rolcreatedb FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            ).scalar_one()
            assert can_manage, (
                f"{POSTGRES_ADMIN_URL_ENV} must identify a dedicated CREATEDB role."
            )
            observed = tuple(
                connection.execute(
                    text(
                        "SELECT datname FROM pg_database "
                        "WHERE datname LIKE :prefix ORDER BY datname"
                    ),
                    {"prefix": EXPECTED_DATABASE_PREFIX + "%"},
                ).scalars()
            )
            assert observed == EXPECTED_DATABASE_NAMES

        assert _revision(database_engine) == EXPECTED_ATLAS_REVISION
        _assert_no_other_database_sessions(database_engine)
        _assert_no_customer_data(database_engine)
        _assert_exact_inventory(database_engine, prepared.success.package)
        _assert_preloaded_page41_identity(database_engine, prepared.success.package)
        clone_contract = ledger["preloaded_post_0048_clone"]
        assert _database_fingerprint(database_engine) == clone_contract[
            "database_fingerprint_sha256"
        ]
        assert _canonical_sha256(_sequence_state(database_engine)) == clone_contract[
            "sequence_state_sha256"
        ]
        ledger["status"] = "PROVISIONED_TESTS_RUNNING"
        _write_execution_ledger(ledger_path, ledger)
        yield plan
    finally:
        tests_passed = (
            ledger.get("status") == "PASS_AWAITING_UNCONDITIONAL_CLEANUP"
        )
        database_engine.dispose(close=True)
        if connected:
            try:
                with admin_engine.connect() as connection:
                    connection.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = :name AND pid <> pg_backend_pid()"
                        ),
                        {"name": database_name},
                    )
                    connection.exec_driver_sql(
                        f'DROP DATABASE IF EXISTS "{database_name}"'
                    )
                    remaining = tuple(
                        connection.execute(
                            text(
                                "SELECT datname FROM pg_database "
                                "WHERE datname = :name"
                            ),
                            {"name": database_name},
                        ).scalars()
                    )
                if remaining:
                    cleanup_failures.append("database remains present")
            except Exception as exc:  # pragma: no cover - teardown diagnostics
                cleanup_failures.append(str(exc))
        else:
            cleanup_failures.append("administrative connection was never established")
        admin_engine.dispose(close=True)

        record = ledger["disposable_database_names"][0]
        record["removed"] = not cleanup_failures
        record["confirmed_absent"] = not cleanup_failures
        ledger["cleanup"] = {
            "sessions_terminated": not cleanup_failures,
            "database_removed": not cleanup_failures,
            "database_confirmed_absent": not cleanup_failures,
        }
        if cleanup_failures:
            ledger["status"] = "FAIL_CLEANUP"
        elif tests_passed:
            ledger["status"] = "PASS_CLEANED"
        else:
            ledger["status"] = "FAIL_TESTS_CLEANED"
        try:
            _write_execution_ledger(ledger_path, ledger)
        except Exception as exc:  # pragma: no cover - teardown diagnostics
            cleanup_failures.append(f"ledger update failed: {exc}")
        assert not cleanup_failures, (
            "PostgreSQL rehearsal cleanup failed: " + "; ".join(cleanup_failures)
        )


def test_postgres_rehearsal_contract_is_collection_safe_and_migration_free() -> None:
    assert EXPECTED_DATABASE_NAMES == ("atlas_pcopy_rehearsal_01",)
    assert all(
        name.startswith(EXPECTED_DATABASE_PREFIX) for name in EXPECTED_DATABASE_NAMES
    )
    assert SEQUENCE_RESTORE_ALLOWLIST == (
        "generatedpagerevision_id_seq",
        "pagecompositionrevision_id_seq",
        "generatedpageqaresult_id_seq",
    )
    assert EXPECTED_INJECTED_FAILURE_AFTER_QA == 33
    assert EXPECTED_ATLAS_REVISION == runner.ATLAS_REVISION
    assert EXPECTED_AFFECTED_PAGE_COUNT == runner.EXPECTED_AFFECTED_PAGE_COUNT
    assert all("active" not in name.lower() for name in EXPECTED_DATABASE_NAMES)
    expected_eligibility_sources = {
        "drafting_eligibility_assessments": "draftingeligibilityassessment",
        "drafting_eligibility_dispositions": "draftingeligibilitydisposition",
        "pre_draft_distinctness_briefs": "predraftdistinctnessbrief",
        "supporting_page_authorizations": "supportingpageauthorization",
        "website_city_coverage_decisions": "websitecitycoveragedecision",
        "website_county_coverage_decisions": "websitecountycoveragedecision",
        "website_service_city_coverage_decisions": (
            "websiteservicecitycoveragedecision"
        ),
        "website_service_county_coverage_decisions": (
            "websiteservicecountycoveragedecision"
        ),
        "website_service_coverage_decisions": "websiteservicecoveragedecision",
    }
    observed_locked_sources = {
        export_name: model.__table__.name
        for model, export_name in reconciliation_service._LOCKED_SOURCE_MODELS
    }
    assert expected_eligibility_sources.items() <= observed_locked_sources.items()
    assert set(expected_eligibility_sources.values()) <= set(PROTECTED_TABLES)
    assert set(expected_eligibility_sources.values()) <= {
        model.__table__.name
        for model in reconciliation_service._RECONCILIATION_TABLE_MODELS
    }
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (
            node.names
            if isinstance(node, ast.Import)
            else [ast.alias(name=node.module or "")]
        )
    }
    assert "alembic" not in imported_roots
    runner_source = (
        BACKEND / RUNNER_RELATIVE_PATH.removeprefix("backend/")
    ).read_text(encoding="utf-8")
    reconciliation_source = (
        BACKEND / "app" / "services" / "public_copy_reconciliation.py"
    ).read_text(encoding="utf-8")
    assert "setval(" not in runner_source
    assert "setval(" not in reconciliation_source


def test_real_postgresql_public_copy_rehearsal_matrix(
    public_copy_postgres_plan: _PostgresRehearsalPlan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = public_copy_postgres_plan
    engine = plan.database_engine
    package = plan.prepared.success.package

    assert _revision(engine) == EXPECTED_ATLAS_REVISION
    _assert_no_other_database_sessions(engine)
    _assert_no_customer_data(engine)
    _assert_exact_inventory(engine, package)
    baseline_page41 = _assert_preloaded_page41_identity(engine, package)
    baseline_database = _database_fingerprint(engine)
    baseline_sequences = _sequence_state(engine)
    baseline_history = _history_rows(engine)
    baseline_protected = _protected_fingerprints(engine)

    injected_report = runner.execute_prepared_invocation(
        plan.prepared.injected_failure
    )
    assert injected_report["outcome"] == "injected_failure_rolled_back"
    assert injected_report["transaction_outcome"] == "rolled_back"
    assert injected_report["injected_failure"] == {
        "type": "PublicCopyReconciliationInjectedFailure",
        "message": "Injected public-copy reconciliation failure after QA 33.",
        "after_qa": EXPECTED_INJECTED_FAILURE_AFTER_QA,
    }
    assert _database_fingerprint(engine) == baseline_database
    assert _history_rows(engine) == baseline_history
    assert _protected_fingerprints(engine) == baseline_protected
    after_rollback_sequences = _sequence_state(engine)
    _restore_allowlisted_clone_sequences(
        plan,
        baseline_sequences,
        after_rollback_sequences,
    )
    assert _database_fingerprint(engine) == baseline_database
    _append_report(
        plan,
        stage="qa33_injected_rollback",
        report=injected_report,
        evidence={
            "database_before_sha256": baseline_database,
            "database_after_rollback_sha256": _database_fingerprint(engine),
            "sequence_before_sha256": _canonical_sha256(baseline_sequences),
            "sequence_after_rollback_sha256": _canonical_sha256(
                after_rollback_sequences
            ),
            "sequence_after_clone_reset_sha256": _canonical_sha256(
                _sequence_state(engine)
            ),
            "changed_sequence_names": list(SEQUENCE_RESTORE_ALLOWLIST),
            "history_sha256": _canonical_sha256(baseline_history),
            "protected_sha256": _canonical_sha256(baseline_protected),
        },
    )

    success_report = runner.execute_prepared_invocation(plan.prepared.success)
    assert success_report["outcome"] == "applied"
    assert success_report["transaction_outcome"] == "committed"
    success_result = success_report["reconciliation_result"]
    assert success_result["affected_page_count"] == EXPECTED_AFFECTED_PAGE_COUNT
    assert len(success_result["page_results"]) == EXPECTED_AFFECTED_PAGE_COUNT
    assert success_result["appended_evidence_row_count"] == 65 * 3
    assert success_result["updated_head_row_count"] == 65 * 2
    assert success_result["superseded_qa_row_count"] == 65
    after_success_history = _history_rows(engine)
    _assert_preexisting_history_preserved(baseline_history, after_success_history)
    page41_successor = _assert_page41_successor(
        engine,
        report=success_report,
        baseline=baseline_page41,
    )
    assert _protected_fingerprints(engine) == baseline_protected
    _assert_no_customer_data(engine)
    _assert_exact_inventory(engine, package)
    after_success_sequences = _sequence_state(engine)
    after_success_database = _database_fingerprint(engine)
    _append_report(
        plan,
        stage="successful_apply",
        report=success_report,
        evidence={
            "database_after_sha256": after_success_database,
            "sequence_after_sha256": _canonical_sha256(after_success_sequences),
            "history_after_sha256": _canonical_sha256(after_success_history),
            "protected_sha256": _canonical_sha256(baseline_protected),
            "page41_successor_sha256": _canonical_sha256(page41_successor),
        },
    )

    repeated_report = runner.execute_prepared_invocation(plan.prepared.success)
    assert repeated_report["outcome"] == "already_applied"
    assert repeated_report["transaction_outcome"] == "write_free_noop"
    assert repeated_report["reconciliation_result"]["page_results"] == []
    assert repeated_report["reconciliation_result"][
        "appended_evidence_row_count"
    ] == 0
    assert repeated_report["reconciliation_result"]["updated_head_row_count"] == 0
    assert repeated_report["reconciliation_result"][
        "superseded_qa_row_count"
    ] == 0
    assert _database_fingerprint(engine) == after_success_database
    assert _sequence_state(engine) == after_success_sequences
    assert _history_rows(engine) == after_success_history
    assert _protected_fingerprints(engine) == baseline_protected
    assert _assert_page41_successor(
        engine,
        report=success_report,
        baseline=baseline_page41,
    ) == page41_successor
    _append_report(
        plan,
        stage="write_free_repeat",
        report=repeated_report,
        evidence={
            "database_sha256": _database_fingerprint(engine),
            "sequence_sha256": _canonical_sha256(_sequence_state(engine)),
            "history_sha256": _canonical_sha256(_history_rows(engine)),
            "protected_sha256": _canonical_sha256(baseline_protected),
        },
    )

    before_lock_database = _database_fingerprint(engine)
    before_lock_sequences = _sequence_state(engine)
    lock_sqlstates = _assert_two_session_governed_writer_rejected(
        plan,
        monkeypatch,
    )
    assert lock_sqlstates == {
        "eligibility_update": "55P03",
        "eligibility_zero_row_insert": "55P03",
        "governed_source_update": "55P03",
        "governed_source_zero_row_insert": "55P03",
    }
    assert _database_fingerprint(engine) == before_lock_database
    assert _sequence_state(engine) == before_lock_sequences
    assert _protected_fingerprints(engine) == baseline_protected
    _append_stage_evidence(
        plan,
        stage="two_session_governed_source_lock",
        outcome="update_and_insert_writers_blocked_and_rejected",
        evidence={
            "database_sha256": before_lock_database,
            "sequence_sha256": _canonical_sha256(before_lock_sequences),
            "protected_sha256": _canonical_sha256(baseline_protected),
            "update_writer_sqlstate": "55P03",
            "insert_writer_sqlstate": "55P03",
            "eligibility_update_writer_sqlstate": "55P03",
            "eligibility_insert_writer_sqlstate": "55P03",
        },
    )

    expected_composition_history = _capture_table_rows(
        engine, "pagecompositionrevision"
    )
    _assert_history_triggers_reject_mutation(
        engine,
        page41_revision_id=int(
            page41_successor["new_composition_revision"]["id"]
        ),
        expected_history=expected_composition_history,
    )
    assert _protected_fingerprints(engine) == baseline_protected
    tampered_composition_id = _tamper_current_destination_binding(engine)
    assert tampered_composition_id > 0
    with Session(engine) as session:
        with pytest.raises(
            PublicCopyReconciliationError,
            match="composition|history|diverge|source",
        ):
            reconcile_public_copy(
                session,
                package,
                actor=EXPECTED_ACTOR,
                commit=True,
            )
    assert _capture_table_rows(engine, "pagecompositionrevision") == (
        expected_composition_history
    )
    assert _history_rows(engine) == after_success_history
    assert _protected_fingerprints(engine) == baseline_protected
    assert _sequence_state(engine) == after_success_sequences
    _assert_no_customer_data(engine)
    _append_stage_evidence(
        plan,
        stage="immutable_history_and_destination_binding_tamper",
        outcome="all_tamper_rejected",
        evidence={
            "tampered_composition_id": tampered_composition_id,
            "immutable_history_sha256": _canonical_sha256(
                expected_composition_history
            ),
            "full_history_sha256": _canonical_sha256(after_success_history),
            "protected_sha256": _canonical_sha256(baseline_protected),
            "sequence_sha256": _canonical_sha256(after_success_sequences),
        },
    )
    plan.execution_ledger["status"] = "PASS_AWAITING_UNCONDITIONAL_CLEANUP"
    _write_execution_ledger(plan.execution_ledger_path, plan.execution_ledger)
