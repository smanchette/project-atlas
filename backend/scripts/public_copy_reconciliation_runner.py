from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable


# Running this file directly places backend/scripts on sys.path. Import Atlas only
# from the adjacent, explicit backend source root; database/configuration discovery
# remains prohibited below.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy.engine import make_url
from sqlmodel import Session, create_engine

from app.services.public_copy_manifest import (
    PublicCopyManifestPackage,
    load_public_copy_manifest_package,
)
from app.services.public_copy_reconciliation import (
    PublicCopyReconciliationInjectedFailure,
    reconcile_public_copy,
)


INVOCATION_CONFIG_SCHEMA = (
    "project-atlas-public-copy-reconciliation-invocation@1"
)
RUNNER_REPORT_SCHEMA = "project-atlas-public-copy-reconciliation-report@1"
RUNNER_ERROR_REPORT_SCHEMA = (
    "project-atlas-public-copy-reconciliation-runner-error@1"
)
RUNNER_OPERATION = "public_copy_reconciliation_only"
ATLAS_REVISION = "20260820_0048"
EXPECTED_AFFECTED_PAGE_COUNT = 65
REHEARSAL_EVIDENCE_SCHEMA = (
    "atlas-public-copy-reconciliation-postgresql-execution-ledger@1"
)
REHEARSAL_EVIDENCE_OPERATION = (
    "public_copy_reconciliation_postgresql_rehearsal_only"
)
REHEARSAL_EVIDENCE_STATUS = "PASS_CLEANED"
POSTGRES_REHEARSAL_HARNESS_PATH = (
    "backend/tests/test_public_copy_reconciliation_postgres.py"
)
POSTGRES_REHEARSAL_CONFTEST_PATH = "backend/tests/conftest.py"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

TARGET_ROLE_DISPOSABLE_CLONE = "disposable_clone"
TARGET_ROLE_ACTIVE_LOCAL = "active_local"
MODE_REHEARSAL_SUCCESS = "rehearsal_success"
MODE_REHEARSAL_INJECTED_FAILURE = "rehearsal_injected_failure"
MODE_ACTIVE_APPLY = "active_apply"

_EXPECTED_ROLE_MODE_PAIRS = frozenset(
    {
        (TARGET_ROLE_DISPOSABLE_CLONE, MODE_REHEARSAL_SUCCESS),
        (TARGET_ROLE_DISPOSABLE_CLONE, MODE_REHEARSAL_INJECTED_FAILURE),
        (TARGET_ROLE_ACTIVE_LOCAL, MODE_ACTIVE_APPLY),
    }
)

_RESULT_KEYS = {
    "status",
    "manifest_file_sha256",
    "ruleset_payload_sha256",
    "website_id",
    "site_plan_id",
    "affected_page_count",
    "page_results",
    "appended_evidence_row_count",
    "updated_head_row_count",
    "superseded_qa_row_count",
    "public_copy_audit_fingerprint",
    "public_copy_warning_count",
    "public_copy_informational_count",
}
_PAGE_RESULT_KEYS = {
    "planned_page_id",
    "generated_page_id",
    "old_generated_page_revision_id",
    "new_generated_page_revision_id",
    "old_content_hash",
    "new_content_hash",
    "composition_id",
    "old_composition_version",
    "new_composition_version",
    "old_composition_source_hash",
    "new_composition_source_hash",
    "old_qa_result_id",
    "new_qa_result_id",
    "new_qa_result_hash",
}

# The runner has no imports, callbacks, or CLI options for these capabilities.
# Requiring this exact false-valued object in the SHA-pinned invocation file also
# makes the prohibition explicit evidence rather than an implicit convention.
FORBIDDEN_ACTIONS = {
    "apply_migration": False,
    "alter_media": False,
    "browser_control": False,
    "customer_data_collection": False,
    "deploy": False,
    "email_send": False,
    "export": False,
    "form_mode_seed_or_enable": False,
    "git_push": False,
    "git_tag": False,
    "media_assignment_change": False,
    "page_41_media_change": False,
    "performance_local_v5_layout_or_styling_change": False,
    "performance_local_v5_registration_or_activation": False,
    "performance_local_v6_creation": False,
    "publish": False,
    "wordpress_or_siteground_access": False,
}


class PublicCopyRunnerError(ValueError):
    pass


class PublicCopyRunnerExecutionError(PublicCopyRunnerError):
    pass


@dataclass(frozen=True)
class RunnerArguments:
    database_url: str
    source_root: Path
    manifest_path: Path
    manifest_sha256: str
    ruleset_path: Path
    ruleset_sha256: str
    invocation_config_path: Path
    invocation_config_sha256: str
    target_role: str
    mode: str
    actor: str
    commit: bool
    rehearsal_evidence_path: Path | None = None
    rehearsal_evidence_sha256: str | None = None


@dataclass(frozen=True)
class PreparedInvocation:
    arguments: RunnerArguments
    config: dict[str, Any]
    invocation: dict[str, Any]
    package: PublicCopyManifestPackage
    runner_sha256: str
    source_root_sha256: str
    database_url_sha256: str
    postgres_rehearsal_harness_sha256: str
    postgres_rehearsal_conftest_sha256: str
    rehearsal_evidence_sha256: str | None


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PublicCopyRunnerError(
            "Runner evidence is not strict canonical JSON."
        ) from exc


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


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
    return bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def runner_file_sha256() -> str:
    path = Path(__file__)
    if _is_link_or_reparse(path.absolute()):
        raise PublicCopyRunnerError("The reconciliation runner must not be a symlink.")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PublicCopyRunnerError(
            "The reconciliation runner source file is unavailable."
        ) from exc
    if not resolved.is_file() or _is_link_or_reparse(resolved):
        raise PublicCopyRunnerError(
            "The reconciliation runner source must be a regular file."
        )
    return hashlib.sha256(resolved.read_bytes()).hexdigest()


def _required_sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise PublicCopyRunnerError(f"{field} must be a lowercase SHA-256 value.")
    return value


def _required_text(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise PublicCopyRunnerError(f"{field} must be exact nonempty text.")
    return value


def _strict_json(payload: bytes, *, label: str) -> dict[str, Any]:
    if payload.startswith(b"\xef\xbb\xbf"):
        raise PublicCopyRunnerError(f"{label} must not contain a UTF-8 BOM.")
    if b"\x00" in payload:
        raise PublicCopyRunnerError(f"{label} must not contain NUL bytes.")

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PublicCopyRunnerError(
                    f"{label} contains a duplicate JSON key: {key}."
                )
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise PublicCopyRunnerError(
            f"{label} contains a non-finite JSON number: {value}."
        )

    try:
        decoded = payload.decode("utf-8", errors="strict")
        value = json.loads(
            decoded,
            object_pairs_hook=object_pairs,
            parse_constant=invalid_constant,
        )
    except PublicCopyRunnerError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicCopyRunnerError(f"{label} is not strict UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise PublicCopyRunnerError(f"{label} must be a JSON object.")
    return value


def _load_sha_pinned_json(
    path: Path,
    expected_sha256: str,
    *,
    label: str,
) -> dict[str, Any]:
    expected = _required_sha256(expected_sha256, field=f"{label} SHA-256")
    current = path.absolute()
    while True:
        if current.exists() and _is_link_or_reparse(current):
            raise PublicCopyRunnerError(
                f"{label} path may not contain a symlink or reparse point."
            )
        parent = current.parent
        if parent == current:
            break
        current = parent
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PublicCopyRunnerError(f"{label} does not exist: {path}.") from exc
    if not resolved.is_file() or _is_link_or_reparse(resolved):
        raise PublicCopyRunnerError(
            f"{label} must be a regular non-symlink file."
        )
    payload = resolved.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected:
        raise PublicCopyRunnerError(
            f"{label} SHA-256 does not match the explicit caller pin."
        )
    return _strict_json(payload, label=label)


def _require_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    *,
    field: str,
) -> None:
    if set(value) != expected:
        raise PublicCopyRunnerError(f"{field} has an unknown or incomplete contract.")


def _validate_source_root(source_root: Path) -> tuple[Path, str]:
    if _is_link_or_reparse(source_root.absolute()):
        raise PublicCopyRunnerError(
            "The explicit source root must not be a symlink or reparse point."
        )
    try:
        resolved = source_root.resolve(strict=True)
    except OSError as exc:
        raise PublicCopyRunnerError("The explicit source root does not exist.") from exc
    if not resolved.is_dir() or _is_link_or_reparse(resolved):
        raise PublicCopyRunnerError("The explicit source root must be a directory.")
    normalized = str(resolved).replace("\\", "/")
    return resolved, hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _source_file_sha256(source_root: Path, relative_path: str) -> str:
    parts = relative_path.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise PublicCopyRunnerError("Pinned source-file path is unsafe.")
    current = source_root
    for part in parts:
        current = current / part
        if _is_link_or_reparse(current):
            raise PublicCopyRunnerError(
                "Pinned source-file path may not contain a symlink or reparse point."
            )
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(source_root)
    except (OSError, ValueError) as exc:
        raise PublicCopyRunnerError(
            "Pinned source file is missing or escapes the source root."
        ) from exc
    if not resolved.is_file():
        raise PublicCopyRunnerError("Pinned source file is not a regular file.")
    return hashlib.sha256(resolved.read_bytes()).hexdigest()


def _database_url_sha256(database_url: str) -> str:
    exact = _required_text(database_url, field="database_url")
    try:
        parsed = make_url(exact)
    except Exception as exc:
        raise PublicCopyRunnerError(
            "database_url is not a valid SQLAlchemy URL."
        ) from exc
    if not (
        parsed.drivername == "postgresql"
        or parsed.drivername.startswith("postgresql+")
    ):
        raise PublicCopyRunnerError(
            "Public-copy reconciliation requires an explicit PostgreSQL URL."
        )
    if not parsed.database:
        raise PublicCopyRunnerError(
            "The explicit PostgreSQL URL must name one exact database."
        )
    return hashlib.sha256(exact.encode("utf-8")).hexdigest()


def validate_invocation_config(config: dict[str, Any]) -> None:
    _require_exact_keys(
        config,
        {
            "schema",
            "operation",
            "atlas_revision",
            "expected_affected_page_count",
            "actor",
            "commit_required",
            "manifest_sha256",
            "ruleset_sha256",
            "runner_sha256",
            "source_root_sha256",
            "postgres_rehearsal_harness_sha256",
            "postgres_rehearsal_conftest_sha256",
            "forbidden_actions",
            "active_apply_prerequisite",
            "invocations",
            "customer_data",
            "external_requests",
        },
        field="Invocation config",
    )
    if (
        config.get("schema") != INVOCATION_CONFIG_SCHEMA
        or config.get("operation") != RUNNER_OPERATION
        or config.get("atlas_revision") != ATLAS_REVISION
        or config.get("expected_affected_page_count")
        != EXPECTED_AFFECTED_PAGE_COUNT
        or config.get("commit_required") is not True
        or config.get("customer_data") is not False
        or config.get("external_requests") is not False
    ):
        raise PublicCopyRunnerError(
            "Invocation config identity or safety scope is invalid."
        )
    _required_text(config.get("actor"), field="Invocation config actor")
    _required_sha256(
        config.get("manifest_sha256"), field="Invocation config manifest_sha256"
    )
    _required_sha256(
        config.get("ruleset_sha256"), field="Invocation config ruleset_sha256"
    )
    _required_sha256(
        config.get("runner_sha256"), field="Invocation config runner_sha256"
    )
    _required_sha256(
        config.get("source_root_sha256"),
        field="Invocation config source_root_sha256",
    )
    _required_sha256(
        config.get("postgres_rehearsal_harness_sha256"),
        field="Invocation config postgres_rehearsal_harness_sha256",
    )
    _required_sha256(
        config.get("postgres_rehearsal_conftest_sha256"),
        field="Invocation config postgres_rehearsal_conftest_sha256",
    )
    if config.get("forbidden_actions") != FORBIDDEN_ACTIONS:
        raise PublicCopyRunnerError(
            "Invocation config must explicitly disable every forbidden action."
        )
    if config.get("active_apply_prerequisite") != {
        "required": True,
        "schema": REHEARSAL_EVIDENCE_SCHEMA,
        "operation": REHEARSAL_EVIDENCE_OPERATION,
        "status": REHEARSAL_EVIDENCE_STATUS,
    }:
        raise PublicCopyRunnerError(
            "Invocation config does not require the exact cleaned rehearsal evidence."
        )

    invocations = config.get("invocations")
    if not isinstance(invocations, list) or len(invocations) != 3:
        raise PublicCopyRunnerError(
            "Invocation config must define exactly clone success, clone failure, "
            "and active apply."
        )
    seen: set[tuple[str, str]] = set()
    clone_database_hashes: set[str] = set()
    active_database_hash: str | None = None
    for index, raw in enumerate(invocations):
        if not isinstance(raw, dict):
            raise PublicCopyRunnerError(
                f"Invocation config entry {index} must be an object."
            )
        _require_exact_keys(
            raw,
            {
                "target_role",
                "mode",
                "database_url_sha256",
                "commit",
                "inject_failure_after_qa",
            },
            field=f"Invocation config entry {index}",
        )
        role = raw.get("target_role")
        mode = raw.get("mode")
        pair = (role, mode)
        if pair not in _EXPECTED_ROLE_MODE_PAIRS or pair in seen:
            raise PublicCopyRunnerError(
                "Invocation config has a duplicate or forbidden target-role/mode pair."
            )
        seen.add(pair)
        database_hash = _required_sha256(
            raw.get("database_url_sha256"),
            field=f"Invocation config entry {index} database_url_sha256",
        )
        if raw.get("commit") is not True:
            raise PublicCopyRunnerError(
                "Every configured reconciliation invocation must commit its "
                "governed outcome."
            )
        injection = raw.get("inject_failure_after_qa")
        if mode == MODE_REHEARSAL_INJECTED_FAILURE:
            if (
                isinstance(injection, bool)
                or not isinstance(injection, int)
                or injection <= 0
                or injection >= EXPECTED_AFFECTED_PAGE_COUNT
            ):
                raise PublicCopyRunnerError(
                    "Clone failure injection must occur strictly inside the "
                    "65-page QA batch."
                )
        elif injection is not None:
            raise PublicCopyRunnerError(
                "Failure injection is allowed only in explicit clone rehearsal mode."
            )
        if role == TARGET_ROLE_DISPOSABLE_CLONE:
            clone_database_hashes.add(database_hash)
        else:
            active_database_hash = database_hash
    if seen != _EXPECTED_ROLE_MODE_PAIRS:
        raise PublicCopyRunnerError(
            "Invocation config does not contain the exact required role/mode contract."
        )
    if (
        len(clone_database_hashes) != 1
        or active_database_hash is None
        or active_database_hash in clone_database_hashes
    ):
        raise PublicCopyRunnerError(
            "Clone modes must share one database URL distinct from active local Atlas."
        )


def _select_invocation(
    config: dict[str, Any],
    *,
    target_role: str,
    mode: str,
) -> dict[str, Any]:
    matches = [
        item
        for item in config["invocations"]
        if item["target_role"] == target_role and item["mode"] == mode
    ]
    if len(matches) != 1:
        raise PublicCopyRunnerError(
            "Requested target role/mode is not authorized by the sealed "
            "invocation config."
        )
    return matches[0]


def _validate_rehearsal_evidence(
    evidence: dict[str, Any],
    *,
    config: dict[str, Any],
    config_sha256: str,
    manifest_sha256: str,
    ruleset_sha256: str,
    runner_sha256: str,
    source_root_sha256: str,
    postgres_rehearsal_harness_sha256: str,
    postgres_rehearsal_conftest_sha256: str,
    actor: str,
) -> None:
    _require_exact_keys(
        evidence,
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
        field="Rehearsal evidence",
    )
    if (
        evidence.get("schema") != REHEARSAL_EVIDENCE_SCHEMA
        or evidence.get("operation") != REHEARSAL_EVIDENCE_OPERATION
        or evidence.get("status") != REHEARSAL_EVIDENCE_STATUS
        or evidence.get("atlas_revision") != ATLAS_REVISION
        or evidence.get("source_freeze_go_received") is not True
        or evidence.get("postgresql_go_received") is not True
        or evidence.get("no_migration") is not True
        or evidence.get("customer_data") is not False
        or evidence.get("external_requests") is not False
        or evidence.get("database_prefix") != "atlas_pcopy_rehearsal_"
    ):
        raise PublicCopyRunnerError(
            "Active apply requires exact PASS_CLEANED PostgreSQL rehearsal evidence."
        )
    if evidence.get("cleanup") != {
        "sessions_terminated": True,
        "database_removed": True,
        "database_confirmed_absent": True,
    }:
        raise PublicCopyRunnerError(
            "PostgreSQL rehearsal evidence is not unconditionally cleaned."
        )
    database_records = evidence.get("disposable_database_names")
    if database_records != [
        {
            "ordinal": 1,
            "name": "atlas_pcopy_rehearsal_01",
            "recorded_before_creation": True,
            "created": True,
            "removed": True,
            "confirmed_absent": True,
        }
    ]:
        raise PublicCopyRunnerError(
            "PostgreSQL rehearsal database lifecycle evidence is incomplete."
        )
    if evidence.get("sequence_restore_allowlist") != [
        "generatedpagerevision_id_seq",
        "pagecompositionrevision_id_seq",
        "generatedpageqaresult_id_seq",
    ]:
        raise PublicCopyRunnerError(
            "PostgreSQL rehearsal sequence-restoration evidence is invalid."
        )

    pins = evidence.get("source_pins")
    if not isinstance(pins, dict):
        raise PublicCopyRunnerError("PostgreSQL rehearsal source pins are missing.")
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
        field="Rehearsal evidence source_pins",
    )
    expected_pin_hashes = {
        "source_root": source_root_sha256,
        "manifest": manifest_sha256,
        "ruleset": ruleset_sha256,
        "runner": runner_sha256,
        "invocation_config": config_sha256,
        "postgres_rehearsal_harness": postgres_rehearsal_harness_sha256,
        "postgres_rehearsal_conftest": postgres_rehearsal_conftest_sha256,
    }
    for name, expected_sha256 in expected_pin_hashes.items():
        contract = pins.get(name)
        if not isinstance(contract, dict):
            raise PublicCopyRunnerError(
                f"PostgreSQL rehearsal source pin {name} is missing."
            )
        _require_exact_keys(
            contract,
            {"path", "sha256"},
            field=f"Rehearsal evidence source_pins.{name}",
        )
        _required_text(
            contract.get("path"),
            field=f"Rehearsal evidence source_pins.{name}.path",
        )
        if _required_sha256(
            contract.get("sha256"),
            field=f"Rehearsal evidence source_pins.{name}.sha256",
        ) != expected_sha256:
            raise PublicCopyRunnerError(
                f"PostgreSQL rehearsal source pin {name} differs from active apply."
            )
    if pins["source_root"]["path"] != ".":
        raise PublicCopyRunnerError(
            "PostgreSQL rehearsal source-root path contract is invalid."
        )
    if (
        pins["postgres_rehearsal_harness"]["path"]
        != POSTGRES_REHEARSAL_HARNESS_PATH
    ):
        raise PublicCopyRunnerError(
            "PostgreSQL rehearsal harness path contract is invalid."
        )
    if (
        pins["postgres_rehearsal_conftest"]["path"]
        != POSTGRES_REHEARSAL_CONFTEST_PATH
    ):
        raise PublicCopyRunnerError(
            "PostgreSQL rehearsal conftest path contract is invalid."
        )

    clone_hashes = {
        item["database_url_sha256"]
        for item in config["invocations"]
        if item["target_role"] == TARGET_ROLE_DISPOSABLE_CLONE
    }
    clone_hash = next(iter(clone_hashes))
    runner_contract = evidence.get("runner_contract")
    expected_runner_contract = {
        "actor": actor,
        "target_role": TARGET_ROLE_DISPOSABLE_CLONE,
        "success_mode": MODE_REHEARSAL_SUCCESS,
        "failure_mode": MODE_REHEARSAL_INJECTED_FAILURE,
        "inject_failure_after_qa": 33,
        "commit": True,
        "clone_database_url_sha256": clone_hash,
        "expected_affected_page_count": EXPECTED_AFFECTED_PAGE_COUNT,
    }
    if runner_contract != expected_runner_contract:
        raise PublicCopyRunnerError(
            "PostgreSQL rehearsal runner contract differs from active apply."
        )

    clone = evidence.get("preloaded_post_0048_clone")
    if not isinstance(clone, dict):
        raise PublicCopyRunnerError("PostgreSQL rehearsal clone evidence is missing.")
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
        field="Rehearsal evidence preloaded_post_0048_clone",
    )
    dump = clone.get("dump")
    if not isinstance(dump, dict):
        raise PublicCopyRunnerError("PostgreSQL rehearsal dump evidence is missing.")
    _require_exact_keys(dump, {"path", "sha256"}, field="Rehearsal evidence dump")
    _required_text(dump.get("path"), field="Rehearsal evidence dump.path")
    _required_sha256(dump.get("sha256"), field="Rehearsal evidence dump.sha256")
    if (
        clone.get("database_name") != "atlas_pcopy_rehearsal_01"
        or clone.get("restored_before_tests") is not True
        or clone.get("migration_applied_by_test") is not False
        or clone.get("atlas_revision") != ATLAS_REVISION
    ):
        raise PublicCopyRunnerError(
            "PostgreSQL rehearsal clone was not the exact preloaded 0048 boundary."
        )
    _required_sha256(
        clone.get("database_fingerprint_sha256"),
        field="Rehearsal evidence clone database fingerprint",
    )
    _required_sha256(
        clone.get("sequence_state_sha256"),
        field="Rehearsal evidence clone sequence fingerprint",
    )

    reports = evidence.get("reports")
    expected_reports = (
        ("qa33_injected_rollback", "injected_failure_rolled_back", "rolled_back"),
        ("successful_apply", "applied", "committed"),
        ("write_free_repeat", "already_applied", "write_free_noop"),
        (
            "two_session_governed_source_lock",
            "update_and_insert_writers_blocked_and_rejected",
            None,
        ),
        (
            "immutable_history_and_destination_binding_tamper",
            "all_tamper_rejected",
            None,
        ),
    )
    if not isinstance(reports, list) or len(reports) != len(expected_reports):
        raise PublicCopyRunnerError(
            "PostgreSQL rehearsal reports are incomplete or duplicated."
        )
    for index, (report, expected) in enumerate(zip(reports, expected_reports)):
        if not isinstance(report, dict):
            raise PublicCopyRunnerError(
                f"PostgreSQL rehearsal report {index} is invalid."
            )
        stage, outcome, transaction_outcome = expected
        expected_keys = {"stage", "outcome", "evidence_sha256"}
        if transaction_outcome is not None:
            expected_keys |= {"transaction_outcome", "report_sha256"}
        _require_exact_keys(
            report,
            expected_keys,
            field=f"Rehearsal evidence reports[{index}]",
        )
        if (
            report.get("stage") != stage
            or report.get("outcome") != outcome
            or (
                transaction_outcome is not None
                and report.get("transaction_outcome") != transaction_outcome
            )
        ):
            raise PublicCopyRunnerError(
                "PostgreSQL rehearsal report stages or outcomes differ from the required matrix."
            )
        _required_sha256(
            report.get("evidence_sha256"),
            field=f"Rehearsal evidence reports[{index}].evidence_sha256",
        )
        if transaction_outcome is not None:
            _required_sha256(
                report.get("report_sha256"),
                field=f"Rehearsal evidence reports[{index}].report_sha256",
            )


def prepare_invocation(
    arguments: RunnerArguments,
    *,
    manifest_loader: Callable[..., PublicCopyManifestPackage] = (
        load_public_copy_manifest_package
    ),
) -> PreparedInvocation:
    manifest_sha = _required_sha256(
        arguments.manifest_sha256, field="manifest_sha256"
    )
    ruleset_sha = _required_sha256(
        arguments.ruleset_sha256, field="ruleset_sha256"
    )
    config_sha = _required_sha256(
        arguments.invocation_config_sha256,
        field="invocation_config_sha256",
    )
    source_root, source_root_sha = _validate_source_root(arguments.source_root)
    harness_sha = _source_file_sha256(
        source_root,
        POSTGRES_REHEARSAL_HARNESS_PATH,
    )
    conftest_sha = _source_file_sha256(
        source_root,
        POSTGRES_REHEARSAL_CONFTEST_PATH,
    )
    database_sha = _database_url_sha256(arguments.database_url)
    manifest_document = _load_sha_pinned_json(
        arguments.manifest_path,
        manifest_sha,
        label="Correction manifest",
    )
    ruleset_document = _load_sha_pinned_json(
        arguments.ruleset_path,
        ruleset_sha,
        label="Public-copy ruleset",
    )
    config = _load_sha_pinned_json(
        arguments.invocation_config_path,
        config_sha,
        label="Invocation config",
    )
    validate_invocation_config(config)

    exact_actor = _required_text(arguments.actor, field="actor")
    if exact_actor != config["actor"]:
        raise PublicCopyRunnerError(
            "CLI actor does not match the sealed invocation config."
        )
    if arguments.commit is not True or config["commit_required"] is not True:
        raise PublicCopyRunnerError(
            "Public-copy reconciliation requires explicit commit=true."
        )
    if manifest_sha != config["manifest_sha256"]:
        raise PublicCopyRunnerError(
            "CLI manifest SHA-256 does not match the sealed invocation config."
        )
    if ruleset_sha != config["ruleset_sha256"]:
        raise PublicCopyRunnerError(
            "CLI ruleset SHA-256 does not match the sealed invocation config."
        )
    observed_runner_sha = runner_file_sha256()
    if observed_runner_sha != config["runner_sha256"]:
        raise PublicCopyRunnerError(
            "Runner bytes do not match the sealed invocation config."
        )
    if source_root_sha != config["source_root_sha256"]:
        raise PublicCopyRunnerError(
            "Explicit source root does not match the sealed invocation config."
        )
    if harness_sha != config["postgres_rehearsal_harness_sha256"]:
        raise PublicCopyRunnerError(
            "PostgreSQL rehearsal harness bytes differ from the sealed invocation config."
        )
    if conftest_sha != config["postgres_rehearsal_conftest_sha256"]:
        raise PublicCopyRunnerError(
            "PostgreSQL rehearsal conftest bytes differ from the sealed invocation config."
        )

    invocation = _select_invocation(
        config,
        target_role=arguments.target_role,
        mode=arguments.mode,
    )
    if invocation["database_url_sha256"] != database_sha:
        raise PublicCopyRunnerError(
            "Explicit database URL does not match the selected sealed target."
        )
    if invocation["commit"] is not arguments.commit:
        raise PublicCopyRunnerError(
            "CLI commit behavior does not match the selected sealed target."
        )

    evidence_path = arguments.rehearsal_evidence_path
    evidence_sha256 = arguments.rehearsal_evidence_sha256
    if (evidence_path is None) != (evidence_sha256 is None):
        raise PublicCopyRunnerError(
            "Rehearsal evidence path and SHA-256 must be supplied together."
        )
    if arguments.target_role == TARGET_ROLE_DISPOSABLE_CLONE:
        if evidence_path is not None:
            raise PublicCopyRunnerError(
                "Disposable-clone modes must not accept active prerequisite evidence."
            )
        observed_evidence_sha256 = None
    else:
        if evidence_path is None or evidence_sha256 is None:
            raise PublicCopyRunnerError(
                "Active apply requires caller-SHA-pinned PASS_CLEANED rehearsal evidence."
            )
        observed_evidence_sha256 = _required_sha256(
            evidence_sha256,
            field="rehearsal_evidence_sha256",
        )
        rehearsal_evidence = _load_sha_pinned_json(
            evidence_path,
            observed_evidence_sha256,
            label="PostgreSQL rehearsal evidence",
        )
        _validate_rehearsal_evidence(
            rehearsal_evidence,
            config=config,
            config_sha256=config_sha,
            manifest_sha256=manifest_sha,
            ruleset_sha256=ruleset_sha,
            runner_sha256=observed_runner_sha,
            source_root_sha256=source_root_sha,
            postgres_rehearsal_harness_sha256=harness_sha,
            postgres_rehearsal_conftest_sha256=conftest_sha,
            actor=exact_actor,
        )

    package = manifest_loader(
        arguments.manifest_path,
        manifest_sha256=manifest_sha,
        ruleset_path=arguments.ruleset_path,
        ruleset_sha256=ruleset_sha,
        source_root=source_root,
    )
    if (
        package.manifest_file_sha256 != manifest_sha
        or package.ruleset_file_sha256 != ruleset_sha
        or package.manifest != manifest_document
        or package.ruleset != ruleset_document
    ):
        raise PublicCopyRunnerError(
            "Loaded manifest package differs from the runner's exact pinned bytes."
        )
    scope = package.manifest.get("scope")
    page_bindings = package.manifest.get("page_bindings")
    if (
        not isinstance(scope, dict)
        or scope.get("affected_page_count")
        != EXPECTED_AFFECTED_PAGE_COUNT
        or not isinstance(page_bindings, list)
        or len(page_bindings) != EXPECTED_AFFECTED_PAGE_COUNT
    ):
        raise PublicCopyRunnerError(
            "The sealed manifest is not the exact 65-page reconciliation scope."
        )
    return PreparedInvocation(
        arguments=arguments,
        config=config,
        invocation=invocation,
        package=package,
        runner_sha256=observed_runner_sha,
        source_root_sha256=source_root_sha,
        database_url_sha256=database_sha,
        postgres_rehearsal_harness_sha256=harness_sha,
        postgres_rehearsal_conftest_sha256=conftest_sha,
        rehearsal_evidence_sha256=observed_evidence_sha256,
    )


def _strict_result_payload(
    result: Any,
    *,
    prepared: PreparedInvocation,
) -> dict[str, Any]:
    if is_dataclass(result):
        raw = asdict(result)
    elif hasattr(result, "model_dump"):
        raw = result.model_dump(mode="json")
    elif isinstance(result, dict):
        raw = dict(result)
    else:
        raise PublicCopyRunnerExecutionError(
            "Reconciliation returned an unsupported result contract."
        )
    if not isinstance(raw, dict):
        raise PublicCopyRunnerExecutionError(
            "Reconciliation result must serialize as an object."
        )
    # Canonical round-trip rejects non-finite values and normalizes tuples.
    payload = json.loads(canonical_json_bytes(raw).decode("utf-8"))
    _require_exact_keys(payload, _RESULT_KEYS, field="Reconciliation result")
    status = payload.get("status")
    page_results = payload.get("page_results")
    manifest = prepared.package.manifest
    scope = manifest["scope"]
    bindings = manifest["page_bindings"]
    if (
        status not in {"applied", "already_applied"}
        or payload.get("manifest_file_sha256")
        != prepared.arguments.manifest_sha256
        or payload.get("ruleset_payload_sha256")
        != prepared.package.ruleset_payload_sha256
        or payload.get("website_id") != scope["website_id"]
        or payload.get("site_plan_id") != scope["site_plan_id"]
        or payload.get("affected_page_count")
        != EXPECTED_AFFECTED_PAGE_COUNT
        or not isinstance(page_results, list)
    ):
        raise PublicCopyRunnerExecutionError(
            "Reconciliation result does not prove the exact sealed 65-page outcome."
        )
    _required_sha256(
        payload.get("public_copy_audit_fingerprint"),
        field="Reconciliation result public_copy_audit_fingerprint",
    )
    for field in (
        "public_copy_warning_count",
        "public_copy_informational_count",
    ):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PublicCopyRunnerExecutionError(
                f"Reconciliation result {field} is invalid."
            )
    expected_counts = (
        {
            "appended_evidence_row_count": EXPECTED_AFFECTED_PAGE_COUNT * 3,
            "updated_head_row_count": EXPECTED_AFFECTED_PAGE_COUNT * 2,
            "superseded_qa_row_count": EXPECTED_AFFECTED_PAGE_COUNT,
        }
        if status == "applied"
        else {
            "appended_evidence_row_count": 0,
            "updated_head_row_count": 0,
            "superseded_qa_row_count": 0,
        }
    )
    if any(payload.get(field) != value for field, value in expected_counts.items()):
        raise PublicCopyRunnerExecutionError(
            "Reconciliation result evidence-row/head counts are not exact."
        )
    if status == "already_applied":
        if page_results:
            raise PublicCopyRunnerExecutionError(
                "Write-free reconciliation replay returned page mutations."
            )
        return payload
    if len(page_results) != EXPECTED_AFFECTED_PAGE_COUNT:
        raise PublicCopyRunnerExecutionError(
            "Applied reconciliation did not return exactly 65 Page results."
        )

    history = manifest["immutable_history_snapshot"]
    minimum_revision_id = history["generated_page_revisions"]["maximum_id"]
    minimum_qa_id = history["generated_page_qa_results"]["maximum_id"]
    new_revision_ids: set[int] = set()
    new_qa_ids: set[int] = set()
    for index, (page_result, binding) in enumerate(zip(page_results, bindings)):
        if not isinstance(page_result, dict):
            raise PublicCopyRunnerExecutionError(
                f"Reconciliation Page result {index} is not an object."
            )
        _require_exact_keys(
            page_result,
            _PAGE_RESULT_KEYS,
            field=f"Reconciliation Page result {index}",
        )
        exact = {
            "planned_page_id": binding["planned_page_id"],
            "generated_page_id": binding["generated_page_id"],
            "old_generated_page_revision_id": binding["current_revision"][
                "latest_page_revision_id"
            ],
            "old_content_hash": binding["current_revision"]["content_hash"],
            "new_content_hash": binding["expected_new_content_hash"],
            "composition_id": binding["current_composition"]["id"],
            "old_composition_version": binding["current_composition"]["version"],
            "new_composition_version": binding["current_composition"]["version"] + 1,
            "old_composition_source_hash": binding["current_composition"][
                "source_hash"
            ],
            "old_qa_result_id": binding["current_qa"]["id"],
        }
        if any(page_result.get(field) != value for field, value in exact.items()):
            raise PublicCopyRunnerExecutionError(
                f"Reconciliation Page result {index} contradicts its sealed binding."
            )
        new_revision_id = page_result.get("new_generated_page_revision_id")
        new_qa_id = page_result.get("new_qa_result_id")
        if (
            isinstance(new_revision_id, bool)
            or not isinstance(new_revision_id, int)
            or new_revision_id <= minimum_revision_id
            or isinstance(new_qa_id, bool)
            or not isinstance(new_qa_id, int)
            or new_qa_id <= minimum_qa_id
            or new_revision_id in new_revision_ids
            or new_qa_id in new_qa_ids
        ):
            raise PublicCopyRunnerExecutionError(
                "Reconciliation returned duplicate or non-successor evidence identities."
            )
        new_revision_ids.add(new_revision_id)
        new_qa_ids.add(new_qa_id)
        new_source_hash = _required_sha256(
            page_result.get("new_composition_source_hash"),
            field=f"Reconciliation Page result {index} new composition source hash",
        )
        _required_sha256(
            page_result.get("new_qa_result_hash"),
            field=f"Reconciliation Page result {index} new QA result hash",
        )
        if new_source_hash == binding["current_composition"]["source_hash"]:
            raise PublicCopyRunnerExecutionError(
                "Reconciliation Page result did not advance composition source identity."
            )
    return payload


def _sealed_report(
    prepared: PreparedInvocation,
    *,
    outcome: str,
    transaction_outcome: str,
    reconciliation_result: dict[str, Any] | None,
    injected_failure: dict[str, Any] | None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": RUNNER_REPORT_SCHEMA,
        "operation": RUNNER_OPERATION,
        "atlas_revision": ATLAS_REVISION,
        "target_role": prepared.arguments.target_role,
        "mode": prepared.arguments.mode,
        "actor": prepared.arguments.actor,
        "commit": prepared.arguments.commit,
        "outcome": outcome,
        "transaction_outcome": transaction_outcome,
        "expected_affected_page_count": EXPECTED_AFFECTED_PAGE_COUNT,
        "runner_sha256": prepared.runner_sha256,
        "source_root_sha256": prepared.source_root_sha256,
        "postgres_rehearsal_harness_sha256": (
            prepared.postgres_rehearsal_harness_sha256
        ),
        "postgres_rehearsal_conftest_sha256": (
            prepared.postgres_rehearsal_conftest_sha256
        ),
        "database_url_sha256": prepared.database_url_sha256,
        "invocation_config_sha256": prepared.arguments.invocation_config_sha256,
        "manifest_sha256": prepared.arguments.manifest_sha256,
        "ruleset_sha256": prepared.arguments.ruleset_sha256,
        "rehearsal_evidence_sha256": prepared.rehearsal_evidence_sha256,
        "forbidden_actions": dict(FORBIDDEN_ACTIONS),
        "reconciliation_result": reconciliation_result,
        "injected_failure": injected_failure,
        "customer_data": False,
        "external_requests": False,
    }
    report["report_sha256"] = canonical_json_sha256(report)
    return report


def _read_exact_atlas_revision(session: Any) -> str:
    try:
        rows = list(
            session.connection()
            .exec_driver_sql(
                "SELECT version_num FROM alembic_version ORDER BY version_num"
            )
            .scalars()
            .all()
        )
    except Exception as exc:
        raise PublicCopyRunnerExecutionError(
            "Unable to read the exact Atlas migration revision."
        ) from exc
    if rows != [ATLAS_REVISION]:
        raise PublicCopyRunnerExecutionError(
            "Target database is not at the exact authorized Atlas revision."
        )
    return rows[0]


def execute_prepared_invocation(
    prepared: PreparedInvocation,
    *,
    engine_factory: Callable[..., Any] = create_engine,
    session_factory: Callable[[Any], Any] = Session,
    reconcile: Callable[..., Any] = reconcile_public_copy,
    revision_reader: Callable[[Any], str] = _read_exact_atlas_revision,
) -> dict[str, Any]:
    engine = engine_factory(prepared.arguments.database_url, echo=False)
    try:
        with session_factory(engine) as session:
            try:
                if revision_reader(session) != ATLAS_REVISION:
                    raise PublicCopyRunnerExecutionError(
                        "Target database revision reader returned a contradictory value."
                    )
                result = reconcile(
                    session,
                    prepared.package,
                    actor=prepared.arguments.actor,
                    # The runner, not the service, owns the final commit so the
                    # exact result contract is validated inside the same open
                    # transaction as the 65-page mutation.
                    commit=False,
                    inject_failure_after_qa=prepared.invocation[
                        "inject_failure_after_qa"
                    ],
                )
                if prepared.arguments.mode == MODE_REHEARSAL_INJECTED_FAILURE:
                    raise PublicCopyRunnerExecutionError(
                        "Configured clone failure injection did not occur."
                    )
                result_payload = _strict_result_payload(
                    result,
                    prepared=prepared,
                )
                status = result_payload["status"]
                if status == "applied":
                    session.commit()
                    transaction_outcome = "committed"
                else:
                    session.rollback()
                    transaction_outcome = "write_free_noop"
            except PublicCopyReconciliationInjectedFailure as exc:
                session.rollback()
                if prepared.arguments.mode != MODE_REHEARSAL_INJECTED_FAILURE:
                    raise PublicCopyRunnerExecutionError(
                        "Unexpected injected failure outside clone rehearsal mode."
                    ) from exc
                return _sealed_report(
                    prepared,
                    outcome="injected_failure_rolled_back",
                    transaction_outcome="rolled_back",
                    reconciliation_result=None,
                    injected_failure={
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "after_qa": prepared.invocation[
                            "inject_failure_after_qa"
                        ],
                    },
                )
            except Exception as exc:
                session.rollback()
                raise PublicCopyRunnerExecutionError(
                    "Public-copy reconciliation failed; the transaction was "
                    "rolled back."
                ) from exc
            return _sealed_report(
                prepared,
                outcome=status,
                transaction_outcome=transaction_outcome,
                reconciliation_result=result_payload,
                injected_failure=None,
            )
    finally:
        engine.dispose()


def run_invocation(
    arguments: RunnerArguments,
    *,
    manifest_loader: Callable[..., PublicCopyManifestPackage] = (
        load_public_copy_manifest_package
    ),
    engine_factory: Callable[..., Any] = create_engine,
    session_factory: Callable[[Any], Any] = Session,
    reconcile: Callable[..., Any] = reconcile_public_copy,
    revision_reader: Callable[[Any], str] = _read_exact_atlas_revision,
) -> dict[str, Any]:
    prepared = prepare_invocation(arguments, manifest_loader=manifest_loader)
    return execute_prepared_invocation(
        prepared,
        engine_factory=engine_factory,
        session_factory=session_factory,
        reconcile=reconcile,
        revision_reader=revision_reader,
    )


def _parse_commit(value: str) -> bool:
    if value != "true":
        raise argparse.ArgumentTypeError("--commit must be the literal value true.")
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the SHA-pinned Project Atlas public-copy reconciliation only."
        )
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--ruleset-path", type=Path, required=True)
    parser.add_argument("--ruleset-sha256", required=True)
    parser.add_argument("--invocation-config-path", type=Path, required=True)
    parser.add_argument("--invocation-config-sha256", required=True)
    parser.add_argument("--rehearsal-evidence-path", type=Path)
    parser.add_argument("--rehearsal-evidence-sha256")
    parser.add_argument(
        "--target-role",
        choices=(TARGET_ROLE_DISPOSABLE_CLONE, TARGET_ROLE_ACTIVE_LOCAL),
        required=True,
    )
    parser.add_argument(
        "--mode",
        choices=(
            MODE_REHEARSAL_SUCCESS,
            MODE_REHEARSAL_INJECTED_FAILURE,
            MODE_ACTIVE_APPLY,
        ),
        required=True,
    )
    parser.add_argument("--actor", required=True)
    parser.add_argument("--commit", type=_parse_commit, required=True)
    return parser


def _error_report(exc: Exception) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": RUNNER_ERROR_REPORT_SCHEMA,
        "outcome": "rejected",
        "error_type": type(exc).__name__,
        "message": str(exc),
        "customer_data": False,
        "external_requests": False,
    }
    report["report_sha256"] = canonical_json_sha256(report)
    return report


def main(argv: list[str] | None = None) -> int:
    namespace = build_parser().parse_args(argv)
    arguments = RunnerArguments(**vars(namespace))
    try:
        report = run_invocation(arguments)
    except PublicCopyRunnerError as exc:
        print(canonical_json_bytes(_error_report(exc)).decode("utf-8"), file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - last-resort secret-safe boundary
        wrapped = PublicCopyRunnerExecutionError(
            "Unexpected runner failure; no successful outcome was reported."
        )
        print(
            canonical_json_bytes(_error_report(wrapped)).decode("utf-8"),
            file=sys.stderr,
        )
        return 3
    print(canonical_json_bytes(report).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
