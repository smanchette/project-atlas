"""Add QA remediation review fields and approval audit records.

Revision ID: 20260701_0010
Revises: 20260630_0009
"""

from alembic import op
import sqlalchemy as sa


revision = "20260701_0010"
down_revision = "20260630_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("generatedpage") as batch_op:
        batch_op.add_column(sa.Column("internal_notes", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("last_reviewed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_reviewed_by", sa.String(), nullable=True))

    op.create_table(
        "approvalaudit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generated_page_id", sa.Integer(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("qa_status_at_approval", sa.String(), nullable=False),
        sa.Column("qa_checked_at", sa.DateTime(), nullable=False),
        sa.Column("qa_result_snapshot", sa.JSON(), nullable=False),
        sa.Column("draft_hash_at_approval", sa.String(), nullable=False),
        sa.Column("page_status_before", sa.String(), nullable=False),
        sa.Column("page_status_after", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["generated_page_id"], ["generatedpage.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generated_page_id",
            "approved_at",
            "draft_hash_at_approval",
            name="uq_approvalaudit_page_time_hash",
        ),
    )
    op.create_index(
        "ix_approvalaudit_generated_page_id",
        "approvalaudit",
        ["generated_page_id"],
        unique=False,
    )
    op.create_index(
        "ix_approvalaudit_approved_at",
        "approvalaudit",
        ["approved_at"],
        unique=False,
    )
    op.create_index(
        "ix_approvalaudit_qa_status_at_approval",
        "approvalaudit",
        ["qa_status_at_approval"],
        unique=False,
    )
    op.create_index(
        "ix_approvalaudit_draft_hash_at_approval",
        "approvalaudit",
        ["draft_hash_at_approval"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_approvalaudit_draft_hash_at_approval", table_name="approvalaudit")
    op.drop_index("ix_approvalaudit_qa_status_at_approval", table_name="approvalaudit")
    op.drop_index("ix_approvalaudit_approved_at", table_name="approvalaudit")
    op.drop_index("ix_approvalaudit_generated_page_id", table_name="approvalaudit")
    op.drop_table("approvalaudit")

    with op.batch_alter_table("generatedpage") as batch_op:
        batch_op.drop_column("last_reviewed_by")
        batch_op.drop_column("last_reviewed_at")
        batch_op.drop_column("internal_notes")
