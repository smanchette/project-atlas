"""add knowledge blocks

Revision ID: 20260629_0003
Revises: 20260629_0002
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision = "20260629_0003"
down_revision = "20260629_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledgeblock",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("question", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("short_answer", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("long_answer", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("customer_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("confidence_level", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source_notes", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["service.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledgeblock_business_id"), "knowledgeblock", ["business_id"], unique=False)
    op.create_index(op.f("ix_knowledgeblock_category"), "knowledgeblock", ["category"], unique=False)
    op.create_index(op.f("ix_knowledgeblock_confidence_level"), "knowledgeblock", ["confidence_level"], unique=False)
    op.create_index(op.f("ix_knowledgeblock_customer_type"), "knowledgeblock", ["customer_type"], unique=False)
    op.create_index(op.f("ix_knowledgeblock_service_id"), "knowledgeblock", ["service_id"], unique=False)
    op.create_index(op.f("ix_knowledgeblock_slug"), "knowledgeblock", ["slug"], unique=True)
    op.create_index(op.f("ix_knowledgeblock_sort_order"), "knowledgeblock", ["sort_order"], unique=False)
    op.create_index(op.f("ix_knowledgeblock_status"), "knowledgeblock", ["status"], unique=False)
    op.create_index(op.f("ix_knowledgeblock_title"), "knowledgeblock", ["title"], unique=False)


def downgrade() -> None:
    op.drop_table("knowledgeblock")
