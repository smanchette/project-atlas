from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
import re
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DatabaseError

from app.core.config import get_settings
from app.db.page_composition_history_evidence import (
    EVIDENCE_RECORDED_BY,
    EVIDENCE_RECORD_SOURCE,
    EVIDENCE_SCHEMA,
    EVIDENCE_VERSION,
)
from app.models import (
    Brand,
    Business,
    GeneratedPage,
    GeneratedPageQAResult,
    GeneratedPageRevision,
    PageComposition,
    PageCompositionRevision,
    PlannedPage,
    SitePlan,
    Website,
)
from app.services.page_composition_history import (
    MIGRATION_BACKFILL_ACTOR,
    MIGRATION_BACKFILL_SOURCE,
    canonical_payload_hash,
    composition_revision_hash,
)
from app.services.page_qa import qa_result_record_hash


BACKEND = Path(__file__).parents[1]
REVISION_0047 = "20260817_0047"
REVISION_0048 = "20260820_0048"
TABLE = "pagecompositionrevision"


def _migration_module():
    path = (
        BACKEND
        / "alembic"
        / "versions"
        / "20260820_0048_append_only_page_composition_history.py"
    )
    spec = spec_from_file_location("atlas_migration_0048", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def _config(monkeypatch: pytest.MonkeyPatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def _insert(connection, model, **values) -> int:
    instance = model(**values)
    payload = {
        column.name: getattr(instance, column.name)
        for column in model.__table__.columns
        if column.name != "id"
    }
    result = connection.execute(sa.insert(model).values(**payload))
    inserted = result.inserted_primary_key
    assert inserted and isinstance(inserted[0], int)
    return inserted[0]


def _seed_bound_composition(engine, *, version: int = 8) -> dict[str, object]:
    when = datetime(2026, 8, 19, 14, 15, 16, 123456, tzinfo=UTC)
    draft = {
        "title": "Disposable composition migration page",
        "h1": "Disposable composition migration page",
        "sections": [],
    }
    content_hash = canonical_payload_hash(draft)
    components = [
        {
            "instance_key": "hero",
            "component_key": "hero",
            "contract_version": 1,
            "region": "main",
            "position": 0,
            "variant": "default",
            "input_bindings": {},
            "provenance": "atlas_generated",
        }
    ]
    with engine.begin() as connection:
        business_id = _insert(
            connection,
            Business,
            company_name="Composition Migration Company",
            business_type="test",
            state="FL",
        )
        brand_id = _insert(
            connection,
            Brand,
            business_id=business_id,
            brand_name="Composition Migration Brand",
            status="active",
        )
        website_id = _insert(
            connection,
            Website,
            business_id=business_id,
            brand_id=brand_id,
            website_name="Composition Migration Website",
            domain="composition-migration.example.test",
            public_url="https://composition-migration.example.test",
            status="active",
        )
        generated_page_id = _insert(
            connection,
            GeneratedPage,
            business_id=business_id,
            website_id=website_id,
            page_type="informational",
            page_title="Composition Migration",
            page_slug="composition-migration",
            draft_content=draft,
            status="draft",
        )
        site_plan_id = _insert(
            connection,
            SitePlan,
            website_id=website_id,
            plan_key="primary",
            plan_name="Composition Migration Plan",
            status="approved",
            version=1,
        )
        planned_page_id = _insert(
            connection,
            PlannedPage,
            website_id=website_id,
            site_plan_id=site_plan_id,
            page_type="informational",
            working_name="Composition Migration",
            intended_slug="composition-migration",
            planning_status="drafted",
            generated_page_id=generated_page_id,
        )
        generated_revision_id = _insert(
            connection,
            GeneratedPageRevision,
            generated_page_id=generated_page_id,
            created_at=when,
            created_by="migration-test",
            reason="Seed exact disposable history",
            draft_hash_before="0" * 64,
            draft_hash_after=content_hash,
            draft_content_before={},
            draft_content_after=draft,
            changed_fields=["title", "h1"],
        )
        snapshot = {
            "website_id": website_id,
            "site_plan_id": site_plan_id,
            "planned_page_id": planned_page_id,
            "generated_page_id": generated_page_id,
            "generated_page_updated_at": when.isoformat(),
            "draft_hash": content_hash,
        }
        source_hash = canonical_payload_hash(snapshot)
        composition_id = _insert(
            connection,
            PageComposition,
            website_id=website_id,
            site_plan_id=site_plan_id,
            planned_page_id=planned_page_id,
            generated_page_id=generated_page_id,
            composition_version=version,
            generated_components=components,
            operator_decisions=[],
            source_snapshot=snapshot,
            source_hash=source_hash,
            status="current",
            generated_at=when,
        )
        qa_id = _insert(
            connection,
            GeneratedPageQAResult,
            website_id=website_id,
            site_plan_id=site_plan_id,
            planned_page_id=planned_page_id,
            generated_page_id=generated_page_id,
            latest_generated_page_revision_id=generated_revision_id,
            content_hash=content_hash,
            source_hash="1" * 64,
            page_composition_id=composition_id,
            composition_version=version,
            composition_source_hash=source_hash,
            qa_algorithm_key="migration-test",
            qa_algorithm_version="1",
            qa_ruleset_key="migration-test",
            qa_ruleset_version="1",
            qa_ruleset_hash="2" * 64,
            readiness_status="ready",
            passed_count=1,
            warning_count=0,
            failed_count=0,
            check_payload=[],
            evaluated_at=when,
            lifecycle_status="current",
            result_hash="3" * 64,
            historical_payload=None,
        )
    return {
        "website_id": website_id,
        "site_plan_id": site_plan_id,
        "planned_page_id": planned_page_id,
        "generated_page_id": generated_page_id,
        "generated_revision_id": generated_revision_id,
        "composition_id": composition_id,
        "qa_id": qa_id,
        "version": version,
        "content_hash": content_hash,
        "source_hash": source_hash,
        "snapshot": snapshot,
        "components": components,
        "generated_at": when,
    }


def _write_recovery_evidence(
    engine,
    tmp_path: Path,
    seeded: dict[str, object],
) -> tuple[Path, str, dict[str, object]]:
    generated_at = seeded["generated_at"]
    assert isinstance(generated_at, datetime)
    historical_snapshot = {
        **deepcopy(seeded["snapshot"]),
        "legacy_history_marker": "synthetic-v7",
    }
    historical_source_hash = canonical_payload_hash(historical_snapshot)
    revision_hash_values = {
        "page_composition_id": seeded["composition_id"],
        "website_id": seeded["website_id"],
        "site_plan_id": seeded["site_plan_id"],
        "planned_page_id": seeded["planned_page_id"],
        "generated_page_id": seeded["generated_page_id"],
        "generated_page_revision_id": seeded["generated_revision_id"],
        "composition_version": int(seeded["version"]) - 1,
        "supersedes_revision_id": None,
        "supersedes_revision_hash": None,
        "lineage_kind": "legacy_root",
        "content_hash": seeded["content_hash"],
        "generated_components": deepcopy(seeded["components"]),
        "operator_decisions": [],
        "source_snapshot": historical_snapshot,
        "source_hash": historical_source_hash,
        "generated_at": generated_at,
        "decided_by": None,
        "decided_at": None,
        "recorded_at": generated_at,
        "recorded_by": EVIDENCE_RECORDED_BY,
        "record_source": EVIDENCE_RECORD_SOURCE,
    }
    revision = {
        **revision_hash_values,
        "generated_at": generated_at.isoformat(),
        "recorded_at": generated_at.isoformat(),
        "revision_hash": composition_revision_hash(revision_hash_values),
    }
    qa_hash_values = {
        "website_id": seeded["website_id"],
        "site_plan_id": seeded["site_plan_id"],
        "planned_page_id": seeded["planned_page_id"],
        "generated_page_id": seeded["generated_page_id"],
        "latest_generated_page_revision_id": seeded["generated_revision_id"],
        "content_hash": seeded["content_hash"],
        "source_hash": "1" * 64,
        "page_composition_id": seeded["composition_id"],
        "composition_version": int(seeded["version"]) - 1,
        "composition_source_hash": historical_source_hash,
        "qa_algorithm_key": "migration-test",
        "qa_algorithm_version": "1",
        "qa_ruleset_key": "migration-test",
        "qa_ruleset_version": "1",
        "qa_ruleset_hash": "2" * 64,
        "readiness_status": "ready",
        "passed_count": 1,
        "warning_count": 0,
        "failed_count": 0,
        "check_payload": [],
        "evaluated_at": generated_at,
    }
    qa_result = {
        "id": seeded["qa_id"],
        **qa_hash_values,
        "evaluated_at": generated_at.isoformat(),
        "result_hash": qa_result_record_hash(qa_hash_values),
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE generatedpageqaresult SET composition_version = :version, "
                "composition_source_hash = :source_hash, result_hash = :result_hash "
                "WHERE id = :qa_id"
            ),
            {
                "version": qa_result["composition_version"],
                "source_hash": qa_result["composition_source_hash"],
                "result_hash": qa_result["result_hash"],
                "qa_id": seeded["qa_id"],
            },
        )

    record_payload = {"revision": revision, "qa_results": [qa_result]}
    record = {
        **record_payload,
        "record_hash": canonical_payload_hash(record_payload),
    }
    source_created_at = generated_at + timedelta(minutes=1)
    payload = {
        "schema": EVIDENCE_SCHEMA,
        "version": EVIDENCE_VERSION,
        "created_at": (source_created_at + timedelta(minutes=1)).isoformat(),
        "source_artifact": {
            "app": "Project Atlas",
            "backup_version": "0.58",
            "created_at": source_created_at.isoformat(),
            "sha256": "a" * 64,
            "size_bytes": 1,
        },
        "records": [record],
    }
    path = tmp_path / "synthetic-page-composition-history-evidence.json"
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest(), payload


def _schema_snapshot(engine) -> dict[str, object]:
    inspector = inspect(engine)
    return {
        "columns": tuple(
            (item["name"], str(item["type"]), bool(item["nullable"]))
            for item in inspector.get_columns(TABLE)
        ),
        "checks": tuple(
            sorted(item["name"] for item in inspector.get_check_constraints(TABLE))
        ),
        "foreign_keys": tuple(
            sorted(
                (
                    item["name"],
                    tuple(item["constrained_columns"]),
                    item["referred_table"],
                    tuple(item["referred_columns"]),
                    tuple(sorted((item.get("options") or {}).items())),
                )
                for item in inspector.get_foreign_keys(TABLE)
            )
        ),
        "uniques": tuple(
            sorted(
                (item["name"], tuple(item["column_names"]))
                for item in inspector.get_unique_constraints(TABLE)
            )
        ),
        "indexes": tuple(
            sorted(
                (
                    item["name"],
                    tuple(item["column_names"]),
                    bool(item["unique"]),
                )
                for item in inspector.get_indexes(TABLE)
                if not item.get("duplicates_constraint")
            )
        ),
    }


def test_0048_is_one_linear_revision_with_postgresql_safe_identifiers() -> None:
    migration, path = _migration_module()
    assert migration.revision == REVISION_0048
    assert migration.down_revision == REVISION_0047
    assert migration.TABLE == TABLE
    source = path.read_text(encoding="utf-8")
    identifiers = {
        first or second
        for first, second in re.findall(
            r'(?:name\s*=\s*"([^"]+)"|op\.create_index\(\s*"([^"]+)")',
            source,
        )
        if first or second
    }
    identifiers.update(migration.EXPECTED_INDEXES)
    identifiers.update(migration.EXPECTED_UNIQUES)
    identifiers.update(
        {
            migration.TABLE,
            migration.CURRENT_HEAD_FK,
            migration.QA_REVISION_FK,
            migration.IMMUTABLE_FUNCTION,
            migration.IMMUTABLE_ROW_TRIGGER,
            migration.IMMUTABLE_TRUNCATE_TRIGGER,
            migration.SQLITE_UPDATE_TRIGGER,
            migration.SQLITE_DELETE_TRIGGER,
        }
    )
    assert identifiers
    assert all(len(identifier.encode("utf-8")) <= 63 for identifier in identifiers)


def test_0048_model_contract_matches_migration_contract() -> None:
    migration, _ = _migration_module()
    model = PageCompositionRevision.__table__
    assert tuple(model.c.keys()) == migration.EXPECTED_COLUMNS
    assert {
        constraint.name
        for constraint in model.constraints
        if isinstance(constraint, sa.CheckConstraint)
    } == migration.EXPECTED_CHECKS
    assert {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in model.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    } == migration.EXPECTED_UNIQUES
    assert {
        index.name: tuple(column.name for column in index.columns)
        for index in model.indexes
    } == migration.EXPECTED_INDEXES
    page_fk = next(
        constraint
        for constraint in PageComposition.__table__.foreign_key_constraints
        if constraint.name == migration.CURRENT_HEAD_FK
    )
    qa_fk = next(
        constraint
        for constraint in GeneratedPageQAResult.__table__.foreign_key_constraints
        if constraint.name == migration.QA_REVISION_FK
    )
    assert page_fk.deferrable is True and page_fk.initially == "DEFERRED"
    assert qa_fk.deferrable is True and qa_fk.initially == "DEFERRED"
    assert PageComposition.__table__.c.id.autoincrement == "ignore_fk"


def test_0048_clean_create_matches_model_and_empty_downgrade_is_repeatable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "composition-history-clean.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    before_tables = set(inspect(engine).get_table_names())
    engine.dispose()

    command.upgrade(config, REVISION_0048)
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert set(inspect(engine).get_table_names()) == before_tables | {TABLE}
    first_schema = _schema_snapshot(engine)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0048
        assert connection.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() == 0
    engine.dispose()

    command.downgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert TABLE not in inspect(engine).get_table_names()
    engine.dispose()
    command.upgrade(config, REVISION_0048)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert _schema_snapshot(engine) == first_schema
    engine.dispose()
    get_settings.cache_clear()


def test_0048_backfills_exact_legacy_root_and_preserves_qa_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "composition-history-backfill.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    seeded = _seed_bound_composition(engine)
    engine.dispose()

    command.upgrade(config, REVISION_0048)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.connect() as connection:
        row = connection.execute(text(f"SELECT * FROM {TABLE}")).mappings().one()
        assert row["page_composition_id"] == seeded["composition_id"]
        assert row["composition_version"] == seeded["version"] == 8
        assert row["source_hash"] == seeded["source_hash"]
        assert row["content_hash"] == seeded["content_hash"]
        assert row["generated_page_revision_id"] == seeded["generated_revision_id"]
        assert row["lineage_kind"] == "legacy_root"
        assert row["supersedes_revision_id"] is None
        assert row["supersedes_revision_hash"] is None
        assert row["recorded_by"] == MIGRATION_BACKFILL_ACTOR
        assert row["record_source"] == MIGRATION_BACKFILL_SOURCE
        values = dict(row)
        for field in (
            "generated_components",
            "operator_decisions",
            "source_snapshot",
        ):
            values[field] = __import__("json").loads(values[field])
        for field in ("generated_at", "decided_at", "recorded_at"):
            if values[field] is not None and isinstance(values[field], str):
                values[field] = datetime.fromisoformat(values[field])
        assert values["revision_hash"] == composition_revision_hash(values)
        qa = connection.execute(
            text(
                "SELECT page_composition_id, composition_version, "
                "composition_source_hash FROM generatedpageqaresult WHERE id = :id"
            ),
            {"id": seeded["qa_id"]},
        ).mappings().one()
        assert tuple(qa.values()) == (
            seeded["composition_id"],
            seeded["version"],
            seeded["source_hash"],
        )
    engine.dispose()
    get_settings.cache_clear()


def test_0048_recovers_exact_qa_required_predecessor_and_blocks_lossy_downgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "composition-history-recovery-evidence.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    seeded = _seed_bound_composition(engine)
    evidence_path, evidence_sha256, payload = _write_recovery_evidence(
        engine,
        tmp_path,
        seeded,
    )
    config.set_main_option(
        "page_composition_history_evidence_path",
        str(evidence_path),
    )
    config.set_main_option(
        "page_composition_history_evidence_sha256",
        evidence_sha256,
    )
    engine.dispose()

    command.upgrade(config, REVISION_0048)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT id, composition_version, source_hash, revision_hash, "
                f"supersedes_revision_id, supersedes_revision_hash, lineage_kind, "
                f"recorded_at, generated_at, recorded_by, record_source FROM {TABLE} "
                "ORDER BY composition_version"
            )
        ).mappings().all()
        assert len(rows) == 2
        recovered, current = rows
        expected_revision = payload["records"][0]["revision"]
        assert (
            recovered["composition_version"],
            recovered["source_hash"],
            recovered["revision_hash"],
            recovered["lineage_kind"],
            recovered["recorded_by"],
            recovered["record_source"],
        ) == (
            7,
            expected_revision["source_hash"],
            expected_revision["revision_hash"],
            "legacy_root",
            EVIDENCE_RECORDED_BY,
            EVIDENCE_RECORD_SOURCE,
        )
        assert recovered["supersedes_revision_id"] is None
        assert recovered["supersedes_revision_hash"] is None
        assert datetime.fromisoformat(recovered["recorded_at"]) == datetime.fromisoformat(
            recovered["generated_at"]
        )
        assert current["composition_version"] == seeded["version"] == 8
        assert current["source_hash"] == seeded["source_hash"]
        assert current["lineage_kind"] == "successor"
        assert current["supersedes_revision_id"] == recovered["id"]
        assert current["supersedes_revision_hash"] == recovered["revision_hash"]
        assert datetime.fromisoformat(current["recorded_at"]) >= datetime.fromisoformat(
            recovered["recorded_at"]
        )
        qa_binding = connection.execute(
            text(
                "SELECT page_composition_id, composition_version, "
                "composition_source_hash, result_hash FROM generatedpageqaresult "
                "WHERE id = :qa_id"
            ),
            {"qa_id": seeded["qa_id"]},
        ).one()
        assert tuple(qa_binding) == (
            seeded["composition_id"],
            7,
            expected_revision["source_hash"],
            payload["records"][0]["qa_results"][0]["result_hash"],
        )
    before_schema = _schema_snapshot(engine)
    engine.dispose()

    with pytest.raises(RuntimeError, match="recovery or post-migration"):
        command.downgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert _schema_snapshot(engine) == before_schema
    with engine.connect() as connection:
        assert connection.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() == 2
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0048
    engine.dispose()
    get_settings.cache_clear()


@pytest.mark.parametrize("tamper", ["caller_sha256", "extra_record", "qa_result"])
def test_0048_recovery_evidence_tamper_fails_before_schema_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tamper: str,
) -> None:
    database = tmp_path / f"composition-history-recovery-tamper-{tamper}.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    seeded = _seed_bound_composition(engine)
    evidence_path, evidence_sha256, payload = _write_recovery_evidence(
        engine,
        tmp_path,
        seeded,
    )
    if tamper == "caller_sha256":
        evidence_sha256 = "f" * 64
    else:
        tampered = deepcopy(payload)
        if tamper == "extra_record":
            extra = deepcopy(tampered["records"][0])
            extra["revision"]["composition_version"] = 6
            extra["revision"]["revision_hash"] = "e" * 64
            extra_payload = {
                "revision": extra["revision"],
                "qa_results": extra["qa_results"],
            }
            extra["record_hash"] = canonical_payload_hash(extra_payload)
            tampered["records"].insert(0, extra)
        else:
            tampered["records"][0]["qa_results"][0]["readiness_status"] = "blocked"
            record_payload = {
                "revision": tampered["records"][0]["revision"],
                "qa_results": tampered["records"][0]["qa_results"],
            }
            tampered["records"][0]["record_hash"] = canonical_payload_hash(
                record_payload
            )
        raw = json.dumps(
            tampered,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        evidence_path.write_bytes(raw)
        evidence_sha256 = hashlib.sha256(raw).hexdigest()
    config.set_main_option(
        "page_composition_history_evidence_path",
        str(evidence_path),
    )
    config.set_main_option(
        "page_composition_history_evidence_sha256",
        evidence_sha256,
    )
    engine.dispose()

    with pytest.raises(RuntimeError):
        command.upgrade(config, REVISION_0048)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0047
    engine.dispose()
    get_settings.cache_clear()


def test_0048_backfill_never_substitutes_a_later_generated_page_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "composition-history-later-revision.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    seeded = _seed_bound_composition(engine)
    with engine.begin() as connection:
        later_revision_id = _insert(
            connection,
            GeneratedPageRevision,
            generated_page_id=seeded["generated_page_id"],
            created_at=seeded["generated_at"] + timedelta(seconds=1),
            created_by="migration-test",
            reason="A later revision must not replace derivation-time identity",
            draft_hash_before=seeded["content_hash"],
            draft_hash_after="e" * 64,
            draft_content_before={},
            draft_content_after={"later": True},
            changed_fields=["later"],
        )
    engine.dispose()

    command.upgrade(config, REVISION_0048)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.connect() as connection:
        history = connection.execute(
            text(
                f"SELECT generated_page_revision_id, generated_at, recorded_at "
                f"FROM {TABLE}"
            )
        ).mappings().one()
        assert history["generated_page_revision_id"] == seeded["generated_revision_id"]
        assert history["generated_page_revision_id"] != later_revision_id
        recorded_at = datetime.fromisoformat(history["recorded_at"])
        generated_at = datetime.fromisoformat(history["generated_at"])
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=UTC)
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=UTC)
        assert recorded_at > generated_at
    engine.dispose()
    get_settings.cache_clear()


def test_0048_immutability_guards_reject_update_and_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "composition-history-immutable.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    _seed_bound_composition(engine)
    engine.dispose()
    command.upgrade(config, REVISION_0048)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with pytest.raises(DatabaseError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(
                text(f"UPDATE {TABLE} SET recorded_by = 'tamper'")
            )
    with pytest.raises(DatabaseError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(text(f"DELETE FROM {TABLE}"))
    with engine.connect() as connection:
        assert connection.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() == 1
    engine.dispose()
    get_settings.cache_clear()


def test_0048_refuses_precreated_table_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "composition-history-precreated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text(f"CREATE TABLE {TABLE} (id INTEGER PRIMARY KEY)"))
    engine.dispose()
    with pytest.raises(RuntimeError, match="pre-created revision table"):
        command.upgrade(config, REVISION_0048)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert {item["name"] for item in inspect(engine).get_columns(TABLE)} == {"id"}
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0047
    engine.dispose()
    get_settings.cache_clear()


@pytest.mark.parametrize("tamper", ["source_hash", "qa_version", "latest_revision"])
def test_0048_refuses_unreconstructable_source_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tamper: str,
) -> None:
    database = tmp_path / f"composition-history-unreconstructable-{tamper}.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    seeded = _seed_bound_composition(engine)
    with engine.begin() as connection:
        if tamper == "source_hash":
            connection.execute(
                text("UPDATE pagecomposition SET source_hash = :hash WHERE id = :id"),
                {"hash": "f" * 64, "id": seeded["composition_id"]},
            )
        elif tamper == "qa_version":
            connection.execute(
                text(
                    "UPDATE generatedpageqaresult SET composition_version = 7 "
                    "WHERE id = :id"
                ),
                {"id": seeded["qa_id"]},
            )
        else:
            connection.execute(
                text(
                    "UPDATE generatedpagerevision SET draft_hash_after = :hash "
                    "WHERE id = :id"
                ),
                {"hash": "e" * 64, "id": seeded["generated_revision_id"]},
            )
    engine.dispose()
    with pytest.raises(RuntimeError):
        command.upgrade(config, REVISION_0048)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0047
    engine.dispose()
    get_settings.cache_clear()


def test_0048_pristine_legacy_root_downgrade_is_lossless(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "composition-history-pristine-downgrade.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    seeded = _seed_bound_composition(engine)
    engine.dispose()
    command.upgrade(config, REVISION_0048)
    command.downgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        head = connection.execute(
            text(
                "SELECT composition_version, source_hash FROM pagecomposition "
                "WHERE id = :id"
            ),
            {"id": seeded["composition_id"]},
        ).one()
        assert tuple(head) == (seeded["version"], seeded["source_hash"])
        qa = connection.execute(
            text(
                "SELECT composition_version, composition_source_hash "
                "FROM generatedpageqaresult WHERE id = :id"
            ),
            {"id": seeded["qa_id"]},
        ).one()
        assert tuple(qa) == (seeded["version"], seeded["source_hash"])
    engine.dispose()
    get_settings.cache_clear()


def test_0048_successor_history_blocks_downgrade_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    migration, _ = _migration_module()
    database = tmp_path / "composition-history-successor-downgrade.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    seeded = _seed_bound_composition(engine)
    engine.dispose()
    command.upgrade(config, REVISION_0048)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        root = connection.execute(text(f"SELECT * FROM {TABLE}")).mappings().one()
        successor = dict(root)
        successor.pop("id")
        successor["composition_version"] = int(root["composition_version"]) + 1
        successor["supersedes_revision_id"] = root["id"]
        successor["supersedes_revision_hash"] = root["revision_hash"]
        successor["lineage_kind"] = "successor"
        successor["recorded_by"] = "migration-test"
        successor["record_source"] = "composition_refresh"
        for field in (
            "generated_components",
            "operator_decisions",
            "source_snapshot",
        ):
            successor[field] = __import__("json").loads(successor[field])
        successor["revision_hash"] = migration._composition_revision_hash(successor)
        for field in ("generated_at", "decided_at", "recorded_at"):
            if successor[field] is not None and isinstance(successor[field], str):
                successor[field] = datetime.fromisoformat(successor[field])
        connection.execute(sa.insert(PageCompositionRevision).values(**successor))
    before_schema = _schema_snapshot(engine)
    engine.dispose()

    with pytest.raises(RuntimeError, match="post-migration revisions"):
        command.downgrade(config, REVISION_0047)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert _schema_snapshot(engine) == before_schema
    with engine.connect() as connection:
        assert connection.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() == 2
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0048
    engine.dispose()
    get_settings.cache_clear()
