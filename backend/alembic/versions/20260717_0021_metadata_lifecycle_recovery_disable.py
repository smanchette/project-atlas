"""Add metadata lifecycle recovery-disable audit fields.

Revision ID: 20260717_0021
Revises: 20260716_0020
"""
from alembic import op
import sqlalchemy as sa

revision = "20260717_0021"
down_revision = "20260716_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table = "wordpressmetadatalifecycleaudit"
    if table not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns(table)}
    if "completion_mode" not in columns:
        op.add_column(
            table,
            sa.Column("completion_mode", sa.String(80), nullable=False, server_default="standard"),
        )
        op.create_index(
            "ix_wordpressmetadatalifecycleaudit_completion_mode",
            table,
            ["completion_mode"],
        )
    if "recovery_recommendation" not in columns:
        op.add_column(table, sa.Column("recovery_recommendation", sa.String(64)))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table = "wordpressmetadatalifecycleaudit"
    if table not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns(table)}
    if "recovery_recommendation" in columns:
        op.drop_column(table, "recovery_recommendation")
    if "completion_mode" in columns:
        indexes = {index["name"] for index in inspector.get_indexes(table)}
        if "ix_wordpressmetadatalifecycleaudit_completion_mode" in indexes:
            op.drop_index("ix_wordpressmetadatalifecycleaudit_completion_mode", table_name=table)
        op.drop_column(table, "completion_mode")
