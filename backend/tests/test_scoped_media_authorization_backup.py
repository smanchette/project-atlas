from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, select

from app.db.backup import (
    BACKUP_VERSION,
    BackupValidationError,
    export_backup,
    load_backup,
    restore_backup,
)
from app.models import (
    ImageMetadata,
    PageComposition,
    PageImageAssignment,
    PlannedPageMediaRequirement,
    ScopedMediaAuthorization,
)
from app.schemas.scoped_media_authorizations import (
    scoped_media_approval_fingerprint,
    scoped_media_authorization_fingerprint,
)
from test_page_media_planning_backup import _engine, _hash, _scope, _seed_governed_graph


def _seed_authorization_history(session: Session) -> tuple[int, int]:
    requirement = session.exec(
        select(PlannedPageMediaRequirement)
        .where(PlannedPageMediaRequirement.lifecycle_status == "active")
        .order_by(PlannedPageMediaRequirement.version.desc())
    ).first()
    asset = session.exec(
        select(ImageMetadata)
        .where(ImageMetadata.governance_status == "approved")
        .order_by(ImageMetadata.media_version.desc())
    ).first()
    assignment = session.exec(
        select(PageImageAssignment)
        .where(PageImageAssignment.status == "active")
        .order_by(PageImageAssignment.assignment_version.desc())
    ).first()
    assert requirement is not None
    assert asset is not None
    assert assignment is not None
    assert asset.approved_at is not None
    asset.usage_authorization_mode = "scoped_required"
    asset.required_authorization_terms = ["no_reuse"]
    session.add(asset)
    approval_values = {
        "image_metadata_id": asset.id,
        "asset_website_id": asset.website_id,
        "asset_business_id": asset.business_id,
        "media_version": asset.media_version,
        "asset_checksum_sha256": asset.checksum_sha256,
        "approval_version": asset.approval_version,
        "asset_approved_by": asset.approved_by,
        "asset_approved_at": asset.approved_at,
        "usage_authorization_mode": asset.usage_authorization_mode,
        "required_authorization_terms": asset.required_authorization_terms,
    }
    approval_fingerprint = scoped_media_approval_fingerprint(approval_values)
    base = {
        "website_id": requirement.website_id,
        "site_plan_id": requirement.site_plan_id,
        "planned_page_id": requirement.planned_page_id,
        "generated_page_id": assignment.generated_page_id,
        "media_requirement_id": requirement.id,
        "requirement_version": requirement.version,
        "placement_key": requirement.placement_key,
        "placement_contract_version": requirement.contract_version,
        "image_metadata_id": asset.id,
        "media_version": asset.media_version,
        "asset_checksum_sha256": asset.checksum_sha256,
        "approval_version": asset.approval_version,
        "asset_approved_by": asset.approved_by,
        "asset_approved_at": asset.approved_at,
        "approval_fingerprint": approval_fingerprint,
        "reuse_policy": "requirement_only",
        "authorization_terms": ["no_reuse", "requirement_only_usage"],
        "authorized_by": "Scoped Backup Operator",
        "authorization_rationale": "Exact Page 41-style governed media use.",
    }
    candidate_values = {
        **base,
        "page_image_assignment_id": None,
        "assignment_version": None,
        "authorized_at": asset.approved_at + timedelta(minutes=1),
        "authorization_version": 1,
        "lifecycle_status": "superseded",
        "supersedes_authorization_id": None,
    }
    candidate_values["authorization_fingerprint"] = (
        scoped_media_authorization_fingerprint(candidate_values)
    )
    candidate = ScopedMediaAuthorization(**candidate_values)
    session.add(candidate)
    session.flush()
    bound_values = {
        **base,
        "page_image_assignment_id": assignment.id,
        "assignment_version": assignment.assignment_version,
        "authorized_at": asset.approved_at + timedelta(minutes=2),
        "authorization_version": 2,
        "lifecycle_status": "current",
        "supersedes_authorization_id": candidate.id,
    }
    bound_values["authorization_fingerprint"] = (
        scoped_media_authorization_fingerprint(bound_values)
    )
    bound = ScopedMediaAuthorization(**bound_values)
    session.add(bound)
    session.flush()
    composition = session.exec(
        select(PageComposition).where(
            PageComposition.planned_page_id == requirement.planned_page_id
        )
    ).one()
    snapshot = deepcopy(composition.source_snapshot)
    snapshot_binding = snapshot["page_media"]["assignments"][0]
    snapshot_binding.update(
        {
            "authorization_id": bound.id,
            "authorization_version": bound.authorization_version,
            "authorization_fingerprint": bound.authorization_fingerprint,
            "authorization_terms": list(bound.authorization_terms),
            "reuse_policy": bound.reuse_policy,
            "authorization_assignment_id": assignment.id,
            "authorization_assignment_version": assignment.assignment_version,
        }
    )
    composition.source_snapshot = snapshot
    composition.source_hash = _hash(snapshot)
    session.add(composition)
    session.commit()
    assert candidate.id is not None and bound.id is not None
    return candidate.id, bound.id


def _append_authorization_successor(session: Session) -> ScopedMediaAuthorization:
    bound = session.exec(
        select(ScopedMediaAuthorization).where(
            ScopedMediaAuthorization.authorization_version == 2
        )
    ).one()
    bound.lifecycle_status = "superseded"
    session.add(bound)
    session.flush()
    values = bound.model_dump(exclude={"id", "created_at", "updated_at"})
    values.update(
        {
            "authorization_rationale": "Exact approved successor authorization.",
            "authorized_at": bound.authorized_at + timedelta(minutes=1),
            "authorization_version": 3,
            "lifecycle_status": "current",
            "supersedes_authorization_id": bound.id,
        }
    )
    values["authorization_fingerprint"] = scoped_media_authorization_fingerprint(
        values
    )
    successor = ScopedMediaAuthorization(**values)
    session.add(successor)
    composition = session.exec(
        select(PageComposition).where(
            PageComposition.planned_page_id == bound.planned_page_id
        )
    ).one()
    composition.status = "stale"
    session.add(composition)
    session.commit()
    session.refresh(successor)
    return successor


def _write_payload(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_backup_056_round_trips_remapped_scoped_authorization_lineage(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_governed_graph(session)
        _seed_authorization_history(session)
        exported = export_backup(session, backup_dir=tmp_path)
    source_engine.dispose()

    loaded = load_backup(Path(exported["path"]))
    assert BACKUP_VERSION == "0.57"
    assert loaded["metadata"]["version"] == "0.57"
    assert loaded["metadata"]["table_counts"]["scoped_media_authorizations"] == 2
    assert [
        record["authorization_version"]
        for record in loaded["data"]["scoped_media_authorizations"]
    ] == [1, 2]
    assert any(
        record["usage_authorization_mode"] == "scoped_required"
        and record["required_authorization_terms"] == ["no_reuse"]
        for record in loaded["data"]["image_metadata"]
    )
    # Move the exported authorization primary keys away from the target's natural
    # sequence so the nested Page Composition authorization ID must be remapped.
    loaded = deepcopy(loaded)
    exported_candidate, exported_bound = loaded["data"][
        "scoped_media_authorizations"
    ]
    exported_candidate["id"] += 1_000
    exported_bound["id"] += 1_000
    exported_bound["supersedes_authorization_id"] = exported_candidate["id"]
    exported_bound["authorization_fingerprint"] = (
        scoped_media_authorization_fingerprint(exported_bound)
    )
    exported_composition = loaded["data"]["page_compositions"][0]
    exported_binding = exported_composition["source_snapshot"]["page_media"][
        "assignments"
    ][0]
    exported_binding["authorization_id"] = exported_bound["id"]
    exported_binding["authorization_fingerprint"] = exported_bound[
        "authorization_fingerprint"
    ]
    exported_composition["source_hash"] = _hash(
        exported_composition["source_snapshot"]
    )
    restore_path = _write_payload(tmp_path / "remapped-authorization-ids.json", loaded)
    loaded = load_backup(restore_path)

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        # Force every durable identity to be remapped rather than accidentally
        # retaining the source primary keys.
        _scope(
            session,
            company="Existing scoped backup target",
            domain="existing-scoped-target.example.test",
        )
        session.commit()
        restored = restore_backup(session, restore_path)
        assert restored["status"] == "restored"
        authorizations = list(
            session.exec(
                select(ScopedMediaAuthorization).order_by(
                    ScopedMediaAuthorization.authorization_version
                )
            ).all()
        )
        assert len(authorizations) == 2
        candidate, bound = authorizations
        assert (
            candidate.website_id
            != loaded["data"]["scoped_media_authorizations"][0]["website_id"]
        )
        assert (
            bound.authorization_fingerprint
            != loaded["data"]["scoped_media_authorizations"][1][
                "authorization_fingerprint"
            ]
        )
        assert candidate.lifecycle_status == "superseded"
        assert candidate.page_image_assignment_id is None
        assert candidate.assignment_version is None
        assert bound.lifecycle_status == "current"
        assert bound.supersedes_authorization_id == candidate.id
        assert bound.page_image_assignment_id is not None
        assert bound.assignment_version == 2
        restored_asset = session.get(ImageMetadata, bound.image_metadata_id)
        assert restored_asset is not None
        assert restored_asset.usage_authorization_mode == "scoped_required"
        assert restored_asset.required_authorization_terms == ["no_reuse"]
        assert bound.approval_fingerprint == scoped_media_approval_fingerprint(
            {
                **bound.model_dump(),
                "asset_website_id": restored_asset.website_id,
                "asset_business_id": restored_asset.business_id,
                "usage_authorization_mode": (
                    restored_asset.usage_authorization_mode
                ),
                "required_authorization_terms": (
                    restored_asset.required_authorization_terms
                ),
            }
        )
        assert (
            bound.authorization_fingerprint
            == scoped_media_authorization_fingerprint(bound.model_dump())
        )
        composition = session.exec(
            select(PageComposition).where(
                PageComposition.planned_page_id == bound.planned_page_id
            )
        ).one()
        binding = composition.source_snapshot["page_media"]["assignments"][0]
        assert binding["authorization_id"] == bound.id
        assert binding["authorization_id"] != loaded["data"][
            "scoped_media_authorizations"
        ][1]["id"]
        assert binding["authorization_assignment_id"] == bound.page_image_assignment_id
        assert binding["authorization_assignment_version"] == bound.assignment_version
        assert binding["authorization_fingerprint"] == bound.authorization_fingerprint
        assert composition.source_hash == _hash(composition.source_snapshot)

        before_second_restore = {
            "authorizations": [
                (
                    item.id,
                    item.authorization_version,
                    item.supersedes_authorization_id,
                    item.lifecycle_status,
                    item.authorization_fingerprint,
                )
                for item in authorizations
            ],
            "composition_snapshot": deepcopy(composition.source_snapshot),
            "composition_hash": composition.source_hash,
        }
        second = restore_backup(session, restore_path)
        assert second["status"] == "restored"
        after_second_restore = list(
            session.exec(
                select(ScopedMediaAuthorization).order_by(
                    ScopedMediaAuthorization.authorization_version
                )
            ).all()
        )
        assert [
            (
                item.id,
                item.authorization_version,
                item.supersedes_authorization_id,
                item.lifecycle_status,
                item.authorization_fingerprint,
            )
            for item in after_second_restore
        ] == before_second_restore["authorizations"]
        composition = session.exec(
            select(PageComposition).where(
                PageComposition.planned_page_id == bound.planned_page_id
            )
        ).one()
        assert composition.source_snapshot == before_second_restore[
            "composition_snapshot"
        ]
        assert composition.source_hash == before_second_restore["composition_hash"]
    target_engine.dispose()


def test_restore_rejects_divergent_same_version_authorization_without_rewrite(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_governed_graph(session)
        _seed_authorization_history(session)
        exported = export_backup(session, backup_dir=tmp_path)
    source_engine.dispose()

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, exported["path"])
        candidate = session.exec(
            select(ScopedMediaAuthorization).where(
                ScopedMediaAuthorization.authorization_version == 1
            )
        ).one()
        candidate.authorization_rationale = (
            "Divergent target-only immutable authorization evidence."
        )
        candidate.authorization_fingerprint = (
            scoped_media_authorization_fingerprint(candidate.model_dump())
        )
        session.add(candidate)
        session.commit()
        divergent_fingerprint = candidate.authorization_fingerprint
        divergent_rationale = candidate.authorization_rationale

        with pytest.raises(
            BackupValidationError,
            match="same-version evidence differs",
        ):
            restore_backup(session, exported["path"])

        session.expire_all()
        preserved = session.get(ScopedMediaAuthorization, candidate.id)
        assert preserved is not None
        assert preserved.authorization_fingerprint == divergent_fingerprint
        assert preserved.authorization_rationale == divergent_rationale
        assert len(session.exec(select(ScopedMediaAuthorization)).all()) == 2
    target_engine.dispose()


def test_restore_rejects_newer_target_authorization_lineage_without_rewrite(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_governed_graph(session)
        _seed_authorization_history(session)
        exported = export_backup(session, backup_dir=tmp_path)
    source_engine.dispose()

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, exported["path"])
        bound = session.exec(
            select(ScopedMediaAuthorization).where(
                ScopedMediaAuthorization.authorization_version == 2
            )
        ).one()
        bound.lifecycle_status = "superseded"
        session.add(bound)
        session.flush()
        successor_values = bound.model_dump(
            exclude={"id", "created_at", "updated_at"}
        )
        successor_values.update(
            {
                "authorization_rationale": (
                    "Newer target authorization that an older backup must preserve."
                ),
                "authorized_at": bound.authorized_at + timedelta(minutes=1),
                "authorization_version": 3,
                "lifecycle_status": "current",
                "supersedes_authorization_id": bound.id,
            }
        )
        successor_values["authorization_fingerprint"] = (
            scoped_media_authorization_fingerprint(successor_values)
        )
        successor = ScopedMediaAuthorization(**successor_values)
        session.add(successor)
        session.commit()
        successor_id = successor.id
        successor_fingerprint = successor.authorization_fingerprint

        with pytest.raises(
            BackupValidationError,
            match="lineage is newer than the backup",
        ):
            restore_backup(session, exported["path"])

        session.expire_all()
        rows = list(
            session.exec(
                select(ScopedMediaAuthorization).order_by(
                    ScopedMediaAuthorization.authorization_version
                )
            ).all()
        )
        assert [row.authorization_version for row in rows] == [1, 2, 3]
        assert [row.lifecycle_status for row in rows] == [
            "superseded",
            "superseded",
            "current",
        ]
        preserved_successor = session.get(ScopedMediaAuthorization, successor_id)
        assert preserved_successor is not None
        assert preserved_successor.authorization_fingerprint == successor_fingerprint
    target_engine.dispose()


def test_restore_extends_an_exact_shorter_authorization_prefix_safely(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_governed_graph(session)
        _seed_authorization_history(session)
        prefix_backup = export_backup(session, backup_dir=tmp_path)
        source_successor = _append_authorization_successor(session)
        extended_backup = export_backup(session, backup_dir=tmp_path)
        assert source_successor.authorization_fingerprint
    source_engine.dispose()

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, prefix_backup["path"])
        prefix_rows = list(
            session.exec(
                select(ScopedMediaAuthorization).order_by(
                    ScopedMediaAuthorization.authorization_version
                )
            ).all()
        )
        assert [row.authorization_version for row in prefix_rows] == [1, 2]
        prefix_ids = [row.id for row in prefix_rows]
        prefix_fingerprints = [row.authorization_fingerprint for row in prefix_rows]

        restored = restore_backup(session, extended_backup["path"])
        assert restored["status"] == "restored"
        rows = list(
            session.exec(
                select(ScopedMediaAuthorization).order_by(
                    ScopedMediaAuthorization.authorization_version
                )
            ).all()
        )
        assert [row.authorization_version for row in rows] == [1, 2, 3]
        assert [row.lifecycle_status for row in rows] == [
            "superseded",
            "superseded",
            "current",
        ]
        assert [row.id for row in rows[:2]] == prefix_ids
        assert [row.authorization_fingerprint for row in rows[:2]] == (
            prefix_fingerprints
        )
        assert rows[2].supersedes_authorization_id == rows[1].id
        assert rows[2].authorization_fingerprint == (
            scoped_media_authorization_fingerprint(rows[2].model_dump())
        )
    target_engine.dispose()


def test_restore_rejects_source_empty_history_over_target_authorization(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_governed_graph(session)
        _seed_authorization_history(session)
        exported = export_backup(session, backup_dir=tmp_path)
    source_engine.dispose()

    source_empty = deepcopy(load_backup(Path(exported["path"])))
    source_empty["data"]["scoped_media_authorizations"] = []
    source_empty["metadata"]["table_counts"]["scoped_media_authorizations"] = 0
    for image in source_empty["data"]["image_metadata"]:
        image["usage_authorization_mode"] = "contract_default"
        image["required_authorization_terms"] = []
    composition = source_empty["data"]["page_compositions"][0]
    binding = composition["source_snapshot"]["page_media"]["assignments"][0]
    for field in (
        "authorization_id",
        "authorization_version",
        "authorization_fingerprint",
        "authorization_terms",
        "reuse_policy",
        "authorization_assignment_id",
        "authorization_assignment_version",
    ):
        binding.pop(field, None)
    composition["source_hash"] = _hash(composition["source_snapshot"])
    source_empty_path = _write_payload(
        tmp_path / "source-empty-authorization-history.json",
        source_empty,
    )
    load_backup(source_empty_path)

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, exported["path"])
        scoped_asset = session.exec(
            select(ImageMetadata).where(
                ImageMetadata.usage_authorization_mode == "scoped_required"
            )
        ).one()
        scoped_asset_id = scoped_asset.id

        with pytest.raises(
            BackupValidationError,
            match="touches restored scope identities absent",
        ):
            restore_backup(session, source_empty_path)

        session.expire_all()
        preserved_asset = session.get(ImageMetadata, scoped_asset_id)
        assert preserved_asset is not None
        assert preserved_asset.usage_authorization_mode == "scoped_required"
        assert preserved_asset.required_authorization_terms == ["no_reuse"]
        assert len(session.exec(select(ScopedMediaAuthorization)).all()) == 2
    target_engine.dispose()


def test_restore_rejects_target_only_cross_requirement_shared_asset_history(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_governed_graph(session)
        _seed_authorization_history(session)
        exported = export_backup(session, backup_dir=tmp_path)
    source_engine.dispose()

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, exported["path"])
        bound = session.exec(
            select(ScopedMediaAuthorization).where(
                ScopedMediaAuthorization.authorization_version == 2
            )
        ).one()
        source_requirement = session.get(
            PlannedPageMediaRequirement,
            bound.media_requirement_id,
        )
        assert source_requirement is not None
        requirement_values = source_requirement.model_dump(
            exclude={"id", "created_at", "updated_at"}
        )
        requirement_values.update(
            {
                "placement_key": "target-only-shared-asset-history",
                "target_component_instance_key": (
                    "target-only-shared-asset-history"
                ),
                "source_suggestion_key": None,
                "version": 1,
                "replaces_requirement_id": None,
            }
        )
        target_only_requirement = PlannedPageMediaRequirement(
            **requirement_values
        )
        session.add(target_only_requirement)
        session.flush()
        target_only_values = bound.model_dump(
            exclude={"id", "created_at", "updated_at"}
        )
        target_only_values.update(
            {
                "media_requirement_id": target_only_requirement.id,
                "requirement_version": 1,
                "placement_key": target_only_requirement.placement_key,
                "page_image_assignment_id": None,
                "assignment_version": None,
                "authorization_rationale": (
                    "Target-only historical authorization sharing a restored asset."
                ),
                "authorization_version": 1,
                "lifecycle_status": "superseded",
                "supersedes_authorization_id": None,
            }
        )
        target_only_values["authorization_fingerprint"] = (
            scoped_media_authorization_fingerprint(target_only_values)
        )
        target_only = ScopedMediaAuthorization(**target_only_values)
        session.add(target_only)
        session.commit()
        target_only_id = target_only.id
        target_only_fingerprint = target_only.authorization_fingerprint

        with pytest.raises(
            BackupValidationError,
            match="touches restored scope identities absent",
        ):
            restore_backup(session, exported["path"])

        session.expire_all()
        preserved = session.get(ScopedMediaAuthorization, target_only_id)
        assert preserved is not None
        assert preserved.authorization_fingerprint == target_only_fingerprint
        assert preserved.media_requirement_id == target_only_requirement.id
        assert len(session.exec(select(ScopedMediaAuthorization)).all()) == 3
    target_engine.dispose()


def test_restore_rejects_target_only_authorization_on_mapped_page_scope(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_governed_graph(session)
        _seed_authorization_history(session)
        exported = export_backup(session, backup_dir=tmp_path)
    source_engine.dispose()

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, exported["path"])
        bound = session.exec(
            select(ScopedMediaAuthorization).where(
                ScopedMediaAuthorization.authorization_version == 2
            )
        ).one()
        source_requirement = session.get(
            PlannedPageMediaRequirement,
            bound.media_requirement_id,
        )
        source_asset = session.get(ImageMetadata, bound.image_metadata_id)
        assert source_requirement is not None
        assert source_asset is not None

        asset_values = source_asset.model_dump(
            exclude={"id", "created_at", "updated_at"}
        )
        asset_values.update(
            {
                "file_name": "target-only-scope-asset.png",
                "media_key": "target-only-scope-asset",
                "media_version": 1,
                "original_filename": "target-only-scope-asset.png",
                "stored_filename": "target-only-scope-asset.png",
                "managed_storage_path": (
                    "originals/target-only-scope-asset.png"
                ),
                "replaces_image_metadata_id": None,
            }
        )
        target_only_asset = ImageMetadata(**asset_values)
        session.add(target_only_asset)
        session.flush()

        requirement_values = source_requirement.model_dump(
            exclude={"id", "created_at", "updated_at"}
        )
        requirement_values.update(
            {
                "placement_key": "target-only-page-scope-history",
                "target_component_instance_key": (
                    "target-only-page-scope-history"
                ),
                "source_suggestion_key": None,
                "version": 1,
                "replaces_requirement_id": None,
            }
        )
        target_only_requirement = PlannedPageMediaRequirement(
            **requirement_values
        )
        session.add(target_only_requirement)
        session.flush()

        approval_fingerprint = scoped_media_approval_fingerprint(
            {
                "image_metadata_id": target_only_asset.id,
                "asset_website_id": target_only_asset.website_id,
                "asset_business_id": target_only_asset.business_id,
                "media_version": target_only_asset.media_version,
                "asset_checksum_sha256": target_only_asset.checksum_sha256,
                "approval_version": target_only_asset.approval_version,
                "asset_approved_by": target_only_asset.approved_by,
                "asset_approved_at": target_only_asset.approved_at,
                "usage_authorization_mode": (
                    target_only_asset.usage_authorization_mode
                ),
                "required_authorization_terms": (
                    target_only_asset.required_authorization_terms
                ),
            }
        )
        target_only_values = bound.model_dump(
            exclude={"id", "created_at", "updated_at"}
        )
        target_only_values.update(
            {
                "media_requirement_id": target_only_requirement.id,
                "requirement_version": 1,
                "placement_key": target_only_requirement.placement_key,
                "image_metadata_id": target_only_asset.id,
                "media_version": target_only_asset.media_version,
                "asset_checksum_sha256": target_only_asset.checksum_sha256,
                "approval_version": target_only_asset.approval_version,
                "asset_approved_by": target_only_asset.approved_by,
                "asset_approved_at": target_only_asset.approved_at,
                "approval_fingerprint": approval_fingerprint,
                "page_image_assignment_id": None,
                "assignment_version": None,
                "authorization_rationale": (
                    "Target-only authorization intersecting a mapped page scope."
                ),
                "authorization_version": 1,
                "lifecycle_status": "superseded",
                "supersedes_authorization_id": None,
            }
        )
        target_only_values["authorization_fingerprint"] = (
            scoped_media_authorization_fingerprint(target_only_values)
        )
        target_only = ScopedMediaAuthorization(**target_only_values)
        session.add(target_only)
        session.commit()
        target_only_id = target_only.id
        target_only_fingerprint = target_only.authorization_fingerprint

        with pytest.raises(
            BackupValidationError,
            match="touches restored scope identities absent",
        ):
            restore_backup(session, exported["path"])

        session.expire_all()
        preserved = session.get(ScopedMediaAuthorization, target_only_id)
        assert preserved is not None
        assert preserved.authorization_fingerprint == target_only_fingerprint
        assert preserved.image_metadata_id == target_only_asset.id
        assert len(session.exec(select(ScopedMediaAuthorization)).all()) == 3
    target_engine.dispose()


@pytest.mark.parametrize(
    "tamper",
    (
        "unknown_term",
        "partial_assignment",
        "approval_identity",
        "multiple_current",
        "forked_lineage",
        "incoherent_policy",
        "partial_composition_binding",
        "unknown_composition_authorization",
        "approved_asset_successor",
        "missing_asset_required_term",
        "restrictive_cross_scope",
    ),
)
def test_backup_056_rejects_tampered_authorization_evidence(
    tmp_path: Path,
    tamper: str,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_governed_graph(session)
        _seed_authorization_history(session)
        exported = export_backup(session, backup_dir=tmp_path)
    engine.dispose()
    payload = deepcopy(load_backup(Path(exported["path"])))
    candidate, bound = payload["data"]["scoped_media_authorizations"]
    if tamper == "unknown_term":
        bound["authorization_terms"] = ["untyped_override"]
    elif tamper == "partial_assignment":
        bound["assignment_version"] = None
    elif tamper == "approval_identity":
        bound["approval_fingerprint"] = "f" * 64
    elif tamper == "multiple_current":
        candidate["lifecycle_status"] = "current"
    elif tamper == "incoherent_policy":
        bound["reuse_policy"] = "page_only"
        bound["authorization_fingerprint"] = (
            scoped_media_authorization_fingerprint(bound)
        )
        composition = payload["data"]["page_compositions"][0]
        snapshot_binding = composition["source_snapshot"]["page_media"][
            "assignments"
        ][0]
        snapshot_binding["reuse_policy"] = "page_only"
        snapshot_binding["authorization_fingerprint"] = bound[
            "authorization_fingerprint"
        ]
        composition["source_hash"] = _hash(composition["source_snapshot"])
    elif tamper == "partial_composition_binding":
        composition = payload["data"]["page_compositions"][0]
        composition["source_snapshot"]["page_media"]["assignments"][0].pop(
            "authorization_terms"
        )
        composition["source_hash"] = _hash(composition["source_snapshot"])
    elif tamper == "unknown_composition_authorization":
        composition = payload["data"]["page_compositions"][0]
        composition["source_snapshot"]["page_media"]["assignments"][0][
            "authorization_id"
        ] = 999_999
        composition["source_hash"] = _hash(composition["source_snapshot"])
    elif tamper == "approved_asset_successor":
        image = next(
            record
            for record in payload["data"]["image_metadata"]
            if record["id"] == bound["image_metadata_id"]
        )
        successor = deepcopy(image)
        successor["id"] = max(
            record["id"] for record in payload["data"]["image_metadata"]
        ) + 1
        successor["media_version"] = image["media_version"] + 1
        successor["replaces_image_metadata_id"] = image["id"]
        payload["data"]["image_metadata"].append(successor)
        payload["metadata"]["table_counts"]["image_metadata"] += 1
    elif tamper == "missing_asset_required_term":
        bound["authorization_terms"] = ["requirement_only_usage"]
        bound["authorization_fingerprint"] = (
            scoped_media_authorization_fingerprint(bound)
        )
        composition = payload["data"]["page_compositions"][0]
        snapshot_binding = composition["source_snapshot"]["page_media"][
            "assignments"
        ][0]
        snapshot_binding["authorization_terms"] = ["requirement_only_usage"]
        snapshot_binding["authorization_fingerprint"] = bound[
            "authorization_fingerprint"
        ]
        composition["source_hash"] = _hash(composition["source_snapshot"])
    elif tamper == "restrictive_cross_scope":
        source_requirement = next(
            record
            for record in payload["data"]["planned_page_media_requirements"]
            if record["id"] == bound["media_requirement_id"]
        )
        additional_requirement = deepcopy(source_requirement)
        additional_requirement["id"] = max(
            record["id"]
            for record in payload["data"]["planned_page_media_requirements"]
        ) + 1
        additional_requirement["placement_key"] = "backup-reuse-conflict"
        additional_requirement["target_component_instance_key"] = (
            "backup-reuse-conflict"
        )
        additional_requirement["source_suggestion_key"] = None
        additional_requirement["version"] = 1
        additional_requirement["replaces_requirement_id"] = None
        payload["data"]["planned_page_media_requirements"].append(
            additional_requirement
        )
        payload["metadata"]["table_counts"][
            "planned_page_media_requirements"
        ] += 1
        conflicting = deepcopy(bound)
        conflicting["id"] = max(candidate["id"], bound["id"]) + 1
        conflicting["media_requirement_id"] = additional_requirement["id"]
        conflicting["requirement_version"] = 1
        conflicting["placement_key"] = additional_requirement["placement_key"]
        conflicting["page_image_assignment_id"] = None
        conflicting["assignment_version"] = None
        conflicting["authorization_version"] = 1
        conflicting["supersedes_authorization_id"] = None
        conflicting["authorization_fingerprint"] = (
            scoped_media_authorization_fingerprint(conflicting)
        )
        payload["data"]["scoped_media_authorizations"].append(conflicting)
        payload["metadata"]["table_counts"]["scoped_media_authorizations"] += 1
    else:
        duplicate = deepcopy(bound)
        duplicate["id"] = max(candidate["id"], bound["id"]) + 1
        duplicate["authorization_version"] = 3
        duplicate["authorization_fingerprint"] = "e" * 64
        payload["data"]["scoped_media_authorizations"].append(duplicate)
        payload["metadata"]["table_counts"]["scoped_media_authorizations"] += 1
    path = _write_payload(tmp_path / f"tampered-{tamper}.json", payload)
    with pytest.raises(BackupValidationError):
        load_backup(path)


def test_backup_version_contract_fails_closed_for_missing_or_legacy_history(
    tmp_path: Path,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_governed_graph(session)
        _seed_authorization_history(session)
        exported = export_backup(session, backup_dir=tmp_path)
    engine.dispose()
    payload = load_backup(Path(exported["path"]))

    missing = deepcopy(payload)
    missing["data"].pop("scoped_media_authorizations")
    missing["metadata"]["table_counts"].pop("scoped_media_authorizations")
    with pytest.raises(BackupValidationError, match="scoped_media_authorizations"):
        load_backup(_write_payload(tmp_path / "missing-current-group.json", missing))

    legacy = deepcopy(payload)
    legacy["metadata"]["version"] = "0.55"
    for image in legacy["data"]["image_metadata"]:
        image["usage_authorization_mode"] = "contract_default"
        image["required_authorization_terms"] = []
    with pytest.raises(
        BackupValidationError,
        match="Legacy backup versions cannot claim scoped-media authorizations",
    ):
        load_backup(_write_payload(tmp_path / "legacy-claimed-history.json", legacy))
