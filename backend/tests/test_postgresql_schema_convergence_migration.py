from __future__ import annotations

import copy
from dataclasses import replace
import importlib.util
from pathlib import Path
import re
import sys

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa


BACKEND = Path(__file__).parents[1]
MIGRATION_PATH = (
    BACKEND
    / "alembic"
    / "versions"
    / "20260815_0046_postgresql_schema_convergence.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location("atlas_migration_0046", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def migration():
    return _migration_module()


def _sqlite_snapshot(connection) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.exec_driver_sql(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
    )


def _sqlite_operations(connection) -> Operations:
    return Operations(MigrationContext.configure(connection))


def _create_generated_page(connection) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "generatedpage",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    metadata.create_all(connection)


def test_revision_inventory_is_complete_and_counted(migration):
    assert migration.revision == "20260815_0046"
    assert migration.down_revision == "20260813_0045"
    assert len(migration.ACTIVE_TABLES) == 65
    assert len(migration.CLEAN_TABLES) == 62
    assert len(migration.ACTIVE_SEQUENCES) == 64
    assert len(migration.CLEAN_SEQUENCES) == 61
    assert len(migration.RUNTIME_TABLES) == 3
    assert len(migration.TIMESTAMPTZ_COLUMNS) == 24
    assert len(migration.SERVER_DEFAULTS) == 25
    assert len(migration.CHECKS_TO_ADD) == 18
    assert len(migration.RELEVANT_INDEXES) == 3
    assert len(migration.FK_NAME_ALIASES) == 16
    assert len(migration._target_column_contracts("clean")) == 52
    assert migration.ORDINAL_ONLY_COLUMNS == {
        "brandasset": (
            "replaces_brand_asset_id",
            "retired_at",
            "retired_by",
            "retirement_rationale",
        ),
        "city": ("notes", "status"),
        "draftingeligibilityassessment": (
            "assessed_at",
            "evidence",
            "local_value_findings",
            "reasons",
            "semantic_findings",
        ),
        "generatedpage": (
            "draft_content",
            "generated_at",
            "internal_notes",
            "last_reviewed_at",
            "last_reviewed_by",
            "qa_checked_at",
            "qa_result",
            "status",
            "wordpress_post_id",
            "wordpress_url",
        ),
        "imagemetadata": (
            "alt_text",
            "asset_url",
            "caption",
            "county_id",
            "exif_status",
            "file_name",
            "geo_city",
            "geo_state",
            "image_prompt",
            "image_title",
            "notes",
            "optimized_url",
            "original_filename",
            "reviewed_alt_text",
            "stored_filename",
            "thumbnail_url",
        ),
        "pageimageassignment": (
            "override_alt_text",
            "override_focal_x",
            "override_focal_y",
            "status",
        ),
        "plannedpage": ("generated_page_id", "planning_status"),
        "scopedmediaauthorization": (
            "approval_fingerprint",
            "asset_approved_at",
            "asset_approved_by",
            "assignment_version",
            "authorization_fingerprint",
            "authorization_rationale",
            "authorization_terms",
            "authorization_version",
            "authorized_at",
            "authorized_by",
            "lifecycle_status",
            "page_image_assignment_id",
            "reuse_policy",
            "supersedes_authorization_id",
        ),
    }
    assert sum(map(len, migration.ORDINAL_ONLY_COLUMNS.values())) == 57
    assert 3 + 3 + 52 + 18 + 1 + 3 + 57 + 16 == 153


def test_exact_source_classifier_accepts_only_the_two_known_surfaces(migration):
    clean = migration._expected_postgres_surface("clean")
    active = migration._expected_postgres_surface("active")

    assert migration._classify_postgres_surface(clean) == "clean"
    assert migration._classify_postgres_surface(active) == "active"

    canonical = migration._expected_postgres_surface("canonical")
    with pytest.raises(RuntimeError, match="unknown PostgreSQL 0045 schema"):
        migration._classify_postgres_surface(canonical)


@pytest.mark.parametrize(
    "field,mutation",
    [
        ("revision", lambda value: "unknown"),
        ("tables", lambda value: value | {"unknown_table"}),
        ("sequences", lambda value: value | {"unknown_sequence"}),
        (
            "object_counts",
            lambda value: tuple((name, count + (name == "columns")) for name, count in value),
        ),
        (
            "columns",
            lambda value: value[:-1]
            + ((value[-1][0], replace(value[-1][1], type_name="text")),),
        ),
        (
            "checks",
            lambda value: value[:-1] + ((value[-1][0], "changed"),),
        ),
        (
            "indexes",
            lambda value: value[:-1] + ((value[-1][0], None),),
        ),
        ("runtime_tables", lambda value: value[:-1]),
        ("sequence_contracts", lambda value: value[:-1]),
        ("catalog_manifest_sha256", lambda value: "0" * 64),
    ],
)
def test_every_surface_dimension_rejects_unknown_near_matches(
    migration, field, mutation
):
    active = migration._expected_postgres_surface("active")
    changed = replace(active, **{field: mutation(getattr(active, field))})
    with pytest.raises(RuntimeError, match="before DDL"):
        migration._classify_postgres_surface(changed)


def test_only_the_sixteen_payload_guarded_fk_names_are_aliases(migration):
    for key, aliases in migration.FK_NAME_ALIASES.items():
        table, local_columns, referred_table, referred_columns = key
        normalized = {
            migration._foreign_key_manifest_name(
                table=table,
                name=name,
                local_columns=local_columns,
                referred_table=referred_table,
                referred_columns=referred_columns,
            )
            for name in aliases
        }
        assert len(normalized) == 1
        with pytest.raises(RuntimeError, match="unknown foreign-key name"):
            migration._foreign_key_manifest_name(
                table=table,
                name="unknown_same_payload_fkey",
                local_columns=local_columns,
                referred_table=referred_table,
                referred_columns=referred_columns,
            )

    assert (
        migration._foreign_key_manifest_name(
            table="generatedpage",
            name="generatedpage_planned_page_id_fkey",
            local_columns=("planned_page_id",),
            referred_table="plannedpage",
            referred_columns=("id",),
        )
        == "generatedpage_planned_page_id_fkey"
    )


def test_check_normalization_preserves_literals_identifiers_and_grouping(migration):
    expected = "status IN ('Ready','ready') AND (left_id = 1 OR right_id = 2)"
    postgres = (
        "((status)::text = ANY ((ARRAY['Ready'::character varying, "
        "'ready'::character varying])::text[])) AND "
        "((left_id = 1) OR (right_id = 2))"
    )
    assert migration._canonical_check(postgres) == migration._canonical_check(expected)
    assert migration._canonical_check(expected) != migration._canonical_check(
        "status IN ('ready','Ready') AND (left_id = 1 OR right_id = 2)"
    )
    assert migration._canonical_check(expected) != migration._canonical_check(
        "status IN ('Ready','ready') AND left_id = 1 OR right_id = 2"
    )
    assert migration._canonical_check('"Status" = \'Ready\'') != migration._canonical_check(
        '"status" = \'Ready\''
    )


@pytest.mark.parametrize(
    "clean_expression,active_expression",
    [
        (
            "((requirement_state)::text = ANY ((ARRAY["
            "'required'::character varying, 'advisory'::character varying, "
            "'excluded'::character varying, 'deferred'::character varying"
            "])::text[]))",
            "((requirement_state)::text = ANY (ARRAY["
            "('required'::character varying)::text, "
            "('advisory'::character varying)::text, "
            "('excluded'::character varying)::text, "
            "('deferred'::character varying)::text]))",
        ),
        (
            "((lifecycle_status)::text = ANY ((ARRAY["
            "'draft'::character varying, 'approved'::character varying, "
            "'active'::character varying])::text[]))",
            "((lifecycle_status)::text = ANY (ARRAY["
            "('draft'::character varying)::text, "
            "('approved'::character varying)::text, "
            "('active'::character varying)::text]))",
        ),
        (
            "((governance_status)::text <> ALL ((ARRAY["
            "'approved'::character varying, 'retired'::character varying"
            "])::text[]))",
            "((governance_status)::text <> ALL (ARRAY["
            "('approved'::character varying)::text, "
            "('retired'::character varying)::text]))",
        ),
    ],
    ids=("check", "partial-index-predicate", "not-in-check"),
)
def test_manifest_expression_normalization_unifies_pg16_array_deparse_shapes(
    migration, clean_expression, active_expression
):
    assert migration._canonical_manifest_expression(
        clean_expression
    ) == migration._canonical_manifest_expression(active_expression)


def test_manifest_expression_normalization_handles_nested_membership_atoms(migration):
    clean = (
        "((gps_status IS NULL) OR ((requirement_state)::text = ANY ((ARRAY["
        "'required'::character varying, 'advisory'::character varying"
        "])::text[])))"
    )
    active = (
        "((gps_status IS NULL) OR ((requirement_state)::text = ANY (ARRAY["
        "('required'::character varying)::text, "
        "('advisory'::character varying)::text])))"
    )

    assert migration._canonical_manifest_expression(
        clean
    ) == migration._canonical_manifest_expression(active)
    assert migration._canonical_manifest_expression(
        active.replace("::text])))", "::bigint])))")
    ) != migration._canonical_manifest_expression(clean)


@pytest.mark.parametrize(
    "changed",
    [
        "status IN ('Ready','a b') AND (\"ExactName\" = 1 OR other = 2)",
        "status IN ('ready','a  b') AND (\"ExactName\" = 1 OR other = 2)",
        "status IN ('Ready','a  b') AND (\"exactname\" = 1 OR other = 2)",
        "status NOT IN ('Ready','a  b') AND (\"ExactName\" = 1 OR other = 2)",
        "status IN ('Ready','a  b') AND \"ExactName\" = 1 OR other = 2",
        "status IN ('Ready','a  b') AND (\"ExactName\" = 1 OR other = 2) "
        "AND enabled = true",
    ],
)
def test_manifest_expression_normalization_keeps_semantic_changes_distinct(
    migration, changed
):
    original = (
        "status IN ('Ready','a  b') AND (\"ExactName\" = 1 OR other = 2)"
    )
    assert migration._canonical_manifest_expression(
        original
    ) != migration._canonical_manifest_expression(changed)


def test_manifest_expression_normalization_preserves_semantic_casts(migration):
    cast_expression = "value::bigint + 2147483647 > 0"
    uncast_expression = "value + 2147483647 > 0"

    assert migration._canonical_manifest_expression(cast_expression) == cast_expression
    assert migration._canonical_manifest_expression(uncast_expression) == uncast_expression
    assert migration._canonical_manifest_expression(
        cast_expression
    ) != migration._canonical_manifest_expression(uncast_expression)

    membership = (
        "((status)::text = ANY ((ARRAY['ready'::character varying])::text[]))"
    )
    assert migration._canonical_manifest_expression(
        f"({cast_expression}) AND {membership}"
    ) != migration._canonical_manifest_expression(
        f"({uncast_expression}) AND {membership}"
    )


def test_manifest_expression_normalization_preserves_token_boundaries(migration):
    membership = (
        "((status)::text = ANY ((ARRAY['ready'::character varying])::text[]))"
    )

    assert migration._canonical_manifest_expression(
        f"{membership} AND flag IS NULL"
    ) != migration._canonical_manifest_expression(
        f"{membership} AND flagisnull"
    )


def test_manifest_expression_structural_marker_cannot_match_raw_sql(migration):
    membership = (
        "((status)::text = ANY ((ARRAY['ready'::character varying])::text[]))"
    )
    canonical = migration._canonical_manifest_expression(membership)

    assert "\x00atlas_membership:" in canonical
    assert canonical != migration._canonical_manifest_expression("statusin('ready')")


def test_manifest_expression_quote_sentinels_cannot_collide_with_identifiers(migration):
    membership = (
        "((status)::text = ANY ((ARRAY['ready'::character varying])::text[]))"
    )
    expression = f"__atlas_manifest_quoted_0__ = 'literal' AND {membership}"

    canonical = migration._canonical_manifest_expression(expression)
    assert "__atlas_manifest_quoted_0__" in canonical
    assert "'literal'" in canonical


def test_full_catalog_reader_mentions_every_required_semantic_field(migration):
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    required_fragments = {
        "character_maximum_length",
        "numeric_precision",
        "numeric_scale",
        "datetime_precision",
        "domain_schema",
        "domain_name",
        "relpersistence",
        "relrowsecurity",
        "reloptions",
        "reltablespace",
        "partition_bound",
        "indnullsnotdistinct",
        "operator_classes",
        "collations",
        "attribute_definitions",
        "indisvalid",
        "indisready",
        "dependency_type",
        '"kind": "view"',
        '"kind": "type"',
        '"kind": "trigger"',
        '"kind": "extension"',
        '"kind": "schema"',
        '"kind": "policy"',
        '"kind": "routine"',
        '"kind": "rule"',
    }
    assert required_fragments <= set(source.split()) | {
        fragment for fragment in required_fragments if fragment in source
    }
    assert "columns.ordinal_position" not in source
    assert re.search(r"\bAS\s+collation(?:\s|$)", source, re.IGNORECASE) is None
    assert "AS collation_record" in source


def _semantic_record_fixture() -> list[dict[str, object]]:
    return [
        {
            "kind": "table",
            "name": "sample",
            "persistence": "p",
            "row_security": False,
            "force_row_security": False,
            "replica_identity": "d",
            "access_method": "heap",
            "options": None,
            "tablespace": None,
            "partition_parent": None,
            "partition_bound": None,
        },
        {
            "kind": "column",
            "table_name": "sample",
            "column_name": "value",
            "data_type": "character varying",
            "udt_name": "varchar",
            "character_maximum_length": 64,
            "column_default": "'ready'::character varying",
            "is_nullable": "NO",
            "collation_name": None,
            "is_identity": "NO",
            "is_generated": "NEVER",
            "storage_strategy": "x",
            "compression_method": "",
        },
        {
            "kind": "constraint",
            "table": "sample",
            "name": "ck_sample_value",
            "constraint_type": "c",
            "local_columns": (),
            "check_expression": "((value)::text <> ''::text)",
            "deferrable": False,
            "validated": True,
        },
        {
            "kind": "constraint",
            "table": "sample",
            "name": "sample_parent_id_fkey",
            "constraint_type": "f",
            "local_columns": ("parent_id",),
            "referred_table": "parent",
            "referred_columns": ("id",),
            "match_type": "s",
            "update_type": "a",
            "delete_type": "a",
            "deferrable": False,
            "initially_deferred": False,
            "validated": True,
        },
        {
            "kind": "index",
            "table_name": "sample",
            "index_name": "ix_sample_value",
            "access_method": "btree",
            "attribute_definitions": ["value", "included_value"],
            "indnkeyatts": 1,
            "indnatts": 2,
            "operator_classes": ["pg_catalog.text_ops"],
            "collations": ["pg_catalog.default"],
            "options": [0],
            "predicate": "value IS NOT NULL",
            "indnullsnotdistinct": False,
            "indisvalid": True,
            "indisready": True,
            "index_options": None,
            "index_persistence": "p",
            "index_tablespace": None,
        },
        {
            "kind": "sequence",
            "sequence_name": "sample_id_seq",
            "owner_table": "sample",
            "owner_column": "id",
            "seqcache": 1,
            "persistence": "p",
            "options": None,
            "tablespace_name": None,
        },
        {"kind": "schema", "nspname": "public"},
        {"kind": "type", "typname": "state", "enum_labels": ["a", "b"]},
        {"kind": "view", "relname": "sample_view", "definition": "SELECT 1;"},
        {
            "kind": "trigger",
            "trigger_name": "sample_trigger",
            "definition": "CREATE TRIGGER sample_trigger BEFORE INSERT ON sample",
        },
        {
            "kind": "extension",
            "extname": "plpgsql",
            "extversion": "1.0",
            "nspname": "pg_catalog",
        },
        {
            "kind": "policy",
            "table_name": "sample",
            "polname": "sample_policy",
            "using_expression": "tenant_id = 1",
        },
        {
            "kind": "routine",
            "schema_name": "public",
            "proname": "sample_function",
            "definition": "CREATE FUNCTION sample_function() RETURNS integer AS 'x'",
        },
        {
            "kind": "rule",
            "table_name": "sample",
            "rule_name": "sample_rule",
            "definition": "CREATE RULE sample_rule AS ON INSERT TO sample DO NOTHING",
        },
    ]


@pytest.mark.parametrize(
    "record_index,field,replacement",
    [
        (0, "row_security", True),
        (0, "options", ["fillfactor=80"]),
        (0, "replica_identity", "f"),
        (0, "access_method", "custom_heap"),
        (0, "tablespace", "fastspace"),
        (0, "partition_bound", "FOR VALUES FROM (1) TO (10)"),
        (1, "character_maximum_length", 65),
        (1, "column_default", "'changed'::character varying"),
        (1, "is_nullable", "YES"),
        (1, "collation_name", "C"),
        (1, "is_identity", "YES"),
        (1, "is_generated", "ALWAYS"),
        (1, "storage_strategy", "e"),
        (1, "compression_method", "p"),
        (2, "name", "ck_sample_value_changed"),
        (2, "check_expression", "length(value) > 1"),
        (2, "validated", False),
        (3, "name", "renamed_parent_fkey"),
        (3, "referred_table", "other_parent"),
        (3, "delete_type", "c"),
        (3, "deferrable", True),
        (4, "operator_classes", ["public.custom_text_ops"]),
        (4, "attribute_definitions", ["included_value", "value"]),
        (4, "indnkeyatts", 2),
        (4, "predicate", "value IS NULL"),
        (4, "indnullsnotdistinct", True),
        (4, "options", [1]),
        (4, "index_options", ["fillfactor=70"]),
        (4, "index_persistence", "u"),
        (4, "index_tablespace", "fastspace"),
        (4, "indisvalid", False),
        (4, "indisready", False),
        (5, "owner_table", "other"),
        (5, "seqcache", 10),
        (5, "persistence", "u"),
        (5, "options", ["cache=10"]),
        (5, "tablespace_name", "fastspace"),
        (6, "nspname", "unexpected_schema"),
        (7, "enum_labels", ["b", "a"]),
        (8, "definition", "SELECT 2;"),
        (9, "definition", "CREATE TRIGGER changed BEFORE INSERT ON sample"),
        (10, "extversion", "1.1"),
        (11, "using_expression", "tenant_id = 2"),
        (12, "definition", "CREATE FUNCTION sample_function() RETURNS integer AS 'y'"),
        (13, "definition", "CREATE RULE changed AS ON INSERT TO sample DO NOTHING"),
    ],
)
def test_catalog_digest_changes_for_every_semantic_field_class(
    migration, record_index, field, replacement
):
    records = _semantic_record_fixture()
    baseline = migration._catalog_records_sha256(records)
    changed = copy.deepcopy(records)
    changed[record_index][field] = replacement
    assert migration._catalog_records_sha256(changed) != baseline


def test_catalog_digest_ignores_only_physical_column_ordinals(migration):
    records = _semantic_record_fixture()
    baseline = migration._catalog_records_sha256(records)

    with_attnum = copy.deepcopy(records)
    with_attnum[1]["attnum"] = 57
    with_attnum[1]["ordinal_position"] = 57
    assert migration._catalog_records_sha256(with_attnum) == baseline

    with_unknown_physical_field = copy.deepcopy(records)
    with_unknown_physical_field[1]["storage"] = "external"
    assert migration._catalog_records_sha256(with_unknown_physical_field) != baseline


def test_catalog_digest_preserves_whitespace_inside_quoted_literals(migration):
    first = [{"kind": "constraint", "expression": "value = 'a  b'"}]
    second = [{"kind": "constraint", "expression": "value = 'a b'"}]
    assert migration._catalog_records_sha256(first) != migration._catalog_records_sha256(
        second
    )
    assert migration._stable_text("value = 'a  b'") == "value = 'a  b'"


def test_catalog_digest_is_order_independent_but_duplicate_sensitive(migration):
    records = _semantic_record_fixture()
    baseline = migration._catalog_records_sha256(records)
    assert migration._catalog_records_sha256(list(reversed(records))) == baseline
    assert migration._catalog_records_sha256(records + [records[0]]) != baseline


def test_catalog_digest_is_explicitly_versioned(migration, monkeypatch):
    records = _semantic_record_fixture()
    baseline = migration._catalog_records_sha256(records)
    monkeypatch.setattr(migration, "CATALOG_MANIFEST_VERSION", "different-version")
    assert migration._catalog_records_sha256(records) != baseline


def test_constraint_count_reader_uses_materialized_result_pairs(migration):
    class _Result:
        def __iter__(self):
            raise AssertionError("CursorResult must not be passed directly to dict()")

        def all(self):
            return [("c", 150), ("f", 177), ("p", 65), ("u", 74)]

    assert migration._count_pairs(_Result()) == {
        "c": 150,
        "f": 177,
        "p": 65,
        "u": 74,
    }


def test_placeholder_catalog_digests_refuse_postgresql_before_inspection(
    migration, monkeypatch
):
    monkeypatch.setattr(
        migration,
        "EXPECTED_CATALOG_MANIFEST_SHA256",
        {
            "clean": "PENDING_CLEAN",
            "active": "PENDING_ACTIVE",
            "canonical": "PENDING_CANONICAL",
        },
    )
    inspected = False

    def forbidden_read(_bind):
        nonlocal inspected
        inspected = True
        raise AssertionError("catalog was inspected before digest freeze gate")

    monkeypatch.setattr(migration, "_read_postgres_surface", forbidden_read)
    with pytest.raises(RuntimeError, match="not frozen"):
        migration._upgrade_postgresql(object())
    assert inspected is False


def test_unknown_manifest_rejects_before_lock_or_any_mutation(migration, monkeypatch):
    monkeypatch.setattr(
        migration,
        "EXPECTED_CATALOG_MANIFEST_SHA256",
        {"clean": "1" * 64, "active": "2" * 64, "canonical": "3" * 64},
    )
    unknown = replace(
        migration._expected_postgres_surface("active"),
        catalog_manifest_sha256="f" * 64,
    )
    monkeypatch.setattr(
        migration, "_require_supported_postgresql_major", lambda _bind: None
    )
    monkeypatch.setattr(migration, "_read_postgres_surface", lambda _bind: unknown)
    touched: list[str] = []
    for name in (
        "_lock_existing_application_tables",
        "_preflight_timestamp_conversions",
        "_preflight_canonical_data",
        "_apply_postgres_convergence",
        "_sync_postgres_sequences",
    ):
        monkeypatch.setattr(
            migration,
            name,
            lambda *args, _name=name, **kwargs: touched.append(_name),
        )

    with pytest.raises(RuntimeError, match="before DDL"):
        migration._upgrade_postgresql(object())
    assert touched == []


def test_postgresql_major_mismatch_rejects_before_catalog_classification(
    migration, monkeypatch
):
    monkeypatch.setattr(
        migration,
        "EXPECTED_CATALOG_MANIFEST_SHA256",
        {"clean": "1" * 64, "active": "2" * 64, "canonical": "PENDING"},
    )

    class _VersionResult:
        def scalar_one(self):
            return "170002"

    class _Bind:
        def exec_driver_sql(self, statement):
            assert statement == "SHOW server_version_num"
            return _VersionResult()

    classified = False

    def forbidden_read(_bind):
        nonlocal classified
        classified = True
        raise AssertionError("catalog classifier ran on unsupported PostgreSQL")

    monkeypatch.setattr(migration, "_read_postgres_surface", forbidden_read)
    with pytest.raises(RuntimeError, match="observed major 17"):
        migration._upgrade_postgresql(_Bind())
    assert classified is False


def test_pending_canonical_digest_allows_provisional_ddl_then_reports_observed_hash(
    migration, monkeypatch
):
    monkeypatch.setattr(
        migration,
        "EXPECTED_CATALOG_MANIFEST_SHA256",
        {
            "clean": "1" * 64,
            "active": "2" * 64,
            "canonical": "PENDING_CANONICAL_CAPTURE",
        },
    )
    source = migration._expected_postgres_surface("active")
    observed_hash = "f" * 64
    observed = replace(
        migration._expected_postgres_surface("canonical"),
        catalog_manifest_sha256=observed_hash,
    )
    reads = iter((source, source, observed))
    monkeypatch.setattr(
        migration,
        "_read_postgres_surface",
        lambda _bind, **_kwargs: next(reads),
    )
    monkeypatch.setattr(
        migration, "_require_supported_postgresql_major", lambda _bind: None
    )
    touched: list[str] = []
    monkeypatch.setattr(
        migration,
        "_lock_existing_application_tables",
        lambda *_args: touched.append("lock"),
    )
    monkeypatch.setattr(
        migration,
        "_preflight_timestamp_conversions",
        lambda *_args: touched.append("timestamp_preflight"),
    )
    monkeypatch.setattr(
        migration,
        "_preflight_canonical_data",
        lambda *_args: touched.append("data_preflight"),
    )
    monkeypatch.setattr(
        migration,
        "_apply_postgres_convergence",
        lambda *_args: touched.append("ddl"),
    )
    monkeypatch.setattr(
        migration,
        "_sync_postgres_sequences",
        lambda *_args: touched.append("sequence_sync"),
    )

    with pytest.raises(RuntimeError, match=observed_hash) as error:
        migration._upgrade_postgresql(object())
    assert "PENDING_CANONICAL_CAPTURE" in str(error.value)
    assert touched == [
        "lock",
        "timestamp_preflight",
        "data_preflight",
        "ddl",
        "sequence_sync",
    ]


def test_frozen_canonical_digest_allows_postvalidation_success(migration, monkeypatch):
    monkeypatch.setattr(
        migration,
        "EXPECTED_CATALOG_MANIFEST_SHA256",
        {"clean": "1" * 64, "active": "2" * 64, "canonical": "3" * 64},
    )
    source = migration._expected_postgres_surface("clean")
    canonical = migration._expected_postgres_surface("canonical")
    reads = iter((source, source, canonical))
    monkeypatch.setattr(
        migration,
        "_read_postgres_surface",
        lambda _bind, **_kwargs: next(reads),
    )
    monkeypatch.setattr(
        migration, "_require_supported_postgresql_major", lambda _bind: None
    )
    for name in (
        "_lock_existing_application_tables",
        "_preflight_canonical_data",
        "_apply_postgres_convergence",
        "_sync_postgres_sequences",
    ):
        monkeypatch.setattr(migration, name, lambda *_args: None)

    migration._upgrade_postgresql(object())


def test_default_and_type_contracts_are_exact(migration):
    clean = migration._target_column_contracts("clean")
    active = migration._target_column_contracts("active")
    canonical = migration._target_column_contracts("canonical")

    for key in migration.TIMESTAMPTZ_COLUMNS:
        assert active[key].type_name == "timestamp without time zone"
        assert clean[key].type_name == "timestamp with time zone"
        assert canonical[key] == clean[key]
        assert clean[key].nullable is False
    for key, contract in migration.SERVER_DEFAULTS.items():
        assert active[key].default is None
        assert clean[key].default == migration._canonical_default(contract.sql)
        assert canonical[key] == clean[key]
    assert clean["draftingeligibilityassessment.status"].type_name == "character varying"
    assert active["draftingeligibilityassessment.status"].type_name == "character varying(64)"
    assert clean["draftingeligibilitydisposition.decision"].type_name == "character varying"
    assert active["draftingeligibilitydisposition.decision"].type_name == "character varying(32)"
    assert clean["wordpressdeploymentaudit.partial_failure_details"].type_name == "text"
    assert canonical["wordpressdeploymentaudit.partial_failure_details"].type_name == "character varying"


def test_source_check_and_index_contracts_converge_without_permitting_both_states(
    migration,
):
    clean_checks = migration._target_checks("clean")
    active_checks = migration._target_checks("active")
    canonical_checks = migration._target_checks("canonical")
    assert sum(value is not None for value in clean_checks.values()) == 19
    assert sum(value is not None for value in active_checks.values()) == 1
    assert "deferred" in canonical_checks[migration.DISPOSITION_CHECK]
    assert "blocked" not in canonical_checks[migration.DISPOSITION_CHECK]
    assert "blocked" in active_checks[migration.DISPOSITION_CHECK]
    assert migration._target_indexes("clean") == {
        name: None for name in migration.RELEVANT_INDEXES
    }
    assert sum(value is not None for value in migration._target_indexes("active").values()) == 3
    assert sum(value is not None for value in migration._target_indexes("canonical").values()) == 2


def test_sequence_restart_never_regresses_and_handles_called_state(migration):
    assert migration._sequence_restart_target(
        maximum_id=None, last_value=1, is_called=False
    ) is None
    assert migration._sequence_restart_target(
        maximum_id=8, last_value=20, is_called=True
    ) is None
    assert migration._sequence_restart_target(
        maximum_id=8, last_value=9, is_called=False
    ) is None
    assert migration._sequence_restart_target(
        maximum_id=8, last_value=7, is_called=True
    ) == 9
    assert migration._sequence_restart_target(
        maximum_id=8, last_value=8, is_called=False
    ) == 9


class _RecordingOp:
    def __init__(self):
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


def test_active_plan_uses_explicit_session_independent_utc_conversion(
    migration, monkeypatch
):
    recorder = _RecordingOp()
    monkeypatch.setattr(migration, "op", recorder)

    migration._apply_postgres_convergence("active")

    timestamp_alters = [
        (args, kwargs)
        for name, args, kwargs in recorder.calls
        if name == "alter_column" and "postgresql_using" in kwargs
    ]
    assert len(timestamp_alters) == 24
    assert {
        f"{args[0]}.{args[1]}" for args, _kwargs in timestamp_alters
    } == migration.TIMESTAMPTZ_COLUMNS
    for _args, kwargs in timestamp_alters:
        assert kwargs["postgresql_using"].endswith(" AT TIME ZONE 'UTC'")
        assert kwargs["existing_nullable"] is False
        assert kwargs["type_"].timezone is True


def test_timestamp_preflight_round_trips_every_column_before_alter(migration):
    class _Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class _Bind:
        def __init__(self):
            self.statements: list[str] = []

        def exec_driver_sql(self, statement):
            self.statements.append(statement)
            return _Result("UTC" if len(self.statements) == 1 else 0)

    bind = _Bind()
    migration._preflight_timestamp_conversions(bind)
    assert bind.statements[0] == "SELECT current_setting('TimeZone')"
    assert len(bind.statements) == 25
    assert all("AT TIME ZONE 'UTC'" in statement for statement in bind.statements[1:])
    assert all("NOT isfinite" in statement for statement in bind.statements[1:])
    assert all("IS DISTINCT FROM" in statement for statement in bind.statements[1:])


@pytest.mark.parametrize(
    "timezone,violation_count,error",
    [
        ("America/New_York", 0, "requires session TimeZone=UTC"),
        ("UTC", 1, "non-finite, non-round-tripping, or null"),
    ],
)
def test_timestamp_preflight_rejects_non_utc_or_nonfinite_values(
    migration, timezone, violation_count, error
):
    class _Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class _Bind:
        def __init__(self):
            self.calls = 0

        def exec_driver_sql(self, _statement):
            self.calls += 1
            return _Result(timezone if self.calls == 1 else violation_count)

    with pytest.raises(RuntimeError, match=error):
        migration._preflight_timestamp_conversions(_Bind())


def test_sqlite_clean_shape_creates_and_then_adopts_exact_owned_tables(
    migration, monkeypatch
):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        _create_generated_page(connection)
        monkeypatch.setattr(migration, "op", _sqlite_operations(connection))

        migration._upgrade_sqlite(connection)
        first = _sqlite_snapshot(connection)
        assert migration.RUNTIME_TABLES <= set(sa.inspect(connection).get_table_names())
        assert migration._classify_sqlite_runtime(connection) == "active"

        migration._upgrade_sqlite(connection)
        assert _sqlite_snapshot(connection) == first
    engine.dispose()


def test_sqlite_partial_shape_fails_before_creating_any_other_table(
    migration, monkeypatch
):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        _create_generated_page(connection)
        connection.exec_driver_sql(
            "CREATE TABLE wordpressqualityreview (id INTEGER PRIMARY KEY)"
        )
        before = _sqlite_snapshot(connection)
        monkeypatch.setattr(migration, "op", _sqlite_operations(connection))

        with pytest.raises(RuntimeError, match="partial SQLite"):
            migration._upgrade_sqlite(connection)
        assert _sqlite_snapshot(connection) == before
    engine.dispose()


def test_sqlite_near_match_fails_before_mutation(migration, monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        _create_generated_page(connection)
        monkeypatch.setattr(migration, "op", _sqlite_operations(connection))
        migration._upgrade_sqlite(connection)
        connection.exec_driver_sql(
            "DROP INDEX ix_wordpressmetadatastate_payload_hash"
        )
        before = _sqlite_snapshot(connection)

        with pytest.raises(RuntimeError, match="incompatible SQLite"):
            migration._upgrade_sqlite(connection)
        assert _sqlite_snapshot(connection) == before
    engine.dispose()


def test_sqlite_adoption_preserves_rows(migration, monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        _create_generated_page(connection)
        monkeypatch.setattr(migration, "op", _sqlite_operations(connection))
        migration._upgrade_sqlite(connection)
        connection.exec_driver_sql("INSERT INTO generatedpage (id) VALUES (41)")
        connection.exec_driver_sql(
            "INSERT INTO wordpressmetadatastate "
            "(created_at, updated_at, generated_page_id, wordpress_post_id, "
            "schema_version, status) VALUES "
            "('2026-08-15', '2026-08-15', 41, 410, '1.0', 'not_applied')"
        )
        before = tuple(
            connection.exec_driver_sql(
                "SELECT * FROM wordpressmetadatastate ORDER BY id"
            )
        )

        migration._upgrade_sqlite(connection)
        after = tuple(
            connection.exec_driver_sql(
                "SELECT * FROM wordpressmetadatastate ORDER BY id"
            )
        )
        assert after == before
    engine.dispose()


def test_downgrade_fails_before_bind_access_or_mutation(migration, monkeypatch):
    class _ForbiddenOp:
        def __getattr__(self, name):
            raise AssertionError(f"downgrade touched op.{name}")

    monkeypatch.setattr(migration, "op", _ForbiddenOp())
    with pytest.raises(RuntimeError, match="intentionally irreversible"):
        migration.downgrade()
