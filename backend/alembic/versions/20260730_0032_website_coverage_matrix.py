"""Add Website-scoped approved coverage and inventory planning.

Revision ID: 20260730_0032
Revises: 20260730_0031
"""

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "20260730_0032"
down_revision = "20260730_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "websitecoverageplanningrecord" not in existing:
        op.create_table(
            "websitecoverageplanningrecord",
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("site_plan_id", sa.Integer(), nullable=False),
            sa.Column("generated_service_candidates", sa.JSON(), nullable=False),
            sa.Column("generated_county_candidates", sa.JSON(), nullable=False),
            sa.Column("generated_city_candidates", sa.JSON(), nullable=False),
            sa.Column("generated_matrix_candidates", sa.JSON(), nullable=False),
            sa.Column("source_snapshot", sa.JSON(), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["site_plan_id"], ["siteplan.id"]),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "site_plan_id",
                name="uq_websitecoverageplanningrecord_site_plan",
            ),
        )
        for column in ("website_id", "site_plan_id"):
            op.create_index(
                op.f(f"ix_websitecoverageplanningrecord_{column}"),
                "websitecoverageplanningrecord",
                [column],
                unique=False,
            )
    _create_decision_table(
        existing,
        "websiteservicecoveragedecision",
        [("service_id", "service.id")],
        "uq_websiteservicecoveragedecision_website_service",
    )
    _create_decision_table(
        existing,
        "websitecountycoveragedecision",
        [("county_id", "county.id")],
        "uq_websitecountycoveragedecision_website_county",
        county=True,
    )
    _create_decision_table(
        existing,
        "websitecitycoveragedecision",
        [("city_id", "city.id")],
        "uq_websitecitycoveragedecision_website_city",
    )
    _create_decision_table(
        existing,
        "websiteservicecitycoveragedecision",
        [("service_id", "service.id"), ("city_id", "city.id")],
        "uq_websiteservicecitycoveragedecision_website_service_city",
    )

    bind = op.get_bind()
    now = datetime.now(UTC)
    plans = list(
        bind.execute(
            sa.text("SELECT id, website_id FROM siteplan ORDER BY id")
        ).mappings()
    )
    for plan in plans:
        bind.execute(
            sa.text(
                """
                INSERT INTO websitecoverageplanningrecord
                    (created_at, updated_at, website_id, site_plan_id,
                     generated_service_candidates, generated_county_candidates,
                     generated_city_candidates, generated_matrix_candidates,
                     source_snapshot, generated_at)
                SELECT :now, :now, :website_id, :site_plan_id,
                       '[]', '[]', '[]', '[]', '{}', :now
                WHERE NOT EXISTS (
                    SELECT 1 FROM websitecoverageplanningrecord
                    WHERE site_plan_id = :site_plan_id
                )
                """
            ),
            {
                "now": now,
                "website_id": int(plan["website_id"]),
                "site_plan_id": int(plan["id"]),
            },
        )


def _create_decision_table(
    existing: set[str],
    table: str,
    relationships: list[tuple[str, str]],
    unique_name: str,
    *,
    county: bool = False,
) -> None:
    if table in existing:
        return
    columns = [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_id", sa.Integer(), nullable=False),
    ]
    columns.extend(
        sa.Column(column, sa.Integer(), nullable=False)
        for column, _ in relationships
    )
    columns.extend(
        [
            sa.Column("status", sa.String(length=24), nullable=False),
            *(
                [sa.Column("page_appropriate", sa.Boolean(), nullable=False)]
                if county
                else []
            ),
            sa.Column("rationale", sa.String(), nullable=True),
            sa.Column("decided_by", sa.String(), nullable=False),
            sa.Column("decision_version", sa.Integer(), nullable=False),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('included','excluded','deferred')",
                name=f"ck_{table}_status",
            ),
            sa.CheckConstraint(
                "decision_version >= 1",
                name=f"ck_{table}_version",
            ),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            *[
                sa.ForeignKeyConstraint([column], [target])
                for column, target in relationships
            ],
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "website_id",
                *[column for column, _ in relationships],
                name=unique_name,
            ),
        ]
    )
    op.create_table(table, *columns)
    for column in (
        "website_id",
        *[column for column, _ in relationships],
        "status",
        *(["page_appropriate"] if county else []),
    ):
        op.create_index(
            op.f(f"ix_{table}_{column}"),
            table,
            [column],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    decision_tables = (
        "websiteservicecitycoveragedecision",
        "websitecitycoveragedecision",
        "websitecountycoveragedecision",
        "websiteservicecoveragedecision",
    )
    existing = set(sa.inspect(bind).get_table_names())
    for table in decision_tables:
        if table in existing:
            count = bind.execute(
                sa.text(f"SELECT COUNT(*) FROM {table}")
            ).scalar_one()
            if count:
                raise RuntimeError(
                    "Cannot downgrade while operator coverage decisions exist."
                )
    for table in (*decision_tables, "websitecoverageplanningrecord"):
        if table in set(sa.inspect(bind).get_table_names()):
            op.drop_table(table)
