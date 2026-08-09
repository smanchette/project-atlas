from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import backup as backup_module
from app.db.backup import (
    BACKUP_VERSION,
    BackupValidationError,
    export_backup,
    load_backup,
    restore_backup,
)
from app.models import (
    ApprovalAudit,
    Business,
    GeneratedPage,
    GeneratedPageQAResult,
    GeneratedPageRevision,
    PageComposition,
    PlannedPage,
    SitePlan,
    Website,
    WebsiteMediaPlanningRecord,
)
from app.services.page_qa import historical_qa_payload_hash, qa_result_record_hash


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _write_payload(tmp_path: Path, payload: dict, name: str) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _legacy_qa_projection(value: dict[str, object]) -> dict[str, object]:
    return {
        key: deepcopy(value[key])
        for key in (
            "page_id",
            "readiness_status",
            "checked_at",
            "passed_count",
            "warning_count",
            "failed_count",
            "checks",
        )
    }


def _candidate_qa_projection(value: dict[str, object]) -> dict[str, object]:
    candidate = deepcopy(value)
    candidate["qa_result_id"] = None
    candidate["lifecycle_status"] = "candidate"
    candidate["currentness_status"] = "candidate_not_persisted"
    candidate["currentness_reasons"] = []
    return candidate


def _candidate_qa_hash(value: dict[str, object]) -> str:
    return qa_result_record_hash(
        {
            "website_id": value["website_id"],
            "site_plan_id": value["site_plan_id"],
            "planned_page_id": value["planned_page_id"],
            "generated_page_id": value["page_id"],
            "latest_generated_page_revision_id": value[
                "latest_generated_page_revision_id"
            ],
            "content_hash": value["content_hash"],
            "source_hash": value["source_hash"],
            "page_composition_id": value["page_composition_id"],
            "composition_version": value["composition_version"],
            "composition_source_hash": value["composition_source_hash"],
            "qa_algorithm_key": value["qa_algorithm_key"],
            "qa_algorithm_version": value["qa_algorithm_version"],
            "qa_ruleset_key": value["qa_ruleset_key"],
            "qa_ruleset_version": value["qa_ruleset_version"],
            "qa_ruleset_hash": value["qa_ruleset_hash"],
            "readiness_status": value["readiness_status"],
            "passed_count": value["passed_count"],
            "warning_count": value["warning_count"],
            "failed_count": value["failed_count"],
            "check_payload": value["checks"],
            "evaluated_at": datetime.fromisoformat(str(value["checked_at"])),
        }
    )


def _seed_qa_graph(session: Session) -> dict[str, object]:
    business = Business(
        company_name="QA Backup Business",
        business_type="Local service company",
        state="FL",
    )
    session.add(business)
    session.flush()
    website = Website(
        business_id=business.id,
        website_name="QA Backup Website",
        domain="qa-backup.example.test",
        public_url="https://qa-backup.example.test",
        status="active",
    )
    session.add(website)
    session.flush()
    generated = GeneratedPage(
        business_id=business.id,
        website_id=website.id,
        page_type="home",
        page_title="Home",
        page_slug="home",
        draft_content={"title": "Home", "h1": "Welcome"},
        generation_status="generated",
        qa_status="ready",
    )
    session.add(generated)
    session.flush()
    plan = SitePlan(
        website_id=website.id,
        plan_key="primary",
        plan_name="Primary Site Plan",
        status="active",
        version=1,
    )
    session.add(plan)
    session.flush()
    planned = PlannedPage(
        website_id=website.id,
        site_plan_id=plan.id,
        page_type="home",
        working_name="Home",
        intended_slug="home",
        planning_status="planned",
        generated_page_id=generated.id,
    )
    session.add(planned)
    session.flush()
    media_snapshot = {
        "website_id": website.id,
        "site_plan_id": plan.id,
        "algorithm_version": "page-media-planning-v1",
        "planned_pages": [
            {
                "id": planned.id,
                "service_id": planned.service_id,
                "city_id": planned.city_id,
                "county_id": planned.county_id,
                "generated_page_id": generated.id,
            }
        ],
    }
    media_planning = WebsiteMediaPlanningRecord(
        website_id=website.id,
        business_id=business.id,
        site_plan_id=plan.id,
        version=1,
        algorithm_version="page-media-planning-v1",
        generated_media_suggestions=[],
        source_snapshot=media_snapshot,
        source_hash=_hash(media_snapshot),
    )
    session.add(media_planning)
    session.flush()
    revision = GeneratedPageRevision(
        generated_page_id=generated.id,
        created_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        created_by="QA Backup Test",
        reason="test",
        draft_hash_before="0" * 64,
        draft_hash_after="1" * 64,
        draft_content_before={},
        draft_content_after=generated.draft_content or {},
        changed_fields=["draft_content"],
    )
    session.add(revision)
    composition_snapshot = {
        "page_media": {
            "planning_record": {"id": media_planning.id},
            "requirements": [],
            "assignments": [],
        }
    }
    composition = PageComposition(
        website_id=website.id,
        site_plan_id=plan.id,
        planned_page_id=planned.id,
        generated_page_id=generated.id,
        composition_version=2,
        generated_components=[],
        operator_decisions=[],
        source_snapshot=composition_snapshot,
        source_hash=_hash(composition_snapshot),
        status="stale",
    )
    session.add(composition)
    session.flush()

    checks = [
        {
            "key": "content_present",
            "status": "pass",
            "message": "Content is present.",
            "category": "content",
            "remediation": None,
        }
    ]
    evaluated_at = datetime(2026, 8, 9, 12, 5, tzinfo=UTC)

    previous_values = {
        "website_id": website.id,
        "site_plan_id": plan.id,
        "planned_page_id": planned.id,
        "generated_page_id": generated.id,
        "latest_generated_page_revision_id": revision.id,
        "content_hash": revision.draft_hash_after,
        "source_hash": "3" * 64,
        "page_composition_id": composition.id,
        "composition_version": composition.composition_version,
        "composition_source_hash": composition.source_hash,
        "qa_algorithm_key": "generated-page-qa",
        "qa_algorithm_version": "2",
        "qa_ruleset_key": "page-type-review",
        "qa_ruleset_version": "2",
        "qa_ruleset_hash": "4" * 64,
        "readiness_status": "ready",
        "passed_count": 1,
        "warning_count": 0,
        "failed_count": 0,
        "check_payload": checks,
        "evaluated_at": evaluated_at - timedelta(minutes=1),
    }
    previous = GeneratedPageQAResult(
        **previous_values,
        lifecycle_status="superseded",
        result_hash=qa_result_record_hash(previous_values),
    )
    session.add(previous)
    session.flush()

    current_values = {
        **previous_values,
        "source_hash": "5" * 64,
        "evaluated_at": evaluated_at,
    }
    current = GeneratedPageQAResult(
        **current_values,
        lifecycle_status="current",
        supersedes_qa_result_id=previous.id,
        result_hash=qa_result_record_hash(current_values),
    )
    session.add(current)

    historical_payload = {
        "page_id": 999,
        "readiness_status": "ready",
        "checks": [{"key": "legacy", "status": "pass"}],
    }
    historical = GeneratedPageQAResult(
        website_id=website.id,
        site_plan_id=plan.id,
        planned_page_id=planned.id,
        generated_page_id=generated.id,
        readiness_status="ready",
        passed_count=1,
        warning_count=0,
        failed_count=0,
        check_payload=historical_payload["checks"],
        evaluated_at=evaluated_at - timedelta(days=1),
        lifecycle_status="historical_unbound",
        result_hash=historical_qa_payload_hash(historical_payload),
        historical_payload=historical_payload,
    )
    session.add(historical)
    session.flush()

    projection = {
        "qa_result_id": current.id,
        "page_id": generated.id,
        "website_id": website.id,
        "site_plan_id": plan.id,
        "planned_page_id": planned.id,
        "latest_generated_page_revision_id": revision.id,
        "content_hash": current.content_hash,
        "source_hash": current.source_hash,
        "page_composition_id": composition.id,
        "composition_version": composition.composition_version,
        "composition_source_hash": composition.source_hash,
        "qa_algorithm_key": current.qa_algorithm_key,
        "qa_algorithm_version": current.qa_algorithm_version,
        "qa_ruleset_key": current.qa_ruleset_key,
        "qa_ruleset_version": current.qa_ruleset_version,
        "qa_ruleset_hash": current.qa_ruleset_hash,
        "readiness_status": current.readiness_status,
        "checked_at": evaluated_at.isoformat(),
        "passed_count": 1,
        "warning_count": 0,
        "failed_count": 0,
        "checks": checks,
        "result_hash": current.result_hash,
        "lifecycle_status": "current",
        "currentness_status": "current_exact_identity_match",
        "currentness_reasons": [],
    }
    generated.qa_result = projection
    generated.qa_checked_at = evaluated_at
    session.add(generated)
    audit = ApprovalAudit(
        generated_page_id=generated.id,
        approved_at=evaluated_at + timedelta(minutes=1),
        approved_by="QA Backup Test",
        qa_status_at_approval="ready",
        qa_checked_at=evaluated_at,
        qa_result_snapshot=deepcopy(projection),
        draft_hash_at_approval=revision.draft_hash_after,
        page_status_before="draft",
        page_status_after="approved",
    )
    session.add(audit)
    session.commit()
    return {
        "website_id": website.id,
        "generated_page_id": generated.id,
        "composition_id": composition.id,
        "current_id": current.id,
        "current_hash": current.result_hash,
        "previous_id": previous.id,
        "historical_id": historical.id,
        "historical_hash": historical.result_hash,
        "historical_payload": historical_payload,
    }


def _seed_filler_scope(session: Session) -> None:
    business = Business(
        company_name="Existing Target Business",
        business_type="Local service company",
        state="FL",
    )
    session.add(business)
    session.flush()
    website = Website(
        business_id=business.id,
        website_name="Existing Target Website",
        domain="existing-target.example.test",
        public_url="https://existing-target.example.test",
        status="active",
    )
    session.add(website)
    session.flush()
    generated = GeneratedPage(
        business_id=business.id,
        website_id=website.id,
        page_type="home",
        page_title="Existing Home",
        page_slug="existing-home",
        draft_content={"title": "Existing Home"},
        generation_status="generated",
    )
    session.add(generated)
    session.flush()
    plan = SitePlan(
        website_id=website.id,
        plan_key="primary",
        plan_name="Existing Plan",
        status="active",
        version=1,
    )
    session.add(plan)
    session.flush()
    planned = PlannedPage(
        website_id=website.id,
        site_plan_id=plan.id,
        page_type="home",
        working_name="Existing Home",
        intended_slug="existing-home",
        planning_status="planned",
        generated_page_id=generated.id,
    )
    session.add(planned)
    session.flush()
    media_snapshot = {
        "website_id": website.id,
        "site_plan_id": plan.id,
        "algorithm_version": "page-media-planning-v1",
        "planned_pages": [
            {
                "id": planned.id,
                "service_id": planned.service_id,
                "city_id": planned.city_id,
                "county_id": planned.county_id,
                "generated_page_id": generated.id,
            }
        ],
    }
    media_planning = WebsiteMediaPlanningRecord(
        website_id=website.id,
        business_id=business.id,
        site_plan_id=plan.id,
        version=1,
        algorithm_version="page-media-planning-v1",
        generated_media_suggestions=[],
        source_snapshot=media_snapshot,
        source_hash=_hash(media_snapshot),
    )
    session.add(media_planning)
    session.flush()
    session.add(
        GeneratedPageRevision(
            generated_page_id=generated.id,
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
            draft_hash_before="0" * 64,
            draft_hash_after="6" * 64,
            draft_content_before={},
            draft_content_after=generated.draft_content or {},
            changed_fields=["draft_content"],
        )
    )
    composition_snapshot = {
        "page_media": {
            "planning_record": {"id": media_planning.id},
            "requirements": [],
            "assignments": [],
        }
    }
    session.add(
        PageComposition(
            website_id=website.id,
            site_plan_id=plan.id,
            planned_page_id=planned.id,
            generated_page_id=generated.id,
            composition_version=1,
            generated_components=[],
            operator_decisions=[],
            source_snapshot=composition_snapshot,
            source_hash=_hash(composition_snapshot),
            status="stale",
        )
    )
    session.commit()


def test_backup_055_round_trip_remaps_qa_identity_and_preserves_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        source_ids = _seed_qa_graph(session)
        source_composition = session.get(
            PageComposition, source_ids["composition_id"]
        )
        assert source_composition is not None
        source_composition.status = "current"
        session.add(source_composition)
        session.commit()
        exported = export_backup(session, backup_dir=tmp_path)

    loaded = load_backup(Path(exported["path"]))
    assert BACKUP_VERSION == "0.55"
    assert loaded["metadata"]["version"] == "0.55"
    assert loaded["metadata"]["table_counts"]["generated_page_qa_results"] == 3

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)

    def _ready_site_connection_plan(*_args, **_kwargs):
        return SimpleNamespace(ready=True)

    def _refresh_remapped_composition(
        session: Session,
        site_plan_id: int,
        *,
        commit: bool,
    ):
        assert commit is False
        compositions = list(
            session.exec(
                select(PageComposition).where(
                    PageComposition.site_plan_id == site_plan_id
                )
            ).all()
        )
        refreshed = 0
        unchanged = 0
        for composition in compositions:
            if (
                composition.composition_version != 3
                or composition.source_hash != "f" * 64
                or composition.status != "current"
            ):
                composition.composition_version = 3
                composition.source_hash = "f" * 64
                composition.status = "current"
                session.add(composition)
                refreshed += 1
            else:
                unchanged += 1
        return SimpleNamespace(
            created=0,
            refreshed=refreshed,
            unchanged=unchanged,
            blocked=0,
            compositions=compositions,
        )

    monkeypatch.setattr(
        "app.services.site_connections.read_site_connection_plan",
        _ready_site_connection_plan,
    )
    monkeypatch.setattr(
        "app.services.page_composition.refresh_site_plan_compositions",
        _refresh_remapped_composition,
    )
    with Session(target_engine) as session:
        _seed_filler_scope(session)
        first = restore_backup(session, exported["path"])
        second = restore_backup(session, exported["path"])
        assert first["status"] == second["status"] == "restored"

        website = session.exec(
            select(Website).where(Website.domain == "qa-backup.example.test")
        ).one()
        page = session.exec(
            select(GeneratedPage).where(GeneratedPage.website_id == website.id)
        ).one()
        results = list(
            session.exec(
                select(GeneratedPageQAResult)
                .where(GeneratedPageQAResult.generated_page_id == page.id)
                .order_by(GeneratedPageQAResult.id)
            ).all()
        )
        assert website.id != source_ids["website_id"]
        assert page.id != source_ids["generated_page_id"]
        assert len(results) == 3
        current = next(item for item in results if item.lifecycle_status == "current")
        previous = next(item for item in results if item.lifecycle_status == "superseded")
        historical = next(
            item for item in results if item.lifecycle_status == "historical_unbound"
        )
        assert current.supersedes_qa_result_id == previous.id
        assert current.website_id == website.id
        assert current.result_hash == qa_result_record_hash(
            current.model_dump(mode="python")
        )
        assert current.result_hash != source_ids["current_hash"]
        restored_composition = session.get(
            PageComposition, current.page_composition_id
        )
        assert restored_composition is not None
        assert current.composition_version == restored_composition.composition_version == 3
        assert current.composition_source_hash == restored_composition.source_hash == "f" * 64
        assert historical.historical_payload == source_ids["historical_payload"]
        assert historical.result_hash == source_ids["historical_hash"]
        assert page.qa_result is not None
        assert page.qa_result["page_id"] == page.id
        assert page.qa_result["qa_result_id"] == current.id
        assert page.qa_result["result_hash"] == current.result_hash
        assert page.qa_result["website_id"] == current.website_id
        assert page.qa_result["site_plan_id"] == current.site_plan_id
        assert page.qa_result["planned_page_id"] == current.planned_page_id
        assert (
            page.qa_result["latest_generated_page_revision_id"]
            == current.latest_generated_page_revision_id
        )
        assert page.qa_result["page_composition_id"] == current.page_composition_id
        assert page.qa_result["composition_version"] == current.composition_version
        assert (
            page.qa_result["composition_source_hash"]
            == current.composition_source_hash
        )
        audit = session.exec(
            select(ApprovalAudit).where(ApprovalAudit.generated_page_id == page.id)
        ).one()
        assert audit.qa_result_snapshot["page_id"] == page.id
        assert audit.qa_result_snapshot["qa_result_id"] == current.id
        assert audit.qa_result_snapshot["result_hash"] == current.result_hash
        assert audit.qa_result_snapshot["website_id"] == current.website_id
        assert audit.qa_result_snapshot["site_plan_id"] == current.site_plan_id
        assert audit.qa_result_snapshot["planned_page_id"] == current.planned_page_id
        assert (
            audit.qa_result_snapshot["latest_generated_page_revision_id"]
            == current.latest_generated_page_revision_id
        )
        assert (
            audit.qa_result_snapshot["page_composition_id"]
            == current.page_composition_id
        )
        assert (
            audit.qa_result_snapshot["composition_version"]
            == current.composition_version
        )
        assert (
            audit.qa_result_snapshot["composition_source_hash"]
            == current.composition_source_hash
        )


def test_backup_055_round_trip_remaps_and_rehashes_candidate_approval_snapshot(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        source_ids = _seed_qa_graph(session)
        audit = session.exec(select(ApprovalAudit)).one()
        candidate = _candidate_qa_projection(audit.qa_result_snapshot)
        assert candidate["result_hash"] == _candidate_qa_hash(candidate)
        audit.qa_result_snapshot = candidate
        session.add(audit)
        session.commit()
        exported = export_backup(session, backup_dir=tmp_path)

    loaded = load_backup(Path(exported["path"]))
    source_candidate = loaded["data"]["approval_audits"][0]["qa_result_snapshot"]
    assert source_candidate["qa_result_id"] is None
    assert source_candidate["lifecycle_status"] == "candidate"

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        _seed_filler_scope(session)
        restored = restore_backup(session, exported["path"])
        assert restored["status"] == "restored"

        website = session.exec(
            select(Website).where(Website.domain == "qa-backup.example.test")
        ).one()
        page = session.exec(
            select(GeneratedPage).where(GeneratedPage.website_id == website.id)
        ).one()
        audit = session.exec(
            select(ApprovalAudit).where(ApprovalAudit.generated_page_id == page.id)
        ).one()
        candidate = audit.qa_result_snapshot
        composition = session.get(PageComposition, candidate["page_composition_id"])

        assert page.id != source_ids["generated_page_id"]
        assert candidate["qa_result_id"] is None
        assert candidate["page_id"] == page.id
        assert candidate["website_id"] == website.id
        assert candidate["checked_at"].endswith("Z")
        assert composition is not None
        assert candidate["composition_source_hash"] == composition.source_hash
        assert candidate["result_hash"] == _candidate_qa_hash(candidate)

        reexported = export_backup(session, backup_dir=tmp_path)
        reloaded = load_backup(Path(reexported["path"]))
        restored_candidate = reloaded["data"]["approval_audits"][0][
            "qa_result_snapshot"
        ]
        assert restored_candidate["result_hash"] == _candidate_qa_hash(
            restored_candidate
        )


@pytest.mark.parametrize(
    "tamper",
    [
        "extra_field",
        "cross_page",
        "result_hash",
        "unknown_check_status",
        "partial_composition",
    ],
)
def test_backup_055_rejects_malformed_candidate_approval_snapshot(
    tmp_path: Path,
    tamper: str,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_qa_graph(session)
        audit = session.exec(select(ApprovalAudit)).one()
        audit.qa_result_snapshot = _candidate_qa_projection(audit.qa_result_snapshot)
        session.add(audit)
        session.commit()
        exported = export_backup(session, backup_dir=tmp_path)
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    snapshot = payload["data"]["approval_audits"][0]["qa_result_snapshot"]

    if tamper == "extra_field":
        snapshot["fabricated"] = True
    elif tamper == "cross_page":
        snapshot["page_id"] = 999
    elif tamper == "result_hash":
        snapshot["result_hash"] = "9" * 64
    elif tamper == "unknown_check_status":
        snapshot["checks"][0]["status"] = "unknown"
    else:
        snapshot["composition_source_hash"] = None

    path = _write_payload(tmp_path, payload, f"candidate-{tamper}.json")
    with pytest.raises(BackupValidationError):
        load_backup(path)


def test_backup_055_restore_supersedes_divergent_target_current_qa(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_qa_graph(session)
        exported = export_backup(session, backup_dir=tmp_path)

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, exported["path"])
        page = session.exec(select(GeneratedPage)).one()
        backup_current = session.exec(
            select(GeneratedPageQAResult).where(
                GeneratedPageQAResult.generated_page_id == page.id,
                GeneratedPageQAResult.lifecycle_status == "current",
            )
        ).one()
        backup_parent = session.get(
            GeneratedPageQAResult,
            backup_current.supersedes_qa_result_id,
        )
        assert backup_parent is not None
        backup_parent_hash = backup_parent.result_hash
        backup_current.lifecycle_status = "superseded"
        session.add(backup_current)
        divergent_values = {
            **backup_current.model_dump(mode="python"),
            "source_hash": "9" * 64,
            "evaluated_at": backup_current.evaluated_at + timedelta(minutes=1),
        }
        divergent = GeneratedPageQAResult(
            **{
                key: value
                for key, value in divergent_values.items()
                if key
                not in {
                    "id",
                    "created_at",
                    "updated_at",
                    "lifecycle_status",
                    "result_hash",
                    "supersedes_qa_result_id",
                }
            },
            lifecycle_status="current",
            supersedes_qa_result_id=backup_current.id,
            result_hash=qa_result_record_hash(divergent_values),
        )
        session.add(divergent)
        session.flush()
        page.qa_result = {
            **(page.qa_result or {}),
            "qa_result_id": divergent.id,
            "source_hash": divergent.source_hash,
            "checked_at": divergent.evaluated_at.isoformat(),
            "result_hash": divergent.result_hash,
        }
        page.qa_checked_at = divergent.evaluated_at
        session.add(page)
        session.commit()
        divergent_id = divergent.id

        restored = restore_backup(session, exported["path"])

        assert restored["status"] == "restored"
        currents = list(
            session.exec(
                select(GeneratedPageQAResult).where(
                    GeneratedPageQAResult.generated_page_id == page.id,
                    GeneratedPageQAResult.lifecycle_status == "current",
                )
            ).all()
        )
        assert len(currents) == 1
        assert currents[0].result_hash == backup_current.result_hash
        assert session.get(GeneratedPageQAResult, divergent_id).lifecycle_status == "superseded"
        session.refresh(page)
        assert page.qa_result["qa_result_id"] == currents[0].id

        lineage_before_repeat = [
            (
                item.id,
                item.lifecycle_status,
                item.supersedes_qa_result_id,
                item.result_hash,
            )
            for item in session.exec(
                select(GeneratedPageQAResult)
                .where(GeneratedPageQAResult.generated_page_id == page.id)
                .order_by(GeneratedPageQAResult.id)
            ).all()
        ]
        repeated = restore_backup(session, exported["path"])
        lineage_after_repeat = [
            (
                item.id,
                item.lifecycle_status,
                item.supersedes_qa_result_id,
                item.result_hash,
            )
            for item in session.exec(
                select(GeneratedPageQAResult)
                .where(GeneratedPageQAResult.generated_page_id == page.id)
                .order_by(GeneratedPageQAResult.id)
            ).all()
        ]
        assert repeated["status"] == "restored"
        assert lineage_after_repeat == lineage_before_repeat
        repeated_export = export_backup(session, backup_dir=tmp_path)
        assert load_backup(Path(repeated_export["path"]))["metadata"][
            "table_counts"
        ]["generated_page_qa_results"] == 4

        restored_current = currents[0]
        restored_current.lifecycle_status = "superseded"
        session.add(restored_current)
        next_values = {
            key: value
            for key, value in restored_current.model_dump(mode="python").items()
            if key
            not in {
                "id",
                "created_at",
                "updated_at",
                "lifecycle_status",
                "result_hash",
                "supersedes_qa_result_id",
            }
        }
        next_values["source_hash"] = "8" * 64
        next_values["evaluated_at"] = restored_current.evaluated_at + timedelta(
            minutes=2
        )
        next_current = GeneratedPageQAResult(
            **next_values,
            lifecycle_status="current",
            supersedes_qa_result_id=restored_current.id,
            result_hash=qa_result_record_hash(next_values),
        )
        session.add(next_current)
        session.flush()
        page.qa_result = {
            **(page.qa_result or {}),
            "qa_result_id": next_current.id,
            "source_hash": next_current.source_hash,
            "checked_at": next_current.evaluated_at.isoformat(),
            "result_hash": next_current.result_hash,
        }
        page.qa_checked_at = next_current.evaluated_at
        session.add(page)
        session.commit()

        replay_after_new_qa = restore_backup(session, exported["path"])
        assert replay_after_new_qa["status"] == "restored"
        replay_current = session.exec(
            select(GeneratedPageQAResult).where(
                GeneratedPageQAResult.generated_page_id == page.id,
                GeneratedPageQAResult.lifecycle_status == "current",
            )
        ).one()
        replay_hashes: list[str] = []
        replay_visited: set[int] = set()
        replay_node: GeneratedPageQAResult | None = replay_current
        while replay_node is not None:
            assert replay_node.id not in replay_visited
            replay_visited.add(replay_node.id)
            replay_hashes.append(replay_node.result_hash)
            replay_node = (
                session.get(
                    GeneratedPageQAResult,
                    replay_node.supersedes_qa_result_id,
                )
                if replay_node.supersedes_qa_result_id is not None
                else None
            )
        assert replay_hashes == [
            backup_current.result_hash,
            next_current.result_hash,
            divergent.result_hash,
            backup_parent_hash,
        ]
        expected_replay_current_hash = replay_current.result_hash

        followup = export_backup(session, backup_dir=tmp_path)
        loaded = load_backup(Path(followup["path"]))
        assert loaded["metadata"]["table_counts"]["generated_page_qa_results"] == 5

    roundtrip_engine = _engine()
    SQLModel.metadata.create_all(roundtrip_engine)
    with Session(roundtrip_engine) as session:
        result = restore_backup(session, followup["path"])
        assert result["status"] == "restored"
        assert session.exec(
            select(GeneratedPageQAResult).where(
                GeneratedPageQAResult.lifecycle_status == "current"
            )
        ).one().result_hash == expected_replay_current_hash


def test_backup_055_export_self_validates_before_reporting_success(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_qa_graph(session)
        page = session.exec(select(GeneratedPage)).one()
        page.qa_result = {**(page.qa_result or {}), "source_hash": "9" * 64}
        session.add(page)
        session.commit()

        with pytest.raises(BackupValidationError):
            export_backup(session, backup_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_backup_055_concurrent_exports_publish_distinct_valid_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_barrier = Barrier(2)
    original_load_backup = load_backup

    def synchronized_validation(path: Path) -> dict:
        payload = original_load_backup(path)
        if path.name.endswith(".validating"):
            validation_barrier.wait(timeout=10)
        return payload

    monkeypatch.setattr(backup_module, "load_backup", synchronized_validation)
    created_at = datetime(2026, 8, 9, 19, 0, tzinfo=UTC)

    def create_export(suffix: str) -> dict[str, object]:
        source_engine = _engine()
        SQLModel.metadata.create_all(source_engine)
        with Session(source_engine) as session:
            _seed_qa_graph(session)
            business = session.exec(select(Business)).one()
            business.company_name = f"QA Backup Business {suffix}"
            session.add(business)
            session.commit()
            return export_backup(
                session,
                backup_dir=tmp_path,
                created_at=created_at,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        exports = list(executor.map(create_export, ("A", "B")))

    paths = [Path(str(item["path"])) for item in exports]
    assert len(set(paths)) == 2
    assert all(path.is_file() for path in paths)
    payloads = [original_load_backup(path) for path in paths]
    assert {
        payload["data"]["businesses"][0]["company_name"] for payload in payloads
    } == {"QA Backup Business A", "QA Backup Business B"}
    assert not list(tmp_path.glob(".*.validating"))


@pytest.mark.parametrize(
    "tamper",
    [
        "generated_page_projection",
        "generated_page_projection_source",
        "generated_page_projection_status",
        "missing_projection",
        "generated_page_projection_downgrade",
        "approval_snapshot",
        "approval_snapshot_counts",
        "approval_snapshot_timestamp",
        "approval_snapshot_downgrade",
        "bound_result",
        "bound_lineage_historical_target",
        "bound_lineage_reversed_order",
        "historical_payload",
    ],
)
def test_backup_055_rejects_qa_identity_and_payload_tampering(
    tmp_path: Path,
    tamper: str,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_qa_graph(session)
        exported = export_backup(session, backup_dir=tmp_path)
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))

    if tamper == "generated_page_projection":
        payload["data"]["generated_pages"][0]["qa_result"]["page_id"] = 999
    elif tamper == "generated_page_projection_source":
        payload["data"]["generated_pages"][0]["qa_result"]["source_hash"] = "9" * 64
    elif tamper == "generated_page_projection_status":
        payload["data"]["generated_pages"][0]["qa_status"] = "blocked"
    elif tamper == "missing_projection":
        payload["data"]["generated_pages"][0]["qa_result"] = None
    elif tamper == "generated_page_projection_downgrade":
        payload["data"]["generated_pages"][0]["qa_result"].pop("qa_result_id")
    elif tamper == "approval_snapshot":
        payload["data"]["approval_audits"][0]["qa_result_snapshot"]["page_id"] = 999
    elif tamper == "approval_snapshot_counts":
        payload["data"]["approval_audits"][0]["qa_result_snapshot"]["failed_count"] = 999
    elif tamper == "approval_snapshot_timestamp":
        payload["data"]["approval_audits"][0]["qa_checked_at"] = (
            datetime(2025, 1, 1, tzinfo=UTC).isoformat()
        )
    elif tamper == "approval_snapshot_downgrade":
        payload["data"]["approval_audits"][0]["qa_result_snapshot"].pop(
            "qa_result_id"
        )
    elif tamper == "bound_result":
        current = next(
            item
            for item in payload["data"]["generated_page_qa_results"]
            if item["lifecycle_status"] == "current"
        )
        current["check_payload"][0]["status"] = "warning"
    elif tamper == "bound_lineage_historical_target":
        current = next(
            item
            for item in payload["data"]["generated_page_qa_results"]
            if item["lifecycle_status"] == "current"
        )
        historical = next(
            item
            for item in payload["data"]["generated_page_qa_results"]
            if item["lifecycle_status"] == "historical_unbound"
        )
        current["supersedes_qa_result_id"] = historical["id"]
    elif tamper == "bound_lineage_reversed_order":
        current = next(
            item
            for item in payload["data"]["generated_page_qa_results"]
            if item["lifecycle_status"] == "current"
        )
        previous = next(
            item
            for item in payload["data"]["generated_page_qa_results"]
            if item["lifecycle_status"] == "superseded"
        )
        current["supersedes_qa_result_id"] = None
        previous["supersedes_qa_result_id"] = current["id"]
    else:
        historical = next(
            item
            for item in payload["data"]["generated_page_qa_results"]
            if item["lifecycle_status"] == "historical_unbound"
        )
        historical["historical_payload"]["readiness_status"] = "blocked"

    path = _write_payload(tmp_path, payload, f"tampered-{tamper}.json")
    with pytest.raises(BackupValidationError):
        load_backup(path)


def test_backup_055_round_trips_normally_invalidated_qa_projection(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_qa_graph(session)
        page = session.exec(select(GeneratedPage)).one()
        current = session.exec(
            select(GeneratedPageQAResult).where(
                GeneratedPageQAResult.generated_page_id == page.id,
                GeneratedPageQAResult.lifecycle_status == "current",
            )
        ).one()
        page.qa_status = "not_run"
        page.qa_result = None
        page.qa_checked_at = None
        session.add(page)
        session.commit()

        exported = export_backup(session, backup_dir=tmp_path)
        loaded = load_backup(Path(exported["path"]))

    assert loaded["data"]["generated_pages"][0]["qa_status"] == "not_run"
    assert loaded["data"]["generated_pages"][0]["qa_result"] is None
    assert loaded["data"]["generated_pages"][0]["qa_checked_at"] is None
    assert any(
        item["id"] == current.id and item["lifecycle_status"] == "current"
        for item in loaded["data"]["generated_page_qa_results"]
    )

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restored = restore_backup(session, exported["path"])
        page = session.exec(select(GeneratedPage)).one()
        currents = list(
            session.exec(
                select(GeneratedPageQAResult).where(
                    GeneratedPageQAResult.generated_page_id == page.id,
                    GeneratedPageQAResult.lifecycle_status == "current",
                )
            ).all()
        )

        assert restored["status"] == "restored"
        assert page.qa_status == "not_run"
        assert page.qa_result is None
        assert page.qa_checked_at is None
        assert len(currents) == 1


def test_backup_054_loads_without_durable_qa_group(tmp_path: Path) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_qa_graph(session)
        exported = export_backup(session, backup_dir=tmp_path)
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    payload["metadata"]["version"] = "0.54"
    payload["metadata"]["table_counts"].pop("generated_page_qa_results")
    payload["data"].pop("generated_page_qa_results")
    for page in payload["data"]["generated_pages"]:
        if isinstance(page.get("qa_result"), dict):
            page["qa_result"] = _legacy_qa_projection(page["qa_result"])
    for audit in payload["data"]["approval_audits"]:
        audit["qa_result_snapshot"] = _legacy_qa_projection(
            audit["qa_result_snapshot"]
        )

    path = _write_payload(tmp_path, payload, "legacy-054.json")
    loaded = load_backup(path)

    assert loaded["data"]["generated_page_qa_results"] == []
    assert loaded["metadata"]["table_counts"]["generated_page_qa_results"] == 0

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restored = restore_backup(session, path)
        assert restored["status"] == "restored"


@pytest.mark.parametrize("bound_location", ["generated_page", "approval_snapshot"])
def test_backup_054_rejects_bound_qa_projection_downgrade(
    tmp_path: Path,
    bound_location: str,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_qa_graph(session)
        exported = export_backup(session, backup_dir=tmp_path)
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    payload["metadata"]["version"] = "0.54"
    payload["metadata"]["table_counts"].pop("generated_page_qa_results")
    payload["data"].pop("generated_page_qa_results")

    if bound_location != "generated_page":
        page = payload["data"]["generated_pages"][0]
        page["qa_result"] = _legacy_qa_projection(page["qa_result"])
    if bound_location != "approval_snapshot":
        audit = payload["data"]["approval_audits"][0]
        audit["qa_result_snapshot"] = _legacy_qa_projection(
            audit["qa_result_snapshot"]
        )

    path = _write_payload(
        tmp_path,
        payload,
        f"downgraded-bound-{bound_location}.json",
    )
    with pytest.raises(BackupValidationError):
        load_backup(path)
