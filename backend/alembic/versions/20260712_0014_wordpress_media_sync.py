"""Add WordPress media sync mapping and audits.

Revision ID: 20260712_0014
Revises: 20260711_0013
"""
from alembic import op
import sqlalchemy as sa

revision = "20260712_0014"
down_revision = "20260711_0013"
branch_labels = None
depends_on = None

def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("imagemetadata")}
    for name, kind in (
        ("wordpress_media_id", sa.Integer()), ("wordpress_media_url", sa.String()),
        ("wordpress_media_status", sa.String()), ("wordpress_media_checksum", sa.String()),
        ("wordpress_media_uploaded_at", sa.DateTime()), ("last_wordpress_media_sync_at", sa.DateTime()),
    ):
        if name not in columns: op.add_column("imagemetadata", sa.Column(name, kind, nullable=True))
    for name in ("wordpress_media_id", "wordpress_media_status", "wordpress_media_checksum"):
        op.create_index(f"ix_imagemetadata_{name}", "imagemetadata", [name])
    if "wordpressmediasyncaudit" not in inspector.get_table_names():
        op.create_table(
            "wordpressmediasyncaudit",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("generated_page_id", sa.Integer(), sa.ForeignKey("generatedpage.id"), nullable=False),
            sa.Column("image_metadata_id", sa.Integer(), sa.ForeignKey("imagemetadata.id"), nullable=False),
            sa.Column("page_image_assignment_id", sa.Integer(), sa.ForeignKey("pageimageassignment.id"), nullable=False),
            sa.Column("wordpress_post_id", sa.Integer(), nullable=False), sa.Column("wordpress_media_id", sa.Integer()),
            sa.Column("action_type", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False),
            sa.Column("attempted_at", sa.DateTime(), nullable=False), sa.Column("completed_at", sa.DateTime()),
            sa.Column("wordpress_site_url", sa.String(), nullable=False), sa.Column("source_file_name", sa.String(), nullable=False),
            sa.Column("source_mime_type", sa.String(), nullable=False), sa.Column("source_file_size", sa.Integer(), nullable=False),
            sa.Column("source_width", sa.Integer(), nullable=False), sa.Column("source_height", sa.Integer(), nullable=False),
            sa.Column("source_checksum", sa.String(), nullable=False), sa.Column("alt_text", sa.String(), nullable=False),
            sa.Column("returned_media_url", sa.String()), sa.Column("gate_results", sa.JSON(), nullable=False),
            sa.Column("backup_file_name", sa.String(), nullable=False), sa.Column("error_message", sa.String()),
            sa.UniqueConstraint("generated_page_id", "attempted_at", "source_checksum", name="uq_wordpressmediasyncaudit_page_time_checksum"),
        )
        for name in ("generated_page_id","image_metadata_id","page_image_assignment_id","wordpress_post_id","wordpress_media_id","action_type","status","attempted_at","source_checksum"):
            op.create_index(f"ix_wordpressmediasyncaudit_{name}", "wordpressmediasyncaudit", [name])

def downgrade() -> None:
    op.drop_table("wordpressmediasyncaudit")
    for name in ("last_wordpress_media_sync_at","wordpress_media_uploaded_at","wordpress_media_checksum","wordpress_media_status","wordpress_media_url","wordpress_media_id"):
        op.drop_column("imagemetadata", name)
