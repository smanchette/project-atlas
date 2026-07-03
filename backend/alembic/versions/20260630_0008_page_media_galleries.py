"""Add page media overrides and gallery uniqueness.

Revision ID: 20260630_0008
Revises: 20260630_0007
"""

from alembic import op
import sqlalchemy as sa


revision = "20260630_0008"
down_revision = "20260630_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pageimageassignment") as batch_op:
        batch_op.add_column(sa.Column("override_focal_x", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("override_focal_y", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("override_alt_text", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "display_preset",
                sa.String(),
                nullable=False,
                server_default="hero_desktop",
            )
        )
        batch_op.drop_constraint("uq_page_image_role", type_="unique")
        batch_op.create_unique_constraint(
            "uq_page_image_role_media",
            ["generated_page_id", "image_metadata_id", "image_role"],
        )
        batch_op.create_check_constraint(
            "ck_pageimageassignment_override_focal_x_range",
            "override_focal_x IS NULL OR (override_focal_x >= 0 AND override_focal_x <= 1)",
        )
        batch_op.create_check_constraint(
            "ck_pageimageassignment_override_focal_y_range",
            "override_focal_y IS NULL OR (override_focal_y >= 0 AND override_focal_y <= 1)",
        )
        batch_op.create_index(
            "ix_pageimageassignment_display_preset",
            ["display_preset"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("pageimageassignment") as batch_op:
        batch_op.drop_index("ix_pageimageassignment_display_preset")
        batch_op.drop_constraint(
            "ck_pageimageassignment_override_focal_y_range",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_pageimageassignment_override_focal_x_range",
            type_="check",
        )
        batch_op.drop_constraint("uq_page_image_role_media", type_="unique")
        batch_op.create_unique_constraint(
            "uq_page_image_role",
            ["generated_page_id", "image_role"],
        )
        batch_op.drop_column("display_preset")
        batch_op.drop_column("override_alt_text")
        batch_op.drop_column("override_focal_y")
        batch_op.drop_column("override_focal_x")
