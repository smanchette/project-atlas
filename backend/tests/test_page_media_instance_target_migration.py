from datetime import UTC, datetime
import importlib.util
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
import pytest
from sqlalchemy import String, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.core.config import get_settings
from app.models import (
    Business,
    PlannedPage,
    PlannedPageMediaRequirement,
    SitePlan,
    Website,
    WebsiteMediaPlanningRecord,
)
from app.models import entities  # noqa: F401
from app.schemas.page_media_planning import PageMediaPlacementDecisionRequest


BACKEND = Path(__file__).parents[1]
REVISION_0045 = "20260813_0045"
TABLE = "plannedpagemediarequirement"
TARGET_COLUMN = "target_component_instance_key"
TARGET_CHECK = "ck_plannedpagemediarequirement_v2_target"
ACTIVE_TARGET_INDEX = "uq_plannedpagemediarequirement_active_target"
COLUMN_INDEX = "ix_plannedpagemediarequirement_target_component_instance_key"


def _migration_module():
    path = (
        BACKEND
        / "alembic"
        / "versions"
        / "20260809_0042_media_contract_instance_targeting.py"
    )
    spec = importlib.util.spec_from_file_location("media_instance_migration_0042", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config(monkeypatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def _run_migration_upgrade(migration, monkeypatch, engine) -> None:
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()


def _seed_scope(engine) -> tuple[int, int, int, int, int]:
    with Session(engine) as session:
        business = Business(
            company_name="Exact Target Test Company",
            business_type="test",
            state="FL",
        )
        session.add(business)
        session.flush()
        website = Website(
            business_id=business.id,
            website_name="Exact Target Website",
            domain="exact-target.example.test",
            public_url="https://exact-target.example.test",
            status="active",
        )
        session.add(website)
        session.flush()
        plan = SitePlan(
            website_id=website.id,
            plan_key="primary",
            plan_name="Primary Site Plan",
        )
        session.add(plan)
        session.flush()
        page = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type="home",
            working_name="Home",
            intended_slug="home",
        )
        session.add(page)
        session.flush()
        planning = WebsiteMediaPlanningRecord(
            website_id=website.id,
            business_id=business.id,
            site_plan_id=plan.id,
            version=1,
            algorithm_version="page-media-planning-v1",
            generated_media_suggestions=[],
            source_snapshot={},
            source_hash="a" * 64,
        )
        session.add(planning)
        session.commit()
        return (
            business.id or 0,
            website.id or 0,
            plan.id or 0,
            page.id or 0,
            planning.id or 0,
        )


def _requirement(
    *,
    business_id: int,
    website_id: int,
    plan_id: int,
    page_id: int,
    planning_id: int,
    placement_key: str,
    contract_version: int,
    target: str | None,
) -> PlannedPageMediaRequirement:
    return PlannedPageMediaRequirement(
        website_id=website_id,
        business_id=business_id,
        site_plan_id=plan_id,
        planned_page_id=page_id,
        planning_record_id=planning_id,
        component_or_section="content_section",
        target_component_instance_key=target,
        placement_key=placement_key,
        contract_version=contract_version,
        version=1,
        requirement_state="advisory",
        purpose="Explain approved page information visually.",
        customer_outcome="Understand the approved page information.",
        intended_subject="Approved page information",
        orientation="landscape",
        aspect_ratio="16:9",
        minimum_width=1200,
        minimum_height=675,
        crop_intent="Preserve the approved subject.",
        focal_point_intent="Keep the approved subject visible.",
        responsive_behavior="Scale without distortion.",
        accessibility_intent="Describe the approved subject.",
        approved_source_constraints=["approved_company_media"],
        permitted_reuse_policy="website_scoped",
        replacement_policy="operator_approval_required",
        compatible_page_types=["home"],
        decided_by="Test Operator",
        rationale="Exercise exact component-instance targeting.",
    )


def test_0042_check_canonicalization_accepts_postgresql_trim_rewrite_only() -> None:
    migration = _migration_module()
    expected = migration.V2_COMPLETENESS
    postgres = (
        "CHECK (((contract_version < 2) OR "
        "((target_component_instance_key IS NOT NULL) AND "
        "(length(TRIM(BOTH FROM (target_component_instance_key)::text)) > 0))))"
    )
    assert migration._canonical(postgres) == migration._canonical(expected)
    assert migration._canonical(postgres.replace("> 0", "> 1")) != migration._canonical(
        expected
    )
    assert migration._canonical(
        postgres.replace("contract_version < 2", "contract_version < 3")
    ) != migration._canonical(expected)
    postgres_predicate = (
        "(((lifecycle_status)::text = 'active'::text) AND "
        "(target_component_instance_key IS NOT NULL))"
    )
    assert migration._canonical(postgres_predicate) == migration._canonical(
        migration.ACTIVE_TARGET_PREDICATE
    )


def test_0042_adds_nullable_exact_target_contract_and_indexes(
    monkeypatch,
    tmp_path,
) -> None:
    database = tmp_path / "media-target-clean.sqlite3"
    config = _config(monkeypatch, database)

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    column = {
        item["name"]: item for item in inspector.get_columns(TABLE)
    }[TARGET_COLUMN]
    assert isinstance(column["type"], String)
    assert column["type"].length == 200
    assert column["nullable"] is True
    assert TARGET_CHECK in {
        item["name"]
        for item in inspector.get_check_constraints(TABLE)
        if item.get("name")
    }
    indexes = {
        item["name"]: item
        for item in inspector.get_indexes(TABLE)
        if item.get("name")
    }
    assert indexes[ACTIVE_TARGET_INDEX]["unique"] == 1
    assert tuple(indexes[ACTIVE_TARGET_INDEX]["column_names"]) == (
        "planned_page_id",
        TARGET_COLUMN,
    )
    migration = _migration_module()
    assert migration._canonical(
        migration._index_predicate(indexes[ACTIVE_TARGET_INDEX])
    ) == migration._canonical(migration.ACTIVE_TARGET_PREDICATE)
    assert indexes[COLUMN_INDEX]["unique"] == 0
    assert tuple(indexes[COLUMN_INDEX]["column_names"]) == (TARGET_COLUMN,)
    assert migration._index_predicate(indexes[COLUMN_INDEX]) == ""
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260820_0048"
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("suffix", "index_sql"),
    (
        (
            "full",
            f"CREATE UNIQUE INDEX {ACTIVE_TARGET_INDEX} ON {TABLE} "
            f"(planned_page_id, {TARGET_COLUMN})",
        ),
        (
            "wrong-partial",
            f"CREATE UNIQUE INDEX {ACTIVE_TARGET_INDEX} ON {TABLE} "
            f"(planned_page_id, {TARGET_COLUMN}) WHERE "
            "lifecycle_status = 'superseded' AND "
            f"{TARGET_COLUMN} IS NOT NULL",
        ),
    ),
)
def test_0042_rejects_same_named_active_index_with_incompatible_predicate(
    monkeypatch,
    tmp_path,
    suffix,
    index_sql,
) -> None:
    database = tmp_path / f"media-target-active-index-{suffix}.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text(f"DROP INDEX {ACTIVE_TARGET_INDEX}"))
        connection.execute(text(index_sql))

    migration = _migration_module()
    with pytest.raises(
        RuntimeError,
        match="active target index is incompatible",
    ):
        _run_migration_upgrade(migration, monkeypatch, engine)
    get_settings.cache_clear()


def test_0042_rejects_same_named_incompatible_target_column_index(
    monkeypatch,
    tmp_path,
) -> None:
    database = tmp_path / "media-target-column-index-incompatible.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text(f"DROP INDEX {COLUMN_INDEX}"))
        connection.execute(
            text(
                f"CREATE UNIQUE INDEX {COLUMN_INDEX} ON {TABLE} "
                f"({TARGET_COLUMN})"
            )
        )

    migration = _migration_module()
    with pytest.raises(
        RuntimeError,
        match="target column index is incompatible",
    ):
        _run_migration_upgrade(migration, monkeypatch, engine)
    get_settings.cache_clear()


def test_0042_preserves_v1_null_and_enforces_v2_nonblank_unique_active_target(
    monkeypatch,
    tmp_path,
) -> None:
    database = tmp_path / "media-target-constraints.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    business_id, website_id, plan_id, page_id, planning_id = _seed_scope(engine)
    common = {
        "business_id": business_id,
        "website_id": website_id,
        "plan_id": plan_id,
        "page_id": page_id,
        "planning_id": planning_id,
    }

    with Session(engine) as session:
        session.add(
            _requirement(
                **common,
                placement_key="legacy-v1",
                contract_version=1,
                target=None,
            )
        )
        session.commit()

    for placement_key, target in (("v2-missing", None), ("v2-blank", "   ")):
        with pytest.raises(IntegrityError):
            with Session(engine) as session:
                session.add(
                    _requirement(
                        **common,
                        placement_key=placement_key,
                        contract_version=2,
                        target=target,
                    )
                )
                session.commit()

    with Session(engine) as session:
        session.add(
            _requirement(
                **common,
                placement_key="v2-first",
                contract_version=2,
                target="content_section:service-overview",
            )
        )
        session.commit()

    with pytest.raises(IntegrityError):
        with Session(engine) as session:
            session.add(
                _requirement(
                    **common,
                    placement_key="v2-duplicate-target",
                    contract_version=2,
                    target="content_section:service-overview",
                )
            )
            session.commit()
    get_settings.cache_clear()


def test_0042_preserves_existing_v1_rows_during_upgrade(monkeypatch, tmp_path) -> None:
    database = tmp_path / "media-target-v1-preservation.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260807_0041")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    business_id, website_id, plan_id, page_id, planning_id = _seed_scope(engine)
    now = datetime.now(UTC).isoformat()
    with engine.begin() as connection:
        requirement_id = connection.execute(
            text(
                "INSERT INTO plannedpagemediarequirement ("
                "created_at, updated_at, website_id, business_id, site_plan_id, "
                "planned_page_id, planning_record_id, component_or_section, "
                "placement_key, contract_version, version, requirement_state, "
                "purpose, customer_outcome, intended_subject, orientation, "
                "aspect_ratio, minimum_width, minimum_height, crop_intent, "
                "focal_point_intent, responsive_behavior, accessibility_intent, "
                "caption_intent, approved_source_constraints, permitted_reuse_policy, "
                "replacement_policy, compatible_page_types, source_suggestion_key, "
                "decided_by, rationale, decided_at, lifecycle_status, "
                "replaces_requirement_id) VALUES ("
                ":now, :now, :website_id, :business_id, :site_plan_id, :page_id, "
                ":planning_id, 'content_section', 'legacy-v1', 1, 1, 'advisory', "
                "'Legacy purpose', 'Legacy outcome', 'Legacy subject', 'landscape', "
                "'16:9', 1200, 675, 'Preserve subject', 'Center subject', "
                "'Scale safely', 'Describe subject', NULL, '[]', 'website_scoped', "
                "'operator_approval_required', '[\"home\"]', NULL, 'Test Operator', "
                "'Preserve V1', :now, 'active', NULL) RETURNING id"
            ),
            {
                "now": now,
                "website_id": website_id,
                "business_id": business_id,
                "site_plan_id": plan_id,
                "page_id": page_id,
                "planning_id": planning_id,
            },
        ).scalar_one()

    command.upgrade(config, "head")

    with engine.connect() as connection:
        preserved = connection.execute(
            text(
                "SELECT placement_key, contract_version, "
                "target_component_instance_key, lifecycle_status "
                "FROM plannedpagemediarequirement WHERE id=:requirement_id"
            ),
            {"requirement_id": requirement_id},
        ).one()
        assert tuple(preserved) == ("legacy-v1", 1, None, "active")
    get_settings.cache_clear()


def test_0042_guarded_downgrade_blocks_exact_instance_contract_loss(
    monkeypatch,
    tmp_path,
) -> None:
    database = tmp_path / "media-target-guarded-downgrade.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0045)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    business_id, website_id, plan_id, page_id, planning_id = _seed_scope(engine)
    with Session(engine) as session:
        session.add(
            _requirement(
                business_id=business_id,
                website_id=website_id,
                plan_id=plan_id,
                page_id=page_id,
                planning_id=planning_id,
                placement_key="v2-target",
                contract_version=2,
                target="content_section:service-overview",
            )
        )
        session.commit()

    with pytest.raises(
        RuntimeError,
        match="durable exact-instance media contracts exist",
    ):
        command.downgrade(config, "20260807_0041")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260809_0042"
        assert connection.execute(
            text(
                "SELECT target_component_instance_key "
                "FROM plannedpagemediarequirement WHERE placement_key='v2-target'"
            )
        ).scalar_one() == "content_section:service-overview"
    get_settings.cache_clear()


def test_0042_empty_schema_downgrades_and_reupgrades_cleanly(
    monkeypatch,
    tmp_path,
) -> None:
    database = tmp_path / "media-target-reversible.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0045)

    command.downgrade(config, "20260807_0041")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    assert TARGET_COLUMN not in {
        item["name"] for item in inspector.get_columns(TABLE)
    }
    assert TARGET_CHECK not in {
        item["name"]
        for item in inspector.get_check_constraints(TABLE)
        if item.get("name")
    }
    assert ACTIVE_TARGET_INDEX not in {
        item["name"]
        for item in inspector.get_indexes(TABLE)
        if item.get("name")
    }
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260807_0041"

    command.upgrade(config, REVISION_0045)

    inspector = inspect(engine)
    assert TARGET_COLUMN in {
        item["name"] for item in inspector.get_columns(TABLE)
    }
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260813_0045"
    get_settings.cache_clear()


def test_exact_target_request_schema_enforces_200_character_bound() -> None:
    base = {
        "website_id": 1,
        "site_plan_id": 1,
        "planned_page_id": 1,
        "placement_key": "home-evidence",
        "requirement_state": "advisory",
        "decided_by": "Test Operator",
        "rationale": "Approved exact target.",
        "expected_planning_version": 2,
    }
    payload = PageMediaPlacementDecisionRequest(
        **base,
        target_component_instance_key="content_section:" + "x" * 184,
    )
    assert len(payload.target_component_instance_key or "") == 200
    with pytest.raises(ValidationError):
        PageMediaPlacementDecisionRequest(
            **base,
            target_component_instance_key="content_section:" + "x" * 185,
        )
