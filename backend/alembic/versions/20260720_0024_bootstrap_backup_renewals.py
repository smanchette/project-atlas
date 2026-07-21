"""Add immutable bootstrap backup-renewal history.

Revision ID: 20260720_0024
Revises: 20260719_0023
"""
from alembic import op
import sqlalchemy as sa

revision = "20260720_0024"
down_revision = "20260719_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "wordpressbootstrapestablishmentaudit"
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
    if "backup_renewals" not in columns:
        op.add_column(table, sa.Column("backup_renewals", sa.JSON(), nullable=False, server_default="[]"))
    if "active_backup_evidence" not in columns:
        op.add_column(table, sa.Column("active_backup_evidence", sa.JSON(), nullable=True))


def downgrade() -> None:
    table = "wordpressbootstrapestablishmentaudit"
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
    if "active_backup_evidence" in columns:
        op.drop_column(table, "active_backup_evidence")
    if "backup_renewals" in columns:
        op.drop_column(table, "backup_renewals")
