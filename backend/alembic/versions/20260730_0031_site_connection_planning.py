"""Add website-scoped navigation and internal-link planning.

Revision ID: 20260730_0031
Revises: 20260728_0030
"""

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "20260730_0031"
down_revision = "20260728_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "siteconnectionplanningrecord" not in existing:
        op.create_table(
            "siteconnectionplanningrecord",
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("site_plan_id", sa.Integer(), nullable=False),
            sa.Column(
                "generated_navigation_suggestions",
                sa.JSON(),
                nullable=False,
            ),
            sa.Column(
                "generated_internal_link_suggestions",
                sa.JSON(),
                nullable=False,
            ),
            sa.Column("source_snapshot", sa.JSON(), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["site_plan_id"], ["siteplan.id"]),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "site_plan_id",
                name="uq_siteconnectionplanningrecord_site_plan",
            ),
        )
        op.create_index(
            op.f("ix_siteconnectionplanningrecord_website_id"),
            "siteconnectionplanningrecord",
            ["website_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_siteconnectionplanningrecord_site_plan_id"),
            "siteconnectionplanningrecord",
            ["site_plan_id"],
            unique=False,
        )
    if "navigationset" not in existing:
        op.create_table(
            "navigationset",
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("site_plan_id", sa.Integer(), nullable=False),
            sa.Column("set_type", sa.String(length=24), nullable=False),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["site_plan_id"], ["siteplan.id"]),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "site_plan_id",
                "set_type",
                name="uq_navigationset_site_plan_type",
            ),
        )
        for column in ("website_id", "site_plan_id", "set_type", "status"):
            op.create_index(
                op.f(f"ix_navigationset_{column}"),
                "navigationset",
                [column],
                unique=False,
            )
    if "navigationitem" not in existing:
        op.create_table(
            "navigationitem",
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("site_plan_id", sa.Integer(), nullable=False),
            sa.Column("navigation_set_id", sa.Integer(), nullable=False),
            sa.Column("target_planned_page_id", sa.Integer(), nullable=False),
            sa.Column("parent_navigation_item_id", sa.Integer(), nullable=True),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.ForeignKeyConstraint(
                ["navigation_set_id"],
                ["navigationset.id"],
            ),
            sa.ForeignKeyConstraint(
                ["parent_navigation_item_id"],
                ["navigationitem.id"],
            ),
            sa.ForeignKeyConstraint(
                ["site_plan_id"],
                ["siteplan.id"],
            ),
            sa.ForeignKeyConstraint(
                ["target_planned_page_id"],
                ["plannedpage.id"],
            ),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "navigation_set_id",
                "target_planned_page_id",
                name="uq_navigationitem_set_target",
            ),
        )
        for column in (
            "website_id",
            "site_plan_id",
            "navigation_set_id",
            "target_planned_page_id",
            "parent_navigation_item_id",
            "status",
        ):
            op.create_index(
                op.f(f"ix_navigationitem_{column}"),
                "navigationitem",
                [column],
                unique=False,
            )
    if "internallinkintent" not in existing:
        op.create_table(
            "internallinkintent",
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("site_plan_id", sa.Integer(), nullable=False),
            sa.Column("source_planned_page_id", sa.Integer(), nullable=False),
            sa.Column("target_planned_page_id", sa.Integer(), nullable=False),
            sa.Column("purpose", sa.String(), nullable=False),
            sa.Column("relationship_type", sa.String(length=40), nullable=False),
            sa.Column("anchor_guidance", sa.String(), nullable=True),
            sa.Column("approval_state", sa.String(length=24), nullable=False),
            sa.ForeignKeyConstraint(["site_plan_id"], ["siteplan.id"]),
            sa.ForeignKeyConstraint(
                ["source_planned_page_id"],
                ["plannedpage.id"],
            ),
            sa.ForeignKeyConstraint(
                ["target_planned_page_id"],
                ["plannedpage.id"],
            ),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "site_plan_id",
                "source_planned_page_id",
                "target_planned_page_id",
                "relationship_type",
                name="uq_internallinkintent_plan_edge_type",
            ),
        )
        for column in (
            "website_id",
            "site_plan_id",
            "source_planned_page_id",
            "target_planned_page_id",
            "relationship_type",
            "approval_state",
        ):
            op.create_index(
                op.f(f"ix_internallinkintent_{column}"),
                "internallinkintent",
                [column],
                unique=False,
            )

    bind = op.get_bind()
    now = datetime.now(UTC)
    plans = bind.execute(
        sa.text("SELECT id, website_id FROM siteplan ORDER BY id")
    ).mappings()
    for plan in plans:
        plan_id = int(plan["id"])
        website_id = int(plan["website_id"])
        for set_type, label in (
            ("primary", "Primary Navigation"),
            ("utility", "Utility Navigation"),
            ("footer", "Footer Navigation"),
        ):
            bind.execute(
                sa.text(
                    """
                    INSERT INTO navigationset
                        (created_at, updated_at, website_id, site_plan_id,
                         set_type, label, status, version)
                    VALUES (
                        :now, :now, :website_id, :plan_id,
                        :set_type, :label, 'draft', 1
                    )
                    ON CONFLICT (site_plan_id, set_type) DO NOTHING
                    """
                ),
                {
                    "now": now,
                    "website_id": website_id,
                    "plan_id": plan_id,
                    "set_type": set_type,
                    "label": label,
                },
            )
        bind.execute(
            sa.text(
                """
                INSERT INTO siteconnectionplanningrecord
                    (created_at, updated_at, website_id, site_plan_id,
                     generated_navigation_suggestions,
                     generated_internal_link_suggestions,
                     source_snapshot, generated_at)
                SELECT :now, :now, :website_id, :plan_id,
                       '[]', '[]', '{}', :now
                WHERE NOT EXISTS (
                    SELECT 1 FROM siteconnectionplanningrecord
                    WHERE site_plan_id = :plan_id
                )
                """
            ),
            {
                "now": now,
                "website_id": website_id,
                "plan_id": plan_id,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("internallinkintent", "navigationitem"):
        if table in set(sa.inspect(bind).get_table_names()):
            count = bind.execute(
                sa.text(f"SELECT COUNT(*) FROM {table}")
            ).scalar_one()
            if count:
                raise RuntimeError(
                    "Cannot downgrade while operator navigation or internal-link decisions exist."
                )
    for table in (
        "internallinkintent",
        "navigationitem",
        "navigationset",
        "siteconnectionplanningrecord",
    ):
        if table in set(sa.inspect(bind).get_table_names()):
            op.drop_table(table)
