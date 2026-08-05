"""Add durable provenance to navigation and internal-link decisions.

Revision ID: 20260805_0040
Revises: 20260804_0039
"""

from alembic import op
import sqlalchemy as sa


revision = "20260805_0040"
down_revision = "20260804_0039"
branch_labels = None
depends_on = None


TABLES = (
    "navigationset",
    "navigationitem",
    "internallinkintent",
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_indexes(table)
        if item.get("name")
    }


def _checks(table: str) -> dict[str, str]:
    return {
        item["name"]: item.get("sqltext") or ""
        for item in sa.inspect(op.get_bind()).get_check_constraints(table)
        if item.get("name")
    }


def _canonical(expression: str) -> str:
    normalized = " ".join(expression.lower().replace('"', "").split())
    if normalized.startswith("check "):
        normalized = normalized[6:].strip()

    def strip_outer(value: str) -> str:
        while value.startswith("(") and value.endswith(")"):
            depth = 0
            closes_at_end = False
            for index, character in enumerate(value):
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth == 0:
                        closes_at_end = index == len(value) - 1
                        break
            if not closes_at_end:
                break
            value = value[1:-1].strip()
        return value

    def split_top_level(value: str, operator: str) -> list[str]:
        token = f" {operator} "
        depth = 0
        start = 0
        index = 0
        parts: list[str] = []
        while index < len(value):
            character = value[index]
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif depth == 0 and value.startswith(token, index):
                parts.append(value[start:index].strip())
                index += len(token)
                start = index
                continue
            index += 1
        if parts:
            parts.append(value[start:].strip())
        return parts or [value]

    def canonical_boolean(value: str) -> str:
        value = strip_outer(value.strip())
        for operator in ("or", "and"):
            parts = split_top_level(value, operator)
            if len(parts) > 1:
                return (
                    f"{operator}("
                    + ",".join(canonical_boolean(part) for part in parts)
                    + ")"
                )
        return "".join(strip_outer(value).split())

    return canonical_boolean(normalized)


def _constraint_name(table: str) -> str:
    return f"ck_{table}_decision_provenance"


def _constraint_expression() -> str:
    return (
        "(decision_version IS NULL AND decided_by IS NULL AND rationale IS NULL "
        "AND decided_at IS NULL AND source_suggestion_key IS NULL) "
        "OR (decision_version IS NOT NULL AND decision_version >= 1 "
        "AND decided_by IS NOT NULL AND rationale IS NOT NULL "
        "AND decided_at IS NOT NULL)"
    )


def _add_missing_columns(table: str) -> None:
    existing = _columns(table)
    additions = {
        "rationale": sa.Column("rationale", sa.String(), nullable=True),
        "decided_by": sa.Column("decided_by", sa.String(), nullable=True),
        "decision_version": sa.Column("decision_version", sa.Integer(), nullable=True),
        "decided_at": sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        "source_suggestion_key": sa.Column(
            "source_suggestion_key",
            sa.String(length=200),
            nullable=True,
        ),
    }
    missing = [name for name in additions if name not in existing]
    if missing:
        with op.batch_alter_table(table) as batch_op:
            for name in missing:
                batch_op.add_column(additions[name])
    required = set(additions)
    if not required.issubset(_columns(table)):
        raise RuntimeError(f"Existing {table} table is incompatible.")


def _ensure_constraint(table: str) -> None:
    name = _constraint_name(table)
    expression = _constraint_expression()
    existing = _checks(table)
    if name not in existing:
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_check_constraint(name, expression)
        existing = _checks(table)
    observed = existing.get(name)
    if observed is None or _canonical(observed) != _canonical(expression):
        raise RuntimeError(
            f"Existing {table} table is incompatible: required decision provenance "
            f"constraint differs (observed={_canonical(observed or '')!r}, "
            f"expected={_canonical(expression)!r})."
        )


def upgrade() -> None:
    existing_tables = _tables()
    for table in TABLES:
        if table not in existing_tables:
            raise RuntimeError(
                f"Required {table} table is missing; apply migration 20260730_0031 first."
            )
        _add_missing_columns(table)
        _ensure_constraint(table)
        index_name = f"ix_{table}_decided_at"
        if index_name not in _indexes(table):
            op.create_index(index_name, table, ["decided_at"])


def downgrade() -> None:
    bind = op.get_bind()
    existing_tables = _tables()
    for table in TABLES:
        if table not in existing_tables:
            continue
        columns = _columns(table)
        provenance_columns = {
            "rationale",
            "decided_by",
            "decision_version",
            "decided_at",
            "source_suggestion_key",
        }
        if provenance_columns.issubset(columns):
            durable_count = bind.execute(
                sa.text(
                    f"SELECT COUNT(*) FROM {table} WHERE "
                    "rationale IS NOT NULL OR decided_by IS NOT NULL OR "
                    "decision_version IS NOT NULL OR decided_at IS NOT NULL OR "
                    "source_suggestion_key IS NOT NULL"
                )
            ).scalar_one()
            if durable_count:
                raise RuntimeError(
                    f"Downgrade blocked: durable decision provenance exists in {table}."
                )

    for table in reversed(TABLES):
        if table not in existing_tables:
            continue
        constraint_name = _constraint_name(table)
        with op.batch_alter_table(table) as batch_op:
            if constraint_name in _checks(table):
                batch_op.drop_constraint(constraint_name, type_="check")
            for column in (
                "source_suggestion_key",
                "decided_at",
                "decision_version",
                "decided_by",
                "rationale",
            ):
                if column in _columns(table):
                    batch_op.drop_column(column)
