"""Add constrained WordPress deployment authorization and transition audits.

Revision ID: 20260712_0015
Revises: 20260712_0014
"""
from alembic import op
import sqlalchemy as sa

revision = "20260712_0015"
down_revision = "20260712_0014"
branch_labels = None
depends_on = None

STATES = "'installation_authorized','awaiting_manual_installation','manual_installation_reported','verification_pending','verified','verification_failed','reconciliation_required','failed'"


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "wordpressdeploymentaudit" not in tables:
        op.create_table(
            "wordpressdeploymentaudit",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("generated_page_id", sa.Integer(), sa.ForeignKey("generatedpage.id"), nullable=False),
            sa.Column("wordpress_post_id", sa.Integer(), nullable=False),
            sa.Column("action_type", sa.String(64), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("operator", sa.String(200), nullable=False),
            sa.Column("shawn_approved_at", sa.DateTime(), nullable=False),
            sa.Column("confirmation_phrase_hash", sa.String(64), nullable=False),
            sa.Column("atlas_version", sa.String(32), nullable=False),
            sa.Column("atlas_commit", sa.String(40), nullable=False),
            sa.Column("atlas_tag", sa.String(32), nullable=False),
            sa.Column("plugin_version", sa.String(32), nullable=False),
            sa.Column("plugin_slug", sa.String(100), nullable=False),
            sa.Column("plugin_path", sa.String(255), nullable=False),
            sa.Column("zip_file_name", sa.String(255), nullable=False),
            sa.Column("zip_sha256", sa.String(64), nullable=False),
            sa.Column("plugin_source_sha256", sa.String(64), nullable=False),
            sa.Column("installation_transport", sa.String(64), nullable=False),
            sa.Column("backup_reference", sa.String(255), nullable=False),
            sa.Column("backup_completed_at", sa.DateTime(), nullable=False),
            sa.Column("backup_deadline", sa.DateTime(), nullable=False),
            sa.Column("authorization_jti", sa.String(64), nullable=False),
            sa.Column("deployment_key", sa.String(64), nullable=False),
            sa.Column("backup_evidence", sa.JSON(), nullable=False),
            sa.Column("pre_snapshot", sa.JSON(), nullable=False),
            sa.Column("post_snapshot", sa.JSON()),
            sa.Column("evidence_summary", sa.JSON(), nullable=False),
            sa.Column("evidence_directory", sa.String(500), nullable=False),
            sa.Column("attempted_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime()),
            sa.Column("error_code", sa.String(64)),
            sa.Column("error_message", sa.String(2000)),
            sa.Column("partial_failure_details", sa.Text()),
            sa.CheckConstraint("action_type = 'install_metadata_bridge'", name="ck_wordpressdeploymentaudit_action"),
            sa.CheckConstraint(f"status IN ({STATES})", name="ck_wordpressdeploymentaudit_status"),
            sa.UniqueConstraint("deployment_key", name="uq_wordpressdeploymentaudit_deployment_key"),
            sa.UniqueConstraint("authorization_jti", name="uq_wordpressdeploymentaudit_authorization_jti"),
        )
        for name in ("generated_page_id", "wordpress_post_id", "action_type", "status", "backup_reference", "backup_deadline", "authorization_jti", "deployment_key", "attempted_at"):
            op.create_index(f"ix_wordpressdeploymentaudit_{name}", "wordpressdeploymentaudit", [name])
    if "wordpressdeploymentnonce" not in tables:
        op.create_table(
            "wordpressdeploymentnonce",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("jti", sa.String(64), nullable=False),
            sa.Column("token_fingerprint", sa.String(64), nullable=False),
            sa.Column("action_type", sa.String(64), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=False),
            sa.Column("audit_id", sa.Integer(), sa.ForeignKey("wordpressdeploymentaudit.id")),
            sa.UniqueConstraint("jti", name="uq_wordpressdeploymentnonce_jti"),
            sa.UniqueConstraint("token_fingerprint", name="uq_wordpressdeploymentnonce_token_fingerprint"),
        )
        for name in ("jti", "action_type", "consumed_at", "audit_id"):
            op.create_index(f"ix_wordpressdeploymentnonce_{name}", "wordpressdeploymentnonce", [name])
    if "wordpressdeploymenttransition" not in tables:
        op.create_table(
            "wordpressdeploymenttransition",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("audit_id", sa.Integer(), sa.ForeignKey("wordpressdeploymentaudit.id"), nullable=False),
            sa.Column("previous_state", sa.String(40)),
            sa.Column("new_state", sa.String(40), nullable=False),
            sa.Column("transitioned_at", sa.DateTime(), nullable=False),
            sa.Column("actor", sa.String(200), nullable=False),
            sa.Column("reason", sa.String(500), nullable=False),
            sa.Column("request_identifier", sa.String(64), nullable=False),
            sa.CheckConstraint(f"previous_state IS NULL OR previous_state IN ({STATES})", name="ck_wordpressdeploymenttransition_previous_state"),
            sa.CheckConstraint(f"new_state IN ({STATES})", name="ck_wordpressdeploymenttransition_new_state"),
            sa.UniqueConstraint("request_identifier", name="uq_wordpressdeploymenttransition_request_identifier"),
        )
        for name in ("audit_id", "new_state", "transitioned_at", "request_identifier"):
            op.create_index(f"ix_wordpressdeploymenttransition_{name}", "wordpressdeploymenttransition", [name])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "wordpressdeploymenttransition" in tables:
        op.drop_table("wordpressdeploymenttransition")
    if "wordpressdeploymentnonce" in tables:
        op.drop_table("wordpressdeploymentnonce")
    if "wordpressdeploymentaudit" in tables:
        op.drop_table("wordpressdeploymentaudit")
