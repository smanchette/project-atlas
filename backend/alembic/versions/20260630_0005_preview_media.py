"""add preview media assignments

Revision ID: 20260630_0005
Revises: 20260629_0004
Create Date: 2026-06-30
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision = "20260630_0005"
down_revision = "20260629_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("imagemetadata") as batch_op:
        batch_op.add_column(sa.Column("county_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("image_title", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column("reviewed_alt_text", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column("asset_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(
            sa.Column("image_role", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="support")
        )
        batch_op.add_column(
            sa.Column("review_status", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="pending")
        )
        batch_op.create_foreign_key("fk_imagemetadata_county_id", "county", ["county_id"], ["id"])
        batch_op.create_index(op.f("ix_imagemetadata_county_id"), ["county_id"], unique=False)
        batch_op.create_index(op.f("ix_imagemetadata_image_role"), ["image_role"], unique=False)
        batch_op.create_index(op.f("ix_imagemetadata_review_status"), ["review_status"], unique=False)

    op.create_table(
        "pageimageassignment",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generated_page_id", sa.Integer(), nullable=False),
        sa.Column("image_metadata_id", sa.Integer(), nullable=False),
        sa.Column("image_role", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["generated_page_id"], ["generatedpage.id"]),
        sa.ForeignKeyConstraint(["image_metadata_id"], ["imagemetadata.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generated_page_id", "image_role", name="uq_page_image_role"),
    )
    op.create_index(
        op.f("ix_pageimageassignment_generated_page_id"),
        "pageimageassignment",
        ["generated_page_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pageimageassignment_image_metadata_id"),
        "pageimageassignment",
        ["image_metadata_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pageimageassignment_image_role"),
        "pageimageassignment",
        ["image_role"],
        unique=False,
    )
    op.create_index(op.f("ix_pageimageassignment_status"), "pageimageassignment", ["status"], unique=False)


def downgrade() -> None:
    op.drop_table("pageimageassignment")
    with op.batch_alter_table("imagemetadata") as batch_op:
        batch_op.drop_index(op.f("ix_imagemetadata_review_status"))
        batch_op.drop_index(op.f("ix_imagemetadata_image_role"))
        batch_op.drop_index(op.f("ix_imagemetadata_county_id"))
        batch_op.drop_constraint("fk_imagemetadata_county_id", type_="foreignkey")
        batch_op.drop_column("review_status")
        batch_op.drop_column("image_role")
        batch_op.drop_column("asset_url")
        batch_op.drop_column("reviewed_alt_text")
        batch_op.drop_column("image_title")
        batch_op.drop_column("county_id")
