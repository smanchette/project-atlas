"""Add controlled WordPress publish audits.

Revision ID: 20260711_0013
Revises: 20260705_0012
"""
from alembic import op
import sqlalchemy as sa

revision = "20260711_0013"
down_revision = "20260705_0012"
branch_labels = None
depends_on = None

def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "wordpresspublishaudit" not in inspector.get_table_names():
        op.create_table(
            "wordpresspublishaudit",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("generated_page_id", sa.Integer(), sa.ForeignKey("generatedpage.id"), nullable=False),
            sa.Column("wordpress_post_id", sa.Integer(), nullable=False),
            sa.Column("wordpress_site_url", sa.String(), nullable=False),
            sa.Column("attempted_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("pre_publish_wordpress_status", sa.String(), nullable=True),
            sa.Column("returned_wordpress_status", sa.String(), nullable=True),
            sa.Column("returned_wordpress_url", sa.String(), nullable=True),
            sa.Column("current_draft_payload_hash", sa.String(), nullable=False),
            sa.Column("latest_update_audit_id", sa.Integer(), sa.ForeignKey("wordpressdraftaudit.id"), nullable=True),
            sa.Column("latest_update_audit_hash", sa.String(), nullable=False),
            sa.Column("publish_payload_hash", sa.String(), nullable=False),
            sa.Column("gate_results", sa.JSON(), nullable=False),
            sa.Column("backup_file_name", sa.String(), nullable=False),
            sa.Column("error_message", sa.String(), nullable=True),
            sa.UniqueConstraint("generated_page_id", "attempted_at", "publish_payload_hash", name="uq_wordpresspublishaudit_page_time_hash"),
        )
        for column in ("generated_page_id", "wordpress_post_id", "attempted_at", "status", "current_draft_payload_hash", "publish_payload_hash"):
            op.create_index(f"ix_wordpresspublishaudit_{column}", "wordpresspublishaudit", [column])

def downgrade() -> None:
    op.drop_table("wordpresspublishaudit")
