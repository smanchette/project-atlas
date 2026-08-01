"""Add semantic component registry and Website-scoped page compositions.

Revision ID: 20260801_0037
Revises: 20260731_0036
"""

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "20260801_0037"
down_revision = "20260731_0036"
branch_labels = None
depends_on = None


COMPONENTS = (
    ("website_header", "Orient visitors with approved Website identity and contact pathways.", ["business_identity", "brand", "website_identity", "contact_information"], "Recognize the business and reach it quickly.", ["all"], ["default"], ["Use a banner landmark.", "Give contact controls accessible names."]),
    ("primary_navigation", "Expose the operator-approved primary visitor journey.", ["navigation:primary"], "Navigate to the Website's principal destinations.", ["all"], ["default"], ["Use a labelled navigation landmark.", "Support keyboard operation and visible focus."]),
    ("utility_navigation", "Expose operator-approved utility destinations without competing with the primary journey.", ["navigation:utility"], "Reach supporting tasks efficiently.", ["all"], ["default"], ["Use a uniquely labelled navigation landmark."]),
    ("footer_navigation", "Repeat operator-approved supporting destinations at the end of the page.", ["navigation:footer"], "Continue the journey without returning to the page top.", ["all"], ["default"], ["Use a uniquely labelled navigation landmark."]),
    ("hero", "State the approved page purpose and primary next step.", ["draft:h1", "draft:intro", "contact_information"], "Understand the page and identify the primary action.", ["all"], ["default", "service", "local"], ["Use the only page-level heading.", "Keep actions keyboard accessible."]),
    ("content_section", "Explain one approved topic from the page draft.", ["draft:section"], "Gain the knowledge promised by the section heading.", ["all"], ["default", "muted"], ["Preserve logical heading order."]),
    ("service_summary", "Summarize an approved Service relationship.", ["service", "draft:section"], "Understand the relevant service and its value.", ["service", "county", "city_service"], ["default"], ["Use descriptive section headings."]),
    ("trust_license", "Present approved trust or licensing facts.", ["trust_information"], "Understand why the business is credible.", ["all"], ["default"], ["Do not communicate trust through color alone."]),
    ("destination_cards", "Present approved City or County destinations.", ["related_pages"], "Navigate to a relevant local destination.", ["service", "county", "city_service"], ["default"], ["Use descriptive link names."]),
    ("related_page_links", "Present approved contextual page relationships.", ["related_pages"], "Continue to a useful related page.", ["all"], ["default"], ["Describe link purpose without relying on surrounding text."]),
    ("faq", "Answer approved recurring customer questions.", ["draft:faq_items"], "Resolve common questions before taking the next step.", ["all"], ["default"], ["Controls expose expanded and collapsed state."]),
    ("contact_pathways", "Provide approved ways to contact the business.", ["website_identity", "contact_information"], "Choose a suitable contact method.", ["contact"], ["default"], ["Give every contact method an accessible name."]),
    ("media_placement", "Reserve an approved semantic role for governed media.", ["media_placement"], "Receive visual support without changing factual meaning.", ["all"], ["placeholder", "approved_media"], ["Require meaningful alternative-text intent."]),
    ("final_cta", "Close the page with its approved conversion purpose.", ["draft:title", "draft:call_to_action", "contact_information"], "Take the intended next action.", ["all"], ["default"], ["Use descriptive, keyboard-accessible actions."]),
    ("website_footer", "Close the page with approved business identity and trust information.", ["business_identity", "website_identity"], "Confirm the business identity and find supporting navigation.", ["all"], ["default"], ["Use a contentinfo landmark."]),
)


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
    if "semanticcomponentdefinition" not in _table_names():
        op.create_table(
            "semanticcomponentdefinition",
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("component_key", sa.String(length=80), nullable=False),
            sa.Column("contract_version", sa.Integer(), nullable=False),
            sa.Column("purpose", sa.String(), nullable=False),
            sa.Column("required_inputs", sa.JSON(), nullable=False),
            sa.Column("customer_outcome", sa.String(), nullable=False),
            sa.Column("compatible_page_types", sa.JSON(), nullable=False),
            sa.Column("supported_variants", sa.JSON(), nullable=False),
            sa.Column("accessibility_requirements", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.CheckConstraint("contract_version >= 1", name="ck_semanticcomponentdefinition_version"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("component_key", "contract_version", name="uq_semanticcomponentdefinition_key_version"),
        )
    required_definition_columns = {
        "created_at", "updated_at", "id", "component_key", "contract_version",
        "purpose", "required_inputs", "customer_outcome", "compatible_page_types",
        "supported_variants", "accessibility_requirements", "status",
    }
    if not required_definition_columns.issubset(_column_names("semanticcomponentdefinition")):
        raise RuntimeError("Existing semanticcomponentdefinition table is incompatible.")
    _ensure_indexes("semanticcomponentdefinition", ("component_key", "status"))
    now = datetime.now(UTC).replace(tzinfo=None)
    table = sa.table(
        "semanticcomponentdefinition",
        sa.column("created_at", sa.DateTime()), sa.column("updated_at", sa.DateTime()),
        sa.column("component_key", sa.String()), sa.column("contract_version", sa.Integer()),
        sa.column("purpose", sa.String()), sa.column("required_inputs", sa.JSON()),
        sa.column("customer_outcome", sa.String()), sa.column("compatible_page_types", sa.JSON()),
        sa.column("supported_variants", sa.JSON()), sa.column("accessibility_requirements", sa.JSON()),
        sa.column("status", sa.String()),
    )
    existing_contracts = {
        (row.component_key, row.contract_version)
        for row in op.get_bind().execute(
            sa.text(
                "SELECT component_key, contract_version "
                "FROM semanticcomponentdefinition"
            )
        )
    }
    missing_contracts = [
        {"created_at": now, "updated_at": now, "component_key": key, "contract_version": 1,
         "purpose": purpose, "required_inputs": inputs, "customer_outcome": outcome,
         "compatible_page_types": page_types, "supported_variants": variants,
         "accessibility_requirements": accessibility + [
             "Text and interactive controls must meet WCAG AA contrast.",
             "Remain usable at mobile, tablet, and desktop widths.",
         ], "status": "active"}
        for key, purpose, inputs, outcome, page_types, variants, accessibility in COMPONENTS
        if (key, 1) not in existing_contracts
    ]
    if missing_contracts:
        op.bulk_insert(table, missing_contracts)

    if "pagecomposition" not in _table_names():
        op.create_table(
            "pagecomposition",
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("site_plan_id", sa.Integer(), nullable=False),
            sa.Column("planned_page_id", sa.Integer(), nullable=False),
            sa.Column("generated_page_id", sa.Integer(), nullable=False),
            sa.Column("composition_version", sa.Integer(), nullable=False),
            sa.Column("generated_components", sa.JSON(), nullable=False),
            sa.Column("operator_decisions", sa.JSON(), nullable=False),
            sa.Column("source_snapshot", sa.JSON(), nullable=False),
            sa.Column("source_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
            sa.Column("decided_by", sa.String(), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint("composition_version >= 1", name="ck_pagecomposition_version"),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.ForeignKeyConstraint(["site_plan_id"], ["siteplan.id"]),
            sa.ForeignKeyConstraint(["planned_page_id"], ["plannedpage.id"]),
            sa.ForeignKeyConstraint(["generated_page_id"], ["generatedpage.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("planned_page_id", name="uq_pagecomposition_planned_page"),
            sa.UniqueConstraint("generated_page_id", name="uq_pagecomposition_generated_page"),
        )
    required_composition_columns = {
        "created_at", "updated_at", "id", "website_id", "site_plan_id",
        "planned_page_id", "generated_page_id", "composition_version",
        "generated_components", "operator_decisions", "source_snapshot",
        "source_hash", "status", "generated_at", "decided_by", "decided_at",
    }
    if not required_composition_columns.issubset(_column_names("pagecomposition")):
        raise RuntimeError("Existing pagecomposition table is incompatible.")
    _ensure_indexes(
        "pagecomposition",
        ("website_id", "site_plan_id", "planned_page_id", "generated_page_id", "source_hash", "status"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT COUNT(*) FROM pagecomposition")).scalar_one():
        raise RuntimeError("Downgrade blocked: durable page compositions exist.")
    op.drop_table("pagecomposition")
    op.drop_table("semanticcomponentdefinition")
