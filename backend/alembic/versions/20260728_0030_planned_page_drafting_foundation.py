"""Allow Website-owned non-service Generated Page drafts.

Revision ID: 20260728_0030
Revises: 20260728_0029
"""

from alembic import op
import sqlalchemy as sa


revision = "20260728_0030"
down_revision = "20260728_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"]: column
        for column in inspector.get_columns("generatedpage")
    }
    service_id = columns.get("service_id")
    if service_id is None:
        raise RuntimeError(
            "generatedpage.service_id is required before migration 20260728_0030."
        )
    if not service_id["nullable"]:
        with op.batch_alter_table("generatedpage") as batch:
            batch.alter_column(
                "service_id",
                existing_type=sa.Integer(),
                nullable=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    null_service_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM generatedpage WHERE service_id IS NULL")
    ).scalar_one()
    if null_service_count:
        raise RuntimeError(
            "Cannot downgrade while non-service Generated Page drafts exist."
        )
    with op.batch_alter_table("generatedpage") as batch:
        batch.alter_column(
            "service_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
