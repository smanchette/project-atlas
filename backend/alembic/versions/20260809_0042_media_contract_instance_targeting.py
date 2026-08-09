"""Add exact semantic-component instance targeting to page-media contracts.

Revision ID: 20260809_0042
Revises: 20260807_0041
"""

from alembic import op
import re
import sqlalchemy as sa


revision = "20260809_0042"
down_revision = "20260807_0041"
branch_labels = None
depends_on = None


TABLE = "plannedpagemediarequirement"
COLUMN = "target_component_instance_key"
CHECK = "ck_plannedpagemediarequirement_v2_target"
COLUMN_INDEX = "ix_plannedpagemediarequirement_target_component_instance_key"
ACTIVE_TARGET_INDEX = "uq_plannedpagemediarequirement_active_target"
V2_COMPLETENESS = (
    "contract_version < 2 OR "
    "(target_component_instance_key IS NOT NULL "
    "AND length(trim(target_component_instance_key)) > 0)"
)
ACTIVE_TARGET_PREDICATE = (
    "lifecycle_status = 'active' AND target_component_instance_key IS NOT NULL"
)


def _inspector():
    return sa.inspect(op.get_bind())


def _columns() -> dict[str, dict]:
    return {item["name"]: item for item in _inspector().get_columns(TABLE)}


def _checks() -> dict[str, str]:
    return {
        item["name"]: item.get("sqltext") or ""
        for item in _inspector().get_check_constraints(TABLE)
        if item.get("name")
    }


def _indexes() -> dict[str, dict]:
    return {
        item["name"]: item
        for item in _inspector().get_indexes(TABLE)
        if item.get("name")
    }


def _canonical(expression: str) -> str:
    value = " ".join(
        expression.lower().replace('"', "").replace("`", "").split()
    )
    if value.startswith("check "):
        value = value[6:].strip()
    value = re.sub(
        r"::(?:character\s+varying|varchar|text|integer|bigint)",
        "",
        value,
    )
    value = re.sub(
        r"(?<![a-z0-9_])\(\s*([a-z_][a-z0-9_]*)\s*\)",
        r"\1",
        value,
    )
    for pattern in (
        r"trim\s*\(\s*both\s+from\s+\(\s*([a-z_][a-z0-9_]*)\s*\)\s*\)",
        r"trim\s*\(\s*both\s+from\s+([a-z_][a-z0-9_]*)\s*\)",
        r"btrim\s*\(\s*\(\s*([a-z_][a-z0-9_]*)\s*\)\s*\)",
        r"btrim\s*\(\s*([a-z_][a-z0-9_]*)\s*\)",
    ):
        value = re.sub(pattern, r"trim(\1)", value)

    def strip_outer(item: str) -> str:
        item = item.strip()
        while item.startswith("(") and item.endswith(")"):
            depth = 0
            closes_at_end = False
            for index, character in enumerate(item):
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth == 0:
                        closes_at_end = index == len(item) - 1
                        break
            if not closes_at_end:
                break
            item = item[1:-1].strip()
        return item

    def split_top_level(item: str, operator: str) -> list[str]:
        token = f" {operator} "
        depth = 0
        start = 0
        index = 0
        parts: list[str] = []
        while index < len(item):
            character = item[index]
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif depth == 0 and item.startswith(token, index):
                parts.append(item[start:index].strip())
                index += len(token)
                start = index
                continue
            index += 1
        if parts:
            parts.append(item[start:].strip())
        return parts or [item]

    def canonical_boolean(item: str) -> str:
        item = strip_outer(item)
        for operator in ("or", "and"):
            parts = split_top_level(item, operator)
            if len(parts) > 1:
                return (
                    f"{operator}("
                    + ",".join(canonical_boolean(part) for part in parts)
                    + ")"
                )
        return "".join(strip_outer(item).split())

    return canonical_boolean(value)


def _index_predicate(index: dict) -> str:
    dialect_options = index.get("dialect_options") or {}
    for key in ("postgresql_where", "sqlite_where"):
        value = dialect_options.get(key)
        if value is not None:
            return str(value)
    return ""


def _validate_column() -> None:
    column = _columns().get(COLUMN)
    if column is None or not column.get("nullable", False):
        raise RuntimeError(
            "Existing plannedpagemediarequirement target column is incompatible."
        )
    column_type = column.get("type")
    if not isinstance(column_type, sa.String) or column_type.length != 200:
        raise RuntimeError(
            "Existing plannedpagemediarequirement target column is incompatible."
        )


def _ensure_check() -> None:
    checks = _checks()
    if CHECK not in checks:
        with op.batch_alter_table(TABLE) as batch_op:
            batch_op.create_check_constraint(CHECK, V2_COMPLETENESS)
        checks = _checks()
    actual = _canonical(checks.get(CHECK, ""))
    expected = _canonical(V2_COMPLETENESS)
    if actual != expected:
        raise RuntimeError(
            "Existing plannedpagemediarequirement V2 target check is incompatible: "
            f"expected {expected!r}, observed {actual!r}; "
            f"raw {checks.get(CHECK, '')!r}."
        )


def _ensure_indexes() -> None:
    indexes = _indexes()
    if COLUMN_INDEX not in indexes:
        op.create_index(COLUMN_INDEX, TABLE, [COLUMN])
    column_index = _indexes().get(COLUMN_INDEX)
    if (
        column_index is None
        or bool(column_index.get("unique"))
        or tuple(column_index.get("column_names") or ()) != (COLUMN,)
        or _canonical(_index_predicate(column_index))
    ):
        raise RuntimeError(
            "Existing plannedpagemediarequirement target column index is "
            "incompatible."
        )
    if ACTIVE_TARGET_INDEX not in _indexes():
        op.create_index(
            ACTIVE_TARGET_INDEX,
            TABLE,
            ["planned_page_id", COLUMN],
            unique=True,
            postgresql_where=sa.text(ACTIVE_TARGET_PREDICATE),
            sqlite_where=sa.text(ACTIVE_TARGET_PREDICATE),
        )
    active = _indexes().get(ACTIVE_TARGET_INDEX)
    if (
        active is None
        or not active.get("unique")
        or tuple(active.get("column_names") or ())
        != ("planned_page_id", COLUMN)
        or _canonical(_index_predicate(active))
        != _canonical(ACTIVE_TARGET_PREDICATE)
    ):
        raise RuntimeError(
            "Existing plannedpagemediarequirement active target index is incompatible."
        )


def upgrade() -> None:
    if TABLE not in set(_inspector().get_table_names()):
        raise RuntimeError(
            "Required plannedpagemediarequirement table is missing; "
            "apply migration 20260807_0041 first."
        )
    if COLUMN not in _columns():
        with op.batch_alter_table(TABLE) as batch_op:
            batch_op.add_column(sa.Column(COLUMN, sa.String(length=200), nullable=True))
    _validate_column()
    _ensure_check()
    _ensure_indexes()


def downgrade() -> None:
    if TABLE not in set(_inspector().get_table_names()):
        return
    if COLUMN not in _columns():
        return
    durable_count = op.get_bind().execute(
        sa.text(
            f"SELECT COUNT(*) FROM {TABLE} "
            f"WHERE {COLUMN} IS NOT NULL OR contract_version >= 2"
        )
    ).scalar_one()
    if durable_count:
        raise RuntimeError(
            "Downgrade blocked: durable exact-instance media contracts exist."
        )

    indexes = _indexes()
    for name in (ACTIVE_TARGET_INDEX, COLUMN_INDEX):
        if name in indexes:
            op.drop_index(name, table_name=TABLE)
    if CHECK in _checks():
        with op.batch_alter_table(TABLE) as batch_op:
            batch_op.drop_constraint(CHECK, type_="check")
    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.drop_column(COLUMN)
