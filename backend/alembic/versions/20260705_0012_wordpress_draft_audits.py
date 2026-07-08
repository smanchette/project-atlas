"""Add WordPress draft references and confirmed-attempt audits.

Revision ID: 20260705_0012
Revises: 20260701_0011
"""

from alembic import op
import sqlalchemy as sa


revision = "20260705_0012"
down_revision = "20260701_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    page_columns = {column["name"] for column in inspector.get_columns("generatedpage")}
    for name, column_type in (
        ("wordpress_post_id", sa.Integer()),
        ("wordpress_status", sa.String()),
        ("wordpress_created_at", sa.DateTime()),
        ("last_wordpress_sync_at", sa.DateTime()),
    ):
        if name not in page_columns:
            op.add_column("generatedpage", sa.Column(name, column_type, nullable=True))

    page_indexes = {index["name"] for index in inspector.get_indexes("generatedpage")}
    if "ix_generatedpage_wordpress_post_id" not in page_indexes:
        op.create_index("ix_generatedpage_wordpress_post_id", "generatedpage", ["wordpress_post_id"])
    if "ix_generatedpage_wordpress_status" not in page_indexes:
        op.create_index("ix_generatedpage_wordpress_status", "generatedpage", ["wordpress_status"])

    if "wordpressdraftaudit" not in inspector.get_table_names():
        op.create_table(
            "wordpressdraftaudit",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("generated_page_id", sa.Integer(), nullable=False),
            sa.Column("attempted_at", sa.DateTime(), nullable=False),
            sa.Column("action_type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("wordpress_site_url", sa.String(), nullable=False),
            sa.Column("wordpress_post_id", sa.Integer(), nullable=True),
            sa.Column("wordpress_status", sa.String(), nullable=True),
            sa.Column("slug", sa.String(), nullable=False),
            sa.Column("payload_hash", sa.String(), nullable=False),
            sa.Column("qa_status_at_attempt", sa.String(), nullable=False),
            sa.Column("qa_checked_at", sa.DateTime(), nullable=True),
            sa.Column("draft_hash_at_attempt", sa.String(), nullable=False),
            sa.Column("gate_results", sa.JSON(), nullable=False),
            sa.Column("error_message", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["generated_page_id"], ["generatedpage.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "generated_page_id",
                "attempted_at",
                "payload_hash",
                name="uq_wordpressdraftaudit_page_time_hash",
            ),
        )

    audit_indexes = (
        {index["name"] for index in inspector.get_indexes("wordpressdraftaudit")}
        if "wordpressdraftaudit" in inspector.get_table_names()
        else set()
    )
    for column in (
        "generated_page_id",
        "attempted_at",
        "action_type",
        "status",
        "wordpress_post_id",
        "wordpress_status",
        "slug",
        "payload_hash",
        "draft_hash_at_attempt",
    ):
        index_name = f"ix_wordpressdraftaudit_{column}"
        if index_name not in audit_indexes:
            op.create_index(index_name, "wordpressdraftaudit", [column])


def downgrade() -> None:
    for column in reversed(
        (
            "generated_page_id",
            "attempted_at",
            "action_type",
            "status",
            "wordpress_post_id",
            "wordpress_status",
            "slug",
            "payload_hash",
            "draft_hash_at_attempt",
        )
    ):
        op.drop_index(f"ix_wordpressdraftaudit_{column}", table_name="wordpressdraftaudit")
    op.drop_table("wordpressdraftaudit")
    op.drop_index("ix_generatedpage_wordpress_status", table_name="generatedpage")
    op.drop_index("ix_generatedpage_wordpress_post_id", table_name="generatedpage")
    op.drop_column("generatedpage", "last_wordpress_sync_at")
    op.drop_column("generatedpage", "wordpress_created_at")
    op.drop_column("generatedpage", "wordpress_status")
    op.drop_column("generatedpage", "wordpress_post_id")
