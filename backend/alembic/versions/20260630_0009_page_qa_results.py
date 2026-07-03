"""Add generated page QA readiness results.

Revision ID: 20260630_0009
Revises: 20260630_0008
"""

from alembic import op
import sqlalchemy as sa


revision = "20260630_0009"
down_revision = "20260630_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("generatedpage") as batch_op:
        batch_op.add_column(
            sa.Column(
                "qa_status",
                sa.String(),
                nullable=False,
                server_default="not_run",
            )
        )
        batch_op.add_column(sa.Column("qa_result", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("qa_checked_at", sa.DateTime(), nullable=True))
        batch_op.create_index(
            "ix_generatedpage_qa_status",
            ["qa_status"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("generatedpage") as batch_op:
        batch_op.drop_index("ix_generatedpage_qa_status")
        batch_op.drop_column("qa_checked_at")
        batch_op.drop_column("qa_result")
        batch_op.drop_column("qa_status")
