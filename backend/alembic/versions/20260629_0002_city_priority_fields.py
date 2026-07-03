"""add city priority fields

Revision ID: 20260629_0002
Revises: 20260629_0001
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision = "20260629_0002"
down_revision = "20260629_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("city", sa.Column("priority", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="Medium"))
    op.add_column("city", sa.Column("is_primary_market", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("city", sa.Column("notes", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f("ix_city_priority"), "city", ["priority"], unique=False)
    op.create_index(op.f("ix_city_is_primary_market"), "city", ["is_primary_market"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_city_is_primary_market"), table_name="city")
    op.drop_index(op.f("ix_city_priority"), table_name="city")
    op.drop_column("city", "notes")
    op.drop_column("city", "is_primary_market")
    op.drop_column("city", "priority")
