"""Add Website-scoped Themes and governed active selection history.

Revision ID: 20260804_0039
Revises: 20260801_0038
"""

from alembic import op
import sqlalchemy as sa


revision = "20260804_0039"
down_revision = "20260801_0038"
branch_labels = None
depends_on = None


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


def _check_constraints(table: str) -> dict[str, str]:
    return {
        item["name"]: item.get("sqltext") or ""
        for item in sa.inspect(op.get_bind()).get_check_constraints(table)
        if item.get("name")
    }


def _canonical_check(expression: str) -> str:
    normalized = "".join(expression.lower().replace('"', "").split())
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1]
    return normalized


def _require_check_constraints(table: str, expected: dict[str, str]) -> None:
    existing = _check_constraints(table)
    for name, expression in expected.items():
        observed = existing.get(name)
        if observed is None or _canonical_check(observed) != _canonical_check(expression):
            raise RuntimeError(
                f"Existing {table} table is incompatible: required check constraint {name} differs."
            )


def _ensure_indexes(table: str, columns: tuple[str, ...]) -> None:
    existing = _indexes(table)
    for column in columns:
        name = f"ix_{table}_{column}"
        if name not in existing:
            op.create_index(name, table, [column])


def upgrade() -> None:
    if "theme" not in _tables():
        op.create_table(
            "theme",
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("brand_id", sa.Integer(), nullable=False),
            sa.Column("theme_key", sa.String(length=120), nullable=False),
            sa.Column("theme_name", sa.String(length=160), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("token_contract_version", sa.Integer(), nullable=False),
            sa.Column("design_tokens", sa.JSON(), nullable=False),
            sa.Column("token_hash_sha256", sa.String(length=64), nullable=False),
            sa.Column("description", sa.String(length=2000), nullable=True),
            sa.Column("lifecycle_status", sa.String(length=24), nullable=False),
            sa.Column("approval_status", sa.String(length=24), nullable=False),
            sa.Column("created_by", sa.String(length=160), nullable=False),
            sa.Column("provenance_type", sa.String(length=40), nullable=False),
            sa.Column("provenance_notes", sa.String(length=2000), nullable=False),
            sa.Column("approved_by", sa.String(length=160), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("retired_by", sa.String(length=160), nullable=True),
            sa.Column("retirement_rationale", sa.String(length=2000), nullable=True),
            sa.Column("retired_at", sa.DateTime(), nullable=True),
            sa.Column("replaces_theme_id", sa.Integer(), nullable=True),
            sa.CheckConstraint("version >= 1", name="ck_theme_version"),
            sa.CheckConstraint(
                "token_contract_version >= 1",
                name="ck_theme_token_contract_version",
            ),
            sa.CheckConstraint(
                "lifecycle_status IN ('draft','available','retired')",
                name="ck_theme_lifecycle_status",
            ),
            sa.CheckConstraint(
                "approval_status IN ('pending_review','approved','rejected')",
                name="ck_theme_approval_status",
            ),
            sa.CheckConstraint(
                "provenance_type IN ('operator_configured','company_original','licensed','third_party')",
                name="ck_theme_provenance_type",
            ),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
            sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
            sa.ForeignKeyConstraint(["replaces_theme_id"], ["theme.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "website_id",
                "theme_key",
                "version",
                name="uq_theme_website_key_version",
            ),
        )
    required_theme_columns = {
        "created_at",
        "updated_at",
        "id",
        "website_id",
        "business_id",
        "brand_id",
        "theme_key",
        "theme_name",
        "version",
        "token_contract_version",
        "design_tokens",
        "token_hash_sha256",
        "description",
        "lifecycle_status",
        "approval_status",
        "created_by",
        "provenance_type",
        "provenance_notes",
        "approved_by",
        "approved_at",
        "retired_by",
        "retirement_rationale",
        "retired_at",
        "replaces_theme_id",
    }
    if not required_theme_columns.issubset(_columns("theme")):
        raise RuntimeError("Existing theme table is incompatible.")
    _require_check_constraints(
        "theme",
        {
            "ck_theme_version": "version >= 1",
            "ck_theme_token_contract_version": "token_contract_version >= 1",
        },
    )
    _ensure_indexes(
        "theme",
        (
            "website_id",
            "business_id",
            "brand_id",
            "theme_key",
            "token_hash_sha256",
            "lifecycle_status",
            "approval_status",
            "provenance_type",
            "replaces_theme_id",
        ),
    )

    if "websitethemeselection" not in _tables():
        op.create_table(
            "websitethemeselection",
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("theme_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("selected_by", sa.String(length=160), nullable=False),
            sa.Column("rationale", sa.String(length=2000), nullable=False),
            sa.Column("selected_at", sa.DateTime(), nullable=False),
            sa.Column("replaced_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint("version >= 1", name="ck_websitethemeselection_version"),
            sa.CheckConstraint(
                "status IN ('active','replaced','retired')",
                name="ck_websitethemeselection_status",
            ),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.ForeignKeyConstraint(["theme_id"], ["theme.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "website_id",
                "version",
                name="uq_websitethemeselection_website_version",
            ),
        )
    required_selection_columns = {
        "created_at",
        "updated_at",
        "id",
        "website_id",
        "theme_id",
        "version",
        "status",
        "selected_by",
        "rationale",
        "selected_at",
        "replaced_at",
    }
    if not required_selection_columns.issubset(_columns("websitethemeselection")):
        raise RuntimeError("Existing websitethemeselection table is incompatible.")
    _require_check_constraints(
        "websitethemeselection",
        {"ck_websitethemeselection_version": "version >= 1"},
    )
    _ensure_indexes(
        "websitethemeselection",
        ("website_id", "theme_id", "status"),
    )
    if "uq_websitethemeselection_active_website" not in _indexes("websitethemeselection"):
        op.create_index(
            "uq_websitethemeselection_active_website",
            "websitethemeselection",
            ["website_id"],
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
            sqlite_where=sa.text("status = 'active'"),
        )


def downgrade() -> None:
    connection = op.get_bind()
    tables = _tables()
    if "websitethemeselection" in tables and connection.execute(
        sa.text("SELECT COUNT(*) FROM websitethemeselection")
    ).scalar_one():
        raise RuntimeError("Downgrade blocked: durable Website Theme selections exist.")
    if "theme" in tables and connection.execute(
        sa.text("SELECT COUNT(*) FROM theme")
    ).scalar_one():
        raise RuntimeError("Downgrade blocked: durable Theme records exist.")
    if "websitethemeselection" in tables:
        op.drop_table("websitethemeselection")
    if "theme" in tables:
        op.drop_table("theme")
