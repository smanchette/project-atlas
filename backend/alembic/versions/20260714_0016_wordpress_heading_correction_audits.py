"""Add dedicated guarded WordPress heading-correction audits.

Revision ID: 20260714_0016
Revises: 20260712_0015
"""
from alembic import op
import sqlalchemy as sa

revision = "20260714_0016"
down_revision = "20260712_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "wordpressheadingcorrectionaudit" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "wordpressheadingcorrectionaudit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generated_page_id", sa.Integer(), sa.ForeignKey("generatedpage.id"), nullable=False),
        sa.Column("wordpress_post_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("wordpress_site_url", sa.String(500), nullable=False),
        sa.Column("current_body_hash", sa.String(64), nullable=False),
        sa.Column("proposed_body_hash", sa.String(64), nullable=False),
        sa.Column("token_fingerprint", sa.String(64), nullable=False),
        sa.Column("backup_identities", sa.JSON(), nullable=False),
        sa.Column("release_identity", sa.JSON(), nullable=False),
        sa.Column("pre_snapshot", sa.JSON(), nullable=False),
        sa.Column("post_snapshot", sa.JSON()),
        sa.Column("gate_results", sa.JSON(), nullable=False),
        sa.Column("wordpress_write_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("error_message", sa.String(2000)),
        sa.CheckConstraint("action_type = 'correct_orlando_duplicate_h1'", name="ck_wordpressheadingcorrectionaudit_action"),
        sa.CheckConstraint("status IN ('pending','corrected','verified','reconciliation_required','failed')", name="ck_wordpressheadingcorrectionaudit_status"),
        sa.UniqueConstraint("token_fingerprint", name="uq_wordpressheadingcorrectionaudit_token_fingerprint"),
    )
    for name in (
        "generated_page_id", "wordpress_post_id", "action_type", "status",
        "current_body_hash", "proposed_body_hash", "token_fingerprint", "attempted_at",
    ):
        op.create_index(
            f"ix_wordpressheadingcorrectionaudit_{name}",
            "wordpressheadingcorrectionaudit",
            [name],
        )


def downgrade() -> None:
    if "wordpressheadingcorrectionaudit" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("wordpressheadingcorrectionaudit")
