from datetime import UTC, datetime
import importlib.util
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import JSON, Integer, String, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel

from app.core.config import get_settings
from app.models import (
    Business,
    GeneratedPage,
    PlannedPage,
    SitePlan,
    Website,
    WebsiteMediaPlanningRecord,
)
from app.models import entities  # noqa: F401


BACKEND = Path(__file__).parents[1]
PLANNING_TABLE = "websitemediaplanningrecord"
REQUIREMENT_TABLE = "plannedpagemediarequirement"


def _migration_module():
    path = BACKEND / "alembic" / "versions" / "20260807_0041_page_media_planning_provenance.py"
    spec = importlib.util.spec_from_file_location("page_media_migration_0041", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

IMAGE_GOVERNANCE_COLUMNS = {
    "website_id",
    "media_key",
    "media_version",
    "mime_type",
    "file_size",
    "width",
    "height",
    "checksum_sha256",
    "managed_storage_path",
    "acquisition_source",
    "creator_source_identity",
    "created_by",
    "reviewed_alt_text",
    "provenance_type",
    "provenance_notes",
    "rights_status",
    "rights_holder",
    "rights_notes",
    "approved_usage",
    "prohibited_usage",
    "permitted_placement_keys",
    "accessibility_intent",
    "governance_status",
    "approval_version",
    "approved_by",
    "approved_at",
    "retired_by",
    "retirement_rationale",
    "retired_at",
    "replaces_image_metadata_id",
    "gps_metadata_status",
    "gps_metadata",
    "gps_authorized_by",
    "gps_authorized_at",
    "gps_authorization_notes",
    "exif_status",
}

ASSIGNMENT_GOVERNANCE_COLUMNS = {
    "website_id",
    "site_plan_id",
    "planned_page_id",
    "media_requirement_id",
    "assignment_version",
    "media_version",
    "placement_contract_version",
    "assigned_by",
    "assignment_rationale",
    "assigned_at",
    "replaced_by",
    "replacement_rationale",
    "replaced_at",
    "retired_by",
    "retirement_rationale",
    "retired_at",
    "replaces_page_image_assignment_id",
}

REQUIREMENT_CONTRACT_COLUMNS = {
    "planning_record_id",
    "crop_intent",
    "focal_point_intent",
    "responsive_behavior",
    "accessibility_intent",
    "caption_intent",
    "approved_source_constraints",
    "permitted_reuse_policy",
    "replacement_policy",
    "compatible_page_types",
}


def _config(monkeypatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def _column_names(inspector, table: str) -> set[str]:
    return {item["name"] for item in inspector.get_columns(table)}


def _columns_by_name(inspector, table: str) -> dict[str, dict]:
    return {item["name"]: item for item in inspector.get_columns(table)}


def _check_names(inspector, table: str) -> set[str]:
    return {
        item["name"]
        for item in inspector.get_check_constraints(table)
        if item.get("name")
    }


def _seed_scope(engine) -> tuple[int, int, int, int, int]:
    with Session(engine) as session:
        business = Business(
            company_name="Preserved Media Company",
            business_type="test",
            state="FL",
        )
        session.add(business)
        session.flush()
        website = Website(
            business_id=business.id,
            website_name="Preserved Website",
            domain="media-preserved.example.test",
            public_url="https://media-preserved.example.test",
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
        generated = GeneratedPage(
            business_id=business.id,
            website_id=website.id,
            page_type="home",
            page_title="Preserved Home",
            page_slug="home",
        )
        session.add(generated)
        session.flush()
        planned = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type="home",
            working_name="Preserved Home",
            intended_slug="home",
            generated_page_id=generated.id,
        )
        session.add(planned)
        session.commit()
        return (
            business.id or 0,
            website.id or 0,
            plan.id or 0,
            planned.id or 0,
            generated.id or 0,
        )


def test_0041_check_canonicalization_accepts_postgresql_membership_rewrites_only():
    migration = _migration_module()
    expected_in = "requirement_state IN ('required','advisory','excluded','deferred')"
    authoritative_postgres_in = (
        "requirement_state::text = ANY "
        "(ARRAY['required'::character varying, 'advisory'::character varying, "
        "'excluded'::character varying, 'deferred'::character varying]::text[])"
    )
    postgres_in = (
        "CHECK (((requirement_state)::text = ANY "
        "((ARRAY['required'::character varying, 'advisory'::character varying, "
        "'excluded'::character varying, 'deferred'::character varying])::text[])))"
    )
    assert migration._canonical(authoritative_postgres_in) == migration._canonical(
        expected_in
    )
    assert migration._canonical(postgres_in) == migration._canonical(expected_in)
    assert migration._canonical(postgres_in.replace("deferred", "blocked")) != migration._canonical(
        expected_in
    )
    assert migration._canonical(
        postgres_in.replace("requirement_state", "lifecycle_status")
    ) != migration._canonical(expected_in)
    assert migration._canonical(
        postgres_in.replace("'required'", "'REQUIRED'")
    ) != migration._canonical(expected_in)
    assert migration._canonical(
        postgres_in.replace("requirement_state", '"Requirement_State"')
    ) != migration._canonical(expected_in)
    assert migration._canonical(
        postgres_in.replace("= ANY", "<> ALL")
    ) != migration._canonical(expected_in)
    assert migration._canonical("minimum_width >= 1") != migration._canonical(
        "minimum_width >= 2"
    )

    expected_not_in = (
        "governance_status NOT IN ('approved','retired') OR "
        "(approval_version IS NOT NULL AND approved_by IS NOT NULL AND approved_at IS NOT NULL)"
    )
    postgres_not_in = (
        "CHECK ((((governance_status)::text <> ALL "
        "((ARRAY['approved'::character varying, 'retired'::character varying])::text[])) "
        "OR ((approval_version IS NOT NULL) AND (approved_by IS NOT NULL) "
        "AND (approved_at IS NOT NULL))))"
    )
    assert migration._canonical(postgres_not_in) == migration._canonical(expected_not_in)
    authoritative_postgres_not_in = (
        "governance_status::text <> ALL "
        "(ARRAY['approved'::character varying, 'retired'::character varying]::text[]) "
        "OR (approval_version IS NOT NULL AND approved_by IS NOT NULL "
        "AND approved_at IS NOT NULL)"
    )
    assert migration._canonical(
        authoritative_postgres_not_in
    ) == migration._canonical(expected_not_in)
    assert migration._canonical(
        "(approval_version IS NULL AND approved_by IS NULL) OR approved_at IS NOT NULL"
    ) != migration._canonical(
        "approval_version IS NULL AND (approved_by IS NULL OR approved_at IS NOT NULL)"
    )


@pytest.mark.parametrize(
    "observed",
    [
        "requirement_state::text <> ALL "
        "(ARRAY['required'::character varying, 'advisory'::character varying, "
        "'excluded'::character varying, 'deferred'::character varying]::text[])",
        "lifecycle_status::text = ANY "
        "(ARRAY['required'::character varying, 'advisory'::character varying, "
        "'excluded'::character varying, 'deferred'::character varying]::text[])",
        "requirement_state::text = ANY "
        "(ARRAY['required'::character varying, 'advisory'::character varying, "
        "'excluded'::character varying, 'blocked'::character varying]::text[])",
        "requirement_state::text = ANY "
        "(ARRAY['required'::character varying, 'advisory'::character varying, "
        "'excluded'::character varying, 'deferred'::character varying]::text[]) "
        "OR requirement_state IS NULL",
        "requirement_state = 'required' OR "
        "(requirement_state = 'advisory' AND requirement_state = 'excluded')",
    ],
    ids=[
        "changed-operator",
        "changed-column",
        "changed-literal",
        "appended-clause",
        "changed-logical-grouping",
    ],
)
def test_0041_check_canonicalization_rejects_semantic_changes(observed):
    migration = _migration_module()
    expected = "requirement_state IN ('required','advisory','excluded','deferred')"
    assert migration._canonical(observed) != migration._canonical(expected)


def test_0041_check_canonicalization_preserves_literal_whitespace():
    migration = _migration_module()

    assert migration._canonical("value = 'a  b'") != migration._canonical(
        "value = 'a b'"
    )


def test_0041_exact_check_contract_rejects_missing_incompatible_and_unknown():
    migration = _migration_module()
    table = "websitemediaplanningrecord"
    required = {"ck_websitemediaplanningrecord_version": "version >= 1"}

    migration._validate_check_contracts(
        table,
        dict(required),
        required,
        reject_unexpected=True,
    )
    with pytest.raises(RuntimeError, match="version differs"):
        migration._validate_check_contracts(
            table,
            {},
            required,
            reject_unexpected=True,
        )
    with pytest.raises(RuntimeError, match="version differs"):
        migration._validate_check_contracts(
            table,
            {"ck_websitemediaplanningrecord_version": "version >= 2"},
            required,
            reject_unexpected=True,
        )
    with pytest.raises(RuntimeError, match="unexpected CHECK constraint"):
        migration._validate_check_contracts(
            table,
            {
                **required,
                "ck_websitemediaplanningrecord_unknown": "version < 100",
            },
            required,
            reject_unexpected=True,
        )


def test_0041_exact_check_contract_allows_only_exact_scoped_0042_forward_check():
    migration = _migration_module()
    table = "plannedpagemediarequirement"
    required = {"ck_plannedpagemediarequirement_version": "version >= 1"}
    forward = migration.ALLOWED_FORWARD_CHECKS_BY_TABLE[table]

    postgres_forward = (
        "contract_version < 2 OR target_component_instance_key IS NOT NULL "
        "AND length(TRIM(BOTH FROM target_component_instance_key)) > 0"
    )
    migration._validate_check_contracts(
        table,
        {
            **required,
            "ck_plannedpagemediarequirement_v2_target": postgres_forward,
        },
        required,
        allowed_additional=forward,
        reject_unexpected=True,
    )
    name, expression = next(iter(forward.items()))
    with pytest.raises(RuntimeError, match=f"{name} differs"):
        migration._validate_check_contracts(
            table,
            {**required, name: expression.replace("> 0", "> 1")},
            required,
            allowed_additional=forward,
            reject_unexpected=True,
        )
    with pytest.raises(RuntimeError, match="unexpected CHECK constraint"):
        migration._validate_check_contracts(
            "websitemediaplanningrecord",
            {
                "ck_websitemediaplanningrecord_version": "version >= 1",
                name: expression,
            },
            {"ck_websitemediaplanningrecord_version": "version >= 1"},
            reject_unexpected=True,
        )


@pytest.mark.parametrize(
    "rows, expected",
    [
        ([{"name": None, "sqltext": "version >= 1"}], "unnamed CHECK"),
        (
            [
                {"name": "ck_duplicate", "sqltext": "version >= 1"},
                {"name": "ck_duplicate", "sqltext": "version >= 1"},
            ],
            "duplicate CHECK",
        ),
    ],
)
def test_0041_strict_check_inspection_rejects_unnamed_or_duplicate(
    monkeypatch,
    rows,
    expected,
):
    migration = _migration_module()

    class Inspector:
        @staticmethod
        def get_check_constraints(_table):
            return rows

    monkeypatch.setattr(migration, "_inspector", lambda: Inspector())
    with pytest.raises(RuntimeError, match=expected):
        migration._checks("websitemediaplanningrecord", strict_names=True)


def test_0041_downgrade_skips_unique_constraint_backing_indexes():
    migration = _migration_module()
    partial = ("uq_pageimageassignment_active_requirement",)
    removed = {"media_requirement_id", "assignment_version"}

    assert not migration._downgrade_owns_index(
        {
            "name": "uq_pageimageassignment_requirement_version",
            "column_names": ["media_requirement_id", "assignment_version"],
            "duplicates_constraint": "uq_pageimageassignment_requirement_version",
        },
        partial_indexes=partial,
        removed_columns=removed,
    )
    assert migration._downgrade_owns_index(
        {
            "name": "uq_pageimageassignment_active_requirement",
            "column_names": ["media_requirement_id"],
            "duplicates_constraint": None,
        },
        partial_indexes=partial,
        removed_columns=removed,
    )
    assert migration._downgrade_owns_index(
        {
            "name": "ix_pageimageassignment_media_requirement_id",
            "column_names": ["media_requirement_id"],
            "duplicates_constraint": None,
        },
        partial_indexes=partial,
        removed_columns=removed,
    )
    assert not migration._downgrade_owns_index(
        {
            "name": "ix_pageimageassignment_status",
            "column_names": ["status"],
            "duplicates_constraint": None,
        },
        partial_indexes=partial,
        removed_columns=removed,
    )


def test_0041_adds_page_media_planning_and_governance_on_clean_database(
    monkeypatch,
    tmp_path,
) -> None:
    database = tmp_path / "page-media-clean.sqlite3"
    config = _config(monkeypatch, database)

    command.upgrade(config, "20260813_0045")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    assert {PLANNING_TABLE, REQUIREMENT_TABLE} <= set(inspector.get_table_names())
    assert REQUIREMENT_CONTRACT_COLUMNS <= _column_names(inspector, REQUIREMENT_TABLE)
    assert not {
        "media_planning_record_id",
        "crop_requirements",
        "focal_point_requirements",
        "responsive_requirements",
        "accessibility_requirements",
        "caption_requirements",
        "source_constraints",
        "reuse_constraints",
        "replacement_constraints",
    } & _column_names(inspector, REQUIREMENT_TABLE)
    requirement_columns = _columns_by_name(inspector, REQUIREMENT_TABLE)
    for column in (
        "planning_record_id",
        "minimum_width",
        "minimum_height",
    ):
        assert isinstance(requirement_columns[column]["type"], Integer)
        assert requirement_columns[column]["nullable"] is False
    for column in (
        "crop_intent",
        "focal_point_intent",
        "responsive_behavior",
        "accessibility_intent",
        "permitted_reuse_policy",
        "replacement_policy",
    ):
        assert isinstance(requirement_columns[column]["type"], String)
        assert requirement_columns[column]["nullable"] is False
    assert isinstance(requirement_columns["caption_intent"]["type"], String)
    assert requirement_columns["caption_intent"]["nullable"] is True
    for column in ("approved_source_constraints", "compatible_page_types"):
        assert isinstance(requirement_columns[column]["type"], JSON)
        assert requirement_columns[column]["nullable"] is False
    assert IMAGE_GOVERNANCE_COLUMNS <= _column_names(inspector, "imagemetadata")
    assert ASSIGNMENT_GOVERNANCE_COLUMNS <= _column_names(
        inspector, "pageimageassignment"
    )
    assert "ck_websitemediaplanningrecord_version" in _check_names(
        inspector, PLANNING_TABLE
    )
    assert "ck_plannedpagemediarequirement_replacement" in _check_names(
        inspector, REQUIREMENT_TABLE
    )
    assert "ck_imagemetadata_governed_completeness" in _check_names(
        inspector, "imagemetadata"
    )
    assert "ck_pageimageassignment_governed_binding" in _check_names(
        inspector, "pageimageassignment"
    )
    assert "uq_plannedpagemediarequirement_active_placement" in {
        item["name"] for item in inspector.get_indexes(REQUIREMENT_TABLE)
    }
    assert "uq_pageimageassignment_active_requirement" in {
        item["name"] for item in inspector.get_indexes("pageimageassignment")
    }
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260813_0045"
    get_settings.cache_clear()


def test_0041_preserves_legacy_media_rows_and_assignments_exactly(
    monkeypatch,
    tmp_path,
) -> None:
    database = tmp_path / "page-media-populated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260805_0040")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    business_id, _website_id, _plan_id, _planned_id, generated_id = _seed_scope(
        engine
    )
    now = datetime.now(UTC).isoformat()
    with engine.begin() as connection:
        image_id = connection.execute(
            text(
                "INSERT INTO imagemetadata "
                "(created_at, updated_at, business_id, file_name, focal_x, focal_y, "
                "image_role, review_status, geo_state, exif_status) "
                "VALUES (:now, :now, :business_id, 'legacy-image.png', 0.25, 0.75, "
                "'hero', 'reviewed', 'FL', 'optimized_copy_stripped') "
                "RETURNING id"
            ),
            {"now": now, "business_id": business_id},
        ).scalar_one()
        assignment_id = connection.execute(
            text(
                "INSERT INTO pageimageassignment "
                "(created_at, updated_at, generated_page_id, image_metadata_id, "
                "image_role, sort_order, display_preset, status) "
                "VALUES (:now, :now, :page_id, :image_id, 'hero', 0, "
                "'hero_desktop', 'active') RETURNING id"
            ),
            {
                "now": now,
                "page_id": generated_id,
                "image_id": image_id,
            },
        ).scalar_one()

    command.upgrade(config, "20260813_0045")

    with engine.connect() as connection:
        legacy_image = connection.execute(
            text(
                "SELECT id, business_id, file_name, focal_x, focal_y, image_role, "
                "review_status, governance_status, website_id, media_key, "
                "checksum_sha256 FROM imagemetadata WHERE id=:image_id"
            ),
            {"image_id": image_id},
        ).one()
        assert tuple(legacy_image) == (
            image_id,
            business_id,
            "legacy-image.png",
            0.25,
            0.75,
            "hero",
            "reviewed",
            "legacy_unverified",
            None,
            None,
            None,
        )
        legacy_assignment = connection.execute(
            text(
                "SELECT id, generated_page_id, image_metadata_id, image_role, "
                "sort_order, display_preset, status, website_id, site_plan_id, "
                "planned_page_id, media_requirement_id, assignment_version "
                "FROM pageimageassignment WHERE id=:assignment_id"
            ),
            {"assignment_id": assignment_id},
        ).one()
        assert tuple(legacy_assignment) == (
            assignment_id,
            generated_id,
            image_id,
            "hero",
            0,
            "hero_desktop",
            "active",
            None,
            None,
            None,
            None,
            None,
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE imagemetadata SET governance_status='pending_review' "
                    "WHERE id=:image_id"
                ),
                {"image_id": image_id},
            )
    get_settings.cache_clear()


def test_0041_adopts_compatible_precreated_planning_tables(
    monkeypatch,
    tmp_path,
) -> None:
    database = tmp_path / "page-media-precreated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260805_0040")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    SQLModel.metadata.tables[PLANNING_TABLE].create(engine)
    SQLModel.metadata.tables[REQUIREMENT_TABLE].create(engine)

    command.upgrade(config, "20260813_0045")

    with engine.connect() as connection:
        assert connection.execute(
            text(f"SELECT COUNT(*) FROM {PLANNING_TABLE}")
        ).scalar_one() == 0
        assert connection.execute(
            text(f"SELECT COUNT(*) FROM {REQUIREMENT_TABLE}")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260813_0045"
    get_settings.cache_clear()


def test_0041_rejects_incompatible_precreated_planning_table(
    monkeypatch,
    tmp_path,
) -> None:
    database = tmp_path / "page-media-incompatible.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260805_0040")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE websitemediaplanningrecord (
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    id INTEGER NOT NULL PRIMARY KEY,
                    website_id INTEGER NOT NULL,
                    business_id INTEGER NOT NULL,
                    site_plan_id INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    algorithm_version VARCHAR(80) NOT NULL,
                    generated_media_suggestions JSON NOT NULL,
                    source_snapshot JSON NOT NULL,
                    source_hash VARCHAR(64) NOT NULL,
                    generated_at DATETIME NOT NULL,
                    replaces_record_id INTEGER,
                    UNIQUE (site_plan_id, version)
                )
                """
            )
        )

    with pytest.raises(
        RuntimeError,
        match="ck_websitemediaplanningrecord_version differs",
    ):
        command.upgrade(config, "20260813_0045")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260805_0040"
    get_settings.cache_clear()


def test_0041_clean_downgrade_removes_only_additive_page_media_schema(
    monkeypatch,
    tmp_path,
) -> None:
    database = tmp_path / "page-media-clean-downgrade.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260813_0045")

    command.downgrade(config, "20260805_0040")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    assert PLANNING_TABLE not in inspector.get_table_names()
    assert REQUIREMENT_TABLE not in inspector.get_table_names()
    assert not (
        set(IMAGE_GOVERNANCE_COLUMNS) - {"reviewed_alt_text", "exif_status"}
    ) & _column_names(inspector, "imagemetadata")
    assert not ASSIGNMENT_GOVERNANCE_COLUMNS & _column_names(
        inspector,
        "pageimageassignment",
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260805_0040"
    get_settings.cache_clear()


def test_0041_populated_downgrade_blocks_durable_media_planning_loss(
    monkeypatch,
    tmp_path,
) -> None:
    database = tmp_path / "page-media-populated-downgrade.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260813_0045")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    business_id, website_id, plan_id, _planned_id, _generated_id = _seed_scope(
        engine
    )
    with Session(engine) as session:
        session.add(
            WebsiteMediaPlanningRecord(
                website_id=website_id,
                business_id=business_id,
                site_plan_id=plan_id,
                version=1,
                algorithm_version="page-media-planning-v1",
                generated_media_suggestions=[],
                source_snapshot={},
                source_hash="a" * 64,
            )
        )
        session.commit()

    with pytest.raises(
        RuntimeError,
        match="durable Website media planning records exist",
    ):
        command.downgrade(config, "20260805_0040")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260807_0041"
        assert connection.execute(
            text(f"SELECT COUNT(*) FROM {PLANNING_TABLE}")
        ).scalar_one() == 1
    get_settings.cache_clear()
