"""Add governed Brand Assets and Website Identity asset selections.

Revision ID: 20260801_0038
Revises: 20260801_0037
"""

from alembic import op
import sqlalchemy as sa


revision = "20260801_0038"
down_revision = "20260801_0037"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table) if item.get("name")}


def _ensure_indexes(table: str, columns: tuple[str, ...]) -> None:
    existing = _indexes(table)
    for column in columns:
        name = f"ix_{table}_{column}"
        if name not in existing:
            op.create_index(name, table, [column])


def upgrade() -> None:
    if "brandasset" not in _tables():
        op.create_table(
            "brandasset",
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("brand_id", sa.Integer(), nullable=False),
            sa.Column("asset_key", sa.String(length=120), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("asset_type", sa.String(), nullable=False),
            sa.Column("variant_key", sa.String(length=80), nullable=False),
            sa.Column("purpose", sa.String(), nullable=False),
            sa.Column("approved_usage", sa.JSON(), nullable=False),
            sa.Column("restrictions", sa.JSON(), nullable=False),
            sa.Column("accessibility_description", sa.String(), nullable=False),
            sa.Column("original_filename", sa.String(), nullable=False),
            sa.Column("stored_filename", sa.String(), nullable=False),
            sa.Column("asset_url", sa.String(), nullable=False),
            sa.Column("optimized_url", sa.String(), nullable=True),
            sa.Column("thumbnail_url", sa.String(), nullable=True),
            sa.Column("mime_type", sa.String(), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
            sa.Column("provenance_type", sa.String(), nullable=False),
            sa.Column("provenance_notes", sa.String(), nullable=True),
            sa.Column("rights_status", sa.String(), nullable=False),
            sa.Column("rights_holder", sa.String(), nullable=True),
            sa.Column("rights_notes", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("approved_by", sa.String(), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("retired_by", sa.String(), nullable=True),
            sa.Column("retirement_rationale", sa.String(), nullable=True),
            sa.Column("retired_at", sa.DateTime(), nullable=True),
            sa.Column("replaces_brand_asset_id", sa.Integer(), nullable=True),
            sa.CheckConstraint("version >= 1", name="ck_brandasset_version"),
            sa.CheckConstraint("file_size >= 1", name="ck_brandasset_file_size"),
            sa.CheckConstraint("width >= 1", name="ck_brandasset_width"),
            sa.CheckConstraint("height >= 1", name="ck_brandasset_height"),
            sa.CheckConstraint(
                "asset_type IN ('primary_logo','alternate_logo','brand_mark','favicon','browser_icon','apple_touch_icon','open_graph_image')",
                name="ck_brandasset_type",
            ),
            sa.CheckConstraint(
                "status IN ('draft','pending_review','approved','rejected','retired')",
                name="ck_brandasset_status",
            ),
            sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
            sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
            sa.ForeignKeyConstraint(["replaces_brand_asset_id"], ["brandasset.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("brand_id", "asset_key", "version", name="uq_brandasset_brand_key_version"),
        )
    existing_asset_columns = _columns("brandasset")
    for column_name in ("retired_by", "retirement_rationale", "retired_at"):
        if column_name not in existing_asset_columns:
            column_type = sa.DateTime() if column_name == "retired_at" else sa.String()
            op.add_column("brandasset", sa.Column(column_name, column_type, nullable=True))
    required_asset_columns = {
        "created_at", "updated_at", "id", "business_id", "brand_id", "asset_key", "version",
        "asset_type", "variant_key", "purpose", "approved_usage", "restrictions",
        "accessibility_description", "original_filename", "stored_filename", "asset_url",
        "optimized_url", "thumbnail_url", "mime_type", "file_size", "width", "height",
        "checksum_sha256", "provenance_type", "provenance_notes", "rights_status", "rights_holder",
        "rights_notes", "status", "created_by", "approved_by", "approved_at", "retired_by",
        "retirement_rationale", "retired_at", "replaces_brand_asset_id",
    }
    if not required_asset_columns.issubset(_columns("brandasset")):
        raise RuntimeError("Existing brandasset table is incompatible.")
    _ensure_indexes(
        "brandasset",
        ("business_id", "brand_id", "asset_key", "asset_type", "checksum_sha256", "status", "replaces_brand_asset_id"),
    )

    if "websiteidentityassetassignment" not in _tables():
        op.create_table(
            "websiteidentityassetassignment",
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_identity_id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("brand_id", sa.Integer(), nullable=False),
            sa.Column("brand_asset_id", sa.Integer(), nullable=False),
            sa.Column("slot", sa.String(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("assigned_by", sa.String(), nullable=False),
            sa.Column("rationale", sa.String(), nullable=True),
            sa.Column("assigned_at", sa.DateTime(), nullable=False),
            sa.Column("replaced_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint("version >= 1", name="ck_identityassetassignment_version"),
            sa.CheckConstraint(
                "slot IN ('header_logo','footer_logo','favicon','browser_icon','apple_touch_icon','open_graph_image')",
                name="ck_identityassetassignment_slot",
            ),
            sa.CheckConstraint(
                "status IN ('active','replaced','retired')",
                name="ck_identityassetassignment_status",
            ),
            sa.ForeignKeyConstraint(["website_identity_id"], ["websiteidentity.id"]),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
            sa.ForeignKeyConstraint(["brand_asset_id"], ["brandasset.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "website_identity_id", "slot", "version",
                name="uq_identityassetassignment_identity_slot_version",
            ),
        )
    required_assignment_columns = {
        "created_at", "updated_at", "id", "website_identity_id", "website_id", "brand_id",
        "brand_asset_id", "slot", "version", "status", "assigned_by", "rationale",
        "assigned_at", "replaced_at",
    }
    if not required_assignment_columns.issubset(_columns("websiteidentityassetassignment")):
        raise RuntimeError("Existing websiteidentityassetassignment table is incompatible.")
    _ensure_indexes(
        "websiteidentityassetassignment",
        ("website_identity_id", "website_id", "brand_id", "brand_asset_id", "slot", "status"),
    )
    if "uq_identityassetassignment_active_slot" not in _indexes("websiteidentityassetassignment"):
        op.create_index(
            "uq_identityassetassignment_active_slot",
            "websiteidentityassetassignment",
            ["website_identity_id", "slot"],
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
            sqlite_where=sa.text("status = 'active'"),
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT COUNT(*) FROM websiteidentityassetassignment")).scalar_one():
        raise RuntimeError("Downgrade blocked: durable Website Identity asset selections exist.")
    if connection.execute(sa.text("SELECT COUNT(*) FROM brandasset")).scalar_one():
        raise RuntimeError("Downgrade blocked: durable Brand Assets exist.")
    op.drop_table("websiteidentityassetassignment")
    op.drop_table("brandasset")
