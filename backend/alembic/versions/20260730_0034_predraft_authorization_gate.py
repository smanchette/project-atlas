"""Add supporting-page authorization and pre-draft distinctness briefs.

Revision ID: 20260730_0034
Revises: 20260730_0033
"""

from alembic import op
import sqlalchemy as sa


revision = "20260730_0034"
down_revision = "20260730_0033"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _index_names(table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        if index.get("name")
    }


def _ensure_indexes(table_name: str, columns: tuple[str, ...]) -> None:
    existing = _index_names(table_name)
    for column in columns:
        name = f"ix_{table_name}_{column}"
        if name not in existing:
            op.create_index(name, table_name, [column])


def upgrade() -> None:
    if "generated_supporting_page_candidates" not in _column_names(
        "websitecoverageplanningrecord"
    ):
        op.add_column(
            "websitecoverageplanningrecord",
            sa.Column(
                "generated_supporting_page_candidates",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )
    if "distinctness_brief_binding" not in _column_names(
        "draftingeligibilityassessment"
    ):
        op.add_column(
            "draftingeligibilityassessment",
            sa.Column(
                "distinctness_brief_binding",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )
    if "supportingpageauthorization" not in _table_names():
        op.create_table(
        "supportingpageauthorization",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_id", sa.Integer(), nullable=False),
        sa.Column("site_plan_id", sa.Integer(), nullable=False),
        sa.Column("planned_page_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("decided_by", sa.String(), nullable=False),
        sa.Column("decision_version", sa.Integer(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('included','excluded','deferred')",
            name="ck_supportingpageauthorization_status",
        ),
        sa.CheckConstraint(
            "decision_version >= 1",
            name="ck_supportingpageauthorization_version",
        ),
        sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
        sa.ForeignKeyConstraint(["site_plan_id"], ["siteplan.id"]),
        sa.ForeignKeyConstraint(["planned_page_id"], ["plannedpage.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "planned_page_id",
            name="uq_supportingpageauthorization_planned_page",
        ),
        )
    required_authorization = {
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "status",
        "rationale",
        "decided_by",
        "decision_version",
    }
    if not required_authorization.issubset(
        _column_names("supportingpageauthorization")
    ):
        raise RuntimeError(
            "Existing supportingpageauthorization table is incompatible."
        )
    _ensure_indexes(
        "supportingpageauthorization",
        (
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "status",
        "decided_at",
        ),
    )
    if "predraftdistinctnessbrief" not in _table_names():
        op.create_table(
        "predraftdistinctnessbrief",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_id", sa.Integer(), nullable=False),
        sa.Column("site_plan_id", sa.Integer(), nullable=False),
        sa.Column("planned_page_id", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("intended_audience", sa.JSON(), nullable=False),
        sa.Column("search_intent", sa.String(), nullable=False),
        sa.Column("approved_fact_identities", sa.JSON(), nullable=False),
        sa.Column("approved_knowledge_identities", sa.JSON(), nullable=False),
        sa.Column("conversion_purpose", sa.String(), nullable=False),
        sa.Column("required_page_specific_value", sa.JSON(), nullable=False),
        sa.Column("proposed_unique_elements", sa.JSON(), nullable=False),
        sa.Column("related_planned_page_ids", sa.JSON(), nullable=False),
        sa.Column("competing_planned_page_ids", sa.JSON(), nullable=False),
        sa.Column("source_binding", sa.JSON(), nullable=False),
        sa.Column("brief_hash", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
        sa.ForeignKeyConstraint(["site_plan_id"], ["siteplan.id"]),
        sa.ForeignKeyConstraint(["planned_page_id"], ["plannedpage.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "planned_page_id",
            name="uq_predraftdistinctnessbrief_planned_page",
        ),
        )
    required_brief = {
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "algorithm_version",
        "brief_hash",
        "source_binding",
    }
    if not required_brief.issubset(_column_names("predraftdistinctnessbrief")):
        raise RuntimeError(
            "Existing predraftdistinctnessbrief table is incompatible."
        )
    _ensure_indexes(
        "predraftdistinctnessbrief",
        (
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "algorithm_version",
        "brief_hash",
        "generated_at",
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table in (
        "predraftdistinctnessbrief",
        "supportingpageauthorization",
    ):
        if connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {table}")
        ).scalar_one():
            raise RuntimeError(
                "Downgrade blocked: durable pre-draft authorization records exist."
            )
    op.drop_table("predraftdistinctnessbrief")
    op.drop_table("supportingpageauthorization")
    op.drop_column(
        "draftingeligibilityassessment",
        "distinctness_brief_binding",
    )
    op.drop_column(
        "websitecoverageplanningrecord",
        "generated_supporting_page_candidates",
    )
