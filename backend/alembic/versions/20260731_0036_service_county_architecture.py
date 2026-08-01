"""Add explicit Website Service-County coverage decisions.

Revision ID: 20260731_0036
Revises: 20260731_0035
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0036"
down_revision = "20260731_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    columns = {
        column["name"]
        for column in inspector.get_columns("websitecoverageplanningrecord")
    }
    if "generated_service_county_candidates" not in columns:
        op.add_column(
            "websitecoverageplanningrecord",
            sa.Column(
                "generated_service_county_candidates",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )
        if op.get_bind().dialect.name != "sqlite":
            op.alter_column(
                "websitecoverageplanningrecord",
                "generated_service_county_candidates",
                server_default=None,
            )

    if "websiteservicecountycoveragedecision" not in tables:
        op.create_table(
            "websiteservicecountycoveragedecision",
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("service_id", sa.Integer(), nullable=False),
            sa.Column("county_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("rationale", sa.String(), nullable=True),
            sa.Column("decided_by", sa.String(), nullable=False),
            sa.Column("decision_version", sa.Integer(), nullable=False),
            sa.Column("decided_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "status IN ('included','excluded','deferred')",
                name="ck_websiteservicecountycoveragedecision_status",
            ),
            sa.CheckConstraint(
                "decision_version >= 1",
                name="ck_websiteservicecountycoveragedecision_version",
            ),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.ForeignKeyConstraint(["service_id"], ["service.id"]),
            sa.ForeignKeyConstraint(["county_id"], ["county.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "website_id",
                "service_id",
                "county_id",
                name="uq_websiteservicecountycoveragedecision_website_service_county",
            ),
        )
        for column in ("website_id", "service_id", "county_id", "status"):
            op.create_index(
                f"ix_websiteservicecountycoveragedecision_{column}",
                "websiteservicecountycoveragedecision",
                [column],
            )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT COUNT(*) FROM websiteservicecountycoveragedecision")
    ).scalar_one():
        raise RuntimeError(
            "Downgrade blocked: durable Service-County coverage decisions exist."
        )
    op.drop_table("websiteservicecountycoveragedecision")
    op.drop_column(
        "websitecoverageplanningrecord",
        "generated_service_county_candidates",
    )
