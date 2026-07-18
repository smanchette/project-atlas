"""Add guarded cache-aware rendering audits.

Revision ID: 20260717_0022
Revises: 20260717_0021
"""
from alembic import op
import sqlalchemy as sa

revision = "20260717_0022"
down_revision = "20260717_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "wordpresscacheawarerenderingaudit"
    if table in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generated_page_id", sa.Integer(), sa.ForeignKey("generatedpage.id"), nullable=False),
        sa.Column("wordpress_post_id", sa.Integer(), nullable=False),
        sa.Column("staging_audit_id", sa.Integer(), sa.ForeignKey("wordpressmetadatalifecycleaudit.id"), nullable=False),
        sa.Column("recovery_disable_audit_id", sa.Integer(), sa.ForeignKey("wordpressmetadatalifecycleaudit.id"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("operator", sa.String(200), nullable=False),
        sa.Column("rendering_handle_fingerprint", sa.String(64), nullable=False),
        sa.Column("cache_handle_fingerprint", sa.String(64)),
        sa.Column("rendering_binding_hash", sa.String(64), nullable=False),
        sa.Column("cache_binding_hash", sa.String(64)),
        sa.Column("rendering_phrase_hash", sa.String(64), nullable=False),
        sa.Column("cache_phrase_hash", sa.String(64)),
        sa.Column("release_identity", sa.JSON(), nullable=False),
        sa.Column("backup_evidence", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.String(40), nullable=False),
        sa.Column("cache_provider", sa.String(80)),
        sa.Column("cache_scope", sa.String(80)),
        sa.Column("cache_target", sa.String(500)),
        sa.Column("pre_purge_headers", sa.JSON(), nullable=False),
        sa.Column("post_purge_headers", sa.JSON(), nullable=False),
        sa.Column("origin_verification", sa.JSON(), nullable=False),
        sa.Column("public_verification", sa.JSON(), nullable=False),
        sa.Column("public_evidence", sa.JSON(), nullable=False),
        sa.Column("page_media_snapshots", sa.JSON(), nullable=False),
        sa.Column("gate_results", sa.JSON(), nullable=False),
        sa.Column("wordpress_write_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("atlas_write_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wordpress_write_scope", sa.JSON(), nullable=False),
        sa.Column("cache_write_scope", sa.JSON(), nullable=False),
        sa.Column("atlas_write_scope", sa.JSON(), nullable=False),
        sa.Column("transition_history", sa.JSON(), nullable=False),
        sa.Column("final_state", sa.JSON()),
        sa.Column("recovery_recommendation", sa.String(64)),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.String(2000)),
        sa.CheckConstraint(
            "status IN ('pending_rendering','origin_verified','pending_cache_purge','verified','verification_failed','failed')",
            name="ck_wordpresscacheawarerenderingaudit_status",
        ),
        sa.UniqueConstraint("rendering_handle_fingerprint", name="uq_cacheaware_rendering_handle"),
        sa.UniqueConstraint("cache_handle_fingerprint", name="uq_cacheaware_cache_handle"),
    )
    for name in (
        "generated_page_id", "wordpress_post_id", "staging_audit_id", "recovery_disable_audit_id",
        "status", "rendering_handle_fingerprint", "cache_handle_fingerprint", "rendering_binding_hash",
        "cache_binding_hash", "payload_hash", "attempted_at",
    ):
        op.create_index(f"ix_{table}_{name}", table, [name])


def downgrade() -> None:
    table = "wordpresscacheawarerenderingaudit"
    if table in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(table)
