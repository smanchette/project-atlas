"""Add durable, identity-bound Generated Page QA result history.

Revision ID: 20260809_0043
Revises: 20260809_0042
"""

from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260809_0043"
down_revision = "20260809_0042"
branch_labels = None
depends_on = None


TABLE = "generatedpageqaresult"
CURRENT_INDEX = "uq_generatedpageqaresult_current_page"
CURRENT_PREDICATE = "lifecycle_status = 'current'"
LIFECYCLE_CHECK = "lifecycle_status IN ('current','superseded','historical_unbound')"
READINESS_CHECK = (
    "readiness_status IS NULL "
    "OR readiness_status IN ('ready','needs_review','blocked')"
)
HASH_LENGTH_CHECK = (
    "length(result_hash) = 64 "
    "AND (content_hash IS NULL OR length(content_hash) = 64) "
    "AND (source_hash IS NULL OR length(source_hash) = 64) "
    "AND (composition_source_hash IS NULL "
    "OR length(composition_source_hash) = 64) "
    "AND (qa_ruleset_hash IS NULL OR length(qa_ruleset_hash) = 64)"
)
COMPOSITION_BINDING_CHECK = (
    "(page_composition_id IS NULL "
    "AND composition_version IS NULL "
    "AND composition_source_hash IS NULL) OR ("
    "page_composition_id IS NOT NULL "
    "AND composition_version IS NOT NULL "
    "AND composition_source_hash IS NOT NULL)"
)
BOUND_EVIDENCE_CHECK = (
    "lifecycle_status = 'historical_unbound' OR ("
    "website_id IS NOT NULL "
    "AND site_plan_id IS NOT NULL "
    "AND planned_page_id IS NOT NULL "
    "AND content_hash IS NOT NULL "
    "AND source_hash IS NOT NULL "
    "AND qa_algorithm_key IS NOT NULL "
    "AND length(trim(qa_algorithm_key)) > 0 "
    "AND qa_algorithm_version IS NOT NULL "
    "AND length(trim(qa_algorithm_version)) > 0 "
    "AND qa_ruleset_key IS NOT NULL "
    "AND length(trim(qa_ruleset_key)) > 0 "
    "AND qa_ruleset_version IS NOT NULL "
    "AND length(trim(qa_ruleset_version)) > 0 "
    "AND qa_ruleset_hash IS NOT NULL "
    "AND readiness_status IS NOT NULL "
    "AND passed_count IS NOT NULL "
    "AND warning_count IS NOT NULL "
    "AND failed_count IS NOT NULL "
    "AND check_payload IS NOT NULL "
    "AND evaluated_at IS NOT NULL "
    "AND historical_payload IS NULL)"
)
EXPECTED_COLUMNS = {
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
EXPECTED_COLUMN_SPECS = {
    "created_at": ("datetime", None, False),
    "updated_at": ("datetime", None, False),
    "id": ("integer", None, False),
    "website_id": ("integer", None, True),
    "site_plan_id": ("integer", None, True),
    "planned_page_id": ("integer", None, True),
    "generated_page_id": ("integer", None, False),
    "latest_generated_page_revision_id": ("integer", None, True),
    "content_hash": ("string", 64, True),
    "source_hash": ("string", 64, True),
    "page_composition_id": ("integer", None, True),
    "composition_version": ("integer", None, True),
    "composition_source_hash": ("string", 64, True),
    "qa_algorithm_key": ("string", 120, True),
    "qa_algorithm_version": ("string", 80, True),
    "qa_ruleset_key": ("string", 120, True),
    "qa_ruleset_version": ("string", 80, True),
    "qa_ruleset_hash": ("string", 64, True),
    "readiness_status": ("string", 32, True),
    "passed_count": ("integer", None, True),
    "warning_count": ("integer", None, True),
    "failed_count": ("integer", None, True),
    "check_payload": ("json", None, True),
    "evaluated_at": ("datetime", None, True),
    "lifecycle_status": ("string", 32, False),
    "supersedes_qa_result_id": ("integer", None, True),
    "result_hash": ("string", 64, False),
    "historical_payload": ("json", None, True),
}
EXPECTED_FOREIGN_KEYS = {
    ("website_id", "website", "id"),
    ("site_plan_id", "siteplan", "id"),
    ("planned_page_id", "plannedpage", "id"),
    ("generated_page_id", "generatedpage", "id"),
    ("latest_generated_page_revision_id", "generatedpagerevision", "id"),
    ("page_composition_id", "pagecomposition", "id"),
    ("supersedes_qa_result_id", TABLE, "id"),
}
BASE_TABLE_COLUMNS = {
    "website": {"id"},
    "siteplan": {"id"},
    "plannedpage": {"id", "site_plan_id", "generated_page_id"},
    "generatedpage": {"id", "website_id", "qa_result", "qa_checked_at"},
    "generatedpagerevision": {"id"},
    "pagecomposition": {"id"},
}
DESIRED_CHECK_NAMES = {
    "ck_generatedpageqaresult_lifecycle",
    "ck_generatedpageqaresult_readiness",
    "ck_generatedpageqaresult_passed_count",
    "ck_generatedpageqaresult_warning_count",
    "ck_generatedpageqaresult_failed_count",
    "ck_generatedpageqaresult_composition_version",
    "ck_generatedpageqaresult_hash_lengths",
    "ck_generatedpageqaresult_historical_payload",
    "ck_generatedpageqaresult_composition_binding",
    "ck_generatedpageqaresult_bound_evidence",
    "ck_generatedpageqaresult_not_self_superseding",
}
CHECK_CONTRACTS = {
    "ck_generatedpageqaresult_lifecycle": LIFECYCLE_CHECK,
    "ck_generatedpageqaresult_readiness": READINESS_CHECK,
    "ck_generatedpageqaresult_passed_count": (
        "passed_count IS NULL OR passed_count >= 0"
    ),
    "ck_generatedpageqaresult_warning_count": (
        "warning_count IS NULL OR warning_count >= 0"
    ),
    "ck_generatedpageqaresult_failed_count": (
        "failed_count IS NULL OR failed_count >= 0"
    ),
    "ck_generatedpageqaresult_composition_version": (
        "composition_version IS NULL OR composition_version >= 1"
    ),
    "ck_generatedpageqaresult_hash_lengths": HASH_LENGTH_CHECK,
    "ck_generatedpageqaresult_historical_payload": (
        "lifecycle_status != 'historical_unbound' "
        "OR historical_payload IS NOT NULL"
    ),
    "ck_generatedpageqaresult_composition_binding": COMPOSITION_BINDING_CHECK,
    "ck_generatedpageqaresult_bound_evidence": BOUND_EVIDENCE_CHECK,
    "ck_generatedpageqaresult_not_self_superseding": (
        "supersedes_qa_result_id IS NULL OR supersedes_qa_result_id != id"
    ),
}
DESIRED_INDEXES = {
    "ix_generatedpageqaresult_website_id": (("website_id",), False),
    "ix_generatedpageqaresult_site_plan_id": (("site_plan_id",), False),
    "ix_generatedpageqaresult_planned_page_id": (("planned_page_id",), False),
    "ix_generatedpageqaresult_generated_page_id": (("generated_page_id",), False),
    "ix_generatedpageqaresult_latest_generated_page_revision_id": (
        ("latest_generated_page_revision_id",),
        False,
    ),
    "ix_generatedpageqaresult_page_composition_id": (("page_composition_id",), False),
    "ix_generatedpageqaresult_readiness_status": (("readiness_status",), False),
    "ix_generatedpageqaresult_evaluated_at": (("evaluated_at",), False),
    "ix_generatedpageqaresult_lifecycle_status": (("lifecycle_status",), False),
    "ix_generatedpageqaresult_supersedes_qa_result_id": (
        ("supersedes_qa_result_id",),
        False,
    ),
    "ix_generatedpageqaresult_scope": (
        ("website_id", "site_plan_id", "planned_page_id"),
        False,
    ),
    "ix_generatedpageqaresult_page_evaluated": (
        ("generated_page_id", "evaluated_at"),
        False,
    ),
    CURRENT_INDEX: (("generated_page_id",), True),
}
def _inspector():
    return sa.inspect(op.get_bind())


def _type_contract(column_type: Any) -> tuple[str, int | None]:
    if isinstance(column_type, sa.Integer):
        return "integer", None
    if isinstance(column_type, sa.String):
        return "string", column_type.length
    if isinstance(column_type, sa.DateTime):
        return "datetime", None
    if isinstance(column_type, sa.JSON):
        return "json", None
    return type(column_type).__name__.lower(), getattr(column_type, "length", None)


def _strip_outer_parentheses(value: str) -> str:
    result = value.strip()
    while result.startswith("(") and result.endswith(")"):
        depth = 0
        quoted = False
        closes_at_end = False
        index = 0
        while index < len(result):
            character = result[index]
            if character == "'":
                if quoted and index + 1 < len(result) and result[index + 1] == "'":
                    index += 2
                    continue
                quoted = not quoted
            elif not quoted:
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth == 0:
                        closes_at_end = index == len(result) - 1
                        break
            index += 1
        if not closes_at_end:
            break
        result = result[1:-1].strip()
    return result


def _normalized_check_sql(value: Any) -> str:
    normalized = str("" if value is None else value).lower().strip()
    if normalized.startswith("check"):
        normalized = normalized[len("check") :].strip()
    normalized = re.sub(
        r"::\s*(?:character\s+varying|text)(?:\s*\[\s*\])?",
        "",
        normalized,
    )
    normalized = re.sub(
        r"trim\s*\(\s*both\s+from\s+([a-z_][a-z0-9_]*)\s*\)",
        r"trim(\1)",
        normalized,
    )
    # PostgreSQL may render otherwise equivalent identifiers and ARRAY
    # operands with an additional parenthesis layer around the cast target.
    # Remove only those representation-only wrappers before normalizing ANY.
    normalized = re.sub(
        r"\(\s*([a-z_][a-z0-9_]*)\s*\)",
        r"\1",
        normalized,
    )
    normalized = re.sub(
        r"([a-z_][a-z0-9_]*)\s*=\s*any\s*"
        r"\(\s*\(\s*array\s*\[([^\]]*)\]\s*\)\s*\)",
        r"\1 in (\2)",
        normalized,
    )
    normalized = re.sub(
        r"([a-z_][a-z0-9_]*)\s*=\s*any\s*"
        r"\(\s*array\s*\[([^\]]*)\]\s*\)",
        r"\1 in (\2)",
        normalized,
    )
    normalized = normalized.replace("<>", "!=")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return _strip_outer_parentheses(normalized)


def _split_top_level_boolean(value: str, operator: str) -> list[str]:
    marker = f" {operator} "
    parts: list[str] = []
    start = 0
    depth = 0
    quoted = False
    index = 0
    while index < len(value):
        character = value[index]
        if character == "'":
            if quoted and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            quoted = not quoted
            index += 1
            continue
        if not quoted:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif depth == 0 and value.startswith(marker, index):
                parts.append(value[start:index].strip())
                index += len(marker)
                start = index
                continue
        index += 1
    if not parts:
        return [value]
    parts.append(value[start:].strip())
    return parts


def _check_contract_ast(value: Any) -> tuple[Any, ...]:
    expression = _strip_outer_parentheses(_normalized_check_sql(value))
    or_parts = _split_top_level_boolean(expression, "or")
    if len(or_parts) > 1:
        children = tuple(
            sorted((_check_contract_ast(part) for part in or_parts), key=repr)
        )
        return ("or", *children)
    and_parts = _split_top_level_boolean(expression, "and")
    if len(and_parts) > 1:
        children = tuple(
            sorted((_check_contract_ast(part) for part in and_parts), key=repr)
        )
        return ("and", *children)
    return ("atom", re.sub(r"\s+", "", expression))


def _validate_check_contracts(
    checks: dict[str, str],
) -> None:
    expected = dict(CHECK_CONTRACTS)
    if set(checks) != set(expected):
        raise RuntimeError(f"Existing {TABLE} table has an unexpected CHECK contract.")
    for name, expected_sql in expected.items():
        if _check_contract_ast(checks[name]) != _check_contract_ast(expected_sql):
            raise RuntimeError(f"Existing {TABLE} table has a malformed {name} CHECK.")


def _inspected_check_contracts(inspector: Any) -> dict[str, str]:
    items = inspector.get_check_constraints(TABLE)
    names = [item.get("name") for item in items]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise RuntimeError(f"Existing {TABLE} table has an unexpected CHECK contract.")
    return {
        str(item["name"]): str(item.get("sqltext") or "")
        for item in items
    }


def _validate_foreign_key_contracts(inspector: Any) -> None:
    inspected_foreign_keys = inspector.get_foreign_keys(TABLE)
    foreign_keys = {
        (
            tuple(item.get("constrained_columns") or ()),
            item.get("referred_schema"),
            item.get("referred_table"),
            tuple(item.get("referred_columns") or ()),
            tuple(
                sorted(
                    (str(key), str(value))
                    for key, value in (item.get("options") or {}).items()
                )
            ),
        )
        for item in inspected_foreign_keys
    }
    expected_foreign_keys = {
        ((column,), None, referred_table, (referred_column,), ())
        for column, referred_table, referred_column in EXPECTED_FOREIGN_KEYS
    }
    if (
        len(inspected_foreign_keys) != len(EXPECTED_FOREIGN_KEYS)
        or foreign_keys != expected_foreign_keys
    ):
        raise RuntimeError(
            f"Existing {TABLE} table has an incompatible foreign key contract."
        )


def _normalized_index_predicate(index: dict[str, Any]) -> str:
    dialect_options = index.get("dialect_options") or {}
    predicate = dialect_options.get("postgresql_where")
    if predicate is None:
        predicate = dialect_options.get("sqlite_where")
    normalized = _strip_outer_parentheses(_normalized_check_sql(predicate))
    return re.sub(r"\s+", "", normalized)


def _validate_index_contracts(
    inspector: Any,
) -> None:
    indexes = {
        item["name"]: item
        for item in inspector.get_indexes(TABLE)
        if not item.get("duplicates_constraint")
    }
    if not set(indexes).issubset(DESIRED_INDEXES):
        raise RuntimeError(f"Existing {TABLE} table has unexpected indexes.")
    for name, (columns, unique) in DESIRED_INDEXES.items():
        item = indexes.get(name)
        if item is None:
            continue
        malformed_shape = (
            tuple(item.get("column_names") or ()) != columns
            or bool(item.get("unique")) != unique
        )
        predicate = _normalized_index_predicate(item)
        if name == CURRENT_INDEX and (
            malformed_shape or predicate != "lifecycle_status='current'"
        ):
            raise RuntimeError(
                f"Existing {TABLE} table has a malformed current-result index."
            )
        if name != CURRENT_INDEX and (malformed_shape or predicate):
            raise RuntimeError(f"Existing {TABLE} table has a malformed {name} index.")
def _canonical_payload_hash(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _historical_rows() -> list[dict[str, Any]]:
    bind = op.get_bind()
    generated_page = sa.table(
        "generatedpage",
        sa.column("id", sa.Integer()),
        sa.column("website_id", sa.Integer()),
        sa.column("qa_result", sa.JSON()),
        sa.column("qa_checked_at", sa.DateTime()),
    )
    planned_page = sa.table(
        "plannedpage",
        sa.column("id", sa.Integer()),
        sa.column("site_plan_id", sa.Integer()),
        sa.column("generated_page_id", sa.Integer()),
    )
    planned_by_generated: dict[int, list[tuple[int, int]]] = {}
    for record in bind.execute(
        sa.select(
            planned_page.c.generated_page_id,
            planned_page.c.id,
            planned_page.c.site_plan_id,
        ).where(planned_page.c.generated_page_id.is_not(None))
    ).mappings():
        planned_by_generated.setdefault(record["generated_page_id"], []).append(
            (record["id"], record["site_plan_id"])
        )

    now = datetime.now(UTC).replace(tzinfo=None)
    rows: list[dict[str, Any]] = []
    for record in bind.execute(
        sa.select(
            generated_page.c.id,
            generated_page.c.website_id,
            generated_page.c.qa_result,
            generated_page.c.qa_checked_at,
        ).order_by(generated_page.c.id)
    ).mappings():
        payload = record["qa_result"]
        if payload is None:
            continue
        planned_matches = planned_by_generated.get(record["id"], [])
        planned_page_id = None
        site_plan_id = None
        if len(planned_matches) == 1:
            planned_page_id, site_plan_id = planned_matches[0]
        readiness_status = None
        passed_count = None
        warning_count = None
        failed_count = None
        check_payload = None
        if isinstance(payload, dict):
            candidate_status = payload.get("readiness_status")
            if candidate_status in {"ready", "needs_review", "blocked"}:
                readiness_status = candidate_status
            passed_count = _nonnegative_integer(payload.get("passed_count"))
            warning_count = _nonnegative_integer(payload.get("warning_count"))
            failed_count = _nonnegative_integer(payload.get("failed_count"))
            candidate_checks = payload.get("checks")
            if isinstance(candidate_checks, list):
                check_payload = candidate_checks
        rows.append(
            {
                "created_at": now,
                "updated_at": now,
                "website_id": record["website_id"],
                "site_plan_id": site_plan_id,
                "planned_page_id": planned_page_id,
                "generated_page_id": record["id"],
                "latest_generated_page_revision_id": None,
                "content_hash": None,
                "source_hash": None,
                "page_composition_id": None,
                "composition_version": None,
                "composition_source_hash": None,
                "qa_algorithm_key": None,
                "qa_algorithm_version": None,
                "qa_ruleset_key": None,
                "qa_ruleset_version": None,
                "qa_ruleset_hash": None,
                "readiness_status": readiness_status,
                "passed_count": passed_count,
                "warning_count": warning_count,
                "failed_count": failed_count,
                "check_payload": check_payload,
                "evaluated_at": record["qa_checked_at"],
                "lifecycle_status": "historical_unbound",
                "supersedes_qa_result_id": None,
                "result_hash": _canonical_payload_hash(payload),
                "historical_payload": payload,
            }
        )
    return rows


def _create_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_id", sa.Integer(), nullable=True),
        sa.Column("site_plan_id", sa.Integer(), nullable=True),
        sa.Column("planned_page_id", sa.Integer(), nullable=True),
        sa.Column("generated_page_id", sa.Integer(), nullable=False),
        sa.Column("latest_generated_page_revision_id", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("page_composition_id", sa.Integer(), nullable=True),
        sa.Column("composition_version", sa.Integer(), nullable=True),
        sa.Column("composition_source_hash", sa.String(length=64), nullable=True),
        sa.Column("qa_algorithm_key", sa.String(length=120), nullable=True),
        sa.Column("qa_algorithm_version", sa.String(length=80), nullable=True),
        sa.Column("qa_ruleset_key", sa.String(length=120), nullable=True),
        sa.Column("qa_ruleset_version", sa.String(length=80), nullable=True),
        sa.Column("qa_ruleset_hash", sa.String(length=64), nullable=True),
        sa.Column("readiness_status", sa.String(length=32), nullable=True),
        sa.Column("passed_count", sa.Integer(), nullable=True),
        sa.Column("warning_count", sa.Integer(), nullable=True),
        sa.Column("failed_count", sa.Integer(), nullable=True),
        sa.Column("check_payload", sa.JSON(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(), nullable=True),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False),
        sa.Column("supersedes_qa_result_id", sa.Integer(), nullable=True),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        sa.Column("historical_payload", sa.JSON(none_as_null=True), nullable=True),
        sa.CheckConstraint(
            LIFECYCLE_CHECK,
            name="ck_generatedpageqaresult_lifecycle",
        ),
        sa.CheckConstraint(
            READINESS_CHECK,
            name="ck_generatedpageqaresult_readiness",
        ),
        sa.CheckConstraint(
            "passed_count IS NULL OR passed_count >= 0",
            name="ck_generatedpageqaresult_passed_count",
        ),
        sa.CheckConstraint(
            "warning_count IS NULL OR warning_count >= 0",
            name="ck_generatedpageqaresult_warning_count",
        ),
        sa.CheckConstraint(
            "failed_count IS NULL OR failed_count >= 0",
            name="ck_generatedpageqaresult_failed_count",
        ),
        sa.CheckConstraint(
            "composition_version IS NULL OR composition_version >= 1",
            name="ck_generatedpageqaresult_composition_version",
        ),
        sa.CheckConstraint(
            HASH_LENGTH_CHECK,
            name="ck_generatedpageqaresult_hash_lengths",
        ),
        sa.CheckConstraint(
            "lifecycle_status != 'historical_unbound' "
            "OR historical_payload IS NOT NULL",
            name="ck_generatedpageqaresult_historical_payload",
        ),
        sa.CheckConstraint(
            COMPOSITION_BINDING_CHECK,
            name="ck_generatedpageqaresult_composition_binding",
        ),
        sa.CheckConstraint(
            BOUND_EVIDENCE_CHECK,
            name="ck_generatedpageqaresult_bound_evidence",
        ),
        sa.CheckConstraint(
            "supersedes_qa_result_id IS NULL OR supersedes_qa_result_id != id",
            name="ck_generatedpageqaresult_not_self_superseding",
        ),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["website.id"],
            name="fk_generatedpageqaresult_website_id",
        ),
        sa.ForeignKeyConstraint(
            ["site_plan_id"],
            ["siteplan.id"],
            name="fk_generatedpageqaresult_site_plan_id",
        ),
        sa.ForeignKeyConstraint(
            ["planned_page_id"],
            ["plannedpage.id"],
            name="fk_generatedpageqaresult_planned_page_id",
        ),
        sa.ForeignKeyConstraint(
            ["generated_page_id"],
            ["generatedpage.id"],
            name="fk_generatedpageqaresult_generated_page_id",
        ),
        sa.ForeignKeyConstraint(
            ["latest_generated_page_revision_id"],
            ["generatedpagerevision.id"],
            name="fk_generatedpageqaresult_latest_revision_id",
        ),
        sa.ForeignKeyConstraint(
            ["page_composition_id"],
            ["pagecomposition.id"],
            name="fk_generatedpageqaresult_page_composition_id",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_qa_result_id"],
            [f"{TABLE}.id"],
            name="fk_generatedpageqaresult_supersedes_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generated_page_id",
            "result_hash",
            name="uq_generatedpageqaresult_page_result_hash",
        ),
    )


def _create_indexes() -> None:
    for name, columns in (
        ("ix_generatedpageqaresult_website_id", ["website_id"]),
        ("ix_generatedpageqaresult_site_plan_id", ["site_plan_id"]),
        ("ix_generatedpageqaresult_planned_page_id", ["planned_page_id"]),
        ("ix_generatedpageqaresult_generated_page_id", ["generated_page_id"]),
        (
            "ix_generatedpageqaresult_latest_generated_page_revision_id",
            ["latest_generated_page_revision_id"],
        ),
        ("ix_generatedpageqaresult_page_composition_id", ["page_composition_id"]),
        ("ix_generatedpageqaresult_readiness_status", ["readiness_status"]),
        ("ix_generatedpageqaresult_evaluated_at", ["evaluated_at"]),
        ("ix_generatedpageqaresult_lifecycle_status", ["lifecycle_status"]),
        (
            "ix_generatedpageqaresult_supersedes_qa_result_id",
            ["supersedes_qa_result_id"],
        ),
        (
            "ix_generatedpageqaresult_scope",
            ["website_id", "site_plan_id", "planned_page_id"],
        ),
        (
            "ix_generatedpageqaresult_page_evaluated",
            ["generated_page_id", "evaluated_at"],
        ),
    ):
        op.create_index(name, TABLE, columns, unique=False)
    op.create_index(
        CURRENT_INDEX,
        TABLE,
        ["generated_page_id"],
        unique=True,
        postgresql_where=sa.text(CURRENT_PREDICATE),
        sqlite_where=sa.text(CURRENT_PREDICATE),
    )


def _adopt_empty_model_created_table() -> None:
    """Adopt only the exact, empty table created by the current SQLModel.

    The local development server calls ``metadata.create_all``. When source is
    bind-mounted before Alembic runs, SQLModel can create this new table while
    the database remains stamped at 0042. Adoption is strictly limited to an
    empty table with the exact column contract; no durable row is rewritten or
    discarded.
    """

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Prevent a concurrent writer from invalidating the empty-table proof
        # while the exact model-created contract is inspected and normalized.
        bind.execute(sa.text(f'LOCK TABLE "{TABLE}" IN ACCESS EXCLUSIVE MODE'))
    inspector = _inspector()
    observed_columns = {
        item["name"]: item for item in inspector.get_columns(TABLE)
    }
    row_count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
    if set(observed_columns) != EXPECTED_COLUMNS or row_count != 0:
        raise RuntimeError(
            f"Existing {TABLE} table is not the exact empty model-created schema."
        )
    for name, expected in EXPECTED_COLUMN_SPECS.items():
        item = observed_columns[name]
        observed = (*_type_contract(item["type"]), bool(item["nullable"]))
        if observed != expected:
            raise RuntimeError(
                f"Existing {TABLE} table has an incompatible {name} column."
            )

    primary_key = inspector.get_pk_constraint(TABLE)
    if tuple(primary_key.get("constrained_columns") or ()) != ("id",):
        raise RuntimeError(f"Existing {TABLE} table has an incompatible primary key.")

    _validate_foreign_key_contracts(inspector)

    checks = _inspected_check_contracts(inspector)

    # A pre-created table must already carry the current result-identity and
    # CHECK contracts. This intentionally rejects intermediate or stale model
    # shapes instead of embedding compatibility for unpublished intermediate DDL.
    unique_constraints = inspector.get_unique_constraints(TABLE)
    unique_by_columns = {
        tuple(item.get("column_names") or ()): item.get("name")
        for item in unique_constraints
    }
    desired_unique = unique_by_columns.get(("generated_page_id", "result_hash"))
    if len(unique_constraints) != 1 or desired_unique is None:
        raise RuntimeError(
            f"Existing {TABLE} table lacks one exact result identity constraint."
        )
    _validate_check_contracts(checks)
    _validate_index_contracts(inspector)

    # Recheck immediately before the first possible DDL mutation. PostgreSQL
    # holds the ACCESS EXCLUSIVE lock above through this migration transaction;
    # the second proof also keeps non-PostgreSQL adoption fail closed.
    if bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() != 0:
        raise RuntimeError(f"Existing {TABLE} table is no longer empty.")

    existing_indexes = {item["name"] for item in _inspector().get_indexes(TABLE)}
    for name, (columns, unique) in DESIRED_INDEXES.items():
        if name not in existing_indexes:
            options: dict[str, Any] = {}
            if name == CURRENT_INDEX:
                options = {
                    "postgresql_where": sa.text(CURRENT_PREDICATE),
                    "sqlite_where": sa.text(CURRENT_PREDICATE),
                }
            op.create_index(name, TABLE, list(columns), unique=unique, **options)

    # Reinspect after normalization/creation rather than trusting DDL calls.
    normalized = _inspector()
    normalized_checks = _inspected_check_contracts(normalized)
    _validate_check_contracts(normalized_checks)
    _validate_index_contracts(normalized)


def _backfill_historical_rows() -> None:
    rows = _historical_rows()
    if not rows:
        return
    qa_result = sa.table(
        TABLE,
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
        sa.column("website_id", sa.Integer()),
        sa.column("site_plan_id", sa.Integer()),
        sa.column("planned_page_id", sa.Integer()),
        sa.column("generated_page_id", sa.Integer()),
        sa.column("latest_generated_page_revision_id", sa.Integer()),
        sa.column("content_hash", sa.String(length=64)),
        sa.column("source_hash", sa.String(length=64)),
        sa.column("page_composition_id", sa.Integer()),
        sa.column("composition_version", sa.Integer()),
        sa.column("composition_source_hash", sa.String(length=64)),
        sa.column("qa_algorithm_key", sa.String(length=120)),
        sa.column("qa_algorithm_version", sa.String(length=80)),
        sa.column("qa_ruleset_key", sa.String(length=120)),
        sa.column("qa_ruleset_version", sa.String(length=80)),
        sa.column("qa_ruleset_hash", sa.String(length=64)),
        sa.column("readiness_status", sa.String(length=32)),
        sa.column("passed_count", sa.Integer()),
        sa.column("warning_count", sa.Integer()),
        sa.column("failed_count", sa.Integer()),
        sa.column("check_payload", sa.JSON()),
        sa.column("evaluated_at", sa.DateTime()),
        sa.column("lifecycle_status", sa.String(length=32)),
        sa.column("supersedes_qa_result_id", sa.Integer()),
        sa.column("result_hash", sa.String(length=64)),
        sa.column("historical_payload", sa.JSON(none_as_null=True)),
    )
    op.bulk_insert(qa_result, rows)


def upgrade() -> None:
    required = set(BASE_TABLE_COLUMNS)
    existing = set(_inspector().get_table_names())
    missing = sorted(required - existing)
    if missing:
        raise RuntimeError(
            "Required QA identity tables are missing: " + ", ".join(missing)
        )
    for table, required_columns in BASE_TABLE_COLUMNS.items():
        observed = {
            item["name"] for item in _inspector().get_columns(table)
        }
        if not required_columns.issubset(observed):
            raise RuntimeError(
                f"Required QA identity columns are missing from {table}."
            )
    if TABLE in existing:
        _adopt_empty_model_created_table()
    else:
        _create_table()
        _create_indexes()
    _backfill_historical_rows()


def downgrade() -> None:
    if TABLE not in set(_inspector().get_table_names()):
        return
    bound_count = op.get_bind().execute(
        sa.text(
            f"SELECT COUNT(*) FROM {TABLE} "
            "WHERE lifecycle_status IN ('current','superseded')"
        )
    ).scalar_one()
    if bound_count:
        raise RuntimeError(
            "Downgrade blocked: durable current or superseded QA results exist."
        )
    op.drop_table(TABLE)
