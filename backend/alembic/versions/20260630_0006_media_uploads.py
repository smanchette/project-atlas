"""Add managed media upload metadata.

Revision ID: 20260630_0006
Revises: 20260630_0005
"""

from alembic import op
import sqlalchemy as sa


revision = "20260630_0006"
down_revision = "20260630_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("imagemetadata") as batch_op:
        batch_op.add_column(sa.Column("thumbnail_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("optimized_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("original_filename", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("stored_filename", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("notes", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("imagemetadata") as batch_op:
        batch_op.drop_column("notes")
        batch_op.drop_column("stored_filename")
        batch_op.drop_column("original_filename")
        batch_op.drop_column("optimized_url")
        batch_op.drop_column("thumbnail_url")
