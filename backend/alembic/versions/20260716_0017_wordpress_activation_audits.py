"""Add guarded Metadata Bridge activation audits.

Revision ID: 20260716_0017
Revises: 20260714_0016
"""
from alembic import op
import sqlalchemy as sa

revision = "20260716_0017"
down_revision = "20260714_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "wordpressactivationaudit" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "wordpressactivationaudit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generated_page_id", sa.Integer(), sa.ForeignKey("generatedpage.id"), nullable=False),
        sa.Column("wordpress_post_id", sa.Integer(), nullable=False),
        sa.Column("installation_audit_id", sa.Integer(), sa.ForeignKey("wordpressdeploymentaudit.id"), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("operator", sa.String(200), nullable=False),
        sa.Column("confirmation_phrase_hash", sa.String(64), nullable=False),
        sa.Column("handle_fingerprint", sa.String(64), nullable=False),
        sa.Column("binding_hash", sa.String(64), nullable=False),
        sa.Column("atlas_version", sa.String(32), nullable=False),
        sa.Column("atlas_commit", sa.String(40), nullable=False),
        sa.Column("atlas_tag", sa.String(32), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("plugin_slug", sa.String(100), nullable=False),
        sa.Column("plugin_path", sa.String(255), nullable=False),
        sa.Column("plugin_version", sa.String(32), nullable=False),
        sa.Column("zip_sha256", sa.String(64), nullable=False),
        sa.Column("backup_evidence", sa.JSON(), nullable=False),
        sa.Column("browser_evidence_id", sa.String(100), nullable=False),
        sa.Column("browser_evidence_schema", sa.String(100), nullable=False),
        sa.Column("browser_evidence_schema_version", sa.Integer(), nullable=False),
        sa.Column("pre_snapshot", sa.JSON(), nullable=False),
        sa.Column("post_snapshot", sa.JSON()),
        sa.Column("gate_results", sa.JSON(), nullable=False),
        sa.Column("wordpress_write_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wordpress_write_scope", sa.JSON(), nullable=False),
        sa.Column("atlas_write_scope", sa.JSON(), nullable=False),
        sa.Column("transition_history", sa.JSON(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.String(2000)),
        sa.CheckConstraint("action_type = 'activate_metadata_bridge'", name="ck_wordpressactivationaudit_action"),
        sa.CheckConstraint("status IN ('pending','verified','verification_failed','failed')", name="ck_wordpressactivationaudit_status"),
        sa.UniqueConstraint("handle_fingerprint", name="uq_wordpressactivationaudit_handle_fingerprint"),
    )
    for name in (
        "generated_page_id", "wordpress_post_id", "installation_audit_id", "action_type",
        "status", "handle_fingerprint", "binding_hash", "attempted_at",
    ):
        op.create_index(f"ix_wordpressactivationaudit_{name}", "wordpressactivationaudit", [name])


def downgrade() -> None:
    if "wordpressactivationaudit" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("wordpressactivationaudit")
