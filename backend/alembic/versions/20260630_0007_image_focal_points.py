"""Add normalized image focal points.

Revision ID: 20260630_0007
Revises: 20260630_0006
"""

from alembic import op
import sqlalchemy as sa


revision = "20260630_0007"
down_revision = "20260630_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("imagemetadata") as batch_op:
        batch_op.add_column(
            sa.Column("focal_x", sa.Float(), nullable=False, server_default=sa.text("0.5"))
        )
        batch_op.add_column(
            sa.Column("focal_y", sa.Float(), nullable=False, server_default=sa.text("0.5"))
        )
        batch_op.create_check_constraint(
            "ck_imagemetadata_focal_x_range",
            "focal_x >= 0 AND focal_x <= 1",
        )
        batch_op.create_check_constraint(
            "ck_imagemetadata_focal_y_range",
            "focal_y >= 0 AND focal_y <= 1",
        )


def downgrade() -> None:
    with op.batch_alter_table("imagemetadata") as batch_op:
        batch_op.drop_constraint("ck_imagemetadata_focal_y_range", type_="check")
        batch_op.drop_constraint("ck_imagemetadata_focal_x_range", type_="check")
        batch_op.drop_column("focal_y")
        batch_op.drop_column("focal_x")
