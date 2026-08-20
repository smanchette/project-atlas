from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, select

from app.db.backup import (
    BackupValidationError,
    export_backup,
    load_backup,
    restore_backup,
)
from app.models import (
    GeneratedPageQAResult,
    PageComposition,
    PageCompositionRevision,
)
from app.services.page_composition_history import (
    advance_composition_revision,
    canonical_payload_hash,
    composition_content_hash,
    composition_revision_hash,
)
from test_qa_backup import _engine, _seed_qa_graph


def _write(tmp_path: Path, payload: dict, name: str) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _export_payload(tmp_path: Path) -> tuple[dict, dict[str, object]]:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        identities = _seed_qa_graph(session)
        composition = session.get(PageComposition, identities["composition_id"])
        assert composition is not None
        composition.status = "current"
        session.add(composition)
        session.commit()
        exported = export_backup(session, backup_dir=tmp_path)
    return (
        json.loads(Path(exported["path"]).read_text(encoding="utf-8")),
        identities,
    )


def _rehash_revision(record: dict) -> None:
    values = deepcopy(record)
    for field in ("generated_at", "recorded_at"):
        values[field] = datetime.fromisoformat(values[field].replace("Z", "+00:00"))
    if values.get("decided_at") is not None:
        values["decided_at"] = datetime.fromisoformat(
            values["decided_at"].replace("Z", "+00:00")
        )
    record["revision_hash"] = composition_revision_hash(values)


def _append_successor(payload: dict, *, update_head: bool) -> dict:
    root = payload["data"]["page_composition_revisions"][0]
    successor = deepcopy(root)
    successor["id"] = max(
        item["id"] for item in payload["data"]["page_composition_revisions"]
    ) + 1
    successor["composition_version"] = root["composition_version"] + 1
    successor["supersedes_revision_id"] = root["id"]
    successor["supersedes_revision_hash"] = root["revision_hash"]
    successor["lineage_kind"] = "successor"
    successor["source_snapshot"] = {
        **successor["source_snapshot"],
        "history_test_successor": True,
    }
    successor["source_hash"] = canonical_payload_hash(
        successor["source_snapshot"]
    )
    successor["content_hash"] = composition_content_hash(
        successor["source_snapshot"]
    )
    generated_at = datetime.fromisoformat(successor["generated_at"])
    recorded_at = datetime.fromisoformat(successor["recorded_at"])
    successor["generated_at"] = (generated_at + timedelta(seconds=1)).isoformat()
    successor["recorded_at"] = (recorded_at + timedelta(seconds=1)).isoformat()
    _rehash_revision(successor)
    payload["data"]["page_composition_revisions"].append(successor)
    payload["metadata"]["table_counts"]["page_composition_revisions"] += 1
    if update_head:
        current = payload["data"]["page_compositions"][0]
        for field in (
            "composition_version",
            "generated_components",
            "operator_decisions",
            "source_snapshot",
            "source_hash",
            "generated_at",
            "decided_by",
            "decided_at",
        ):
            current[field] = deepcopy(successor[field])
    return successor


def test_backup_059_clean_restore_replays_exact_history_and_qa_tuple(
    tmp_path: Path,
) -> None:
    payload, identities = _export_payload(tmp_path)
    path = _write(tmp_path, payload, "history-059.json")
    source_history = payload["data"]["page_composition_revisions"]

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, path)
        restore_backup(session, path)
        history = list(
            session.exec(
                select(PageCompositionRevision).order_by(
                    PageCompositionRevision.composition_version
                )
            ).all()
        )
        assert len(history) == len(source_history) == 1
        assert history[0].id == source_history[0]["id"]
        assert history[0].revision_hash == source_history[0]["revision_hash"]
        composition = session.get(PageComposition, identities["composition_id"])
        qa = session.get(GeneratedPageQAResult, identities["current_id"])
        assert composition is not None and qa is not None
        assert (
            composition.id,
            composition.composition_version,
            composition.source_hash,
        ) == (
            history[0].page_composition_id,
            history[0].composition_version,
            history[0].source_hash,
        )
        assert (
            qa.page_composition_id,
            qa.composition_version,
            qa.composition_source_hash,
        ) == (
            history[0].page_composition_id,
            history[0].composition_version,
            history[0].source_hash,
        )


def test_backup_058_restore_synthesizes_one_deterministic_legacy_root(
    tmp_path: Path,
) -> None:
    payload, identities = _export_payload(tmp_path)
    payload["metadata"]["version"] = "0.58"
    payload["metadata"]["table_counts"].pop("page_composition_revisions")
    payload["data"].pop("page_composition_revisions")
    path = _write(tmp_path, payload, "legacy-058.json")

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, path)
        first = session.exec(select(PageCompositionRevision)).one()
        first_identity = (
            first.id,
            first.revision_hash,
            first.recorded_at,
            first.recorded_by,
            first.record_source,
        )
        restore_backup(session, path)
        roots = list(session.exec(select(PageCompositionRevision)).all())
        assert len(roots) == 1
        root = roots[0]
        assert root.lineage_kind == "legacy_root"
        assert root.composition_version == 2
        assert root.supersedes_revision_id is None
        assert root.recorded_at == root.generated_at
        assert (
            root.id,
            root.revision_hash,
            root.recorded_at,
            root.recorded_by,
            root.record_source,
        ) == first_identity
        qa = session.get(GeneratedPageQAResult, identities["current_id"])
        assert qa is not None
        assert (
            qa.page_composition_id,
            qa.composition_version,
            qa.composition_source_hash,
        ) == (
            root.page_composition_id,
            root.composition_version,
            root.source_hash,
        )


@pytest.mark.parametrize(
    "tamper",
    (
        "refingerprinted_tip_payload",
        "refingerprinted_tip_and_head",
        "refingerprinted_predecessor",
        "disconnected_root",
        "successor_beyond_head",
    ),
)
def test_backup_059_rejects_refingerprinted_or_disconnected_history(
    tmp_path: Path,
    tamper: str,
) -> None:
    payload, _ = _export_payload(tmp_path)
    root = payload["data"]["page_composition_revisions"][0]
    if tamper == "refingerprinted_tip_payload":
        root["source_snapshot"]["tampered"] = True
        root["source_hash"] = canonical_payload_hash(root["source_snapshot"])
        _rehash_revision(root)
    elif tamper == "refingerprinted_tip_and_head":
        root["source_snapshot"]["tampered"] = True
        root["source_hash"] = canonical_payload_hash(root["source_snapshot"])
        _rehash_revision(root)
        current = payload["data"]["page_compositions"][0]
        current["source_snapshot"] = deepcopy(root["source_snapshot"])
        current["source_hash"] = root["source_hash"]
    elif tamper == "refingerprinted_predecessor":
        _append_successor(payload, update_head=True)
        root["source_snapshot"]["tampered"] = True
        root["source_hash"] = canonical_payload_hash(root["source_snapshot"])
        _rehash_revision(root)
    elif tamper == "disconnected_root":
        disconnected = deepcopy(root)
        disconnected["id"] += 1000
        disconnected["composition_version"] += 1000
        _rehash_revision(disconnected)
        payload["data"]["page_composition_revisions"].append(disconnected)
        payload["metadata"]["table_counts"]["page_composition_revisions"] += 1
    else:
        _append_successor(payload, update_head=False)

    path = _write(tmp_path, payload, f"history-{tamper}.json")
    with pytest.raises(BackupValidationError):
        load_backup(path)


@pytest.mark.parametrize(
    "tamper",
    ("null_generated_revision", "substituted_older_revision", "cross_page_revision"),
)
def test_backup_059_requires_exact_latest_generated_revision_anchor(
    tmp_path: Path,
    tamper: str,
) -> None:
    payload, _ = _export_payload(tmp_path)
    history = payload["data"]["page_composition_revisions"][0]
    original_revision = payload["data"]["page_revisions"][0]
    if tamper == "null_generated_revision":
        history["generated_page_revision_id"] = None
    elif tamper == "substituted_older_revision":
        older = deepcopy(original_revision)
        older["id"] += 1000
        created_at = datetime.fromisoformat(older["created_at"])
        older["created_at"] = (created_at - timedelta(seconds=1)).isoformat()
        payload["data"]["page_revisions"].append(older)
        payload["metadata"]["table_counts"]["page_revisions"] += 1
        history["generated_page_revision_id"] = older["id"]
    else:
        cross_page = deepcopy(payload["data"]["generated_pages"][0])
        cross_page["id"] += 1000
        cross_page["page_slug"] = f"{cross_page['page_slug']}-cross"
        cross_page["page_title"] = f"{cross_page['page_title']} Cross"
        cross_page["qa_status"] = "not_run"
        cross_page["qa_checked_at"] = None
        cross_page["qa_result"] = None
        payload["data"]["generated_pages"].append(cross_page)
        payload["metadata"]["table_counts"]["generated_pages"] += 1
        cross_revision = deepcopy(original_revision)
        cross_revision["id"] += 2000
        cross_revision["generated_page_id"] = cross_page["id"]
        payload["data"]["page_revisions"].append(cross_revision)
        payload["metadata"]["table_counts"]["page_revisions"] += 1
        history["generated_page_revision_id"] = cross_revision["id"]
    _rehash_revision(history)

    path = _write(tmp_path, payload, f"history-{tamper}.json")
    with pytest.raises(BackupValidationError):
        load_backup(path)


def test_backup_059_generated_revision_anchor_uses_derivation_time(
    tmp_path: Path,
) -> None:
    payload, _ = _export_payload(tmp_path)
    history = payload["data"]["page_composition_revisions"][0]
    generated_at = datetime.fromisoformat(history["generated_at"])
    history["recorded_at"] = (generated_at + timedelta(seconds=10)).isoformat()
    later = deepcopy(payload["data"]["page_revisions"][0])
    later["id"] += 1000
    later["created_at"] = (generated_at + timedelta(seconds=5)).isoformat()
    later["draft_hash_before"] = later["draft_hash_after"]
    later["draft_hash_after"] = "2" * 64
    payload["data"]["page_revisions"].append(later)
    payload["metadata"]["table_counts"]["page_revisions"] += 1
    _rehash_revision(history)

    path = _write(tmp_path, payload, "history-derivation-time-anchor.json")
    loaded = load_backup(path)
    assert loaded["data"]["page_composition_revisions"][0][
        "generated_page_revision_id"
    ] != later["id"]


def test_backup_059_rejects_newer_target_history_without_committed_mutation(
    tmp_path: Path,
) -> None:
    payload, identities = _export_payload(tmp_path)
    path = _write(tmp_path, payload, "history-target-newer.json")
    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, path)
        composition = session.get(PageComposition, identities["composition_id"])
        assert composition is not None
        snapshot = {**composition.source_snapshot, "target_newer": True}
        successor = advance_composition_revision(
            session,
            composition,
            generated_components=composition.generated_components,
            operator_decisions=composition.operator_decisions,
            source_snapshot=snapshot,
            source_hash=canonical_payload_hash(snapshot),
            generated_at=composition.generated_at + timedelta(seconds=1),
            decided_by=composition.decided_by,
            decided_at=composition.decided_at,
            recorded_at=composition.generated_at + timedelta(seconds=1),
            recorded_by="Target Operator",
            record_source="target_newer_test",
        )
        session.commit()
        newer_identity = (
            composition.composition_version,
            composition.source_hash,
            successor.revision_hash,
        )
        with pytest.raises(BackupValidationError, match="newer immutable revisions"):
            restore_backup(session, path)
        session.refresh(composition)
        assert (
            composition.composition_version,
            composition.source_hash,
            successor.revision_hash,
        ) == newer_identity
        assert len(list(session.exec(select(PageCompositionRevision)).all())) == 2


def test_backup_059_export_before_history_migration_fails_cleanly(
    tmp_path: Path,
) -> None:
    engine = _engine()
    with Session(engine) as session:
        with pytest.raises(
            BackupValidationError,
            match="requires the Page Composition history migration",
        ):
            export_backup(session, backup_dir=tmp_path)
