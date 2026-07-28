"""Add website-scoped site plans and planning records.

Revision ID: 20260728_0029
Revises: 20260727_0028
"""

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "20260728_0029"
down_revision = "20260727_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "siteplan" not in existing_tables:
        _create_site_plan_table()
    else:
        _validate_existing_table(
            "siteplan",
            {
                "created_at",
                "updated_at",
                "id",
                "website_id",
                "plan_key",
                "plan_name",
                "status",
                "version",
            },
            {("website_id", "plan_key")},
        )
        _ensure_indexes("siteplan", ("website_id", "plan_key", "status"))
    if "plannedpage" not in existing_tables:
        _create_planned_page_table()
    else:
        _validate_existing_table(
            "plannedpage",
            {
                "created_at",
                "updated_at",
                "id",
                "website_id",
                "site_plan_id",
                "page_type",
                "working_name",
                "intended_slug",
                "service_id",
                "city_id",
                "county_id",
                "parent_planned_page_id",
                "planning_status",
                "generated_page_id",
            },
            {("website_id", "intended_slug"), ("generated_page_id",)},
        )
        _ensure_indexes(
            "plannedpage",
            (
                "website_id",
                "site_plan_id",
                "page_type",
                "intended_slug",
                "service_id",
                "city_id",
                "county_id",
                "parent_planned_page_id",
                "planning_status",
                "generated_page_id",
            ),
        )
    if "planningrecord" not in existing_tables:
        _create_planning_record_table()
    else:
        _validate_existing_table(
            "planningrecord",
            {
                "created_at",
                "updated_at",
                "id",
                "planned_page_id",
                "generated_answers",
                "operator_overrides",
                "source_snapshot",
                "confidence_score",
                "confidence_level",
                "missing_information",
                "improvement_recommendations",
                "generated_at",
                "reviewed_at",
            },
            {("planned_page_id",)},
        )
        _ensure_indexes(
            "planningrecord",
            ("planned_page_id", "confidence_level"),
        )

    _replace_generated_page_slug_index()
    _backfill_site_plans()


def _create_site_plan_table() -> None:
    op.create_table(
        "siteplan",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("website_id", sa.Integer(), sa.ForeignKey("website.id"), nullable=False),
        sa.Column("plan_key", sa.String(length=80), nullable=False),
        sa.Column("plan_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("website_id", "plan_key", name="uq_siteplan_website_key"),
    )
    for column in ("website_id", "plan_key", "status"):
        op.create_index(f"ix_siteplan_{column}", "siteplan", [column])


def _create_planned_page_table() -> None:
    op.create_table(
        "plannedpage",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("website_id", sa.Integer(), sa.ForeignKey("website.id"), nullable=False),
        sa.Column("site_plan_id", sa.Integer(), sa.ForeignKey("siteplan.id"), nullable=False),
        sa.Column("page_type", sa.String(), nullable=False),
        sa.Column("working_name", sa.String(), nullable=False),
        sa.Column("intended_slug", sa.String(), nullable=False),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("service.id"), nullable=True),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("city.id"), nullable=True),
        sa.Column("county_id", sa.Integer(), sa.ForeignKey("county.id"), nullable=True),
        sa.Column(
            "parent_planned_page_id",
            sa.Integer(),
            sa.ForeignKey("plannedpage.id"),
            nullable=True,
        ),
        sa.Column(
            "generated_page_id",
            sa.Integer(),
            sa.ForeignKey("generatedpage.id"),
            nullable=True,
        ),
        sa.Column("planning_status", sa.String(), nullable=False),
        sa.UniqueConstraint("website_id", "intended_slug", name="uq_plannedpage_website_slug"),
        sa.UniqueConstraint("generated_page_id", name="uq_plannedpage_generated_page"),
    )
    for column in (
        "website_id",
        "site_plan_id",
        "page_type",
        "intended_slug",
        "service_id",
        "city_id",
        "county_id",
        "parent_planned_page_id",
        "planning_status",
        "generated_page_id",
    ):
        op.create_index(f"ix_plannedpage_{column}", "plannedpage", [column])


def _create_planning_record_table() -> None:
    op.create_table(
        "planningrecord",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "planned_page_id",
            sa.Integer(),
            sa.ForeignKey("plannedpage.id"),
            nullable=False,
        ),
        sa.Column("generated_answers", sa.JSON(), nullable=False),
        sa.Column("operator_overrides", sa.JSON(), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("confidence_level", sa.String(), nullable=False),
        sa.Column("missing_information", sa.JSON(), nullable=False),
        sa.Column("improvement_recommendations", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("planned_page_id", name="uq_planningrecord_planned_page"),
    )
    op.create_index("ix_planningrecord_planned_page_id", "planningrecord", ["planned_page_id"])
    op.create_index("ix_planningrecord_confidence_level", "planningrecord", ["confidence_level"])


def _validate_existing_table(
    table_name: str,
    expected_columns: set[str],
    required_unique_columns: set[tuple[str, ...]],
) -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"]
        for column in inspector.get_columns(table_name)
    }
    if columns != expected_columns:
        raise RuntimeError(
            f"Existing {table_name} schema does not match migration 20260728_0029."
        )
    unique_columns = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table_name)
    }
    if not required_unique_columns.issubset(unique_columns):
        raise RuntimeError(
            f"Existing {table_name} uniqueness does not match migration 20260728_0029."
        )


def _ensure_indexes(table_name: str, columns: tuple[str, ...]) -> None:
    existing = {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }
    for column in columns:
        name = f"ix_{table_name}_{column}"
        if name not in existing:
            op.create_index(name, table_name, [column])


def _replace_generated_page_slug_index() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {item["name"]: item for item in inspector.get_indexes("generatedpage")}
    existing = indexes.get("ix_generatedpage_page_slug")
    if existing and existing.get("unique"):
        op.drop_index("ix_generatedpage_page_slug", table_name="generatedpage")
        op.create_index(
            "ix_generatedpage_page_slug",
            "generatedpage",
            ["page_slug"],
            unique=False,
        )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("generatedpage") as batch:
            batch.create_unique_constraint(
                "uq_generatedpage_website_slug",
                ["website_id", "page_slug"],
            )
    else:
        op.create_unique_constraint(
            "uq_generatedpage_website_slug",
            "generatedpage",
            ["website_id", "page_slug"],
        )


def _backfill_site_plans() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    website = sa.Table("website", metadata, autoload_with=bind)
    generated_page = sa.Table("generatedpage", metadata, autoload_with=bind)
    site_plan = sa.Table("siteplan", metadata, autoload_with=bind)
    planned_page = sa.Table("plannedpage", metadata, autoload_with=bind)
    planning_record = sa.Table("planningrecord", metadata, autoload_with=bind)
    now = datetime.now(UTC)
    websites = bind.execute(sa.select(website).order_by(website.c.id)).mappings().all()
    for site in websites:
        plan_id = bind.execute(
            sa.select(site_plan.c.id).where(
                site_plan.c.website_id == site["id"],
                site_plan.c.plan_key == "primary",
            )
        ).scalar_one_or_none()
        if plan_id is None:
            plan_result = bind.execute(
                site_plan.insert().values(
                    created_at=now,
                    updated_at=now,
                    website_id=site["id"],
                    plan_key="primary",
                    plan_name=f"{site['website_name']} Site Plan",
                    status="draft",
                    version=1,
                )
            )
            plan_id = plan_result.inserted_primary_key[0]
        pages = bind.execute(
            sa.select(generated_page)
            .where(generated_page.c.website_id == site["id"])
            .order_by(generated_page.c.id)
        ).mappings().all()
        for page in pages:
            existing_planned_id = bind.execute(
                sa.select(planned_page.c.id).where(
                    planned_page.c.generated_page_id == page["id"]
                )
            ).scalar_one_or_none()
            if existing_planned_id is not None:
                existing_record = bind.execute(
                    sa.select(planning_record.c.id).where(
                        planning_record.c.planned_page_id == existing_planned_id
                    )
                ).scalar_one_or_none()
                if existing_record is None:
                    _insert_planning_record(
                        bind,
                        planning_record,
                        planned_id=existing_planned_id,
                        site=site,
                        page=page,
                        now=now,
                    )
                continue
            planned_result = bind.execute(
                planned_page.insert().values(
                    created_at=now,
                    updated_at=now,
                    website_id=site["id"],
                    site_plan_id=plan_id,
                    page_type=page["page_type"],
                    working_name=page["page_title"],
                    intended_slug=page["page_slug"],
                    service_id=page["service_id"],
                    city_id=page["city_id"],
                    county_id=page["county_id"],
                    parent_planned_page_id=None,
                    planning_status="generated",
                    generated_page_id=page["id"],
                )
            )
            planned_id = planned_result.inserted_primary_key[0]
            _insert_planning_record(
                bind,
                planning_record,
                planned_id=planned_id,
                site=site,
                page=page,
                now=now,
            )


def _insert_planning_record(
    bind,
    planning_record: sa.Table,
    *,
    planned_id: int,
    site,
    page,
    now: datetime,
) -> None:
    relationships = [{"type": "website", "id": site["id"], "name": site["website_name"]}]
    for relation_type, column in (
        ("service", "service_id"),
        ("county", "county_id"),
        ("city", "city_id"),
    ):
        if page[column] is not None:
            relationships.append(
                {"type": relation_type, "id": page[column], "name": None}
            )
    bind.execute(
        planning_record.insert().values(
            created_at=now,
            updated_at=now,
            planned_page_id=planned_id,
            generated_answers={
                "purpose": "Explain an approved service for a legitimate local service area without unsupported localization.",
                "audiences": ["General customers"],
                "required_facts": [],
                "missing_required_facts": [],
                "relationships": relationships,
                "primary_action": "Request an estimate for the service in this area.",
            },
            operator_overrides={},
            source_snapshot={
                "website_id": site["id"],
                "generated_page_id": page["id"],
                "provider_sources": ["migration_backfill"],
            },
            confidence_score=1.0,
            confidence_level="high",
            missing_information=[],
            improvement_recommendations=[],
            generated_at=now,
            reviewed_at=None,
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    populated = bind.execute(
        sa.text(
            "SELECT (SELECT COUNT(*) FROM siteplan) + "
            "(SELECT COUNT(*) FROM plannedpage) + "
            "(SELECT COUNT(*) FROM planningrecord)"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError(
            "Cannot downgrade while Site Plan records exist; restore a pre-migration Atlas Data backup."
        )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("generatedpage") as batch:
            batch.drop_constraint(
                "uq_generatedpage_website_slug",
                type_="unique",
            )
    else:
        op.drop_constraint(
            "uq_generatedpage_website_slug",
            "generatedpage",
            type_="unique",
        )
    op.drop_index("ix_generatedpage_page_slug", table_name="generatedpage")
    op.create_index(
        "ix_generatedpage_page_slug",
        "generatedpage",
        ["page_slug"],
        unique=True,
    )
    op.drop_table("planningrecord")
    op.drop_table("plannedpage")
    op.drop_table("siteplan")
