from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, select

from app.db.backup import (
    BackupValidationError,
    _prepare_page_composition_history_evidence,
    restore_backup,
)
from app.db.page_composition_history_evidence import (
    EVIDENCE_RECORDED_BY,
    EVIDENCE_RECORD_SOURCE,
    EVIDENCE_SCHEMA,
    EVIDENCE_VERSION,
    PageCompositionHistoryEvidenceError,
    load_page_composition_history_evidence,
    stable_qa_result_projection,
)
from app.models import (
    GeneratedPage,
    GeneratedPageQAResult,
    PageComposition,
    PageCompositionRevision,
    PlannedPage,
    SitePlan,
    Website,
)
from app.services.page_composition_history import (
    canonical_payload_hash,
    composition_revision_hash,
    create_initial_composition_revision,
)
from app.services.page_qa import qa_result_record_hash
from test_page_composition_history_backup import (
    _append_successor,
    _export_payload,
    _rehash_revision,
    _write,
)
from test_qa_backup import _engine, _seed_filler_scope


def _seal(tmp_path: Path, evidence: dict, name: str = "history-evidence.json") -> tuple[Path, str]:
    path = _write(tmp_path, evidence, name)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _seal_raw(tmp_path: Path, raw: bytes, name: str) -> tuple[Path, str]:
    path = tmp_path / name
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def _rehash_qa_result(record: dict) -> None:
    values = deepcopy(record)
    values["evaluated_at"] = datetime.fromisoformat(values["evaluated_at"])
    record["result_hash"] = qa_result_record_hash(values)


def _rehash_evidence_record(record: dict) -> None:
    record["record_hash"] = canonical_payload_hash(
        {
            "revision": record["revision"],
            "qa_results": sorted(
                record["qa_results"], key=lambda value: value["id"]
            ),
        }
    )


def _rebind_current_qa(payload: dict, *, successor: dict, current_id: int) -> None:
    current = next(
        record
        for record in payload["data"]["generated_page_qa_results"]
        if record["id"] == current_id
    )
    current["composition_version"] = successor["composition_version"]
    current["composition_source_hash"] = successor["source_hash"]
    _rehash_qa_result(current)

    for projection in (
        payload["data"]["generated_pages"][0]["qa_result"],
        payload["data"]["approval_audits"][0]["qa_result_snapshot"],
    ):
        projection["composition_version"] = current["composition_version"]
        projection["composition_source_hash"] = current[
            "composition_source_hash"
        ]
        projection["result_hash"] = current["result_hash"]


def _legacy_backup_and_evidence(
    tmp_path: Path,
) -> tuple[dict, dict, dict[str, object], dict]:
    payload, identities = _export_payload(tmp_path)
    composition = payload["data"]["page_compositions"][0]
    root_revision = payload["data"]["page_composition_revisions"][0]
    scoped_snapshot = {
        **root_revision["source_snapshot"],
        "website_id": root_revision["website_id"],
        "site_plan_id": root_revision["site_plan_id"],
        "planned_page_id": root_revision["planned_page_id"],
        "generated_page_id": root_revision["generated_page_id"],
    }
    scoped_source_hash = canonical_payload_hash(scoped_snapshot)
    composition["source_snapshot"] = deepcopy(scoped_snapshot)
    composition["source_hash"] = scoped_source_hash
    root_revision["source_snapshot"] = deepcopy(scoped_snapshot)
    root_revision["source_hash"] = scoped_source_hash
    root_revision["generated_at"] = composition["generated_at"]
    root_revision["recorded_at"] = composition["generated_at"]
    _rehash_revision(root_revision)
    for qa_result in payload["data"]["generated_page_qa_results"]:
        if qa_result.get("page_composition_id") == composition["id"]:
            qa_result["composition_source_hash"] = scoped_source_hash
            _rehash_qa_result(qa_result)
    current_qa = next(
        qa_result
        for qa_result in payload["data"]["generated_page_qa_results"]
        if qa_result.get("lifecycle_status") == "current"
    )
    for projection in (
        payload["data"]["generated_pages"][0]["qa_result"],
        payload["data"]["approval_audits"][0]["qa_result_snapshot"],
    ):
        projection["composition_source_hash"] = scoped_source_hash
        projection["result_hash"] = current_qa["result_hash"]

    historical = deepcopy(root_revision)

    source_payload = deepcopy(payload)
    source_payload["metadata"]["version"] = "0.58"
    source_payload["metadata"]["table_counts"].pop(
        "page_composition_revisions"
    )
    source_payload["data"].pop("page_composition_revisions")
    source_artifact_path = _write(
        tmp_path,
        source_payload,
        "source-artifact-058.json",
    )
    source_bytes = source_artifact_path.read_bytes()

    successor = _append_successor(payload, update_head=True)
    _rebind_current_qa(
        payload,
        successor=successor,
        current_id=int(identities["current_id"]),
    )
    complete_059 = deepcopy(payload)

    historical.pop("id")
    historical["recorded_at"] = historical["generated_at"]
    historical["recorded_by"] = EVIDENCE_RECORDED_BY
    historical["record_source"] = EVIDENCE_RECORD_SOURCE
    _rehash_revision(historical)

    required_qa = next(
        record
        for record in payload["data"]["generated_page_qa_results"]
        if record["id"] == identities["previous_id"]
    )
    evidence_record = {
        "revision": historical,
        "qa_results": [stable_qa_result_projection(required_qa)],
        "record_hash": "",
    }
    _rehash_evidence_record(evidence_record)

    payload["metadata"]["version"] = "0.58"
    payload["metadata"]["table_counts"].pop("page_composition_revisions")
    payload["data"].pop("page_composition_revisions")
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "version": EVIDENCE_VERSION,
        "created_at": payload["metadata"]["created_at"],
        "source_artifact": {
            "app": "Project Atlas",
            "backup_version": "0.58",
            "created_at": payload["metadata"]["created_at"],
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "size_bytes": len(source_bytes),
        },
        "records": [evidence_record],
    }
    return payload, evidence, identities, complete_059


def test_backup_058_recovery_sidecar_restores_exact_root_successor_and_qa_bindings(
    tmp_path: Path,
) -> None:
    payload, evidence, identities, _ = _legacy_backup_and_evidence(tmp_path)
    backup_path = _write(tmp_path, payload, "legacy-history-gap-058.json")
    evidence_path, evidence_sha256 = _seal(tmp_path, evidence)
    source_artifact_path = tmp_path / "source-artifact-058.json"
    source_payload = json.loads(source_artifact_path.read_text(encoding="utf-8"))
    source_composition = source_payload["data"]["page_compositions"][0]
    evidence_revision = evidence["records"][0]["revision"]
    assert evidence["source_artifact"]["backup_version"] == "0.58"
    assert evidence["source_artifact"]["sha256"] == hashlib.sha256(
        source_artifact_path.read_bytes()
    ).hexdigest()
    assert evidence["source_artifact"]["size_bytes"] == (
        source_artifact_path.stat().st_size
    )
    assert evidence["source_artifact"]["sha256"] != hashlib.sha256(
        backup_path.read_bytes()
    ).hexdigest()
    assert source_payload["metadata"]["version"] == "0.58"
    for source_field, revision_field in (
        ("id", "page_composition_id"),
        ("website_id", "website_id"),
        ("site_plan_id", "site_plan_id"),
        ("planned_page_id", "planned_page_id"),
        ("generated_page_id", "generated_page_id"),
        ("composition_version", "composition_version"),
        ("generated_components", "generated_components"),
        ("operator_decisions", "operator_decisions"),
        ("source_snapshot", "source_snapshot"),
        ("source_hash", "source_hash"),
        ("generated_at", "generated_at"),
        ("decided_by", "decided_by"),
        ("decided_at", "decided_at"),
    ):
        assert source_composition[source_field] == evidence_revision[revision_field]

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        with pytest.raises(
            BackupValidationError,
            match="does not resolve an exact restored Page Composition revision",
        ):
            restore_backup(session, backup_path)
        assert list(session.exec(select(PageCompositionRevision)).all()) == []

        restore_backup(
            session,
            backup_path,
            page_composition_history_evidence_path=evidence_path,
            page_composition_history_evidence_sha256=evidence_sha256,
        )
        restore_backup(
            session,
            backup_path,
            page_composition_history_evidence_path=evidence_path,
            page_composition_history_evidence_sha256=evidence_sha256,
        )

        history = list(
            session.exec(
                select(PageCompositionRevision).order_by(
                    PageCompositionRevision.composition_version
                )
            ).all()
        )
        assert len(history) == 2
        root, successor = history
        assert root.lineage_kind == "legacy_root"
        assert root.supersedes_revision_id is None
        assert root.recorded_at == root.generated_at
        assert root.recorded_by == EVIDENCE_RECORDED_BY
        assert root.record_source == EVIDENCE_RECORD_SOURCE
        assert successor.lineage_kind == "successor"
        assert successor.composition_version == root.composition_version + 1
        assert successor.supersedes_revision_id == root.id
        assert successor.supersedes_revision_hash == root.revision_hash
        assert successor.recorded_at >= root.recorded_at

        previous = session.get(
            GeneratedPageQAResult, int(identities["previous_id"])
        )
        current = session.get(
            GeneratedPageQAResult, int(identities["current_id"])
        )
        assert previous is not None and current is not None
        assert (
            previous.page_composition_id,
            previous.composition_version,
            previous.composition_source_hash,
        ) == (
            root.page_composition_id,
            root.composition_version,
            root.source_hash,
        )
        assert (
            current.page_composition_id,
            current.composition_version,
            current.composition_source_hash,
        ) == (
            successor.page_composition_id,
            successor.composition_version,
            successor.source_hash,
        )


def test_backup_history_evidence_requires_explicit_path_and_sha_together(
    tmp_path: Path,
) -> None:
    payload, evidence, _, _ = _legacy_backup_and_evidence(tmp_path)
    backup_path = _write(tmp_path, payload, "legacy-history-gap-058.json")
    evidence_path, evidence_sha256 = _seal(tmp_path, evidence)
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        with pytest.raises(BackupValidationError, match="supplied together"):
            restore_backup(
                session,
                backup_path,
                page_composition_history_evidence_path=evidence_path,
            )
        with pytest.raises(BackupValidationError, match="supplied together"):
            restore_backup(
                session,
                backup_path,
                page_composition_history_evidence_sha256=evidence_sha256,
            )


@pytest.mark.parametrize(
    "tamper",
    (
        "caller_sha",
        "revision_payload",
        "qa_substitution",
        "generated_revision_substitution",
        "cross_scope",
        "duplicate",
        "extra",
        "missing_qa",
    ),
)
def test_backup_058_recovery_sidecar_rejects_tamper_substitution_and_unused_records(
    tmp_path: Path,
    tamper: str,
) -> None:
    payload, evidence, _, _ = _legacy_backup_and_evidence(tmp_path)
    record = evidence["records"][0]
    if tamper == "revision_payload":
        record["revision"]["source_snapshot"]["tampered"] = True
    elif tamper == "qa_substitution":
        record["qa_results"][0]["id"] += 1000
        _rehash_evidence_record(record)
    elif tamper == "generated_revision_substitution":
        record["revision"]["generated_page_revision_id"] += 1000
        record["qa_results"][0]["latest_generated_page_revision_id"] += 1000
        _rehash_revision(record["revision"])
        _rehash_qa_result(record["qa_results"][0])
        _rehash_evidence_record(record)
    elif tamper == "cross_scope":
        record["revision"]["planned_page_id"] += 1000
        record["qa_results"][0]["planned_page_id"] += 1000
        _rehash_revision(record["revision"])
        _rehash_qa_result(record["qa_results"][0])
        _rehash_evidence_record(record)
    elif tamper == "duplicate":
        evidence["records"].append(deepcopy(record))
    elif tamper == "extra":
        extra = deepcopy(record)
        extra["revision"]["page_composition_id"] += 1000
        extra["qa_results"][0]["id"] += 1000
        extra["qa_results"][0]["page_composition_id"] += 1000
        _rehash_revision(extra["revision"])
        _rehash_qa_result(extra["qa_results"][0])
        _rehash_evidence_record(extra)
        evidence["records"].append(extra)
    elif tamper == "missing_qa":
        record["qa_results"] = []
        _rehash_evidence_record(record)

    backup_path = _write(tmp_path, payload, f"legacy-{tamper}-058.json")
    evidence_path, evidence_sha256 = _seal(
        tmp_path, evidence, f"history-evidence-{tamper}.json"
    )
    if tamper == "caller_sha":
        evidence_sha256 = "0" * 64

    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        with pytest.raises(BackupValidationError):
            restore_backup(
                session,
                backup_path,
                page_composition_history_evidence_path=evidence_path,
                page_composition_history_evidence_sha256=evidence_sha256,
            )
        assert list(session.exec(select(PageCompositionRevision)).all()) == []


def test_history_evidence_rejects_recursive_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    raw = b'{"outer":{"nested":{"identity":1,"identity":2}}}'
    evidence_path, evidence_sha256 = _seal_raw(
        tmp_path,
        raw,
        "recursive-duplicate.json",
    )

    with pytest.raises(
        PageCompositionHistoryEvidenceError,
        match="duplicate JSON key",
    ):
        load_page_composition_history_evidence(
            evidence_path,
            evidence_sha256,
        )


@pytest.mark.parametrize("constant", (b"NaN", b"Infinity", b"-Infinity"))
def test_history_evidence_rejects_non_finite_json_constants(
    tmp_path: Path,
    constant: bytes,
) -> None:
    raw = b'{"nested":{"value":' + constant + b"}}"
    evidence_path, evidence_sha256 = _seal_raw(
        tmp_path,
        raw,
        f"non-finite-{constant.decode('ascii').replace('-', 'negative-')}.json",
    )

    with pytest.raises(
        PageCompositionHistoryEvidenceError,
        match="invalid JSON constant",
    ):
        load_page_composition_history_evidence(
            evidence_path,
            evidence_sha256,
        )


@pytest.mark.parametrize(
    "tamper",
    (
        "schema",
        "version",
        "source_app",
        "source_version",
        "source_sha",
        "source_size",
        "source_future",
        "revision_provenance",
    ),
)
def test_history_evidence_rejects_invalid_schema_and_provenance(
    tmp_path: Path,
    tamper: str,
) -> None:
    _, evidence, _, _ = _legacy_backup_and_evidence(tmp_path)
    if tamper == "schema":
        evidence["schema"] = "unsupported-history-evidence"
    elif tamper == "version":
        evidence["version"] = "2"
    elif tamper == "source_app":
        evidence["source_artifact"]["app"] = "Different Application"
    elif tamper == "source_version":
        evidence["source_artifact"]["backup_version"] = "0.59"
    elif tamper == "source_sha":
        evidence["source_artifact"]["sha256"] = "A" * 64
    elif tamper == "source_size":
        evidence["source_artifact"]["size_bytes"] = 0
    elif tamper == "source_future":
        evidence["source_artifact"]["created_at"] = "2999-01-01T00:00:00+00:00"
    elif tamper == "revision_provenance":
        record = evidence["records"][0]
        record["revision"]["recorded_by"] = "atlas:substituted_recovery"
        _rehash_revision(record["revision"])
        _rehash_evidence_record(record)

    evidence_path, evidence_sha256 = _seal(
        tmp_path,
        evidence,
        f"invalid-{tamper}.json",
    )
    with pytest.raises(PageCompositionHistoryEvidenceError):
        load_page_composition_history_evidence(
            evidence_path,
            evidence_sha256,
        )


def test_history_evidence_rejects_direct_record_hash_tamper(
    tmp_path: Path,
) -> None:
    _, evidence, _, _ = _legacy_backup_and_evidence(tmp_path)
    evidence["records"][0]["record_hash"] = "0" * 64
    evidence_path, evidence_sha256 = _seal(
        tmp_path,
        evidence,
        "record-hash-tamper.json",
    )

    with pytest.raises(
        PageCompositionHistoryEvidenceError,
        match="record hash does not match",
    ):
        load_page_composition_history_evidence(
            evidence_path,
            evidence_sha256,
        )


def test_history_evidence_rejects_refingerprinted_nested_snapshot_cross_scope(
    tmp_path: Path,
) -> None:
    _, evidence, _, _ = _legacy_backup_and_evidence(tmp_path)
    record = evidence["records"][0]
    revision = record["revision"]
    revision["source_snapshot"]["planned_page_id"] += 1000
    revision["source_hash"] = canonical_payload_hash(revision["source_snapshot"])
    record["qa_results"][0]["composition_source_hash"] = revision["source_hash"]
    _rehash_revision(revision)
    _rehash_qa_result(record["qa_results"][0])
    _rehash_evidence_record(record)
    evidence_path, evidence_sha256 = _seal(
        tmp_path,
        evidence,
        "nested-snapshot-cross-scope.json",
    )

    with pytest.raises(
        PageCompositionHistoryEvidenceError,
        match="source snapshot crosses its exact scope",
    ):
        load_page_composition_history_evidence(
            evidence_path,
            evidence_sha256,
        )


@pytest.mark.parametrize(
    "tamper",
    (
        "non_string_actor",
        "untrimmed_actor",
        "empty_actor",
    ),
)
def test_history_evidence_rejects_malformed_decision_provenance(
    tmp_path: Path,
    tamper: str,
) -> None:
    _, evidence, _, _ = _legacy_backup_and_evidence(tmp_path)
    record = evidence["records"][0]
    revision = record["revision"]
    if tamper == "non_string_actor":
        revision["decided_by"] = 17
        revision["decided_at"] = revision["generated_at"]
    elif tamper == "untrimmed_actor":
        revision["decided_by"] = " recovery operator "
        revision["decided_at"] = revision["generated_at"]
    elif tamper == "empty_actor":
        revision["decided_by"] = ""
        revision["decided_at"] = revision["generated_at"]
    _rehash_revision(revision)
    _rehash_evidence_record(record)
    evidence_path, evidence_sha256 = _seal(
        tmp_path,
        evidence,
        f"decision-provenance-{tamper}.json",
    )

    with pytest.raises(
        PageCompositionHistoryEvidenceError,
        match="decision provenance is malformed",
    ):
        load_page_composition_history_evidence(
            evidence_path,
            evidence_sha256,
        )


@pytest.mark.parametrize(
    ("decided_by", "reuse_generated_at"),
    (
        ("x" * 256, False),
        ("recovery operator", False),
        (None, True),
    ),
)
def test_history_evidence_preserves_independently_nullable_decision_fields(
    tmp_path: Path,
    decided_by: str | None,
    reuse_generated_at: bool,
) -> None:
    _, evidence, _, _ = _legacy_backup_and_evidence(tmp_path)
    record = evidence["records"][0]
    revision = record["revision"]
    revision["decided_by"] = decided_by
    revision["decided_at"] = (
        revision["generated_at"] if reuse_generated_at else None
    )
    _rehash_revision(revision)
    _rehash_evidence_record(record)
    evidence_path, evidence_sha256 = _seal(
        tmp_path,
        evidence,
        "valid-independent-decision-fields.json",
    )

    loaded = load_page_composition_history_evidence(
        evidence_path,
        evidence_sha256,
    )
    assert loaded.records[0]["revision"]["decided_by"] == decided_by


@pytest.mark.parametrize(
    "field",
    ("passed_count", "warning_count", "failed_count"),
)
def test_history_evidence_rejects_boolean_qa_counts(
    tmp_path: Path,
    field: str,
) -> None:
    _, evidence, _, _ = _legacy_backup_and_evidence(tmp_path)
    record = evidence["records"][0]
    record["qa_results"][0][field] = True
    _rehash_qa_result(record["qa_results"][0])
    _rehash_evidence_record(record)
    evidence_path, evidence_sha256 = _seal(
        tmp_path,
        evidence,
        f"boolean-qa-{field}.json",
    )

    with pytest.raises(
        PageCompositionHistoryEvidenceError,
        match="QA counts are invalid",
    ):
        load_page_composition_history_evidence(
            evidence_path,
            evidence_sha256,
        )


@pytest.mark.parametrize(
    "field",
    (
        "qa_algorithm_key",
        "qa_algorithm_version",
        "qa_ruleset_key",
        "qa_ruleset_version",
    ),
)
def test_history_evidence_rejects_untrimmed_qa_provenance(
    tmp_path: Path,
    field: str,
) -> None:
    _, evidence, _, _ = _legacy_backup_and_evidence(tmp_path)
    record = evidence["records"][0]
    record["qa_results"][0][field] = (
        f" {record['qa_results'][0][field]} "
    )
    _rehash_qa_result(record["qa_results"][0])
    _rehash_evidence_record(record)
    evidence_path, evidence_sha256 = _seal(
        tmp_path,
        evidence,
        f"untrimmed-qa-{field}.json",
    )

    with pytest.raises(
        PageCompositionHistoryEvidenceError,
        match="QA provenance is malformed",
    ):
        load_page_composition_history_evidence(
            evidence_path,
            evidence_sha256,
        )


def test_backup_history_evidence_rejects_multiple_roots_for_one_composition(
    tmp_path: Path,
) -> None:
    payload, evidence, _, _ = _legacy_backup_and_evidence(tmp_path)
    alternate = deepcopy(evidence["records"][0])
    alternate_revision = alternate["revision"]
    alternate_revision["source_snapshot"]["alternate_recovered_root"] = True
    alternate_revision["source_hash"] = canonical_payload_hash(
        alternate_revision["source_snapshot"]
    )
    alternate_qa = alternate["qa_results"][0]
    alternate_qa["id"] += 1000
    alternate_qa["composition_source_hash"] = alternate_revision["source_hash"]
    _rehash_revision(alternate_revision)
    _rehash_qa_result(alternate_qa)
    _rehash_evidence_record(alternate)
    evidence["records"].append(alternate)
    evidence["records"].sort(
        key=lambda value: (
            value["revision"]["page_composition_id"],
            value["revision"]["composition_version"],
            value["revision"]["source_hash"],
        )
    )
    evidence_path, evidence_sha256 = _seal(
        tmp_path,
        evidence,
        "multiple-roots-one-composition.json",
    )

    with pytest.raises(
        BackupValidationError,
        match="more than one root for a composition",
    ):
        _prepare_page_composition_history_evidence(
            data=payload["data"],
            backup_version="0.58",
            evidence_path=evidence_path,
            evidence_sha256=evidence_sha256,
        )


def test_backup_058_recovery_sidecar_remaps_history_and_qa_non_identity_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, evidence, identities, _ = _legacy_backup_and_evidence(tmp_path)
    backup_path = _write(tmp_path, payload, "legacy-history-remap-058.json")
    evidence_path, evidence_sha256 = _seal(
        tmp_path,
        evidence,
        "history-evidence-remap.json",
    )

    monkeypatch.setattr(
        "app.services.site_connections.read_site_connection_plan",
        lambda *_args, **_kwargs: SimpleNamespace(ready=True),
    )

    def _leave_remapped_composition_unchanged(
        session: Session,
        site_plan_id: int,
        *,
        commit: bool,
    ) -> SimpleNamespace:
        assert commit is False
        compositions = list(
            session.exec(
                select(PageComposition).where(
                    PageComposition.site_plan_id == site_plan_id
                )
            ).all()
        )
        return SimpleNamespace(
            created=0,
            refreshed=0,
            unchanged=len(compositions),
            blocked=0,
            compositions=compositions,
        )

    monkeypatch.setattr(
        "app.services.page_composition.refresh_site_plan_compositions",
        _leave_remapped_composition_unchanged,
    )

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        _seed_filler_scope(session)
        filler_website = session.exec(
            select(Website).where(
                Website.domain == "existing-target.example.test"
            )
        ).one()
        filler_plan = session.exec(
            select(SitePlan).where(SitePlan.website_id == filler_website.id)
        ).one()
        filler_planned_page = session.exec(
            select(PlannedPage).where(
                PlannedPage.site_plan_id == filler_plan.id
            )
        ).one()
        filler_generated_page = session.exec(
            select(GeneratedPage).where(
                GeneratedPage.website_id == filler_website.id
            )
        ).one()
        filler_snapshot = {
            "draft_hash": "6" * 64,
            "website_id": filler_website.id,
            "site_plan_id": filler_plan.id,
            "planned_page_id": filler_planned_page.id,
            "generated_page_id": filler_generated_page.id,
        }
        filler_generated_at = datetime(2026, 8, 2, tzinfo=UTC)
        filler_composition = PageComposition(
            website_id=filler_website.id,
            site_plan_id=filler_plan.id,
            planned_page_id=filler_planned_page.id,
            generated_page_id=filler_generated_page.id,
            composition_version=1,
            generated_components=[],
            operator_decisions=[],
            source_snapshot=filler_snapshot,
            source_hash=canonical_payload_hash(filler_snapshot),
            status="current",
            generated_at=filler_generated_at,
        )
        session.add(filler_composition)
        session.flush()
        create_initial_composition_revision(
            session,
            filler_composition,
            recorded_at=filler_generated_at,
        )
        session.commit()
        restore_backup(
            session,
            backup_path,
            page_composition_history_evidence_path=evidence_path,
            page_composition_history_evidence_sha256=evidence_sha256,
        )

        website = session.exec(
            select(Website).where(Website.domain == "qa-backup.example.test")
        ).one()
        composition = session.exec(
            select(PageComposition).where(PageComposition.website_id == website.id)
        ).one()
        history = list(
            session.exec(
                select(PageCompositionRevision)
                .where(
                    PageCompositionRevision.page_composition_id == composition.id
                )
                .order_by(PageCompositionRevision.composition_version)
            ).all()
        )
        assert website.id != payload["data"]["websites"][0]["id"]
        assert composition.id != payload["data"]["page_compositions"][0]["id"]
        assert len(history) == 2
        root, successor = history
        assert root.revision_hash != evidence["records"][0]["revision"][
            "revision_hash"
        ]
        assert successor.supersedes_revision_id == root.id
        assert successor.supersedes_revision_hash == root.revision_hash

        restored_qa = list(
            session.exec(
                select(GeneratedPageQAResult).where(
                    GeneratedPageQAResult.page_composition_id == composition.id
                )
            ).all()
        )
        previous = next(
            result
            for result in restored_qa
            if result.composition_version == root.composition_version
        )
        current = next(
            result
            for result in restored_qa
            if result.composition_version == successor.composition_version
            and result.lifecycle_status == "current"
        )
        assert previous.id is not None
        assert previous.page_composition_id == root.page_composition_id
        assert previous.composition_source_hash == root.source_hash
        assert current.page_composition_id == successor.page_composition_id
        assert current.composition_source_hash == successor.source_hash
        assert int(identities["previous_id"]) != int(identities["current_id"])


def test_backup_059_rejects_legacy_history_evidence(
    tmp_path: Path,
) -> None:
    _, evidence, _, complete_059 = _legacy_backup_and_evidence(tmp_path)
    backup_path = _write(tmp_path, complete_059, "complete-history-059.json")
    evidence_path, evidence_sha256 = _seal(tmp_path, evidence)
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        with pytest.raises(BackupValidationError, match="cannot use legacy evidence"):
            restore_backup(
                session,
                backup_path,
                page_composition_history_evidence_path=evidence_path,
                page_composition_history_evidence_sha256=evidence_sha256,
            )
