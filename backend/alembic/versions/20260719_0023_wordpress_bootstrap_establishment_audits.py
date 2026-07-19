"""Add audited manual bootstrap establishment records.

Revision ID: 20260719_0023
Revises: 20260717_0022
"""
from alembic import op
import sqlalchemy as sa

revision = "20260719_0023"
down_revision = "20260717_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "wordpressbootstrapestablishmentaudit"
    if table in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generated_page_id", sa.Integer(), sa.ForeignKey("generatedpage.id"), nullable=False),
        sa.Column("wordpress_post_id", sa.Integer(), nullable=False),
        sa.Column("installation_audit_id", sa.Integer(), sa.ForeignKey("wordpressdeploymentaudit.id"), nullable=False),
        sa.Column("activation_audit_id", sa.Integer(), sa.ForeignKey("wordpressactivationaudit.id"), nullable=False),
        sa.Column("action_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("operator", sa.String(200), nullable=False),
        sa.Column("bootstrap_slug", sa.String(100), nullable=False),
        sa.Column("bootstrap_directory", sa.String(160), nullable=False),
        sa.Column("bootstrap_path", sa.String(255), nullable=False),
        sa.Column("bootstrap_version", sa.String(32), nullable=False),
        sa.Column("bootstrap_zip_filename", sa.String(180), nullable=False),
        sa.Column("bootstrap_zip_sha256", sa.String(64), nullable=False),
        sa.Column("bootstrap_entry_sha256", sa.String(64), nullable=False),
        sa.Column("manual_phrase_hash", sa.String(64), nullable=False),
        sa.Column("activation_phrase_hash", sa.String(64), nullable=False),
        sa.Column("manual_handle_fingerprint", sa.String(64), nullable=False),
        sa.Column("activation_handle_fingerprint", sa.String(64)),
        sa.Column("manual_binding_hash", sa.String(64), nullable=False),
        sa.Column("activation_binding_hash", sa.String(64)),
        sa.Column("release_identity", sa.JSON(), nullable=False),
        sa.Column("backup_evidence", sa.JSON(), nullable=False),
        sa.Column("browser_evidence_id", sa.String(200), nullable=False),
        sa.Column("pre_snapshot", sa.JSON(), nullable=False),
        sa.Column("upload_snapshot", sa.JSON()),
        sa.Column("final_snapshot", sa.JSON()),
        sa.Column("source_inventories", sa.JSON(), nullable=False),
        sa.Column("upload_inventories", sa.JSON()),
        sa.Column("final_inventories", sa.JSON()),
        sa.Column("protected_state", sa.JSON(), nullable=False),
        sa.Column("gate_results", sa.JSON(), nullable=False),
        sa.Column("inactive_checksum_verifiable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approved_residual_risk", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("checksum_verification_source", sa.String(160)),
        sa.Column("checksum_verification_result", sa.String(80)),
        sa.Column("wordpress_write_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wordpress_write_scope", sa.JSON(), nullable=False),
        sa.Column("cache_write_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("atlas_write_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("atlas_write_scope", sa.JSON(), nullable=False),
        sa.Column("transition_history", sa.JSON(), nullable=False),
        sa.Column("recovery_recommendation", sa.String(80)),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.String(2000)),
        sa.CheckConstraint("status IN ('awaiting_manual_bootstrap_installation','manual_installation_inventory_verified','activation_pending_checksum_verification','verified','manual_installation_mismatch','manual_activation_detected','installation_partial','checksum_mismatch','checksum_unavailable','verification_failed','recovery_required')", name="ck_wordpressbootstrapestablishmentaudit_status"),
        sa.UniqueConstraint("manual_handle_fingerprint", name="uq_bootstrapestablishment_manual_handle"),
        sa.UniqueConstraint("activation_handle_fingerprint", name="uq_bootstrapestablishment_activation_handle"),
    )
    for name in ("generated_page_id", "wordpress_post_id", "installation_audit_id", "activation_audit_id", "action_type", "status", "manual_handle_fingerprint", "activation_handle_fingerprint", "manual_binding_hash", "activation_binding_hash", "attempted_at"):
        op.create_index(f"ix_{table}_{name}", table, [name])


def downgrade() -> None:
    table = "wordpressbootstrapestablishmentaudit"
    if table in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(table)
