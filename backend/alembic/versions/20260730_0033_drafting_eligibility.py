"""Add Website-scoped drafting eligibility assessments and dispositions.

Revision ID: 20260730_0033
Revises: 20260730_0032
"""

from alembic import op
import sqlalchemy as sa


revision = "20260730_0033"
down_revision = "20260730_0032"
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


def _check_names(table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(
            table_name
        )
        if constraint.get("name")
    }


def _row_count(table_name: str) -> int:
    return int(
        op.get_bind()
        .execute(sa.text(f"SELECT COUNT(*) FROM {table_name}"))
        .scalar_one()
    )


def _ensure_indexes(table_name: str, columns: tuple[str, ...]) -> None:
    existing = _index_names(table_name)
    for column in columns:
        name = f"ix_{table_name}_{column}"
        if name not in existing:
            op.create_index(name, table_name, [column])


def _repair_empty_legacy_assessment_table() -> None:
    columns = _column_names("draftingeligibilityassessment")
    current_only = {"evidence", "local_value_findings"}
    legacy_only = {
        "assessment_version",
        "local_value_brief",
        "supporting_evidence",
    }
    if current_only.issubset(columns) and not legacy_only.intersection(columns):
        return
    if not legacy_only.issubset(columns) or _row_count(
        "draftingeligibilityassessment"
    ):
        raise RuntimeError(
            "Migration 20260730_0033 found an incompatible, non-empty "
            "draftingeligibilityassessment table; refusing automatic repair."
        )

    checks = _check_names("draftingeligibilityassessment")
    for name in (
        "ck_draftingeligibilityassessment_version",
        "ck_draftingeligibilityassessment_status",
    ):
        if name in checks:
            op.drop_constraint(
                name,
                "draftingeligibilityassessment",
                type_="check",
            )
    for column in legacy_only:
        op.drop_column("draftingeligibilityassessment", column)
    op.add_column(
        "draftingeligibilityassessment",
        sa.Column(
            "evidence",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "draftingeligibilityassessment",
        sa.Column(
            "local_value_findings",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.alter_column(
        "draftingeligibilityassessment",
        "evidence",
        server_default=None,
    )
    op.alter_column(
        "draftingeligibilityassessment",
        "local_value_findings",
        server_default=None,
    )
    op.alter_column(
        "draftingeligibilityassessment",
        "algorithm_version",
        existing_type=sa.String(length=64),
        type_=sa.String(length=80),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_draftingeligibilityassessment_status",
        "draftingeligibilityassessment",
        "status IN ('eligible','blocked_missing_required_information',"
        "'insufficient_local_value','semantic_duplication',"
        "'consolidation_recommended','deferred','excluded_by_coverage',"
        "'stale_assessment')",
    )


def upgrade() -> None:
    if "draftingeligibilityassessment" not in _table_names():
        op.create_table(
            "draftingeligibilityassessment",
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("site_plan_id", sa.Integer(), nullable=False),
            sa.Column("planned_page_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("algorithm_version", sa.String(length=80), nullable=False),
            sa.Column("coverage_binding", sa.JSON(), nullable=False),
            sa.Column("expected_inventory_binding", sa.JSON(), nullable=False),
            sa.Column("planning_record_binding", sa.JSON(), nullable=False),
            sa.Column("approved_source_identities", sa.JSON(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column("local_value_findings", sa.JSON(), nullable=False),
            sa.Column("semantic_findings", sa.JSON(), nullable=False),
            sa.Column("reasons", sa.JSON(), nullable=False),
            sa.Column("assessed_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "status IN ('eligible','blocked_missing_required_information',"
                "'insufficient_local_value','semantic_duplication',"
                "'consolidation_recommended','deferred','excluded_by_coverage',"
                "'stale_assessment')",
                name="ck_draftingeligibilityassessment_status",
            ),
            sa.ForeignKeyConstraint(["planned_page_id"], ["plannedpage.id"]),
            sa.ForeignKeyConstraint(["site_plan_id"], ["siteplan.id"]),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "planned_page_id",
                name="uq_draftingeligibilityassessment_planned_page",
            ),
        )
    else:
        _repair_empty_legacy_assessment_table()
        required = {
            "website_id",
            "site_plan_id",
            "planned_page_id",
            "status",
            "algorithm_version",
            "evidence",
            "local_value_findings",
        }
        if not required.issubset(
            _column_names("draftingeligibilityassessment")
        ):
            raise RuntimeError(
                "Existing draftingeligibilityassessment table is incompatible."
            )
    _ensure_indexes(
        "draftingeligibilityassessment",
        (
            "website_id",
            "site_plan_id",
            "planned_page_id",
            "status",
            "algorithm_version",
            "assessed_at",
        ),
    )

    if "draftingeligibilitydisposition" not in _table_names():
        op.create_table(
            "draftingeligibilitydisposition",
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("site_plan_id", sa.Integer(), nullable=False),
            sa.Column("planned_page_id", sa.Integer(), nullable=False),
            sa.Column("assessment_id", sa.Integer(), nullable=False),
            sa.Column("decision", sa.String(), nullable=False),
            sa.Column("rationale", sa.String(), nullable=False),
            sa.Column("decided_by", sa.String(), nullable=False),
            sa.Column("accepted_exception", sa.Boolean(), nullable=False),
            sa.Column("decision_version", sa.Integer(), nullable=False),
            sa.Column("decided_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "decision IN "
                "('accepted','exception_approved','deferred','consolidate')",
                name="ck_draftingeligibilitydisposition_decision",
            ),
            sa.CheckConstraint(
                "decision_version >= 1",
                name="ck_draftingeligibilitydisposition_version",
            ),
            sa.ForeignKeyConstraint(
                ["assessment_id"], ["draftingeligibilityassessment.id"]
            ),
            sa.ForeignKeyConstraint(["planned_page_id"], ["plannedpage.id"]),
            sa.ForeignKeyConstraint(["site_plan_id"], ["siteplan.id"]),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "planned_page_id",
                name="uq_draftingeligibilitydisposition_planned_page",
            ),
        )
    required_disposition = {
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "assessment_id",
        "decision",
        "decision_version",
    }
    if not required_disposition.issubset(
        _column_names("draftingeligibilitydisposition")
    ):
        raise RuntimeError(
            "Existing draftingeligibilitydisposition table is incompatible."
        )
    _ensure_indexes(
        "draftingeligibilitydisposition",
        (
            "website_id",
            "site_plan_id",
            "planned_page_id",
            "assessment_id",
            "decision",
            "decided_at",
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table in (
        "draftingeligibilitydisposition",
        "draftingeligibilityassessment",
    ):
        if connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {table}")
        ).scalar_one():
            raise RuntimeError(
                "Downgrade blocked: durable drafting eligibility records exist."
            )
    op.drop_table("draftingeligibilitydisposition")
    op.drop_table("draftingeligibilityassessment")
