"""add structured generated page drafts

Revision ID: 20260629_0004
Revises: 20260629_0003
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision = "20260629_0004"
down_revision = "20260629_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generatedpage", sa.Column("draft_content", sa.JSON(), nullable=True))
    op.add_column(
        "generatedpage",
        sa.Column(
            "generation_status",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="not_generated",
        ),
    )
    op.add_column("generatedpage", sa.Column("generated_at", sa.DateTime(), nullable=True))
    op.create_index(
        op.f("ix_generatedpage_generation_status"),
        "generatedpage",
        ["generation_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_generatedpage_generation_status"), table_name="generatedpage")
    op.drop_column("generatedpage", "generated_at")
    op.drop_column("generatedpage", "generation_status")
    op.drop_column("generatedpage", "draft_content")
