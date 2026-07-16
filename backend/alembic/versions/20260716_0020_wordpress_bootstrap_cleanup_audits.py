"""Add guarded upgrade-bootstrap cleanup audits.

Revision ID: 20260716_0020
Revises: 20260716_0019
"""
from alembic import op
import sqlalchemy as sa

revision = "20260716_0020"
down_revision = "20260716_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "wordpressbootstrapcleanupaudit" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "wordpressbootstrapcleanupaudit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generated_page_id", sa.Integer(), sa.ForeignKey("generatedpage.id"), nullable=False),
        sa.Column("wordpress_post_id", sa.Integer(), nullable=False),
        sa.Column("installation_audit_id", sa.Integer(), sa.ForeignKey("wordpressdeploymentaudit.id"), nullable=False),
        sa.Column("activation_audit_id", sa.Integer(), sa.ForeignKey("wordpressactivationaudit.id"), nullable=False),
        sa.Column("upgrade_audit_id", sa.Integer(), sa.ForeignKey("wordpresspluginupgradeaudit.id"), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("operator", sa.String(200), nullable=False),
        sa.Column("bootstrap_slug", sa.String(100), nullable=False),
        sa.Column("bootstrap_path", sa.String(255), nullable=False),
        sa.Column("bootstrap_version", sa.String(32), nullable=False),
        sa.Column("bootstrap_zip_sha256", sa.String(64), nullable=False),
        sa.Column("bridge_version", sa.String(32), nullable=False),
        sa.Column("deactivation_phrase_hash", sa.String(64), nullable=False),
        sa.Column("deletion_phrase_hash", sa.String(64), nullable=False),
        sa.Column("deactivation_handle_fingerprint", sa.String(64), nullable=False),
        sa.Column("deletion_handle_fingerprint", sa.String(64)),
        sa.Column("deactivation_binding_hash", sa.String(64), nullable=False),
        sa.Column("deletion_binding_hash", sa.String(64)),
        sa.Column("release_identity", sa.JSON(), nullable=False),
        sa.Column("backup_evidence", sa.JSON(), nullable=False),
        sa.Column("browser_evidence_id", sa.String(200), nullable=False),
        sa.Column("browser_evidence_hashes", sa.JSON(), nullable=False),
        sa.Column("pre_snapshot", sa.JSON(), nullable=False),
        sa.Column("deactivated_snapshot", sa.JSON()),
        sa.Column("final_snapshot", sa.JSON()),
        sa.Column("previous_inventories", sa.JSON(), nullable=False),
        sa.Column("deactivated_inventories", sa.JSON()),
        sa.Column("final_inventories", sa.JSON()),
        sa.Column("metadata_rendering_state", sa.JSON(), nullable=False),
        sa.Column("page_media_snapshots", sa.JSON(), nullable=False),
        sa.Column("gate_results", sa.JSON(), nullable=False),
        sa.Column("wordpress_write_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wordpress_write_scope", sa.JSON(), nullable=False),
        sa.Column("atlas_write_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("atlas_write_scope", sa.JSON(), nullable=False),
        sa.Column("verification_findings", sa.JSON()),
        sa.Column("recovery_recommendation", sa.String(64)),
        sa.Column("transition_history", sa.JSON(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("deactivated_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.String(2000)),
        sa.CheckConstraint("action_type = 'cleanup_upgrade_bootstrap'", name="ck_wordpressbootstrapcleanupaudit_action"),
        sa.CheckConstraint("status IN ('pending','deactivated','verified','verification_failed','failed')", name="ck_wordpressbootstrapcleanupaudit_status"),
        sa.UniqueConstraint("deactivation_handle_fingerprint", name="uq_wordpressbootstrapcleanupaudit_deactivation_handle"),
        sa.UniqueConstraint("deletion_handle_fingerprint", name="uq_wordpressbootstrapcleanupaudit_deletion_handle"),
    )
    for name in (
        "generated_page_id", "wordpress_post_id", "installation_audit_id",
        "activation_audit_id", "upgrade_audit_id", "status",
        "deactivation_handle_fingerprint", "deletion_handle_fingerprint",
        "deactivation_binding_hash", "deletion_binding_hash", "attempted_at",
    ):
        op.create_index(f"ix_wordpressbootstrapcleanupaudit_{name}", "wordpressbootstrapcleanupaudit", [name])


def downgrade() -> None:
    if "wordpressbootstrapcleanupaudit" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("wordpressbootstrapcleanupaudit")
