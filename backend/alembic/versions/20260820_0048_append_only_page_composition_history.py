"""Add immutable, append-only Page Composition revision history.

Revision ID: 20260820_0048
Revises: 20260817_0047
Create Date: 2026-08-20
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from alembic import context, op
import sqlalchemy as sa


revision = "20260820_0048"
down_revision = "20260817_0047"
branch_labels = None
depends_on = None


TABLE = "pagecompositionrevision"
MIGRATION_BACKFILL_SOURCE = "migration_0048_backfill"
MIGRATION_BACKFILL_ACTOR = "migration:20260820_0048"
RECOVERY_EVIDENCE_SOURCE = "legacy_history_evidence_v1"
RECOVERY_EVIDENCE_ACTOR = "atlas:legacy_composition_recovery"

EVIDENCE_PATH_OPTION = "page_composition_history_evidence_path"
EVIDENCE_SHA256_OPTION = "page_composition_history_evidence_sha256"
EVIDENCE_SCHEMA = "project-atlas-page-composition-history-evidence"
EVIDENCE_VERSION = "1"

CURRENT_HEAD_FK = "fk_pagecomposition_current_revision"
QA_REVISION_FK = "fk_generatedpageqaresult_composition_revision"
IMMUTABLE_FUNCTION = "atlas_pagecomprev_reject_mutation"
IMMUTABLE_ROW_TRIGGER = "trg_pagecomprev_immutable_rows"
IMMUTABLE_TRUNCATE_TRIGGER = "trg_pagecomprev_immutable_truncate"
SQLITE_UPDATE_TRIGGER = "trg_pagecomprev_immutable_update"
SQLITE_DELETE_TRIGGER = "trg_pagecomprev_immutable_delete"

REVISION_HASH_FIELDS = (
    "page_composition_id",
    "website_id",
    "site_plan_id",
    "planned_page_id",
    "generated_page_id",
    "generated_page_revision_id",
    "composition_version",
    "supersedes_revision_id",
    "supersedes_revision_hash",
    "lineage_kind",
    "content_hash",
    "generated_components",
    "operator_decisions",
    "source_snapshot",
    "source_hash",
    "generated_at",
    "decided_by",
    "decided_at",
    "recorded_at",
    "recorded_by",
    "record_source",
)

QA_RESULT_HASH_FIELDS = (
    "website_id",
    "site_plan_id",
    "planned_page_id",
    "generated_page_id",
    "latest_generated_page_revision_id",
    "content_hash",
    "source_hash",
    "page_composition_id",
    "composition_version",
    "composition_source_hash",
    "qa_algorithm_key",
    "qa_algorithm_version",
    "qa_ruleset_key",
    "qa_ruleset_version",
    "qa_ruleset_hash",
    "readiness_status",
    "passed_count",
    "warning_count",
    "failed_count",
    "check_payload",
    "evaluated_at",
)
QA_EVIDENCE_FIELDS = ("id", *QA_RESULT_HASH_FIELDS, "result_hash")

EXPECTED_COLUMNS = (
    "id",
    "page_composition_id",
    "website_id",
    "site_plan_id",
    "planned_page_id",
    "generated_page_id",
    "generated_page_revision_id",
    "composition_version",
    "supersedes_revision_id",
    "supersedes_revision_hash",
    "lineage_kind",
    "content_hash",
    "generated_components",
    "operator_decisions",
    "source_snapshot",
    "source_hash",
    "revision_hash",
    "generated_at",
    "decided_by",
    "decided_at",
    "recorded_at",
    "recorded_by",
    "record_source",
)

NULLABLE_COLUMNS = frozenset(
    {
        "generated_page_revision_id",
        "supersedes_revision_id",
        "supersedes_revision_hash",
        "decided_by",
        "decided_at",
    }
)

SOURCE_COLUMNS = {
    "pagecomposition": frozenset(
        {
            "created_at",
            "updated_at",
            "id",
            "website_id",
            "site_plan_id",
            "planned_page_id",
            "generated_page_id",
            "composition_version",
            "generated_components",
            "operator_decisions",
            "source_snapshot",
            "source_hash",
            "status",
            "generated_at",
            "decided_by",
            "decided_at",
        }
    ),
    "generatedpagerevision": frozenset(
        {
            "id",
            "generated_page_id",
            "created_at",
            "created_by",
            "reason",
            "draft_hash_before",
            "draft_hash_after",
            "draft_content_before",
            "draft_content_after",
            "changed_fields",
        }
    ),
    "generatedpageqaresult": frozenset(
        {
            "created_at",
            "updated_at",
            "id",
            "website_id",
            "site_plan_id",
            "planned_page_id",
            "generated_page_id",
            "latest_generated_page_revision_id",
            "content_hash",
            "source_hash",
            "page_composition_id",
            "composition_version",
            "composition_source_hash",
            "qa_algorithm_key",
            "qa_algorithm_version",
            "qa_ruleset_key",
            "qa_ruleset_version",
            "qa_ruleset_hash",
            "readiness_status",
            "passed_count",
            "warning_count",
            "failed_count",
            "check_payload",
            "evaluated_at",
            "lifecycle_status",
            "supersedes_qa_result_id",
            "result_hash",
            "historical_payload",
        }
    ),
}

EXPECTED_CHECKS = {
    "ck_pagecomprev_version",
    "ck_pagecomprev_hashes",
    "ck_pagecomprev_lineage",
    "ck_pagecomprev_not_self",
    "ck_pagecomprev_provenance",
}

EXPECTED_UNIQUES = {
    "uq_pagecomprev_stream_id": ("page_composition_id", "id"),
    "uq_pagecomprev_stream_version": (
        "page_composition_id",
        "composition_version",
    ),
    "uq_pagecomprev_identity": (
        "page_composition_id",
        "composition_version",
        "source_hash",
    ),
    "uq_pagecomprev_successor": (
        "page_composition_id",
        "supersedes_revision_id",
    ),
    "uq_pagecomprev_stream_hash": (
        "page_composition_id",
        "revision_hash",
    ),
}

EXPECTED_INDEXES = {
    "ix_pagecompositionrevision_page_composition_id": ("page_composition_id",),
    "ix_pagecompositionrevision_website_id": ("website_id",),
    "ix_pagecompositionrevision_site_plan_id": ("site_plan_id",),
    "ix_pagecompositionrevision_planned_page_id": ("planned_page_id",),
    "ix_pagecompositionrevision_generated_page_id": ("generated_page_id",),
    "ix_pagecomprev_scope": ("website_id", "site_plan_id", "planned_page_id"),
    "ix_pagecomprev_generated_revision": ("generated_page_revision_id",),
    "ix_pagecomprev_source_hash": ("source_hash",),
    "ix_pagecomprev_revision_hash": ("revision_hash",),
}

EXPECTED_HISTORY_FKS = {
    "fk_pagecomprev_composition": (
        ("page_composition_id",),
        "pagecomposition",
        ("id",),
        False,
    ),
    "fk_pagecomprev_website": (
        ("website_id",),
        "website",
        ("id",),
        False,
    ),
    "fk_pagecomprev_site_plan": (
        ("site_plan_id",),
        "siteplan",
        ("id",),
        False,
    ),
    "fk_pagecomprev_planned_page": (
        ("planned_page_id",),
        "plannedpage",
        ("id",),
        False,
    ),
    "fk_pagecomprev_generated_page": (
        ("generated_page_id",),
        "generatedpage",
        ("id",),
        False,
    ),
    "fk_pagecomprev_generated_revision": (
        ("generated_page_revision_id",),
        "generatedpagerevision",
        ("id",),
        False,
    ),
    "fk_pagecomprev_predecessor": (
        ("page_composition_id", "supersedes_revision_id"),
        TABLE,
        ("page_composition_id", "id"),
        True,
    ),
}


def _lower_sha256_sql(column_name: str) -> str:
    stripped = column_name
    for character in "0123456789abcdef":
        stripped = f"replace({stripped}, '{character}', '')"
    return (
        f"length({column_name}) = 64 "
        f"AND {column_name} = lower({column_name}) "
        f"AND length({stripped}) = 0"
    )


HASH_CHECK = (
    f"({_lower_sha256_sql('content_hash')}) "
    f"AND ({_lower_sha256_sql('source_hash')}) "
    f"AND ({_lower_sha256_sql('revision_hash')}) "
    "AND (supersedes_revision_hash IS NULL OR "
    f"({_lower_sha256_sql('supersedes_revision_hash')}))"
)


def upgrade() -> None:
    bind = op.get_bind()
    _require_supported_dialect(bind)
    _lock_source_tables(bind)
    rows = _preflight_source_and_build_rows(bind)
    _preflight_target_absent(bind)
    _create_history_table()
    _create_history_indexes()
    if rows:
        op.bulk_insert(_history_table(), rows)
        _synchronize_history_identity(bind, rows)
    _add_binding_foreign_keys(bind)
    _install_immutability_guards(bind)
    _assert_owned_shape(bind)
    _assert_history_matches_heads_and_qa(bind, require_pristine_roots=False)


def downgrade() -> None:
    bind = op.get_bind()
    _require_supported_dialect(bind)
    existing = set(sa.inspect(bind).get_table_names())
    if TABLE not in existing:
        raise RuntimeError(
            "Cannot downgrade Page Composition history because its table is missing."
        )
    _lock_downgrade_tables(bind)
    _assert_owned_shape(bind)
    _assert_history_matches_heads_and_qa(bind, require_pristine_roots=True)
    _remove_immutability_guards(bind)
    _drop_binding_foreign_keys(bind)
    op.drop_table(TABLE)


def _require_supported_dialect(bind: Any) -> None:
    if bind.dialect.name not in {"postgresql", "sqlite"}:
        raise RuntimeError(
            "Page Composition history supports only PostgreSQL and disposable SQLite."
        )


def _lock_source_tables(bind: Any) -> None:
    if bind.dialect.name != "postgresql":
        return
    bind.execute(
        sa.text(
            "LOCK TABLE generatedpage, generatedpagerevision, "
            "generatedpageqaresult, pagecomposition, plannedpage, siteplan, "
            "website IN SHARE ROW EXCLUSIVE MODE"
        )
    )


def _lock_downgrade_tables(bind: Any) -> None:
    if bind.dialect.name != "postgresql":
        return
    bind.execute(
        sa.text(
            "LOCK TABLE generatedpageqaresult, pagecomposition, "
            "pagecompositionrevision IN ACCESS EXCLUSIVE MODE"
        )
    )


def _preflight_target_absent(bind: Any) -> None:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if TABLE in tables:
        raise RuntimeError(
            "Page Composition history refuses any pre-created revision table."
        )
    for table, forbidden in (
        ("pagecomposition", CURRENT_HEAD_FK),
        ("generatedpageqaresult", QA_REVISION_FK),
    ):
        foreign_keys = inspector.get_foreign_keys(table)
        if forbidden in {item.get("name") for item in foreign_keys} or any(
            item.get("referred_table") == TABLE for item in foreign_keys
        ):
            raise RuntimeError(
                "Page Composition history refuses a partially pre-created schema."
            )
    if bind.dialect.name == "postgresql":
        reserved_relations = {
            TABLE,
            f"{TABLE}_id_seq",
            *EXPECTED_INDEXES,
            f"{TABLE}_pkey",
            *EXPECTED_UNIQUES,
        }
        collisions = {
            str(value)
            for value in bind.execute(
                sa.text(
                    "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid = c.relnamespace WHERE n.nspname = current_schema() "
                    "AND c.relname = ANY(:names)"
                ),
                {"names": sorted(reserved_relations)},
            ).scalars()
        }
        if collisions:
            raise RuntimeError(
                "Page Composition history refuses reserved relation collisions: "
                + ", ".join(sorted(collisions))
            )
        function_exists = bind.execute(
            sa.text(
                "SELECT 1 FROM pg_proc p JOIN pg_namespace n "
                "ON n.oid = p.pronamespace "
                "WHERE n.nspname = current_schema() AND p.proname = :name"
            ),
            {"name": IMMUTABLE_FUNCTION},
        ).scalar_one_or_none()
        if function_exists is not None:
            raise RuntimeError(
                "Page Composition history refuses a pre-created immutable function."
            )
    else:
        reserved_names = {
            TABLE,
            *EXPECTED_INDEXES,
            *EXPECTED_UNIQUES,
        }
        placeholders = ", ".join(
            f":name_{index}" for index, _value in enumerate(sorted(reserved_names))
        )
        parameters = {
            f"name_{index}": value
            for index, value in enumerate(sorted(reserved_names))
        }
        collisions = {
            str(value)
            for value in bind.execute(
                sa.text(
                    "SELECT name FROM sqlite_master WHERE name IN "
                    f"({placeholders})"
                ),
                parameters,
            ).scalars()
        }
        if collisions:
            raise RuntimeError(
                "Page Composition history refuses reserved schema collisions: "
                + ", ".join(sorted(collisions))
            )
        trigger_count = bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' "
                "AND name IN (:update_name, :delete_name)"
            ),
            {
                "update_name": SQLITE_UPDATE_TRIGGER,
                "delete_name": SQLITE_DELETE_TRIGGER,
            },
        ).scalar_one()
        if trigger_count:
            raise RuntimeError(
                "Page Composition history refuses pre-created immutable triggers."
            )


def _synchronize_history_identity(
    bind: Any,
    rows: list[dict[str, Any]],
) -> None:
    expected_ids = list(range(1, len(rows) + 1))
    observed_ids = [row.get("id") for row in rows]
    if observed_ids != expected_ids:
        raise RuntimeError(
            "Page Composition history backfill identities are not deterministic."
        )
    if bind.dialect.name != "postgresql":
        return
    synchronized = bind.execute(
        sa.text(
            "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
            ":last_value, true)"
        ),
        {"table_name": TABLE, "last_value": expected_ids[-1]},
    ).scalar_one()
    if synchronized != expected_ids[-1]:
        raise RuntimeError(
            "Page Composition history identity sequence did not synchronize exactly."
        )


def _preflight_source_and_build_rows(bind: Any) -> list[dict[str, Any]]:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    required_tables = {
        "website",
        "siteplan",
        "plannedpage",
        "generatedpage",
        *SOURCE_COLUMNS,
    }
    missing = sorted(required_tables - tables)
    if missing:
        raise RuntimeError(
            "Page Composition history source tables are missing: "
            + ", ".join(missing)
        )
    for table, expected in SOURCE_COLUMNS.items():
        observed = {item["name"] for item in inspector.get_columns(table)}
        if observed != expected:
            raise RuntimeError(
                f"Page Composition history refuses incompatible {table} columns."
            )
    _assert_source_binding_constraints(inspector)

    websites = _integer_key_set(bind, "website")
    site_plans = _scope_map(bind, "siteplan", ("website_id",))
    planned_pages = _scope_map(
        bind,
        "plannedpage",
        ("website_id", "site_plan_id", "generated_page_id"),
    )
    generated_pages = _scope_map(bind, "generatedpage", ("website_id",))
    generated_revisions = _generated_revisions_by_page(bind)
    backfilled_at = datetime.now(UTC)

    compositions: dict[int, dict[str, Any]] = {}
    current_material: dict[int, dict[str, Any]] = {}
    page_composition = _page_composition_table()
    for record in bind.execute(
        sa.select(*page_composition.c).order_by(page_composition.c.id)
    ).mappings():
        values = dict(record)
        composition_id = _positive_integer(values.get("id"), "pagecomposition.id")
        if composition_id in compositions:
            raise RuntimeError("Duplicate Page Composition identity was found.")
        _validate_composition_scope(
            values,
            websites=websites,
            site_plans=site_plans,
            planned_pages=planned_pages,
            generated_pages=generated_pages,
        )
        snapshot = values.get("source_snapshot")
        components = values.get("generated_components")
        decisions = values.get("operator_decisions")
        if (
            not isinstance(snapshot, dict)
            or not isinstance(components, list)
            or not isinstance(decisions, list)
        ):
            raise RuntimeError(
                "Page Composition history requires exact JSON payload shapes."
            )
        source_hash = values.get("source_hash")
        if not _is_lower_sha256(source_hash):
            raise RuntimeError("Page Composition source hash is not lowercase SHA-256.")
        if source_hash != _canonical_payload_hash(snapshot):
            raise RuntimeError(
                "Page Composition source hash does not match its source snapshot."
            )
        content_hash = snapshot.get("draft_hash")
        if not _is_lower_sha256(content_hash):
            raise RuntimeError(
                "Page Composition source snapshot lacks an exact lowercase draft hash."
            )
        version = _positive_integer(
            values.get("composition_version"),
            "pagecomposition.composition_version",
        )
        generated_at = _require_datetime(
            values.get("generated_at"),
            "pagecomposition.generated_at",
        )
        decided_at = values.get("decided_at")
        if decided_at is not None:
            decided_at = _require_datetime(
                decided_at,
                "pagecomposition.decided_at",
            )
        generated_page_id = _positive_integer(
            values.get("generated_page_id"),
            "pagecomposition.generated_page_id",
        )
        generated_revision_cutoff = _as_utc(generated_at)
        generated_page_revision_id = None
        latest = next(
            (
                revision_row
                for revision_row in generated_revisions.get(
                    generated_page_id,
                    (),
                )
                if _as_utc(revision_row["created_at"])
                <= generated_revision_cutoff
            ),
            None,
        )
        if latest is not None:
            if latest["draft_hash_after"] != content_hash:
                raise RuntimeError(
                    "Page Composition content is not represented by the latest "
                    "Generated Page revision available when it was recorded."
                )
            generated_page_revision_id = latest["id"]

        current_material[composition_id] = {
            "page_composition_id": composition_id,
            "website_id": values["website_id"],
            "site_plan_id": values["site_plan_id"],
            "planned_page_id": values["planned_page_id"],
            "generated_page_id": generated_page_id,
            "generated_page_revision_id": generated_page_revision_id,
            "composition_version": version,
            "content_hash": content_hash,
            "generated_components": components,
            "operator_decisions": decisions,
            "source_snapshot": snapshot,
            "source_hash": source_hash,
            "generated_at": generated_at,
            "decided_by": values.get("decided_by"),
            "decided_at": decided_at,
        }
        compositions[composition_id] = values

    qa_rows = _qa_evidence_rows(bind)
    recovered = _validated_recovery_evidence(
        bind,
        compositions=compositions,
        qa_rows=qa_rows,
        generated_revisions=generated_revisions,
    )

    rows: list[dict[str, Any]] = []
    next_revision_id = 1
    for composition_id in sorted(compositions):
        predecessor: dict[str, Any] | None = None
        recovered_root = recovered.get(composition_id)
        if recovered_root is not None:
            predecessor = {**recovered_root, "id": next_revision_id}
            next_revision_id += 1
            rows.append(predecessor)

        revision_values: dict[str, Any] = {
            **current_material[composition_id],
            "id": next_revision_id,
            "supersedes_revision_id": (
                predecessor["id"] if predecessor is not None else None
            ),
            "supersedes_revision_hash": (
                predecessor["revision_hash"] if predecessor is not None else None
            ),
            "lineage_kind": "successor" if predecessor is not None else "legacy_root",
            "recorded_at": backfilled_at,
            "recorded_by": MIGRATION_BACKFILL_ACTOR,
            "record_source": MIGRATION_BACKFILL_SOURCE,
        }
        next_revision_id += 1
        revision_values["revision_hash"] = _composition_revision_hash(
            revision_values
        )
        if predecessor is not None and _as_utc(
            _require_datetime(predecessor["recorded_at"], "history.recorded_at")
        ) > _as_utc(backfilled_at):
            raise RuntimeError(
                "Recovered Page Composition history has decreasing recording time."
            )
        rows.append(revision_values)

    available_identities = {
        (
            row["page_composition_id"],
            row["composition_version"],
            row["source_hash"],
        )
        for row in rows
    }
    _validate_existing_qa_bindings(
        bind,
        compositions,
        qa_rows=qa_rows,
        available_identities=available_identities,
    )
    return rows


def _assert_source_binding_constraints(inspector: Any) -> None:
    page_uniques = {
        tuple(item.get("column_names") or ())
        for item in inspector.get_unique_constraints("pagecomposition")
    }
    if (
        ("planned_page_id",) not in page_uniques
        or ("generated_page_id",) not in page_uniques
    ):
        raise RuntimeError(
            "Page Composition history requires the exact sole-head constraints."
        )
    qa_checks = {
        item.get("name")
        for item in inspector.get_check_constraints("generatedpageqaresult")
    }
    if "ck_generatedpageqaresult_composition_binding" not in qa_checks:
        raise RuntimeError(
            "Page Composition history requires the exact QA binding contract."
        )


def _integer_key_set(bind: Any, table_name: str) -> set[int]:
    table = sa.table(table_name, sa.column("id", sa.Integer()))
    return {
        _positive_integer(value, f"{table_name}.id")
        for value in bind.execute(sa.select(table.c.id)).scalars()
    }


def _scope_map(
    bind: Any,
    table_name: str,
    columns: tuple[str, ...],
) -> dict[int, tuple[Any, ...]]:
    table = sa.table(
        table_name,
        sa.column("id", sa.Integer()),
        *(sa.column(column, sa.Integer()) for column in columns),
    )
    result: dict[int, tuple[Any, ...]] = {}
    for row in bind.execute(sa.select(*table.c)).mappings():
        key = _positive_integer(row["id"], f"{table_name}.id")
        result[key] = tuple(row[column] for column in columns)
    return result


def _validate_composition_scope(
    values: Mapping[str, Any],
    *,
    websites: set[int],
    site_plans: Mapping[int, tuple[Any, ...]],
    planned_pages: Mapping[int, tuple[Any, ...]],
    generated_pages: Mapping[int, tuple[Any, ...]],
) -> None:
    website_id = _positive_integer(values.get("website_id"), "website_id")
    site_plan_id = _positive_integer(values.get("site_plan_id"), "site_plan_id")
    planned_page_id = _positive_integer(
        values.get("planned_page_id"), "planned_page_id"
    )
    generated_page_id = _positive_integer(
        values.get("generated_page_id"), "generated_page_id"
    )
    if website_id not in websites:
        raise RuntimeError("Page Composition references an unknown Website.")
    if site_plans.get(site_plan_id) != (website_id,):
        raise RuntimeError("Page Composition crosses its Site Plan Website boundary.")
    if planned_pages.get(planned_page_id) != (
        website_id,
        site_plan_id,
        generated_page_id,
    ):
        raise RuntimeError("Page Composition crosses its Planned Page boundary.")
    if generated_pages.get(generated_page_id) != (website_id,):
        raise RuntimeError("Page Composition crosses its Generated Page boundary.")


def _generated_revisions_by_page(
    bind: Any,
) -> dict[int, list[dict[str, Any]]]:
    table = sa.table(
        "generatedpagerevision",
        sa.column("id", sa.Integer()),
        sa.column("generated_page_id", sa.Integer()),
        sa.column("created_at", sa.DateTime()),
        sa.column("draft_hash_after", sa.String()),
    )
    result: dict[int, list[dict[str, Any]]] = {}
    for row in bind.execute(
        sa.select(*table.c).order_by(
            table.c.generated_page_id,
            table.c.created_at.desc(),
            table.c.id.desc(),
        )
    ).mappings():
        generated_page_id = _positive_integer(
            row["generated_page_id"],
            "generatedpagerevision.generated_page_id",
        )
        revision_id = _positive_integer(row["id"], "generatedpagerevision.id")
        created_at = _require_datetime(
            row["created_at"],
            "generatedpagerevision.created_at",
        )
        result.setdefault(generated_page_id, []).append(
            {
                "id": revision_id,
                "created_at": created_at,
                "draft_hash_after": row["draft_hash_after"],
            }
        )
    return result


def _validated_recovery_evidence(
    bind: Any,
    *,
    compositions: Mapping[int, Mapping[str, Any]],
    qa_rows: list[dict[str, Any]],
    generated_revisions: Mapping[int, list[dict[str, Any]]],
) -> dict[int, dict[str, Any]]:
    package = _configured_recovery_evidence()
    missing: dict[tuple[int, int, str], list[dict[str, Any]]] = {}
    for qa_row in qa_rows:
        binding = (
            qa_row["page_composition_id"],
            qa_row["composition_version"],
            qa_row["composition_source_hash"],
        )
        if binding == (None, None, None):
            continue
        if any(value is None for value in binding):
            raise RuntimeError("Generated Page QA has a partial composition binding.")
        composition = compositions.get(qa_row["page_composition_id"])
        if composition is None:
            raise RuntimeError(
                "Generated Page QA references an unknown Page Composition."
            )
        if any(
            qa_row[field] != composition[field]
            for field in (
                "website_id",
                "site_plan_id",
                "planned_page_id",
                "generated_page_id",
            )
        ):
            raise RuntimeError("Generated Page QA crosses its Page Composition scope.")
        current_identity = (
            composition["id"],
            composition["composition_version"],
            composition["source_hash"],
        )
        if binding != current_identity:
            missing.setdefault(binding, []).append(qa_row)

    if not missing:
        if package is not None:
            raise RuntimeError(
                "Page Composition recovery evidence contains no required historical state."
            )
        return {}
    if package is None:
        raise RuntimeError(
            "Generated Page QA cannot be reconstructed from exact current Page "
            "Composition data; supply explicitly SHA-pinned legacy history evidence."
        )

    records = package["records"]
    evidence_by_identity = {
        (
            record["revision"]["page_composition_id"],
            record["revision"]["composition_version"],
            record["revision"]["source_hash"],
        ): record
        for record in records
    }
    if len(evidence_by_identity) != len(records):
        raise RuntimeError("Page Composition recovery evidence duplicates a revision.")
    if set(evidence_by_identity) != set(missing):
        raise RuntimeError(
            "Page Composition recovery evidence has missing, extra, or unrelated states."
        )

    recovered: dict[int, dict[str, Any]] = {}
    for identity in sorted(evidence_by_identity):
        record = evidence_by_identity[identity]
        revision = record["revision"]
        composition_id = revision["page_composition_id"]
        composition = compositions.get(composition_id)
        if composition is None:
            raise RuntimeError(
                "Page Composition recovery evidence references an unknown head."
            )
        if composition_id in recovered:
            raise RuntimeError(
                "Page Composition recovery evidence provides more than one legacy root."
            )
        if (
            revision["composition_version"] + 1
            != composition["composition_version"]
            or any(
                revision[field] != composition[field]
                for field in (
                    "website_id",
                    "site_plan_id",
                    "planned_page_id",
                    "generated_page_id",
                )
            )
            or _as_utc(revision["generated_at"])
            > _as_utc(
                _require_datetime(
                    composition["generated_at"],
                    "pagecomposition.generated_at",
                )
            )
        ):
            raise RuntimeError(
                "Page Composition recovery evidence is not the exact contiguous "
                "predecessor of its current head."
            )

        latest = next(
            (
                candidate
                for candidate in generated_revisions.get(
                    revision["generated_page_id"],
                    (),
                )
                if _as_utc(candidate["created_at"])
                <= _as_utc(revision["generated_at"])
            ),
            None,
        )
        if latest is None:
            if revision["generated_page_revision_id"] is not None:
                raise RuntimeError(
                    "Page Composition recovery evidence claims an unavailable "
                    "Generated Page revision."
                )
        elif (
            revision["generated_page_revision_id"] != latest["id"]
            or latest["draft_hash_after"] != revision["content_hash"]
        ):
            raise RuntimeError(
                "Page Composition recovery evidence loses the exact latest Generated "
                "Page revision available when derived."
            )

        expected_qa = {
            row["id"]: _normalized_live_qa_projection(row)
            for row in missing[identity]
        }
        observed_qa = {
            row["id"]: row for row in record["qa_results"]
        }
        if len(observed_qa) != len(record["qa_results"]):
            raise RuntimeError("Page Composition recovery evidence duplicates QA identity.")
        if set(observed_qa) != set(expected_qa):
            raise RuntimeError(
                "Page Composition recovery evidence omits or adds required QA evidence."
            )
        for qa_id, expected in expected_qa.items():
            observed = observed_qa[qa_id]
            if not _qa_projections_equal(expected, observed):
                raise RuntimeError(
                    "Page Composition recovery evidence QA identity or outcome diverges."
                )
            if (
                observed["page_composition_id"] != revision["page_composition_id"]
                or observed["composition_version"]
                != revision["composition_version"]
                or observed["composition_source_hash"] != revision["source_hash"]
                or observed["content_hash"] != revision["content_hash"]
                or observed["latest_generated_page_revision_id"]
                != revision["generated_page_revision_id"]
            ):
                raise RuntimeError(
                    "Page Composition recovery evidence QA binding is not exact."
                )
        recovered[composition_id] = revision
    return recovered


def _configured_recovery_evidence() -> dict[str, Any] | None:
    option_values: dict[str, list[str]] = {
        EVIDENCE_PATH_OPTION: [],
        EVIDENCE_SHA256_OPTION: [],
    }
    config = op.get_context().config
    for name in option_values:
        configured = config.get_main_option(name)
        attributed = config.attributes.get(name)
        for value in (configured, attributed):
            if value is not None:
                option_values[name].append(str(value))
    try:
        x_arguments = context.get_x_argument(as_dictionary=True)
    except (AttributeError, TypeError):  # pragma: no cover - Alembic compatibility
        x_arguments = {}
    for name in option_values:
        value = x_arguments.get(name)
        if value is not None:
            option_values[name].append(str(value))

    resolved: dict[str, str | None] = {}
    for name, values in option_values.items():
        normalized = {value.strip() for value in values if value.strip()}
        if len(normalized) > 1:
            raise RuntimeError(
                f"Conflicting Page Composition recovery evidence option {name}."
            )
        resolved[name] = next(iter(normalized), None)
    path_value = resolved[EVIDENCE_PATH_OPTION]
    sha256_value = resolved[EVIDENCE_SHA256_OPTION]
    if path_value is None and sha256_value is None:
        return None
    if path_value is None or sha256_value is None:
        raise RuntimeError(
            "Page Composition recovery evidence path and SHA-256 must be supplied together."
        )
    if not _is_lower_sha256(sha256_value):
        raise RuntimeError(
            "Page Composition recovery evidence caller SHA-256 is malformed."
        )
    path = Path(path_value)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RuntimeError(
            "Page Composition recovery evidence could not be read."
        ) from exc
    if hashlib.sha256(raw).hexdigest() != sha256_value:
        raise RuntimeError(
            "Page Composition recovery evidence does not match its caller SHA-256."
        )
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Page Composition recovery evidence is not exact UTF-8 JSON."
        ) from exc
    return _validate_recovery_evidence_package(payload)


def _validate_recovery_evidence_package(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "version",
        "created_at",
        "source_artifact",
        "records",
    }:
        raise RuntimeError(
            "Page Composition recovery evidence has an incompatible root contract."
        )
    if (
        payload["schema"] != EVIDENCE_SCHEMA
        or payload["version"] != EVIDENCE_VERSION
    ):
        raise RuntimeError(
            "Page Composition recovery evidence schema or version is unsupported."
        )
    created_at = _evidence_timestamp(
        payload["created_at"],
        "evidence.created_at",
        require_utc=True,
    )
    source = payload["source_artifact"]
    if not isinstance(source, dict) or set(source) != {
        "app",
        "backup_version",
        "created_at",
        "sha256",
        "size_bytes",
    }:
        raise RuntimeError(
            "Page Composition recovery evidence source provenance is incompatible."
        )
    source_created_at = _evidence_timestamp(
        source["created_at"],
        "evidence.source_artifact.created_at",
        require_utc=True,
    )
    if (
        source["app"] != "Project Atlas"
        or not isinstance(source["backup_version"], str)
        or not _is_pre_history_backup_version(source["backup_version"])
        or not _is_lower_sha256(source["sha256"])
        or isinstance(source["size_bytes"], bool)
        or not isinstance(source["size_bytes"], int)
        or source["size_bytes"] < 1
        or _as_utc(source_created_at) > _as_utc(created_at)
    ):
        raise RuntimeError(
            "Page Composition recovery evidence source provenance is invalid."
        )
    raw_records = payload["records"]
    if not isinstance(raw_records, list) or not raw_records:
        raise RuntimeError("Page Composition recovery evidence records are missing.")

    normalized_records: list[dict[str, Any]] = []
    observed_identities: set[tuple[int, int, str]] = set()
    observed_qa_ids: set[int] = set()
    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, dict) or set(raw_record) != {
            "revision",
            "qa_results",
            "record_hash",
        }:
            raise RuntimeError(
                "Page Composition recovery evidence record contract is incompatible."
            )
        raw_revision = raw_record["revision"]
        raw_qa_results = raw_record["qa_results"]
        if (
            not isinstance(raw_revision, dict)
            or not isinstance(raw_qa_results, list)
            or not raw_qa_results
            or not _is_lower_sha256(raw_record["record_hash"])
            or raw_record["record_hash"]
            != _canonical_payload_hash(
                {"revision": raw_revision, "qa_results": raw_qa_results}
            )
        ):
            raise RuntimeError(
                "Page Composition recovery evidence record hash or payload is invalid."
            )
        revision = _normalized_evidence_revision(
            raw_revision,
            evidence_created_at=created_at,
            source_created_at=source_created_at,
            field=f"evidence.records[{index}].revision",
        )
        qa_results = [
            _normalized_evidence_qa_projection(
                value,
                field=f"evidence.records[{index}].qa_results[{qa_index}]",
            )
            for qa_index, value in enumerate(raw_qa_results)
        ]
        if [value["id"] for value in qa_results] != sorted(
            value["id"] for value in qa_results
        ):
            raise RuntimeError(
                "Page Composition recovery evidence QA records are not ordered."
            )
        identity = (
            revision["page_composition_id"],
            revision["composition_version"],
            revision["source_hash"],
        )
        qa_ids = {value["id"] for value in qa_results}
        if identity in observed_identities or observed_qa_ids.intersection(qa_ids):
            raise RuntimeError(
                "Page Composition recovery evidence duplicates revision or QA identity."
            )
        observed_identities.add(identity)
        observed_qa_ids.update(qa_ids)
        normalized_records.append(
            {
                "revision": revision,
                "qa_results": qa_results,
                "record_hash": raw_record["record_hash"],
            }
        )
    observed_order = [
        (
            record["revision"]["page_composition_id"],
            record["revision"]["composition_version"],
            record["revision"]["source_hash"],
        )
        for record in normalized_records
    ]
    if observed_order != sorted(observed_identities):
        raise RuntimeError(
            "Page Composition recovery evidence revisions are not ordered."
        )
    return {**payload, "created_at": created_at, "records": normalized_records}


def _normalized_evidence_revision(
    value: Any,
    *,
    evidence_created_at: datetime,
    source_created_at: datetime,
    field: str,
) -> dict[str, Any]:
    expected_fields = {*REVISION_HASH_FIELDS, "revision_hash"}
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise RuntimeError(
            "Page Composition recovery evidence revision contract is incompatible."
        )
    normalized = dict(value)
    for name in (
        "page_composition_id",
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
        "composition_version",
    ):
        normalized[name] = _positive_integer(value[name], f"{field}.{name}")
    if value["generated_page_revision_id"] is not None:
        normalized["generated_page_revision_id"] = _positive_integer(
            value["generated_page_revision_id"],
            f"{field}.generated_page_revision_id",
        )
    if (
        value["supersedes_revision_id"] is not None
        or value["supersedes_revision_hash"] is not None
        or value["lineage_kind"] != "legacy_root"
        or value["recorded_by"] != RECOVERY_EVIDENCE_ACTOR
        or value["record_source"] != RECOVERY_EVIDENCE_SOURCE
    ):
        raise RuntimeError(
            "Page Composition recovery evidence revision provenance or root is invalid."
        )
    if (
        not isinstance(value["generated_components"], list)
        or not all(isinstance(item, dict) for item in value["generated_components"])
        or not isinstance(value["operator_decisions"], list)
        or not all(isinstance(item, dict) for item in value["operator_decisions"])
        or not isinstance(value["source_snapshot"], dict)
    ):
        raise RuntimeError(
            "Page Composition recovery evidence revision JSON payload is malformed."
        )
    normalized["generated_at"] = _evidence_timestamp(
        value["generated_at"],
        f"{field}.generated_at",
    )
    normalized["recorded_at"] = _evidence_timestamp(
        value["recorded_at"],
        f"{field}.recorded_at",
    )
    normalized["decided_at"] = (
        _evidence_timestamp(value["decided_at"], f"{field}.decided_at")
        if value["decided_at"] is not None
        else None
    )
    if (
        _canonical_utc_timestamp(normalized["recorded_at"])
        != _canonical_utc_timestamp(normalized["generated_at"])
        or _as_utc(normalized["recorded_at"]) > _as_utc(source_created_at)
        or _as_utc(normalized["recorded_at"]) > _as_utc(evidence_created_at)
    ):
        raise RuntimeError(
            "Page Composition recovery evidence has untruthful recording time."
        )
    if value["decided_by"] is not None and (
        not isinstance(value["decided_by"], str)
        or value["decided_by"] != value["decided_by"].strip()
        or not value["decided_by"]
    ):
        raise RuntimeError(
            "Page Composition recovery evidence decision provenance is malformed."
        )
    if (
        value["source_hash"] != _canonical_payload_hash(value["source_snapshot"])
        or value["content_hash"] != value["source_snapshot"].get("draft_hash")
        or not _is_lower_sha256(value["content_hash"])
        or not _is_lower_sha256(value["revision_hash"])
        or value["revision_hash"] != _composition_revision_hash(normalized)
    ):
        raise RuntimeError(
            "Page Composition recovery evidence revision hash is invalid."
        )
    for scope_field in (
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
    ):
        if value["source_snapshot"].get(scope_field) != value[scope_field]:
            raise RuntimeError(
                "Page Composition recovery evidence source snapshot crosses scope."
            )
    return normalized


def _normalized_evidence_qa_projection(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(QA_EVIDENCE_FIELDS):
        raise RuntimeError(
            "Page Composition recovery evidence QA contract is incompatible."
        )
    normalized = dict(value)
    for name in (
        "id",
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
        "page_composition_id",
        "composition_version",
    ):
        normalized[name] = _positive_integer(value[name], f"{field}.{name}")
    if value["latest_generated_page_revision_id"] is not None:
        normalized["latest_generated_page_revision_id"] = _positive_integer(
            value["latest_generated_page_revision_id"],
            f"{field}.latest_generated_page_revision_id",
        )
    for name in (
        "content_hash",
        "source_hash",
        "composition_source_hash",
        "qa_ruleset_hash",
        "result_hash",
    ):
        if not _is_lower_sha256(value[name]):
            raise RuntimeError(
                "Page Composition recovery evidence QA hash is malformed."
            )
    for name in (
        "qa_algorithm_key",
        "qa_algorithm_version",
        "qa_ruleset_key",
        "qa_ruleset_version",
    ):
        if (
            not isinstance(value[name], str)
            or value[name] != value[name].strip()
            or not value[name]
        ):
            raise RuntimeError(
                "Page Composition recovery evidence QA provenance is malformed."
            )
    if value["readiness_status"] not in {"ready", "needs_review", "blocked"}:
        raise RuntimeError(
            "Page Composition recovery evidence QA readiness is invalid."
        )
    for name in ("passed_count", "warning_count", "failed_count"):
        if (
            isinstance(value[name], bool)
            or not isinstance(value[name], int)
            or value[name] < 0
        ):
            raise RuntimeError(
                "Page Composition recovery evidence QA counts are invalid."
            )
    if not isinstance(value["check_payload"], list) or not all(
        isinstance(item, dict) for item in value["check_payload"]
    ):
        raise RuntimeError(
            "Page Composition recovery evidence QA checks are malformed."
        )
    normalized["evaluated_at"] = _evidence_timestamp(
        value["evaluated_at"],
        f"{field}.evaluated_at",
    )
    if value["result_hash"] != _qa_result_record_hash(normalized):
        raise RuntimeError(
            "Page Composition recovery evidence QA result hash is invalid."
        )
    return normalized


def _normalized_live_qa_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {field: value[field] for field in QA_EVIDENCE_FIELDS}
    normalized["evaluated_at"] = _require_datetime(
        normalized["evaluated_at"],
        "generatedpageqaresult.evaluated_at",
    )
    if normalized["result_hash"] != _qa_result_record_hash(normalized):
        raise RuntimeError("Generated Page QA result hash is invalid.")
    return normalized


def _qa_projections_equal(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> bool:
    for field in QA_EVIDENCE_FIELDS:
        left = expected[field]
        right = observed[field]
        if field == "evaluated_at":
            if _canonical_utc_timestamp(left) != _canonical_utc_timestamp(right):
                return False
        elif left != right:
            return False
    return True


def _qa_result_record_hash(values: Mapping[str, Any]) -> str:
    payload: dict[str, Any] = {}
    for field in QA_RESULT_HASH_FIELDS:
        value = values[field]
        if field == "evaluated_at":
            value = _canonical_utc_timestamp(
                _require_datetime(value, "qa.evaluated_at")
            )
        payload[field] = value
    return _canonical_payload_hash(payload)


def _evidence_timestamp(
    value: Any,
    field: str,
    *,
    require_utc: bool = False,
) -> datetime:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RuntimeError(f"{field} must be an exact timestamp string.")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = _require_datetime(normalized, field)
    if require_utc and (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset().total_seconds() != 0
    ):
        raise RuntimeError(f"{field} must be explicit UTC.")
    return parsed


def _is_pre_history_backup_version(value: str) -> bool:
    try:
        major, minor = value.split(".", maxsplit=1)
        version_value = (int(major), int(minor))
    except (TypeError, ValueError):
        return False
    return (0, 49) <= version_value < (0, 59)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise RuntimeError(
                "Page Composition recovery evidence contains a duplicate JSON key."
            )
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise RuntimeError(
        f"Page Composition recovery evidence contains invalid JSON constant {value}."
    )


def _validate_existing_qa_bindings(
    bind: Any,
    compositions: Mapping[int, Mapping[str, Any]],
    *,
    qa_rows: list[dict[str, Any]] | None = None,
    available_identities: set[tuple[int, int, str]] | None = None,
) -> None:
    rows = qa_rows if qa_rows is not None else _qa_evidence_rows(bind)
    for row in rows:
        binding = (
            row["page_composition_id"],
            row["composition_version"],
            row["composition_source_hash"],
        )
        if binding == (None, None, None):
            continue
        if any(value is None for value in binding):
            raise RuntimeError("Generated Page QA has a partial composition binding.")
        composition = compositions.get(row["page_composition_id"])
        if composition is None:
            raise RuntimeError(
                "Generated Page QA references an unknown Page Composition."
            )
        if (
            row["website_id"] != composition["website_id"]
            or row["site_plan_id"] != composition["site_plan_id"]
            or row["planned_page_id"] != composition["planned_page_id"]
            or row["generated_page_id"] != composition["generated_page_id"]
        ):
            raise RuntimeError(
                "Generated Page QA crosses its Page Composition scope."
            )
        if available_identities is None:
            expected = (
                composition["id"],
                composition["composition_version"],
                composition["source_hash"],
            )
            reconstructable = binding == expected
        else:
            reconstructable = binding in available_identities
        if not reconstructable:
            raise RuntimeError(
                "Generated Page QA cannot be reconstructed from exact Page "
                "Composition history."
            )


def _qa_evidence_rows(bind: Any) -> list[dict[str, Any]]:
    table = sa.table(
        "generatedpageqaresult",
        sa.column("id", sa.Integer()),
        sa.column("website_id", sa.Integer()),
        sa.column("site_plan_id", sa.Integer()),
        sa.column("planned_page_id", sa.Integer()),
        sa.column("generated_page_id", sa.Integer()),
        sa.column("latest_generated_page_revision_id", sa.Integer()),
        sa.column("content_hash", sa.String()),
        sa.column("source_hash", sa.String()),
        sa.column("page_composition_id", sa.Integer()),
        sa.column("composition_version", sa.Integer()),
        sa.column("composition_source_hash", sa.String()),
        sa.column("qa_algorithm_key", sa.String()),
        sa.column("qa_algorithm_version", sa.String()),
        sa.column("qa_ruleset_key", sa.String()),
        sa.column("qa_ruleset_version", sa.String()),
        sa.column("qa_ruleset_hash", sa.String()),
        sa.column("readiness_status", sa.String()),
        sa.column("passed_count", sa.Integer()),
        sa.column("warning_count", sa.Integer()),
        sa.column("failed_count", sa.Integer()),
        sa.column("check_payload", sa.JSON()),
        sa.column("evaluated_at", sa.DateTime()),
        sa.column("result_hash", sa.String()),
    )
    return [
        dict(row)
        for row in bind.execute(sa.select(*table.c).order_by(table.c.id)).mappings()
    ]


def _create_history_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("page_composition_id", sa.Integer(), nullable=False),
        sa.Column("website_id", sa.Integer(), nullable=False),
        sa.Column("site_plan_id", sa.Integer(), nullable=False),
        sa.Column("planned_page_id", sa.Integer(), nullable=False),
        sa.Column("generated_page_id", sa.Integer(), nullable=False),
        sa.Column("generated_page_revision_id", sa.Integer(), nullable=True),
        sa.Column("composition_version", sa.Integer(), nullable=False),
        sa.Column("supersedes_revision_id", sa.Integer(), nullable=True),
        sa.Column("supersedes_revision_hash", sa.String(length=64), nullable=True),
        sa.Column("lineage_kind", sa.String(length=24), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("generated_components", sa.JSON(), nullable=False),
        sa.Column("operator_decisions", sa.JSON(), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("revision_hash", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", sa.String(length=255), nullable=False),
        sa.Column("record_source", sa.String(length=80), nullable=False),
        sa.CheckConstraint(
            "composition_version >= 1",
            name="ck_pagecomprev_version",
        ),
        sa.CheckConstraint(HASH_CHECK, name="ck_pagecomprev_hashes"),
        sa.CheckConstraint(
            "(lineage_kind = 'initial' "
            "AND composition_version = 1 "
            "AND supersedes_revision_id IS NULL "
            "AND supersedes_revision_hash IS NULL) "
            "OR (lineage_kind = 'legacy_root' "
            "AND supersedes_revision_id IS NULL "
            "AND supersedes_revision_hash IS NULL) "
            "OR (lineage_kind = 'successor' "
            "AND composition_version > 1 "
            "AND supersedes_revision_id IS NOT NULL "
            "AND supersedes_revision_hash IS NOT NULL)",
            name="ck_pagecomprev_lineage",
        ),
        sa.CheckConstraint(
            "supersedes_revision_id IS NULL OR supersedes_revision_id != id",
            name="ck_pagecomprev_not_self",
        ),
        sa.CheckConstraint(
            "length(trim(recorded_by)) > 0 "
            "AND length(trim(record_source)) > 0",
            name="ck_pagecomprev_provenance",
        ),
        sa.ForeignKeyConstraint(
            ["page_composition_id"],
            ["pagecomposition.id"],
            name="fk_pagecomprev_composition",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["website.id"],
            name="fk_pagecomprev_website",
        ),
        sa.ForeignKeyConstraint(
            ["site_plan_id"],
            ["siteplan.id"],
            name="fk_pagecomprev_site_plan",
        ),
        sa.ForeignKeyConstraint(
            ["planned_page_id"],
            ["plannedpage.id"],
            name="fk_pagecomprev_planned_page",
        ),
        sa.ForeignKeyConstraint(
            ["generated_page_id"],
            ["generatedpage.id"],
            name="fk_pagecomprev_generated_page",
        ),
        sa.ForeignKeyConstraint(
            ["generated_page_revision_id"],
            ["generatedpagerevision.id"],
            name="fk_pagecomprev_generated_revision",
        ),
        sa.ForeignKeyConstraint(
            ["page_composition_id", "supersedes_revision_id"],
            [f"{TABLE}.page_composition_id", f"{TABLE}.id"],
            name="fk_pagecomprev_predecessor",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "page_composition_id",
            "id",
            name="uq_pagecomprev_stream_id",
        ),
        sa.UniqueConstraint(
            "page_composition_id",
            "composition_version",
            name="uq_pagecomprev_stream_version",
        ),
        sa.UniqueConstraint(
            "page_composition_id",
            "composition_version",
            "source_hash",
            name="uq_pagecomprev_identity",
        ),
        sa.UniqueConstraint(
            "page_composition_id",
            "supersedes_revision_id",
            name="uq_pagecomprev_successor",
        ),
        sa.UniqueConstraint(
            "page_composition_id",
            "revision_hash",
            name="uq_pagecomprev_stream_hash",
        ),
    )


def _create_history_indexes() -> None:
    for name, columns in EXPECTED_INDEXES.items():
        op.create_index(name, TABLE, list(columns), unique=False)


def _add_binding_foreign_keys(bind: Any) -> None:
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("pagecomposition", recreate="always") as batch:
            batch.create_foreign_key(
                CURRENT_HEAD_FK,
                TABLE,
                ["id", "composition_version", "source_hash"],
                ["page_composition_id", "composition_version", "source_hash"],
                deferrable=True,
                initially="DEFERRED",
            )
        with op.batch_alter_table(
            "generatedpageqaresult", recreate="always"
        ) as batch:
            batch.create_foreign_key(
                QA_REVISION_FK,
                TABLE,
                [
                    "page_composition_id",
                    "composition_version",
                    "composition_source_hash",
                ],
                ["page_composition_id", "composition_version", "source_hash"],
                deferrable=True,
                initially="DEFERRED",
            )
        return
    op.create_foreign_key(
        CURRENT_HEAD_FK,
        "pagecomposition",
        TABLE,
        ["id", "composition_version", "source_hash"],
        ["page_composition_id", "composition_version", "source_hash"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        QA_REVISION_FK,
        "generatedpageqaresult",
        TABLE,
        [
            "page_composition_id",
            "composition_version",
            "composition_source_hash",
        ],
        ["page_composition_id", "composition_version", "source_hash"],
        deferrable=True,
        initially="DEFERRED",
    )


def _drop_binding_foreign_keys(bind: Any) -> None:
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "generatedpageqaresult", recreate="always"
        ) as batch:
            batch.drop_constraint(QA_REVISION_FK, type_="foreignkey")
        with op.batch_alter_table("pagecomposition", recreate="always") as batch:
            batch.drop_constraint(CURRENT_HEAD_FK, type_="foreignkey")
        return
    op.drop_constraint(
        QA_REVISION_FK,
        "generatedpageqaresult",
        type_="foreignkey",
    )
    op.drop_constraint(
        CURRENT_HEAD_FK,
        "pagecomposition",
        type_="foreignkey",
    )


def _install_immutability_guards(bind: Any) -> None:
    message = "Page Composition revision history is immutable."
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                f"CREATE FUNCTION {IMMUTABLE_FUNCTION}() RETURNS trigger "
                "LANGUAGE plpgsql AS $atlas$ BEGIN "
                f"RAISE EXCEPTION '{message}' USING ERRCODE = '55000'; "
                "END; $atlas$"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {IMMUTABLE_ROW_TRIGGER} BEFORE UPDATE OR DELETE "
                f"ON {TABLE} FOR EACH ROW EXECUTE FUNCTION "
                f"{IMMUTABLE_FUNCTION}()"
            )
        )
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {IMMUTABLE_TRUNCATE_TRIGGER} BEFORE TRUNCATE "
                f"ON {TABLE} FOR EACH STATEMENT EXECUTE FUNCTION "
                f"{IMMUTABLE_FUNCTION}()"
            )
        )
        return
    bind.execute(
        sa.text(
            f"CREATE TRIGGER {SQLITE_UPDATE_TRIGGER} BEFORE UPDATE ON {TABLE} "
            f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
        )
    )
    bind.execute(
        sa.text(
            f"CREATE TRIGGER {SQLITE_DELETE_TRIGGER} BEFORE DELETE ON {TABLE} "
            f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
        )
    )


def _remove_immutability_guards(bind: Any) -> None:
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(f"DROP TRIGGER {IMMUTABLE_TRUNCATE_TRIGGER} ON {TABLE}")
        )
        bind.execute(sa.text(f"DROP TRIGGER {IMMUTABLE_ROW_TRIGGER} ON {TABLE}"))
        bind.execute(sa.text(f"DROP FUNCTION {IMMUTABLE_FUNCTION}()"))
        return
    bind.execute(sa.text(f"DROP TRIGGER {SQLITE_UPDATE_TRIGGER}"))
    bind.execute(sa.text(f"DROP TRIGGER {SQLITE_DELETE_TRIGGER}"))


def _assert_owned_shape(bind: Any) -> None:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if TABLE not in tables:
        raise RuntimeError("Page Composition revision table is missing.")
    columns = inspector.get_columns(TABLE)
    if tuple(item["name"] for item in columns) != EXPECTED_COLUMNS:
        raise RuntimeError("Page Composition revision columns are incompatible.")
    for item in columns:
        if bool(item["nullable"]) != (item["name"] in NULLABLE_COLUMNS):
            raise RuntimeError(
                f"Page Composition revision {item['name']} nullability is incompatible."
            )
    primary = inspector.get_pk_constraint(TABLE)
    if tuple(primary.get("constrained_columns") or ()) != ("id",):
        raise RuntimeError("Page Composition revision primary key is incompatible.")
    checks = {
        item.get("name") for item in inspector.get_check_constraints(TABLE)
    }
    if checks != EXPECTED_CHECKS:
        raise RuntimeError("Page Composition revision checks are incompatible.")
    uniques = {
        item.get("name"): tuple(item.get("column_names") or ())
        for item in inspector.get_unique_constraints(TABLE)
    }
    if uniques != EXPECTED_UNIQUES:
        raise RuntimeError("Page Composition revision unique constraints are incompatible.")
    indexes = {
        item.get("name"): tuple(item.get("column_names") or ())
        for item in inspector.get_indexes(TABLE)
        if not item.get("duplicates_constraint")
    }
    if indexes != EXPECTED_INDEXES or any(
        bool(item.get("unique"))
        for item in inspector.get_indexes(TABLE)
        if not item.get("duplicates_constraint")
    ):
        raise RuntimeError("Page Composition revision indexes are incompatible.")
    _assert_foreign_keys(inspector)
    _assert_immutability_guards(bind)


def _assert_foreign_keys(inspector: Any) -> None:
    observed: dict[str, tuple[tuple[str, ...], str, tuple[str, ...], bool]] = {}
    for item in inspector.get_foreign_keys(TABLE):
        options = {
            str(key).lower(): str(value).upper()
            for key, value in (item.get("options") or {}).items()
        }
        observed[str(item.get("name"))] = (
            tuple(item.get("constrained_columns") or ()),
            str(item.get("referred_table")),
            tuple(item.get("referred_columns") or ()),
            options.get("deferrable") in {"TRUE", "1"}
            and options.get("initially") == "DEFERRED",
        )
    if observed != EXPECTED_HISTORY_FKS:
        raise RuntimeError("Page Composition revision foreign keys are incompatible.")
    for table, name, local, remote in (
        (
            "pagecomposition",
            CURRENT_HEAD_FK,
            ("id", "composition_version", "source_hash"),
            ("page_composition_id", "composition_version", "source_hash"),
        ),
        (
            "generatedpageqaresult",
            QA_REVISION_FK,
            (
                "page_composition_id",
                "composition_version",
                "composition_source_hash",
            ),
            ("page_composition_id", "composition_version", "source_hash"),
        ),
    ):
        matches = [
            item
            for item in inspector.get_foreign_keys(table)
            if item.get("name") == name
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Page Composition binding {name} is missing.")
        item = matches[0]
        options = {
            str(key).lower(): str(value).upper()
            for key, value in (item.get("options") or {}).items()
        }
        if (
            tuple(item.get("constrained_columns") or ()) != local
            or item.get("referred_table") != TABLE
            or tuple(item.get("referred_columns") or ()) != remote
            or options.get("deferrable") not in {"TRUE", "1"}
            or options.get("initially") != "DEFERRED"
        ):
            raise RuntimeError(f"Page Composition binding {name} is incompatible.")


def _assert_immutability_guards(bind: Any) -> None:
    if bind.dialect.name == "postgresql":
        functions = bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM pg_proc p JOIN pg_namespace n "
                "ON n.oid = p.pronamespace WHERE n.nspname = current_schema() "
                "AND p.proname = :name AND p.prorettype = 'trigger'::regtype "
                "AND p.prokind = 'f'"
            ),
            {"name": IMMUTABLE_FUNCTION},
        ).scalar_one()
        triggers = {
            row["name"]: (row["enabled"], int(row["type_bits"]), row["function"])
            for row in bind.execute(
                sa.text(
                    "SELECT g.tgname AS name, g.tgenabled AS enabled, "
                    "g.tgtype AS type_bits, p.proname AS function "
                    "FROM pg_trigger g "
                    "JOIN pg_class t ON t.oid = g.tgrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "JOIN pg_proc p ON p.oid = g.tgfoid "
                    "WHERE n.nspname = current_schema() AND t.relname = :table "
                    "AND NOT g.tgisinternal"
                ),
                {"table": TABLE},
            ).mappings()
        }
        if functions != 1 or triggers != {
            IMMUTABLE_ROW_TRIGGER: ("O", 27, IMMUTABLE_FUNCTION),
            IMMUTABLE_TRUNCATE_TRIGGER: ("O", 34, IMMUTABLE_FUNCTION),
        }:
            raise RuntimeError(
                "Page Composition revision immutability guards are incompatible."
            )
        return
    triggers = {
        row["name"]: re.sub(r"\s+", " ", str(row["sql"] or "")).lower()
        for row in bind.execute(
            sa.text(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = :table"
            ),
            {"table": TABLE},
        ).mappings()
    }
    if set(triggers) != {SQLITE_UPDATE_TRIGGER, SQLITE_DELETE_TRIGGER} or not all(
        "raise(abort, 'page composition revision history is immutable.')"
        in sql
        for sql in triggers.values()
    ) or "before update" not in triggers[SQLITE_UPDATE_TRIGGER] or (
        "before delete" not in triggers[SQLITE_DELETE_TRIGGER]
    ):
        raise RuntimeError(
            "Page Composition revision immutability guards are incompatible."
        )


def _assert_history_matches_heads_and_qa(
    bind: Any,
    *,
    require_pristine_roots: bool,
) -> None:
    history = _history_table()
    rows = [dict(row) for row in bind.execute(sa.select(*history.c)).mappings()]
    by_composition: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_composition.setdefault(row["page_composition_id"], []).append(row)
        _validate_history_row_hash(row)
    heads = {
        row["id"]: dict(row)
        for row in bind.execute(
            sa.select(*_page_composition_table().c)
        ).mappings()
    }
    if set(by_composition) != set(heads):
        raise RuntimeError(
            "Page Composition history does not contain one stream for every head."
        )
    for composition_id, head in heads.items():
        records = sorted(
            by_composition[composition_id],
            key=lambda value: (value["composition_version"], value["id"]),
        )
        root = records[0]
        if (
            root["lineage_kind"] != "legacy_root"
            or root["supersedes_revision_id"] is not None
            or root["supersedes_revision_hash"] is not None
        ):
            raise RuntimeError("Page Composition history has an invalid legacy root.")
        for predecessor, successor in zip(records, records[1:], strict=False):
            if (
                successor["composition_version"]
                != predecessor["composition_version"] + 1
                or successor["lineage_kind"] != "successor"
                or successor["supersedes_revision_id"] != predecessor["id"]
                or successor["supersedes_revision_hash"]
                != predecessor["revision_hash"]
                or _as_utc(
                    _require_datetime(
                        successor["recorded_at"],
                        "history.recorded_at",
                    )
                )
                < _as_utc(
                    _require_datetime(
                        predecessor["recorded_at"],
                        "history.recorded_at",
                    )
                )
            ):
                raise RuntimeError(
                    "Page Composition history is disconnected, branched, or has "
                    "decreasing recording time."
                )

        is_pristine_backfill = (
            len(records) == 1
            and root["recorded_by"] == MIGRATION_BACKFILL_ACTOR
            and root["record_source"] == MIGRATION_BACKFILL_SOURCE
        )
        is_exact_recovery_backfill = (
            len(records) == 2
            and root["recorded_by"] == RECOVERY_EVIDENCE_ACTOR
            and root["record_source"] == RECOVERY_EVIDENCE_SOURCE
            and records[1]["recorded_by"] == MIGRATION_BACKFILL_ACTOR
            and records[1]["record_source"] == MIGRATION_BACKFILL_SOURCE
        )
        if require_pristine_roots and not is_pristine_backfill:
            raise RuntimeError(
                "Downgrade blocked: Page Composition history contains durable "
                "recovery or post-migration revisions. Recover through an accepted "
                "backup and evidence sidecar."
            )
        if not require_pristine_roots and not (
            is_pristine_backfill or is_exact_recovery_backfill
        ):
            raise RuntimeError(
                "Page Composition history backfill provenance is incompatible."
            )
        current = [
            row
            for row in records
            if row["composition_version"] == head["composition_version"]
            and row["source_hash"] == head["source_hash"]
        ]
        if len(current) != 1:
            raise RuntimeError(
                "Page Composition head does not resolve one exact history revision."
            )
        _assert_head_mirror(head, current[0])
    available_identities = {
        (
            row["page_composition_id"],
            row["composition_version"],
            row["source_hash"],
        )
        for row in rows
    }
    _validate_existing_qa_bindings(
        bind,
        heads,
        available_identities=available_identities,
    )


def _validate_history_row_hash(row: Mapping[str, Any]) -> None:
    if row["source_hash"] != _canonical_payload_hash(row["source_snapshot"]):
        raise RuntimeError("Page Composition history source hash was altered.")
    if row["content_hash"] != row["source_snapshot"].get("draft_hash"):
        raise RuntimeError("Page Composition history content hash was altered.")
    if row["revision_hash"] != _composition_revision_hash(row):
        raise RuntimeError("Page Composition history revision hash was altered.")


def _assert_head_mirror(
    head: Mapping[str, Any],
    revision_row: Mapping[str, Any],
) -> None:
    fields = (
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
        "composition_version",
        "generated_components",
        "operator_decisions",
        "source_snapshot",
        "source_hash",
        "generated_at",
        "decided_by",
        "decided_at",
    )
    for field in fields:
        left = head[field]
        right = revision_row[field]
        if isinstance(left, datetime) and isinstance(right, datetime):
            if _canonical_utc_timestamp(left) == _canonical_utc_timestamp(right):
                continue
        elif left == right:
            continue
        raise RuntimeError(
            f"Page Composition head diverges from history field {field}."
        )


def _history_table() -> sa.TableClause:
    return sa.table(
        TABLE,
        sa.column("id", sa.Integer()),
        sa.column("page_composition_id", sa.Integer()),
        sa.column("website_id", sa.Integer()),
        sa.column("site_plan_id", sa.Integer()),
        sa.column("planned_page_id", sa.Integer()),
        sa.column("generated_page_id", sa.Integer()),
        sa.column("generated_page_revision_id", sa.Integer()),
        sa.column("composition_version", sa.Integer()),
        sa.column("supersedes_revision_id", sa.Integer()),
        sa.column("supersedes_revision_hash", sa.String()),
        sa.column("lineage_kind", sa.String()),
        sa.column("content_hash", sa.String()),
        sa.column("generated_components", sa.JSON()),
        sa.column("operator_decisions", sa.JSON()),
        sa.column("source_snapshot", sa.JSON()),
        sa.column("source_hash", sa.String()),
        sa.column("revision_hash", sa.String()),
        sa.column("generated_at", sa.DateTime()),
        sa.column("decided_by", sa.String()),
        sa.column("decided_at", sa.DateTime()),
        sa.column("recorded_at", sa.DateTime(timezone=True)),
        sa.column("recorded_by", sa.String()),
        sa.column("record_source", sa.String()),
    )


def _page_composition_table() -> sa.TableClause:
    return sa.table(
        "pagecomposition",
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
        sa.column("id", sa.Integer()),
        sa.column("website_id", sa.Integer()),
        sa.column("site_plan_id", sa.Integer()),
        sa.column("planned_page_id", sa.Integer()),
        sa.column("generated_page_id", sa.Integer()),
        sa.column("composition_version", sa.Integer()),
        sa.column("generated_components", sa.JSON()),
        sa.column("operator_decisions", sa.JSON()),
        sa.column("source_snapshot", sa.JSON()),
        sa.column("source_hash", sa.String()),
        sa.column("status", sa.String()),
        sa.column("generated_at", sa.DateTime()),
        sa.column("decided_by", sa.String()),
        sa.column("decided_at", sa.DateTime()),
    )


def _canonical_payload_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _composition_revision_hash(values: Mapping[str, Any]) -> str:
    payload: dict[str, Any] = {}
    for field in REVISION_HASH_FIELDS:
        if field not in values:
            raise RuntimeError(
                f"Page Composition revision hash input is missing {field}."
            )
        value = values[field]
        if field in {"generated_at", "recorded_at"}:
            value = _canonical_utc_timestamp(
                _require_datetime(value, f"history.{field}")
            )
        elif field == "decided_at" and value is not None:
            value = _canonical_utc_timestamp(
                _require_datetime(value, "history.decided_at")
            )
        payload[field] = value
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _canonical_utc_timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _as_utc(value: datetime) -> datetime:
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return normalized.astimezone(UTC)


def _require_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise RuntimeError(f"{field} is not an exact timestamp.") from exc
    raise RuntimeError(f"{field} is not an exact timestamp.")


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeError(f"{field} must be a positive integer.")
    return value


def _is_lower_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )
