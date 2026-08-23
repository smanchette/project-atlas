from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from app.services.public_copy_reconciliation import (
    PublicCopyReconciliationInjectedFailure,
)
from scripts import public_copy_reconciliation_runner as runner


CLONE_DATABASE_URL = (
    "postgresql+psycopg://atlas:clone-secret@127.0.0.1:5432/atlas_clone"
)
ACTIVE_DATABASE_URL = (
    "postgresql+psycopg://atlas:active-secret@127.0.0.1:5432/atlas_active"
)
ACTOR = "public-copy-reconciliation-operator"
WEBSITE_ID = 7
SITE_PLAN_ID = 11
AUDIT_FINGERPRINT = hashlib.sha256(b"public-copy-audit").hexdigest()


@dataclass(frozen=True)
class _Case:
    source_root: Path
    manifest_path: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    ruleset_path: Path
    ruleset: dict[str, Any]
    ruleset_sha256: str
    config_path: Path
    config: dict[str, Any]
    config_sha256: str
    evidence_path: Path
    evidence: dict[str, Any]
    evidence_sha256: str
    harness_sha256: str
    conftest_sha256: str


@dataclass(frozen=True)
class _Result:
    status: str
    manifest_file_sha256: str
    ruleset_payload_sha256: str
    website_id: int
    site_plan_id: int
    affected_page_count: int
    page_results: tuple[dict[str, Any], ...]
    appended_evidence_row_count: int
    updated_head_row_count: int
    superseded_qa_row_count: int
    public_copy_audit_fingerprint: str
    public_copy_warning_count: int
    public_copy_informational_count: int


class _FakeEngine:
    def __init__(self, database_url: str, echo: bool) -> None:
        self.database_url = database_url
        self.echo = echo
        self.dispose_count = 0

    def dispose(self) -> None:
        self.dispose_count += 1


class _FakeSession:
    def __init__(self, engine: _FakeEngine) -> None:
        self.engine = engine
        self.commit_count = 0
        self.rollback_count = 0
        self.enter_count = 0
        self.exit_count = 0

    def __enter__(self) -> _FakeSession:
        self.enter_count += 1
        return self

    def __exit__(self, *_args: Any) -> None:
        self.exit_count += 1

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def connection(self) -> _FakeConnection:
        return _FakeConnection()


class _FakeConnection:
    def exec_driver_sql(self, statement: str) -> _FakeRevisionResult:
        assert statement == (
            "SELECT version_num FROM alembic_version ORDER BY version_num"
        )
        return _FakeRevisionResult()


class _FakeRevisionResult:
    def scalars(self) -> _FakeRevisionResult:
        return self

    def all(self) -> list[str]:
        return [runner.ATLAS_REVISION]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> str:
    payload = runner.canonical_json_bytes(value)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _full_page_binding(page_id: int) -> dict[str, Any]:
    generated_page_id = 100 + page_id
    old_revision_id = 1_000 + page_id
    composition_id = 5_000 + page_id
    composition_history_id = 6_000 + page_id
    qa_id = 3_000 + page_id
    old_content_hash = _hash(f"old-content:{page_id}")
    updated_at = f"2026-08-20T12:{page_id % 60:02d}:00+00:00"
    expected_draft = {
        "title": f"Public page {page_id}",
        "description": f"Corrected public description {page_id}",
        "public_destination_copy": [
            {
                "field": "intro",
                "text": f"Corrected destination copy for page {page_id}.",
            }
        ],
    }
    return {
        "website_id": WEBSITE_ID,
        "site_plan_id": SITE_PLAN_ID,
        "planned_page_id": page_id,
        "generated_page_id": generated_page_id,
        "page_type": "service_city",
        "working_name": f"Page {page_id}",
        "slug": f"page-{page_id}",
        "page_identity": {
            "planned_page_status": "drafted",
            "planned_page_parent_id": None,
            "service_id": 1,
            "county_id": 2,
            "city_id": 3,
            "generated_page_type": "service_city",
            "generated_page_slug": f"page-{page_id}",
            "generated_page_title": f"Public page {page_id}",
            "generated_page_status": "draft",
            "generated_page_generation_status": "generated",
            "generated_page_qa_status": "approved",
            "generated_page_meta_title": f"Meta {page_id}",
            "generated_page_meta_description": f"Description {page_id}",
            "generated_page_h1": f"Heading {page_id}",
            "generated_page_content_body_sha256": old_content_hash,
            "generated_page_preserved_state_sha256": _hash(
                f"preserved-generated-page:{page_id}"
            ),
            "generated_page_updated_at": updated_at,
        },
        "current_revision": {
            "bound_generated_page_revision_id": old_revision_id,
            "latest_page_revision_id": old_revision_id,
            "latest_page_revision_hash_after": old_content_hash,
            "latest_page_revision_row_sha256": _hash(
                f"revision-row:{page_id}"
            ),
            "binding_kind": "canonical_bound",
            "content_hash": old_content_hash,
            "generated_page_updated_at": updated_at,
        },
        "current_composition": {
            "id": composition_id,
            "version": 8,
            "source_hash": _hash(f"old-composition-source:{page_id}"),
            "history_revision_id": composition_history_id,
            "history_revision_hash": _hash(f"composition-history:{page_id}"),
            "history_revision_row_sha256": _hash(
                f"composition-history-row:{page_id}"
            ),
            "content_hash": old_content_hash,
        },
        "current_qa": {
            "id": qa_id,
            "result_hash": _hash(f"old-qa-result:{page_id}"),
            "source_hash": _hash(f"old-qa-source:{page_id}"),
            "ruleset_key": "public-copy-active",
            "ruleset_version": "1",
            "ruleset_hash": _hash("public-copy-ruleset"),
            "readiness_status": "ready",
            "preserved_evidence_sha256": _hash(
                f"preserved-qa-evidence:{page_id}"
            ),
        },
        "expected_new_content_hash": runner.canonical_json_sha256(
            expected_draft
        ),
        "expected_draft_content": expected_draft,
        "expected_revision_required": True,
        "correction_entry_ids": [f"correction-{page_id:03d}"],
        "expected_changed_top_level_fields": [
            "description",
            "public_destination_copy",
        ],
        "expected_public_block_distinctness": {
            "planned_page_id": page_id,
            "public_block_count": 1,
            "inventory_sha256": _hash(f"public-blocks:{page_id}"),
            "duplicate_group_count": 0,
        },
    }


def _manifest() -> dict[str, Any]:
    bindings = [_full_page_binding(page_id) for page_id in range(1, 66)]
    return {
        "document": "sealed-manifest",
        "scope": {
            "website_id": WEBSITE_ID,
            "site_plan_id": SITE_PLAN_ID,
            "planned_page_count": 65,
            "generated_page_count": 65,
            "affected_page_count": 65,
            "customer_data": False,
        },
        "immutable_history_snapshot": {
            "generated_page_revisions": {
                "row_count": 65,
                "maximum_id": 1_065,
                "canonical_rows_sha256": _hash("all-generated-page-revisions"),
            },
            "page_composition_revisions": {
                "row_count": 65,
                "maximum_id": 6_065,
                "canonical_rows_sha256": _hash(
                    "all-page-composition-revisions"
                ),
            },
            "generated_page_qa_results": {
                "row_count": 65,
                "maximum_id": 3_065,
                "canonical_rows_sha256": _hash("all-generated-page-qa"),
                "current_row_ids": list(range(3_001, 3_066)),
                "canonical_noncurrent_rows_sha256": _hash(
                    "all-noncurrent-generated-page-qa"
                ),
                "canonical_current_preserved_rows_sha256": _hash(
                    "all-current-preserved-generated-page-qa"
                ),
            },
        },
        "page_bindings": bindings,
    }


def _build_rehearsal_evidence(
    *,
    source_root_sha256: str,
    manifest_sha256: str,
    ruleset_sha256: str,
    runner_sha256: str,
    config_sha256: str,
    harness_sha256: str,
    conftest_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": runner.REHEARSAL_EVIDENCE_SCHEMA,
        "operation": runner.REHEARSAL_EVIDENCE_OPERATION,
        "source_freeze_go_received": True,
        "postgresql_go_received": True,
        "atlas_revision": runner.ATLAS_REVISION,
        "database_prefix": "atlas_pcopy_rehearsal_",
        "disposable_database_names": [
            {
                "ordinal": 1,
                "name": "atlas_pcopy_rehearsal_01",
                "recorded_before_creation": True,
                "created": True,
                "removed": True,
                "confirmed_absent": True,
            }
        ],
        "source_pins": {
            "source_root": {"path": ".", "sha256": source_root_sha256},
            "manifest": {
                "path": "manifest.json",
                "sha256": manifest_sha256,
            },
            "ruleset": {
                "path": "ruleset.json",
                "sha256": ruleset_sha256,
            },
            "runner": {
                "path": "backend/scripts/public_copy_reconciliation_runner.py",
                "sha256": runner_sha256,
            },
            "invocation_config": {
                "path": "invocation.json",
                "sha256": config_sha256,
            },
            "postgres_rehearsal_harness": {
                "path": runner.POSTGRES_REHEARSAL_HARNESS_PATH,
                "sha256": harness_sha256,
            },
            "postgres_rehearsal_conftest": {
                "path": runner.POSTGRES_REHEARSAL_CONFTEST_PATH,
                "sha256": conftest_sha256,
            },
        },
        "runner_contract": {
            "actor": ACTOR,
            "target_role": runner.TARGET_ROLE_DISPOSABLE_CLONE,
            "success_mode": runner.MODE_REHEARSAL_SUCCESS,
            "failure_mode": runner.MODE_REHEARSAL_INJECTED_FAILURE,
            "inject_failure_after_qa": 33,
            "commit": True,
            "clone_database_url_sha256": _sha256_text(CLONE_DATABASE_URL),
            "expected_affected_page_count": 65,
        },
        "preloaded_post_0048_clone": {
            "database_name": "atlas_pcopy_rehearsal_01",
            "dump": {
                "path": "sealed/atlas-post-0048.dump",
                "sha256": _hash("post-0048-dump"),
            },
            "restored_before_tests": True,
            "migration_applied_by_test": False,
            "atlas_revision": runner.ATLAS_REVISION,
            "database_fingerprint_sha256": _hash("clone-database"),
            "sequence_state_sha256": _hash("clone-sequences"),
        },
        "sequence_restore_allowlist": [
            "generatedpagerevision_id_seq",
            "pagecompositionrevision_id_seq",
            "generatedpageqaresult_id_seq",
        ],
        "no_migration": True,
        "customer_data": False,
        "external_requests": False,
        "status": runner.REHEARSAL_EVIDENCE_STATUS,
        "reports": [
            {
                "stage": "qa33_injected_rollback",
                "outcome": "injected_failure_rolled_back",
                "transaction_outcome": "rolled_back",
                "report_sha256": _hash("rollback-runner-report"),
                "evidence_sha256": _hash("rollback-stage-evidence"),
            },
            {
                "stage": "successful_apply",
                "outcome": "applied",
                "transaction_outcome": "committed",
                "report_sha256": _hash("success-runner-report"),
                "evidence_sha256": _hash("success-stage-evidence"),
            },
            {
                "stage": "write_free_repeat",
                "outcome": "already_applied",
                "transaction_outcome": "write_free_noop",
                "report_sha256": _hash("repeat-runner-report"),
                "evidence_sha256": _hash("repeat-stage-evidence"),
            },
            {
                "stage": "two_session_governed_source_lock",
                "outcome": "update_and_insert_writers_blocked_and_rejected",
                "evidence_sha256": _hash("concurrency-stage-evidence"),
            },
            {
                "stage": "immutable_history_and_destination_binding_tamper",
                "outcome": "all_tamper_rejected",
                "evidence_sha256": _hash("tamper-stage-evidence"),
            },
        ],
        "cleanup": {
            "sessions_terminated": True,
            "database_removed": True,
            "database_confirmed_absent": True,
        },
    }


def _build_case(tmp_path: Path) -> _Case:
    source_root = tmp_path / "sealed-source"
    tests_root = source_root / "backend" / "tests"
    tests_root.mkdir(parents=True)
    harness_path = source_root / runner.POSTGRES_REHEARSAL_HARNESS_PATH
    conftest_path = source_root / runner.POSTGRES_REHEARSAL_CONFTEST_PATH
    harness_path.write_text("# sealed PostgreSQL rehearsal harness\n", encoding="utf-8")
    conftest_path.write_text("# sealed PostgreSQL rehearsal fixtures\n", encoding="utf-8")

    manifest_path = source_root / "manifest.json"
    ruleset_path = source_root / "ruleset.json"
    config_path = source_root / "invocation.json"
    evidence_path = source_root / "rehearsal-evidence.json"
    manifest = _manifest()
    ruleset = {"document": "sealed-ruleset"}
    manifest_sha256 = _write_json(manifest_path, manifest)
    ruleset_sha256 = _write_json(ruleset_path, ruleset)
    source_root_sha256 = runner._validate_source_root(source_root)[1]
    harness_sha256 = runner._source_file_sha256(
        source_root.resolve(), runner.POSTGRES_REHEARSAL_HARNESS_PATH
    )
    conftest_sha256 = runner._source_file_sha256(
        source_root.resolve(), runner.POSTGRES_REHEARSAL_CONFTEST_PATH
    )
    config = {
        "schema": runner.INVOCATION_CONFIG_SCHEMA,
        "operation": runner.RUNNER_OPERATION,
        "atlas_revision": runner.ATLAS_REVISION,
        "expected_affected_page_count": runner.EXPECTED_AFFECTED_PAGE_COUNT,
        "actor": ACTOR,
        "commit_required": True,
        "manifest_sha256": manifest_sha256,
        "ruleset_sha256": ruleset_sha256,
        "runner_sha256": runner.runner_file_sha256(),
        "source_root_sha256": source_root_sha256,
        "postgres_rehearsal_harness_sha256": harness_sha256,
        "postgres_rehearsal_conftest_sha256": conftest_sha256,
        "forbidden_actions": dict(runner.FORBIDDEN_ACTIONS),
        "active_apply_prerequisite": {
            "required": True,
            "schema": runner.REHEARSAL_EVIDENCE_SCHEMA,
            "operation": runner.REHEARSAL_EVIDENCE_OPERATION,
            "status": runner.REHEARSAL_EVIDENCE_STATUS,
        },
        "invocations": [
            {
                "target_role": runner.TARGET_ROLE_DISPOSABLE_CLONE,
                "mode": runner.MODE_REHEARSAL_SUCCESS,
                "database_url_sha256": _sha256_text(CLONE_DATABASE_URL),
                "commit": True,
                "inject_failure_after_qa": None,
            },
            {
                "target_role": runner.TARGET_ROLE_DISPOSABLE_CLONE,
                "mode": runner.MODE_REHEARSAL_INJECTED_FAILURE,
                "database_url_sha256": _sha256_text(CLONE_DATABASE_URL),
                "commit": True,
                "inject_failure_after_qa": 33,
            },
            {
                "target_role": runner.TARGET_ROLE_ACTIVE_LOCAL,
                "mode": runner.MODE_ACTIVE_APPLY,
                "database_url_sha256": _sha256_text(ACTIVE_DATABASE_URL),
                "commit": True,
                "inject_failure_after_qa": None,
            },
        ],
        "customer_data": False,
        "external_requests": False,
    }
    config_sha256 = _write_json(config_path, config)
    evidence = _build_rehearsal_evidence(
        source_root_sha256=source_root_sha256,
        manifest_sha256=manifest_sha256,
        ruleset_sha256=ruleset_sha256,
        runner_sha256=config["runner_sha256"],
        config_sha256=config_sha256,
        harness_sha256=harness_sha256,
        conftest_sha256=conftest_sha256,
    )
    evidence_sha256 = _write_json(evidence_path, evidence)
    return _Case(
        source_root=source_root,
        manifest_path=manifest_path,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        ruleset_path=ruleset_path,
        ruleset=ruleset,
        ruleset_sha256=ruleset_sha256,
        config_path=config_path,
        config=config,
        config_sha256=config_sha256,
        evidence_path=evidence_path,
        evidence=evidence,
        evidence_sha256=evidence_sha256,
        harness_sha256=harness_sha256,
        conftest_sha256=conftest_sha256,
    )


def _arguments(
    case: _Case,
    *,
    target_role: str = runner.TARGET_ROLE_ACTIVE_LOCAL,
    mode: str = runner.MODE_ACTIVE_APPLY,
    database_url: str = ACTIVE_DATABASE_URL,
    actor: str = ACTOR,
    commit: bool = True,
    config_sha256: str | None = None,
    include_rehearsal_evidence: bool | None = None,
) -> runner.RunnerArguments:
    if include_rehearsal_evidence is None:
        include_rehearsal_evidence = target_role == runner.TARGET_ROLE_ACTIVE_LOCAL
    return runner.RunnerArguments(
        database_url=database_url,
        source_root=case.source_root,
        manifest_path=case.manifest_path,
        manifest_sha256=case.manifest_sha256,
        ruleset_path=case.ruleset_path,
        ruleset_sha256=case.ruleset_sha256,
        invocation_config_path=case.config_path,
        invocation_config_sha256=config_sha256 or case.config_sha256,
        target_role=target_role,
        mode=mode,
        actor=actor,
        commit=commit,
        rehearsal_evidence_path=(
            case.evidence_path if include_rehearsal_evidence else None
        ),
        rehearsal_evidence_sha256=(
            case.evidence_sha256 if include_rehearsal_evidence else None
        ),
    )


def _manifest_loader(case: _Case, calls: list[dict[str, Any]]):
    def load(
        manifest_path: Path,
        *,
        manifest_sha256: str,
        ruleset_path: Path,
        ruleset_sha256: str,
        source_root: Path,
    ) -> SimpleNamespace:
        calls.append(
            {
                "manifest_path": manifest_path,
                "manifest_sha256": manifest_sha256,
                "ruleset_path": ruleset_path,
                "ruleset_sha256": ruleset_sha256,
                "source_root": source_root,
            }
        )
        return SimpleNamespace(
            manifest=case.manifest,
            ruleset=case.ruleset,
            manifest_file_sha256=case.manifest_sha256,
            ruleset_file_sha256=case.ruleset_sha256,
            ruleset_payload_sha256=runner.canonical_json_sha256(case.ruleset),
        )

    return load


def _valid_page_results(case: _Case) -> tuple[dict[str, Any], ...]:
    results: list[dict[str, Any]] = []
    for page_id, binding in enumerate(case.manifest["page_bindings"], start=1):
        results.append(
            {
                "planned_page_id": binding["planned_page_id"],
                "generated_page_id": binding["generated_page_id"],
                "old_generated_page_revision_id": binding["current_revision"][
                    "latest_page_revision_id"
                ],
                "new_generated_page_revision_id": 2_000 + page_id,
                "old_content_hash": binding["current_revision"]["content_hash"],
                "new_content_hash": binding["expected_new_content_hash"],
                "composition_id": binding["current_composition"]["id"],
                "old_composition_version": binding["current_composition"][
                    "version"
                ],
                "new_composition_version": binding["current_composition"][
                    "version"
                ]
                + 1,
                "old_composition_source_hash": binding["current_composition"][
                    "source_hash"
                ],
                "new_composition_source_hash": _hash(
                    f"new-composition-source:{page_id}"
                ),
                "old_qa_result_id": binding["current_qa"]["id"],
                "new_qa_result_id": 4_000 + page_id,
                "new_qa_result_hash": _hash(f"new-qa-result:{page_id}"),
            }
        )
    return tuple(results)


def _valid_result(case: _Case, *, status: str = "applied") -> _Result:
    applied = status == "applied"
    return _Result(
        status=status,
        manifest_file_sha256=case.manifest_sha256,
        ruleset_payload_sha256=runner.canonical_json_sha256(case.ruleset),
        website_id=WEBSITE_ID,
        site_plan_id=SITE_PLAN_ID,
        affected_page_count=65,
        page_results=_valid_page_results(case) if applied else (),
        appended_evidence_row_count=195 if applied else 0,
        updated_head_row_count=130 if applied else 0,
        superseded_qa_row_count=65 if applied else 0,
        public_copy_audit_fingerprint=AUDIT_FINGERPRINT,
        public_copy_warning_count=11,
        public_copy_informational_count=0,
    )


def _reseal_evidence(
    case: _Case,
    mutate: Callable[[dict[str, Any]], None],
) -> runner.RunnerArguments:
    evidence = deepcopy(case.evidence)
    mutate(evidence)
    sha256 = _write_json(case.evidence_path, evidence)
    return replace(
        _arguments(case),
        rehearsal_evidence_sha256=sha256,
    )


def _root_cause_message(exc: BaseException) -> str:
    current = exc
    while current.__cause__ is not None:
        current = current.__cause__
    return str(current)


@pytest.mark.parametrize(
    "path_field",
    ["manifest_path", "ruleset_path", "config_path"],
)
def test_sha_pins_reject_tampered_manifest_ruleset_or_config(
    tmp_path: Path,
    path_field: str,
) -> None:
    case = _build_case(tmp_path)
    path = getattr(case, path_field)
    path.write_bytes(path.read_bytes() + b"\n")
    loader_called = False

    def loader(*_args: Any, **_kwargs: Any) -> None:
        nonlocal loader_called
        loader_called = True

    with pytest.raises(runner.PublicCopyRunnerError, match="caller pin"):
        runner.prepare_invocation(_arguments(case), manifest_loader=loader)
    assert loader_called is False


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("manifest_sha256", "manifest SHA-256 does not match"),
        ("ruleset_sha256", "ruleset SHA-256 does not match"),
        ("runner_sha256", "Runner bytes do not match"),
        ("source_root_sha256", "source root does not match"),
        (
            "postgres_rehearsal_harness_sha256",
            "harness bytes differ",
        ),
        (
            "postgres_rehearsal_conftest_sha256",
            "conftest bytes differ",
        ),
    ],
)
def test_resealed_config_cannot_change_any_execution_binding(
    tmp_path: Path,
    field: str,
    message: str,
) -> None:
    case = _build_case(tmp_path)
    config = deepcopy(case.config)
    config[field] = "0" * 64
    config_sha256 = _write_json(case.config_path, config)
    with pytest.raises(runner.PublicCopyRunnerError, match=message):
        runner.prepare_invocation(
            _arguments(case, config_sha256=config_sha256),
            manifest_loader=lambda *_args, **_kwargs: None,
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b'{"schema":"one","schema":"two"}', "duplicate JSON key"),
        (b'{"value":NaN}', "non-finite JSON number"),
    ],
)
def test_strict_json_rejects_duplicates_and_nonfinite_values(
    tmp_path: Path,
    payload: bytes,
    message: str,
) -> None:
    path = tmp_path / "strict.json"
    path.write_bytes(payload)
    sha256 = hashlib.sha256(payload).hexdigest()
    with pytest.raises(runner.PublicCopyRunnerError, match=message):
        runner._load_sha_pinned_json(path, sha256, label="Test document")


def test_pinned_json_rejects_symlink_and_nonregular_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    regular = tmp_path / "regular.json"
    regular.write_text("{}", encoding="utf-8")
    original_check = runner._is_link_or_reparse
    monkeypatch.setattr(
        runner,
        "_is_link_or_reparse",
        lambda path: path == regular.absolute() or original_check(path),
    )
    with pytest.raises(runner.PublicCopyRunnerError, match="symlink or reparse"):
        runner._load_sha_pinned_json(
            regular,
            hashlib.sha256(b"{}").hexdigest(),
            label="Test document",
        )

    directory = tmp_path / "directory.json"
    directory.mkdir()
    with pytest.raises(runner.PublicCopyRunnerError, match="regular non-symlink"):
        runner._load_sha_pinned_json(
            directory,
            "0" * 64,
            label="Test document",
        )


@pytest.mark.parametrize(
    ("entry_index", "injection", "message"),
    [
        (0, 1, "only in explicit clone rehearsal mode"),
        (1, 0, "strictly inside"),
        (1, 65, "strictly inside"),
        (2, 1, "only in explicit clone rehearsal mode"),
    ],
)
def test_config_rejects_injection_outside_the_explicit_clone_boundary(
    tmp_path: Path,
    entry_index: int,
    injection: int,
    message: str,
) -> None:
    case = _build_case(tmp_path)
    config = deepcopy(case.config)
    config["invocations"][entry_index]["inject_failure_after_qa"] = injection
    config_sha256 = _write_json(case.config_path, config)
    with pytest.raises(runner.PublicCopyRunnerError, match=message):
        runner.prepare_invocation(
            _arguments(case, config_sha256=config_sha256),
            manifest_loader=lambda *_args, **_kwargs: None,
        )


@pytest.mark.parametrize(
    ("argument_overrides", "message"),
    [
        (
            {
                "target_role": runner.TARGET_ROLE_ACTIVE_LOCAL,
                "mode": runner.MODE_REHEARSAL_SUCCESS,
            },
            "role/mode is not authorized",
        ),
        ({"actor": "different-actor"}, "actor does not match"),
        ({"commit": False}, "commit=true"),
        ({"database_url": CLONE_DATABASE_URL}, "database URL does not match"),
    ],
)
def test_cli_identity_and_behavior_must_match_the_sealed_target(
    tmp_path: Path,
    argument_overrides: dict[str, Any],
    message: str,
) -> None:
    case = _build_case(tmp_path)
    with pytest.raises(runner.PublicCopyRunnerError, match=message):
        runner.prepare_invocation(
            _arguments(case, **argument_overrides),
            manifest_loader=lambda *_args, **_kwargs: None,
        )


def test_runner_exposes_no_forbidden_action_switches() -> None:
    parser_destinations = {action.dest for action in runner.build_parser()._actions}
    assert parser_destinations.isdisjoint(runner.FORBIDDEN_ACTIONS)
    assert runner.FORBIDDEN_ACTIONS == {
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


def test_config_cannot_enable_a_forbidden_action(tmp_path: Path) -> None:
    case = _build_case(tmp_path)
    config = deepcopy(case.config)
    config["forbidden_actions"]["publish"] = True
    config_sha256 = _write_json(case.config_path, config)
    with pytest.raises(runner.PublicCopyRunnerError, match="forbidden action"):
        runner.prepare_invocation(
            _arguments(case, config_sha256=config_sha256),
            manifest_loader=lambda *_args, **_kwargs: None,
        )


def test_config_requires_exact_active_apply_prerequisite(tmp_path: Path) -> None:
    case = _build_case(tmp_path)
    config = deepcopy(case.config)
    config["active_apply_prerequisite"]["required"] = False
    config_sha256 = _write_json(case.config_path, config)
    with pytest.raises(runner.PublicCopyRunnerError, match="cleaned rehearsal evidence"):
        runner.prepare_invocation(
            _arguments(case, config_sha256=config_sha256),
            manifest_loader=lambda *_args, **_kwargs: None,
        )


@pytest.mark.parametrize(
    "source_path",
    [
        runner.POSTGRES_REHEARSAL_HARNESS_PATH,
        runner.POSTGRES_REHEARSAL_CONFTEST_PATH,
    ],
)
def test_sealed_postgres_test_source_bytes_cannot_drift(
    tmp_path: Path,
    source_path: str,
) -> None:
    case = _build_case(tmp_path)
    path = case.source_root / source_path
    path.write_bytes(path.read_bytes() + b"# drift\n")
    with pytest.raises(runner.PublicCopyRunnerError, match="bytes differ"):
        runner.prepare_invocation(
            _arguments(case),
            manifest_loader=lambda *_args, **_kwargs: None,
        )


@pytest.mark.parametrize("missing", ["both", "path", "sha256"])
def test_active_apply_rejects_absent_or_one_sided_rehearsal_evidence(
    tmp_path: Path,
    missing: str,
) -> None:
    case = _build_case(tmp_path)
    arguments = _arguments(case)
    if missing == "both":
        arguments = replace(
            arguments,
            rehearsal_evidence_path=None,
            rehearsal_evidence_sha256=None,
        )
        message = "Active apply requires"
    elif missing == "path":
        arguments = replace(arguments, rehearsal_evidence_path=None)
        message = "must be supplied together"
    else:
        arguments = replace(arguments, rehearsal_evidence_sha256=None)
        message = "must be supplied together"
    with pytest.raises(runner.PublicCopyRunnerError, match=message):
        runner.prepare_invocation(
            arguments,
            manifest_loader=_manifest_loader(case, []),
        )


def test_active_apply_rejects_wrong_rehearsal_evidence_sha(tmp_path: Path) -> None:
    case = _build_case(tmp_path)
    with pytest.raises(runner.PublicCopyRunnerError, match="caller pin"):
        runner.prepare_invocation(
            replace(
                _arguments(case),
                rehearsal_evidence_sha256="0" * 64,
            ),
            manifest_loader=_manifest_loader(case, []),
        )


def test_active_apply_rejects_tampered_rehearsal_evidence_file(
    tmp_path: Path,
) -> None:
    case = _build_case(tmp_path)
    case.evidence_path.write_bytes(case.evidence_path.read_bytes() + b"\n")
    with pytest.raises(runner.PublicCopyRunnerError, match="caller pin"):
        runner.prepare_invocation(
            _arguments(case),
            manifest_loader=_manifest_loader(case, []),
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda evidence: evidence.__setitem__("status", "FAIL_CLEANED"),
            "exact PASS_CLEANED",
        ),
        (
            lambda evidence: evidence["cleanup"].__setitem__(
                "database_removed", False
            ),
            "not unconditionally cleaned",
        ),
        (
            lambda evidence: evidence["source_pins"]["runner"].__setitem__(
                "sha256", "0" * 64
            ),
            "source pin runner differs",
        ),
        (
            lambda evidence: evidence["reports"][0].__setitem__(
                "stage", "wrong_stage"
            ),
            "report stages or outcomes differ",
        ),
    ],
    ids=["non-pass", "unclean", "source-pin", "stage"],
)
def test_active_apply_rejects_invalid_rehearsal_evidence_contract(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    case = _build_case(tmp_path)
    with pytest.raises(runner.PublicCopyRunnerError, match=message):
        runner.prepare_invocation(
            _reseal_evidence(case, mutate),
            manifest_loader=_manifest_loader(case, []),
        )


def test_clone_modes_reject_active_prerequisite_evidence(tmp_path: Path) -> None:
    case = _build_case(tmp_path)
    arguments = _arguments(
        case,
        target_role=runner.TARGET_ROLE_DISPOSABLE_CLONE,
        mode=runner.MODE_REHEARSAL_SUCCESS,
        database_url=CLONE_DATABASE_URL,
    )
    arguments = replace(
        arguments,
        rehearsal_evidence_path=case.evidence_path,
        rehearsal_evidence_sha256=case.evidence_sha256,
    )
    with pytest.raises(runner.PublicCopyRunnerError, match="must not accept"):
        runner.prepare_invocation(
            arguments,
            manifest_loader=_manifest_loader(case, []),
        )


def test_same_runner_config_and_strict_result_drive_clone_and_active(
    tmp_path: Path,
) -> None:
    case = _build_case(tmp_path)
    loader_calls: list[dict[str, Any]] = []
    engines: list[_FakeEngine] = []
    sessions: list[_FakeSession] = []
    reconcile_calls: list[dict[str, Any]] = []

    def engine_factory(database_url: str, *, echo: bool) -> _FakeEngine:
        engine = _FakeEngine(database_url, echo)
        engines.append(engine)
        return engine

    def session_factory(engine: _FakeEngine) -> _FakeSession:
        session = _FakeSession(engine)
        sessions.append(session)
        return session

    def reconcile(
        session: _FakeSession,
        package: Any,
        *,
        actor: str,
        commit: bool,
        inject_failure_after_qa: int | None,
    ) -> _Result:
        reconcile_calls.append(
            {
                "session": session,
                "package": package,
                "actor": actor,
                "commit": commit,
                "inject_failure_after_qa": inject_failure_after_qa,
            }
        )
        status = "already_applied" if len(reconcile_calls) == 3 else "applied"
        return _valid_result(case, status=status)

    common = {
        "manifest_loader": _manifest_loader(case, loader_calls),
        "engine_factory": engine_factory,
        "session_factory": session_factory,
        "reconcile": reconcile,
    }
    clone_report = runner.run_invocation(
        _arguments(
            case,
            target_role=runner.TARGET_ROLE_DISPOSABLE_CLONE,
            mode=runner.MODE_REHEARSAL_SUCCESS,
            database_url=CLONE_DATABASE_URL,
        ),
        **common,
    )
    active_report = runner.run_invocation(_arguments(case), **common)
    repeated_active_report = runner.run_invocation(_arguments(case), **common)

    assert [engine.database_url for engine in engines] == [
        CLONE_DATABASE_URL,
        ACTIVE_DATABASE_URL,
        ACTIVE_DATABASE_URL,
    ]
    assert all(engine.echo is False for engine in engines)
    assert all(engine.dispose_count == 1 for engine in engines)
    assert all(session.enter_count == 1 for session in sessions)
    assert all(session.exit_count == 1 for session in sessions)
    assert [session.commit_count for session in sessions] == [1, 1, 0]
    assert [session.rollback_count for session in sessions] == [0, 0, 1]
    assert [call["inject_failure_after_qa"] for call in reconcile_calls] == [
        None,
        None,
        None,
    ]
    assert all(call["actor"] == ACTOR for call in reconcile_calls)
    assert all(call["commit"] is False for call in reconcile_calls)
    assert len(loader_calls) == 3
    assert all(
        call
        == {
            "manifest_path": case.manifest_path,
            "manifest_sha256": case.manifest_sha256,
            "ruleset_path": case.ruleset_path,
            "ruleset_sha256": case.ruleset_sha256,
            "source_root": case.source_root.resolve(),
        }
        for call in loader_calls
    )

    for report, role, mode, evidence_sha in (
        (
            clone_report,
            runner.TARGET_ROLE_DISPOSABLE_CLONE,
            runner.MODE_REHEARSAL_SUCCESS,
            None,
        ),
        (
            active_report,
            runner.TARGET_ROLE_ACTIVE_LOCAL,
            runner.MODE_ACTIVE_APPLY,
            case.evidence_sha256,
        ),
    ):
        assert report["target_role"] == role
        assert report["mode"] == mode
        assert report["outcome"] == "applied"
        assert report["transaction_outcome"] == "committed"
        assert report["rehearsal_evidence_sha256"] == evidence_sha
        result = report["reconciliation_result"]
        assert set(result) == runner._RESULT_KEYS
        assert result["status"] == "applied"
        assert result["manifest_file_sha256"] == case.manifest_sha256
        assert result["ruleset_payload_sha256"] == (
            runner.canonical_json_sha256(case.ruleset)
        )
        assert result["website_id"] == WEBSITE_ID
        assert result["site_plan_id"] == SITE_PLAN_ID
        assert result["affected_page_count"] == 65
        assert len(result["page_results"]) == 65
        assert all(
            set(page_result) == runner._PAGE_RESULT_KEYS
            for page_result in result["page_results"]
        )
        assert [
            page_result["planned_page_id"]
            for page_result in result["page_results"]
        ] == list(range(1, 66))
        report_without_seal = dict(report)
        observed_report_sha = report_without_seal.pop("report_sha256")
        assert runner.canonical_json_sha256(report_without_seal) == (
            observed_report_sha
        )
        serialized = runner.canonical_json_bytes(report)
        assert b"secret" not in serialized
        assert report["forbidden_actions"] == runner.FORBIDDEN_ACTIONS

    assert clone_report["runner_sha256"] == active_report["runner_sha256"]
    assert clone_report["invocation_config_sha256"] == (
        active_report["invocation_config_sha256"]
    )
    assert clone_report["source_root_sha256"] == (
        active_report["source_root_sha256"]
    )
    assert clone_report["database_url_sha256"] != (
        active_report["database_url_sha256"]
    )
    assert repeated_active_report["outcome"] == "already_applied"
    assert repeated_active_report["transaction_outcome"] == "write_free_noop"
    assert repeated_active_report["rehearsal_evidence_sha256"] == (
        case.evidence_sha256
    )
    repeated_result = repeated_active_report["reconciliation_result"]
    assert set(repeated_result) == runner._RESULT_KEYS
    assert repeated_result["status"] == "already_applied"
    assert repeated_result["affected_page_count"] == 65
    assert repeated_result["page_results"] == []


def test_exact_active_success_commits_only_after_result_validation(
    tmp_path: Path,
) -> None:
    case = _build_case(tmp_path)
    sessions: list[_FakeSession] = []
    service_commit_values: list[bool] = []

    def session_factory(engine: _FakeEngine) -> _FakeSession:
        session = _FakeSession(engine)
        sessions.append(session)
        return session

    def reconcile(*_args: Any, **kwargs: Any) -> _Result:
        service_commit_values.append(kwargs["commit"])
        return _valid_result(case)

    report = runner.run_invocation(
        _arguments(case),
        manifest_loader=_manifest_loader(case, []),
        engine_factory=lambda url, *, echo: _FakeEngine(url, echo),
        session_factory=session_factory,
        reconcile=reconcile,
    )
    assert service_commit_values == [False]
    assert sessions[0].commit_count == 1
    assert sessions[0].rollback_count == 0
    assert report["outcome"] == "applied"
    assert report["transaction_outcome"] == "committed"
    assert report["rehearsal_evidence_sha256"] == case.evidence_sha256


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload.pop("public_copy_audit_fingerprint"),
            "unknown or incomplete contract",
        ),
        (
            lambda payload: payload.__setitem__(
                "appended_evidence_row_count", 194
            ),
            "evidence-row/head counts are not exact",
        ),
        (
            lambda payload: payload["page_results"][0].__setitem__(
                "planned_page_id", 2
            ),
            "contradicts its sealed binding",
        ),
        (
            lambda payload: payload["page_results"][1].__setitem__(
                "new_generated_page_revision_id",
                payload["page_results"][0]["new_generated_page_revision_id"],
            ),
            "duplicate or non-successor",
        ),
        (
            lambda payload: payload["page_results"][0].__setitem__(
                "new_composition_source_hash",
                payload["page_results"][0]["old_composition_source_hash"],
            ),
            "did not advance composition source identity",
        ),
    ],
    ids=["missing-key", "lying-count", "wrong-order", "duplicate-id", "old-source"],
)
def test_malformed_or_lying_applied_result_rolls_back_without_commit(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], Any],
    message: str,
) -> None:
    case = _build_case(tmp_path)
    sessions: list[_FakeSession] = []
    payload = asdict(_valid_result(case))
    mutate(payload)

    def session_factory(engine: _FakeEngine) -> _FakeSession:
        session = _FakeSession(engine)
        sessions.append(session)
        return session

    with pytest.raises(runner.PublicCopyRunnerExecutionError) as exc_info:
        runner.run_invocation(
            _arguments(case),
            manifest_loader=_manifest_loader(case, []),
            engine_factory=lambda url, *, echo: _FakeEngine(url, echo),
            session_factory=session_factory,
            reconcile=lambda *_args, **_kwargs: payload,
        )
    assert message in _root_cause_message(exc_info.value)
    assert sessions[0].commit_count == 0
    assert sessions[0].rollback_count == 1


def test_lying_already_applied_result_rolls_back_without_commit(
    tmp_path: Path,
) -> None:
    case = _build_case(tmp_path)
    sessions: list[_FakeSession] = []
    payload = asdict(_valid_result(case, status="already_applied"))
    payload["page_results"] = [dict(_valid_page_results(case)[0])]

    def session_factory(engine: _FakeEngine) -> _FakeSession:
        session = _FakeSession(engine)
        sessions.append(session)
        return session

    with pytest.raises(runner.PublicCopyRunnerExecutionError) as exc_info:
        runner.run_invocation(
            _arguments(case),
            manifest_loader=_manifest_loader(case, []),
            engine_factory=lambda url, *, echo: _FakeEngine(url, echo),
            session_factory=session_factory,
            reconcile=lambda *_args, **_kwargs: payload,
        )
    assert "Write-free reconciliation replay returned page mutations" in (
        _root_cause_message(exc_info.value)
    )
    assert sessions[0].commit_count == 0
    assert sessions[0].rollback_count == 1


def test_injected_clone_failure_is_rolled_back_and_reported(
    tmp_path: Path,
) -> None:
    case = _build_case(tmp_path)
    engines: list[_FakeEngine] = []
    sessions: list[_FakeSession] = []
    observed_calls: list[dict[str, Any]] = []

    def engine_factory(database_url: str, *, echo: bool) -> _FakeEngine:
        engine = _FakeEngine(database_url, echo)
        engines.append(engine)
        return engine

    def session_factory(engine: _FakeEngine) -> _FakeSession:
        session = _FakeSession(engine)
        sessions.append(session)
        return session

    def reconcile(*_args: Any, **kwargs: Any) -> None:
        observed_calls.append(kwargs)
        raise PublicCopyReconciliationInjectedFailure(
            "Injected public-copy reconciliation failure after QA 33."
        )

    report = runner.run_invocation(
        _arguments(
            case,
            target_role=runner.TARGET_ROLE_DISPOSABLE_CLONE,
            mode=runner.MODE_REHEARSAL_INJECTED_FAILURE,
            database_url=CLONE_DATABASE_URL,
        ),
        manifest_loader=_manifest_loader(case, []),
        engine_factory=engine_factory,
        session_factory=session_factory,
        reconcile=reconcile,
    )

    assert observed_calls[0]["inject_failure_after_qa"] == 33
    assert observed_calls[0]["commit"] is False
    assert sessions[0].commit_count == 0
    assert sessions[0].rollback_count == 1
    assert engines[0].dispose_count == 1
    assert report["outcome"] == "injected_failure_rolled_back"
    assert report["transaction_outcome"] == "rolled_back"
    assert report["reconciliation_result"] is None
    assert report["rehearsal_evidence_sha256"] is None
    assert report["injected_failure"] == {
        "type": "PublicCopyReconciliationInjectedFailure",
        "message": "Injected public-copy reconciliation failure after QA 33.",
        "after_qa": 33,
    }


def test_configured_clone_injection_must_actually_fail(tmp_path: Path) -> None:
    case = _build_case(tmp_path)
    sessions: list[_FakeSession] = []

    def session_factory(engine: _FakeEngine) -> _FakeSession:
        session = _FakeSession(engine)
        sessions.append(session)
        return session

    with pytest.raises(
        runner.PublicCopyRunnerExecutionError,
        match="transaction was rolled back",
    ) as exc_info:
        runner.run_invocation(
            _arguments(
                case,
                target_role=runner.TARGET_ROLE_DISPOSABLE_CLONE,
                mode=runner.MODE_REHEARSAL_INJECTED_FAILURE,
                database_url=CLONE_DATABASE_URL,
            ),
            manifest_loader=_manifest_loader(case, []),
            engine_factory=lambda url, *, echo: _FakeEngine(url, echo),
            session_factory=session_factory,
            reconcile=lambda *_args, **_kwargs: _valid_result(case),
        )
    assert "injection did not occur" in _root_cause_message(exc_info.value)
    assert sessions[0].commit_count == 0
    assert sessions[0].rollback_count == 1


def test_unexpected_injected_exception_is_not_accepted_as_clone_success(
    tmp_path: Path,
) -> None:
    case = _build_case(tmp_path)
    sessions: list[_FakeSession] = []

    def session_factory(engine: _FakeEngine) -> _FakeSession:
        session = _FakeSession(engine)
        sessions.append(session)
        return session

    def reconcile(*_args: Any, **_kwargs: Any) -> None:
        raise PublicCopyReconciliationInjectedFailure("unexpected")

    with pytest.raises(
        runner.PublicCopyRunnerExecutionError,
        match="outside clone rehearsal mode",
    ):
        runner.run_invocation(
            _arguments(
                case,
                target_role=runner.TARGET_ROLE_DISPOSABLE_CLONE,
                mode=runner.MODE_REHEARSAL_SUCCESS,
                database_url=CLONE_DATABASE_URL,
            ),
            manifest_loader=_manifest_loader(case, []),
            engine_factory=lambda url, *, echo: _FakeEngine(url, echo),
            session_factory=session_factory,
            reconcile=reconcile,
        )
    assert sessions[0].commit_count == 0
    assert sessions[0].rollback_count == 1


def test_runner_rejects_a_target_not_at_exact_0048_before_reconciliation(
    tmp_path: Path,
) -> None:
    case = _build_case(tmp_path)
    sessions: list[_FakeSession] = []
    reconcile_called = False

    def session_factory(engine: _FakeEngine) -> _FakeSession:
        session = _FakeSession(engine)
        sessions.append(session)
        return session

    def reconcile(*_args: Any, **_kwargs: Any) -> None:
        nonlocal reconcile_called
        reconcile_called = True

    with pytest.raises(
        runner.PublicCopyRunnerExecutionError,
        match="transaction was rolled back",
    ):
        runner.run_invocation(
            _arguments(case),
            manifest_loader=_manifest_loader(case, []),
            engine_factory=lambda url, *, echo: _FakeEngine(url, echo),
            session_factory=session_factory,
            reconcile=reconcile,
            revision_reader=lambda _session: "20260817_0047",
        )
    assert reconcile_called is False
    assert sessions[0].commit_count == 0
    assert sessions[0].rollback_count == 1
