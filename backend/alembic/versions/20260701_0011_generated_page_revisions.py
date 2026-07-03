"""Add generated page manual edit revisions.

Revision ID: 20260701_0011
Revises: 20260701_0010
"""

from alembic import op
import sqlalchemy as sa


revision = "20260701_0011"
down_revision = "20260701_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generatedpagerevision",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generated_page_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("draft_hash_before", sa.String(), nullable=False),
        sa.Column("draft_hash_after", sa.String(), nullable=False),
        sa.Column("draft_content_before", sa.JSON(), nullable=False),
        sa.Column("draft_content_after", sa.JSON(), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["generated_page_id"], ["generatedpage.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generated_page_id",
            "created_at",
            "draft_hash_after",
            name="uq_pagerevision_page_time_hash",
        ),
    )
    op.create_index(
        "ix_generatedpagerevision_generated_page_id",
        "generatedpagerevision",
        ["generated_page_id"],
        unique=False,
    )
    op.create_index(
        "ix_generatedpagerevision_created_at",
        "generatedpagerevision",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_generatedpagerevision_draft_hash_after",
        "generatedpagerevision",
        ["draft_hash_after"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_generatedpagerevision_draft_hash_after",
        table_name="generatedpagerevision",
    )
    op.drop_index(
        "ix_generatedpagerevision_created_at",
        table_name="generatedpagerevision",
    )
    op.drop_index(
        "ix_generatedpagerevision_generated_page_id",
        table_name="generatedpagerevision",
    )
    op.drop_table("generatedpagerevision")
