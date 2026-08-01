"""Add resumable Website draft-generation runs and items.

Revision ID: 20260731_0035
Revises: 20260730_0034
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0035"
down_revision = "20260730_0034"
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
    if "websitedraftgenerationrun" not in _table_names():
        op.create_table(
        "websitedraftgenerationrun",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_id", sa.Integer(), nullable=False),
        sa.Column("site_plan_id", sa.Integer(), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "eligibility_algorithm_version",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("manifest_snapshot", sa.JSON(), nullable=False),
        sa.Column("expected_count", sa.Integer(), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("generated_count", sa.Integer(), nullable=False),
        sa.Column("already_drafted_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("blocked_count", sa.Integer(), nullable=False),
        sa.Column("deferred_count", sa.Integer(), nullable=False),
        sa.Column("excluded_count", sa.Integer(), nullable=False),
        sa.Column("stale_count", sa.Integer(), nullable=False),
        sa.Column("consolidation_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("progress_message", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_resumed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('preparing','running','interrupted','completed',"
            "'completed_with_errors')",
            name="ck_websitedraftgenerationrun_status",
        ),
        sa.CheckConstraint(
            "expected_count >= 0 AND eligible_count >= 0 "
            "AND generated_count >= 0 AND already_drafted_count >= 0 "
            "AND skipped_count >= 0 AND blocked_count >= 0 "
            "AND deferred_count >= 0 AND excluded_count >= 0 "
            "AND stale_count >= 0 AND consolidation_count >= 0 "
            "AND error_count >= 0 AND processed_count >= 0",
            name="ck_websitedraftgenerationrun_counts",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_websitedraftgenerationrun_duration",
        ),
        sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
        sa.ForeignKeyConstraint(["site_plan_id"], ["siteplan.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "site_plan_id",
            "manifest_hash",
            name="uq_websitedraftgenerationrun_plan_manifest",
        ),
        )
    required_run = {
        "website_id",
        "site_plan_id",
        "manifest_hash",
        "eligibility_algorithm_version",
        "status",
        "manifest_snapshot",
        "processed_count",
    }
    if not required_run.issubset(
        _column_names("websitedraftgenerationrun")
    ):
        raise RuntimeError(
            "Existing websitedraftgenerationrun table is incompatible."
        )
    _ensure_indexes(
        "websitedraftgenerationrun",
        (
        "website_id",
        "site_plan_id",
        "manifest_hash",
        "eligibility_algorithm_version",
        "status",
        "started_at",
        ),
    )

    if "websitedraftgenerationitem" not in _table_names():
        op.create_table(
        "websitedraftgenerationitem",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("website_id", sa.Integer(), nullable=False),
        sa.Column("site_plan_id", sa.Integer(), nullable=False),
        sa.Column("planned_page_id", sa.Integer(), nullable=True),
        sa.Column("generated_page_id", sa.Integer(), nullable=True),
        sa.Column("inventory_key", sa.String(length=180), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page_type", sa.String(length=40), nullable=False),
        sa.Column("working_name", sa.String(), nullable=False),
        sa.Column(
            "manifest_classification", sa.String(length=40), nullable=False
        ),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=True),
        sa.Column("assessment_binding", sa.JSON(), nullable=False),
        sa.Column(
            "generated_content_hash", sa.String(length=64), nullable=True
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "manifest_classification IN ('eligible','blocked','excluded',"
            "'deferred','stale','consolidation_recommended')",
            name="ck_websitedraftgenerationitem_classification",
        ),
        sa.CheckConstraint(
            "outcome IN ('pending','generated','already_drafted','blocked',"
            "'deferred','excluded','stale','consolidation_recommended',"
            "'unsupported','error')",
            name="ck_websitedraftgenerationitem_outcome",
        ),
        sa.CheckConstraint(
            "ordinal >= 1 AND attempt_count >= 0",
            name="ck_websitedraftgenerationitem_counts",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["websitedraftgenerationrun.id"]
        ),
        sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
        sa.ForeignKeyConstraint(["site_plan_id"], ["siteplan.id"]),
        sa.ForeignKeyConstraint(["planned_page_id"], ["plannedpage.id"]),
        sa.ForeignKeyConstraint(["generated_page_id"], ["generatedpage.id"]),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["draftingeligibilityassessment.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "inventory_key",
            name="uq_websitedraftgenerationitem_run_inventory",
        ),
        )
    required_item = {
        "run_id",
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
        "inventory_key",
        "manifest_classification",
        "outcome",
        "assessment_binding",
    }
    if not required_item.issubset(
        _column_names("websitedraftgenerationitem")
    ):
        raise RuntimeError(
            "Existing websitedraftgenerationitem table is incompatible."
        )
    _ensure_indexes(
        "websitedraftgenerationitem",
        (
        "run_id",
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
        "inventory_key",
        "page_type",
        "manifest_classification",
        "outcome",
        "assessment_id",
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT COUNT(*) FROM websitedraftgenerationrun")
    ).scalar_one():
        raise RuntimeError(
            "Downgrade blocked: durable Website draft-generation runs exist."
        )
    op.drop_table("websitedraftgenerationitem")
    op.drop_table("websitedraftgenerationrun")
